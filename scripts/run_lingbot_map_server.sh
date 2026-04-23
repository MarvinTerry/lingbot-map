#!/usr/bin/env bash
set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$REPO_ROOT"

if [[ ! -x "$REPO_ROOT/.venv/bin/python" ]]; then
  echo "Missing virtualenv python at $REPO_ROOT/.venv/bin/python" >&2
  exit 1
fi

export PATH="$REPO_ROOT/.venv/bin:$PATH"

echo "Starting LingBot-Map server"
echo "Config is loaded from environment and optional $REPO_ROOT/.env"

exec "$REPO_ROOT/.venv/bin/python" -m lingbot_map_server
