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
              ledger=_AUTO, denies=None, until="2026-10-25T18:00:00Z"):
    """``(store path, selection, terms, ctx, context, home, now)``: the arguments of ``make_plan``. Episodes
    ``e0`` (never given a co-subject) and ``e1`` to ``e<episodes>`` in the work lane hold text naming Jenn; ``s1`` is sourced on ``e1``. A ledger is made
    when ``cosubjects`` or ``denies`` are given (``ledger=None`` forbids one)."""
    from imprint_filter import parse_selection, parse_terms

    s = new_store(tmp_path, "src")
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
    led = None
    if ledger is _AUTO and (cosubjects is not None or denies):
        ledger = True
    if ledger is True:
        led = globals()["ledger"](tmp_path / "eh", owner=owner, store=s, cosubjects=cosubjects, denies=denies)
    context = plan_context(owner)
    sel = parse_selection(lanes="work", layers="episode,semantic", since=None, until=until, shared_with=None,
                          exclude_file=None, unsourced=False, now=PLAN_NOW)
    t = parse_terms(audience="place:home/andy", actions="imprint,route" if route else "imprint",
                    purposes="calibration,trail-evaluation" if route else "calibration", days=90,
                    operator=context.operator)
    c = ctx(s, ledger=led, owner=owner, home=owner == context.operator, terms=t, now=PLAN_NOW)
    return Path(s.db_path), sel, t, c, context, tmp_path / "home", PLAN_NOW
