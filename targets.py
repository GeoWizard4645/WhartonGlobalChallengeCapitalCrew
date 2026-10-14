# Tests many facility targets so the team can see what each one costs in risk and what it earns.
# Run: python3 targets.py YEAR VALUE      e.g.  python3 targets.py 2027 300000
# Runs twice: with the data-driven return view in config.py, and with the CAUTIOUS_RETURNS view.
import sys

import config
from goal import *

year = float(sys.argv[1])
value = float(sys.argv[2])
scenarios = {"DATA-DRIVEN returns (config.py as set)": dict(config.EXPECTED_RETURNS),
             "CAUTIOUS returns (config.CAUTIOUS_RETURNS)": config.CAUTIOUS_RETURNS}


def m(x):
    return f"{x:>10,.0f}"


for label, overrides in scenarios.items():
    config.EXPECTED_RETURNS = overrides
    ctx = setup(year, value)
    results = search(ctx)
    deposits = value + sum(ctx["flows"].values())
    reserve = ctx["reserve"]
    names = list(config.BUCKETS)

    print("\n" + "=" * 110)
    print(label)
    print("=" * 110)
    print("Average return used:", {i["name"]: pct(i["mean"]).strip() for i in ctx["info"]})
    print(f"Total deposited by 2033: {dollars(deposits)} | reserve needed {dollars(reserve)} | gain = 2033 value minus deposits")

    # --- A. every efficient split: what it earns and what facility target it can support ---
    print("\nA. EFFICIENT SPLITS - how much risk buys how much (facility = what could go to the building)")
    print(f"{'Bonds':>6}{'Funds':>6}{'Stocks':>7} |{'vol':>7}{'Sharpe':>7}{'P(reserve)':>11}{'P(<deposits)':>13} |{'5th gain':>10}{'median gain':>12}{'95th gain':>10} |"
          f"{'facility@90%':>13}{'@75%':>9}{'@50%':>9}")
    rows = [score(config.BASELINE, ctx)]
    best_ret = -1
    last_vol = -1
    for r in sorted(results, key=lambda r: r["vol"]):
        if r["p50"] > best_ret:
            best_ret = r["p50"]
            if r["vol"] - last_vol >= 0.0075:
                last_vol = r["vol"]
                rows.append(r)
    for i, r in enumerate(rows):
        f = r["finals"]
        tag = "  <- plan-doc baseline" if i == 0 else ""
        w = r["w"]
        print(f"{w[0] * 100:5.1f}%{w[1] * 100:5.1f}%{w[2] * 100:6.1f}% |{pct(r['vol'], 6)}{r['sharpe']:7.2f}{pct(r['p_safe'], 10)}{pct(sum(v < deposits for v in f) / len(f), 12)} |"
              f"{m(r['p5'] - deposits)}{m(r['p50'] - deposits):>12}{m(r['p95'] - deposits)} |"
              f"{m(facility(percentile(f, 0.10), reserve)):>13}{m(facility(percentile(f, 0.25), reserve)):>9}{m(facility(percentile(f, 0.50), reserve)):>9}{tag}")
    print("facility@90% = contribution she beats in 90% of simulated futures (and @75%, @50%). A target above a split's @65% line is a long shot for it.")

    # --- B. for each target, the lowest-risk split that reaches it ---
    picks = []
    for t in config.TARGET_SWEEP:
        need = reserve + t / (1 - config.FLEX_PCT)
        rs = []
        for r in results:
            r2 = dict(r)
            r2["p_goal"] = sum(v >= need for v in r["finals"]) / len(r["finals"])
            rs.append(r2)
        best, why = choose(rs)
        picks.append((t, best, why.startswith("lowest-risk")))

    print(f"\nB. FOR EACH FACILITY TARGET: the split the rule picks (goal = reach target in >= {config.GOAL_PROB * 100:.0f}% of futures, risk cap {config.MAX_VOL * 100:.0f}% vol)")
    print(f"{'target':>9} |{'Bonds':>6}{'Funds':>6}{'Stocks':>7} |{'goal met?':>10}{'P(target)':>10}{'vol':>7}{'Sharpe':>7}{'P(reserve)':>11}")
    for t, b, ok in picks:
        w = b["w"]
        print(f"{t:>9,} |{w[0] * 100:5.1f}%{w[1] * 100:5.1f}%{w[2] * 100:6.1f}% |{'yes' if ok else 'NO':>10}{pct(b['p_goal'], 9)}{pct(b['vol'], 6)}{b['sharpe']:7.2f}{pct(b['p_safe'], 10)}")

    print("\n   Dollar outcomes of those picks (2033 value minus deposits; facility = contribution after the reserve and 20% flexibility)")
    print(f"{'target':>9} |{'5th gain':>10}{'median gain':>12}{'95th gain':>10}{'stdev':>10}{'P(<deposits)':>13}{'median gain per $ of 5% shortfall':>36} |{'facility 5th':>13}{'median':>9}{'95th':>9}")
    for t, b, ok in picks:
        f = b["finals"]
        med = b["p50"]
        spread = med - b["p5"]
        ratio = (med - deposits) / spread if spread > 0 else float("nan")
        print(f"{t:>9,} |{m(b['p5'] - deposits)}{m(med - deposits):>12}{m(b['p95'] - deposits)}{m(stdev(f))}{pct(sum(v < deposits for v in f) / len(f), 12)}{ratio:36.2f} |"
              f"{m(facility(b['p5'], reserve)):>13}{m(facility(med, reserve)):>9}{m(facility(b['p95'], reserve)):>9}")
    print("'gain per $ of 5% shortfall' = median gain divided by (median value - 5th percentile value): reward per dollar of bad-case downside.")
