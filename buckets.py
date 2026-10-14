# Searches bucket splits (bonds / funds / stocks) with Monte Carlo and ranks them
# on risk vs reward. Every split is run through the SAME random paths.
# Run: python3 buckets.py
import config
from utils import *

names = list(config.BUCKETS)
dates, prices = load_prices(config.ALL_TICKERS)
rows = bucket_rows(prices)
blocks = monthly_blocks(rows)
paths = make_paths(len(blocks), config.N_PATHS, config.HORIZON_YEARS * 12)


def evaluate(weights):
    res = simulate(weights, blocks, paths)
    n = len(paths)
    return {
        "w": weights,
        "cagr": percentile(res["cagrs"], 0.50),
        "vol": res["vol"],
        "sharpe": res["sharpe"],
        "var": hist_var(res["ret_1y"], 0.95),
        "cvar": hist_cvar(res["ret_1y"], 0.95),
        "ploss": sum(f < 1 for f in res["finals"]) / n,
        "dd95": percentile(res["drawdowns"], 0.95),
    }


def show_header():
    print(f"{'Bonds':>7}{'Funds':>7}{'Stocks':>7} |{'medCAGR':>9}{'vol':>8}{'sharpe':>8}"
          f"{'VaR95 1y':>10}{'CVaR95 1y':>11}{'P(loss)':>9}{'DD95':>8}")


def show(r):
    w = r["w"]
    print(f"{w[0] * 100:6.1f}%{w[1] * 100:6.1f}%{w[2] * 100:6.1f}% |{pct(r['cagr'], 8)}{pct(r['vol'], 7)}{r['sharpe']:8.2f}"
          f"{pct(r['var'], 9)}{pct(r['cvar'], 10)}{pct(r['ploss'], 8)}{pct(r['dd95'], 7)}")


# --- grid of allocations inside the bounds ---
steps = round(1 / config.GRID_STEP)
results = []
for a in range(steps + 1):
    for b in range(steps + 1 - a):
        w = [a / steps, b / steps, (steps - a - b) / steps]
        if all(lo - 1e-9 <= x <= hi + 1e-9 for x, (lo, hi) in zip(w, config.BOUNDS)):
            results.append(evaluate(w))

print("History:", dates[0], "to", dates[-1])
print(f"{len(results)} allocations x {config.N_PATHS} paths x {config.HORIZON_YEARS}y | bucket order: {', '.join(names)}")
print("Bounds:", {n: (lo, hi) for n, (lo, hi) in zip(names, config.BOUNDS)})
print("medCAGR = median annualized return | VaR/CVaR = 1-year loss size | DD95 = 95th pct max drawdown")

print("\nYOUR BASELINE FROM THE PLAN DOC")
show_header()
show(evaluate(config.BASELINE))

print("\nBEST RISK-ADJUSTED (max Sharpe)")
show_header()
show(max(results, key=lambda r: r["sharpe"]))

print("\nLOWEST RISK (min volatility)")
show_header()
show(min(results, key=lambda r: r["vol"]))

print("\nBEST RETURN FOR EACH CLIENT RISK LEVEL (highest median CAGR with 1y VaR95 under the limit)")
show_header()
for level, limit in config.RISK_PROFILES.items():
    ok = [r for r in results if r["var"] <= limit]
    if ok:
        print(f"{level} (max loss {limit * 100:g}%):")
        show(max(ok, key=lambda r: r["cagr"]))
    else:
        print(f"{level} (max loss {limit * 100:g}%): nothing in the bounds fits")

# efficient frontier: walk up in volatility, keep an allocation only if it beats all lower-vol ones on return
print("\nEFFICIENT FRONTIER (most return for each level of risk)")
show_header()
best = -1
last_vol = -1
for r in sorted(results, key=lambda r: r["vol"]):
    if r["cagr"] > best:
        best = r["cagr"]
        if r["vol"] - last_vol >= 0.01:     # skip near-duplicates, print roughly every 1% of vol
            last_vol = r["vol"]
            show(r)
