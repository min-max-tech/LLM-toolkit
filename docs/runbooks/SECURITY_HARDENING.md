# Security Hardening Runbook

Operational guidance for hardening the AI-toolkit stack beyond the defaults.

**See also:** [SECURITY.md](../../SECURITY.md) · [ARCHITECTURE_RFC.md](../ARCHITECTURE_RFC.md) WS4

---

## 1. SSRF Egress Blocks (MCP Gateway)

The MCP gateway spawns tool containers that make outbound HTTP calls. Without egress controls, a
malicious or misconfigured tool can reach internal services (Ollama, ops-controller, cloud metadata).

### Linux host (iptables / DOCKER-USER chain)

```bash
# Find the subnet used by MCP containers.
# The docker network name is usually ai-toolkit_default or ai-toolkit-backend.
docker network inspect ai-toolkit_default | jq '.[0].IPAM.Config[].Subnet'
# Example output: "172.18.0.0/16"
MCP_SUBNET="172.18.0.0/16"   # replace with your subnet

# Block RFC1918 (private) ranges
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -d 10.0.0.0/8     -j DROP
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -d 172.16.0.0/12  -j DROP
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -d 192.168.0.0/16 -j DROP

# Block Tailscale range
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -d 100.64.0.0/10  -j DROP

# Block cloud metadata endpoints
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -d 169.254.169.254/32 -j DROP
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -d 169.254.170.2/32   -j DROP  # ECS metadata

# Allow DNS (required for outbound tool calls)
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -p udp --dport 53 -j ACCEPT
sudo iptables -I DOCKER-USER -s "$MCP_SUBNET" -p tcp --dport 53 -j ACCEPT

# Verify
sudo iptables -L DOCKER-USER -n --line-numbers
```

**Make persistent:** On Debian/Ubuntu: `apt install iptables-persistent && netfilter-persistent save`.
On RHEL/Fedora: use `firewalld` rich rules or `iptables-services`.

### Windows host (WSL2 / Docker Desktop)

Docker Desktop on Windows uses a virtual network; DOCKER-USER is not directly accessible.
Alternatives:
- Use Docker Desktop network policies (enterprise feature) or a network plugin.
- Run a proxy container between MCP and the internet with egress filtering.
- Accept reduced protection for local-only use (default posture).

---

## 2. Ops Controller Port Isolation

The ops controller runs without a host port by default (internal Docker network only).
**Never expose port 9000 to the network** unless behind a VPN/firewall.

To verify no host port is exposed:
```bash
docker inspect ai-toolkit-ops-controller-1 --format '{{json .HostConfig.PortBindings}}'
# Expected: {} (empty)
```

If you need remote access to the controller for debugging, use SSH tunneling:
```bash
ssh -L 9000:localhost:9000 user@host
# Then access locally: curl http://localhost:9000/health
```

---

## 3. Dashboard Auth

By default, `DASHBOARD_AUTH_TOKEN` and `DASHBOARD_PASSWORD` are empty and auth is disabled.
For any multi-user or networked deployment, set one of these in `.env`:

```bash
# Bearer token auth (recommended for programmatic access)
DASHBOARD_AUTH_TOKEN=$(openssl rand -hex 32)

# OR: Basic password auth (for browser use)
DASHBOARD_PASSWORD=<strong-passphrase>
```

Then restart the dashboard: `docker compose up -d dashboard`.

---

## 4. Token Rotation

All tokens live in `.env` (gitignored). To rotate:

```bash
# Generate new token
NEW_TOKEN=$(openssl rand -hex 32)

# Update .env
# Replace OPS_CONTROLLER_TOKEN or OPENCLAW_GATEWAY_TOKEN with the new value

# Restart affected services
docker compose up -d dashboard ops-controller   # for OPS_CONTROLLER_TOKEN
docker compose restart openclaw-gateway          # for OPENCLAW_GATEWAY_TOKEN
# Re-pair OpenClaw clients after gateway restart (see TROUBLESHOOTING.md)
```

---

## 5. Open WebUI Auth

Open WebUI ships with `WEBUI_AUTH=True` by default in this stack.
If you're on a single-user local machine and want to skip the login:

```bash
# .env
WEBUI_AUTH=False
```

For shared/LAN use, keep `WEBUI_AUTH=True` and create a strong admin account on first launch.

---

## 6. Container Hardening Verification

After `docker compose up -d`, verify hardening is applied to custom services:

```bash
# Check cap_drop on model-gateway
docker inspect $(docker compose ps -q model-gateway) \
  --format '{{.HostConfig.CapDrop}}' 
# Expected: [ALL]

# Check read-only rootfs on dashboard
docker inspect $(docker compose ps -q dashboard) \
  --format '{{.HostConfig.ReadonlyRootfs}}'
# Expected: true

# Check no-new-privileges
docker inspect $(docker compose ps -q model-gateway) \
  --format '{{.HostConfig.SecurityOpt}}'
# Expected: [no-new-privileges:true]
```

---

## 7. Supply Chain

Optional: scan images before deploy.

```bash
# Install Trivy (https://aquasecurity.github.io/trivy/)
# Scan Ollama image
trivy image ollama/ollama:0.17.4

# Scan custom builds
docker compose build model-gateway
trivy image ai-toolkit-model-gateway:latest
```

For pinned digests, see the comment in `docker-compose.yml` under `ollama`:
```
# Pin digest: OLLAMA_IMAGE=ollama/ollama:0.17.4@sha256:...
```
Run `docker inspect ollama/ollama:0.17.4 --format '{{index .RepoDigests 0}}'` to get the digest.

---

## 8. Filesystem MCP Server

The `filesystem` MCP server is disabled by default (`allow_clients: []` in `data/mcp/registry.json`).
To enable it safely:

1. Decide which directory to expose (e.g. a specific project folder, NOT `/` or home).
2. Add to `mcp/.env`:
   ```
   FILESYSTEM_ROOT=/path/to/allowed/directory
   ```
3. Wire the secret in `docker-compose.yml` under `mcp-gateway` (uncomment the `secrets:` block).
4. Edit `data/mcp/servers.txt` and add `filesystem`.
5. Restart: `docker compose up -d mcp-gateway`.
6. **Test:** Verify the server can only access the intended directory.
