# Case logic for Laura Gao: accumulate to 2033, fund the 10 payments, size the facility contribution.
# allocate.py and plan.py both sit on top of this file.
import math
import random

import config
from utils import *


# ---------- timeline ----------

def months_left(year):
    return round((config.TARGET_YEAR - year) * 12)


def future_flows(year):
    """{months from now: deposit}. A deposit dated exactly `year` is assumed to be inside the value you pass in."""
    return {round((y - year) * 12): amt for y, amt in config.CONTRIBUTIONS.items() if y > year}


# ---------- reserve ----------

def riskfree_reserve(rate):
    """Cost in 2033 of the 10 payments held as Treasuries to maturity (annuity due)"""
    return sum(config.PAYMENT / (1 + rate) ** k for k in range(config.N_PAYMENTS))


def reserve_growth(blocks, paths, mix):
    """For every path and each of the 10 years: growth factor of the risky sleeve"""
    port = [sum(w * x for w, x in zip(mix, b)) for b in blocks]
    out = []
    for path in paths:
        years = []
        for k in range(config.N_PAYMENTS):
            g = 1.0
            for idx in path[12 * k:12 * k + 12]:
                g *= 1 + port[idx]
            years.append(g)
        out.append(years)
    return out


def funded_prob(reserve, f0, growth):
    """Share of paths where all 10 payments get paid.
    Each year: pay $50k, then put fraction f in the risky sleeve and the rest in Treasuries.
    f starts at f0 and fades straight-line to 0 at the last payment."""
    n = config.N_PAYMENTS
    ok = 0
    for years in growth:
        v = reserve
        good = True
        for k in range(n):
            if v < config.PAYMENT - 1e-9:
                good = False
                break
            v -= config.PAYMENT
            f = f0 * (1 - k / (n - 1))
            v *= f * years[k] + (1 - f) * (1 + config.PLANNING_YIELD)
        if good:
            ok += 1
    return ok / len(growth)


def min_reserve(f0, growth, conf):
    """Smallest reserve that pays everything with probability >= conf (bisection)"""
    hi = riskfree_reserve(config.PLANNING_YIELD) * 1.5
    lo = config.PAYMENT * config.N_PAYMENTS * 0.3
    if funded_prob(hi, f0, growth) < conf:
        return hi
    for _ in range(30):
        mid = (lo + hi) / 2
        if funded_prob(mid, f0, growth) >= conf:
            hi = mid
        else:
            lo = mid
    return hi


# ---------- facility ----------

def facility(value, reserve):
    """What Laura can put toward the building: everything above the reserve, minus the flexibility share"""
    return max(0.0, (value - reserve) * (1 - config.FLEX_PCT))


# ---------- accumulation ----------

def accumulate(port, paths, v0, flows, snaps=None, shifts=None):
    """Grow the portfolio month by month along every path, adding deposits when due.
    port[idx] = portfolio return in historical block idx.
    shifts[p] = extra monthly return for path p (the uncertainty in the true average return).
    Returns value at the start of 2033 per path."""
    finals = []
    for p, path in enumerate(paths):
        v = v0
        s = shifts[p] if shifts else 0.0
        for m, idx in enumerate(path):
            if m in flows:
                v += flows[m]
            if snaps is not None and m % 12 == 0:
                snaps[m // 12].append(v)
            v *= 1 + port[idx] + s
        finals.append(v)
    return finals


def required_return(v0, flows, n_months, goal):
    """Constant annual return that turns today's value plus future deposits into `goal` (bisection)"""
    def end_value(r):
        monthly = (1 + r) ** (1 / 12) - 1
        v = v0
        for m in range(n_months):
            if m in flows:
                v += flows[m]
            v *= 1 + monthly
        return v
    lo, hi = -0.5, 1.0
    for _ in range(60):
        mid = (lo + hi) / 2
        if end_value(mid) < goal:
            lo = mid
        else:
            hi = mid
    return hi


# ---------- setup + scoring ----------

def setup(year, value, rows=None, cash=None):
    """Everything the other scripts need for 'we are at start of <year> and the portfolio is worth <value>'"""
    assert year <= config.TARGET_YEAR, "year must be 2033 or earlier"
    if rows is None:
        dates, prices = load_prices(config.ALL_TICKERS)
        rows = bucket_rows(prices)
        cash = load_cash(dates[1:])
        hist = (dates[0], dates[-1])
    else:
        hist = None
    n = months_left(year)
    blocks, info = scenario_blocks(rows, 0, n, cash)
    paths = make_paths(len(blocks), config.N_PATHS, n)

    n_res = 12 * config.N_PAYMENTS
    res_blocks, _ = scenario_blocks(rows, n, n + n_res, cash)
    res_paths = make_paths(len(res_blocks), config.N_PATHS, n_res, config.SEED + 1)
    mix = [config.RESERVE_MIX[name] for name in config.BUCKETS]
    growth = reserve_growth(res_blocks, res_paths, mix)
    reserve = min_reserve(config.RESERVE_RISKY_START, growth, config.RESERVE_CONFIDENCE)
    if config.RESERVE_RISKY_START == 0:
        reserve = riskfree_reserve(config.PLANNING_YIELD)

    need = reserve + config.TARGET_FACILITY / (1 - config.FLEX_PCT)   # portfolio value that gives the target contribution
    rng = random.Random(config.SEED + 2)
    z = [[rng.gauss(0, 1) for _ in config.BUCKETS] for _ in paths]   # one draw per path and bucket
    return {"year": year, "value": value, "n": n, "rows": rows, "cash": cash, "z": z, "hist": hist, "blocks": blocks, "info": info,
            "paths": paths, "flows": future_flows(year), "growth": growth, "reserve": reserve, "need": need}


def port_returns(weights, blocks):
    return [sum(w * x for w, x in zip(weights, b)) for b in blocks]


def path_shifts(weights, ctx):
    """Each simulated future believes in its own true average return: the estimated average plus
    a random error of one standard error. Returns the extra monthly portfolio return per path."""
    if not config.PARAM_UNCERTAINTY:
        return None
    se = [i["se"] / 12 for i in ctx["info"]]
    return [sum(w * s * zz for w, s, zz in zip(weights, se, z)) for z in ctx["z"]]


def score(weights, ctx):
    port = port_returns(weights, ctx["blocks"])
    if ctx["n"] > 0:
        finals = accumulate(port, ctx["paths"], ctx["value"], ctx["flows"], None, path_shifts(weights, ctx))
    else:
        finals = [ctx["value"]] * config.N_PATHS
    n = len(finals)
    vol = stdev(port) * math.sqrt(12)
    return {
        "w": weights,
        "vol": vol,
        "sharpe": (mean(port) * 12 - config.RISK_FREE) / vol,
        "p_safe": sum(f >= ctx["reserve"] for f in finals) / n,
        "p_goal": sum(f >= ctx["need"] for f in finals) / n,
        "p5": percentile(finals, 0.05),
        "p50": percentile(finals, 0.50),
        "p95": percentile(finals, 0.95),
        "finals": finals,
    }


def choose(results):
    """Take only as much risk as the goal needs.
    1. keep allocations that cover the reserve with probability >= SAFETY_PROB
    2. of those, keep ones that reach the facility target with probability >= GOAL_PROB
    3. pick the lowest-volatility one
    If nothing reaches the target, pick the safe one with the best chance of it,
    but never one riskier than MAX_VOL (so a portfolio that is behind doesn't gamble)."""
    safe = [r for r in results if r["p_safe"] >= config.SAFETY_PROB]
    if not safe:
        return max(results, key=lambda r: r["p_safe"]), "NO split meets the safety level - showing the safest one"
    good = [r for r in safe if r["p_goal"] >= config.GOAL_PROB]
    if good:
        return min(good, key=lambda r: (r["vol"], -r["p_goal"])), "lowest-risk split that still reaches the facility target"
    capped = [r for r in safe if r["vol"] <= config.MAX_VOL] or [min(safe, key=lambda r: r["vol"])]
    return max(capped, key=lambda r: r["p_goal"]), "target not reachable at the required confidence - best chance of it within the risk cap"


def search(ctx, step=config.GRID_STEP):
    grid = allocations(len(config.BUCKETS), step, config.BOUNDS)
    return [score(w, ctx) for w in grid]


def dollars(x):
    x = round(x)
    return f"-${-x:,}" if x < 0 else f"${x:,}"
