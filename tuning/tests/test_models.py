import hashlib
import json

import pytest

from superyak_tuning.models import selected_model, verify_file, verify_prepared
from superyak_tuning.data import canonical, digest


def test_selected_variant_is_exact_and_does_not_claim_maintainer_origin():
    model = selected_model()
    assert model["repo_id"] == "HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced"
    assert model["revision"] == "96c11c22b1128c3c8c655b21557b409f307c557f"
    assert model["sha256"] == "f8b1da6dc139e6928159e536bc85602adbc1412018871732a878dedcad7ccafd"
    assert model["base_publisher"] == "Google"
    assert model["derivative_publisher"] == "HauhauCS"
    assert model["eligibility_basis"] == "explicit_user_selection"


def test_hash_and_size_both_checked(tmp_path):
    p = tmp_path / "model.gguf"; p.write_bytes(b"GGUFfixture")
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    assert verify_file(p, sha, 11) == sha
    with pytest.raises(ValueError, match="size"):
        verify_file(p, sha, 12)
    with pytest.raises(ValueError, match="hash"):
        verify_file(p, "0" * 64, 11)


def test_prepared_weights_are_pinned_to_selected_derivative(tmp_path):
    files = {"config.json": b'{"model_type":"gemma4_text"}', "model.safetensors": b"fixture", "tokenizer.json": b"{}"}
    for name, content in files.items(): (tmp_path / name).write_bytes(content)
    manifest = {"schema_version": 1, "source": selected_model(), "format": "dequantized_gguf_text",
        "files": {name: digest(data) for name, data in files.items()}}
    manifest["digest"] = digest(canonical(manifest))
    (tmp_path / "lineage.json").write_bytes(canonical(manifest))
    assert verify_prepared(tmp_path)["source"]["sha256"] == selected_model()["sha256"]
    (tmp_path / "model.safetensors").write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash"):
        verify_prepared(tmp_path)


def test_prepared_model_cannot_point_outside_directory(tmp_path):
    manifest = {"schema_version": 1, "source": selected_model(), "format": "dequantized_gguf_text", "files": {"../outside": "0" * 64}}
    manifest["digest"] = digest(canonical(manifest))
    (tmp_path / "lineage.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="inventory"):
        verify_prepared(tmp_path)
