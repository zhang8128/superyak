# Atlas research POC engineering review

Reviewed on 2026-09-12. No unresolved blocking implementation finding remains
within the bounded local POC scope. The observed run demonstrates source capture,
separate private/shared memory, explicit publication, and durable research
artifacts. It does not establish research benefit, independent scientific
validity, or Stampede capacity.

The delegated reviewer implemented the Atlas bridge but did not implement the
controller. Controller review was independent of its implementation; this is
an engineering review, not an external scientific assessment.

## Scope and verification

Reviewed `research_poc/experiment.py`, `research_poc/__main__.py`, their tests,
and the Atlas integration boundaries. Read the completed local diagnostic at
`.engram/research-poc/live-01` without issuing model requests or changing its
journal, stores, or exports. The original Atlas checkout was preserved.

Fresh combined verification:

```
/Users/kairos/Projects/superyak/engram/.venv/bin/python -m pytest engram/tests/test_atlas_poc_bridge.py engram/tests/test_research_poc.py -q
31 passed in 2.21s
```

Bridge tests use actual frozen Atlas code, validation, filesystem journals,
publication generation, and browser/Obsidian rendering, replacing only model and
literature HTTP replies. Controller tests use actual Engram SQLite/sharing with
controlled research boundaries. Coverage includes completed-call reuse,
interrupted publication recovery, explicit retry requirements, source quotation
checks, private/shared isolation, implementation pinning, and persistence of
community identity when moving a run directory.

## Resolved findings

- Rejected model responses previously lost their token usage from summaries.
  Error artifacts now retain normalized results or raw Atlas responses, and
  accounting includes rejected attempts while marking unknown usage explicitly.
- A crash after writing a result but before finalizing its attempt could leave
  misleading interruption accounting. Resume reuses the durable result and
  repairs attempt status; summaries recognize the known returned result.
- Atlas validation exceptions cannot be directly pickle-round-tripped because
  their constructors require additional arguments. Worker boundaries now convert
  failures to a transportable built-in exception after saving detailed failure
  artifacts. The worker entry point also resides in an importable module for
  spawn-based processes.
- Atlas permits one in-flight HTTP request per process. Separate worker
  processes provide the requested two-process cap without changing its transport
  guard or sharing SQLite owners.
- Future experiments now pin hashes of the POC implementation. Resuming against
  changed implementation files is refused. Persisted cell identities preserve
  agent attribution and sharing audiences when a run directory is copied.

## Completed live artifact checks

The final invocation artifact reports **20 completed turns and 40 calls**, with
no failures. The filesystem independently contains 40 attempt artifacts and
40 returned-result artifacts. These are five cells, each with two researchers
and two rounds; the continuing community remains a separate cell.

For both researchers in the second round, saved extraction manifests confirm:

| Cell | Actual admitted memory |
| --- | --- |
| `i0-s0` | None |
| `i0-s1` | The other researcher's first-round shared finding only |
| `i1-s0` | The researcher's own first-round private note only |
| `i1-s1` | Own private note and the other researcher's shared finding |
| `community` | Own private note and the other researcher's shared finding |

All ten inspected second-round requests admitted every supplied memory record:
`omitted_records=0`. Neither researcher's own shared finding was recalled as
peer memory. First-round community requests began with empty memory context.

For the completed community, the reviewer additionally checked:

- All four saved candidate quotations and all four source-review results pass
  the frozen Atlas validators against their exact cached documents. Review
  manifests contain no prior research records.
- Its four recorded findings exist in the current publication bundle, remain
  `proposed`, and have no named scientific reviewer. Receipts report successful
  capture/current publication with the actual logical-agent session IDs.
- Both `prediction` and `regulation` publication packages validate. Their seed
  grant configuration files remain byte-for-byte unchanged.
- `Research/index.html`, `Research/Start Here.md`, and `Research/Atlas Map.canvas`
  exist and are nonempty. The browser contains all four saved record IDs.
- All four published Engram copies match their stored content digests and have
  the public envelope shape. None of the four complete private notes appears in
  the generated research exports.

No pending community publication/export error was observed. Completed-resume
behavior is covered by the automated tests above; this review did not invoke
the live model or rerun the live controller.

## Accepted interpretation and provenance limits

**Source exposure varies with memory.** The two source snapshots are fixed, but
the bounded compiler can choose different source passages when memory occupies
input capacity. For example, the CellRank second-round agent-1 request selected
9 passages and omitted 16 in `i0-s0`, versus 8 selected and 17 omitted in
`i0-s1`, with different selected IDs. This is not a comparison with identical
source evidence in every request. A subsequent controlled comparison should
use a fixed common passage packet or reserve enough capacity to retain it under
every treatment. Actual selected passage IDs are retained for this diagnostic.

**Source support uses the same model.** Extraction and review are separate,
fresh requests to `qwen3.8:27b-mlx`; source-only review is useful grounding but
not independent scientific validation. Exact quotation checks do not establish
the truth or completeness of a surrounding interpretation. Records remain
proposed, and provider coverage remains explicit, including abstract-only
coverage where full text was unavailable.

**The first run predates implementation pinning.** `live-01` began during
development. It retains the Atlas source manifest, exact paper/document
snapshots, model metadata, request manifests, and returned outputs, but its
Superyak Git revision does not capture all contemporaneous uncommitted
controller changes. It should remain identified as the first development
diagnostic. The current CLI refuses to treat an already-started, unpinned run as
a newly pinned experiment. Future runs start with implementation hashes in
place. Temperature zero has no fixed-seed or deterministic-execution guarantee.

This small run supports claims about observed memory routing, recording, and
recovery mechanisms. It does not support a causal estimate of memory benefit,
a claim of scientific discovery, or a capacity prediction for different
hardware or larger research populations.
