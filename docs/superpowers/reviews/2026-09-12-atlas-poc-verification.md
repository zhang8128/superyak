# Atlas + Superyak local POC verification

The POC uses genuine Europe PMC documents, the locally loaded
`qwen3.8:27b-mlx` model, actual Engram stores/sharing and actual Atlas validation,
journals and browser/Obsidian exports. It runs independently of Stampede or Intel.

## Development run

Raw local artifacts are retained in
`.worktrees/atlas-research-poc/.engram/research-poc/live-01/`.
This first run was assembled during implementation. Initial process startup
exposed Python's inability to pickle a worker defined in package `__main__`;
no model calls happened in that failed launch. The worker was moved into an
importable module and the live run proceeded. While it ran, tests/review improved
failure accounting, process exception handling and persisted cell identities.
The model instructions, selected model and context budget were unchanged across
its calls. Exact Atlas source hashes and per-request manifests were captured.

Implementation pinning was added after this development run started. The final
code hashes are recorded separately for its resume check; they do not establish
that every initial turn executed the final controller version. New experiments
pin the complete POC Python files before any model call and reject source changes
on resume. This is a working mechanism diagnostic, not a preregistered scientific
comparison or deterministic replication claim.

## Research boundaries

The question is Atlas's public `q-fate`: how measured cellular state predicts fate.
The cached papers are CellRank 2 (DOI 10.1038/s41592-024-02303-9, retrieved full-text
excerpts) and Weinreb et al. (DOI 10.1126/science.aaw3381, retrieved abstract only).
Source coverage is preserved in the audit and generated findings.

Each of four memory cells and the separate community has two logical researchers
and two rounds. Researchers swap document assignments in the second round. All
source review is a fresh source-only call to the same model; accepted findings
remain proposed. Repeated claims are not independent scientific evidence.

All supplied private/shared memories in the four factorial cells were admitted
in the expected conditions. However, additional source passages compete with
memory within the fixed request budget. Actual CellRank passages differed across
conditions, so even matched source hashes do not imply matched evidence exposure.
Do not use this run to estimate memory's causal effect on research quality.

## Atlas lookup profile

A read-only profile of the active Atlas dataset reproduced the context delay on
this Mac, independently of Intel:

| Measurement | Observed |
| --- | ---: |
| Live context lookup | Exceeded 20-second bound |
| All 610 file/JSON reads in that bounded run | 0.062 seconds |
| Isolated public pilot context lookup | 0.008 seconds |
| Temporary process-only verification deduplication | 3.98 seconds |

Repeated canonicalization/verification of the same snapshot dominated the initial
profile. The temporary diagnostic preserved the public validation boundary and
removed repeated inner-loop validation; it did not edit the Atlas checkout. A
small targeted Atlas fix is therefore a separate follow-up, not an Intel blocker.
Full profiling evidence is in the retained `.engram/poc-notes/context-profile.md`.

## Verification results

The isolated Atlas snapshot has its own immutable journal;
no active Atlas service, original journal, model installation, remote cluster or
Stanley node was changed.


| Cell | Completed turns | Calls | Proposed source-supported candidates | Explicit shared findings | Memory supplied/admitted |
| --- | ---: | ---: | ---: | ---: | ---: |
| community | 4 | 8 | 4 | 4 | 4/4 |
| i0-s0 | 4 | 8 | 4 | 0 | 0/0 |
| i0-s1 | 4 | 8 | 4 | 4 | 2/2 |
| i1-s0 | 4 | 8 | 4 | 0 | 2/2 |
| i1-s1 | 4 | 8 | 4 | 4 | 4/4 |

The live run completed **20 turns / 40 returned model calls in 567.70 seconds**,
with no failed attempts. The model reported 61,851 prompt tokens and 9,148
output tokens; all returned calls included those fields. These are provider-reported
counts, not an independently measured tokenizer total. All 12 shared findings had
current Atlas publication receipts and browser/Obsidian exports.

The completed run replay took 0.203 seconds with **zero new model calls**.
All 152 audited call, turn and immutable draft files retained identical hashes.
Its pre-pin development provenance is explicitly retained in
`development-provenance.json`; final source pinning is used for this replay.
A new `make research-poc ... prepare` invocation also passed under the final code.

Independent regression verification: **2,472 passed, two optional live-config skips**
in the full Engram suite, including configured Lighthouse interoperability tests.
A fresh focused run after the final identity/pinning additions passed **31 POC tests**.
The independent review is [recorded here](2026-09-12-atlas-poc-review.md).

## Continue

From the main repository, `make research-poc` starts a fresh pinned experiment.
The completed development run can be inspected with:

```sh
make research-poc RESEARCH_POC_ARGS='status --output .worktrees/atlas-research-poc/.engram/research-poc/live-01'
```

Open the run's `report.md`, or its community Atlas view at
`cells/community/atlas-project/Research/index.html`. The next efficacy round needs
fixed evidence exposure and independent assessment, alongside more varied tasks.
The current implementation exercises memory continuity/sharing and research
recording; Intel inference and cluster scale remain unmeasured.
