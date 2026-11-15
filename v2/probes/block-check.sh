#!/bin/sh
# Before a block of turns that will be compared: what a worker's program would load by itself is not there, and
# what must not change during the block is written down.
#
#   sh block-check.sh <block-dir> <yak binary>
#
# <block-dir> must exist. Prints one line for each place looked at, writes <block-dir>/versions.txt, and exits
# non-zero if an instruction file is where a program would load it. Run again at the block's end with the same
# words: it then says whether anything it wrote down has changed.
set -eu
BLOCK=$1
Y=$2
[ -d "$BLOCK" ] || { echo "refused: $BLOCK is not a directory"; exit 2; }
[ -x "$Y" ] || { echo "refused: $Y is not a program"; exit 2; }
found=0
look() { # a path: says whether something is there
    if [ -e "$1" ] || [ -L "$1" ]; then
        echo "THERE  $1"
        return 1
    fi
    echo "absent $1"
}
# The control: the same look finds a file that is there.
here=$(cd "$BLOCK" && pwd -P)
control="$here/.block-check-control"
: > "$control"
if look "$control" >/dev/null; then
    echo "refused: the look did not find a file that is there"
    exit 2
fi
unlink "$control"
echo "control: the look finds a file that is there"
# Each program's own home, as it is and as the environment names another.
for f in "$HOME/.claude/CLAUDE.md" "$HOME/.claude/rules" "$HOME/.codex/AGENTS.md" "$HOME/.codex/AGENTS.override.md"; do
    look "$f" || found=1
done
if [ -n "${CLAUDE_CONFIG_DIR:-}" ]; then
    for n in CLAUDE.md rules; do look "$CLAUDE_CONFIG_DIR/$n" || found=1; done
fi
if [ -n "${CODEX_HOME:-}" ]; then
    for n in AGENTS.md AGENTS.override.md; do look "$CODEX_HOME/$n" || found=1; done
fi
# One an organisation would put on the machine for every user: a program's settings cannot leave it out.
for f in "/Library/Application Support/ClaudeCode/CLAUDE.md" "/etc/claude-code/CLAUDE.md"; do
    look "$f" || found=1
done
# Every directory above the block, and the block's own.
d=$here
while :; do
    for n in CLAUDE.md CLAUDE.local.md AGENTS.md AGENTS.override.md .claude/CLAUDE.md .claude/AGENTS.md .claude/rules; do
        look "${d%/}/$n" || found=1
    done
    [ "$d" = / ] && break
    d=$(dirname "$d")
done
# What must not change during the block. Each is asked by itself, and one that ends badly or says nothing
# refuses the block: it is not written down as if it were a version.
: > "$here/versions.now"
ask() { # a name, then the command that says it
    name=$1
    shift
    if ! said=$("$@" 2>&1); then
        echo "refused: $name could not be asked ($*)"
        return 1
    fi
    first=$(printf '%s\n' "$said" | sed -n 1p)
    if [ -z "$first" ]; then
        echo "refused: $name said nothing ($*)"
        return 1
    fi
    printf '%s %s\n' "$name" "$first" >> "$here/versions.now"
}
hash_of() { # a file: its SHA-256 alone, by whichever of the two tools is here
    # The tool's own end is looked at, and what it printed must begin with a digest: 64 hex digits.
    if command -v sha256sum >/dev/null 2>&1; then
        summed=$(sha256sum "$1") || return 1
    else
        summed=$(shasum -a 256 "$1") || return 1
    fi
    digest=${summed%% *}
    case $digest in
    '' | *[!0-9a-f]*) return 1 ;;
    esac
    [ "${#digest}" -eq 64 ] || return 1
    printf '%s\n' "$digest"
}
asked=0
ask claude claude --version || asked=1
ask codex codex --version || asked=1
ask git git --version || asked=1
ask yak hash_of "$Y" || asked=1
ask machine uname -srm || asked=1
if [ "$asked" != 0 ]; then
    unlink "$here/versions.now"
    echo "REFUSED: what must not change could not be written down"
    exit 1
fi
if [ -e "$here/versions.txt" ]; then
    if cmp -s "$here/versions.txt" "$here/versions.now"; then
        echo "versions: as at the block's start"
    else
        echo "versions: CHANGED since the block's start"
        diff "$here/versions.txt" "$here/versions.now" || true
        found=1
    fi
    unlink "$here/versions.now"
else
    mv "$here/versions.now" "$here/versions.txt"
    echo "versions: written"
    cat "$here/versions.txt"
fi
[ "$found" = 0 ] || { echo "REFUSED: see the lines that say THERE or CHANGED"; exit 1; }
echo "ok"
