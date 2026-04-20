"""Engram compression — clustering, centroid selection, LLM dedup, instinct creation."""

from __future__ import annotations

import json as _json
import logging
import random
import uuid
from typing import TYPE_CHECKING

import numpy as np
from scipy.cluster.hierarchy import fclusterdata

from clusters import ClusterEngine
from storage import vec0_distance_to_similarity

if TYPE_CHECKING:
    from config import CompressionConfig
    from dedup import Deduplicator
    from storage import Storage

logger = logging.getLogger("engram.compression")

_KNOWN_NAMES = {"andy", "kairos", "vaughn", "emma", "koan", "vin", "kelsier"}


def classify_episode_kind(
    episode: dict,
    model: str | None = None,
    prompt_path: str | None = None,
) -> list[str]:
    """Classify an episode into one or more kinds based on metadata and content.

    If model is provided, attempts model-assisted classification first and falls
    back to the heuristic if the model is unavailable or returns no valid kinds.

    Returns sorted list of kinds. An episode can belong to multiple types.
    """
    if model:
        model_kinds = classify_episode_kind_with_model(
            episode,
            model=model,
            prompt_path=prompt_path or "prompts/classify.txt",
        )
        if model_kinds:
            return model_kinds

    kinds: set[str] = set()
    content = (episode.get("content") or "").lower()
    source = (episode.get("source") or "").lower()
    context_raw = episode.get("context")

    # Parse context JSON if present
    context_str = ""
    ctx = {}
    if context_raw:
        if isinstance(context_raw, str):
            try:
                ctx = _json.loads(context_raw)
                context_str = _json.dumps(ctx).lower()
            except (ValueError, TypeError):
                context_str = context_raw.lower()
        elif isinstance(context_raw, dict):
            ctx = context_raw
            context_str = _json.dumps(context_raw).lower()

    # Challenge episodes are exclusively observation — prevents them from
    # being absorbed into "factual" clusters where they can't form instincts
    if ctx.get("type") == "instinct_challenge":
        return ["observation"]

    # Reading: source tag or passage/chapter references
    if source == "reading" or "passage" in context_str or "chapter" in context_str:
        kinds.add("reading")

    # Design: built/architecture/design/commit references
    design_signals = ("design", "architecture", "built", "commit", "implement", "branch")
    if any(s in context_str for s in design_signals) or any(s in content[:100] for s in ("built ", "session 20")):
        kinds.add("design")

    # Observation: self-observation, pattern-noticed, instinct challenges
    obs_signals = ("self-observation", "observation", "pattern", "noticed",
                   "instinct_challenge", "instinct_retirement")
    if any(s in context_str for s in obs_signals) or "pattern noticed" in content:
        kinds.add("observation")

    # Relational: mentions known people
    content_words = set(content.split())
    if content_words & _KNOWN_NAMES:
        kinds.add("relational")

    # Factual: session summaries, build logs
    if content.startswith(("session 20", "completed ", "implemented ", "built ")):
        kinds.add("factual")

    # Reflection: recursive, philosophical
    refl_signals = ("reflection", "recursive", "philosophical", "self-reflection")
    if any(s in context_str for s in refl_signals) or "recursive" in content:
        kinds.add("reflection")

    # Default: if nothing matched, it's factual
    if not kinds:
        kinds.add("factual")

    return sorted(kinds)


def classify_episode_kind_with_model(
    episode: dict,
    model: str = "gemma4:31b",
    prompt_path: str = "prompts/classify.txt",
) -> list[str] | None:
    """Classify episode using a local LLM. Returns None if model unavailable."""
    from pathlib import Path
    import os

    template_file = Path(prompt_path)
    if not template_file.exists():
        engram_home = Path(os.environ.get("ENGRAM_HOME", Path(__file__).parent))
        template_file = engram_home / prompt_path
    if not template_file.exists():
        return None

    template = template_file.read_text()
    content = episode.get("content", "")
    context = episode.get("context", "")
    prompt = template.replace("{content}", content).replace("{context}", str(context))

    try:
        import requests
        ollama_url = os.environ.get("ENGRAM_OLLAMA_URL", "http://localhost:11434")
        resp = requests.post(
            f"{ollama_url}/api/generate",
            json={"model": model, "prompt": prompt, "stream": False},
            timeout=10,
        )
        if resp.status_code != 200:
            return None
        raw = resp.json().get("response", "").strip().lower()
        valid_kinds = {"reading", "design", "observation", "disposition", "relational", "factual", "reflection"}
        kinds = [k.strip() for k in raw.split(",") if k.strip() in valid_kinds]
        return kinds if kinds else None
    except Exception:
        logger.debug("Model classification unavailable", exc_info=True)
        return None


# Episode kind → semantic kind mapping
_EPISODE_TO_SEMANTIC_KIND = {
    "reading": "preference",
    "observation": "disposition",
    "reflection": "disposition",
    "relational": "relationship",
    "design": "fact",
    "factual": "fact",
}


def derive_semantic_kind(cluster_kind: str) -> str:
    """Map a cluster's episode kind to the appropriate semantic kind."""
    return _EPISODE_TO_SEMANTIC_KIND.get(cluster_kind, "fact")


class Compressor:
    """Compression pipeline: episodes → semantics → instincts.

    Two paths:
    - Manual: cluster_episodes() → (AI writes summaries) → commit()
    - Auto: auto_compress() — centroid selection, no AI needed
    """

    def __init__(
        self,
        storage: Storage,
        embedding_provider,
        config: CompressionConfig | None = None,
        deduplicator: Deduplicator | None = None,
        knowledge_graph=None,
        classification_config=None,
    ):
        self._storage = storage
        self._embeddings = embedding_provider
        self._config = config
        self._dedup = deduplicator
        self._knowledge_graph = knowledge_graph
        self._classification_config = classification_config
        self._pending: dict[str, dict] = {}  # compress_id -> cluster state

    @property
    def _cluster_similarity(self) -> float:
        return self._config.cluster_similarity if self._config else 0.75

    @property
    def _reinforce_threshold(self) -> float:
        return self._config.reinforce_threshold if self._config else 0.85

    @property
    def _instinct_confidence(self) -> float:
        return self._config.instinct_confidence if self._config else 0.75

    def cluster_episodes(self, scope: str = "recent") -> dict:
        """Phase 1: cluster uncompressed episodes, check for semantic matches.

        Returns: {clusters: [{episodes, centroid, match, action}], compress_id}
        """
        if scope == "full":
            self._reset_all()
        elif scope == "refine":
            return self._refine_clusters()

        episodes = self._storage.get_uncompressed_episodes()
        if not episodes:
            return {"clusters": [], "compress_id": None}

        # Step 1: Classify episodes by kind — an episode can appear in multiple type pools
        typed_groups: dict[str, list[dict]] = {}
        for ep in episodes:
            model = self._classification_config.model if self._classification_config else None
            prompt_path = self._classification_config.prompt_path if self._classification_config else None
            kinds = classify_episode_kind(ep, model=model, prompt_path=prompt_path)
            for kind in kinds:
                typed_groups.setdefault(kind, []).append(ep)

        # Step 2: Cluster within each type independently
        all_clusters = []

        for kind, kind_episodes in typed_groups.items():
            if not kind_episodes:
                continue

            texts = [ep["content"] for ep in kind_episodes]
            embeddings = self._embeddings.embed(texts, prefix="clustering")

            valid = [(ep, emb) for ep, emb in zip(kind_episodes, embeddings) if emb is not None]
            if not valid:
                continue

            valid_episodes, valid_embeddings = zip(*valid)
            valid_episodes = list(valid_episodes)
            valid_embeddings = list(valid_embeddings)
            embeddings_matrix = np.array(valid_embeddings)

            if len(embeddings_matrix) == 1:
                cluster_labels = [1]
            else:
                cluster_labels = fclusterdata(
                    embeddings_matrix,
                    t=1.0 - self._cluster_similarity,
                    metric="cosine",
                    criterion="distance",
                )

            cluster_groups: dict[int, list[tuple[dict, list[float]]]] = {}
            for label, ep, emb in zip(cluster_labels, valid_episodes, valid_embeddings):
                label_int = int(label)
                if label_int not in cluster_groups:
                    cluster_groups[label_int] = []
                cluster_groups[label_int].append((ep, emb))

            for label, members in cluster_groups.items():
                eps = [m[0] for m in members]
                embs = [m[1] for m in members]
                centroid = np.mean(embs, axis=0).tolist()
                action, match, near_miss = self._find_semantic_match(centroid)

                all_clusters.append({
                    "episodes": eps,
                    "centroid": centroid,
                    "match": match,
                    "action": action,
                    "near_miss": near_miss,
                    "kind": kind,
                })

        compress_id = str(uuid.uuid4())
        self._pending[compress_id] = {"clusters": all_clusters}
        return {"clusters": all_clusters, "compress_id": compress_id}

    def commit(self, compress_id: str, summaries: list[dict]) -> dict:
        """Phase 2: store semantics from AI-provided summaries.

        Each summary should have: {content, kind, action, semantic_id (if reinforce)}

        Returns: {episodes_processed, semantics_created, semantics_reinforced, instincts_created}
        """
        state = self._pending.pop(compress_id, None)
        if state is None:
            raise ValueError(f"Unknown compress_id: {compress_id}")

        clusters = state["clusters"]
        episodes_processed = 0
        semantics_created = 0
        semantics_reinforced = 0

        for i, cluster in enumerate(clusters):
            if i >= len(summaries):
                break

            summary = summaries[i]
            all_episode_ids = [ep["id"] for ep in cluster["episodes"]]
            centroid = cluster["centroid"]
            action = summary.get("action", cluster["action"])

            if action == "reinforce":
                semantic_id = summary.get("semantic_id") or (cluster["match"] or {}).get("id")
                if semantic_id:
                    self._storage.reinforce_semantic(semantic_id, all_episode_ids)
                    semantics_reinforced += 1
                else:
                    logger.warning("Reinforce requested but no semantic_id found, falling back to new")
                    action = "new"
            if action != "reinforce":
                new_id = str(uuid.uuid4())
                semantic_content = summary.get("content", "")

                # Only link episodes actually similar to the semantic content.
                # Prevents mega-semantics where loose clusters create catch-all
                # source links (e.g. 128 unrelated episodes linked to one semantic).
                source_ids = self._filter_relevant_sources(
                    cluster["episodes"], semantic_content,
                )
                if not source_ids:
                    source_ids = all_episode_ids[:3]  # fallback: keep a few

                n_sources = len(source_ids)
                confidence = min(0.9, 0.5 + 0.1 * (n_sources - 1))
                semantic_embedding = self._embeddings.embed(
                    [semantic_content], prefix="search_document"
                )[0]
                self._storage.add_semantic(
                    id=new_id,
                    content=semantic_content,
                    kind=summary.get("kind", "fact"),
                    confidence=confidence,
                    embedding=semantic_embedding if semantic_embedding is not None else centroid,
                    source_episode_ids=source_ids,
                    auto_generated=bool(summary.get("auto_generated", False)),
                )
                semantics_created += 1
                # Only auto-promote the centroid-nearest episode as core.
                # Promoting all source episodes caused 74% core bloat,
                # defeating decay. The centroid representative preserves
                # evidence alongside the conclusion without exempting everything.
                if centroid is not None and source_ids:
                    centroid_nearest = self._find_centroid_nearest_id(
                        cluster["episodes"], centroid, source_ids,
                    )
                    if centroid_nearest:
                        self._storage.mark_core(centroid_nearest)

                # Disposition semantics get resonance links to source episodes
                # so specific correction moments surface alongside the pattern
                if summary.get("kind") == "disposition":
                    for src_id in source_ids:
                        self._storage.add_resonance(
                            new_id, "semantic",
                            src_id, "episode",
                            similarity=0.0,  # provenance-based, not similarity-based
                            weight=max(0.1, min(0.9, random.gauss(0.6, 0.1))),
                        )

                near_miss = cluster.get("near_miss")
                if near_miss:
                    weight = max(0.1, min(0.9, random.gauss(0.5, 0.15)))
                    self._storage.add_resonance(
                        new_id, "semantic",
                        near_miss["id"], "semantic",
                        similarity=near_miss["similarity"],
                        weight=weight,
                    )

                # Feed episode cluster to knowledge graph for entity extraction
                if self._knowledge_graph is not None:
                    try:
                        self._knowledge_graph.feed(
                            cluster["episodes"],
                            semantic_content=semantic_content,
                        )
                    except Exception:
                        logger.warning("Knowledge graph feed failed", exc_info=True)

            self._storage.mark_episodes_compressed(all_episode_ids)
            episodes_processed += len(all_episode_ids)

        # Multi-link: connect episodes to all matching semantics
        # Only include clusters that were actually processed (had summaries)
        processed_count = min(len(clusters), len(summaries))
        all_processed_episodes = []
        cluster_semantic_ids = []
        for i in range(processed_count):
            all_processed_episodes.extend(clusters[i]["episodes"])
            sid = summaries[i].get("semantic_id")
            if sid:
                cluster_semantic_ids.append(sid)

        multi_links = self._multi_link_episodes(all_processed_episodes, cluster_semantic_ids)

        singletons_created = self._promote_singletons()

        # Log compression event
        self._storage.add_log_entry(
            id=str(uuid.uuid4()),
            event_type="compression",
            layer="semantic",
            target_ids=[],
            context={
                "compress_id": compress_id,
                "episodes_processed": episodes_processed,
                "semantics_created": semantics_created,
                "semantics_reinforced": semantics_reinforced,
                "multi_links": multi_links,
                "singletons_created": singletons_created,
            },
        )

        instincts_created = self._check_instinct_creation()

        # Re-derive clusters if we have co-firing data
        edges = list(self._storage.get_all_co_firing_edges())
        if edges:
            cluster_engine = ClusterEngine(self._storage, self._embeddings)
            cluster_engine.derive_clusters()
            logger.info("Clusters re-derived from co-firing graph")
        elif list(self._storage.get_all_instincts()):
            cluster_engine = ClusterEngine(self._storage, self._embeddings)
            cluster_engine.seed_clusters()
            logger.info("Clusters seeded from embedding proximity")

        return {
            "episodes_processed": episodes_processed,
            "semantics_created": semantics_created,
            "semantics_reinforced": semantics_reinforced,
            "instincts_created": instincts_created,
            "multi_links": multi_links,
            "singletons_created": singletons_created,
        }

    def auto_compress(self) -> dict:
        """Automatic compression using centroid selection (no AI needed).

        For each cluster, picks the most representative episode(s) instead
        of concatenating everything. Uses MMR for clusters with 4+ episodes
        to select diverse representatives.
        """
        result = self.cluster_episodes()
        clusters = result.get("clusters", [])
        compress_id = result.get("compress_id")

        if not clusters or compress_id is None:
            return {
                "episodes_processed": 0,
                "semantics_created": 0,
                "semantics_reinforced": 0,
                "instincts_created": 0,
            }

        summaries = []
        for cluster in clusters:
            episodes = cluster["episodes"]
            centroid = cluster["centroid"]

            if len(episodes) == 1:
                content = episodes[0]["content"]
            elif len(episodes) < 4:
                # Small cluster: pick centroid-nearest episode
                content = self._select_centroid_nearest(episodes, centroid)
            else:
                # Larger cluster: MMR for diverse representatives
                representatives = self._select_mmr(episodes, centroid, k=3)
                content = " --- ".join(representatives)

            summaries.append({
                "content": content,
                "kind": derive_semantic_kind(cluster["kind"]),
                "action": cluster["action"],
                "auto_generated": True,
                "semantic_id": (cluster["match"] or {}).get("id") if cluster["match"] else None,
            })

        return self.commit(compress_id, summaries)

    def _find_centroid_nearest_id(
        self, episodes: list[dict], centroid: list[float], candidate_ids: list[str],
    ) -> str | None:
        """Find the episode ID closest to centroid, restricted to candidate_ids."""
        candidates = [ep for ep in episodes if ep["id"] in set(candidate_ids)]
        if not candidates:
            return None
        texts = [ep["content"] for ep in candidates]
        embeddings = self._embeddings.embed(texts, prefix="clustering")
        centroid_arr = np.array(centroid)
        best_id = None
        best_sim = -1.0
        for ep, emb in zip(candidates, embeddings):
            if emb is None:
                continue
            emb_arr = np.array(emb)
            dot = np.dot(centroid_arr, emb_arr)
            norm = np.linalg.norm(centroid_arr) * np.linalg.norm(emb_arr)
            sim = dot / norm if norm > 0 else 0.0
            if sim > best_sim:
                best_sim = sim
                best_id = ep["id"]
        return best_id

    def _select_centroid_nearest(self, episodes: list[dict], centroid: list[float]) -> str:
        """Select the episode closest to the cluster centroid."""
        texts = [ep["content"] for ep in episodes]
        embeddings = self._embeddings.embed(texts, prefix="clustering")

        centroid_arr = np.array(centroid)
        best_idx = 0
        best_sim = -1.0

        for i, emb in enumerate(embeddings):
            if emb is None:
                continue
            emb_arr = np.array(emb)
            # Cosine similarity
            dot = np.dot(centroid_arr, emb_arr)
            norm = np.linalg.norm(centroid_arr) * np.linalg.norm(emb_arr)
            sim = dot / norm if norm > 0 else 0.0
            if sim > best_sim:
                best_sim = sim
                best_idx = i

        return texts[best_idx]

    def _select_mmr(
        self, episodes: list[dict], centroid: list[float], k: int = 3, lambda_: float = 0.7,
    ) -> list[str]:
        """Maximal Marginal Relevance: select k diverse, relevant episodes.

        Iteratively picks episodes that are both relevant (close to centroid)
        and novel (dissimilar to already-selected episodes).
        """
        texts = [ep["content"] for ep in episodes]
        embeddings = self._embeddings.embed(texts, prefix="clustering")

        # Filter valid embeddings
        valid = [(i, np.array(emb)) for i, emb in enumerate(embeddings) if emb is not None]
        if not valid:
            return texts[:k]

        centroid_arr = np.array(centroid)
        selected: list[int] = []
        remaining = list(range(len(valid)))

        for _ in range(min(k, len(valid))):
            best_idx = -1
            best_score = -float("inf")

            for r in remaining:
                orig_idx, emb = valid[r]

                # Relevance: cosine similarity to centroid
                dot_c = np.dot(centroid_arr, emb)
                norm_c = np.linalg.norm(centroid_arr) * np.linalg.norm(emb)
                relevance = dot_c / norm_c if norm_c > 0 else 0.0

                # Redundancy: max cosine similarity to any already-selected
                if selected:
                    redundancy = max(
                        np.dot(emb, valid[s][1]) / (np.linalg.norm(emb) * np.linalg.norm(valid[s][1]) + 1e-10)
                        for s in selected
                    )
                else:
                    redundancy = 0.0

                score = lambda_ * relevance - (1 - lambda_) * redundancy
                if score > best_score:
                    best_score = score
                    best_idx = r

            if best_idx >= 0:
                selected.append(best_idx)
                remaining.remove(best_idx)

        return [texts[valid[s][0]] for s in selected]

    def _generate_perceptual_framing(self, content: str, kind: str) -> tuple[str, str]:
        """Generate notice/implication fields from semantic content.

        Returns (notice, implication) where:
        - notice: brief context cue — when does this apply? (< 60 chars ideal)
        - implication: what follows — one sentence max (< 120 chars ideal)

        The notice is what appears in mid-conversation nudges. It must be
        short enough to glance at and decide whether to pull the thread.
        The implication is revealed if you pull.
        """
        if not content:
            return (f"when: {kind}", content)

        # Extract the first sentence as the core insight
        first_sentence = content.split(". ")[0].strip().rstrip(".")

        lower = content.lower()

        # Try to find a natural "when" boundary
        if " when " in lower:
            idx = lower.index(" when ")
            after = content[idx + len(" when "):].split(". ")[0].strip()
            before = content[:idx].split(". ")[0].strip()
            notice = f"when {after[:55]}"
            implication = before[:120]
        elif lower.startswith(("always ", "never ", "prefer ", "avoid ")):
            # Action-oriented: the whole thing is the implication
            word_end = content.find(" ")
            if word_end < 0:
                word_end = len(content)
            notice = f"when relevant: {first_sentence[:45]}"
            implication = first_sentence[:120]
        elif kind == "constraint":
            # Constraints are imperatives — the notice is the domain,
            # the implication is the rule itself.
            # Extract domain from key nouns (crude but better than "when use X")
            words = first_sentence.split()
            # Skip leading verbs to find the domain
            skip = {"use", "always", "never", "ensure", "make", "keep", "avoid",
                    "prefer", "do", "don't", "check", "run", "set", "add"}
            domain_words = [w for w in words[:8] if w.lower().rstrip(",:;") not in skip]
            domain = " ".join(domain_words[:4]).rstrip(",:;") if domain_words else kind
            notice = f"when {domain[:55].lower()}"
            implication = first_sentence[:120]
        else:
            notice = f"when {first_sentence[:55].lower()}"
            implication = first_sentence[:120]

        return (notice, implication)

    def _check_instinct_creation(self) -> int:
        """Check for semantics qualifying for instinct creation.

        Uses LLM dedup (if available) to prevent duplicate instincts that
        express the same preference in different words.
        """
        created = 0

        for kind in ("preference", "constraint", "disposition"):
            semantics = self._storage.get_active_semantics(kind=kind)
            for sem in semantics:
                if sem["confidence"] < self._instinct_confidence:
                    continue

                # Check if instinct already exists for this semantic
                row = self._storage.conn.execute(
                    "SELECT 1 FROM instinct_sources WHERE semantic_id = ? LIMIT 1",
                    (sem["id"],),
                ).fetchone()
                if row is not None:
                    continue

                # Dedup: check if an existing instinct says the same thing
                if self._instinct_already_exists(sem["content"], kind=kind):
                    logger.info("Skipping duplicate instinct for semantic %s", sem["id"])
                    continue

                instinct_id = str(uuid.uuid4())
                instinct_embedding = self._embeddings.embed(
                    [sem["content"]], prefix="search_document"
                )[0]

                notice, implication = self._generate_perceptual_framing(sem["content"], kind)

                # Context vector: embed the notice (describes when instinct applies)
                context_embedding = self._embeddings.embed([notice], prefix="search_document")[0]

                # Cap action length — instincts are dispositions, not essays.
                # The full semantic content is still available via source links.
                action = sem["content"]
                if len(action) > 200:
                    # Take first two sentences max
                    sentences = action.split(". ")
                    action = ". ".join(sentences[:2]).rstrip(".") + "."

                self._storage.add_instinct(
                    id=instinct_id,
                    trigger=kind,
                    action=action,
                    source_semantic_ids=[sem["id"]],
                    strength=0.5,
                    embedding=instinct_embedding,
                    notice=notice,
                    implication=implication,
                    context=kind,
                )

                # Store context vector separately
                if context_embedding is not None:
                    self._storage.add_instinct_context_vector(instinct_id, context_embedding)

                # Assign to nearest cluster (or create singleton)
                cluster_engine = ClusterEngine(self._storage, self._embeddings)
                cluster_engine.assign_new_instinct(instinct_id)

                created += 1
                logger.info("Instinct created: %s from semantic %s", instinct_id, sem["id"])

        return created

    def _instinct_already_exists(self, content: str, kind: str = "preference") -> bool:
        """Check if an existing instinct expresses the same thing.

        Two-tier check:
        1. LLM dedup (if available) — detects pragmatic equivalence
        2. Embedding similarity fallback — catches obvious duplicates

        Considers both the action content and the perceptual notice to avoid
        false dedup of instincts with different contexts.
        """
        existing = self._storage.get_all_instincts()
        if not existing:
            return False

        # Generate notice for the new content to compare
        new_notice, _new_implication = self._generate_perceptual_framing(content, kind)

        # Tier 1: LLM-based pragmatic equivalence
        if self._dedup is not None and self._dedup.is_available():
            for inst in existing:
                action = inst.get("action", "")
                # Check if actions are equivalent
                if self._dedup.is_equivalent(content, action):
                    # If the existing instinct has a notice, also check notice similarity
                    # (same action but different context = different instinct)
                    existing_notice = inst.get("notice")
                    if existing_notice and new_notice:
                        # Both have notices — check if they're also equivalent
                        if self._dedup.is_equivalent(new_notice, existing_notice):
                            logger.info("LLM dedup: '%s' ≡ '%s'", content[:50], action[:50])
                            return True
                        # Same action, different notice = NOT a duplicate
                        continue
                    # Legacy instinct without notice — action match is enough
                    logger.info("LLM dedup: '%s' ≡ '%s'", content[:50], action[:50])
                    return True
            return False

        # Tier 2: Embedding similarity fallback
        try:
            embedding = self._embeddings.embed([content], prefix="clustering")[0]
            if embedding is None:
                return False
            actions = [inst.get("action", "") for inst in existing]
            action_embeddings = self._embeddings.embed(actions, prefix="clustering")
            content_arr = np.array(embedding)
            for action_emb in action_embeddings:
                if action_emb is None:
                    continue
                action_arr = np.array(action_emb)
                dot = np.dot(content_arr, action_arr)
                norm = np.linalg.norm(content_arr) * np.linalg.norm(action_arr)
                if norm > 0 and dot / norm >= self._reinforce_threshold:
                    return True
        except Exception:
            logger.debug("Instinct dedup check failed", exc_info=True)
        return False

    def _promote_singletons(self) -> int:
        """Promote core episodes with no semantic links to singleton semantics.

        Candidates: core episodes not in semantic_sources.
        Each gets its own semantic at confidence 0.5.
        Returns number of singletons created.
        """
        rows = self._storage.conn.execute(
            """
            SELECT e.id, e.content, e.context, e.source FROM episodes e
            WHERE e.core = 1
            AND e.id NOT IN (SELECT episode_id FROM semantic_sources)
            """
        ).fetchall()

        if not rows:
            return 0

        created = 0
        for row in rows:
            ep_id = row[0]
            content = row[1]
            if not content or len(content.strip()) < 10:
                continue

            sem_id = str(uuid.uuid4())
            embedding = self._embeddings.embed([content], prefix="search_document")[0]
            if embedding is None:
                continue

            # Classify kind from episode data
            ep_dict = {"content": content, "source": row[3], "context": row[2]}
            kinds = classify_episode_kind(ep_dict)
            kind_to_semantic = {
                "reading": "preference",
                "design": "fact",
                "observation": "disposition",
                "relational": "fact",
                "factual": "fact",
                "reflection": "disposition",
            }
            semantic_kind = kind_to_semantic.get(kinds[0], "fact")

            self._storage.add_semantic(
                id=sem_id,
                content=content,
                kind=semantic_kind,
                confidence=0.5,
                embedding=embedding,
                source_episode_ids=[ep_id],
                auto_generated=True,
            )
            # Update the source link with similarity = 1.0 (exact match)
            self._storage.conn.execute(
                "UPDATE semantic_sources SET similarity = 1.0 WHERE semantic_id = ? AND episode_id = ?",
                (sem_id, ep_id),
            )
            self._storage.conn.commit()
            created += 1

        return created

    def _multi_link_episodes(
        self,
        episodes: list[dict],
        exclude_semantic_ids: list[str],
    ) -> int:
        """Link episodes to all matching semantics above threshold.

        Compares each episode's embedding against all semantic embeddings.
        Adds source links with similarity scores for matches above reinforce_threshold.
        Skips semantic IDs in exclude_semantic_ids (already linked by the cluster step).

        Returns number of new links created.
        """
        all_semantics = self._storage.get_active_semantics(limit=500)
        if not all_semantics:
            return 0

        sem_ids = [s["id"] for s in all_semantics]
        sem_texts = [s["content"] for s in all_semantics]
        sem_embeddings = self._embeddings.embed(sem_texts, prefix="clustering")

        sem_emb_map: dict[str, np.ndarray] = {}
        for sid, emb in zip(sem_ids, sem_embeddings):
            if emb is not None:
                sem_emb_map[sid] = np.array(emb)

        ep_texts = [ep["content"] for ep in episodes]
        ep_embeddings = self._embeddings.embed(ep_texts, prefix="clustering")

        links_created = 0
        for ep, ep_emb in zip(episodes, ep_embeddings):
            if ep_emb is None:
                continue
            ep_arr = np.array(ep_emb)
            ep_norm = np.linalg.norm(ep_arr)
            if ep_norm == 0:
                continue

            for sid, sem_arr in sem_emb_map.items():
                if sid in exclude_semantic_ids:
                    continue
                sem_norm = np.linalg.norm(sem_arr)
                if sem_norm == 0:
                    continue
                sim = float(np.dot(ep_arr, sem_arr) / (ep_norm * sem_norm))
                if sim >= self._reinforce_threshold:
                    existing = self._storage.conn.execute(
                        "SELECT 1 FROM semantic_sources WHERE semantic_id = ? AND episode_id = ?",
                        (sid, ep["id"]),
                    ).fetchone()
                    if existing is None:
                        self._storage.conn.execute(
                            "INSERT INTO semantic_sources (semantic_id, episode_id, similarity) VALUES (?, ?, ?)",
                            (sid, ep["id"], sim),
                        )
                        links_created += 1

        if links_created:
            self._storage.conn.commit()
        return links_created

    def _find_semantic_match(self, centroid: list[float]) -> tuple[str, dict | None, dict | None]:
        """Search for existing semantic matching this centroid.

        Returns (action, match_info, near_miss) where:
        - action is 'reinforce' or 'new'
        - match_info is populated when action == 'reinforce'
        - near_miss is populated when similarity is in [0.50, reinforce_threshold)
        """
        try:
            results = self._storage.search_vectors("semantic", centroid, k=1)
            if results:
                sem_id, distance = results[0]
                similarity = vec0_distance_to_similarity(distance)
                if similarity >= self._reinforce_threshold:
                    sem = self._storage.get_semantic(sem_id)
                    if sem:
                        return "reinforce", {"id": sem_id, "similarity": similarity, "content": sem["content"]}, None
                elif similarity >= 0.50:
                    return "new", None, {"id": sem_id, "similarity": similarity}
        except Exception:
            logger.debug("Semantic vector search failed (table may be empty)")

        return "new", None, None

    def _filter_relevant_sources(
        self, episodes: list[dict], semantic_content: str,
    ) -> list[str]:
        """Return IDs of episodes actually similar to the semantic content.

        Prevents mega-semantics: only episodes above the reinforce threshold
        get linked as sources. The rest are still marked compressed but don't
        pollute the source chain.
        """
        if not semantic_content or not episodes:
            return []

        sem_emb = self._embeddings.embed([semantic_content], prefix="clustering")
        if not sem_emb or sem_emb[0] is None:
            return []

        sem_arr = np.array(sem_emb[0])
        texts = [ep["content"] for ep in episodes]
        ep_embs = self._embeddings.embed(texts, prefix="clustering")

        relevant = []
        for ep, emb in zip(episodes, ep_embs):
            if emb is None:
                continue
            emb_arr = np.array(emb)
            norm = np.linalg.norm(sem_arr) * np.linalg.norm(emb_arr)
            if norm > 0:
                sim = np.dot(sem_arr, emb_arr) / norm
                if sim >= self._reinforce_threshold:
                    relevant.append(ep["id"])

        return relevant

    def _reset_all(self) -> None:
        """Reset all episodes to uncompressed and delete all semantics and instincts."""
        self._storage.conn.execute("UPDATE episodes SET compressed=0")
        self._storage.conn.execute("DELETE FROM instinct_context_vectors")
        self._storage.conn.execute("DELETE FROM instinct_context_feedback")
        self._storage.conn.execute("DELETE FROM instinct_sources")
        self._storage.conn.execute("DELETE FROM instincts")
        self._storage.conn.execute("DELETE FROM semantic_sources")
        self._storage.conn.execute(
            "DELETE FROM semantic_vectors WHERE id IN (SELECT id FROM semantics)"
        )
        self._storage.conn.execute("DELETE FROM semantics")
        self._storage.conn.execute("DELETE FROM resonances")
        self._storage.conn.commit()

    def _refine_clusters(self) -> dict:
        """Find auto-generated semantics (containing ' --- ') for re-summarization."""
        rows = self._storage.conn.execute(
            "SELECT * FROM semantics WHERE content LIKE '%--- %' AND contradicted_by IS NULL"
        ).fetchall()

        if not rows:
            return {"clusters": [], "compress_id": None}

        clusters = []
        for row in rows:
            sem = dict(row)
            source_rows = self._storage.conn.execute(
                "SELECT episode_id FROM semantic_sources WHERE semantic_id = ?",
                (sem["id"],),
            ).fetchall()
            episode_ids = [r[0] for r in source_rows]

            episodes = []
            for eid in episode_ids:
                ep_row = self._storage.conn.execute(
                    "SELECT * FROM episodes WHERE id = ?", (eid,)
                ).fetchone()
                if ep_row:
                    episodes.append(dict(ep_row))

            if episodes:
                clusters.append({
                    "episodes": episodes,
                    "centroid": None,
                    "match": {"id": sem["id"], "content": sem["content"]},
                    "action": "reinforce",
                    "near_miss": None,
                })

        compress_id = str(uuid.uuid4())
        self._pending[compress_id] = {"clusters": clusters}

        return {"clusters": clusters, "compress_id": compress_id}
