"""Installed-wheel integration tests for Engram's runtime boundary."""

from __future__ import annotations

import os
import shutil
import subprocess
import zipfile
from pathlib import Path


PROJECT_ROOT = Path(__file__).resolve().parents[1]


def _build_wheel(tmp_path: Path) -> Path:
    wheelhouse = tmp_path / "wheelhouse"
    wheelhouse.mkdir()
    checkout_build = PROJECT_ROOT / "build"
    build_was_present = checkout_build.exists()
    try:
        subprocess.run(
            ["uv", "build", "--wheel", "--out-dir", str(wheelhouse)],
            cwd=PROJECT_ROOT,
            check=True,
            capture_output=True,
            text=True,
        )
    finally:
        if checkout_build.exists() and not build_was_present:
            shutil.move(str(checkout_build), tmp_path / "setuptools-build")

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
assert len(server.mcp._tool_manager.list_tools()) == 40
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
