from __future__ import annotations

from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parent.parent
MERGE_SCRIPT = REPO_ROOT / "openclaw" / "scripts" / "merge_gateway_config.py"
OPENCLAW_CONFIG = REPO_ROOT / "data" / "openclaw" / "openclaw.json"


def test_merge_script_keeps_real_model_id_and_gateway_primary():
    text = MERGE_SCRIPT.read_text(encoding="utf-8")

    assert '"id": filename' in text
    assert 'desired_primary = active_model_id if "/" in active_model_id else f"gateway/{active_model_id}"' in text


def test_openclaw_config_uses_gateway_qualified_primary_model():
    text = OPENCLAW_CONFIG.read_text(encoding="utf-8")

    assert '"id": "google_gemma-4-31B-it-Q4_K_M.gguf"' in text
    assert '"primary": "gateway/google_gemma-4-31B-it-Q4_K_M.gguf"' in text
