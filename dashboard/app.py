"""LLM-toolkit Dashboard — unified model management and service hub."""
from __future__ import annotations

import os
import subprocess
import threading
from pathlib import Path

from fastapi import FastAPI, HTTPException
from fastapi.responses import StreamingResponse
from fastapi.staticfiles import StaticFiles
from httpx import AsyncClient
from pydantic import BaseModel

app = FastAPI(title="LLM-toolkit Dashboard", version="1.0.0")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434")
MODELS_DIR = Path(os.environ.get("MODELS_DIR", "/models"))
SCRIPTS_DIR = Path(os.environ.get("SCRIPTS_DIR", "/scripts"))

# Background ComfyUI pull status
_comfyui_status: dict = {"running": False, "output": "", "done": False, "success": None}


class PullRequest(BaseModel):
    model: str


# --- Ollama ---


@app.get("/api/ollama/models")
async def ollama_models():
    """List models available in Ollama."""
    async with AsyncClient(timeout=30.0) as client:
        try:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            data = r.json()
            return {"models": data.get("models", []), "ok": True}
        except Exception as e:
            return {"models": [], "ok": False, "error": str(e)}


@app.post("/api/ollama/pull")
async def ollama_pull(req: PullRequest):
    """Stream Ollama model pull progress."""
    async def stream():
        async with AsyncClient(timeout=3600.0) as client:
            async with client.stream(
                "POST",
                f"{OLLAMA_URL}/api/pull",
                json={"model": req.model, "stream": True},
            ) as response:
                async for chunk in response.aiter_bytes():
                    yield chunk

    return StreamingResponse(
        stream(),
        media_type="application/x-ndjson",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )


# --- ComfyUI ---


def _scan_comfyui_models() -> list[dict]:
    """Scan ComfyUI models directory for installed files."""
    subdirs = ("checkpoints", "loras", "text_encoders", "latent_upscale_models")
    models = []
    for sub in subdirs:
        d = MODELS_DIR / sub
        if not d.exists():
            continue
        for f in d.iterdir():
            if f.is_file():
                size_mb = f.stat().st_size / (1024 * 1024)
                models.append(
                    {
                        "name": f.name,
                        "category": sub,
                        "size_mb": round(size_mb, 1),
                    }
                )
    return sorted(models, key=lambda m: (m["category"], m["name"]))


def _run_comfyui_pull():
    """Run ComfyUI model pull script in background."""
    global _comfyui_status
    _comfyui_status = {"running": True, "output": "", "done": False, "success": None}
    script = SCRIPTS_DIR / "comfyui" / "pull_comfyui_models.py"
    env = os.environ.copy()
    env["MODELS_DIR"] = str(MODELS_DIR)
    try:
        proc = subprocess.Popen(
            ["python3", str(script)],
            env=env,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            cwd=str(SCRIPTS_DIR.parent),
        )
        output_lines = []
        for line in proc.stdout:
            output_lines.append(line)
            _comfyui_status["output"] = "".join(output_lines)
        proc.wait()
        _comfyui_status["success"] = proc.returncode == 0
    except Exception as e:
        _comfyui_status["output"] += f"\nError: {e}"
        _comfyui_status["success"] = False
    finally:
        _comfyui_status["running"] = False
        _comfyui_status["done"] = True


@app.get("/api/comfyui/models")
async def comfyui_models():
    """List ComfyUI models on disk."""
    try:
        models = _scan_comfyui_models()
        return {"models": models, "ok": True}
    except Exception as e:
        return {"models": [], "ok": False, "error": str(e)}


@app.post("/api/comfyui/pull")
async def comfyui_pull():
    """Start ComfyUI model pull (LTX-2) in background."""
    global _comfyui_status
    if _comfyui_status.get("running"):
        raise HTTPException(status_code=409, detail="Pull already in progress")
    thread = threading.Thread(target=_run_comfyui_pull)
    thread.daemon = True
    thread.start()
    return {"status": "started", "message": "ComfyUI model pull started. Poll /api/comfyui/pull/status for progress."}


@app.get("/api/comfyui/pull/status")
async def comfyui_pull_status():
    """Get ComfyUI pull progress."""
    return _comfyui_status


# --- Services ---


@app.get("/api/services")
async def services():
    """Service links and status."""
    ollama_ok = False
    try:
        async with AsyncClient(timeout=5.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/version")
            ollama_ok = r.status_code == 200
    except Exception:
        pass

    return {
        "services": [
            {"id": "ollama", "name": "Ollama", "port": 11434, "url": "http://localhost:11434", "ok": ollama_ok},
            {"id": "webui", "name": "Open WebUI", "port": 3000, "url": "http://localhost:3000"},
            {"id": "comfyui", "name": "ComfyUI", "port": 8188, "url": "http://localhost:8188"},
            {"id": "n8n", "name": "N8N", "port": 5678, "url": "http://localhost:5678"},
            {"id": "openclaw", "name": "OpenClaw", "port": 18789, "url": "http://localhost:18789"},
        ]
    }


# --- Static ---

static_dir = Path(__file__).parent / "static"
if static_dir.exists():
    app.mount("/", StaticFiles(directory=str(static_dir), html=True), name="static")
