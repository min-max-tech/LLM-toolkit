# OpenClaude Self-Serve Install — Design

**Date:** 2026-04-16
**Status:** Draft, pending user approval
**Author:** Brainstorming session, Cam Lynch + Claude

## Summary

Make OpenClaude (`@gitlawb/openclaude`, the open-source Claude Code fork that targets any LLM provider) installable on any tailnet device with a single one-liner copied from the host's dashboard. Each device's OpenClaude is auto-configured to talk to the host's local model gateway (LiteLLM → llama.cpp serving Gemma 4 31B GGUF) and the host's MCP gateway, with no manual config and no impact on a co-installed Claude Code.

As part of the same change, replace the GGUF-basename model identity used by every consumer in the stack (OpenWebUI, OpenClaw, etc.) with a single canonical identity `local-chat` (and `local-embed`), so swapping the loaded GGUF on the host is invisible to all downstream services including OpenClaude.

## Goals

- One-liner install on Windows (PowerShell) and macOS (bash) tailnet devices
- Each device's OpenClaude points at the host's model gateway and MCP gateway by default
- Swapping the loaded GGUF on the host requires no action on remote devices
- Co-installed Claude Code on the same device is never touched
- Re-running the installer is a safe re-sync, not a re-install

## Non-Goals

- Linux desktop support (deferrable; same script body would work, just not in initial scope)
- iOS / Android (OpenClaude is a Node CLI; phones get nothing)
- Code-signed `.msi` / `.pkg` packaging (one-liner only)
- Per-device authentication or revocation (tailnet-only trust is sufficient)
- Sharing OpenClaude workspace across devices
- Auto-update on a schedule (re-run installer to update)
- Uninstall script
- Auto-start daemon on device boot
- Bootstrapping Node or ripgrep on the device (script detects and instructs; does not install)

## Architecture

```
┌─ Dashboard (host, port 8080)                  ┌─ Remote tailnet device ──┐
│                                               │                          │
│  /install/openclaude.ps1   ◀─── one-liner ────│                          │
│  /install/openclaude.sh    ◀─── (curl/irm) ──▶│ bash/pwsh runs:          │
│  /api/openclaude/preview        (UI only)     │  1. node + ripgrep check │
│                                               │  2. npm i -g @gitlawb/   │
│  Renders self-contained script via Jinja2     │     openclaude           │
│  from current host state:                     │  3. write               │
│   • host tailnet hostname                     │     ~/.openclaude/       │
│     (TS_HOSTNAME or Host-header fallback)     │       .claude.json,      │
│   • LITELLM_MASTER_KEY                        │       settings.json     │
│   • model-gateway port (11435)                │  4. write wrapper       │
│   • mcp-gateway port (8811)                   │     openclaude-local    │
│   • blog-mcp port (3500), if reachable        │     to PATH              │
│                                               │  5. print "run          │
│                                               │     openclaude-local"   │
└───────────────────────────────────────────────┴──────────────────────────┘
```

### New files

- `dashboard/routes_openclaude.py` — FastAPI router. Three GET routes: `/install/openclaude.ps1`, `/install/openclaude.sh`, `/api/openclaude/preview`.
- `dashboard/openclaude_install.py` — pure logic module: hostname resolution, MCP reachability preflight, config rendering. Testable in isolation.
- `dashboard/templates/openclaude_install.ps1.j2` — PowerShell install script template.
- `dashboard/templates/openclaude_install.sh.j2` — POSIX install script template.
- `dashboard/templates/openclaude_claude_json.j2` — embedded literal that both scripts emit as `~/.openclaude/.claude.json`.
- `dashboard/templates/openclaude_wrapper.cmd.j2`, `dashboard/templates/openclaude_wrapper.sh.j2` — wrapper script templates.
- Tests under `tests/dashboard/test_openclaude_install.py`.

### Touched files

- `model-gateway/litellm_config.yaml` — replace per-GGUF templated entries with two stable entries: `local-chat`, `local-embed`. Drop `__CHAT_MODEL__` and `__EMBED_MODEL__` placeholders.
- `model-gateway/entrypoint.sh` — only substitute `__MASTER_KEY__` now. Verify `__CHAT_MODEL__` / `__EMBED_MODEL__` substitution code is removed (currently uses `sed`).
- `docker-compose.yml` — `mcp-gateway` service gets `ports: ["${MCP_GATEWAY_PORT:-8811}:8811"]` published by default. Also remove the `# No host port by default (backend-only per PRD M6)` comment.
- `overrides/mcp-expose.yml` — delete (or leave a stub with a deprecation comment for migration).
- `dashboard/app.py` — `app.include_router(openclaude_router)`. Simplify the `/api/active-model` flow (lines ~400-462): drop the OpenWebUI default + OpenClaw config + openclaw-gateway restart steps, since every consumer now uses `local-chat` and doesn't care about the loaded GGUF basename. Keep the `LLAMACPP_MODEL` env update + llamacpp recreate, and keep `OPENCLAW_CONTEXT_WINDOW` metadata logic.
- `dashboard/static/index.html` — new "Add OpenClaude to a device" card with OS toggle, one-liner display, copy button, MCP reachability status row.
- `data/openclaw/openclaw.json` — `agents.defaults.model.primary: "gateway/local-chat"`; replace the `id: "google_gemma-4-31B-it-Q4_K_M.gguf"` model entry with `id: "local-chat"`.
- `.env` — `OPEN_WEBUI_DEFAULT_MODEL=local-chat`, `DEFAULT_MODEL=local-chat`. `LLAMACPP_MODEL` stays as the GGUF basename (only llamacpp container reads it).
- `.env.example` — same changes for documentation.
- Any test files in `tests/` referencing GGUF-basename model identifiers — update to `local-chat`/`local-embed`. (Scan during implementation.)
- `docs/` references to `OPEN_WEBUI_DEFAULT_MODEL` setup, model swap procedures — update to reflect canonical name.

## Components in detail

### Single canonical model identity

**Principle:** `local-chat` and `local-embed` are the only names any consumer ever uses for the host's chat / embed model. The loaded GGUF on disk is an internal detail of the llamacpp container.

Why this works: llama.cpp's OpenAI-compat server only loads the model specified at startup (via `-m` flag). The model name in `/v1/chat/completions` requests is essentially ignored — llama.cpp returns whatever's loaded regardless. So LiteLLM can advertise `local-chat`, forward `openai/local-chat` downstream, and llama.cpp serves Gemma (or whatever the current GGUF is) without complaint.

**New `model-gateway/litellm_config.yaml`:**

```yaml
model_list:
  - model_name: "local-chat"
    litellm_params:
      model: "openai/local-chat"
      api_base: "http://llamacpp:8080/v1"
      api_key: "local"
      timeout: 1800
      stream_timeout: 1800

  - model_name: "local-embed"
    litellm_params:
      model: "openai/local-embed"
      api_base: "http://llamacpp-embed:8080/v1"
      api_key: "local"

general_settings:
  master_key: "__MASTER_KEY__"

litellm_settings:
  request_timeout: 1800
  stream_timeout: 1800
```

**Verification after change:** `curl http://<host>:11435/v1/models -H "Authorization: Bearer local"` should return exactly two entries: `local-chat`, `local-embed`. No GGUF-basename entries.

**Side benefit — `/api/active-model` simplifies:** The current flow updates `LLAMACPP_MODEL` → recreates llamacpp → updates `DEFAULT_MODEL` → updates `OPEN_WEBUI_DEFAULT_MODEL` → updates `data/openclaw/openclaw.json` → restarts openclaw-gateway. After this change: update `LLAMACPP_MODEL` → recreate llamacpp. Done. Every consumer already calls `local-chat` and is oblivious to the swap.

**Caveat:** Some clients echo `response.model` to the user. With `local-chat` as the advertised name, OpenWebUI's chat header will show "local-chat" instead of the GGUF name. The actual loaded GGUF remains visible via `/api/llamacpp/active`.

### Dashboard endpoints

**`GET /install/openclaude.ps1`** and **`GET /install/openclaude.sh`** — public, no auth. Each returns `Content-Type: text/plain` with `Cache-Control: no-store`. Body is the rendered install script with the host's tailnet hostname, master key, MCP gateway URL, and (conditionally) blog MCP URL substituted.

**`GET /api/openclaude/preview`** — public, JSON. Drives the dashboard UI without re-fetching the script:

```json
{
  "host": "your-machine.your-tailnet.ts.net",
  "model_gateway_url": "http://your-machine.your-tailnet.ts.net:11435/v1",
  "mcp_gateway_url": "http://your-machine.your-tailnet.ts.net:8811/mcp",
  "blog_mcp_reachable": true,
  "model": "local-chat",
  "one_liner_ps1": "irm http://your-machine.your-tailnet.ts.net:8080/install/openclaude.ps1 | iex",
  "one_liner_sh":  "curl -fsSL http://your-machine.your-tailnet.ts.net:8080/install/openclaude.sh | bash"
}
```

### Hostname resolution

Order, implemented in `dashboard/openclaude_install.py`:

1. `TS_HOSTNAME` env var if set (explicit override)
2. `request.headers["Host"]` minus port (works because the user opened the dashboard from a tailnet URL)
3. If both resolve to `localhost` / `127.0.0.1` / similar, return a sentinel that the install endpoint converts to HTTP 503 with a remediation message ("set TS_HOSTNAME"). The dashboard UI card detects this and shows a yellow warning instead of an unusable one-liner.

No `socket.getfqdn()` fallback — too unreliable on Windows tailnet hosts.

### MCP reachability preflight

Before rendering each install script, `dashboard/openclaude_install.py` does a preflight `GET http://host.docker.internal:3500/mcp` (or equivalent) with a short timeout (2s) from inside the dashboard container. Result is cached for 10s to avoid hammering the blog server.

- Reachable → blog MCP entry included with `BLOG_MCP_API_KEY` from env.
- Unreachable → blog entry omitted entirely. Script logs "blog MCP not configured on host, skipping" during install.
- Cache TTL ensures a transient blog-server outage during install doesn't poison subsequent installs for long.

`mcp-gateway` and `model-gateway` are assumed reachable (they're docker services in the compose network and the dashboard always has access). No preflight needed.

### Per-device file layout

```
$HOME/.openclaude/                       ← CLAUDE_CONFIG_DIR target
  .claude.json                           ← mcpServers entries
  settings.json                          ← { "model": "local-chat" }
$HOME/openclaude-workspace/              ← per-device local-tools root
$HOME/.local/bin/openclaude-local        ← wrapper (macOS); chmod +x
%LOCALAPPDATA%\openclaude\openclaude-local.cmd  ← wrapper (Windows)
```

**Why a separate `$HOME/.openclaude/` and not `~/.claude/`:** OpenClaude is a Claude Code fork that reads `~/.claude.json` and `~/.claude/settings.json` by default. If the user has Claude Code installed, writing those paths would clobber Claude Code's config. OpenClaude honors the `CLAUDE_CONFIG_DIR` env var to relocate, so the wrapper sets `CLAUDE_CONFIG_DIR=$HOME/.openclaude` before exec'ing openclaude. Claude Code is never touched.

**Why a wrapper script and not env vars in shell profile:** OpenClaude reads `OPENAI_BASE_URL` and `OPENAI_API_KEY` at process launch. Setting these in `~/.bashrc` / `~/.zshrc` / PowerShell profile would also affect any other tool that reads them (e.g., the OpenAI Python SDK). The wrapper sets them only for OpenClaude.

### Generated `~/.openclaude/.claude.json`

```json
{
  "mcpServers": {
    "gateway": {
      "transport": "http",
      "url": "http://your-machine.your-tailnet.ts.net:8811/mcp"
    },
    "blog": {
      "transport": "http",
      "url": "http://your-machine.your-tailnet.ts.net:3500/mcp",
      "headers": { "x-api-key": "<BLOG_MCP_API_KEY value>" }
    },
    "local-tools": {
      "transport": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "<resolved abs path of $HOME/openclaude-workspace>"
      ]
    }
  }
}
```

The blog entry is omitted entirely if the dashboard's preflight failed. The local-tools path is resolved by the install script at install time (not by the template), so each device's path is correct for that device.

### Wrapper script bodies

**POSIX (`openclaude-local`):**
```sh
#!/usr/bin/env sh
export CLAUDE_CONFIG_DIR="$HOME/.openclaude"
export OPENAI_BASE_URL="http://your-machine.your-tailnet.ts.net:11435/v1"
export OPENAI_API_KEY="local"
exec openclaude --model local-chat "$@"
```

**Windows (`openclaude-local.cmd`):**
```cmd
@echo off
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.openclaude"
set "OPENAI_BASE_URL=http://your-machine.your-tailnet.ts.net:11435/v1"
set "OPENAI_API_KEY=local"
openclaude --model local-chat %*
```

Both have the host's tailnet hostname baked in by the dashboard at render time. Re-running the installer overwrites them with current host state.

### Install script flow

PowerShell variant (the bash variant mirrors):

1. Verify Node ≥ 20 (`node --version`). If missing, print install URL (`https://nodejs.org/`), exit 1. Do not auto-install — too invasive.
2. Verify ripgrep (`rg --version`). If missing, print platform-specific hint (`winget install BurntSushi.ripgrep.MSVC` on Windows, `brew install ripgrep` on macOS), exit 1.
3. `npm install -g @gitlawb/openclaude` (idempotent). On non-zero exit, propagate exit code, no files written.
4. Create `$HOME/.openclaude/` and `$HOME/openclaude-workspace/` (idempotent `mkdir -p`).
5. Write `$HOME/.openclaude/.claude.json` from embedded literal in the script body (heredoc-style). Local-tools workspace path is substituted at this step using the resolved absolute path.
6. Write `$HOME/.openclaude/settings.json` with `{ "model": "local-chat" }`.
7. Write wrapper to PATH location:
   - macOS: `$HOME/.local/bin/openclaude-local`, `chmod +x`. If `$HOME/.local/bin` is not on PATH, print a one-line hint to add it.
   - Windows: `%LOCALAPPDATA%\openclaude\openclaude-local.cmd`. If not on PATH, run `setx PATH "%PATH%;%LOCALAPPDATA%\openclaude"` (idempotent — checked first).
8. Print: "Installed. Run `openclaude-local` to start. Re-run this installer any time to re-sync with the host."

### Dashboard UI card

Added to `dashboard/static/index.html`, mirroring the "Unified download row" pattern at line 1332:

```
┌─ Add OpenClaude to a device ───────────────────────────────────┐
│  Detected tailnet host: your-machine.your-tailnet.ts.net  [✓]  │
│                                                                │
│  ( ) Windows (PowerShell)   (•) macOS / Linux (bash)           │
│                                                                │
│  ┌────────────────────────────────────────────────────────┐   │
│  │ curl -fsSL http://your-machine.your-tailnet.ts.net:    │   │
│  │ 8080/install/openclaude.sh | bash                       │   │
│  └────────────────────────────────────────────────────────┘   │
│  [ Copy ]                                                      │
│                                                                │
│  Status: model-gateway ✓  mcp-gateway ✓  blog-mcp ⚠ skipped   │
│                                                                │
│  After install, run `openclaude-local` on that device.        │
└────────────────────────────────────────────────────────────────┘
```

OS toggle swaps the visible one-liner client-side (no server round-trip — both come from `/api/openclaude/preview`). Status row reads MCP reachability from preview response. ⚠ for blog-mcp means it'll be skipped in the generated config; not a blocker. If detected hostname is `localhost`, card shows yellow warning ("Set TS_HOSTNAME to make this work from remote devices") instead of a one-liner.

## Error handling

| Failure | Where caught | User experience |
|---|---|---|
| `TS_HOSTNAME` unset and Host header is `localhost` | dashboard hostname resolver | UI card shows yellow warning + remediation; install endpoint returns 503 if hit directly |
| Node missing on device | install script step 1 | Print install URL, exit 1, no files written |
| ripgrep missing on device | install script step 1 | Print platform-specific install hint, exit 1 |
| `npm i -g` fails (network, perms) | install script step 3 | Propagate npm exit code, no config written |
| Blog MCP unreachable from dashboard | dashboard preflight | Omitted from generated config; UI shows ⚠; install proceeds normally |
| Re-running installer on a device that already has it | npm install (no-op), file writes (overwrite) | Idempotent; no error; config refreshed with current host state |
| Tailnet hostname changes later | n/a | User re-runs the one-liner on each device; gets refreshed config |
| Master key rotated on host | n/a | User re-runs the one-liner on each device; new key embedded |

## Testing

| Layer | Test |
|---|---|
| `dashboard/openclaude_install.py` (unit) | Hostname resolution: `TS_HOSTNAME` set → returns it; Host header set → returns Host minus port; both unset / localhost → returns sentinel and raises detectable error. |
| `dashboard/openclaude_install.py` (unit) | Config rendering: given URL + key + reachable MCP set, returns expected JSON for `.claude.json` and POSIX/PS1 wrapper bodies. Snapshot test. |
| Dashboard route (integration) | `GET /api/openclaude/preview` returns expected JSON keys; `GET /install/openclaude.sh` returns 200 text/plain with the host substituted. FastAPI TestClient. |
| Install script (POSIX, integration) | Run rendered shell script in an Ubuntu container with Node + rg pre-installed; assert config files written, wrapper on PATH, wrapper exec invokes openclaude with right env (mock openclaude with a stub that prints env). |
| Install script (PowerShell) | Documented manual smoke test on the user's Windows host; not CI-tested (no Windows runner). |
| End-to-end (manual) | After implementation, run installer on a 2nd device, confirm `openclaude-local` connects to host's gateway and lists MCP tools. Document in commit message. |
| Model alias rollout regression | Existing tests in `tests/` referencing GGUF-basename model identifiers — find and update to `local-chat` / `local-embed`. |
| Model swap regression | Run dashboard `/api/active-model` swap GGUF A → GGUF B. Verify all consumers continue to work without restart (only llamacpp recreated). |

## Open questions

- Does the host's existing reverse proxy / firewall config already pass through ports 8811 (mcp-gateway) and 3500 (blog-mcp) on the tailnet interface? Verify before publishing in compose. (If not, that's a one-line `0.0.0.0` binding fix per service.)
- Is `BLOG_MCP_API_KEY` a real env var name in the current setup, or is the blog server using a different auth header? Verify against the blog server's docs during implementation; rename in this spec if needed.
- OpenWebUI currently uses `OPEN_WEBUI_DEFAULT_MODEL=google_gemma-4-31B-it-Q4_K_M:chat` — the `:chat` suffix is OpenWebUI's tag convention. Confirm `local-chat` works without a `:chat` suffix in OpenWebUI's model picker, or determine whether the new value should be `local-chat:chat`.
- The wrapper script passes `--model local-chat` on the command line *and* the generated `settings.json` sets `model: local-chat`. Both should agree. Confirm OpenClaude doesn't error or warn on the redundant specification; if it does, drop one (prefer keeping the CLI flag for visibility).

## Implementation order suggestion (for the planning step)

1. Single-canonical-model rollout first (litellm config, entrypoint, consumer configs). Verify nothing breaks.
2. Publish mcp-gateway port by default; verify existing host-side users still work.
3. Build `dashboard/openclaude_install.py` + tests.
4. Build `dashboard/routes_openclaude.py` + tests.
5. Add UI card to `dashboard/static/index.html`.
6. Manual end-to-end test on the user's MacBook.
