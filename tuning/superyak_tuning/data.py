"""Purpose-bound local snapshots; clinical sensitivity is not a topic ban."""
from __future__ import annotations

import hashlib
import json
import os
from pathlib import Path
import re
import shutil
import tempfile

PURPOSES = {"inference", "local_training", "shared_training", "publish_adapter"}
LIMIT = 64 * 1024 * 1024


def canonical(value) -> bytes:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"), allow_nan=False).encode()


def digest(data: bytes) -> str:
    return hashlib.sha256(data).hexdigest()


def private_write(path: Path, content: bytes):
    with path.open("xb") as stream:
        os.chmod(path, 0o600)
        stream.write(content)


def bounded_read(path: Path) -> bytes:
    if not path.is_file() or path.is_symlink():
        raise ValueError("input must be a regular local file")
    with path.open("rb") as stream:
        data = stream.read(LIMIT + 1)
    if len(data) > LIMIT:
        raise ValueError("file exceeds the 64 MiB import limit")
    return data


def _identifier(value):
    if not isinstance(value, str) or not re.fullmatch(r"[a-zA-Z0-9_.-]{1,128}", value):
        raise ValueError("invalid record identifier")
    return value


def _check_permissions(sources, purpose):
    if purpose not in PURPOSES:
        raise ValueError("unknown use purpose")
    for source in sources:
        permissions = source.get("permissions", {})
        if not isinstance(permissions, dict) or any(type(v) is not bool for v in permissions.values()):
            raise ValueError("permissions must be boolean values")
        if any(key not in PURPOSES for key in permissions):
            raise ValueError("unknown permission")
        if permissions.get(purpose) is not True:
            raise ValueError("source permission does not allow the requested purpose")


def validate_dataset(value, purpose):
    if not isinstance(value, dict) or value.get("schema_version") != 1:
        raise ValueError("dataset schema_version must be 1")
    sources, rows = value.get("sources"), value.get("examples")
    if not isinstance(sources, list) or not isinstance(rows, list) or not rows:
        raise ValueError("dataset requires sources and nonempty examples")
    by_id = {}
    for source in sources:
        if not isinstance(source, dict):
            raise ValueError("invalid source")
        sid = _identifier(source.get("id"))
        if sid in by_id:
            raise ValueError("duplicate source ID")
        if source.get("domain") not in {"clinical", "biotech"}:
            raise ValueError("source domain must be clinical or biotech")
        if source.get("sensitivity") not in {"public", "deidentified", "identifiable", "confidential"}:
            raise ValueError("source requires a sensitivity classification")
        if not isinstance(source.get("rights"), str) or not source["rights"].strip():
            raise ValueError("source requires a rights description")
        by_id[sid] = source
    used, ids, groups, conversations = set(), set(), {}, {}
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError("invalid example")
        rid, gid = _identifier(row.get("id")), _identifier(row.get("group_id"))
        if rid in ids:
            raise ValueError("duplicate example ID")
        ids.add(rid)
        split = row.get("split")
        if split not in {"train", "dev", "test"}:
            raise ValueError("invalid dataset split")
        if gid in groups and groups[gid] != split:
            raise ValueError("a group crosses dataset splits")
        groups[gid] = split
        refs = row.get("source_ids")
        if not isinstance(refs, list) or not refs or any(not isinstance(s, str) or s not in by_id for s in refs):
            raise ValueError("example references an unknown or missing source")
        used.update(refs)
        messages = row.get("messages")
        if not isinstance(messages, list) or len(messages) < 2:
            raise ValueError("example requires a conversation")
        for message in messages:
            if not isinstance(message, dict) or message.get("role") not in {"system", "user", "assistant", "tool"}:
                raise ValueError("invalid conversation role")
            if not isinstance(message.get("content"), str) or not message["content"].strip():
                raise ValueError("message content must be nonempty text")
        if messages[-1]["role"] != "assistant" or not any(m["role"] == "user" for m in messages):
            raise ValueError("supervised examples need a user and final assistant completion")
        fingerprint = digest(canonical(messages))
        if fingerprint in conversations and conversations[fingerprint] != split:
            raise ValueError("duplicate conversation crosses dataset splits")
        conversations[fingerprint] = split
    selected = [by_id[sid] for sid in sorted(used)]
    _check_permissions(selected, purpose)
    return selected, rows


def snapshot_dataset(input_path: Path, output_dir: Path, purpose: str = "local_training") -> dict:
    input_path, output_dir = Path(input_path), Path(output_dir)
    if output_dir.exists():
        raise FileExistsError("snapshot destination already exists")
    value = json.loads(bounded_read(input_path))
    sources, rows = validate_dataset(value, purpose)
    output_dir.parent.mkdir(parents=True, exist_ok=True)
    temporary = Path(tempfile.mkdtemp(prefix=".snapshot-", dir=output_dir.parent))
    try:
        manifest_sources, inventory = [], {}
        for index, source in enumerate(sources):
            copied = {k: source[k] for k in ("id", "domain", "sensitivity", "rights")}
            copied["permissions"] = {p: source.get("permissions", {}).get(p, False) for p in sorted(PURPOSES)}
            copied["attachments"] = []
            attachments = source.get("attachments", [])
            if not isinstance(attachments, list):
                raise ValueError("source attachments must be a list of local paths")
            for attachment_index, name in enumerate(attachments):
                if not isinstance(name, str):
                    raise ValueError("attachment must be a local path")
                path = input_path.parent / name
                if not path.resolve().is_relative_to(input_path.parent.resolve()) or path.is_symlink():
                    raise ValueError("attachment must stay within the dataset directory")
                suffix = path.suffix.lower()
                if suffix not in {".csv", ".json", ".jsonl", ".txt"}:
                    raise ValueError("attachment format must be CSV, JSON, JSONL, or text")
                raw = bounded_read(path)
                stored = f"source-{index}-{attachment_index}{suffix}"
                private_write(temporary / stored, raw)
                inventory[stored] = digest(raw)
                copied["attachments"].append({"file": stored, "sha256": digest(raw), "bytes": len(raw)})
            manifest_sources.append(copied)
        raw_rows = b"".join(canonical(row) + b"\n" for row in rows)
        private_write(temporary / "examples.jsonl", raw_rows)
        inventory["examples.jsonl"] = digest(raw_rows)
        manifest = {"schema_version": 1, "purpose": purpose, "sources": manifest_sources,
                    "example_count": len(rows), "splits": {s: sum(r["split"] == s for r in rows) for s in ("train", "dev", "test")},
                    "files": inventory}
        manifest["digest"] = digest(canonical(manifest))
        private_write(temporary / "manifest.json", canonical(manifest) + b"\n")
        temporary.rename(output_dir)
        return manifest
    except BaseException:
        shutil.rmtree(temporary)
        raise


def read_snapshot(path: Path, purpose: str = "local_training") -> tuple[dict, list[dict]]:
    path = Path(path)
    manifest = json.loads(bounded_read(path / "manifest.json"))
    if not isinstance(manifest, dict):
        raise ValueError("snapshot integrity failure")
    if manifest.get("schema_version") != 1:
        raise ValueError("snapshot schema_version must be 1")
    if manifest.get("purpose") != purpose:
        raise ValueError("snapshot purpose differs from the requested use; create a new snapshot")
    expected = manifest.get("digest")
    if expected != digest(canonical({k: v for k, v in manifest.items() if k != "digest"})):
        raise ValueError("snapshot manifest integrity failure")
    inventory = manifest.get("files", {})
    if not isinstance(inventory, dict) or "examples.jsonl" not in inventory:
        raise ValueError("snapshot file inventory missing")
    if {p.name for p in path.iterdir()} != set(inventory) | {"manifest.json"}:
        raise ValueError("snapshot file inventory differs from disk")
    for name, sha in inventory.items():
        if not isinstance(name, str) or Path(name).name != name:
            raise ValueError("invalid snapshot file inventory")
        if digest(bounded_read(path / name)) != sha:
            raise ValueError("snapshot file integrity failure")
    rows = [json.loads(line) for line in bounded_read(path / "examples.jsonl").splitlines() if line]
    validate_dataset({"schema_version": 1, "sources": manifest["sources"], "examples": rows}, purpose)
    attachment_names = set()
    for source in manifest["sources"]:
        attachments = source.get("attachments", [])
        if not isinstance(attachments, list):
            raise ValueError("invalid attachment inventory")
        for attachment in attachments:
            if not isinstance(attachment, dict):
                raise ValueError("invalid attachment inventory")
            name = attachment.get("file")
            if not isinstance(name, str) or name == "examples.jsonl" or name not in inventory or name in attachment_names:
                raise ValueError("invalid attachment inventory reference")
            if attachment.get("sha256") != inventory[name] or attachment.get("bytes") != (path / name).stat().st_size:
                raise ValueError("attachment inventory integrity failure")
            attachment_names.add(name)
    if attachment_names != set(inventory) - {"examples.jsonl"}:
        raise ValueError("snapshot attachment inventory is incomplete")
    if len(rows) != manifest.get("example_count"):
        raise ValueError("snapshot count integrity failure")
    split_counts = {split: sum(row["split"] == split for row in rows) for split in ("train", "dev", "test")}
    if manifest.get("splits") != split_counts:
        raise ValueError("snapshot split count integrity failure")
    return manifest, rows
