"""Scratch-only mutation evidence for the maker and runner; no real room or worker.

Usage: python3 -I mutate_documents.py <repository root> <documents_plan.py|documents_run.py>
Add --bm25 for the eighth-row changes and explicit score/order regressions.
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
        for pattern, replacement in (("{3,}", "{4,}"), ("{40}", "{39}"), ("{32}", "{33}"),
                ("exit 1", "exit 0"), ("exit 0", "exit 1"), ("-eq 1", "-eq 0"), ("4b25d330", "00000000"),
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

# Recreate the reader's actual proof hole and lock lifetime failures, in addition
# to the mechanical condition/number sweep. These edits never touch the checkout.
regressions = "--regressions" in sys.argv
if regressions:
    changes = []
    patches = {
        "documents_plan.py": [
            ('first, row["base"]', 'row["base"], row["base"]', "proof-self-diff"),
            ('exclude_test_functions=True', 'exclude_test_functions=False', "test-function-gate-disabled"),
            ('-eq 1', '-ne 0', "check-accepts-git-errors")],
        "documents_run.py": [
            ('pass_fds=(lock_fd,)', 'pass_fds=()', "clock-drops-lock"),
            ('yield lock.fileno()', 'try:\n            yield lock.fileno()\n        finally:\n            fcntl.flock(lock, fcntl.LOCK_UN)', "parent-unlocks-child")],
    }
    for before, after, kind in patches[target]:
        a = source.index(before)
        changes.append((a, a + len(before), after, kind, source.count("\n", 0, a) + 1))

bm25_mode = "--bm25" in sys.argv
bm25_tests = ["Rules.test_bm25_hand_worked_scores", "Rules.test_bm25_search_words_candidates_and_best_matching_file",
    "Rules.test_bm25_sorted_sum_and_empty_documents", "Rules.test_bm25_rounded_ties_and_path_bytes",
    "Rules.test_search_half_threshold_ties_and_task_bytes"]
if bm25_mode:
    if target != "documents_plan.py":
        raise SystemExit("--bm25 applies to documents_plan.py")
    score_function = next(n for n in tree.body if isinstance(n, ast.FunctionDef) and n.name == "bm25_scores")
    bm25_lines = set(range(score_function.lineno, score_function.end_lineno + 1))
    bm25_lines.update(i for i, line in enumerate(lines, 1)
        if "bm25" in line or "second_search" in line or "second_best" in line or line.startswith(("K1 =", "B =")))
    changes = [c for c in changes if c[4] in bm25_lines]
    patches = [
        ('for w in sorted(use)', 'for w in use', "bm25-unsorted-sum"),
        ('for w in sorted(use)', 'for w in sorted(use, reverse=True)', "bm25-reverse-sum"),
        ('math.log(1 +', 'math.log10(1 +', "bm25-base-ten-log"),
        ('sum(counts.values())', 'len(counts)', "bm25-distinct-length"),
        ('/ count or 1', '/ count or 0', "bm25-zero-average"),
        ('bm25 = bm25_scores(frequencies, use, df)', 'bm25 = bm25_scores(frequencies, words, df)', "bm25-includes-common-words"),
        ('(-bm25[p], p.encode("utf-8"))', '(bm25[p], p.encode("utf-8"))', "bm25-ascending-score"),
        ('(-bm25[p], p.encode("utf-8"))', '(-bm25[p],)', "bm25-no-path-tie"),
        ('(-bm25[p], p.encode("utf-8"))', '(-bm25[p], bytes(255 - b for b in p.encode("utf-8")))', "bm25-reverse-path-tie"),
        ('second_best = min(', 'second_best = max(', "bm25-worst-matching-place"),
    ]
    # Remove the complete round call, including its precision argument.
    score_round = next(n for n in ast.walk(score_function)
        if isinstance(n, ast.Call) and isinstance(n.func, ast.Name) and n.func.id == "round")
    add(score_round, ast.get_source_segment(source, score_round.args[0]), "bm25-unrounded-scores")
    term = score_round.args[0].args[0].elt
    add(term, "round(" + ast.get_source_segment(source, term) + ", 9)", "bm25-rounds-each-term")
    for before, after, kind in patches:
        a = source.index(before)
        changes.append((a, a + len(before), after, kind, source.count("\n", 0, a) + 1))
    for row_tuple in ('("nothing-1", "nothing-2", "exists", "path", "search", "newest", "lot", "bm25")',
            '("search", "newest", "lot", "bm25")'):
        for match in re.finditer(re.escape(row_tuple), source):
            changes.append((match.start(), match.end(), row_tuple.replace(', "bm25"', ''),
                "bm25-row-omitted", source.count("\n", 0, match.start()) + 1))

tests = ["Maker", "Rules.test_census_parser_only_accepts_passing_reference", "Rules.test_name_and_document_boundaries", "Rules.test_search_half_threshold_ties_and_task_bytes",
    "Rules.test_order_96_hashes_stable_and_full_commit", "Rules.test_collision_is_refused", "Rules.test_python_39", *bm25_tests]
if bm25_mode:
    tests = [*bm25_tests, "Rules.test_order_96_hashes_stable_and_full_commit",
        "Maker.test_paragraphs_bases_pins_and_directory_names", "Maker.test_bm25_only_offer_is_pinned"]
if target == "documents_run.py":
    tests = []
test_file = "test_documents_run.py" if target == "documents_run.py" else "test_documents_plan.py"
control_tests = tests if only_lines or regressions or extra_numbers or bm25_mode else []
control = subprocess.run([sys.executable, "-I", str(root / "v2/probes/documents" / test_file), *control_tests], capture_output=True, text=True)
print(control.stderr, end="", flush=True)
if control.returncode:
    raise SystemExit(control.returncode)
def run(change):
    a, b, replacement, kind, line = change
    selected_tests = tests
    function = next((n.name for n in tree.body if isinstance(n, ast.FunctionDef)
        and n.lineno <= line <= n.end_lineno), "")
    if target == "documents_plan.py" and (only_lines or extra_numbers):
        selected_tests = {
            "distinct_items": ["Rules.test_collision_is_refused", "Rules.test_search_half_threshold_ties_and_task_bytes"],
            "census_passes": ["Rules.test_census_parser_only_accepts_passing_reference"],
            "tree_files": ["Maker.test_selection_and_ranking"],
            "read_blobs": ["Maker.test_selection_and_ranking"],
            "markdown": ["Maker.test_selection_and_ranking"],
            "under": ["Rules.test_name_and_document_boundaries"],
            "has_word": ["Rules.test_name_and_document_boundaries"],
            "matching_documents": ["Rules.test_name_and_document_boundaries"],
            "select_items": ["Maker.test_selection_and_ranking", "Maker.test_selection_refuses_test_function_and_nonpassing_reference"],
            "bm25_scores": bm25_tests,
            "rank_documents": ["Maker.test_selection_and_ranking", "Rules.test_search_half_threshold_ties_and_task_bytes", *bm25_tests],
            "paragraphs": ["Maker.test_paragraphs_bases_pins_and_directory_names"],
            "task_bytes": ["Maker.test_paragraphs_bases_pins_and_directory_names", "Rules.test_search_half_threshold_ties_and_task_bytes"],
            "row_order": ["Rules.test_order_96_hashes_stable_and_full_commit"],
            "git_as": ["Maker.test_paragraphs_bases_pins_and_directory_names"],
            "check_script": ["Maker.test_small_check_requires_git_difference_exit"],
            "make_bases": ["Maker.test_paragraphs_bases_pins_and_directory_names"],
            "prove_bases": ["Maker.test_proof_rejects_difference_outside_task_and_wrong_parent"],
            "pin_path": ["Maker.test_changed_input_task_plan_are_refused"],
            "input_path": ["Maker.test_changed_input_task_plan_are_refused"],
            "task_path": ["Maker.test_runtime_and_task_refusals"],
            "runtime_pins": ["Maker.test_runtime_and_task_refusals", "Maker.test_script_path_is_absolute_and_worker_lookup_is_pinned", "Maker.test_paragraphs_bases_pins_and_directory_names"],
            "make_plan": ["Maker.test_runtime_and_task_refusals", "Maker.test_item_list_hash_is_required_even_with_fixture_cohort",
                "Maker.test_paragraphs_bases_pins_and_directory_names", "Maker.test_task_cannot_change_between_search_and_freeze"],
            "load_plan": ["Maker.test_changed_input_task_plan_are_refused", "Maker.test_script_path_is_absolute_and_worker_lookup_is_pinned"],
            "main": ["Maker.test_cli_show_and_refusal"],
        }.get(function, tests)
    if target == "documents_run.py":
        selected_tests = {
            "runner_lock": ["Runner.test_lock_and_changed_input_before_any_row",
                "Runner.test_clock_keeps_lock_after_runner_is_killed", "Runner.test_inherited_lock_survives_runner_context_exit"],
            "outcome": ["Outcomes"], "archive_interrupted": ["Archives"],
            "controls_ready": ["Runner.test_controls_gate_precedes_any_row", "Runner.test_stopped_controls_refuse_even_with_success_markers"],
            "run_turn": ["Runner.test_every_outcome_and_commit_at_limit", "Runner.test_kept_out_objects_are_checked_before_room",
                "Runner.test_order_row_limit_recorded_rows_and_clock_contract", "Runner.test_failure_to_start_clock_is_recorded",
                "Runner.test_failed_export_is_recorded_and_not_rerun", "Runner.test_failed_walks_export_preserves_finished_turn_outcome",
                "Runner.test_archived_attempts_distinguish_refused_running_and_finished",
                "Runner.test_failed_turns_export_does_not_trust_partial_output", "Runner.test_preclock_fetch_refusal_is_not_an_interrupted_turn"],
            "run_rows": ["Runner.test_order_row_limit_recorded_rows_and_clock_contract", "Runner.test_invalid_row_cap_and_malformed_turn",
                "Runner.test_controls_gate_precedes_any_row", "Runner.test_lock_and_changed_input_before_any_row"],
            "main": ["Runner.test_cli_zero_rows_and_refusal"],
        }.get(function, [])
        if only_lines and line in (173, 174, 175):
            selected_tests = ["Runner.test_every_outcome_and_commit_at_limit",
                "Runner.test_failed_export_is_recorded_and_not_rerun", "Runner.test_failed_turns_export_does_not_trust_partial_output"]
        if only_lines and line == 180:
            selected_tests = ["Runner.test_archived_attempts_distinguish_refused_running_and_finished"]
    if regressions:
        selected_tests = {
            "proof-self-diff": ["Maker.test_proof_rejects_difference_outside_task_and_wrong_parent"],
            "test-function-gate-disabled": ["Maker.test_selection_refuses_test_function_and_nonpassing_reference"],
            "check-accepts-git-errors": ["Maker.test_small_check_requires_git_difference_exit"],
            "clock-drops-lock": ["Runner.test_clock_keeps_lock_after_runner_is_killed"],
            "parent-unlocks-child": ["Runner.test_inherited_lock_survives_runner_context_exit"],
        }[kind]
    if bm25_mode:
        selected_tests = {
            "bm25_scores": bm25_tests,
            "rank_documents": bm25_tests,
            "paragraphs": ["Maker.test_paragraphs_bases_pins_and_directory_names"],
            "make_plan": ["Maker.test_bm25_only_offer_is_pinned"],
        }.get(function, ["Rules.test_order_96_hashes_stable_and_full_commit", *bm25_tests])
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
            reason = "" if killed else "The covering fixture tests passed; this mutation was not detected."
            if bm25_mode and not killed and function == "bm25_scores" and source[a:b] == "1" and replacement == "2":
                reason = ("Equivalent: the average fallback is used only when every document has zero words. "
                    "Every term frequency is then zero, so any positive fallback gives all-zero scores. "
                    "The separate fallback-to-zero mutant is killed by the empty-document test.")
            return {"line": line, "column": a - starts[line - 1], "kind": kind, "before": source[a:b], "after": replacement,
                "killed": killed, "tests": names, "tail": done.stderr.splitlines()[-3:],
                "reason": reason}
        except subprocess.TimeoutExpired:
            return {"line": line, "column": a - starts[line - 1], "kind": kind, "before": source[a:b], "after": replacement,
                "killed": False, "tests": [], "reason": "Scratch tests timed out; conservatively counted as survived.",
                "tail": ["timeout; mutation not established killed"]}
workers = next((int(a.split("=", 1)[1]) for a in sys.argv if a.startswith("--workers=")), 4)
with concurrent.futures.ThreadPoolExecutor(max_workers=workers) as pool:
    results = list(pool.map(run, changes))
suffix = ".bm25-mutants.json" if bm25_mode else ".fix-mutants.json" if regressions else ".recheck-mutants.json" if only_lines else ".numbers-mutants.json" if extra_numbers else ".mutants.json"
output = root / "v2/probes/documents" / (target + suffix)
output.write_text(json.dumps({"file": target, "source_sha256": hashlib.sha256(source.encode()).hexdigest(),
    "control": {"command": " ".join(["python3", "-I", "v2/probes/documents/" + test_file, *control_tests]),
        "returncode": control.returncode, "last_lines": control.stderr.splitlines()[-4:]},
    "mutants": [{k: v for k, v in r.items() if k != "tail"} for r in results]}, indent=1) + "\n")
print("mutants", len(results), "killed", sum(r["killed"] for r in results), "survived", sum(not r["killed"] for r in results))
for n, r in enumerate(results):
    if not r["killed"]:
        print(n, r["line"], r["kind"], repr(r["before"]))
