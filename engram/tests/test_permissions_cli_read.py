"""Task 27: engram-permissions, the gate and the reading and checking commands (P 12.3, 14, 9.2 to 9.4, 8)."""
import getpass
import json

import pytest

import permission_cli
from permission_cli import main
from permission_ledger import Ledger, effective_gate, houses, ledger_path
from permission_uses import UseRow, Uses
from permissions import BulkUse, Use, decide, decide_bulk
from lighthouse_protocol import canonical_json
from tests.permissions_support import (ANDY, CLINIC_3, HOME, M1, M2, M3, PR, R1_ACTIONS, SW, T, _doc_of, cli_home,
                                       cli_home_with_house, do, e1_county_ledger, e1_through_use_9, fake_tty,
                                       house_before_029, parse_selector)

HOUSE_COPY = "store:HOUSE"          # the published house's instance_id in the E1 world (STORE_HOUSE)


# ---------------------------------------------------------------- fixtures

def _as_andy(tmp_path, monkeypatch):
    monkeypatch.setenv("ENGRAM_HOME", str(tmp_path))
    monkeypatch.setattr(getpass, "getuser", lambda: "andy")


@pytest.fixture
def cli_e1_county(tmp_path, monkeypatch, fake_tty):
    """P 13's county and Andy's side, in a ledger at tmp_path made by Andy. Returns the home."""
    _as_andy(tmp_path, monkeypatch)
    e1_county_ledger(tmp_path).close()
    return tmp_path


@pytest.fixture
def cli_e1_world(tmp_path, monkeypatch, fake_tty):
    """E1 through use 9 (P 13), in a ledger at tmp_path. Returns the home."""
    _as_andy(tmp_path, monkeypatch)
    led, _ = e1_through_use_9(tmp_path)
    led.close()
    return tmp_path


def add_receipt(home, *, place, obj=M1, at, allowed=True, agent="agent:ph-coordinator", action="read",
                cited=(), refusal=None, shadow=0, subjects=(), copy=HOUSE_COPY, content_digest=None):
    led = Ledger.open_read_only(home)
    ledger_id = led.meta()["ledger_id"]
    led.close()
    uses = Uses.open(home)
    try:
        return uses.append(UseRow(
            at=T(at), ledger_id=ledger_id, ledger_seq=1, agent=agent, place=place, acting_for=HOME, action=action,
            purpose="care-coordination", allowed=int(allowed), cited=canonical_json(list(cited)), object=obj,
            copy=copy, refusal=None if refusal is None else canonical_json(refusal), shadow=shadow,
            content_digest=content_digest), list(subjects))
    finally:
        uses.close()


def deny_cited(layer):
    return {"layer": layer, "kind": "consent", "action": "read", "verdict": "deny", "records": [], "version": 1}


def legacy_cited(verdict):
    return {"layer": "publisher", "kind": "legacy", "action": "read", "verdict": verdict, "records": [],
            "version": None}


@pytest.fixture
def cli_e1_world_andy_stewards_clinic_3(cli_e1_world):
    """cli_e1_world, Andy a steward of clinic-3, and receipts at clinic-3 (one refused, naming his home) and at
    parks-and-rec."""
    led = Ledger.open(cli_e1_world)
    do(led, "person:ph-steward", "add-steward", now="2026-11-20", place=CLINIC_3, person=ANDY)
    led.close()
    add_receipt(cli_e1_world, place=CLINIC_3, obj=M3, at="2026-11-21", allowed=False,
                cited=[deny_cited(HOME)], refusal={"code": "DENIED", "layer": HOME, "action": "read"},
                subjects=[("person:andy", M3), ("person:jenn", M3)])
    add_receipt(cli_e1_world, place=PR, obj=M1, at="2026-11-22", agent="agent:parks-planner")
    return cli_e1_world


class ShadowWorld:
    pass


@pytest.fixture
def cli_shadow_world(cli_home_with_house):
    """A ledger with an allow covering every memory of store S, a published house holding three placements (one
    linked to the allow, one with no record that the allow covers, one with no record in store T that nothing
    covers), and four shadow-era receipts, one of them a disagreement."""
    from storage import Storage
    home = cli_home_with_house
    led = Ledger.open(home)
    for iid in ("S", "T"):
        do(led, ANDY, "register-store", now="2026-01-01", instance_id=iid, name=iid, owner=ANDY, place=HOME,
           imprint_of=None)
    sel = parse_selector(_doc_of(["self"], kinds=["memory"], stores=["S"], memories="*", actions=R1_ACTIONS))
    allow = do(led, ANDY, "allow", now="2026-01-01", layer=HOME, selector=sel, valid_from=T("2026-01-01"),
               valid_until=None, reason="test").ref
    led.close()
    house = Storage(str(home / ".engram" / "instances" / "lighthouse" / "graph.db"))
    rows = [("share-linked", "mem-1", "S", "m1", allow), ("share-covered", "mem-2", "S", "m2", None),
            ("share-uncovered", "mem-3", "T", "m3", None)]
    for share_id, memory_id, store, source_id, record in rows:
        house.conn.execute(
            "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, audience, reason, "
            "content_digest, shared_at, source_instance_id, record_id) VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (share_id, memory_id, "engram", source_id, "episode", "commons", "t", "0" * 64, "2026-11-01", store,
             record))
    house.conn.commit()
    house.close()
    world = ShadowWorld()
    world.refused_receipt = add_receipt(home, place=HOME, at="2026-11-02", allowed=False, shadow=1,
                                        cited=[deny_cited(HOME), legacy_cited("allow")])
    add_receipt(home, place=HOME, at="2026-11-03", allowed=False, shadow=1, cited=[legacy_cited("deny")])
    add_receipt(home, place=HOME, at="2026-11-04", allowed=True, shadow=1, cited=[legacy_cited("allow")])
    add_receipt(home, place=HOME, at="2026-11-05", allowed=False, shadow=0, cited=[legacy_cited("allow")])
    world.uncovered_share = "share-uncovered"
    world.home = home
    return world


def write_objects_file(home, refs):
    path = home / "objects.txt"
    path.write_text("\n".join(refs) + "\n")
    return path


def mode_of(home):
    return effective_gate(home, houses(home)).mode


# ---------------------------------------------------------------- gate

def test_u16_only_the_terminal_yes_moves_the_gate(cli_home_with_house, fake_tty):
    fake_tty.answer("wrong1"); assert main(["gate", "shadow"]) == 3
    assert mode_of(cli_home_with_house) == "off"
    fake_tty.answer_the_printed_code(); assert main(["gate", "shadow"]) == 0
    assert mode_of(cli_home_with_house) == "shadow"


def test_u16_gate_refuses_a_raise_without_a_published_house(cli_home, fake_tty, capsys):
    fake_tty.answer_the_printed_code()
    assert main(["gate", "shadow"]) == 1 and "published house" in capsys.readouterr().err


def test_r27_gate_lists_the_houses_that_lack_029_before_the_yes(cli_home_with_house, fake_tty, capsys):
    house_before_029(cli_home_with_house, "old")
    fake_tty.answer_the_printed_code(); assert main(["gate", "shadow"]) == 0
    out = capsys.readouterr().out
    assert out.index("old") < out.index("code:") and "serves nothing" in out


def test_gate_prints_the_published_house_and_every_house_it_marks_before_the_yes(cli_home_with_house, fake_tty,
                                                                                capsys):
    fake_tty.answer("wrong1"); assert main(["gate", "enforce"]) == 3
    out = capsys.readouterr().out
    assert out.index("instances/lighthouse/graph.db") < out.index("code:") and "Move the gate to enforce" in out


def test_gate_off_after_a_raise_needs_the_yes_too(cli_home_with_house, fake_tty):
    fake_tty.answer_the_printed_code(); assert main(["gate", "shadow"]) == 0
    fake_tty.answer("wrong1"); assert main(["gate", "off"]) == 3
    assert mode_of(cli_home_with_house) == "shadow"
    fake_tty.answer_the_printed_code(); assert main(["gate", "off"]) == 0
    assert mode_of(cli_home_with_house) == "off"


# ---------------------------------------------------------------- check, place show, rebuild

def test_u15_check_prints_the_summer_wellness_sentence(cli_e1_county, capsys):
    assert main(["check", "place:la-county/summer-wellness"]) == 0
    assert "Summer Wellness may only recall." in capsys.readouterr().out


def test_check_with_no_place_checks_every_joint_place(cli_e1_county, capsys):
    assert main(["check"]) == 0
    assert "Summer Wellness may only recall." in capsys.readouterr().out


def test_check_says_so_when_a_place_has_nothing_to_report(cli_e1_county, capsys):
    assert main(["check", "place:la-county/public-health"]) == 0
    assert "No disagreement" in capsys.readouterr().out


def test_check_refuses_an_unregistered_place(cli_e1_county, capsys):
    assert main(["check", "place:nowhere"]) == 1 and "not a registered place" in capsys.readouterr().err


def test_check_does_not_write(cli_e1_county, capsys):
    before = ledger_path(cli_e1_county).read_bytes()
    assert main(["check"]) == 0 and ledger_path(cli_e1_county).read_bytes() == before


def test_place_show_prints_place_rules_and_refuses_a_home(cli_e1_county, capsys):
    ph = "place:la-county/public-health"
    assert main(["place", "show", ph, "--json"]) == 0
    art = json.loads(capsys.readouterr().out)
    assert art["kind"] == "PlaceRules" and art["payload"]["place"] == ph and art["payload"]["records"]
    assert main(["place", "show", ph]) == 0
    assert ph in capsys.readouterr().out
    assert main(["place", "show", HOME, "--json"]) == 1
    assert "home places are not published" in capsys.readouterr().err


def test_rebuild_writes_a_file_with_the_same_tables(cli_e1_world, tmp_path_factory, capsys):
    out = tmp_path_factory.mktemp("rebuilt")
    assert main(["rebuild", "--out", str(out)]) == 0
    assert str(ledger_path(out)) in capsys.readouterr().out
    a, b = Ledger.open_read_only(cli_e1_world), Ledger.open_read_only(out)
    try:
        assert a.tables() == b.tables() and b.verify() is None
    finally:
        a.close(), b.close()


def test_rebuild_refuses_to_overwrite_a_ledger(cli_e1_world, capsys):
    assert main(["rebuild", "--out", str(cli_e1_world)]) == 1 and "already" in capsys.readouterr().err


# ---------------------------------------------------------------- uses

def test_uses_place_shows_the_place_view_for_a_place_the_owner_stewards(cli_e1_world_andy_stewards_clinic_3, capsys):
    assert main(["uses", "--place", "place:la-county/public-health/clinic-3", "--json"]) == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert rows and "place:home" not in json.dumps(rows)                        # homes as pseudonyms (P 9.2, 9.3)
    assert main(["uses", "--place", "place:la-county/parks-and-rec", "--json"]) == 0   # not his: his list, filtered
    got = json.loads(capsys.readouterr().out)["rows"]
    assert got and all(r["place"] == "place:la-county/parks-and-rec" for r in got)


def test_uses_json_matches_owner_list(cli_e1_world_andy_stewards_clinic_3, capsys):
    home = cli_e1_world_andy_stewards_clinic_3
    assert main(["uses", "--json"]) == 0
    got = json.loads(capsys.readouterr().out)
    led, uses = Ledger.open_read_only(home), Uses.open_read_only(home)
    try:
        want = uses.owner_list(led.state())
    finally:
        uses.close(), led.close()
    assert got == json.loads(json.dumps({"counts": want.counts, "rows": want.rows})) and got["rows"]


def test_uses_filters_pass_through(cli_e1_world_andy_stewards_clinic_3, capsys):
    assert main(["uses", "--json", "--refused"]) == 0
    rows = json.loads(capsys.readouterr().out)["rows"]
    assert [r["outcome"] for r in rows] == ["refused"]
    assert main(["uses", "--json", "--since", "2026-11-22"]) == 0
    assert [r["place"] for r in json.loads(capsys.readouterr().out)["rows"]] == [PR]
    assert main(["uses", "--json", "--until", "2026-11-22"]) == 0
    assert [r["place"] for r in json.loads(capsys.readouterr().out)["rows"]] == [CLINIC_3]


def test_uses_prints_counts_and_rows_in_words(cli_e1_world_andy_stewards_clinic_3, capsys):
    assert main(["uses"]) == 0
    out = capsys.readouterr().out
    assert "2 uses" in out and "refused" in out and CLINIC_3 in out


def test_uses_with_no_receipts_file_says_so(cli_e1_world, capsys):
    assert main(["uses"]) == 0 and "No uses" in capsys.readouterr().out
    assert main(["uses", "--json"]) == 0 and json.loads(capsys.readouterr().out)["rows"] == []


# ---------------------------------------------------------------- report shadow

def test_report_shadow_lists_the_disagreements_and_the_shares_that_would_need_a_proposal(cli_shadow_world, capsys):
    assert main(["report", "shadow", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert [r["id"] for r in out["disagreements"]] == [cli_shadow_world.refused_receipt]
    assert [s["share_id"] for s in out["would_need_a_proposal"]] == [cli_shadow_world.uncovered_share]


def _audience_receipt(home, at, *, allowed, refusal, digest):
    return add_receipt(home, place=HOME, at=at, allowed=allowed, action="inject_context", shadow=1,
                       cited=[deny_cited(HOME)] if not allowed else [], refusal=refusal, content_digest=digest)


def test_report_shadow_counts_the_audience_refusal_as_legacy(cli_shadow_world, capsys):
    home = cli_shadow_world.home
    # both refuse: the ledger's refusal, and the publisher delivered nothing (no content digest)
    _audience_receipt(home, "2026-11-06", allowed=False, digest=None,
                      refusal={"code": "DENIED", "layer": HOME, "action": "inject_context"})
    # the ledger alone refuses: the legacy path delivered (digest kept under shadow)
    only_ledger = _audience_receipt(home, "2026-11-07", allowed=False, digest="d" * 64,
                                    refusal={"code": "DENIED", "layer": HOME, "action": "inject_context"})
    # the audience check alone refuses: the ledger allowed, the receipt notes LEGACY_DENY by the publisher
    only_audience = _audience_receipt(home, "2026-11-08", allowed=True, digest=None,
                                      refusal={"code": "LEGACY_DENY", "layer": "publisher",
                                               "action": "inject_context"})
    assert main(["report", "shadow", "--json"]) == 0
    got = [r["id"] for r in json.loads(capsys.readouterr().out)["disagreements"]]
    assert got == [cli_shadow_world.refused_receipt, only_ledger, only_audience]


def test_report_shadow_in_words(cli_shadow_world, capsys):
    assert main(["report", "shadow"]) == 0
    out = capsys.readouterr().out
    assert cli_shadow_world.refused_receipt in out and "share-uncovered" in out and "share-linked" not in out


def test_report_shadow_lists_a_placement_with_no_object(cli_shadow_world, capsys):
    from storage import Storage
    house = Storage(str(cli_shadow_world.home / ".engram" / "instances" / "lighthouse" / "graph.db"))
    house.conn.execute("UPDATE shared_memories SET source_instance_id = NULL WHERE share_id = 'share-linked'")
    house.conn.commit()
    house.close()
    assert main(["report", "shadow", "--json"]) == 0
    got = {s["share_id"]: s["why"] for s in json.loads(capsys.readouterr().out)["would_need_a_proposal"]}
    assert got["share-linked"] == "no object" and "share-uncovered" in got


def test_report_shadow_with_no_house_and_no_receipts_is_empty(cli_home, capsys):
    assert main(["report", "shadow", "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["disagreements"] == [] and out["would_need_a_proposal"] == []


def test_report_shadow_does_not_write_the_house(cli_shadow_world):
    path = cli_shadow_world.home / ".engram" / "instances" / "lighthouse" / "graph.db"
    before = path.read_bytes()
    assert main(["report", "shadow"]) == 0 and path.read_bytes() == before


# ---------------------------------------------------------------- explain

def test_explain_agrees_with_decide_for_a_single_and_a_bulk_use(cli_e1_world, capsys):   # P 14's `explain`
    s = Ledger.open(cli_e1_world).state()
    who = ["--agent", "agent:ph-coordinator", "--place", CLINIC_3, "--copy", HOUSE_COPY, "--purpose",
           "care-coordination", "--at", "2026-11-02"]
    assert main(["explain", *who, "--object", M3, "--action", "read", "--json"]) == 0      # E1 use 2: refused
    assert json.loads(capsys.readouterr().out) == decide(s, Use("agent:ph-coordinator", CLINIC_3, M3, HOUSE_COPY,
                                                                "read", "care-coordination", T("2026-11-02"))).to_json()
    objects = write_objects_file(cli_e1_world, [M1, M2])
    assert main(["explain", *who, "--objects", str(objects), "--counted", "--action", "recall", "--json"]) == 0
    bulk = BulkUse("agent:ph-coordinator", CLINIC_3, (M1, M2), HOUSE_COPY, "recall", "care-coordination",
                   T("2026-11-02"), named=False)
    assert json.loads(capsys.readouterr().out) == decide_bulk(s, bulk).to_json()


def test_explain_in_words_cites_the_refusal_and_its_layer(cli_e1_world, capsys):
    assert main(["explain", "--agent", "agent:ph-coordinator", "--place", CLINIC_3, "--copy", HOUSE_COPY,
                 "--purpose", "care-coordination", "--at", "2026-11-02", "--object", M3, "--action", "read"]) == 0
    out = capsys.readouterr().out
    decision = decide(Ledger.open(cli_e1_world).state(), Use("agent:ph-coordinator", CLINIC_3, M3, HOUSE_COPY, "read",
                                                              "care-coordination", T("2026-11-02")))
    assert "refused" in out and decision.refusal.code in out and decision.refusal.layer in out


def test_explain_takes_names_for_a_road(cli_e1_world, tmp_path, capsys):
    names = tmp_path / "names.json"
    names.write_text(json.dumps([M1, M2]))
    road = "road:S/r1"
    args = ["explain", "--agent", "agent:ph-coordinator", "--place", CLINIC_3, "--copy", HOUSE_COPY,
            "--purpose", "care-coordination", "--at", "2026-11-02", "--object", road, "--action", "recall",
            "--names", str(names), "--json"]
    assert main(args) == 0
    s = Ledger.open(cli_e1_world).state()
    want = decide(s, Use("agent:ph-coordinator", CLINIC_3, road, HOUSE_COPY, "recall", "care-coordination",
                         T("2026-11-02"), names=(M1, M2)))
    assert json.loads(capsys.readouterr().out) == want.to_json()


def test_explain_needs_exactly_one_of_object_and_objects(cli_e1_world, capsys):
    base = ["explain", "--agent", "agent:ph-coordinator", "--place", CLINIC_3, "--copy", HOUSE_COPY,
            "--purpose", "care-coordination", "--action", "read"]
    with pytest.raises(SystemExit) as e:
        main(base)
    assert e.value.code == 2
    with pytest.raises(SystemExit) as e:
        main([*base, "--object", M1, "--objects", "x"])
    assert e.value.code == 2


def test_explain_refuses_an_unreadable_objects_file(cli_e1_world, capsys):
    assert main(["explain", "--agent", "agent:ph-coordinator", "--place", CLINIC_3, "--copy", HOUSE_COPY,
                 "--purpose", "care-coordination", "--action", "recall", "--objects",
                 str(cli_e1_world / "missing.txt")]) == 1
    assert "cannot be read" in capsys.readouterr().err


def test_explain_refuses_a_named_bulk_use_over_the_bound(cli_e1_world, capsys):
    path = write_objects_file(cli_e1_world, [f"mem:S/episode/m{i}" for i in range(600)])      # at most 512 named
    assert main(["explain", "--agent", "agent:ph-coordinator", "--place", CLINIC_3, "--copy", HOUSE_COPY,
                 "--purpose", "care-coordination", "--action", "recall", "--at", "2026-11-02", "--objects",
                 str(path), "--json"]) == 0
    assert json.loads(capsys.readouterr().out)["refusal"]["code"] == "BOUND"


def test_the_objects_file_is_read_no_further_than_the_bound(cli_e1_world, monkeypatch):
    monkeypatch.setattr(permission_cli, "MAX_OBJECT_LINES", 3)
    path = write_objects_file(cli_e1_world, [f"mem:S/episode/m{i}" for i in range(10)])
    assert permission_cli._object_lines(str(path)) == tuple(f"mem:S/episode/m{i}" for i in range(3))


# ---------------------------------------------------------------- sweep

def test_sweep_under_off_does_nothing_and_says_so(cli_home_with_house, capsys):
    assert main(["sweep"]) == 0 and "off" in capsys.readouterr().out


def test_sweep_removes_the_placement_of_an_allow_that_no_longer_counts(cli_shadow_world, fake_tty, capsys):
    home = cli_shadow_world.home
    fake_tty.answer_the_printed_code(); assert main(["gate", "enforce"]) == 0
    led = Ledger.open(home)
    record = next(iter(led.state().records))
    do(led, ANDY, "revoke", now="2026-12-01", record=record)
    led.close()
    capsys.readouterr()
    assert main(["sweep"]) == 0
    assert "removed" in capsys.readouterr().out
