"""Build, validate, and persist Lighthouse recall receipts.

A receipt is a sealed Lighthouse artifact. ``injected`` is true exactly
when something was delivered. Receipts never carry query text or memory
content, and the schema rejects unknown members.
"""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone

import jsonschema

from lighthouse_protocol import artifact_digest, verify_artifact_digest
from resources import resource_path

MEDIA_TYPE = "application/vnd.lighthouse.recall-receipt+json"
_SCHEMA_PATH = resource_path("schemas/lighthouse/recall-receipt.schema.json")
_VALIDATOR = jsonschema.Draft202012Validator(
    json.loads(_SCHEMA_PATH.read_text(encoding="utf-8"))
)


class ReceiptError(ValueError):
    def __init__(self, code: str):
        super().__init__(code)
        self.code = code


def build_receipt(
    *,
    receiver: str,
    turn_id: str,
    context: dict,
    purpose: str,
    sources: list[dict],
    selected: list[dict],
    delivered: list[dict],
    receiver_rule: str | None,
    issued_at: str | None = None,
) -> dict:
    receipt = {
        "protocolVersion": "0.1",
        "kind": "RecallReceipt",
        "id": f"urn:engram:{receiver}:receipt:{uuid.uuid4()}",
        "issuedAt": issued_at or datetime.now(timezone.utc).isoformat(),
        "issuer": f"urn:engram:{receiver}",
        "payloadMediaType": MEDIA_TYPE,
        "payload": {
            "turnId": turn_id,
            "context": {
                "id": context["id"],
                "path": list(context["path"]),
            },
            "purpose": purpose,
            "audience": "self",
            "action": "recall",
            "injected": len(delivered) > 0,
            "transformation": "weighted-rrf-v1",
            "receiverRule": {"ruleId": receiver_rule},
            "sources": sources,
            "selected": selected,
            "delivered": delivered,
        },
    }
    receipt["digest"] = artifact_digest(receipt)
    validate_receipt(receipt)
    return receipt


def validate_receipt(receipt: dict) -> None:
    payload = receipt.get("payload") if isinstance(receipt, dict) else None
    if isinstance(payload, dict):
        injected = payload.get("injected")
        delivered = payload.get("delivered")
        if (
            isinstance(injected, bool)
            and isinstance(delivered, list)
            and injected != (len(delivered) > 0)
        ):
            raise ReceiptError("INJECTED_MISMATCH")
    if list(_VALIDATOR.iter_errors(receipt)):
        raise ReceiptError("SCHEMA_INVALID")
    if not verify_artifact_digest(receipt):
        raise ReceiptError("DIGEST_MISMATCH")


def write_receipt(
    storage,
    receipt: dict,
    *,
    session_id: str | None,
    recall_id: str,
) -> str:
    validate_receipt(receipt)
    targets = [
        f"{item['publisher']}:{item['memoryId']}"
        for item in receipt["payload"]["delivered"]
    ]
    storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="lighthouse_receipt",
        layer="all",
        target_ids=targets,
        context={
            "recall_id": recall_id,
            "session_id": session_id,
            "receipt": receipt,
        },
    )
    return receipt["id"]
