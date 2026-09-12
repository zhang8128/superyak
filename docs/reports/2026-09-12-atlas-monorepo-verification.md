# Atlas monorepo verification — September 12, 2026

The current Atlas workbench is bundled under `atlas/`. Root setup, tests, CI,
an offline pilot, the memory POC, and allowlisted source staging now use that
component. The [integration plan](../atlas-integration.md) separates this
completed source integration from the next research-turn, aDNA, and cluster work.

## Imported source and isolation

The import captured 104 selected files from the dirty standalone Atlas working
tree based on `3a948a67be3357ed1b1c179a9c405a04450f14d7`: 48 unchanged tracked
files, 19 modified files, and 37 untracked files. The
[manifest](../../atlas/IMPORT-MANIFEST.json) records their original bytes before
monorepo packaging and documentation edits. All 104 original source hashes were
rechecked unchanged after integration. The 76 imported runtime, data, static,
script, and test files remain byte-identical to the audited source snapshot.

The import excludes the legacy engine, archived research collections, generated
archive artifacts, live research journals, personal notes, local environments,
and service/MCP bindings. The original checkout and historical POC worktree
remain in place. The demo uses an explicit project under `.engram/atlas/project`;
it copies four public inputs and refuses a mismatching existing seed before
refreshing. It creates no research drafts.

## Checks performed

Checks ran from the isolated migration worktree on macOS with Python 3.13.5
and uv 0.8.3. Atlas used its own locked environment with pytest 9.1.1 and MCP
1.30.0; Engram used its existing lock in a new worktree environment. These are
local results; the updated CI workflow has not been run remotely.

| Check | Result |
| --- | --- |
| `make setup-atlas` and `make setup-engram setup-lighthouse` | Locked installs and Lighthouse build passed |
| `make check-atlas` | 675 passed in 177.46 seconds |
| `make check-engram` | 2,495 passed, two expected live-config skips, five existing warnings in 255.94 seconds |
| `make check-lighthouse` | Build, lint, type checks, 139 tests, and both protocol proof commands passed |
| `make check-integration` | Two matching schemas, seven socket checks, four validated receipts, three interoperability tests; Atlas: 28 artifacts, 20 policy comparisons, two canonical JSON comparisons |
| Focused POC and monorepo tests | 35 passed; four new tests were first observed failing before implementation |
| `make atlas-demo` and `make atlas ATLAS_ARGS='context q-fate'` | Current publications, browser and Obsidian exports; pilot question readable |
| `uv build` in `atlas/` | Source distribution and wheel built |
| Independent implementation review | No actionable findings; four monorepo tests passed independently, plus seed/symlink/archive/lock checks |

Atlas and Engram run in separate pytest processes. The POC intentionally rejects
an already imported `workbench` outside its immutable run snapshot; this guard
was preserved. Bundled-source bridge tests now fail if Atlas is missing rather
than silently skipping without an external developer checkout.

## Distribution checks

The wheel contains all 40 workbench source/data/static files and distribution
metadata. It was installed without dependencies into a separate environment,
then imported with isolated Python from outside the checkout. Its renderer
produced HTML from packaged data and its installed `atlas-research` command
read the explicitly selected pilot. A separate review extracted the wheel and
checked its resources and 17-item pilot snapshot with site initialization off.

The actual prepared Stampede source archive was extracted into a temporary
directory. Its Atlas demo ran with `python -S`, without any editable install or
external Atlas source. The POC entry point loaded from that extracted tree using
the existing Engram dependencies. Regression tests also extract the archive and
read `q-fate` through its own Atlas script. Adversarial fixtures verify exclusion
of `.atlas`, `.engram`, `.obsidian`, `Research`, databases, environment files,
arbitrary JSON/text, and symlink payloads.

The staging change carries Atlas/POC source and reviewed public assets. The
existing synthetic Stampede campaign still uses its prior execution workflow;
bundling code does not connect the research scheduler or deploy a model.

## Recovery and remaining execution work

Changing the POC CLI's default Atlas path changes its implementation fingerprint.
Historical runs remain inspectable through `status`, while execution requires
their original pinned implementation. Saved hashes were not modified and old
run directories were not migrated. Use a new output directory for new code.

No live inference, literature retrieval, model download, Slurm submission,
external message, service restart, or remote push was performed. Tests used
controlled research/provider fixtures, temporary local transports, and disposable
projects. Dependency installation is the only new setup activity. An existing
Atlas worker or MCP process continues using its prior installation until an
explicit deployment changes its binding and process.

The repository-wide license remains undecided. The import does not assign a
new license or establish scientific quality, K3/GLM hosting, peer access, or
whole-Stampede3 capacity. Next work is the bounded evidence/provider/memory turn
and matched correction tests described in the integration plan.

Detailed local audit logs, source inventories, reviews, wheels and the prepared
source archive are retained under
`.worktrees/atlas-monorepo/.engram/atlas-import/`. The portable evidence for
contributors is this report, the import manifest, and the executable checks.
