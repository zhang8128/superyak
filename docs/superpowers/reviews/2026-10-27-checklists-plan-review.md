# Plan review: Checklists, phase 1 (plan at 9a756393)

**Verdict: APPROVE WITH CHANGES.** The plan builds the approved spec, and its tests specify behaviour, not mocks. Five
changes are needed before building. Ruling 2 changes the spec's `command` rule, and that silently misses live station
acts run over ssh. The hold's acting check runs outside its time budget. Two tasks leave the suite red. The seed's
Reflect list doesn't read the report, which the spec requires. Apply M1 to M5 as written; they need no further round.
S1 to S3 should land before Tasks 6 and 7 are built.

Reviewer: a fresh agent under law section 3, with no part in the spec or the plan. I worked read-only. I read the spec
(rev 3, 784a60b), its review and re-check, and the plan, and checked them against `hook.py`, `__main__.py`,
`run_agent.py`, `install.py`, `project_dock.py`, `mcp.py`, `claims.py`, `station.py`, `team/superyak_team/teamlib.py`,
`tests/conftest.py` and the tests the plan touches. I also read `docs/checklists.md` at 127d285. The baseline is
confirmed: `uv run --locked --extra dev python -m pytest -q` gives **755 passed**. I ran the plan's `command_matches`
next to the spec's rule on real command shapes; the results are below.

## Must fix

**M1. Ruling 2 changes the spec's `command` rule, and the change hides the acts the lists guard.** (Plan 142-144, the
parenthetical at 53, Task 4 at 809-813 and 894-916.)
- The spec (rev 3, "`command`, exactly") says a match begins at the start of the command, after whitespace, or after
  one of `;&|(` or a backtick. Nothing in it says "outside quotes".
- S-b was a should-fix in the re-check. Revision 3 applies only R1 to R4, so S-b isn't part of the approved spec.
- With the plan's matcher, these return False (the spec's rule returns True):
  - `ssh … andy@smart 'cd ~/superyak && make station-approve ID=3fa2'`;
  - `ssh andy@smart '… && systemctl --user restart superyak-peer'`;
  - `bash -c 'cd /x && git push origin feature'`;
  - a heredoc line "we don't push yet" followed by `git push origin feature`, because the lone apostrophe opens a
    quote that never closes.
- Andy's standing instruction is that the Mac carries out Pi acts over SSH once he says yes (memory
  `smart-pi-tailnet`). So "A live station act" and "Merging to main" would go silent for exactly those acts.
- What S-b removes is a false positive like `git commit -m "fix: git push docs"`. That costs one held turn, and R2's
  context fallback already bounds it. The re-check called it "acceptable once R2 lands".
- `echo "git push"` doesn't match under the spec's rule either, because a quote isn't a boundary.

Change:
- Delete Ruling 2 and the parenthetical at 53.
- Task 4 Step 3 becomes one sentence: `command_matches` is true when some `i` has `command.startswith(words, i)`, with
  `i == 0`, or `command[i-1].isspace()`, or `command[i-1] in ';&|(`'`.
- In `test_words_match_nowhere_else…` (809-810), remove `'git commit -m "fix: git push docs"'`. Add it to the
  positives as a known false positive, and add the `bash -c '… && git push …'` form.
- In Task 11, add a positive for `live-station-act` with `ssh andy@smart 'cd ~/superyak && make station-approve ID=abc'`.
- Every other negative still holds, including 2347 and `--include='*.py'`.
- If the ships want S-b, it needs a spec revision under law section 3, not a planning ruling.

**M2. The hold's acting check can stall a Bash call past its 1 s.** (Task 7 Step 3, 1676-1679; Review Focus 3,
247-252.)
- `decide` runs `acting.verdict(home, acting.session_project(cwd))` as a precondition, before "the work runs in a
  daemon thread". That puts it on the main thread, with no clock.
- `verdict` reads `projects.json` and `claim.json`. Its `project_root` calls `realpath` and `lexists` on every
  ancestor of the cwd (`claims.py:129-158`). That is exactly the stalled network or cloud folder Review Focus 3 names.
- The spec gives the hold "150 ms from its start to read files and at most 1 s in all". As written, a hung cwd costs up
  to the 5 s hook timeout on every Bash call.
- The Review Focus 3 test (1583-1590) hangs only `checklists.find`, so it can't see this.

Change:
- The main thread checks only the payload (no file I/O).
- The worker calls `acting.verdict` (through the module) first, before `find`, and inside the 150 ms "read done"
  window.
- Add to Task 7: `test_a_hung_registry_or_cwd_read_never_stalls_the_bash_call`. It monkeypatches `acting.verdict` to
  `never.wait()` and asserts `decide(...) is None` in under 1.2 s.

**M3. Task 8 leaves the suite red.** `tests/test_session_end.py:57` asserts `sorted(install.install_hooks(...)) ==
['SessionEnd', 'SessionStart', 'UserPromptSubmit']`. With `PreToolUse` installed, it returns four events. Task 8 Step 4
(1842) runs that file and expects it to pass.
Change: add to Task 8's Files (1714-1715) "Modify: `agent/tests/test_session_end.py:57` (the installed events include
`PreToolUse`)", and add the file to the `git add` at 1848.

**M4. Task 9 leaves the suite red.** `tests/test_mcp.py:21-24` asserts the exact ordered list of the 21 tool names.
Adding `checklist_run` and `checklist_propose` to `TOOLS` breaks it, and Task 9 Step 4 (2095) runs `test_mcp.py`.
Change: add to Task 9's Files (1858-1862) "Modify: `agent/tests/test_mcp.py:21-24` (the list gains `checklist_run`,
`checklist_propose` in `TOOLS` order)", and add the file to the `git add` at 2101.

**M5. A spec requirement has no task: "The reflect list reads this report"** (spec, Renegotiation, The report). The seed's
Reflect items (2406-2413) never mention the report.
Change:
- Add an item to `reflect.md` (9 items, within 12; 104 bytes): "Read `python3 agent/run_agent.py checklists report`
  and propose what it suggests with checklist_propose."
- In `test_the_seed_is_the_spec_s_table` (2320), assert `any('checklists report' in i for i in seed('reflect').items)`.

## Should fix

**S1. The hold can record a hold it never printed** (1679-1687). The worker writes the record and then appends the log
lines. The main thread waits for the whole thread, and on a timeout it sets `abandoned` and prints nothing. Two cases
break this:
- the worker commits just before the main thread times out;
- the commit is done but an append is slow.

Either way the record says held and the digest passed, but no deny was shown. That breaks "a list named but not shown
isn't fired" and spends one of the 3 holds.

Change:
- The worker publishes its result under the small lock, in the same critical section as the record write, and only
  then appends.
- On a timeout, the main thread takes the small lock with `acquire(timeout=max(0, started + HOLD_SECONDS -
  monotonic()))`. It prints a published result; otherwise it sets `abandoned` and prints nothing.
- Test: patch `checklist_firing.append_line` to sleep 1.5 s. The deny still prints, and `holds == 1`.

**S2. `_prune` can delete a live record mid-rewrite** (Ruling 14 at 176-179; Task 6 at 1447).
- `locked_record` rewrites in place with `ftruncate`, then `write`.
- Another session's hook runs `_prune` (`hook.py:491`) and reads without the lock. A file caught empty has no `seen`,
  so `_prune` deletes it.
- The writer then writes to an unlinked inode. The record is lost: `holds`, `fired` (so `enter` lists fire again) and
  `passed` all reset, and a fourth hold becomes possible.

Change:
- `_prune` ages a `.checklists` file without a usable `seen` by its mtime, as it already does for `.watch`
  (`hook.py:289-290`).
- `locked_record` reopens when `os.fstat(fd).st_nlink == 0` after locking.
- Drop "or `_prune` deletes it as damaged" from Ruling 14.
- Test: an empty `.checklists` file with a fresh mtime survives `_prune`.

**S3. A slow session start loses its `start` lists for the whole session** (Task 6 at 1434-1441; Rulings 3 and 7).
- `begin` (which sets `fresh`) runs in the reader thread after `find`. A late thread writes nothing.
- `fresh` is set only at `SessionStart`. So on a cold start that misses 150 ms, Why we build and A session starting
  never fire that session.

Change:
- On a time miss at a `session-start` whose source is in `START_SOURCES`, the main thread records `touch` and `begin`
  under `locked_record(..., monotonic() + 0.05)` beside the miss line.
- Test: `find` sleeps 0.3 s at the start; at the next prompt (fast), the start list shows.

**S4. Ruling 27: keep it, and widen it a little** (215-220; 2299; 2335-2337; 2415).
- It is needed. The Mac pushes with `git -c 'credential.helper=!gh auth git-credential' push https://…` (memory
  `git-push-over-https`), and that holds no `git push`.
- It is within the spec's rules: adding a moment is the one change silence can accept, and the seed is reviewed with
  the branch.
- But `git -C <path> push -u origin x` still matches no moment (checked).

Change:
- Before any push becomes `command git push; command push origin; command push -u origin; command push https://`.
- Add `'git -C /x push -u origin feature'` to the Review Focus 1 cases.
- Task 12 Step 5's post names the moments added beyond the spec's table, so the section 2 verdict accepts them
  explicitly.

**S5. `test_parallel_holds_never_pass_three` depends on timing** (1609-1622). Six holds share one 150 ms window, while
each holds the flock through `render` (with teamlib's first import) and the write. On a loaded runner, a None output
makes `o['hookSpecificOutput']` raise.

Change:
- Render the matching lists before taking the lock (`render` is pure), so the lock covers only due, fit, mark and
  write.
- In the test, monkeypatch `fp.READ_SECONDS` and `fp.HOLD_SECONDS` to 5, so the test pins the cap, not the clock.

**S6. `trust` should default to the ship that acts where the lists are** (Ruling 26 at 213-214; Task 10 at 2129-2137).
- Using the shell's cwd means a person who runs `trust ~/proj/.superyak/checklists` from elsewhere writes the machine
  ship's `trusted.json`. If a project ship claims `~/proj`, its lists stay untrusted.
- Change: default to `acting.acting_home(<the directory holding .superyak>)`, and print the home it changed.

**S7. `trust_checkout` must never raise** (1727-1731, 1836-1838).
- It runs inside `ProjectDock.install`'s `try` (`project_dock.py:252-283`). A raise there rolls back the claim and
  every write, so a full disk or a read-only home would undo the dock.
- Change: catch `OSError` and `ValueError`, print one line, and return False.
- Test: an unwritable home gives one line, and the dock completes.

**S8. Task 12 measures against real ship homes** (2512-2529). The Pi's p50/p95 runs and the Mac's smoke would append
fake firings to the real `~/.superyak/checklists/fired.jsonl`, and `checklists report` would count them as unrun.
Change: run both with `HOME=<scratch>`, a scratch `station.json` and a scratch `trusted.json` that trusts the worktree's
lists.

**S9. Add `hold.main`'s malformed-input test**, mirroring `test_hook.py:283`: stdin `''`, `'not json'`, `'[]'` and
`{"tool_input": {"command": 5}}` each return 0 with empty stdout.

**S10. Task 1's monkeypatch note is incomplete** (357-359).
- `test_hook.py:707` patches `hook.claims.verdict`, as well as the `kind_of` patch the plan names.
- Say that `hook.py` keeps calling `claims.verdict` and `claims.kind_of` through the `claims` module. Moving it to
  `acting` would break that test silently.

**S11. The fuzz test can pass while asserting nothing** (1556-1565). Assert that the 300 commands produced at least one
`deny` and at least one context output.

**S12. One deferred item is missing.** Spec Deferred S2 says each ship retires its own reflect reminder once the hook
fires Reflect. Add it to Task 12 Step 5.

## Nits

- **N1.** Task 1's line ranges (287-289) take in `Refused`, `local_ships`, `check_mode` and `lock_path`, which stay in
  `claims.py`. The name list governs; say so.
- **N2.** `search_dirs` should compare `realpath(cwd)` with `realpath(home)`.
- **N3.** `locked_record`:
  - it must create the sessions folder 0700 (Task 5's test writes into a missing one);
  - it should treat a short `os.write` as a failure.
- **N4.** `render` puts `{path}` outside the fence. Replace non-printables with `?` there too, as Task 3 does for
  notices (745).
- **N5.** `_place` (1442-1445): say it marks `told` only for the notices it showed.
- **N6.** Ruling 20's reason ("Titles go into the header unfenced") is wrong for `render`, which fences the title. Titles
  are unfenced only in `checklists list` and in the proposal.
- **N7.** Unused names:
  - `checklist_fakes.trust_dirs` in Task 11's Interfaces (2277);
  - `tmp_path` and `capsys` in `test_report_writes_nothing` (2187).
- **N8.** `__main__.main(argv=None)` must resolve `argv` before the `hold` dispatch (1484).
- **N9.** Ruling 7 says `/clear` "may keep the session id", but Known limits says it gets a new one. Write "unknown;
  Task 12 confirms".
- **N10.** `_same_hook` ignores `timeout`, so a later change to `HOLD_TIMEOUT` isn't upgraded by a re-dock.
- **N11.** Claude Code's Bash sets `CLAUDE_CODE_SESSION_ID`, and `private_home` doesn't clear it. The new MCP tests set
  or delete it explicitly. A `delenv` in `conftest.private_home` would make every test independent of the session
  running it.

## The rulings

- **Overturn Ruling 2** (M1).
- **Amend:**
  - 3 and 7 (S3);
  - 14 (S2);
  - 26 (S6);
  - 27 (keep; S4).
- **The rest stand.** These are consistent with the spec, or stricter where the spec is silent: 1, 4, 5, 6, 8 to 13,
  15 to 25 and 28 to 30. In particular:
  - Ruling 3's cost (`every` counts from when lists first load) is an honest trade against writing a record in every
    session;
  - Ruling 15 reconciles "a renewal fires nothing" with "due again at the next event";
  - Ruling 29 fixes a real gap (`claims.py` and `project_dock.py` are missing from `only-include` today).

## Proportion

The length is mostly test code, and that code is the behavioural spec for each task: keep it. It is also the seed
wording under review: keep that. Cuts:
- **Task 4 Step 3's `command_matches` body (894-916).** It is a transcript that the tests determine. After M1 it is one
  sentence.
- **Global Constraints (26-133).** About 108 lines re-quote the spec, which the plan tells executors to read. Keep the
  plan-only values: the person-data regexes, 9,500, the all-hands id and the record shape. Point to spec sections for
  the rest (about 70 lines saved).
- **Known limits (229-236).** These repeat Task 12 Step 3; keep one copy.

## Checked and fine

- **Baseline:** 755 passed at 9a756393 (code as at 784a60b).
- **Plan line references:** they match the code.
  - `hook.py`: 16, 66-88, 96, 154-194, 209-258 (219-221, 248-257);
  - `__main__.py`: 5, 73-87, 120-125;
  - `install.py`: 68-79, 84, 94-100, 120-127, 130-160 (150), 355-356, 401-411;
  - `project_dock.py`: 266-267;
  - `mcp.py`: 11-13, 162-171, 374-387 (383), 611-613, 657-661;
  - `station.py`: 21, 40-44.
- **The light path:**
  - `run_agent.py:15` reaches `station` only through `__main__.py:5`, which the plan moves into `build_parser`;
  - teamlib imports no `urllib.request` or `http.client` (`teamlib.py:12-24`), so the probe's lazy-fence assertion is
    sound;
  - `fence_external` defuses three backticks and `[team] from x:` line starts (`teamlib.py:458-463`), and
    `limit=FILE_BYTES` avoids its 2,000-character cut.
- **Install and undock:**
  - `remove_hooks` walks `HOOK_EVENTS` (`install.py:172`), so undock removes the hold, and the test keeps the person's
    own entries;
  - D9 holds: today's `main()` sends anything but `hook` to `parse_args`, which exits 2, and the guard turns that into
    0.
- **The deny-only contract:** `decide`'s output shape and the past-cap `additionalContext` follow spec rev 3 (R2).
  Nothing emits `allow`, `ask` or `updatedInput`, and subagents and `SUPERYAK_RUN` are excluded.
- **The cap of 3 under parallel calls:** read, decide and commit happen in one flock hold. Task 5's multi-process
  writer test pins `locked_record`; separate opens conflict under flock even inside one process.
- **Starvation:** I simulated the plan's due rules (Ruling 17) over a day of 10-minute events. Each of Why we build,
  Each hour and Reflect shows in every period.
- **Budget:**
  - `_place` sits after the version line and before the board lines; at a prompt it follows the law and the messages
    (`hook.py:240-257`);
  - the law is never cut;
  - the Review Focus 5 arithmetic holds for a 9,200-character law.
- **Trust:**
  - per-directory realpaths;
  - a worktree is untrusted, and its byte-identical copies are silent;
  - `trust` needs a TTY;
  - the mode and owner checks are there;
  - a project dock trusts only the Superyak checkout.
- **The seed:**
  - every item is at most 187 bytes;
  - every `see:` is at most 112 bytes and matches a heading slug in `docs/checklists.md` at 127d285;
  - Why we build's body is 652 bytes;
  - `.superyak/` isn't gitignored;
  - the `checklists` merge adds only `docs/checklists.md` and `docs/goals.md`, on 60dd851 (an ancestor of HEAD).
- **`claim`:** it fires only when `board == 'open'`, and the fake station returns `board` for an item's key
  (`conftest.py:374-376`).
- **Coverage:** every other spec section and every bullet of the spec's Tests maps to a task and a test.
- **Interfaces:** each task's Interfaces block matches what later tasks consume (names, signatures, return shapes).
- **Review Focus:** each of the five is pinned by a test in its owning task. Review Focus 3 is pinned for the hold
  only by `find` until M2.
