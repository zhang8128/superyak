"""The spec, the plan and the hub docs state what Task 50's bounded H1 changed (revision of I 10)."""
from pathlib import Path

DOCS = Path(__file__).resolve().parent.parent / "docs" / "superpowers"
SPEC = (DOCS / "specs" / "2026-10-25-store-imprint-design.md").read_text()
PLAN = (DOCS / "plans" / "2026-10-25-store-imprint.md").read_text()
PERSISTENCE = (DOCS / "specs" / "2026-06-13-persistence-design.md").read_text()


def test_the_spec_budgets_classify_hubs_at_20_and_says_why():
    assert "20 × n² × 8" in SPEC and "`classify_hubs`" in SPEC and "18.48" in SPEC


def test_the_spec_says_a_looped_verdict_is_sound_but_not_complete():
    assert "H1_EDGES_PER_POINT" in SPEC and "lower bound" in SPEC


def test_the_plan_asserts_the_revised_ratio():
    assert "RATIO_BOUND" in PLAN and "20" in PLAN


def test_the_persistence_design_notes_the_bound():
    assert "H1_EDGES_PER_POINT" in PERSISTENCE


def test_the_pi_ratio_test_asserts_its_bound():
    src = (Path(__file__).parent / "test_imprint_calibrate.py").read_text()
    assert "RATIO_BOUND" in src and "assert ratio <=" in src
