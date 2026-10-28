"""Fixtures for the store-copy (imprint) tests.

Nothing here opens a stamped file with ``Storage(path)``: writers use
``sqlite3`` with ``sqlite_vec`` and readers use ``store_reader.connect`` or
``Storage.open_read_only`` (an imprint refuses a writable open).
"""
import ast
import json
import os
import re
import shlex
import shutil
import sqlite3
import subprocess
import warnings
import sys
import uuid
from collections import defaultdict
from dataclasses import dataclass, replace
from pathlib import Path

import store_identity
import store_reader
from storage import Storage
from tests.permissions_support import T, World  # noqa: F401  (T re-exported)
from tests.test_store_identity import build_schema27_store

GENOME_PARENT = "3f2b8c1e-5a4d-4e6f-9b7a-1c2d3e4f5a6b"


def _path(tmp_path: Path, name: str) -> Path:
    return tmp_path / f"{name}.db"


def new_store(tmp_path: Path, name: str) -> Storage:
    tmp_path.mkdir(parents=True, exist_ok=True)
    return Storage(str(_path(tmp_path, name)))


def retro_store(tmp_path: Path, name: str, first: tuple[str, str]) -> Storage:
    """A store older than identity: a schema-27 file with one episode, then migrated."""
    path = _path(tmp_path, name)
    (tmp_path / f"{name}-mig").mkdir()
    build_schema27_store(path, tmp_path / f"{name}-mig", [first])
    return Storage(str(path))


def unidentified_store(tmp_path: Path, name: str) -> sqlite3.Connection:
    """A read-only connection to a store holding no identity keys."""
    path = _path(tmp_path, name)
    s = Storage(str(path))
    s.conn.execute(
        f"DELETE FROM meta WHERE key IN ({', '.join('?' * len(store_identity.KEYS))})",
        store_identity.KEYS)
    s.conn.commit()
    s.close()
    return store_reader.connect(path)


def _writable(path: Path) -> sqlite3.Connection:
    import sqlite_vec

    conn = sqlite3.connect(str(path))
    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)
    return conn


def _backup(store: Storage, path: Path) -> sqlite3.Connection:
    store.conn.commit()
    dst = _writable(path)
    store.conn.backup(dst)
    return dst


def fork_of(tmp_path: Path, parent: Storage, name: str) -> Storage:
    path = _path(tmp_path, name)
    dst = _backup(parent, path)
    try:
        store_identity.stamp_fork(dst, store_identity.effective_id(parent.conn),
                                  *store_identity.ancestry(parent.conn))
        dst.commit()
    finally:
        dst.close()
    return Storage(str(path))


def old_fork_of(tmp_path: Path, parent: Storage, name: str) -> Storage:
    """A fork made before ancestry existed: the two ancestry keys are gone."""
    path = _path(tmp_path, name)
    dst = _backup(parent, path)
    try:
        store_identity.stamp_fork(dst, store_identity.effective_id(parent.conn))
        dst.execute("DELETE FROM meta WHERE key IN ('ancestry', 'ancestry_complete')")
        dst.commit()
    finally:
        dst.close()
    return Storage(str(path))


def imprint_of(tmp_path: Path, parent: Storage, name: str) -> Storage:
    path = _path(tmp_path, name)
    dst = _backup(parent, path)
    try:
        store_identity.stamp_imprint(
            dst, store_identity.effective_id(parent.conn),
            *store_identity.ancestry(parent.conn), str(uuid.uuid4()))
        dst.commit()
        dst.execute("PRAGMA journal_mode=DELETE")
    finally:
        dst.close()
    return Storage.open_read_only(path)


def file_copy(tmp_path: Path, store: Storage, name: str) -> Storage:
    """A copy of the file: same identity, same bytes' meaning (backup API, so WAL pages come too)."""
    path = _path(tmp_path, name)
    _backup(store, path).close()
    return Storage(str(path))


def iid(store: Storage) -> str:
    return store_identity.read(store.conn)["instance_id"]


def iid_of(path: Path) -> str:
    conn = store_reader.connect(path)
    try:
        return store_identity.read(conn)["instance_id"]
    finally:
        conn.close()


def genome_with_parent(tmp_path: Path) -> Path:
    """An engram dir whose genome was forked (by stamp_fork) from a store with id GENOME_PARENT."""
    engram_dir = tmp_path / "engram"
    (engram_dir / "genome").mkdir(parents=True)
    genome = Storage(str(engram_dir / "genome" / "graph.db"))
    try:
        store_identity.stamp_fork(genome.conn, GENOME_PARENT)
        genome.conn.commit()
    finally:
        genome.close()
    return engram_dir


def imprint_file(tmp_path: Path, name: str = "imprint.db") -> Path:
    """A rollback-journal file stamped ``imprint``, holding work-lane episode ``e1``, with its newest
    ``schema_version`` row deleted so a migration is pending."""
    stem = name[:-3] if name.endswith(".db") else name
    src = new_store(tmp_path, f"{stem}-src")
    src.add_episode("e1", None, "an imprinted note", lane="work")
    imp = imprint_of(tmp_path, src, stem)
    path = Path(imp.db_path)
    imp.close()
    src.close()
    conn = sqlite3.connect(str(path))
    try:
        conn.execute("DELETE FROM schema_version WHERE version = (SELECT MAX(version) FROM schema_version)")
        conn.commit()
    finally:
        conn.close()
    return path


def engram_dir_with_imprint_instance(tmp_path: Path, name: str) -> Path:
    """An engram dir whose ``instances/<name>/graph.db`` is stamped ``imprint``."""
    engram_dir = tmp_path / "engram-dir"
    inst = engram_dir / "instances" / name
    inst.mkdir(parents=True)
    import shutil

    shutil.copyfile(imprint_file(tmp_path, "inst-imprint.db"), inst / "graph.db")
    return engram_dir


def ep(store: Storage, id: str, *, lane: str = "work", at: str = "2026-01-01T00:00:00+00:00",
       session: str | None = None, content: str | None = None, core: int = 0) -> str:
    """Insert an episode with ``created_at`` as given; returns its id."""
    store.conn.execute(
        "INSERT INTO episodes (id, session_id, content, created_at, lane, core) VALUES (?, ?, ?, ?, ?, ?)",
        (id, session, content if content is not None else f"episode {id}", at, lane, core))
    store.conn.commit()
    return id


def vec(store: Storage, layer: str, id: str, seed: int) -> None:
    """Write a seeded unit 768-dimension vector for ``id`` in ``layer`` ('episode' or 'semantic')."""
    import numpy as np
    from storage import _pack_embedding

    v = np.random.default_rng(seed).standard_normal(768)
    v = (v / np.linalg.norm(v)).tolist()
    store.conn.execute(f"INSERT INTO {layer}_vectors (id, embedding) VALUES (?, ?)", (id, _pack_embedding(v)))
    store.conn.commit()


def sem(store: Storage, id: str, *, sources=(), lane: str = "work", at: str = "2026-01-01T00:00:00+00:00",
        contradicted_by: str | None = None, content: str | None = None) -> str:
    """Insert a semantic with ``created_at`` as given and one ``semantic_sources`` row per source; returns its id.

    Foreign keys are off for the insert, so ``contradicted_by`` may name a semantic inserted later."""
    store.conn.execute("PRAGMA foreign_keys=OFF")
    try:
        store.conn.execute(
            "INSERT INTO semantics (id, content, kind, confidence, created_at, contradicted_by, lane) "
            "VALUES (?, ?, 'fact', 0.5, ?, ?, ?)",
            (id, content if content is not None else f"semantic {id}", at, contradicted_by, lane))
        store.conn.executemany("INSERT INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)",
                               [(id, e) for e in sources])
        store.conn.commit()
    finally:
        store.conn.execute("PRAGMA foreign_keys=ON")
    return id


def prune(store: Storage, *ids: str) -> None:
    """Prune episodes the way the store does; their ``semantic_sources`` rows cascade away (I 5.2)."""
    store.prune_episode_ids(list(ids))


def resonance(store: Storage, id: str, a: str, b: str, *, layer_a: str = "episode", layer_b: str = "episode",
              at: str = "2026-10-01T00:00:00+00:00") -> str:
    store.conn.execute(
        "INSERT INTO resonances (id, memory_a, layer_a, memory_b, layer_b, weight, created_at, last_seen) "
        "VALUES (?, ?, ?, ?, ?, 0.5, ?, ?)", (id, a, layer_a, b, layer_b, at, at))
    store.conn.commit()
    return id


def peer_edge(store: Storage, peer_id: str, parent_id: str) -> None:
    store.conn.execute("INSERT INTO semantic_peers (peer_id, parent_id, created_at) VALUES (?, ?, ?)",
                       (peer_id, parent_id, "2026-10-01T00:00:00+00:00"))
    store.conn.commit()


def subdivision(store: Storage, id: str, parent_id: str, peer_ids) -> str:
    import json

    store.conn.execute(
        "INSERT INTO subdivision_events (id, parent_id, peer_ids, energy_before, energy_after, dl_cost, site, "
        "created_at) VALUES (?, ?, ?, 1.0, 0.5, 0.1, 'sleep', ?)",
        (id, parent_id, json.dumps(list(peer_ids)), "2026-10-01T00:00:00+00:00"))
    store.conn.commit()
    return id


MEMORY_PREFIX = "private memory text number"


def _unit_blob(rng, dim: int) -> bytes:
    import numpy as np

    v = rng.standard_normal(dim)
    return (v / np.linalg.norm(v)).astype("<f4").tobytes()


def calibration_source(tmp_path: Path, *, resonances: int = 0, decayed: int = 0) -> Path:
    """12 work episodes with vectors, one semantic over 10 of them, two cores.

    ``resonances`` adds that many episode-to-episode resonance rows (at most 66); ``decayed`` adds that many
    compressed, decayed work episodes with vectors, which the two-key prune preview weighs."""
    import numpy as np

    def v(seed: int) -> list[float]:
        base = np.zeros(768)
        base[seed % 3] = 1.0
        x = base + 0.05 * np.random.default_rng(seed).standard_normal(768)
        return (x / np.linalg.norm(x)).tolist()

    path = tmp_path / "src" / "graph.db"
    path.parent.mkdir()
    store = Storage(str(path))
    ids = []
    for i in range(12):
        eid = str(uuid.uuid4())
        store.add_episode(eid, f"s{i % 2}", f"{MEMORY_PREFIX} {i} about rivers and cheese", embedding=v(i))
        ids.append(eid)
    store.conn.execute("UPDATE episodes SET lane = 'work'")
    store.conn.execute("UPDATE episodes SET core = 1 WHERE id IN (?, ?)", (ids[1], ids[2]))
    store.conn.commit()
    store.add_semantic(str(uuid.uuid4()), f"{MEMORY_PREFIX} semantic about rivers and also cheese", "fact", 0.8,
                       v(0), ids[:10], lane="work")
    for i in range(decayed):
        eid = store.add_episode(str(uuid.uuid4()), f"d{i % 2}", f"{MEMORY_PREFIX} decayed {i}", embedding=v(100 + i),
                                lane="work")
        store.conn.execute("UPDATE episodes SET decay_strength = 0.01, compressed = 1 WHERE id = ?", (eid,))
    pairs = [(a, b) for k, a in enumerate(ids) for b in ids[k + 1:]][:resonances]
    assert len(pairs) == resonances, "at most 66 resonance rows over 12 episodes"
    for k, (a, b) in enumerate(pairs):
        store.conn.execute(
            "INSERT INTO resonances (id, memory_a, layer_a, memory_b, layer_b, similarity, weight, strength,"
            " co_occurrences, created_at, last_seen) VALUES (?, ?, 'episode', ?, 'episode', 0.5, 1.0, 0.5, ?,"
            " '2026-10-25T00:00:00+00:00', '2026-10-25T00:00:00+00:00')", (f"r{k}", a, b, 1 + k % 3))
    store.conn.commit()
    store.close()
    return path


def dense_source(tmp_path: Path, lane_n: int, cores: int = 0, hub_sources: int = 0, event_sources: int = 0,
                 semantics: int = 0, sources_each: int = 3, dim: int = 768, seed: int = 0) -> Path:
    """A store of ``lane_n`` work episodes with random unit vectors (inserted in batches, not through
    ``add_episode``). The first ``cores`` are cores. A hub semantic holds the first ``hub_sources``; an
    unchecked subdivision event has two peer semantics that together hold the first ``event_sources``;
    ``semantics`` more semantics hold ``sources_each`` episodes each, taken round the lane."""
    import json

    import numpy as np

    assert max(cores, hub_sources, event_sources) <= lane_n
    path = tmp_path / "dense" / "graph.db"
    path.parent.mkdir()
    rng = np.random.default_rng(seed)
    store = Storage(str(path))
    conn = store.conn
    ids = [f"w{i}" for i in range(lane_n)]
    for lo in range(0, lane_n, 1000):
        chunk = ids[lo:lo + 1000]
        conn.executemany(
            "INSERT INTO episodes (id, content, created_at, lane, core) VALUES (?, ?, '2026-01-01T00:00:00+00:00',"
            " 'work', ?)", [(e, f"episode {e}", 1 if lo + k < cores else 0) for k, e in enumerate(chunk)])
        conn.executemany("INSERT INTO episode_vectors (id, embedding) VALUES (?, ?)",
                         [(e, _unit_blob(rng, dim)) for e in chunk])
    conn.commit()

    def semantic(sid: str, sources: list[str]) -> str:
        store.add_semantic(sid, f"semantic {sid}", "fact", 0.8, rng.standard_normal(dim).tolist(), sources,
                           lane="work")
        return sid

    if hub_sources:
        semantic("hub", ids[:hub_sources])
    if event_sources:
        half = (event_sources + 1) // 2
        peers = [semantic("peer-a", ids[:half]), semantic("peer-b", ids[half:event_sources])]
        conn.execute(
            "INSERT INTO subdivision_events (id, parent_id, peer_ids, energy_before, energy_after, dl_cost,"
            " persistence_checked, site, created_at) VALUES ('ev1', 'parent', ?, 0.9, 0.1, 0.1, 0, 'sleep',"
            " '2026-10-25T00:00:00+00:00')", (json.dumps(peers),))
        conn.commit()
    for k in range(semantics):
        semantic(f"s{k}", [ids[(k * sources_each + j) % lane_n] for j in range(sources_each)])
    store.close()
    return path


# --- bounded-calibration test seams -----------------------------------------------------------------

PEAK_BUDGET = 384 * 2**20          # R27, per process at its bounds
ENGRAM_DIR = Path(__file__).resolve().parent.parent


def random_unit_vectors(n: int, dim: int, *, seed: int = 0, duplicate_rows: int = 0):
    """``n`` random vectors (not yet normalized); the last ``duplicate_rows`` repeat the first rows exactly."""
    import numpy as np

    X = np.random.default_rng(seed).standard_normal((n, dim))
    for j in range(duplicate_rows):
        X[n - 1 - j] = X[j]
    return X


def unit_rows(X):
    """``X`` with every row L2-normalized as ``persistence.distance_matrix`` does."""
    import numpy as np

    X = np.asarray(X, dtype=np.float64)
    return X / (np.linalg.norm(X, axis=1, keepdims=True) + 1e-12)


def heights(f) -> list[float]:
    """The sorted edge heights of a filtration's tree."""
    return sorted(float(h) for h in f.heights)


def spy(fn, built: list, *, size=len):
    """``fn`` wrapped so each call appends ``size(*args)`` to ``built``."""
    def wrapper(*args, **kwargs):
        built.append(size(*args))
        return fn(*args, **kwargs)
    return wrapper


def refuse_over(limit: int, *, size=len):
    """A stand-in that fails when called over ``limit``. It wraps no real function: a call at or under the
    limit fails too, so a test that installs it asserts the dense code is never reached at all."""
    def refuse(*args, **kwargs):
        n = size(*args)
        raise AssertionError(f"dense code reached with {n} rows (limit {limit})"
                             if n > limit else f"unexpected call with {n} rows")
    return refuse


GROWING_TABLES = ("episodes", "episode_vectors", "semantics", "semantic_vectors", "semantic_sources",
                  "resonances", "memory_log", "subdivision_events", "subdivision_queue", "semantic_peers",
                  "persistence_scores")
# A statement keyed to one memory (``... id = ?``) is bounded by that memory, not by the store.
_KEYED = re.compile(r"\b(?:semantic_id|episode_id|id)\s*=\s*\?", re.I)


class _Cursor:
    def __init__(self, cur, sql: str, tables):
        self._cur, self._sql, self._tables = cur, sql, tables

    def _grows(self) -> bool:
        return not _KEYED.search(self._sql) and any(re.search(rf"\b{t}\b", self._sql) for t in self._tables)

    def fetchall(self):
        if self._grows():
            raise AssertionError(f"fetchall on a table that grows with the store: {self._sql}")
        return self._cur.fetchall()

    def fetchmany(self, size=None):
        if self._grows() and (size or self._cur.arraysize) > 1000:
            raise AssertionError(f"fetchmany beyond one batch on a table that grows with the store: {self._sql}")
        return self._cur.fetchmany(*(() if size is None else (size,)))

    def execute(self, sql, *args):
        """A statement run again on the same cursor is checked as its own (final review M12)."""
        self._cur.execute(sql, *args)
        self._sql = sql
        return self

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _Connection:
    def __init__(self, conn, tables):
        object.__setattr__(self, "_conn", conn)
        object.__setattr__(self, "_tables", tables)

    def execute(self, sql, *args):
        return _Cursor(self._conn.execute(sql, *args), sql, self._tables)

    def cursor(self, *args):
        """A guarded cursor: its ``execute`` names the statement its fetches are checked against (M12)."""
        return _Cursor(self._conn.cursor(*args), "", self._tables)

    def __getattr__(self, name):
        return getattr(self._conn, name)

    def __setattr__(self, name, value):
        setattr(self._conn, name, value)

    def __enter__(self):
        self._conn.__enter__()
        return self                                     # the guard stays on inside ``with`` (final review M12)

    def __exit__(self, *exc):
        return self._conn.__exit__(*exc)


def refusing_fetchall(tables):
    """A replacement for ``calibrate._connect_read_only`` (called with a path) or for ``imprint._connect`` (called
    with ``read_only=`` and the rest): a connection whose ``execute`` raises on ``fetchall``, or ``fetchmany`` of more
    than a batch, of a statement naming one of ``tables`` unless it is keyed to one memory."""
    import imprint

    real = imprint._connect

    def connect(path, **kw):
        if "read_only" in kw:
            return _Connection(real(path, **kw), tables)
        store = Storage.open_read_only(path)
        store.conn = _Connection(store.conn, tables)
        return store
    return connect


_PREAMBLE = ("import sys; sys.path.insert(0, {engram!r}); SRC = {src!r}\n"
             "import calibrate, persistence, sheaf\nfrom storage import Storage\n")
_RUN_ONE = "from tests.imprint_support import run_one\n"   # only when used: the support module is heavy
# The backstop of R27's cap: where the user manager has no memory controller, ``MemoryMax=512M`` is silently not
# applied, so the child also gets a hard ``RLIMIT_DATA`` (private writable memory) equal to the cap, as the units'
# ``LimitDATA=512M`` gives them (review I4), and a wall-clock kill, and a runaway ends in the child's own MemoryError
# or timeout, never in someone killing it by hand.
CAP_BYTES = 512 * 2**20
HARD_DATA_LIMIT = CAP_BYTES
_LAUNCHER = ("import os, resource, signal, subprocess, sys, time\n"
             "lim = int(os.environ.pop('IMPRINT_DATA_LIMIT')); wall = float(os.environ.pop('IMPRINT_WALL'))\n"
             "t = time.monotonic()\n"
             "p = subprocess.Popen(sys.argv[1:], start_new_session=True,\n"
             "                     preexec_fn=lambda: resource.setrlimit(resource.RLIMIT_DATA, (lim, lim)))\n"
             "try:\n"
             "    code = p.wait(timeout=wall)\n"
             "except subprocess.TimeoutExpired:\n"
             "    os.killpg(p.pid, signal.SIGKILL); p.wait(); code = 124\n"
             "print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024, time.monotonic() - t, code)\n")


def memory_cap_enforced(controllers: str | None = None) -> bool:
    """True when ``systemd-run --user --scope -p MemoryMax=…`` is applied here: the user manager must hold the
    ``memory`` controller. On a Pi whose user cgroup lists only ``cpu pids`` the property is accepted and ignored."""
    if controllers is None:
        path = Path(f"/sys/fs/cgroup/user.slice/user-{os.getuid()}.slice/user@{os.getuid()}.service/cgroup.controllers")
        try:
            controllers = path.read_text()
        except OSError:
            return False
    return "memory" in controllers.split()


def child_peak_rss(code: str | None = None, *, src=None, timed: bool = False, cmd=None, env=None, cwd=None,
                   wall: float = 3600.0):
    """Peak resident bytes (``VmHWM``, read as ``ru_maxrss``) of ``code`` run in a child, or of the whole command
    ``cmd`` (a list) when it is given (``timed``: and its wall seconds). The child runs under
    ``systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0`` where that exists (R27), and always under a
    hard ``RLIMIT_DATA`` of 512 MiB and ``OPENBLAS_NUM_THREADS=1``, as the units start it, and a ``wall`` seconds kill, so a runaway fails the test on its own where the
    cap is not applied (``memory_cap_enforced``; a warning says so). A launcher process reads ``RUSAGE_CHILDREN``,
    so the figure is this child's alone, whatever it re-executes or forks."""
    if cmd is not None:
        argv = [str(a) for a in cmd]
    else:
        preamble = _PREAMBLE.format(engram=str(ENGRAM_DIR), src=str(src)) + (_RUN_ONE if "run_one" in code else "")
        argv = [sys.executable, "-c", preamble + code]
    if shutil.which("systemd-run"):
        argv = ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=512M", "-p", "MemorySwapMax=0"] + argv
        if not memory_cap_enforced():
            warnings.warn("MemoryMax=512M is not applied here (the user manager has no memory controller); "
                          "the child's RLIMIT_DATA and wall-clock kill are the only backstop", stacklevel=2)
    import imprint

    env = {**(os.environ if env is None else env), **imprint.ONE_BLAS_THREAD,     # as the units start it (review I4)
           "IMPRINT_DATA_LIMIT": str(HARD_DATA_LIMIT), "IMPRINT_WALL": str(wall)}
    out = subprocess.run([sys.executable, "-c", _LAUNCHER, *argv], cwd=cwd or ENGRAM_DIR, env=env,
                         capture_output=True, text=True, timeout=wall + 60)
    assert out.returncode == 0 and out.stdout.split(), out.stderr[-2000:]
    peak, seconds, status = out.stdout.split()[-3:]
    assert int(status) == 0, ("killed at the wall-clock limit" if int(status) == 124 else "",
                              out.stdout[-1000:], out.stderr[-2000:])
    return (int(peak), float(seconds)) if timed else int(peak)


_BASE_IMPORTS = {"admit": "import imprint, calibrate", "count": "import imprint, store_reader",
                 "plan": "import imprint, imprint_filter", "read": "import imprint, imprint_filter",
                 "build": "import imprint, imprint_filter", "import-receipts": "import imprint, imprint_copies",
                 "use": "import imprint"}


def base_peak(step=None) -> int:
    """The peak a child reaches after its imports alone: the modules the step's command loads, none of its data."""
    if step is None:
        return child_peak_rss("pass", src="")
    code = f"import sys; sys.path.insert(0, {str(ENGRAM_DIR)!r}); {_BASE_IMPORTS[step]}"
    return child_peak_rss(cmd=[sys.executable, "-c", code])


def run_one(analysis: str, src) -> None:
    """One dense analysis over the store's ``hub`` semantic, for the Pi measurements."""
    import persistence
    import sheaf
    from config import PersistenceConfig

    store = Storage.open_read_only(src)
    try:
        if analysis == "classify_hubs":
            persistence.classify_hubs(store, PersistenceConfig(enabled=True))
            return
        ids, X = sheaf._episode_matrix(store.conn, "hub")
        if analysis == "cohesion_energy":
            sheaf.cohesion_energy(sheaf.build_local_sheaf("hub", ids, X))
        else:
            half = len(ids) // 2
            persistence.split_band(X, list(range(half)), list(range(half, len(ids))))
    finally:
        store.close()


def memory_texts(path: Path) -> list[str]:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        return ([r[0] for r in conn.execute("SELECT content FROM episodes")]
                + [r[0] for r in conn.execute("SELECT content FROM semantics")])
    finally:
        conn.close()


def has_key(value, key: str) -> bool:
    """True when ``key`` appears as a dict key at any depth."""
    if isinstance(value, dict):
        return key in value or any(has_key(x, key) for x in value.values())
    if isinstance(value, (list, tuple)):
        return any(has_key(x, key) for x in value)
    return False


# ---- hook tables (Task 6): the DDL the hooks run in graph.db, read from their source ----
_HOOK_FILES = ("nudge.py", "wake.py")


def _hook_ddl() -> list[str]:
    """Every CREATE TABLE string literal in hooks/nudge.py and hooks/wake.py, as written."""
    out = []
    for name in _HOOK_FILES:
        tree = ast.parse((ENGRAM_DIR / "hooks" / name).read_text())
        out += [n.value for n in ast.walk(tree)
                if isinstance(n, ast.Constant) and isinstance(n.value, str) and "CREATE TABLE" in n.value.upper()]
    return out


def hook_ddl_names() -> set[str]:
    return {m.group(1) for ddl in _hook_ddl()
            for m in re.finditer(r"CREATE TABLE(?: IF NOT EXISTS)?\s+(\w+)", ddl, re.I)}


def add_hook_tables(conn: sqlite3.Connection) -> None:
    for ddl in _hook_ddl():
        conn.execute(ddl)


# Task 7: the selection, the terms and the source context. The imports are inside the helpers so that
# importing this module never needs imprint_filter.

SELECTION_UNTIL = T("2026-10-25T18:00:00Z")


def selection(**over):
    """A Selection: work lane, both layers, no window start, until 2026-10-25T18:00Z, nothing else."""
    from imprint_filter import Selection

    values = dict(lanes=frozenset({"work"}), layers=frozenset({"episode", "semantic"}), since=None,
                  until=SELECTION_UNTIL, shared_with=None, exclude=frozenset(), unsourced=False)
    values.update(over)
    return Selection(**values)


def terms(**over):
    """Terms for the home place of andy, without route; ``route=True`` adds the route action and the
    trail-evaluation purpose."""
    from imprint_filter import Terms

    values = dict(audience="place:home/andy", actions=frozenset({"imprint"}),
                  purposes=frozenset({"calibration"}), days=90)
    if over.pop("route", False):
        values.update(actions=frozenset({"imprint", "route"}), purposes=frozenset({"calibration", "trail-evaluation"}))
    values.update(over)
    return Terms(**values)


def ctx(store: Storage, *, published: Path | None = None, owner: str | None = None, home: bool = True,
        instance_name: str = "default", ledger=None, terms=None, now: int = None):
    """A SourceContext for ``store``, with a scratch file beside it (a new one each call). ``terms`` default to
    the home place of ``owner`` without route; ``now`` to NOW; ``owner`` to the ledger's owner, else andy."""
    import store_identity
    from imprint_filter import Scratch, SourceContext

    if owner is None:
        owner = ledger.meta()["owner"].removeprefix("person:") if ledger is not None else "andy"

    path = Path(store.db_path)
    return SourceContext(
        source_path=path, source_id=store_identity.effective_id(store.conn), instance_name=instance_name,
        owner=owner, published=published, ledger=ledger, home=home,
        scratch=Scratch(path.parent / f"{path.stem}-scratch-{uuid.uuid4().hex[:8]}.db"),
        terms=_terms(audience=f"place:home/{owner}") if terms is None else terms,
        now=NOW if now is None else now)


_terms = terms


def published_house(tmp_path: Path) -> Path:
    """An empty published house (a migrated store) at the path the server uses for the lighthouse instance."""
    path = tmp_path / ".engram" / "instances" / "lighthouse" / "graph.db"
    path.parent.mkdir(parents=True, exist_ok=True)
    Storage(str(path)).close()
    return path


def share_as(store: Storage, published: Path, id: str, audience: str, *, layer: str = "episode",
             source_instance_id: str | None = None):
    """Record a share as ``sharing.share`` does, with the store's own id unless another is given.

    A semantic share of an id the store holds only as an episode first gives the store a semantic of that id.
    """
    import sharing
    import store_identity

    if layer == "semantic" and store.get_semantic(id) is None:
        store.conn.execute(
            "INSERT INTO semantics (id, content, kind, confidence, created_at, auto_generated, content_hash,"
            " lane) VALUES (?, ?, 'fact', 0.5, '2026-01-01T00:00:00+00:00', 0, ?, 'work')",
            (id, f"semantic {id}", f"hash-{id}"))
        store.conn.commit()
    house = Storage(str(published))
    try:
        return sharing.share(
            source_storage=store, published_storage=house, source_id=id, layer=layer, audience=audience,
            reason="test", source_instance="default",
            source_instance_id=source_instance_id or store_identity.effective_id(store.conn))
    finally:
        house.close()


# Task 8: a permissions ledger in the fixture, and the refused sources. Rows are written straight into the
# ledger with their own log rows (``Ledger._append``), since no step-1 command writes another person's layer
# (P 7.6) and a source gains subjects after a copy. Imports are inside the helpers, as above.

NOW = T("2026-10-26T12:00:00Z")
FIXTURE_AT = NOW - 86400                   # every fixture log row is older than the plan's clock
GENOME_ID = "9a1c7e20-4b3d-4f58-8e6a-0d2c1b7f3e55"


def ref_of(store: Storage, id: str, layer: str = "episode") -> str:
    return f"mem:{iid(store)}/{layer}/{id}"


def _put(led, kind: str, ref: str, body: dict) -> int:
    return led._append(kind, ref, "fixture", "tool", body, at=FIXTURE_AT)


def _ins(table: str, **row) -> dict:
    return {"table": table, "row": row}


def deny(*, audience=("place:home/andy",), requesters="*", kinds="*", stores="*", actions="*", purposes="*",
         valid_from: int | None = None, valid_until: int | None = None, revoked: bool = False) -> dict:
    """A deny record's fields, for ``ledger(denies=...)``. The audience defaults to the owner's home, which refuses
    a use of agent:station-imprints in it."""
    def lst(v):
        return v if v == "*" else list(v)
    return dict(selector={"audience": list(audience), "requesters": lst(requesters),
                          "objects": {"kinds": lst(kinds), "stores": lst(stores), "layers": "*", "lanes": "*",
                                      "collections": "*", "memories": "*"},
                          "actions": lst(actions), "purposes": lst(purposes)},
                valid_from=valid_from, valid_until=valid_until, revoked=revoked)


def _layer_of(subject: str) -> str:
    from permissions import home_of

    return home_of(subject) if subject.startswith("person:") else subject


def write_denies(led, person: str, *records: dict) -> None:
    """A deny record in ``person``'s layer (the person's home, or the place itself)."""
    from permission_ledger import new_id

    for rec in records:
        row = dict(id=new_id("r-"), layer=_layer_of(person), effect="deny", selector=rec["selector"],
                   valid_from=FIXTURE_AT if rec["valid_from"] is None else rec["valid_from"],
                   valid_until=rec["valid_until"], anchor=FIXTURE_AT, backing="person", set_by=person,
                   channel="tool", reason="fixture", created=FIXTURE_AT, created_seq="@seq")
        if rec["revoked"]:
            row.update(revoked="@at", revoked_by=person, revoke_reason="fixture", revoked_seq="@seq")
        _put(led, "fixture-deny", row["id"], {"insert": [_ins("records", **row)]})


def add_subject(led, ref: str, subject: str) -> None:
    _put(led, "fixture-subject", ref, {"insert": [_ins(
        "subjects", object=ref, subject=subject, added_seq="@seq", added_by="person:" + "fixture",
        self_claimed=0)]})


def remove_cosubject(led, ref: str, subject: str, *, by: str) -> None:
    """Mark a subjects row removed. ``ref`` may be an episode id of the ledger's one registered store."""
    if not ref.startswith("mem:"):
        ref = f"mem:{led.conn.execute('SELECT instance_id FROM stores').fetchone()[0]}/episode/{ref}"
    _put(led, "fixture-unsubject", ref, {"update": [{
        "table": "subjects", "where": {"object": ref, "subject": subject},
        "set": {"removed_seq": "@seq", "removed_by": by}}]})


def copy_of(led, copy_ref: str, source_ref: str) -> None:
    led.record_copy(copy_ref, source_ref, now=FIXTURE_AT)


def link_copies(led, refs) -> None:
    """``copies`` rows straight in: refs[0] is a copy of refs[1], which is a copy of refs[2], and so on."""
    _put(led, "fixture-copies", refs[0], {"insert": [
        _ins("copies", object=a, source=b, added_seq="@seq") for a, b in zip(refs, refs[1:])]})


def retire(led, person: str) -> None:
    """A person row with ``retired_seq``, as ``person retire`` writes it (permission_cli.py:396-397)."""
    from permissions import home_of

    _put(led, "fixture-retire", person, {"insert": [_ins(
        "persons", id=person, home=home_of(person), is_admin=0, created_seq="@seq", retired_seq="@seq")]})


def retire_place(led, place: str) -> None:
    """A place row with ``retired_seq``; for a home place also its person's row, not retired."""
    rows = [_ins("places", id=place, is_root=1, created_seq="@seq", retired_seq="@seq", pseudonym_salt="00" * 16)]
    if place.startswith("place:home/"):
        rows.append(_ins("persons", id="person:" + place.split("/", 1)[1], home=place, is_admin=0,
                         created_seq="@seq"))
    _put(led, "fixture-retire-place", place, {"insert": rows})


def forbid_state(monkeypatch) -> None:
    """Any ``Ledger.state`` call fails the test (the plan builds no State without a deny or a retirement)."""
    from permission_ledger import Ledger

    def refuse(self, *args, **kwargs):
        raise AssertionError("Ledger.state() was called")
    monkeypatch.setattr(Ledger, "state", refuse)


def ledger(home: Path, *, owner: str, store: Storage | None, store_owner: str | None = None,
           cosubjects: dict | None = None, lane_notes: dict | None = None, denies: dict | None = None):
    """A permissions ledger under ``home`` for ``owner``. ``store`` is registered with its owner unless None.
    ``cosubjects`` and ``lane_notes`` map an episode id to one person (or a list) and a lane; ``denies`` maps a
    person to deny records (``deny(...)``)."""
    from permission_ledger import Ledger

    home.mkdir(parents=True, exist_ok=True)
    led = Ledger.create(home, owner, now=FIXTURE_AT)
    if store is not None:
        _put(led, "register-store", iid(store), {"insert": [_ins(
            "stores", instance_id=iid(store), name=Path(store.db_path).stem,
            owner=store_owner or f"person:{owner}", place=f"place:home/{owner}", created_seq="@seq")]})
    for id, who in (cosubjects or {}).items():
        for subject in ([who] if isinstance(who, str) else who):
            add_subject(led, ref_of(store, id), subject)
    for id, lane in (lane_notes or {}).items():
        _put(led, "fixture-lane", id, {"insert": [_ins(
            "lane_notes", object=ref_of(store, id), lane=lane, at=FIXTURE_AT, seq="@seq")]})
    for person, records in (denies or {}).items():
        write_denies(led, person, *records)
    return led


def base_ids(store: Storage, led, *, route: bool) -> set:
    """The episode ids ``base`` keeps at the owner's home, with the route terms or without."""
    from collections import Counter

    from imprint_filter import base

    t = (terms(actions=frozenset({"imprint", "route"}), purposes=frozenset({"calibration", "trail-evaluation"}))
         if route else terms())
    c = ctx(store, ledger=led, owner="andy", home=True, now=NOW, terms=t)
    return set(base(store.conn, "episode", selection(), c, Counter()))


def published_house_file(engram_home: Path) -> Path:
    """The published house of ``engram_home``: a migrated store at ``.engram/instances/lighthouse/graph.db``."""
    path = published_house(engram_home)
    (path.parent.parent / "x").mkdir(exist_ok=True)     # a sibling instance, so a path through ``x/..`` exists
    return path


def empty_old_store(tmp_path: Path) -> Path:
    """A migrated store with no episodes and no identity keys: no identity can be derived."""
    path = _path(tmp_path, "unidentified")
    s = Storage(str(path))
    s.conn.execute(f"DELETE FROM meta WHERE key IN ({', '.join('?' * len(store_identity.KEYS))})",
                   store_identity.KEYS)
    s.conn.commit()
    s.close()
    return path


def future_store(tmp_path: Path) -> Path:
    """A store that holds a migration this code doesn't know."""
    path = _path(tmp_path, "future")
    s = Storage(str(path))
    s.conn.execute("INSERT INTO schema_version (version, applied_at) VALUES (99999, '2026-10-26T00:00:00+00:00')")
    s.conn.commit()
    s.close()
    return path


# Task 10: sessions closed at t1 and the two log tables.

def op(store: Storage, id: str, *, session: str | None, at: str, operation: str, targets=(),
       harness: str | None = "claude-code", model: str | None = "m1", repo: str | None = "/work/repo",
       details: dict | None = None, outcome: str = "ok") -> str:
    """Insert an ``operation_log`` row with ``timestamp`` as given; returns its id."""
    import json

    store.conn.execute(
        "INSERT INTO operation_log (id, timestamp, operation, session_id, harness, model, repo, target_ids, "
        "details, outcome) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (id, at, operation, session, harness, model, repo, json.dumps(list(targets)),
         json.dumps(details if details is not None else {"note": "x"}), outcome))
    store.conn.commit()
    return id


def log_row(store: Storage, *, session: str | None, at: str, event: str = "recall", id: str | None = None,
            targets=(), context=None) -> str:
    """Insert a ``memory_log`` row whose context holds ``session_id``; ``context`` (a string) replaces the context."""
    import json

    id = id or f"log-{uuid.uuid4().hex[:8]}"
    ctx_text = context if context is not None else json.dumps({"session_id": session})
    store.conn.execute(
        "INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
        "VALUES (?, ?, ?, 'episode', ?, ?, NULL)", (id, at, event, json.dumps(list(targets)), ctx_text))
    store.conn.commit()
    return id


def footpath_store(tmp_path: Path) -> Storage:
    """One closed session wrote two work-lane episodes and made no recall."""
    s = new_store(tmp_path, "footpath")
    ep(s, "f1", session="walker", at="2026-10-25T10:00:00+00:00")
    ep(s, "f2", session="walker", at="2026-10-25T10:05:00+00:00")
    return s


# Task 11: recall and route_shown rows, and instincts.

def recall(store: Storage, id: str, *, targets, session: str | None = "s1", at: str = "2026-10-25T15:00:00+00:00",
           outcome: str | None = None, **context) -> str:
    """Insert a ``recall`` row; ``context`` keys (``recall_id``, ``query``, ...) join ``session_id``."""
    import json

    ctx_ = {"session_id": session, **context} if session is not None else dict(context)
    store.conn.execute(
        "INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
        "VALUES (?, ?, 'recall', 'episode', ?, ?, ?)", (id, at, json.dumps(list(targets)), json.dumps(ctx_), outcome))
    store.conn.commit()
    return id


def route_shown(store: Storage, id: str, *, targets, session: str | None = "s1", lane: str | None = "work",
                at: str = "2026-10-25T15:00:00+00:00", **context) -> str:
    """Insert a ``route_shown`` row whose context holds ``receipt_id``, ``session_id``, ``tool``, ``lane`` and more."""
    import json

    ctx_ = {"receipt_id": f"r-{id}", "tool": "recall", **context}
    if session is not None:
        ctx_["session_id"] = session
    if lane is not None:
        ctx_["lane"] = lane
    store.conn.execute(
        "INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
        "VALUES (?, ?, 'route_shown', 'episode', ?, ?, NULL)", (id, at, json.dumps(list(targets)), json.dumps(ctx_)))
    store.conn.commit()
    return id


def inst(store: Storage, id: str) -> str:
    """Insert an instinct; returns its id."""
    store.conn.execute("INSERT INTO instincts (id, trigger, action, created_at) VALUES (?, 't', 'a', "
                       "'2026-01-01T00:00:00+00:00')", (id,))
    store.conn.commit()
    return id


# Task 12: a store with a row in every table that can ship, and its ledger.

def digest_store(tmp_path: Path, *, every_table: bool = False, cosubjects: bool = False) -> Storage:
    """Work-lane episodes ``e1`` and ``e2``, a semantic ``s1`` sourced on ``e1``, their vectors and one resonance.
    ``every_table`` adds a peer edge, a subdivision, an instinct, a recall, a route_shown row and a citing
    operation in the closed session ``sx`` (so a route plan ships all eleven tables with ``cosubjects``); ``cosubjects``
    is used by ``digest_ledger``."""
    s = new_store(tmp_path, "digest")
    ep(s, "e1", session="sx", at="2026-10-25T10:00:00+00:00")
    ep(s, "e2", session="sx", at="2026-10-25T10:05:00+00:00")
    sem(s, "s1", sources=["e1"], at="2026-10-25T10:10:00+00:00")
    for i, (layer, id) in enumerate([("episode", "e1"), ("episode", "e2"), ("semantic", "s1")]):
        vec(s, layer, id, seed=i + 1)
    resonance(s, "r1", "e1", "e2")
    if every_table:
        sem(s, "s2", sources=["e2"], at="2026-10-25T10:15:00+00:00")
        vec(s, "semantic", "s2", seed=9)
        peer_edge(s, "s1", "s2")
        subdivision(s, "d1", "s2", ["s1"])
        recall(s, "l1", targets=["e1", "e2"], session="sx", outcome="used", recall_id="rc1")
        route_shown(s, "l2", targets=["e1", "s1"], session="sx")
        op(s, "o1", session="sx", at="2026-10-25T10:20:00+00:00", operation="mark_core", targets=["e1"])
    return s


def digest_ledger(tmp_path: Path, s: Storage):
    """A ledger on which ``e1`` names jenn and ``s1`` names lee and jenn as co-subjects."""
    led = ledger(tmp_path / "digest-home", owner="andy", store=s, cosubjects={"e1": "person:jenn"})
    add_subject(led, ref_of(s, "s1", "semantic"), "person:lee")
    add_subject(led, ref_of(s, "s1", "semantic"), "person:jenn")
    return led


# Task 13: a package written from a source whose rowids have gaps and odd order.

def gap_source(tmp_path: Path, name: str = "gaps") -> Storage:
    """Work-lane episodes and semantics inserted out of creation order, with personal ones and a pruned row between
    them, so the source's rowids have gaps and run in no order of ``(created_at, id)``."""
    s = new_store(tmp_path, name)
    ep(s, "e3", at="2026-10-25T12:00:00+00:00")
    ep(s, "p1", lane="personal", at="2026-10-25T09:00:00+00:00")
    ep(s, "e1", at="2026-10-25T10:00:00+00:00")
    ep(s, "gone", at="2026-10-25T10:30:00+00:00")
    ep(s, "e2", at="2026-10-25T10:00:00+00:00")
    sem(s, "s2", sources=["e3"], at="2026-10-25T13:00:00+00:00")
    sem(s, "q1", lane="personal", at="2026-10-25T08:00:00+00:00")
    sem(s, "s1", sources=["e1", "e2"], at="2026-10-25T11:00:00+00:00")
    for i, (layer, id) in enumerate([("episode", "e3"), ("episode", "p1"), ("episode", "e1"), ("episode", "e2"),
                                     ("semantic", "s2"), ("semantic", "q1"), ("semantic", "s1")]):
        vec(s, layer, id, seed=i + 20)
    prune(s, "gone")
    return s


def before_identity_source(tmp_path: Path, name: str = "old") -> Storage:
    """Episodes and no stored identity: the id its migration would assign is derived from them."""
    s = gap_source(tmp_path, name)
    s.conn.execute(f"DELETE FROM meta WHERE key IN ({', '.join('?' * len(store_identity.KEYS))})",
                   store_identity.KEYS)
    s.conn.commit()
    return s


def stored_instance_id(store: Storage) -> str | None:
    return store_identity.read(store.conn).get("instance_id")


def written_with_source(tmp_path: Path, *, source: str = "gaps", cosubjects: dict | None = None, home: bool = True,
                        name: str | None = None, store: Storage | None = None):
    """``(source store, package path)``: the package of the source's work lane, written by ``write_package``.
    ``name`` keeps a second package beside the first; ``store`` is a source the caller built."""
    from imprint import write_package
    from imprint_filter import package_rows

    if store is not None:
        s = store
    else:
        s = {"gaps": gap_source, "before_identity": before_identity_source}.get(source)
        s = (s(tmp_path, name) if name else s(tmp_path)) if s else fork_of(tmp_path, gap_source(tmp_path, "parent"), "fork")
    led = ledger(tmp_path / "home", owner="andy", store=s, cosubjects=cosubjects) if cosubjects else None
    rows = package_rows(s.conn, selection(), terms(), ctx(s, ledger=led, home=home))
    out = tmp_path / (f"out-{name}" if name else "out")
    out.mkdir(parents=True, exist_ok=True)
    path = out / "imprint.db"
    ids, complete = store_identity.ancestry(s.conn)
    write_package(rows, path, source_id=store_identity.effective_id(s.conn), source_ancestry=ids,
                  source_complete=complete, imprint_id=str(uuid.uuid4()))
    return s, path


def written(tmp_path: Path, name: str | None = None) -> Path:
    return written_with_source(tmp_path, name=name)[1]


def written_with_x_star(tmp_path: Path, contents=None):
    """``(package path, X*, expected)``: a package of work-lane episodes (with ``contents`` as their text) and
    semantics, X* the lower-case ids of the left-out rows and a stranger, and the vec0 expectations hashed from the
    source's embedding bytes."""
    import hashlib

    s = new_store(tmp_path, "xstar")
    left_out = [str(uuid.uuid4()) for _ in range(2)]
    texts = contents or ["episode one", "episode two", "episode three"]
    kept = [ep(s, f"e{i}", content=t, at=f"2026-10-25T1{i}:00:00+00:00") for i, t in enumerate(texts, 1)]
    for u in left_out:
        ep(s, u, lane="personal", content=f"personal {u[:8]}", at="2026-10-25T09:00:00+00:00")
    sem(s, "s1", sources=[kept[0]], at="2026-10-25T14:00:00+00:00")
    for i, id in enumerate(kept + left_out):
        vec(s, "episode", id, seed=i + 3)
    vec(s, "semantic", "s1", seed=40)
    _, path = written_with_source(tmp_path, store=s)
    expected = {f"{layer}_vectors": {k: hashlib.sha256(v).hexdigest()
                                    for k, v in vectors_of(path, layer).items()}
                for layer in ("episode", "semantic")}
    for layer in ("episode", "semantic"):   # the source's bytes, not the package's own
        src = vectors_of(s, layer, only=set(expected[f"{layer}_vectors"]))
        assert {k: hashlib.sha256(v).hexdigest() for k, v in src.items()} == expected[f"{layer}_vectors"]
    return path, frozenset(left_out + [str(uuid.uuid4()).upper().lower()]), expected


def load_vec(conn: sqlite3.Connection) -> None:
    import sqlite_vec

    conn.enable_load_extension(True)
    sqlite_vec.load(conn)
    conn.enable_load_extension(False)


def writable_copy(path: Path) -> sqlite3.Connection:
    """A writable connection (sqlite-vec loaded) to a fresh copy of a package, for planting a defect."""
    copy = path.with_name(f"copy-{uuid.uuid4().hex[:8]}.db")
    shutil.copyfile(path, copy)
    return _writable(copy)


def plant_index_only_term(conn: sqlite3.Connection, fts: str, *, rowid: int, term: str) -> None:
    """An FTS entry for a rowid that has no content row (an external-content index accepts it)."""
    conn.execute(f"INSERT INTO {fts}(rowid, content) VALUES (?, ?)", (rowid, term))
    conn.commit()


def poke_invalid_slot(conn: sqlite3.Connection, table: str, *, byte: int) -> None:
    """Write ``byte`` into the first invalid slot's vector bytes."""
    dim = int(re.search(r"float\[(\d+)\]", conn.execute("SELECT sql FROM sqlite_master WHERE name=?",
                                                         (table,)).fetchone()[0]).group(1))
    chunk_id, size, validity = conn.execute(f"SELECT chunk_id, size, validity FROM {table}_chunks").fetchone()
    slot = next(i for i in range(size) if not validity[i // 8] >> (i % 8) & 1)
    vectors = bytearray(conn.execute(f"SELECT vectors FROM {table}_vector_chunks00 WHERE rowid=?",
                                     (chunk_id,)).fetchone()[0])
    vectors[4 * dim * slot] = byte
    conn.execute(f"UPDATE {table}_vector_chunks00 SET vectors=? WHERE rowid=?", (bytes(vectors), chunk_id))
    conn.commit()


def rename_rowids_id(conn: sqlite3.Connection, table: str, *, to: str) -> None:
    conn.execute(f"UPDATE {table}_rowids SET id=? WHERE rowid=(SELECT min(rowid) FROM {table}_rowids)", (to,))
    conn.commit()


def put_value_across_page_boundary(conn: sqlite3.Connection, table: str, column: str, token: str) -> None:
    """Set ``column`` of the table's first row to a value longer than three pages with ``token`` straddling the
    first page boundary of the row's payload."""
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    value = "x" * (page - len(token) // 2 - 40) + token + "y" * (3 * page)
    conn.execute(f"UPDATE {table} SET {column}=? WHERE rowid=(SELECT min(rowid) FROM {table})", (value,))
    conn.commit()


def vectors_of(where, layer: str, only=None) -> dict:
    """``{id: raw embedding bytes}`` of a package path or a store, optionally only the ids in ``only``."""
    own = not isinstance(where, Storage)
    conn = _writable(where) if own else where.conn
    try:
        got = {r[0]: bytes(r[1]) for r in conn.execute(f"SELECT id, embedding FROM {layer}_vectors")}
    finally:
        if own:
            conn.close()
    return got if only is None else {k: v for k, v in got.items() if k in only}


def shipped_ids(path: Path, layer: str) -> set:
    conn = sqlite3.connect(path)
    try:
        return {r[0] for r in conn.execute(f"SELECT id FROM {layer}s")}
    finally:
        conn.close()


# Task 15: the plan and the dry run. Imports are inside the helpers, as above.

PLAN_NOW = SELECTION_UNTIL                 # the plan's clock: 2026-10-25T18:00:00Z, so every fixture row is older
_AUTO = object()


def plan_context(owner: str = "sam"):
    """The station's answer for a ship whose owner is ``owner``; its operator (the home an audience may name) is
    andy, so ``sam`` plans a copy that leaves his home and ``andy`` one that stays in it."""
    from imprint import Context

    return Context(station="https://smart.tail7db420.ts.net", ship="voyager", owner=owner, operator="andy",
                   station_peer_id="ab" * 32)


def write_context(home: Path, context) -> Path:
    """The file ``agent imprint context`` writes (R7): ``home/imprints/context.json``."""
    import json
    import os

    path = home / "imprints" / "context.json"
    path.parent.mkdir(parents=True, exist_ok=True)
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as f:
        json.dump({"ship": context.ship, "owner": context.owner, "operator": context.operator,
                   "station": context.station_peer_id, "url": context.station}, f)
    return path


def live_source(tmp_path: Path) -> Storage:
    """A store whose connection stays open, so a second write lands in its WAL while a plan runs."""
    s = new_store(tmp_path, "live")
    ep(s, "e1", content="Jenn drove the truck to the clinic", at="2026-10-25T10:00:00+00:00")
    vec(s, "episode", "e1", seed=1)
    return s


def plan_args(tmp_path: Path, *, owner: str = "sam", route: bool = False, episodes: int = 2, cosubjects=None,
              ledger=_AUTO, denies=None, until="2026-10-25T18:00:00Z", ancestry=None, store=None,
              every_table: bool = False, cross_ref: bool = False, exclude=(), lanes=("work",)):
    """``(store path, selection, terms, ctx, context, home, now)``: the arguments of ``make_plan``. Episodes
    ``e0`` (never given a co-subject) and ``e1`` to ``e<episodes>`` in the work lane hold text naming Jenn; ``s1`` is sourced on ``e1``. A ledger is made
    when ``cosubjects`` or ``denies`` are given (``ledger=None`` forbids one)."""
    from imprint_filter import parse_selection, parse_terms

    if store is not None:                       # a store the caller builds: ``store(tmp_path)``
        s = store(tmp_path)
    elif every_table:                           # a row in every table that can ship (``digest_store``)
        s = digest_store(tmp_path, every_table=True)
    else:
        s = new_store(tmp_path, "src")
        if ancestry:                                # a store copied from these stores, nearest first
            store_identity.stamp_fork(s.conn, ancestry[0], list(ancestry[1:]), True)
            s.conn.commit()
        ep(s, "e0", content="Jenn drove the truck to the clinic, trip 0", session="sx", at="2026-10-25T09:00:00+00:00")
        vec(s, "episode", "e0", seed=100)           # no one else is recorded on e0, so a plan always has a memory
        for i in range(1, episodes + 1):
            ep(s, f"e{i}", content=f"Jenn drove the truck to the clinic, trip {i}", session="sx",
               at=f"2026-10-25T10:{i % 60:02d}:00+00:00")
            vec(s, "episode", f"e{i}", seed=i)
        sem(s, "s1", sources=["e1"], at="2026-10-25T12:00:00+00:00")
        vec(s, "semantic", "s1", seed=99)
        if route:
            recall(s, "l1", targets=["e1"], session="sx", outcome="used", recall_id="rc1")
    if cross_ref:                               # ``names-it`` names an instinct that stays home
        key = inst(s, str(uuid.uuid4()))
        ep(s, "names-it", content=f"see {key} for the rest", at="2026-10-25T11:00:00+00:00")
    led = None
    if ledger is _AUTO and (cosubjects is not None or denies):
        ledger = True
    if ledger is True:
        led = globals()["ledger"](tmp_path / "eh", owner=owner, store=s, cosubjects=cosubjects, denies=denies)
    context = plan_context(owner)
    until = iso_of(until) if isinstance(until, int) else until          # seconds or ISO text
    sel = parse_selection(lanes=",".join(lanes), layers="episode,semantic", since=None, until=until, shared_with=None,
                          exclude_file=None, unsourced=False, now=PLAN_NOW)
    sel = replace(sel, exclude=frozenset(exclude))
    t = parse_terms(audience="place:home/andy", actions="imprint,route" if route else "imprint",
                    purposes="calibration,trail-evaluation" if route else "calibration", days=90,
                    operator=context.operator)
    c = ctx(s, ledger=led, owner=owner, home=owner == context.operator, terms=t, now=PLAN_NOW)
    return Path(s.db_path), sel, t, c, context, tmp_path / "home", PLAN_NOW


def HOME(tmp_path: Path) -> Path:
    """The superyak home ``plan_args`` plans into."""
    return tmp_path / "home"


def EH(tmp_path: Path) -> Path:
    """The engram home ``plan_args`` puts its permissions ledger in."""
    return tmp_path / "eh"


def edit_source(tmp_path: Path, id: str, *, content: str, name: str = "src") -> None:
    """Change an episode of the plan's source store behind the plan's back."""
    conn = sqlite3.connect(_path(tmp_path, name))
    try:
        with conn:
            conn.execute("UPDATE episodes SET content = ? WHERE id = ?", (content, id))
    finally:
        conn.close()


def expected_order(plan) -> list[str]:
    """Ids of every episode and semantic of the plan's source in ``(created_at, id)`` order (layers interleaved)."""
    conn = sqlite3.connect(plan.store)
    try:
        rows = [(r[0], r[1]) for table in ("episodes", "semantics")
                for r in conn.execute(f"SELECT created_at, id FROM {table}")]
    finally:
        conn.close()
    return [id for _, id in sorted(rows)]


# Task 20: the canaries (store-copy spec I 16, "Canaries").

def open_package(path: Path) -> sqlite3.Connection:
    """A read-only, immutable connection to a built package with sqlite-vec loaded (never ``Storage``, P19)."""
    conn = sqlite3.connect(f"file:{path}?mode=ro&immutable=1", uri=True)
    load_vec(conn)
    return conn


def _ordinary_tables(conn: sqlite3.Connection) -> list[str]:
    return [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE type='table' "
                                       "AND sql NOT LIKE 'CREATE VIRTUAL%'")]


def any_value_contains(conn: sqlite3.Connection, needle: str) -> bool:
    """Whether any value of any ordinary table (every shadow table too) holds ``needle``, ignoring case. A BLOB is
    read as Latin-1."""
    low = needle.lower()
    for table in _ordinary_tables(conn):
        for row in conn.execute(f'SELECT * FROM "{table}"'):
            for v in row:
                if isinstance(v, (bytes, bytearray, memoryview)):
                    v = bytes(v).decode("latin-1")
                if isinstance(v, str) and low in v.lower():
                    return True
    return False


def _folded(text: str) -> str:
    import unicodedata

    return "".join(ch for ch in unicodedata.normalize("NFKD", text.lower()) if not unicodedata.combining(ch))


def fts_vocab_contains(conn: sqlite3.Connection, needle: str) -> bool:
    """Whether any FTS5 table's term list holds a term containing ``needle`` (case and accents folded, as the
    tokenizer folds them), read through ``fts5vocab`` because the terms are stored prefix-compressed."""
    wanted = _folded(needle)
    fts = [r[0] for r in conn.execute("SELECT name FROM sqlite_master WHERE sql LIKE 'CREATE VIRTUAL TABLE%USING fts5%'")]
    for name in fts:
        conn.execute(f'CREATE VIRTUAL TABLE IF NOT EXISTS temp."{name}_canary_vocab" USING fts5vocab(main, "{name}", row)')
        try:
            if any(wanted in _folded(t) for (t,) in conn.execute(f'SELECT term FROM temp."{name}_canary_vocab"')):
                return True
        finally:
            conn.execute(f'DROP TABLE temp."{name}_canary_vocab"')
    return False


def any_vec0_slot_equals(conn: sqlite3.Connection, vectors) -> bool:
    """Whether any slot of any vec0 table's chunk blobs equals one of ``vectors`` (raw 4*dim-byte embeddings)."""
    wanted = set(vectors)
    for (table,) in conn.execute("SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%\\_vector\\_chunks%' ESCAPE '\\'"):
        base = table.split("_vector_chunks")[0]
        dim = int(re.search(r"float\[(\d+)\]", conn.execute("SELECT sql FROM sqlite_master WHERE name=?",
                                                             (base,)).fetchone()[0]).group(1))
        for (blob,) in conn.execute(f'SELECT vectors FROM "{table}"'):
            blob = bytes(blob)
            if any(blob[i:i + 4 * dim] in wanted for i in range(0, len(blob), 4 * dim)):
                return True
    return False


_PLANTED_VECTORS: dict[str, list[bytes]] = {}


def planted_vectors(store: Storage) -> list[bytes]:
    """The 3,072-byte embedding of every left-out vector row ``canary_store`` planted in ``store``."""
    return _PLANTED_VECTORS[str(store.db_path)]


def _fill(conn: sqlite3.Connection, table: str, canary, **values) -> None:
    """Insert one row: ``values`` as given, every other TEXT, JSON or BLOB column without a default a fresh canary."""
    row = dict(values)
    ddl = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (table,)).fetchone()[0]
    for col, allowed in re.findall(r"(\w+)\s+IN\s*\(([^)]*)\)", ddl):      # an enum with a CHECK: its first value
        row.setdefault(col, allowed.split(",")[0].strip().strip("'\""))
    for _, name, typ, _, default, pk in conn.execute(f"PRAGMA table_info({table})").fetchall():
        if name in row:
            continue
        typ = typ.upper()
        if typ in ("TEXT", "JSON"):
            if default is not None:             # an enum such as ``status`` (it has a CHECK), not free text
                continue
            row[name] = canary()
        elif typ == "BLOB":
            row[name] = canary().encode()
        elif default is None:
            row[name] = 1                       # a required number
    cols = ", ".join(f'"{c}"' for c in row)
    conn.execute(f"INSERT INTO {table} ({cols}) VALUES ({', '.join('?' * len(row))})", list(row.values()))


def canary_store(tmp_path: Path) -> tuple[Storage, list[str]]:
    """The anti-goal fixture of I 16: a route plan's store (kept work-lane memories ``e0`` to ``e2``, ``s1``, a
    recall) with a unique random string in every TEXT column of every left-out row and of every dropped table, in
    a recall's query and outcome note, and in the files beside the store; some canaries share a 14-letter prefix
    with a shipped term, some are UUIDs (split at hyphens by the tokenizer), some sit in long values across an
    overflow page boundary, and every left-out vector row holds a unique 3,072-byte vector. Returns the store
    and every canary."""
    import secrets

    import numpy as np
    from storage import _pack_embedding

    canaries: list[str] = []

    def canary(prefix: str = "") -> str:
        c = prefix + secrets.token_hex(10)
        canaries.append(c)
        return c

    def uuid_canary() -> str:
        c = str(uuid.uuid4())
        canaries.append(c)
        return c

    s = new_store(tmp_path, "src")
    conn = s.conn
    shipped_word = "uncharacteristically"       # a shipped term; the canaries below share its first 14 letters
    ep(s, "e0", content=f"Jenn drove the truck to the clinic, trip 0, {shipped_word}", session="sx",
       at="2026-10-25T09:00:00+00:00")
    vec(s, "episode", "e0", seed=100)
    for i in (1, 2):
        ep(s, f"e{i}", content=f"Jenn drove the truck to the clinic, trip {i}", session="sx",
           at=f"2026-10-25T10:{i:02d}:00+00:00")
        vec(s, "episode", f"e{i}", seed=i)
    sem(s, "s1", sources=["e1"], at="2026-10-25T12:00:00+00:00")
    vec(s, "semantic", "s1", seed=99)

    conn.execute("PRAGMA foreign_keys=OFF")
    seeds = iter(range(1000, 2000))
    left_vectors: list[bytes] = []

    def left_out_vector(table: str, id: str) -> None:
        dim = int(re.search(r"float\[(\d+)\]", conn.execute("SELECT sql FROM sqlite_master WHERE name=?",
                                                             (table,)).fetchone()[0]).group(1))
        v = np.random.default_rng(next(seeds)).standard_normal(dim)       # 768 (3,072 bytes), but residue's is 64
        blob = _pack_embedding((v / np.linalg.norm(v)).tolist())
        assert len(blob) == 4 * dim
        conn.execute(f"INSERT INTO {table} (id, embedding) VALUES (?, ?)", (id, blob))
        left_vectors.append(blob)

    # Left-out episodes: another lane, and a work-lane episode too new for the plan.
    long_value = ""
    page = conn.execute("PRAGMA page_size").fetchone()[0]
    left_ids = []
    for lane, at in (("personal", "2026-10-25T09:30:00+00:00"), ("work", "2026-10-25T20:00:00+00:00")):
        id = uuid_canary()
        left_ids.append(id)
        _fill(conn, "episodes", canary, id=id, lane=lane, created_at=at, core=0, dormant=0,
              content=canary("uncharacteristic") + " " + canary(), context=f'{{"k": "{canary()}"}}')
        left_out_vector("episode_vectors", id)
    # A long value with left-out UUIDs at offsets that cross every overflow boundary of its payload.
    for offset in (page - 18, 2 * page - 18, 3 * page - 5):
        long_value += "x" * (offset - len(long_value)) + uuid_canary()
    long_id = uuid_canary()
    _fill(conn, "episodes", canary, id=long_id, lane="personal", created_at="2026-10-25T09:40:00+00:00", core=0,
          dormant=0, content=long_value + "y" * (3 * page), context=None)
    left_out_vector("episode_vectors", long_id)

    # Left-out semantics (and what ties them to left-out episodes).
    sid = uuid_canary()
    _fill(conn, "semantics", canary, id=sid, lane="personal", created_at="2026-10-25T09:50:00+00:00", kind="fact",
          content=canary("uncharacteristic"), contradicted_by=None)
    left_out_vector("semantic_vectors", sid)
    _fill(conn, "semantic_sources", canary, semantic_id=sid, episode_id=left_ids[0])
    _fill(conn, "resonances", canary, id=uuid_canary(), memory_a=left_ids[0], layer_a="episode", memory_b="e1",
          layer_b="episode", created_at="2026-10-25T09:55:00+00:00", last_seen="2026-10-25T09:55:00+00:00")
    _fill(conn, "semantic_peers", canary, peer_id=sid, parent_id="s1", created_at="2026-10-25T09:55:00+00:00")
    _fill(conn, "subdivision_events", canary, id=uuid_canary(), parent_id=sid, peer_ids=f'["{uuid_canary()}"]',
          site="sleep", created_at="2026-10-25T09:55:00+00:00")

    # Every dropped table: a row of canaries (the hook tables are not in graph.db, and the shadows of vec0 tables
    # are filled by their embeddings below).
    from imprint_filter import HOOK_TABLES, TABLE_RULES

    for table, rule in TABLE_RULES.items():
        if rule != "dropped" or table in HOOK_TABLES or table.endswith("_vectors"):
            continue
        _fill(conn, table, canary, **({"instinct_a": canary("a"), "instinct_b": canary("b")}   # CHECK a < b
                                      if table == "instinct_co_firing" else {}))
    for table in ("instinct_vectors", "instinct_context_vectors", "entity_vectors", "residue_vectors"):
        left_out_vector(table, uuid_canary())
    inst_id = inst(s, uuid_canary())

    # The log: a query and an outcome note on a kept recall, a recall of left-out memories and an instinct, an
    # operation that carries free text, and a route_shown row with a query.
    recall(s, "l1", targets=["e1"], session="sx", outcome=f"used: {canary()}", recall_id="rc1", query=canary(),
           note=canary())
    recall(s, "l2", targets=["e2", inst_id], session="sx", outcome=f"not_used {canary()}", recall_id="rc2",
           query=canary())
    recall(s, "l3", targets=[left_ids[0]], session="sx", outcome="used", recall_id="rc3", query=canary())
    route_shown(s, "l4", targets=["e1", left_ids[0]], session="sx", query=canary(), cut=canary())
    op(s, "o1", session="sx", at="2026-10-25T10:20:00+00:00", operation="mark_core", targets=["e1"],
       harness=canary(), model=canary(), repo=canary(), details={"note": canary()})
    conn.execute("PRAGMA foreign_keys=ON")
    conn.commit()

    # The stores beside graph.db (the plan never reads them, so nothing of them may arrive).
    import sqlite3 as _sq

    for name in ("cold.db", "categories.db", "categories_v2.db", "clipboard.db", "notepad.db"):
        side = _sq.connect(tmp_path / name)
        side.execute("CREATE TABLE notes (id TEXT, body TEXT)")
        side.execute("INSERT INTO notes VALUES (?, ?)", (uuid_canary(), canary()))
        side.commit()
        side.close()
    _PLANTED_VECTORS[str(s.db_path)] = left_vectors
    return s, canaries


# Task 21: recall-row touches. The reader below is written from the trail spec's section 4 alone and imports nothing
# from imprint*.py or trails.py.

def iso_of(seconds: int) -> str:
    """UTC seconds to the ISO-8601 text a plan's ``until`` takes."""
    from datetime import datetime, timezone

    return datetime.fromtimestamp(seconds, timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _at(text: str) -> int:
    from datetime import datetime

    return int(datetime.fromisoformat(text).timestamp())


def _uid(n: int) -> str:
    return str(uuid.UUID(int=n))


def mixed_lane_recall_store(tmp_path: Path, fixture: str) -> tuple[Storage, int]:
    """A route plan's store with a closed session ``sx``, plus its end ``t1`` (18:00 UTC). Kept work-lane episodes
    ``e0``, ``e1``, ``e2`` (uuid ids, so a mention is never an accident) and ``e3`` (naming ``e1`` and ``e2``); a
    personal ``p1``; a ``route_shown`` row listing ``e1``; used recalls of ``[instinct, e2, e1]`` (cited by ``e3``),
    of ``[e0]`` (one target), of ``[instinct, e2]`` (one target once the instinct goes), and of ``[e0, e1]`` (cited by
    an operation); a not-used recall; and a mixed-lane used recall ``[e2, p1]`` and a used recall of ``[p1]`` that
    stay home. ``nothing_at_or_after_t1`` adds a session open at t1 and no row at or after t1 (XS1);
    ``as_of_t1_nothing_at_t1`` adds rows after t1 and none at exactly t1."""
    assert fixture in ("nothing_at_or_after_t1", "as_of_t1_nothing_at_t1")
    t1 = T("2026-10-25T18:00:00Z")
    s = new_store(tmp_path, "src")
    day = "2026-10-25T"
    e0, e1, e2, p1, e3 = (_uid(i) for i in range(1, 6))
    ep(s, e0, content="Jenn drove the truck to the clinic, trip 0", session="sx", at=day + "09:00:00+00:00")
    ep(s, e1, content="Jenn drove the truck to the clinic, trip 1", session="sx", at=day + "10:01:00+00:00")
    ep(s, e2, content="Jenn drove the truck to the clinic, trip 2", session="sx", at=day + "10:02:00+00:00")
    ep(s, p1, content="A private errand", lane="personal", session="sx", at=day + "10:03:00+00:00")
    ep(s, e3, content=f"Went back over {e1} and then {e2}.", session="sx", at=day + "11:30:00+00:00")
    for i, id in enumerate((e0, e1, e2, e3)):
        vec(s, "episode", id, seed=i + 1)
    key, key2 = inst(s, _uid(100)), inst(s, _uid(101))
    route_shown(s, "rs1", targets=[e1, p1], session="sx", at=day + "10:50:00+00:00")
    recall(s, "l1", targets=[key, e2, e1], session="sx", at=day + "11:00:00+00:00", outcome="used: auto: cited",
           recall_id="rc1")
    recall(s, "l2", targets=[e2, p1], session="sx", at=day + "12:00:00+00:00", outcome="used", recall_id="rc2")
    recall(s, "l2b", targets=[p1], session="sx", at=day + "12:30:00+00:00", outcome="used", recall_id="rc2b")
    recall(s, "l3", targets=[e0], session="sx", at=day + "13:00:00+00:00", outcome="used", recall_id="rc3")
    recall(s, "l4", targets=[key2, e2], session="sx", at=day + "14:00:00+00:00", outcome="used", recall_id="rc4")
    recall(s, "l6", targets=[e0, e1], session="sx", at=day + "14:20:00+00:00", outcome="used", recall_id="rc6")
    op(s, "o1", session="sx", at=day + "14:30:00+00:00", operation="mark_core", targets=[e1])
    recall(s, "l5", targets=[e1], session="sx", at=day + "14:40:00+00:00", outcome="not_used", recall_id="rc5")
    if fixture == "nothing_at_or_after_t1":
        ep(s, _uid(7), content="Still working at t1", session="sy", at=day + "17:30:00+00:00")
    else:
        ep(s, _uid(7), content="Back again after t1", session="sx", at=day + "23:20:00+00:00")
        ep(s, _uid(8), content="Another session after t1", session="sz", at=day + "18:01:40+00:00")
    return s, t1


@dataclass(frozen=True)
class Touch:
    session: str
    memory: str
    kind: str                 # "wrote" or "cited"
    time: int
    rank: int
    recall_id: str | None
    suggested: bool


def touches_from(path: Path, as_of: int) -> list[Touch]:
    """Wrote and cited touches of every closed session as of ``as_of`` (trail spec section 4), in no set order."""
    import json

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        instincts = {r[0] for r in conn.execute("SELECT id FROM instincts")} if "instincts" in names else set()
        episodes = [(i, s, _at(c), content or "", ctx or "") for i, s, c, content, ctx in conn.execute(
            "SELECT id, session_id, created_at, content, context FROM episodes") if _at(c) <= as_of]
        logs = []
        for id, at, event, targets, ctx in conn.execute(
                "SELECT id, timestamp, event_type, target_ids, context FROM memory_log "
                "WHERE event_type IN ('recall', 'route_shown')"):
            if _at(at) > as_of:
                continue
            c = json.loads(ctx) if ctx else {}
            logs.append((id, _at(at), event, json.loads(targets), c.get("session_id"), c.get("recall_id")))
        ops = [(s, _at(at), op_, json.loads(t)) for s, at, op_, t in conn.execute(
            "SELECT session_id, timestamp, operation, target_ids FROM operation_log") if _at(at) <= as_of]
        existing = {r[0] for r in conn.execute("SELECT id FROM episodes UNION SELECT id FROM semantics")}
    finally:
        conn.close()
    newest: dict[str, int] = {}
    made = {s for _, s, *_ in episodes if s} | {s for _, _, e, _, s, _ in logs if e == "recall" and s}
    for _, s, at, *_ in episodes:
        if s:
            newest[s] = max(newest.get(s, at), at)
    for _, at, _, _, s, _ in logs:
        if s in made:                       # a route_shown row never makes a session by itself
            newest[s] = max(newest.get(s, at), at)
    closed = {s for s in made if newest[s] < as_of - 3600}
    out = [Touch(s, i, "wrote", at, 0, None, False) for i, s, at, *_ in episodes if s in closed]
    citing = {"mark_core", "instinct_feedback", "dream_react"}
    for id, at, event, targets, s, rid in logs:
        if event != "recall" or s not in closed:
            continue
        outcome = conn_outcome(path, id)
        if not (outcome or "").startswith("used"):
            continue
        targets = [t for t in targets if t not in instincts]
        for rank, m in enumerate(targets):
            later_text = any(es == s and eat > at and (m in content or m in ctx)
                             for _, es, eat, content, ctx in episodes)
            later_op = any(os == s and oat > at and o in citing and m in ot for os, oat, o, ot in ops)
            if m in existing and (later_text or later_op or len(targets) == 1):
                shown = any(k == "route_shown" and ks == s and kat <= at and m in kt
                            for _, kat, k, kt, ks, _ in logs)
                out.append(Touch(s, m, "cited", at, rank, rid or id, shown))
    return out


def conn_outcome(path: Path, id: str) -> str | None:
    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        row = conn.execute("SELECT outcome FROM memory_log WHERE id = ?", (id,)).fetchone()
    finally:
        conn.close()
    return row[0] if row else None


def order_within_recalls(touches, only=None) -> dict:
    """Each recall's cited memories in delivered order (rank), for the recalls in ``only`` when given."""
    by: dict = {}
    for t in sorted((t for t in touches if t.kind == "cited"), key=lambda t: (t.recall_id, t.rank)):
        if only is None or t.recall_id in only:
            by.setdefault(t.recall_id, []).append(t.memory)
    return by


def recalls_of(touches) -> set:
    return {t.recall_id for t in touches if t.kind == "cited"}


def _recall_rows(path: Path):
    import json

    conn = sqlite3.connect(f"file:{path}?mode=ro", uri=True)
    try:
        names = {r[0] for r in conn.execute("SELECT name FROM sqlite_master")}
        instincts = {r[0] for r in conn.execute("SELECT id FROM instincts")} if "instincts" in names else set()
        rows = conn.execute("SELECT id, target_ids, context, outcome FROM memory_log WHERE event_type = 'recall'"
                            ).fetchall()
    finally:
        conn.close()
    for id, targets, ctx, outcome in rows:
        c = json.loads(ctx) if ctx else {}
        yield c.get("recall_id") or id, [t for t in json.loads(targets) if t not in instincts], outcome


def exactly_one_target_answers(path: Path, only=None) -> dict:
    """For each used recall row (in ``only`` when given): does the rule "exactly one target, instincts removed" hold."""
    return {rid: len(targets) == 1 for rid, targets, outcome in _recall_rows(path)
            if (outcome or "").startswith("used") and (only is None or rid in only)}


def kept_recalls(built) -> set:
    """The recall ids of the package's recall rows."""
    return {rid for rid, _, _ in _recall_rows(built.dir / "imprint.db")}


# ---------------------------------------------------------------- Task 28: P's meet over the ceiling fixture

_AGENT = "agent:station-imprints"
_CALIB, _TRAILEV = "calibration", "trail-evaluation"
_CEILING_C = frozenset({("recall", _CALIB), ("read", _CALIB), ("imprint", _CALIB), ("recall", _TRAILEV),
                        ("read", _TRAILEV), ("imprint", _TRAILEV), ("route", _TRAILEV)})
_STATUS_FOR = {"admission": "approved", "trail-evaluation": "admitted"}
_BATCH = 512
_MEMORIES = 40
_TOUCHES = {"road": {"r2": 2}, "trail": {"t3": 3, "t40": 40}}


def _memories_of(source: str) -> tuple:
    return tuple(f"mem:{source}/episode/m{i}" for i in range(1, _MEMORIES + 1))


def _derived_of(source: str) -> dict:
    """R(I) of every copy of `source` in the world: its roads and trails, each with the memories it names. Every
    memory a road or trail names is in objects(I)."""
    mem = _memories_of(source)
    return {f"{kind}:{source}/{name}": mem[:n] for kind, names in _TOUCHES.items() for name, n in names.items()}


def _effective_end(permission: dict, receipts: list) -> int:
    return min([r["valid_until"] for r in permission["records"]]
               + [x["detail"]["valid_until"] for x in receipts if x["event"] == "shortened"])


def ceiling_world(fixture: dict):
    """(State, ceiling) for the ceiling fixture: P 5.5's tables built with `World`. Persons `sam` and `andy` (the
    operator), `agent:station-imprints` acting for andy in `place:home/andy`, each source store with its owner, each
    imprint a store held at the operator's home, its collection and members, and every inner record in its owner's
    home layer (a record the owner withdrew is revoked; the owner's shortenings cut `valid_until`, as a replacement
    does; the ship's act on the ceiling only). The ceiling is I 8's items 1 to 5, for the layer kept outside a
    ledger for the operator's home (P 6.1; XM1), so the operator's own records add nothing there."""
    imprints = fixture["imprints"]
    start = min(i["permission"]["created"] for i in imprints.values())
    w = World(owner=fixture["operator"], start=start)
    operator = f"person:{fixture['operator']}"
    home = f"place:home/{fixture['operator']}"
    owners = {i["permission"]["owner"] for i in imprints.values()} - {operator}
    for owner in sorted(owners):
        w.person(owner)
    w.agent("station-imprints", home, at=home)
    sources = {i["permission"]["source_instance_id"]: i["permission"]["owner"] for i in imprints.values()}
    for source, owner in sorted(sources.items()):
        w.store(source, owner=owner, place=f"place:home/{owner.split(':', 1)[1]}")
    info = {}
    for name, imp in imprints.items():
        p, receipts = imp["permission"], imp["receipts"]
        source, owner_id = p["source_instance_id"], p["owner_id"]
        w.store(p["imprint_id"], owner=operator, place=home, imprint_of=source)
        w.now = p["created"]
        collection = next(r["selector"]["objects"]["collections"][0] for r in p["records"]
                          if r["selector"]["objects"]["collections"] != "*")
        w.collect(collection, _memories_of(source))
        withdrawn_by_owner = [r for r in receipts if r["event"] == "withdrawn" and r["actor_id"] == owner_id]
        cut = [r["detail"]["valid_until"] for r in receipts
               if r["event"] == "shortened" and r["actor_id"] == owner_id]
        for r in p["records"]:
            sel, obj = r["selector"], r["selector"]["objects"]
            rid = w.allow(r["layer"], audience=sel["audience"], requesters=sel["requesters"], stores=obj["stores"],
                          kinds=obj["kinds"], collections=obj["collections"], actions=sel["actions"],
                          purposes=sel["purposes"], valid_from=r["valid_from"],
                          valid_until=min([r["valid_until"]] + cut))
            if withdrawn_by_owner:
                w.now = withdrawn_by_owner[0]["at"]
                w.revoke(rid)
                w.now = p["created"]
        info[p["imprint_id"]] = dict(permission=p, receipts=receipts, source=source,
                                     objects=frozenset(_memories_of(source)), derived=_derived_of(source),
                                     route=any("route" in r["selector"]["actions"] for r in p["records"]),
                                     end=_effective_end(p, receipts),
                                     start=min(r["valid_from"] for r in p["records"]),
                                     withdrawn=[x["at"] for x in receipts if x["event"] == "withdrawn"])
    state = w.state()

    def ceiling(sub, action) -> str:
        """I 8, items 1 to 5, for the uses of every copy at the station."""
        imp = info.get(sub.copy.rpartition("/")[2])
        if imp is None or sub.requester != _AGENT or sub.place != home:                         # item 1
            return "silent"
        p, x, purpose, t = imp["permission"], action, sub.purpose, sub.at

        def holds(kind: str, objects: dict) -> bool:
            for r in p["records"]:
                sel = r["selector"]
                if kind in sel["objects"]["kinds"] and x in sel["actions"] and purpose in sel["purposes"]:
                    return sub.obj in objects
            return False

        if not (holds("memory", imp["objects"]) or holds("road", imp["derived"]) or holds("trail", imp["derived"])):
            return "silent"                                                                     # item 2
        if (x, purpose) not in _CEILING_C:                                                      # item 3
            return "silent"
        if not (imp["start"] <= t < imp["end"]):                                                # item 4
            return "silent"
        if any(t >= at for at in imp["withdrawn"]):                                             # item 5
            return "silent"
        return "allow"

    ceiling.info = info
    return state, ceiling


def status_ok(fixture: dict, case: dict) -> bool:
    """The status conjunct of I 8's rule `allowed(k, t) <=> status(I) in Status(k) and Need(k, t) in meet`; the
    permissions spec has no status, so the test applies it beside `decide_bulk`."""
    status = case.get("status", fixture["imprints"][case["imprint"]]["status"])
    return status == _STATUS_FOR[case["kind"]]


def _batches(objects) -> list:
    objects = list(objects)
    return [tuple(objects[i:i + _BATCH]) for i in range(0, len(objects), _BATCH)] or [()]


def _bulk(fixture: dict, name: str, objects, action: str, purpose: str, at: int, *, named: bool, names=lambda o: ()):
    from permissions import BulkUse

    p = fixture["imprints"][name]["permission"]
    return BulkUse(requester=_AGENT, place=f"place:home/{fixture['operator']}",
                   objects=tuple(objects), copy=f"imprint:{p['station']}/{p['imprint_id']}", action=action,
                   purpose=purpose, at=at, named=named, names=names)


def bulk_uses_of(fixture: dict, case: dict) -> list:
    """Need(kind) as P's bulk uses (I 8, "Bulk uses"): the memories named, in batches of 512, and R(I) counted. R(I)
    is every road and trail of the source in the world, whether or not the copy has `route`, so a copy without
    `route` is refused by its own ceiling."""
    name, at = case["imprint"], case["t"]
    p = fixture["imprints"][name]["permission"]
    memories, derived = _memories_of(p["source_instance_id"]), _derived_of(p["source_instance_id"])
    route = any("route" in r["selector"]["actions"] for r in p["records"])
    uses = []
    if case["kind"] == "admission":
        uses += [_bulk(fixture, name, b, "imprint", _CALIB, at, named=True) for b in _batches(memories)]
        if route:
            uses += [_bulk(fixture, name, b, "read", _TRAILEV, at, named=True) for b in _batches(memories)]
            uses.append(_bulk(fixture, name, derived, "imprint", _TRAILEV, at, named=False, names=derived.__getitem__))
    else:
        uses += [_bulk(fixture, name, b, "read", _TRAILEV, at, named=True) for b in _batches(memories)]
        uses.append(_bulk(fixture, name, derived, "route", _TRAILEV, at, named=False, names=derived.__getitem__))
    return uses


def evaluation_route_bulk(fixture: dict, name: str, *, touches: int, at: int | None = None):
    """The counted bulk `route` use of a trail evaluation on one trail that names `touches` memories."""
    source = fixture["imprints"][name]["permission"]["source_instance_id"]
    derived = _derived_of(source)
    trail = next(ref for ref in derived if ref.startswith("trail:") and len(derived[ref]) == touches)
    return _bulk(fixture, name, (trail,), "route", _TRAILEV, fixture["now"] if at is None else at, named=False,
                 names=derived.__getitem__)


# ---- Admission (Tasks 32 and 33) -----------------------------------------------------------------------------------

FAR = 4_102_444_800                 # 2100-01-01: a valid_until no test reaches
MIGRATIONS = store_reader.MIGRATIONS_DIR


def built_package(tmp_path: Path, **plan_kw):
    """The ``Built`` of a plan made by ``plan_args(tmp_path, **plan_kw)`` and built at once."""
    from imprint import build, make_plan

    plan = make_plan(*plan_args(tmp_path, **plan_kw))
    return build(plan.id, home=HOME(tmp_path), now=1_761_415_451, engram_home=EH(tmp_path))


def stub_verify(*, ok: bool) -> list[str]:
    """A ``verify_cmd`` that exits 0 or 1 whatever file it is given (the peer's ``verify-imprint`` stands behind R9)."""
    import sys

    return [sys.executable, "-c", f"import sys; sys.exit({0 if ok else 1})"]


def handed_off(tmp_path: Path, built, *, route: bool, valid_until: int, owner: str = "andy") -> tuple[Path, str]:
    """``(root, imprint id)``: a root laid out as the station's hand-off leaves it (I 10): ``<id>/`` holding
    ``imprint.db``, ``manifest.json``, ``permission.json`` and ``approved.json``, and ``<id>.state/`` holding
    ``admission.json``. The permission's signature is a stub; ``stub_verify`` stands in for the peer. The record has the
    shape the station writes (``peer`` ``permission_record``): ``owner`` is ``person:<owner>``, ``attestation`` follows
    whether the audience (always the operator ``andy``'s home) is the owner's, and ``route`` adds r_T."""
    import json

    root = tmp_path / "root"
    imprint_id = built.imprint_id
    folder, state = root / imprint_id, root / f"{imprint_id}.state"
    folder.mkdir(parents=True, mode=0o700)
    state.mkdir(mode=0o700)
    for name in ("imprint.db", "manifest.json"):
        shutil.copyfile(built.dir / name, folder / name)
    manifest = built.manifest
    created, source = 1_761_415_451, manifest["source"]["instance_id"]
    purposes = ["calibration", "trail-evaluation"] if route else ["calibration"]

    def inner(kinds, actions, purposes, collections):
        return {"id": "r-" + "0" * 32, "layer": f"place:home/{owner}", "effect": "allow",
                "valid_from": created, "valid_until": created + 604_800,
                "selector": {"audience": ["place:home/andy"], "requesters": ["agent:station-imprints"],
                             "objects": {"kinds": kinds, "collections": collections, "stores": [source]},
                             "actions": actions, "purposes": purposes}}

    records = [inner(["memory"], ["imprint", "read", "recall"], purposes, [f"collection:{owner}/imprint-{imprint_id}"])]
    if route:
        records.append(inner(["road", "trail"], ["imprint", "read", "recall", "route"], ["trail-evaluation"], "*"))
    record = {"kind": "imprint-permission", "station": "ab" * 32, "id": str(uuid.uuid4()), "owner": f"person:{owner}",
              "owner_id": "u1", "ship_id": "s1", "imprint_id": imprint_id,
              "source_instance_id": source,
              "request_sha256": manifest["request_sha256"], "plan_digest": manifest["plan_digest"],
              "attestation": "others-copied-at-home-v1" if owner == "andy" else "no-unconsented-others-v1",
              "created": created, "records": records}
    (folder / "permission.json").write_text(json.dumps({"record": record, "signature": "", "station_key": ""}))
    (folder / "approved.json").write_text(json.dumps({"imprint_id": imprint_id, "request_id": "r1",
                                                      "approved_at": 1_761_415_500, "approved_by": "andy"}))
    (state / "admission.json").write_text(json.dumps({"kind": "imprint-admission-allow", "instance_id": imprint_id,
                                                      "decided_at": 1_761_415_500, "valid_until": valid_until}))
    return root, imprint_id


def _refix_package(folder: Path) -> None:
    """Set ``manifest.package`` to the facts of the file as it now is, so checks 1 and 2 pass."""
    import json

    from imprint import _package_facts

    manifest = json.loads((folder / "manifest.json").read_text())
    parts = manifest["package"]["part_bytes"]
    size = (folder / "imprint.db").stat().st_size
    sha, hashes, size = _package_facts(folder / "imprint.db", max(1, -(-size // parts)))
    manifest["package"].update(bytes=size, sha256=sha, parts=hashes)
    (folder / "manifest.json").write_text(json.dumps(manifest))


def _edit_db(path: Path, *statements: str) -> None:
    conn = sqlite3.connect(path)
    try:
        load_vec(conn)
        for sql in statements:
            conn.execute(sql)
        conn.commit()
    finally:
        conn.close()


_DB_CHANGES = {
    "unknown_migration": ("INSERT INTO schema_version (version, applied_at) VALUES (9999, 'x')",),
    "planted_trigger": ("CREATE TRIGGER planted AFTER INSERT ON episodes BEGIN SELECT 1; END",),
    "extra_table": ("CREATE TABLE rides_along (x TEXT)",),
    "other_vec_info": ("UPDATE episode_vectors_info SET value = 'v0.0.0' WHERE key = 'CREATE_VERSION'",),
    "changed_meta": ("UPDATE meta SET value = 'not-the-id' WHERE key = 'forked_from_instance_id'",),
    "non_empty_dropped_table": ("INSERT INTO session_registry (session_id, harness, model, repo, started_at) "
                                "VALUES ('x', 'h', 'm', 'r', '2026-01-01')",),
}


_HOME_PLAN = {"owner": "andy", "cosubjects": {"e1": "person:jenn"}}      # a copy that stays at home, with a co-subject
_BUILDS = {                                  # how the package of a tamper kind is built (default: owner sam, no route)
    "dangling_target": {"route": True}, "unscrubbed_context": {"route": True}, "instinct_id_in_recall": {"route": True},
    "subject_row_for_a_missing_memory": _HOME_PLAN, "subject_row_naming_the_owner": _HOME_PLAN,
    "others_disagree_with_the_rows": _HOME_PLAN,
}
_INSTINCT = "5d1c0f3a-9b7e-4c2a-8f61-0a3b5c7d9e11"
_BIG = "replace(hex(zeroblob(20000)), '0', 'x')"
_DB_CHANGES.update({
    "dangling_target": ("UPDATE memory_log SET target_ids = '[\"no-such-memory\"]'",),
    "instinct_id_in_recall": (f"UPDATE memory_log SET target_ids = '[\"e1\", \"{_INSTINCT}\"]'",),
    "unscrubbed_context": ("UPDATE memory_log SET context = "
                           "'{\"recall_id\": \"rc1\", \"session_id\": \"sx\", \"query\": \"private words\"}'",),
    "lane_outside_scope": ("UPDATE episodes SET lane = 'personal' WHERE id = 'e1'",),
    "time_outside_scope": ("UPDATE episodes SET created_at = '2030-01-01T00:00:00+00:00' WHERE id = 'e1'",),
    "session_id_without_route": ("UPDATE episodes SET session_id = 'sx' WHERE id = 'e1'",),
    "digest_mismatch": ("UPDATE episodes SET content = 'Jenn drove somewhere else' WHERE id = 'e1'",),
    "free_page": (f"INSERT INTO episodes (id, content, created_at, lane) VALUES ('big', {_BIG}, "
                  "'2026-10-25T11:00:00+00:00', 'work')", "DELETE FROM episodes WHERE id = 'big'"),
    "rowid_gap": ("UPDATE episodes SET rowid = 50 WHERE id = 'e2'",),
    "fts_orphan": ("INSERT INTO episode_fts (episode_fts, rowid, content) VALUES ('delete', 2, "
                   "'Jenn drove the truck to the clinic, trip 1')",
                   "INSERT INTO episode_fts (rowid, content) VALUES (2, 'something the row never said')"),
    "subject_row_for_a_missing_memory": ("INSERT INTO imprint_subjects VALUES ('no-such-memory', 'episode', 'person:jenn')",),
    "subject_row_naming_the_owner": ("INSERT INTO imprint_subjects VALUES ('e2', 'episode', 'person:andy')",),
    "subject_row_in_a_copy_leaving_home": ("INSERT INTO imprint_subjects VALUES ('e1', 'episode', 'person:jenn')",),
})


def open_checked(folder: Path):
    """``(conn, manifest)``: the package opened as admission opens it, for one check at a time."""
    import json

    return (store_reader.connect(folder / "imprint.db", immutable=True, vec=True),
            json.loads((folder / "manifest.json").read_text()))


def tampered(tmp_path: Path, change: str) -> tuple[Path, str]:
    """``(root, imprint id)`` of a handed-off package with one defect. For a defect inside ``imprint.db``,
    ``manifest.package`` is then set to the file's facts, so every check before the target passes."""
    import json

    kind = _BUILDS.get(change, {})
    root, imprint_id = handed_off(tmp_path, built_package(tmp_path, **kind), route=kind.get("route", False),
                                  valid_until=FAR, owner=kind.get("owner", "sam"))
    folder = root / imprint_id
    db = folder / "imprint.db"
    if change == "extra_file":
        (folder / "extra.txt").write_text("x")
    elif change == "symlinked_manifest":
        real = tmp_path / "elsewhere.json"
        (folder / "manifest.json").rename(real)
        (folder / "manifest.json").symlink_to(real)
    elif change == "changed_byte":
        data = bytearray(db.read_bytes())
        data[-1] ^= 0xFF
        db.write_bytes(bytes(data))
    elif change == "permission_fails_verify":
        pass
    elif change == "request_sha256_differs":
        manifest = json.loads((folder / "manifest.json").read_text())
        manifest["request_sha256"] = "0" * 64
        (folder / "manifest.json").write_text(json.dumps(manifest))
    elif change == "wal_header":
        data = bytearray(db.read_bytes())
        data[18] = data[19] = 2
        db.write_bytes(bytes(data))
        _refix_package(folder)
    elif change == "corrupt_page":
        size = int.from_bytes(db.read_bytes()[16:18], "big")
        with open(db, "r+b") as f:
            f.seek(size)                                    # page 2
            f.write(b"\xff" * size)
        _refix_package(folder)
    elif change == "others_disagree_with_the_rows":
        manifest = json.loads((folder / "manifest.json").read_text())
        manifest["others"]["people"] += 1
        (folder / "manifest.json").write_text(json.dumps(manifest))
    elif change == "non_zero_invalid_vec0_slot":
        conn = sqlite3.connect(db)
        try:
            validity = bytearray(conn.execute("SELECT validity FROM episode_vectors_chunks").fetchone()[0])
            validity[0] &= 0xFE                         # slot 0 invalid, but its rowid and vector bytes stay
            conn.execute("UPDATE episode_vectors_chunks SET validity = ?", (bytes(validity),))
            conn.commit()
        finally:
            conn.close()
        _refix_package(folder)
    elif change in _DB_CHANGES:
        _edit_db(db, *_DB_CHANGES[change])
        _refix_package(folder)
    else:
        raise ValueError(change)
    return root, imprint_id


# ---- Admission (Task 34) --------------------------------------------------------------------------------------

def built_texts(tmp_path: Path) -> list[str]:
    """The text of every memory in the source store ``plan_args(tmp_path)`` planned from."""
    return memory_texts(_path(tmp_path, "src"))


def session_ids(tmp_path: Path) -> list[str]:
    """The session ids the source store's episodes hold."""
    conn = sqlite3.connect(f"file:{_path(tmp_path, 'src')}?mode=ro", uri=True)
    try:
        return [r[0] for r in conn.execute("SELECT DISTINCT session_id FROM episodes WHERE session_id IS NOT NULL")]
    finally:
        conn.close()


def no_memory_text(report, texts) -> bool:
    import json

    dumped = json.dumps(report, default=str)
    return all(text[:24] not in dumped for text in texts)


def mentions_any(report, ids) -> bool:
    import json

    dumped = json.dumps(report, default=str)
    return any(f'"{i}"' in dumped for i in ids)


def survey_minus(report: dict) -> dict:
    """The snapshot survey without what ``route`` legitimately changes: the episodes' session count, the log tables'
    row counts, the file facts and the identity."""
    import copy

    snap = copy.deepcopy(report["snapshot"])
    snap.get("episodes", {}).pop("sessions", None)
    for name in ("memory_log", "operation_log"):
        snap.get("row_counts", {}).pop(name, None)
    snap.pop("file", None)
    snap.pop("identity", None)
    return snap


def raise_(exc: BaseException):
    def fn(*args, **kwargs):
        raise exc

    return fn


def must_not_be_called(*args, **kwargs):
    raise AssertionError("this must not run")


class Withdrawal:
    """What a withdrawal does on the Pi: both directories go, and a tombstone is written. Callable in process, or as
    a command (for a ``verify_cmd``, which runs in a child)."""

    def __init__(self, root: Path, imprint_id: str):
        self.root, self.imprint_id = Path(root), imprint_id

    def __call__(self) -> None:
        for name in (self.imprint_id, f"{self.imprint_id}.state"):
            shutil.rmtree(self.root / name, ignore_errors=True)
        (self.root / "tombstones").mkdir(exist_ok=True)
        (self.root / "tombstones" / f"{self.imprint_id}.json").write_text("{}")

    def command(self) -> list[str]:
        import sys

        code = ("import shutil, sys\nfrom pathlib import Path\nroot, i = Path(sys.argv[1]), sys.argv[2]\n"
                "[shutil.rmtree(root / n, ignore_errors=True) for n in (i, i + '.state')]\n"
                "(root / 'tombstones').mkdir(exist_ok=True)\n(root / 'tombstones' / (i + '.json')).write_text('{}')\n")
        return [sys.executable, "-c", code, str(self.root), self.imprint_id]


def remove_like_withdrawal(root: Path, imprint_id: str) -> Withdrawal:
    return Withdrawal(root, imprint_id)


def hooked_verify(hook: Withdrawal) -> list[str]:
    return hook.command()


def hooked_calibrate(hook):
    """A ``calibrate_fn`` that runs ``hook`` first and then the real calibration."""
    def fn(*args, **kwargs):
        import calibrate

        hook()
        return calibrate.calibrate(*args, **kwargs)

    return fn


def shorten_admission_json(root: Path, imprint_id: str, *, to: int) -> None:
    import json

    path = Path(root) / f"{imprint_id}.state" / "admission.json"
    doc = json.loads(path.read_text())
    doc["valid_until"] = to
    path.write_text(json.dumps(doc))


def admitted_report(tmp_path: Path, *, route: bool, now) -> dict:
    """The ``report.json`` an admission of a fresh package leaves."""
    import json

    from imprint import admit

    root, imprint_id = handed_off(tmp_path, built_package(tmp_path, route=route), route=route, valid_until=FAR)
    assert admit(imprint_id, root=root, verify_cmd=stub_verify(ok=True), calibration_now=now,
                 derive=counting_stub(0)) == 0
    return json.loads((root / f"{imprint_id}.state" / "calibration" / "report.json").read_text())


# ---- Counting R(I) (Task 35) ---------------------------------------------------------------------------------------

def counting_stub(n: int):
    """A ``derive`` that counts ``n`` roads and trails in every lane and no session over the bound."""
    return per_lane_stub(defaultdict(lambda: n))


def per_lane_stub(lane_counts, too_large=None):
    """A ``derive`` that returns ``lane_counts[lane]`` and adds ``too_large[lane]`` to that call's own ``counts``."""
    too_large = too_large or {}

    def derive(conn, *, lane, as_of, counts):
        counts["sessions_too_large"] += too_large.get(lane, 0)
        return lane_counts[lane]

    return derive


def recording_stub(seen: list):
    """A ``derive`` that records its keywords in ``seen`` and counts nothing."""
    def derive(conn, *, lane, as_of, counts):
        seen.append({"lane": lane, "as_of": as_of})
        return 0

    return derive


def fixture_for(root: Path, imprint_id: str) -> dict:
    """The ceiling fixture's shape (Task 27) for one handed-off imprint, read from its ``permission.json``."""
    import json

    permission = json.loads((Path(root) / imprint_id / "permission.json").read_text())["record"]
    return {"operator": "andy", "now": permission["created"] + 1,
            "imprints": {"admitted": {"permission": permission, "receipts": [], "status": "approved"}}}


def as_bulk(use, root: Path, imprint_id: str):
    """P's bulk use for one ``UseRecord`` of admission: the memories of its batch, or R(I) counted. The decision reads
    an object only through its kind (I 8, "A finite check"), so the ceiling fixture's objects stand in for the package's."""
    fixture = fixture_for(root, imprint_id)
    source = fixture["imprints"]["admitted"]["permission"]["source_instance_id"]
    if use.object_kind == "memory":
        return _bulk(fixture, "admitted", _batches(_memories_of(source))[0], use.action, use.purpose, fixture["now"],
                     named=True)
    derived = _derived_of(source)
    return _bulk(fixture, "admitted", derived, use.action, use.purpose, fixture["now"], named=False,
                 names=derived.__getitem__)


def trail_rich_store(tmp_path: Path) -> Storage:
    """A route plan's store with a closed session of used recalls, cited touches and an operation (Task 21's)."""
    return mixed_lane_recall_store(tmp_path, "nothing_at_or_after_t1")[0]


def roads_and_trails_by_hand(trails, db: Path, *, as_of: int, lanes=("work",)) -> int:
    """The trail functions' count over ``lanes`` of one package, as the trails plan's ``roads_and_trails`` gives it."""
    conn = store_reader.connect(db, immutable=True)
    try:
        counts = {"sessions_too_large": 0}
        return sum(trails.roads_and_trails(conn, lane=lane, as_of=as_of * 10**6, counts=counts) for lane in lanes)
    finally:
        conn.close()


# ---- Using an imprint (Task 38) ------------------------------------------------------------------------------------

def _stub(code: str) -> list[str]:
    """A ``trails_cmd`` that runs ``code`` with the argv ``use`` appends in ``sys.argv[1:]``."""
    import sys

    return [sys.executable, "-c", code]


STUB_OK = _stub("import json, sys; print(json.dumps({'ok': True}))")
STUB_EXIT_3 = _stub("import sys; sys.exit(3)")
STUB_EXIT_1 = _stub("import sys; print('{}'); sys.exit(1)")
STUB_KILLED = _stub("import os, signal; os.kill(os.getpid(), signal.SIGKILL)")
STUB_PRINTS_ENV = _stub("import json, os; print(json.dumps({k: os.environ.get(k) for k in ('SQLITE_TMPDIR', 'TMPDIR', 'OPENBLAS_NUM_THREADS')}"
                        " | {'exists': os.path.isdir(os.environ['TMPDIR'])}))")
STUB_PRINTS_ARGV = _stub("import json, sys; print(json.dumps(sys.argv[1:]))")


def admitted_imprint(tmp_path: Path, *, lanes=("work",)) -> tuple[Path, str]:
    """``(root, imprint id)`` of a handed-off imprint with no use allowed yet."""
    return handed_off(tmp_path, built_package(tmp_path, lanes=lanes), route=False, valid_until=FAR)


def with_allow(tmp_path: Path, *, lanes=("work",), fault: str | None = None) -> tuple[Path, str, str]:
    """``(root, imprint id, use id)``: an imprint and the allow file the station writes for one use (Task 37).
    ``fault`` is ``tombstone``, ``ended`` (the allow file's end has passed) or ``no_allow_file``."""
    import json
    import uuid

    root, imprint_id = admitted_imprint(tmp_path, lanes=lanes)
    use_id = str(uuid.uuid4())
    uses = root / f"{imprint_id}.state" / "uses"
    uses.mkdir(mode=0o700)
    if fault != "no_allow_file":
        doc = {"kind": "imprint-use-allow", "use_id": use_id, "instance_id": imprint_id, "use": "trail-evaluation",
               "actions": ["read"], "purpose": "trail-evaluation", "decided_at": 1_761_415_500,
               "valid_until": 1 if fault == "ended" else FAR}
        (uses / f"{use_id}.allow.json").write_text(json.dumps(doc))
    if fault == "tombstone":
        (root / "tombstones").mkdir()
        (root / "tombstones" / f"{imprint_id}.json").write_text("{}")
    return root, imprint_id, use_id


def uses_dir(root: Path, imprint_id: str, use_id: str) -> Path:
    return Path(root) / f"{imprint_id}.state" / "uses" / use_id


def uses_dirs(root: Path, imprint_id: str) -> list[Path]:
    uses = Path(root) / f"{imprint_id}.state" / "uses"
    return [p for p in uses.iterdir() if p.is_dir()] if uses.is_dir() else []


def result_of(root: Path, imprint_id: str, use_id: str) -> str:
    return (uses_dir(root, imprint_id, use_id) / "result.json").read_text()


def report_exists(root: Path, imprint_id: str, use_id: str) -> bool:
    return (uses_dir(root, imprint_id, use_id) / "report.json").exists()


def recording_replace(order: list):
    """An ``os.replace`` that records ``(src, dst)`` in ``order`` and then replaces."""
    import os

    real = os.replace

    def replace(src, dst, *args, **kwargs):
        order.append((src, dst))
        return real(src, dst, *args, **kwargs)

    return replace


# ---------------------------------------------------------------- Task 45: the owner's side of the receipts

IMPRINT_ID = "c0a8f5e2-7b1d-4a3c-9e5f-2d6b8a1c4e70"
STATION = "5" * 64


def ledger_home(tmp_path: Path, owner: str = "andy") -> Path:
    """An engram home holding a permissions ledger for ``owner`` and nothing else."""
    from permission_ledger import Ledger

    home = Path(tmp_path) / "engram"
    Ledger.create(home, owner, now=T("2026-11-01")).close()
    return home


def state_of(engram_home: Path):
    from permission_ledger import Ledger

    led = Ledger.open_read_only(engram_home)
    try:
        return led.state()
    finally:
        led.close()


def _record(id_: str, kinds: list, actions: list, purposes: list, owner: str) -> dict:
    return {"id": id_, "layer": f"place:home/{owner}", "effect": "allow",
            "selector": {"audience": [f"place:home/{owner}"], "requesters": ["agent:station-imprints"],
                         "objects": {"kinds": kinds}, "actions": actions, "purposes": purposes},
            "valid_from": 1, "valid_until": T("2027-01-30"), "created": 1}


def _write_lines(path: Path, items) -> None:
    path.write_text("[\n" + ",\n".join(json.dumps(i) for i in items) + ("\n" if items else "") + "]\n")


def _receipt_record(n: int, event: str, detail: dict, at: int) -> dict:
    return {"kind": "imprint-receipt", "station": STATION, "id": f"rc{n:02d}-{event}", "permission": "req1",
            "event": event, "actor_id": "o", "at": at, "detail": detail, "previous": "0" * 64}


def _detail(event: str, n, term, route: bool, count: int) -> dict:
    if event == "admitted":
        return {"checks": 17, "report_sha256": "a" * 64, "skipped": [], "roads_and_trails": n or 0, "sessions_too_large": 0}
    if event in ("denied", "failed"):
        return {"term": term} if term else ({} if event == "denied" else {"step": "calibration", "message": "x"})
    actions = ["read", "recall", "route"]
    use = {"use": "trail-evaluation", "actions": actions, "purpose": "trail-evaluation"}
    if event == "use-finished":
        return {**use, "use_id": "u1", "end": 5,
                "objects": {"imprint": IMPRINT_ID, "count": count, "roads_and_trails": n or 0}}
    if event == "refused":
        return {**use, "term": term or "end", **({"roads_and_trails": n} if n is not None else {})}
    return {}


def add_receipt(home: Path, event: str, *, n=None, term=None, verified: bool = True, route: bool = False, memories: int = 0):
    folder = Path(home) / "imprints" / IMPRINT_ID
    existing = sorted((folder / "receipts").glob("*.json"))
    seq = len(existing) + 1
    record = _receipt_record(seq, event, _detail(event, n, term, route, memories) if event != "deleted"
                             else {"reason": "ended", "files": 1, "limits": "x"}, 1_800_000_000 + seq * 100)
    (folder / "receipts" / f"{seq}-{IMPRINT_ID}.json").write_text(
        json.dumps({"seq": seq, "record": record, "signature": "sig"}))
    if verified:
        vf = folder / "verified.json"
        doc = json.loads(vf.read_text())
        doc["verified"].append(record["id"])
        vf.write_text(json.dumps(doc))
    return record


def imported_home(tmp_path: Path, *, memories: int = 3, route: bool = False, receipts=("admitted",), owner: str = "andy",
                  subjects=None) -> Path:
    """What ``make imprint-status`` and ``verify-imprint`` leave under ``~/.superyak/imprints/<id>/``."""
    home = Path(tmp_path) / "superyak"
    folder = home / "imprints" / IMPRINT_ID
    (folder / "receipts").mkdir(parents=True)
    refs = sorted(f"mem:S/episode/m{i:05d}" for i in range(memories))
    _write_lines(folder / "objects.json", refs)
    _write_lines(folder / "subjects.json", sorted([refs[i], s] for i, extra in (subjects or {}).items() for s in extra))
    records = [_record("r-mem", ["memory"], ["imprint", "read", "recall"],
                       ["calibration", "trail-evaluation"] if route else ["calibration"], owner)]
    if route:
        records.append(_record("r-road", ["road", "trail"], ["imprint", "read", "recall", "route"], ["trail-evaluation"], owner))
    permission = {"kind": "imprint-permission", "station": STATION, "id": "req1", "owner": f"person:{owner}",
                  "imprint_id": IMPRINT_ID, "attestation": "others-copied-at-home-v1", "records": records}
    for r in records:
        r["selector"]["actions"] = sorted(r["selector"]["actions"])
    (folder / "permission.json").write_text(json.dumps({"record": permission, "signature": "s", "station_key": "k"}))
    (folder / "verified.json").write_text(json.dumps({"station_key": "k", "verified": [], "chain": "intact", "pin": "pinned"}))
    for spec in receipts:
        event, n, term = (spec, None, None) if isinstance(spec, str) else (*spec, *([None] * (3 - len(spec))))
        add_receipt(home, event, n=n, term=term, route=route, memories=memories)
    return home


def add_verified(home: Path, event: str, **kw):
    return add_receipt(home, event, **kw)


def saved_receipts(home: Path) -> list:
    folder = Path(home) / "imprints" / IMPRINT_ID / "receipts"
    return [json.loads(p.read_text()) for p in sorted(folder.glob("*.json"))]


def shipped_refs(home: Path) -> list:
    return json.loads((Path(home) / "imprints" / IMPRINT_ID / "objects.json").read_text())


def first_ref(home: Path) -> str:
    return shipped_refs(home)[0]


def imported_rows(engram_home: Path) -> list:
    from permission_uses import Uses

    uses = Uses.open_read_only(engram_home)
    try:
        rows = []
        for r in uses.conn.execute("SELECT * FROM uses ORDER BY seq"):
            d = dict(r)
            d["subjects"] = [(s["subject"], s["object"]) for s in uses.conn.execute(
                "SELECT subject, object FROM use_subjects WHERE use_seq=? ORDER BY rowid", (r["seq"],))]
            rows.append(d)
        return rows
    finally:
        uses.close()


def subject_pairs(engram_home: Path, *, action: str) -> list:
    return [p for r in imported_rows(engram_home) if r["action"] == action and r["object"] is None
            for p in r["subjects"] if p[1].startswith("mem:")]


def subject_rows(engram_home: Path, *, action: str) -> int:
    return len(subject_pairs(engram_home, action=action))


def is_copy_subject(row: dict) -> bool:
    return any(obj.startswith("imprint:") for _, obj in row["subjects"])


def render(listed) -> str:
    lines = [c["line"] for c in listed.copies]
    lines += [f"{r['action']} {r['purpose']} {r['id']}" for r in listed.rows]
    return "\n".join(lines)


def render_list(engram_home: Path, home: Path) -> str:
    from imprint_copies import copies_held
    from permission_uses import Uses

    uses = Uses.open_read_only(engram_home)
    try:
        return render(uses.owner_list(state_of(engram_home), copies=copies_held(home)))
    finally:
        uses.close()


# ---- Task 50: peak memory on the Pi, for every process ---------------------------------------------------------------

IMPRINT_PY = str(ENGRAM_DIR / "imprint.py")
NOW_SECONDS = 1_761_415_451
CAP_ROOT = Path("/var/tmp") / f"imprint-cap-{os.getuid()}"      # built once and kept (R27); not under tmp_path
CAP_UNTIL = "2026-10-25T18:00:00Z"


def mib(n: int) -> float:
    return round(n / 2**20, 1)


_STUB_TRAILS = '''"""A stand-in for the trails plan's roads_and_trails (G13): one SQL pass over the log, one session at a time."""


def roads_and_trails(conn, *, lane, as_of, counts):
    n = 0
    for (_,) in conn.execute("SELECT DISTINCT json_extract(context, '$.session_id') FROM memory_log "
                             "WHERE json_extract(context, '$.session_id') IS NOT NULL"):
        n += 1
    return n
'''


ROUTE_OPEN_MODULE = "imprint_route_open"
_ROUTE_OPEN_WRAPPER = '''"""Test-only: imprint.py with route open in this one process (the fresh review's M2).

Route waits until trails ships (``imprint_filter.ROUTE_OPEN``); a pytest fixture can't reach a child, so the Pi
measurements of what route does run their route children as ``python -m imprint_route_open <imprint.py arguments>``.
Nothing that ships opens route: this file lives only in the measurements' stub directory."""
import sys

import imprint_filter

imprint_filter.ROUTE_OPEN = True

import imprint  # noqa: E402

sys.exit(imprint.main())
'''


def _write_stub(path: Path, text: str) -> None:
    """Whole or absent: several sessions may write the same stub at once."""
    if path.is_file() and path.read_text() == text:
        return
    tmp = path.with_name(f".{path.name}.{os.getpid()}.tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _stub_trails_dir(root: Path = CAP_ROOT) -> Path:
    """The stub directory on the measurements' ``PYTHONPATH``: the stand-in ``trails.py`` and the route-open wrapper."""
    path = root / "stubs"
    path.mkdir(parents=True, exist_ok=True)
    _write_stub(path / "trails.py", _STUB_TRAILS)
    _write_stub(path / f"{ROUTE_OPEN_MODULE}.py", _ROUTE_OPEN_WRAPPER)
    return path


def imprint_argv(*, route: bool) -> list[str]:
    """How a measurement starts imprint.py: as it ships, or with route open in that child alone (run from
    ``ENGRAM_DIR`` with the stub directory on ``PYTHONPATH``, as ``world.env`` and ``_run`` do)."""
    return [sys.executable, "-m", ROUTE_OPEN_MODULE] if route else [sys.executable, IMPRINT_PY]


@dataclass
class CapWorld:
    """A fixture store beside its ledger, and where one measured command runs."""
    kind: str                   # "cap" or "bounds"
    store: Path
    engram_home: Path
    work: Path                  # the test's tmp_path
    env: dict

    @property
    def home(self) -> Path:
        return self.work / "home"

    @property
    def root(self) -> Path:
        return self.work / "root"


def _unit_vectors(rng, n: int, dim: int = 768):
    import numpy as np

    X = rng.standard_normal((n, dim)).astype("<f4")
    X /= np.linalg.norm(X, axis=1, keepdims=True)
    return X


def _text(i: int, kind: str, size: int = 1024) -> str:
    return (f"{kind} {i} of the fixture store at its bounds, with no name in it. " * 20)[:size]


def _memory_ids(lane: str, n: int):
    return [f"{lane[0]}{i:07d}-0000-4000-8000-{i:012d}" for i in range(n)]


def _fill_store(path: Path, *, lanes: dict, semantics: int, hub_sources: int, log_rows: int, sessions: int,
                cold_keys: int, cores: bool, resonances: bool, seed: int) -> list[tuple[str, str]]:
    """A store at ``path`` holding ``lanes`` (lane -> episode count) of work-or-personal episodes with random unit
    vectors and 1 KiB of text, ``semantics`` semantics (the first a hub of ``hub_sources`` sources, the rest three
    sources each), ``log_rows`` recall rows over ``sessions`` sessions, and a ``cold.db`` of ``cold_keys`` keys.
    Returns every ``(layer, id)`` it wrote."""
    import numpy as np

    rng = np.random.default_rng(seed)
    path.parent.mkdir(parents=True, exist_ok=True)
    store = Storage(str(path))
    conn, written, by_lane = store.conn, [], {}
    stamp = "2026-01-01T00:00:00+00:00"
    k = 0
    for lane, n in lanes.items():
        ids = by_lane[lane] = _memory_ids(lane, n)
        for lo in range(0, n, 1000):
            chunk = ids[lo:lo + 1000]
            conn.executemany(
                "INSERT INTO episodes (id, session_id, content, created_at, lane, core) VALUES (?, ?, ?, ?, ?, ?)",
                [(e, f"sess-{(k + j) % sessions}", _text(k + j, "episode"), stamp, lane,
                  int(cores and lane == next(iter(lanes))))
                 for j, e in enumerate(chunk)])
            X = _unit_vectors(rng, len(chunk))
            conn.executemany("INSERT INTO episode_vectors (id, embedding) VALUES (?, ?)",
                             [(e, X[j].tobytes()) for j, e in enumerate(chunk)])
            conn.commit()
            k += len(chunk)
        written += [("episode", e) for e in ids]
    lane_names = list(lanes)
    conn.execute("PRAGMA foreign_keys=OFF")
    for lo in range(0, semantics, 1000):
        rows, sources, ids = [], [], []
        for j in range(lo, min(lo + 1000, semantics)):
            lane = lane_names[j % len(lane_names)]
            sid = f"s{j:07d}-0000-4000-8000-{j:012d}"
            pool = by_lane[lane]
            rows.append((sid, _text(j, "semantic"), "fact", 0.5, stamp, lane))
            n_src = hub_sources if j == 0 else 3
            sources += [(sid, pool[(j * 3 + m) % len(pool)]) for m in range(n_src)]
            ids.append(sid)
        conn.executemany("INSERT INTO semantics (id, content, kind, confidence, created_at, lane) VALUES (?, ?, ?, ?, ?, ?)", rows)
        conn.executemany("INSERT OR IGNORE INTO semantic_sources (semantic_id, episode_id) VALUES (?, ?)", sources)
        X = _unit_vectors(rng, len(ids))
        conn.executemany("INSERT INTO semantic_vectors (id, embedding) VALUES (?, ?)",
                         [(sid, X[j].tobytes()) for j, sid in enumerate(ids)])
        conn.commit()
        written += [("semantic", s) for s in ids]
    conn.execute("PRAGMA foreign_keys=ON")
    flat = [e for lane in lane_names for e in by_lane[lane]]
    for lo in range(0, log_rows, 5000):
        conn.executemany(
            "INSERT INTO memory_log (id, timestamp, event_type, layer, target_ids, context, outcome) "
            "VALUES (?, ?, 'recall', 'episode', ?, ?, NULL)",
            [(f"log-{j:08d}", f"2026-01-02T00:{j % 60:02d}:00+00:00", json.dumps([flat[j % len(flat)]]),
              json.dumps({"session_id": f"sess-{j % sessions}", "recall_id": f"rc{j}"}))
             for j in range(lo, min(lo + 5000, log_rows))])
        conn.commit()
    if resonances:
        for lane in lane_names:
            ids = by_lane[lane]
            conn.executemany(
                "INSERT INTO resonances (id, memory_a, layer_a, memory_b, layer_b, similarity, weight, strength,"
                " co_occurrences, created_at, last_seen) VALUES (?, ?, 'episode', ?, 'episode', 0.5, 1.0, 0.5, 2, ?, ?)",
                [(f"res-{a}", a, ids[(i + 1) % len(ids)], stamp, stamp) for i, a in enumerate(ids)])
        conn.commit()
    if cold_keys:
        cold = store._cold_storage()
        for lo in range(0, cold_keys, 5000):
            cold.executemany("INSERT INTO episodes (id, content, created_at, lane) VALUES (?, ?, ?, 'work')",
                             [(f"c{j:07d}-0000-4000-8000-{j:012d}", _text(j, "cold"), stamp)
                              for j in range(lo, min(lo + 5000, cold_keys))])
            cold.commit()
    store.close()
    return written


def _fixture_ledger(eh: Path, store_path: Path, memories, per_memory: int) -> None:
    """A ledger for the owner ``andy`` (the operator, so every memory ships) that registers the store and gives each
    memory ``per_memory`` co-subjects, every one a person of its own, written as rows in one pass."""
    store = Storage.open_read_only(store_path)
    try:
        led = ledger(eh, owner="andy", store=store)
        instance = iid(store)
    finally:
        store.close()
    try:
        seq = led.conn.execute("SELECT max(seq) FROM ledger_log").fetchone()[0]
    except sqlite3.Error:
        seq = 1
    n = 0
    batch = []
    led.conn.execute("BEGIN IMMEDIATE")                  # one transaction: a commit a row would sync 700,000 times
    for layer, id in memories:
        ref = f"mem:{instance}/{layer}/{id}"
        for _ in range(per_memory):
            batch.append((ref, f"person:p{n:07d}", seq or 1, "person:fixture", 0))
            n += 1
        if len(batch) >= 50_000:
            led.conn.executemany("INSERT INTO subjects (object, subject, added_seq, added_by, self_claimed) "
                                 "VALUES (?, ?, ?, ?, ?)", batch)
            batch = []
    if batch:
        led.conn.executemany("INSERT INTO subjects (object, subject, added_seq, added_by, self_claimed) "
                             "VALUES (?, ?, ?, ?, ?)", batch)
    led.conn.execute("COMMIT")
    led.close()


def _cap_world(tmp_path: Path, kind: str, build_fixture) -> CapWorld:
    """The fixture of ``kind`` under ``CAP_ROOT``, built on first use. Several sessions at once wait on its lock."""
    import fcntl

    base = CAP_ROOT / kind
    base.mkdir(parents=True, exist_ok=True)
    with open(CAP_ROOT / f"{kind}.lock", "a+") as lock:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if not (base / ".ready").is_file():
            shutil.rmtree(base, ignore_errors=True)
            base.mkdir(parents=True)
            build_fixture(base)
            (base / ".ready").write_text("ok")
    env = {**os.environ, "PYTHONPATH": str(_stub_trails_dir()), "PYTHONDONTWRITEBYTECODE": "1"}
    env.pop("ENGRAM_HOME", None)
    return CapWorld(kind, base / "src" / "graph.db", base / "eh", Path(tmp_path), env)


def _build_cap(base: Path) -> None:
    written = _fill_store(base / "src" / "graph.db", lanes={"personal": 45_000, "work": 45_000}, semantics=10_000,
                          hub_sources=1_025, log_rows=200_000, sessions=2_000, cold_keys=100_000, cores=False,
                          resonances=False, seed=1)
    _fixture_ledger(base / "eh", base / "src" / "graph.db", written, 7)


def _build_bounds(base: Path) -> None:
    written = _fill_store(base / "src" / "graph.db", lanes={"personal": 16_000, "work": 16_000}, semantics=8,
                          hub_sources=1_024, log_rows=2_000, sessions=100, cold_keys=0, cores=True, resonances=True,
                          seed=2)
    _fixture_ledger(base / "eh", base / "src" / "graph.db", written[:1], 0)


def build_cap_store(tmp_path: Path) -> CapWorld:
    """I 16's "Every process at its bounds": 100,000 memories (two lanes of 45,000 episodes, so both are over the
    16,000 a calibration set may hold; 10,000 semantics, one a hub of 1,025 sources), random 768-dimension unit
    vectors, 1 KiB of text each, 200,000 ``memory_log`` rows over 2,000 sessions, a ``cold.db`` of 100,000 keys, and
    a ledger giving every memory 7 co-subjects, 700,000 people in all. Built once under ``/var/tmp``."""
    return _cap_world(tmp_path, "cap", _build_cap)


def build_bounds_store(tmp_path: Path) -> CapWorld:
    """Every calibration set at its bound: two lanes of 16,000 episodes, the first lane's all cores (one core set of
    16,000: both lanes as cores would be a set of 32,000, over its bound and skipped), a semantic of 1,024
    sources, and a resonance on every episode. Built once under ``/var/tmp``."""
    return _cap_world(tmp_path, "bounds", _build_bounds)


def _plan_command(world: CapWorld, home: Path, *, route: bool) -> list[str]:
    return [*imprint_argv(route=route), "plan", "--store", str(world.store), "--lanes", "personal,work",
            "--layers", "episode,semantic", "--until", CAP_UNTIL, "--audience", "place:home/andy",
            "--actions", "imprint,route" if route else "imprint", "--superyak-home", str(home),
            "--engram-home", str(world.engram_home), "--json"]


def _context_home(world: CapWorld, home: Path) -> Path:
    write_context(home, plan_context("andy"))
    return home


def _run(cmd, env, cwd=None) -> str:
    out = subprocess.run([str(a) for a in cmd], env=env, cwd=cwd or ENGRAM_DIR, capture_output=True, text=True)
    assert out.returncode == 0, (cmd[:4], out.stderr[-2000:])
    return out.stdout


STAGE_VERSION = "v2"      # stages kept from before route waited for trails (2026-10-28) are made again (review M2)


def _staged(world: CapWorld, name: str, *, route: bool, built: bool) -> Path:
    """A home holding a plan (and its built package) made once, unmeasured, beside the fixture; copied to the test.
    On the cap fixture the built package is the planned stage built, so one plan serves both. A stage with ``route``
    plans and builds with route open in those children alone (``imprint_argv``)."""
    stage = CAP_ROOT / world.kind / f"stage-{STAGE_VERSION}-{name}"
    if not (stage / ".ready").is_file():
        if built and world.kind == "cap":
            _staged(world, "planned-route" if route else "planned", route=route, built=False)
            shutil.rmtree(stage, ignore_errors=True)
            shutil.copytree(world.home, stage, symlinks=True)
            shutil.rmtree(world.home)
            plan_id = (stage / "plan.id").read_text()
        else:
            shutil.rmtree(stage, ignore_errors=True)
            _context_home(world, stage)
            plan = json.loads(_run(_plan_command(world, stage, route=route), world.env))
            plan_id = plan["id"]
            (stage / "plan.id").write_text(plan_id)
        if built:
            _run([*imprint_argv(route=route), "build", "--plan", plan_id, "--superyak-home", stage,
                  "--engram-home", world.engram_home], world.env)
        (stage / ".ready").write_text("ok")
    shutil.copytree(stage, world.home, symlinks=True)
    return world.home


def _plan_id(world: CapWorld) -> str:
    return (world.home / "plan.id").read_text()


def _handed_off_from(world: CapWorld, *, route: bool) -> tuple[Path, str]:
    import imprint

    saved = json.loads(next((world.home / "imprints" / "plans").glob("*.json")).read_text())
    built = imprint._built_of(world.home, saved["imprint_id"])
    return handed_off(world.work, built, route=route, valid_until=FAR)


def cap_command(world: CapWorld, step: str) -> list[str]:
    """The argv of one process of I 16's "Every process at its bounds" run on the cap fixture. What it needs made
    first (a plan, a built package, a handed-off root) is made unmeasured and kept, then copied to ``world.work``.
    Plan, read and build are measured as they ship, without route (it waits until trails ships; the fresh review's
    M2). ``count`` needs a package with route, so its stage is made with route open in those children alone."""
    if step == "plan":
        return _plan_command(world, _context_home(world, world.home), route=False)
    if step == "read":
        _staged(world, "planned", route=False, built=False)
        return [sys.executable, IMPRINT_PY, "read", "--plan", _plan_id(world), "--start", "45000", "--limit", "1000",
                "--superyak-home", world.home, "--engram-home", world.engram_home]
    if step == "build":
        _staged(world, "planned", route=False, built=False)
        return [sys.executable, IMPRINT_PY, "build", "--plan", _plan_id(world), "--superyak-home", world.home,
                "--engram-home", world.engram_home]
    if step == "admit":                                         # a package without route: a count needs trails.py
        _staged(world, "built-noroute", route=False, built=True)
        root, imprint_id = _handed_off_from(world, route=False)
        return [sys.executable, IMPRINT_PY, "admit", "--id", imprint_id, "--imprints-dir", root, "--verify-cmd",
                shlex.join(stub_verify(ok=True))]
    if step == "count":
        _staged(world, "built-route", route=True, built=True)
        saved = json.loads(next((world.home / "imprints" / "plans").glob("*.json")).read_text())
        package = world.home / "imprints" / saved["imprint_id"] / "imprint.db"
        code = ("import sys, store_reader, imprint\n"
                "conn = store_reader.connect(sys.argv[1], immutable=True)\n"
                "print(imprint.count_roads_and_trails(conn, lanes=['personal', 'work'], as_of=1761415451))\n")
        return [sys.executable, "-c", code, package]
    if step == "import-receipts":
        led_home = ledger_home(world.work)
        memories = 100_000
        subjects = {i: [f"person:q{i * 7 + j:07d}" for j in range(7)] for i in range(memories)}
        home = imported_home(world.work, memories=memories, receipts=["admitted"], subjects=subjects, route=False)
        return [sys.executable, IMPRINT_PY, "import-receipts", "--id", IMPRINT_ID[:8], "--superyak-home", home,
                "--engram-home", led_home]
    raise ValueError(step)


def admit_command(world: CapWorld, *, derive: str) -> list[str]:
    """``imprint.py admit`` on the bounds fixture, with ``route`` and, for ``derive="stub"``, the stand-in trail
    count on ``PYTHONPATH`` (``world.env``), so the whole command runs as the unit would. Its package is planned and
    built with route open in those children alone; admission itself doesn't consult ``ROUTE_OPEN``."""
    assert derive == "stub"
    _staged(world, "built-bounds-route", route=True, built=True)
    root, imprint_id = _handed_off_from(world, route=True)
    return [sys.executable, IMPRINT_PY, "admit", "--id", imprint_id, "--imprints-dir", root, "--verify-cmd",
            shlex.join(stub_verify(ok=True))]


def admission_result(world: CapWorld) -> dict:
    """The ``result.json`` an admission left, less an empty ``skipped``, so ``"skipped" in`` it says a set was skipped."""
    (state,) = world.root.glob("*.state")
    result = json.loads((state / "result.json").read_text())
    if not result.get("skipped"):
        result.pop("skipped", None)
    return result


def analysis_errors(world: CapWorld) -> list[str]:
    """Each analysis of the admission's calibration report that raised (``calibrate._run`` records it and goes on, so
    an admission can end ``admitted`` with an analysis lost to a MemoryError): ``"<analysis>: <error>"``."""
    (state,) = world.root.glob("*.state")
    report = json.loads((state / "calibration" / "report.json").read_text())
    return [f"{name}: {body['error']}" for name, body in report["analyses"].items()
            if isinstance(body, dict) and "error" in body]


def use_command(tmp_path: Path, *, trails_cmd) -> list[str]:
    """``imprint.py use`` on a small admitted imprint, with a stand-in trails command: the parent's own peak."""
    root, imprint_id, use_id = with_allow(Path(tmp_path))
    return [sys.executable, IMPRINT_PY, "use", "--id", imprint_id, "--use-id", use_id, "--imprints-dir", root,
            "--trails-cmd", shlex.join(trails_cmd)]


_C_STRING = re.compile(r'"((?:[^"\\]|\\.)*)"|\[|\]')


def _c_unescape(text: str) -> str:
    return text.encode("latin-1", "backslashreplace").decode("unicode_escape", "replace")


def _execve_env(line: str) -> dict[str, str] | None:
    """The environment of a successful ``execve`` line of ``strace -v``, or None."""
    head = re.match(r'\d+\s+execve\(', line)
    if not head or not re.search(r"\)\s*=\s*0\s*$", line):
        return None
    lists, current, depth, first = [], None, 0, True
    for m in _C_STRING.finditer(line, head.end()):
        token = m.group(0)
        if token == "[":
            current, depth = [], depth + 1
        elif token == "]":
            lists.append(current)
            current, depth = None, depth - 1
        elif current is not None:
            current.append(_c_unescape(m.group(1)))
    if len(lists) < 2:
        return None
    return dict(item.split("=", 1) for item in lists[1] if "=" in item)


def strace_temp_files(cmd, env) -> tuple[list[str], list[dict[str, str]]]:
    """Run ``cmd`` as a child under ``strace -f -v -s 65536 -e trace=execve,open,openat`` with ``env`` from its first
    instruction; return every SQLite temporary file (``etilqs_…``) it opened and the environment of every ``execve``
    (the re-exec's included, R26)."""
    import tempfile

    with tempfile.NamedTemporaryFile("r", suffix=".strace") as log:
        done = subprocess.run(["strace", "-f", "-v", "-s", "65536", "-e", "trace=execve,open,openat", "-o", log.name,
                               *[str(a) for a in cmd]], env=env, cwd=ENGRAM_DIR, capture_output=True, text=True)
        assert done.returncode == 0, (done.returncode, done.stderr[-2000:])
        lines = Path(log.name).read_text(errors="replace").splitlines()
    opened = []
    for line in lines:
        m = re.search(r'open(?:at)?\([^"]*"([^"]*etilqs_[^"]*)"[^)]*\)\s*=\s*(-?\d+)', line)
        if m and int(m.group(2)) >= 0:
            opened.append(m.group(1))
    return opened, [e for e in map(_execve_env, lines) if e is not None]


def built_of(tmp_path: Path, plan_id: str):
    """The ``Built`` of a plan that a child process built under ``HOME(tmp_path)``."""
    import imprint

    saved = json.loads(imprint.resolve_plan(HOME(tmp_path), plan_id).read_text())
    return imprint._built_of(HOME(tmp_path), saved["imprint_id"])
