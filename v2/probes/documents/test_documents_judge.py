#!/usr/bin/env python3
"""Tests of the judge, with stand-ins for the room, its jail and the JUnit report.

  python3 -I v2/probes/documents/test_documents_judge.py
"""
import importlib.util
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from fractions import Fraction
from pathlib import Path
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("documents_judge", HERE / "documents_judge.py")
judge = importlib.util.module_from_spec(spec)
spec.loader.exec_module(judge)
Refused = judge.Refused
spec = importlib.util.spec_from_file_location("documents_plan_tests", HERE / "test_documents_plan.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)


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

    def test_a_dtd_in_utf_16_is_refused(self):
        hostile = '<?xml version="1.0" encoding="UTF-16"?><!DOCTYPE t [<!ENTITY e "expanded">]>' \
            '<testsuite><testcase classname="c" name="&e;"/></testsuite>'
        for data in (hostile.encode("utf-16"), hostile.encode("utf-16-le"), hostile.encode("utf-16-be")):
            with self.assertRaisesRegex(Refused, "not UTF-8|control character"):
                judge.read_junit(data)
        # Without its DTD the same UTF-16 document is still refused: only UTF-8 reaches the parser.
        plain = '<?xml version="1.0" encoding="UTF-16"?><testsuite><testcase classname="c" name="t"/></testsuite>'
        for data in (plain.encode("utf-16"), plain.encode("utf-16-le")):
            with self.assertRaises(Refused):
                judge.read_junit(data)
        self.assertEqual(judge.read_junit(plain.encode("utf-8"))["cases"], {"c::t": ("passed", "")})
        for character in ("\x00", "\x01", "\x08", "\x0b", "\x0c", "\x0e", "\x1f"):
            with self.assertRaisesRegex(Refused, "control character"):
                judge.read_junit(("<testsuite name='%s'/>" % character).encode("utf-8"))
        for allowed in ("\t", "\n", "\r", " "):
            self.assertEqual(judge.read_junit(("<testsuite>%s</testsuite>" % allowed).encode("utf-8")), judge.NO_REPORT)

    def test_a_declaration_in_any_case_or_spacing_is_refused(self):
        for data in (b"<!doctype t><testsuite/>", b"<testsuite/><!ENTITY x 'y'>", b"<! DOCTYPE t><testsuite/>"):
            with self.assertRaisesRegex(Refused, "DOCTYPE or an entity"):
                judge.read_junit(data)
        with self.assertRaisesRegex(Refused, "not UTF-8"):
            judge.read_junit(b"<testsuite name='\xff'/>")

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

    def test_only_xml_white_space_makes_a_report_empty(self):
        # The reader's input at 06ee50fa: a report of one forbidden character was read as empty and scored.
        for empty in (b"", b" ", b"\t\r\n  \n"):
            self.assertEqual(judge.read_junit(empty), {"cases": {}, "collection_errors": []}, empty)
        for refused in (b"\x0b", b"\x0c", b"\x1c", b"\x1d", b"\x1e", b"\x1f", b" \x0b\n", b"\x00",
                "\u00a0".encode("utf-8"), "\u2028".encode("utf-8"), b"\x85".decode("latin-1").encode("utf-8"), b"x"):
            with self.assertRaises(judge.ReportRefused, msg=refused):
                judge.read_junit(refused)

    def test_an_empty_report_has_no_cases_and_a_doctype_is_refused(self):
        self.assertEqual(judge.read_junit(b"  \n"), {"cases": {}, "collection_errors": []})
        with self.assertRaises(Refused):
            judge.read_junit(b'<!DOCTYPE x [<!ENTITY a "b">]><testsuite/>')
        with self.assertRaises(Refused):
            judge.read_junit(b"<testsuite>")

    def test_a_frozen_case_not_collected_is_not_run(self):
        report = judge.read_junit(junit([("tests.test_a", "t1", "passed", "")],
            [("tests.test_b", "E   ImportError: no name")]))
        counted = judge.score_cases(frozen_ids("t1") + ["tests.test_b::t9"], report, ["tests.test_b::t9"])
        self.assertEqual((counted["of"], counted["passed"], counted["not_run"]), (2, 1, 1))
        self.assertEqual((counted["of_new"], counted["passed_new"]), (1, 0))
        self.assertEqual(counted["collection_errors"], ["tests.test_b: ImportError: no name"])

    def test_a_candidate_that_adds_cases_does_not_change_of(self):
        report = judge.read_junit(junit([("tests.test_a", name, "passed", "") for name in ("t1", "t2", "t3", "t4", "t5")]))
        counted = judge.score_cases(frozen_ids("t1", "t2"), report, frozen_ids("t2"))
        self.assertEqual((counted["of"], counted["passed"], counted["unfrozen"]), (2, 2, 3))
        self.assertEqual((counted["of_new"], counted["passed_new"]), (1, 1))
        with self.assertRaises(Refused):                          # a new case is always a frozen one
            judge.score_cases(frozen_ids("t1"), report, frozen_ids("t2"))

    def test_counts_and_first_obstacles(self):
        report = judge.read_junit(junit([("tests.test_a", "t1", "passed", ""), ("tests.test_a", "t2", "failed", "first\nsecond"),
            ("tests.test_a", "t3", "error", "err"), ("tests.test_a", "t4", "skipped", "s")]))
        counted = judge.score_cases(frozen_ids("t1", "t2", "t3", "t4", "t5"), report, frozen_ids("t1", "t2", "t5"))
        self.assertEqual({key: counted[key] for key in ("of", "passed", "failed", "error", "skipped", "not_run", "unfrozen")},
            {"of": 5, "passed": 1, "failed": 1, "error": 1, "skipped": 1, "not_run": 1, "unfrozen": 0})
        self.assertEqual((counted["of_new"], counted["passed_new"]), (3, 1))
        self.assertEqual(counted["first_obstacles"], ["first", "err"])

    def test_first_obstacles_stop_at_twenty_and_lines_are_cut(self):
        names = ["t%02d" % k for k in range(25)]
        report = judge.read_junit(junit([("tests.test_a", name, "failed", "x" * 500) for name in names]))
        counted = judge.score_cases(frozen_ids(*names), report, [])
        self.assertEqual(len(counted["first_obstacles"]), 20)
        self.assertEqual(len(counted["first_obstacles"][0]), 400)
        self.assertEqual(counted["failed"], 25)

    def test_a_failure_with_no_message_gives_its_text(self):
        data = b'<testsuite><testcase classname="c" name="t"><failure>\n  text line\nmore</failure></testcase></testsuite>'
        self.assertEqual(judge.score_cases(["c::t"], judge.read_junit(data), [])["first_obstacles"], ["text line"])


class RoomAnswers(unittest.TestCase):
    def test_a_turn_is_read_as_the_runner_reads_a_row(self):
        c, base = "c" * 40, "b" * 40
        with tempfile.TemporaryDirectory() as temporary:
            path, code = Path(temporary) / "turns.json", Path(temporary) / "clock.exit"
            self.assertEqual(judge.turn_outcome(temporary, base), ("clock-failed", None, None))
            code.write_text("0\n")
            path.write_text(json.dumps([{"commit": c, "passed": True, "measured": {"ended": "exited"}}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("handed-in", c, True))
            path.write_text(json.dumps([{"commit": c, "passed": "yes", "measured": {"ended": "exited"}}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("handed-in", c, None))
            path.write_text(json.dumps([{"commit": None, "passed": None, "measured": {"ended": "timed_out"}}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("limit", None, None))
            # As the real room records a turn stopped at its limit with nothing handed in: its base as the commit.
            path.write_text(json.dumps([{"commit": base, "passed": False, "measured": {"ended": "timed_out"}}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("limit", None, None))
            self.assertEqual(judge.read_turns(path, base), ("limit", None, True))
            self.assertIs(judge.turn_timed_out(temporary), True)
            # The mark is kept apart from the outcome: a commit made before the limit is still a hand-in here, and
            # the judge's own stages gate on the mark (the reader's input at 06ee50fa).
            path.write_text(json.dumps([{"commit": c, "passed": True, "measured": {"ended": "timed_out"}}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("handed-in", c, True))
            self.assertIs(judge.turn_timed_out(temporary), True)
            for held in ([{"commit": c, "passed": True, "measured": {"ended": "exited"}}],
                    [{"commit": c, "passed": True, "measured": "timed_out"}], [{"commit": c, "passed": True}],
                    [{"commit": c, "measured": {"ended": "timed_out"}}] * 2, [None], {"measured": {"ended": "timed_out"}}):
                path.write_text(json.dumps(held))
                self.assertIs(judge.turn_timed_out(temporary), False, held)
            path.write_text("not json")
            self.assertIs(judge.turn_timed_out(temporary), False)
            path.unlink()
            self.assertIs(judge.turn_timed_out(temporary), False)
            path.write_text(json.dumps([{"commit": None, "passed": None, "measured": {"ended": "timed_out"}}]))
            path.write_text(json.dumps([{"commit": None, "passed": True, "measured": {"ended": "exited"}}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("no-hand-in", None, None))
            # As the real room records a turn that handed in nothing: its base as the commit, clock exit 1.
            code.write_text("1\n")
            path.write_text(json.dumps([{"commit": base, "passed": False, "measured": {"ended": "exited"}}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("no-hand-in", None, None))
            # The same record read against another base is a hand-in: the turn's own base decides, not the code.
            self.assertEqual(judge.turn_outcome(temporary, c), ("handed-in", base, False))
            # A finished hand-in with clock exit 1 (or 3, or none) is still a hand-in.
            path.write_text(json.dumps([{"commit": c, "passed": True, "measured": {"ended": "exited"}}]))
            for written in ("1\n", "3\n", None):
                if written is None:
                    code.unlink()
                else:
                    code.write_text(written)
                self.assertEqual(judge.turn_outcome(temporary, base), ("handed-in", c, True), written)
            path.write_text(json.dumps([{"commit": c, "passed": True}, {"commit": c, "passed": True}]))
            self.assertEqual(judge.turn_outcome(temporary, base), ("clock-failed", None, None))

    def test_a_judges_turn_begins_on_the_item_lists_base(self):
        listed = {"commits": [entry_for("a" * 40, "b" * 40)]}
        self.assertEqual(judge.turn_base(listed, "a" * 40), "b" * 40)
        with self.assertRaises(Refused):
            judge.turn_base(listed, "c" * 40)

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


def makers_order(commits):
    """The order by the maker's own row_order, with the eighth row another builder adds to the maker's ROWS."""
    with mock.patch.object(judge.maker, "ROWS", judge.ROWS):
        return judge.maker.row_order(commits)


def entry_for(commit, base):
    """An item list's entry as pilot_driver.item_from accepts it."""
    return {"commit": commit, "base": base, "wrong": "d" * 40, "reference": "e" * 40, "title": "t", "part": "pilot",
        "check": {"command": "c", "files": ["f"]}}


JAIL_BASE = "b" * 40          # the item list's base: where the judge's own turns begin


class Plan:
    """A plan's directory with one or more items: plan.json shaped as the maker writes it (every key, the order and
    its directories by the maker's own row_order, one pinned input), controls, a row repository with a base and
    turns. Records are written where the runner writes them: <out>/<order's directory>."""

    def __init__(self, root, items=1, group=lambda k: "p%d" % k):
        self.out = Path(root) / "out"
        (self.out / "rows").mkdir(parents=True)
        self.pinned = Path(root) / "pinned.txt"
        self.pinned.write_text("a pinned input\n")
        self.repo = Path(root) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")
        (self.repo / "peer" / "superyak_peer").mkdir(parents=True)
        (self.repo / "peer" / "superyak_peer" / "a.py").write_text("x = 1\n")
        (self.repo / "TASK.md").write_text("task\n")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        plan_items = []
        for k in range(items):
            short = ("%x" % k) * 10 if k else ITEM
            commit = (short + "0" * 30)
            plan_items.append({"commit": commit, "item": short, "parent": "f" * 40, "probed_before": k == 1,
                "plan_group": group(k), "tests": [], "kept_out": {"reference": "", "test_blobs": []},
                "direct_path": "docs/plans/p.md", "matching": ["docs/plans/p.md"], "facts_sha256": "", "task_sha256": "",
                "query_sha256": "", "search": {"three": ["a.md", "b.md", "docs/plans/p.md"], "best_place": 3, "tied": 0},
                "newest": {"three": ["docs/plans/p.md", "c.md", "d.md"], "best_place": 1}, "lot": {"three": ["e.md", "f.md", "g.md"]},
                "bm25": {"three": ["h.md", "docs/plans/p.md", "i.md"], "best_place": 2, "tied": 1},
                "documents": {}, "rows": {row: {"paragraph": "", "base": self.base, "wrong": "0" * 40, "task_file_sha256": ""}
                    for row in judge.ROWS}})
        environment = {"HOME": "/home/fixture", "USER": "fixture", "LOGNAME": "fixture", "SHELL": "/bin/sh",
            "LANG": "en_US.UTF-8", "TERM": "dumb", "PATH": "/pinned/bin:/usr/bin:/bin", "YAK_JAIL_READ": "/pinned/read"}
        self.plan = {"v": 1, "seed": judge.maker.SEED, "spec_sha256": "", "list_sha256": "",
            "worker": {"name": "script:/pinned/worker.sh", "version": "script", "model": "script"},
            "limits": {"worker_secs": 1, "check_secs": 900, "replay_secs": 11, "diagnostic_secs": 7, "lease_secs": 13},
            "inputs": {judge.maker.pin_path(self.pinned): judge.pilot.digest(self.pinned.read_bytes())},
            "items": plan_items, "order": makers_order([item["commit"] for item in plan_items]),
            "items_dir": str(Path(root) / "items"), "tasks_dir": "", "census_file": "", "spec_file": "",
            "programs": {"yak": {"path": "/pinned/yak", "sha256": ""}, "worker": {"path": "/pinned/worker.sh", "sha256": ""}},
            "environment": environment, "machine": {}}
        self.write()

    def write(self):
        raw = (json.dumps(self.plan, sort_keys=True, indent=1) + "\n").encode()
        (self.out / "plan.json").write_bytes(raw)
        (self.out / "plan.sha256").write_text(judge.pilot.digest(raw) + "\n")
        for item in self.plan["items"]:
            controls = self.out / "controls" / item["item"]
            if controls.exists():
                continue
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

    def record(self, row, outcome, turn_commit=None, item=ITEM, at_limit=None, turns_exit=None, walks_exit=0,
            attempts=()):
        """record.json as documents_run.run_turn writes it. `attempts` are (started, clock_exited) pairs."""
        order = self.order(row, item)
        directory = self.out / order["directory"]          # where the runner writes it
        directory.mkdir()
        os.symlink(self.repo, directory / "repo")
        (directory / "item.txt").write_text("%s room-item-%s script:/pinned/worker.sh\n" % (order["commit"], row))
        held = [{"directory": "rows/interrupted/%s-%d" % (name(order), k), "started": started, "clock_exited": exited}
            for k, (started, exited) in enumerate(attempts, 1)]
        (directory / "record.json").write_text(json.dumps({"n": order["n"], "commit": order["commit"], "row": row,
            "began": "", "ended": "", "load_before": "", "load_after": "", "clock_exit": 0, "outcome": outcome,
            "turn_commit": turn_commit, **({} if at_limit is None else {"at_limit": at_limit}),
            "turns_exit": (1 if outcome == "export-failed" else 0) if turns_exit is None else turns_exit,
            "walks_exit": walks_exit, "earlier_attempts": len(held), "attempts": held,
            "interrupted_attempts": sum(started and not exited for started, exited in attempts)}))
        return order


def stand_in_diagnostic(applied=True, limit=False, cases=(), turn="handed-in"):
    seen = []

    def run(directory, items, commit, patch, plan, base):
        seen.append((directory, commit, patch, plan, base))
        return {"turn": turn, "applied": applied, "limit": limit, "report": judge.read_junit(junit(cases))}
    return run, seen


def stand_in_replay(verdict, kind="handed-in", bases=None):
    seen = []
    bases = [] if bases is None else bases

    def run(directory, items, commit, patch, plan, base):
        seen.append(patch)
        bases.append(base)
        return kind, verdict
    return run, seen


class JudgeRow(unittest.TestCase):
    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.plan = Plan(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def judged(self, order, diagnostic=None, replay=None, export=None):
        listed = {"commits": [entry_for(item["commit"], JAIL_BASE) for item in self.plan.plan["items"]]}
        return judge.judge_row(self.plan.out, "items", self.plan.plan, order, diagnostic, replay, listed, export)

    def test_a_source_change_is_replayed_and_scored_over_the_frozen_cases(self):
        commit = self.plan.turn(change=True)
        order = self.plan.record("path", "handed-in", commit)
        diagnostic, seen = stand_in_diagnostic(cases=[("tests.test_a", "t1", "passed", ""),
            ("tests.test_a", "t2", "failed", "AssertionError: 1 != 2"), ("tests.test_a", "t3", "passed", ""),
            ("tests.test_a", "t7", "passed", "")])
        bases = []
        replay, replayed = stand_in_replay(False, bases=bases)
        got = self.judged(order, diagnostic, replay)
        self.assertEqual(bases, [JAIL_BASE])                       # the replay's turn begins there too
        self.assertEqual((got["scored"], got["outcome"], got["of"], got["passed"], got["failed"], got["not_run"],
            got["unfrozen"], got["room_passed"]), (True, "handed-in", 4, 2, 1, 1, 1, False))
        self.assertEqual(got["first_obstacles"], ["AssertionError: 1 != 2"])
        self.assertIn(b"peer/superyak_peer/a.py", seen[0][2])
        self.assertIs(seen[0][3], self.plan.plan)
        self.assertEqual(replayed, [seen[0][2]])
        self.assertEqual(set(got) - {"n", "commit", "row"}, {"outcome", "scored", "of", "passed", "failed", "error",
            "skipped", "not_run", "unfrozen", "collection_errors", "first_obstacles", "room_passed", "matching_named",
            "offered_named", "of_new", "passed_new", "at_limit", "exported_again"})
        # The new cases are t2, t3 and t4 (t1 passes on the parent); t3 passes here.
        self.assertEqual((got["of_new"], got["passed_new"]), (3, 1))
        self.assertEqual(seen[0][4], JAIL_BASE)                   # the diagnostic's turn begins on the list's base

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
        self.assertEqual((got["of"], got["not_run"], got["passed"], got["unfrozen"]), (4, 4, 0, 0))

    def unscored(self, row, diagnostic, replay=None):
        return self.judged(self.plan.record(row, "handed-in", self.plan.turn(change=True)), diagnostic, replay)

    def test_a_diagnostic_turn_that_ends_otherwise_is_its_own_unscored_outcome(self):
        for row, turn, outcome in (("nothing-1", "limit", "diagnostic-limit"),
                ("nothing-2", "clock-failed", "diagnostic-clock-failed"),
                ("exists", "no-hand-in", "diagnostic-no-hand-in"), ("path", "no-status", "diagnostic-no-status")):
            diagnostic, _ = stand_in_diagnostic(applied=None, limit=turn == "limit", turn=turn)
            replay, replayed = stand_in_replay(True)
            got = self.unscored(row, diagnostic, replay)
            self.assertEqual((got["scored"], got["outcome"], got["of"], got["not_run"], got["room_passed"]),
                (False, outcome, 4, 4, None), turn)
            self.assertEqual(replayed, [])

    def test_a_replay_at_its_limit_or_with_a_failed_clock_is_unscored_and_keeps_its_counts(self):
        for row, kind in (("search", "limit"), ("newest", "clock-failed")):
            diagnostic, _ = stand_in_diagnostic(cases=[("tests.test_a", "t1", "passed", "")])
            replay, replayed = stand_in_replay(None, kind)
            got = self.unscored(row, diagnostic, replay)
            self.assertEqual((got["scored"], got["outcome"], got["of"], got["passed"], got["not_run"], got["room_passed"]),
                (False, "replay-" + kind, 4, 1, 3, None))
            self.assertEqual(len(replayed), 1)

    def test_a_replay_with_no_hand_in_is_scored_with_no_verdict(self):
        diagnostic, _ = stand_in_diagnostic(cases=[("tests.test_a", "t1", "passed", "")])
        replay, _ = stand_in_replay(None, "no-hand-in")
        got = self.unscored("lot", diagnostic, replay)
        self.assertEqual((got["scored"], got["outcome"], got["passed"], got["room_passed"]), (True, "handed-in", 1, None))

    def test_inconsistent_records_are_refused(self):
        with self.assertRaises(Refused):
            self.judged(self.plan.record("nothing-1", "handed-in", None))
        with self.assertRaises(Refused):
            self.judged(self.plan.record("nothing-2", "no-hand-in", self.plan.base))
        with self.assertRaises(Refused):
            self.judged(self.plan.record("exists", "finished"))
        order = self.plan.record("path", "no-hand-in")
        record = self.plan.out / order["directory"] / "record.json"
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
            # --rows 1 judges the earlier of the two in the plan's order; the later is left for the next run.
            early, late = sorted(NOTHING, key=lambda row: self.plan.order(row)["n"])
            self.assertEqual(sorted(os.listdir(self.plan.out / "judged")), [name(self.plan.order(early))])
            interrupted = self.plan.out / "judged" / name(self.plan.order(late))
            interrupted.mkdir()
            (interrupted / "partial").write_text("")
            judge.judge(self.plan.out, "items")
            self.assertTrue((interrupted / "score.json").exists())
            self.assertFalse((interrupted / "partial").exists())
            self.assertEqual(os.listdir(self.plan.out / "judged" / "interrupted"), [interrupted.name + "-1"])
            first = (self.plan.out / "judged" / name(self.plan.order(early)) / "score.json").read_bytes()
            judge.judge(self.plan.out, "items")
            self.assertEqual(sorted(os.listdir(self.plan.out / "judged")), sorted(
                [name(self.plan.order(row)) for row in NOTHING] + ["interrupted"]))
            self.assertEqual((self.plan.out / "judged" / name(self.plan.order(early)) / "score.json")
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

    def test_the_makers_load_plan_refuses_a_changed_or_missing_input(self):
        self.assertIs(judge.load_plan, judge.maker.load_plan)
        self.assertEqual(judge.load_plan(self.plan.out)["order"], self.plan.plan["order"])
        self.plan.pinned.write_text("changed\n")
        with self.assertRaisesRegex(Refused, "input changed"):
            judge.load_plan(self.plan.out)
        self.plan.pinned.unlink()
        with self.assertRaisesRegex(Refused, "input missing"):
            judge.load_plan(self.plan.out)
        self.plan.pinned.write_text("a pinned input\n")
        with mock.patch.object(judge, "check_items", lambda plan, items: None):
            self.plan.pinned.write_text("changed again\n")
            for stage in (lambda: judge.judge(self.plan.out, "items"), lambda: judge.make_report(self.plan.out),
                    lambda: judge.controls(self.plan.out, "items")):
                with self.assertRaisesRegex(Refused, "input changed"):
                    stage()

    def test_the_directory_is_the_makers_rows_path(self):
        order = self.plan.order("path")
        self.assertTrue(order["directory"].startswith("rows/"))
        self.assertEqual(judge.row_dir(self.plan.out, order), self.plan.out / order["directory"])
        self.assertEqual(judge.judged_dir(self.plan.out, order), self.plan.out / "judged" / name(order))
        for wrong in (name(order), "rows/" + name(order) + "/x", "rows/../" + name(order), "judged/" + name(order),
                "rows/%03d-%s-%s" % (order["n"] + 1, order["item"], order["row"])):
            with self.assertRaises(Refused):
                judge.row_name(dict(order, directory=wrong))


def stand_in_export(turns=None, turns_exit=0, walk=None, walks_exit=0):
    """In the room's place for `item turns|walks --json` run again: writes what the room would print, returns its code."""
    seen = []

    def run(out, plan, order, judged, what):
        seen.append(what)
        Path(judged).mkdir(parents=True, exist_ok=True)
        if what == "turns":
            (Path(judged) / "turns.json").write_text("" if turns is None else json.dumps(turns))
            return turns_exit
        (Path(judged) / "walks.jsonl").write_text("" if walk is None else json.dumps(walk) + "\n")
        return walks_exit
    return run, seen


class ExportedAgain(unittest.TestCase):
    """A failed turns or walks export is exported again from the row's room, never run again."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.plan = Plan(self.temporary.name)

    def tearDown(self):
        self.temporary.cleanup()

    def judged(self, order, export, diagnostic=None, replay=None):
        listed = {"commits": [entry_for(self.plan.plan["items"][0]["commit"], JAIL_BASE)]}
        return judge.judge_row(self.plan.out, "items", self.plan.plan, order, diagnostic, replay, listed, export)

    def test_a_failed_turns_export_is_decided_from_the_turns_exported_again(self):
        commit = self.plan.turn(change=True)
        export, seen = stand_in_export(turns=[{"commit": commit, "passed": True, "measured": {"ended": "exited"}}])
        diagnostic, ran = stand_in_diagnostic(cases=[("tests.test_a", "t1", "passed", "")])
        replay, _ = stand_in_replay(True)
        got = self.judged(self.plan.record("path", "export-failed"), export, diagnostic, replay)
        self.assertEqual(seen, ["turns"])                          # walks_exit 0: the walk is the row's own
        self.assertEqual((got["outcome"], got["scored"], got["room_passed"], got["at_limit"], got["exported_again"]),
            ("handed-in", True, True, False, {"turns": 0}))
        self.assertEqual(len(ran), 1)

    def test_the_base_decides_a_turns_export_and_a_limit_is_kept(self):
        export, _ = stand_in_export(turns=[{"commit": self.plan.base, "passed": False, "measured": {"ended": "exited"}}])
        got = self.judged(self.plan.record("lot", "export-failed"), export)
        self.assertEqual((got["outcome"], got["scored"], got["passed"]), ("no-hand-in", True, 1))
        export, _ = stand_in_export(turns=[{"commit": None, "passed": None, "measured": {"ended": "timed_out"}}])
        got = self.judged(self.plan.record("newest", "export-failed"), export)
        self.assertEqual((got["outcome"], got["scored"], got["at_limit"]), ("limit", True, True))
        export, _ = stand_in_export(turns=[{"commit": None, "passed": None, "measured": {"ended": "timed_out"}}] * 2)
        got = self.judged(self.plan.record("exists", "export-failed"), export)
        self.assertEqual((got["outcome"], got["scored"], got["at_limit"]), ("clock-failed", False, False))

    def test_a_turns_export_that_fails_again_has_no_score(self):
        export, seen = stand_in_export(turns_exit=2, walk={"steps": []})
        got = self.judged(self.plan.record("search", "export-failed", walks_exit=1), export)
        self.assertEqual(seen, ["turns", "walks"])
        self.assertEqual((got["outcome"], got["scored"], got["of"], got["not_run"], got["of_new"], got["passed_new"]),
            ("export-failed", False, 4, 4, 3, 0))
        self.assertEqual(got["exported_again"], {"turns": 2, "walks": 0})
        self.assertEqual((got["matching_named"], got["offered_named"]), ({}, []))

    def test_a_walk_that_cannot_be_read_again_is_null_not_empty(self):
        export, seen = stand_in_export(walks_exit=1)
        got = self.judged(self.plan.record("nothing-1", "no-hand-in", walks_exit=3), export)
        self.assertEqual(seen, ["walks"])
        self.assertEqual((got["outcome"], got["scored"], got["matching_named"], got["offered_named"]),
            ("no-hand-in", True, None, None))
        walk = {"steps": [{"seq": 0, "seen_ms": 1000, "named": [["docs/plans/p.md", "read"]]}]}
        export, _ = stand_in_export(walk=walk)
        got = self.judged(self.plan.record("bm25", "no-hand-in", walks_exit=1), export)
        self.assertEqual((got["matching_named"], got["offered_named"]),
            ({"docs/plans/p.md": {"step": 0, "seconds": 1.0}}, ["docs/plans/p.md"]))

    def test_records_whose_exports_disagree_are_refused(self):
        export, _ = stand_in_export()
        for outcome, turns_exit in (("export-failed", 0), ("no-hand-in", 1)):
            order = self.plan.record({"export-failed": "exists", "no-hand-in": "nothing-2"}[outcome], outcome,
                turns_exit=turns_exit)
            with self.assertRaisesRegex(Refused, "turns_exit"):
                self.judged(order, export)
        order = self.plan.record("nothing-1", "no-hand-in", walks_exit=None)
        with self.assertRaisesRegex(Refused, "walks_exit"):
            self.judged(order, export)
        order = self.plan.record("lot", "export-failed", turn_commit=self.plan.base)
        with self.assertRaisesRegex(Refused, "yet turn_commit"):
            self.judged(order, export)

    def test_the_rooms_exports_run_with_the_plans_program_and_environment(self):
        order = self.plan.record("path", "export-failed")
        judged = judge.judged_dir(self.plan.out, order)
        judged.mkdir(parents=True)
        seen = []

        def run(argv, env=None, capture_output=None):
            seen.append((argv, env))
            return subprocess.CompletedProcess(argv, 5, b"partial", b"no room")
        with mock.patch.object(judge.runner.subprocess, "run", run), mock.patch.dict(os.environ, {"YAK_LEAK": "1"}):
            self.assertEqual(judge.export_again(self.plan.out, self.plan.plan, order, judged, "turns"), 5)
            self.assertEqual(judge.export_again(self.plan.out, self.plan.plan, order, judged, "walks"), 5)
        room = str(self.plan.out / order["directory"] / "room")
        self.assertEqual([argv for argv, _ in seen], [["/pinned/yak", "--room", room, "item", what, "room-item-path",
            "--json"] for what in ("turns", "walks")])
        self.assertEqual(seen[0][1], self.plan.plan["environment"])
        self.assertEqual(((judged / "turns.json").read_bytes(), (judged / "walks.err").read_bytes()),
            (b"partial", b"no room"))
        (self.plan.out / order["directory"] / "item.txt").write_text("%s\n" % order["commit"])
        with self.assertRaisesRegex(Refused, "item.txt"):
            judge.export_again(self.plan.out, self.plan.plan, order, judged, "turns")
        (self.plan.out / order["directory"] / "item.txt").write_text("%s id w\n" % ("0" * 40))
        with self.assertRaisesRegex(Refused, "item.txt"):
            judge.export_again(self.plan.out, self.plan.plan, order, judged, "turns")

    def test_judge_exports_again_with_the_room_and_reports_the_recovered_limit(self):
        self.plan.record("nothing-1", "export-failed")

        def export(argv, env=None, capture_output=None):
            out = json.dumps([{"commit": None, "passed": None, "measured": {"ended": "timed_out"}}]).encode() \
                if argv[4] == "turns" else b""
            return subprocess.CompletedProcess(argv, 0, out, b"")
        with mock.patch.object(judge, "check_items", lambda held, items: None), \
                mock.patch.object(judge.runner.subprocess, "run", export):
            judge.judge(self.plan.out, "items")
        report = judge.make_report(self.plan.out)
        self.assertEqual(report["rows"]["outcomes"], {"export-failed": 1})
        self.assertEqual(report["rows"]["judged_outcomes"], {"limit": 1})
        self.assertEqual(report["rows"]["at_limit"]["nothing-1"], 1)


class RefusedReport(unittest.TestCase):
    """A report the judge refuses is a row with no score, and the other rows are judged."""

    def test_a_refused_report_is_a_row_with_no_score_and_judging_goes_on(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary)
            commit = plan.turn(change=True)
            first, second = sorted(("path", "lot"), key=lambda row: plan.order(row)["n"])
            plan.record(first, "handed-in", commit)
            plan.record(second, "handed-in", commit)
            calls = []

            def diagnostic(directory, items, held, patch, plan_, base):
                calls.append(directory)
                if len(calls) == 1:
                    raise judge.ReportRefused("the JUnit report declares a DOCTYPE or an entity")
                return {"turn": "handed-in", "applied": True, "limit": False,
                    "report": judge.read_junit(junit([("tests.test_a", "t1", "passed", "")]))}
            replay, _ = stand_in_replay(True)
            listed = {"commits": [entry_for(plan.plan["items"][0]["commit"], JAIL_BASE)]}
            with mock.patch.object(judge, "check_items", lambda held, items: listed), \
                    mock.patch.object(judge, "diagnostic", diagnostic), mock.patch.object(judge, "replay", replay):
                judge.judge(plan.out, "items")
            refused = json.loads((plan.out / "judged" / name(plan.order(first)) / "score.json").read_text())
            self.assertEqual((refused["outcome"], refused["scored"], refused["of"], refused["not_run"], refused["reason"]),
                ("report-refused", False, 4, 4, "the JUnit report declares a DOCTYPE or an entity"))
            other = json.loads((plan.out / "judged" / name(plan.order(second)) / "score.json").read_text())
            self.assertEqual((other["outcome"], other["scored"], other["passed"]), ("handed-in", True, 1))
            report = judge.make_report(plan.out)
            self.assertEqual(report["rows"]["unscored"], {"report-refused": 1})
            self.assertIn("Rows with no score, by outcome: report-refused 1.", judge.report_markdown(report))

    def test_what_a_turn_commits_is_refused_as_a_report_and_a_room_failure_is_not(self):
        for data in (b"<!DOCTYPE t><testsuite/>", b"\xff", b"<testsuite>", "<t a='\x01'/>".encode()):
            with self.assertRaises(judge.ReportRefused):
                judge.read_junit(data)
        self.assertTrue(issubclass(judge.ReportRefused, Refused))
        with tempfile.TemporaryDirectory() as temporary:
            directory = Path(temporary)

            def turn(where, items, commit, worker_dir, plan, secs):
                repo = Path(where) / "repo"
                repo.mkdir(parents=True)
                git(repo, "init", "-q")
                (repo / "jail-status.json").write_text(status)
                git(repo, "add", "-A")
                git(repo, "commit", "-q", "-m", "hand-in")
                room_turns(where, git(repo, "rev-parse", "HEAD"), None)
            for k, status in enumerate(("not json", "[1]")):
                with mock.patch.object(judge, "jail_turn", turn):
                    with self.assertRaises(judge.ReportRefused):
                        judge.diagnostic(directory / str(k), "items", "c" * 40, b"x", {"limits": {"diagnostic_secs": 1}},
                            "b" * 40)


class Bm25(unittest.TestCase):
    def test_one_plan_shape_only(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary)
            self.assertIs(judge.check_shape(plan.plan), plan.plan)
            self.assertEqual(judge.ROWS[-1], "bm25")
            self.assertEqual(judge.RULE_ROWS, ("nothing-1", "nothing-2", "search", "newest", "lot"))
            seven = json.loads(json.dumps(plan.plan))
            seven["order"] = [held for held in seven["order"] if held["row"] != "bm25"]
            with self.assertRaisesRegex(Refused, "each item's 8 rows once"):
                judge.check_shape(seven)
            for item in seven["items"]:
                del item["rows"]["bm25"]
            with self.assertRaisesRegex(Refused, "the plan's rows are"):
                judge.check_shape(seven)
            twice = json.loads(json.dumps(plan.plan))
            twice["order"] = twice["order"] + twice["order"][:1]
            with self.assertRaisesRegex(Refused, "rows once"):
                judge.check_shape(twice)
            for broken in ({}, {"three": ["a", "b"], "best_place": 1, "tied": 0},
                    {"three": ["a", "b", "c"], "best_place": "1", "tied": 0},
                    {"three": ["a", "b", "c"], "best_place": 1, "tied": None}, None, {"three": "abc", "best_place": 1,
                    "tied": 0}):
                held = json.loads(json.dumps(plan.plan))
                held["items"][0]["bm25"] = broken
                with self.assertRaisesRegex(Refused, "bm25 member"):
                    judge.check_shape(held)
            del held["items"][0]["bm25"]
            with self.assertRaisesRegex(Refused, "bm25 member"):
                judge.check_shape(held)

    def test_bm25_offers_its_three_and_is_tallied_but_not_ruled(self):
        item = {"matching": ["p.md"], "direct_path": "p.md", "bm25": {"three": ["x.md", "p.md", "y.md"]}}
        self.assertEqual(judge.offered_paths(item, "bm25"), ["x.md", "p.md", "y.md"])
        plan, scores, items, plans = rule_inputs(higher_search=5)
        for held in scores.values():
            held["bm25"] = score(0, 2, "report-refused", False)
        self.assertEqual(judge.spending_rule(plan, scores, items, plans)["decision"], "not worth one")
        reading = judge.item_reading({"nothing-1": score(1, 4), "nothing-2": score(1, 4), "bm25": score(4, 4)})
        self.assertEqual(reading["conditions"]["bm25"]["class"], "higher")
        self.assertEqual(judge.tally({"i": reading}, "bm25"), {"higher": 1, "lower": 0, "within": 0, "on": 1})


class Unscored(unittest.TestCase):
    def test_every_unscored_outcome_is_in_one_place_and_a_scored_one_is_not(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary)
            listed = {"commits": [entry_for(plan.plan["items"][0]["commit"], JAIL_BASE)]}
            seen = set()
            for row, turn, kind in (("nothing-1", "limit", "handed-in"), ("nothing-2", "clock-failed", "handed-in"),
                    ("exists", "no-hand-in", "handed-in"), ("path", "no-status", "handed-in"),
                    ("search", "handed-in", "limit"), ("newest", "handed-in", "clock-failed")):
                diagnostic, _ = stand_in_diagnostic(limit=turn == "limit", turn=turn)
                replay, _ = stand_in_replay(None, kind)
                got = judge.judge_row(plan.out, "items", plan.plan, plan.record(row, "handed-in", plan.turn(change=True)),
                    diagnostic, replay, listed)
                self.assertFalse(got["scored"])
                seen.add(got["outcome"])
            self.assertTrue(seen <= set(judge.UNSCORED), seen)
            self.assertEqual(len(seen), 6)
            for outcome in ("handed-in", "no-hand-in", "limit", "unchanged-source"):
                self.assertNotIn(outcome, judge.UNSCORED)
            with mock.patch.object(judge, "UNSCORED", judge.UNSCORED + ("no-hand-in",)):
                with self.assertRaisesRegex(Refused, "with a score"):
                    judge.judge_row(plan.out, "items", plan.plan, plan.record("lot", "no-hand-in"), None, None, listed)
            with mock.patch.object(judge, "UNSCORED", tuple(held for held in judge.UNSCORED if held != "clock-failed")):
                with self.assertRaisesRegex(Refused, "without a score"):
                    judge.judge_row(plan.out, "items", plan.plan, plan.record("bm25", "clock-failed"), None, None,
                        listed)


NOTHING = judge.NOTHING


def name(order):
    return Path(order["directory"]).name


class Report(unittest.TestCase):
    def test_the_reports_counts_equal_the_records(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary, items=2)
            plan.record("nothing-1", "no-hand-in", attempts=[(True, False)])
            plan.record("nothing-2", "no-hand-in", attempts=[(True, True), (False, False)])
            plan.record("path", "clock-failed", at_limit=False)
            plan.record("lot", "handed-in", plan.turn(change=False), at_limit=True)
            plan.record("bm25", "limit", at_limit=True)
            plan.record("nothing-1", "limit", item="1111111111", attempts=[(True, False), (True, False)])
            (plan.out / "rows" / "interrupted" / "x-1").mkdir(parents=True)     # directories count for nothing now
            with mock.patch.object(judge, "check_items", lambda held, items: None):
                judge.judge(plan.out, "items")
            plan.record("exists", "no-hand-in")
            report = judge.make_report(plan.out)
            self.assertEqual(report["rows"]["unjudged"], [plan.order("exists")["directory"]])
            (plan.out / plan.order("exists")["directory"] / "record.json").unlink()
            report = judge.make_report(plan.out)
            self.assertEqual(report["rows"]["planned"], 16)
            self.assertEqual(report["rows"]["recorded"], 6)
            self.assertEqual(report["rows"]["judged"], 6)
            self.assertEqual(report["rows"]["outcomes"], {"no-hand-in": 2, "clock-failed": 1, "limit": 2, "handed-in": 1})
            self.assertEqual(report["rows"]["judged_outcomes"], {"no-hand-in": 2, "clock-failed": 1, "limit": 2,
                "unchanged-source": 1})
            self.assertEqual(report["rows"]["unscored"], {"clock-failed": 1})
            self.assertEqual(report["rows"]["at_limit"], dict({row: 0 for row in judge.ROWS}, lot=1, bm25=1))
            self.assertEqual(report["rows"]["interrupted"], dict({row: 0 for row in judge.ROWS}, **{"nothing-1": 3}))
            self.assertEqual(report["rows"]["earlier_attempts"], dict({row: 0 for row in judge.ROWS},
                **{"nothing-1": 3, "nothing-2": 2}))
            self.assertEqual(report["items"][ITEM]["b"], 0.25)
            self.assertEqual(report["items"][ITEM]["conditions"]["bm25"], {"o": 0.25, "d": 0.0, "class": "within"})
            self.assertEqual(report["items_new"][ITEM]["b"], 0.0)          # the parent passes none of the new cases
            self.assertIsNone(report["items"]["1111111111"])
            self.assertEqual(report["probed"], ["1111111111"])
            self.assertEqual(report["rule"]["decision"], "suspended")
            self.assertIn(ITEM + " search", report["rule"]["missing"])
            self.assertFalse([held for held in report["rule"]["missing"] if "bm25" in held])
            self.assertEqual(report["parent"][ITEM], {"passed": 1, "of": 4, "of_new": 3})
            self.assertEqual(report["places"][ITEM], {"search": 3, "search_tied": 0, "newest": 1, "bm25": 2,
                "bm25_tied": 1})
            judge.write_report(plan.out)
            text = (plan.out / "report.md").read_text()
            self.assertIn("Suspended", text)
            self.assertIn("from the records: nothing-1 3, nothing-2 0, exists 0, path 0, search 0, newest 0, lot 0, "
                "bm25 0; earlier attempts of any kind: nothing-1 3, nothing-2 2,", text)
            self.assertIn("Rows with no score, by outcome: clock-failed 1.", text)
            self.assertIn("| 1111111111 | p1 | 1 of 4 | 4 | 3 | no baseline |" + " |" * 9 + "\n", text)
            for line in text.splitlines():
                if (line.startswith("| a1b2") or line.startswith("| 1111")) and " of 4 |" in line:
                    self.assertEqual(line.count("|"), 16, line)
            self.assertEqual(text.count(judge.BM25_SENTENCE), 2)
            # What the spec's section 7 requires before the tables, each once, and before the first table.
            first_table = text.index("\n| ")
            for sentence in (judge.BM25_SENTENCE, judge.FORGE_SENTENCE, judge.REPLAY_SENTENCE):
                self.assertIn("four orderings", judge.BM25_SENTENCE)
                self.assertLess(text.index("- " + sentence), first_table, sentence)
            self.assertEqual((text.count(judge.FORGE_SENTENCE), text.count(judge.REPLAY_SENTENCE)), (1, 1))
            # In every table the second search carries how it was chosen; no other row does.
            self.assertEqual((judge.label("bm25"), judge.label("search")), ("bm25 (selected after retrieval counts)", "search"))
            for line in text.splitlines():
                if line.startswith("| bm25"):
                    self.assertTrue(line.startswith("| %s |" % judge.BM25_LABEL), line)
            self.assertEqual(sum(1 for line in text.splitlines() if line.startswith("| %s |" % judge.BM25_LABEL)), 2)
            for head in (line for line in text.splitlines() if line.startswith("| item | plan |") or line.startswith("| plan |")):
                self.assertIn("%s d (class)" % judge.BM25_LABEL if head.startswith("| item") else "%s D, R (class)"
                    % judge.BM25_LABEL, head)
            self.assertIn("| item | search: best place | tied | %s: best place |" % judge.BM25_LABEL, text)
            self.assertIn("Plans higher, lower, within, of those read: ", text)
            self.assertIn("; %s " % judge.BM25_LABEL, text)
            self.assertIn("| %s | 3 | 0 | 2 | 1 | 1 |" % ITEM, text)
            self.assertEqual(json.loads((plan.out / "report.json").read_text())["rows"]["recorded"], 6)
            self.assertIn("by condition: nothing-1 0, nothing-2 0, exists 0, path 0, search 0, newest 0, lot 1, bm25 1.",
                text)
            # The attempt counts must agree with the attempts the record lists.
            record = plan.out / plan.order("nothing-2")["directory"] / "record.json"
            held = json.loads(record.read_text())
            record.write_text(json.dumps(dict(held, interrupted_attempts=1)))
            with self.assertRaisesRegex(Refused, "attempt counts"):
                judge.make_report(plan.out)
            record.write_text(json.dumps(dict(held, earlier_attempts=1)))
            with self.assertRaisesRegex(Refused, "attempt counts"):
                judge.make_report(plan.out)
            for attempts in (None, [1]):
                record.write_text(json.dumps(dict(held, attempts=attempts, earlier_attempts=1, interrupted_attempts=0)))
                with self.assertRaisesRegex(Refused, "no attempts list"):
                    judge.make_report(plan.out)

    def test_the_shares_over_the_new_cases(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary, items=2)
            other = "1111111111"
            commit = plan.plan["items"][1]["commit"]
            (plan.out / "controls" / other / "parent.json").write_text(json.dumps({"commit": commit,
                "passed": frozen_ids("t1", "t2", "t3", "t4")}))       # every frozen case passes on its parent
            for item in (ITEM, other):
                for row in ("nothing-1", "nothing-2", "search"):
                    plan.record(row, "no-hand-in", item=item)
            with mock.patch.object(judge, "check_items", lambda held, items: None):
                judge.judge(plan.out, "items")
            scored = json.loads((plan.out / "judged" / name(plan.order("search", other)) / "score.json").read_text())
            self.assertEqual((scored["of"], scored["of_new"], scored["passed_new"]), (4, 0, 0))
            ruled = []
            original = judge.spending_rule

            def spy(plan_, scores, items_tally, plans_tally):
                ruled.append((items_tally, plans_tally))
                return original(plan_, scores, items_tally, plans_tally)
            with mock.patch.object(judge, "spending_rule", spy):
                report = judge.make_report(plan.out)
            self.assertEqual(ruled, [(report["tally"], report["plans_tally"])])
            self.assertNotEqual(report["tally"], report["tally_new"])
            self.assertEqual(report["parent"][other], {"passed": 4, "of": 4, "of_new": 0})
            self.assertIsNotNone(report["items"][other])
            self.assertIsNone(report["items_new"][other])               # of_new 0: left out of the new reading
            self.assertEqual((report["tally"]["search"]["on"], report["tally_new"]["search"]["on"]), (2, 1))
            self.assertEqual(report["tally_without_probed_new"]["search"]["on"], 1)
            self.assertEqual(report["figures_on_new"]["search"], {"plans": 0, "items": 0})   # plan p1 is not read
            self.assertEqual(report["plans_new"]["p0"]["conditions"]["search"]["on"], 1)
            for key in ("plans_tally_new", "figures_new", "plans_without_probed_new", "plans_tally_without_probed_new",
                    "figures_without_probed_new", "figures_on_without_probed_new"):
                self.assertIn(key, report)
            text = judge.report_markdown(report)
            self.assertIn("## Each condition over the items (shares of the new cases", text)
            self.assertIn("## By plan, without the probed item (shares of the new cases", text)
            self.assertIn("| %s (probed) | p1 | 4 of 4 | 4 | 0 |" % other, text)
            # With the probed item's new cases read too, the tally without it still leaves it out.
            (plan.out / "controls" / other / "parent.json").write_text(json.dumps({"commit": commit,
                "passed": frozen_ids("t1")}))
            shutil.rmtree(plan.out / "judged")
            with mock.patch.object(judge, "check_items", lambda held, items: None):
                judge.judge(plan.out, "items")
            report = judge.make_report(plan.out)
            self.assertEqual((report["tally_new"]["search"]["on"], report["tally_without_probed_new"]["search"]["on"]),
                (2, 1))

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
            (plan.out / "judged" / name(order)).mkdir(parents=True)
            (plan.out / "judged" / name(order) / "score.json").write_text(json.dumps({"n": order["n"] + 1,
                "commit": order["commit"], "row": "path"}))
            with self.assertRaises(Refused):
                judge.make_report(plan.out)


def room_turns(directory, commit, verdict, kind="handed-in"):
    """turns.json as `item turns --json` prints it and clock.exit as pilot_driver's turn writes it (a guess at the
    real room's shape, the runner's: a list of one attempt with "commit", "passed" and "measured": {"ended"})."""
    directory = Path(directory)
    turns = {"handed-in": [{"commit": commit, "passed": verdict, "measured": {"ended": "exited"}}],
        "limit": [{"commit": None, "passed": None, "measured": {"ended": "timed_out"}}],
        "no-hand-in": [{"commit": None, "passed": None, "measured": {"ended": "exited"}}],
        "clock-failed": []}[kind]
    (directory / "turns.json").write_text(json.dumps(turns))
    (directory / "clock.exit").write_text("0\n" if kind in ("handed-in", "no-hand-in") else "7\n")


class StandInJail:
    """In the room's place: a turn directory with a repository whose one commit holds what the script worker would
    hand in, and the room's turns.json and clock.exit (room_turns). `kinds` names how a turn ends, by its place in
    the calls (0: the reference's diagnostic, 1: its replay, 2: the parent's diagnostic)."""

    def __init__(self, reference_cases, parent_cases, verdict=True, applied=True, limit=False, kinds=None):
        self.reference_cases, self.parent_cases = reference_cases, parent_cases
        self.verdict, self.applied, self.limit = verdict, applied, limit
        self.kinds = kinds or {}
        self.calls = []

    def __call__(self, directory, items, commit, worker_dir, plan, secs):
        directory, worker_dir = Path(directory), Path(worker_dir)
        self.calls.append((directory, commit, secs))
        kind = self.kinds.get(len(self.calls) - 1, "handed-in")
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
        room_turns(directory, git(repo, "rev-parse", "HEAD"), self.verdict if not diagnostic else False, kind)


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
        self.assertEqual(judge.parent_score(controls, cases["cases"], [])["passed"], 1)
        # The plan's limits, given to each turn: the diagnostic's tests' limit and its margin, the replay's.
        self.assertEqual([secs for _, _, secs in jail.calls], [7 + judge.DIAGNOSTIC_MARGIN_SECS, 11,
            7 + judge.DIAGNOSTIC_MARGIN_SECS])
        # Both files hold the item's whole commit id, and the runner accepts them.
        item = self.plan.plan["items"][0]
        self.assertEqual((cases["commit"], json.loads((controls / "parent.json").read_text())["commit"]),
            (item["commit"], item["commit"]))
        self.assertEqual(len(item["commit"]), 40)
        judge.runner.controls_ready(self.plan.out, item)
        self.run_controls(jail)                                   # a made control is not made again
        self.assertEqual(len(jail.calls), 3)

    def stopped(self, jail):
        self.run_controls(jail)
        controls = self.plan.out / "controls" / ITEM
        self.assertFalse((controls / "parent.json").exists())
        return json.loads((controls / "stopped.json").read_text())["reason"]

    def refusing(self, nth):
        """read_junit as it is, but its nth call in a run of controls refuses the report (1: the reference's, 2: the
        parent's)."""
        original, calls = judge.read_junit, []

        def read(data):
            calls.append(data)
            if len(calls) == nth:
                raise judge.ReportRefused("the JUnit report declares a DOCTYPE or an entity")
            return original(data)
        return mock.patch.object(judge, "read_junit", read)

    def test_a_refused_report_in_a_control_stops_the_item_with_its_reason(self):
        for nth, whose, turns in ((1, "reference", 1), (2, "parent", 3)):
            jail = StandInJail([("tests.test_a", "t1", "passed", "")], [("tests.test_a", "t1", "passed", "")])
            with self.refusing(nth):
                self.assertEqual(self.run_controls(jail), 0)
            controls = self.plan.out / "controls" / ITEM
            self.assertEqual(json.loads((controls / "stopped.json").read_text()), {"commit":
                self.plan.plan["items"][0]["commit"], "reason": "the %s's report was refused: the JUnit report "
                "declares a DOCTYPE or an entity" % whose})
            self.assertFalse((controls / "parent.json").exists())
            self.assertEqual(len(jail.calls), turns)
            with self.assertRaises(judge.runner.Refused):          # the runner starts no turn of a stopped item
                judge.runner.controls_ready(self.plan.out, self.plan.plan["items"][0])
            shutil.rmtree(controls)

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

    def test_turns_that_end_otherwise_stop_the_item_and_are_not_refusals(self):
        one = [("tests.test_a", "t1", "passed", "")]
        for kinds, reason in (({0: "limit"}, "the reference's diagnostic reached its limit"),
                ({0: "clock-failed"}, "the reference's diagnostic turn ended clock-failed"),
                ({0: "no-hand-in"}, "the reference's diagnostic turn ended no-hand-in"),
                ({1: "limit"}, "the reference's replay turn ended limit"),
                ({1: "clock-failed"}, "the reference's replay turn ended clock-failed"),
                ({1: "no-hand-in"}, "the room's verdict on the reference by replay is null"),
                ({2: "limit"}, "the parent's run reached its limit"),
                ({2: "clock-failed"}, "the parent's turn ended clock-failed")):
            shutil.rmtree(self.plan.out / "controls" / ITEM)
            self.assertEqual(self.stopped(StandInJail(one, one, kinds=kinds)), reason, kinds)

    def test_a_controls_turn_is_read_against_the_item_lists_base(self):
        base = self.plan.base

        def jail(directory, items, commit, worker_dir, plan, secs):
            Path(directory).mkdir(parents=True)
            (Path(directory) / "turns.json").write_text(json.dumps([{"commit": base, "passed": False,
                "measured": {"ended": "exited"}}]))
        self.assertEqual(self.stopped(jail), "the reference's diagnostic turn ended no-hand-in")

    def test_a_stopped_item_is_not_judged_and_is_reported(self):
        self.stopped(StandInJail([("tests.test_a", "t1", "failed", "x")], []))
        self.plan.record("nothing-2", "no-hand-in")
        judge.judge(self.plan.out, self.items)
        self.assertFalse((self.plan.out / "judged" / name(self.plan.order("nothing-2"))).exists())
        self.assertIn("no case passes", judge.make_report(self.plan.out)["controls_stopped"][ITEM])

    def test_an_item_stopped_by_its_replay_is_not_judged(self):
        self.stopped(StandInJail([("tests.test_a", "t1", "passed", "")], [], verdict=False))
        self.assertTrue((self.plan.out / "controls" / ITEM / "cases.json").exists())
        self.plan.record("nothing-1", "no-hand-in")
        judge.judge(self.plan.out, self.items)
        self.assertFalse((self.plan.out / "judged" / name(self.plan.order("nothing-1"))).exists())
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
        self.head = git(self.base, "rev-parse", "HEAD")

    def tearDown(self):
        judge.jail_turn = self.original
        self.temporary.cleanup()

    def turn(self, directory, items, commit, worker_dir, plan, secs):
        directory = Path(directory)
        directory.mkdir(parents=True)
        subprocess.run(["git", "clone", "-q", str(self.base), str(directory / "repo")], check=True)
        subprocess.run(["sh", str(Path(worker_dir) / "worker.sh")], cwd=directory / "repo", capture_output=True)
        room_turns(directory, git(directory / "repo", "rev-parse", "HEAD"), None)

    def test_a_change_is_applied_and_its_tests_read_back(self):
        ran = judge.diagnostic(Path(self.temporary.name) / "d1", "items", "c" * 40, self.patch, {"limits": {"diagnostic_secs": 20}}, self.head)
        self.assertEqual((ran["applied"], ran["limit"]), (True, False))
        self.assertEqual(ran["report"]["cases"], {"tests.test_p::t1": ("passed", ""), "tests.test_p::t2": ("passed", "")})

    def test_no_change_runs_the_tests_on_the_base(self):
        ran = judge.diagnostic(Path(self.temporary.name) / "d2", "items", "c" * 40, b"", {"limits": {"diagnostic_secs": 20}}, self.head)
        self.assertEqual(ran["applied"], True)
        self.assertEqual(ran["report"]["cases"]["tests.test_p::t2"], ("failed", "AssertionError: y"))

    def test_a_change_that_does_not_apply_runs_no_test(self):
        ran = judge.diagnostic(Path(self.temporary.name) / "d3", "items", "c" * 40, self.patch.replace(b"x = 1", b"z = 9"), {"limits": {"diagnostic_secs": 20}}, self.head)
        self.assertEqual((ran["applied"], ran["report"]["cases"]), (False, {}))

    def test_the_tests_limit_is_kept(self):
        (self.base / "peer" / "superyak_peer" / "slow").write_text("")
        git(self.base, "add", "-A")
        git(self.base, "commit", "-q", "-m", "slow")
        ran = judge.diagnostic(Path(self.temporary.name) / "d4", "items", "c" * 40, b"", {"limits": {"diagnostic_secs": 1}}, self.head)
        self.assertEqual((ran["applied"], ran["limit"], ran["report"]["cases"]), (True, True, {}))


class CommittedReport(unittest.TestCase):
    """The report and the status are read from the diagnostic's commit: a regular file, its size read first."""

    def setUp(self):
        self.temporary = tempfile.TemporaryDirectory()
        self.repo = Path(self.temporary.name) / "repo"
        self.repo.mkdir()
        git(self.repo, "init", "-q")

    def tearDown(self):
        self.temporary.cleanup()

    def commit(self, write):
        write(self.repo / "jail-junit.xml")
        git(self.repo, "add", "-A")
        git(self.repo, "commit", "-q", "-m", "hand-in")
        return git(self.repo, "rev-parse", "HEAD")

    def read(self, commit):
        calls = []
        original = judge.pilot.git

        def recorded(repo, *words):
            calls.append(words)
            return original(repo, *words)
        with mock.patch.object(judge.pilot, "git", recorded):
            try:
                return judge.committed(self.repo, commit, "jail-junit.xml"), calls
            except Refused as error:
                return error, calls

    def test_a_report_at_the_bound_is_read_and_one_byte_over_is_refused_before_its_contents(self):
        self.assertEqual(judge.MAX_REPORT, 8 * 1024 * 1024)             # 8 MiB, as the reader named it
        head = b'<testsuite><testcase classname="c" name="t"/></testsuite>'
        at = self.commit(lambda path: path.write_bytes(head + b" " * (judge.MAX_REPORT - len(head))))
        data, _ = self.read(at)
        self.assertEqual(len(data), judge.MAX_REPORT)
        self.assertEqual(judge.read_junit(data)["cases"], {"c::t": ("passed", "")})
        over = self.commit(lambda path: path.write_bytes(head + b" " * (judge.MAX_REPORT + 1 - len(head))))
        error, calls = self.read(over)
        self.assertIsInstance(error, judge.ReportRefused)
        self.assertIn("over %d" % judge.MAX_REPORT, str(error))
        self.assertFalse([words for words in calls if "blob" in words or "show" in words], calls)

    def test_a_report_that_is_a_link_is_refused(self):
        (self.repo / "real.xml").write_bytes(b"<testsuite/>")
        error, calls = self.read(self.commit(lambda path: os.symlink("real.xml", path)))
        self.assertIsInstance(error, judge.ReportRefused)
        self.assertIn("not a regular file (mode 120000)", str(error))
        self.assertFalse([words for words in calls if "blob" in words], calls)

    def test_a_report_that_is_a_directory_is_refused_and_none_is_none(self):
        self.assertIsNone(self.read(self.commit(lambda path: (self.repo / "other").write_text("x")))[0])
        self.assertIsInstance(self.read(self.commit(lambda path: (path.mkdir(), (path / "x").write_text("x"))))[0],
            Refused)

    def test_an_executable_report_is_read(self):
        def write(path):
            path.write_bytes(b"<testsuite/>")
            path.chmod(0o755)
        self.assertEqual(self.read(self.commit(write))[0], b"<testsuite/>")


class PinnedRuntime(unittest.TestCase):
    def test_the_room_is_started_with_the_plans_program_environment_and_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary).plan
            seen = {}

            def run(argv, env=None, capture_output=None):
                seen.update(argv=argv, env=env)
                return subprocess.CompletedProcess(argv, 0, b"out", b"err")
            with mock.patch.object(judge.subprocess, "run", run), mock.patch.dict(os.environ, {"YAK_LEAK": "1",
                    "YAK": "/not/pinned"}):
                judge.jail_turn(Path(temporary) / "turn", "items", "c" * 40, Path(temporary) / "worker", plan, 17)
            self.assertEqual(seen["argv"][:2], ["/bin/sh", str(judge.ITEMS / "turn.sh")])
            self.assertEqual(seen["argv"][2:], [str(Path(temporary) / "turn"), "items", "c" * 40,
                "script:" + str(Path(temporary) / "worker" / "worker.sh"), "--concurrent", "1", "--turn-secs", "17",
                "--lease-secs", "13"])
            expected = dict(plan["environment"], YAK="/pinned/yak", YAK_PROBE_PATH="/pinned/bin:/usr/bin:/bin",
                YAK_JAIL_READ="/pinned/read" + os.pathsep + str(Path(temporary) / "worker"))
            self.assertEqual(seen["env"], expected)
            self.assertIn(b"exit 0", (Path(temporary) / "turn.log").read_bytes())

    def test_a_diagnostic_and_a_replay_give_the_plans_limits(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary).plan
            seen = []

            def turn(directory, items, commit, worker_dir, held, secs):
                seen.append((held, secs))
                Path(directory).mkdir(parents=True)
                room_turns(directory, None, None, "limit")
            with mock.patch.object(judge, "jail_turn", turn):
                ran = judge.diagnostic(Path(temporary) / "d", "items", "c" * 40, b"", plan, "b" * 40)
                self.assertEqual(ran, {"turn": "limit", "applied": None, "limit": True, "report": judge.NO_REPORT})
                self.assertEqual(judge.replay(Path(temporary) / "r", "items", "c" * 40, b"", plan, "b" * 40), ("limit", None))
            self.assertEqual(seen, [(plan, 7 + 120), (plan, 11)])

    def test_a_judges_turn_stopped_at_its_limit_after_it_committed_is_at_its_limit(self):
        # The reader's input at 06ee50fa: a commit, a status that says no limit, a passing case, ended timed_out.
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary).plan
            held = {"jail-status.json": json.dumps({"apply_exit": 0, "tests_exit": 0, "limit": False}).encode(),
                "jail-junit.xml": junit([("tests.test_a", "t1", "passed", "")])}
            for ended, limit, replayed in (("timed_out", True, ("limit", None)), ("exited", False, ("handed-in", True))):
                def turn(directory, items, commit, worker_dir, plan_, secs, ended=ended):
                    Path(directory).mkdir(parents=True)
                    (Path(directory) / "turns.json").write_text(json.dumps([{"commit": "c" * 40, "passed": True,
                        "measured": {"ended": ended}}]))
                with mock.patch.object(judge, "jail_turn", turn), \
                        mock.patch.object(judge, "committed", lambda repo, commit, name: held.get(name)):
                    ran = judge.diagnostic(Path(temporary) / ("d-" + ended), "items", "c" * 40, b"", plan, "b" * 40)
                    self.assertEqual((ran["turn"], ran["applied"], ran["limit"]), ("handed-in", True, limit), ended)
                    # What was counted before the limit is kept beside the row.
                    self.assertEqual(ran["report"]["cases"], {"tests.test_a::t1": ("passed", "")})
                    self.assertEqual(judge.replay(Path(temporary) / ("r-" + ended), "items", "c" * 40, b"", plan,
                        "b" * 40), replayed, ended)

    def test_a_judges_turn_at_its_limit_as_the_real_room_records_it(self):
        # The base's own commit and ended timed_out: the runner's classifier says limit (7062a4aa), each stage too.
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary).plan

            def turn(directory, items, commit, worker_dir, held, secs):
                Path(directory).mkdir(parents=True)
                (Path(directory) / "turns.json").write_text(json.dumps([{"commit": "b" * 40, "passed": False,
                    "measured": {"ended": "timed_out"}}]))
            with mock.patch.object(judge, "jail_turn", turn):
                ran = judge.diagnostic(Path(temporary) / "d", "items", "c" * 40, b"", plan, "b" * 40)
                self.assertEqual(ran, {"turn": "limit", "applied": None, "limit": True, "report": judge.NO_REPORT})
                self.assertEqual(judge.replay(Path(temporary) / "r", "items", "c" * 40, b"", plan, "b" * 40), ("limit", None))

    def test_a_judges_turn_that_records_its_base_handed_in_nothing(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary).plan

            def turn(directory, items, commit, worker_dir, held, secs):
                Path(directory).mkdir(parents=True)
                (Path(directory) / "turns.json").write_text(json.dumps([{"commit": "b" * 40, "passed": False,
                    "measured": {"ended": "exited"}}]))
                (Path(directory) / "clock.exit").write_text("1\n")       # as the real room ends such a turn
            with mock.patch.object(judge, "jail_turn", turn):
                ran = judge.diagnostic(Path(temporary) / "d", "items", "c" * 40, b"", plan, "b" * 40)
                self.assertEqual(ran, {"turn": "no-hand-in", "applied": None, "limit": False, "report": judge.NO_REPORT})
                self.assertEqual(judge.replay(Path(temporary) / "r", "items", "c" * 40, b"", plan, "b" * 40),
                    ("no-hand-in", None))
            self.assertIn("LIMIT = 7\n", (Path(temporary) / "d" / "stand-in" / "explain.py").read_text())


class WithoutTheProbed(unittest.TestCase):
    def test_every_summary_is_also_given_without_the_probed_item(self):
        plan = {"items": [{"item": "a", "plan_group": "p", "probed_before": False},
            {"item": "b", "plan_group": "p", "probed_before": True},
            {"item": "c", "plan_group": "q", "probed_before": True},
            {"item": "d", "plan_group": "r", "probed_before": False}]}
        def reading(d):
            return {"r": Fraction(0), "conditions": {"search": {"d": Fraction(d)}}}
        readings = {"a": reading(1), "b": reading(-1), "c": reading(1), "d": reading(-1, )}
        every = judge.plan_summaries(plan, readings)
        without = judge.plan_summaries(plan, readings, lambda item: not item["probed_before"])
        self.assertEqual(sorted(every["plans"]), ["p", "q", "r"])
        self.assertEqual(sorted(without["plans"]), ["p", "r"])
        self.assertEqual(without["plans"]["p"]["items"], ["a"])
        self.assertEqual((every["plans"]["p"]["conditions"]["search"]["D"], every["plans"]["p"]["conditions"]["search"]["on"]),
            (Fraction(0), 2))
        self.assertEqual((without["plans"]["p"]["conditions"]["search"]["D"],
            without["plans"]["p"]["conditions"]["search"]["on"]), (Fraction(1), 1))
        self.assertEqual(every["figures"]["search"], Fraction(0))          # (0 + 1 - 1) / 3 plans
        self.assertEqual(without["figures"]["search"], Fraction(0))        # (1 - 1) / 2 plans
        self.assertEqual(every["figures_on"]["search"], {"plans": 3, "items": 4})
        self.assertEqual(without["figures_on"]["search"], {"plans": 2, "items": 2})
        self.assertEqual(every["figures_on"]["path"], {"plans": 0, "items": 0})
        # p is within (D 0, R 0), q higher, r lower; without the probed, p is a alone and higher.
        self.assertEqual(every["plans_tally"]["search"], {"higher": 1, "lower": 1, "within": 1, "on": 3})
        self.assertEqual(without["plans_tally"]["search"], {"higher": 1, "lower": 1, "within": 0, "on": 2})
        self.assertEqual(every["plans_tally"]["path"], {"higher": 0, "lower": 0, "within": 0, "on": 0})
        for held in (every, without):
            for row in judge.OFFERING:
                counts = held["plans_tally"][row]
                self.assertEqual(counts["higher"] + counts["lower"] + counts["within"], counts["on"], row)
        readings["d"] = reading(1)
        self.assertEqual(judge.plan_summaries(plan, readings, lambda item: not item["probed_before"])["figures"]["search"],
            Fraction(1))

    def test_the_report_gives_them(self):
        with tempfile.TemporaryDirectory() as temporary:
            plan = Plan(temporary, items=2)
            report = judge.make_report(plan.out)
            self.assertEqual(sorted(report["plans"]), ["p0", "p1"])
            self.assertEqual(sorted(report["plans_without_probed"]), ["p0"])
            for key in ("plans_tally", "figures", "figures_on"):
                self.assertEqual(set(report[key + "_without_probed"]), set(judge.OFFERING), key)
            text = judge.report_markdown(report)
            self.assertIn("## By plan, without the probed item", text)
            self.assertIn("search - (0 plans, 0 items)", text)


class MakersPlan(fixtures.Fixture):
    """A plan the maker makes, read by the judge: its rows' records where the runner writes them are found."""

    def test_records_the_runner_writes_are_judged_and_reported(self):
        with mock.patch.dict(os.environ, self.env):
            plan = self.make()
            self.assertEqual(judge.load_plan(self.out), plan)
            if "bm25" not in judge.maker.ROWS:
                # One plan shape only: until the maker gains the bm25 row, every stage refuses the plan it makes.
                for stage in (lambda: judge.judge(self.out, None), lambda: judge.make_report(self.out),
                        lambda: judge.controls(self.out, None)):
                    with self.assertRaisesRegex(Refused, "the plan's rows are"):
                        stage()
                self.skipTest("the maker at this commit makes seven rows; the judge refuses its plan (checked above)")
            item = plan["items"][0]
            controls = self.out / "controls" / item["item"]
            (controls / "parent").mkdir(parents=True)
            (controls / "cases.json").write_text(json.dumps({"commit": item["commit"], "cases": ["c::t"], "counts": {}}))
            (controls / "parent.json").write_text(json.dumps({"commit": item["commit"], "passed": []}))
            (controls / "parent" / "junit.json").write_text(json.dumps({"cases": {}, "collection_errors": []}))
            for order in plan["order"]:
                directory = self.out / order["directory"]       # as documents_run.run_turn makes it
                directory.mkdir(parents=True)
                (directory / "record.json").write_text(json.dumps({"n": order["n"], "commit": order["commit"],
                    "row": order["row"], "outcome": "clock-failed", "turn_commit": None, "at_limit": False,
                    "turns_exit": 0, "walks_exit": 0, "earlier_attempts": 0, "attempts": [], "interrupted_attempts": 0}))
            self.assertEqual(judge.judge(self.out, None), 0)
            report = judge.make_report(self.out)
        self.assertEqual((report["rows"]["planned"], report["rows"]["recorded"], report["rows"]["judged"]), (8, 8, 8))
        self.assertEqual(report["rows"]["judged_outcomes"], {"clock-failed": 8})
        self.assertEqual(sorted(os.listdir(self.out / "judged")), sorted(Path(order["directory"]).name
            for order in plan["order"]))
        for order in plan["order"]:
            held = json.loads((self.out / "judged" / Path(order["directory"]).name / "score.json").read_text())
            self.assertEqual((held["of"], held["of_new"]), (1, 1))


class Shape(unittest.TestCase):
    def test_parses_under_python_3_9(self):
        import ast
        for name in ("documents_judge.py", "test_documents_judge.py"):
            ast.parse((HERE / name).read_text(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
