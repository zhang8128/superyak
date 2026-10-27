"""Peak memory on the Pi, for every process this work adds (store-copy spec I 14.1, 16; plan Task 50, A4, D42, R26, R27).

The Pi tests run only with ENGRAM_PI_BUDGET=1. Each starts its command in a fresh child under
``systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0`` and asserts the child's peak resident size
(``VmHWM``, read as ``ru_maxrss`` of that one child) under ``PEAK_BUDGET``. The fixtures are built once under
``/var/tmp/imprint-cap-<uid>/`` and reused.
"""
import os
import shlex
import shutil
import sqlite3
import sys
import time
from pathlib import Path

import pytest

import imprint
from imprint import admit, build, make_plan
from tests.imprint_support import (EH, _Connection, FAR, GROWING_TABLES, HOME, IMPRINT_PY, NOW_SECONDS, PEAK_BUDGET, admit_command,
                                   admission_result, base_peak, build_bounds_store, build_cap_store, built_of,
                                   cap_command, child_peak_rss, counting_stub, handed_off, mib, plan_args,
                                   refusing_fetchall, stub_verify, strace_temp_files, use_command)

PI = pytest.mark.skipif(os.environ.get("ENGRAM_PI_BUDGET") != "1", reason="Pi measurement (R16, R27)")
OK = stub_verify(ok=True)
OK_CMD = shlex.join(OK)


@pytest.fixture
def cap_store(tmp_path):
    return build_cap_store(tmp_path)


@pytest.fixture
def bounds_store(tmp_path):
    return build_bounds_store(tmp_path)


@PI
@pytest.mark.parametrize("step", ["plan", "read", "build", "admit", "count", "import-receipts"])
def test_pi_every_process_at_the_cap(cap_store, step):
    peak = child_peak_rss(cmd=cap_command(cap_store, step), env=cap_store.env)
    assert peak < PEAK_BUDGET, (step, mib(peak))
    if step == "import-receipts":                               # it did the work: the use list holds the rows
        from permission_uses import Uses
        uses = Uses.open_read_only(cap_store.work / "engram")
        try:
            assert uses.conn.execute("SELECT count(*) FROM uses").fetchone()[0] > 0
        finally:
            uses.close()
    print(step, mib(peak), "MiB, base", mib(base_peak(step)), "MiB")


@PI
def test_pi_one_admission_at_its_bounds_timed(bounds_store):                # I 10, "Time"; the check's S3
    started = time.monotonic()
    peak = child_peak_rss(cmd=admit_command(bounds_store, derive="stub"), env=bounds_store.env)
    seconds = time.monotonic() - started
    assert peak < PEAK_BUDGET and seconds < 3300, (mib(peak), seconds)
    result = admission_result(bounds_store)
    assert result["status"] == "admitted" and "skipped" not in result            # every set ran at its bound
    print("admission at its bounds", mib(peak), "MiB", round(seconds), "s")


@PI
def test_pi_the_use_parent_with_a_sleeping_child(tmp_path):                  # I 16, "The use's parent"; the check's S7
    peak = child_peak_rss(cmd=use_command(tmp_path, trails_cmd=[sys.executable, "-c", "import time; time.sleep(2)"]))
    assert peak < 64 * 2**20, mib(peak)
    print("use parent", mib(peak), "MiB, base", mib(base_peak("use")), "MiB")


def test_plan_build_and_admission_read_no_whole_table(tmp_path, monkeypatch):
    args = plan_args(tmp_path, owner="andy", route=True, cosubjects={"e1": "person:jenn"})
    guard, guarded = refusing_fetchall(GROWING_TABLES), []

    def connect(path, **kw):
        guarded.append(Path(path).name)
        return guard(path, **kw)
    monkeypatch.setattr(imprint, "_connect", connect)
    built = build(make_plan(*args).id, home=HOME(tmp_path), now=NOW_SECONDS, engram_home=EH(tmp_path))
    root, iid_ = handed_off(tmp_path, built, route=True, valid_until=FAR)
    assert admit(iid_, root=root, verify_cmd=OK, derive=counting_stub(1)) == 0
    assert guarded                                  # the plan and the build read through the refusing connection


def test_the_whole_table_guard_refuses_a_whole_table():
    raw = sqlite3.connect(":memory:")
    raw.execute("CREATE TABLE memory_log (id TEXT, x TEXT)")
    guarded = _Connection(raw, GROWING_TABLES)
    guarded.execute("SELECT * FROM memory_log WHERE id = ?", ("a",)).fetchall()      # keyed to one memory: allowed
    guarded.execute("SELECT * FROM memory_log").fetchmany(1000)                       # one batch: allowed
    with pytest.raises(AssertionError, match="grows with the store"):
        guarded.execute("SELECT * FROM memory_log").fetchall()
    with pytest.raises(AssertionError, match="grows with the store"):
        guarded.execute("SELECT * FROM memory_log").fetchmany(5000)


@pytest.mark.skipif(shutil.which("strace") is None, reason="needs strace (the Pi has /usr/bin/strace)")
def test_scratch_stays_on_disk_where_it_belongs(tmp_path):                  # I 16, "Scratch on disk"; the check's S1
    watched = tmp_path / "watched"
    watched.mkdir()
    env = {**os.environ, "TMPDIR": str(watched), "SQLITE_TMPDIR": str(watched)}   # set before each child starts
    plan_id = make_plan(*plan_args(tmp_path)).id
    opened, _ = strace_temp_files([sys.executable, IMPRINT_PY, "build", "--plan", plan_id,
                                   "--superyak-home", str(HOME(tmp_path)), "--engram-home", str(EH(tmp_path))], env)
    assert opened and all(Path(p).parent.parent == HOME(tmp_path) / "imprints" / "plans" for p in opened)
    root, iid_ = handed_off(tmp_path, built_of(tmp_path, plan_id), route=False, valid_until=FAR)
    scratch = str(root / f"{iid_}.state" / "scratch")
    opened, envs = strace_temp_files([sys.executable, IMPRINT_PY, "admit", "--id", iid_, "--imprints-dir", str(root),
                                      "--verify-cmd", OK_CMD], env)
    assert any(e.get("SQLITE_TMPDIR") == e.get("TMPDIR") == e.get("IMPRINT_SCRATCH") == scratch for e in envs)   # the re-exec ran
    assert all(Path(p).parent == Path(scratch) for p in opened)        # admission may need no temporary file (the re-check's S5)
    assert not [p for p in opened if Path(p).is_relative_to(watched)] and not Path(scratch).exists()
