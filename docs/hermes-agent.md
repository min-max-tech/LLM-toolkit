# Hermes Agent (host-mode)

Phase-1 evaluation of [NousResearch/hermes-agent](https://github.com/NousResearch/hermes-agent)
as the stack's assistant-agent layer. Installed alongside OpenClaw; OpenClaw is not decommissioned
until phase 2.

## Why

OpenClaw has not reached a reliably working state on this stack. Hermes overlaps functionally
(messaging, MCP, cron, OpenAI-compatible) and adds a self-improving skill/learning system
(FTS5 session search, Honcho user modeling, autonomous skill creation from experience).

## Platform requirements

- **WSL2** (recommended) or **Git Bash** on Windows; Linux or macOS on POSIX hosts.
- Python **3.11** (installed automatically by `uv` into the Hermes venv — no system Python change).
- `uv` from astral.sh (installed automatically by the bootstrap if missing).
- The stack running (or startable via `docker compose up -d`).

## Running

From the repo root:

```bash
./scripts/start-hermes-host.sh
```

On first run this clones `vendor/hermes-agent/`, installs it into a dedicated venv, starts the
Docker stack, and launches the Hermes CLI. Subsequent runs skip the clone and install steps.

## Stopping

- `Ctrl-C` exits the Hermes CLI.
- The Docker stack keeps running. Stop it with `docker compose down` when desired.

## State

| Path | Contents |
|---|---|
| `vendor/hermes-agent/` | Upstream repo clone, pinned to a specific commit SHA |
| `vendor/hermes-agent/.venv/` | Python 3.11 venv managed by `uv` |
| `data/hermes/` | Hermes `HERMES_HOME` — config, skills, FTS5 sessions |

All three are gitignored. To fully reset:

```bash
rm -rf vendor/hermes-agent data/hermes
./scripts/start-hermes-host.sh
```

## Known egress

- **Honcho user modeling**: No disable flag exists. Hermes only activates Honcho if
  `~/.honcho/config.json` exists. Since the bootstrap script does not create one, Honcho
  remains dormant in phase 1. If you later enable Honcho, audit the outbound destinations
  before committing to it.
- **`uv` install**: First run fetches `https://astral.sh/uv/install.sh` if `uv` is not already
  present. Install `uv` ahead of time (e.g. `winget install --id=astral-sh.uv -e`) if outbound
  access is blocked.
- **`hermes-agent` clone**: First run clones from GitHub. Pin to a specific SHA via
  `HERMES_PINNED_SHA` in `.env` to freeze upstream.

## Configuration keys

The bootstrap script calls `hermes config set` to persist these (discovered from
`vendor/hermes-agent/hermes_cli/config.py`):

| Key | Value | Purpose |
|---|---|---|
| `providers.ordo.base_url` | `http://localhost:11435/v1` | OpenAI-compatible endpoint (model-gateway / LiteLLM) |
| `providers.ordo.api_key` | `LITELLM_MASTER_KEY` (default `local`) | Bearer key |
| `model` | `ordo:local-chat` | Primary model slug (provider:id format) |
| `mcp_servers.gateway.url` | `http://localhost:8811/mcp` | MCP streamable-http endpoint |

If Hermes rejects a key at runtime (e.g. upstream renamed something), check current config:

```bash
./vendor/hermes-agent/.venv/bin/hermes config --help
./vendor/hermes-agent/.venv/bin/hermes config show
```

Then update `scripts/start-hermes-host.sh` Phase 8 accordingly.

## Validation checklist

After `./scripts/start-hermes-host.sh`:

- [ ] Hermes CLI launches to its TUI.
- [ ] Hermes reports the local gateway model as available (slash-command or equivalent).
- [ ] Hermes MCP tool listing shows tools from mcp-gateway (ComfyUI, Tavily, n8n, GitHub,
      orchestration).
- [ ] Ask Hermes to read a repo file (e.g. `cat README.md`) — confirms host filesystem access.
- [ ] Ask Hermes to call a Tavily search or a ComfyUI tool — confirms MCP roundtrip.
- [ ] Exit. Confirm `data/hermes/` now contains config/session files.

## Discord gateway

The Discord gateway is a persistent process that connects Hermes to Discord. It runs separately
from the TUI and the web dashboard; one or both can be active.

### One-time Discord Developer Portal setup

1. Open https://discord.com/developers/applications and create a new application.
2. **Bot → Token:** click *Reset Token*. Copy it — you won't see it again. This becomes
   `DISCORD_BOT_TOKEN` in `.env`.
3. **Bot → Privileged Gateway Intents:** enable **Message Content Intent** (required — without
   this, the bot connects but receives empty message text) and **Server Members Intent**.
4. **OAuth2 → URL Generator:** select scopes `bot` and `applications.commands`, and bot
   permissions `274878286912` (View Channels, Send Messages, Read Message History, Embed Links,
   Attach Files, Send Messages in Threads, Add Reactions). Copy the URL, open it, and invite the
   bot to your server.
5. **Get your user ID:** Discord → Settings → Advanced → **Developer Mode** on. Then right-click
   your username → *Copy User ID*. This becomes `DISCORD_ALLOWED_USERS` in `.env`.

### `.env` entries

Add to `.env`:

```
DISCORD_BOT_TOKEN=<token-from-step-2>
DISCORD_ALLOWED_USERS=<your-user-id-from-step-5>
# Respond without @mention (OpenClaw-equivalent behavior):
DISCORD_REQUIRE_MENTION=false
```

If you already had `DISCORD_TOKEN=...` in `.env` (from OpenClaw), the bootstrap script aliases
it to `DISCORD_BOT_TOKEN` automatically — so you can just add `DISCORD_ALLOWED_USERS` and
`DISCORD_REQUIRE_MENTION` and you're done.

### Starting the gateway

In a dedicated terminal (leave it running):

```bash
./scripts/start-hermes-host.sh --gateway
```

This runs `hermes gateway` with the env vars from `.env` exported. The process connects to
Discord's WebSocket, joins as your bot, and routes DMs and allowed-channel messages to the
Hermes agent using the same `local-chat` model and mcp-gateway tools.

To stop: `Ctrl-C`.

### Verifying

- In Discord, your bot should show as online (green circle).
- DM the bot or @-mention it in a permitted channel.
- The bot reacts with 👀 while thinking and ✅ when it responds.
- If the bot connects but doesn't reply, the most common cause is **Message Content Intent
  disabled** in the Developer Portal.

### Running dashboard + gateway at the same time

The dashboard and gateway are two independent processes. Open two terminals and run:

```bash
./scripts/start-hermes-host.sh --dashboard    # terminal 1
./scripts/start-hermes-host.sh --gateway      # terminal 2
```

Both use the same `data/hermes/` state, so sessions started on Discord appear in the dashboard
and vice-versa.

## Refreshing the pin

`HERMES_PINNED_SHA` is set near the top of `scripts/start-hermes-host.sh` (and may be overridden
via `.env`). To upgrade:

```bash
cd vendor/hermes-agent
git fetch origin
git log --oneline origin/main -20
# pick a new SHA
```

Update `HERMES_PINNED_SHA` in the script (or `.env`), re-run the bootstrap. If the new version
changes config key names, inspect `vendor/hermes-agent/hermes_cli/config.py` and update Phase 8
of the script accordingly.

---

> **Note:** The stack previously used OpenClaw as its assistant-agent layer. It was decommissioned on 2026-04-20 — see `CHANGELOG.md` for the removal entry.
