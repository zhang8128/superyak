"""Bounded, read-only source adapters. Category influence remains disabled."""

from __future__ import annotations

import json
import hashlib
from pathlib import Path
import re
import sqlite3
import time

from context_compile import Candidate


class EngramSource:
    """A dependency-light lexical adapter, explicitly distinct from rich recall.

    It reads bounded recent rows and a small core sample; it does not initialize
    Storage, load an embedding model, run maintenance, or reinforce selections.
    """

    mode = "sqlite_lexical"

    def __init__(self, path: str | Path, *, scan_limit=256, timeout=0.2):
        self.path = Path(path).resolve()
        self.scan_limit = max(1, min(int(scan_limit), 1024))
        self.timeout = min(max(float(timeout), 0.01), 2.0)

    def search(self, query: str, limit=8):
        if not self.path.is_file():
            return []
        terms = set(re.findall(r"[^\W_]+", query[:2000].casefold()))
        deadline = time.monotonic() + self.timeout
        results = []
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=self.timeout)
        try:
            conn.execute("PRAGMA query_only=ON")
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
            for table, layer, field in (("episodes", "episode", "content"), ("semantics", "semantic", "content"), ("instincts", "instinct", "action")):
                columns = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
                if not {"id", field}.issubset(columns):
                    continue
                rows = list(conn.execute(f"SELECT id,substr({field},1,8192) FROM {table} ORDER BY rowid DESC LIMIT ?", (self.scan_limit,)))
                if table == "episodes" and "core" in columns:
                    rows += list(conn.execute("SELECT id,substr(content,1,8192) FROM episodes WHERE core=1 ORDER BY rowid DESC LIMIT 16"))
                for eid, content in dict(rows).items():
                    if not isinstance(content, str):
                        continue
                    words = set(re.findall(r"[^\W_]+", content.casefold()))
                    overlap = len(terms & words)
                    if overlap or layer == "instinct":
                        evidence = self._evidence(layer, content)
                        version = hashlib.sha256(evidence.encode()).hexdigest()
                        results.append(Candidate(f"engram:{layer}:{eid}", "user", (evidence,), score=float(overlap), reason="Engram source account", version=version))
        except sqlite3.OperationalError:
            # A deadline/schema mismatch gives incomplete coverage, never a write.
            pass
        finally:
            conn.close()
        return sorted(results, key=lambda c: (-c.score, c.id))[:max(0, min(int(limit), 32))]

    def _evidence(self, layer, content):
        return json.dumps({"source": str(self.path), "layer": layer, "retrieval": self.mode, "account": content}, ensure_ascii=False)

    def valid(self, candidate):
        first = self.read(candidate.id, offset=0, limit=4096)
        second = self.read(candidate.id, offset=4096, limit=4096)
        if first is None or second is None:
            return False
        evidence = self._evidence(first["layer"], first["text"] + second["text"])
        return hashlib.sha256(evidence.encode()).hexdigest() == candidate.version

    def read(self, source_id, *, offset=0, limit=4096):
        if type(offset) is not int or offset < 0 or type(limit) is not int or not 1 <= limit <= 4096:
            raise ValueError("Invalid source page")
        parts = source_id.split(":", 2)
        tables = {"episode": ("episodes", "content"), "semantic": ("semantics", "content"), "instinct": ("instincts", "action")}
        if len(parts) != 3 or parts[0] != "engram" or parts[1] not in tables or not self.path.is_file():
            return None
        table, field = tables[parts[1]]
        conn = sqlite3.connect(self.path.as_uri() + "?mode=ro", uri=True, timeout=self.timeout)
        try:
            deadline = time.monotonic() + self.timeout
            conn.set_progress_handler(lambda: int(time.monotonic() >= deadline), 100)
            row = conn.execute(f"SELECT substr({field},?,?),length({field}) FROM {table} WHERE id=?", (offset+1, limit, parts[2])).fetchone()
            return {"id": source_id, "layer": parts[1], "source": str(self.path), "text": row[0], "next_offset": offset+limit if offset+limit < row[1] else None} if row else None
        except sqlite3.OperationalError:
            return None
        finally:
            conn.close()
