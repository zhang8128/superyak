"""The final whole-branch review's fixes (final-review.md, 2026-10-27): each test names its finding."""
import pytest

from permission_ledger import Ledger
from permissions import RuleError
from tests.permissions_support import ANDY, T, do, e1_ledger_through_andys_side, selector_of


# ---------------------------------------------------------------- M1: a row is revoked once (P 5.1)

def _another_writer_goes_first(led, first):
    """`led`'s next write runs `first()` on another connection just before it: both acts passed their checks
    against a State made before either wrote, as a CLI command and an agent's `withdraw` can."""
    original = led._append

    def append(*args, **kw):
        led._append = original
        first()
        return original(*args, **kw)
    led._append = append


SECOND = {"revoke": {}, "shorten": {"valid_until": T("2027-01-01")},
          "narrow": {"selector": selector_of(purposes=frozenset({"care-coordination"}),
                                             actions=frozenset({"recall"}))}}


@pytest.mark.parametrize("kind", ["revoke", "shorten", "narrow"])
def test_m1_a_record_one_writer_revoked_is_not_revoked_again_by_another(tmp_path, kind):
    led = e1_ledger_through_andys_side(tmp_path)
    rid, before = led.ids.R1, len(led.state().records)
    other = Ledger.open(tmp_path)
    _another_writer_goes_first(led, lambda: do(other, ANDY, "revoke", now="2026-11-05", record=rid, reason="first"))
    with pytest.raises(RuleError, match=rf"^.*: {rid} is already revoked \(by another write\)$"):
        do(led, ANDY, kind, now="2026-11-06", record=rid, reason="second", **SECOND[kind])
    s = Ledger.open(tmp_path).state()
    assert (s.records[rid].revoke_reason, s.records[rid].revoked) == ("first", T("2026-11-05"))
    assert len(s.records) == before                       # no second, live replacement
    assert Ledger.open(tmp_path).verify() is None


@pytest.mark.parametrize("kind", ["revoke-grant", "give-up-grant"])
def test_m1_a_grant_one_writer_ended_is_not_ended_again_by_another(tmp_path, kind):
    led = e1_ledger_through_andys_side(tmp_path)
    gid = led.ids.G1
    other = Ledger.open(tmp_path)
    _another_writer_goes_first(led, lambda: do(other, ANDY, "revoke-grant", now="2026-11-05", grant=gid,
                                               reason="first"))
    actor, channel = (ANDY, "terminal") if kind == "revoke-grant" else ("agent:rio-grande", "tool")
    with pytest.raises(RuleError, match=rf"^.*: {gid} has already ended \(by another write\)$"):
        do(led, actor, kind, now="2026-11-06", channel=channel, grant=gid, reason="second")
    g = Ledger.open(tmp_path).state().grants[gid]
    assert (g.revoke_reason, g.revoked, g.revoked_by) == ("first", T("2026-11-05"), ANDY)


# ---------------------------------------------------------------- I1: proposals and child grants are bounded (15, P37)

import time
import tracemalloc

from permissions import Act, selector_json
from tests.permissions_support import HOME, R1_ENVELOPE, RIO, memories

WHEN = "2026-12-05"          # G1 expired on 11-30, so an agent's allow on the tool channel is a proposal
PER_AGENT, IN_LEDGER, CHILDREN = 64, 1024, 64


def _big_allow(i):
    """An allow whose selector lists 512 memories: the largest body an agent's proposal holds."""
    import dataclasses
    sel = dataclasses.replace(R1_ENVELOPE, collections="*", memories=frozenset(memories(512, start=i * 512)))
    return Act("allow", {"layer": HOME, "selector": selector_json(sel), "valid_from": T(WHEN),
                         "valid_until": T("2027-01-31"), "reason": f"ask {i}"})


def _propose(led, agent, i, when=WHEN):
    out = led.perform(_big_allow(i), actor=agent, channel="tool", now=T(when))
    assert out.status == "proposal"
    return out.ref


def test_i1_an_agent_holds_at_most_64_open_proposals(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    filed = [_propose(led, RIO, i) for i in range(PER_AGENT)]
    with pytest.raises(RuleError, match=f"at most {PER_AGENT} open proposals"):
        _propose(led, RIO, PER_AGENT)
    assert len(led.proposals(now=T(WHEN))) == PER_AGENT
    do(led, ANDY, "decline", now=WHEN, proposal=filed[0])        # a decided proposal is no longer open
    _propose(led, RIO, PER_AGENT)
    later = "2026-12-13"                                         # every one of them has expired: none is open
    assert led.proposals(now=T(later)) == []
    _propose(led, RIO, PER_AGENT + 1, when=later)


def test_i1_a_ledger_holds_at_most_1024_open_proposals_and_a_state_holds_none_of_them(tmp_path):
    """The probe that holds the bound (U24's way, without ENGRAM_PI_BUDGET): 1,024 open proposals of 512 refs
    each, the most a ledger holds, and the State a frame or a `perform` builds is no larger for them."""
    led = e1_ledger_through_andys_side(tmp_path)
    agents = [f"agent:asker-{k}" for k in range(IN_LEDGER // PER_AGENT + 1)]
    for a in agents:
        do(led, ANDY, "register-agent", agent=a, acts_for=HOME)
        do(led, ANDY, "put-agent", agent=a, place=HOME)

    def traced_state():
        tracemalloc.start()
        try:
            base = tracemalloc.get_traced_memory()[0]
            s = led.state()
            held = tracemalloc.get_traced_memory()[0] - base
        finally:
            tracemalloc.stop()
        return s, held

    _s, before = traced_state()
    del _s
    start = time.perf_counter()
    for k, a in enumerate(agents[:-1]):
        for i in range(PER_AGENT):
            _propose(led, a, k * PER_AGENT + i)
    took = time.perf_counter() - start
    with pytest.raises(RuleError, match=f"at most {IN_LEDGER:,} open proposals"):
        _propose(led, agents[-1], IN_LEDGER)
    s, after = traced_state()
    assert after - before < 512 * 1024, f"a State grew by {after - before:,} B for {IN_LEDGER} proposals"
    some = led.proposals(now=T(WHEN))
    assert len(some) == IN_LEDGER and len(s.proposals) == IN_LEDGER
    p = s.proposals[some[-1]["id"]]                              # read on demand, whole
    assert p.status == "pending" and f'"reason":"{some[-1]["reason"]}"' in p.body
    print(f"I1 probe: {IN_LEDGER} proposals filed in {took:.1f} s; a State grew by {after - before:,} B")


def test_i1_a_parent_grant_has_at_most_64_live_children(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    do(led, ANDY, "register-agent", now="2026-11-02", agent="agent:rio-2", acts_for=HOME)
    root = do(led, ANDY, "grant", now="2026-11-02", layer=HOME, grantee=RIO, ops=["share", "narrow"],
              envelope=R1_ENVELOPE, max_days=90, depth=1, hours=240).ref

    def child(now="2026-11-03", hours=24):
        return do(led, RIO, "grant", now=now, channel="tool", parent=root, grantee="agent:rio-2", ops=["share"],
                  envelope=R1_ENVELOPE, max_days=30, depth=0, hours=hours).ref

    kids = [child() for _ in range(CHILDREN)]
    with pytest.raises(RuleError, match=f"at most {CHILDREN} live child grants"):
        child()
    do(led, RIO, "revoke-grant", now="2026-11-03", channel="tool", grant=kids[0], reason="done")
    child()                                                      # a revoked child is not live
    with pytest.raises(RuleError, match=f"at most {CHILDREN} live child grants"):
        child()
    child(now="2026-11-04T01:00:00Z")                              # the first 64 expired after 24 hours


# ---------------------------------------------------------------- I2 (SH-13): a chunked collect or uncollect is honest

import permission_cli
from tests.permissions_support import cli_home, fake_tty, log_rows       # noqa: F401 (fixtures)

C = "collection:andy/c"
REFS = [f"mem:elsewhere/episode/m{i}" for i in range(9)]


def _members_of(home):
    led = Ledger.open(home)
    try:
        return {r.object for r in led.state().collection_members.get(C, ()) if r.removed_seq is None}
    finally:
        led.close()


@pytest.fixture
def small_acts(cli_home, fake_tty, monkeypatch):
    """The review's repro: acts of at most 3 objects, and m3 to m5 already in the collection."""
    monkeypatch.setattr(permission_cli, "MAX_ACT_OBJECTS", 3)
    import permissions
    monkeypatch.setattr(permissions, "MAX_ACT_OBJECTS", 3)
    fake_tty.answer_the_printed_code()
    assert permission_cli.main(["collection", "add", C, *REFS[3:6]]) == 0
    return cli_home


def test_i2_collection_add_leaves_out_members_and_writes_every_new_one(small_acts, fake_tty, capsys):
    capsys.readouterr()
    fake_tty.answer_the_printed_code()
    assert permission_cli.main(["collection", "add", C, *REFS]) == 0
    out = capsys.readouterr()
    assert _members_of(small_acts) == set(REFS)
    assert "3 of the refs are already in" in out.out and out.out.index("already in") < out.out.index("code:")
    assert "refused" not in out.err


def test_i2_collection_add_with_nothing_new_is_refused_before_the_yes(small_acts, fake_tty, capsys):
    before = len(log_rows(small_acts))
    capsys.readouterr()
    assert permission_cli.main(["collection", "add", C, *REFS[3:6]]) == 1
    out = capsys.readouterr()
    assert "already in" in out.err and "code:" not in out.out and len(log_rows(small_acts)) == before


def test_i2_collection_remove_names_each_ref_not_in_it_before_the_yes(small_acts, fake_tty, capsys):
    before = len(log_rows(small_acts))
    capsys.readouterr()
    assert permission_cli.main(["collection", "remove", C, *REFS]) == 1
    out = capsys.readouterr()
    assert "code:" not in out.out and len(log_rows(small_acts)) == before
    for i in (0, 1, 2, 6, 7, 8):
        assert REFS[i] in out.err
    for i in (3, 4, 5):
        assert REFS[i] not in out.err
    fake_tty.answer_the_printed_code()
    assert permission_cli.main(["collection", "remove", C, *REFS[3:6]]) == 0
    assert _members_of(small_acts) == set()


def test_i2_an_act_that_fails_after_others_were_written_says_which_were(small_acts, fake_tty, capsys, monkeypatch):
    """A concurrent writer can still make a later act fail: the person is told which acts were written."""
    real, calls = Ledger.perform, []

    def perform(self, act, **kw):
        calls.append(act.kind)
        if len(calls) == 2:
            raise RuleError("7.1 who may set what", "another writer got there first")
        return real(self, act, **kw)
    monkeypatch.setattr(Ledger, "perform", perform)
    seq = len(log_rows(small_acts))
    capsys.readouterr()
    fake_tty.answer_the_printed_code()
    assert permission_cli.main(["collection", "add", C, *REFS]) == 1
    err = capsys.readouterr().err
    assert f"act 1 of 2 done (log {seq + 1}); the rest were not written" in err
    assert err.index("the rest were not written") < err.index("refused: ")
    assert _members_of(small_acts) == set(REFS[:3]) | set(REFS[3:6])


# ---------------------------------------------------------------- M3: a read refuses an item with a sourceless row (12.2)

import hashlib
import sqlite3

from tests.permissions_support import HOUSE_NAME, M1_ITEM, M1_TEXT, enforce_daemon, house_dir, receipt_rows, shadow_daemon


def _add_sourceless_row(root, memory_id):
    """A second placement of the same copy, written by older code: it has no source_instance_id, so no object."""
    con = sqlite3.connect(house_dir(root, HOUSE_NAME) / "graph.db")
    con.execute("INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, audience, "
                "reason, content_digest, shared_at, source_instance_id, record_id) "
                "VALUES ('old-share', ?, 'engram', 'm1-old', 'episode', 'commons', 'old', ?, '2026-10-01', NULL, NULL)",
                (memory_id, hashlib.sha256(M1_TEXT.encode()).hexdigest()))
    con.commit()
    con.close()


def test_m3_under_enforce_a_read_refuses_a_copy_one_of_whose_placements_has_no_object(tmp_path):
    rig = enforce_daemon(tmp_path)
    assert rig.read(M1_ITEM)["content"] is not None                  # its one sourced placement is allowed
    _add_sourceless_row(tmp_path, M1_ITEM)
    assert M1_ITEM not in {c["memoryId"] for c in rig.recall()["candidates"]}     # recall already filters it
    before = len(receipt_rows(tmp_path, action="inject_context"))
    item = rig.read(M1_ITEM)
    assert item["content"] is None and "permission" not in item
    assert len(receipt_rows(tmp_path, action="inject_context")) == before         # no object to name: no receipt


def test_m3_under_shadow_the_legacy_path_still_delivers_it(tmp_path):
    rig = shadow_daemon(tmp_path)
    _add_sourceless_row(tmp_path, M1_ITEM)
    before = receipt_rows(tmp_path, action="inject_context")
    assert rig.read(M1_ITEM)["content"] is not None
    assert receipt_rows(tmp_path, action="inject_context") == before    # no object to name: no receipt (gate G12)


# ---------------------------------------------------------------- M8: a shadow receipt keeps the ledger's own refusal

import json

from permission_cli import main as cli_main
from tests.permissions_support import cli_home_with_house, write_publisher_policy       # noqa: F401 (fixture)
from tests.test_permissions_cli_read import add_receipt, cli_shadow_world, deny_cited   # noqa: F401 (fixture)

AUDIENCE = {"layer": "publisher", "kind": "audience", "action": "inject_context", "verdict": "deny",
            "record": None, "version": None}
OLD_AUDIENCE = {"code": "LEGACY_DENY", "layer": "publisher", "action": "inject_context"}


def test_m8_a_shadow_receipt_both_paths_refuse_keeps_the_ledgers_code_and_cites_the_audience(tmp_path):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows=False)
    assert d.read(M1_ITEM)["content"]
    ledger_only = json.loads(receipt_rows(tmp_path, action="inject_context")[-1]["refusal"])
    write_publisher_policy(tmp_path, receiver_audiences=["group:other"])
    assert d.read(M1_ITEM)["content"] is None
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert row["shadow"] == 1 and row["allowed"] == 0 and row["content_digest"] is None
    assert json.loads(row["refusal"]) == ledger_only and ledger_only["code"] != "LEGACY_DENY"
    assert AUDIENCE in json.loads(row["cited"])


def test_m8_a_shadow_receipt_only_the_audience_refuses_is_allowed_with_no_refusal_and_cites_it(tmp_path):
    d = shadow_daemon(tmp_path, legacy_allows=True, ledger_allows=True)
    write_publisher_policy(tmp_path, receiver_audiences=["group:other"])
    assert d.read(M1_ITEM)["content"] is None
    row = receipt_rows(tmp_path, action="inject_context")[-1]
    assert row["shadow"] == 1 and row["allowed"] == 1 and row["refusal"] is None
    assert AUDIENCE in json.loads(row["cited"])


def _shadow_receipt(home, at, *, allowed, refusal, cited, digest=None):
    return add_receipt(home, place=HOME, at=at, allowed=allowed, action="inject_context", shadow=1, cited=cited,
                       refusal=refusal, content_digest=digest)


def test_m8_report_shadow_reads_the_audience_refusal_from_its_cited_entry_and_still_reads_old_receipts(
        cli_shadow_world, capsys):
    home, ledger_deny = cli_shadow_world.home, {"code": "DENIED", "layer": HOME, "action": "inject_context"}
    both = _shadow_receipt(home, "2026-11-06", allowed=False, refusal=ledger_deny,
                           cited=[deny_cited(HOME), AUDIENCE])
    only_audience = _shadow_receipt(home, "2026-11-07", allowed=True, refusal=None, cited=[AUDIENCE])
    old_both = _shadow_receipt(home, "2026-11-08", allowed=False, refusal=OLD_AUDIENCE, cited=[deny_cited(HOME)])
    old_only_audience = _shadow_receipt(home, "2026-11-09", allowed=True, refusal=OLD_AUDIENCE, cited=[])
    assert cli_main(["report", "shadow", "--json"]) == 0
    rows = {r["id"]: r for r in json.loads(capsys.readouterr().out)["disagreements"]}
    assert both not in rows and old_both not in rows
    assert rows[only_audience]["refusal"] == rows[old_only_audience]["refusal"] == OLD_AUDIENCE
    assert cli_main(["report", "shadow"]) == 0
    out = capsys.readouterr().out
    assert f"{only_audience}" in out and "LEGACY_DENY at publisher" in out.split(only_audience)[1].splitlines()[0]


# ---------------------------------------------------------------- M9: `sweep` says it failed when it failed

def test_m9_a_sweep_that_fails_says_so_and_does_not_say_nothing_to_change(cli_home, monkeypatch, capsys):
    from permission_ledger import Gate
    from tests.permissions_support import make_house

    def boom(*a, **k):
        raise RuntimeError("sweep broke")
    make_house(cli_home, "lighthouse")
    monkeypatch.setattr(permission_cli, "effective_gate", lambda *a, **k: Gate("shadow"))
    monkeypatch.setattr(permission_cli, "_sweep_house", boom)
    capsys.readouterr()
    assert cli_main(["sweep"]) == 1
    out = capsys.readouterr()
    assert "nothing to change" not in out.out + out.err
    assert "sweep broke" in out.err and "The placement sweep failed" in out.err


# ---------------------------------------------------------------- M5: a place's name cannot rewrite the terminal

from tests.permissions_support import county_ledger


@pytest.mark.parametrize("name", ["Public\x1b[2JHealth", "Public\nHealth", "Public‮Health", "Public\x07"])
def test_m5_a_place_name_with_a_character_that_does_not_print_is_refused(tmp_path, name):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    with pytest.raises(RuleError, match="prints"):
        do(led, ANDY, "register-place", place="place:county", name=name)
    assert "place:county" not in led.state().places


def test_m5_confirm_cleans_what_it_prints_and_keeps_its_lines(fake_tty, capsys):
    from permission_cli import confirm
    fake_tty.answer_the_printed_code()
    assert confirm("Allow \x1b[2Jplace:x to read.\nSecond line", "change \x1b]0;title\x07 here") is True
    out = capsys.readouterr().out
    assert "\x1b" not in out and "\x07" not in out
    assert "Allow ?[2Jplace:x to read.\nSecond line" in out and "change ?]0;title? here" in out


# ---------------------------------------------------------------- M6: cosubjects follows copies (P 7.4, 19)

from tests.permissions_support import COPY_OF_M3, M3, add_subject, remove_subject


def test_m6_cosubjects_of_a_copy_holds_its_sources_later_subjects_and_not_its_default_subject(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    led.record_copy(COPY_OF_M3, M3, now=T("2026-11-03"))
    add_subject(led, M3, "person:amy", actor=ANDY, now="2026-11-04")       # after the copy was made
    assert led.cosubjects(COPY_OF_M3) == frozenset({"person:jenn", "person:amy"})
    assert ANDY not in led.cosubjects(COPY_OF_M3) and led.cosubjects(M3) == frozenset({"person:jenn", "person:amy"})
    remove_subject(led, M3, "person:amy", actor=ANDY, now="2026-11-05")
    assert led.cosubjects(COPY_OF_M3) == frozenset({"person:jenn"})
    assert led.cosubjects(COPY_OF_M3, at=T("2026-11-04") + 60) == frozenset({"person:jenn", "person:amy"})


def test_m6_cosubjects_of_a_copy_another_person_keeps_names_the_sources_owner(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    do(led, "person:jenn", "register-store", instance_id="J", name="jenn's", owner="person:jenn",
       place="place:home/jenn")
    led.record_copy("mem:J/episode/c1", "mem:S/episode/m1", now=T("2026-11-03"))
    assert led.cosubjects("mem:J/episode/c1") == frozenset({ANDY})


# ---------------------------------------------------------------- M4: a kept copy carries every matching source's subjects

import server
from permissions import subjects_of
from tests.permissions_support import (CLINIC_3, COUNTY, KEEP_LATER, KEEP_NOW, M2, PH, _phc_allow, deliver_m1_through,
                                       keep_world, keep_world_with_imprint_allowed, write_delivery_receipt)  # noqa: F401
from tests.test_recall_margins import engram_server_env  # noqa: F401


def test_m4_record_copy_carries_the_subjects_of_each_source_it_is_told_of(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    copy = "mem:K/episode/c9"
    led.record_copy(copy, "mem:S/episode/m1", also=[M3], now=T("2026-11-03"))
    s = led.state()
    assert s.copies[copy] == "mem:S/episode/m1"                       # `copies` keeps one source
    rows = {r.subject: r.added_by for r in s.subjects[copy]}
    assert rows == {"person:jenn": f"copy:{M3}"}                      # andy is K's owner, its default subject


def test_m4_the_remember_guard_carries_the_union_of_every_matching_sources_subjects(
        keep_world_with_imprint_allowed):
    world = keep_world_with_imprint_allowed
    led = Ledger.open(world.root)
    try:
        add_subject(led, M2, "person:amy", actor=ANDY, now="2026-11-02")
        for steward, layer, audience in ((ANDY, HOME, PH), ("person:county-steward", COUNTY, COUNTY),
                                         ("person:ph-steward", PH, PH), ("person:ph-steward", CLINIC_3, CLINIC_3),
                                         ("person:amy", "place:home/amy", PH)):
            actions = ["imprint"] if steward != "person:amy" else ["recall", "read", "inject_context", "imprint"]
            _phc_allow(led, steward, layer, audience=[audience], dims={"memories": [M2]}, actions=actions)
    finally:
        led.close()
    from tests.permissions_support import M1_TEXT as TEXT
    write_delivery_receipt(world.root, content=TEXT, agent="agent:ph-coordinator", obj=M2)  # the same text, m2
    deliver_m1_through(world, "neighbors")            # the newest delivery, so the guard's first match is m1
    out = server.remember(content=TEXT)
    assert "episode_id" in out and "would_refuse" not in out, out
    kept = f"mem:{world.ids.PHC_STORE}/episode/{out['episode_id']}"
    led = Ledger.open_read_only(world.root)
    try:
        s = led.state()
    finally:
        led.close()
    assert "person:amy" in subjects_of(s, kept, KEEP_NOW) and ANDY in subjects_of(s, kept, KEEP_NOW)


# ---------------------------------------------------------------- M2: a backward clock step and the cache's horizon

from tests.permissions_support import M1_ID, M1 as M1_REF, cached_daemon, parse_selector, _doc_of

STEPPED = T("2026-11-03")          # the ledger writer's clock; the daemon's reads 2026-11-02, a day behind


def _write(root, *acts):
    led = Ledger.open(root)
    try:
        for actor, kind, now, args in acts:
            do(led, actor, kind, now=now, **args)
    finally:
        led.close()


def _deny_collection(root, cid):
    sel = parse_selector(_doc_of(["self"], kinds=["memory"], collections=[cid]))
    _write(root, (ANDY, "make-collection", "2026-11-01", {"collection": cid}),
           (ANDY, "deny", "2026-11-01", {"layer": HOME, "selector": sel, "valid_from": T("2026-11-01"),
                                         "valid_until": None, "reason": "stop"}))


def test_m2_a_deny_membership_written_past_the_daemons_clock_ends_the_cached_allow_at_its_time(tmp_path):
    d, root, _house = cached_daemon(tmp_path)
    _deny_collection(root, "collection:andy/stop")
    _write(root, (ANDY, "collect", "2026-11-03", {"collection": "collection:andy/stop", "refs": [M1_REF]}))
    d.clock_to(T("2026-11-02"))
    assert M1_ID in d.recall_ids()                # at 11-02 the membership is not yet in force (P 5.3)
    assert d.cache_horizon() == STEPPED            # so the entry ends when it comes into force
    d.clock_to(STEPPED + 60)
    assert M1_ID not in d.recall_ids()             # no ledger write since: the horizon re-decides it


def test_m2_a_co_subject_written_past_the_daemons_clock_ends_the_cached_allow_at_its_time(tmp_path):
    d, root, _house = cached_daemon(tmp_path)
    _write(root, (ANDY, "register-person", "2026-11-01", {"person": "person:jenn"}),
           (ANDY, "add-subject", "2026-11-03", {"object": M1_REF, "subject": "person:jenn"}))
    d.clock_to(T("2026-11-02"))
    assert M1_ID in d.recall_ids() and d.cache_horizon() == STEPPED
    d.clock_to(STEPPED + 60)
    assert M1_ID not in d.recall_ids()             # Jenn's home allows nothing


def test_m2_a_requester_moved_out_past_the_daemons_clock_ends_the_cached_allow_at_its_time(tmp_path):
    d, root, _house = cached_daemon(tmp_path)
    _write(root, (ANDY, "remove-agent", "2026-11-03", {"agent": "agent:engram", "place": HOME}))
    d.clock_to(T("2026-11-02"))
    assert M1_ID in d.recall_ids() and d.cache_horizon() == STEPPED
    d.clock_to(STEPPED + 60)
    assert M1_ID not in d.recall_ids()


def test_m2_a_back_dated_deny_written_past_the_daemons_clock_ends_the_cached_allow_at_its_anchor(tmp_path):
    """The re-review's probe: m1 has been in the collection since 11-01, and a deny on it with valid_from 11-01
    is written by the ledger's clock at 11-03 (a `--from` in the past, or a deny proposal signed after it was
    filed). Its anchor is 11-03, so at the daemon's 11-02 its membership does not count yet (P 5.3), and the
    cached allow must end at the anchor, not at the allow's end or the next ledger write."""
    d, root, _house = cached_daemon(tmp_path)
    cid = "collection:andy/stop"
    sel = parse_selector(_doc_of(["self"], kinds=["memory"], collections=[cid]))
    _write(root, (ANDY, "make-collection", "2026-11-01", {"collection": cid}),
           (ANDY, "collect", "2026-11-01", {"collection": cid, "refs": [M1_REF]}),
           (ANDY, "deny", "2026-11-03", {"layer": HOME, "selector": sel, "valid_from": T("2026-11-01"),
                                         "valid_until": None, "reason": "stop"}))
    d.clock_to(T("2026-11-02"))
    assert M1_ID in d.recall_ids()                # at 11-02 the deny's anchor is not reached
    assert d.cache_horizon() == STEPPED            # so the entry ends at the anchor
    d.clock_to(STEPPED + 60)
    assert M1_ID not in d.recall_ids()             # no ledger write since: the horizon re-decides it


# ---------------------------------------------------------------- the fix wave's concern 3: a proposal is decided once,
# and a person or place is retired once (M1's fix for the other rows a second writer can find already changed)

def _proposal_records(root, pid):
    return [r for r in Ledger.open(root).state().records.values() if r.proposal_id == pid]


@pytest.mark.parametrize("first, second", [("sign", "sign"), ("decline", "sign"), ("sign", "decline"),
                                           ("decline", "decline")])
def test_concern3_a_proposal_one_writer_decided_is_not_decided_again_by_another(tmp_path, first, second):
    led = e1_ledger_through_andys_side(tmp_path)
    pid = _propose(led, RIO, 0)
    other = Ledger.open(tmp_path)
    _another_writer_goes_first(led, lambda: do(other, ANDY, first, now=WHEN, proposal=pid))
    decided = "signed" if first == "sign" else "declined"
    with pytest.raises(RuleError, match=rf"^.*: {pid} is already {decided} \(by another write\)$"):
        do(led, ANDY, second, now=WHEN, proposal=pid)
    assert Ledger.open(tmp_path).state().proposals[pid].status == decided
    assert len(_proposal_records(tmp_path, pid)) == (1 if first == "sign" else 0)      # its act ran at most once
    assert Ledger.open(tmp_path).verify() is None


def test_concern3_a_person_one_writer_retired_is_not_retired_again_by_another(tmp_path):
    led = county_ledger(tmp_path)
    other = Ledger.open(tmp_path)
    _another_writer_goes_first(led, lambda: do(other, ANDY, "retire-person", now="2026-11-05", person="person:amy"))
    with pytest.raises(RuleError, match=r"^.*: person:amy is already retired \(by another write\)$"):
        do(led, ANDY, "retire-person", now="2026-11-06", person="person:amy")
    s = Ledger.open(tmp_path).state()
    first = s.persons["person:amy"].retired_seq
    assert s.seq_at[first] == T("2026-11-05") and s.places[s.persons["person:amy"].home].retired_seq == first


def test_concern3_a_place_one_writer_retired_is_not_retired_again_by_another(tmp_path):
    from tests.permissions_support import CLINIC_3
    led = county_ledger(tmp_path)
    other = Ledger.open(tmp_path)
    _another_writer_goes_first(led, lambda: do(other, "person:ph-steward", "retire-place", now="2026-11-05",
                                               place=CLINIC_3))
    with pytest.raises(RuleError, match=rf"^.*: {CLINIC_3} is already retired \(by another write\)$"):
        do(led, "person:ph-steward", "retire-place", now="2026-11-06", place=CLINIC_3)
    s = Ledger.open(tmp_path).state()
    assert s.seq_at[s.places[CLINIC_3].retired_seq] == T("2026-11-05")
