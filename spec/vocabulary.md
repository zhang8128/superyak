# Lighthouse 0.1 Vocabulary

## Terms

| Term | Meaning |
|---|---|
| Lighthouse | A locally governed publisher and consumer of protocol artifacts. |
| Profile | An adapter's versioned declaration of local signatures, claims, models, and evaluation. |
| Signature | Typed vocabulary under which a claim is expressed. |
| Model | Local state against which an adapter evaluates claims. |
| Claim | A typed assertion with context, issuer, snapshot lineage, and provenance. |
| Context | An explicit subdomain in which an artifact or bridge applies. |
| Snapshot | An immutable, content-addressed projection of local state. |
| Restriction | A supported projection from a context to one of its subcontexts. |
| Bridge | A directional, partial translation between profile fragments. |
| Witness | Content-addressed evidence of preservation, loss, conflict, approximation, or obstruction. |
| Connection policy | A local, directional, scoped decision rule; never a global reputation score. |
| Attestation | An algorithm-agile signature over an artifact digest. |

## Stable diagnostic codes

| Code | Meaning |
|---|---|
| `DIGEST_MISMATCH` | Canonical content does not match the declared digest. |
| `SCHEMA_INVALID` | Input violates its strict artifact schema. |
| `CONTEXT_OUTSIDE_DOMAIN` | Requested restriction is not beneath the current context. |
| `BRIDGE_DOMAIN_MISMATCH` | Claim profile/version does not match the bridge source. |
| `BRIDGE_CLAIM_UNMAPPED` | Claim is outside the bridge's declared supported fragment. |
| `SATISFACTION_NOT_PRESERVED` | Independent source and target evaluation disagree. |
| `NO_MATCHING_ALLOW` | No local rule grants the exact requested use. |
| `EXPLICIT_DENY` | The highest-specificity decision is a deny rule. |
| `OUTSIDE_VALIDITY` | Matching rules exist but none is active at the requested time. |
| `SNAPSHOT_NOT_DETERMINISTIC` | Equivalent projections produced different digests. |
| `RESTRICTION_IDENTITY_FAILED` | Identity restriction changed the semantic projection. |
| `RESTRICTION_COMPOSITION_FAILED` | Two-step restriction differs from direct restriction. |
| `BRIDGE_IDENTITY_FAILED` | An identity bridge changed a supported claim. |
| `BRIDGE_COMPOSITION_FAILED` | Supported bridge composition is not associative. |
| `OBSTRUCTION_MISSING` | An out-of-domain case did not produce the required obstruction. |
| `INVALID_BRIDGE_ACCEPTED` | A negative-control bridge was not rejected. |

Human-readable messages may improve without changing these codes. New codes use uppercase snake case and MUST NOT silently reuse an existing meaning.
