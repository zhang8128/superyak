"""The package writer and ``imprint.py build`` (store-copy spec I 6.1, 6.2, 6.4, D3, D33, D42, R26, R30, RF5)."""
import contextlib
import fcntl
import hashlib
import json
import os
import sqlite3
import stat
import uuid

import pytest

import store_identity
from store_identity import ancestry
from imprint import PlanBusy, build, main, make_plan
from imprint_checks import l1_values, l2_fts, l3_vec0, l4_raw
from imprint_filter import PlanRefused, row_key
from tests.imprint_support import (EH, HOME, deny, ep, footpath_store, iid, load_vec, plan_args, shipped_ids,
                                   stored_instance_id, vectors_of, write_denies, written, written_with_source)


def test_insertion_only(tmp_path):
    path = written(tmp_path)                 # a package from a source whose rowids have gaps and odd order
    conn = sqlite3.connect(path)
    assert conn.execute("PRAGMA freelist_count").fetchone()[0] == 0 and conn.execute("PRAGMA foreign_key_check").fetchall() == []
    assert path.read_bytes()[18:20] == b"\x01\x01"


def test_rowids_run_one_to_n(tmp_path):
    conn = sqlite3.connect(written(tmp_path))
    for table in ("episodes", "semantics", "episode_fts_docsize", "semantic_fts_docsize"):
        ids = [r[0] for r in conn.execute(f"SELECT rowid FROM {table} ORDER BY rowid")]
        assert ids == list(range(1, len(ids) + 1)), table
    assert [r[0] for r in conn.execute("SELECT id FROM episodes ORDER BY rowid")] == ["e1", "e2", "e3"]


def test_vectors_are_copied_bit_for_bit(tmp_path):
    src, path = written_with_source(tmp_path)
    for layer in ("episode", "semantic"):
        assert vectors_of(path, layer) == vectors_of(src, layer, only=shipped_ids(path, layer))
        assert vectors_of(path, layer)


def test_the_package_is_an_imprint_of_its_source(tmp_path):
    src, path = written_with_source(tmp_path, source="fork")
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM meta"))
    assert meta["instance_id_origin"] == "imprint" and meta["forked_from_instance_id"] == iid(src)
    assert json.loads(meta["ancestry"]) == [iid(src)] + ancestry(src.conn)[0] and uuid.UUID(meta["instance_id"]).version == 4
    assert set(meta) == set(store_identity.KEYS) - {"instance_id_basis_episode"}


def test_a_source_older_than_identity_names_its_derived_id(tmp_path):
    src, path = written_with_source(tmp_path, source="before_identity")   # episodes, no stored instance_id
    derived = store_identity.effective_id(src.conn)                       # the id its migration would assign
    meta = dict(sqlite3.connect(path).execute("SELECT key, value FROM meta"))
    assert meta["forked_from_instance_id"] == derived and stored_instance_id(src) is None
    assert (json.loads(meta["ancestry"]), meta["ancestry_complete"]) == ([derived], "false")


def test_co_subject_rows_are_written_only_at_home(tmp_path):
    src, path = written_with_source(tmp_path, cosubjects={"e1": "person:jenn"}, home=True)
    conn = sqlite3.connect(path)
    assert conn.execute("SELECT memory_id, layer, subject FROM imprint_subjects").fetchall() == [("e1", "episode", "person:jenn")]
    _, away = written_with_source(tmp_path / "away", cosubjects={"e1": "person:jenn"}, home=False)
    assert sqlite3.connect(away).execute("SELECT count(*) FROM imprint_subjects").fetchone()[0] == 0


def test_the_writer_refuses_an_existing_file(tmp_path):
    from imprint import write_package
    src, path = written_with_source(tmp_path)
    before = path.read_bytes()
    with pytest.raises(FileExistsError):
        write_package(None, path, source_id="x", source_ancestry=[], source_complete=True, imprint_id="y")
    assert path.read_bytes() == before


def test_batches_split_by_rows_and_by_bytes_and_commit_each(tmp_path, monkeypatch):
    import imprint
    monkeypatch.setattr(imprint, "BATCH_ROWS", 2)
    _, path = written_with_source(tmp_path)
    assert sqlite3.connect(path).execute("SELECT count(*) FROM episodes").fetchone()[0] == 3
    monkeypatch.setattr(imprint, "BATCH_ROWS", 1000)
    monkeypatch.setattr(imprint, "BATCH_BYTES", 1)          # every row alone is over: one row a batch
    sizes = []
    real = imprint._batched
    monkeypatch.setattr(imprint, "_batched", lambda rows: (sizes.append(len(b)) or b for b in real(rows)))
    _, path2 = written_with_source(tmp_path / "two")
    assert sizes and set(sizes) == {1}
    assert sqlite3.connect(path2).execute("SELECT count(*) FROM episodes").fetchone()[0] == 3


def test_the_ddl_is_the_specs(tmp_path):
    from imprint_filter import IMPRINT_SUBJECTS_DDL
    assert "PRIMARY KEY (memory_id, layer, subject)" in IMPRINT_SUBJECTS_DDL
    conn = sqlite3.connect(written(tmp_path))
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name = 'imprint_subjects'").fetchone()[0] == IMPRINT_SUBJECTS_DDL


# ---- imprint.py build (Task 19) ------------------------------------------------------------------------------------

NOW = 1_761_415_451


def run_build(tmp_path, plan, **kw):
    return build(plan.id, home=HOME(tmp_path), now=NOW, engram_home=EH(tmp_path), **kw)


def imprint_dirs(tmp_path):
    root = HOME(tmp_path) / "imprints"
    return [p for p in root.iterdir() if p.is_dir() and p.name != "plans"] if root.exists() else []


def plan_file(tmp_path, plan):
    return json.loads((HOME(tmp_path) / "imprints" / "plans" / f"{plan.id}.json").read_text())


def late_sql(tmp_path, sql, *params, name="src"):
    """Change the plan's source store behind the plan's back."""
    conn = sqlite3.connect(tmp_path / f"{name}.db")
    try:
        with conn:
            conn.execute(sql, params)
    finally:
        conn.close()


def package_conn(built):
    return sqlite3.connect(f"file:{built.dir / 'imprint.db'}?mode=ro&immutable=1", uri=True)


def table_rows(path, table):
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    conn.row_factory = sqlite3.Row
    try:
        return [dict(r) for r in conn.execute(f"SELECT * FROM {table}")]
    finally:
        conn.close()


def empty(built, *tables):
    return all(table_rows(built.dir / "imprint.db", t) == [] for t in tables)


def canon(value) -> bytes:
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=False).encode()


def digest_written_from_section_5_4(path, scope):
    """The digest as I 5.4 defines it, in memory, from the package's own tables (no code of this plan)."""
    def h(v):
        return "" if v is None else hashlib.sha256(v if isinstance(v, bytes) else v.encode()).hexdigest()

    def as_json(v):
        return json.loads(v) if isinstance(v, str) else v

    rows = lambda t: table_rows(path, t)
    keys = {
        "episodes": [[r["id"], r["lane"], r["created_at"], r["session_id"], h(r["content"]), h(r["context"])]
                     for r in rows("episodes")],
        "semantics": [[r["id"], r["lane"], r["created_at"], h(r["content"])] for r in rows("semantics")],
        "episode_vectors": [[k, h(v)] for k, v in vectors_of(path, "episode").items()],
        "semantic_vectors": [[k, h(v)] for k, v in vectors_of(path, "semantic").items()],
        "semantic_sources": [[r["semantic_id"], r["episode_id"]] for r in rows("semantic_sources")],
        "resonances": [[r["id"], r["memory_a"], r["layer_a"], r["memory_b"], r["layer_b"], r["created_at"]]
                       for r in rows("resonances")],
        "semantic_peers": [[r["peer_id"], r["parent_id"]] for r in rows("semantic_peers")],
        "subdivision_events": [[r["id"], r["parent_id"], sorted(as_json(r["peer_ids"]))]
                               for r in rows("subdivision_events")],
        "memory_log": [[r["id"], r["timestamp"], r["event_type"], r["layer"], as_json(r["target_ids"]),
                        as_json(r["context"]), r["outcome"]] for r in rows("memory_log")],
        "operation_log": [[r["id"], r["timestamp"], r["operation"], r["session_id"], as_json(r["target_ids"]),
                           r["outcome"]] for r in rows("operation_log")],
        "imprint_subjects": [[r["memory_id"], r["layer"], r["subject"]] for r in rows("imprint_subjects")],
    }
    whole = {"filter": "imprint-filter-v1", "scope": scope, "rows": {t: sorted(v, key=canon) for t, v in keys.items()}}
    return hashlib.sha256(canon(whole)).hexdigest()


def section_4_sessions(path):
    """T 4 alone: a session is any distinct non-null ``episodes.session_id``; it holds the episodes it wrote."""
    out = {}
    for r in table_rows(path, "episodes"):
        if r["session_id"] is not None:
            out.setdefault(r["session_id"], []).append((r["created_at"], r["id"]))
    return {s: [i for _, i in sorted(v)] for s, v in out.items()}


def section_4_trails(path):
    """Two touches make a trail: the episodes a session wrote, in order, when it wrote at least two."""
    return [ids for ids in section_4_sessions(path).values() if len(ids) >= 2]


def walker_store(tmp_path):
    """``footpath_store`` (a closed session ``walker`` wrote f1 and f2) plus one episode of a session still open at t1."""
    s = footpath_store(tmp_path)
    ep(s, "open-episode", session="live", at="2026-10-25T17:50:00+00:00")
    return s


@contextlib.contextmanager
def held_lock(path):
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o600)
    try:
        fcntl.flock(fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        yield
    finally:
        os.close(fd)


def scratch_env(monkeypatch, home):
    """What the re-executed process finds: a 0700 directory under home/imprints/plans named by three variables."""
    scratch = home / "imprints" / "plans" / "scratch-test"
    scratch.mkdir(parents=True, mode=0o700, exist_ok=True)
    for key in ("SQLITE_TMPDIR", "TMPDIR", "IMPRINT_SCRATCH"):
        monkeypatch.setenv(key, str(scratch))
    return scratch


def test_build_refuses_when_a_memory_changed_since_the_plan(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    late_sql(tmp_path, "UPDATE episodes SET content = 'changed' WHERE id = 'e1'")
    with pytest.raises(PlanRefused, match="changed since the plan"):
        run_build(tmp_path, plan)
    assert imprint_dirs(tmp_path) == [] and "imprint_id" not in plan_file(tmp_path, plan)


def test_a_recall_and_a_log_outcome_after_the_plan_change_nothing_but_a_late_outcome_on_a_kept_row_does(tmp_path):
    def recall_now(root):
        late_sql(root, "INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
                       "VALUES ('late', '2026-10-25T19:00:00+00:00', 'recall', 'episode', '[\"e1\"]', "
                       "'{\"session_id\": \"sx\"}', NULL)")
        late_sql(root, "UPDATE episodes SET accessed_count = accessed_count + 1, last_accessed = '2026-10-25T19:00:00+00:00'")

    plan = make_plan(*plan_args(tmp_path, route=True))
    recall_now(tmp_path)
    late_sql(tmp_path, "UPDATE memory_log SET outcome = 'used' WHERE id = 'late'")        # a row that stays home
    assert run_build(tmp_path, plan).imprint_id                                            # same digest
    two = tmp_path / "2"
    plan2 = make_plan(*plan_args(two, route=True))
    late_sql(two, "UPDATE memory_log SET outcome = 'not_used' WHERE id = 'l1'")           # l1 ships
    with pytest.raises(PlanRefused, match="changed since the plan"):
        run_build(two, plan2)


def test_a_co_subjects_no_between_plan_and_build_refuses_the_build(tmp_path):    # I 5.2 denied(m); the check's M1
    args = plan_args(tmp_path, owner="andy", cosubjects={"e1": "person:lee"})
    plan = make_plan(*args)
    write_denies(args[3].ledger, "person:lee", deny(actions=["read"], purposes=["calibration"]))
    with pytest.raises(PlanRefused, match="changed since the plan"):
        run_build(tmp_path, plan)


def test_plan_list_equals_the_package_rows(tmp_path):
    listing = tmp_path / "list.jsonl"
    plan = make_plan(*plan_args(tmp_path, route=True), list_to=listing)
    built = run_build(tmp_path, plan)
    listed = sorted(listing.read_text().splitlines())
    path = built.dir / "imprint.db"
    read = []
    for table in ("episodes", "semantics", "semantic_sources", "resonances", "semantic_peers", "subdivision_events",
                  "memory_log", "operation_log", "imprint_subjects"):
        read += [json.dumps({"table": table, "key": row_key(table, r)}, sort_keys=True) for r in table_rows(path, table)]
    for layer in ("episode", "semantic"):
        read += [json.dumps({"table": f"{layer}_vectors", "key": [k, hashlib.sha256(v).hexdigest()]}, sort_keys=True)
                 for k, v in vectors_of(path, layer).items()]
    assert listed == sorted(read) and listed


def test_plan_digest_from_the_definitions(tmp_path):
    built = run_build(tmp_path, make_plan(*plan_args(tmp_path, route=True, every_table=True)))
    assert digest_written_from_section_5_4(built.dir / "imprint.db", built.request["scope"]) == built.request["plan_digest"]


def test_cross_references_stop_the_build_until_excluded(tmp_path):
    plan = make_plan(*plan_args(tmp_path, cross_ref=True))
    with pytest.raises(PlanRefused, match="names something staying here") as refused:
        run_build(tmp_path, plan)
    assert "1 memory" in str(refused.value) and "--show-cross-references" in str(refused.value)
    assert "--exclude FILE" in str(refused.value) and imprint_dirs(tmp_path) == []
    two = tmp_path / "2"
    built = run_build(two, make_plan(*plan_args(two, cross_ref=True, exclude={"names-it"})))
    key = sqlite3.connect(two / "src.db").execute("SELECT id FROM instincts").fetchone()[0]
    conn = package_conn(built)
    load_vec(conn)
    stay = frozenset({key})
    assert l1_values(conn, stay) == l2_fts(conn, two / "l2") == l3_vec0(conn, None) == l4_raw(built.dir / "imprint.db", stay) == []


def test_no_footpath_without_route(tmp_path):
    without = run_build(tmp_path, make_plan(*plan_args(tmp_path, store=walker_store, route=False)))
    r = tmp_path / "r"
    with_route = run_build(r, make_plan(*plan_args(r, store=walker_store, route=True)))
    assert section_4_sessions(without.dir / "imprint.db") == {} and empty(without, "memory_log", "operation_log")
    assert section_4_trails(with_route.dir / "imprint.db") == [["f1", "f2"]]
    sessions = {x["id"]: x["session_id"] for x in table_rows(with_route.dir / "imprint.db", "episodes")}
    assert "open-episode" in sessions and sessions["open-episode"] is None


def test_the_files_on_the_source_machine(tmp_path):
    plan = make_plan(*plan_args(tmp_path))
    built = run_build(tmp_path, plan)
    assert stat.S_IMODE((built.dir / "imprint.db").stat().st_mode) == 0o400 and stat.S_IMODE(built.dir.stat().st_mode) == 0o700
    assert built.dir == HOME(tmp_path) / "imprints" / built.imprint_id and built.imprint_id == built.imprint_id.lower()
    assert sorted(p.name for p in built.dir.iterdir()) == ["imprint.db", "manifest.json", "objects.json", "request.json",
                                                           "subjects.json"]
    objects = json.loads((built.dir / "objects.json").read_text())
    assert objects == sorted(objects) and objects and (built.dir / "objects.json").read_text().startswith("[\n")
    assert json.loads((built.dir / "subjects.json").read_text()) == []
    request_bytes = (built.dir / "request.json").read_bytes()
    assert json.loads(request_bytes) == built.request
    manifest = json.loads((built.dir / "manifest.json").read_text())
    assert manifest == built.manifest and manifest["request_sha256"] == hashlib.sha256(request_bytes).hexdigest()
    assert manifest["package"]["sha256"] == hashlib.sha256((built.dir / "imprint.db").read_bytes()).hexdigest()
    assert manifest["built_at"] == "2025-10-25T18:04:11Z" and built.request["imprint_id"] == built.imprint_id
    assert plan_file(tmp_path, plan)["imprint_id"] == built.imprint_id
    assert not [p for p in (HOME(tmp_path) / "imprints" / "plans").iterdir() if p.is_dir()]      # scratch removed
    again = run_build(tmp_path, plan, if_needed=True)
    assert (again.imprint_id, again.dir, again.request, again.manifest) == (built.imprint_id, built.dir, built.request, built.manifest)
    assert len(imprint_dirs(tmp_path)) == 1
    with pytest.raises(PlanRefused, match="already built"):
        run_build(tmp_path, plan)


def test_a_failing_leak_check_leaves_no_imprint(tmp_path, monkeypatch):
    import imprint
    monkeypatch.setattr(imprint, "l4_raw", lambda path, x_star: ["L4 imprint.db: planted"], raising=False)
    plan = make_plan(*plan_args(tmp_path))
    with pytest.raises(PlanRefused, match="leak checks"):
        run_build(tmp_path, plan)
    assert imprint_dirs(tmp_path) == [] and "imprint_id" not in plan_file(tmp_path, plan)


def test_the_subcommand_prints_the_request_and_if_needed_prints_nothing_the_second_time(tmp_path, monkeypatch, capsys):
    plan = make_plan(*plan_args(tmp_path))
    flags = ["build", "--plan", plan.id[:4], "--if-needed", "--superyak-home", str(HOME(tmp_path)),
             "--engram-home", str(EH(tmp_path))]
    scratch_env(monkeypatch, HOME(tmp_path))
    assert main(flags) == 0
    first = capsys.readouterr().out
    assert first.startswith("Imprint request ") and "Plan digest" in first
    scratch_env(monkeypatch, HOME(tmp_path))
    assert main(flags) == 0 and capsys.readouterr().out == ""


def test_rf5_a_second_build_of_one_plan_refuses(tmp_path, monkeypatch, capsys):
    plan = make_plan(*plan_args(tmp_path))
    scratch_env(monkeypatch, HOME(tmp_path))
    with held_lock(HOME(tmp_path) / "imprints" / "plans" / f"{plan.id}.lock"):          # the first run is building
        with pytest.raises(PlanBusy):
            run_build(tmp_path, plan)
        assert main(["build", "--plan", plan.id[:4], "--if-needed", "--superyak-home", str(HOME(tmp_path)),
                     "--engram-home", str(EH(tmp_path))]) == 4
    assert "Another make imprint-send of this plan is running." in capsys.readouterr().err
    assert imprint_dirs(tmp_path) == []                                                  # no imprint dir
    assert "imprint_id" not in plan_file(tmp_path, plan)
    assert issubclass(PlanBusy, PlanRefused)


# ---- A killed plan or build leaves no copy of the store for good (final review M9) ----

def leftover_scratch(plans):
    """Scratch directories as a killed run leaves them, and others a sweep must keep: {name: path}."""
    import subprocess
    import sys
    import time

    plans.mkdir(parents=True, exist_ok=True)
    dead = subprocess.run([sys.executable, "-c", "import os; print(os.getpid())"], capture_output=True, text=True)
    made = {}
    for name, pid in (("scratch-dead", dead.stdout.strip()), ("scratch-live", str(os.getpid())),
                      ("scratch-unmarked-old", None), ("scratch-unmarked-new", None), ("kept-dead", dead.stdout.strip())):
        folder = plans / name
        folder.mkdir(mode=0o700)
        (folder / "snapshot.db").write_bytes(b"a whole copy of the store")
        if pid is not None:
            (folder / "owner.pid").write_text(pid)
        made[name] = folder
    old = time.time() - 2 * 86400
    os.utime(made["scratch-unmarked-old"], (old, old))
    (plans / "scratch-link").symlink_to(made["kept-dead"])
    return made


@pytest.mark.parametrize("step", ["plan", "build"])
def test_a_killed_runs_scratch_is_removed_at_the_next_start_and_a_live_ones_kept(tmp_path, step):
    args = plan_args(tmp_path)
    plans = HOME(tmp_path) / "imprints" / "plans"
    if step == "build":
        plan = make_plan(*args)
    made = leftover_scratch(plans)
    make_plan(*args) if step == "plan" else run_build(tmp_path, plan)
    left = {p.name for p in plans.iterdir() if p.is_dir() or p.is_symlink()}
    assert left == {"scratch-live", "scratch-unmarked-new", "kept-dead", "scratch-link"}, left
    assert (made["kept-dead"] / "snapshot.db").is_file()


def test_a_bad_owner_file_is_held_a_day_and_never_blocks(tmp_path):
    import time
    import imprint
    plans = tmp_path / "plans"
    plans.mkdir()
    cases = {"scratch-empty": "", "scratch-huge": str(2 ** 31), "scratch-junk": "not a pid"}
    for name, text in cases.items():
        folder = plans / name
        folder.mkdir(mode=0o700)
        (folder / "owner.pid").write_text(text)
    imprint._remove_stale_scratch(plans)
    assert {p.name for p in plans.iterdir()} == set(cases)                      # fresh: all kept
    old = time.time() - 2 * 86400
    for name in cases:
        os.utime(plans / name, (old, old))
    imprint._remove_stale_scratch(plans)
    assert list(plans.iterdir()) == []


def test_the_owner_file_is_written_by_replace(tmp_path, monkeypatch):
    import imprint
    seen = []
    real = os.replace
    monkeypatch.setattr(os, "replace", lambda a, b: (seen.append(os.path.basename(b)), real(a, b))[1])
    made = imprint._new_scratch(tmp_path)
    assert "owner.pid" in seen and (made / "owner.pid").read_text() == str(os.getpid())
    assert [p.name for p in made.iterdir()] == ["owner.pid"]
