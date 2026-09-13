"""Import the selected public weights into an existing local Ollama server."""

from __future__ import annotations

import json
import os
import re
import subprocess
import tempfile
from pathlib import Path

from .data import bounded_read, canonical, digest, private_write
from .models import selected_model, verify_file

DEFAULT_MODEL = "superyak-clinical-gemma4-balanced:q4_k_m"


def runtime_identity(endpoint: str, model: str) -> dict:
    from .evaluation import request_json

    tags = request_json(endpoint, "/api/tags")
    entries = tags.get("models", [])
    if not isinstance(entries, list):
        raise ValueError("invalid model listing")
    matches = [
        e
        for e in entries
        if isinstance(e, dict) and (e.get("name") == model or e.get("model") == model)
    ]
    if (
        len(matches) != 1
        or not isinstance(matches[0].get("digest"), str)
        or not re.fullmatch("[0-9a-f]{64}", matches[0]["digest"])
    ):
        raise ValueError("model identity is absent or ambiguous")
    details = request_json(endpoint, "/api/show", {"model": model})
    modelfile = details.get("modelfile")
    if not isinstance(modelfile, str):
        raise ValueError("invalid runtime model description")
    blobs = [
        Path(line.strip()[5:].strip().strip('"')).name
        for line in modelfile.splitlines()
        if line.strip().startswith("FROM ")
    ]
    if len(blobs) != 1 or not re.fullmatch("sha256-[0-9a-f]{64}", blobs[0]):
        raise ValueError("runtime model blob is absent or ambiguous")
    return {"model": model, "digest": matches[0]["digest"], "blob_sha256": blobs[0][7:]}


def read_import_receipt(path: Path) -> dict:
    value = json.loads(bounded_read(path))
    if not isinstance(value, dict) or value.get("digest") != digest(
        canonical({k: v for k, v in value.items() if k != "digest"})
    ):
        raise ValueError("invalid model import receipt")
    if (
        value.get("schema_version") != 1
        or value.get("source") != selected_model()
        or value.get("operation") != "ollama_create_from_verified_gguf"
    ):
        raise ValueError("model import receipt has a different source")
    return value


def install_model(
    gguf_path: Path, endpoint: str, model: str, receipt_path: Path
) -> dict:
    from .evaluation import local_endpoint

    endpoint = local_endpoint(endpoint)
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.:/-]{0,127}", model):
        raise ValueError("invalid local model name")
    receipt_path = Path(receipt_path)
    if receipt_path.exists():
        raise FileExistsError("model import receipt already exists")
    source = selected_model()
    gguf_path = Path(gguf_path).resolve()
    verify_file(gguf_path, source["sha256"], source["bytes"])
    # A quote or newline in a path cannot be safely represented in a Modelfile.
    if any(c in str(gguf_path) for c in '\n\r"'):
        raise ValueError("unsupported GGUF path characters")
    with tempfile.TemporaryDirectory(prefix="superyak-import-") as temporary:
        modelfile = Path(temporary) / "Modelfile"
        modelfile.write_text(f'FROM "{gguf_path}"\nPARAMETER num_ctx 8192\n')
        result = subprocess.run(
            ["ollama", "create", model, "-f", str(modelfile)],
            env={**os.environ, "OLLAMA_HOST": endpoint},
            capture_output=True,
            check=False,
            timeout=1800,
        )
        if result.returncode:
            raise ValueError("local Ollama model import failed")
    verify_file(gguf_path, source["sha256"], source["bytes"])
    identity = runtime_identity(endpoint, model)
    receipt = {
        "schema_version": 1,
        "operation": "ollama_create_from_verified_gguf",
        "source": source,
        "runtime": identity,
        "endpoint": endpoint,
    }
    receipt["digest"] = digest(canonical(receipt))
    receipt_path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    private_write(receipt_path, canonical(receipt) + b"\n")
    return receipt
