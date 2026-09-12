#!/usr/bin/env bash
# Finder/Terminal entrypoint. Configure login/account once before launching.
set -euo pipefail
cd "$(dirname "$0")/.."
stampede_python="${STAMPEDE_PYTHON:-$PWD/engram/.venv/bin/python}"
stampede_config="${STAMPEDE_CONFIG:-$PWD/.engram/stampede/config.json}"
if [[ ! -x "$stampede_python" ]]; then
  echo "Install the local environment first: make setup-engram" >&2
  exit 2
fi
if [[ ! -f "$stampede_config" ]]; then
  mkdir -p "$(dirname "$stampede_config")"
  cp deploy/stampede/config.example.json "$stampede_config"
  echo "Created $stampede_config" >&2
  echo "Set login and account in that file, then launch again." >&2
  exit 2
fi
exec "$stampede_python" -m deploy.stampede deploy --config "$stampede_config"
