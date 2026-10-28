"""Cross-references: text that names something staying home (store-copy spec I 6.4 item 1, D23)."""
import json
import sqlite3
import uuid
from pathlib import Path

import pytest

from imprint import main, make_plan, render_dry_run
from imprint_filter import CrossRef, cross_references, left_out_keys
from tests.imprint_support import (ctx, ep, inst, log_row, new_store, plan_args, plan_context, prune, selection, terms,
                                   vec, write_context)

FLAGS = ["--lanes", "work", "--layers", "episode,semantic", "--until", "2026-10-25T18:00:00Z"]

LEFT_OUT = {
    "episode": lambda s, key: ep(s, key, lane="personal"),
    "instinct": lambda s, key: inst(s, key),
    "residue": lambda s, key: s.conn.execute(
        "INSERT INTO residue (id, created_at) VALUES (?, '2026-01-01T00:00:00+00:00')", (key,)),
    "assessment": lambda s, key: s.conn.execute(
        "INSERT INTO assessments (id, status, scheduled_by, scheduled_at) VALUES (?, 'scheduled', 'user', "
        "'2026-01-01T00:00:00+00:00')", (key,)),
    "drift_report": lambda s, key: s.conn.execute(
        "INSERT INTO drift_reports (id, session_id, checked_at) VALUES (?, 'x', '2026-01-01T00:00:00+00:00')", (key,)),
    "memory_log": lambda s, key: log_row(s, session="x", at="2026-10-25T15:00:00+00:00", id=key),
}


def store_with_left_out(tmp_path, kind):
    s = new_store(tmp_path, "src")
    key = str(uuid.uuid4())
    LEFT_OUT[kind](s, key)
    s.conn.commit()
    return s, key


def session_text_store(tmp_path):
    s = new_store(tmp_path, "sess")
    sid = str(uuid.uuid4())
    s.conn.execute("INSERT INTO session_registry (session_id, started_at) VALUES (?, '2026-10-25T09:00:00+00:00')",
                   (sid,))
    ep(s, "e1", session=sid, at="2026-10-25T10:00:00+00:00")
    ep(s, "e2", session=sid, at="2026-10-25T10:05:00+00:00", content=f"written in {sid}")
    s.conn.commit()
    return s


def store_with_cold(tmp_path):
    import store_reader

    s = new_store(tmp_path, "src")
    key = str(uuid.uuid4())
    ep(s, key, at="2026-10-25T08:00:00+00:00")
    vec(s, "episode", key, seed=1)
    ep(s, "kept", content=f"it came from {key}", at="2026-10-25T09:00:00+00:00")
    prune(s, key)
    return s, store_reader.connect(Path(s.db_path).with_name("cold.db"), immutable=True)


def refs(s, sel, trm, cold=None):
    from imprint_filter import package_rows

    rows = package_rows(s.conn, sel, trm, ctx(s))
    return cross_references(rows, left_out_keys(s.conn, cold, rows))


@pytest.mark.parametrize("kind", ["episode", "instinct", "residue", "assessment", "drift_report", "memory_log"])
def test_text_naming_any_left_out_key_is_a_cross_reference_ignoring_case(tmp_path, kind):
    s, key = store_with_left_out(tmp_path, kind)
    ep(s, "names-it", content=f"see {key.upper()} for the rest")
    found = refs(s, selection(), terms())
    assert [c.id for c in found] == ["names-it"] and found[0].keys == 1
    assert key not in repr(found)


def test_a_shipped_session_id_in_a_kept_column_is_not_one_but_without_route_a_registered_session_is(tmp_path):
    s = session_text_store(tmp_path)
    assert refs(s, selection(), terms(route=True)) == []
    assert [c.id for c in refs(s, selection(), terms(route=False))] == ["e2"]


def test_exclude_clears_them_and_no_flag_keeps_one(tmp_path):
    s, key = store_with_left_out(tmp_path, "episode")
    ep(s, "names-it", content=key)
    ep(s, "keeper")
    assert refs(s, selection(exclude={"names-it", key}), terms()) == []
    from imprint import _parser
    flags = [a for act in _parser()._subparsers._group_actions[0].choices["plan"]._actions for a in act.option_strings]
    assert not any("keep" in a and "cross" in a for a in flags)


def test_cold_db_keys_count(tmp_path):
    s, cold = store_with_cold(tmp_path)
    try:
        assert [c.id for c in refs(s, selection(), terms(), cold)] == ["kept"]
        assert refs(s, selection(), terms(), None) == []
    finally:
        cold.close()


def test_a_shipped_memory_naming_a_shipped_one_is_no_cross_reference(tmp_path):
    s = new_store(tmp_path, "src")
    a = str(uuid.uuid4())
    ep(s, a, at="2026-10-25T08:00:00+00:00")
    ep(s, "b", content=f"after {a}", at="2026-10-25T09:00:00+00:00")
    s.conn.execute("INSERT INTO persistence_scores (episode_id, redundancy, uniqueness, generativity, computed_at) VALUES (?, 0, 0, 0, 'x')", (a,))
    s.conn.commit()
    assert refs(s, selection(), terms()) == []


def test_the_key_is_named_by_its_table_and_counted_once_per_token(tmp_path):
    s, key = store_with_left_out(tmp_path, "instinct")
    ep(s, "names-it", content=f"{key} and {key.upper()}")
    (c,) = refs(s, selection(), terms())
    assert c == CrossRef(table="instincts", id="names-it", keys=2)


def scratch_env(monkeypatch, home: Path, again: bool = False) -> Path:
    """What the re-executed process finds: a 0700 directory under home/imprints/plans named by three variables."""
    scratch = home / "imprints" / "plans" / "scratch-test"
    scratch.mkdir(parents=True, mode=0o700, exist_ok=again)
    for key in ("SQLITE_TMPDIR", "TMPDIR", "IMPRINT_SCRATCH"):
        monkeypatch.setenv(key, str(scratch))
    return scratch


def named_source(tmp_path):
    """plan_args' source, with episode e1 naming an instinct that stays home; returns (args, key)."""
    args = plan_args(tmp_path, owner="andy")
    key = str(uuid.uuid4())
    conn = sqlite3.connect(str(args[0]))
    with conn:
        conn.execute("INSERT INTO instincts (id, trigger, action, created_at) VALUES (?, 't', 'a', 'x')", (key,))
        conn.execute("UPDATE episodes SET content = ? WHERE id = 'e1'", (f"look at {key}",))
    conn.close()
    return args, key


def test_the_dry_run_counts_them_and_says_how_to_clear_them(tmp_path):
    args, key = named_source(tmp_path)
    plan = make_plan(*args)
    assert [(c.table, c.id) for c in plan.cross_references] == [("instincts", "e1")]
    text = render_dry_run(plan, plan_context("andy"))
    assert "Text that names something staying here: 1 episode." in text
    assert "--show-cross-references" in text and "--exclude FILE" in text and key not in text
    saved = json.loads((tmp_path / "home" / "imprints" / "plans" / f"{plan.id}.json").read_text())
    assert saved["cross_references"] == 1 and "e1" not in json.dumps(saved["cross_references"])


def test_no_cross_references_no_line(tmp_path):
    plan = make_plan(*plan_args(tmp_path, owner="andy"))
    assert plan.cross_references == () and "names something staying here" not in render_dry_run(plan, plan_context("andy"))


def test_the_flag_lists_each_memory_and_the_table_never_the_key(tmp_path, monkeypatch, capsys):
    args, key = named_source(tmp_path)
    home = tmp_path / "h"
    write_context(home, plan_context("andy"))
    scratch_env(monkeypatch, home)
    flags = ["plan", "--store", str(args[0]), "--engram-home", str(tmp_path / "eh2"), *FLAGS,
             "--audience", "place:home/andy", "--superyak-home", str(home)]
    assert main(flags) == 0
    quiet = capsys.readouterr().out
    assert "names something staying here: 1 episode" in quiet and "e1 names a key in instincts" not in quiet
    scratch_env(monkeypatch, home, again=True)
    assert main([*flags, "--show-cross-references"]) == 0
    out = capsys.readouterr().out
    assert "e1 names a key in instincts" in out and key not in out
