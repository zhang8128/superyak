# Compression never promotes unused prompt captures

Revision 1, 2026-10-27. Serenity (the Mac). Board item `spec:compress-no-auto-promotion` in City of AI.
Amends the compression rework (2026-03-26-compression-rework-design.md) for one source of episodes.

## Why

The nudge hook (`hooks/nudge.py:532-537`) stores every novel prompt of 50 characters or more, verbatim, as an
episode with `source='auto'` in the work lane. Compression then treats those prompts like any other episode.
`auto_compress()` (`compress.py:827-869`) runs with no model, at startup maintenance (`server.py:1080-1087`) and
after every 10 `remember()` calls (`server.py:1914-1923`). It writes each cluster's semantic from the episodes'
own text:
- a 1-episode cluster becomes that episode's text;
- a 2-3 episode cluster becomes the text of the episode nearest the centroid;
- a cluster of 4 or more becomes three representatives joined by `" --- "`.

Measured on the Mac's store (read-only, 2026-10-27):
- 260 auto episodes, all compressed.
- 315 semantics, 280 of them auto-generated.
- **234 semantics are an auto episode's text, word for word.**
- 164 semantics have only auto episodes as sources.
- Of 550 recalls, 64 were logged used. None of them returned an auto episode.

So most of the layer meant for distilled knowledge is the person's raw prompts. No recall ever found those
prompts useful. Semantics are what imprints and shares carry to other lighthouses, and prompts name other people
and private matters. The imprint of Andy's store had to drop 491 capture ids by hand for exactly this reason.

## Goal

A captured prompt becomes knowledge only through a model's summary, and only after a recall actually used it.

## Non-goals

- The nudge hook's capture and pruning, and recall over auto episodes, stay as they are.
- Other sources (`remember(source=…)`, `signal/…`, `prism:…`, NULL), lanes, core promotion, singleton promotion and
  instincts are unchanged.
- The 234 existing copies are left alone here (see "Existing copies").

## Rules

1. **The no-model path never takes auto episodes.** `auto_compress()` clusters only episodes whose source is not
   `'auto'`. It copies text, so it never copies a prompt, used or not.
2. **The model path takes an auto episode only once it was used.** `compress()` (the MCP tool, then
   `compress_commit`) offers an auto episode only when some recall that returned it was logged used. That means a
   `memory_log` row with `event_type = 'recall'`, `outcome LIKE 'used%'` and the episode's id in `target_ids`. This
   includes the sleep hook's `used: auto: cited`, which is positive evidence: a later act cited the result.
3. **Left-out episodes are untouched.** They stay `compressed = 0`, remain recallable as episodes, decay as today,
   and are pruned by the nudge hook's inline prune (`source='auto' AND core=0 AND decay_strength < 0.08`), which
   doesn't need them compressed. `prune_decayed` only moves compressed episodes, so it never touches them. That's
   unchanged.
4. **An auto episode that becomes used is offered at the next `compress()`.** No other change is needed.

## Design

Filter before clustering, never after. If auto episodes joined a cluster and were filtered out afterwards, a
mixed cluster could still take a prompt as its centroid text, or a prompt-only cluster could `reinforce` an
existing semantic. The filter runs where the episodes are read, so neither can happen.

- `Storage.get_uncompressed_episodes(auto: str = "all")` takes `auto` as one of `"all"` (today's query),
  `"used"` (non-auto episodes, plus auto episodes in a used recall's `target_ids`) or `"none"` (non-auto only).
  Any other value raises `ValueError`. The `"used"` filter is SQL: the ids from
  `memory_log m, json_each(m.target_ids)` where `m.event_type = 'recall' AND m.outcome LIKE 'used%'` (1 ms on the
  Mac's 7,689 log rows; `idx_memory_log_event_type` exists).
- `Compressor.cluster_episodes(scope="recent", *, auto="used")` passes `auto` to storage. The `compress` tool
  keeps calling it with no `auto`, so it gets `"used"`. `auto_compress()` calls `cluster_episodes(auto="none")`.
- `scope="full"` resets every episode to uncompressed as today, then clusters under the same rule. Its auto
  episodes therefore stay uncompressed.
- `scope="refine"` re-summarizes existing joined semantics through the model, as today. It's the one path that
  already lets a model replace the 4+ copies (see "Existing copies").
- The startup check (`server.py:1080`) asks `get_uncompressed_episodes(auto="none")`. Otherwise every startup would
  count the left-out prompts as pending, note them in the maintenance report, and run a compression that finds
  nothing.
- The engram CLAUDE.md "Sleep-time consolidation" paragraph gains one sentence: auto-captured prompts are never
  auto-compressed, and the model's compress offers them only after a recall used them.

## Tests (`tests/test_compression.py`, `tests/test_storage.py`)

- `auto_compress` over a store holding a cluster of remembered episodes and a cluster of auto episodes creates a
  semantic only from the remembered ones. The auto episodes stay `compressed = 0`.
- `auto_compress` never creates or reinforces a semantic from an auto episode, even one a used recall returned.
- With a used auto episode near remembered ones, no auto-generated semantic's content equals or contains the auto
  episode's text.
- `cluster_episodes()` (the model path) leaves out an unused auto episode. After a recall returning it is logged
  `used`, the next call offers it. A `not_used` outcome, a NULL outcome, a non-recall row naming it, and a used
  recall that returned a different id all leave it out. A `used: auto: cited` outcome lets it in.
- `get_uncompressed_episodes`: `"all"` matches today's rows; `"none"` and `"used"` as above; an unknown value raises.
- The startup step with only auto episodes uncompressed runs no compression and notes nothing pending.
- `scope="full"` leaves auto episodes uncompressed afterwards.
- The existing compression, nudge-capture and startup-maintenance tests pass unchanged.

## Deploy

Engram code runs in every session's engram MCP server and in the Mac's lighthouse daemon (launchd, from the main
checkout). Each picks the change up at its next start. A Serenity branch merges under law section 2: Rio Grande's
verdict, and the engram suite on the Pi. The change writes nothing on its own and needs no migration. Rollback:
revert. Episodes left uncompressed in the meantime are compressed by the old rule at the next start.

## Existing copies (Andy's call, not this change)

On the Mac, 234 semantics are a prompt word for word. The imprint already excludes them by id. Removing them from
the store itself is a hard-to-undo change to Andy's own memory, so it needs his explicit yes and its own small
design: a backup first, then delete those semantics and their `semantic_sources` rows, then set their source
episodes to `compressed = 0` so the rules above apply. `compress(scope="refine")` already lets a model rewrite the
joined ones. The measurement queries are in this spec's commit message.

## Decisions

- D1: filter before clustering, not after (see Design).
- D2: `auto_compress` excludes auto episodes even when used. A verbatim prompt isn't distilled knowledge, so only
  a model's summary may carry one.
- D3: any `used…` outcome counts, including the sleep hook's citation evidence. `not_used` and NULL don't.
- D4: left-out episodes stay uncompressed rather than being marked discarded. They can still earn their way in
  later, and the hook that writes them prunes them.
- D5: the existing copies stay until Andy decides.
