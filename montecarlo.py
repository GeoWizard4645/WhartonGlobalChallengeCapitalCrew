# Monte Carlo on one bucket allocation (bootstrapped from real history).
# Run: python3 montecarlo.py                 (uses BASELINE from config)
#      python3 montecarlo.py 0.30 0.45 0.25  (bonds funds stocks)
import sys

import config
from utils import *

weights = [float(a) for a in sys.argv[1:4]] if len(sys.argv) >= 4 else config.BASELINE
assert abs(sum(weights) - 1) < 1e-9, "weights must add to 1"

dates, prices = load_prices(config.ALL_TICKERS)
rows = bucket_rows(prices)
blocks = monthly_blocks(rows)
n_months = config.HORIZON_YEARS * 12
paths = make_paths(len(blocks), config.N_PATHS, n_months)
res = simulate(weights, blocks, paths)

print("History used:", dates[0], "to", dates[-1], f"({len(blocks)} overlapping monthly windows)")
print("Allocation:", dict(zip(config.BUCKETS, weights)))
print(f"{config.N_PATHS} paths x {config.HORIZON_YEARS} years, start ${config.START_VALUE:,}, seed {config.SEED}")

print("\nENDING VALUE PERCENTILES")
print(f"{'pctile':8}{'value':>14}{'CAGR':>10}")
for p in [0.01, 0.05, 0.25, 0.50, 0.75, 0.95, 0.99]:
    v = percentile(res["finals"], p)
    c = percentile(res["cagrs"], p)
    print(f"{p * 100:>5.0f}th {config.START_VALUE * v:>14,.0f}{pct(c, 9)}")
print(f"{'mean':8}{config.START_VALUE * mean(res['finals']):>14,.0f}")

n = len(res["finals"])
print("\nPROBABILITIES")
print(f"Lose money over {config.HORIZON_YEARS}y:            ", pct(sum(f < 1 for f in res["finals"]) / n).strip())
print(f"Beat {config.TARGET_CAGR * 100:g}%/yr:                    ", pct(sum(c >= config.TARGET_CAGR for c in res["cagrs"]) / n).strip())
print("Drawdown worse than 10%:       ", pct(sum(d > 0.10 for d in res["drawdowns"]) / n).strip())
print("Drawdown worse than 20%:       ", pct(sum(d > 0.20 for d in res["drawdowns"]) / n).strip())
print("Drawdown worse than 30%:       ", pct(sum(d > 0.30 for d in res["drawdowns"]) / n).strip())

print("\n1-YEAR RISK (loss sizes)")
r1 = res["ret_1y"]
for conf in [0.95, 0.99]:
    print(f"VaR  {conf * 100:g}%: {pct(hist_var(r1, conf)).strip():>8}   "
          f"CVaR {conf * 100:g}%: {pct(hist_cvar(r1, conf)).strip():>8}   "
          f"(${config.START_VALUE * hist_var(r1, conf):,.0f} / ${config.START_VALUE * hist_cvar(r1, conf):,.0f} on the start value)")
print("Normal-assumption VaR 95%:", pct(param_var(r1, 0.95)).strip())

print("\nOTHER")
print("Annualized vol:       ", pct(res["vol"]).strip())
print("Sharpe:               ", f"{res['sharpe']:.2f}")
print("Median max drawdown:  ", pct(percentile(res["drawdowns"], 0.50)).strip())
print("95th pct max drawdown:", pct(percentile(res["drawdowns"], 0.95)).strip())
