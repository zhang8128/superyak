# Atlas research workbench

Atlas keeps research questions, source passages, proposed findings, relations,
and assessments together. It produces searchable browser pages and linked
Obsidian notes. A recorded finding retains its evidence and uncertainty;
automated support review leaves its scientific status **proposed**.

This component contains the current `workbench` implementation. Superyak's
[integration plan](../docs/atlas-integration.md) explains its relationship to
Engram memory, Lighthouse interchange, aDNA projects, and execution infrastructure.

## Setup and offline pilot

Run from the Superyak repository root:

```sh
make setup-atlas
make atlas-demo
make atlas ATLAS_ARGS='context q-fate'
make atlas ATLAS_ARGS='status'
make check-atlas
```

Setup uses `atlas/uv.lock` and `atlas/.venv`, including development and optional
MCP dependencies. The root defaults to Python 3.13; the core workbench supports
Python 3.11 or newer and uses the standard library.

The demo seeds `.engram/atlas/project` from the bundled public cell-fate data,
then refreshes its publications and browser/Obsidian exports. It creates no
drafts and needs no model, network, or external Atlas checkout after setup.
Open the browser path it reports. Repeated refreshes preserve the project's
draft journal and personal notes. `ATLAS_PROJECT` selects a different explicit
project for the root commands:

```sh
make atlas-demo ATLAS_PROJECT=/absolute/path/to/my-atlas-project
make atlas ATLAS_PROJECT=/absolute/path/to/my-atlas-project ATLAS_ARGS='context q-fate'
```

Use a new destination for an independent pilot. An existing project's seed
files must exactly match the bundled inputs; the demo refuses changed inputs.
The source directory `atlas/` and the selected
research project have separate roles: `.atlas/`, `Research/`, and `.obsidian/`
belong inside the research project.

## Research and capture

The root `make atlas` command exposes the automation CLI. For example,
`make atlas ATLAS_ARGS='record /absolute/path/to/finding.json --session my-research-session'`
records an attributed proposed draft. Outside Codex, supply `--session` with
your actual local attribution label; a Codex session can use `CODEX_THREAD_ID`.
Consult the [recording guide](docs/research-recording.md)
before capture; stable idempotency keys make interrupted publication recoverable.
`make atlas ATLAS_ARGS='refresh'` regenerates derived views.

The [continuous research guide](docs/ollama-research.md) describes explicit
model-backed operation against an existing local Ollama service. Its default
model is `qwen3.8:27b-mlx`. The [memory POC](../docs/atlas-research-poc.md)
instead runs fixed public-source tasks across Engram memory conditions using
isolated Atlas snapshots. These are separate research workflows.

Setup installs `atlas-research` and `atlas-workbench` inside `atlas/.venv`; it
does not configure a global launcher or connect an MCP server. If using the
installed CLI directly, always select the project explicitly:

```sh
atlas/.venv/bin/atlas-research --project /absolute/path/to/project context q-fate
```

Optional MCP tools are constructed with
`workbench.automation_mcp.create_server(ResearchInbox(project))` for an explicit
project. Root CLI commands provide capture without that connection.

## Guides and checks

- [Workbench format, status, and database CLI](WORKBENCH.md)
- [Research workers and overlapping questions](docs/research-worker-roles.md)
- [Dynamic evidence context](docs/dynamic-research-context.md) and [source review](docs/source-support-review.md)
- [Lighthouse publication and admission](docs/lighthouse.md)
- [Browser and Obsidian views](docs/obsidian-research.md)
- [Pilot sources](docs/workbench/pilot-sources.md) and [human evaluation sheet](docs/workbench/evaluation.md)

`make check-atlas` runs the component suite independently of Engram's frozen
Atlas POC tests. After `make setup`, `make check-integration` also validates
Atlas pilot publications against Lighthouse's TypeScript implementation.
Model and literature boundaries use controlled fixtures in these checks.
Dated plans and verification notes under `docs/` describe their original runs.

## Import provenance and release status

[IMPORT-MANIFEST.json](IMPORT-MANIFEST.json) records the selected current files
from standalone Atlas revision `3a948a67be3357ed1b1c179a9c405a04450f14d7`,
including modified and untracked work. Its hashes describe original bytes
**before monorepo integration edits**; Git records subsequent changes here.
This is a selective snapshot, not an exact checkout of that revision or a
subtree import of Atlas history.

The legacy engine, archived research collections and generated artifacts,
live journal, Obsidian settings, and local service bindings were excluded.
The original checkout and its uncommitted work remain in place. See the
[migration record](../docs/monorepo-migration.md) for the full boundary.
The repository-wide open-source license remains undecided; no new license
was inferred from the import.
