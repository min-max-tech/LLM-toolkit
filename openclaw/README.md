# OpenClaw — Personal AI Assistant

[OpenClaw](https://docs.openclaw.ai) is a self-hosted personal AI assistant that runs in Docker. This folder provides a ready-to-use setup integrated with the AI-toolkit project.

## Quick Start

### 1. Prepare directories and workspace

From the **repo root** (e.g. `F:\AI-toolkit`):

```powershell
$env:BASE_PATH = "F:/AI-toolkit"
.\scripts\ensure_dirs.ps1
.\openclaw\scripts\ensure_openclaw_workspace.ps1
```

### 2. Configure environment

```powershell
cd openclaw
copy .env.example .env
```

Edit `.env` and set:

- `BASE_PATH` — repo root (e.g. `F:/AI-toolkit`)
- `OPENCLAW_GATEWAY_TOKEN` — generate with `openssl rand -hex 32`
- **Ollama** — enabled by default when using the main compose; models from `ollama` are auto-discovered
- Optional cloud APIs: `OPENAI_API_KEY`, `ANTHROPIC_API_KEY`, `GEMINI_API_KEY`, or `OPENROUTER_API_KEY`
- **Discord / Telegram (optional):** set `DISCORD_TOKEN` and/or `TELEGRAM_BOT_TOKEN` in the **project root** `.env` (same file the main compose uses). On startup, `openclaw-config-sync` runs `openclaw/scripts/merge_gateway_config.py`, which rewrites channel entries in `data/openclaw/openclaw.json` to OpenClaw **SecretRef** form so bot tokens are not stored as plaintext in the JSON. See [OPENCLAW_SECURE.md](OPENCLAW_SECURE.md) §4.

### 3. Start OpenClaw

```powershell
docker compose up -d openclaw-gateway
```

### 4. Onboarding (first run)

```powershell
docker compose run --rm openclaw-cli onboard --no-install-daemon
```

Use the token from `.env` when prompted.

### 5. Access the UI

With the **main** `docker-compose.yml`, the web Control UI is on the **gateway** port (default **6680**). Open **`http://localhost:6680/?token=<OPENCLAW_GATEWAY_TOKEN>`** (token from `.env`). In Settings → Model, choose a model from the **gateway** provider (e.g. `gateway/ollama/deepseek-r1:7b`) — this routes through the Model Gateway so dashboard monitoring shows performance. MCP tools (web search, etc.) from the gateway at `http://mcp-gateway:8811/mcp` are exposed via the **openclaw-mcp-bridge** plugin — the agent can call them automatically. **Do not use :6682** for this UI — that port is the browser/CDP bridge only.

If you use **`overrides/openclaw-secure.yml`**, the mapped gateway port is typically **18789** on localhost — see [OPENCLAW_SECURE.md.example](OPENCLAW_SECURE.md.example).

**Existing config?** Ensure `plugins.entries["openclaw-mcp-bridge"]` is set as in [mcp/README.md](../mcp/README.md#openclaw); this repo’s `data/openclaw/openclaw.json` already includes it.

**Not reachable?** When using the main AI-toolkit compose, the gateway is configured with `OPENCLAW_GATEWAY_BIND=lan` so it accepts connections from the host. If you run OpenClaw standalone from `openclaw/`, add `OPENCLAW_GATEWAY_BIND=lan` to your `.env`. Then verify: `docker compose ps` (gateway running), `docker compose logs openclaw-gateway` (no errors).

**Dashboard performance monitoring:** To see OpenClaw throughput in the dashboard (Token Throughput section), use the **gateway** provider for models. In Settings → Model, pick a model prefixed with `gateway/` (e.g. `gateway/ollama/deepseek-r1:7b`). If you only see `ollama/` models, add the gateway provider to `data/openclaw/openclaw.json` — copy the `gateway` block from `openclaw/openclaw.json.example` into `models.providers`.

**Security & Tailscale:** To bind the UI to localhost only (Tailscale Serve recommended), see [OPENCLAW_SECURE.md.example](OPENCLAW_SECURE.md.example).

## Workspace Files

Layering (see templates in `openclaw/workspace/`). **In git:** only `*.md.example` templates (plus `agents/*.md` and `health_check.sh`) are tracked; personalized top-level `SOUL.md`, `AGENTS.md`, etc. are listed in `.gitignore` — your working copies live under `data/openclaw/workspace/` or are created locally from the examples.

| File | Purpose |
|------|---------|
| `SOUL.md` | Identity, tone, boundaries — minimal operational detail |
| `USER.md` | Operator profile and preferences (optional; from `USER.md.example`) |
| `IDENTITY.md` | Optional display name / avatar notes (from `IDENTITY.md.example`) |
| `AGENTS.md` | Operating policy: startup order, when to use tools, failure and memory rules, safety |
| `TOOLS.md` | **Environment contract:** URLs, MCP invocation, ComfyUI/dashboard runbooks, failure modes |
| `MEMORY.md` | Curated long-term notes (main session) |
| `HEARTBEAT.md` | Optional operator checklist (from `HEARTBEAT.md.example`) |
| `memory/` | Dated episodic notes (`YYYY-MM-DD.md`) |

Sub-agents read **AGENTS.md** and **TOOLS.md**, not `SOUL.md` — keep critical rules there or in TOOLS.

**Seeding:** `ensure_openclaw_workspace.ps1` copies missing files from `openclaw/workspace/` (or `*.example`) into `data/openclaw/workspace/`.

**Docker sync (`openclaw-workspace-sync`):** For each workspace `*.md`, copies from the repo **only if the file does not already exist** in `data/openclaw/workspace/` (so local edits persist). **`health_check.sh`** and **`agents/`** are still refreshed from the repo on every sync. To pick up a new upstream template for a given markdown file, remove that file from `data/openclaw/workspace/` once, then restart the stack (or re-run the sync service).

## Data Paths

- **Config:** `data/openclaw/` (openclaw.json, agents, etc.)
- **Workspace:** `data/openclaw/workspace/` (files above, plus `memory/`)

## Discord (default channel)

Discord is the default client for interacting with OpenClaw.

**Recommended (AI-toolkit compose):** put the bot token in the **repo root** `.env` as `DISCORD_TOKEN`. Compose maps it to `DISCORD_BOT_TOKEN` inside `openclaw-gateway`, and `merge_gateway_config.py` (run by `openclaw-config-sync` before the gateway starts) updates `openclaw.json` to reference that env var instead of saving the token in the file.

**Alternative:** interactive login via CLI (writes config for you):

```powershell
docker compose run --rm openclaw-cli channels login
```

See [OpenClaw Discord docs](https://docs.openclaw.ai/channels/discord) for bot token, guild/channel restrictions, and configuration.

**Telegram:** set `TELEGRAM_BOT_TOKEN` in the root `.env`; the gateway container receives it and the merge step can apply the same SecretRef pattern for `channels.telegram`. See upstream [Telegram channel docs](https://docs.openclaw.ai/channels/telegram).

## CLI Commands

When the stack runs in Docker, the CLI must target the gateway by service name. Use the helper script (from repo root), which passes `--url ws://openclaw-gateway:6680` (container gateway port in the default compose) and token from the project root `.env`:

```powershell
# List devices (requires gateway running)
.\openclaw\scripts\run-cli.ps1 devices list

# Approve a device (replace DEVICE_ID with the id from the list)
.\openclaw\scripts\run-cli.ps1 devices approve DEVICE_ID

# Remove a device
.\openclaw\scripts\run-cli.ps1 devices remove DEVICE_ID
```

For other commands (e.g. `dashboard --no-open`) that don't need to call the gateway, you can run `docker compose --profile openclaw-cli run --rm openclaw-cli ...` directly.

## Build from Source (Optional)

To use the latest OpenClaw from source instead of the pre-built image:

```powershell
git clone https://github.com/openclaw/openclaw.git
cd openclaw
./docker-setup.sh
```

Then set `OPENCLAW_IMAGE=openclaw:local` in `.env` and point `OPENCLAW_CONFIG_DIR` / `OPENCLAW_WORKSPACE_DIR` to this project’s data paths.

## Docs

- [OPENCLAW_SECURE.md](OPENCLAW_SECURE.md) — trust model, channel env vars, backups
- [docs/runbooks/SECURITY_HARDENING.md](../docs/runbooks/SECURITY_HARDENING.md) — §11 `openclaw.json` / SecretRefs
- [OpenClaw Docker Guide](https://docs.openclaw.ai/install/docker)
- [Setup](https://docs.openclaw.ai/setup)
- [Agent Workspace](https://docs.openclaw.ai/concepts/agent-workspace)
