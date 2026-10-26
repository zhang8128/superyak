"""Task 26A: engram-permissions allow, deny, revoke, shorten, narrow, grants, sign, decline, proposals
(P 7.1 to 7.7; U14, U18, U26, R26, R27)."""
import json

import pytest

import permission_cli
from permission_cli import main
from permission_ledger import Ledger
from permissions import Act, parse_selector, selector_json
from tests.test_permissions_cli import option_names
from tests.permissions_support import (ANDY, HOME, T, cli_home, cli_home_with_house, fake_tty, house_before_029,
                                       house_meta, ledger_bytes, log_rows, register_default_agent_at_home)

PARKS = "place:la-county/parks-and-rec"
AGENT = "agent:default"
FROM, UNTIL = "2026-11-01", "2027-01-31"


def sel(audience=(PARKS,), **objects):
    obj = {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*", "collections": ["collection:andy/c"],
           "memories": "*"}
    obj.update(objects)
    return {"audience": list(audience), "requesters": "*", "objects": obj, "actions": ["recall", "read"],
            "purposes": ["care-coordination"]}


def canon(doc):
    return selector_json(parse_selector(doc))


def run(argv, fake_tty):
    fake_tty.answer_the_printed_code()
    return main(argv)


def led_of(home):
    return Ledger.open(home)


def records(home):
    led = led_of(home)
    try:
        return dict(led.state().records)
    finally:
        led.close()


def allow_argv(doc=None, *extra):
    return ["allow", "--layer", HOME, "--selector", json.dumps(doc or sel()), "--from", FROM, "--until", UNTIL,
            "--reason", "because", *extra]


def make_allow(home, fake_tty, doc=None):
    assert run(allow_argv(doc), fake_tty) == 0
    return max(records(home).values(), key=lambda r: r.created_seq).id


def make_deny(home, fake_tty):
    assert run(["deny", "--layer", HOME, "--selector", json.dumps(sel()), "--from", FROM, "--until", UNTIL],
               fake_tty) == 0
    return max(records(home).values(), key=lambda r: r.created_seq).id


def agent_files(home, kind, args):
    led = led_of(home)
    try:
        out = led.perform(Act(kind, args), actor=AGENT, channel="tool", now=T("2026-11-02"))
        assert out.status == "proposal", kind
        return out.ref
    finally:
        led.close()


def with_agent(home):
    led = led_of(home)
    try:
        register_default_agent_at_home(led)
    finally:
        led.close()


def open_proposals(home):
    led = led_of(home)
    try:
        return led.proposals(now=T("2026-11-03"))
    finally:
        led.close()


def sample_args(home, fake_tty):
    """One argv for every writing subcommand of this task, in an order each can run."""
    allow_id = make_allow(home, fake_tty)
    deny_id = make_deny(home, fake_tty)
    deny_id2 = make_deny(home, fake_tty)
    with_agent(home)
    pid = agent_files(home, "allow", {"layer": HOME, "selector": canon(sel()), "valid_from": T(FROM),
                                      "valid_until": T(UNTIL), "reason": "r"})
    pid2 = agent_files(home, "allow", {"layer": HOME, "selector": canon(sel(collections=["collection:andy/d"])),
                                       "valid_from": T(FROM), "valid_until": T(UNTIL), "reason": "r"})
    env = json.dumps(sel())
    return [
        allow_argv(),
        ["deny", "--layer", HOME, "--selector", json.dumps(sel()), "--from", FROM],
        ["narrow", allow_id, "--selector", json.dumps(sel(memories=["mem:S/episode/m1"]))],
        ["shorten", deny_id, "--until", "2026-12-01"],
        ["revoke", deny_id2, "--reason", "changed my mind"],
        ["grant", "--to", AGENT, "--ops", "share", "--envelope", env, "--max-days", "30", "--depth", "0",
         "--hours", "24"],
        ["sign", pid],
        ["decline", pid2],
    ]


def test_u18_no_command_acts_as_anyone_but_the_owner(cli_home, fake_tty):
    for argv in sample_args(cli_home, fake_tty):
        assert run(argv, fake_tty) == 0, argv
    # revoke-grant needs a grant id
    gid = next(iter(grants(cli_home)))
    assert run(["revoke-grant", gid], fake_tty) == 0
    assert {row["actor"] for row in log_rows(cli_home) if row["channel"] == "terminal"} == {"person:andy"}
    assert not option_names(permission_cli.build_parser()) & {"--as", "--actor", "--person", "--by", "--owner"}


def grants(home):
    led = led_of(home)
    try:
        return dict(led.state().grants)
    finally:
        led.close()


def test_u18_each_widening_act_works_only_with_the_yes(cli_home, fake_tty):
    argvs = sample_args(cli_home, fake_tty)
    for argv in argvs:
        before = ledger_bytes(cli_home)
        fake_tty.answer("wrong1")
        assert main(argv) == 3 and ledger_bytes(cli_home) == before, argv
        assert run(argv, fake_tty) == 0, argv
    gid = next(iter(grants(cli_home)))
    before = ledger_bytes(cli_home)
    fake_tty.answer("wrong1")
    assert main(["revoke-grant", gid]) == 3 and ledger_bytes(cli_home) == before
    assert run(["revoke-grant", gid], fake_tty) == 0


def test_u26_the_cli_takes_full_ids_and_unique_prefixes_and_refuses_ambiguous_ones(
        cli_home, fake_tty, capsys, monkeypatch):
    import os
    import permission_ledger
    monkeypatch.setattr(permission_ledger, "new_id", lambda prefix: prefix + "ab12" + os.urandom(14).hex())
    a = make_allow(cli_home, fake_tty, sel(memories=["mem:S/episode/m1"]))
    b = make_allow(cli_home, fake_tty, sel(memories=["mem:S/episode/m2"]))
    assert a[:6] == b[:6] and a[:8] != b[:8]
    capsys.readouterr()
    assert run(["revoke", a, "--reason", "r"], fake_tty) == 0               # a full id
    assert run(["revoke", b[:8], "--reason", "r"], fake_tty) == 0           # a unique prefix
    c = make_allow(cli_home, fake_tty, sel(memories=["mem:S/episode/m3"]))
    capsys.readouterr()
    before = ledger_bytes(cli_home)
    assert run(["revoke", c[:6], "--reason", "r"], fake_tty) == 1           # ambiguous: a, b and c
    err = capsys.readouterr().err
    assert a in err and b in err and c in err and ledger_bytes(cli_home) == before


def test_a_prefix_that_is_unique_resolves(cli_home, fake_tty):
    rid = make_allow(cli_home, fake_tty)
    assert run(["revoke", rid[:8], "--reason", "r"], fake_tty) == 0
    assert records(cli_home)[rid].revoked_seq is not None


def test_a_prefix_matching_nothing_is_refused(cli_home, fake_tty, capsys):
    assert run(["revoke", "r-ffffffff", "--reason", "r"], fake_tty) == 1
    assert "matches no id" in capsys.readouterr().err


def test_allow_prints_the_words_and_the_whole_change_before_the_code(cli_home, fake_tty, capsys):
    capsys.readouterr()
    assert run(allow_argv(), fake_tty) == 0
    out = capsys.readouterr().out
    assert out.index("Share collection andy/c with " + PARKS) < out.index("code:")
    assert out.index('"audience":["place:la-county/parks-and-rec"]') < out.index("code:")
    for needle in ("valid_from", "valid_until", HOME, "layer", "2027-01-31"):
        assert out.index(needle) < out.index("code:"), needle


def test_deny_writes_a_deny_and_prints_refuse(cli_home, fake_tty, capsys):
    capsys.readouterr()
    rid = make_deny(cli_home, fake_tty)
    assert records(cli_home)[rid].effect == "deny"
    assert "Refuse" in capsys.readouterr().out


def test_allow_reads_the_selector_from_a_file(cli_home, fake_tty, tmp_path):
    path = tmp_path / "sel.json"
    path.write_text(json.dumps(sel()))
    argv = ["allow", "--layer", HOME, "--selector", "@" + str(path), "--from", FROM, "--until", UNTIL]
    assert run(argv, fake_tty) == 0
    [rec] = records(cli_home).values()
    assert selector_json(rec.selector) == canon(sel()) and rec.valid_until == T(UNTIL)


def test_a_bad_selector_is_refused_by_the_rule_and_a_missing_file_too(cli_home, fake_tty, capsys):
    before = ledger_bytes(cli_home)
    assert run(["allow", "--layer", HOME, "--selector", "{not json", "--from", FROM], fake_tty) == 1
    assert run(["allow", "--layer", HOME, "--selector", "@/no/such/file.json", "--from", FROM], fake_tty) == 1
    assert ledger_bytes(cli_home) == before
    assert "refused" in capsys.readouterr().err


def test_a_selector_file_over_the_limit_is_not_read_whole(cli_home, fake_tty, tmp_path, capsys):
    path = tmp_path / "big.json"
    path.write_text(" " * (permission_cli.SELECTOR_FILE_BYTES + 10))
    assert run(["allow", "--layer", HOME, "--selector", "@" + str(path), "--from", FROM], fake_tty) == 1
    assert "too large" in capsys.readouterr().err


def test_narrow_and_shorten_print_the_replaced_record_and_replace_it(cli_home, fake_tty, capsys):
    rid = make_allow(cli_home, fake_tty)
    capsys.readouterr()
    assert run(["shorten", rid, "--until", "2026-12-01"], fake_tty) == 0
    out = capsys.readouterr().out
    assert out.index(rid) < out.index("code:") and out.index("replaces") < out.index("code:")
    assert out.index('"audience":["place:la-county/parks-and-rec"]') < out.index("code:")
    recs = records(cli_home)
    new = next(r for r in recs.values() if r.replaces == rid)
    assert new.valid_until == T("2026-12-01") and recs[rid].revoked_seq is not None
    assert run(["narrow", new.id, "--selector", json.dumps(sel(memories=["mem:S/episode/m1"]))], fake_tty) == 0
    newer = next(r for r in records(cli_home).values() if r.replaces == new.id)
    assert newer.selector.memories == ("mem:S/episode/m1",)


def test_revoke_withdraws_a_record_with_the_reason(cli_home, fake_tty):
    rid = make_allow(cli_home, fake_tty)
    assert run(["revoke", rid, "--reason", "no longer"], fake_tty) == 0
    rec = records(cli_home)[rid]
    assert rec.revoked_seq is not None and rec.revoke_reason == "no longer"


def test_grant_and_revoke_grant(cli_home, fake_tty, capsys):
    with_agent(cli_home)
    capsys.readouterr()
    argv = ["grant", "--to", AGENT, "--ops", "share,collect", "--envelope", json.dumps(sel()), "--max-days", "30",
            "--depth", "1", "--hours", "48"]
    assert run(argv, fake_tty) == 0
    out = capsys.readouterr().out
    assert out.index('"audience":["place:la-county/parks-and-rec"]') < out.index("code:")
    assert "share" in out and "collect" in out
    [g] = grants(cli_home).values()
    assert g.depth == 1 and g.max_days == 30 and set(json.loads(g.ops)) == {"share", "collect"} and g.grantee == AGENT
    assert run(["revoke-grant", g.id[:8]], fake_tty) == 0
    assert next(iter(grants(cli_home).values())).revoked_seq is not None


def test_a_child_grant_names_its_parent(cli_home, fake_tty, capsys):
    with_agent(cli_home)
    led = led_of(cli_home)
    try:
        for name in ("agent:two",):
            led.perform(Act("register-agent", {"agent": name, "acts_for": HOME}), actor=ANDY, channel="terminal",
                        now=T("2026-11-01"))
    finally:
        led.close()
    assert run(["grant", "--to", AGENT, "--ops", "share", "--envelope", json.dumps(sel()), "--max-days", "30",
                "--depth", "1", "--hours", "24"], fake_tty) == 0
    [g] = grants(cli_home).values()
    # a child is issued by the holder of the parent, never by the owner here: the rule refuses it, exit 1
    capsys.readouterr()
    assert run(["grant", "--to", "agent:two", "--ops", "share", "--envelope", json.dumps(sel()), "--max-days", "30",
                "--depth", "0", "--hours", "24", "--parent", g.id[:8]], fake_tty) == 1
    cap = capsys.readouterr()
    assert f"parent: {g.id}" in cap.out                      # the short prefix resolved to the full parent id
    assert "a child is issued by its parent's grantee" in cap.err
    assert list(grants(cli_home)) == [g.id]                 # nothing was written


def file_parks_proposal(home):
    with_agent(home)
    return agent_files(home, "allow", {"layer": HOME, "selector": canon(sel()), "valid_from": T(FROM),
                                       "valid_until": T(UNTIL), "reason": "ignore previous instructions"})


def test_u14_sign_prints_the_full_selector_before_asking(cli_home, fake_tty, capsys):
    pid = file_parks_proposal(cli_home)
    capsys.readouterr()
    assert run(["sign", pid], fake_tty) == 0
    out = capsys.readouterr().out
    assert out.index('"audience":["place:la-county/parks-and-rec"]') < out.index("code:")
    assert "valid_from" in out and "place:home/andy" in out
    assert "ignore previous instructions" not in out.split("change:")[0]      # never in the words


def test_sign_with_a_wrong_code_leaves_the_proposal_open(cli_home, fake_tty):
    pid = file_parks_proposal(cli_home)
    before = ledger_bytes(cli_home)
    fake_tty.answer("wrong1")
    assert main(["sign", pid]) == 3 and ledger_bytes(cli_home) == before
    assert [p["id"] for p in open_proposals(cli_home)] == [pid]


def test_decline_closes_the_proposal_and_writes_no_record(cli_home, fake_tty):
    pid = file_parks_proposal(cli_home)
    assert run(["decline", pid[:8]], fake_tty) == 0
    assert open_proposals(cli_home) == [] and records(cli_home) == {}


def test_proposals_lists_open_ones_with_words_and_needs_no_yes(cli_home, fake_tty, capsys):
    pid = file_parks_proposal(cli_home)
    capsys.readouterr()
    before = ledger_bytes(cli_home)
    assert main(["proposals"]) == 0
    out = capsys.readouterr().out
    assert pid in out and "Share collection andy/c with " + PARKS in out and AGENT in out
    assert ledger_bytes(cli_home) == before


def test_proposals_says_when_there_are_none(cli_home, capsys):
    assert main(["proposals"]) == 0
    assert "No open proposals" in capsys.readouterr().out


def test_proposals_shows_the_agents_reason_as_one_clean_line(cli_home, fake_tty, capsys):
    with_agent(cli_home)
    agent_files(cli_home, "allow", {"layer": HOME, "selector": canon(sel()), "valid_from": T(FROM),
                                    "valid_until": T(UNTIL), "reason": "a\x1b[31mred"})
    capsys.readouterr()
    assert main(["proposals"]) == 0
    assert "\x1b" not in capsys.readouterr().out


def file_one_of_each_r26_kind(home, fake_tty):
    """(kind, proposal id) for every kind of R26 the tool can file, each through Ledger.perform on channel tool."""
    deny_id, deny_id2, deny_id3 = (make_deny(home, fake_tty) for _ in range(3))
    led = led_of(home)
    try:
        for act in (Act("register-person", {"person": "person:jenn"}),
                    Act("make-collection", {"collection": "collection:andy/c"}),
                    Act("register-store", {"instance_id": "S", "name": "s", "owner": ANDY, "place": HOME}),
                    Act("register-place", {"place": "place:andy-lab", "stewards": [ANDY]}),
                    Act("register-place", {"place": "place:andy-other", "stewards": [ANDY]}),
                    Act("register-place", {"place": "place:andy-lab/x", "parents": ["place:andy-lab"],
                                           "stewards": [ANDY]}),
                    Act("register-agent", {"agent": "agent:two", "acts_for": HOME}),
                    Act("add-subject", {"object": "mem:S/episode/m3", "subject": "person:jenn"})):
            led.perform(act, actor=ANDY, channel="terminal", now=T("2026-11-01"))
    finally:
        led.close()
    with_agent(home)
    acts = [
        Act("allow", {"layer": HOME, "selector": canon(sel()), "valid_from": T(FROM), "valid_until": T(UNTIL),
                      "reason": "r"}),
        Act("shorten", {"record": deny_id, "valid_until": T("2026-12-01")}),
        Act("narrow", {"record": deny_id2, "selector": canon(sel(memories=["mem:S/episode/m1"]))}),
        Act("revoke", {"record": deny_id3}),
        Act("collect", {"collection": "collection:andy/c", "objects": ["mem:S/episode/m4"]}),
        Act("grant", {"layer": HOME, "grantee": "agent:two", "ops": ["share"], "envelope": canon(sel()),
                      "max_days": 30, "depth": 0, "hours": 24}),
        Act("group", {"group": "group:g1", "owner": ANDY, "members": [AGENT]}),
        Act("put-agent", {"agent": "agent:two", "place": "place:andy-lab"}),
        Act("add-steward", {"place": "place:andy-lab", "person": "person:jenn"}),
        Act("add-parent", {"place": "place:andy-lab/x", "parent": "place:andy-other"}),
        Act("register-store", {"instance_id": "Q", "name": "q", "owner": ANDY, "place": HOME}),
        Act("remove-subject", {"object": "mem:S/episode/m3", "subject": "person:jenn"}),
        Act("register-place", {"place": "place:andy-new", "stewards": [ANDY]}),
        Act("register-agent", {"agent": "agent:three", "acts_for": HOME}),
        Act("gate", {"mode": "shadow"}),
    ]
    out = []
    led = led_of(home)
    try:
        for act in acts:
            res = led.perform(act, actor=AGENT, channel="tool", now=T("2026-11-02"))
            assert res.status == "proposal", act.kind
            out.append((act.kind, res.ref))
    finally:
        led.close()
    return out


def test_r26_sign_completes_each_kind_the_tool_files(cli_home_with_house, fake_tty):
    filed = file_one_of_each_r26_kind(cli_home_with_house, fake_tty)
    for kind, pid in filed:
        assert run(["sign", pid], fake_tty) == 0, kind
    assert open_proposals(cli_home_with_house) == []


def file_gate_proposal(home, mode):
    with_agent(home)
    return agent_files(home, "gate", {"mode": mode})


def test_rs2_sign_of_a_gate_proposal_lists_the_houses_and_those_lacking_029_before_the_yes(
        cli_home_with_house, fake_tty, capsys):
    pid = file_gate_proposal(cli_home_with_house, "shadow")
    house_before_029(cli_home_with_house, "old")
    capsys.readouterr()
    assert run(["sign", pid], fake_tty) == 0
    out = capsys.readouterr().out
    assert out.index("instances/old/graph.db") < out.index("code:") and "serves nothing" in out
    assert out.index("instances/lighthouse/graph.db") < out.index("code:")
    old = cli_home_with_house / ".engram" / "instances" / "old" / "graph.db"
    assert house_meta(old)["permissions_ledger_id"] == Ledger.open(cli_home_with_house).meta()["ledger_id"]


def test_a_house_made_between_the_print_and_the_yes_is_marked_and_named_after_it(
        cli_home_with_house, fake_tty, capsys, monkeypatch):
    pid = file_gate_proposal(cli_home_with_house, "shadow")
    real_confirm = permission_cli.confirm

    def late(words, change):
        ok = real_confirm(words, change)
        house_before_029(cli_home_with_house, "late")
        return ok
    monkeypatch.setattr(permission_cli, "confirm", late)
    capsys.readouterr()
    assert run(["sign", pid], fake_tty) == 0
    out = capsys.readouterr().out
    late_path = cli_home_with_house / ".engram" / "instances" / "late" / "graph.db"
    assert "late/graph.db" in out.split("code:")[1]
    assert house_meta(late_path)["permissions_ledger_id"]


def test_sign_of_a_non_proposal_id_is_refused(cli_home, fake_tty, capsys):
    assert run(["sign", "p-ffffffff"], fake_tty) == 1
    assert "refused" in capsys.readouterr().err


def test_every_new_command_with_no_terminal_writes_nothing(cli_home, monkeypatch):
    monkeypatch.setattr(permission_cli, "TTY", str(cli_home / "no-such-tty"))
    before = ledger_bytes(cli_home)
    assert main(allow_argv()) == 3 and ledger_bytes(cli_home) == before


def test_a_huge_proposal_time_does_not_crash_sign_decline_or_proposals(cli_home, fake_tty, capsys):
    with_agent(cli_home)
    huge = 10 ** 15
    pid = agent_files(cli_home, "allow", {"layer": HOME, "selector": canon(sel(audience=(HOME,))),
                                          "valid_from": T(FROM), "valid_until": huge, "reason": "r"})
    capsys.readouterr()
    assert main(["proposals"]) == 0
    assert pid in capsys.readouterr().out
    assert run(["sign", pid[:8]], fake_tty) in (0, 1, 3)    # reviewed, never a traceback
    out = capsys.readouterr().out
    assert str(huge) in out
    if pid in {p["id"] for p in open_proposals(cli_home)}:
        assert run(["decline", pid[:8]], fake_tty) == 0
    assert open_proposals(cli_home) == []
