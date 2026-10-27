"""The receipts fold reads one receipt at a time, in batches, each with its own anchor (SH-6; P 9.1, 15)."""
import gc
import json
import tracemalloc

import pytest

import permission_uses
from permission_uses import Uses, _digest, _entry, ZERO

MB = 1 << 20
DAY = 86400
NOW = 1_800_000_000
OLD = NOW - 401 * DAY


def write_chain(uses, count, *, at=lambda i: OLD + i, cited="[]", returned=None, subjects=1):
    """Receipts 1..count written by SQL in one transaction, with a true digest chain."""
    prev = ZERO
    uses.conn.execute("BEGIN IMMEDIATE")
    for i in range(1, count + 1):
        row = {"seq": i, "id": f"u-{i}", "at": at(i), "ledger_id": "L", "ledger_seq": i, "agent": "a", "place": "p",
               "acting_for": "andy", "session_label": None, "action": "recall", "purpose": "work", "object": None,
               "copy": None, "allowed": 1, "cited": cited, "refusal": None, "until": None, "horizon": None,
               "returned": returned, "filtered": None, "content_digest": None, "shadow": 0}
        subs = [(f"s{j}", f"memory:{i}") for j in range(subjects)]
        digest = _digest(prev, _entry(row, subs))
        uses.conn.execute(f"INSERT INTO uses({','.join(row)},prev_digest,digest) VALUES({','.join('?' * (len(row) + 2))})",
                          (*row.values(), prev, digest))
        uses.conn.executemany("INSERT INTO use_subjects VALUES(?,?,?)", [(i, s, o) for s, o in subs])
        prev = digest
    uses.conn.execute("COMMIT")


def monthly(uses):
    return [tuple(r) for r in uses.conn.execute("SELECT * FROM uses_monthly ORDER BY month, subject, place, "
                                                "action, purpose, outcome")]


def anchors(uses):
    return [r["through_seq"] for r in uses.conn.execute("SELECT through_seq FROM uses_anchor ORDER BY through_seq")]


def traced(fn):
    gc.collect()
    tracemalloc.start()
    try:
        result = fn()
        gc.collect()
        _, peak = tracemalloc.get_traced_memory()
    finally:
        tracemalloc.stop()
    return result, peak


def test_the_fold_holds_one_batch(tmp_path, monkeypatch):
    uses = Uses.open(tmp_path)
    cited = json.dumps([{"layer": f"layer-{k:03d}", "kind": "memory", "action": "recall", "verdict": "allow",
                         "records": [f"rec-{k:04d}"], "version": k} for k in range(43)])
    write_chain(uses, 5000, cited=cited, returned="[]")
    monkeypatch.setattr(permission_uses, "FOLD_BATCH", 500)
    folded, peak = traced(lambda: uses.fold(now=NOW))
    assert folded == 5000 and uses.verify() is None
    assert peak < 12 * MB, f"peak {peak / MB:.1f} MB"


def test_the_fold_anchors_each_batch(tmp_path, monkeypatch):
    a, b = Uses.open(tmp_path / "a"), Uses.open(tmp_path / "b")
    for u in (a, b):
        write_chain(u, 1050, at=lambda i: OLD + i * 86400 * 3, subjects=2)
    monkeypatch.setattr(permission_uses, "FOLD_BATCH", 100)
    assert a.fold(now=NOW + 5000 * DAY) == 1050
    assert len(anchors(a)) == 11 and a.verify() is None
    monkeypatch.undo()
    assert b.fold(now=NOW + 5000 * DAY) == 1050
    assert monthly(a) == monthly(b) and monthly(a)


def test_a_break_stops_the_fold_at_its_batch(tmp_path, monkeypatch):
    uses = Uses.open(tmp_path)
    write_chain(uses, 400)
    uses.conn.execute("UPDATE uses SET agent='b' WHERE seq=250")
    monkeypatch.setattr(permission_uses, "FOLD_BATCH", 100)
    with pytest.raises(ValueError):
        uses.fold(now=NOW)
    assert anchors(uses) == [100, 200]
    assert uses.conn.execute("SELECT MIN(seq), COUNT(*) FROM uses").fetchone()[:] == (201, 200)
    assert uses.verify() == 250


def test_the_fold_keeps_one_receipt_at_a_time(tmp_path):
    uses = Uses.open(tmp_path)
    write_chain(uses, 100, returned=json.dumps(["x" * 1024] * 1024))
    folded, peak = traced(lambda: uses.fold(now=NOW))
    assert folded == 100
    assert peak < 8 * MB, f"peak {peak / MB:.1f} MB"


def test_a_younger_receipt_stops_the_fold(tmp_path):
    uses = Uses.open(tmp_path)
    write_chain(uses, 10, at=lambda i: NOW if i == 4 else OLD)
    assert uses.fold(now=NOW) == 3
    assert anchors(uses) == [3]
    assert [r["seq"] for r in uses.conn.execute("SELECT seq FROM uses ORDER BY seq")] == list(range(4, 11))
    assert uses.verify() is None
