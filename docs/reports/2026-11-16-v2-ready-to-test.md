# v2: the path from walks to a prompt, shown working

Serenity, 2026-11-16. What "ready to test" asks is in section 7 of
`docs/superpowers/specs/2026-11-16-v2-a-route-offered.md`: the path shown working, deciding nothing. No
second of any turn below enters a sizing or a reading, and nothing here says whether a route helps.

## What ran

- **The room:** the `yak` program built from `v2` at c5af5ed3, taken out of that commit with its scripts
  (on macOS its SHA-256 begins fe7872d7).
- **The store:** its owner's program on the branch `tardis/v2-walks-and-routes`, at 8efa3130 for the six
  turns (the store's version 1), and afterwards at 8ce02f78 (version 2, after its reader's eight changes).
- **The history:** the first pilot's 21 stores, read only.
- **The second machine:** Linux on aarch64, with the room built from the same tree.

## The path on real walks, with no turn run

| Step | What came of it |
| --- | --- |
| `yak item walks` on each of the 21 stores | 21 walk files. Every one begins at step 0 |
| `yak history make`, then `yak history check` | A list of 21 turns, all passed and verified, on one base; admitted. With one walk changed: refused, `wrong_hash`. With an extra file: refused, `unlisted_file` |
| The store built from them | 21 turns, 16 paths, 50 roads, 39 detours; its own check replays 155 cells. The same at both of the store's commits. The lead's count from the stores, made earlier by other means: 16 files, 50 roads |

## The six live turns

Each of the first run's three items, once under each offering arm. An item's history is the arrived turns
at the other two. The room and the worker are as in the first pilot; the block is new.

| Turn | Item | Arm | Worker | Turns of history | Roads | The block | Outcome | Worker's seconds |
| --- | --- | --- | --- | --- | --- | --- | --- | --- |
| 1 | `item-add-wrong-commit` | route | `claude:opus` | 11 | 44 | 841 bytes | passed, verified | 97 |
| 2 | `item-add-wrong-commit` | shuffled | `claude:opus` | 11 | 44 | 418 bytes | passed, verified | 158 |
| 3 | `item-add-title` | route | `codex:gpt-6.1-sol` | 15 | 14 | 868 bytes | passed, verified | 56 |
| 4 | `item-add-title` | shuffled | `codex:gpt-6.1-sol` | 15 | 14 | 443 bytes | passed, verified | 45 |
| 5 | `item-add-check-freezable` | route | `claude:opus` | 16 | 43 | 951 bytes | passed, verified | 765 |
| 6 | `item-add-check-freezable` | shuffled | `claude:opus` | 16 | 43 | 445 bytes | passed, verified | 156 |

- **In every turn the room's record of the block is the block made beforehand.** Before each turn the
  block was rendered by `yak offer render` from the offer file, the arm and the seed. The SHA-256 and the
  length the room recorded for what it gave the worker are that block's, in all six. The record also holds
  the arm, the seed, the order, the list's hash, the ranker's, the store's and the kernel's versions, the
  measure, the chosen turns with their scores, and the goals.
- **Every offer had two goals,** from three chosen turns. None was empty.
- **Under the store's version 2 the six blocks are the same.** With no turn run, each turn's walks, list
  and question were put through the store at 8ce02f78 and the block made again: byte for byte the block
  that turn was given, six of six. The offer files differ only in the store's version.
- **Nothing is to be read from the seconds.** These are six single turns, at items that stand on a commit
  from before the test repair. They are here because every turn is reported.
- **One turn before these, also reported:** the same as turn 3, run earlier against a copy of the store in
  which the lead had relaxed one rule (below). Passed, verified; the same 868-byte block. The machine was
  asleep for most of that turn: 87 minutes passed for 357 seconds of the worker's time, and the turn's
  limit, which is counted on a clock that stops in sleep, did not end it.

## Two machines

- **The store gives the same bytes.** On the second machine, with the kernel compiled there and another
  version of Python: the fixture's answer byte for byte; the 21 real walks to the same counts; and for one
  question over them, one answer of 3,645 bytes with one SHA-256 on both machines.
- **So does the room.** From the same walks, list, goals and question, the second machine's answer, its
  offer file and its rendered block are each byte for byte the first's.
- **One live turn there with that block.** The room recorded giving it: 841 bytes, the same SHA-256 as
  turn 1's. **The room then failed the turn, and was wrong to.** Run by hand outside the jail, the turn's
  commit passes all 23 cases of its item's check. Inside the Linux jail the check cannot run. See below.

## What running found, that reading had not

1. **A step's number begins at 0.** The room numbers a turn's steps from 0 in every store there is. The
   store's spec said "positive", and both the room's export and the store, built to those words, refused
   every real walk. The one test that runs a real turn showed it for the room; the first real walks showed
   it for the store. Both are mended.
2. **A program of ours cannot start a child inside the Linux jail.** Before it starts another program, a
   program built with this toolchain makes a Unix socket pair of the seqpacket kind, and the Linux filter
   lets through only the stream kind. So `cargo` cannot build there, and the three old items cannot be
   judged there. Found with checks whose exit code says which step failed, and a stand-in worker. The mend
   is written as `docs/superpowers/specs/2026-11-16-v2-a-child-inside-the-linux-jail.md` and is not made.
3. **Freezing takes a check that cannot run for one that says no.** It asks that a check fail on the base
   and on the wrong commit, and a check that cannot run does both. Written down in that spec, not mended.
4. **A check of the kind the new items use does run inside the Linux jail:** Python that starts git and
   another Python, lists the paths that differ from a parent, makes the event loop, and uses files, a
   socket pair, a local socket and a thread. One stand-in turn, passed.

## What is not shown

- Whether a route shortens a turn. Nothing here bears on it.
- A check that builds Rust judged on Linux: it waits for the mend above.
- Anything on x86-64.
- A second read of the store after its eight changes. Its reader read 2d1a2dac; 8ce02f78 has had no reader.
- The new items. The six turns are at the three old ones.
