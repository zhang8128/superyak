"""Read-only adapter for saved Atlas vault notes."""

from __future__ import annotations

import hashlib
from pathlib import Path
import re

from .validation import WorkbenchError


WARNING = "Legacy import warning: node kind and claims have not been reassessed."


def _unquote(value):
    if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
        return value[1:-1]
    return value


def _parse_note(path, vault_path):
    raw = path.read_bytes()
    try:
        text = raw.decode("utf-8")
    except UnicodeDecodeError as exc:
        raise WorkbenchError(f"malformed legacy note {path}: not valid UTF-8") from exc
    lines = text.splitlines()
    if not lines or lines[0].strip() != "---":
        raise WorkbenchError(f"malformed legacy note {path}: missing frontmatter")
    try:
        closing = next(index for index, line in enumerate(lines[1:], 1) if line.strip() == "---")
    except StopIteration as exc:
        raise WorkbenchError(f"malformed legacy note {path}: unclosed frontmatter") from exc
    metadata = {}
    for line_number, line in enumerate(lines[1:closing], 2):
        if not line.strip() or line.lstrip().startswith("#"):
            continue
        if ":" not in line:
            raise WorkbenchError(f"malformed legacy note {path}:{line_number}: expected key: value")
        key, value = line.split(":", 1)
        key = key.strip()
        if not key or key in metadata:
            raise WorkbenchError(f"malformed legacy note {path}:{line_number}: invalid duplicate key")
        metadata[key] = _unquote(value.strip())
    for key in ("id", "layer", "domain"):
        if not metadata.get(key, "").strip():
            raise WorkbenchError(f"malformed legacy note {path}: missing {key}")
    body = lines[closing + 1:]
    title = next(
        (match.group(1).strip() for line in body if (match := re.match(r"^#\s+(.+?)\s*$", line))),
        "",
    )
    if not title:
        raise WorkbenchError(f"malformed legacy note {path}: missing title")
    summary_start = next(
        (index for index, line in enumerate(body) if re.match(r"^##\s+Summary\s*$", line, re.IGNORECASE)),
        None,
    )
    if summary_start is None:
        raise WorkbenchError(f"malformed legacy note {path}: missing Summary section")
    summary_lines = []
    for line in body[summary_start + 1:]:
        if re.match(r"^##\s+", line):
            break
        summary_lines.append(line)
    summary = "\n".join(summary_lines).strip()
    if not summary:
        raise WorkbenchError(f"malformed legacy note {path}: blank Summary section")
    return {
        "id": f"legacy:{metadata['id']}",
        "kind": "question",
        "title": title,
        "summary": f"{summary}\n\n{WARNING}",
        "status": "proposed",
        "facets": {"layer": [metadata["layer"]], "domain": [metadata["domain"]]},
        "provenance": {
            "old_id": metadata["id"],
            "path": path.relative_to(vault_path).as_posix(),
            "sha256": hashlib.sha256(raw).hexdigest(),
        },
    }


def import_vault(store, vault_path):
    """Parse every Nodes/**/*.md file before atomically importing the batch."""
    vault_path = Path(vault_path)
    nodes_path = vault_path / "Nodes"
    if not nodes_path.is_dir():
        raise WorkbenchError(f"legacy vault has no Nodes directory: {vault_path}")
    paths = sorted(path for path in nodes_path.rglob("*.md") if path.is_file())
    try:
        items = [_parse_note(path, vault_path) for path in paths]
    except OSError as exc:
        raise WorkbenchError(f"cannot read legacy vault: {exc}") from exc
    return store.import_bundle({
        "schema_version": 1,
        "title": f"Legacy import: {vault_path.name}",
        "sources": [],
        "items": items,
        "relations": [],
    })
