"""--exclude: every id must name a memory in the store, and what it names never leaves (section 2 review S4)."""
import contextlib
import json
import sqlite3
from dataclasses import replace

import pytest

from imprint import build, main, make_plan, plan_dict, render_dry_run
from imprint_filter import PlanRefused, unmatched_exclude
from tests.imprint_support import EH, HOME, ep, iid_of, plan_args, plan_context, write_context

CONTEXT = plan_context("sam")
ANDY_CONTEXT = plan_context("andy")
NOW = 1_761_415_451
FLAGS = ["--lanes", "work", "--layers", "episode,semantic", "--until", "2026-10-25T18:00:00Z"]


def with_exclude(args, exclude):
    args = list(args)
    args[1] = replace(args[1], exclude=frozenset(exclude))
    return args


def plans_written(tmp_path):
    plans = HOME(tmp_path) / "imprints" / "plans"
    return sorted(p.name for p in plans.glob("*")) if plans.exists() else []


def refused(tmp_path, exclude):
    """make_plan with ``exclude`` over the plan_args store (e0 to e2, s1); the refusal's text."""
    args = plan_args(tmp_path)
    with pytest.raises(PlanRefused) as refusal:
        make_plan(*with_exclude(args, exclude(args) if callable(exclude) else exclude))
    assert plans_written(tmp_path) == []                       # nothing was planned, and the scratch is gone
    text = str(refusal.value)
    assert "Jenn drove" not in text and "trip" not in text     # ids only, never content
    return text


def test_a_typo_is_refused(tmp_path):
    text = refused(tmp_path, {"e9"})
    assert text.startswith("1 id in --exclude names no memory in this store or its cold storage")
    assert "'e9'" in text and "nothing was planned" in text


def test_upper_case_is_refused(tmp_path):
    text = refused(tmp_path, {"E1"})
    assert "'E1'" in text and "case" in text


def test_a_mem_ref_is_refused(tmp_path):
    ref = []

    def mem_ref(args):
        ref.append(f"mem:{iid_of(args[0])}/episode/e1")
        return set(ref)
    text = refused(tmp_path, mem_ref)
    assert repr(ref[0]) in text and "mem:" in text


def test_a_mix_of_good_and_bad_ids_is_refused_naming_only_the_bad(tmp_path):
    text = refused(tmp_path, {"e1", "s1", "e2 ", "S1", "e7"})
    for bad in ("'e2 '", "'S1'", "'e7'"):
        assert bad in text, bad
    assert "'e1'" not in text and "'s1'" not in text
    assert text.startswith("3 ids in --exclude name no memory")


def test_a_long_list_of_bad_ids_names_twenty_and_counts_the_rest(tmp_path):
    text = refused(tmp_path, {f"x{i:03d}" for i in range(503)})
    assert "'x000'" in text and "'x019'" in text and "'x020'" not in text and "and 483 more" in text


def test_matching_is_exact_by_id_in_either_layer(tmp_path):
    args = plan_args(tmp_path)
    conn = sqlite3.connect(f"file:{args[0]}?mode=ro", uri=True)
    try:
        assert unmatched_exclude(conn, {"e0", "s1", "E0", "e0\n", "mem:x/episode/e0", ""}) == ("", "E0", "e0\n",
                                                                                              "mem:x/episode/e0")
        assert unmatched_exclude(conn, set()) == ()
    finally:
        conn.close()


def test_an_id_outside_the_selection_is_accepted_and_the_dry_run_counts_what_it_left_out(tmp_path):
    def personal(tmp_path):
        from tests.imprint_support import new_store
        s = new_store(tmp_path, "src")
        for i in range(3):
            ep(s, f"e{i}", at=f"2026-10-25T10:0{i}:00+00:00")
        ep(s, "home-only", lane="personal", at="2026-10-25T10:05:00+00:00")
        return s
    plan = make_plan(*with_exclude(plan_args(tmp_path, store=personal), {"e1", "home-only"}))
    assert plan.counts["excluded"] == 1 and plan.counts["exclude_ids"] == 2 and plan.contents["episodes"] == 2
    text = render_dry_run(plan, CONTEXT)
    assert "1 memory stays because --exclude names it; its 2 ids each name a memory in this store." in text
    assert plan_dict(plan)["counts"]["excluded"] == 1


def test_the_dry_run_counts_many_and_says_nothing_without_exclude(tmp_path):
    plan = make_plan(*plan_args(tmp_path, episodes=3, exclude={"e1", "e2"}))
    assert "2 memories stay because --exclude names them; its 2 ids each name a memory in this store." in \
        render_dry_run(plan, CONTEXT)
    plain = make_plan(*plan_args(tmp_path / "plain"))
    assert "--exclude names" not in render_dry_run(plain, CONTEXT) and "excluded" not in plain.counts


def test_the_command_refuses_a_typo_and_writes_no_plan(tmp_path, monkeypatch, capsys):
    home = tmp_path / "h"
    write_context(home, ANDY_CONTEXT)
    scratch = home / "imprints" / "plans" / "scratch-test"
    scratch.mkdir(parents=True, mode=0o700)
    for key in ("SQLITE_TMPDIR", "TMPDIR", "IMPRINT_SCRATCH"):
        monkeypatch.setenv(key, str(scratch))
    store, *_ = plan_args(tmp_path, owner="andy")
    ex = tmp_path / "exclude.txt"
    ex.write_text("e1\ne1-typo\n")
    rc = main(["plan", "--store", str(store), "--engram-home", str(tmp_path / "eh2"), *FLAGS,
               "--audience", "place:home/andy", "--superyak-home", str(home), "--exclude", str(ex)])
    err = capsys.readouterr().err
    assert rc != 0 and "'e1-typo'" in err and "'e1'" not in err
    assert not list((home / "imprints" / "plans").glob("*.json"))


def test_an_id_in_cold_storage_is_accepted_and_still_left_out_if_it_comes_back(tmp_path):
    """A pruned episode moves to cold.db with its id and can be revived into the store. Its id is not a typo, and
    refusing it would make the owner drop the line, so that a revival between plan and build would ship it."""
    from tests.imprint_support import new_store, prune

    def with_cold(tmp_path):
        s = new_store(tmp_path, "src")
        for i in range(3):
            ep(s, f"e{i}", at=f"2026-10-25T10:0{i}:00+00:00")
        ep(s, "pruned", at="2026-10-25T09:00:00+00:00")
        prune(s, "pruned")
        return s
    args = plan_args(tmp_path, store=with_cold)
    with contextlib.closing(sqlite3.connect(f"file:{args[0]}?mode=ro", uri=True)) as conn:
        assert unmatched_exclude(conn, {"pruned"}) == ("pruned",)            # not in the store's own tables
    plan = make_plan(*with_exclude(args, {"e1", "pruned"}))
    assert plan.counts["exclude_ids"] == 2 and plan.counts["exclude_cold"] == 1 and plan.counts["excluded"] == 1
    assert ("1 memory stays because --exclude names it; its 2 ids each name a memory in this store (1 in cold "
            "storage, which never leaves).") in render_dry_run(plan, CONTEXT)
    with pytest.raises(PlanRefused, match="'pruned-typo'"):
        make_plan(*with_exclude(plan_args(tmp_path / "typo", store=with_cold), {"pruned-typo"}))


# The section 2 probe: an owner's --exclude list holds end to end (plan, saved plan, build, package, request,
# manifest).

def ids_in(path):
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    try:
        tables = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")]
        found = set()
        for t in tables:
            try:
                for row in conn.execute(f'SELECT * FROM "{t}"'):
                    found.update(v for v in row if isinstance(v, str))
            except sqlite3.Error:
                pass
        return found
    finally:
        conn.close()


def test_exclude_holds_end_to_end(tmp_path):
    plan = make_plan(*plan_args(tmp_path, episodes=3, exclude={"e1"}))
    saved = json.loads((HOME(tmp_path) / "imprints" / "plans" / f"{plan.id}.json").read_text())
    assert saved["exclude"] == ["e1"]
    built = build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path))
    package = built.dir / "imprint.db"
    values = ids_in(package)
    assert "e1" not in values and "s1" not in values, sorted(v for v in values if len(v) < 6)
    assert {"e0", "e2", "e3"} <= values
    assert b"trip 1" not in package.read_bytes()             # e1's text, in any page or free space
    for name in ("request.json", "manifest.json"):
        text = (built.dir / name).read_text()
        assert '"e1"' not in text and "exclude" not in text, name
    assert built.request["contents"].get("episodes") == 3 and "semantics" not in built.request["contents"]
    objects = (built.dir / "objects.json").read_text()       # the owner's own list names only what ships
    assert "/e1" not in objects and "/s1" not in objects


def test_one_id_reads_in_the_singular(tmp_path):
    plan = make_plan(*plan_args(tmp_path, exclude={"e1"}))
    assert "1 memory stays because --exclude names it; its 1 id names a memory in this store." in \
        render_dry_run(plan, CONTEXT)
