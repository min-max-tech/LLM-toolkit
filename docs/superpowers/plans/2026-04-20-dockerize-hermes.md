# Dockerize Hermes Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Move Hermes Agent from host-mode install to two first-class Docker compose services so `docker compose up -d` brings the whole stack online atomically.

**Architecture:** One multi-stage Dockerfile under `hermes/` builds a single image running either `hermes gateway` or `hermes dashboard --port 9119 --host 0.0.0.0 --no-open`. Two compose services share the image and mount `${BASE_PATH}:/workspace` (repo) + `${DATA_PATH}/hermes:/home/hermes/.hermes` (state). Dashboard probe switches to internal DNS. Host-mode files (`scripts/start-hermes-host.sh`, `tests/test_start_hermes_host.py`) are deleted.

**Tech Stack:** Docker, Docker Compose, Python 3.11 (runtime), Node 20 (build-only for web UI), bash, pytest + pyyaml.

**Spec:** `docs/superpowers/specs/2026-04-20-dockerize-hermes-design.md`.

**Branch:** `feat/dockerize-hermes` off `main` at `61c14a7`.

**Operator uncommitted state to preserve** (do NOT sweep into commits):
- Modified: `.gitignore`, `overrides/compute.yml`
- Untracked: `ops-controller/entrypoint.sh`, `test_output.log`

Use targeted `git add <path>` — never `git add .` or `git add -A`.

---

### Task 1: Write the failing test file

**Files:**
- Create: `tests/test_hermes_docker.py`

- [ ] **Step 1: Write the test**

Write this exact content to `C:\dev\AI-toolkit\tests\test_hermes_docker.py`:

```python
"""Static checks for the dockerized Hermes integration.

No Docker daemon required — pure file-content checks.
"""
from __future__ import annotations

from pathlib import Path

import pytest
import yaml

REPO_ROOT = Path(__file__).resolve().parents[1]
COMPOSE_FILE = REPO_ROOT / "docker-compose.yml"
DOCKERFILE = REPO_ROOT / "hermes" / "Dockerfile"
ENTRYPOINT = REPO_ROOT / "hermes" / "entrypoint.sh"
DOCKERIGNORE = REPO_ROOT / "hermes" / ".dockerignore"
CATALOG = REPO_ROOT / "dashboard" / "services_catalog.py"


def _compose_services() -> dict:
    with COMPOSE_FILE.open(encoding="utf-8") as f:
        doc = yaml.safe_load(f)
    return doc.get("services", {})


def test_hermes_services_exist():
    services = _compose_services()
    assert "hermes-gateway" in services
    assert "hermes-dashboard" in services


def test_hermes_services_use_same_image():
    services = _compose_services()
    img_a = services["hermes-gateway"].get("image")
    img_b = services["hermes-dashboard"].get("image")
    assert img_a == img_b, f"expected shared image, got {img_a!r} vs {img_b!r}"


def test_hermes_services_build_from_hermes_dir():
    services = _compose_services()
    for svc in ("hermes-gateway", "hermes-dashboard"):
        build = services[svc].get("build")
        assert build, f"{svc} has no build section"
        assert build.get("context") == "./hermes", f"{svc} context != ./hermes"


def test_dashboard_port_is_env_overridable():
    svc = _compose_services()["hermes-dashboard"]
    ports = svc.get("ports", [])
    assert any("${HERMES_DASHBOARD_PORT:-9119}:9119" in p for p in ports), (
        f"expected env-overridable port mapping, got: {ports}"
    )


def test_hermes_services_mount_workspace_and_state():
    services = _compose_services()
    for svc in ("hermes-gateway", "hermes-dashboard"):
        vols = services[svc].get("volumes", [])
        assert any(":/workspace" in v for v in vols), f"{svc} missing /workspace mount"
        assert any(":/home/hermes/.hermes" in v for v in vols), (
            f"{svc} missing /home/hermes/.hermes mount"
        )


def test_hermes_services_depend_on_stack():
    services = _compose_services()
    required = ("model-gateway", "mcp-gateway", "dashboard")
    for svc in ("hermes-gateway", "hermes-dashboard"):
        deps = services[svc].get("depends_on") or {}
        for dep in required:
            assert dep in deps, f"{svc} missing depends_on: {dep}"
            assert deps[dep].get("condition") == "service_healthy", (
                f"{svc} depends_on {dep} must require service_healthy"
            )


def test_gateway_command_is_hermes_gateway():
    svc = _compose_services()["hermes-gateway"]
    cmd = svc.get("command")
    joined = " ".join(cmd) if isinstance(cmd, list) else (cmd or "")
    assert "hermes" in joined and "gateway" in joined, f"got: {cmd!r}"


def test_dashboard_command_binds_all_interfaces():
    svc = _compose_services()["hermes-dashboard"]
    cmd = svc.get("command") or []
    joined = " ".join(cmd) if isinstance(cmd, list) else cmd
    assert "dashboard" in joined, f"dashboard subcommand missing: {cmd}"
    assert "--host" in joined and "0.0.0.0" in joined, f"must bind 0.0.0.0: {cmd}"
    assert "--no-open" in joined, f"must use --no-open: {cmd}"


def test_dockerfile_exists_and_multistage():
    assert DOCKERFILE.is_file(), f"{DOCKERFILE} missing"
    src = DOCKERFILE.read_text(encoding="utf-8")
    assert "FROM node:" in src, "web-builder stage missing"
    assert "FROM python:3.11-slim" in src, "runtime stage missing"
    assert "ARG HERMES_PINNED_SHA" in src, "pinned SHA must be a build arg"


def test_entrypoint_is_bash_and_seeds_config():
    assert ENTRYPOINT.is_file(), f"{ENTRYPOINT} missing"
    src = ENTRYPOINT.read_text(encoding="utf-8")
    first_line = src.splitlines()[0]
    assert first_line == "#!/usr/bin/env bash", f"unexpected shebang: {first_line!r}"
    assert "model.base_url" in src, "entrypoint must seed model.base_url"
    assert "model-gateway:11435" in src, "entrypoint must point at Docker DNS model-gateway:11435"
    assert "mcp_servers.gateway.url" in src, "entrypoint must seed mcp_servers.gateway.url"
    assert 'exec "$@"' in src, "entrypoint must exec the supplied command"


def test_dockerignore_exists():
    assert DOCKERIGNORE.is_file(), f"{DOCKERIGNORE} missing"


def test_services_catalog_hermes_uses_internal_dns():
    src = CATALOG.read_text(encoding="utf-8")
    assert "hermes-dashboard:9119" in src, (
        "catalog must probe internal DNS hermes-dashboard:9119"
    )
    assert "host.docker.internal:9119" not in src, (
        "catalog must not use host.docker.internal (host-mode residue)"
    )


def test_host_mode_files_removed():
    """Post-migration: host-mode bootstrap and tests must be gone."""
    start_host = REPO_ROOT / "scripts" / "start-hermes-host.sh"
    host_test = REPO_ROOT / "tests" / "test_start_hermes_host.py"
    assert not start_host.exists(), f"{start_host} should be deleted"
    assert not host_test.exists(), f"{host_test} should be deleted"
```

- [ ] **Step 2: Run the tests — all fail**

```bash
cd C:/dev/AI-toolkit
python -m pytest tests/test_hermes_docker.py -v 2>&1 | tail -25
```

Expected: 13 tests collected, all fail or error — `hermes/` directory doesn't exist, compose has no `hermes-*` services, catalog still uses `host.docker.internal`, host-mode files still present. This establishes the TDD baseline.

- [ ] **Step 3: Commit the failing test**

```bash
git add tests/test_hermes_docker.py
git diff --cached --stat
git commit -m "test(hermes): failing static checks for docker integration"
```

---

### Task 2: Create `hermes/Dockerfile`

**Files:**
- Create: `hermes/Dockerfile`

- [ ] **Step 1: Create the hermes directory and Dockerfile**

```bash
mkdir -p C:/dev/AI-toolkit/hermes
```

Write this exact content to `C:\dev\AI-toolkit\hermes\Dockerfile`:

```dockerfile
# syntax=docker/dockerfile:1.6
# Multi-stage build for Hermes Agent.
# Stage 1: node builds the web UI bundle.
# Stage 2: python runtime with hermes installed; copies web_dist from stage 1.

ARG HERMES_PINNED_SHA=dcd763c284086afd5ddee4fdcd86daaf534916ab
ARG HERMES_REPO=https://github.com/NousResearch/hermes-agent.git

# ── Stage 1: web-builder ──
FROM node:20-slim AS web-builder
ARG HERMES_REPO
ARG HERMES_PINNED_SHA

RUN apt-get update && apt-get install -y --no-install-recommends git ca-certificates \
    && rm -rf /var/lib/apt/lists/*

WORKDIR /build
RUN git clone --no-single-branch "$HERMES_REPO" hermes-agent \
    && cd hermes-agent \
    && git checkout "$HERMES_PINNED_SHA"

WORKDIR /build/hermes-agent/web
RUN npm install && npm run build
# Produces: /build/hermes-agent/hermes_cli/web_dist/

# ── Stage 2: runtime ──
FROM python:3.11-slim AS runtime
ARG HERMES_REPO
ARG HERMES_PINNED_SHA

RUN apt-get update && apt-get install -y --no-install-recommends \
        git ca-certificates curl \
    && rm -rf /var/lib/apt/lists/*

# uv — fast Python package manager.
RUN curl -LsSf https://astral.sh/uv/install.sh | sh \
    && mv /root/.local/bin/uv /usr/local/bin/uv \
    && mv /root/.local/bin/uvx /usr/local/bin/uvx

# Non-root user (uid 1000 matches other stack services).
RUN useradd -m -u 1000 -s /bin/bash hermes

# Clone hermes-agent source into /opt, owned by hermes user.
RUN git clone --no-single-branch "$HERMES_REPO" /opt/hermes-agent \
    && cd /opt/hermes-agent \
    && git checkout "$HERMES_PINNED_SHA" \
    && chown -R hermes:hermes /opt/hermes-agent

USER hermes
WORKDIR /opt/hermes-agent

# Install Hermes + all extras into a venv at /opt/hermes-agent/.venv/.
RUN uv venv --python 3.11 \
    && uv pip install -e ".[all]"

# Web UI — copy built SPA from stage 1.
COPY --from=web-builder --chown=hermes:hermes \
    /build/hermes-agent/hermes_cli/web_dist/ \
    /opt/hermes-agent/hermes_cli/web_dist/

USER root
COPY entrypoint.sh /entrypoint.sh
RUN chmod +x /entrypoint.sh

USER hermes
ENV HERMES_HOME=/home/hermes/.hermes
ENV PYTHONIOENCODING=utf-8
ENV PATH=/opt/hermes-agent/.venv/bin:$PATH

WORKDIR /workspace

ENTRYPOINT ["/entrypoint.sh"]
CMD ["hermes", "--help"]
```

- [ ] **Step 2: Run the tests — Dockerfile test passes**

```bash
cd C:/dev/AI-toolkit
python -m pytest tests/test_hermes_docker.py::test_dockerfile_exists_and_multistage -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add hermes/Dockerfile
git diff --cached --stat
git commit -m "feat(hermes): multi-stage Dockerfile (node web-builder + python runtime)"
```

---

### Task 3: Create `hermes/entrypoint.sh`

**Files:**
- Create: `hermes/entrypoint.sh`

- [ ] **Step 1: Write the entrypoint**

Write to `C:\dev\AI-toolkit\hermes\entrypoint.sh`:

```bash
#!/usr/bin/env bash
# hermes/entrypoint.sh — container startup.
# 1. Seeds $HERMES_HOME/config.yaml with Docker-network endpoints.
# 2. Execs the compose-supplied command (hermes gateway, hermes dashboard, etc).
#
# Idempotent: re-writes only the keys we manage (model.* + mcp_servers.gateway.url).
# Preserves any other operator-set keys (skills, memory providers, Discord behavior).
set -eu

HERMES_HOME="${HERMES_HOME:-/home/hermes/.hermes}"
mkdir -p "$HERMES_HOME"
export HERMES_HOME

HERMES_BIN=/opt/hermes-agent/.venv/bin/hermes

# Seed model + MCP endpoints to Docker-network DNS. hermes config set is idempotent
# and overwrites stale values (e.g. localhost: from a prior host-mode install).
"$HERMES_BIN" config set model.provider        "custom"                        >/dev/null
"$HERMES_BIN" config set model.base_url        "http://model-gateway:11435/v1" >/dev/null
"$HERMES_BIN" config set model.api_key         "${LITELLM_MASTER_KEY:-local}"  >/dev/null
"$HERMES_BIN" config set model.default         "local-chat"                    >/dev/null
"$HERMES_BIN" config set mcp_servers.gateway.url "http://mcp-gateway:8811/mcp" >/dev/null

exec "$@"
```

- [ ] **Step 2: Run the entrypoint test**

```bash
cd C:/dev/AI-toolkit
python -m pytest tests/test_hermes_docker.py::test_entrypoint_is_bash_and_seeds_config -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add hermes/entrypoint.sh
git diff --cached --stat
git commit -m "feat(hermes): entrypoint seeds model + MCP config on container start"
```

---

### Task 4: Create `hermes/.dockerignore`

**Files:**
- Create: `hermes/.dockerignore`

- [ ] **Step 1: Write**

Write to `C:\dev\AI-toolkit\hermes\.dockerignore`:

```
# Only Dockerfile + entrypoint.sh are needed in the build context.
# Exclude everything else (markdown, editor files, etc.).
*.md
.git
.gitignore
__pycache__
*.pyc
*.swp
*.bak
```

- [ ] **Step 2: Run the dockerignore test**

```bash
python -m pytest tests/test_hermes_docker.py::test_dockerignore_exists -v
```

Expected: PASS.

- [ ] **Step 3: Commit**

```bash
git add hermes/.dockerignore
git diff --cached --stat
git commit -m "feat(hermes): dockerignore to keep build context minimal"
```

---

### Task 5: Add `hermes-gateway` and `hermes-dashboard` services to `docker-compose.yml`

**Files:**
- Modify: `docker-compose.yml`

- [ ] **Step 1: Find the insertion point**

Open `docker-compose.yml`. The new services go after the existing services list, before the top-level `volumes:` and `networks:` keys. Locate the last service block (currently `worker` or similar).

- [ ] **Step 2: Append the two services**

Insert these two service blocks just before the `volumes:` section (or at the end of the `services:` block):

```yaml
  hermes-gateway:
    build:
      context: ./hermes
      dockerfile: Dockerfile
    image: ordo-ai-stack-hermes:latest
    pull_policy: build
    restart: unless-stopped
    depends_on:
      model-gateway:
        condition: service_healthy
      mcp-gateway:
        condition: service_healthy
      dashboard:
        condition: service_healthy
    environment:
      - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY:-local}
      - PYTHONIOENCODING=utf-8
      # Accept both DISCORD_BOT_TOKEN (Hermes-native) and legacy DISCORD_TOKEN (OpenClaw era).
      - DISCORD_BOT_TOKEN=${DISCORD_BOT_TOKEN:-${DISCORD_TOKEN:-}}
      - DISCORD_ALLOWED_USERS=${DISCORD_ALLOWED_USERS:-}
      - DISCORD_ALLOWED_CHANNELS=${DISCORD_ALLOWED_CHANNELS:-}
      - DISCORD_ALLOWED_ROLES=${DISCORD_ALLOWED_ROLES:-}
      - DISCORD_REQUIRE_MENTION=${DISCORD_REQUIRE_MENTION:-true}
      - DISCORD_FREE_RESPONSE_CHANNELS=${DISCORD_FREE_RESPONSE_CHANNELS:-}
      - DISCORD_HOME_CHANNEL=${DISCORD_HOME_CHANNEL:-}
      - DISCORD_AUTO_THREAD=${DISCORD_AUTO_THREAD:-true}
      - DISCORD_REACTIONS=${DISCORD_REACTIONS:-true}
      - TELEGRAM_BOT_TOKEN=${TELEGRAM_BOT_TOKEN:-}
    volumes:
      - ${BASE_PATH:-.}:/workspace:rw
      - ${DATA_PATH:-${BASE_PATH:-.}/data}/hermes:/home/hermes/.hermes:rw
    healthcheck:
      # gateway.pid appears once Hermes has registered messaging platforms.
      test: ["CMD-SHELL", "test -f /home/hermes/.hermes/gateway.pid"]
      start_period: 60s
      interval: 30s
      timeout: 5s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - frontend
      - backend
    command: ["hermes", "gateway"]

  hermes-dashboard:
    build:
      context: ./hermes
      dockerfile: Dockerfile
    image: ordo-ai-stack-hermes:latest
    pull_policy: build
    restart: unless-stopped
    depends_on:
      model-gateway:
        condition: service_healthy
      mcp-gateway:
        condition: service_healthy
      dashboard:
        condition: service_healthy
    environment:
      - LITELLM_MASTER_KEY=${LITELLM_MASTER_KEY:-local}
      - PYTHONIOENCODING=utf-8
    volumes:
      - ${BASE_PATH:-.}:/workspace:rw
      - ${DATA_PATH:-${BASE_PATH:-.}/data}/hermes:/home/hermes/.hermes:rw
    ports:
      - "${HERMES_DASHBOARD_PORT:-9119}:9119"
    healthcheck:
      test: ["CMD", "curl", "-sf", "http://localhost:9119/"]
      start_period: 30s
      interval: 30s
      timeout: 5s
      retries: 3
    logging:
      driver: json-file
      options:
        max-size: "10m"
        max-file: "3"
    networks:
      - frontend
      - backend
    command: ["hermes", "dashboard", "--port", "9119", "--host", "0.0.0.0", "--no-open"]
```

- [ ] **Step 2: Validate compose parses**

```bash
cd C:/dev/AI-toolkit
docker compose config >/dev/null 2>&1 && echo OK || docker compose config 2>&1 | tail -10
```

Expected: `OK`. If it errors, the YAML indentation is wrong (most likely cause at this stage).

- [ ] **Step 3: Run the compose-related tests**

```bash
python -m pytest tests/test_hermes_docker.py -v -k "hermes_services or dashboard_port or gateway_command or dashboard_command" 2>&1 | tail -20
```

Expected: all pass.

- [ ] **Step 4: Commit**

```bash
git add docker-compose.yml
git diff --cached --stat
git commit -m "feat(compose): add hermes-gateway and hermes-dashboard services"
```

---

### Task 6: Update `dashboard/services_catalog.py` health probe

**Files:**
- Modify: `dashboard/services_catalog.py`

- [ ] **Step 1: Find the Hermes entry**

Search for the hermes entry:

```bash
rg -n "hermes" dashboard/services_catalog.py
```

You should see a block similar to:

```python
    {"id": "hermes", "name": "Hermes Agent", "port": 9119, "url": "http://localhost:9119",
     "check": "http://host.docker.internal:9119/", "has_gpu": False,
     "hint": "Assistant agent web UI. Start it with: ./scripts/start-hermes-host.sh --dashboard"},
```

- [ ] **Step 2: Replace with Docker-internal DNS probe**

Use Edit to change the `check` URL and the `hint`:

Find:
```python
    {"id": "hermes", "name": "Hermes Agent", "port": 9119, "url": "http://localhost:9119",
     "check": "http://host.docker.internal:9119/", "has_gpu": False,
     "hint": "Assistant agent web UI. Start it with: ./scripts/start-hermes-host.sh --dashboard"},
```

Replace with:
```python
    {"id": "hermes", "name": "Hermes Agent", "port": 9119, "url": "http://localhost:9119",
     "check": "http://hermes-dashboard:9119/", "has_gpu": False,
     "hint": "Managed by docker compose. Logs: docker compose logs hermes-dashboard"},
```

Also look for the preceding comment — update it if it references host-mode:

Find:
```python
    # Hermes Agent runs on the host (not in Docker) via scripts/start-hermes-host.sh. From inside the
    # dashboard container we reach it via host.docker.internal; unhealthy just means it's not running.
```

Replace with:
```python
    # Hermes Agent runs as two compose services (hermes-gateway + hermes-dashboard). The dashboard
    # container probes via internal DNS — unhealthy means the Hermes services haven't started.
```

- [ ] **Step 3: Run the catalog test**

```bash
python -m pytest tests/test_hermes_docker.py::test_services_catalog_hermes_uses_internal_dns -v
```

Expected: PASS.

- [ ] **Step 4: Smoke check dashboard imports**

```bash
python -c "import dashboard.services_catalog" 2>&1 | tail -3
```

Expected: silent (no import error).

- [ ] **Step 5: Commit**

```bash
git add dashboard/services_catalog.py
git diff --cached --stat
git commit -m "feat(dashboard): hermes probe via internal DNS (hermes-dashboard:9119)"
```

---

### Task 7: Build the Hermes image and bring services up (operator-gated)

This task runs Docker commands. It's the first point where we verify the whole chain works end-to-end.

- [ ] **Step 1: Kill any stale host-mode hermes processes**

```bash
# Windows: there may be hermes.exe running from the prior host-mode tests.
tasklist.exe //FI "IMAGENAME eq hermes.exe" 2>&1 | head -5
# If any PIDs shown:
taskkill.exe //F //IM hermes.exe 2>&1 | head -3
# If port 9119 is still taken:
netstat -ano 2>&1 | grep ":9119.*LISTENING" | head -3
# Kill the PID: taskkill.exe //F //PID <pid>
```

Required: port 9119 must be free before the new `hermes-dashboard` container can bind it.

- [ ] **Step 2: Build the hermes image**

```bash
cd C:/dev/AI-toolkit
docker compose build hermes-gateway hermes-dashboard 2>&1 | tail -30
```

Expected: build completes. First build takes 3-5 minutes (npm install + uv pip install with `[all]` extras is ~900MB of deps). Successive builds are cached.

If the build fails:
- `npm install` errors → read the stage-1 log; usually a vite/pnpm version mismatch that upstream has since fixed. Check if a newer `HERMES_PINNED_SHA` resolves it.
- `uv pip install` errors → read the stage-2 log; usually a Python-3.11-only dep with Windows-cross-compile issue. Retry without `[all]` (edit Dockerfile, change `".[all]"` → `".[telegram,discord]"`).

- [ ] **Step 3: Rebuild dashboard image (it has a code change from Task 6)**

```bash
docker compose build dashboard 2>&1 | tail -5
```

- [ ] **Step 4: Bring services up**

```bash
docker compose up -d hermes-gateway hermes-dashboard 2>&1 | tail -5
```

- [ ] **Step 5: Watch services come healthy**

```bash
# Poll until both services are healthy, up to ~2 minutes.
for i in $(seq 1 40); do
  ps=$(docker compose ps hermes-gateway hermes-dashboard 2>&1)
  healthy=$(echo "$ps" | grep -c "(healthy)")
  starting=$(echo "$ps" | grep -c "(health: starting)")
  echo "[$i] healthy=$healthy starting=$starting"
  [ "$healthy" = "2" ] && break
  sleep 3
done
docker compose ps hermes-gateway hermes-dashboard
```

Expected: eventually `healthy=2`. If it stalls on `starting`, inspect `docker compose logs hermes-gateway` or `... hermes-dashboard`.

- [ ] **Step 6: Verify web UI responds**

```bash
curl -sf -o /dev/null -w "dashboard=%{http_code}\n" http://localhost:9119/
```

Expected: `dashboard=200`.

- [ ] **Step 7: Verify Ordo dashboard sees Hermes as healthy**

```bash
# Wait a moment for the dashboard container's periodic health probe to run.
sleep 5
curl -sf http://localhost:8080/api/health | python -c "import json,sys; d=json.load(sys.stdin); h=[s for s in d['services'] if s['id']=='hermes'][0]; print(h)"
```

Expected: `{'id': 'hermes', 'ok': True, 'error': ''}`. If `ok: False`, check `docker compose logs hermes-dashboard` for startup errors.

- [ ] **Step 8: Verify Discord gateway connected**

```bash
docker compose logs --tail=30 hermes-gateway 2>&1 | grep -iE "discord connected|✓ discord|Shard.*ready|Gateway|Opus" | head -10
```

Expected output contains: `✓ discord connected` or `[Discord] Connected as primus#<discriminator>`.

If Discord doesn't connect, check that `DISCORD_BOT_TOKEN` is in your `.env` (or legacy `DISCORD_TOKEN`) and `DISCORD_ALLOWED_USERS` is set.

- [ ] **Step 9: No commit — this task verifies runtime only**

---

### Task 8: Delete host-mode bootstrap and its tests

**Files:**
- Delete: `scripts/start-hermes-host.sh`
- Delete: `tests/test_start_hermes_host.py`

- [ ] **Step 1: Verify the files exist**

```bash
ls scripts/start-hermes-host.sh tests/test_start_hermes_host.py 2>&1
```

Both should print their paths.

- [ ] **Step 2: Delete**

```bash
rm scripts/start-hermes-host.sh tests/test_start_hermes_host.py
```

- [ ] **Step 3: Run the cleanup test**

```bash
python -m pytest tests/test_hermes_docker.py::test_host_mode_files_removed -v
```

Expected: PASS.

- [ ] **Step 4: Verify no other code still references these files**

```bash
rg -n "start-hermes-host|test_start_hermes_host" -g '!docs/**' -g '!CHANGELOG.md' 2>&1 | head -10
```

Expected: empty. If any hits, remove those references.

- [ ] **Step 5: Stage and commit**

```bash
git add scripts/start-hermes-host.sh tests/test_start_hermes_host.py
git diff --cached --stat
git commit -m "chore: delete host-mode hermes bootstrap and tests (replaced by compose)"
```

---

### Task 9: Rewrite `docs/hermes-agent.md` for Docker mode

**Files:**
- Modify: `docs/hermes-agent.md`

- [ ] **Step 1: Write the new content**

Replace the entire content of `docs/hermes-agent.md` with:

````markdown
# Hermes Agent (Docker-mode)

[Hermes Agent](https://github.com/NousResearch/hermes-agent) is the stack's assistant-agent layer. It runs as two compose services — `hermes-gateway` (Discord / Telegram messaging) and `hermes-dashboard` (web UI at :9119) — that come up with the rest of the stack.

## Running

```bash
docker compose up -d
```

That's it. Hermes starts automatically, waits for model-gateway / mcp-gateway / dashboard to be healthy, then registers messaging platforms (if configured) and serves the web UI.

Web UI: <http://localhost:9119/>
Logs: `docker compose logs -f hermes-gateway hermes-dashboard`
Restart: `docker compose restart hermes-gateway`
Stop only Hermes: `docker compose stop hermes-gateway hermes-dashboard`

## State

All persistent state lives in `data/hermes/`:

| Path | Contents |
|---|---|
| `data/hermes/config.yaml` | Hermes config (endpoints, Discord behavior, skills preferences) |
| `data/hermes/sessions/` | Conversation history |
| `data/hermes/memories/` | FTS5-indexed memories |
| `data/hermes/skills/` | Installed and auto-generated skills |
| `data/hermes/cron/` | Scheduled jobs |
| `data/hermes/logs/` | Hermes's own log files (separate from `docker compose logs`) |

`data/hermes/` is gitignored. To start from a clean slate: `docker compose down`, `rm -rf data/hermes/*`, `docker compose up -d`.

## Discord setup

Same flow as before — the env vars move into the container via `docker-compose.yml`, not into a host-side `.env` Hermes reads.

### One-time Discord Developer Portal setup

1. Open <https://discord.com/developers/applications>, create an application.
2. **Bot → Token:** click *Reset Token*, copy. This becomes `DISCORD_BOT_TOKEN`.
3. **Bot → Privileged Gateway Intents:** enable **Message Content Intent** (required — without this the bot receives empty message text) and **Server Members Intent**.
4. **OAuth2 → URL Generator:** scopes `bot` + `applications.commands`; permissions `274878286912` (View Channels, Send Messages, Read Message History, Embed Links, Attach Files, Send Messages in Threads, Add Reactions). Copy the URL; use it to invite the bot to your server.
5. Discord → Settings → Advanced → enable **Developer Mode**. Right-click your own username → *Copy User ID*. This becomes `DISCORD_ALLOWED_USERS`.

### `.env` entries

Add to `.env`:

```
DISCORD_BOT_TOKEN=<token-from-step-2>
DISCORD_ALLOWED_USERS=<your-user-id-from-step-5>
DISCORD_REQUIRE_MENTION=false
```

The compose file aliases legacy `DISCORD_TOKEN` to `DISCORD_BOT_TOKEN` automatically, so if you already had `DISCORD_TOKEN=` (e.g. from OpenClaw), you don't need to rename it.

After editing `.env`:

```bash
docker compose up -d hermes-gateway   # recreate with new env
```

### Verifying

```bash
docker compose logs --tail=50 hermes-gateway | grep -i discord
```

Expected: `[Discord] Connected as <botname>#<discriminator>`. If the bot appears in Discord as offline, check the Message Content Intent — that's the #1 cause.

## Configuration endpoints (seeded automatically)

The container's entrypoint seeds `data/hermes/config.yaml` on every start so the Docker-network endpoints are correct:

```yaml
model:
  provider: custom
  base_url: http://model-gateway:11435/v1
  api_key: <LITELLM_MASTER_KEY>
  default: local-chat
mcp_servers:
  gateway:
    url: http://mcp-gateway:8811/mcp
```

Any other keys you add manually (skills, memory providers, display preferences) are preserved across restarts — the entrypoint only touches the five keys above.

## Updating Hermes

The Hermes upstream SHA is pinned in `hermes/Dockerfile` as `ARG HERMES_PINNED_SHA=...`. To upgrade:

1. Check recent commits: `git ls-remote https://github.com/NousResearch/hermes-agent.git main` — pick a SHA.
2. Edit `hermes/Dockerfile`, change the `ARG HERMES_PINNED_SHA` default.
3. `docker compose build hermes-gateway hermes-dashboard` (rebuilds both with the new pin).
4. `docker compose up -d hermes-gateway hermes-dashboard` (recreates).

You can also override without editing the file: `docker compose build --build-arg HERMES_PINNED_SHA=<sha> hermes-gateway`.

## Troubleshooting

**Service is `unhealthy`:**

```bash
docker compose logs hermes-gateway | tail -50
docker compose logs hermes-dashboard | tail -50
```

**Web UI returns 502 / connection refused:**
- Check that the dashboard container is running: `docker compose ps hermes-dashboard`.
- Port 9119 collision with an old host-mode process: `netstat -ano | grep :9119` and kill the PID.

**Discord bot shows online but doesn't reply:**
- Message Content Intent disabled in Developer Portal.

**Clean restart (throws away all sessions + skills):**
```bash
docker compose down
rm -rf data/hermes/*
docker compose up -d
```

---

> **Note:** The stack previously used OpenClaw as its assistant-agent layer. It was decommissioned on 2026-04-20 — see `CHANGELOG.md` for the removal entry.
````

- [ ] **Step 2: Commit**

```bash
git add docs/hermes-agent.md
git diff --cached --stat
git commit -m "docs(hermes): rewrite for docker-mode (host-mode section removed)"
```

---

### Task 10: Strip host-mode vars from `.env.example`

**Files:**
- Modify: `.env.example`

- [ ] **Step 1: Find the Hermes section**

```bash
rg -n "Hermes Agent\|HERMES_HOME\|HERMES_PINNED_SHA" .env.example
```

- [ ] **Step 2: Remove the host-mode-specific lines**

Find the current block (approximately):
```
# --- Hermes Agent (phase-1 assistant agent evaluation) ---
# Hermes runs as a host process via scripts/start-hermes-host.sh (WSL2 or Git Bash).
# It points at model-gateway + mcp-gateway over localhost using the stack's existing
# LITELLM_MASTER_KEY, MODEL_GATEWAY_PORT, and MCP_GATEWAY_PORT. State lives in data/hermes/.
# See docs/hermes-agent.md for the validation checklist and known egress notes.
# HERMES_HOME overrides the default state dir (default: BASE_PATH/data/hermes).
# HERMES_HOME=/path/to/hermes/home
# Pin to a specific hermes-agent commit SHA. Filled by Task 3 of the integration plan.
# HERMES_PINNED_SHA=
```

Replace with:
```
# --- Hermes Agent (docker-mode) ---
# Hermes runs as two compose services (hermes-gateway + hermes-dashboard). State in data/hermes/.
# See docs/hermes-agent.md for setup, Discord config, and upgrade instructions.
# HERMES_DASHBOARD_PORT overrides the host port for the web UI (default 9119).
# HERMES_DASHBOARD_PORT=9119
```

Keep the existing Discord block below unchanged.

- [ ] **Step 3: Verify**

```bash
rg -n "HERMES_HOME\|HERMES_PINNED_SHA\|start-hermes-host" .env.example
```

Expected: empty.

- [ ] **Step 4: Commit**

```bash
git add .env.example
git diff --cached --stat
git commit -m "docs(env): drop host-mode hermes vars; add HERMES_DASHBOARD_PORT"
```

---

### Task 11: Add CHANGELOG entry

**Files:**
- Modify: `CHANGELOG.md`

- [ ] **Step 1: Find the `[Unreleased]` section**

```bash
head -30 CHANGELOG.md
```

- [ ] **Step 2: Add `### Changed` subsection under [Unreleased]**

Use Edit to add this entry as the first sub-section under `## [Unreleased]`:

```markdown
### Changed
- Hermes Agent migrated from host-mode install to Docker compose services (`hermes-gateway` + `hermes-dashboard`). One `docker compose up -d` now brings the whole stack online atomically. Auto-restart, service_healthy dependencies, internal-DNS health probes from the Ordo dashboard. Deletes `scripts/start-hermes-host.sh` and the global `hermes` wrapper at `~/.local/bin/`. Operator runtime state at `data/hermes/` is preserved — endpoints are re-seeded on each container start.
```

- [ ] **Step 3: Commit**

```bash
git add CHANGELOG.md
git diff --cached --stat
git commit -m "docs(changelog): record hermes docker-mode migration"
```

---

### Task 12: Final verification sweep

- [ ] **Step 1: Run the full hermes test file**

```bash
cd C:/dev/AI-toolkit
python -m pytest tests/test_hermes_docker.py -v 2>&1 | tail -20
```

Expected: 13 passed.

- [ ] **Step 2: Full suite (regression check)**

```bash
python -m pytest tests/ -q 2>&1 | tail -10
```

Compare to the pre-existing failure baseline from the previous branch (6 pre-existing failures: ComfyUI packs x2, vraam_pct x4). No NEW failures from this branch.

- [ ] **Step 3: Compose config parse**

```bash
docker compose config >/dev/null 2>&1 && echo OK || docker compose config 2>&1 | tail -10
```

Expected: `OK`.

- [ ] **Step 4: Grep for any remaining host-mode residue**

```bash
rg -n "start-hermes-host|~/.local/bin/hermes" -g '!docs/**' -g '!CHANGELOG.md' -g '!vendor/**' -g '!data/**' 2>&1 | head -5
```

Expected: empty. Any hits = stragglers to remove.

- [ ] **Step 5: Live stack check**

```bash
docker compose ps hermes-gateway hermes-dashboard 2>&1 | head -5
curl -sf http://localhost:9119/ -o /dev/null -w "9119=%{http_code}\n"
curl -sf http://localhost:8080/api/health | python -c "import json,sys; d=json.load(sys.stdin); h=[s for s in d['services'] if s['id']=='hermes'][0]; print(h)"
```

Expected: both services `healthy`, 9119=200, hermes `{'ok': True}`.

- [ ] **Step 6: If stragglers found — fix + commit**

```bash
# If Step 4 found anything, Edit the files and:
git add <each-file>
git commit -m "chore: remove straggler host-mode references"
```

Otherwise no commit.

---

### Task 13: Final code review

Dispatch the `superpowers:code-reviewer` subagent over the branch.

**Input to reviewer:** commits from `main..HEAD`, spec at `docs/superpowers/specs/2026-04-20-dockerize-hermes-design.md`.

**Required checks:**
- Spec work buckets all covered (Dockerfile multi-stage, entrypoint seeds config, compose services, dashboard catalog probe, host-mode deleted, docs rewritten, changelog)
- No drive-by changes outside the hermes migration
- Operator uncommitted state untouched (`.gitignore`, `overrides/compute.yml`, untracked files)
- `docker compose config` parses
- All tests pass
- Verification grep returns zero hits

If reviewer flags critical issues, fix them and re-run the review.

---

### Task 14: Merge to main

Use `superpowers:finishing-a-development-branch`.

- Verify tests pass.
- Present the 4 merge options.
- If merge-locally: `git checkout main`, `git merge --no-ff feat/dockerize-hermes`, delete feat branch.

Do not push to remote unless the user explicitly requests.

---

## Operator post-merge cleanup (not a task — documented reminder)

After the merge lands on main, the operator can free disk space and remove the stale global wrapper:

```bash
# PowerShell or Git Bash:
rm -rf C:/dev/AI-toolkit/vendor/hermes-agent        # ~500MB, no longer needed
rm ~/.local/bin/hermes ~/.local/bin/hermes.cmd      # wrappers for the deleted host-mode
```

These aren't tracked — optional and operator-driven.
