#!/usr/bin/env python3
"""Merge gateway provider into openclaw.json if missing. Injects OPENCLAW_GATEWAY_TOKEN from env when set."""
from __future__ import annotations

import json
import os
import sys
from pathlib import Path


GATEWAY_PROVIDER = {
    "baseUrl": "http://model-gateway:11435/v1",
    "apiKey": "ollama-local",
    "api": "openai-completions",
    "models": [],
    "headers": {"X-Service-Name": "openclaw"},
}


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
    if "gateway" not in providers:
        providers["gateway"] = GATEWAY_PROVIDER.copy()
        modified = True
        msg = "added gateway provider"
    else:
        # Ensure schema compliance and X-Service-Name for dashboard identification
        gw = providers["gateway"]
        if isinstance(gw, dict):
            if gw.get("api") != "openai-completions":
                gw["api"] = "openai-completions"
                modified = True
                msg = "fixed gateway provider api"
            if "models" not in gw or not isinstance(gw.get("models"), list):
                gw["models"] = []
                modified = True
                msg = "fixed gateway provider models"
            gw.setdefault("headers", {})
            if not isinstance(gw["headers"], dict):
                gw["headers"] = {}
            if gw["headers"].get("X-Service-Name") != "openclaw":
                gw["headers"]["X-Service-Name"] = "openclaw"
                modified = True
                msg = "added X-Service-Name to gateway provider"

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
