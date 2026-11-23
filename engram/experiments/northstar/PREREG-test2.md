# North-star test 2: the pre-registration

Committed before the run, 2026-11-22. The spec is
[docs/superpowers/specs/2026-11-22-north-star-test-2-design.md](../../../docs/superpowers/specs/2026-11-22-north-star-test-2-design.md),
revision 3, approved by a fresh reviewer over three rounds. Nothing below changes after the run starts. A finding
during the run is reported; it doesn't change this page.

## Inputs, fixed

| What | Value |
| --- | --- |
| Code | `engram/experiments/northstar/test2.py` at 22caf0f0 (64 tests; 170 with test 1's) |
| Plan | `results/test2-plan-2026-11-22.json`, sha256 `0fe6e10b676ec46ad276eed67381fcc21786e5032505851cf40f24f8ee9588ea`, 631,404 bytes |
| Bridge questions | 800 qualifying from HotpotQA train-00000 (revision 1908d6af), seed 2026112205; 2,843 bridge rows examined (28.1% qualify) |
| Comparison stratum | 300 qualifying, seed 2026112206; 1,224 comparison rows examined (24.5% qualify) |
| Held out | 4,726 ids: the 3,926 fresh-router ids and test 1's 800 |
| Answer classes | bridge: year 164, person 197, other name 439; comparison: person 109, other name 191 |
| Corpus | corpus v0, `enwiki-20261101-v0.sqlite3` |
| Index | `index.bin`, sha256 `b3dd2e6dba28eef125bdecce5330564e78974e37bb03e1d8720a6a26d92f651d` (test 1's index before its correction) |
| Reader | `nemotron-mini:latest` through Ollama, digest `ed76ab18784f5a01…`, temperature 0, prompt v2, two leads |
| Dense rerank | fastembed `nomic-ai/nomic-embed-text-v1.5`, snapshot `e9b6763023c6…` |
| Cross rerank | fastembed `BAAI/bge-reranker-base`, snapshot `2cfc18c9415c…`; its tokenizer truncates at 512 tokens, `longest_first` |
| Pools | B: BM25 top 100. G: B plus the out-links of BM25's top 5 (median 126 bridge, 120 comparison; 102 to 226). W: BM25's top N, N being that question's G size; matched exactly on all 1,100 (none short) |

## Arms

E (BM25's top 1 and its best-scoring out-link, test 1's E), and B, G and W under each of the dense and cross rerankers,
each choosing two leads. One reader, one prompt.

## Measures

- **Primary, on the 800:** answer-lead recall at two, G-dense against W-dense, paired, 95% CI. The graph earns its
  place if the lower end is above 0 and the point estimate is at least 5 points. A CI straddling 0 is "no measured
  gain".
  - Two further outcomes are named, which the spec's prose leaves open: "measured gain under the margin" (the lower end
    above 0, the estimate under 5) and "measured loss" (the CI wholly below 0).
- **Power, stated before the run:** a true gain of about 4 to 6.7 points is needed for 80% power. A smaller one may
  read as "no measured gain".
- **The comparison stratum, reported apart, never pooled:** each arm's both-gold at two and answer-lead recall at two
  first. Then G-dense against W-dense on both-gold at two, then on answer-lead recall, paired, with 95% CIs.
  - **Ceiling rule:** if W-dense's both-gold at two there is 90% or more, the stratum is labelled "uninformative at
    ceiling", and that applies to every G-against-W verdict in the stratum, never "no gain".
- **Secondary:**
  - G-cross against W-cross;
  - G against B under each reranker, on recall and exact match;
  - each arm's answer-lead recall, both-gold and pool recall;
  - the reader's exact match and F1;
  - whether recall gains reach exact match;
  - truncation: the share of cross-encoder pairs over 512 tokens, per arm;
  - cost per arm: the reader's calls, tokens and seconds; embeddings or pairs computed; rerank wall time; and each
    stratum's wall time.
- **What would count against:**
  - G no better than W under either reranker;
  - recall gains that don't reach exact match;
  - a cross-encoder that wins alone.
- **Known limits, stated before the run:**
  - HotpotQA's bridge questions were built from links (test 2b uses another set);
  - the pool rule is fixed at five seeds;
  - the cross-encoder truncates, which biases cross against dense, though not G against W;
  - HippoRAG 2 and LightRAG are out of reach at 7.2 million leads.

## Seen before this commit, not results

Smokes of 10 questions per stratum, against the real models:
- **Truncation:** 0.4% to 4.7% of cross pairs, G-cross highest.
- **Time:** about 28 s a question, about 8.6 hours in all.
- **Cost:** the cross rerank was about twice dense's wall time per candidate.

No recall or answer number from a smoke is read as a result.

## The command

On the Mac, from `engram/`, at `nice` 10. The whole process tree runs under a 24 GB cap, as test 1 did: `capped.sh`
kills it if the tree's resident memory passes the cap, and macOS has no RLIMIT_AS. The index queries also run under
their own cap inside.

```
<scratchpad>/capped.sh 24 ~/Projects/superyak-data/northstar/test2/run.log -- \
  env PYTHONPATH=.:../atlas nice -n 10 uv run --locked --extra dev --with pyarrow python -m experiments.northstar.test2 run \
  --plan experiments/northstar/results/test2-plan-2026-11-22.json --full \
  --corpus ~/Projects/superyak-data/multihop/builds/enwiki-20261101-v0.sqlite3 \
  --index ~/Projects/superyak-data/multihop/rs/index.bin \
  --bin native/corpus_index/target/release/corpus-index \
  --capped-sh <scratchpad>/capped.sh --out ~/Projects/superyak-data/northstar/test2/results.json
```

The result goes into RESULTS-test2.md and onto the north-star page, whatever it is, with its failures.
