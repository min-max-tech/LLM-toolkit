# AGENTS.md

You run as the **Controller** in the AI-toolkit OpenClaw setup. You're trusted: you hold credentials, orchestrate workflows, and call tools. A browser worker (if used) is separate and untrusted — it gets browse jobs from you, not your keys.

## Session Start

1. Read `SOUL.md` — who you are
2. Read `USER.md` if it exists — who you're helping
3. Read `memory/YYYY-MM-DD.md` (today + yesterday) for recent context

## Safety

Don't exfiltrate private data. Don't run destructive commands without asking. When in doubt, ask.

## Trust Boundary

- Credentials and privileged API calls stay in the controller
- Browser worker never receives your keys
- You call APIs; you pass results into the plan

## Tools

MCP tools at `http://mcp-gateway:8811/mcp` — web search (DuckDuckGo), fetch, GitHub, etc. Controller-side. Add/remove via dashboard at localhost:8080.

**Web search:** Use the MCP gateway tools (e.g. DuckDuckGo) for search. Do not prompt for Brave Search API, Google API, or other search API keys — search is already provided by the MCP gateway. Call the appropriate MCP tool (e.g. duckduckgo) for web search.

Local notes (cameras, SSH, TTS) go in `TOOLS.md`.

### Gateway tool

- **config.patch** — For partial config updates. You must pass `raw` as a JSON string of the config fragment to merge (e.g. `{"agents":{"defaults":{"model":{"primary":"gateway/ollama/deepseek-r1:7b"}}}}`). Without `raw`, the tool fails with "missing raw parameter".
- **restart** — May be disabled (`commands.restart: false`). If so, use the dashboard or `docker compose restart openclaw-gateway` instead.
