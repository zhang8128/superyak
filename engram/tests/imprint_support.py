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
              every_table: bool = False, cross_ref: bool = False, exclude=()):
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
    sel = parse_selection(lanes="work", layers="episode,semantic", since=None, until=until, shared_with=None,
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


def handed_off(tmp_path: Path, built, *, route: bool, valid_until: int) -> tuple[Path, str]:
    """``(root, imprint id)``: a root laid out as the station's hand-off leaves it (I 10): ``<id>/`` holding
    ``imprint.db``, ``manifest.json``, ``permission.json`` and ``approved.json``, and ``<id>.state/`` holding
    ``admission.json``. The permission's signature is a stub; ``stub_verify`` stands in for the peer."""
    import json

    root = tmp_path / "root"
    imprint_id = built.imprint_id
    folder, state = root / imprint_id, root / f"{imprint_id}.state"
    folder.mkdir(parents=True, mode=0o700)
    state.mkdir(mode=0o700)
    for name in ("imprint.db", "manifest.json"):
        shutil.copyfile(built.dir / name, folder / name)
    manifest = built.manifest
    record = {"kind": "imprint-permission", "station": "ab" * 32, "id": str(uuid.uuid4()), "owner": "andy",
              "owner_id": "u1", "ship_id": "s1", "imprint_id": imprint_id,
              "source_instance_id": manifest["source"]["instance_id"],
              "request_sha256": manifest["request_sha256"], "plan_digest": manifest["plan_digest"],
              "attestation": {"route": route}, "created": 1_761_415_451, "records": []}
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


def tampered(tmp_path: Path, change: str) -> tuple[Path, str]:
    """``(root, imprint id)`` of a handed-off package with one defect. For a defect inside ``imprint.db``,
    ``manifest.package`` is then set to the file's facts, so every check before the target passes."""
    import json

    root, imprint_id = handed_off(tmp_path, built_package(tmp_path), route=False, valid_until=FAR)
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
    elif change in _DB_CHANGES:
        _edit_db(db, *_DB_CHANGES[change])
        _refix_package(folder)
    else:
        raise ValueError(change)
    return root, imprint_id
