"""Installed-wheel integration tests for Engram's runtime boundary."""

from __future__ import annotations

import json
import os
import shutil
import subprocess
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def test_claude_plugin_defaults_unbound_projects_to_engram_instance():
    mcp_config = json.loads((PROJECT_ROOT / ".mcp.json").read_text())
    engram_env = mcp_config["mcpServers"]["engram"]["env"]
    assert engram_env["ENGRAM_DEFAULT_INSTANCE"] == "engram"

    hooks_config = json.loads((PROJECT_ROOT / "hooks" / "hooks.json").read_text())
    commands = [
        hook["command"]
        for registrations in hooks_config["hooks"].values()
        for registration in registrations
        for hook in registration["hooks"]
    ]
    assert commands
    assert all("ENGRAM_DEFAULT_INSTANCE=engram" in command for command in commands)


def _build_wheel(tmp_path: Path) -> Path:
    source_copy = tmp_path / "source-copy"
    wheelhouse = tmp_path / "wheelhouse"
    source_copy.mkdir()
    wheelhouse.mkdir()
    tracked = subprocess.run(
        ["git", "ls-files", "-z"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
    ).stdout.split(b"\0")
    for raw_relative in tracked:
        if not raw_relative:
            continue
        relative = Path(os.fsdecode(raw_relative))
        source = PROJECT_ROOT / relative
        if not source.is_file():
            continue
        destination = source_copy / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(source, destination)

    subprocess.run(
        ["uv", "build", "--wheel", "--out-dir", str(wheelhouse)],
        cwd=source_copy,
        check=True,
        capture_output=True,
        text=True,
    )

    wheels = list(wheelhouse.glob("*.whl"))
    assert len(wheels) == 1
    return wheels[0]


def test_wheel_contains_runtime_modules_and_assets(tmp_path):
    wheel = _build_wheel(tmp_path)

    with zipfile.ZipFile(wheel) as archive:
        names = set(archive.namelist())

    required_modules = {path.name for path in PROJECT_ROOT.glob("*.py")}
    wheel_modules = {Path(name).name for name in names}
    assert required_modules <= wheel_modules
    assert any(
        name.endswith("share/engram/migrations/026_scrub_operation_details.sql")
        for name in names
    )
    assert any(name.endswith("share/engram/prompts/classify.txt") for name in names)
    assert any(name.endswith("share/engram/hooks/hooks.json") for name in names)
    assert any(name.endswith("share/engram/skills/engram/skill.md") for name in names)


def test_wheel_build_does_not_create_artifacts_in_source_tree(
    tmp_path, monkeypatch,
):
    source = tmp_path / "source"
    source.mkdir()
    (source / "sample.py").write_text("VALUE = 1\n")
    (source / "pyproject.toml").write_text(
        "[build-system]\n"
        'requires = ["setuptools>=75"]\n'
        'build-backend = "setuptools.build_meta"\n'
        "\n"
        "[project]\n"
        'name = "test-artifact-hygiene"\n'
        'version = "0.0.0"\n'
        "\n"
        "[tool.setuptools]\n"
        'py-modules = ["sample"]\n'
    )
    subprocess.run(["git", "init", "-q"], cwd=source, check=True)
    subprocess.run(
        ["git", "add", "pyproject.toml", "sample.py"], cwd=source, check=True
    )
    monkeypatch.setattr("tests.test_packaging.PROJECT_ROOT", source)
    artifacts = tmp_path / "artifacts"
    artifacts.mkdir()

    wheel = _build_wheel(artifacts)

    assert wheel.exists()
    assert not (source / "build").exists()
    assert not list(source.glob("*.egg-info"))


def test_lockfile_matches_project_metadata():
    subprocess.run(
        ["uv", "lock", "--check"],
        cwd=PROJECT_ROOT,
        check=True,
        capture_output=True,
        text=True,
    )


def test_installed_wheel_starts_outside_checkout(tmp_path):
    wheel = _build_wheel(tmp_path)
    venv = tmp_path / "venv"
    subprocess.run(
        ["uv", "venv", str(venv), "--python", str(Path(os.sys.executable))],
        check=True,
        capture_output=True,
        text=True,
    )
    python = venv / "bin" / "python"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )

    engram_home = tmp_path / "engram-home"
    config_dir = engram_home / ".engram"
    config_dir.mkdir(parents=True)
    (config_dir / "config.toml").write_text(
        "[watcher]\n"
        "enabled = false\n"
        "\n"
        "[graph]\n"
        "enabled = false\n"
    )
    outside_checkout = tmp_path / "outside-checkout"
    outside_checkout.mkdir()
    script = """
import os
os.environ["ENGRAM_HOME"] = os.environ["TEST_ENGRAM_HOME"]
os.environ["ENGRAM_PROJECT_ROOT"] = os.environ["TEST_ENGRAM_HOME"]
os.environ["ENGRAM_HARNESS"] = "codex"
import server
server._init()
assert len(server.mcp._tool_manager.list_tools()) == 43
assert server.status()["layers"]["episodes"] == 0
print("installed-wheel-startup-ok")
"""
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    env["TEST_ENGRAM_HOME"] = str(engram_home)
    result = subprocess.run(
        [str(python), "-c", script],
        cwd=outside_checkout,
        env=env,
        check=True,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.stdout.strip() == "installed-wheel-startup-ok"


def test_installed_wheel_imports_evolving_category_runtime(tmp_path):
    """Consumers can import the v2 category runtime from the installed wheel."""
    wheel = _build_wheel(tmp_path)
    venv = tmp_path / "venv"
    subprocess.run(
        ["uv", "venv", str(venv), "--python", str(Path(os.sys.executable))],
        check=True,
        capture_output=True,
        text=True,
    )
    python = venv / "bin" / "python"
    subprocess.run(
        ["uv", "pip", "install", "--python", str(python), str(wheel)],
        check=True,
        capture_output=True,
        text=True,
    )

    outside_checkout = tmp_path / "outside-checkout"
    outside_checkout.mkdir()
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    env["PYTHONNOUSERSITE"] = "1"
    result = subprocess.run(
        [
            str(python),
            "-c",
            "import category_context, category_compile, category_evolution; "
            "print('installed-wheel-category-runtime-imports-ok')",
        ],
        cwd=outside_checkout,
        env=env,
        capture_output=True,
        text=True,
        timeout=180,
    )

    assert result.returncode == 0, result.stderr
    assert result.stdout.strip() == "installed-wheel-category-runtime-imports-ok"
