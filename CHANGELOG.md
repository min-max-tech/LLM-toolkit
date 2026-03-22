# Changelog

All notable changes to this project are documented here. The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **OpenClaw channel secrets:** `merge_gateway_config.py` rewrites Discord and Telegram bot tokens to OpenClaw SecretRef form when `DISCORD_TOKEN` / `DISCORD_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN` is set in `.env`, so tokens need not live as plaintext in `openclaw.json`. `openclaw-gateway` receives `TELEGRAM_BOT_TOKEN` from the environment.
- **Housekeeping:** This changelog; PRD milestone updates for M6 (partial, non-auth) and resolved open questions where features already exist (CI, audit rotation, M7 spine).

### Changed

- **Documentation:** `SECURITY_HARDENING.md` §11 and `.env.example` describe channel SecretRef behavior and Telegram env wiring.
- **OpenClaw docs:** `openclaw/README.md`, `openclaw/OPENCLAW_SECURE.md`, and `openclaw/OPENCLAW_SECURE.md.example` updated for Discord/Telegram `.env` + `merge_gateway_config.py` SecretRef flow.
- **OpenClaw workspace:** Layered `SOUL.md` / `AGENTS.md` / `TOOLS.md` (policy vs environment contract); expanded `TOOLS.md` runbook; optional `USER.md.example`, `IDENTITY.md.example`, `HEARTBEAT.md.example`; `MEMORY.md` guidance; `openclaw-workspace-sync` now copies workspace `*.md` **only when missing** in `data/` (still refreshes `health_check.sh` and `agents/`); `ensure_openclaw_workspace.ps1` seeds the additional files.
