"""Instinct cluster engine — community detection, seeding, temperament.

Clusters emerge from two signals:
1. Embedding proximity (cold start — "these instincts are about similar things")
2. Co-firing patterns (matures — "these instincts activate together in practice")

Each cluster has a temperament (conservative ↔ exploratory) derived from
the follow/override ratio of its internal co-firing edges.
"""

from __future__ import annotations

import logging
import uuid
from typing import TYPE_CHECKING

import numpy as np
from scipy.cluster.hierarchy import fclusterdata

if TYPE_CHECKING:
    from storage import Storage

logger = logging.getLogger(__name__)


class ClusterEngine:
    def __init__(
        self,
        storage: Storage,
        embeddings,
        cluster_similarity: float = 0.75,
    ):
        self._storage = storage
        self._embeddings = embeddings
        self._cluster_similarity = cluster_similarity

    def seed_clusters(self) -> list[str]:
        """Cold start: cluster instincts by embedding similarity.

        Clears existing clusters and re-seeds from content embeddings.
        Returns list of created cluster IDs.
        """
        instincts = list(self._storage.get_all_instincts())
        if len(instincts) == 0:
            return []

        actions = [inst["action"] for inst in instincts]
        ids = [inst["id"] for inst in instincts]

        embeddings_list = self._embeddings.embed(actions, prefix="search_document")
        valid_ids = []
        valid_embeddings = []
        failed_ids = []
        for inst_id, emb in zip(ids, embeddings_list):
            if emb is not None:
                valid_ids.append(inst_id)
                valid_embeddings.append(emb)
            else:
                failed_ids.append(inst_id)

        if not valid_ids:
            return []

        if len(valid_ids) == 1:
            labels = [1]
        else:
            embeddings_matrix = np.array(valid_embeddings)
            labels = fclusterdata(
                embeddings_matrix,
                t=1.0 - self._cluster_similarity,
                metric="cosine",
                criterion="distance",
            )

        # Clear existing clusters only after new labels are computed
        for cluster in self._storage.get_all_clusters():
            self._storage.delete_cluster(cluster["id"])

        cluster_ids = self._create_clusters_from_labels(valid_ids, labels, maturity="seeded")

        # Assign instincts whose embeddings failed to singleton clusters
        for iid in failed_ids:
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity="seeded")
            self._storage.add_to_cluster(iid, cid)
            cluster_ids.append(cid)

        return cluster_ids

    def derive_clusters(self) -> list[str]:
        """Re-derive clusters from co-firing graph using community detection.

        Falls back to seed_clusters() if insufficient co-firing data.
        Returns list of cluster IDs.
        """
        edges = self._storage.get_all_co_firing_edges()
        if not edges:
            return self.seed_clusters()

        try:
            import networkx as nx
            from networkx.algorithms.community import louvain_communities
        except ImportError:
            logger.warning("networkx not available, falling back to embedding seed")
            return self.seed_clusters()

        G = nx.Graph()
        all_instincts = self._storage.get_all_instincts()
        known = {inst["id"] for inst in all_instincts}
        for inst in all_instincts:
            G.add_node(inst["id"])

        for edge in edges:
            # Stale edges can reference instincts deleted without cascade;
            # add_edge would resurrect them as nodes and break the members FK.
            if edge["instinct_a"] not in known or edge["instinct_b"] not in known:
                continue
            G.add_edge(
                edge["instinct_a"],
                edge["instinct_b"],
                weight=edge["co_fire_count"],
            )

        connected = {n for n in G.nodes() if G.degree(n) > 0}
        isolated = {n for n in G.nodes() if G.degree(n) == 0}

        if len(connected) < 2:
            return self.seed_clusters()

        connected_subgraph = G.subgraph(connected)
        communities = louvain_communities(connected_subgraph, weight="weight", seed=42)

        # Clear existing clusters
        for cluster in self._storage.get_all_clusters():
            self._storage.delete_cluster(cluster["id"])

        cluster_ids = []
        for community in communities:
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity="confirmed")
            for instinct_id in community:
                self._storage.add_to_cluster(instinct_id, cid)
            cluster_ids.append(cid)

        # Assign isolated instincts to nearest cluster by embedding
        if isolated and cluster_ids:
            self._assign_isolated_to_clusters(list(isolated))

        # Compute temperaments
        for cid in cluster_ids:
            temp = self.compute_temperament(cid)
            self._storage.update_cluster(cid, temperament=temp)

        return cluster_ids

    def compute_temperament(self, cluster_id: str) -> float:
        """Compute cluster temperament from internal co-firing feedback.

        Returns 0.0 (conservative) to 1.0 (exploratory).
        """
        members = self._storage.get_cluster_members(cluster_id)
        if len(members) < 2:
            return 0.5

        member_ids = {m["instinct_id"] for m in members}
        total_follow = 0
        total_override = 0

        for mid in member_ids:
            neighbors = self._storage.get_co_firing_neighbors(mid)
            for n in neighbors:
                if n["instinct_id"] in member_ids:
                    total_follow += n["co_follow_count"]
                    total_override += n["co_override_count"]

        # Each edge counted twice (once from each side), so divide by 2
        total_follow /= 2.0
        total_override /= 2.0

        total = total_follow + total_override
        if total == 0:
            return 0.5

        follow_ratio = total_follow / total
        return 1.0 - follow_ratio

    def assign_new_instinct(self, instinct_id: str) -> str | None:
        """Assign a newly created instinct to the nearest existing cluster.

        If no clusters exist or the instinct is too distant, creates a new cluster.
        """
        clusters = self._storage.get_all_clusters()
        if not clusters:
            # No clusters yet — create first one
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity="seeded")
            self._storage.add_to_cluster(instinct_id, cid)
            return cid

        inst = self._storage.get_instinct(instinct_id)
        if not inst:
            return None

        inst_emb = self._embeddings.embed([inst["action"]], prefix="search_document")[0]
        if inst_emb is None:
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity="seeded")
            self._storage.add_to_cluster(instinct_id, cid)
            return cid
        inst_arr = np.array(inst_emb)

        best_cluster = None
        best_sim = -1.0

        for cluster in clusters:
            centroid = self._compute_cluster_centroid(cluster["id"])
            if centroid is None:
                continue
            sim = float(np.dot(inst_arr, centroid) / (
                np.linalg.norm(inst_arr) * np.linalg.norm(centroid) + 1e-10
            ))
            if sim > best_sim:
                best_sim = sim
                best_cluster = cluster["id"]

        if best_cluster and best_sim >= self._cluster_similarity:
            self._storage.add_to_cluster(instinct_id, best_cluster)
            return best_cluster
        else:
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity="seeded")
            self._storage.add_to_cluster(instinct_id, cid)
            return cid

    def _compute_cluster_centroid(self, cluster_id: str) -> np.ndarray | None:
        members = self._storage.get_cluster_members(cluster_id)
        if not members:
            return None

        embeddings = []
        for m in members:
            inst = self._storage.get_instinct(m["instinct_id"])
            if inst:
                emb = self._embeddings.embed([inst["action"]], prefix="search_document")[0]
                if emb is not None:
                    embeddings.append(emb)

        if not embeddings:
            return None

        return np.mean(embeddings, axis=0)

    def _create_clusters_from_labels(
        self, instinct_ids: list[str], labels, maturity: str
    ) -> list[str]:
        from collections import defaultdict

        groups = defaultdict(list)
        for iid, label in zip(instinct_ids, labels):
            groups[int(label)].append(iid)

        cluster_ids = []
        for members in groups.values():
            cid = str(uuid.uuid4())
            self._storage.create_cluster(cid, maturity=maturity)
            for iid in members:
                self._storage.add_to_cluster(iid, cid)
            cluster_ids.append(cid)

        return cluster_ids

    def _assign_isolated_to_clusters(self, isolated_ids: list[str]) -> None:
        for iid in isolated_ids:
            assigned = self.assign_new_instinct(iid)
            if not assigned:
                cid = str(uuid.uuid4())
                self._storage.create_cluster(cid, maturity="seeded")
                self._storage.add_to_cluster(iid, cid)
