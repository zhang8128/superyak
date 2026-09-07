# Engram and Lighthouse import

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

Develop new changes in `engram/` and `lighthouse/` here. Keep Python dependency
updates in `engram/pyproject.toml` and `engram/uv.lock`, and Node dependency
updates in Lighthouse's workspace and lockfile. CI checks both projects and
their shared schemas on every pull request and push to `main`.

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
