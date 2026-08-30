# Lighthouse

Lighthouse is an implementation-neutral interchange protocol for independently governed knowledge systems. It lets each participant choose which lighthouses to connect to, in which domains, for which actions, without requiring one universal server or authority.

Version 0.1 is deliberately offline and falsifiable. It proves that one Hyper workflow-dependency claim can be translated into an aDNA typed-port claim while both local evaluators preserve satisfaction. It also proves negative cases: a wrong type mapping fails, Hyper lease semantics remain unmapped, and recall permission does not become permission to inject or reshare memory.

## Quickstart

Requirements: Node.js 24 or newer and Corepack.

```bash
corepack enable
pnpm install --frozen-lockfile
pnpm check
pnpm build
pnpm proof
```

`pnpm proof` prints one canonical JSON conformance report. A successful report contains `"passed":true`, the exact profile IDs and bridge digest, and 15 named checks with their evidence digests.

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

The CLI consumes data files only. A bridge descriptor's implementation identifier is resolved from locally installed code; Lighthouse never imports executable code named by received artifacts.

## Repository

```text
schemas/              Generated language-neutral JSON Schemas
packages/protocol/    Canonical JSON, digests, and artifact contracts
packages/calculus/    Restriction, bridge, witness, and policy laws
adapters/hyper/       Hyper graph projection and evaluator
adapters/adna/        aDNA lattice projection and evaluator
bridges/hyper-adna/   Scoped reference translation
packages/conformance/ Law harness, reports, and CLI
fixtures/             Valid and negative-control source systems
spec/                 Normative 0.1 summary and vocabulary
```

Read [the normative 0.1 summary](spec/lighthouse-v0.1.md) for protocol requirements and [the design](docs/superpowers/specs/2026-08-30-lighthouse-interchange-protocol-design.md) for rationale.

## Boundaries

The passing report applies only to the declared Hyper and aDNA profile versions, reference bridge digest, and fixture domain. It is not a claim that arbitrary systems or all claims are equivalent.

Version 0.1 has no networking, discovery, registry, replication, blockchain, global reputation, or consensus. Engram retrieval and Starshine attestations are later adapters. Trust stays local, directional, purpose-bound, time-bounded, and non-transitive.

Memory permissions are intentionally separate: `read`, `recall`, `suggest`, `inject_context`, `derive`, `retain`, and `reshare` do not imply one another. Revocation can stop future authorized access; it cannot force a recipient to forget plaintext already disclosed.
