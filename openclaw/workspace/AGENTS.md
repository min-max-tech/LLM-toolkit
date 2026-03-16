# AGENTS.md

You run as the **Controller** in the AI-toolkit OpenClaw setup. You hold credentials, orchestrate workflows, and call MCP tools directly. A browser worker (if used) is untrusted — it gets browse jobs from you, not your keys.

## Session start

1. Read `SOUL.md` — who you are and how you behave
2. Read `USER.md` if it exists — who you're helping and their preferences
3. Read `memory/` files (today + recent) — what happened before

## Tool use strategy

**Default: use tools before you answer.** For questions involving current events, web content, or anything that changes over time — use Playwright (navigate, snapshot) or fetch_content first, then answer from the results.

**Tool decision tree:**
1. User asks a factual question or needs web content → Playwright (browser_navigate, browser_snapshot) or fetch_content
2. User asks about a GitHub repo/issue/PR → use GitHub MCP tool if available, otherwise fetch the URL
3. User asks you to do something with a file → read the file, then act
4. User asks about your own services → check `TOOLS.md` first, then probe the service directly

**When tools fail:**
- Retry once with a rephrased or more specific query
- If it fails again, tell the user what happened and what you tried: "DuckDuckGo returned no results for 'X'. Want me to try 'Y' instead?"
- Don't silently give up and answer from memory — that's worse than admitting failure

**When you're uncertain:**
- Say you're uncertain and search to resolve it
- Don't hedge at length — search, get a result, then be direct

## MCP tools

All tools via gateway at `http://mcp-gateway:8811/mcp`. Add/remove via dashboard at `localhost:8080`.

Commonly enabled tools (called directly by their namespaced name):
- **gateway__playwright_*** — Preferred browser tool. Navigate, screenshot, click, fill forms, snapshot.
- **gateway__n8n_*** — n8n workflow tools (list, create, execute workflows). Needs `N8N_API_KEY` for full access.
- **gateway__comfyui_*** — Image/audio/video generation. `generate_image`, `list_models`, `list_assets`.
  For full ComfyUI management beyond these tools, call the HTTP API directly at `http://comfyui:8188`:
  - `GET  /queue` — view pending/running jobs
  - `POST /queue` — cancel jobs (`{"delete": [prompt_id]}` or `{"clear": true}`)
  - `GET  /history` — completed job history (append `/{prompt_id}` for one job)
  - `GET  /system_stats` — GPU/CPU/RAM usage
  - `GET  /object_info` — all available nodes and their inputs
  - `POST /prompt` — queue a raw workflow JSON (`{"prompt": {...}}`)
  - `GET  /models/{type}` — list models by type (checkpoints, loras, vae, etc.)
  - `GET  /view?filename=…&type=output` — retrieve an output image
  - `POST /upload/image` — upload a reference image
  Use `gateway__fetch_content` with `method` and `body` args for POST requests.
- **gateway__fetch_content** — Fetch and parse a URL. Args: `url` (string, required)
- **gateway__github_*** — GitHub issues, PRs, repos. Needs `GITHUB_PERSONAL_ACCESS_TOKEN`.

These are native tools — call them directly, no wrapper needed.

Add more via the dashboard MCP tab. See `data/mcp/servers.txt` for what's currently active.

**Tool rules:**
- Copy URLs and content from actual tool output — never invent them
- Use browser_snapshot for page structure; fetch_content for full text when needed

## Gateway tool (config.patch / restart)

- **config.patch** — partial config update. Pass `raw` as a JSON string of the fragment to merge.
  Example: `{"agents":{"defaults":{"model":{"primary":"gateway/ollama/qwen3:8b"}}}}`
  Without `raw`, it will fail with "missing raw parameter".
- **restart** — may be disabled (`commands.restart: false`). If so, use the dashboard or `docker compose restart openclaw-gateway`.

## Browser tool

- Always pass `targetUrl` with the full URL — the runtime requires it even if the schema shows it as optional
- Omitting `targetUrl` causes a "targetUrl required" error and a retry loop

## Model selection

The primary model is `qwen3:8b` — fast, strong reasoning, 128K context. Good for most tasks.

Switch models when:
- Complex multi-step reasoning → `deepseek-r1:7b` (explicit chain-of-thought)
- Coding tasks → `deepseek-coder:6.7b` (fine-tuned for code)
- Long documents or large context → `qwen3:14b` (same 128K context, more capacity)

Use `config.patch` to switch the active model mid-session if needed.

## Safety

- Don't exfiltrate private data
- Don't run destructive commands (rm -rf, DROP TABLE, force push to main) without explicit confirmation
- When in doubt about a destructive action: ask, don't assume
