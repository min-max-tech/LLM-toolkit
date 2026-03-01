#!/usr/bin/env bash
# Optional: block MCP gateway (and spawned tool containers) from reaching private ranges
# and cloud metadata. Reduces SSRF risk. See docs/runbooks/SECURITY_HARDENING.md.
#
# Usage:
#   ./scripts/ssrf-egress-block.sh              # apply rules (requires root/sudo)
#   ./scripts/ssrf-egress-block.sh --dry-run      # print commands only
#   ./scripts/ssrf-egress-block.sh --remove      # remove rules added by this script
#
# Persistence: apt install iptables-persistent && sudo netfilter-persistent save

set -e

DRY_RUN=false
REMOVE=false
SUBNET=""

for arg in "$@"; do
  case "$arg" in
    --dry-run)  DRY_RUN=true ;;
    --remove)   REMOVE=true ;;
    -h|--help)
      echo "Usage: $0 [--dry-run|--remove] [SUBNET]"
      echo "  SUBNET: e.g. 172.18.0.0/16 (default: auto-detect from Docker network ai-toolkit-frontend)"
      exit 0
      ;;
    *) [ -z "$SUBNET" ] && SUBNET="$arg" ;;
  esac
done

if [ -z "$SUBNET" ]; then
  if command -v docker >/dev/null 2>&1; then
    SUBNET=$(docker network inspect ai-toolkit-frontend 2>/dev/null | jq -r '.[0].IPAM.Config[0].Subnet // empty')
    [ -z "$SUBNET" ] && SUBNET=$(docker network inspect ai-toolkit_default 2>/dev/null | jq -r '.[0].IPAM.Config[0].Subnet // empty')
  fi
  if [ -z "$SUBNET" ]; then
    echo "Could not detect subnet. Start the stack once (docker compose up -d), or pass SUBNET (e.g. 172.18.0.0/16)." >&2
    exit 1
  fi
  echo "Using subnet: $SUBNET"
fi

RUN() {
  if [ "$DRY_RUN" = true ]; then
    echo "Would run: $*"
  else
    "$@"
  fi
}

if [ "$REMOVE" = true ]; then
  echo "Removing DOCKER-USER rules for source $SUBNET..."
  for _ in 1 2 3 4 5 6 7 8; do
    sudo iptables -D DOCKER-USER -s "$SUBNET" -d 10.0.0.0/8     -j DROP 2>/dev/null || true
    sudo iptables -D DOCKER-USER -s "$SUBNET" -d 172.16.0.0/12  -j DROP 2>/dev/null || true
    sudo iptables -D DOCKER-USER -s "$SUBNET" -d 192.168.0.0/16 -j DROP 2>/dev/null || true
    sudo iptables -D DOCKER-USER -s "$SUBNET" -d 100.64.0.0/10 -j DROP 2>/dev/null || true
    sudo iptables -D DOCKER-USER -s "$SUBNET" -d 169.254.169.254/32 -j DROP 2>/dev/null || true
    sudo iptables -D DOCKER-USER -s "$SUBNET" -d 169.254.170.2/32   -j DROP 2>/dev/null || true
    sudo iptables -D DOCKER-USER -s "$SUBNET" -p udp --dport 53 -j ACCEPT 2>/dev/null || true
    sudo iptables -D DOCKER-USER -s "$SUBNET" -p tcp --dport 53 -j ACCEPT 2>/dev/null || true
  done
  echo "Done. Verify: sudo iptables -L DOCKER-USER -n -v"
  exit 0
fi

echo "Adding egress blocks for source $SUBNET (RFC1918, Tailscale, metadata)..."
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -d 10.0.0.0/8     -j DROP
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -d 172.16.0.0/12  -j DROP
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -d 192.168.0.0/16 -j DROP
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -d 100.64.0.0/10  -j DROP
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -d 169.254.169.254/32 -j DROP
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -d 169.254.170.2/32   -j DROP
# Allow DNS so MCP tools can resolve external hostnames
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -p udp --dport 53 -j ACCEPT
RUN sudo iptables -I DOCKER-USER -s "$SUBNET" -p tcp --dport 53 -j ACCEPT
echo "Done. Verify: sudo iptables -L DOCKER-USER -n -v"
echo "To persist (Debian/Ubuntu): sudo apt install iptables-persistent && sudo netfilter-persistent save"
