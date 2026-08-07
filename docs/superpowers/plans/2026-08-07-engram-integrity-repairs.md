# Engram Integrity Repairs Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Repair Engram's audit retention, compression and migration atomicity, knowledge-graph client configuration, and wheel contents without changing public MCP tool names or response shapes.

**Architecture:** Add two narrow boundaries: `operation_audit.py` owns metadata-only attribution, while `Storage.transaction()` makes existing storage helpers participate in one compression unit of work. Migrations become self-contained transactions, Graphiti receives explicit local embedding and reranking adapters, and installed resources resolve through a source-or-distribution helper.

**Tech Stack:** Python 3.12+, SQLite/SQLite-vec, MCP FastMCP, pytest 9, FastEmbed Nomic embeddings, Graphiti/Kuzu, setuptools, uv.

## Global Constraints

- Preserve the user's current uncommitted changes.
- Keep all existing MCP tool names and response shapes compatible.
- Keep attribution fail-open: an audit failure must not block a domain mutation.
- Keep optional knowledge-graph failure non-fatal.
- Never send knowledge-graph content to OpenAI implicitly.
- Make data-integrity guarantees enforceable with failure-injection tests.
- Do not inspect or rewrite the live Engram database during unit tests.
- Apply the live historical scrub only after the new server code is active and a verified backup exists.

---

## File Structure

**Create:**

- `operation_audit.py` — strict conversion of tool arguments to non-content audit metadata.
- `graphiti_local.py` — Graphiti embedding and cosine-reranking clients backed by Engram's provider.
- `resources.py` — locate migrations and prompts in source and installed layouts.
- `migrations/026_scrub_operation_details.sql` — remove historical content payloads while retaining approved metadata.
- `tests/test_packaging.py` — wheel-content and isolated-import regressions.

**Modify:**

- `storage.py` — atomic migrations, transaction context, deferred commits, installed migration resolution.
- `compress.py` — validation, one transaction, retryable pending state, post-commit graph feed, installed prompts.
- `server.py` — sanitized operation details and embedding-provider injection.
- `knowledge.py` — explicit local Graphiti clients and resource cleanup.
- `pyproject.toml` — all runtime modules and shared assets.
- `tests/test_storage.py`, `tests/test_operation_log.py`, `tests/test_compression.py`, `tests/test_knowledge.py`, `tests/test_config.py` — focused regressions.
- `CLAUDE.md` — accurate test and integration documentation.

---

### Task 1: Atomic Storage and Migration Foundation

**Files:**

- Modify: `storage.py:45-122`
- Test: `tests/test_storage.py`

**Interfaces:**

- Produces: `Storage.transaction() -> ContextManager[None]`.
- Produces: `Storage._commit() -> None`, immediate outside a transaction and deferred inside one.
- Produces: `_run_migrations()` with SQL and `schema_version` committed together.

- [ ] **Step 1: Write the failing migration rollback test**

```python
def test_failed_migration_rolls_back_schema_and_version(tmp_path):
    migrations = tmp_path / "migrations"
    migrations.mkdir()
    (migrations / "001_partial.sql").write_text(
        "CREATE TABLE half_applied(id INTEGER);\nTHIS IS NOT SQL;\n"
    )
    db_path = tmp_path / "graph.db"

    with pytest.raises(sqlite3.OperationalError, match="near \"THIS\""):
        Storage(str(db_path), migrations_dir=str(migrations))

    conn = sqlite3.connect(db_path)
    assert conn.execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='half_applied'"
    ).fetchone() is None
    assert conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0] == 0
    conn.close()
```

- [ ] **Step 2: Run it to verify the current partial-DDL failure**

Run: `.venv/bin/python -m pytest tests/test_storage.py::test_failed_migration_rolls_back_schema_and_version -q`

Expected: FAIL because `half_applied` still exists.

- [ ] **Step 3: Make each migration atomic**

Extract the connection pragmas into `_restore_pragmas()`. Execute each file as an explicit transaction, parameterize the version insert, and rollback before re-raising:

```python
try:
    self.conn.executescript("BEGIN IMMEDIATE;\n" + sql)
    self.conn.execute(
        "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
        (ver, _now_iso()),
    )
    self.conn.commit()
except Exception:
    if self.conn.in_transaction:
        self.conn.rollback()
    raise
finally:
    self._restore_pragmas()
```

Run the migration-7 content-hash backfill only after this transaction succeeds.

- [ ] **Step 4: Run storage tests to green**

Run: `.venv/bin/python -m pytest tests/test_storage.py -q`

Expected: PASS.

- [ ] **Step 5: Write the failing outer-transaction test**

```python
def test_storage_transaction_defers_helper_commits_and_rolls_back(tmp_db):
    episode_id = str(uuid.uuid4())
    with pytest.raises(RuntimeError, match="injected"):
        with tmp_db.transaction():
            tmp_db.add_episode(
                id=episode_id,
                session_id="transaction-test",
                content="This write must roll back with the outer unit of work.",
                embedding=[0.0] * 768,
            )
            raise RuntimeError("injected")

    assert tmp_db.get_episode(episode_id) is None
    assert tmp_db.conn.in_transaction is False
```

- [ ] **Step 6: Run it to verify the missing transaction boundary**

Run: `.venv/bin/python -m pytest tests/test_storage.py::test_storage_transaction_defers_helper_commits_and_rolls_back -q`

Expected: FAIL because `Storage.transaction` does not exist.

- [ ] **Step 7: Implement deferred nested commits**

Initialize `_transaction_depth = 0` before migrations and add:

```python
@contextmanager
def transaction(self) -> Iterator[None]:
    outermost = self._transaction_depth == 0
    if outermost:
        self.conn.execute("BEGIN IMMEDIATE")
    self._transaction_depth += 1
    try:
        yield
    except Exception:
        if outermost and self.conn.in_transaction:
            self.conn.rollback()
        raise
    else:
        if outermost:
            self.conn.commit()
    finally:
        self._transaction_depth -= 1

def _commit(self) -> None:
    if self._transaction_depth == 0:
        self.conn.commit()
```

Replace storage helper calls to `self.conn.commit()` with `self._commit()`. Keep migration commits and commits on separate cold-storage connections explicit. Preserve existing rollback-and-reraise paths.

- [ ] **Step 8: Run storage, integration, and forgetting tests**

Run: `.venv/bin/python -m pytest tests/test_storage.py tests/test_integration.py tests/test_persistence_forgetting.py -q`

Expected: PASS without a locked-database warning.

- [ ] **Step 9: Commit the storage foundation**

```bash
git add storage.py tests/test_storage.py
git diff --cached --check
git commit -m "fix: make storage migrations and transactions atomic"
```

---

### Task 2: Metadata-Only Operation Attribution and Historical Scrub

**Files:**

- Create: `operation_audit.py`
- Create: `migrations/026_scrub_operation_details.sql`
- Modify: `server.py:24-70`
- Modify: `tests/test_operation_log.py`

**Interfaces:**

- Produces: `sanitize_operation_details(operation: str, arguments: Mapping[str, object]) -> dict[str, object]`.
- Consumes: `inspect.BoundArguments.arguments` from `_record_operation()`.
- Produces: migration 026 with the same operation allowlist.

- [ ] **Step 1: Write failing table-driven sanitizer tests**

```python
@pytest.mark.parametrize(
    ("operation", "arguments", "expected"),
    [
        ("remember", {"content": "SECRET-REMEMBER", "core": True, "work": False},
         {"core": True, "work": False}),
        ("dream_capture", {"reaction": "SECRET-DREAM"}, {}),
        ("challenge_instinct", {"instinct_id": "i1", "evidence": "SECRET-EVIDENCE"}, {}),
        ("assessment_report", {"function_score": 4, "notes": "SECRET-NOTES"},
         {"function_score": 4}),
        ("compress_commit", {"compress_id": "c1", "summaries": [{"content": "SECRET-SUMMARY"}]},
         {"summary_count": 1}),
        ("clipboard_remind", {"text": "SECRET-CLIP", "trigger": "every_n_steps", "value": 5, "repeat": True},
         {"trigger": "every_n_steps", "value": 5, "repeat": True}),
    ],
)
def test_sanitize_operation_details_drops_content(operation, arguments, expected):
    from operation_audit import sanitize_operation_details
    sanitized = sanitize_operation_details(operation, arguments)
    assert sanitized == expected
    assert "SECRET" not in json.dumps(sanitized)
```

- [ ] **Step 2: Run the sanitizer test to verify RED**

Run: `.venv/bin/python -m pytest tests/test_operation_log.py::test_sanitize_operation_details_drops_content -q`

Expected: ERROR because `operation_audit` does not exist.

- [ ] **Step 3: Implement the strict sanitizer**

Use per-operation rules. Preserve only booleans and finite numbers from these scalar fields:

```python
_SCALAR_FIELDS = {
    "remember": {"core", "genome", "work"},
    "instinct_feedback": {"followed"},
    "mark_core": {"tier"},
    "assessment_report": {"function_score"},
    "reindex": {"full"},
    "graph_view": {"depth"},
    "clipboard_pin": {"priority"},
    "clipboard_remind": {"value", "repeat"},
}
```

Preserve strings only when they match exact enum sets for `reflect.focus`, `jot.scope`, `jot.status`, `erase.scope`, and `clipboard_remind.trigger`. Derive `summary_count` from `compress_commit.summaries`. Unknown operations and fields produce `{}`.

- [ ] **Step 4: Run sanitizer tests to green**

Run: `.venv/bin/python -m pytest tests/test_operation_log.py::test_sanitize_operation_details_drops_content -q`

Expected: PASS.

- [ ] **Step 5: Write a failing wrapper integration test**

Use the existing fake storage pattern. Decorate a function whose `__name__` is `dream_capture`, call it with `SECRET-DREAM-WRAPPER`, and assert `fake_storage.args[6] == {}` and the marker is absent from serialized details.

- [ ] **Step 6: Run it to verify raw arguments still cross the boundary**

Run: `.venv/bin/python -m pytest tests/test_operation_log.py::test_mutation_wrapper_never_logs_raw_content -q`

Expected: FAIL because `_record_operation()` forwards `bound.arguments`.

- [ ] **Step 7: Sanitize at `_record_operation()`**

Keep ID collection on raw arguments and results. Pass only:

```python
details = sanitize_operation_details(operation, values)
_storage.add_operation(
    operation, _session_id, harness, model, repo,
    list(dict.fromkeys(str(i) for i in ids if i)),
    details, outcome,
)
```

Preserve fail-open exception handling.

- [ ] **Step 8: Write migration 026 and a failing historical scrub test**

Use `json_valid`, `json_extract`, `json_type`, `json_array_length`, and `json_object` in a CASE by operation. The migration retains only fields defined by `operation_audit.py`; malformed or unknown rows become `{}`. Seed old rows with secret markers, remove schema version 26, rerun migrations, and assert markers are gone while `target_ids`, attribution columns, and approved scalar metadata remain.

- [ ] **Step 9: Add regressions for every content-bearing tool family**

Using the real temporary server fixture, invoke `remember`, `dream_capture`, `dream_react`, `task_focus`, `task_update`, `jot`, `clipboard_pin`, `clipboard_remind`, `challenge_instinct`, `retire_instinct`, `assessment_schedule`, `assessment_report`, and `compress_commit` with a distinct `SECRET-*` marker wherever their prerequisites can be seeded directly. Query only `operation_log.details` and assert none of the markers appear. Also assert each operation still has an attribution row with its target IDs and outcome.

- [ ] **Step 10: Run operation and migration tests**

Run: `.venv/bin/python -m pytest tests/test_operation_log.py tests/test_storage.py -q`

Expected: PASS with no secret marker in `operation_log.details`.

- [ ] **Step 11: Commit audit privacy changes**

`server.py` already has unrelated user edits. Stage only the sanitizer hunk and inspect the cached diff before committing:

```bash
git add operation_audit.py migrations/026_scrub_operation_details.sql tests/test_operation_log.py
git add -p server.py
git diff --cached --check
git diff --cached
git commit -m "fix: keep operation attribution metadata-only"
```

---

### Task 3: Atomic, Validated, Retryable Compression

**Files:**

- Modify: `compress.py:424-690`
- Modify: `tests/test_compression.py`
- Modify: `tests/test_knowledge.py:220-280`

**Interfaces:**

- Produces: `Compressor._validate_commit(state: dict, summaries: list[dict]) -> None`.
- Produces: `Compressor._commit_state(state: dict, summaries: list[dict], knowledge_feeds: list[tuple[list[dict], str]]) -> dict`.
- Consumes: `Storage.transaction()` from Task 1.
- Preserves: `Compressor.commit(compress_id: str, summaries: list[dict]) -> dict`.

- [ ] **Step 1: Write failing complete-request validation tests**

```python
def test_commit_rejects_summary_count_mismatch_without_consuming_pending(
    tmp_db, compressor, embedder,
):
    text = "validation episode"
    _add_episode(tmp_db, text, embedder.embed([text])[0])
    result = compressor.cluster_episodes()

    with pytest.raises(ValueError, match="summary count"):
        compressor.commit(result["compress_id"], [])

    assert result["compress_id"] in compressor._pending
    assert tmp_db.get_uncompressed_episodes()
```

Add a parameterized test for invalid action, semantic kind, lane, empty non-discard content, and missing or unknown reinforce semantic ID. Every case must assert unchanged database state and retained pending state.

- [ ] **Step 2: Run validation tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_compression.py -k 'summary_count_mismatch or invalid_commit_summary' -q`

Expected: FAIL because partial summaries are accepted and state is popped before validation.

- [ ] **Step 3: Implement full pre-validation**

Add:

```python
_VALID_COMMIT_ACTIONS = frozenset({"new", "reinforce", "discard"})
_VALID_SEMANTIC_KINDS = frozenset(
    {"fact", "relationship", "preference", "constraint", "disposition"}
)
_VALID_LANES = frozenset({"personal", "work"})
```

`_validate_commit` examines every cluster/summary pair before any write. Resolve reinforce IDs from the summary or cluster match and require `storage.get_semantic(id)` to exist. Reject booleans where a numeric or string value is required. Do not mutate the input summaries.

- [ ] **Step 4: Run validation tests to green**

Run: `.venv/bin/python -m pytest tests/test_compression.py -k 'summary_count_mismatch or invalid_commit_summary' -q`

Expected: PASS.

- [ ] **Step 5: Write a failing mid-commit rollback and retry test**

Create two controlled pending clusters. Monkeypatch `storage.add_semantic` to call the real method once and raise `RuntimeError("injected second cluster")` on the second call. Assert:

```python
with pytest.raises(RuntimeError, match="injected second cluster"):
    compressor.commit(compress_id, summaries)

assert tmp_db.conn.execute("SELECT COUNT(*) FROM semantics").fetchone()[0] == 0
assert [
    tmp_db.get_episode(episode_id)["compressed"] for episode_id in episode_ids
] == [0, 0]
assert tmp_db.conn.in_transaction is False
assert compress_id in compressor._pending
```

Restore `add_semantic`, retry the same `compress_id`, and assert two semantics and two compressed episodes are created exactly once.

Add a late-failure variant that raises from `storage.add_log_entry` after semantics, vectors, source links, and compressed flags have been written. It must assert that all of those writes roll back and the same `compress_id` remains retryable. Together with pre-validation and the second-cluster failure, these cover early, middle, and late failure stages.

- [ ] **Step 6: Run rollback test to verify RED**

Run: `.venv/bin/python -m pytest tests/test_compression.py::test_commit_rolls_back_every_write_and_remains_retryable -q`

Expected: FAIL with a committed first semantic, a consumed pending ID, or both.

- [ ] **Step 7: Coordinate one storage transaction**

Make `commit()` a small coordinator:

```python
def commit(self, compress_id: str, summaries: list[dict]) -> dict:
    state = self._pending.get(compress_id)
    if state is None:
        raise ValueError(f"Unknown compress_id: {compress_id}")
    self._validate_commit(state, summaries)
    knowledge_feeds = []
    with self._storage.transaction():
        result = self._commit_state(state, summaries, knowledge_feeds)
    self._pending.pop(compress_id, None)
    self._feed_knowledge_graph(knowledge_feeds)
    return result
```

Move the existing mutation body to `_commit_state`. Replace direct `self._storage.conn.commit()` calls reached by `_commit_state`, `_multi_link_episodes`, and `_check_instinct_creation` with `self._storage._commit()`.

- [ ] **Step 8: Move external graph calls after local commit**

Append `(cluster["episodes"], semantic_content)` to `knowledge_feeds` inside `_commit_state`. `_feed_knowledge_graph()` runs after the transaction commits and retains the existing non-fatal warning behavior.

- [ ] **Step 9: Write and run a graph ordering test**

Use a fake graph whose `feed()` asserts `storage.conn.in_transaction is False`. Inject a local failure and assert `feed()` was not called.

Run: `.venv/bin/python -m pytest tests/test_compression.py tests/test_knowledge.py -q`

Expected: PASS, including rollback, retry, and ordering cases.

- [ ] **Step 10: Commit compression integrity changes**

```bash
git add compress.py tests/test_compression.py tests/test_knowledge.py
git diff --cached --check
git commit -m "fix: make compression commits atomic and retryable"
```

---

### Task 4: Explicit Local Graphiti Clients

**Files:**

- Create: `graphiti_local.py`
- Modify: `knowledge.py:35-108`
- Modify: `server.py:324-350`
- Modify: `tests/test_knowledge.py`

**Interfaces:**

- Produces: `GraphitiEmbedder(embedding_provider)` implementing `EmbedderClient.create` and `create_batch`.
- Produces: `GraphitiReranker(embedding_provider)` implementing `CrossEncoderClient.rank` with cosine similarity.
- Changes: `KnowledgeGraph(config: GraphConfig, embedding_provider=None)`.
- Consumes: a provider with `embed(texts, prefix=...)` and `dimension()`.

- [ ] **Step 1: Write failing local-adapter tests**

```python
class FakeGraphEmbeddingProvider:
    def dimension(self):
        return 2

    def embed(self, texts, *, prefix="search_document"):
        return [[1.0, 0.0] if text == "query" else [0.0, 1.0] for text in texts]


@pytest.mark.anyio
async def test_graphiti_local_clients_use_engram_embeddings():
    provider = FakeGraphEmbeddingProvider()
    embedder = GraphitiEmbedder(provider)
    reranker = GraphitiReranker(provider)

    expected = provider.embed(["query"], prefix="search_document")[0]
    assert await embedder.create("query") == expected
    ranked = await reranker.rank("query", ["unrelated", "query"])
    assert ranked[0][0] == "query"
```

- [ ] **Step 2: Run adapter tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py -k graphiti_local_clients -q`

Expected: ERROR because `graphiti_local` does not exist.

- [ ] **Step 3: Implement both local adapters**

Subclass Graphiti's abstract clients. Use `asyncio.to_thread` for synchronous provider calls. `create()` accepts a string or list and returns one vector; `create_batch()` returns all vectors. `rank()` embeds the query with `search_query`, passages with `search_document`, computes NumPy cosine similarity, and sorts `(passage, score)` descending.

- [ ] **Step 4: Write a failing explicit-client construction test**

Patch `graphiti_core.Graphiti`, `KuzuDriver`, and `_run_async`. Construct `KnowledgeGraph(config, embedding_provider=fake_provider)` and assert the Graphiti call receives non-null `embedder` and `cross_encoder` instances of the local adapter classes. Patch the OpenAI client constructors to raise if invoked.

- [ ] **Step 5: Run construction test to verify RED**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py -k explicit_local_clients -q`

Expected: FAIL because `KnowledgeGraph` neither accepts nor passes an embedding provider.

- [ ] **Step 6: Inject clients and close partial initialization**

Pass:

```python
graphiti = Graphiti(
    graph_driver=driver,
    llm_client=llm_client,
    embedder=GraphitiEmbedder(self._embedding_provider),
    cross_encoder=GraphitiReranker(self._embedding_provider),
)
```

When initialization fails, close the Kuzu driver or Graphiti instance once, log one concise warning without a duplicate traceback, set `_graphiti = None`, and disable the graph. If graph support is enabled without an embedding provider, degrade through this same path rather than constructing defaults.

- [ ] **Step 7: Pass the server's existing provider**

Change server initialization to:

```python
_knowledge_graph = KnowledgeGraph(graph_config, embedding_provider=_embeddings)
```

Do not construct a second FastEmbed model.

- [ ] **Step 8: Run graph and server initialization tests**

Run: `.venv/bin/python -m pytest tests/test_knowledge.py tests/test_server_registry.py tests/test_server.py -q`

Expected: PASS without `OPENAI_API_KEY`.

- [ ] **Step 9: Commit local graph clients**

Stage only the graph constructor hunk from the already-modified `server.py`:

```bash
git add graphiti_local.py knowledge.py tests/test_knowledge.py
git add -p server.py
git diff --cached
git commit -m "fix: keep Graphiti embedding and ranking local"
```

---

### Task 5: Complete Wheel and Installed Resource Resolution

**Files:**

- Create: `resources.py`
- Create: `tests/test_packaging.py`
- Modify: `storage.py:69-72`
- Modify: `compress.py:133-146`
- Modify: `pyproject.toml:30-31`
- Test: `tests/test_config.py`

**Interfaces:**

- Produces: `resource_path(relative: str) -> Path`, resolving source checkout first and `${sys.prefix}/share/engram` second.
- Consumes: setuptools `data-files` installed under `share/engram`.
- Preserves: explicit `migrations_dir` and explicit absolute prompt paths.

- [ ] **Step 1: Write failing resource-resolution tests**

```python
def test_resource_path_uses_installed_share_when_source_asset_is_absent(
    tmp_path, monkeypatch,
):
    installed = tmp_path / "share" / "engram" / "migrations"
    installed.mkdir(parents=True)
    marker = installed / "001.sql"
    marker.write_text("SELECT 1;")
    monkeypatch.setattr(resources, "_SOURCE_ROOT", tmp_path / "missing-source")
    monkeypatch.setattr(resources, "_INSTALL_ROOT", tmp_path / "share" / "engram")

    assert resources.resource_path("migrations/001.sql") == marker
```

Also assert the checked-out source asset wins when both layouts exist.

- [ ] **Step 2: Run resource tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_config.py -k resource_path -q`

Expected: ERROR because `resources` does not exist.

- [ ] **Step 3: Implement source-or-installed resolution**

`resource_path()` returns an existing source path first, then an existing installed path, then the source path so callers produce an intelligible missing-file diagnostic. Change the default storage migration directory to `resource_path("migrations")`. In `classify_episode_kind_with_model`, preserve explicit paths, then check `ENGRAM_HOME / prompt_path`, then `resource_path(prompt_path)`.

- [ ] **Step 4: Write a failing wheel-content test**

Build under `tmp_path`, inspect with `zipfile.ZipFile`, and assert:

```python
required_modules = {path.name for path in PROJECT_ROOT.glob("*.py")}
wheel_modules = {Path(name).name for name in archive.namelist()}
assert required_modules <= wheel_modules
assert any(name.endswith("share/engram/migrations/026_scrub_operation_details.sql") for name in names)
assert any(name.endswith("share/engram/prompts/classify.txt") for name in names)
assert any(name.endswith("share/engram/hooks/hooks.json") for name in names)
assert any(name.endswith("share/engram/skills/engram/skill.md") for name in names)
```

The test moves any setuptools `build/` directory created in the checkout to its `tmp_path` cleanup area.

- [ ] **Step 5: Run wheel-content test to verify RED**

Run: `.venv/bin/python -m pytest tests/test_packaging.py::test_wheel_contains_runtime_modules_and_assets -q`

Expected: FAIL listing omitted modules and assets.

- [ ] **Step 6: Complete setuptools configuration**

Expand `py-modules` to every tracked top-level module plus `operation_audit`, `graphiti_local`, and `resources`. Add:

```toml
[tool.setuptools.data-files]
"share/engram/migrations" = ["migrations/*.sql"]
"share/engram/prompts" = ["prompts/*.txt"]
"share/engram/hooks" = ["hooks/*.py", "hooks/hooks.json"]
"share/engram/skills/engram" = ["skills/engram/skill.md"]
```

- [ ] **Step 7: Write and run isolated installed-wheel startup**

The packaging test creates a uv virtualenv under `tmp_path`, installs the wheel, changes cwd outside the repository, writes a temporary config with graph and watcher disabled, and runs:

```python
import os
os.environ["ENGRAM_HOME"] = os.environ["TEST_ENGRAM_HOME"]
os.environ["ENGRAM_PROJECT_ROOT"] = os.environ["TEST_ENGRAM_HOME"]
os.environ["ENGRAM_HARNESS"] = "codex"
import server
server._init()
assert len(server.mcp._tool_manager.list_tools()) == 40
assert server.status()["layers"]["episodes"] == 0
```

Run: `.venv/bin/python -m pytest tests/test_packaging.py -q`

Expected: PASS outside the repository.

- [ ] **Step 8: Run packaging-adjacent tests**

Run: `.venv/bin/python -m pytest tests/test_packaging.py tests/test_config.py tests/test_storage.py tests/test_compression.py -q`

Expected: PASS.

- [ ] **Step 9: Commit packaging changes**

```bash
git add resources.py pyproject.toml storage.py compress.py tests/test_packaging.py tests/test_config.py
git diff --cached --check
git commit -m "fix: ship complete Engram runtime assets"
```

---

### Task 6: Documentation, Full Verification, and Live-Scrub Handoff

**Files:**

- Modify: `CLAUDE.md`
- Verify: all files changed in Tasks 1-5

**Interfaces:**

- Consumes: all completed integrity repairs.
- Produces: accurate operator documentation and a restart-safe live migration procedure.

- [ ] **Step 1: Update architecture and test documentation**

In `CLAUDE.md`:

- replace `# 624 tests` with `# full test suite`;
- state that operation attribution stores metadata only and migration 026 scrubs historical payloads; and
- state that Graphiti extraction, embedding, and reranking remain local through Ollama and FastEmbed clients.

- [ ] **Step 2: Run focused regression suites**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_operation_log.py \
  tests/test_storage.py \
  tests/test_compression.py \
  tests/test_knowledge.py \
  tests/test_packaging.py -q
```

Expected: PASS with no raw-marker, partial-commit, half-migration, OpenAI-client, or wheel-asset failure.

- [ ] **Step 3: Run the complete suite and compile check**

Run:

```bash
.venv/bin/python -m pytest tests/ -q
.venv/bin/python -m compileall -q -x '/(?:\.venv|\.worktrees|\.claude/worktrees)/' .
```

Expected: all tests PASS and compileall exits 0.

- [ ] **Step 4: Run a real isolated MCP lifecycle and restart test**

Using a temporary `ENGRAM_HOME` and MCP stdio:

1. initialize and list 40 tools;
2. remember four work-lane episodes;
3. recall and log an outcome;
4. create, update, and archive a task context;
5. compress every returned cluster;
6. close the server;
7. start a second server against the same temporary home; and
8. verify original episode IDs and the semantic are recalled.

Query `operation_log.details` and assert none of the submitted content markers appear.

- [ ] **Step 5: Verify scrub behavior on a copy of the live database**

Resolve the active database with `config.resolve_db_path(Path("/Users/kairos/Projects/engram"))`. Use SQLite's backup API to copy it to a temporary directory. Open only the copy with updated `Storage`, verify schema version 26, and run:

```sql
SELECT COUNT(*)
FROM operation_log
WHERE details LIKE '%reaction%'
   OR details LIKE '%content%'
   OR details LIKE '%evidence%'
   OR details LIKE '%notes%';
```

Expected: `0`. Do not print historical payloads.

- [ ] **Step 6: Commit documentation**

```bash
git add CLAUDE.md
git diff --cached --check
git commit -m "docs: document Engram integrity guarantees"
```

- [ ] **Step 7: Inspect final repository state**

Run:

```bash
git status --short --branch
git log --oneline --decorate -8
```

Confirm every pre-existing user modification remains present and no build directory or temporary database is in the repository.

- [ ] **Step 8: Prepare the live scrub and restart handoff**

Do not mutate the live database while an old MCP process can append unsanitized rows. Report that the Engram MCP server must restart to load the new code. After the new process is active:

1. resolve and report the exact active database path without reading payload content;
2. create a timestamped SQLite backup under `.engram/backups/` with the backup API;
3. start updated `Storage` once to apply migration 026;
4. verify schema version 26 and zero forbidden keys in `operation_log.details`; and
5. report the backup path and verification counts.

The live scrub is complete only after this restart-and-verify sequence.
