# Prism-Engram Bridge Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Connect prism gap topology to engram's uninvited memories, add recall queries to lens questions, extend notepad into a planner, and add a mandatory authorial intent lens.

**Architecture:** Four independent changes across engram (server.py, notepad.py), reader (reading_prism.py), and prism pack (~/.prism/packs/reading/). No shared abstractions — build clean, extract later if needed.

**Tech Stack:** Python, SQLite, engram MCP, prism TransitionGraph, Ollama

**Spec:** `docs/superpowers/specs/2026-03-26-prism-engram-bridge-design.md`

**Repos:** `~/Projects/engram` (Tasks 1-2), `~/Projects/reader` (Task 3), `~/.prism/packs/reading/` (Task 3)

---

### Task 1: Notepad planner extension

**Files:**
- Modify: `~/Projects/engram/notepad.py`
- Modify: `~/Projects/engram/server.py`
- Test: `~/Projects/engram/tests/test_notepad.py`

- [ ] **Step 1: Add columns to notepad schema**

In `notepad.py`, `_ensure_schema()`, after the CREATE TABLE, add migration for existing DBs:

```python
        # Planner extension — add status, depends_on, due if missing
        try:
            self.conn.execute("SELECT status FROM notes LIMIT 0")
        except sqlite3.OperationalError:
            self.conn.execute("ALTER TABLE notes ADD COLUMN status TEXT DEFAULT 'open'")
            self.conn.execute("ALTER TABLE notes ADD COLUMN depends_on TEXT")
            self.conn.execute("ALTER TABLE notes ADD COLUMN due TEXT")
            self.conn.commit()
```

Also update the CREATE TABLE to include these columns for fresh DBs:

```sql
CREATE TABLE IF NOT EXISTS notes (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    tags JSON,
    session_id TEXT,
    accessed_count INTEGER DEFAULT 0,
    status TEXT DEFAULT 'open',
    depends_on TEXT,
    due TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL
);
```

- [ ] **Step 2: Extend jot() with planner params**

Update `jot()` signature and implementation:

```python
    def jot(self, key: str, value: str, tags: list[str] | None = None,
            session_id: str | None = None, status: str = "open",
            depends_on: str | None = None, due: str | None = None) -> dict:
        """Write or update a note. Planner fields: status, depends_on, due."""
        now = _now_iso()
        tags_json = json.dumps(tags) if tags else None
        existing = self.conn.execute(
            "SELECT rowid FROM notes WHERE key = ?", (key,)
        ).fetchone()
        if existing:
            self.conn.execute(
                "UPDATE notes SET value = ?, tags = ?, session_id = ?, status = ?, "
                "depends_on = ?, due = ?, updated_at = ? WHERE key = ?",
                (value, tags_json, session_id, status, depends_on, due, now, key),
            )
        else:
            self.conn.execute(
                "INSERT INTO notes (key, value, tags, session_id, status, depends_on, due, "
                "created_at, updated_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (key, value, tags_json, session_id, status, depends_on, due, now, now),
            )
        self.conn.commit()
        return {"key": key, "value": value, "tags": tags, "status": status}
```

- [ ] **Step 3: Add planner query methods**

Add to Notepad class:

```python
    def open_items(self, tag: str | None = None) -> list[dict]:
        """All notes with status 'open', ordered by due date (nulls last)."""
        if tag:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'open' AND tags LIKE ? "
                "ORDER BY CASE WHEN due IS NULL THEN 1 ELSE 0 END, due",
                (f'%"{tag}"%',),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'open' "
                "ORDER BY CASE WHEN due IS NULL THEN 1 ELSE 0 END, due",
            ).fetchall()
        return [self._note_dict(r) for r in rows]

    def deferred_items(self, tag: str | None = None) -> list[dict]:
        """All notes with status 'deferred'."""
        if tag:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'deferred' AND tags LIKE ? "
                "ORDER BY updated_at DESC",
                (f'%"{tag}"%',),
            ).fetchall()
        else:
            rows = self.conn.execute(
                "SELECT * FROM notes WHERE status = 'deferred' ORDER BY updated_at DESC",
            ).fetchall()
        return [self._note_dict(r) for r in rows]

    def defer(self, key: str, reason: str | None = None) -> bool:
        """Set note status to deferred, optionally append reason."""
        now = _now_iso()
        if reason:
            self.conn.execute(
                "UPDATE notes SET status = 'deferred', "
                "value = value || '\n\nDeferred: ' || ?, updated_at = ? WHERE key = ?",
                (reason, now, key),
            )
        else:
            self.conn.execute(
                "UPDATE notes SET status = 'deferred', updated_at = ? WHERE key = ?",
                (now, key),
            )
        self.conn.commit()
        return self.conn.total_changes > 0

    def resolve(self, key: str) -> bool:
        """Set note status to done."""
        now = _now_iso()
        self.conn.execute(
            "UPDATE notes SET status = 'done', updated_at = ? WHERE key = ?",
            (now, key),
        )
        self.conn.commit()
        return self.conn.total_changes > 0

    def _note_dict(self, row) -> dict:
        """Convert a row to a note dict with parsed tags."""
        note = dict(row)
        note["tags"] = json.loads(note["tags"]) if note["tags"] else []
        return note
```

- [ ] **Step 4: Write tests**

Add to `~/Projects/engram/tests/test_notepad.py` (create if needed):

```python
"""Tests for notepad planner extension."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

from notepad import Notepad


def test_jot_with_status(tmp_path):
    pad = Notepad(tmp_path / "test.db")
    result = pad.jot("task-1", "Build the thing", status="open", due="2026-04-01")
    assert result["status"] == "open"


def test_open_items(tmp_path):
    pad = Notepad(tmp_path / "test.db")
    pad.jot("a", "first", status="open", due="2026-04-02")
    pad.jot("b", "second", status="open", due="2026-04-01")
    pad.jot("c", "done one", status="done")
    pad.jot("d", "deferred one", status="deferred")

    items = pad.open_items()
    assert len(items) == 2
    assert items[0]["key"] == "b"  # earlier due date first


def test_deferred_items(tmp_path):
    pad = Notepad(tmp_path / "test.db")
    pad.jot("a", "open", status="open")
    pad.jot("b", "deferred", status="deferred")

    items = pad.deferred_items()
    assert len(items) == 1
    assert items[0]["key"] == "b"


def test_defer(tmp_path):
    pad = Notepad(tmp_path / "test.db")
    pad.jot("task", "Build it", status="open")
    pad.defer("task", reason="Needs more data")

    items = pad.deferred_items()
    assert len(items) == 1
    assert "Needs more data" in items[0]["value"]


def test_resolve(tmp_path):
    pad = Notepad(tmp_path / "test.db")
    pad.jot("task", "Build it", status="open")
    pad.resolve("task")

    assert pad.open_items() == []


def test_depends_on(tmp_path):
    pad = Notepad(tmp_path / "test.db")
    pad.jot("task-1", "First thing", status="open")
    pad.jot("task-2", "Depends on first", status="open", depends_on="task-1")

    items = pad.open_items()
    dep = [i for i in items if i["key"] == "task-2"][0]
    assert dep["depends_on"] == "task-1"
```

- [ ] **Step 5: Run tests**

Run: `cd ~/Projects/engram && uv run pytest tests/test_notepad.py -v`
Expected: All pass.

- [ ] **Step 6: Update jot MCP tool in server.py**

In `server.py`, update the `jot()` MCP tool to accept new params:

```python
@mcp.tool()
def jot(key: str, value: str, tags: list[str] | None = None,
        scope: str = "project", status: str = "open",
        depends_on: str | None = None, due: str | None = None) -> dict:
    """Write a working note or plan item.

    Args:
        key: Short label.
        value: The content.
        tags: Optional tags for grouping.
        scope: "project" (default) or "global".
        status: "open" (default), "deferred", or "done".
        depends_on: Optional key of a note that blocks this one.
        due: Optional due date (ISO format).
    """
    _init()
    project_pad, global_pad = _get_notepads()
    pad = global_pad if scope == "global" else project_pad
    result = pad.jot(key, value, tags=tags, session_id=_session_id,
                     status=status, depends_on=depends_on, due=due)
    logger.info("Tool called: jot(key=%r, scope=%s, status=%s)", key, scope, status)
    return result
```

- [ ] **Step 7: Run all engram tests**

Run: `cd ~/Projects/engram && uv run pytest tests/ -q`
Expected: All pass.

- [ ] **Step 8: Commit**

```bash
cd ~/Projects/engram && git add notepad.py server.py tests/test_notepad.py
git commit -m "feat: notepad planner — status, depends_on, due, defer/resolve"
```

---

### Task 2: Gap-informed uninvited memories

**Files:**
- Modify: `~/Projects/engram/server.py`
- Test: `~/Projects/engram/tests/test_server.py`

- [ ] **Step 1: Add gap detection helper**

Add to `server.py` after the existing imports/globals:

```python
def _get_reading_gap_domains() -> list[str]:
    """Read the prism reading transition graph and find gap domains.

    Returns lens names with zero or lowest total weight — the perspectives
    attention never reaches.
    """
    import os
    db_path = os.environ.get(
        "PRISM_READING_TRANSITIONS_DB",
        str(Path.home() / ".prism" / "reading-transitions.db"),
    )
    if not Path(db_path).exists():
        return []

    try:
        from transitions import TransitionGraph
        graph = TransitionGraph(db_path)
        transitions = graph.all_transitions()
        graph.close()

        if not transitions:
            return []

        # Collect all known labels and their total outgoing weight
        all_labels = set()
        outgoing_weight: dict[str, float] = {}
        for t in transitions:
            all_labels.add(t["from_label"])
            all_labels.add(t["to_label"])
            outgoing_weight[t["from_label"]] = (
                outgoing_weight.get(t["from_label"], 0.0) + t["weight"]
            )

        # Labels with zero outgoing weight are the deepest gaps
        # (never led to anything — attention stopped there)
        # Then sort the rest by ascending weight
        scored = [(label, outgoing_weight.get(label, 0.0)) for label in all_labels]
        scored.sort(key=lambda x: x[1])

        # Return bottom 3
        return [name for name, _ in scored[:3]]

    except Exception:
        logger.debug("Reading gap detection failed", exc_info=True)
        return []
```

- [ ] **Step 2: Modify uninvited memory selection in recall()**

In the `recall()` function, find the uninvited memory block (starts around line 847). Replace:

```python
    # Uninvited memories: random distant samples for generative collisions
    if uninvited > 0:
        matched_ids = {r["id"] for r in results}
        try:
            uninvited_layers = (layer,) if layer else None
            distant = _storage.sample_distant_memories(
                embedding, matched_ids, k=uninvited, layers=uninvited_layers,
            )
```

With:

```python
    # Uninvited memories: gap-biased + pure random for generative collisions
    if uninvited > 0:
        matched_ids = {r["id"] for r in results}
        try:
            uninvited_layers = (layer,) if layer else None

            # Check for reading gap domains
            gap_domains = _get_reading_gap_domains()
            if gap_domains and uninvited > 1:
                # N-1 gap-biased, 1 pure random
                gap_query = " ".join(gap_domains)
                gap_embedding = _embeddings.embed([gap_query], prefix="search_query")[0]
                if gap_embedding:
                    # Blend gap embedding with original query (alpha=0.3)
                    import numpy as np
                    blended = np.array(embedding) * 0.7 + np.array(gap_embedding) * 0.3
                    blended = (blended / np.linalg.norm(blended)).tolist()

                    gap_distant = _storage.sample_distant_memories(
                        blended, matched_ids, k=uninvited - 1, layers=uninvited_layers,
                    )
                    pure_random = _storage.sample_distant_memories(
                        embedding, matched_ids | {d[0] for d in gap_distant},
                        k=1, layers=uninvited_layers,
                    )
                    distant = gap_distant + pure_random
                else:
                    distant = _storage.sample_distant_memories(
                        embedding, matched_ids, k=uninvited, layers=uninvited_layers,
                    )
            else:
                distant = _storage.sample_distant_memories(
                    embedding, matched_ids, k=uninvited, layers=uninvited_layers,
                )
```

- [ ] **Step 3: Run all tests**

Run: `cd ~/Projects/engram && uv run pytest tests/ -q`
Expected: All pass. Gap detection returns empty when no transition DB exists, so existing behavior is unchanged.

- [ ] **Step 4: Commit**

```bash
cd ~/Projects/engram && git add server.py
git commit -m "feat: gap-informed uninvited memories — prism topology biases recall"
```

---

### Task 3: Recall queries + authorial lens

**Files:**
- Create: `~/.prism/packs/reading/authorial.yaml`
- Modify: `~/.prism/packs/reading/pack.yaml`
- Modify: `~/Projects/reader/reading_prism.py`
- Test: `~/Projects/reader/tests/test_reading_prism.py`

- [ ] **Step 1: Create authorial lens**

```yaml
# ~/.prism/packs/reading/authorial.yaml
name: authorial
domain: craft
sources:
  - "Booth, The Rhetoric of Fiction (1961)"
  - "Iser, The Act of Reading (1978)"
prompt: |
  You are asking about authorial construction — what the writer
  is building and why.

  Given a passage and a reader's reaction, ask ONE question about
  what the author is doing on purpose. Not what the characters feel —
  what effect the text is designed to produce. How is this passage
  constructed to make the reader respond a certain way?

  Notice: pacing choices, information withheld or revealed, structural
  parallels to earlier passages, tone shifts, the gap between what
  characters know and what the reader knows, imagery that does work
  the prose doesn't name.
temperature: 0.8
model: null
```

- [ ] **Step 2: Update pack manifest**

Add `authorial.yaml` to `~/.prism/packs/reading/pack.yaml` frames list.

- [ ] **Step 3: Add recall_query and authorial slot to reading_prism.py**

In `_load_reading_lenses()`, also include `domain: "craft"` in the filter:

```python
        reading_domains = {
            "early-childhood-development", "literary-theory",
            "philosophy", "social-sciences", "sciences", "craft",
        }
```

In `run_reading_prism()`, after the classified lenses loop, add the mandatory authorial lens:

```python
    # Mandatory authorial lens — always fires, not classifier-routed
    authorial = lenses.get("authorial")
    if authorial:
        question = _ask_lens(authorial, context)
        if question:
            qid = store.store_prism_question(
                book_id=book_id,
                chunk_position=chunk_position,
                lens="authorial",
                question=question,
                selection_type="mandatory",
            )
            results.append({
                "id": qid,
                "lens": "authorial",
                "question": question,
                "selection_type": "mandatory",
                "recall_query": question,
            })
```

Also add `recall_query` to every result in the main loop — the raw question verbatim:

```python
        results.append({
            "id": qid,
            "lens": name,
            "question": question,
            "selection_type": selection_type,
            "recall_query": question,
        })
```

- [ ] **Step 4: Add tests**

Add to `~/Projects/reader/tests/test_reading_prism.py`:

```python
def test_recall_query_is_raw_question(tmp_path):
    from reading_prism import run_reading_prism

    store = ReadingStore(tmp_path / "test.db")

    with patch("reading_prism._classify") as mock_classify, \
         patch("reading_prism._ask_lens") as mock_ask:
        mock_classify.return_value = (["attachment"], "power", "formalist")
        mock_ask.side_effect = lambda lens, ctx: f"Question from {lens['name']}"

        lenses = {
            "attachment": {"name": "attachment", "prompt": "test", "domain": "early-childhood-development", "temperature": 0.8},
            "power": {"name": "power", "prompt": "test", "domain": "literary-theory", "temperature": 0.8},
            "formalist": {"name": "formalist", "prompt": "test", "domain": "literary-theory", "temperature": 0.8},
            "authorial": {"name": "authorial", "prompt": "test", "domain": "craft", "temperature": 0.8},
        }

        questions = run_reading_prism(
            store=store, book_id=1, chunk_position=42,
            passage="test", reaction="test", lenses=lenses,
        )

        # Should have classified lenses + authorial
        assert any(q["lens"] == "authorial" for q in questions)
        # Every question should have recall_query = raw question
        for q in questions:
            assert q["recall_query"] == q["question"]
```

- [ ] **Step 5: Run tests**

Run: `cd ~/Projects/reader && python3 -m pytest tests/ -v`
Expected: All pass.

- [ ] **Step 6: Commit**

```bash
cd ~/Projects/reader && git add reading_prism.py tests/test_reading_prism.py
git commit -m "feat: recall_query on lens questions + mandatory authorial lens"
```

---

### Task 4: Seed the planner with deferred items

**Files:** None — uses the MCP tools built in Task 1.

- [ ] **Step 1: Create deferred planner items**

After Task 1 is deployed and the MCP server restarted, use the `jot` tool to create:

```
jot("change-tracking",
    "Compare reactions before/after lens engagement to detect actual perceptual shift vs performed engagement. Sequential reactions are stored in reader, comparison is computable.",
    tags=["prism", "engram", "reading"],
    status="deferred",
    depends_on="reading-prism-live",
    scope="global")

jot("dream-from-lens-shifts",
    "Capture perceptual shifts from lens engagement as dream material. Not the question or answer but the shift itself. Compress like dream residue. Don't structure it — the combinatorial complexity without structure is the point.",
    tags=["engram", "dreams", "prism"],
    status="deferred",
    scope="global")

jot("memory-traversal",
    "Wander tool for walking the memory graph. Start at a memory, follow connections (resonances, source chains, shared tags, temporal proximity). Not recall (query → results) but exploration (start here → what's connected → follow a thread). Like reading Mistborn passage by passage but through your own episodes and semantics.",
    tags=["engram", "exploration"],
    status="deferred",
    scope="global")

jot("reading-prism-live",
    "Reading prism MCP server needs restart to pick up new code. Verify: react() runs prism, read() surfaces questions, prism_response flows to engram.",
    tags=["reader", "prism"],
    status="open",
    scope="global")
```

- [ ] **Step 2: Verify planner works**

Use `look` with scope="global" to see the items, or query by tag.

This is a manual step after the MCP server restarts.
