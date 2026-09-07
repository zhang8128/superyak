# Preliminary continuity comparison protocol

Frozen before generating answers. This is a synthetic, subscription-backed
preliminary comparison, not the design's human-reviewed continuity gate or a
certification of equal internal model token budgets.

## Corpus and arms

Use the 100 fixed probes in `tests/fixtures/context_retrieval/probes.json`, SHA256
`be562a36147b0e10fd8ad6df6f019526a5e576b09fb367ccbc9ca2ab3ee80266`.
Report the 30 development and 70 held-out questions separately. Source retrieval
was tuned on development outcomes only; the search policy froze at `84e7f50`
before held-out source-selection results were inspected.

The answer comparison uses **1,000 routine entries**, following all synthetic
source records, plus each probe's temporary recent referents. This is separate
from the 25,000-entry retrieval scaling benchmark. The smaller live corpus keeps
the comparator's serial compaction cost practical; all arms see the same source
corpus and dialogue. No private memory, real conversations, or Lighthouse sharing
is used.

- **Dynamic context:** the actual runtime selector/compiler, with explicit pins
  and recent referents. The Codex episode provider accepts no runtime tools, so
  the live envelope omits them and is counted again before dispatch.
- **LocalAgent context:** the actual `EngineCore.recall`, Nomic embeddings, and
  `LocalAgent.build_system_prompt` / `build_prompt`, with empty core/instinct
  state and disabled delegation. Seed every synthetic original as an episode,
  using its opaque event ID as provenance. This is a controlled preloaded-memory
  comparison, not a test of the legacy system's capture choices. Substitute Codex
  for Ollama as the common answering host; do not call `LocalAgent.chat` or
  process generated memory/signal tags. Use cached embedding weights offline.
- **Append-and-compact comparator:** a newly frozen benchmark comparator, not an
  existing Engram implementation. Append the corpus chronologically, keep the
  last six base entries and each probe's supplied recent referents verbatim,
  and summarize older prefixes through Codex under
  the same envelope ceiling. Preserve speaker/source attribution, corrections,
  unresolved conflicts, quoted-text boundaries, and personal context. The
  compactor sees no future questions, expected IDs, or answer key. Its shared
  query-independent summary is frozen before any scored answer. Count every
  auxiliary call, retain raw compaction outputs, and reject overflow or invented
  source IDs rather than silently trimming or accepting them.

## Admission, generation, and failures

Use managed ChatGPT login and `gpt-6-astra` in isolated ephemeral episodes, with
tools and external integrations disabled. No API fallback. All answering and
compaction requests must fit **16,000 canonical JSON UTF-8 bytes** of supplied
envelope; record actual app-server input/output usage afterward. Codex's hidden
instructions and internal context are outside this byte ceiling. Do not call
this equal per-model-call token usage.

Ask for JSON containing a natural `answer` and `source_ids` drawn only from
supplied evidence. Use the same answering instruction for every arm. Common
answer instructions prohibit emitted memory/signal/delegation tags; no response
is executed. Keep original baseline formatting otherwise. Capture malformed
answers, provider failures, and capacity failures as outcomes. Never replace
unfavorable outputs with retries. Resume only cells without any recorded
dispatch; interrupted in-flight cells remain uncertain outcomes. Use a fixed
seed (20260906) to shuffle the 300 probe/arm cells, and at most two concurrent
provider calls. Save immutable request digests and durable dispatch markers.

The compactor has a 6,000-byte summary cap and at most 64 calls. Each next chunk
is chosen solely by chronological order and the envelope ceiling. A summary
failure leaves that arm unavailable; it must not become an extractive substitute
with the same label. No scored answer or grading result is fed into any other
probe or summary.

## Grading and interpretation

Freeze answers before grading. Programmatically report parse failures, provider
failures, invented/unavailable citation IDs, expected-source citation coverage,
usage, and latency. Keyword coverage is not answer correctness: reversed
attribution or stale corrections can include every expected keyword.

Prepare an arm-label-blinded review packet containing the question, original expected
sources, supplied evidence, and raw answer. Human reviewers judge factual
correctness, attribution, current corrections, unresolved conflicts, referents,
quoted-instruction handling, and relational continuity/naturalness. Leave human
ratings unset until reviewed; any model-assisted grading must be identified as
such. Report paired results and family-level differences once these judgments
exist. Context formatting can still reveal the likely method to a reviewer.
Neither synthetic source selection nor automated citation checks can
establish the proposed 95/100 human quality gate.

Related templates, reused names/values, repeated generic distractors, explicitly
warned-about quotations, and answerable-only questions limit generalization.
Old-source age is tested; indexing delay and calibrated abstention are not.
Normal-use rollout and Lighthouse expansion remain outside this evaluation.
