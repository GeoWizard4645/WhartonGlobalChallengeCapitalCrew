# Backtests and Monte Carlos every bonds / funds / stocks split (2.5% grid) for the Laura Gao plan:
# $300k in 2027 and $150k in 2028 grow to the start of 2033, where a Treasury-ladder reserve for the ten $50k
# payments is set aside and what is left over is x, the extra contribution we can make in 2033.
#
# Stocks = the team's 50/50 momentum + Magic Formula strategy (output/stock_sleeve.csv, written by quant.run).
# Bonds and Funds = the long-history fund proxies in config.BUCKETS. Settings: the ALLOCATION OPTIMIZER block of config.py.
#
# Run: .venv/bin/python optimize.py        (needs numpy, pandas; about 40 seconds)
# Writes output/allocation/: grid.csv, scenarios.csv, x_projection.csv, cppi_grid.csv, steady_grid.csv (the charts are in visuals.py)
import os

import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

import config  # noqa: E402
from goal import dollars, riskfree_reserve  # noqa: E402

OUT = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")
OUT_DIR = os.path.join(OUT, "allocation")
NAMES = list(config.BUCKETS)                       # Bonds, Funds, Stocks
FIRST_YEAR = min(config.CONTRIBUTIONS)
MONTHS = (config.TARGET_YEAR - FIRST_YEAR) * 12    # 72
DEPOSITS = np.zeros(MONTHS)
for _y, _a in config.CONTRIBUTIONS.items():
    DEPOSITS[(_y - FIRST_YEAR) * 12] += _a
TOTAL_IN = DEPOSITS.sum()
RESERVE = riskfree_reserve(config.PLANNING_YIELD)
RF_M = config.RISK_FREE / 12
RC = config.RANGE_CONFIDENCE
RLO, RHI = (1 - RC) / 2 * 100, (1 + RC) / 2 * 100      # percentiles of the quoted range of x
# present value, at month t, of the deposits still to come after month t (the committed 2028 deposit is a safe asset until it arrives)
FUTURE_PV = np.array([sum(DEPOSITS[k] / (1 + config.PLANNING_YIELD) ** ((k - t) / 12) for k in range(t + 1, MONTHS)) for t in range(MONTHS)])
BOUNDS = np.array(config.BOUNDS)



# ---------- history ----------

def load_history():
    """Monthly returns: Bonds, Funds, Stocks (strategy), Mkt (S&P 500 fund), rf. Only complete months."""
    tickers = sorted(set(config.BUCKETS["Bonds"]) | set(config.BUCKETS["Funds"]) | {config.BENCHMARK})
    read = lambda t: pd.read_csv(os.path.join(config.DATA_DIR, t + ".csv"), index_col=0, parse_dates=True).iloc[:, 0]
    px = pd.concat({t: read(t) for t in tickers}, axis=1, sort=True).dropna()
    month_end = px.resample("ME").last()
    if (px.index[-1] + pd.offsets.BDay(1)).month == px.index[-1].month:
        month_end = month_end.iloc[:-1]                     # last month still open
    r = month_end.pct_change().dropna()
    cash = read(config.CASH_TICKER.lstrip("^")) / 100
    rf = (cash.resample("ME").mean() / 12).reindex(r.index).ffill()
    h = pd.DataFrame({"Bonds": sum(w * r[t] for t, w in config.BUCKETS["Bonds"].items()),
                      "Funds": sum(w * r[t] for t, w in config.BUCKETS["Funds"].items()),
                      "Mkt": r[config.BENCHMARK], "rf": rf})
    sleeve = pd.read_csv(os.path.join(OUT, "stock_sleeve.csv"), index_col=0)["ret"]
    sleeve.index = pd.PeriodIndex(sleeve.index, freq="M").to_timestamp(how="end").normalize()
    h["Stocks"] = sleeve.reindex(h.index)
    return h


def beta_alpha(y, x):
    X = np.c_[np.ones(len(x)), x]
    (a, b), *_ = np.linalg.lstsq(X, y, rcond=None)
    return a, b, y - X @ np.array([a, b])


def fill_stocks(h, rng):
    """The strategy only has months from 2011-07. Before that, Stocks = cash + alpha + beta x market + noise drawn from
    the strategy's own residuals, so the older crashes (2000-02, 2008) still hit the stock sleeve."""
    live = h["Stocks"].notna()
    ex_m = h["Mkt"] - h["rf"]
    a, b, resid = beta_alpha((h["Stocks"] - h["rf"])[live].to_numpy(), ex_m[live].to_numpy())
    modeled = h["rf"] + config.STOCK_ALPHA_KEEP * a + b * ex_m + rng.choice(resid, size=len(h))
    h["Stocks"] = h["Stocks"].where(live, modeled)
    _, beta_f, _ = beta_alpha((h["Funds"] - h["rf"]).to_numpy(), ex_m.to_numpy())
    info = dict(live_from=h.index[live][0], live_months=int(live.sum()), alpha=a * 12, beta_s=b,
                resid_vol=resid.std(ddof=1) * np.sqrt(12), beta_f=beta_f)
    return h, info


# ---------- grid and metrics ----------

def make_grid():
    n = round(1 / config.OPT_STEP)
    w = np.array([(i / n, j / n, (n - i - j) / n) for i in range(n + 1) for j in range(n + 1 - i)])
    ok = np.all((w >= BOUNDS[:, 0] - 1e-9) & (w <= BOUNDS[:, 1] + 1e-9), axis=1)
    return w, ok


def final_values(R):
    """R (paths, months, splits) of portfolio returns -> value at the start of 2033 (deposits go in at the start of the month)."""
    v = np.zeros((R.shape[0], R.shape[2]))
    for t in range(R.shape[1]):
        v = (v + DEPOSITS[t]) * (1 + R[:, t, :])
    return v


def ratios(n, s1, s2, sd, sc, m1, m2):
    """Annualized Sharpe, Sortino, Treynor, beta, vol from sums of monthly excess returns (over rf):
    s1 = sum e, s2 = sum e^2, sd = sum min(e,0)^2, sc = sum e*excess market, m1/m2 = sums for the market."""
    mean = s1 / n
    var = s2 / n - mean ** 2
    cov = sc / n - mean * (m1 / n)
    beta = cov / (m2 / n - (m1 / n) ** 2)
    ann = 12 * mean
    vol = np.sqrt(12 * var)
    return {"vol": vol, "beta": beta, "sharpe": ann / vol, "sortino": ann / np.sqrt(12 * sd / n),
            "treynor": np.where(beta >= 0.05, ann / np.where(beta >= 0.05, beta, 1), np.nan)}   # undefined for a market-neutral split


# ---------- backtest on real history ----------

def backtest(h, w):
    """Every 72-month stretch of real history, with the real deposit schedule. Ratios use the whole record."""
    sleeves = h[NAMES].to_numpy()
    port = sleeves @ w.T                                        # (months of history, splits)
    starts = np.arange(len(h) - MONTHS + 1)
    v = final_values(port[starts[:, None] + np.arange(MONTHS)])
    e = port - h["rf"].to_numpy()[:, None]
    em = (h["Mkt"] - h["rf"]).to_numpy()
    r = ratios(len(h), e.sum(0), (e ** 2).sum(0), (np.minimum(e, 0) ** 2).sum(0), (e * em[:, None]).sum(0), em.sum(), (em ** 2).sum())
    return v, r


# ---------- Monte Carlo ----------

def draw_counts():
    p = np.array([s[3] for s in config.SCENARIOS.values()])
    c = np.floor(p * config.MC_PATHS).astype(int)
    for i in np.argsort(-(p * config.MC_PATHS - c))[:config.MC_PATHS - c.sum()]:
        c[i] += 1
    return c


def simulate_returns(h, info, rng):
    """(paths, months, [Bonds, Funds, Stocks, Mkt]) in float32, paths grouped by scenario. Returns (X, slices, scenario means)."""
    cols = NAMES + ["Mkt"]
    raw = h[cols].to_numpy()
    dm = raw - raw.mean(0)                                      # history with its own average removed
    ann_vol = dm.std(0, ddof=1) * np.sqrt(12)
    blocks = -(-MONTHS // config.BLOCK_MONTHS)
    counts = draw_counts()
    parts, slices, means, s0 = [], [], [], 0
    for (name, (mkt_ret, bond_ret, vol_mult, _)), n in zip(config.SCENARIOS.items(), counts):
        mkt_arith = mkt_ret + 0.5 * (ann_vol[3] * vol_mult) ** 2        # compound -> arithmetic average
        bond_arith = bond_ret + 0.5 * (ann_vol[0] * vol_mult) ** 2
        funds_arith = config.RISK_FREE + info["beta_f"] * (mkt_arith - config.RISK_FREE)
        stock_arith = config.RISK_FREE + config.STOCK_ALPHA_KEEP * info["alpha"] + info["beta_s"] * (mkt_arith - config.RISK_FREE)
        mu = np.array([bond_arith, funds_arith, stock_arith, mkt_arith]) / 12
        starts = rng.integers(0, len(dm), size=(n, blocks))
        idx = ((starts[:, :, None] + np.arange(config.BLOCK_MONTHS)) % len(dm)).reshape(n, -1)[:, :MONTHS]
        parts.append((mu + vol_mult * dm[idx]).astype(np.float32))
        slices.append((s0, s0 + n))
        means.append(mu * 12)
        s0 += n
    return np.concatenate(parts), slices, means


def monte_carlo(X, slices, w, chunk=12):
    n_k = len(slices)
    a = len(w)
    v = np.zeros((len(X), a), dtype=np.float32)
    sums = np.zeros((5, n_k, a))
    msums = np.zeros((2, n_k))
    em = X[:, :, 3] - RF_M
    for k, (s0, s1) in enumerate(slices):
        msums[:, k] = [em[s0:s1].sum(dtype=np.float64), (em[s0:s1].astype(np.float64) ** 2).sum()]
    w32 = w.astype(np.float32)
    for c0 in range(0, a, chunk):
        c1 = min(c0 + chunk, a)
        R = np.einsum("ntj,aj->nta", X[:, :, :3], w32[c0:c1])
        v[:, c0:c1] = final_values(R)
        E = R - np.float32(RF_M)
        for k, (s0, s1) in enumerate(slices):
            e = E[s0:s1]
            sums[0, k, c0:c1] = e.shape[0] * e.shape[1]
            sums[1, k, c0:c1] = e.sum((0, 1), dtype=np.float64)
            sums[2, k, c0:c1] = (e.astype(np.float64) ** 2).sum((0, 1))
            sums[3, k, c0:c1] = (np.minimum(e, 0).astype(np.float64) ** 2).sum((0, 1))
            sums[4, k, c0:c1] = (e * em[s0:s1, :, None]).sum((0, 1), dtype=np.float64)
    per = [ratios(sums[0, k], sums[1, k], sums[2, k], sums[3, k], sums[4, k], msums[0, k], msums[1, k]) for k in range(n_k)]
    allr = ratios(sums[0].sum(0), sums[1].sum(0), sums[2].sum(0), sums[3].sum(0), sums[4].sum(0),
                  msums[0].sum(), msums[1].sum())
    return v, allr, per


# ---------- summaries ----------

def x_stats(v, flex=False):
    """Statistics of x = what is left above the reserve in 2033 (0 if the portfolio can't cover the reserve)."""
    x = np.maximum(v - RESERVE, 0.0) * ((1 - config.FLEX_PCT) if flex else 1.0)
    q = np.percentile(x, [2.5, 25, 50, 75, 97.5])
    lo, hi = np.percentile(x, [RLO, RHI])
    return {"x_mean": x.mean(), "x_median": q[2], "x_range_lo": lo, "x_range_hi": hi, "x_p2_5": q[0], "x_p25": q[1], "x_p75": q[3], "x_p97_5": q[4],
            "p_shortfall": float((v < RESERVE).mean()), "value_median": float(np.median(v)),
            "surplus_p2_5": float(np.percentile(v - RESERVE, 2.5))}


def best(values, mask):
    return int(np.nanargmax(np.where(mask, values, -np.inf)))


def label(w):
    return "/".join(f"{x * 100:g}" for x in w)


def main():
    os.makedirs(OUT_DIR, exist_ok=True)
    rng = np.random.default_rng(config.SEED)
    h, info = fill_stocks(load_history(), rng)
    w, in_bounds = make_grid()
    print(f"HISTORY {h.index[0]:%Y-%m} to {h.index[-1]:%Y-%m} ({len(h)} months); stock strategy live from {info['live_from']:%Y-%m} "
          f"({info['live_months']} months), earlier months modeled from the market")
    print(f"Stock sleeve vs S&P 500: beta {info['beta_s']:.2f}, backtested alpha {info['alpha'] * 100:.1f}%/yr (we keep {config.STOCK_ALPHA_KEEP:.0%}), "
          f"residual vol {info['resid_vol'] * 100:.1f}%/yr | Funds beta {info['beta_f']:.2f}")
    print(f"Deposits {dollars(TOTAL_IN)} ({', '.join(f'{y}: {dollars(a)}' for y, a in config.CONTRIBUTIONS.items())}), {MONTHS} months to {config.TARGET_YEAR}; "
          f"reserve for {config.N_PAYMENTS} x {dollars(config.PAYMENT)} at {config.PLANNING_YIELD:.1%} = {dollars(RESERVE)}")
    print(f"{len(w)} splits on a {config.OPT_STEP:.1%} grid, {int(in_bounds.sum())} inside the team bounds {dict(zip(NAMES, config.BOUNDS))}")

    # --- backtest ---
    v_bt, r_bt = backtest(h, w)
    print(f"Backtest: {len(v_bt)} overlapping {MONTHS}-month stretches of real history")

    # --- Monte Carlo ---
    X, slices, means = simulate_returns(h, info, rng)
    mkt6 = np.prod(1 + X[:, :, 3].astype(np.float64), axis=1) ** (12 / MONTHS) - 1
    hist6 = np.prod(1 + h["Mkt"].to_numpy()[np.arange(len(h) - MONTHS + 1)[:, None] + np.arange(MONTHS)], axis=1) ** (12 / MONTHS) - 1
    q = [5, 25, 50, 75, 95]
    print(f"\nS&P 500 compound return over the 6 years, 5/25/50/75/95th pct:  simulated {np.percentile(mkt6, q).round(3) * 100}  "
          f"real history {np.percentile(hist6, q).round(3) * 100}")
    v_mc, r_mc, r_k = monte_carlo(X, slices, w)

    # --- grid table ---
    g = pd.DataFrame({"bonds": w[:, 0], "funds": w[:, 1], "stocks": w[:, 2], "in_bounds": in_bounds})
    xs = {"mc": x_stats(v_mc), "bt": x_stats(v_bt)}
    for tag, v, r in (("mc", v_mc, r_mc), ("bt", v_bt, r_bt)):
        x = np.maximum(v - RESERVE, 0)
        pc = np.percentile(x, [2.5, 25, 50, 75, 97.5], axis=0)
        g[tag + "_profit"] = v.mean(0) - TOTAL_IN
        g[tag + "_x_mean"], g[tag + "_x_median"] = x.mean(0), pc[2]
        g[tag + "_x_p2_5"], g[tag + "_x_p97_5"], g[tag + "_x_p25"], g[tag + "_x_p75"] = pc[0], pc[4], pc[1], pc[3]
        g[tag + "_p_shortfall"] = (v < RESERVE).mean(0)
        for k in ("vol", "beta", "sharpe", "sortino", "treynor"):
            g[tag + "_" + k] = r[k]
    metrics = ["profit", "sharpe", "treynor", "sortino"]
    g["rank_score"] = np.mean([g["mc_" + m].rank(ascending=False, na_option="bottom") for m in metrics], axis=0)
    g.round(5).to_csv(os.path.join(OUT_DIR, "grid.csv"), index=False)

    # --- optimal splits ---
    names = {"profit": "Max profit", "sharpe": "Max Sharpe", "treynor": "Max Treynor", "sortino": "Max Sortino"}
    picks = {}                                                   # label -> grid index
    for m in metrics:
        for tag in ("mc", "bt"):
            picks[f"{tag}:{m}:bounds"] = best(g[f"{tag}_{m}"].to_numpy(), in_bounds)
            picks[f"{tag}:{m}:free"] = best(g[f"{tag}_{m}"].to_numpy(), np.ones(len(g), bool))
    rec = int(g.loc[in_bounds, "rank_score"].idxmin())
    safe = in_bounds & (g["mc_p_shortfall"].to_numpy() <= config.MAX_SHORTFALL)
    low_risk = best(g["mc_x_median"].to_numpy(), safe) if safe.any() else int(g.loc[in_bounds, "mc_p_shortfall"].idxmin())
    base = int(np.argmin(np.abs(w - np.array(config.BASELINE)).sum(1)))

    def line(tag, i):
        return (f"{label(w[i]):>13} | profit {g.at[i, tag + '_profit']:>9,.0f}  Sharpe {g.at[i, tag + '_sharpe']:5.2f}  "
                f"Treynor {g.at[i, tag + '_treynor']:6.3f}  Sortino {g.at[i, tag + '_sortino']:5.2f}  vol {g.at[i, tag + '_vol']:5.1%}  "
                f"median x {g.at[i, tag + '_x_median']:>9,.0f}  P(short) {g.at[i, tag + '_p_shortfall']:5.1%}")

    for tag, title in (("mc", "MONTE CARLO (all futures mixed by probability)"), ("bt", "BACKTEST (real history, every 6-year stretch)")):
        print(f"\nBEST SPLITS - {title}   [Bonds/Funds/Stocks %]")
        for m in metrics:
            print(f"  {names[m]:12} in team bounds:", line(tag, picks[f"{tag}:{m}:bounds"]))
            if picks[f"{tag}:{m}:free"] != picks[f"{tag}:{m}:bounds"]:
                print(f"  {'':12} no bounds:     ", line(tag, picks[f"{tag}:{m}:free"]))
    print("\n  Plan-doc baseline (MC):  ", line("mc", base))
    print("  Plan-doc baseline (BT):  ", line("bt", base))
    print("  Best average rank across the four ratios (MC, in bounds) =", label(w[rec]), "->", line("mc", rec).split("|")[1].strip())
    print(f"  Highest median x with P(short) <= {config.MAX_SHORTFALL:.0%} (MC, in bounds):", line("mc", low_risk))
    for nm, x, (lo, hi) in zip(NAMES, w[rec], config.BOUNDS):
        if abs(x - lo) < 1e-9 or abs(x - hi) < 1e-9:
            print(f"  NOTE: recommended {nm} sits at its bound ({lo:.0%}-{hi:.0%}); the bound, not the math, sets it.")

    # --- scenario table ---
    rows = []
    print(f"\nEACH FUTURE ON ITS OWN: average annual returns used, and the best split in the team bounds")
    print(f"{'':14}{'prob':>6}{'S&P':>7}{'Bonds':>7}{'Funds':>7}{'Stocks':>7} | {'max profit':>13}{'max Sharpe':>13}{'max Sortino':>13}{'max Treynor':>13} | median x @ recommended")
    for k, (name, spec) in enumerate(config.SCENARIOS.items()):
        s0, s1 = slices[k]
        prof = v_mc[s0:s1].mean(0) - TOTAL_IN
        bests = {"profit": best(prof, in_bounds), "sharpe": best(r_k[k]["sharpe"], in_bounds),
                 "sortino": best(r_k[k]["sortino"], in_bounds), "treynor": best(r_k[k]["treynor"], in_bounds)}
        xr = x_stats(v_mc[s0:s1, rec])
        rows.append({"scenario": name, "probability": spec[3], "sp500_compound": spec[0], "bond_compound": spec[1], "vol_multiplier": spec[2],
                     "avg_return_bonds": means[k][0], "avg_return_funds": means[k][1], "avg_return_stocks": means[k][2],
                     **{f"best_{m}": label(w[i]) for m, i in bests.items()},
                     "rec_x_median": xr["x_median"], "rec_p_shortfall": xr["p_shortfall"]})
        print(f"{name:14}{spec[3]:6.0%}{spec[0]:7.1%}{means[k][0]:7.1%}{means[k][1]:7.1%}{means[k][2]:7.1%} | "
              f"{label(w[bests['profit']]):>13}{label(w[bests['sharpe']]):>13}{label(w[bests['sortino']]):>13}{label(w[bests['treynor']]):>13} | {xr['x_median']:>9,.0f}  (short {xr['p_shortfall']:.0%})")
    pd.DataFrame(rows).round(5).to_csv(os.path.join(OUT_DIR, "scenarios.csv"), index=False)
    print("  (average returns are arithmetic, before the compounding drag; Stocks include our share of the strategy's alpha)")

    # --- x projection ---
    splits = {"Plan-doc baseline": base, "Recommended (best avg rank)": rec, f"Risk-limited (P(short) <= {config.MAX_SHORTFALL:.0%})": low_risk}
    for m in metrics:
        splits[f"{names[m]} (MC, bounds)"] = picks[f"mc:{m}:bounds"]
        if picks[f"mc:{m}:free"] != picks[f"mc:{m}:bounds"]:
            splits[f"{names[m]} (MC, no bounds)"] = picks[f"mc:{m}:free"]
    for m in metrics:
        if picks[f"bt:{m}:bounds"] not in splits.values():
            splits[f"{names[m]} (backtest, bounds)"] = picks[f"bt:{m}:bounds"]
    spec_rows = []
    futures = [("All futures (Monte Carlo)", None)] + [(n, s) for n, s in zip(config.SCENARIOS, slices)]
    for sp, i in splits.items():
        for fut, sl in futures:
            v = v_mc[:, i] if sl is None else v_mc[sl[0]:sl[1], i]
            spec_rows.append({"split": sp, "bonds": w[i, 0], "funds": w[i, 1], "stocks": w[i, 2], "scenario": fut, "n": len(v),
                              **x_stats(v), "x_median_after_flex": x_stats(v, True)["x_median"]})
        spec_rows.append({"split": sp, "bonds": w[i, 0], "funds": w[i, 1], "stocks": w[i, 2], "scenario": "Real-history stretches (backtest)",
                          "n": len(v_bt), **x_stats(v_bt[:, i]), "x_median_after_flex": x_stats(v_bt[:, i], True)["x_median"]})
    # named historical replays for the recommended split
    ends = h.index[MONTHS - 1:]
    replays = {"worst stretch": int(np.argmin(v_bt[:, rec])), "best stretch": int(np.argmax(v_bt[:, rec]))}
    for lbl, end in {"6y ending 2002-10 (dot-com bust)": "2002-10", "6y ending 2009-02 (financial crisis)": "2009-02",
                     "6y ending 2020-03 (COVID crash)": "2020-03", "6y ending 2022-09 (2022 bear)": "2022-09",
                     "latest 6y": str(ends[-1])[:7]}.items():
        hit = np.where(ends.strftime("%Y-%m") == end)[0]
        if len(hit):
            replays[lbl] = int(hit[0])
    print(f"\nREPLAYS OF REAL HISTORY, recommended split {label(w[rec])} (stocks before 2011 are modeled)")
    for lbl, s in replays.items():
        val = v_bt[s, rec]
        xv = max(val - RESERVE, 0)
        print(f"  {lbl:38} {h.index[s]:%Y-%m} to {ends[s]:%Y-%m}: portfolio {val:>9,.0f}   x {xv:>9,.0f}")
        spec_rows.append({"split": "Recommended (best avg rank)", "bonds": w[rec, 0], "funds": w[rec, 1], "stocks": w[rec, 2],
                          "scenario": f"Replay {lbl} [{h.index[s]:%Y-%m} to {ends[s]:%Y-%m}]", "n": 1, "x_mean": xv, "x_median": xv,
                          "p_shortfall": float(val < RESERVE), "value_median": val, "x_median_after_flex": xv * (1 - config.FLEX_PCT)})
    xp = pd.DataFrame(spec_rows)
    xp.round(4).to_csv(os.path.join(OUT_DIR, "x_projection.csv"), index=False)

    print(f"\nx = PORTFOLIO IN {config.TARGET_YEAR} MINUS THE {dollars(RESERVE)} RESERVE (before the {config.FLEX_PCT:.0%} flexibility hold-back)")
    print(f"{'split':34}{'B/F/S':>12}{'mean':>10}{'median':>10}{'2.5%':>10}{'25%':>10}{'75%':>10}{'97.5%':>10}  P(short)  surplus@2.5%")
    for sp, i in splits.items():
        r = xp[(xp["split"] == sp) & (xp["scenario"] == "All futures (Monte Carlo)")].iloc[0]
        print(f"{sp:34}{label(w[i]):>12}{r.x_mean:10,.0f}{r.x_median:10,.0f}{r.x_p2_5:10,.0f}{r.x_p25:10,.0f}{r.x_p75:10,.0f}{r.x_p97_5:10,.0f}  {r.p_shortfall:6.1%}  {r.surplus_p2_5:>10,.0f}")
    print(f"\nx for the recommended split {label(w[rec])} by future ({RC:.0%} interval, IQR, median, mean)")
    sub = xp[(xp["split"] == "Recommended (best avg rank)") & (xp["n"] > 1)]
    for _, r in sub.iterrows():
        print(f"  {r.scenario:34} {RC:.0%} [{r.x_range_lo:>9,.0f}, {r.x_range_hi:>9,.0f}]  IQR [{r.x_p25:>9,.0f}, {r.x_p75:>9,.0f}]  median {r.x_median:>9,.0f}  mean {r.x_mean:>9,.0f}  P(short) {r.p_shortfall:5.1%}  (2.5th pct of value minus reserve {r.surplus_p2_5:>+10,.0f})")

    # reserve cost sensitivity
    print(f"\nIf the {config.TARGET_YEAR} Treasury yield differs from the {config.PLANNING_YIELD:.1%} planning rate (recommended split, all futures):")
    for y in (0.02, 0.03, 0.035, 0.04, 0.05):
        res = riskfree_reserve(y)
        x = np.maximum(v_mc[:, rec] - res, 0)
        print(f"  yield {y:.1%}: reserve {res:>9,.0f}   x median {np.median(x):>9,.0f}   95% [{np.percentile(x, 2.5):>9,.0f}, {np.percentile(x, 97.5):>9,.0f}]   P(short) {(v_mc[:, rec] < res).mean():5.1%}")

    xp, cgrid, pick, share_p, path, optima = reserve_first(h, X, slices, xp)
    xp, sgrid, spick, sstatic, soptima, sbonds, svpath = steady_split(h, X, slices, xp, w, in_bounds)
    copt = cppi_options(X, slices)
    print_cppi_options(copt, pick_menu(copt))
    print(f"\nWrote {OUT_DIR}")


# ---------- reserve-first: Treasury ladder + growth sleeve, with CPPI ----------

def run_reserve_first(rr, m, path=None, reserve=None, count_future=False):
    """CPPI with a Treasury-ladder floor. rr (paths, months): monthly return of the growth sleeve.
    The safe sleeve is a Treasury ladder earning the planning yield, so it is worth exactly the reserve in 2033 if it holds the
    present value of the reserve (the floor). Each month: growth = clip(m x (portfolio - floor), 0, portfolio), the rest is safe.
    m = 1 is the plain 'fund the reserve first, grow only the surplus' ladder.
    reserve = the amount to reach in 2033 (default RESERVE; pass RESERVE x 1.05 for a 5% buffer).
    count_future = also count the PV of deposits still to come as part of the cushion (they are committed in the case), so the first year
    does not have to be 100% safe.
    Returns (value in 2033, portfolio monthly returns, growth share of the portfolio); path (paths, months+1), if given, is filled with the value."""
    reserve = RESERVE if reserve is None else reserve
    n = rr.shape[0]
    g = (1 + config.PLANNING_YIELD) ** (1 / 12) - 1
    safe, risk = np.zeros(n), np.zeros(n)
    port = np.empty(rr.shape, np.float32)
    share = np.empty(rr.shape, np.float32)
    for t in range(MONTHS):
        floor = reserve / (1 + config.PLANNING_YIELD) ** ((MONTHS - t) / 12)
        tot = safe + risk + DEPOSITS[t]
        risk = np.clip(m * (tot - floor + (FUTURE_PV[t] if count_future else 0.0)), 0, tot)
        safe = tot - risk
        share[:, t] = risk / tot
        if path is not None:
            path[:, t] = tot
        safe = safe * (1 + g)
        risk = risk * (1 + rr[:, t])
        port[:, t] = (safe + risk) / tot - 1
    if path is not None:
        path[:, MONTHS] = safe + risk
    return safe + risk, port, share


def grow_returns(sleeves, s):
    """Growth sleeve = (1-s) Funds + s Stocks. sleeves: (..., 4) [Bonds, Funds, Stocks, Mkt]."""
    return sleeves[..., 1] * (1 - s) + sleeves[..., 2] * s


def reserve_first(h, X, slices, xp):
    """Grid of CPPI strategies (multiplier x growth-sleeve mix); picks one; replays it on real history."""
    em = X[:, :, 3] - RF_M
    shares = np.round(np.arange(0, 1 + 1e-9, config.RISKY_STOCK_STEP), 4)
    rows, store = [], {}
    for m in config.CPPI_MULTIPLIERS:
        for s in shares:
            v, port, share = run_reserve_first(grow_returns(X, s), float(m))
            e = port.astype(np.float64) - RF_M
            r = ratios(e.size, e.sum(), (e ** 2).sum(), (np.minimum(e, 0) ** 2).sum(), (e * em).sum(), em.sum(dtype=np.float64), (em.astype(np.float64) ** 2).sum())
            x = np.maximum(v - RESERVE, 0)
            q = np.percentile(x, [2.5, 25, 50, 75, 97.5, RLO, RHI])
            rows.append({"multiplier": m, "stock_share_of_growth": s, "x_mean": x.mean(), "x_range_lo": q[5], "x_range_hi": q[6], "x_p2_5": q[0],
                         "x_p25": q[1], "x_median": q[2], "x_p75": q[3], "x_p97_5": q[4], "p_shortfall": float((v < RESERVE - 1).mean()),
                         "avg_growth_share": float(share.mean()), "eff_bonds": 1 - float(share.mean()), "eff_funds": float(share.mean()) * (1 - s),
                         "eff_stocks": float(share.mean()) * s, **{k: float(r[k]) for k in ("vol", "beta", "sharpe", "sortino", "treynor")}})
            store[(m, s)] = v
    c = pd.DataFrame(rows)
    c["safe"] = c["p_shortfall"] <= 1 - config.SAFETY_PROB
    metrics = ["x_median", "sharpe", "sortino", "treynor"]
    c["rank_score"] = np.mean([c[m].rank(ascending=False, na_option="bottom") for m in metrics], axis=0)
    c.round(5).to_csv(os.path.join(OUT_DIR, "cppi_grid.csv"), index=False)

    ok = c[c["safe"]]
    rules = ok[(ok["x_range_lo"] >= config.MIN_X_LOW) & (ok["stock_share_of_growth"] <= config.MAX_STOCK_SHARE_OF_GROWTH + 1e-9)]
    pick = int((rules if len(rules) else ok)["rank_score"].idxmin())
    top_x = int(ok["x_median"].idxmax())
    ladder_best = int(c[c["multiplier"] == 1]["rank_score"].idxmin())
    rule_ok = c["safe"] & (c["x_range_lo"] >= config.MIN_X_LOW) & (c["stock_share_of_growth"] <= config.MAX_STOCK_SHARE_OF_GROWTH + 1e-9)
    objectives = {"x_mean": "Max profit (mean x)", "x_median": "Max median x", "sharpe": "Max Sharpe", "sortino": "Max Sortino", "treynor": "Max Treynor"}
    optima = {}
    for col in objectives:
        a = int(c[c["safe"]][col].idxmax())
        b = int(c[rule_ok][col].idxmax()) if rule_ok.any() else a
        optima[col] = (a, b)
    print(f"\nRESERVE-FIRST STRATEGIES (safe sleeve = Treasury ladder worth the {dollars(RESERVE)} reserve in 2033; growth sleeve = Funds/Stocks)")
    print(f"  floor today (PV of the reserve at {config.PLANNING_YIELD:.1%}) {dollars(RESERVE / (1 + config.PLANNING_YIELD) ** (MONTHS / 12))} vs PV of both deposits "
          f"{dollars(sum(a / (1 + config.PLANNING_YIELD) ** ((y - FIRST_YEAR)) for y, a in config.CONTRIBUTIONS.items()))}")
    print(f"  {len(c)} strategies; 'safe' = chance the reserve is short <= {1 - config.SAFETY_PROB:.0%} ({int(c['safe'].sum())} qualify)")

    def line(i):
        r = c.loc[i]
        return (f"{mname(r.multiplier):12} growth sleeve {1 - r.stock_share_of_growth:.0%} funds/{r.stock_share_of_growth:.0%} stocks | x median {r.x_median:>8,.0f}  "
                f"{RC:.0%} range [{r.x_range_lo:>8,.0f}, {r.x_range_hi:>9,.0f}]  P(short) {r.p_shortfall:5.2%} | Sharpe {r.sharpe:5.2f} Sortino {r.sortino:5.2f} "
                f"Treynor {r.treynor:6.3f}  avg split Treasuries {r.eff_bonds:.0%}/Funds {r.eff_funds:.0%}/Stocks {r.eff_stocks:.0%}")
    print(f"  CHOSEN = best average rank (x median, Sharpe, Sortino, Treynor) among safe strategies whose {RC:.0%} range starts at {dollars(config.MIN_X_LOW)} or more "
          f"and stocks <= {config.MAX_STOCK_SHARE_OF_GROWTH:.0%} of the growth sleeve:\n    ", line(pick))
    print(f"  OPTIMAL CPPI SETTING FOR EACH OBJECTIVE ({len(c)} multiplier x mix cells; 'avg split' = time-averaged Treasuries/Funds/Stocks share of the portfolio)")
    for col, nm in objectives.items():
        a, b = optima[col]
        print(f"   {nm}\n      safe only:        {line(a)}")
        if b != a:
            print(f"      + team rules:     {line(b)}")
    print("  plain ladder (m=1), best mix:\n    ", line(ladder_best))
    print("  each multiplier, best mix by median x (safe, stocks within the cap):")
    for m in config.CPPI_MULTIPLIERS:
        sub = c[c["multiplier"] == m]
        sub_ok = sub[sub["safe"] & (sub["stock_share_of_growth"] <= config.MAX_STOCK_SHARE_OF_GROWTH + 1e-9)]
        if len(sub_ok):
            print("     ", line(int(sub_ok["x_median"].idxmax())))

    # chosen strategy: by scenario, co-sponsor range, real-history replay
    m, s = c.at[pick, "multiplier"], c.at[pick, "stock_share_of_growth"]
    v_pick = store[(m, s)]
    flex = 1 - config.FLEX_PCT
    print(f"\nCHOSEN: {mname(m)}, growth sleeve {1 - s:.0%} Funds / {s:.0%} Stocks")
    print(f"  x by future (surplus above the reserve):")
    for k, (name, (a, b)) in enumerate(zip(config.SCENARIOS, slices)):
        st = x_stats(v_mc_slice(v_pick, a, b))
        print(f"    {name:14} median {st['x_median']:>9,.0f}  {RC:.0%} [{st['x_range_lo']:>8,.0f}, {st['x_range_hi']:>9,.0f}]  IQR [{st['x_p25']:>8,.0f}, {st['x_p75']:>9,.0f}]  P(short) {st['p_shortfall']:5.1%}")
    st = x_stats(v_pick)
    print(f"    {'All futures':14} median {st['x_median']:>9,.0f}  mean {st['x_mean']:>9,.0f}  {RC:.0%} [{st['x_range_lo']:>8,.0f}, {st['x_range_hi']:>9,.0f}]  95% [{st['x_p2_5']:>8,.0f}, {st['x_p97_5']:>9,.0f}]  IQR [{st['x_p25']:>8,.0f}, {st['x_p75']:>9,.0f}]  P(short) {st['p_shortfall']:5.2%}")
    fac = np.maximum(v_pick - RESERVE, 0) * flex
    qf = np.percentile(fac, [2.5, 5, RLO, 25, 50, 75, RHI, 95, 97.5])
    print(f"\n  FACILITY CONTRIBUTION after holding back {config.FLEX_PCT:.0%} for flexibility (what to tell co-sponsors in 2031):")
    print(f"    RANGE TO QUOTE: {dollars(qf[2])} to {dollars(qf[6])}  ({RC:.0%} confident the contribution lands inside; {1 - RLO / 100:.0%} confident she can give at least {dollars(qf[2])})")
    print(f"    for reference: 95% confident she can contribute at least {dollars(qf[1])};  95% interval {dollars(qf[0])} to {dollars(qf[8])};  median {dollars(qf[4])}")
    print(f"    middle 50% (IQR)  {dollars(qf[3])} to {dollars(qf[5])}   |   mean {dollars(fac.mean())}")
    infl = (1 + config.INFLATION) ** (config.TARGET_YEAR - 2026)
    print(f"    in today's dollars (deflated {config.INFLATION:.1%}/yr to 2026): {1 - RLO / 100:.0%} confident at least {dollars(qf[2] / infl)}, median {dollars(qf[4] / infl)}")

    # real-history replay of the chosen strategy (stocks before 2011 are modeled)
    sleeves = h[NAMES + ["Mkt"]].to_numpy()
    rr_h = grow_returns(sleeves, s)
    starts = np.arange(len(h) - MONTHS + 1)
    v_h, _, _ = run_reserve_first(rr_h[starts[:, None] + np.arange(MONTHS)], m)
    sh = x_stats(v_h)
    print(f"\n  REAL-HISTORY REPLAY ({len(v_h)} six-year stretches): x median {sh['x_median']:,.0f}, 95% [{sh['x_p2_5']:,.0f}, {sh['x_p97_5']:,.0f}], "
          f"P(short) {sh['p_shortfall']:.1%}, worst stretch x {max(v_h.min() - RESERVE, 0):,.0f} (value {v_h.min():,.0f})")
    ends = h.index[MONTHS - 1:]
    for lbl, end in {"dot-com bust": "2002-10", "financial crisis": "2009-02", "COVID crash": "2020-03", "2022 bear": "2022-09"}.items():
        hit = np.where(ends.strftime("%Y-%m") == end)[0]
        if len(hit):
            j = int(hit[0])
            print(f"    6y ending {end} ({lbl}): x {max(v_h[j] - RESERVE, 0):>9,.0f}   portfolio {v_h[j]:>9,.0f}")

    # add to the x projection table
    def add(label_, v_mc_, v_hist_):
        out = []
        for fut, sl in [("All futures (Monte Carlo)", None)] + list(zip(config.SCENARIOS, slices)):
            v = v_mc_ if sl is None else v_mc_[sl[0]:sl[1]]
            out.append({"split": label_, "scenario": fut, "n": len(v), **x_stats(v), "x_median_after_flex": x_stats(v, True)["x_median"]})
        out.append({"split": label_, "scenario": "Real-history stretches (backtest)", "n": len(v_hist_), **x_stats(v_hist_),
                    "x_median_after_flex": x_stats(v_hist_, True)["x_median"]})
        return out
    def tag(i):
        r = c.loc[i]
        return f"Reserve-first: {mname(r.multiplier)}, growth {1 - r.stock_share_of_growth:.0%}F/{r.stock_share_of_growth:.0%}S"
    new = add(tag(pick) + " [chosen]", v_pick, v_h)
    for i in {top_x, ladder_best} - {pick}:
        sub_h, _, _ = run_reserve_first(grow_returns(sleeves, c.at[i, "stock_share_of_growth"])[starts[:, None] + np.arange(MONTHS)], c.at[i, "multiplier"])
        new += add(tag(i), store[(c.at[i, "multiplier"], c.at[i, "stock_share_of_growth"])], sub_h)
    xp = pd.concat([xp, pd.DataFrame(new)], ignore_index=True)
    xp.round(4).to_csv(os.path.join(OUT_DIR, "x_projection.csv"), index=False)

    # value and growth-share paths of the chosen strategy, for the chart
    path = np.empty((len(X), MONTHS + 1))
    _, _, share_p = run_reserve_first(grow_returns(X, s), m, path)
    print(f"\n  GLIDE PATH OF THE CHOSEN STRATEGY: median share of the portfolio at the start of each year (it moves with the market)")
    print(f"    {'year':6}{'Treasuries':>12}{'Funds':>9}{'Stocks':>9}   {'growth share 25th-75th pct':>28}")
    for k in range(6):
        gs = share_p[:, 12 * k]
        med = float(np.median(gs))
        lo, hi = np.percentile(gs, [25, 75])
        print(f"    {FIRST_YEAR + k:<6}{1 - med:>12.0%}{med * (1 - s):>9.0%}{med * s:>9.0%}   {lo:>14.0%} to {hi:.0%}")
    return xp, c, pick, share_p, path, optima


# ---------- zero-risk CPPI options: extra reserve buffer, committed deposit counted, start mix ----------

def cppi_options(X, slices):
    """Every multiplier x growth mix x buffer, with and without counting the committed 2028 deposit as a safe asset.
    Writes cppi_options_grid.csv and returns the table. x is measured above the buffered reserve."""
    em = X[:, :, 3] - RF_M
    shares = np.round(np.arange(0, 1 + 1e-9, config.RISKY_STOCK_STEP), 4)
    rows = []
    for buf in config.CPPI_BUFFERS:
        res = RESERVE * (1 + buf)
        for count in (False, True):
            for m in config.CPPI_MULTIPLIERS:
                for s in shares:
                    v, port, share = run_reserve_first(grow_returns(X, s), float(m), reserve=res, count_future=count)
                    e = port.astype(np.float64) - RF_M
                    r = ratios(e.size, e.sum(), (e ** 2).sum(), (np.minimum(e, 0) ** 2).sum(), (e * em).sum(), em.sum(dtype=np.float64), (em.astype(np.float64) ** 2).sum())
                    x = np.maximum(v - res, 0)
                    q = np.percentile(x, [2.5, 25, 50, 75, 97.5, RLO, RHI])
                    jan = share[:, ::12]                                   # growth share each January 2027..2032
                    g0 = float(jan[:, 0].mean())
                    row = {"buffer": buf, "reserve": res, "count_deposit": count, "multiplier": m, "stock_share_of_growth": s,
                           "start_bonds": 1 - g0, "start_funds": g0 * (1 - s), "start_stocks": g0 * s,
                           "x_mean": x.mean(), "x_median": q[2], "x_range_lo": q[5], "x_range_hi": q[6], "x_p25": q[1], "x_p75": q[3],
                           "x_p2_5": q[0], "x_p97_5": q[4], "p_shortfall": float((v < res - 1).mean()),
                           "chg_2028": float(np.abs(jan[:, 1] - jan[:, 0]).mean()), "chg_after": float(np.abs(np.diff(jan[:, 1:], axis=1)).mean()),
                           **{k: float(r[k]) for k in ("vol", "beta", "sharpe", "sortino", "treynor")}}
                    for k in range(jan.shape[1]):
                        row[f"bonds_{FIRST_YEAR + k}"] = float(1 - np.median(jan[:, k]))
                    rows.append(row)
    c = pd.DataFrame(rows)
    c["zero_risk"] = c["p_shortfall"] <= config.CPPI_ZERO_RISK
    c.round(5).to_csv(os.path.join(OUT_DIR, "cppi_options_grid.csv"), index=False)
    return c


def pick_menu(c):
    """One option per multiplier (so per starting Bonds weight): buffered reserve, committed deposit counted, zero risk,
    stocks within the cap of the growth sleeve, best median x. Returns row labels A, B, C... as {letter: row index}, safest start first."""
    ok = c[(c["buffer"] == config.CPPI_BUFFER) & c["count_deposit"] & c["zero_risk"] & (c["stock_share_of_growth"] <= config.MAX_STOCK_SHARE_OF_GROWTH + 1e-9)]
    best = ok.sort_values(["x_median", "x_range_lo"], ascending=False).groupby("multiplier").head(1).sort_values("multiplier")
    best = best[best["start_bonds"] > 0.2]                                  # a start under 20% bonds is not an 'option' for a team that wants safety
    return {chr(65 + i): idx for i, idx in enumerate(best.index)}


def print_cppi_options(c, menu):
    def line(i):
        r = c.loc[i]
        return (f"CPPI m={r.multiplier:<3g} start Bonds {r.start_bonds:4.0%} / Funds {r.start_funds:4.0%} / Stocks {r.start_stocks:4.0%} | x median {r.x_median:>8,.0f}  "
                f"{RC:.0%} range [{r.x_range_lo:>8,.0f}, {r.x_range_hi:>9,.0f}]  P(short) {r.p_shortfall:6.3%} | Sharpe {r.sharpe:4.2f} Sortino {r.sortino:4.2f} Treynor {r.treynor:5.3f}")
    res = RESERVE * (1 + config.CPPI_BUFFER)
    print(f"\nZERO-RISK CPPI OPTIONS with a {config.CPPI_BUFFER:.0%} buffer: reserve target {dollars(res)} instead of {dollars(RESERVE)}; x is what is left above the buffered amount")
    print(f"  {len(c)} runs = buffers {config.CPPI_BUFFERS} x deposit counted yes/no x {len(config.CPPI_MULTIPLIERS)} multipliers x {c['stock_share_of_growth'].nunique()} stock shares; "
          f"zero risk = reserve short in <= {config.CPPI_ZERO_RISK:.2%} of futures")
    base = c[(c["buffer"] == config.CPPI_BUFFER) & ~c["count_deposit"] & c["zero_risk"] & (c["stock_share_of_growth"] <= config.MAX_STOCK_SHARE_OF_GROWTH + 1e-9)]
    if len(base):
        i = int(base["x_median"].idxmax())
        print(f"  STANDARD CPPI (2028 deposit not counted): every setting starts {c.loc[i, 'start_bonds']:.0%} Bonds in 2027. Best zero-risk:\n    ", line(i))
    print("  OPTIONS (2028 deposit counted as a safe asset; growth sleeve at the stock cap; one per multiplier = one per starting Bonds weight):")
    for letter, i in menu.items():
        r = c.loc[i]
        path = "  ".join(f"{FIRST_YEAR + k}: {r[f'bonds_{FIRST_YEAR + k}']:.0%}" for k in range(MONTHS // 12))
        print(f"    {letter}  {line(i)}\n       median Bonds weight each January  {path}   | typical yearly move after 2028: {r.chg_after * 100:.1f} points")
    print(f"  what the {config.CPPI_BUFFER:.0%} buffer costs at the same settings (median x, no buffer -> buffer):")
    for letter, i in menu.items():
        r = c.loc[i]
        nb = c[(c["buffer"] == 0) & c["count_deposit"] & (c["multiplier"] == r.multiplier) & (c["stock_share_of_growth"] == r.stock_share_of_growth)].iloc[0]
        print(f"    {letter} m={r.multiplier:g}: {nb.x_median:>8,.0f} -> {r.x_median:>8,.0f}  ({r.x_median - nb.x_median:+,.0f})")
    print("  NOTE: counting the 2028 deposit assumes the $150k really arrives (the case timeline says it does). If it did not, no allocation could fund the reserve anyway.")


def mname(m):
    return "ladder (m=1)" if m == 1 else f"CPPI m={m:g}"


def v_mc_slice(v, a, b):
    return v[a:b]


# ---------- steady split: one split now, nudged by at most ADJUST_STEP each January ----------

def bond_limits(w0):
    """Range of the Bonds weight that keeps Bonds, Funds and Stocks inside the team bounds while the Funds:Stocks ratio stays fixed."""
    rs = w0[:, 2] / (w0[:, 1] + w0[:, 2])
    (bl, bh), (fl, fh), (sl, sh) = config.BOUNDS
    g_hi = np.minimum(fh / (1 - rs), sh / rs)           # most the non-bond part may be
    g_lo = np.maximum(fl / (1 - rs), sl / rs)           # least the non-bond part may be
    return np.maximum(bl, 1 - g_hi), np.minimum(bh, 1 - g_lo), rs


def adaptive_run(Xt, w0, f_lo, f_hi, track=False):
    """Monthly-rebalanced Bonds/Funds/Stocks. Xt (months, paths, [Bonds, Funds, Stocks, Mkt]); w0 (splits, 3) = the split on day one.
    Each January from the second year: funded ratio = (portfolio + deposit) / PV of the reserve; below f_lo Bonds +step, above f_hi Bonds -step.
    Returns value in 2033 (paths, splits), annualized ratios, and (if track) the Bonds weight each January and the value path."""
    n, a = Xt.shape[1], len(w0)
    b_lo, b_hi, rs = bond_limits(w0)
    b = np.tile(w0[:, 0], (n, 1))
    v = np.zeros((n, a))
    sums = np.zeros((4, a))
    bonds_path = np.empty((MONTHS // 12, n, a)) if track else None
    vpath = np.empty((MONTHS + 1, n, a)) if track else None
    for t in range(MONTHS):
        floor = RESERVE / (1 + config.PLANNING_YIELD) ** ((MONTHS - t) / 12)
        tot = v + DEPOSITS[t]
        if t % 12 == 0:
            if t > 0:
                f = tot / floor
                b = np.clip(b + config.ADJUST_STEP * ((f < f_lo).astype(float) - (f > f_hi)), b_lo, b_hi)
            if track:
                bonds_path[t // 12] = b
        if track:
            vpath[t] = tot
        x = Xt[t]
        r = b * x[:, 0:1] + (1 - b) * ((1 - rs) * x[:, 1:2] + rs * x[:, 2:3])
        v = tot * (1 + r)
        e = r - RF_M
        sums[0] += e.sum(0)
        sums[1] += (e * e).sum(0)
        sums[2] += (np.minimum(e, 0) ** 2).sum(0)
        sums[3] += (e * (x[:, 3:4] - RF_M)).sum(0)
    if track:
        vpath[MONTHS] = v
    em = Xt[:, :, 3] - RF_M
    return v, ratios(n * MONTHS, sums[0], sums[1], sums[2], sums[3], em.sum(), (em ** 2).sum()), bonds_path, vpath


def steady_split(h, X, slices, xp, w, in_bounds):
    """Search every starting split inside the team bounds x every nudge rule; pick one; replay it on real history."""
    w0 = w[in_bounds]
    Xt_all = np.ascontiguousarray(X.astype(np.float64).transpose(1, 0, 2))
    Xt = np.ascontiguousarray(Xt_all[:, ::len(X) // config.STEADY_SEARCH_PATHS, :])
    variants = [("static (no nudges)", -np.inf, np.inf)] + [(f"nudge if funded ratio < {lo:g} or > {hi:g}", lo, hi)
                                                           for lo in config.FUNDED_LO for hi in config.FUNDED_HI if lo < hi]
    rows = []
    for name, lo, hi in variants:
        for c0 in range(0, len(w0), 40):
            wc = w0[c0:c0 + 40]
            v, r, _, _ = adaptive_run(Xt, wc, lo, hi)
            x = np.maximum(v - RESERVE, 0)
            q = np.percentile(x, [2.5, 25, 50, 75, 97.5, RLO, RHI], axis=0)
            for j in range(len(wc)):
                rows.append({"variant": name, "f_lo": lo, "f_hi": hi, "bonds": wc[j, 0], "funds": wc[j, 1], "stocks": wc[j, 2],
                             "x_mean": x[:, j].mean(), "x_range_lo": q[5, j], "x_range_hi": q[6, j], "x_p2_5": q[0, j], "x_p25": q[1, j],
                             "x_median": q[2, j], "x_p75": q[3, j], "x_p97_5": q[4, j], "p_shortfall": float((v[:, j] < RESERVE).mean()),
                             **{k: float(r[k][j]) for k in ("vol", "beta", "sharpe", "sortino", "treynor")}})
    c = pd.DataFrame(rows)
    c["safe"] = c["p_shortfall"] <= 1 - config.SAFETY_PROB
    c["rules"] = c["safe"] & (c["x_range_lo"] >= config.MIN_X_LOW)
    pool = c[c["rules"]] if c["rules"].any() else c[c["safe"]]
    metrics = ["x_median", "sharpe", "sortino", "treynor"]
    c["rank_score"] = np.nan
    c.loc[pool.index, "rank_score"] = np.mean([pool[m].rank(ascending=False, na_option="bottom") for m in metrics], axis=0)
    pick = int(c["rank_score"].idxmin())
    static = c[c["variant"] == variants[0][0]]
    static_pool = static[static["rules"]] if static["rules"].any() else static[static["safe"]]
    static_best = int(static_pool["x_median"].idxmax()) if len(static_pool) else int(static["p_shortfall"].idxmin())

    def line(i):
        r = c.loc[i]
        return (f"Bonds {r.bonds:5.1%} / Funds {r.funds:5.1%} / Stocks {r.stocks:5.1%} | {r.variant:40} | x median {r.x_median:>8,.0f}  "
                f"{RC:.0%} range [{r.x_range_lo:>8,.0f}, {r.x_range_hi:>9,.0f}]  P(short) {r.p_shortfall:5.2%} | Sharpe {r.sharpe:5.2f} Sortino {r.sortino:5.2f} Treynor {r.treynor:6.3f}")
    print(f"\nSTEADY SPLIT: one split now, Bonds weight nudged at most {config.ADJUST_STEP:.0%} a year (every January from {FIRST_YEAR + 1}), Funds:Stocks ratio fixed")
    print(f"  {len(c)} combinations ({len(w0)} starting splits in the team bounds x {len(variants)} nudge rules, {Xt.shape[1]:,} futures each); safe = reserve short in <= {1 - config.SAFETY_PROB:.0%} of futures "
          f"({int(c['safe'].sum())} qualify, {int(c['rules'].sum())} also have a {RC:.0%} range starting at {dollars(config.MIN_X_LOW)}+)")
    print("  CHOSEN (best average rank of median x, Sharpe, Sortino, Treynor among those):\n    ", line(pick))
    print("  best static split (no nudges), same rules:\n    ", line(static_best))
    print("  OPTIMUM FOR EACH OBJECTIVE")
    objectives = {"x_mean": "Max profit (mean x)", "x_median": "Max median x", "sharpe": "Max Sharpe", "sortino": "Max Sortino", "treynor": "Max Treynor"}
    optima = {}
    for col, nm in objectives.items():
        a_ = int(c[c["safe"]][col].idxmax())
        b_ = int(pool[col].idxmax())
        optima[col] = (a_, b_)
        print(f"   {nm}\n      safe only:    {line(a_)}")
        if b_ != a_:
            print(f"      + {RC:.0%} range rule: {line(b_)}")

    # re-run the winner and the best static split on every path, with tracking
    def full(i):
        r = c.loc[i]
        wi = np.array([[r.bonds, r.funds, r.stocks]])
        v, rr_, bp, vp = adaptive_run(Xt_all, wi, r.f_lo, r.f_hi, track=True)
        return v[:, 0], rr_, bp[:, :, 0], vp[:, :, 0]
    v_pick, r_pick, bonds_p, vpath = full(pick)
    v_static, _, _, _ = full(static_best)
    r = c.loc[pick]
    print(f"\nCHOSEN: start Bonds {r.bonds:.1%} / Funds {r.funds:.1%} / Stocks {r.stocks:.1%}; rule: {r.variant}")
    print(f"  full run ({len(v_pick):,} futures): x median {np.median(np.maximum(v_pick - RESERVE, 0)):,.0f}, P(short) {(v_pick < RESERVE).mean():.2%}")
    print(f"  nudge size actually used: Bonds weight at the start of each year (25th / median / 75th pct, min-max)")
    prev = None
    for k in range(MONTHS // 12):
        bk = bonds_p[k]
        lo_, md, hi_ = np.percentile(bk, [25, 50, 75])
        chg = "" if prev is None else f"   moved from last year: up {(bk > prev + 1e-9).mean():4.0%}, down {(bk < prev - 1e-9).mean():4.0%}, same {(abs(bk - prev) <= 1e-9).mean():4.0%}"
        print(f"    {FIRST_YEAR + k}: {lo_:5.1%} / {md:5.1%} / {hi_:5.1%}   ({bk.min():5.1%} - {bk.max():5.1%}){chg}")
        prev = bk
    print(f"  x by future (surplus above the reserve):")
    for name, (a_, b_) in zip(config.SCENARIOS, slices):
        st = x_stats(v_pick[a_:b_])
        print(f"    {name:14} median {st['x_median']:>9,.0f}  {RC:.0%} [{st['x_range_lo']:>8,.0f}, {st['x_range_hi']:>9,.0f}]  IQR [{st['x_p25']:>8,.0f}, {st['x_p75']:>9,.0f}]  P(short) {st['p_shortfall']:5.1%}")
    st = x_stats(v_pick)
    print(f"    {'All futures':14} median {st['x_median']:>9,.0f}  mean {st['x_mean']:>9,.0f}  {RC:.0%} [{st['x_range_lo']:>8,.0f}, {st['x_range_hi']:>9,.0f}]  95% [{st['x_p2_5']:>8,.0f}, {st['x_p97_5']:>9,.0f}]  IQR [{st['x_p25']:>8,.0f}, {st['x_p75']:>9,.0f}]  P(short) {st['p_shortfall']:5.2%}")
    fac = np.maximum(v_pick - RESERVE, 0) * (1 - config.FLEX_PCT)
    qf = np.percentile(fac, [2.5, 5, RLO, 25, 50, 75, RHI, 95, 97.5])
    print(f"\n  FACILITY CONTRIBUTION after holding back {config.FLEX_PCT:.0%} for flexibility (what to tell co-sponsors in 2031):")
    print(f"    RANGE TO QUOTE: {dollars(qf[2])} to {dollars(qf[6])}  ({RC:.0%} confident the contribution lands inside; {1 - RLO / 100:.0%} confident she can give at least {dollars(qf[2])})")
    print(f"    for reference: 95% confident at least {dollars(qf[1])};  95% interval {dollars(qf[0])} to {dollars(qf[8])};  median {dollars(qf[4])};  middle 50% {dollars(qf[3])} to {dollars(qf[5])}")
    infl = (1 + config.INFLATION) ** (config.TARGET_YEAR - 2026)
    print(f"    in today's dollars (deflated {config.INFLATION:.1%}/yr to 2026): {1 - RLO / 100:.0%} confident at least {dollars(qf[2] / infl)}, median {dollars(qf[4] / infl)}")

    # replay on real history (stocks before 2011 are modeled)
    sleeves = h[NAMES + ["Mkt"]].to_numpy()
    starts = np.arange(len(h) - MONTHS + 1)
    Xh = np.ascontiguousarray(sleeves[starts[:, None] + np.arange(MONTHS)].transpose(1, 0, 2))
    def hist(i):
        rr_ = c.loc[i]
        return adaptive_run(Xh, np.array([[rr_.bonds, rr_.funds, rr_.stocks]]), rr_.f_lo, rr_.f_hi)[0][:, 0]
    v_h, v_hs = hist(pick), hist(static_best)
    sh = x_stats(v_h)
    print(f"\n  REAL-HISTORY REPLAY ({len(v_h)} six-year stretches): x median {sh['x_median']:,.0f}, {RC:.0%} [{sh['x_range_lo']:,.0f}, {sh['x_range_hi']:,.0f}], "
          f"P(short) {sh['p_shortfall']:.1%}, worst stretch x {max(v_h.min() - RESERVE, 0):,.0f} (value {v_h.min():,.0f})")
    ends = h.index[MONTHS - 1:]
    for lbl, end in {"dot-com bust": "2002-10", "financial crisis": "2009-02", "COVID crash": "2020-03", "2022 bear": "2022-09"}.items():
        hit = np.where(ends.strftime("%Y-%m") == end)[0]
        if len(hit):
            j = int(hit[0])
            print(f"    6y ending {end} ({lbl}): x {max(v_h[j] - RESERVE, 0):>9,.0f}   portfolio {v_h[j]:>9,.0f}")

    def add(label_, v_mc_, v_hist_, i):
        out = []
        ri = c.loc[i]
        for fut, sl in [("All futures (Monte Carlo)", None)] + list(zip(config.SCENARIOS, slices)):
            v = v_mc_ if sl is None else v_mc_[sl[0]:sl[1]]
            out.append({"split": label_, "bonds": ri.bonds, "funds": ri.funds, "stocks": ri.stocks, "scenario": fut, "n": len(v), **x_stats(v),
                        "x_median_after_flex": x_stats(v, True)["x_median"]})
        out.append({"split": label_, "bonds": ri.bonds, "funds": ri.funds, "stocks": ri.stocks, "scenario": "Real-history stretches (backtest)", "n": len(v_hist_),
                    **x_stats(v_hist_), "x_median_after_flex": x_stats(v_hist_, True)["x_median"]})
        return out
    new = add(f"Steady split [chosen]: {r.bonds:.1%}/{r.funds:.1%}/{r.stocks:.1%}, {r.variant}", v_pick, v_h, pick)
    if static_best != pick:
        rs_ = c.loc[static_best]
        new += add(f"Steady split, no nudges: {rs_.bonds:.1%}/{rs_.funds:.1%}/{rs_.stocks:.1%}", v_static, v_hs, static_best)
    xp = pd.concat([xp, pd.DataFrame(new)], ignore_index=True)
    xp.round(4).to_csv(os.path.join(OUT_DIR, "x_projection.csv"), index=False)
    keep = c[c["variant"].isin([r.variant, variants[0][0]])]
    keep.round(5).to_csv(os.path.join(OUT_DIR, "steady_grid.csv"), index=False)
    return xp, c, pick, static_best, optima, bonds_p, vpath


if __name__ == "__main__":
    main()
