#!/bin/sh
# yak item add refuses a check that could never be frozen: an empty command, a file that is not a plain tracked file at the base, or a path that leads outside the repository
#
# Refuse an empty command and a command of spaces. Refuse a file absent from
# the base; a base directory; a tracked symbolic link; an untracked working
# file; and a file tracked only in a later commit. Refuse ../x, an absolute
# outside path, and checks/../../x; the outside file actually exists.
# Refuse the entire add when an absent file is first, middle, or last among
# valid --file values, and name the absent value in the one stderr line.
# Every refusal exits nonzero, has no stdout and exactly one stderr line,
# and adds no item. No further error wording is required.
#
# Controls before and after each refusal accept nearby nonempty commands or
# plain tracked files. Before and after the suite, accept a plain base file,
# a subdirectory file, an executable base file, a base file deleted from the
# working tree, and a command with no --file. Success prints the added id.
# Other freezer path-spelling restrictions are outside this item's scope.
#
# Run at the candidate clone's root with an absolute vendor directory as $1.
# Build its yak offline and locked, using crates-io replacement by that vendor
# directory and clone-local target/CARGO_HOME. All git fixtures and the room
# live in a fresh TMPDIR child, removed on exit; no clock or check is run.

check_name=item-add-check-freezable
set -eu
LC_ALL=C
export LC_ALL

fatal() {
    printf 'FAIL setup: %s\n' "$*"
    exit 1
}

[ "$#" -eq 1 ] || fatal 'usage: sh CHECK <absolute-vendor-dir>'
case $1 in
    /*) ;;
    *) fatal 'vendor directory must be absolute' ;;
esac
clone=$(pwd -P)
CARGO_HOME="$clone/v2/target/cargo-home"
CARGO_TARGET_DIR="$clone/v2/target"
export CARGO_HOME CARGO_TARGET_DIR
[ -n "${TMPDIR:-}" ] || fatal 'TMPDIR must name the scratch directory'
work=$(mktemp -d "$TMPDIR/$check_name.XXXXXX")
trap 'rm -rf "$work"' 0
trap 'exit 1' HUP INT TERM
# Keep build-tool temporary files inside the directory removed by the trap too.
mkdir "$work/tmp"
TMPDIR="$work/tmp"
export TMPDIR
if ! (cd "$clone/v2" && cargo build -q -p yak --offline --locked \
    --config 'source.crates-io.replace-with="vendored"' \
    --config "source.vendored.directory=\"$1\""); then
    fatal 'offline yak build failed'
fi
yak="$clone/v2/target/debug/yak"
repo="$work/repo"
room="$work/room"
mkdir "$repo"

git_fixture() {
    git -c user.name=Check -c user.email=check@example.invalid \
        -c commit.gpgsign=false -c core.hooksPath=/dev/null -C "$repo" "$@"
}

snapshot() {
    if ! "$yak" --room "$room" item list </dev/null \
        >"$work/list.json" 2>"$work/list.err"; then
        cat "$work/list.err"
        fatal 'yak item list failed'
    fi
    item_count=$(awk '/^[ \t]*"id"[ \t]*:/ { n++ } END { print n+0 }' "$work/list.json")
}

run_add() {
    add_command=$1
    shift
    "$yak" --room "$room" item add --title 'Frozen check fixture' \
        --repo "$repo" --base "$base" --check "$add_command" \
        --origin outside --by person:check "$@" </dev/null
}

fail_case() {
    failures=$((failures + 1))
    printf 'FAIL %s: expected %s; exit=%s; stdout=<%s>; stderr-lines=%s; stderr=<%s>; items=%s->%s\n' \
        "$case_name" "$expectation" "$code" "$(cat "$work/out")" \
        "$stderr_lines" "$(cat "$work/err")" "$before" "$item_count"
}

accept() {
    case_name=$1
    shift
    cases=$((cases + 1))
    snapshot
    before=$item_count
    if run_add "$@" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
    snapshot
    stderr_lines=$(awk 'END { print NR+0 }' "$work/err")
    id=$(cat "$work/out")
    # The printed value must identify the item just added, not merely be nonempty.
    if [ "$code" -ne 0 ] || [ -z "$id" ] || [ "$item_count" -ne "$((before + 1))" ] ||
        ! awk -v id="$id" '$1 == "\"id\":" { gsub(/[",]/, "", $2); if ($2 == id) found=1 } END { exit !found }' "$work/list.json"; then
        expectation='acceptance and an added item id on stdout'
        fail_case
    fi
}

refuse() {
    case_name=$1
    named=$2
    shift 2
    cases=$((cases + 1))
    snapshot
    before=$item_count
    if run_add "$@" >"$work/out" 2>"$work/err"; then code=0; else code=$?; fi
    snapshot
    stderr_lines=$(awk 'END { print NR+0 }' "$work/err")
    good=yes
    if [ "$code" -eq 0 ] || [ -s "$work/out" ] || [ "$stderr_lines" -ne 1 ] ||
        [ "$item_count" -ne "$before" ]; then good=no; fi
    if [ -n "$named" ] && ! grep -F -e "$named" "$work/err" >/dev/null; then good=no; fi
    if [ "$good" = no ]; then
        expectation='nonzero exit, empty stdout, one stderr line, no added item'
        if [ -n "$named" ]; then expectation="$expectation, naming $named"; fi
        fail_case
    fi
}

finish() {
    if [ "$failures" -ne 0 ]; then
        printf 'FAIL %s: %s of %s cases failed\n' "$check_name" "$failures" "$cases"
        exit 1
    fi
    printf 'PASS %s: %s cases\n' "$check_name" "$cases"
}

failures=0
cases=0

git_fixture init -q -b main
mkdir "$repo/checks"
printf 'exit 1\n' >"$repo/plain.sh"
printf 'exit 1\n' >"$repo/checks/nested.sh"
printf 'exit 1\n' >"$repo/executable.sh"
printf 'exit 1\n' >"$repo/deleted.sh"
chmod +x "$repo/executable.sh"
ln -s plain.sh "$repo/link.sh"
git_fixture add .
git_fixture commit -qm base
base=$(git_fixture rev-parse HEAD)
printf 'exit 1\n' >"$repo/later.sh"
git_fixture add later.sh
git_fixture commit -qm later
printf 'exit 1\n' >"$repo/worktree-only.sh"
rm "$repo/deleted.sh"
printf 'outside fixture\n' >"$work/x"
"$yak" --room "$room" init </dev/null

controls() {
    phase=$1
    accept "$phase: plain tracked file" false --file plain.sh
    accept "$phase: subdirectory file" false --file checks/nested.sh
    accept "$phase: executable tracked file" false --file executable.sh
    accept "$phase: base file deleted from working tree" false --file deleted.sh
    accept "$phase: command without --file" false
}

file_case() {
    label=$1
    bad_path=$2
    good_path=$3
    accept "before $label: tracked file" false --file "$good_path"
    refuse "$label" '' false --file "$bad_path"
    accept "after $label: tracked file" false --file "$good_path"
}

controls before
accept 'before empty command: nonempty command' false
refuse 'empty command' '' ''
accept 'after empty command: nonempty command' false
accept 'before spaces command: nonempty command' ' false '
refuse 'spaces-only command' '' '   '
accept 'after spaces command: nonempty command' ' false '

file_case 'path absent from base' missing.sh plain.sh
file_case 'directory at base' checks checks/nested.sh
file_case 'symbolic link at base' link.sh plain.sh
file_case 'untracked working file' worktree-only.sh plain.sh
file_case 'file tracked only after base' later.sh plain.sh
file_case 'parent path outside repository' ../x plain.sh
file_case 'absolute outside path' "$work/x" plain.sh
file_case 'inner parent path outside repository' checks/../../x checks/nested.sh

accept 'before bad first: two tracked files' false --file plain.sh --file checks/nested.sh
refuse 'bad first among check files' missing.sh false --file missing.sh --file checks/nested.sh
accept 'after bad first: two tracked files' false --file plain.sh --file checks/nested.sh
accept 'before bad middle: three tracked files' false --file plain.sh --file executable.sh --file checks/nested.sh
refuse 'bad middle among check files' missing.sh false --file plain.sh --file missing.sh --file checks/nested.sh
accept 'after bad middle: three tracked files' false --file plain.sh --file executable.sh --file checks/nested.sh
accept 'before bad last: two tracked files' false --file plain.sh --file checks/nested.sh
refuse 'bad last among check files' missing.sh false --file plain.sh --file missing.sh
accept 'after bad last: two tracked files' false --file plain.sh --file checks/nested.sh
controls after
finish
