"""The reference ledger of U24's memory checks, and the files beside it (Task 31; spec 15).

The ledger is `generated_world_parts` with 100,000 memories, written by SQL: building it through acts would take
hours (one `state()` per act). Its tables are the World's; its log is a true hash chain of the right length whose
rows are empty but for one `collect` of 10,000 members, so `check`, `verify` and `rebuild` read a real chain. For
memory tests only: the log does not say how the tables came to be."""
import json
import sqlite3

from lighthouse_protocol import canonical_json
from permission_ledger import ZERO, Ledger, _digest, ledger_path
from permissions import _COLUMNS, selector_json
from tests.permissions_budget_core import (ALL, COLLECTIONS, JOINT, LEFT, OWNER, REQUESTER_CHAIN, RIGHT, budget_refs)

LEDGER_ID = "reference-ledger"
LOG_ROWS = 811_000              # spec 15: "about 811,000" rows wrote the reference ledger
RECEIVERS = tuple(f"rcv{k}" for k in range(7))
OLD_RECEIPT = 1_700_000_000     # 2023-11-14, far older than the fold's 400 days


def _extend(w, universe, tail):
    """The reference's own parts on top of the generated world: a collection of every memory (its last `tail` in
    a `collect` act of their own), a joint place whose parents' layers allow that collection, and the receivers
    the daemon serves."""
    refs = budget_refs(universe)
    w._add("collections", id=ALL, owner=OWNER, created_seq=w._bump())
    w.collect(ALL, refs[:universe - tail])
    w.collect(ALL, refs[universe - tail:])
    collect_seq = w.seq
    for p in (LEFT, RIGHT):
        w.place(p, stewards=["andy"])
    w.place(JOINT, parents=[LEFT, RIGHT], stewards=["andy"])
    w.allow(LEFT, audience=["commons"], collections=[ALL], actions=["recall"], purposes=["care-coordination"])
    w.allow(RIGHT, audience=["commons"], collections=[ALL])
    for name in RECEIVERS:
        w.agent(name, REQUESTER_CHAIN[0], at="place:req-15")
    return collect_seq


def _cell(table, col, row):
    v = row.get(col)
    if table == "records" and col == "selector":
        return selector_json(v)
    if table == "permission_grants" and col in ("ops", "envelope") and not isinstance(v, str):
        return canonical_json(v if col == "ops" else v)
    return v


def build_reference(home, *, universe=100_000, log_rows=LOG_ROWS, tail=10_000):
    """Write the reference ledger under `home`. Returns (the ledger path, the seq of the `collect` act of the
    last `tail` memories of ALL)."""
    from tests.permissions_support import generated_world_parts
    w, _ = generated_world_parts(0, 43, 256, universe=universe, trails=universe)
    tail = min(tail, universe // 10)
    collect_seq = _extend(w, universe, tail)
    led = Ledger._blank(home, LEDGER_ID)
    conn = led.conn
    conn.execute("BEGIN")
    conn.executemany("INSERT INTO meta VALUES(?,?)", [("owner", OWNER), ("admins", OWNER)])
    for table, cols in _COLUMNS.items():
        rows = w.rows.get(table, [])
        conn.executemany(f"INSERT INTO {table}({', '.join(cols)}) VALUES({', '.join('?' * len(cols))})",
                         ([_cell(table, c, r) for c in cols] for r in rows))
    total = max(log_rows, w.seq)
    refs = budget_refs(universe)
    members = [{"table": "collection_members",
                "row": {"collection": ALL, "object": r, "backing": "person", "added_seq": "@seq", "added_by": OWNER}}
               for r in refs[universe - tail:]]
    prev = ZERO

    def rows():
        nonlocal prev
        for seq in range(1, total + 1):
            at = w.seq_at.get(seq, w.start)
            kind, ref, body = (("collect", ALL, canonical_json({"insert": members})) if seq == collect_seq
                               else ("filler", "none", "{}"))
            entry = {"seq": seq, "at": at, "kind": kind, "ref": ref, "actor": OWNER, "channel": "terminal",
                     "under_grant": None, "proposal_id": None, "body": body}
            digest = _digest(prev, entry)
            yield (seq, at, kind, ref, OWNER, "terminal", None, None, body, prev, digest)
            prev = digest

    conn.executemany("INSERT INTO ledger_log VALUES(?,?,?,?,?,?,?,?,?,?,?)", rows())
    conn.execute("COMMIT")
    led.close()
    return ledger_path(home), collect_seq


def add_revoked_records(home, count):
    """`count` more record rows, each a copy of a passing allow of the requester's restriction layer, revoked."""
    conn = sqlite3.connect(ledger_path(home), isolation_level=None)
    try:
        conn.execute("BEGIN")
        have = conn.execute("SELECT COUNT(*) FROM records").fetchone()[0]
        seq = conn.execute("SELECT MAX(seq) FROM ledger_log").fetchone()[0]
        cols = [r[1] for r in conn.execute("PRAGMA table_info(records)")]
        first = list(conn.execute("SELECT * FROM records ORDER BY rowid LIMIT 1").fetchone())
        i_id, i_rev, i_by, i_why, i_seq = (cols.index(c) for c in ("id", "revoked", "revoked_by", "revoke_reason",
                                                                   "revoked_seq"))
        first[i_rev], first[i_by], first[i_why], first[i_seq] = 1_700_000_000, OWNER, "budget", seq
        conn.executemany(f"INSERT INTO records VALUES({','.join('?' * len(cols))})",
                         ([*first[:i_id], f"r-{have + i + 7000:032x}", *first[i_id + 1:]] for i in range(count)))
        conn.execute("COMMIT")
    finally:
        conn.close()


def detach_last_collect(home, tail):
    """The ledger under `home` with the last `tail` members of ALL taken out of the table, and their refs: the
    collection holds 90,000 and a `collect` act of the 10,000 puts them back."""
    conn = sqlite3.connect(ledger_path(home), isolation_level=None)
    try:
        refs = [r[0] for r in conn.execute(
            "SELECT object FROM collection_members WHERE collection=? ORDER BY rowid DESC LIMIT ?", (ALL, tail))]
        conn.execute("BEGIN")
        conn.executemany("DELETE FROM collection_members WHERE collection=? AND object=?",
                         ((ALL, r) for r in refs))
        conn.execute("COMMIT")
        return sorted(refs)
    finally:
        conn.close()


# ---------------------------------------------------------------- the receipts file (fold, uses)

def _cited(layers, marker):
    return canonical_json([{"layer": l, "kind": "consent", "action": "recall", "verdict": "allow",
                            "record": f"r-{marker:032x}", "version": 1} for l in layers])


def build_receipts(home, layers, *, count=100_000, bulk=64, objects=512, subjects=8, refs_each=20, at=OLD_RECEIPT):
    """The receipts file under `home`, written by SQL with a true chain: `count` receipts, each a recall that cites
    every layer in `layers` and returns `refs_each` refs with `subjects` subjects each; the first `bulk` are named
    bulk receipts of `objects` objects with `subjects` subjects each, citing 256 records in each of 40 layers
    for 3 actions (spec 9.1, 15)."""
    from permission_uses import Uses, _COLUMNS as USE_COLUMNS
    from permission_uses import _digest as use_digest
    uses = Uses.open(home)
    conn = uses.conn
    refs = budget_refs(max(objects, refs_each))
    who = [f"person:{'andy' if k == 0 else f'co{k}'}" for k in range(subjects)]
    cited_recall = _cited(layers, 1)
    cited_bulk = canonical_json([{"layer": l, "kind": "consent", "action": a, "verdict": "allow",
                                  "records": [f"r-{(i * 256 + j):032x}" for j in range(256)], "version": 1}
                                 for i, l in enumerate(layers[:40]) for a in ("recall", "read", "imprint")])
    bulk_pairs = sorted([s, o] for s in who for o in refs[:objects])
    bulk_returned = canonical_json({"count": objects, "sha256": "0" * 64})
    prev = ZERO
    conn.execute("BEGIN IMMEDIATE")
    for i in range(1, count + 1):
        is_bulk = i <= bulk
        if is_bulk:
            pairs, returned, cited, action, obj = bulk_pairs, bulk_returned, cited_bulk, "imprint", None
        else:
            picked = [refs[(i * 7 + j) % len(refs)] for j in range(refs_each)]
            pairs = sorted([s, o] for s in who for o in picked)
            returned, cited, action, obj = canonical_json(sorted(picked)), cited_recall, "recall", None
        row = {"seq": i, "id": f"u-{i:032x}", "at": at + i, "ledger_id": LEDGER_ID, "ledger_seq": 1,
               "agent": "agent:rcv0", "place": "place:req-15", "acting_for": "place:home/andy", "session_label": None,
               "action": action, "purpose": "care-coordination", "object": obj, "copy": "store:HOUSE", "allowed": 1,
               "cited": cited, "refusal": None, "until": None, "horizon": None, "returned": returned,
               "filtered": 0 if not is_bulk else None, "content_digest": None, "shadow": 0}
        digest = use_digest(prev, {"seq": i, **{c: row[c] for c in USE_COLUMNS}, "subjects": pairs})
        conn.execute(f"INSERT INTO uses({', '.join(row)}, prev_digest, digest) VALUES({','.join('?' * (len(row) + 2))})",
                     (*row.values(), prev, digest))
        conn.executemany("INSERT INTO use_subjects VALUES(?,?,?)", ((i, s, o) for s, o in pairs))
        prev = digest
    conn.execute("COMMIT")
    uses.close()


# ---------------------------------------------------------------- the files the daemon and migrate read

def build_daemon_house(home, placements, receivers):
    """House `why` of `placements` placed memories (mem:S/episode/m0 on), each an episode with its embedding; a
    policy that lets every receiver recall and read; the receivers' own settings; and the ledger's gate raised to
    `enforce`. The ledger is under `home` already."""
    from permission_ledger import Ledger
    from tests.permissions_support import (ANDY, HOUSE_NAME, PURPOSES, T, connection_policy, do, make_house,
                                           make_placed_house, raise_gate, write_receiver_files)
    make_placed_house(home, receiver=RECEIVERS[0], ns=range(placements))
    urns = [f"urn:engram:{r}" for r in RECEIVERS[:receivers]]
    inst = home / ".engram" / "instances" / HOUSE_NAME
    (inst / "lighthouse-policy.json").write_text(json.dumps(connection_policy(
        HOUSE_NAME, urns, actions=("recall", "read"), purposes=PURPOSES, audience_map={u: ["commons"] for u in urns})))
    for r in RECEIVERS[:receivers]:
        write_receiver_files(home, r)
    make_house(home, "lighthouse")
    led = Ledger.open(home)
    try:
        raise_gate(led, "enforce")
    finally:
        led.close()


def build_migrate_home(home, shares):
    """A home with no ledger: the default store holding `shares` episodes, and the published house with a share
    row for each (migration 029 not yet run on it is not needed: `Storage` runs it)."""
    from lighthouse_protocol import content_digest
    from storage import Storage
    from tests.permissions_support import house_dir
    default = Storage(str(home / ".engram" / "graph.db"))
    default.conn.execute("UPDATE meta SET value = 'S' WHERE key = 'instance_id'")
    rows = []
    for i in range(shares):
        text = f"note {i}: a thing worth sharing"
        default.add_episode(id=f"m{i}", session_id=None, content=text, lane="personal")
        rows.append((f"share-{i}", f"pub-{i}", "default", f"m{i}", "episode", "commons", "budget",
                     content_digest(text)["value"], "2026-10-02"))
    default.conn.execute("UPDATE episodes SET created_at = '2026-10-01T00:00:00+00:00'")
    default.conn.commit()
    default.close()
    house_dir(home, "lighthouse")
    published = Storage(str(home / ".engram" / "instances" / "lighthouse" / "graph.db"))
    published.conn.executemany(
        "INSERT INTO shared_memories (share_id, memory_id, source_instance, source_id, layer, audience, reason, "
        "content_digest, shared_at) VALUES (?,?,?,?,?,?,?,?,?)", rows)
    published.conn.commit()
    published.close()


# ---------------------------------------------------------------- the reference, and a copy of it per operation

def ensure_reference(base, *, universe=100_000, log_rows=LOG_ROWS, tail=10_000, placements=20_000, receivers=7,
                     receipts=100_000, bulk=64, shares=20_000, stages=("ref", "house", "receipts")):
    """`base/ref` (ledger, then house and receivers) and `base/receipts` (the receipts file, with a link to the
    ledger), each stage built once: a file `READY-<stage>` says it is, so a build that was cut short resumes at
    the stage it stopped in."""
    import os
    import shutil
    from pathlib import Path
    from tests.permissions_support import LEDGER_LAYERS
    base = Path(base)
    ref, rec = base / "ref", base / "receipts"

    def stage(name, build):
        marker = base / f"READY-{name}"
        if name in stages and not marker.exists():
            build()
            marker.write_text("ready\n")

    def make_ref():
        shutil.rmtree(ref, ignore_errors=True)
        build_reference(ref, universe=universe, log_rows=log_rows, tail=tail)

    def make_house():
        shutil.rmtree(ref / ".engram" / "instances", ignore_errors=True)
        build_daemon_house(ref, placements, receivers)

    def make_receipts():
        shutil.rmtree(rec, ignore_errors=True)
        (rec / ".engram").mkdir(parents=True)
        build_receipts(rec, LEDGER_LAYERS, count=receipts, bulk=bulk, objects=min(512, universe))
        os.symlink(ref / ".engram" / "permissions.db", rec / ".engram" / "permissions.db")

    stage("ref", make_ref)
    stage("house", make_house)
    stage("receipts", make_receipts)
    return base


def prepare(base, op, *, universe=100_000, tail=10_000, placements=20_000, receivers=7, trails=100_000,
            touches=512, shares=20_000, revoked=0, **_ignored):
    """(the home `op` runs on, its extra arguments). An operation that writes runs on a copy made now."""
    import os
    import shutil
    from pathlib import Path
    base = Path(base)
    work = base / "work" / f"{op}{'-' + str(revoked) if revoked else ''}"
    shutil.rmtree(work, ignore_errors=True)
    args = ["--universe", str(universe), "--tail", str(tail), "--placements", str(placements),
            "--receivers", str(receivers), "--trails", str(trails), "--touches", str(touches)]
    ref_db = base / "ref" / ".engram" / "permissions.db"
    if op in ("state", "eligible", "bulk", "check", "rebuild") or (op == "daemon" and not revoked):
        if op == "rebuild":
            shutil.rmtree(base / "ref" / "rebuilt-ref", ignore_errors=True)
        return base / "ref", args
    if op in ("uses-owner", "uses-place"):
        return base / "receipts", args
    (work / ".engram").mkdir(parents=True)
    if op == "fold":
        shutil.copy(base / "receipts" / ".engram" / "permission-uses.db", work / ".engram")
    elif op in ("perform-allow", "perform-collect", "daemon"):
        shutil.copy(ref_db, work / ".engram" / "permissions.db")
        if op == "perform-collect":
            detach_last_collect(work, min(tail, universe // 10))
        if op == "daemon":
            os.symlink(base / "ref" / ".engram" / "instances", work / ".engram" / "instances")
            add_revoked_records(work, revoked)
    elif op == "migrate":
        build_migrate_home(work, shares)
    return work, args


def run_probe(op, home, extra=(), *, scope=True, timeout=None):
    """Run the probe in a fresh process, under `systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0`
    unless `scope` is false. Returns its JSON line as a dict; a process that was killed raises."""
    import os
    import subprocess
    import sys
    from pathlib import Path
    cmd = [sys.executable, "-m", "tests.pi_budget_probe", op, str(home), *extra]
    if scope:
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=512M", "-p", "MemorySwapMax=0", *cmd]
    env = {**os.environ, "PYTHONDONTWRITEBYTECODE": "1"}
    cp = subprocess.run(cmd, cwd=Path(__file__).resolve().parent.parent, env=env, capture_output=True, text=True,
                        timeout=timeout)
    if cp.returncode != 0:
        raise RuntimeError(f"{op} exited {cp.returncode}: {cp.stderr[-1500:]}")
    return json.loads(cp.stdout.strip().splitlines()[-1])
