# Superyak

Superyak brings persistent agents, research evidence, and scoped interchange
into one repository. Engram provides individual and shared memory; Atlas manages
research questions, sources, proposed findings, and readable views; Lighthouse
defines interchange contracts and its TypeScript conformance kit. Component
packages and lockfiles remain independent, with shared commands and CI at the root.

| Path | Contents |
| --- | --- |
| [`engram/`](engram/) | Python memory system, MCP server, dynamic chat, and Lighthouse publisher/receiver |
| [`atlas/`](atlas/README.md) | Evidence workbench, literature workers, source review, and browser/Obsidian views |
| [`lighthouse/`](lighthouse/README.md) | Protocol schemas, TypeScript packages, adapters, bridges, and proofs |
| [`scripts/check_integration.py`](scripts/check_integration.py) | Schema agreement and Python-to-TypeScript receipt validation |

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
packages. `make check` runs the Engram and Atlas suites in separate processes,
Lighthouse build/lint/typecheck/tests
and proofs, and the interoperability check. Each check is also available
separately through `make check-engram`, `make check-atlas`, `make check-lighthouse`, and
`make check-integration`. Run `make help` for the command list.

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

For the agreed Kimi K3 / GLM-5.3 lead pairing, use the bounded
[model protocol probe](docs/lead-model-probes.md). `make lead-probe` shows how to
test an existing endpoint with an initial observation and a source correction.
Model loading and hardware placement remain separate measurements.

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
uses its bounded synthetic workflow. Whole-Stampede3 execution and the agreed
four Kimi K3 plus four GLM-5.3 lead identities remain planning scope; model
placement, replica counts, and useful throughput have not been measured.

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

An open-source release is intended. The repository-wide license is still an
owner decision; this integration preserves existing notices and does not assign
a new license to the imported code.
