from __future__ import annotations

import json
import os
import re
from pathlib import Path

import pytest

from lighthouse_protocol import content_digest
from lighthouse_receipts import (
    ReceiptError,
    build_receipt,
    validate_receipt,
    write_receipt,
)
from storage import Storage

CONTEXT = {"id": "memory/technical", "path": ["memory", "technical"]}
ALLOW = {"effect": "allow", "ruleId": "r1", "code": None}


def sample(delivered=True) -> dict:
    return build_receipt(
        receiver="engram",
        turn_id="turn-1",
        context=CONTEXT,
        purpose="session-recall",
        sources=[
            {
                "publisher": "urn:engram:why",
                "role": "remote",
                "weight": 1.0,
                "storeDigest": content_digest("store"),
                "policyDecision": ALLOW,
                "traceOutcome": "matched",
            }
        ],
        selected=[
            {
                "publisher": "urn:engram:why",
                "memoryId": "m1",
                "contentDigest": content_digest("x"),
                "score": 1 / 61,
                "contributions": [
                    {"publisher": "urn:engram:why", "rank": 1}
                ],
            }
        ],
        delivered=[
            {
                "publisher": "urn:engram:why",
                "memoryId": "m1",
                "readDecision": ALLOW,
            }
        ]
        if delivered
        else [],
        receiver_rule="allow-why",
        issued_at="2026-09-01T00:00:00+00:00",
    )


def test_build_receipt_is_sealed_and_valid():
    receipt = sample()
    assert receipt["kind"] == "RecallReceipt"
    assert receipt["issuer"] == "urn:engram:engram"
    assert receipt["payload"]["injected"] is True
    validate_receipt(receipt)


def test_injected_false_when_nothing_delivered():
    receipt = sample(delivered=False)
    assert receipt["payload"]["injected"] is False
    validate_receipt(receipt)


def test_validate_rejects_unknown_member_and_digest_mismatch():
    receipt = sample()
    receipt["payload"]["extra"] = 1
    with pytest.raises(ReceiptError) as err:
        validate_receipt(receipt)
    assert err.value.code == "SCHEMA_INVALID"

    receipt = sample()
    receipt["digest"]["value"] = "0" * 64
    with pytest.raises(ReceiptError) as err:
        validate_receipt(receipt)
    assert err.value.code == "DIGEST_MISMATCH"


def test_validate_rejects_injected_mismatch():
    receipt = sample()
    receipt["payload"]["injected"] = False
    with pytest.raises(ReceiptError) as err:
        validate_receipt(receipt)
    assert err.value.code == "INJECTED_MISMATCH"


def test_write_receipt_logs_without_content(tmp_path):
    store = Storage(str(tmp_path / "graph.db"))
    receipt = sample()
    receipt_id = write_receipt(
        store, receipt, session_id="s1", recall_id="rc1"
    )
    row = store.conn.execute(
        "SELECT layer, target_ids, context FROM memory_log "
        "WHERE event_type='lighthouse_receipt'"
    ).fetchone()
    assert row["layer"] == "all"
    assert json.loads(row["target_ids"]) == ["urn:engram:why:m1"]
    context = json.loads(row["context"])
    assert context["recall_id"] == "rc1"
    assert context["receipt"]["id"] == receipt_id
    assert all(
        "content" not in item
        for item in context["receipt"]["payload"]["selected"]
    )
    store.close()


def test_decisions_serialize_with_explicit_nulls_and_store_digest_shape():
    from lighthouse_policy import Decision
    from lighthouse_protocol import canonical_json

    assert '"code":null' in canonical_json(
        Decision("allow", "r1", None).to_json()
    )
    assert '"ruleId":null' in canonical_json(
        Decision("deny", None, "NO_MATCHING_ALLOW").to_json()
    )
    assert (
        Decision("deny", "d1", "EXPLICIT_DENY").to_json()["ruleId"]
        == "d1"
    )
    receipt = sample()
    for source in receipt["payload"]["sources"]:
        assert set(source["policyDecision"]) == {"effect", "ruleId", "code"}
        assert source["storeDigest"]["algorithm"] == "sha256"
        assert re.fullmatch(r"[0-9a-f]{64}", source["storeDigest"]["value"])
    for item in receipt["payload"]["delivered"]:
        assert set(item["readDecision"]) == {"effect", "ruleId", "code"}
    assert '"code":null' in canonical_json(receipt)


def test_vendored_schema_matches_lighthouse_when_present():
    kit = Path(os.environ.get(
        "LIGHTHOUSE_REPO", Path(__file__).resolve().parents[2] / "lighthouse"
    )) / "schemas/recall-receipt.schema.json"
    if not kit.exists():
        pytest.skip("lighthouse checkout or schema not present")
    ours = json.loads(
        Path("schemas/lighthouse/recall-receipt.schema.json").read_text()
    )
    assert ours == json.loads(kit.read_text())
