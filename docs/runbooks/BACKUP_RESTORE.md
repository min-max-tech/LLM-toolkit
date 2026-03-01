# Backup and Restore Runbook

## Overview

This runbook covers backing up and restoring the AI-toolkit platform data. Critical data lives under `data/` (or `DATA_PATH`).

## What to Back Up

| Path | Contents |
|------|----------|
| `data/ollama` | Ollama models and manifests |
| `data/open-webui` | Open WebUI chats, users, settings |
| `data/n8n-data` | N8N workflows and credentials |
| `data/n8n-files` | N8N file storage |
| `data/mcp` | MCP servers config (`servers.txt`), `registry.json` |
| `data/ops-controller` | Audit logs |
| `data/openclaw` | OpenClaw config and workspace |
| `data/comfyui-output` | ComfyUI generated images |
| `models/comfyui` | ComfyUI checkpoints, LoRAs (optional, large) |

## Backup Procedure

### Full backup (recommended)

```bash
# Set BASE_PATH if not in repo root
export BASE_PATH="${BASE_PATH:-.}"
export DATA_PATH="${DATA_PATH:-$BASE_PATH/data}"

# Create timestamped archive
BACKUP_DIR="backups"
mkdir -p "$BACKUP_DIR"
STAMP=$(date +%Y%m%d-%H%M%S)
ARCHIVE="$BACKUP_DIR/ai-toolkit-$STAMP.tar.gz"

# Stop services to ensure consistent state (optional)
docker compose down

# Backup data and config
tar -czvf "$ARCHIVE" \
  -C "$BASE_PATH" \
  data \
  .env

# Restart services
docker compose up -d

echo "Backup saved to $ARCHIVE"
```

### Incremental / selective backup

```bash
# Ollama models only (largest)
tar -czvf backups/ollama-$(date +%Y%m%d).tar.gz -C "$BASE_PATH" data/ollama

# Config and small data only
tar -czvf backups/config-$(date +%Y%m%d).tar.gz \
  -C "$BASE_PATH" \
  data/mcp data/ops-controller data/openclaw \
  .env
```

## Restore Procedure

### Full restore

```bash
ARCHIVE="backups/ai-toolkit-YYYYMMDD-HHMMSS.tar.gz"

# Stop services
docker compose down

# Restore
tar -xzvf "$ARCHIVE" -C "$BASE_PATH"

# Restart
docker compose up -d
```

### Partial restore (e.g. MCP config only)

```bash
tar -xzvf backups/config-YYYYMMDD.tar.gz -C "$BASE_PATH"
# Restart MCP gateway to pick up changes
docker compose restart mcp-gateway
```

## Verification

After restore:

1. `docker compose ps` — all services should be running
2. Dashboard: http://localhost:8080 — check models, MCP tools
3. Open WebUI: http://localhost:3000 — verify chats
4. N8N: http://localhost:5678 — verify workflows

## Retention

- Keep at least 3 daily backups
- Store off-host (e.g. S3, NAS) for disaster recovery
- Test restore periodically (e.g. quarterly)
