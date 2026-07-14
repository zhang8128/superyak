from __future__ import annotations

import json
import os
from pathlib import Path


def append_jsonl(path: Path, record: dict) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = (json.dumps(record, sort_keys=True, ensure_ascii=False) + "\n").encode()
    with path.open("a+b") as handle:
        handle.seek(0, os.SEEK_END)
        separator = b""
        if handle.tell():
            handle.seek(-1, os.SEEK_END)
            if handle.read(1) != b"\n":
                separator = b"\n"
        handle.write(separator + payload)
        handle.flush()
        os.fsync(handle.fileno())


def read_jsonl(path: Path):
    if not path.exists():
        return
    with path.open("rb") as handle:
        for line in handle:
            try:
                value = json.loads(line.decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError):
                continue
            if isinstance(value, dict):
                yield value


def completed_ids(path: Path) -> set[str]:
    return {
        row["run_id"] for row in read_jsonl(path)
        if row.get("run_id") and row.get("status") in {"completed", "timeout", "failed"}
    }
