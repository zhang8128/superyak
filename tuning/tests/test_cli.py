import json
import subprocess
from pathlib import Path

from superyak_tuning.__main__ import main

EXAMPLE = Path(__file__).parents[1] / "examples" / "clinical-biotech-dataset.json"


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
    output = tmp_path / "job.sh"
    args = [
        "slurm",
        "--account",
        "allocation",
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
    assert "'/scratch/a model'" in script
    assert "--device xpu" in script
    assert (
        subprocess.run(
            ["bash", "-n", str(output)], capture_output=True, check=False
        ).returncode
        == 0
    )
    assert main(args) == 1
    assert "already exists" in capsys.readouterr().err


def test_slurm_rejects_directive_injection(tmp_path, capsys):
    args = [
        "slurm",
        "--account",
        "bad\n#SBATCH --nodes=99",
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


def test_cli_errors_do_not_echo_participant_content(tmp_path, capsys):
    path = tmp_path / "data.json"
    path.write_text("{PRIVATE CLINICAL CONTENT")
    assert (
        main(["snapshot", "--input", str(path), "--output", str(tmp_path / "snapshot")])
        == 1
    )
    assert "PRIVATE CLINICAL" not in capsys.readouterr().err
