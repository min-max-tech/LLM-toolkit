# Changelog

All notable changes to this project are documented here. The format is loosely based on [Keep a Changelog](https://keepachangelog.com/).

## [Unreleased]

### Added

- **OpenClaw channel secrets:** `merge_gateway_config.py` rewrites Discord and Telegram bot tokens to OpenClaw SecretRef form when `DISCORD_TOKEN` / `DISCORD_BOT_TOKEN` or `TELEGRAM_BOT_TOKEN` is set in `.env`, so tokens need not live as plaintext in `openclaw.json`. `openclaw-gateway` receives `TELEGRAM_BOT_TOKEN` from the environment.
- **Housekeeping:** This changelog; PRD milestone updates for M6 (partial, non-auth) and resolved open questions where features already exist (CI, audit rotation, M7 spine).

### Changed

- **Documentation:** `SECURITY_HARDENING.md` §11 and `.env.example` describe channel SecretRef behavior and Telegram env wiring.
