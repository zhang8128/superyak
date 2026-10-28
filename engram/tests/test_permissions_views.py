"""Task 15 (P 9.2, 9.3, U8, YN6, XS2): the views of the receipts."""
import hashlib
import json
import re

from permission_uses import Uses, UseRow, row_for_bulk, row_for_decision, row_for_recall
from permissions import BulkUse, GUARD_RECEIPTS, GUARD_SECONDS, USE_LIST_ROWS, decide, decide_bulk, subjects_of
from permission_uses import pseudonym
from tests.permissions_support import (
    CLINIC_3, HOME, M1, M2, M3, MEDICAL, T, andy_world, e1_world, use)

M5 = "mem:S/episode/m5"
STATION = "5d" + "c3" * 15
PH, PARKS = "place:la-county/public-health", "place:la-county/parks-and-rec"
LEDGER = "ledger-test"       # World's meta.ledger_id: a row with another ledger_id is an imported one (R14)


def sha(refs):
    return hashlib.sha256("\n".join(sorted(refs)).encode()).hexdigest()


def plain(at, obj=M1, *, allowed=1, **kw):
    """A local receipt with no cited layers, for the fixtures that need no decision."""
    fields = dict(at=at, ledger_id=LEDGER, ledger_seq=1, agent="agent:ph-coordinator", place=CLINIC_3,
                  acting_for=HOME, action="read", purpose="care-coordination", allowed=allowed, cited="[]",
                  object=obj, copy="store:house")
    return UseRow(**{**fields, **kw})


def imported(n, *, action, purpose="calibration", returned, objects, allowed=1, refusal=None, ledger_seq=None):
    """An imported station row in the imprints spec's form (P 9.1, the four differences)."""
    h = f"imprint:{STATION}/i1"
    row = UseRow(id="u-" + hashlib.sha256(f"{n}".encode()).hexdigest()[:32], at=T("2026-11-03") + n,
                 ledger_id=STATION, ledger_seq=n, agent="agent:station-imprints", place=HOME, acting_for=HOME,
                 action=action, purpose=purpose, allowed=allowed, cited='["r-' + "ab" * 16 + '"]', copy=h,
                 returned=None if returned is None else json.dumps(returned), refusal=refusal)
    return row, [("person:andy", o) for o in objects]


def local_state_and_uses(tmp_path):
    w, _ = e1_world(3)
    return Uses.open(tmp_path), w.state()


def e1_receipts(tmp_path):
    """The receipts of E1's uses 1 to 3, plus one refused bulk use by station-imprints (see the brief)."""
    uses, state = local_state_and_uses(tmp_path)
    at = T("2026-11-02")

    def ph(obj, action="recall"):
        return use("agent:ph-coordinator", CLINIC_3, obj, action=action, at=at)

    def pairs(u, objs):
        return [(s, o) for o in objs for s in subjects_of(state, o, u.at)]
    base = ph(M1)
    decisions = [decide(state, ph(m)) for m in (M1, M2)]
    assert all(d.allowed for d in decisions)
    uses.append(row_for_recall(decisions, base, acting_for=HOME, returned=[M1, M2], filtered=1, ledger_id=LEDGER),
                pairs(base, (M1, M2)))
    delivery = ph(M1, "inject_context")
    d = decide(state, delivery)
    assert d.allowed
    uses.append(row_for_decision(d, delivery, acting_for=HOME, content_digest="00" * 32, ledger_id=LEDGER),
                pairs(delivery, (M1,)))
    read = ph(M3, "read")
    d = decide(state, read)
    assert not d.allowed and d.refusal.layer == "place:home/jenn"
    uses.append(row_for_decision(d, read, acting_for=HOME, ledger_id=LEDGER), pairs(read, (M3,)))
    parks = use("agent:parks-planner", PARKS, M1, at=at)
    uses.append(row_for_recall([], parks, acting_for=HOME, returned=[], filtered=3, ledger_id=LEDGER), [])
    bulk = BulkUse(requester="agent:station-imprints", place=HOME, objects=(M1, M2), copy="store:house",
                   action="imprint", purpose="imprint-keep", at=at, named=True)
    d = decide_bulk(state, bulk)
    assert not d.allowed
    uses.append(row_for_bulk(d, bulk, acting_for=HOME, ledger_id=LEDGER), [("person:andy", M1), ("person:andy", M2)])
    return uses, state


def county_record_ids(state):
    return {r.id for r in state.records.values() if not r.layer.startswith("place:home/")}


def cited_ids(rows):
    return [rec for r in rows for c in r["cited"] for rec in c["records"]]


def receipts_around_a_late_co_subject(tmp_path):
    w = andy_world()
    w.person("amy")
    w.now = T("2026-11-03")
    w.subject(M5, "person:jenn")
    uses = Uses.open(tmp_path)
    uses.append(plain(T("2026-11-02"), M5), [("person:andy", M5)])
    uses.append(plain(T("2026-11-04"), M5), [("person:andy", M5), ("person:jenn", M5)])
    uses.append(plain(T("2026-11-04"), M1), [("person:andy", M1)])
    return uses, w.state()


def local_and_imported_rows(tmp_path):
    uses = Uses.open(tmp_path)
    uses.append(plain(T("2026-11-02")), [("person:andy", M1)])
    refs = ["mem:S/episode/e17", "mem:S/episode/e18"]
    row, subjects = imported(1, action="recall", returned={"count": 2, "sha256": sha(refs)}, objects=refs)
    uses.append_imported(row, subjects)
    return uses, andy_world().state()


def imported_admission_with_route(tmp_path):
    uses = Uses.open(tmp_path)
    refs = ["mem:S/episode/e17"]
    n = 0
    for action, purpose in (("recall", "calibration"), ("read", "calibration"), ("imprint", "calibration"),
                            ("recall", "trail-evaluation"), ("read", "trail-evaluation")):
        n += 1
        row, subjects = imported(n, action=action, purpose=purpose, returned={"count": 1, "sha256": sha(refs)},
                                 objects=refs)
        uses.append_imported(row, subjects)
    row, _ = imported(6, action="route", purpose="trail-evaluation", returned={"count": 3}, objects=[])
    uses.append_imported(row, [("person:andy", row.copy)])
    return uses, andy_world().state()


def imported_denied_with_route(tmp_path):
    uses = Uses.open(tmp_path)
    refs = ["mem:S/episode/e17"]
    refusal = json.dumps({"code": "NO_ALLOW", "layer": "place:la-county", "action": "route"})
    row, subjects = imported(1, action="read", returned={"count": 1, "sha256": sha(refs)}, objects=refs)
    uses.append_imported(row, subjects)
    row, _ = imported(2, action="route", purpose="trail-evaluation", returned=None, objects=[], allowed=0,
                      refusal=refusal)
    uses.append_imported(row, [("person:andy", row.copy)])
    return uses, andy_world().state()


def many_rows(tmp_path, n):
    uses = Uses.open(tmp_path)
    for i in range(n):
        uses.append(plain(T("2026-11-02") + i), [("person:andy", M1)])
    return uses, andy_world().state()


def receipts_with_self_claim(tmp_path):
    w = andy_world()
    w.now = T("2026-11-03")
    w.subject(M3, "person:jenn", self_claimed=True)
    uses = Uses.open(tmp_path)
    uses.append(plain(T("2026-11-04"), M3), [("person:andy", M3), ("person:jenn", M3)])
    uses.append(plain(T("2026-11-02"), M3), [("person:andy", M3)])      # before the claim: no note
    return uses, w.state()


# ---------------------------------------------------------------- the brief's tests

def test_u8_an_agent_sees_its_refusals_only_as_not_allowed(tmp_path):
    uses, state = e1_receipts(tmp_path)
    single = [r for r in uses.agent_view("agent:ph-coordinator") if r["object"] == M3][0]
    assert single["outcome"] == "not allowed" and set(single) == {"object", "at", "outcome"}
    bulk = [r for r in uses.agent_view("agent:station-imprints") if r.get("count") is not None][0]
    assert set(bulk) <= {"count", "sha256", "at", "outcome"} and "code" not in bulk     # BN4
    owner = uses.owner_list(state, obj=M3).rows[0]
    assert owner["refusal"]["layer"] == "place:home/jenn" and "m3: needs Jenn's yes" in owner["notes"]   # BN3


def test_u8_a_steward_sees_a_home_only_as_its_persons_pseudonym(tmp_path):
    uses, state = e1_receipts(tmp_path)
    view = uses.place_view(state, "place:la-county/public-health/clinic-3")
    refused = [r for r in view.rows if not r["allowed"]][0]
    jenn = pseudonym(state.places["place:la-county/public-health/clinic-3"].pseudonym_salt, "person:jenn")
    assert refused["refusal"]["layer"] == jenn and "place:home" not in json.dumps(view.rows)
    assert all(not rec.startswith("r-") or rec in county_record_ids(state) for rec in cited_ids(view.rows))
    assert view.counts["filtered"] >= 1


def test_u8_pseudonyms_are_stable_in_a_place_and_differ_across_places(tmp_path):
    uses, state = e1_receipts(tmp_path)
    clinic = state.places["place:la-county/public-health/clinic-3"].pseudonym_salt
    ph = state.places["place:la-county/public-health"].pseudonym_salt
    jenn_at_clinic, jenn_at_ph = pseudonym(clinic, "person:jenn"), pseudonym(ph, "person:jenn")
    assert re.fullmatch(r"[0-9a-f]{16}", jenn_at_clinic) and jenn_at_clinic == pseudonym(clinic, "person:jenn")
    assert jenn_at_clinic != jenn_at_ph and jenn_at_clinic != pseudonym(clinic, "person:andy")
    first = uses.place_view(state, "place:la-county/public-health/clinic-3").rows
    assert uses.place_view(state, "place:la-county/public-health/clinic-3").rows == first        # stable
    at_ph = json.dumps(uses.place_view(state, "place:la-county/public-health").rows)   # use 2 is at clinic-3, below it
    assert jenn_at_clinic in json.dumps(first) and jenn_at_ph in at_ph and jenn_at_clinic not in at_ph


def test_u8_agents_in_a_place_see_no_filtered_counts(tmp_path):
    uses, state = e1_receipts(tmp_path)    # use 1's recall filtered m3; use 3's recall by parks-planner filtered 3
    assert uses.place_view(state, "place:la-county/public-health/clinic-3").counts["filtered"] == 1   # stewards do
    assert uses.place_view(state, "place:la-county/parks-and-rec").counts["filtered"] == 3
    for agent in ("agent:ph-coordinator", "agent:parks-planner", "agent:station-imprints"):
        view = uses.agent_view(agent)
        assert all(set(r) <= {"object", "at", "outcome", "count", "sha256", "permission"} for r in view), agent
        assert "filtered" not in json.dumps(view), agent
    assert uses.agent_view("agent:parks-planner") == []    # its one receipt is a recall that returned nothing


def test_u8_a_subject_sees_only_receipts_naming_them_at_the_time(tmp_path):
    uses, state = receipts_around_a_late_co_subject(tmp_path)
    jenn = uses.subject_view("person:jenn")
    assert [(r["object"], r["at"]) for r in jenn] == [(M5, T("2026-11-04"))]     # the earlier use stays hidden
    assert set(jenn[0]) >= {"requester", "place", "action", "purpose", "records", "at", "outcome"}
    assert sorted(r["at"] for r in uses.subject_view("person:andy") if r["object"] == M5) == [
        T("2026-11-02"), T("2026-11-04")]
    assert uses.subject_view("person:amy") == []                                  # never a subject


def test_u8_imported_rows_are_marked_and_counted_apart_and_found_by_object(tmp_path):
    uses, state = local_and_imported_rows(tmp_path)
    lst = uses.owner_list(state)
    assert lst.counts["imported"] and all(r["station"] == STATION for r in lst.rows if r["imported"])
    assert uses.owner_list(state, obj="mem:S/episode/e17").rows                     # --object finds a batch row


def test_yn6_imported_admission_rows_are_per_action_and_purpose(tmp_path):
    uses, state = imported_admission_with_route(tmp_path)
    lst = uses.owner_list(state, action="read")
    assert {r["purpose"] for r in lst.rows} == {"calibration", "trail-evaluation"}
    assert uses.owner_list(state, action="read", purpose="trail-evaluation").counts["imported"] == 1


def test_xs2_a_null_returned_row_is_listed_as_not_counted(tmp_path):
    uses, state = imported_denied_with_route(tmp_path)
    [row] = [r for r in uses.owner_list(state).rows if r["kind"] == "roads-and-trails"]
    assert row["count"] == "not counted"


def test_the_list_shows_counts_then_the_200_newest_rows(tmp_path):
    uses, state = many_rows(tmp_path, 250)
    lst = uses.owner_list(state)
    assert lst.counts["total"] == 250 and len(lst.rows) == 200 and lst.rows[0]["at"] >= lst.rows[-1]["at"]


def test_u5_a_self_claim_appears_in_the_owners_list(tmp_path):
    uses, state = receipts_with_self_claim(tmp_path)
    assert "Jenn claimed m3 on 2026-11-03" in [n for r in uses.owner_list(state).rows for n in r["notes"]]


# ---------------------------------------------------------------- beyond the brief

def test_the_owner_list_leaves_out_a_recall_that_returned_nothing_and_counts_local_and_imported(tmp_path):
    uses, state = e1_receipts(tmp_path)
    lst = uses.owner_list(state)
    assert lst.counts == {"total": 4, "local": 4, "imported": 0}         # use 3's empty recall is not a use (9.1)
    assert all(r["agent"] != "agent:parks-planner" for r in lst.rows)
    assert "filtered" not in lst.counts


def test_owner_list_filters(tmp_path):
    uses, state = e1_receipts(tmp_path)
    assert [r["object"] for r in uses.owner_list(state, refused=True).rows if r["object"]] == [M3]
    assert uses.owner_list(state, refused=True).counts["total"] == 2         # the read of m3 and the bulk use
    assert uses.owner_list(state, action="inject_context").counts["total"] == 1
    assert uses.owner_list(state, since=T("2026-11-03")).counts["total"] == 0
    assert uses.owner_list(state, until=T("2026-11-02")).counts["total"] == 0       # half-open
    assert uses.owner_list(state, place=PH).counts["total"] == 3                    # clinic-3 is below public health
    assert uses.owner_list(state, collection=MEDICAL).counts["total"] == 4          # m1, m2, m3 are members
    assert uses.owner_list(state, collection="collection:andy/nothing").counts["total"] == 0


def test_a_shadow_receipt_is_flagged_in_the_owners_list_and_shown_to_nobody_else(tmp_path):
    uses = Uses.open(tmp_path)
    uses.append(plain(T("2026-11-02"), shadow=1), [("person:andy", M1)])
    state = andy_world().state()
    assert uses.owner_list(state).rows[0]["shadow"] is True
    assert uses.agent_view("agent:ph-coordinator") == [] and uses.subject_view("person:andy") == []
    assert uses.place_view(state, PH).rows == []


def test_an_agent_sees_its_allowed_items_and_recalls_as_counts(tmp_path):
    uses, state = e1_receipts(tmp_path)
    view = uses.agent_view("agent:ph-coordinator")
    assert {"object": M1, "at": T("2026-11-02"), "outcome": "allowed"} in view
    assert {"object": M2, "at": T("2026-11-02"), "outcome": "allowed"} in view      # a recall's items, one each


def test_a_steward_view_drops_home_record_ids_and_the_home_places_of_requesters(tmp_path):
    uses, state = e1_receipts(tmp_path)
    clinic = state.places[CLINIC_3].pseudonym_salt
    view = uses.place_view(state, CLINIC_3)
    assert view.counts["total"] == 3 and view.counts["local"] == 3
    andy = pseudonym(clinic, "person:andy")
    home_records = {r.id for r in state.records.values() if r.layer.startswith("place:home/")}
    assert home_records and not home_records & set(cited_ids(view.rows))
    assert all("object" not in r and "acting_for" not in r for r in view.rows)
    assert any(c["layer"] == andy for r in view.rows for c in r["cited"])


def test_a_place_view_covers_the_places_it_dominates_and_not_a_sibling(tmp_path):
    uses, state = e1_receipts(tmp_path)
    assert uses.place_view(state, "place:la-county").counts["total"] == 4       # the bulk use is at a home, on a home copy
    assert uses.place_view(state, PARKS).counts["total"] == 1                  # the empty recall: stewards see it
    assert uses.place_view(state, "place:la-county/summer-wellness").counts["total"] == 0


def test_a_place_view_covers_uses_of_copies_the_place_holds(tmp_path):
    w = andy_world()
    w.store("county-copy", owner="person:andy", place="place:la-county/public-health")
    state = w.state()
    uses = Uses.open(tmp_path)
    uses.append(plain(T("2026-11-02"), place=HOME, copy="store:county-copy"), [("person:andy", M1)])
    view = uses.place_view(state, "place:la-county")
    assert view.counts["total"] == 1
    assert HOME not in json.dumps(view.rows) and view.rows[0]["place"] == pseudonym(
        state.places["place:la-county"].pseudonym_salt, "person:andy")


def test_a_steward_sees_legacy_and_restriction_layers_by_those_words(tmp_path):
    state = andy_world().state()
    uses = Uses.open(tmp_path)
    cited = [{"layer": "publisher", "kind": "legacy", "action": "read", "verdict": "deny", "record": None,
              "version": None},
             {"layer": "agent:ph-coordinator", "kind": "restriction", "action": "read", "verdict": "deny",
              "record": None, "version": None}]
    for layer in ("publisher", "agent:ph-coordinator"):
        uses.append(plain(T("2026-11-02"), allowed=0, cited=json.dumps(cited),
                          refusal=json.dumps({"code": "LEGACY_DENY", "layer": layer, "action": "read"})),
                    [("person:andy", M1)])
    layers = {r["refusal"]["layer"] for r in uses.place_view(state, CLINIC_3).rows}
    assert layers == {"legacy", "restriction"}


def test_a_subject_sees_refusals_as_refused_and_never_a_reason(tmp_path):
    uses, state = e1_receipts(tmp_path)
    [row] = [r for r in uses.subject_view("person:jenn") if r["object"] == M3]
    assert row["outcome"] == "refused" and "refusal" not in row and "notes" not in row


def test_deliveries_are_the_agents_allowed_injections_in_the_last_24_hours(tmp_path):
    uses = Uses.open(tmp_path)
    now = T("2026-11-10")

    def inject(at, agent="agent:ph-coordinator", allowed=1, action="inject_context"):
        uses.append(plain(at, agent=agent, allowed=allowed, action=action), [("person:andy", M1)])
    inject(now - GUARD_SECONDS)             # exactly 24 hours old: out (half-open)
    inject(now - GUARD_SECONDS + 1)
    inject(now)
    inject(now + 1)                          # after now
    inject(now - 5, agent="agent:other")
    inject(now - 5, allowed=0)
    inject(now - 5, action="read")
    got = uses.deliveries("agent:ph-coordinator", now=now)
    assert [r.at for r in got] == [now, now - GUARD_SECONDS + 1] and all(isinstance(r, UseRow) for r in got)


def test_deliveries_are_at_most_the_guard_receipts_newest_first(tmp_path):
    uses = Uses.open(tmp_path)
    now = T("2026-11-10")
    for i in range(GUARD_RECEIPTS + 5):
        uses.append(plain(now - 1000 + i, action="inject_context"), [("person:andy", M1)])
    got = uses.deliveries("agent:ph-coordinator", now=now)
    assert len(got) == GUARD_RECEIPTS and got[0].at == now - 1000 + GUARD_RECEIPTS + 4
    assert USE_LIST_ROWS == 200
