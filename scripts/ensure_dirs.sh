#!/usr/bin/env bash
# Creates data directories for bind mounts. Run before first docker compose up.
# Linux/Mac: ./scripts/ensure_dirs.sh

set -e

base="${BASE_PATH:-$(pwd)}"
base="${base//\\/\/}"
data="${DATA_PATH:-$base/data}"

dirs=(
  "$data/ollama"
  "$data/mcp"
  "$data/ops-controller"
  "$data/open-webui"
  "$data/comfyui-storage"
  "$data/comfyui-output"
  "$data/n8n-data"
  "$data/n8n-files"
  "$data/openclaw"
  "$data/openclaw/workspace"
  "$base/models/comfyui/checkpoints"
  "$base/models/comfyui/loras"
  "$base/models/comfyui/latent_upscale_models"
  "$base/models/comfyui/text_encoders"
)

for d in "${dirs[@]}"; do
  mkdir -p "$d"
  echo "OK $d"
done

# Bootstrap openclaw.json with Ollama provider if config doesn't exist
openclaw_config="$data/openclaw/openclaw.json"
openclaw_config_example="$base/openclaw/openclaw.json.example"
if [[ ! -f "$openclaw_config" && -f "$openclaw_config_example" ]]; then
  cp "$openclaw_config_example" "$openclaw_config"
  echo "OK openclaw config (Ollama provider)"
fi

# Ensure root .env has OPENCLAW_GATEWAY_TOKEN (required for OpenClaw service)
root_env="$base/.env"
root_example="$base/.env.example"
needs_create=false
needs_token=false

if [[ ! -f "$root_env" ]]; then
  needs_create=true
elif grep -q 'OPENCLAW_GATEWAY_TOKEN=change-me\|^OPENCLAW_GATEWAY_TOKEN=[[:space:]]*$' "$root_env" 2>/dev/null; then
  needs_token=true
elif ! grep -q '^OPENCLAW_GATEWAY_TOKEN=[a-zA-Z0-9]' "$root_env" 2>/dev/null; then
  needs_token=true
fi

if [[ "$needs_create" == "true" || "$needs_token" == "true" ]]; then
  token=$(openssl rand -hex 32 2>/dev/null || head -c 32 /dev/urandom | xxd -p -c 32)
  if [[ "$needs_create" == "true" && -f "$root_example" ]]; then
    cp "$root_example" "$root_env"
  fi
  if [[ -f "$root_env" ]]; then
    if grep -q 'OPENCLAW_GATEWAY_TOKEN=' "$root_env" 2>/dev/null; then
      sed -i.bak "s/^OPENCLAW_GATEWAY_TOKEN=.*/OPENCLAW_GATEWAY_TOKEN=$token/" "$root_env" && rm -f "$root_env.bak"
    else
      echo "" >> "$root_env"
      echo "# OpenClaw gateway auth (pinned; do not change unless re-pairing all devices)" >> "$root_env"
      echo "OPENCLAW_GATEWAY_TOKEN=$token" >> "$root_env"
    fi
  else
    echo -e "BASE_PATH=$base\nOPENCLAW_GATEWAY_TOKEN=$token" > "$root_env"
  fi
  echo "OK .env ($([[ "$needs_create" == "true" ]] && echo 'created' || echo 'OPENCLAW_GATEWAY_TOKEN set'))"
fi

# Auto-detect GPU and generate docker-compose.compute.yml
detect_script="$base/scripts/detect_hardware.py"
if [[ -f "$detect_script" ]]; then
  BASE_PATH="$base" python3 "$detect_script" 2>/dev/null && echo "OK Hardware detected (docker-compose.compute.yml)"
fi

echo "Directories ready."
