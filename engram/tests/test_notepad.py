"""Tests for the notepad — working reference graph."""
import pytest
from notepad import Notepad


@pytest.fixture
def pad(tmp_path):
    return Notepad(tmp_path / "notepad.db")


def test_jot_and_look(pad):
    """Basic jot and look."""
    pad.jot("embed", "NomicEmbedProvider, 768-dim")
    results = pad.look("embed")
    assert len(results) == 1
    assert results[0]["key"] == "embed"
    assert "768" in results[0]["value"]


def test_jot_updates_existing(pad):
    """Jotting same key updates the value."""
    pad.jot("embed", "old value")
    pad.jot("embed", "new value")
    results = pad.look("embed")
    assert len(results) == 1
    assert results[0]["value"] == "new value"


def test_jot_with_tags(pad):
    """Tags are stored and searchable."""
    pad.jot("emma db", "/sandbox/emma/engram.db", tags=["path", "emma"])
    results = pad.look("emma")
    assert len(results) == 1
    assert "path" in results[0]["tags"]


def test_look_searches_values(pad):
    """Look searches across values, not just keys."""
    pad.jot("embed", "NomicEmbedProvider, 768-dim, in embeddings.py")
    results = pad.look("768")
    assert len(results) == 1
    assert results[0]["key"] == "embed"


def test_look_substring_fallback(pad):
    """If FTS finds nothing, falls back to substring match."""
    pad.jot("add_episode", "no source param, context as dict")
    # Single character queries won't match FTS well, but substring will
    results = pad.look("add_episode")
    assert len(results) == 1


def test_look_co_session_neighbors(pad):
    """Notes from the same session surface alongside direct matches."""
    pad.jot("embed", "NomicEmbedProvider", session_id="s1")
    pad.jot("vectors", "episode_vectors, 768-dim", session_id="s1")
    pad.jot("unrelated", "something else", session_id="s2")

    results = pad.look("embed")
    keys = {r["key"] for r in results}
    assert "embed" in keys
    assert "vectors" in keys  # same session
    assert "unrelated" not in keys  # different session


def test_look_co_session_marks_nearby(pad):
    """Co-session neighbors are marked as 'nearby', not 'direct'."""
    pad.jot("a", "first note", session_id="s1")
    pad.jot("b", "second note", session_id="s1")

    results = pad.look("first")
    matches = {r["key"]: r["match"] for r in results}
    assert matches["a"] == "direct"
    assert matches["b"] == "nearby"


def test_erase(pad):
    """Erase removes a note."""
    pad.jot("tmp", "temporary")
    assert pad.count() == 1
    removed = pad.erase("tmp")
    assert removed is True
    assert pad.count() == 0


def test_erase_nonexistent(pad):
    """Erasing a nonexistent key returns False."""
    assert pad.erase("nope") is False


def test_erase_cleans_fts(pad):
    """Erased notes don't appear in FTS results."""
    pad.jot("secret", "hidden value")
    pad.erase("secret")
    results = pad.look("hidden")
    assert len(results) == 0


def test_access_count_incremented(pad):
    """Looking up a note bumps its access count."""
    pad.jot("freq", "frequently accessed")
    pad.look("freq")
    pad.look("freq")
    row = pad.conn.execute("SELECT accessed_count FROM notes WHERE key = 'freq'").fetchone()
    assert row[0] == 2


def test_empty_look(pad):
    """Looking in an empty notepad returns nothing."""
    results = pad.look("anything")
    assert results == []


def test_count(pad):
    """Count returns number of notes."""
    assert pad.count() == 0
    pad.jot("a", "1")
    pad.jot("b", "2")
    assert pad.count() == 2


# --- Planner extension tests ---

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
