import json
import subprocess
from pathlib import Path

import pytest
from superyak_tuning.__main__ import main

EXAMPLE = Path(__file__).parents[1] / "examples" / "clinical-biotech-dataset.json"
ROOT = Path(__file__).parents[2]


def test_cli_snapshot_and_selected_model(tmp_path, capsys):
    assert main(["model"]) == 0
    assert json.loads(capsys.readouterr().out)["derivative_publisher"] == "HauhauCS"
    assert (
        main(
            [
                "snapshot",
                "--input",
                str(EXAMPLE),
                "--output",
                str(tmp_path / "snapshot"),
            ]
        )
        == 0
    )
    out = json.loads(capsys.readouterr().out)
    assert out["example_count"] == 8
    assert "messages" not in out


def test_slurm_quotes_paths_and_requires_explicit_account(tmp_path, capsys):
    output = tmp_path / "new-private-parent" / "job.sh"
    args = [
        "slurm",
        "--account",
        "allocation",
        "--python",
        "/opt/tuning env/bin/python",
        "--model-dir",
        "/scratch/a model",
        "--snapshot",
        "/scratch/data",
        "--run-dir",
        "/scratch/run",
        "--output",
        str(output),
        "--reservation",
        "res_1",
    ]
    assert main(args) == 0
    script = output.read_text()
    assert "#SBATCH --account=allocation" in script
    assert "'/opt/tuning env/bin/python'" in script
    assert "'/scratch/a model'" in script
    assert "--device xpu" in script
    assert output.stat().st_mode & 0o777 == 0o600
    assert output.parent.stat().st_mode & 0o777 == 0o700
    assert (
        subprocess.run(
            ["bash", "-n", str(output)], capture_output=True, check=False
        ).returncode
        == 0
    )
    assert main(args) == 1
    assert "already exists" in capsys.readouterr().err


def test_slurm_requires_explicit_python(tmp_path):
    with pytest.raises(SystemExit) as error:
        main(
            [
                "slurm",
                "--account",
                "allocation",
                "--model-dir",
                "/model",
                "--snapshot",
                "/snapshot",
                "--run-dir",
                "/run",
                "--output",
                str(tmp_path / "job.sh"),
            ]
        )
    assert error.value.code == 2
    assert not (tmp_path / "job.sh").exists()


@pytest.mark.parametrize(
    ("option", "value", "expected_error"),
    [
        ("--python", "tuning/.venv/bin/python", "absolute"),
        ("--model-dir", "prepared-model", "absolute"),
        ("--snapshot", "dataset-snapshot", "absolute"),
        ("--run-dir", "training-run", "absolute"),
        ("--snapshot", "/scratch/data\n#SBATCH --nodes=99", "invalid"),
    ],
)
def test_slurm_rejects_relative_or_malformed_job_paths(
    tmp_path, capsys, option, value, expected_error
):
    output = tmp_path / "job.sh"
    values = {
        "--python": "/opt/tuning/.venv/bin/python",
        "--model-dir": "/scratch/model",
        "--snapshot": "/scratch/snapshot",
        "--run-dir": "/scratch/run",
    }
    values[option] = value
    args = ["slurm", "--account", "allocation"]
    for name, path in values.items():
        args.extend([name, path])
    args.extend(["--output", str(output)])

    assert main(args) == 1
    error = capsys.readouterr().err
    assert expected_error in error
    assert not output.exists()


def test_slurm_rejects_directive_injection(tmp_path, capsys):
    args = [
        "slurm",
        "--account",
        "bad\n#SBATCH --nodes=99",
        "--python",
        "/python",
        "--model-dir",
        "/m",
        "--snapshot",
        "/s",
        "--run-dir",
        "/r",
        "--output",
        str(tmp_path / "job.sh"),
    ]
    assert main(args) == 1
    assert not (tmp_path / "job.sh").exists()


def test_root_setup_and_check_include_cpu_tuning_component():
    setup = subprocess.run(
        ["make", "-n", "setup"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout
    check = subprocess.run(
        ["make", "-n", "check"], cwd=ROOT, capture_output=True, text=True, check=True
    ).stdout

    assert 'cd tuning && uv sync --locked --extra dev --extra "train"' in setup
    assert (
        'cd tuning && uv run --locked --extra dev --extra "train" '
        "python -m pytest" in check
    )
    assert 'extra "xpu"' not in setup + check


def test_cli_errors_do_not_echo_participant_content(tmp_path, capsys):
    path = tmp_path / "data.json"
    path.write_text("{PRIVATE CLINICAL CONTENT")
    assert (
        main(["snapshot", "--input", str(path), "--output", str(tmp_path / "snapshot")])
        == 1
    )
    assert "PRIVATE CLINICAL" not in capsys.readouterr().err
