"""Recall scoring — one function, three callers.

``recall()``, the margin counterfactual (``server._unbiased_top``), and the
replay script (``scripts/margins_replay.py``) all score candidates through
``score_candidate`` so a control arm and a replay measure the formula, not a
second implementation of it.

Two modes:

- ``additive`` — the historical formula ``similarity * w_sim + recency * w_rec``.
  With w_rec = 0.4 a day-old memory earns about 0.2 from age alone, which on
  the September 2026 store decided roughly half of all winners.
- ``tiebreak`` — ``similarity * w_sim + recency * cap``. Recency can move a
  score by at most ``cap``, so it decides near-ties and nothing else.

``cap`` defaults to the margins near-tie threshold. Provisional: no
calibration exists yet; ``docs/reports/2026-09-margins-replay.md`` is the
first measurement.
"""

from __future__ import annotations

MODES = ("tiebreak", "additive")

# Provisional — equals margins.DEFAULT_NEAR_TIE by design, kept separate so a
# calibration pass can move either without touching the other.
DEFAULT_RECENCY_CAP = 0.02

AUTO_GENERATED_PENALTY = 0.7


def score_candidate(
    similarity: float,
    recency: float,
    auto_generated: bool,
    *,
    mode: str,
    w_sim: float,
    w_rec: float,
    cap: float,
) -> float:
    """Score one recall candidate.

    ``recency`` is in [0, 1] (1 / (1 + days)). ``auto_generated`` marks
    concatenated semantics that were never AI-summarized; they keep the
    historical 0.7 penalty.
    """
    if mode not in MODES:
        raise ValueError(f"unknown recency_mode {mode!r}; expected one of {MODES}")
    if mode == "additive":
        score = similarity * w_sim + recency * w_rec
    else:
        score = similarity * w_sim + recency * cap
    if auto_generated:
        score *= AUTO_GENERATED_PENALTY
    return score
