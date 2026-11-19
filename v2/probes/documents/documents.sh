#!/bin/sh
set -eu
HERE=$(CDPATH= cd -- "$(dirname -- "$0")" && pwd)
stage=$1
shift
case "$stage" in
 make|show) exec python3 -I "$HERE/documents_plan.py" "$stage" "$@" ;;
 run) exec python3 -I "$HERE/documents_run.py" "$stage" "$@" ;;
 controls|judge|report) exec python3 -I "$HERE/documents_judge.py" "$stage" "$@" ;;
 *) echo "Unknown stage: $stage" >&2; exit 2 ;;
esac
