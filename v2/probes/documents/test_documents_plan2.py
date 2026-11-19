#!/usr/bin/env python3
"""Small real repositories and hand-written review/control records; no room."""
import ast
import contextlib
import hashlib
import importlib.util
import io
import json
import os
from pathlib import Path
import subprocess
import sys
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
spec = importlib.util.spec_from_file_location("first_maker_tests", HERE / "test_documents_plan.py")
fixtures = importlib.util.module_from_spec(spec)
spec.loader.exec_module(fixtures)
LINE = "There may be a plan for this work in the repository. Look for one before you change code."


def write_json(path, value):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(value, sort_keys=True, indent=1) + "\n", encoding="ascii")


class Fixture(fixtures.Fixture):
    def setUp(self):
        super().setUp()
        self.first = self.driver
        self.driver = fixtures.module("documents_plan2")
        self.selection = self.tmp / "selection"
        self.selection.mkdir()
        (self.selection / "used-before.txt").write_text("f" * 40 + "\n")
        self.entries = []
        self.a = [self.add_item(self.parent, "frozen work %s" % n) for n in range(12)]
        index = self.tmp / "pool.index"
        self.first.git_as(self.repo, "read-tree", self.parent, index=index)
        blob = self.first.git_as(self.repo, "hash-object", "-w", "--stdin",
            data=b"new_behavior\ndef test_from_plan(): pass\n").decode().strip()
        self.first.git_as(self.repo, "update-index", "--cacheinfo",
            "100644,%s,docs/plans/z-plan.md" % blob, index=index)
        tree = self.first.git_as(self.repo, "write-tree", index=index).decode().strip()
        parent_p = self.first.git_as(self.repo, "commit-tree", tree, "-p", self.parent, "-m", "pool parent").decode().strip()
        index.unlink()
        self.p = [self.add_item(parent_p, "Use z-plan.md Task 2 new_behavior\n\nTrailer: kept\n \t\n") for _ in range(8)]
        self.n = [self.add_item(parent_p, "Unmentioned work %s" % n) for n in range(7)]
        # Different commit-tree timestamps are unnecessary: make each message unique.
        self.orders = {}
        for pool, entries in (("P", self.p), ("N", self.n)):
            ordered = sorted(entries, key=lambda e: hashlib.sha256(
                ("20261120:pick:" + e["commit"]).encode("ascii")).hexdigest())
            rows = []
            for n, entry in enumerate(ordered, 1):
                row = {"n": n, "commit": entry["commit"], "parent": entry["parent"],
                    "hash": hashlib.sha256(("20261120:pick:" + entry["commit"]).encode("ascii")).hexdigest(),
                    "counted_names": ["new_behavior", "other_name"]}
                if pool == "P":
                    row.update(matching=["docs/plans/z-plan.md", "docs/specs/design.md"],
                        direct_path="docs/plans/z-plan.md")
                rows.append(row)
            self.orders[pool] = rows
            write_json(self.selection / ("pool-%s.order.json" % pool.lower()),
                {"pool": pool, "seed_text": "20261120:pick:<commit>", "items": rows})
            self.record(pool)
        self.list.write_text(json.dumps({"commits": self.entries}))
        self.census.write_text("".join(e["commit"] + " scored 0 1 passed\n" for e in self.entries))
        manifest = []
        for entry in self.a:
            for kind, content in (("task", b"Please provide rare behavior.\n"), ("facts", b"Required facts.\n")):
                path = self.tasks / (entry["commit"][:10] + "." + kind + ".md")
                path.write_bytes(content)
                manifest.append(hashlib.sha256(content).hexdigest() + "  " + path.name)
        (self.tasks / "FROZEN.sha256").write_text("\n".join(manifest) + "\n")
        self.expected_hash = hashlib.sha256(self.list.read_bytes()).hexdigest()

    def add_item(self, parent, message):
        # A unique reference for each entry, with a real held-back test blob.
        number = len(self.entries)
        tree = fixtures.git(self.repo, "rev-parse", self.commit + "^{tree}")
        commit = self.first.git_as(self.repo, "commit-tree", tree, "-p", parent,
            data=(message + "\nFixture: %s\n \t\n" % number).encode()).decode().strip()
        index = self.tmp / "item.index"
        self.first.git_as(self.repo, "read-tree", parent, index=index)
        meta = {"parent": parent, "tests": [{"path": "peer/tests/test_work.py",
            "blob": fixtures.git(self.repo, "rev-parse", self.commit + ":peer/tests/test_work.py")}]}
        blob = self.first.git_as(self.repo, "hash-object", "-w", "--stdin", data=json.dumps(meta).encode()).decode().strip()
        self.first.git_as(self.repo, "update-index", "--add", "--cacheinfo",
            "100644,%s,.yak-check/item.json" % blob, index=index)
        base_tree = self.first.git_as(self.repo, "write-tree", index=index).decode().strip()
        base = self.first.git_as(self.repo, "commit-tree", base_tree, "-p", parent, "-m", "item base").decode().strip()
        index.unlink()
        fixtures.git(self.repo, "update-ref", "refs/yak-items/%s/base" % commit, base)
        entry = {"commit": commit, "parent": parent, "base": base, "reference": commit, "wrong": base}
        self.entries.append(entry)
        return entry

    def record(self, pool, skipped=()):
        walked = []
        for row in self.orders[pool]:
            entry = {"n": row["n"], "commit": row["commit"],
                "verdict": "skipped" if row["n"] in skipped else "accepted", "reason": "Fixture review.",
                "files_read": ["docs/plans/z-plan.md"]}
            if pool == "P":
                entry.update(plan_group="group-%s" % ((row["n"] - 1) // 2),
                    plan_group_reason="One piece of planned work.", gives="The tested behavior.")
            else:
                entry.update(subject="Fixture subject", terms=["fixture"],
                    queries=[{"query": "fixture", "mode": "substring; case kept; text", "hits": []}], found=None)
            walked.append(entry)
        path = self.selection / ("pool-%s.record.json" % pool.lower())
        value = {"pool": pool, "reader": "fixture", "repository_read": "the item list's repository",
            "walked": walked, "stopped": "the pool ended", "stopped_n": len(walked)}
        write_json(path, value)
        return value

    def candidates(self):
        return self.driver.candidates(self.items, self.selection, self.out, census=self.census,
            expected=None, expected_list_sha256=self.expected_hash)

    def runtime(self):
        """The controls' runtime, written where the judge writes it, as this fixture's make will pin it."""
        with mock.patch.dict(os.environ, self.env):
            _, limits, programs, environment = self.driver.first.runtime_pins(self.items, self.out,
                "script:" + str(self.worker), None, 1200, 300)
        held = self.driver.first.control_runtime(limits, programs, environment)
        write_json(self.out / self.driver.first.CONTROL_RUNTIME, held)
        return held

    def controls(self, candidates):
        for item in candidates["part_a"] + candidates["pool_p"] + candidates["pool_n"]:
            directory = self.out / "controls" / item["item"]
            write_json(directory / "cases.json", {"commit": item["commit"], "cases": ["one", "two"],
                "counts": {"passed": 2, "failed": 0, "error": 0, "skipped": 0}})
            write_json(directory / "parent.json", {"commit": item["commit"], "passed": ["one"]})
        self.runtime()

    def make(self):
        with mock.patch.dict(os.environ, self.env):
            return self.driver.make_plan(self.items, self.tasks, self.selection, self.out,
                "script:" + str(self.worker), self.census, expected=None, expected_list_sha256=self.expected_hash)


class Candidates(Fixture):
    def test_directory_with_a_full_id_is_refused(self):
        self.out = self.tmp / ("a" * 32) / "pilot"
        with self.assertRaisesRegex(self.driver.Refused, "directory.*hexadecimal"):
            self.candidates()
        self.assertFalse(self.out.exists())

    def test_skipped_record_entries_are_left_out_and_part_a_uses_first_rules(self):
        self.record("P", skipped=(1,))
        candidate = self.candidates()
        self.assertEqual([i["n"] for i in candidate["pool_p"]], list(range(2, 9)))
        self.assertEqual([i["commit"] for i in candidate["part_a"]], [e["commit"] for e in self.a])
        self.assertEqual(candidate["v"], 2)
        self.assertEqual(len(candidate["pool_n"]), 7)
        self.assertEqual(candidate["list_sha256"], self.expected_hash)
        self.assertFalse((self.out / "plan.json").exists())
        self.assertEqual((self.out / "candidates.json").read_text(), json.dumps(candidate, sort_keys=True, indent=1) + "\n")
        self.assertEqual(candidate["pool_p"][0]["plan_group"], "group-0")

    def test_records_must_be_a_prefix_with_a_verdict_and_a_group(self):
        path = self.selection / "pool-p.record.json"
        original = self.record("P")
        edits = [lambda r: r["walked"].reverse(), lambda r: r["walked"].pop(0),
            lambda r: r["walked"][0].update(n=2), lambda r: r["walked"][0].update(commit="a" * 40),
            lambda r: r["walked"][0].update(verdict="maybe"), lambda r: r["walked"][0].update(plan_group=""),
            lambda r: r.update(stopped_n=1), lambda r: r.update(stopped="unknown"),
            lambda r: r["walked"][0].pop("gives"), lambda r: r.update(pool="N")]
        for edit in edits:
            with self.subTest(edit=edit):
                record = json.loads(json.dumps(original))
                edit(record)
                write_json(path, record)
                with self.assertRaises(self.driver.Refused):
                    self.candidates()
                self.assertFalse(self.out.exists())
        record = json.loads(json.dumps(original))
        record["walked"] = record["walked"][:2]
        record.update(stopped="time", stopped_n=2)
        write_json(path, record)
        self.assertEqual(len(self.candidates()["pool_p"]), 2)

    def test_used_or_out_of_hash_order_is_refused(self):
        path = self.selection / "pool-p.order.json"
        order = json.loads(path.read_text())
        for edit in (lambda v: v["items"].reverse(), lambda v: v["items"][0].update(hash="0" * 64)):
            value = json.loads(json.dumps(order))
            edit(value)
            write_json(path, value)
            with self.assertRaises(self.driver.Refused):
                self.candidates()
        write_json(path, order)
        (self.selection / "used-before.txt").write_text(order["items"][0]["commit"] + "\n")
        with self.assertRaisesRegex(self.driver.Refused, "used before"):
            self.candidates()


class Maker(Fixture):
    def test_seventy_two_rows_tasks_bases_messages_and_pins(self):
        candidates = self.candidates()
        self.controls(candidates)
        plan = self.make()
        self.assertEqual((plan["v"], plan["seed"], plan["line"], plan["part_b_run"]), (2, 20261120, LINE, True))
        self.assertEqual(plan["limits"], {"worker_secs": 1200, "check_secs": 900,
            "replay_secs": 1200, "diagnostic_secs": 300, "lease_secs": 1800})
        self.assertEqual(len(plan["items"]), 24)
        self.assertEqual(len(plan["order"]), 72)
        expected = sorted((hashlib.sha256(("20261120:order:%s:%s" % (i["commit"], r)).encode("ascii")).hexdigest(),
            i["commit"], r) for i in plan["items"] for r in (("may-1", "may-2") if i["part"] == "A" else
            ("nothing-1", "nothing-2", "may-1", "may-2")))
        self.assertEqual([(r["hash"], r["commit"], r["row"]) for r in plan["order"]], expected)
        self.assertEqual([r["n"] for r in plan["order"]], list(range(1, 73)))
        for row in plan["order"]:
            self.assertEqual(row["directory"], "rows/%03d-%s-%s" % (row["n"], row["commit"][:10], row["row"]))
        for item in plan["items"]:
            self.assertEqual(len(item["rows"]), 2 if item["part"] == "A" else 4)
            if item["part"] == "A":
                raw = b"Please provide rare behavior.\n"
                self.assertEqual((item["pool"], item["task_kind"], item["message"]), (None, "frozen", None))
            else:
                raw = self.first.git(self.repo, "show", "-s", "--encoding=UTF-8", "--format=%s%n%n%b", item["commit"]).rstrip(b" \t\r\n\v\f")
                self.assertEqual((self.out / "messages" / (item["item"] + ".txt")).read_bytes(), raw)
                self.assertIn(b"Fixture:", raw)
                self.assertFalse(raw.endswith(b"\n"))
                self.assertEqual(item["task_kind"], "message")
            self.assertEqual(item["task_sha256"], hashlib.sha256(raw).hexdigest())
            common = raw + (b"\n" if raw.endswith(b"\n") else b"\n\n") + self.first.FIXED.encode() + b"\n"
            for name, row in item["rows"].items():
                content = self.first.git(self.out / "src", "show", row["base"] + ":TASK.md")
                self.assertEqual(row["paragraph"], LINE if name.startswith("may") else "")
                self.assertEqual(content, common + (("\n" + LINE + "\n").encode() if name.startswith("may") else b""))
                self.assertEqual(fixtures.git(self.out / "src", "rev-parse", row["base"] + "^"), item["parent"])
                self.first.prove_bases(self.out / "src", item, raw, {n: r["paragraph"] for n, r in item["rows"].items()})
        self.assertEqual(self.first.load_plan(self.out), plan)
        required = list(HERE.glob("*.py")) + list(HERE.glob("*.sh")) + [self.driver.SPEC,
            self.tasks / "FROZEN.sha256", self.census] + list(self.selection.iterdir())
        pinned_paths = {self.first.input_path(path).resolve() for path in plan["inputs"]}
        for path in required:
            self.assertIn(path.resolve(), pinned_paths)
        record = self.selection / "pool-p.record.json"
        record.write_text(record.read_text() + " ")
        with self.assertRaisesRegex(self.first.Refused, "record.json"):
            self.first.load_plan(self.out)

    def test_walk_caps_groups_skips_parent_ceiling_and_stops_at_six(self):
        record = self.record("P")
        for entry in record["walked"][:3]:
            entry["plan_group"] = "same"
        write_json(self.selection / "pool-p.record.json", record)
        candidates = self.candidates()
        self.controls(candidates)
        ceiling = candidates["pool_n"][0]
        write_json(self.out / "controls" / ceiling["item"] / "parent.json",
            {"commit": ceiling["commit"], "passed": ["one", "two", "extra"]})
        plan = self.make()
        self.assertTrue(plan["part_b_run"])
        self.assertEqual([e["why"] for e in plan["walk"]["P"]],
            ["taken", "taken", "the plan group has two", "taken", "taken", "taken", "taken"])
        self.assertEqual(plan["walk"]["N"][0]["why"], "every frozen case passes on the parent")
        self.assertEqual([e["n"] for e in plan["walk"]["N"]], list(range(1, 8)))
        self.assertEqual([e["taken"] for e in plan["walk"]["P"]], [True, True, False, True, True, True, True])

    def test_five_taken_gives_part_a_alone_and_last_line_says_so(self):
        self.record("N", skipped=(6, 7))
        candidate = self.candidates()
        self.controls(candidate)
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            plan = self.make()
        self.assertFalse(plan["part_b_run"])
        self.assertEqual(len(plan["items"]), 12)
        self.assertEqual(len(plan["order"]), 24)
        self.assertEqual({i["part"] for i in plan["items"]}, {"A"})
        self.assertIn("part B was not run", output.getvalue().splitlines()[-1])

    def test_missing_controls_anywhere_refuses(self):
        candidates = self.candidates()
        self.controls(candidates)
        last = candidates["pool_n"][-1]
        (self.out / "controls" / last["item"] / "parent.json").unlink()
        with self.assertRaisesRegex(self.driver.Refused, last["item"]):
            self.make()
        self.assertFalse((self.out / "src").exists())

    def test_stopped_reached_or_part_a_refuses_and_unreached_does_not(self):
        candidates = self.candidates()
        self.controls(candidates)
        for item in (candidates["part_a"][0], candidates["pool_p"][0]):
            path = self.out / "controls" / item["item"] / "stopped.json"
            write_json(path, {"commit": item["commit"], "reason": "Fixture stop."})
            with self.assertRaisesRegex(self.driver.Refused, item["item"]):
                self.make()
            path.unlink()
        item = candidates["pool_p"][-1]
        directory = self.out / "controls" / item["item"]
        (directory / "parent.json").unlink()
        (directory / "cases.json").unlink()
        write_json(directory / "stopped.json", {"commit": item["commit"], "reason": "Fixture stop."})
        plan = self.make()
        self.assertEqual(len(plan["walk"]["P"]), 6)
        self.assertTrue(plan["part_b_run"])

    def test_frozen_manifest_and_changed_candidate_record_are_refused(self):
        candidates = self.candidates()
        self.controls(candidates)
        record = self.selection / "pool-n.record.json"
        raw = record.read_bytes()
        record.write_bytes(raw + b" ")
        with self.assertRaisesRegex(self.driver.Refused, "candidates|selection"):
            self.make()
        record.write_bytes(raw)
        task = self.tasks / (self.a[0]["commit"][:10] + ".task.md")
        task.write_text("Changed task.\n")
        with self.assertRaisesRegex(self.driver.Refused, "frozen|FROZEN"):
            self.make()


class ControlsRuntime(Fixture):
    def ready(self):
        candidate = self.candidates()
        self.controls(candidate)
        return candidate

    def test_make_needs_the_record_of_what_the_controls_ran_under(self):
        self.ready()
        (self.out / self.driver.first.CONTROL_RUNTIME).unlink()
        with self.assertRaisesRegex(self.driver.Refused, "not recorded"):
            self.make()
        self.assertFalse((self.out / "plan.json").exists())

    def test_make_refuses_controls_that_ran_under_another_runtime(self):
        self.ready()
        path = self.out / self.driver.first.CONTROL_RUNTIME
        good = json.loads(path.read_text())
        for change in ("program", "environment", "limit"):
            held = json.loads(json.dumps(good))
            if change == "program":
                held["yak"]["sha256"] = "0" * 64
            elif change == "environment":
                held["environment"]["PATH"] = held["environment"]["PATH"] + ":/elsewhere"
            else:
                held["limits"]["diagnostic_secs"] += 1
            write_json(path, held)
            with self.assertRaisesRegex(self.driver.Refused, "another runtime", msg=change):
                self.make()
            self.assertFalse((self.out / "plan.json").exists(), change)
        write_json(path, good)
        self.make()
        self.assertTrue((self.out / "plan.json").exists())

    def test_the_record_is_pinned_and_a_change_after_make_is_refused(self):
        self.ready()
        self.make()
        plan = self.driver.first.load_plan(self.out)
        path = (self.out / self.driver.first.CONTROL_RUNTIME).resolve()
        self.assertIn(self.driver.first.pin_path(path), plan["inputs"])
        held = json.loads(path.read_text())
        held["limits"]["replay_secs"] += 1
        write_json(path, held)
        with self.assertRaisesRegex(self.driver.Refused, "input changed"):
            self.driver.first.load_plan(self.out)

    def test_the_runtime_leaves_out_the_workers_pin_and_limit(self):
        got = self.driver.first.control_runtime({"worker_secs": 9, "check_secs": 1, "replay_secs": 2,
            "diagnostic_secs": 3, "lease_secs": 4}, {"yak": {"path": "/y", "sha256": "s"}, "worker": {"path": "/w"}},
            {"PATH": "/p"})
        self.assertEqual(got, {"limits": {"check_secs": 1, "replay_secs": 2, "diagnostic_secs": 3, "lease_secs": 4},
            "yak": {"path": "/y", "sha256": "s"}, "environment": {"PATH": "/p"}})


class Message(unittest.TestCase):
    def test_exact_message_bytes_keep_trailer_and_strip_only_trailing_ascii_space(self):
        with __import__("tempfile").TemporaryDirectory() as folder:
            repo = Path(folder)
            fixtures.git(repo, "init", "-q", "--bare", "--template=")
            first = fixtures.module()
            tree = first.git_as(repo, "mktree", data=b"").decode().strip()
            commit = first.git_as(repo, "commit-tree", tree,
                data=b"A subject\n\nKeep  interior\tspace\n\nTrailer: yes\n \t\r\v\f").decode().strip()
            self.assertEqual(fixtures.module("documents_plan2").message_bytes(repo, commit),
                b"A subject\n\nKeep  interior\tspace\n\nTrailer: yes")
            latin = first.git_as(repo, "-c", "i18n.commitEncoding=ISO-8859-1", "commit-tree", tree,
                data=b"Caf\xe9 subject\n\nTrailer: kept\n").decode().strip()
            self.assertEqual(fixtures.module("documents_plan2").message_bytes(repo, latin),
                b"Caf\xc3\xa9 subject\n\nTrailer: kept")

    def test_message_annotation_each_fact_true_false_and_whole_words(self):
        driver = fixtures.module("documents_plan2")
        item = {"matching": ["docs/plans/a.md"], "counted_names": ["new_name", "held_name"]}
        for text, expected in [(b"a.md Task 2 new_name", (True, True, ["new_name"])),
            (b"docs/plans/a.md step\t12 held_name", (True, True, ["held_name"])),
            (b"unrelated xnew_name new_namex Task x Stepwise 1", (False, False, [])),
            (b"STEP 1 TASK 2", (False, False, []))]:
            with self.subTest(text=text):
                actual = driver.message_record(text, item)
                self.assertEqual(actual, dict(zip(("names_a_matching_file", "cites_a_task_or_step", "counted_names_held"), expected)))

    def test_python_39(self):
        ast.parse((HERE / "documents_plan2.py").read_bytes(), feature_version=(3, 9))

    def test_history_skip_checks_the_first_census_commit(self):
        driver = fixtures.module()
        first_commit = (HERE / "census-2026-11-18.txt").read_text().split()[0]
        def missing(repo, *words):
            if words == ("cat-file", "-e", first_commit + "^{commit}"):
                raise driver.Refused("first census commit unavailable")
            raise AssertionError("history check did not test the first census commit")
        with mock.patch.object(fixtures, "module", return_value=driver), mock.patch.object(driver, "git", side_effect=missing):
            with self.assertRaisesRegex(unittest.SkipTest, "first census commit is unavailable"):
                fixtures.Rules().test_frozen_twelve_ids_selected_by_rules_from_repository_history()


class Guards(fixtures.Fixture):
    """One real first-pilot item for refusal paths, without the full cohort."""
    def setUp(self):
        super().setUp()
        self.first = self.driver
        self.driver = fixtures.module("documents_plan2")
        self.selection = self.tmp / "selection"
        self.selection.mkdir()
        (self.selection / "used-before.txt").write_text("")
        for pool in ("P", "N"):
            write_json(self.selection / ("pool-%s.order.json" % pool.lower()), {"pool": pool, "items": []})
            write_json(self.selection / ("pool-%s.record.json" % pool.lower()),
                {"pool": pool, "reader": "fixture", "repository_read": "the item list's repository",
                    "walked": [], "stopped": "the pool ended", "stopped_n": 0})
        self.expected_hash = hashlib.sha256(self.list.read_bytes()).hexdigest()
        self.kw = {"expected": None, "expected_list_sha256": self.expected_hash}
        paths = list(self.tasks.iterdir())
        (self.tasks / "FROZEN.sha256").write_text("".join(
            hashlib.sha256(path.read_bytes()).hexdigest() + "  " + path.name + "\n" for path in paths))

    def prepare(self):
        candidate = self.driver.candidates(self.items, self.selection, self.out, self.census, **self.kw)
        directory = self.out / "controls" / self.commit[:10]
        write_json(directory / "cases.json", {"commit": self.commit, "cases": ["one"]})
        write_json(directory / "parent.json", {"commit": self.commit, "passed": []})
        self.runtime()
        return candidate

    def runtime(self):
        with mock.patch.dict(os.environ, self.env):
            _, limits, programs, environment = self.driver.first.runtime_pins(self.items, self.out,
                "script:" + str(self.worker), None, 1200, 300)
        write_json(self.out / self.driver.first.CONTROL_RUNTIME,
            self.driver.first.control_runtime(limits, programs, environment))

    def make_second(self):
        with mock.patch.dict(os.environ, self.env):
            return self.driver.make_plan(self.items, self.tasks, self.selection, self.out,
                "script:" + str(self.worker), self.census, **self.kw)

    def test_candidate_list_cohort_and_selection_pins(self):
        candidate, selected = self.driver.candidate_data(self.items, self.selection, self.census, **self.kw)
        same, _ = self.driver.candidate_data(self.items, self.selection, self.census,
            expected={self.commit[:8]}, expected_list_sha256=self.expected_hash)
        self.assertEqual(same, candidate)
        self.assertEqual(candidate["part_a"], [{"commit": self.commit, "item": self.commit[:10], "parent": self.parent}])
        self.assertEqual(candidate["v"], 2)
        self.assertEqual(set(candidate["selection"]), {"used_before_sha256", "pool_p_order_sha256", "pool_n_order_sha256",
            "pool_p_record_sha256", "pool_n_record_sha256"})
        with self.assertRaisesRegex(self.driver.Refused, "sha256 differs"):
            self.driver.candidate_data(self.items, self.selection, self.census)
        with self.assertRaisesRegex(self.driver.Refused, "cohort differs"):
            self.driver.candidate_data(self.items, self.selection, self.census,
                expected=set(), expected_list_sha256=self.expected_hash)
        order = {"pool": "N", "items": [{"n": 1, "commit": "b" * 40, "parent": self.parent,
            "hash": hashlib.sha256(("20261120:pick:" + "b" * 40).encode()).hexdigest()}]}
        record = {"pool": "N", "stopped": "the pool ended", "stopped_n": 1, "walked": [{"n": 1,
            "commit": "b" * 40, "verdict": "accepted", "reason": "Reviewed.", "subject": "Work",
            "terms": [], "queries": [], "files_read": [], "found": None}]}
        write_json(self.selection / "pool-n.order.json", order)
        write_json(self.selection / "pool-n.record.json", record)
        with self.assertRaisesRegex(self.driver.Refused, "absent from the list"):
            self.driver.candidate_data(self.items, self.selection, self.census, **self.kw)

    def test_existing_output_and_unlisted_frozen_task_refuse(self):
        self.prepare()
        for name in ("plan.json", "src"):
            path = self.out / name
            path.touch()
            with self.assertRaisesRegex(self.driver.Refused, "already exists"):
                self.make_second()
            path.unlink()
        (self.tasks / "FROZEN.sha256").write_text("")
        with self.assertRaisesRegex(self.driver.Refused, "frozen task"):
            self.make_second()

    def test_small_fallback_proves_first_named_row_and_detects_input_race(self):
        self.prepare()
        real = self.driver.first.make_bases
        def changed(*args, **kwargs):
            real(*args, **kwargs)
            self.census.write_text(self.census.read_text() + "changed\n")
        with mock.patch.object(self.driver.first, "make_bases", side_effect=changed):
            with self.assertRaisesRegex(self.driver.Refused, "input changed while making bases"):
                self.make_second()
        self.assertFalse((self.out / "plan.json").exists())

    def test_task_cannot_change_between_reading_and_pinning(self):
        self.prepare()
        real = self.driver.pilot.load
        counts = []
        def changed(path):
            value = real(path)
            if Path(path).name == "pool-p.order.json":
                counts.append(path)
                if len(counts) == 2:
                    self.task.write_text("A changed task.\n")
            return value
        with mock.patch.object(self.driver.pilot, "load", side_effect=changed):
            with self.assertRaisesRegex(self.driver.Refused, "frozen file changed"):
                self.make_second()
        self.assertFalse((self.out / "plan.json").exists())

    def test_proof_checks_the_supplied_paragraph_for_each_named_row(self):
        self.prepare()
        plan = self.make_second()
        item = plan["items"][0]
        with self.assertRaisesRegex(self.driver.Refused, "TASK.md"):
            self.driver.first.prove_bases(self.out / "src", item, self.task.read_bytes(),
                {"may-1": "A different paragraph.", "may-2": LINE})

    def test_cli_refuses_bad_inputs_with_an_exit_status(self):
        done = subprocess.run([sys.executable, "-I", str(HERE / "documents_plan2.py"), "candidates",
            str(self.items), str(self.selection), str(self.out)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("REFUSED: items.json sha256 differs", done.stderr)

    def test_cli_candidates_then_make_preserve_the_artifacts_and_exit_zero(self):
        # Only the fixed historical cohort/hash are replaced by this small list.
        real = self.driver.candidate_data
        def fixture_cohort(items, selection, *unused):
            return real(items, selection, self.census, **self.kw)
        output = io.StringIO()
        with mock.patch.object(self.driver, "candidate_data", side_effect=fixture_cohort), contextlib.redirect_stdout(output):
            self.assertEqual(self.driver.main(["candidates", str(self.items), str(self.selection), str(self.out)]), 0)
            directory = self.out / "controls" / self.commit[:10]
            write_json(directory / "cases.json", {"commit": self.commit, "cases": ["one"]})
            write_json(directory / "parent.json", {"commit": self.commit, "passed": []})
            self.runtime()
            with mock.patch.dict(os.environ, self.env):
                self.assertEqual(self.driver.main(["make", str(self.items), str(self.tasks), str(self.selection),
                    str(self.out), "--worker", "script:" + str(self.worker), "--census", str(self.census)]), 0)
        self.assertEqual(json.loads((self.out / "candidates.json").read_text())["part_a"][0]["commit"], self.commit)
        plan = self.driver.first.load_plan(self.out)
        self.assertEqual(len(plan["order"]), 2)
        self.assertEqual(plan["spec_sha256"], hashlib.sha256(self.driver.SPEC.read_bytes()).hexdigest())
        judge = fixtures.module("documents_judge")
        self.assertEqual(judge.check_items(plan, self.items)["commits"][0]["commit"], self.commit)
        self.assertIn("part B was not run", output.getvalue().splitlines()[-1])


class Walk(unittest.TestCase):
    def test_order_is_the_seventy_two_hashes_and_directory_places(self):
        driver = fixtures.module("documents_plan2")
        commits = [hashlib.sha1(str(n).encode()).hexdigest() for n in range(24)]
        rows_a = ("may-1", "may-2")
        rows_b = ("nothing-1", "nothing-2", "may-1", "may-2")
        items = [{"commit": c, "item": c[:10], "rows": {name: {} for name in (rows_a if n < 12 else rows_b)}}
            for n, c in enumerate(commits)]
        expected = sorted((hashlib.sha256(("20261120:order:%s:%s" % (c, name)).encode()).hexdigest(), c, name)
            for n, c in enumerate(commits) for name in (rows_a if n < 12 else rows_b))
        actual = driver.row_order(items)
        self.assertEqual([(r["hash"], r["commit"], r["row"]) for r in actual], expected)
        self.assertEqual([r["n"] for r in actual], list(range(1, 73)))
        for row in actual:
            self.assertEqual(row["directory"], "rows/%03d-%s-%s" % (row["n"], row["commit"][:10], row["row"]))
        self.assertEqual(driver.row_order(list(reversed(items))), actual)

    def test_cap_ceiling_and_stop_boundaries(self):
        driver = fixtures.module("documents_plan2")
        items = [{"n": n, "commit": "%040x" % n, "item": "%010x" % n,
            "plan_group": "same" if n < 4 else str(n)} for n in range(1, 10)]
        controls = {i["commit"]: [{"a", "b"}, {"a"}] for i in items}
        controls[items[3]["commit"]] = [{"a", "b"}, {"a", "b"}]
        controls[items[-1]["commit"]] = None
        taken, walked = driver.walk_pool(items, controls, "P")
        self.assertEqual([i["n"] for i in taken], [1, 2, 5, 6, 7, 8])
        self.assertEqual([i["n"] for i in walked], list(range(1, 9)))
        self.assertEqual([i["why"] for i in walked], ["taken", "taken", "the plan group has two",
            "every frozen case passes on the parent", "taken", "taken", "taken", "taken"])
        self.assertEqual([i["taken"] for i in walked], [True, True, False, False, True, True, True, True])
        taken, walked = driver.walk_pool(items, controls, "N")
        self.assertEqual([i["n"] for i in taken], [1, 2, 3, 5, 6, 7])
        with self.assertRaisesRegex(driver.Refused, items[-1]["item"]):
            driver.walk_pool(items[-1:], controls, "N")
        self.assertEqual(driver.walk_pool([], {}, "P"), ([], []))


class Records(unittest.TestCase):
    def setUp(self):
        self.temp = __import__("tempfile").TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.folder = Path(self.temp.name)
        self.driver = fixtures.module("documents_plan2")
        (self.folder / "used-before.txt").write_text("")
        self.orders, self.records = {}, {}
        for pool in ("P", "N"):
            commits = sorted([hashlib.sha1(str(n).encode()).hexdigest() for n in range(1, 13)], key=lambda c:
                hashlib.sha256(("20261120:pick:" + c).encode()).hexdigest())
            rows = [{"n": n, "commit": c, "parent": "a" * 40,
                "hash": hashlib.sha256(("20261120:pick:" + c).encode()).hexdigest(),
                "matching": ["plans/work.md"], "direct_path": "plans/work.md"} for n, c in enumerate(commits, 1)]
            entries = [{"n": r["n"], "commit": r["commit"], "verdict": "accepted", "reason": "Reviewed.",
                "files_read": [], "plan_group": "g%s" % ((r["n"] - 1) // 2), "plan_group_reason": "One plan.",
                "gives": "A tested behavior."} if pool == "P" else {"n": r["n"], "commit": r["commit"],
                "verdict": "accepted", "reason": "Reviewed.", "subject": "Work", "terms": [], "queries": [],
                "files_read": [], "found": None} for r in rows]
            self.orders[pool] = {"pool": pool, "items": rows}
            self.records[pool] = {"pool": pool, "reader": "fixture", "repository_read": "the item list's repository",
                "walked": entries, "stopped": "the pool ended", "stopped_n": len(entries)}
        self.save()

    def save(self):
        for pool in ("P", "N"):
            write_json(self.folder / ("pool-%s.order.json" % pool.lower()), self.orders[pool])
            write_json(self.folder / ("pool-%s.record.json" % pool.lower()), self.records[pool])

    def test_prefix_verdict_group_and_record_end(self):
        original = json.loads(json.dumps(self.records["P"]))
        bad = [lambda r: r["walked"].reverse(), lambda r: r["walked"].append(r["walked"][-1]),
            lambda r: r["walked"][0].pop("gives"), lambda r: r["walked"][0].update(verdict="other"),
            lambda r: r["walked"][0].update(plan_group=None), lambda r: r["walked"][0].update(plan_group=" "),
            lambda r: r.update(pool="N"), lambda r: r.update(stopped_n=True),
            lambda r: r.update(stopped_n=1), lambda r: r.update(stopped="unknown"),
            lambda r: r["walked"].pop()]
        self.assertEqual(len(self.driver.accepted(self.folder, "P")), 12)
        self.assertEqual(len(self.driver.accepted(self.folder, "N")), 12)
        for edit in bad:
            self.records["P"] = json.loads(json.dumps(original))
            edit(self.records["P"])
            self.save()
            with self.subTest(edit=edit), self.assertRaises(self.driver.Refused):
                self.driver.accepted(self.folder, "P")
        self.records["P"] = json.loads(json.dumps(original))
        self.records["P"]["walked"] = self.records["P"]["walked"][:3]
        self.records["P"].update(stopped="time", stopped_n=3)
        self.records["P"]["walked"][0]["verdict"] = "skipped"
        self.save()
        self.assertEqual([i["n"] for i in self.driver.accepted(self.folder, "P")], [2, 3])

    def test_order_and_used_boundaries(self):
        original = json.loads(json.dumps(self.orders["P"]))
        for edit in (lambda r: r.update(pool="N"), lambda r: r["items"][0].update(n=0),
                lambda r: r["items"][0].update(hash="0" * 64), lambda r: r["items"].reverse()):
            self.orders["P"] = json.loads(json.dumps(original))
            edit(self.orders["P"])
            self.save()
            with self.subTest(edit=edit), self.assertRaises(self.driver.Refused):
                self.driver.accepted(self.folder, "P")
        self.orders["P"] = original
        self.save()
        (self.folder / "used-before.txt").write_text(original["items"][0]["commit"])
        with self.assertRaisesRegex(self.driver.Refused, "used before"):
            self.driver.accepted(self.folder, "P")

    def test_nine_accepted_counts_at_most_two_per_group(self):
        for pool in ("P", "N"):
            self.records[pool]["walked"] = self.records[pool]["walked"][:9]
            self.records[pool].update(stopped="nine accepted", stopped_n=9)
        self.save()
        self.assertEqual(len(self.driver.accepted(self.folder, "P")), 9)
        self.assertEqual(len(self.driver.accepted(self.folder, "N")), 9)
        self.records["P"]["walked"][2]["plan_group"] = "g0"
        self.save()
        with self.assertRaisesRegex(self.driver.Refused, "nine accepted"):
            self.driver.accepted(self.folder, "P")

    def test_control_files_require_identity_lists_and_a_nonempty_frozen_set(self):
        item = {"commit": "a" * 40, "item": "a" * 10}
        directory = self.folder / "controls" / item["item"]
        good = {"cases.json": {"commit": item["commit"], "cases": ["one", "two"]},
            "parent.json": {"commit": item["commit"], "passed": ["one"]}}
        for name, value in good.items():
            write_json(directory / name, value)
        self.assertEqual(self.driver.control_data(self.folder, item), [{"one", "two"}, {"one"}])
        for name in good:
            for value in (None, [], {}, {"commit": "b" * 40}, {"commit": item["commit"], "cases": "wrong", "passed": "wrong"}):
                path = directory / name
                path.unlink()
                if value is not None:
                    write_json(path, value)
                with self.subTest(name=name, value=value), self.assertRaisesRegex(self.driver.Refused, item["item"]):
                    self.driver.control_data(self.folder, item)
                write_json(path, good[name])
        write_json(directory / "cases.json", {"commit": item["commit"], "cases": []})
        with self.assertRaisesRegex(self.driver.Refused, "empty"):
            self.driver.control_data(self.folder, item)
        write_json(directory / "stopped.json", {"commit": item["commit"], "reason": "Stopped."})
        self.assertIsNone(self.driver.control_data(self.folder, item))


if __name__ == "__main__":
    unittest.main()
