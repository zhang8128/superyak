"""Behavioral tests for the source/state runtime boundary."""

from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import runpy
import shutil
import socket
import sqlite3
import subprocess
import sys

import pytest


REPOSITORY = Path(__file__).resolve().parents[2]
RUNTIME = REPOSITORY / "scripts" / "runtime.py"
HOOKS = REPOSITORY / "engram" / "hooks"
REVISION = "0123456789abcdef0123456789abcdef01234567"


def _write(path: Path, content: str, *, executable: bool = False) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")
    if executable:
        path.chmod(0o755)


def _synthetic_source(tmp_path: Path) -> tuple[Path, Path]:
    """Copy the real launcher into a source tree with a recording Python."""
    assert RUNTIME.is_file(), "the canonical runtime launcher is not implemented"
    source = tmp_path / "source"
    launcher = source / "scripts" / "runtime.py"
    launcher.parent.mkdir(parents=True)
    shutil.copy2(RUNTIME, launcher)
    for relative in (
        "engram/server.py",
        "engram/hooks/wake.py",
        "engram/hooks/nudge.py",
        "engram/hooks/sleep.py",
        "engram/lighthouse_daemon.py",
        "engram/embedder_service.py",
        "team/run_team.py",
    ):
        _write(source / relative, "# synthetic target\n")
    interpreter = source / "engram" / ".venv" / "bin" / "python"
    _write(
        interpreter,
        "#!/usr/bin/env python3\n"
        "import json, os, pathlib, sys\n"
        "pathlib.Path(os.environ['RECORD_EXEC']).write_text(json.dumps({\n"
        "  'argv': sys.argv[1:],\n"
        "  'cwd': os.getcwd(),\n"
        "  'engram_home': os.environ.get('ENGRAM_HOME'),\n"
        "  'instance': os.environ.get('ENGRAM_DEFAULT_INSTANCE'),\n"
        "  'harness': os.environ.get('ENGRAM_HARNESS'),\n"
        "  'run_key': os.environ.get('ENGRAM_RUN_KEY'),\n"
        "  'sentinel': os.environ.get('PRESERVE_SENTINEL'),\n"
        "  'embedder_socket': os.environ.get('ENGRAM_EMBEDDER_SOCKET'),\n"
        "}))\n",
        executable=True,
    )
    _write(source / ".git" / "HEAD", REVISION + "\n")
    return source, launcher


def _runtime_config(path: Path, memory_home: Path, instance: str = "engram") -> Path:
    path.write_text(
        json.dumps({"memory_home": str(memory_home), "default_instance": instance}),
        encoding="utf-8",
    )
    return path


def _run_launcher(
    launcher: Path,
    config: Path,
    *args: str,
    cwd: Path | None = None,
    env: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[str]:
    command = [sys.executable, str(launcher), "--config", str(config), *args]
    return subprocess.run(
        command,
        cwd=cwd,
        env=env,
        text=True,
        capture_output=True,
        timeout=10,
        check=False,
    )


def _tree_snapshot(root: Path) -> dict[str, tuple[str, str]]:
    snapshot = {}
    for path in sorted(root.rglob("*")):
        relative = str(path.relative_to(root))
        if path.is_file():
            snapshot[relative] = (
                "file",
                hashlib.sha256(path.read_bytes()).hexdigest(),
            )
        elif path.is_dir():
            snapshot[relative] = ("directory", "")
    return snapshot


@pytest.mark.parametrize(
    ("arguments", "target", "tail"),
    [
        (("mcp",), "engram/server.py", []),
        (("hook", "wake"), "engram/hooks/wake.py", []),
        (("hook", "nudge"), "engram/hooks/nudge.py", []),
        (("hook", "sleep"), "engram/hooks/sleep.py", []),
        (
            ("publisher",),
            "engram/lighthouse_daemon.py",
            [
                "--config",
                ".engram/lighthouse-daemon.toml",
                "--socket",
                ".engram/lighthouse.sock",
            ],
        ),
    ],
)
def test_launcher_executes_source_target_and_preserves_process_context(
    tmp_path, arguments, target, tail
):
    source, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    _write(memory_home / ".engram" / "instances" / "engram" / "graph.db", "")
    if arguments == ("publisher",):
        _write(
            memory_home / ".engram" / "lighthouse-daemon.toml",
            'publishers = ["lighthouse"]\n',
        )
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    caller_cwd = tmp_path / "caller"
    caller_cwd.mkdir()
    record = tmp_path / "exec.json"
    env = {
        **os.environ,
        "RECORD_EXEC": str(record),
        "ENGRAM_HOME": "/stale/home",
        "ENGRAM_DEFAULT_INSTANCE": "stale-instance",
        "ENGRAM_HARNESS": "codex",
        "ENGRAM_RUN_KEY": "codex:4321",
        "PRESERVE_SENTINEL": "kept",
    }

    result = _run_launcher(launcher, config, *arguments, cwd=caller_cwd, env=env)

    assert result.returncode == 0, result.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    expected_target = str(source / target)
    expected_tail = [
        str(memory_home / item) if item.startswith(".engram/") else item
        for item in tail
    ]
    assert observed["argv"] == [expected_target, *expected_tail]
    assert observed["cwd"] == str(caller_cwd)
    assert observed["engram_home"] == str(memory_home)
    assert observed["instance"] == "engram"
    assert observed["harness"] == "codex"
    assert observed["run_key"] == "codex:4321"
    assert observed["sentinel"] == "kept"


def test_instance_override_replaces_only_the_configured_default(tmp_path):
    _, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    _write(memory_home / ".engram" / "instances" / "research" / "graph.db", "")
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record), "PRESERVE_SENTINEL": "yes"}

    result = _run_launcher(
        launcher, config, "--instance", "research", "mcp", env=env
    )

    assert result.returncode == 0, result.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["instance"] == "research"
    assert observed["engram_home"] == str(memory_home)
    assert observed["sentinel"] == "yes"


def test_publisher_resolves_relative_socket_independently_of_caller_cwd(tmp_path):
    source, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    daemon_config = memory_home / ".engram" / "lighthouse-daemon.toml"
    _write(daemon_config, 'publishers = ["lighthouse"]\nsocket = "publisher.sock"\n')
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    caller = tmp_path / "unrelated-caller"
    caller.mkdir()
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}

    result = _run_launcher(launcher, config, "publisher", cwd=caller, env=env)

    assert result.returncode == 0, result.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["argv"] == [
        str(source / "engram" / "lighthouse_daemon.py"),
        "--config",
        str(daemon_config),
        "--socket",
        str(daemon_config.parent / "publisher.sock"),
    ]
    assert observed["cwd"] == str(caller)


@pytest.mark.parametrize(
    ("config_body", "message"),
    [
        (None, "runtime configuration does not exist"),
        ('{"memory_home": "relative", "default_instance": "engram"}', "absolute"),
        ('{"memory_home": "/tmp", "default_instance": "../escape"}', "instance"),
    ],
)
def test_invalid_or_missing_config_fails_without_creating_state(
    tmp_path, config_body, message
):
    _, launcher = _synthetic_source(tmp_path)
    config = tmp_path / "configuration" / "runtime.json"
    if config_body is not None:
        config.parent.mkdir()
        config.write_text(config_body, encoding="utf-8")
    before = _tree_snapshot(tmp_path)

    result = _run_launcher(launcher, config, "mcp")

    assert result.returncode != 0
    assert message in result.stderr.lower()
    assert "traceback" not in result.stderr.lower()
    assert _tree_snapshot(tmp_path) == before


def test_missing_interpreter_fails_without_executing_or_writing(tmp_path):
    _, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    interpreter = launcher.parent.parent / "engram" / ".venv" / "bin" / "python"
    interpreter.unlink()
    before = _tree_snapshot(tmp_path)

    result = _run_launcher(launcher, config, "mcp")

    assert result.returncode != 0
    assert str(interpreter) in result.stderr
    assert "interpreter" in result.stderr.lower()
    assert _tree_snapshot(tmp_path) == before


def test_publisher_rejects_invalid_daemon_configuration_before_exec(tmp_path):
    _, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    _write(memory_home / ".engram" / "lighthouse-daemon.toml", "publishers = []\n")
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}
    before = _tree_snapshot(tmp_path)

    result = _run_launcher(launcher, config, "publisher", env=env)

    assert result.returncode != 0
    assert "publisher configuration" in result.stderr.lower()
    assert "traceback" not in result.stderr.lower()
    assert not record.exists()
    assert _tree_snapshot(tmp_path) == before


@pytest.mark.parametrize("arguments", [("mcp",), ("hook", "wake")])
def test_memory_commands_reject_an_empty_memory_home_without_creating_a_store(
    tmp_path, arguments
):
    _, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "empty-memory-home"
    memory_home.mkdir()
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}
    before = _tree_snapshot(tmp_path)

    result = _run_launcher(launcher, config, *arguments, env=env)

    assert result.returncode != 0
    assert "memory database" in result.stderr.lower()
    assert not record.exists()
    assert _tree_snapshot(tmp_path) == before


def _create_memory_log(db_path: Path, *, with_receipt: bool = False) -> None:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.execute(
        "CREATE TABLE memory_log (id TEXT, timestamp TEXT, event_type TEXT, context TEXT)"
    )
    if with_receipt:
        connection.execute(
            "INSERT INTO memory_log VALUES (?, ?, ?, ?)",
            (
                "log-row-id",
                "2026-09-09T17:05:04+00:00",
                "lighthouse_receipt",
                json.dumps(
                    {
                        "query": "SECRET QUERY MUST NOT LEAK",
                        "receipt": {
                            "id": "urn:engram:engram:receipt:latest",
                            "payload": {"delivered": ["SECRET MEMORY MUST NOT LEAK"]},
                        },
                    }
                ),
            ),
        )
    connection.commit()
    connection.close()


def _healthy_status_tree(tmp_path: Path, *, receipt: bool = True):
    source, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    receiver = memory_home / ".engram" / "instances" / "engram"
    publisher = memory_home / ".engram" / "instances" / "lighthouse"
    _create_memory_log(receiver / "graph.db", with_receipt=receipt)
    _create_memory_log(publisher / "graph.db")
    socket_path = Path("/tmp") / (
        f"superyak-runtime-{os.getpid()}-{tmp_path.name}.sock"
    )
    socket_path.unlink(missing_ok=True)
    _write(
        receiver / "lighthouse-receiver.toml",
        'enabled = true\npublishers = ["lighthouse"]\n'
        f'socket_path = "{socket_path}"\n'
        'policy_path = "lighthouse-receiver-policy.json"\n',
    )
    _write(
        receiver / "lighthouse-receiver-policy.json",
        json.dumps(
            {
                "kind": "ConnectionPolicy",
                "issuer": "urn:engram:engram",
                "payload": {"rules": []},
            }
        ),
    )
    _write(
        publisher / "lighthouse-policy.json",
        json.dumps(
            {
                "kind": "ConnectionPolicy",
                "issuer": "urn:engram:lighthouse",
                "payload": {"rules": []},
            }
        ),
    )
    _write(
        memory_home / ".engram" / "lighthouse-daemon.toml",
        f'publishers = ["lighthouse"]\nsocket = "{socket_path}"\n',
    )
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    return source, launcher, memory_home, config, socket_path


def test_status_reports_healthy_installation_and_latest_receipt_without_content(
    tmp_path,
):
    source, launcher, memory_home, config, socket_path = _healthy_status_tree(
        tmp_path
    )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    before = _tree_snapshot(tmp_path)
    try:
        result = _run_launcher(launcher, config, "status")
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)

    assert result.returncode == 0, result.stderr
    status = json.loads(result.stdout)
    assert status["ok"] is True
    assert status["source"] == {
        "path": str(source),
        "configured_revision": REVISION,
    }
    assert status["interpreter"] == {
        "path": str(source / "engram" / ".venv" / "bin" / "python"),
        "available": True,
    }
    assert status["memory_home"] == {
        "path": str(memory_home),
        "available": True,
    }
    assert status["instance"] == {
        "configured_default": "engram",
        "project_override": None,
        "project_root": str(Path.cwd()),
        "name": "engram",
        "database": str(
            memory_home / ".engram" / "instances" / "engram" / "graph.db"
        ),
        "available": True,
    }
    assert status["receiver"]["state"] == "enabled"
    assert status["receiver"]["publishers"] == ["lighthouse"]
    assert status["publisher"]["state"] == "available"
    assert status["publisher"]["publishers"] == ["lighthouse"]
    assert status["socket"] == {
        "path": str(socket_path.resolve()),
        "connected": True,
    }
    assert status["latest_lighthouse_receipt"] == {
        "id": "urn:engram:engram:receipt:latest",
        "timestamp": "2026-09-09T17:05:04+00:00",
    }
    assert "SECRET" not in result.stdout
    assert _tree_snapshot(tmp_path) == before


def test_status_does_not_create_sidecars_for_a_checkpointed_wal_database(tmp_path):
    _, launcher, memory_home, config, socket_path = _healthy_status_tree(
        tmp_path, receipt=False
    )
    database = memory_home / ".engram" / "instances" / "engram" / "graph.db"
    database.unlink()
    connection = sqlite3.connect(database)
    connection.execute("PRAGMA journal_mode = WAL")
    connection.execute(
        "CREATE TABLE memory_log (id TEXT, timestamp TEXT, event_type TEXT, context TEXT)"
    )
    connection.commit()
    connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    connection.close()
    assert not Path(str(database) + "-wal").exists()
    assert not Path(str(database) + "-shm").exists()
    before = _tree_snapshot(memory_home)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    try:
        result = _run_launcher(launcher, config, "status")
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["latest_lighthouse_receipt"] is None
    assert _tree_snapshot(memory_home) == before


def test_status_reads_latest_active_wal_receipt_without_touching_source_files(
    tmp_path,
):
    _, launcher, memory_home, config, socket_path = _healthy_status_tree(
        tmp_path, receipt=False
    )
    database = memory_home / ".engram" / "instances" / "engram" / "graph.db"
    database.unlink()
    writer = sqlite3.connect(database)
    writer.execute("PRAGMA journal_mode = WAL")
    writer.execute("PRAGMA wal_autocheckpoint = 0")
    writer.execute(
        "CREATE TABLE memory_log (id TEXT, timestamp TEXT, event_type TEXT, context TEXT)"
    )
    writer.commit()
    writer.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    writer.execute(
        "INSERT INTO memory_log VALUES (?, ?, ?, ?)",
        (
            "row-in-wal",
            "2026-09-09T18:06:05+00:00",
            "lighthouse_receipt",
            json.dumps(
                {
                    "receipt": {"id": "urn:engram:engram:receipt:active-wal"},
                    "query": "ACTIVE WAL SECRET",
                }
            ),
        ),
    )
    writer.commit()
    assert Path(str(database) + "-wal").is_file()
    before = _tree_snapshot(memory_home)
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    try:
        result = _run_launcher(launcher, config, "status")
        after = _tree_snapshot(memory_home)
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)
        writer.close()

    assert result.returncode == 0, result.stdout + result.stderr
    assert json.loads(result.stdout)["latest_lighthouse_receipt"] == {
        "id": "urn:engram:engram:receipt:active-wal",
        "timestamp": "2026-09-09T18:06:05+00:00",
    }
    assert "SECRET" not in result.stdout
    assert after == before


def test_receipt_snapshot_refuses_to_copy_more_than_its_byte_budget(tmp_path):
    database = tmp_path / "graph.db"
    _create_memory_log(database)
    runtime = runpy.run_path(str(RUNTIME))
    runtime["_latest_receipt"].__globals__["MAX_DATABASE_SNAPSHOT_BYTES"] = 1

    receipt, error = runtime["_latest_receipt"](database)

    assert receipt is None
    assert error == "database snapshot exceeds status byte limit"


def test_status_identifies_disconnected_socket_and_allows_no_receipt(tmp_path):
    _, launcher, _, config, socket_path = _healthy_status_tree(
        tmp_path, receipt=False
    )
    stale = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    stale.bind(str(socket_path))
    stale.close()

    try:
        result = _run_launcher(launcher, config, "status")
    finally:
        socket_path.unlink(missing_ok=True)

    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["ok"] is False
    assert status["receiver"]["state"] == "enabled"
    assert status["socket"] == {
        "path": str(socket_path.resolve()),
        "connected": False,
        "error": "connection unavailable",
    }
    assert status["latest_lighthouse_receipt"] is None


def test_status_reports_a_receiver_choice_the_publisher_does_not_serve(tmp_path):
    _, launcher, memory_home, config, socket_path = _healthy_status_tree(tmp_path)
    receiver = memory_home / ".engram" / "instances" / "engram"
    settings = receiver / "lighthouse-receiver.toml"
    settings.write_text(
        settings.read_text(encoding="utf-8").replace("lighthouse", "missing", 1),
        encoding="utf-8",
    )
    listener = socket.socket(socket.AF_UNIX, socket.SOCK_STREAM)
    listener.bind(str(socket_path))
    listener.listen(1)
    try:
        result = _run_launcher(launcher, config, "status")
    finally:
        listener.close()
        socket_path.unlink(missing_ok=True)

    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["receiver"]["state"] == "enabled"
    assert status["receiver"]["unavailable_publishers"] == ["missing"]


@pytest.mark.parametrize(
    ("receiver_config", "expected_state"),
    [
        (None, "disabled"),
        ('enabled = false\n', "disabled"),
        ('enabled = true\npublishers = "lighthouse"\n', "invalid"),
    ],
)
def test_status_distinguishes_disabled_and_invalid_receiver(
    tmp_path, receiver_config, expected_state
):
    _, launcher, memory_home, config, _ = _healthy_status_tree(tmp_path)
    settings = (
        memory_home
        / ".engram"
        / "instances"
        / "engram"
        / "lighthouse-receiver.toml"
    )
    if receiver_config is None:
        settings.unlink()
    else:
        settings.write_text(receiver_config, encoding="utf-8")

    result = _run_launcher(launcher, config, "status")

    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["receiver"]["state"] == expected_state
    if expected_state == "invalid":
        assert status["receiver"]["error"] == "invalid receiver configuration"
    assert "traceback" not in result.stderr.lower()


def test_status_bounds_malformed_receiver_values_without_a_traceback(tmp_path):
    _, launcher, memory_home, config, _ = _healthy_status_tree(tmp_path)
    settings = (
        memory_home
        / ".engram"
        / "instances"
        / "engram"
        / "lighthouse-receiver.toml"
    )
    settings.write_text('enabled = true\npublishers = [{bad = "value"}]\n')

    result = _run_launcher(launcher, config, "status")

    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["receiver"]["state"] == "invalid"
    assert "traceback" not in result.stderr.lower()


def test_status_rejects_receiver_options_the_runtime_does_not_support(tmp_path):
    _, launcher, memory_home, config, _ = _healthy_status_tree(tmp_path)
    settings = (
        memory_home
        / ".engram"
        / "instances"
        / "engram"
        / "lighthouse-receiver.toml"
    )
    settings.write_text(settings.read_text() + "discover_publishers = true\n")

    result = _run_launcher(launcher, config, "status")

    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["receiver"]["state"] == "invalid"


def test_status_reports_missing_selected_database_without_creating_it(tmp_path):
    _, launcher, memory_home, config, _ = _healthy_status_tree(tmp_path)
    database = (
        memory_home / ".engram" / "instances" / "engram" / "graph.db"
    )
    database.unlink()
    before = _tree_snapshot(tmp_path)

    result = _run_launcher(launcher, config, "status")

    assert result.returncode != 0
    status = json.loads(result.stdout)
    assert status["instance"] == {
        "configured_default": "engram",
        "project_override": None,
        "project_root": str(Path.cwd()),
        "name": "engram",
        "database": str(database),
        "available": False,
    }
    assert status["latest_lighthouse_receipt"] is None
    assert _tree_snapshot(tmp_path) == before


def test_status_reports_project_instance_override_as_the_effective_database(tmp_path):
    _, launcher, memory_home, config, _ = _healthy_status_tree(tmp_path)
    project = tmp_path / "project"
    _write(project / ".engram" / "config.toml", 'instance = "project-memory"\n')
    project_database = (
        memory_home / ".engram" / "instances" / "project-memory" / "graph.db"
    )
    _create_memory_log(project_database)

    result = _run_launcher(launcher, config, "status", cwd=project)

    assert result.returncode != 0  # this instance has no enabled receiver
    status = json.loads(result.stdout)
    assert status["instance"] == {
        "configured_default": "engram",
        "project_override": "project-memory",
        "project_root": str(project),
        "name": "project-memory",
        "database": str(project_database),
        "available": True,
    }


def _copy_hook_installation(tmp_path: Path, hook_name: str) -> tuple[Path, Path]:
    source = tmp_path / "installed" / "engram"
    hooks = source / "hooks"
    hooks.mkdir(parents=True)
    shutil.copy2(HOOKS / f"{hook_name}.py", hooks / f"{hook_name}.py")
    shutil.copy2(HOOKS / "harness.py", hooks / "harness.py")
    return source, hooks / f"{hook_name}.py"


def _module_probe(module_dir: Path, label: str, names: tuple[str, ...]) -> None:
    for name in names:
        if name == "sqlite_vec":
            body = (
                "import os, pathlib\n"
                f"LABEL = {label!r}\n"
                "def load(connection):\n"
                "    path = connection.execute('PRAGMA database_list').fetchone()[2]\n"
                "    pathlib.Path(os.environ['MODULE_LOG']).write_text(LABEL + ':' + path)\n"
            )
        elif name == "deep_pass":
            body = (
                "import os, pathlib\n"
                f"LABEL = {label!r}\n"
                "def deep_pass(storage, embeddings, session_id=None):\n"
                "    pathlib.Path(os.environ['MODULE_LOG']).write_text(LABEL + ':' + storage.path)\n"
                "    return {'structural_count': 0, 'gap_count': 0}\n"
            )
        elif name == "storage":
            body = (
                "class Storage:\n"
                "    def __init__(self, path): self.path = path\n"
                "    def close(self): pass\n"
            )
        else:
            body = (
                "class NomicEmbedProvider: pass\n"
                "def create_embedding_provider(): return NomicEmbedProvider()\n"
            )
        _write(module_dir / f"{name}.py", body)


def test_nudge_imports_code_from_installation_but_database_from_memory_home(tmp_path):
    source, hook = _copy_hook_installation(tmp_path, "nudge")
    memory_home = tmp_path / "memory"
    database = memory_home / ".engram" / "instances" / "research" / "graph.db"
    _create_memory_log(database)
    _module_probe(source, "source", ("sqlite_vec",))
    _module_probe(memory_home, "stale", ("sqlite_vec",))
    module_log = tmp_path / "module.log"
    project = tmp_path / "caller-project"
    project.mkdir()
    env = {
        **os.environ,
        "ENGRAM_HOME": str(memory_home),
        "ENGRAM_DEFAULT_INSTANCE": "research",
        "ENGRAM_PROJECT_ROOT": str(project),
        "ENGRAM_HARNESS": "codex",
        "MODULE_LOG": str(module_log),
    }

    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps(
            {"session_id": "synthetic", "prompt": "a sufficiently long prompt"}
        ),
        text=True,
        capture_output=True,
        cwd=project,
        env=env,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert module_log.read_text(encoding="utf-8") == f"source:{database}"


def test_wake_imports_deep_pass_from_installation_and_uses_instance_database(tmp_path):
    source, hook = _copy_hook_installation(tmp_path, "wake")
    memory_home = tmp_path / "memory"
    database = memory_home / ".engram" / "instances" / "research" / "graph.db"
    database.parent.mkdir(parents=True)
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE episodes (id TEXT, content TEXT);
        CREATE TABLE semantics (
          content TEXT, kind TEXT, confidence REAL, created_at TEXT, lane TEXT,
          contradicted_by TEXT, reinforced_count INTEGER
        );
        CREATE TABLE instincts (
          id TEXT, trigger TEXT, action TEXT, strength REAL, fired_count INTEGER,
          followed_count INTEGER, notice TEXT, implication TEXT, context TEXT
        );
        """
    )
    connection.close()
    _module_probe(source, "source", ("deep_pass", "embeddings", "storage"))
    _module_probe(memory_home, "stale", ("deep_pass", "embeddings", "storage"))
    module_log = tmp_path / "module.log"
    project = tmp_path / "caller-project"
    project.mkdir()
    env = {
        **os.environ,
        "ENGRAM_HOME": str(memory_home),
        "ENGRAM_DEFAULT_INSTANCE": "research",
        "ENGRAM_PROJECT_ROOT": str(project),
        "ENGRAM_HARNESS": "codex",
        "MODULE_LOG": str(module_log),
    }

    result = subprocess.run(
        [sys.executable, str(hook)],
        input=json.dumps({"session_id": "", "cwd": str(project)}),
        text=True,
        capture_output=True,
        cwd=project,
        env=env,
        timeout=10,
        check=False,
    )

    assert result.returncode == 0, result.stderr
    assert module_log.read_text(encoding="utf-8") == f"source:{database}"


def test_embedder_socket_is_passed_to_engram_processes_and_runs_the_embedder(tmp_path):
    source, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    _write(memory_home / ".engram" / "instances" / "engram" / "graph.db", "")
    sock = tmp_path / "run" / "embedder.sock"
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({
        "memory_home": str(memory_home),
        "default_instance": "engram",
        "embedder_socket": str(sock),
    }), encoding="utf-8")
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}
    env.pop("ENGRAM_EMBEDDER_SOCKET", None)

    for arguments in (("mcp",), ("hook", "nudge")):
        result = _run_launcher(launcher, config, *arguments, env=env)
        assert result.returncode == 0, result.stderr
        assert json.loads(record.read_text(encoding="utf-8"))["embedder_socket"] == str(sock)

    result = _run_launcher(launcher, config, "embedder", env=env)
    assert result.returncode == 0, result.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["argv"] == [str(source / "engram" / "embedder_service.py"), "--socket", str(sock)]


def test_without_embedder_socket_processes_load_their_own_model(tmp_path):
    _, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    _write(memory_home / ".engram" / "instances" / "engram" / "graph.db", "")
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}
    env.pop("ENGRAM_EMBEDDER_SOCKET", None)

    result = _run_launcher(launcher, config, "mcp", env=env)
    assert result.returncode == 0, result.stderr
    assert json.loads(record.read_text(encoding="utf-8"))["embedder_socket"] is None

    result = _run_launcher(launcher, config, "embedder", env=env)
    assert result.returncode == 2
    assert "embedder_socket" in result.stderr


def test_embedder_socket_must_be_absolute(tmp_path):
    _, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    config = tmp_path / "runtime.json"
    config.write_text(json.dumps({
        "memory_home": str(memory_home),
        "default_instance": "engram",
        "embedder_socket": "relative.sock",
    }), encoding="utf-8")

    result = _run_launcher(launcher, config, "embedder")
    assert result.returncode == 2
    assert "absolute" in result.stderr

def test_team_runs_the_team_launcher_without_a_memory_database(tmp_path):
    source, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"          # no graph.db: team mode must not need one
    memory_home.mkdir()
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}

    result = _run_launcher(launcher, config, "team", cwd=tmp_path, env=env)

    assert result.returncode == 0, result.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["argv"] == [str(source / "team" / "run_team.py")]
    assert not (memory_home / ".engram").exists()   # launcher creates no state


def test_team_passes_cli_arguments_through(tmp_path):
    source, launcher = _synthetic_source(tmp_path)
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}

    result = _run_launcher(launcher, config, "team", "status", "team=t-res", cwd=tmp_path, env=env)

    assert result.returncode == 0, result.stderr
    observed = json.loads(record.read_text(encoding="utf-8"))
    assert observed["argv"] == [str(source / "team" / "run_team.py"), "status", "team=t-res"]


def test_team_launcher_missing_fails_before_exec(tmp_path):
    source, launcher = _synthetic_source(tmp_path)
    (source / "team" / "run_team.py").unlink()
    memory_home = tmp_path / "memory"
    memory_home.mkdir()
    config = _runtime_config(tmp_path / "runtime.json", memory_home)
    record = tmp_path / "exec.json"
    env = {**os.environ, "RECORD_EXEC": str(record)}

    result = _run_launcher(launcher, config, "team", cwd=tmp_path, env=env)

    assert result.returncode == 2 and "source script is unavailable" in result.stderr
    assert not record.exists()
