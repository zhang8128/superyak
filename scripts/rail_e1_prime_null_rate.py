#!/usr/bin/env python3
"""The false-claim rate of E1′'s final rule (section 6′, revision 4), on fresh realistic no-order logs.

Each seed plants a fresh realistic-noorder log (the realistic order log's sessions with each session's queries permuted
over its times, so there is no order to find) and runs scripts/rail_e1_prime.py's own evaluation and verdict on it.
It counts how often the rule falsely says "order carries information" and how often C1′ falsely "holds".

For this study only, the bootstrap uses fewer resamples than the real run's 10,000 (--resamples, default 1,000), to
fit the Pi's time. Everything else, including set B's K = 199 shuffles, is the real rule. One numbers-only line is
written per seed as it finishes, so a study cut short still counts what it ran.

Run: /home/andy/superyak/engram/.venv/bin/python -I scripts/rail_e1_prime_null_rate.py --seeds 100 --out PATH
"""

from __future__ import annotations

import os

for _name in ("OPENBLAS_NUM_THREADS", "OMP_NUM_THREADS", "VECLIB_MAXIMUM_THREADS", "MKL_NUM_THREADS"):
    os.environ.setdefault(_name, "1")

import argparse
import math
import sys
import time
from pathlib import Path

import numpy as np

sys.path.insert(0, str(Path(__file__).resolve().parent))  # -I drops the script's directory
import rail_e1_prime as e  # noqa: E402

SEED_OFFSET = 30_000  # fresh seeds, unused by the smoke runs and the earlier studies


def wilson(k: int, n: int, z: float = 1.959964) -> tuple[float, float]:
    """The Wilson score 95% interval for k of n."""
    if n == 0:
        return float("nan"), float("nan")
    p = k / n
    centre = (p + z * z / (2 * n)) / (1 + z * z / n)
    half = z * math.sqrt(p * (1 - p) / n + z * z / (4 * n * n)) / (1 + z * z / n)
    return max(0.0, centre - half), min(1.0, centre + half)


def one(seed: int, sessions: int | None) -> dict:
    e.SEED = seed
    writer, uri, _ = e.synthetic("realistic-noorder", sessions)
    try:
        conn = e.open_reader(uri)
        try:
            log, uni = e.read_store(conn)
        finally:
            conn.close()
    finally:
        writer.close()
    recalls = np.flatnonzero((log.session >= 0) & ~log.instinct & (log.t >= e.PRIMARY_START))
    res = e.evaluate(log, uni, recalls, 1)
    v = e.verdict(res)
    out = {"c1": v["c1"], "order": v["order"], "steps": res.get("steps", 0)}
    if "stats" in res:
        st = res["stats"]
        out.update(p=st["rank"]["p"], d_order=st["order"]["session"]["point"], d_order_lo=st["order"]["session"]["lo"],
                   d_order_day_lo=st["order"]["day"]["lo"], d=st[("D", 10)]["session"]["point"],
                   d_lo=st[("D", 10)]["session"]["lo"], d_hi=st[("D", 10)]["session"]["hi"])
    return out


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("--seeds", type=int, default=100)
    parser.add_argument("--start", type=int, default=0, help="the first seed index (to resume)")
    parser.add_argument("--resamples", type=int, default=1000, help="bootstrap resamples, for this study only")
    parser.add_argument("--sessions", type=int, help="planted sessions per log (default: the realistic default)")
    parser.add_argument("--out", type=Path, required=True, help="append one line per seed here")
    args = parser.parse_args(argv)
    e.check_classifier()
    e.RESAMPLES = args.resamples
    base = e.SEED
    with args.out.open("a") as sink:
        for k in range(args.start, args.start + args.seeds):
            began = time.monotonic()
            try:
                r = one(base + SEED_OFFSET + k, args.sessions)
            except Exception as error:  # numbers only: the type, never a message
                sink.write(f"seed {k}: stopped ({type(error).__name__})\n")
                sink.flush()
                continue
            fields = " ".join(f"{key} {value:+.4f}" if isinstance(value, float) else f"{key} {value}"
                              for key, value in r.items())
            sink.write(f"seed {k}: {fields} wall {time.monotonic() - began:.0f}s\n")
            sink.flush()
    return 0


def summary(path: Path) -> str:
    rows = [line for line in path.read_text().splitlines() if line.startswith("seed ") and "stopped" not in line]
    n = len(rows)
    order = sum("order carries information" in line for line in rows)
    holds = sum(" c1 holds " in f" {line} " for line in rows)
    negligible = sum(" c1 negligible " in f" {line} " for line in rows)
    insufficient = sum(" c1 insufficient " in f" {line} " for line in rows)
    lo_o, hi_o = wilson(order, n)
    lo_h, hi_h = wilson(holds, n)
    return (f"{n} seeds: order falsely carries information in {order} ({lo_o:.1%} to {hi_o:.1%}, Wilson 95%); "
            f"C1′ falsely holds in {holds} ({lo_h:.1%} to {hi_h:.1%}); negligible {negligible}; insufficient "
            f"{insufficient}")


if __name__ == "__main__":
    if len(sys.argv) == 3 and sys.argv[1] == "--summary":
        print(summary(Path(sys.argv[2])))
        raise SystemExit(0)
    raise SystemExit(main())
