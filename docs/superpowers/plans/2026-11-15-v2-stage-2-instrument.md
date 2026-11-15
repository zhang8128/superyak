# v2 Stage 2, Part 0: The Instrument: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make a turn's record hold what the stage 2 experiment has to compare: its whole cost in tokens and in
active seconds, every tracked file it named and changed, and a clone that holds no other turn's answer.

**Architecture:** The `room` crate's store moves to version 2 with four new tables and brings a version-1 store
forward. The `turn` crate's parsers read each program's closing total and every file a command names, and a
sandbox is made from what its base reaches and nothing else. The clock measures each phase of a turn on a
monotonic clock and writes one measured record for every way a turn can end.

**Tech Stack:** Rust 1.100.0, edition 2024, `rusqlite`, `serde_json`, git as a subprocess. No new dependency.

**Spec:** `docs/superpowers/specs/2026-11-15-v2-stage-2-experiment.md`, part 0. It answers to
`docs/superpowers/specs/2026-11-14-superyak-v2-design.md`. Read both.

**This plan covers what the pilot (part 1) needs.** The offer (the ranker, the renderer and its record) is a
second plan, written after the pilot. It is not needed for a turn that is offered nothing.

## Global Constraints

Everything in the Global Constraints of `docs/superpowers/plans/2026-11-14-v2-stage-1-room.md` still holds.
In particular:

- The repository is public. No private name, research detail, prompt text or transcript text in any tracked file.
- No `unsafe`. No new crate. Builds and passes on macOS arm64, Linux aarch64 and Linux x86_64.
- **Rule 9.** The store holds no text from a transcript or a prompt: names of tracked files at a commit, numbers
  and verdicts. Every new TEXT column holds a path, a hex id or a fixed word from an enum, and a test says so.
- Tests hold with the jail on. A builder's sandbox cannot enter a jail or inspect processes, so the lead runs
  the whole suite on the host. Say plainly in your report which tests you could not run and why.
- **A test that starts something with no end of its own owns a stop** that acts on every path (see
  `StopsWithin` in `crates/yak/tests/common/mod.rs`). Tests wait for an event, not for a timer.
- Mutate every guard you add: for each new condition, show one test that fails without it, and name it.

## Review Focus

The inputs the spec implies and no task's happy path exercises, most likely first. Each has a test in the task
that owns the code.

1. **A turn that is killed at its limit.** Its program gives no closing total. Expected: a measured record with
   `tokens.complete == false`, whole durations, and its steps kept. (Tasks 3 and 5.)
2. **A worker whose run returns an error** (the room's commit on its behalf fails, the clone was replaced).
   Expected: the steps seen so far and a measured record are still written. Today both are lost. (Tasks 3, 5.)
3. **A tracked file whose name has a space or a non-ASCII letter.** Expected: that one name is counted as
   unknown and the rest of the walk is kept. Today the store refuses the whole walk. (Task 2.)
4. **A store made by the stage 1 program.** Expected: opening it for writing brings it forward to version 2
   with its rows intact; opening it read-only says how. Today it is refused as damaged. (Task 1.)
5. **An object in the item's repository that the base does not reach** (another turn's commit, a dangling
   blob, another branch). Expected: absent from the sandbox, beside a control object that is present. (Task 4.)

---

### Task 0: The shared types (the lead)

Done by the lead before either builder starts, so that both branch from one commit.

**Files:**
- Modify: `v2/crates/room/src/types.rs`, and every place that builds a `Step` or a `WorkerRun`.

**Interfaces:**
- Produces, in `room::types` (re-exported from `room`):

```rust
/// A tracked file a step named: its path in the repository and its blob at the base.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Named { pub path: String, pub blob: String }

pub struct Step {
    pub seq: u32, pub tool: Tool, pub target: Target, pub ok: bool,
    pub tokens_in: Option<u32>, pub tokens_out: Option<u32>,
    /// Every tracked file the step named, in the order named. Empty when it named none.
    pub named: Vec<Named>,
    /// Milliseconds from the turn's start to the call being seen, and to its result.
    pub seen_ms: Option<u32>, pub result_ms: Option<u32>,
}

/// What a worker's program reported for a whole turn. A part it did not report is `None`, never 0.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Tokens {
    pub fresh_in: Option<u64>, pub cache_write: Option<u64>, pub cache_read: Option<u64>,
    pub output: Option<u64>, pub reasoning: Option<u64>,
    /// True only when the program gave its closing total.
    pub complete: bool,
}
impl Tokens {
    pub fn none() -> Tokens;                 // every part None, complete false
    pub fn total(&self) -> Option<u64>;      // fresh_in + cache_write + cache_read + output, when complete
}

/// How a turn's worker ended.
#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Ended { Exited, Signalled, TimedOut, Stopped, LeaseLost, NotRun }

/// A turn's measured record. Durations are milliseconds on a clock that does not jump.
#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct Measured {
    pub ended: Ended, pub exit_code: Option<i32>,
    pub tokens: Tokens, pub steps_seen: u64, pub unknown_steps: u64,
    pub sandbox_ms: u64, pub worker_ms: u64, pub seal_ms: u64, pub bring_ms: u64,
    pub check_ms: Option<u64>, pub recheck_ms: Option<u64>,
    /// sandbox_ms + worker_ms + seal_ms + bring_ms + check_ms. A second look is not in it.
    pub active_ms: u64,
}

#[derive(Debug, Clone, Copy, PartialEq, Eq, Serialize, Deserialize)]
#[serde(rename_all = "snake_case")]
pub enum Change { Added, Changed, Removed }

#[derive(Debug, Clone, PartialEq, Eq, Serialize, Deserialize)]
pub struct ChangedFile { pub path: String, pub change: Change }
```

- Produces, in `turn::worker`:

```rust
/// What the room saw of a worker's run. It is filled as the run goes, so it holds whatever was seen when a
/// run ends in an error.
pub struct Seen { pub steps: Vec<Step>, pub tokens: Tokens, pub steps_seen: u64 }

pub trait Worker {
    fn name(&self) -> String;
    fn run(&self, sandbox: &Sandbox, item_title: &str, check_command: &str, limit_secs: u32,
           seen: &mut Seen) -> Result<RunStatus, TurnError>;
}
```

`WorkerRun` is removed: its `exit_code` and `timed_out` are `RunStatus`'s, and its `steps` are `Seen`'s.

- [x] **Step 1:** Add the types. `Tokens::total` is tested for: all parts present and complete; a part missing;
  not complete (None).
- [x] **Step 2:** Give every existing `Step` its new fields with nothing in them (`named` empty, both times
  `None`), and move every `Worker::run` to the new signature with `Seen::tokens = Tokens::none()` and
  `steps_seen` the parser's `total_steps()`. No behaviour changes.
- [x] **Step 3:** The whole suite passes on the Mac and the Pi, as CI runs it. Commit.

---

### Task 1: The store at version 2 (the Codex builder)

**Files:**
- Modify: `v2/crates/room/src/store.rs`, `v2/crates/room/src/limits.rs`, `v2/crates/room/src/types.rs`
- Test: `v2/crates/room/tests/store.rs`, `v2/crates/room/tests/review.rs`

**Interfaces:**
- Consumes: Task 0's types.
- Produces: `limits::SCHEMA_VERSION == 2`; `RoomError::OlderSchema { found: u32, known: u32 }`; four tables:

```sql
CREATE TABLE step_files (attempt TEXT NOT NULL, seq INTEGER NOT NULL, ordinal INTEGER NOT NULL,
    path TEXT NOT NULL, blob TEXT NOT NULL, PRIMARY KEY(attempt, seq, ordinal),
    FOREIGN KEY(attempt, seq) REFERENCES steps(attempt, seq));
CREATE TABLE measured (attempt TEXT PRIMARY KEY REFERENCES attempts(id), ended TEXT NOT NULL,
    exit_code INTEGER, tokens_complete INTEGER NOT NULL, fresh_in INTEGER, cache_write INTEGER,
    cache_read INTEGER, output INTEGER, reasoning INTEGER, steps_seen INTEGER NOT NULL,
    unknown_steps INTEGER NOT NULL, sandbox_ms INTEGER NOT NULL, worker_ms INTEGER NOT NULL,
    seal_ms INTEGER NOT NULL, bring_ms INTEGER NOT NULL, check_ms INTEGER, recheck_ms INTEGER,
    active_ms INTEGER NOT NULL);
CREATE TABLE changes (attempt TEXT NOT NULL REFERENCES attempts(id), ordinal INTEGER NOT NULL,
    path TEXT NOT NULL, change TEXT NOT NULL, PRIMARY KEY(attempt, ordinal));
```

  and two columns on `steps`: `seen_ms INTEGER`, `result_ms INTEGER`.

- [ ] **Step 1: Write the failing tests.**
  - `a_version_1_store_is_brought_forward_when_opened_for_writing`: build a version-1 store by running the
    stage 1 schema text (keep it in the test as a constant) and inserting one item, attempt, step and verdict;
    `Room::open` succeeds; `schema_version` is 2; every old row reads back; the new tables exist and are empty.
  - `a_version_1_store_opened_read_only_says_how`: `Room::open_read_only` returns
    `OlderSchema { found: 1, known: 2 }`, and its message names opening it once for writing.
  - `a_newer_schema_is_refused` now expects `NewerSchema { found: 3, known: 2 }`.
  - `bringing_a_store_forward_is_all_or_nothing`: with the write lock held by another connection (the
    `StoreHeld` pattern of `crates/yak/tests/common/mod.rs`), `Room::open` fails and the store is still
    version 1 and opens with the stage 1 column list.
  - Erasing an item removes its rows from the three new tables (extend the table list in
    `erasing_an_item_removes_every_row_and_its_title_from_the_file`).
- [ ] **Step 2:** Run them. Expected: FAIL (no such variant, version mismatch).
- [ ] **Step 3: Implement.** One transaction: create the new tables, add the two columns, set the version.
  `validate` prepares against every table and column of version 2. `erase_item` deletes from the new tables
  before their parents.
- [ ] **Step 4:** `cargo test -p room` passes. Commit.

---

### Task 2: A turn's measured record in the store (the Codex builder)

**Files:**
- Modify: `v2/crates/room/src/walk.rs`, `v2/crates/room/src/lib.rs`; create `v2/crates/room/src/measured.rs`
- Test: `v2/crates/room/tests/walk.rs`; create `v2/crates/room/tests/measured.rs`

**Interfaces:**
- Consumes: Task 1's tables.
- Produces:

```rust
impl Room {
    /// Keeps a walk. A named file whose path is not a plain path is left out of `named` and the step is
    /// counted as unknown; the rest of the walk is kept. Returns how many names were left out.
    pub fn record_walk(&mut self, attempt: &AttemptId, steps: &[Step]) -> Result<usize, RoomError>;
    pub fn walk(&self, attempt: &AttemptId) -> Result<Vec<Step>, RoomError>;   // with named and times
    /// One per attempt. A second call for the same attempt is refused.
    pub fn record_measured(&mut self, attempt: &AttemptId, m: &Measured) -> Result<(), RoomError>;
    /// Adds the seconds of a second look to an attempt already measured.
    pub fn record_recheck_ms(&mut self, attempt: &AttemptId, ms: u64) -> Result<(), RoomError>;
    pub fn measured(&self, attempt: &AttemptId) -> Result<Option<Measured>, RoomError>;
    /// Keeps the files a turn's commit changed. A path that is not plain is counted, not kept.
    pub fn record_changes(&mut self, attempt: &AttemptId, files: &[ChangedFile]) -> Result<usize, RoomError>;
    pub fn changes(&self, attempt: &AttemptId) -> Result<Vec<ChangedFile>, RoomError>;
    /// Every attempt of an item, in the order taken.
    pub fn turns(&self, item: &ItemId) -> Result<Vec<TurnView>, RoomError>;
}
#[derive(Debug, Clone, PartialEq, Eq, Serialize)]
pub struct TurnView {
    pub attempt: AttemptId, pub lease_no: u32, pub worker: String, pub state: String,
    pub commit: Option<String>, pub passed: Option<bool>, pub measured: Option<Measured>,
    pub changes: Vec<ChangedFile>, pub steps: u32, pub steps_with_a_name: u32,
}
```

`record_walk`'s return changes meaning (it returned the number of steps). Its one caller is updated in Task 5.

- [ ] **Step 1: Write the failing tests.**
  - `a_step_keeps_every_file_it_named_in_order`: a step with three `Named` reads back with the same three.
  - `a_name_that_is_not_a_plain_path_is_left_out_and_the_walk_is_kept`: three steps, the second naming
    `"a b.txt"` and `"ok.txt"`: all three steps are kept, the second has only `ok.txt`, and the call returns 1.
    (Review Focus 3.) Paths tried: a space, `é`, `../x`, an absolute path, 513 bytes.
  - `a_measured_record_reads_back_whole`: every field, with `None` parts staying `None` and not 0.
  - `a_second_measured_record_for_one_attempt_is_refused`.
  - `a_second_looks_seconds_are_kept_beside_the_turns` (`record_recheck_ms` sets `recheck_ms`, leaves
    `active_ms`).
  - `changes_read_back_in_order`, and a path that is not plain is counted and not kept.
  - `the_store_holds_no_free_text` covers every TEXT column of the three new tables.
  - `turns_lists_an_items_attempts_with_what_was_measured`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** `cargo test -p room` passes. Commit.

---

### Task 3: What the parsers read (the Claude builder)

**Files:**
- Modify: `v2/crates/turn/src/transcript.rs`, `v2/crates/turn/src/worker.rs`
- Test: `v2/crates/turn/tests/transcript.rs`, `v2/crates/turn/tests/worker.rs`

**Interfaces:**
- Consumes: Task 0's `Step`, `Tokens`, `Seen` and the `Worker::run` signature.
- Produces: `ClaudeParser::tokens(&self) -> Tokens` and `CodexParser::tokens(&self) -> Tokens`; both parsers
  take the turn's start (`Instant`) at `new` and stamp each step's `seen_ms` and `result_ms`; `Seen` is filled
  line by line, so it holds what was seen when `run` returns an error.

- [ ] **Step 1: Write the failing tests.**
  - `the_closing_total_is_the_turns_tokens`, on `tests/data/claude-stream-ids.jsonl`: `tokens()` is
    `{ fresh_in: 4, cache_write: 7287, cache_read: 29643, output: 286, complete: true }`, total 37,220. On
    `codex-json-sample.jsonl`: read `turn.completed.usage`. **First establish, from the two captured files and
    the program's own documentation in the repository if any, whether Codex's `input_tokens` includes its
    `cached_input_tokens`.** Write what you found in the test's comment and in your report. If the captures
    cannot settle it, keep both numbers as reported, mark which is which, and say it is not settled.
  - `a_stream_cut_off_before_its_closing_total_is_not_complete`: the same streams without their last line:
    `complete == false`, and the parts are `None`, not a partial sum.
  - `a_closing_total_that_arrives_twice_is_counted_once`.
  - `a_turn_with_no_tool_call_still_has_its_tokens`: a stream of text messages and a closing total.
  - `a_shell_step_names_every_tracked_file_in_order`: `cat a.txt b.txt` has `named == [a.txt, b.txt]`. Its
    `target` stays `Outside`, as today, so nothing that reads `target` changes meaning. A file named twice is
    named once, at its first place.
  - `a_step_has_the_time_it_was_seen_and_the_time_of_its_result`, with the lines fed at known moments
    (a parser method that takes the moment as an argument, used by `line`): `seen_ms <= result_ms`, and a
    call with no result has `result_ms == None`.
  - `what_was_seen_is_kept_when_the_run_ends_in_an_error`: a worker whose stream gives two steps and whose
    clone is then made unusable so that the room's commit fails: `run` returns `Err`, and `seen.steps.len() == 2`.
    (Review Focus 2.)
  - The parsers' line filters (`"tool_"`, `"item`) no longer drop the closing lines:
    `a_closing_line_with_no_tool_word_in_it_is_read`.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.** Keep the two-hundred-megabyte and hundred-thousand-step tests passing: nothing
  new is held per line beyond what a step holds.
- [ ] **Step 4:** `cargo test -p turn --test transcript --test worker` passes. Commit.

---

### Task 4: A sandbox holds what its base reaches (the Claude builder)

**Files:**
- Modify: `v2/crates/turn/src/sandbox.rs`, `v2/crates/turn/src/worker.rs`
- Test: `v2/crates/turn/tests/sandbox.rs`, `v2/crates/turn/tests/worker.rs`

**Interfaces:**
- Produces: `Sandbox::create` unchanged in signature. The clone holds the objects `base_commit` reaches and no
  other object of the item's repository. `seal` uses a worker's own message when it left one.

- [ ] **Step 1: Write the failing tests.**
  - `a_sandbox_holds_nothing_its_base_does_not_reach`: the item's repository has the base, a later commit on
    another branch, and a dangling blob. In the sandbox, `git cat-file -e` fails for the later commit, its
    tree's new blob and the dangling blob, and succeeds for the base's tree (the control). The same for the
    clone a check runs in. (Review Focus 5.)
  - `two_turns_at_one_item_do_not_share_an_answer`: make a sandbox, commit in it, bring that commit into the
    item's repository as the clock does (`fetch` by id, then `update-ref`); a second sandbox at the same base
    does not hold the commit. Control: the item's repository does.
  - `a_base_that_is_not_a_branch_tip_can_still_be_cloned` (the base is an older commit of a branch).
  - Every existing sandbox test still passes: no remote, the room's settings, the branch, `head()`.
  - `a_worker_that_cannot_commit_leaves_its_message`: an agent leaves a change and a file `.yak-message` at
    the clone's root. The room's commit has that text as its message, followed by the room's two trailer
    lines; `.yak-message` is not in the commit's tree and not on disk afterwards.
  - `a_message_file_that_is_not_a_plain_file_is_not_read`: a link, a directory, a pipe, or more than 16,384
    bytes: the room commits with its fixed message and removes what was there if it is a file or a link.
  - `the_prompt_says_where_to_leave_a_message`: `prompt(..)` holds the sentence below.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.** The clone is made by `git init` and a fetch of the base by its id from the item's
  repository, with the room's safe git and no hard links. Add to `INTRO`, exactly: "If your tools cannot
  commit, leave your commit message in a file named `.yak-message` at the repository's root and the room will
  commit for you with it."
- [ ] **Step 4:** `cargo test -p turn` passes where your sandbox allows. Say which tests it does not. Commit.

---

### Task 5: The clock measures and records every turn (the Codex builder)

**Files:**
- Modify: `v2/crates/yak/src/clock.rs`, `v2/crates/yak/src/lib.rs`, `v2/crates/yak/src/main.rs`
- Test: `v2/crates/yak/tests/clock.rs`, `v2/crates/yak/tests/cli.rs`

**Interfaces:**
- Consumes: Tasks 0 and 2. It can be built against Task 0's `Worker::run` before Task 3 lands, since the
  parsers then give `Tokens::none()`.
- Produces: `yak item turns <id> [--json]`, printing `Room::turns`. No new MCP tool: the server keeps four.

- [ ] **Step 1: Write the failing tests.** Each uses a script worker, so no model runs.
  - `every_way_a_turn_ends_leaves_a_measured_record`: one item each for: passes; fails its check; hands in
    nothing; times out; the room is stopped while it runs; its lease is lost; its clone is unusable. For each:
    `Room::measured` is `Some`, `ended` is the right word, and `active_ms` equals the sum of its parts.
    (Review Focus 1 and 2.)
  - `a_turns_steps_are_kept_when_its_worker_ends_in_an_error` and `a_turn_with_no_steps_still_has_a_record`.
  - `a_turns_changes_are_the_difference_between_its_base_and_its_commit`: a script that adds one file, changes
    one with a shell redirection and removes one: `Room::changes` has the three, with their kinds.
  - `a_second_look_is_timed_beside_the_turn`: with random numbers that always pick a second look,
    `recheck_ms` is `Some` and `active_ms` is unchanged by it.
  - `durations_do_not_depend_on_the_wall_clock`: nothing in the measured record is read from `SystemTime`
    (assert on the code path by a unit test of the timer type you add, not by changing the machine's clock).
  - `item_turns_prints_what_was_measured` (the command line), and `the_mcp_server_lists_exactly_four_tools`
    still passes.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.** One `Instant` at the moment the room starts to make the sandbox. Phases are closed
  in order: sandbox, worker, seal, bring, check. A phase that did not happen is 0, or `None` for the check.
  The changed files come from `git diff --name-status -z --no-renames <base> <commit>` in the item's
  repository, by the room's safe git.
- [ ] **Step 4:** `cargo test -p yak` passes where your sandbox allows. Say which tests it does not. Commit.

---

### Task 5b: A prompt of its own (the lead, after the builders' work is merged)

Added after the plan was written, from an advisory read of the spec by the ship Tardis: two turns given the
same prompt share a program's memory of it, so the later one is cheaper and faster.

**Files:**
- Modify: `v2/crates/turn/src/worker.rs`, `v2/crates/yak/src/main.rs`, `v2/crates/yak/src/clock.rs`
- Test: `v2/crates/turn/tests/worker.rs`, `v2/crates/yak/tests/cli.rs`

**Interfaces:**
- Produces: `yak clock run --own-prompts`. With it, `prompt` is given the turn's attempt id and begins with one
  line holding it. Without it the prompt is as it was. The line is in no store.

- [ ] **Step 1: Write the failing tests.** `two_turns_at_one_item_have_prompts_that_differ_from_the_first_line`
  with the switch on; `the_prompt_is_as_it_was_without_the_switch`; `no_turns_own_line_reaches_the_store`
  (scan the store's file for the attempt id inside any text that is not an id column).
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.**
- [ ] **Step 4:** The whole suite on both machines. Commit.

---

### Task 4b: A worker's shell is shown what the jail shows (a Claude builder, read by the other family)

Added after the plan was written, from a question by the ship Tardis: what can a model worker reach outside
its clone? The lead measured it (the spec, "What a worker can read beside its sandbox"). As stage 1 set the
two programs, a worker's shell reads the home but for a few named places, and shares the machine's temporary
directories with every other turn. Both programs can be set to hide all of that and still do a turn's work;
that was measured through a live turn of Claude and through Codex's own sandbox command.

**The rule.** A model worker's shell is shown its sandbox, a temporary directory of the turn's own, the
system, and the directories named in `YAK_JAIL_READ`. Hidden from it: the home, the room's directory, the
item's repository, and the temporary directories the machine shares.

**Files:**
- Modify: `v2/crates/turn/src/jail.rs`, `v2/crates/turn/src/sandbox.rs`, `v2/crates/turn/src/worker.rs`,
  `v2/crates/yak/src/clock.rs`
- Test: `v2/crates/turn/tests/sandbox.rs`, `v2/crates/turn/tests/worker.rs`, `v2/crates/yak/tests/clock.rs`

**Interfaces:**
- Produces:
  - `turn::jail::places() -> Result<Places, TurnError>` with `pub struct Places { pub home: PathBuf, pub
    hidden: Vec<PathBuf>, pub shown: Vec<PathBuf>, pub system: Vec<PathBuf> }`: the home as a real path; the
    home's keys and settings that are there; each `YAK_JAIL_READ` directory; and the system directories the
    jail shows on this machine that are there. All read exactly as the jail reads them, with the jail's
    refusals: one reading of the settings, not a second copy of the rules.
  - `Sandbox::hide_from_worker(&mut self, path: &Path) -> Result<(), TurnError>` and
    `Sandbox::hidden_from_worker(&self) -> &[PathBuf]`. `create` puts the item's repository there as a real
    path. A path that is not absolute or is not there is refused.
  - `Sandbox::worker_tmp(&self) -> Result<PathBuf, TurnError>`: the turn's own temporary directory, made on
    first use and the same afterwards. It is a new directory `yak-` and 16 hex characters from the system's
    random source, directly under the real path of `/tmp`, with mode 0700, made so that making it fails if
    anything is already there (then another name is tried, five times at most). It is removed where the
    sandbox is removed, by the same care: only the directory the room made, never a link. A clock that dies
    leaves it behind; nothing reads it, and the system clears `/tmp`.
    Why `/tmp` and not beside the sandbox: Claude gives a shell command a temporary directory shared by
    every session on the machine unless the one it is told to use has a short path (measured: a path of 77
    characters was not used, one of 19 was).
  - `Sandbox::shared_tmp() -> Vec<PathBuf>`: the real path of `/tmp`, and the real path of the clock's own
    `TMPDIR` when it is set, is there and is another directory.
  - `ClaudeWorker::settings(sandbox) -> Result<serde_json::Value, TurnError>`. In `sandbox.filesystem`:
    `denyRead` is the home, each of `hidden_from_worker()`, each of `shared_tmp()`, each of `places.hidden`,
    then `**/.env` and `**/.env.*`; `allowRead` is the sandbox's directory, `worker_tmp()`, and each of
    `places.shown` that is not itself in `denyRead`; `allowWrite` is the sandbox's directory and
    `worker_tmp()`. The rest is as it was.
  - `CodexWorker::args(sandbox) -> Result<Vec<String>, TurnError>`: no `-s` and no sandbox mode (a sandbox
    mode makes Codex ignore a profile). In their place three `-c` values: `default_permissions="yak"`,
    `permissions.yak.extends=":workspace"`, and `permissions.yak.filesystem={…}`, an inline table that holds,
    in this order: `":root"="deny"`, `":minimal"="read"`, `":slash_tmp"="deny"`; each of `places.system` as
    `"read"`; each of `places.shown` as `"read"`; `worker_tmp()` as `"write"`; each of
    `hidden_from_worker()` and of `places.hidden` as `"deny"`. A key that is a path is a TOML basic string:
    `\` and `"` are escaped. A path that holds a control character or is not UTF-8 is refused. A shown
    path that is also hidden is left out of the shown ones, and no path is written twice. Hiding the home alone is not used for Codex: measured, it breaks
    `cd` in a script run by `sh`.
  - The environment a model worker's program is given also carries `TMPDIR` and `CLAUDE_CODE_TMPDIR`, both
    `worker_tmp()`, and `GIT_CONFIG_GLOBAL=/dev/null`: git stops when it may not read the home's settings
    (measured: "fatal: unable to access '…/.gitconfig': Operation not permitted").
  - A clone's settings also name `/dev/null` for `core.excludesFile` and `core.attributesFile`, so that no git
    in the clone looks for either in a home.
  - The clock hides the room's directory from every worker: `hide_from_worker(room directory)` on each
    sandbox it makes for a turn.

- [ ] **Step 1: Write the failing tests.**
  - `a_sandbox_hides_its_items_repository_from_a_worker`: after `create`, the list is the repository's real
    path; a relative path and a missing one are refused; a good one is added as a real path.
  - `a_turns_own_temporary_directory_is_short_private_and_removed_with_it`: its parent is the real `/tmp`;
    its mode is 0700; a second call gives the same path; another sandbox gets another; it is gone when the
    sandbox is removed; a link put in its place is not followed when removing.
  - `claudes_shell_is_shown_the_sandbox_its_own_tmp_and_the_named_tools_and_not_the_home`: with a home and
    one `YAK_JAIL_READ` directory, `denyRead` begins with the home and holds the repository, a path that was
    added, and the shared temporary directories; `allowRead` is the sandbox's directory, the turn's own
    temporary directory and the tool directory; `allowWrite` is the first two of those alone.
  - `codex_is_given_a_profile_and_no_sandbox_mode`: the arguments hold no `-s` and no `workspace-write`, and
    hold the three values, the table compared as a whole string.
  - `a_path_with_a_quote_or_a_backslash_is_written_as_toml`, `a_path_with_a_control_character_is_refused`.
  - `a_tool_directory_that_is_also_hidden_is_not_shown`: the item's repository named in `YAK_JAIL_READ`.
  - `a_workers_program_is_given_its_own_tmp_and_no_global_git_settings`: a script standing in for each
    program prints the three variables.
  - `a_clone_looks_for_no_ignore_or_attributes_file_in_a_home`.
  - `the_clock_hides_its_room_from_a_worker`: fails when the clock's call is taken out.
- [ ] **Step 2:** Run them. Expected: FAIL.
- [ ] **Step 3: Implement.** Bring the doc comments on both workers up to date: they say what a shell can read.
- [ ] **Step 4:** `cargo test -p turn -p yak` where your sandbox allows. Say which tests it does not. Commit.
- [ ] **Step 5 (the lead):** A live turn of each program in a throwaway room, on an item whose repository
  holds a script of probes and whose work is to run it and commit its output. Read the output in the commit
  handed in: the room's directory, the item's repository, another checkout, the home and a file left in
  `/tmp` refused; the sandbox, the turn's own temporary directory and a named tool used; an earlier answer's
  object absent and the base's tree present. Then the three live replays of the stage 1 items, as the spec's
  smoke test, to see that a worker can still do real work.

---

### Task 6: Each builder reads the other's work, then the lead runs the acceptance table

- [ ] **Step 1:** The Codex builder reads Tasks 3 and 4; the Claude builder reads Tasks 1, 2 and 5. Each
  reports what it would change, by file and line, and whether any test would still pass with its change
  taken out.
- [ ] **Step 2 (the lead):** Merge, run the whole suite on the Mac and the Pi as CI runs it, and CI.
- [ ] **Step 3 (the lead):** Go down the table under "How we know part 0 is done" in the spec, row by row,
  with the test or the measurement that shows each. The rows about the offer wait for the second plan.
- [ ] **Step 4 (the lead):** Decide tokens or seconds by that table, publish it, and only then run the pilot.
