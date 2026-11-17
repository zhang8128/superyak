#!/bin/sh
# One listed item, fresh repository and room, one turn; see pilot_driver.py.
# sh turn.sh <out-dir> <items-dir> <commit> <worker> [more words for the clock]
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I "$HERE/pilot_driver.py" turn "$@"
