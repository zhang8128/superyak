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
    with pytest.raises(RuleError, match="matched no row"):
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
    with pytest.raises(RuleError, match="matched no row"):
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
    assert rig.read(M1_ITEM)["content"] is not None


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
