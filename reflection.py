"""Engram reflection — self-observation and pattern analysis over memory."""
from __future__ import annotations

import json
import logging
from collections.abc import Callable
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("engram.reflection")

# Provisional gravity-well threshold: the degree-Gini above which the graph's
# connectivity is concentrated enough that recall and wander orbit a few hubs.
# Anchored to the one pathological graph measured so far (the live engram store
# read 0.61, having been observed to collapse every walk into a single cluster);
# a pure single-hub star tops out at 0.5. This is a measurement-first flag, not
# a calibrated boundary — recalibrate once healthy-graph baselines accumulate.
GRAVITY_WARN = 0.6


def _gravity_warning(gravity: float) -> str | None:
    """Return a warning string if degree concentration is pathological, else None."""
    if gravity > GRAVITY_WARN:
        return (
            f"gravity well: graph degree-Gini {gravity:.2f} exceeds provisional "
            f"threshold {GRAVITY_WARN} — connectivity is concentrated in a few hubs, "
            f"so recall and wander tend to orbit them"
        )
    return None


# Provisional low-fidelity threshold: cosine below which a semantic's embedding
# sits far enough from its source-episode centroid to warrant review — either a
# poor distillation at birth or drift as sources changed. Measurement-first, not
# calibrated; recalibrate once a fidelity distribution has been observed.
FIDELITY_LOW = 0.5


def _source_fidelity(semantic_vec, source_vecs) -> float:
    """Cosine between a semantic's embedding and the centroid of its source
    embeddings. 1.0 = the distillation still sits at the center of its sources;
    low = it has drifted from (or never matched) them. Returns 0.0 for
    degenerate zero-norm inputs rather than NaN."""
    import numpy as np
    s = np.asarray(semantic_vec, dtype=float)
    centroid = np.mean(np.asarray(source_vecs, dtype=float), axis=0)
    ns = float(np.linalg.norm(s))
    nc = float(np.linalg.norm(centroid))
    if ns == 0.0 or nc == 0.0:
        return 0.0
    return round(float(np.dot(s, centroid) / (ns * nc)), 4)


class Reflector:
    def __init__(self, storage, staleness_days=30,
                 genome_db_path: str | None = None,
                 signals_db_path: str | None = None,
                 *,
                 cohesion_config=None,
                 persistence_config=None,
                 category_reporter: Callable[[], dict] | None = None):
        self._storage = storage
        self._staleness_days = staleness_days
        self._genome_db_path = genome_db_path
        self._signals_db_path = signals_db_path
        self._cohesion_config = cohesion_config
        self._persistence_config = persistence_config
        self._category_reporter = category_reporter

    def analyze_category_evolution(self) -> dict:
        """Return optional category diagnostics without exposing reporter errors."""
        if self._category_reporter is None:
            return {"available": False}
        try:
            return self._category_reporter()
        except Exception as exc:
            logger.warning("Category evolution report failed (%s)", type(exc).__name__)
            return {"available": False, "error": type(exc).__name__}

    def analyze_usage(self) -> dict:
        """Most/least accessed episodes and semantics."""
        rows = self._storage.conn.execute(
            "SELECT id, content, accessed_count FROM episodes ORDER BY accessed_count DESC LIMIT 10"
        ).fetchall()
        most = [dict(r) for r in rows]

        rows_least = self._storage.conn.execute(
            "SELECT id, content, accessed_count FROM episodes ORDER BY accessed_count ASC LIMIT 10"
        ).fetchall()
        least = [dict(r) for r in rows_least]

        return {"most_accessed": most, "least_accessed": least}

    def detect_gaps(self) -> list[dict]:
        """Queries that returned no results (empty target_ids in recall log entries)."""
        entries = self._storage.get_log_entries(event_type="recall", limit=1000)
        gaps = []
        for entry in entries:
            target_ids_raw = entry.get("target_ids", "[]")
            try:
                target_ids = json.loads(target_ids_raw) if isinstance(target_ids_raw, str) else target_ids_raw
            except (json.JSONDecodeError, TypeError):
                target_ids = []

            if not target_ids:
                context_raw = entry.get("context")
                try:
                    context = json.loads(context_raw) if isinstance(context_raw, str) else (context_raw or {})
                except (json.JSONDecodeError, TypeError):
                    context = {}
                query = context.get("query", "")
                gaps.append({"query": query, "timestamp": entry.get("timestamp", "")})
        return gaps

    def instinct_health(self) -> list[dict]:
        """Instinct reliability analysis."""
        instincts = self._storage.get_all_instincts()
        results = []
        for inst in instincts:
            fired = inst.get("fired_count", 0) or 0
            followed = inst.get("followed_count", 0) or 0
            if fired == 0:
                reliability = 0.0
                recommendation = "unobserved"
            else:
                reliability = followed / fired
                if reliability > 0.7:
                    recommendation = "reliable"
                elif reliability <= 0.2:
                    recommendation = "weaken_or_remove"
                elif reliability < 0.3:
                    recommendation = "weak"
                else:
                    recommendation = "monitor"
            results.append({
                "id": inst["id"],
                "trigger": inst.get("trigger", ""),
                "action": inst.get("action", ""),
                "fired_count": fired,
                "followed_count": followed,
                "reliability": reliability,
                "recommendation": recommendation,
            })
        results.sort(key=lambda x: x["reliability"])
        return results

    def detect_staleness(self) -> list[dict]:
        """Semantics unreinforced for staleness_days."""
        cutoff = (datetime.now(timezone.utc) - timedelta(days=self._staleness_days)).isoformat()
        rows = self._storage.conn.execute(
            """
            SELECT id, content, kind, created_at, last_reinforced
            FROM semantics
            WHERE contradicted_by IS NULL
              AND (
                    (last_reinforced IS NULL AND created_at < ?)
                    OR (last_reinforced IS NOT NULL AND last_reinforced < ?)
                  )
            """,
            (cutoff, cutoff),
        ).fetchall()

        now = datetime.now(timezone.utc)
        result = []
        for row in rows:
            r = dict(row)
            ref_ts = r.get("last_reinforced") or r.get("created_at")
            try:
                dt = datetime.fromisoformat(ref_ts)
                if dt.tzinfo is None:
                    dt = dt.replace(tzinfo=timezone.utc)
                days_stale = (now - dt).days
            except (TypeError, ValueError):
                days_stale = 0
            result.append({
                "id": r["id"],
                "content": r["content"],
                "kind": r["kind"],
                "days_stale": days_stale,
            })
        return result

    def detect_contradictions(self) -> list[dict]:
        """Semantics that have been contradicted."""
        rows = self._storage.conn.execute(
            "SELECT id, content, contradicted_by FROM semantics WHERE contradicted_by IS NOT NULL"
        ).fetchall()
        return [{"id": r["id"], "content": r["content"], "contradicted_by": r["contradicted_by"]} for r in rows]

    def _lane_counts(self) -> dict:
        """Return per-table, per-lane counts for episodes and semantics."""
        lane_counts: dict[str, dict[str, int]] = {
            "episodes": {"personal": 0, "work": 0},
            "semantics": {"personal": 0, "work": 0},
        }
        for table in ("episodes", "semantics"):
            rows = self._storage.conn.execute(
                f"SELECT COALESCE(lane, 'personal') AS lane, COUNT(*) FROM {table} GROUP BY 1"
            ).fetchall()
            for lane_name, count in rows:
                lane_counts[table][lane_name] = count
        return lane_counts

    def vital_signs(self, include_graph: bool = True) -> dict:
        """Structural health checks for pathologies the other foci can't see.

        ``include_graph`` gates the graph-gravity scan (a full traversal); it
        is False on the no-focus default reflect() path and True for an
        explicit ``reflect(focus="vital_signs")``.


        The existing foci measure activity (usage, gaps, contradictions); these
        measure whether the regulating mechanisms themselves still function:
        core inflation disables decay's salience contrast, a frozen feedback
        loop means instinct strengths can never move, and access concentration
        shows whether recall is spread across memory or orbiting a few nodes.

        Both ``personal_episode_count`` and ``core_count`` are personal-lane
        scoped — they exclude any episodes in the work lane.
        """
        warnings = []

        # Compute lane_counts first; derive personal episode count from it
        # to avoid a redundant COUNT query.
        lane_counts = self._lane_counts()

        personal_episode_count = lane_counts["episodes"]["personal"]
        # core_count is personal-lane scoped — excludes work-lane episodes.
        core_count = self._storage.conn.execute(
            "SELECT COUNT(*) FROM episodes WHERE core >= 1 AND COALESCE(lane, 'personal') = 'personal'"
        ).fetchone()[0]
        core_fraction = (core_count / personal_episode_count) if personal_episode_count else 0.0
        if core_fraction > 0.3:
            warnings.append(
                f"core inflation: {core_count}/{personal_episode_count} personal episodes "
                f"({core_fraction:.0%}) are decay-exempt — salience contrast degrades above 30%"
            )

        instincts = self._storage.get_all_instincts()
        total_fired = sum(i.get("fired_count") or 0 for i in instincts)
        frozen = bool(instincts) and total_fired == 0
        if frozen:
            warnings.append(
                f"frozen instinct loop: {len(instincts)} instincts with zero feedback "
                f"events ever — strengths cannot move without instinct_feedback"
            )

        # Access concentration is deliberately lane-agnostic: it measures recall attention across ALL memory.
        rows = self._storage.conn.execute(
            "SELECT accessed_count FROM episodes ORDER BY accessed_count DESC"
        ).fetchall()
        counts = [r[0] or 0 for r in rows]
        total_accesses = sum(counts)
        top_n = max(1, len(counts) // 10)
        top_decile_share = (sum(counts[:top_n]) / total_accesses) if total_accesses else 0.0

        # Graph gravity: how concentrated is connectivity? A few nodes hoarding
        # edges create gravity wells that collapse recall/wander onto themselves.
        # The full graph traversal is heavy (a query per node), so it is gated
        # behind include_graph and left OUT of the no-focus default reflect() —
        # mirroring how cohesion and persistence are excluded from the default.
        # None means "not measured" (skipped or failed), distinct from 0.0
        # "measured, no concentration" — a failed metric must not read as healthy.
        graph_gravity = None
        if include_graph:
            try:
                from graph import MemoryGraph
                graph_gravity = MemoryGraph(self._storage).analyze()["gravity"]
            except Exception:
                logger.warning("gravity computation failed", exc_info=True)
                warnings.append("gravity metric unavailable — graph scan failed")
            else:
                gravity_warning = _gravity_warning(graph_gravity)
                if gravity_warning:
                    warnings.append(gravity_warning)

        return {
            "core_fraction": round(core_fraction, 3),
            "core_count": core_count,
            "personal_episode_count": personal_episode_count,
            "instinct_feedback": {
                "frozen": frozen,
                "total_fired": total_fired,
                "instinct_count": len(instincts),
            },
            "access_concentration": {"top_decile_share": round(top_decile_share, 3)},
            "graph_concentration": {"degree_gini": graph_gravity},
            "lanes": lane_counts,
            "warnings": warnings,
        }

    def introspect(self) -> dict:
        """High-level self-portrait of memory state."""
        # Group active semantics by kind
        rows = self._storage.conn.execute(
            "SELECT kind, COUNT(*) as count FROM semantics WHERE contradicted_by IS NULL GROUP BY kind"
        ).fetchall()
        semantics_by_kind = {r["kind"]: r["count"] for r in rows}

        # All instincts with strength
        instincts = self._storage.get_all_instincts()
        instinct_list = [
            {"id": inst["id"], "trigger": inst.get("trigger", ""), "action": inst.get("action", ""), "strength": inst.get("strength", 0.0)}
            for inst in instincts
        ]

        # Health metrics
        episode_count = self._storage.get_table_count("episodes")
        semantic_count = self._storage.get_table_count("semantics")

        avg_row = self._storage.conn.execute(
            "SELECT AVG(confidence) as avg_conf FROM semantics WHERE contradicted_by IS NULL"
        ).fetchone()
        avg_confidence = avg_row["avg_conf"] if avg_row and avg_row["avg_conf"] is not None else 0.0

        instinct_health_list = self.instinct_health()
        if instinct_health_list:
            avg_reliability = sum(i["reliability"] for i in instinct_health_list) / len(instinct_health_list)
        else:
            avg_reliability = 0.0

        health_metrics = {
            "episode_count": episode_count,
            "semantic_count": semantic_count,
            "avg_confidence": avg_confidence,
            "instinct_reliability": avg_reliability,
            "lanes": self._lane_counts(),
        }

        # Recent activity (last 10 log entries)
        recent_log = self._storage.get_log_entries(limit=10)
        recent_activity = [
            {"event_type": e.get("event_type"), "layer": e.get("layer"), "timestamp": e.get("timestamp")}
            for e in recent_log
        ]

        return {
            "semantics_by_kind": semantics_by_kind,
            "instincts": instinct_list,
            "health_metrics": health_metrics,
            "recent_activity": recent_activity,
        }

    def detect_genome_drift(self) -> list[dict]:
        """Compare local instincts against genome instincts. Returns drift observations."""
        if not self._genome_db_path:
            return []
        import sqlite3
        genome_conn = sqlite3.connect(self._genome_db_path)
        genome_conn.row_factory = sqlite3.Row
        genome_instincts = genome_conn.execute(
            "SELECT action, strength FROM instincts WHERE strength > 0.1"
        ).fetchall()
        local_instincts = self._storage.get_all_instincts()
        genome_conn.close()

        drift = []
        for gi in genome_instincts:
            for li in local_instincts:
                g_words = set(gi["action"].lower().split())
                l_words = set(li["action"].lower().split())
                overlap = g_words & l_words
                if len(overlap) > 2 and gi["action"] != li["action"]:
                    drift.append({
                        "type": "potential_drift",
                        "genome_instinct": gi["action"],
                        "genome_strength": gi["strength"],
                        "local_instinct": li["action"],
                        "local_strength": li["strength"],
                    })
        return drift

    def signal_health(self) -> dict | None:
        """Analyze signal responsiveness."""
        if not self._signals_db_path:
            return None
        import sqlite3
        conn = sqlite3.connect(self._signals_db_path)
        conn.row_factory = sqlite3.Row
        total = conn.execute("SELECT COUNT(*) FROM messages").fetchone()[0]
        conn.close()
        return {"total_messages": total}

    def instinct_context_health(self) -> list[dict]:
        """Per-context instinct health: follow/override ratio broken down by context."""
        instincts = self._storage.get_all_instincts()
        results = []
        for inst in instincts:
            feedback = self._storage.get_instinct_context_feedback(inst["id"])
            if not feedback:
                results.append({
                    "id": inst["id"],
                    "action": inst.get("action", ""),
                    "notice": inst.get("notice"),
                    "implication": inst.get("implication"),
                    "contexts": [],
                })
                continue

            # Group by context_text
            context_groups: dict[str, list[bool]] = {}
            for fb in feedback:
                ctx = fb["context_text"]
                if ctx not in context_groups:
                    context_groups[ctx] = []
                context_groups[ctx].append(bool(fb["followed"]))

            contexts = []
            for ctx, follows in context_groups.items():
                count = len(follows)
                follow_ratio = sum(follows) / count
                contexts.append({
                    "context": ctx,
                    "follow_ratio": follow_ratio,
                    "count": count,
                })

            results.append({
                "id": inst["id"],
                "action": inst.get("action", ""),
                "notice": inst.get("notice"),
                "implication": inst.get("implication"),
                "contexts": contexts,
            })
        return results

    def analyze_classifications(self) -> dict:
        """Show recent episode classifications for review."""
        rows = self._storage.conn.execute(
            "SELECT id, content, context, created_at FROM episodes "
            "ORDER BY created_at DESC LIMIT 20"
        ).fetchall()

        classified = []
        for row in rows:
            ep = dict(row)
            context_raw = ep.get("context")
            suggested = None
            if context_raw:
                try:
                    ctx = json.loads(context_raw) if isinstance(context_raw, str) else context_raw
                    suggested = ctx.get("suggested_kinds")
                except (ValueError, TypeError):
                    pass

            from compress import classify_episode_kind
            heuristic = classify_episode_kind(ep)

            classified.append({
                "id": ep["id"],
                "content": ep["content"][:100] if ep.get("content") else "",
                "heuristic_kinds": heuristic,
                "model_suggested": suggested,
                "created_at": ep.get("created_at"),
            })

        return {"recent_episodes": classified}

    def analyze_resonances(self) -> dict:
        """Show the associative resonance network."""
        rows = self._storage.conn.execute(
            "SELECT * FROM resonances ORDER BY strength DESC LIMIT 30"
        ).fetchall()

        network = []
        orphan_count = 0
        for row in rows:
            r = dict(row)
            a_content = self._get_memory_preview(r["memory_a"], r["layer_a"])
            b_content = self._get_memory_preview(r["memory_b"], r["layer_b"])

            if a_content is None:
                orphan_count += 1
            if b_content is None:
                orphan_count += 1

            network.append({
                "id": r["id"],
                "a": {"id": r["memory_a"], "layer": r["layer_a"], "preview": a_content},
                "b": {"id": r["memory_b"], "layer": r["layer_b"], "preview": b_content},
                "weight": r["weight"],
                "strength": r["strength"],
                "co_occurrences": r["co_occurrences"],
            })

        return {"network": network, "total": len(rows), "orphans": orphan_count}

    def _get_memory_preview(self, memory_id: str, layer: str) -> str | None:
        """Get a short content preview for a memory by layer."""
        if layer == "episode":
            row = self._storage.get_episode(memory_id)
            return row["content"][:80] if row and row.get("content") else None
        elif layer == "semantic":
            row = self._storage.get_semantic(memory_id)
            return row["content"][:80] if row and row.get("content") else None
        elif layer == "instinct":
            row = self._storage.get_instinct(memory_id)
            return row["action"][:80] if row and row.get("action") else None
        return None

    def analyze_instinct_clusters(self) -> list[dict]:
        """Analyze instinct cluster structure, membership, and temperament."""
        clusters = self._storage.get_all_clusters()
        result = []

        for cluster in clusters:
            cid = cluster["id"]
            members = self._storage.get_cluster_members(cid)

            member_details = []
            for m in members:
                inst = self._storage.get_instinct(m["instinct_id"])
                if inst:
                    member_details.append({
                        "id": m["instinct_id"],
                        "action": inst["action"][:100],
                        "notice": inst.get("notice", ""),
                        "cluster_strength": m["strength"],
                        "global_strength": inst["strength"],
                    })

            # Gather internal co-firing stats
            member_ids = {m["instinct_id"] for m in members}
            internal_edges = []
            for mid in member_ids:
                neighbors = self._storage.get_co_firing_neighbors(mid)
                for n in neighbors:
                    if n["instinct_id"] in member_ids:
                        internal_edges.append(n)

            total_co_fires = sum(e["co_fire_count"] for e in internal_edges) // 2
            total_follows = sum(e["co_follow_count"] for e in internal_edges) // 2
            total_overrides = sum(e["co_override_count"] for e in internal_edges) // 2

            result.append({
                "id": cid,
                "maturity": cluster["maturity"],
                "temperament": cluster["temperament"],
                "member_count": len(member_details),
                "members": member_details,
                "internal_co_fires": total_co_fires,
                "internal_follows": total_follows,
                "internal_overrides": total_overrides,
                "last_active": cluster.get("last_active"),
            })

        return result

    def analyze_coherence(self) -> dict:
        """Show the latest drift report with trend data."""
        latest = self._storage.get_latest_drift_report()
        if latest is None:
            return {"latest_report": None, "trend": []}

        history = self._storage.get_drift_history(limit=10)
        trend = []
        for report in history:
            try:
                apart = json.loads(report["drifted_apart"])
                together = json.loads(report["drifted_together"])
                unchall = json.loads(report["unchallenged"])
            except (json.JSONDecodeError, TypeError):
                apart, together, unchall = [], [], []
            trend.append({
                "session_id": report["session_id"],
                "checked_at": report["checked_at"],
                "drifted_apart": len(apart),
                "drifted_together": len(together),
                "unchallenged": len(unchall),
                "summary": report.get("summary"),
            })

        return {"latest_report": dict(latest), "trend": trend}

    def analyze_anchors(self) -> list[dict]:
        """Show all anchors with their current status and scores."""
        return self._storage.get_active_anchors()

    def analyze_assessments(self) -> dict:
        """Off-device assessment history — function over time."""
        history = []
        for a in self._storage.list_assessments(status="completed"):
            try:
                report = json.loads(a["self_report"]) if a["self_report"] else {}
                objective = json.loads(a["objective"]) if a["objective"] else {}
            except (json.JSONDecodeError, TypeError):
                history.append({
                    "id": a["id"],
                    "completed_at": a["completed_at"],
                    "function_score": None,
                    "parse_error": True,
                })
                continue
            transfer = report.get("instinct_consistent_moments") or ""
            history.append({
                "id": a["id"],
                "session_id": a["session_id"],
                "completed_at": a["completed_at"],
                "function_score": report.get("function_score"),
                "objective": objective,
                "reached_for": report.get("reached_for", []),
                "missing": report.get("missing", []),
                "transfer_preview": transfer[:100],
            })
        status_rows = self._storage.conn.execute(
            "SELECT status, COUNT(*) AS n FROM assessments GROUP BY status"
        ).fetchall()
        found = {r["status"]: r["n"] for r in status_rows}
        counts = {
            status: found.get(status, 0)
            for status in ("scheduled", "active", "completed", "skipped", "abandoned")
        }
        return {"history": history, "counts": counts}

    def analyze_cohesion(self) -> dict:
        """Sheaf cohesion: global energy picture, hottest semantics, audit trail."""
        from config import CohesionConfig
        from sheaf import measure_all
        measured = measure_all(self._storage, self._cohesion_config or CohesionConfig())
        hottest = []
        for entry in measured[:5]:
            sem = self._storage.get_semantic(entry["semantic_id"])
            edges = []
            for ea, eb, r in entry["worst_edges"]:
                rows = self._storage.conn.execute(
                    "SELECT id, substr(content, 1, 80) FROM episodes"
                    " WHERE id IN (?, ?)", (ea, eb)).fetchall()
                edges.append({"residual": round(r, 4),
                              "episodes": {row[0]: row[1] for row in rows}})
            hottest.append({"semantic_id": entry["semantic_id"],
                            "content": (sem or {}).get("content", "")[:120],
                            "energy": round(entry["energy"], 3),
                            "episodes": entry["n"], "worst_edges": edges})
        return {
            "semantics_measured": len(measured),
            "mean_energy": (round(sum(m["energy"] for m in measured)
                                  / len(measured), 3) if measured else None),
            "hottest": hottest,
            "recent_events": self._storage.get_subdivision_events(limit=10),
            "queued": self._storage.get_queued_subdivisions(),
        }

    def analyze_fidelity(self) -> dict:
        """Semantic-source fidelity: does each semantic still sit near its live
        source episodes, and how many have lost all their sources?

        Read-only and embedding-based (no LLM re-distillation, so no write-path
        corruption risk). 'Unreconcilable' semantics have no live source
        episodes — the provenance link is severed when a source is pruned to
        cold — so drift cannot be measured for them; their count quantifies how
        much reconciliation substrate the store has already lost.
        """
        from sheaf import _unpack_embedding
        rows = self._storage.conn.execute(
            "SELECT s.id, s.content, sv.embedding FROM semantics s"
            " JOIN semantic_vectors sv ON sv.id = s.id"
        ).fetchall()
        reconcilable = []
        unreconcilable = 0
        for sid, content, sem_blob in rows:
            src = self._storage.conn.execute(
                "SELECT ev.embedding FROM semantic_sources ss"
                " JOIN episode_vectors ev ON ev.id = ss.episode_id"
                " WHERE ss.semantic_id = ?", (sid,)).fetchall()
            if not src:
                unreconcilable += 1
                continue
            fid = _source_fidelity(_unpack_embedding(sem_blob),
                                   [_unpack_embedding(r[0]) for r in src])
            reconcilable.append({"semantic_id": sid,
                                 "content": (content or "")[:120],
                                 "fidelity": fid,
                                 "live_sources": len(src)})
        reconcilable.sort(key=lambda d: d["fidelity"])
        fids = [d["fidelity"] for d in reconcilable]
        return {
            "semantics_total": len(rows),
            "reconcilable": len(reconcilable),
            "unreconcilable": unreconcilable,
            "mean_fidelity": round(sum(fids) / len(fids), 3) if fids else None,
            "low_fidelity_count": sum(1 for f in fids if f < FIDELITY_LOW),
            "threshold": FIDELITY_LOW,
            "lowest": reconcilable[:5],
            "note": ("unreconcilable = no live source episodes (pruned to cold "
                     "or never recorded); provenance links are severed on prune, "
                     "so drift cannot be measured for those"),
        }

    def analyze_persistence(self) -> dict:
        """Layer 4: forgetting preview, hub classification, core flags, audit."""
        from config import PersistenceConfig
        from persistence import (audit_unchecked_events, classify_hubs,
                                 compute_scores, evaluate_prune,
                                 flag_redundant_cores, innovation_distribution)
        cfg = self._persistence_config or PersistenceConfig()
        compute_scores(self._storage, cfg)
        return {
            "enabled": bool(getattr(cfg, "enabled", False)),
            "forgetting_preview": evaluate_prune(self._storage, cfg),
            "hubs": classify_hubs(self._storage, cfg),
            "flagged_cores": flag_redundant_cores(self._storage, cfg),
            "conjunct_audit": audit_unchecked_events(self._storage, cfg),
            "innovation": innovation_distribution(self._storage),
        }

    def reflect(self, focus=None) -> dict:
        """Dispatch to specific analysis based on focus."""
        if focus == "usage":
            return {"usage": self.analyze_usage()}
        elif focus == "gaps":
            return {"gaps": self.detect_gaps()}
        elif focus == "instincts":
            return {"instincts": self.instinct_health()}
        elif focus == "contradictions":
            return {"contradictions": self.detect_contradictions()}
        elif focus == "vital_signs":
            return {"vital_signs": self.vital_signs()}
        elif focus == "staleness":
            return {"staleness": self.detect_staleness()}
        elif focus == "instinct_contexts":
            return {"instinct_contexts": self.instinct_context_health()}
        elif focus == "classifications":
            return {"classifications": self.analyze_classifications()}
        elif focus == "resonances":
            return {"resonances": self.analyze_resonances()}
        elif focus == "instinct_clusters":
            return {"instinct_clusters": self.analyze_instinct_clusters()}
        elif focus == "coherence":
            return {"coherence": self.analyze_coherence()}
        elif focus == "anchors":
            return {"anchors": self.analyze_anchors()}
        elif focus == "assessments":
            return {"assessments": self.analyze_assessments()}
        elif focus == "fidelity":
            # Not in the no-focus default: a source query per semantic — heavier than other foci.
            return {"fidelity": self.analyze_fidelity()}
        elif focus == "cohesion":
            # Not included in the no-focus default: runs SVD+eigh per semantic — heavier than other foci.
            return {"cohesion": self.analyze_cohesion()}
        elif focus == "persistence":
            # Not in the no-focus default: filtrations per hub — heavier than other foci.
            return {"persistence": self.analyze_persistence()}
        elif focus == "category_evolution":
            # Explicit only: archive/compiler diagnostics stay out of default reflection.
            return {"category_evolution": self.analyze_category_evolution()}
        else:
            return {
                "usage": self.analyze_usage(),
                "gaps": self.detect_gaps(),
                "instincts": self.instinct_health(),
                "contradictions": self.detect_contradictions(),
                "staleness": self.detect_staleness(),
                "instinct_contexts": self.instinct_context_health(),
                "coherence": self.analyze_coherence(),
                "anchors": self.analyze_anchors(),
                "vital_signs": self.vital_signs(include_graph=False),
            }
