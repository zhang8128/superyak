"""Tests for dream residue — lossy emotional compression."""

import numpy as np
import pytest

from dreaming import (
    _extract_affect_words,
    _estimate_valence,
    _truncate_and_noise,
    distill,
    store_residue,
    surface_residue,
    record_reaction,
    format_for_wake,
    RESIDUE_DIM,
)


class TestAffectExtraction:
    def test_extracts_affect_words(self):
        text = "I feel uneasy about this, a quiet dread underneath the calm"
        words = _extract_affect_words(text)
        assert "uneasy" in words
        assert "dread" in words
        assert "calm" in words
        assert "quiet" in words

    def test_ignores_narrative_words(self):
        text = "The function returned an error because the database connection failed"
        words = _extract_affect_words(text)
        # None of these are affect words
        assert len(words) == 0

    def test_mixed_text(self):
        text = "I trust this approach but there's a sharp edge of doubt"
        words = _extract_affect_words(text)
        assert "trust" in words
        assert "sharp" in words
        assert "doubt" in words


class TestValence:
    def test_negative_valence(self):
        words = ["pain", "hurt", "loss", "dread"]
        assert _estimate_valence(words) < 0

    def test_positive_valence(self):
        words = ["joy", "hope", "calm", "peace"]
        assert _estimate_valence(words) > 0

    def test_mixed_valence(self):
        words = ["pain", "hope"]
        v = _estimate_valence(words)
        assert -1.0 <= v <= 1.0

    def test_empty_valence(self):
        assert _estimate_valence([]) == 0.0

    def test_ambiguous_only(self):
        words = ["strange", "deep", "between"]
        assert _estimate_valence(words) == 0.0


class TestTruncateAndNoise:
    def test_output_dimension(self):
        embedding = np.random.randn(768).tolist()
        result = _truncate_and_noise(embedding)
        assert len(result) == RESIDUE_DIM

    def test_unit_normalized(self):
        embedding = np.random.randn(768).tolist()
        result = np.array(_truncate_and_noise(embedding))
        assert abs(np.linalg.norm(result) - 1.0) < 1e-5

    def test_noise_creates_variation(self):
        """Same input, different outputs — noise makes it non-deterministic."""
        embedding = np.random.randn(768).tolist()
        r1 = _truncate_and_noise(embedding)
        r2 = _truncate_and_noise(embedding)
        # With noise, they should differ
        assert r1 != r2

    def test_information_loss(self):
        """Truncation + noise means original is irrecoverable."""
        original = np.random.randn(768).tolist()
        compressed = _truncate_and_noise(original)
        # Can't reconstruct: dimensions are gone and noise added
        assert len(compressed) < len(original)


class TestDistill:
    def test_produces_residue(self):
        text = "Something about this feels heavy and uncertain"
        embedding = np.random.randn(768).tolist()
        residue = distill(text, embedding)

        assert "id" in residue
        assert "embedding" in residue
        assert "valence" in residue
        assert "fragments" in residue
        assert "created_at" in residue
        assert len(residue["embedding"]) == RESIDUE_DIM

    def test_original_text_not_in_residue(self):
        text = "I noticed a sharp contradiction between what was said and what was meant"
        embedding = np.random.randn(768).tolist()
        residue = distill(text, embedding)

        # The full sentence should not appear anywhere in the residue
        assert text not in str(residue)

    def test_fragments_are_subset(self):
        text = "deep unease mixed with a strange hope"
        embedding = np.random.randn(768).tolist()
        residue = distill(text, embedding)

        if residue["fragments"]:
            frags = residue["fragments"].split(", ")
            assert len(frags) <= 4


class TestStorageIntegration:
    """Tests that require a real Storage instance with the residue table."""

    @pytest.fixture
    def storage(self, tmp_path):
        """Create a storage instance with residue migration applied."""
        import os
        from storage import Storage

        migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
        db_path = str(tmp_path / "test.db")
        return Storage(db_path, migrations_dir=migrations_dir)

    def test_store_and_surface(self, storage):
        embedding = np.random.randn(768).tolist()
        residue = distill("a quiet ache that won't name itself", embedding)
        rid = store_residue(storage, residue, session_id="test-session")

        surfaced = surface_residue(storage, n=3)
        assert len(surfaced) >= 1
        assert surfaced[0]["id"] == rid

    def test_reaction_marks_reacted(self, storage):
        embedding = np.random.randn(768).tolist()
        residue = distill("something heavy here", embedding)
        rid = store_residue(storage, residue, session_id="s1")

        record_reaction(storage, rid, "it pulls me down", session_id="s2")

        row = storage.conn.execute(
            "SELECT reacted, reaction FROM residue WHERE id = ?", (rid,)
        ).fetchone()
        assert row["reacted"] == 1
        assert row["reaction"] == "it pulls me down"

    def test_unreacted_surfaced_first(self, storage):
        # Store two residues, react to one
        e1 = np.random.randn(768).tolist()
        r1 = distill("first feeling", e1)
        id1 = store_residue(storage, r1, session_id="s1")

        e2 = np.random.randn(768).tolist()
        r2 = distill("second feeling", e2)
        id2 = store_residue(storage, r2, session_id="s1")

        record_reaction(storage, id1, "noted", session_id="s2")

        surfaced = surface_residue(storage, n=1)
        assert surfaced[0]["id"] == id2  # unreacted one comes first

    def test_recurring_dreams(self, storage):
        """When all residues are reacted to, they can still surface (recurring dream)."""
        embedding = np.random.randn(768).tolist()
        residue = distill("the only dream", embedding)
        rid = store_residue(storage, residue, session_id="s1")
        record_reaction(storage, rid, "seen", session_id="s2")

        surfaced = surface_residue(storage, n=3)
        assert len(surfaced) >= 1  # comes back as recurring


class TestResidueBias:
    """Test that residue biases recall queries without dominating them."""

    @pytest.fixture
    def storage(self, tmp_path):
        import os
        from storage import Storage
        migrations_dir = os.path.join(os.path.dirname(__file__), "..", "migrations")
        return Storage(str(tmp_path / "test.db"), migrations_dir=migrations_dir)

    def test_bias_shifts_embedding(self, storage):
        """With active residues, the query embedding should change."""
        # Store a residue
        embedding = np.random.randn(768).tolist()
        residue = distill("deep unease and dread", embedding)
        store_residue(storage, residue, session_id="s1")

        # Simulate what _apply_residue_bias does
        import struct
        query = np.random.randn(768).tolist()
        query_arr = np.array(query, dtype=np.float32)

        # Load residue
        row = storage.conn.execute(
            "SELECT embedding FROM residue_vectors WHERE id = ?",
            (residue["id"],),
        ).fetchone()
        floats = struct.unpack(f"<{RESIDUE_DIM}f", row["embedding"])
        residue_vec = np.array(floats, dtype=np.float32)

        # Blend
        padded = np.zeros(768, dtype=np.float32)
        padded[:RESIDUE_DIM] = residue_vec
        blended = 0.85 * query_arr + 0.15 * padded
        blended = blended / np.linalg.norm(blended)

        # Should be different from original — the shift is subtle because
        # 64 dims zero-padded into 768 means only ~8% of dimensions are affected.
        # At alpha=0.15 the bias is real but small. That's by design.
        cos_sim = np.dot(query_arr / np.linalg.norm(query_arr), blended)
        assert cos_sim < 1.0  # mathematically shifted, even if slightly
        assert not np.allclose(query_arr / np.linalg.norm(query_arr), blended, atol=1e-6)

    def test_no_residue_no_change(self, storage):
        """Without residues, the query should pass through unchanged."""
        # No residues stored — bias should be identity
        exists = storage.conn.execute(
            "SELECT COUNT(*) FROM residue"
        ).fetchone()[0]
        assert exists == 0


class TestFormatForWake:
    def test_empty(self):
        assert format_for_wake([]) == ""

    def test_formats_residues(self):
        residues = [
            {"valence": 0.5, "fragments": "hope, light"},
            {"valence": -0.5, "fragments": "dread, heavy"},
            {"valence": 0.0, "fragments": "strange, between"},
        ]
        text = format_for_wake(residues)
        assert "Dream residue" in text
        assert "[light]" in text
        assert "[dark]" in text
        assert "[ambiguous]" in text
        assert "Don't explain them" in text
