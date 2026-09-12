"""Exercise the bounded probe over the real local HTTP client and filesystem."""

import importlib
import json
import stat

import pytest

from tests.test_stampede_provider import completion, service  # noqa: F401


@pytest.fixture
def probe_module():
    try:
        return importlib.import_module("deploy.stampede.probe")
    except ModuleNotFoundError:
        pytest.fail("The two-turn model probe has not been implemented")


def answer(version, observed):
    response = completion()
    response["choices"][0]["message"].update(
        content=json.dumps({"source_id": f"probe-observation-v{version}",
                            "observed": observed, "total": 10,
                            "causal_effect_established": False,
                            "supersedes": None if version == 1 else "probe-observation-v1"}),
        reasoning_content="Synthetic protocol fixture, retained only in this run.",
        tool_calls=[],
    )
    return response


def test_probe_records_two_calls_and_passes_complete_state_to_correction(probe_module, service, tmp_path):
    from deploy.stampede.provider import LocalModel

    endpoint, responses, requests = service
    responses.extend([(200, answer(1, 6), 0), (200, answer(2, 2), 0)])
    output = tmp_path / "probe"
    result = probe_module.run_probe(LocalModel(endpoint, "test-model", protocol="kimi-k3", reasoning_effort="low"),
                                    output, revision="a" * 40, deployment="scripted HTTP fixture")
    assert result["status"] == "passed"
    assert len(requests) == 2
    assert requests[1]["body"]["messages"][2] == answer(1, 6)["choices"][0]["message"]
    assert result["server_revision_verified"] is False
    assert result["declared_revision"] == "a" * 40
    assert result["model"] == "test-model"
    assert [turn["checks_passed"] for turn in result["turns"]] == [True, True]
    assert result["turns"][0]["input_tokens"] == 12
    assert result["turns"][1]["elapsed_s"] >= 0
    assert json.loads((output / "report.json").read_text()) == result
    assert stat.S_IMODE(output.stat().st_mode) == 0o700
    assert stat.S_IMODE((output / "turn-1.json").stat().st_mode) == 0o600
    assert "reasoning_content" not in (output / "report.json").read_text()
    assert json.loads((output / "turn-1.json").read_text())["response"]["assistant_message"] == answer(1, 6)["choices"][0]["message"]
    before = {p.name: p.read_bytes() for p in output.iterdir()}
    with pytest.raises(FileExistsError):
        probe_module.run_probe(LocalModel(endpoint, "test-model"), output,
                               revision="a" * 40, deployment="fixture")
    assert len(requests) == 2
    assert before == {p.name: p.read_bytes() for p in output.iterdir()}


@pytest.mark.parametrize("second,status", [(answer(1, 6), 200), ({"error": "fixture"}, 500)])
def test_stale_answer_or_failed_second_call_cannot_pass(probe_module, service, tmp_path, second, status):
    from deploy.stampede.provider import LocalModel

    endpoint, responses, requests = service
    responses.extend([(200, answer(1, 6), 0), (status, second, 0)])
    result = probe_module.run_probe(LocalModel(endpoint, "test-model", protocol="glm-5.3"),
                                    tmp_path / "probe", revision="b" * 40, deployment="fixture")
    assert result["status"] == "failed"
    assert len(requests) == 2
    assert result["turns"][0]["checks_passed"] is True
    assert result["turns"][1]["checks_passed"] is False


def test_truncated_response_stops_without_retry_or_followup(probe_module, service, tmp_path):
    from deploy.stampede.provider import LocalModel

    endpoint, responses, requests = service
    truncated = answer(1, 6)
    truncated["choices"][0]["finish_reason"] = "length"
    responses.append((200, truncated, 0))
    result = probe_module.run_probe(LocalModel(endpoint, "test-model", protocol="kimi-k3"),
                                    tmp_path / "probe", revision="c" * 40, deployment="fixture")
    assert result["status"] == "failed"
    assert len(requests) == 1
    assert "error" in result["turns"][0]


def test_cli_returns_failure_and_does_not_overwrite_artifacts(probe_module, service, tmp_path, capsys):
    endpoint, responses, requests = service
    responses.append((500, {"error": "fixture"}, 0))
    args = ["--endpoint", endpoint, "--model", "test-model", "--protocol", "glm-5.3",
            "--revision", "d" * 40, "--deployment", "fixture", "--output", str(tmp_path / "probe")]
    assert probe_module.main(args) == 1
    assert json.loads(capsys.readouterr().out)["status"] == "failed"
    assert probe_module.main(args) == 2
    assert len(requests) == 1


@pytest.mark.parametrize("revision", ["main", "", "latest"])
def test_unpinned_revision_rejected_before_inference(probe_module, service, tmp_path, revision):
    from deploy.stampede.provider import LocalModel

    endpoint, _, requests = service
    with pytest.raises(ValueError):
        probe_module.run_probe(LocalModel(endpoint, "test-model"), tmp_path / "probe",
                               revision=revision, deployment="fixture")
    assert not (tmp_path / "probe").exists()
    assert requests == []


def test_malformed_prefix_is_reported_without_repairing_model_output(probe_module, service, tmp_path):
    from deploy.stampede.provider import LocalModel

    endpoint, responses, _ = service
    malformed = answer(1, 6)
    malformed["choices"][0]["message"]["content"] = 'source' + malformed["choices"][0]["message"]["content"]
    responses.extend([(200, malformed, 0), (200, answer(1, 6), 0)])
    output = tmp_path / "probe"
    result = probe_module.run_probe(LocalModel(endpoint, "test-model"), output,
                                    revision="e" * 40, deployment="fixture")
    assert result["status"] == "failed"
    assert result["turns"][0]["check_failure"] == "invalid_json"
    assert result["turns"][1]["check_failure"] == "unexpected_answer"
    assert json.loads((output / "turn-1.json").read_text())["response"]["text"].startswith('source{')
