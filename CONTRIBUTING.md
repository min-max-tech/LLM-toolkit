# Contributing

Thanks for contributing to Ordo AI Stack.

## What not to commit

This repo is public. **Never commit**:

- **`.env`** — contains API keys, tokens, paths. Use `.env.example` as a template.
- **`data/`** — contains user-specific runtime state (Hermes session data, Discord guild/user IDs, MCP config). Gitignored.
- **`models/`** — model files. Gitignored.
- **`overrides/compute.yml`** — hardware-specific. Gitignored.

Shared code should use placeholders (e.g. `YOUR_GUILD_ID`, `BASE_PATH=.`) or read from environment variables. See [SECURITY.md](SECURITY.md) for details.
