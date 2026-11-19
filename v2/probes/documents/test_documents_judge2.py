#!/usr/bin/env python3
"""Tests of the second pilot's judge, with stand-ins for the plan, the runner's records and the room's exports.

  python3 -I v2/probes/documents/test_documents_judge2.py
"""
import hashlib
import importlib.util
import json
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("documents_judge2", HERE / "documents_judge2.py")
judge2 = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge2)
first = judge2.first
Refused = judge2.Refused
SOURCE = first.SOURCE


def order_for(items):
    """The order as the plan fixes it: ascending SHA-256 of `20261120:order:<commit>:<row>`."""
    rows = sorted((hashlib.sha256(("20261120:order:%s:%s" % (item["commit"], row)).encode("ascii")).hexdigest(),
        item["commit"], item["item"], row) for item in items for row in item["rows"])
    return [{"n": n, "commit": commit, "item": short, "row": row, "hash": digest,
        "directory": "rows/%03d-%s-%s" % (n, short, row)} for n, (digest, commit, short, row) in enumerate(rows, 1)]


def plan_item(k, part, pool=None, group=None, rows=None, base="b" * 40):
    short = "%010x" % (0xa000000000 + k)
    rows = rows if rows is not None else judge2.PART_ROWS[part]
    return {"commit": short + "0" * 30, "item": short, "parent": "f" * 40, "part": part, "pool": pool,
        "plan_group": group, "matching": ["docs/plans/p%d.md" % k] if pool in (None, "P") else [],
        "direct_path": "docs/plans/p%d.md" % k if pool in (None, "P") else None,
        "task_kind": "frozen" if part == "A" else "message", "task_sha256": "",
        "message": {"names_a_matching_file": k % 2 == 0, "cites_a_task_or_step": False, "counted_names_held": ["f%d" % k]}
            if pool == "P" else None,
        "tests": [], "kept_out": {"reference": "", "test_blobs": []}, "documents": {},
        "rows": {row: {"paragraph": judge2.LINE if row.startswith("may") else "", "base": base, "wrong": "0" * 40,
            "task_file_sha256": ""} for row in rows}}


class Plan2:
    """A plan's directory shaped as the build's plan fixes plan.json (v 2), with one pinned input, the controls of
    every item (four frozen cases, t1 passing on the parent), and records where the runner writes them."""

    def __init__(self, root, items, part_b_run=True, v=2):
        self.root = Path(root)
        self.out = self.root / "out"
        (self.out / "rows").mkdir(parents=True)
        self.pinned = self.root / "pinned.txt"
        self.pinned.write_text("a pinned input\n")
        self.plan = {"v": v, "seed": 20261120, "spec_sha256": "", "list_sha256": "", "line": judge2.LINE,
            "selection": {}, "part_b_run": part_b_run, "walk": {"P": [], "N": []},
            "worker": {"name": "script:/pinned/worker.sh", "version": "script", "model": "script"},
            "limits": {"worker_secs": 1, "check_secs": 900, "replay_secs": 11, "diagnostic_secs": 7, "lease_secs": 13},
            "inputs": {first.maker.pin_path(self.pinned): first.pilot.digest(self.pinned.read_bytes())},
            "items": items, "order": order_for(items), "items_dir": str(self.root / "items"),
            "programs": {"yak": {"path": "/pinned/yak", "sha256": ""}, "worker": {"path": "/pinned/worker.sh", "sha256": ""}},
            "environment": {"PATH": "/usr/bin:/bin", "YAK_JAIL_READ": "/pinned/read"}}
        self.write()

    def write(self):
        raw = (json.dumps(self.plan, sort_keys=True, indent=1) + "\n").encode()
        (self.out / "plan.json").write_bytes(raw)
        (self.out / "plan.sha256").write_text(first.pilot.digest(raw) + "\n")
        # A made plan always has the record of what its controls ran under: the maker requires it.
        (self.out / first.maker.CONTROL_RUNTIME).write_text(json.dumps(first.maker.control_runtime(
            self.plan["limits"], self.plan["programs"], self.plan["environment"])))
        for item in self.plan["items"]:
            controls = self.out / "controls" / item["item"]
            if controls.exists():
                continue
            (controls / "parent").mkdir(parents=True)
            (controls / "cases.json").write_text(json.dumps({"commit": item["commit"],
                "cases": ["tests.test_a::t%d" % k for k in range(1, 5)], "counts": {}}))
            (controls / "parent" / "junit.json").write_text(json.dumps({"cases": {"tests.test_a::t1": ["passed", ""],
                "tests.test_a::t2": ["failed", "nope"]}, "collection_errors": []}))
            (controls / "parent.json").write_text(json.dumps({"commit": item["commit"], "passed": ["tests.test_a::t1"]}))

    def order(self, item, row):
        return [held for held in self.plan["order"] if held["item"] == item["item"] and held["row"] == row][0]

    def record(self, item, row, walk=None, turns=None, walks_exit=0, outcome="no-hand-in", **more):
        """A no-hand-in row as the runner writes it, with the room's turns export and its one walk; `more` are further
        fields of its record (no_commit, say)."""
        order = self.order(item, row)
        directory = self.out / order["directory"]
        directory.mkdir()
        (directory / "item.txt").write_text("%s room-item script:/pinned/worker.sh\n" % order["commit"])
        (directory / "record.json").write_text(json.dumps({"n": order["n"], "commit": order["commit"], "row": row,
            "outcome": outcome, "turn_commit": None, "at_limit": False, "turns_exit": 0, "walks_exit": walks_exit,
            "earlier_attempts": 0, "attempts": [], "interrupted_attempts": 0, **more}))
        (directory / "turns.json").write_text(json.dumps(turns if turns is not None else
            [{"commit": None, "passed": None, "measured": {"ended": "exited"}}]))
        if walk is not None:
            (directory / "walks.jsonl").write_text(walk if isinstance(walk, str) else json.dumps(walk) + "\n")
        return order

    def score(self, item, row, passed, of=4, passed_new=None, of_new=3, scored=True, **more):
        """score.json written directly, as the judge writes it."""
        order = self.order(item, row)
        directory = self.out / "judged" / order["directory"][len("rows/"):]
        directory.mkdir(parents=True)
        held = {"n": order["n"], "commit": order["commit"], "row": row, "passed": passed, "of": of,
            "passed_new": max(passed - 1, 0) if passed_new is None else passed_new, "of_new": of_new, "scored": scored,
            "outcome": "handed-in" if scored else "report-refused", "matching_named": {}, "walk_read": True,
            "plans_named": [], "first_source_second": None, "steps": 3, "worker_seconds": 10.0, "tokens": 100}
        held.update(more)
        (directory / "score.json").write_text(json.dumps(held))


def s(passed, of=8, scored=True, passed_new=None, of_new=None):
    return {"passed": passed, "of": of, "scored": scored, "outcome": "handed-in",
        "passed_new": passed if passed_new is None else passed_new, "of_new": of if of_new is None else of_new}


def reading_of(n1, n2, m1, m2, of=8):
    scores = {}
    for row, value in (("nothing-1", n1), ("nothing-2", n2), ("may-1", m1), ("may-2", m2)):
        if value is not None:
            scores[row] = s(value, of)
    return judge2.item_reading(scores)


class Readings(unittest.TestCase):
    def test_higher_by_hand(self):
        got = reading_of(2, 4, 7, 7)                       # b = 3/8, rn = 2/8; m = 7/8, rm = 0; d = 4/8 > 2/8
        self.assertEqual((got["b"], got["rn"], got["m"], got["rm"], got["d"], got["class"]),
            (Fraction(3, 8), Fraction(2, 8), Fraction(7, 8), Fraction(0), Fraction(1, 2), "higher"))

    def test_lower_by_hand(self):
        got = reading_of(6, 6, 2, 3)                       # d = 5/16 - 6/8 = -7/16 < -1/8
        self.assertEqual((got["d"], got["rm"], got["class"]), (Fraction(-7, 16), Fraction(1, 8), "lower"))

    def test_a_loss_inside_a_wide_gap_stays_within(self):
        got = reading_of(0, 8, 2, 2)                       # d = 2/8 - 4/8 = -2/8; max gap 8/8
        self.assertEqual((got["d"], got["rn"], got["class"]), (Fraction(-1, 4), Fraction(1), "within"))

    def test_d_equal_to_the_gap_is_within(self):
        self.assertEqual(reading_of(4, 6, 7, 7)["class"], "within")       # d = 2/8 = rn
        self.assertEqual(reading_of(4, 6, 2, 4)["class"], "within")       # d = -2/8 = -rn = -rm
        self.assertEqual(reading_of(4, 6, 1, 3)["class"], "lower")        # d = -3/8 < -2/8
        self.assertEqual(reading_of(4, 4, 2, 6)["class"], "within")       # d = 0, rm = 4/8

    def test_the_class_reads_the_larger_gap_of_the_two(self):
        self.assertEqual(reading_of(4, 4, 5, 8)["class"], "within")       # d = 2.5/8, rm = 3/8 > d
        self.assertEqual(reading_of(4, 4, 6, 7)["class"], "higher")       # d = 2.5/8, rm = 1/8

    def test_a_pair_with_one_row_unscored_gives_nulls(self):
        got = reading_of(2, None, 7, 7)
        self.assertEqual((got["n1"], got["n2"], got["b"], got["rn"], got["d"], got["class"], got["ceiling"]),
            (None, None, None, None, None, None, None))
        self.assertEqual((got["m1"], got["m"]), (Fraction(7, 8), Fraction(7, 8)))
        got = judge2.item_reading({"nothing-1": s(2), "nothing-2": s(2), "may-1": s(3), "may-2": s(0, scored=False)})
        self.assertEqual((got["m1"], got["m2"], got["m"], got["rm"], got["d"]), (None, None, None, None, None))
        self.assertEqual(got["b"], Fraction(2, 8))

    def test_the_ceiling_is_over_all_frozen_cases_in_both_readings(self):
        # The reader's input at 33dce6eb: both Nothing rows pass 4 of 8, and all 4 of the 4 that fail on the parent.
        half = {row: s(4, 8, passed_new=4, of_new=4) for row in ("nothing-1", "nothing-2", "may-1", "may-2")}
        self.assertIs(judge2.item_reading(half)["ceiling"], False)
        self.assertIs(judge2.item_reading(half, new=True)["ceiling"], False)
        self.assertEqual(judge2.item_reading(half, new=True)["n1"], 1)          # the new-case share is whole all the same
        whole = {row: s(8, 8, passed_new=4, of_new=4) for row in half}
        self.assertIs(judge2.item_reading(whole)["ceiling"], True)
        self.assertIs(judge2.item_reading(whole, new=True)["ceiling"], True)
        left_out = {row: s(8, 8, passed_new=0, of_new=0) for row in half}       # no case fails on the parent
        self.assertIs(judge2.item_reading(left_out)["ceiling"], True)
        self.assertIsNone(judge2.item_reading(left_out, new=True)["ceiling"])
        one_only = {row: s(8, 8, passed_new=4, of_new=4) for row in half}
        one_only["nothing-2"] = s(7, 8, passed_new=4, of_new=4)                 # whole on the new cases, not on all
        self.assertIs(judge2.item_reading(one_only, new=True)["ceiling"], False)

    def test_the_ceiling(self):
        self.assertIs(reading_of(8, 8, 8, 8)["ceiling"], True)
        self.assertIs(reading_of(8, 7, 8, 8)["ceiling"], False)
        self.assertIs(reading_of(7, 8, 8, 8)["ceiling"], False)
        self.assertEqual(reading_of(8, 8, 8, 8)["class"], "within")

    def test_the_new_cases_share(self):
        scores = {row: s(5, 8, passed_new=1, of_new=4) for row in judge2.NOTHING}
        scores.update({row: s(8, 8, passed_new=4, of_new=4) for row in judge2.MAY})
        got = judge2.item_reading(scores, new=True)
        self.assertEqual((got["b"], got["d"], got["ceiling"]), (Fraction(1, 4), Fraction(3, 4), False))
        scores = {row: s(5, 8, passed_new=0, of_new=0) for row in judge2.PART_ROWS["B"]}
        self.assertIsNone(judge2.item_reading(scores, new=True)["d"])       # no new case: not read


def pool_plan(p_groups=("g1", "g1", "g2", "g3"), n=3):
    items = [plan_item(k, "B", "P", group) for k, group in enumerate(p_groups)]
    items += [plan_item(10 + k, "B", "N") for k in range(n)]
    return {"items": items, "part_b_run": True}


def readings_with(plan, ds, gaps=None, ceilings=None):
    """Readings whose d is given by item: None for no d."""
    gaps = gaps or {}
    readings = {}
    for item, d in zip(plan["items"], ds):
        r = gaps.get(item["item"], Fraction(0))
        readings[item["item"]] = {"d": d, "class": None if d is None else first.classify(d, r),
            "ceiling": (ceilings or {}).get(item["item"], False)}
    return readings


class Pools(unittest.TestCase):
    def test_pool_means_and_the_mean_over_plan_groups(self):
        plan = pool_plan()
        ds = [Fraction(1, 2), Fraction(1, 4), Fraction(-1, 4), None, Fraction(0), Fraction(1, 10), None]
        readings = readings_with(plan, ds)
        p = judge2.pool_reading(plan, readings, "P")
        # Items: (1/2 + 1/4 - 1/4) / 3 = 1/6. Groups: g1 = 3/8, g2 = -1/4, g3 has no d and is left out.
        self.assertEqual((p["mean_d"], p["on"], p["items"]), (Fraction(1, 6), 3, 4))
        self.assertEqual(p["groups"], {"g1": {"mean_d": Fraction(3, 8), "on": 2}, "g2": {"mean_d": Fraction(-1, 4), "on": 1}})
        self.assertEqual((p["mean_groups"], p["groups_on"]), (Fraction(1, 16), 2))
        self.assertEqual((p["higher"], p["lower"], p["within"]), (2, 1, 0))
        n = judge2.pool_reading(plan, readings, "N")
        self.assertEqual((n["mean_d"], n["on"], n["higher"], n["within"]), (Fraction(1, 20), 2, 1, 1))
        self.assertNotIn("mean_groups", n)

    def test_an_aggregate_with_nothing_under_it_is_not_available(self):
        plan = pool_plan()
        readings = readings_with(plan, [None] * 7)
        p = judge2.pool_reading(plan, readings, "P")
        self.assertEqual((p["mean_d"], p["mean_groups"], p["on"], p["groups_on"]), (None, None, 0, 0))
        self.assertEqual(judge2.aggregate(None, 0), "not available")
        self.assertEqual(judge2.aggregate(0.0, 3), "0.000 (on 3 items)")
        self.assertEqual(judge2.mean_of([None, None]), {"mean": None, "on": 0})
        self.assertEqual(judge2.mean_of([0, None, 4]), {"mean": 2, "on": 2})

    def test_all_at_ceiling(self):
        plan = pool_plan(("g1", "g2"), 1)
        names = [item["item"] for item in plan["items"]]
        readings = readings_with(plan, [Fraction(0)] * 3, ceilings={names[0]: True, names[1]: True})
        self.assertIs(judge2.pool_reading(plan, readings, "P")["all_at_ceiling"], True)
        readings = readings_with(plan, [Fraction(0)] * 3, ceilings={names[0]: True})
        self.assertIs(judge2.pool_reading(plan, readings, "P")["all_at_ceiling"], False)
        readings = readings_with(plan, [Fraction(0)] * 3, ceilings={names[0]: True, names[1]: None})
        self.assertIs(judge2.pool_reading(plan, readings, "P")["all_at_ceiling"], False)
        self.assertIs(judge2.pool_reading({"items": []}, {}, "P")["all_at_ceiling"], False)


def every_score(plan):
    return {item["item"]: {row: s(4) for row in item["rows"]} for item in plan["items"]}


def ruled(p_mean=Fraction(1, 10), p_groups=Fraction(1, 10), p_higher=1, n_mean=Fraction(0), n_lower=0, ceiling=False):
    plan = pool_plan()
    pools = {"P": {"mean_d": p_mean, "mean_groups": p_groups, "higher": p_higher, "lower": 0, "all_at_ceiling": ceiling},
        "N": {"mean_d": n_mean, "lower": n_lower, "higher": 0}}
    return judge2.rule(plan, every_score(plan), pools)


class Rule(unittest.TestCase):
    def test_worth_at_its_edges(self):
        self.assertEqual(ruled()["decision"], "worth a larger trial")
        self.assertEqual(ruled(n_mean=Fraction(0))["decision"], "worth a larger trial")      # zero or above
        self.assertEqual(ruled(p_mean=Fraction(1, 1000))["decision"], "worth a larger trial")
        self.assertEqual(ruled(p_mean=Fraction(0))["decision"], "between")                 # above zero
        self.assertEqual(ruled(p_groups=Fraction(0))["decision"], "between")
        self.assertEqual(ruled(p_groups=None)["decision"], "between")
        self.assertEqual(ruled(p_higher=0)["decision"], "between")
        self.assertEqual(ruled(n_mean=Fraction(-1, 1000))["decision"], "between")
        self.assertEqual(ruled(n_mean=None)["decision"], "between")
        self.assertEqual(ruled(n_lower=1)["decision"], "between")

    def test_not_worth_at_its_edges(self):
        self.assertEqual(ruled(n_lower=2)["decision"], "not worth one")
        self.assertEqual(ruled(n_lower=1, p_higher=0)["decision"], "between")
        self.assertEqual(ruled(n_mean=Fraction(-5, 100))["decision"], "between")             # -0.05 exactly
        self.assertEqual(ruled(n_mean=Fraction(-5, 100) - Fraction(1, 10 ** 9))["decision"], "not worth one")
        self.assertEqual(judge2.NOT_WORTH_BELOW, Fraction(-1, 20))

    def test_all_zero_is_between(self):
        got = ruled(p_mean=Fraction(0), p_groups=Fraction(0), p_higher=0, n_mean=Fraction(0))
        self.assertEqual((got["decision"], got["missing"], got["no_gain_possible"]), ("between", [], False))
        got = ruled(p_mean=Fraction(0), p_groups=Fraction(0), p_higher=0, n_mean=Fraction(0), ceiling=True)
        self.assertEqual((got["decision"], got["no_gain_possible"]), ("between", True))

    def test_suspended_on_a_missing_part_b_score_and_not_on_part_a(self):
        plan = pool_plan()
        plan["items"].append(plan_item(30, "A"))
        scores = every_score(plan)
        del scores[plan["items"][-1]["item"]]["may-2"]                           # part A: does not suspend
        pools = {"P": {"mean_d": Fraction(1), "mean_groups": Fraction(1), "higher": 1, "all_at_ceiling": False},
            "N": {"mean_d": Fraction(0), "lower": 0}}
        self.assertEqual(judge2.rule(plan, scores, pools)["decision"], "worth a larger trial")
        scores[plan["items"][4]["item"]]["nothing-2"] = s(0, scored=False)      # pool N, no score
        del scores[plan["items"][0]["item"]]["may-1"]                            # pool P, not judged
        got = judge2.rule(plan, scores, pools)
        self.assertEqual((got["decision"], sorted(got["missing"])), ("suspended", sorted(["%s nothing-2" %
            plan["items"][4]["item"], "%s may-1" % plan["items"][0]["item"]])))

    def test_part_b_not_run_gives_no_rule(self):
        plan = {"items": [plan_item(30, "A")], "part_b_run": False}
        self.assertIsNone(judge2.rule(plan, {}, {"P": {}, "N": {}}))


class Shape(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_plan_of_the_first_pilot_is_refused(self):
        plan = Plan2(self.temporary.name, [plan_item(0, "A")], part_b_run=False, v=1)
        with self.assertRaisesRegex(Refused, "v is 1, not 2"):
            judge2.load_judged_plan(plan.out)

    def test_a_part_b_item_with_a_row_missing_is_refused(self):
        items = [plan_item(0, "B", "P", "g", rows=("nothing-1", "nothing-2", "may-1"))]
        with self.assertRaisesRegex(Refused, "rows are"):
            judge2.check_shape({"v": 2, "part_b_run": True, "items": items, "order": order_for(items)})

    def test_shapes_refused(self):
        a, b = plan_item(0, "A"), plan_item(1, "B", "N")
        good = {"v": 2, "part_b_run": True, "items": [a, b], "order": order_for([a, b])}
        self.assertIs(judge2.check_shape(good), good)
        for change, words in ((dict(part_b_run="yes"), "not a bool"), (dict(part_b_run=False), "part_b_run is false"),
                (dict(order=good["order"][1:]), "order"), (dict(order=good["order"] + good["order"][:1]), "order")):
            with self.assertRaisesRegex(Refused, words):
                judge2.check_shape(dict(good, **change))
        for item, words in ((dict(a, part="C"), "part"), (dict(a, pool="P"), "pool"), (dict(b, pool=None), "pool"),
                (dict(a, rows=b["rows"]), "rows are")):
            with self.assertRaisesRegex(Refused, words):
                judge2.check_shape(dict(good, items=[item, b], order=order_for([item, b])))


class Walks(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.a = plan_item(0, "A")
        self.plan = Plan2(self.temporary.name, [self.a], part_b_run=False)

    def tearDown(self):
        self.temporary.cleanup()

    def judged(self, again=0, **record):
        """The row judged by judge2.judge; `again` is the exit of the room's export run again by judge_row."""
        order = self.plan.record(self.a, "may-1", **record)
        listed = {"commits": [{"commit": self.a["commit"], "base": "b" * 40, "wrong": "d" * 40, "reference": "e" * 40,
            "title": "t", "part": "pilot", "check": {"command": "c", "files": ["f"]}}]}
        calls = []
        real = first.judge_row

        def counted(*args, **kwargs):
            calls.append(args)
            return real(*args, **kwargs)
        with mock.patch.object(first, "check_items", lambda plan, items: listed), \
                mock.patch.object(first, "judge_row", counted), \
                mock.patch.object(first, "export_again", lambda out, plan, order, judged, what: again):
            self.assertEqual(judge2.judge(self.plan.out, "items"), 0)
        self.assertEqual(len(calls), 1)                          # the first judge's own judge_row scores the row
        return first.pilot.load(self.plan.out / "judged" / order["directory"][len("rows/"):] / "score.json")

    def test_judge_skips_what_it_must_not_judge(self):
        b = plan_item(1, "A")
        self.plan.plan["items"].append(b)
        self.plan.plan["order"] = order_for(self.plan.plan["items"])
        self.plan.write()
        for name in ("parent.json", "cases.json"):
            (self.plan.out / "controls" / b["item"] / name).unlink()
        self.plan.record(b, "may-1")                             # its controls are not made: not judged
        order = self.plan.record(self.a, "may-2", walk={"steps": []})
        listed = {"commits": [{"commit": self.a["commit"], "base": "b" * 40, "wrong": "d" * 40, "reference": "e" * 40,
            "title": "t", "part": "pilot", "check": {"command": "c", "files": ["f"]}}]}
        score = self.plan.out / "judged" / order["directory"][len("rows/"):] / "score.json"
        with mock.patch.object(first, "check_items", lambda plan, items: listed):
            judge2.judge(self.plan.out, "items", rows=0)
            self.assertFalse(score.exists())
            judge2.judge(self.plan.out, "items", rows=1)
            self.assertTrue(score.exists())
            score.write_text(json.dumps({"kept": True}))
            judge2.judge(self.plan.out, "items")                 # a judged row is not judged again
            self.assertEqual(json.loads(score.read_text()), {"kept": True})
        self.assertFalse((self.plan.out / "judged" / self.plan.order(b, "may-1")["directory"][len("rows/"):]).exists())
        stale = self.plan.out / "judged" / self.plan.order(self.a, "may-1")["directory"][len("rows/"):]
        stale.mkdir()
        self.plan.record(self.a, "may-1", walk={"steps": []})
        with mock.patch.object(first, "check_items", lambda plan, items: listed):
            judge2.judge(self.plan.out, "items")
        self.assertTrue((stale / "score.json").exists())
        self.assertTrue((self.plan.out / "judged" / "interrupted").is_dir())     # a stale directory moved aside

    def test_the_walks_counts_from_a_small_walk(self):
        walk = {"steps": [
            {"seq": 0, "seen_ms": 900, "named": [["peer/superyak_peerx/z.py", "a" * 40], [], "x", [3, "y"],
                {"path": "docs/plans/q.md"}]},
            {"seq": 1, "seen_ms": 4000, "named": [["docs/reviews/r.md", "b" * 40], ["docs/plans/p0.md", "c" * 40]]},
            {"seq": 2, "seen_ms": 7500, "named": [[SOURCE + "/b.py", "d" * 40]]},
            {"seq": 3, "seen_ms": 5200, "named": [[SOURCE + "/a.py", "e" * 40], ["docs/reviews/r.md", "b" * 40]]},
            {"seq": 4, "seen_ms": None, "named": [[SOURCE + "/c.py", "f" * 40]]},
            {"seq": 5, "seen_ms": 9000, "named": [["specs.md", "1" * 40], ["x/specs/y/z.md", "3" * 40]]}]}
        turns = [{"commit": None, "passed": None, "measured": {"ended": "exited", "worker_ms": 187250,
            "tokens": {"fresh_in": 1000, "output": 234, "cache_read": 99999, "complete": True}}}]
        got = self.judged(walk=walk, turns=turns)
        self.assertEqual(got["plans_named"], ["docs/plans/p0.md", "docs/reviews/r.md", "x/specs/y/z.md"])
        self.assertEqual(got["first_source_second"], 5.2)
        self.assertEqual((got["steps"], got["steps_from"], got["worker_seconds"], got["tokens"], got["walk_read"]),
            (6, "walk", 187.25, 1234, True))
        self.assertNotIn("seconds", got)
        self.assertEqual(got["matching_named"], {"docs/plans/p0.md": {"step": 1, "seconds": 4.0}})
        self.assertEqual((got["outcome"], got["passed"], got["of"]), ("no-hand-in", 1, 4))      # judge_row's own

    def test_a_walk_naming_none_gives_empty_and_null_not_unread(self):
        got = self.judged(walk={"steps": [{"seq": 0, "seen_ms": 10, "named": [["README.md", "a" * 40]]},
            {"seq": 1, "seen_ms": 20, "named": []}]})
        self.assertEqual((got["plans_named"], got["first_source_second"], got["steps"], got["walk_read"]),
            ([], None, 2, True))
        self.assertEqual((got["worker_seconds"], got["tokens"]), (None, None))     # the turns export had no numbers

    def test_a_walk_that_cannot_be_read_gives_nulls(self):
        walk = {"steps": [{"seq": 0, "seen_ms": 10, "named": [["docs/plans/p0.md", "a" * 40]]}]}
        got = self.judged(again=2, walks_exit=3, walk=walk)     # export failed; exported again, which fails too
        self.assertEqual((got["plans_named"], got["first_source_second"], got["steps"], got["walk_read"]),
            (None, None, None, False))
        self.assertEqual((got["exported_again"], got["matching_named"], got["steps_from"]), ({"walks": 2}, None, None))

    def test_the_rooms_own_step_count_is_taken_when_its_export_gives_one(self):
        turns = [{"commit": None, "passed": None, "steps": 9, "steps_with_a_name": 4, "measured": {"ended": "exited"}}]
        got = self.judged(walk={"steps": [{"seq": 0, "seen_ms": 10, "named": []}]}, turns=turns)
        self.assertEqual((got["steps"], got["steps_from"]), (9, "room"))
        self.temporary.cleanup()
        self.setUp()
        got = self.judged(again=2, walks_exit=3, turns=turns)  # the walk unread: the room's count stands
        self.assertEqual((got["steps"], got["steps_from"], got["plans_named"]), (9, "room", None))

    def test_a_walk_exported_again_is_read_from_the_judged_row(self):
        def again(out, plan, order, judged, what):
            (Path(judged) / "walks.jsonl").write_text(json.dumps({"steps": [{"seq": 0, "seen_ms": 2500,
                "named": [["docs/specs/s.md", "a" * 40], [SOURCE + "/a.py", "b" * 40]]}]}) + "\n")
            return 0
        order = self.plan.record(self.a, "may-1", walks_exit=3, walk={"steps": []})
        listed = {"commits": [{"commit": self.a["commit"], "base": "b" * 40, "wrong": "d" * 40, "reference": "e" * 40,
            "title": "t", "part": "pilot", "check": {"command": "c", "files": ["f"]}}]}
        with mock.patch.object(first, "check_items", lambda plan, items: listed), \
                mock.patch.object(first, "export_again", again):
            judge2.judge(self.plan.out, "items")
        got = first.pilot.load(self.plan.out / "judged" / order["directory"][len("rows/"):] / "score.json")
        self.assertEqual((got["plans_named"], got["first_source_second"], got["steps"]), (["docs/specs/s.md"], 2.5, 1))

    def test_unreadable_walk_files(self):
        directory = Path(self.temporary.name)
        for name, text in (("empty", ""), ("two", "{\"steps\": []}\n{\"steps\": []}\n"), ("list", "[]\n"),
                ("bad", "{\n"), ("steps", "{\"steps\": 3}\n"), ("step", "{\"steps\": [3]}\n")):
            (directory / name).write_text(text)
            self.assertIsNone(judge2.read_steps(directory / name), name)
        self.assertIsNone(judge2.read_steps(None))
        self.assertIsNone(judge2.read_steps(directory / "absent"))
        (directory / "one").write_text("\n{\"steps\": []}\n\n")
        self.assertEqual(judge2.read_steps(directory / "one"), [])

    def test_seconds_and_tokens_are_null_where_not_given(self):
        directory = Path(self.temporary.name)
        for turns, wanted in (
                ([{"steps": 7, "measured": {"worker_ms": 1500, "tokens": {"fresh_in": 0, "output": 0}}}], (1.5, 0, 7)),
                ([{"steps": 0, "measured": {"worker_ms": None, "tokens": {"fresh_in": 5, "output": None}}}], (None, None, 0)),
                ([{"steps": "7", "measured": {"worker_ms": "9", "tokens": {"fresh_in": None, "output": 5}}}], (None, None, None)),
                ([{"steps": True, "measured": {"worker_ms": 2000, "tokens": None}}], (2.0, None, None)),
                ([{"measured": {"worker_ms": 2000, "tokens": [1, 2]}}], (2.0, None, None)),
                ([{"measured": {"tokens": {"fresh_in": True, "output": 1}}}], (None, None, None)),
                ([{"steps": 3, "measured": []}], (None, None, 3)), ([], (None, None, None)), ({}, (None, None, None)),
                ([None], (None, None, None)),
                ([{"steps": 1, "measured": {"worker_ms": 1}}, {"measured": {"worker_ms": 1}}], (None, None, None))):
            (directory / "turns.json").write_text(json.dumps(turns))
            self.assertEqual(judge2.read_measured(directory / "turns.json"), wanted, turns)
        (directory / "turns.json").write_text("{")
        self.assertEqual(judge2.read_measured(directory / "turns.json"), (None, None, None))
        self.assertEqual(judge2.read_measured(None), (None, None, None))

    def test_the_export_read_is_the_one_judge_row_read(self):
        order = self.plan.order(self.a, "may-1")
        out = self.plan.out
        self.assertEqual(judge2.export_path(out, order, {"walks_exit": 0}, {"exported_again": {}}, "walks", "w"),
            first.row_dir(out, order) / "w")
        self.assertEqual(judge2.export_path(out, order, {"walks_exit": 1}, {"exported_again": {"walks": 0}}, "walks",
            "w"), first.judged_dir(out, order) / "w")
        self.assertIsNone(judge2.export_path(out, order, {"walks_exit": 1}, {"exported_again": {"walks": 2}}, "walks",
            "w"))

    def test_folders_and_the_source(self):
        self.assertTrue(judge2.under_folders("plans/a.md"))
        self.assertTrue(judge2.under_folders("a/reviews/b/c.md"))
        self.assertFalse(judge2.under_folders("plans"))
        self.assertFalse(judge2.under_folders("a/plans.md"))
        self.assertFalse(judge2.under_folders("a/Plans/b.md"))
        self.assertEqual(judge2.first_source_second([{"seq": 0, "seen_ms": None, "named": [[SOURCE + "/a.py", "x"]]}]),
            None)
        self.assertEqual(judge2.first_source_second([{"seq": 2, "seen_ms": 300, "named": [[SOURCE + "/a.py", "x"]]},
            {"seq": 1, "seen_ms": 300, "named": [[SOURCE + "/b.py", "x"]]}]), 0.3)


class Controls(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.out = Path(self.temporary.name) / "out"
        self.out.mkdir()

    def tearDown(self):
        self.temporary.cleanup()

    limits = {"worker_secs": 1200, "check_secs": 900, "replay_secs": 1200, "diagnostic_secs": 300, "lease_secs": 1800}
    yak = {"path": "/y", "sha256": "a" * 64}

    def run_controls(self, items="items"):
        made = []
        pins = mock.Mock(return_value=({"name": "script:/bin/sh"}, dict(self.limits), {"yak": dict(self.yak),
            "worker": {"path": "/bin/sh"}}, {"PATH": "/p"}))
        listed = {"commits": []}
        with mock.patch.object(first, "control_item", lambda out, plan, items, held, item:
                made.append((out, plan, items, held, item["item"]))), \
                mock.patch.object(first, "check_items", lambda plan, items: (plan, listed)[1] if plan.get("list_sha256")
                == "L" else self.fail("the item list is checked against candidates.json")), \
                mock.patch.object(first.maker, "runtime_pins", pins):
            self.assertEqual(judge2.controls(self.out, items), 0)
        return made, pins, listed

    def test_before_a_plan_every_candidate_is_controlled_with_the_makers_pins(self):
        (self.out / "candidates.json").write_text(json.dumps({"v": 2, "list_sha256": "L", "selection": {},
            "part_a": [{"commit": "1" * 40, "item": "1" * 10, "parent": "f" * 40}],
            "pool_p": [{"n": 1, "commit": "2" * 40, "item": "2" * 10, "parent": "f" * 40, "plan_group": "g",
                "matching": [], "direct_path": "x"}],
            "pool_n": [{"n": 1, "commit": "3" * 40, "item": "3" * 10, "parent": "f" * 40},
                {"n": 2, "commit": "1" * 40, "item": "1" * 10, "parent": "f" * 40},
                {"n": 3, "commit": "4" * 40, "item": "4" * 10, "parent": "f" * 40}]}))
        made, pins, listed = self.run_controls()
        self.assertEqual([held[4] for held in made], ["1" * 10, "2" * 10, "3" * 10, "4" * 10])
        self.assertEqual(made[0][:4], (self.out.resolve(), {"limits": self.limits,
            "programs": {"yak": self.yak, "worker": {"path": "/bin/sh"}}, "environment": {"PATH": "/p"}}, "items", listed))
        self.assertEqual(pins.call_args[0][2:], ("script:/bin/sh", None, 1200, 300))    # make_plan's defaults
        self.assertTrue((self.out / "controls").is_dir())
        # What the controls ran under is written down: the limits a control uses, the room's program, the
        # environment; not the worker's pin or its limit, which no control uses.
        held = json.loads((self.out / first.maker.CONTROL_RUNTIME).read_text())
        self.assertEqual(held, {"limits": {key: value for key, value in self.limits.items() if key != "worker_secs"},
            "yak": self.yak, "environment": {"PATH": "/p"}})

    def candidates_of_one(self):
        (self.out / "candidates.json").write_text(json.dumps({"v": 2, "list_sha256": "L", "selection": {},
            "part_a": [{"commit": "1" * 40, "item": "1" * 10, "parent": "f" * 40}], "pool_p": [], "pool_n": []}))

    def test_the_runtime_is_written_before_the_first_control(self):
        self.candidates_of_one()
        seen = []
        pins = mock.Mock(return_value=({}, dict(self.limits), {"yak": dict(self.yak)}, {"PATH": "/p"}))
        with mock.patch.object(first, "control_item", lambda out, plan, items, held, item:
                seen.append((out / first.maker.CONTROL_RUNTIME).exists())), \
                mock.patch.object(first, "check_items", lambda plan, items: {"commits": []}), \
                mock.patch.object(first.maker, "runtime_pins", pins):
            self.assertEqual(judge2.controls(self.out, "items"), 0)
        self.assertEqual(seen, [True])

    def test_a_changed_runtime_is_refused_on_a_later_run_and_makes_no_control(self):
        self.candidates_of_one()
        self.run_controls()
        for change in ("program", "environment", "limit"):
            limits, yak, environment = dict(self.limits), dict(self.yak), {"PATH": "/p"}
            if change == "program":
                yak["sha256"] = "b" * 64
            elif change == "environment":
                environment["PATH"] = "/q"
            else:
                limits["replay_secs"] = 1201
            made = []
            pins = mock.Mock(return_value=({}, limits, {"yak": yak}, environment))
            with mock.patch.object(first, "control_item", lambda *held: made.append(held)), \
                    mock.patch.object(first, "check_items", lambda plan, items: {"commits": []}), \
                    mock.patch.object(first.maker, "runtime_pins", pins):
                with self.assertRaisesRegex(Refused, "runtime differs", msg=change):
                    judge2.controls(self.out, "items")
            self.assertEqual(made, [], change)
        # The worker's own limit is no part of it: a control does not use it.
        pins = mock.Mock(return_value=({}, dict(self.limits, worker_secs=5), {"yak": dict(self.yak)}, {"PATH": "/p"}))
        with mock.patch.object(first, "control_item", lambda *held: None), \
                mock.patch.object(first, "check_items", lambda plan, items: {"commits": []}), \
                mock.patch.object(first.maker, "runtime_pins", pins):
            self.assertEqual(judge2.controls(self.out, "items"), 0)

    def test_controls_found_with_no_record_of_their_runtime_are_refused(self):
        self.candidates_of_one()
        (self.out / "controls" / ("1" * 10)).mkdir(parents=True)
        made = []
        pins = mock.Mock(return_value=({}, dict(self.limits), {"yak": dict(self.yak)}, {"PATH": "/p"}))
        with mock.patch.object(first, "control_item", lambda *held: made.append(held)), \
                mock.patch.object(first, "check_items", lambda plan, items: {"commits": []}), \
                mock.patch.object(first.maker, "runtime_pins", pins):
            with self.assertRaisesRegex(Refused, "not recorded"):
                judge2.controls(self.out, "items")
        self.assertEqual(made, [])
        self.assertFalse((self.out / first.maker.CONTROL_RUNTIME).exists())
        # An empty controls directory holds no control: the record is written and the controls are made.
        (self.out / "controls" / ("1" * 10)).rmdir()
        with mock.patch.object(first, "control_item", lambda *held: made.append(held)), \
                mock.patch.object(first, "check_items", lambda plan, items: {"commits": []}), \
                mock.patch.object(first.maker, "runtime_pins", pins):
            self.assertEqual(judge2.controls(self.out, "items"), 0)
        self.assertEqual(len(made), 1)

    def test_before_a_plan_items_are_needed_and_candidates_of_v2(self):
        (self.out / "candidates.json").write_text(json.dumps({"v": 2, "list_sha256": "L", "part_a": [], "pool_p": [],
            "pool_n": []}))
        with self.assertRaisesRegex(Refused, "--items"):
            judge2.controls(self.out, None)
        (self.out / "candidates.json").write_text(json.dumps({"v": 1, "list_sha256": "L", "part_a": [], "pool_p": [],
            "pool_n": []}))
        with self.assertRaisesRegex(Refused, "v is 1"):
            judge2.controls(self.out, "items")

    def test_with_a_plan_its_items_are_controlled_with_its_pins(self):
        items = [plan_item(0, "A"), plan_item(1, "B", "N")]
        plan = Plan2(self.temporary.name + "/p", items)
        made = []
        with mock.patch.object(first, "control_item", lambda out, held, items, listed, item:
                made.append((held["limits"], items, item["item"]))), \
                mock.patch.object(first, "check_items", lambda held, items: {"commits": []}):
            self.assertEqual(judge2.controls(plan.out, None), 0)
        self.assertEqual(made, [(plan.plan["limits"], plan.plan["items_dir"], item["item"]) for item in items])
        # With a plan the runtime compared is the plan's own: a record of another program refuses, and makes none.
        held = json.loads((plan.out / first.maker.CONTROL_RUNTIME).read_text())
        held["yak"]["sha256"] = "c" * 64
        (plan.out / first.maker.CONTROL_RUNTIME).write_text(json.dumps(held))
        made.clear()
        with mock.patch.object(first, "control_item", lambda *taken: made.append(taken)), \
                mock.patch.object(first, "check_items", lambda held, items: {"commits": []}):
            with self.assertRaisesRegex(Refused, "runtime differs"):
                judge2.controls(plan.out, None)
        self.assertEqual(made, [])

    def test_the_first_judges_controls_call_control_item_for_each_item(self):
        source = (HERE / "documents_judge.py").read_text(encoding="utf-8")
        body = source[source.index("def controls(out, items):"):source.index("def parent_score")]
        self.assertIn("control_item(out, plan, items, listed, item)", body)
        self.assertNotIn("diagnostic(", body)


class Report(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def test_the_report_end_to_end(self):
        a, a2 = plan_item(0, "A"), plan_item(4, "A")
        p1, p2, n1 = plan_item(1, "B", "P", "g1"), plan_item(2, "B", "P", "g2"), plan_item(3, "B", "N")
        plan = Plan2(self.temporary.name, [a, a2, p1, p2, n1])
        for row, passed in (("nothing-1", 1), ("nothing-2", 1), ("may-1", 4), ("may-2", 3)):
            plan.score(p1, row, passed, matching_named={"docs/plans/p1.md": {}} if row == "may-1" else {},
                plans_named=["docs/plans/p1.md"] if row.startswith("may") else [])
            plan.score(p2, row, 2)
            plan.score(n1, row, 2, tokens=None, walk_read=False, steps=5, plans_named=None)        # the room's count
        plan.score(a, "may-1", 2, matching_named={"docs/plans/p0.md": {}})
        plan.record(a, "may-1")
        plan.score(a, "may-2", 0, scored=False)                  # matching_named {}: names none
        plan.record(a2, "may-1")                                 # recorded, not judged
        (plan.out / "controls" / n1["item"] / "stopped.json").write_text(json.dumps({"reason": "a reason"}))
        report = judge2.write_report(plan.out)
        self.assertEqual(report["rule"], {"decision": "worth a larger trial", "missing": [], "no_gain_possible": False})
        self.assertEqual(report["items"][p1["item"]]["d"], 0.625)
        self.assertEqual(report["items"][p1["item"]]["class"], "higher")
        self.assertEqual(report["items"][p1["item"]]["message"], p1["message"])
        self.assertEqual(report["pools"]["P"]["mean_d"], 0.3125)
        self.assertEqual(report["pools"]["P"]["mean_groups"], 0.3125)
        self.assertEqual(report["pools"]["N"]["mean_d"], 0.0)
        self.assertEqual(report["counts"]["P may"]["names_matching"], 1)
        self.assertEqual(report["counts"]["P may"]["plans_paths"], ["docs/plans/p1.md"])
        self.assertEqual(report["counts"]["N may"]["tokens"], {"mean": None, "on": 0})
        self.assertEqual(report["counts"]["N may"]["walks_read"], 0)
        # No walk of pool N was read: what its walks name is not known, and is not said to be nothing.
        for kind in ("N may", "N nothing"):
            self.assertIsNone(report["counts"][kind]["turns_naming_plans_paths"], kind)
            self.assertIsNone(report["counts"][kind]["plans_paths"], kind)
        self.assertEqual(report["counts"]["P nothing"]["plans_paths"], [])        # read, and naming none: a real zero
        self.assertEqual(report["counts"]["N may"]["worker_seconds"], {"mean": 10.0, "on": 2})
        self.assertEqual(report["counts"]["N may"]["steps"], {"mean": 5, "on": 2})
        self.assertEqual(report["counts"]["P may"]["steps"], {"mean": 3, "on": 4})
        self.assertEqual((report["counts"]["A may"]["turns"], report["counts"]["A may"]["names_matching"]), (2, 1))
        self.assertEqual(report["counts"]["P may"]["turns_naming_plans_paths"], 2)
        self.assertEqual(report["counts"]["P nothing"]["turns_naming_plans_paths"], 0)
        self.assertEqual(sorted(report["counts"]), ["A may", "N may", "N nothing", "P may", "P nothing"])
        self.assertEqual((report["rows"]["planned"], report["rows"]["recorded"], report["rows"]["judged"],
            report["rows"]["unjudged"]), (16, 2, 14, [plan.order(a2, "may-1")["directory"]]))
        self.assertEqual(report["controls_stopped"], {n1["item"]: "a reason"})
        self.assertNotIn("names_matching", report["counts"]["N may"])
        self.assertEqual((report["part_a"]["names_matching"], report["part_a"]["walks_read"]), (1, 2))
        self.assertEqual(report["part_a"]["turns"], 4)
        self.assertEqual(report["part_a"]["items"][a["item"]], {"may-1": {"passed": 2, "of": 4}, "may-2": None})
        self.assertEqual(report["part_a"]["items"][a2["item"]], {"may-1": None, "may-2": None})
        text = (plan.out / "report.md").read_text()
        for sentence in (judge2.RULE_SENTENCE, first.FORGE_SENTENCE, first.REPLAY_SENTENCE, judge2.PART_A_SENTENCE,
                judge2.NONE_FOUND_SENTENCE, "**Worth a larger trial**.", "not available"):
            self.assertIn(sentence, text)
        self.assertLess(text.index(judge2.RULE_SENTENCE), text.index("## Part B, each item"))
        self.assertNotIn("no plan exists", text.replace(judge2.NONE_FOUND_SENTENCE, ""))
        self.assertNotIn("could show no gain", text)
        text.encode("ascii")
        # The table's rows for pool N, whose walks were not read, say so in the three counts of what walks name.
        rows = {line.split(" | ")[0].lstrip("| "): line for line in text.splitlines() if line.startswith("| ")}
        self.assertEqual(rows["N may"].split(" | ")[3:6], ["-", "not available", "not available"])
        self.assertEqual(rows["P nothing"].split(" | ")[3:6], ["0", "0", "0"])
        self.assertEqual(rows["P may"].split(" | ")[3:6], ["1", "2", "1"])

    def test_part_a_with_no_walk_read_does_not_say_none_named(self):
        a = plan_item(0, "A")
        plan = Plan2(self.temporary.name, [a])
        plan.score(a, "may-1", 2, walk_read=False, matching_named=None, plans_named=None)
        plan.score(a, "may-2", 2, walk_read=False, matching_named=None, plans_named=None)
        report = judge2.write_report(plan.out)
        self.assertEqual((report["part_a"]["names_matching"], report["part_a"]["walks_read"]), (None, 0))
        self.assertIsNone(report["counts"]["A may"]["names_matching"])
        text = (plan.out / "report.md").read_text()
        self.assertIn("Turns whose walk names a matching file: not available of 2 (walks read: 0).", text)
        self.assertIn("| A may | 2 | 0 | not available | not available | not available |", text)

    def test_suspended_and_part_b_not_run_in_the_report(self):
        p1, n1 = plan_item(1, "B", "P", "g1"), plan_item(3, "B", "N")
        plan = Plan2(self.temporary.name, [p1, n1])
        for row in judge2.PART_ROWS["B"]:
            plan.score(p1, row, 2)
            if row != "may-2":
                plan.score(n1, row, 2)
        report = judge2.write_report(plan.out)
        self.assertEqual(report["rule"], {"decision": "suspended", "missing": ["%s may-2" % n1["item"]],
            "no_gain_possible": None})
        self.assertIn("**Suspended.**", (plan.out / "report.md").read_text())
        a = plan_item(0, "A")
        alone = Plan2(self.temporary.name + "/a", [a], part_b_run=False)
        report = judge2.write_report(alone.out)
        self.assertIsNone(report["rule"])
        self.assertIn("Part B was not run", (alone.out / "report.md").read_text())

    def test_a_pool_at_its_ceiling_could_show_no_gain(self):
        p1, n1 = plan_item(1, "B", "P", "g1"), plan_item(3, "B", "N")
        plan = Plan2(self.temporary.name, [p1, n1])
        for row in judge2.PART_ROWS["B"]:
            plan.score(p1, row, 4)
            plan.score(n1, row, 2)
        report = judge2.write_report(plan.out)
        self.assertEqual(report["rule"], {"decision": "between", "missing": [], "no_gain_possible": True})
        self.assertIn("the pool could show no gain", (plan.out / "report.md").read_text())

    def test_a_score_of_another_row_is_refused(self):
        p1 = plan_item(1, "B", "P", "g1")
        plan = Plan2(self.temporary.name, [p1])
        plan.score(p1, "may-1", 2)
        path = plan.out / "judged" / plan.order(p1, "may-1")["directory"][len("rows/"):] / "score.json"
        held = json.loads(path.read_text())
        path.write_text(json.dumps(dict(held, row="may-2")))
        with self.assertRaisesRegex(Refused, "another row"):
            judge2.make_report(plan.out)


class RefusedHandIn(unittest.TestCase):
    """A hand-in the room refused (spec 2026-11-19, section 3), judged by judge2.judge with the first judge's own
    judge_row, and read in the report."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()

    def tearDown(self):
        self.temporary.cleanup()

    def test_a_refused_part_b_row_suspends_the_rule_by_name_and_a_part_a_row_suspends_nothing(self):
        a, p1, n1 = plan_item(0, "A"), plan_item(1, "B", "P", "g1"), plan_item(3, "B", "N")
        plan = Plan2(self.temporary.name, [a, p1, n1])
        walk = {"steps": [{"seq": 0, "seen_ms": 1500, "named": [["docs/plans/p1.md", "a" * 40]]},
            {"seq": 1, "seen_ms": 3000, "named": [[SOURCE + "/a.py", "b" * 40]]}]}

        def turns(worker_ms, tokens, steps):
            return [{"commit": "b" * 40, "lease_no": 1, "passed": False, "steps": steps, "measured": {"ended": "exited",
                "worker_ms": worker_ms, "tokens": {"fresh_in": tokens, "output": 0}}}]
        for row in ("nothing-1", "nothing-2", "may-1"):
            plan.record(p1, row, walk={"steps": []}, turns=turns(10000, 100, 5))
        plan.record(p1, "may-2", walk=walk, turns=turns(30000, 300, 9), outcome="refused",
            no_commit="refused: single repository")
        for row in judge2.PART_ROWS["B"]:
            plan.record(n1, row, walk={"steps": []}, turns=turns(10000, 100, 5))
        plan.record(a, "may-1", walk=walk, turns=turns(20000, 200, 7), outcome="refused", no_commit="refused: gitlinks")
        plan.record(a, "may-2", walk={"steps": []}, turns=turns(10000, 100, 5))
        with mock.patch.object(first, "check_items", lambda held, items: None):
            judge2.judge(plan.out, "items")
        refused = first.pilot.load(plan.out / "judged" / plan.order(p1, "may-2")["directory"][len("rows/"):]
            / "score.json")
        self.assertEqual((refused["outcome"], refused["scored"], refused["of"], refused["of_new"], refused["no_commit"]),
            ("refused", False, 4, 3, "refused: single repository"))
        # Its costs and what its walk names are kept: they describe work that was done.
        self.assertEqual((refused["worker_seconds"], refused["tokens"], refused["steps"], refused["steps_from"],
            refused["walk_read"], refused["plans_named"], refused["first_source_second"]),
            (30.0, 300, 9, "room", True, ["docs/plans/p1.md"], 3.0))
        report = judge2.write_report(plan.out)
        self.assertEqual(report["rule"], {"decision": "suspended", "missing": ["%s may-2" % p1["item"]],
            "no_gain_possible": None})
        for suffix in ("", "_new"):
            held = report["items" + suffix][p1["item"]]
            self.assertEqual((held["m"], held["d"], held["class"]), (None, None, None), suffix)
            self.assertIsNotNone(held["b"], suffix)
            self.assertIsNotNone(report["items" + suffix][n1["item"]]["d"], suffix)
        self.assertEqual(report["rows"]["unscored"], {"refused": 2})
        self.assertEqual(report["rows"]["outcomes"], {"refused": 2, "no-hand-in": 8})
        self.assertEqual(report["part_a"]["items"][a["item"]], {"may-1": None, "may-2": {"passed": 1, "of": 4}})
        self.assertEqual(report["counts"]["P may"]["worker_seconds"], {"mean": 20.0, "on": 2})
        self.assertEqual(report["counts"]["P may"]["tokens"], {"mean": 200, "on": 2})
        self.assertEqual(report["counts"]["P may"]["steps"], {"mean": 7, "on": 2})
        self.assertEqual((report["counts"]["P may"]["turns_naming_plans_paths"], report["counts"]["P may"]["names_matching"]),
            (1, 1))
        self.assertEqual(report["counts"]["A may"]["worker_seconds"], {"mean": 15.0, "on": 2})
        text = (plan.out / "report.md").read_text()
        self.assertIn("Rows with no score, by outcome: refused 2.", text)
        self.assertIn("**Suspended.** The rule is not applied: these rows it needs have no score: %s may-2." % p1["item"],
            text)
        self.assertIn("| %s | no score | 1 of 4 |" % a["item"], text)
        # Only the part A row refused: the rule reads part B alone and is not suspended by it.
        (plan.out / "judged" / plan.order(p1, "may-2")["directory"][len("rows/"):] / "score.json").unlink()
        record = plan.out / plan.order(p1, "may-2")["directory"] / "record.json"
        held = json.loads(record.read_text())
        del held["no_commit"]
        record.write_text(json.dumps(dict(held, outcome="no-hand-in")))
        with mock.patch.object(first, "check_items", lambda held, items: None):
            judge2.judge(plan.out, "items")
        report = judge2.make_report(plan.out)
        self.assertNotEqual(report["rule"]["decision"], "suspended")
        self.assertEqual(report["rule"]["missing"], [])
        self.assertEqual(report["rows"]["unscored"], {"refused": 1})


class Source(unittest.TestCase):
    def test_parses_under_python_3_9_and_is_ascii(self):
        import ast
        for name in ("documents_judge2.py", "test_documents_judge2.py", "documents_judge.py"):
            data = (HERE / name).read_bytes()
            data.decode("ascii")
            ast.parse(data, feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
