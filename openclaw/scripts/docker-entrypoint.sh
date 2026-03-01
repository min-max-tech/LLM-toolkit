#!/bin/sh
# Install MCP bridge plugin into the mounted config dir if missing, then start OpenClaw.
set -e
CONFIG_DIR="${OPENCLAW_CONFIG_DIR:-/home/node/.openclaw}"
EXT_DIR="${CONFIG_DIR}/extensions"
if [ ! -d "${EXT_DIR}/openclaw-mcp-bridge" ]; then
  echo "Installing openclaw-mcp-bridge plugin..."
  openclaw plugins install openclaw-mcp-bridge --pin
fi
exec openclaw "$@"
