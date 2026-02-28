# MCP Module — Shared Model Context Protocol Gateway

The [Model Context Protocol (MCP)](https://modelcontextprotocol.io/) lets AI applications connect to external tools and data. This module runs Docker's [MCP Gateway](https://github.com/docker/mcp-gateway), giving all your LLM-toolkit services access to the same MCP servers through one endpoint.

## Quick Start

The MCP Gateway starts with the stack. By default it runs **DuckDuckGo** (web search). Add more servers via `.env`:

```bash
# In your project .env
MCP_GATEWAY_SERVERS=duckduckgo,fetch
```

Restart: `docker compose up -d mcp-gateway`

## Adding MCP Servers

Edit `MCP_GATEWAY_SERVERS` in `.env` (comma-separated, no spaces):

```bash
MCP_GATEWAY_SERVERS=duckduckgo,fetch,dockerhub,github-official
```

**Popular servers from the [Docker MCP Catalog](https://hub.docker.com/mcp):**

| Server | Purpose |
|--------|---------|
| `duckduckgo` | Web search |
| `fetch` | Fetch and parse web pages |
| `dockerhub` | Docker Hub / Docker Docs |
| `github-official` | GitHub (issues, PRs, repos) — needs `GITHUB_PERSONAL_ACCESS_TOKEN` |
| `brave` | Brave Search API — needs `BRAVE_API_KEY` |
| `mongodb` | MongoDB — needs connection string |
| `postgres` | PostgreSQL — needs `DATABASE_URL` |

Servers that need API keys or secrets require extra setup (see [Secrets](#secrets)).

## Connecting Services

### Open WebUI

1. Open **Admin Settings** → **External Tools**
2. Click **+ Add Server**
3. **Type:** MCP (Streamable HTTP)
4. **Server URL:** `http://mcp-gateway:8811/mcp` (from inside Docker) or `http://localhost:8811/mcp` (from host)
5. **Authentication:** None (for local gateway)
6. Save

### Cursor / Claude Desktop / VS Code

Point your MCP client to the gateway:

- **URL:** `http://localhost:8811/mcp` (Streamable HTTP)
- Or use `http://host.docker.internal:8811/mcp` if the client runs in a container

### OpenClaw

OpenClaw supports MCP via its config. For the gateway's Streamable HTTP endpoint, add to `data/openclaw/openclaw.json` (or via `clawdbot` config):

```json
{
  "mcp": {
    "servers": {
      "gateway": {
        "url": "http://mcp-gateway:8811/mcp",
        "transport": "streamable-http"
      }
    }
  }
}
```

(Exact schema depends on your OpenClaw version — see [OpenClaw MCP docs](https://docs.openclaw.ai/tools).)

## Secrets

MCP servers like `github-official` or `brave` need API keys. Use Docker secrets:

1. Create `mcp/.env` with your keys (do **not** commit):

   ```
   GITHUB_PERSONAL_ACCESS_TOKEN=ghp_...
   BRAVE_API_KEY=...
   ```

2. Uncomment the `secrets` block in `docker-compose.yml` for `mcp-gateway`
3. Add a `secrets` section to the compose file:

   ```yaml
   secrets:
     mcp_secrets:
       file: ./mcp/.env
   ```

4. Restart: `docker compose up -d mcp-gateway`

See [Docker MCP Gateway secrets](https://github.com/docker/mcp-gateway/tree/main/examples/secrets) for details.

## Port

Default: **8811**. Override with `MCP_GATEWAY_PORT` in `.env`.

## Requirements

- **Docker socket:** The gateway needs `/var/run/docker.sock` to spawn MCP server containers. On Docker Desktop (Windows/Mac), this is provided automatically.
- **Network:** Services must be on the same Docker network to reach `http://mcp-gateway:8811`.

## Troubleshooting

- **Gateway won't start:** Ensure Docker can access the socket. On some setups you may need to add the compose project to a network that has socket access.
- **"Connection refused" from a service:** Use `mcp-gateway` (not `localhost`) as the hostname when connecting from another container.
- **Server needs a secret:** Add the secret to `mcp/.env` and wire it via Docker secrets as above.
