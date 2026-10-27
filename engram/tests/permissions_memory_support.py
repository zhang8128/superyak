"""Ledgers written by SQL for the small-hardware memory tests (SH-1, SH-2). For memory tests only: the rows are
plausible in shape but not made by `Ledger.perform`, and the hash chain is not real. Behavior tests write
through `Ledger.perform` or `Ledger._append`."""
import json
import sqlite3

from permission_ledger import Ledger, ledger_path

OWNER = "person:andy"
HOME = "place:home/andy"


def _body(size: int | None, seq: int) -> str:
    """A log body of about `size` bytes (valid JSON), or a small one."""
    if size is None:
        return json.dumps({"n": seq})
    return json.dumps({"pad": "x" * max(size - 10, 0)})


def synthetic_ledger(home, memories, *, records=False, body_bytes=None, log_rows=None, per_object_rows=True):
    """Write a ledger file under `home` by SQL, in the shape `Ledger._blank` makes: Andy, his home place and
    steward row, `memories` collection members, `records` record rows (True is one), and `log_rows` log rows
    (default: as many as the projection rows need, at least 1) of kind `collect` with bodies of `body_bytes`
    bytes (small when None). Log row `s` has time `1_000_000 + s`. With `memories` and `per_object_rows` (SH-2),
    each memory also has 7 subject rows (the owner live, six co-subjects removed at seq 1) and 3 lane notes
    (personal, work, personal), and store S is registered: 20,000 memories hold 140,000 subject rows, 60,000
    lane notes and 20,000 memberships. Returns the ledger file's path."""
    led = Ledger._blank(home, "synthetic-ledger")
    conn = led.conn
    n_records = int(records)
    seqs = max(log_rows if log_rows is not None else 1, 1)
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO meta VALUES(?,?)", [("owner", OWNER), ("admins", OWNER)])
    conn.execute("INSERT INTO persons VALUES(?,?,1,1,NULL)", (OWNER, HOME))
    conn.execute("INSERT INTO places VALUES(?,1,1,NULL,?)", (HOME, bytes(16)))
    conn.execute("INSERT INTO place_stewards VALUES(?,?,1,NULL)", (HOME, OWNER))
    coll = "collection:andy/memories"
    if memories:
        conn.execute("INSERT INTO collections VALUES(?,?,1)", (coll, OWNER))
        conn.executemany(
            "INSERT INTO collection_members VALUES(?,?,'person',1,?,NULL,NULL)",
            ((coll, f"mem:S/episode/m{i}", OWNER) for i in range(memories)))
    if memories and per_object_rows:
        conn.execute("INSERT INTO stores VALUES('S','S',?,?,NULL,1)", (OWNER, HOME))
        conn.executemany(
            "INSERT INTO subjects VALUES(?,?,1,?,0,?,?)",
            ((f"mem:S/episode/m{i}", who, OWNER, None if who == OWNER else 1, None if who == OWNER else OWNER)
             for i in range(memories) for who in (OWNER, *(f"person:co{k}" for k in range(6)))))
        conn.executemany(
            "INSERT INTO lane_notes VALUES(?,?,?,1)",
            ((f"mem:S/episode/m{i}", lane, 1_000_000 + j, ) for i in range(memories)
             for j, lane in enumerate(("personal", "work", "personal"))))
    selector = json.dumps({"audience": ["self"], "requesters": "*",
                           "objects": {"kinds": ["memory"], "stores": "*", "layers": "*", "lanes": "*",
                                       "collections": "*", "memories": "*"},
                           "actions": ["recall"], "purposes": "*"}, sort_keys=True)
    conn.executemany(
        "INSERT INTO records VALUES(?,?,?,?,?,NULL,?,?,?,?,NULL,NULL,NULL,?,?,1,NULL,NULL,NULL,NULL)",
        ((f"r-{i:032x}", HOME, "allow", selector, 1_000_000, 1_000_000, "person", OWNER, "terminal",
          "synthetic", 1_000_000) for i in range(n_records)))
    pad = "0" * 64
    conn.executemany(
        "INSERT INTO ledger_log VALUES(?,?,?,?,?,?,NULL,NULL,?,?,?)",
        ((s, 1_000_000 + s, "collect", coll, OWNER, "terminal", _body(body_bytes, s), pad, pad)
         for s in range(1, seqs + 1)))
    conn.execute("COMMIT")
    led.close()
    return ledger_path(home)


def add_records_by_sql(home, count):
    """Add `count` more record rows to the ledger under `home`, copying its first record's columns."""
    conn = sqlite3.connect(ledger_path(home), isolation_level=None)
    try:
        conn.execute("BEGIN")
        have = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        cols = [r[1] for r in conn.execute("PRAGMA table_info(records)")]
        first = conn.execute("SELECT * FROM records ORDER BY rowid LIMIT 1").fetchone()
        for i in range(count):
            row = list(first)
            row[cols.index("id")] = f"r-{have + i + 1000:032x}"
            conn.execute(f"INSERT INTO records VALUES({','.join('?' * len(cols))})", row)
        conn.execute("COMMIT")
    finally:
        conn.close()
