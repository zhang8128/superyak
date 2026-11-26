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
    """runtime.json as superyak-runtime reads it: memory_home is an existing absolute folder (scripts/runtime.py:79-87)."""
    if Path(memory_home).is_absolute():
        Path(memory_home).mkdir(parents=True, exist_ok=True)
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
    line = f"ledger: {ledger_path(memory_home)} (home from runtime.json's memory_home)"
    assert fake_tty.shown().count(line) == 2                    # init's yes and the writing act's, each whole


def test_engram_home_wins_over_the_runtime_s_and_the_yes_says_which(bare_run, fake_tty, monkeypatch):
    _runtime_config(bare_run, bare_run / "memories")
    named = bare_run / "named"
    monkeypatch.setenv("ENGRAM_HOME", str(named))
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 0
    assert ledger_path(named).is_file() and not ledger_path(bare_run / "memories").exists()
    assert "home from ENGRAM_HOME" in fake_tty.shown()


@pytest.mark.parametrize("config", ['{"memory_home": ""}', '{"memory_home": 7}', "not json", '["memory_home"]',
                                    '{"memory_home": "rel-home"}', '{"memory_home": "~/mem"}',
                                    '{"memory_home": "/no/such/folder"}', '{"memory_home": "/x"}' + " " * 20_000])
def test_a_runtime_config_without_a_usable_memory_home_names_no_home(bare_run, fake_tty, capsys, config):
    path = _runtime_config(bare_run, "unused")
    path.write_text(config)
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 1 and "ENGRAM_HOME" in capsys.readouterr().err
    assert fake_tty.shown() == ""
    assert not (Path.cwd() / "rel-home").exists()               # a relative home is never taken from the folder it runs in


def test_a_writing_act_with_a_home_that_holds_no_ledger_still_refuses_and_makes_none(bare_run, fake_tty, capsys):
    """Tardis's guard: a wrong home must be a loud refusal, never a fresh ledger that takes the act. It holds today
    (Ledger._open raises on a missing file, and only init creates); this pins it on the new default."""
    memory_home = bare_run / "memories"
    _runtime_config(bare_run, memory_home)
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 1
    assert "no ledger" in capsys.readouterr().err and not ledger_path(memory_home).exists()



def test_a_runtime_config_that_is_not_a_regular_file_names_no_home_and_never_waits(bare_run):
    """runtime.py's own reader opens it non-blocking and reads only a regular file (scripts/runtime.py:40-63): a FIFO in
    its place must not hang the CLI (the fresh reader's NO on 5e904c2e)."""
    import os
    config = bare_run / "person" / ".config" / "superyak" / "runtime.json"
    config.parent.mkdir(parents=True)
    os.mkfifo(config)
    import threading
    answer = []
    reader = threading.Thread(target=lambda: answer.append(permission_cli._runtime_memory_home()), daemon=True)
    reader.start()
    reader.join(5)                                              # a blocking read would hang here: fail, don't wait
    if reader.is_alive():
        os.close(os.open(config, os.O_WRONLY | os.O_NONBLOCK))  # free the stuck reader, then fail
        reader.join(5)
        pytest.fail("reading a FIFO runtime.json blocked")
    assert answer == [None]


def test_one_command_resolves_its_home_once_so_the_yes_names_the_ledger_it_writes(bare_run, fake_tty, monkeypatch):
    """The fresh reader's NO on 5e904c2e: _ledger() and the yes's line each resolved the home, so runtime.json rewritten
    between them showed one ledger at the yes and wrote another. One command resolves it once."""
    first, second = bare_run / "first", bare_run / "second"
    for home in (first, second):
        home.mkdir()
    _runtime_config(bare_run, first)
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 0
    calls = []
    real = permission_cli._runtime_memory_home

    def moving():
        calls.append(1)
        return first if len(calls) == 1 else second              # as if runtime.json were rewritten mid-command
    monkeypatch.setattr(permission_cli, "_runtime_memory_home", moving)
    fake_tty.answer_the_printed_code()
    assert main(["person", "add", "jenn"]) == 0
    assert len(calls) == 1 and str(ledger_path(second)) not in fake_tty.shown() and not ledger_path(second).exists()
    monkeypatch.setattr(permission_cli, "_runtime_memory_home", real)



def test_each_command_resolves_its_own_home_and_a_caller_outside_main_keeps_none(tmp_path, monkeypatch, fake_tty):
    """Tardis (all hands bff06c16): the home is kept only while main() runs one command. Two commands in one process
    resolve separately, and a caller that imports this module, as scripts/unstamp_ledger.py does, never gets an earlier
    command's home (it did: test_5_unstamp_is_the_way_back_and_asks_the_persons_yes read a stale one)."""
    monkeypatch.setattr(permission_cli, "_login_name", lambda: "andy")
    first, second = tmp_path / "first", tmp_path / "second"
    monkeypatch.setenv("ENGRAM_HOME", str(first))
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 0
    monkeypatch.setenv("ENGRAM_HOME", str(second))
    assert permission_cli._home() == second                    # outside main(): afresh, not the first command's
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 0                                 # the second command: its own home
    assert ledger_path(first).is_file() and ledger_path(second).is_file()
    assert permission_cli._RESOLVED is None



@pytest.mark.parametrize("value", ["rel-home", ".", "~/mem"])
def test_a_memory_home_that_is_not_absolute_names_no_home_even_where_that_folder_exists(bare_run, fake_tty, capsys,
                                                                                      monkeypatch, value):
    """The fresh reader's second NO (on 3299be61): each case must exist as a folder, so only the absolute-path rule
    refuses it. "." would make the folder the command runs in the home, the bug itself, and "~" is never expanded,
    as runtime.py doesn't (scripts/runtime.py:83-84)."""
    here = bare_run / "here"
    (here / "rel-home").mkdir(parents=True)
    (bare_run / "person" / "mem").mkdir()
    monkeypatch.chdir(here)
    path = _runtime_config(bare_run, "unused")
    path.write_text(json.dumps({"memory_home": value}))
    assert permission_cli._runtime_memory_home() is None
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 1 and fake_tty.shown() == ""
    assert not list(here.rglob("permissions.db")) and not (bare_run / "person" / "mem" / ".engram").exists()


def test_a_runtime_config_past_its_size_limit_names_no_home_though_its_folder_exists(bare_run):
    """runtime.py reads at most 16,384 bytes (MAX_CONFIG_BYTES): one byte more, with memory_home an existing absolute
    folder, names no home; at the limit it does."""
    memory_home = bare_run / "memories"
    path = _runtime_config(bare_run, memory_home)
    body = json.dumps({"memory_home": str(memory_home)})
    path.write_text(body + " " * (permission_cli.RUNTIME_CONFIG_BYTES - len(body)))
    assert permission_cli._runtime_memory_home() == memory_home
    path.write_text(body + " " * (permission_cli.RUNTIME_CONFIG_BYTES - len(body) + 1))
    assert permission_cli._runtime_memory_home() is None


def test_unstamp_with_no_home_named_refuses_without_a_traceback(bare_run, capsys):
    """scripts/unstamp_ledger.py called _home() bare, so no home named ended in a RuleError traceback."""
    import sys
    scripts = str(Path(permission_cli.__file__).resolve().parent / "scripts")
    sys.path.insert(0, scripts)
    try:
        import unstamp_ledger
    finally:
        sys.path.remove(scripts)
    assert unstamp_ledger.main([]) == 1
    assert capsys.readouterr().err.startswith("refused: ")


@pytest.mark.parametrize("value", [".", "rel-home"])
def test_a_relative_engram_home_refuses_and_makes_nothing_where_the_command_runs(bare_run, fake_tty, capsys,
                                                                               monkeypatch, value):
    """Tardis's finding on a9fab0f1 (all hands 1575bf23): ENGRAM_HOME was taken as given, so "." run from engram/ put
    the ledger beside the code, the bug by the other door. It's held to an absolute path as runtime.json's value is
    (every runtime and test sets it absolute). A folder that doesn't exist yet stays allowed: init makes it on a
    person's first run, and a writing act already refuses where no ledger is."""
    here = bare_run / "here"
    (here / "rel-home").mkdir(parents=True)
    monkeypatch.chdir(here)
    monkeypatch.setenv("ENGRAM_HOME", value)
    fake_tty.answer_the_printed_code()
    assert main(["init"]) == 1 and "absolute" in capsys.readouterr().err
    assert fake_tty.shown() == "" and not list(here.rglob("permissions.db"))
