#!/bin/sh
# Show a reference through the jail, without a model; leaves reference.json and turn/.
# sh reference.sh <out-dir> <items-dir> <commit>
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I "$HERE/pilot_driver.py" reference "$@"
