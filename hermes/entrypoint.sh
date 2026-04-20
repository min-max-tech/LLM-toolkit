#!/usr/bin/env bash
# hermes/entrypoint.sh — container startup.
# 1. Seeds $HERMES_HOME/config.yaml with Docker-network endpoints.
# 2. Execs the compose-supplied command (hermes gateway, hermes dashboard, etc).
#
# Idempotent: re-writes only the keys we manage (model.* + mcp_servers.gateway.url).
# Preserves any other operator-set keys (skills, memory providers, Discord behavior).
set -eu

HERMES_HOME="${HERMES_HOME:-/home/hermes/.hermes}"
mkdir -p "$HERMES_HOME"
export HERMES_HOME

HERMES_BIN=/opt/hermes-agent/.venv/bin/hermes

# Seed model + MCP endpoints to Docker-network DNS. hermes config set is idempotent
# and overwrites stale values (e.g. localhost: from a prior host-mode install).
"$HERMES_BIN" config set model.provider        "custom"                        >/dev/null
"$HERMES_BIN" config set model.base_url        "http://model-gateway:11435/v1" >/dev/null
"$HERMES_BIN" config set model.api_key         "${LITELLM_MASTER_KEY:-local}"  >/dev/null
"$HERMES_BIN" config set model.default         "local-chat"                    >/dev/null
"$HERMES_BIN" config set mcp_servers.gateway.url "http://mcp-gateway:8811/mcp" >/dev/null

exec "$@"
