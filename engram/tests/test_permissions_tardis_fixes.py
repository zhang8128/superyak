"""Tardis's advisory review of permissions-core (reviews/2026-10-27-tardis-permissions-core-advisory.md): each
test names its finding."""
import dataclasses
import json
import os
import pwd
import signal
import subprocess
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import federation
import permission_cli
import server
import sharing
from permission_cli import main as cli_main
from permission_ledger import Ledger, _may_retire_person, effective_gate, ledger_path
from permission_uses import Uses, UseRow
from permissions import (RETENTION_DAYS, STAR, Act, Placement, Refusal, RuleError, authorize, check_narrower, decide,
                         eligible_set, parse_selector, placement_still_counts, selector_json, share_cover, subjects_of)
from storage import Storage
from tests.permissions_support import (  # noqa: F401
    ANDY, HOME, M1, M1_TEXT, M4, MEDICAL, T, World, andy_world, cli_home, deliver_m1_through, do, e1_county_ledger,
    e1_ledger_through_andys_side, fails_the_test, fake_tty, genome_world, home_use, keep_world, keep_world_with_imprint_allowed, make_ledger_unreadable,
    use_json)
from tests.permissions_oracle import oracle_decide
from tests.test_permissions_migrate import NOW as MIGRATE_NOW, legacy_home  # noqa: F401
from tests.test_permissions_server import enforce_server  # noqa: F401
from tests.test_recall_margins import engram_server_env  # noqa: F401


# ---------------------------------------------------------------- T1: a grant behind a grant's envelope (P 6.5, L8)

C1, C2 = "collection:andy/c1", "collection:andy/c2"


def _envelope(collections):
    return selector_json(parse_selector({
        "audience": ["self"], "requesters": "*", "actions": "*", "purposes": "*",
        "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": collections,
                    "memories": "*"}}))


def _nested(*, revoke_inner=False):
    """An allow at Andy's home names c1. m1 is in c1 only under G1, whose envelope names c2 and which expires
    2026-11-30; and in c2 only under G2, which expires 2026-11-05. So the allow holds only while G2 does."""
    w = andy_world()
    w.agent("helper", HOME, at=HOME)
    g1 = w.grant("person:andy", "agent:helper", HOME, ops=("collect",), envelope=_envelope([C2]),
                 expires=T("2026-11-30"))
    g2 = w.grant("person:andy", "agent:helper", HOME, ops=("collect",), envelope=_envelope("*"),
                 expires=T("2026-11-05"))
    w.collect(C1, [M1], backing="grant:" + g1)
    w.collect(C2, [M1], backing="grant:" + g2)
    w.allow(HOME, audience=["self"], collections=[C1], actions=["recall"])
    if revoke_inner:
        w.revoke_grant(g2)
    return w.state()


def test_t1_until_and_horizon_stop_at_the_expiry_of_the_grant_the_envelope_relies_on():
    s = _nested()
    d = decide(s, home_use(M1, T("2026-11-02")))
    assert d.allowed
    assert d.until == d.horizon == T("2026-11-05")
    assert not decide(s, home_use(M1, T("2026-11-05"))).allowed        # L8: it flips at the horizon, not after


def test_t1_a_use_after_the_inner_grant_expires_is_refused_with_expired():
    d = decide(_nested(), home_use(M1, T("2026-11-05")))
    assert d.refusal == Refusal("EXPIRED", HOME, "recall")


def test_t1_a_use_after_the_inner_grant_is_revoked_is_refused_with_grant_invalid():
    d = decide(_nested(revoke_inner=True), home_use(M1, T("2026-11-02")))
    assert d.refusal == Refusal("GRANT_INVALID", HOME, "recall")


def test_t1_an_eligible_set_ends_at_the_inner_grants_expiry():
    s = _nested()
    es = eligible_set(s, [Placement("p1", M1, "store:house")], requester="agent:rio-grande", place=HOME,
                      purpose="care-coordination", action="recall", at=T("2026-11-02"))
    assert es.memory_ids == {"p1"} and es.horizon == T("2026-11-05")
    later = replace(home_use(M1, T("2026-11-02")), copy="store:house")
    assert not decide(s, replace(later, at=es.horizon)).allowed


# ---------------------------------------------------------------- T2: a delivered item is never written to the genome

GENOME_REFUSED = {"error": "delivered content cannot be written to the genome: remember it without genome=True to keep "
                           "it in this store", "layer": "rejected"}


def _genome_store():
    server._genome_db_path.parent.mkdir(parents=True, exist_ok=True)
    Storage(str(server._genome_db_path)).close()


def _genome_writes():
    g = Storage(str(server._genome_db_path))
    try:
        return g.conn.execute("SELECT count(*) FROM episodes WHERE episode_type = 'genome_write'").fetchone()[0]
    finally:
        g.close()


def _set_gate(root, mode):
    led = Ledger.open(root)
    try:
        led.perform(Act("gate", {"mode": mode}), actor=ANDY, channel="terminal", now=T("2026-11-02"))
    finally:
        led.close()


def _episodes():
    return server._storage.conn.execute("SELECT count(*) FROM episodes").fetchone()[0]


def test_t2_remember_into_the_genome_after_a_delivery_is_refused_and_writes_nothing(
        keep_world_with_imprint_allowed):
    _genome_store()
    deliver_m1_through(keep_world_with_imprint_allowed, "neighbors")
    before = _episodes()
    copies = len(Ledger.open_read_only(server.ENGRAM_HOME).state().copies)
    assert server.remember(content=M1_TEXT, genome=True) == GENOME_REFUSED
    assert _genome_writes() == 0 and _episodes() == before
    assert len(Ledger.open_read_only(server.ENGRAM_HOME).state().copies) == copies
    assert "episode_id" in server.remember(content=M1_TEXT)          # it can still be kept in this store


def test_t2_under_shadow_the_genome_write_goes_on_and_is_reported(keep_world_with_imprint_allowed):
    _genome_store()
    _set_gate(keep_world_with_imprint_allowed.root, "shadow")
    deliver_m1_through(keep_world_with_imprint_allowed, "neighbors")
    out = server.remember(content=M1_TEXT, genome=True)
    assert "episode_id" in out and out.get("would_refuse") is True and _genome_writes() == 1


def test_t2_remember_into_the_genome_of_content_never_delivered_is_unchanged(keep_world_with_imprint_allowed):
    _genome_store()
    out = server.remember(content="a genome note nobody delivered to this agent", genome=True)
    assert "episode_id" in out and "would_refuse" not in out and _genome_writes() == 1


# ---------------------------------------------------------------- T3: a replacement never states a wider record (P 7.1, P8)

JENN_HOME = "place:home/jenn"             # no agent works there, so a record whose audience is it has an empty region


def _medical_allow(w):
    """An allow at Andy's home for Jenn's home on the medical-history collection, until 2027-01-31."""
    return w.allow(HOME, audience=[JENN_HOME], collections=[MEDICAL], actions=["recall", "read", "inject_context"],
                   valid_until=T("2027-01-31"))


def test_t3_a_narrowing_may_not_state_wider_fields_when_the_old_records_region_is_empty():
    w = andy_world()
    rid = _medical_allow(w)
    s = w.state()
    old = s.records[rid]
    for wider in (old._replace(selector=dataclasses.replace(old.selector, collections=STAR)),
                  old._replace(selector=dataclasses.replace(old.selector, audience=("commons",))),
                  old._replace(valid_until=T("2027-12-31")), old._replace(valid_until=None)):
        with pytest.raises(RuleError, match="lies within the record it replaces"):
            check_narrower(s, wider, old)
    check_narrower(s, old._replace(valid_until=T("2027-01-01")), old)                 # a real shortening
    check_narrower(s, old._replace(selector=dataclasses.replace(old.selector, actions=("recall",))), old)


def _stated_wider_replacement():
    """A ledger written before T3's fix: R names medical-history (m1 to m3) until 2027-01-31, and R', which
    replaces it and is live, states every collection until 2027-12-31. R is revoked."""
    w = andy_world()
    rid = w.allow(HOME, audience=["self"], collections=[MEDICAL], actions=["recall", "read", "inject_context"],
                  valid_until=T("2027-01-31"))
    r = w.record(rid)
    wide = w.allow(HOME, audience=["self"], collections="*", actions=["recall", "read", "inject_context"],
                   valid_until=T("2027-12-31"), replaces=rid, anchor=r.anchor)
    w.revoke(rid)
    return w, rid, wide


def test_t3_share_cover_reads_a_record_through_its_replaces_chain():
    w, _, wide = _stated_wider_replacement()
    s = w.state()
    cover = lambda obj, at: share_cover(s, owner=ANDY, obj=obj, audience=HOME, at=at)       # noqa: E731
    assert cover(M1, T("2026-12-01")) == wide                  # m1 is in medical-history, inside R's interval
    assert decide(s, home_use(M4, T("2026-12-01"))).allowed is False
    assert cover(M4, T("2026-12-01")) is None                  # m4 never was: R' states it, R does not
    assert cover(M1, T("2027-06-01")) is None                  # past R's end, which bounds R'
    assert not placement_still_counts(s, wide, owner=ANDY, obj=M4, at=T("2026-12-01"))


def test_t3_an_agents_narrowing_grant_covers_a_record_only_where_its_chain_meets_the_envelope():
    w, _, wide = _stated_wider_replacement()
    w.collect("collection:andy/other", [M4])
    env = _envelope(["collection:andy/other"])
    gid = w.grant(ANDY, "agent:rio-grande", HOME, ops=("narrow", "shorten"), envelope=env, expires=T("2027-06-01"))
    s = w.state()
    act = Act("shorten", {"record": wide, "valid_until": T("2027-01-01"), "reason": "test"})
    assert authorize(s, "agent:rio-grande", act, channel="tool", at=T("2026-11-02")).outcome == "proposal"
    w.collect(MEDICAL, [M4])                                   # now R itself meets the envelope through m4
    got = authorize(w.state(), "agent:rio-grande", act, channel="tool", at=T("2026-11-02"))
    assert (got.outcome, got.under_grant) == ("do", gid)


# ---------------------------------------------------------------- T4: genome sync under a closed gate (P 12.3, P25)

def _mark(instance, value):
    if value is None:
        instance.conn.execute("DELETE FROM meta WHERE key = 'permissions_ledger_id'")
    else:
        instance.conn.execute("INSERT OR REPLACE INTO meta(key, value) VALUES('permissions_ledger_id', ?)", (value,))
    instance.conn.commit()


def _synced(instance):
    return [r["id"] for r in instance.conn.execute("SELECT id FROM episodes WHERE episode_type = 'genome_sync'")]


def test_t4_genome_sync_under_a_closed_gate_skips_and_a_later_sync_keeps_the_subjects(tmp_path, monkeypatch):
    led, genome_path, instance, ids = genome_world(tmp_path, mode="enforce")
    ledger_id = led.meta()["ledger_id"]
    led.close()
    _mark(instance, "a-ledger-from-another-home")          # the store's mark is not this ledger's: closed
    assert effective_gate(tmp_path, [Path(instance.db_path)]).mode == "closed"
    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "_storage", instance)
    monkeypatch.setattr(server, "_genome_db_path", genome_path)
    assert server._sync_genome_kept(fails_the_test) == 0 and _synced(instance) == []
    _mark(instance, ledger_id)                              # the gate opens again: the sync now records the copy
    assert server._sync_genome_kept(federation.sync_genome) == 1
    [local] = _synced(instance)
    s = Ledger.open_read_only(tmp_path).state()
    assert "person:jenn" in subjects_of(s, f"mem:{ids.I}/episode/{local}", T("2026-11-02"))


def test_t4_genome_sync_with_no_ledger_is_mains(tmp_path, monkeypatch):
    _, genome_path, instance, _ = genome_world(tmp_path, mode=None)
    monkeypatch.setattr(server, "ENGRAM_HOME", tmp_path)
    monkeypatch.setattr(server, "_storage", instance)
    monkeypatch.setattr(server, "_genome_db_path", genome_path)
    assert server._sync_genome_kept(federation.sync_genome) == 1 and len(_synced(instance)) == 1
    assert not ledger_path(tmp_path).exists()


# ---------------------------------------------------------------- T5: placements are listed and removed for the owner (P23)

OWNER_ONLY = {"error": "only agents acting for the ledger owner can read this"}
OWNER_ONLY_UNSHARE = {"error": "only agents acting for the ledger owner can remove a placement"}


def _place_jenns_result():
    """A placement in the published house whose reason names a person and a diagnosis. Returns its share id."""
    src = Storage(str(server.ENGRAM_HOME / "andy-src.db"))
    try:
        src.add_episode(id="jenn-1", session_id=None, content="Jenn's test came back", episode_type="x")
        src.conn.commit()
        with server._published_house_storage() as (_p, house):
            return sharing.share(source_storage=src, published_storage=house, source_id="jenn-1", layer="episode",
                                 audience="group:jenn-care", reason="Jenn's [condition] result for her care group",
                                 source_instance="default", source_instance_id="andy-store").share_id
    finally:
        src.close()


def _placed(share_id):
    with server._published_house_storage() as (_p, house):
        return house.conn.execute("SELECT count(*) FROM shared_memories WHERE share_id = ?",
                                  (share_id,)).fetchone()[0]


@pytest.mark.parametrize("mode", ["enforce", "shadow", "off"])
def test_t5_an_agent_not_acting_for_the_owner_is_refused_the_placements_under_every_gate(keep_world, mode):
    sid = _place_jenns_result()
    if mode != "enforce":
        _set_gate(keep_world.root, mode)
    assert server._agent_ref() == "agent:ph-coordinator"
    assert server.shares() == OWNER_ONLY and server.shares(audience="group:jenn-care") == OWNER_ONLY
    assert server.unshare(share_id=sid) == OWNER_ONLY_UNSHARE and _placed(sid) == 1
    assert server.unshare(share_id="no-such-share") == OWNER_ONLY_UNSHARE      # the same reply: nothing told


def test_t5_an_unreadable_ledger_lists_nothing_and_unshare_still_works(keep_world):
    sid = _place_jenns_result()
    make_ledger_unreadable(keep_world.root)
    out = server.shares()
    assert "shares" not in out and "Jenn" not in json.dumps(out)
    assert server.unshare(share_id=sid) == {"removed": True} and _placed(sid) == 0     # U11: it only narrows


def test_t5_the_owners_agent_still_lists_and_removes_its_placements(enforce_server):
    sid = _place_jenns_result()
    assert server._agent_ref() == "agent:default"
    [row] = server.shares()["shares"]
    assert row["share_id"] == sid and row["reason"] == "Jenn's [condition] result for her care group"
    assert server.unshare(share_id=sid) == {"removed": True} and _placed(sid) == 0


# ---------------------------------------------------------------- T6: an object in an unregistered store (P 6.3 item 1, P32)

K_COPY, K_MEM, K_ROAD = "mem:nowhere/episode/c1", "mem:nowhere/episode/x", "road:nowhere/r1"   # no `stores` row


def _unregistered_k():
    """Andy's home allows Rio Grande everything on memories and roads. `nowhere` is no registered store, yet its
    objects have co-subject rows and one is a copy of m1, as an unchecked write could leave them."""
    w = andy_world()
    w.copy(K_COPY, M1)
    w.subject(K_COPY, ANDY)
    w.subject(K_MEM, ANDY)
    w.allow(HOME, audience=["self"], kinds=["memory", "road"])
    return w


@pytest.mark.parametrize("obj,names", [(K_COPY, ()), (K_MEM, ()), (K_ROAD, (M1,))])
def test_t6_an_object_in_an_unregistered_store_has_no_subject_and_is_refused_with_no_layer(obj, names):
    w = _unregistered_k()
    s = w.state()
    u = replace(home_use(obj, T("2026-11-02"), action="route" if obj == K_ROAD else "recall"), names=names)
    d = decide(s, u)
    assert d.refusal == Refusal("NO_LAYER", None, None) and not d.allowed
    assert oracle_decide(s.to_tables(), dict(s.seq_at), use_json(u), seq=s.seq) == ("NO_LAYER", None, None)
    assert decide(s, home_use(M1, T("2026-11-02"))).allowed           # its registered source is decided as before


def test_t6_a_kept_copy_is_never_recorded_into_an_unregistered_store(tmp_path):
    led = e1_ledger_through_andys_side(tmp_path)
    s = led.state()
    store = next(iter(s.stores))
    with pytest.raises(RuleError, match="no registered store"):
        led.record_copy(K_COPY, f"mem:{store}/episode/m1", now=T("2026-11-03"))
    assert K_COPY not in led.state().copies
    led.record_copy(f"mem:{store}/episode/kept-1", f"mem:{store}/episode/m1", now=T("2026-11-03"))
    assert led.state().copies[f"mem:{store}/episode/kept-1"] == f"mem:{store}/episode/m1"


# ---------------------------------------------------------------- T7: what the retention fold counts (P 9.1, 9.3)

LOCAL = "ledger-local"
DAY = 86400


def _receipt(**kw):
    base = dict(at=T("2025-06-01"), ledger_id=LOCAL, ledger_seq=3, agent="agent:rio-grande", place=HOME,
                acting_for=HOME, action="read", purpose="care-coordination", allowed=1, cited="[]", object=M1,
                copy="store:house", shadow=0)
    base.update(kw)
    return UseRow(**base)


def _monthly(uses):
    return {(r["subject"], r["action"], r["outcome"]): r["n"] for r in uses.conn.execute("SELECT * FROM uses_monthly")}


def test_t7_the_fold_counts_no_shadow_receipt_no_empty_recall_and_no_imported_row(tmp_path):
    uses = Uses.open(tmp_path)
    andy = [(ANDY, M1)]
    uses.append(_receipt(allowed=0), andy)                                    # a refused read: counted
    uses.append(_receipt(allowed=0, shadow=1), andy)                          # what shadow would refuse: not
    uses.append(_receipt(allowed=1, shadow=1), andy)                          # nor what it would allow
    uses.append(_receipt(action="recall", object=None, returned="[]", filtered=20), [])   # a recall of nothing
    uses.append(_receipt(action="recall", object=None, returned=json.dumps([M1]), filtered=0), andy)   # counted
    uses.append_imported(UseRow(id="u-" + "cd" * 16, at=T("2025-06-01"), ledger_id="peer-station", ledger_seq=7,
                                agent="agent:station", place=HOME, acting_for=ANDY, action="route",
                                purpose="care-coordination", object=None, copy="imprint:peer-station/i1", allowed=1,
                                cited="[]", returned=json.dumps({"count": 1}), shadow=0), [(ANDY, "imprint:x/i1")])
    assert uses.fold(now=T("2025-06-01") + (RETENTION_DAYS + 5) * DAY, ledger_id=LOCAL) == 6
    assert _monthly(uses) == {(ANDY, "read", "refused"): 1, (ANDY, "recall", "allowed"): 1}
    assert uses.conn.execute("SELECT count(*) FROM uses").fetchone()[0] == 0 and uses.verify() is None


# ---------------------------------------------------------------- T8, T10 and the last admin: the ledger stays writable

def test_t10_the_ledger_owner_is_never_retired_and_the_ledger_stays_writable(tmp_path):
    led = Ledger.create(tmp_path, "andy", now=T("2026-11-01"))
    with pytest.raises(RuleError, match="person:andy owns this ledger"):
        led.perform(Act("retire-person", {"person": ANDY}), actor=ANDY, channel="terminal", now=T("2026-11-02"))
    assert led.state().persons[ANDY].retired_seq is None
    led.perform(Act("register-person", {"person": "person:jenn"}), actor=ANDY, channel="terminal", now=T("2026-11-02"))


def test_t10_person_retire_of_the_owner_is_refused_before_the_yes(cli_home, capsys):
    before = Ledger.open(cli_home).seq()
    assert cli_main(["person", "retire", "andy"]) == 1          # a yes asked for would wait, then exit 3
    err = capsys.readouterr().err
    assert "person:andy owns this ledger" in err and "code:" not in err
    assert Ledger.open(cli_home).seq() == before


def test_the_last_admin_is_never_retired():
    w = World()
    w.person("bob", admin=True)
    s = w.state()
    _may_retire_person(s, "person:bob", {"person": "person:bob"})       # Andy, the owner, is an admin still
    w._find("persons", id=ANDY)["retired_seq"] = w._bump()             # a ledger whose owner was retired before
    with pytest.raises(RuleError, match="person:bob is this ledger's last admin"):
        _may_retire_person(w.state(), "person:bob", {"person": "person:bob"})


_KILL_AT_THE_SIXTH_ACT = """
import os, signal, sys
import permission_cli, permission_ledger
permission_cli.confirm = lambda words, change: True        # the yes is not what this tests
permission_cli._owner_login = lambda: "andy"
permission_cli._now = lambda: {now}
real, n = permission_ledger.Ledger.perform, [0]
def perform(self, *a, **k):
    n[0] += 1
    if n[0] == 6:
        os.kill(os.getpid(), signal.SIGKILL)               # the terminal closes: no Python clean-up runs
    return real(self, *a, **k)
permission_ledger.Ledger.perform = perform
sys.exit(permission_cli.main(["migrate"]))
"""


def test_t8_a_migrate_killed_part_way_leaves_no_ledger_and_runs_again(legacy_home, fake_tty):
    engram = Path(permission_cli.__file__).resolve().parent
    env = dict(os.environ, ENGRAM_HOME=str(legacy_home), PYTHONPATH=str(engram), PYTHONDONTWRITEBYTECODE="1")
    done = subprocess.run([sys.executable, "-c", _KILL_AT_THE_SIXTH_ACT.format(now=MIGRATE_NOW)], env=env,
                          cwd=engram, capture_output=True, timeout=300)
    assert done.returncode == -signal.SIGKILL, done.stderr
    path = ledger_path(legacy_home)
    assert not path.exists()
    fake_tty.answer_the_printed_code()
    assert cli_main(["migrate"]) == 0 and path.exists()
    assert sorted(p.name for p in path.parent.glob("permissions.db*")) == ["permissions.db"]
    assert Ledger.open(legacy_home).verify() is None


# ---------------------------------------------------------------- T9: the yes is the terminal's alone (P 7.6, R12)

def test_t9_the_words_and_the_code_are_shown_on_the_terminal_and_never_on_stdout(fake_tty, capsys):
    fake_tty.mirror = False
    fake_tty.answer_the_printed_code()
    assert permission_cli.confirm("THE WORDS", "THE CHANGE") is True
    out = capsys.readouterr()
    assert "THE WORDS" not in out.out + out.err and fake_tty.code not in out.out + out.err
    shown = fake_tty.shown()
    assert shown.index("THE WORDS") < shown.index("THE CHANGE") < shown.index("code: " + fake_tty.code)


def test_t9_with_no_terminal_nothing_is_shown_and_the_yes_is_refused(monkeypatch, capsys, tmp_path):
    monkeypatch.setattr(permission_cli, "TTY", str(tmp_path / "no-such-tty"))
    with pytest.raises(permission_cli.NoTerminal):
        permission_cli.confirm("THE WORDS", "THE CHANGE")
    out = capsys.readouterr()
    assert out.out == "" and out.err == ""


# ---------------------------------------------------------------- T13: the owner is the process's own login (R24)

def test_t13_the_owner_comes_from_the_process_uid_not_from_the_environment(monkeypatch):
    for name in ("LOGNAME", "USER", "LNAME", "USERNAME"):
        monkeypatch.setenv(name, "mallory")
    assert permission_cli._owner_login() == pwd.getpwuid(os.getuid()).pw_name != "mallory"


# ---------------------------------------------------------------- T14: a place publishes the records in force (P 9.4)

def test_t14_place_rules_leaves_out_a_record_past_its_end_and_keeps_one_that_starts_later(tmp_path):
    led = e1_county_ledger(tmp_path)
    sw = "place:la-county/summer-wellness"
    shorter = do(led, "person:sw-steward", "shorten", now="2026-11-02", record=led.ids.W1,
                 valid_until=T("2026-12-01"), reason="ends sooner").ref
    w1 = led.state().records[shorter]
    later = do(led, "person:sw-steward", "deny", now="2026-11-02", layer=sw, selector=w1.selector,
               valid_from=T("2027-01-01"), valid_until=None, reason="from January").ref
    published = lambda at: {r["id"] for r in led.place_rules(sw, now=at)["payload"]["records"]}   # noqa: E731
    assert published(T("2026-11-30")) == {shorter, later}
    assert published(T("2026-12-01")) == {later}           # past its valid_until: no longer in force
    assert led.ids.W1 not in published(T("2026-11-02"))    # the revoked record it replaced
