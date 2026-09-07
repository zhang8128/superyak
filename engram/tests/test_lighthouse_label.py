"""Labels are explicit caller judgments, never inferred from delivery."""

import json
import subprocess
import sys

import pytest

from lighthouse_receipts import build_receipt


@pytest.fixture
def receipt():
    return build_receipt(
        receiver="receiver", turn_id="turn-1",
        context={"id": "memory/technical", "path": ["memory", "technical"]},
        purpose="session-recall", sources=[], selected=[], delivered=[],
        receiver_rule=None,
    )


def test_labels_preserve_explicit_judgments_including_absent_memories(receipt):
    from lighthouse_label import build_labels

    labels = build_labels(
        receipt, relevant=[("urn:engram:why", "not-delivered")],
        forbidden=[("urn:engram:other", "never-requested")],
    )
    assert labels == {
        "formatVersion": "1.0", "instance": "urn:engram:receiver",
        "turns": [{
            "turnId": "turn-1",
            "context": {"id": "memory/technical", "path": ["memory", "technical"]},
            "purpose": "session-recall",
            "relevant": [{"publisher": "urn:engram:why", "memoryId": "not-delivered"}],
            "forbidden": [{"publisher": "urn:engram:other", "memoryId": "never-requested"}],
        }],
    }


@pytest.mark.parametrize(
    ("relevant", "forbidden"),
    [([], []),
     ([("urn:engram:a", "m"), ("urn:engram:a", "m")], []),
     ([("urn:engram:a", "m")], [("urn:engram:a", "m")]),
     ([("urn:engram:a", "m")], [("urn:engram:b", "x"), ("urn:engram:b", "x")]),
     ([("not-a-urn", "m")], []),
     ([("urn:engram:a", "")], [])],
)
def test_empty_ambiguous_or_invalid_judgments_are_rejected(receipt, relevant, forbidden):
    from lighthouse_label import build_labels

    with pytest.raises(ValueError):
        build_labels(receipt, relevant=relevant, forbidden=forbidden)


def test_tampered_receipt_cannot_be_labeled(receipt):
    from lighthouse_label import build_labels

    receipt["payload"]["turnId"] = "tampered-turn"
    with pytest.raises(ValueError, match="DIGEST_MISMATCH"):
        build_labels(receipt, relevant=[("urn:engram:a", "m")])


def test_label_cli_requires_relevance_and_refuses_output_overwrite(receipt, tmp_path):
    receipt_path = tmp_path / "receipt.json"
    receipt_path.write_text(json.dumps(receipt))
    output = tmp_path / "labels.json"
    command = [sys.executable, "-m", "lighthouse_label", str(receipt_path),
               "--output", str(output)]
    missing = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert missing.returncode != 0
    assert not output.exists()
    command += ["--relevant", "urn:engram:a", "explicit-memory"]
    completed = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert completed.returncode == 0, completed.stderr
    labels = json.loads(output.read_text())
    assert labels["turns"][0]["relevant"] == [
        {"publisher": "urn:engram:a", "memoryId": "explicit-memory"}
    ]
    before = output.read_bytes()
    repeated = subprocess.run(command, capture_output=True, text=True, timeout=10)
    assert repeated.returncode != 0
    assert output.read_bytes() == before
