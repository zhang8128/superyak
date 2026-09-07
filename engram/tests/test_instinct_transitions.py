"""Tests for instinct transition recording."""
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent.parent))

import pytest
from transitions import TransitionGraph


@pytest.fixture
def graph(tmp_path):
    g = TransitionGraph(db_path=tmp_path / "instinct_transitions.db")
    yield g
    g.close()


def test_instinct_transition_recording(graph):
    """When instinct B fires after instinct A, record the transition."""
    graph.record("observe-before-judging", "dont-framework-single-use",
                 context="architecture")
    weights = graph.next_weights("observe-before-judging", context="architecture")
    assert "dont-framework-single-use" in weights


def test_instinct_transitions_context_isolated(graph):
    graph.record("observe-before-judging", "dont-framework-single-use",
                 context="architecture")
    graph.record("observe-before-judging", "check-assumptions",
                 context="debugging")
    arch = graph.next_weights("observe-before-judging", context="architecture")
    debug = graph.next_weights("observe-before-judging", context="debugging")
    assert "dont-framework-single-use" in arch
    assert "dont-framework-single-use" not in debug
    assert "check-assumptions" in debug
