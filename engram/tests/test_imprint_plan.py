"""imprint.py plan and the dry run (store-copy spec I 5.1, 5.4, R7, R26)."""
import hashlib
import json
import os
import sqlite3
import stat
import sys
from dataclasses import replace
from pathlib import Path

import pytest

import calibrate
from imprint import (Context, ensure_scratch_env, main, make_plan, read_context, read_plan, render_dry_run,
                     resolve_plan, resolve_store)
from imprint_filter import (DIGEST_TABLES, OTHERS_NO_LEDGER_WORDS, PlanRefused, TIMES_WORDS, scope_of)
from tests.imprint_support import (EH, HOME, PLAN_NOW, deny, edit_source, ep, expected_order, live_source, plan_args,
                                   plan_context, vec, write_context)

CONTEXT = plan_context("sam")
ANDY_CONTEXT = plan_context("andy")
FLAGS = ["--lanes", "work", "--layers", "episode,semantic", "--until", "2026-10-25T18:00:00Z"]


def sha(path) -> str:
    return hashlib.sha256(Path(path).read_bytes()).hexdigest()


def scratch_env(monkeypatch, home: Path) -> Path:
    """What the re-executed process finds: a 0700 directory under home/imprints/plans named by three variables."""
    scratch = home / "imprints" / "plans" / "scratch-test"
    scratch.mkdir(parents=True, mode=0o700)
    for key in ("SQLITE_TMPDIR", "TMPDIR", "IMPRINT_SCRATCH"):
        monkeypatch.setenv(key, str(scratch))
    return scratch


def plan_flags(tmp_path: Path, home: Path, *extra: str) -> list[str]:
    store, *_ = plan_args(tmp_path, owner="andy")
    return ["plan", "--store", str(store), "--engram-home", str(tmp_path / "eh2"), *FLAGS,
            "--audience", "place:home/andy", "--superyak-home", str(home), *extra]


def test_plan_never_writes_the_source(tmp_path, monkeypatch):
    src = live_source(tmp_path)                      # a WAL store; a second connection writes during the plan
    before = sha(src.db_path)
    real, wrote = calibrate.snapshot, []

    def snapshot_then_write(source, dest):
        real(source, dest)
        ep(src, "late", at="2026-10-25T11:00:00+00:00")
        wrote.append(1)
    monkeypatch.setattr(calibrate, "snapshot", snapshot_then_write)
    from tests.imprint_support import ctx, selection, terms
    plan = make_plan(Path(src.db_path), selection(), terms(), ctx(src, owner="andy"), ANDY_CONTEXT,
                     home=tmp_path / "home", now=PLAN_NOW)
    assert wrote and plan.contents["episodes"] == 1              # the late row came after the snapshot
    assert sha(src.db_path) == before                            # the writer's page went to the WAL; the plan wrote none
    assert [r[0] for r in src.conn.execute("SELECT id FROM episodes ORDER BY id")] == ["e1", "late"]
    assert list((tmp_path / "home" / "imprints" / "plans").glob("*/")) == []          # scratch removed


def test_plan_file_is_private_and_never_holds_content(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    path = tmp_path / "home" / "imprints" / "plans" / f"{plan.id}.json"
    assert stat.S_IMODE(path.stat().st_mode) == 0o600 and "Jenn drove" not in path.read_text()
    saved = json.loads(path.read_text())
    assert saved["digest"] == plan.digest and saved["terms"]["audience"] == "place:home/andy"


def test_the_dry_run_says_what_leaves_and_what_stays(tmp_path, route_open):
    text = render_dry_run(make_plan(*plan_args(tmp_path, route=True)), CONTEXT)
    for line in ("Imprint plan", "(nothing has left this machine)", "Store id", "lineage complete",
                 "as ship voyager (owner sam)", "Session ids",
                 "sent only because you chose route", TIMES_WORDS.split(";")[0], "when either was last recalled",
                 "What stays here", "Other people:", "Plan digest", "make imprint-send PLAN="):
        assert line in text, line
    assert str(tmp_path / "src.db") in text
    assert "Without route" in render_dry_run(make_plan(*plan_args(tmp_path / "b", route=False)), CONTEXT)


def test_the_dry_run_says_plainly_how_many_memories_name_other_people(tmp_path):
    cos = {"e1": "person:jenn", "e2": ["person:jenn", "person:lee"]}
    at_home = render_dry_run(make_plan(*plan_args(tmp_path, owner="andy", cosubjects=cos)), ANDY_CONTEXT)
    assert "2 memories have other people recorded on them (2 people: jenn, lee)" in at_home
    assert "They will be copied" in at_home and "outside your" in at_home and "patients" in at_home
    assert "copied with them as co-subjects" in at_home
    away = render_dry_run(make_plan(*plan_args(tmp_path / "away", owner="sam", cosubjects=cos)), CONTEXT)
    assert "needs jenn's yes" in away and "stay here" in away and "patient or participant data" in away
    none = render_dry_run(make_plan(*plan_args(tmp_path / "none", owner="andy", ledger=None)), ANDY_CONTEXT)
    assert "can't count them" in none and "no one but you is recorded on them" in none and "on your yes alone" in none
    zero = render_dry_run(make_plan(*plan_args(tmp_path / "zero", owner="andy", cosubjects={})), ANDY_CONTEXT)
    assert OTHERS_NO_LEDGER_WORDS in zero and "0 memories" not in zero and "(0 people" not in zero   # M2
    said_no = render_dry_run(make_plan(*plan_args(tmp_path / "no", owner="andy", cosubjects=cos,
                                                  denies={"person:lee": [deny(actions=["read"], purposes=["calibration"])]})),
                             ANDY_CONTEXT)
    assert "1 memory stays because lee said no" in said_no
    many = {f"e{i + 1}": f"person:p{i:02d}" for i in range(12)}                # the re-check's S3
    capped_plan = make_plan(*plan_args(tmp_path / "many", owner="andy", episodes=12, cosubjects=many))
    capped = render_dry_run(capped_plan, ANDY_CONTEXT)
    assert "(12 people: " + ", ".join(f"p{i:02d}" for i in range(10)) + " and 2 more)" in capped and "p10" not in capped


def test_retired_and_bound_memories_stay_with_their_reasons(tmp_path):
    from tests.imprint_support import retire

    cos = {"e1": "person:ava", "e2": [f"person:q{i}" for i in range(8)]}
    args = list(plan_args(tmp_path, owner="andy", cosubjects=cos))
    retire(args[3].ledger, "person:ava")
    text = render_dry_run(make_plan(*args), ANDY_CONTEXT)
    assert "1 memory stays because ava is retired in your permissions ledger" in text
    assert "1 memory stays because more than 8 people or places are recorded on them" in text
    assert "q0" not in text                                            # the bound line names no one


def test_the_scratch_directory_is_set_before_python_starts(tmp_path):           # R26; the check's S1
    calls, scratch = [], tmp_path / "s"; scratch.mkdir()
    ensure_scratch_env(scratch, environ={"TMPDIR": "/tmp"}, execve=lambda *a: calls.append(a))
    (_, argv, env), = calls
    assert argv[0] == sys.executable and env["SQLITE_TMPDIR"] == env["TMPDIR"] == env["IMPRINT_SCRATCH"] == str(scratch)
    assert env["OPENBLAS_NUM_THREADS"] == "1"          # one BLAS thread, set before numpy loads (review I4)
    ensure_scratch_env(scratch, environ=env, execve=lambda *a: calls.append(a))     # already set: no second exec
    assert len(calls) == 1
    ensure_scratch_env(scratch, environ={"OPENBLAS_NUM_THREADS": "4"}, execve=lambda *a: calls.append(a))
    assert len(calls) == 2 and calls[-1][2]["OPENBLAS_NUM_THREADS"] == "1"        # the caller's own setting gives way


def test_list_writes_one_line_per_row_that_would_leave(tmp_path, monkeypatch):
    home = tmp_path / "h"
    write_context(home, ANDY_CONTEXT)
    scratch_env(monkeypatch, home)
    rc = main(plan_flags(tmp_path, home, "--list", str(tmp_path / "rows.jsonl")))
    lines = [json.loads(l) for l in (tmp_path / "rows.jsonl").read_text().splitlines()]
    assert rc == 0 and lines and {l["table"] for l in lines} <= set(DIGEST_TABLES)
    assert all(set(l) == {"table", "key"} for l in lines)
    assert not (home / "imprints" / "plans" / "scratch-test").exists()          # the command removes its scratch


def test_json_carries_the_dry_run_with_counts_and_no_content(tmp_path, monkeypatch, capsys):
    home = tmp_path / "h"
    write_context(home, ANDY_CONTEXT)
    scratch_env(monkeypatch, home)
    assert main(plan_flags(tmp_path, home, "--json")) == 0
    shown = json.loads(capsys.readouterr().out)
    assert shown["contents"]["episodes"] == 3 and len(shown["digest"]) == 64 and "Jenn drove" not in json.dumps(shown)


def test_until_is_always_written(tmp_path):
    plan = make_plan(*plan_args(tmp_path, until=None))
    assert plan.selection.until == PLAN_NOW and scope_of(plan.selection)["until"] == "2026-10-25T18:00:00Z"


def test_a_plan_naming_another_home_is_refused_before_anything_is_written(tmp_path, monkeypatch, capsys):
    home = tmp_path / "h"; write_context(home, ANDY_CONTEXT)                 # the station said: operator andy
    scratch_env(monkeypatch, home)
    assert main([*plan_flags(tmp_path, home)[:-4], "--audience", "place:home/jenn",
                 "--superyak-home", str(home)]) != 0
    assert not list((home / "imprints" / "plans").glob("*.json"))
    assert "place:home/andy" in capsys.readouterr().err
    assert "acting for andy" in render_dry_run(make_plan(*plan_args(tmp_path / "ok")), CONTEXT)


def test_the_plan_command_refuses_route_before_anything_is_written(tmp_path, monkeypatch, capsys, route_closed):
    """The fresh review's N1: route waits for trails at the command, not only in parse_terms."""
    home = tmp_path / "h"; write_context(home, ANDY_CONTEXT)
    scratch_env(monkeypatch, home)
    assert main(plan_flags(tmp_path, home, "--actions", "imprint,route")) == 2
    assert "route waits until trails ships" in capsys.readouterr().err
    assert not list((home / "imprints" / "plans").glob("*.json"))


def test_the_help_says_route_waits(capsys):                             # the fresh review's N3
    with pytest.raises(SystemExit):
        main(["plan", "--help"])
    shown = " ".join(capsys.readouterr().out.split())
    assert shown.count("waits until trails ships") == 2 and "imprint, or imprint,route" not in shown


def test_without_a_station_context_nothing_is_planned(tmp_path):
    with pytest.raises(PlanRefused, match="No station context"):
        read_context(tmp_path / "h")
    write_context(tmp_path / "h", CONTEXT)
    assert read_context(tmp_path / "h") == CONTEXT


def test_the_store_is_the_one_the_server_would_open_unless_named(tmp_path):
    eh = tmp_path / "eh"
    (eh / ".engram").mkdir(parents=True)
    (eh / ".engram" / "graph.db").write_bytes(b"")
    assert resolve_store(None, engram_home=eh, project_root=tmp_path) == eh / ".engram" / "graph.db"
    assert resolve_store(tmp_path / "x.db", engram_home=eh, project_root=tmp_path) == tmp_path / "x.db"


def test_a_source_the_plan_refuses_leaves_nothing_behind(tmp_path):
    args = list(plan_args(tmp_path, owner="andy", cosubjects={}))
    args[3], args[4] = replace(args[3], owner="jenn"), replace(args[4], owner="jenn")   # the ledger names andy
    with pytest.raises(PlanRefused):
        make_plan(*args)
    assert list((tmp_path / "home" / "imprints" / "plans").glob("*")) == []


PACKAGE_SESSIONS = {"e0": "sx", "e1": "sx", "e2": "sx"}


def test_read_pages_through_what_would_leave(tmp_path):
    plan = make_plan(*plan_args(tmp_path, route=False))
    first = read_plan(plan.id[:4], home=HOME(tmp_path), engram_home=EH(tmp_path))
    rest = read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), start=1, limit=99)
    seen = first + rest
    assert len(first) == 1 and [m["id"] for m in seen] == expected_order(plan) == ["e0", "e1", "e2", "s1"]
    assert [m["position"] for m in seen] == [0, 1, 2, 3] and [m["layer"] for m in seen][-1] == "semantic"
    assert all(m.get("session_id") is None for m in seen if m["layer"] == "episode")      # route off: the package holds null
    assert seen[0]["content"].startswith("Jenn drove") and "content" in seen[3]
    assert list((HOME(tmp_path) / "imprints" / "plans").glob("*/")) == []                # scratch removed


def test_read_shows_a_semantic_as_the_package_holds_it(tmp_path):
    args = plan_args(tmp_path, route=False)
    conn = sqlite3.connect(args[0])
    with conn:
        conn.execute("UPDATE semantics SET contradicted_by = 'home-only' WHERE id = 's1'")
    conn.close()
    plan = make_plan(*args)
    seen = read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
    assert [m["contradicted_by"] for m in seen if m["layer"] == "semantic"] == [None]


def test_read_shows_the_session_where_the_package_keeps_it(tmp_path, route_open):
    plan = make_plan(*plan_args(tmp_path, route=True))
    seen = read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
    sessions = {m["id"]: m["session_id"] for m in seen if m["layer"] == "episode"}
    assert sessions == PACKAGE_SESSIONS


def test_read_refuses_when_the_store_changed(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    edit_source(tmp_path, "e1", content="changed")
    with pytest.raises(PlanRefused, match="changed since the plan"):
        read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path))


def test_read_with_a_ledger_reaches_the_same_digest(tmp_path):
    cos = {"e1": "person:jenn"}
    plan = make_plan(*plan_args(tmp_path, owner="andy", cosubjects=cos))
    seen = read_plan(plan.id, home=HOME(tmp_path), engram_home=EH(tmp_path), limit=99)
    assert [m["id"] for m in seen] == expected_order(plan)


def test_resolve_plan_takes_a_unique_prefix_of_four_or_more(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    home = HOME(tmp_path)
    assert resolve_plan(home, plan.id[:4]) == home / "imprints" / "plans" / f"{plan.id}.json"
    for bad in (plan.id[:3], "zzzz", ""):
        with pytest.raises(PlanRefused, match="plan"):
            resolve_plan(home, bad)
    twin = home / "imprints" / "plans" / (plan.id[:4] + "f" * 28 + ".json")
    twin.write_text("{}")
    with pytest.raises(PlanRefused, match="(?i)more than one"):
        resolve_plan(home, plan.id[:4])


def test_the_read_command_prints_a_page(tmp_path, monkeypatch, capsys):
    home = tmp_path / "home"
    write_context(home, ANDY_CONTEXT)
    plan = make_plan(*plan_args(tmp_path, owner="andy"))
    scratch_env(monkeypatch, home)
    assert main(["read", "--plan", plan.id[:4], "--start", "1", "--limit", "2", "--superyak-home", str(home),
                 "--engram-home", str(EH(tmp_path))]) == 0
    shown = [json.loads(line) for line in capsys.readouterr().out.splitlines()]
    assert [m["id"] for m in shown] == ["e1", "e2"]
