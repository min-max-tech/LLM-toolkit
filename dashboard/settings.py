"""Environment-derived settings for the dashboard (single source of truth)."""
from __future__ import annotations

import logging
import os
from pathlib import Path

logger = logging.getLogger(__name__)

DASHBOARD_AUTH_TOKEN: str = os.environ.get("DASHBOARD_AUTH_TOKEN", "").strip()
AUTH_REQUIRED: bool = bool(DASHBOARD_AUTH_TOKEN)

# Blocked port range: browsers refuse connections to 6666-6669 (IRC).
# Kept as a stack-wide safety utility even without current callers — any future
# service that accepts a port via env var should route through `_validated_port`.
_BLOCKED_PORTS = set(range(6666, 6670))


def _validated_port(name: str, default: str) -> str:
    """Return the env-var value if it's a valid port number, else the default."""
    raw = os.environ.get(name, default).strip()
    if not raw.isdigit() or not (1 <= int(raw) <= 65535):
        logger.warning("Invalid %s=%r — falling back to %s", name, raw, default)
        return default
    if int(raw) in _BLOCKED_PORTS:
        logger.warning("%s=%s is in the browser-blocked IRC range (6666-6669) — connections will fail", name, raw)
    return raw
