"""What the owner's machine knows of the copies held at the station (store-copy spec I 12, "In the owner's own use
list"). Standard library only: ``permission_cli`` imports this and must never load ``imprint``, ``calibrate`` or
numpy. It reads ``verified.json`` and the saved receipts under ``<home>/imprints/<imprint id>/``."""
from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

STATION_NAME = "Deep Space 9"


def _json(path: Path):
    try:
        return json.loads(path.read_text())
    except (OSError, ValueError):
        return None


def saved_receipts(folder: Path) -> list[dict]:
    """The receipts the agent saved under ``folder/receipts``, in seq order; an unreadable file is skipped."""
    found = {}
    for path in (folder / "receipts").glob("*.json"):
        doc = _json(path)
        if isinstance(doc, dict) and type(doc.get("seq")) is int and isinstance(doc.get("record"), dict):
            found[doc["seq"]] = doc
    return [found[seq] for seq in sorted(found)]


def verified_ids(folder: Path) -> set[str]:
    doc = _json(folder / "verified.json")
    ids = doc.get("verified") if isinstance(doc, dict) else None
    return {i for i in ids if isinstance(i, str)} if isinstance(ids, list) else set()


def copies_held(home: Path) -> list[dict]:
    """One entry per imprint kept under ``home/imprints``: ``line`` says the copy is held, deletion not confirmed,
    until a verified ``deleted`` receipt, then the deletion's date and the receipt's short id."""
    root = Path(home) / "imprints"
    out = []
    try:
        folders = sorted(p for p in root.iterdir() if p.is_dir() and not p.name.startswith("."))
    except OSError:
        return out
    for folder in folders:
        if not any((folder / name).exists() for name in ("permission.json", "verified.json", "receipts")):
            continue
        short = folder.name[:4]
        verified = verified_ids(folder)
        deleted = [r for r in saved_receipts(folder)
                   if r["record"].get("event") == "deleted" and r["record"].get("id") in verified]
        entry = {"imprint_id": folder.name, "deleted": bool(deleted)}
        if deleted:
            record = deleted[-1]["record"]
            at = record.get("at")
            day = datetime.fromtimestamp(at, timezone.utc).strftime("%Y-%m-%d") if type(at) is int else "an unknown day"
            entry.update(receipt=str(record["id"])[:8], deleted_at=at,
                         line=f"copy at {STATION_NAME} (imprint {short}) deleted on {day}, receipt {str(record['id'])[:8]}")
        else:
            entry["line"] = f"copy held at {STATION_NAME} (imprint {short}), deletion not confirmed"
        out.append(entry)
    return out
