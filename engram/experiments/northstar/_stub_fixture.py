"""A STUB of Tardis's graded-blame fixture generator (all hands d9c5f051), to unblock test7.py until the
real one lands. Follows ``docs/superpowers/specs/2026-11-22-graded-blame-fixture-design.md``'s rules as
closely as a stub reasonably can:

- K sources, M items, each source reporting each item with probability rho;
- minimums: every item at least 2 reports, every source at least 5, fixed by redrawing (items first, then
  sources, repeated until both hold);
- one bad source (fixed at index 0) biasing a seeded share ``ceil(s * n)`` (at least 1) of its own n items
  by one signed ``b*sigma``;
- in C and D only, one copier (fixed at index 1) repeating the bad source's report plus ``tau*sigma`` noise
  on a seeded share of their *shared* items (``round(q * n_shared)``, at least 1 if any are shared).

C and D draw identically -- the base instance, the bias and the copier's reports never depend on
``condition`` -- and differ *only* in whether a copied report's chain names the bad source (C) or stays
unnamed (D), per the fixture spec's A3/R6. This is why ``generate(cell, "C", i, seed_root)`` and
``generate(cell, "D", i, seed_root)`` have identical ``reports``.

Swap this module for Tardis's real one by changing the single import at the top of ``test7.py``
(``from experiments.northstar._stub_fixture import generate``).
"""
from __future__ import annotations

import numpy as np

BAD_SOURCE = 0
COPIER_SOURCE = 1
MIN_ITEM_REPORTS = 2
MIN_SOURCE_REPORTS = 5


def _key(x) -> int:
    """A grid float as a ``SeedSequence``-safe int, exact for the grid's own values (quarters, tenths)."""
    return int(round(float(x) * 1000))


def _rng(seed_root: int, tag: int, cell: dict, instance_index: int, *extra: float) -> np.random.Generator:
    """A generator keyed by every argument that must make two calls draw identically (``seed_root``, a
    ``tag`` separating independent draws, the cell's K/M/rho/b/s, any ``extra`` grid values, and the
    instance index) -- never by ``condition``, so C and D share every draw their common reports need."""
    entropy = [int(seed_root), tag, int(round(cell["K"])), int(round(cell["M"])), _key(cell["rho"]),
              _key(cell["b"]), _key(cell["s"])] + [_key(e) for e in extra] + [int(instance_index)]
    return np.random.default_rng(np.random.SeedSequence(entropy))


def _build_mask(K: int, M: int, rho: float, rng: np.random.Generator) -> tuple[np.ndarray, int]:
    """Every source reports each item with probability ``rho``; an item under ``MIN_ITEM_REPORTS`` is
    redrawn on its own, then a source under ``MIN_SOURCE_REPORTS`` gets more items, repeated until both
    minimums hold. Returns the mask and how many redraw passes it took."""
    mask = rng.random((K, M)) < rho
    attempts = 0
    for _ in range(200):
        attempts += 1
        item_short = np.where(mask.sum(axis=0) < MIN_ITEM_REPORTS)[0]
        source_short = np.where(mask.sum(axis=1) < MIN_SOURCE_REPORTS)[0]
        if len(item_short) == 0 and len(source_short) == 0:
            break
        for m in item_short:
            needed = MIN_ITEM_REPORTS - mask[:, m].sum()
            if needed <= 0:
                continue
            candidates = np.where(~mask[:, m])[0]
            if len(candidates) == 0:
                continue
            chosen = rng.choice(candidates, size=min(needed, len(candidates)), replace=False)
            mask[chosen, m] = True
        for k in source_short:
            needed = MIN_SOURCE_REPORTS - mask[k, :].sum()
            if needed <= 0:
                continue
            candidates = np.where(~mask[k, :])[0]
            if len(candidates) == 0:
                continue
            chosen = rng.choice(candidates, size=min(needed, len(candidates)), replace=False)
            mask[k, chosen] = True
    return mask, attempts


def generate(cell: dict, condition: str, instance_index: int, seed_root: int) -> dict:
    """One instance of ``condition`` ("A", "C" or "D") for ``cell`` (a dict with at least K, M, rho, b, s,
    and -- for C/D -- tau, q), keyed by ``instance_index`` and ``seed_root``. See the module docstring for
    what C and D share and where they differ."""
    if condition not in ("A", "C", "D"):
        raise ValueError(f"condition must be A, C or D; got {condition!r}")
    K, M, rho = int(cell["K"]), int(cell["M"]), float(cell["rho"])
    b, s = float(cell["b"]), float(cell["s"])
    sigma = 1.0

    base_rng = _rng(seed_root, 0, cell, instance_index)
    mask, attempts = _build_mask(K, M, rho, base_rng)
    true_values = base_rng.uniform(0.0, 1.0, M)
    reports = true_values[None, :] + base_rng.normal(0.0, sigma, (K, M))

    bad_item_ids = np.where(mask[BAD_SOURCE])[0]
    n_biased = max(1, int(np.ceil(s * len(bad_item_ids)))) if len(bad_item_ids) else 0
    biased_items = (base_rng.choice(bad_item_ids, size=min(n_biased, len(bad_item_ids)), replace=False)
                    if n_biased else np.array([], dtype=int))
    sign = float(base_rng.choice([-1.0, 1.0]))
    if len(biased_items):
        reports[BAD_SOURCE, biased_items] += sign * b * sigma
    biased_items = np.sort(biased_items)

    chains = np.full((K, M), None, dtype=object)
    copier = None
    copied_items: np.ndarray = np.array([], dtype=int)
    honest_counts_on_copied: np.ndarray = np.array([], dtype=int)

    if condition in ("C", "D"):
        tau, q = float(cell["tau"]), float(cell["q"])
        copier = COPIER_SOURCE
        shared = np.where(mask[BAD_SOURCE] & mask[COPIER_SOURCE])[0]
        copier_rng = _rng(seed_root, 1, cell, instance_index, tau, q)
        n_copy = int(round(q * len(shared))) if len(shared) else 0
        n_copy = max(1, n_copy) if len(shared) else 0
        if n_copy:
            copied_items = np.sort(copier_rng.choice(shared, size=min(n_copy, len(shared)), replace=False))
            copier_noise = copier_rng.normal(0.0, tau * sigma, len(copied_items))
            reports[COPIER_SOURCE, copied_items] = reports[BAD_SOURCE, copied_items] + copier_noise
            honest_counts_on_copied = mask[:, copied_items].sum(axis=0) - 2
            if condition == "C":
                for item in copied_items:
                    chains[COPIER_SOURCE, item] = BAD_SOURCE

    reports = reports.astype(float)
    reports[~mask] = np.nan
    copied_biased_items = np.intersect1d(copied_items, biased_items)

    return {
        "reports": reports,
        "sigma": sigma,
        "chains": chains,
        "truth": {
            "bad": BAD_SOURCE, "copier": copier, "biased_items": biased_items,
            "copied_items": copied_items, "true_values": true_values,
            "honest_counts_on_copied": honest_counts_on_copied,
        },
        "meta": {
            "K": K, "M": M, "rho": rho, "condition": condition, "instance_index": int(instance_index),
            "realised_density": float(mask.mean()), "redraw_attempts": attempts,
            "copied_biased_items": copied_biased_items, "stub": True,
        },
    }
