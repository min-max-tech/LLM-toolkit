#!/bin/sh
set -eu

MASTER_KEY="${LITELLM_MASTER_KEY:-local}"

sed -e "s|__MASTER_KEY__|${MASTER_KEY}|g" /app/config.template.yaml > /tmp/config.yaml

exec litellm --config /tmp/config.yaml --host 0.0.0.0 --port 11435
