# Local Atlas + Superyak research POC

**Current model requirement:** [American models only](model-policy.md), with
Gemma 4 preferred. The original Qwen defaults and live measurements below are
historical. Do not start a fresh POC with those defaults; eligible replacements
need explicit selection and compatibility checks. Preserve old run artifacts.

This executable tests actual public-source research with individual and explicitly
shared memory on the Mac, independently of Intel, Slurm and Stampede3. It uses
Atlas's evidence pipeline and Engram's real SQLite and sharing implementation.
The first workload asks how measured cellular state predicts fate, using CellRank 2
and the Weinreb lineage-tracing study. It needs no patient or participant details.

## Run

After `make setup-engram`, with an existing compatible model served on loopback
port 11434:

```sh
make research-poc
```

Defaults: this checkout's bundled `atlas/`, model `qwen3.8:27b-mlx`, and output
at `.engram/research-poc/local-pilot`. No model is downloaded. Override explicitly:

```sh
make research-poc RESEARCH_POC_ARGS='run --atlas-source /path/to/atlas-workbench --model existing-model --output .engram/research-poc/round-01'
make research-poc RESEARCH_POC_ARGS='prepare'
make research-poc RESEARCH_POC_ARGS='status'
```

`prepare` snapshots code, reads the pilot question, retrieves the two DOI-matched
documents through Europe PMC and checks the installed model. It makes no inference
calls. `run` also performs preparation, then runs/resumes all five cells. `status`
reads local results without contacting the model or literature provider. Open the
output's `report.md` or `report.html` for the comparison and scoped findings.

## Experiment

| Cell | Individual recall | Shared recall | Purpose |
| --- | --- | --- | --- |
| i0-s0 | Off | Off | Source-only reference |
| i0-s1 | Off | On | Other-agent published findings |
| i1-s0 | On | Off | Owner's prior private reflections |
| i1-s1 | On | On | Combined condition |
| community | On | On | Separate continuing community |

Every cell has two stable logical researchers and two rounds. Each researcher
starts with a different paper; assignments swap in round two. A round uses only
earlier rounds' memory. The author cannot recall its own shared publication through
the shared channel. Private reflections persist only when individual memory is on;
all model outputs remain in an operator audit independent of recall settings.

Publication requires both an explicit `publish=true` model decision and a supported
verdict from a fresh source-only model review. The public candidate and citation are
copied through Engram's audience-bound `share()` operation; the private reflection
field is never copied. The scoped finding is also recorded in that cell's isolated
Atlas journal, with a stable logical-agent identity and idempotency key. Atlas
generates browser and Obsidian views. A model's supported verdict still leaves the
claim **proposed**. It is not independent expert or experimental verification.

Two worker processes can issue requests concurrently; Atlas's per-process HTTP
semaphore permits only one outstanding request in each. This is a request cap,
not a statement about how many agents the hardware can sustain. Use
`--concurrency 1` in a new output directory for a serial timing comparison.

## What is recorded

- Frozen Atlas Python/public JSON data and its three browser assets, file hashes,
  source repository revision and dirty flag. For bundled Atlas, the revision is
  Superyak's; [Atlas's import manifest](../atlas/IMPORT-MANIFEST.json) separately
  records original upstream provenance. The active `.atlas` journal is not copied.
- Actual Europe PMC metadata, passage coverage and immutable document hashes.
  An abstract-only retrieval stays labelled abstract-only.
- Every attempt, response, available model-reported usage, elapsed time, exact
  request/input hashes, and memory IDs supplied versus actually admitted.
- Separate private stores, a cell-local published store, attributed Atlas receipts,
  and readable proposed findings. Audit retention is not an access-control system
  against the operator: all local files remain readable to the user running it.

The comparison fixes the question, source cache, model, prompt and context budget.
Memory competes with additional source passages for the byte budget, so the actual
passages admitted can differ between cells. The report lists those passage IDs;
the first run is not a clean causal comparison of memory alone. A subsequent
efficacy experiment should reserve a fixed source packet in every condition.
Temperature is zero; there is no fixed seed or guarantee of deterministic model
execution. Two rounds and one small question cannot establish a scientific benefit
from memory. Differences in accepted claims, cost or context admission are diagnostic
observations, not causal quality scores. Source review uses the same model family.

## Recovery and iteration

Repeat the same command with the same pinned implementation to reuse completed
calls and findings. Each returned call
is saved before memory/publication, and stable IDs repair interruption while
applying results. An unsuccessful or interrupted HTTP request may have completed
remotely. It stops that cell and records what is known. After inspecting the audit,
`--retry-interrupted` explicitly permits another attempt and retains both attempts.
Other cells continue. Unknown token usage remains marked incomplete.

Comparison rounds/configuration stay fixed for an output directory. To extend only
the continuing community while retaining its identities:

```sh
make research-poc RESEARCH_POC_ARGS='run --community-rounds 3'
```

This small POC cycles the same two papers; extending it tests continuity, not a
growing literature search. A new output directory is required for changed code,
model, comparison rounds, concurrency or a later experimental design. The next
research iteration should add a broader fixed task set and independent outcome
checks before making claims about research improvement. Intel backend and
Stampede infrastructure tests can then run against the same research interfaces.

The monorepo import changed the CLI's default Atlas source. The implementation
pin includes `research_poc/__main__.py`, so this CLI cannot resume execution of a
historical run pinned to the previous bytes. Preserve its fingerprint. The old
`.worktrees/atlas-research-poc` implementation and run artifacts remain available
locally; use that original implementation for compatible execution, or choose a
new output directory for current code. The new CLI can still inspect old results:

```sh
make research-poc RESEARCH_POC_ARGS='status --output .worktrees/atlas-research-poc/.engram/research-poc/live-01'
```

This historical path belongs to the original development checkout and is not
included in a fresh clone. Existing frozen Atlas snapshots keep their exact code
even if the selected source checkout changes later. See the
[integration plan](atlas-integration.md) for the next research interfaces.

## Verification

```sh
cd engram
uv run --locked --extra dev python -m pytest tests/test_research_poc.py tests/test_atlas_poc_bridge.py -q
```

Tests use real Engram storage/sharing and actual Atlas validation, immutable drafts,
browser and Obsidian rendering. Only model/literature HTTP boundaries use controlled
fixtures. Atlas integration tests use the bundled source and fail if it is
missing. `ATLAS_TEST_SOURCE` remains an explicit alternative source selector.
The [live verification report](superpowers/reviews/2026-09-12-atlas-poc-verification.md)
records 20 completed research turns, 40 real model calls, 12 shared findings, and
a completed-run replay with zero additional model calls. It also states the
source-exposure and development-run provenance limitations.
