"""fix:engram-permissions-default-home (all hands bdecc17a, Tardis's design in 72db4540): engram-permissions run with no
ENGRAM_HOME made and used a ledger in its own code directory (a checkout, or a plugin cache an update replaces), not the
person's. Real runs go through superyak-runtime, which sets ENGRAM_HOME from runtime.json's memory_home
(scripts/runtime.py), so the CLI now takes that same memory_home when the variable is missing, and refuses when neither
names a home. Every yes names the ledger it writes and where the home came from."""
import json
from pathlib import Path

import pytest

import permission_cli
from permission_cli import main
from permission_ledger import ledger_path
from tests.permissions_support import fake_tty  # noqa: F401 - a fixture


@pytest.fixture
def bare_run(tmp_path, monkeypatch):
    """No ENGRAM_HOME, HOME at a fresh folder, and the Unix login `andy`: as a person runs it from a plain shell."""
    monkeypatch.delenv("ENGRAM_HOME", raising=False)
    monkeypatch.setenv("HOME", str(tmp_path / "person"))
    (tmp_path / "person").mkdir()
    monkeypatch.setattr(permission_cli, "_login_name", lambda: "andy")
    return tmp_path


def _runtime_config(tmp_path, memory_home):
    config = tmp_path / "person" / ".config" / "superyak" / "runtime.json"
    config.parent.mkdir(parents=True)
    config.write_text(json.dumps({"default_instance": "rio-grande", "embedder_socket": "/nowhere.sock",
                                  "memory_home": str(memory_home)}))
    return config


def test_with_no_home_named_anywhere_it_refuses_and_writes_nothing_beside_the_code(bare_run, fake_tty, capsys):
    code_dir = Path(permission_cli.__file__).resolve().parent
    before = ledger_path(code_dir).exists()
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 1
    error = capsys.readouterr().err
    assert "ENGRAM_HOME" in error and "runtime.json" in error and "memory_home" in error
    assert ledger_path(code_dir).exists() == before            # nothing made in the code's own folder
    assert fake_tty.shown() == ""                              # refused before any yes was asked


def test_with_no_engram_home_it_takes_the_runtime_s_memory_home_and_says_so_at_the_yes(bare_run, fake_tty, capsys):
    memory_home = bare_run / "memories"
    _runtime_config(bare_run, memory_home)
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 0
    assert ledger_path(memory_home).is_file()
    assert f"ledger: {ledger_path(memory_home)}" in fake_tty.shown()
    assert "home from runtime.json's memory_home" in fake_tty.shown()
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 0                # a writing act finds the same ledger, and says so
    assert fake_tty.shown().count(f"ledger: {ledger_path(memory_home)}") == 2


def test_engram_home_wins_over_the_runtime_s_and_the_yes_says_which(bare_run, fake_tty, monkeypatch):
    _runtime_config(bare_run, bare_run / "memories")
    named = bare_run / "named"
    monkeypatch.setenv("ENGRAM_HOME", str(named))
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 0
    assert ledger_path(named).is_file() and not ledger_path(bare_run / "memories").exists()
    assert "home from ENGRAM_HOME" in fake_tty.shown()


@pytest.mark.parametrize("config", ['{"memory_home": ""}', '{"memory_home": 7}', "not json", '["memory_home"]'])
def test_a_runtime_config_without_a_usable_memory_home_names_no_home(bare_run, fake_tty, capsys, config):
    path = _runtime_config(bare_run, "unused")
    path.write_text(config)
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 1 and "ENGRAM_HOME" in capsys.readouterr().err
    assert fake_tty.shown() == ""


def test_a_writing_act_with_a_home_that_holds_no_ledger_still_refuses_and_makes_none(bare_run, fake_tty, capsys):
    """Tardis's guard: a wrong home must be a loud refusal, never a fresh ledger that takes the act. It holds today
    (Ledger._open raises on a missing file, and only init creates); this pins it on the new default."""
    memory_home = bare_run / "memories"
    _runtime_config(bare_run, memory_home)
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 1
    assert "no ledger" in capsys.readouterr().err and not ledger_path(memory_home).exists()
