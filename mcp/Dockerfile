# Extends docker/mcp-gateway with wrapper for runtime config reload (no container restart).
FROM docker/mcp-gateway:latest
COPY gateway-wrapper.sh /mcp-scripts/gateway-wrapper.sh
ENTRYPOINT ["/bin/sh", "/mcp-scripts/gateway-wrapper.sh"]
