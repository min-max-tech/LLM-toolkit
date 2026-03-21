"""Patch upstream comfyui_client.py after git clone — longer waits for FLUX / large checkpoints.

Env (read at runtime in container):
  COMFY_MCP_MAX_WAIT_SEC   — poll attempts for /history (default 600, ~1s per attempt)
  COMFY_MCP_HTTP_TIMEOUT_SEC — HTTP timeout for POST /prompt (default 180)
"""
from __future__ import annotations

from pathlib import Path


def main() -> None:
    p = Path("comfyui_client.py")
    text = p.read_text(encoding="utf-8")
    if "COMFY_MCP_MAX_WAIT_SEC" in text:
        print("patch_comfyui_client: already applied")
        return

    if "import os" not in text.split("\n", 5)[:5]:
        text = "import os\n" + text

    old_run = (
        "def run_custom_workflow(self, workflow: Dict[str, Any], preferred_output_keys: Sequence[str] | None = None, max_attempts: int = 30):"
    )
    new_run = (
        "def run_custom_workflow(self, workflow: Dict[str, Any], preferred_output_keys: Sequence[str] | None = None, max_attempts: int = int(os.getenv(\"COMFY_MCP_MAX_WAIT_SEC\", \"600\"))):"
    )
    if old_run not in text:
        raise SystemExit("patch_comfyui_client: run_custom_workflow signature not found — upstream changed?")
    text = text.replace(old_run, new_run)

    old_wait = "def _wait_for_prompt(self, prompt_id: str, max_attempts: int = 30):"
    new_wait = "def _wait_for_prompt(self, prompt_id: str, max_attempts: int = int(os.getenv(\"COMFY_MCP_MAX_WAIT_SEC\", \"600\"))):"
    if old_wait not in text:
        raise SystemExit("patch_comfyui_client: _wait_for_prompt signature not found — upstream changed?")
    text = text.replace(old_wait, new_wait)

    old_post = 'requests.post(f"{self.base_url}/prompt", json={"prompt": workflow}, timeout=30)'
    new_post = 'requests.post(f"{self.base_url}/prompt", json={"prompt": workflow}, timeout=int(os.getenv("COMFY_MCP_HTTP_TIMEOUT_SEC", "180")))'
    if old_post not in text:
        raise SystemExit("patch_comfyui_client: prompt POST line not found — upstream changed?")
    text = text.replace(old_post, new_post)

    p.write_text(text, encoding="utf-8")
    print("patch_comfyui_client: ok (COMFY_MCP_MAX_WAIT_SEC, COMFY_MCP_HTTP_TIMEOUT_SEC)")


if __name__ == "__main__":
    main()
