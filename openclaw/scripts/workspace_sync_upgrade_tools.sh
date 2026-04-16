#!/bin/sh
# Used only inside openclaw-workspace-sync (paths /templates, /workspace).
# Replaces stale short TOOLS.md with TOOLS.md.example when the contract markers are missing.
set -e
if [ "${OPENCLAW_SKIP_TOOLS_MD_UPGRADE:-0}" = "1" ]; then
  exit 0
fi
EXAMPLE="/templates/TOOLS.md.example"
DEST="/workspace/TOOLS.md"
[ -f "$EXAMPLE" ] || exit 0
need=0
if [ ! -f "$DEST" ]; then
  need=1
elif ! grep -q 'gateway__tavily_search' "$DEST" 2>/dev/null; then
  need=1
fi
if [ "$need" -eq 1 ]; then
  cp "$EXAMPLE" "$DEST"
  echo "[openclaw-workspace-sync] Upgraded TOOLS.md from TOOLS.md.example (missing or stale stub)"
fi
