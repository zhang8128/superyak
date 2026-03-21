"""Engram reflection — self-observation and pattern analysis over memory."""
from __future__ import annotations

import json
import logging
from datetime import datetime, timezone, timedelta

logger = logging.getLogger("engram.reflection")


class Reflector:
    def __init__(self, storage, staleness_days=30):
        self._storage = storage
        self._staleness_days = staleness_days

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
        elif focus == "staleness":
            return {"staleness": self.detect_staleness()}
        else:
            return {
                "usage": self.analyze_usage(),
                "gaps": self.detect_gaps(),
                "instincts": self.instinct_health(),
                "contradictions": self.detect_contradictions(),
                "staleness": self.detect_staleness(),
            }
