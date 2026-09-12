# Component imports

Superyak contains Engram, Lighthouse, and the current Atlas research workbench.
The imports have different provenance: Engram and Lighthouse retain Git ancestry;
Atlas is a selective snapshot of its current working files.

## Engram and Lighthouse

Superyak is the shared development repository at
`git@github.com:zhang8128/superyak.git`. Its original `main` contained only a
README. The import branch is `feat/engram-lighthouse-monorepo`.

Both projects were imported with non-squashed `git subtree add`, preserving
the complete ancestry of the selected branches and the original commit IDs.
The component directories are ordinary tracked source, with no submodules or
dependency on the original local checkout paths.

| Component | Selected source | Original commit | Imported tree |
| --- | --- | --- | --- |
| Engram | `feat/dynamic-context` | `5dedd396e213daea2742445f89b0c21e12fea0bc` | `dd2c7db4bdccff22619359217ad3d73deee1e88b` |
| Lighthouse | `main` | `0a9f615e681f84386d0088fc0f5ddde18ed00966` | `2c746068f65c0c6c1f017eaa9a7d2d7ab91afe32` |

Engram's import includes the completed dynamic chat Lighthouse source adapter
and its validation evidence. The subtree import commits are `5f132048` for
Engram and `45ebe223` for Lighthouse. The imported trees were checked against
the originals before the monorepo integration changes.

Develop new changes in `engram/` and `lighthouse/` here. Keep their Python dependency
updates in `engram/pyproject.toml` and `engram/uv.lock`, and Node dependency
updates in Lighthouse's workspace and lockfile. CI checks both projects and
their shared schemas on every pull request and branch push, including the
initial import before the workflow exists on `main`.

For history before the directory move, inspect the retained source commits:

```sh
git log --all --graph --oneline
git log 5dedd396 -- context_lighthouse.py
git log 0a9f615e -- schemas/recall-receipt.schema.json
```

The original `/Users/kairos/Projects/engram` and
`/Users/kairos/Projects/lighthouse` checkouts remain in place. Their live
services, memory databases, receiver grants, and publisher policies were not
migrated. Tracked historical reports retain their original paths and bytes so
their checksums remain useful; their old launch commands describe those runs.
Use the root README's commands for this checkout.

Monorepo changes make sibling schema tests resolve the adjacent Lighthouse
directory (or explicit `LIGHTHOUSE_REPO`), make two live Codex host checks
opt-in, and move Lighthouse's tracked project binding from
`.engram/config.toml` to `examples/engram-project.toml`. Setup and checks do not
activate that example. The existing Engram MCP/plugin configuration remains
specific to the original installation; changing it is a separate deployment
step.

## Atlas workbench — September 12, 2026

`atlas/` was imported from the standalone `atlas-workbench` checkout at base
revision `3a948a67be3357ed1b1c179a9c405a04450f14d7`. That checkout had
substantial modified and untracked current research code. The import includes
those selected working files rather than reverting them to the base commit.

[IMPORT-MANIFEST.json](../atlas/IMPORT-MANIFEST.json) records the capture time,
base revision, dirty flag, and each selected file's original size, SHA-256, and
tracked/modified/untracked status. Paths are relative to the original Atlas
root. Hashes describe the original bytes before integration changes to package
metadata, documentation, and entry points. Git records the integrated files;
the manifest should not be rewritten to pretend those later edits were upstream.

The selected scope includes `workbench/`, its tests, public pilot/configuration
JSON, three browser assets, relevant guides and dated design history, and the
CLI/interoperability helper scripts. The package remains named `workbench`, with
its existing relative data layout, inside the monorepo's `atlas/` component.
Atlas dependency changes belong in `atlas/pyproject.toml` and `atlas/uv.lock`.

This import excludes the legacy `atlas/` engine, legacy vault and archived
research collections, generated browser/archive artifacts, live `.atlas` journal,
`Research/` notes, `.obsidian/` settings, environments, credentials, and local
MCP/service bindings. It does not import Atlas's complete Git ancestry. The
original `/Users/kairos/Projects/atlas-workbench` checkout, its history, dirty
work, and research state remain in place. No running process is migrated by
setup or by the source import.

Root commands use an explicit research project under `.engram/atlas/project`
by default. `make atlas-demo` prepares the public seed and refreshes derived
views without adding drafts. Atlas tests run separately from Engram's POC
tests, whose process imports an immutable frozen Atlas snapshot. Root setup,
checks, and CI include Atlas; the POC defaults to bundled source and the source
archive carries Atlas/POC code without activating them in the synthetic campaign.

Changing the POC CLI changes its implementation fingerprint. Historical results
remain inspectable, but execution requires their pinned implementation; the old
`.worktrees/atlas-research-poc` is retained locally. See the
[POC recovery guide](atlas-research-poc.md#recovery-and-iteration).

Historical dated documents retain the context of their original runs, including
paths to excluded artifacts. Current guides use the bundled pilot and root
commands. The repository-wide open-source license is still an owner decision;
this selective import preserves notices without inventing a new license grant.
