# Atlas integration and execution plan

Superyak now carries Atlas alongside Engram and Lighthouse so a contributor can
install one checkout, inspect a public research pilot offline, and exercise the
existing Atlas/Engram memory POC. The next integration joins their existing
interfaces around a reproducible research turn. It does not require replacing
the workbench, memory stores, or interchange formats.

## Responsibilities and present connections

| Component | Owns | Present boundary |
| --- | --- | --- |
| Atlas | Questions, source versions/passages, proposed findings, relations, assessments, and human views | `ResearchInbox`, `ResearchRunner`, validation and publication APIs |
| Engram | Individual memory, retrieval, durable histories, and explicit audience-bound sharing | Separate stores and `share()` in the research POC; attributed context sources in chat |
| Lighthouse | Scoped interchange, content binding, publisher/receiver policy, and projections | Atlas publications and Python/TypeScript checks; existing Engram receipts and aDNA projection |
| aDNA | Selected project documents and workflow/lattice descriptions | Explicit local `AdnaSource` inputs and native lattice projection |
| Execution | Model transports, placement, request limits, job lifecycle, and checkpoints | Local Ollama research, bounded K3/GLM text probes, and the synthetic Stampede campaign |

The current Atlas role rotation shares one model and project journal. The POC
already gives two logical researchers separate Engram stores and explicit
sharing, but it is a fixed two-paper experiment. Neither workflow implements the
planned whole-cluster research population. Model adapters also differ: Atlas's
`Ollama` compiles research schemas and passage manifests; Stampede's `LocalModel`
accepts chat messages; Engram's context providers have their own counting and
dispatch contract. Sharing a repository does not make these APIs interchangeable.

## Phase 1: Self-contained source and offline demonstration

This import preserves the `workbench` package under `atlas/`, its public seed,
tests, and relevant guides. Run from the repository root:

```sh
make setup
make atlas-demo
make atlas ATLAS_ARGS='context q-fate'
make check
```

The demo refreshes `.engram/atlas/project` without creating research drafts.
`ATLAS_PROJECT` selects another destination. Atlas and Engram tests run in
separate processes because the POC requires its own frozen `workbench` import.
POC tests use bundled Atlas by default and no longer depend on a developer's
external checkout. Interoperability checks validate the pilot's publications,
digests, and policy decisions in Python and TypeScript.

Acceptance is a fresh checkout that renders the public pilot after setup with
no model or literature requests, passes the component and interoperability
checks, and produces an extracted source archive that can load Atlas and the
POC without an editable install. The archive must omit live journals, personal
notes, databases, keys, and unrelated documents. Staging Atlas source leaves the
existing synthetic Stampede campaign's behavior unchanged.

The [import manifest](../atlas/IMPORT-MANIFEST.json) records original selected
bytes from a dirty working tree; it is not a checksum of later integration edits.
The [migration record](monorepo-migration.md) describes the preserved standalone
checkout and excluded legacy engine/archive. An open-source release still needs
the owner's repository-wide license choice; no license is assigned by this plan.

## Phase 2: One research turn across evidence, providers, and memory

Keep `ResearchInbox` as the evidence journal and Engram as the memory owner.
Define a small research-model adapter at the existing injected `model` boundary
of `ResearchRunner(project, provider=..., model=...)`. The request identifies the
task/question, fixed source packet, selected prior records, recalled memories,
output schema, and budget. The result preserves the actual model identity, raw
response, complete assistant state where needed, context manifest, usage, and
attempt status. Reuse existing transports through explicit adapters.

Start with two logical researchers, one fixed public or synthetic task, and
separate individual stores plus an audience-bound shared store. Each turn reads
Atlas evidence, selects the agent's permitted recollection, makes a bounded
generation/review request, then records a supported proposed finding through
existing validation and idempotent `ResearchInbox.record`. Private reflections
remain memory. Claims and quotations must resolve to current source passages;
recalled text alone cannot satisfy evidence validation.

Checkpoint returned responses before applying memory or publication effects.
Retain task, source, model/protocol, prompt, and implementation versions so a
retry cannot silently become another experiment. Preserve failed and uncertain
attempts. K3/GLM adapters must retain required assistant state across calls rather
than flattening every response to content text.

Acceptance: a scripted transport produces one source-supported proposed finding,
one private reflection, and one explicit share. The other researcher can recall
that share only for the configured audience. Restart after a saved response and
prove zero repeated completed calls and one publication. A changed source digest
must invalidate dependent support or mark it stale. Then run the same bounded
case against an explicitly selected existing local endpoint and retain its
actual observations, including failures.

## Phase 3: Correction, disagreement, and selected aDNA interchange

Build a fixed task set containing an initial source, a correction, a conflicting
source account, and an unsupported proposed claim. Reserve identical source
passages across memory conditions; memory must not change evidence exposure as
it can in the first POC. Keep the continuing community separate from controlled
comparisons. Preserve distinct source accounts and explicit disagreements;
repeated agent summaries do not become additional studies.

Attach one explicit local aDNA project through the existing `AdnaSource` API.
Retain its origin-qualified identifiers, original text, full content hashes, and
bounded reads. Project context can help select a task; it does not automatically
become a supported scientific claim. Export one selected proposed result and
its provenance through the existing Lighthouse/aDNA projection boundary. Peer
transport should consume that bounded publication, not a copy of private stores.

Acceptance: correction makes stale support visible without erasing its history;
two conflicting accounts remain distinguishable; an unsupported claim is held;
private memory is absent from the exported artifact. An independent assessor
checks source fidelity, relevance, scope, and correction handling. Record cost,
latency, and failures separately from quality. Local aDNA compatibility does not
demonstrate mesh access, private-vault access, or completed peer delivery.

## Phase 4: Measured execution on Stampede3

The planning premise is the whole Stampede3 machine. Preserve the agreed eight
lead identities: four Kimi K3 and four GLM-5.3, each with its own history, plus
the Qwen3.8-27B worker preference. Eight identities do not require eight loaded
replicas. The existing launcher remains a bounded synthetic preset and its
default model settings do not implement that preferred population.

First use the same fixed evidence packet to measure provider correctness,
supported backend/precision, memory use, latency, useful request rate, queueing,
and checkpoint recovery on the available node classes. Hardware placement and
capacity are results of these probes. CPU, PVC, and H100 paths require their own
measurements; no throughput or simultaneous fit is established by this import.

Next connect the phase-2 research turn to the scheduler, sharing model services
while keeping identities and histories separate. Run parallel memory-condition,
population, and request-cap comparisons with serial references; retain the
separate continuing community. Use measurements to set replica placement and
request limits within the whole-machine plan. Acceptance includes recovery from
worker interruption, reproducible source/version selection, identity isolation,
auditable calls/publications, and an observed capacity report. Model downloads,
service deployment, and Slurm submission are execution work beyond source import.

## Parallel work after the import

| Lane | First deliverable | Integration point |
| --- | --- | --- |
| Research architecture and memory | Fixed task packet, per-agent store adapter, explicit evidence/recollection labels, restart case | Phase-2 turn and phase-3 correction tests |
| Model providers | Research schema adapter with context/usage manifests and retained K3/GLM assistant state | Same scripted and optional live task packet |
| aDNA and interchange | Explicit local project input and one bounded, attributed result projection | Source/version contract and publication policy checks |
| HPC execution | Backend probes, measured placement, request caps, and scheduler adapter | Same research turn and interruption semantics |

The first two lanes meet on a passing offline turn before a live comparison.
aDNA work can proceed on public fixtures, and HPC probes can proceed against
synthetic packets independently. Integrate using shared task IDs and source
digests rather than merging each lane's internal state format. Increased claim
counts, recalled memories, or agent populations are operational observations;
research benefit needs the correction and assessment evidence above.
