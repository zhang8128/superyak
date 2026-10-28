"""SH-13: the records bound on every write, an act's object bound, and `perform` holding one State (P 5.4, 5.6, 15)."""
import gc
import threading
import weakref

import pytest

import permission_cli
import permission_ledger
import permissions
from permission_cli import main
from permission_ledger import Ledger
from permissions import Act, RuleError
from tests.permissions_memory_support import add_records_by_sql
from tests.permissions_support import (ANDY, HOME, M1, PH, PR, SW, T, cli_home, county_ledger, do, fake_tty,
                                       log_rows)
from tests.permissions_support import _doc_of

NOW = T("2026-11-01")


def sel(*actions):
    return _doc_of(["self"], actions=list(actions) or ["recall"])


def ledger_with_records(tmp_path, n):
    """A ledger with exactly `n` record rows: one written by `perform`, the rest copied by SQL."""
    led = Ledger.create(tmp_path, "andy", now=NOW)
    first = do(led, ANDY, "allow", layer=HOME, selector=sel(), valid_from=NOW, valid_until=None)
    if n > 1:
        add_records_by_sql(tmp_path, n - 1)
    return led, first.ref


def count(led, table):
    return led.conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]


def test_the_records_bound_refuses_a_write(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "MAX_RECORDS", 50)
    led, rid = ledger_with_records(tmp_path, 50)
    assert count(led, "records") == 50
    # the agent's proposal is filed while it writes no record
    led.perform(Act("register-agent", {"agent": "agent:rio", "acts_for": HOME}), actor=ANDY, channel="terminal",
                now=NOW)
    filed = do(led, "agent:rio", "allow", channel="tool", layer=HOME, selector=sel("read"), valid_from=NOW,
               valid_until=None)
    assert filed.status == "proposal"
    seq = led.seq()
    for kind, args in (("allow", {"layer": HOME, "selector": sel("route"), "valid_from": NOW, "valid_until": None}),
                       ("deny", {"layer": HOME, "selector": sel("inject_context"), "valid_from": NOW,
                                 "valid_until": None}),
                       ("shorten", {"record": rid, "valid_until": NOW + 1000})):
        with pytest.raises(RuleError, match=r"5\.4.*\b50\b"):
            do(led, ANDY, kind, **args)
    assert led.seq() == seq and count(led, "records") == 50
    with pytest.raises(RuleError, match=r"5\.4.*\b50\b"):
        do(led, ANDY, "sign", proposal=filed.ref)
    assert led.seq() == seq and count(led, "records") == 50
    assert led.state().proposals[filed.ref].status == "pending"
    do(led, ANDY, "revoke", record=rid, reason="done")                 # a revocation inserts no record
    assert led.seq() == seq + 1 and count(led, "records") == 50


def test_two_writers_meet_the_records_bound_once(tmp_path, monkeypatch):
    monkeypatch.setattr(permissions, "MAX_RECORDS", 50)
    led, _ = ledger_with_records(tmp_path, 49)
    led.close()
    barrier = threading.Barrier(2, timeout=20)
    real = Ledger._make

    def held(self, *a, **k):
        out = real(self, *a, **k)
        barrier.wait()
        return out

    monkeypatch.setattr(Ledger, "_make", held)
    results = {}

    def writer(i):
        mine = Ledger.open(tmp_path)
        try:
            mine.perform(Act("allow", {"layer": HOME, "selector": sel("read") if i else sel("route"),
                                       "valid_from": NOW, "valid_until": None}),
                         actor=ANDY, channel="terminal", now=NOW)
            results[i] = "written"
        except Exception as e:                  # a RuleError is the refusal; anything else shows in the assert
            results[i] = f"{type(e).__name__}: {e}"
        finally:
            mine.close()

    threads = [threading.Thread(target=writer, args=(i,)) for i in (0, 1)]
    for t in threads:
        t.start()
    for t in threads:
        t.join(60)
    assert sorted(v == "written" for v in results.values()) == [False, True], results
    refused = [v for v in results.values() if v != "written"][0]
    assert "5.4" in refused and "50" in refused
    check = Ledger.open(tmp_path)
    assert count(check, "records") == 50
    check.close()


def collection_ledger(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=NOW)
    do(led, ANDY, "make-collection", collection="collection:andy/c")
    return led


def refs(n):
    return [f"mem:S/episode/m{i}" for i in range(n)]


def test_an_act_names_at_most_10000_objects(tmp_path):
    led = collection_ledger(tmp_path)
    seq = led.seq()
    with pytest.raises(RuleError, match="10,000"):
        do(led, ANDY, "collect", collection="collection:andy/c", refs=refs(10_001))
    assert led.seq() == seq
    do(led, ANDY, "collect", collection="collection:andy/c", refs=refs(10_000))
    assert led.seq() == seq + 1 and count(led, "collection_members") == 10_000
    with pytest.raises(RuleError, match="10,000"):
        do(led, ANDY, "uncollect", collection="collection:andy/c", refs=refs(10_001))
    seq = led.seq()
    do(led, ANDY, "uncollect", collection="collection:andy/c", refs=refs(10_000))
    assert led.seq() == seq + 1


def test_the_cli_splits_a_large_collect(cli_home, fake_tty, monkeypatch):
    asked = []
    real = permission_cli.confirm
    monkeypatch.setattr(permission_cli, "confirm", lambda *a, **k: asked.append(1) or real(*a, **k))
    fake_tty.answer_the_printed_code()
    assert main(["collection", "add", "collection:andy/c", *refs(25_000)]) == 0
    assert len(asked) == 1
    collects = [r for r in log_rows(cli_home) if r["kind"] == "collect"]
    assert len(collects) == 3


def test_perform_holds_one_state(tmp_path, monkeypatch):
    led = county_ledger(tmp_path)
    filed = do(led, "person:ph-steward", "register-place", place=SW, parents=[PH, PR], name="S",
               stewards=["person:sw-steward"])
    do(led, "person:pr-steward", "sign", proposal=filed.ref)
    do(led, "person:ph-steward", "add-steward", place=PH, person=ANDY)
    do(led, ANDY, "make-collection", collection="collection:andy/c")
    live, worst = [], []
    real = Ledger.state

    def watched(self, *a, **k):
        gc.collect()
        worst.append(sum(1 for r in live if r() is not None))
        st = real(self, *a, **k)
        live.append(weakref.ref(st))
        return st

    monkeypatch.setattr(Ledger, "state", watched)
    layer_sel = _doc_of([PH], actions=["recall"], purposes=["care-coordination"])
    do(led, "person:ph-steward", "allow", layer=PH, selector=layer_sel, valid_from=NOW, valid_until=None)
    do(led, ANDY, "collect", collection="collection:andy/c", refs=[M1])
    proposal = do(led, "agent:rio-grande", "allow", channel="tool", layer=PH, selector=layer_sel, valid_from=NOW,
                  valid_until=None)
    assert proposal.status == "proposal"
    worst.clear(), live.clear()
    do(led, ANDY, "sign", proposal=proposal.ref)
    assert worst and max(worst) <= 1, worst
    worst.clear(), live.clear()
    do(led, "person:ph-steward", "allow", layer=PH, selector=sel("read"), valid_from=NOW, valid_until=None)
    do(led, ANDY, "collect", collection="collection:andy/c", refs=["mem:S/episode/m2"])
    assert worst and max(worst) <= 1, worst


def test_a_collect_reads_the_collections_members_once(tmp_path, monkeypatch):
    """U24 (Task 31): `_prep_collect` took the collection's members again for every object it named, so a collect
    of 10,000 into a collection of 90,000 did 900 million membership tests."""
    led = Ledger.create(tmp_path, "andy", now=NOW)
    do(led, ANDY, "make-collection", collection="collection:andy/big")
    refs = [f"mem:S/episode/m{i}" for i in range(300)]
    do(led, ANDY, "collect", collection="collection:andy/big", objects=refs[:100])
    calls = []
    real = permission_ledger._members
    monkeypatch.setattr(permission_ledger, "_members", lambda state, cid: calls.append(cid) or real(state, cid))
    do(led, ANDY, "collect", collection="collection:andy/big", objects=refs[50:])
    assert len(calls) <= 2, f"{len(calls)} reads of the members"
    assert count(led, "collection_members") == 300
    led.close()


def test_an_uncollect_reads_the_collections_members_once(tmp_path, monkeypatch):
    led = Ledger.create(tmp_path, "andy", now=NOW)
    do(led, ANDY, "make-collection", collection="collection:andy/big")
    refs = [f"mem:S/episode/m{i}" for i in range(300)]
    do(led, ANDY, "collect", collection="collection:andy/big", objects=refs)
    calls = []
    real = permission_ledger._members
    monkeypatch.setattr(permission_ledger, "_members", lambda state, cid: calls.append(cid) or real(state, cid))
    do(led, ANDY, "uncollect", collection="collection:andy/big", objects=refs[:200])
    assert len(calls) <= 2, f"{len(calls)} reads of the members"
    led.close()
