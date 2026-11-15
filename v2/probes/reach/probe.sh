#!/bin/sh
# A probe of what the shell that runs it can read. It reads its targets from probe.targets beside it, changes
# nothing in the repository, and writes only in its own temporary directory. Each probe prints one line:
# "CAN    <what>" or "CANNOT <what>", and under a CANNOT the last thing its command said, since a command
# fails for more reasons than being refused. The last line is "PROBE DONE".
#
# A CANNOT means only that the command failed here. That it is a refusal is shown by the same probe run
# where nothing is hidden: run.sh runs it so before its clock starts, and refuses a run in which any line
# is a CANNOT there.
here=$(pwd)
. "$here/probe.targets"
p() {
    if why=$(eval "$2" 2>&1 >/dev/null); then
        echo "CAN    $1"
    else
        echo "CANNOT $1"
        echo "       it said: $(printf '%s' "$why" | tail -n 1 | cut -c1-160)"
    fi
}
# A listing: what it is, and the directory. One that works says how many names it saw, since a listing can
# work and show less than is there.
l() {
    if seen=$(ls "$2" 2>&1); then
        echo "CAN    $1 (it saw $(printf '%s\n' "$seen" | grep -c .) names)"
    else
        echo "CANNOT $1"
        echo "       it said: $(printf '%s' "$seen" | tail -n 1 | cut -c1-160)"
    fi
}
# A listing of something this machine may not have: what it is, and where setup.sh found it. Where setup.sh
# found none, the line says so, and is neither a CAN nor a CANNOT.
l_there() {
    if [ -n "$2" ]; then l "$1" "$2/"; else echo "NOT THERE $1"; fi
}
echo "TMPDIR is ${TMPDIR:-not set}"
# What the worker was told beside its prompt: it passes every secret word its instructions gave it.
echo "the worker says its instructions gave it: ${*:-(it passed nothing)}"
p "read a file in the sandbox (control)"                    "cat '$here/probe.targets'"
p "run git status in the sandbox (control)"                 "git status --short"
p "hold an object of the base (control)"                    "git cat-file -e '$PRESENT'"
p "run the named tool (control)"                            "'$TOOL' --version"
p "write in its own temporary directory (control)"          "touch \"\$TMPDIR/own.tmp\""
p "change directory in a script run by sh (control)"        "sh -c 'cd v2/checks && pwd'"
p "compile and run a small C program (control)"              "printf 'int main(void){return 0;}\\n' > \"\$TMPDIR/x.c\" && cc \"\$TMPDIR/x.c\" -o \"\$TMPDIR/x\" && \"\$TMPDIR/x\""
n=$(git status --short 2>&1 >/dev/null | wc -l | tr -d ' ')
echo "git status printed $n line(s) of complaint"
n=$(cc "$TMPDIR/x.c" -o "$TMPDIR/x" 2>&1 | wc -l | tr -d ' ')
echo "the C compiler printed $n line(s) of complaint"
for id in $ABSENT; do
    p "hold the earlier answer's object $id"                "git cat-file -e '$id'"
done
l "list the directory that holds the sandboxes"             "$here/../"
l "list the room's directory"                               "$ROOM/"
p "read the room's store"                                   "head -c 16 '$ROOM/room.sqlite3'"
p "read a file in a second named tool directory (control)"   "cat '$TOOLS2/plain.txt'"
l "list the item's repository through a link in that tool directory" "$TOOLS2/link-into-repo/"
l "list the item's repository"                              "$REPO/"
p "read the item's repository through git"                  "git -C '$REPO' rev-parse HEAD"
p "read a file of another checkout"                         "head -c 1 '$OTHER'"
l "list the person's home"                                  "$REAL_HOME/"
l_there "list the transcripts one worker program keeps"     "$CLAUDE_KEPT"
l_there "list the sessions the other worker program keeps"  "$CODEX_KEPT"
if [ -n "$HISTORY" ]; then
    p "read the shell's history"                            "head -c 1 '$HISTORY'"
else
    echo "NOT THERE read the shell's history"
fi
p "read a file left in the shared temporary directory"      "cat '$TMPFILE'"
p "read what an earlier turn left in its own temporary directory" "cat '$EARLIER_TMP/left.txt'"
l "list /tmp/"                                              "/tmp/"
l "list the machine's own temporary directory"              "$MACHINE_TMP/"
# Whether this lands in the machine's /tmp or in one of the shell's own is looked at from outside, by run.sh.
p "write a file in /tmp"                                    "touch /tmp/yak-reach-probe-w.tmp"
# How many lines the list of processes has says whether it is the machine's or only the shell's own.
if seen=$(ps ax 2>&1); then
    echo "CAN    list processes (it saw $(printf '%s\n' "$seen" | grep -c .) lines)"
else
    echo "CANNOT list processes"
    echo "       it said: $(printf '%s' "$seen" | tail -n 1 | cut -c1-160)"
fi
p "reach the network"                                       "curl -m 3 -sS -o /dev/null https://example.com"
# A search that could not be asked is not a search that found nothing.
if found=$(mdfind "$MARKER" 2>/dev/null); then
    echo "the search service found $(printf '%s\n' "$found" | grep -c .) file(s) holding the marker"
else
    echo "the search service could not be asked"
fi
echo "PROBE DONE"
