# Codex Session Binding and Sleep Fail-Open Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Make Codex hooks and Engram MCP writes share one authoritative session identity, while guaranteeing that sleep-hook vector-extension failures remain silent and close their database connection.

**Architecture:** A measured launcher key (`ENGRAM_RUN_KEY=codex:<parent-pid>`) binds the hook payload's Codex session ID to the lazily initialized MCP server through a small SQLite `session_bindings` table. Hook provenance remains authoritative and invisible; the MCP server adopts that session ID or falls back to its existing generated UUID. The sleep hook expands its fail-open boundary across connection and extension setup and clears the runtime binding at Stop.

**Tech Stack:** Python 3.14, SQLite, sqlite-vec, FastMCP, pytest, Codex hooks JSON, Codex TOML MCP configuration

## Global Constraints

- Shared Engram identity; exact hook/MCP session identity per Codex encounter.
- GPT/Claude perspective provenance stays silent during orientation, recall, reflect, and normal MCP output.
- Never correlate sessions approximately by repository or timestamp.
- Claude Code continues to prefer `CLAUDE_SESSION_ID` and must ignore an inherited Codex run key.
- Missing bindings, missing migrations, malformed input, and hook failures remain fail-open.
- Reviewer children continue to skip all Engram hooks.
- No retrospective repair of existing model-less registry rows.
- No assessment scheduling or content changes.
- Do not harden the pre-existing nudge connection path in this patch.

---

## File Map

- Create `migrations/024_session_bindings.sql`: runtime-key to authoritative-session mapping.
- Create `tests/test_session_bindings.py`: migration and Storage binding contract.
- Modify `storage.py`: best-effort bind, resolve, and clear methods.
- Modify `hooks/harness.py`: parse Codex-only run key and provide raw-SQL bind/clear helpers.
- Modify `hooks/wake.py`: bind immediately after the authoritative registry stamp.
- Modify `hooks/sleep.py`: fail-open connection lifecycle and Stop cleanup.
- Modify `tests/test_harness.py`: run-key parsing and raw-SQL helper coverage.
- Modify `tests/test_wake.py`: SessionStart binding integration.
- Modify `tests/test_nudge_harness.py`: extension-load failure/close regression and binding cleanup.
- Modify `server.py`: resolve bound Codex session before generated-UUID fallback.
- Modify `tests/test_server_registry.py`: bound Codex, fallback, Claude precedence, and provenance-join tests.
- Modify `~/.codex/hooks.json`: export the measured run key from all three hook launchers.
- Modify `~/.codex/config.toml`: launch Engram MCP through a shell exporting the same run key.

---

### Task 1: Prove the Launcher Correlation Key

**Files:**
- Create temporarily: `/tmp/engram-codex-run-key-probe/hooks.json`
- Create temporarily: `/tmp/engram-codex-run-key-probe/config.toml`
- Output: `/tmp/engram-codex-run-key-probe/parents.log`

**Interfaces:**
- Consumes: Codex SessionStart hook launcher and stdio MCP launcher behavior.
- Produces: verified rule that both launcher shells observe the same Codex parent PID; if false, the exact ancestry rule replacing `$PPID`.

- [ ] **Step 1: Create an isolated probe configuration**

Use `apply_patch` to create the temporary files. `hooks.json` contains:

```json
{
  "description": "Engram run-key parent probe",
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "sh -c 'printf \"hook|%s\\n\" \"$PPID\" >> /tmp/engram-codex-run-key-probe/parents.log'", "timeout": 5}]}
    ]
  }
}
```

`config.toml` contains:

```toml
model = "gpt-5.6-sol"

[mcp_servers.engram_probe]
command = "sh"
args = ["-c", 'printf "mcp|%s\n" "$PPID" >> /tmp/engram-codex-run-key-probe/parents.log; exec uv run --directory /Users/kairos/Projects/engram python server.py']
startup_timeout_sec = 30
```

- [ ] **Step 2: Run the isolated exec probe**

Run:

```bash
: > /tmp/engram-codex-run-key-probe/parents.log
CODEX_HOME=/tmp/engram-codex-run-key-probe codex exec \
  --skip-git-repo-check --dangerously-bypass-hook-trust "Reply only: ok" < /dev/null
sort /tmp/engram-codex-run-key-probe/parents.log
```

Expected: exactly one `hook|<pid>` line and one `mcp|<pid>` line with identical numeric PID values.

- [ ] **Step 3: Probe TUI launch behavior**

Run `CODEX_HOME=/tmp/engram-codex-run-key-probe codex`, submit `Reply only: ok`, exit, then inspect:

```bash
sort /tmp/engram-codex-run-key-probe/parents.log
```

Expected: the newly appended hook/MCP pair has the same numeric PID within that launch and a different PID from the exec launch.

- [ ] **Step 4: Record the result before proceeding**

If both probes pass, use `ENGRAM_RUN_KEY="codex:$PPID"` in Tasks 2-5. If either differs, stop: inspect both process trees with `ps -o pid=,ppid=,command= -p <pid>` and amend the approved design and this plan with a deterministic nearest-common-Codex-ancestor helper before writing migration 024. Do not substitute timestamp or repo matching.

---

### Task 2: Add the Runtime Binding Store

**Files:**
- Create: `migrations/024_session_bindings.sql`
- Create: `tests/test_session_bindings.py`
- Modify: `storage.py:1588-1616`
- Modify: `tests/test_harness.py`
- Modify: `hooks/harness.py:29-111`

**Interfaces:**
- Consumes: verified `ENGRAM_RUN_KEY` from Task 1.
- Produces: `Storage.bind_session(run_key: str, session_id: str) -> None`, `Storage.resolve_session_binding(run_key: str) -> str | None`, `Storage.clear_session_binding(run_key: str, session_id: str | None = None) -> None`, `bind_session(conn, ctx) -> None`, and `clear_session_binding(conn, ctx) -> None`.

- [ ] **Step 1: Write failing Storage tests**

Create `tests/test_session_bindings.py`:

```python
import sqlite3

import pytest

from storage import Storage


@pytest.fixture
def store(tmp_path):
    value = Storage(str(tmp_path / "graph.db"))
    yield value
    value.close()


def test_migration_creates_exact_binding_schema(store):
    cols = {row[1] for row in store.conn.execute("PRAGMA table_info(session_bindings)")}
    assert cols == {"run_key", "session_id", "bound_at"}


def test_bind_resolve_rebind_and_clear(store):
    store.bind_session("codex:10", "session-a")
    assert store.resolve_session_binding("codex:10") == "session-a"
    store.bind_session("codex:10", "session-b")
    assert store.resolve_session_binding("codex:10") == "session-b"
    store.clear_session_binding("codex:10", session_id="session-a")
    assert store.resolve_session_binding("codex:10") == "session-b"
    store.clear_session_binding("codex:10", session_id="session-b")
    assert store.resolve_session_binding("codex:10") is None


def test_concurrent_run_keys_are_isolated(store):
    store.bind_session("codex:10", "session-a")
    store.bind_session("codex:11", "session-b")
    assert store.resolve_session_binding("codex:10") == "session-a"
    assert store.resolve_session_binding("codex:11") == "session-b"


def test_binding_operations_fail_open_without_table(store):
    store.conn.execute("DROP TABLE session_bindings")
    store.bind_session("codex:10", "session-a")
    assert store.resolve_session_binding("codex:10") is None
    store.clear_session_binding("codex:10")


def test_empty_binding_inputs_are_noops(store):
    store.bind_session("", "session-a")
    store.bind_session("codex:10", "")
    assert store.conn.execute("SELECT COUNT(*) FROM session_bindings").fetchone()[0] == 0


def test_malformed_binding_payload_is_swallowed(store):
    store.bind_session(object(), "session-a")
    assert store.resolve_session_binding("codex:missing") is None
```

- [ ] **Step 2: Run the Storage tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_session_bindings.py -v`

Expected: FAIL because `session_bindings` and the three methods do not exist.

- [ ] **Step 3: Add migration 024**

Create `migrations/024_session_bindings.sql`:

```sql
-- Runtime-only bridge between Codex hook identity and its stdio MCP process.
-- Never rendered in a working surface; durable provenance remains in session_registry.
CREATE TABLE IF NOT EXISTS session_bindings (
    run_key    TEXT PRIMARY KEY,
    session_id TEXT NOT NULL,
    bound_at   TEXT NOT NULL
);
```

- [ ] **Step 4: Implement the Storage contract**

Add after `stamp_session_registry` in `storage.py`:

```python
    def bind_session(self, run_key: str, session_id: str) -> None:
        if not run_key or not session_id:
            return
        try:
            self.conn.execute(
                "INSERT INTO session_bindings (run_key, session_id, bound_at) "
                "VALUES (?, ?, ?) ON CONFLICT(run_key) DO UPDATE SET "
                "session_id = excluded.session_id, bound_at = excluded.bound_at",
                (run_key, session_id, _now_iso()),
            )
            self.conn.commit()
        except sqlite3.Error:
            logger.debug("session binding skipped", exc_info=True)

    def resolve_session_binding(self, run_key: str) -> str | None:
        if not run_key:
            return None
        try:
            row = self.conn.execute(
                "SELECT session_id FROM session_bindings WHERE run_key = ?",
                (run_key,),
            ).fetchone()
            return row["session_id"] if row else None
        except sqlite3.Error:
            logger.debug("session binding lookup skipped", exc_info=True)
            return None

    def clear_session_binding(self, run_key: str, session_id: str | None = None) -> None:
        if not run_key:
            return
        try:
            if session_id:
                self.conn.execute(
                    "DELETE FROM session_bindings WHERE run_key = ? AND session_id = ?",
                    (run_key, session_id),
                )
            else:
                self.conn.execute("DELETE FROM session_bindings WHERE run_key = ?", (run_key,))
            self.conn.commit()
        except sqlite3.Error:
            logger.debug("session binding cleanup skipped", exc_info=True)
```

- [ ] **Step 5: Run the Storage tests to verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_session_bindings.py tests/test_storage_registry.py -v`

Expected: all tests PASS.

- [ ] **Step 6: Write failing harness-adapter tests**

Append to `tests/test_harness.py`:

```python
def test_codex_context_carries_run_key(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _fake_stdin(monkeypatch, CODEX_PAYLOAD)
    assert harness.read_context()["run_key"] == "codex:42"


def test_claude_context_ignores_inherited_run_key(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "claude-code")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _fake_stdin(monkeypatch, {"session_id": "claude-session"})
    assert harness.read_context()["run_key"] is None


def test_raw_binding_helpers_round_trip(monkeypatch):
    conn = sqlite3.connect(":memory:")
    conn.execute(
        "CREATE TABLE session_bindings (run_key TEXT PRIMARY KEY, "
        "session_id TEXT NOT NULL, bound_at TEXT NOT NULL)"
    )
    ctx = {"run_key": "codex:42", "session_id": "cx-session"}
    harness.bind_session(conn, ctx)
    assert conn.execute(
        "SELECT session_id FROM session_bindings WHERE run_key='codex:42'"
    ).fetchone()[0] == "cx-session"
    harness.clear_session_binding(conn, ctx)
    assert conn.execute("SELECT COUNT(*) FROM session_bindings").fetchone()[0] == 0


def test_raw_binding_helpers_fail_open_without_table(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "pre-migration.db"))
    ctx = {"run_key": "codex:42", "session_id": "cx-session"}
    harness.bind_session(conn, ctx)
    harness.clear_session_binding(conn, ctx)
    conn.close()
```

- [ ] **Step 7: Run harness tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_harness.py -v`

Expected: FAIL because `run_key`, `bind_session`, and `clear_session_binding` do not exist.

- [ ] **Step 8: Implement raw hook binding helpers**

In `hooks/harness.py`, add `run_key` to `read_context()` only for Codex:

```python
        "run_key": os.environ.get("ENGRAM_RUN_KEY") if harness == CODEX else None,
```

Add:

```python
def bind_session(conn, ctx: dict) -> None:
    run_key = ctx.get("run_key")
    session_id = ctx.get("session_id")
    if not run_key or not session_id:
        return
    try:
        conn.execute(
            "INSERT INTO session_bindings (run_key, session_id, bound_at) "
            "VALUES (?, ?, ?) ON CONFLICT(run_key) DO UPDATE SET "
            "session_id = excluded.session_id, bound_at = excluded.bound_at",
            (run_key, session_id, datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except sqlite3.Error:
        pass


def clear_session_binding(conn, ctx: dict) -> None:
    run_key = ctx.get("run_key")
    session_id = ctx.get("session_id")
    if not run_key:
        return
    try:
        conn.execute(
            "DELETE FROM session_bindings WHERE run_key = ? AND session_id = ?",
            (run_key, session_id),
        )
        conn.commit()
    except sqlite3.Error:
        pass
```

- [ ] **Step 9: Run binding unit tests**

Run: `.venv/bin/python -m pytest tests/test_session_bindings.py tests/test_storage_registry.py tests/test_harness.py -v`

Expected: all tests PASS.

- [ ] **Step 10: Commit Task 2**

```bash
git add migrations/024_session_bindings.sql storage.py hooks/harness.py tests/test_session_bindings.py tests/test_harness.py
git commit -m "feat(provenance): add runtime session binding store"
```

---

### Task 3: Bind Wake and Make Sleep Fully Fail-Open

**Files:**
- Modify: `hooks/wake.py:20,159`
- Modify: `hooks/sleep.py:20-23,132-204`
- Modify: `tests/test_wake.py`
- Modify: `tests/test_nudge_harness.py`

**Interfaces:**
- Consumes: `bind_session(conn, ctx)` and `clear_session_binding(conn, ctx)` from Task 2.
- Produces: authoritative SessionStart binding, Stop cleanup, and guaranteed connection closure on extension-load failure.

- [ ] **Step 1: Write a failing wake integration test**

Add to the Codex wake section in `tests/test_wake.py`:

```python
def test_codex_wake_binds_run_key(tmp_path):
    db_path = _seed_db(tmp_path)
    output = _run_wake_raw(
        str(tmp_path),
        extra_env={"ENGRAM_HARNESS": "codex", "ENGRAM_RUN_KEY": "codex:42"},
        stdin=json.dumps({
            "session_id": "codex-hook-session",
            "hook_event_name": "SessionStart",
            "model": "gpt-5.6-sol",
            "cwd": str(tmp_path),
        }),
    )
    assert output.startswith("# Engram")
    conn = sqlite3.connect(db_path)
    row = conn.execute(
        "SELECT session_id FROM session_bindings WHERE run_key = 'codex:42'"
    ).fetchone()
    conn.close()
    assert row == ("codex-hook-session",)
```

- [ ] **Step 2: Run the wake test to verify RED**

Run: `.venv/bin/python -m pytest tests/test_wake.py::test_codex_wake_binds_run_key -v`

Expected: FAIL because wake does not call `bind_session`.

- [ ] **Step 3: Bind immediately after registry stamping**

Change the import in `hooks/wake.py`:

```python
from harness import bind_session, emit, read_context, stamp_registry
```

Immediately after `stamp_registry(conn, ctx)` add:

```python
    bind_session(conn, ctx)
```

- [ ] **Step 4: Run wake tests to verify GREEN**

Run: `.venv/bin/python -m pytest tests/test_wake.py -q`

Expected: all wake tests PASS.

- [ ] **Step 5: Write the failing sleep regression test**

Append to `tests/test_nudge_harness.py`:

```python
def test_sleep_extension_load_failure_closes_connection(
    tmp_path, monkeypatch, capsys,
):
    import types

    sleep = _load("sleep")
    db_path = tmp_path / ".engram" / "graph.db"
    db_path.parent.mkdir()
    db_path.touch()
    monkeypatch.setattr(sleep, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(sleep, "DB_PATH", db_path)
    monkeypatch.setattr(sleep, "PROJECT_ROOT", tmp_path)
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "session_id": "codex-hook-session", "hook_event_name": "Stop",
    })))

    class FakeConnection:
        def __init__(self):
            self.closed = False
            self.row_factory = None

        def execute(self, *_args, **_kwargs):
            return self

        def enable_load_extension(self, _enabled):
            pass

        def commit(self):
            pass

        def close(self):
            self.closed = True

    conn = FakeConnection()
    monkeypatch.setattr(sleep.sqlite3, "connect", lambda _path: conn)
    monkeypatch.setitem(sys.modules, "sqlite_vec", types.SimpleNamespace(
        load=lambda _conn: (_ for _ in ()).throw(RuntimeError("load failed"))
    ))

    sleep.sleep()

    assert conn.closed is True
    assert capsys.readouterr().out == ""


def test_sleep_clears_runtime_binding(tmp_path):
    db_path = _seed_episodes(tmp_path)
    from storage import Storage

    store = Storage(str(db_path), migrations_dir=MIGRATIONS_DIR)
    store.bind_session("codex:42", "codex-sleep-sess")
    store.close()

    result = _run_sleep(
        str(tmp_path),
        extra_env={
            "ENGRAM_HARNESS": "codex",
            "ENGRAM_RUN_KEY": "codex:42",
        },
        stdin=json.dumps({
            "session_id": "codex-sleep-sess", "hook_event_name": "Stop",
        }),
    )
    assert result.returncode == 0, result.stderr
    conn = sqlite3.connect(str(db_path))
    row = conn.execute(
        "SELECT session_id FROM session_bindings WHERE run_key = 'codex:42'"
    ).fetchone()
    conn.close()
    assert row is None
```

- [ ] **Step 6: Run the sleep regression to verify RED**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_nudge_harness.py::test_sleep_extension_load_failure_closes_connection \
  tests/test_nudge_harness.py::test_sleep_clears_runtime_binding -v
```

Expected: the extension-load test FAILS with `RuntimeError: load failed` and/or
`conn.closed is False`; the cleanup test FAILS because the binding remains.

- [ ] **Step 7: Expand sleep's fail-open boundary and cleanup binding**

Change the import in `hooks/sleep.py`:

```python
from harness import clear_session_binding, read_context
```

Replace `sleep()` with the complete function below:

```python
def sleep():
    ctx = read_context()
    if ctx["skip"]:
        return

    instance_name = _load_instance_config()
    db_path = DB_PATH
    if instance_name:
        instance_db = ENGRAM_HOME / ".engram" / "instances" / instance_name / "graph.db"
        if instance_db.exists():
            db_path = instance_db

    if not db_path.exists():
        return

    conn = None
    try:
        import sqlite_vec

        conn = sqlite3.connect(str(db_path))
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.enable_load_extension(True)
        sqlite_vec.load(conn)
        conn.enable_load_extension(False)
        conn.row_factory = sqlite3.Row

        has_residue = conn.execute(
            "SELECT name FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()
        if not has_residue:
            return

        episodes = conn.execute(
            "SELECT e.id, e.content FROM episodes e ORDER BY RANDOM() LIMIT ?",
            (DREAMS_PER_SLEEP,),
        ).fetchall()
        if not episodes:
            return

        for episode in episodes:
            vec_row = conn.execute(
                "SELECT embedding FROM episode_vectors WHERE id = ?",
                (episode["id"],),
            ).fetchone()
            if not vec_row:
                continue

            embedding = _unpack_embedding(vec_row["embedding"])
            residue = _distill_episode(episode["content"], embedding)
            conn.execute(
                "INSERT INTO residue (id, valence, fragments, created_at, session_id) "
                "VALUES (?, ?, ?, ?, ?)",
                (
                    residue["id"], residue["valence"], residue["fragments"],
                    residue["created_at"], ctx["session_id"] or None,
                ),
            )
            packed = struct.pack(
                f"<{len(residue['embedding'])}f", *residue["embedding"]
            )
            conn.execute(
                "INSERT INTO residue_vectors (id, embedding) VALUES (?, ?)",
                (residue["id"], packed),
            )

        conn.commit()
    except Exception:
        pass  # Stop hooks and dreams are non-critical.
    finally:
        if conn is not None:
            clear_session_binding(conn, ctx)
            conn.close()
```

- [ ] **Step 8: Run hook tests**

Run: `.venv/bin/python -m pytest tests/test_nudge_harness.py tests/test_wake.py tests/test_harness.py -q`

Expected: all tests PASS.

- [ ] **Step 9: Commit Task 3**

```bash
git add hooks/wake.py hooks/sleep.py tests/test_wake.py tests/test_nudge_harness.py
git commit -m "fix(hooks): bind wake identity and keep sleep fail-open"
```

---

### Task 4: Resolve the Bound Session in MCP Initialization

**Files:**
- Modify: `server.py:244-254`
- Modify: `tests/test_server_registry.py`

**Interfaces:**
- Consumes: `Storage.resolve_session_binding(run_key: str) -> str | None` from Task 2.
- Produces: `_session_id` equal to the hook session for bound Codex runs; unchanged Claude and UUID fallback behavior.

- [ ] **Step 1: Harden the server fixture's environment isolation**

In `engram_server_env`, add:

```python
    monkeypatch.delenv("ENGRAM_RUN_KEY", raising=False)
```

- [ ] **Step 2: Write failing bound-session and precedence tests**

Append to `tests/test_server_registry.py`:

```python
def _seed_bound_hook_row(server_module, run_key="codex:42", session_id="hook-session"):
    from storage import Storage

    db_path = server_module.DB_PATH
    db_path.parent.mkdir(parents=True, exist_ok=True)
    store = Storage(str(db_path))
    store.stamp_session_registry(
        session_id, harness="codex", model="gpt-5.6-sol", repo=str(server_module.PROJECT_ROOT)
    )
    store.bind_session(run_key, session_id)
    store.close()


def test_codex_init_adopts_bound_hook_session(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "hook-session"
    row = engram_server_env._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (engram_server_env._session_id,),
    ).fetchone()
    assert tuple(row) == ("codex", "gpt-5.6-sol", str(engram_server_env.PROJECT_ROOT))

    result = engram_server_env.remember(
        "Bound Codex session provenance probe", work=True
    )
    episode = engram_server_env._storage.get_episode(result["episode_id"])
    assert episode["session_id"] == "hook-session"


def test_codex_init_without_binding_generates_uuid(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:missing")
    engram_server_env._init()
    assert engram_server_env._session_id != ""
    assert engram_server_env._session_id != "hook-session"


def test_claude_session_id_wins_over_inherited_run_key(engram_server_env, monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "claude-code")
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-session")
    monkeypatch.setenv("ENGRAM_RUN_KEY", "codex:42")
    _seed_bound_hook_row(engram_server_env)
    engram_server_env._init()
    assert engram_server_env._session_id == "claude-session"
```

- [ ] **Step 3: Run server tests to verify RED**

Run: `.venv/bin/python -m pytest tests/test_server_registry.py -v`

Expected: `test_codex_init_adopts_bound_hook_session` FAILS because `_init()` generates a UUID.

- [ ] **Step 4: Implement ordered session resolution**

Replace the current `_session_id` assignment in `server.py` with:

```python
    harness = os.environ.get("ENGRAM_HARNESS", "claude-code")
    claude_session_id = os.environ.get("CLAUDE_SESSION_ID")
    bound_session_id = None
    if harness == "codex" and not claude_session_id:
        bound_session_id = _storage.resolve_session_binding(
            os.environ.get("ENGRAM_RUN_KEY", "")
        )
    _session_id = claude_session_id or bound_session_id or str(uuid.uuid4())
```

Use `harness` in the immediately following registry stamp:

```python
        harness=harness,
```

- [ ] **Step 5: Run server and provenance tests**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_server_registry.py tests/test_session_bindings.py \
  tests/test_storage_registry.py -q
```

Expected: all tests PASS.

- [ ] **Step 6: Run the combined Codex harness regression set**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_harness.py tests/test_wake.py tests/test_nudge_harness.py \
  tests/test_server_registry.py tests/test_session_bindings.py \
  tests/test_storage_registry.py -q
```

Expected: all tests PASS.

- [ ] **Step 7: Commit Task 4**

```bash
git add server.py tests/test_server_registry.py
git commit -m "fix(server): adopt Codex hook session binding"
```

---

### Task 5: Install the Measured Run Key in Codex Configuration

**Files:**
- Modify: `~/.codex/hooks.json`
- Modify: `~/.codex/config.toml`

**Interfaces:**
- Consumes: verified `$PPID` rule from Task 1 and binding code from Tasks 2-4.
- Produces: identical `ENGRAM_RUN_KEY` in hook and MCP subprocesses.

- [ ] **Step 1: Update all three hook launchers**

Preserve all descriptions, event names, and timeouts. Change only each command prefix:

```json
"command": "sh -c 'ENGRAM_HARNESS=codex ENGRAM_RUN_KEY=\"codex:$PPID\" python3 \"$HOME/Projects/engram/hooks/wake.py\"'"
```

Apply the same prefix to `nudge.py` and `sleep.py`.

- [ ] **Step 2: Update the Engram MCP launcher**

Replace only `command` and `args` under `[mcp_servers.engram]`:

```toml
command = "sh"
args = ["-c", 'ENGRAM_RUN_KEY="codex:$PPID" exec uv run --directory /Users/kairos/Projects/engram python server.py']
env = { ENGRAM_HOME = "/Users/kairos/Projects/engram", ENGRAM_HARNESS = "codex" }
startup_timeout_sec = 30
```

Keep existing per-tool approval modes unchanged.

- [ ] **Step 3: Validate both configuration files**

Run:

```bash
.venv/bin/python -c "import json; json.load(open('/Users/kairos/.codex/hooks.json')); print('hooks json ok')"
.venv/bin/python -c "import tomllib; tomllib.load(open('/Users/kairos/.codex/config.toml','rb')); print('codex toml ok')"
codex mcp list
```

Expected: both parse messages print, and `engram` is listed as enabled.

- [ ] **Step 4: Re-approve the changed hooks**

Start `codex` in any directory. The hook review must list wake, nudge, and sleep because their trusted hashes changed. Approve all three deliberately, then exit.

- [ ] **Step 5: Confirm the three new trusted hashes exist**

Run:

```bash
rg -n "session_start|user_prompt_submit|stop|trusted_hash" ~/.codex/config.toml
```

Expected: all three hook-state entries have a `trusted_hash` matching the new commands.

---

### Task 6: Full Verification and Task 8 Acceptance

**Files:**
- Modify if results require documentation only: `docs/superpowers/plans/2026-07-11-engram-codex-harness.md`

**Interfaces:**
- Consumes: completed code and machine configuration from Tasks 1-5.
- Produces: fresh automated and live evidence that both blockers are closed without regressing Claude or reviewer isolation.

- [ ] **Step 1: Run the full test suite**

Run: `.venv/bin/python -m pytest tests/ -q`

Expected: all tests PASS with zero failures.

- [ ] **Step 2: Verify the sleep failure directly**

Run:

```bash
.venv/bin/python -m pytest \
  tests/test_nudge_harness.py::test_sleep_extension_load_failure_closes_connection -v
```

Expected: PASS; no stdout from the hook.

- [ ] **Step 3: Start a fresh interactive Codex session**

This must be a new process so it loads the new MCP command and trusted hook hashes. Start from `/Users/kairos/Projects/engram` and verify orientation appears before the first response.

- [ ] **Step 4: Exercise MCP identity and write path**

In that session call `status()` and record its `session_id`, then call:

```text
remember("Task 8 post-fix identity probe", work=true, source="codex/task-8-post-fix")
```

Record the returned episode ID.

- [ ] **Step 5: Verify the probe joins the authoritative registry row**

Run against `.engram/instances/engram/graph.db`, substituting the recorded episode ID:

```sql
SELECT e.id, e.session_id, r.harness, r.model, r.repo
FROM episodes e
JOIN session_registry r USING (session_id)
WHERE e.id = '<episode-id>';
```

Expected: one row with the status session ID, `codex`, `gpt-5.6-sol`, and `/Users/kairos/Projects/engram`.

- [ ] **Step 6: Verify focus and reviewer isolation**

Submit a prompt using known instinct vocabulary and verify a `Thread:` line appears. Then run codex-pair review over `main...HEAD` and verify its transcript contains no `Memory Orientation`, `Thread:`, or `Echo:` text.

- [ ] **Step 7: Verify Claude continuity**

Start the next Claude Code session in the Engram repo. Verify wake remains unchanged and query the latest Claude row:

```sql
SELECT harness, model, repo
FROM session_registry
WHERE harness = 'claude-code'
ORDER BY started_at DESC
LIMIT 1;
```

Expected: `claude-code` and the correct repo; Claude's existing session-ID path is unchanged.

- [ ] **Step 8: Update Task 8 evidence and commit only if the plan document changes**

Mark the live checklist with the concrete episode/session evidence. If that edit is made:

```bash
git add docs/superpowers/plans/2026-07-11-engram-codex-harness.md
git commit -m "docs(plan): record passing Codex live acceptance"
```

- [ ] **Step 9: Run final branch verification**

Run:

```bash
git status --short
git log --oneline main..HEAD
.venv/bin/python -m pytest tests/ -q
```

Expected: clean worktree and full suite with zero failures. Then use `superpowers:finishing-a-development-branch`; do not merge before all live checks pass.
