# Lighthouse receiver and local crossing

The user asked to continue building the Lighthouse network. This milestone finishes the receiver side of the existing local-city architecture against the explicit-sharing publisher now on main. The old work-lane publication rule is superseded by the layered publisher design. The existing PostgreSQL service branch remains reference-only.

## Acceptance and measurement

The September 1 census found empty candidate publishers. A read-only September 6 census now finds 15 explicit commons shares in the Lighthouse house (45 episodes, 6 semantics). Availability has changed; the receiver-owned usefulness study has not been completed. This build provides an opt-in receiver and a reproducible synthetic crossing/pilot instrument. It does not enable live recall injection, alter actual policies/group membership, label real memories useful on the user's behalf, or claim the B0 usefulness threshold passed.

Success means a real Unix-socket publisher delivers a permitted share into a separate `neighbors` response, a denied share remains absent, and a strictly validated receipt records the exchange. Withdrawal prevents the next authorized delivery, publisher store bytes stay unchanged, and failures preserve local recall. The pilot writes disposable stores and produces a content-free receipt suitable for validation by the sibling Lighthouse kit.

## Receiver selection and scope

A receiver-owned `.engram/instances/<name>/lighthouse-receiver.toml` explicitly enables the integration and lists chosen publisher instance names, socket path, receiver policy path, result limit, and total timeout. Paths resolve relative to that file. Missing configuration means the feature is off. Merely adding publisher grants or belonging to a group never opts a receiver in.

The MCP `recall` gains optional `lighthouse_context` and `lighthouse_purpose` arguments. No Lighthouse request is sent without an explicitly supplied context, an enabled receiver config, and a matching receiver policy. Context paths are derived from slash-separated context IDs with a validated vocabulary. The fixed default purpose is `session-recall`. Instinct-only recall keeps its existing local behavior. The local scoring, margins, dream behavior and result set remain unchanged.

Receiver policy separately authorizes `recall`, `read`, and `inject_context`. No query leaves before `recall` is allowed. No content is requested before both other actions are allowed. Policies reload per operation and are rechecked before delivery. Receiver weights are finite, nonnegative local preferences from the artifact's `engram:weight` extension keyed by publisher URN; no global reputation or transitive discovery is introduced.

## Bounded wire exchange

Use the current JSON-lines Unix socket protocol. At most eight configured publishers, at most twenty candidates per trace, at most five delivered memories, a default one-result request, a total two-second network deadline (maximum ten seconds), a one-MiB wire-frame cap, a 4096-character query cap, and a 32-KiB total content-delivery cap. Socket reads and writes share an absolute deadline; truncated, oversized, malformed, mismatched or trickled replies fail closed. Use no unbounded `readline`.

Validate the returned query digest and exact context including its path. Candidates must have supported episode/semantic layers, explicit personal/work lane, positive integer ranks, unique IDs, valid SHA-256 content digests and no embedded content. Fuse using `weight/(60+rank)`, publisher-qualified identity and deterministic canonical identity ordering. Conflicting digests and duplicated candidate IDs within one trace are rejected.

Read replies can deliver only requested IDs, under allowed publisher read decisions, with content matching the selected digest. Preserve publisher, published memory ID, layer, lane, audience and digest alongside content. Reject unsupported or malformed audiences and bound content before response construction. An unshared/missing item with null content is not delivered.

## Evidence without invented digests

The old unimplemented plan used an all-zero store digest when the publisher snapshot was unknown. This build will not do that. A validated reply defines a bounded opaque trace snapshot: publisher, source turn, query digest, context, ordered opaque candidates, publisher decision and disclosure ID. Its canonical JSON digest is the receipt's `storeDigest`, explicitly identified as a received trace snapshot rather than the raw SQLite file. Store this content-free snapshot in `extensions['engram:traceSnapshots']` so the digest is reproducible.

A source for which no valid snapshot arrived is listed in `extensions['engram:unavailableSources']` with its publisher, local weight, receiver decision and stable diagnostic. It is absent from the schema's `sources` array because the current schema requires a known digest. Preserve all receiver action decisions in `engram:receiverDecisions` and publisher decisions in the snapshot. The standard source `policyDecision` is the receiver's recall authorization. Namespaced extensions use the existing 0.1 extension mechanism; no schema fork or fake digest is required.

Receipts contain no query text or memory contents. A consultation writes a receipt even if no content is delivered. `injected` is true exactly when the receipt's delivered set is nonempty. Persist and validate the receipt before returning content; failure to record evidence suppresses delivery. This records response construction, not proof that a downstream model used the material.

## Publisher withdrawal

The current daemon caches action policy while rereading audience grants. Reload one validated publisher policy for each operation, using that same policy snapshot for the action and audience decisions. A changed or invalid policy cannot leave an earlier allow in force. Review added complete schema validation and issuer binding, and expiry checks against a publisher-owned clock; malformed selectors and caller-supplied times must never expand access. Existing explicit unshare behavior remains intact. Do not change the daemon's read-only storage or disclosure requirements.

## Integration and pilot

Call the receiver at the final `server.recall` response boundary only. Return neighbor data under `neighbors`; append `neighbors` to existing degradation indicators on failure. Never merge remote content into local `results` or use it to reinforce identity memory. Keep live connections disabled unless the owner explicitly configures them and calls a declared scope.

A standalone pilot command creates or uses a caller-selected disposable output directory, starts a publisher with synthetic memories and fake deterministic embeddings, performs allowed and denied crossings, withdraws a share, validates receipts, and emits a content-free report. A labeling CLI produces receiver-owned labels from receipt references for the existing offline evaluation path, without inventing relevance from use logs. Documentation includes configuration, inspection, withdrawal and the still-pending usefulness gate.

Out of scope: cross-machine authentication/discovery, blockchain, sheaf influence, automatic reach adaptation, new live grants, real patient/civic datasets, and restarting the user's MCP/daemon processes.
