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
| Recall receipt | Content-addressed record of one policy-scoped recall: sources, decisions, selection, delivery, and whether active context was injected. |
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
| `RECEIPT_INJECTION_MISMATCH` | A receipt's injected value does not match whether its delivered list is non-empty. |
| `DELIVERED_NOT_SELECTED` | A delivered reference does not appear in the receipt's selected list. |
| `DELIVERED_WITHOUT_ALLOW` | A delivered reference does not carry an allow read decision. |
| `RECEIPTS_REQUIRE_1_1` | An Engram 1.0 export declares a receipts member reserved for 1.1. |
| `RECEIPT_DIGEST_MISMATCH` | A receipt's canonical content does not match its declared digest. |
| `DUPLICATE_RECEIPT` | An Engram export contains more than one receipt for a turn and context. |
| `DUPLICATE_LABEL_TURN` | A labels document repeats a `(turnId, context.id)` key. |
| `EMPTY_RELEVANCE_JUDGMENT` | A labeled turn has no receiver-owned relevant references. |
| `PREREGISTRATION_REQUIRED` | Live-shadow evaluation was requested without a preregistration document. |
| `CORPUS_DIGEST_MISMATCH` | The normalized export does not match the preregistered corpus digest. |
| `HOLDOUT_TURN_UNLABELED` | A preregistered holdout turn has no receiver-owned label. |
| `HOLDOUT_TURN_MISSING_TRACE` | A preregistered holdout turn has no local recall trace. |
| `HOLDOUT_TURN_CONTEXT_MISMATCH` | A holdout turn's local trace does not match its labeled context. |
| `RECEIPT_SCORE_MISMATCH` | A selected receipt score does not equal weighted reciprocal rank over its contributions. |
| `SNAPSHOT_NOT_DETERMINISTIC` | Equivalent projections produced different digests. |
| `RESTRICTION_IDENTITY_FAILED` | Identity restriction changed the semantic projection. |
| `RESTRICTION_COMPOSITION_FAILED` | Two-step restriction differs from direct restriction. |
| `BRIDGE_IDENTITY_FAILED` | An identity bridge changed a supported claim. |
| `BRIDGE_COMPOSITION_FAILED` | Supported bridge composition is not associative. |
| `OBSTRUCTION_MISSING` | An out-of-domain case did not produce the required obstruction. |
| `INVALID_BRIDGE_ACCEPTED` | A negative-control bridge was not rejected. |

Human-readable messages may improve without changing these codes. New codes use uppercase snake case and MUST NOT silently reuse an existing meaning.
