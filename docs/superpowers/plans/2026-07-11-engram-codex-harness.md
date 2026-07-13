# Engram on Codex Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Interactive Codex CLI sessions wake into the same engram memory as Claude Code — full orientation, nudge, sleep, all MCP tools — with every write silently attributed to {harness, model, repo, time}.

**Architecture:** A thin harness adapter (`hooks/harness.py`) gives the existing wake/nudge/sleep scripts two I/O contracts selected explicitly by `ENGRAM_HARNESS`; a new `session_registry` table records silent provenance stamped by hooks (authoritative) and the MCP server (best-effort); registration is config-only on the Codex side (`~/.codex/hooks.json` in Claude Code's hooks format + one MCP server block).

**Tech Stack:** Python 3.14, sqlite3 (raw in hooks, `Storage` in server), pytest, Codex CLI ≥ 0.144.

**Spec:** `docs/superpowers/specs/2026-07-11-engram-codex-hooks-design.md` — read it first, especially "Probe findings".

## Global Constraints

- **Claude Code behavior must stay byte-identical when `ENGRAM_HARNESS` is unset.** These hooks run live from this working tree on every Claude Code session — every commit must leave them working.
- **The codex output path must NEVER emit JSON.** Codex parses JSON stdout as control flow (`{"continue": false}` kills the session). Plain text only.
- **The codex shim must never read `CLAUDE_*` env vars** (they leak into Codex children spawned from Claude sessions).
- **Provenance is never a gate:** registry failures (missing table, bad payload) must not block orientation or writes.
- **Attribution stays invisible:** no working surface (wake, recall, reflect, tool output) renders harness/model/repo. Time IS rendered (compact `YYYY-MM-DD`).
- Work on branch `feat/engram-codex-harness` in `~/Projects/engram` directly — NOT a worktree (hooks are machine-bound to this path; a worktree would leave live hooks running stale code and changes untestable live).
- Test command: `.venv/bin/python -m pytest tests/ -q` (full suite; 674 green before this plan).

---

### Task 1: session_registry migration + Storage helper

**Files:**
- Create: `migrations/023_session_registry.sql`
- Modify: `storage.py` (add one method to `Storage`, anywhere near `count_session_log_events`, ~line 1563)
- Test: `tests/test_storage_registry.py` (new)

**Interfaces:**
- Produces: table `session_registry(session_id TEXT PRIMARY KEY, harness TEXT, model TEXT, repo TEXT, started_at TEXT NOT NULL)`
- Produces: `Storage.stamp_session_registry(session_id: str, harness: str | None, model: str | None, repo: str | None) -> None`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_storage_registry.py
"""session_registry — silent provenance store (spec: 2026-07-11-engram-codex-hooks-design.md)."""
import pytest

from storage import Storage


@pytest.fixture
def store(tmp_path):
    s = Storage(str(tmp_path / "graph.db"))
    yield s
    s.close()


def test_migration_creates_table(store):
    cols = {r[1] for r in store.conn.execute("PRAGMA table_info(session_registry)")}
    assert cols == {"session_id", "harness", "model", "repo", "started_at"}


def test_stamp_inserts_row(store):
    store.stamp_session_registry("s1", harness="codex", model="gpt-5.6-sol", repo="/tmp/x")
    row = store.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id='s1'"
    ).fetchone()
    assert tuple(row) == ("codex", "gpt-5.6-sol", "/tmp/x")


def test_stamp_coalesce_merges_without_clobbering(store):
    # Server stamps first (no model), hook stamps later (has model):
    store.stamp_session_registry("s2", harness="codex", model=None, repo="/tmp/x")
    store.stamp_session_registry("s2", harness="codex", model="gpt-5.6-sol", repo="/should/not/clobber")
    row = store.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id='s2'"
    ).fetchone()
    assert row["model"] == "gpt-5.6-sol"   # NULL filled in
    assert row["repo"] == "/tmp/x"          # existing value kept


def test_stamp_empty_session_id_is_noop(store):
    store.stamp_session_registry("", harness="codex", model=None, repo=None)
    n = store.conn.execute("SELECT COUNT(*) FROM session_registry").fetchone()[0]
    assert n == 0
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_storage_registry.py -v`
Expected: FAIL — `session_registry` table absent / `Storage` has no attribute `stamp_session_registry`

- [ ] **Step 3: Write the migration**

```sql
-- migrations/023_session_registry.sql
-- Silent provenance: which harness/model/repo drove each session.
-- Never rendered in any working surface; post-analysis is SQL-only.
-- Spec: docs/superpowers/specs/2026-07-11-engram-codex-hooks-design.md
CREATE TABLE IF NOT EXISTS session_registry (
    session_id TEXT PRIMARY KEY,
    harness    TEXT,
    model      TEXT,
    repo       TEXT,
    started_at TEXT NOT NULL
);
```

- [ ] **Step 4: Add the Storage method**

In `storage.py`, add to the `Storage` class (near `count_session_log_events`):

```python
    def stamp_session_registry(
        self,
        session_id: str,
        harness: str | None = None,
        model: str | None = None,
        repo: str | None = None,
    ) -> None:
        """Upsert silent provenance for a session. COALESCE-merge: later
        stampers fill NULLs, never clobber. Provenance is never a gate —
        failures are swallowed."""
        if not session_id:
            return
        try:
            self.conn.execute(
                "INSERT INTO session_registry (session_id, harness, model, repo, started_at) "
                "VALUES (?, ?, ?, ?, ?) "
                "ON CONFLICT(session_id) DO UPDATE SET "
                "harness = COALESCE(session_registry.harness, excluded.harness), "
                "model = COALESCE(session_registry.model, excluded.model), "
                "repo = COALESCE(session_registry.repo, excluded.repo)",
                (session_id, harness, model, repo,
                 datetime.now(timezone.utc).isoformat()),
            )
            self.conn.commit()
        except sqlite3.Error:
            # Not just OperationalError: bad payloads must not gate either.
            logger.debug("session_registry stamp skipped", exc_info=True)
```

(`datetime`/`timezone`/`sqlite3`/`logger` are already imported/defined in storage.py.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_storage_registry.py -v`
Expected: 4 PASS

- [ ] **Step 6: Full suite, then commit**

Run: `.venv/bin/python -m pytest tests/ -q` — expected: all pass.

```bash
git add migrations/023_session_registry.sql storage.py tests/test_storage_registry.py
git commit -m "feat(provenance): session_registry table + COALESCE-merge stamp helper"
```

---

### Task 2: hooks/harness.py — the harness adapter

**Files:**
- Create: `hooks/harness.py`
- Test: `tests/test_harness.py` (new)

**Interfaces:**
- Produces: `read_context() -> dict` with keys `harness` (`"claude-code"` | `"codex"`), `session_id` (str), `model` (str | None), `cwd` (str), `prompt` (str | None), `event` (str | None), `skip` (bool)
- Produces: `emit(harness: str, event: str, text: str) -> None` — writes hook output to stdout in the harness's contract
- Produces: `stamp_registry(conn, ctx: dict) -> None` — raw-sqlite version of Task 1's upsert for hook processes
- Produces: module constants `CLAUDE = "claude-code"`, `CODEX = "codex"`

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_harness.py
"""Harness adapter: explicit shim selection, payload parsing, output contracts.

Codex clones Claude Code's hook payload format field-for-field (probe
2026-07-11), so selection is env-explicit — never sniffed from shape.
"""
import importlib.util
import io
import json
import sqlite3
from pathlib import Path

import pytest

_HOOKS = Path(__file__).resolve().parent.parent / "hooks"
_spec = importlib.util.spec_from_file_location("harness", _HOOKS / "harness.py")
harness = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(harness)

CODEX_PAYLOAD = {
    "session_id": "019f53e8-2d7b-7e40-b8bd-e24534d56bdb",
    "transcript_path": "/tmp/rollout.jsonl",
    "cwd": "/tmp/somerepo",
    "hook_event_name": "SessionStart",
    "model": "gpt-5.6-sol",
    "permission_mode": "bypassPermissions",
    "source": "startup",
}


def _fake_stdin(monkeypatch, payload):
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps(payload) if payload else ""))


def test_default_harness_is_claude(monkeypatch):
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-sess-1")
    _fake_stdin(monkeypatch, {})
    ctx = harness.read_context()
    assert ctx["harness"] == harness.CLAUDE
    assert ctx["session_id"] == "claude-sess-1"
    assert ctx["skip"] is False


def test_codex_reads_payload_not_claude_env(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    # CLAUDE_* env leaks into codex children — must be ignored:
    monkeypatch.setenv("CLAUDE_SESSION_ID", "leaked-claude-sess")
    monkeypatch.delenv("CODEX_PAIR_SESSION_ID", raising=False)
    _fake_stdin(monkeypatch, CODEX_PAYLOAD)
    ctx = harness.read_context()
    assert ctx["harness"] == harness.CODEX
    assert ctx["session_id"] == CODEX_PAYLOAD["session_id"]
    assert ctx["model"] == "gpt-5.6-sol"
    assert ctx["cwd"] == "/tmp/somerepo"
    assert ctx["event"] == "SessionStart"


def test_codex_pair_child_skips(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("CODEX_PAIR_SESSION_ID", "some-claude-session")
    _fake_stdin(monkeypatch, CODEX_PAYLOAD)
    assert harness.read_context()["skip"] is True


def test_engram_wake_skip_any_harness(monkeypatch):
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.setenv("ENGRAM_WAKE", "skip")
    _fake_stdin(monkeypatch, {})
    assert harness.read_context()["skip"] is True


def test_claude_pair_env_does_not_skip_claude(monkeypatch):
    # CODEX_PAIR_SESSION_ID is set in the *Claude* session too — must only
    # gate the codex shim, or Claude wake dies whenever codex-pair is loaded.
    monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
    monkeypatch.delenv("ENGRAM_WAKE", raising=False)
    monkeypatch.setenv("CODEX_PAIR_SESSION_ID", "some-claude-session")
    _fake_stdin(monkeypatch, {})
    assert harness.read_context()["skip"] is False


def test_malformed_stdin_degrades(monkeypatch):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.delenv("CODEX_PAIR_SESSION_ID", raising=False)
    monkeypatch.setattr("sys.stdin", io.StringIO("not json {"))
    ctx = harness.read_context()
    assert ctx["session_id"] == ""
    assert ctx["skip"] is False  # provenance degrades; wake still happens


def test_emit_claude_is_envelope(monkeypatch, capsys):
    harness.emit(harness.CLAUDE, "SessionStart", "hello")
    out = json.loads(capsys.readouterr().out)
    assert out["systemMessage"] == "hello"
    assert out["hookSpecificOutput"]["hookEventName"] == "SessionStart"
    assert out["hookSpecificOutput"]["additionalContext"] == "hello"


def test_emit_codex_is_plain_text_never_json(capsys):
    harness.emit(harness.CODEX, "SessionStart", "orientation text")
    out = capsys.readouterr().out
    assert out == "orientation text"
    with pytest.raises(ValueError):
        json.loads(out)  # MUST not parse as JSON — Codex treats JSON as control flow


def test_emit_empty_writes_nothing(capsys):
    harness.emit(harness.CODEX, "SessionStart", "")
    assert capsys.readouterr().out == ""


def test_stamp_registry_upserts_and_tolerates_missing_table(tmp_path):
    conn = sqlite3.connect(str(tmp_path / "t.db"))
    ctx = {"session_id": "s1", "harness": "codex", "model": "gpt-5.6-sol", "cwd": "/r"}
    harness.stamp_registry(conn, ctx)  # no table yet — must not raise
    conn.execute(
        "CREATE TABLE session_registry (session_id TEXT PRIMARY KEY, harness TEXT,"
        " model TEXT, repo TEXT, started_at TEXT NOT NULL)"
    )
    harness.stamp_registry(conn, ctx)
    harness.stamp_registry(conn, {"session_id": "s1", "harness": "codex", "model": None, "cwd": "/other"})
    row = conn.execute("SELECT model, repo FROM session_registry WHERE session_id='s1'").fetchone()
    assert row == ("gpt-5.6-sol", "/r")  # merge never clobbers
    harness.stamp_registry(conn, {"session_id": "", "harness": "codex", "model": None, "cwd": None})
    assert conn.execute("SELECT COUNT(*) FROM session_registry").fetchone()[0] == 1
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_harness.py -v`
Expected: FAIL — `hooks/harness.py` does not exist (FileNotFoundError at import)

- [ ] **Step 3: Write hooks/harness.py**

```python
#!/usr/bin/env python3
"""Harness adapter — one orientation logic, two harness I/O contracts.

Claude Code and Codex CLI both deliver hook payloads as JSON on stdin in
the SAME format (Codex cloned Claude Code's hooks API — probe-verified
2026-07-11). Because the shapes are indistinguishable, the shim is
selected EXPLICITLY via ENGRAM_HARNESS in the registered command line,
never sniffed.

Output contracts differ:
- claude-code: JSON envelope (systemMessage + hookSpecificOutput).
- codex: plain stdout. NEVER JSON — Codex parses JSON stdout as control
  flow ({"continue": false} kills the session).

Spec: docs/superpowers/specs/2026-07-11-engram-codex-hooks-design.md
"""

import json
import os
import sqlite3
import sys
from datetime import datetime, timezone

CLAUDE = "claude-code"
CODEX = "codex"


def read_context() -> dict:
    """Parse harness selection + hook payload into one dict.

    Never raises: a malformed payload degrades to empty provenance fields.
    Orientation must still happen — provenance is optional, wake is not.
    """
    harness = os.environ.get("ENGRAM_HARNESS", CLAUDE)

    raw = ""
    try:
        if not sys.stdin.isatty():  # manual runs keep working
            raw = sys.stdin.read()
    except Exception:
        pass
    try:
        payload = json.loads(raw) if raw and raw.strip() else {}
        if not isinstance(payload, dict):
            payload = {}
    except ValueError:
        payload = {}

    if harness == CODEX:
        # Never read CLAUDE_* env here: a codex child spawned from a
        # Claude session inherits them (probe-observed leak).
        session_id = payload.get("session_id") or ""
    else:
        session_id = os.environ.get("CLAUDE_SESSION_ID") or payload.get("session_id") or ""

    skip = os.environ.get("ENGRAM_WAKE", "").lower() == "skip"
    if harness == CODEX and os.environ.get("CODEX_PAIR_SESSION_ID"):
        # codex-pair review child — reviews stay lean (spec decision 4).
        skip = True

    return {
        "harness": harness,
        "session_id": session_id,
        "model": payload.get("model"),
        "cwd": payload.get("cwd") or os.getcwd(),
        "prompt": payload.get("prompt"),
        "event": payload.get("hook_event_name"),
        "skip": skip,
    }


def emit(harness: str, event: str, text: str) -> None:
    """Write hook output to stdout in the harness's contract."""
    if not text:
        return
    if harness == CODEX:
        sys.stdout.write(text)
        return
    json.dump(
        {
            "systemMessage": text,
            "hookSpecificOutput": {
                "hookEventName": event,
                "additionalContext": text,
            },
        },
        sys.stdout,
    )


def stamp_registry(conn, ctx: dict) -> None:
    """Upsert silent provenance (raw-sqlite twin of
    Storage.stamp_session_registry). COALESCE-merge; started_at is kept
    from the first stamp. No-op without a session_id or before migration
    023 — provenance is never a gate."""
    if not ctx.get("session_id"):
        return
    try:
        conn.execute(
            "INSERT INTO session_registry (session_id, harness, model, repo, started_at) "
            "VALUES (?, ?, ?, ?, ?) "
            "ON CONFLICT(session_id) DO UPDATE SET "
            "harness = COALESCE(session_registry.harness, excluded.harness), "
            "model = COALESCE(session_registry.model, excluded.model), "
            "repo = COALESCE(session_registry.repo, excluded.repo)",
            (ctx["session_id"], ctx.get("harness"), ctx.get("model"),
             ctx.get("cwd"), datetime.now(timezone.utc).isoformat()),
        )
        conn.commit()
    except sqlite3.Error:
        # Not just OperationalError: bad payloads raise InterfaceError/
        # ProgrammingError and must not gate either ("provenance is never a gate").
        pass
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_harness.py -v`
Expected: 10 PASS

- [ ] **Step 5: Commit**

```bash
git add hooks/harness.py tests/test_harness.py
git commit -m "feat(harness): adapter for claude-code/codex hook I/O contracts"
```

---

### Task 3: wake.py speaks both harnesses

**Files:**
- Modify: `hooks/wake.py` (session_id sourcing at `wake()` top ~line 147-150; the three `json.dump(_hook_output(...))` call sites ~lines 169, 527, 531-533; add registry stamp after DB connect ~line 162)
- Test: `tests/test_wake.py` (append new tests; existing tests must stay green)

**Interfaces:**
- Consumes: `harness.read_context()`, `harness.emit()`, `harness.stamp_registry()` from Task 2
- Produces: wake orientation on both harnesses; `session_registry` row per oriented session

- [ ] **Step 1: Write the failing tests**

Append to `tests/test_wake.py`, following that file's existing fixture/import pattern for invoking `wake()` against a temp DB (reuse its existing helpers for DB setup; the tests below show the harness-specific assertions):

```python
class TestWakeHarnessAdapter:
    def test_codex_wake_emits_plain_text(self, seeded_db, monkeypatch, capsys):
        # seeded_db: this file's existing fixture giving ENGRAM_HOME + populated graph.db
        monkeypatch.setenv("ENGRAM_HARNESS", "codex")
        monkeypatch.delenv("CODEX_PAIR_SESSION_ID", raising=False)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "session_id": "codex-sess-1", "cwd": "/tmp/r",
            "hook_event_name": "SessionStart", "model": "gpt-5.6-sol",
        })))
        wake_module.wake()
        out = capsys.readouterr().out
        assert "Memory Orientation" in out
        with pytest.raises(ValueError):
            json.loads(out)  # plain text — never JSON on the codex path

    def test_codex_wake_stamps_registry(self, seeded_db, monkeypatch, capsys):
        monkeypatch.setenv("ENGRAM_HARNESS", "codex")
        monkeypatch.delenv("CODEX_PAIR_SESSION_ID", raising=False)
        monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
            "session_id": "codex-sess-2", "cwd": "/tmp/r",
            "hook_event_name": "SessionStart", "model": "gpt-5.6-sol",
        })))
        wake_module.wake()
        conn = sqlite3.connect(seeded_db)  # path to the temp graph.db
        row = conn.execute(
            "SELECT harness, model, repo FROM session_registry WHERE session_id='codex-sess-2'"
        ).fetchone()
        assert row == ("codex", "gpt-5.6-sol", "/tmp/r")

    def test_skip_emits_nothing(self, seeded_db, monkeypatch, capsys):
        monkeypatch.setenv("ENGRAM_HARNESS", "codex")
        monkeypatch.setenv("CODEX_PAIR_SESSION_ID", "parent-claude-sess")
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
        wake_module.wake()
        assert capsys.readouterr().out == ""

    def test_claude_wake_still_json_envelope(self, seeded_db, monkeypatch, capsys):
        monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
        monkeypatch.delenv("ENGRAM_WAKE", raising=False)
        monkeypatch.setenv("CLAUDE_SESSION_ID", "claude-sess-9")
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
        wake_module.wake()
        out = json.loads(capsys.readouterr().out)
        assert "hookSpecificOutput" in out
```

Note: the seeded_db fixture requires migration 023 to be present in the
temp DB. If test_wake.py builds its temp DB via `Storage(...)`, migration
023 applies automatically; if it hand-creates tables, add the
`session_registry` CREATE TABLE from Task 1 to the fixture.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_wake.py -v -k Harness`
Expected: FAIL — wake ignores ENGRAM_HARNESS (emits JSON envelope on codex path), no registry row

- [ ] **Step 3: Integrate the adapter into wake.py**

At the top of `hooks/wake.py` after the existing imports, add:

```python
sys.path.insert(0, str(Path(__file__).resolve().parent))
from harness import emit, read_context, stamp_registry
```

In `wake()`, replace:

```python
    now = datetime.now(timezone.utc).isoformat()
    session_id = os.environ.get("CLAUDE_SESSION_ID", "")
```

with:

```python
    now = datetime.now(timezone.utc).isoformat()
    ctx = read_context()
    if ctx["skip"]:
        return  # review children / explicit skip: no orientation, no output
    session_id = ctx["session_id"]
```

After the `conn.row_factory = sqlite3.Row` line, add:

```python
    stamp_registry(conn, ctx)
```

Replace all three output sites:
- `json.dump(_hook_output(assessment_marker), sys.stdout)` → `emit(ctx["harness"], "SessionStart", assessment_marker)`
- `json.dump(_hook_output(orientation), sys.stdout)` → `emit(ctx["harness"], "SessionStart", orientation)`
- the failure path `json.dump(_hook_output(f"Engram wake failed ..."), sys.stdout)` → `emit(ctx["harness"], "SessionStart", f"Engram wake failed ({e.__class__.__name__}: {e}). Memory tools still available.")`

Then delete the now-unused `_hook_output` function from wake.py.

- [ ] **Step 4: Run the full wake test file**

Run: `.venv/bin/python -m pytest tests/test_wake.py -v`
Expected: ALL pass — pre-existing tests prove the Claude path is unchanged.

- [ ] **Step 5: Full suite, live smoke test, commit**

Run: `.venv/bin/python -m pytest tests/ -q` — all pass.
Live smoke (Claude path, manual run — must print the JSON envelope):

```bash
ENGRAM_HOME=$HOME/Projects/engram ENGRAM_PROJECT_ROOT=$HOME/Projects/engram \
  .venv/bin/python hooks/wake.py < /dev/null | head -c 200
```

Expected: output starts with `{"systemMessage": "# Engram`.

```bash
git add hooks/wake.py tests/test_wake.py
git commit -m "feat(wake): harness adapter — codex plain-text orientation + registry stamp"
```

---

### Task 4: nudge.py and sleep.py speak both harnesses

**Files:**
- Modify: `hooks/nudge.py` (stdin parse ~line 101, envelope fn ~lines 88-95 and emit site ~line 631, `CLAUDE_SESSION_ID` reads at lines ~546 and ~620)
- Modify: `hooks/sleep.py` (`CLAUDE_SESSION_ID` read at line ~168; add context read + skip at top of its main function)
- Test: `tests/test_nudge_harness.py` (new; follow test_wake.py's module-loading pattern)

**Interfaces:**
- Consumes: `harness.read_context()`, `harness.emit()`, `harness.stamp_registry()`
- Produces: nudge Thread/Echo output on both harnesses; residue/episode writes carry the harness's session_id

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_nudge_harness.py
"""Nudge/sleep harness integration: session_id sourcing + output contract."""
import importlib.util
import io
import json
import sqlite3
from pathlib import Path

import pytest

_HOOKS = Path(__file__).resolve().parent.parent / "hooks"


def _load(name):
    spec = importlib.util.spec_from_file_location(name, _HOOKS / f"{name}.py")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def test_nudge_codex_skips_for_pair_child(monkeypatch, capsys):
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    monkeypatch.setenv("CODEX_PAIR_SESSION_ID", "parent")
    monkeypatch.setattr("sys.stdin", io.StringIO(json.dumps({
        "session_id": "cx1", "hook_event_name": "UserPromptSubmit",
        "prompt": "anything at all",
    })))
    nudge = _load("nudge")
    nudge.nudge()
    assert capsys.readouterr().out == ""


def test_sleep_codex_uses_payload_session_id(tmp_path, monkeypatch):
    # Arrange a minimal graph.db via Storage so sleep can dream from it,
    # then verify residues carry the codex session_id, not CLAUDE env.
    # (Set ENGRAM_HOME to tmp_path; seed >= 5 episodes with vectors using
    # the same seeding helper test_wake.py uses for its temp store.)
    ...  # see Step 1 note below
```

Note: write the sleep test with the exact same temp-store seeding helper
`tests/test_wake.py` already uses (episodes + episode_vectors). Assert:

```python
    row = conn.execute("SELECT session_id FROM residue ORDER BY created_at DESC LIMIT 1").fetchone()
    assert row[0] == "codex-sleep-sess"
```

with `CLAUDE_SESSION_ID` set to a decoy value in env, `ENGRAM_HARNESS=codex`,
and stdin carrying `{"session_id": "codex-sleep-sess", "hook_event_name": "Stop"}`.

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_nudge_harness.py -v`
Expected: FAIL — nudge emits JSON envelope / sleep records decoy CLAUDE session id

- [ ] **Step 3: Integrate**

`hooks/nudge.py`:
- After existing imports (it already does `sys.path.insert(0, str(ENGRAM_HOME))`), add:
  ```python
  sys.path.insert(0, str(Path(__file__).resolve().parent))
  from harness import emit, read_context, stamp_registry
  ```
- In `nudge()`, replace the raw `hook_input = json.loads(sys.stdin.read())` block:
  ```python
  ctx = read_context()
  if ctx["skip"]:
      return
  prompt = (ctx["prompt"] or "").strip()
  if not prompt:
      return
  ```
  (Adapt the variable name to whatever the function currently extracts from `hook_input` — keep all downstream logic identical.)
- After nudge opens its DB connection, add `stamp_registry(conn, ctx)`.
- Replace both `os.environ.get("CLAUDE_SESSION_ID", "")` occurrences with `ctx["session_id"]`.
- Replace the final `json.dump(_hook_output("\n".join(lines)), sys.stdout)` with `emit(ctx["harness"], "UserPromptSubmit", "\n".join(lines))` and delete nudge's local `_hook_output`.

`hooks/sleep.py`:
- Add the same two-line import block.
- At the top of its entry function: `ctx = read_context()` / `if ctx["skip"]: return`.
- Replace `os.environ.get("CLAUDE_SESSION_ID")` with `ctx["session_id"] or None`.
- Sleep produces no stdout — no emit call.

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_nudge_harness.py tests/test_wake.py -v`
Expected: ALL pass

- [ ] **Step 5: Full suite + commit**

Run: `.venv/bin/python -m pytest tests/ -q` — all pass.

```bash
git add hooks/nudge.py hooks/sleep.py tests/test_nudge_harness.py
git commit -m "feat(nudge,sleep): harness adapter — codex session identity + plain-text nudges"
```

---

### Task 5: server.py stamps its own session

**Files:**
- Modify: `server.py` (in `_init()`, immediately after `_session_id = os.environ.get("CLAUDE_SESSION_ID") or str(uuid.uuid4())` at ~line 244; `_storage` is constructed just before/around this point — place the stamp after BOTH exist)
- Test: `tests/test_server_registry.py` (new; follow the pattern existing server tests use to drive `_init` against a temp ENGRAM_HOME)

**Interfaces:**
- Consumes: `Storage.stamp_session_registry` (Task 1)
- Produces: registry row for every MCP server session: `harness` from `ENGRAM_HARNESS` env (default `claude-code`), `model` NULL, `repo` = `os.getcwd()`

- [ ] **Step 1: Write the failing test**

```python
# tests/test_server_registry.py
def test_init_stamps_server_session(engram_server_env, monkeypatch):
    # engram_server_env: the existing fixture pattern for a temp server init
    monkeypatch.setenv("ENGRAM_HARNESS", "codex")
    server._init()
    row = server._storage.conn.execute(
        "SELECT harness, model, repo FROM session_registry WHERE session_id = ?",
        (server._session_id,),
    ).fetchone()
    assert row["harness"] == "codex"
    assert row["model"] is None
    assert row["repo"]  # cwd recorded
```

(Use whatever fixture existing server tests use to run `_init()` in isolation; if none exists, initialize `Storage` + module globals directly the way `tests/test_wake.py` fakes its store.)

- [ ] **Step 2: Run test to verify it fails**

Run: `.venv/bin/python -m pytest tests/test_server_registry.py -v`
Expected: FAIL — no registry row

- [ ] **Step 3: Add the stamp**

In `server.py::_init()`, after `_session_id` is assigned and `_storage` exists:

```python
    # Silent provenance: server-side best-effort stamp. The hook-side stamp
    # (same session_id under Claude Code) is authoritative and fills model.
    _storage.stamp_session_registry(
        _session_id,
        harness=os.environ.get("ENGRAM_HARNESS", "claude-code"),
        model=None,
        repo=os.getcwd(),
    )
```

- [ ] **Step 4: Run test to verify it passes**

Run: `.venv/bin/python -m pytest tests/test_server_registry.py -v`
Expected: PASS

- [ ] **Step 5: Full suite + commit**

```bash
git add server.py tests/test_server_registry.py
git commit -m "feat(server): stamp session_registry at init — silent harness/repo provenance"
```

---

### Task 6: time visible in working surfaces

**Files:**
- Modify: `server.py` (recall result dict construction, the `result = {...}` block ~line 1070 where `created_at` is in scope)
- Modify: `hooks/wake.py` ("What you know" query ~line 196-199 + its display line ~line 318; residue display line ~line 409)
- Test: append to `tests/test_wake.py`; new `tests/test_recall_when.py`

**Interfaces:**
- Produces: recall results carry `when: "YYYY-MM-DD"` (omitted when created_at unknown); wake semantic lines end with the date; residue lines include the date.

- [ ] **Step 1: Write the failing tests**

```python
# tests/test_recall_when.py
def test_recall_results_carry_when(engram_server_env):
    # Store an episode, recall it, expect a compact date on the hit.
    server.remember(content="the sky over Barima-Waini")
    out = server.recall(query="sky Barima", uninvited=0)
    hits = [r for r in out["results"] if "sky over Barima" in r["content"]]
    assert hits and hits[0]["when"] == datetime.now(timezone.utc).isoformat()[:10]
```

Append to `tests/test_wake.py` (inside the harness test class or a new one):

```python
    def test_semantic_lines_show_date(self, seeded_db, monkeypatch, capsys):
        # seeded fixture stores semantics with created_at; wake must render [YYYY-MM-DD]
        monkeypatch.delenv("ENGRAM_HARNESS", raising=False)
        monkeypatch.setenv("CLAUDE_SESSION_ID", "s")
        monkeypatch.setattr("sys.stdin", io.StringIO("{}"))
        wake_module.wake()
        out = json.loads(capsys.readouterr().out)["systemMessage"]
        know = [l for l in out.splitlines() if l.startswith("- [fact") or l.startswith("- [preference")]
        assert know and re.search(r", \d{4}-\d{2}-\d{2}\]", know[0])
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `.venv/bin/python -m pytest tests/test_recall_when.py tests/test_wake.py -v -k "when or date"`
Expected: FAIL — no `when` key / no date in line

- [ ] **Step 3: Implement**

`server.py`, in the recall result construction (where `result = {"id": cid, ...}` is built and `created_at` is in scope):

```python
        if created_at:
            result["when"] = str(created_at)[:10]
```

`hooks/wake.py`:
- Semantics query gains the column: `SELECT content, kind, confidence, created_at FROM semantics ORDER BY confidence DESC LIMIT 20`
- Display line becomes:
  ```python
  for sem in recent_semantics:
      when = (sem["created_at"] or "")[:10]
      stamp = f", {when}" if when else ""
      lines.append(f"- [{sem['kind']}, confidence={sem['confidence']:.2f}{stamp}] {sem['content']}")
  ```
- Residue line becomes:
  ```python
  when = (r["created_at"] or "")[:10]
  stamp = f", {when}" if when else ""
  lines.append(f"- `{r['id'][:8]}` [{direction}{stamp}] {fragments}")
  ```

- [ ] **Step 4: Run tests to verify they pass**

Run: `.venv/bin/python -m pytest tests/test_recall_when.py tests/test_wake.py -v`
Expected: ALL pass

- [ ] **Step 5: Full suite + commit**

```bash
git add server.py hooks/wake.py tests/test_recall_when.py tests/test_wake.py
git commit -m "feat(display): time visible — recall hits carry when=, wake lines show dates"
```

---

### Task 7: registration — Codex config, Claude env tag, loom guard, framing move

No repo code; config files on this machine plus one loom commit. All hook
commands use the `sh -c '...'` form so the env prefix and `$HOME` expansion
work regardless of how Codex execs the command line.

- [ ] **Step 1: Create `~/.codex/hooks.json`** (file does not exist today — verify with `ls ~/.codex/hooks.json` first; if it exists, merge instead of overwrite):

```json
{
  "description": "Engram memory hooks — wake into memories, nudge mid-conversation, dream on exit. Machine-bound to the live store at ~/Projects/engram (same rationale as engram hooks/hooks.json). Interactive sessions only: codex-pair review children are skipped via CODEX_PAIR_SESSION_ID.",
  "hooks": {
    "SessionStart": [
      {"hooks": [{"type": "command", "command": "sh -c 'ENGRAM_HARNESS=codex python3 \"$HOME/Projects/engram/hooks/wake.py\"'", "timeout": 10}]}
    ],
    "UserPromptSubmit": [
      {"hooks": [{"type": "command", "command": "sh -c 'ENGRAM_HARNESS=codex python3 \"$HOME/Projects/engram/hooks/nudge.py\"'", "timeout": 10}]}
    ],
    "Stop": [
      {"hooks": [{"type": "command", "command": "sh -c 'ENGRAM_HARNESS=codex python3 \"$HOME/Projects/engram/hooks/sleep.py\"'", "timeout": 5}]}
    ]
  }
}
```

- [ ] **Step 2: Append the MCP server to `~/.codex/config.toml`**:

```toml

# ── Engram memory (spec: engram docs/superpowers/specs/2026-07-11-engram-codex-hooks-design.md) ──
[mcp_servers.engram]
command = "uv"
args = ["run", "--directory", "/Users/kairos/Projects/engram", "python", "server.py"]
env = { ENGRAM_HOME = "/Users/kairos/Projects/engram", ENGRAM_HARNESS = "codex" }
startup_timeout_sec = 30
```

- [ ] **Step 3: Move the reviewer framing out of global scope** (spec §6):
  1. `cat ~/.codex/quick.config.toml ~/.codex/deep.config.toml` — check whether either already sets `developer_instructions`.
  2. Into each profile file that lacks it, paste the exact `developer_instructions = """..."""` block currently in `~/.codex/config.toml` (the "You are a pair programmer for Claude Code..." block).
  3. Delete that block (and `personality = "pragmatic"` only if it also reads as reviewer framing — otherwise leave it) from `~/.codex/config.toml`.

- [ ] **Step 4: Tag Claude's MCP registration.** In `~/Projects/engram/.mcp.json`, add to the engram server env:

```json
"env": {
  "ENGRAM_HOME": "/Users/kairos/Projects/engram",
  "ENGRAM_HARNESS": "claude-code"
}
```

- [ ] **Step 5: Loom belt-and-suspenders.** In `~/Projects/loom/tooling/claude-code-plugins/codex-pair/scripts/`, find each script that invokes `codex exec` or the codex MCP (`grep -rln "codex" --include="*.sh" | xargs grep -l "exec\|review"`), and add near the top of each:

```bash
export ENGRAM_WAKE=skip  # reviewer children must not wake into engram
```

Commit in loom on main (matches loom's existing convention for this plugin):

```bash
cd ~/Projects/loom && git add tooling/claude-code-plugins/codex-pair/scripts/ && \
git commit -m "chore(codex-pair): export ENGRAM_WAKE=skip — reviewer children stay lean"
```

- [ ] **Step 6: Commit the .mcp.json change in engram**

```bash
cd ~/Projects/engram && git add .mcp.json && \
git commit -m "chore(mcp): tag Claude registration with ENGRAM_HARNESS for provenance"
```

---

### Task 8: trust approval + live verification (human-in-the-loop)

The trust step is Kairos's: hooks stay silently skipped until approved once
in the Codex TUI.

- [x] **Step 1 (Kairos): trust the hooks.** Run `codex` in any directory; the startup hooks review lists the three engram hooks; approve them. (Re-approval is needed any time the command strings change.)

- [ ] **Step 2: automated pre-check (before Kairos's session).** First apply migration 023 to the live store (Storage runs migrations on construction):

```bash
cd ~/Projects/engram && ENGRAM_HOME=$PWD .venv/bin/python -c "
import os
from config import resolve_db_path
from storage import Storage
Storage(str(resolve_db_path(os.environ['ENGRAM_HOME']))).close()
print('migrated')"
```

Then verify the codex wake path end-to-end without trust, using the bypass
flag. CRITICAL details learned in execution: (1) run with `env -u` — a codex
child spawned from a Claude session inherits `CODEX_PAIR_SESSION_ID`, which
would trip our own review-child gate and make wake skip; (2) run from a
directory WITH a `.engram/config.toml` instance config (e.g. the engram
repo) — instance routing is cwd-based BY DESIGN (per-project memory
instances), and from a bare directory wake correctly finds no store and
stays silent:

```bash
cd ~/Projects/engram && env -u CODEX_PAIR_SESSION_ID -u ENGRAM_WAKE \
  codex exec --skip-git-repo-check --dangerously-bypass-hook-trust \
  "What memory orientation were you given at session start? Quote its first heading." < /dev/null
```

Expected: the reply quotes `# Engram (…) — Memory Orientation`.

- [ ] **Step 3: live checklist (Kairos's interactive Codex session):**
  1. Orientation appears in first-turn context (self-verifying delivery).
  2. `status()` via engram MCP works; `remember()` a probe episode.
  3. Provenance row is correct and invisible:
     ```bash
     sqlite3 ~/Projects/engram/.engram/instances/*/graph.db \
       "SELECT harness, model, repo FROM session_registry ORDER BY started_at DESC LIMIT 3;"
     ```
     Expected: a `codex|gpt-5.6-sol|<cwd>` row; and the orientation text contains no harness/model/repo mention.
  4. A prompt using known instinct vocabulary surfaces a Thread line.
  5. Run a codex-pair review from Claude; its transcript contains no orientation.
  6. Next Claude Code session: wake unchanged, its registry row says `claude-code`.

  Post-fix acceptance evidence (2026-07-13, through `513a3ae`):

  - [x] A fresh bounded Codex process loaded `# Engram (engram) — Memory Orientation` before its response.
  - [x] `status()` returned session `019f5c04-4a5a-7470-8b17-f0ba93ceb05f`; `remember("Task 8 post-fix identity probe", work=true, source="codex/task-8-post-fix")` returned episode `06ffd1b5-9050-4f46-ab9c-397fa935d60b`.
  - [x] The authoritative episode/registry join is `codex | gpt-5.6-sol | /Users/kairos/Projects/engram`, and Stop removed the runtime binding.
  - [x] Familiar vocabulary emitted `Thread: when code changes affect a running MCP server so the user kn` (a separate fresh prompt also emitted the measurement-first Thread).
  - [x] The corrected codex-pair reviewer child used the working FNM Codex binary and returned no `Memory Orientation`, `Thread:`, or `Echo:` output. Its lean-skip finding was fixed in `513a3ae` and the fix re-review was clean.
  - [ ] A new human Claude Code session was not started by this automated acceptance. The existing Claude-ID precedence tests pass, but the next-session wake/registry observation remains human-only.

  The reviewer also noted that a first-use/new-store wake with no selected
  database cannot create a binding before MCP startup. That is the approved
  missing-binding/pre-migration fail-open path: MCP remains available under a
  generated UUID rather than inferring identity.

  Expanded acceptance evidence (2026-07-13, through `4bb6dc9`):

  - [x] Codex identity hardening rejects malformed run keys, ignores a decoy
    `CLAUDE_SESSION_ID`, and keeps Stop cleanup/close independently fail-open.
  - [x] MCP launcher now uses `uv run --project` with the absolute server path,
    preserving the caller's project cwd; the exact command passed a temporary
    non-Engram-cwd smoke check.
  - [x] Fresh status session `019f5ce9-28c9-7402-bef7-ae7245dbd464` and episode
    `53427a47-71bd-4249-ae77-c054f3e0d9d7` joined `codex | gpt-5.6-sol | /Users/kairos/Projects/engram`.
  - [x] The same session produced an `operation_log` row for `remember` with
    the episode target, source details, and `success` outcome; Stop left zero
    runtime bindings.
  - [x] Familiar vocabulary still surfaced `Thread: when don't engineer for
    what you can't measure yet`.
  - [x] Expanded codex-pair output contained no `Memory Orientation`,
    `Thread:`, or `Echo:` text; its two attribution findings were fixed and
    re-reviewed clean.
  - [ ] A new human Claude Code session remains the only unperformed
    continuity observation; existing Claude precedence tests pass.

- [ ] **Step 4: merge.** After the checklist passes, merge `feat/engram-codex-harness` to main per superpowers:finishing-a-development-branch.
