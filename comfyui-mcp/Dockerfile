# ComfyUI MCP Server — joenorton/comfyui-mcp-server
# Connects to remote ComfyUI for image/audio/video generation.
FROM python:3.12-slim

WORKDIR /app

# Clone and install from source (includes workflows, COMFYUI_URL support)
COPY patch_comfyui_client.py /tmp/patch_comfyui_client.py
RUN apt-get update -qq && apt-get install -y -qq git curl && rm -rf /var/lib/apt/lists/* \
  && git clone --depth 1 https://github.com/joenorton/comfyui-mcp-server.git . \
  && pip install --no-cache-dir -r requirements.txt \
  && sed -i 's/port=9000,/port=9000, host="0.0.0.0",/' server.py \
  && python3 /tmp/patch_comfyui_client.py

# Server binds to 0.0.0.0:9000; ComfyUI at comfyui:8188
# Poll/wait for slow generations (FLUX). Override in compose if needed.
ENV COMFYUI_URL=http://comfyui:8188
ENV COMFY_MCP_MAX_WAIT_SEC=600
ENV COMFY_MCP_HTTP_TIMEOUT_SEC=180
EXPOSE 9000

# Use stdio so Docker MCP Gateway can communicate (it spawns containers and uses stdin/stdout)
CMD ["python", "server.py", "--stdio"]
