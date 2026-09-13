import hashlib
import json
import sys
from pathlib import Path
from types import ModuleType, SimpleNamespace

import pytest

from superyak_tuning.data import canonical, digest
import superyak_tuning.models as model_tools
from superyak_tuning.models import selected_model, verify_file, verify_prepared


TINY_GGUF = b"GGUFfixture"


def use_tiny_selected_model(monkeypatch):
    selected = selected_model()
    selected["sha256"] = hashlib.sha256(TINY_GGUF).hexdigest()
    selected["bytes"] = len(TINY_GGUF)
    monkeypatch.setattr(model_tools, "SELECTED", selected)
    return selected


def write_prepared_fixture(path):
    files = {
        "config.json": b'{"model_type":"gemma4_text"}',
        "model.safetensors": b"fixture",
        "tokenizer.json": b"{}",
    }
    for name, content in files.items():
        (path / name).write_bytes(content)
    manifest = {
        "schema_version": 1,
        "source": selected_model(),
        "configuration": model_tools._prepared_configuration(),
        "format": "dequantized_gguf_text",
        "files": {name: digest(data) for name, data in files.items()},
    }
    manifest["digest"] = digest(canonical(manifest))
    (path / "lineage.json").write_bytes(canonical(manifest))
    return manifest


def install_fake_preparation_dependencies(
    monkeypatch,
    *,
    available=161 * 2**30,
    model_type="gemma4_text",
    loading_info=None,
    chat_template="{{ messages }}",
):
    calls = {}
    bfloat16 = object()

    psutil = ModuleType("psutil")
    psutil.virtual_memory = lambda: SimpleNamespace(available=available)
    torch = ModuleType("torch")
    torch.bfloat16 = bfloat16
    torch.__version__ = "2.test"
    transformers = ModuleType("transformers")
    transformers.__version__ = "5.test"

    class FakeConfig:
        def __init__(self, **kwargs):
            calls["config"] = kwargs
            self.__dict__.update(kwargs)

    class FakeTokenizer:
        def __init__(self):
            self.chat_template = chat_template

        @classmethod
        def from_pretrained(cls, source, **kwargs):
            calls["tokenizer_load"] = (source, kwargs)
            return cls()

        def save_pretrained(self, destination):
            calls["tokenizer_save"] = Path(destination)
            (Path(destination) / "tokenizer.json").write_text("{}")

    class FakeModel:
        config = SimpleNamespace(model_type=model_type)

        def save_pretrained(self, destination, **kwargs):
            calls["model_save"] = (Path(destination), kwargs)
            destination = Path(destination)
            (destination / "config.json").write_text(json.dumps({"model_type": model_type}))
            (destination / "model.safetensors").write_bytes(b"prepared weights")

    class FakeAutoModel:
        @staticmethod
        def from_pretrained(source, **kwargs):
            calls["model_load"] = (source, kwargs)
            calls["mapping"] = gguf_utils.get_gguf_hf_weights_map(
                SimpleNamespace(config=SimpleNamespace(model_type="gemma4_text", num_hidden_layers=30)),
                object(),
            )
            info = loading_info
            if info is None:
                info = {"missing_keys": [], "unexpected_keys": [], "mismatched_keys": [], "error_msgs": []}
            return FakeModel(), info

    class BrokenAutoTokenizer:
        @staticmethod
        def from_pretrained(*args, **kwargs):
            raise AssertionError("AutoTokenizer cannot parse the selected heterogeneous GGUF config")

    gguf_utils = ModuleType("transformers.modeling_gguf_pytorch_utils")
    gguf_utils.get_gguf_hf_weights_map = lambda *args, **kwargs: {}
    transformers.AutoTokenizer = BrokenAutoTokenizer
    transformers.AutoModelForCausalLM = FakeAutoModel
    transformers.Gemma4TextConfig = FakeConfig
    transformers.GemmaTokenizer = FakeTokenizer
    transformers.modeling_gguf_pytorch_utils = gguf_utils
    monkeypatch.setitem(sys.modules, "psutil", psutil)
    monkeypatch.setitem(sys.modules, "torch", torch)
    monkeypatch.setitem(sys.modules, "transformers", transformers)
    monkeypatch.setitem(sys.modules, "transformers.modeling_gguf_pytorch_utils", gguf_utils)
    return calls, bfloat16


def test_selected_variant_is_exact_and_does_not_claim_maintainer_origin():
    model = selected_model()
    assert model["repo_id"] == "HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced"
    assert model["revision"] == "96c11c22b1128c3c8c655b21557b409f307c557f"
    assert model["sha256"] == "f8b1da6dc139e6928159e536bc85602adbc1412018871732a878dedcad7ccafd"
    assert model["base_publisher"] == "Google"
    assert model["derivative_publisher"] == "HauhauCS"
    assert model["eligibility_basis"] == "explicit_user_selection"
    assert "base_config" not in model
    assert model_tools.BASE_CONFIG == {
        "repo_id": "google/gemma-4-26B-A4B-it",
        "revision": "4d7ae4984b7db7de8f8457170b3f1a419ee76d52",
        "filename": "config.json",
        "sha256": "ed0c1eb3633de771906e9ba004a44cc5635bcc06ee2062077c3d2e88a50707d3",
        "bytes": 3815,
    }


def test_hash_and_size_both_checked(tmp_path):
    p = tmp_path / "model.gguf"; p.write_bytes(b"GGUFfixture")
    sha = hashlib.sha256(p.read_bytes()).hexdigest()
    assert verify_file(p, sha, 11) == sha
    with pytest.raises(ValueError, match="size"):
        verify_file(p, sha, 12)
    with pytest.raises(ValueError, match="hash"):
        verify_file(p, "0" * 64, 11)


def test_prepared_weights_are_pinned_to_selected_derivative(tmp_path):
    write_prepared_fixture(tmp_path)
    assert verify_prepared(tmp_path)["source"]["sha256"] == selected_model()["sha256"]
    (tmp_path / "model.safetensors").write_bytes(b"modified")
    with pytest.raises(ValueError, match="hash"):
        verify_prepared(tmp_path)


def test_prepared_configuration_is_pinned_even_with_a_valid_manifest_digest(tmp_path):
    manifest = write_prepared_fixture(tmp_path)
    manifest["configuration"]["source"]["revision"] = "unpinned"
    manifest["digest"] = digest(canonical({key: value for key, value in manifest.items() if key != "digest"}))
    (tmp_path / "lineage.json").write_bytes(canonical(manifest))

    with pytest.raises(ValueError, match="configuration lineage"):
        verify_prepared(tmp_path)


def test_prepared_model_cannot_point_outside_directory(tmp_path):
    manifest = {"schema_version": 1, "source": selected_model(),
        "configuration": model_tools._prepared_configuration(),
        "format": "dequantized_gguf_text", "files": {"../outside": "0" * 64}}
    manifest["digest"] = digest(canonical(manifest))
    (tmp_path / "lineage.json").write_bytes(canonical(manifest))
    with pytest.raises(ValueError, match="inventory"):
        verify_prepared(tmp_path)


def test_download_uses_pinned_hub_identity_and_disables_token_forwarding(tmp_path, monkeypatch):
    selected = use_tiny_selected_model(monkeypatch)
    calls = {}
    hub = ModuleType("huggingface_hub")

    def fake_download(repo_id, *, filename, revision, local_dir, token):
        calls.update(repo_id=repo_id, filename=filename, revision=revision, local_dir=Path(local_dir), token=token)
        path = Path(local_dir) / filename
        path.write_bytes(TINY_GGUF)
        return str(path)

    hub.hf_hub_download = fake_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)

    destination = tmp_path / "download"
    result = model_tools.download_model(destination)

    assert calls == {
        "repo_id": "HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced",
        "filename": "Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf",
        "revision": "96c11c22b1128c3c8c655b21557b409f307c557f",
        "local_dir": destination,
        "token": False,
    }
    assert result == {
        "status": "download_verified",
        "path": str((destination / selected["filename"]).resolve()),
        "source": selected,
    }


@pytest.mark.parametrize(
    ("downloaded", "error"),
    [(b"short", "size"), (b"GGUXfixture", "hash")],
)
def test_download_rejects_wrong_size_or_hash(tmp_path, monkeypatch, downloaded, error):
    selected = use_tiny_selected_model(monkeypatch)
    hub = ModuleType("huggingface_hub")

    def fake_download(repo_id, *, filename, revision, local_dir, token):
        path = Path(local_dir) / selected["filename"]
        path.write_bytes(downloaded)
        return str(path)

    hub.hf_hub_download = fake_download
    monkeypatch.setitem(sys.modules, "huggingface_hub", hub)

    with pytest.raises(ValueError, match=error):
        model_tools.download_model(tmp_path / "download")


def test_prepare_enforces_available_memory_floor_before_loading(tmp_path, monkeypatch):
    use_tiny_selected_model(monkeypatch)
    gguf = tmp_path / "selected.gguf"
    gguf.write_bytes(TINY_GGUF)
    install_fake_preparation_dependencies(monkeypatch, available=160 * 2**30 - 1)

    with pytest.raises(ValueError, match="160 GiB"):
        model_tools.prepare_model(gguf, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()
    assert list(tmp_path.glob(".prepare-*")) == []


def test_prepare_rejects_an_unverified_selected_artifact(tmp_path, monkeypatch):
    use_tiny_selected_model(monkeypatch)
    gguf = tmp_path / "selected.gguf"
    gguf.write_bytes(b"GGUXfixture")

    with pytest.raises(ValueError, match="hash"):
        model_tools.prepare_model(gguf, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()


@pytest.mark.parametrize(
    ("options", "error"),
    [
        (
            {
                "loading_info": {
                    "missing_keys": ["model.layers.0.weight"],
                    "unexpected_keys": [],
                    "mismatched_keys": [],
                    "error_msgs": [],
                }
            },
            "incomplete",
        ),
        ({"model_type": "gemma3_text"}, "Gemma 4 text"),
        ({"chat_template": ""}, "conversation template"),
    ],
)
def test_prepare_rejects_incomplete_materialization_and_cleans_up(tmp_path, monkeypatch, options, error):
    use_tiny_selected_model(monkeypatch)
    gguf = tmp_path / "selected.gguf"
    gguf.write_bytes(TINY_GGUF)
    install_fake_preparation_dependencies(monkeypatch, **options)

    with pytest.raises(ValueError, match=error):
        model_tools.prepare_model(gguf, tmp_path / "prepared")
    assert not (tmp_path / "prepared").exists()
    assert list(tmp_path.glob(".prepare-*")) == []


def test_prepare_uses_safe_local_bf16_loading_and_records_complete_lineage(tmp_path, monkeypatch):
    selected = use_tiny_selected_model(monkeypatch)
    gguf = tmp_path / "selected.gguf"
    gguf.write_bytes(TINY_GGUF)
    calls, bfloat16 = install_fake_preparation_dependencies(monkeypatch)
    gguf_utils = sys.modules["transformers.modeling_gguf_pytorch_utils"]
    original_mapper = gguf_utils.get_gguf_hf_weights_map

    destination = tmp_path / "prepared"
    lineage = model_tools.prepare_model(gguf, destination)

    source = str(gguf.parent.resolve())
    assert calls["tokenizer_load"] == (
        source,
        {"gguf_file": gguf.name, "local_files_only": True, "trust_remote_code": False},
    )
    loaded_source, loaded_options = calls["model_load"]
    assert loaded_source == source
    assert {key: value for key, value in loaded_options.items() if key != "config"} == {
        "gguf_file": gguf.name,
        "local_files_only": True,
        "trust_remote_code": False,
        "dtype": bfloat16,
        "attn_implementation": "eager",
        "output_loading_info": True,
    }
    assert loaded_options["config"].model_type == "gemma4_text"
    assert calls["config"]["num_key_value_heads"] == 8
    assert calls["config"]["num_global_key_value_heads"] == 2
    assert calls["config"]["head_dim"] == 256
    assert calls["config"]["global_head_dim"] == 512
    assert calls["config"]["enable_moe_block"] is True
    assert calls["config"]["num_experts"] == 128
    assert calls["config"]["top_k_experts"] == 8
    assert calls["config"]["moe_intermediate_size"] == 704
    assert calls["config"]["layer_types"] == [
        "full_attention" if (index + 1) % 6 == 0 else "sliding_attention" for index in range(30)
    ]
    assert len(calls["mapping"]) == 150
    assert calls["mapping"]["blk.0.ffn_gate_up_exps.weight"] == "model.layers.0.experts.gate_up_proj"
    assert calls["mapping"]["blk.29.ffn_down_exps.scale"] == "model.layers.29.router.per_expert_scale"
    assert calls["mapping"]["blk.29.layer_output_scale.weight"] == "model.layers.29.layer_scalar"
    assert gguf_utils.get_gguf_hf_weights_map is original_mapper
    assert calls["model_save"][1] == {"safe_serialization": True, "max_shard_size": "4GB"}
    assert lineage["source"] == selected
    assert lineage["configuration"] == {
        "source": {
            "repo_id": "google/gemma-4-26B-A4B-it",
            "revision": "4d7ae4984b7db7de8f8457170b3f1a419ee76d52",
            "filename": "config.json",
            "sha256": "ed0c1eb3633de771906e9ba004a44cc5635bcc06ee2062077c3d2e88a50707d3",
            "bytes": 3815,
        },
        "text_config_sha256": "60217c028c5b67ecad91b7d882fbdbd636999f2ea774ab6df93ccb06962691b8",
    }
    assert lineage["versions"] == {"torch": "2.test", "transformers": "5.test"}
    assert set(lineage["files"]) == {"config.json", "model.safetensors", "tokenizer.json"}
    assert verify_prepared(destination) == lineage
