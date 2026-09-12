import hashlib

import pytest

from workbench import Store, WorkbenchError
from workbench.legacy import import_vault


def write_note(path, *, node_id="mol.cell-fate", layer="molecular-bio", domain="development", title="Cell fate", summary="Predict cell fate."):
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(
        "\n".join([
            "---",
            f"id: {node_id}",
            f"layer: {layer}",
            f"domain: {domain}",
            "confidence_tier: high",
            "cost_low_m: 12",
            "---",
            "",
            f"# {title}",
            "",
            "## Summary",
            "",
            summary,
            "",
            "## Dependencies",
            "",
            "- [[another-note]]",
        ]),
        encoding="utf-8",
    )


def hashes(root):
    return {
        path.relative_to(root).as_posix(): hashlib.sha256(path.read_bytes()).hexdigest()
        for path in sorted(root.rglob("*"))
        if path.is_file()
    }


def test_import_vault_is_read_only_proposed_and_idempotent(tmp_path):
    vault = tmp_path / "vault"
    note = vault / "Nodes" / "molecular-bio" / "cell-fate.md"
    write_note(note)
    before = hashes(vault)

    with Store(tmp_path / "workbench.db", create=True) as store:
        assert import_vault(store, vault) == {"sources": 0, "items": 1, "relations": 0}
        assert import_vault(store, vault) == {"sources": 0, "items": 0, "relations": 0}
        record = store.get("legacy:mol.cell-fate")

    assert hashes(vault) == before
    assert record["kind"] == "question"
    assert record["status"] == "proposed"
    assert record["facets"] == {"layer": ["molecular-bio"], "domain": ["development"]}
    assert record["provenance"] == {
        "old_id": "mol.cell-fate",
        "path": "Nodes/molecular-bio/cell-fate.md",
        "sha256": hashlib.sha256(note.read_bytes()).hexdigest(),
    }
    assert "not been reassessed" in record["summary"]
    assert "cost" not in record
    assert "confidence" not in record


def test_one_malformed_note_rolls_back_entire_vault_batch_and_changes_no_source_bytes(tmp_path):
    vault = tmp_path / "vault"
    write_note(vault / "Nodes" / "molecular-bio" / "good.md", node_id="good")
    bad = vault / "Nodes" / "cellular-bio" / "bad.md"
    bad.parent.mkdir(parents=True)
    bad.write_bytes(b"---\nid: bad\nlayer: cellular-bio\ndomain: test\n---\n# Missing summary\n")
    before = hashes(vault)

    with Store(tmp_path / "workbench.db", create=True) as store:
        with pytest.raises(WorkbenchError, match="bad.md"):
            import_vault(store, vault)
        assert store.export_bundle()["items"] == []

    assert hashes(vault) == before


def test_invalid_utf8_note_reports_its_path_without_importing_siblings(tmp_path):
    vault = tmp_path / "vault"
    write_note(vault / "Nodes" / "molecular-bio" / "good.md", node_id="good")
    bad = vault / "Nodes" / "molecular-bio" / "binary.md"
    bad.write_bytes(b"\xff\xfe")

    with Store(tmp_path / "workbench.db", create=True) as store:
        with pytest.raises(WorkbenchError, match="binary.md"):
            import_vault(store, vault)
        assert store.search() == []
