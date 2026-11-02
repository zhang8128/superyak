"""The superyak-memory plugin's launcher (plugins/superyak-memory/bin/engram), run from an installed copy."""

from __future__ import annotations

import json
import os
import shutil
import socket
import subprocess
import sys
from pathlib import Path

import pytest

PLUGIN = Path(__file__).resolve().parents[2] / "plugins" / "superyak-memory"
REPORT = "import json, os, sys; print(json.dumps({'script': sys.argv[0], 'env': {k: os.environ.get(k) for k in ('ENGRAM_HOME', 'ENGRAM_DEFAULT_INSTANCE', 'ENGRAM_EMBEDDER_SOCKET', 'ENGRAM_HARNESS')}}))\n"


@pytest.fixture
def place(tmp_path):
    """A fake checkout, a cached copy of the plugin outside it, and a Claude config dir."""
    checkout = tmp_path / "checkout"
    for script in ("engram/server.py", "engram/hooks/wake.py", "engram/hooks/nudge.py", "engram/hooks/sleep.py"):
        (checkout / script).parent.mkdir(parents=True, exist_ok=True)
        (checkout / script).write_text(REPORT)
    (checkout / "engram/.venv/bin").mkdir(parents=True)
    os.symlink(sys.executable, checkout / "engram/.venv/bin/python")
    cached = tmp_path / "cfg/plugins/cache/superyak/superyak-memory/0.1.0"
    shutil.copytree(PLUGIN, cached)
    home = tmp_path / "memory"
    home.mkdir()
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({"memory_home": str(home), "default_instance": "rio-grande", "embedder_socket": str(tmp_path / "e.sock")}))
    return {"tmp": tmp_path, "checkout": checkout, "launcher": cached / "bin/engram", "config": config, "home": home}


def _run(place, *args, marketplace=True):
    if marketplace:
        record = {"superyak": {"source": {"source": "directory", "path": str(place["checkout"])}, "installLocation": str(place["checkout"])}}
        (place["tmp"] / "cfg/plugins/known_marketplaces.json").write_text(json.dumps(record))
    env = {"PATH": os.environ["PATH"], "HOME": str(place["tmp"]), "CLAUDE_CONFIG_DIR": str(place["tmp"] / "cfg"), "SUPERYAK_RUNTIME_CONFIG": str(place["config"])}
    return subprocess.run([str(place["launcher"]), *args], env=env, capture_output=True, text=True, timeout=30)


def test_an_installed_copy_runs_the_server_from_the_marketplace_checkout(place):
    result = _run(place)
    assert result.returncode == 0, result.stderr
    report = json.loads(result.stdout)
    assert report["script"] == str(place["checkout"] / "engram/server.py")
    assert report["env"]["ENGRAM_HOME"] == str(place["home"])
    assert report["env"]["ENGRAM_DEFAULT_INSTANCE"] == "rio-grande"
    assert report["env"]["ENGRAM_EMBEDDER_SOCKET"] is None  # configured, but nothing listens there


def test_the_socket_is_passed_when_it_exists_and_the_nudge_runs(place):
    with socket.socket(socket.AF_UNIX) as listening:
        listening.bind(str(place["tmp"] / "e.sock"))
        served = json.loads(_run(place).stdout)
        nudged = json.loads(_run(place, "hook", "nudge").stdout)
    assert served["env"]["ENGRAM_EMBEDDER_SOCKET"] == str(place["tmp"] / "e.sock")
    assert nudged["script"] == str(place["checkout"] / "engram/hooks/nudge.py")
    assert nudged["env"]["ENGRAM_HARNESS"] == "claude-code"


def test_without_the_shared_embedder_the_nudge_does_nothing(place):
    nudged = _run(place, "hook", "nudge")
    assert nudged.returncode == 0 and nudged.stdout == ""
    woke = json.loads(_run(place, "hook", "wake").stdout)
    assert woke["script"] == str(place["checkout"] / "engram/hooks/wake.py")


def test_no_checkout_is_a_clear_refusal(place):
    result = _run(place, marketplace=False)
    assert result.returncode == 1
    assert "can't find the Superyak checkout" in result.stderr
    assert _run(place, "hook", "dream").returncode == 2
