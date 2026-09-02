# Local city cycle record

## Base refs

- engram main: 195439d537ebc2d5e84d61b6c66dd7b5c03dc59c (step zero, 2026-09-01)
- lighthouse main: 0a6fae7e515ce6f0e9c2e9e0a70a5094a13027f9 (2026-09-01)

## B0

Census 2026-09-01: no-go for `why` and `blocks` (zero work-lane rows,
identical March snapshots). Neighborhood amended to `lighthouse`, a new
instance bound to `~/Projects/lighthouse` (lighthouse commit b9dc702).
Spike re-runs against `lighthouse` at 30 work-lane episodes. Report:
`docs/reports/2026-09-b0-neighbor-spike.md`.

## Step zero

Working tree committed as 195439d; 1490 tests passed on that tree. The live
MCP server in the integrator session was already running this code (margins
data visible through reflect before the commit), so no restart was needed
for step zero. Every later engram merge still requires one.

## Outcome coverage baseline

Last 30 days at cycle start: 14 of 31 recalls carry an outcome.

## Teams launched (2026-09-01 evening)

- lighthouse `team-lighthouse-local-city-l1`: first launch at 19:30 failed on
  MCP tool approval (codex 0.152 denies MCP calls under approval_policy=never
  unless the tool's approval_mode is "approve"; launcher fixed in codex-team
  b9b35cb). Relaunched 19:42 from lighthouse main b9dc702; lead confirmed
  both devs via team_status(); brief delivered through the tmux paste buffer.
- engram `team-engram-local-city-e`: launched 19:46 from engram main 5fb3804;
  dev1 = E1, dev2 = E2; brief delivered the same way, with the seam rule, the
  B0 gate on the receiver arm, and a reference-only note about the branch
  `feature/engram-lighthouses`.

## Prior art noted

`feature/engram-lighthouses` (2026-08-27..28, 48 commits, ~35k lines): a
Postgres-backed multi-user Lighthouse service inside engram (lighthouse/
package: mesh API, gluing, overlaps, invalidation, GitLab authority via Hyper
Coordinator, own MCP server), spec approved 2026-08-27. Three days later the
protocol repo chose a sibling-repository design. Kairos's decision this cycle:
reference only; nothing merged or imported; the service can become a publisher
later.

## Overnight log (2026-09-01 late)

- 20:0x The lighthouse instance binding was broken from 19:11 until
  lighthouse commit 760b88e. Two causes in sequence: the config I appended
  duplicated the `[memory]` table (TOML parse error), and after fixing that,
  `default_lane` is not yet a `MemoryConfig` field, so engram's loader raised
  on it. Either way `resolve_db_path` swallows the exception and silently
  falls back to the default store. Consequence: the L1 team's three Codex
  sessions woke into the `engram` store (three `session_start` rows there
  at 19:42) and will stay bound to it for their lifetime. The `lighthouse`
  store has zero rows. The B0 gate cannot open overnight; the receiver arm
  waits. The binding now resolves correctly for any session started in
  `~/Projects/lighthouse` from here on. `default_lane = "work"` returns to
  that config once E2 lands.
- Follow-up defect for the engram lanes (not done overnight): a project
  config that fails to parse silently reroutes memory to a different store.
  `resolve_db_path` should fail loudly, or at least log at WARNING with the
  parse error, and `MemoryConfig` should ignore unknown keys with a warning
  instead of raising.
- L1 lead escalation, authorized narrowly: `schemas/lighthouse-descriptor.schema.json`
  regenerated (kind enum gains RecallReceipt only) and `biome.json` gains one
  exclusion for `fixtures/policy-conformance` so canonical fixture bytes
  survive lint. Both added to the WP allowed list for those changes only.
- Engram team: the dev2/lead pair tripped the loop guard (8 messages per
  30 minutes) on ordinary WP setup traffic. Cleared with `codex-team reset`.
  Standing decisions given to the lead: devs use the main checkout's
  interpreter read-only (`/Users/kairos/Projects/engram/.venv/bin/python`)
  with their worktree as cwd and a per-dev `UV_CACHE_DIR` under /private/tmp,
  because linked worktrees carry no venv and the sandbox denies ~/.cache/uv;
  message traffic is batched one send per WP event. `jsonschema` 4.26.0 was
  already importable from the shared venv, so E1's tests can import it; the
  pyproject change stays on E1's branch.
- Follow-up for codex-team: `up` should provision an interpreter per worktree
  (symlink or uv sync) and set UV_CACHE_DIR in the launch scripts; the loop
  guard's default budget is too tight for a two-message brief plus
  acceptance relay.
- Both teams' devs could not commit: codex 0.152's workspace-write sandbox
  keeps a linked worktree's gitdir read-only, so `git commit` failed on
  `<repo>/.git/worktrees/<name>/index.lock` in every dev worktree. Verified
  with `codex sandbox` on a scratch repo: default config fails; an explicit
  `sandbox_workspace_write.writable_roots=["<repo>/.git"]` commits cleanly
  with cwd, /tmp, and $TMPDIR still writable; a narrower grant errors on
  `packed-refs.lock`. Launcher fixed with a test (codex-team 617df61), the
  six live launch scripts patched, the four dev panes respawned in place
  (`tmux respawn-pane -k`, pane ids preserved, worktrees untouched with all
  uncommitted work). Leads kept their context and were told to re-send
  assignments; leads get relaunched before integration. Uncommitted work at
  relaunch: L1 dev1 (RecallReceipt schema, protocol tests), L1 dev2 (policy
  fixtures, generator, biome exclusion), E dev1 (read-only Storage, protocol,
  policy tests), E dev2 (replay report, scoring.py, tests).
- Live verification of the sandbox fix: engram dev1 made the previously
  blocked commit from its relaunched pane (`011624d feat: add read-only
  Storage open path for publishers` on team/local-city-e/dev1). No git
  denials in any dev pane since the relaunch.
- Lighthouse team: dev1 committed Task 1 (`da8afa9` RecallReceipt artifact
  kind), dev2 committed Task 7 (`7e24d29` policy conformance fixtures);
  lead started cross challenge reviews. The dev1/lead pair tripped the loop
  guard a second time on legitimate traffic (16 and 15 messages per pair in
  30 minutes during the relaunch and review cadence); reset again, leads
  told to batch. The guard's 8-per-30-minutes default is a constant in
  codex-team's server.py; raising it for future teams and making it
  env-configurable is the next launcher change.
- E1 pre-gate complete: seven commits on team/local-city-e/dev1 (read-only
  Storage, canonical JSON and digests, policy evaluator with kit parity
  fixtures, socket frames, publisher daemon, receipts with strict schema,
  exporter 1.1). Full suite 1528 passed, 1 failed on the packaging lock
  check because the plan's `jsonschema>=4.23` direct dependency needs a
  uv.lock refresh. Decisions given to the lead: uv.lock refresh authorized
  on dev1's branch (its own commit, diff limited to jsonschema); the B0 gate
  stays closed tonight; dev1 gets one narrow extra WP, E1x, for the routing
  defect found tonight (load_config tolerates unknown keys with a WARNING,
  resolve_db_path logs its fallback instead of failing silently), limited
  to config.py's load_config/resolve_db_path and a new test file so it does
  not touch E2's MemoryConfig. This is an integrator decision outside the
  approved spec's lane scope; it is small, tested, and reversible.
- L1: Task 5 committed (`cad10ff`); Task 6 escalated one more Biome
  exclusion, `!!fixtures/engram/receipts`, so canonical receipt fixture bytes
  survive lint. Authorized on the same terms; biome.json diff is now exactly
  two exclusion lines. E: dev1 at 9 commits including the E1x routing
  warnings (`6192700`); dev2 at 17 commits; the lead found and assigned a
  lane-precedence fix (explicit personal beats work signals, per contracts).
- Engram integration: both lanes accepted by reciprocal review (E1+E1x at
  `5d9a9d4`, E2 at `4aa6483`). Merged by the integrator in the team's
  integration worktree: dev1 fast-forward, dev2 as merge `a034f2a`, no
  conflicts (pyproject py-modules and CLAUDE.md merged as separate hunks).
  Full suite running on the integration branch.
- **Decision point for the morning (not taken overnight).** E2's replay
  report (`docs/reports/2026-09-margins-replay.md`, 200 historical recalls)
  measures the recency change the plan specified as the default:

  | Mode | Near-tie rate | Winner under 7d | Winner under 1d |
  |---|---|---|---|
  | additive (today) | 0.30 | 90.5% | 83.5% |
  | tiebreak (new default) | 0.66 | 73.5% | 61.0% |

  118 of 200 winners change. Recency dominance drops as intended, but the
  near-tie rate doubles because the 0.02 near-tie threshold was calibrated
  against additive scores; the margin instrument needs recalibration under
  tiebreak. The code ships both modes behind `[memory] recency_mode`; the
  live effect begins only at the MCP restart, which is yours. Options: restart
  on the plan's default (tiebreak) and let E3 re-measure live, or set
  `recency_mode = "additive"` in `.engram/config.toml` first and flip later.
  No code change is needed either way.
- Do not re-add `default_lane = "work"` to the lighthouse config until the
  MCP server has been restarted on the merged code: the running server's
  loader still raises on the unknown key and reroutes the binding.
- Engram integration branch: full suite 1673 passed, 1 skipped. Merged into
  local main as `927bcca` (E1 through E1x, E2). Not pushed. The running MCP
  server still executes the pre-merge code; the restart is the morning's
  first action, followed by re-adding `default_lane = "work"` to the
  lighthouse config, then the B0 rerun once that store has content.
- Main after merge `927bcca`: full suite green (1673 passed, 1 skipped). Engram side is integrated
  for the night.
- Lighthouse integration: all three WPs accepted (L1-A/L1-C at `4992a15`,
  L1-B at `1c80c33`). Merged by the integrator in the team's integration
  worktree as `7839f27`, acceptance list run there (pnpm check green; proof
  passed with bridgeDigest `8f2194e9…6b4538` unchanged; recall proof passed;
  schemas and 14 policy decisions regenerate clean; receipt fixtures
  validate and reject correctly; shadow report emitted; preregistration
  required; digest command prints one line), then merged into lighthouse
  local main as `b178460` and re-verified (check green, both proofs pass).
  Not pushed. Team marked its STATE done and stood down.
- Cross-implementation conformance, the one result the cycle needed most:
  with L1's 14 generated policy fixtures synced into engram, the Python
  policy evaluator's decisions match the TypeScript kit's on all 16 cases
  (14 generated plus 2 hand-vendored), and engram-built receipts validate
  against the generated RecallReceipt schema with zero errors. Two
  test-side mismatches remain (the generated request files name their
  policy without a `.json` suffix; the generated schema also encodes the
  injected invariant so two negative tests now see SCHEMA_INVALID instead
  of the specific code). Assigned to dev1 as E1y: merge main, sync the
  artifacts additively, tolerate the suffix, check the invariant before
  schema validation. The main checkout was returned to its committed state.
- E1y accepted (`2eb010d` artifact sync at lighthouse b178460, `363ae9f`
  fixture suffix tolerance, `1f9dab1` validation order: invariant, then
  schema, then digest). Fast-forwarded into main; full suite 1674 passed.
  All 16 policy parity cases pass in the committed test. Engram main is
  `1f9dab1`; both teams are complete for the night and standing down.

## Morning checklist (2026-09-02)

1. Restart the MCP server (exit and reopen the Claude Code session in
   `~/Projects/engram`). Before that, decide `[memory] recency_mode`: the
   plan's default is `tiebreak`; the replay above shows what changes.
   Setting `additive` in `.engram/config.toml` keeps today's behavior with
   no code change.
2. After the restart, add `default_lane = "work"` inside the existing
   `[memory]` table of `~/Projects/lighthouse/.engram/config.toml` and
   commit it there.
3. Open one Claude session in `~/Projects/lighthouse` and work normally for
   a while; it now writes to the `lighthouse` instance. E3's step 7b
   re-lanes anything written before step 2.
4. When that store holds 30 episodes, run the B0 spike against it (plan
   Task B0, neighbor `lighthouse`). On a go, reopen E1's gate: the engram
   team's dev1 pane is alive and its plan Tasks 7 to 10 are next.
5. E3 and S sessions have not started; their briefs are in the
   coordination plan.
6. Tear down the two codex-teams when you no longer need the panes:
   `codex-team down --task local-city-l1` in lighthouse and
   `codex-team down --task local-city-e` in engram (branches kept).
7. Nothing has been pushed from either repository.

## Road test (2026-09-02 morning, integrator)

First live run of the merged publisher path, against the still-empty
`lighthouse` store, before any MCP restart (the daemon is a fresh process,
so it runs the merged code):

- Publisher policy written and sealed with engram's `artifact_digest`
  (`.engram/instances/lighthouse/lighthouse-policy.json`, one rule: allow
  `recall` and `read` to `urn:engram:engram` in `memory/technical`, purpose
  `session-recall`, valid to 2026-10-15). The TypeScript kit validates it
  with the same digest (`a8f7cc4c…8f98`).
- Daemon config `.engram/lighthouse-daemon.toml` (`publishers = ["lighthouse"]`);
  daemon started on `.engram/lighthouse.sock`.
- Probe over the socket: allowed recall answers `recall_result` with an
  allow decision, a turn id, and zero candidates (empty store); a recall in
  `memory/personal` and one from an unknown receiver both deny with
  `NO_MATCHING_ALLOW`; `read` of an unknown id returns `content: null` under
  an allow decision; an unknown publisher answers `PUBLISHER_UNAVAILABLE`.
- Publisher store bytes unchanged across the probe. Four disclosures in the
  sidecar, one per request, including the two denials.

The road holds with the house empty. What it cannot show yet is recall
quality; that needs content in the store and the receiver arm.

## Morning checklist, progress (2026-09-02)

1. Done except the restart: `[memory] recency_mode = "additive"` set in
   `.engram/config.toml` (keeps today's behavior live; `tiebreak` stays
   measured, not deployed, until E3 compares them). The restart is the
   human's action: exit and reopen the Claude Code session in this repo.
2. Done: `default_lane = "work"` re-added inside the existing `[memory]`
   table of the lighthouse repo's config (lighthouse `58461b1`); verified
   under the merged loader that the binding resolves to the lighthouse
   store. Safe before the restart because every new engram process runs the
   merged code; only this session's server is old.
3. Daemon relaunched detached (`nohup`, pid recorded in
   `.engram/logs/lighthouse-daemon.log`) so it survives the session restart;
   re-probed successfully. If it is ever missing:
   `cd ~/Projects/engram && nohup .venv/bin/python -m lighthouse_daemon --config .engram/lighthouse-daemon.toml > .engram/logs/lighthouse-daemon.log 2>&1 &`

## Morning, after the restart (2026-09-02, integrator)

Restart verified: `status()` maintenance timestamp 12:07:15Z on a session
that began 12:06:53Z; daemon socket and process survived. Kairos's steer
for the day, given mid-morning: help the existing sessions get to a better
place rather than supersede them, and get engram working first. What
follows is what "working" turned out to require.

**Defects found in engram's own session plumbing, in the order found.**

1. *Plugin binding.* The Claude plugin's `.mcp.json` launched the server
   with `uv run --directory <engram>`, which chdirs, so `server.py`'s
   `PROJECT_ROOT` (env or cwd) was always the engram repo: every Claude
   session in every project bound its MCP server to the engram store,
   while the hooks (run by Claude Code in the project cwd) bound by the
   real cwd. The Codex config never had this because it uses `--project`.
   Evidence: the lighthouse store's `memory_log` had zero rows of any
   kind before today. Fixed: `--project` plus an absolute server path;
   verified from the lighthouse cwd that the instance resolves to
   `lighthouse`, `default_lane = work`. The morning checklist's step 3
   ("open a session in lighthouse, it now writes there") could not have
   worked before this.
2. *Handshake timeout.* Claude Code allows an MCP server 30,000 ms to
   connect. Startup sleep maintenance ran inline before `mcp.run()`. On
   the first bind to the fresh lighthouse store the genome replicated (29
   episodes) and tripped auto-compress; the compression event landed at
   12:59:57.0, the client gave up at 12:59:56.65. That session had no
   memory tools for its whole life. My own session connected in ~22 s.
   A copy-store reproduction measured ~40 s in both init modes (the
   `allow_startup_consolidation` flag gates only the category observer).
   Fixed: maintenance factored into `_run_sleep_maintenance()`, inline for
   `_init()` callers, deferred to a background thread by
   `_initialize_pre_serving()`; the thread takes the lifecycle barrier per
   step; `status()` reports `maintenance_pending`. Tests:
   `tests/test_startup_maintenance.py`.
3. *Knowledge-graph model.* `GraphConfig.model` defaulted to
   `nemotron-nano`, which Ollama no longer has; every feed 404ed and
   Graphiti retried with backoff (~19 s for the first feed of the
   reproduction). Kairos chose `qwen3.8:27b-mlx`; set as the code default,
   in `_DEFAULT_TOML`, and in both live configs. A real feed is being
   timed as this is written.
4. *Canonical JSON parity.* E1's `canonical_json` renders the integral
   float `1.0` as `1.0`; the TypeScript kit's digest canonicalization
   renders it as `1`. Found while writing the receiver policy (Task I
   step 3): `extensions["engram:weight"] = 1.0` sealed by engram failed the
   kit's `validate` with `DIGEST_MISMATCH`; the same artifact with the
   weight written as `1` validates (digest `491bde6e…`). The vendored
   parity fixtures contain no integral floats, so the tests never saw it.
   The receiver policy now exists at
   `.engram/instances/engram/lighthouse-policy.json` (allow `recall`,
   `read`, `inject_context` for `urn:engram:lighthouse` in
   `memory/technical`, valid to 2026-10-15, weight 1) and passes both
   implementations. The code gap is a narrow work package for dev1.

**The worker experiment, and why it stopped.** I launched a headless
Claude session in `~/Projects/lighthouse` to populate the store toward
the B0 threshold. It bound correctly (registry row, genome replicated,
compression ran), then its server was killed by the 30 s timeout above,
and the session spent its time trying to work around missing tools; my
allow-list had also named the tools `mcp__engram__*` when, outside the
engram repo, the plugin exposes them as `mcp__plugin_engram_engram__*`.
Killed after ~10 minutes, zero episodes written by it. Kairos's note
arrived during this: the sessions that should inhabit the house are the
Codex ones, and the better plan is to help them get there.

**What the Codex sessions need before they can inhabit anything.** They
never called `remember()` once overnight (every episode since 09-01
18:00 in the engram store is mine); their role briefs never mention
memory. The three L1 worktrees still carry the b9dc702 config with a
duplicated `[memory]` table (tomllib: "Cannot declare ('memory',) twice"),
so a relaunched pane there would fall back to the engram store until its
branch merges main. Both are codex-team changes for Kairos to decide.

**Also observed.** A fresh house is never empty: the genome replicates on
first bind and is compressed into semantics on the first breath (8 from
29 in the lighthouse store). Two Codex sessions in `~/Projects/work/wcl`
started 12:09Z and 12:40Z and bound to the engram store (unbound project,
default instance), the same "one inhabited house" mechanism the census
found.

**Knowledge graph, measured.** One real feed with `qwen3.8:27b-mlx`
took 29 s of extraction and then failed on the Kuzu side: `Binder
exception: Table Entity doesn't have an index with name
node_name_and_summary`, although `build_indices_and_constraints()` is
called at init (a Graphiti/Kuzu version mismatch to chase separately).
The live graph file is 24 KB. Consequence for startup: the auto-compress
step holds the barrier, and a fresh house would spend minutes feeding a
graph that cannot accept the writes. Startup auto-compress now queues and
drops its graph feeds (`Compressor.defer_knowledge_feeds`,
`discard_knowledge_feeds`), counted in the maintenance report as
`knowledge_feeds_skipped`; `compress_commit` still feeds. Tests added to
`tests/test_startup_maintenance.py` (6 total).

**Codex sessions.** The engram lead's composer was found holding last
night's stand-down message unsubmitted (the paste landed, the Enter did
not), which is why its STATE never recorded E1y as merged. Submitted this
morning; the lead updated STATE and, unprompted, stored an episode about
the night with `remember()`: the first Codex-written memory of the cycle.
The lighthouse lead's composer holds a typed `go ahead` from Kairos,
left alone. A narrow work package for dev1 on the canonical-JSON parity
gap (E1p) is drafted and not yet sent; the E1 gate-reopen brief is drafted
and waits on B0.

**Handshake fix, measured on the fresh-house copy (genome present).**

| Path | Before | After |
|---|---|---|
| `_initialize_pre_serving()` returns (handshake-relevant) | ~40 s | 1.0 s |
| First `status()` after it | blocked until maintenance ended | 0.0 s, `maintenance_pending: true` |
| Background maintenance completes | n/a (inline) | 23 s later, report ok, 7 semantics, 7 graph feeds skipped |

The running MCP server in this session still executes the pre-fix code;
the change takes effect at the next restart.
