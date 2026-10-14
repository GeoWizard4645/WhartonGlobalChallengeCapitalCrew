# Full report for Laura: allocation, operating reserve, facility contribution, co-sponsor range.
# Run: python3 plan.py YEAR VALUE
#   python3 plan.py 2027 300000   the plan at the start
#   python3 plan.py 2031 640000   the co-sponsor conversation, using the real 2031 value
import sys

import config
from goal import *

year = float(sys.argv[1])
value = float(sys.argv[2])
names = list(config.BUCKETS)

ctx = setup(year, value)
rows = ctx["rows"]
print(f"PLAN FROM START OF {year:g}: portfolio {dollars(value)}, {ctx['n']} months to {config.TARGET_YEAR}")

# --- 1. allocation ---
results = search(ctx)
best, why = choose(results)
w = best["w"]
print("\n1. ALLOCATION NOW:", why)
print("   " + ", ".join(f"{n} {x * 100:g}%" for n, x in zip(names, w)))
print(f"   volatility {pct(best['vol']).strip()} | P(reserve covered) {pct(best['p_safe']).strip()} | P(facility target) {pct(best['p_goal']).strip()}")

# --- 2. portfolio path, re-simulated with the chosen split ---
port = port_returns(w, ctx["blocks"])
n_years = ctx["n"] // 12
snaps = [[] for _ in range(n_years + 1)]
if ctx["n"] > 0:
    finals = accumulate(port, ctx["paths"], value, ctx["flows"], snaps, path_shifts(w, ctx))
else:
    finals = [value] * config.N_PATHS
print("\n2. PROJECTED PORTFOLIO VALUE (start of each year, after that year's deposit)")
print(f"{'year':8}{'10th':>12}{'median':>12}{'90th':>12}")
for i, vals in enumerate(snaps[:n_years]):
    print(f"{year + i:<8g}{percentile(vals, 0.10):12,.0f}{percentile(vals, 0.50):12,.0f}{percentile(vals, 0.90):12,.0f}")
print(f"{config.TARGET_YEAR:<8}{percentile(finals, 0.10):12,.0f}{percentile(finals, 0.50):12,.0f}{percentile(finals, 0.90):12,.0f}")

# --- 3. the reserve ---
print(f"\n3. OPERATING RESERVE (10 x {dollars(config.PAYMENT)}, {config.TARGET_YEAR}-{config.TARGET_YEAR + 9})")
print(f"   our definition of high certainty: all 10 payments made in >= {pct(config.RESERVE_CONFIDENCE, 0).strip()} of simulated worlds")
ladder = riskfree_reserve(config.PLANNING_YIELD)
print(f"\n   Treasury ladder cost at {pct(config.PLANNING_YIELD).strip()}: {dollars(ladder)}   <- certain unless the issuer defaults")
print("   cost of the ladder if yields in 2033 are different:")
for y in [0.02, 0.03, 0.04, 0.05]:
    print(f"      {pct(y, 5).strip():>6} -> {dollars(riskfree_reserve(y))}")
print("\n   Could we hold the reserve smaller by keeping some of it in assets that can grow?")
print(f"   {'risky share in 2033':>20}{'smallest reserve':>18}{'saving vs ladder':>18}{'P(funded) at ladder size':>26}")
for f0 in [0.0, 0.1, 0.2, 0.3, 0.5]:
    r = min_reserve(f0, ctx["growth"], config.RESERVE_CONFIDENCE)
    p = funded_prob(ladder, f0, ctx["growth"])
    print(f"   {pct(f0, 19).strip():>20}{dollars(r):>18}{dollars(ladder - r):>18}{pct(p, 25).strip():>26}")
print(f"   (risky share = share of the reserve in {config.RESERVE_MIX}, fading to 0 by the last payment)")
print("\n   Ladder purchase list (buy a Treasury maturing just before each payment):")
for k in range(config.N_PAYMENTS):
    print(f"      {config.TARGET_YEAR + k}: payment {dollars(config.PAYMENT)} costs {dollars(config.PAYMENT / (1 + config.PLANNING_YIELD) ** k)} in {config.TARGET_YEAR}")

# --- 4. facility ---
reserve = ctx["reserve"]
contrib = [facility(v, reserve) for v in finals]
print(f"\n4. FACILITY CONTRIBUTION in {config.TARGET_YEAR} (reserve {dollars(reserve)}, {pct(config.FLEX_PCT, 0).strip()} of the rest held back for flexibility)")
print(f"   P(portfolio can't cover the reserve): {pct(sum(v < reserve for v in finals) / len(finals)).strip()}")
print(f"   {'':26}{'portfolio':>12}{'contribution':>14}{'in today $':>12}")
deflate = (1 + config.INFLATION) ** (config.TARGET_YEAR - 2026)
for label, p in [("severe (1st pct)", 0.01), ("unfavorable (10th pct)", 0.10), ("below average (25th)", 0.25),
                 ("base case (median)", 0.50), ("good (75th)", 0.75), ("favorable (90th pct)", 0.90)]:
    c = percentile(contrib, p)
    print(f"   {label:26}{percentile(finals, p):12,.0f}{c:14,.0f}{c / deflate:12,.0f}")
print(f"   (today $ = deflated at {pct(config.INFLATION).strip()}/yr back to 2026)")

low = percentile(contrib, config.RANGE_LOW_PCT)
high = percentile(contrib, config.RANGE_HIGH_PCT)
in_range = sum(low <= c <= high for c in contrib) / len(contrib)
print(f"\n5. RANGE TO TELL CO-SPONSORS: {dollars(low)} to {dollars(high)}")
print(f"   {pct(1 - config.RANGE_LOW_PCT, 0).strip()} chance she can contribute at least {dollars(low)}")
print(f"   {pct(1 - config.RANGE_HIGH_PCT, 0).strip()} chance she can contribute at least {dollars(high)}")
print(f"   {pct(in_range, 0).strip()} chance the contribution lands inside the range")
print("   The low end is already net of the full reserve, so quoting it never puts the 10 payments at risk.")

# --- 6. glide path: how the split should move if the portfolio tracks the median ---
if ctx["n"] >= 12 and float(year).is_integer():
    print("\n6. PLANNED GLIDE PATH (re-optimized each January, assuming the portfolio sits at its median)")
    print(f"   {'year':6}{'value':>12}  {'Bonds':>7}{'Funds':>7}{'Stocks':>7}   P(target)")
    for i in range(n_years):
        y = int(year) + i
        v = percentile(snaps[i], 0.50)
        c = setup(y, v, rows, ctx["cash"])
        b, _ = choose(search(c))
        wi = b["w"]
        print(f"   {y:<6}{v:12,.0f}  {wi[0] * 100:6.1f}%{wi[1] * 100:6.1f}%{wi[2] * 100:6.1f}%   {pct(b['p_goal'], 6).strip()}")
    print("   Each year's real answer comes from running allocate.py with the actual value and the then-current market view.")
