# Lighthouse Interchange Protocol v0.1 Design

**Status:** Approved  
**Date:** 2026-08-30  
**Scope:** An implementation-neutral interchange standard and TypeScript reference kit for translating claims between independently governed knowledge systems.

## 1. Purpose

Lighthouse lets a person, agent, lab, institution, or community connect selected parts of independently operated knowledge systems without surrendering local ownership or authority.

The first release proves one narrow proposition: two structurally different systems can exchange a scoped claim, preserve its meaning across the translation they explicitly support, and expose every unsupported or lossy part instead of silently inventing equivalence.

Lighthouse is a universal protocol, not a universal server. A small, close community and a city-scale federation use the same envelopes and laws while choosing different peers, policies, and operating infrastructure.

## 2. Architectural decision

Lighthouse is a new sibling repository. It does not broaden Hyper Coordinator into a universal platform and does not replace aDNA, Engram, Starshine, or another local system.

- Hyper Coordinator remains a focused coordination runtime and becomes the first reference adapter.
- aDNA becomes the second adapter and supplies a structurally different test of interoperability.
- Engram follows after the structural protocol survives those two adapters.
- Starshine supplies optional attestation and durable validation rails after the semantic laws are working locally.

This separation keeps the standard implementable by groups that will never run the same server, database, programming language, or governance process.

## 3. v0.1 boundary

### Included

- Canonical, language-neutral JSON envelopes and JSON Schemas.
- A TypeScript reference implementation of the protocol types and mathematical laws.
- Adapter contracts for describing local languages, snapshots, claims, and evaluation.
- Partial, scoped bridges between systems.
- Machine-checkable witnesses for preservation, loss, conflict, and unsupported translation.
- Local connection policies scoped by publisher, domain, action, and validity interval.
- An offline conformance suite with Hyper and aDNA fixtures.
- A CLI that validates artifacts and runs the reference conformance scenario.

### Excluded

- Peer discovery, networking, replication, consensus, or a hosted registry.
- Blockchain or Starshine integration.
- Executing code received from another lighthouse.
- A global identity provider, reputation score, trust graph, or moderation authority.
- Automatic trust propagation.
- A universal ontology or formula language.
- General sheaf gluing across arbitrary covers.
- Engram retrieval and automatic right-turn context injection.

The exclusions are deliberate. v0.1 measures semantic preservation before adding distribution.

## 4. Domain language

| Term | Meaning |
|---|---|
| **Lighthouse** | A locally governed participant that publishes descriptors, snapshots, claims, and bridges. |
| **Profile** | An adapter's declaration of its local signatures, claims, models, evaluator, and supported translations. |
| **Signature** | The typed vocabulary in which a local claim is expressed. |
| **Model** | A local state against which claims can be evaluated. |
| **Claim** | A typed assertion bound to a signature, context, issuer, and snapshot lineage. |
| **Context** | The explicit subdomain in which a claim or bridge is intended to apply. |
| **Snapshot** | An immutable, content-addressed projection of local state. |
| **Bridge** | A directional, partial translation from one profile/context to another. |
| **Witness** | Evidence describing what a bridge preserved, lost, conflicted with, approximated, or could not map. |
| **Connection policy** | A local rule granting a publisher selected actions in selected domains for a bounded time. |
| **Attestation** | An algorithm-agile signature over an artifact digest; optional in v0.1. |

## 5. Mathematical kernel

### 5.1 Local profiles

Each adapter profile presents an institution-like structure:

\[
I = (\mathrm{Sign}, \mathrm{Sen}, \mathrm{Mod}, \models)
\]

- `Sign` is a class of typed signatures.
- `Sen(Sigma)` is the set of claims expressible under signature `Sigma`.
- `Mod(Sigma)` is the set of local models for `Sigma`.
- `M |=_Sigma phi` is the adapter's local evaluation relation.

Lighthouse standardizes the boundary around these parts, not their internal representation. A profile may use graphs, schemas, ontologies, source trees, relational data, or another formalism. Claims and models therefore carry opaque, typed payloads; the adapter owns their interpretation.

Evaluation returns one of `satisfied`, `violated`, or `indeterminate`. Missing translation or unavailable evidence is never coerced to `violated`.

### 5.2 Contexts and restrictions

A context identifies an explicit portion of a signature or model. Restriction from context `U` to a supported subcontext `V` is written:

\[
\rho_{U,V}: F(U) \rightarrow F(V)
\]

v0.1 requires only:

1. Identity: restricting a context to itself changes nothing.
2. Composition: restricting from `U` to `V` and then `V` to `W` equals restricting directly from `U` to `W` where all operations are defined.
3. Explicit failure: an unsupported restriction returns an obstruction witness.

This is the sheaf-shaped seam. Full cover compatibility, uniqueness, and gluing are deferred until real adapters provide measurable cases.

### 5.3 Bridges

A bridge `B: I -> J` is directional and partial. It declares:

- an explicit source and target profile;
- the source contexts and signature fragment in its domain;
- a signature translation;
- a claim translation over the supported fragment;
- a target-to-source model reduct or an equivalent adapter-provided comparison operation;
- a declared fidelity of `exact`, `partial`, or `approximate`;
- version and digest constraints for every artifact it depends on.

For an exact bridge, the central satisfaction condition is:

\[
M' \models_J B_{Sen}(\varphi)
\quad\Longleftrightarrow\quad
B_{Mod}(M') \models_I \varphi
\]

for every supported source claim `phi` and compatible target model `M'` in the bridge domain.

A partial bridge must satisfy the same law on its declared domain and emit an explicit `unmapped` obstruction outside it. An approximate bridge replaces equivalence with a named metric, tolerance, and evidence procedure; it cannot present approximate evidence as exact preservation.

### 5.4 Bridge laws

The conformance layer tests these laws over declared fixture domains:

1. **Identity:** the identity bridge preserves canonical artifacts and evaluation results.
2. **Composition:** supported translations through `B` and then `C` equal translation through their declared composition, including witness lineage.
3. **Restriction naturality:** translating then restricting agrees with restricting then translating where both paths are defined.
4. **Satisfaction preservation:** exact and partial bridges preserve local truth on the declared domain.
5. **Honest obstruction:** unsupported, ambiguous, conflicting, or lossy cases are represented in the witness and do not produce a false successful result.

These are executable conformance properties, not claims that arbitrary local systems are globally equivalent.

## 6. Canonical protocol artifacts

Every artifact uses canonical JSON, a schema version, a media type, and a content digest. Object member order and local filesystem paths cannot affect its digest. Unknown extension members are preserved but do not alter core semantics unless a profile explicitly includes them in its signed payload.

### 6.1 Common envelope

All artifacts share:

- `kind`: stable artifact kind.
- `protocolVersion`: Lighthouse protocol version.
- `id`: stable, publisher-scoped identifier.
- `issuedAt`: RFC 3339 timestamp.
- `issuer`: local publisher identifier.
- `payloadMediaType`: interpretation contract for the payload.
- `payload`: JSON value or digest reference.
- `digest`: `{ algorithm, value }` over the canonical signed content.
- `attestations`: optional algorithm-agile signatures.
- `extensions`: namespaced extension values.

Core schemas reject undeclared core members. Extensions live only under `extensions` and use reverse-domain or URI-like namespaces.

### 6.2 Descriptor

A `LighthouseDescriptor` advertises protocol versions, profiles, supported actions, artifact endpoints as inert identifiers, and optional attestations. Discovery of descriptors is out of scope; v0.1 consumes local files.

### 6.3 Snapshot

A `Snapshot` binds a profile, signature, context, immutable model payload, source lineage, and digest. Adapters must normalize away checkout paths, enumeration order, and other host-specific accidents before canonicalization.

### 6.4 Claim

A `Claim` binds:

- a profile and signature;
- a context;
- a typed local sentence payload;
- issuer and issuance time;
- source snapshot digests;
- provenance links;
- optional validity interval and attestations.

Claims are assertions, not automatically trusted facts.

### 6.5 Bridge

A `BridgeDescriptor` declares source and target profile versions, supported contexts and claim kinds, fidelity, implementation identifier, dependency digests, and any approximation contract. The executable adapter implementation is installed and trusted locally; it is never transported in the descriptor.

### 6.6 Witness

A `TranslationWitness` records:

- input and output artifact digests;
- bridge digest and lineage;
- outcome: `preserved`, `partial`, `approximate`, `unmapped`, `conflict`, or `invalid`;
- mapped and unmapped paths;
- local source and target evaluation results;
- evidence digests;
- approximation metric and tolerance when applicable;
- diagnostics using stable codes plus human-readable detail.

A witness is independently serializable and content-addressed so later attestation does not require replaying an adapter.

### 6.7 Connection policy

A `ConnectionPolicy` remains local and is not a universal reputation statement. A rule selects:

- publishers or publisher namespaces;
- profiles and semantic domains;
- actions such as `discover`, `read`, `compile`, `contribute`, `link_overlap`, `moderate`, or `administer`;
- contexts and claim kinds;
- validity interval;
- optional evidence and attestation requirements;
- effect `allow` or `deny`.

Evaluation is deny-by-default. A more specific deny overrides an allow. Policy does not transitively trust a publisher merely because a trusted publisher trusts it.

## 7. Reference repository

```text
spec/                         Normative prose and protocol vocabulary
schemas/                      Language-neutral JSON Schemas
packages/protocol/            TypeScript artifact types and canonicalization
packages/calculus/            Restrictions, bridge composition, and witness logic
packages/conformance/         Adapter harness, law checks, CLI, and reports
adapters/hyper/               Hyper fixture extractor and bridge half
adapters/adna/                aDNA fixture extractor and bridge half
fixtures/                     Minimal source systems and invalid cases
docs/superpowers/specs/       Approved designs
docs/superpowers/plans/       Executable implementation plans
```

The workspace uses TypeScript because Hyper Coordinator and Starshine already use it. JSON Schemas and canonical JSON are the compatibility surface for other languages.

## 8. Adapter contract

An adapter must implement a narrow interface:

1. Return its profile descriptor.
2. Project a local fixture or system state into a deterministic snapshot.
3. Restrict a snapshot or claim to a supported context.
4. Evaluate a supported claim against a compatible snapshot.
5. Translate supported signatures and claims for its registered bridges.
6. Produce stable obstruction codes for unsupported operations.

Adapters receive parsed data and return data. The conformance runner does not evaluate downloaded scripts, package hooks, or arbitrary commands.

## 9. First interoperability proof

The reference scenario uses one shared dependency fact represented differently by each system.

### Hyper source

Hyper models a brick that publishes and subscribes to typed event schemas:

```text
brick --PUBLISHES--> event-schema
brick --SUBSCRIBES--> event-schema
```

The source claim states that a named producer publishes the event schema required by a named consumer within a workflow context.

### aDNA target

aDNA models a node with typed output and input ports connected through a lattice interface:

```text
node --output-port--> typed-value
node --input-port--> typed-value
```

The bridge maps the shared producer/consumer/type fragment. Hyper-specific lease ownership, fencing tokens, and channel cursor semantics remain unmapped in v0.1.

### Proof flow

1. Each adapter builds a deterministic snapshot from its fixture.
2. Hyper evaluates the source claim as `satisfied`.
3. The bridge translates the supported signature and claim into the aDNA profile.
4. aDNA evaluates the translated claim as `satisfied`.
5. The conformance runner emits a preservation witness binding both snapshots, claims, evaluations, and the bridge.
6. A deliberately invalid bridge maps the event type incorrectly and fails the satisfaction law.
7. A Hyper lease claim returns `unmapped` with an obstruction witness.

## 10. Conformance model

Conformance is profile- and bridge-specific, never a blanket certification of a whole system.

A report contains:

- protocol schema results;
- canonicalization and digest vectors;
- adapter determinism results;
- restriction law results;
- identity and composition law results;
- satisfaction cases for the declared domain;
- negative cases and obstruction behavior;
- fixture, adapter, profile, and bridge digests.

A candidate passes only if all required exact laws pass and every out-of-domain case is honestly classified. Approximate bridges are reported separately and cannot earn an exact conformance result.

## 11. Acceptance criteria

v0.1 is complete when the automated suite demonstrates:

1. Hyper and aDNA snapshots have stable digests regardless of checkout path or input enumeration order.
2. A scoped bridge translates the shared dependency claim.
3. Independent local evaluators agree that the source and translated claims are satisfied.
4. Each profile's identity bridge preserves its supported claims.
5. Bridge composition is associative over the supported fixture fragment.
6. A Hyper-specific lease claim produces an explicit `unmapped` obstruction.
7. A deliberately invalid type mapping fails satisfaction preservation.
8. A local policy can trust one publisher for workflow structure while denying unrelated domains and actions.
9. The CLI exits non-zero for invalid schemas, digests, bridge laws, or policy denials and emits a machine-readable report.
10. A clean checkout can install, build, test, and run the reference proof from documented commands.

## 12. Safety and governance boundaries

- Bridges are data plus references to locally installed implementations, never executable code from peers.
- Trust is local, scoped, time-bounded, revocable, and deny-by-default.
- Provenance is append-only in artifact lineage; a translation cannot erase its source.
- Content digests and attestations are algorithm-agile. Semantic identity is not tied to one cryptographic primitive or ledger.
- Exact, partial, and approximate translations are visibly distinct in schemas and output.
- Approximation requires a named metric, tolerance, and evidence procedure.
- Personally sensitive payloads are referenced by digest where possible; federation and disclosure controls are deferred until a threat model is attached to a concrete transport.
- Conflicting claims may coexist. Lighthouse records conflict and authority context; it does not manufacture global consensus.

## 13. Evolution path

After v0.1 passes:

1. Add an Engram adapter and measure whether scoped context selection improves right-turn recall.
2. Add a Starshine attestation driver for snapshots, bridges, witnesses, and policy receipts.
3. Specify authenticated transport and peer discovery without changing core artifact semantics.
4. Add cover compatibility and gluing only for demonstrated multi-lighthouse overlap cases.
5. Add community governance profiles that can express small trusted crews, institutional consortia, and city-scale public rules without making any one scale mandatory.

Each layer must preserve the offline conformance corpus. Network agreement cannot substitute for semantic preservation.

## 14. Prior art and grounding

- Goguen and Burstall's institution theory supplies the satisfaction-preserving translation shape: <https://doi.org/10.1145/147508.147524>
- The OMG Distributed Ontology, Model, and Specification Language demonstrates heterogeneous formal-system integration without imposing one base logic: <https://www.omg.org/spec/DOL/1.0/About-DOL>
- Ologs motivate category-theoretic knowledge representation: <https://doi.org/10.1371/journal.pone.0024274>
- Functorial data migration motivates composable transformations between schemas: <https://arxiv.org/abs/1009.1166>
- Sheaf-theoretic contextuality motivates explicit local contexts, overlap, and obstructions to global consistency: <https://arxiv.org/abs/1102.0264>

Lighthouse uses these as mathematical discipline, not as branding. The reference implementation succeeds only when independent adapter evaluations and negative fixtures make its preservation claims falsifiable.
