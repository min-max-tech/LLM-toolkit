"""Model Gateway — OpenAI-compatible proxy for Ollama, vLLM, and future providers."""
from __future__ import annotations

import asyncio
import json
import os
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import StreamingResponse
from httpx import AsyncClient

app = FastAPI(title="Model Gateway", version="1.0.0")

OLLAMA_URL = os.environ.get("OLLAMA_URL", "http://ollama:11434").rstrip("/")
VLLM_URL = os.environ.get("VLLM_URL", "").rstrip("/")  # e.g. http://vllm:8000
DEFAULT_PROVIDER = os.environ.get("DEFAULT_PROVIDER", "ollama")
DASHBOARD_URL = os.environ.get("DASHBOARD_URL", "").rstrip("/")


def _model_provider_and_id(name: str) -> tuple[str, str]:
    """Return (provider, model_id). Provider: ollama, vllm. Model ID is unprefixed."""
    if "/" in name:
        prefix, rest = name.split("/", 1)
        if prefix.lower() == "vllm" and VLLM_URL:
            return ("vllm", rest)
        return ("ollama", rest)
    return (DEFAULT_PROVIDER, name)


def _ollama_model_id(name: str) -> str:
    """Strip provider prefix if present (ollama/deepseek-r1:7b -> deepseek-r1:7b)."""
    _, model_id = _model_provider_and_id(name)
    return model_id


def _service_from_headers(origin: str | None, x_service: str | None) -> str:
    """Derive service name from Origin or X-Service-Name header."""
    if x_service and x_service.strip():
        return x_service.strip()[:64]
    if not origin:
        return "unknown"
    o = origin.lower()
    if ":3000" in o or "open-webui" in o:
        return "open-webui"
    if ":5678" in o or "n8n" in o:
        return "n8n"
    if ":8080" in o and "dashboard" not in o:
        return "dashboard"
    if "openclaw" in o or ":18789" in o or ":18790" in o:
        return "openclaw"
    # Fallback: host:port
    try:
        return origin.replace("http://", "").replace("https://", "").split("/")[0][:64]
    except Exception:
        return "unknown"


def _record_throughput(
    model: str, eval_count: int, eval_duration_ns: int, service: str = ""
) -> None:
    """Fire-and-forget: record throughput to dashboard for real-world stats."""
    if not DASHBOARD_URL or eval_count <= 0 or eval_duration_ns <= 0:
        return
    eval_duration_sec = eval_duration_ns / 1e9
    tps = eval_count / eval_duration_sec

    async def _post():
        try:
            async with AsyncClient(timeout=5.0) as client:
                await client.post(
                    f"{DASHBOARD_URL}/api/throughput/record",
                    json={
                        "model": model,
                        "output_tokens_per_sec": round(tps, 1),
                        "service": service or "unknown",
                    },
                )
        except Exception:
            pass

    asyncio.create_task(_post())


# --- Models ---


@app.get("/v1/models")
async def list_models():
    """List models in OpenAI format. Aggregates from Ollama and vLLM (when configured)."""
    objects = []

    # Ollama
    async with AsyncClient(timeout=30.0) as client:
        try:
            r = await client.get(f"{OLLAMA_URL}/api/tags")
            r.raise_for_status()
            data = r.json()
            for m in data.get("models", []):
                name = m.get("name", "")
                if name:
                    objects.append({
                        "id": f"ollama/{name}",
                        "object": "model",
                        "created": m.get("modified_at", 0) or 0,
                        "owned_by": "ollama",
                    })
        except Exception:
            pass

    # vLLM (OpenAI-compatible /v1/models)
    if VLLM_URL:
        try:
            async with AsyncClient(timeout=30.0) as client:
                r = await client.get(f"{VLLM_URL}/v1/models")
                if r.status_code < 500:
                    data = r.json()
                    for m in data.get("data", []):
                        mid = m.get("id", "")
                        if mid:
                            objects.append({
                                "id": f"vllm/{mid}" if "/" not in mid else mid,
                                "object": "model",
                                "created": m.get("created", 0) or 0,
                                "owned_by": "vllm",
                            })
        except Exception:
            pass

    return {"object": "list", "data": objects}


@app.get("/health")
async def health():
    """Gateway health check. OK if at least one provider is reachable."""
    ok = False
    try:
        async with AsyncClient(timeout=3.0) as client:
            r = await client.get(f"{OLLAMA_URL}/api/version")
            ok = ok or r.status_code < 500
    except Exception:
        pass
    if VLLM_URL:
        try:
            async with AsyncClient(timeout=3.0) as client:
                r = await client.get(f"{VLLM_URL}/health")
                ok = ok or r.status_code < 500
        except Exception:
            pass
    return {"ok": ok}


# --- Chat ---


def _ollama_to_openai_message(msg: dict) -> dict:
    """Convert Ollama message to OpenAI format."""
    role = msg.get("role", "assistant")
    content = msg.get("content", "")
    if isinstance(content, list):
        # Ollama can return content as list of parts
        text = "".join(p.get("text", "") if isinstance(p, dict) else str(p) for p in content)
    else:
        text = str(content)
    return {"role": role, "content": text}


def _stream_chunk_openai(obj: dict) -> str:
    """Format OpenAI SSE chunk."""
    return f"data: {json.dumps(obj)}\n\n"


@app.post("/v1/chat/completions")
async def chat_completions(request: Request, body: dict[str, Any]):
    """Chat completion. Proxies to Ollama or vLLM based on model prefix."""
    model = body.get("model", "")
    provider, model_id = _model_provider_and_id(model)
    service = _service_from_headers(
        request.headers.get("Origin"),
        request.headers.get("X-Service-Name") or request.headers.get("X-Client-Id"),
    )
    messages = body.get("messages", [])
    stream = body.get("stream", False)

    # vLLM: native OpenAI format — proxy directly
    if provider == "vllm" and VLLM_URL:
        if stream:
            async def vllm_stream():
                async with AsyncClient(timeout=600.0) as client:
                    async with client.stream(
                        "POST",
                        f"{VLLM_URL}/v1/chat/completions",
                        json={**body, "model": model_id},
                        headers={"Content-Type": "application/json"},
                    ) as r:
                        r.raise_for_status()
                        async for chunk in r.aiter_bytes():
                            yield chunk
            return StreamingResponse(
                vllm_stream(),
                media_type="text/event-stream",
                headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
            )
        async with AsyncClient(timeout=600.0) as client:
            r = await client.post(
                f"{VLLM_URL}/v1/chat/completions",
                json={**body, "model": model_id},
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            return r.json()

    # Ollama
    ollama_body = {"model": model_id, "messages": messages, "stream": stream}

    if stream:
        async def generate():
            prev = ""
            last_eval_count = 0
            last_eval_duration = 0
            async with AsyncClient(timeout=3600.0) as client:
                async with client.stream(
                    "POST", f"{OLLAMA_URL}/api/chat", json=ollama_body
                ) as resp:
                    async for line in resp.aiter_lines():
                        if not line or line == "data: [DONE]":
                            continue
                        try:
                            data = json.loads(line)
                            if data.get("done"):
                                last_eval_count = data.get("eval_count", 0)
                                last_eval_duration = data.get("eval_duration", 0)
                            msg = data.get("message", {})
                            content = msg.get("content", "")
                            if isinstance(content, list):
                                content = "".join(
                                    p.get("text", "") if isinstance(p, dict) else str(p)
                                    for p in content
                                )
                            else:
                                content = str(content)
                            # Ollama sends cumulative content; emit delta only
                            delta_text = content[len(prev):] if len(content) >= len(prev) else content
                            prev = content
                            if delta_text:
                                delta = {"content": delta_text, "role": "assistant"}
                                chunk = {
                                    "id": "chatcmpl-gateway",
                                    "object": "chat.completion.chunk",
                                    "model": model,
                                    "choices": [{"index": 0, "delta": delta, "finish_reason": None}],
                                }
                                yield _stream_chunk_openai(chunk)
                        except json.JSONDecodeError:
                            continue
            if last_eval_count and last_eval_duration:
                _record_throughput(model_id, last_eval_count, last_eval_duration, service)
            yield _stream_chunk_openai({"choices": [{"delta": {}, "finish_reason": "stop"}]})
            yield "data: [DONE]\n\n"

        return StreamingResponse(
            generate(),
            media_type="text/event-stream",
            headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
        )

    # Non-streaming
    async with AsyncClient(timeout=600.0) as client:
        r = await client.post(f"{OLLAMA_URL}/api/chat", json=ollama_body)
        r.raise_for_status()
        data = r.json()
    eval_count = data.get("eval_count", 0)
    eval_duration = data.get("eval_duration", 0)
    if eval_count and eval_duration:
        _record_throughput(model_id, eval_count, eval_duration, service)
    msg = data.get("message", {})
    content = msg.get("content", "")
    if isinstance(content, list):
        content = "".join(
            p.get("text", "") if isinstance(p, dict) else str(p) for p in content
        )
    return {
        "id": "chatcmpl-gateway",
        "object": "chat.completion",
        "model": model,
        "choices": [
            {
                "index": 0,
                "message": {"role": "assistant", "content": content},
                "finish_reason": "stop",
            }
        ],
        "usage": data.get("eval_count", {}),
    }


# --- Embeddings ---


@app.post("/v1/embeddings")
async def embeddings(body: dict[str, Any]):
    """Embeddings. Proxies to Ollama or vLLM based on model prefix."""
    model = body.get("model", "")
    provider, model_id = _model_provider_and_id(model)
    inp = body.get("input", "")

    if isinstance(inp, str):
        inp = [inp]
    if not inp:
        return {"object": "list", "data": [], "model": model}

    # vLLM: native OpenAI format
    if provider == "vllm" and VLLM_URL:
        async with AsyncClient(timeout=120.0) as client:
            r = await client.post(
                f"{VLLM_URL}/v1/embeddings",
                json={**body, "model": model_id},
                headers={"Content-Type": "application/json"},
            )
            r.raise_for_status()
            return r.json()

    # Ollama
    ollama_body = {"model": model_id, "input": inp}
    async with AsyncClient(timeout=120.0) as client:
        r = await client.post(f"{OLLAMA_URL}/api/embed", json=ollama_body)
        r.raise_for_status()
        data = r.json()

    embeds = data.get("embeddings", [])
    objects = []
    for i, emb in enumerate(embeds):
        objects.append({
            "object": "embedding",
            "embedding": emb,
            "index": i,
        })
    return {"object": "list", "data": objects, "model": model}
