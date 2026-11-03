"""Task 0 of the projection digest plan (docs/superpowers/plans/2026-11-03-projection-digest.md): measure, before
building anything, what a full projection check would cost at the records bound. Read-only on a ledger it builds in a
fresh temporary directory; it never touches ~/.engram.

    cd engram && .venv/bin/python -I scripts/projection_digest_timing.py [--memories 20000] [--records 16384]

Prints one JSON object: the ledger's size and row counts, and the median of 5 runs each of
  - state_s:      Ledger.open_read_only + state(), as every caller pays today;
  - scan_hash_s:  a NOT INDEXED scan of every projected table, hashing each row (BLAKE2b-256 of the plan's D2 tagged
                  encoding), summing per table mod 2**256: the reader's full recompute (D4);
  - integrity_s:  PRAGMA integrity_check, which catches a torn index page.
"""
import argparse
import hashlib
import json
import os
import sqlite3
import statistics
import sys
import tempfile
import time
from pathlib import Path

ENGRAM = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ENGRAM))

from lighthouse_protocol import canonical_json  # noqa: E402
from permission_ledger import Ledger, ledger_path  # noqa: E402
from permissions import _COLUMNS  # noqa: E402
from tests.permissions_memory_support import add_records_by_sql, synthetic_ledger  # noqa: E402

MOD = 2 ** 256


def plain(value):
    return {"hex": value.hex()} if isinstance(value, (bytes, bytearray, memoryview)) else value


def encode(table: str, row) -> bytes:
    """The plan's D2 row encoding: the table name, then each value as a type tag, a length and its bytes."""
    out = [b"t", str(len(table)).encode(), b":", table.encode()]
    for value in row:
        if value is None:
            out.append(b"n")
        elif isinstance(value, int):
            raw = str(value).encode()
            out += [b"i", str(len(raw)).encode(), b":", raw]
        elif isinstance(value, str):
            raw = value.encode()
            out += [b"s", str(len(raw)).encode(), b":", raw]
        elif isinstance(value, (bytes, bytearray, memoryview)):
            raw = bytes(value)
            out += [b"b", str(len(raw)).encode(), b":", raw]
        else:
            raw = repr(value).encode()
            out += [b"r", str(len(raw)).encode(), b":", raw]
    return b"".join(out)


def scan_hash(path: Path) -> dict:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        parts = {}
        for table, columns in _COLUMNS.items():
            total, count = 0, 0
            cols = ", ".join(columns)
            for row in conn.execute(f"SELECT {cols} FROM {table} NOT INDEXED"):
                digest = hashlib.blake2b(encode(table, row), digest_size=32).digest()
                total = (total + int.from_bytes(digest, "big")) % MOD
                count += 1
            parts[table] = (count, total)
        return parts
    finally:
        conn.close()


def scan_hash_canonical(path: Path) -> None:
    """Revision 1's encoding (canonical JSON, SHA-256), kept to show why D2 changed."""
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        for table, columns in _COLUMNS.items():
            for row in conn.execute(f"SELECT {', '.join(columns)} FROM {table} NOT INDEXED"):
                hashlib.sha256(canonical_json([table, [plain(v) for v in row]]).encode()).digest()
    finally:
        conn.close()


def integrity(path: Path) -> str:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return conn.execute("PRAGMA integrity_check").fetchone()[0]
    finally:
        conn.close()


def state_once(home: Path) -> None:
    led = Ledger.open_read_only(home)
    try:
        led.state()
    finally:
        led.close()


def timed(fn, runs: int) -> float:
    times = []
    for _ in range(runs):
        start = time.perf_counter()
        fn()
        times.append(time.perf_counter() - start)
    return statistics.median(times)


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--memories", type=int, default=20_000)
    parser.add_argument("--records", type=int, default=16_384)
    parser.add_argument("--runs", type=int, default=5)
    args = parser.parse_args()
    with tempfile.TemporaryDirectory(prefix="projection-digest-") as tmp:
        home = Path(tmp)
        synthetic_ledger(home, args.memories, records=True)
        if args.records > 1:
            add_records_by_sql(home, args.records - 1)
        path = ledger_path(home)
        counts = {t: c for t, (c, _) in scan_hash(path).items()}
        state_ok = True
        try:
            state_s = timed(lambda: state_once(home), args.runs)
        except Exception as error:  # a synthetic ledger may not satisfy every state() check; report, don't hide
            state_ok, state_s = f"{type(error).__name__}: {error}"[:200], None
        result = {
            "host": os.uname().nodename,
            "machine": os.uname().machine,
            "ledger_bytes": path.stat().st_size,
            "rows": counts,
            "rows_total": sum(counts.values()),
            "state_s": state_s,
            "state_ok": state_ok,
            "scan_hash_s": timed(lambda: scan_hash(path), args.runs),
            "scan_hash_canonical_s": timed(lambda: scan_hash_canonical(path), max(1, args.runs // 2)),
            "integrity_s": timed(lambda: integrity(path), args.runs),
            "integrity": integrity(path),
            "runs": args.runs,
        }
    print(json.dumps(result, indent=2))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
