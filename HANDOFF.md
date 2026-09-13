# Resume here — medical lighthouse / aDNA

**Clinical/biotech tuning implementation, September 13 (current):** User approved
implementation and explicitly selected the HauhauCS uncensored Balanced variant.
`tuning/` supports identifiable clinical and confidential biotech data with
separate local/shared training and adapter-publication grants. Read
[tuning/README.md](tuning/README.md) and the
[baseline report](docs/reports/2026-09-13-clinical-tuning-baseline.md).
The selected 16.8 GB Q4_K_M artifact was downloaded and SHA-256 verified, then
imported into the existing local Ollama as
`superyak-clinical-gemma4-balanced:q4_k_m`. The import receipt binds the original
GGUF to Ollama's converted blob; all eight fictional domain cases produced
answers, six strict term checks passed, and no configured refusal was detected.
Two misses and clinical-validation limits are retained in the report.

Implementation worktree `.worktrees/clinical-tuning`, branch
`codex/clinical-tuning`, contains ignored model/import/baseline evidence in
`.engram/clinical-tuning-model/` and `.engram/clinical-tuning-baseline-20260913/`.
Real-tokenizer integration found a Transformers 5.17 loader mismatch with the
selected GGUF per-layer KV-head list. Resolve it before treating preparation as
runnable; local Ollama inference itself succeeded.
Private snapshots, exact model lineage, bounded loopback evaluations, real LoRA
training/checkpoints/resume, separate Linux CPU/XPU dependency locks, and a
non-submitting Slurm generator are implemented. CPU checks use a tiny actual
Gemma4 text model; no full-size materialization or Intel backward pass has run.
A first real dataset and Stampede3 SSH alias/allocation/reservation are still
needed; saved login/account fields were empty. Do not invent them or submit jobs.
This package does not yet expose peer training-consent APIs or distribute adapters.
The existing peer demo and its model are preserved; Atlas remains stopped.
Dated candidate-only statements and “no weights downloaded” below are superseded
by this update. Retain the worktree and evidence; use Git for integration status.

**Model-tuning research plan, September 13 (latest):** The
[Stampede3 LoRA plan](docs/reports/2026-09-13-stampede3-model-tuning-plan.md)
proposes official Gemma 4 12B Unified BF16 LoRA alongside a 26B-A4B BF16
attention-adapter lane, with 31B as a larger reference and E4B for smaller peers.
It includes 16 planned screening cells, exact official checkpoint metadata,
evaluation/data gates, source-training consent, and peer adapter distribution.
Whole-Stampede3 scope remains the planning premise, with Intel PVC as the
baseline. The user reports Gemma inference can run there; no retained Stampede3
training/backward/resume receipt has been established. Current PyTorch and
bitsandbytes document XPU support, but Gemma MoE expert quantization recipes
examined here require CUDA. This is a research/design artifact, not an executed
training campaign. No model weights were downloaded, model generated, remote
job submitted, or application/research/model/MCP service changed.

**Backend data-source management, September 13 (latest):** The peer now has an
account-owned source registry at `/api/data-sources`, with versioned names and
descriptions, pause/resume, item listings, and success/failure import receipts.
Sources register owned uploaded files or selected-source documents. Successful
request IDs replay their receipt; conflicting input fails, and failed batches
roll back content. CSV/JSON files preserve exact bytes. Pausing a source affects
new imports, not existing data or sharing permissions. These are backend APIs;
the dashboard keeps its existing selected-record import/export interface.
See [the API examples](peer/API.md#backend-data-sources) and
[implementation plan](docs/superpowers/plans/2026-09-13-data-source-management.md).

The existing password-free demo at **http://127.0.0.1:7435** serves the installed
package in `.worktrees/peer-home/.engram/data-sources-20260913/`, PID `44387` at
verification. Its `runtime.json` holds the exact launch command and unchanged
hashes of all 22 existing content tables and credentials; `verification.json`
records a fresh browser/API check. The new source tables are additive, and legacy
imports are cataloged without altering records or inventing old import dates.
The standalone source archive `superyak-peer-data-sources.tar.gz` has SHA-256
`9cfe6159ebf35a6b8d5db785b7a328142df25eb4de07346bc06e1d124f5afdaf`.

All 162 peer tests passed, including browser/package checks and CSV/JSON attachment
transfer/withdrawal between two test peers. Independent review approved without
findings and exercised additional synthetic API/integrity cases. The ignored
`integration.json` in that evidence directory records the final pushed commit
and CI result when integration finishes. Preserve the original demo state and
all prior evidence. Only the peer demo was reloaded; no external source fetch,
model generation, research-worker restart, or MCP-server restart occurred.

**Password-free local demo, September 13 (latest):** `make home-demo` now uses
`serve --local-demo`: fresh visits open the patient home, the account menu switches
between the four seeded dashboards, and expired demo sessions renew without a
password. An optional password form remains available for invited accounts.
Ordinary serving still requires authentication. The option requires validated
seeded state and loopback binding/origins/connections.

The retained demo at **http://127.0.0.1:7435** now runs installed source from
`.worktrees/peer-home/.engram/local-demo-20260913/`, PID `30323` at verification.
Its `runtime.json` records the exact command and preserved content/credential
hashes; `verification.json` records fresh browser entry and account switching.
Saved content and credential hashes were unchanged through the restart. Source
archive `superyak-peer-local-demo.tar.gz` has SHA-256
`2e1cd44b6bb462835f6a7bd2f3b4207fbd89c6d0a7fe43f1fa3cc52730c034fb`.
Review approved after fixing invitation sign-in; 58 auth/CLI/browser checks passed
before that final disclosure fix, then all three affected browser cases passed.
Preserve the runtime, original `.engram/home-demo`, and older review evidence.
Only the peer demo was reloaded; no research or model service was restarted.

The user also relayed Stanley's recommendation of
[HauhauCS Gemma4-26B-A4B Balanced](https://huggingface.co/HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced).
Its card identifies Google's Gemma 4 as the base and community modifications;
the maintainer's U.S. provenance is unverified. This is a candidate, not an
installed or measured replacement. The demo still uses the existing pinned
`gemma4:31b`; ask/read current user steering before treating the variant as chosen.

**Peer home reviewed and integrated, September 12 (latest):** The reviewed
implementation through `7222037a32b3b2fbbbe2823cff549127c15b4c66` is merged into local
`main`. All required final findings are addressed. The existing user demo now
serves the reviewed candidate-9 wheel at **http://127.0.0.1:7435**; a fresh Chromium
login and exact served-JavaScript check passed. Its original state and credentials
remain in `.worktrees/peer-home/.engram/home-demo/`; no demo reset or content edit
occurred. Refresh an already-open page to load the final interface.

The standalone Apache-2.0 source is the candidate-9 archive described below.
The parent repository remains private, and its imported history is not relicensed
or included in that archive. Actual Mac/Pi acceptance passed ten checks for the
same Python backend/checker; candidate 9's subsequent browser presentation change
passed all 27 browser tests and fresh package checks. One nonblocking follow-up
remains: received-room reply summary cards need origin-aware matching; per-message
status and Connections check/retry work. Inherited dependency warnings remain.

Atlas/MG research is stopped, with supervision disabled; no model generation was
repeated. Keep the worktree, all verification evidence and user-entered demo data.
The local [integration receipt](.worktrees/peer-home/.superpowers/sdd/2026-09-12-peer-home/integration-result.json)
records the final remote commit and CI outcome as synchronization finishes;
`git status --short --branch` and `gh run list` provide current remote status.
The [verification report](docs/reports/2026-09-12-peer-home-verification.md) records
measured behavior, exact artifact hashes and remaining limits.

**Final peer-home review fixes, September 12 (current source pointer):**
`codex/peer-home` now includes ordinary participant space creation, authoritative
saved-version file/member previews with membership-conflict protection, truthful
local/remote withdrawal status, and delivery refresh preserving unsaved work.
Native modal focus, mobile metrics, isolated screenshot paths, and public network
error wording are repaired. Covering checks: 74 passed (27 Chromium workflows),
plus three package tests; inherited warnings remain.

Current archive in the worktree's ignored `.superpowers/sdd/2026-09-12-peer-home/`:
`superyak-peer-candidate-9.tar.gz`, SHA-256
`6f693dbe751f98a19d1a81b3be1cc678fb9ad90cd6cd72b98a02a8f4ec466c4a`.
`release-inspection-9.json` confirms the exact 45-file source manifest, real
sdist/direct-wheel private-state exclusions and fresh installed startup.
`final-fix-manifest-audit-9.json` records the five changed runtime/static files
from candidate 4. Only browser presentation and its tests changed from measured
candidate 8; all Python backend/checker bytes remain identical. Final browser
verification passed 27 cases, with technical IDs/hashes behind optional details.
The controller's fresh exact
candidate 8 Mac/Pi check passed all ten checks in 7.311 seconds, with both cleanup
records stopped; read `final-two-host-reviewed/result.json`. Original candidate 4
measurement and all model evidence remain intact. `final-fix-report.md` records
fixes, RED/GREEN commands, visual checks and limits. See the
[public-safe verification report](docs/reports/2026-09-12-peer-home-verification.md).
The controller owns final integration/CI and the user demo's runtime reload;
preserve the existing `.engram/home-demo` state and credentials.

**Personal peer home implemented, September 12 (historical Task 5 snapshot):** The first
standalone participant application is implemented in `peer/`; use
[its guide](peer/README.md) and the [verification report](docs/reports/2026-09-12-peer-home-verification.md).
Authenticated homes, private drafts/rooms, active sharing layers, paired signed
HTTPS transport, and selected-source/aDNA interchange now exist. The richer
clinical/HPC/help design remains future scope. The same allowlisted source passed
a real Mac/Pi check with independent identities/stores, bidirectional chat,
selected share/correction/withdrawal, invalid-peer denial, offline editing and
restart/retry recovery. Only temporary synthetic services/tunnels were started;
all are stopped after verification. Earlier dated “not implemented” statements
below are historical snapshots.

The isolated local demo is running at **http://127.0.0.1:7435** from
`/Users/kairos/Projects/superyak/.worktrees/peer-home`. Its private credentials are
`.engram/home-demo/demo-credentials.json` within that worktree; do not print or
replace them. It was launched with `make home-demo` and an explicit private model
configuration in `.superpowers/sdd/2026-09-12-peer-home/demo-model.json`.
Browser login/readiness and read-only Gemma identity status passed. Preserve any
new user work in this state. If it has stopped, inspect the saved launch command
in `demo-launch.json` before starting it; do not restart other services.

Task evidence and report remain in that worktree's ignored
`.superpowers/sdd/2026-09-12-peer-home/` directory. `final-two-host-4/result.json`
records the passing final source run, receipt IDs/hashes and cleanup;
`release-inspection-7.json` records the revised source/sdist/direct-wheel exclusion
and startup checks. The Task 5 source archive was `superyak-peer-candidate-7.tar.gz`,
SHA-256 `734cf0f80ac00d6bdbb6363dd24fce65caf6d91eb4ee2adbae79b2611076b677`.
Review found that standard `uv build` on candidate 4 could include private state,
even though its custom archive itself was safe. The revised package shares explicit
source inventory, adds wheel inventory, and clears Hatch's implicit source additions.
Candidate 7 runtime/static/checker bytes remain identical to measured candidate 4;
`task-5-fix1-manifest-audit.json` proves that equality. The unchanged two-host test
was not repeated; all three focused packaging tests and exact candidate 7 package
inspection passed. Previous artifacts and evidence remain preserved.
The checker uses generic configurable SSH/host/path inputs; personal operational
details stay in ignored evidence. Newly authored `peer/` code is Apache-2.0;
imported history retains its licenses and the parent repository remains private.
The exact artifact is ready for review, not publicly published by Task 5.

The prior Task 4 Gemma evidence remains the only measured generation: HTTP 200,
22.562 seconds, one explicit fictional request, unchanged draft and no publication.
Task 5 performed no further generation. The demo's opt-in guard is component-scoped;
Atlas/MG research remains stopped with supervision disabled. No migration or
universal eligibility/capacity claim follows. Controller owns final review,
integration/push and remote CI after Task 5; see `task-5-report.md` for the exact
verified commit and check results when resuming.

**Open-source and peer-to-peer reaffirmed, September 12:** Kairos asked for current progress and reaffirmed that the system must be **open-source and peer-to-peer**. Treat this as an architectural requirement for the personal home, private chats, and sharing layers: independently hosted peers, locally governed data/access, explicitly shared publications, and no mandatory central application owner. The [design](docs/superpowers/specs/2026-09-12-personal-dashboards-sharing-design.md) now makes the next measurable milestone a private message and a selected share/correction/withdrawal between two machines with separate stores. Existing memory/research/aDNA components are implemented; the new dashboard and authenticated cross-machine participant application are not. GitHub was rechecked private with no root license. Public release requires a license decision and review of source/history because tracked handoffs include private operational context; no visibility or license change was made. The recent design/model-policy edits remain local and uncommitted after the earlier push at `407c39c`. MG research remains stopped pending Gemma validation; no MCP or model service was restarted.

**Dashboard entry point confirmed, September 12:** Kairos selected **a personal home across chats, care circles, projects, and organizations** as the first dashboard's main entry point. The Wilhelm Foundation hackathon hub is one accessible organization/project space. This resolves the navigation preference in the [dashboard design](docs/superpowers/specs/2026-09-12-personal-dashboards-sharing-design.md); it does not by itself approve every other proposed behavior or authorize deployment.

**Sharing layers and American models only, September 12:** Kairos clarified that people should be able to spend time constructing their sharing layers and public presence, save private drafts across sessions, preview each audience, and activate selected versions when ready. The [dashboard proposal](docs/superpowers/specs/2026-09-12-personal-dashboards-sharing-design.md) now includes this dedicated workspace. Kairos also requires **American models only**, with **Gemma 4** preferred; this supersedes all earlier Qwen/Kimi/GLM preferences and DeepSeek alternatives below. Read the [current model requirement](docs/model-policy.md). The whole-Stampede3 premise remains; earlier model-specific replica counts do not transfer to Gemma. `gemma4:31b` is listed locally, but workflow compatibility is not yet verified. The MG Qwen worker was cooperatively stopped: final observation `running=false`, `last_phase=stopped`, prior PID 73977, supervision disabled. Status snapshots are in `.engram/atlas/operations/american-models-20260912/`. The project and historical model attribution are preserved; no replacement worker was started. Existing CLI defaults have not become a universal eligibility guard.

**Organization correction and dashboard direction, September 12:** Kairos clarified that this is a **Wilhelm Foundation hackathon**; the earlier Research to the People attribution was a mix-up. Treat Wilhelm Foundation as the current hackathon context without inferring Stanley's affiliation or changing any permissions. People mixing up names and organizations is an expected product case: preserve original accounts, accept attributed corrections, update dependent context, and keep identity and sharing changes separate. Kairos requested personal dashboards for patients, doctors, family and others, private chats, and simple sharing/public controls across organizational levels. The [proposed dashboard and sharing design](docs/superpowers/specs/2026-09-12-personal-dashboards-sharing-design.md) develops that request; its detailed defaults are proposals, not deployed behavior. Existing services and private archives are unchanged.

**Repository synchronization requested, September 12:** Kairos requested all project work merged and pushed. All existing development branch commits were verified as ancestors of local `main`; this publication also preserves the outstanding laptop/MG handoff updates and the [historical Stampede worker notes](.superpowers/stampede/README.md). Private `.engram/` archives and historical worktrees remain local and preserved. Earlier "nothing has been pushed" statements below describe their original snapshots; inspect the Git remote for the current synchronization state. No running research or MCP service was restarted by this synchronization.

**Original conversation preserved, September 12:** At Kairos's request, the original September 11 evening and overnight conversation is now archived locally as [115 verbatim user/assistant messages](.engram/conversations/2026-09-11-superyak/conversation-overnight.md), alongside the [continuing thread through September 12](.engram/conversations/2026-09-11-superyak/conversation-through-september-12.md). The [archive index](.engram/conversations/2026-09-11-superyak/README.md) links exact JSONL messages, original timestamps/source locators, checksums, and copies of both letters written that evening. A [portable ZIP](.engram/conversations/2026-09-11-superyak.zip) is also saved. These are original recorded messages, distinct from later narrative summaries. Read the conversation itself when revisiting its meaning; do not substitute the handoff's interpretation. The private archive is under Git-ignored `.engram/` and has not been published.

**Laptop handoff — September 12:** Kairos is returning to the laptop. Read [.engram/handoffs/2026-09-12/LAPTOP-RESUME.md](.engram/handoffs/2026-09-12/LAPTOP-RESUME.md) first for the latest session state and a pasteable resume prompt. Local `main` is at `a247675`. The MG worker was rechecked running as PID73977, with 31 cycles since reload; phase `waiting`. The latest last-error field is preserved in the snapshot; these are dated observations. Full status is saved beside the guide in `LAPTOP-STATUS.json`. Preserve the existing worker and uncommitted notes. Acknowledge the handoff and wait for Kairos's next instruction; this handoff does not request new jobs or service restarts. Older phone/tmux restart entries below are historical.

**Latest preparation — portable MG tasks, September 12:** Kairos authorized the next Stampede preparation slice. Local `main` now includes `d39ea19`: bounded independent paper/model HTTP lanes and absolute deadlines; explicit one-question/cached-paper task export; native Ollama and chat-completions providers; immutable request/reply checkpoints and isolated Atlas capture. Read [usage](docs/portable-research-tasks.md) and [verification](docs/reports/2026-09-12-portable-mg-verification.md). Tests: Engram 2,495 passed/two expected skips; Atlas 694; portable tasks 83; Atlas/TypeScript parity passed. One real native Qwen extraction/review produced a proposed isolated finding; offline and extracted-source replay made zero network calls and preserved all artifacts. The same packet through `/v1` timed out at 120 seconds; failure preserved, no retry. The endpoint was shared, so these timings are not a throughput comparison. MG's live worker was cooperatively stopped after 22 cycles and restarted with the fix, same model/options and stable identity/rotation; observed new PID 73977. Recheck current status. All preexisting state matched before reload and 38 immutable journal/turn files were verified afterward. The existing live project continues. Source/task artifacts remain in `.worktrees/mg-portable/.engram/mg-portable/`; preserve that worktree and all historical POC artifacts. No push or unrelated service restart occurred. Whole-Stampede3 capacity/K3/GLM hosting remain unmeasured; this runner has one fresh extraction/review turn, not yet the multi-researcher memory architecture. Detailed continuation: [.engram/handoffs/2026-09-12/MG-PORTABLE.md](.engram/handoffs/2026-09-12/MG-PORTABLE.md).

**Newest operation — MG research running, September 12:** Kairos asked to clear the active setup for myasthenia gravis and start local Qwen. The previous cell-fate pilot was archived under `.engram/atlas/archive/` with all 45 file hashes preserved. The default `.engram/atlas/project` is now MG, seeded with four proposed journaled questions: mechanisms/heterogeneity, therapeutic evidence, outcomes/biomarkers, and complex disease/comorbidity. A detached Atlas worker was started using `qwen3.8:27b-mlx`, default five-role rotation, batch size 3 and interval 60 seconds. Initial observed PID 66989; inspect current status rather than assuming this dated PID is live. The first Europe PMC search succeeded; a first paper job was recorded after Qwen extraction and a supported automated source check. Its finding remains proposed; Atlas publications and research views were current. The worker continued to the next paper. Startup verification is in `.engram/atlas/operations/mg-start-verification.json`. Use `make atlas ATLAS_ARGS='research-status --once'`, `make atlas ATLAS_ARGS='open'`, or `make atlas ATLAS_ARGS='stop'`. Read [.engram/atlas/project/README.md](.engram/atlas/project/README.md) and [.engram/atlas/operations/mg-setup.json](.engram/atlas/operations/mg-setup.json). No participant details supplied; model outputs remain proposed and source checked. No unrelated process, model service, or standalone Atlas installation was restarted. No new OS supervision or peer grants were installed. `make atlas-demo` now needs a different `ATLAS_PROJECT` because the default is MG. This supersedes the earlier no-jobs instruction for this explicitly requested local MG worker only.

**Latest continuation — Atlas monorepo, September 12:** Kairos requested Atlas here for the open-source hackathon and an integration/execution plan. Local `main` now includes `adc686f`: audited current Atlas workbench under `atlas/`, its own lock/environment, root offline demo/CLI/setup/check/CI, bundled POC default, and Atlas/POC source in allowlisted staging. Read [the integration plan](docs/atlas-integration.md) and [verification](docs/reports/2026-09-12-atlas-monorepo-verification.md). `make atlas-demo` has been run in this checkout; open `.engram/atlas/project/Research/index.html`. Full migration checks: Atlas 675 passed; Engram 2,495 passed and two expected skips; Lighthouse 139 tests and both proofs; Atlas/TypeScript publication parity passed. Source and historical runs remain preserved. The changed POC CLI fingerprint requires a new output directory for current code; old runs use their pinned implementation. Next bounded work is one fixed evidence/provider/memory turn, with private histories, an explicit share, and restart/correction checks; provider/aDNA/HPC lanes can proceed in parallel. The agreed four K3/four GLM identities and whole-Stampede3 premise stand. Actual K3/GLM hosting remains unmeasured. License choice is pending. No live research jobs, model calls, cluster deployment, service restarts, or push occurred. This entry preserves the previous uncommitted restart handoff below. Detailed local continuation: [.engram/handoffs/2026-09-12/ATLAS-MONOREPO.md](.engram/handoffs/2026-09-12/ATLAS-MONOREPO.md).

Updated 2026-09-12. Kairos is moving to a phone/tmux session and asked for this handoff. This is continuity context, not authorization to start an unrelated deployment. Follow the newest user instruction.

**Restart here, latest September 12 handoff:** Kairos is returning to the phone/tmux session and restarting it. Read the [restart guide](.engram/handoffs/2026-09-12/TMUX-RESTART.md) for the current state, next bounded work, and exact artifact paths. Implementation and reports are merged into local `main` through `14eaf74`; nothing has been pushed. The new restart notes are a local documentation update. Older dated entries below are history, especially their proposed model counts, four-node capacity assumptions, and live-service observations.

## Latest direction — Stampede3 memory research

**Latest implementation continuation, September 12:** Kairos asked to merge and continue. The earlier source branches were already included in local `main`; commit `b0accae` integrates the outstanding research reports, plans, and handoff. The bounded follow-up adds `make lead-probe`, opt-in K3/GLM text protocols preserving complete assistant state, and a two-turn fictional observation/correction probe against an existing loopback endpoint. Read [usage](docs/lead-model-probes.md) and [verification / actual observations](docs/reports/2026-09-12-lead-probe-verification.md). Full Python regression from the required `engram` working directory: 2,491 passed, two expected skips, five existing warnings; independent review and 66 focused tests passed. Lighthouse and interoperability checks passed before this Python-only continuation. The new source bundle was extracted and its probe entry point checked without the local editable install. Source/archive artifacts are under `.engram/lead-probes/`. Actual local Qwen control made two completed calls but both failed strict JSON checks: otherwise expected counts/source versions had malformed prefixes. A one-call comparison omitting only forced JSON mode returned valid JSON. Preserve the failed outputs; this suggests a local serving-path issue and is not a demonstrated two-turn repair. Neither K3 nor GLM was actually hosted; their tests used scripted HTTP fixtures. No models were downloaded, no live service was changed, no cluster job was submitted, and nothing was pushed. The agreed eight identities and whole-machine scope remain in force; native tool execution, vision, GPU placement, and replica capacity are still unmeasured/unimplemented by this bounded probe.

**Agreed starting lead group, September 12:** Kairos suggested “maybe k3 and glm5.3 for several leaders.” The preferred lead pairing is now Kimi K3 plus GLM-5.3. Kairos subsequently replied “sounds good” to the proposal of four persistent identities of each, eight total, with separate histories and four paired starting responsibilities: research direction, evidence synthesis, methods scrutiny, and case applicability / participant priorities. Treat this eight-agent starting group as agreed. The wider Qwen population and physical model-replica counts remain proposals pending measurement. This supersedes the earlier 24-leader proposal and GLM-first / three-family recommendation below. DeepSeek V4.1 Flash remains an alternative; Nemotron remains a comparison. Eight identities does not mean eight loaded model replicas. H100 compatibility, simultaneous placement, and useful request rates remain unmeasured, especially for K3's GB300-oriented recipe. Read the updated [whole-cluster plan](docs/reports/2026-09-12-stampede3-whole-cluster-plan.md) and [model review](docs/reports/2026-09-12-open-model-lead-selection.md). Whole-machine scope and the Qwen27B worker preference remain in force. Documentation only; no models, code, jobs, or running services changed.

**Newest model correction, September 12:** Kairos challenged Nemotron 3 Ultra's standing against weekly new open releases. Read the [current model review](docs/reports/2026-09-12-open-model-lead-selection.md). Same-version Artificial Analysis v4.3 pages/leaderboard show rounded GLM-5.3 max 45, Kimi K3 max 44, DeepSeek V4.1 Flash max 40, DeepSeek V4 Pro 0813 max 36, Qwen3.8-27B xhigh 34, and Nemotron 3 Ultra reasoning 23. These are generic served-model evaluations, not biomedical or Stampede measurements; June Nemotron's 47.7 used an older index and must not be mixed in. The recommendation is GLM-5.3 as first lead candidate, with Kimi K3 and DeepSeek V4.1 Flash in parallel comparison. DeepSeek's latest official repo was created September 10; its internal Engram is unrelated to this project's Engram. Preserve the user's Qwen27B worker preference. The whole-cluster proposal now treats the 96 H100s as a model-dependent comparison pool; twelve Nemotron services are only a retained hardware-fit scenario, no longer the recommended allocation. GLM/Kimi/large-Qwen custom licenses differ from DeepSeek MIT; large-Qwen hosted Max benchmark scores do not automatically describe the open checkpoint. H100 backend/precision/multi-node support must be measured for the selected candidates. No downloads, inference calls, or application changes occurred. Local primary-source snapshots are in `.engram/research/2026-09-12-model-selection/`. Whole-machine scope is still accepted; do not reopen the earlier allocation question.

**Newest user clarification, September 12 — THE WHOLE STAMPEDE3:** Kairos explicitly confirmed the entire machine, correcting the repeated four-node/shared-allocation assumption. Accept the whole-cluster reservation as the planning premise; do not ask again whether access is only a normal shared allocation. Read the [whole-cluster capacity proposal](docs/reports/2026-09-12-stampede3-whole-cluster-plan.md). The new proposed layout is 1,792 Qwen3.8-27B replicas (560 SPR + 960 SKX + 192 ICX + 80 PVC GPU placements), supporting an initial design population of 10,000 persistent researchers, plus 24 lead identities sharing 12 Nemotron 3 Ultra NVFP4 services across 96 H100s. NVIDIA documents an eight-H100 NVFP4 minimum; BF16's sixteen-H100 minimum permits six services instead. Remaining 132 ordinary CPU nodes and three large-memory nodes support research tools, retrieval, memory, and coordination. These are design choices and hardware-count arithmetic, not a measured capacity or user-selected population/model. No model calls or deployment occurred. The actual reservation launch details and runtime compatibility remain execution work, without reopening the user-confirmed whole-machine scope. Earlier 128+4 suggestions and the four-node capacity baseline are superseded. The current launcher still implements only the bounded pilot and has not been enlarged.

**Latest capacity correction, September 12:** Kairos pointed out that Stampede3 has about 330 TB of RAM. The earlier 128-worker/four-lead example was anchored to a four-PVC-node pilot and must not be treated as a whole-cluster estimate or the user's intended scope. TACC's [system overview](https://tacc.utexas.edu/systems/stampede3/) advertises over 330 TB. The current [operational guide](https://docs.tacc.utexas.edu/hpc/stampede3/) lists 560 SPR nodes × 128 GB HBM, 1,060 SKX nodes × 192 GB DDR4, and 224 ICX nodes × 256 GB DDR4: 1,844 main CPU nodes and 332,544 nominal GB, before other node classes. CPU inference belongs in capacity planning; the SPR HBM pool is particularly worth benchmarking. A 27-billion-parameter model has approximately 54 GB of BF16 weights or 13.5 GB of raw four-bit weights before metadata, runtime, and sequence state. One replica per main CPU node is a memory-plausible whole-machine illustration, not a measured deployment or available allocation. Ordinary per-job limits include 256 SKX nodes, 32 SPR nodes, and 32 ICX nodes; these differ from the four-node PVC limit. Dedicated hackathon reservation size, granted partitions/SUs, actual backend support, and useful throughput remain unknown. No cluster access, implementation change, or new chosen population follows from this correction.

**Newest completed research, September 12 — global biomedical organization:** Kairos asked for deep research before choosing the mathematical organization of research data, and selected balanced coverage of the global landscape and system design. Read the [full report](docs/reports/2026-09-12-global-biomedical-research-organization.md), [browser version](docs/reports/2026-09-12-global-biomedical-research-organization.html), or [14-page PDF](docs/reports/2026-09-12-global-biomedical-research-organization.pdf). A [CSV source catalog](docs/reports/2026-09-12-global-biomedical-research-organization-sources.csv) and equivalent JSON accompany 49 numbered source entries. The report covers institutions and patient-led research, geographically distributed infrastructure, clinical/biological/study standards, disagreement, provenance, federation, and an illustrative MG/complex-case workflow. Its proposed foundation is typed observations, studies, qualified assertions, models, questions, decisions, and memories with explicit partial mappings and versioned dependencies. A graph is one view alongside timelines, tables, narratives, and executable models. Preserve source identity and uncertainty; distinguish study evidence from repeated reports and agent recollection. These are recommendations, not an approved or implemented schema. The article-extraction POC remains a successful bounded mechanism test, not a failed attempt at the full research architecture. Existing services and application code were not changed. HTML citation/local-link checks, PDF text checks, and visual rendering inspection completed; no model calls or cluster jobs were launched. Local retrieval evidence and the renderer are under `.engram/research/2026-09-12-biomedical-landscape/`. Public/synthetic research remains possible without patient identity or private Stanley plans.

During that research Kairos also asked for a concrete 27B/lead count. A **provisional example**, not a measured ceiling or accepted configuration, was 128 persistent Qwen3.8-27B researchers sharing up to 12 replicas across three four-GPU PVC nodes, with four lead identities sharing a larger model across the fourth node. Nemotron 3 Ultra was identified as a local candidate to test; Intel-compatible quantization, runtime support, and comparative quality remain unverified. Claude Opus 5 was mentioned as an optional paid API alternative, not launched or selected. Do not confuse persistent identities with replicas or concurrent requests. The current launcher does not implement that layout and its defaults remain as described below.

**Latest model preference, September 12:** Kairos favors the 27B Qwen model as the main research-worker model, with perhaps a few more capable models leading. The user wrote “qwen 2.8 27b”; the working interpretation is **Qwen3.8-27B**, matching the local pilot's `qwen3.8:27b-mlx` (the local model listing reports NVFP4). Preserve the preference while keeping that spelling interpretation explicit. No leading model, population split, or Intel precision has been selected or benchmarked. The Stampede launcher still defaults to `Qwen/Qwen3-8B`; its code and prepared archive have not been switched to 27B. The existing population/concurrency settings are scheduling bounds, not measured 27B capacity. Kairos also clarified that the narrow article-extraction task was a proof of concept for the base structure, not the intended mathematical organization of research data; that organization remains an open design discussion.

**Newest completed work — local real-research POC:** Kairos authorized “put together and test a poc.” Local main commit `3d44f2f` adds `research_poc/` and `make research-poc`, independent of Stampede/Intel. Read [POC instructions](docs/atlas-research-poc.md), [verification](docs/superpowers/reviews/2026-09-12-atlas-poc-verification.md), and [review](docs/superpowers/reviews/2026-09-12-atlas-poc-review.md). It uses a frozen public snapshot of the current Atlas workbench, two genuine Europe PMC papers, local `qwen3.8:27b-mlx`, and real Engram individual stores and explicit audience-bound sharing. Four crossed memory conditions plus a separate community, two logical researchers each, completed 20 research turns / 40 real model calls in 567.70 seconds. All expected memories were admitted; 12 explicit shared findings have current proposed Atlas publications and browser/Obsidian exports. Completed replay made zero new model calls and preserved all 152 audited call/turn/draft file hashes. Full Engram regression: 2,472 passed/two optional skips; final focused POC tests: 31 passed. Existing dirty work was preserved, and no code was pushed.

The complete development artifacts remain at `.worktrees/atlas-research-poc/.engram/research-poc/live-01/`; use `make research-poc RESEARCH_POC_ARGS='status --output .worktrees/atlas-research-poc/.engram/research-poc/live-01'` from main to inspect them. Default `make research-poc` prepares and runs a fresh pinned experiment. The first live run began during development before implementation pinning; its separate provenance record says that explicitly. Future runs pin code before calls. Actual source passages varied with memory's use of the context budget; source review used the same model. This proves observed routing, recording and recovery mechanisms, not memory benefit, independent scientific validity, or cluster capacity. A next efficacy round should hold source passages fixed and broaden tasks/independent evaluation.

The slow active-Atlas context lookup was profiled read-only: >20 seconds, only 0.062 seconds in file reads, with repeated canonicalization/verification dominating. An isolated pilot took 0.008 seconds; temporary process-only verification deduplication completed the live lookup in 3.98 seconds. The active Atlas checkout/journal/service was not changed. A small targeted Atlas validation fix is a separate follow-up; this problem is already reproducible without Intel.

**Latest steering after launch preparation:** Kairos questioned full readiness and chose to separate research-architecture testing from Intel/Stampede3 troubleshooting. Iterate locally using Atlas Research, doing useful public-source research alongside memory/scale comparisons; investigate the Intel side when access exists. Read [research rounds](docs/stampede3-research-rounds.md). Atlas's current workbench has source/evidence capture, dynamic context, and Obsidian/browser exports (`d856fb6` is present locally), but it is not integrated with the Stampede launcher or independent Engram-backed agents. On this read-only inspection Atlas reported stopped; a context CLI lookup exceeded 15 seconds. Do not treat that timeout as absence of evidence or report a running research service. No worker was restarted, biological record saved, or remote job submitted. Atlas's substantial ongoing uncommitted work was preserved.

Later on September 12, Kairos asked for deep research on a Superyak research community on Stampede3, clarified **individual and shared memory**, and emphasized that the architecture itself may be original research. The completed [research proposal](docs/reports/2026-09-12-stampede3-research-community.md) and [capacity workbook](docs/reports/2026-09-12-stampede3-capacity.xlsx) cover prior work, Intel inference, memory ownership, organization, controlled comparisons, continuing community observation, and a proposed allocation week. The report is a design artifact; no cluster deployment or inference measurement was performed.

TACC's operational guide documents Intel PVC nodes with four Max 1550 GPUs each, alongside H100 nodes. Use **PVC as the planning baseline**. Actual allocation dates, account, available SU, and host software remain unknown. Kairos rejected a serial population ladder: use parallel cross-comparisons to troubleshoot under limited time. The revised proposal crosses four memory conditions × populations 32/128 × request caps 4/16 (16 cells), adds four serial references, and keeps a continuing community separate. Eight-member controls and 256-member probes are early diagnostics, not mandatory promotion steps. These are experimental settings, not measured capacity.

**Newest task completed locally:** Kairos wanted one-command deployment preparation before access arrives, potentially days before patient or participant details. Do not ask about those details or introduce academic-bureaucracy prerequisites. Commit `e417885` on local `main` implements the Stampede3 launcher, Intel profiles, synthetic memory comparisons, continuing community, and consistent checkpoint export/resume. Read [deployment instructions](docs/stampede3-deployment.md) and [verification](docs/superpowers/reviews/2026-09-12-stampede-verification.md). The local config is `.engram/stampede/config.json`; only `login` and `account` remain empty until access arrives. Then use `make stampede-deploy` or double-click `scripts/Start Stampede3.command`. `make stampede-plan` is offline. `make stampede-simulate` completed 20 cells/156 scripted calls in the main checkout, and its repeat made zero new calls. Full Python verification passed 2,442 tests (two expected live-config skips); Lighthouse and interoperability checks passed. Independent review resolved all established important findings. No live cluster submission, Intel inference, or push occurred. The initial data mode is synthetic only; public aDNA ingestion and open-ended research are future additions. A prepared allowlisted source archive is `.engram/stampede/prepared-source.tar.gz`. The implementation worktree/branch remains available with local worker notes; preserve root untracked reports and this handoff.

Closer precedents include DecentMem (May 2026) and an August 18 preprint describing six persistent scientific agents across nearly six months. Treat these as related, early evidence, not proof the proposed system works or that its full design is unprecedented. The local-model provider and bounded lifecycle/recovery scheduler are now implemented for the synthetic bootstrap. Live cross-node Lighthouse transport, adaptive research tasks, and full scientific evaluation remain follow-up work. Existing Unix-socket sharing is local; SQLite WAL should not be opened across nodes on shared storage.

The earlier request to leave Stanley a **plan/documentation request** remains paused and unsent. Kairos shifted first to memories of Superyak and last night's conversation, then to this research. A shared document path or export would satisfy the original request; broad workstation access is unnecessary. Do not claim delivery. If that task resumes, inspect the Pi's coordination naming override before creating a note, and distinguish a local note from a message Stanley has received.

## SSH works now

The earlier SSH blocker is **resolved**. Verified an authenticated login from this Mac:

```sh
ssh -o IdentitiesOnly=yes -i ~/.ssh/personal andy@smart.local
```

LAN fallback: `andy@192.168.50.111`. Login is **andy**, not smart or kairos. The private key remains on this Mac. Kairos had the existing Claude Code session on the Pi add its public key. This session verified access and saved the matching Pi host key in `~/.ssh/known_hosts` for both hostname and LAN address.

Pi ED25519 host fingerprint:

```text
SHA256:VJq5KSapTy7U0Bb+Snzz1N9j51cJWUgY6io+0kA0Xt4
```

## Read these next

1. [Fuller conversation and technical handoff](.engram/handoffs/2026-09-12/CONTEXT.md). It preserves the philosophical motivation, user decisions, implementation history, live Pi observations, and remaining work. This local file is under ignored `.engram/`.
2. [Medical lighthouse pilot plan](docs/medical-lighthouse-pilot-plan.md). This is a proposal, updated with the user's answers and new Pi evidence; it is not an executable deployment specification.
3. [Implemented aDNA compatibility](docs/adna-compatibility.md). This describes what the code actually supports.
4. [Captured historical Pi notes](.engram/handoffs/2026-09-12/pi-evidence/index.json). Original source paths, snapshot time, and hashes are recorded. **Their June plans differ from the September live service.**

## User decisions to preserve

- Work on the medical-discovery system in the **Wilhelm Foundation hackathon** context; its user-reported Singapore focus is **myasthenia gravis and complex disease**. Kairos corrected the earlier Research to the People attribution on September 12. Keep Stanley's involvement distinct from any unverified organizational affiliation.
- The first pilot is **one complex patient case**. Neither the patient's identity nor their actual unresolved question has been supplied here.
- First-version ingestion includes **both uploads and medical-record connections**.
- Personal agents and accessible dashboards for patients, family, clinicians, and specialists; Stanley can administer accounts on his own lighthouse.
- The system must be **peer to peer and use aDNA**. No particular aDNA/LatLab API was mandated.
- Kairos says Stanley's plans and notes are in the Pi's lattice. Read existing work before designing replacement infrastructure.
- A week of Stampede3 access is anticipated. Actual allocation dates, partitions, and authorized data/model destinations remain unverified. The earlier “Sunday” travel reference needs a current date check.

## Verified Pi state — observed, not a deployment claim

| Item | Observed value |
| --- | --- |
| Hardware | Raspberry Pi 5 Model B Rev 1.1, Linux aarch64 |
| Memory / disk | About 15 GiB reported RAM, 13 GiB available; 939 GiB NVMe filesystem with 884 GiB available at inspection |
| Home / aDNA workspace | `/home/andy`, `/home/andy/aDNA` |
| Installed project | `/home/andy/aDNA/Nebula.aDNA` |
| Project revision | `3ea749a54f2eb0632c290c6be3e8db00326e98b9`; worktree clean when inspected |
| Wi-Fi / Ethernet IPv4 | `192.168.50.111` / `192.168.1.141` |
| Active overlay | `nebula43dd`, `10.43.0.16` |
| Active service | `nebula-1043-dd.service`, described as drug-discovery lighthouse |
| Service binary / config | `/usr/local/bin/nebula -config /etc/nebula-1043-dd/config.yml` |
| Service start reported by systemd | 2026-08-04 17:07:10 PDT |
| Observed listeners | UDP 4244, SSH TCP 22, local CUPS TCP 631, discovery-related UDP sockets |

No aDNA web application, JupyterHub, or LatLab service was demonstrated. A running Nebula process/interface does not prove healthy peer handshakes or access from Singapore. No Pi services, configuration, private keys, or lattice documents were changed by this session.

## Newer setup records and research leads found

**aDNA repo usage, later 2026-09-12:** The official read-only MCP server was found in `aDNA-Network/aDNA.aDNA/mcp`, built locally, and successfully used to search the published corpus and 74-vault registry. All four tools passed upstream live checks. A reusable CLI client and exact commands are in [aDNA usage and connection findings](.engram/handoffs/2026-09-12/adna-usage/README.md). It supplies published snapshots, not private live files. Newer registry leads include `Harness.aDNA` (display RareHarness, persona Panacea) and planned patient-system platform `CakeProtocol.aDNA`.

Newer `Git.aDNA` records describe **existing Forgejo mesh replicas**, not just a planned federation layer: R&D host `10.43.0.28`, HTTP 3300 / Git SSH 2222, intended mesh hostname `git.rd.adna.network`. The documented machine-read mechanism is **repo-scoped read-only deploy keys**, separate from Nebula identity. From this Pi, the hostname does not resolve and all tested forge ports time out; journal entries show no learned UDP address for `.28`. Pi certificate groups are `ssh` and `drug_discovery`, while an August forge record mentions `adna_lab` gating; this is a clue, not a confirmed diagnosis. We have not established which clinical vaults are replicated. Use the linked evidence to continue without repeating the claim that aDNA has no usable interface or requiring full workstation shell access as the only option.

**Direct mesh test, later 2026-09-12:** Stanley's workstation is reachable at **`10.43.0.2`**, identified in the Pi journal as `stanley-1043`. Ping succeeded and SSH TCP 22 responds. A Mac-to-Pi-to-Stanley SSH attempt as `stanley`, using the Mac's existing personal key and a pinned observed host key, reached the server but failed with **`Permission denied (publickey)`**. Both fleet lighthouses also respond; the old `.9`/`.11` compute addresses timed out from this Pi. Documented web ports 8000/8443 and standard 80/443 timed out on Stanley. [Connection evidence and continuation](.engram/handoffs/2026-09-12/stanley-lattice-exploration/MESH_CONNECTIVITY.md). An accepted login or shared application endpoint is needed to read his vaults; mesh reachability is now demonstrated.

Follow-up exploration on 2026-09-12 recovered newer Pi instructions and followed their aDNA references. Read [the exploration findings](.engram/handoffs/2026-09-12/stanley-lattice-exploration/FINDINGS.md) and source manifest before repeating the search. The snapshots remain local under ignored `.engram/`.

The project's June `MANIFEST.md` / `STATE.md` / genesis campaign describe an unfinished plan for **10.43.0.11**, `nebula-1043.service`, and `/etc/nebula-1043/`. The newly located `/home/andy/aDNA/Andy_Medicine_Discovery_Pi_Setup.md` (July file) and `/home/andy/Downloads/Prompt` (August Part 2 v2) instead specify **10.43.0.16**, `nebula-1043-dd.service`, and `/etc/nebula-1043-dd/`, matching live observation. The Pi's saved Claude transcripts also preserve the later setup history. Do not replay either set of installation instructions; the service is already running.

Those notes also define a **Nebula lighthouse as a non-data-bearing discovery/relay host**, with network governance held by upstream `Network.aDNA` (Venus). Superyak's **Lighthouse** is a semantic interchange system; these are different roles sharing a name. The draft proposal to host medical accounts/records on this Pi needs architectural reconciliation with the installed network role. Read the exact context in the fuller handoff. No deployment decision was made here.

An inherited March scorecard names MG disease-graph, therapeutic-landscape, target-dataset, and science-discovery lattice files, but their bodies are absent from the Pi's two aDNA roots. Public coordination notes identify Stanley-side `RareHarness.aDNA` (clinical runtime) and `RareArchive.aDNA` (rare-disease knowledge/governance); `science_stanley.aDNA` is documented as a brand-content vault. The actual clinical vaults were not reached. The related public codebase `Wilhelm-Foundation/rare-archive` is accessible at April 2 revision `8b8d4d0a62bf185e36d47aa12556b1abc18edf2c` and explicitly discusses MG. Its docs and root lattice were read, not executed or clinically validated. No current patient-case or Singapore plan was recovered. Exact artifact paths and access results are in the exploration findings.

## What is already implemented locally

Commit **`b01c475`** on local `main`: `feat: integrate aDNA project context and native lattice projections`. It has not been pushed by this session.

- Explicit `--adna-project INSTANCE=PATH` sources for chat and coding, preserving source IDs, original text, full content hashes, and bounded access.
- `make adna` / `superyak-adna` inspect, search, and read commands without a model.
- Native `lattice:` envelope support, preserved refs/ports, conservative typed-port evaluation, and `project-adna` export in Lighthouse.
- Tests, packaging, real upstream example validation, and independent review completed. Details in the fuller handoff.

```sh
make adna ADNA_ARGS='inspect adna=/Users/kairos/Projects/kinn/aDNA'
```

This adapter accepts **local paths**. An SSH connection does not automatically make the Pi's project a configured Superyak source. No medical ingestion, multiuser isolation, peer application transport, or Pi deployment was implemented.

## Safe continuation

Recheck `git status` and any live state needed for the next task. The newer Pi setup records and saved Claude transcripts have now been read. Follow the exact MG artifact paths and RareHarness/RareArchive leads in the exploration findings to locate the current research plan. Avoid changing services while discovering what is installed. Define the first patient question and actual record provider before implementing provider-specific ingestion.

The next model should preserve the broader aim: a home that supports continuity, recovery, disagreement, and independence. More agents, more recalled memories, and faster output are not sufficient evidence that it helps someone.
