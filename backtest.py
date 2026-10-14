# Backtest the bucket strategy on real history.
# Run: python3 backtest.py                 (uses BASELINE from config)
#      python3 backtest.py 0.30 0.45 0.25  (bonds funds stocks)
import sys

import config
from utils import *

names = list(config.BUCKETS)
weights = [float(a) for a in sys.argv[1:4]] if len(sys.argv) >= 4 else config.BASELINE
assert abs(sum(weights) - 1) < 1e-9, "weights must add to 1"

dates, prices = load_prices(config.ALL_TICKERS)
rows = bucket_rows(prices)
dates = dates[1:]    # returns start on the second date

print("Data:", dates[0], "to", dates[-1], f"({len(rows)} trading days, {len(rows) / 252:.1f} years)")
print("Rebalance every", config.REBALANCE_DAYS, "days | risk-free", pct(config.RISK_FREE).strip())

# --- each ticker on its own ---
print("\nINDIVIDUAL TICKERS")
print(f"{'ticker':8}{'CAGR':>9}{'vol':>9}{'sharpe':>8}{'maxDD':>9}{'VaR95 1d':>10}")
for t in config.ALL_TICKERS:
    s = summarize(daily_returns(prices[t]))
    print(f"{t:8}{pct(s['cagr'], 8)}{pct(s['vol'], 8)}{s['sharpe']:8.2f}{pct(s['maxdd'], 8)}{pct(s['var95'], 9)}")

# --- portfolios to compare ---
label = "/".join(f"{w * 100:g}" for w in weights)
portfolios = {}
for i, n in enumerate(names):
    only = [1.0 if j == i else 0.0 for j in range(len(names))]
    portfolios[n + " only"] = run_backtest(rows, only)
portfolios["STRATEGY " + label] = run_backtest(rows, weights)
portfolios["Benchmark " + config.BENCHMARK] = daily_returns(prices[config.BENCHMARK])

print("\nPORTFOLIOS")
print(f"{'':24}{'CAGR':>9}{'vol':>9}{'sharpe':>8}{'sortino':>9}{'maxDD':>9}{'VaR95 1d':>10}{'CVaR95 1d':>11}{'VaR99 1d':>10}")
for name, rets in portfolios.items():
    s = summarize(rets)
    print(f"{name:24}{pct(s['cagr'], 8)}{pct(s['vol'], 8)}{s['sharpe']:8.2f}{s['sortino']:9.2f}"
          f"{pct(s['maxdd'], 8)}{pct(s['var95'], 9)}{pct(s['cvar95'], 10)}{pct(s['var99'], 9)}")

s = summarize(portfolios["STRATEGY " + label])
print(f"\nStrategy 1-day 95% VaR: historical {pct(s['var95']).strip()} vs normal-assumption {pct(s['pvar95']).strip()}")
print("(if historical is bigger, the real tails are fatter than a bell curve says)")

# --- calendar years ---
print("\nCALENDAR YEARS")
print(f"{'year':8}{'strategy':>10}{'benchmark':>11}")
strat = portfolios["STRATEGY " + label]
bench = portfolios["Benchmark " + config.BENCHMARK]
years = sorted({d[:4] for d in dates})
for y in years:
    idx = [i for i, d in enumerate(dates) if d[:4] == y]
    a = b = 1.0
    for i in idx:
        a *= 1 + strat[i]
        b *= 1 + bench[i]
    note = "  (partial year)" if len(idx) < 240 else ""
    print(f"{y:8}{pct(a - 1, 9)}{pct(b - 1, 10)}{note}")

# --- stress windows ---
print("\nSTRESS WINDOWS")
print(f"{'':20}{'strategy':>10}{'benchmark':>11}")
for name, (start, end) in config.STRESS.items():
    idx = [i for i, d in enumerate(dates) if start <= d <= end]
    if not idx:
        print(f"{name:20}  no data in this window")
        continue
    a = b = 1.0
    for i in idx:
        a *= 1 + strat[i]
        b *= 1 + bench[i]
    print(f"{name:20}{pct(a - 1, 9)}{pct(b - 1, 10)}")
