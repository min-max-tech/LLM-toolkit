#!/bin/sh
# Auto-download LTX-2 models for ComfyUI from Hugging Face
# Note: Gemma text encoder auto-downloads on first use via LTXVideo nodes
set -eu

MODELS_DIR="${MODELS_DIR:-/models}"
mkdir -p "$MODELS_DIR/checkpoints" "$MODELS_DIR/text_encoders" "$MODELS_DIR/loras" "$MODELS_DIR/latent_upscale_models"

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

echo "ComfyUI LTX-2 models ready. Text encoder (Gemma) downloads on first workflow run."
