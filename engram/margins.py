"""Tropical margins — how separated a recall result is from its runner-up.

Recall scores every layer on one soft sum (`similarity * w_sim + recency *
w_rec`) and returns the argmax. That formula always produces a winner, even
when the top two are separated by 0.001 — at which point the ranking is
arbitrary and the store is not discriminating, it is rounding.

Tropical attention makes the selection hard (`max_j {s_ij + v_j}`) and reports
the margin `gamma = z_j* - max_{j != j*} z_j` alongside it. The margin is the
diagnostic worth borrowing: it says nothing about whether the top result is
*right*, only whether the ranking that produced it was decided or a coin flip.

Two caveats this module encodes rather than hides:

- Our scores are uncalibrated cosine similarity plus a recency term. There is
  no oracle, so `gamma` is evidence about ranking stability, not a decision
  rule. Nothing here gates anything.
- The FTS keyword fallback assigns every keyword-only hit a flat similarity of
  0.5. A near-tie against one of those is an artifact of the fallback, not a
  failure to discriminate, so it is flagged separately (`fts_tie`).
"""

from __future__ import annotations

# Provisional: no calibration exists yet for what counts as "too close".
# Kept as a parameter so a calibration pass can move it without a code change.
DEFAULT_NEAR_TIE = 0.02


def margin_stats(entries: list[dict], near_tie_threshold: float = DEFAULT_NEAR_TIE) -> dict:
    """Separation between the top-scored entry and its runner-up.

    Entries are dicts with `score`, and optionally `similarity` and `from_fts`.
    Order is not assumed — the caller's sort is not trusted.

    Returns `top` (gamma), `normalized` (gamma over the full score spread, so
    margins are comparable across queries), `near_tie`, `fts_tie`, and `n`.
    """
    ranked = sorted(entries, key=lambda e: e["score"], reverse=True)
    stats = {
        "top": None,
        "normalized": None,
        "near_tie": False,
        "fts_tie": False,
        "n": len(ranked),
    }
    if len(ranked) < 2:
        return stats

    best, runner_up = ranked[0], ranked[1]
    gamma = best["score"] - runner_up["score"]
    spread = best["score"] - ranked[-1]["score"]

    stats["top"] = gamma
    stats["normalized"] = (gamma / spread) if spread > 0 else 0.0
    stats["near_tie"] = gamma <= near_tie_threshold
    stats["fts_tie"] = stats["near_tie"] and bool(runner_up.get("from_fts"))
    return stats


def distribution(logged: list[dict]) -> dict:
    """Aggregate logged per-recall margins into a calibration view.

    Takes the `margin` payloads recorded on recall log entries. The point is
    to make the shape of `gamma` visible across many recalls — a store whose
    margins cluster near zero is not discriminating, whichever result it
    happened to return first.
    """
    tops = sorted(m["top"] for m in logged if m.get("top") is not None)
    near_ties = [m for m in logged if m.get("near_tie")]
    verdicts = [m.get("stability") or {} for m in logged]
    checked = [v for v in verdicts if v.get("checked")]

    return {
        "recalls": len(logged),
        "median_top": _median(tops),
        "min_top": tops[0] if tops else None,
        "max_top": tops[-1] if tops else None,
        "near_tie_rate": (len(near_ties) / len(logged)) if logged else 0.0,
        "fts_tie_share": (
            sum(1 for m in near_ties if m.get("fts_tie")) / len(near_ties)
        ) if near_ties else 0.0,
        "stability": {
            "checked": len(checked),
            "unchecked": len(verdicts) - len(checked),
            "survived": sum(1 for v in checked if v.get("survives")),
            "displaced": sum(1 for v in checked if v.get("survives") is False),
        },
    }


def _median(values: list[float]) -> float | None:
    if not values:
        return None
    mid = len(values) // 2
    if len(values) % 2:
        return values[mid]
    return (values[mid - 1] + values[mid]) / 2


def stability(biased_top: str | None, unbiased_top: str | None,
              bias_applied: bool) -> dict:
    """Whether the winner survives removing the dream/instinct query bias.

    Tropical stability says the active support holds when `gamma > 2 * epsilon`
    for a perturbation of size epsilon. Engram has a perturbation of exactly
    that shape: `_apply_recall_bias` tilts the query vector toward dream
    residues and session biases at alpha=0.15. Rather than bound it, we measure
    it directly — re-run the search unbiased and see whether the top result
    moves.

    `checked` is False when there was no bias to remove, or when the unbiased
    pass returned nothing to compare against.
    """
    if not bias_applied or unbiased_top is None:
        return {"checked": False, "survives": None, "displaced": None}
    survives = biased_top == unbiased_top
    return {
        "checked": True,
        "survives": survives,
        "displaced": None if survives else unbiased_top,
    }
