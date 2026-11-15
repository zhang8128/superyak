#!/bin/sh
# One turn of the pilot: a new room and a new copy of the items' repository, one item, one worker, one turn.
#
#   sh turn.sh <out-dir> <made-dir> <slug> <worker> [more words for the clock]
#
# <out-dir>   must not exist. It gets repo/, room/, item.txt, manifest.json (written before the clock starts:
#             the clock's command and environment word for word, the limits in force, the programs and
#             their versions; see records.py), started.txt, clock.log (each line with the UTC time it came),
#             clock.exit, ended.txt, turns.json (what the room recorded of the turn), and how busy the
#             machine was before and after (load-before.txt, load-after.txt).
#             The script ends with something other than 0 when what it leaves is not one usable
#             observation (records.py check): no turn, two, another worker's, one whose program did not run.
#             A turn that failed its check or ran to its limit is a usable observation.
# <made-dir>  what was made for the first run with model workers: repo/ (the items' repository, on branch
#             v2 at the commit every item is based on) and ids.txt (that base, and each item's wrong commit).
#             The copy made here takes the branch and the wrong commits over git's own transport, so nothing
#             a turn ever handed in comes with it.
# <slug>      item-add-wrong-commit, item-add-check-freezable or item-add-title.
# <worker>    as the clock names one, claude:opus say. The room gives an item only to a worker of another
#             family than its check's writer.
# From the environment:
#   YAK             the yak program.
#   YAK_PROBE_PATH  the PATH the clock is given: the worker's program, git and the toolchain are on it.
#   YAK_JAIL_READ   the directories the room shows its workers: the toolchain and the vendored crates.
#   YAK_VENDOR      the vendored crates' directory, which each item's check is told.
#   SDKROOT         passed on when it is set (see ../reach/run.sh).
#   YAK_PILOT_SLOT, YAK_PILOT_KIND  the turn's line in a pilot's plan, when pilot.sh runs this.
set -eu
HERE=$(cd "$(dirname "$0")" && pwd)
OUT=$1
MADE=$2
SLUG=$3
WORKER=$4
shift 4
[ ! -e "$OUT" ] || { echo "refused: $OUT exists"; exit 1; }
[ -x "${YAK:-}" ] || { echo "refused: YAK is not a program"; exit 1; }
[ -n "${YAK_PROBE_PATH:-}" ] || { echo "refused: YAK_PROBE_PATH is not set"; exit 1; }
[ -n "${YAK_JAIL_READ:-}" ] || { echo "refused: YAK_JAIL_READ is not set"; exit 1; }
[ -d "${YAK_VENDOR:-}" ] || { echo "refused: YAK_VENDOR is not a directory"; exit 1; }
[ -d "$MADE/repo" ] && [ -f "$MADE/ids.txt" ] || { echo "refused: $MADE holds no repo and ids.txt"; exit 1; }
case $SLUG in
item-add-wrong-commit)
    BY=codex:gpt-6.1-sol
    TITLE="yak item add refuses a wrong commit that is not a commit of the repository, and says which"
    ;;
item-add-check-freezable)
    BY=codex:gpt-6.1-sol
    TITLE="yak item add refuses a check that could never be frozen: an empty command, a file that is not a plain tracked file at the base, or a path that leads outside the repository"
    ;;
item-add-title)
    BY=claude:opus
    TITLE="yak item add refuses a title that is empty, more than one line, or longer than 200 characters"
    ;;
*)
    echo "refused: $SLUG is not one of the three items"
    exit 1
    ;;
esac
BASE=$(sed -n 's/^base //p' "$MADE/ids.txt")
WRONG=$(sed -n "s/^wrong $SLUG //p" "$MADE/ids.txt")
[ -n "$BASE" ] && [ -n "$WRONG" ] || { echo "refused: no base or no wrong commit for $SLUG in $MADE/ids.txt"; exit 1; }
mkdir -p "$OUT"
OUT=$(cd "$OUT" && pwd -P)
SRC=$(cd "$MADE/repo" && pwd -P)
# The copy: one branch and the wrong commits, fetched, so that it holds what those reach and no more.
git clone -q --no-local --no-tags --single-branch --branch v2 "$SRC" "$OUT/repo"
git -C "$OUT/repo" fetch -q origin 'refs/wrong/*:refs/wrong/*'
git -C "$OUT/repo" remote remove origin
[ "$(git -C "$OUT/repo" rev-parse HEAD)" = "$BASE" ] || { echo "refused: the copy's branch is not at $BASE"; exit 1; }
git -C "$OUT/repo" cat-file -e "$WRONG^{commit}" || { echo "refused: the copy lacks the wrong commit"; exit 1; }
# What turns handed in to the repository copied from is not in the copy. The control is the base, which is.
git -C "$OUT/repo" cat-file -e "$BASE^{commit}" || { echo "refused: the copy lacks its base"; exit 1; }
for answer in $(git -C "$SRC" for-each-ref --format='%(objectname)' 'refs/heads/room/'); do
    if git -C "$OUT/repo" cat-file -e "$answer" 2>/dev/null; then
        echo "refused: the copy holds $answer, which a turn handed in"
        exit 1
    fi
done
"$YAK" --room "$OUT/room" init
ID=$("$YAK" --room "$OUT/room" item add --title "$TITLE" --repo "$OUT/repo" --base "$BASE" \
    --check "sh v2/checks/$SLUG.sh $YAK_VENDOR" --file "v2/checks/$SLUG.sh" --wrong "$WRONG" \
    --origin observed --by "$BY")
printf '%s %s %s\n' "$SLUG" "$ID" "$WORKER" > "$OUT/item.txt"
date -u '+%Y-%m-%d %H:%M:%S UTC' > "$OUT/started.txt"
# The clock is given only what is named here, whatever this shell holds, and one turn.
set -- HOME="$HOME" USER="$USER" LOGNAME="$LOGNAME" SHELL="${SHELL:-/bin/sh}" LANG=en_US.UTF-8 TERM=dumb \
    PATH="$YAK_PROBE_PATH" YAK_JAIL_READ="$YAK_JAIL_READ" \
    "$YAK" --room "$OUT/room" clock run --once-through --daily-turns 1 --worker "$WORKER" "$@"
[ -z "${TMPDIR:-}" ] || set -- TMPDIR="$TMPDIR" "$@"
[ -z "${SDKROOT:-}" ] || set -- SDKROOT="$SDKROOT" "$@"
# Written down before the clock starts, from the very words it is about to be given.
python3 -I "$HERE/records.py" manifest "$OUT" "slot=${YAK_PILOT_SLOT:-}" "kind=${YAK_PILOT_KIND:-}" \
    "slug=$SLUG" "worker=$WORKER" "item=$ID" "base=$BASE" "wrong=$WRONG" \
    "check=sh v2/checks/$SLUG.sh $YAK_VENDOR" "check_file=v2/checks/$SLUG.sh" \
    "check_blob=$(git -C "$OUT/repo" rev-parse "$BASE:v2/checks/$SLUG.sh")" -- "$@"
# How busy the machine is, before and after: a turn's seconds are read beside it.
uptime > "$OUT/load-before.txt"
{
    # The clock ends with something other than 0 when its item is left open, which is no failure of this
    # script: its exit is written down either way.
    code=0
    env -i "$@" </dev/null || code=$?
    echo "$code" > "$OUT/clock.exit"
} 2>&1 | while IFS= read -r line; do
    printf '%s %s\n' "$(date -u '+%H:%M:%S')" "$line"
done > "$OUT/clock.log"
date -u '+%Y-%m-%d %H:%M:%S UTC' > "$OUT/ended.txt"
uptime > "$OUT/load-after.txt"
"$YAK" --room "$OUT/room" item turns "$ID" --json > "$OUT/turns.json"
# One usable observation, or this script fails: a turn that is lost is not passed over.
python3 -I "$HERE/records.py" check "$OUT"
