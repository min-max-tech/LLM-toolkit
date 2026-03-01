# Security Policy

## Supported Versions

| Version | Supported          |
| ------- | ------------------ |
| main    | :white_check_mark: |

This project follows a rolling release model. The `main` branch is supported.

## Reporting a Vulnerability

If you discover a security vulnerability, please report it responsibly:

1. **Do not** open a public issue for security vulnerabilities.
2. Email the maintainers or use GitHub Security Advisories if available.
3. Include:
   - Description of the vulnerability
   - Steps to reproduce
   - Potential impact
   - Suggested fix (if any)

We will acknowledge receipt and aim to respond within a reasonable timeframe.

## Security Considerations

### Authentication

- **Open WebUI:** The default `WEBUI_AUTH=False` disables login. This is intended for **local/single-user** use only. If you expose the stack to a network (e.g., via port forwarding or LAN access), **enable authentication** by setting `WEBUI_AUTH=True` in the environment.
- **OpenClaw:** Requires `OPENCLAW_GATEWAY_TOKEN`. Generate with `openssl rand -hex 32` and keep it secret.
- **n8n:** No built-in auth by default. Consider n8n's security options if exposed.

### Network Binding

Services bind to `0.0.0.0` to allow access from other machines on your network. Use a firewall to restrict access if needed.

### Secrets

- **Never commit** `.env`, `openclaw/.env`, or `mcp/.env`. They are gitignored.
- Use `.env.example` as a template; copy to `.env` and fill in values locally.
- API keys (OpenAI, Anthropic, etc.) and tokens should only live in `.env` files, never in the repository.

### Data

All runtime data is stored under `BASE_PATH/data/` via bind mounts. Ensure appropriate filesystem permissions and backups.

## Pre-deployment checklist

- [ ] `OPS_CONTROLLER_TOKEN` set (generate: `openssl rand -hex 32`)
- [ ] `OPENCLAW_GATEWAY_TOKEN` set in `openclaw/.env`
- [ ] `.env` and `openclaw/.env` not committed (in `.gitignore`)
- [ ] Ops controller port (9000) not exposed to host/network
- [ ] Dashboard bound to localhost or Tailscale-only when multi-user

## Threat mitigations

| Threat | Check |
|--------|-------|
| docker.sock exposure | Only ops-controller and mcp-gateway mount it; dashboard does not |
| Controller compromise | Token in env; no default; never expose port |
| MCP SSRF (browser worker) | Egress blocks for 100.64/10, RFC1918, 169.254.169.254 (see [ARCHITECTURE_RFC.md](docs/ARCHITECTURE_RFC.md) Section 9) |
| Secret exfiltration | No secrets in browser worker; controller-only API keys |
| Unauthenticated admin | Set `DASHBOARD_AUTH_TOKEN` or `DASHBOARD_PASSWORD` for Tailscale/group use |

## Audit

- [ ] Audit log path writable: `data/ops-controller/`
- [ ] Schema: [docs/audit/SCHEMA.md](docs/audit/SCHEMA.md)

## Break-glass

1. **Reset OPS_CONTROLLER_TOKEN:** Generate new token, update `.env`, restart dashboard + ops-controller
2. **Restore data:** Restore `data/` from backup (see [docs/runbooks/BACKUP_RESTORE.md](docs/runbooks/BACKUP_RESTORE.md))
3. **Disable MCP tools:** Clear `data/mcp/servers.txt` or set to single safe server
4. **Safe mode:** Stop mcp-gateway and openclaw-gateway; use ollama + open-webui only
