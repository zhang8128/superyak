"""Ledgers written by SQL for the small-hardware memory tests (SH-1, SH-2). For memory tests only: the rows are
plausible in shape but not made by `Ledger.perform`, and the hash chain is not real. Behavior tests write
through `Ledger.perform` or `Ledger._append`."""
import json
import sqlite3

from permission_ledger import Ledger, _parts_text, ledger_path, projection_now

OWNER = "person:andy"
HOME = "place:home/andy"


def restamp_projection(home):
    """`meta.projection` and `projection_parts` set to the tables as they are now, at the log's last seq, after a
    fixture wrote rows by its own SQL: the stamp a writer would have kept had it made them (the projection digest
    plan, Task 6). For fixtures only: on a real ledger this would bless whatever tear it holds (D5). A ledger that
    keeps no digest is left as it is."""
    conn = sqlite3.connect(ledger_path(home), isolation_level=None)
    try:
        conn.execute("BEGIN IMMEDIATE")
        if conn.execute("SELECT 1 FROM meta WHERE key = 'projection_parts'").fetchone() is not None:
            whole, parts = projection_now(conn)
            top = conn.execute("SELECT COALESCE(MAX(seq), 0) FROM ledger_log").fetchone()[0]
            conn.executemany("INSERT INTO meta VALUES(?,?) ON CONFLICT(key) DO UPDATE SET value=excluded.value",
                             [("projection", f"{top}:{whole}"), ("projection_parts", _parts_text(parts))])
        conn.execute("COMMIT")
    finally:
        conn.close()


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
    restamp_projection(home)
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
    restamp_projection(home)


# ---------------------------------------------------------------- the projection digest's budgets (its plan's D9, Task 6)

DIGEST_MEMORIES, DIGEST_RECORDS = 20_000, 16_384     # D9's shape: Task 0's, 236,389 rows and 28.7 MB


def digest_shape(home):
    """D9's ledger under `home`: Task 0's shape, written by SQL and restamped."""
    synthetic_ledger(home, DIGEST_MEMORIES, records=True)
    add_records_by_sql(home, DIGEST_RECORDS - 1)
    return ledger_path(home)


def _median(times):
    times = sorted(times)
    return times[len(times) // 2]


def digest_timings(home, *, runs=5, appends=41):
    """D9's timings, in seconds, on the ledger under `home` (`digest_shape`), each a median:
    - "rare": state() with the full check, as a reader with no memo and no marker match runs it (its 50 ms re-read
      included);
    - "match": what a state() served by this process's memo spends in the key protocol: the key reads, the memo,
      the late connections' checks and the descriptor count (a difference of two 0.35 s state()s can't show 2 ms);
    - "append": an append's time less the same append on a copy made before the digest (version 1, which keeps no
      digest and no key), the two taken in turn, the median of those differences; both with synchronous=OFF so the
      disk's fsync is left out.
    Makes that copy beside `home`."""
    import shutil
    import time

    import permission_ledger
    from permission_ledger import Ledger
    old = home.parent / (home.name + "-unstamped")
    (old / ".engram").mkdir(parents=True, exist_ok=True)
    shutil.copyfile(ledger_path(home), ledger_path(old))
    conn = sqlite3.connect(ledger_path(old), isolation_level=None)
    conn.execute("UPDATE meta SET value = '1' WHERE key = 'schema_version'")
    conn.execute("DELETE FROM meta WHERE key IN ('projection', 'projection_parts')")
    conn.close()

    def one_state(where):
        led = Ledger.open_read_only(where)
        try:
            led.state()
        finally:
            led.close()

    rare = []
    real_marker = permission_ledger._read_marker
    permission_ledger._read_marker = lambda path: None
    try:
        for _ in range(runs):
            permission_ledger._forget_verified()
            start = time.perf_counter()
            one_state(home)
            rare.append(time.perf_counter() - start)
    finally:
        permission_ledger._read_marker = real_marker

    spent, wrapped = [0.0], []

    def timed(owner, name):
        real = getattr(owner, name)

        def run(*args, **kwargs):
            start = time.perf_counter()
            try:
                return real(*args, **kwargs)
            finally:
                spent[0] += time.perf_counter() - start
        wrapped.append((owner, name, real))
        setattr(owner, name, run)

    for owner, name in ((Ledger, "_read_key"), (Ledger, "_verify"), (Ledger, "_check_late"),
                        (permission_ledger, "_hold"), (permission_ledger, "_release")):
        timed(owner, name)
    match = []
    try:
        one_state(home)                              # the memo now holds the key
        for _ in range(runs * 4):
            spent[0] = 0.0
            one_state(home)
            match.append(spent[0])
    finally:
        for owner, name, real in wrapped:
            setattr(owner, name, real)

    def append_s(led, i):
        start = time.perf_counter()
        led._append("note", f"n{i}", OWNER, "terminal", {"insert": [{"table": "lane_notes", "row": {
            "object": f"mem:S/episode/m{i}", "lane": "work", "at": 2_000_000 + i, "seq": "@seq"}}]}, at=2_000_000 + i)
        return time.perf_counter() - start

    # the two ledgers' appends in turn, and the median of the paired differences: two medians taken one ledger after
    # the other flaked on a loaded Pi (the section 2 review's S5)
    stamped, unstamped = Ledger.open(home), Ledger.open(old)
    try:
        for led in (stamped, unstamped):
            led.conn.execute("PRAGMA synchronous=OFF")
        paired = [append_s(stamped, i) - append_s(unstamped, i) for i in range(appends)]
    finally:
        stamped.close()
        unstamped.close()
    return {"rare": _median(rare), "match": _median(match), "append": _median(paired)}
