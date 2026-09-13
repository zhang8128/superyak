"""Pinned, explicitly selected derivative; no implicit replacement model."""
from __future__ import annotations

import copy
from contextlib import contextmanager
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile
import threading

from .data import bounded_read, canonical, digest, private_write

SELECTED = {
    "repo_id": "HauhauCS/Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced",
    "revision": "96c11c22b1128c3c8c655b21557b409f307c557f",
    "filename": "Gemma4-26B-A4B-Uncensored-HauhauCS-Balanced-Q4_K_M.gguf",
    "sha256": "f8b1da6dc139e6928159e536bc85602adbc1412018871732a878dedcad7ccafd",
    "bytes": 16796015968,
    "base_model": "google/gemma-4-26B-A4B-it",
    "base_publisher": "Google",
    "derivative_publisher": "HauhauCS",
    "eligibility_basis": "explicit_user_selection",
    "license": "Apache-2.0",
    "format": "GGUF-Q4_K_M",
    "modalities_for_training": ["text"],
    "dequantization_note": "Reconstructed weights retain quantization loss; original BF16 precision is not recovered.",
}

BASE_CONFIG = {
    "repo_id": "google/gemma-4-26B-A4B-it",
    "revision": "4d7ae4984b7db7de8f8457170b3f1a419ee76d52",
    "filename": "config.json",
    "sha256": "ed0c1eb3633de771906e9ba004a44cc5635bcc06ee2062077c3d2e88a50707d3",
    "bytes": 3815,
}

# Exact text_config from BASE_CONFIG. The selected GGUF metadata
# matches these values, including heterogeneous local/global attention and MoE.
_SELECTED_TEXT_CONFIG = {
    "attention_bias": False,
    "attention_dropout": 0.0,
    "attention_k_eq_v": True,
    "bos_token_id": 2,
    "dtype": "bfloat16",
    "enable_moe_block": True,
    "eos_token_id": 1,
    "final_logit_softcapping": 30.0,
    "global_head_dim": 512,
    "head_dim": 256,
    "hidden_activation": "gelu_pytorch_tanh",
    "hidden_size": 2816,
    "hidden_size_per_layer_input": 0,
    "initializer_range": 0.02,
    "intermediate_size": 2112,
    "layer_types": ["full_attention" if (index + 1) % 6 == 0 else "sliding_attention" for index in range(30)],
    "max_position_embeddings": 262144,
    "model_type": "gemma4_text",
    "moe_intermediate_size": 704,
    "num_attention_heads": 16,
    "num_experts": 128,
    "num_global_key_value_heads": 2,
    "num_hidden_layers": 30,
    "num_key_value_heads": 8,
    "num_kv_shared_layers": 0,
    "pad_token_id": 0,
    "rms_norm_eps": 1e-6,
    "rope_parameters": {
        "full_attention": {
            "partial_rotary_factor": 0.25,
            "rope_theta": 1000000.0,
            "rope_type": "proportional",
        },
        "sliding_attention": {"rope_theta": 10000.0, "rope_type": "default"},
    },
    "sliding_window": 1024,
    "tie_word_embeddings": True,
    "top_k_experts": 8,
    "use_bidirectional_attention": "vision",
    "use_cache": True,
    "use_double_wide_mlp": False,
    "vocab_size": 262144,
    "vocab_size_per_layer_input": 262144,
}

_GGUF_MAPPING_LOCK = threading.Lock()


def _prepared_configuration() -> dict:
    return {
        "source": copy.deepcopy(BASE_CONFIG),
        "text_config_sha256": digest(canonical(_SELECTED_TEXT_CONFIG)),
    }


def _add_gemma4_weight_mappings(mapping: dict[str, str], num_hidden_layers: int) -> dict[str, str]:
    """Complete Transformers 5.17's legacy map for Gemma 4 MoE tensors."""
    for index in range(num_hidden_layers):
        prefix = f"blk.{index}"
        target = f"model.layers.{index}"
        mapping[f"{prefix}.ffn_gate_up_exps.weight"] = f"{target}.experts.gate_up_proj"
        mapping[f"{prefix}.ffn_down_exps.weight"] = f"{target}.experts.down_proj"
        mapping[f"{prefix}.ffn_gate_inp.scale"] = f"{target}.router.scale"
        mapping[f"{prefix}.ffn_down_exps.scale"] = f"{target}.router.per_expert_scale"
        mapping[f"{prefix}.layer_output_scale.weight"] = f"{target}.layer_scalar"
    return mapping


@contextmanager
def _gemma4_weight_mapping():
    """Scope the selected Gemma 4 mapping repair to one synchronous load."""
    from transformers import modeling_gguf_pytorch_utils as gguf_utils

    with _GGUF_MAPPING_LOCK:
        original = gguf_utils.get_gguf_hf_weights_map

        def mapped(hf_model, processor, model_type=None, num_layers=None, qual_name=""):
            result = original(hf_model, processor, model_type, num_layers, qual_name)
            config = getattr(hf_model, "config", None)
            if not qual_name and getattr(config, "model_type", None) == "gemma4_text":
                _add_gemma4_weight_mappings(result, config.num_hidden_layers)
            return result

        gguf_utils.get_gguf_hf_weights_map = mapped
        try:
            yield
        finally:
            gguf_utils.get_gguf_hf_weights_map = original


def selected_model() -> dict:
    return copy.deepcopy(SELECTED)


def verify_file(path: Path, expected_sha: str, expected_size: int | None = None) -> str:
    path = Path(path)
    if path.is_symlink() or not path.is_file():
        raise ValueError("model artifact must be a regular file")
    if expected_size is not None and path.stat().st_size != expected_size:
        raise ValueError("model artifact size mismatch")
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    if sha.hexdigest() != expected_sha:
        raise ValueError("model artifact hash mismatch")
    return sha.hexdigest()


def _hash_file(path):
    sha = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(8 * 1024 * 1024), b""):
            sha.update(chunk)
    return sha.hexdigest()


def download_model(output_dir: Path) -> dict:
    from huggingface_hub import hf_hub_download
    output_dir = Path(output_dir)
    output_dir.mkdir(parents=True, exist_ok=True, mode=0o700)
    model = selected_model()
    path = Path(hf_hub_download(model["repo_id"], filename=model["filename"], revision=model["revision"],
                                local_dir=output_dir, token=False))
    verify_file(path, model["sha256"], model["bytes"])
    return {"status": "download_verified", "path": str(path.resolve()), "source": model}


def prepare_model(gguf_path: Path, output_dir: Path) -> dict:
    """Materialize the selected text weights on a host with adequate RAM."""
    gguf_path, output_dir = Path(gguf_path).resolve(), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("prepared model destination already exists")
    model_source = selected_model()
    verify_file(gguf_path, model_source["sha256"], model_source["bytes"])
    import psutil
    # Legacy GGUF loaders may temporarily keep full FP32 tensors as well as the
    # destination BF16 state. This is a conservative execution floor, not a
    # measured Gemma peak. PVC nodes have substantially more host RAM.
    if psutil.virtual_memory().available < 160 * 2**30:
        raise ValueError("GGUF preparation has a 160 GiB available-host-RAM floor; use an allocated high-memory compute node")
    import torch
    import transformers
    from transformers import AutoModelForCausalLM, Gemma4TextConfig, GemmaTokenizer
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".prepare-", dir=output_dir.parent))
    try:
        config = Gemma4TextConfig(**copy.deepcopy(_SELECTED_TEXT_CONFIG))
        tokenizer = GemmaTokenizer.from_pretrained(str(gguf_path.parent), gguf_file=gguf_path.name,
            local_files_only=True, trust_remote_code=False)
        with _gemma4_weight_mapping():
            model, info = AutoModelForCausalLM.from_pretrained(str(gguf_path.parent), gguf_file=gguf_path.name,
                local_files_only=True, trust_remote_code=False, dtype=torch.bfloat16,
                attn_implementation="eager", output_loading_info=True, config=config)
        if model.config.model_type != "gemma4_text":
            raise ValueError("selected artifact did not load as Gemma 4 text")
        if any(info.get(key) for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
            raise ValueError("GGUF loading was incomplete; no prepared model was accepted")
        if not tokenizer.chat_template:
            raise ValueError("selected artifact has no usable conversation template")
        model.save_pretrained(temporary, safe_serialization=True, max_shard_size="4GB")
        tokenizer.save_pretrained(temporary)
        inventory = {p.name: _hash_file(p) for p in temporary.iterdir() if p.is_file()}
        lineage = {"schema_version": 1, "source": model_source, "configuration": _prepared_configuration(),
                   "format": "dequantized_gguf_text",
                   "files": inventory, "versions": {"torch": torch.__version__, "transformers": transformers.__version__}}
        lineage["digest"] = digest(canonical(lineage))
        private_write(temporary / "lineage.json", canonical(lineage) + b"\n")
        for path in temporary.iterdir():
            if path.is_file(): os.chmod(path, 0o600)
        temporary.rename(output_dir)
        return lineage
    except BaseException:
        shutil.rmtree(temporary)
        raise


def verify_prepared(path: Path) -> dict:
    path = Path(path)
    lineage = json.loads(bounded_read(path / "lineage.json"))
    if not isinstance(lineage, dict) or lineage.get("digest") != digest(canonical({k: v for k, v in lineage.items() if k != "digest"})):
        raise ValueError("prepared model lineage integrity failure")
    if lineage.get("source") != selected_model() or lineage.get("format") != "dequantized_gguf_text":
        raise ValueError("prepared model does not match selected derivative lineage")
    if lineage.get("configuration") != _prepared_configuration():
        raise ValueError("prepared model configuration lineage does not match the pinned base config")
    inventory = lineage.get("files")
    if not isinstance(inventory, dict) or any(not isinstance(n, str) or Path(n).name != n for n in inventory):
        raise ValueError("invalid prepared model file inventory")
    if "config.json" not in inventory or "tokenizer.json" not in inventory or not any(n.endswith(".safetensors") for n in inventory):
        raise ValueError("prepared model inventory is incomplete")
    actual = {p.name for p in path.iterdir() if p.name != "lineage.json"}
    if actual != set(inventory):
        raise ValueError("prepared model file inventory differs from disk")
    for name, sha in inventory.items():
        verify_file(path / name, sha)
    return lineage
