"""Tests for sheaf sleep pass and content distillation."""

import json

import sheaf


class TestDistillSubdivision:
    def test_parses_valid_response(self, monkeypatch):
        reply = json.dumps({"peers": ["About Mistborn.", "About Perfect State."],
                            "hub": "Reading sessions in general."})
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: reply)
        out = sheaf.distill_subdivision(
            parent_content="Reading sessions: Mistborn and Perfect State",
            part_episode_contents=[["read mistborn ch1"], ["read perfect state"]],
            has_ambiguous=True, framing_cfg=None)
        assert out == (["About Mistborn.", "About Perfect State."],
                       "Reading sessions in general.")

    def test_none_on_transport_failure(self, monkeypatch):
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: None)
        assert sheaf.distill_subdivision("x", [["a"], ["b"]], False, None) is None

    def test_none_on_wrong_peer_count(self, monkeypatch):
        reply = json.dumps({"peers": ["only one"], "hub": None})
        monkeypatch.setattr(sheaf, "_ollama_generate", lambda prompt, cfg: reply)
        assert sheaf.distill_subdivision("x", [["a"], ["b"]], False, None) is None
