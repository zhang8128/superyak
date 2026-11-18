# The fresh reader's verdict on the report of the whole stack's test

Kept whole, as the reader gave it on 2026-11-17, so that the room's page does not have to carry it. The reader
was a fresh one of the other model family (the team's worker w87), reading the report at 87e8ad9d against the
run's records. One thing is changed from its words: the link in its second paragraph named a path on the
lead's machine and is given here as the report's path in the repository. Its line numbers are of the report at
87e8ad9d. Every named change is made in a3fc4127 and listed at the report's end.

---

push with named changes

Read-only sandbox; no files changed. Reviewed the report at 87e8ad9d (`docs/reports/2026-11-17-v2-the-whole-stack-tested.md`). Line numbers below refer to it.

1. **Lines 13–15, 105–115: the probes did not run with “no tests.”**  
   `scripts/describe-probe.py` builds their bases from the true parent without removing its existing tests. It checks that the **new test blobs** are absent. The walks confirm existing tests were available: at 37a887d3, `test_chat_paging.py` is named alongside the first source file; at 9490f597, `test_federation_outcomes.py` is named before any source file.

   **Smallest change:** say “with the item’s new tests withheld; existing parent tests remained available,” and carry that qualification into the conclusions about description-first work.

2. **Lines 13–19, 137–138, 221–228 and 247–249: quick first naming does not establish that finding is finished or bound what routes could save.**  
   I reproduce sixteen of sixteen **reference-file occurrences** named and changed, covering twelve distinct files. But 10–22 seconds describes entry to the first reference file. `__main__.py` first appears at 40.871 seconds and `inbox.py` at 80.554 seconds. Naming a file also does not establish understanding it, finding every dependency, or completing discovery. Four of the five replays with passing controls failed.

   The reading counts measure later file recall, not saved time. Consequently “little to carry here” and “seconds to shorten” exceed the measurements. Likewise, line 173’s assertion that real walks *would* know more is stronger than counting additional named files establishes.

   **Smallest change:** consistently say “first reference-changed file,” give the complete-file range through approximately 81 seconds, and replace the claimed limit on usefulness with “these observations establish no time saving or upper bound on one.” The decision against an experiment can remain an engineering judgment.

   An equally consistent reading is that familiar descriptions and existing tests supplied quick entry, while sparse history and similar candidate lists limited the offline route comparison. That leaves help after initial entry unresolved.

3. **Lines 93–99: remove the rehearsal’s probability inference and resulting design prescription.**  
   The first turn really was slowest at all three items. However, \(1/27=(1/3)^3\) requires independent, exchangeable duration ranks. “Place did nothing” alone does not supply those assumptions: arms, prompts, generated work and shared operating conditions differ.

   The runs also occur sequentially, leaving changing load and possible cache or tool warmness uncontrolled. The first traces have different step counts: 15 against 14/14, 20 against 18/17, and 13 against 11/13. These records identify no mechanism.

   More decisively, the rehearsal spec says nothing is tested for a difference and its numbers enter no later sizing or reading. The order already balances **every arm across every position**.

   **Smallest change:** retain the descriptive first-slowest observation; delete “one time in 27” and the instruction to discard first turns or balance positions. State that positions were already balanced and the cause is unknown.

4. **Lines 117–120 and 232–235: distinguish the literal selection filter from descriptions that conceal the place.**  
   The task messages provide recognizable cues despite passing the filter: “Owner trust” points toward `owner_trust.py`; “Chat paging” toward `chats.py`; `could_hold` names a symbol. These are materially different from descriptions offering no location clues.

   Both selectors also require at least eight message words. Their pool consists of small, already merged Python changes that change tests, satisfy the item-maker’s failing-to-passing rule, and were left out by rule 5. It excludes larger changes, deletions, renames, most other components and unresolved work.

   **Smallest change:** state that the filter excludes literal filenames/stem tokens while allowing component and symbol clues; add the omitted selection restrictions and their scope to Limits.

5. **Lines 16–17, 204–210 and 227–228: narrow the reading-work conclusions to their measured scores.**  
   The pooled own/other program means reproduce, but “no difference was seen” conceals opposing subgroup results. At the first ten files:

   - Fifteen workers: own-program history **0.183**, other-program history **0.373**.
   - Thirty-three workers: own **0.336**, other **0.255**.
   - Pooled: own **0.288**, other **0.292**.

   Roles, walk lengths and selected histories are not controlled. Nor does the route comparison establish that sequence contains no useful information: thirty of forty-three comparisons at five files tie.

   **Smallest change:** describe the close **pooled mean recall**, show or acknowledge the subgroup reversal, and replace general claims about programs and roads with observations about these offline lists. Preserve the existing statement that reader savings were not tested.

6. **Lines 149–159: some repetition counts cannot be reconstructed from the supplied records.**  
   I confirm the five passing-control items, five failing-control items, and the initial replay outcomes. However:

   - Each successful replay item has one supplied `turns.json` record; the summary says three successful replays.
   - For 7c6cda37, the supplied evidence contains two failed-reference receipts: the initial control and `repeats/7c6cda3733-r2/reference.json`. The summary says three.

   **Smallest change:** supply the missing receipts, or distinguish independently documented counts from the operator’s reported repetitions. I asked the lead where the remaining receipts were; no answer arrived before this verdict.

7. **Lines 62–68 and 100–101: make the protocol’s complete record reachable from the report.**  
   The raw pass report contains fields required by rehearsal sections 5–6 that the published narrative omits: unknown steps, tokens and completeness, per-turn start/end/load, complete block statistics, answer sizes and the full teaching-list hash.

   **Smallest change:** include or link a durable, scrubbed copy of the pass report/JSON. For example, the three answers are each **1,327 bytes**; route blocks each contain three places and three roads, shuffled blocks three places and no roads; each has zero gone and one changed path. Those required measurements should remain accessible.

8. **Smaller numerical and wording corrections:**

   - **Line 88:** README is tied at eight of eight history turns with `AGENTS.md` and `.yak-check/check.py`. Say these share the highest count rather than claiming README would rank first.
   - **Line 183:** median eight extra files applies to the forty-nine-worker cohort; the combined sixty-eight-worker cohort has median six. Name the cohort.
   - **Lines 211–212:** name the recency cohort and denominator. With eligible targets in the combined ordered rows, I get **115/167 = 68.9%** within the preceding five rows. **53/70 = 75.7%** arises in the filtered titled-worker cohort.
   - **Line 42:** 64–179 seconds describes the eight retained history turns. The thrown-away turn took **59.560 seconds**; make the exclusion explicit.
   - **Lines 250–251:** retained check output *could help explain* failures. One retained line is not guaranteed to explain them.

The remaining table arithmetic reproduces:

- **Rehearsal:** eighteen passed turns; twenty-six passed and verified screen receipts; eight teaching turns; all nine printed timing/step/first-naming rows match. Seeded arm orders reproduce independently. Block lengths and hashes agree with turn records. Route/nothing ratios are **1.182, 1.238, 0.896**; shuffled/nothing **1.192, 1.110, 0.945**.
- **Probes:** all ten rows’ file occurrences, times, changed-source sets, step counts and last-step times match. No extra source file was changed.
- **Description-history table:** **22/40, all 12**; **15/40, all 4**; **11/40, all 3**. The 2,000-draw mean is **8.2555**, correctly printed as 8.3.
- **Reading work:** the four history-selection triples reproduce as **.170/.242/.361**, **.183/.268/.381**, **.248/.334/.421**, **.338/.418/.477**. The thirty-nine-worker triples reproduce as **.202/.338/.397**, **.295/.423/.518**, **.221/.334/.486**. The pooled program rows also reproduce.
- **Store owner’s row:** it agrees with the quoted posts and is correctly identified as another ship’s measure. I independently reproduce its places baseline, **.284/.413/.511**; I cannot independently reproduce its route scores.

“No fault was found” is supported for the documented successful execution and metadata comparisons. It should retain that scope.

I could not independently check the original logs and their extraction; original pinned binaries/item repository; candidate counts of twenty-eight and eight; the 38–54-file range; the previous night’s 59-second observation; the two outside-jail checks; searching’s one-sixth command share; the store’s route calculation or the lead’s short-road calculation. The 297-cell check is supported by the store’s recorded receipt, not a fresh independent replay.

I found no private words or absolute machine paths in the report.

---

# The fresh reader's verdict on the third probe's section

Kept whole, as the reader gave it on 2026-11-17. A second fresh reader of the other model family (the team's
worker w90), reading the added section at dc3dfc0f against the probe's records. Its line numbers are of the
report at dc3dfc0f. Nothing in its words is changed.

---

push with named changes

Line numbers refer to the report at dc3dfc0f.

1. **Lines 256–258: failed replays do not establish task/test gaps.** The five replay records show four failures, whose causes remain undiagnosed. A task/test mismatch, an implementation mistake and missed discovery remain possible. At 6f57b4cb, incomplete propagation of an understood repair is also consistent with the missing changes; the earlier turn’s replay failed too.

   **Smallest change:** replace the causal conclusion with: “These failures are undiagnosed. Held-back tests may require unstated details, but these records do not distinguish that from implementation or discovery failures.”

2. **Lines 205–206 and 262–263: preserve the earlier reader’s uncertainty and scope the naming claim.** Finding 2 of the earlier verdict presents tests and familiar descriptions as an “equally consistent reading,” not established causes of quick entry. The rewritten tasks remove identifiers, while source names and documentation remain; every walk names `README.md`.

   **Smallest change:** say the reader “suggested two possible aids,” and replace “the project’s own naming taken away” with “the task rewritten without project identifiers.” The closing suggestion about earlier work is appropriately labelled as judgement; these observations do not test it.

3. **Lines 225–226 and 252–255: describe the changed check.** In `describe-probe.py`, the earlier check requires a change under `peer/superyak_peer`. The new check accepts any tracked change outside `TASK.md` and `.yak-check`, including tests or documentation. That is another difference between paired turns. All five actually changed source, so it does not alter the table.

   **Smallest change:** add that difference to the conditions described. Say “component folder” rather than “a folder”: the check still names `.yak-check`.

4. **Lines 338–347: the addition leaves Limits contradictory.** They still say ten probe turns, user-word tasks untried, and parent tests present in the probes’ sandboxes.

   **Smallest change:** count fifteen probe turns and restrict the commit-message and parent-test statements to probes 1–2. Name the five rewritten, test-withheld turns separately.

5. **Lines 248–250: distinguish file occurrences and source changes.** The references contain ten file occurrences across nine distinct paths: `chats.py` occurs twice. Eight occurrences were named and changed. At 6f57b4cb, `chats.py` was the only source file changed; the turn also added `peer/tests/test_message_lookup.py`.

   **Smallest change:** say “ten reference-file occurrences, covering nine distinct files,” and “changed `chats.py` alone among source files.”

All table cells otherwise reproduce from the walks and replay records, including the fourth-to-seventh-step range. I confirm three verified passing controls per item, one replay per new turn, 31–130 task words, and parent test inventories of 45, 83, 54, 45 and 90 blobs. No withheld test blob or parent test path appears in the walks, and I found no sign of earlier Git history. The script constructs parentless bases and checks withheld objects before each turn.

Both final task-reader changes were made: the lessons task separates task actions from reservation actions and covers any holder; the connector task says “explaining why.” All five task hashes match the `TASK.md` blobs named in the walks. I also regenerated the fifteen replacement candidates from the supplied ordered list and original commit messages/source diffs, matching the selection record.

I found no private words or absolute machine paths in the added section or verdict file.

I could not freshly inspect the synthetic item/turn Git object stores or worker patches, or determine why the four replays failed. Withholding verification rests on the supplied records and script, corroborated by the walks and original parent trees. No model, replay or heavy check was run; no file was changed.

---

# The fresh reader's verdict on the correction about references that failed in the jail

Kept whole, as the reader gave it on 2026-11-17. A third fresh reader of the other model family (the team's
worker w91), reading the correction at 61962697 against the records. Its line numbers are of the report at
61962697. Two links in its words named a path on the lead's machine and are given here as "Report, line N".
The folders it names (`depths/`, `run-5/`) are in the evidence kept with the read, not in the repository.

---

push with named changes

1. **Report, line 201: withdraw the depth explanation.** New `depths/` receipts show 7c6cda37 passing with padded directory names at lengths 90, 108 and 126, but failing with a full-commit-ID name at 126. Base, check, reference tree and room binary match. At 79aaa586, `run-5/79aaa58602.txt` directly shows the test’s `[0-9a-f]{32}` assertion matching the commit ID in a printed path: one failure, 22 passes. That test function is identical at all three commits. Replace “That is why” and the depth attribution with this mechanism, directly observed at 79aaa586 and inferred at the other two. Keep trials item-specific: only 7c6cda37 received the padded-directory trials.

2. **Report, line 393: revise the takeaway.** Distinguish the socket-length failure from the hexadecimal-name failure. The pilot and pass scripts themselves include full commit IDs in turn-directory names (`pilot_driver.py:393`, `pass_driver.py:122`), so this extends beyond the lead’s directory choice. A shorter path alone is not the established remedy for these three items.

The recount holds:

- The first four references passed three of three, including the newly supplied third-probe receipts; d9860589 passed once.
- The three affected references each failed three original controls and passed three short controls.
- 5b0c8376 failed three original controls and one short control; 113d188e failed four original controls and one short control.
- Replays support **eight judgeable items, two successes and six failures**. Short-directory replays agree with the original outcomes.

The socket and network diagnoses hold. Rule 9 permits the diagnostic hand-in: the store receives tracked-file metadata and verdicts; the file’s contents remain outside it. I found no stale denominator elsewhere or private names or machine paths in the changed lines.

Could not check: failing output at 027834bf or 7c6cda37, or a rewritten report. No model, test suite or heavy run was executed; no file changed.

---

# The fresh reader's verdict on the correction about the socket's path

Kept whole, as the reader gave it on 2026-11-18. A fourth fresh reader of the other model family (the
team's worker w98), reading the correction at bd894772 against the records. Its line numbers are of the
report at bd894772. The files it names (`probe-5b0c8376.txt`, `tests-short-home-5b0c8376.txt`,
`outside-the-jail.txt`) are in the evidence kept with the read, not in the repository.

---

push with named changes

1. Report lines 201–202: “both places a jailed run may write” is too broad. `probe-5b0c8376.txt` supports the two tested directories on macOS. `v2/crates/turn/src/jail.rs:840` and `:904` also allow writes to two null devices; its lines 30–32 describe additional writable directories on Linux. Smallest change: “So, on macOS, the jail refuses a Unix socket’s bind in both writable directories.”

2. Report line 196: distinguish field size from usable pathname length. The newly appended `outside-the-jail.txt` records a 104-byte field, but Python 3.15 binds a 103-byte name and rejects 104 bytes with `errno None`. Smallest change: replace the ceiling clause with “the field for a Unix socket’s path on macOS is 104 bytes”, or omit it. Those boundary trials do not establish the kit’s Python 3.13 boundary.

3. Report lines 480–481: “What follows now” still presents the superseded socket-path diagnosis as current. `probe-5b0c8376.txt` and `tests-short-home-5b0c8376.txt` establish the correction. Preserve the historical review by using past tense and “the then-apparent socket-path failure”.

The central correction is supported. The added original diagnostic records TMPDIR 118; the short-home record shows 82 characters, 17 passes and 12 permission errors. The probe shows short relative binds refused in both directories while its pair and file controls succeed. `outside-the-jail.txt` supports the wording about no system error number.

The intent is consistent with the complete macOS profile: `jail.rs:854` denies by default, the generator adds no network allowance, and `:1433–1434` explicitly tests that absence. “Whatever the path’s length” is therefore a policy inference supported by these observations, not an exhaustive measurement. No table or outcome-count change is needed. No private words or machine paths appear in the changed lines.

I did not independently verify the spec’s withdrawal history. These records do not test the other twenty census items, Linux, or a connection to an existing bound socket. I ran no model or runtime test. The evidence README’s provenance correction was verified during this read.

---

# The fresh reader's verdict on the section "Why the changes failed their held-back tests"

Kept whole, as the reader gave it on 2026-11-18. A fifth fresh reader of the other model family (the
team's worker w99), reading the section at 01f032c5. It was asked to sort the ten failures itself from
the outputs before opening the section, and its sorting comes first. Its line numbers are of the report
at 01f032c5. The files it names under `outputs/`, `tasks/` and `changes/` are in the evidence kept with
the read, not in the repository.

---

push with named changes

Blind sorting, recorded before opening the report:

1. SQL inspection/export surface (four changes): probe1-37a887d3d7 and probe3-37a887d3d7 each pass 15 tests and fail one at importing SINCE_SQL. probe2-6f57b4cb36 and probe3-6f57b4cb36 each pass 16 and fail two at importing page_rows_sql and replies_sql. The failed tests do not get as far as checking their SQL/index behaviour.

2. Notice selection/identity (two changes): probe1-9490f59750 and probe3-9490f59750 each pass 33 and fail two because selecting notices with push-failing- or pull-quiet- yields none. Both patches add day-old episode notices with other prefixes. This explains a selection mismatch; it does not establish all timing, pairing, recovery, or sanitising behaviour.

3. Call and return contracts (two changes): probe2-d98605894d fails nine tests before entering station_imprint_use_begin because its positional interface differs, and two command tests return 1 with No such imprint instead of success/refusal exits. The method name exists in the turn. probe2-027834bf0e passes 55 and fails nine: six expect an empty list where settlement returns None; two expect revocation result keys/counts absent from its success result; one gets status 409 with a different reason. These are interface/observable-result mismatches, and can mask later behaviour.

4. Refusal wording (one change): probe3-317a6e0bd2 passes 23 and fails two because Problem is raised with other text than the regex expects. Those two refusals happened; later assertions remain untested.

5. Refusal behaviour (one change): probe1-79aaa58602 passes 22 and fails one because renewal does not raise the expected Problem for a trust-made contact. The task calls for shared owner checks; its patch adds checks, but the tested refusal is missing.

Totals across these ten outputs: 33 failed and 228 passed, 261 tests. The two controls each give exit 0 and 35 passed. These groups describe the first observed obstacle, not a complete correctness verdict.

Findings, most serious first. Report line numbers refer to 01f032c5; evidence paths are relative to the supplied evidence directory.

1. **Withdraw the bound on what an offer could change — report 359–363.** Neither a static name check nor these unoffered turns establishes that “no offer could have moved them far.” There is a concrete counterexample to the premise: at 027834bf^, docs/superpowers/plans/2026-11-02-owner-trust.md:156–157 already specifies settle_owner_trust returning list[str] and revoke_owner_trust returning grant_id/held. Eight of that change’s nine first failures concern those pre-existing contracts. At d9860589^, engram/docs/superpowers/plans/2026-10-25-store-imprint.md:3630–3635 already specifies the exact positional call shape and the command’s success/refusal outputs; its examples at 3642 and 3653 match the failing calls. A prior note or route could carry these contracts. Evidence: outputs/probe2-027834bf0e.txt, tasks/probe2-027834bf0e.TASK.md, changes/probe2-027834bf0e.turn.patch, and those parent-version plans. Smallest change: replace the paragraph’s inference with “These pass rates mix interface incompatibilities with behavioural failures; they do not separate those causes or measure what an offer could change.” Keep the recommendation to specify interfaces or use implementation-independent behavioural tests. This does not establish that an offer would help.

2. **Keep first obstacles distinct from complete diagnoses — report 329, 354–357, 365–368 and 429–432.** My blind groups separate call/return contracts from wording. Grouping them together is permissible as an explicit description of first obstacles; “nine spelling failures, one behavioural omission” is too strong as an explanation of the implementations. At d9860589, both command tests return 1 with “No such imprint”: its own command calls its own method successfully, but that method requires the full id and omits prefix resolution. At probe3-6f57b4cb, the patch leaves reply/source lookups unchanged while tests stop before inspecting their query plans. At 027834bf, six tests stop at the preliminary empty-result assertion before setting up the owner failure. Evidence: outputs/probe2-d98605894d.txt, changes/probe2-d98605894d.turn.patch, changes/probe3-6f57b4cb36.turn.patch, outputs/probe3-6f57b4cb36.txt, and outputs/probe2-027834bf0e.txt. I also checked the corresponding tests’ committed source after recording the blind sorting. Smallest change: say “first observed failures” in the judgement and summary; add the CLI’s actual message to its row; add to the limits that later behaviour was not established and these diagnostic runs were macOS only. The same caution applies beneath the imports at 37a887d3, the notice filters at 9490f597, and the early wording checks at 317a6e0b.

3. **Correct which name the reference adds — report 184.** events_kind_room_id already exists at 37a887d3^:peer/superyak_peer/inbox.py:31. The supplied changes/probe1-37a887d3d7.reference.patch itself calls it the existing index; SINCE_SQL is the newly exported name. Smallest change: “The tests import the reference’s new SINCE_SQL to inspect use of the existing events_kind_room_id index.” This changes no count.

4. **Put the historical review note in the past tense — report 523–524.** It still says the four failures “are called undiagnosed,” under “all five are made here,” although report 298–300 now describes that as the earlier state. Evidence: outputs/probe3-{37a887d3d7,9490f59750,317a6e0bd2,6f57b4cb36}.txt. Smallest change: “The four failed replays were initially called undiagnosed; the later section now records their first failures.”

No numerical correction is needed. Every table row agrees with outputs/ and tally.txt: 228/261, 228/250 without d9860589, and the 33 split 6, 4, 2, 9, 2, 9, 1. The corrected 027834bf split is six/two/one. Seven changes at four items account for the six checked strings.

I independently checked all six strings in tasks/ and both patches: task/turn/reference counts are 0/0/2 for SINCE_SQL, page_rows_sql and replies_sql, and 0/0/1 for push-failing-, pull-quiet- and “has open board items,” at every relevant change. Absence of those literals does not imply absence of the operation: the turns use inline SQL, other episode-id prefixes, or another refusal wording. Whether the SQL and notices meet all requirements remains open.

The patch claims about the alternate notice ids, the shared method name, three source files versus one, and the sixteen-word subject line check out. Both controls give pytest exit 0 and 35 passed; run.txt also shows apply exit 0 for every patch. They validate the diagnostic’s pass output, not the room’s hand-in verdict, which is false for both controls as disclosed. The other changed retrospective sentences and the judge-design addition are consistent with this evidence once the qualifications above are made. I found no private names or machine paths in the changed report lines.

Not checked: another run of any change, execution after adapting names/interfaces, complete behavioural correctness, whether reading either plan would improve a turn’s result, or Linux. No files changed and no evidence program or test executed.
