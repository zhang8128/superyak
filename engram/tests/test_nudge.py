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


from tests.test_recall_margins import engram_server_env  # noqa: E402,F401 - the real server on a temp home


def test_nudge_shows_no_remote_text_after_a_crossing(engram_server_env, tmp_path, monkeypatch):
    """Ship home and crossing plan, Task 12 (spec 2.5, rule 1): the nudge hook calls no neighbor, so after a recall
    that delivered remote text its output holds none of it."""
    import os
    import subprocess
    import sys
    import server
    from tests.test_wake import REMOTE_SENTENCE, REMOTE_TEXT, _deliver_remote_through_a_recall
    monkeypatch.setenv("HOME", str(tmp_path / "home"))
    server._init()
    assert _deliver_remote_through_a_recall(tmp_path, REMOTE_TEXT) == [REMOTE_TEXT]
    server._storage.conn.commit()
    env = {**os.environ, "ENGRAM_HOME": str(tmp_path), "ENGRAM_PROJECT_ROOT": str(tmp_path), "HOME": str(tmp_path / "home")}
    env.pop("CLAUDE_SESSION_ID", None)
    done = subprocess.run([sys.executable, str(NUDGE_SCRIPT)],
                          input=json.dumps({"prompt": "What did the lighthouse crossing record for the receiving store?"}),
                          capture_output=True, text=True, env=env, timeout=120)
    assert done.returncode == 0, done.stderr
    assert REMOTE_SENTENCE not in done.stdout and "Remote words stay remote" not in done.stdout
