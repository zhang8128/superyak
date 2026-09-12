# Atlas research workbench

Run `make atlas-demo` from the Superyak root and open the reported browser path
to explore two questions about cell fate and gene regulation. Follow an approach
to a scoped claim, its primary source and a proposed next test. The page works
offline; opening a publication link requires a connection.

This is the first usable local slice: 2 questions, 5 approaches, 8 source-reported claims, 2 proposed experiments and 6 primary publications. It has no expert-reviewed records or adjudicated dependencies. See the [source coverage](docs/workbench/pilot-sources.md), [evaluation sheet](docs/workbench/evaluation.md) and [longer-term roadmap](docs/workbench/roadmap.md).

The original research archive and its generated browser were excluded from this
source import. They remain in the standalone checkout and are not part of the
active public pilot. See the [migration record](../docs/monorepo-migration.md).

For optional model-backed work, see the [continuous research guide](docs/ollama-research.md).
The root command `make atlas ATLAS_ARGS='start'` uses an existing compatible local
Ollama model and the explicit project selected by `ATLAS_PROJECT`. It retrieves
papers and records proposed findings. Setup and the offline demo do not start it.

## Quick start

By default, the same model rotates through paper research, auditing, question
discovery, question overlap and comparisons of existing evidence. See [worker roles](docs/research-worker-roles.md)
for the `--role` rotation and its persistent outcomes.

Use Python 3.11 or newer. The low-level commands below run from `atlas/`, not
the Superyak root; change into that directory first. They use the standard
library and require no model or network access.

```bash
WORKBENCH_RUN_DIR="$(mktemp -d)"
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" init
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" import workbench/data/cell_fate.json
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" render --output "$WORKBENCH_RUN_DIR/pilot.html"
```

Open the resulting `pilot.html` with your browser. Keep the directory if you
want to retain local reviews. The source import includes the public JSON and
renderer; generated HTML is created locally.

The top cards show the first two questions by ID, with connected approaches and proposed tests. Larger collections show an explicit preview count and a “Browse all records” link. The browser retains every record. Search matches titles and summaries; type, status and facet filters intersect. Selecting a linked record outside the current filters preserves the filters and explains why the detail is outside the result set. All controls support the keyboard.

```bash
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" search fate --kind question --facet scale=molecular
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" search fate --kind question --facet scale=cellular
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" show c-markov
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" duplicates
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" unlocks q-fate
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" export > "$WORKBENCH_RUN_DIR/export.json"
```

Both scale searches find the same two question identities. `unlocks` returns `[]` in this pilot: prerequisites have not been adjudicated. It traverses only reviewed, active `requires`/`enables` relations, reversing `requires` and following `enables`. It reports reachability, not importance, funding priority or scientific certainty.

## Evidence and status

`proposed` means a question, interpretation, relation or experiment awaiting assessment. `source_reported` attributes a claim to a publication with a section locator; it does not assert independent replication. All pilot relation rationales are proposed editorial interpretations. A challenge is a reason to examine a boundary, not blanket disproof.

`reviewed` records a named local assessment and its timestamp. The software does not verify reviewer credentials, certify truth or turn a publication's peer-review status into our review. Review claims only after actually checking the evidence and scope. Reviewed claims and relations require source evidence; reviewed dependency relations also require rationale and context.

`withdrawn` retains the record and its evidence/history while excluding it and its incident edges from dependency traversal. Withdrawal is irreversible in this store. Here is a demonstration you can run against your temporary database:

```bash
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" review c-markov --status withdrawn --reason "Demo withdrawal; inspect retained evidence and history" --actor "Local reader"
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" render --output "$WORKBENCH_RUN_DIR/pilot.html"
```

Open the claim's “Review & withdrawal history” section in the regenerated page. A genuine assessment uses the same command with `--status reviewed`, the actual reviewer name and the actual reason. Each successful status transition is timestamped in the local database. Nothing in the browser silently changes a record's status.

## Editing JSON and importing corrections

The [pilot JSON](workbench/data/cell_fate.json) is a complete example of the [version 1 format](docs/superpowers/specs/2026-09-07-research-workbench-design.md). A bundle contains `schema_version`, `title`, `sources`, `items` and `relations`. Records have stable IDs; facets are annotations, not identities. Evidence entries contain `source_id`, a nonblank `locator`, and a short scoped `note`. Source URLs must use HTTP or HTTPS. Do not add full-text abstracts, guessed confidence scores or cost estimates.

Imports are atomic. An identical repeated import inserts nothing. A changed record with an existing ID is a conflict, even when only its summary or evidence changed; the entire import is refused. Unknown fields and dangling references are also refused. Import is not an in-place editor or merge operation.

For an amendment, make a small bundle containing the new revision with a new ID, its necessary sources, and new relation IDs with explicit rationale. Include only unchanged existing sources/items if needed. Import the amendment, then withdraw the superseded record with a reason naming the replacement ID. Do not reimport an old export containing stale versions of records whose statuses have since changed. You can instead import an edited complete snapshot into a new empty database to explore it separately; retain the original database if its local history matters.

Exports include `history` for inspection. Import validates that `history` is a list but deliberately ignores its events: a new database does not inherit another database's audit trail. Imported `reviewed_by` and `reviewed_at` fields are retained as supplied declarations, not credential verification. Keep the original database and exports when preserving provenance.

Rendering writes a complete temporary file beside the destination, then atomically replaces the destination. Existing output is replaceable only if it begins with this renderer's document marker. The command refuses source JSON, unrelated files, symlink outputs, the database and its journals; it does not create missing output directories. Other commands cannot initialize a missing database; use `init` explicitly.

## Optional legacy-note import

```bash
python3 -m workbench --db "$WORKBENCH_RUN_DIR/pilot.db" import-vault /absolute/path/to/VAULT
```

Only `VAULT/Nodes/**/*.md` is read. Each imported note becomes a proposed question with its original layer/domain as facets and original path/hash as provenance. The visible warning says the legacy kind and claims have not been reassessed. No old edges, costs, confidence or timelines become trusted workbench records. Local paths remain text. The adapter does not write to the source vault.

## Verification and next evaluation

With pytest available in your Python environment:

```bash
python3 -m pytest tests/workbench/test_store.py tests/workbench/test_legacy.py tests/workbench/test_cli.py tests/workbench/test_render.py tests/workbench/test_pilot.py -q
```

The checks cover store invariants, the portable corpus, output protection,
escaping and the CLI round trip. Use `make check-atlas` from the Superyak root
for the full component suite. The original pilot also received Chrome
navigation/filter and responsive-layout checks, as recorded in its historical
verification notes. These establish software behavior. The
[human evaluation sheet](docs/workbench/evaluation.md) remains uncompleted:
domain experts and prospective users still need to judge the research's usefulness.
