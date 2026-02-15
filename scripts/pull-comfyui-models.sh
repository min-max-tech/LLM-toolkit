#!/bin/sh
# Auto-download LTX-2 models for ComfyUI from Hugging Face
# On Windows, large file writes to bind mounts can fail (curl error 23).
# Gemma is downloaded to /downloads (volume) first, then copied to /models.
set -eu

MODELS_DIR="${MODELS_DIR:-/models}"
DL_DIR="${DL_DIR:-/downloads}"
mkdir -p "$MODELS_DIR/checkpoints" "$MODELS_DIR/text_encoders" "$MODELS_DIR/loras" "$MODELS_DIR/latent_upscale_models"
mkdir -p "$DL_DIR"

download() {
  url="$1"
  dest="$2"
  if [ -f "$dest" ]; then
    echo "==> Skipping (exists): $dest"
    return 0
  fi
  echo "==> Downloading: $dest"
  curl -fsSL -C - -o "$dest" -A "ComfyUI-Docker/1.0" "$url" || {
    echo "Warning: Download failed for $dest"
    rm -f "$dest"
    return 1
  }
}

download_via_volume() {
  url="$1"
  dest="$2"
  if [ -f "$dest" ]; then
    echo "==> Skipping (exists): $dest"
    return 0
  fi
  base=$(basename "$dest")
  tmp="$DL_DIR/$base"
  if [ ! -f "$tmp" ]; then
    echo "==> Downloading to temp: $base"
    curl -fsSL -C - -o "$tmp" -A "ComfyUI-Docker/1.0" "$url" || {
      echo "Warning: Download failed for $base"
      rm -f "$tmp"
      return 1
    }
  fi
  echo "==> Copying to models: $dest"
  cp "$tmp" "$dest"
}

HF="https://huggingface.co"

# LTX-2 base model (fp8, ~27GB)
download "$HF/Lightricks/LTX-2/resolve/main/ltx-2-19b-dev-fp8.safetensors" \
  "$MODELS_DIR/checkpoints/ltx-2-19b-dev-fp8.safetensors"

# LoRAs
download "$HF/Lightricks/LTX-2/resolve/main/ltx-2-19b-distilled-lora-384.safetensors" \
  "$MODELS_DIR/loras/ltx-2-19b-distilled-lora-384.safetensors"
download "$HF/Lightricks/LTX-2-19b-LoRA-Camera-Control-Dolly-Left/resolve/main/ltx-2-19b-lora-camera-control-dolly-left.safetensors" \
  "$MODELS_DIR/loras/ltx-2-19b-lora-camera-control-dolly-left.safetensors"

# Latent upscaler
download "$HF/Lightricks/LTX-2/resolve/main/ltx-2-spatial-upscaler-x2-1.0.safetensors" \
  "$MODELS_DIR/latent_upscale_models/ltx-2-spatial-upscaler-x2-1.0.safetensors"

# Text encoder - Gemma 3 12B (~24GB). Download to volume first to avoid curl error 23 on Windows bind mounts.
download_via_volume "$HF/Comfy-Org/ltx-2/resolve/main/split_files/text_encoders/gemma_3_12B_it.safetensors" \
  "$MODELS_DIR/text_encoders/gemma_3_12B_it.safetensors"

echo "ComfyUI LTX-2 models ready."
