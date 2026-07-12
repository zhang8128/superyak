"""Tests for the UserPromptSubmit nudge hook's output format."""

import importlib.util
import json
from pathlib import Path

NUDGE_SCRIPT = Path(__file__).resolve().parent.parent / "hooks" / "nudge.py"


def _load_nudge_module():
    spec = importlib.util.spec_from_file_location("engram_nudge_hook", NUDGE_SCRIPT)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


class TestNudgeOutput:
    def test_output_injected_into_context(self, capsys):
        """Nudge lines must reach the model via hookSpecificOutput.additionalContext.
        systemMessage is only displayed to the user — it never enters context.

        nudge.py no longer builds its own envelope (`_hook_output` was
        deleted in the harness-adapter integration); it delegates to
        `harness.emit`, imported into the module as `emit`."""
        nudge = _load_nudge_module()
        nudge.emit("claude-code", "UserPromptSubmit", "Thread: notice this")
        out = json.loads(capsys.readouterr().out)
        hso = out["hookSpecificOutput"]
        assert hso["hookEventName"] == "UserPromptSubmit"
        assert hso["additionalContext"] == "Thread: notice this"
        # The user-visible copy stays in sync with what the model sees
        assert out["systemMessage"] == "Thread: notice this"
