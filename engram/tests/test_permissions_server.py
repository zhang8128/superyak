"""Task 23: share under the gate, permit and permissions (P 9.3, 12.1; U9, U11, U16, U18, R26, R28, SF8)."""
import json
import sqlite3
import time
import tomllib

import pytest

import server
import sharing
from config import resolve_db_path
from permission_ledger import Gate, Ledger, ledger_path
from permissions import MAX_PLACEMENTS, Act, parse_selector
from storage import Storage
from tests.permissions_support import (
    ANDY, COUNTY, HOME, PH, deliver_m1_through, house_dir, keep_world, make_ledger_unreadable,  # noqa: F401
    only_proposal_rows_changed, refused_read_of_m3)
from tests.test_recall_margins import engram_server_env  # noqa: F401

COLLECTION = "collection:andy/local"
ACTIONS3 = ["recall", "read", "inject_context"]


def now() -> int:
    return int(time.time())


def selector(audience, *, memories="*", collections="*", purposes="*"):
    return {"audience": audience, "requesters": "*",
            "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                        "collections": collections, "memories": memories},
            "actions": ACTIONS3, "purposes": purposes}


HOME_SELECTOR = selector(["place:home/andy"], collections=[COLLECTION])
PUBLIC_HEALTH_SELECTOR = selector(["place:la-county/public-health"], collections=[COLLECTION],
                                  purposes=["care-coordination"])


def perf(led, actor, kind, channel="terminal", **args):
    return led.perform(Act(kind, args), actor=actor, channel=channel, now=now())


def ledger_open():
    return Ledger.open_read_only(server.ENGRAM_HOME)


def ledger_state():
    led = ledger_open()
    try:
        return led.state()
    finally:
        led.close()


def ledger_tables():
    led = ledger_open()
    try:
        return led.tables()
    finally:
        led.close()


def ledger_bytes():
    return ledger_path(server.ENGRAM_HOME).read_bytes()


def house_path():
    return server.ENGRAM_HOME / ".engram" / "instances" / "lighthouse" / "graph.db"


def house_bytes(tmp_path):
    return house_path().read_bytes()


def placement_row(share_id):
    con = sqlite3.connect(house_path())
    con.row_factory = sqlite3.Row
    try:
        r = con.execute("SELECT * FROM shared_memories WHERE share_id = ?", (share_id,)).fetchone()
        return None if r is None else dict(r)
    finally:
        con.close()


def andy_allows(memory_id, audience, ref=None):
    """A person-backed allow in Andy's home covering one memory, for the three actions."""
    ref = ref or f"mem:{STORE_ID[0]}/episode/{memory_id}"
    outside = audience != ["place:home/andy"]
    led = Ledger.open(server.ENGRAM_HOME)
    try:
        return perf(led, ANDY, "allow", layer=HOME, selector=selector(audience, memories=[ref],
                    purposes=["care-coordination"] if outside else "*"), valid_from=now() - 5,
                    valid_until=now() + 20 * 86400 if outside else None, reason="test").ref
    finally:
        led.close()


def andy_grants_default(ops, envelope, max_days):
    led = Ledger.open(server.ENGRAM_HOME)
    try:
        return perf(led, ANDY, "grant", layer=HOME, grantee="agent:default", ops=sorted(ops), envelope=envelope,
                    max_days=max_days, depth=0, hours=24).ref
    finally:
        led.close()


def revoke_as_andy(rid):
    led = Ledger.open(server.ENGRAM_HOME)
    try:
        return perf(led, ANDY, "revoke", record=rid, reason="test")
    finally:
        led.close()


STORE_ID = [None]
M = {}


@pytest.fixture
def enforce_server(engram_server_env, tmp_path):
    server._init()
    STORE_ID[0] = server._storage.instance_identity()["instance_id"]
    house = Storage(str(house_dir(tmp_path, "lighthouse") / "graph.db"))
    house_id = house.instance_identity()["instance_id"]
    house.close()
    led = Ledger.create(tmp_path, "andy", now=now() - 100)
    for handle in ("county-steward", "ph-steward"):
        perf(led, ANDY, "register-person", person="person:" + handle)
    perf(led, ANDY, "register-place", place=COUNTY, name="LA County", stewards=["person:county-steward"])
    perf(led, "person:county-steward", "register-place", place=PH, name="Public Health",
         stewards=["person:ph-steward"])
    for iid, name in ((STORE_ID[0], "engram"), (house_id, "published house")):
        perf(led, ANDY, "register-store", instance_id=iid, name=name, owner=ANDY, place=HOME, imprint_of=None)
    perf(led, ANDY, "register-agent", agent="agent:default", acts_for=HOME)
    perf(led, ANDY, "put-agent", agent="agent:default", place=HOME)
    perf(led, ANDY, "register-place", place="place:andy-lab", name="Lab", stewards=[ANDY])
    perf(led, ANDY, "register-place", place="place:andy-other", stewards=[ANDY])
    perf(led, ANDY, "register-place", place="place:andy-lab/x", parents=["place:andy-lab"], stewards=[ANDY])
    perf(led, ANDY, "register-agent", agent="agent:parked", acts_for=HOME)
    perf(led, ANDY, "make-collection", collection=COLLECTION)
    perf(led, ANDY, "gate", mode="enforce")
    led.close()
    M["local"] = server.remember(content="a local note, worth keeping")["episode_id"]
    M["other"] = server.remember(content="another local note about rivers")["episode_id"]
    return server


# ---------------------------------------------------------------- share under enforce

def test_u11_share_with_no_covering_allow_changes_nothing_and_returns_the_permit_call(enforce_server):
    before = ledger_bytes()
    out = server.share(memory_id=M["local"], audience="place:la-county/public-health", reason="r")
    assert out["status"] == "needs-allow" and out["permit"]["op"] == "share" and server.shares()["shares"] == []
    assert out["cli"].startswith("engram-permissions allow") and ledger_bytes() == before


def test_u11_with_a_covering_allow_it_places_a_copy_with_the_placement_audience_and_record_id(enforce_server):
    rid = andy_allows(M["local"], ["place:la-county/public-health"])
    out = server.share(memory_id=M["local"], audience="place:la-county/public-health", reason="r")
    row = placement_row(out["share_id"])
    assert row["audience"] == "group:outside-home" and row["record_id"] == rid
    assert row["source_instance_id"] == STORE_ID[0]
    note = ledger_state().lane_notes[f"mem:{STORE_ID[0]}/episode/{M['local']}"]
    assert [n.lane for n in note] == ["personal"]            # P 5.3: the first note, written by the share


def test_commons_maps_to_the_owners_home_place(enforce_server):
    rid = andy_allows(M["local"], ["place:home/andy"])
    out = server.share(memory_id=M["local"], audience="commons", reason="r")
    assert out["audience"] == "commons" and placement_row(out["share_id"])["record_id"] == rid


def test_u11_permit_inside_the_envelope_is_grant_backed_and_outside_is_a_proposal(enforce_server):
    gid = andy_grants_default({"share"}, HOME_SELECTOR, 30)
    inside = server.permit(op="share", selector=HOME_SELECTOR, valid_until=now() + 30 * 86400, reason="r")
    assert inside["status"] == "done" and inside["under_grant"] == gid
    rec = ledger_state().records[inside["ref"]]
    assert (rec.backing, rec.set_by, rec.channel) == (f"grant:{gid}", "agent:default", "tool")
    before = ledger_tables()
    outside = server.permit(op="share", selector=PUBLIC_HEALTH_SELECTOR, valid_until=now() + 30 * 86400,
                            reason="r")
    assert outside["status"] == "proposal" and outside["under_grant"] is None
    assert only_proposal_rows_changed(before, ledger_tables())
    [p] = [p for p in ledger_tables()["proposals"] if p["id"] == outside["ref"]]
    assert (p["by_agent"], p["for_person"]) == ("agent:default", "person:andy")


def test_u11_unshare_always_works(enforce_server, tmp_path):
    rid = andy_allows(M["local"], ["place:home/andy"])
    first = server.share(memory_id=M["local"], audience="commons", reason="r")["share_id"]
    andy_allows(M["other"], ["place:home/andy"])
    second = server.share(memory_id=M["other"], audience="commons", reason="r")["share_id"]
    revoke_as_andy(rid)
    before = ledger_tables()
    assert server.unshare(share_id=first) == {"removed": True} and placement_row(first) is None
    assert (ledger_tables()["records"], ledger_tables()["proposals"]) == (before["records"], before["proposals"])
    make_ledger_unreadable(tmp_path)
    assert server.unshare(share_id=second) == {"removed": True} and placement_row(second) is None


def test_u16_closed_refuses_share_and_permit(enforce_server, tmp_path):
    make_ledger_unreadable(tmp_path)
    before = house_bytes(tmp_path)
    for out in (server.share(memory_id=M["local"], audience="commons", reason="r"),
                server.permit(op="share", selector=HOME_SELECTOR, reason="r")):
        assert "error" in out and "closed" in out["error"]
    assert house_bytes(tmp_path) == before


def test_sf8_sharing_an_unmigrated_row_again_fills_its_identity(enforce_server):
    sid = _unmigrated_commons_row(M["local"])
    rid = andy_allows(M["local"], ["place:home/andy"])
    out = server.share(memory_id=M["local"], audience="commons", reason="again")
    row = placement_row(sid)
    assert out["share_id"] == sid and row["source_instance_id"] == STORE_ID[0] and row["record_id"] == rid
    _set_record_id(sid, "r-" + "0" * 32)
    server.share(memory_id=M["local"], audience="commons", reason="again")
    assert placement_row(sid)["record_id"] == "r-" + "0" * 32


def _unmigrated_commons_row(memory_id):
    """A share row as `migrate` leaves it unmatched: made under off-style sharing, both columns nulled."""
    with server._published_house_storage() as (_, house):
        rec = sharing.share(source_storage=server._storage, published_storage=house, source_id=memory_id,
                            layer="episode", audience="commons", reason="old", source_instance="default")
    con = sqlite3.connect(house_path())
    con.execute("UPDATE shared_memories SET source_instance_id = NULL, record_id = NULL WHERE share_id = ?",
                (rec.share_id,))
    con.commit()
    con.close()
    return rec.share_id


def _set_record_id(share_id, rid):
    con = sqlite3.connect(house_path())
    con.execute("UPDATE shared_memories SET record_id = ? WHERE share_id = ?", (rid, share_id))
    con.commit()
    con.close()


def test_u16_a_config_that_fails_to_parse_changes_no_mode(enforce_server, tmp_path, monkeypatch, caplog):
    (tmp_path / ".engram" / "config.toml").write_text("[permissions\n")
    assert resolve_db_path(tmp_path) == tmp_path / ".engram" / "graph.db"
    assert "Could not load config" in caplog.text
    monkeypatch.setattr(server, "_initialized", False)
    with pytest.raises(tomllib.TOMLDecodeError):
        server._init()
    assert server._permission_gate() == Gate("enforce", None)


# ---------------------------------------------------------------- the bound (sharing layer)

def _house_with_placements(tmp_path, n):
    house = Storage(str(house_dir(tmp_path, "h") / "graph.db"))
    source = Storage(str(house_dir(tmp_path, "s") / "graph.db"))
    old = source.add_episode(id="old-1", session_id="t", content="an old memory") or "old-1"
    sharing.share(source_storage=source, published_storage=house, source_id="old-1", layer="episode",
                  audience="commons", reason="r", source_instance="default")
    with house.transaction():
        house.conn.executemany(
            "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, audience,"
            " reason, content_digest, shared_at) VALUES (?, ?, 'x', ?, 'episode', 'commons', 'r', ?, '2026-11-01')",
            [(f"s{i}", f"m{i}", f"x{i}", "0" * 64) for i in range(n - 1)])
    return house, source, "old-1"


def _count(house):
    return house.conn.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0]


def test_u9_the_20001st_placement_is_refused(tmp_path):
    house, source, old = _house_with_placements(tmp_path, MAX_PLACEMENTS)
    source.add_episode(id="new-1", session_id="t", content="a new memory")
    with pytest.raises(ValueError, match="20,000"):
        sharing.share(source_storage=source, published_storage=house, source_id="new-1", layer="episode",
                      audience="commons", reason="r", source_instance="default")
    assert _count(house) == MAX_PLACEMENTS
    sid = house.conn.execute("SELECT share_id FROM shared_memories WHERE source_id = ?", (old,)).fetchone()[0]
    again = sharing.share(source_storage=source, published_storage=house, source_id=old, layer="episode",
                          audience="commons", reason="r", source_instance="default")
    assert again.share_id == sid and _count(house) == MAX_PLACEMENTS
    sharing.unshare(published_storage=house, share_id=again.share_id)
    sharing.share(source_storage=source, published_storage=house, source_id="new-1", layer="episode",
                  audience="commons", reason="r", source_instance="default")
    assert _count(house) == MAX_PLACEMENTS


# ---------------------------------------------------------------- permit

def _widening(enforce_server):
    """(op, kwargs) for each widening row of P 7.6 that is one Act (R26)."""
    led = Ledger.open(server.ENGRAM_HOME)
    deny = perf(led, ANDY, "deny", layer=HOME, selector=selector(["place:la-county/public-health"],
                purposes=["care-coordination"]), valid_from=now() - 5, valid_until=None, reason="consent").ref
    other = f"mem:{STORE_ID[0]}/episode/{M['other']}"
    perf(led, ANDY, "add-subject", object=other, subject="person:ph-steward")
    led.close()
    end = now() + 30 * 86400
    ref = f"mem:{STORE_ID[0]}/episode/{M['local']}"
    return [
        ("share", dict(selector=PUBLIC_HEALTH_SELECTOR, valid_until=end, reason="r")),
        ("withdraw", dict(record=deny, reason="r")),
        ("shorten", dict(record=deny, valid_until=end, reason="r")),
        ("narrow", dict(record=deny, selector=selector(["place:la-county/public-health"],
                        collections=[COLLECTION], purposes=["care-coordination"]), reason="r")),
        ("collect", dict(collection=COLLECTION, memory=ref, reason="r")),
        ("grant", dict(args=dict(layer=HOME, grantee="agent:default", ops=["share"], envelope=HOME_SELECTOR,
                                 max_days=30, depth=0, hours=24))),
        ("group", dict(args=dict(group="group:g1", owner="person:andy", members=["agent:default"]))),
        ("register-agent", dict(args=dict(agent="agent:rio-2", acts_for=HOME))),
        ("put-agent", dict(args=dict(agent="agent:parked", place=HOME))),
        ("add-steward", dict(args=dict(place="place:andy-lab", person="person:ph-steward"))),
        ("register-place", dict(args=dict(place="place:andy-lab2", stewards=["person:andy"], name="Lab 2"))),
        ("add-parent", dict(args=dict(place="place:andy-lab/x", parent="place:andy-other"))),
        ("register-store", dict(args=dict(instance_id="Q", name="q", owner="person:andy", place=HOME))),
        ("remove-subject", dict(args=dict(object=other, subject="person:ph-steward"))),
        ("gate", dict(args=dict(mode="shadow"))),
    ]


def test_u18_each_widening_act_through_the_mcp_tools_is_filed_as_a_proposal(enforce_server):
    for op, kwargs in _widening(enforce_server):
        before = ledger_tables()
        out = server.permit(op=op, **kwargs)
        assert out.get("status") == "proposal", (op, out)
        assert only_proposal_rows_changed(before, ledger_tables()), op
    before = ledger_bytes()
    assert "engram-permissions migrate" in server.permit(op="migrate")["error"] and ledger_bytes() == before
    assert "error" in server.permit(op="nonsense") and ledger_bytes() == before
    assert not [r for r in ledger_tables()["records"] if r["set_by"] == "agent:default"]


def test_permit_deny_is_the_agents_own_restriction(enforce_server):
    out = server.permit(op="deny", selector=selector(["place:la-county/public-health"]), reason="r")
    assert out["status"] == "done" and ledger_state().records[out["ref"]].layer == "agent:default"


def test_permissions_tool_is_read_only(enforce_server):
    before = ledger_bytes()
    for focus in ("uses", "rules", "proposals", "grants"):
        assert "error" not in server.permissions(focus=focus)
    assert ledger_bytes() == before


def test_permissions_for_an_unregistered_agent_is_an_error_for_every_focus(enforce_server, monkeypatch):
    monkeypatch.setattr(server, "_instance_name", "stranger")
    for focus in ("uses", "rules", "proposals", "grants"):
        assert server.permissions(focus=focus) == {"error": "only agents acting for the ledger owner can read this"}


def test_r28_an_agent_not_acting_for_the_owner_sees_only_its_own_receipts(keep_world):
    deliver_m1_through(keep_world, "neighbors")
    refused_read_of_m3(keep_world)
    out = server.permissions(focus="uses")
    assert {"object", "at", "outcome"} <= set(out["rows"][0]) and "counts" not in out
    assert all(set(r) <= {"object", "at", "outcome", "count", "sha256", "permission"} for r in out["rows"])
    text = json.dumps(out)
    assert "jenn" not in text and "place:home" not in text and "NO_ALLOW" not in text
    for focus in ("rules", "proposals", "grants"):
        assert server.permissions(focus=focus) == {"error": "only agents acting for the ledger owner can read this"}


# ---------------------------------------------------------------- off and shadow

def test_off_fills_source_instance_id_and_writes_no_record(engram_server_env, tmp_path):
    house = Storage(str(house_dir(tmp_path, "lighthouse") / "graph.db"))
    house.close()
    server._init()
    ep = server.remember(content="an off-mode note, long enough")["episode_id"]
    out = server.share(memory_id=ep, audience="commons", reason="r")
    row = placement_row(out["share_id"])
    assert row["source_instance_id"] == server._storage.instance_identity()["instance_id"]
    assert row["record_id"] is None and not ledger_path(tmp_path).exists()


def test_shadow_keeps_the_legacy_audience_and_links_a_covering_allow_when_there_is_one(enforce_server):
    led = Ledger.open(server.ENGRAM_HOME)
    perf(led, ANDY, "gate", mode="shadow")
    led.close()
    bare = server.share(memory_id=M["other"], audience="commons", reason="r")        # no allow: still placed
    assert placement_row(bare["share_id"])["record_id"] is None and bare["audience"] == "commons"
    rid = andy_allows(M["local"], ["place:home/andy"])
    out = server.share(memory_id=M["local"], audience="commons", reason="r")
    assert placement_row(out["share_id"])["record_id"] == rid
    assert ledger_state().lane_notes[f"mem:{STORE_ID[0]}/episode/{M['local']}"]
    assert "error" in server.share(memory_id=M["local"], audience="place:la-county/public-health", reason="r")
