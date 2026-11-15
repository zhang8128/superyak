#!/bin/sh
# Frozen check for the item:
#   "yak item add refuses a title that is empty, more than one line, or longer than 200 characters"
#
# HOW IT IS RUN: sh v2/checks/item-add-title.sh <vendor-dir>
# at the root of a clone of the candidate commit. <vendor-dir> is the absolute path of the vendored crates.
#
# HOW IT BUILDS: cd v2 && cargo build -q -p yak --offline --locked, with two --config words that replace
# crates-io by the directory <vendor-dir>, and CARGO_HOME set to v2/target/cargo-home (git ignores v2/target).
# Then, under $TMPDIR, it makes a throwaway git repository with one commit and a room (`yak --room <room>
# init`), runs v2/target/debug/yak --room <room> item add ... once per case below, and removes what it made.
#
# Every `item add` gives a valid --repo (that repository), --base (its one commit), --check true,
# --origin outside and --by person:check, with stdin closed. Only --title changes from case to case.
#
# ACCEPTED means all of: exit 0; stdout is exactly one line, and that line is the id of the one item that
#   `yak item list` gained (the list's item ids before and after are compared).
# REFUSED means all of: a non-zero exit; nothing at all on stdout; exactly one line on stderr, not blank;
#   and `yak item list` shows the same item ids before and after. The words of the refusal are not checked.
#
# The cases, in the order they are tried (\t is a tab, \r a carriage return, \n a line feed):
#    1  "Make the answer green"                                   ACCEPTED  (an ordinary title)
#    2  ""  (empty)                                               REFUSED
#    3  "a"  (one letter)                                         ACCEPTED  (the nearest fine title to 2)
#    4  "   "  (three spaces only)                                REFUSED
#    5  "\t\t"  (two tabs only)                                   REFUSED
#    6  "a b"  (a space between two letters)                      ACCEPTED  (the nearest fine title to 4 and 5)
#    7  "first\nsecond"                                           REFUSED
#    8  "first\r\nsecond"                                         REFUSED
#    9  "first second"                                            ACCEPTED  (the nearest fine title to 7 and 8)
#   10  200 ASCII letters "a" (200 bytes)                         ACCEPTED  (exactly at the limit)
#   11  201 ASCII letters "a" (201 bytes)                         REFUSED
#   12  202 ASCII letters "a" (202 bytes)                         REFUSED   (past the limit by more than one)
#   13  200 two-byte letters U+00E9 "e acute" (400 bytes)         ACCEPTED  (the limit is in characters, not bytes)
#   14  201 two-byte letters U+00E9 "e acute" (402 bytes)         REFUSED
#   15  200 four-byte letters U+1F600 (800 bytes)                 ACCEPTED  (one character each, not two)
#   16  "Make the answer green again"                             ACCEPTED  (an ordinary title, after the refusals)
# The script itself stays ASCII: the longer letters are made with printf and octal escapes, and the script
# checks the byte length of each long title it made before it uses it.
#
# NOT TRIED, EITHER WAY (any behaviour passes): a title that only ends in a line break; spaces or tabs around
# a real title; whether the stored title is trimmed; a lone carriage return or any other line or paragraph
# separator; any other kind of white space; a letter made of more than one code point.
#
# OUTPUT: one line per case on stdout, "ok N ..." or "FAIL N ...: what was seen"; then one summary line.
# Exit 0 only if every case held. A build or setup failure says so and exits non-zero.

set -u
LC_ALL=C
export LC_ALL

# Prints its words and a line feed, as they are: an sh's echo may turn a backslash and a letter into a control
# character, and what this script prints holds escapes and whatever yak said.
say() {
    printf '%s\n' "$*"
}

vendor=${1:-}
if [ -z "$vendor" ] || [ ! -d "$vendor" ]; then
    say "FAIL setup: give the vendored crates' directory as the first argument (got '$vendor')"
    exit 2
fi
case $vendor in
    *'"'* | *'\'*)
        say "FAIL setup: the vendored crates' path holds a quote or a backslash: $vendor"
        exit 2
        ;;
esac
if [ ! -f v2/Cargo.toml ]; then
    say "FAIL setup: run this at the root of the repository (no v2/Cargo.toml in $(pwd))"
    exit 2
fi
if [ -z "${TMPDIR:-}" ] || [ ! -d "$TMPDIR" ]; then
    say "FAIL setup: TMPDIR must name a directory"
    exit 2
fi

root=$(pwd)
yak="$root/v2/target/debug/yak"

# --- Build yak from this clone, offline. ---
CARGO_HOME="$root/v2/target/cargo-home"
export CARGO_HOME
unset CARGO_TARGET_DIR
say "building yak from $root/v2"
if ! (cd v2 && cargo build -q -p yak --offline --locked \
    --config 'source.crates-io.replace-with="vendored"' \
    --config "source.vendored.directory=\"$vendor\"" 2>&1); then
    say "FAIL build: cargo build -p yak failed (its output is above)"
    exit 1
fi
if [ ! -x "$yak" ]; then
    say "FAIL build: no $yak after the build"
    exit 1
fi

# --- A throwaway repository and room under TMPDIR, removed at exit. ---
work=''
cleanup() {
    if [ -n "$work" ]; then
        rm -rf "$work"
    fi
}
trap cleanup EXIT
trap 'exit 129' HUP
trap 'exit 130' INT
trap 'exit 143' TERM
work=$(mktemp -d "${TMPDIR%/}/item-add-title.XXXXXX") || {
    say "FAIL setup: mktemp -d under $TMPDIR failed"
    exit 2
}
repo="$work/repo"
room="$work/room"

# No machine or personal git settings: the jail shows none, and the check must not depend on them.
GIT_CONFIG_NOSYSTEM=1
GIT_ATTR_NOSYSTEM=1
GIT_CONFIG_GLOBAL=/dev/null
GIT_TERMINAL_PROMPT=0
GIT_AUTHOR_NAME=check
GIT_AUTHOR_EMAIL=check@example.invalid
GIT_COMMITTER_NAME=check
GIT_COMMITTER_EMAIL=check@example.invalid
export GIT_CONFIG_NOSYSTEM GIT_ATTR_NOSYSTEM GIT_CONFIG_GLOBAL GIT_TERMINAL_PROMPT
export GIT_AUTHOR_NAME GIT_AUTHOR_EMAIL GIT_COMMITTER_NAME GIT_COMMITTER_EMAIL

setup_failed() {
    say "FAIL setup: $1"
    if [ -s "$work/setup.err" ]; then
        say "  it said: $(tr '\n' ' ' <"$work/setup.err" | cut -b 1-400)"
    fi
    exit 2
}

git -c init.defaultBranch=main init -q "$repo" </dev/null >"$work/setup.err" 2>&1 ||
    setup_failed "git init of the throwaway repository failed"
printf 'answer\n' >"$repo/answer.txt"
git -C "$repo" add answer.txt </dev/null >"$work/setup.err" 2>&1 ||
    setup_failed "git add in the throwaway repository failed"
git -C "$repo" commit -q -m 'the base' </dev/null >"$work/setup.err" 2>&1 ||
    setup_failed "git commit in the throwaway repository failed"
base=$(git -C "$repo" rev-parse HEAD 2>"$work/setup.err") ||
    setup_failed "git rev-parse HEAD in the throwaway repository failed"
"$yak" --room "$room" init </dev/null >"$work/setup.err" 2>&1 ||
    setup_failed "yak --room $room init failed"

# --- The titles. ---
nl='
'
cr=$(printf '\r')
tab=$(printf '\t')
e_acute=$(printf '\303\251')
four_byte=$(printf '\360\237\230\200')

repeat() { # $1 repeated $2 times, on stdout
    r=''
    i=0
    while [ "$i" -lt "$2" ]; do
        r="$r$1"
        i=$((i + 1))
    done
    printf '%s' "$r"
}

a200=$(repeat a 200)
a201="${a200}a"
a202="${a201}a"
e200=$(repeat "$e_acute" 200)
e201="$e200$e_acute"
g200=$(repeat "$four_byte" 200)

bytes() { # the byte length of $1
    say $(($(printf '%s' "$1" | wc -c)))
}

for want in "a200 200" "a201 201" "a202 202" "e200 400" "e201 402" "g200 800"; do
    name=${want% *}
    size=${want#* }
    eval "value=\$$name"
    got=$(bytes "$value")
    if [ "$got" -ne "$size" ]; then
        say "FAIL setup: the title $name has $got bytes, not $size: this shell did not build it as meant"
        exit 2
    fi
done

# --- Running a case. ---
n=0
failed=0
failed_list=''

# One printable line for a file's bytes: tabs as \t, carriage returns as \r, line feeds as \n, cut short.
seen() {
    sed "s/$tab/\\\\t/g; s/$cr/\\\\r/g" "$1" |
        awk 'BEGIN { ORS = "" } NR > 1 { print "\\n" } { print }' |
        cut -b 1-240
}

# The number of lines in a file, a last line without a line feed included.
lines_in() {
    awk 'END { print NR }' "$1"
}

# The item ids `yak item list` shows, sorted, into the file $1. Fails if `yak item list` fails.
list_ids() {
    "$yak" --room "$room" item list </dev/null >"$work/list.out" 2>"$work/list.err" || return 1
    sed -n 's/^[[:space:]]*"id":[[:space:]]*"\([^"]*\)".*$/\1/p' "$work/list.out" | sort >"$1"
}

add_title() { # runs `yak item add` with the title $1; sets $code
    "$yak" --room "$room" item add --title "$1" --repo "$repo" --base "$base" \
        --check true --origin outside --by person:check \
        </dev/null >"$work/out" 2>"$work/err"
    code=$?
}

held() {
    say "ok $n $1"
}

broke() {
    say "FAIL $n $1"
    failed=$((failed + 1))
    failed_list="$failed_list $n"
}

# A case whose title must be refused. $1 names the case, $2 is the title.
refused() {
    n=$((n + 1))
    if ! list_ids "$work/before"; then
        broke "$1: yak item list failed before the case: $(seen "$work/list.err")"
        return
    fi
    add_title "$2"
    if ! list_ids "$work/after"; then
        broke "$1: yak item list failed after the case: $(seen "$work/list.err")"
        return
    fi
    why=''
    if [ "$code" -eq 0 ]; then
        why="$why; exit 0, wanted a non-zero exit"
    fi
    if [ -s "$work/out" ]; then
        why="$why; stdout should be empty and holds: $(seen "$work/out")"
    fi
    errlines=$(lines_in "$work/err")
    if [ "$errlines" -ne 1 ]; then
        why="$why; stderr should be exactly one line and has $errlines: $(seen "$work/err")"
    elif ! grep -q '[^[:space:]]' "$work/err"; then
        why="$why; stderr is one blank line"
    fi
    if ! cmp -s "$work/before" "$work/after"; then
        added=$(comm -13 "$work/before" "$work/after" | tr '\n' ' ')
        gone=$(comm -23 "$work/before" "$work/after" | tr '\n' ' ')
        why="$why; the item list changed (added: ${added:-none}; gone: ${gone:-none})"
    fi
    if [ -n "$why" ]; then
        broke "$1: wanted a refusal${why}"
    else
        held "$1: refused (exit $code): $(seen "$work/err")"
    fi
}

# A case whose title must be accepted. $1 names the case, $2 is the title.
accepted() {
    n=$((n + 1))
    if ! list_ids "$work/before"; then
        broke "$1: yak item list failed before the case: $(seen "$work/list.err")"
        return
    fi
    add_title "$2"
    if ! list_ids "$work/after"; then
        broke "$1: yak item list failed after the case: $(seen "$work/list.err")"
        return
    fi
    why=''
    if [ "$code" -ne 0 ]; then
        why="$why; exit $code, wanted 0; stderr: $(seen "$work/err")"
    fi
    outlines=$(lines_in "$work/out")
    id=$(cat "$work/out")
    added=$(comm -13 "$work/before" "$work/after")
    gone=$(comm -23 "$work/before" "$work/after")
    if [ "$outlines" -ne 1 ]; then
        why="$why; stdout should be one line, the new item's id, and has $outlines: $(seen "$work/out")"
    fi
    if [ -n "$gone" ]; then
        why="$why; items left the list: $(printf '%s' "$gone" | tr '\n' ' ')"
    fi
    if [ -z "$added" ]; then
        why="$why; no item was added to the list"
    elif [ "$added" != "$id" ]; then
        why="$why; the list gained $(printf '%s' "$added" | tr '\n' ' ')but stdout says: $(seen "$work/out")"
    fi
    if [ -n "$why" ]; then
        broke "$1: wanted it accepted${why}"
    else
        held "$1: accepted as $id"
    fi
}

# --- The cases (see the list at the top). ---
accepted "an ordinary title" "Make the answer green"
refused "an empty title" ""
accepted "a title of one letter" "a"
refused "a title of three spaces only" "   "
refused "a title of two tabs only" "$tab$tab"
accepted "a title with a space between two letters" "a b"
refused "a line feed between two words" "first${nl}second"
refused "a carriage return and line feed between two words" "first${cr}${nl}second"
accepted "the same two words with a space between" "first second"
accepted "200 ASCII letters" "$a200"
refused "201 ASCII letters" "$a201"
refused "202 ASCII letters" "$a202"
accepted "200 two-byte letters (400 bytes)" "$e200"
refused "201 two-byte letters (402 bytes)" "$e201"
accepted "200 four-byte letters (800 bytes)" "$g200"
accepted "another ordinary title, after the refusals" "Make the answer green again"

if [ "$failed" -eq 0 ]; then
    say "PASS: all $n cases held"
    exit 0
fi
say "FAIL: $failed of $n cases did not hold: case(s)$failed_list"
exit 1
