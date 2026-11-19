#!/usr/bin/env python3
"""Real git fixtures; no room, jail or model is run."""
import ast
import collections
import hashlib
import importlib.util
import json
import os
from pathlib import Path
import re
import subprocess
import sys
import tempfile
import unittest
from unittest import mock

sys.dont_write_bytecode = True
HERE = Path(__file__).resolve().parent
ROOT = HERE.parents[2]


def module(name="documents_plan"):
    spec = importlib.util.spec_from_file_location(name, HERE / (name + ".py"))
    value = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(value)
    return value


def git(repo, *words):
    done = subprocess.run(["git", "-c", "user.name=fixture", "-c", "user.email=fixture@invalid",
        "-c", "commit.gpgsign=false", "-C", str(repo), *words], capture_output=True)
    if done.returncode:
        raise AssertionError(done.stderr.decode())
    return done.stdout.decode().strip()


class Fixture(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.tmp = Path(self.temp.name)
        self.items = self.tmp / "items"
        self.repo = self.items / "repo"
        self.repo.mkdir(parents=True)
        self.tasks = self.tmp / "tasks"
        self.tasks.mkdir()
        git(self.repo, "init", "-q", "--template=")
        for path, text in {
            "peer/superyak_peer/work.py": "old_value = 1\n",
            "peer/tests/test_work.py": "def test_old(): pass\n",
            "docs/plans/z-plan.md": "# Plan\nnew_behavior\nrare common words\n",
            "docs/specs/design.md": "new_behavior\n",
            "docs/specs/other.md": "Unrelated note.\n",
            "docs/plans/a-plan.md": "other words\n",
            "docs/plans/b-plan.md": "unrelated\n",
            "docs/plans/c-plan.md": "more unrelated\n",
            "README.md": "common words\n",
        }.items():
            target = self.repo / path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(text)
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "parent")
        self.parent = git(self.repo, "rev-parse", "HEAD")
        (self.repo / "peer/superyak_peer/work.py").write_text("old_value = 1\ndef new_behavior(): pass\n")
        (self.repo / "peer/tests/test_work.py").write_text("def test_new(): pass\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "work")
        self.commit = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "checkout", "-q", "--detach", self.parent)
        meta = {"parent": self.parent, "tests": [{"path": "peer/tests/test_work.py",
            "blob": git(self.repo, "rev-parse", self.commit + ":peer/tests/test_work.py")}]}
        check = self.repo / ".yak-check/item.json"
        check.parent.mkdir()
        check.write_text(json.dumps(meta))
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "item base")
        self.base = git(self.repo, "rev-parse", "HEAD")
        git(self.repo, "update-ref", "refs/yak-items/%s/base" % self.commit, self.base)
        self.entry = {"commit": self.commit, "base": self.base, "reference": self.commit, "wrong": self.base}
        self.list = self.items / "list/items.json"
        self.list.parent.mkdir()
        self.list.write_text(json.dumps({"commits": [self.entry]}))
        self.census = self.tmp / "census.txt"
        self.census.write_text(self.commit + " scored 0 1 passed\n")
        self.task = self.tasks / (self.commit[:10] + ".task.md")
        self.task.write_bytes(b"Please provide rare behavior.\n")
        (self.tasks / (self.commit[:10] + ".facts.md")).write_text("Required facts.\n")
        self.yak = self.tmp / "yak"
        self.yak.write_text("#!/bin/sh\nprintf '%s\\n' '--turn-secs <TURN_SECS> [default: 1200]' '--lease-secs <LEASE_SECS> [default: 1800]'\n")
        self.yak.chmod(0o755)
        self.worker = self.tmp / "worker"
        self.worker.write_text("#!/bin/sh\nexit 0\n")
        self.worker.chmod(0o755)
        self.env = dict(os.environ, YAK=str(self.yak), YAK_PROBE_PATH=os.environ["PATH"],
            YAK_JAIL_READ=str(self.tmp / "readable"), USER="fixture", LOGNAME="fixture")
        self.out = self.tmp / "pilot"
        self.driver = module()

    def make(self):
        with mock.patch.dict(os.environ, self.env):
            return self.driver.make_plan(self.items, self.tasks, self.out,
                "script:" + str(self.worker), self.census, expected=None,
                expected_list_sha256=hashlib.sha256(self.list.read_bytes()).hexdigest())


class Maker(Fixture):
    def test_script_path_is_absolute_and_worker_lookup_is_pinned(self):
        with mock.patch.dict(os.environ, self.env):
            with self.assertRaisesRegex(self.driver.Refused, "absolute"):
                self.driver.runtime_pins(self.items, self.out,
                    "script:" + os.path.relpath(self.worker, Path.cwd()), None, 1200, 300)
        early, late = self.tmp / "early", self.tmp / "late"
        early.mkdir()
        late.mkdir()
        worker = late / "codex"
        worker.write_text("#!/bin/sh\necho fixture-version\n")
        worker.chmod(0o755)
        self.env["YAK_PROBE_PATH"] = os.pathsep.join((str(early), str(late), os.environ["PATH"]))
        with mock.patch.dict(os.environ, self.env):
            plan = self.driver.make_plan(self.items, self.tasks, self.out, "codex:fixture", self.census, expected=None,
                expected_list_sha256=hashlib.sha256(self.list.read_bytes()).hexdigest())
        self.assertEqual(plan["worker"], {"name": "codex:fixture", "version": "fixture-version", "model": "fixture"})
        self.assertEqual(self.driver.load_plan(self.out), plan)
        shadow = early / "codex"
        shadow.write_text("#!/bin/sh\necho different\n")
        shadow.chmod(0o755)
        with self.assertRaisesRegex(self.driver.Refused, "worker lookup"):
            self.driver.load_plan(self.out)

    def test_output_directory_cannot_hold_full_id(self):
        self.out = self.tmp / ("a" * 32) / "pilot"
        with self.assertRaisesRegex(self.driver.Refused, "directory.*hexadecimal"):
            self.make()
        self.assertFalse(self.out.exists())

    def test_cli_show_and_refusal(self):
        plan = self.make()
        done = subprocess.run(["sh", str(HERE / "documents.sh"), "show", str(self.out)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 0, done.stderr)
        self.assertEqual(json.loads(done.stdout), plan)
        (self.out / "plan.json").write_text("{}")
        done = subprocess.run([sys.executable, "-I", str(HERE / "documents_plan.py"), "show", str(self.out)], capture_output=True, text=True)
        self.assertEqual(done.returncode, 1)
        self.assertIn("REFUSED: plan.json", done.stderr)

    def test_task_cannot_change_between_search_and_freeze(self):
        rank = self.driver.rank_documents
        def changed(*args):
            result = rank(*args)
            self.task.write_text("A different task.\n")
            return result
        with mock.patch.object(self.driver, "rank_documents", side_effect=changed):
            with self.assertRaisesRegex(self.driver.Refused, "task.*changed"):
                self.make()

    def test_runtime_and_task_refusals(self):
        for worker in ("unknown:model", "codex:", "script:", "codex:two words", "script:missing"):
            with self.subTest(worker=worker), mock.patch.dict(os.environ, self.env):
                with self.assertRaises(self.driver.Refused):
                    self.driver.runtime_pins(self.items, self.out, worker, None, 1200, 300)
        for limits in ((0, 1200, 300), (-1, 1200, 300), (None, 0, 300), (None, 1200, 0)):
            with self.subTest(limits=limits), mock.patch.dict(os.environ, self.env):
                with self.assertRaisesRegex(self.driver.Refused, "positive"):
                    self.driver.runtime_pins(self.items, self.out, "script:" + str(self.worker), *limits)
        with self.assertRaisesRegex(self.driver.Refused, "expected one facts"):
            self.driver.task_path(self.tmp, self.commit, "facts")
        with self.assertRaisesRegex(self.driver.Refused, "cohort differs"):
            with mock.patch.dict(os.environ, self.env):
                self.driver.make_plan(self.items, self.tasks, self.out, "script:" + str(self.worker), self.census,
                    expected_list_sha256=hashlib.sha256(self.list.read_bytes()).hexdigest())
        self.assertFalse(self.out.exists())

    def test_item_list_hash_is_required_even_with_fixture_cohort(self):
        with mock.patch.dict(os.environ, self.env):
            with self.assertRaisesRegex(self.driver.Refused, "items.json sha256 differs: expected 4b25d330"):
                self.driver.make_plan(self.items, self.tasks, self.out,
                    "script:" + str(self.worker), self.census, expected=None)
        self.assertFalse(self.out.exists())
        expected = hashlib.sha256(self.list.read_bytes()).hexdigest()
        self.list.write_bytes(self.list.read_bytes() + b"\n")
        with mock.patch.dict(os.environ, self.env):
            with self.assertRaisesRegex(self.driver.Refused, "items.json sha256 differs"):
                self.driver.make_plan(self.items, self.tasks, self.out,
                    "script:" + str(self.worker), self.census, expected=None, expected_list_sha256=expected)
        plan = self.make()
        self.assertEqual(plan["list_sha256"], hashlib.sha256(self.list.read_bytes()).hexdigest())

    def test_small_check_requires_git_difference_exit(self):
        script = self.driver.check_script(self.parent)
        shell = __import__("shutil").which("sh")
        fake_bin = self.tmp / "check-bin"
        fake_bin.mkdir()
        fake_git = fake_bin / "git"
        for status in (0, 1, 2, 127, 128):
            with self.subTest(status=status):
                fake_git.write_text("#!/bin/sh\nexit %s\n" % status)
                fake_git.chmod(0o755)
                done = subprocess.run([shell], input=script, capture_output=True,
                    cwd=self.repo, env=dict(os.environ, PATH=str(fake_bin)))
                self.assertEqual(done.returncode, 0 if status == 1 else 1, done.stderr)
                self.assertEqual(done.stdout, b"ok\n" if status == 1 else b"")
        fake_git.unlink()
        missing = subprocess.run([shell], input=script, capture_output=True,
            cwd=self.repo, env=dict(os.environ, PATH=str(fake_bin)))
        self.assertEqual(missing.returncode, 1)
        unchanged = subprocess.run([shell], input=script, capture_output=True, cwd=self.repo)
        self.assertEqual(unchanged.returncode, 1)
        (self.repo / "peer/superyak_peer/work.py").write_text("changed_value = 2\n")
        git(self.repo, "add", ".")
        git(self.repo, "commit", "-qm", "source changed")
        changed = subprocess.run([shell], input=script, capture_output=True, cwd=self.repo)
        self.assertEqual(changed.returncode, 0, changed.stderr)
        absent = subprocess.run([shell], input=self.driver.check_script("0" * 40), capture_output=True, cwd=self.repo)
        self.assertEqual(absent.returncode, 1)

    def test_selection_and_ranking(self):
        selected = self.driver.select_items(self.repo, [self.entry], self.driver.census_passes(self.census))
        self.assertEqual(len(selected), 1)
        item = selected[0]
        self.assertEqual(item["item"], self.commit[:10])
        self.assertEqual(item["parent"], self.parent)
        self.assertEqual(item["matching"], ["docs/plans/z-plan.md", "docs/specs/design.md"])
        self.assertEqual(item["direct_path"], "docs/plans/z-plan.md")
        ranked = self.driver.rank_documents(self.driver.markdown(self.repo, self.parent),
            b"rare rare common behavior", item["matching"], self.commit)
        self.assertEqual(ranked["search"]["three"][0], "docs/plans/z-plan.md")
        self.assertEqual(ranked["search"]["best_place"], 1)
        self.assertEqual(ranked["search"]["tied"], 1)
        self.assertEqual(ranked["newest"]["three"], ["docs/plans/z-plan.md", "docs/plans/c-plan.md", "docs/plans/b-plan.md"])
        self.assertEqual(ranked["newest"]["best_place"], 1)
        wanted = sorted(["docs/plans/a-plan.md", "docs/plans/b-plan.md", "docs/plans/c-plan.md", "docs/specs/other.md"],
            key=lambda p: hashlib.sha256(("20261118:lot:%s:%s" % (self.commit, p)).encode("ascii")).hexdigest())[:3]
        self.assertEqual(ranked["lot"]["three"], wanted)
        self.assertEqual(len(set(ranked["lot"]["three"])), 3)

    def test_selection_refuses_test_function_and_nonpassing_reference(self):
        docs = self.driver.markdown(self.repo, self.parent)
        docs["docs/specs/design.md"]["text"] += "\n    def test_leak(): pass\n"
        with mock.patch.object(self.driver, "markdown", return_value=docs):
            self.assertEqual(self.driver.select_items(self.repo, [self.entry], {self.commit}), [])
            self.assertEqual(len(self.driver.select_items(self.repo, [self.entry], {self.commit}, exclude_test_functions=False)), 1)
        docs["docs/specs/design.md"]["text"] = docs["docs/specs/design.md"]["text"].replace("def test_", "async def test_")
        with mock.patch.object(self.driver, "markdown", return_value=docs):
            self.assertEqual(len(self.driver.select_items(self.repo, [self.entry], {self.commit})), 1)
        self.assertEqual(self.driver.select_items(self.repo, [self.entry], set()), [])

    def test_paragraphs_bases_pins_and_directory_names(self):
        plan = self.make()
        item = plan["items"][0]
        self.assertEqual(plan["v"], 1)
        self.assertEqual(plan["seed"], 20261118)
        self.assertEqual(set(item["rows"]), {"nothing-1", "nothing-2", "exists", "path", "search", "newest", "lot"})
        self.assertEqual(item["rows"]["exists"]["paragraph"], "There is a plan for this work in the repository.")
        self.assertEqual(item["rows"]["path"]["paragraph"], "The plan for this work is in the repository at `docs/plans/z-plan.md`.")
        for name in ("search", "newest", "lot"):
            self.assertEqual(item["rows"][name]["paragraph"], "These documents in the repository may bear on this work:\n" +
                "\n".join("- `" + p + "`" for p in item[name]["three"]))
        common = self.task.read_bytes() + b"\nMake this change in the code under `peer/superyak_peer`. Add tests for it if you like.\n"
        for name, row in item["rows"].items():
            content = self.driver.git(self.out / "src", "show", row["base"] + ":TASK.md")
            expected = common + (("\n" + row["paragraph"] + "\n").encode() if row["paragraph"] else b"")
            self.assertEqual(content, expected)
            self.assertEqual(hashlib.sha256(content).hexdigest(), row["task_file_sha256"])
            self.assertEqual(git(self.out / "src", "rev-parse", row["base"] + "^"), self.parent)
            self.assertEqual(set(git(self.out / "src", "diff", "--name-only", self.parent, row["base"]).splitlines()),
                {"TASK.md", ".yak-check/probe.sh"})
            self.assertEqual(git(self.out / "src", "rev-parse", "refs/documents/%s/%s" % (item["item"], name)), row["base"])
            changed = git(self.out / "src", "diff", "--name-only", item["rows"]["nothing-1"]["base"], row["base"]).splitlines()
            self.assertEqual(changed, [] if name.startswith("nothing") else ["TASK.md"])
        self.assertEqual(self.driver.load_plan(self.out), plan)
        self.assertEqual(plan["limits"], {"worker_secs": 1200, "check_secs": 900, "replay_secs": 1200,
            "diagnostic_secs": 300, "lease_secs": 1800})
        self.assertEqual(plan["worker"]["name"], "script:" + str(self.worker))
        self.assertEqual(plan["worker"]["model"], "script")
        self.assertTrue(plan["inputs"])
        for directory in self.out.rglob("*"):
            if directory.is_dir():
                self.assertIsNone(re.search("[0-9a-fA-F]{32}", directory.name))

    def test_changed_input_task_plan_are_refused(self):
        self.make()
        original = self.task.read_bytes()
        self.task.write_bytes(original + b"changed")
        with self.assertRaisesRegex(self.driver.Refused, "task.md"):
            self.driver.load_plan(self.out)
        self.task.write_bytes(original)
        raw = (self.out / "plan.json").read_bytes()
        (self.out / "plan.json").write_bytes(raw + b" ")
        with self.assertRaisesRegex(self.driver.Refused, "plan.json"):
            self.driver.load_plan(self.out)
        (self.out / "plan.json").write_bytes(raw)
        self.yak.write_text("changed")
        with self.assertRaisesRegex(self.driver.Refused, "yak"):
            self.driver.load_plan(self.out)

    def test_proof_rejects_difference_outside_task_and_wrong_parent(self):
        plan = self.make()
        item = plan["items"][0]
        altered = json.loads(json.dumps(item))
        altered["rows"]["exists"]["base"] = altered["rows"]["exists"]["wrong"]
        with self.assertRaisesRegex(self.driver.Refused, "parent"):
            self.driver.prove_bases(self.out / "src", altered, self.task.read_bytes())
        altered = json.loads(json.dumps(item))
        altered["rows"]["exists"]["task_file_sha256"] = "0" * 64
        with self.assertRaisesRegex(self.driver.Refused, "TASK.md"):
            self.driver.prove_bases(self.out / "src", altered, self.task.read_bytes())
        # A real sibling base with the right parent and identical TASK.md, but
        # different source, must fail the proof even if the task hashes match.
        altered = json.loads(json.dumps(item))
        src = self.out / "src"
        index = self.tmp / "counterexample.index"
        self.driver.git_as(src, "read-tree", item["rows"]["exists"]["base"], index=index)
        blob = self.driver.git_as(src, "hash-object", "-w", "--stdin", data=b"changed_value = 2\n").decode().strip()
        self.driver.git_as(src, "update-index", "--cacheinfo", "100644,%s,peer/superyak_peer/work.py" % blob, index=index)
        tree = self.driver.git_as(src, "write-tree", index=index).decode().strip()
        counterexample = self.driver.git_as(src, "commit-tree", tree, "-p", item["parent"], "-m", "outside task").decode().strip()
        self.assertEqual(git(src, "show", counterexample + ":TASK.md"),
            git(src, "show", item["rows"]["exists"]["base"] + ":TASK.md"))
        self.assertEqual(git(src, "show", "-s", "--format=%P", counterexample), item["parent"])
        altered["rows"]["exists"]["base"] = counterexample
        with self.assertRaisesRegex(self.driver.Refused, "outside TASK.md"):
            self.driver.prove_bases(src, altered, self.task.read_bytes())


class Rules(unittest.TestCase):
    def test_census_parser_only_accepts_passing_reference(self):
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "census.txt"
            path.write_text("a scored 0 1 passed\nb scored 1 1 passed\nc scored 0 1 failed\nd passed\n")
            self.assertEqual(module().census_passes(path), {"a"})

    def test_name_and_document_boundaries(self):
        d = module()
        good = {"docs/plans/a.md": {"text": "abc_defg"}}
        self.assertEqual(dict(d.matching_documents("+def abc_defg():", "", good)),
            {"docs/plans/a.md": {"abc_defg"}})
        for name in ("ab_cdef", "abcdefgh", "_abcdefg", "abcdefg_", "__abcdefg"):
            self.assertEqual(dict(d.matching_documents("+def %s():" % name, "", {"plans/a.md": {"text": name}})), {})
        for name in ("a_bcdefg", "abcdef_g", "ABC_DEFG"):
            self.assertTrue(d.matching_documents("+def %s():" % name, "", {"plans/a.md": {"text": name}}))
        self.assertTrue(d.matching_documents("+ABC_DEFG = 1", "", {"plans/a.md": {"text": "ABC_DEFG"}}))
        for line in ("+    def ab_12345():", "+    async def ab_12345():", "+    class ab_12345:"):
            self.assertTrue(d.matching_documents(line, "", {"plans/a.md": {"text": "ab_12345"}}))
        for line in ("+    ABC_DEFG = 1", "+abc_defg = 1"):
            self.assertFalse(d.matching_documents(line, "", {"plans/a.md": {"text": "ABC_DEFG abc_defg"}}))
        self.assertEqual(dict(d.matching_documents("+def abc_defg():", "abc_defg", good)), {})
        self.assertTrue(d.matching_documents("+def abc_defg():", "xabc_defgx", good))
        five = {"plans/%s.md" % n: {"text": "abc_defg"} for n in range(5)}
        self.assertEqual(len(d.matching_documents("+def abc_defg():", "", five)), 5)
        five["other.md"] = {"text": "abc_defg"}
        self.assertEqual(dict(d.matching_documents("+def abc_defg():", "", five)), {})
        self.assertFalse(d.under("plans.md", "plans"))
        self.assertFalse(d.under("x/myplans/a.md", "plans"))
        self.assertTrue(d.under("plans/a.md", "plans"))

    def test_search_half_threshold_ties_and_task_bytes(self):
        d = module()
        docs = {"plans/%s.md" % n: {"text": "ubiquitous " + ("specific " if n < 3 else "") +
            ("halfword " if n < 2 else "")} for n in range(4)}
        ranked = d.rank_documents(docs, b"ubiquitous specific halfword halfword", ["plans/0.md"], "a" * 40)
        self.assertEqual(ranked["search"], {"three": ["plans/0.md", "plans/1.md", "plans/2.md"], "best_place": 1, "tied": 2})
        self.assertEqual(d.task_bytes(b"Work", ""), b"Work\n\n" + d.FIXED.encode() + b"\n")
        with self.assertRaisesRegex(d.Refused, "fewer than three"):
            d.rank_documents({"plans/a.md": {"text": ""}}, b"", ["plans/a.md"], "a" * 40)
        for commits in (["a" * 39], ["A" * 40], ["a" * 40, "a" * 40]):
            with self.assertRaises(d.Refused):
                d.distinct_items(commits)

    def test_order_84_hashes_stable_and_full_commit(self):
        driver = module()
        commits = ["%040x" % n for n in range(12)]
        actual = driver.row_order(commits)
        expected = sorted((hashlib.sha256(("20261118:order:%s:%s" % (c, r)).encode("ascii")).hexdigest(), c, r)
            for c in commits for r in ("nothing-1", "nothing-2", "exists", "path", "search", "newest", "lot"))
        self.assertEqual([(r["hash"], r["commit"], r["row"]) for r in actual], expected)
        self.assertEqual([r["n"] for r in actual], list(range(1, 85)))
        for row in actual:
            self.assertEqual(row["item"], row["commit"][:10])
            self.assertEqual(row["directory"], "rows/%03d-%s-%s" % (row["n"], row["commit"][:10], row["row"]))
        self.assertEqual(actual, driver.row_order(list(reversed(commits))))

    def test_collision_is_refused(self):
        driver = module()
        with self.assertRaisesRegex(driver.Refused, "first ten"):
            driver.distinct_items(["a" * 40, "a" * 10 + "b" * 30])

    def test_frozen_twelve_ids_selected_by_rules_from_repository_history(self):
        driver = module()
        census_file = HERE / "census-2026-11-18.txt"
        census = driver.census_passes(census_file)
        # Include failing references too, so removing rule 1 changes the census.
        commits = [line.split()[0] for line in census_file.read_text().splitlines()]
        entries = [{"commit": c, "reference": c} for c in commits]
        first_two = driver.select_items(ROOT, entries, census, exclude_test_functions=False)
        self.assertEqual(len(first_two), 40)
        selected = driver.select_items(ROOT, entries, census)
        self.assertEqual({i["commit"][:8] for i in selected}, {
            "9a3f21cf", "71a593d5", "d20c739b", "cd884db7", "c9ceb15b", "671a2250",
            "1113f1db", "0193bde8", "fff1b349", "027834bf", "3879e609", "3f349e89"})
        groups = collections.Counter(i["plan_group"] for i in selected)
        self.assertEqual(sorted(groups.values()), [1, 1, 1, 2, 3, 4])

    def test_python_39(self):
        for path in HERE.glob("*.py"):
            ast.parse(path.read_bytes(), feature_version=(3, 9))


if __name__ == "__main__":
    unittest.main()
