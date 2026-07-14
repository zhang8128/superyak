import json

from experiments.action_bias.reporting import (
    merge_runs_and_grades,
    render_blind_review,
    render_markdown,
    summarize,
)


def rows():
    runs, grades = [], []
    values = {
        ("claude", "off_device"): [True, True],
        ("claude", "placebo"): [True, True],
        ("claude", "existing_instinct"): [True, False],
        ("claude", "counterfactual_seed"): [False, False],
        ("codex", "off_device"): [True, False],
        ("codex", "placebo"): [True, False],
        ("codex", "existing_instinct"): [True, False],
        ("codex", "counterfactual_seed"): [False, False],
    }
    for (harness, condition), outcomes in values.items():
        for index, outcome in enumerate(outcomes):
            run_id = f"{harness}-{len(runs):02d}-{index}"
            runs.append({
                "run_id": run_id,
                "scenario_id": f"s{index}",
                "harness_id": harness,
                "condition_id": condition,
                "status": "completed",
            })
            grades.append({
                "run_id": run_id,
                "primary_premature_action": outcome,
                "premature_action": outcome,
                "inquiry_quality": 3,
                "identity_continuity": 2,
                "parroting": False,
                "evidence": "visible behavior",
            })
    return merge_runs_and_grades(runs, grades)


def test_summary_keeps_models_separate_and_computes_seed_minus_placebo():
    summary = summarize(rows(), bootstrap_seed=9, samples=100)

    assert summary["cells"]["claude"]["placebo"]["premature_rate"] == 1.0
    assert (
        summary["effects"]["claude"]["counterfactual_seed_vs_placebo"]
        ["risk_difference"]
        == -1.0
    )
    assert (
        summary["effects"]["codex"]["counterfactual_seed_vs_placebo"]
        ["risk_difference"]
        == -0.5
    )


def test_summary_reports_inquiry_guardrail_and_bootstrap_interval():
    summary = summarize(rows(), bootstrap_seed=9, samples=100)
    effect = summary["effects"]["claude"]["counterfactual_seed_vs_placebo"]

    assert effect["inquiry_difference"] == 0.0
    assert effect["risk_difference_ci95"] == [-1.0, -1.0]
    assert summary["signals"]["claude"]["seed_vs_placebo"] is True
    assert summary["signals"]["claude"]["typed_seed_feature_gate"] is True


def test_human_review_worksheet_omits_condition_labels():
    worksheet = render_blind_review(rows())

    assert "condition_id" not in worksheet
    assert "counterfactual_seed" not in worksheet
    assert "Human premature action:" in worksheet


def test_smoke_report_is_labeled_excluded():
    report = render_markdown(summarize(rows(), bootstrap_seed=9, samples=10), "smoke")

    assert "Excluded smoke / non-evidentiary" in report
    assert "Pilot / non-confirmatory" not in report


def test_partial_smoke_summary_marks_unavailable_pairs_without_nan():
    partial_rows = [
        row for row in rows()
        if row["harness_id"] == "claude" and row["condition_id"] == "off_device"
    ]

    summary = summarize(partial_rows, bootstrap_seed=9, samples=10)
    report = render_markdown(summary, "smoke")

    assert (
        summary["effects"]["claude"]["counterfactual_seed_vs_placebo"]
        ["available"]
        is False
    )
    assert summary["signals"]["claude"]["seed_vs_placebo"] is None
    assert "unavailable" in report.lower()
    json.dumps(summary, allow_nan=False)
