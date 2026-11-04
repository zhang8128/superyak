"""Ship home and crossing plan, Tasks 8 and 9: the publisher daemon serving a remote frame (spec 2.2, 2.3; P10 to P13).

A remote frame's receiver is a store ref, `urn:superyak:<origin peer>:store:<instance>`, written by the publisher's peer
from what it verified. The daemon judges it by the exact-ref policy rule and audience entry, and in the ledger as the
one reserved agent `remote-stores` at the root place `place:outside-home`, never by any local receiver's files, and
serves it only under `enforce`."""
import json
import uuid

import pytest

from lighthouse_protocol import read_frame, recall_frame
from permission_ledger import Ledger
from permissions import parse_selector
from tests.permissions_support import (
    ANDY, DAEMON_CLOCK, HOME, HOUSE_ID, HOUSE_NAME, M1_ID, M1_TEXT, M2_ID, M2_TEXT, SOURCE_ID, T, _daemon_over, _doc_of,
    at, connection_policy, do, house_dir, make_house, make_placed_house, raise_gate, receipt_rows,
)
from tests.test_lighthouse_daemon import CONTEXT, NOW

PEER_A, PEER_B = "a" * 64, "b" * 64
X, Y = "2f1c8a64-3b7e-4d2a-9c11-5e8f0a7b6c3d", "00000000-0000-4000-8000-000000000000"
REF = f"urn:superyak:{PEER_A}:store:{X}"
OUTSIDE = "place:outside-home"
AGENT = "agent:remote-stores"
M1_OBJ, M2_OBJ = "mem:S/episode/m1", "mem:S/episode/m2"


def remote_house(root, refs=(REF,), audience="commons", **policy):
    """The published house `why` (m1 to m3, placed to `audience`) whose policy grants each of `refs` by its exact ref,
    with its `engram:audiences` entry, as `grant-remote` writes one."""
    pub = make_placed_house(root, audience=audience)
    (house_dir(root, HOUSE_NAME) / "lighthouse-policy.json").write_text(json.dumps(connection_policy(
        HOUSE_NAME, list(refs), actions=("recall", "read"), audience_map={r: [audience] for r in refs}, **policy)))
    return pub


S1_ACTIONS = ["recall", "read", "inject_context"]  # deciding inject_context needs read too (P11's S1 named two)


def _allow(led, layer, audience, memories):
    sel = parse_selector(_doc_of([audience], requesters=[AGENT], kinds=["memory"], memories=sorted(memories),
                                 actions=S1_ACTIONS, purposes=["session-recall"]))
    do(led, ANDY, "allow", layer=layer, selector=sel, valid_from=T("2026-11-01"),
       valid_until=T("2026-11-01") + 300 * 86400, reason="a crossing (S1)")


def remote_ledger(root, mode="enforce", *, register=True, place=OUTSIDE, home_audience="commons", home_allow=True,
                  outside_allow=True, memories=(M1_OBJ,)):
    """Andy's ledger with S1's records: `remote-stores` registered once, acting for his home, placed at the root place
    `place:outside-home`, and two allows of `memories` to it (audience commons), one in his home's layer and one in
    `place:outside-home`'s. Each part can be left out or changed."""
    make_house(root, "lighthouse")
    led = Ledger.create(root, "andy", now=T("2026-11-01"))
    do(led, ANDY, "register-store", instance_id=SOURCE_ID, name="engram", owner=ANDY, place=HOME, imprint_of=None)
    do(led, ANDY, "register-store", instance_id=HOUSE_ID, name="published house", owner=ANDY, place=HOME,
       imprint_of=None)
    do(led, ANDY, "register-place", place=OUTSIDE, name="Outside home")
    if register:
        do(led, ANDY, "register-agent", agent=AGENT, acts_for=HOME)
        do(led, ANDY, "put-agent", agent=AGENT, place=place)
    if home_allow:
        _allow(led, HOME, home_audience, memories)
    if outside_allow:
        _allow(led, OUTSIDE, "commons", memories)
    if mode != "off":
        raise_gate(led, mode)
    led.close()


def remote_daemon(root, mode="enforce", refs=(REF,), **ledger):
    pub = remote_house(root, refs)
    remote_ledger(root, mode, **ledger)
    return _daemon_over(root, [pub], clock=at(DAEMON_CLOCK))


def recall_as(daemon, receiver=REF, query=M1_TEXT, k=5):
    return daemon.handle_frame(recall_frame(receiver=receiver, publisher=HOUSE_NAME, context=CONTEXT,
                                            purpose="session-recall", query=query, k=k, at=NOW))


def read_as(daemon, turn_id, ids, receiver=REF, publisher=HOUSE_NAME):
    return daemon.handle_frame(read_frame(receiver=receiver, publisher=publisher, context=CONTEXT,
                                          purpose="session-recall", turn_id=turn_id, memory_ids=list(ids)))


def delivered(daemon, receiver=REF, ids=(M1_ID, M2_ID)):
    """The memory ids a remote recall then read delivers with content."""
    trace = recall_as(daemon, receiver)
    assert trace["kind"] == "recall_result", trace
    offered = [c["memoryId"] for c in trace["candidates"]]
    wanted = [i for i in ids if i in offered]
    if not wanted:
        return []
    reply = read_as(daemon, trace["turnId"], wanted, receiver)
    assert reply["kind"] == "read_result", reply
    return [item["memoryId"] for item in reply["items"] if item["content"] is not None]


def ledger_refusal(daemon, obj=M1_OBJ, action="inject_context"):
    """The ledger's verdict on `obj` for a remote frame, from the daemon's own ledger side: its place, and its refusal
    code or None when it allows."""
    from lighthouse_daemon import _FrameHouse
    from lighthouse_policy import Decision
    pub = daemon.publishers[HOUSE_NAME]
    storage = pub.checkout() if pub.open() else None
    frame = recall_frame(receiver=REF, publisher=HOUSE_NAME, context=CONTEXT, purpose="session-recall", query="q",
                         k=5, at=NOW)
    side, _ = daemon._ledger_side(_FrameHouse(pub, storage), frame, daemon._gate(), Decision("allow", "allow", None))
    try:
        decision = side.decide(obj, action)
        return side.place, None if decision.allowed else decision.refusal.code
    finally:
        side.close()
        pub.checkin(storage)


def disclosures(root):
    import sqlite3
    path = house_dir(root, HOUSE_NAME) / "lighthouse-disclosures.db"
    if not path.is_file():
        return []
    con = sqlite3.connect(path)
    try:
        return [r[0] for r in con.execute("SELECT receiver FROM disclosures")]
    finally:
        con.close()


# ---------------------------------------------------------------- refs

def test_receiver_ref_maps_local_names_as_today_and_keeps_a_store_ref():
    from sharing import REMOTE_SHIP_REF, REMOTE_STORE_REF, RESERVED_AGENT, is_remote, receiver_ref
    assert receiver_ref("tardis") == "urn:engram:tardis"
    assert receiver_ref(REF) == REF
    assert REMOTE_STORE_REF.fullmatch(REF) and REMOTE_SHIP_REF.fullmatch(f"urn:superyak:{PEER_A}:ship:" + "c" * 32)
    assert is_remote(REF) and not is_remote("tardis") and RESERVED_AGENT == "remote-stores"
    for bad in (f"urn:superyak:{PEER_A}:store:not-a-uuid", f"urn:superyak:{PEER_A[:-1]}:store:{X}",
                f"urn:superyak:{PEER_A}:ship:x", "urn:superyak:", "has:colon", "", "x" * 65):
        with pytest.raises(ValueError):
            receiver_ref(bad)


@pytest.mark.parametrize("receiver", [f"urn:superyak:{PEER_A}:store:not-a-uuid", f"urn:superyak:{PEER_A}:ship:abc",
                                      "urn:superyak:" + "A" * 64 + f":store:{X}", f"urn:superyak:{PEER_A}:store:{X}x"])
def test_a_malformed_remote_receiver_is_refused_before_any_read(tmp_path, receiver):
    d = remote_daemon(tmp_path)
    reply = recall_as(d, receiver)
    assert (reply["kind"], reply.get("code")) == ("error", "MALFORMED_FRAME")
    assert disclosures(tmp_path) == []


# ---------------------------------------------------------------- the ledger, under enforce

def test_registered_with_both_allows_an_allowed_memory_is_delivered_and_one_kept_home_is_not(tmp_path):
    d = remote_daemon(tmp_path)
    assert delivered(d) == [M1_ID]  # m2 isn't named by S1's allows: the ledger keeps it at home
    [*_, last] = receipt_rows(tmp_path, action="inject_context")
    assert last["agent"] == AGENT and last["place"] == OUTSIDE


def test_with_remote_stores_unregistered_nothing_is_delivered_and_the_refusal_is_unknown_requester(tmp_path):
    d = remote_daemon(tmp_path, register=False)
    assert recall_as(d)["candidates"] == [] and delivered(d) == []
    assert ledger_refusal(d) == ("", "UNKNOWN_REQUESTER")
    assert ledger_refusal(remote_daemon(tmp_path / "registered")) == (OUTSIDE, None)


@pytest.mark.parametrize("missing", ["home_allow", "outside_allow"])
def test_with_either_allow_missing_nothing_is_delivered(tmp_path, missing):
    d = remote_daemon(tmp_path, **{missing: False})
    assert delivered(d) == []


def test_placed_anywhere_else_nothing_is_delivered(tmp_path):
    d = remote_daemon(tmp_path, place=HOME)
    assert delivered(d) == []


def test_a_self_allow_never_reaches_remote_stores_even_once_the_place_has_a_parent(tmp_path, monkeypatch):
    """M2: `self` doesn't reach a root place, so a home `self` allow in place of S1's `commons` one delivers nothing.
    With a parent the home would dominate the place, and every `self` allow there would reach every remote store, so
    the daemon treats `remote-stores` as unplaced and every crossing is refused (UNKNOWN_REQUESTER). The ledger itself
    never gives place:outside-home a parent (P26: a one-segment name is a root and takes none, at registration or by
    add-parent), so the parent is simulated here, in the one function every dominance and the daemon's check read."""
    d = remote_daemon(tmp_path, home_audience="self")
    assert delivered(d) == []
    import permissions
    real = permissions._parents
    monkeypatch.setattr(permissions, "_parents",
                        lambda state, place: [HOME] if place == OUTSIDE else real(state, place))
    d = remote_daemon(tmp_path / "parented", home_audience="self")
    assert delivered(d) == []
    assert ledger_refusal(d) == ("", "UNKNOWN_REQUESTER")


def test_with_no_receiver_file_anywhere_a_remote_crossing_is_still_delivered(tmp_path):
    """Re-check 2, change 1: the receiver's legacy layer is left out for a remote ref (the receiver checked its own
    policy before asking), so a missing receiver file can't refuse every crossing under enforce."""
    d = remote_daemon(tmp_path)
    assert not list((tmp_path / ".engram" / "instances").glob("*/lighthouse-receiver.toml"))
    assert delivered(d) == [M1_ID]


def test_no_local_file_or_agent_named_like_the_store_contributes(tmp_path, monkeypatch):
    """Spec section 4, "No local file": an instance directory named like the remote instance, with receiver settings
    that would refuse, and a ledger agent of that name, change nothing; the receiver policy is never loaded."""
    import lighthouse_daemon
    d = remote_daemon(tmp_path)
    inst = house_dir(tmp_path, X)
    (inst / "lighthouse-receiver.toml").write_text('enabled = true\npublishers = ["nobody"]\nsocket_path = "s"\n'
                                                   'policy_path = "missing.json"\n')
    led = Ledger.open(tmp_path)
    try:
        do(led, ANDY, "register-agent", agent=f"agent:{X}", acts_for=HOME, now="2026-11-02")
    finally:
        led.close()

    def never(self):
        raise AssertionError("a remote frame loaded a receiver policy")
    monkeypatch.setattr(lighthouse_daemon._LedgerSide, "_load_receiver_policy", never)
    assert delivered(d) == [M1_ID]


def test_the_audience_is_the_exact_ref(tmp_path):
    """Spec section 4, "Audience": with only <A>:store:<X> granted, <A>:store:<Y> and <B>:store:<X> get nothing."""
    d = remote_daemon(tmp_path)
    for other in (f"urn:superyak:{PEER_A}:store:{Y}", f"urn:superyak:{PEER_B}:store:{X}"):
        assert delivered(d, other) == []
    assert delivered(d) == [M1_ID]


# ---------------------------------------------------------------- P10: enforce only, no imprint, at most 5 ids

@pytest.mark.parametrize("mode", ["off", "shadow", "closed"])
def test_a_remote_frame_outside_enforce_is_publisher_unavailable_with_no_disclosure(tmp_path, mode):
    if mode == "closed":
        d = remote_daemon(tmp_path, "enforce")
        from permission_ledger import Gate
        d._gate = lambda: Gate("closed", "a test closes it")
    else:
        d = remote_daemon(tmp_path, mode)
    for reply in (recall_as(d), read_as(d, "turn-1", [M1_ID])):
        assert (reply["kind"], reply.get("code")) == ("error", "PUBLISHER_UNAVAILABLE")
    assert disclosures(tmp_path) == []


def test_an_imprint_house_refuses_a_remote_frame(tmp_path):
    import sqlite3
    d = remote_daemon(tmp_path)
    con = sqlite3.connect(house_dir(tmp_path, HOUSE_NAME) / "graph.db")
    con.execute("INSERT OR REPLACE INTO meta (key, value) VALUES ('instance_id_origin', 'imprint')")
    con.commit()
    con.close()
    reply = recall_as(d)
    assert (reply["kind"], reply.get("code")) == ("error", "PUBLISHER_UNAVAILABLE")
    assert disclosures(tmp_path) == []


def test_a_remote_read_of_six_ids_is_malformed(tmp_path):
    d = remote_daemon(tmp_path)
    reply = read_as(d, "turn-1", [str(uuid.UUID(int=n)) for n in range(1, 7)])
    assert (reply["kind"], reply.get("code")) == ("error", "MALFORMED_FRAME")
    assert disclosures(tmp_path) == []


def test_a_local_frame_whose_receiver_is_remote_stores_is_malformed(tmp_path):
    """Nit 4: an instance directory of that name can appear without fork_instance, and its frames would otherwise be
    judged as the reserved agent."""
    d = remote_daemon(tmp_path)
    house_dir(tmp_path, "remote-stores")
    assert (house_dir(tmp_path, "remote-stores")).is_dir()
    for reply in (recall_as(d, "remote-stores"), read_as(d, "turn-1", [M1_ID], "remote-stores")):
        assert (reply["kind"], reply.get("code")) == ("error", "MALFORMED_FRAME")
    assert disclosures(tmp_path) == []


# ---------------------------------------------------------------- records

def test_after_unshare_the_memory_is_not_delivered(tmp_path):
    import sqlite3
    d = remote_daemon(tmp_path)
    assert delivered(d) == [M1_ID]
    con = sqlite3.connect(house_dir(tmp_path, HOUSE_NAME) / "graph.db")
    con.execute("DELETE FROM shared_memories WHERE memory_id = ?", (M1_ID,))
    con.commit()
    con.close()
    assert delivered(d) == []


def test_the_sidecar_names_the_store_ref(tmp_path):
    d = remote_daemon(tmp_path)
    delivered(d)
    assert disclosures(tmp_path) == [REF, REF]


# ---------------------------------------------------------------- Task 9: the turnId binding (P13, S-f)

class MovingClock:
    def __init__(self, t=DAEMON_CLOCK):
        self.t = float(t)

    def __call__(self):
        from datetime import datetime, timezone
        return datetime.fromtimestamp(self.t, tz=timezone.utc)


def bound_daemon(root, *, other_house=False):
    """remote_daemon on a clock the test moves, and with `other_house` a second published house, `other`, granting
    the same ref."""
    clock = MovingClock()
    pub = remote_house(root)
    pubs = [pub]
    if other_house:
        other = make_placed_house(root, name="other", house_id="HOUSE2")
        (house_dir(root, "other") / "lighthouse-policy.json").write_text(json.dumps(connection_policy(
            "other", [REF], actions=("recall", "read"), audience_map={REF: ["commons"]})))
        pubs.append(other)
    remote_ledger(root)
    return _daemon_over(root, pubs, clock=clock), clock


def unbound(reply):
    return (reply["kind"], reply.get("code")) == ("error", "TURN_UNBOUND")


def test_a_remote_read_inside_30_seconds_succeeds_twice(tmp_path):
    d, clock = bound_daemon(tmp_path)
    trace = recall_as(d)
    clock.t += 30.0
    for _ in range(2):
        reply = read_as(d, trace["turnId"], [M1_ID])
        assert reply["kind"] == "read_result" and reply["items"][0]["content"] == M1_TEXT


def test_a_remote_read_of_an_unknown_turn_is_unbound_with_no_disclosure(tmp_path):
    d, clock = bound_daemon(tmp_path)
    recall_as(d)
    before = disclosures(tmp_path)
    assert unbound(read_as(d, str(uuid.uuid4()), [M1_ID]))
    assert disclosures(tmp_path) == before


def test_a_remote_read_by_another_receiver_ref_is_unbound(tmp_path):
    d, clock = bound_daemon(tmp_path)
    trace = recall_as(d)
    before = disclosures(tmp_path)
    for other in (f"urn:superyak:{PEER_A}:store:{Y}", f"urn:superyak:{PEER_B}:store:{X}"):
        assert unbound(read_as(d, trace["turnId"], [M1_ID], receiver=other))
    assert disclosures(tmp_path) == before


def test_a_remote_read_from_another_publisher_is_unbound(tmp_path):
    d, clock = bound_daemon(tmp_path, other_house=True)
    trace = recall_as(d)
    assert unbound(read_as(d, trace["turnId"], [M1_ID], publisher="other"))


def test_a_remote_read_of_an_id_not_returned_is_unbound(tmp_path):
    d, clock = bound_daemon(tmp_path)
    trace = recall_as(d)
    assert [c["memoryId"] for c in trace["candidates"]] == [M1_ID]
    assert unbound(read_as(d, trace["turnId"], [M2_ID]))
    assert unbound(read_as(d, trace["turnId"], [M1_ID, M2_ID]))


def test_a_remote_read_after_30_seconds_is_unbound(tmp_path):
    d, clock = bound_daemon(tmp_path)
    trace = recall_as(d)
    clock.t += 30.001
    assert unbound(read_as(d, trace["turnId"], [M1_ID]))


def test_the_binding_keeps_at_most_1000_turns_dropping_the_oldest(tmp_path, monkeypatch):
    import lighthouse_daemon
    assert lighthouse_daemon.TURNS_KEPT == 1000
    monkeypatch.setattr(lighthouse_daemon, "TURNS_KEPT", 3)
    d, clock = bound_daemon(tmp_path)
    first = recall_as(d)
    later = [recall_as(d) for _ in range(3)]
    assert unbound(read_as(d, first["turnId"], [M1_ID]))
    assert read_as(d, later[0]["turnId"], [M1_ID])["kind"] == "read_result"


def test_a_local_read_with_an_old_turn_still_succeeds(tmp_path):
    """The `context` re-read: a local read by turnId minutes after its recall is unchanged (local frames never touch
    the binding)."""
    from tests.test_lighthouse_daemon import CONTEXT as LOCAL_CONTEXT
    clock = MovingClock()
    pub = make_placed_house(tmp_path)  # its policy grants the local receiver `engram`
    d = _daemon_over(tmp_path, [pub], clock=clock)
    trace = d.handle_frame(recall_frame(receiver="engram", publisher=HOUSE_NAME, context=LOCAL_CONTEXT,
                                        purpose="session-recall", query=M1_TEXT, k=5, at=NOW))
    clock.t += 31
    reply = d.handle_frame(read_frame(receiver="engram", publisher=HOUSE_NAME, context=LOCAL_CONTEXT,
                                      purpose="session-recall", turn_id=trace["turnId"], memory_ids=[M1_ID]))
    assert reply["kind"] == "read_result" and reply["items"][0]["content"] == M1_TEXT
    reply = d.handle_frame(read_frame(receiver="engram", publisher=HOUSE_NAME, context=LOCAL_CONTEXT,
                                      purpose="session-recall", turn_id="never-recalled", memory_ids=[M1_ID]))
    assert reply["kind"] == "read_result" and reply["items"][0]["content"] == M1_TEXT
