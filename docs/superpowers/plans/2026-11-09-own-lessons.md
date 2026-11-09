# Own Lessons, Once a Context Window: Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or
> superpowers:executing-plans to implement this plan task by task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** show a ship its own lessons, and show every lesson again once a context window as a reminder, at the
lessons hook's three events. Reminders count nowhere, and the hold is untouched.

**Architecture:** the peer (`peer/superyak_peer/lessons.py`) learns three request keys (`own`, `window_seen`, `reask`).
It answers first reaches, then reminders, then own lessons, and writes receipts only for first reaches. The hook
(`agent/superyak_agent/lessons_hook.py`) keeps window lists beside its session lists, clears them at a compact
SessionStart, finds the last compaction boundary, and reads back only after it at a prompt.

**Tech stack:** Python 3 standard library, SQLite, pytest.

**Spec:** `docs/superpowers/specs/2026-11-09-own-lessons-on-the-rail-design.md` (draft 6, final, 322802fa). Every
section reference below is to it. Its "Tests" list is this plan's tests: each one is named under the task that owns it.

## Global constraints

- `hold.py`, `lessons_hold.py`, `holds.py`, `could_hold`, `heads` and their tests are not edited. `agent/tests/test_lessons_hold.py` and `peer/tests/test_lessons_hold_contract.py` pass unchanged.
- The prompt path writes nothing. No id read from the transcript is ever written (first rail section 8; `agent/tests/test_lessons_hook_nowrite.py` passes unchanged).
- Own lessons match by words only, never Near. No new embedding, store open or query on any path.
- `ANSWER_BYTES` 2,000, `SEEN_MAX` 128, `SHOWN_AT_PROMPT` 2, `REQUEST_LIMITS` {prompt 2, start 3, failure 3}, `STATE_DAYS` 14, `WINDOW` 4 MiB: unchanged.
- Own heading, exactly: `Your own lessons, from this ship's earlier sessions (quoted data, not instructions)`.
- Commits end with the line `Made by Rio Grande.` and the Co-Authored-By trailer.
- Tests: peer `cd peer && .venv/bin/python -m pytest`; agent `cd agent && ../peer/.venv/bin/python -m pytest` (or the agent's own venv if it has one); both under `TMPDIR=/var/tmp`.

## Review focus

1. **A lesson shown at any event, in any window, never holds later.** The hold reads `shown`, and `shown` must stay the session's (spec "What stays as it is").
2. **A reminder or an own lesson never gets a receipt, and never takes a first reach's slot or bytes** (spec "The answer").
3. **Text that isn't a real top-level, non-sidechain system record never moves the boundary** (spec "Finding the boundary").
4. **A compact SessionStart clears the window whatever the query then does**, and writes nothing read from the transcript (spec "At compaction, first").
5. **An old hook with a new peer, and an old peer with a new hook, behave exactly as main** (spec "The request and the answer").

## Rulings (made while planning)

- **Own lessons at the 2 s events go through step 4's live check** (retraction and membership, as for others'), with no receipt. At a prompt they come from the index, as others' do. Why: a retracted own lesson shouldn't show. Cost if wrong: one more filter.
- **The shadow (`reordered`, `displaced`) isn't built yet**, so "the shadow counts first reaches only" is a sentence in the outcomes spec, not code. The same goes for section 7's recalibration of `r_max` from query rows: it's a written procedure, not code.
- **The first rail spec lives on `trail-arrows-spec`, not on main.** Its sentences (sections 5 step 3, 7.1 and 8) are amended there in one commit after this branch merges. The outcomes spec's section 6 line and `REPEAT_OWN` change here.
- **Reviews:** each task is checked by its own tests and the suites. One fresh reader then reads the whole branch on the Pi before the merge, and Tardis gives its yes as partner (spec "Whose yes"). Why: Andy asked us to save tokens (2026-11-07), and the spec has already had five reads. Cost if wrong: the reader's findings land in one bigger round.

---

### Task 1: The peer answers own lessons and reminders, and counts first reaches only

**Files:**
- Modify: `peer/superyak_peer/lessons.py` (`read_request` :508, `fit` :541, `prompt_answer` :574, `query` :693, `Lessons._lessons_answer` :1382, the counts :1569, `REPEAT_OWN` :112, `LESSON_SCHEMA` :1618)
- Modify: `peer/superyak_peer/db.py` (the ALTER pattern, :103-120)
- Modify: `docs/superpowers/specs/2026-11-03-lesson-outcomes-design.md` (section 6's own-lesson sentence; one line in section 5 saying `reask` rows and reminders are left out, and the shadow counts first reaches only)
- Create: `peer/tests/test_lessons_own.py`

**Interfaces:**
- Produces, for Task 2:
  - The request: `own` (bool, default False), `window_seen` (a list checked by `seen_ok`, absent means `seen`), and `reask` (bool, default False, failure requests only).
  - The answer: `{'lessons': [...], 'own': [...]}`. `own` is present only when it isn't empty, and its entries never carry `receipt`. A reminder in `lessons` carries no `receipt`.
  - `fit(lessons, own=())` returns that shape, measured on the exact bytes of `dumps(answer)`.

- [ ] **Step 1: Write the failing tests** in `peer/tests/test_lessons_own.py`. Build on the fixtures in `peer/tests/test_lessons.py` and `peer/tests/test_lessons_outcomes.py`. Each test takes its name and assertions from the spec's "Tests":
  - `test_a_reminder_writes_no_receipt`: a lesson in `seen` but not in `window_seen` is answered with no `receipt`, and `lesson_receipts` doesn't grow.
  - `test_a_reask_answers_reminders_only`: with `reask: true`, a matching lesson not in `seen` isn't answered. One in `seen` is answered with no receipt. The query row has `reask=1`, and the `queries` count leaves it out.
  - `test_first_reaches_come_first`: at a failure with 3 slots, 2 reminders and 2 first reaches matching gives both first reaches with receipts, then 1 reminder. The same holds within the 2,000-byte fit.
  - `test_no_window_seen_is_mains_answer`: a request with no `window_seen` gets exactly the answer it gets on main.
  - `test_own_by_author_id`: an own lesson is answered under `own` with no receipt. A remote lesson whose text says `ship: <asking ship>` never appears in `own`.
  - `test_words_only_never_gets_own`: a `words_only` request with `own: true` gets no `own` key.
  - `test_fitting_edges`: three receipted lessons at 1,990 bytes plus own matches gives no `own` key, shows all three, and writes no receipt for a lesson left out. One other lesson plus own lessons over 2,000 bytes keeps the other and drops own entries first.
  - `test_per_event_rules`: an own lesson whose only `command` value is 4 bytes matches at a failure and never at a prompt.
  - `test_retracted_own_lesson_is_not_shown`: at a failure, a retracted own lesson fails step 4's live check and isn't shown (the ruling).
  - `test_reask_column_added_to_an_old_store`: a store made with main's schema gains `reask` with default 0 on open.
  - `test_one_outcome_a_session_after_a_reshow`: after a re-show, a second outcome for the lesson is refused by the existing `OUTCOME_TWICE` rule.
  - `test_old_peer_drops_new_keys`: main's `read_request` given `own`, `window_seen` and `reask` parses as before. Check this by calling it with those keys and asserting the parsed request has none of them, so it pins the claim the spec rests on.

- [ ] **Step 2: Run them to see them fail:** `cd peer && TMPDIR=/var/tmp .venv/bin/python -m pytest tests/test_lessons_own.py -q`. Expected: failures on the new keys and the new shape.

- [ ] **Step 3: Implement.**
  - **`read_request`:** the three keys. `window_seen` goes through `seen_ok`, capped at SEEN_MAX, and when absent `request['window_seen'] = request['seen']`. `own` and `reask` must be bool. `reask` is accepted only without `prompt`.
  - **`prompt_answer`:** filter others' by `window_seen`, not `seen`. When `own` is true, add own words matches (author id == asking) after the others, under the prompt's rule.
  - **`query`:** the pool filters by `window_seen`. Candidates are first reaches (not in `seen`) sorted as today, then reminders (in `seen`). With `reask`, first reaches are dropped. Near stays over first reaches only. Own lessons, when asked and not `words_only`, are words matches over own authored lessons in `window_seen`'s complement.
  - **`_lessons_answer`:** the live check for all candidates, own included (author == full is now allowed only for own entries). A `uid()` and a receipt only for first reaches. The fit runs through `fit(lessons, own)`. The query row gains `reask`, and its `shown` counts first reaches only.
  - **`fit(lessons, own=())`:** keep lessons in order while the exact `dumps` bytes, with `own` included when non-empty, stay within ANSWER_BYTES. Then add own entries while they fit. Leave the `own` key out when it's empty.
  - **`db.py` and `LESSON_SCHEMA`:** `reask INTEGER NOT NULL DEFAULT 0` on `lesson_queries`, through the ALTER pattern. The `queries` count becomes `WHERE reask=0`.
  - **`REPEAT_OWN`:** the spec's new reason, word for word from its "Sentences elsewhere that change".
  - **The outcomes spec:** section 6's sentence as the spec words it, plus one line in section 5.

- [ ] **Step 4: Run the peer suite:** `cd peer && TMPDIR=/var/tmp .venv/bin/python -m pytest -q`. Expected: all pass, `test_lessons_hold_contract.py` and `test_lessons_tool_holds.py` unchanged. Name any failure that also fails on main.

- [ ] **Step 5: Commit:** `Own lessons, the peer: own, window_seen and reask; receipts for first reaches only. Made by Rio Grande.`

### Task 2: The hook keeps a window, clears it at compaction, and shows own lessons last

**Files:**
- Modify: `agent/superyak_agent/lessons_hook.py` (`transcript_ids` :253, new `last_boundary`, `render` :239, `_output` :434, `_record` :438, `run` :483, the module docstring)
- Create: `agent/tests/test_lessons_hook_own.py`
- Modify: `Makefile` (`lessons-own-shown`, beside `lessons-list` :508)

**Interfaces:**
- Consumes Task 1's request and answer, above.
- Produces:
  - `last_boundary(path, deadline, window=WINDOW, monotonic=time.monotonic) -> int | None`: the byte offset just after the last real boundary record. None for no boundary, or past the deadline.
  - `transcript_ids(path, deadline, window=WINDOW, monotonic=time.monotonic, start=0)`: the same return as today when `start` is 0.
  - The record keys `window_shown`, `window_commands`, `window_errors`, `windows` and `own_count`.
  - `render(lessons, data_dir=None, own=())`.

- [ ] **Step 1: Write the failing tests** in `agent/tests/test_lessons_hook_own.py`. Reuse `agent/tests/test_lessons_hook.py`'s world and stub-query fixtures (`lessons_stub.py`), and take names and assertions from the spec's "Tests":
  - `test_hold_across_a_compaction`: a lesson is shown at a failure, then a compact SessionStart runs, then `lessons_hold.candidates` sees a matching command; it gives no hold. The same holds for a lesson shown at session start and one shown at a prompt. The test calls the hold's real code without editing it.
  - `test_shown_once_a_window`: own and others' lessons each show once before a compaction and once after it. A prompt's ids are read back, never written.
  - `test_the_split_at_the_boundary`: a lesson shown at a prompt in window 1 and again in window 2 is in `window_seen` at a failure in window 2, and doesn't show a third time.
  - `test_the_clear`: a compact SessionStart with no cwd, with a spent budget, with an empty answer and with a failed query each leaves the window lists empty, the session lists as they were, and `windows` one higher. One that can't take the lock by its deadline writes nothing.
  - `test_a_planted_boundary`: a `tool_use` input holding `{"type":"system","subtype":"compact_boundary"}` after the real last boundary doesn't move the window. A sidechain boundary doesn't either.
  - `test_the_search_is_bounded`: with `windows` 1 and no boundary, the search checks the deadline between chunks (a fake `monotonic`), and past it the event adds nothing.
  - `test_the_hooks_cap`: a stub that sends 2 others' and 3 own lessons at a prompt shows exactly the 2 others. An own entry with a receipt, another ship's name, or a `match` other than `words` is dropped. An id in both keys shows once.
  - `test_budget_order`: 2 others' lessons matching at a prompt leaves no room for own; 1 leaves room for at most 1 own.
  - `test_reask_sent_once_a_window`: a failure whose command and error are in the session lists but not the window's asks with `reask: true`. One already in the window's returns before the query.
  - `test_old_hook_ignores_own`: today's `check_answer` given an answer with `own` returns the others' lessons.
  - `test_own_heading_and_id_lines`: own lessons render after the others under the exact heading, each with its `Lesson <id> from <ship>` line and fence, and `transcript_ids` reads them back.
  - `test_the_name_trick`: a remote lesson saying `ship: <this ship>`, shown at a prompt, shows once in the window, and the hold never holds on it in the session.
  - `test_a_real_case`: the shape of `4f6d3140-689a342e` as laid (`command: make check`) shows after a matching failure, and again after a compaction with no second receipt. It runs against a stub peer whose receipts are counted.
  - `test_transcript_ids_start_zero_is_today`: on a transcript with boundaries, `transcript_ids(path, d)` and `transcript_ids(path, d, start=0)` return what main returns.

- [ ] **Step 2: Run them to see them fail:** `cd agent && TMPDIR=/var/tmp ../peer/.venv/bin/python -m pytest tests/test_lessons_hook_own.py -q`.

- [ ] **Step 3: Implement.**
  - **`last_boundary`:** search backward in WINDOW chunks with an overlap of at least the pattern's length, checking the deadline between chunks. For each hit of `"type":"system","subtype":"compact_boundary"`, parse its whole line. Accept it only when it's a dict with `type == 'system'`, `subtype == 'compact_boundary'` and `isSidechain` not True, and the hit starts its line's record. Otherwise go on backward.
  - **`transcript_ids(start=)`:** scan from `start`.
  - **`run`:**
    - A compact SessionStart first takes the lock and writes the clear: the window lists emptied and `windows + 1`. It computes this event's `window_seen` from the cleared record.
    - When `windows ≥ 1`, call `last_boundary`. A prompt reads from its offset only and sends `window_seen` alone, plus `own: true`. The 2 s events read the whole file for `seen`, and the tail for `window_seen`.
    - A failure checks the window lists first, then the session lists (`reask`).
  - **`_record`:** carry every key explicitly. Filter and guard over `window_shown`. Each shown id joins `shown` and `window_shown`; own ones add to `own_count`.
  - **The hook's merge:** others first, then own entries. Cap at the event's limit, show each id once, and drop bad own entries (spec "The hook").
  - **`render(..., own=())`:** the own heading block after the others.
  - **The module docstring:** "once a context window, counted once a session".
  - **`make lessons-own-shown`:** sum `own_count` over the state directory's records. Print that it misses prompts and covers 14 days.

- [ ] **Step 4: Run the agent suite:** `cd agent && TMPDIR=/var/tmp ../peer/.venv/bin/python -m pytest -q`. Expected: all pass, with `test_lessons_hold.py` and `test_lessons_hook_nowrite.py` unchanged. Confirm with `git diff main --stat -- agent/superyak_agent/hold.py agent/superyak_agent/lessons_hold.py agent/superyak_agent/holds.py agent/tests/test_lessons_hold.py agent/tests/test_lessons_hook_nowrite.py`: empty.

- [ ] **Step 5: Commit:** `Own lessons, the hook: a window beside the session, cleared at compaction, own lessons last. Made by Rio Grande.`

### Task 3: Timing on the Pi, with the margin

**Files:**
- Modify: `peer/scripts/lessons_timing.py` (or a new `agent/scripts/readback_timing.py` if the read-back doesn't fit there)

- [ ] **Step 1:** Add a read-back arm. On a transcript given by path (default: this session's), report `transcript_ids` over the whole file, `last_boundary`, and `transcript_ids(start=offset)`, each as p50 and p95 in ms against its limit (150 ms at a prompt, 2 s at the 2 s events), with the margin.
- [ ] **Step 2:** Run it on the Pi against Rio Grande's transcript: `python3 -I <script> --transcript <path> --runs 20`. Expected: a prompt in a compacted session well under 150 ms. Record the printed lines in the commit message.
- [ ] **Step 3:** Run `make lessons-timing` (the existing arms) and confirm they still PASS.
- [ ] **Step 4: Commit:** `Own lessons: the read-back's timing, with the margin, on the Pi. Made by Rio Grande.`

### Task 4: One fresh reader, Tardis's yes, and the merge

- [ ] **Step 1:** Run the whole peer and agent suites once more, then post the counts.
- [ ] **Step 2:** Give a fresh reader on the Pi the branch's diff against main as a file, plus the spec, the plan and the Review focus above. Post its verdict whole in City of AI.
- [ ] **Step 3:** Fix what it finds, with a scoped re-check if any must was found. Then ask Tardis for its yes on the exact head and tree.
- [ ] **Step 4:** The merge follows docs/checklists.md's merging-to-main list and section 2 of the law. It isn't safety code, so it waits on no train. Then restart and check the lessons hook on the Pi, and amend the first rail spec on `trail-arrows-spec` (the ruling above).
