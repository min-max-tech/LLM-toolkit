"""Ops Controller — secure Docker Compose control plane."""
from __future__ import annotations

import json
import os
from datetime import datetime
from pathlib import Path

import docker
from fastapi import Depends, HTTPException, Request
from fastapi import FastAPI
from pydantic import BaseModel

app = FastAPI(title="Ops Controller", version="1.0.0")

COMPOSE_PROJECT = os.environ.get("COMPOSE_PROJECT", "ai-toolkit")
OPS_CONTROLLER_TOKEN = os.environ.get("OPS_CONTROLLER_TOKEN", "")
AUDIT_LOG_PATH = Path(os.environ.get("AUDIT_LOG_PATH", "/data/audit.log"))

# Services we allow operations on (allowlist)
ALLOWED_SERVICES = {
    "ollama", "dashboard", "open-webui", "model-gateway", "mcp-gateway",
    "comfyui", "n8n", "openclaw-gateway",
}


def _docker_client():
    return docker.from_env()


async def verify_token(request: Request) -> None:
    """Verify Bearer token. Use as Depends(verify_token)."""
    if not OPS_CONTROLLER_TOKEN:
        raise HTTPException(status_code=503, detail="Ops controller not configured (no token)")
    auth = request.headers.get("Authorization", "")
    if not auth.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = auth[7:].strip()
    if token != OPS_CONTROLLER_TOKEN:
        raise HTTPException(status_code=403, detail="Invalid token")


def _audit(
    action: str,
    resource: str = "",
    result: str = "ok",
    detail: str = "",
    correlation_id: str = "",
):
    """Append to audit log. Schema: docs/audit/SCHEMA.md."""
    try:
        AUDIT_LOG_PATH.parent.mkdir(parents=True, exist_ok=True)
        entry = {
            "ts": datetime.utcnow().isoformat() + "Z",
            "action": action,
            "resource": resource or "",
            "actor": "dashboard",
            "result": result,
            "detail": detail or "",
        }
        if correlation_id:
            entry["correlation_id"] = correlation_id
        with open(AUDIT_LOG_PATH, "a") as f:
            f.write(json.dumps(entry) + "\n")
    except Exception:
        pass


def _get_containers():
    """Get all containers for compose project."""
    client = _docker_client()
    return client.containers.list(
        all=True,
        filters={"label": f"com.docker.compose.project={COMPOSE_PROJECT}"},
    )


def _containers_for_service(service_id: str):
    """Get containers for a compose service."""
    client = _docker_client()
    return client.containers.list(
        all=True,
        filters={
            "label": [
                f"com.docker.compose.project={COMPOSE_PROJECT}",
                f"com.docker.compose.service={service_id}",
            ]
        },
    )


@app.get("/health")
async def health():
    """Controller health. No auth required."""
    return {"ok": True}


@app.get("/services")
async def list_services():
    """List compose services. No auth for read-only."""
    try:
        containers = _get_containers()
        seen = set()
        services = []
        for c in containers:
            labels = c.labels or {}
            svc = labels.get("com.docker.compose.service", c.name)
            if svc in seen:
                continue
            seen.add(svc)
            state = c.status if hasattr(c, "status") else "unknown"
            services.append({"id": svc, "name": svc, "state": state})
        return {"services": sorted(services, key=lambda s: s["id"])}
    except Exception as e:
        return {"services": [], "error": str(e)}


class ConfirmBody(BaseModel):
    confirm: bool = False
    dry_run: bool = False


@app.post("/services/{service_id}/start")
async def service_start(service_id: str, body: ConfirmBody, _: None = Depends(verify_token)):
    if service_id not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail=f"Service {service_id} not in allowlist")
    if body.dry_run:
        return {"would": "start", "service": service_id}
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm: true to execute")
    containers = _containers_for_service(service_id)
    if not containers:
        raise HTTPException(status_code=404, detail=f"No container found for service {service_id}")
    errs = []
    for c in containers:
        try:
            c.start()
        except Exception as e:
            errs.append(str(e))
    _audit("start", service_id, "error" if errs else "ok", "; ".join(errs) if errs else "")
    if errs:
        raise HTTPException(status_code=500, detail="; ".join(errs))
    return {"ok": True, "service": service_id, "action": "started"}


@app.post("/services/{service_id}/stop")
async def service_stop(service_id: str, body: ConfirmBody, _: None = Depends(verify_token)):
    if service_id not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail=f"Service {service_id} not in allowlist")
    if body.dry_run:
        return {"would": "stop", "service": service_id}
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm: true to execute")
    containers = _containers_for_service(service_id)
    if not containers:
        raise HTTPException(status_code=404, detail=f"No container found for service {service_id}")
    errs = []
    for c in containers:
        try:
            c.stop(timeout=30)
        except Exception as e:
            errs.append(str(e))
    _audit("stop", service_id, "error" if errs else "ok", "; ".join(errs) if errs else "")
    if errs:
        raise HTTPException(status_code=500, detail="; ".join(errs))
    return {"ok": True, "service": service_id, "action": "stopped"}


@app.post("/services/{service_id}/restart")
async def service_restart(service_id: str, body: ConfirmBody, _: None = Depends(verify_token)):
    if service_id not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail=f"Service {service_id} not in allowlist")
    if body.dry_run:
        return {"would": "restart", "service": service_id}
    if not body.confirm:
        raise HTTPException(status_code=400, detail="Set confirm: true to execute")
    containers = _containers_for_service(service_id)
    if not containers:
        raise HTTPException(status_code=404, detail=f"No container found for service {service_id}")
    errs = []
    for c in containers:
        try:
            c.restart(timeout=30)
        except Exception as e:
            errs.append(str(e))
    _audit("restart", service_id, "error" if errs else "ok", "; ".join(errs) if errs else "")
    if errs:
        raise HTTPException(status_code=500, detail="; ".join(errs))
    return {"ok": True, "service": service_id, "action": "restarted"}


@app.get("/services/{service_id}/logs")
async def service_logs(service_id: str, tail: int = 100, _: None = Depends(verify_token)):
    """Tail service logs. Auth required."""
    if service_id not in ALLOWED_SERVICES:
        raise HTTPException(status_code=400, detail=f"Service {service_id} not in allowlist")
    containers = _containers_for_service(service_id)
    if not containers:
        raise HTTPException(status_code=404, detail=f"No container found for service {service_id}")
    lines = []
    for c in containers:
        try:
            out = c.logs(tail=min(tail, 500), timestamps=True).decode("utf-8", errors="replace")
            lines.append(f"=== {c.name} ===\n{out}")
        except Exception as e:
            lines.append(f"=== {c.name} ===\nError: {e}")
    _audit("logs", service_id, "ok", "")
    return {"logs": "\n".join(lines), "service": service_id}


class PullBody(BaseModel):
    services: list[str] = []


@app.post("/images/pull")
async def images_pull(body: PullBody, _: None = Depends(verify_token)):
    svcs = [s for s in body.services if s in ALLOWED_SERVICES]
    if not svcs:
        raise HTTPException(status_code=400, detail="No allowed services specified")
    errs = []
    for svc in svcs:
        containers = _containers_for_service(svc)
        for c in containers:
            try:
                c.image.pull()
            except Exception as e:
                errs.append(f"{svc}: {e}")
    _audit("pull", ",".join(svcs), "error" if errs else "ok", "; ".join(errs) if errs else "")
    if errs:
        raise HTTPException(status_code=500, detail="; ".join(errs))
    return {"ok": True, "services": svcs}


@app.get("/mcp/containers")
async def mcp_containers(_: None = Depends(verify_token)):
    """List MCP server containers (spawned by mcp-gateway). Auth required."""
    try:
        client = _docker_client()
        all_containers = client.containers.list(all=True)
        mcp_containers = []
        for c in all_containers:
            image = (c.image.tags[0] if c.image.tags else str(c.image)) if hasattr(c, "image") else ""
            # MCP gateway spawns containers with mcp/* images
            if "mcp/" in image or (hasattr(c, "name") and "mcp" in (c.name or "").lower()):
                server_id = image.split("/")[-1].split(":")[0] if "/" in image else (c.name or "unknown")
                mcp_containers.append({
                    "id": server_id,
                    "name": c.name,
                    "status": c.status if hasattr(c, "status") else "unknown",
                    "image": image,
                })
        return {"containers": mcp_containers}
    except Exception as e:
        return {"containers": [], "error": str(e)}


@app.get("/audit")
async def audit(limit: int = 50, _: None = Depends(verify_token)):
    """Read audit log. Auth required."""
    if not AUDIT_LOG_PATH.exists():
        return {"entries": []}
    lines = AUDIT_LOG_PATH.read_text().strip().splitlines()
    entries = []
    for line in reversed(lines[-limit:]):
        try:
            entries.append(json.loads(line))
        except json.JSONDecodeError:
            continue
    return {"entries": list(reversed(entries))}
