# v2: a hand-in the room refuses is told beforehand and named afterwards

Serenity, 2026-11-19 (UTC). A small change to what every turn reads and to the pilots' runner and judges.
Revision 1, not yet read.

## Why

In the second pilot ("a line that says a plan may exist") one of 72 real turns lost its whole change. The
worker ran 120 seconds and 13 steps. The room, which commits for a Codex worker, then refused: "the work tree
must contain a single repository". It refuses when anything named `.git` lies below the top of the work tree
(`Sandbox::single_repository`, called once from `seal` in the turn crate). The room recorded the base's own
commit. None of the first pilot's 96 turns met this.

Two things were wrong around a rule that is itself right:

1. **No turn is told the rule.** What a worker reads at its start (`INTRO` in the turn crate's `worker.rs`)
   says to commit, or to leave a message file for the room to commit with. It says nothing of a second
   repository. A worker that clones the repository into a scratch folder to compare, or points a test run's
   temporary files inside the clone when some tests make repositories there, loses its change and never
   learns why.
2. **The runner's record hides it.** The pilots' runner names a turn by its commit: a turn that ends on its
   base's commit is "no-hand-in". A worker that changed nothing and a worker whose change the room refused
   get the same word, and the judge scores both as the parent. In the pilot this lowered one item's
   baseline; the report had to say so by hand. Only the clock's own line tells the two apart ("no new
   commit: the turn committed nothing" against "no new commit: refused: ...").

What made the second repository at that turn is not known; a walk holds paths and no command. This spec does
not depend on the cause.

## What does not change

- **The refusal.** The room's own git runs on the worker's tree when it commits for the worker. A nested
  repository, or a `.git` file that points elsewhere, is a way to steer that git. The rule stays as it is,
  with its tests.
- **The room's store and its exports.** Nothing is added to what the room keeps. (Whether a turn's record
  in the room should say why no commit was made is a larger change, left for a later spec.)
- **Rule 9.** No text from a transcript or a prompt is kept anywhere by this change. The sentence the
  runner copies is the room's own, from the clock's output.
- **Recorded pilots.** Their rows stay as recorded and their plans keep their pins. The second pilot's row
  056 stays "no-hand-in" in its record; its report says what happened.

## The change

### 1. What every turn reads

`INTRO` gains one sentence, after the sentence about the message file and before nothing else:

> Make no other git repository, clone or worktree inside this clone, and keep a test run's temporary files
> out of it: the room refuses a work tree that holds a second repository, and the turn's change is lost.
> The directory named by `TMPDIR` is yours for those.

It is one paragraph with the rest of `INTRO`, as plain text. Every worker kind gets it: the prompt is the
same for all. `prompt` with no offered block stays equal, byte for byte, to `prompt_with` with none.

This changes the room's program, so its hash: a plan made after it pins the new one, and a turn of an
earlier plan is refused by that plan's own check, as today.

### 2. The runner (`v2/probes/documents/documents_run.py`)

- A row's record gains `room_said`: for a turn that ended on its base's commit, the text after
  `no new commit: ` on the clock's line that says how the turn ended, to the end of that line; `null` when
  the turn handed in a commit of its own, or when the clock's output has no such text.
- `outcome` gains one value, `refused`: a turn that ended on its base's commit, was not stopped at its
  limit, and whose `room_said` begins with `refused:`. A turn stopped at its limit is `limit` as today,
  whatever the line says. Every other case is as today.
- The clock's line is read from the same captured output the runner already keeps beside the row
  (`clock.log`). Exactly one line that says the turn ended is expected; with none or more than one,
  `room_said` is `null` and the outcome is as today.

### 3. The judges (`documents_judge.py`, `documents_judge2.py`)

- `refused` is an outcome with no score, beside the others that have none. Its row is kept, is in the
  report's count of rows with no score by outcome, and is never read as the parent's score.
- Nothing else in a rule or a reading changes: where a spec's rule is suspended by a row with no score, a
  refused row suspends it. What a later trial does about such a row (run it again once, or leave its cell
  out) is for that trial's spec to say before its turns.

## Tests

- **The turn crate:** the prompt holds the new sentence once; `prompt` and `prompt_with(None)` are equal,
  byte for byte; with an offered block the sentence comes before the item's line as the rest of `INTRO`
  does. The existing tests of `single_repository` are untouched and pass.
- **The runner:** with a turn export that ends on the base and a clock output that says
  `no new commit: refused: the work tree must contain a single repository`, the outcome is `refused` and
  `room_said` is that text from `refused:` on; with `no new commit: the turn committed nothing` it is
  `no-hand-in` with `room_said` that sentence; stopped at its limit with a refusal line, `limit`; a
  handed-in commit, `room_said` is `null`; no line or two lines, `null` and the outcome as today.
- **On the real room, before any reader:** one row with a stand-in script worker that leaves a directory
  named `.git` in a subfolder of its work tree and commits nothing itself, where the room commits for
  the worker; if the room does not commit for a script worker, a row whose worker commits and then leaves
  the nested repository, to see what the room says there. The row's record must say what the room said.
  The builder runs this and says which of the two it could run.
- **The judges:** a `refused` row has no score; the first judge's report and the second's count it under
  rows with no score; in the second judge a refused part B row suspends the rule and names the row.
- Every condition added gets a mutant that a test kills.

## Checks before a push

- The Rust workspace's whole suite on both machines, since the turn crate changes.
- The five documents test files on this machine; the workflow runs them on Linux and macOS at the push.
- A fresh reader of the other family than the builder, on the diff and on this spec.

## What this narrows

- It does not find out what made the second repository in the pilot.
- It does not make the room say in its own record why a turn made no commit.
- It does not decide what a trial does with a refused row.
- A sentence is not a guard: a worker may still leave a repository. The refusal still catches it, and the
  record now says so.
