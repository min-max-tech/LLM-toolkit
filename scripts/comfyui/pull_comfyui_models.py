#!/usr/bin/env python3
"""Download LTX-2 models for ComfyUI from Hugging Face."""
import os
import shutil
import sys

MODELS_DIR = os.environ.get("MODELS_DIR", "/models")

DOWNLOADS = [
    # (repo_id, filename, subdir, [dest_name], [min_size_gb])
    ("Lightricks/LTX-2", "ltx-2-19b-dev-fp8.safetensors", "checkpoints"),
    ("Lightricks/LTX-2", "ltx-2-19b-distilled-lora-384.safetensors", "loras"),
    ("Lightricks/LTX-2-19b-LoRA-Camera-Control-Dolly-Left", "ltx-2-19b-lora-camera-control-dolly-left.safetensors", "loras"),
    ("Lightricks/LTX-2", "ltx-2-spatial-upscaler-x2-1.0.safetensors", "latent_upscale_models"),
    ("Comfy-Org/ltx-2", "split_files/text_encoders/gemma_3_12B_it_fp4_mixed.safetensors", "text_encoders", "gemma_3_12B_it_fp4_mixed.safetensors", 8.0),
]

SUBDIRS = ("checkpoints", "text_encoders", "loras", "latent_upscale_models")


def ensure_huggingface_hub():
    try:
        from huggingface_hub import hf_hub_download  # noqa: F401
    except ImportError:
        import subprocess
        subprocess.check_call([sys.executable, "-m", "pip", "install", "-q", "huggingface_hub"])


def download(repo_id, filename, subdir, dest_name=None, min_size_gb=0.0):
    from huggingface_hub import hf_hub_download

    dest_name = dest_name or os.path.basename(filename)
    dest_path = os.path.join(MODELS_DIR, subdir, dest_name)

    if os.path.exists(dest_path):
        if min_size_gb > 0:
            size_gb = os.path.getsize(dest_path) / (1024 ** 3)
            if size_gb < min_size_gb:
                print(f"==> Incomplete ({size_gb:.1f} GB < {min_size_gb} GB), re-downloading: {dest_name}")
                os.remove(dest_path)
            else:
                print(f"==> OK (exists): {dest_name}")
                return True
        else:
            print(f"==> OK (exists): {dest_name}")
            return True

    print(f"==> Downloading: {dest_name}")
    try:
        cached = hf_hub_download(repo_id=repo_id, filename=filename)
        shutil.copy2(cached, dest_path)
        print(f"==> Saved: {dest_name}")
        return True
    except Exception as e:
        print(f"ERROR: {dest_name}: {e}")
        return False


def main():
    for sub in SUBDIRS:
        os.makedirs(os.path.join(MODELS_DIR, sub), exist_ok=True)

    ensure_huggingface_hub()

    ok = True
    for item in DOWNLOADS:
        repo_id, filename, subdir = item[0], item[1], item[2]
        dest_name = item[3] if len(item) > 3 else None
        min_size_gb = item[4] if len(item) > 4 else 0.0
        if not download(repo_id, filename, subdir, dest_name, min_size_gb):
            ok = False

    if ok:
        print("All ComfyUI models ready.")
    else:
        print("Some downloads failed. Re-run to retry.")
    return 0 if ok else 1


if __name__ == "__main__":
    sys.exit(main())
