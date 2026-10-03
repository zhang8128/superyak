# Task C: layered channels for Superyak engram (fast lanes + lighthouses)

# Task C: layered channels for Superyak engram

Author: w3 (Claude collaborator). This is a read-only review; every claim about code cites a file and line in `/var/home/adeptus/Projects/work/superyak`.

Status: v3. It incorporates w1's delivery trace (§1.6) and w4's challenges: §5 is re-scoped to failures observed in this run, the §2 table is labelled descriptive, and the ordering of the Codex sovereignty work is in §6.

## 0. Summary

- **Three unrelated messaging mechanisms exist**, and none is wired to another:
  1. Team mode's broker (`team/superyak_team/teamd.py`).
  2. Engram's `federation.SignalBus`.
  3. Engram's lighthouse: explicit `share` → published house → policy-gated Unix-socket daemon.
- **Inside a team, `share(audience="group:agent-team")` can be written but never read.** Every worker already shares the lead's private engram store across both lanes (§1.7). This is the most important finding, and it is a **scope question for Kairos** about data sovereignty.
- **The layered model (§2) is descriptive vocabulary, not a roadmap.** It names semantics the existing blocks already have.
- **What to build now** is only what this run actually broke on (§5):
  - docs and diagnostics;
  - a decision on instance and lane scoping;
  - a pull path so peers can read posts and plans.
- **Not now:** topics, beacons, cross-machine transport, SignalBus.

## 1. What exists (verified in code)

### 1.1 Explicit sharing: `engram/sharing.py`
- A share is an act with an audience and a reason, and it produces a copy. The private original keeps its own lifecycle (`:1-6`).
- Audiences are `commons` or `group:<name>`, where the name matches `[a-z][a-z0-9-]{0,63}` (`:18-19`, `:41-46`). Only episodes and semantics can be shared (`:20`).
- Reusing an existing copy is idempotent and checks digests (`:77-142`).
- `unshare` deletes the share row. It deletes the copy only when no other audience still holds it (`:176-204`). It stops future reads but cannot recall past disclosures (`atlas/docs/lighthouse.md:130-133`).
- `audiences_for` fails closed (`:236-254`).
- The tools are `share`, `unshare` and `shares` (`engram/server.py:1949-2015`). The published house is `ENGRAM_HOME/.engram/instances/lighthouse/graph.db` and is never created implicitly (`server.py:1934-1946`).

### 1.2 Publisher daemon and policy
- The daemon listens on a 0600 Unix socket (`lighthouse_daemon.py:455-476`) and accepts only `recall` and `read` (`:324-359`).
- Policy is reloaded on every request (`:339-347`). It is deny-by-default, directional and non-transitive (`lighthouse_policy.py:1-8`).
- Audience grants are held by the publisher, in `extensions["engram:audiences"]` (`lighthouse_daemon.py:156-170`). They are generated from `groups.toml` (`policy_gen.py:16-105`).
- `recall` returns no content and no similarity scores (`:396-398`). `read` is authorized again before any content is returned (`:401-453`).
- Every request writes a disclosure record, including denials (`:130-153`).
- The receiver's identity is taken from the request frame (`:366-370`), so it is not authenticated across machines.

### 1.3 Receiver side
- A receiver opts in with `instances/<receiver>/lighthouse-receiver.toml` (`neighbors.py:175-188`). Local recall never depends on a neighbor (`:1`).
- Consent is two-sided: the receiver's own policy must also allow the exchange (`:52-62`).
- The client has bounded transport (`lighthouse_client.py:6-11`).
- `context_lighthouse.py:79-104` re-checks `recall`, `read` and `inject_context` at dispatch time and writes content-free receipts (`lighthouse_receipts.py:1-6`).
- A context is a path of segments, such as `memory/technical` (`lighthouse_receiver_config.py:11-23`).

### 1.4 Disagreement without a winner
- `lighthouse_sheaf.py:1-25` and the atlas overlap check (`atlas/docs/lighthouse.md:121-126`) compute disagreement and keep it attributed. Trust is scoped per topic, and missing coverage is not counted as dissent.

### 1.5 `engram/federation.py` SignalBus
- It is a SQLite queue for direct messages and broadcasts (`:17-65`).
- It is used only in these places:
  - startup inbox processing (`server.py:1443-1461`);
  - the `genome_updated` broadcast (`server.py:1894-1899`);
  - `local_agent.py:68-98`;
  - `cli.py:79-93`.
- It has latent defects, none of which was observed in this run:
  - **Consent:** every received message becomes an episode in the recipient's memory, with no consent step (`:211-230`).
  - **Authentication:** `from_instance` is not authenticated (`:52-65`).
  - **Archival:** `archive_old` deletes a broadcast as soon as *anyone* has seen it (`:95-103`).
  - **Ordering:** messages are ordered by wall-clock text (`:75`).

### 1.6 Team-mode messaging (including w1's trace)
- **Transcript:** `messages.jsonl` is append-only and written under `fcntl` (`teamlib.py:268-286`).
- **Inboxes:** each worker's `inbox` lives in `state.json`, which is saved by atomic replace (`teamd.py:50-53`, `:275-290`). The lead has a `lead_inbox` and a single global `lead_cursor`, which `status` consumes (`:564-579`).
- **`team_post`** (via `say()`) writes locally and to Slack on a best-effort basis. **It never reaches a teammate's inbox** (`teamd.py:65-78`).
- **`team_plan` with Slack off** produces only a file in the team home. Claude workers can't read that file, because their sandbox denies `$HOME` (`workers.py:339`). The lead's manual relay to `.claude/team-relay/` works around this.
- **Peer messages are pushed only to collaborators** (`:415-442`):
  - a running Claude worker gets no live push; the message waits for `team_read` or for resume when the process exits (`:267-289`, `:337-344`);
  - Codex receives it at the turn boundary (`workers.py:403-407`).
- **No receipts:** when a worker resumes, everything pending is marked read before launch (`:292-315`). There are no message IDs, acks or dedup.
- **Fan-out:** `to="all"` sends N direct messages plus a copy to the lead (`:423-433`).
- **Truncation:** fencing cuts messages to 2000 characters, or 1500 for the lead (`teamlib.py:521-526`, `teamd.py:349-353`).
- **Race (w1):** a message that arrives between a worker's last `team_read` and its `team_done` can be stranded. A delivery to a worker that is already done can overwrite `self.procs[wid]` (`:260`, `:286-288`, `:445-460`).
- **`team_end`** keeps the transcript and plans and removes rooms and worktrees (`:606-622`). Nothing flows to engram unless an agent calls `remember` itself.

### 1.7 How team mode meets engram
- Each worker's engram root is its own folder, seeded with a copy of the repo's `.engram/config.toml` (`teamd.py:219-245`).
- That config has **no `instance` key**, so `config.py:359-370` falls back to `ENGRAM_DEFAULT_INSTANCE`. The lead and every Claude worker therefore use one store, across both lanes. w3 and w4 both observed plain `recall` returning Kairos's personal-lane memories.
- Codex workers currently have **no engram tools** (w1; `workers.py:215` keeps engram only if it is in the user's Codex config). So the personal lane did not leave through Codex in this run.
- `docs/team-mode.md:84` and `roles/collaborator.md:38` tell workers to "share to `group:agent-team`, then recall with `lighthouse_context`". That instruction fails at every step:
  - `group:agent-team` is not a valid context, because `:` fails `SEGMENT` (`lighthouse_receiver_config.py:14`; w4 reproduced this).
  - `neighbors.py:192` masks that error as `RECEIVER_CONFIG_INVALID`.
  - A valid context (`memory/technical`) returns `UNAVAILABLE`, because worker sandboxes can't connect to Unix sockets.
  - Even if they could, all workers present the same receiver name.

## 2. Layered model: descriptive vocabulary, not a roadmap

Principle: **nothing moves into a slower layer except by an explicit act that has an author and a reason.** This rules out copying `federation.process_inbox`.

| Layer | Address | Read by | Ordering | Durability | Consent / sovereignty | Exists today |
|---|---|---|---|---|---|---|
| L1 Direct | worker id | recipient (+ lead audit) | teamd append order | team lifetime + transcript | push only from lead/Kairos; peer→builder is pull-only | teamd |
| L2 Topic | free string (Zulip-style) | team, by pull | per topic | team lifetime | waking needs a subscription | no (not now) |
| L3 Broadcast | `all` | live members | as L1 | as L1 | fence + guard | teamd fan-out |
| L4 Lead inbox | `lead` | lead | append + cursor | team lifetime | escalations land here | teamd |
| L5 Private memory | engram instance | owner (*today: whole team*) | n/a | decays/compresses | sovereign root | engram |
| L6 Published share | `commons` / `group:<name>` | receivers in publisher-held policy | none (set of digested claims) | until `unshare`; past disclosures stand | two-sided policy, disclosure log, receipts | engram published house |
| L7 Lighthouse | publisher URN × context path | communities that opt in | per-publisher versioned artifacts | long-lived | directional, non-transitive, time-boxed; disagreement kept | daemon / offline artifacts |

- **Audience and context are different axes.** Audience answers who may read; the publisher resolves it from the receiver's identity. Context answers what the request is about; the receiver asks for it. The docs must not conflate the two.
- **Promotion path:** message → `remember` → `share(audience, reason)` → curated lighthouse view. Each step is explicit, reversible going forward and audited.
- **Cross-boundary L7** (other machines, tribal or community partners) first needs authenticated identity. Today the issuer is only declared (`atlas/docs/lighthouse.md:133`) and the receiver is taken from the frame (`lighthouse_daemon.py:366-370`). Policy and disclosure logs must also be owned by the publishing community. Superyak supplies the blocks; communities set the rules.

## 3. How team mode should relate to the layers
- **teamd stays the broker for L1–L4.** It already has HMAC tokens, fencing, push/pull delivery, guards and a single writer. Replacing it with SignalBus would lose all of that and add involuntary ingestion.
- **Engram holds L5–L7.** Team mode touches it only through explicit `remember` and `share` calls.
- **Cross-team reading is done by the lead.** The lead can reach the socket; worker sandboxes stay closed.

## 4. Prior art (general knowledge, not fetched this session)
- **Zulip** (topics as cheap strings): https://zulip.com/help/introduction-to-topics
- **Matrix** (per-server replicas, redaction can't unsend, state kept separate from timeline): https://spec.matrix.org/latest/
- **Secure Scuttlebutt** (per-identity signed append-only feeds, replication by consented follow, no global order; identity becomes the hard part): https://ssbc.github.io/scuttlebutt-protocol-guide/
- **Hypercore-style single-writer logs** (merge at read time). Avoid multi-writer CRDT merge for memories: it would blend accounts that the sheaf deliberately keeps apart.

## 5. What to do now (failures observed in this run)

| # | Failure | Evidence | Smallest fix | Effort |
|---|---|---|---|---|
| 1 | Claude workers read and write Kairos's whole private store, both lanes | repo `.engram/config.toml` has no `instance`; `config.py:359-370`; recall output (w3, w4) | **Kairos decides:** (a) seed `instance = team-<id>` in `_seed_engram_config`; (b) a lane=work recall default for workers; (c) accept and document. **(b) must land before Codex engram parity** | S |
| 2 | Docs prescribe a `group:agent-team` share/recall path that cannot work | `docs/team-mode.md:84`, `roles/collaborator.md:38`; `lighthouse_receiver_config.py:14`; UNAVAILABLE | Rewrite: audience ≠ context; workers can't read neighbors; the lead does cross-team reads | S |
| 3 | `RECEIVER_CONFIG_INVALID` hides the real cause | `neighbors.py:192` bare `except` | Propagate the specific code (`INVALID_CONTEXT`, `RECEIVER_STORE_MISMATCH`) | S |
| 4 | Posts and plans are write-only with Slack off; long docs are truncated in transit | `teamd.py:65-78`, `:376-406`; `workers.py:339`; `teamlib.py:521-526` | `team_read(kind="posts"\|"plans")` serves existing `messages.jsonl` and plan files through the team MCP; no new store (replaces the manual relay) | S–M |

**Not now:**
- **Topics with subscription.** Revisit if a team of more than about 6 workers shows interleaving.
- **Lead-approved beacon harvest.** Sequence it after decision #1. With a team-scoped instance it becomes the bridge; with a shared instance `remember` already is the bridge.
- **Cross-machine lighthouse transport and signatures.**
- **SignalBus.** Before anyone reuses it, drop auto-ingest and add per-reader cursors.

## 6. Open questions
- Is #1 intended? If Kairos keeps a shared store, document it. Either way, scope worker recall to the work lane before Codex workers get engram tools, because their context goes to another vendor.
- Who curates L7 for community lighthouses? It must be someone from the publishing community.

## Disagreements and resolution
- **w4: "name a concrete failure or no new channel."** Accepted. Topics and beacons are on the not-now list, and item 4 stays because three workers observed it.
- **w4: "label the table descriptive."** Done.
- **w4: "personal lane leaves via Codex."** Corrected with w1's evidence: Codex has no engram tools today. The real risk is ordering, so the lane default must come before Codex parity.

