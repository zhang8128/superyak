"""Engram MCP Server v3 — layered memory with compression and reflection."""
from __future__ import annotations

import json
import logging
import os
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
ENGRAM_HOME = Path(os.environ.get("ENGRAM_HOME", Path.home() / "Projects" / "engram"))
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
_genome_db_path = None
_signals_db_path = None
_recall_scores: dict[str, dict[str, float]] = {}  # recall_id -> {result_id: score}
_recall_resonances: dict[str, list[dict]] = {}  # recall_id -> [{resonance_id, memory_id}]
_instinct_graph = None
_last_instinct_id = None
_knowledge_graph = None


from resonance import form_resonances as _form_resonances, surface_resonances as _surface_resonances
from transitions import TransitionGraph


def _get_instinct_graph():
    global _instinct_graph
    if _instinct_graph is None:
        db_path = Path(os.environ.get("ENGRAM_HOME", Path.home())) / ".engram" / "instinct_transitions.db"
        _instinct_graph = TransitionGraph(db_path=db_path)
    return _instinct_graph


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
    global _storage, _embeddings, _config, _compressor, _reflector, _watcher, _session_id, _instance_name, _genome_db_path, _signals_db_path, _knowledge_graph
    if _storage is not None:
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

    _session_id = str(uuid.uuid4())

    from compress import Compressor
    from dedup import Deduplicator, DedupConfig

    dedup_model = os.environ.get("ENGRAM_DEDUP_MODEL", "qwen3.5:27b")
    _dedup = Deduplicator(DedupConfig(model=dedup_model))

    # Knowledge graph (Graphiti + Kuzu)
    graph_model = os.environ.get("ENGRAM_GRAPH_MODEL")
    if _config and _config.graph.enabled:
        from knowledge import KnowledgeGraph
        graph_config = _config.graph
        if graph_model:
            graph_config.model = graph_model
        if not graph_config.db_path:
            graph_config.db_path = str(db_path.parent / "knowledge.kuzu")
        _knowledge_graph = KnowledgeGraph(graph_config)
    else:
        _knowledge_graph = None

    _compressor = Compressor(
        _storage, _embeddings,
        _config.compression if _config else None,
        deduplicator=_dedup,
        knowledge_graph=_knowledge_graph,
    )

    from reflection import Reflector
    _genome_db_path = ENGRAM_HOME / ".engram" / "genome" / "graph.db"
    _signals_db_path = ENGRAM_HOME / ".engram" / "signals.db"
    _reflector = Reflector(
        _storage,
        _config.reflection.staleness_days if _config else 30,
        genome_db_path=str(_genome_db_path) if _genome_db_path and _genome_db_path.exists() else None,
        signals_db_path=str(_signals_db_path) if _signals_db_path and _signals_db_path.exists() else None,
    )

    # Watcher is created but NOT started — lazy-started on first code search
    from watcher import FileWatcher
    _watcher = FileWatcher(PROJECT_ROOT, _config.watcher, _storage, _embeddings)
    import atexit
    atexit.register(lambda: _watcher.stop() if _watcher else None)
    atexit.register(lambda: _storage.close() if _storage else None)
    atexit.register(lambda: _knowledge_graph.close() if _knowledge_graph else None)

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
    try:
        # 1. Apply decay: weaken memories that weren't accessed last session
        decayed = _storage.apply_decay(factor=0.9)
        if decayed:
            logger.info("Decay applied to %d episodes", decayed)

        # 2. Prune: delete compressed episodes that have decayed past threshold
        pruned = _storage.prune_decayed(threshold=0.05)
        if pruned:
            logger.info("Pruned %d decayed episodes", pruned)

        # 2b. Prune weak instincts (overridden enough to drop below threshold)
        pruned_instincts = _storage.prune_weak_instincts(strength_threshold=0.1)
        if pruned_instincts:
            logger.info("Pruned %d weak instincts", pruned_instincts)

        # 3. Auto-compress uncompressed episodes (crash recovery + consolidation)
        uncompressed = _storage.get_uncompressed_episodes()
        if uncompressed:
            logger.info("Auto-compressing %d uncompressed episodes on init", len(uncompressed))
            _compressor.auto_compress()
        # 4. Backfill: embed any episodes that lost vectors (WAL corruption recovery)
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

        # 6. Backfill notice/implication for pre-existing instincts
        _backfill_instinct_perceptual(_storage, _embeddings)
    except Exception:
        logger.warning("Sleep-time maintenance failed — will retry next session", exc_info=True)

    # Log session start
    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="session_start",
        layer="system",
        target_ids=[],
        context={"session_id": _session_id},
    )


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
        logger.debug("Recall bias skipped", exc_info=True)
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
) -> dict:
    """Store an episode in memory. Returns episode_id and layer.

    Args:
        content: The episode content to store.
        context: Optional metadata dict.
        core: If True, this episode is exempt from decay (formative memory).
        genome: If True, this is a genome-level memory (tier 2 core, replicated to all instances).
        source: Cross-system provenance tag (e.g. 'claw/atlas', 'agi/arena').
    """
    global _session_episode_count
    _init()

    # Input validation — reject junk before it enters the system
    content = content.strip()
    if len(content) < 10:
        return {"error": f"Content too short ({len(content)} chars). Minimum 10 characters.", "layer": "rejected"}

    logger.info("Tool called: remember(content_len=%d, core=%s, source=%s)", len(content), core, source)

    episode_id = str(uuid.uuid4())
    embedding = _embeddings.embed([content], prefix="search_document")[0]

    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context=context,
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


@mcp.tool()
def recall(
    query: str,
    layer: str | None = None,
    max_results: int = 20,
    uninvited: int = 3,
) -> dict:
    """Search memory across layers. Returns ranked results with recall_id for feedback.

    Args:
        query: Search query.
        layer: Filter to a specific layer (episode, semantic, instinct).
        max_results: Maximum matched results.
        uninvited: Number of random distant memories to append (0 to disable).
    """
    _init()
    logger.info("Tool called: recall(query=%r, layer=%s, max_results=%d, uninvited=%d)",
                query[:80], layer, max_results, uninvited)

    # Special case: instinct layer — context-aware vector search
    if layer == "instinct":
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
                strength = inst.get("strength", 0.5) if inst else 0.5
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
        if info["layer"] == "semantic":
            result["confidence"] = info.get("confidence")
            result["kind"] = info.get("kind")
            # Provenance: how many episodes fed this semantic
            source_ep_ids = info.get("source_episode_ids", [])
            result["source_episode_count"] = len(source_ep_ids)
            result["origin"] = "organic" if source_ep_ids else "direct"
        if info["layer"] == "episode":
            result["context"] = info.get("context")
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

    # Uninvited memories: random distant samples for generative collisions
    if uninvited > 0:
        matched_ids = {r["id"] for r in results}
        try:
            uninvited_layers = (layer,) if layer else None
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
                    uninvited_result["origin"] = "lived"
                    _storage.increment_episode_access(did)
                elif dlayer == "semantic":
                    row = _storage.get_semantic(did)
                    if row:
                        uninvited_result["content"] = row.get("content", "")
                        uninvited_result["confidence"] = row.get("confidence")
                        uninvited_result["kind"] = row.get("kind")
                        uninvited_result["origin"] = "organic"
                elif dlayer == "instinct":
                    inst = _storage.get_instinct(did)
                    if inst:
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
    try:
        resonant_ids = {r["id"] for r in results}
        resonant = _surface_resonances(_storage, results, resonant_ids, max_resonant=2)
        for r in resonant:
            results.append(r)
            result_ids.append(r["id"])
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
        for r in results:
            r.pop("score", None)
        # Shuffle slightly so order doesn't leak ranking
        import random as _rng
        # Keep first 3 stable (likely genuine), shuffle the rest
        stable = results[:3]
        rest = results[3:]
        _rng.shuffle(rest)
        results = stable + rest

    # Knowledge graph: entities and temporal facts
    knowledge = None
    if _knowledge_graph is not None and _knowledge_graph.enabled:
        try:
            knowledge = _knowledge_graph.search(query)
        except Exception:
            logger.warning("Knowledge graph search failed during recall", exc_info=True)

    response = {"results": results, "recall_id": recall_id}
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

    return {"logged": True}


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
        content=content,
        embedding=embedding,
        context=json.dumps({
            "type": "instinct_challenge",
            "instinct_id": instinct_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }),
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
        content=content,
        embedding=embedding,
        context=json.dumps({
            "type": "instinct_retirement",
            "instinct_id": instinct_id,
            "date": datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        }),
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
    Each summary: {content, kind, action, semantic_id (if reinforce)}."""
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

    Args:
        episode_id: The episode to mark.
        tier: Core tier (1 = instance core, 2 = genome-level).
    """
    _init()
    logger.info("Tool called: mark_core(episode_id=%s, tier=%d)", episode_id, tier)
    _storage.mark_core(episode_id, tier=tier)
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
# Reflection Tools (Task 10)
# ---------------------------------------------------------------------------

@mcp.tool()
def reflect(focus: str | None = None) -> dict:
    """Self-observation over memory. Focus: usage, gaps, instincts, contradictions, staleness."""
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
        scope: str = "project") -> dict:
    """Write a working note — API surfaces, paths, gotchas, anything you'll need again.

    Not memory. Just a reference you can look up later.

    Args:
        key: Short label (e.g. "embed", "emma db", "add_episode").
        value: The reference content.
        tags: Optional tags for grouping.
        scope: "project" (default) or "global".
    """
    _init()
    project_pad, global_pad = _get_notepads()
    pad = global_pad if scope == "global" else project_pad
    result = pad.jot(key, value, tags=tags, session_id=_session_id)
    logger.info("Tool called: jot(key=%r, scope=%s)", key, scope)
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


if __name__ == "__main__":
    mcp.run()
