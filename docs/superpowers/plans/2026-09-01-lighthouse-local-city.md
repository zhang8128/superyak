# Lighthouse Local City Implementation Plan (coordination)

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** The first live, policy-scoped crossing between engram instances on this machine, with content delivery and a validated `injected: true` receipt, built in parallel by two Codex teams and four Claude sessions without any two lanes editing the same recall code.

**Architecture:** A publisher daemon opens every local instance store read-only and answers `recall` and `read` over a Unix socket under deny-by-default Lighthouse policy. A receiver arm in engram's `recall()` fuses neighbor traces by weighted reciprocal rank and delivers under a separate `neighbors` key with a receipt. Lighthouse promotes the receipt to a core artifact and adds a preregistered live-shadow evaluation. This document coordinates the lanes; each code lane has its own plan.

**Tech Stack:** Python 3 (engram, pytest, sqlite-vec, FastEmbed), TypeScript on Node 24+ (Lighthouse, pnpm, vitest), codex-team (tmux, Codex CLI), Claude Code sessions.

**Spec:** `docs/superpowers/specs/2026-09-01-lighthouse-local-city-design.md`

**Lane plans:**
- E1: `docs/superpowers/plans/2026-09-01-local-city-e1-publisher-daemon.md` (engram, Codex dev1)
- E2: `docs/superpowers/plans/2026-09-01-local-city-e2-targeting.md` (engram, Codex dev2)
- L1: `~/Projects/lighthouse/docs/superpowers/plans/2026-09-01-local-city-l1-receipts-shadow.md` (lighthouse, Codex team)
- B0, E3, S, I: briefs in this document (Claude sessions)

**Shared contracts:** every exact name, frame shape, schema field, config key, and fixture path the lanes share is fixed in section "Contracts" below. Lane plans repeat what they need; this section wins on conflict.

## Global Constraints

- Publisher stores are opened read-only. `total_changes` stays zero and the file bytes are unchanged across any neighbor retrieval.
- Policy is deny-by-default, directional, non-transitive. `recall`, `read`, and `inject_context` are independent actions.
- Neighbor material is delivered under `response["neighbors"]` and never merged into `results`.
- Nothing in the neighbor path may raise into `recall()`. Failure yields `degraded: ["neighbors"]` and the unchanged local result.
- Receipts and exports contain digests, ids, counts, and decisions only. Never content, never query text.
- Only work-lane episodes and semantics are published. Instincts are never published.
- Lighthouse protocol version stays `"0.1"`. The engram export format becomes `"1.1"` with 1.0 still accepted.
- Engram lanes cut from `main` only after the integrator's step-zero commit. Lighthouse lanes cut from `main` HEAD.
- The MCP server executes old code until restarted. Every engram merge is followed by a restart before anything is verified live.
- Nothing is pushed to origin until the integrator has seen a validated `injected: true` receipt from a real session.
- No threshold on right-turn recall is claimed this cycle. Metrics are reported with a bootstrap interval, preregistered.

---

## Contracts

Copied from the design conversation; binding for every lane.

### Engram modules (E1 owns)

| Module | Public surface |
|---|---|
| `storage.py` | `Storage.open_read_only(db_path: Path) -> Storage`. `mode=ro`, `PRAGMA query_only=ON`, vec extension loaded, no migrations. Mutation methods raise `ReadOnlyStorageError`. |
| `lighthouse_policy.py` | `load_policy(path: Path) -> Policy`; `Policy.decide(req: PolicyRequest) -> Decision`; `PolicyRequest(publisher, profile, domain, action, context_id, claim_type, purpose, audience, at)`; `Decision(effect, rule_id, code)` with codes `NO_MATCHING_ALLOW`, `EXPLICIT_DENY`, `OUTSIDE_VALIDITY`. |
| `lighthouse_protocol.py` | Frames `recall`, `recall_result`, `read`, `read_result`, `error`, each `{"protocolVersion": "0.1", "kind": ...}`; `encode(frame) -> bytes`, `decode(line: bytes) -> Frame`. Error codes add `PUBLISHER_UNAVAILABLE`, `PROTOCOL_VERSION_MISMATCH`, `MALFORMED_FRAME`. |
| `lighthouse_daemon.py` | `python -m lighthouse_daemon --config <toml> [--socket <path>]`. Config: `publishers = ["why", "blocks"]`, `socket = "<path>"` (default `ENGRAM_HOME/.engram/lighthouse.sock`; config default `ENGRAM_HOME/.engram/lighthouse-daemon.toml`). Instance stores live at `ENGRAM_HOME/.engram/instances/<name>/graph.db` with `lighthouse-policy.json` beside each. Disclosures go to a sidecar `lighthouse-disclosures.db` beside the store (table `disclosures`), never to the read-only `graph.db`. Publisher and receiver identity is `urn:engram:<instance>`; frames carry the plain instance name and the daemon maps it. Never imports `server.py`. |
| `neighbors.py` | `neighbor_arm(*, query, context, purpose, k, storage, embeddings, config, session_id, recall_id, socket_path, policy_path, timeout_s=2.0) -> dict \| None`. Returns `{"receipt_id", "sources", "selected", "delivered"}` or `None` when no publisher applies; on failure returns `{"degraded": True, ...}`. Never raises. |
| `lighthouse_receipts.py` | `build_receipt(...) -> dict`; `validate_receipt(receipt)`; `write_receipt(storage, receipt, *, session_id, recall_id) -> str`. Validates against `schemas/lighthouse/recall-receipt.schema.json` with `jsonschema`; unknown members rejected; `injected` must equal `len(delivered) > 0`; writes `lighthouse_receipt` to the receiver's `memory_log` with `target_ids = ["<publisher>:<memoryId>", ...]`. The vendored schema is authored from the contracts until L1 generates the real one; L1's generated schema is authoritative, the integrator syncs it (Task I step 2), and E1 edits the engram side to conform if the sync test then fails. `schemas/` is packaged the same way `migrations/` is. |
| `lighthouse_label.py` | `python -m lighthouse_label --db <graph.db> --instance <name> --output <labels.json>`. Interactive. Never infers labels from outcomes. |
| `lighthouse_export.py` | Adds `receipts`; `formatVersion` `"1.1"`. |
| `server.py` | One call after `_observe_category_recall(...)` in `recall()`: attach `response["neighbors"]`; add `"neighbors"` to the degraded list when the payload says so. |

### Engram scoring and write path (E2 owns)

- `[memory] recency_mode = "tiebreak" | "additive"` (default `tiebreak`); `[memory] recency_cap = 0.02` (provisional). Both on `config.MemoryConfig`.
- Tiebreak: `score = similarity * w_sim + recency * recency_cap`. Additive: today's formula. One pure function `scoring.score_candidate(similarity, recency, auto_generated, *, mode, w_sim, w_rec, cap) -> float` in a new module `scoring.py` (so the replay script can score without importing `server.py`), used by `recall()` and `_unbiased_top`. `_unbiased_top` gains keyword-only `mode=None, cap=None`; its positional signature is unchanged. E1 does not touch `_unbiased_top`.
- `remember()` lane rule via `server._derive_lane(work, core, genome, context)`: `work=True` or `context.get("project")` truthy gives `lane="work"`, unless `context.get("lane") == "personal"`; core or genome episodes always stay personal.
- `dream_verify()` returns `scores` (matched) and `uninvited_scores` (raw similarity) separately. `_recall_scores[recall_id]` becomes `{"matched": {...}, "uninvited": {...}}`. `_recall_margins` is untouched.
- Lane filter applies to `scored` before the margin and before truncation.
- `hooks/sleep.py` `auto_capture_outcomes(conn, session_id) -> int` sets `memory_log.outcome = "used: auto: cited"` where it is NULL for session recalls whose result ids were later cited in the same session (later episode content or context, or `operation_log` rows for `mark_core`, `instinct_feedback`, `dream_react`). Never negatives, never overwrites. There is no separate outcomes table; `log_outcome` writes `memory_log.outcome`.

### Lighthouse (L1 owns)

- Artifact kind `RecallReceipt`, `payloadMediaType` `application/vnd.lighthouse.recall-receipt+json`, schema `schemas/recall-receipt.schema.json`. Payload: `turnId, context{id,path}, purpose, audience:"self", action:"recall", injected, transformation:"weighted-rrf-v1", receiverRule{ruleId}, sources[{publisher, role, weight, storeDigest, policyDecision{effect,ruleId,code}, traceOutcome}], selected[{publisher, memoryId, contentDigest, score, contributions[{publisher, rank}]}], delivered[{publisher, memoryId, readDecision}]`. Invariant `injected === (delivered.length > 0)`.
- Export `formatVersion: "1.1"` with optional `receipts: RecallReceipt[]`.
- Labels document `*.labels.json`: `{formatVersion:"1.0", instance, turns:[{turnId, context, purpose, relevant[], forbidden[]}]}`.
- Live-shadow mode: `pnpm lighthouse recall shadow --preregistration <pre.json> --export <x.engram.json> --labels <x.labels.json>`. Preregistration: `{corpusDigest, holdoutTurnIds[], cutoff:5, metrics:["rightTurnRecall","nDCG"], bootstrap:{samples:1000, seed}}`.
- Policy fixtures: `fixtures/policy-conformance/{policies,requests,decisions}/*.json`; generator `pnpm policy:fixtures`. Each request file carries a `_policy` member naming its policy file relative to `policies/`; each decision file is the exact `authorize` output for that request (`{"allowed": ..., "ruleId": ...}` or `{"allowed": false, "code": ...}`). Engram vendors a copy under `tests/fixtures/lighthouse/policy/` and asserts identical decisions through `Decision.to_lighthouse()`.
- Identity: publishers and receivers are `urn:engram:<instance>` in policies, receipts, fixtures, and labels. Content digests use algorithm label `sha256` (recall profile); envelope digests use the kit's own label as generated by `packages/protocol`.
- Shared-touch files: both engram lanes edit `pyproject.toml` (`py-modules`) and `CLAUDE.md`. E1 merges first; E2 rebases and resolves those two files. The lead treats a conflict anywhere else as a seam violation.

### First neighborhood

Receiver `engram`. Publishers `why`, `blocks`. Context `{"id": "memory/technical", "path": ["memory", "technical"]}`. Purpose `session-recall`. Audience `self`. Receiver grants `recall`, `read`, `inject_context` for both publishers in that context with a validity interval ending 2026-10-15. Publishers allow `recall` and `read` to receiver `engram` in that context only.

---

## Lane map

| Lane | Executor | Cuts from | Produces | Blocks |
|---|---|---|---|---|
| Step 0 | Integrator (this session) | n/a | Committed working tree, recorded base refs | everything |
| B0 | Claude session | engram main (read-only, scratch) | `docs/reports/2026-09-b0-neighbor-spike.md` | E1 Tasks for the receiver arm |
| L1 | Codex team, lighthouse | lighthouse main | Receipt artifact, shadow mode, labels format, policy fixtures | E1 vendored schema and fixtures (E1 stubs first, then syncs) |
| E1 | Codex team engram, dev1 | engram main after step 0 | Daemon, receiver arm, receipts, exporter 1.1, labeling CLI | live acceptance |
| E2 | Codex team engram, dev2 | engram main after step 0 | Replay report, targeting fixes | E3 re-measurement |
| E3 | Claude session | engram main, data only | Calibration reports, labels, preregistration, first assessment | live acceptance (labels, preregistration) |
| S | Claude session | docs only | Science-pilot design spec | nothing |
| I | Integrator | both | Merges, restarts, live acceptance report, docs | close of cycle |

---

### Task 0: Step zero (Integrator)

**Files:**
- Commit: every tracked and untracked file currently in the engram working tree except caches.

- [ ] **Step 1: Confirm the tree contains only intended files**

Run: `cd ~/Projects/engram && git status --short && git check-ignore -q docs/fieldtests-2026-08-02/__pycache__ && echo pycache-ignored`
Expected: the modified and untracked list matches the September 1 review (CLAUDE.md, dedup.py, framing.py, margins.py, pyproject.toml, reflection.py, server.py, five test files, two research docs, `docs/fieldtests-2026-08-02/`, `tests/test_dedup.py`) and `pycache-ignored` prints.

- [ ] **Step 2: Run the suite once more on the exact tree being committed**

Run: `.venv/bin/python -m pytest tests/ -q`
Expected: `1490 passed` (warnings allowed).

- [ ] **Step 3: Commit the tree**

```bash
git add -A
git commit -m "feat: tropical margins, think-mode dedup and framing fix, August field tests

Margins: recall reports gamma, normalized margin, fts_tie, and a
bias-stability counterfactual; hidden while dreaming, revealed by
dream_verify, logged always; reflect(focus=\"margins\").
Dedup/framing: think:false for thinking models, retry without the flag,
empty+length treated as a signal not a verdict.
Docs: 2026-08-02 field scan, field-test results, and test artifacts.

Co-Authored-By: Claude Fable 5.1 <noreply@anthropic.com>
Claude-Session: https://claude.ai/code/session_01MJAfpBppHULvppj1iowXHs"
```

- [ ] **Step 4: Record base refs**

Run: `git rev-parse HEAD && (cd ~/Projects/lighthouse && git rev-parse HEAD)`
Write both SHAs at the top of `docs/reports/2026-09-local-city-cycle.md` under a heading `Base refs`. Create the file with that heading and the two lines; nothing else yet.

- [ ] **Step 5: Restart the MCP server so the live process runs the committed margins code**

Exit the Claude Code session that hosts the engram MCP server and start a new one. Verify: `status()` shows `last_maintenance.at` later than the restart time.

---

### Task B0: Neighbor spike (one Claude session, throwaway)

**Purpose:** Measure whether `why` and `blocks` would have supplied anything to `engram`'s last 60 recalls before the daemon is built. Gate for E1's receiver arm.

**Files:**
- Create in scratch only: `<scratchpad>/b0/b0_spike.py`, `<scratchpad>/b0/*.db` copies, `<scratchpad>/b0/b0_report.json`
- Create: `docs/reports/2026-09-b0-neighbor-spike.md` (the only committed artifact)

**Interfaces:**
- Consumes: `storage.Storage(db_path)`, `Storage.search_vectors(layer, embedding, k) -> list[(id, distance)]`, `Storage.get_episode(id) -> dict | None`, `Storage.get_semantic(id) -> dict | None`, `embeddings.NomicEmbedProvider().embed(texts, prefix="search_query")`.
- Produces: a report with counts and a go or no-go recommendation.

- [ ] **Step 1: Copy the three stores with SQLite backup (never open the live files for writing)**

```bash
S=/private/tmp/claude-501/-Users-kairos-Projects-engram/$CLAUDE_SESSION_ID/scratchpad/b0; mkdir -p "$S"
for n in engram why blocks; do
  sqlite3 "file:$HOME/Projects/engram/.engram/instances/$n/graph.db?mode=ro" ".backup $S/$n.db"
done
ls -la "$S"
```
Expected: three `.db` files.

- [ ] **Step 2: Write the spike script**

```python
# b0_spike.py  (throwaway; never committed)
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path.home() / "Projects" / "engram"))
from storage import Storage
from embeddings import NomicEmbedProvider

S = Path(sys.argv[1])
local = Storage(str(S / "engram.db"))
neighbors = {n: Storage(str(S / f"{n}.db")) for n in ("why", "blocks")}
emb = NomicEmbedProvider()

rows = local.conn.execute(
    "SELECT context FROM memory_log WHERE event_type='recall' "
    "ORDER BY timestamp DESC LIMIT 60").fetchall()
queries = []
for r in rows:
    try:
        q = json.loads(r["context"] or "{}").get("query")
    except ValueError:
        q = None
    if q:
        queries.append(q)

local_hashes = {row[0] for row in local.conn.execute(
    "SELECT content_hash FROM episodes UNION SELECT content_hash FROM semantics")}

report = []
for q in queries:
    vec = emb.embed([q], prefix="search_query")[0]
    for name, st in neighbors.items():
        hits = []
        for layer in ("episode", "semantic"):
            for mid, dist in st.search_vectors(layer, vec, k=3):
                row = st.get_episode(mid) if layer == "episode" else st.get_semantic(mid)
                if row and (row.get("lane") or "personal") == "work":
                    hits.append((dist, layer, mid, row.get("content_hash"), (row.get("content") or "")[:200]))
        hits.sort()
        for dist, layer, mid, h, snippet in hits[:3]:
            report.append({"query": q, "publisher": name, "layer": layer, "id": mid,
                           "distance": dist, "novel": h not in local_hashes, "snippet": snippet})

(S / "b0_report.json").write_text(json.dumps(report, indent=1))
novel = [r for r in report if r["novel"]]
print(f"queries={len(queries)} candidates={len(report)} novel={len(novel)} "
      f"novel_share={len(novel) / max(1, len(report)):.2f}")
```

- [ ] **Step 3: Run it**

Run: `cd ~/Projects/engram && .venv/bin/python "$S/b0_spike.py" "$S"`
Expected: one summary line. If `queries=0`, the recall log has no query text in context; stop and report that instead.

- [ ] **Step 4: Hand-judge twenty novel candidates**

Sample 20 entries with `novel: true` (all of them if fewer). For each, read the query and the snippet and answer one question: would this have been useful at that turn, yes or no. Record the answers in the report. Do not use a model as the judge for this step; the point is the receiver's judgment.

- [ ] **Step 5: Write the report and commit only the report**

`docs/reports/2026-09-b0-neighbor-spike.md` contains: the three counts from step 3, the novel share, the twenty judgments as a table (query, publisher, layer, distance, useful), the count of useful, and one line: `Recommendation: go` if at least 4 of 20 were useful, otherwise `Recommendation: no-go`. The threshold is provisional and the report says so. Do not include memory content beyond the 200-character snippets already shown to the judge; if any snippet is personal-lane by mistake, remove it.

```bash
git add docs/reports/2026-09-b0-neighbor-spike.md
git commit -m "docs: B0 neighbor spike report"
```

- [ ] **Step 6: Tell the integrator the recommendation** in the plan's cycle report (`docs/reports/2026-09-local-city-cycle.md`, section `B0`).

---

### Task L1: Lighthouse receipts and shadow mode (Codex team on lighthouse)

Brief for the Codex lead: the work-package block at the top of `~/Projects/lighthouse/docs/superpowers/plans/2026-09-01-local-city-l1-receipts-shadow.md`.

- [ ] **Step 1: Start the team**

```bash
cd ~/Projects/lighthouse && codex-team main --task local-city-l1
```

- [ ] **Step 2: Paste the work-package brief to the lead pane.** Add: "Two devs: dev1 takes the RecallReceipt artifact, export 1.1, and labels schema; dev2 takes preregistration, shadow mode, the corpus-digest subcommand, bootstrap, and policy fixtures; cross-review as usual. A `pnpm-lock.yaml` diff limited to the new workspace dependency is accepted. The original proof's `bridgeDigest` and its 15 checks must be unchanged."

- [ ] **Step 3: When the lead reports the integration branch green**, the integrator copies `schemas/recall-receipt.schema.json` and `fixtures/policy-conformance/` into engram (Task I, step 3) and records the lighthouse SHA in the cycle report.

---

### Task E1 and E2: Engram code lanes (Codex team on engram)

Briefs for the Codex lead: the work-package blocks at the top of the E1 and E2 plans.

- [ ] **Step 1: Start the team (after Task 0)**

```bash
cd ~/Projects/engram && codex-team main --task local-city-e
```

- [ ] **Step 2: Paste both work-package briefs to the lead pane.** Add: "dev1 takes E1, dev2 takes E2. The allowed-files and forbidden-files lists are the seam; the cross-review checks every touched file against them. E1's `server.py` call site merges first; E2 rebases across it. E1's receiver arm tasks wait for the B0 recommendation in `docs/reports/2026-09-b0-neighbor-spike.md`; everything before the receiver arm proceeds now."

- [ ] **Step 3: On a B0 no-go**, tell the lead: "E1 stops after the daemon and protocol tasks; the receiver arm, call site, and labeling CLI are deferred." Record in the cycle report.

---

### Task E3: Calibration, labeling, first assessment (one Claude session)

**Files:**
- Create: `docs/reports/2026-09-cohesion-calibration.md`, `docs/reports/2026-09-inverted-u-pilot.md`, `docs/fieldtests-2026-09/` (scripts and blinded artifacts), `docs/reports/2026-09-uninvited-band-audit.md`, `docs/reports/2026-09-duplicates-sweep.md`, `docs/reports/2026-09-instinct-redistill.md`, `docs/reports/2026-09-local-city-preregistration.json`, `docs/reports/2026-09-local-city-labels.json`
- Modify: nothing under source. The instinct re-distillation applies to the live store only after approval and with a backup.

**Interfaces:**
- Consumes: `python sheaf.py <copy>`, `docs/fieldtests-2026-08-02/test1_pairing.py`, `Storage.sample_distant_memories(embedding, matched_ids, k, layers=None) -> list[(id, layer, distance)]`, `dedup.Deduplicator().find_duplicates(items, key="content")`, `framing.FramingDistiller().distill(content, kind) -> (notice, implication) | None`, MCP tools `assessment_schedule`, `assessment_report`, `reflect`.
- Produces: reports, the labels document, and the preregistration document.

- [ ] **Step 1: Make a working copy of the engram store**

```bash
S=/private/tmp/claude-501/-Users-kairos-Projects-engram/$CLAUDE_SESSION_ID/scratchpad/e3; mkdir -p "$S"
sqlite3 "file:$HOME/Projects/engram/.engram/instances/engram/graph.db?mode=ro" ".backup $S/engram.db"
```

- [ ] **Step 2: Cohesion calibration**

Run: `cd ~/Projects/engram && .venv/bin/python sheaf.py "$S/engram.db" > "$S/cohesion.txt" 2>&1; tail -40 "$S/cohesion.txt"`
Write `docs/reports/2026-09-cohesion-calibration.md`: the energy for the three known-conflated semantics from the August field test (the "Records of complex system analysis" and "Technical development and strategic planning" semantics and the junk sink) versus the three known-faithful ones (Vaughn's name, Danielle's EDS, the self-observation disposition); whether hot and cool separate; a recommendation on `[cohesion] enabled`, held provisionally. Include the sheaf script's own summary lines verbatim.

- [ ] **Step 3: Inverted-U dream-pairing pilot**

Copy `docs/fieldtests-2026-08-02/test1_pairing.py` to `docs/fieldtests-2026-09/test1b_inverted_u.py` and change the pairing to four distance bands with 12 pairs each: `within` (same KMeans cluster), `near` (different cluster, distance in the bottom third of cross-cluster distances), `mid` (middle third), `far` (top third). Keep the prompt, `gemma4:31b` with `think: false`, temperature 0.7, and the 0 to 3 rubric. Shuffle and strip labels; have a fresh subagent judge blind with the August rubric text; unblind after. Write `docs/reports/2026-09-inverted-u-pilot.md` with per-band mean, keeper rate, and the Spearman correlation of distance against score across all 48. State the sample size limits plainly.

Run: `.venv/bin/python docs/fieldtests-2026-09/test1b_inverted_u.py "$S/engram.db" docs/fieldtests-2026-09/`

- [ ] **Step 4: Uninvited-band audit**

Write `docs/fieldtests-2026-09/uninvited_band_audit.py`:

```python
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "Projects" / "engram"))
from storage import Storage
from embeddings import NomicEmbedProvider

st = Storage(sys.argv[1]); emb = NomicEmbedProvider()
rows = st.conn.execute("SELECT context FROM memory_log WHERE event_type='recall' "
                       "ORDER BY timestamp DESC LIMIT 60").fetchall()
out = []
for r in rows:
    q = json.loads(r["context"] or "{}").get("query")
    if not q:
        continue
    vec = emb.embed([q], prefix="search_query")[0]
    top = st.search_vectors("episode", vec, k=1)
    top_dist = top[0][1] if top else None
    matched = {mid for mid, _ in st.search_vectors("episode", vec, k=20)}
    for did, layer, dist in st.sample_distant_memories(vec, matched, k=3):
        out.append({"query": q[:60], "top_distance": top_dist, "uninvited_distance": dist, "layer": layer})
json.dump(out, open(sys.argv[2], "w"), indent=1)
ds = sorted(o["uninvited_distance"] for o in out)
print("n", len(ds), "min", ds[0], "median", ds[len(ds)//2], "max", ds[-1])
```

Run: `.venv/bin/python docs/fieldtests-2026-09/uninvited_band_audit.py "$S/engram.db" docs/fieldtests-2026-09/uninvited_bands.json`
Write `docs/reports/2026-09-uninvited-band-audit.md`: histogram of uninvited distances against the top-match distance, and which band of the inverted-U pilot the slot's picks fall in.

- [ ] **Step 5: Duplicates sweep**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "Projects" / "engram"))
from storage import Storage
from dedup import Deduplicator
st = Storage(sys.argv[1])
items = [dict(r) for r in st.conn.execute("SELECT id, content, lane, confidence FROM semantics")]
d = Deduplicator()
print("llm available:", d.is_available())
pairs = d.find_duplicates(items, key="content")
for i, j in pairs:
    print(items[i]["id"][:8], items[j]["id"][:8], "|", items[i]["content"][:80], "||", items[j]["content"][:80])
```

Run it against the copy. Write `docs/reports/2026-09-duplicates-sweep.md`: every pair, a recommended action per pair (merge, keep both, retire one), and nothing applied. Merges are a decision for Kairos.

- [ ] **Step 6: Instinct re-distillation proposal**

```python
import sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "Projects" / "engram"))
from storage import Storage
from framing import FramingDistiller
st = Storage(sys.argv[1]); fd = FramingDistiller()
for inst in st.get_all_instincts():
    notice = inst.get("notice") or ""
    action = inst.get("action") or ""
    if notice.startswith("when ") and (action.lower().startswith(notice[5:20].lower()) or len(notice) >= 60):
        out = fd.distill(action, inst.get("kind") or "fact")
        print(inst["id"], "\n  OLD:", notice, "\n  NEW:", out)
```

Write `docs/reports/2026-09-instinct-redistill.md` with the old and proposed notice and implication per instinct. Apply only after Kairos approves, and then: back up the live store with `.backup`, run `UPDATE instincts SET notice=?, implication=? WHERE id=?` per approved row, restart the MCP server, and confirm the wake orientation shows the new notices.

- [ ] **Step 7: Schedule and complete the first off-device assessment**

At the end of an E3 session call the MCP tool `assessment_schedule(reason="local city cycle calibration")`. The next session starts blind; work normally for at least thirty minutes, then call `assessment_report(...)` honestly. Afterwards run `reflect(focus="assessments")` and paste the history into `docs/reports/2026-09-local-city-cycle.md` under `Assessment 1`.

- [ ] **Step 8: Choose the holdout queries (before the live run)**

Pick 30 queries from the engram recall log that are technical and belong in context `memory/technical`. Write them to `docs/reports/2026-09-local-city-holdout-queries.json` as `{"queries": ["...", ...]}` and commit it before the live run. The integrator replays exactly these queries (Task I step 6), which produces one receipt per turn. The order of honesty for the evaluation is fixed: retrieval and receipts first, then labels, then preregistration, then the metric. Nobody sees a metric before labels and preregistration are committed.

- [ ] **Step 9: Label the holdout turns (after the live run, before any metric)**

Run: `.venv/bin/python -m lighthouse_label --db <fresh copy of the live engram store> --instance engram --output docs/reports/2026-09-local-city-labels.json`
The CLI reads the 30 `lighthouse_receipt` events and presents each turn's publisher-qualified candidates. Mark relevant and forbidden. Forbidden is anything personal, relational, or outside the technical context. The labels file contains publisher-qualified ids only. Commit it.

- [ ] **Step 9b: Write the preregistration (after labels, before the shadow evaluation)**

Export the same copy with `.venv/bin/python -m lighthouse_export --db <copy> --instance engram --output "$S/engram.engram.json"`, then obtain the corpus digest from the adapter:

```bash
cd ~/Projects/lighthouse && pnpm --silent lighthouse recall digest --export "$S/engram.engram.json"
```

Write `docs/reports/2026-09-local-city-preregistration.json` with the 30 receipt turn ids from the run manifest:

```json
{
  "receiverPublisher": "urn:engram:engram",
  "corpusDigest": {"algorithm": "<as printed>", "value": "<as printed>"},
  "holdoutTurnIds": ["<30 receipt turn ids>"],
  "cutoff": 5,
  "metrics": ["rightTurnRecall", "nDCG"],
  "bootstrap": {"samples": 1000, "seed": 20260901}
}
```

Commit it. Only then may Task I step 8 run the shadow evaluation. If the export digest changes afterwards, the evaluation is invalid; regenerate and say so in the cycle report.

- [ ] **Step 10: Re-measure after E2 merges and after the restart**

Run the two queries from the September 1 review against the live store read-only and `reflect(focus="margins")`, and append a `Post-E2` section to `docs/reports/2026-09-margins-replay.md` with near-tie rate, recent-winner share at 7 days and 1 day, and outcome coverage. Run it again one week later for outcome coverage.

```bash
db=~/Projects/engram/.engram/instances/engram/graph.db
sqlite3 -header "file:$db?mode=ro" "WITH r AS (SELECT timestamp AS ts, json_extract(target_ids,'\$[0]') AS top FROM memory_log WHERE event_type='recall' AND json_array_length(target_ids)>0 ORDER BY timestamp DESC LIMIT 60) SELECT COUNT(*) n, SUM(julianday(r.ts)-julianday(e.created_at) <= 7) le7, SUM(julianday(r.ts)-julianday(e.created_at) <= 1) le1 FROM r JOIN episodes e ON e.id=r.top;"
sqlite3 -header "file:$db?mode=ro" "SELECT COUNT(*) recalls, SUM(outcome IS NOT NULL) with_outcome FROM memory_log WHERE event_type='recall' AND timestamp >= date('now','-30 days');"
```

---

### Task S: Science-pilot design (one Claude session, docs only)

**Files:**
- Create: `docs/superpowers/specs/2026-09-<day>-science-pilot-design.md`

- [ ] **Step 1: Run the brainstorming skill with Kairos**, not solo. The three questions in spec section 13 are the agenda: policy from memory, the uncertainty field for semantics, and the oracle-backed assessment.

- [ ] **Step 2: The design must name one concrete domain with a public, cheap oracle** (candidates to discuss: pendulum period against length, Kepler's third law from orbital data, ideal-gas measurements), and state the minimal falsifiable test: episodes are observations, compression forms semantics and instincts, an off-device assessment scores the instincts' attention directives against held-out observations by prediction, not self-report.

- [ ] **Step 3: No build.** The spec ends with the same "Approved / spec written for review" status line as the local-city spec and is committed alone.

---

### Task I: Integration and live acceptance (Integrator)

**Files:**
- Create: `docs/reports/2026-09-local-city-cycle.md` (running record), `docs/reports/2026-09-local-city-acceptance.md`
- Modify: `CLAUDE.md` (E1 and E2 lane plans specify their paragraphs; the integrator verifies both landed)

- [ ] **Step 1: Merge order.** L1 integration branch first (lighthouse), then E1, then E2 rebased across E1's call site. After each engram merge: run `.venv/bin/python -m pytest tests/ -q`, then restart the MCP server, then `status()`.

- [ ] **Step 2: Sync artifacts from lighthouse into engram** after L1 lands:

```bash
cp ~/Projects/lighthouse/schemas/recall-receipt.schema.json ~/Projects/engram/schemas/lighthouse/recall-receipt.schema.json
rsync -a --delete ~/Projects/lighthouse/fixtures/policy-conformance/ ~/Projects/engram/tests/fixtures/lighthouse/policy/
cd ~/Projects/engram && .venv/bin/python -m pytest tests/test_lighthouse_policy.py tests/test_lighthouse_receipts.py -q
```
Expected: green. Commit the synced files with the lighthouse SHA in the message.

- [ ] **Step 3: Write the three policy files.** The integrator, not E1, writes the live files from the templates in the E1 plan's Task 5 and Task 7 test helpers into `.engram/instances/{engram,why,blocks}/lighthouse-policy.json`, with the receiver's grants for `urn:engram:why` and `urn:engram:blocks` in context `memory/technical`, purpose `session-recall`, `validUntil` `2026-10-15T00:00:00Z`, and `extensions["engram:weight"]` of `1.0` per publisher. Validate each:

```bash
cd ~/Projects/lighthouse && for n in engram why blocks; do pnpm --silent lighthouse validate ~/Projects/engram/.engram/instances/$n/lighthouse-policy.json; done
```
Expected: each prints a passing validation.

- [ ] **Step 4: Record publisher store digests before the run**

```bash
for n in why blocks; do shasum -a 256 ~/Projects/engram/.engram/instances/$n/graph.db; done | tee -a docs/reports/2026-09-local-city-acceptance.md
```

- [ ] **Step 5: Start the daemon**

```bash
cd ~/Projects/engram && printf 'publishers = ["why", "blocks"]\n' > .engram/lighthouse-daemon.toml
.venv/bin/python -m lighthouse_daemon --config .engram/lighthouse-daemon.toml &
```
Expected: the daemon logs each publisher opened read-only and the socket path.

- [ ] **Step 6: Live crossing.** Two parts, both against the live receiver store with the daemon running.

Part one, by hand in a real Claude Code session in `~/Projects/engram`: call the MCP tool `recall(...)` with three of the holdout queries. For each response record: `neighbors` present, `neighbors.delivered` non-empty for at least one, `results` unchanged in shape, `degraded` absent. Paste the receipt ids into the acceptance report.

Part two, the holdout replay through the same code path, run while no other session is mid-recall:

```python
# scratch/local_city_run.py  (integrator tooling; manifest stays in scratch)
import json, sys
from pathlib import Path
sys.path.insert(0, str(Path.home() / "Projects" / "engram"))
import server

queries = json.loads(Path(sys.argv[1]).read_text())["queries"]
server._init()
rows = []
for q in queries:
    out = server.recall(query=q, uninvited=0)
    nb = out.get("neighbors") or {}
    rows.append({"query": q, "recall_id": out["recall_id"], "receipt_id": nb.get("receipt_id"),
                 "delivered": len(nb.get("delivered") or []), "degraded": out.get("degraded")})
Path(sys.argv[2]).write_text(json.dumps(rows, indent=1))
print(sum(1 for r in rows if r["delivered"]), "of", len(rows), "turns delivered;",
      sum(1 for r in rows if r["degraded"]), "degraded")
```

Run: `cd ~/Projects/engram && .venv/bin/python scratch/local_city_run.py docs/reports/2026-09-local-city-holdout-queries.json "$S/run-manifest.json"`
Expected: 30 rows, 0 degraded, at least one delivered. Copy only the 30 `recall_id` values into the acceptance report; the manifest with query text is not committed. E3 now labels (E3 step 9) and preregisters (E3 step 9b) before step 8 below runs.

- [ ] **Step 7: Verify receipts and disclosures**

```bash
db=~/Projects/engram/.engram/instances/engram/graph.db
sqlite3 "file:$db?mode=ro" "SELECT COUNT(*) FROM memory_log WHERE event_type='lighthouse_receipt' AND json_extract(context,'\$.receipt.payload.injected')=1;"
for n in why blocks; do sqlite3 "file:$HOME/Projects/engram/.engram/instances/$n/lighthouse-disclosures.db?mode=ro" "SELECT COUNT(*) FROM disclosures;"; done
```
Expected: at least 1 receipt with `injected` true; each publisher's sidecar shows disclosures. `write_receipt` stores the artifact under `context.receipt` with `recall_id` and `session_id` beside it (E1 plan, Task 6).

- [ ] **Step 8: Export and validate through Lighthouse**

```bash
cd ~/Projects/engram && sqlite3 "file:.engram/instances/engram/graph.db?mode=ro" ".backup /tmp/lc-engram.db"
.venv/bin/python -m lighthouse_export --db /tmp/lc-engram.db --instance engram --output /tmp/lc-engram.engram.json
cd ~/Projects/lighthouse && pnpm --silent lighthouse validate /tmp/lc-engram.engram.json
pnpm --silent lighthouse recall shadow --preregistration ~/Projects/engram/docs/reports/2026-09-local-city-preregistration.json --export /tmp/lc-engram.engram.json --labels ~/Projects/engram/docs/reports/2026-09-local-city-labels.json | tee -a ~/Projects/engram/docs/reports/2026-09-local-city-acceptance.md
```
Expected: validation passes; the shadow report shows forbidden exposure 0 and unauthorized selections 0 in `policy-scoped`, the unsafe control non-zero, and both metrics with intervals. Record numbers only.

- [ ] **Step 9: Non-mutation check**

```bash
for n in why blocks; do shasum -a 256 ~/Projects/engram/.engram/instances/$n/graph.db; done | tee -a docs/reports/2026-09-local-city-acceptance.md
```
Expected: identical to step 4. Also `PRAGMA data_version` unchanged if recorded.

- [ ] **Step 10: Degradation check.** Stop the daemon (`kill %1`), call `recall(...)` again in the live session. Expected: no `neighbors` key, `degraded` contains `neighbors`, `results` identical in shape and count to a daemon-up recall of the same query.

- [ ] **Step 11: Both suites and both proofs**

```bash
cd ~/Projects/engram && .venv/bin/python -m pytest tests/ -q
cd ~/Projects/lighthouse && pnpm check && pnpm --silent proof | grep -o '"passed":[a-z]*' && pnpm --silent recall:proof | grep -o '"passed":[a-z]*'
```
Expected: engram green; both proofs `"passed":true` with the original `bridgeDigest` unchanged.

- [ ] **Step 12: Docs and record.** Confirm the CLAUDE.md paragraphs from E1 and E2 landed. Mark the spec status `Shipped 2026-09-<day>` with the acceptance report path. Store an engram episode summarizing the cycle with counts only. Only then decide, with Kairos, whether to push.

---

## Self-review against the spec

| Spec section | Where |
|---|---|
| 4.1 read-only open | E1 plan |
| 4.2 daemon | E1 plan |
| 4.3 protocol, query disclosure stated | E1 plan; Contracts |
| 4.4 policy, cross-implementation | E1 plan (Python), L1 plan (fixtures), Task I step 2 |
| 4.5 receiver arm, separate channel | E1 plan |
| 4.6 receipts | E1 plan, L1 plan |
| 4.7 Lighthouse changes | L1 plan |
| 4.8 exporter 1.1 | E1 plan |
| 4.9 labeling CLI | E1 plan; E3 step 9 |
| 5 data flow, 6 failure semantics | E1 plan tests; Task I step 10 |
| 7 first neighborhood, expiring grant | Contracts; Task I step 3 |
| 8 spike | Task B0 |
| 9 lanes, seam, coordination, order | Lane map; Tasks L1, E1/E2; Task I step 1 |
| 10 acceptance | Task I steps 6 to 11; E2 acceptance in E2 plan; E3 acceptance in Task E3 |
| 11 testing | lane plans; Task I step 11 |
| 12, 13 deferred and open questions | Task S |
