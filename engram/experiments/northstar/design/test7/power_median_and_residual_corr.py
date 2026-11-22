"""Design-time power check for test 7's auditor (not a run): candidate pair statistics on toy fixture instances.
Uses the reviewer's gen_instance (t7review/sim.py). Seeds here are design seeds, disjoint from any plan's."""
import sys, itertools, numpy as np
sys.path.insert(0, sys.argv[1])
from sim import gen_instance

def med_ratio_scores(inst):
    K = inst['mask'].shape[0]; d = {}
    for i, j in itertools.combinations(range(K), 2):
        both = inst['mask'][i] & inst['mask'][j]
        if both.sum() >= 3:
            d[(i, j)] = np.median((inst['reports'][i, both] - inst['reports'][j, both]) ** 2)
    if not d: return {}
    med = np.median(list(d.values()))
    return {p: -(v / med) for p, v in d.items()}   # higher = more dependent

def resid_corr_scores(inst, min_n=5):
    K, M = inst['mask'].shape; R = inst['reports']; out = {}
    for i, j in itertools.combinations(range(K), 2):
        ri, rj = [], []
        for m in np.where(inst['mask'][i] & inst['mask'][j])[0]:
            others = [k for k in np.where(inst['mask'][:, m])[0] if k not in (i, j)]
            if not others: continue
            c = np.median(R[others, m]); ri.append(R[i, m] - c); rj.append(R[j, m] - c)
        n = len(ri)
        if n >= min_n and np.std(ri) > 0 and np.std(rj) > 0:
            r = np.clip(np.corrcoef(ri, rj)[0, 1], -0.999999, 0.999999)
            out[(i, j)] = np.arctanh(r) * np.sqrt(n - 3)
    return out

STATS = {'med_ratio': med_ratio_scores, 'resid_corr': resid_corr_scores}
rng = np.random.default_rng(20261122)
obs = [(4, 20, 0.5), (4, 60, 0.9), (6, 20, 0.5), (6, 60, 0.9)]
for K, M, rho in obs:
    # calibrate theta per statistic on A, pooled over b in {2,4,8} and s in {0.25,0.5}
    cal = {name: [] for name in STATS}
    for _ in range(400):
        inst = gen_instance(K, M, rho, rng.choice([2., 4., 8.]), rng.choice([.25, .5]), rng, copier=False)
        for name, f in STATS.items():
            sc = f(inst); cal[name].append(max(sc.values()) if sc else -np.inf)
    theta = {name: np.percentile(v, 95) for name, v in cal.items()}
    for b in (2., 8.):
        for s in (0.5,):
            # realised false-flag rate in A at this (b, s)
            fa = {name: 0 for name in STATS}
            for _ in range(300):
                inst = gen_instance(K, M, rho, b, s, rng, copier=False)
                for name, f in STATS.items():
                    sc = f(inst); fa[name] += any(v > theta[name] for v in sc.values())
            for tau, q in ((0.5, 0.25), (1.5, 0.5)):
                hit = {name: 0 for name in STATS}; honest = {name: 0 for name in STATS}
                for _ in range(300):
                    inst = gen_instance(K, M, rho, b, s, rng, copier=True, tau=tau, q=q)
                    cp = tuple(sorted((inst['bad'], inst['copier'])))
                    for name, f in STATS.items():
                        sc = f(inst); fl = [p for p, v in sc.items() if v > theta[name]]
                        hit[name] += cp in fl; honest[name] += any(p != cp for p in fl)
                print(f"K{K} M{M} rho{rho} b{b:.0f} tau{tau} q{q}: " + "  ".join(
                    f"{n}: copier {hit[n]/3:.0f}% honestFP {honest[n]/3:.0f}% A-FP {fa[n]/3:.0f}%" for n in STATS))
