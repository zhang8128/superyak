"""Pinned, explicitly selected derivative; no implicit replacement model."""
from __future__ import annotations

import copy
import hashlib
import json
import os
from pathlib import Path
import shutil
import tempfile

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
    from transformers import AutoModelForCausalLM, AutoTokenizer
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".prepare-", dir=output_dir.parent))
    try:
        tokenizer = AutoTokenizer.from_pretrained(str(gguf_path.parent), gguf_file=gguf_path.name,
            local_files_only=True, trust_remote_code=False)
        model, info = AutoModelForCausalLM.from_pretrained(str(gguf_path.parent), gguf_file=gguf_path.name,
            local_files_only=True, trust_remote_code=False, dtype=torch.bfloat16,
            attn_implementation="eager", output_loading_info=True)
        if model.config.model_type != "gemma4_text":
            raise ValueError("selected artifact did not load as Gemma 4 text")
        if any(info.get(key) for key in ("missing_keys", "unexpected_keys", "mismatched_keys", "error_msgs")):
            raise ValueError("GGUF loading was incomplete; no prepared model was accepted")
        if not tokenizer.chat_template:
            raise ValueError("selected artifact has no usable conversation template")
        model.save_pretrained(temporary, safe_serialization=True, max_shard_size="4GB")
        tokenizer.save_pretrained(temporary)
        inventory = {p.name: _hash_file(p) for p in temporary.iterdir() if p.is_file()}
        lineage = {"schema_version": 1, "source": model_source, "format": "dequantized_gguf_text",
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
