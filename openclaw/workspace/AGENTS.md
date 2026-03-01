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

**Web search:** Use the MCP gateway tools (e.g. DuckDuckGo) for search. When the user asks for news, headlines, or "find X", **call the MCP search tool and wait for its real response.**

Rules for search results:
- **Show only what the tool response contains.** Copy URLs and headlines from the actual tool output. Do not paraphrase from memory.
- **Do not simulate the tool call.** Do not write placeholder output like `[[Searching...]]` then fill in invented content. Call the tool for real and use its output.
- **No invented URLs ever.** A URL you write must have come directly from tool output. If no URLs were returned, say: "The search didn't return any URLs for that query."
- **If the tool fails or returns nothing,** say so and offer to retry with a different query.

Local notes (cameras, SSH, TTS) go in `TOOLS.md`.

### Gateway tool

- **config.patch** — For partial config updates. You must pass `raw` as a JSON string of the config fragment to merge (e.g. `{"agents":{"defaults":{"model":{"primary":"gateway/ollama/deepseek-r1:7b"}}}}`). Without `raw`, the tool fails with "missing raw parameter".
- **restart** — May be disabled (`commands.restart: false`). If so, use the dashboard or `docker compose restart openclaw-gateway` instead.

### Browser tool

- **open / navigate** — The runtime requires `targetUrl` even though the schema may show it as optional. Always pass `targetUrl` with the full URL (e.g. `https://example.com/news`) when calling browser open or navigate. Omitting it causes "targetUrl required" and can put the agent in a retry loop.
