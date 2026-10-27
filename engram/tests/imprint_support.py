"""Fixtures for the store-copy (imprint) tests.

Nothing here opens a stamped file with ``Storage(path)``: writers use
``sqlite3`` with ``sqlite_vec`` and readers use ``store_reader.connect`` or
``Storage.open_read_only`` (an imprint refuses a writable open).
"""
import ast
import re
import shutil
import sqlite3
import uuid
from pathlib import Path

import store_identity
import store_reader
from storage import Storage
from tests.permissions_support import T  # noqa: F401  (re-exported)
from tests.test_store_identity import build_schema27_store

GENOME_PARENT = "3f2b8c1e-5a4d-4e6f-9b7a-1c2d3e4f5a6b"


def _path(tmp_path: Path, name: str) -> Path:
    return tmp_path / f"{name}.db"


def new_store(tmp_path: Path, name: str) -> Storage:
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

    def fetchall(self):
        if not _KEYED.search(self._sql) and any(re.search(rf"\b{t}\b", self._sql) for t in self._tables):
            raise AssertionError(f"fetchall on a table that grows with the store: {self._sql}")
        return self._cur.fetchall()

    def __iter__(self):
        return iter(self._cur)

    def __getattr__(self, name):
        return getattr(self._cur, name)


class _Connection:
    def __init__(self, conn, tables):
        self._conn, self._tables = conn, tables

    def execute(self, sql, *args):
        return _Cursor(self._conn.execute(sql, *args), sql, self._tables)

    def __getattr__(self, name):
        return getattr(self._conn, name)


def refusing_fetchall(tables):
    """A replacement for ``calibrate._connect_read_only``: a read-only Storage whose connection raises on
    ``fetchall`` of a statement naming one of ``tables`` unless it is keyed to one memory."""
    def connect(path):
        store = Storage.open_read_only(path)
        store.conn = _Connection(store.conn, tables)
        return store
    return connect


_PREAMBLE = ("import sys; sys.path.insert(0, {engram!r}); SRC = {src!r}\n"
             "import calibrate, persistence, sheaf\nfrom storage import Storage\n")
_RUN_ONE = "from tests.imprint_support import run_one\n"   # only when used: the support module is heavy
_LAUNCHER = ("import resource, subprocess, sys, time\n"
             "t = time.monotonic(); r = subprocess.run(sys.argv[1:])\n"
             "print(resource.getrusage(resource.RUSAGE_CHILDREN).ru_maxrss * 1024, time.monotonic() - t, r.returncode)\n")


def child_peak_rss(code: str, *, src, timed: bool = False):
    """Peak resident bytes of ``code`` run in a child (``timed``: and its wall seconds). The child runs under
    ``systemd-run --user --scope -p MemoryMax=512M -p MemorySwapMax=0`` where that exists (R27). A launcher
    process reads ``RUSAGE_CHILDREN``, so the figure is this child's alone."""
    import subprocess
    import sys

    preamble = _PREAMBLE.format(engram=str(ENGRAM_DIR), src=str(src)) + (_RUN_ONE if "run_one" in code else "")
    cmd = [sys.executable, "-c", preamble + code]
    if shutil.which("systemd-run"):
        cmd = ["systemd-run", "--user", "--scope", "--quiet", "-p", "MemoryMax=512M", "-p", "MemorySwapMax=0"] + cmd
    out = subprocess.run([sys.executable, "-c", _LAUNCHER, *cmd], cwd=ENGRAM_DIR, capture_output=True, text=True)
    peak, seconds, status = out.stdout.split()[-3:]
    assert int(status) == 0, out.stderr[-2000:]
    return (int(peak), float(seconds)) if timed else int(peak)


def base_peak(step=None) -> int:
    """The peak a child reaches after its imports alone. ``step`` is reserved for Task 50's per-command
    imports and changes nothing here."""
    return child_peak_rss("pass", src="")


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
    """Terms for the home place of andy, without route."""
    from imprint_filter import Terms

    values = dict(audience="place:home/andy", actions=frozenset({"imprint"}),
                  purposes=frozenset({"calibration"}), days=90)
    values.update(over)
    return Terms(**values)


def ctx(store: Storage, *, published: Path | None = None, owner: str = "andy", home: bool = True,
        instance_name: str = "default", ledger=None):
    """A SourceContext for ``store``, with a scratch file beside it (a new one each call)."""
    import store_identity
    from imprint_filter import Scratch, SourceContext

    path = Path(store.db_path)
    return SourceContext(
        source_path=path, source_id=store_identity.effective_id(store.conn), instance_name=instance_name,
        owner=owner, published=published, ledger=ledger, home=home,
        scratch=Scratch(path.parent / f"{path.stem}-scratch-{uuid.uuid4().hex[:8]}.db"))


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
