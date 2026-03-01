# Extends docker/mcp-gateway with wrapper for runtime config reload (no container restart).
FROM docker/mcp-gateway:latest
USER root
# Add jq for registry.json parsing (Alpine or Debian)
RUN apk add --no-cache jq 2>/dev/null || (apt-get update -qq && apt-get install -y -qq jq && rm -rf /var/lib/apt/lists/*) 2>/dev/null || true
COPY gateway-wrapper.sh /mcp-scripts/gateway-wrapper.sh
ENTRYPOINT ["/bin/sh", "/mcp-scripts/gateway-wrapper.sh"]
