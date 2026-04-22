#!/bin/sh
# Align the in-container "docker" group with the gid of the mounted /var/run/docker.sock
# so appuser can read it. On Docker Desktop for Windows/WSL2 the socket is root:root,
# so in that case add appuser to the root group instead.
set -e
if [ -S /var/run/docker.sock ]; then
  SOCK_GID=$(stat -c '%g' /var/run/docker.sock)
  if [ "$SOCK_GID" = "0" ]; then
    usermod -aG root appuser 2>/dev/null || true
  else
    groupmod -o -g "$SOCK_GID" docker 2>/dev/null \
      || groupadd -o -g "$SOCK_GID" socket-access 2>/dev/null && usermod -aG socket-access appuser 2>/dev/null \
      || true
  fi
fi
exec gosu appuser "$@"
