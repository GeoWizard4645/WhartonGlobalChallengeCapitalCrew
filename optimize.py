# Backtests and Monte Carlos every bonds / funds / stocks split (2.5% grid) for the Laura Gao plan:
# $300k in 2027 and $150k in 2028 grow to the start of 2033, where a Treasury-ladder reserve for the ten $50k
# payments is set aside and what is left over is x, the extra contribution we can make in 2033.
#
# Stocks = the team's 50/50 momentum + Magic Formula strategy (output/stock_sleeve.csv, written by quant.run).
# Bonds and Funds = the long-history fund proxies in config.BUCKETS. Settings: the ALLOCATION OPTIMIZER block of config.py.
#
# Run: .venv/bin/python optimize.py        (needs numpy, pandas, matplotlib; ~2 minutes)
# Writes output/allocation/: grid.csv, scenarios.csv, x_projection.csv, heatmaps_montecarlo.png,
#                            heatmaps_backtest.png, x_projection.png
import os

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap  # noqa: E402

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
BOUNDS = np.array(config.BOUNDS)

# chart colors (dataviz reference palette: blue sequential ramp, neutral ink)
INK, INK2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#d9d8d3"
BLUE = "#2a78d6"
RAMP = LinearSegmentedColormap.from_list("blue", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])


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
    return {"x_mean": x.mean(), "x_median": q[2], "x_p2_5": q[0], "x_p25": q[1], "x_p75": q[3], "x_p97_5": q[4],
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
    print(f"\nx for the recommended split {label(w[rec])} by future (95% interval, IQR, median, mean)")
    sub = xp[(xp["split"] == "Recommended (best avg rank)") & (xp["n"] > 1)]
    for _, r in sub.iterrows():
        print(f"  {r.scenario:34} 95% [{r.x_p2_5:>9,.0f}, {r.x_p97_5:>9,.0f}]  IQR [{r.x_p25:>9,.0f}, {r.x_p75:>9,.0f}]  median {r.x_median:>9,.0f}  mean {r.x_mean:>9,.0f}  P(short) {r.p_shortfall:5.1%}  (2.5th pct of value minus reserve {r.surplus_p2_5:>+10,.0f})")

    # reserve cost sensitivity
    print(f"\nIf the {config.TARGET_YEAR} Treasury yield differs from the {config.PLANNING_YIELD:.1%} planning rate (recommended split, all futures):")
    for y in (0.02, 0.03, 0.035, 0.04, 0.05):
        res = riskfree_reserve(y)
        x = np.maximum(v_mc[:, rec] - res, 0)
        print(f"  yield {y:.1%}: reserve {res:>9,.0f}   x median {np.median(x):>9,.0f}   95% [{np.percentile(x, 2.5):>9,.0f}, {np.percentile(x, 97.5):>9,.0f}]   P(short) {(v_mc[:, rec] < res).mean():5.1%}")

    charts(g, w, in_bounds, picks, rec, base, xp, X, slices)
    print(f"\nWrote {OUT_DIR}")


# ---------- charts ----------

def style(ax):
    ax.set_facecolor(SURFACE)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.tick_params(colors=INK2, labelsize=8)


def heatmaps(g, w, in_bounds, tag, title, path, rec):
    n = round(1 / config.OPT_STEP)
    panels = [("profit", "Profit: mean gain by 2033 ($k)", 1e-3), ("sharpe", "Sharpe ratio", 1), ("treynor", "Treynor ratio", 1), ("sortino", "Sortino ratio", 1)]
    fig, axes = plt.subplots(2, 2, figsize=(11.5, 10.6), facecolor=SURFACE)
    bi, si = np.round(w[:, 0] * n).astype(int), np.round(w[:, 2] * n).astype(int)
    inb = np.full((n + 1, n + 1), 0.0)
    inb[si[in_bounds], bi[in_bounds]] = 1.0
    for ax, (m, ttl, scale) in zip(axes.flat, panels):
        z = np.full((n + 1, n + 1), np.nan)
        vals = g[f"{tag}_{m}"].to_numpy() * scale
        z[si, bi] = vals
        lo, hi = np.nanpercentile(vals, [1 if m == "profit" else 10, 99])
        im = ax.imshow(z, origin="lower", extent=[-0.5 / n * 100, 100 + 0.5 / n * 100] * 2, cmap=RAMP, vmin=lo, vmax=hi, interpolation="nearest")
        ax.contour(np.linspace(0, 100, n + 1), np.linspace(0, 100, n + 1), inb, levels=[0.5], colors=[INK], linewidths=1.1, linestyles="--")
        free = int(np.nanargmax(vals))
        bnd = int(np.nanargmax(np.where(in_bounds, vals, -np.inf)))
        ax.scatter(w[free, 0] * 100, w[free, 2] * 100, marker="*", s=230, c="white", edgecolors=INK, linewidths=1.2, zorder=5, clip_on=False)
        ax.scatter(w[bnd, 0] * 100, w[bnd, 2] * 100, marker="D", s=70, c="white", edgecolors=INK, linewidths=1.2, zorder=6)
        ax.scatter(w[rec, 0] * 100, w[rec, 2] * 100, marker="o", s=70, c=INK, edgecolors="white", linewidths=1.0, zorder=7)
        ax.set_xlim(-1, 101)
        ax.set_ylim(-1, 101)
        ax.set_xlabel("Bonds %   (Funds % = 100 - Bonds - Stocks)", color=INK2, fontsize=9)
        ax.set_ylabel("Stocks %", color=INK2, fontsize=9)
        ax.set_title(ttl, color=INK, fontsize=11.5, loc="left", fontweight="bold")
        ax.text(0.99, 0.99, f"★ best overall  {label(w[free])}  ({vals[free]:,.2f})\n◆ best in team bounds  {label(w[bnd])}  ({vals[bnd]:,.2f})",
                transform=ax.transAxes, ha="right", va="top", fontsize=8, color=INK, linespacing=1.5)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.ax.tick_params(colors=INK2, labelsize=8)
        cb.outline.set_edgecolor(GRID)
        ax.set_aspect("equal")
        style(ax)
    fig.suptitle(title, color=INK, fontsize=13.5, fontweight="bold", x=0.02, ha="left")
    fig.text(0.02, 0.925, "Each cell is one Bonds / Funds / Stocks split.  Dashed line = team bounds.\n● = recommended (best average rank of the four, Monte Carlo).  "
             "Colors clipped at the 10th/99th percentile (1st for profit).", color=INK2, fontsize=8.5, ha="left")
    fig.tight_layout(rect=(0, 0, 1, 0.93))
    fig.savefig(path, dpi=140, facecolor=SURFACE)
    plt.close(fig)


def charts(g, w, in_bounds, picks, rec, base, xp, X, slices):
    heatmaps(g, w, in_bounds, "mc", "Monte Carlo: which split earns the most for the risk (30,000 futures, 2027-2033)",
             os.path.join(OUT_DIR, "heatmaps_montecarlo.png"), rec)
    heatmaps(g, w, in_bounds, "bt", "Backtest on real history (1993-2026, every 6-year stretch; stocks before 2011 modeled)",
             os.path.join(OUT_DIR, "heatmaps_backtest.png"), rec)

    # x projection: value fan chart + x range by future for the recommended split
    R = np.einsum("ntj,j->nt", X[:, :, :3], w[rec].astype(np.float32))
    v = np.zeros(len(X))
    path = np.zeros((len(X), MONTHS + 1))
    for t in range(MONTHS):
        v = (v + DEPOSITS[t]) * (1 + R[:, t])
        path[:, t + 1] = v
    path[:, 0] = DEPOSITS[0]
    yrs = FIRST_YEAR + np.arange(MONTHS + 1) / 12
    pc = np.percentile(path, [2.5, 25, 50, 75, 97.5], axis=0)
    fig, (a1, a2) = plt.subplots(1, 2, figsize=(13, 5.4), facecolor=SURFACE, gridspec_kw={"width_ratios": [1, 1.15]})
    a1.fill_between(yrs, pc[0] / 1e3, pc[4] / 1e3, color="#cde2fb", label="95% of futures", lw=0)
    a1.fill_between(yrs, pc[1] / 1e3, pc[3] / 1e3, color="#6da7ec", label="middle 50%", lw=0)
    a1.plot(yrs, pc[2] / 1e3, color="#184f95", lw=2, label="median")
    a1.axhline(RESERVE / 1e3, color=INK, lw=1, ls="--")
    a1.text(yrs[1], RESERVE / 1e3 + 8, f"reserve for the 10 payments ${RESERVE / 1e3:,.0f}k", color=INK, fontsize=8.5, bbox=dict(facecolor=SURFACE, edgecolor="none", pad=1.5))
    a1.set_title(f"Portfolio value, split {label(w[rec])} (Bonds/Funds/Stocks)", color=INK, fontsize=11.5, loc="left", fontweight="bold")
    a1.set_ylabel("$ thousands", color=INK2, fontsize=9)
    a1.legend(loc="upper left", fontsize=8.5, frameon=False, labelcolor=INK2)
    a1.grid(color=GRID, lw=0.6)
    style(a1)

    sub = xp[(xp["split"] == "Recommended (best avg rank)") & (xp["n"] > 1) & ~xp["scenario"].str.startswith("Real-history")]
    sub = sub.iloc[::-1]
    y = np.arange(len(sub))
    a2.hlines(y, sub.x_p2_5 / 1e3, sub.x_p97_5 / 1e3, color="#86b6ef", lw=1.6)
    a2.hlines(y, sub.x_p25 / 1e3, sub.x_p75 / 1e3, color="#2a78d6", lw=7)
    a2.scatter(sub.x_median / 1e3, y, color="white", edgecolors=INK, s=36, zorder=4)
    for yi, (_, r) in zip(y, sub.iterrows()):
        a2.text(r.x_p97_5 / 1e3 + 6, yi, f"median ${r.x_median / 1e3:,.0f}k", va="center", fontsize=8, color=INK2)
    a2.set_yticks(y, [f"{s} (n={n:,})" if s.startswith("All") else s for s, n in zip(sub.scenario, sub.n)], fontsize=8.5, color=INK2)
    a2.set_xlabel("x = extra contribution available in 2033, $ thousands (95% range, middle 50%, median)", color=INK2, fontsize=9)
    a2.set_title("How much x depends on the market we get", color=INK, fontsize=11.5, loc="left", fontweight="bold")
    a2.set_xlim(left=-10)
    a2.grid(axis="x", color=GRID, lw=0.6)
    style(a2)
    fig.tight_layout()
    fig.savefig(os.path.join(OUT_DIR, "x_projection.png"), dpi=140, facecolor=SURFACE)
    plt.close(fig)


if __name__ == "__main__":
    main()
