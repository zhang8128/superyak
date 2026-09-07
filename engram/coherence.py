"""Coherence layer — memory health monitoring.

Vital sign anchors, graph-vs-geometry drift detection, and unchallenged
instinct monitoring. All observation — no auto-resolution.
"""

from __future__ import annotations

import json
import logging
from typing import TYPE_CHECKING

from embeddings import NomicEmbedProvider
from storage import vec0_distance_to_similarity

if TYPE_CHECKING:
    from storage import Storage

logger = logging.getLogger("engram.coherence")


class CoherenceChecker:
    """Measures and reports on memory system health."""

    def __init__(self, storage: Storage):
        self._storage = storage
        self._embeddings: NomicEmbedProvider | None = None

    def _get_embeddings(self) -> NomicEmbedProvider:
        if self._embeddings is None:
            self._embeddings = NomicEmbedProvider()
        return self._embeddings

    def check_identity_anchors(self) -> list[dict]:
        """Check identity anchors: can we still find our core memories?

        For each identity anchor, search for the expected memory ID in
        recall results for the anchor's query. Reports pass/degraded/fail.
        """
        anchors = self._storage.get_active_anchors(anchor_type="identity")
        results = []

        for anchor in anchors:
            expected_id = anchor["expected"]
            query = anchor["content"]
            baseline = anchor["baseline_score"] if anchor["baseline_score"] is not None else 0.5

            ep = self._storage.get_episode(expected_id)
            if ep is None:
                sem = self._storage.get_semantic(expected_id)
                if sem is None:
                    results.append({
                        "anchor_id": anchor["id"],
                        "status": "fail",
                        "reason": "expected memory not found",
                        "score": 0.0,
                        "baseline": baseline,
                    })
                    self._storage.update_anchor_result(
                        anchor["id"],
                        json.dumps({"status": "fail", "reason": "memory_not_found"}),
                    )
                    continue

            # Memory exists — check if it's retrievable via vector search
            try:
                query_emb = self._get_embeddings().embed([query], prefix="search_query")[0]
            except Exception:
                result = {
                    "anchor_id": anchor["id"],
                    "status": "error",
                    "reason": "embedding failed",
                    "score": 0.0,
                    "baseline": baseline,
                }
                results.append(result)
                self._storage.update_anchor_result(
                    anchor["id"],
                    json.dumps({"status": "error", "reason": "embedding_failed"}),
                )
                continue

            found = False
            score = 0.0
            layers_searched = 0
            for layer in ("episode", "semantic", "instinct"):
                try:
                    hits = self._storage.search_vectors(layer, query_emb, k=20)
                    layers_searched += 1
                    for hit_id, distance in hits:
                        if hit_id == expected_id:
                            score = vec0_distance_to_similarity(distance)
                            found = True
                            break
                except Exception:
                    continue
                if found:
                    break

            if layers_searched == 0:
                status = "error"
                reason = "all vector searches failed"
            elif not found:
                status = "fail"
                reason = "memory exists but not in top-20 results"
            elif score < baseline * 0.5:
                status = "degraded"
                reason = f"score {score:.3f} < 50% of baseline {baseline:.3f}"
            else:
                status = "pass"
                reason = None

            result = {
                "anchor_id": anchor["id"],
                "status": status,
                "score": round(score, 4),
                "baseline": baseline,
            }
            if reason:
                result["reason"] = reason
            results.append(result)
            self._storage.update_anchor_result(
                anchor["id"], json.dumps({"status": status, "score": round(score, 4)}),
            )

        return results

    def check_value_anchors(self) -> list[dict]:
        """Check value anchors: do expected concerns still surface?

        V1: the expected field is a JSON list of keywords/phrases.
        Check if a generated response to the scenario would contain them.
        For now, we check against existing semantic content that matches
        the query — if the system's knowledge base contains the expected
        concerns, the anchor passes.
        """
        anchors = self._storage.get_active_anchors(anchor_type="value")
        results = []

        for anchor in anchors:
            try:
                expected_terms = json.loads(anchor["expected"])
            except (json.JSONDecodeError, TypeError):
                expected_terms = [anchor["expected"]]

            # Search semantics for the scenario terms
            found_terms = []
            all_semantics = self._storage.conn.execute(
                "SELECT content FROM semantics WHERE contradicted_by IS NULL"
            ).fetchall()

            if not all_semantics:
                result = {
                    "anchor_id": anchor["id"],
                    "status": "insufficient_data",
                    "reason": "no semantics available for matching",
                    "found_terms": [],
                    "missing_terms": expected_terms,
                    "coverage": 0.0,
                }
                results.append(result)
                self._storage.update_anchor_result(
                    anchor["id"],
                    json.dumps({"status": "insufficient_data", "reason": "no_semantics"}),
                )
                continue

            corpus = " ".join(r[0].lower() for r in all_semantics)

            for term in expected_terms:
                if term.lower() in corpus:
                    found_terms.append(term)

            ratio = len(found_terms) / len(expected_terms) if expected_terms else 0.0

            if ratio >= 0.5:
                status = "pass"
            elif ratio > 0:
                status = "degraded"
            else:
                status = "fail"

            result = {
                "anchor_id": anchor["id"],
                "status": status,
                "found_terms": found_terms,
                "missing_terms": [t for t in expected_terms if t not in found_terms],
                "coverage": round(ratio, 2),
            }
            results.append(result)
            self._storage.update_anchor_result(
                anchor["id"], json.dumps({"status": status, "coverage": round(ratio, 2)}),
            )

        return results

    def scan_drift(
        self,
        session_id: str = "unknown",
        apart_threshold: float = 0.3,
        together_threshold: float = 0.85,
        max_together: int = 20,
        _save: bool = True,
    ) -> dict:
        """Compare graph edges against embedding geometry.

        Returns three lists:
        - drifted_apart: structurally connected, geometrically distant
        - drifted_together: geometrically close, structurally unconnected
        """
        import numpy as np
        from graph import MemoryGraph

        graph = MemoryGraph(self._storage)
        all_nodes = graph._all_node_ids()

        if not all_nodes:
            empty_report = {
                "drifted_apart": [],
                "drifted_together": [],
            }
            if _save:
                self._storage.save_drift_report(
                    session_id=session_id, summary="no nodes",
                    **empty_report, unchallenged=[], anchor_results=[],
                )
            return empty_report

        # --- Drifted apart: edges where embedding similarity is low ---
        drifted_apart = []
        seen_edges: set[tuple[str, str, str]] = set()

        for nid, layer in all_nodes:
            vec_a = self._storage.get_vector(layer, nid)
            if vec_a is None:
                continue
            arr_a = np.array(vec_a, dtype=np.float32)
            norm_a = np.linalg.norm(arr_a)
            if norm_a == 0:
                continue

            edges = graph.neighbors(nid)
            for edge in edges:
                peer = edge.target if edge.source == nid else edge.source
                peer_layer = edge.target_layer if edge.source == nid else edge.source_layer

                key = tuple(sorted([nid, peer])) + (edge.edge_type,)
                if key in seen_edges:
                    continue
                seen_edges.add(key)

                vec_b = self._storage.get_vector(peer_layer, peer)
                if vec_b is None:
                    continue
                arr_b = np.array(vec_b, dtype=np.float32)
                norm_b = np.linalg.norm(arr_b)
                if norm_b == 0:
                    continue

                l2_dist = float(np.linalg.norm(arr_a - arr_b))
                sim = vec0_distance_to_similarity(l2_dist)

                if sim < apart_threshold:
                    drifted_apart.append({
                        "source": edge.source,
                        "source_layer": edge.source_layer,
                        "target": edge.target,
                        "target_layer": edge.target_layer,
                        "edge_type": edge.edge_type,
                        "edge_weight": edge.weight,
                        "embedding_similarity": round(sim, 4),
                    })

        # --- Drifted together: close in embedding space, no structural edge ---
        drifted_together = []
        node_vecs: dict[str, tuple[str, np.ndarray]] = {}
        for nid, layer in all_nodes:
            vec = self._storage.get_vector(layer, nid)
            if vec is not None:
                arr = np.array(vec, dtype=np.float32)
                norm = np.linalg.norm(arr)
                if norm > 0:
                    node_vecs[nid] = (layer, arr / norm)

        # Build structural neighbor set for fast lookup
        structural_neighbors: dict[str, set[str]] = {}
        for nid, layer in all_nodes:
            edges = graph.neighbors(nid)
            structural_neighbors[nid] = {
                e.target if e.source == nid else e.source for e in edges
            }
            structural_neighbors[nid].add(nid)

        # Sample-based: for each node, find closest unconnected via vector search
        seen_together: set[tuple[str, str]] = set()
        for nid, (layer, _) in node_vecs.items():
            raw_vec = self._storage.get_vector(layer, nid)
            if raw_vec is None:
                continue
            try:
                hits = self._storage.search_vectors(layer, raw_vec, k=10)
            except Exception:
                continue
            connected = structural_neighbors.get(nid, {nid})
            for hit_id, distance in hits:
                if hit_id in connected:
                    continue
                sim = vec0_distance_to_similarity(distance)
                if sim >= together_threshold:
                    pair = tuple(sorted([nid, hit_id]))
                    if pair not in seen_together:
                        seen_together.add(pair)
                        drifted_together.append({
                            "node_a": pair[0],
                            "node_b": pair[1],
                            "layer_a": layer,
                            "layer_b": node_vecs.get(hit_id, (layer, None))[0] if hit_id in node_vecs else layer,
                            "similarity": round(sim, 4),
                        })
                        if len(drifted_together) >= max_together:
                            break
            if len(drifted_together) >= max_together:
                break

        report = {
            "drifted_apart": drifted_apart,
            "drifted_together": drifted_together,
        }

        if _save:
            n_apart = len(drifted_apart)
            n_together = len(drifted_together)
            summary = f"{n_apart} drifted apart, {n_together} drifted together"
            self._storage.save_drift_report(
                session_id=session_id,
                drifted_apart=drifted_apart,
                drifted_together=drifted_together,
                unchallenged=[],
                anchor_results=[],
                summary=summary,
            )

        return report

    def check_capability_anchors(self) -> list[dict]:
        """Check capability anchors: is the substrate still sound?

        V1: stores the task and rubric but doesn't run generative evaluation.
        Marks as 'pass' with a note that full evaluation requires an LLM call.
        This is a placeholder for the evaluation harness — the storage and
        reporting infrastructure is real.
        """
        anchors = self._storage.get_active_anchors(anchor_type="capability")
        results = []

        for anchor in anchors:
            result = {
                "anchor_id": anchor["id"],
                "status": "skipped",
                "note": "v1: task stored, full generative evaluation not yet implemented",
                "content": anchor["content"][:100],
            }
            results.append(result)
            self._storage.update_anchor_result(
                anchor["id"],
                json.dumps({"status": "skipped", "note": "v1_stub"}),
            )

        return results

    def detect_unchallenged(
        self,
        min_strength: float = 0.7,
        min_follows: int = 5,
        recent_feedback_limit: int = 20,
    ) -> list[dict]:
        """Find instincts that fire often, always get followed, and never get questioned.

        Criteria per spec:
        - strength >= min_strength
        - followed_count >= min_follows
        - No override (followed=False) in recent context feedback
        """
        instincts = self._storage.get_all_instincts()
        unchallenged = []

        for inst in instincts:
            strength = inst.get("strength", 0.0)
            followed = inst.get("followed_count", 0) or 0

            if strength < min_strength or followed < min_follows:
                continue

            feedback = self._storage.get_instinct_context_feedback(inst["id"])
            recent = feedback[-recent_feedback_limit:] if feedback else []
            has_recent_override = any(not fb["followed"] for fb in recent)

            if not has_recent_override:
                unchallenged.append({
                    "instinct_id": inst["id"],
                    "action": inst.get("action", ""),
                    "notice": inst.get("notice"),
                    "implication": inst.get("implication"),
                    "strength": strength,
                    "followed_count": followed,
                    "fired_count": inst.get("fired_count", 0) or 0,
                    "feedback_count": len(feedback),
                })

        return unchallenged

    def run_full_check(self, session_id: str = "unknown") -> dict:
        """Run all coherence checks. Called during sleep consolidation.

        Order: anchors first (if vitals fail, drift report is untrustworthy),
        then drift scan.
        """
        identity_results = self.check_identity_anchors()
        value_results = self.check_value_anchors()
        capability_results = self.check_capability_anchors()

        all_anchor_results = identity_results + value_results + capability_results
        anchor_failures = [r for r in all_anchor_results if r["status"] == "fail"]
        anchor_degraded = [r for r in all_anchor_results if r["status"] == "degraded"]
        anchor_errors = [r for r in all_anchor_results if r["status"] in ("error", "insufficient_data")]

        drift = self.scan_drift(session_id=session_id, _save=False)
        unchallenged = self.detect_unchallenged()
        drift["unchallenged"] = unchallenged

        parts = []
        if anchor_errors:
            parts.append(f"{len(anchor_errors)} anchor(s) could not be checked")
        if anchor_failures:
            parts.append(f"{len(anchor_failures)} anchor(s) FAILED")
        if anchor_degraded:
            parts.append(f"{len(anchor_degraded)} anchor(s) degraded")
        n_apart = len(drift["drifted_apart"])
        n_together = len(drift["drifted_together"])
        n_unchall = len(unchallenged)
        if n_apart:
            parts.append(f"{n_apart} drifted apart")
        if n_together:
            parts.append(f"{n_together} drifted together")
        if n_unchall:
            parts.append(f"{n_unchall} unchallenged instinct(s)")

        if not all_anchor_results and not drift["drifted_apart"] and not drift["drifted_together"]:
            summary = "no data to check"
        else:
            summary = "; ".join(parts) if parts else "coherence stable"

        self._storage.save_drift_report(
            session_id=session_id,
            drifted_apart=drift["drifted_apart"],
            drifted_together=drift["drifted_together"],
            unchallenged=unchallenged,
            anchor_results=all_anchor_results,
            summary=summary,
        )

        return {
            "anchor_results": all_anchor_results,
            "drift": drift,
            "summary": summary,
        }
