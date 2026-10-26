"""Task 29: E1, the worked example of P 13 end to end, on one ledger, under `enforce`.

Fixtures go through `Ledger.perform` (the county's stewards as actors, channel `terminal`), the daemon's
`handle_frame` with hand-written legacy policies (P 13, "Legacy layers"), `permissions.gluing`, `server._keep_check`
and `Uses.owner_list`. The clock moves from step to step: the daemon's clock for what the daemon decides, the `now` of
each ledger act, and the `now` the remember guard is given."""
import dataclasses
import hashlib
import json
import sqlite3

import server
import sharing
from permission_ledger import Ledger
from permission_uses import Uses, pseudonym
from permissions import (Act, annotation_line, decide, disagreement_words, gluing, receipt_short, selector_json,
                         short_id)
from storage import Storage
from tests.permissions_support import (
    ANDY, CLINIC_3, HOME, HOUSE_ID, HOUSE_NAME, M1, M1_ID, M2, M2_ID, M3, M3_ID, M4, MEDICAL, OUTSIDE_HOME,
    PH, RIO, SOURCE_ID, SW, CachedRig, Clock, T, _daemon_over, _memory_n, connection_policy, d1_selector,
    e1_county_ledger, do, house_dir, make_house, make_placed_house, parks_proposal_body, only_proposal_rows_changed,
    raise_gate, read_by_ph, receipt_rows, write_receiver_files)
from tests.test_lighthouse_daemon import unit

BOTH = ("care-coordination", "program-operations")
RECEIVERS = ("ph-coordinator", "parks-planner", "sw-helper")
DAY = 86400


def write_legacy_layers(root):
    """P 13, "Legacy layers (E1)": the publisher's policy and each receiver's, by hand. The publisher allows recall and
    read, a receiver recall, read and inject_context, for `memory/technical` and both purposes; `engram:audiences`
    gives each receiver `commons`."""
    names = [f"urn:engram:{r}" for r in RECEIVERS]
    path = house_dir(root, HOUSE_NAME) / "lighthouse-policy.json"
    path.write_text(json.dumps(connection_policy(
        HOUSE_NAME, names, actions=("recall", "read"), purposes=BOTH, audience_map={n: ["commons"] for n in names})))
    for receiver in RECEIVERS:
        write_receiver_files(root, receiver, publisher=HOUSE_NAME, purposes=BOTH)


def place_m4(pub):
    """The lab result m4 enters the published house (use 7), as an outside-home placement of source memory m4."""
    memory_id, text = _memory_n(4)
    store = Storage(str(pub.db_path))
    try:
        store.add_episode(memory_id, "s", text, embedding=unit(text))
        store.conn.execute(
            "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, audience, reason, "
            "content_digest, shared_at, source_instance_id, record_id) VALUES (?,?,?,?,?,?,?,?,?,?,NULL)",
            ("share-4", memory_id, "engram", "m4", "episode", OUTSIDE_HOME, "test",
             hashlib.sha256(text.encode()).hexdigest(), "2026-11-05", SOURCE_ID))
        store.conn.commit()
    finally:
        store.close()
    return memory_id, text


def link_placements_to(pub, record_id):
    """Every placement in the house is linked to `record_id`, as `share` does for the allow it relies on (P29)."""
    con = sqlite3.connect(pub.db_path)
    try:
        con.execute("UPDATE shared_memories SET record_id = ?", (record_id,))
        con.commit()
    finally:
        con.close()


def cited_records(row, action):
    """The records the receipt cites for `action`, whatever the layer."""
    out = set()
    for c in json.loads(row["cited"]):
        if c.get("action") == action and c.get("verdict") == "allow":
            out |= set(c["records"]) if "records" in c else {c["record"]}
    return out - {None}


def test_e1_andys_medical_history(tmp_path, monkeypatch):
    root = tmp_path
    monkeypatch.setattr(server, "ENGRAM_HOME", root)

    # ---- the world: the county, Andy's side (R1, G1), the published house, the legacy layers, the gate raised
    pub = make_placed_house(root, receiver="ph-coordinator", audience=OUTSIDE_HOME, purposes=BOTH)
    make_house(root, "lighthouse")
    led = e1_county_ledger(root)
    ids = led.ids
    raise_gate(led, "enforce", now="2026-11-02")
    write_legacy_layers(root)
    link_placements_to(pub, ids.R1)
    clock = Clock(T("2026-11-02"))
    daemon = _daemon_over(root, [pub], clock=clock)

    def rig(receiver, purpose):
        return CachedRig(daemon, root, clock, {pub.name: pub}, receiver=receiver, purpose=purpose)

    ph = rig("ph-coordinator", "care-coordination")
    parks = rig("parks-planner", "program-operations")
    helper = rig("sw-helper", "program-operations")

    def state():
        return led.state()

    def on(day):
        clock.t = T(day)

    # ---- use 1: ph-coordinator recalls, then is delivered m1, for care-coordination
    on("2026-11-02")
    candidates = {c["memoryId"] for c in ph.recall()["candidates"]}
    assert candidates == {M1_ID, M2_ID}, "use 1: the recall returns m1 and m2, and m3 is filtered"
    [recall_1] = receipt_rows(root, "recall")
    assert recall_1["filtered"] == 1 and json.loads(recall_1["returned"]) == [M1, M2], "use 1: filtered 1"
    item = ph.read(M1_ID)
    assert item["content"], "use 1: the delivery of m1 is allowed"
    [delivery_1] = receipt_rows(root, "inject_context")
    assert delivery_1["allowed"] == 1 and delivery_1["copy"] == f"store:{HOUSE_ID}", "use 1: copy h is the house"
    assert delivery_1["object"] == M1, "use 1: the delivery names m1"
    assert delivery_1["until"] == delivery_1["horizon"] == T("2027-01-31"), "use 1: until and horizon 2027-01-31"
    for action in ("recall", "read", "inject_context"):
        assert cited_records(delivery_1, action) == {ids.R1, ids.C1, ids.H1, ids.L1}, f"use 1: {action} cites R1 C1 H1 L1"
    assert annotation_line(item["permission"]) == (
        f"laid by andy (engram) · allowed by home/andy {short_id(ids.R1)}, la-county {short_id(ids.C1)}, "
        f"public-health {short_id(ids.H1)}, clinic-3 {short_id(ids.L1)} · until 2027-01-31 · "
        f"receipt {receipt_short(delivery_1['id'])}"), "use 1: the annotation line"
    delivered_at = delivery_1["at"]

    # ---- use 12 and the first half of use 13: public health asks to keep m1, an hour after the delivery
    on("2026-11-02")
    keep_1 = {"error": "keeping this content is not allowed", "layer": "rejected"}
    assert server._keep_check(item["content"], agent="agent:ph-coordinator", now=delivered_at + 3600) == keep_1, \
        "use 13: a verbatim remember within 24 hours of the delivery is refused"
    [imprint_1] = receipt_rows(root, "imprint")
    assert json.loads(imprint_1["refusal"]) == {"code": "NO_ALLOW", "layer": HOME, "action": "imprint"}, \
        "use 12: no imprint is allowed, and Andy's layer, first in the order, refuses"

    # ---- use 2: m3, asked for by an id Andy gave the agent
    refused_3 = ph.read(M3_ID)
    assert refused_3["content"] is None and "permission" not in refused_3, "use 2: content is null"
    assert refused_3["audiences"] == [], "use 2: the item says nothing more"
    refused_row = [r for r in receipt_rows(root, "inject_context") if r["object"] == M3][-1]
    assert refused_row["allowed"] == 0 and json.loads(refused_row["refusal"])["code"] == "NO_ALLOW", "use 2: NO_ALLOW"
    assert json.loads(refused_row["refusal"])["layer"] == "place:home/jenn", "use 2: at Jenn's home layer"
    assert "jenn" not in json.dumps(refused_3), "use 2: the agent is not told why"
    uses = Uses.open(root)
    try:
        agent_view = uses.agent_view("agent:ph-coordinator")
        assert {"object": M3, "at": refused_row["at"], "outcome": "not allowed"} in agent_view, \
            "use 2: the agent's view says 'not allowed'"
        assert "jenn" not in json.dumps(agent_view).lower(), "use 2: the agent's view never says m3 is about Jenn"
        owner = uses.owner_list(state(), collection=MEDICAL)
        [row_3] = [r for r in owner.rows if r["object"] == M3]
        assert row_3["notes"] == ["m3: needs Jenn's yes"], "use 2: the owner's list says whose yes m3 needs"
        salt = state().places[CLINIC_3].pseudonym_salt
        steward_view = uses.place_view(state(), CLINIC_3)
        [steward_3] = [r for r in steward_view.rows if r["id"] == refused_row["id"]]
        assert steward_3["refusal"]["layer"] == pseudonym(salt, "person:jenn"), \
            "use 2: clinic-3's stewards see Jenn's pseudonym"
        assert "place:home/jenn" not in json.dumps(steward_view.rows), "use 2: never place:home/jenn"
    finally:
        uses.close()

    # ---- use 3: parks-planner recalls for program-operations
    assert parks.recall()["candidates"] == [], "use 3: no candidates"
    [recall_3] = [r for r in receipt_rows(root, "recall") if r["agent"] == "agent:parks-planner"]
    assert recall_3["filtered"] == 3, "use 3: the receipt counts 3 filtered"
    assert recall_3["object"] is None and json.loads(recall_3["returned"]) == [], "use 3: it names no memory"
    con = sqlite3.connect(root / ".engram" / "permission-uses.db")
    try:
        subjects = con.execute("SELECT COUNT(*) FROM use_subjects WHERE use_seq = ?", (recall_3["seq"],)).fetchone()[0]
    finally:
        con.close()
    assert subjects == 0 and "jenn" not in json.dumps(recall_3), "use 3: the receipt names no subject"

    # ---- use 4: sw-helper recalls for program-operations
    assert helper.recall()["candidates"] == [], "use 4: no candidates, though public health's H2 lets Summer Wellness recall"

    # ---- use 5: the gluing check at Summer Wellness
    report = gluing(state(), SW)
    assert report.delta and not report.ineffective and not report.too_complex, "use 5: Delta is not empty, no ineffective part"
    assert disagreement_words(state(), report) == (
        "Parks and Recreation allows read in Summer Wellness for program-operations; Public Health does not. "
        "Until one of you changes your rules, Summer Wellness may only recall."), "use 5: the sentence of section 8"

    # ---- use 6: Rio Grande tries to add parks-and-rec to R1
    before = led.tables()
    tried = led.perform(Act("allow", parks_proposal_body()), actor=RIO, channel="tool", now=T("2026-11-03"))
    assert tried.status == "proposal", "use 6: outside G1's envelope, so a proposal"
    [proposal] = led.proposals(now=T("2026-11-03"))
    assert proposal["words"] == (
        "Share collection andy/medical-history with place:la-county/parks-and-rec, for care-coordination, until "
        "2027-01-31. Agents that act for a place Parks and Recreation dominates, working there, may use it. Parks and "
        "Recreation's stewards, and LA County's above it, decide which agents those are."), "use 6: P 13's words (the template of 7.7 sets off the purposes and the end with commas)"
    do(led, ANDY, "decline", now="2026-11-03", proposal=tried.ref)
    assert only_proposal_rows_changed(before, led.tables()), "use 6: Andy declines, and the tables are unchanged"

    # ---- use 7: Rio Grande adds m4 (a lab result) to the collection, under G1
    place_m4(pub)
    link_placements_to(pub, ids.R1)
    collected = do(led, RIO, "collect", now="2026-11-05", channel="tool", collection=MEDICAL, objects=[M4])
    assert collected.status == "done", "use 7: collect of m4 under G1 is allowed"
    [m4_member] = [r for r in state().collection_members[MEDICAL] if r.object == M4]
    assert m4_member.backing == f"grant:{ids.G1}", "use 7: the membership is backed by G1"
    d_m4 = decide(state(), read_by_ph(M4, T("2026-11-06")))
    assert d_m4.allowed and d_m4.until == d_m4.horizon == T("2026-11-30"), "use 7: m4 is covered until G1 expires"
    assert pub_m4[0]

    # ---- use 8: 2026-11-10, Rio Grande shortens R1 to 2026-12-15
    out = do(led, RIO, "shorten", now="2026-11-10", channel="tool", record=ids.R1, valid_until=T("2026-12-15"))
    r1, r1p = state().records[ids.R1], state().records[out.ref]
    assert (r1p.replaces, r1p.anchor, r1p.backing, r1p.set_by, r1p.under_grant) == (
        ids.R1, r1.anchor, "person", RIO, ids.G1), "use 8: R1' replaces R1, person-backed, set by Rio Grande under G1"
    assert r1.revoked_seq == r1p.created_seq, "use 8: R1 is revoked in the same transaction"
    assert (r1p.selector, r1p.valid_from) == (r1.selector, r1.valid_from) and r1p.valid_until == T("2026-12-15") \
        <= r1.valid_until, "use 8: R1' lies inside R1"
    ids.R1P = out.ref

    # ---- use 9: 2026-11-12, Andy denies m2 from 2026-12-01
    d1 = do(led, ANDY, "deny", now="2026-11-12", layer=HOME, selector=d1_selector(), valid_from=T("2026-12-01"),
            valid_until=None, reason="tell my doctor first")
    ids.D1 = d1.ref
    d_m2 = decide(state(), read_by_ph(M2, T("2026-11-13")))
    assert d_m2.allowed and d_m2.until == d_m2.horizon == T("2026-12-01"), "use 9: m2's next decision ends 2026-12-01"
    d1_selector_now = state().records[ids.D1].selector
    for act in (Act("revoke", {"record": ids.D1, "reason": "r"}),
                Act("shorten", {"record": ids.D1, "valid_until": T("2026-12-10")}),
                Act("narrow", {"record": ids.D1, "selector": selector_json(dataclasses.replace(
                    d1_selector_now, audience=(CLINIC_3,)))})):
        before = led.tables()
        tried = led.perform(act, actor=RIO, channel="tool", now=T("2026-11-13"))
        assert tried.status == "proposal" and only_proposal_rows_changed(before, led.tables()), \
            f"use 9: Rio Grande's {act.kind} of D1 is a proposal"
    assert state().records[ids.D1].revoked_seq is None, "use 9: D1 stands"

    # ---- use 10: 2026-11-20, Andy revokes G1
    do(led, ANDY, "revoke-grant", now="2026-11-20", grant=ids.G1)
    assert state().records[ids.R1P].revoked_seq is None, "use 10: R1' stays, being person-backed"
    on("2026-11-20")
    refused_4 = ph.read(str(_memory_n(4)[0]))
    assert refused_4["content"] is None, "use 10: m4 is no longer covered"
    m4_row = [r for r in receipt_rows(root, "inject_context") if r["object"] == M4][-1]
    assert json.loads(m4_row["refusal"]) == {"code": "GRANT_INVALID", "layer": HOME, "action": "recall"}, \
        "use 10: GRANT_INVALID at place:home/andy, action recall"
    after_expiry = decide(state(), read_by_ph(M4, T("2026-11-30")))
    assert (after_expiry.refusal.code, after_expiry.refusal.layer) == ("EXPIRED", HOME), \
        "use 10: from 2026-11-30 the code is EXPIRED"
    assert decide(state(), read_by_ph(M1, T("2026-11-21"))).allowed, "use 10: m1 is still allowed under R1'"

    # ---- use 11: 2026-12-01, no ledger write since use 10
    on("2026-11-21")
    assert {c["memoryId"] for c in ph.recall()["candidates"]} == {M1_ID, M2_ID}, "use 11: before D1, m1 and m2 are served"
    [horizon] = [e.eligible.horizon for key, e in daemon._cache.items()
                 if key[:2] == (pub.db_path, "agent:ph-coordinator")]
    # Ledger ruling 'Task 6, horizon': the broader reading also counts m4's G1-backed membership, which ended 11-30
    assert horizon == T("2026-11-30") <= T("2026-12-01"), "use 11: the cache entry has a horizon before D1 begins"
    built = ph.rebuilds
    seq_before = state().seq
    on("2026-12-01")
    assert {c["memoryId"] for c in ph.recall()["candidates"]} == {M1_ID}, "use 11: m2 is gone from the recall"
    assert ph.rebuilds == built + 1 and state().seq == seq_before, \
        "use 11: the daemon decided again at the horizon, with no write to the ledger since use 10"
    refused_2 = ph.read(M2_ID)
    assert refused_2["content"] is None, "use 11: the delivery of m2 is refused"
    m2_row = [r for r in receipt_rows(root, "inject_context") if r["object"] == M2][-1]
    assert json.loads(m2_row["refusal"])["code"] == "DENIED" and json.loads(m2_row["refusal"])["layer"] == HOME, \
        "use 11: DENIED at place:home/andy"
    assert ph.read(M1_ID)["content"], "use 11: m1 is still allowed"
    delivered_12_01 = receipt_rows(root, "inject_context")[-1]

    # ---- use 12: the imprint, again under R1'
    assert server._keep_check(item["content"], agent="agent:ph-coordinator", now=delivered_12_01["at"] + 60) == keep_1, \
        "use 12: imprint of m1 is refused"
    imprint_2 = receipt_rows(root, "imprint")[-1]
    assert json.loads(imprint_2["refusal"]) == {"code": "NO_ALLOW", "layer": HOME, "action": "imprint"}, \
        "use 12: R1' lists no imprint, so NO_ALLOW at place:home/andy"

    # ---- use 13: 2026-12-15T00:00:00Z, R1' ends
    on("2026-12-15")
    expired = ph.read(M1_ID)
    assert expired["content"] is None, "use 13: the delivery of m1 is refused"
    expired_row = receipt_rows(root, "inject_context")[-1]
    assert json.loads(expired_row["refusal"])["code"] == "EXPIRED", "use 13: EXPIRED"
    swept = sharing.sweep_placements(published_storage=Storage(str(pub.db_path)), ledger=led, mode="enforce",
                                     now=T("2026-12-15"))
    house = sqlite3.connect(pub.db_path)
    try:
        left = house.execute("SELECT COUNT(*) FROM shared_memories").fetchone()[0]
    finally:
        house.close()
    assert swept.removed == 4 and left == 0, "use 13: the sweep removes the placements within a pass"
    assert server._keep_check(item["content"], agent="agent:ph-coordinator", now=T("2026-12-15")) is None, \
        "use 13: with no delivery of m1 in the last 24 hours the guard finds no receipt, and the keep passes"
    assert server._keep_decision(item["content"], agent="agent:ph-coordinator", now=T("2026-12-15")).source is None, \
        "use 13: the kept memory carries no source subjects"

    # ---- use 14: Andy lists his uses of the medical history; public health's stewards see the same
    uses = Uses.open_read_only(root)
    try:
        s = state()
        listed = uses.owner_list(s, collection=MEDICAL)
        got = sorted((r["at"], r["action"], r["object"] or r["kind"], r["outcome"]) for r in listed.rows)
        expected = sorted([
            (T("2026-11-02"), "recall", "recall", "allowed"),              # use 1: m1 and m2
            (T("2026-11-02"), "inject_context", M1, "allowed"),            # use 1: the delivery
            (T("2026-11-02") + 3600, "imprint", M1, "refused"),            # use 12 as the guard first saw it
            (T("2026-11-02"), "inject_context", M3, "refused"),            # use 2
            (T("2026-11-20"), "inject_context", M4, "refused"),            # use 10
            (T("2026-11-21"), "recall", "recall", "allowed"),              # use 11, before D1
            (T("2026-12-01"), "recall", "recall", "allowed"),              # use 11, at D1
            (T("2026-12-01"), "inject_context", M2, "refused"),            # use 11: the refused m2 read
            (T("2026-12-01"), "inject_context", M1, "allowed"),            # use 11: m1 still allowed
            (delivered_12_01["at"] + 60, "imprint", M1, "refused"),        # use 12
            (T("2026-12-15"), "inject_context", M1, "refused"),            # use 13: the expired read
        ])
        assert got == expected, "use 14: the owner's list"
        assert all(r["place"] and r["agent"] == "agent:ph-coordinator" and r["purpose"] == "care-coordination"
                   and r["cited"] for r in listed.rows if r["action"] != "imprint"), \
            "use 14: each row shows place, agent, purpose, records and time"
        assert all(r["records"] if "records" in r else True for r in listed.rows)
        assert not [r for r in listed.rows if r["action"] == "recall" and r["count"] == 0], "use 14: no filtered recall"
        assert listed.counts == {"total": len(expected), "local": len(expected), "imported": 0}, "use 14: counts"
        [expired_listed] = [r for r in listed.rows if r["refusal"] and r["refusal"]["code"] == "EXPIRED"]
        assert expired_listed["at"] == T("2026-12-15"), "use 14: the expired read"

        salt = s.places[PH].pseudonym_salt
        seen = uses.place_view(s, PH)
        ours = {r["id"] for r in listed.rows if r["place"] == CLINIC_3}
        assert {r["id"] for r in seen.rows} == ours, "use 14: public health's stewards see the same uses"
        assert all(pseudonym(salt, ANDY) in r["subjects"] for r in seen.rows if r["subjects"]), \
            "use 14: with Andy as a pseudonym"
        assert "andy" not in json.dumps(seen.rows).lower(), "use 14: Andy is never named to the stewards"
        filtered = sum(r["filtered"] or 0 for r in receipt_rows(root) if r["place"] == CLINIC_3 and not r["shadow"])
        assert seen.counts["filtered"] == filtered and filtered >= 1, "use 14: and the filtered counts"
    finally:
        uses.close()
        led.close()
