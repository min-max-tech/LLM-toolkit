"""RAG ingestion service — watches WATCH_DIR, chunks files, embeds via model-gateway, stores in Qdrant."""
from __future__ import annotations

import hashlib
import json
import os
import time
import uuid
from pathlib import Path

import httpx
from watchdog.events import FileSystemEventHandler
from watchdog.observers import Observer

GATEWAY_URL = os.environ.get("MODEL_GATEWAY_URL", "http://model-gateway:11435")
EMBED_MODEL = os.environ.get("EMBED_MODEL", "nomic-embed-text")
QDRANT_URL = os.environ.get("QDRANT_URL", "http://qdrant:6333")
COLLECTION = os.environ.get("QDRANT_COLLECTION", "documents")
WATCH_DIR = Path(os.environ.get("WATCH_DIR", "/watch"))
CHUNK_SIZE = int(os.environ.get("CHUNK_SIZE", "400"))
CHUNK_OVERLAP = int(os.environ.get("CHUNK_OVERLAP", "50"))
STATE_DIR = WATCH_DIR / ".rag-state"
STATE_FILE = STATE_DIR / "processed.json"

SUPPORTED_EXTENSIONS = {".txt", ".md", ".py", ".js", ".ts", ".go", ".rs", ".java", ".pdf"}


# --- State tracking ---

def _load_state() -> dict:
    try:
        return json.loads(STATE_FILE.read_text())
    except Exception:
        return {}


def _save_state(state: dict) -> None:
    STATE_DIR.mkdir(parents=True, exist_ok=True)
    STATE_FILE.write_text(json.dumps(state, indent=2))


def _file_key(path: Path) -> str:
    return str(path.relative_to(WATCH_DIR))


def _file_mtime(path: Path) -> float:
    return path.stat().st_mtime


# --- Text extraction ---

def _extract_text(path: Path) -> str:
    if path.suffix.lower() == ".pdf":
        try:
            from pypdf import PdfReader
            reader = PdfReader(str(path))
            return "\n".join(page.extract_text() or "" for page in reader.pages)
        except Exception as e:
            print(f"[warn] PDF extraction failed for {path}: {e}")
            return ""
    try:
        return path.read_text(encoding="utf-8", errors="replace")
    except Exception as e:
        print(f"[warn] Could not read {path}: {e}")
        return ""


# --- Chunking ---

def _chunk(text: str, size: int, overlap: int) -> list[str]:
    words = text.split()
    if not words:
        return []
    chunks = []
    i = 0
    while i < len(words):
        chunk = " ".join(words[i : i + size])
        if chunk.strip():
            chunks.append(chunk)
        i += size - overlap
    return chunks


# --- Embedding ---

def _embed(texts: list[str]) -> list[list[float]]:
    resp = httpx.post(
        f"{GATEWAY_URL}/v1/embeddings",
        json={"model": EMBED_MODEL, "input": texts},
        headers={"X-Service-Name": "rag-ingestion"},
        timeout=60.0,
    )
    resp.raise_for_status()
    data = resp.json()
    return [item["embedding"] for item in data["data"]]


# --- Qdrant ---

def _ensure_collection(vector_size: int) -> None:
    r = httpx.get(f"{QDRANT_URL}/collections/{COLLECTION}", timeout=10.0)
    if r.status_code == 200:
        return
    httpx.put(
        f"{QDRANT_URL}/collections/{COLLECTION}",
        json={"vectors": {"size": vector_size, "distance": "Cosine"}},
        timeout=15.0,
    ).raise_for_status()
    print(f"[info] Created Qdrant collection '{COLLECTION}' (dim={vector_size})")


def _upsert_points(points: list[dict]) -> None:
    httpx.put(
        f"{QDRANT_URL}/collections/{COLLECTION}/points",
        json={"points": points},
        timeout=30.0,
    ).raise_for_status()


def _delete_by_source(source_key: str) -> None:
    try:
        httpx.post(
            f"{QDRANT_URL}/collections/{COLLECTION}/points/delete",
            json={"filter": {"must": [{"key": "source", "match": {"value": source_key}}]}},
            timeout=10.0,
        )
    except Exception:
        pass


# --- Ingest one file ---

def ingest_file(path: Path, state: dict) -> None:
    key = _file_key(path)
    mtime = _file_mtime(path)

    if state.get(key, {}).get("mtime") == mtime:
        return  # unchanged

    print(f"[info] Ingesting {key} …")
    text = _extract_text(path)
    if not text.strip():
        print(f"[warn] No text extracted from {key}, skipping")
        state[key] = {"mtime": mtime, "chunks": 0}
        return

    chunks = _chunk(text, CHUNK_SIZE, CHUNK_OVERLAP)
    if not chunks:
        state[key] = {"mtime": mtime, "chunks": 0}
        return

    try:
        embeddings = _embed(chunks)
    except Exception as e:
        print(f"[error] Embedding failed for {key}: {e}")
        return

    vector_size = len(embeddings[0])
    _ensure_collection(vector_size)
    _delete_by_source(key)  # remove old version first

    points = [
        {
            "id": str(uuid.uuid5(uuid.NAMESPACE_URL, f"{key}::{i}")),
            "vector": emb,
            "payload": {"source": key, "chunk_index": i, "text": chunk},
        }
        for i, (chunk, emb) in enumerate(zip(chunks, embeddings))
    ]
    _upsert_points(points)
    state[key] = {"mtime": mtime, "chunks": len(chunks)}
    print(f"[info] {key}: {len(chunks)} chunks stored")


def ingest_all(state: dict) -> None:
    for path in sorted(WATCH_DIR.rglob("*")):
        if path.is_file() and path.suffix.lower() in SUPPORTED_EXTENSIONS and ".rag-state" not in path.parts:
            try:
                ingest_file(path, state)
            except Exception as e:
                print(f"[error] {path}: {e}")
    _save_state(state)


# --- Watchdog ---

class IngestHandler(FileSystemEventHandler):
    def __init__(self, state: dict):
        self._state = state

    def _handle(self, path_str: str) -> None:
        path = Path(path_str)
        if not path.is_file():
            return
        if path.suffix.lower() not in SUPPORTED_EXTENSIONS:
            return
        if ".rag-state" in path.parts:
            return
        try:
            ingest_file(path, self._state)
            _save_state(self._state)
        except Exception as e:
            print(f"[error] {path}: {e}")

    def on_created(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_modified(self, event):
        if not event.is_directory:
            self._handle(event.src_path)

    def on_moved(self, event):
        if not event.is_directory:
            self._handle(event.dest_path)


# --- Startup wait ---

def _wait_for_services() -> None:
    for name, url in [("Qdrant", f"{QDRANT_URL}/readyz"), ("model-gateway", f"{GATEWAY_URL}/health")]:
        for _ in range(30):
            try:
                r = httpx.get(url, timeout=5.0)
                if r.status_code < 400:
                    print(f"[info] {name} ready")
                    break
            except Exception:
                pass
            print(f"[info] Waiting for {name} …")
            time.sleep(5)


# --- Main ---

def main() -> None:
    print(f"[info] RAG ingestion starting — watching {WATCH_DIR}, embed={EMBED_MODEL}, collection={COLLECTION}")
    WATCH_DIR.mkdir(parents=True, exist_ok=True)
    _wait_for_services()

    state = _load_state()
    print("[info] Running initial scan …")
    ingest_all(state)

    handler = IngestHandler(state)
    observer = Observer()
    observer.schedule(handler, str(WATCH_DIR), recursive=True)
    observer.start()
    print("[info] Watching for changes …")
    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
    observer.join()


if __name__ == "__main__":
    main()
