#!/usr/bin/env bash
# Host-side: same logic as workspace_sync_upgrade_tools.sh (paths from BASE_PATH / DATA_PATH).
# Set OPENCLAW_SKIP_TOOLS_MD_UPGRADE=1 to skip.
set -euo pipefail
if [[ "${OPENCLAW_SKIP_TOOLS_MD_UPGRADE:-0}" == "1" ]]; then
  exit 0
fi

base="${BASE_PATH:-$(cd "$(dirname "${BASH_SOURCE[0]}")/../.." && pwd)}"
base="${base//\\//}"
data="${DATA_PATH:-$base/data}"
workspace="$data/openclaw/workspace"
example="$base/openclaw/workspace/TOOLS.md.example"
dest="$workspace/TOOLS.md"

[[ -f "$example" ]] || exit 0
mkdir -p "$workspace"

need=0
if [[ ! -f "$dest" ]]; then
  need=1
elif ! grep -q 'gateway__tavily_search' "$dest" 2>/dev/null; then
  need=1
fi
if [[ "$need" -eq 1 ]]; then
  cp "$example" "$dest"
  echo "Upgraded TOOLS.md from TOOLS.md.example (missing or stale stub)."
fi
