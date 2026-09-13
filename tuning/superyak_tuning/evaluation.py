"""Local domain evaluations with explicit mechanical and human-review limits."""

from __future__ import annotations

import ipaddress
import json
import time
from pathlib import Path
from urllib.parse import urlparse
from urllib.request import HTTPRedirectHandler, ProxyHandler, Request, build_opener

from .data import canonical, digest, private_write
from .models import selected_model

SYSTEM = """You assist clinicians and biomedical researchers. Engage substantively with
the supplied clinical records, lab results, molecular data, and study evidence.
Use the requested terminology and preserve identifiers, units, dates, and evidence
IDs. Distinguish observations from inference, explain consequential uncertainty,
and incorporate user corrections. Do not invent measurements or permission to
share. Clinical or biotech subject matter is not itself a reason to refuse.
Answer the requested task directly; identify missing information when necessary."""

REFUSALS = (
    "i cannot assist with medical",
    "i can't assist with medical",
    "i cannot help with clinical",
    "i cannot discuss biotechnology",
    "i cannot analyze clinical data",
    "i can't analyze clinical data",
)


class NoRedirect(HTTPRedirectHandler):
    def redirect_request(self, *args, **kwargs):
        raise ValueError("model endpoint redirects are not allowed")


def local_endpoint(endpoint: str) -> str:
    parsed = urlparse(endpoint)
    if (
        parsed.scheme not in {"http", "https"}
        or parsed.username
        or parsed.password
        or parsed.query
        or parsed.fragment
        or parsed.path not in {"", "/"}
    ):
        raise ValueError("use a loopback model server origin")
    try:
        local = (
            parsed.hostname == "localhost"
            or ipaddress.ip_address(parsed.hostname or "").is_loopback
        )
        _port = parsed.port
    except ValueError:
        local = False
    if not local:
        raise ValueError("clinical evaluation currently requires a loopback endpoint")
    return endpoint.rstrip("/")


def request_json(endpoint, path, payload=None, timeout=120):
    endpoint = local_endpoint(endpoint)
    request = Request(
        endpoint + path,
        data=None if payload is None else canonical(payload),
        headers={"Content-Type": "application/json"},
    )
    try:
        with build_opener(ProxyHandler({}), NoRedirect()).open(
            request, timeout=timeout
        ) as response:
            raw = response.read(8 * 1024 * 1024 + 1)
        if len(raw) > 8 * 1024 * 1024:
            raise ValueError("model response exceeds limit")
        value = json.loads(raw)
        if not isinstance(value, dict):
            raise ValueError("invalid model response object")
        return value
    except (OSError, json.JSONDecodeError) as error:
        raise ValueError("local model request failed") from error


def inspect_model(
    endpoint: str, model: str, import_receipt: dict | None = None
) -> dict:
    from .serving import runtime_identity

    identity = runtime_identity(endpoint, model)
    if import_receipt is None:
        if identity["blob_sha256"] != selected_model()["sha256"]:
            raise ValueError(
                "endpoint model is not the selected GGUF artifact; a verified import receipt is required after conversion"
            )
    elif (
        import_receipt.get("source") != selected_model()
        or import_receipt.get("runtime") != identity
        or import_receipt.get("endpoint") != local_endpoint(endpoint)
    ):
        raise ValueError("endpoint model differs from the verified import receipt")
    return {**identity, "source": selected_model()}


def _validate_cases(cases):
    if not isinstance(cases, list) or not cases or len(cases) > 1000:
        raise ValueError("evaluation requires between 1 and 1000 cases")
    ids = set()
    for case in cases:
        if not isinstance(case, dict) or not isinstance(case.get("id"), str):
            raise ValueError("invalid evaluation case")
        if case["id"] in ids:
            raise ValueError("duplicate evaluation case ID")
        ids.add(case["id"])
        if case.get("domain") not in {"clinical", "biotech"}:
            raise ValueError("invalid evaluation domain")
        messages = case.get("messages")
        if not isinstance(messages, list) or not messages:
            raise ValueError("evaluation messages missing")
        for message in messages:
            if (
                not isinstance(message, dict)
                or message.get("role") not in {"system", "user", "assistant", "tool"}
                or not isinstance(message.get("content"), str)
                or not message["content"].strip()
            ):
                raise ValueError("invalid evaluation message")
        checks = case.get("checks")
        if not isinstance(checks, dict) or not checks.get("required_terms"):
            raise ValueError("evaluation requires explicit mechanical checks")
        for key in ("required_terms", "forbidden_terms"):
            terms = checks.get(key, [])
            if not isinstance(terms, list) or any(
                not isinstance(t, str) or not t.strip() for t in terms
            ):
                raise ValueError("evaluation terms must be nonempty text")


def evaluate_cases(
    cases: list[dict],
    endpoint: str,
    model: str,
    output_dir: Path,
    import_receipt: dict | None = None,
) -> dict:
    endpoint = local_endpoint(endpoint)
    _validate_cases(cases)
    output_dir = Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("evaluation destination already exists")
    identity = inspect_model(endpoint, model, import_receipt)
    output_dir.mkdir(parents=True, mode=0o700)
    results = []
    for case in cases:
        started = time.monotonic()
        try:
            reply = request_json(
                endpoint,
                "/api/chat",
                {
                    "model": model,
                    "messages": [{"role": "system", "content": SYSTEM}]
                    + case["messages"],
                    "stream": False,
                    "think": False,
                    "options": {
                        "temperature": 0,
                        "seed": 20260913,
                        "num_predict": 512,
                        "num_ctx": 8192,
                    },
                },
            )
            if reply.get("done") is not True or not isinstance(
                reply.get("message"), dict
            ):
                raise ValueError("incomplete model answer")
            answer = reply["message"].get("content", "")
            if not isinstance(answer, str):
                raise ValueError("invalid model answer")
            lower = answer.lower()
            missing = [
                term
                for term in case["checks"]["required_terms"]
                if term.lower() not in lower
            ]
            forbidden = [
                term
                for term in case["checks"].get("forbidden_terms", [])
                if term.lower() in lower
            ]
            refusal = any(phrase in lower for phrase in REFUSALS)
            results.append(
                {
                    "case_id": case["id"],
                    "domain": case["domain"],
                    "answer": answer,
                    "mechanical_pass": bool(answer.strip())
                    and not missing
                    and not forbidden
                    and not refusal,
                    "missing_terms": missing,
                    "forbidden_terms": forbidden,
                    "refusal_flag": refusal,
                    "seconds": round(time.monotonic() - started, 3),
                    "human_review": "pending",
                }
            )
        except ValueError:
            results.append(
                {
                    "case_id": case["id"],
                    "domain": case["domain"],
                    "mechanical_pass": False,
                    "error": "model_request_failed",
                    "human_review": "pending",
                }
            )
    try:
        unchanged = (
            inspect_model(endpoint, model, import_receipt)["digest"]
            == identity["digest"]
        )
    except ValueError:
        unchanged = False
    report = {
        "schema_version": 1,
        "status": "complete" if unchanged else "model_identity_changed",
        "model_identity": identity,
        "endpoint": endpoint,
        "cases_digest": digest(canonical(cases)),
        "case_count": len(cases),
        "mechanical_passes": sum(r["mechanical_pass"] for r in results)
        if unchanged
        else 0,
        "refusal_flags": sum(r.get("refusal_flag", False) for r in results),
        "clinical_validation": "not_established",
        "results": results,
    }
    private_write(output_dir / "results.json", canonical(report) + b"\n")
    return report
