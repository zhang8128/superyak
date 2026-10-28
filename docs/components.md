# More of the system

These parts are earlier work that the README used to describe at length. They are kept here so the README can stay a
front door.

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
The [Atlas guide](../atlas/README.md) covers capture and optional local research;
the [integration plan](../docs/atlas-integration.md) defines the next executable slices.

## Prepare Stampede3

The current [model requirement](../docs/model-policy.md) is **American models only**,
with **Gemma 4** preferred. This supersedes the earlier Qwen/Kimi/GLM choices.
Historical examples and launcher defaults have not all been migrated; do not
launch them unchanged. Whole-machine scope remains accepted, while Gemma task
compatibility and placement require measurement.

The [model-tuning research plan](../docs/reports/2026-09-13-stampede3-model-tuning-plan.md)
proposes Gemma LoRA experiments on Intel PVC, with exact model metadata,
parallel comparisons, evaluation gates, training consent, and peer adapter
distribution. It is a plan; cluster training has not been verified or launched.

Use [portable research tasks](../docs/portable-research-tasks.md) to freeze one cached
MG source and compare an extraction/review turn through local or cluster model
protocols. `make research-task` shows explicit export/run commands; replay checks
saved evidence and responses without another model call.

The bounded [model protocol probe](../docs/lead-model-probes.md) preserves the earlier
Kimi K3 / GLM-5.3 preparation as historical protocol work. `make lead-probe` shows
the existing endpoint probe interface; a new run must use an eligible model and
a compatible protocol. Model loading and hardware placement remain measurements.

For real public-source research before cluster access, use the separate
[Atlas research POC](../docs/atlas-research-poc.md): `make research-poc` runs two
logical researchers across individual/shared memory conditions using an existing
local model and an isolated Atlas snapshot. It produces research drafts and a
comparison report, and resumes completed work without new model calls.
New runs use the bundled `atlas/` source. Resume requires the same pinned POC
implementation; the guide explains how to inspect preserved historical runs.

The [Stampede3 launcher](../docs/stampede3-deployment.md) stages an Intel PVC campaign
with individual/shared memory comparisons and a separate continuing community.
It starts with bundled synthetic evidence, so patient or participant details are
not needed. Run `make stampede-plan` to create and inspect the local configuration,
then fill in its SSH login and allocation account when access arrives.
`make stampede-deploy` starts staging and submission; on macOS, you can instead
double-click [Start Stampede3.command](../scripts/Start%20Stampede3.command).
`make stampede-simulate` rehearses memory and recovery locally. Intel hardware
compatibility is verified during the first compute allocation.
The source archive carries Atlas and the POC, while the launched campaign still
uses its bounded synthetic workflow. Whole-Stampede3 execution and persistent
lead identities remain planning scope. Their earlier K3/GLM assignments are
superseded; eligible model placement, replica counts, and useful throughput
have not been measured.

## Run Engram

To use an existing aDNA project, see [aDNA compatibility](../docs/adna-compatibility.md).
`make adna ADNA_ARGS='inspect clinic=/path/to/Clinic.aDNA'` inspects a project
without a model. Add `--adna-project clinic=/path/to/Clinic.aDNA` to chat or
coding options to retrieve its attributed documents. Lighthouse also accepts
the current aDNA lattice format through its `project-adna` command.

To ask another local Codex session a question, see
[Codex session messaging](../docs/codex-sessions.md). `make sessions` lists session
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
[dynamic context guide](../engram/docs/dynamic-context.md), especially
[Lighthouse sources for chat](../engram/docs/dynamic-context.md#opt-into-lighthouse-sources-for-chat),
and the [receiver guide](../engram/docs/lighthouse-receiver.md) for opt-in policies.

The imported Engram plugin's MCP and hook files retain their original
machine-specific bindings. Cloning this repository does not install those
bindings, move memory databases, or change a running service. The former
Lighthouse project binding is available as an optional
[`engram-project.toml` example](../lighthouse/examples/engram-project.toml);
actual `.engram/` state is ignored.

For a shared installation, use the repository's canonical
[`scripts/runtime.py`](../scripts/runtime.py) launcher to keep source code separate
from the existing memory home. The launcher requires an explicit runtime JSON
file and provides MCP, hook, publisher, and read-only status commands. See
[Runtime installation](../docs/runtime-installation.md) for the configuration,
stable wrapper, supervision, health, restart, and rollback procedures.

Engram and Lighthouse retain their source histories. Atlas is a selective
snapshot of its current workbench, including uncommitted source, with original
file hashes in [IMPORT-MANIFEST.json](../atlas/IMPORT-MANIFEST.json). See the
[migration record](../docs/monorepo-migration.md) for source revisions, exclusions,
and the relationship to the preserved original checkouts.

The whole repository is under the [Apache License 2.0](../LICENSE), with one exception that
[NOTICE](../NOTICE) names: `lighthouse/fixtures/adna-upstream/`, a Lat Labs fixture under the MIT License.
