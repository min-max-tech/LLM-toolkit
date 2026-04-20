# Remove OpenClaw — Design

**Date:** 2026-04-20
**Status:** Approved for planning
**Context:** Phase 2 of Hermes migration (Phase 1: `docs/superpowers/specs/2026-04-18-hermes-agent-integration-design.md`).

## Goal

Surgically remove all OpenClaw-specific code, services, tests, dashboard surfaces, env vars, and ops-controller references from the tracked repository. After this change the stack runs without OpenClaw and nothing in the tracked build targets or runtime references it.

PRD cleanup and operator-doc cleanup are explicitly **deferred** to a later pass. Only `CHANGELOG.md` (one new entry) and `docs/hermes-agent.md` (one-line footnote update) are edited in this PR.

## Non-goals

- Rewriting any PRD under `docs/product requirements docs/`.
- Editing `docs/configuration.md`, `docs/data.md`, `docs/GETTING_STARTED.md` (knowingly stale until a future pass).
- Removing historical `CHANGELOG.md` entries.
- Touching `vendor/hermes-agent/` or `data/openclaw/` on disk.
- Re-adding Discord/Telegram integration for Hermes (separate future phase).

## Branch

`feat/remove-openclaw` off `main` at `198f537`.

## Verification contract

After the change, this command must return zero matches:

```bash
rg -i openclaw \
  -g '!docs/**' \
  -g '!CHANGELOG.md' \
  -g '!vendor/**' \
  -g '!data/**'
```

Any remaining OpenClaw mentions are confined to knowingly-stale docs, historical CHANGELOG, the vendored Hermes repo, and gitignored runtime data.

Additional checks:
- `docker compose config` parses cleanly with no warnings about unresolved service dependencies.
- `python -m pytest tests/` passes (minus deleted tests).
- Dashboard module imports resolve (`python -c "import dashboard.app"` succeeds).
- Ops-controller module imports resolve.

## Work buckets

Each bucket becomes one or more plan tasks.

### 1. Docker Compose surface

Remove these services from `docker-compose.yml`:
- `openclaw-workspace-sync`
- `openclaw-config-sync`
- `openclaw-plugin-install`
- `openclaw-plugin-config`
- `openclaw-gateway`
- `openclaw-ui-proxy`
- `openclaw-cli`
- `wait-orchestration` (orphaned once openclaw-gateway is gone)

Remove profiles: `openclaw-docker`, `openclaw-setup`, `openclaw-cli`.

Remove the named volume: `openclaw-extensions`.

Remove any `depends_on` clauses referencing these services on other services.

Delete overrides:
- `overrides/openclaw-gateway-root.yml`
- `overrides/openclaw-secure.yml`

### 2. Repo tree

Delete:
- `openclaw/` (entire directory including `openclaw/scripts/`, `openclaw/workspace/`, `openclaw/extensions/openclaw-mcp-bridge/`, `openclaw/README.md`, `openclaw/OPENCLAW_SECURE.md`, `openclaw/OPENCLAW_SECURE.md.example`, `openclaw/openclaw.json.example`)
- `scripts/fix_openclaw_workspace_permissions.ps1`
- `scripts/fix_openclaw_workspace_permissions.sh`
- `scripts/validate_openclaw_config.py`
- `scripts/start-openclaw-host.sh` (this file is currently untracked — just delete from working tree)

### 3. Env vars (`.env.example`)

Remove all lines (and their explanatory comments) for these variables:

- `OPENCLAW_CONTEXT_WINDOW`
- `OPENCLAW_COMPACTION_MODE`
- `OPENCLAW_AGENT_TIMEOUT_SECONDS`
- `OPENCLAW_LLM_IDLE_TIMEOUT_SECONDS`
- `OPENCLAW_BOOTSTRAP_MAX_CHARS`
- `OPENCLAW_BOOTSTRAP_TOTAL_MAX_CHARS`
- `OPENCLAW_MCP_CONNECT_TIMEOUT_MS`
- `OPENCLAW_MCP_REQUEST_TIMEOUT_MS`
- `OPENCLAW_IMAGE`
- `OPENCLAW_GATEWAY_TOKEN`
- `OPENCLAW_GATEWAY_INTERNAL_PORT`
- `OPENCLAW_GATEWAY_PORT` (if distinct)
- `OPENCLAW_UI_PORT`
- `OPENCLAW_NATIVE_WEB_SEARCH`
- `OPENCLAW_ALLOW_BUILTIN_BROWSER`
- `OPENCLAW_ELEVATED_ALLOW_WEBCHAT`
- `OPENCLAW_UNRESTRICTED_GATEWAY_CONTAINER`
- `OPENCLAW_SKIP_TOOLS_MD_UPGRADE`
- `OPENCLAW_ALLOW_IN_APP_UPDATE`
- `OPENCLAW_DISCORD_GUILD_IDS`
- `OPENCLAW_DISCORD_USER_IDS`
- `DISCORD_TOKEN`
- `DISCORD_BOT_TOKEN`
- `TELEGRAM_BOT_TOKEN`

Leave the Hermes block and the Hermes `HERMES_PINNED_SHA` pointer intact. Operator's real `.env` keeps whatever Discord/Telegram values it already has; we're only pruning the example.

### 4. Tests

Delete:
- `tests/test_openclaw_gateway_model_defaults.py`
- `tests/test_openclaw_mcp_bridge_contract.py`
- `tests/test_openclaw_mcp_bridge_runtime_contract.py`
- `tests/test_openclaw_mcp_plugin_config.py`
- `tests/test_validate_openclaw_config.py`
- `tests/test_merge_gateway_config.py` (tests `openclaw/scripts/merge_gateway_config.py`, which is gone)
- `tests/fixtures/openclaw_valid.json`

Check and possibly update (not delete wholesale):
- `tests/test_dashboard_dependencies.py` — may assert on openclaw-gateway presence in dependency registry. Update assertions or drop OpenClaw-specific cases.
- `tests/test_dashboard_service_pressure.py` — may iterate services catalog. Update if it enumerates openclaw.

Any other `test_*` that imports from `dashboard.app` and references removed symbols must be updated.

### 5. Dashboard backend (`dashboard/`)

**`dashboard/app.py`**: remove
- `OPENCLAW_CONFIG_PATH` import / constant
- `OPENCLAW_CONTEXT_WINDOW` constant and the `_ctx_raw` env read
- `openclaw_context_window` field in any system-info / health payload
- Any call that POSTs to `/services/openclaw-gateway/restart`
- `_OPENCLAW_GATEWAY_BASE`
- `_make_openclaw_model()` helper
- Endpoints: `GET /api/openclaw/models`, `GET /api/openclaw/default-model`, `POST /api/openclaw/default-model`, `POST /api/openclaw/sync`
- Any imports these endpoints depended on that become unused

**`dashboard/settings.py`**: remove
- `OPENCLAW_GATEWAY_PORT`
- `OPENCLAW_GATEWAY_INTERNAL_PORT`
- `OPENCLAW_UI_PORT`
- `OPENCLAW_GATEWAY_TOKEN`
- `OPENCLAW_CONFIG_PATH`

**`dashboard/services_catalog.py`**: remove
- All `OPENCLAW_GATEWAY_*` imports/module-level reads
- The `openclaw` entry in the `SERVICES` list (the one with `"id": "openclaw"`)
- The `"openclaw" -> "openclaw-gateway"` entry in `OPS_SERVICE_MAP`

**`dashboard/dependency_registry.json`**: remove
- The `openclaw-gateway` entry
- The `"openclaw_critical": true` flag from any other entries

**`dashboard/entrypoint.sh`**: remove the `openclaw-config` permission-fix block.

### 6. Dashboard UI (`dashboard/static/index.html`)

Remove:
- `.openclaw-sync-status` CSS class
- The "Sync to OpenClaw" button, its container, and its status div
- The emoji mapping entry for `openclaw`
- The event listener that calls `/api/openclaw/sync`

Scan for any other `openclaw`/`OpenClaw` text in the HTML and remove (titles, tooltips, help text).

### 7. Ops-controller (`ops-controller/main.py`)

Remove `"openclaw-gateway"` from `ALLOWED_SERVICES` (and similar allowlists if any).

Scan for other OpenClaw references in `ops-controller/`.

### 8. `docs/hermes-agent.md`

Replace the "Relationship to OpenClaw" section (currently about 6 lines describing defensive stops and dual-stack risk) with a single footer line:

```
> **Note:** The stack previously used OpenClaw as its assistant-agent layer. It was decommissioned on 2026-04-20 (see CHANGELOG).
```

Also remove the one-line mention in the "Running" section about OpenClaw.

### 9. CHANGELOG

Add one new entry at the top under `[Unreleased]`:

```
### Removed
- OpenClaw assistant-agent layer (services, workspace, MCP bridge fork, dashboard endpoints + sync UI, tests, overrides, env vars, `wait-orchestration` barrier). Replaced by Hermes Agent (see 2026-04-18 integration). `data/openclaw/` runtime data is left on operator machines; delete manually if desired.
```

Historical OpenClaw entries are not touched.

## Sequencing considerations

The plan will apply buckets in this order to maintain a green build at each step:

1. Delete tests first (otherwise they'd fail when the code they test is removed).
2. Delete dashboard routes (after removing UI that calls them).
3. Delete dashboard UI + settings + services catalog + entrypoint fix.
4. Delete ops-controller allowlist entry.
5. Delete Docker compose services + overrides + named volume.
6. Delete scripts and `openclaw/` tree.
7. Strip `.env.example` vars.
8. Update `docs/hermes-agent.md`.
9. Add CHANGELOG entry.
10. Run verification grep; clean up stragglers.
11. Final test run.

Each bucket becomes one or more tasks with TDD-style verification (`pytest`, `docker compose config`, the verification grep).

## Risks

1. **Dashboard test regressions from shared fixtures.** `dashboard/services_catalog.py` edits may break `test_dashboard_dependencies.py` assertions. Plan will run the test suite after each dashboard edit and update assertions inline if needed.
2. **Unused imports lint failures** once symbols are removed. Plan will run a linter check (or a `python -c "import dashboard.app"` smoke check) after each module edit.
3. **Surgical `.env.example` diff** — sweeping edits risk dropping comments that still document non-OpenClaw vars adjacent to OpenClaw vars. Plan instructs targeted line-range edits, not wholesale replacement.
4. **`dashboard/static/index.html` is large (~3000 lines)**. The emoji map, button, CSS, and event listener are scattered; plan dispatches one subagent for all UI edits and verifies with a final grep.
5. **Uncommitted operator state** (`.gitignore`, `tests/test_ops_controller_stats.py`, 4 untracked files) must not be swept into commits. Plan reminds each subagent to use targeted `git add <path>`.

## File-change summary (approximate)

| Category | Deletes | Edits |
|---|---|---|
| `openclaw/` tree | ~130 files (entire directory) | 0 |
| `overrides/` | 2 files | 0 |
| `scripts/` | 3 tracked files + 1 untracked | 0 |
| `tests/` | 7 files | ~2 existing tests updated |
| `dashboard/` | 0 files | 5 files |
| `ops-controller/` | 0 files | 1 file |
| root | 0 files | 3 files (`docker-compose.yml`, `.env.example`, `CHANGELOG.md`) |
| `docs/` | 0 files | 1 file (`docs/hermes-agent.md`) |

Total new files: 0. This is a pure removal/cleanup change.
