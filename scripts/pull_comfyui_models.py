#!/usr/bin/env python3
"""Download LTX-2 models for ComfyUI. Uses huggingface_hub for reliable large-file downloads."""
import os
import shutil
import sys
from typing import Optional

MODELS_DIR = os.environ.get("MODELS_DIR", "/models")

# All downloads via huggingface_hub to avoid curl error 23 on Windows/Docker
DOWNLOADS = [
    ("Lightricks/LTX-2", "ltx-2-19b-dev-fp8.safetensors", "checkpoints"),
    ("Lightricks/LTX-2", "ltx-2-19b-distilled-lora-384.safetensors", "loras"),
    ("Lightricks/LTX-2-19b-LoRA-Camera-Control-Dolly-Left", "ltx-2-19b-lora-camera-control-dolly-left.safetensors", "loras"),
    ("Lightricks/LTX-2", "ltx-2-spatial-upscaler-x2-1.0.safetensors", "latent_upscale_models"),
    ("Comfy-Org/ltx-2", "split_files/text_encoders/gemma_3_12B_it.safetensors", "text_encoders", "gemma_3_12B_it.safetensors"),
]


def ensure_dirs():
    for sub in ("checkpoints", "text_encoders", "loras", "latent_upscale_models"):
        os.makedirs(os.path.join(MODELS_DIR, sub), exist_ok=True)


def hf_download(repo_id: str, filename: str, subdir: str, dest_name: Optional[str] = None) -> bool:
    dest_name = dest_name or os.path.basename(filename)
    dest_path = os.path.join(MODELS_DIR, subdir, dest_name)

    if os.path.exists(dest_path):
        print(f"==> Skipping (exists): {dest_path}")
        return True

    print(f"==> Downloading: {dest_name}")
    try:
        from huggingface_hub import hf_hub_download
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"])
        from huggingface_hub import hf_hub_download

    try:
        cached = hf_hub_download(repo_id=repo_id, filename=filename)
        shutil.copy2(cached, dest_path)
        print(f"==> Saved: {dest_path}")
        return True
    except Exception as e:
        print(f"Warning: Download failed: {e}")
        return False


def main():
    ensure_dirs()

    for item in DOWNLOADS:
        if len(item) == 4:
            repo_id, filename, subdir, dest_name = item
        else:
            repo_id, filename, subdir = item
            dest_name = None

        if not hf_download(repo_id, filename, subdir, dest_name):
            return 1

    print("ComfyUI LTX-2 models ready.")
    return 0


if __name__ == "__main__":
    sys.exit(main())
