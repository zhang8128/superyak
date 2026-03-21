"""Engram MCP Server v3 — layered memory with compression and reflection."""
from __future__ import annotations

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

PROJECT_ROOT = Path(os.environ.get("ENGRAM_PROJECT_ROOT", os.getcwd()))
DB_PATH = PROJECT_ROOT / ".engram" / "graph.db"

_storage = None
_embeddings = None
_config = None
_compressor = None
_reflector = None
_watcher = None
_session_id = None
_session_episode_count = 0


def _init():
    global _storage, _embeddings, _config, _compressor, _reflector, _watcher, _session_id
    if _storage is not None:
        return
    from embeddings import NomicEmbedProvider
    from storage import Storage

    setup_logging(os.environ.get("ENGRAM_LOG_LEVEL", "INFO"))
    DB_PATH.parent.mkdir(parents=True, exist_ok=True)
    _config = load_config(PROJECT_ROOT)
    _storage = Storage(str(DB_PATH))
    _embeddings = NomicEmbedProvider()

    _session_id = str(uuid.uuid4())

    from compress import Compressor
    from dedup import Deduplicator, DedupConfig

    dedup_model = os.environ.get("ENGRAM_DEDUP_MODEL", "qwen3.5:27b")
    _dedup = Deduplicator(DedupConfig(model=dedup_model))

    _compressor = Compressor(
        _storage, _embeddings,
        _config.compression if _config else None,
        deduplicator=_dedup,
    )

    from reflection import Reflector
    _reflector = Reflector(
        _storage,
        _config.reflection.staleness_days if _config else 30,
    )

    # Watcher is created but NOT started — lazy-started on first code search
    from watcher import FileWatcher
    _watcher = FileWatcher(PROJECT_ROOT, _config.watcher, _storage, _embeddings)
    import atexit
    atexit.register(lambda: _watcher.stop() if _watcher else None)
    atexit.register(lambda: _storage.close() if _storage else None)

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

        # 3. Auto-compress uncompressed episodes (crash recovery + consolidation)
        uncompressed = _storage.get_uncompressed_episodes()
        if uncompressed:
            logger.info("Auto-compressing %d uncompressed episodes on init", len(uncompressed))
            _compressor.auto_compress()
        # 4. Backfill: embed any instincts that lack vectors (pre-existing instincts)
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
def remember(content: str, context: dict | None = None) -> dict:
    """Store an episode in memory. Returns episode_id and layer."""
    global _session_episode_count
    _init()
    logger.info("Tool called: remember(content_len=%d)", len(content))

    episode_id = str(uuid.uuid4())
    embedding = _embeddings.embed([content], prefix="search_document")[0]

    _storage.add_episode(
        id=episode_id,
        session_id=_session_id,
        content=content,
        embedding=embedding,
        context=context,
    )

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
) -> dict:
    """Search memory across layers. Returns ranked results with recall_id for feedback."""
    _init()
    logger.info("Tool called: recall(query=%r, layer=%s, max_results=%d)",
                query[:80], layer, max_results)

    # Special case: instinct layer
    if layer == "instinct":
        instincts = _storage.get_all_instincts()
        recall_id = str(uuid.uuid4())
        _storage.add_log_entry(
            id=str(uuid.uuid4()),
            event_type="recall",
            layer="instinct",
            target_ids=[i["id"] for i in instincts],
            context={"recall_id": recall_id, "query": query},
        )
        return {
            "results": [
                {
                    "id": i["id"],
                    "content": i.get("action", ""),
                    "layer": "instinct",
                    "score": i.get("strength", 0.5),
                    "trigger": i.get("trigger", ""),
                }
                for i in instincts
            ],
            "recall_id": recall_id,
        }

    embedding = _embeddings.embed([query], prefix="search_query")[0]
    now = datetime.now(timezone.utc)

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
        elif info["layer"] == "semantic":
            row = _storage.get_semantic(cid)
            if row is None:
                continue
            created_at = row.get("created_at")
            info["content"] = row.get("content", "")
            info["confidence"] = row.get("confidence")
            info["kind"] = row.get("kind")
            info["auto_generated"] = bool(row.get("auto_generated", 0))
        elif info["layer"] == "instinct":
            inst = _storage.get_instinct(cid)
            if inst is None:
                continue
            created_at = inst.get("created_at")
            info["content"] = inst.get("action", "")
            info["trigger"] = inst.get("trigger", "")

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
        if info["layer"] == "episode":
            result["context"] = info.get("context")
        if info["layer"] == "instinct":
            result["trigger"] = info.get("trigger")

        scored.append(result)

    scored.sort(key=lambda x: x["score"], reverse=True)

    # Deduplicate across layers: if an instinct covers a semantic which
    # covers an episode, keep only the highest-layer result.
    covered_ids: set[str] = set()
    for item in scored:
        if item["layer"] == "instinct":
            # Mark source semantics as covered
            src_rows = _storage.conn.execute(
                "SELECT semantic_id FROM instinct_sources WHERE instinct_id = ?",
                (item["id"],),
            ).fetchall()
            for (sid,) in src_rows:
                covered_ids.add(sid)
                # Also mark episodes that fed those semantics
                ep_rows = _storage.conn.execute(
                    "SELECT episode_id FROM semantic_sources WHERE semantic_id = ?",
                    (sid,),
                ).fetchall()
                for (eid,) in ep_rows:
                    covered_ids.add(eid)
        elif item["layer"] == "semantic":
            # Mark source episodes as covered
            src_rows = _storage.conn.execute(
                "SELECT episode_id FROM semantic_sources WHERE semantic_id = ?",
                (item["id"],),
            ).fetchall()
            for (eid,) in src_rows:
                covered_ids.add(eid)

    deduped = [item for item in scored if item["id"] not in covered_ids]
    results = deduped[:max_results]

    # Generate recall_id and log
    recall_id = str(uuid.uuid4())
    result_ids = [r["id"] for r in results]

    _storage.add_log_entry(
        id=str(uuid.uuid4()),
        event_type="recall",
        layer=layer or "all",
        target_ids=result_ids,
        context={"recall_id": recall_id, "query": query},
    )

    # Increment access count for episode results
    for r in results:
        if r["layer"] == "episode":
            _storage.increment_episode_access(r["id"])

    response = {"results": results, "recall_id": recall_id}
    if search_errors:
        response["degraded"] = search_errors
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

    return {"logged": True}


@mcp.tool()
def instinct_feedback(instinct_id: str, followed: bool) -> dict:
    """Report whether you followed or overrode an instinct. Adjusts instinct strength."""
    _init()
    logger.info("Tool called: instinct_feedback(instinct_id=%s, followed=%s)", instinct_id, followed)

    inst = _storage.get_instinct(instinct_id)
    if inst is None:
        return {"error": f"Unknown instinct: {instinct_id}"}

    if followed:
        _storage.update_instinct_followed(instinct_id)
    else:
        _storage.update_instinct_overridden(instinct_id)

    updated = _storage.get_instinct(instinct_id)
    return {
        "instinct_id": instinct_id,
        "followed": followed,
        "new_strength": updated["strength"] if updated else None,
        "fired_count": updated["fired_count"] if updated else None,
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

    return {
        "session_id": _session_id,
        "layers": {
            "episodes": _safe_count("episodes"),
            "semantics": _safe_count("semantics"),
            "instincts": _safe_count("instincts"),
        },
        "log_entries": _safe_count("memory_log"),
        "watcher_alive": watcher_alive,
    }


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


if __name__ == "__main__":
    mcp.run()
