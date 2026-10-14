import csv
import itertools
import math
import os
import random
from statistics import NormalDist

import config

TRADING_DAYS = 252


# ---------- data ----------

def load_prices(tickers):
    """Read data/TICKER.csv for each ticker, keep only dates every ticker has."""
    series = {}
    for t in tickers:
        with open(os.path.join(config.DATA_DIR, t + ".csv")) as f:
            rows = list(csv.reader(f))[1:]
        series[t] = {r[0]: float(r[1]) for r in rows}
    dates = sorted(set.intersection(*[set(s) for s in series.values()]))
    prices = {t: [series[t][d] for d in dates] for t in tickers}
    return dates, prices


def load_cash(dates):
    """Annual cash rate (decimal) for each date, from data/IRX.csv. None if the file isn't there."""
    path = os.path.join(config.DATA_DIR, config.CASH_TICKER.lstrip("^") + ".csv")
    if not os.path.exists(path):
        return None
    with open(path) as f:
        series = {r[0]: float(r[1]) / 100 for r in list(csv.reader(f))[1:]}
    days = sorted(series)
    out = []
    i = 0
    last = series[days[0]]
    for d in dates:
        while i < len(days) and days[i] <= d:
            last = series[days[i]]
            i += 1
        out.append(last)
    return out


def daily_returns(prices):
    return [prices[i] / prices[i - 1] - 1 for i in range(1, len(prices))]


def bucket_rows(prices):
    """One row per day: [bucket1_return, bucket2_return, ...]
    Each bucket is its tickers at fixed weights, rebalanced daily."""
    rets = {t: daily_returns(p) for t, p in prices.items()}
    n = len(next(iter(rets.values())))
    rows = []
    for i in range(n):
        row = []
        for bucket in config.BUCKETS.values():
            row.append(sum(w * rets[t][i] for t, w in bucket.items()))
        rows.append(row)
    return rows


# ---------- basic stats ----------

def mean(x):
    return sum(x) / len(x)


def stdev(x):
    m = mean(x)
    return math.sqrt(sum((v - m) ** 2 for v in x) / (len(x) - 1))


def percentile(x, p):
    """p between 0 and 1, linear interpolation"""
    s = sorted(x)
    k = (len(s) - 1) * p
    lo = int(k)
    hi = min(lo + 1, len(s) - 1)
    return s[lo] + (s[hi] - s[lo]) * (k - lo)


def max_drawdown(values):
    """Biggest peak-to-trough fall, returned as a positive number (0.25 = -25%)"""
    peak = values[0]
    worst = 0.0
    for v in values:
        if v > peak:
            peak = v
        dd = v / peak - 1
        if dd < worst:
            worst = dd
    return -worst


# ---------- VaR / CVaR (all returned as positive loss sizes) ----------

def hist_var(returns, conf=0.95):
    return -percentile(returns, 1 - conf)


def hist_cvar(returns, conf=0.95):
    """Expected Shortfall: average loss on the days worse than the VaR cutoff"""
    cutoff = percentile(returns, 1 - conf)
    tail = [r for r in returns if r <= cutoff]
    return -mean(tail)


def param_var(returns, conf=0.95):
    """Normal-distribution VaR: -(mean - z * stdev)"""
    z = NormalDist().inv_cdf(conf)
    return -(mean(returns) - z * stdev(returns))


# ---------- backtest engine ----------

def run_backtest(rows, weights, rebalance_days=config.REBALANCE_DAYS):
    """rows = daily bucket returns, weights = target weight per bucket.
    Sleeves drift with returns and get reset to target every rebalance_days.
    Returns the list of daily portfolio returns."""
    sleeves = list(weights)          # start with $1 split by target weights
    out = []
    for day, row in enumerate(rows, start=1):
        before = sum(sleeves)
        sleeves = [s * (1 + r) for s, r in zip(sleeves, row)]
        after = sum(sleeves)
        out.append(after / before - 1)
        if day % rebalance_days == 0:
            sleeves = [w * after for w in weights]
    return out


def summarize(rets):
    """Stats for a list of daily returns"""
    values = [1.0]
    for r in rets:
        values.append(values[-1] * (1 + r))
    years = len(rets) / TRADING_DAYS
    daily_rf = config.RISK_FREE / TRADING_DAYS
    vol = stdev(rets) * math.sqrt(TRADING_DAYS)
    downside = [min(r - daily_rf, 0) for r in rets]
    down_dev = math.sqrt(sum(d * d for d in downside) / len(downside)) * math.sqrt(TRADING_DAYS)
    ann_excess = (mean(rets) - daily_rf) * TRADING_DAYS
    return {
        "total": values[-1] - 1,
        "cagr": values[-1] ** (1 / years) - 1,
        "vol": vol,
        "sharpe": ann_excess / vol,
        "sortino": ann_excess / down_dev,
        "maxdd": max_drawdown(values),
        "var95": hist_var(rets, 0.95),
        "cvar95": hist_cvar(rets, 0.95),
        "var99": hist_var(rets, 0.99),
        "pvar95": param_var(rets, 0.95),
    }


# ---------- monte carlo (bootstrap) ----------

def monthly_blocks(rows, k=config.REBALANCE_DAYS):
    """Every overlapping k-day window of history, compounded into one return per bucket.
    Drawing whole windows keeps the correlation between buckets and the fat tails."""
    blocks = []
    nb = len(rows[0])
    for start in range(len(rows) - k + 1):
        growth = [1.0] * nb
        for day in rows[start:start + k]:
            for j in range(nb):
                growth[j] *= 1 + day[j]
        blocks.append([g - 1 for g in growth])
    return blocks


def make_paths(n_blocks, n_paths, n_months, seed=config.SEED):
    """Random month picks. Same paths get reused for every allocation so comparisons are fair."""
    rng = random.Random(seed)
    return [[rng.randrange(n_blocks) for _ in range(n_months)] for _ in range(n_paths)]


def simulate(weights, blocks, paths):
    """Run the allocation through every path. Returns a dict of results."""
    port = [sum(w * x for w, x in zip(weights, b)) for b in blocks]   # portfolio return of each block
    years = len(paths[0]) / 12

    finals, ret_1y, drawdowns = [], [], []
    for path in paths:
        v = 1.0
        peak = 1.0
        worst = 0.0
        for m, idx in enumerate(path, start=1):
            v *= 1 + port[idx]
            if v > peak:
                peak = v
            dd = v / peak - 1
            if dd < worst:
                worst = dd
            if m == 12:
                ret_1y.append(v - 1)
        finals.append(v)
        drawdowns.append(-worst)

    monthly_mean = mean(port)
    monthly_vol = stdev(port)
    vol = monthly_vol * math.sqrt(12)
    return {
        "finals": finals,
        "ret_1y": ret_1y,
        "drawdowns": drawdowns,
        "cagrs": [f ** (1 / years) - 1 for f in finals],
        "vol": vol,
        "sharpe": (monthly_mean * 12 - config.RISK_FREE) / vol,
    }


def allocations(n, step, bounds):
    """Every split of 100% across n buckets on a grid, keeping those inside the bounds"""
    steps = round(1 / step)
    out = []
    for combo in itertools.product(range(steps + 1), repeat=n - 1):
        last = steps - sum(combo)
        if last < 0:
            continue
        w = [c / steps for c in combo] + [last / steps]
        if all(lo - 1e-9 <= x <= hi + 1e-9 for x, (lo, hi) in zip(w, bounds)):
            out.append(w)
    return out


def vol_ratio(rows, j, lam=0.94):
    """Recent volatility vs long-run volatility of bucket j.
    Recent = exponentially weighted (lambda 0.94, the RiskMetrics number)."""
    var = rows[0][j] ** 2
    total = 0.0
    for day in rows:
        var = lam * var + (1 - lam) * day[j] ** 2
        total += day[j] ** 2
    long_run = total / len(rows)
    lo, hi = config.VOL_RATIO_CLAMP
    return min(max(math.sqrt(var / long_run), lo), hi)


def scenario_blocks(rows, m_start=0, m_end=None, cash=None):
    """monthly_blocks, then adjusted to today's view of the market:
      1. average return projected (see config.RETURN_METHOD), unless config.EXPECTED_RETURNS overrides it.
         Spread, correlation and tails always stay historical.
      2. spread scaled by how fast-moving the market is right now, fading with
         a half-life; averaged over months m_start .. m_end of the projection
    cash = annual cash rate for every day in rows (needed for the "premium" method).
    Returns (blocks, info per bucket)."""
    blocks = monthly_blocks(rows)
    names = list(config.BUCKETS)
    years = len(rows) / TRADING_DAYS
    use_premium = config.RETURN_METHOD == "premium" and cash is not None
    info = []
    for j, name in enumerate(names):
        col = [b[j] for b in blocks]
        old_mean = mean(col)
        se = stdev(col) * math.sqrt(12) / math.sqrt(years)   # how precisely history pins down the average
        premium = None
        new_mean = old_mean
        if use_premium:
            premium = old_mean * 12 - mean(cash)              # average return above cash
            new_mean = (mean(cash[-21:]) + premium) / 12      # today's cash + that premium
        if config.EXPECTED_RETURNS[name] is not None:
            new_mean = config.EXPECTED_RETURNS[name] / 12
        factor = 1.0
        ratio = 1.0
        if config.VOL_REGIME and m_end is not None and m_end > m_start:
            ratio = vol_ratio(rows, j)
            decay = [0.5 ** (m / config.VOL_HALF_LIFE_MONTHS) for m in range(m_start, m_end)]
            factor = 1 + (ratio - 1) * mean(decay)
        for b in blocks:
            b[j] = new_mean + factor * (b[j] - old_mean)
        info.append({"name": name, "hist_mean": old_mean * 12, "premium": premium, "mean": new_mean * 12,
                     "se": se, "ratio": ratio, "factor": factor})
    return blocks, info


# ---------- printing ----------

def pct(x, width=7):
    return f"{x * 100:{width}.2f}%"
