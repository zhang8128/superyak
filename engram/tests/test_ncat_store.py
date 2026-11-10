"""The n-category store (docs/superpowers/specs/2026-11-07-ncat-store.md): a ship's memory use, kept as cells."""
from __future__ import annotations

import json
import os
import sqlite3
import stat
import subprocess
import sys
import time
from pathlib import Path

import pytest

import ncat_store

ENGRAM = Path(__file__).resolve().parent.parent


def _engram(path: Path, memories=("a", "b", "c", "d")) -> Path:
    """The few columns the store reads, in a scratch store: never a live one."""
    db = sqlite3.connect(path)
    db.executescript("""
        CREATE TABLE episodes (id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE semantics (id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE instincts (id TEXT PRIMARY KEY, content TEXT);
        CREATE TABLE memory_log (id TEXT PRIMARY KEY, timestamp TEXT NOT NULL, event_type TEXT NOT NULL,
                                 layer TEXT NOT NULL, target_ids JSON, context JSON, outcome TEXT);
    """)
    for m in memories:
        db.execute("INSERT INTO episodes VALUES (?, ?)", (m, f"private words of {m}"))
    db.commit()
    db.close()
    return path


def _recall(path, row_id, when, session, targets, used=True, raw_context=None, raw_targets=None):
    db = sqlite3.connect(path)
    context = raw_context if raw_context is not None else json.dumps({"session_id": session, "recall_id": f"r-{row_id}"})
    target = raw_targets if raw_targets is not None else json.dumps(list(targets))
    db.execute("INSERT INTO memory_log VALUES (?, ?, 'recall', 'episode', ?, ?, ?)",
               (row_id, when, target, context, "used: helped" if used else None))
    db.commit()
    db.close()


def _rebuild(tmp_path, engram):
    return ncat_store.rebuild(engram, tmp_path / "ncat.db")


def _keys(store_path):
    with ncat_store.open_store(store_path) as store:
        return {sid: store.session(sid).key() for sid in store.session_ids()}


def test_a_session_is_the_composite_of_its_roads_and_order_matters(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s1", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s1", ["b"])
    _recall(engram, "3", "2026-11-07T10:02:00+00:00", "s1", ["a"])
    _recall(engram, "4", "2026-11-07T10:00:00+00:00", "s2", ["b"])
    _recall(engram, "5", "2026-11-07T10:01:00+00:00", "s2", ["a"])
    _recall(engram, "6", "2026-11-07T10:02:00+00:00", "s2", ["b"])
    report = _rebuild(tmp_path, engram)
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        s1, s2 = store.session("s1"), store.session("s2")
        assert s1.dim == 1 and s2.dim == 1
        assert s1 != s2  # a→b→a and b→a→b
        assert store.roads() == {("a", "b"): 2, ("b", "a"): 2}
    assert report["sessions"] == 2


def test_a_memory_used_again_is_a_loop_road_walked_once_per_use(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    for i in range(3):
        _recall(engram, str(i), f"2026-11-07T10:0{i}:00+00:00", "s", ["a"])
    _rebuild(tmp_path, engram)
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {("a", "a"): 2}
        assert store.session("s").size > 0


def test_a_repeat_inside_one_recall_makes_no_loop(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a", "a", "b"])
    report = _rebuild(tmp_path, engram)
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {("a", "b"): 1}


def test_a_session_of_one_memory_is_its_identity(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["c"])
    _rebuild(tmp_path, engram)
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        cell = store.session("s")
        assert cell == store.memory("c").identity()


def test_the_same_rows_in_another_order_give_the_same_keys(tmp_path):
    rows = [("1", "2026-11-07T10:00:00+00:00", "s1", ["a"]), ("2", "2026-11-07T10:01:00+00:00", "s1", ["b", "c"]),
            ("3", "2026-11-07T10:00:00+00:00", "s2", ["c"]), ("4", "2026-11-07T10:05:00+00:00", "s2", ["d", "a"])]
    one, two = tmp_path / "one", tmp_path / "two"
    one.mkdir(); two.mkdir()
    e1, e2 = _engram(one / "graph.db"), _engram(two / "graph.db")
    for row in rows:
        _recall(e1, *row)
    for row in reversed(rows):
        _recall(e2, *row)
    ncat_store.rebuild(e1, one / "ncat.db")
    ncat_store.rebuild(e2, two / "ncat.db")
    assert _keys(one / "ncat.db") == _keys(two / "ncat.db")


def test_order_is_by_parsed_time_not_the_string(tmp_path):
    """10:00 at +02:00 is 08:00 UTC, before 09:00 UTC, though its string sorts after it."""
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T09:00:00+00:00", "s", ["b"])
    _recall(engram, "2", "2026-11-07T10:00:00+02:00", "s", ["a"])
    _rebuild(tmp_path, engram)
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {("a", "b"): 1}


def test_a_naive_timestamp_is_utc_and_counted(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T09:00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T09:30:00+00:00", "s", ["b"])
    report = _rebuild(tmp_path, engram)
    assert report["naive_time"] == 1
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {("a", "b"): 1}


def test_unused_rows_and_bad_rows_are_skipped_and_counted(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b"], used=False)
    _recall(engram, "3", "2026-11-07T10:02:00+00:00", "s", ["c"], raw_context="not json")
    _recall(engram, "4", "2026-11-07T10:03:00+00:00", None, ["c"])
    _recall(engram, "5", "never", "s", ["c"])
    _recall(engram, "6", "2026-11-07T10:05:00+00:00", "s", [], raw_targets=json.dumps([1, 2]))
    _recall(engram, "7", "2026-11-07T10:06:00+00:00", "s", ["d", "gone"])
    report = _rebuild(tmp_path, engram)
    skipped = report["skipped"]
    assert skipped == {"bad_context": 1, "no_session": 1, "bad_time": 1, "bad_targets": 1, "not_a_memory": 1}
    assert report["unused_rows"] == 1
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {("a", "d"): 1}


def test_a_late_outcome_is_read_by_the_next_rebuild(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b"], used=False)
    _rebuild(tmp_path, engram)
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {}
    db = sqlite3.connect(engram)
    db.execute("UPDATE memory_log SET outcome = 'used: later' WHERE id = '2'")
    db.commit(); db.close()
    _rebuild(tmp_path, engram)
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {("a", "b"): 1}


def test_an_erased_memory_is_gone_from_the_next_file(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b"])
    _rebuild(tmp_path, engram)
    db = sqlite3.connect(engram)
    db.execute("DELETE FROM episodes WHERE id = 'b'")
    db.commit(); db.close()
    _rebuild(tmp_path, engram)
    raw = (tmp_path / "ncat.db").read_bytes()
    assert b'"b"' not in raw and b"'b'" not in raw
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {}
        assert "b" not in store.memory_ids()


def test_nothing_but_ids_is_read_and_the_person_store_is_unchanged(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b"])
    before = engram.read_bytes()
    _rebuild(tmp_path, engram)
    assert engram.read_bytes() == before
    assert b"private words" not in (tmp_path / "ncat.db").read_bytes()
    assert stat.S_IMODE((tmp_path / "ncat.db").stat().st_mode) == 0o600
    assert not (tmp_path / "ncat.db-wal").exists() and not (tmp_path / "ncat.db-journal").exists()


def test_the_query_in_a_recall_never_leaves_sqlite(tmp_path, monkeypatch):
    """Engram's recall context holds the person's query beside the session id. Only the id may reach this process."""
    engram = _engram(tmp_path / "graph.db")
    for i, memory in enumerate(["a", "b"]):
        _recall(engram, str(i), f"2026-11-07T10:0{i}:00+00:00", "s", [memory],
                raw_context=json.dumps({"session_id": "s", "recall_id": f"r{i}", "query": "a private worry about a patient"}))
    seen = []
    connect = sqlite3.connect

    class Watched:
        def __init__(self, conn):
            self._conn = conn

        def execute(self, *args):
            rows = self._conn.execute(*args).fetchall()
            seen.extend(rows)
            return Rows(rows)

        def close(self):
            self._conn.close()

    class Rows(list):
        def fetchall(self):
            return list(self)

        def fetchone(self):
            return self[0] if self else None

    monkeypatch.setattr(ncat_store.sqlite3, "connect", lambda *a, **k: Watched(connect(*a, **k)))
    sessions, _ = ncat_store.read_engram(engram)
    monkeypatch.undo()
    assert sessions == {"s": ["a", "b"]}
    assert seen and not any("private worry" in str(value) for row in seen for value in row)


def test_a_session_id_that_isnt_a_string_is_skipped_not_kept_as_text(tmp_path):
    """Tardis ran it: json_extract gives an object back as its JSON text, which would have become the session id."""
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", None, ["a"], raw_context=json.dumps({"session_id": {"q": "words"}}))
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", None, ["b"], raw_context=json.dumps({"session_id": ["words"]}))
    sessions, report = ncat_store.read_engram(engram)
    assert sessions == {} and report["skipped"] == {"no_session": 2}


def test_replay_gives_the_same_keys_and_a_rebuild_the_same_content(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b", "c"])
    _rebuild(tmp_path, engram)
    first = _keys(tmp_path / "ncat.db")
    assert _keys(tmp_path / "ncat.db") == first
    dump = lambda: list(sqlite3.connect(tmp_path / "ncat.db").execute(
        "SELECT * FROM generator UNION ALL SELECT key, dim, recipe, NULL, NULL, NULL, NULL FROM composite ORDER BY 1"))
    before = dump()
    _rebuild(tmp_path, engram)
    assert dump() == before and _keys(tmp_path / "ncat.db") == first


def test_a_key_that_doesnt_match_its_recipe_is_caught_on_open(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b"])
    _recall(engram, "3", "2026-11-07T10:02:00+00:00", "s", ["c"])
    _rebuild(tmp_path, engram)
    db = sqlite3.connect(tmp_path / "ncat.db")
    db.execute("UPDATE composite SET recipe = json_array('then', 0, json_array("
               "json_extract(recipe, '$[2][1]'), json_extract(recipe, '$[2][0]'))) WHERE dim = 1 AND recipe LIKE '[\"then\"%'")
    db.commit(); db.close()
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        with pytest.raises(ncat_store.IntegrityError):
            store.session("s")


def test_a_crashed_rebuild_leaves_the_old_file_and_the_next_run_clears_its_temp(tmp_path, monkeypatch):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b"])
    _rebuild(tmp_path, engram)
    good = _keys(tmp_path / "ncat.db")
    _recall(engram, "3", "2026-11-07T10:02:00+00:00", "s", ["c"])
    monkeypatch.setattr(ncat_store, "_replace", lambda *_: (_ for _ in ()).throw(KeyboardInterrupt))
    with pytest.raises(KeyboardInterrupt):
        _rebuild(tmp_path, engram)
    monkeypatch.undo()
    assert _keys(tmp_path / "ncat.db") == good
    assert any(p.name.startswith("ncat.db.tmp-") for p in tmp_path.iterdir())
    _rebuild(tmp_path, engram)
    assert not any(p.name.startswith("ncat.db.tmp-") for p in tmp_path.iterdir())
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.roads() == {("a", "b"): 1, ("b", "c"): 1}


def _three_step(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    for i, (session, memory) in enumerate([("s1", "a"), ("s1", "b"), ("s2", "b"), ("s2", "c"), ("s3", "d")]):
        _recall(engram, str(i), f"2026-11-07T10:0{i}:00+00:00", session, [memory])
    _rebuild(tmp_path, engram)
    return tmp_path / "ncat.db"


@pytest.mark.parametrize("tamper", [
    "UPDATE session SET key = (SELECT key FROM session WHERE session_id = 's2') WHERE session_id = 's1'",
    "UPDATE generator SET ref = CASE ref WHEN 'a' THEN 'b' WHEN 'b' THEN 'a' ELSE ref END WHERE kind = 'object'",
    "UPDATE generator SET ref = '[\"a\", \"c\"]' WHERE kind = 'road' AND ref = '[\"a\", \"b\"]'",
    "DELETE FROM road_use",
    "UPDATE session SET used = 7 WHERE session_id = 's1'",
    "UPDATE composite SET dim = 2",
    "UPDATE road_use SET road = (SELECT max(road) FROM road_use) WHERE session_id = 's1'",
], ids=["session key moved", "object refs swapped", "road ref edited", "walks deleted", "count edited", "dim edited",
        "walk moved"])
def test_a_tampered_file_is_caught_by_check(tmp_path, tamper):
    store = _three_step(tmp_path)
    db = sqlite3.connect(store)
    db.execute(tamper)
    db.commit(); db.close()
    with pytest.raises(ncat_store.IntegrityError):
        with ncat_store.open_store(store) as opened:
            opened.check()


def test_an_unreadable_or_missing_file_is_an_integrity_error(tmp_path):
    (tmp_path / "garbage.db").write_bytes(b"not a database at all" * 100)
    for path in (tmp_path / "garbage.db", tmp_path / "missing.db"):
        with pytest.raises(ncat_store.IntegrityError):
            with ncat_store.open_store(path) as opened:
                opened.check()


def test_a_failed_rebuild_leaves_no_temporary_file(tmp_path, monkeypatch):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    monkeypatch.setattr(ncat_store, "_write", lambda *_: (_ for _ in ()).throw(RuntimeError("boom")))
    with pytest.raises(RuntimeError):
        _rebuild(tmp_path, engram)
    assert not any(p.name.startswith("ncat.db.tmp-") for p in tmp_path.iterdir())


def test_a_session_the_kernel_refuses_is_counted_and_the_rest_are_kept(tmp_path, monkeypatch):
    engram = _engram(tmp_path / "graph.db", [f"m{i}" for i in range(400)])
    for i in range(300):
        _recall(engram, f"long{i:03d}", f"2026-11-07T10:{i // 60:02d}:{i % 60:02d}+00:00", "long", [f"m{i}"])
    _recall(engram, "short1", "2026-11-07T11:00:00+00:00", "short", ["m1"])
    _recall(engram, "short2", "2026-11-07T11:01:00+00:00", "short", ["m2"])
    compose = ncat_store._compose

    def over_budget(parts, k):  # the kernel's own refusal, as a budget overrun on the long one gives it
        if len(parts) > 100:
            raise ncat_store.NCatError(-9)
        return compose(parts, k)
    monkeypatch.setattr(ncat_store, "_compose", over_budget)
    report = _rebuild(tmp_path, engram)
    monkeypatch.undo()
    assert report["skipped"].get("refused_by_kernel") == 1 and report["sessions"] == 1
    with ncat_store.open_store(tmp_path / "ncat.db") as store:
        assert store.session_ids() == ["short"]


def test_a_missing_engram_store_says_so_and_exits_1(tmp_path):
    env = {**os.environ, "PYTHONPATH": str(ENGRAM)}
    done = subprocess.run([sys.executable, "-m", "ncat_store", "rebuild", "--engram", str(tmp_path / "nope.db")],
                          capture_output=True, text=True, env=env, cwd=ENGRAM)
    assert done.returncode == 1 and "no Engram store" in done.stderr and "Traceback" not in done.stderr


def test_one_rebuild_at_a_time(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    holder = subprocess.Popen([sys.executable, "-c", (
        "import fcntl, sys, time; f = open(sys.argv[1], 'a'); fcntl.flock(f, fcntl.LOCK_EX); print('held', flush=True); time.sleep(30)"),
        str(tmp_path / "ncat.db.lock")], stdout=subprocess.PIPE, text=True)
    try:
        assert holder.stdout.readline().strip() == "held"
        with pytest.raises(ncat_store.Busy):
            _rebuild(tmp_path, engram)
        assert not (tmp_path / "ncat.db").exists()
    finally:
        holder.kill(); holder.wait()
    _rebuild(tmp_path, engram)  # a dead holder's lock is gone with it
    assert (tmp_path / "ncat.db").exists()


def test_the_command_rebuilds_and_an_integrity_error_exits_2(tmp_path):
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "1", "2026-11-07T10:00:00+00:00", "s", ["a"])
    _recall(engram, "2", "2026-11-07T10:01:00+00:00", "s", ["b"])
    env = {**os.environ, "PYTHONPATH": str(ENGRAM)}
    done = subprocess.run([sys.executable, "-m", "ncat_store", "rebuild", "--engram", str(engram)],
                          capture_output=True, text=True, env=env, cwd=ENGRAM)
    assert done.returncode == 0, done.stderr
    assert "1 session" in done.stdout and (tmp_path / "ncat.db").exists()
    db = sqlite3.connect(tmp_path / "ncat.db")
    db.execute("UPDATE composite SET key = 'tampered' WHERE dim = 1")
    db.commit(); db.close()
    checked = subprocess.run([sys.executable, "-m", "ncat_store", "check", "--store", str(tmp_path / "ncat.db")],
                             capture_output=True, text=True, env=env, cwd=ENGRAM)
    assert checked.returncode == 2 and "rebuild" in checked.stderr


def test_the_budgets_on_this_machine(tmp_path):
    """Spec: 10,000 recall rows rebuilt in under 10 s, a 200-road session rebuilt in under 5 ms, under 256 MB."""
    import random
    rng = random.Random(7)
    memories = [f"m{i}" for i in range(2000)]
    engram = _engram(tmp_path / "graph.db", memories)
    db = sqlite3.connect(engram)
    rows = []
    for i in range(10_000):
        session = f"s{i // 50}"
        rows.append((f"{i:06d}", f"2026-11-07T{10 + (i % 50) // 60:02d}:{(i % 50) % 60:02d}:00+00:00", "recall", "episode",
                     json.dumps([rng.choice(memories)]), json.dumps({"session_id": session}), "used: x"))
    for j in range(200):
        rows.append((f"long{j:04d}", f"2026-11-08T00:{j // 60:02d}:{j % 60:02d}+00:00", "recall", "episode",
                     json.dumps([rng.choice(memories)]), json.dumps({"session_id": "long"}), "used: x"))
    db.executemany("INSERT INTO memory_log VALUES (?,?,?,?,?,?,?)", rows)
    db.commit(); db.close()
    # In a process of its own, so the peak is the store's and not the test runner's (1.9 GB inside the whole suite),
    # read as VmHWM: a child's ru_maxrss on Linux starts at its parent's peak (train-1111's suite read 1,976 MB).
    measure = (
        "import json, resource, sys, time\n"
        "import ncat_store\n"
        "started = time.perf_counter(); ncat_store.rebuild(sys.argv[1], sys.argv[2]); took = time.perf_counter() - started\n"
        "rebuilt = 1e9\n"
        "for _ in range(5):  # each a fresh store and kernel; the best of five, so a busy machine doesn't decide it\n"
        "    with ncat_store.open_store(sys.argv[2]) as store:\n"
        "        started = time.perf_counter(); store.session('long'); rebuilt = min(rebuilt, time.perf_counter() - started)\n"
        "try:  # VmHWM is this process's own peak; ru_maxrss carries the parent's across exec (the suite's 1.9 GB)\n"
        "    peak = int(next(l for l in open('/proc/self/status') if l.startswith('VmHWM:')).split()[1]) / 1024\n"
        "except OSError:  # no /proc (macOS): ru_maxrss, in bytes there\n"
        "    peak = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss / 1024 / 1024\n"
        "print(json.dumps([took, rebuilt, peak]))\n")
    done = subprocess.run([sys.executable, "-c", measure, str(engram), str(tmp_path / "ncat.db")], capture_output=True,
                          text=True, env={**os.environ, "PYTHONPATH": str(ENGRAM)}, cwd=ENGRAM, timeout=120)
    assert done.returncode == 0, done.stderr
    took, rebuilt, peak_mb = json.loads(done.stdout)
    print(f"rebuild {took:.2f} s, 200-road session {rebuilt * 1e3:.2f} ms, peak {peak_mb:.0f} MB")
    assert took < 10 and rebuilt < 0.005 and peak_mb < 256


def test_a_generator_the_kernel_refuses_stops_the_rebuild_exits_4_and_keeps_the_old_file(tmp_path, monkeypatch):
    """A reader's should (S2): a budget too small for the generators themselves ended in a traceback."""
    engram = _engram(tmp_path / "graph.db")
    _recall(engram, "r1", "2026-11-07T10:00:00+00:00", "s1", ["a", "b"])
    assert ncat_store.main(["rebuild", "--engram", str(engram), "--store", str(tmp_path / "ncat.db")]) == 0
    before = _keys(tmp_path / "ncat.db")
    _recall(engram, "r2", "2026-11-07T10:01:00+00:00", "s2", ["c", "d"])
    monkeypatch.setattr(ncat_store, "BUDGET_BYTES", 3_000)
    assert ncat_store.main(["rebuild", "--engram", str(engram), "--store", str(tmp_path / "ncat.db")]) == 4
    monkeypatch.undo()
    assert _keys(tmp_path / "ncat.db") == before
    assert sorted(p.name for p in tmp_path.iterdir()) == ["graph.db", "ncat.db", "ncat.db.lock"]
