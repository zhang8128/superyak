"""Sessions closed at t1, session ids, operation_log and memory_log (store-copy spec I 5.2, 6.2, D7, D35)."""
import json

import imprint_filter
from imprint_filter import (Scratch, Shipped, closed_sessions, episode_rows, instinct_ids as _instinct_ids,
                            memory_log_rows, normalize_outcome, operation_rows)
from tests.imprint_support import (T, ep, footpath_store, inst, log_row, new_store, op, recall, route_shown,
                                   selection, terms)

MEMORY_LOG_COLUMNS = ("id", "timestamp", "event_type", "layer", "target_ids", "context", "outcome")

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


def instinct_ids(s):
    return _instinct_ids(s.conn, Scratch(":memory:"))


def rows_of(s):
    return list(memory_log_rows(s.conn, selection(until=T1), terms(route=True), closed_sessions(s.conn, T1),
                                shipped_all(s), instinct_ids(s)))


def recall_rows_of(s):
    return [r for r in rows_of(s) if r["event_type"] == "recall"]


def _log_base(tmp_path, name):
    s = new_store(tmp_path, name)
    ep(s, "e1", session="s1", at="2026-10-25T09:00:00+00:00")
    ep(s, "e2", session="s1", at="2026-10-25T09:01:00+00:00")
    ep(s, "e3", session="s1", at="2026-10-25T09:02:00+00:00")
    ep(s, "e-home", lane="personal", session="s1", at="2026-10-25T09:03:00+00:00")
    inst(s, "i1")
    return s


def recall_store(tmp_path, outcomes=None, query=None, extra=()):
    s = _log_base(tmp_path, "recall")
    if outcomes is None:
        for n, targets in enumerate([["e1", "i1"], ["e1", "e-home"], ["i1"], ["e1", "e2"]]):
            recall(s, f"rc{n}", targets=targets, at=f"2026-10-25T15:0{n}:00+00:00")
    else:
        for n, outcome in enumerate(outcomes):
            recall(s, f"rc{n}", targets=["e1"], at=f"2026-10-25T15:0{n}:00+00:00", outcome=outcome,
                   recall_id=f"rid{n}", query=query, note="Jenn")
    for id, at in extra:
        recall(s, id, targets=["e1"], at=at, session="s1" if id == "after-t1" else "open-s")
    return s


def route_shown_store(tmp_path):
    s = _log_base(tmp_path, "shown")
    route_shown(s, "rs0", targets=["e3", "e-home", "e1"], at="2026-10-25T15:00:00+00:00", query="private", cut=True)
    route_shown(s, "rs1", targets=["e-home"], at="2026-10-25T15:01:00+00:00")
    route_shown(s, "rs2", targets=["e1"], lane="personal", at="2026-10-25T15:02:00+00:00")
    return s


def test_recall_rows_lose_instincts_and_ship_whole_or_not_at_all(tmp_path):
    s = recall_store(tmp_path)   # rows: [e1, i1] kept; [e1, e-home] dropped; [i1] dropped; [e1, e2] kept
    rows = memory_log_rows(s.conn, selection(until=T1), terms(route=True), closed_sessions(s.conn, T1),
                           shipped_all(s), instinct_ids(s))
    assert [json.loads(r["target_ids"]) for r in rows if r["event_type"] == "recall"] == [["e1"], ["e1", "e2"]]


def test_kept_recall_rows_keep_two_context_keys_and_normalized_outcomes(tmp_path):
    s = recall_store(tmp_path, outcomes=["used: auto: cited", "used \u2014 it helped me with Jenn", "not_used, meh", "odd"],
                     query="who drove me")
    rows = recall_rows_of(s)
    assert [r["outcome"] for r in rows] == ["used: auto: cited", "used", "not_used", None]
    assert all(set(json.loads(r["context"])) <= {"recall_id", "session_id"} for r in rows)
    assert all("who drove" not in json.dumps(r) and "Jenn" not in json.dumps(r) for r in rows)


def test_route_shown_rows_are_cut_to_m_in_order(tmp_path):
    s = route_shown_store(tmp_path)   # [e3, e-home, e1] work; [e-home] work; [e1] personal lane; extra context keys
    rows = [r for r in rows_of(s) if r["event_type"] == "route_shown"]
    assert [json.loads(r["target_ids"]) for r in rows] == [["e3", "e1"]]
    assert set(json.loads(rows[0]["context"])) == {"receipt_id", "session_id", "tool", "lane"} and rows[0]["outcome"] is None


def test_no_kept_row_carries_a_cut_mark(tmp_path):
    for r in rows_of(route_shown_store(tmp_path)) + rows_of(recall_store(tmp_path)):
        assert "cut" not in json.loads(r["context"]) and set(r) == set(MEMORY_LOG_COLUMNS)


def test_log_rows_need_route_a_closed_session_and_the_window(tmp_path):
    s = recall_store(tmp_path, extra=[("after-t1", "2026-10-25T18:00:00+00:00"), ("open", "2026-10-25T17:45:00+00:00")])
    ids = [r["id"] for r in rows_of(s)]
    assert "after-t1" not in ids and "open" not in ids and ids
    assert list(memory_log_rows(s.conn, selection(until=T1), terms(route=False), closed_sessions(s.conn, T1),
                                shipped_all(s), instinct_ids(s))) == []


def test_normalize_outcome_and_the_window_start_and_sessionless_rows(tmp_path):
    assert [normalize_outcome(t) for t in ("used: auto: cited", "used", "not_used x", "unused", "", None)] == [
        "used: auto: cited", "used", "not_used", None, None, None]
    s = recall_store(tmp_path)
    recall(s, "nosession", targets=["e1"], session=None)
    assert "nosession" not in [r["id"] for r in rows_of(s)]
    late = selection(until=T1, since=T("2026-10-25T15:03:00Z"))
    got = memory_log_rows(s.conn, late, terms(route=True), closed_sessions(s.conn, T1), shipped_all(s), instinct_ids(s))
    assert [r["id"] for r in got] == ["rc3"]


def test_a_route_shown_row_whose_lane_is_not_text_is_dropped_not_fatal(tmp_path):     # review's Task 11 item
    s = _log_base(tmp_path, "odd-lane")
    route_shown(s, "rs-list", targets=["e1"], lane=["work"], at="2026-10-25T15:00:00+00:00")
    route_shown(s, "rs-dict", targets=["e1"], lane={"w": 1}, at="2026-10-25T15:01:00+00:00")
    route_shown(s, "rs-ok", targets=["e1"], at="2026-10-25T15:02:00+00:00")
    assert [r["id"] for r in rows_of(s) if r["event_type"] == "route_shown"] == ["rs-ok"]
