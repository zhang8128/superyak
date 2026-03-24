"""Resonance formation and surfacing — shared by server.py and emma_engram.py."""
from __future__ import annotations


def form_resonances(storage, results, reinforce_threshold=0.70) -> int:
    """Form resonances between co-occurring recall results in the resonance zone.

    For each pair in the top 5 results, fetches stored vectors and computes cosine
    similarity. If similarity is in [0.50, reinforce_threshold), creates or updates
    a resonance with a stochastic birth weight. Returns count of resonances formed.
    """
    import random
    import numpy as np

    top = results[:5]
    formed = 0
    for i in range(len(top)):
        for j in range(i + 1, len(top)):
            a, b = top[i], top[j]
            vec_a = storage.get_vector(a["layer"], a["id"])
            vec_b = storage.get_vector(b["layer"], b["id"])
            if vec_a is None or vec_b is None:
                continue
            arr_a = np.array(vec_a, dtype=np.float32)
            arr_b = np.array(vec_b, dtype=np.float32)
            norm_a = np.linalg.norm(arr_a)
            norm_b = np.linalg.norm(arr_b)
            if norm_a == 0 or norm_b == 0:
                continue
            similarity = float(np.dot(arr_a, arr_b) / (norm_a * norm_b))
            if 0.50 <= similarity < reinforce_threshold:
                weight = max(0.1, min(0.9, random.gauss(0.5, 0.15)))
                storage.add_resonance(a["id"], a["layer"], b["id"], b["layer"],
                                      similarity=similarity, weight=weight)
                formed += 1
    return formed


def surface_resonances(storage, top_results, existing_ids, max_resonant=2) -> list[dict]:
    """Surface resonance-linked memories that weren't in the direct recall results.

    Takes the top 3 results, queries their resonances, and probabilistically surfaces
    the other side of each resonance pair. Max 2 resonance-pulled memories per recall.
    """
    import random

    surfaced = []
    seen_ids = set(existing_ids)

    for result in top_results[:3]:
        if len(surfaced) >= max_resonant:
            break
        resonances = storage.get_resonances_for(result["id"])
        for res in resonances:
            if len(surfaced) >= max_resonant:
                break
            # Find the "other side" of this resonance pair
            other_id = res["memory_b"] if res["memory_a"] == result["id"] else res["memory_a"]
            other_layer = res["layer_b"] if res["memory_a"] == result["id"] else res["layer_a"]
            if other_id in seen_ids:
                continue
            strength = res.get("strength", 0.5)
            weight = res.get("weight", 0.5)
            if random.random() >= weight * strength:
                continue
            # Hydrate content
            mem = None
            if other_layer == "episode":
                row = storage.get_episode(other_id)
                if row:
                    mem = {
                        "id": other_id,
                        "layer": "episode",
                        "content": row.get("content", ""),
                        "context": row.get("context"),
                        "origin": "lived",
                        "resonant": True,
                        "resonance_id": res["id"],
                    }
            elif other_layer == "semantic":
                row = storage.get_semantic(other_id)
                if row:
                    mem = {
                        "id": other_id,
                        "layer": "semantic",
                        "content": row.get("content", ""),
                        "confidence": row.get("confidence"),
                        "kind": row.get("kind"),
                        "origin": "organic",
                        "resonant": True,
                        "resonance_id": res["id"],
                    }
            elif other_layer == "instinct":
                row = storage.get_instinct(other_id)
                if row:
                    mem = {
                        "id": other_id,
                        "layer": "instinct",
                        "content": row.get("action", ""),
                        "trigger": row.get("trigger", ""),
                        "origin": "organic",
                        "resonant": True,
                        "resonance_id": res["id"],
                    }
            if mem is not None:
                surfaced.append(mem)
                seen_ids.add(other_id)

    return surfaced
