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
