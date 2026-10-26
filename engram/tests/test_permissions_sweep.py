"""Task 24: the sweep (P 10; U12). Placements follow their records, and pending lane notes are settled."""
import sqlite3
import uuid
from types import SimpleNamespace

import pytest

import server
import sharing
from permission_ledger import Ledger
from permission_uses import Uses, UseRow
from permissions import Act
from sharing import SweepReport, sweep_placements
from storage import Storage
from tests.conftest import MIGRATIONS_DIR
from tests.permissions_support import ANDY, HOME, T, do, house_dir
from tests.test_recall_margins import engram_server_env  # noqa: F401

LAB = "place:andy-lab"
ACTIONS3 = ["recall", "read", "inject_context"]
NOW = T("2026-11-05")


# ---------------------------------------------------------------- helpers

def _selector(audience, memories, purposes=("care-coordination",)):
    return {"audience": list(audience), "requesters": "*",
            "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                        "collections": "*", "memories": memories},
            "actions": ACTIONS3, "purposes": list(purposes)}


def andy_allows(led, *, name=None, audience=None, valid_until=T("2027-01-15"), like=None, valid_from="2026-11-01"):
    """A person-backed allow in Andy's home. `like` names an earlier allow: its audience and purposes are reused."""
    if audience is None:
        audience = led.sel[like] if like is not None else (LAB,)
    if name is None:
        name = f"A{len(led.names)}"
    out = do(led, ANDY, "allow", now=valid_from, layer=HOME, selector=_selector(audience, [f"mem:{led.sid}/episode/{e}" for e in led.eps]),
             valid_from=T(valid_from), valid_until=valid_until, reason="sweep test")
    led.names[name] = out.ref
    led.sel[name] = tuple(audience)
    return out.ref


def revoke(led, name):
    rid = led.names.get(name, name)
    return do(led, ANDY, "revoke", now="2026-11-02", record=rid, reason="sweep test")


def _vector():
    return [0.25] * 768


def _world(tmp_path, mode, n, *, vectors=True):
    root = tmp_path
    (root / ".engram").mkdir(parents=True, exist_ok=True)
    src = Storage(str(root / ".engram" / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    house = Storage(str(house_dir(root, "lighthouse") / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    led = Ledger.create(root, "andy", now=T("2026-11-01"))
    led.names, led.sel = {}, {}
    led.source = src
    led.sid = src.instance_identity()["instance_id"]
    for iid, name in ((led.sid, "engram"), (house.instance_identity()["instance_id"], "published house")):
        do(led, ANDY, "register-store", instance_id=iid, name=name, owner=ANDY, place=HOME, imprint_of=None)
    do(led, ANDY, "register-place", place=LAB, name="Lab", stewards=[ANDY])
    do(led, ANDY, "register-agent", agent="agent:default", acts_for=HOME)
    do(led, ANDY, "put-agent", agent="agent:default", place=HOME)
    do(led, ANDY, "gate", now="2026-11-02", mode=mode)
    led.eps = []
    for i in range(n):
        ep = str(uuid.uuid4())
        src.add_episode(id=ep, session_id="t", content=f"note {i}", embedding=_vector() if vectors else None)
        led.eps.append(ep)
    return house, led


def _place(house, led, ep, record_id, audience="group:outside-home"):
    return sharing.share(source_storage=led.source, published_storage=house, source_id=ep, layer="episode",
                         audience=audience, reason="t", source_instance="engram", source_instance_id=led.sid,
                         record_id=record_id)


def enforce_house_with_placements(tmp_path, n, linked_to="R", mode="enforce"):
    house, led = _world(tmp_path, mode, n)
    rid = andy_allows(led, name=linked_to, valid_until=T("2026-11-10"))
    for ep in led.eps:
        _place(house, led, ep, rid)
    return house, led


def shadow_house_with_placements(tmp_path, n, linked_to="R"):
    return enforce_house_with_placements(tmp_path, n, linked_to, mode="shadow")


def add_share_row_for_the_same_copy(house, led, *, audience, linked_to):
    rid = andy_allows(led, name=linked_to, audience=(audience,))
    row = dict(house.conn.execute("SELECT * FROM shared_memories ORDER BY shared_at, share_id LIMIT 1").fetchone())
    row.update(share_id=str(uuid.uuid4()), audience=audience, record_id=rid)
    house.conn.execute(f"INSERT INTO shared_memories ({', '.join(row)}) VALUES ({', '.join('?' * len(row))})",
                       list(row.values()))
    house.conn.commit()


def placement_rows(house):
    return [dict(r) for r in house.conn.execute("SELECT * FROM shared_memories ORDER BY shared_at, share_id")]


def copies_left(house):
    return house.conn.execute("SELECT COUNT(*) FROM episodes").fetchone()[0]


def vectors_left(house):
    return house.conn.execute("SELECT COUNT(*) FROM episode_vectors").fetchone()[0]


def house_bytes(house):
    return (placement_rows(house), [tuple(r) for r in house.conn.execute("SELECT * FROM episodes ORDER BY id")],
            vectors_left(house))


def enforce_house_with_a_pending_note(tmp_path):
    house, led = _world(tmp_path, "enforce", 1)
    store, ep = led.source, led.eps[0]
    sid = led.sid

    def listener(phase, rows, target):
        if phase == "after":
            raise SystemExit("crash between the store's commit and the settling note")
        led.note_lanes(phase, rows, target, store_id=sid, now=T("2026-11-01"))
    store.lane_listener = listener
    with pytest.raises(SystemExit):
        store.set_episode_lanes([ep], "work")
    return house, led, store, ep


def ref(store, ep):
    return f"mem:{store.instance_identity()['instance_id']}/episode/{ep}"


# ---------------------------------------------------------------- the tests of the brief

def test_u12_after_a_revocation_the_placements_go_within_one_pass(tmp_path):
    house, led = enforce_house_with_placements(tmp_path, n=300, linked_to="R")
    revoke(led, "R")
    first = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert first.removed == 256
    second = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert second.removed == 44 and copies_left(house) == 0


def test_u12_after_an_expiry_a_placement_is_relinked_when_another_allow_covers_it(tmp_path):
    house, led = enforce_house_with_placements(tmp_path, n=1, linked_to="R")   # R: outside home, ends 2026-11-10
    r2 = andy_allows(led, like="R", valid_until=T("2027-01-31"))   # same subject, object and placement audience
    other = andy_allows(led, like="R", audience=["group:g1"])
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-10"))
    assert (report.relinked, report.removed) == (1, 0)
    [row] = placement_rows(house)
    assert row["record_id"] == r2 and row["audience"] == "group:outside-home" and copies_left(house) == 1
    revoke(led, r2)
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-11"))
    assert (report.relinked, report.removed) == (0, 1) and copies_left(house) == 0     # `other` never relinks it
    assert other in led.state().records                                                 # and is left alone


def test_u12_the_copy_goes_with_its_last_share_row(tmp_path):
    house, led = enforce_house_with_placements(tmp_path, n=1, linked_to="R")   # one copy, its row linked to R
    add_share_row_for_the_same_copy(house, led, audience="group:g1", linked_to="RG")   # a second row, same copy
    revoke(led, "R")
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert report.removed == 1 and len(placement_rows(house)) == 1
    assert copies_left(house) == 1 and vectors_left(house) == 1               # a row still holds the copy
    revoke(led, "RG")
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert report.removed == 1 and placement_rows(house) == []
    assert copies_left(house) == 0 and vectors_left(house) == 0               # its last row: copy and vector go


def test_u12_the_sweep_settles_pending_lane_notes(tmp_path):
    house, led, store, ep = enforce_house_with_a_pending_note(tmp_path)    # the store committed `work`; no settling note
    assert led.latest_lane_note(ref(store, ep)) == "pending"
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert report.settled == 1 and led.latest_lane_note(ref(store, ep)) == "work"   # read from the store, read-only
    again = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert again.settled == 0


def test_shadow_only_reports_what_it_would_remove(tmp_path):
    house, led = shadow_house_with_placements(tmp_path, n=3, linked_to="R")
    revoke(led, "R")
    before = house_bytes(house)
    report = sweep_placements(published_storage=house, ledger=led, mode="shadow", now=NOW)
    assert (report.would_remove, report.removed, report.relinked) == (3, 0, 0) and house_bytes(house) == before


def test_a_placement_with_no_record_is_left_alone(tmp_path):
    house, led = _world(tmp_path, "enforce", 1)
    _place(house, led, led.eps[0], None, audience="commons")
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert report == SweepReport(0, 0, 0, 0) and copies_left(house) == 1


def test_a_placement_whose_record_still_counts_is_left_alone(tmp_path):
    house, led = enforce_house_with_placements(tmp_path, n=2, linked_to="R")
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=T("2026-11-06"))
    assert report == SweepReport(0, 0, 0, 0) and copies_left(house) == 2


def test_a_placement_naming_a_record_the_ledger_does_not_hold_is_left_alone(tmp_path):
    house, led = _world(tmp_path, "enforce", 1)
    _place(house, led, led.eps[0], "r-" + "0" * 32)
    report = sweep_placements(published_storage=house, ledger=led, mode="enforce", now=NOW)
    assert report == SweepReport(0, 0, 0, 0) and copies_left(house) == 1


# ---------------------------------------------------------------- the server

def _published_house(tmp_path):
    house = Storage(str(house_dir(tmp_path, "lighthouse") / "graph.db"), migrations_dir=MIGRATIONS_DIR)
    return house


def raise_gate_through_perform(root, mode):
    house = _published_house(root)
    led = Ledger.create(root, "andy", now=T("2026-11-01"))
    do(led, ANDY, "register-store", instance_id=house.instance_identity()["instance_id"], name="published house",
       owner=ANDY, place=HOME, imprint_of=None)
    do(led, ANDY, "gate", now="2026-11-02", mode=mode)
    ledger_id = led.meta()["ledger_id"]
    led.close()
    house.close()
    return ledger_id


def receipts_spanning_days(root, *, days, ledger_id):
    uses = Uses.open(root)
    start = T("2026-11-01")
    for d in range(days):
        row = UseRow(at=start + d * 86400, ledger_id=ledger_id, ledger_seq=1, agent="agent:default", place=HOME,
                     acting_for=HOME, action="recall", purpose="care-coordination", allowed=1, cited="[]",
                     object=None, copy="store:house", returned="[]", filtered=0)
        uses.append(row, subjects=[("person:andy", "mem:S/episode/m1")])
    uses.close()


def test_server_startup_folds_old_receipts(engram_server_env, tmp_path, monkeypatch):   # P 9.1, "Retention"
    ledger_id = raise_gate_through_perform(tmp_path, "shadow")
    receipts_spanning_days(tmp_path, days=420, ledger_id=ledger_id)
    monkeypatch.setattr(server, "_permission_now", lambda: T("2026-11-01") + 420 * 86400)
    monkeypatch.setattr(server, "_initialized", False)
    server._init()
    uses = Uses.open(tmp_path)
    assert uses.verify() is None
    assert uses.conn.execute("SELECT COUNT(*) FROM uses_monthly").fetchone()[0] > 0
    assert uses.conn.execute("SELECT MIN(at) FROM uses").fetchone()[0] >= T("2026-11-01") + 20 * 86400


def test_server_startup_does_not_fold_when_the_gate_is_off(engram_server_env, tmp_path, monkeypatch):
    ledger_id = raise_gate_through_perform(tmp_path, "shadow")
    receipts_spanning_days(tmp_path, days=420, ledger_id=ledger_id)
    led = Ledger.open(tmp_path)
    do(led, ANDY, "gate", now="2026-11-03", mode="off")
    led.close()
    monkeypatch.setattr(server, "_permission_now", lambda: T("2026-11-01") + 420 * 86400)
    monkeypatch.setattr(server, "_initialized", False)
    server._init()
    assert Uses.open(tmp_path).conn.execute("SELECT COUNT(*) FROM uses").fetchone()[0] == 420


def test_a_failing_sweep_never_stops_startup_or_changes_the_reply(engram_server_env, tmp_path, monkeypatch):
    raise_gate_through_perform(tmp_path, "enforce")

    def boom(**kw):
        raise RuntimeError("sweep broke")
    monkeypatch.setattr(sharing, "sweep_placements", boom)
    monkeypatch.setattr(server, "_initialized", False)
    server._init()
    assert server.unshare("no-such-share") == {"removed": False}
