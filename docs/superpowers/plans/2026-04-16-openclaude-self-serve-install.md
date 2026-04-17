# OpenClaude Self-Serve Install Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make OpenClaude installable on any tailnet device via a single one-liner from the dashboard, auto-configured to use the host's local model gateway and MCP gateway, while a single canonical model identity (`local-chat`) makes GGUF swaps invisible to all downstream consumers.

**Architecture:** Three changes that build on each other: (1) collapse all consumer model identities to a stable `local-chat` / `local-embed` advertised by LiteLLM (independent of the loaded GGUF); (2) publish the MCP gateway port on the host network by default so remote tailnet devices can reach it; (3) add a dashboard endpoint that renders a self-contained per-OS install script embedding the host's tailnet hostname, gateway URL, master key, and MCP server config — script writes everything to `~/.openclaude/` via `CLAUDE_CONFIG_DIR` so Claude Code on the same device is never touched.

**Tech Stack:** FastAPI (dashboard), Jinja2 (script templating), pytest + FastAPI TestClient (tests), Docker Compose, LiteLLM (model gateway), llama.cpp (model server), npm (`@gitlawb/openclaude` package), PowerShell + POSIX shell (install scripts).

**Spec:** See `docs/superpowers/specs/2026-04-16-openclaude-self-serve-install-design.md` for the full design and rationale.

---

## File Structure

### New files
- `dashboard/openclaude_install.py` — pure logic: hostname resolution, MCP reachability preflight (with TTL cache), config rendering. ~150 lines.
- `dashboard/routes_openclaude.py` — FastAPI router with three GET routes. ~80 lines.
- `dashboard/templates/__init__.py` — empty marker.
- `dashboard/templates/openclaude_install.sh.j2` — POSIX install script template. ~100 lines.
- `dashboard/templates/openclaude_install.ps1.j2` — PowerShell install script template. ~120 lines.
- `dashboard/templates/openclaude_claude_json.j2` — `~/.openclaude/.claude.json` body (shared by both scripts as a heredoc).
- `tests/test_openclaude_install_module.py` — unit tests for `openclaude_install.py`.
- `tests/test_openclaude_install_routes.py` — integration tests for the FastAPI routes.
- `tests/test_openclaude_install_script_integration.py` — POSIX script integration test (Linux Docker container).

### Modified files
- `model-gateway/litellm_config.yaml` — replace placeholder-templated entries with literal `local-chat` and `local-embed`.
- `model-gateway/entrypoint.sh` — only substitute `__MASTER_KEY__`.
- `dashboard/requirements.txt` — add `jinja2>=3.1.0`.
- `dashboard/app.py` — register router; simplify `/api/active-model` flow to drop OpenWebUI/OpenClaw rewrites.
- `dashboard/static/index.html` — add "Add OpenClaude to a device" card with OS toggle, copy button, status row.
- `data/openclaw/openclaw.json` — `agents.defaults.model.primary` = `gateway/local-chat`; replace GGUF model entry with `local-chat` entry.
- `openclaw/scripts/merge_gateway_config.py` — always write a single `local-chat` model entry and `gateway/local-chat` primary, regardless of `LLAMACPP_MODEL`.
- `.env`, `.env.example` — `OPEN_WEBUI_DEFAULT_MODEL=local-chat`, `DEFAULT_MODEL=local-chat`.
- `docker-compose.yml` — `mcp-gateway` gets `ports: ["${MCP_GATEWAY_PORT:-8811}:8811"]`.
- `overrides/mcp-expose.yml` — replace contents with deprecation comment, leave file as no-op.
- `tests/test_model_gateway_config.py` — assertions updated for new template.
- `tests/test_openclaw_gateway_model_defaults.py` — assertions updated for `local-chat`.

---

## Phase A — Single canonical model identity

### Task A1: Update litellm_config.yaml to literal local-chat / local-embed entries

**Files:**
- Modify: `model-gateway/litellm_config.yaml`
- Test: `tests/test_model_gateway_config.py`

- [ ] **Step 1: Update the existing test for the new schema (failing)**

Replace the body of `tests/test_model_gateway_config.py` with:

```python
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MODEL_GATEWAY_DIR = REPO_ROOT / "model-gateway"


def test_litellm_config_advertises_canonical_model_names():
    config_text = (MODEL_GATEWAY_DIR / "litellm_config.yaml").read_text(encoding="utf-8")

    # Stable identities — never change with GGUF swaps.
    assert 'model_name: "local-chat"' in config_text
    assert 'model_name: "local-embed"' in config_text

    # Underlying api_base routing preserved.
    assert 'api_base: "http://llamacpp:8080/v1"' in config_text
    assert 'api_base: "http://llamacpp-embed:8080/v1"' in config_text

    # Master key still templated for entrypoint substitution.
    assert "__MASTER_KEY__" in config_text

    # Old templated GGUF placeholders are gone.
    assert "__CHAT_MODEL__" not in config_text
    assert "__EMBED_MODEL__" not in config_text


def test_litellm_dockerfile_uses_proxy_image():
    dockerfile = (MODEL_GATEWAY_DIR / "Dockerfile").read_text(encoding="utf-8")

    assert "ghcr.io/berriai/litellm:" in dockerfile
    assert "config.template.yaml" in dockerfile
    assert "entrypoint.sh" in dockerfile
```

- [ ] **Step 2: Run the test, verify both assertions fail**

Run: `pytest tests/test_model_gateway_config.py::test_litellm_config_advertises_canonical_model_names -v`
Expected: FAIL — `'model_name: "local-chat"' in config_text` is False; `'__CHAT_MODEL__' not in config_text` is False.

- [ ] **Step 3: Replace `model-gateway/litellm_config.yaml` body**

Overwrite the file with:

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

- [ ] **Step 4: Run the test, verify it passes**

Run: `pytest tests/test_model_gateway_config.py -v`
Expected: PASS (both tests).

- [ ] **Step 5: Commit**

```bash
git add model-gateway/litellm_config.yaml tests/test_model_gateway_config.py
git commit -m "refactor(model-gateway): collapse model identity to local-chat / local-embed"
```

---

### Task A2: Simplify entrypoint.sh

**Files:**
- Modify: `model-gateway/entrypoint.sh`

- [ ] **Step 1: Replace the script body**

Overwrite `model-gateway/entrypoint.sh` with:

```sh
#!/bin/sh
set -eu

MASTER_KEY="${LITELLM_MASTER_KEY:-local}"

sed -e "s|__MASTER_KEY__|${MASTER_KEY}|g" /app/config.template.yaml > /tmp/config.yaml

exec litellm --config /tmp/config.yaml --host 0.0.0.0 --port 11435
```

- [ ] **Step 2: Verify file is still executable**

Run: `git update-index --chmod=+x model-gateway/entrypoint.sh && stat -c "%a" model-gateway/entrypoint.sh`
Expected: `755` (or otherwise executable on POSIX checkouts).

- [ ] **Step 3: Rebuild model-gateway container and verify it starts**

Run: `docker compose build model-gateway && docker compose up -d --force-recreate model-gateway && sleep 5 && docker compose logs --tail=20 model-gateway`
Expected: Logs show `LiteLLM:` startup banner, no `unbound variable` or `bad substitution` errors.

- [ ] **Step 4: Verify advertised models**

Run: `curl -s -H "Authorization: Bearer local" http://localhost:11435/v1/models | python -m json.tool`
Expected: JSON lists exactly two models with `id` `local-chat` and `local-embed`. No GGUF basenames.

- [ ] **Step 5: Commit**

```bash
git add model-gateway/entrypoint.sh
git commit -m "refactor(model-gateway): drop CHAT/EMBED model name substitution from entrypoint"
```

---

### Task A3: Update merge_gateway_config.py to write canonical OpenClaw model

**Files:**
- Modify: `openclaw/scripts/merge_gateway_config.py`
- Test: `tests/test_openclaw_gateway_model_defaults.py`

- [ ] **Step 1: Update the existing test for new behavior (failing)**

Replace the body of `tests/test_openclaw_gateway_model_defaults.py` with:

```python
from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MERGE_SCRIPT = REPO_ROOT / "openclaw" / "scripts" / "merge_gateway_config.py"
OPENCLAW_CONFIG = REPO_ROOT / "data" / "openclaw" / "openclaw.json"


def test_merge_script_pins_canonical_local_chat_primary():
    text = MERGE_SCRIPT.read_text(encoding="utf-8")

    # Always emit local-chat regardless of LLAMACPP_MODEL value.
    assert 'OPENCLAW_PRIMARY_MODEL_ID = "local-chat"' in text
    assert 'desired_primary = f"gateway/{OPENCLAW_PRIMARY_MODEL_ID}"' in text


def test_openclaw_config_uses_canonical_local_chat_primary():
    text = OPENCLAW_CONFIG.read_text(encoding="utf-8")

    assert '"id": "local-chat"' in text
    assert '"primary": "gateway/local-chat"' in text
    # GGUF basenames should not appear as model identities anymore.
    assert "google_gemma-4-31B-it-Q4_K_M.gguf" not in text
```

- [ ] **Step 2: Run the test, verify it fails**

Run: `pytest tests/test_openclaw_gateway_model_defaults.py -v`
Expected: FAIL on both tests.

- [ ] **Step 3: Add the constant + simplify the merge logic**

Open `openclaw/scripts/merge_gateway_config.py`. Just below the `GATEWAY_PROVIDER = {...}` block (around line 41-46), add:

```python
# Canonical OpenClaw model identity. Independent of the loaded GGUF on the host —
# every consumer (OpenWebUI, OpenClaw, OpenClaude) refers to the model by this name.
# The model-gateway (LiteLLM) advertises "local-chat" and forwards to whatever GGUF
# llama.cpp has loaded.
OPENCLAW_PRIMARY_MODEL_ID = "local-chat"
```

Then locate the block around lines 685-700 that derives `active_model_id` from `LLAMACPP_MODEL` and computes `desired_primary`. Replace it with:

```python
    # Always pin OpenClaw to the canonical gateway alias.
    active_model_id = OPENCLAW_PRIMARY_MODEL_ID
    desired_primary = f"gateway/{OPENCLAW_PRIMARY_MODEL_ID}"
```

(Read the surrounding context with grep first: `grep -n "active_model_id" openclaw/scripts/merge_gateway_config.py` to identify the precise line numbers; the lines may have drifted since this plan was written.)

- [ ] **Step 4: Update the model list builder**

Find the section that builds `gw["models"]` (search for `gw["models"] = [active_entry]` or similar). Ensure the model entry uses `OPENCLAW_PRIMARY_MODEL_ID` as `id`. Look at `_gguf_model_entry(filename, ...)` (line ~450) — it builds an entry with `"id": filename`. We want the equivalent but with `id="local-chat"` and a sensible context window.

Add a helper near `_gguf_model_entry`:

```python
def _canonical_model_entry(context_window: int = LLAMACPP_CTX) -> dict:
    """Build the single canonical OpenClaw model entry used for all chat agents."""
    return {
        "id": OPENCLAW_PRIMARY_MODEL_ID,
        "name": "Local Chat (gateway alias)",
        "reasoning": True,
        "input": ["text"],
        "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
        "contextWindow": context_window,
        "maxTokens": 8192,
    }
```

Then replace the `active_entry = _gguf_model_entry(...)` (or `_make_openclaw_model(...)`) call near line 692 with:

```python
    active_entry = _canonical_model_entry(context_window=LLAMACPP_CTX)
```

- [ ] **Step 5: Hand-edit `data/openclaw/openclaw.json` to match**

Open `data/openclaw/openclaw.json`. Locate `agents.defaults.model.primary`:

```json
        "primary": "gateway/google_gemma-4-31B-it-Q4_K_M.gguf",
```

Change to:

```json
        "primary": "gateway/local-chat",
```

Locate `models.providers.gateway.models[0]`:

```json
          {
            "id": "google_gemma-4-31B-it-Q4_K_M.gguf",
            "name": "Google Gemma 4 31b It Q4 K M Gguf",
            ...
          }
```

Replace with:

```json
          {
            "id": "local-chat",
            "name": "Local Chat (gateway alias)",
            "reasoning": true,
            "input": ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 65536,
            "maxTokens": 8192
          }
```

(Preserve the `contextWindow` value already present in your config if it differs from `65536`.)

- [ ] **Step 6: Run the tests, verify they pass**

Run: `pytest tests/test_openclaw_gateway_model_defaults.py -v`
Expected: PASS (both tests).

- [ ] **Step 7: Commit**

```bash
git add openclaw/scripts/merge_gateway_config.py data/openclaw/openclaw.json tests/test_openclaw_gateway_model_defaults.py
git commit -m "refactor(openclaw): pin primary model to canonical gateway/local-chat alias"
```

---

### Task A4: Update .env and .env.example

**Files:**
- Modify: `.env`
- Modify: `.env.example`

- [ ] **Step 1: Edit `.env`**

Find these lines:
```
DEFAULT_MODEL=google_gemma-4-31B-it-Q4_K_M
OPEN_WEBUI_DEFAULT_MODEL=google_gemma-4-31B-it-Q4_K_M:chat
```

Replace with:
```
DEFAULT_MODEL=local-chat
OPEN_WEBUI_DEFAULT_MODEL=local-chat
```

Leave `LLAMACPP_MODEL=google_gemma-4-31B-it-Q4_K_M.gguf` unchanged — only the llamacpp container reads it now.

- [ ] **Step 2: Edit `.env.example`**

Apply the same change. If the example file currently shows commented placeholders like `# OPEN_WEBUI_DEFAULT_MODEL=`, set them to the same canonical value with a comment explaining stability:

```
# Single canonical model identity. Don't change unless you renamed the alias in litellm_config.yaml.
DEFAULT_MODEL=local-chat
OPEN_WEBUI_DEFAULT_MODEL=local-chat
```

- [ ] **Step 3: Recreate the consumers**

Run: `docker compose up -d --force-recreate open-webui` then test the model picker in OpenWebUI; confirm `local-chat` is selected and a chat round-trip works.

- [ ] **Step 4: Manual verification: OpenClaw reads canonical primary**

Restart OpenClaw to re-run merge_gateway_config:
```
docker compose restart openclaw-gateway
docker compose logs --tail=30 openclaw-gateway
```
Expected: log lines mention writing `gateway/local-chat` as primary; no errors.

- [ ] **Step 5: Commit**

```bash
git add .env .env.example
git commit -m "refactor: switch DEFAULT_MODEL and OPEN_WEBUI_DEFAULT_MODEL to canonical local-chat"
```

(If your `.env` is gitignored — which it typically should be — only commit `.env.example`. Verify with `git check-ignore .env`.)

---

### Task A5: Simplify dashboard /api/active-model flow

**Files:**
- Modify: `dashboard/app.py:395-469` (the `/api/active-model` POST handler body)

- [ ] **Step 1: Read the current implementation**

Run: `sed -n '378,470p' dashboard/app.py`
Note the exact line range — line numbers may have drifted.

- [ ] **Step 2: Replace the handler body**

Locate the function decorated `@app.post("/api/active-model")`. Replace its body (everything after the docstring and validation up to the final `return`) with:

```python
    bare_name = re.sub(r"\.gguf$", "", model.strip(), flags=re.IGNORECASE)
    if not bare_name:
        raise HTTPException(status_code=400, detail="Invalid model filename")
    results: dict = {}
    errors: list[str] = []

    # Switch LLAMACPP_MODEL + recreate llamacpp. Every consumer (OpenWebUI, OpenClaw,
    # OpenClaude on remote devices) uses the canonical 'local-chat' alias from the
    # model-gateway, so there's nothing else to update.
    code, data = await _ops_request(
        "POST", "/env/set", request=request,
        json={"key": "LLAMACPP_MODEL", "value": model, "confirm": True},
    )
    if code not in (200, 201):
        raise HTTPException(status_code=502, detail=f"Failed to update LLAMACPP_MODEL: {data}")
    code2, _ = await _ops_request(
        "POST", "/services/llamacpp/recreate", request=request, json={"confirm": True}
    )
    results["llamacpp_restarting"] = code2 in (200, 201, 202)
    if not results["llamacpp_restarting"]:
        errors.append("llamacpp recreate failed")

    all_ok = len(errors) == 0
    if errors:
        logger.warning("Model switch to %s partial failure: %s", model, "; ".join(errors))
    return {"ok": all_ok, "model": model, "errors": errors, **results}
```

- [ ] **Step 3: Confirm no longer-needed helpers can be removed**

Run: `grep -n "_make_openclaw_model\|OPENCLAW_CONFIG_PATH\|_open_webui_default_model" dashboard/app.py`

If `_make_openclaw_model` is no longer referenced elsewhere, leave it — it's used by `merge_gateway_config.py` semantically and may be referenced by other handlers; only delete it if truly unused. `_open_webui_default_model` is still used by `/api/config/default-model` (line ~1820); leave it.

- [ ] **Step 4: Manual smoke test the simplified flow**

```
curl -s -X POST http://localhost:8080/api/active-model \
  -H "Content-Type: application/json" \
  -d '{"model":"google_gemma-4-31B-it-Q4_K_M.gguf"}' | python -m json.tool
```
Expected: returns `{"ok": true, "model": "...", "llamacpp_restarting": true}`. No openclaw or open-webui restart triggered.

- [ ] **Step 5: Commit**

```bash
git add dashboard/app.py
git commit -m "refactor(dashboard): simplify /api/active-model — only swap LLAMACPP_MODEL"
```

---

### Task A6: Regression-scan for stale model identifier references

**Files:**
- Read-only sweep across repo.

- [ ] **Step 1: Grep for any remaining hardcoded GGUF basenames in test files or config**

Run: `grep -rEn "google_gemma-4-31B-it-Q4_K_M|gemma-4-31B-it-Q4_K_M" --include="*.py" --include="*.json" --include="*.yaml" --include="*.yml" --include="*.md" .`

- [ ] **Step 2: For each hit outside `.env`, `data/openclaw/openclaw.json.bak*`, and `LLAMACPP_MODEL=` lines, decide:**
  - **Test files:** Update to `local-chat`. Re-run the test to ensure it still passes meaningfully.
  - **Doc files:** Update prose to refer to `local-chat` and note the GGUF is configurable via `LLAMACPP_MODEL`.
  - **Config (.bak files):** Leave alone (historical backups).

- [ ] **Step 3: Run the full test suite**

Run: `pytest tests/ -x --tb=short`
Expected: all green. Investigate any failures introduced by the rename.

- [ ] **Step 4: Commit any test/doc updates**

```bash
git add tests/ docs/
git commit -m "test/docs: update stale GGUF-basename references to canonical local-chat"
```

---

## Phase B — Publish mcp-gateway port by default

### Task B1: Move ports stanza into base docker-compose.yml

**Files:**
- Modify: `docker-compose.yml` (mcp-gateway service block, around line 493-541)
- Modify: `overrides/mcp-expose.yml`

- [ ] **Step 1: Read the current mcp-gateway block**

Run: `sed -n '493,545p' docker-compose.yml`

- [ ] **Step 2: Add the ports stanza to the base service**

In `docker-compose.yml`, locate the `mcp-gateway:` service. Just above the `healthcheck:` line (the comment currently reads `# No host port by default (backend-only per PRD M6). For external MCP access: -f overrides/mcp-expose.yml`), insert:

```yaml
    # Published on host so remote tailnet devices can reach it (OpenClaude install,
    # external MCP clients like Cursor). Backend services still address it as
    # http://mcp-gateway:8811 over the docker network.
    ports:
      - "${MCP_GATEWAY_PORT:-8811}:8811"
```

Delete the prior comment line about "No host port by default".

- [ ] **Step 3: Replace overrides/mcp-expose.yml with a deprecation stub**

Overwrite `overrides/mcp-expose.yml` with:

```yaml
# DEPRECATED: mcp-gateway is now published on the host by default in docker-compose.yml.
# This override is intentionally a no-op so existing -f flags continue to work.
# Remove from your launch scripts at your convenience.

services: {}
```

- [ ] **Step 4: Recreate mcp-gateway and verify host-side reachability**

Run:
```
docker compose up -d --force-recreate mcp-gateway
sleep 8
curl -s http://localhost:8811/mcp -i | head -5
```
Expected: HTTP response (likely 405 Method Not Allowed for a bare GET, or a JSON-RPC handshake — anything but `Connection refused`).

- [ ] **Step 5: Commit**

```bash
git add docker-compose.yml overrides/mcp-expose.yml
git commit -m "compose: publish mcp-gateway on host by default; deprecate mcp-expose override"
```

---

## Phase C — Dashboard install logic module

### Task C1: Create the install module skeleton with hostname resolution

**Files:**
- Create: `dashboard/openclaude_install.py`
- Create: `tests/test_openclaude_install_module.py`

- [ ] **Step 1: Write the failing tests for hostname resolution**

Create `tests/test_openclaude_install_module.py`:

```python
"""Unit tests for dashboard.openclaude_install."""
from __future__ import annotations

import pytest

from dashboard.openclaude_install import (
    HostnameResolutionError,
    resolve_tailnet_hostname,
)


def test_ts_hostname_env_takes_precedence(monkeypatch):
    monkeypatch.setenv("TS_HOSTNAME", "explicit.example.ts.net")
    assert resolve_tailnet_hostname(host_header="other.example.ts.net:8080") == "explicit.example.ts.net"


def test_falls_back_to_host_header_minus_port(monkeypatch):
    monkeypatch.delenv("TS_HOSTNAME", raising=False)
    assert resolve_tailnet_hostname(host_header="my-host.tail1234.ts.net:8080") == "my-host.tail1234.ts.net"


def test_host_header_without_port(monkeypatch):
    monkeypatch.delenv("TS_HOSTNAME", raising=False)
    assert resolve_tailnet_hostname(host_header="my-host.tail1234.ts.net") == "my-host.tail1234.ts.net"


def test_localhost_host_header_raises(monkeypatch):
    monkeypatch.delenv("TS_HOSTNAME", raising=False)
    with pytest.raises(HostnameResolutionError):
        resolve_tailnet_hostname(host_header="localhost:8080")


def test_loopback_ip_host_header_raises(monkeypatch):
    monkeypatch.delenv("TS_HOSTNAME", raising=False)
    with pytest.raises(HostnameResolutionError):
        resolve_tailnet_hostname(host_header="127.0.0.1:8080")


def test_no_inputs_raises(monkeypatch):
    monkeypatch.delenv("TS_HOSTNAME", raising=False)
    with pytest.raises(HostnameResolutionError):
        resolve_tailnet_hostname(host_header=None)
```

- [ ] **Step 2: Run, verify all six tests fail with ImportError**

Run: `pytest tests/test_openclaude_install_module.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'dashboard.openclaude_install'`.

- [ ] **Step 3: Create the module with minimal hostname logic**

Create `dashboard/openclaude_install.py`:

```python
"""Install-script generation for OpenClaude on remote tailnet devices.

This module is import-safe (no side effects). All I/O is async or pure;
the FastAPI router in routes_openclaude.py wires it to HTTP.
"""
from __future__ import annotations

import os


class HostnameResolutionError(RuntimeError):
    """Raised when no usable tailnet hostname can be determined."""


_LOOPBACK_HOSTS = {"localhost", "127.0.0.1", "::1", "0.0.0.0"}


def resolve_tailnet_hostname(host_header: str | None) -> str:
    """Determine the tailnet-visible hostname the install script should embed.

    Resolution order:
      1. TS_HOSTNAME env var (explicit override)
      2. The Host header sent by the browser when the user opened the dashboard
         (Strip any :port suffix.)

    Raises HostnameResolutionError if neither yields a non-loopback hostname.
    """
    explicit = (os.environ.get("TS_HOSTNAME") or "").strip()
    if explicit:
        return explicit

    if not host_header:
        raise HostnameResolutionError(
            "Cannot determine tailnet hostname. Set TS_HOSTNAME in the dashboard env, "
            "or open the dashboard via your tailnet hostname (e.g. http://my-host.tailXXXX.ts.net:8080)."
        )

    bare = host_header.split(":", 1)[0].strip().lower()
    if bare in _LOOPBACK_HOSTS or bare.endswith(".localhost"):
        raise HostnameResolutionError(
            f"Host header is loopback ({host_header!r}). Set TS_HOSTNAME or open the dashboard "
            "via your tailnet hostname so remote devices can reach this host."
        )
    return bare
```

- [ ] **Step 4: Run, verify all six tests pass**

Run: `pytest tests/test_openclaude_install_module.py -v`
Expected: PASS (six tests).

- [ ] **Step 5: Commit**

```bash
git add dashboard/openclaude_install.py tests/test_openclaude_install_module.py
git commit -m "feat(dashboard): add openclaude_install module with hostname resolution"
```

---

### Task C2: Add blog MCP reachability preflight with TTL cache

**Files:**
- Modify: `dashboard/openclaude_install.py`
- Modify: `tests/test_openclaude_install_module.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_openclaude_install_module.py`:

```python
import time
from unittest.mock import AsyncMock, MagicMock

import pytest

from dashboard.openclaude_install import BlogMcpPreflight


@pytest.mark.asyncio
async def test_blog_preflight_returns_true_on_2xx():
    client = MagicMock()
    response = MagicMock(status_code=200)
    client.get = AsyncMock(return_value=response)

    preflight = BlogMcpPreflight(url="http://host.docker.internal:3500/mcp", ttl_seconds=10)
    assert await preflight.is_reachable(client) is True
    client.get.assert_awaited_once()


@pytest.mark.asyncio
async def test_blog_preflight_returns_false_on_connection_error():
    import httpx

    client = MagicMock()
    client.get = AsyncMock(side_effect=httpx.RequestError("connection refused", request=MagicMock()))

    preflight = BlogMcpPreflight(url="http://host.docker.internal:3500/mcp", ttl_seconds=10)
    assert await preflight.is_reachable(client) is False


@pytest.mark.asyncio
async def test_blog_preflight_caches_result_within_ttl():
    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(status_code=200))

    preflight = BlogMcpPreflight(url="http://x/mcp", ttl_seconds=60)
    await preflight.is_reachable(client)
    await preflight.is_reachable(client)
    assert client.get.await_count == 1


@pytest.mark.asyncio
async def test_blog_preflight_refreshes_after_ttl():
    client = MagicMock()
    client.get = AsyncMock(return_value=MagicMock(status_code=200))

    preflight = BlogMcpPreflight(url="http://x/mcp", ttl_seconds=0)
    await preflight.is_reachable(client)
    await preflight.is_reachable(client)
    assert client.get.await_count == 2
```

Make sure `pytest-asyncio` is available. If not, add `pytest-asyncio>=0.23` to `dashboard/requirements.txt` and install. (Most likely already present given the existing async test pattern.)

- [ ] **Step 2: Run, verify the four tests fail**

Run: `pytest tests/test_openclaude_install_module.py -k "blog_preflight" -v`
Expected: FAIL with ImportError on `BlogMcpPreflight`.

- [ ] **Step 3: Append the class to `dashboard/openclaude_install.py`**

```python
import asyncio
import time

import httpx


class BlogMcpPreflight:
    """Caches the result of a quick reachability probe to the blog MCP server.

    The blog MCP runs as a host-side process on the dashboard host (port 3500 by default).
    Whether it's running varies across deploys, so we probe before generating an install
    script and skip the entry if unreachable. Cached briefly so back-to-back installs
    don't hammer it.
    """

    def __init__(self, url: str, ttl_seconds: float = 10.0, request_timeout: float = 2.0) -> None:
        self.url = url
        self.ttl_seconds = ttl_seconds
        self.request_timeout = request_timeout
        self._cache: tuple[float, bool] | None = None
        self._lock = asyncio.Lock()

    async def is_reachable(self, client: httpx.AsyncClient) -> bool:
        async with self._lock:
            now = time.monotonic()
            if self._cache is not None and (now - self._cache[0]) < self.ttl_seconds:
                return self._cache[1]
            try:
                response = await client.get(self.url, timeout=self.request_timeout)
                ok = response.status_code < 500
            except httpx.RequestError:
                ok = False
            self._cache = (now, ok)
            return ok
```

- [ ] **Step 4: Run, verify all tests in this file pass**

Run: `pytest tests/test_openclaude_install_module.py -v`
Expected: PASS (all six original + four new = ten tests).

- [ ] **Step 5: Commit**

```bash
git add dashboard/openclaude_install.py tests/test_openclaude_install_module.py
git commit -m "feat(dashboard): add cached blog-MCP reachability preflight"
```

---

### Task C3: Add Jinja2 dependency and template loader

**Files:**
- Modify: `dashboard/requirements.txt`
- Create: `dashboard/templates/__init__.py`

- [ ] **Step 1: Add jinja2 to requirements**

Open `dashboard/requirements.txt`. Add:

```
jinja2>=3.1.0
```

- [ ] **Step 2: Create the templates package marker**

Create empty file `dashboard/templates/__init__.py`. Run:
```
mkdir -p dashboard/templates && touch dashboard/templates/__init__.py
```

- [ ] **Step 3: Rebuild dashboard image so jinja2 is installed**

Run: `docker compose build dashboard`
Expected: build succeeds, log shows `Successfully installed jinja2-...`.

- [ ] **Step 4: Commit**

```bash
git add dashboard/requirements.txt dashboard/templates/__init__.py
git commit -m "feat(dashboard): add jinja2 dependency for openclaude install templates"
```

---

### Task C4: Render the `~/.openclaude/.claude.json` body

**Files:**
- Create: `dashboard/templates/openclaude_claude_json.j2`
- Modify: `dashboard/openclaude_install.py`
- Modify: `tests/test_openclaude_install_module.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_openclaude_install_module.py`:

```python
import json

from dashboard.openclaude_install import render_claude_json


def test_render_claude_json_includes_gateway_and_local_tools_only_when_blog_unreachable():
    body = render_claude_json(
        host="my-host.tail.ts.net",
        mcp_gateway_port=8811,
        blog_reachable=False,
        blog_port=3500,
        blog_api_key="",
        local_workspace_path="/Users/me/openclaude-workspace",
    )
    parsed = json.loads(body)
    assert "gateway" in parsed["mcpServers"]
    assert "local-tools" in parsed["mcpServers"]
    assert "blog" not in parsed["mcpServers"]
    assert parsed["mcpServers"]["gateway"]["url"] == "http://my-host.tail.ts.net:8811/mcp"
    assert parsed["mcpServers"]["gateway"]["transport"] == "http"
    assert parsed["mcpServers"]["local-tools"]["transport"] == "stdio"
    assert "/Users/me/openclaude-workspace" in parsed["mcpServers"]["local-tools"]["args"]


def test_render_claude_json_includes_blog_when_reachable():
    body = render_claude_json(
        host="my-host.tail.ts.net",
        mcp_gateway_port=8811,
        blog_reachable=True,
        blog_port=3500,
        blog_api_key="secret-key-123",
        local_workspace_path="/home/me/openclaude-workspace",
    )
    parsed = json.loads(body)
    assert parsed["mcpServers"]["blog"]["url"] == "http://my-host.tail.ts.net:3500/mcp"
    assert parsed["mcpServers"]["blog"]["headers"] == {"x-api-key": "secret-key-123"}


def test_render_claude_json_omits_blog_when_no_api_key_even_if_reachable():
    body = render_claude_json(
        host="x", mcp_gateway_port=8811,
        blog_reachable=True, blog_port=3500, blog_api_key="",
        local_workspace_path="/x",
    )
    parsed = json.loads(body)
    assert "blog" not in parsed["mcpServers"]
```

- [ ] **Step 2: Create the template**

Create `dashboard/templates/openclaude_claude_json.j2`:

```jinja
{
  "mcpServers": {
    "gateway": {
      "transport": "http",
      "url": "http://{{ host }}:{{ mcp_gateway_port }}/mcp"
    }{% if include_blog %},
    "blog": {
      "transport": "http",
      "url": "http://{{ host }}:{{ blog_port }}/mcp",
      "headers": { "x-api-key": "{{ blog_api_key }}" }
    }{% endif %},
    "local-tools": {
      "transport": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "{{ local_workspace_path }}"
      ]
    }
  }
}
```

- [ ] **Step 3: Run tests, verify ImportError on render_claude_json**

Run: `pytest tests/test_openclaude_install_module.py -k "render_claude_json" -v`
Expected: FAIL with ImportError.

- [ ] **Step 4: Add the template loader and renderer to `dashboard/openclaude_install.py`**

Append:

```python
from pathlib import Path

import jinja2

_TEMPLATES_DIR = Path(__file__).resolve().parent / "templates"
_jinja_env = jinja2.Environment(
    loader=jinja2.FileSystemLoader(_TEMPLATES_DIR),
    autoescape=False,                # rendering scripts/JSON, not HTML
    trim_blocks=True,
    lstrip_blocks=True,
    undefined=jinja2.StrictUndefined,
)


def render_claude_json(
    *,
    host: str,
    mcp_gateway_port: int,
    blog_reachable: bool,
    blog_port: int,
    blog_api_key: str,
    local_workspace_path: str,
) -> str:
    """Render the body of ~/.openclaude/.claude.json for a remote device.

    Blog entry is included only when both reachable AND an API key is configured —
    a reachable-but-keyless blog server would fail auth at runtime.
    """
    template = _jinja_env.get_template("openclaude_claude_json.j2")
    return template.render(
        host=host,
        mcp_gateway_port=mcp_gateway_port,
        blog_port=blog_port,
        blog_api_key=blog_api_key,
        local_workspace_path=local_workspace_path,
        include_blog=bool(blog_reachable and blog_api_key),
    )
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `pytest tests/test_openclaude_install_module.py -v`
Expected: PASS (all 13 tests).

- [ ] **Step 6: Commit**

```bash
git add dashboard/openclaude_install.py dashboard/templates/openclaude_claude_json.j2 tests/test_openclaude_install_module.py
git commit -m "feat(dashboard): render ~/.openclaude/.claude.json body via jinja template"
```

---

### Task C5: Render the per-OS install scripts

**Files:**
- Create: `dashboard/templates/openclaude_install.sh.j2`
- Create: `dashboard/templates/openclaude_install.ps1.j2`
- Modify: `dashboard/openclaude_install.py`
- Modify: `tests/test_openclaude_install_module.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_openclaude_install_module.py`:

```python
from dashboard.openclaude_install import render_install_script_sh, render_install_script_ps1


def _render_kwargs(blog_reachable=False):
    return dict(
        host="my-host.tail.ts.net",
        model_gateway_port=11435,
        mcp_gateway_port=8811,
        master_key="local",
        blog_reachable=blog_reachable,
        blog_port=3500,
        blog_api_key="key" if blog_reachable else "",
    )


def test_sh_script_contains_required_actions():
    script = render_install_script_sh(**_render_kwargs())
    assert script.startswith("#!/usr/bin/env sh")
    assert "command -v node" in script           # Node check
    assert "command -v rg" in script              # ripgrep check
    assert "npm install -g @gitlawb/openclaude" in script
    assert 'CLAUDE_CONFIG_DIR="$HOME/.openclaude"' in script
    assert 'OPENAI_BASE_URL="http://my-host.tail.ts.net:11435/v1"' in script
    assert 'OPENAI_API_KEY="local"' in script
    assert 'exec openclaude --model local-chat "$@"' in script


def test_sh_script_writes_claude_json_with_local_tools_path():
    script = render_install_script_sh(**_render_kwargs())
    # Per-device workspace path is resolved at runtime by the script ($HOME-relative).
    assert "$HOME/openclaude-workspace" in script
    assert "mkdir -p" in script


def test_ps1_script_contains_required_actions():
    script = render_install_script_ps1(**_render_kwargs())
    assert "#requires -version 5" in script.lower() or "#Requires" in script
    assert "Get-Command node" in script
    assert "Get-Command rg" in script
    assert "npm install -g @gitlawb/openclaude" in script
    assert "$env:CLAUDE_CONFIG_DIR" in script
    assert "openclaude --model local-chat" in script


def test_sh_script_omits_blog_block_when_unreachable():
    script = render_install_script_sh(**_render_kwargs(blog_reachable=False))
    assert '"blog"' not in script


def test_sh_script_includes_blog_block_when_reachable():
    script = render_install_script_sh(**_render_kwargs(blog_reachable=True))
    assert '"blog"' in script
    assert "x-api-key" in script
```

- [ ] **Step 2: Create the POSIX template**

Create `dashboard/templates/openclaude_install.sh.j2`:

```jinja
#!/usr/bin/env sh
# OpenClaude self-install for {{ host }}
# Generated by the dashboard at install time. Re-run any time to re-sync.
set -eu

HOST="{{ host }}"
MODEL_GATEWAY="http://${HOST}:{{ model_gateway_port }}/v1"
MCP_GATEWAY="http://${HOST}:{{ mcp_gateway_port }}/mcp"
{% if include_blog %}BLOG_MCP="http://${HOST}:{{ blog_port }}/mcp"
BLOG_API_KEY="{{ blog_api_key }}"
{% endif %}MASTER_KEY="{{ master_key }}"

echo "==> Checking prerequisites"
if ! command -v node >/dev/null 2>&1; then
  echo "ERROR: Node.js not found. Install from https://nodejs.org/ then re-run." >&2
  exit 1
fi
if ! command -v rg >/dev/null 2>&1; then
  echo "ERROR: ripgrep not found. Install with 'brew install ripgrep' (macOS) or your package manager, then re-run." >&2
  exit 1
fi

echo "==> Installing @gitlawb/openclaude"
npm install -g @gitlawb/openclaude

CONFIG_DIR="$HOME/.openclaude"
WORKSPACE_DIR="$HOME/openclaude-workspace"
mkdir -p "$CONFIG_DIR" "$WORKSPACE_DIR"

echo "==> Writing $CONFIG_DIR/.claude.json"
cat > "$CONFIG_DIR/.claude.json" <<EOF
{
  "mcpServers": {
    "gateway": {
      "transport": "http",
      "url": "${MCP_GATEWAY}"
    },{% if include_blog %}
    "blog": {
      "transport": "http",
      "url": "${BLOG_MCP}",
      "headers": { "x-api-key": "${BLOG_API_KEY}" }
    },{% endif %}
    "local-tools": {
      "transport": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "${WORKSPACE_DIR}"
      ]
    }
  }
}
EOF

echo "==> Writing $CONFIG_DIR/settings.json"
cat > "$CONFIG_DIR/settings.json" <<EOF
{ "model": "local-chat" }
EOF

WRAPPER_DIR="$HOME/.local/bin"
WRAPPER="$WRAPPER_DIR/openclaude-local"
mkdir -p "$WRAPPER_DIR"

echo "==> Writing wrapper $WRAPPER"
cat > "$WRAPPER" <<EOF
#!/usr/bin/env sh
export CLAUDE_CONFIG_DIR="\$HOME/.openclaude"
export OPENAI_BASE_URL="${MODEL_GATEWAY}"
export OPENAI_API_KEY="${MASTER_KEY}"
exec openclaude --model local-chat "\$@"
EOF
chmod +x "$WRAPPER"

case ":$PATH:" in
  *":$WRAPPER_DIR:"*) : ;;
  *) echo "NOTE: $WRAPPER_DIR is not on your PATH. Add it to your shell profile to use 'openclaude-local' directly." ;;
esac

echo
echo "Installed. Run 'openclaude-local' (or '$WRAPPER' directly) to start."
echo "Re-run this installer any time to re-sync with the host."
```

- [ ] **Step 3: Create the PowerShell template**

Create `dashboard/templates/openclaude_install.ps1.j2`:

```jinja
#Requires -Version 5
# OpenClaude self-install for {{ host }}
# Generated by the dashboard at install time. Re-run any time to re-sync.

$ErrorActionPreference = "Stop"

$Host_         = "{{ host }}"
$ModelGateway  = "http://${Host_}:{{ model_gateway_port }}/v1"
$McpGateway    = "http://${Host_}:{{ mcp_gateway_port }}/mcp"
{% if include_blog %}$BlogMcp       = "http://${Host_}:{{ blog_port }}/mcp"
$BlogApiKey    = "{{ blog_api_key }}"
{% endif %}$MasterKey     = "{{ master_key }}"

Write-Host "==> Checking prerequisites"
if (-not (Get-Command node -ErrorAction SilentlyContinue)) {
    Write-Error "Node.js not found. Install from https://nodejs.org/ then re-run."
    exit 1
}
if (-not (Get-Command rg -ErrorAction SilentlyContinue)) {
    Write-Error "ripgrep not found. Install with 'winget install BurntSushi.ripgrep.MSVC' then re-run."
    exit 1
}

Write-Host "==> Installing @gitlawb/openclaude"
npm install -g "@gitlawb/openclaude"
if ($LASTEXITCODE -ne 0) { exit $LASTEXITCODE }

$ConfigDir    = Join-Path $env:USERPROFILE ".openclaude"
$WorkspaceDir = Join-Path $env:USERPROFILE "openclaude-workspace"
New-Item -ItemType Directory -Force -Path $ConfigDir, $WorkspaceDir | Out-Null

$WorkspaceForJson = $WorkspaceDir -replace '\\', '\\'

Write-Host "==> Writing $ConfigDir\.claude.json"
$ClaudeJson = @"
{
  "mcpServers": {
    "gateway": {
      "transport": "http",
      "url": "$McpGateway"
    },{% if include_blog %}
    "blog": {
      "transport": "http",
      "url": "$BlogMcp",
      "headers": { "x-api-key": "$BlogApiKey" }
    },{% endif %}
    "local-tools": {
      "transport": "stdio",
      "command": "npx",
      "args": [
        "-y",
        "@modelcontextprotocol/server-filesystem",
        "$WorkspaceForJson"
      ]
    }
  }
}
"@
Set-Content -Path (Join-Path $ConfigDir ".claude.json") -Value $ClaudeJson -Encoding UTF8

Write-Host "==> Writing $ConfigDir\settings.json"
Set-Content -Path (Join-Path $ConfigDir "settings.json") -Value '{ "model": "local-chat" }' -Encoding UTF8

$WrapperDir = Join-Path $env:LOCALAPPDATA "openclaude"
$Wrapper    = Join-Path $WrapperDir "openclaude-local.cmd"
New-Item -ItemType Directory -Force -Path $WrapperDir | Out-Null

Write-Host "==> Writing wrapper $Wrapper"
$WrapperBody = @"
@echo off
set "CLAUDE_CONFIG_DIR=%USERPROFILE%\.openclaude"
set "OPENAI_BASE_URL=$ModelGateway"
set "OPENAI_API_KEY=$MasterKey"
openclaude --model local-chat %*
"@
Set-Content -Path $Wrapper -Value $WrapperBody -Encoding ASCII

# Ensure wrapper dir is on the user's PATH (idempotent).
$UserPath = [Environment]::GetEnvironmentVariable("Path", "User")
if ($UserPath -notlike "*$WrapperDir*") {
    [Environment]::SetEnvironmentVariable("Path", "$UserPath;$WrapperDir", "User")
    Write-Host "Added $WrapperDir to your user PATH. Open a new terminal to pick it up."
}

Write-Host ""
Write-Host "Installed. Run 'openclaude-local' (in a new terminal) to start."
Write-Host "Re-run this installer any time to re-sync with the host."
```

- [ ] **Step 4: Append the renderer functions to `dashboard/openclaude_install.py`**

```python
def render_install_script_sh(
    *,
    host: str,
    model_gateway_port: int,
    mcp_gateway_port: int,
    master_key: str,
    blog_reachable: bool,
    blog_port: int,
    blog_api_key: str,
) -> str:
    """Render the POSIX install script (macOS / Linux)."""
    template = _jinja_env.get_template("openclaude_install.sh.j2")
    return template.render(
        host=host,
        model_gateway_port=model_gateway_port,
        mcp_gateway_port=mcp_gateway_port,
        master_key=master_key,
        blog_port=blog_port,
        blog_api_key=blog_api_key,
        include_blog=bool(blog_reachable and blog_api_key),
    )


def render_install_script_ps1(
    *,
    host: str,
    model_gateway_port: int,
    mcp_gateway_port: int,
    master_key: str,
    blog_reachable: bool,
    blog_port: int,
    blog_api_key: str,
) -> str:
    """Render the PowerShell install script (Windows)."""
    template = _jinja_env.get_template("openclaude_install.ps1.j2")
    return template.render(
        host=host,
        model_gateway_port=model_gateway_port,
        mcp_gateway_port=mcp_gateway_port,
        master_key=master_key,
        blog_port=blog_port,
        blog_api_key=blog_api_key,
        include_blog=bool(blog_reachable and blog_api_key),
    )
```

- [ ] **Step 5: Run tests, verify all pass**

Run: `pytest tests/test_openclaude_install_module.py -v`
Expected: PASS (all 18 tests).

- [ ] **Step 6: Commit**

```bash
git add dashboard/openclaude_install.py dashboard/templates/openclaude_install.sh.j2 dashboard/templates/openclaude_install.ps1.j2 tests/test_openclaude_install_module.py
git commit -m "feat(dashboard): render per-OS openclaude install scripts via jinja templates"
```

---

## Phase D — Dashboard install routes

### Task D1: Add /api/openclaude/preview route

**Files:**
- Create: `dashboard/routes_openclaude.py`
- Create: `tests/test_openclaude_install_routes.py`
- Modify: `dashboard/app.py`

- [ ] **Step 1: Write failing tests for /api/openclaude/preview**

Create `tests/test_openclaude_install_routes.py`:

```python
"""Integration tests for dashboard openclaude install routes."""
from __future__ import annotations

import os
import sys
from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi.testclient import TestClient

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))


@pytest.fixture
def client(monkeypatch):
    monkeypatch.setenv("TS_HOSTNAME", "host.tailtest.ts.net")
    monkeypatch.setenv("LITELLM_MASTER_KEY", "local")
    monkeypatch.setenv("BLOG_MCP_API_KEY", "")  # blog disabled by default in tests

    import dashboard.app as dashboard_app

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=500))  # blog unreachable
    monkeypatch.setattr("dashboard.app._http_client", mock_client)

    async def _stub_check(url: str, client=None):
        return (True, "")
    monkeypatch.setattr("dashboard.services_catalog._check_service", _stub_check)

    return TestClient(dashboard_app.app)


def test_preview_returns_200_and_expected_keys(client):
    r = client.get("/api/openclaude/preview")
    assert r.status_code == 200
    data = r.json()
    for key in ("host", "model_gateway_url", "mcp_gateway_url", "blog_mcp_reachable",
                "model", "one_liner_ps1", "one_liner_sh"):
        assert key in data, f"missing key {key}"
    assert data["host"] == "host.tailtest.ts.net"
    assert data["model"] == "local-chat"
    assert data["model_gateway_url"] == "http://host.tailtest.ts.net:11435/v1"
    assert data["mcp_gateway_url"] == "http://host.tailtest.ts.net:8811/mcp"
    assert data["one_liner_sh"].startswith("curl -fsSL http://host.tailtest.ts.net:8080/install/openclaude.sh")
    assert data["one_liner_ps1"].startswith("irm http://host.tailtest.ts.net:8080/install/openclaude.ps1")


def test_preview_503_when_no_hostname(monkeypatch):
    monkeypatch.delenv("TS_HOSTNAME", raising=False)
    import dashboard.app as dashboard_app

    mock_client = MagicMock()
    monkeypatch.setattr("dashboard.app._http_client", mock_client)

    c = TestClient(dashboard_app.app)
    # FastAPI sends Host: testserver by default — that's not loopback-listed but
    # we want to verify the explicit-loopback failure mode separately.
    r = c.get("/api/openclaude/preview", headers={"Host": "localhost:8080"})
    assert r.status_code == 503
    assert "TS_HOSTNAME" in r.json().get("detail", "")
```

- [ ] **Step 2: Run, verify tests fail (router not registered)**

Run: `pytest tests/test_openclaude_install_routes.py -v`
Expected: FAIL — 404 on /api/openclaude/preview.

- [ ] **Step 3: Create the router file**

Create `dashboard/routes_openclaude.py`:

```python
"""FastAPI routes for OpenClaude self-serve install on remote tailnet devices."""
from __future__ import annotations

import os

from fastapi import APIRouter, HTTPException, Request
from fastapi.responses import PlainTextResponse

from dashboard.openclaude_install import (
    BlogMcpPreflight,
    HostnameResolutionError,
    render_claude_json,
    render_install_script_ps1,
    render_install_script_sh,
    resolve_tailnet_hostname,
)

router = APIRouter(tags=["openclaude"])

_DEFAULT_DASHBOARD_PORT = 8080
_DEFAULT_MODEL_GATEWAY_PORT = 11435
_DEFAULT_MCP_GATEWAY_PORT = 8811
_DEFAULT_BLOG_PORT = 3500

_blog_preflight = BlogMcpPreflight(
    url=f"http://host.docker.internal:{_DEFAULT_BLOG_PORT}/mcp",
    ttl_seconds=10.0,
)


def _ports() -> tuple[int, int, int, int]:
    return (
        int(os.environ.get("DASHBOARD_PORT", _DEFAULT_DASHBOARD_PORT)),
        int(os.environ.get("MODEL_GATEWAY_PORT", _DEFAULT_MODEL_GATEWAY_PORT)),
        int(os.environ.get("MCP_GATEWAY_PORT", _DEFAULT_MCP_GATEWAY_PORT)),
        int(os.environ.get("BLOG_MCP_PORT", _DEFAULT_BLOG_PORT)),
    )


def _resolve_host_or_503(request: Request) -> str:
    try:
        return resolve_tailnet_hostname(host_header=request.headers.get("host"))
    except HostnameResolutionError as exc:
        raise HTTPException(status_code=503, detail=str(exc)) from exc


@router.get("/api/openclaude/preview")
async def preview(request: Request):
    from dashboard.app import _get_http_client
    host = _resolve_host_or_503(request)
    dashboard_port, model_port, mcp_port, blog_port = _ports()
    blog_api_key = os.environ.get("BLOG_MCP_API_KEY", "")
    blog_reachable = await _blog_preflight.is_reachable(_get_http_client())
    return {
        "host": host,
        "model_gateway_url": f"http://{host}:{model_port}/v1",
        "mcp_gateway_url": f"http://{host}:{mcp_port}/mcp",
        "blog_mcp_reachable": bool(blog_reachable and blog_api_key),
        "model": "local-chat",
        "one_liner_ps1": (
            f"irm http://{host}:{dashboard_port}/install/openclaude.ps1 | iex"
        ),
        "one_liner_sh": (
            f"curl -fsSL http://{host}:{dashboard_port}/install/openclaude.sh | bash"
        ),
    }
```

- [ ] **Step 4: Wire router into `dashboard/app.py`**

Open `dashboard/app.py`. Locate the existing router includes (around line 91-92):
```python
app.include_router(hub_router)
app.include_router(orchestration_router)
```

Add the import at the top with other router imports (around line 31-32):
```python
from dashboard.routes_openclaude import router as openclaude_router
```

Then add below the existing includes:
```python
app.include_router(openclaude_router)
```

- [ ] **Step 5: Run tests, verify they pass**

Run: `pytest tests/test_openclaude_install_routes.py -v`
Expected: PASS (both tests).

- [ ] **Step 6: Commit**

```bash
git add dashboard/routes_openclaude.py dashboard/app.py tests/test_openclaude_install_routes.py
git commit -m "feat(dashboard): add /api/openclaude/preview route"
```

---

### Task D2: Add /install/openclaude.{sh,ps1} routes

**Files:**
- Modify: `dashboard/routes_openclaude.py`
- Modify: `tests/test_openclaude_install_routes.py`

- [ ] **Step 1: Append failing tests**

Append to `tests/test_openclaude_install_routes.py`:

```python
def test_install_sh_returns_text_plain_with_substituted_host(client):
    r = client.get("/install/openclaude.sh")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    assert r.headers["cache-control"] == "no-store"
    body = r.text
    assert body.startswith("#!/usr/bin/env sh")
    assert "host.tailtest.ts.net" in body
    assert "OPENAI_BASE_URL=\"http://host.tailtest.ts.net:11435/v1\"" in body
    assert "openclaude --model local-chat" in body


def test_install_ps1_returns_text_plain_with_substituted_host(client):
    r = client.get("/install/openclaude.ps1")
    assert r.status_code == 200
    assert r.headers["content-type"].startswith("text/plain")
    body = r.text
    assert "host.tailtest.ts.net" in body
    assert "openclaude --model local-chat" in body


def test_install_sh_omits_blog_when_blog_unreachable(client):
    r = client.get("/install/openclaude.sh")
    assert '"blog"' not in r.text


def test_install_503_when_no_hostname(monkeypatch):
    monkeypatch.delenv("TS_HOSTNAME", raising=False)
    import dashboard.app as dashboard_app

    mock_client = MagicMock()
    mock_client.get = AsyncMock(return_value=MagicMock(status_code=500))
    monkeypatch.setattr("dashboard.app._http_client", mock_client)

    c = TestClient(dashboard_app.app)
    r = c.get("/install/openclaude.sh", headers={"Host": "localhost:8080"})
    assert r.status_code == 503
```

- [ ] **Step 2: Run, verify tests fail (404)**

Run: `pytest tests/test_openclaude_install_routes.py -v`
Expected: 4 new tests fail (404).

- [ ] **Step 3: Append routes to `dashboard/routes_openclaude.py`**

```python
async def _build_install_render_kwargs(request: Request) -> dict:
    from dashboard.app import _get_http_client
    host = _resolve_host_or_503(request)
    _, model_port, mcp_port, blog_port = _ports()
    blog_api_key = os.environ.get("BLOG_MCP_API_KEY", "")
    blog_reachable = await _blog_preflight.is_reachable(_get_http_client())
    master_key = os.environ.get("LITELLM_MASTER_KEY", "local")
    return dict(
        host=host,
        model_gateway_port=model_port,
        mcp_gateway_port=mcp_port,
        master_key=master_key,
        blog_reachable=blog_reachable,
        blog_port=blog_port,
        blog_api_key=blog_api_key,
    )


@router.get("/install/openclaude.sh", response_class=PlainTextResponse)
async def install_sh(request: Request):
    kwargs = await _build_install_render_kwargs(request)
    body = render_install_script_sh(**kwargs)
    return PlainTextResponse(body, headers={"Cache-Control": "no-store"})


@router.get("/install/openclaude.ps1", response_class=PlainTextResponse)
async def install_ps1(request: Request):
    kwargs = await _build_install_render_kwargs(request)
    body = render_install_script_ps1(**kwargs)
    return PlainTextResponse(body, headers={"Cache-Control": "no-store"})
```

- [ ] **Step 4: Run all route tests**

Run: `pytest tests/test_openclaude_install_routes.py -v`
Expected: PASS (all 6 tests).

- [ ] **Step 5: Manual smoke test against the running dashboard**

```
curl -s -H "Host: host.tailtest.ts.net:8080" http://localhost:8080/install/openclaude.sh | head -30
curl -s -H "Host: host.tailtest.ts.net:8080" http://localhost:8080/api/openclaude/preview | python -m json.tool
```
Expected: shell script with `host.tailtest.ts.net` substituted; preview JSON with all keys.

- [ ] **Step 6: Commit**

```bash
git add dashboard/routes_openclaude.py tests/test_openclaude_install_routes.py
git commit -m "feat(dashboard): add /install/openclaude.{sh,ps1} routes"
```

---

## Phase E — Install script integration test

### Task E1: Run rendered POSIX script in an Ubuntu container

**Files:**
- Create: `tests/test_openclaude_install_script_integration.py`
- Create: `tests/fixtures/openclaude_install/Dockerfile`
- Create: `tests/fixtures/openclaude_install/stub-openclaude.sh`

- [ ] **Step 1: Create the test container files**

Create `tests/fixtures/openclaude_install/Dockerfile`:

```dockerfile
FROM ubuntu:24.04
RUN apt-get update && apt-get install -y --no-install-recommends \
      curl ca-certificates ripgrep nodejs npm \
    && rm -rf /var/lib/apt/lists/*

# Install a stub `openclaude` that echoes its env and args, so the wrapper test
# can verify what would have been launched without actually running OpenClaude.
COPY stub-openclaude.sh /usr/local/bin/openclaude
RUN chmod +x /usr/local/bin/openclaude

# Stub `npm install -g` to a no-op (the stub openclaude is already present).
RUN printf '#!/bin/sh\nif [ "$1 $2" = "install -g" ]; then exit 0; fi\nexec /usr/bin/npm "$@"\n' > /usr/local/bin/npm-shim \
    && chmod +x /usr/local/bin/npm-shim \
    && ln -sf /usr/local/bin/npm-shim /usr/local/bin/npm

WORKDIR /work
```

Create `tests/fixtures/openclaude_install/stub-openclaude.sh`:

```sh
#!/bin/sh
echo "STUB_OPENCLAUDE_RAN"
echo "CLAUDE_CONFIG_DIR=$CLAUDE_CONFIG_DIR"
echo "OPENAI_BASE_URL=$OPENAI_BASE_URL"
echo "OPENAI_API_KEY=$OPENAI_API_KEY"
echo "ARGS=$*"
```

- [ ] **Step 2: Write the failing integration test**

Create `tests/test_openclaude_install_script_integration.py`:

```python
"""Integration test: render the POSIX install script via the module and execute
it inside an Ubuntu container with a stubbed openclaude/npm. Asserts that the
config files are written, the wrapper is on PATH, and the wrapper exec'd
openclaude with the right env vars.

Marked with `pytest.mark.integration` so it can be excluded in fast CI runs.
"""
from __future__ import annotations

import os
import shutil
import subprocess
import textwrap
from pathlib import Path

import pytest

pytestmark = pytest.mark.integration

REPO_ROOT = Path(__file__).resolve().parent.parent
FIXTURE_DIR = REPO_ROOT / "tests" / "fixtures" / "openclaude_install"
IMAGE_TAG = "openclaude-install-test:latest"


@pytest.fixture(scope="module")
def docker_image():
    if shutil.which("docker") is None:
        pytest.skip("docker not available on this runner")
    subprocess.run(
        ["docker", "build", "-t", IMAGE_TAG, str(FIXTURE_DIR)],
        check=True,
    )
    yield IMAGE_TAG


def _render_script() -> str:
    from dashboard.openclaude_install import render_install_script_sh
    return render_install_script_sh(
        host="test-host.tail.ts.net",
        model_gateway_port=11435,
        mcp_gateway_port=8811,
        master_key="local",
        blog_reachable=False,
        blog_port=3500,
        blog_api_key="",
    )


def _run(image: str, script_body: str) -> subprocess.CompletedProcess:
    """Execute the install script + invoke wrapper inside the container."""
    inner_cmd = textwrap.dedent("""
        set -e
        echo "$INSTALL_SCRIPT" > /tmp/install.sh
        sh /tmp/install.sh
        echo "---"
        ls -la $HOME/.openclaude/
        echo "---"
        cat $HOME/.openclaude/.claude.json
        echo "---"
        cat $HOME/.openclaude/settings.json
        echo "---"
        $HOME/.local/bin/openclaude-local
    """)
    return subprocess.run(
        [
            "docker", "run", "--rm",
            "-e", f"INSTALL_SCRIPT={script_body}",
            image, "sh", "-c", inner_cmd,
        ],
        capture_output=True, text=True, check=False,
    )


def test_install_script_writes_config_and_wrapper_invokes_openclaude(docker_image):
    script = _render_script()
    result = _run(docker_image, script)
    assert result.returncode == 0, f"stderr: {result.stderr}\nstdout: {result.stdout}"
    out = result.stdout

    # Config files written
    assert ".claude.json" in out
    assert "settings.json" in out
    assert '"local-tools"' in out
    assert '"local-chat"' in out

    # Wrapper script invoked openclaude with the right env
    assert "STUB_OPENCLAUDE_RAN" in out
    assert "CLAUDE_CONFIG_DIR=/root/.openclaude" in out
    assert "OPENAI_BASE_URL=http://test-host.tail.ts.net:11435/v1" in out
    assert "OPENAI_API_KEY=local" in out
    assert "ARGS=--model local-chat" in out
```

- [ ] **Step 3: Run the test**

Run: `pytest tests/test_openclaude_install_script_integration.py -v -m integration`
Expected: PASS. If docker is unavailable on the runner, the test skips cleanly.

- [ ] **Step 4: Add the integration marker if not already configured**

Check `pyproject.toml` for `[tool.pytest.ini_options].markers`. If absent, add:

```toml
[tool.pytest.ini_options]
markers = [
    "integration: end-to-end tests requiring docker; opt-in with -m integration",
]
```

(Or extend the existing markers list.)

- [ ] **Step 5: Commit**

```bash
git add tests/fixtures/openclaude_install/ tests/test_openclaude_install_script_integration.py pyproject.toml
git commit -m "test: integration test for openclaude install script in ubuntu container"
```

---

## Phase F — Dashboard UI card

### Task F1: Add the "Add OpenClaude to a device" card to index.html

**Files:**
- Modify: `dashboard/static/index.html`

- [ ] **Step 1: Locate a good insertion point**

Run: `grep -n "Unified download row\|Unified Model Hub" dashboard/static/index.html | head -5`

Pick a sensible spot (the existing model-hub area is a natural neighbor; insert as a sibling card). Identify the closing `</div>` of an adjacent card so the new card sits at the same DOM depth.

- [ ] **Step 2: Insert the card markup**

In `dashboard/static/index.html`, immediately after the chosen sibling card's closing `</div>`, insert:

```html
      <!-- OpenClaude self-serve install -->
      <div class="card" id="openclaude-install-card">
        <h2>Add OpenClaude to a device</h2>
        <div id="openclaude-install-status" class="muted">Loading…</div>
        <div id="openclaude-install-body" hidden>
          <p>
            Detected tailnet host:
            <code id="openclaude-install-host"></code>
            <span id="openclaude-install-host-warn" class="warn" hidden></span>
          </p>
          <div class="row">
            <label><input type="radio" name="openclaude-os" value="sh" checked> macOS / Linux (bash)</label>
            <label style="margin-left:1em;"><input type="radio" name="openclaude-os" value="ps1"> Windows (PowerShell)</label>
          </div>
          <pre id="openclaude-install-oneliner" class="oneliner"></pre>
          <button type="button" id="openclaude-install-copy">Copy</button>
          <p class="status-row">
            Status:
            <span class="ok">model-gateway ✓</span>
            <span class="ok">mcp-gateway ✓</span>
            <span id="openclaude-install-blog-status"></span>
          </p>
          <p class="muted">After install, run <code>openclaude-local</code> on that device.</p>
        </div>
      </div>
```

(Match the existing card class names in the file — if cards use `class="panel"` instead of `class="card"`, adjust accordingly. Likewise for `muted`, `warn`, etc. Reuse what's already there.)

- [ ] **Step 3: Add the script logic**

Locate the existing `<script>` block at the bottom of the file (the `'/api/models/download'` fetch flow at line ~2540 is in the same block). Append at the end of that block, just before the closing `</script>`:

```javascript
// --- OpenClaude self-serve install card ---
(async function initOpenClaudeInstallCard() {
  const statusEl   = document.getElementById('openclaude-install-status');
  const bodyEl     = document.getElementById('openclaude-install-body');
  const hostEl     = document.getElementById('openclaude-install-host');
  const hostWarnEl = document.getElementById('openclaude-install-host-warn');
  const lineEl     = document.getElementById('openclaude-install-oneliner');
  const blogEl     = document.getElementById('openclaude-install-blog-status');
  const copyBtn    = document.getElementById('openclaude-install-copy');
  if (!statusEl) return;

  let preview = null;
  try {
    const r = await api('/api/openclaude/preview');
    if (r.status === 503) {
      const err = await r.json().catch(() => ({}));
      statusEl.textContent = 'Tailnet hostname not detected. ' + (err.detail || '');
      return;
    }
    preview = await r.json();
  } catch (e) {
    statusEl.textContent = 'Could not load preview: ' + e.message;
    return;
  }

  hostEl.textContent = preview.host;
  blogEl.innerHTML = preview.blog_mcp_reachable
    ? '<span class="ok">blog-mcp ✓</span>'
    : '<span class="warn">blog-mcp ⚠ skipped</span>';

  function refreshOneLiner() {
    const os = document.querySelector('input[name="openclaude-os"]:checked').value;
    lineEl.textContent = os === 'ps1' ? preview.one_liner_ps1 : preview.one_liner_sh;
  }
  document.querySelectorAll('input[name="openclaude-os"]').forEach(el => {
    el.addEventListener('change', refreshOneLiner);
  });
  refreshOneLiner();

  copyBtn.addEventListener('click', async () => {
    try {
      await navigator.clipboard.writeText(lineEl.textContent);
      const orig = copyBtn.textContent;
      copyBtn.textContent = 'Copied';
      setTimeout(() => { copyBtn.textContent = orig; }, 1500);
    } catch (e) {
      copyBtn.textContent = 'Copy failed';
    }
  });

  statusEl.hidden = true;
  bodyEl.hidden = false;
})();
```

(The `api()` helper already exists in this file — confirm with `grep -n "function api\|const api" dashboard/static/index.html`. Use the same name as the rest of the file.)

- [ ] **Step 4: Manual smoke test**

Open the dashboard in your browser via the tailnet hostname (e.g. `http://your-machine.tailXXXX.ts.net:8080`). The new card should appear, show the detected hostname, and let you toggle between bash and PowerShell one-liners. Click Copy and paste into a terminal to verify.

If you see "Tailnet hostname not detected", set `TS_HOSTNAME` in `.env` and recreate the dashboard:
```
docker compose up -d --force-recreate dashboard
```

- [ ] **Step 5: Commit**

```bash
git add dashboard/static/index.html
git commit -m "feat(dashboard): add 'Add OpenClaude to a device' card with OS toggle and copy"
```

---

## Phase G — End-to-end smoke test

### Task G1: Document and execute manual smoke test on a second device

**Files:**
- Create: `docs/superpowers/plans/2026-04-16-openclaude-self-serve-install-smoke-results.md`

- [ ] **Step 1: Run the one-liner on the user's MacBook (or a second tailnet device)**

On the remote device, paste the bash one-liner from the dashboard card. Confirm:
- Script completes with exit 0.
- `~/.openclaude/.claude.json` exists with the expected MCP entries.
- `~/.openclaude/settings.json` exists.
- `~/.local/bin/openclaude-local` is on PATH (after a shell restart if needed).

- [ ] **Step 2: Run `openclaude-local` and verify connectivity**

Run: `openclaude-local`
Expected: OpenClaude TUI launches, model picker shows `local-chat`. Type a prompt — response should come from the host's loaded GGUF.

In the OpenClaude TUI, list MCP tools (e.g. `/mcp` or whatever command openclaude provides). Confirm `gateway`, `local-tools`, and (if the host has a blog server with key) `blog` are listed.

- [ ] **Step 3: Verify model-swap propagation**

On the host, swap models via the dashboard (e.g. switch GGUF). Wait for llamacpp recreate. On the remote device, send a fresh prompt in OpenClaude. Expected: continues to work — no config change needed on the remote.

- [ ] **Step 4: Verify Claude Code is unaffected**

If Claude Code is installed on the remote device, run `claude --version` and `cat ~/.claude.json` (the original Claude Code config). Confirm:
- Claude Code launches normally.
- `~/.claude.json` and `~/.claude/settings.json` are untouched.
- `CLAUDE_CONFIG_DIR` is not set in the user's shell profile (only in the wrapper).

- [ ] **Step 5: Write up the smoke test result**

Create `docs/superpowers/plans/2026-04-16-openclaude-self-serve-install-smoke-results.md` with:

```markdown
# OpenClaude Self-Serve Install — Smoke Test Results

**Date:** YYYY-MM-DD
**Tester:** Cam Lynch
**Devices tested:** <list>

## Results

- [ ] One-liner install completed cleanly on macOS
- [ ] One-liner install completed cleanly on Windows
- [ ] `openclaude-local` launches and connects to host gateway
- [ ] All expected MCP servers visible in `/mcp` listing
- [ ] Model swap on host propagates without device-side action
- [ ] Claude Code on the same device unaffected
- [ ] Re-running installer is idempotent

## Notes / issues found

(Anything to follow up on.)
```

Fill in the boxes after testing. Commit:

```bash
git add docs/superpowers/plans/2026-04-16-openclaude-self-serve-install-smoke-results.md
git commit -m "docs: openclaude self-serve install smoke test results"
```

---

## Wrap-up

After Phase G passes, the feature is complete. Suggested follow-ups (not in this plan):

- Linux desktop variant (the bash script likely works as-is; just expand testing).
- Fold a "Re-sync" button into the dashboard card that copies the same one-liner with a `# re-sync` comment, for users who don't want to remember the URL.
- Surface OpenClaude versions installed across devices (would require a small phone-home from each `openclaude-local` invocation; out of scope unless the user asks).
- If `BLOG_MCP_API_KEY` ends up being a different env var name than assumed (open question in spec), update the env reads in `routes_openclaude.py` and `_build_install_render_kwargs`.
