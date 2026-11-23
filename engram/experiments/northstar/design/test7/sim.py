import numpy as np

# ---------- fixture ----------

def build_mask(K, M, rho, rng):
    mask = rng.random((K, M)) < rho
    for _ in range(50):
        item_counts = mask.sum(axis=0)
        under = np.where(item_counts < 2)[0]
        if len(under) == 0:
            break
        for m in under:
            needed = 2 - mask[:, m].sum()
            if needed <= 0:
                continue
            zero_idx = np.where(~mask[:, m])[0]
            if len(zero_idx) == 0:
                continue
            chosen = rng.choice(zero_idx, size=min(needed, len(zero_idx)), replace=False)
            mask[chosen, m] = True
    for _ in range(50):
        src_counts = mask.sum(axis=1)
        under = np.where(src_counts < 5)[0]
        if len(under) == 0:
            break
        for k in under:
            needed = 5 - mask[k, :].sum()
            if needed <= 0:
                continue
            zero_idx = np.where(~mask[k, :])[0]
            if len(zero_idx) == 0:
                continue
            chosen = rng.choice(zero_idx, size=min(needed, len(zero_idx)), replace=False)
            mask[k, chosen] = True
    # one more item-min pass in case source-fix broke an item min (rare)
    item_counts = mask.sum(axis=0)
    under = np.where(item_counts < 2)[0]
    for m in under:
        needed = 2 - mask[:, m].sum()
        if needed <= 0:
            continue
        zero_idx = np.where(~mask[:, m])[0]
        if len(zero_idx) == 0:
            continue
        chosen = rng.choice(zero_idx, size=min(needed, len(zero_idx)), replace=False)
        mask[chosen, m] = True
    return mask


def gen_instance(K, M, rho, b, s, rng, copier=False, tau=None, q=None, bad=0, copier_idx=1):
    mask = build_mask(K, M, rho, rng)
    true_vals = rng.uniform(0, 1, M)
    noise = rng.normal(0, 1, (K, M))
    reports = true_vals[None, :] + noise
    reports[~mask] = np.nan

    bad_items = np.where(mask[bad])[0]
    n_bad = len(bad_items)
    n_biased = max(1, int(np.ceil(s * n_bad)))
    biased_items = rng.choice(bad_items, size=min(n_biased, n_bad), replace=False)
    sign = rng.choice([-1.0, 1.0])
    reports[bad, biased_items] += sign * b

    copied_items = np.array([], dtype=int)
    if copier:
        shared = np.where(mask[bad] & mask[copier_idx])[0]
        n_copy = int(round(q * len(shared))) if len(shared) > 0 else 0
        n_copy = max(1, n_copy) if len(shared) > 0 else 0
        if n_copy > 0:
            copied_items = rng.choice(shared, size=min(n_copy, len(shared)), replace=False)
            copier_noise = rng.normal(0, tau, len(copied_items))
            reports[copier_idx, copied_items] = reports[bad, copied_items] + copier_noise

    copied_biased_items = np.intersect1d(copied_items, biased_items)

    return dict(mask=mask, reports=reports, true=true_vals, bad=bad,
                biased_items=biased_items, copier=copier_idx if copier else None,
                copied_items=copied_items, copied_biased_items=copied_biased_items)


def pairwise_d(inst):
    K = inst['mask'].shape[0]
    d = {}
    for i in range(K):
        for j in range(i + 1, K):
            both = inst['mask'][i] & inst['mask'][j]
            if both.sum() >= 3:
                diffs = (inst['reports'][i, both] - inst['reports'][j, both]) ** 2
                d[(i, j)] = np.median(diffs)
    return d


def consensus_general(inst, pair_specs):
    K, M = inst['mask'].shape
    cons = np.full(M, np.nan)
    for m in range(M):
        srcs = np.where(inst['mask'][:, m])[0]
        if len(srcs) == 0:
            continue
        vals = {k: inst['reports'][k, m] for k in srcs}
        used = set()
        merged = []
        for (i, j, items) in pair_specs:
            if i in used or j in used:
                continue
            if i not in vals or j not in vals:
                continue
            if items is not None and m not in items:
                continue
            merged.append((vals[i] + vals[j]) / 2.0)
            used.add(i)
            used.add(j)
        for k in srcs:
            if k not in used:
                merged.append(vals[k])
        cons[m] = np.median(merged)
    return cons


def naive_consensus(inst):
    return consensus_general(inst, [])


def auditor_flagged_pairs(inst, theta):
    d = pairwise_d(inst)
    if len(d) == 0:
        return [], d, None
    med = np.median(list(d.values()))
    flagged = [pair for pair, val in d.items() if (val / med) < theta]
    return flagged, d, med


def min_r(inst):
    d = pairwise_d(inst)
    if len(d) == 0:
        return None
    med = np.median(list(d.values()))
    return min(d.values()) / med, d, med


# ---------- calibration of theta ----------

def calibrate_theta(K, M, rho, rng, n_cal=400, b_grid=(2.0, 8.0), s_grid=(0.25, 0.5)):
    mins = []
    for _ in range(n_cal):
        b = rng.choice(b_grid)
        s = rng.choice(s_grid)
        inst = gen_instance(K, M, rho, b, s, rng, copier=False)
        r = min_r(inst)
        if r is not None:
            mins.append(r[0])
    mins = np.array(mins)
    theta = np.percentile(mins, 5)
    return theta, mins


# ---------- experiment ----------

def run_cell(K, M, rho, b, s, tau, q, theta, rng, n_instances=300):
    rows = []
    for _ in range(n_instances):
        inst = gen_instance(K, M, rho, b, s, rng, copier=True, tau=tau, q=q)
        flagged, d, med = auditor_flagged_pairs(inst, theta)
        cons_N = naive_consensus(inst)
        cons_I = consensus_general(inst, [(i, j, None) for (i, j) in flagged])
        oracle_pair_specs = [(inst['bad'], inst['copier'], set(inst['copied_items'].tolist()))] if inst['copier'] is not None else []
        cons_O = consensus_general(inst, oracle_pair_specs)

        cbi = inst['copied_biased_items']
        true = inst['true']
        if len(cbi) == 0:
            err_N = err_I = err_O = np.nan
        else:
            err_N = np.mean(np.abs(cons_N[cbi] - true[cbi]))
            err_I = np.mean(np.abs(cons_I[cbi] - true[cbi]))
            err_O = np.mean(np.abs(cons_O[cbi] - true[cbi]))

        bad_items = np.where(inst['mask'][inst['bad']])[0]
        err_N_all = np.mean(np.abs(cons_N[bad_items] - true[bad_items]))
        err_I_all = np.mean(np.abs(cons_I[bad_items] - true[bad_items]))

        true_pair = (min(inst['bad'], inst['copier']), max(inst['bad'], inst['copier']))
        copier_flagged = true_pair in flagged
        # "an honest pair" flagged: any flagged pair not equal to true_pair
        honest_flagged = any(p != true_pair for p in flagged)

        # scale estimate ŝ = sqrt(median pair d / 2), using the SAME median used for r (over all eligible pairs)
        s_hat = np.sqrt(med / 2.0) if med is not None else np.nan

        rows.append(dict(err_N=err_N, err_I=err_I, err_O=err_O,
                          err_N_all=err_N_all, err_I_all=err_I_all,
                          n_scored=len(cbi), copier_flagged=copier_flagged,
                          honest_flagged=honest_flagged, n_flagged=len(flagged),
                          s_hat=s_hat))
    return rows


def run_cell_A(K, M, rho, b, s, theta, rng, n_instances=300):
    rows = []
    for _ in range(n_instances):
        inst = gen_instance(K, M, rho, b, s, rng, copier=False)
        r = min_r(inst)
        flagged, d, med = auditor_flagged_pairs(inst, theta)
        cons_N = naive_consensus(inst)
        cons_I = consensus_general(inst, [(i, j, None) for (i, j) in flagged])
        bad_items = np.where(inst['mask'][inst['bad']])[0]
        true = inst['true']
        err_N_all = np.mean(np.abs(cons_N[bad_items] - true[bad_items]))
        err_I_all = np.mean(np.abs(cons_I[bad_items] - true[bad_items]))
        flagged_any = (r is not None) and (r[0] < theta)
        rows.append(dict(err_N_all=err_N_all, err_I_all=err_I_all, flagged_any=flagged_any,
                          n_flagged=len(flagged)))
    return rows


def bootstrap_mean_diff(a, b, n_boot=2000, seed=2026112207):
    rng = np.random.default_rng(seed)
    a = np.asarray(a)
    b = np.asarray(b)
    n = len(a)
    diffs = a - b
    idx_all = rng.integers(0, n, size=(n_boot, n))
    boot = diffs[idx_all].mean(axis=1)
    lo, hi = np.percentile(boot, [2.5, 97.5])
    return diffs.mean(), lo, hi


if __name__ == "__main__":
    import json
    rng_master = np.random.default_rng(12345)

    cells = [
        dict(name="baseline", K=4, M=20, rho=0.5, b=2.0, s=0.5, tau=0.5, q=0.25),
        dict(name="K6", K=6, M=20, rho=0.5, b=2.0, s=0.5, tau=0.5, q=0.25),
        dict(name="M60", K=4, M=60, rho=0.5, b=2.0, s=0.5, tau=0.5, q=0.25),
        dict(name="rho09", K=4, M=20, rho=0.9, b=2.0, s=0.5, tau=0.5, q=0.25),
        dict(name="b8", K=4, M=20, rho=0.5, b=8.0, s=0.5, tau=0.5, q=0.25),
        dict(name="tau15", K=4, M=20, rho=0.5, b=2.0, s=0.5, tau=1.5, q=0.25),
        dict(name="q50", K=4, M=20, rho=0.5, b=2.0, s=0.5, tau=0.5, q=0.5),
        dict(name="hard_all", K=6, M=60, rho=0.9, b=8.0, s=0.5, tau=1.5, q=0.5),
        dict(name="easy_bigbias_lowtau", K=4, M=20, rho=0.5, b=8.0, s=0.5, tau=0.5, q=0.5),
    ]

    results = {}
    n_inst = 300

    for cell in cells:
        name = cell["name"]
        K, M, rho = cell["K"], cell["M"], cell["rho"]
        b, s, tau, q = cell["b"], cell["s"], cell["tau"], cell["q"]

        theta, cal_mins = calibrate_theta(K, M, rho, rng_master, n_cal=500)

        rows = run_cell(K, M, rho, b, s, tau, q, theta, rng_master, n_instances=n_inst)
        rows_A = run_cell_A(K, M, rho, b, s, theta, rng_master, n_instances=n_inst)

        err_N = np.array([r["err_N"] for r in rows])
        err_I = np.array([r["err_I"] for r in rows])
        err_O = np.array([r["err_O"] for r in rows])
        valid = ~np.isnan(err_N)
        n_valid = valid.sum()

        mean_NI, lo_NI, hi_NI = bootstrap_mean_diff(err_N[valid], err_I[valid])
        mean_NO, lo_NO, hi_NO = bootstrap_mean_diff(err_N[valid], err_O[valid])
        ratio = mean_NI / mean_NO if mean_NO != 0 else float('nan')

        err_N_all = np.array([r["err_N_all"] for r in rows])
        err_I_all = np.array([r["err_I_all"] for r in rows])
        mean_IN_all, lo_IN_all, hi_IN_all = bootstrap_mean_diff(err_I_all, err_N_all)  # I - N, do-no-harm direction

        copier_flag_rate = np.mean([r["copier_flagged"] for r in rows])
        honest_flag_rate = np.mean([r["honest_flagged"] for r in rows])
        s_hat_mean = np.nanmean([r["s_hat"] for r in rows])

        err_N_all_A = np.array([r["err_N_all"] for r in rows_A])
        err_I_all_A = np.array([r["err_I_all"] for r in rows_A])
        mean_IN_A, lo_IN_A, hi_IN_A = bootstrap_mean_diff(err_I_all_A, err_N_all_A)
        flag_rate_A = np.mean([r["flagged_any"] for r in rows_A])

        results[name] = dict(
            cell=cell, theta=theta, n_valid_scored=int(n_valid),
            mean_err_N=float(np.nanmean(err_N)), mean_err_I=float(np.nanmean(err_I)), mean_err_O=float(np.nanmean(err_O)),
            NminusI=(mean_NI, lo_NI, hi_NI), NminusO=(mean_NO, lo_NO, hi_NO), ratio_I_over_O=float(ratio),
            do_no_harm_D_items=(mean_IN_all, lo_IN_all, hi_IN_all),
            do_no_harm_A=(mean_IN_A, lo_IN_A, hi_IN_A),
            flag_rate_A_pooled_calib=float(flag_rate_A),
            copier_flag_rate_D=float(copier_flag_rate), honest_flag_rate_D=float(honest_flag_rate),
            s_hat_mean=float(s_hat_mean),
        )

        print(f"--- {name}: K={K} M={M} rho={rho} b={b} s={s} tau={tau} q={q} ---")
        print(f"  theta = {theta:.4f} (calib n={len(cal_mins)})")
        print(f"  scored instances (copied+biased items exist): {n_valid}/{n_inst}")
        print(f"  mean err: N={np.nanmean(err_N):.4f} I={np.nanmean(err_I):.4f} O={np.nanmean(err_O):.4f}")
        print(f"  N-I = {mean_NI:.4f} [{lo_NI:.4f}, {hi_NI:.4f}]")
        print(f"  N-O = {mean_NO:.4f} [{lo_NO:.4f}, {hi_NO:.4f}]  ratio I/O gain = {ratio:.3f}")
        print(f"  do-no-harm (I-N) on bad-source items, condition D: {mean_IN_all:.4f} [{lo_IN_all:.4f},{hi_IN_all:.4f}]")
        print(f"  do-no-harm (I-N) on bad-source items, condition A: {mean_IN_A:.4f} [{lo_IN_A:.4f},{hi_IN_A:.4f}]")
        print(f"  A flag-rate at this (b,s) using pooled theta: {flag_rate_A:.3f} (target 0.05)")
        print(f"  D: copier-pair flagged rate = {copier_flag_rate:.3f}, an honest pair flagged rate = {honest_flag_rate:.3f}")
        print(f"  mean s_hat = {s_hat_mean:.4f} (true sigma = 1.0)")
        print()

    # Pooling question: for ONE fixed (K,M,rho), compute theta pooled over b,s grid,
    # then check A flag rate SEPARATELY for each (b,s) cell to see how much it varies.
    print("=== Pooling sensitivity: does A's flag rate vary by (b,s) under one pooled theta? ===")
    K, M, rho = 4, 20, 0.5
    theta, cal_mins = calibrate_theta(K, M, rho, rng_master, n_cal=800)
    print(f"pooled theta (K={K},M={M},rho={rho}) = {theta:.4f}")
    for b in (2.0, 8.0):
        for s in (0.25, 0.5):
            rows_A = run_cell_A(K, M, rho, b, s, theta, rng_master, n_instances=400)
            flag_rate = np.mean([r["flagged_any"] for r in rows_A])
            print(f"  b={b} s={s}: flag rate = {flag_rate:.3f}")

    with open("/private/tmp/claude-501/-Users-kairos-Projects-superyak/73639fc4-1fe9-4949-9cff-a87a42a5ea74/scratchpad/t7review/results.json", "w") as f:
        json.dump({k: {kk: (list(vv) if isinstance(vv, tuple) else vv) for kk, vv in v.items() if kk != "cell"} for k, v in results.items()}, f, indent=2, default=str)
