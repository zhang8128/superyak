# Review: Compression never promotes unused prompt captures

Spec: `docs/superpowers/specs/2026-10-27-compress-no-auto-promotion-design.md` (branch `compress-no-auto`, 02b112a).
Reviewer: a fresh agent approving in Andy's place under station law section 3. I took no part in writing the spec.
Method: I read the spec, the amended code and the 2026-03-26 rework spec, and ran read-only counts on the Mac's store
(`graph.db` and `cold.db` opened with `mode=ro`, schema 28, counts only).

**Verdict: APPROVE WITH CHANGES**

The rules are right and close the hole for `auto_compress`. Filtering where episodes are read is the right place,
and a builder can plan from the spec. All of the spec's measurements reproduce exactly. Three things must change
before building. Two claims about current code are wrong: what `scope="refine"` does, and what "used" means for a
recall. The spec also promises that every existing test passes unchanged, which one startup test cannot do.

## Must fix

1. **`scope="refine"` doesn't rewrite anything, and on the Mac no semantics qualify for it.**
   - Evidence, rewriting: `_refine_clusters` (compress.py:1429-1467) builds clusters with `action: "reinforce"`. The
     reinforce branch of `_commit_state` (compress.py:529-533) calls `reinforce_semantic(semantic_id, ids)`
     (storage.py:1118-1129), which only raises confidence and adds source links. The summary's `content` is
     validated (compress.py:805-808) and then ignored. If a model overrides the action to `new`, it gets a second
     semantic, and the joined copy stays as it was.
   - Evidence, the Mac: `SELECT count(*) FROM semantics WHERE content LIKE '%--- %' AND contradicted_by IS NULL`
     returns 0. All 234 copies come from 1-3 episode clusters.
   - Refine also shows the model every source episode of a joined semantic, unused captures included. That
     contradicts Rule 2 as worded.
   - Change: replace the Design bullet at lines 68-69 with:
     > `scope="refine"` is unchanged and outside these rules. It re-presents the sources of existing `" --- "`
     > semantics for a reinforce, which bumps confidence and never rewrites content. It ignores `auto`. On the Mac
     > no semantic qualifies.

     In "Existing copies", delete "`compress(scope="refine")` already lets a model rewrite the joined ones."

2. **"Used" is evidence about a whole recall, not about one episode. Rule 2, D3 and the Goal claim more than the
   code records.**
   - Evidence, the tool: `log_outcome(recall_id, used)` writes one outcome per recall (server.py:2624-2633,
     storage.py:1704-1709).
   - Evidence, the sleep hook: it marks the whole recall `used: auto: cited` when any one target id is cited later
     (hooks/sleep.py:116-141). D3 says "a later act cited the result". It cited *a* result.
   - Evidence, lane-filtered recalls: the log row is rewritten with every delivered id (server.py:2551-2560). That
     includes uninvited random draws and resonance pulls appended at server.py:2416, 2484 and 2502, so a capture
     that only arrived as a random draw is credited too. Recalls without a lane log only the matched top-k
     (server.py:2371-2384).
   - So a capture delivered next to the result that was actually used still gets in. The model's review in
     `compress()` is the real gate.
   - Change:
     - Rule 2: add "Evidence is per recall. Every episode the recall delivered and logged in `target_ids` counts as
       used, and the model's summary or discard in `compress_commit` is the gate."
     - D3: replace "positive evidence: a later act cited the result" with "positive evidence that the recall
       mattered; the hook marks the whole recall when any of its results is cited".
     - Goal: "only after a recall that returned it was logged used".

3. **The spec says the existing startup-maintenance tests pass unchanged. One of them can't.**
   - Evidence: `test_startup_auto_compress_skips_knowledge_feeds` monkeypatches
     `get_uncompressed_episodes` with `lambda: [{"id": "x"}]` (tests/test_startup_maintenance.py:132). Calling it
     with `auto="none"` raises `TypeError`. The step's `report.step` records the error, and the assertion
     `steps[0]["pending"] == 1` fails.
   - Change: replace the last Tests bullet with "Existing tests pass unchanged except
     `test_startup_auto_compress_skips_knowledge_feeds`, whose stub becomes `lambda **_: [{"id": "x"}]`."

## Should fix

1. **Say how NULL sources are handled, and pin it with a test.**
   - On the Mac, 646 of 1,046 episodes have `source IS NULL`. A literal `source != 'auto'` drops every one of them
     from compression without any error.
   - Change: in the Design, write the filter as `coalesce(source, '') <> 'auto'`.
   - Add a test to the `get_uncompressed_episodes` bullet: "`"none"` and `"used"` include NULL-source and
     other-source episodes."
   - Existing tests would probably catch this mistake, but only indirectly.

2. **`_promote_singletons` is still a no-model path that copies text word for word.**
   - The path: the model's `compress_commit` re-lanes a used capture to personal (compress.py:508-510). The
     `mark_core` tool, which only refuses work-lane episodes (server.py:3050-3056), then marks it core. If no
     semantic links it, because `_filter_relevant_sources` and the multi-link step can both leave it out, the
     next commit copies it verbatim with `auto_generated=True` (compress.py:1218-1262). That commit can be an
     `auto_compress` one.
   - Today 0 captures are core on the Mac, so this is a narrow residual.
   - Change: add `AND coalesce(e.source, '') <> 'auto'` to the `_promote_singletons` query, and add a test that a
     core, unlinked auto episode isn't promoted. If you'd rather keep it, name it in Non-goals as an accepted
     residual.

3. **Name the change in how often the commit-time sweeps run.**
   - `auto_compress` returns before `commit` when there are no clusters (compress.py:838-844). Singleton
     promotion, the instinct-creation check and instinct co-firing cluster re-derivation only run inside commit
     (compress.py:696-725), and nothing else calls `derive_clusters` or `seed_clusters`.
   - Today the nudge hook leaves a capture pending at almost every start, so these sweeps run at almost every
     start. On the Mac, 31 of the 51 days since 2026-09-01 created only auto episodes. After this change those
     starts skip all three sweeps.
   - The Non-goals line says these are "unchanged". Add one sentence: "they now run only when a non-auto episode
     (or, through `compress()`, a used one) is compressed". The alternative is to decide to run them anyway.

4. **Say what happens to the knowledge-graph feed.**
   - The model path feeds every episode in a committed cluster to Graphiti as `episode_body` (compress.py:623,
     knowledge.py:338-341). A used capture's raw text therefore reaches the graph verbatim, not as the model's
     summary.
   - The change also stops a feed that happens today. The served process's remember-threshold `auto_compress`
     (server.py:1919-1927) feeds captures with background feeds on. Only startup discards its feeds.
   - Change: say that a used capture's text reaches the local graph as an episode body and that this is
     accepted. The alternative is to drop `source='auto'` episodes from `knowledge_feeds`.

5. **Pin the `memory_log` shape end to end.**
   - Every planned "used" test can be written with hand-inserted `memory_log` rows. Such tests wouldn't notice if
     the shape that `recall`, `log_outcome` and the lane-filter UPDATE actually write drifted.
   - Add one server-level test: a real `recall(lane="work")` returns an auto episode, then
     `log_outcome(recall_id, True)`, then the `compress` tool offers it. Before `log_outcome`, it doesn't.

6. **Correct the wording of the `scope="full"` test.**
   - Change it to: "after `scope="full"`, unused auto episodes stay uncompressed and used ones are offered".

## Nits

- **Rule 3:** `guarded_prune` and `evaluate_prune` also require `compressed = 1` (persistence.py:274-277). Mention
  them next to `prune_decayed`, because with `[persistence] enabled` they replace it (server.py:1176-1182).
- **Test location:** the startup test belongs in `tests/test_startup_maintenance.py`, not the two files the Tests
  header names.
- **`remember(source="auto")`:** the filter keys on the source string, so a deliberately remembered episode with
  that source is treated as a capture. Say so, or reserve the value.
- **Malformed JSON:** `json_each` raises on malformed JSON. Every writer uses `json.dumps`, and 0 rows are invalid
  on the Mac, so a `json_valid(m.target_ids)` guard is optional hardening.
- **The `compress` tool's output:** it emits only `id` and `content` (server.py:3003-3006). Adding `source` would
  tell the reviewing model which episodes are a person's raw prompts, which serves D2.
- **Deploy:** "Rollback: revert" should say plainly that a revert copies every waiting capture into semantics at
  the next start. That is the leak again, all at once.
- **Unverifiable here:** "491 capture ids" and "the imprint already excludes them by id". No imprint code is in
  this repository. 260 captures plus 234 copies is 494, which is close.

## Checked and fine

- The `auto_compress` lines (compress.py:827-869) and its three content rules (1 episode, centroid-nearest for 2-3,
  MMR k=3 joined by `" --- "`) match the spec.
- The startup call (server.py:1080-1087) and the remember threshold (server.py:1914-1923, default 10 at
  config.py:42) match.
- The nudge capture (hooks/nudge.py:506-537) stores prompts of 50+ characters that are below 0.65 similarity to the
  3 nearest episodes, as `source='auto'` and `lane='work'` with `compressed` defaulting to 0.
- The nudge inline prune predicate (hooks/nudge.py:552-555) is exactly as quoted, and it doesn't depend on
  `compressed`.
- `prune_decayed` selects only `compressed = 1 AND core = 0 AND dormant = 0` (storage.py:783-785).
- `apply_decay` covers uncompressed episodes too (storage.py:683), so "decay as today" holds.
- I reproduced every measured number:
  - 260 captures, all compressed.
  - 315 semantics, 280 of them auto-generated.
  - 234 verbatim copies, all in the work lane.
  - 164 semantics whose sources are all captures.
  - 7,689 log rows, 550 of them recalls, 64 logged used.
  - 0 captures in a used recall, while 29 captures appear in some recall.
  - Schema 28. The used-ids query took 0.18 ms here.
- `idx_memory_log_event_type` exists (migrations/002_v3_layers.sql:62), and the query plan uses it.
- Nothing deletes from `memory_log`, so the "used" evidence doesn't expire.
- `target_ids` only ever holds delivered ids, never non-delivered candidates: either `scored[:max_results]`, or after
  the lane filter the delivered set. The category re-rank is disabled by default and only re-orders.
- `outcome LIKE 'used%'` can't match `not_used…` because the pattern is anchored at the start. Notes appended after
  `used: ` still match. The Mac's recall outcomes are exactly 64 `used%`, 16 `not_used%`, 470 NULL and 0 others.
- The only other writers of `event_type='recall'` (server.py:2099, 2178) are instinct recalls, so they never hold
  episode ids.
- Nothing else reads `compressed`: not status, reflect, wake, maintenance, cohesion or sharing. The only readers are
  startup, the two prune paths and the calibrate projection (calibrate.py:102), which is consistent.
- `_session_episode_count` doesn't interact: nudge inserts bypass `remember()`, and an `auto_compress` that finds
  nothing still resets the counter.
- The existing tests that expect every episode to end up compressed (test_compression.py:498, test_server.py:662,
  test_integration.py:78/95) use NULL-source episodes, so they're unaffected. The MagicMock storage in
  test_knowledge.py:472 accepts the new argument.
- Filtering before clustering covers every text- and link-producing step that is keyed on a cluster:
  centroid/MMR text, reinforce, multi-link over processed episodes only (compress.py:685-694), the
  compression-time sheaf gate (it partitions filtered clusters) and the knowledge feed.
- `scope="full"` resets and then clusters under the filter, which closes that path. It also deletes the existing
  copies as a side effect of its existing behavior.
- The sheaf sleep pass distills peers through Ollama, or queues them, and never copies text verbatim
  (sheaf.py:337-356). It only reaches captures that are already sources of existing copies, so it belongs under
  "Existing copies".
- Instinct formation skips the work lane (compress.py:1094-1095), and all 260 captures are in the work lane.
- Genome sync copies only `core >= 2` episodes (federation.py:175). The `mark_core` tool refuses the work lane, and
  0 captures are core on the Mac.
- Lane re-labelling happens only in `compress_commit`'s override (compress.py:508-510), which is the model path.
- The lighthouse daemon serves only memories that were explicitly shared (lighthouse_daemon.py:6-7, 54).
- `cold.db` holds 0 captures, and with this change uncompressed captures can never be moved there.
- No migration is needed: every table and index the filter uses already exists.

## Re-check of revision 2

Revision: 944976d. I ran `git diff 02b112a 944976d -- engram/docs/superpowers/specs/` and checked each change
against the code. Everything was read-only. The only new store fact is a SQLite in-memory check of the
`json_valid` guard.

**Verdict: APPROVE WITH CHANGES.** Every finding was applied, and Rules 5 and 6 match the code at the lines they
cite. Nothing blocks planning or building. One Deploy instruction is newly wrong, and it must be corrected before
merge because following it would not protect the captures. Two smaller sentences are newly inaccurate.

### Findings from the first review

| Finding | Status | Note |
|---|---|---|
| Must 1, refine | Applied | Moved to Non-goals. The reinforce-only claim (compress.py:529-533, storage.py:1118-1129) and "nothing on the Mac" are correct. The refine sentence is gone from Existing copies. |
| Must 2, per-recall evidence | Applied | The Goal, Rule 2 and D3 now say the evidence is per recall and that the model's review is the gate. The false "cited the result" is gone. |
| Must 3, startup stub | Applied | `lambda **_: [{"id": "x"}]` accepts `auto="none"`. |
| Should 1, NULL sources | Applied | `coalesce(source,'') <> 'auto'` is in Rule 1 and the Design, with a test that NULL-source episodes are clustered by both paths. |
| Should 2, singleton guard | Applied | Now Rule 5, with a test. |
| Should 3, fewer passes | Applied wrongly | Accepted and disclosed, but the justification is false. See new item 2. |
| Should 4, knowledge feed | Applied | Now Rule 6, with a test. One gap remains; see new item 3. |
| Should 5, end-to-end test | Applied | It is buildable: `recall(lane="work")` rewrites `target_ids` with the delivered ids (server.py:2551-2560), and the compress tool runs at server.py:2989-3011. |
| Should 6, `scope="full"` wording | Applied | |
| Nits | Applied | `guarded_prune`, test locations, `remember(source="auto")`, the `json_valid` guard, `source` in the compress output, and the revert note. The revert note is applied wrongly; see new item 1. |

### Rules 5 and 6 against the code

- **Rule 5 matches.** The candidate query is at compress.py:1218-1224 inside `_promote_singletons`
  (compress.py:1211-1271). One added `AND coalesce(e.source,'') <> 'auto'` closes the gap. The query already
  selects `e.source`.
- **Rule 6 matches.** The feed is appended at compress.py:623, and only on the non-reinforce branch. Cluster
  episodes come from `SELECT *` (storage.py:612-617 today, and from `_refine_clusters`), so they carry `source`.
  Graphiti stores `episode_body` as given (knowledge.py:338-341).
- **Builder note.** Filter with `ep.get("source")`, not `ep["source"]`. The mocked episodes in
  tests/test_knowledge.py:472-475 have no `source` key.
- **The `json_valid` guard works as specified.** On SQLite 3.54.0, the unguarded join raises `malformed JSON` on a
  bad row. With `AND json_valid(m.target_ids)` it skips the row, both as a join and inside the `IN (…)` subquery.
  So the planned "malformed row is skipped" test is meaningful.
- **No existing test asserts the compress tool's exact output shape**, so adding `source` is safe.

### Newly wrong

1. **Must fix: the Deploy revert advice doesn't do what it says.**
   - The spec says: "Before a revert, run `compress()` once if those captures should be reviewed by a model
     instead."
   - Under this change, `compress()` offers only captures with used-recall evidence (Rule 2). Unused captures,
     which are nearly all of them (0 of the 64 used recalls returned one), stay waiting. A revert's first startup
     then copies them verbatim through the old `auto_compress`, before anyone can call `compress()`.
   - Change: replace that sentence with "Running `compress()` first only reviews captures with recall evidence;
     the unused ones still become verbatim semantics at the reverted start. If that matters, fix forward instead of
     reverting, or get Andy's yes to mark the waiting captures discarded (`compressed = 1`, no semantic) before
     the revert."
2. **Should fix: "They worked on semantics made from prompts anyway" (Design, the fewer-passes bullet) is false.**
   - None of the three passes reads capture-made semantics:
     - singleton promotion reads core episodes not linked to any semantic (compress.py:1218-1224);
     - instinct formation skips the work lane (compress.py:1094-1095), and every copy is in the work lane;
     - re-derivation reads instinct co-firing edges (compress.py:717-725).
   - They ran on capture-only days only because a capture was pending.
   - Change: replace the sentence with "None of them reads capture-made semantics; they ran on those days only
     because a capture was pending, so skipping them only delays them."
   - Also, "the Mac's last 51 days" should read "the 51 days since 2026-09-01 with new episodes".
3. **Should fix: say what happens to a cluster made only of captures.**
   - "Minus any with `source='auto'`, plus the semantic's content as today" can leave an empty episode list.
     `feed` and `feed_background` return None on empty episodes (knowledge.py:283-284, 299-300). The semantic
     content is only each episode's `source_description` (knowledge.py:341), so nothing reaches the graph.
   - `_feed_knowledge_graph` would still count the empty feed as handed (compress.py:745-757). That inflates
     `knowledge_feeds_queued`.
   - Change: "A cluster whose episodes are all captures appends no feed, so its summary doesn't reach the graph."
   - Add that case to the Rule 6 test.

### Nit

- The refine Non-goal says "no capture's text reaches a semantic through it". That holds for refine's default
  reinforce. A model can override the action to `new` (compress.py:501), which writes the model's own summary as
  a new semantic, without recall evidence. Add "unless the model overrides the action to `new`, which stores its
  own summary". On the Mac this can't happen, because no semantic qualifies for refine.
