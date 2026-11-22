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


import shutil  # noqa: E402
import tempfile  # noqa: E402

from tests.test_embedder_service import FakeProvider, _serve  # noqa: E402
from tests.test_recall_margins import engram_server_env  # noqa: E402,F401 - the real server on a temp home

# A hook run in a subprocess gets none of the test's monkeypatched fakes. Its model cache sits under HOME
# (embeddings._CACHE_DIR), and the test's HOME is empty, so without this the hook downloads the model from the network
# on every run: CI timed out on it on three branches on 11-21. No network here, so a download fails at once.
_NO_NETWORK = {"HF_HUB_OFFLINE": "1", "HTTP_PROXY": "http://127.0.0.1:9", "HTTPS_PROXY": "http://127.0.0.1:9",
               "http_proxy": "http://127.0.0.1:9", "https_proxy": "http://127.0.0.1:9", "NO_PROXY": "", "no_proxy": ""}


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
    prompt = "What did the lighthouse crossing record for the receiving store?"
    # The hook embeds through the shared-embedder socket, served here by a fake: no model, no network.
    sockets = Path(tempfile.mkdtemp(prefix="emb-", dir="/tmp"))   # AF_UNIX paths are short; tmp_path can be too long
    provider = FakeProvider()
    service = _serve(sockets / "e.sock", provider)
    try:
        env = {**os.environ, "ENGRAM_HOME": str(tmp_path), "ENGRAM_PROJECT_ROOT": str(tmp_path),
               "HOME": str(tmp_path / "home"), "ENGRAM_EMBEDDER_SOCKET": str(sockets / "e.sock"), **_NO_NETWORK}
        env.pop("CLAUDE_SESSION_ID", None)
        done = subprocess.run([sys.executable, str(NUDGE_SCRIPT)], input=json.dumps({"prompt": prompt}),
                              capture_output=True, text=True, env=env, timeout=120)
    finally:
        service.shutdown()
        service.server_close()
        shutil.rmtree(sockets, ignore_errors=True)
    assert done.returncode == 0, done.stderr
    # The hook catches every error and exits 0, so an absence alone would pass where nothing ran: it must have searched.
    assert "# nudge:" not in done.stderr, done.stderr
    assert ([prompt], "search_query") in provider.calls
    assert REMOTE_SENTENCE not in done.stdout and "Remote words stay remote" not in done.stdout
