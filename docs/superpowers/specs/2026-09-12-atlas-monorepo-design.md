# Atlas in the Superyak monorepo

The user requested Atlas research in the same repository for an open-source
hackathon, together with a plan for integrating the systems. This authorizes
local source integration and its verification. The first deliverable is a
self-contained checkout with a working offline research demonstration and
existing POC integration. It does not start or move an existing research service.

## Choice and boundaries

Use `atlas/` as a peer of `engram/` and `lighthouse/`. Keep Atlas's `workbench`
Python package name and its relative data layout, allowing its tested interfaces
to survive the move. A submodule would leave hackathon users coordinating several
checkouts; flattening the packages would mix unrelated imports and state. A
component directory follows the monorepo's existing organization.

Import the current workbench source, its tests, public fixtures, and relevant
documentation from the existing Atlas checkout. Record the original Git revision,
per-file hashes and tracked/modified/untracked status. Use a selective source
snapshot rather than adding all ancestry: the upstream repository also contains a
legacy engine, old research collections and local operational material. Keep the
original repository, history, dirty work and live journal untouched. Include only
reviewed dependencies needed by the current workbench. Preserve third-party notices.

A fresh checkout must not require `/Users/kairos/Projects/atlas-workbench` or the
existing research journal. The POC defaults to this checkout's `atlas/`, with an
explicit external source override retained. Existing POC snapshots remain immutable;
a completed historical run can still be inspected regardless of the new default.
A new run uses code from its selected source and records its provenance.

## First integration slice

- A source-only Atlas component, independently usable/testable with Python 3.13.
- Root commands to render an offline pilot, invoke Atlas's CLI with an explicit
  local project, and run Atlas tests and Lighthouse interoperability checks.
- Root setup/check/CI includes Atlas and the POC's real Atlas boundary tests.
- A source archive includes the bundled Atlas implementation, public pilot data,
  static assets and the POC, without local stores or research artifacts.
- Documentation explains component responsibilities, safe state locations,
  contributor setup, migration provenance, license status, and follow-up slices.

The default demonstration creates fresh state under ignored `.engram/atlas/`,
using only the public pilot. Root entry points must not silently attach to the
standalone Atlas journal. Merely installing/importing code does not restart MCP,
continuous Atlas research, a model endpoint or any remote service.

## Integration model and next slices

Engram owns individual memory, retrieval and explicit publication choices.
Atlas owns research questions, source versions, evidence, proposed interpretations,
relations and readable views. Lighthouse owns scoped interchange contracts and
publisher/receiver policies. aDNA supplies compatible project/workflow artifacts;
a future adapter will connect selected inputs/publications, not entire private stores.
Deployment owns model service placement and execution, independently of identity.

After the monorepo slice, work can proceed in parallel on three independently
checkable paths: (a) research/model boundary plus persistent individual histories,
(b) local aDNA input/output and peer-exchange semantics, and (c) model protocol and
hardware probes. Integrate on the same fixed evidence packets. Scientific benefit
requires correction/contradiction tests and independent assessment; increased
memory scores, claims, agents or tokens are not sufficient.

Preserve the agreed four Kimi K3 and four GLM-5.3 lead identities, the Qwen3.8-27B
worker preference, and the whole-Stampede3 planning scope. Eight identities do not
mean eight replicas. The existing launcher is still a bounded synthetic preset;
this import must not relabel it as the whole-machine deployment.

## Acceptance

A clean extracted checkout renders and validates the public pilot without an
external Atlas checkout, model call or network. Imported Atlas tests pass. POC
boundary tests use bundled Atlas by default and verify actual record/export
behavior. The deployment source archive contains required Atlas assets and omits
private state. Existing relevant Engram/Lighthouse checks pass. The import records
what was copied and what changed, and the final report distinguishes completed
integration from planned research/remote deployment.
