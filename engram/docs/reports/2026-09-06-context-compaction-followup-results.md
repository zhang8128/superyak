# Compaction follow-up results

Both separately frozen follow-ups failed during preparation. Neither generated
comparator answers. The original 200 dynamic/LocalAgent answers and original
120-second timeout remain unchanged. The result is evidence about this
compaction workflow's reliability and cost, not a three-way answer-quality
comparison.

| Profile | New auxiliary calls | New auxiliary elapsed time, summed | Last accepted prefix | Terminal outcome |
| --- | ---: | ---: | ---: | --- |
| Deadline-only, 300 seconds | 2 | 289.74 s | 140/1,124 entries | 6,024-byte summary exceeds 6,000-byte cap |
| Whole-entry admission, low auxiliary reasoning | 9 | 763.65 s | 385/1,124 entries | Summary cites an unavailable source ID |

Each profile imported the same original step-zero success: 91 prefix entries,
86.45 seconds, 14,246 reported input tokens and 2,656 output tokens. That call
was not dispatched again. Imported usage is reported separately; adding it to
both profiles does not represent two additional physical calls.

## Deadline-only continuation

The [protocol](2026-09-06-context-compaction-followup-protocol.md) and runner
froze at `b6b7497`. Reconstructing the formerly timed-out request reproduced
digest `84e2ba5e08ff6bcc24aebc7b943397a42f1d9511a733c292f0d4ecd1f5b0de01`.
With the longer deadline, it completed in 140.87 seconds. The next call took
148.87 seconds and returned parseable JSON with available source IDs, but its
summary exceeded the cap by 24 bytes. It was rejected as specified.

Both new responses reported usage: 29,136 input and 9,229 output tokens total.
All 100 comparator cells record one shared preparation failure; these are not
100 provider failures. There were zero answer dispatches, uncertain dispatches,
or unattempted cells. The terminal response remains available for inspection.

## Bounded admission continuation

The separate [protocol](2026-09-06-context-bounded-compaction-protocol.md) froze
at `8574e39`. It validates the entire raw summary before retaining a prefix of
whole entries within the cap, and sets auxiliary reasoning to `low`. Answering
settings remain unchanged. These are two workflow changes, so the result cannot
identify either change's isolated effect. No production provider default or
global Codex configuration changed.

Eight new compactions succeeded. Their raw summaries were 5,761–5,905 bytes;
**none required projection and no entries were omitted by the admission code**.
This run therefore did not exercise clipping in live generation. Repeated
summarization itself can still lose facts; fitting the cap is not a fidelity
measurement.

Step nine attempted to extend the prefix through entry 420. Its 5,761-byte
response substituted `ev-10d945971f535c71a90d5f39` for the available
`ev-10f945971f535c71a90d5f39` in a keepsake-summary entry. The generated ID is
absent from both the supplied request and the synthetic original corpus. The
validator rejected it; the ID was not repaired or silently remapped. The last
accepted summary covers entry 385.

All nine new responses reported usage: 130,190 input and 24,055 output tokens.
Auxiliary latency p50/p95 was 84.33/89.07 seconds. All 100 comparator cells
record preparation failure, with zero answer dispatches, uncertain dispatches,
or unattempted cells. The approximately 12.7 minutes of new auxiliary episode
time is retained as a cost of this unsuccessful profile.

## Interpretation and next design question

The three observed failure modes are deadline exhaustion, byte overflow, and
source-ID corruption. More time resolved the first failed request, but did not
make the overall pipeline succeed. Deterministic admission protects the byte
bound; it does not protect model-written provenance or semantic fidelity.
Rewriting a nearly full summary to incorporate roughly 35 routine entries per
call also accumulates substantial auxiliary cost in this synthetic fixture.

No fourth profile was dispatched. Before another experiment, the compaction
design needs to separate immutable source references from generated prose and
address repeated rewriting cost. Any such change needs a newly frozen protocol
and a fidelity comparison; it must not repair this run's historical outcomes.
These observations apply to this implementation and fixture, not all
append-and-compact systems.

The original protocol caps supplied envelopes at 16,000 canonical JSON UTF-8
bytes, not equal internal model tokens. The deadline-only provider inherited
the installed reasoning configuration (observed as `xhigh`); effective reasoning
was not independently recorded per call in the original capture. Workload and
execution times varied on a shared machine. The later follow-ups are exploratory
and not temporally interleaved with the 200 historical answers. Human factual
and relational ratings remain entirely unset.

## Evidence

Each archive retains configuration, fixture, imported provenance, original raw
responses, durable dispatch journals, failure outcomes, report, review packet
and origin mapping. A retrospective request reconstruction reproduces every
recorded request digest; its metadata distinguishes reconstruction from capture.
Per-file checksums are inside each archive. Parent evidence manifest SHA256:
`2799cf512ebff5a5d84598356287fbfad3e223ee868edb84bc94c29ff58103f4`.

- Deadline-only: [results JSON](2026-09-06-context-compaction-followup-results.json),
  [evidence archive](2026-09-06-context-compaction-followup-evidence.tar.gz),
  [review page](2026-09-06-context-compaction-followup-review.html).
- Bounded profile: [results JSON](2026-09-06-context-bounded-compaction-results.json),
  [evidence archive](2026-09-06-context-bounded-compaction-evidence.tar.gz),
  [review page](2026-09-06-context-bounded-compaction-review.html).
- [Artifact checksums](2026-09-06-context-followups-sha256.json).
- [Artifact and browser verification](2026-09-06-context-followups-verification.json):
  all original artifact hashes unchanged, both archives internally verified,
  historical answers identical, and all three new review pages checked for
  blank ratings, expected counts, navigation, and supplied-context inspection.

Each review page contains the same 200 historical answers plus its own 100
preparation outcomes. They are alternative views, not 400 independent answers.
The [original study](2026-09-06-context-continuity-results.md) and its failed
comparator slot remain preserved separately. The new
[assistant assessment](2026-09-06-context-assistant-assessment.md) concerns only
the original 200 answers and does not supply human ratings.
