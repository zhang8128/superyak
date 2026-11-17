#!/bin/sh
# The rehearsal's first half; see pass_driver.py for the frozen file formats.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I "$HERE/pass_driver.py" "$@"
