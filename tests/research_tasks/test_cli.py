"""Exercise portable-task commands, local HTTP calls, and build entry points."""

import importlib
import json
import os
from pathlib import Path
import socket
import subprocess
import sys
import tarfile

import pytest

from test_providers import completion, service  # noqa: F401
from test_tasks import source  # noqa: F401


ROOT = Path(__file__).resolve().parents[2]


def cli():
    try:
        return importlib.import_module("research_tasks.__main__")
    except ModuleNotFoundError as error:
        pytest.fail(f"Portable task CLI is missing: {error}")


def forbid_connections(monkeypatch):
    def unexpected(*args, **kwargs):
        pytest.fail("An offline command tried to connect to a service")
    monkeypatch.setattr(socket.socket, "connect", unexpected)


def exported(source, tmp_path):
    from research_tasks.packet import export_task
    packet = tmp_path / "task.json"
    export_task(source[0], "q-mg", "a" * 64, packet)
    return packet


def run_args(packet, output, endpoint):
    return ["run", "--packet", str(packet), "--output", str(output),
            "--backend", "completions", "--model", "fixture-model", "--model-revision", "sha256:" + "1" * 64,
            "--endpoint", endpoint, "--protocol", "glm-5.3", "--timeout", "2.25",
            "--output-tokens", "701", "--seed", "13", "--reasoning-effort", "low"]


def extraction():
    return {"relevant": True, "title": "Fictional fatigue observation",
            "summary": "The fictional study measured reported fatigue.", "scope": "Fictional fixture only.",
            "limitations": "Only an abstract was supplied; no treatment effect was established.",
            "passage_id": "p1", "quote": "study measured reported fatigue in ten participants",
            "rationale": "This describes the measured endpoint."}


def test_default_command_shows_help_without_constructing_or_calling_a_model(monkeypatch, capsys):
    forbid_connections(monkeypatch)
    assert cli().main([]) == 0
    help_text = capsys.readouterr().out
    assert "export" in help_text and "run" in help_text
    with pytest.raises(SystemExit) as caught:
        cli().main(["run", "--help"])
    assert caught.value.code == 0
    assert "--model-revision" in capsys.readouterr().out


def test_export_writes_only_selected_packet_without_network(source, tmp_path, monkeypatch, capsys):
    from research_tasks.packet import load_task

    forbid_connections(monkeypatch)
    output = tmp_path / "selected.json"
    assert cli().main(["export", "--project", str(source[0]), "--question-id", "q-mg",
                       "--job-id", "a" * 64, "--output", str(output)]) == 0
    packet = load_task(output)
    summary = json.loads(capsys.readouterr().out)
    assert summary["task_id"] == packet["task_id"]
    assert Path(summary["packet"]) == output
    assert "DO NOT EXPORT" not in output.read_text()


def test_run_forwards_every_model_option_and_completed_replay_is_offline(source, tmp_path, service, capsys, monkeypatch):
    endpoint, responses, requests = service
    review = {"verdict": "supported", "reason": "The passage states the measured endpoint.",
              "evidence": [{"passage_id": "p1"}]}
    responses.extend([completion(extraction(), reasoning_content="First fixture analysis."),
                      completion(review, reasoning_content="Fresh fixture review.")])
    packet = exported(source, tmp_path)
    output = tmp_path / "run"
    args = run_args(packet, output, endpoint)
    assert cli().main(args) == 0
    summary = json.loads(capsys.readouterr().out)
    assert summary["status"] == "recorded"
    assert summary["model_revision_verified"] is False
    assert summary["model_revision"] == "sha256:" + "1" * 64
    manifest = json.loads((output / "manifest.json").read_text())["payload"]
    assert manifest["config"] == {
        "backend": "completions", "model": "fixture-model", "model_revision": "sha256:" + "1" * 64,
        "endpoint": endpoint, "protocol": "glm-5.3", "timeout": 2.25,
        "output_tokens": 701, "seed": 13, "reasoning_effort": "low"}
    assert len(requests) == 2
    assert all(request["body"]["max_tokens"] == 701 for request in requests)
    assert all(request["body"]["reasoning_effort"] == "low" for request in requests)
    assert all(request["body"]["seed"] == 13 for request in requests)
    before = {p.relative_to(output): p.read_bytes() for p in output.rglob("*") if p.is_file()}
    forbid_connections(monkeypatch)
    assert cli().main(args) == 0
    assert json.loads(capsys.readouterr().out) == summary
    assert all((output / path).read_bytes() == content for path, content in before.items())


def test_malformed_completed_reply_returns_failure_and_preserves_artifact(source, tmp_path, service, capsys):
    endpoint, responses, requests = service
    answer = completion(extraction(), reasoning_content="Malformed output fixture.")
    answer["choices"][0]["message"]["content"] = "prefix " + answer["choices"][0]["message"]["content"]
    responses.append(answer)
    output = tmp_path / "run"
    assert cli().main(run_args(exported(source, tmp_path), output, endpoint)) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    raw = json.loads((output / "calls/extract.response.json").read_text())["payload"]["raw_response"]
    assert raw["response"]["raw_response"] == answer
    assert len(requests) == 1


@pytest.mark.parametrize("flag", ["--packet", "--output", "--backend", "--model", "--model-revision", "--endpoint"])
def test_run_requires_explicit_task_destination_and_model_identity(tmp_path, monkeypatch, flag):
    forbid_connections(monkeypatch)
    args = run_args(tmp_path / "task.json", tmp_path / "run", "http://127.0.0.1:9")
    index = args.index(flag)
    del args[index:index + 2]
    with pytest.raises(SystemExit) as caught:
        cli().main(args)
    assert caught.value.code == 2
    assert not (tmp_path / "run").exists()


def test_ollama_nonzero_seed_is_rejected_before_execution(tmp_path, monkeypatch, capsys):
    forbid_connections(monkeypatch)
    args = ["run", "--packet", str(tmp_path / "missing.json"), "--output", str(tmp_path / "run"),
            "--backend", "ollama", "--model", "fixture-model", "--model-revision", "fixture-revision",
            "--endpoint", "http://127.0.0.1:9", "--seed", "7"]
    assert cli().main(args) == 2
    assert "seed" in capsys.readouterr().err.lower()
    assert not (tmp_path / "run").exists()


def test_blank_declared_revision_is_rejected_without_network(tmp_path, monkeypatch):
    forbid_connections(monkeypatch)
    args = run_args(tmp_path / "task.json", tmp_path / "run", "http://127.0.0.1:9")
    args[args.index("--model-revision") + 1] = "   "
    with pytest.raises(SystemExit) as caught:
        cli().main(args)
    assert caught.value.code == 2


def test_make_research_task_defaults_to_help(tmp_path):
    completed = subprocess.run(["make", "research-task", f"RESEARCH_TASK_PYTHON={sys.executable}"],
                               cwd=ROOT, text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert "export" in completed.stdout and "run" in completed.stdout


def test_make_checks_portable_tests_in_a_separate_root_process(tmp_path):
    capture = tmp_path / "invocation.json"
    python = tmp_path / "python with spaces"
    python.write_text(f"#!{sys.executable}\nimport json, os, sys\n"
                      f"open({str(capture)!r}, 'w').write(json.dumps({{'cwd':os.getcwd(),'argv':sys.argv[1:]}}))\n")
    python.chmod(0o755)
    completed = subprocess.run(["make", "check-research-tasks", f"RESEARCH_TASK_PYTHON={python}"],
                               cwd=ROOT, text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    invocation = json.loads(capture.read_text())
    assert Path(invocation["cwd"]) == ROOT
    assert invocation["argv"][:3] == ["-m", "pytest", "tests/research_tasks"]
    assert "tests/test_research_poc.py" not in invocation["argv"]


def test_prepared_source_archive_runs_portable_cli_without_editable_install(tmp_path):
    from deploy.stampede.launcher import prepare_bundle

    archive_path = prepare_bundle(ROOT, tmp_path / "source.tar.gz")
    unpacked = tmp_path / "unpacked"
    with tarfile.open(archive_path, "r:gz") as archive:
        assert archive.extractfile("research_tasks/__main__.py").read() == (ROOT / "research_tasks/__main__.py").read_bytes()
        archive.extractall(unpacked, filter="data")
    env = os.environ.copy()
    env.pop("PYTHONPATH", None)
    completed = subprocess.run([sys.executable, "-S", "-m", "research_tasks", "--help"],
                               cwd=unpacked, env=env, text=True, capture_output=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    assert "export" in completed.stdout and "run" in completed.stdout
