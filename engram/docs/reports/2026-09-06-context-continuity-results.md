# Preliminary continuity capture

The frozen comparison captured live answers from dynamic context and the existing
LocalAgent context path. The append-and-compact comparator became unavailable:
its second auxiliary summary call reached the provider's 120-second episode
deadline. That failure is retained, with no replacement call. This therefore
provides a two-arm answer review and a failed third-arm preparation outcome;
it does not establish three-way answer quality or the human continuity gate.

The [protocol](2026-09-06-context-continuity-protocol.md) and runner froze at
`d0c1999`, before generation. Both answering approaches used isolated managed
Codex `gpt-6-astra` episodes. All supplied envelopes were capped at 16,000
canonical JSON UTF-8 bytes. Actual model input usage includes hidden Codex
context and internal processing; internal token budgets were not equalized.
The fixture contains 100 related synthetic questions, split 30 development and
70 held out, with 130 original records followed by 1,000 routine entries.

## Captured results

| Approach | Captured answers | Provider/capacity failures | Malformed answer JSON | Unavailable citation IDs | All expected source IDs cited |
| --- | ---: | ---: | ---: | ---: | ---: |
| Dynamic context | 100/100 | 0 | 0 | 0 answers | 99/100 |
| LocalAgent context | 100/100 | 0 | 0 | 0 answers | 96/100 |
| Append-and-compact comparator | 0/100 | 100 preparation failures from one shared timeout | — | — | — |

There were **200 answer dispatches and two auxiliary compaction dispatches**,
with no uncertain dispatches or unattempted cells. The missing comparator
answers are recorded preparation outcomes, not 100 failed model calls.

| Split | Dynamic: expected IDs cited | LocalAgent: expected IDs cited |
| --- | ---: | ---: |
| development | 30/30 | 30/30 |
| holdout | 69/70 | 66/70 |

| Approach | Reported input tokens, total | Reported output tokens, total | Response latency p50 / p95 |
| --- | ---: | ---: | ---: |
| Dynamic context | 1,192,104 | 9,688 | 7.40 / 11.97 s |
| LocalAgent context | 1,070,874 | 9,613 | 7.45 / 10.76 s |

Usage was reported for 100 dynamic and 100 LocalAgent responses.
The successful compaction reported 14,246 input and 2,656 output tokens.
The timed-out auxiliary call returned no usage; its consumption is unknown.

Expected-source citation coverage is a provenance check, not correctness. It can
pass with reversed attribution, stale revisions, unsupported assertions, or
misread personal meaning. Human factual and conversational ratings remain unset.
The dynamic selector supplied all expected originals for 99/100 live-capture
questions; one 50 ms archive timeout was preserved. This live capture is separate
from the 25,000-entry [retrieval scaling comparison](2026-09-06-context-retrieval-evaluation.md).

## Compaction failure and comparability

The comparator's first auxiliary call completed in 86.45 seconds, summarizing
91 of 1,124 prefix entries with valid source IDs. The second timed out after
120.07 seconds without a final response. All 100 comparator cells were marked
unavailable before answer dispatch. The first summary, request digests, both
dispatch records, and the timeout are preserved. A longer deadline or different
chunking would define a revised experiment; no such rerun was substituted here.
The timeout establishes a limitation of this comparator under the chosen
provider settings, not an answer-quality ranking for append-and-compact systems.

The LocalAgent arm used actual `EngineCore.recall` and prompt formatters, with
130 preloaded synthetic episodes and empty core/instinct state. Cached Nomic
weights (`e9b6763023c676ca8431644204f50c2b100d9aab`, FastEmbed 0.7.4) ran offline.
This does not compare automatic memory capture, private identity context, or the
usual Ollama answering host. The dynamic arm's source selection was frozen before
its model instructions were changed to the common JSON-answer instruction and
the tools removed; the final supplied envelope was counted again before dispatch.

## Human review and evidence

Open the [local review page](2026-09-06-context-continuity-review.html). It shows
captured answers by default and can also display preparation failures. Labels
hide the method, although formatting may reveal it. Compare each answer with
its original sources; check attribution, corrections, constraints, unresolved
conflicts, quoted instructions, referents, and personal meaning. Save and export
ratings from the page. Browser-local ratings do not modify the captured evidence.
No human ratings were prefilled or inferred from keywords or citation counts.

The evidence archive includes the frozen fixture/configuration, supplied
contexts, original responses and usage, durable dispatch journals, source-selection
results, compactions, report, review packet/key, and environment/code provenance.
Interrupted dispatched calls are never silently replayed. Preparation failures
are recorded separately from model calls. SHA256 values identify saved artifacts.

- [Machine-readable results](2026-09-06-context-continuity-results.json).
- [Complete captured evidence archive](2026-09-06-context-continuity-evidence.tar.gz).
- [Artifact checksums](2026-09-06-context-continuity-sha256.json); the archive also contains a per-file manifest.

The remaining work is human review of the captured answers and a separately
specified, practical compaction comparison. The proposed 95/100 human quality
gate, zero lost constraints, and relational-continuity acceptance remain open.
Normal-use rollout and Lighthouse expansion remain later steps.
