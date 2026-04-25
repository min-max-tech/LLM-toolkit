# Auth & Secrets Redesign — Google SSO + SOPS + Bounded Hermes

**Status:** Design (working draft on `feat/auth-redesign`).
**Date:** 2026-04-25.
**Lifecycle:** This document lives on the feature branch only. It is dropped before
the implementation work merges to `main`, in keeping with the project's
"main = current state" docs policy (see commit `91246c3`).

---

## Goals

- Replace the manual paste-the-bearer-token dashboard login with Google SSO
  bound to a single Gmail allowlist.
- Single sign-in covers all web UIs: dashboard, open-webui, n8n,
  hermes-dashboard, comfyui.
- Encrypt all secrets at rest in a form that is safe to commit to a public
  repository.
- Bound Hermes' filesystem and Docker-socket reach so a prompt-injected Hermes
  cannot exfiltrate high-value tokens.
- Preserve Hermes' role as the main controller of the stack: it can still
  drive privileged container operations, just through a narrower API.

## Non-goals

- Multi-tenant auth, RBAC, role hierarchies, federation. This is a single-user
  homelab.
- Removing Tailscale. Tailscale stays as the network gate.
- Public-internet exposure of any service. Tailscale is the only ingress.
- Replacing internal service-to-service tokens (`LITELLM_MASTER_KEY`,
  `OPS_CONTROLLER_TOKEN`, `DASHBOARD_AUTH_TOKEN`). Those continue to gate
  Docker-network traffic.
- Migrating to a heavyweight identity provider (Keycloak, Authelia full mode,
  Pomerium).

---

## Architecture

### Two gates

- **Tailscale (network):** every device that wants to reach the stack must be
  on the user's tailnet. No public ingress, no Tailscale Funnel, no Cloudflare
  Tunnel.
- **Google OIDC (identity):** a single email allowlist (`YOUR_ALLOWLIST_EMAIL`
  in placeholders) is the only account that can complete the OIDC dance.

Either gate failing closed denies access. Both must succeed for any browser
request to reach an upstream UI.

### Single host, single hostname, path-mounted UIs

- One Caddy container, listening **only on the Tailscale interface**
  (the `tailscale0` IP, not `0.0.0.0`).
- One hostname (`ordo.<tailnet>.ts.net`) with all UIs under one cookie scope:
  - `/dash/`   → `dashboard:8080`
  - `/chat/`   → `open-webui:8080`
  - `/n8n/`    → `n8n:5678`
  - `/hermes/` → `hermes-dashboard:9119`
  - `/comfy/`  → `comfyui:8188`
- Single session cookie covers all five — sign in once, every UI is unlocked.

### Identity layer

- One `oauth2-proxy` container handles Google OIDC.
- Caddy uses `forward_auth` on every protected route, calling
  `oauth2-proxy:4180/oauth2/auth`.
- oauth2-proxy validates `email == <allowlist>`, sets a 24-hour httpOnly cookie
  scoped to `.<tailnet>.ts.net`.

### Internal traffic unchanged

- Container-to-container HTTP (orchestration-mcp → dashboard,
  ops-controller → docker daemon, Hermes → model-gateway) keeps using existing
  bearer tokens.
- The only thing the redesign removes from the **browser** path is the manual
  paste-the-token UX.

---

## Components & per-service changes

### New containers (2)

**`caddy`** (`caddy:2-alpine`)
- Single Caddyfile. Listens on the tailnet IP at `:443`.
- TLS via `tailscale cert` (sidecar pattern) renewed weekly. Fallback: Caddy
  internal CA with per-device CA trust.
- `forward_auth` directive on every protected location.
- Strips `/dash/`, `/chat/`, etc. before forwarding to the upstream.
- Bypass list for n8n callbacks: `/n8n/rest/oauth2-credential/callback`,
  `/n8n/webhook/*` (these need to be reachable without SSO so external services
  can call back).

**`oauth2-proxy`** (`quay.io/oauth2-proxy/oauth2-proxy:latest`)
- Google OIDC provider.
- `--authenticated-emails-file=/etc/oauth2-proxy/emails.txt` — single placeholder
  line `YOUR_ALLOWLIST_EMAIL` (replaced from SOPS-decrypted secrets at boot).
- `--cookie-secret`, `--client-id`, `--client-secret` from
  SOPS-decrypted secrets.
- `--cookie-domain=.<tailnet>.ts.net`, `--cookie-secure=true`,
  `--cookie-samesite=lax`, `--cookie-expire=24h`.
- `--reverse-proxy=true` to trust Caddy's `X-Forwarded-*` headers.
- `--whitelist-domain=.<tailnet>.ts.net` so the redirect back from Google
  resolves cleanly.

### Modified services

**`dashboard`** (`dashboard/app.py`)
- `_verify_auth()` (currently at `dashboard/app.py:97-105`) gains a "trust
  proxy headers" mode: when the request comes from the proxy network, treat
  `X-Forwarded-Email` as the authenticated identity. Bearer-token mode stays
  for orchestration-mcp/internal calls.
- New env: `DASHBOARD_TRUST_PROXY_HEADERS=true`,
  `DASHBOARD_TRUSTED_PROXY_NET=<caddy network CIDR>`.
- Drop the `8080:8080` host-port publish. Reachable only via Caddy.
- UI reads `X-Forwarded-Email` for "who am I" badges and audit logging.

**`open-webui`**, **`n8n`**, **`hermes-dashboard`**, **`comfyui`**
- Drop host-port publishes (`3000:8080`, `5678:5678`, `9119:9119`, `8188:8188`).
- Reachable only via Caddy.
- Open WebUI: keep `WEBUI_AUTH=False`. Caddy is the gate; per-user accounts
  inside Open WebUI add no value for a single-user setup.
- n8n: continue to bypass `forward_auth` on the OAuth callback and webhook
  paths so external integrations and OAuth providers can still call in.

**`ops-controller`** (the privileged surface)
- Adds endpoints for the verbs Hermes used to reach via the raw Docker socket:
  - `GET /containers` — list with status
  - `GET /containers/{name}/logs?tail=N&since=...` — read-only log access
  - `POST /containers/{name}/restart`
  - `POST /compose/up`, `POST /compose/down`, `POST /compose/restart`
    (specific service or whole stack)
  - `POST /models/pull` (already exists)
- **No** `docker exec` endpoint. Arbitrary shell-into-container is the
  prompt-injection escape hatch and is removed by design. If Hermes legitimately
  needs to do something inside a container, it gets a named verb, not arbitrary
  shell.
- Each privileged endpoint emits one structured audit log line:
  `{ts, caller, action, target, result}` to `data/ops-controller/audit.jsonl`.
  Append-only JSONL with a 50MB rotation cap (rename to `audit.1.jsonl` when
  exceeded). `tail -f`-friendly; greppable.
- All gated by existing `OPS_CONTROLLER_TOKEN` bearer.

**`hermes-gateway`** + **`hermes-dashboard`**
- **Remove** `volumes: /var/run/docker.sock:/var/run/docker.sock` and
  `group_add: ["0"]`.
- Hermes' Docker-using MCP tools rewritten to call ops-controller HTTP endpoints
  with `OPS_CONTROLLER_TOKEN`. A thin `ops-client` module wraps the calls.
- Keep `/workspace` and
  `${BASE_PATH:-.}/..:${HERMES_HOST_DEV_MOUNT:-/projects}:rw` mounts (current
  behavior preserved per the user's "Hermes is the main controller" requirement).
- Move secrets Hermes does not actually use (Tavily, GitHub PAT, HF, Civitai)
  out of its env block — only services that actually use those tokens get them.

### Removed

- The dashboard's "paste your token" UX.
- Hermes' raw Docker socket access (replaced by ops-controller HTTP API).
- Browser-side reachability of `DASHBOARD_AUTH_TOKEN` and
  `OPS_CONTROLLER_TOKEN`.

### Network topology

- New Docker network `proxy-net`: `caddy`, `oauth2-proxy`.
- `caddy` is dual-homed: `proxy-net` plus the existing `frontend` network so
  it can reach upstream services.
- Internal-only services lose their host-port publishes.

---

## Data flows

### A. First-time browser login

```
Browser (on tailnet) → https://ordo.<tailnet>.ts.net/dash/
  → Caddy: forward_auth check
  → oauth2-proxy: no session cookie → 302 to /oauth2/start
  → Google OIDC consent screen
  → Google → /oauth2/callback?code=...
  → oauth2-proxy: exchange code, validate email == allowlist
  → Set httpOnly cookie (24h, signed) for .<tailnet>.ts.net
  → 302 back to /dash/
  → Caddy: forward_auth passes, strips /dash/ prefix
  → dashboard:8080 receives request with X-Forwarded-Email header
  → dashboard renders UI
```

### B. Subsequent browser request (any UI)

```
Browser → https://ordo.<tailnet>.ts.net/{dash,chat,n8n,hermes,comfy}/...
  → Caddy: forward_auth
  → oauth2-proxy: cookie valid → 202 Accepted, sets X-Forwarded-Email
  → Caddy: strips path prefix, proxies to upstream
  → upstream serves
```

Single cookie covers all five UIs (same domain, different paths). No re-auth
between them.

### C. Hermes takes a privileged action

```
Hermes (e.g., user asked it to restart a container)
  → ops-client.post("http://ops-controller:9000/containers/foo/restart",
                    headers={"Authorization": f"Bearer {OPS_CONTROLLER_TOKEN}"})
  → ops-controller verifies token, calls docker SDK
  → emits audit line: {ts, action: "container.restart", target: "foo", result: "ok"}
  → 200 → Hermes reports success
```

Hermes never touches `/var/run/docker.sock` directly.

### D. Stack startup with encrypted secrets

```
make up
  → check ~/.config/sops/age/keys.txt exists; abort if missing
  → sops -d secrets/.env.sops > ~/.ai-toolkit/runtime/.env  (chmod 600)
  → for each high-value token:
      sops -d secrets/<name>.sops > ~/.ai-toolkit/runtime/secrets/<name>
  → docker compose --env-file ~/.ai-toolkit/runtime/.env up -d
  → high-value tokens loaded via Docker `secrets:` (mounted at /run/secrets/<name>)
  → containers start
```

Runtime files stay in place between compose cycles so Hermes can drive
`restart` / `up` / `down` via ops-controller without needing the age key. Files
live at `~/.ai-toolkit/runtime/` — outside both `/workspace` and the
`HERMES_HOST_DEV_MOUNT` bind-mount, so a prompt-injected Hermes cannot `cat`
them.

The age key is the single thing the human keeps in their hands. After a host
reboot, the human runs `make up` once with the key present; from then on,
Hermes-driven ops work without the key.

### Identity propagation

- oauth2-proxy stamps `X-Forwarded-Email`, `X-Forwarded-User`,
  `X-Forwarded-Preferred-Username` on every request.
- Dashboard reads `X-Forwarded-Email` for "who am I" UI bits and audit logging
  — replaces today's anonymous-bearer-token model.

---

## Secrets handling

### File layout

```
<repo>/secrets/                          # public, encrypted, committable
├── .env.sops                            # SOPS-encrypted .env (env-form tokens)
├── discord_token.sops                   # high-value, file-form, encrypted
├── github_pat.sops
├── hf_token.sops
├── tavily_key.sops
├── civitai_token.sops
└── .sops.yaml                           # SOPS rules / age recipients

~/.config/sops/age/keys.txt              # age private key. NEVER committed.
                                         # chmod 600. NOT in any container.

~/.ai-toolkit/runtime/                   # outside repo, outside all bind-mounts
├── .env                                 # decrypted env-form (chmod 600)
└── secrets/
    ├── discord_token                    # decrypted high-value tokens (file-form)
    ├── github_pat
    ├── hf_token
    ├── tavily_key
    └── civitai_token
```

### Form-by-form classification

| Token | Form | Rationale |
|-------|------|-----------|
| `LITELLM_MASTER_KEY` | env (in `.env.sops`) | Internal; never leaves Docker network |
| `DASHBOARD_AUTH_TOKEN` | env | Same |
| `OPS_CONTROLLER_TOKEN` | env | Same |
| `THROUGHPUT_RECORD_TOKEN` | env | Same |
| `OAUTH2_PROXY_COOKIE_SECRET` | env | New; oauth2-proxy session signing |
| `OAUTH2_PROXY_CLIENT_ID` | env | Google OIDC |
| `OAUTH2_PROXY_CLIENT_SECRET` | env | Google OIDC |
| `DISCORD_BOT_TOKEN` | Docker secret (file) | High-value. Not visible in `docker inspect` |
| `GITHUB_PERSONAL_ACCESS_TOKEN` | Docker secret (file) | Same |
| `HF_TOKEN` | Docker secret (file) | Same |
| `TAVILY_API_KEY` | Docker secret (file) | Same |
| `CIVITAI_TOKEN` | Docker secret (file) | Same |

In compose, file-form secrets attach only to services that need them
(`hermes-gateway` for Discord, `mcp-gateway` for GitHub PAT and Tavily,
`gguf-puller` for HF, etc.) via Docker `secrets:` blocks. Services read via the
`_FILE` convention: `DISCORD_BOT_TOKEN_FILE=/run/secrets/discord_token`.

### Why two forms?

A token passed as an env var is visible to anyone with Docker daemon access:
`docker inspect <container> | grep TOKEN` shows the value. A token mounted via
Docker secrets shows only the secret reference, not the value. Today Hermes
has the docker socket; in the redesign it does not, but the highest-value
tokens get file-form anyway as defense-in-depth.

### Key management

There is exactly one thing to safeguard: `~/.config/sops/age/keys.txt`.

- Lose it → cannot decrypt own secrets. Back up to a password manager
  (1Password / Bitwarden) at setup time.
- Leak it → whoever has it can decrypt the public repo's `secrets/`. Treat
  it like a master password.
- chmod 600. Never in a container. Never committed. Never sent over chat.

For multi-machine setups: generate a separate age keypair on each machine,
add the new public key as a recipient in `.sops.yaml`, re-encrypt the
secrets. Both machines can decrypt independently with their own private keys.

---

## Failure modes and mitigations

| Failure | Effect | Mitigation |
|---------|--------|------------|
| Google OIDC outage | Cannot log in via SSO | Document a host-local bypass: a `localhost`-bound listener on the Caddy host (not on the tailnet IP) reaches the dashboard's bearer-token mode directly. Run from the host shell when SSO is down. |
| oauth2-proxy crashes | All web UIs return 401 / redirect loops | Caddy returns a static "auth temporarily unavailable" page when oauth2-proxy is unhealthy, instead of redirecting to a broken endpoint. Restart via `docker compose restart oauth2-proxy`. |
| age key lost | Cannot decrypt own secrets, cannot bring stack up after reboot | Offline copy in 1Password / Bitwarden. Recovery procedure documented in `docs/runbooks/secrets.md`. |
| age key leaked | Anyone with the key can decrypt all SOPS-encrypted secrets in the repo | Rotate every encrypted secret, generate a new age keypair, re-encrypt with the new public key, force-push the new `secrets/` contents. Detection: monitor for unusual access patterns or `atime` jumps on the key file. |
| Discord DNS fails inside Hermes | No Discord interactions; stack stays up; Hermes loops on reconnect | `discord.py` already handles reconnect. Long-term: pin Hermes' DNS to `1.1.1.1` / `8.8.8.8` in compose instead of relying on Docker Desktop's resolver. |
| Hermes prompt-injected to leak tokens | High-value (file-form) tokens are not in env, not on Hermes' bind-mounted disk. Low-value (env-form) tokens are internal-only. | Token classification + Docker socket removal. Audit log shows any unusual ops-controller calls Hermes makes. |
| ops-controller compromised | All compose verbs accessible to attacker | Smallest attack target; structured audit log; no `exec` endpoint. Mitigation: rate-limit at Caddy/oauth2-proxy on calls reaching it from the browser side; Hermes-side calls audited. |
| `OPS_CONTROLLER_TOKEN` leaks | Service-to-service privilege bypass | `make rotate-internal-tokens` regenerates `LITELLM_MASTER_KEY`, `DASHBOARD_AUTH_TOKEN`, `OPS_CONTROLLER_TOKEN` simultaneously, re-encrypts via SOPS, restarts dependent services. |
| Tailscale ACL misconfigured (unauthorized device on tailnet) | Device can attempt SSO but blocked by allowlist | Defense-in-depth holds. Tighten ACL by tagging the host and requiring tag-owner devices only. |
| Cookie secret leaks | Attacker can forge sessions | Rotate `OAUTH2_PROXY_COOKIE_SECRET` (32+ random bytes), restart oauth2-proxy. All existing sessions invalidate. |
| Caddy or proxy drops `X-Forwarded-Email` | Dashboard would otherwise see no identity | **Fail closed**: dashboard responds 401 if `DASHBOARD_TRUST_PROXY_HEADERS=true` is set but the header is missing. Never silently accept anonymous requests. |
| New unauthenticated endpoints accidentally added to dashboard | Bypass of SSO | Dashboard middleware lists *required-auth* routes by default-deny pattern (allowlist of public endpoints), not by per-route opt-in. |

---

## Testing

### Unit / integration

- `dashboard/test_auth.py`: `_verify_auth()` correctly trusts `X-Forwarded-Email`
  only when proxy network is configured AND request originates there; rejects
  spoofed header from other networks.
- `ops-controller/test_audit.py`: every privileged endpoint emits exactly one
  well-formed audit line; rotation triggers at 50MB.
- `ops-controller/test_endpoints.py`: each new verb
  (`/containers/list`, `/containers/{name}/logs`,
  `/containers/{name}/restart`, `/compose/up|down|restart`) round-trips
  correctly and rejects without `OPS_CONTROLLER_TOKEN`.
- `hermes/test_ops_client.py`: the new `ops-client` module retries on
  transient failures, includes the bearer token, and surfaces
  ops-controller errors faithfully.

### Stack-level smoke tests

1. **Cold start with secrets.** From a fresh checkout: `make up`. Assert:
   stack healthy. `docker inspect <container>` for any service that holds a
   high-value token shows only the secret reference, never the plaintext.
2. **First-time login.** Hit `https://ordo.<tailnet>.ts.net/dash/` from a
   browser. Assert: redirect to Google → after success, cookie set with 24h
   expiry, dashboard renders.
3. **Cross-UI session.** After login at `/dash/`, navigate to `/chat/`,
   `/n8n/`, `/hermes/`, `/comfy/`. Assert: no re-auth prompt at any of them.
4. **Allowlist deny.** Sign in with a non-allowlisted Google account. Assert:
   oauth2-proxy 403s after the OIDC dance; user does not see any UI.
5. **Hermes ops-controller round-trip.** Ask Hermes to restart a service.
   Assert: ops-controller audit log shows the action; container restarted;
   no reference to `/var/run/docker.sock` in Hermes' logs.
6. **Bind-mount sealing.** From inside Hermes:
   `cat /workspace/.env`, `cat /c/dev/AI-toolkit/.env`. Assert: file does
   not exist (it lives at `~/.ai-toolkit/runtime/.env`, outside the mount).
7. **Token revocation.** Rotate `OAUTH2_PROXY_COOKIE_SECRET`. Assert: existing
   sessions invalidate, next request → re-auth.
8. **Tailscale-only.** From a non-tailnet device:
   `curl -k https://ordo.<tailnet>.ts.net/`. Assert: connection refused
   / no route to host.

### Pre-ship checklist

- [ ] `git log -p --all -- .env` confirms no historical commit ever included
      plaintext `.env`.
- [ ] `git log -p --all | grep -E "(github_pat_|hf_[A-Za-z0-9]{20,}|tvly-)"`
      finds no matches in tracked history. (Public token-format prefixes only;
      add provider-specific patterns as needed for any token type that lacks
      a stable prefix, e.g. Discord bot tokens or Civitai keys.)
- [ ] If either above finds anything: **rotate every found token before any
      of this lands** — Discord bot reset, GitHub PAT revoke, HF regen,
      Tavily regen, Civitai regen. The redesign starts from clean tokens.
- [ ] Google OAuth client created in GCP console; client ID + secret captured
      and encrypted into `secrets/.env.sops`.
- [ ] age keypair generated and backed up to a password manager.
- [ ] Tailscale `tailscale cert` issued for the chosen hostname.
- [ ] `data/ops-controller/audit.jsonl` exists and is appended on every
      privileged call.

---

## Open questions / decisions to revisit

- **Caddy TLS issuance.** `tailscale cert` (cleanest, ties cert lifecycle to
  tailnet) vs Caddy internal CA (simpler, requires per-device CA trust).
  Default: `tailscale cert`. Revisit if cert renewal becomes a pain.
- **Open WebUI internal user system.** Kept disabled (proxy is the gate).
  Revisit only if multi-user chat history becomes a goal.
- **Migrate `LITELLM_MASTER_KEY` to file-form.** Currently env. Cost: small.
  Benefit: defense-in-depth uniformity. Defer.
- **Cookie lifetime.** 24h chosen. Shorter (e.g. 8h) makes session theft window
  tighter but increases prompts. Revisit if theft becomes a real concern.
- **Fallback bypass for Google OIDC outage.** Host-local bearer-token reach is
  documented as a workaround. Acceptable for personal use; revisit if the stack
  ever has a second user.

---

## Lifecycle of this document

This spec lives only on `feat/auth-redesign`. It is **not** to be merged to
`main`. Two-step lifecycle:

1. While this branch is active, the spec is the working source of truth and is
   reviewable on GitHub via the branch URL.
2. When implementation is complete and ready to ship, the implementation PR's
   final rebase or squash drops the spec's commits so `main` only sees the
   code/config changes that resulted from this design.

This honors the project's stated docs policy from commit `91246c3`:
"main = current state, not the planning trail that produced it."
