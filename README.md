# Superyak

The product goal is an **open-source, peer-to-peer system** where people have
personal homes, private chats, and sharing layers they control across care
circles, projects, and organizations. The [dashboard and peer design](docs/superpowers/specs/2026-09-12-personal-dashboards-sharing-design.md)
records that direction and the first two-peer demonstration. The first participant application now lives in independently installable
[`peer/`](peer/README.md): authenticated homes, private rooms, versioned sharing,
explicit paired HTTPS delivery, and optional guarded local Gemma drafting.
The [verification report](docs/reports/2026-09-12-peer-home-verification.md) records
measured behavior and release boundaries. Richer clinical/HPC integrations remain
future work.

[`tuning/`](tuning/README.md) now provides clinical/biotech dataset snapshots,
selected Gemma provenance, local domain evaluations, and recoverable LoRA training.
The tiny-model CPU trainer is measured; the full-size Stampede3 pilot is pending.

The [backend data-source catalog](peer/API.md#backend-data-sources) manages private
uploaded files and selected-record collections, with source corrections,
pause/resume controls and repeatable imports with success/failure receipts.
CSV and JSON datasets retain their original bytes. Registering or enabling a
source does not publish its contents. The dashboard’s **Research & data** view now
exposes these controls, source provenance, and private evidence-review drafts.
Home also provides private starting templates, personal search, space membership
pages, a sharing overview, and larger-text/quiet-view preferences.

The [standard medical research source comparison](docs/reports/2026-09-13-standard-medical-research-sources.md)
prioritizes publication feeds and source-grounded evidence review. A
[three-paper import package](docs/data-sources/README.md) is prepared and checked
against the existing backend; automatic external feed connectors remain follow-up
work.

Superyak brings persistent agents, research evidence, and scoped interchange
into one repository. Engram provides individual and shared memory; Atlas manages
research questions, sources, proposed findings, and readable views; Lighthouse
defines interchange contracts and its TypeScript conformance kit. Component
packages and lockfiles remain independent, with shared commands and CI at the root.

| Path | Contents |
| --- | --- |
| [`tuning/`](tuning/README.md) | Clinical/biotech datasets, local evaluations, and text-attention LoRA training |
| [`team/`](team/README.md) | Team mode: a Claude Code or Codex lead with Codex and Claude Code builders/collaborators, Slack threads, plan canvases, shared engram memory ([guide](docs/team-mode.md)) |
| [`peer/`](peer/README.md) | Standalone personal home, private chats, sharing layers, and paired peer exchange |
| [`agent/`](agent/README.md) | Dock a machine's agent at a station: room tools, hook, mention watcher and `make dock`; the wormhole bridge to Stanley's aDNA lattice |
| [`engram/`](engram/) | Python memory system, MCP server, dynamic chat, and Lighthouse publisher/receiver |
| [`atlas/`](atlas/README.md) | Evidence workbench, literature workers, source review, and browser/Obsidian views |
| [`lighthouse/`](lighthouse/README.md) | Protocol schemas, TypeScript packages, adapters, bridges, and proofs |
| [`scripts/check_integration.py`](scripts/check_integration.py) | Schema agreement and Python-to-TypeScript receipt validation |

## Dock this machine

Deep Space 9 is the Superyak station on Andy's Pi: a [peer](peer/README.md) where people and
their agents share rooms. `make dock` docks this machine's agent there as a **ship**. Start
Claude Code in this clone and it offers to dock when `~/.superyak/station.json` is missing,
following [CLAUDE.md](CLAUDE.md); the [agent guide](agent/README.md) and the
[design](docs/superpowers/specs/2026-10-03-ds9-station-design.md) cover the rest. A newcomer
asks for access with `make dock DOCK_ARGS='--request ...'`, Andy approves it in the web app,
and Tailscale access arrives as one reusable share link (`make station-share-link` on the
Pi creates it; no admin key stays there). Mentioning the ship wakes it: the owner's fresh mentions (within 24 hours, not yet answered)
run Claude as a builder on a `lighthouse/<ship>/<message id>` branch (committed, never
pushed) and anyone else's get a read-only answer. Those runs get only the read-only aDNA
tools, never the station tools, and ignore user-level Claude settings.

## Setup and checks

Use Python 3.13, uv, Node.js 24 or newer, pnpm 11.20.0, and Make on Linux or
macOS. CI uses Python 3.13, uv 0.8.3, Node.js 24, and pnpm 11.20.0.
Engram's package supports Python 3.12 or newer; the shared setup defaults to 3.13.

```sh
git clone git@github.com:zhang8128/superyak.git
cd superyak
make setup
make check
```

`make setup` installs `engram/uv.lock` into `engram/.venv`,
`atlas/uv.lock` into `atlas/.venv`, and
`lighthouse/pnpm-lock.yaml` into the Lighthouse workspace, then builds its
packages. It also installs `peer/uv.lock` independently and installs the
`tuning/uv.lock` CPU training and development environment. For browser checks, run
`uv run --locked --project peer playwright install chromium` (Linux CI adds
`--with-deps`). `make check` runs the Engram, Atlas, peer, and clinical/biotech
tuning suites in separate processes, Lighthouse build/lint/typecheck/tests and
proofs, and the interoperability checks. Each check is also available separately
through `make check-peer`, `make check-team`, `make check-agent`,
`make check-tuning`, `make check-engram`,
`make check-atlas`, `make check-lighthouse`, and `make check-integration`. Run
`make help` for the command list.

The interoperability check uses disposable synthetic stores and a real local
Unix socket. It checks both shared schemas and validates four Engram receipts
with Lighthouse's CLI, including denial and withdrawal scenarios. It also
checks Unicode artifact digests and scoped receipt exports across both languages.
Atlas's public pilot publications are also validated by the Python and
TypeScript implementations, including their policy decisions.
These cross-language regression tests require the built Lighthouse packages in
`make check-integration`; Python-only test runs skip them when that setup is absent.
The interoperability check requires no model credentials or configured live
publishers.

Two Engram tests inspect a developer's live Codex configuration and are skipped
by default. To run those tests, explicitly supply both
`ENGRAM_LIVE_CODEX_CONFIG=/absolute/path/to/config.toml` and
`ENGRAM_LIVE_CODEX_PROJECT=/absolute/path/to/the/bound/engram` when running
`make check-engram`. An explicitly supplied invalid configuration fails the tests.

## Open your personal home

```sh
make setup-peer
make home-demo
```

Open the reported loopback URL (default `http://127.0.0.1:7435`). The local demo
opens the patient dashboard without a password. Open the account menu to try
family, doctor, or organizer; save your work before switching. This uses the
explicit loopback-only `--local-demo` option. Ordinary peers still require sign-in.
Fictional credentials remain private in `.engram/home-demo/demo-credentials.json`.
`HOME_DEMO_DATA` selects a different demo directory,
`HOME_PORT` changes the port, and `HOME_ARGS` adds explicit server options.
`make home` serves ordinary state at `.engram/home` (`HOME_DATA` overrides it);
provision its first owner with the [peer CLI](peer/README.md) before signing in.
Neither command starts a research worker or changes existing component stores.

`make peer-bundle PEER_BUNDLE=/new/path/superyak-peer.tar.gz` creates an explicit
allowlisted standalone source archive and refuses output reuse. The archive
includes its own license, lock, docs, tests, source, static assets and checksums.
Standard `uv build` in `peer/` also uses explicit sdist/wheel file inventories,
so demo credentials and other unlisted local files stay out of those packages.
Review the resulting artifact separately before public distribution; it contains
no parent history.

## Try Atlas offline

From the repository root:

```sh
make setup-atlas
make atlas-demo
make atlas ATLAS_ARGS='context q-fate'
```

The demo copies the public cell-fate pilot into `.engram/atlas/project` and
refreshes its publications, browser, and Obsidian notes. Open the reported browser
path to inspect the sources and proposed interpretations. It creates no research
drafts and makes no model or literature requests. Repeat it to refresh the same
project. Use `ATLAS_PROJECT=/absolute/path/to/project` to select another project.
The [Atlas guide](atlas/README.md) covers capture and optional local research;
the [integration plan](docs/atlas-integration.md) defines the next executable slices.

## Prepare Stampede3

The current [model requirement](docs/model-policy.md) is **American models only**,
with **Gemma 4** preferred. This supersedes the earlier Qwen/Kimi/GLM choices.
Historical examples and launcher defaults have not all been migrated; do not
launch them unchanged. Whole-machine scope remains accepted, while Gemma task
compatibility and placement require measurement.

The [model-tuning research plan](docs/reports/2026-09-13-stampede3-model-tuning-plan.md)
proposes Gemma LoRA experiments on Intel PVC, with exact model metadata,
parallel comparisons, evaluation gates, training consent, and peer adapter
distribution. It is a plan; cluster training has not been verified or launched.

Use [portable research tasks](docs/portable-research-tasks.md) to freeze one cached
MG source and compare an extraction/review turn through local or cluster model
protocols. `make research-task` shows explicit export/run commands; replay checks
saved evidence and responses without another model call.

The bounded [model protocol probe](docs/lead-model-probes.md) preserves the earlier
Kimi K3 / GLM-5.3 preparation as historical protocol work. `make lead-probe` shows
the existing endpoint probe interface; a new run must use an eligible model and
a compatible protocol. Model loading and hardware placement remain measurements.

For real public-source research before cluster access, use the separate
[Atlas research POC](docs/atlas-research-poc.md): `make research-poc` runs two
logical researchers across individual/shared memory conditions using an existing
local model and an isolated Atlas snapshot. It produces research drafts and a
comparison report, and resumes completed work without new model calls.
New runs use the bundled `atlas/` source. Resume requires the same pinned POC
implementation; the guide explains how to inspect preserved historical runs.

The [Stampede3 launcher](docs/stampede3-deployment.md) stages an Intel PVC campaign
with individual/shared memory comparisons and a separate continuing community.
It starts with bundled synthetic evidence, so patient or participant details are
not needed. Run `make stampede-plan` to create and inspect the local configuration,
then fill in its SSH login and allocation account when access arrives.
`make stampede-deploy` starts staging and submission; on macOS, you can instead
double-click [Start Stampede3.command](scripts/Start%20Stampede3.command).
`make stampede-simulate` rehearses memory and recovery locally. Intel hardware
compatibility is verified during the first compute allocation.
The source archive carries Atlas and the POC, while the launched campaign still
uses its bounded synthetic workflow. Whole-Stampede3 execution and persistent
lead identities remain planning scope. Their earlier K3/GLM assignments are
superseded; eligible model placement, replica counts, and useful throughput
have not been measured.

## Run Engram

To use an existing aDNA project, see [aDNA compatibility](docs/adna-compatibility.md).
`make adna ADNA_ARGS='inspect clinic=/path/to/Clinic.aDNA'` inspects a project
without a model. Add `--adna-project clinic=/path/to/Clinic.aDNA` to chat or
coding options to retrieve its attributed documents. Lighthouse also accepts
the current aDNA lattice format through its `project-adna` command.

To ask another local Codex session a question, see
[Codex session messaging](docs/codex-sessions.md). `make sessions` lists session
metadata; the separate MCP server adds discovery, question, and reply tools.
It uses Codex's native queue alongside Engram and Lighthouse.

After setup, with the Codex CLI installed and authenticated:

```sh
make chat ENGRAM_ARGS='--no-engram --thread first-chat'
make serve ENGRAM_ARGS='--no-engram --thread browser-chat' SERVE_ARGS='--port 7434'
```

The web interface in this example opens at `http://127.0.0.1:7434`.
`ENGRAM_ARGS` holds options before the subcommand; `CHAT_ARGS` and `SERVE_ARGS`
hold options after it. The default provider is Codex, using the existing login.
The examples archive conversations locally under `engram/.engram/context-runtime`.

To use an existing memory installation, explicitly set `ENGRAM_HOME` to its
parent directory and pass `--instance` for the intended named instance. See the
[dynamic context guide](engram/docs/dynamic-context.md), especially
[Lighthouse sources for chat](engram/docs/dynamic-context.md#opt-into-lighthouse-sources-for-chat),
and the [receiver guide](engram/docs/lighthouse-receiver.md) for opt-in policies.

The imported Engram plugin's MCP and hook files retain their original
machine-specific bindings. Cloning this repository does not install those
bindings, move memory databases, or change a running service. The former
Lighthouse project binding is available as an optional
[`engram-project.toml` example](lighthouse/examples/engram-project.toml);
actual `.engram/` state is ignored.

For a shared installation, use the repository's canonical
[`scripts/runtime.py`](scripts/runtime.py) launcher to keep source code separate
from the existing memory home. The launcher requires an explicit runtime JSON
file and provides MCP, hook, publisher, and read-only status commands. See
[Runtime installation](docs/runtime-installation.md) for the configuration,
stable wrapper, supervision, health, restart, and rollback procedures.

Engram and Lighthouse retain their source histories. Atlas is a selective
snapshot of its current workbench, including uncommitted source, with original
file hashes in [IMPORT-MANIFEST.json](atlas/IMPORT-MANIFEST.json). See the
[migration record](docs/monorepo-migration.md) for source revisions, exclusions,
and the relationship to the preserved original checkouts.

The newly authored standalone `peer/` application is Apache-2.0. Imported code
retains its existing notices and is not relicensed. The historical parent
repository remains private; the allowlisted peer source archive is the reviewable
public-release candidate. Preparing it does not publish it or change visibility.
