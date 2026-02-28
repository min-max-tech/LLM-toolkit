# Scripts

Setup and maintenance scripts for the LLM-toolkit stack.

## Setup

| Script | Purpose |
|--------|---------|
| `ensure_dirs.ps1` | Creates all data directories (`data/`, `models/`) for bind mounts. **Windows.** Run before first `docker compose up`. |
| `ensure_dirs.sh` | Same as above. **Linux/Mac.** Run: `./scripts/ensure_dirs.sh` |

## ComfyUI

| Script | Purpose |
|--------|---------|
| `comfyui/pull_comfyui_models.py` | Downloads LTX-2 models from Hugging Face. Run by `comfyui-model-puller` on first start, or manually: `docker compose run --rm comfyui-model-puller`. |

## Usage

From the repo root:

**Windows (PowerShell):**
```powershell
$env:BASE_PATH = "F:/LLM-toolkit"
.\scripts\ensure_dirs.ps1
```

**Linux/Mac:**
```bash
export BASE_PATH="$HOME/LLM-toolkit"
./scripts/ensure_dirs.sh
```

**OpenClaw workspace** (if using openclaw/):
```powershell
.\openclaw\scripts\ensure_openclaw_workspace.ps1
```
