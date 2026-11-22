# North-star test 1: the pre-registration

Committed before the run, 2026-11-22. The spec is
[docs/superpowers/specs/2026-11-22-north-star-test-1-design.md](../../../docs/superpowers/specs/2026-11-22-north-star-test-1-design.md),
revision 4, approved by a fresh reviewer after four rounds. Nothing below changes after the run starts. A finding
during the run is reported; it doesn't change this page.

## Inputs, fixed

| What | Value |
| --- | --- |
| Code | `engram/experiments/northstar/test1.py` at 245a8537 (95 tests; 117 with the Atlas bridge and open tests) |
| Plan | `results/test1-plan-2026-11-22.json`, sha256 `e56c7362adb5c59a743fe736e0aec0bb0ca54336fde24456d2ab53b6469c98a7`, 1,503,184 bytes |
| Questions | 800 qualifying from HotpotQA train-00000 (revision 1908d6af), less the 3,926 fresh-router ids; 3,358 draws; seeds 2026112201, 02, 03 |
| Classes | year 148, person 205, other name 447 |
| Split | 400 corrected, 400 controls; overlay 398 rows, sha256 `bb2780fdc35d72fc9490fa3808a9dfeaf316a5f3cf3a287fbd10c833d0965097` |
| Corpus | corpus v0, digest `adb91daf…c8c43` |
| Index before the correction | `index.bin`, sha256 `b3dd2e6dba28eef125bdecce5330564e78974e37bb03e1d8720a6a26d92f651d` |
| Index after | built during the run from corpus v0's export with the overlay applied; its sha256 goes in the results |
| Model | `nemotron-mini:latest` through Ollama, digest `ed76ab18784f5a01…`, 4.2B, temperature 0, prompt v2 |
| Embedder (B's rerank) | fastembed `nomic-ai/nomic-embed-text-v1.5`, local cache |

## Arms

E (BM25 and one hop, Atlas claims, re-asks only what `retraction_impact` names), E-all (E's retrieval, re-asks
everything), B-all (BM25 top 100 with dense rerank, re-asks everything), B-cache (B's answers, never re-asked), closed
book (the corrected half with no evidence). One model, one prompt, two leads.

## Measures

- **Primary, on the corrected half:** E against B-all. That's exact match after the correction, paired with a 95% CI,
  plus after-correction calls. Success means E within 5 points (the CI's lower end above −5) at under 60% of B-all's
  calls. A CI straddling −5 is borderline. Failing the calls test fails, whatever the accuracy.
- **Secondary:**
  - E against E-all on the corrected half;
  - the same two comparisons within each class, and within year and person together (`clean_classes`, the
    substitutions that keep their kind);
  - the retrieval gap before the correction (each arm's source support and exact match on all 800);
  - targeting (corrected questions E re-asks; controls it re-asks);
  - stale answers beside the closed-book arm;
  - controls unchanged;
  - the history check through `history_as_of`;
  - cost (calls, tokens, time, and building E's records and the corrected index).
- **Known limits, stated before the run:**
  - inside "other name", a substitute can change kind; the sample read before this commit found about 7 people among
    25 other-names, plus 2 demonyms;
  - the person cue can catch a building or organisation with a founding-date range.

## The command

```
PYTHONPATH=engram:atlas uv run --no-project --with pyarrow python -m experiments.northstar.test1 run \
  --plan engram/experiments/northstar/results/test1-plan-2026-11-22.json --full \
  --corpus ~/Projects/superyak-data/multihop/builds/enwiki-20261101-v0.sqlite3 \
  --index ~/Projects/superyak-data/multihop/rs/index.bin \
  --store ~/Projects/superyak-data/northstar/test1/store.db \
  --capped-sh <scratchpad>/capped.sh --out ~/Projects/superyak-data/northstar/test1/results.json
```

The result goes into RESULTS and onto issues #8 and #9 whatever it is, with its failures.
