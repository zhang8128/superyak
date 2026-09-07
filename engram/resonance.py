"""Resonance — lateral associations formed from recall co-occurrence patterns."""
from __future__ import annotations

import math
import random


# Minimum total recalls before PMI computation is meaningful
MIN_RECALLS_FOR_PMI = 5


def compute_pmi(
    cooccurrences: dict[tuple[str, str], int],
    frequency: dict[str, int],
    total_recalls: int,
) -> dict[tuple[str, str], float]:
    """Compute pointwise mutual information for co-occurring memory pairs.

    PMI(a,b) = log2( P(a,b) / (P(a) * P(b)) )

    Returns only pairs where both memories have nonzero frequency
    and total_recalls >= MIN_RECALLS_FOR_PMI.
    """
    if total_recalls < MIN_RECALLS_FOR_PMI:
        return {}

    pmi: dict[tuple[str, str], float] = {}
    for (a, b), count in cooccurrences.items():
        freq_a = frequency.get(a, 0)
        freq_b = frequency.get(b, 0)
        if freq_a == 0 or freq_b == 0:
            continue
        p_ab = count / total_recalls
        p_a = freq_a / total_recalls
        p_b = freq_b / total_recalls
        ratio = p_ab / (p_a * p_b + 1e-15)
        if ratio > 0:
            pmi[(a, b)] = math.log2(ratio)
    return pmi


def form_resonances(storage, results, reinforce_threshold=0.70) -> int:
    """Form resonances from recall co-occurrence history using PMI.

    Called after each recall. Computes PMI across all recall history,
    then creates/updates resonances for pairs with PMI > 0 (co-occur
    more than chance predicts). Stochastic birth weight for individuality.

    `reinforce_threshold` is accepted for backwards compatibility but unused.
    PMI formation is gated on score > 0, not a similarity threshold.
    """
    cooccurrences = storage.get_recall_cooccurrences()
    frequency = storage.get_memory_recall_frequency()
    total_recalls = sum(1 for _ in storage.conn.execute(
        "SELECT 1 FROM memory_log WHERE event_type = 'recall'"
    ))

    pmi = compute_pmi(cooccurrences, frequency, total_recalls)
    if not pmi:
        return 0

    # Build lookup for layer info from current results
    layer_map: dict[str, str] = {}
    for r in results:
        layer_map[r["id"]] = r["layer"]

    # Only consider pairs where at least one member is in current results.
    current_ids = {r["id"] for r in results}

    formed = 0
    for (a, b), score in pmi.items():
        if score <= 0:
            continue
        if a not in current_ids and b not in current_ids:
            continue
        layer_a = layer_map.get(a) or _guess_layer(storage, a)
        layer_b = layer_map.get(b) or _guess_layer(storage, b)
        if layer_a is None or layer_b is None:
            continue
        weight = max(0.1, min(0.9, random.gauss(0.5, 0.15)))
        storage.add_resonance(a, layer_a, b, layer_b,
                              similarity=score, weight=weight)
        formed += 1

    return formed


def _guess_layer(storage, memory_id: str) -> str | None:
    """Determine which layer a memory ID belongs to."""
    for layer, table in [("episode", "episodes"), ("semantic", "semantics"),
                         ("instinct", "instincts")]:
        row = storage.conn.execute(
            f"SELECT 1 FROM {table} WHERE id = ?", (memory_id,)
        ).fetchone()
        if row:
            return layer
    return None


def surface_resonances(storage, top_results, existing_ids, max_resonant=2) -> list[dict]:
    """Surface resonance-linked memories not in direct recall results.

    Takes the top 3 results, queries their resonances, and probabilistically
    surfaces the other side of each resonance pair.
    """
    surfaced = []
    seen_ids = set(existing_ids)

    for result in top_results[:3]:
        if len(surfaced) >= max_resonant:
            break
        resonances = storage.get_resonances_for(result["id"])
        for res in resonances:
            if len(surfaced) >= max_resonant:
                break
            other_id = res["memory_b"] if res["memory_a"] == result["id"] else res["memory_a"]
            other_layer = res["layer_b"] if res["memory_a"] == result["id"] else res["layer_a"]
            if other_id in seen_ids:
                continue
            strength = res.get("strength", 0.5)
            weight = res.get("weight", 0.5)
            if random.random() >= weight * strength:
                continue
            mem = _hydrate(storage, other_id, other_layer, res["id"])
            if mem is not None:
                surfaced.append(mem)
                seen_ids.add(other_id)

    return surfaced


def _hydrate(storage, memory_id: str, layer: str, resonance_id: str) -> dict | None:
    """Load content for a resonance-surfaced memory."""
    if layer == "episode":
        row = storage.get_episode(memory_id)
        if row:
            return {"id": memory_id, "layer": "episode",
                    "content": row.get("content", ""),
                    "context": row.get("context"),
                    "lane": row.get("lane") or "personal",
                    "origin": "lived", "resonant": True,
                    "resonance_id": resonance_id}
    elif layer == "semantic":
        row = storage.get_semantic(memory_id)
        if row:
            return {"id": memory_id, "layer": "semantic",
                    "content": row.get("content", ""),
                    "confidence": row.get("confidence"),
                    "kind": row.get("kind"),
                    "lane": row.get("lane") or "personal",
                    "origin": "organic", "resonant": True,
                    "resonance_id": resonance_id}
    elif layer == "instinct":
        row = storage.get_instinct(memory_id)
        if row:
            return {"id": memory_id, "layer": "instinct",
                    "content": row.get("action", ""),
                    "trigger": row.get("trigger", ""),
                    "origin": "organic", "resonant": True,
                    "resonance_id": resonance_id}
    return None
