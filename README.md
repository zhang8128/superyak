# Lighthouse

Lighthouse is an implementation-neutral interchange protocol for independently governed knowledge systems. It lets each participant choose which lighthouses to connect to, in which domains, for which actions, without requiring one universal server or authority.

Version 0.1 is deliberately offline and falsifiable. Its original proof shows that one Hyper workflow-dependency claim can be translated into an aDNA typed-port claim while both local evaluators preserve satisfaction. It also proves negative cases: a wrong type mapping fails, Hyper lease semantics remain unmapped, and recall permission does not become permission to inject or reshare memory.

The independent Engram recall profile adds an opaque shadow-trace adapter and a two-turn measurement fixture. It shows a policy-scoped neighbor supplying one missing memory while a denied relational memory stays out; an intentionally unsafe control demonstrates that the same privacy instrument detects the forbidden exposure.

## Quickstart

Requirements: Node.js 24 or newer and Corepack.

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm check
pnpm build
pnpm proof
pnpm recall:proof
pnpm policy:fixtures
```

`pnpm proof` prints one canonical JSON conformance report. A successful report contains `"passed":true`, the exact profile IDs and bridge digest, and 15 named checks with their evidence digests.

`pnpm recall:proof` prints a separate canonical report with 14 named checks. In the fixed fixture, local-only right-turn recall is `0.5`, policy-scoped recall is `1.0`, scoped forbidden exposure is `0`, and the indiscriminate negative control records one forbidden and unauthorized selection. The reference proof's receipts say `"injected":false`; a live receiver's receipts say `true` only when their `delivered` list is non-empty, and the schema enforces the equivalence.

`pnpm policy:fixtures` regenerates the shared policy decision fixtures; `git diff --exit-code fixtures/policy-conformance` must be clean.

## CLI

Run the reference proof:

```bash
pnpm lighthouse prove --fixtures fixtures
```

Validate a sealed artifact's strict schema and digest:

```bash
pnpm lighthouse validate fixtures/policy/workflow-policy.json
```

Evaluate a local policy request:

```bash
pnpm lighthouse authorize \
  fixtures/policy/workflow-policy.json \
  fixtures/policy/recall-request.json
```

Run the memory-shaped conformance experiment:

```bash
pnpm recall:proof
```

Replay a receiver's 1.1 export against its own labels under a preregistration:

```bash
pnpm lighthouse recall shadow \
  --preregistration fixtures/engram/receipts/preregistration.json \
  --export fixtures/engram/receipts/receiver.engram.json \
  --labels fixtures/engram/receipts/receiver.labels.json
```

The CLI consumes data files only. A bridge descriptor's implementation identifier is resolved from locally installed code; Lighthouse never imports executable code named by received artifacts.

## Repository

```text
schemas/              Generated language-neutral JSON Schemas
packages/protocol/    Canonical JSON, digests, and artifact contracts
packages/calculus/    Restriction, bridge, witness, and policy laws
adapters/hyper/       Hyper graph projection and evaluator
adapters/adna/        aDNA lattice projection and evaluator
adapters/engram/      Opaque Engram recall-trace projection and evaluator
bridges/hyper-adna/   Scoped reference translation
packages/conformance/ Law harness, reports, and CLI
packages/recall-evaluation/ Policy admission, rank fusion, metrics, and receipts
fixtures/policy-conformance/  Shared policy decisions for other implementations
fixtures/             Valid and negative-control source systems
spec/                 Normative 0.1 summary and vocabulary
```

Read [the normative 0.1 summary](spec/lighthouse-v0.1.md) for core protocol requirements. The memory profile has its own [normative summary](spec/engram-recall-v0.1.md) and [design rationale](docs/superpowers/specs/2026-08-30-engram-recall-conformance-design.md).

## Boundaries

The passing report applies only to the declared Hyper and aDNA profile versions, reference bridge digest, and fixture domain. It is not a claim that arbitrary systems or all claims are equivalent.

Version 0.1 has no networking, discovery, registry, replication, blockchain, global reputation, or consensus. The Engram adapter consumes portable offline traces; it does not open a live database, deliver memory content, or change retrieval. A live exporter and Starshine attestations remain later work. Trust stays local, directional, purpose-bound, time-bounded, and non-transitive.

Memory permissions are intentionally separate: `read`, `recall`, `suggest`, `inject_context`, `derive`, `retain`, and `reshare` do not imply one another. Revocation can stop future authorized access; it cannot force a recipient to forget plaintext already disclosed.
