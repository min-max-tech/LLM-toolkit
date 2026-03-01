# Upgrade Runbook

## Overview

This runbook covers upgrading the AI-toolkit platform: images, config, and data migrations.

## Pre-Upgrade Checklist

1. **Backup** — Run `docs/runbooks/BACKUP_RESTORE.md` backup procedure
2. **Check release notes** — Review `CHANGELOG.md` or release tags for breaking changes
3. **Pin digests (production)** — Use pinned image digests to avoid surprise pulls

## Upgrade Steps

### 1. Pull latest images

```bash
docker compose pull
```

### 2. Rebuild local images (dashboard, model-gateway, mcp-gateway, ops-controller)

```bash
docker compose build --no-cache
```

### 3. Stop and recreate containers

```bash
docker compose down
docker compose up -d
```

### 4. Verify health

```bash
# Run smoke test if available
./scripts/smoke_test.sh

# Or manually
docker compose ps
curl -s http://localhost:8080/api/health | jq
curl -s http://localhost:11435/health | jq
```

## Pinned Image Digests (Production)

For production, pin critical images to avoid supply-chain surprises:

```bash
# Get current digests
docker pull ollama/ollama:0.17.4
docker inspect ollama/ollama:0.17.4 --format '{{.RepoDigests}}'

# Set in .env or export
export OLLAMA_IMAGE="ollama/ollama:0.17.4@sha256:1edb4ab90ebbe34b484bb120ab8de22601f463834bfeca7f5a2de2ca6dad13ee"
export OPEN_WEBUI_IMAGE="ghcr.io/open-webui/open-webui:v0.8.4@sha256:..."  # get via docker pull + inspect
```

Then run `docker compose up -d` — Compose will use the digest-pinned images.

## Component-Specific Upgrades

### Ollama

```bash
# Update OLLAMA_IMAGE in .env or docker-compose override
# Example: ollama/ollama:0.18.0
docker compose pull ollama
docker compose up -d ollama
```

### Open WebUI

```bash
# Update OPEN_WEBUI_IMAGE
docker compose pull open-webui
docker compose up -d open-webui
```

### Model Gateway / Dashboard (built from source)

```bash
git pull
docker compose build model-gateway dashboard
docker compose up -d model-gateway dashboard
```

### OpenClaw

```bash
# Update OPENCLAW_IMAGE in openclaw/.env
docker compose pull openclaw-gateway
docker compose up -d openclaw-gateway
```

## Rollback

If upgrade fails:

```bash
docker compose down
# Restore previous images (e.g. revert .env or use previous digest)
docker compose up -d
# Restore data from backup if needed (see BACKUP_RESTORE.md)
```

## Data Migrations

- **Ollama**: Model format may change between versions; re-pull models if needed
- **Open WebUI**: Check migration notes in their releases
- **N8N**: Usually backward-compatible; export workflows before major upgrades
- **OpenClaw**: Config in `data/openclaw`; backup before upgrading
