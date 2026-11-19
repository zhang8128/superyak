# v2: a hand-in the room refuses is told beforehand and named afterwards

Serenity, 2026-11-19 (UTC). A small change to what every turn reads and to the pilots' runner and judges.
Revision 3. Revision 1 was read by a fresh reader of the other family (w130): approve with named changes,
seven, made in revision 2 as named. The build of revision 2 was read by another (w133): join with named
changes, four. Three are in the code; where they touch this spec's words, and for the fourth, this revision
changes them. The last two sections list both sets.

## Why

In the second pilot ("a line that says a plan may exist") one of 72 real turns lost its whole change. The
worker ran 120 seconds and 13 steps. The room, which commits for a Codex worker, then refused: "the work tree
must contain a single repository". It recorded the base's own commit. None of the first pilot's 96 turns met
this.

Two things were wrong around a rule that is itself right:

1. **No turn is told the rule.** What a worker reads at its start (`INTRO` in the turn crate's `worker.rs`)
   says to commit, or to leave a message file for the room to commit with. It says nothing of a second
   repository.
2. **The runner's record hides it.** The pilots' runner names a turn by its commit: a turn that ends on its
   base's commit is "no-hand-in". A worker that changed nothing and a worker whose change the room refused
   get the same word, and the judge scores both as the parent. Only the clock's own line tells the two apart
   ("no new commit: the turn committed nothing" against "no new commit: refused: ...").

What made the second repository at that turn is not known; a walk holds paths and no command. This spec does
not depend on the cause, and it does not claim that its sentence would have prevented that refusal.

## What the room does today, as read in the code

- **Who is sealed.** A Claude worker and a Codex worker both end in `seal`: the room's own git commits what
  the worker left uncommitted. A script worker is not sealed; it commits for itself or hands in nothing.
- **What `seal` refuses.** `single_repository` refuses when any entry named `.git`, in any letter case and
  of any kind, lies below the top of the work tree, and when the index holds a gitlink; the index is checked
  again after staging. It does not follow a directory that is a symbolic link.
- **What a refusal costs.** It guards the room's own staging and commit. If the worker had committed
  nothing, the turn hands in its base and the uncommitted change is lost. If a model worker had already
  committed for itself, the refusal is reported as a problem and the worker's commit is still brought and
  judged. A script that commits and leaves a nested repository meets no such check.
- **Where the reason is.** The clock's line for the turn's end holds it ("; no new commit: {why}"). The
  room's export of a turn does not: neither its state, its exit code nor its seal time tells a refusal from
  an ordinary base hand-in.
- **Whose words the reason is.** Mostly the room's. Not wholly: a refusal about the clone can repeat a file
  name the worker chose, and git's own complaints can hold a worker's text. The clock's command line removes
  control characters, so such text cannot start a new line, but its words remain.

## What does not change

- **The refusal,** with its tests. This spec's promise is narrower than "a second repository is always
  caught": the room refuses to commit uncommitted work from a tree that holds one.
- **The room's store and its exports.** Nothing is added to what the room keeps. Whether a turn's record in
  the room should say why no commit was made is a larger change, left for a later spec.
- **Rule 9.** The new field in a row's record holds one of a fixed list of the room's own reasons and
  nothing a worker could choose. The clock's captured output stays beside the row as today; it is not called
  wholly the room's.
- **Recorded pilots.** Their rows stay as recorded, their scores stand, and their plans keep their pins.
  The second pilot's row 056 stays "no-hand-in" in its record; its report says what happened.

## The change

### 1. What every turn reads

`INTRO` gains two sentences at its end, in the same paragraph:

> Keep any extra repository, clone or worktree, including one made by tests, outside this clone; use TMPDIR
> for scratch work. When the room commits for you, it refuses nested .git entries or submodule entries in
> the index, and uncommitted changes are lost.

Every worker kind gets the same prompt. `prompt` with no offered block stays equal, byte for byte, to
`prompt_with` with none. A model worker's `TMPDIR` is its own directory under `/tmp`; a jailed script's is a
scratch directory beside the clone; with the jail off a script inherits `TMPDIR`. The sentence is true of
all three as worded: it asks only that extra repositories be kept out of the clone.

This changes the room's program, so its hash: a plan made after it pins the new one.

### 2. The runner and the judges name the turn's end the same way

One function, in one place both use, takes the export of a turn, the row's item, and the clock's captured
output for that turn, and returns the outcome and a field `no_commit`.

- **The clock's line.** An ended event is a line of the form the clock writes for a turn's end: the
  runner's time stamp, `ended`, the item, the lease number, the item's state in the room's own words,
  `commit` and forty hexadecimal characters, then optionally `; timed out`, optionally `; no new commit: `
  and a reason, and optionally `; rechecked: ` and a state. A state is one of the nine the room writes; any
  other words there make the line no ended event. The recheck is the room's last words, so a reason is read
  without it. A lease number above the room's 32-bit count is not the room's and matches no event. Only an ended event whose item is
  the row's item (`item.txt`) and whose lease and commit are the exported turn's is this turn's. Other
  lines, and ended events of another item, lease or commit, are not evidence. With no such event, or more
  than one, `no_commit` is `null` and the outcome is as today.
- **`no_commit`** is `null` when the turn handed in a commit of its own, and otherwise one of:
  - `committed nothing`: the reason is exactly "the turn committed nothing";
  - `refused: single repository`: the reason begins "refused: the work tree must contain a single
    repository";
  - `refused: gitlinks`: it begins "refused: the index must contain no gitlinks";
  - `refused: other`: it begins "refused:" and is neither of those;
  - `other`: any other reason.
  The reason's own text is never copied into the record.
- **The outcome,** in this order:
  1. an export that failed or is not one well-formed turn: `export-failed` or `clock-failed` as today,
     whatever the clock's output says;
  2. a commit of the turn's own: `handed-in`, with `at_limit` true when the export's measured end is
     `timed_out`, and `no_commit` `null`;
  3. the base's commit and the export's measured end `timed_out`: `limit`, whatever the reason;
  4. the base's commit and `no_commit` beginning `refused`: **`refused`**, the new outcome;
  5. the base's commit otherwise: `no-hand-in` as today.
  The export's measured end is used and not the clock's own flag, since a seal that fails can leave that
  flag false when the worker did run out of time. A nonzero exit of the clock alone is not a failure, as
  today.
- **Export recovery.** Where the judge recovers a row whose export had failed, by exporting again, it uses
  the same function with the row's original captured clock output. A recovered export that ends on the base
  with a refusal line is `refused`, not `no-hand-in`.
- **A record made before this change** has no `no_commit`; it is read as `null` and its outcome stands.

### 3. A refused row has no score: a new rule for plans pinned after this change

The first pilot's spec, section 6, scores a turn with no hand-in as its parent. That stays true of a worker
that committed nothing. A refused hand-in is different: the worker changed something and what it changed
cannot be assessed. It is not evidence that the lost change would have passed, and it is a real failure to
deliver. **For plans pinned after this change, `refused` is an outcome with no score.** This is a new
policy, stated here as an exception to that section, and it does not reach back.

What follows from the judges as they are, with no change to their arithmetic:

- `refused` joins the outcomes and the outcomes with no score in the first judge, and is handled before the
  branch that scores a row with no commit as its parent.
- In the first judge, a refused Nothing row leaves its item with no baseline, and a refused row the rule
  needs suspends the rule.
- In the second judge, a refused part B row leaves its item with no difference and suspends the rule,
  naming the row; a refused part A row suspends nothing.
- The readings on all frozen cases and on the cases that do not pass on the parent both leave the refused
  row's score out and keep their denominators.
- In the second judge the row's seconds, tokens, steps and walk counts stay in the counts beside the rule:
  they describe work that was done. The first judge's report gives no costs and no walk counts for a row
  with no score, a refused one included; the row's own files keep them.
- Both reports count refused rows by name among the rows with no score.

What a later trial does about such a row (run it again once, or leave its cell out) is for that trial's
spec to say before its turns.

## Tests

- **The turn crate:** the prompt holds each new sentence once; `prompt` and `prompt_with(None)` are equal,
  byte for byte; with an offered block the sentences come with the rest of `INTRO`, before the item's line.
  The existing tests of `single_repository` are untouched and pass under the repository's whole-suite
  script, which runs the tests a plain `cargo test` leaves out.
- **The naming function:**
  - the base's commit with a matched ended event saying the single-repository refusal: `refused`,
    `no_commit` "refused: single repository";
  - "the turn committed nothing": `no-hand-in`, "committed nothing";
  - a refusal whose text holds words a worker could choose: `refused`, "refused: other", and no word of
    that text in the record;
  - any other reason: `no-hand-in`, "other";
  - the base's commit, measured end `timed_out`, a refusal line: `limit`;
  - a commit of the turn's own at its limit: `handed-in`, `at_limit` true, `no_commit` `null`;
  - a real line with its time stamp, matched on item, lease and commit, for each of the room's nine states
    as the verdict;
  - a recheck after a refusal, after "the turn committed nothing", and with no reason; words after a reason
    that are no recheck in the room's states stay part of the reason;
  - a lease at the room's largest count, one above it, and one too large to write as text;
  - an ended event of another item, another lease or another commit, and unrelated lines that hold
    "no new commit": not evidence, so `null` and the outcome as today;
  - no ended event, and two: `null` and the outcome as today;
  - a failed or malformed export beside a refusal-looking log: `export-failed` or `clock-failed`;
  - a record with no `no_commit`: read as `null`.
- **Export recovery:** a row whose export failed at first and is recovered to the base, with a refusal line
  in its captured clock output: `refused`, with no score.
- **The judges:** a `refused` row has no score in either; the first judge's rule is suspended by one it
  needs and its item has no baseline; the second judge's rule is suspended by a part B one and not by a part
  A one; both readings leave its score out and keep their denominators; its costs and walk counts are in the
  second judge's report; both reports count it by name.
- **On the real room, with no model, before any reader:**
  - a script put in the place of a Codex worker's program, so that `seal` runs: it changes a file under the
    source directory, commits nothing, and leaves a directory named `.git` in a subfolder. Asked for its
    version, as the maker asks a worker's program in its own working directory, it prints one line and
    changes nothing; a test holds that. Expected: the
    room refuses; the row's record says `refused` and "refused: single repository";
  - beside it, as a description of what is and not as a guard: a script worker that commits its change and
    leaves the same nested directory. Expected: `handed-in`, `no_commit` `null`.
  The builder runs both and reports what the room said.
- Every condition added gets a mutant that a test kills.

## Checks before a push

- The repository's whole-suite script for the Rust workspace on both machines, since the turn crate changes.
- The five documents test files on this machine; the workflow runs them on Linux and macOS at the push.
- A fresh reader of the other family than the builder, on the diff and on this spec.

## What this narrows

- It does not find out what made the second repository in the pilot, and does not show that the new
  sentences would have prevented it.
- It does not make the room say in its own record why a turn made no commit.
- It does not decide what a trial does with a refused row.
- It does not guard a worker that commits for itself and leaves a repository behind.

## The first reader's named changes, and where each is made

1. Failure text is not wholly the room's: the record keeps one of a fixed list of reasons and never the
   text ("Whose words the reason is"; `no_commit`).
2. The classification is carried through export recovery, with `refused` in the first judge's outcomes and
   handled before the parent-score branch ("Export recovery"; section 3).
3. The promise is narrowed to refusing to commit uncommitted work; the real-room test puts a script in a
   Codex worker's place so that `seal` runs, and the self-committing case is described separately.
4. The log's boundary and the order of outcomes are specified ("The clock's line"; "The outcome").
5. The sentence for `INTRO` is the reader's narrower one.
6. No score for a refused row is named as a new policy and an exception to the first pilot's section 6,
   with what follows in each judge.
7. The test list is completed, the whole-suite script is named, and the either-or test and the
   unconditional claim are cut.

## The build's reader's named changes, and where each is made

1. The stand-in for the Codex program answers a version question and changes nothing (the stand-in; a test
   in the runner's tests that also shows it would otherwise have changed the directory).
2. The whole grammar of an ended line is parsed, the recheck with it, and a verdict must be one of the room's
   states ("The clock's line"; the naming function's tests).
3. The costs and walk counts of a refused row are promised for the second judge's report only (section 3;
   "Tests").
4. A lease number above the room's count matches no event and is never turned into text.

Run on the real room with no model, from the build as read: the stand-in in the Codex program's place was
refused by the room with the single-repository sentence, its record says `refused` and "refused: single
repository", and it has no score; the script worker that commits for itself was taken, `handed-in` with
`no_commit` null. Both rows ran on the room program the pilot's controls were made with, so the two new
sentences were not in what those turns read; the turn crate's tests hold them.
