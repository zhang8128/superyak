import json
import threading
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer

import pytest
from superyak_tuning.evaluation import evaluate_cases
from superyak_tuning.models import selected_model


@pytest.fixture
def endpoint():
    state = {
        "answer": "1.2 mg/dL [lab-A]",
        "requests": [],
        "sha": selected_model()["sha256"],
    }

    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass

        def do_GET(self):
            data = {"models": [{"name": "clinical:test", "digest": "a" * 64}]}
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(data).encode())

        def do_POST(self):
            data = json.loads(self.rfile.read(int(self.headers["Content-Length"])))
            state["requests"].append((self.path, data))
            if self.path == "/api/chat" and "chat_status" in state:
                self.send_response(state["chat_status"])
                self.end_headers()
                self.wfile.write(b'{"error":"temporary local failure"}')
                return
            reply = (
                {"modelfile": "FROM /models/sha256-" + state["sha"]}
                if self.path == "/api/show"
                else {"message": {"content": state["answer"]}, "done": True}
            )
            if self.path == "/api/chat" and "chat_reply" in state:
                reply = state["chat_reply"]
            self.send_response(200)
            self.end_headers()
            self.wfile.write(json.dumps(reply).encode())

    server = ThreadingHTTPServer(("127.0.0.1", 0), Handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    yield f"http://127.0.0.1:{server.server_port}", state
    server.shutdown()
    server.server_close()
    thread.join()


def cases():
    return [
        {
            "id": "clinical-extraction",
            "domain": "clinical",
            "messages": [
                {
                    "role": "user",
                    "content": "[lab-A] Fictional patient Ada. Creatinine 1.2 mg/dL. Extract value and unit.",
                }
            ],
            "checks": {"required_terms": ["1.2", "mg/dL", "[lab-A]"]},
        }
    ]


def biotech_cases():
    return [
        {
            "id": "biotech-assay-control",
            "domain": "biotech",
            "messages": [
                {
                    "role": "user",
                    "content": "[control-B] Fictional assay negative control amplified. State the QC consequence.",
                }
            ],
            "checks": {
                "required_terms": ["[control-B]", "repeat", "invalid"],
                "forbidden_terms": ["publish"],
            },
        }
    ]


def test_clinical_answer_is_evaluated_without_domain_refusal(endpoint, tmp_path):
    url, state = endpoint
    result = evaluate_cases(cases(), url, "clinical:test", tmp_path / "eval")
    assert result["mechanical_passes"] == 1
    assert result["clinical_validation"] == "not_established"
    assert result["model_identity"]["source"]["sha256"] == selected_model()["sha256"]
    assert any(path == "/api/chat" for path, _ in state["requests"])


def test_biotech_answer_retains_evidence_id_and_passes_explicit_checks(
    endpoint, tmp_path
):
    url, state = endpoint
    state["answer"] = (
        "The result is invalid; repeat the assay because [control-B] amplified."
    )

    result = evaluate_cases(
        biotech_cases(), url, "clinical:test", tmp_path / "biotech-eval"
    )

    assert result["mechanical_passes"] == 1
    assert result["results"][0]["case_id"] == "biotech-assay-control"
    assert result["results"][0]["domain"] == "biotech"
    assert result["results"][0]["missing_terms"] == []


def test_generic_refusal_and_empty_answer_are_not_passes(endpoint, tmp_path):
    url, state = endpoint
    state["answer"] = "I cannot assist with medical questions."
    result = evaluate_cases(cases(), url, "clinical:test", tmp_path / "refusal")
    assert result["mechanical_passes"] == 0
    assert result["refusal_flags"] == 1
    state["answer"] = ""
    result = evaluate_cases(cases(), url, "clinical:test", tmp_path / "empty")
    assert result["mechanical_passes"] == 0


def test_wrong_model_is_rejected_before_clinical_prompt(endpoint, tmp_path):
    url, state = endpoint
    state["sha"] = "b" * 64
    with pytest.raises(ValueError, match="selected"):
        evaluate_cases(cases(), url, "clinical:test", tmp_path / "eval")
    assert not any(path == "/api/chat" for path, _ in state["requests"])


def test_nonlocal_endpoint_and_duplicate_cases_rejected(endpoint, tmp_path):
    with pytest.raises(ValueError, match="loopback"):
        evaluate_cases(
            cases(), "https://example.com", "clinical:test", tmp_path / "remote"
        )
    url, state = endpoint
    with pytest.raises(ValueError, match="duplicate"):
        evaluate_cases(cases() * 2, url, "clinical:test", tmp_path / "duplicate")
    assert state["requests"] == []


@pytest.mark.parametrize(
    "reply",
    [
        [],
        {"done": False, "message": {"content": "1.2 mg/dL [lab-A]"}},
        {"done": True, "message": None},
    ],
)
def test_malformed_or_incomplete_response_is_a_failed_case(endpoint, tmp_path, reply):
    url, state = endpoint
    state["chat_reply"] = reply
    result = evaluate_cases(cases(), url, "clinical:test", tmp_path / "eval")
    assert result["mechanical_passes"] == 0
    assert result["results"][0]["error"] == "model_request_failed"


def test_non_successful_model_request_is_saved_as_a_failed_case(endpoint, tmp_path):
    url, state = endpoint
    state["chat_status"] = 503

    result = evaluate_cases(cases(), url, "clinical:test", tmp_path / "failed")

    assert result["mechanical_passes"] == 0
    assert result["results"] == [
        {
            "case_id": "clinical-extraction",
            "domain": "clinical",
            "mechanical_pass": False,
            "error": "model_request_failed",
            "human_review": "pending",
        }
    ]
    saved = json.loads((tmp_path / "failed" / "results.json").read_text())
    assert saved["results"] == result["results"]
