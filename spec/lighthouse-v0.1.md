# Lighthouse Interchange Protocol 0.1

## Status and scope

This document is the normative summary of Lighthouse 0.1. Version 0.1 specifies offline artifacts, local evaluation, partial bridges, restriction laws, witnesses, local connection policy, and profile-scoped conformance. It does not specify discovery, transport, replication, consensus, a registry, or remotely executable adapters.

The keywords MUST, MUST NOT, REQUIRED, SHOULD, SHOULD NOT, and MAY are to be interpreted as requirements on conforming 0.1 implementations.

## Artifact envelope

A Lighthouse artifact MUST conform to one schema in `schemas/` and MUST contain:

- `kind` and literal `protocolVersion: "0.1"`;
- publisher-scoped `id`, offset-aware `issuedAt`, and `issuer`;
- `payloadMediaType` and a kind-specific `payload`;
- algorithm-agile `{ algorithm, value }` content `digest`;
- optional `attestations` and namespaced `extensions`.

Core objects MUST reject unknown members. Extension keys MUST be URI-scheme-like names such as `org.example:field`. Implementations MUST preserve extension data they accept.

The content digest covers the complete canonical envelope except `digest` and `attestations`. This exclusion prevents self-reference and permits signatures to be added without changing artifact identity. The reference implementation supports SHA-256; consumers MUST reject unsupported algorithms rather than reinterpret them.

Canonical JSON recursively sorts object member names, preserves array order, uses JSON string/number serialization, and rejects non-finite numbers or values outside the JSON data model. Checkout paths, directory enumeration order, and host-specific temporary paths MUST NOT enter normalized snapshots.

## Local profiles and evaluation

A profile presents an institution-like boundary consisting of signatures, sentences, models, and a local satisfaction relation. Lighthouse does not prescribe their internal logic.

An adapter MUST provide deterministic projection, supported context restriction, claim restriction, and local evaluation. Evaluation returns exactly:

- `satisfied` when the local model establishes the claim;
- `violated` when the local model establishes its negation or incompatibility;
- `indeterminate` when the adapter lacks the language, evidence, or decision procedure.

Missing evidence, unknown media types, and unsupported claims MUST NOT be coerced to `violated`.

## Context restriction

For supported contexts, restriction MUST obey:

1. Identity: restricting an artifact to its current context preserves its semantic projection.
2. Composition: restricting from `U` to `V` and then `V` to `W` equals restricting directly from `U` to `W`.
3. Honest obstruction: restriction outside the declared context returns `CONTEXT_OUTSIDE_DOMAIN`.

Version 0.1 does not claim general sheaf gluing across covers.

## Bridges

A bridge is directional, versioned, and partial. Its descriptor MUST declare source and target profiles, supported contexts and claim media types, fidelity, a locally resolved implementation identifier, and dependency digests. A descriptor MUST NOT carry executable implementation code.

For every exact or partial bridge claim inside the declared domain, independent source and target evaluation MUST satisfy:

```text
target-model satisfies translated-claim
if and only if
source-model satisfies source-claim
```

An unsupported claim MUST produce `unmapped`; it MUST NOT produce a fabricated target claim. Evaluation disagreement produces `invalid` with `SATISFACTION_NOT_PRESERVED`.

An approximate bridge MUST declare a named metric, finite non-negative tolerance, and evidence procedure. Exact and partial descriptors MUST NOT contain approximation metadata. Approximate results cannot satisfy an exact conformance check.

Identity bridges preserve supported claims. Composition requires adjacent profiles to match and MUST preserve flattened bridge lineage. Composition is associative over the declared supported fragment.

## Translation witnesses

Every attempted conformance translation produces a content-addressed witness. A witness binds source and optional target claims, source and optional target snapshots, bridge and lineage digests, local evaluation results, evidence, mapped/unmapped paths, outcome, and stable diagnostics.

Outcome is one of `preserved`, `partial`, `approximate`, `unmapped`, `conflict`, or `invalid`. Witnesses MUST retain source provenance and MUST NOT present loss or approximation as exact preservation.

## Local connection policy

Policy evaluation is local and deny-by-default. A grant is directional and scoped by publisher, profile, domain, action, context, claim media type, purpose, audience, evidence, attestations, and validity interval. Exact selectors are more specific than explicitly declared prefix selectors. The most specific matching rule wins; a deny wins a specificity tie.

Policy MUST NOT follow another publisher's trust relationships. Lighthouse membership, mutual connection, and overlapping lighthouses do not imply reciprocal or transitive consent.

The actions `read`, `recall`, `suggest`, `inject_context`, `derive`, `retain`, and `reshare` are independent. Permission for one grants none of the others.

Future Engram adapters that inject active context MUST emit a local receipt identifying the source lighthouse, matched policy, declared purpose, selected material, and transformations. Revocation prevents future authorized access; it cannot guarantee that a recipient forgets plaintext already disclosed.

## Conformance

Conformance applies only to named profile versions, bridge digest, declared domains, adapters, and fixture/evidence digests. It is never certification of every claim a system can express.

A passing exact report MUST include successful schema/digest validation, deterministic projections, restriction identity/composition, bridge identity/composition, satisfaction preservation, negative controls, honest out-of-domain obstruction, and scoped policy decisions. Every required check MUST pass. A report MUST be machine-readable and MUST identify artifact digests used as evidence.

The 0.1 reference corpus proves only the shared Hyper workflow-dependency and aDNA typed-port fragment. Hyper lease/fencing/channel semantics remain explicitly unmapped.
