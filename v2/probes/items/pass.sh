#!/bin/sh
# The rehearsal's pass: plan, screen, history, list, offers, arms, report, run; see pass_driver.py for the file formats.
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
exec python3 -I "$HERE/pass_driver.py" "$@"
