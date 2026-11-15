#!/usr/bin/env python3
"""Tests of records.py and of ../block-check.sh. Run as: python3 -I test_records.py

No model, no clock and no room are run: every record here is made by hand, and the room program and the
workers' programs are scripts that print what the real ones would.
"""
import contextlib
import importlib.util
import io
import json
import math
import os
import shutil
import stat
import subprocess
import sys
import tempfile
import unittest

# Nothing is left beside the scripts by running these.
sys.dont_write_bytecode = True
HERE = os.path.dirname(os.path.abspath(__file__))
spec = importlib.util.spec_from_file_location("records", os.path.join(HERE, "records.py"))
assert spec is not None and spec.loader is not None
records = importlib.util.module_from_spec(spec)
spec.loader.exec_module(records)

HELP = """Usage: yak clock run [OPTIONS] --worker <WORKER>...

Options:
      --once-through
      --lease-secs <LEASE_SECS>    [default: 1800]
      --turn-secs <TURN_SECS>      [default: 1200]
      --daily-turns <DAILY_TURNS>  [default: 40]
      --concurrent <CONCURRENT>    [default: 1]
      --own-prompts                Begin each turn's prompt with a line of that turn's own
"""


def script(path, body):
    with open(path, "w", encoding="utf-8") as out:
        out.write("#!/bin/sh\n" + body + "\n")
    os.chmod(path, os.stat(path).st_mode | stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH)
    return path


def measured(ended="exited", active=3000, worker=2000, check=500, **more):
    record = {"ended": ended, "exit_code": 0, "sandbox_ms": active - worker - (check or 0) - 20, "worker_ms": worker,
              "seal_ms": 10, "bring_ms": 10, "check_ms": check, "recheck_ms": None, "active_ms": active,
              "steps_seen": 2, "unknown_steps": 1, "unknown_changes": 0,
              "tokens": {"fresh_in": 1, "cache_write": 2, "cache_read": 3, "output": 4, "reasoning": 0,
                         "complete": True}}
    record.update(more)
    return record


def turn(by="claude:opus", passed: "bool | None" = True, **of_record):
    """One attempt as the room prints it: taken by `by`, with a record made by `measured`."""
    return {"attempt": "a1", "lease_no": 1, "worker": by, "state": "finished", "commit": "c" * 40,
            "passed": passed, "measured": measured(**of_record), "changes": [], "steps": 2, "steps_with_a_name": 1}


def a_manifest(slug="item-a", worker="claude:opus", own=True):
    return {"slug": slug, "worker": worker, "limits": {"own_prompts": own}}


class Made(unittest.TestCase):
    def setUp(self):
        held = tempfile.TemporaryDirectory()
        self.addCleanup(held.cleanup)
        self.tmp = held.name

    def a_turn(self, name, turns=None, code="0", plan=None, without=(), times=("10:00:00", "10:01:00")):
        """A turn's directory as turn.sh leaves one."""
        path = os.path.join(self.tmp, name)
        os.makedirs(path)
        files = {"manifest.json": json.dumps(plan if plan is not None else a_manifest()),
                 "turns.json": json.dumps([turn()] if turns is None else turns),
                 "clock.exit": code + "\n", "started.txt": f"2026-11-15 {times[0]} UTC\n",
                 "ended.txt": f"2026-11-15 {times[1]} UTC\n"}
        for file, text in files.items():
            if file not in without:
                with open(os.path.join(path, file), "w", encoding="utf-8") as out:
                    out.write(text)
        return path

    def problems(self, *args, **kwargs):
        return records.observation(self.a_turn("t", *args, **kwargs))[2]


class OneTurn(Made):
    def test_a_turn_that_passed_is_one_usable_observation(self):
        self.assertEqual(self.problems(), [])

    def test_a_turn_that_failed_its_check_is_one_usable_observation(self):
        self.assertEqual(self.problems(turns=[turn(passed=False)], code="1"), [])

    def test_a_turn_that_ran_twenty_minutes_to_its_limit_is_one_usable_observation(self):
        late = turn(passed=False, ended="timed_out", active=1_216_000, worker=1_200_000, check=15_000)
        late["measured"]["tokens"] = {"fresh_in": None, "cache_write": None, "cache_read": None, "output": None,
                                      "reasoning": None, "complete": False}
        self.assertEqual(self.problems(turns=[late], code="1"), [])

    def test_a_program_ended_by_a_signal_is_one_usable_observation(self):
        self.assertEqual(self.problems(turns=[turn(passed=False, ended="signalled")]), [])

    def test_what_is_not_one_usable_observation_is_said(self):
        nothing_measured = turn()
        nothing_measured["measured"] = None
        no_verdict = turn(passed=None)
        do_not_add_up = turn(sandbox_ms=1)
        no_worker_time = turn(worker=0, check=500, active=3000)
        cases = [
            ("no record", {"without": ("turns.json",)}, "no record"),
            ("an empty record", {"turns": []}, "0 attempts"),
            ("two attempts", {"turns": [turn(), turn()]}, "2 attempts"),
            ("another worker", {"turns": [turn(by="codex:gpt-6.1-sol")]}, "taken by codex:gpt-6.1-sol"),
            ("nothing measured", {"turns": [nothing_measured]}, "no measured record"),
            ("not run", {"turns": [turn(ended="not_run")]}, "did not run"),
            ("stopped", {"turns": [turn(ended="stopped")]}, "did not run"),
            ("lease lost", {"turns": [turn(ended="lease_lost")]}, "did not run"),
            ("unknown end", {"turns": [turn(ended="unknown")]}, "did not run"),
            ("parts that do not add up", {"turns": [do_not_add_up]}, "do not add up"),
            ("no time for the worker", {"turns": [no_worker_time]}, "no time for its worker"),
            ("no verdict", {"turns": [no_verdict]}, "no verdict"),
            ("a clock that was ended", {"without": ("clock.exit",)}, "exit was not written"),
            ("a clock killed", {"code": "137"}, "ended with 137"),
            ("no manifest", {"without": ("manifest.json",)}, "no manifest"),
            # Parts that add up and are not durations: one below nothing, one that is not a number at all.
            ("a time below nothing", {"turns": [turn(sandbox_ms=-500, active=2000, worker=2000, check=480)]},
             "not a whole number of milliseconds"),
            ("a time that is true", {"turns": [turn(seal_ms=True, bring_ms=19)]}, "not a whole number"),
            ("a check's time below nothing", {"turns": [turn(check=-5, sandbox_ms=985)]}, "not a whole number"),
            ("a check's time in words", {"turns": [turn(check_ms="soon")]}, "not a whole number"),
        ]
        for at, (name, how, says) in enumerate(cases):
            with self.subTest(name):
                found = records.observation(self.a_turn(f"case-{at}", **how))[2]
                self.assertTrue(any(says in problem for problem in found), found)

    def test_the_check_says_ok_or_why_not_and_exits_so(self):
        good = self.a_turn("good")
        bad = self.a_turn("bad", turns=[])
        for path, code, says in [(good, 0, "ok: one usable observation"), (bad, 1, "REFUSED: 0 attempts")]:
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                self.assertEqual(records.main(["records.py", "check", path]), code)
            self.assertIn(says, out.getvalue())


class APilot(Made):
    def a_pilot(self, plan, before="ok", after="ok"):
        with open(os.path.join(self.tmp, "plan.txt"), "w", encoding="utf-8") as out:
            out.write("".join(line + "\n" for line in plan))
        for name, last in (("block-before.txt", before), ("block-after.txt", after)):
            if last is not None:
                with open(os.path.join(self.tmp, name), "w", encoding="utf-8") as out:
                    out.write(f"absent /x\n{last}\n")

    def printed(self, *more):
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = records.main(["records.py", "tables", self.tmp, *more])
        return code, out.getvalue()

    def test_a_whole_pilot_prints_every_turn_and_the_spread_over_all_of_them(self):
        self.a_pilot(["1 thrown-away item-a claude:opus --own-prompts", "2 round-1 item-a claude:opus --own-prompts",
                      "3 round-2 item-a claude:opus --own-prompts", "4 round-3 item-a claude:opus --own-prompts"])
        self.a_turn("1-thrown-away-item-a", times=("10:00:00", "10:02:00"))
        # One second, two and four: one passed, one failed its check, one ran to its limit.
        self.a_turn("2-round-1-item-a", turns=[turn(active=1000, worker=400, check=500)],
                    times=("10:02:30", "10:03:00"))
        self.a_turn("3-round-2-item-a", turns=[turn(passed=False, active=2000, worker=1400, check=500)], code="1",
                    times=("10:03:45", "10:04:00"))
        self.a_turn("4-round-3-item-a", turns=[turn(passed=False, ended="timed_out", active=4000, worker=3400)],
                    code="1")
        self.assertEqual(records.gathered(self.tmp)[1], [])
        code, out = self.printed()
        self.assertEqual(code, 0)
        self.assertNotIn("REFUSED", out)
        for slot in ("| 1 | thrown-away |", "| 2 | round-1 |", "| 3 | round-2 |", "| 4 | round-3 |"):
            self.assertEqual(out.count(slot), 1, out)
        # How long it was since the same worker's turn before: nothing for its first, then from the files.
        gaps = [line.split(" | ")[8] for line in out.splitlines() if line.startswith(("| 1 |", "| 2 |", "| 3 |"))]
        self.assertEqual(gaps, ["", "30", "45"])
        # All three measured turns are in the spread: a geometric mean of 2 and a spread of ln 2. The turn that
        # was thrown away is not.
        row = [line for line in out.splitlines() if line.startswith("| item-a | claude:opus | 3 of 3 | 1 |")]
        self.assertEqual(len(row), 1, out)
        self.assertIn("| 1 2 4 | 2 | 0.693 |", row[0])
        self.assertAlmostEqual(records.of_logs([1, 2, 4])[1], math.log(2), places=12)

    def test_a_pilot_that_is_not_whole_prints_no_table_unless_asked_and_then_says_so_first(self):
        whole = ["1 round-1 item-a claude:opus --own-prompts", "2 round-1 item-b codex:gpt-6.1-sol --own-prompts"]
        cases = [
            ("a turn not run", lambda: None, "turn 2 (round-1, item-b): not run"),
            ("an empty record", lambda: self.a_turn("2-round-1-item-b", turns=[],
                                                    plan=a_manifest("item-b", "codex:gpt-6.1-sol")),
             "turn 2 (round-1, item-b): 0 attempts"),
            ("a turn run twice", lambda: self.a_turn("2-round-1-item-b", turns=[turn("codex:gpt-6.1-sol")] * 2,
                                                     plan=a_manifest("item-b", "codex:gpt-6.1-sol")),
             "turn 2 (round-1, item-b): 2 attempts"),
            ("another worker than planned", lambda: self.a_turn("2-round-1-item-b", turns=[turn("claude:unexpected")],
                                                                plan=a_manifest("item-b", "codex:gpt-6.1-sol")),
             "taken by claude:unexpected"),
            ("a manifest for another item", lambda: self.a_turn("2-round-1-item-b", turns=[turn("codex:gpt-6.1-sol")],
                                                                plan=a_manifest("item-a", "codex:gpt-6.1-sol")),
             "its manifest is for item-a"),
            ("a first line not as planned", lambda: self.a_turn(
                "2-round-1-item-b", turns=[turn("codex:gpt-6.1-sol")],
                plan=a_manifest("item-b", "codex:gpt-6.1-sol", own=False)), "first line of its own is not as the plan"),
        ]
        for name, make, says in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.tmp = tmp
                self.a_pilot(whole)
                self.a_turn("1-round-1-item-a")
                make()
                code, out = self.printed()
                self.assertEqual(code, 1)
                self.assertIn("REFUSED", out)
                self.assertIn(says, out)
                self.assertNotIn("| Turn |", out)
                code, out = self.printed("--partial")
                self.assertEqual(code, 0)
                self.assertLess(out.index("NOT WHOLE"), out.index("| Turn |"))
                self.assertIn(says, out)
                # The turn that is there is still printed, once, and a slot that is not usable is not counted.
                self.assertEqual(out.count("| 1 | round-1 | item-a |"), 1, out)
                self.assertIn("| item-a | claude:opus | 1 of 1 |", out)
                self.assertNotIn("| item-b | codex:gpt-6.1-sol | 1 of 1 |", out)

    def test_a_turns_directory_that_the_plan_does_not_have_refuses_the_pilot(self):
        self.a_pilot(["1 round-1 item-a claude:opus --own-prompts"])
        self.a_turn("1-round-1-item-a")
        self.a_turn("2-round-1-item-a")
        code, out = self.printed()
        self.assertEqual(code, 1)
        self.assertIn("2-round-1-item-a: a turn's directory that is not in the plan", out)
        self.assertNotIn("| Turn |", out)

    def test_a_turn_that_is_in_the_plan_twice_refuses_the_pilot(self):
        self.a_pilot(["1 round-1 item-a claude:opus --own-prompts", "1 round-1 item-a claude:opus --own-prompts"])
        self.a_turn("1-round-1-item-a")
        for more in ([], ["--partial"]):
            code, out = self.printed(*more)
            self.assertEqual(code, 1)
            self.assertIn("REFUSED: turn 1 is in the plan twice", out)
            self.assertNotIn("| Turn |", out)

    def test_a_record_that_is_not_usable_is_listed_and_its_numbers_are_not_shown(self):
        self.a_pilot(["1 round-1 item-a claude:opus --own-prompts"])
        broken = turn()
        broken["measured"]["tokens"] = None
        broken["measured"]["active_ms"] = "long"
        self.a_turn("1-round-1-item-a", turns=[broken])
        code, out = self.printed("--partial")
        self.assertEqual(code, 0)
        self.assertIn("turn 1 (round-1, item-a): a duration of its record is missing", out)
        self.assertIn("| 1 | round-1 | item-a | claude:opus | NOT USABLE |", out)
        self.assertIn("| item-a | claude:opus | 0 of 1 |", out)

    def test_the_worker_printed_is_the_one_the_record_names(self):
        self.a_pilot(["1 round-1 item-b codex:gpt-6.1-sol --own-prompts"])
        self.a_turn("1-round-1-item-b", turns=[turn("claude:unexpected")],
                    plan=a_manifest("item-b", "codex:gpt-6.1-sol"))
        _, out = self.printed("--partial")
        self.assertIn("| 1 | round-1 | item-b | claude:unexpected | NOT USABLE |", out)

    def test_a_block_check_that_did_not_end_well_at_either_end_refuses_the_pilot(self):
        for before, after, says in [("ok", None, "block-after.txt: not written"),
                                    ("ok", "REFUSED: see the lines that say THERE or CHANGED", "block-after.txt"),
                                    ("REFUSED: see the lines", "ok", "block-before.txt")]:
            with self.subTest(says), tempfile.TemporaryDirectory() as tmp:
                self.tmp = tmp
                self.a_pilot(["1 round-1 item-a claude:opus --own-prompts"], before, after)
                self.a_turn("1-round-1-item-a")
                code, out = self.printed()
                self.assertEqual(code, 1)
                self.assertIn(says, out)


class AManifest(Made):
    def programs(self, version="echo '2.1.325 (Claude Code)'"):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        script(os.path.join(bin_dir, "claude"), version)
        yak = script(os.path.join(self.tmp, "yak"), f"cat <<'HELP'\n{HELP}HELP")
        turn_dir = os.path.join(self.tmp, "1-round-1-item-a")
        os.makedirs(turn_dir)
        with open(os.path.join(self.tmp, "versions.txt"), "w", encoding="utf-8") as out:
            out.write("claude 2.1.325 (Claude Code)\n")
        return turn_dir, yak, bin_dir

    def words(self, yak, bin_dir, *more):
        return [f"PATH={bin_dir}:/usr/bin:/bin", "YAK_JAIL_READ=/tools:/vendor", "HOME=/home/someone", yak,
                "--room", "/room", "clock", "run", "--once-through", "--daily-turns", "1", "--worker",
                "claude:opus", *more]

    PAIRS = ["slot=7", "kind=round-1", "slug=item-a", "worker=claude:opus", "item=i1", "base=" + "b" * 40,
             "wrong=" + "c" * 40, "check=sh v2/checks/item-a.sh /vendor", "check_file=v2/checks/item-a.sh",
             "check_blob=" + "d" * 40]

    def test_the_clocks_command_its_environment_and_the_limits_in_force_can_be_read_back(self):
        turn_dir, yak, bin_dir = self.programs()
        words = self.words(yak, bin_dir, "--turn-secs", "5", "--own-prompts")
        records.manifest(turn_dir, self.PAIRS, list(words))
        kept = records.load(os.path.join(turn_dir, "manifest.json"))
        # The command as it was given, word for word, and apart from it the environment it was given.
        self.assertEqual(kept["argv"], words[3:])
        self.assertEqual(kept["environment"], {"PATH": f"{bin_dir}:/usr/bin:/bin", "YAK_JAIL_READ": "/tools:/vendor",
                                               "HOME": "/home/someone"})
        self.assertEqual(kept["limits"]["defaults"],
                         {"lease-secs": 1800, "turn-secs": 1200, "daily-turns": 40, "concurrent": 1})
        self.assertEqual(kept["limits"]["in_force"],
                         {"lease-secs": 1800, "turn-secs": 5, "daily-turns": 1, "concurrent": 1})
        self.assertIs(kept["limits"]["own_prompts"], True)
        self.assertEqual(kept["program"], {"name": "claude", "path": os.path.realpath(os.path.join(bin_dir, "claude")),
                                           "version": "2.1.325 (Claude Code)"})
        self.assertEqual(kept["yak"], {"path": yak, "sha256": records.sha256(yak)})
        self.assertEqual(kept["block"]["sha256"], records.sha256(os.path.join(self.tmp, "versions.txt")))
        self.assertEqual((kept["slot"], kept["kind"], kept["slug"], kept["worker"]),
                         (7, "round-1", "item-a", "claude:opus"))
        self.assertEqual((kept["base"], kept["check"], kept["check_blob"]),
                         ("b" * 40, "sh v2/checks/item-a.sh /vendor", "d" * 40))
        # Without the two words, the program's own limit and no line of the turn's own.
        other = os.path.join(self.tmp, "2-round-1-item-a")
        os.makedirs(other)
        records.manifest(other, self.PAIRS, self.words(yak, bin_dir, "--turn-secs=9"))
        kept = records.load(os.path.join(other, "manifest.json"))
        self.assertEqual((kept["limits"]["in_force"]["turn-secs"], kept["limits"]["own_prompts"]), (9, False))
        # A second manifest for one turn is refused: what was written before the turn is not written over.
        with self.assertRaises(FileExistsError):
            records.manifest(other, self.PAIRS, self.words(yak, bin_dir))

    def test_a_program_that_is_not_there_or_does_not_say_its_version_refuses_the_turn(self):
        for name, version, says in [("ends badly", "echo 2.1.325; exit 7", "ended with 7"),
                                    ("says nothing", "exit 0", "said nothing")]:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.tmp = tmp
                turn_dir, yak, bin_dir = self.programs(version)
                with self.assertRaises(records.Refused) as refused:
                    records.manifest(turn_dir, self.PAIRS, self.words(yak, bin_dir))
                self.assertIn(says, str(refused.exception))
                self.assertFalse(os.path.exists(os.path.join(turn_dir, "manifest.json")))
        turn_dir, yak, bin_dir = self.programs()
        os.remove(os.path.join(bin_dir, "claude"))
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            code = records.main(["records.py", "manifest", turn_dir, *self.PAIRS, "--", *self.words(yak, bin_dir)])
        self.assertEqual(code, 1)
        self.assertIn("REFUSED: claude is not on the path the clock is given", out.getvalue())
        self.assertFalse(os.path.exists(os.path.join(turn_dir, "manifest.json")))

    def test_a_path_with_an_entry_that_is_not_absolute_is_refused(self):
        turn_dir, yak, bin_dir = self.programs()
        for path in (f"{bin_dir}:relative/bin", f"{bin_dir}::/usr/bin", f".:{bin_dir}"):
            with self.subTest(path):
                words = self.words(yak, bin_dir)
                words[0] = f"PATH={path}"
                with self.assertRaises(records.Refused) as refused:
                    records.manifest(turn_dir, self.PAIRS, words)
                self.assertIn("not an absolute directory", str(refused.exception))
                self.assertFalse(os.path.exists(os.path.join(turn_dir, "manifest.json")))

    def test_a_limit_that_is_not_a_number_or_a_help_without_a_default_is_refused(self):
        turn_dir, yak, bin_dir = self.programs()
        with self.assertRaises(records.Refused):
            records.manifest(turn_dir, self.PAIRS, self.words(yak, bin_dir, "--turn-secs", "soon"))
        script(yak, "echo 'Usage: yak clock run'")
        with self.assertRaises(records.Refused) as refused:
            records.manifest(turn_dir, self.PAIRS, self.words(yak, bin_dir))
        self.assertIn("names no default", str(refused.exception))


class ThePlan(unittest.TestCase):
    def plan(self, **more):
        out = subprocess.run(["sh", os.path.join(HERE, "pilot.sh"), "--plan"], env={"PATH": "/usr/bin:/bin", **more},
                             capture_output=True, text=True)
        self.assertEqual(out.returncode, 0, out.stderr)
        return [line.split() for line in out.stdout.splitlines()]

    def test_the_plan_is_the_twenty_one_turns_the_experiment_names_in_their_order(self):
        plan = self.plan()
        self.assertEqual([int(words[0]) for words in plan], list(range(1, 22)))
        a = ["item-add-wrong-commit", "claude:opus"]
        b = ["item-add-title", "codex:gpt-6.1-sol"]
        c = ["item-add-check-freezable", "claude:opus"]
        own = ["--own-prompts"]
        # A turn thrown away with the line, the pair without it, the pair with it, and one thrown away for the
        # other worker.
        self.assertEqual([words[1:] for words in plan[:6]],
                         [["thrown-away"] + a + own, ["memory-without"] + a, ["memory-without"] + a,
                          ["memory-with"] + a + own, ["memory-with"] + a + own, ["thrown-away"] + b + own])
        # Then five rounds, one of each item and round again, each with the line.
        rounds = plan[6:]
        self.assertEqual([words[1:] for words in rounds],
                         [[f"round-{n}"] + item + own for n in range(1, 6) for item in (a, b, c)])
        for item in (a, b, c):
            at = [index for index, words in enumerate(rounds) if words[2:4] == item]
            self.assertEqual(len(at), 5)
            self.assertTrue(all(later - earlier == 3 for earlier, later in zip(at, at[1:])), at)
        # Every worker that has a measured turn has one thrown away before it.
        for worker in {words[3] for words in rounds}:
            first = min(index for index, words in enumerate(plan) if words[3] == worker)
            self.assertEqual(plan[first][1], "thrown-away", worker)

    def test_a_dress_rehearsal_cuts_the_rounds_and_nothing_else(self):
        self.assertEqual(self.plan(YAK_PILOT_ROUNDS="1"), self.plan()[:9])


class TheDrivers(Made):
    """pilot.sh and turn.sh themselves, with everything they start a script: that a lost turn stops them."""

    def programs(self):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir)
        for name in ("claude", "codex"):
            script(os.path.join(bin_dir, name), f"echo '0.0.0 (a stand-in for {name})'")
        for tool in TheBlockCheck.TOOLS + ("sha256sum", "shasum", "python3", "git", "date", "uptime", "env", "mkdir",
                                           "tr", "wc", "sh"):
            found = shutil.which(tool)
            if found and not os.path.lexists(os.path.join(bin_dir, tool)):
                os.symlink(found, os.path.join(bin_dir, tool))
        return bin_dir

    def a_kit(self, turn_script):
        """A copy of the pilot's scripts with a turn's script of the test's own beside them."""
        kit = os.path.join(self.tmp, "kit", "probes")
        os.makedirs(os.path.join(kit, "pilot"))
        shutil.copy(os.path.join(HERE, "..", "block-check.sh"), kit)
        for name in ("pilot.sh", "records.py"):
            shutil.copy(os.path.join(HERE, name), os.path.join(kit, "pilot"))
        script(os.path.join(kit, "pilot", "turn.sh"), turn_script)
        return os.path.join(kit, "pilot", "pilot.sh")

    # A turn's script that leaves what the real one leaves for a turn that passed, but for the slots the test
    # names: one it fails at, and one it leaves an empty record at while saying all is well.
    TURN = """OUT=$1; SLUG=$3; WORKER=$4; OWN=false; [ "${5:-}" = --own-prompts ] && OWN=true
[ "$YAK_PILOT_SLOT" = "${FAIL_AT:-}" ] && exit 1
mkdir -p "$OUT"
printf '{"slug": "%s", "worker": "%s", "limits": {"own_prompts": %s}}' "$SLUG" "$WORKER" "$OWN" > "$OUT/manifest.json"
echo 0 > "$OUT/clock.exit"
echo '2026-11-15 10:00:00 UTC' > "$OUT/started.txt"; echo '2026-11-15 10:01:00 UTC' > "$OUT/ended.txt"
if [ "$YAK_PILOT_SLOT" = "${EMPTY_AT:-}" ]; then echo '[]' > "$OUT/turns.json"; exit 0; fi
sed "s/WORKER/$WORKER/" "$TURN_JSON" > "$OUT/turns.json"
"""

    def pilot(self, **more):
        bin_dir = self.programs()
        driver = self.a_kit(self.TURN)
        one = os.path.join(self.tmp, "turn.json")
        with open(one, "w", encoding="utf-8") as out:
            json.dump([turn("WORKER")], out)
        pilot = os.path.join(self.tmp, "pilot")
        done = subprocess.run(["/bin/sh", driver, pilot, os.path.join(self.tmp, "made")], capture_output=True, text=True,
                              env={"PATH": bin_dir, "HOME": self.tmp, "YAK": script(os.path.join(self.tmp, "yak"), "exit 0"),
                                   "YAK_PROBE_PATH": bin_dir, "YAK_PILOT_ROUNDS": "1", "TURN_JSON": one, **more})
        log = open(os.path.join(pilot, "pilot.log"), encoding="utf-8").read()
        return done, pilot, log

    def test_a_pilot_whose_turns_all_leave_an_observation_writes_its_tables(self):
        done, pilot, log = self.pilot()
        self.assertEqual(done.returncode, 0, done.stdout + done.stderr + log)
        self.assertIn("every turn of the plan is in tables.md", log)
        tables = open(os.path.join(pilot, "tables.md"), encoding="utf-8").read()
        self.assertEqual(sum(1 for line in tables.splitlines() if line.startswith("| ") and line[2].isdigit()), 9)
        self.assertNotIn("REFUSED", tables)

    def test_a_turn_whose_script_fails_ends_the_pilot_there(self):
        done, pilot, log = self.pilot(FAIL_AT="2")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("turn 2 left no usable observation, or its script failed: the pilot ends here", log)
        # The turn before it is kept, and nothing after it is run: no third turn, no block check at the end, no
        # tables.
        left = sorted(name for name in os.listdir(pilot) if name[0].isdigit())
        self.assertEqual(left, ["1-thrown-away-item-add-wrong-commit"])
        self.assertNotIn("turn 3 begins", log)
        for name in ("block-after.txt", "tables.md"):
            self.assertFalse(os.path.exists(os.path.join(pilot, name)), name)

    def test_a_record_that_is_not_usable_at_the_end_refuses_the_tables_though_every_turn_said_well(self):
        done, pilot, log = self.pilot(EMPTY_AT="3")
        self.assertNotEqual(done.returncode, 0)
        self.assertIn("the tables are REFUSED", log)
        tables = open(os.path.join(pilot, "tables.md"), encoding="utf-8").read()
        self.assertIn("REFUSED", tables)
        self.assertIn("turn 3 (memory-without, item-add-wrong-commit): 0 attempts", tables)
        self.assertNotIn("| Turn |", tables)

    def a_turn_of_the_real_script(self, record, clock_exit="0"):
        """turn.sh as it is, with a room program that is a script: what it leaves, and how it ends."""
        bin_dir = self.programs()
        made = os.path.join(self.tmp, "made")
        repo = os.path.join(made, "repo")
        os.makedirs(os.path.join(repo, "v2", "checks"))

        def git(*words):
            done = subprocess.run(["git", "-C", repo, "-c", "user.name=t", "-c", "user.email=t@example.invalid",
                                   "-c", "commit.gpgsign=false", *words], capture_output=True, text=True)
            self.assertEqual(done.returncode, 0, done.stderr)
            return done.stdout.strip()

        git("init", "-q", "-b", "v2")
        with open(os.path.join(repo, "v2", "checks", "item-add-title.sh"), "w", encoding="utf-8") as out:
            out.write("true\n")
        git("add", ".")
        git("commit", "-qm", "base")
        base = git("rev-parse", "HEAD")
        git("commit", "-q", "--allow-empty", "-m", "wrong")
        wrong = git("rev-parse", "HEAD")
        git("update-ref", "refs/wrong/item-add-title", wrong)
        git("reset", "-q", "--hard", base)
        with open(os.path.join(made, "ids.txt"), "w", encoding="utf-8") as out:
            out.write(f"base {base}\nwrong item-add-title {wrong}\n")
        wanted = os.path.join(self.tmp, "wanted")
        os.makedirs(wanted)
        with open(os.path.join(wanted, "turns.json"), "w", encoding="utf-8") as out:
            json.dump(record, out)
        # The room program: makes a room, names an item, says its help, runs a clock that ends as the test says
        # and notes whether the manifest was there by then, and prints the record the test wants.
        yak = script(os.path.join(self.tmp, "yak"), f"""case "$*" in
*" init") mkdir -p "$2" ;;
*" item add "*) echo i0123456789ab ;;
*"clock run --help") cat <<'HELP'
{HELP}HELP
;;
*" clock run "*) [ -f "$(dirname "$2")/manifest.json" ] && : > "$(dirname "$2")/manifest-was-there"; exit {clock_exit} ;;
*" item turns "*) cat '{wanted}/turns.json' ;;
*) echo "the stand-in does not know: $*" >&2; exit 9 ;;
esac""")
        out = os.path.join(self.tmp, "a-turn")
        vendor = os.path.join(self.tmp, "vendor")
        os.makedirs(vendor)
        done = subprocess.run(["/bin/sh", os.path.join(HERE, "turn.sh"), out, made, "item-add-title", "codex:gpt-6.1-sol"],
                              capture_output=True, text=True,
                              env={"PATH": bin_dir, "HOME": self.tmp, "USER": "t", "LOGNAME": "t", "YAK": yak,
                                   "YAK_PROBE_PATH": bin_dir, "YAK_JAIL_READ": "/tools", "YAK_VENDOR": vendor,
                                   "YAK_PILOT_SLOT": "8", "YAK_PILOT_KIND": "round-1"})
        return done, out

    def test_a_turns_script_writes_its_manifest_before_its_clock_and_ends_well_on_one_usable_observation(self):
        for name, record, clock_exit in [("passed", [turn("codex:gpt-6.1-sol")], "0"),
                                         ("failed its check", [turn("codex:gpt-6.1-sol", passed=False)], "1")]:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.tmp = tmp
                done, out = self.a_turn_of_the_real_script(record, clock_exit)
                self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                self.assertIn("ok: one usable observation", done.stdout)
                self.assertTrue(os.path.exists(os.path.join(out, "manifest-was-there")))
                self.assertEqual(open(os.path.join(out, "clock.exit"), encoding="utf-8").read().strip(), clock_exit)
                kept = records.load(os.path.join(out, "manifest.json"))
                self.assertEqual((kept["slot"], kept["kind"], kept["slug"], kept["worker"], kept["item"]),
                                 (8, "round-1", "item-add-title", "codex:gpt-6.1-sol", "i0123456789ab"))
                self.assertEqual(kept["argv"][1:], ["--room", os.path.join(os.path.realpath(out), "room"), "clock",
                                                    "run", "--once-through", "--daily-turns", "1", "--worker",
                                                    "codex:gpt-6.1-sol"])
                self.assertEqual(kept["limits"]["in_force"]["daily-turns"], 1)

    def test_a_turns_script_fails_when_what_it_leaves_is_not_one_usable_observation(self):
        for name, record, clock_exit, says in [
                ("no attempt", [], "1", "0 attempts"),
                ("another worker", [turn("claude:opus")], "0", "taken by claude:opus"),
                ("a clock that ended badly", [turn("codex:gpt-6.1-sol")], "101", "the clock ended with 101")]:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.tmp = tmp
                done, out = self.a_turn_of_the_real_script(record, clock_exit)
                self.assertNotEqual(done.returncode, 0, done.stdout)
                self.assertIn(f"REFUSED: {says}", done.stdout)
                # What it left is kept for a person to look at.
                self.assertTrue(os.path.exists(os.path.join(out, "turns.json")))


class TheBlockCheck(Made):
    """../block-check.sh, with each program it asks a script: it refuses a block whose versions it cannot learn."""

    # What the script runs beside the two programs and a hash tool: found once, and linked into a directory
    # that is the whole of its search path, so that a test decides which hash tool is there.
    TOOLS = ("git", "uname", "sed", "cut", "cmp", "diff", "mv", "cat", "unlink", "dirname")

    def run_check(self, claude="echo '2.1.325 (Claude Code)'", codex="echo 'codex-cli 0.163.0'", hashers=None):
        bin_dir = os.path.join(self.tmp, "bin")
        os.makedirs(bin_dir, exist_ok=True)
        script(os.path.join(bin_dir, "claude"), claude)
        script(os.path.join(bin_dir, "codex"), codex)
        for tool in self.TOOLS:
            found = shutil.which(tool)
            self.assertIsNotNone(found, tool)
            if not os.path.lexists(os.path.join(bin_dir, tool)):
                os.symlink(found, os.path.join(bin_dir, tool))
        # By default one hash tool that works, under the name the script asks for first.
        digest = "ab" * 32
        for name, body in (hashers or {"sha256sum": f"echo '{digest}  '\"$1\""}).items():
            script(os.path.join(bin_dir, name), body)
        yak = script(os.path.join(self.tmp, "yak"), "exit 0")
        block = os.path.join(self.tmp, "block")
        os.makedirs(block, exist_ok=True)
        home = os.path.join(self.tmp, "home")
        os.makedirs(home, exist_ok=True)
        return subprocess.run(["/bin/sh", os.path.join(HERE, "..", "block-check.sh"), block, yak],
                              env={"PATH": bin_dir, "HOME": home}, capture_output=True, text=True)

    def test_a_block_whose_programs_say_their_versions_is_written_down_and_checked_again(self):
        first = self.run_check()
        self.assertEqual(first.returncode, 0, first.stdout + first.stderr)
        self.assertIn("versions: written", first.stdout)
        kept = open(os.path.join(self.tmp, "block", "versions.txt"), encoding="utf-8").read()
        self.assertIn("claude 2.1.325 (Claude Code)\n", kept)
        self.assertIn("codex codex-cli 0.163.0\n", kept)
        again = self.run_check()
        self.assertEqual(again.returncode, 0, again.stdout + again.stderr)
        self.assertIn("versions: as at the block's start", again.stdout)
        changed = self.run_check(claude="echo '2.1.326 (Claude Code)'")
        self.assertNotEqual(changed.returncode, 0)
        self.assertIn("CHANGED", changed.stdout)

    def test_the_room_programs_hash_is_asked_of_whichever_tool_is_there_and_a_tool_that_fails_refuses(self):
        digest = "cd" * 32
        good = f"echo '{digest}  '\"$1\""
        cases = [
            # The tool asked first, and the other when the first is not there: each one's digest is written down.
            ("the first tool", {"sha256sum": good}, True),
            ("the other tool", {"shasum": good}, True),
            # A tool that ends badly, with a complaint or with what looks like a digest; and one that ends well
            # and gives no digest.
            ("the first tool complains", {"sha256sum": "echo 'sha256sum: yak: No such file' >&2; exit 7"}, False),
            ("the first tool ends badly after a digest", {"sha256sum": good + "; exit 7"}, False),
            ("the other tool complains", {"shasum": "echo 'shasum: yak: No such file' >&2; exit 7"}, False),
            ("the other tool ends badly after a digest", {"shasum": good + "; exit 7"}, False),
            ("a tool that gives no digest", {"sha256sum": "echo 'not a digest  yak'"}, False),
            ("a tool that gives a short digest", {"sha256sum": "echo 'abcdef  yak'"}, False),
            ("a tool that gives 64 letters that are not hex", {"sha256sum": f"echo '{'z' * 64}  yak'"}, False),
            ("no hash tool at all", {"unused": "exit 0"}, False),
        ]
        for name, hashers, written in cases:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.tmp = tmp
                done = self.run_check(hashers=hashers)
                kept = os.path.join(tmp, "block", "versions.txt")
                if written:
                    self.assertEqual(done.returncode, 0, done.stdout + done.stderr)
                    self.assertIn(f"yak {digest}\n", open(kept, encoding="utf-8").read())
                else:
                    self.assertNotEqual(done.returncode, 0, done.stdout)
                    self.assertIn("refused: yak", done.stdout)
                    self.assertFalse(os.path.exists(kept))

    def test_a_program_that_ends_badly_or_says_nothing_refuses_the_block(self):
        for name, how in [("claude ends badly", {"claude": "echo 2.1.325; exit 7"}),
                          ("claude says nothing", {"claude": "exit 0"}),
                          ("codex ends badly", {"codex": "echo codex-cli; exit 3"})]:
            with self.subTest(name), tempfile.TemporaryDirectory() as tmp:
                self.tmp = tmp
                refused = self.run_check(**how)
                self.assertNotEqual(refused.returncode, 0, refused.stdout)
                self.assertIn("refused", refused.stdout)
                self.assertFalse(os.path.exists(os.path.join(tmp, "block", "versions.txt")))


if __name__ == "__main__":
    unittest.main()
