# Picks the bucket split (bonds / funds / stocks) for where Laura's portfolio is right now.
# Re-run it whenever the date, the portfolio value, or the market view (config.py) changes.
#
# Run: python3 allocate.py YEAR VALUE [current bonds funds stocks]
#   python3 allocate.py 2026 0                       before any money goes in
#   python3 allocate.py 2027 300000                  start of 2027, after the first deposit
#   python3 allocate.py 2029 510000 0.40 0.40 0.20   mid-plan, also shows the trades to get from 40/40/20
import sys

import config
from goal import *

year = float(sys.argv[1])
value = float(sys.argv[2])
current = [float(a) for a in sys.argv[3:3 + len(config.BUCKETS)]] if len(sys.argv) > 3 else None

ctx = setup(year, value)
names = list(config.BUCKETS)

print(f"SITUATION: start of {year:g}, portfolio {dollars(value)}, {ctx['n']} months until {config.TARGET_YEAR}")
if ctx["hist"]:
    print("History used:", ctx["hist"][0], "to", ctx["hist"][1])
print("Deposits still to come:", {y: dollars(a) for y, a in config.CONTRIBUTIONS.items() if y > year} or "none")

print(f"\nMARKET VIEW (method: {config.RETURN_METHOD}; overrides in config.py)")
if ctx["cash"]:
    print(f"Cash rate now {pct(mean(ctx['cash'][-21:])).strip()} | average over history {pct(mean(ctx['cash'])).strip()}")
elif config.RETURN_METHOD == "premium":
    print("NOTE: data/IRX.csv (cash rate) not found - falling back to plain historical averages. Run fetch_data.py.")
years = len(ctx["rows"]) / 252
print(f"{years:.1f} years of history. An average measured from that long carries the +/- shown below (1 std error).")
print(f"{'':8}{'hist avg':>10}{'over cash':>11}{'used avg':>10}{'+/- SE':>9}{'vol now/long':>14}{'vol scale':>11}")
for i in ctx["info"]:
    prem = pct(i["premium"], 9) if i["premium"] is not None else "       n/a"
    print(f"{i['name']:8}{pct(i['hist_mean'], 9)}{prem}{pct(i['mean'], 9)}{pct(i['se'], 8)}{i['ratio']:14.2f}{i['factor']:11.2f}")
if years < 20:
    print("WARNING: under 20 years of history - one young ticker in config.BUCKETS is shortening it.")

print("\nTARGETS")
print(f"Reserve needed in {config.TARGET_YEAR}: {dollars(ctx['reserve'])}  (10 x {dollars(config.PAYMENT)}, Treasuries at {pct(config.PLANNING_YIELD).strip()}, "
      f"start {pct(config.RESERVE_RISKY_START, 0).strip()} risky)")
print(f"Portfolio needed for a {dollars(config.TARGET_FACILITY)} facility contribution (keeping {pct(config.FLEX_PCT, 0).strip()} back): {dollars(ctx['need'])}")
if ctx["n"] > 0:
    for label, goal in [("cover the reserve", ctx["reserve"]), ("hit the facility target", ctx["need"])]:
        r = required_return(value, ctx["flows"], ctx["n"], goal)
        print(f"Steady annual return needed to {label}: {pct(r).strip()}")

results = search(ctx)
best, why = choose(results)
print(f"\nSEARCHED {len(results)} splits x {config.N_PATHS} paths | safety rule: P(reserve covered) >= {pct(config.SAFETY_PROB, 0).strip()}, "
      f"goal rule: P(target) >= {pct(config.GOAL_PROB, 0).strip()}")


def header():
    print(f"{'Bonds':>7}{'Funds':>7}{'Stocks':>7} |{'vol':>8}{'P(reserve)':>11}{'P(target)':>10}{'5th pct':>12}{'median':>12}{'95th pct':>12}")


def show(r):
    w = r["w"]
    print(f"{w[0] * 100:6.1f}%{w[1] * 100:6.1f}%{w[2] * 100:6.1f}% |{pct(r['vol'], 7)}{pct(r['p_safe'], 10)}{pct(r['p_goal'], 9)}"
          f"{r['p5']:12,.0f}{r['p50']:12,.0f}{r['p95']:12,.0f}")


print("\nRECOMMENDED SPLIT:", why)
header()
show(best)

print("\nYOUR PLAN-DOC BASELINE (37.5 / 37.5 / 25) for comparison")
header()
show(score(config.BASELINE, ctx))

for name, x, (lo, hi) in zip(names, best["w"], config.BOUNDS):
    if abs(x - lo) < 1e-9 or abs(x - hi) < 1e-9:
        print(f"NOTE: {name} sits at its bound ({lo * 100:g}%-{hi * 100:g}%) - the bound, not the math, is setting it. Widen BOUNDS in config.py if that's not intended.")

safe = [r for r in results if r["p_safe"] >= config.SAFETY_PROB]
print("\nSAFE SPLITS RANKED BY CHANCE OF HITTING THE TARGET (top 8)")
header()
for r in sorted(safe, key=lambda r: (-r["p_goal"], r["vol"]))[:8]:
    show(r)
if not safe:
    print("  none - no split in the bounds covers the reserve with the required probability")

print("\nLOWEST-RISK SPLIT IN THE BOUNDS")
header()
show(min(results, key=lambda r: r["vol"]))

if current:
    assert abs(sum(current) - 1) < 1e-9, "current weights must add to 1"
    print(f"\nTRADES TO MOVE FROM CURRENT HOLDINGS TO THE RECOMMENDED SPLIT ({dollars(value)} portfolio)")
    for name, c, t in zip(names, current, best["w"]):
        diff = (t - c) * value
        print(f"{name:8} {c * 100:5.1f}% -> {t * 100:5.1f}%   {'BUY ' if diff >= 0 else 'SELL'} {dollars(abs(diff))}")
