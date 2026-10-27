"""Sessions closed at t1, session ids and operation_log (store-copy spec I 5.2, 6.2, D7)."""
import imprint_filter
from imprint_filter import Scratch, Shipped, closed_sessions, episode_rows, operation_rows
from tests.imprint_support import (T, ep, footpath_store, log_row, new_store, op, selection, terms)

T1 = T("2026-10-25T18:00:00Z")


def shipped_all(s):
    """The work-lane memories, without going through admissible."""
    ids = lambda t: tuple(r[0] for r in s.conn.execute(f"SELECT id FROM {t} WHERE lane = 'work' ORDER BY id"))
    return Shipped(ids("episodes"), ids("semantics"))


def ops_store(tmp_path):
    s = new_store(tmp_path, "ops")
    ep(s, "k", session="s1", at="2026-10-25T15:00:00+00:00")
    ep(s, "p", lane="personal", session="s1", at="2026-10-25T15:00:00+00:00")
    ep(s, "q", session="s2", at="2026-10-25T17:30:00+00:00")
    op(s, "o-kept", session="s1", at="2026-10-25T15:30:00+00:00", operation="mark_core", targets=["k"],
       details={"why": "private"})
    op(s, "o-share", session="s1", at="2026-10-25T15:31:00+00:00", operation="share", targets=["k"])
    op(s, "o-outside", session="s1", at="2026-10-25T15:32:00+00:00", operation="mark_core", targets=["p"])
    op(s, "o-mixed", session="s1", at="2026-10-25T15:33:00+00:00", operation="instinct_feedback", targets=["k", "p"])
    op(s, "o-none", session="s1", at="2026-10-25T15:34:00+00:00", operation="dream_react", targets=[])
    op(s, "o-nosession", session=None, at="2026-10-25T15:35:00+00:00", operation="mark_core", targets=["k"])
    op(s, "o-after", session="s1", at="2026-10-25T18:30:00+00:00", operation="mark_core", targets=["k"])
    op(s, "o-open", session="s2", at="2026-10-25T17:30:00+00:00", operation="mark_core", targets=["k"])
    return s


def test_closed_at_t1_reads_every_row_kind_before_t1_only(tmp_path):
    s = new_store(tmp_path, "s")
    ep(s, "a", session="old", at="2026-10-25T16:00:00+00:00")
    ep(s, "b", session="late-log", at="2026-10-25T16:00:00+00:00")
    log_row(s, session="late-log", at="2026-10-25T17:30:00+00:00", event="cohesion_pass")
    ep(s, "c", session="late-op", at="2026-10-25T16:00:00+00:00")
    op(s, "o1", session="late-op", at="2026-10-25T17:10:00+00:00", operation="share", targets=["c"])
    ep(s, "d", session="after", at="2026-10-25T16:00:00+00:00"); ep(s, "e", session="after", at="2026-10-25T19:00:00+00:00")
    assert set(closed_sessions(s.conn, T1)) == {"old", "after"}


def test_closed_ignores_unparsable_times_and_bad_contexts_and_takes_a_scratch(tmp_path):
    s = new_store(tmp_path, "s")
    ep(s, "a", session="x", at="2026-10-25T10:00:00+00:00"); ep(s, "b", session="x", at="not a time")
    log_row(s, session=None, at="2026-10-25T10:00:00+00:00", context="not json")
    log_row(s, session=None, at="2026-10-25T10:00:00+00:00", context='{"session_id": 7}')
    log_row(s, session="y", at="2026-10-25T10:00:00+02:00")      # 08:00 UTC
    scratch = Scratch(tmp_path / "scratch.db")
    got = closed_sessions(s.conn, T1, scratch=scratch)
    assert set(got) == {"x", "y"}
    assert "x" in got and "z" not in got


def test_a_session_exactly_an_hour_before_t1_is_not_yet_closed(tmp_path):
    s = new_store(tmp_path, "s")
    ep(s, "a", session="edge", at="2026-10-25T17:00:00+00:00"); ep(s, "b", session="ok", at="2026-10-25T16:59:59+00:00")
    assert set(closed_sessions(s.conn, T1)) == {"ok"}


def test_session_ids_ship_only_with_route_and_only_for_closed_sessions(tmp_path):
    s = new_store(tmp_path, "s")
    ep(s, "w1", session="closed", at="2026-10-25T15:00:00+00:00"); ep(s, "w2", session="open", at="2026-10-25T17:30:00+00:00")
    sh, closed = Shipped(("w1", "w2"), ()), closed_sessions(s.conn, T1)
    assert [r["session_id"] for r in episode_rows(s.conn, sh, terms(route=False), closed)] == [None, None]
    assert [r["session_id"] for r in episode_rows(s.conn, sh, terms(route=True), closed)] == ["closed", None]
    assert "rowid" not in next(episode_rows(s.conn, sh, terms(route=True), closed))


def test_episode_rows_are_whole_in_created_at_then_id_order_and_only_the_shipped(tmp_path):
    s = new_store(tmp_path, "s")
    ep(s, "b", at="2026-10-25T10:00:00+00:00"); ep(s, "a", at="2026-10-25T10:00:00+00:00")
    ep(s, "c", at="2026-10-25T09:00:00+00:00"); ep(s, "z", at="2026-10-25T08:00:00+00:00")
    rows = list(episode_rows(s.conn, Shipped(("a", "b", "c"), ()), terms(), closed_sessions(s.conn, T1)))
    assert [r["id"] for r in rows] == ["c", "a", "b"]
    cols = [r[1] for r in s.conn.execute("PRAGMA table_info(episodes)")]
    assert list(rows[0]) == cols and rows[0]["content"] == "episode c"


def test_operation_rows_are_citing_closed_inside_m_and_scrubbed(tmp_path):
    s = ops_store(tmp_path)
    rows = list(operation_rows(s.conn, selection(until=T1), terms(route=True), closed_sessions(s.conn, T1), shipped_all(s)))
    assert [r["id"] for r in rows] == ["o-kept"]
    assert (rows[0]["harness"], rows[0]["model"], rows[0]["repo"], rows[0]["details"]) == (None, None, None, "{}")
    assert rows[0]["target_ids"] == '["k"]' and rows[0]["outcome"] == "ok"
    assert list(operation_rows(s.conn, selection(until=T1), terms(route=False), closed_sessions(s.conn, T1), shipped_all(s))) == []


def test_operation_rows_honour_the_window_start(tmp_path):
    s = ops_store(tmp_path)
    closed, sh = closed_sessions(s.conn, T1), shipped_all(s)
    late = selection(until=T1, since=T("2026-10-25T15:31:00Z"))
    assert list(operation_rows(s.conn, late, terms(route=True), closed, sh)) == []
    edge = selection(until=T1, since=T("2026-10-25T15:30:00Z"))
    assert [r["id"] for r in operation_rows(s.conn, edge, terms(route=True), closed, sh)] == ["o-kept"]


def test_no_footpath_rows_without_route(tmp_path):
    s = footpath_store(tmp_path)
    rows = list(episode_rows(s.conn, shipped_all(s), terms(route=False), closed_sessions(s.conn, T1)))
    assert len(rows) == 2 and all(r["session_id"] is None for r in rows)
