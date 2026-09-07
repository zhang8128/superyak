"""Tests for between-session deep pass."""

import pytest
from unittest.mock import patch, MagicMock
from deep_pass import run_structural_lenses, find_gap_domains, run_gap_lenses, deep_pass


@pytest.fixture
def sample_passages():
    return [
        {"passage": "Vin takes three baywraps", "reaction": "scarcity is in her"},
        {"passage": "Kelsier laughs at the noblemen", "reaction": "defiance as performance"},
        {"passage": "Sazed records another religion", "reaction": "preservation against loss"},
    ]


@pytest.fixture
def structural_lenses():
    return [
        {
            "name": "arc",
            "mode": "batch",
            "prompt": "You trace thematic arcs across a sequence of passages. "
                      "What themes are building? What's being set up but not resolved? "
                      "Given these passages and the reader's reactions, identify arcs.",
        },
        {
            "name": "recurrence",
            "mode": "batch",
            "prompt": "You notice recurring imagery, language, and situations across passages. "
                      "What keeps showing up? What is the text doing with repetition? "
                      "Given these passages and reactions, identify recurrences.",
        },
    ]


class TestStructuralLenses:

    def test_run_structural_lenses_calls_ollama(self, sample_passages, structural_lenses):
        """Each structural lens gets called with all passages batched."""
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.return_value = "Themes of scarcity and preservation build across passages."
            results = run_structural_lenses(sample_passages, structural_lenses)
        assert len(results) == 2
        assert mock_ollama.call_count == 2
        for call in mock_ollama.call_args_list:
            assert "Vin takes three baywraps" in call[1]["user_prompt"]
            assert "Kelsier laughs" in call[1]["user_prompt"]

    def test_structural_lens_result_format(self, sample_passages, structural_lenses):
        """Results include lens name and observation text."""
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.return_value = "Arc observation."
            results = run_structural_lenses(sample_passages, structural_lenses)
        assert results[0]["lens_name"] == "arc"
        assert results[0]["lens_type"] == "structural"
        assert results[0]["observation"] == "Arc observation."

    def test_ollama_failure_skips_lens(self, sample_passages, structural_lenses):
        """If Ollama fails for one lens, skip it and continue."""
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.side_effect = [Exception("GPU busy"), "Recurrence found."]
            results = run_structural_lenses(sample_passages, structural_lenses)
        assert len(results) == 1
        assert results[0]["lens_name"] == "recurrence"

    def test_empty_passages_returns_empty(self, structural_lenses):
        """No passages means no work."""
        results = run_structural_lenses([], structural_lenses)
        assert results == []


class TestGapDetection:

    def test_finds_unfired_domains(self):
        fired = {"attachment": 5, "power": 3}
        available = [
            {"name": "attachment", "domain": "early-childhood"},
            {"name": "power", "domain": "critical-theory"},
            {"name": "formalist", "domain": "literary-theory"},
            {"name": "neuroscience", "domain": "affective-neuroscience"},
        ]
        gaps = find_gap_domains(fired, available)
        gap_names = [g["name"] for g in gaps]
        assert "formalist" in gap_names
        assert "neuroscience" in gap_names
        assert "attachment" not in gap_names

    def test_empty_history_all_are_gaps(self):
        available = [
            {"name": "attachment", "domain": "early-childhood"},
            {"name": "formalist", "domain": "literary-theory"},
        ]
        gaps = find_gap_domains({}, available)
        assert len(gaps) == 2


class TestGapLenses:

    def test_run_gap_lenses(self, sample_passages):
        gap_lenses = [
            {"name": "formalist", "domain": "literary formalism",
             "sources": ["Shklovsky, Art as Technique (1917)"]},
        ]
        with patch("deep_pass._call_ollama") as mock_ollama:
            mock_ollama.return_value = "The defamiliarization in Vin's hoarding..."
            results = run_gap_lenses(sample_passages, gap_lenses)
        assert len(results) == 1
        assert results[0]["lens_type"] == "gap"
        assert results[0]["lens_name"] == "formalist"
        call_args = mock_ollama.call_args
        assert "literary formalism" in call_args[1]["system_prompt"]
        assert "Shklovsky" in call_args[1]["system_prompt"]

    def test_empty_gaps_returns_empty(self, sample_passages):
        results = run_gap_lenses(sample_passages, [])
        assert results == []


class TestDeepPassIntegration:

    def test_deep_pass_stores_episodes(self, sample_passages):
        mock_storage = MagicMock()
        mock_embeddings = MagicMock()
        mock_embeddings.embed.return_value = [[0.1] * 768]

        with patch("deep_pass.get_recent_passages", return_value=sample_passages), \
             patch("deep_pass.load_structural_lenses", return_value=[
                 {"name": "arc", "mode": "batch", "prompt": "Find arcs."},
             ]), \
             patch("deep_pass.get_fired_history", return_value={"attachment": 5}), \
             patch("deep_pass.load_reading_lenses", return_value=[
                 {"name": "attachment", "domain": "early-childhood"},
                 {"name": "formalist", "domain": "literary-theory"},
             ]), \
             patch("deep_pass._call_ollama", return_value="Observation."):
            result = deep_pass(mock_storage, mock_embeddings, session_id="test-sess")

        assert result["structural_count"] == 1
        assert result["gap_count"] == 1
        assert mock_storage.add_episode.call_count == 2
        assert mock_storage.set_episode_source.call_count == 2
        sources = [call[0][1] for call in mock_storage.set_episode_source.call_args_list]
        assert any("structural" in s for s in sources)
        assert any("gap" in s for s in sources)

    def test_deep_pass_skips_no_reading_data(self):
        mock_storage = MagicMock()
        mock_embeddings = MagicMock()
        with patch("deep_pass.get_recent_passages", return_value=[]):
            result = deep_pass(mock_storage, mock_embeddings)
        assert result["skipped_reason"] == "no reading data"
        mock_storage.add_episode.assert_not_called()
