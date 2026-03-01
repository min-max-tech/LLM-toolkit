#!/usr/bin/env python3
"""Merge gateway provider into openclaw.json. Fetches models from model-gateway (Ollama).
Injects OPENCLAW_GATEWAY_TOKEN from env when set."""
from __future__ import annotations

import json
import os
import sys
import urllib.request
from pathlib import Path

GATEWAY_PROVIDER = {
    "baseUrl": "http://model-gateway:11435/v1",
    "apiKey": "ollama-local",
    "api": "openai-responses",
    "headers": {"X-Service-Name": "openclaw"},
}

# Default models when model-gateway is unreachable. Empty models[] causes OpenClaw to skip LLM calls.
DEFAULT_GATEWAY_MODELS = [
    {"id": "ollama/qwen2.5:7b", "name": "Qwen 2.5 7B", "reasoning": False, "input": ["text"],
     "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 32768, "maxTokens": 8192},
    {"id": "ollama/deepseek-r1:7b", "name": "DeepSeek R1 7B", "reasoning": True, "input": ["text"],
     "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 65536, "maxTokens": 8192},
    {"id": "ollama/deepseek-coder:6.7b", "name": "DeepSeek Coder 6.7B", "reasoning": False, "input": ["text"],
     "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 16384, "maxTokens": 8192},
    {"id": "ollama/llama3.2-vision:11b", "name": "Llama 3.2 Vision 11B", "reasoning": False, "input": ["text", "image"],
     "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 131072, "maxTokens": 8192},
    {"id": "ollama/nomic-embed-text:latest", "name": "Nomic Embed", "reasoning": False, "input": ["text"],
     "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0}, "contextWindow": 8192, "maxTokens": 8192},
]

MODEL_GATEWAY_URL = os.environ.get("MODEL_GATEWAY_URL", "http://model-gateway:11435")


def _fetch_models_from_gateway() -> list[dict] | None:
    """Fetch /v1/models from model-gateway. Returns list of model dicts for OpenClaw, or None on failure."""
    try:
        req = urllib.request.Request(
            f"{MODEL_GATEWAY_URL.rstrip('/')}/v1/models",
            headers={"Accept": "application/json"},
        )
        with urllib.request.urlopen(req, timeout=15) as resp:
            data = json.loads(resp.read().decode())
    except Exception as e:
        print(f"merge_gateway_config: could not fetch models from gateway: {e}", file=sys.stderr)
        return None

    items = data.get("data") if isinstance(data, dict) else []
    if not items:
        return None

    models = []
    for m in items:
        mid = m.get("id") or m.get("name", "")
        if not mid:
            continue
        # Derive name from id (ollama/qwen2.5:7b -> Qwen 2.5 7B)
        name = mid.split("/")[-1] if "/" in mid else mid
        name = name.replace(":", " ").replace("-", " ").replace(".", " ")
        name = " ".join(w.capitalize() for w in name.split())
        # Vision/embed heuristic
        lower_id = mid.lower()
        has_vision = "vision" in lower_id or "llava" in lower_id or "puppy" in lower_id
        is_embed = "embed" in lower_id
        models.append({
            "id": mid,
            "name": name,
            "reasoning": "r1" in lower_id or "reasoning" in lower_id,
            "input": ["text", "image"] if has_vision else ["text"],
            "cost": {"input": 0, "output": 0, "cacheRead": 0, "cacheWrite": 0},
            "contextWindow": 131072 if has_vision else 32768,
            "maxTokens": 8192,
        })
    return models if models else None


def main() -> int:
    config_path = Path("/config/openclaw.json")
    if not config_path.exists():
        return 0  # No config yet; ensure_dirs or first run will create it

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError) as e:
        print(f"merge_gateway_config: skip (read error): {e}", file=sys.stderr)
        return 0

    providers = data.setdefault("models", {}).setdefault("providers", {})
    modified = False
    msg = ""

    # Strip baseUrl/apiKey from model objects (OpenClaw 2026.2.x rejects them per-model)
    for pv in providers.values() if isinstance(providers, dict) else []:
        if isinstance(pv, dict):
            for m in (pv.get("models") or []):
                if isinstance(m, dict) and ("baseUrl" in m or "apiKey" in m):
                    m.pop("baseUrl", None)
                    m.pop("apiKey", None)
                    modified = True

    # Remove direct ollama provider — all models route through the gateway
    if "ollama" in providers:
        del providers["ollama"]
        modified = True
        msg = "removed direct ollama provider (all models via gateway)"

    # Fetch models from model-gateway (Ollama); fallback to defaults if unreachable
    gateway_models = _fetch_models_from_gateway()
    if gateway_models:
        msg = f"synced {len(gateway_models)} models from model-gateway"
    else:
        gateway_models = [m.copy() for m in DEFAULT_GATEWAY_MODELS]
        msg = f"using {len(gateway_models)} default models (gateway unreachable)"

    if "gateway" not in providers:
        providers["gateway"] = {
            **GATEWAY_PROVIDER,
            "models": gateway_models,
        }
        modified = True
    else:
        gw = providers["gateway"]
        if isinstance(gw, dict):
            if gw.get("api") != GATEWAY_PROVIDER["api"]:
                gw["api"] = GATEWAY_PROVIDER["api"]
                modified = True
            # Always sync from gateway (all Ollama models)
            gw["models"] = gateway_models
            modified = True
            gw.setdefault("headers", {})
            if not isinstance(gw["headers"], dict):
                gw["headers"] = {}
            if gw["headers"].get("X-Service-Name") != "openclaw":
                gw["headers"]["X-Service-Name"] = "openclaw"
                modified = True

    # Inject gateway auth token from env so it lives in .env, not in committed config
    gateway = data.setdefault("gateway", {})
    auth = gateway.setdefault("auth", {})
    if isinstance(auth, dict):
        token = os.environ.get("OPENCLAW_GATEWAY_TOKEN", "").strip()
        if token and auth.get("token") != token:
            auth["token"] = token
            auth["mode"] = "token"
            modified = True
            msg = "injected gateway token from OPENCLAW_GATEWAY_TOKEN"

    if not modified:
        return 0
    try:
        config_path.write_text(json.dumps(data, indent=2), encoding="utf-8")
        print(f"merge_gateway_config: {msg} in openclaw.json")
    except OSError as e:
        print(f"merge_gateway_config: write failed: {e}", file=sys.stderr)
        return 1

    return 0


if __name__ == "__main__":
    sys.exit(main())
