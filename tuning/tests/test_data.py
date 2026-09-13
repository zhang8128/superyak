import copy
import json
from pathlib import Path

import pytest

from superyak_tuning.data import snapshot_dataset, read_snapshot


def dataset():
    return {"schema_version": 1, "sources": [{"id": "clinical", "domain": "clinical",
        "sensitivity": "identifiable", "rights": "Owner authorized local use",
        "permissions": {"inference": True, "local_training": True}}], "examples": [
        {"id": "encounter-1", "group_id": "fictional-person-1", "source_ids": ["clinical"],
         "split": "train", "messages": [{"role": "user", "content": "Fictional patient Ada, sample A: creatinine 1.2 mg/dL. Extract the value and unit."},
         {"role": "assistant", "content": "1.2 mg/dL, sample A."}]}]}


def write(tmp_path, value):
    p = tmp_path / "input.json"
    p.write_text(json.dumps(value))
    return p


def test_identifiable_clinical_data_is_supported_locally(tmp_path):
    source = write(tmp_path, dataset())
    result = snapshot_dataset(source, tmp_path / "snapshot", "local_training")
    manifest, records = read_snapshot(tmp_path / "snapshot", "local_training")
    assert records[0]["messages"][0]["content"] == dataset()["examples"][0]["messages"][0]["content"]
    assert result["digest"] == manifest["digest"]
    assert manifest["sources"][0]["sensitivity"] == "identifiable"
    assert (tmp_path / "snapshot").stat().st_mode & 0o077 == 0


@pytest.mark.parametrize("purpose", ["shared_training", "publish_adapter"])
def test_local_permission_does_not_imply_shared_permission(tmp_path, purpose):
    source = write(tmp_path, dataset())
    with pytest.raises(ValueError, match="permission"):
        snapshot_dataset(source, tmp_path / "snapshot", purpose)
    assert not (tmp_path / "snapshot").exists()


def test_missing_or_string_permission_is_not_consent(tmp_path):
    value = dataset(); value["sources"][0]["permissions"] = {"local_training": "false"}
    with pytest.raises(ValueError, match="boolean"):
        snapshot_dataset(write(tmp_path, value), tmp_path / "snapshot", "local_training")


def test_split_family_leakage_rejected(tmp_path):
    value = dataset(); second = copy.deepcopy(value["examples"][0])
    second.update(id="encounter-2", split="test")
    second["messages"][0]["content"] = "A different question about the same patient."
    value["examples"].append(second)
    with pytest.raises(ValueError, match="group"):
        snapshot_dataset(write(tmp_path, value), tmp_path / "snapshot", "local_training")


def test_duplicate_content_across_groups_rejected(tmp_path):
    value = dataset(); second = copy.deepcopy(value["examples"][0])
    second.update(id="another", group_id="another-family", split="test")
    value["examples"].append(second)
    with pytest.raises(ValueError, match="duplicate"):
        snapshot_dataset(write(tmp_path, value), tmp_path / "snapshot", "local_training")


def test_snapshot_tampering_rejected(tmp_path):
    snapshot_dataset(write(tmp_path, dataset()), tmp_path / "snapshot", "local_training")
    (tmp_path / "snapshot" / "examples.jsonl").write_text("{}\n")
    with pytest.raises(ValueError, match="integrity"):
        read_snapshot(tmp_path / "snapshot", "local_training")


def test_existing_snapshot_never_overwritten(tmp_path):
    path = write(tmp_path, dataset()); dest = tmp_path / "snapshot"
    snapshot_dataset(path, dest, "local_training")
    before = (dest / "manifest.json").read_bytes()
    with pytest.raises(FileExistsError):
        snapshot_dataset(path, dest, "local_training")
    assert (dest / "manifest.json").read_bytes() == before


def test_private_biotech_attachment_preserves_exact_bytes(tmp_path):
    value = dataset(); source = value["sources"][0]
    source.update(domain="biotech", sensitivity="confidential", attachments=["assay.csv"])
    raw = b"sample,signal,unit\r\nA,0.13,AU\r\n"
    (tmp_path / "assay.csv").write_bytes(raw)
    snapshot_dataset(write(tmp_path, value), tmp_path / "snapshot", "local_training")
    manifest, _ = read_snapshot(tmp_path / "snapshot", "local_training")
    name = manifest["sources"][0]["attachments"][0]["file"]
    assert (tmp_path / "snapshot" / name).read_bytes() == raw


def test_unknown_source_and_empty_assistant_rejected(tmp_path):
    value = dataset(); value["examples"][0]["source_ids"] = ["missing"]
    with pytest.raises(ValueError, match="source"):
        snapshot_dataset(write(tmp_path, value), tmp_path / "snapshot", "local_training")
    value = dataset(); value["examples"][0]["messages"][-1]["content"] = ""
    with pytest.raises(ValueError, match="content"):
        snapshot_dataset(write(tmp_path, value), tmp_path / "snapshot", "local_training")
