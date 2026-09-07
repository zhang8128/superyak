# Archive retrieval evaluation

The repeated-history failure measured in the [runtime completion report](2026-09-06-context-runtime-completion.md)
now has a fixed benchmark and a targeted search change. In a serial paired repeat
at 25,000 routine entries, the runtime supplied all expected original sources for
**99/100 questions**, versus **10/100** before. The one remaining timeout is retained
in the results. These are source-selection measurements, not answer-quality scores.

## Frozen fixture and method

Commit `5fc1e66` froze 100 synthetic probes with 130 distinct original source
records. Ten related variants cover each of ten families: returning to a project,
personal interludes, explicit corrections, revised plans, conflicting speakers,
recent referents, old details, Unicode, quoted instructions, and paraphrases.
The first three variants per family are development cases; the other seven are
held out. Fixture SHA256:
`be562a36147b0e10fd8ad6df6f019526a5e576b09fb367ccbc9ca2ab3ee80266`.

The runner seeds originals, foreign-thread copies, and increasing routine
dialogue, then invokes the actual candidate selector and compiler, including
the normal tool schema. Ground-truth IDs are used only after compilation.
Temporary recent referents and explicit pins are restored per probe and cleaned
afterward. Admission uses a 16,000-byte canonical JSON UTF-8 ceiling; byte counts
are synthetic units, not model tokens. No generated answers are graded here.

The baseline is `5fc1e66`; production search froze at `84e7f50` before inspecting
held-out outcomes. Related templates, reused names/values, repetitive generic
distractors, warned-about quoted instructions, and answerable-only questions
limit generalization. Old facts do not simulate delayed indexing. This fixture
does not establish abstention calibration or broad injection resistance.

## Search change and tradeoff

All SQL preparation, probes, and ranking share the existing cooperative 50 ms
deadline and one read snapshot. Small eligible archives (up to 512 entries)
retain the previous BM25 ordering. For larger archives, search probes each of
the original first 16 terms for at most 33 eligible matches. Terms with 1–32
matches define a smaller union for BM25 ranking. If no such term exists, broad
matches are returned in reverse archive order. Thread, kind, and completion
filters apply consistently to probes and ranking.

This favors distinctive words. When one exists, matches containing only broad
terms are excluded; an incidental rare word can therefore reduce recall. Broad-only
queries now favor recency. Returned-row bounds are not hard scan-work bounds:
filtered rows and postings can still take work, and lock waiting, native work
between SQLite callbacks, and OS scheduling can exceed 50 ms. Timeout fallbacks
remain explicit in manifests and retain mandatory context.

Exploration on development cases rejected rank-only SQL changes, global term
frequency selection, larger query term sets, and descending term probes: they
left timeouts or lost recent/small-corpus evidence. The final policy requires no
schema migration, vocabulary table, domain word list, or model call.

## Source-selection results

| Run | Routine entries | Before: all expected sources | After: all expected sources | After: timeout rate |
| --- | ---: | ---: | ---: | ---: |
| Development | 0 / 1,000 / 10,000 | 30/30 at each | 30/30 at each | 0% at each |
| Development | 25,000 | 3/30 | 30/30 | 0% |
| Held out | 0 / 10,000 | 70/70 at each | 70/70 at each | 0% at each |
| Held out | 1,000 | 70/70 | 69/70 | 1.43% |
| Held out | 25,000 | 7/70 | 70/70 | 0% |
| Separate paired repeat, all probes | 25,000 | 10/100 | 99/100 | 1% |

Before tuning, all 25,000-entry searches timed out; the ten explicit correction
pins survived independently of search. In the paired repeat, selection latency
changed from **53.22/57.23 ms** p50/p95 to **24.24/32.16 ms**. Maximum candidates
were 26 against the bound of 32; maximum input was 10,844 bytes against 16,000.
No measured run lost a required constraint or selected a foreign-thread source.
Both adverse after-change timeouts remain in the published data. This machine
was also serving the user's other work; wall-clock comparisons are observations,
not controlled throughput certification.

## 10,000-call runtime replay

The same synthetic mechanical replay at `84e7f50` completed 10,000 generation,
count, and matching-dispatch checks, plus 5,000 tool continuations and call/output
pair checks. All admission and candidate bounds passed as the archive grew to
25,000 events.

| Measurement | Before | After |
| --- | ---: | ---: |
| Incomplete archive retrievals | 8,547/10,000 (85.47%) | 66/10,000 (0.66%) |
| Elapsed seconds | 738.51 | 274.33 |
| Maximum selected candidates | 20 | 20 |
| Retained Python allocation growth | See original report | 966,961 bytes; bound 33,554,432 |

Maximum input was 13,718 synthetic bytes against 131,072, with the configured
4,096 output reserve and 1,024 margin. Peak Python-traced allocation was
2,101,252 bytes. Separate macOS RSS sampling every five seconds produced 52
samples from 40,896 to 42,016 KiB (first-to-last increase 1,120 KiB). Sampling
started about 15 seconds into the process; this is not its startup peak or a
proof against native-memory growth on other workloads.

## Reproduction and remaining gate

Verification passed **1,973 repository tests** in 136.17 seconds, with the same
three existing dependency/fork warnings. The initial full run had 1,972 passes
and one unrelated category-validation test failure: its 5 ms budget expired
before the intended type check. That test now fixes the clock and directly
rejects invocation of caller-supplied hashing; all 88 category tests and the
subsequent full suite passed. No category production code changed. Independent
review covered search correctness, benchmark design, and these reported figures.

From the corresponding checkout, using its configured Python environment:

```bash
python scripts/context_retrieval_benchmark.py --split all --noise-counts 25000 > retrieval.json
python scripts/context_runtime_replay.py > runtime-replay.json
```

The [raw data directory](2026-09-06-context-retrieval-data/) contains every final
development, held-out, and paired-repeat report, the new replay and RSS samples,
and a SHA256 manifest. The first runtime run remains in the historical report.

The [preliminary live comparison protocol](2026-09-06-context-continuity-protocol.md)
separately freezes 100 questions across dynamic context, actual LocalAgent context
construction, and a new append-and-compact comparator. Human correctness and
relational-continuity review remain required before claiming the proposed 95/100
quality gate. Lighthouse expansion and normal-use rollout follow that evaluation.
