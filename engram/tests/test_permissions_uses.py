"""Task 14 (P 9.1, U8, U22, U27): the receipts file."""
import hashlib
import json
import multiprocessing
import sqlite3

import pytest

from permission_uses import Uses, UseRow, row_for_bulk, row_for_decision, row_for_recall, uses_path
from permissions import decide, decide_bulk, subjects_of
from tests.permissions_support import (
    HOME, M1, M2, T, bulk_use, home_use, memories, road_world, route)

A, B = M1, M2
HOUSE = "store:house"
ROADS = tuple(f"road:S/r{i}" for i in range(5))
DAY = 86400
LEDGER = "ledger-test"


# ---------------------------------------------------------------- helpers (the test file's, per the brief)

def rows(uses):
    return [dict(r) for r in uses.conn.execute("SELECT * FROM uses ORDER BY seq")]


def subject_rows(uses):
    return [dict(r) for r in uses.conn.execute("SELECT * FROM use_subjects ORDER BY rowid")]


def recall_row(*, returned, filtered, at=None, shadow=False):
    """A recall's receipt, built from one allowed decision per memory it returned."""
    s = road_world()
    at = T("2026-11-02") if at is None else at
    base = home_use(M1, at, action="recall")
    decisions = [decide(s, home_use(m, at, action="recall")) for m in returned]
    assert all(d.allowed for d in decisions)
    return row_for_recall(decisions, base, acting_for=HOME, returned=returned, filtered=filtered, shadow=shadow,
                          ledger_id=LEDGER)


def five_road_world():
    """Task 7's road_world: HOME allows route, recall and read on every kind, so each of the five roads
    (each naming A and B) is covered, and an answer that shows A needs nothing more (P 6.4)."""
    return road_world()


def allowed_bulk_route(n):
    objs = [f"road:S/b{i}" for i in range(n)]
    return bulk_use(objs, action="route", names=lambda o: (A, B)), objs


BULK = None  # set by the tests that need it


def write_read_of_three_items(tmp_path, *, content, query):
    """Three items read and delivered; each receipt keeps the content's digest, never the content or query."""
    s = road_world()
    uses = Uses.open(tmp_path)
    digest = hashlib.sha256(content.encode()).hexdigest()
    for m in memories(3):
        u = home_use(m, T("2026-11-02"), action="read")
        d = decide(s, u)
        assert d.allowed
        uses.append(row_for_decision(d, u, acting_for=HOME, content_digest=digest, ledger_id=LEDGER), subjects=[("person:andy", m)])
    return uses


def batch_refs(n):
    return memories(n)


def write_named_batch(tmp_path, objects):
    s = road_world()
    uses = Uses.open(tmp_path)
    bulk = bulk_use(objects, action="read", named=True)
    d = decide_bulk(s, bulk)
    assert d.allowed
    uses.append(row_for_bulk(d, bulk, acting_for=HOME, ledger_id=LEDGER), subjects=[("person:andy", o) for o in objects])
    [row] = rows(uses)
    return row


def flip_one_byte(path, *, table, seq, column):
    """Change one character of that row's column through the test's own sqlite3 connection."""
    conn = sqlite3.connect(path)
    try:
        text = conn.execute(f"SELECT {column} FROM {table} WHERE seq=?", (seq,)).fetchone()[0]
        flipped = text[:-1] + ("x" if text[-1] != "x" else "y")
        conn.execute(f"UPDATE {table} SET {column}=? WHERE seq=?", (flipped, seq))
        conn.commit()
    finally:
        conn.close()


def _append_many(home, each, tag):
    uses = Uses.open(home)
    for i in range(each):
        uses.append(recall_row(returned=[M1], filtered=0, at=T("2026-11-02") + i), subjects=[("person:andy", M1)])
    uses.conn.close()


def run_in_two_processes_appending(home, each):
    ctx = multiprocessing.get_context("spawn")
    procs = [ctx.Process(target=_append_many, args=(home, each, tag)) for tag in ("daemon", "server")]
    for p in procs:
        p.start()
    for p in procs:
        p.join(120)
        assert p.exitcode == 0


def rows_spanning_days(tmp_path, *, days):
    uses = Uses.open(tmp_path)
    start = T("2026-11-01")
    for d in range(days):
        uses.append(recall_row(returned=[M1], filtered=0, at=start + d * DAY), subjects=[("person:andy", M1)])
    return uses


def monthly_counts(uses):
    return [dict(r) for r in uses.conn.execute("SELECT * FROM uses_monthly ORDER BY month")]


# ---------------------------------------------------------------- the tests of the brief

def test_u8_a_recall_writes_one_receipt_with_returned_and_filtered_and_no_filtered_subjects(tmp_path):
    uses = Uses.open(tmp_path)
    uses.append(recall_row(returned=[M1, M2], filtered=1), subjects=[("person:andy", M1), ("person:andy", M2)])
    [row] = rows(uses)
    assert json.loads(row["returned"]) == [M1, M2] and row["filtered"] == 1 and row["copy"] == HOUSE
    assert {r["object"] for r in subject_rows(uses)} == {M1, M2}


def test_u8_a_read_writes_one_receipt_per_item_and_none_holds_content_or_query(tmp_path):
    uses = write_read_of_three_items(tmp_path, content="Jenn drove me to the clinic", query="who drove")
    assert len(rows(uses)) == 3
    raw = uses_path(tmp_path).read_bytes()
    assert b"Jenn drove" not in raw and b"who drove" not in raw and all(r["copy"] for r in rows(uses))
    assert {r["content_digest"] for r in rows(uses)} == {hashlib.sha256(b"Jenn drove me to the clinic").hexdigest()}


def test_u8_the_chain_verifies_and_one_changed_byte_fails(tmp_path):   # the receipts chain; Task 10 tests the log's
    uses = Uses.open(tmp_path)
    for i in range(10):
        uses.append(recall_row(returned=[M1], filtered=0, at=T("2026-11-02") + i), subjects=[("person:andy", M1)])
    assert uses.verify() is None
    flip_one_byte(uses_path(tmp_path), table="uses", seq=4, column="cited")   # its own sqlite3 connection
    assert Uses.open(tmp_path).verify() == 4


def test_u22_five_roads_are_five_route_uses_with_five_receipts(tmp_path):
    s = five_road_world()                         # roads ROADS[0] to ROADS[4], each naming A and B, all allowed
    uses = Uses.open(tmp_path)
    for road in ROADS:                            # one answer that walks five roads: five route uses
        u = route(road, names=(A, B), shows={A})
        d = decide(s, u)
        assert d.allowed, road
        uses.append(row_for_decision(d, u, acting_for=HOME, ledger_id=LEDGER),
                    subjects=[(p, road) for p in subjects_of(s, road, u.at, u.names)])
    route_rows = [r for r in rows(uses) if r["action"] == "route"]
    assert [r["object"] for r in route_rows] == list(ROADS) and len({r["id"] for r in route_rows}) == 5
    assert all(json.loads(r["returned"]) == sorted([A, B]) for r in route_rows)   # the memories each named (R15)
    cited = json.loads(route_rows[0]["cited"])
    assert cited and all("records" in c and "record" not in c and "version" in c for c in cited)


def test_u22_a_counted_bulk_use_writes_one_receipt_naming_no_object(tmp_path):
    uses = Uses.open(tmp_path)
    bulk, _ = allowed_bulk_route(3)
    d = decide_bulk(road_world(), bulk)
    assert d.allowed
    uses.append(row_for_bulk(d, bulk, acting_for=HOME, ledger_id=LEDGER), subjects=[("person:andy", HOUSE)])
    [row] = rows(uses)
    assert row["object"] is None and json.loads(row["returned"]) == {"count": 3} and row["copy"] == HOUSE
    assert [r["object"] for r in subject_rows(uses)] == [HOUSE]


def test_u22_a_named_batch_holds_its_count_and_the_sha256_of_its_sorted_objects(tmp_path):
    objects = sorted(batch_refs(512))
    row = write_named_batch(tmp_path, objects)
    assert row["object"] is None
    assert json.loads(row["returned"]) == {"count": 512,
                                           "sha256": hashlib.sha256("\n".join(objects).encode()).hexdigest()}


def _imported(**kw):
    base = dict(id="u-" + "ab" * 16, at=T("2026-11-03"), ledger_id="peer-station", ledger_seq=7,
                agent="agent:station", place="place:la-county/public-health", acting_for="person:andy",
                session_label=None, action="route", purpose="care-coordination", object=None,
                copy="imprint:peer-station/i1", allowed=0, cited="[]", refusal=None, until=None, horizon=None,
                returned=None, filtered=None, content_digest=None, shadow=0)
    base.update(kw)
    return UseRow(**base)


def test_xs2_an_imported_counted_row_may_hold_null_returned(tmp_path):
    uses = Uses.open(tmp_path)
    refusal = json.dumps({"code": "BOUND", "layer": None, "action": "route"})
    uses.append_imported(_imported(refusal=refusal), subjects=[("person:andy", "imprint:peer-station/i1")])
    [row] = rows(uses)
    assert row["returned"] is None and row["object"] is None and row["ledger_id"] == "peer-station"
    assert row["id"] == "u-" + "ab" * 16
    assert uses.verify() is None
    # the imported form is asserted: a memory object, a store copy, or cited with versions are refused
    for bad in (dict(object="mem:S/episode/m1"), dict(copy="store:house"),
                dict(cited=json.dumps([{"layer": "x", "record": "r-1"}])), dict(returned=None, allowed=1)):
        with pytest.raises(ValueError):
            uses.append_imported(_imported(id="u-" + "cd" * 16, **bad), subjects=[])
    assert len(rows(uses)) == 1


def test_u27_the_daemon_and_a_server_writing_at_once_keep_one_chain(tmp_path):
    run_in_two_processes_appending(tmp_path, each=100)
    uses = Uses.open(tmp_path)
    assert uses.verify() is None
    assert len(rows(uses)) == 200


def test_u27_after_the_400_day_fold_the_chain_verifies_from_its_anchor(tmp_path):
    uses = rows_spanning_days(tmp_path, days=420)
    folded = uses.fold(now=T("2026-11-01") + 420 * DAY)
    assert folded > 0 and uses.verify() is None and monthly_counts(uses)
    left = rows(uses)
    assert len(left) + folded == 420 and left[0]["seq"] == folded + 1
    assert sum(m["n"] for m in monthly_counts(uses)) == folded     # one subject per use here
    assert uses.conn.execute("SELECT COUNT(*) FROM use_subjects").fetchone()[0] == len(left)
    anchor = uses.conn.execute("SELECT through_seq FROM uses_anchor").fetchone()[0]
    assert anchor == folded
    # a row after the fold still chains from the anchor, and a changed byte after it still fails
    uses.append(recall_row(returned=[M1], filtered=0, at=T("2027-12-30")), subjects=[("person:andy", M1)])
    assert uses.verify() is None
    flip_one_byte(uses_path(tmp_path), table="uses", seq=folded + 3, column="cited")
    assert Uses.open(tmp_path).verify() == folded + 3


def test_fold_refuses_a_span_whose_chain_does_not_verify(tmp_path):
    uses = rows_spanning_days(tmp_path, days=420)
    flip_one_byte(uses_path(tmp_path), table="uses", seq=5, column="cited")
    with pytest.raises(ValueError, match="5"):
        uses.fold(now=T("2026-11-01") + 420 * DAY)
    assert len(rows(uses)) == 420


def test_a_refused_decision_row_holds_the_refusal_and_a_read_only_open_cannot_append(tmp_path):
    s = road_world()
    u = home_use("mem:S/episode/m9", T("2026-11-02"), action="inject_context")
    d = decide(s, u)
    assert not d.allowed
    row = row_for_decision(d, u, acting_for=HOME, shadow=True, ledger_id=LEDGER)
    uses = Uses.open(tmp_path)
    uses.append(row, subjects=[("person:andy", u.obj)])
    [r] = rows(uses)
    assert r["allowed"] == 0 and r["shadow"] == 1 and r["returned"] is None
    assert set(json.loads(r["refusal"])) == {"code", "layer", "action"}
    ro = Uses.open_read_only(tmp_path)
    assert ro.verify() is None
    with pytest.raises(sqlite3.OperationalError):
        ro.append(row, subjects=[])


# ---------------------------------------------------------------- Task 16B: the hardening

def _three(tmp_path):
    uses = Uses.open(tmp_path)
    for i in range(3):
        uses.append(recall_row(returned=[M1, M2], filtered=0, at=T("2026-11-02") + i),
                    subjects=[("person:andy", M1), ("person:jenn", M2)])
    return uses


def _sql(tmp_path, statement, params=()):
    conn = sqlite3.connect(uses_path(tmp_path))
    try:
        conn.execute(statement, params)
        conn.commit()
    finally:
        conn.close()


def test_16b_changing_a_subject_row_fails_verify_at_that_receipt(tmp_path):
    _three(tmp_path)
    _sql(tmp_path, "UPDATE use_subjects SET subject='person:eve' WHERE use_seq=2 AND subject='person:jenn'")
    assert Uses.open(tmp_path).verify() == 2


def test_16b_adding_a_subject_row_fails_verify_at_that_receipt(tmp_path):
    _three(tmp_path)
    _sql(tmp_path, "INSERT INTO use_subjects VALUES(3, 'person:eve', ?)", (M1,))
    assert Uses.open(tmp_path).verify() == 3


def test_16b_deleting_a_subject_row_fails_verify_at_that_receipt(tmp_path):
    _three(tmp_path)
    _sql(tmp_path, "DELETE FROM use_subjects WHERE use_seq=1 AND subject='person:andy'")
    assert Uses.open(tmp_path).verify() == 1


def test_16b_the_order_subjects_are_given_does_not_change_the_digest(tmp_path):
    from dataclasses import replace
    first, second = Uses.open(tmp_path / "a"), Uses.open(tmp_path / "b")
    row = replace(recall_row(returned=[M1, M2], filtered=0), id="u-" + "11" * 16)
    first.append(row, subjects=[("person:andy", M1), ("person:jenn", M2)])
    second.append(row, subjects=[("person:jenn", M2), ("person:andy", M1)])
    assert first.conn.execute("SELECT digest FROM uses").fetchone()[0] == second.conn.execute(
        "SELECT digest FROM uses").fetchone()[0]
    assert first.verify() is None and second.verify() is None


def test_16b_a_file_of_the_old_digest_form_is_refused_with_a_clear_error(tmp_path):
    Uses.open(tmp_path).conn.close()
    _sql(tmp_path, "PRAGMA user_version=0")
    from permission_uses import UsesUnreadable
    with pytest.raises(UsesUnreadable, match="digest form"):
        Uses.open(tmp_path)
    with pytest.raises(UsesUnreadable, match="digest form"):
        Uses.open_read_only(tmp_path)


def test_16b_fold_counts_a_receipt_with_no_subject_rows_under_none(tmp_path):
    uses = Uses.open(tmp_path)
    start = T("2026-11-01")
    for d in range(420):
        subjects = [] if d % 3 == 0 else [("person:andy", M1)]
        uses.append(recall_row(returned=[M1], filtered=0, at=start + d * DAY), subjects=subjects)
    folded = uses.fold(now=start + 420 * DAY)
    assert folded > 0
    assert sum(m["n"] for m in monthly_counts(uses)) == folded
    none_rows = [m for m in monthly_counts(uses) if m["subject"] == "(none)"]
    assert none_rows and sum(m["n"] for m in none_rows) == len([d for d in range(folded) if d % 3 == 0])
    assert uses.verify() is None


def test_16b_the_chain_with_subjects_verifies_from_the_anchor_after_a_fold(tmp_path):
    uses = rows_spanning_days(tmp_path, days=420)
    folded = uses.fold(now=T("2026-11-01") + 420 * DAY)
    assert uses.verify() is None
    uses.append(recall_row(returned=[M1], filtered=0, at=T("2027-12-30")), subjects=[("person:andy", M1)])
    assert uses.verify() is None
    _sql(tmp_path, "UPDATE use_subjects SET subject='person:eve' WHERE use_seq=?", (folded + 2,))
    assert Uses.open(tmp_path).verify() == folded + 2


def test_16b_append_refuses_a_local_receipt_with_an_empty_ledger_id_naming_the_field(tmp_path):
    uses = Uses.open(tmp_path)
    row = recall_row(returned=[M1], filtered=0)
    from dataclasses import replace
    with pytest.raises(ValueError, match="ledger_id"):
        uses.append(replace(row, ledger_id=""), subjects=[("person:andy", M1)])
    assert rows(uses) == [] and subject_rows(uses) == []


def test_16b_an_imported_row_keeps_its_own_ledger_id(tmp_path):
    uses = Uses.open(tmp_path)
    uses.append_imported(_imported(), subjects=[("person:andy", "imprint:peer-station/i1")])
    assert rows(uses)[0]["ledger_id"] == "peer-station"
    from dataclasses import replace
    with pytest.raises(ValueError, match="ledger_id"):
        uses.append_imported(_imported(id="u-" + "ee" * 16, ledger_id=""), subjects=[])
