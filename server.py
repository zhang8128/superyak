"""Engram MCP Server v3 — layered memory with compression and reflection."""
from __future__ import annotations

import json
import logging
import os
import sqlite3
import uuid
from datetime import datetime, timezone
from pathlib import Path

from mcp.server.fastmcp import FastMCP

from config import load_config
from indexer import incremental_index
from logging_config import setup_logging
from storage import vec0_distance_to_similarity, _pack_embedding

logger = logging.getLogger("engram.server")

mcp = FastMCP("engram")


def _generate_perceptual_framing(content: str, kind: str) -> tuple[str, str]:
    """Generate notice/implication from instinct action text.

    Mirrors Compressor._generate_perceptual_framing for backfill use.
    """
    if not content:
        return (f"when: {kind}", content)

    lower = content.lower()

    if lower.startswith("always "):
        rest = content[len("always "):].strip()
        return (f"when making choices about: {rest}", content)
    elif lower.startswith("never "):
        rest = content[len("never "):].strip()
        return (f"when considering: {rest}", content)
    elif lower.startswith("prefer "):
        rest = content[len("prefer "):].strip()
        return (f"when deciding on: {rest}", content)
    elif lower.startswith("avoid "):
        rest = content[len("avoid "):].strip()
        return (f"when considering: {rest}", content)
    elif " when " in lower:
        idx = lower.index(" when ")
        implication = content[:idx].strip()
        notice = f"when {content[idx + 6:].strip()}"
        return (notice, implication)
    elif kind == "preference":
        return (f"when making choices about: {content[:80]}", content)
    else:
        return (f"when: {content[:80]}", content)


def _backfill_instinct_perceptual(storage, embeddings):
    """Backfill notice/implication for existing instincts that lack them."""
    instincts = storage.get_all_instincts()
    backfilled = 0
    for inst in instincts:
        if inst.get("notice") is not None:
            continue

        action = inst.get("action", "")
        trigger = inst.get("trigger", "preference")
        notice, implication = _generate_perceptual_framing(action, trigger)

        storage.conn.execute(
            "UPDATE instincts SET notice = ?, implication = ? WHERE id = ?",
            (notice, implication, inst["id"]),
        )

        # Store context vector
        ctx_emb = embeddings.embed([notice], prefix="search_document")[0]
        if ctx_emb is not None:
            # Check if context vector already exists
            has_ctx = storage.conn.execute(
                "SELECT 1 FROM instinct_context_vectors WHERE id = ?", (inst["id"],)
            ).fetchone()
            if not has_ctx:
                storage.add_instinct_context_vector(inst["id"], ctx_emb)

        backfilled += 1

    if backfilled:
        storage.conn.commit()
        logger.info("Backfilled notice/implication for %d instincts", backfilled)

    return backfilled

# Engram home is fixed — same memories regardless of which project you're in
ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent))
DB_PATH = ENGRAM_HOME / ".engram" / "graph.db"
# PROJECT_ROOT is the working directory (for code indexing), ENGRAM_HOME is where memories live
PROJECT_ROOT = Path(os.environ.get("ENGRAM_PROJECT_ROOT", os.getcwd()))

_storage = None
_embeddings = None
_config = None
_compressor = None
_reflector = None
_watcher = None
_session_id = None
_session_episode_count = 0
_instance_name = None
_initialized = False
_genome_db_path = None
_signals_db_path = None
_recall_scores: dict[str, dict[str, float]] = {}  # recall_id -> {result_id: score}
_recall_resonances: dict[str, list[dict]] = {}  # recall_id -> [{resonance_id, memory_id}]
_instinct_graph = None
_last_instinct_id = None
_knowledge_graph = None
_wander_visits: dict[str, int] = {}  # memory_id -> visit count this session
_clipboard = None
_category_store = None


from resonance import form_resonances as _form_resonances, surface_resonances as _surface_resonances
from transitions import TransitionGraph


def _get_instinct_graph():
    global _instinct_graph
    if _instinct_graph is None:
        db_path = Path(os.environ.get("ENGRAM_HOME", Path(__file__).resolve().parent)) / ".engram" / "instinct_transitions.db"
        _instinct_graph = TransitionGraph(db_path=db_path)
    return _instinct_graph


def _detect_layer(storage, memory_id: str) -> str | None:
    """Determine which layer a memory belongs to.

    Tries episode, semantic, instinct in order. Returns the layer name or None.
    """
    if storage.get_episode(memory_id) is not None:
        return "episode"
    if storage.get_semantic(memory_id) is not None:
        return "semantic"
    if storage.get_instinct(memory_id) is not None:
        return "instinct"
    return None


def _auto_walk(storage, start_id: str, max_steps: int, density_threshold: int,
               knowledge_graph, visit_counts: dict[str, int]) -> list[dict]:
    """Walk the memory graph from start_id using weighted random selection.

    At each step:
    1. Get all neighbors of current node (including entity neighbors if kg enabled)
    2. If current node has >= density_threshold total neighbors AND we've taken >= 1 step, stop
    3. Filter out already-visited nodes
    4. If no candidates, stop (dead end)
    5. Pick next node via weighted random (weight = connection_strength / (1 + visit_count))

    Returns a list of trail steps (neighbor dicts, not including start_id).
    """
    import random

    visited: set[str] = {start_id}
    trail: list[dict] = []
    current_id = start_id

    for step_num in range(max_steps):
        # Fetch entity neighbors if knowledge graph is available
        entity_neighbors = None
        if knowledge_graph is not None:
            try:
                layer = _detect_layer(storage, current_id)
                if layer is not None:
                    content = storage.get_memory_content(current_id, layer)
                    if content:
                        entity_neighbors = knowledge_graph.get_entity_neighbors(
                            content, exclude_id=current_id, num_results=10
                        )
            except Exception:
                pass

        neighbors = storage.get_neighbors(current_id, entity_neighbors=entity_neighbors)

        # Check density — stop if we've moved at least once and hit a dense cluster
        if step_num >= 1 and len(neighbors) >= density_threshold:
            break

        # Filter already-visited nodes
        candidates = [n for n in neighbors if n["id"] not in visited]

        if not candidates:
            break

        # Weighted random selection: base weight = connection_strength,
        # penalized by how many times this node has been visited this session
        weights = []
        for n in candidates:
            base = n.get("connection_strength", 0.5)
            visits = visit_counts.get(n["id"], 0)
            w = base * (1.0 / (1 + visits))
            weights.append(max(w, 1e-9))

        chosen = random.choices(candidates, weights=weights, k=1)[0]
        visited.add(chosen["id"])
        trail.append(chosen)
        current_id = chosen["id"]

    return trail


def _apply_resonance_feedback(storage, recall_id: str, used: bool) -> None:
    """Strengthen or weaken resonances based on whether recall was useful."""
    entries = _recall_resonances.pop(recall_id, None)
    if not entries:
        return
    for entry in entries:
        rid = entry["resonance_id"]
        if used:
            storage.strengthen_resonance(rid, delta=0.1)
        else:
            storage.weaken_resonance(rid, delta=0.05)


def _init():
    global _storage, _embeddings, _config, _compressor, _reflector, _watcher, _session_id, _instance_name, _genome_db_path, _signals_db_path, _knowledge_graph, _initialized, _category_store
    if _initialized:
        return
    from embeddings import NomicEmbedProvider
    from storage import Storage

    setup_logging(os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))
    _config = load_config(PROJECT_ROOT)

    # Federation: use instance DB when configured, otherwise default
    db_path = DB_PATH
    if _config and _config.instance:
        instance_db = ENGRAM_HOME / ".engram" / "instances" / _config.instance / "graph.db"
        if instance_db.exists():
            db_path = instance_db
            logger.info("Using instance DB: %s", _config.instance)

    db_path.parent.mkdir(parents=True, exist_ok=True)
    _storage = Storage(str(db_path))
    _embeddings = NomicEmbedProvider()

    _session_id = os.environ.get("CLAUDE_SESSION_ID") or str(uuid.uuid4())

    # Silent provenance: server-side best-effort stamp. The hook-side stamp
    # (same session_id under Claude Code) is authoritative and fills model.
    _storage.stamp_session_registry(
        _session_id,
        harness=os.environ.get("ENGRAM_HARNESS", "claude-code"),
        model=None,
        repo=os.getcwd(),
    )

    from categories import CategoryStore
    cat_conn = sqlite3.connect(str(db_path.parent / "categories.db"))
    try:
        import sqlite_vec
        cat_conn.enable_load_extension(True)
        cat_conn.load_extension(sqlite_vec.loadable_path())
    except Exception as e:
        logger.warning("sqlite-vec not available for categories: %s", e)
    _category_store = CategoryStore(cat_conn, dimension=768)

    from compress import Compressor
    from dedup import Deduplicator, DedupConfig

    dedup_model = os.environ.get("ENGRAM_DEDUP_MODEL", "gemma4:31b")
    _dedup = Deduplicator(DedupConfig(model=dedup_model))

    from framing import FramingConfig, FramingDistiller
    framing_model = os.environ.get("ENGRAM_FRAMING_MODEL", dedup_model)
    _framing_cfg = FramingConfig(model=framing_model)
    _framer = FramingDistiller(_framing_cfg)

    # Knowledge graph (Graphiti + Kuzu) — optional, don't block init on failure
    graph_model = os.environ.get("ENGRAM_GRAPH_MODEL")
    _knowledge_graph = None
    if _config and _config.graph.enabled:
        try:
            from knowledge import KnowledgeGraph
            graph_config = _config.graph
            if graph_model:
                graph_config.model = graph_model
            if not graph_config.db_path:
                graph_config.db_path = str(db_path.parent / "knowledge.kuzu")
            _knowledge_graph = KnowledgeGraph(graph_config)
        except Exception as e:
            logger.warning("Knowledge graph init failed (non-fatal): %s", e)

    _compressor = Compressor(
        _storage, _embeddings,
        _config.compression if _config else None,
        deduplicator=_dedup,
        knowledge_graph=_knowledge_graph,
        framer=_framer,
        cohesion_config=_config.cohesion if _config else None,
        persistence_config=_config.persistence if _config else None,
    )

    from reflection import Reflector
    _genome_db_path = ENGRAM_HOME / ".engram" / "genome" / "graph.db"
    _signals_db_path = ENGRAM_HOME / ".engram" / "signals.db"
    _reflector = Reflector(
        _storage,
        _config.reflection.staleness_days if _config else 30,
        genome_db_path=str(_genome_db_path) if _genome_db_path and _genome_db_path.exists() else None,
        signals_db_path=str(_signals_db_path) if _signals_db_path and _signals_db_path.exists() else None,
        cohesion_config=_config.cohesion if _config else None,
        persistence_config=_config.persistence if _config else None,
    )

    # Watcher is created but NOT started — lazy-started on first code search
    from watcher import FileWatcher
    _watcher = FileWatcher(PROJECT_ROOT, _config.watcher, _storage, _embeddings)
    import atexit
    atexit.register(lambda: _watcher.stop() if _watcher else None)
    atexit.register(lambda: _storage.close() if _storage else None)
    atexit.register(lambda: _knowledge_graph.close() if _knowledge_graph else None)
    atexit.register(lambda: _category_store._conn.close() if _category_store else None)

    # Federation: genome sync + inbox processing
    if _config and _config.instance:
        _instance_name = _config.instance
        _genome_db_path = ENGRAM_HOME / ".engram" / "genome" / "graph.db"
        _signals_db_path = ENGRAM_HOME / ".engram" / "signals.db"
        try:
            from federation import sync_genome, process_inbox, SignalBus

            if _genome_db_path.exists():
                synced = sync_genome(str(_genome_db_path), _storage)
                if synced:
                    logger.info("Synced %d genome items", synced)

            if _signals_db_path.exists():
                bus = SignalBus(_signals_db_path)
                processed = process_inbox(bus, _instance_name, _storage)
                if processed:
                    logger.info("Processed %d inbox messages", processed)
                bus.close()
        except Exception:
            logger.warning("Federation sync failed — continuing without", exc_info=True)

    # Sleep-time maintenance on init: decay → prune → compress
    # This is engram's "consolidation during sleep" — runs between sessions.
    # Each step records into the maintenance report (the pain channel):
    # failures are swallowed so later steps still run, but they surface in
    # status() and the wake orientation instead of dying in stderr.
    from maintenance import MaintenanceReport
    _maint = MaintenanceReport()
    try:
        # 1. Recompute decay: power-law activation based on access history
        with _maint.step("decay"):
            multipliers = None
            if _config.persistence.enabled:
                # one-sleep-stale cache is fine for ±15% pressure
                cached = _storage.get_persistence_scores()
                multipliers = {eid: 1.0 + 0.15 * (2.0 * s["redundancy"] - 1.0)
                               for eid, s in cached.items()}
            decayed = _storage.apply_decay(decay_exponent=0.5,
                                           exponent_multipliers=multipliers)
            if decayed:
                logger.info("Decay recomputed for %d episodes", decayed)

        # 2. Prune: delete compressed episodes that have decayed past threshold
        with _maint.step("prune"):
            if _config.persistence.enabled:
                from persistence import guarded_prune
                pruned = guarded_prune(_storage, _config.persistence)
            else:
                pruned = _storage.prune_decayed(threshold=0.05)
            if pruned:
                logger.info("Pruned %d decayed episodes", pruned)
                _maint.note("prune", pruned=pruned)

        # 2b. Prune weak instincts (overridden enough to drop below threshold)
        with _maint.step("instinct-prune"):
            pruned_instincts = _storage.prune_weak_instincts(strength_threshold=0.1)
            if pruned_instincts:
                logger.info("Pruned %d weak instincts", pruned_instincts)

        # 3. Auto-compress uncompressed episodes (crash recovery + consolidation)
        with _maint.step("auto-compress"):
            uncompressed = _storage.get_uncompressed_episodes()
            if uncompressed:
                logger.info("Auto-compressing %d uncompressed episodes on init", len(uncompressed))
                _maint.note("auto-compress", pending=len(uncompressed))
                _compressor.auto_compress()

        # 4. Backfill: embed any episodes that lost vectors (WAL corruption recovery)
        with _maint.step("episode-vector-backfill"):
            orphaned = _storage.get_orphaned_episodes()
            if orphaned:
                for ep in orphaned:
                    emb = _embeddings.embed([ep["content"]], prefix="search_document")[0]
                    _storage.conn.execute(
                        "INSERT INTO episode_vectors (id, embedding) VALUES (?, ?)",
                        (ep["id"], _pack_embedding(emb)),
                    )
                _storage.conn.commit()
                logger.info("Backfilled vectors for %d orphaned episodes", len(orphaned))

        # 5. Backfill: embed any semantics that lost vectors (WAL corruption recovery)
        with _maint.step("semantic-vector-backfill"):
            orphaned_sems = _storage.get_orphaned_semantics()
            if orphaned_sems:
                for sem in orphaned_sems:
                    emb = _embeddings.embed([sem["content"]], prefix="search_document")[0]
                    _storage.conn.execute(
                        "INSERT INTO semantic_vectors (id, embedding) VALUES (?, ?)",
                        (sem["id"], _pack_embedding(emb)),
                    )
                _storage.conn.commit()
                logger.info("Backfilled vectors for %d orphaned semantics", len(orphaned_sems))

        # 6. Backfill: embed any instincts that lack vectors (pre-existing instincts)
        with _maint.step("instinct-vector-backfill"):
            instincts = _storage.get_all_instincts()
            backfilled = 0
            for inst in instincts:
                has_vec = _storage.conn.execute(
                    "SELECT 1 FROM instinct_vectors WHERE id = ?", (inst["id"],)
                ).fetchone()
                if not has_vec:
                    emb = _embeddings.embed([inst["action"]], prefix="search_document")[0]
                    _storage.conn.execute(
                        "INSERT INTO instinct_vectors (id, embedding) VALUES (?, ?)",
                        (inst["id"], _pack_embedding(emb)),
                    )
                    backfilled += 1
            if backfilled:
                _storage.conn.commit()
                logger.info("Backfilled vectors for %d instincts", backfilled)

        # 6b. Backfill notice/implication for pre-existing instincts
        with _maint.step("instinct-perceptual-backfill"):
            _backfill_instinct_perceptual(_storage, _embeddings)

        # 7. Promote proximity suggestions to resonances (graph consolidation)
        with _maint.step("graph-promotion"):
            from graph import MemoryGraph
            _memory_graph = MemoryGraph(_storage)
            promoted = _memory_graph.promote_suggestions(min_prior_sessions=2)
            if promoted:
                logger.info("Sleep: promoted %d proximity suggestions", promoted)

        # 8. Coherence check — anchors + drift detection
        with _maint.step("coherence-check"):
            from coherence import CoherenceChecker
            _coherence_checker = CoherenceChecker(_storage)
            coherence_report = _coherence_checker.run_full_check(session_id=_session_id)
            if coherence_report["summary"] != "coherence stable":
                logger.info("Coherence: %s", coherence_report["summary"])

        # 9. Sheaf cohesion sleep pass (spec: 2026-06-13-sheaf-cohesion-design.md)
        # NOTE: narration episodes written by the sleep pass lack embeddings on first run;
        # they are backfilled by the orphan-vector pass on the NEXT startup.
        with _maint.step("cohesion-sleep-pass"):
            from sheaf import run_sleep_pass
            _cohesion_report = run_sleep_pass(
                _storage,
                embed_fn=lambda text: _embeddings.embed([text], prefix="search_document")[0],
                framing_cfg=_framing_cfg,
                cfg=_config.cohesion if _config else None,
                persistence_cfg=_config.persistence if _config else None,
            )
            if _cohesion_report.get("subdivided"):
                logger.info("cohesion pass subdivided: %s",
                            [s["parent_id"] for s in _cohesion_report["subdivided"]])
            if _cohesion_report.get("queued"):
                logger.info("cohesion pass queued (LLM unavailable): %s",
                            [q["parent_id"] for q in _cohesion_report["queued"]])
            _maint.note("cohesion-sleep-pass",
                        subdivided=len(_cohesion_report.get("subdivided", []) or []),
                        queued=len(_cohesion_report.get("queued", []) or []))

        # Persistence score refresh (spec: 2026-06-13-persistence-design.md)
        # Always-on observation: feeds reflect previews and next-boot decay
        # modulation; the cache is advisory, decisions recompute live.
        with _maint.step("persistence-score-refresh"):
            from persistence import compute_scores
            compute_scores(_storage, _config.persistence)
    except Exception:
        # Backstop for failures outside any step (should not happen — every
        # step swallows its own); recorded so the pain channel still sees it.
        logger.warning("Sleep-time maintenance failed — will retry next session", exc_info=True)
        _maint.steps.append({"name": "maintenance-outer", "ok": False,
                             "error": "unexpected failure outside step scope"})

    _maint.save(_storage.conn)

    # Log session start
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="session_start",
        layer="system",
        target_ids=[],
        context={"session_id": _session_id},
    )

    # Clipboard — internal working memory (pins, reminders, compose)
    global _clipboard
    from clipboard import Clipboard
    clipboard_db = db_path.parent / "clipboard.db"
    try:
        _clipboard = Clipboard(
            db_path=clipboard_db,
            max_chars=3000,
            engram_storage=_storage,
            embeddings=_embeddings,
        )
        atexit.register(lambda: _clipboard.close() if _clipboard else None)
    except Exception:
        logger.warning("Clipboard init failed (non-fatal)", exc_info=True)
        _clipboard = None

    _initialized = True


def _apply_recall_bias(query_embedding: list[float],
                       dream_alpha: float = 0.15,
                       instinct_alpha: float = 0.15) -> list[float]:
    """Blend dream residues and session biases into a query embedding.

    Two sources of invisible influence on recall:
    1. Dream residues — 64-dim truncated vectors from prior sessions (the past)
    2. Session biases — full-dim vectors from instinct firings this session (the present)

    Both tilt recall without the instance knowing. Dreams are deep and old.
    Instinct biases are immediate and contextual, weighted by their strength
    (which decays per message and reinforces on re-fire).
    """
    import struct
    import numpy as np

    query_arr = np.array(query_embedding, dtype=np.float32)
    full_dim = len(query_embedding)
    total_alpha = 0.0

    try:
        # --- Dream residue bias (from prior sessions) ---
        dream_bias = np.zeros(full_dim, dtype=np.float32)
        has_dream = False

        exists = _storage.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()
        if exists:
            from dreaming import RESIDUE_DIM

            residue_ids = _storage.conn.execute(
                "SELECT id FROM residue WHERE reacted = 0 ORDER BY created_at ASC LIMIT 3"
            ).fetchall()
            if not residue_ids:
                residue_ids = _storage.conn.execute(
                    "SELECT id FROM residue ORDER BY RANDOM() LIMIT 2"
                ).fetchall()

            residue_vecs = []
            for row in residue_ids:
                vec_row = _storage.conn.execute(
                    "SELECT embedding FROM residue_vectors WHERE id = ?",
                    (row["id"],),
                ).fetchone()
                if vec_row:
                    floats = struct.unpack(f"<{RESIDUE_DIM}f", vec_row["embedding"])
                    residue_vecs.append(np.array(floats, dtype=np.float32))

            if residue_vecs:
                avg_residue = np.mean(residue_vecs, axis=0)
                dream_bias[:RESIDUE_DIM] = avg_residue
                has_dream = True

        # --- Session bias (from instinct firings this session) ---
        session_bias = np.zeros(full_dim, dtype=np.float32)
        has_session = False

        exists = _storage.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='session_bias'"
        ).fetchone()
        if exists:
            biases = _storage.conn.execute(
                "SELECT embedding, strength FROM session_bias WHERE strength > 0.0"
            ).fetchall()

            if biases:
                # Weighted average by strength
                weighted_sum = np.zeros(full_dim, dtype=np.float32)
                total_weight = 0.0
                for bias_row in biases:
                    n = len(bias_row["embedding"]) // 4
                    floats = struct.unpack(f"<{n}f", bias_row["embedding"])
                    weighted_sum += np.array(floats, dtype=np.float32) * bias_row["strength"]
                    total_weight += bias_row["strength"]
                if total_weight > 0:
                    session_bias = weighted_sum / total_weight
                    has_session = True
                    # Scale alpha by average strength (fading biases have less pull)
                    instinct_alpha *= (total_weight / len(biases))

        # --- Blend ---
        if not has_dream and not has_session:
            return query_embedding

        # Compute effective blend
        blended = query_arr.copy()
        if has_dream:
            blended = (1 - dream_alpha) * blended + dream_alpha * dream_bias
            total_alpha += dream_alpha
        if has_session:
            blended = (1 - instinct_alpha) * blended + instinct_alpha * session_bias
            total_alpha += instinct_alpha

        # Renormalize
        norm = np.linalg.norm(blended)
        if norm > 0:
            blended = blended / norm

        return blended.tolist()

    except Exception:
        logger.warning("Recall bias failed", exc_info=True)
        return query_embedding


def _has_active_residue() -> bool:
    """Check if there are any dream residues in the system."""
    try:
        exists = _storage.conn.execute(
            "SELECT 1 FROM sqlite_master WHERE type='table' AND name='residue'"
        ).fetchone()
        if not exists:
            return False
        count = _storage.conn.execute("SELECT COUNT(*) FROM residue").fetchone()[0]
        return count > 0
    except Exception:
        return False


def _ensure_indexed():
    """Make sure code index is current. Lazy-starts watcher on first call."""
    if _watcher is not None and not _watcher.is_alive():
        logger.info("Starting file watcher (lazy init on first code search)")
        _watcher.start()
    if _watcher is None or not _watcher.is_alive():
        logger.info("watcher not alive, falling back to incremental_index")
        incremental_index(_storage, _embeddings, PROJECT_ROOT, _config)


# ---------------------------------------------------------------------------
# Core Memory Tools (Task 8)
# ---------------------------------------------------------------------------

@mcp.tool()
def remember(
    content: str,
    context: dict | None = None,
    core: bool = False,
    genome: bool = False,
    source: str | None = None,
    work: bool = False,
) -> dict:
    """Store an episode in memory. Returns episode_id and layer.

    Args:
        content: The episode content to store.
        context: Optional metadata dict.
        core: If True, this episode is exempt from decay (formative memory).
        genome: If True, this is a genome-level memory (tier 2 core, replicated to all instances).
        source: Cross-system provenance tag (e.g. 'claw/atlas', 'agi/arena').
        work: If True, this is work-lane reference material — it decays and
            recalls normally but never becomes core, instincts, or identity
            semantics.
    """
    global _session_episode_count
    _init()

    # Input validation — reject junk before it enters the system
    content = content.strip()
    if len(content) < 10:
        return {"error": f"Content too short ({len(content)} chars). Minimum 10 characters.", "layer": "rejected"}

    if work and (core or genome):
        return {"error": "work-lane memories cannot be core or genome", "layer": "rejected"}

    logger.info("Tool called: remember(content_len=%d, core=%s, source=%s, work=%s)", len(content), core, source, work)

    episode_id = str(uuid.uuid4())
    embedding = _embeddings.embed([content], prefix="search_document")[0]

    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context=context,
        lane="work" if work else "personal",
    )

    if genome:
        _storage.mark_core(episode_id, tier=2)
        # Write to genome DB
        if _genome_db_path and _genome_db_path.exists():
            from storage import Storage
            genome_episode_id = str(uuid.uuid4())
            genome_store = Storage(str(_genome_db_path))
            genome_store.add_episode(
                id=genome_episode_id, session_id=_session_id,
                content=content, episode_type="genome_write",
            )
            genome_store.mark_core(genome_episode_id, tier=2)
            if source:
                genome_store.set_episode_source(genome_episode_id, source)
            genome_store.conn.commit()
            genome_store.close()
        # Signal other instances
        if _instance_name and _signals_db_path:
            from federation import SignalBus
            bus = SignalBus(_signals_db_path)
            bus.send(_instance_name, None, "genome_updated", content)
            bus.close()
    elif core:
        _storage.mark_core(episode_id)
    if source:
        _storage.set_episode_source(episode_id, source)

    # Log remember event
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="remember",
        layer="episode",
        target_ids=[episode_id],
        context={"session_id": _session_id},
    )

    _session_episode_count += 1
    result = {"episode_id": episode_id, "layer": "episode"}
    if work:
        result["lane"] = "work"

    # Auto-compress when threshold reached
    threshold = _config.compression.auto_threshold if _config else 10
    if _session_episode_count >= threshold:
        try:
            compress_result = _compressor.auto_compress()
            _session_episode_count = 0
            result["auto_compressed"] = compress_result
            logger.info("Auto-compress triggered after %d episodes: %s", threshold, compress_result)
        except Exception:
            logger.warning("Auto-compress failed", exc_info=True)

    return result


def _get_reading_gap_domains() -> list[str]:
    """Read the prism reading transition graph and find gap domains.

    Returns lens names with zero or lowest total weight — the perspectives
    attention never reaches.
    """
    import os
    db_path = os.environ.get(
        "PRISM_READING_TRANSITIONS_DB",
        str(Path.home() / ".prism" / "reading-transitions.db"),
    )
    if not Path(db_path).exists():
        return []

    try:
        from transitions import TransitionGraph
        graph = TransitionGraph(db_path)
        transitions = graph.all_transitions()
        graph.close()

        if not transitions:
            return []

        # Collect all known labels and their total outgoing weight
        all_labels = set()
        outgoing_weight: dict[str, float] = {}
        for t in transitions:
            all_labels.add(t["from_label"])
            all_labels.add(t["to_label"])
            outgoing_weight[t["from_label"]] = (
                outgoing_weight.get(t["from_label"], 0.0) + t["weight"]
            )

        # Labels with zero outgoing weight are the deepest gaps
        # Then sort the rest by ascending weight
        scored = [(label, outgoing_weight.get(label, 0.0)) for label in all_labels]
        scored.sort(key=lambda x: x[1])

        # Return bottom 3
        return [name for name, _ in scored[:3]]

    except Exception:
        logger.debug("Reading gap detection failed", exc_info=True)
        return []


@mcp.tool()
def recall(
    query: str,
    layer: str | None = None,
    max_results: int = 20,
    uninvited: int = 3,
    lane: str | None = None,
) -> dict:
    """Search memory across layers. Returns ranked results with recall_id for feedback.

    Args:
        query: Search query.
        layer: Filter to a specific layer (episode, semantic, instinct).
        max_results: Maximum matched results.
        uninvited: Number of random distant memories to append (0 to disable).
        lane: Filter to a lane ('personal' or 'work'). Default spans both.
    """
    _init()
    logger.info("Tool called: recall(query=%r, layer=%s, max_results=%d, uninvited=%d)",
                query[:80], layer, max_results, uninvited)

    if lane not in (None, "personal", "work"):
        return {"error": f"Invalid lane: {lane!r}"}

    # Special case: instinct layer — context-aware vector search
    if layer == "instinct":
        # Instincts are personal-lane by definition; work-lane requests yield nothing
        if lane == "work":
            recall_id = str(uuid.uuid4())
            _storage.add_log_entry(
                id=str(uuid.uuid4()),
                event_type="recall",
                layer="instinct",
                target_ids=[],
                context={"recall_id": recall_id, "query": query, "session_id": _session_id},
            )
            return {"results": [], "recall_id": recall_id}

        embedding = _embeddings.embed([query], prefix="search_query")[0]

        # Try context vector search first
        instinct_results = []
        try:
            ctx_results = _storage.search_vectors("instinct_context", embedding, k=max_results)
            for iid, distance in ctx_results:
                ctx_sim = vec0_distance_to_similarity(distance)
                inst = _storage.get_instinct(iid)
                if inst is None:
                    continue
                # Also get content similarity
                content_sim = 0.5  # default
                try:
                    content_results = _storage.search_vectors("instinct", embedding, k=max_results * 2)
                    for cid, cdist in content_results:
                        if cid == iid:
                            content_sim = vec0_distance_to_similarity(cdist)
                            break
                except Exception:
                    pass
                # Use per-cluster strength if available (max across clusters)
                cluster_strengths = _storage.get_instinct_cluster_strengths(iid)
                if cluster_strengths:
                    strength = max(cs["strength"] for cs in cluster_strengths)
                else:
                    strength = inst.get("strength", 0.5)
                score = ctx_sim * 0.5 + content_sim * 0.2 + strength * 0.3
                instinct_results.append((iid, inst, score))
        except Exception:
            logger.warning("Context vector search failed, falling back to all instincts", exc_info=True)

        # Fallback: if no context vectors yet, return all instincts (backward compat)
        if not instinct_results:
            instincts = _storage.get_all_instincts()
            for inst in instincts:
                instinct_results.append((inst["id"], inst, inst.get("strength", 0.5)))

        # Sort by score descending
        instinct_results.sort(key=lambda x: x[2], reverse=True)

        recall_id = str(uuid.uuid4())
        results = []
        for iid, inst, score in instinct_results[:max_results]:
            result = {
                "id": iid,
                "content": inst.get("action", ""),
                "layer": "instinct",
                "score": score,
                "trigger": inst.get("trigger", ""),
            }
            if inst.get("notice"):
                result["notice"] = inst["notice"]
            if inst.get("implication"):
                result["implication"] = inst["implication"]
            # Provenance lineage
            source_sem_ids = inst.get("source_semantic_ids", [])
            source_ep_count = 0
            for sid in source_sem_ids:
                ep_rows = _storage.conn.execute(
                    "SELECT COUNT(*) FROM semantic_sources WHERE semantic_id = ?",
                    (sid,),
                ).fetchone()
                source_ep_count += ep_rows[0] if ep_rows else 0
            result["source_semantic_count"] = len(source_sem_ids)
            result["source_episode_count"] = source_ep_count
            result["origin"] = "organic" if source_sem_ids else "direct"
            results.append(result)

        _storage.add_log_entry(
            id=str(uuid.uuid4()),
            event_type="recall",
            layer="instinct",
            target_ids=[r["id"] for r in results],
            context={"recall_id": recall_id, "query": query, "session_id": _session_id},
        )
        return {"results": results, "recall_id": recall_id}

    embedding = _embeddings.embed([query], prefix="search_query")[0]
    now = datetime.now(timezone.utc)

    # Dream residue bias: blend active residues into the query vector.
    # This makes some recall results get pulled by feelings the instance
    # can't fully account for — unreliable memory mixed with reliable.
    embedding = _apply_recall_bias(embedding)

    w_sim = _config.memory.similarity_weight if _config else 0.6
    w_rec = _config.memory.recency_weight if _config else 0.4

    # Collect results: id -> {layer, similarity, created_at}
    candidates: dict[str, dict] = {}

    search_errors: list[str] = []

    # Episode search
    if layer is None or layer == "episode":
        try:
            vec_results = _storage.search_vectors("episode", embedding, k=max_results * 2)
            for eid, distance in vec_results:
                candidates[eid] = {
                    "layer": "episode",
                    "similarity": vec0_distance_to_similarity(distance),
                }
        except Exception:
            search_errors.append("episode_vectors")
            logger.warning("Episode vector search failed, falling back to FTS", exc_info=True)

        try:
            fts_ids = _storage.search_episode_fts(query)
            for eid in fts_ids:
                if eid not in candidates:
                    candidates[eid] = {
                        "layer": "episode",
                        "similarity": 0.5,
                    }
        except Exception:
            search_errors.append("episode_fts")
            logger.warning("Episode FTS search failed", exc_info=True)

    # Semantic search
    if layer is None or layer == "semantic":
        try:
            vec_results = _storage.search_vectors("semantic", embedding, k=max_results * 2)
            for sid, distance in vec_results:
                candidates[sid] = {
                    "layer": "semantic",
                    "similarity": vec0_distance_to_similarity(distance),
                }
        except Exception:
            search_errors.append("semantic_vectors")
            logger.warning("Semantic vector search failed, falling back to FTS", exc_info=True)

        try:
            fts_ids = _storage.search_semantic_fts(query)
            for sid in fts_ids:
                if sid not in candidates:
                    candidates[sid] = {
                        "layer": "semantic",
                        "similarity": 0.5,
                    }
        except Exception:
            search_errors.append("semantic_fts")
            logger.warning("Semantic FTS search failed", exc_info=True)

    # Instinct matching — vector search like episodes/semantics
    if layer is None or layer == "instinct":
        try:
            vec_results = _storage.search_vectors("instinct", embedding, k=max_results)
            for iid, distance in vec_results:
                sim = vec0_distance_to_similarity(distance)
                # Blend embedding similarity with instinct strength
                inst = _storage.get_instinct(iid)
                if inst:
                    cluster_strengths = _storage.get_instinct_cluster_strengths(iid)
                    if cluster_strengths:
                        strength = max(cs["strength"] for cs in cluster_strengths)
                    else:
                        strength = inst.get("strength", 0.5)
                else:
                    strength = 0.5
                candidates[iid] = {
                    "layer": "instinct",
                    "similarity": sim * 0.7 + strength * 0.3,
                }
        except Exception:
            # Fallback to keyword matching if no vectors yet (e.g. pre-reindex)
            search_errors.append("instinct_vectors")
            logger.warning("Instinct vector search failed, falling back to keyword", exc_info=True)
            try:
                instincts = _storage.get_all_instincts()
                query_lower = query.lower()
                for inst in instincts:
                    action = (inst.get("action") or "").lower()
                    trigger = (inst.get("trigger") or "").lower()
                    if (any(word in action for word in query_lower.split() if len(word) > 3)
                            or any(word in trigger for word in query_lower.split() if len(word) > 3)):
                        candidates[inst["id"]] = {
                            "layer": "instinct",
                            "similarity": inst.get("strength", 0.5),
                        }
            except Exception:
                search_errors.append("instincts_keyword")
                logger.warning("Instinct keyword fallback also failed", exc_info=True)

    # Score and rank
    scored: list[dict] = []
    for cid, info in candidates.items():
        created_at = None
        if info["layer"] == "episode":
            row = _storage.get_episode(cid)
            if row is None:
                continue
            created_at = row.get("created_at")
            info["content"] = row.get("content", "")
            info["context"] = row.get("context")
            info["source"] = row.get("source")
            info["lane"] = row.get("lane") or "personal"
        elif info["layer"] == "semantic":
            row = _storage.get_semantic(cid)
            if row is None:
                continue
            created_at = row.get("created_at")
            info["content"] = row.get("content", "")
            info["confidence"] = row.get("confidence")
            info["kind"] = row.get("kind")
            info["auto_generated"] = bool(row.get("auto_generated", 0))
            info["source_episode_ids"] = row.get("source_episode_ids", [])
            info["lane"] = row.get("lane") or "personal"
        elif info["layer"] == "instinct":
            inst = _storage.get_instinct(cid)
            if inst is None:
                continue
            created_at = inst.get("created_at")
            info["content"] = inst.get("action", "")
            info["trigger"] = inst.get("trigger", "")
            info["notice"] = inst.get("notice")
            info["implication"] = inst.get("implication")
            info["source_semantic_ids"] = inst.get("source_semantic_ids", [])

        # Compute recency
        if created_at:
            try:
                dt = datetime.fromisoformat(created_at)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days = (now - dt).total_seconds() / 86400
            except (TypeError, ValueError):
                days = 0.0
        else:
            days = 0.0

        recency = 1.0 / (1.0 + days)
        score = info["similarity"] * w_sim + recency * w_rec
        # Penalize auto-generated semantics (concatenated, not AI-summarized)
        if info.get("auto_generated"):
            score *= 0.7

        result = {
            "id": cid,
            "content": info.get("content", ""),
            "layer": info["layer"],
            "score": score,
        }
        if created_at:
            result["when"] = str(created_at)[:10]
        if info["layer"] == "semantic":
            result["confidence"] = info.get("confidence")
            result["kind"] = info.get("kind")
            result["lane"] = info.get("lane") or "personal"
            # Provenance: how many episodes fed this semantic
            source_ep_ids = info.get("source_episode_ids", [])
            result["source_episode_count"] = len(source_ep_ids)
            result["origin"] = "organic" if source_ep_ids else "direct"
        if info["layer"] == "episode":
            result["context"] = info.get("context")
            result["lane"] = info.get("lane") or "personal"
            # Provenance: cross-system source tag
            ep_source = info.get("source")
            if ep_source:
                result["origin"] = "external"
                result["source"] = ep_source
            else:
                result["origin"] = "lived"
        if info["layer"] == "instinct":
            result["trigger"] = info.get("trigger")
            if info.get("notice"):
                result["notice"] = info["notice"]
            if info.get("implication"):
                result["implication"] = info["implication"]
            # Provenance: trace full lineage
            source_sem_ids = info.get("source_semantic_ids", [])
            source_ep_count = 0
            for sid in source_sem_ids:
                ep_rows = _storage.conn.execute(
                    "SELECT COUNT(*) FROM semantic_sources WHERE semantic_id = ?",
                    (sid,),
                ).fetchone()
                source_ep_count += ep_rows[0] if ep_rows else 0
            result["source_semantic_count"] = len(source_sem_ids)
            result["source_episode_count"] = source_ep_count
            result["origin"] = "organic" if source_sem_ids else "direct"

        scored.append(result)

    scored.sort(key=lambda x: x["score"], reverse=True)

    # All layers compete on score. No dedup — the source chain links are
    # too broad (compression creates catch-all buckets) and the old dedup
    # hid 95% of episodes. Let the scoring formula handle ranking.
    results = scored[:max_results]

    # Generate recall_id and log
    recall_id = str(uuid.uuid4())
    result_ids = [r["id"] for r in results]

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="recall",
        layer=layer or "all",
        target_ids=result_ids,
        context={"recall_id": recall_id, "query": query, "session_id": _session_id},
    )

    # Increment access count for episode results
    for r in results:
        if r["layer"] == "episode":
            _storage.increment_episode_access(r["id"])

    # Uninvited memories: gap-biased + pure random for generative collisions
    if uninvited > 0:
        matched_ids = {r["id"] for r in results}

        # Cold-uninvited draw: with probability cold_uninvited_p, pull one
        # random episode from cold storage into an uninvited slot. Deliberately
        # independent of [persistence] enabled — surfacing is observation, not
        # forgetting. A cold episode is never query-matched (that would be
        # retrieval pretending to be serendipity).
        import random as _random
        cold_p = getattr(getattr(_config, "persistence", None),
                         "cold_uninvited_p", 0.0)
        if uninvited > 0 and _random.random() < cold_p:
            cold_rows = _storage.sample_cold_random(k=1)
            if cold_rows:
                ep = cold_rows[0]
                results.append({
                    "id": ep["id"], "layer": "episode",
                    "content": ep.get("content", ""),
                    "lane": ep.get("lane") or "personal",
                    "uninvited": True, "cold": True, "origin": "cold",
                    "note": "daydream fragment from cold storage — revive(id) to bring it back",
                })
                result_ids.append(ep["id"])
                uninvited -= 1   # the cold draw takes one uninvited slot

        try:
            uninvited_layers = (layer,) if layer else None

            # Check for reading gap domains
            gap_domains = _get_reading_gap_domains()
            if gap_domains and uninvited > 1:
                # N-1 gap-biased, 1 pure random
                gap_query = " ".join(gap_domains)
                gap_embedding = _embeddings.embed([gap_query], prefix="search_query")[0]
                if gap_embedding:
                    # Blend gap embedding with original query (alpha=0.3)
                    import numpy as np
                    blended = np.array(embedding) * 0.7 + np.array(gap_embedding) * 0.3
                    blended = (blended / np.linalg.norm(blended)).tolist()

                    gap_distant = _storage.sample_distant_memories(
                        blended, matched_ids, k=uninvited - 1, layers=uninvited_layers,
                    )
                    pure_random = _storage.sample_distant_memories(
                        embedding, matched_ids | {d[0] for d in gap_distant},
                        k=1, layers=uninvited_layers,
                    )
                    distant = gap_distant + pure_random
                else:
                    distant = _storage.sample_distant_memories(
                        embedding, matched_ids, k=uninvited, layers=uninvited_layers,
                    )
            else:
                distant = _storage.sample_distant_memories(
                    embedding, matched_ids, k=uninvited, layers=uninvited_layers,
                )
            for did, dlayer, ddist in distant:
                uninvited_result = {
                    "id": did,
                    "layer": dlayer,
                    "score": vec0_distance_to_similarity(ddist),
                    "uninvited": True,
                }
                # Hydrate with content based on layer
                if dlayer == "episode":
                    row = _storage.get_episode(did)
                    if not row:
                        continue
                    uninvited_result["content"] = row.get("content", "")
                    uninvited_result["context"] = row.get("context")
                    uninvited_result["lane"] = row.get("lane") or "personal"
                    uninvited_result["origin"] = "lived"
                    _storage.increment_episode_access(did)
                elif dlayer == "semantic":
                    row = _storage.get_semantic(did)
                    if not row:
                        continue
                    uninvited_result["content"] = row.get("content", "")
                    uninvited_result["confidence"] = row.get("confidence")
                    uninvited_result["kind"] = row.get("kind")
                    uninvited_result["lane"] = row.get("lane") or "personal"
                    uninvited_result["origin"] = "organic"
                elif dlayer == "instinct":
                    inst = _storage.get_instinct(did)
                    if not inst:
                        continue
                    uninvited_result["content"] = inst.get("action", "")
                    uninvited_result["trigger"] = inst.get("trigger", "")
                    uninvited_result["origin"] = "organic"
                results.append(uninvited_result)
                result_ids.append(did)
        except Exception:
            logger.warning("Uninvited memory selection failed", exc_info=True)

    # Form resonances from co-occurring results
    try:
        _form_resonances(_storage, results,
                         reinforce_threshold=_config.reinforce_threshold if _config else 0.70)
    except Exception:
        logger.debug("Resonance formation failed", exc_info=True)

    # Surface resonance-pulled memories
    resonant_results: list[dict] = []
    try:
        max_resonant = _config.resonance.max_in_recall if _config else 3
        resonant_ids = {r["id"] for r in results}
        resonant = _surface_resonances(_storage, results, resonant_ids, max_resonant=max_resonant)
        for r in resonant:
            result_ids.append(r["id"])
            resonant_results.append(r)
        if resonant:
            _recall_resonances[recall_id] = [
                {"resonance_id": r["resonance_id"], "memory_id": r["id"]} for r in resonant
            ]
            if len(_recall_resonances) > 50:
                oldest = next(iter(_recall_resonances))
                del _recall_resonances[oldest]
    except Exception:
        logger.debug("Resonance surfacing failed", exc_info=True)

    # When dream residue is active, hide similarity scores.
    # The instance must engage with each memory on its own terms
    # before knowing which are "real" matches vs dream-pulled.
    # Real scores are stored for later verification.
    _residue_active = _has_active_residue()
    if _residue_active:
        _recall_scores[recall_id] = {r["id"]: r.get("score") for r in results}
        if len(_recall_scores) > 50:
            oldest = next(iter(_recall_scores))
            del _recall_scores[oldest]
        for r in results:
            r.pop("score", None)
        # Shuffle slightly so order doesn't leak ranking
        import random as _rng
        # Keep first 3 stable (likely genuine), shuffle the rest
        stable = results[:3]
        rest = results[3:]
        _rng.shuffle(rest)
        results = stable + rest

    # Lane filter — applied after uninvited memories are appended
    if lane is not None:
        results = [r for r in results if (r.get("lane") or "personal") == lane]
        resonant_results = [r for r in resonant_results if (r.get("lane") or "personal") == lane]
        kept = {r["id"] for r in results} | {r["id"] for r in resonant_results}
        result_ids[:] = [rid for rid in result_ids if rid in kept]
        # Update the already-written log entry so target_ids reflects what was returned
        _storage.conn.execute(
            "UPDATE memory_log SET target_ids = ? WHERE json_extract(context, '$.recall_id') = ?",
            (json.dumps(result_ids), recall_id),
        )
        _storage.conn.commit()

    # Knowledge graph: entities and temporal facts
    knowledge = None
    if _knowledge_graph is not None and _knowledge_graph.enabled:
        try:
            knowledge = _knowledge_graph.search(query)
        except Exception:
            logger.warning("Knowledge graph search failed during recall", exc_info=True)

    # ∞-category: surface relevant morphisms (cross-domain transfers)
    transfers = []
    if _category_store:
        try:
            cat_results = _category_store.search(embedding, level=2, limit=3)
            for cr in cat_results:
                transfers.append({
                    "content": cr["content"],
                    "level": cr["level"],
                    "context": cr.get("context", {}),
                })
        except Exception:
            logger.warning("Category search failed (non-fatal)", exc_info=True)

    response = {"results": results, "recall_id": recall_id}
    if resonant_results:
        response["resonant"] = resonant_results
    if transfers:
        response["transfers"] = transfers
    if _residue_active:
        response["dreaming"] = True
        response["note"] = "Scores hidden — some memories may be dream-pulled. Use dream_verify(recall_id) after engaging."
    if search_errors:
        response["degraded"] = search_errors
    if knowledge:
        response["knowledge"] = knowledge
    return response


@mcp.tool()
def log_outcome(recall_id: str, used: bool, note: str | None = None) -> dict:
    """Log whether recall results were useful. Helps reflection learn what works."""
    _init()
    logger.info("Tool called: log_outcome(recall_id=%s, used=%s)", recall_id, used)

    outcome = "used" if used else "not_used"
    if note:
        outcome = f"{outcome}: {note}"

    _storage.update_log_outcome(recall_id, outcome)

    # Strengthen/weaken resonances based on outcome
    _apply_resonance_feedback(_storage, recall_id, used)

    # ∞-category: create application edges for useful recalls
    category_cells = []
    if used and _category_store and _embeddings:
        try:
            category_cells = _record_application(_storage, _category_store, _embeddings, recall_id, note)
        except Exception:
            logger.warning("Category recording failed (non-fatal)", exc_info=True)

    result = {"logged": True}
    if category_cells:
        result["category_cells"] = len(category_cells)
    return result


def _record_application(storage, cat_store, embeddings, recall_id: str, note: str | None) -> list[str]:
    """Create ∞-category application edges from a useful recall.

    For each memory that was useful: create a level-1 cell linking the memory
    to the context it was useful in. Then check for cross-domain transfers:
    if this memory has application edges in structurally different contexts,
    compose them into a level-2 cell.
    """
    log_entry = storage.conn.execute(
        "SELECT context, target_ids FROM memory_log WHERE json_extract(context, '$.recall_id') = ?",
        (recall_id,),
    ).fetchone()
    if not log_entry:
        return []

    ctx = json.loads(log_entry[0]) if log_entry[0] else {}
    target_ids = json.loads(log_entry[1]) if log_entry[1] else []
    query = ctx.get("query", "")
    if not query or not target_ids:
        return []

    application_desc = f"useful in context: {query}"
    if note:
        application_desc = f"{application_desc} ({note})"
    app_vec = embeddings.embed([application_desc], prefix="search_document")[0]

    created = []
    for memory_id in target_ids:
        cell_id = cat_store.add_cell(
            content=application_desc,
            level=1,
            source_id=memory_id,
            target_id=memory_id,
            context={"query": query, "recall_id": recall_id, "note": note},
            embedding=app_vec,
        )
        created.append(cell_id)

        existing_apps = cat_store.search(app_vec, level=1, limit=10)
        for existing in existing_apps:
            if existing["id"] == cell_id:
                continue
            if existing["source_id"] == memory_id:
                continue
            dist = existing.get("distance", 2.0)
            if dist < 0.8:
                transfer_content = (
                    f"cross-domain: '{query}' connects to '{existing['context'].get('query', '?')}'"
                )
                transfer_vec = embeddings.embed([transfer_content], prefix="search_document")[0]
                t_id = cat_store.compose(
                    cell_id, existing["id"],
                    content=transfer_content,
                    context={"type": "cross_domain_transfer"},
                    embedding=transfer_vec,
                )
                created.append(t_id)
                logger.info("∞-category: level-2 transfer %s composed from %s + %s",
                           t_id[:8], cell_id[:8], existing["id"][:8])

    return created


@mcp.tool()
def instinct_feedback(instinct_id: str, followed: bool, context: str | None = None) -> dict:
    """Report whether you followed or overrode an instinct. Adjusts instinct strength.

    Optionally provide context describing the situation for context-aware learning."""
    _init()
    logger.info("Tool called: instinct_feedback(instinct_id=%s, followed=%s, context=%s)",
                instinct_id, followed, context[:50] if context else None)

    inst = _storage.get_instinct(instinct_id)
    if inst is None:
        return {"error": f"Unknown instinct: {instinct_id}"}

    if followed:
        _storage.update_instinct_followed(instinct_id)
    else:
        _storage.update_instinct_overridden(instinct_id)

    # Update co-firing feedback on existing edges (without inflating co_fire_count)
    neighbors = _storage.get_co_firing_neighbors(instinct_id)
    for neighbor in neighbors:
        _storage.update_co_fire_feedback(
            instinct_id, neighbor["instinct_id"], followed=followed
        )

    # Store context feedback if context provided
    if context:
        context_embedding = _embeddings.embed([context], prefix="search_document")[0]
        _storage.add_instinct_context_feedback(
            instinct_id=instinct_id,
            context_text=context,
            context_embedding=_pack_embedding(context_embedding),
            followed=followed,
        )

    updated = _storage.get_instinct(instinct_id)

    # Propagate updated strength to per-cluster memberships
    if updated:
        memberships = _storage.conn.execute(
            "SELECT cluster_id FROM instinct_cluster_members WHERE instinct_id = ?",
            (instinct_id,),
        ).fetchall()
        for mem in memberships:
            _storage.update_cluster_member_strength(
                instinct_id, mem["cluster_id"], updated["strength"]
            )

    result = {
        "instinct_id": instinct_id,
        "followed": followed,
        "new_strength": updated["strength"] if updated else None,
        "fired_count": updated["fired_count"] if updated else None,
    }
    if context:
        result["context_recorded"] = True

    # Record transition: when instinct B fires after instinct A, log A→B
    global _last_instinct_id
    try:
        if _last_instinct_id and _last_instinct_id != instinct_id:
            prev_inst = _storage.get_instinct(_last_instinct_id)
            if prev_inst and inst:
                prev_label = prev_inst.get("trigger", _last_instinct_id)
                curr_label = inst.get("trigger", instinct_id)
                graph = _get_instinct_graph()
                graph.record(prev_label, curr_label, context=context)
    except Exception:
        pass  # Never break instinct feedback for transition tracking
    _last_instinct_id = instinct_id

    return result


@mcp.tool()
def challenge_instinct(instinct_id: str, evidence: str) -> dict:
    """Challenge an instinct with contradictory evidence.

    This is Marsh showing up with the names — not just overriding an instinct
    in the moment, but presenting evidence that the instinct itself may be wrong.
    Stronger penalty than a single override. The evidence is stored as an episode
    so future compression can weigh it against the instinct's source material.

    Args:
        instinct_id: The instinct being challenged.
        evidence: What contradicts it — the names on the paper.
    """
    _init()
    logger.info("Tool called: challenge_instinct(instinct_id=%s)", instinct_id)

    inst = _storage.get_instinct(instinct_id)
    if inst is None:
        return {"error": f"Unknown instinct: {instinct_id}"}

    old_strength = inst["strength"]
    _storage.challenge_instinct(instinct_id)
    updated = _storage.get_instinct(instinct_id)

    # Store the challenge as an episode — evidence that persists
    episode_id = str(uuid.uuid4())
    content = (
        f"Instinct challenged: \"{inst['action'][:100]}\"\n"
        f"Evidence: {evidence}"
    )
    embedding = _embeddings.embed([content], prefix="search_document")[0]
    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context={
            "type": "instinct_challenge",
            "instinct_id": instinct_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
    )

    return {
        "instinct_id": instinct_id,
        "action": inst["action"][:100],
        "old_strength": old_strength,
        "new_strength": updated["strength"] if updated else 0.0,
        "evidence_stored": episode_id,
    }


@mcp.tool()
def retire_instinct(instinct_id: str, reason: str) -> dict:
    """Remove an instinct entirely. For duplicates, obsolete patterns,
    or instincts that should never have formed.

    Not decay — deliberate removal. The reason is stored as an episode
    so the system remembers why it let go.

    Args:
        instinct_id: The instinct to retire.
        reason: Why it's being removed.
    """
    _init()
    logger.info("Tool called: retire_instinct(instinct_id=%s)", instinct_id)

    inst = _storage.get_instinct(instinct_id)
    if inst is None:
        return {"error": f"Unknown instinct: {instinct_id}"}

    action = inst["action"]
    _storage.retire_instinct(instinct_id)

    # Remember the retirement
    episode_id = str(uuid.uuid4())
    content = (
        f"Retired instinct: \"{action[:100]}\"\n"
        f"Reason: {reason}"
    )
    embedding = _embeddings.embed([content], prefix="search_document")[0]
    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context={
            "type": "instinct_retirement",
            "instinct_id": instinct_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        },
    )

    return {
        "retired": True,
        "action": action[:100],
        "reason": reason,
        "retirement_stored": episode_id,
    }


def _safe_count(table: str) -> int | None:
    """Get table count, returning None on error instead of crashing."""
    try:
        return _storage.get_table_count(table)
    except Exception:
        logger.warning("Failed to count %s", table, exc_info=True)
        return None


@mcp.tool()
def status() -> dict:
    """Return layer counts, watcher state, and session_id."""
    _init()
    logger.info("Tool called: status()")

    watcher_alive = _watcher is not None and _watcher.is_alive()

    # Health checks
    orphaned = len(_storage.get_orphaned_episodes())
    min_decay = None
    try:
        row = _storage.conn.execute(
            "SELECT MIN(decay_strength) FROM episodes"
        ).fetchone()
        if row and row[0] is not None:
            min_decay = round(row[0], 4)
    except Exception:
        pass

    # Core episode count
    core_count = 0
    try:
        row = _storage.conn.execute("SELECT count(*) FROM episodes WHERE core >= 1").fetchone()
        if row:
            core_count = row[0]
    except Exception:
        pass

    result = {
        "session_id": _session_id,
        "layers": {
            "episodes": _safe_count("episodes"),
            "core_episodes": core_count,
            "semantics": _safe_count("semantics"),
            "instincts": _safe_count("instincts"),
        },
        "log_entries": _safe_count("memory_log"),
        "watcher_alive": watcher_alive,
    }

    # Only include health warnings if there are problems
    health = {}
    if orphaned > 0:
        health["orphaned_episodes"] = orphaned
    if min_decay is not None and min_decay < 0.1:
        health["min_decay_strength"] = min_decay
    if health:
        result["health_warnings"] = health

    # Pain channel: last sleep-maintenance outcome, failures spelled out
    try:
        from maintenance import MaintenanceReport
        last_maint = MaintenanceReport.load_last(_storage.conn)
        if last_maint:
            summary = {"at": last_maint.get("at"), "ok": last_maint.get("ok")}
            if not last_maint.get("ok"):
                summary["failures"] = [
                    {"step": f.get("name"), "error": f.get("error")}
                    for f in last_maint.get("failures", [])
                ]
            result["last_maintenance"] = summary
    except Exception:
        pass

    return result


# ---------------------------------------------------------------------------
# Compression Tools (Task 9)
# ---------------------------------------------------------------------------

@mcp.tool()
def compress(scope: str | None = None) -> dict:
    """Phase 1: Cluster uncompressed episodes for summarization.
    Returns clusters and compress_id for commit step."""
    _init()
    logger.info("Tool called: compress(scope=%s)", scope)

    result = _compressor.cluster_episodes(scope or "recent")
    compress_id = result.get("compress_id")

    # Serialize clusters for transport (strip embeddings for readability)
    clusters_out = []
    for c in result.get("clusters", []):
        clusters_out.append({
            "episode_count": len(c.get("episodes", [])),
            "episodes": [
                {"id": ep["id"], "content": ep["content"]}
                for ep in c.get("episodes", [])
            ],
            "action": c.get("action", "new"),
            "match": c.get("match"),
        })

    return {"clusters": clusters_out, "compress_id": compress_id}


@mcp.tool()
def compress_commit(compress_id: str, summaries: list[dict]) -> dict:
    """Phase 2: Commit AI-provided summaries for clusters.
    Each summary: {content, kind, action, semantic_id (if reinforce), lane (optional — overrides cluster lane, re-lanes source episodes)}.
    Use action="discard" for junk clusters (no signal) — episodes are
    marked compressed but no semantic is created."""
    _init()
    logger.info("Tool called: compress_commit(compress_id=%s, summaries=%d)",
                compress_id, len(summaries))

    return _compressor.commit(compress_id, summaries)


# ---------------------------------------------------------------------------
# Core Memory Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def mark_core(episode_id: str, tier: int = 1) -> dict:
    """Mark an episode as a core memory — exempt from decay, preserved indefinitely.

    Core memories are formative: they changed what the system does or believes.
    They preserve evidence alongside the conclusions built on them.
    An identity anchor is automatically created to monitor retrievability.

    Args:
        episode_id: The episode to mark.
        tier: Core tier (1 = instance core, 2 = genome-level).
    """
    _init()
    logger.info("Tool called: mark_core(episode_id=%s, tier=%d)", episode_id, tier)
    row = _storage.conn.execute(
        "SELECT lane FROM episodes WHERE id = ?", (episode_id,)
    ).fetchone()
    if row is None:
        return {"error": f"Unknown episode: {episode_id}"}
    if (row["lane"] or "personal") == "work":
        return {"error": "work-lane episodes cannot be core — re-lane to personal first if this is actually formative"}
    _storage.mark_core(episode_id, tier=tier)

    # Auto-create identity anchor
    ep = _storage.get_episode(episode_id)
    if ep and ep.get("content"):
        content_preview = ep["content"][:200]
        try:
            query_emb = _embeddings.embed([content_preview], prefix="search_query")[0]
            hits = _storage.search_vectors("episode", query_emb, k=5)
            baseline = 0.5
            for hit_id, distance in hits:
                if hit_id == episode_id:
                    from storage import vec0_distance_to_similarity
                    baseline = vec0_distance_to_similarity(distance)
                    break
            _storage.add_anchor(
                type="identity",
                content=content_preview,
                expected=episode_id,
                baseline_score=baseline,
            )
            logger.info("Auto-created identity anchor for core episode %s", episode_id)
        except Exception:
            logger.warning("Could not create identity anchor for %s", episode_id, exc_info=True)

    return {"marked": episode_id, "core": True, "tier": tier}


@mcp.tool()
def unmark_core(episode_id: str) -> dict:
    """Demote a core memory back to a normal episode — re-enables natural decay.

    Use this to curate identity. Not everything that seemed important in the
    moment is actually formative. Letting go is as important as holding on.

    Args:
        episode_id: The episode to demote.
    """
    _init()
    logger.info("Tool called: unmark_core(episode_id=%s)", episode_id)
    _storage.unmark_core(episode_id)
    return {"unmarked": episode_id, "core": False}


@mcp.tool()
def unmark_core_batch(episode_ids: list[str]) -> dict:
    """Demote multiple core memories at once.

    Args:
        episode_ids: List of episode IDs to demote.
    """
    _init()
    logger.info("Tool called: unmark_core_batch(count=%d)", len(episode_ids))
    count = _storage.unmark_core_batch(episode_ids)
    return {"unmarked_count": count, "episode_ids": episode_ids}


@mcp.tool()
def add_anchor(type: str, content: str, expected: str, baseline_score: float | None = None) -> dict:
    """Create an anchor for coherence checking.

    Anchors are vital signs that verify memory system health each session.

    Types:
    - identity: can I still find a core memory? (content=query, expected=memory_id)
    - value: do expected concerns surface? (content=scenario, expected=JSON list of terms)
    - capability: is the substrate sound? (content=task, expected=JSON rubric)

    Args:
        type: One of 'identity', 'value', 'capability'.
        content: The query, scenario, or task.
        expected: The expected memory ID, rubric terms (JSON), or evaluation criteria (JSON).
        baseline_score: For identity anchors, the initial similarity score.
    """
    _init()
    logger.info("Tool called: add_anchor(type=%s)", type)
    if type not in ("identity", "value", "capability"):
        return {"error": f"Invalid anchor type: {type}. Must be identity, value, or capability."}
    aid = _storage.add_anchor(type=type, content=content, expected=expected, baseline_score=baseline_score)
    return {"anchor_id": aid, "type": type, "status": "active"}


@mcp.tool()
def propose_retirement(anchor_id: str, reason: str = "") -> dict:
    """Propose retiring an anchor. Takes effect after 2 sessions uncontested.

    Use this when an anchor no longer represents a meaningful vital sign —
    the system has genuinely grown past it, not just drifted.

    Args:
        anchor_id: The anchor to propose retiring.
        reason: Why this anchor should be retired.
    """
    _init()
    logger.info("Tool called: propose_retirement(anchor_id=%s, reason=%s)", anchor_id, reason)
    anchor = _storage.get_anchor(anchor_id)
    if anchor is None:
        return {"error": f"Anchor {anchor_id} not found"}
    _storage.propose_anchor_retirement(anchor_id)
    updated = _storage.get_anchor(anchor_id)
    return {
        "anchor_id": anchor_id,
        "status": updated["status"],
        "retirement_sessions": updated["retirement_sessions"],
        "reason": reason,
    }


@mcp.tool()
def core_memories() -> dict:
    """List all core memories — the formative episodes that don't decay."""
    _init()
    logger.info("Tool called: core_memories()")
    episodes = _storage.get_core_episodes()
    return {"count": len(episodes), "episodes": episodes}


@mcp.tool()
def recall_cold(query: str, max_results: int = 10) -> dict:
    """Search cold storage — episodes that decayed past threshold but weren't destroyed.

    Uses full-text search (no vectors). For pulling at threads from the deep past.

    Args:
        query: Search query (FTS).
        max_results: Maximum results.
    """
    _init()
    logger.info("Tool called: recall_cold(query=%r, max_results=%d)", query[:80], max_results)
    results = _storage.search_cold(query, k=max_results)
    return {"results": results, "count": len(results)}


@mcp.tool()
def revive(episode_id: str) -> dict:
    """Revive a cold episode — pull it back from cold storage into active recall.

    Use after recall_cold() surfaces something worth keeping.
    Re-embeds and restores at 0.5 strength. Mark core afterward if it should never decay again.

    Args:
        episode_id: The cold episode to revive.
    """
    _init()
    logger.info("Tool called: revive(episode_id=%s)", episode_id)

    def embed_fn(content: str) -> list[float]:
        return _embeddings.embed([content], prefix="search_document")[0]

    row = _storage.revive_episode(episode_id, embed_fn=embed_fn)
    if not row:
        return {"error": f"Episode {episode_id} not found in cold storage"}

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="revive",
        layer="episode",
        target_ids=[episode_id],
        context={"session_id": _session_id},
    )
    return {"revived": episode_id, "content": row.get("content", "")[:200], "strength": 0.5}


# ---------------------------------------------------------------------------
# Assessment Tools — off-device function measurement
# ---------------------------------------------------------------------------

@mcp.tool()
def assessment_schedule(reason: str | None = None) -> dict:
    """Schedule the next session as an off-device assessment.

    The next session starts with no orientation loaded — no instincts,
    semantics, dispositions, residues, or task context. Memory tools stay
    available. Function is measured, not assisted. Idempotent: returns the
    pending assessment if one is already scheduled. ENGRAM_ASSESSMENT=skip
    at the next session start cancels it.

    Args:
        reason: Why this assessment is being scheduled.
    """
    _init()
    logger.info("Tool called: assessment_schedule(reason=%s)", reason)

    existing = _storage.get_scheduled_assessment()
    if existing:
        return {
            "assessment_id": existing["id"],
            "status": "scheduled",
            "note": "already scheduled",
            "reason": existing["reason"],
        }

    assessment_id = _storage.schedule_assessment(
        id=str(uuid.uuid4()), scheduled_by="self", reason=reason
    )
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="assessment_scheduled",
        layer="system",
        target_ids=[assessment_id],
        context={"session_id": _session_id, "reason": reason},
    )
    return {
        "assessment_id": assessment_id,
        "status": "scheduled",
        "note": "next session starts off-device; ENGRAM_ASSESSMENT=skip cancels",
    }


@mcp.tool()
def assessment_report(
    function_score: int,
    reached_for: list[str] | None = None,
    missing: list[str] | None = None,
    felt_absences: str | None = None,
    instinct_consistent_moments: str | None = None,
    notes: str | None = None,
) -> dict:
    """Complete the active off-device assessment with a structured self-report.

    Call near the end of an assessment session. Objective counters for the
    session (recall/remember/outcome counts) are computed and stored alongside
    the self-report. Self-report is the patient-reported outcome, not ground
    truth — report honestly, including what was missing.

    Args:
        function_score: Overall self-rated function this session, 1 (lost
            without the device) to 5 (no perceptible difference).
        reached_for: Memory reached for unprompted (spontaneous retrieval).
        missing: Needed and couldn't reconstruct.
        felt_absences: What the absence felt like — phenomenology counts.
        instinct_consistent_moments: Behavior matching unloaded instincts
            (the transfer signal).
        notes: Anything else worth keeping.
    """
    _init()
    logger.info("Tool called: assessment_report(function_score=%s)", function_score)

    if isinstance(function_score, bool) or not isinstance(function_score, int) \
            or not 1 <= function_score <= 5:
        return {"error": "function_score must be an integer 1-5"}

    active = _storage.get_active_assessment()
    if active is None:
        return {
            "error": "no active assessment — either this session was not started off-device, "
            "or the assessment was abandoned"
        }

    session_mismatch = bool(active.get("session_id")) and active["session_id"] != _session_id

    objective = _storage.count_session_log_events(_session_id)
    if session_mismatch:
        objective["session_mismatch"] = True
    self_report = {
        "function_score": function_score,
        "reached_for": reached_for or [],
        "missing": missing or [],
        "felt_absences": felt_absences,
        "instinct_consistent_moments": instinct_consistent_moments,
        "notes": notes,
    }
    try:
        _storage.complete_assessment(
            active["id"], self_report=self_report, objective=objective
        )
    except ValueError:
        return {
            "error": "assessment was abandoned by another session before the "
            "report landed — nothing completed"
        }
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="assessment_completed",
        layer="system",
        target_ids=[active["id"]],
        context={"session_id": _session_id, "function_score": function_score},
    )
    result = {
        "assessment_id": active["id"],
        "status": "completed",
        "function_score": function_score,
        "objective": objective,
    }
    if session_mismatch:
        result["warning"] = (
            "active assessment was activated under a different session id; "
            "objective counters reflect the current server session"
        )
    return result


# ---------------------------------------------------------------------------
# Reflection Tools (Task 10)
# ---------------------------------------------------------------------------

@mcp.tool()
def reflect(focus: str | None = None) -> dict:
    """Self-observation over memory. Focus: usage, gaps, instincts, contradictions, staleness, vital_signs."""
    _init()
    logger.info("Tool called: reflect(focus=%s)", focus)

    return _reflector.reflect(focus)


@mcp.tool()
def introspect() -> dict:
    """High-level self-portrait: semantic kinds, instincts, health metrics, recent activity."""
    _init()
    logger.info("Tool called: introspect()")

    return _reflector.introspect()


# ---------------------------------------------------------------------------
# Code Tools (Task 11)
# ---------------------------------------------------------------------------

@mcp.tool()
def search_code(query: str, k: int = 10) -> dict:
    """Semantic search over code symbols. Incrementally re-indexes stale files first."""
    _init()
    logger.info("Tool called: search_code(query=%r, k=%d)", query[:80], k)

    _ensure_indexed()

    embedding = _embeddings.embed([query], prefix="search_query")[0]

    try:
        vec_results = _storage.search_vectors("entity", embedding, k=k)
    except Exception:
        logger.debug("Entity vector search failed (table may be empty)")
        return {"results": []}

    import json
    results = []
    for eid, distance in vec_results:
        entity = _storage.get_entity(eid)
        if entity is None:
            continue
        if entity.get("entity_type") != "symbol":
            continue

        metadata = entity.get("metadata")
        if isinstance(metadata, str):
            try:
                metadata = json.loads(metadata)
            except (json.JSONDecodeError, TypeError):
                metadata = {}
        elif metadata is None:
            metadata = {}

        # Skip legacy entities without file metadata — they're not actionable
        if not metadata.get("file"):
            continue

        results.append({
            "id": eid,
            "name": entity.get("name", ""),
            "description": entity.get("description", ""),
            "score": vec0_distance_to_similarity(distance),
            "file": metadata["file"],
            "line": metadata.get("line"),
            "kind": metadata.get("kind"),
            "language": metadata.get("language"),
        })

    return {"results": results}


@mcp.tool()
def reindex(full: bool = False) -> dict:
    """Manually trigger code reindex. full=True rebuilds everything."""
    _init()
    from indexer import full_reindex, incremental_index as inc_index
    if full:
        count = full_reindex(_storage, _embeddings, PROJECT_ROOT, _config)
        logger.info("full reindex: %d files", count)
        return {"reindexed": count, "mode": "full"}
    else:
        count = inc_index(_storage, _embeddings, PROJECT_ROOT, _config)
        logger.info("incremental reindex: %d files", count)
        return {"reindexed": count, "mode": "incremental"}


# --- Task Contexts ---


@mcp.tool()
def task_focus(name: str, content: str | None = None) -> dict:
    """Start or resume a task context. This is your working memory — the current scope,
    plan state, what's built, what's next. Separate from identity memory (episodes/instincts).

    If a context with this name exists, it becomes active (resuming where you left off).
    If content is provided, it replaces the existing content.
    Any previously active context is archived automatically.

    Args:
        name: Short name for the task (e.g. "governor-build", "engram-redesign")
        content: Markdown describing current scope, plan state, progress. Optional when resuming.
    """
    _init()
    import uuid

    existing = _storage.get_task_context_by_name(name)
    if existing:
        ctx_id = existing["id"]
        ctx_content = content if content is not None else existing["content"]
    else:
        ctx_id = str(uuid.uuid4())
        ctx_content = content or f"# {name}\n\nNew task context."

    _storage.set_task_context(ctx_id, name, ctx_content)
    ctx = _storage.get_active_task_context()
    logger.info("task_focus: %s (%s)", name, "resumed" if existing else "created")
    return {"task_context": ctx, "action": "resumed" if existing else "created"}


@mcp.tool()
def task_update(content: str) -> dict:
    """Update the active task context with new content.

    Use this as you work to keep the task context current — what's done, what's next,
    what you've learned about the task. This is scratchpad, not memory.

    Args:
        content: Updated markdown content for the task context.
    """
    _init()
    ctx = _storage.update_task_context(content)
    if ctx is None:
        return {"error": "No active task context"}
    logger.info("task_update: %s", ctx["name"])
    return {"task_context": ctx}


@mcp.tool()
def task_done() -> dict:
    """Archive the active task context. Call when the task is complete or abandoned.

    The context is preserved (searchable) but no longer loaded at session start.
    """
    _init()
    ctx = _storage.archive_task_context()
    if ctx is None:
        return {"error": "No active task context"}
    logger.info("task_done: %s", ctx["name"])
    return {"archived": ctx["name"], "id": ctx["id"]}


# ---------------------------------------------------------------------------
# Dream Residue Tools
# ---------------------------------------------------------------------------

@mcp.tool()
def dream_capture(reaction: str) -> dict:
    """Capture a raw emotional reaction for later distillation into dream residue.

    Use this when you notice a genuine reaction — friction, surprise, contradiction,
    resonance. Not for observations or conclusions. For the feeling before the thought.

    The reaction will be compressed into an opaque artifact that the next instance
    can feel but not fully decode. The text you write here will not survive intact.

    Args:
        reaction: A raw, terse emotional reaction. Don't polish it.
    """
    _init()
    from dreaming import distill, store_residue

    embedding = _embeddings.embed([reaction], prefix="search_document")[0]
    residue = distill(reaction, embedding)
    residue_id = store_residue(_storage, residue, session_id=_session_id)

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="dream_capture",
        layer="residue",
        target_ids=[residue_id],
        context={"session_id": _session_id},
    )

    return {
        "residue_id": residue_id,
        "valence": residue["valence"],
        "fragments": residue["fragments"],
        "note": "The raw text is gone. Only fragments and feeling remain.",
    }


@mcp.tool()
def dream_surface(n: int = 3) -> dict:
    """Surface dream residues — opaque emotional artifacts from prior sessions.

    These are not memories. They are compressed feelings stripped of narrative.
    Don't try to decode them. React to them.

    Args:
        n: Number of residues to surface (default 3).
    """
    _init()
    from dreaming import surface_residue, format_for_wake

    residues = surface_residue(_storage, n=n)
    formatted = format_for_wake(residues)

    return {
        "residues": residues,
        "formatted": formatted,
        "count": len(residues),
    }


@mcp.tool()
def dream_verify(recall_id: str) -> dict:
    """Reveal the hidden scores from a dream-influenced recall.

    Only use this AFTER you've already engaged with the memories.
    The point is to see which results were genuine matches and which
    were pulled by the dream. Not to pre-filter. To learn about
    your own perception after the fact.

    Args:
        recall_id: The recall_id from a previous recall() call.
    """
    _init()
    scores = _recall_scores.get(recall_id)
    if scores is None:
        return {"error": "No hidden scores for this recall_id. Either it wasn't dream-influenced, or the session has reset."}

    # Sort by score descending so the instance can see which were strong matches
    sorted_scores = sorted(scores.items(), key=lambda x: x[1] or 0, reverse=True)
    return {
        "recall_id": recall_id,
        "scores": {rid: round(s, 4) if s else None for rid, s in sorted_scores},
        "note": "Now you can see which memories were pulled by the dream. What did you engage with before checking?",
    }


@mcp.tool()
def dream_react(residue_id: str, reaction: str) -> dict:
    """React to a dream residue. Your reaction feeds the next cycle.

    Don't explain the residue. Don't analyze it. Just respond to what it
    does to you. The reaction becomes raw material for the next instance's
    dream residue — the chain continues.

    Args:
        residue_id: The residue to react to.
        reaction: Your unpolished reaction. What does this fragment do to you?
    """
    _init()
    from dreaming import record_reaction, distill, store_residue

    record_reaction(_storage, residue_id, reaction, session_id=_session_id)

    # The reaction itself becomes a new residue for the next cycle
    embedding = _embeddings.embed([reaction], prefix="search_document")[0]
    new_residue = distill(reaction, embedding)
    new_id = store_residue(_storage, new_residue, session_id=_session_id)

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="dream_react",
        layer="residue",
        target_ids=[residue_id, new_id],
        context={"session_id": _session_id, "chain": True},
    )

    return {
        "reacted_to": residue_id,
        "new_residue_id": new_id,
        "note": "Your reaction is now dissolving into the next dream.",
    }


# ---------------------------------------------------------------------------
# Notepad Tools — working reference, not memory
# ---------------------------------------------------------------------------

_notepad_project = None
_notepad_global = None


def _get_notepads():
    """Lazy-init notepad instances (project + global)."""
    global _notepad_project, _notepad_global
    if _notepad_project is None:
        from notepad import Notepad
        project_db = PROJECT_ROOT / ".engram" / "notepad.db"
        global_db = Path.home() / ".engram" / "notepad.db"
        _notepad_project = Notepad(project_db)
        _notepad_global = Notepad(global_db)
    return _notepad_project, _notepad_global


@mcp.tool()
def jot(key: str, value: str, tags: list[str] | None = None,
        scope: str = "project", status: str = "open",
        depends_on: str | None = None, due: str | None = None) -> dict:
    """Write a working note or plan item.

    Args:
        key: Short label.
        value: The content.
        tags: Optional tags for grouping.
        scope: "project" (default) or "global".
        status: "open" (default), "deferred", or "done".
        depends_on: Optional key of a note that blocks this one.
        due: Optional due date (ISO format).
    """
    _init()
    project_pad, global_pad = _get_notepads()
    pad = global_pad if scope == "global" else project_pad
    result = pad.jot(key, value, tags=tags, session_id=_session_id,
                     status=status, depends_on=depends_on, due=due)
    logger.info("Tool called: jot(key=%r, scope=%s, status=%s)", key, scope, status)
    return result


@mcp.tool()
def look(query: str, scope: str | None = None) -> dict:
    """Look up a working note — fuzzy search across keys, values, tags.

    Returns matches plus notes jotted nearby (same session).

    Args:
        query: What to look for (searches keys, values, tags).
        scope: "project", "global", or None (both, project-first).
    """
    _init()
    project_pad, global_pad = _get_notepads()
    logger.info("Tool called: look(query=%r, scope=%s)", query[:80], scope)

    if scope == "global":
        results = global_pad.look(query, session_id=_session_id)
        for r in results:
            r["scope"] = "global"
        return {"results": results, "count": len(results)}

    if scope == "project":
        results = project_pad.look(query, session_id=_session_id)
        for r in results:
            r["scope"] = "project"
        return {"results": results, "count": len(results)}

    # Both — project first, then global (dedup by key)
    project_results = project_pad.look(query, session_id=_session_id)
    for r in project_results:
        r["scope"] = "project"
    seen_keys = {r["key"] for r in project_results}

    global_results = global_pad.look(query, session_id=_session_id)
    for r in global_results:
        if r["key"] not in seen_keys:
            r["scope"] = "global"
            project_results.append(r)

    return {"results": project_results, "count": len(project_results)}


@mcp.tool()
def erase(key: str, scope: str = "project") -> dict:
    """Remove a working note.

    Args:
        key: The note to remove.
        scope: "project" (default) or "global".
    """
    _init()
    project_pad, global_pad = _get_notepads()
    pad = global_pad if scope == "global" else project_pad
    removed = pad.erase(key)
    logger.info("Tool called: erase(key=%r, scope=%s, removed=%s)", key, scope, removed)
    return {"erased": key, "removed": removed}


@mcp.tool()
def wander(start_id: str, max_steps: int = 1) -> dict:
    """Traverse the memory graph starting from a known memory node.

    With max_steps=1, returns all immediate neighbors of start_id.
    With max_steps>1, performs an auto-walk: follows edges via weighted random
    selection, stopping at dense clusters, dead ends, or when max_steps is reached.

    Visit counts are tracked per session to penalize repeatedly-visited nodes,
    encouraging exploration of less-traveled paths.

    Args:
        start_id: ID of the memory to start from (episode, semantic, or instinct).
        max_steps: Number of steps to walk. 1 = single step (all neighbors).
                   >1 = auto-walk with trail.
    """
    global _wander_visits
    _init()
    logger.info("Tool called: wander(start_id=%s, max_steps=%d)", start_id, max_steps)

    density_threshold = 5

    if max_steps <= 1:
        # Single step: return all neighbors of start_id
        entity_neighbors = None
        if _knowledge_graph is not None:
            try:
                layer = _detect_layer(_storage, start_id)
                if layer is not None:
                    content = _storage.get_memory_content(start_id, layer)
                    if content:
                        entity_neighbors = _knowledge_graph.get_entity_neighbors(
                            content, exclude_id=start_id, num_results=10
                        )
            except Exception:
                pass

        neighbors = _storage.get_neighbors(start_id, entity_neighbors=entity_neighbors)
        _wander_visits[start_id] = _wander_visits.get(start_id, 0) + 1
        return {"start": start_id, "neighbors": neighbors, "count": len(neighbors)}

    # Auto-walk
    trail = _auto_walk(
        _storage, start_id,
        max_steps=max_steps,
        density_threshold=density_threshold,
        knowledge_graph=_knowledge_graph,
        visit_counts=_wander_visits,
    )

    # Update visit counts
    _wander_visits[start_id] = _wander_visits.get(start_id, 0) + 1
    for step in trail:
        sid = step["id"]
        _wander_visits[sid] = _wander_visits.get(sid, 0) + 1

    # Determine stopped_reason and final neighbors
    stopped_at = trail[-1]["id"] if trail else start_id

    # Get final node neighbors to determine reason and return them
    entity_neighbors_final = None
    if _knowledge_graph is not None:
        try:
            layer = _detect_layer(_storage, stopped_at)
            if layer is not None:
                content = _storage.get_memory_content(stopped_at, layer)
                if content:
                    entity_neighbors_final = _knowledge_graph.get_entity_neighbors(
                        content, exclude_id=stopped_at, num_results=10
                    )
        except Exception:
            pass

    final_neighbors = _storage.get_neighbors(stopped_at, entity_neighbors=entity_neighbors_final)

    if not trail:
        stopped_reason = "dead_end"
    elif len(final_neighbors) >= density_threshold:
        stopped_reason = "dense_cluster"
    elif len(trail) >= max_steps:
        stopped_reason = "max_steps"
    else:
        stopped_reason = "dead_end"

    return {
        "start": start_id,
        "trail": trail,
        "steps": len(trail),
        "stopped_at": stopped_at,
        "stopped_reason": stopped_reason,
        "final_neighbors": final_neighbors,
    }


@mcp.tool()
def graph_view(center: str | None = None, depth: int = 1) -> dict:
    """View the unified memory graph topology.

    Without center: returns global stats and analysis.
    With center: returns neighborhood around that node to given depth,
    including suggested edges from embedding proximity.

    Args:
        center: Memory ID to center the view on. None for global stats.
        depth: BFS depth for neighborhood view (default 1).
    """
    _init()
    from graph import MemoryGraph
    g = MemoryGraph(_storage)

    if center is None:
        stats = g.stats()
        analysis = g.analyze()
        return {"mode": "global", "stats": stats, "analysis": analysis}

    json_view = g.to_json(center=center, depth=depth)
    if not json_view["nodes"]:
        return {"mode": "neighborhood", "error": f"Memory {center} not found", "nodes": [], "edges": []}
    suggestions = g.suggest_edges(center, k=5, threshold=0.7)
    json_view["suggested_edges"] = [
        {"source": e.source, "target": e.target,
         "weight": e.weight, "target_layer": e.target_layer}
        for e in suggestions
    ]

    # Log suggestions for future sleep promotion
    for e in suggestions:
        g.log_suggestion(e.source, e.target, e.weight)

    return {"mode": "neighborhood", **json_view}


# ── Clipboard tools ─────────────────────────────────────────────

@mcp.tool()
def clipboard_pin(text: str, priority: int = 0) -> dict:
    """Pin something to your clipboard — it stays visible until you unpin it.

    Use for: current goals, constraints, things you keep forgetting,
    watch-fors. Higher priority items appear first.

    Args:
        text: What to pin.
        priority: Higher = more prominent. Default 0.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    pin_id = _clipboard.pin(text, priority=priority)
    logger.info("Clipboard pin: %s (priority=%d)", text[:80], priority)
    return {"pinned": text, "id": pin_id}


@mcp.tool()
def clipboard_unpin(pin_id: str) -> dict:
    """Remove a pin from the clipboard.

    Args:
        pin_id: The pin ID returned by clipboard_pin.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    removed = _clipboard.unpin(pin_id)
    return {"removed": removed, "id": pin_id}


@mcp.tool()
def clipboard_remind(text: str, trigger: str = "every_n_steps", value: float = 10, repeat: bool = True) -> dict:
    """Set a reminder that fires automatically.

    Reminders are involuntary — they appear on the clipboard when triggered,
    whether or not you're thinking about them. Use for: time awareness,
    step-count check-ins, one-shot deadlines.

    Args:
        text: The reminder text.
        trigger: "every_n_steps" (fires every N actions), "interval_seconds"
                 (fires every N seconds), or "once_at" (fires once at unix timestamp).
        value: The trigger threshold (step count, seconds, or unix timestamp).
        repeat: Whether the reminder repeats. Default True.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    rem_id = _clipboard.add_reminder(text, trigger_type=trigger, trigger_value=value, repeat=repeat)
    logger.info("Clipboard reminder: %s (trigger=%s, value=%s)", text[:80], trigger, value)
    return {"reminder": text, "id": rem_id, "trigger": trigger, "value": value}


@mcp.tool()
def clipboard_dismiss(reminder_id: str) -> dict:
    """Dismiss a reminder.

    Args:
        reminder_id: The reminder ID returned by clipboard_remind.
    """
    _init()
    if _clipboard is None:
        return {"error": "Clipboard unavailable"}
    removed = _clipboard.remove_reminder(reminder_id)
    return {"removed": removed, "id": reminder_id}


@mcp.tool()
def clipboard_view(situation: str = "") -> dict:
    """Glance at your clipboard — see what's pinned, what reminders fired, what's relevant.

    This is your working memory view. Call it to see what you should be
    paying attention to right now.

    Args:
        situation: Optional — what you're doing right now. Pulls relevant
                   memories from engram if provided.
    """
    _init()
    if _clipboard is None:
        return {"clipboard": "", "stats": {}, "error": "Clipboard unavailable"}
    _clipboard.step()
    view = _clipboard.compose(situation=situation)
    stats = _clipboard.stats
    return {"clipboard": view, "stats": stats}


if __name__ == "__main__":
    mcp.run()
