# OpenClaw Security & Trust Boundary

See [docs/ARCHITECTURE_RFC.md](../docs/ARCHITECTURE_RFC.md) Section 9 for the full stance.

## Quick Hardening

### 1. Bind UI to localhost only

Set in `.env` or docker-compose override:

```yaml
# Bind gateway to localhost only (access via Tailscale Serve)
ports:
  - "127.0.0.1:18789:18789"
  - "127.0.0.1:18790:18790"
```

### 2. Tailscale access

- Keep OpenClaw **off the public internet**
- Use **Tailscale Serve** to expose `127.0.0.1:18789` to your tailnet only
- Avoid Funnel unless intentional public exposure

### 3. Browser worker egress (when using web crawling)

If OpenClaw uses a browser worker for dynamic sites, block private ranges:

**Host firewall (DOCKER-USER chain):**

```bash
# Block browser container from reaching private networks (SSRF prevention)
# Replace <BROWSER_CONTAINER> with actual container name or use network
iptables -I DOCKER-USER -s <browser_subnet> -d 100.64.0.0/10 -j DROP
iptables -I DOCKER-USER -s <browser_subnet> -d 10.0.0.0/8 -j DROP
iptables -I DOCKER-USER -s <browser_subnet> -d 172.16.0.0/12 -j DROP
iptables -I DOCKER-USER -s <browser_subnet> -d 192.168.0.0/16 -j DROP
iptables -I DOCKER-USER -s <browser_subnet> -d 169.254.169.254 -j DROP
```

### 4. Secrets

- Store credentials only in controller (OpenClaw gateway) environment/volumes
- Browser worker must have **no secrets**, **no host mounts**
