"""Trading comps with GICS peers (strategy 3, research/04_trading_comps.md).

Monthly rebalance.  At each month-end ``t`` (a trading day close):

1. universe = S&P 900 members on ``t`` (S&P 500 + MidCap 400, ``ctx.universe(t, 'SP900')``, point-in-time GICS;
   the S&P 600 is NOT used because Wikipedia has no S&P 600 history before 2018-09, which would change the
   universe's composition at the train/test split) minus GICS Financials / Real Estate and names without a
   GICS sub-industry, market cap >= $300M, as-traded price >= $5 (research/04 M2).  The peer pool is the
   same universe.
2. for P/E and EV/EBITDA (TTM): GICS sub-industry peers -> industry fallback, 0.5x-2x size window and the
   5 closest (size filter ON) or all valid peers (OFF), caps on peers AND targets, no recent IPO/merger,
   fresh filings, trim to 0.5x-2x of the peer median, benchmark = median of the kept     (``comps.py``)
3. BUY candidate if BOTH multiples are < (1 - theta) x benchmark; score = average discount
4. key-metric gates on the target (ND/EBITDA <= 3, FCF + margin stability, ROIC > WACC) from
   ``quant.signals.key_metrics.key_metrics_table``
5. top 20 by score (ties: lower ND/EBITDA), equal weight 1/max(k, 5), the remainder is cash.  Trade at
   the close of t+1, 10 bps one way (engine).

Module contract (quant/ARCHITECTURE.md): ``DEFAULT``, ``GRID``, ``target_weights``, ``backtest``,
``live_picks``; plus ``monthly_returns(params)`` for ``grid.run_grid`` and ``preregister_grid()``.

Efficiency
----------
The expensive parts are shared across the 54 grid cells and cached on the ``DataContext`` object:

* per (date, basis): universe, ``multiples_table``, ``key_metrics_table`` (one ``_DateState``);
* inside a ``_DateState`` the peer benchmark of a multiple depends only on (size_filter, cap of THAT
  multiple), so the 54 cells need 2 (size) x 3 (P/E cap) + 2 x 3 (EV cap) = 12 benchmark computations per
  date, not 54; theta and the AND combination are cheap vectorised comparisons on top.

Forward multiples cannot be backtested point-in-time with free data (no historical consensus estimates);
``live_picks`` therefore shows yfinance ``forwardPE`` only as an information column.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

from quant import settings
from quant.backtest import engine
from quant.backtest import grid as grid_mod
from quant.signals import comps as C

log = logging.getLogger(__name__)

STRATEGY = "trading_comps"

# --------------------------------------------------------------------------------------------------
# parameters, grid, pre-registration
# --------------------------------------------------------------------------------------------------
# v1 (doc) grid, run 2026-10-19: theta {10,15,20%} x P/E cap {30,40,50} x EV/EBITDA cap {25,35,45} x size filter
# {on, off} = 54 cells, TTM only ("forward" multiples cannot be backtested point-in-time). Train-window findings:
# the size filter hurt in every cell, the caps made almost no difference; selected theta=10%, caps 40/35, no filter.
DOC_DEFAULT: dict = dict(theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis="TTM", mom_filter=0.0)
V1_CHOSEN: dict = dict(theta=0.10, pe_cap=40, ev_cap=35, size_filter=False, basis="TTM", mom_filter=0.0)

# v2 grid: keep the v1 choice of caps / size filter and add the value-trap momentum filter
# (Asness, Moskowitz & Pedersen 2013). Default = the v1 choice, so v2 only changes it if the train data say so.
DEFAULT: dict = dict(V1_CHOSEN)
THETAS = [0.10, 0.15, 0.20]
MOM_FILTERS = [0.0, 0.3, 0.5]
AXES: dict = {"theta": THETAS, "mom_filter": MOM_FILTERS}                       # ordinal
CATEGORICAL: dict = {}
GRID: list[dict] = [dict(DEFAULT, theta=t, mom_filter=m) for t in THETAS for m in MOM_FILTERS]

# fixed (not tuned) knobs: research/04 section 7.1 "Fixed (not tuned) in the main grid"
FIXED: dict = dict(
    universe="SP900", top_n=20, min_hold=5, min_mcap=3.0e8, min_price=5.0,
    exclude_sectors=C.EXCLUDED_SECTORS, gates=("leverage", "quality", "roic"),
    size_lo=0.5, size_hi=2.0, k_min=4, k_max=5, trim_lo=0.5, trim_hi=2.0, k_trim_min=3, stale_days=135,
    km_params=None,
)

TRAIN_START = "2012-01-01"        # 4 fiscal years of history needed (XBRL phase-in): first signal 2012-01-31
TRAIN_END = settings.TRAIN_END    # "2018-12-31"
TEST_START = settings.TEST_START  # "2019-01-01"

PREREG_NOTES = (
    "Pre-registered grid for the trading-comps strategy (research/04_trading_comps.md sections 5-7). "
    "3 theta {0.10,0.15,0.20} x 3 P/E cap {30,40,50} x 3 EV/EBITDA cap {25,35,45} x size filter {on,off} = 54 cells, "
    "TTM basis only. The team doc also lists 'TTM vs forward': forward multiples CANNOT be backtested point-in-time "
    "with free data (there are no historical consensus estimates and realized future earnings would be look-ahead), "
    "so 'forward' is pre-registered as NOT BACKTESTABLE; yfinance forwardPE is shown for the live date as an "
    "information-only cross-check column (not tuned, not in the selection). The last-fiscal-year (LFY) basis is a "
    "pre-registered robustness check run ONLY at the cell chosen on the train window (basis='LFY'); it is not part "
    "of the selection grid and counts as an extra trial in the ledger. Train window: signals 2012-01-31..2018-12-31; "
    "test window 2019-01..latest, looked at once for the chosen cell (plateau rule research/06 5.4, "
    "research/04 7.3-7.4). Rules fixed across all cells: sub-industry peers with industry fallback if < 4, size window "
    "0.5x-2x with the 5 closest peers (size filter on) or all valid peers (off), caps applied to peers AND targets, "
    "negative multiples ignored, stale (>135d) and recent IPO/merger names excluded, peers trimmed to 0.5x-2x of "
    "their median (>= 3 kept), BUY if multiple < (1-theta) x benchmark for BOTH multiples, key-metric gates "
    "(ND/EBITDA <= 3, FCF + margin stability, ROIC > WACC) on the target only, top 20 by average discount, equal "
    "weight 1/max(k,5), 10 bps one-way costs, universe = point-in-time S&P 900 (S&P 500 + MidCap 400) ex "
    "Financials/Real Estate, mcap >= $300M, price >= $5, peers drawn from the same universe. "
    "UNIVERSE CHANGED TO SP900 BEFORE ANY GRID RUN BECAUSE S&P 600 HISTORY STARTS 2018-09 (Wikipedia has no earlier "
    "S&P 600 membership; including it would add about 600 small caps exactly at the 2019 train/test boundary and "
    "confound the comparison). The first version of this registration (2026-10-19T02:09:35Z, same 54-cell grid) named "
    "the S&P 1500; only a train-window sanity run of the DEFAULT cell (stage counts, no return statistics) had been "
    "looked at before the change. "
    "Known biases and data constraints: survivorship of the index membership, GICS as per the membership snapshots "
    "(point-in-time names/codes, not restated), no analyst estimates; names without a GICS sub-industry code are "
    "dropped and counted; peer groups are thinner in a 900-name universe, so the industry fallback and the 'no "
    "signal' share are high and are reported per rebalance (diagnostics); the 135-day staleness gate removes names "
    "that have not yet filed their 10-K at February month-ends - all reported, none tuned."
)


def prereg_extra() -> dict:
    return dict(
        notes=PREREG_NOTES,
        forward_multiples="not_backtestable_point_in_time; live cross-check only (yfinance forwardPE)",
        lfy_robustness="basis='LFY' at the chosen cell only; extra trial, never used for selection",
        fixed_params={k: (list(v) if isinstance(v, tuple) else v) for k, v in FIXED.items()},
        windows=dict(train_start="2012-01-31", train_end=TRAIN_END, test_start=TEST_START,
                     test_policy="single look at the chosen cell"),
        doc_defaults=dict(DEFAULT),
        cost_bps_one_way=10,
        rebalance="month-end signal, trade at next close, hold one month",
    )


def preregister_grid(out_dir=None, force: bool = False):
    """Write ``output/trading_comps/preregistration.json`` (idempotent; refuses a different grid).

    ``force=True`` supersedes an existing registration: a different grid is replaced by ``grid.preregister``
    (old one kept in ``history``); an identical grid whose ``extra`` (notes) changed is re-stamped here, with the
    old registration appended to ``history`` (``grid.preregister`` itself returns early on identical content).
    """
    import json

    extra = prereg_extra()
    path = grid_mod.preregister(STRATEGY, GRID, axes=AXES, categorical=CATEGORICAL, default=DEFAULT,
                                out_dir=out_dir, force=force, extra=extra)
    if force:
        doc = json.loads(path.read_text())
        if doc.get("extra") != json.loads(json.dumps(extra)):
            doc["history"] = list(doc.get("history", [])) + [dict(
                timestamp=doc.get("timestamp"), content_hash=doc.get("content_hash"), n_cells=doc.get("n_cells"),
                grid_hash=doc.get("grid_hash"), superseded_extra=doc.get("extra", {}).get("fixed_params"))]
            doc["extra"] = json.loads(json.dumps(extra))
            doc["timestamp"] = grid_mod._utcnow()
            path.write_text(json.dumps(doc, indent=2) + "\n")
    return path


def resolve_params(params: dict | None = None) -> dict:
    """COMPS defaults < FIXED < DEFAULT < ``params``; validated."""
    p = dict(C.COMPS_DEFAULTS)
    p.update(FIXED)
    p.update(DEFAULT)
    if params:
        p.update(params)
    return C.merge_params(p)


# --------------------------------------------------------------------------------------------------
# point-in-time state per date (cached on the DataContext)
# --------------------------------------------------------------------------------------------------
def _key_metrics(ctx, date, univ: pd.DataFrame, km_params=None) -> pd.DataFrame:
    """Key-metric gates for the universe (imported lazily; the module is written by another agent)."""
    from quant.signals.key_metrics import key_metrics_table
    return key_metrics_table(ctx, date, univ, km_params)


class _DateState:
    """Everything about one decision date that does not depend on theta / caps / size filter."""
    __slots__ = ("date", "basis", "counts", "univ", "mt", "km", "cache")

    def __init__(self, date, basis, counts, univ, mt, km):
        self.date, self.basis, self.counts, self.univ, self.mt, self.km = date, basis, counts, univ, mt, km
        self.cache: dict = {}          # peer benchmarks, valid for this (mt, km) only


def _ctx_cache(ctx, name: str) -> dict:
    try:
        return ctx.__dict__.setdefault(name, {})
    except AttributeError:             # ctx without __dict__: no caching
        return {}


def _trading_day(ctx, date) -> pd.Timestamp:
    f = getattr(ctx, "trading_day_on_or_before", None)
    return pd.Timestamp(f(date)) if f is not None else pd.Timestamp(date).normalize()


def _state(ctx, date, p: dict) -> _DateState:
    date = _trading_day(ctx, date)
    sectors = tuple(p["exclude_sectors"])
    ukey = (date, str(p["universe"]), float(p["min_mcap"]), float(p["min_price"]), sectors, int(p["stale_days"]))
    key = ukey + (p["basis"], repr(p.get("km_params")))
    states = _ctx_cache(ctx, "_tc_states")
    st = states.get(key)
    if st is not None:
        return st

    univ = ctx.universe(date, p["universe"])
    ex = C.exclude_sector_mask(univ, sectors).to_numpy()
    univ_s = univ[~ex]
    # names without a GICS sub-industry (membership rows the data layer could not classify) can neither be a
    # target nor a peer; they are dropped here and counted (n_no_gics)
    classified = C.group_codes(univ_s)[0].notna().to_numpy()
    univ0 = univ_s[classified]
    mt0 = C.multiples_table(ctx, date, univ0, p["basis"], int(p["stale_days"]))
    keep = ((mt0["mcap"] >= p["min_mcap"]) & (mt0["price_raw"] >= p["min_price"])).fillna(False)
    mt = mt0[keep.to_numpy()]
    univ_f = univ0[univ0["cik"].isin(mt.index)]
    # key metrics do not depend on the multiples basis: share them between TTM and LFY runs
    kms = _ctx_cache(ctx, "_tc_km")
    kkey = ukey + (repr(p.get("km_params")),)
    km = kms.get(kkey)
    if km is None:
        km = _key_metrics(ctx, date, univ_f, p.get("km_params"))
        kms[kkey] = km
    counts = dict(n_index=int(len(univ)), n_ex_sector=int(len(univ_s)), n_no_gics=int((~classified).sum()),
                  n_mcap=int(len(mt0)), n_universe=int(len(mt)))
    st = _DateState(date, p["basis"], counts, univ_f, mt, km)
    states[key] = st
    return st


def clear_cache(ctx) -> None:
    """Drop the per-date caches stored on ``ctx``."""
    for name in ("_tc_states", "_tc_km"):
        try:
            ctx.__dict__.pop(name, None)
        except AttributeError:
            pass


# --------------------------------------------------------------------------------------------------
# comps as a second check on other strategies' picks
# --------------------------------------------------------------------------------------------------
# Same peer method (GICS sub-industry -> industry fallback, >= 4 peers, 0.5x-2x trim, median), but no P/E or
# EV/EBITDA cap on the stock being checked: a momentum stock at 60x earnings must get a valuation, not be skipped.
CHECK_PARAMS: dict = dict(V1_CHOSEN, pe_cap=float("inf"), ev_cap=float("inf"))


def valuation_check(ctx, date) -> pd.DataFrame:
    """Peer-relative valuation of every stock in the comps universe on ``date`` (index = cik).

    comps_premium = average over P/E and EV/EBITDA of (multiple / peer median - 1), using whichever of the two has
    a peer benchmark (NaN when neither does: no peers, negative earnings, recent IPO/merger, stale data).
    comps_km_pass = the doc's key metrics all pass (net debt/EBITDA <= 3, free cash flow + stable margins,
    ROIC > WACC).
    """
    d = _trading_day(ctx, date)
    cache = _ctx_cache(ctx, "_tc_valuation_check")
    if d not in cache:
        st, sig = _signals(ctx, d, resolve_params(CHECK_PARAMS))
        prem = pd.concat([-sig["pe_disc"], -sig["ev_disc"]], axis=1).astype(float).mean(axis=1, skipna=True)
        km = (sig["pass_leverage"].fillna(False).astype(bool) & sig["quality_ok"].fillna(False).astype(bool)
              & sig["pass_roic"].fillna(False).astype(bool))
        cache[d] = pd.DataFrame({"comps_premium": prem, "comps_km_pass": km})
    return cache[d]


def check_mask(ctx, date, ciks, max_premium, key_metrics: bool) -> pd.Series:
    """True = the stock passes the comps check (or cannot be checked: not in the comps universe / no peers)."""
    v = valuation_check(ctx, date).reindex(pd.Index(ciks))
    ok = pd.Series(True, index=v.index)
    if max_premium is not None:
        ok &= ~(v["comps_premium"] > float(max_premium))              # NaN premium -> cannot verify -> pass
    if key_metrics:
        ok &= v["comps_km_pass"].fillna(True).astype(bool)
    return ok


def _signals(ctx, date, p: dict, return_peers: bool = False):
    st = _state(ctx, date, p)
    sig = C.comps_signals(ctx, st.date, st.univ, p, st.km, mt=st.mt, cache=st.cache, return_peers=return_peers)
    mf = float(p.get("mom_filter", 0.0) or 0.0)
    if mf > 0:
        # Value-trap guard (Asness, Moskowitz & Pedersen 2013): a stock that screens cheap against its peers but is
        # still in the bottom `mom_filter` of 12-1 momentum across the universe is not bought.
        from quant.signals import technical as tech
        mom = tech.get_technicals(ctx).mom
        u = st.univ.drop_duplicates("cik").set_index("cik")["yf_ticker"]
        vals = mom.loc[st.date].reindex(u.to_numpy()).to_numpy() if st.date in mom.index else float("nan")
        pct = pd.Series(vals, index=u.index).rank(pct=True)
        sig = sig.copy()
        sig["mom_pct"] = pct.reindex(sig.index)
        low = ~(sig["mom_pct"] >= mf)
        sig["fail_mom"] = low
        sig["eligible"] = sig["eligible"].astype(bool) & ~low
    return st, sig


# --------------------------------------------------------------------------------------------------
# portfolio construction
# --------------------------------------------------------------------------------------------------
def rank_candidates(sig: pd.DataFrame) -> pd.DataFrame:
    """Eligible names sorted by score (desc), ties -> lower ND/EBITDA (NaN last), then cik (deterministic)."""
    el = sig[sig["eligible"]]
    if el.empty:
        return el
    score = el["score"].astype(float).round(10).to_numpy()
    nd = el["nd_ebitda"].astype(float).fillna(np.inf).to_numpy()
    cik = el.index.to_numpy()
    order = np.lexsort((cik, nd, -score))
    return el.iloc[order]


def portfolio_from_signals(sig: pd.DataFrame, p: dict) -> pd.Series:
    """Top ``top_n`` by score, weights 1/max(k, min_hold) each (remainder is cash).  Index = yf_ticker."""
    ranked = rank_candidates(sig).head(int(p["top_n"]))
    k = len(ranked)
    if k == 0:
        return pd.Series(dtype=float)
    w = 1.0 / max(k, int(p["min_hold"]))
    return pd.Series(w, index=ranked["yf_ticker"].astype(object).to_numpy(), dtype=float)


def _build(ctx, p: dict, dates) -> tuple[pd.DataFrame, pd.DataFrame]:
    """(target weights, per-rebalance diagnostics) for the given signal dates."""
    rows, diags, idx = [], [], []
    prev = pd.Series(dtype=float)
    for d in dates:
        st, sig = _signals(ctx, d, p)
        w = portfolio_from_signals(sig, p)
        sc = C.stage_counts(sig)
        union = w.index.union(prev.index)
        dw = w.reindex(union).fillna(0.0) - prev.reindex(union).fillna(0.0)
        cash_new, cash_old = 1.0 - w.sum(), 1.0 - prev.sum()
        row = dict(date=st.date, **st.counts, **sc, n_held=int(len(w)), invested=float(w.sum()),
                   cash_weight=float(cash_new), turnover_target=float(0.5 * (dw.abs().sum() + abs(cash_new - cash_old))),
                   k_below_min_hold=bool(len(w) < int(p["min_hold"])))
        diags.append(row)
        rows.append(w)
        idx.append(st.date)
        prev = w
    tw = pd.DataFrame(rows, index=pd.DatetimeIndex(idx)).fillna(0.0)
    tw = tw.astype(float)
    diag = pd.DataFrame(diags).set_index("date")
    return tw, diag


def target_weights(ctx, params: dict | None, dates: list) -> pd.DataFrame:
    """Signal date x yf_ticker weights (rows sum to <= 1; an all-zero row means 'sell everything to cash')."""
    p = resolve_params(params)
    tw, _ = _build(ctx, p, list(dates))
    return tw


def rebalance_diagnostics(ctx, params: dict | None, dates: list) -> pd.DataFrame:
    """Per-rebalance counts at each stage, fallback rate, average peers, holdings (cheap after a backtest)."""
    p = resolve_params(params)
    return _build(ctx, p, list(dates))[1]


# --------------------------------------------------------------------------------------------------
# backtest
# --------------------------------------------------------------------------------------------------
def backtest(ctx, params: dict | None = None, start=TRAIN_START, end=None, cost_bps: float = 10.0,
             store_weights: bool = True) -> engine.BacktestResult:
    """Run the strategy between ``start`` and ``end`` (inclusive).  Nothing after ``end`` is touched:
    prices and signals stop at ``end`` (signals whose trade day would fall after it are ignored).

    The returned ``BacktestResult`` carries an extra attribute ``diagnostics`` (per-rebalance DataFrame).
    """
    p = resolve_params(params)
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp(ctx.returns.index[-1])
    dates = ctx.month_ends(start, end_ts)
    tw, diag = _build(ctx, p, dates)
    returns = ctx.returns.loc[:end_ts]
    rf = ctx.rf.loc[:end_ts]
    res = engine.run(tw, returns, rf, engine.BacktestConfig(cost_bps=cost_bps), store_weights=store_weights)
    res.diagnostics = diag
    return res


def _drop_partial_last_month(m: pd.Series, last_price_date: pd.Timestamp) -> pd.Series:
    """Drop the final calendar month if the data stop more than 4 days before its end."""
    if m.empty:
        return m
    last = m.index[-1]
    if last_price_date < last - pd.Timedelta(days=4):
        return m.iloc[:-1]
    return m


def monthly_returns(params: dict | None = None, ctx=None, start=TRAIN_START, end=None,
                    cost_bps: float = 10.0) -> pd.Series:
    """Monthly NET return series of one grid cell, for ``grid.run_grid(strategy, cells, fn)``.

    Defaults to the whole history (train + test); pass ``end='2018-12-31'`` for train-only work.  A final
    month that is not complete in the price data is dropped.  Run grids serially (``n_jobs=1``) so the
    per-date caches are shared between cells.
    """
    if ctx is None:
        from quant.data.context import get_context
        ctx = get_context()
    res = backtest(ctx, params, start=start, end=end, cost_bps=cost_bps, store_weights=False)
    end_ts = pd.Timestamp(end) if end is not None else pd.Timestamp(ctx.returns.index[-1])
    last_px = pd.Timestamp(ctx.returns.loc[:end_ts].index[-1])
    return _drop_partial_last_month(res.monthly(), last_px)


# --------------------------------------------------------------------------------------------------
# live screen
# --------------------------------------------------------------------------------------------------
GATE_NAMES = ["pe_discount", "ev_discount", "leverage", "quality", "roic"]
# key-metric columns that are shown under their own (non-prefixed) names or duplicate other columns
_KM_SKIP = {"yf_ticker", "gics_sector", "mcap", "nd_ebitda", "roic", "wacc", "fcf_ttm", "om_slope_pp",
            "pass_leverage", "quality_ok", "pass_roic"}


def _gate_failed(row) -> str:
    bad = []
    if not row["pe_pass"]:
        bad.append("pe_discount")
    if not row["ev_pass"]:
        bad.append("ev_discount")
    if not row["pass_leverage"]:
        bad.append("leverage")
    if not row["quality_ok"]:
        bad.append("quality")
    if not row["pass_roic"]:
        bad.append("roic")
    return ";".join(bad)


def _peer_detail(mt: pd.DataFrame, sel_ciks, kept_ciks, col: str) -> str:
    kept = set(kept_ciks)
    parts = []
    for c in sel_ciks:
        r = mt.loc[c]
        s = f"{r['yf_ticker']} {r[col]:.1f}x (${r['mcap'] / 1e9:.1f}B)"
        parts.append(s if c in kept else s + " [trimmed]")
    return "; ".join(parts)


def _first_col(km: pd.DataFrame, exact: list[str], contains: str | None = None) -> str | None:
    for c in exact:
        if c in km.columns:
            return c
    if contains:
        for c in km.columns:
            if contains in str(c).lower() and pd.api.types.is_numeric_dtype(km[c]):
                return c
    return None


_FWD_CACHE: dict = {}


def _yf_forward_pe(tickers: list[str], retries: int = 2, pause: float = 2.0) -> dict:
    """yfinance ``forwardPE`` per ticker (NaN if unavailable or rate-limited).  Information only."""
    import time

    import yfinance as yf
    out: dict = {}
    for t in tickers:
        if t in _FWD_CACHE:
            out[t] = _FWD_CACHE[t]
            continue
        val = np.nan
        for attempt in range(retries + 1):
            try:
                v = yf.Ticker(t).info.get("forwardPE")
                v = float(v) if v is not None else np.nan
                val = v if np.isfinite(v) else np.nan
                break
            except Exception as exc:          # network / rate limit / schema problems must not break the screen
                log.debug("forwardPE failed for %s (attempt %d): %s", t, attempt + 1, exc)
                if attempt < retries:
                    time.sleep(pause)
        out[t] = val
        if np.isfinite(val):
            _FWD_CACHE[t] = val
    return out


def live_picks(ctx, params: dict | None = None, asof=None, near_miss: bool = True, forward_check: bool = True,
               fetch_forward=None, max_near_miss: int = 60) -> pd.DataFrame:
    """Audit table for the live screen at ``asof`` (default: last price date).

    One row per BUY (all gates passed; ``selected`` marks the top ``top_n`` that get weight) and, if
    ``near_miss``, per name that failed exactly one of the five gates (P/E discount, EV/EBITDA discount,
    leverage, quality, ROIC) while both multiples had a benchmark.  Columns: ticker, name, sub-industry,
    peer level / peers (with their multiples, ``[trimmed]`` = dropped by the 0.5x-2x trim) per multiple,
    medians, benchmarks, discounts, score, ND/EBITDA, FCF, margin slope, ROIC, WACC (from the key-metric
    table, passed through as ``km_*`` columns too), yfinance ``forwardPE`` cross-check (target, peer median,
    ``fwd_below_peers``) and the failed gate(s).  ``DataFrame.attrs['diagnostics']`` holds the stage counts,
    fallback rate and average peer count.  ``fetch_forward(list_of_tickers) -> {ticker: forwardPE}`` can be
    injected (tests); the default uses yfinance.
    """
    p = resolve_params(params)
    date = _trading_day(ctx, asof) if asof is not None else pd.Timestamp(ctx.dates[-1])
    st, sig = _signals(ctx, date, p, return_peers=True)
    mt, km = st.mt, st.km

    ranked = rank_candidates(sig)
    top_n, min_hold = int(p["top_n"]), int(p["min_hold"])
    k = min(len(ranked), top_n)
    w = 1.0 / max(k, min_hold) if k else 0.0
    buys = ranked.copy()
    buys["status"] = "BUY"
    buys["rank"] = np.arange(1, len(buys) + 1)
    buys["selected"] = buys["rank"] <= top_n
    buys["weight"] = np.where(buys["selected"], w, 0.0)

    parts = [buys]
    if near_miss:
        m = (sig["n_fail"] == 1) & sig["pe_disc"].notna() & sig["ev_disc"].notna() & ~sig["eligible"]
        nm = sig[m].sort_values("score", ascending=False).head(int(max_near_miss)).copy()
        nm["status"] = "NEAR_MISS"
        nm["rank"] = np.nan
        nm["selected"] = False
        nm["weight"] = 0.0
        parts.append(nm)
    tab = pd.concat(parts) if parts else sig.iloc[0:0]

    # forward P/E cross-check (information only)
    fwd: dict = {}
    if forward_check and len(tab):
        need = set(tab["yf_ticker"])
        for lst in tab["pe_kept"]:
            need.update(lst)
        fetch = fetch_forward or _yf_forward_pe
        try:
            fwd = dict(fetch(sorted(need)))
        except Exception as exc:
            log.warning("forward P/E fetch failed: %s", exc)

    rows = []
    kmj = km.reindex(tab.index) if km is not None and len(km) else pd.DataFrame(index=tab.index)
    fcf_c = _first_col(km, ["fcf_ttm", "fcf"], "fcf") if km is not None else None
    slope_c = _first_col(km, ["om_slope_pp", "margin_slope"], "slope") if km is not None else None
    for cik, r in tab.iterrows():
        pe_peers = r["pe_kept"] if len(r["pe_kept"]) else []
        peer_fwd = [fwd.get(t, np.nan) for t in pe_peers]
        peer_fwd = [v for v in peer_fwd if np.isfinite(v) and v > 0]
        peer_med = float(np.median(peer_fwd)) if peer_fwd else np.nan
        tgt_fwd = fwd.get(r["yf_ticker"], np.nan)
        fwd_below = bool(0 < tgt_fwd < peer_med) if (np.isfinite(tgt_fwd) and np.isfinite(peer_med)) else None
        row = dict(
            status=r["status"], rank=r["rank"], selected=bool(r["selected"]), weight=float(r["weight"]),
            cik=cik, ticker=r["yf_ticker"], name=r["name"], sector=r["gics_sector"],
            sub_industry=r["gics_sub_industry"], mcap=r["mcap"], score=r["score"],
            pe=r["pe"], pe_level=r["pe_level"], pe_npeers=r["pe_npeers"], pe_nkept=r["pe_nkept"],
            pe_median_pretrim=r["pe_median"], pe_bench=r["pe_bench"], pe_disc=r["pe_disc"],
            pe_peers=_peer_detail(mt, r["pe_peer_ciks"], r["pe_kept_ciks"], "pe"),
            ev_ebitda=r["ev_ebitda"], ev_level=r["ev_level"], ev_npeers=r["ev_npeers"], ev_nkept=r["ev_nkept"],
            ev_median_pretrim=r["ev_median"], ev_bench=r["ev_bench"], ev_disc=r["ev_disc"],
            ev_peers=_peer_detail(mt, r["ev_peer_ciks"], r["ev_kept_ciks"], "ev_ebitda"),
            nd_ebitda=r["nd_ebitda"],
            fcf=kmj.loc[cik, fcf_c] if fcf_c and cik in kmj.index else np.nan,
            margin_slope=kmj.loc[cik, slope_c] if slope_c and cik in kmj.index else np.nan,
            roic=kmj.loc[cik, "roic"] if "roic" in kmj.columns else np.nan,
            wacc=kmj.loc[cik, "wacc"] if "wacc" in kmj.columns else np.nan,
            pass_leverage=bool(r["pass_leverage"]), quality_ok=bool(r["quality_ok"]), pass_roic=bool(r["pass_roic"]),
            fwd_pe_yahoo=tgt_fwd, fwd_pe_peer_median=peer_med,
            fwd_below_peers=fwd_below,
            gate_failed=_gate_failed(r),
            price=mt.loc[cik, "price_raw"], period_end=mt.loc[cik, "period_end"],
        )
        if cik in kmj.index:
            for c in kmj.columns:
                if c not in _KM_SKIP:
                    row[f"km_{c}"] = kmj.loc[cik, c]
        rows.append(row)
    out = pd.DataFrame(rows)

    diag = dict(asof=str(st.date.date()), **st.counts, **C.stage_counts(sig), n_buy=int(len(buys)),
                n_selected=int(k), weight_each=float(w), cash_weight=float(1.0 - w * k),
                n_near_miss=int((out["status"] == "NEAR_MISS").sum()) if "status" in out.columns else 0)
    out.attrs["diagnostics"] = diag
    out.attrs["sector_coverage"] = C.coverage_by_sector(sig)
    out.attrs["params"] = {kk: p[kk] for kk in ("theta", "pe_cap", "ev_cap", "size_filter", "basis")}
    return out
