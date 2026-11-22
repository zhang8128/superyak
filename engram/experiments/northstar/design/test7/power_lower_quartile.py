"""Design-time check 2: a lower-quartile pair statistic, normalised by the median over pairs of their lower quartiles."""
import sys, itertools, numpy as np
sys.path.insert(0, sys.argv[1])
from sim import gen_instance

def lq_scores(inst, min_n=4):
    K = inst['mask'].shape[0]; d = {}
    for i, j in itertools.combinations(range(K), 2):
        both = inst['mask'][i] & inst['mask'][j]
        if both.sum() >= min_n:
            d[(i, j)] = np.percentile((inst['reports'][i, both] - inst['reports'][j, both]) ** 2, 25)
    if len(d) < 2: return {}
    ref = np.median(list(d.values()))
    return {p: -(v / ref) for p, v in d.items()}

def med_scores(inst):
    K = inst['mask'].shape[0]; d = {}
    for i, j in itertools.combinations(range(K), 2):
        both = inst['mask'][i] & inst['mask'][j]
        if both.sum() >= 3:
            d[(i, j)] = np.median((inst['reports'][i, both] - inst['reports'][j, both]) ** 2)
    if not d: return {}
    med = np.median(list(d.values()))
    return {p: -(v / med) for p, v in d.items()}

STATS = {'med_ratio': med_scores, 'lower_q': lq_scores}
rng = np.random.default_rng(20261124)
for K, M, rho in [(4, 20, 0.5), (4, 60, 0.9), (6, 20, 0.5), (6, 60, 0.9), (5, 60, 0.5)]:
    cal = {n: [] for n in STATS}
    for _ in range(400):
        inst = gen_instance(K, M, rho, rng.choice([2., 4., 8.]), rng.choice([.25, .5]), rng, copier=False)
        for n, f in STATS.items():
            sc = f(inst); cal[n].append(max(sc.values()) if sc else -np.inf)
    theta = {n: np.percentile(v, 95) for n, v in cal.items()}
    for b in (2., 8.):
        fa = {n: 0 for n in STATS}
        for _ in range(300):
            inst = gen_instance(K, M, rho, b, 0.5, rng, copier=False)
            for n, f in STATS.items():
                sc = f(inst); fa[n] += any(v > theta[n] for v in sc.values())
        for tau, q in ((0.5, 0.25), (0.5, 0.5), (1.0, 0.5)):
            hit = {n: 0 for n in STATS}; hon = {n: 0 for n in STATS}
            for _ in range(300):
                inst = gen_instance(K, M, rho, b, 0.5, rng, copier=True, tau=tau, q=q)
                cp = tuple(sorted((inst['bad'], inst['copier'])))
                for n, f in STATS.items():
                    sc = f(inst); fl = [p for p, v in sc.items() if v > theta[n]]
                    hit[n] += cp in fl; hon[n] += any(p != cp for p in fl)
            print(f"K{K} M{M} rho{rho} b{b:.0f} tau{tau} q{q}: " + "  ".join(
                f"{n}: copier {hit[n]/3:.0f}% honestFP {hon[n]/3:.0f}% A-FP {fa[n]/3:.0f}%" for n in STATS))
