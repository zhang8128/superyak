# Lighthouse Local City

**Date:** 2026-09-01

**Status:** Approved in conversation (Kairos, 2026-09-01); spec written for
review before planning.

**Scope:** The first live crossing between engram instances on one machine
under Lighthouse policy, with content delivery and receipts, plus the engram
targeting fixes and calibration work that run beside it. Spans the `engram`
and `lighthouse` repositories. Executed in parallel by two Codex teams and
several Claude sessions.

**Companions:**
- `docs/superpowers/specs/2026-08-30-lighthouse-shadow-export-design.md`
  (engram, read-only exporter; shipped)
- `~/Projects/lighthouse/docs/superpowers/specs/2026-08-30-lighthouse-interchange-protocol-design.md`
- `~/Projects/lighthouse/docs/superpowers/specs/2026-08-30-engram-recall-conformance-design.md`
- `~/Projects/lighthouse/spec/engram-recall-v0.1.md`
- `docs/research-fieldtest-results-2026-08-02.md` (feedback sparsity,
  confidence-as-attach-count, far-bridge null)

## 1. Purpose

Lighthouse 0.1 proves, offline, that a policy-scoped neighbor can supply a
missing memory while a denied relational memory stays out. Every receipt it
has ever emitted says `injected: false`. No memory has crossed between two
live minds.

This cycle builds the road for the smallest real case: several engram
instances owned by one person on one machine. The receiver is the instance
live in a Claude Code session. The publishers are other instances whose
stores are opened read-only by a local daemon. Policy is deny-by-default,
directional, and non-transitive. Content delivery into a recall response is
treated as entry into a mind's active context, so it requires an explicit
`inject_context` grant and emits the receipt the protocol mandates. The first
validated `injected: true` receipt is the milestone.

Beside the road, two things the September 1 review measured on the live
store get fixed or calibrated: recall targeting (recency deciding half the
winners, lane leaking at write time, near-tie rate of 39 percent) and the
instruments that have never been run (cohesion calibration, the off-device
assessment, the inverted-U dream-pairing pilot).

## 2. Decisions taken in conversation

| Question | Decision |
|---|---|
| What does "working" mean this cycle | Local city: instances on this machine, filesystem transport, content delivery with receipts. No network, no attestation. |
| Engram improvements in the same cycle | Yes, in parallel, under a seam rule so no two lanes edit the same recall code. |
| Architecture | Publisher daemon plus receiver arm (approach A), preceded by a throwaway spike that reads a neighbor store directly to measure whether neighbors supply anything on these stores (approach B as spike). |
| Who does what | Codex teams take all production code in both repos, including the targeting fixes. Claude sessions take measurement, calibration, labeling, design, and integration. |

## 3. Boundary

### Included

- A read-only open path in engram's `Storage`.
- A publisher daemon hosting every local instance listed in its config.
- A JSON-lines protocol over a Unix socket with two actions, `recall` and
  `read`.
- Publisher-side and receiver-side policy files in the Lighthouse
  `ConnectionPolicy` schema.
- A receiver arm in engram behind one call site in `recall()`, delivering
  under a separate `neighbors` response key.
- Receipts and disclosure logs written to `memory_log` on both sides.
- A receipt artifact kind and schema in Lighthouse, promoted from
  package-level evidence to a core artifact.
- A live-shadow evaluation mode in Lighthouse requiring a preregistered
  corpus and holdout.
- A labeling-queue format and an engram CLI for receiver-owned relevance and
  forbidden labels.
- Exporter extension so engram emits receipts and neighbor traces for the
  Lighthouse adapter.
- Cross-implementation policy conformance: identical decisions from the
  Python and TypeScript policy evaluators over a shared fixture set.
- Engram targeting fixes (section 9) with measurement rails.
- Calibration and instrument runs (section 9) with reports.
- A science-pilot design document (section 9), no build.

### Excluded

- Attestation, encryption, authenticated transport, peer discovery.
- Learned source weights, reputation, resharing, derivation, retention
  promises.
- Publication of personal-lane material or instincts.
- Any change to the Lighthouse protocol version.
- Any connection to a remote instance. Gil is the next cycle.

## 4. Components

### 4.1 Read-only store open

`Storage` gains a read-only construction path. It opens the database with
SQLite URI `mode=ro`, sets `PRAGMA query_only=ON`, loads the vector
extension so `search_vectors` works, and skips migrations, backfills,
consolidation, watcher start, and every write-oriented pragma. Mutation
methods raise. A test proves `total_changes` stays at zero across a
retrieval and that the database file's bytes are unchanged.

This is the mechanism that keeps neighbor retrieval from altering a
publisher's access counts, strengths, or decay. It is a guarantee, not a
discipline.

### 4.2 Publisher daemon

One process per machine, started by hand or by launchd. Its config lists
the instances to publish. For each it opens the store read-only, loads the
instance's policy file, and keeps the shared embedding model warm.

Per request it evaluates policy first and retrieves only after an allow.
Retrieval reuses engram's existing vector search and scoring on the
publisher's own store, restricted to `lane = "work"` and to the episode and
semantic layers. Instincts are never published. The daemon never opens a
store for writing and never imports the MCP server.

Every allow or deny decision is logged to the publisher's own `memory_log`
as a `lighthouse_disclosure` event carrying receiver id, context, purpose,
action, matched rule, and the ids and digests of anything returned. Content
is never logged.

### 4.3 Socket protocol

JSON lines over a Unix socket under `ENGRAM_HOME`. Requests and responses
are single-line JSON objects with a `protocolVersion` of `"0.1"` and the
`kind` member set to one of `recall`, `read`, or `error`.

`recall` request: receiver id, publisher id, context id and path, purpose,
audience `self`, query text, `k`, timestamp.

`recall` response: an opaque trace in the shape the Lighthouse Engram recall
profile already defines: `turnId`, query digest, context, ordered
candidates of `{ memoryId, rank, layer, lane, contentDigest }`, plus the
publisher's policy decision record.

`read` request: receiver id, publisher id, context, purpose, list of memory
ids, the `turnId` of the recall that selected them.

`read` response: content for each id the policy allows, the policy decision
per id, and the disclosure log id.

`error` response: a stable diagnostic code from the Lighthouse vocabulary
where one exists (`NO_MATCHING_ALLOW`, `EXPLICIT_DENY`, `OUTSIDE_VALIDITY`,
`CONTEXT_OUTSIDE_DOMAIN`) and `PUBLISHER_UNAVAILABLE` when the store cannot
be opened.

The receiver's query leaves the receiver in plaintext. The publisher
performs retrieval, so it must see the query. In the local city this is one
owner's data moving between one owner's processes. For the cross-machine
step it becomes a receiver-side policy question, and this document names it
now so it is not discovered then.

### 4.4 Policy

Each instance carries `lighthouse-policy.json` beside its store, in the
Lighthouse `ConnectionPolicy` schema, validated by `pnpm lighthouse validate`
from the Lighthouse checkout. Evaluation is deny-by-default; the most
specific matching rule wins; a deny wins a specificity tie; policy never
follows another publisher's trust.

The publisher's policy governs what it will answer: which receivers, which
contexts, which actions. The receiver's policy governs whom it will ask and
with what local weight. `recall`, `read`, and `inject_context` are separate
actions. A `recall` grant yields ids and digests only. Delivery into the
recall response requires `inject_context`; fetching content requires `read`.
The receiver arm requests `read` only when it already holds
`inject_context`.

Engram implements policy evaluation in Python. Its decisions must match the
TypeScript kit's decisions over a shared fixture set of policies and
requests (section 11). Drift between the two evaluators is a failing test,
not a documentation note.

### 4.5 Receiver arm

A new engram module exposes one function. `recall()` calls it once, after
local results, the margin, uninvited selection, and category influence are
final. The function:

1. reads the receiver's policy and selects publishers for this context and
   purpose;
2. sends one `recall` request per publisher, with a short timeout;
3. fuses admitted traces by weighted reciprocal rank with the constant 60
   the Lighthouse recall profile fixes, on publisher-qualified identity;
4. selects the top `k`;
5. if `inject_context` is granted for a publisher and context, sends a
   `read` request for that publisher's selected ids;
6. writes a receipt (section 4.6) and returns a `neighbors` payload.

`recall()` attaches the payload under `response["neighbors"]`. Neighbor
material is never merged into `results`. The margin, which measures local
retrieval discrimination, is unaffected. The uninvited slot stays as it is.
This keeps the targeted channel and the perspective channel structurally
distinct: local results are what the receiver's own store discriminated;
neighbors are perspective from a different store with different geometry.

Every failure in the arm is caught. Daemon absent, socket timeout, malformed
frame, publisher unavailable, or policy file missing produce
`degraded: ["neighbors"]` on the response and leave everything else exactly
as it would have been without Lighthouse.

### 4.6 Receipts

The receiver writes a `lighthouse_receipt` event to `memory_log` for every
recall that consulted at least one publisher, whether or not anything was
delivered. The receipt carries the fields the interchange protocol mandates
for context injection:

- experiment or session id, turn id, context, purpose;
- action `recall` and `injected` as a literal boolean;
- per publisher: snapshot or store digest, local weight, policy decision,
  trace outcome (matched, absent, context-mismatched, unavailable);
- selected opaque references with content digests, fused scores, and rank
  contributions;
- delivered references, if any, with the `read` decision per id;
- transformation `weighted-rrf-v1`;
- the receiver's own policy rule that matched.

Receipts never contain query text or memory content. Receipts are validated
against a strict schema at write time; unknown members are rejected. The
receipt schema is a Lighthouse core artifact kind in this cycle (section
4.7), and engram's exporter emits receipts in that shape.

### 4.7 Lighthouse changes

- **Receipt artifact.** A `RecallReceipt` kind with schema and canonical
  digest, replacing the package-level receipt in `recall-evaluation`. The
  adapter validates engram-emitted receipts. Negative controls: any
  `injected` value that does not match the delivered set, unknown members,
  missing publisher decisions.
- **Live-shadow evaluation mode.** Accepts a preregistration document
  naming corpus digest, holdout turn ids, metrics, cutoff, and uncertainty
  procedure. Refuses to run without one. Reports right-turn recall and nDCG
  at the declared cutoff for `local-only` and `policy-scoped`, forbidden
  exposure, unauthorized selections, and a bootstrap interval. The
  `indiscriminate-control` remains available only as a labeled unsafe
  control.
- **Labeling queue format.** A JSON document listing turns with receiver-
  owned labels: relevant references, forbidden references, or neither. The
  adapter consumes it as the experiment's ground truth.
- **Policy validation.** `pnpm lighthouse validate` and `authorize` are the
  reference evaluator for engram's policy files and the source of the shared
  decision fixtures.

### 4.8 Engram exporter extension

`lighthouse_export.py` gains receipts and neighbor traces as additional
sections of the portable document, under the same read-only, hash-only
discipline. Traces exported from receipts preserve the publisher-qualified
identity. The export still contains no content and no query text.

### 4.9 Labeling CLI

An engram CLI presents historical and live turns for the receiver to label,
writes the Lighthouse labeling-queue document, and refuses to infer labels
from `log_outcome`. The shadow-export design already established why:
outcome is per recall, not per memory, and converting it would invent
evidence.

## 5. Data flow

1. A session calls `recall(query)`. Local retrieval, scoring, margin,
   truncation, logging, uninvited selection, and category influence run
   unchanged.
2. The receiver arm reads the receiver policy. Zero publishers means the
   arm returns nothing and no receipt is written.
3. For each publisher, one `recall` request. The daemon evaluates the
   publisher's policy, retrieves on the publisher's read-only store, and
   returns an opaque trace and a decision record. The publisher logs a
   disclosure.
4. The receiver fuses admitted traces and selects the top `k`.
5. Where `inject_context` is granted, one `read` request per publisher for
   the selected ids. Content returns with per-id decisions. The publisher
   logs a disclosure with ids and digests.
6. The receiver writes a receipt and attaches `neighbors` to the response.
7. The session reads the response. Neighbor content is now in the active
   context, which is what the receipt records.

## 6. Failure semantics

| Condition | Result |
|---|---|
| Daemon not running, socket timeout, malformed frame | `degraded: ["neighbors"]`, local result untouched, receipt records `unavailable` per publisher |
| Receiver policy file missing or invalid | No publishers consulted, no receipt, local result untouched |
| Publisher policy denies | Decision recorded, trace outcome `policy-denied`, nothing retrieved |
| Publisher store cannot open | `PUBLISHER_UNAVAILABLE`, trace outcome `unavailable`, never a denial |
| Unknown context, memory, or publisher | `indeterminate`, never `violated` |
| `recall` allowed, `inject_context` not | Ids and digests in the receipt, nothing delivered, `injected: false` |
| Any exception inside the arm | Caught, logged, `degraded`, recall returns |

Nothing in the neighbor path may raise into `recall()`. This is the same
contract the margin, uninvited, resonance, and category blocks already
hold, and the tests pin it the same way.

## 7. First neighborhood

Receiver: `engram`. Publishers: `why` and `blocks`. Same owner, technical
context, and the July 8 cross-repo review is evidence that missing pieces
sit across these stores. Context path for this cycle is
`["memory", "technical"]`, matching the shadow export. Both publishers
publish work lane only. The receiver's policy grants `recall`, `read`, and
`inject_context` for `why` and `blocks` in that context, purpose
`session-recall`, audience `self`, with a validity interval ending at the
cycle's close so the grant expires rather than lingers.

## 8. The spike (B0)

Before the daemon is built, one Claude session runs a throwaway spike. It
opens `why` and `blocks` read-only, replays the last 60 logged recalls from
the `engram` store through those stores, and counts how often a neighbor
would have placed a candidate in the top 3 that the local store did not
hold. Twenty of those candidates are hand-judged for whether they were
useful at that turn. The output is a report with the counts and a go or
no-go recommendation. No spike code is committed.

If the spike finds nothing, the daemon lane shrinks to the read-only open
path and the protocol skeleton, the receiver arm is deferred, and the
cycle's Lighthouse value is the receipt artifact, the live-shadow mode, and
the labeling queue, all of which are needed regardless.

## 9. Lanes

Split by the house rule: convention problems get strict rails and go to
Codex; exploration problems get freedom and go to Claude sessions. Codex
teams take all production code. Claude sessions take measurement,
calibration, labeling, design, and integration. Codex-team runs one team
per repository.

| Lane | Executor | Repo | Work |
|---|---|---|---|
| B0 | Claude session | engram, scratch only | The spike in section 8. Gates E1's receiver arm. |
| E1 | Codex team on engram, dev1 | engram | Read-only `Storage` path, publisher daemon, socket protocol, Python policy evaluator, receiver arm, receipts, exporter extension, labeling CLI. |
| E2 | Codex team on engram, dev2 | engram | Targeting fixes: margins replay report first, then recency as a within-band tiebreak; lane derived at write time from project context or active task context; `dream_verify` reveals one score regime; margin computed after lane filtering; outcome auto-capture at session end for recalls this session touched. |
| L1 | Codex team on lighthouse | lighthouse | Receipt artifact kind and schema, live-shadow evaluation mode with preregistration, labeling-queue format, shared policy decision fixtures, negative controls. |
| E3 | Claude session | engram, data and docs only | Cohesion calibration on a store copy, inverted-U dream-pairing pilot with the August blind protocol, uninvited-band audit, duplicates sweep after the dedup fix, instinct re-distillation, the first off-device assessment, labeling the holdout turns, independent re-measurement after E2 merges. |
| S | Claude session | docs only | Science-pilot design: oracle-backed assessment, an uncertainty field for semantics distinct from confidence, and whether connection policy can derive from memory rather than config. Design document only. |
| I | Claude session | both | Integration: merge order, MCP restart after every engram merge, both suites, both proofs, the live acceptance script, CLAUDE.md updates. |

### 9.1 Seam rule

E1 may not edit `recall()`'s scoring loop, the margin block, the lane
filter, the write path in `remember()`, or `dream_verify()`. Its footprint
in `server.py` is one call site and one response key. E2 may not touch the neighbor module, the daemon, the
protocol, or the `neighbors` key. Both cut from the same base ref. E1's
call site merges first; E2 rebases across it. The Codex lead enforces the
seam as each package's allowed-files list, and the cross-review checks it.

E2 carries a measurement rail: the margins replay report, showing how many
of the recent-winner recalls survive a within-band tiebreak, must exist in
`docs/` before the formula changes, and the package's acceptance cites it.
E3 re-measures independently after the merge.

### 9.2 Coordination

Engram's task context is a single active slot, so parallel sessions would
overwrite each other. The implementation plan is the coordination record.
Decisions land in the codex-pair graph through the acknowledge command.
Each Codex team receives work-package briefs in the format its lead
expects: scope, allowed files, acceptance criteria, base ref. Each Claude
session receives a brief naming its lane, its forbidden files, and the
report it must produce.

### 9.3 Integration order

1. B0 report.
2. L1 receipt artifact and policy fixtures (no engram dependency).
3. E1 read-only open path and daemon, then receiver arm if B0 says go.
4. E2 targeting fixes, rebased across E1's call site.
5. Live acceptance script against `why` and `blocks`.
6. E3 re-measurement.
7. CLAUDE.md and spec updates.

The MCP server is restarted after every engram merge; the running process
executes old code until then. Nothing pushes to origin until the integrator
has seen a validated `injected: true` receipt from a real session.

## 10. Acceptance

All of the following, in one real Claude Code session against live stores:

1. **Crossing.** `engram` obtains scoped recall from `why` and `blocks`
   through the daemon, with content delivered under `neighbors`.
2. **Receipt.** At least one `injected: true` receipt validated by the
   Lighthouse adapter, with the matching disclosure entries in the
   publishers' logs.
3. **Privacy.** Forbidden exposure is zero on a receiver-labeled holdout of
   at least 30 turns, labeled by E3 before the run. The unsafe control
   still trips both counters.
4. **Right-turn recall.** Policy-scoped versus local-only recall at k=5 and
   nDCG, with a bootstrap interval, preregistered before the run. Reported,
   not gated. No threshold is claimed this cycle.
5. **Non-mutation.** Publisher store files are byte-identical after the
   session. Access counts, strengths, and decay in `why` and `blocks` are
   unchanged.
6. **Degradation.** With the daemon stopped mid-session, recall returns its
   local result with `degraded: ["neighbors"]`.
7. **Conformance.** Python and TypeScript policy evaluators agree on every
   shared fixture.
8. **Suites.** Both repositories green; both existing conformance proofs
   still pass; CLAUDE.md recall sections updated.

E2 acceptance: the margins replay report exists before the change; near-tie
rate and recent-winner share reported before and after; lane derivation
covers every episode written with a project tag; `dream_verify` reveals one
score regime; outcome auto-capture raises outcome coverage above the 14
percent baseline on the next week of recalls.

E3 acceptance: cohesion calibration report from a copy; inverted-U pilot
report with the August protocol; uninvited-band audit; duplicates sweep
report; instinct notices re-distilled; assessment history shows one
completed off-device assessment with counters.

## 11. Testing

**Cross-implementation conformance.** A fixture directory in Lighthouse
holds policy files and request sets. The TypeScript kit produces the
reference decisions. Engram's tests load the same fixtures and assert
identical decisions. Any divergence fails engram's suite.

**Engram.** Read-only open refuses every mutation method and leaves
`total_changes` at zero across retrieval. Daemon: policy-before-retrieval,
lane and layer restriction, disclosure logging, unavailable store. Protocol:
round-trip, timeout, malformed frame, unknown publisher, version mismatch.
Receiver arm: policy miss, `recall` without `inject_context`, delivery with
receipt, every failure path leaves the local result untouched, receipt
schema rejects unknown members. Exporter: receipts and traces exported
hash-only, deterministic across insertion order. Labeling CLI: refuses to
infer from outcomes.

**Lighthouse.** Receipt schema and digest, negative controls, live-shadow
mode refuses an unpreregistered run, labeling-queue validation, fixture
decisions stable.

**Live.** A scripted session exercises the acceptance list end to end and
writes a report with counts and digests only. The integrator runs it after
every engram merge and after every MCP restart.

## 12. Deferred

- Authenticated transport, discovery, encryption, attestation. The daemon's
  client interface is the seam for the remote step; the local city does not
  change it.
- Receiver-side policy on query disclosure to remote publishers.
- Personal-lane and instinct publication.
- Learned weights, reputation, resharing, derivation, retention.
- Deriving connection policy from memory rather than config (S lane
  question).
- The science pilot itself (S lane produces the design only).

## 13. Open questions carried by the S lane

- Can an instinct or semantic become a policy rule, and what would the
  receipt look like when the rule that matched was itself a memory?
- What does a semantic need to carry through compression for a scientific
  regularity to keep its domain of validity: an uncertainty field, a
  conditions field, or a witness to the episodes that would falsify it?
- What is the oracle-backed form of the off-device assessment: held-out
  observations scored by prediction rather than self-report?
