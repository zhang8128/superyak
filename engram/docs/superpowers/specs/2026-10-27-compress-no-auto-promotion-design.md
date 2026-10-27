# Compression never promotes unused prompt captures

Revision 3, 2026-10-27. Serenity (the Mac). Board item `spec:compress-no-auto-promotion` in City of AI.
Amends the compression rework (2026-03-26-compression-rework-design.md) for one source of episodes.
Revision 2 applies the fresh review (docs/superpowers/reviews/2026-10-27-compress-no-auto-promotion-review.md):
- **Must-fix:** refine is out of scope; "used" evidence is per recall; the startup test stub.
- **Should-fix:**
  - NULL sources, with a test;
  - the singleton guard;
  - fewer maintenance passes, accepted;
  - captures kept out of the knowledge feed;
  - an end-to-end test;
  - `source` in the compress output;
  - the revert note.

Revision 3 applies the re-check, as worded there:
- the revert note's must-fix (fix forward, or discard with Andy's yes);
- the corrected reason for fewer maintenance passes;
- a cluster made only of captures adds no feed;
- refine's `new` override is accepted.

## Why

The nudge hook (`hooks/nudge.py:532-537`) stores every novel prompt of 50 characters or more, verbatim, as an
episode with `source='auto'` in the work lane. Compression then treats those prompts like any other episode.
`auto_compress()` (`compress.py:827-869`) runs with no model, at startup maintenance (`server.py:1080-1087`) and
after every 10 `remember()` calls (`server.py:1914-1923`). It writes each cluster's semantic from the episodes'
own text:
- a 1-episode cluster becomes that episode's text;
- a 2-3 episode cluster becomes the text of the episode nearest the centroid;
- a cluster of 4 or more becomes three representatives joined by `" --- "`.

Measured on the Mac's store (read-only, 2026-10-27, and reproduced by the review):
- 260 auto episodes, all compressed.
- 315 semantics, 280 of them auto-generated.
- **234 semantics are an auto episode's text, word for word.**
- 164 semantics have only auto episodes as sources.
- Of 550 recalls, 64 were logged used (16 not_used, 470 with no outcome). None of the 64 returned an auto episode.

So most of the layer meant for distilled knowledge is the person's raw prompts. No recall ever found those
prompts useful. Semantics are what imprints and shares carry to other lighthouses, and prompts name other people
and private matters. The exclude file for the imprint of Andy's store had to drop 491 capture ids by hand.

## Goal

A captured prompt becomes knowledge only through a model's summary, and only after it was returned by a recall
that was logged used. The evidence is per recall, not per episode: `log_outcome` records one outcome for a whole
recall. The sleep hook marks a whole recall `used: auto: cited` when any of its results is cited later. So a capture
shown beside the result that was actually used also qualifies. The model reviewing `compress()` is the real gate.
Recall evidence only decides what the model is shown.

## Non-goals

- The nudge hook's capture and pruning, and recall over auto episodes, stay as they are.
- Other sources (`remember(source=…)`, `signal/…`, `prism:…`, NULL), lanes, core promotion and instinct formation
  are unchanged, except as stated below.
- `compress(scope="refine")` is outside these rules. Its clusters commit through the reinforce step, which only
  raises a semantic's confidence and adds source links (`compress.py:529-533`, `storage.py:1118-1129`). It never
  rewrites content by default, so no capture's text reaches a semantic through it. It does show the model a joined
  semantic's source episodes, which may include captures. The model can override a refine cluster's action to `new`
  (`compress.py:501`). That stores the model's own summary without recall evidence, which is accepted because it's
  still a model's summary. On the Mac, no semantic contains `" --- "`, so refine has nothing to work on there.
- The 234 existing copies are left alone (see "Existing copies").

## Rules

1. **The no-model path never takes auto episodes.** `auto_compress()` clusters only episodes whose source is not
   `'auto'`, NULL included. It copies text, so it never copies a prompt, used or not.
2. **The model path takes an auto episode only with recall evidence.** `compress()` (the MCP tool, then
   `compress_commit`) offers an auto episode only when its id is in `target_ids` of a `memory_log` row with
   `event_type = 'recall'` and `outcome LIKE 'used%'`. That covers `log_outcome(used=True)` with or without a note,
   and the sleep hook's `used: auto: cited`. It never covers `not_used` or NULL.
3. **Left-out episodes are untouched.** They stay `compressed = 0`, remain recallable as episodes, and decay as
   today. The nudge hook's inline prune (`source='auto' AND core=0 AND decay_strength < 0.08`) still prunes them,
   since it doesn't need them compressed. The startup prune only moves compressed episodes, whether it's
   `prune_decayed` (`storage.py:770`) or `guarded_prune` when persistence is enabled (`persistence.py:274-277`).
   So it never touches them. That's unchanged.
4. **An auto episode that gains evidence is offered at the next `compress()`.**
5. **A capture never becomes a singleton semantic.** `_promote_singletons` (`compress.py:1211-1271`) copies a core
   episode's content verbatim with no model. Its candidate query also requires `coalesce(e.source,'') <> 'auto'`.
   Today no capture on the Mac is core. This closes the one remaining no-model copy: a used capture that a model
   moved to the personal lane and someone marked core.
6. **Captures never feed the knowledge graph.** When the model path commits a cluster, the knowledge feed
   (`compress.py:623`) gets the cluster's episodes minus any with `source='auto'`, plus the semantic's content as
   today. Graphiti stores episode text as it is given (`knowledge.py:338-341`). A cluster made only of captures
   leaves no episodes to feed, so no feed is added for it, and it isn't counted in `knowledge_feeds_queued`
   (`compress.py:745-757`). That cluster's summary therefore doesn't reach the graph, which is accepted. The builder
   reads `ep.get("source")`, because some test episodes carry no `source` key (`tests/test_knowledge.py:472`). This
   also ends a feed that happens today, where captures reached the graph through `auto_compress` after 10
   `remember()` calls.

## Design

Filter where episodes are read, before clustering, never after. If auto episodes joined a cluster and were filtered
out afterwards, a mixed cluster could still take a prompt as its centroid text. A prompt-only cluster could also
`reinforce` an existing semantic. Filtering at the read prevents both.

- **Storage.** `Storage.get_uncompressed_episodes(auto: str = "all")` takes `auto` as one of three values:
  - `"all"`: today's query.
  - `"used"`: non-auto episodes, plus auto episodes in a used recall's `target_ids`.
  - `"none"`: non-auto episodes only.

  Any other value raises `ValueError`. "Non-auto" is `coalesce(source,'') <> 'auto'`, because 646 of the Mac's
  1,046 episodes have no source. The `"used"` filter is SQL: the ids from `memory_log m, json_each(m.target_ids)`
  where `m.event_type = 'recall' AND m.outcome LIKE 'used%' AND json_valid(m.target_ids)`. It takes 1 ms on the
  Mac's 7,689 log rows, and `idx_memory_log_event_type` exists.
- **Clustering.** `Compressor.cluster_episodes(scope="recent", *, auto="used")` passes `auto` to storage. The
  `compress` tool keeps calling it with no `auto`, so it gets `"used"`. `auto_compress()` calls
  `cluster_episodes(auto="none")`.
- **The compress tool.** Its output gives each episode its `source`, so the reviewing model can see which episodes
  are a person's raw prompts. This adds a key and removes none.
- **`scope="full"`.** It resets every episode to uncompressed as today, then clusters under the same rule. Unused
  captures stay uncompressed, and used ones are offered.
- **The startup check** (`server.py:1080`) asks `get_uncompressed_episodes(auto="none")`. Otherwise every startup
  would count the left-out prompts as pending, note them in the maintenance report, and run a compression that
  finds nothing.
- **Accepted: fewer maintenance passes.** Singleton promotion, the instinct check and instinct-cluster
  re-derivation run only when a compression commits (`compress.py:696-725`). None of them reads prompt semantics:
  - singleton promotion reads core episodes;
  - instinct formation skips the work lane;
  - re-derivation reads instinct co-firing edges.

  They ran on capture-only days only because a pending capture made startup commit. On 31 of the 51 days since
  2026-09-01 with new episodes, the only new episodes on the Mac were captures. On days like that, startup now
  commits nothing, so those three passes wait for the next commit. If they, re-derivation especially, should run on
  their own schedule, that's a separate item.
- **Accepted: a deliberate `remember(source="auto")` is treated as a capture.** No caller does this today.
- **Docs.** The engram CLAUDE.md "Sleep-time consolidation" paragraph gains one sentence: auto-captured prompts are
  never auto-compressed, and the model's compress offers them only after a used recall returned them.

## Tests

`tests/test_compression.py`:
- `auto_compress` over a store holding a cluster of remembered episodes and a cluster of auto episodes creates a
  semantic only from the remembered ones. The auto episodes stay `compressed = 0`.
- `auto_compress` never creates or reinforces a semantic from an auto episode, even one a used recall returned.
- With a used auto episode near remembered ones, no auto-generated semantic's content equals or contains the auto
  episode's text.
- `cluster_episodes()` (the model path) leaves out an unused auto episode. After a recall returning it is logged
  `used`, the next call offers it.
  - Each of these leaves it out: a `not_used` outcome, a NULL outcome, a non-recall row naming it, and a used recall
    that returned a different id.
  - Each of these lets it in: `used: <note>` and `used: auto: cited`.
- Episodes with NULL source are clustered by both paths, exactly as today.
- `scope="full"`: unused captures stay uncompressed afterwards, and used ones are offered.
- `_promote_singletons` skips a core capture.
- A committed cluster holding a used capture feeds the knowledge graph without the capture's episode. A committed
  cluster made only of used captures adds no feed, and `knowledge_feeds_queued` doesn't count it.
- **End to end (`tests/test_server.py`):**
  1. `remember` several work episodes, insert a capture as the nudge hook does, and call `recall(lane="work")` so
     the capture is returned.
  2. Call `log_outcome(recall_id, used=True)`.
  3. The `compress` tool then offers the capture, with `source: "auto"` in its output. Without step 2 it doesn't.

`tests/test_storage.py`:
- `get_uncompressed_episodes`: `"all"` matches today's rows, and `"none"` and `"used"` behave as above. A malformed
  `target_ids` row is skipped, and an unknown value raises.

`tests/test_startup_maintenance.py`:
- Startup with only auto episodes uncompressed runs no compression and notes nothing pending.
- The existing stub at :132 becomes `lambda **_: [{"id": "x"}]`, since the method now takes a keyword.

The existing compression, nudge-capture and startup-maintenance tests otherwise pass unchanged.

## Deploy

Engram code runs in every session's engram MCP server and in the Mac's lighthouse daemon (launchd, from the main
checkout). Each picks the change up at its next start. A Serenity branch merges under law section 2: a partner's
verdict, and the engram suite on the Pi. The change writes nothing on its own and needs no migration.

Rollback is a revert, but a revert isn't free. At the first start after it, the old `auto_compress` copies every
capture still waiting uncompressed into a semantic word for word. That's nearly all of them, since few captures ever
gain recall evidence. Running `compress()` first doesn't help, because it only offers captures with evidence.
Prefer fixing forward. If a revert is needed, first get Andy's yes to mark the waiting captures compressed with no
semantic (a discard), then revert.

## Existing copies (Andy's call, not this change)

On the Mac, 234 semantics are a prompt word for word. The imprint already excludes them by id. Removing them from
the store itself is a hard-to-undo change to Andy's own memory. It needs his explicit yes and its own small design:
1. a backup first;
2. then delete those semantics and their `semantic_sources` rows;
3. then set their source episodes to `compressed = 0`, so the rules above apply.

The measurement queries are in the commit message of this spec's revision 1 (02b112a).

## Decisions

- D1: filter before clustering, not after (see Design).
- D2: `auto_compress` excludes auto episodes even when used. A verbatim prompt isn't distilled knowledge, so only
  a model's summary may carry one.
- D3: the evidence is a recall logged `used…`, per recall, including the sleep hook's citation mark. `not_used` and
  NULL don't count. The model's review is the gate; the evidence only decides what it is shown.
- D4: left-out episodes stay uncompressed rather than being marked discarded. They can still qualify later, and
  the hook that writes them prunes them.
- D5: the existing copies stay until Andy decides.
- D6: captures are kept out of singleton promotion and the knowledge feed. Those are the remaining places where
  their verbatim text would be stored as knowledge.
