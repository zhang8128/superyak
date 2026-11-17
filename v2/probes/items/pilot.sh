#!/bin/sh
# sh pilot.sh <pilot-dir> <items-dir> <worker> --references <dir>
# sh pilot.sh --plan <items-dir> <worker>
# Receipts: <dir>/<full-commit>/reference.json, as reference.sh writes them.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I "$HERE/pilot_driver.py" pilot "$@"
