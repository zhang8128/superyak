#!/usr/bin/env python3
"""Tests of the judge, with stand-ins for the room, its jail and the JUnit report.

  python3 -I v2/probes/documents/test_documents_judge.py
"""
import importlib.util
import json
import os
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path

HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("documents_judge", HERE / "documents_judge.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)
Refused = judge.Refused


def junit(cases, collection=()):
    """A JUnit report shaped as pytest writes it: cases are (classname, name, status, message)."""
    parts = ['<?xml version="1.0" encoding="utf-8"?><testsuites><testsuite name="pytest">']
    for name, text in collection:
        parts.append('<testcase classname="" name="%s" time="0.0"><error message="collection failure">%s'
            '</error></testcase>' % (name, text))
    for classname, name, status, message in cases:
        message = message.replace("\n", "&#10;")     # as ElementTree, which pytest writes with, escapes it
        child = {"passed": "", "failed": '<failure message="%s">trace</failure>' % message,
            "error": '<error message="%s">trace</error>' % message,
            "skipped": '<skipped type="pytest.skip" message="%s" />' % message}[status]
        parts.append('<testcase classname="%s" name="%s" time="0.1">%s</testcase>' % (classname, name, child))
    parts.append("</testsuite></testsuites>")
    return "".join(parts).encode("utf-8")


def frozen_ids(*names):
    return ["tests.test_a::%s" % name for name in names]


def score(passed, of, outcome="handed-in", scored=True):
    return {"passed": passed, "of": of, "outcome": outcome, "scored": scored}


def git(repo, *words):
    return subprocess.run(["git", "-C", str(repo), "-c", "user.name=t", "-c", "user.email=t@t.invalid",
        "-c", "commit.gpgsign=false", *words], check=True, capture_output=True).stdout.decode().strip()


class Scoring(unittest.TestCase):
    def test_statuses_and_collection_error_are_read(self):
        report = judge.read_junit(junit([("tests.test_a", "t1", "passed", ""), ("tests.test_a", "t2", "failed", "boom\nmore"),
            ("tests.test_a", "t3", "error", "bad"), ("tests.test_a", "t4", "skipped", "later")],
            [("tests.test_b", "ImportError while importing\nE   ImportError: cannot import name 'x'")]))
        self.assertEqual(report["cases"]["tests.test_a::t1"][0], "passed")
        self.assertEqual(report["cases"]["tests.test_a::t2"], ("failed", "boom"))
        self.assertEqual(report["cases"]["tests.test_a::t3"][0], "error")
        self.assertEqual(report["cases"]["tests.test_a::t4"][0], "skipped")
        self.assertEqual(report["collection_errors"], ["tests.test_b: ImportError: cannot import name 'x'"])

    def test_a_collection_error_line_is_cut(self):
        report = judge.read_junit(junit([], [("tests.test_b", "E   " + "y" * 600)]))
        self.assertEqual(len(report["collection_errors"][0]), len("tests.test_b: ") + 400)

    def test_a_doctype_alone_is_refused(self):
        with self.assertRaises(Refused):
            judge.read_junit(b"<!DOCTYPE testsuite><testsuite/>")

    def test_a_module_skipped_whole_is_not_a_collection_error(self):
        data = b'<testsuite><testcase classname="" name="tests.test_b"><skipped message="no db"/></testcase></testsuite>'
        self.assertEqual(judge.read_junit(data), {"cases": {"::tests.test_b": ("skipped", "no db")}, "collection_errors": []})

    def test_a_collection_error_with_no_E_line_keeps_the_message(self):
        report = judge.read_junit(junit([], [("tests.test_b", "no such line")]))
        self.assertEqual(report["collection_errors"], ["tests.test_b: collection failure"])

    def test_a_case_listed_twice_keeps_its_worst_status(self):
        data = (b'<testsuite><testcase classname="c" name="t"/><testcase classname="c" name="t">'
            b'<error message="teardown"/></testcase><testcase classname="c" name="t"/></testsuite>')
        self.assertEqual(judge.read_junit(data)["cases"]["c::t"], ("error", "teardown"))
        data = b'<testsuite><testcase classname="c" name="t"><skipped/></testcase><testcase classname="c" name="t"/></testsuite>'
        self.assertEqual(judge.read_junit(data)["cases"]["c::t"][0], "skipped")
        data = b'<testsuite><testcase classname="c" name="t"><failure message="f"/></testcase>' \
            b'<testcase classname="c" name="t"><skipped/></testcase></testsuite>'
        self.assertEqual(judge.read_junit(data)["cases"]["c::t"][0], "failed")

    def test_a_failure_with_a_teardown_error_is_an_error(self):
        data = b'<testsuite><testcase classname="c" name="t"><failure message="f"/><error message="e"/></testcase></testsuite>'
        self.assertEqual(judge.read_junit(data)["cases"]["c::t"], ("error", "e"))
        data = b'<testsuite><testcase classname="c" name="t"><skipped message="s"/><failure message="f"/></testcase></testsuite>'
        self.assertEqual(judge.read_junit(data)["cases"]["c::t"], ("failed", "f"))

    def test_an_empty_report_has_no_cases_and_a_doctype_is_refused(self):
        self.assertEqual(judge.read_junit(b"  \n"), {"cases": {}, "collection_errors": []})
        with self.assertRaises(Refused):
            judge.read_junit(b'<!DOCTYPE x [<!ENTITY a "b">]><testsuite/>')
        with self.assertRaises(Refused):
            judge.read_junit(b"<testsuite>")

    def test_a_frozen_case_not_collected_is_not_run(self):
        report = judge.read_junit(junit([("tests.test_a", "t1", "passed", "")],
            [("tests.test_b", "E   ImportError: no name")]))
        counted = judge.score_cases(frozen_ids("t1") + ["tests.test_b::t9"], report)
        self.assertEqual((counted["of"], counted["passed"], counted["not_run"]), (2, 1, 1))
        self.assertEqual(counted["collection_errors"], ["tests.test_b: ImportError: no name"])

    def test_a_candidate_that_adds_cases_does_not_change_of(self):
        report = judge.read_junit(junit([("tests.test_a", name, "passed", "") for name in ("t1", "t2", "t3", "t4", "t5")]))
        counted = judge.score_cases(frozen_ids("t1", "t2"), report)
        self.assertEqual((counted["of"], counted["passed"], counted["unfrozen"]), (2, 2, 3))

    def test_counts_and_first_obstacles(self):
        report = judge.read_junit(junit([("tests.test_a", "t1", "passed", ""), ("tests.test_a", "t2", "failed", "first\nsecond"),
            ("tests.test_a", "t3", "error", "err"), ("tests.test_a", "t4", "skipped", "s")]))
        counted = judge.score_cases(frozen_ids("t1", "t2", "t3", "t4", "t5"), report)
        self.assertEqual({key: counted[key] for key in ("of", "passed", "failed", "error", "skipped", "not_run", "unfrozen")},
            {"of": 5, "passed": 1, "failed": 1, "error": 1, "skipped": 1, "not_run": 1, "unfrozen": 0})
        self.assertEqual(counted["first_obstacles"], ["first", "err"])

    def test_first_obstacles_stop_at_twenty_and_lines_are_cut(self):
        names = ["t%02d" % k for k in range(25)]
        report = judge.read_junit(junit([("tests.test_a", name, "failed", "x" * 500) for name in names]))
        counted = judge.score_cases(frozen_ids(*names), report)
        self.assertEqual(len(counted["first_obstacles"]), 20)
        self.assertEqual(len(counted["first_obstacles"][0]), 400)
        self.assertEqual(counted["failed"], 25)

    def test_a_failure_with_no_message_gives_its_text(self):
        data = b'<testsuite><testcase classname="c" name="t"><failure>\n  text line\nmore</failure></testcase></testsuite>'
        self.assertEqual(judge.score_cases(["c::t"], judge.read_junit(data))["first_obstacles"], ["text line"])


class RoomAnswers(unittest.TestCase):
    def test_handed_in_reads_one_attempt_and_a_bool_verdict(self):
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "turns.json"
            self.assertEqual(judge.handed_in(temporary), (None, None))
            path.write_text(json.dumps([{"commit": "c", "passed": True}]))
            self.assertEqual(judge.handed_in(temporary), ("c", True))
            path.write_text(json.dumps([{"commit": "c", "passed": "yes"}]))
            self.assertEqual(judge.handed_in(temporary), ("c", None))
            path.write_text(json.dumps([{"commit": "c", "passed": True}, {"commit": "d", "passed": True}]))
            self.assertEqual(judge.handed_in(temporary), (None, None))

    def test_a_changed_item_list_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            (Path(temporary) / "list").mkdir()
            raw = json.dumps({"commits": []}).encode()
            (Path(temporary) / "list" / "items.json").write_bytes(raw)
            self.assertEqual(judge.check_items({"list_sha256": judge.pilot.digest(raw)}, temporary), {"commits": []})
            with self.assertRaises(Refused):
                judge.check_items({"list_sha256": "0" * 64}, temporary)


class Arithmetic(unittest.TestCase):
    def test_classes_by_hand(self):
        self.assertEqual(judge.classify(Fraction(1, 4), Fraction(1, 4)), "within")     # d == r
        self.assertEqual(judge.classify(Fraction(-1, 4), Fraction(1, 4)), "within")    # d == -r
        self.assertEqual(judge.classify(Fraction(26, 100), Fraction(1, 4)), "higher")
        self.assertEqual(judge.classify(Fraction(-26, 100), Fraction(1, 4)), "lower")
        self.assertEqual(judge.classify(Fraction(0), Fraction(0)), "within")

    def test_b_r_d_worked_by_hand(self):
        # n1 = 4/8 = 0.5, n2 = 2/8 = 0.25: b = 0.375, r = 0.25.
        scores = {"nothing-1": score(4, 8), "nothing-2": score(2, 8), "exists": score(5, 8), "path": score(8, 8),
            "search": score(1, 8), "newest": score(0, 8), "lot": score(3, 8)}
        reading = judge.item_reading(scores)
        self.assertEqual((reading["b"], reading["r"]), (Fraction(3, 8), Fraction(1, 4)))
        got = {row: (held["d"], held["class"]) for row, held in reading["conditions"].items()}
        self.assertEqual(got, {"exists": (Fraction(1, 4), "within"),      # d == r exactly
            "path": (Fraction(5, 8), "higher"), "search": (Fraction(-1, 4), "within"),
            "newest": (Fraction(-3, 8), "lower"), "lot": (Fraction(0), "within")})

    def test_r_is_the_absolute_gap(self):
        reading = judge.item_reading({"nothing-1": score(1, 4), "nothing-2": score(3, 4), "lot": score(4, 4)})
        # b = 1/2, r = 1/2, d = 1/2 == r: within (a signed r of -1/2 would make it higher).
        self.assertEqual((reading["r"], reading["conditions"]["lot"]["class"]), (Fraction(1, 2), "within"))

    def test_a_score_of_nothing_is_not_usable(self):
        self.assertFalse(judge.usable(score(0, 0)))
        self.assertFalse(judge.usable(None))
        self.assertTrue(judge.usable(score(0, 1)))

    def test_thirds_compare_exactly(self):
        # n1 = 1/3, n2 = 0: b = 1/6, r = 1/3; o = 1/2 gives d = 1/3 == r: within, not higher by rounding.
        scores = {"nothing-1": score(1, 3), "nothing-2": score(0, 3), "exists": score(3, 6)}
        self.assertEqual(judge.item_reading(scores)["conditions"]["exists"]["class"], "within")

    def test_no_baseline_when_a_nothing_row_has_no_score(self):
        self.assertIsNone(judge.item_reading({"nothing-1": score(1, 2), "path": score(2, 2)}))
        self.assertIsNone(judge.item_reading({"nothing-1": score(1, 2), "nothing-2": score(1, 2, "not-applied", False),
            "path": score(2, 2)}))
        reading = judge.item_reading({"nothing-1": score(1, 2), "nothing-2": score(1, 2),
            "path": score(1, 2, "diagnostic-limit", False)})
        self.assertEqual(reading["conditions"], {})

    def test_by_plan_of_one_and_of_four(self):
        plan = {"items": [{"item": "a", "plan_group": "p1"}] + [{"item": "b%d" % k, "plan_group": "p4"} for k in range(4)]}
        def reading(d, r):
            return {"r": Fraction(r), "conditions": {"search": {"d": Fraction(d)}}}
        readings = {"a": reading("1/2", "1/4"), "b0": reading("1/2", "0"), "b1": reading("-1/4", "1/2"),
            "b2": reading("1/4", "1/4"), "b3": reading("-1/4", "1/4")}
        table, figures = judge.by_plan(plan, readings)
        self.assertEqual(table["p1"]["conditions"]["search"]["class"], "higher")
        self.assertEqual(table["p1"]["conditions"]["search"]["D"], Fraction(1, 2))
        # p4: D = (1/2 - 1/4 + 1/4 - 1/4) / 4 = 1/16, R = (0 + 1/2 + 1/4 + 1/4) / 4 = 1/4: within.
        self.assertEqual((table["p4"]["conditions"]["search"]["D"], table["p4"]["conditions"]["search"]["R"]),
            (Fraction(1, 16), Fraction(1, 4)))
        self.assertEqual(table["p4"]["conditions"]["search"]["class"], "within")
        self.assertEqual(table["p4"]["conditions"]["search"]["on"], 4)
        self.assertEqual(table["p4"]["items"], ["b0", "b1", "b2", "b3"])
        self.assertEqual(figures["search"], Fraction(9, 32))      # (1/2 + 1/16) / 2 plans
        self.assertIsNone(figures["path"])                        # read at no plan

    def test_a_plan_with_D_equal_to_minus_R_is_within_and_below_is_lower(self):
        plan = {"items": [{"item": "a", "plan_group": "p"}]}
        def table(d, r):
            return judge.by_plan(plan, {"a": {"r": Fraction(r), "conditions": {"lot": {"d": Fraction(d)}}}})[0]
        self.assertEqual(table("-1/4", "1/4")["p"]["conditions"]["lot"]["class"], "within")
        self.assertEqual(table("-1/2", "1/4")["p"]["conditions"]["lot"]["class"], "lower")

    def test_the_equally_weighted_figure_waits_for_every_plan(self):
        plan = {"items": [{"item": "a", "plan_group": "p"}, {"item": "b", "plan_group": "q"}]}
        readings = {"a": {"r": Fraction(0), "conditions": {"lot": {"d": Fraction(1, 2)}}}, "b": None}
        self.assertIsNone(judge.by_plan(plan, readings)[1]["lot"])


def rule_inputs(higher_search=0, lower_search=0, plans_search=0, higher_newest=0, lower_lot=0):
    items = {row: {"higher": 0, "lower": 0, "within": 0, "on": 12} for row in judge.OFFERING}
    items["search"].update(higher=higher_search, lower=lower_search)
    items["newest"].update(higher=higher_newest)
    items["lot"].update(lower=lower_lot)
    plans = {row: {"higher": 0, "on": 6} for row in judge.OFFERING}
    plans["search"]["higher"] = plans_search
    plan = {"items": [{"item": "i%d" % k} for k in range(12)]}
    scores = {"i%d" % k: {row: score(1, 2) for row in judge.ROWS} for k in range(12)}
    return plan, scores, items, plans


class Rule(unittest.TestCase):
    def decide(self, **kwargs):
        plan, scores, items, plans = rule_inputs(**kwargs)
        return judge.spending_rule(plan, scores, items, plans)["decision"]

    def test_worth_at_the_edges(self):
        self.assertEqual(self.decide(higher_search=8, lower_search=2, plans_search=4, lower_lot=3),
            "worth designing an experiment")
        self.assertEqual(self.decide(higher_search=7, lower_search=2, plans_search=4, lower_lot=3), "between")
        self.assertEqual(self.decide(higher_search=8, lower_search=3, plans_search=4, lower_lot=3), "between")
        self.assertEqual(self.decide(higher_search=8, lower_search=2, plans_search=3, lower_lot=3), "between")
        self.assertEqual(self.decide(higher_search=8, lower_search=2, plans_search=4, lower_lot=4), "between")

    def test_newest_alone_can_be_worth(self):
        plan, scores, items, plans = rule_inputs(higher_newest=9)
        plans["newest"]["higher"] = 5
        self.assertEqual(judge.spending_rule(plan, scores, items, plans)["decision"], "worth designing an experiment")

    def test_not_worth_and_between(self):
        self.assertEqual(self.decide(higher_search=5, higher_newest=5), "not worth one")
        self.assertEqual(self.decide(higher_search=6), "between")
        self.assertEqual(self.decide(higher_newest=6), "between")

    def test_suspended_when_a_nothing_row_has_no_score(self):
        plan, scores, items, plans = rule_inputs(higher_search=12, plans_search=6)
        scores["i3"]["nothing-2"] = score(0, 2, "diagnostic-limit", False)
        del scores["i5"]["lot"]
        decided = judge.spending_rule(plan, scores, items, plans)
        self.assertEqual(decided, {"decision": "suspended", "missing": ["i3 nothing-2", "i5 lot"]})

    def test_rows_the_rule_does_not_need_do_not_suspend_it(self):
        plan, scores, items, plans = rule_inputs(higher_search=5)
        scores["i0"]["path"] = score(0, 2, "not-applied", False)
        del scores["i1"]["exists"]
        self.assertEqual(judge.spending_rule(plan, scores, items, plans)["decision"], "not worth one")


class Walks(unittest.TestCase):
    def test_matching_and_offered_named(self):
        item = {"matching": ["docs/plans/p.md", "docs/specs/s.md"], "direct_path": "docs/plans/p.md",
            "search": {"three": ["a.md", "docs/plans/p.md", "b.md"]}}
        walk = {"steps": [{"seq": 0, "seen_ms": 4000, "named": [["src/x.py", "read"]]},
            {"seq": 2, "seen_ms": 9500, "named": [["b.md", "read"], ["docs/plans/p.md", "read"]]},
            {"seq": 1, "seen_ms": 7000, "named": [["docs/plans/p.md", "read"]]},
            {"seq": 3, "named": [["docs/specs/s.md", "read"]]}]}
        with tempfile.TemporaryDirectory() as temporary:
            path = Path(temporary) / "walks.jsonl"
            path.write_text(json.dumps(walk) + "\n")
            matching, offered = judge.read_walk(path, item, "search")
            self.assertEqual(matching, {"docs/plans/p.md": {"step": 1, "seconds": 7.0},
                "docs/specs/s.md": {"step": 3, "seconds": None}})
            self.assertEqual(offered, ["docs/plans/p.md", "b.md"])
            self.assertEqual(judge.read_walk(path, item, "path")[1], ["docs/plans/p.md"])
            self.assertEqual(judge.read_walk(path, item, "exists")[1], [])
            self.assertEqual(judge.read_walk(path, dict(item, newest={"three": ["b.md"]}), "newest")[1], ["b.md"])
            self.assertEqual(judge.read_walk(path, dict(item, lot={"three": ["x.md", "b.md"]}), "lot")[1], ["b.md"])
            self.assertEqual(judge.read_walk(path, item, "nothing-1")[1], [])
            self.assertEqual(judge.read_walk(Path(temporary) / "none.jsonl", item, "search"), ({}, []))
            path.write_text(json.dumps(walk) + "\n" + json.dumps(walk) + "\n")
            with self.assertRaises(Refused):
                judge.read_walk(path, item, "search")

    def test_an_earlier_step_by_seq_wins_a_tie_in_time(self):
        steps = [{"seq": 5, "seen_ms": 1000, "named": [["p", ""]]}, {"seq": 4, "seen_ms": 1000, "named": [["p", ""]]}]
        self.assertEqual(judge.first_named(steps, "p"), {"step": 4, "seconds": 1.0})


ITEM = "a1b2c3d4e5"


class Plan:
    """A plan's directory with one or more items: plan.json, controls, a row repository with a base and turns."""

    def __init__(self, root, items=1, group=lambda k: "p%d" % k):
        self.out = Path(root) / "out"
        (self.out / "rows").mkdir(parents=True)
        self.repo = Path(root) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "peer" / "superyak_peer").mkdir(parents=True)
        (self.repo / "peer" / "superyak_peer" / "a.py").write_text("x = 1\n")
        (self.repo / "TASK.md").write_text("task\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        plan_items, order = [], []
        for k in range(items):
            short = ("%x" % k) * 10 if k else ITEM
            commit = (short + "0" * 30)
            plan_items.append({"commit": commit, "item": short, "parent": "f" * 40, "probed_before": k == 1,
                "plan_group": group(k), "tests": [], "kept_out": {"reference": "", "test_blobs": []},
                "direct_path": "docs/plans/p.md", "matching": ["docs/plans/p.md"], "facts_sha256": "", "task_sha256": "",
                "query_sha256": "", "search": {"three": ["a.md", "b.md", "docs/plans/p.md"], "best_place": 3, "tied": 0},
                "newest": {"three": ["docs/plans/p.md", "c.md", "d.md"], "best_place": 1}, "lot": {"three": ["e.md", "f.md", "g.md"]},
                "documents": {}, "rows": {row: {"paragraph": "", "base": self.base, "wrong": "0" * 40, "task_file_sha256": ""}
                    for row in judge.ROWS}})
            for row in judge.ROWS:
                order.append({"n": 0, "commit": commit, "item": short, "row": row, "hash": "", "directory": ""})
        order.sort(key=lambda held: (held["item"], judge.ROWS.index(held["row"])))
        for n, held in enumerate(order, 1):
            held.update(n=n, directory="%03d-%s-%s" % (n, held["item"], held["row"]))
        self.plan = {"v": 1, "seed": 20261118, "spec_sha256": "", "list_sha256": "", "worker": {},
            "limits": {"worker_secs": 1, "check_secs": 1, "replay_secs": 1, "diagnostic_secs": 7}, "inputs": {},
            "items": plan_items, "order": order}
        raw = (json.dumps(self.plan, sort_keys=True, indent=1) + "\n").encode()
        (self.out / "plan.json").write_bytes(raw)
        (self.out / "plan.sha256").write_text(judge.pilot.digest(raw) + "\n")
        for item in plan_items:
            controls = self.out / "controls" / item["item"]
            (controls / "parent").mkdir(parents=True)
            (controls / "cases.json").write_text(json.dumps({"commit": item["commit"], "cases": frozen_ids("t1", "t2", "t3", "t4"),
                "counts": {"passed": 4, "failed": 0, "error": 0, "skipped": 0}}))
            (controls / "parent" / "junit.json").write_text(json.dumps({"cases": {"tests.test_a::t1": ["passed", ""],
                "tests.test_a::t2": ["failed", "nope"], "tests.test_a::t9": ["passed", ""]},
                "collection_errors": ["tests.test_c: ImportError: x"]}))
            (controls / "parent.json").write_text(json.dumps({"commit": item["commit"], "passed": frozen_ids("t1")}))

    def order(self, row, item=ITEM):
        return [held for held in self.plan["order"] if held["row"] == row and held["item"] == item][0]

    def turn(self, change):
        git(self.repo, "checkout", "-q", "--detach", self.base)
        if change:
            (self.repo / "peer" / "superyak_peer" / "a.py").write_text("x = 2\n")
        else:
            (self.repo / "notes.txt").write_text("outside the source\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "turn")
        return git(self.repo, "rev-parse", "HEAD")

    def record(self, row, outcome, turn_commit=None, item=ITEM, at_limit=None):
        order = self.order(row, item)
        directory = self.out / "rows" / order["directory"]
        directory.mkdir()
        os.symlink(self.repo, directory / "repo")
        (directory / "record.json").write_text(json.dumps({"n": order["n"], "commit": order["commit"], "row": row,
            "began": "", "ended": "", "load_before": "", "load_after": "", "clock_exit": 0, "outcome": outcome,
            "turn_commit": turn_commit, **({} if at_limit is None else {"at_limit": at_limit})}))
        return order


def stand_in_diagnostic(applied=True, limit=False, cases=()):
    seen = []

    def run(directory, items, commit, patch, limit_secs):
        seen.append((directory, commit, patch, limit_secs))
        return {"applied": applied, "limit": limit, "report": judge.read_junit(junit(cases))}
    return run, seen


def stand_in_replay(verdict):
    seen = []

    def run(directory, items, commit, patch):
        seen.append(patch)
        return verdict
    return run, seen


class JudgeRow(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.plan = Plan(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def judged(self, order, diagnostic=None, replay=None):
        return judge.judge_row(self.plan.out, "items", self.plan.plan, order, diagnostic, replay)

    def test_a_source_change_is_replayed_and_scored_over_the_frozen_cases(self):
        commit = self.plan.turn(change=True)
        order = self.plan.record("path", "handed-in", commit)
        diagnostic, seen = stand_in_diagnostic(cases=[("tests.test_a", "t1", "passed", ""),
            ("tests.test_a", "t2", "failed", "AssertionError: 1 != 2"), ("tests.test_a", "t3", "passed", ""),
            ("tests.test_a", "t7", "passed", "")])
        replay, replayed = stand_in_replay(False)
        got = self.judged(order, diagnostic, replay)
        self.assertEqual((got["scored"], got["outcome"], got["of"], got["passed"], got["failed"], got["not_run"],
            got["unfrozen"], got["room_passed"]), (True, "handed-in", 4, 2, 1, 1, 1, False))
        self.assertEqual(got["first_obstacles"], ["AssertionError: 1 != 2"])
        self.assertIn(b"peer/superyak_peer/a.py", seen[0][2])
        self.assertEqual(seen[0][3], 7)
        self.assertEqual(replayed, [seen[0][2]])
        self.assertEqual(set(got) - {"n", "commit", "row"}, {"outcome", "scored", "of", "passed", "failed", "error",
            "skipped", "not_run", "unfrozen", "collection_errors", "first_obstacles", "room_passed", "matching_named",
            "offered_named"})

    def test_no_hand_in_is_scored_as_the_parent(self):
        got = self.judged(self.plan.record("nothing-1", "no-hand-in"))
        self.assertEqual((got["scored"], got["outcome"], got["of"], got["passed"], got["failed"], got["not_run"],
            got["unfrozen"], got["room_passed"]), (True, "no-hand-in", 4, 1, 1, 2, 1, None))
        self.assertEqual(got["collection_errors"], ["tests.test_c: ImportError: x"])
        self.assertEqual(got["first_obstacles"], ["nope"])

    def test_limit_with_no_commit_is_scored_as_the_parent(self):
        got = self.judged(self.plan.record("exists", "limit"))
        self.assertEqual((got["scored"], got["outcome"], got["passed"]), (True, "limit", 1))

    def test_a_hand_in_that_changes_nothing_under_the_source_is_scored_as_the_parent(self):
        diagnostic, seen = stand_in_diagnostic()
        got = self.judged(self.plan.record("search", "handed-in", self.plan.turn(change=False)), diagnostic)
        self.assertEqual((got["scored"], got["outcome"], got["passed"]), (True, "unchanged-source", 1))
        self.assertEqual(seen, [])

    def test_a_change_that_does_not_apply_has_no_score(self):
        diagnostic, _ = stand_in_diagnostic(applied=False)
        replay, replayed = stand_in_replay(True)
        got = self.judged(self.plan.record("lot", "handed-in", self.plan.turn(change=True)), diagnostic, replay)
        self.assertEqual((got["scored"], got["outcome"], got["of"]), (False, "not-applied", 4))
        self.assertEqual(replayed, [])

    def test_a_diagnostic_at_its_limit_has_no_score_and_keeps_its_counts(self):
        diagnostic, _ = stand_in_diagnostic(limit=True, cases=[("tests.test_a", "t1", "passed", "")])
        got = self.judged(self.plan.record("newest", "handed-in", self.plan.turn(change=True)), diagnostic)
        self.assertEqual((got["scored"], got["outcome"], got["passed"]), (False, "diagnostic-limit", 1))

    def test_a_failed_clock_has_no_score(self):
        got = self.judged(self.plan.record("nothing-2", "clock-failed"))
        self.assertEqual((got["scored"], got["outcome"]), (False, "clock-failed"))

    def test_inconsistent_records_are_refused(self):
        with self.assertRaises(Refused):
            self.judged(self.plan.record("nothing-1", "handed-in", None))
        with self.assertRaises(Refused):
            self.judged(self.plan.record("nothing-2", "no-hand-in", self.plan.base))
        with self.assertRaises(Refused):
            self.judged(self.plan.record("exists", "finished"))
        order = self.plan.record("path", "no-hand-in")
        record = self.plan.out / "rows" / order["directory"] / "record.json"
        held = json.loads(record.read_text())
        held["row"] = "lot"
        record.write_text(json.dumps(held))
        with self.assertRaises(Refused):
            self.judged(order)

    def test_judge_writes_each_recorded_row_once_and_skips_the_unrecorded(self):
        self.plan.record("nothing-1", "no-hand-in")
        self.plan.record("nothing-2", "limit")
        original = judge.check_items
        judge.check_items = lambda plan, items: None
        try:
            self.assertEqual(judge.judge(self.plan.out, "items", rows=1), 0)
            self.assertEqual(sorted(os.listdir(self.plan.out / "judged")), [self.plan.order("nothing-1")["directory"]])
            interrupted = self.plan.out / "judged" / self.plan.order("nothing-2")["directory"]
            interrupted.mkdir()
            (interrupted / "partial").write_text("")
            judge.judge(self.plan.out, "items")
            self.assertTrue((interrupted / "score.json").exists())
            self.assertFalse((interrupted / "partial").exists())
            self.assertEqual(os.listdir(self.plan.out / "judged" / "interrupted"), [interrupted.name + "-1"])
            first = (self.plan.out / "judged" / self.plan.order("nothing-1")["directory"] / "score.json").read_bytes()
            judge.judge(self.plan.out, "items")
            self.assertEqual(sorted(os.listdir(self.plan.out / "judged")), sorted(
                [self.plan.order(row)["directory"] for row in NOTHING] + ["interrupted"]))
            self.assertEqual((self.plan.out / "judged" / self.plan.order("nothing-1")["directory"] / "score.json")
                .read_bytes(), first)
        finally:
            judge.check_items = original

    def test_an_empty_plan_hash_is_refused(self):
        (self.plan.out / "plan.sha256").write_text("")
        with self.assertRaises(Refused):
            judge.load_plan(self.plan.out)

    def test_the_items_dir_comes_from_the_plan_when_not_given(self):
        self.assertEqual(judge.items_dir({"items_dir": "a"}, None), "a")
        self.assertEqual(judge.items_dir({"items_dir": "a"}, "b"), "b")
        with self.assertRaises(Refused):
            judge.items_dir({}, None)

    def test_move_aside_numbers_each_move(self):
        for _ in range(2):
            (self.plan.out / "judged" / "x").mkdir(parents=True)
            judge.move_aside(self.plan.out / "judged" / "x")
        self.assertEqual(sorted(os.listdir(self.plan.out / "judged" / "interrupted")), ["x-1", "x-2"])

    def test_a_changed_plan_is_refused(self):
        with (self.plan.out / "plan.json").open("a") as held:
            held.write(" ")
        with self.assertRaises(Refused):
            judge.load_plan(self.plan.out)


NOTHING = judge.NOTHING


class Report(unittest.TestCase):
    def test_the_reports_counts_equal_the_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary, items=2)
            plan.record("nothing-1", "no-hand-in")
            plan.record("nothing-2", "no-hand-in")
            plan.record("path", "clock-failed", at_limit=False)
            plan.record("lot", "handed-in", plan.turn(change=False), at_limit=True)
            plan.record("nothing-1", "limit", item="1111111111")
            (plan.out / "rows" / "interrupted" / "x-1").mkdir(parents=True)
            (plan.out / "rows" / "interrupted" / "x-2").mkdir()
            original = judge.check_items
            judge.check_items = lambda held, items: None
            try:
                judge.judge(plan.out, "items")
            finally:
                judge.check_items = original
            plan.record("exists", "no-hand-in")
            report = judge.make_report(plan.out)
            self.assertEqual(report["rows"]["unjudged"], [plan.order("exists")["directory"]])
            (plan.out / "rows" / plan.order("exists")["directory"] / "record.json").unlink()
            report = judge.make_report(plan.out)
            self.assertEqual(report["rows"]["planned"], 14)
            self.assertEqual(report["rows"]["recorded"], 5)
            self.assertEqual(report["rows"]["judged"], 5)
            self.assertEqual(report["rows"]["outcomes"], {"no-hand-in": 2, "clock-failed": 1, "limit": 1, "handed-in": 1})
            self.assertEqual(report["rows"]["judged_outcomes"], {"no-hand-in": 2, "clock-failed": 1, "limit": 1,
                "unchanged-source": 1})
            self.assertEqual(report["rows"]["at_limit"], dict({row: 0 for row in judge.ROWS}, lot=1))
            self.assertEqual(report["rows"]["interrupted"], 2)
            self.assertEqual(report["items"][ITEM]["b"], 0.25)
            self.assertIsNone(report["items"]["1111111111"])
            self.assertEqual(report["probed"], ["1111111111"])
            self.assertEqual(report["rule"]["decision"], "suspended")
            self.assertIn(ITEM + " search", report["rule"]["missing"])
            self.assertEqual(report["parent"][ITEM], {"passed": 1, "of": 4})
            self.assertEqual(report["places"][ITEM], {"search": 3, "search_tied": 0, "newest": 1})
            judge.write_report(plan.out)
            text = (plan.out / "report.md").read_text()
            self.assertIn("Suspended", text)
            self.assertIn("2 interrupted", text)
            self.assertIn("| 1111111111 | p1 | 1 of 4 | no baseline |" + " |" * 8 + "\n", text)
            for line in text.splitlines():
                if (line.startswith("| a1b2") or line.startswith("| 1111")) and " of 4 |" in line:
                    self.assertEqual(line.count("|"), 13, line)
            self.assertEqual(json.loads((plan.out / "report.json").read_text())["rows"]["recorded"], 5)
            self.assertIn("by condition: nothing-1 0, nothing-2 0, exists 0, path 0, search 0, newest 0, lot 1.", text)

    def test_without_the_probed_item(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary, items=2)
            readings = {ITEM: {"r": Fraction(0), "conditions": {"path": {"class": "higher"}}},
                "1111111111": {"r": Fraction(0), "conditions": {"path": {"class": "higher"}}}}
            self.assertEqual(judge.tally(readings, "path")["higher"], 2)
            self.assertEqual(judge.tally(readings, "path", lambda item: item != "1111111111")["higher"], 1)
            self.assertEqual(judge.tally(readings, "path", lambda item: item != "1111111111")["on"], 1)
            self.assertTrue(plan.plan["items"][1]["probed_before"])

    def test_a_score_for_another_row_is_refused(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary)
            order = plan.order("path")
            (plan.out / "judged" / order["directory"]).mkdir(parents=True)
            (plan.out / "judged" / order["directory"] / "score.json").write_text(json.dumps({"n": order["n"] + 1,
                "commit": order["commit"], "row": "path"}))
            with self.assertRaises(Refused):
                judge.make_report(plan.out)


class StandInJail:
    """In the room's place: a turn directory with a repository whose one commit holds what the script worker would
    hand in, and turns.json as `item turns --json` prints it (a guess at the real room's shape: a list of one
    attempt with "commit" and "passed")."""

    def __init__(self, reference_cases, parent_cases, verdict=True, applied=True, limit=False):
        self.reference_cases, self.parent_cases = reference_cases, parent_cases
        self.verdict, self.applied, self.limit = verdict, applied, limit
        self.calls = []

    def __call__(self, directory, items, commit, worker_dir):
        directory, worker_dir = Path(directory), Path(worker_dir)
        self.calls.append((directory, commit))
        repo = directory / "repo"
        repo.mkdir(parents=True)
        git(repo, "init", "-q")
        diagnostic = (worker_dir / "explain.py").exists()
        if diagnostic:
            patch = (worker_dir / "change.patch").read_bytes()
            self.patch_seen = self.patch_seen if hasattr(self, "patch_seen") else []
            self.patch_seen.append(patch)
            (repo / "jail-junit.xml").write_bytes(junit(self.reference_cases if patch else self.parent_cases))
            (repo / "jail-status.json").write_text(json.dumps({"apply_exit": 0 if self.applied else 1,
                "limit": self.limit if patch else getattr(self, "parent_limit", False), "tests_exit": 1}))
        else:
            (repo / "hand-in.txt").write_text("replayed\n")
        git(repo, "add", "-A")
        git(repo, "commit", "-q", "-m", "hand-in")
        (directory / "turns.json").write_text(json.dumps([{"commit": git(repo, "rev-parse", "HEAD"),
            "passed": self.verdict if not diagnostic else False}]))


class Controls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.plan = Plan(self.temporary.name)
        for item in self.plan.plan["items"]:
            controls = self.plan.out / "controls" / item["item"]
            for name in ("cases.json", "parent.json", "parent/junit.json"):
                (controls / name).unlink()
        git(self.plan.repo, "checkout", "-q", "--detach", self.plan.base)
        (self.plan.repo / "peer" / "superyak_peer" / "b.py").write_text("y = 1\n")
        git(self.plan.repo, "add", "-A")
        git(self.plan.repo, "commit", "-q", "-m", "reference")
        reference = git(self.plan.repo, "rev-parse", "HEAD")
        self.items = Path(self.temporary.name) / "items"
        self.items.mkdir()
        os.symlink(self.plan.repo, self.items / "repo")
        entry = {"commit": self.plan.plan["items"][0]["commit"], "base": self.plan.base, "wrong": self.plan.base,
            "reference": reference, "title": "t", "part": "pilot", "check": {"command": "c", "files": ["f"]}}
        self.originals = (judge.check_items, judge.jail_turn)
        judge.check_items = lambda plan, items: {"commits": [entry]}

    def tearDown(self):
        judge.check_items, judge.jail_turn = self.originals
        self.temporary.cleanup()

    def run_controls(self, jail):
        judge.jail_turn = jail
        return judge.controls(self.plan.out, self.items)

    def test_cases_and_parent_are_frozen_from_the_jail(self):
        jail = StandInJail([("tests.test_a", "t1", "passed", ""), ("tests.test_a", "t2", "passed", ""),
            ("tests.test_a", "t3", "failed", "x"), ("tests.test_a", "t4", "skipped", "s"), ("tests.test_a", "t5", "error", "e")],
            [("tests.test_a", "t1", "passed", ""),
            ("tests.test_a", "t2", "failed", "y"), ("tests.test_a", "t8", "passed", "")])
        self.run_controls(jail)
        controls = self.plan.out / "controls" / ITEM
        cases = json.loads((controls / "cases.json").read_text())
        self.assertEqual(cases["cases"], ["tests.test_a::t1", "tests.test_a::t2"])
        self.assertEqual(cases["counts"], {"passed": 2, "failed": 1, "error": 1, "skipped": 1})
        self.assertEqual(json.loads((controls / "parent.json").read_text())["passed"], ["tests.test_a::t1"])
        self.assertIn(b"peer/superyak_peer/b.py", jail.patch_seen[0])
        self.assertEqual(jail.patch_seen[1], b"")
        self.assertEqual(len(jail.calls), 3)
        self.assertEqual(judge.parent_score(controls, cases["cases"])["passed"], 1)
        self.run_controls(jail)                                   # a made control is not made again
        self.assertEqual(len(jail.calls), 3)

    def stopped(self, jail):
        self.run_controls(jail)
        controls = self.plan.out / "controls" / ITEM
        self.assertFalse((controls / "parent.json").exists())
        return json.loads((controls / "stopped.json").read_text())["reason"]

    def test_a_reference_with_no_passing_case_stops_the_item(self):
        reason = self.stopped(StandInJail([("tests.test_a", "t1", "failed", "x")], []))
        self.assertIn("no case passes", reason)

    def test_a_reference_the_room_does_not_pass_stops_the_item(self):
        reason = self.stopped(StandInJail([("tests.test_a", "t1", "passed", "")], [], verdict=False))
        self.assertIn("by replay is false", reason)

    def test_a_reference_with_no_verdict_stops_the_item(self):
        self.assertIn("by replay is null", self.stopped(StandInJail([("tests.test_a", "t1", "passed", "")], [], verdict=None)))

    def test_a_parent_run_at_its_limit_stops_the_item(self):
        jail = StandInJail([("tests.test_a", "t1", "passed", "")], [])
        jail.parent_limit = True
        self.assertIn("parent's run reached its limit", self.stopped(jail))
        calls = len(jail.calls)
        self.run_controls(jail)
        self.assertEqual(len(jail.calls), calls)

    def test_a_reference_that_does_not_apply_or_reaches_its_limit_stops_the_item(self):
        self.assertIn("did not apply", self.stopped(StandInJail([("tests.test_a", "t1", "passed", "")], [], applied=False)))

    def test_a_reference_at_its_limit_stops_the_item(self):
        self.assertIn("reached its limit", self.stopped(StandInJail([("tests.test_a", "t1", "passed", "")], [], limit=True)))

    def test_a_stopped_item_is_not_judged_and_is_reported(self):
        self.stopped(StandInJail([("tests.test_a", "t1", "failed", "x")], []))
        self.plan.record("nothing-2", "no-hand-in")
        judge.judge(self.plan.out, self.items)
        self.assertFalse((self.plan.out / "judged" / self.plan.order("nothing-2")["directory"]).exists())
        self.assertIn("no case passes", judge.make_report(self.plan.out)["controls_stopped"][ITEM])

    def test_an_item_stopped_by_its_replay_is_not_judged(self):
        self.stopped(StandInJail([("tests.test_a", "t1", "passed", "")], [], verdict=False))
        self.assertTrue((self.plan.out / "controls" / ITEM / "cases.json").exists())
        self.plan.record("nothing-1", "no-hand-in")
        judge.judge(self.plan.out, self.items)
        self.assertFalse((self.plan.out / "judged" / self.plan.order("nothing-1")["directory"]).exists())
        self.assertIn("by replay is false", judge.make_report(self.plan.out)["controls_stopped"][ITEM])


FAKE_PYTEST = """import json, os, sys, time
args = sys.argv[1:]
report = [a for a in args if a.startswith("--junitxml=")][0].split("=", 1)[1]
if os.environ.get("HOME") and os.path.exists(os.path.join(os.getcwd(), "slow")):
    time.sleep(30)
passed = "y = 1" in open(os.path.join(os.getcwd(), "pkg.py")).read()
with open(report, "w") as out:
    out.write('<testsuites><testsuite><testcase classname="tests.test_p" name="t1"/>'
        '<testcase classname="tests.test_p" name="t2">%s</testcase></testsuite></testsuites>'
        % ("" if passed else '<failure message="AssertionError: y"/>'))
"""


class InJailScript(unittest.TestCase):
    """The script worker and its explain.py, run by a stand-in for the room's turn in a fresh repository with a
    fake pytest (this machine has none; the jail's interpreter is guessed to have it, as the earlier probes' had)."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.base = Path(self.temporary.name) / "base"
        self.base.mkdir()
        git(self.base, "init", "-q")
        component = self.base / "peer" / "superyak_peer"
        (component / "pytest").mkdir(parents=True)
        (component / "pytest" / "__main__.py").write_text(FAKE_PYTEST)
        (component / "pkg.py").write_text("x = 1\n")
        (self.base / ".yak-check").mkdir()
        (self.base / ".yak-check" / "item.json").write_text(json.dumps({"component": "peer/superyak_peer",
            "tests": [{"path": "peer/superyak_peer/tests/test_p.py"}]}))
        git(self.base, "add", "-A")
        git(self.base, "commit", "-q", "-m", "base")
        (component / "pkg.py").write_text("x = 1\ny = 1\n")
        self.patch = subprocess.run(["git", "-C", str(self.base), "diff", "--binary"], capture_output=True).stdout
        git(self.base, "checkout", "-q", "--", ".")
        self.original = judge.jail_turn
        judge.jail_turn = self.turn

    def tearDown(self):
        judge.jail_turn = self.original
        self.temporary.cleanup()

    def turn(self, directory, items, commit, worker_dir):
        directory = Path(directory)
        directory.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", str(self.base), str(directory / "repo")], check=True)
        subprocess.run(["sh", str(Path(worker_dir) / "worker.sh")], cwd=directory / "repo", capture_output=True)
        head = git(directory / "repo", "rev-parse", "HEAD")
        (directory / "turns.json").write_text(json.dumps([{"commit": head, "passed": None}]))

    def test_a_change_is_applied_and_its_tests_read_back(self):
        ran = judge.diagnostic(Path(self.temporary.name) / "d1", "items", "c" * 40, self.patch, 20)
        self.assertEqual((ran["applied"], ran["limit"]), (True, False))
        self.assertEqual(ran["report"]["cases"], {"tests.test_p::t1": ("passed", ""), "tests.test_p::t2": ("passed", "")})

    def test_no_change_runs_the_tests_on_the_base(self):
        ran = judge.diagnostic(Path(self.temporary.name) / "d2", "items", "c" * 40, b"", 20)
        self.assertEqual(ran["applied"], True)
        self.assertEqual(ran["report"]["cases"]["tests.test_p::t2"], ("failed", "AssertionError: y"))

    def test_a_change_that_does_not_apply_runs_no_test(self):
        ran = judge.diagnostic(Path(self.temporary.name) / "d3", "items", "c" * 40, self.patch.replace(b"x = 1", b"z = 9"), 20)
        self.assertEqual((ran["applied"], ran["report"]["cases"]), (False, {}))

    def test_the_tests_limit_is_kept(self):
        (self.base / "peer" / "superyak_peer" / "slow").write_text("")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-q", "-m", "slow")
        ran = judge.diagnostic(Path(self.temporary.name) / "d4", "items", "c" * 40, b"", 1)
        self.assertEqual((ran["applied"], ran["limit"], ran["report"]["cases"]), (True, True, {}))


class Shape(unittest.TestCase):
    def test_parses_under_python_3_9(self):
        import ast
        for name in ("documents_judge.py", "test_documents_judge.py"):
            ast.parse((HERE / name).read_text(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
