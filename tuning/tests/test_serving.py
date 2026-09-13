import copy
import json
from types import SimpleNamespace

import pytest
from superyak_tuning import serving
from superyak_tuning.data import canonical, digest
from superyak_tuning.evaluation import inspect_model


def test_import_binds_converted_runtime_to_verified_original(tmp_path, monkeypatch):
    gguf = tmp_path / "selected.gguf"
    gguf.write_bytes(b"fixture")
    receipt_path = tmp_path / "import.json"
    checks = []
    monkeypatch.setattr(serving, "verify_file", lambda *a: checks.append(a))
    runtime = {"model": "clinical:test", "digest": "a" * 64, "blob_sha256": "b" * 64}
    monkeypatch.setattr(serving, "runtime_identity", lambda *a: runtime)

    def create(command, **kwargs):
        assert command[:3] == ["ollama", "create", "clinical:test"]
        assert kwargs["env"]["OLLAMA_HOST"] == "http://127.0.0.1:11434"
        assert str(gguf) in __import__("pathlib").Path(command[-1]).read_text()
        return SimpleNamespace(returncode=0)

    monkeypatch.setattr(serving.subprocess, "run", create)
    receipt = serving.install_model(
        gguf, "http://127.0.0.1:11434", "clinical:test", receipt_path
    )
    assert len(checks) == 2
    assert serving.read_import_receipt(receipt_path) == receipt
    assert (
        inspect_model(receipt["endpoint"], "clinical:test", receipt)["blob_sha256"]
        == "b" * 64
    )
    altered = copy.deepcopy(receipt)
    altered["runtime"]["digest"] = "c" * 64
    with pytest.raises(ValueError, match="differs"):
        inspect_model(receipt["endpoint"], "clinical:test", altered)
    assert receipt_path.stat().st_mode & 0o077 == 0


def test_failed_import_never_publishes_a_receipt(tmp_path, monkeypatch):
    monkeypatch.setattr(serving, "verify_file", lambda *a: None)
    monkeypatch.setattr(
        serving.subprocess, "run", lambda *a, **k: SimpleNamespace(returncode=1)
    )
    with pytest.raises(ValueError, match="import failed"):
        serving.install_model(
            tmp_path / "model.gguf",
            "http://127.0.0.1:11434",
            "clinical:test",
            tmp_path / "receipt.json",
        )
    assert not (tmp_path / "receipt.json").exists()


def test_import_receipt_tamper_rejected(tmp_path):
    value = {"schema_version": 1, "source": serving.selected_model()}
    value["digest"] = digest(canonical(value))
    value["schema_version"] = 2
    path = tmp_path / "receipt.json"
    path.write_text(json.dumps(value))
    with pytest.raises(ValueError, match="receipt"):
        serving.read_import_receipt(path)
