"""Scratch-only mutation evidence for the maker and runner; no real room or worker.

Usage: python3 -I mutate_documents.py <repository root> <documents_plan.py|documents_run.py>
The control runs first. Each mutant negates one condition/comparison/filter,
swaps one boolean operator, removes one negation, or increments one numeric
literal. Regex thresholds, the check's exit code and fixed commit dates also
get mutants. The costly historical cohort recount is a control, not repeated
for every mutant. A timeout is reported as survived, never as a test kill.
"""
import ast
import concurrent.futures
import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import subprocess
import sys
import tempfile

root = Path(sys.argv[1]).resolve()
target = sys.argv[2]
if target not in ("documents_plan.py", "documents_run.py"):
    raise SystemExit("choose documents_plan.py or documents_run.py")
source = (root / "v2/probes/documents" / target).read_text()
tree = ast.parse(source)
lines = source.splitlines(keepends=True)
starts = [0]
for line in lines:
    starts.append(starts[-1] + len(line))
changes = []
def add(node, replacement, kind):
    a = starts[node.lineno - 1] + node.col_offset
    b = starts[node.end_lineno - 1] + node.end_col_offset
    changes.append((a, b, replacement, kind, node.lineno))
for node in ast.walk(tree):
    if isinstance(node, (ast.If, ast.IfExp, ast.While, ast.Assert)):
        test = node.test
        add(test, "not (" + ast.get_source_segment(source, test) + ")", "condition")
    if isinstance(node, ast.comprehension):
        for test in node.ifs:
            add(test, "not (" + ast.get_source_segment(source, test) + ")", "filter")
    if isinstance(node, ast.Compare):
        add(node, "not (" + ast.get_source_segment(source, node) + ")", "comparison")
    if isinstance(node, ast.BoolOp):
        word = " or " if isinstance(node.op, ast.And) else " and "
        add(node, "(" + word.join("(" + ast.get_source_segment(source, n) + ")" for n in node.values) + ")", "boolean")
    if isinstance(node, ast.UnaryOp) and isinstance(node.op, ast.Not):
        add(node, ast.get_source_segment(source, node.operand), "negation")
    if isinstance(node, ast.Constant) and type(node.value) in (int, float):
        add(node, repr(node.value + 1), "number")
    if isinstance(node, ast.Constant) and isinstance(node.value, str):
        for pattern, replacement in (("{3,}", "{4,}"), ("{40}", "{39}"), ("{32}", "{33}"), ("exit 1", "exit 0"),
                ("2026-11-18T00:00:00Z", "2026-11-19T00:00:00Z")):
            if pattern in node.value:
                add(node, repr(node.value.replace(pattern, replacement)), "embedded-number")

# Numeric command arguments, file modes and embedded parent/format numbers are
# a separate sweep so their evidence is easy to distinguish from Python literals.
extra_numbers = "--extra-numbers" in sys.argv
if extra_numbers:
    changes = []
    for node in ast.walk(tree):
        if isinstance(node, ast.Constant) and isinstance(node.value, (str, bytes)):
            value = node.value
            if value.isdigit():
                changed = str(int(value) + 1)
                add(node, repr(changed.encode() if isinstance(value, bytes) else changed), "argument-or-mode-number")
            if isinstance(value, str):
                for old, new in (("^1", "^2"), ("%03d", "%04d"), ("2026-11-18-v2", "2026-11-19-v2"), ("100644,", "100755,")):
                    if old in value:
                        add(node, repr(value.replace(old, new)), "embedded-argument-number")
only_lines = next((a.split("=", 1)[1] for a in sys.argv if a.startswith("--only-lines=")), None)
if only_lines:
    wanted_lines = {int(n) for n in only_lines.split(",")}
    changes = [c for c in changes if c[4] in wanted_lines]

tests = ["Maker", "Rules.test_census_parser_only_accepts_passing_reference", "Rules.test_name_and_document_boundaries", "Rules.test_search_half_threshold_ties_and_task_bytes",
    "Rules.test_order_84_hashes_stable_and_full_commit", "Rules.test_collision_is_refused", "Rules.test_python_39"]
if target == "documents_run.py":
    tests = []
test_file = "test_documents_run.py" if target == "documents_run.py" else "test_documents_plan.py"
control = subprocess.run([sys.executable, "-I", str(root / "v2/probes/documents" / test_file)], capture_output=True, text=True)
print(control.stderr, end="", flush=True)
if control.returncode:
    raise SystemExit(control.returncode)
def run(change):
    a, b, replacement, kind, line = change
    selected_tests = tests
    if target == "documents_run.py" and not only_lines:
        function = next((n.name for n in tree.body if isinstance(n, ast.FunctionDef)
            and n.lineno <= line <= n.end_lineno), "")
        selected_tests = {
            "runner_lock": ["Runner.test_lock_and_changed_input_before_any_row"],
            "outcome": ["Outcomes"], "archive_interrupted": ["Archives"],
            "controls_ready": ["Runner.test_controls_gate_precedes_any_row"],
            "run_turn": ["Runner.test_every_outcome_and_commit_at_limit", "Runner.test_kept_out_objects_are_checked_before_room",
                "Runner.test_order_row_limit_recorded_rows_and_clock_contract", "Runner.test_failure_to_start_clock_is_recorded"],
            "run_rows": ["Runner.test_order_row_limit_recorded_rows_and_clock_contract", "Runner.test_invalid_row_cap_and_malformed_turn",
                "Runner.test_controls_gate_precedes_any_row", "Runner.test_lock_and_changed_input_before_any_row"],
            "main": ["Runner.test_cli_zero_rows_and_refusal"],
        }.get(function, [])
    with tempfile.TemporaryDirectory(prefix="document-mutant-") as folder:
        scratch = Path(folder)
        dest = scratch / "v2/probes/documents"
        dest.mkdir(parents=True)
        for path in (root / "v2/probes/documents").glob("*"):
            if path.is_file() and path.suffix in (".py", ".sh", ".txt"):
                shutil.copyfile(path, dest / path.name)
        (scratch / "v2/probes/items").mkdir()
        shutil.copyfile(root / "v2/probes/items/pilot_driver.py", scratch / "v2/probes/items/pilot_driver.py")
        spec = Path("docs/superpowers/specs/2026-11-18-v2-a-document-offered.md")
        (scratch / spec).parent.mkdir(parents=True)
        shutil.copyfile(root / spec, scratch / spec)
        (dest / target).write_text(source[:a] + replacement + source[b:])
        try:
            done = subprocess.run([sys.executable, "-I", str(dest / test_file), *selected_tests], capture_output=True, text=True, timeout=45)
            killed = done.returncode != 0
            names = re.findall(r"(?:FAIL|ERROR): ([^\n]+)", done.stderr)
            return {"line": line, "kind": kind, "before": source[a:b], "after": replacement,
                "killed": killed, "tests": names, "tail": done.stderr.splitlines()[-3:],
                "reason": "" if killed else "The covering fixture tests passed; this mutation was not detected."}
        except subprocess.TimeoutExpired:
            return {"line": line, "kind": kind, "before": source[a:b], "after": replacement,
                "killed": False, "tests": [], "reason": "Scratch tests timed out; conservatively counted as survived.",
                "tail": ["timeout; mutation not established killed"]}
with concurrent.futures.ThreadPoolExecutor(max_workers=4) as pool:
    results = list(pool.map(run, changes))
suffix = ".recheck-mutants.json" if only_lines else ".numbers-mutants.json" if extra_numbers else ".mutants.json"
output = root / "v2/probes/documents" / (target + suffix)
output.write_text(json.dumps({"file": target, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    "control": {"command": "python3 -I v2/probes/documents/" + test_file,
        "returncode": control.returncode, "last_lines": control.stderr.splitlines()[-4:]},
    "mutants": [{k: v for k, v in r.items() if k != "tail"} for r in results]}, indent=1) + "\n")
print("mutants", len(results), "killed", sum(r["killed"] for r in results), "survived", sum(not r["killed"] for r in results))
for n, r in enumerate(results):
    if not r["killed"]:
        print(n, r["line"], r["kind"], repr(r["before"]))
