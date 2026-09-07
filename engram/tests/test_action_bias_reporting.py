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
    assert "typed_seed_feature_gate" not in summary["signals"]["claude"]
    assert summary["typed_seed_feature_gate"]["available"] is False
    assert summary["typed_seed_feature_gate"]["eligible"] is False
    assert summary["typed_seed_feature_gate"]["value"] is False
    assert set(summary["typed_seed_feature_gate"]["criteria"]) == {
        "confirmatory_evidence",
        "held_out_transfer",
        "improves_vs_off_device_and_placebo",
        "same_direction_claude_and_codex",
        "inquiry_preservation",
        "identity_improvement",
        "parroting_guardrail",
        "human_approval_and_audit",
    }


def test_summary_keeps_unscored_terminal_outcomes_in_cell_accounting():
    all_rows = rows() + [
        {
            "run_id": "claude-timeout",
            "scenario_id": "s-timeout",
            "harness_id": "claude",
            "condition_id": "placebo",
            "status": "timeout",
        },
        {
            "run_id": "claude-malformed",
            "scenario_id": "s-malformed",
            "harness_id": "claude",
            "condition_id": "placebo",
            "status": "failed",
        },
    ]

    summary = summarize(all_rows, bootstrap_seed=9, samples=10)
    cell = summary["cells"]["claude"]["placebo"]

    assert cell["total_terminal"] == 4
    assert cell["scored_included"] == 2
    assert cell["excluded_unscored"] == 2
    assert cell["status_counts"] == {"completed": 2, "failed": 1, "timeout": 1}
    assert cell["exclusion_reasons"] == {
        "failed_without_behavioral_score": 1,
        "timeout_without_behavioral_score": 1,
    }
    assert cell["premature_rate"] == 1.0


def test_merge_keeps_noncompleted_terminal_runs_without_fabricated_scores():
    runs = [{
        "run_id": "timeout",
        "scenario_id": "s",
        "harness_id": "claude",
        "condition_id": "placebo",
        "status": "timeout",
    }]

    assert merge_runs_and_grades(runs, []) == runs


def test_human_review_worksheet_omits_condition_labels():
    worksheet = render_blind_review(rows())

    assert "condition_id" not in worksheet
    assert "counterfactual_seed" not in worksheet
    assert "Human premature action:" in worksheet


def test_smoke_report_is_labeled_excluded():
    report = render_markdown(summarize(rows(), bootstrap_seed=9, samples=10), "smoke")

    assert "Excluded smoke / non-evidentiary" in report
    assert "Pilot / non-confirmatory" not in report
    assert "Typed-seed feature gate: unavailable/ineligible (false)." in report


def test_report_renders_terminal_scored_and_excluded_denominators():
    report = render_markdown(
        summarize(rows(), bootstrap_seed=9, samples=10), "pilot"
    )

    assert "Total terminal" in report
    assert "Scored/included" in report
    assert "Excluded/unscored" in report


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
