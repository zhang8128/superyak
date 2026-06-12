"""Tests for the UserPromptSubmit nudge hook's output format."""

import importlib.util
from pathlib import Path

NUDGE_SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "nudge.py"


def _load_nudge_module():
    spec = importlib.util.spec_from_file_location("engram_nudge_hook", NUDGE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNudgeOutput:
    def test_output_injected_into_context(self):
        """Nudge lines must reach the model via hookSpecificOutput.additionalContext.
        systemMessage is only displayed to the user — it never enters context."""
        nudge = _load_nudge_module()
        out = nudge._hook_output("Thread: notice this")
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "UserPromptSubmit"
        assert hso["additionalContext"] == "Thread: notice this"
        # The user-visible copy stays in sync with what the model sees
        assert out["systemMessage"] == "Thread: notice this"
