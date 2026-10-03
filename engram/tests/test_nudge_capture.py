"""Prompt capture against real migrations, with deterministic local embeddings."""

import hashlib
import math
import sqlite3
import sys
from types import SimpleNamespace

import pytest

from storage import Storage
from tests.test_nudge import _load_nudge_module


PROMPT = "Inspect the research evidence and record the limitations of this proposed experiment."
VECTOR = [1.0] + [0.0] * 767
OTHER_VECTOR = [0.0, 1.0] + [0.0] * 766


@pytest.fixture
def capture(tmp_path, monkeypatch):
    directory = tmp_path / ".engram"
    directory.mkdir()
    store = Storage(str(directory / "graph.db"))
    hook = _load_nudge_module()
    context = dict(skip=False, prompt=PROMPT, session_id="capture-session", harness="codex",
                   cwd=str(tmp_path), run_key=None, model="fixture")
    monkeypatch.setattr(hook, "read_context", lambda: context)
    monkeypatch.setattr(hook, "_load_instance_config", lambda: None)
    monkeypatch.setattr(hook, "DB_PATH", directory / "graph.db")
    monkeypatch.setattr(hook, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(hook, "PROJECT_ROOT", tmp_path)
    embedded = []

    class Embeddings:
        def __init__(self, **kwargs):
            tokenizer = SimpleNamespace(enable_truncation=lambda **_: None)
            self.model = SimpleNamespace(tokenizer=tokenizer)

        def embed(self, texts, **kwargs):
            texts = list(texts)
            embedded.extend(texts)
            return [VECTOR for _ in texts]

    monkeypatch.setitem(sys.modules, "fastembed", SimpleNamespace(TextEmbedding=Embeddings))
    yield SimpleNamespace(hook=hook, store=store, context=context, embedded=embedded)
    store.close()


def rows(capture):
    return [dict(row) for row in capture.store.conn.execute("SELECT * FROM episodes ORDER BY id")]


def seed_episode(capture, identifier, *, source=None, core=0, strength=0.01, vector=OTHER_VECTOR):
    capture.store.add_episode(identifier, "existing-session", "Existing " + identifier,
                              embedding=vector, lane="work")
    capture.store.conn.execute("UPDATE episodes SET source=?, core=?, decay_strength=? WHERE id=?",
                               (source, core, strength, identifier))
    capture.store.conn.commit()


def seed_echo(capture):
    capture.store.add_semantic("echo", "Keep the scientific scope explicit.", "fact", 0.8, VECTOR, [], lane="work")


def test_novel_prompt_persists_with_session_provenance_and_work_lane(capture, capsys):
    columns = {row[1] for row in capture.store.conn.execute("PRAGMA table_info(episodes)")}
    assert "source" in columns and "origin" not in columns
    capture.hook.nudge()
    episodes = rows(capture)
    assert len(episodes) == 1, capsys.readouterr().err
    episode = episodes[0]
    assert episode["content"] == PROMPT
    assert episode["source"] == "auto"
    assert episode["session_id"] == "capture-session"
    assert episode["lane"] == "work" and episode["core"] == 0
    assert episode["content_hash"] == hashlib.sha256(PROMPT.encode()).hexdigest()
    assert episode["decay_strength"] == 1.0
    vector = capture.store.conn.execute("SELECT embedding FROM episode_vectors WHERE id=?", (episode["id"],)).fetchone()
    assert capture.hook._unpack_embedding(vector[0]) == VECTOR
    registry = capture.store.conn.execute("SELECT harness, repo FROM session_registry WHERE session_id='capture-session'").fetchone()
    assert tuple(registry) == ("codex", capture.context["cwd"])


def test_replayed_and_similar_prompts_do_not_duplicate_capture(capture):
    capture.hook.nudge()
    capture.hook.nudge()
    capture.context["prompt"] = "A different wording about the same research evidence and proposed experiment limitations."
    capture.hook.nudge()
    assert len(rows(capture)) == 1
    assert capture.store.conn.execute("SELECT count(*) FROM episode_vectors").fetchone()[0] == 1


def test_existing_manual_memory_preserves_novelty_threshold(capture):
    similar = [0.7, math.sqrt(1 - 0.7**2)] + [0.0] * 766
    seed_episode(capture, "manual", vector=similar)
    capture.hook.nudge()
    assert [row["id"] for row in rows(capture)] == ["manual"]
    assert rows(capture)[0]["source"] is None


@pytest.mark.parametrize("prompt", ["", "short", "A short research question."])
def test_short_prompts_are_not_captured(capture, prompt):
    capture.context["prompt"] = prompt
    capture.hook.nudge()
    assert rows(capture) == []
    if len(prompt) < 10:
        assert capture.embedded == []


def test_vector_write_failure_rolls_back_capture_and_preserves_echo(capture, monkeypatch, capsys):
    seed_echo(capture)
    original_connect = sqlite3.connect
    denied = []

    def connect(*args, **kwargs):
        connection = original_connect(*args, **kwargs)

        def authorize(action, table, *_):
            if action == sqlite3.SQLITE_INSERT and table == "episode_vectors":
                denied.append(table)
                return sqlite3.SQLITE_DENY
            return sqlite3.SQLITE_OK

        connection.set_authorizer(authorize)
        return connection

    monkeypatch.setattr(capture.hook.sqlite3, "connect", connect)
    capture.hook.nudge()
    output = capsys.readouterr()
    assert "Echo: Keep the scientific scope explicit." in output.out
    assert denied == ["episode_vectors"]
    assert rows(capture) == []
    assert capture.store.conn.execute("SELECT count(*) FROM episode_vectors").fetchone()[0] == 0
    # Dream capture runs afterward and commits; it must not commit a partial episode.
    assert capture.store.conn.execute("SELECT count(*) FROM residue").fetchone()[0] == 1


def test_inline_pruning_is_bounded_and_preserves_manual_core_and_external(capture):
    for index in range(5):
        seed_episode(capture, f"auto-{index}", source="auto", strength=0.01 * (index + 1))
    seed_episode(capture, "manual")
    seed_episode(capture, "core", source="auto", core=1)
    seed_episode(capture, "external", source="external:atlas")
    seed_episode(capture, "strong", source="auto", strength=0.5)
    capture.context["prompt"] = "A short research question."
    capture.hook.nudge()
    assert {row["id"] for row in rows(capture)} == {"auto-3", "auto-4", "manual", "core", "external", "strong"}
    assert next(row for row in rows(capture) if row["id"] == "external")["source"] == "external:atlas"
    assert capture.store.conn.execute("SELECT count(*) FROM episode_vectors").fetchone()[0] == 6


def test_pruning_failure_rolls_back_all_deletions_and_still_emits_echo(capture, capsys):
    seed_echo(capture)
    for index in range(2):
        seed_episode(capture, f"auto-{index}", source="auto", strength=0.01 * (index + 1))
    capture.store.conn.execute("""CREATE TRIGGER refuse_second_auto BEFORE DELETE ON episodes
                              WHEN OLD.id = 'auto-1' BEGIN SELECT RAISE(ABORT, 'fixture failure'); END""")
    capture.store.conn.commit()
    capture.context["prompt"] = "A short research question."
    capture.hook.nudge()
    assert "Echo: Keep the scientific scope explicit." in capsys.readouterr().out
    assert {row["id"] for row in rows(capture)} == {"auto-0", "auto-1"}
    assert capture.store.conn.execute("SELECT count(*) FROM episode_vectors").fetchone()[0] == 2
    assert capture.store.conn.execute("SELECT count(*) FROM residue").fetchone()[0] == 1
