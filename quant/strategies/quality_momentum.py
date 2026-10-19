"""Strategy 1: quality-filtered momentum (team doc §1, research/01_momentum.md §11-12, research/02_quality.md §7).

Pipeline at every month-end ``t`` (signals use prices <= t and filings with ``filed < t`` only)
-------------------------------------------------------------------------------------------------
Universe   point-in-time S&P 900 = S&P 500 + MidCap 400 (``ctx.universe(t, 'SP900')``, GICS as of ``t``), minus GICS Financials
           (quality metrics undefined), RAW price >= $5 (split-adjusted close x split factor after ``t``),
           >= 253 trading days of price history, valid 12-1 momentum.
Momentum   ``P[t-21] / P[t-252] - 1`` on adjusted close (quant/signals/technical.py).
Order MF   (team sketch, default) shortlist = top ``shortlist`` (20%) of the eligible universe by momentum ->
           quality arm -> technical filters -> rank by momentum -> top N.
Order QF   quality arm on the whole eligible universe -> technical filters -> rank by momentum -> top N.
Quality    any arm of quant/signals/quality.py ('Q0' = none; 'Q3a' = team rule NI>0, debt/equity<=X, gross margin
           or ROE >= industry median; percentile arms are computed over the whole eligible universe whatever
           the order).  Arms 'Q4-*' have no hard filter: they rank the eligible, technically-passing names by
           ``blend_score`` instead of momentum (order is irrelevant for them).
Technical  'none' | 'sma' (close > SMA200) | 'sma_rsi' (+ 50 <= RSI14 <= 70).
Weights    1/N each; if fewer than N names pass, hold the survivors at 1/N and leave the rest in CASH (never
           backfill with names that failed a filter).
Exits      re-ranking at every month-end sells any name that no longer passes (= month-end trend-break exit).
           Optional daily stop-loss (``stop_loss`` = fraction from the rebalance price, engine HZZ-style) and
           own-book vol targeting (``vol_target``; engine back-casts the target book over 126 days, cap 1).
Execution  signal at the close of the last trading day of the month, trade at the next close (engine
           ``exec_lag=1``), one-way cost ``cost_bps`` (default 10).

Public API (strategy-module contract of quant/ARCHITECTURE.md)
    DEFAULT, GRID, AXES, CATEGORICAL, register()
    target_weights(ctx, params, dates) -> DataFrame (signal date x yf_ticker)
    backtest(ctx, params, start, end, cost_bps=10) -> BacktestResult
    live_picks(ctx, params, asof) -> DataFrame (+ .attrs: vol_scalar, dropped, funnel)
    monthly_returns(params) -> Series of monthly net returns (for grid.run_grid)
    diagnostics(ctx, params, ...) -> DataFrame of the per-rebalance funnel
    first_signal_date(ctx) -> the common start month of every grid cell

Parameter encoding: stop_loss and vol_target use the string ``'none'`` for "off" so cells are JSON-friendly
and hash identically everywhere; ``None`` is accepted on input and normalised.

Caching: everything that does not depend on the cell is cached on the DataContext (``ctx._qm_cache``): the
technical panels, the per-date eligible frame, the per-date quality table, and the per-(date, quality arm,
technical, order, shortlist, X) ranked candidate list.  N, stop-loss and vol-target only change the slice /
engine config, so the 216 grid cells share ~(4 arms x 3 technicals) signal sets.
"""
from __future__ import annotations

import itertools
import logging
import math

import numpy as np
import pandas as pd

from quant.backtest import engine, grid
from quant.signals import quality as quality_mod
from quant.signals import technical as tech

log = logging.getLogger(__name__)

UNIVERSE = "SP900"      # S&P 500 + 400; S&P 600 history starts 2018-09 (would break train/test comparability)
STRATEGY = "quality_momentum"

# ----------------------------------------------------------------------------------------------
# constants that are NOT grid axes (documented, not tuned)
# ----------------------------------------------------------------------------------------------
MIN_PRICE = 5.0
MIN_HISTORY = 253
RSI_LO, RSI_HI = tech.RSI_BAND
VOL_LOOKBACK = 126
VOL_CAP = 1.0
START = "2011-01-01"
MIN_COVERAGE = 0.70           # first_signal_date(): share of the eligible universe with a fundamentals snapshot
MIN_UNIVERSE = 100
TABLE_QUALITY_COLS = ["gpoa", "gpoa_pct", "gmar", "roe", "roa", "debt_to_equity", "nd_ebitda", "net_income_ttm",
                      "cfo_ttm", "QL", "ql_pct", "gmar_ge_ind_med", "roe_ge_ind_med", "gpoa_ge_ind_med",
                      "period_end", "filed"]

# ----------------------------------------------------------------------------------------------
# DEFAULT / GRID (pre-registered, see register())
# ----------------------------------------------------------------------------------------------
FIXED = dict(order="MF", shortlist=0.20, x_debt=1.0)
DEFAULT = dict(FIXED, N=10, quality="Q3a", technical="sma_rsi", stop_loss="none", vol_target="none")

AXES = {"N": [5, 10, 20], "stop_loss": ["none", 0.15, 0.10]}          # ordinal, ordered loose -> tight
CATEGORICAL = {"technical": ["none", "sma", "sma_rsi"], "vol_target": ["none", 0.20],
               "quality": ["Q0", "Q3a", "Q1-50", "Q2-Q50"]}

GRID: list[dict] = [
    dict(FIXED, N=n, quality=q, technical=tc, stop_loss=sl, vol_target=vt)
    for q, tc, vt, sl, n in itertools.product(CATEGORICAL["quality"], CATEGORICAL["technical"],
                                              CATEGORICAL["vol_target"], AXES["stop_loss"], AXES["N"])
]

_OPTIONAL = dict(y_nde=3.0, trend_exit_daily=False)           # not part of the cells; accepted for ablations
_ALLOWED = set(DEFAULT) | set(_OPTIONAL)
_TECHNICALS = ("none", "sma", "sma_rsi")
_ORDERS = ("MF", "QF")


def register(force: bool = False, out_dir=None):
    """Write ``output/quality_momentum/preregistration.json`` (idempotent; refuses a different grid)."""
    extra = dict(
        description="quality-filtered 12-1 momentum, monthly, long-only top-N equal weight, point-in-time S&P 900 (S&P 500 + MidCap 400)",
        fixed=FIXED, optional_defaults=_OPTIONAL, constants=dict(
            min_price=MIN_PRICE, min_history=MIN_HISTORY, rsi_band=[RSI_LO, RSI_HI], sma_window=tech.SMA_WINDOW,
            mom="P[t-21]/P[t-252]-1 (adjclose, >=90% valid days)", vol_lookback=VOL_LOOKBACK, vol_cap=VOL_CAP,
            exec_lag=1, cost_bps_base=10, exclude="GICS Financials and Real Estate (REITs were inside Financials before 2016-08-31)", universe=f"{UNIVERSE} point-in-time (S&P 500 + MidCap 400; S&P 600 history only exists from 2018-09)",
            start_rule=f"first month-end >= {START} where >= {MIN_COVERAGE:.0%} of the eligible universe has a "
                       f"fundamentals snapshot (common to all cells)"),
        note="Cell-level stop_loss / vol_target use the string 'none' for off. technical in {none, sma, sma_rsi}.")
    return grid.preregister(STRATEGY, GRID, axes=AXES, categorical=CATEGORICAL, default=DEFAULT,
                            force=force, out_dir=out_dir, extra=extra)


# ----------------------------------------------------------------------------------------------
# parameters
# ----------------------------------------------------------------------------------------------
def _off(v) -> bool:
    return v is None or (isinstance(v, str) and v.lower() == "none")


def _params(params: dict | None) -> dict:
    """Merge with DEFAULT, validate, and normalise stop_loss / vol_target to float | None."""
    p = dict(DEFAULT)
    p.update(_OPTIONAL)
    p.update(params or {})
    unknown = set(p) - _ALLOWED
    if unknown:
        raise ValueError(f"unknown parameter(s) {sorted(unknown)}; allowed: {sorted(_ALLOWED)}")
    p["N"] = int(p["N"])
    if p["N"] < 1:
        raise ValueError("N must be >= 1")
    if p["technical"] not in _TECHNICALS:
        raise ValueError(f"technical must be one of {_TECHNICALS}")
    if p["order"] not in _ORDERS:
        raise ValueError(f"order must be one of {_ORDERS}")
    p["shortlist"] = float(p["shortlist"])
    if not 0.0 < p["shortlist"] <= 1.0:
        raise ValueError("shortlist must be in (0, 1]")
    p["stop_loss"] = None if _off(p["stop_loss"]) else float(p["stop_loss"])
    p["vol_target"] = None if _off(p["vol_target"]) else float(p["vol_target"])
    p["x_debt"] = float(p["x_debt"])
    p["y_nde"] = float(p["y_nde"])
    p["trend_exit_daily"] = bool(p["trend_exit_daily"])
    if p["quality"] not in quality_mod.ARMS:
        raise ValueError(f"unknown quality arm {p['quality']!r}; choose from {sorted(quality_mod.ARMS)}")
    return p


def _engine_cfg(p: dict, cost_bps: float) -> engine.BacktestConfig:
    return engine.BacktestConfig(exec_lag=1, cost_bps=float(cost_bps), stop_loss=p["stop_loss"],
                                 trend_exit_daily=p["trend_exit_daily"], vol_target=p["vol_target"],
                                 vol_lookback=VOL_LOOKBACK, vol_cap=VOL_CAP)


# ----------------------------------------------------------------------------------------------
# caches
# ----------------------------------------------------------------------------------------------
def _cache(ctx) -> dict:
    try:
        store = ctx.__dict__.setdefault("_qm_cache", {})
    except AttributeError:               # exotic ctx without __dict__: no caching across calls
        store = {}
    key = id(ctx.close)
    if store.get("_key") != key:
        store.clear()
        store.update(_key=key, frames={}, qt={}, sig={}, start={})
    return store


def clear_cache(ctx) -> None:
    """Drop every cached signal object of this strategy from the context."""
    try:
        ctx.__dict__.pop("_qm_cache", None)
    except AttributeError:
        pass


def _snap(ctx, d) -> pd.Timestamp:
    d = pd.Timestamp(d).normalize()
    fn = getattr(ctx, "trading_day_on_or_before", None)
    return fn(d) if fn is not None else d


def _first_pos(ctx) -> np.ndarray:
    c = _cache(ctx)
    if "first_pos" not in c:
        nn = ctx.close.notna().to_numpy()
        c["first_pos"] = np.where(nn.any(axis=0), nn.argmax(axis=0), nn.shape[0]).astype(np.int64)
    return c["first_pos"]


def _price_restore_factor(ctx, tickers, t: pd.Timestamp) -> np.ndarray:
    """Per ticker: product of ALL Yahoo split ratios with ex-date after ``t``, so ``close * factor`` is the price
    actually quoted on ``t`` (``close`` is split-adjusted to today).  Built from ``ctx.splits`` including the
    non-genuine rows (Yahoo back-adjusts prices for spin-off "splits" too, the context's share-count factor
    ignores them); falls back to ``ctx.split_factor_after`` if the context has no splits table."""
    c = _cache(ctx)
    if "split_idx" not in c:
        sp = getattr(ctx, "splits", None)
        idx = None
        if isinstance(sp, pd.DataFrame) and len(sp) and {"yf_ticker", "date", "ratio"} <= set(sp.columns):
            idx = {}
            for tk, g in sp.groupby("yf_ticker"):
                g = g.sort_values("date")
                suffix = np.cumprod(g["ratio"].to_numpy(dtype="float64")[::-1])[::-1]
                idx[tk] = (g["date"].to_numpy(dtype="datetime64[ns]"), np.append(suffix, 1.0))
        c["split_idx"] = idx
    idx = c["split_idx"]
    if idx is None:
        sf = getattr(ctx, "split_factor_after", None)
        return np.array([sf(tk, t) for tk in tickers], dtype="float64") if sf is not None else np.ones(len(tickers))
    t64 = np.datetime64(t, "ns")
    out = np.ones(len(tickers))
    for i, tk in enumerate(tickers):
        e = idx.get(tk)
        if e is not None:
            out[i] = e[1][np.searchsorted(e[0], t64, side="right")]
    return out


# ----------------------------------------------------------------------------------------------
# per-date eligible frame
# ----------------------------------------------------------------------------------------------
def _frame(ctx, t: pd.Timestamp) -> pd.DataFrame:
    """Eligible universe at ``t`` sorted by momentum (desc, ties by ticker), with all technical inputs.

    ``frame.attrs`` holds the funnel counts n_sp1500 / n_fin / n_price / n_hist / n_mom (sequential).
    """
    cache = _cache(ctx)["frames"]
    if t in cache:
        return cache[t]
    tp = tech.get_technicals(ctx)
    u = ctx.universe(t, UNIVERSE)
    n0 = len(u)
    keep = np.ones(n0, dtype=bool)
    if "gics_sector" in u.columns:
        # Financials and Real Estate: REITs sat inside GICS Financials until 2016-08-31, so excluding both keeps
        # the universe consistent across the reclassification (and matches Novy-Marx's SIC 6xxx exclusion)
        keep &= ~u["gics_sector"].astype(str).str.strip().str.lower().isin(["financials", "real estate"]).to_numpy()
    n_fin = int(keep.sum())
    u = u[keep].reset_index(drop=True)

    pos = ctx.close.index.get_loc(t)
    tick = u["yf_ticker"].to_numpy()
    cols = ctx.close.columns.get_indexer(tick)
    ok_col = cols >= 0
    cols = np.where(ok_col, cols, 0)

    def row(frame):
        return frame.iloc[pos].to_numpy(dtype="float64")[cols]

    close_t = np.where(ok_col, row(ctx.close), np.nan)
    price = close_t * _price_restore_factor(ctx, tick, t)   # raw (as-traded) price on t
    hist = pos - _first_pos(ctx)[cols] + 1
    mom = np.where(ok_col, row(tp.mom), np.nan)

    m_price = np.isfinite(price) & (price >= MIN_PRICE)
    m_hist = m_price & (hist >= MIN_HISTORY)
    m_mom = m_hist & np.isfinite(mom)
    F = pd.DataFrame({
        "cik": u["cik"].to_numpy() if "cik" in u.columns else np.nan,
        "yf_ticker": tick,
        "name": u["name"].to_numpy() if "name" in u.columns else "",
        "gics_sector": u["gics_sector"].to_numpy() if "gics_sector" in u.columns else None,
        "gics_industry_group": u["gics_industry_group"].to_numpy() if "gics_industry_group" in u.columns else None,
        "gics_industry": u["gics_industry"].to_numpy() if "gics_industry" in u.columns else None,
        "sic": u["sic"].to_numpy() if "sic" in u.columns else np.nan,
        "price": price,
        "close": close_t,
        "mom": mom,
        "sma200": np.where(ok_col, row(tp.sma200), np.nan),
        "rsi14": np.where(ok_col, row(tp.rsi14), np.nan),
        "hi52": np.where(ok_col, row(tp.hi52), np.nan),
    })[m_mom]
    F = F.sort_values(["mom", "yf_ticker"], ascending=[False, True], kind="stable").reset_index(drop=True)
    F["mom_rank"] = np.arange(1, len(F) + 1)
    F.attrs.update(n_sp1500=n0, n_fin=n_fin, n_price=int(m_price.sum()), n_hist=int(m_hist.sum()),
                   n_mom=int(m_mom.sum()))
    cache[t] = F
    return F


# ----------------------------------------------------------------------------------------------
# quality
# ----------------------------------------------------------------------------------------------
def _qtable(ctx, t: pd.Timestamp, F: pd.DataFrame) -> pd.DataFrame:
    cache = _cache(ctx)["qt"]
    if t not in cache:
        cache[t] = quality_mod.quality_table(ctx, t, F)
    return cache[t]


def _quality_kw(arm: str, p: dict) -> dict:
    if arm == "Q3a":
        return {"X": p["x_debt"]}
    if arm in ("Q3b", "Q3c", "Q6"):
        return {"Y": p["y_nde"]}
    return {}


def _quality_flags(ctx, t, F: pd.DataFrame, p: dict) -> np.ndarray:
    """Boolean pass flag per row of F (missing fundamentals => False; Q0 => everyone)."""
    arm = p["quality"]
    if arm == "Q0":
        return np.ones(len(F), dtype=bool)
    qt = _qtable(ctx, t, F)
    s = quality_mod.passes(qt, arm, **_quality_kw(arm, p))
    ciks = pd.to_numeric(F["cik"], errors="coerce")
    return ciks.map(s).fillna(False).astype(bool).to_numpy()


def _blend(ctx, t, F: pd.DataFrame, arm: str) -> np.ndarray:
    w = float(arm.split("-", 1)[1])
    qt = _qtable(ctx, t, F)
    ciks = pd.to_numeric(F["cik"], errors="coerce")
    mom = pd.Series(F["mom"].to_numpy(), index=ciks.to_numpy())
    mom = mom[~pd.isna(mom.index)]
    score = quality_mod.blend_score(qt, mom, w)
    return ciks.map(score).to_numpy(dtype="float64")


def _tech_mask(F: pd.DataFrame, technical: str) -> tuple[np.ndarray, np.ndarray]:
    sma_ok = (F["close"] > F["sma200"]).to_numpy()                     # NaN compares False
    rsi = F["rsi14"]
    rsi_ok = ((rsi >= RSI_LO) & (rsi <= RSI_HI)).to_numpy()
    n = len(F)
    if technical == "none":
        return np.ones(n, bool), np.ones(n, bool)
    if technical == "sma":
        return sma_ok, np.ones(n, bool)
    return sma_ok, rsi_ok


# ----------------------------------------------------------------------------------------------
# signal (ranked candidates at one date)
# ----------------------------------------------------------------------------------------------
def _masks(ctx, t, F: pd.DataFrame, p: dict) -> dict:
    """All stage masks (aligned to the rows of F, which is in momentum order) for one parameter set."""
    n = len(F)
    arm = p["quality"]
    is_blend = arm.startswith("Q4-")
    if p["order"] == "MF" and not is_blend:
        k = min(n, int(math.ceil(p["shortlist"] * n - 1e-9)))
        short = np.zeros(n, dtype=bool)
        short[:k] = True
    else:
        short = np.ones(n, dtype=bool)
    if is_blend:
        q = quality_mod.passes(_qtable(ctx, t, F), arm)
        q = pd.to_numeric(F["cik"], errors="coerce").map(q).fillna(False).astype(bool).to_numpy()
    else:
        q = _quality_flags(ctx, t, F, p)
    sma_ok, rsi_ok = _tech_mask(F, p["technical"])
    return dict(short=short, quality=q, sma=sma_ok, rsi=rsi_ok)


def _signal(ctx, t: pd.Timestamp, p: dict) -> dict:
    """Ranked list of ALL names passing every stage at ``t`` (top N is a slice) plus the funnel counts."""
    key = (t, p["quality"], p["technical"], p["order"], round(p["shortlist"], 9), p["x_debt"], p["y_nde"])
    cache = _cache(ctx)["sig"]
    if key in cache:
        return cache[key]
    F = _frame(ctx, t)
    n = len(F)
    m = _masks(ctx, t, F, p)
    s1 = m["short"]
    s2 = s1 & m["quality"]
    s3 = s2 & m["sma"] & m["rsi"]
    idx = np.flatnonzero(s3)
    if p["quality"].startswith("Q4-") and len(idx):
        score = _blend(ctx, t, F, p["quality"])[idx]
        order = np.lexsort((idx, -np.nan_to_num(score, nan=-np.inf)))      # score desc, ties by momentum rank
        idx = idx[order[np.isfinite(score[order])]]
    out = dict(tickers=F["yf_ticker"].to_numpy()[idx].tolist(), n_sp1500=F.attrs.get("n_sp1500", n),
               n_universe=n, n_shortlist=int(s1.sum()), n_quality=int(s2.sum()), n_tech=int(len(idx)))
    cache[key] = out
    return out


# ----------------------------------------------------------------------------------------------
# target weights / backtest
# ----------------------------------------------------------------------------------------------
def target_weights(ctx, params: dict, dates) -> pd.DataFrame:
    """Signal date x yf_ticker weights (rows sum <= 1; an all-zero row = all cash).

    ``dates`` are signal dates (month-end trading days).  The signal at ``t`` is built from prices <= t and
    filings filed before ``t``.  Fewer than N survivors => each at 1/N and the rest stays in cash.
    """
    p = _params(params)
    dates = pd.DatetimeIndex([pd.Timestamp(d).normalize() for d in dates])
    N = p["N"]
    picks = []
    for d in dates:
        picks.append(_signal(ctx, _snap(ctx, d), p)["tickers"][:N])
    cols = sorted({tk for pk in picks for tk in pk})
    col_ix = {c: j for j, c in enumerate(cols)}
    W = np.zeros((len(dates), len(cols)))
    for i, pk in enumerate(picks):
        for tk in pk:
            W[i, col_ix[tk]] = 1.0 / N
    return pd.DataFrame(W, index=dates, columns=cols)


def first_signal_date(ctx, start=START, min_coverage: float | None = None,
                      min_universe: int | None = None) -> pd.Timestamp:
    """First month-end ``>= start`` with a usable cross-section: >= ``min_universe`` eligible names and a
    fundamentals snapshot for >= ``min_coverage`` of them.  Data availability only (no returns involved); it
    is common to every grid cell so all cells share one sample period (XBRL phase-in makes early months empty)."""
    min_coverage = MIN_COVERAGE if min_coverage is None else min_coverage
    min_universe = MIN_UNIVERSE if min_universe is None else min_universe
    cache = _cache(ctx)["start"]
    key = (pd.Timestamp(start), min_coverage, min_universe)
    if key in cache:
        return cache[key]
    found = None
    for t in ctx.month_ends(pd.Timestamp(start), ctx.dates[-1]):
        F = _frame(ctx, t)
        if len(F) < min_universe:
            continue
        fund = ctx.fundamentals(t)
        ciks = pd.to_numeric(F["cik"], errors="coerce").dropna()
        cov = float(ciks.isin(fund.index).mean()) if len(ciks) else 0.0
        if cov >= min_coverage:
            found = t
            break
    if found is None:
        raise ValueError(f"no month-end >= {pd.Timestamp(start).date()} has >= {min_coverage:.0%} fundamentals "
                         f"coverage on >= {min_universe} eligible names")
    cache[key] = found
    return found


def backtest(ctx, params: dict, start=START, end=None, cost_bps: float = 10.0, *, store_weights: bool = True,
             common_start: bool = True) -> engine.BacktestResult:
    """Run the strategy on month-end signals in ``[start, end]`` and return the engine result.

    ``common_start`` moves ``start`` to :func:`first_signal_date` (the same for every cell) when that is later.
    Returns are cut at ``end``, so a window run never sees data after ``end`` (a signal on the last day of the
    window whose trade day lies beyond ``end`` is dropped by the engine).
    """
    p = _params(params)
    end = pd.Timestamp(ctx.dates[-1] if end is None else end)
    start = pd.Timestamp(start)
    if common_start:
        start = max(start, first_signal_date(ctx, start))
    dates = ctx.month_ends(start, end)
    tw = target_weights(ctx, p, dates)
    cfg = _engine_cfg(p, cost_bps)
    sma = tech.get_technicals(ctx).sma200 if cfg.trend_exit_daily else None
    return engine.run(tw, ctx.returns.loc[:end], ctx.rf, cfg, close=ctx.close, sma=sma,
                      store_weights=store_weights)


def _market_holidays_between(a: pd.Timestamp, b: pd.Timestamp) -> bool:
    """True if every weekday in (a, b] is Good Friday or Memorial Day (the only holidays that can fall on the
    last business day of a month)."""
    from dateutil.easter import easter
    days = pd.bdate_range(a + pd.Timedelta(days=1), b)
    for d in days:
        good_friday = pd.Timestamp(easter(d.year)) - pd.Timedelta(days=2)
        memorial = d.month == 5 and d.weekday() == 0 and (d + pd.Timedelta(days=7)).month == 6
        if not (d == good_friday or memorial):
            return False
    return True


def _month_complete(last: pd.Timestamp) -> bool:
    bme = last + pd.offsets.BMonthEnd(0)
    return bme == last or _market_holidays_between(last, bme)


def monthly_returns(params: dict, ctx=None, start=START, end=None, cost_bps: float = 10.0) -> pd.Series:
    """Monthly NET returns for one cell over the full common sample (default ``2011-01`` .. latest data).

    Convenience for ``grid.run_grid(STRATEGY, GRID, monthly_returns)``; the last calendar month is dropped if
    the data end before its last trading day (a partial month is not a monthly observation).
    """
    if ctx is None:
        from quant.data.context import get_context
        ctx = get_context()
    res = backtest(ctx, params, start, end, cost_bps, store_weights=False)
    m = res.monthly()
    last = pd.Timestamp(ctx.returns.loc[: (ctx.dates[-1] if end is None else pd.Timestamp(end))].index[-1])
    if len(m) and not _month_complete(last):
        m = m.iloc[:-1]
    return m


# ----------------------------------------------------------------------------------------------
# diagnostics
# ----------------------------------------------------------------------------------------------
def diagnostics(ctx, params: dict, start=START, end=None, dates=None, common_start: bool = True) -> pd.DataFrame:
    """Per-rebalance funnel: n_sp1500 -> n_universe (eligible) -> n_shortlist -> n_quality -> n_tech -> n_held,
    cash_weight (= 1 - n_held / N, before vol targeting)."""
    p = _params(params)
    if dates is None:
        end = pd.Timestamp(ctx.dates[-1] if end is None else end)
        s = pd.Timestamp(start)
        if common_start:
            s = max(s, first_signal_date(ctx, s))
        dates = ctx.month_ends(s, end)
    rows = []
    for d in dates:
        sg = _signal(ctx, _snap(ctx, d), p)
        held = min(p["N"], sg["n_tech"])
        rows.append(dict(date=pd.Timestamp(d), n_sp1500=sg["n_sp1500"], n_universe=sg["n_universe"],
                         n_shortlist=sg["n_shortlist"], n_quality=sg["n_quality"], n_tech=sg["n_tech"],
                         n_held=held, cash_weight=1.0 - held / p["N"]))
    return pd.DataFrame(rows).set_index("date")


# ----------------------------------------------------------------------------------------------
# live picks
# ----------------------------------------------------------------------------------------------
def book_vol_scalar(ctx, tickers: list[str], weights: np.ndarray, t: pd.Timestamp, vol_target: float | None,
                    lookback: int = VOL_LOOKBACK, cap: float = VOL_CAP) -> tuple[float, float]:
    """(book vol, exposure scalar) exactly as the engine computes them: the target book is back-cast over the
    last ``lookback`` daily returns up to ``t`` (NaN -> 0, uncentered), scalar = min(cap, target / vol)."""
    if vol_target is None:
        return float("nan"), 1.0
    R = ctx.returns.loc[:t, [c for c in tickers if c in ctx.returns.columns]].iloc[-lookback:]
    if len(R) < min(lookback, 21) or R.shape[1] == 0:
        return float("nan"), min(1.0, cap)
    w = np.array([w for c, w in zip(tickers, weights) if c in ctx.returns.columns])
    r_book = R.fillna(0.0).to_numpy() @ w
    vol = float(np.sqrt(252.0 * np.mean(r_book * r_book)))
    if vol < 1e-12:
        return vol, cap
    return vol, float(min(cap, vol_target / vol))



def live_picks(ctx, params: dict, asof=None) -> pd.DataFrame:
    """Ranked table at the latest trading day on or before ``asof`` with every input shown for audit.

    Rows: the momentum shortlist (order MF) or every eligible name (order QF / Q4 arms); selected names first
    (by rank), then the rest by momentum rank.  Columns: rank (rank among names that pass every filter),
    selected (rank <= N), weight (1/N for selected), weight_after_vol (x the vol scalar), dropped_by
    ('' | 'quality' | 'sma200' | 'rsi' | 'beyond_N'; first filter that removes the name), mom_rank, ticker
    (Yahoo symbol = the price-series key), cik, name, gics_sector, gics_industry, price, mom_12_1, sma200,
    sma200_gap (close / SMA200 - 1), rsi14, hi52, pass flags, and the quality metrics of the fundamentals used
    (gpoa, gmar, roe, debt_to_equity, nd_ebitda, net_income_ttm, QL, industry-median flags, period_end, filed).

    ``.attrs``: ``asof``, ``params``, ``funnel`` (stage counts), ``n_held``, ``cash_weight``, ``vol_scalar`` and
    ``book_vol`` (only meaningful when vol targeting is on; scalar is 1.0 otherwise), and ``dropped`` =
    {'quality'|'sma200'|'rsi'|'beyond_N': DataFrame of the names removed by that filter}.
    """
    p = _params(params)
    t = _snap(ctx, ctx.dates[-1] if asof is None else asof)
    F = _frame(ctx, t)
    m = _masks(ctx, t, F, p)
    arm = p["quality"]
    sg = _signal(ctx, t, p)

    d = F.copy()
    d["pass_shortlist"] = m["short"]
    d["pass_quality"] = m["quality"]
    d["pass_sma200"] = m["sma"]
    d["pass_rsi"] = m["rsi"]
    d["sma200_gap"] = d["close"] / d["sma200"] - 1.0
    d["mom_12_1"] = d["mom"]
    stage = np.where(~d["pass_shortlist"], "shortlist", np.where(~d["pass_quality"], "quality",
             np.where(~d["pass_sma200"], "sma200", np.where(~d["pass_rsi"], "rsi", ""))))
    d["dropped_by"] = stage
    d["rank"] = d["yf_ticker"].map({tk: i + 1 for i, tk in enumerate(sg["tickers"])})
    d["selected"] = (d["rank"] <= p["N"]).fillna(False).astype(bool)
    d.loc[(stage == "") & ~d["selected"], "dropped_by"] = "beyond_N"
    d["weight"] = np.where(d["selected"], 1.0 / p["N"], 0.0)

    if arm != "Q0":
        qt = _qtable(ctx, t, F)
        q = qt[[c for c in TABLE_QUALITY_COLS if c in qt.columns]].reindex(pd.to_numeric(d["cik"], errors="coerce").to_numpy())
        q.index = d.index
        d = d.join(q)

    sel = d[d["selected"]].sort_values("rank")
    book_vol, scalar = book_vol_scalar(ctx, sel["yf_ticker"].tolist(), sel["weight"].to_numpy(), t, p["vol_target"])
    d["weight_after_vol"] = d["weight"] * scalar

    base = ["rank", "selected", "weight", "weight_after_vol", "dropped_by", "mom_rank", "ticker", "cik", "name",
            "gics_sector", "gics_industry", "price", "mom_12_1", "sma200", "sma200_gap", "rsi14", "hi52",
            "pass_shortlist", "pass_quality", "pass_sma200", "pass_rsi"]
    d["ticker"] = d["yf_ticker"]
    out = d[d["pass_shortlist"]][base + [c for c in TABLE_QUALITY_COLS if c in d.columns]].copy()
    out["_s"] = ~out["selected"]
    out = out.sort_values(["_s", "rank", "mom_rank"]).drop(columns="_s").reset_index(drop=True)

    metric_cols = [c for c in ("gpoa", "roe", "debt_to_equity", "nd_ebitda", "net_income_ttm") if c in out.columns]
    dropped = {stg: out.loc[out["dropped_by"] == stg,
                            ["ticker", "name", "mom_rank", "mom_12_1", "sma200_gap", "rsi14"] + metric_cols]
                   .reset_index(drop=True) for stg in ("quality", "sma200", "rsi", "beyond_N")}
    n_sel = int(out["selected"].sum())
    out.attrs.update(asof=t, params=p, vol_scalar=scalar, book_vol=book_vol, dropped=dropped, n_held=n_sel,
                     cash_weight=1.0 - n_sel / p["N"],
                     funnel=dict(n_sp1500=sg["n_sp1500"], n_universe=sg["n_universe"], n_shortlist=sg["n_shortlist"],
                                 n_quality=sg["n_quality"], n_tech=sg["n_tech"], n_held=n_sel))
    return out
