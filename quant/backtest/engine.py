"""Daily portfolio simulator (buy-and-hold drift between rebalances, costs, exits, vol targeting).

Conventions (all of them are tested in ``tests/test_engine.py``)
-----------------------------------------------------------------

Timing
    ``target_weights`` is indexed by *signal date* ``t`` (a trading-day close).  A signal date that is not
    in ``returns.index`` is mapped to the last trading day ``<= t``.  With ``exec_lag = L`` the trade is
    executed at the **close** of the trading day ``L`` rows after the signal day.  Day ``d``'s return is
    the close(d-1) -> close(d) return and is earned by the holdings that existed *before* the trade made
    at close(d).  So with ``L = 1`` the return of day ``t+1`` belongs to the old book and the new book
    first earns on day ``t+2``; with ``L = 0`` the new book earns from day ``t+1``.  If two signal dates
    map to the same trade day the later one wins.  Signals whose trade day falls after the last row of
    ``returns`` are ignored (logged).  A row that is absent from ``target_weights`` means "hold".

Weights and NAV
    All weights are fractions of NAV.  Between rebalances weights drift with returns:
    ``w_i <- w_i (1 + r_i) / (1 + r_p)`` and cash drifts with ``rf``.  The weights right after a trade
    are exactly the target weights (the trading cost is booked in the return series and is not fed back
    into the weights; this is the second-order simplification of research/06 section 2.3).
    Cash is ``1 - sum(stock weights)`` (it may be negative only if ``vol_cap > 1``, i.e. leverage financed
    at ``rf``).  Cash earns ``rf`` (a daily decimal, missing dates -> 0) if ``cash_earns_rf``.

Costs and turnover (per trade day)
    ``dw = w_post_trade - w_drifted_pre_trade``.
    ``cost = cost_bps / 1e4 * sum_stocks |dw|`` (every buy and every sell pays), and
    ``ret_net = ret_gross - cost`` on that day.
    ``turnover = 0.5 * (sum_stocks |dw| + |dw_cash|)`` = max(total buys, total sells) = one-way turnover.
    Cash is counted as an asset in the turnover (as in research/06 section 2.3, "cash is an asset with
    return rf"), but it is never charged a cost.  For a fully invested book rebalanced to a fully
    invested book this is the textbook ``0.5 * sum |dw|``; entering a fully invested book from cash is
    100% one-way turnover; a stop-loss sale of a 10% position is 10% turnover.

Output window
    ``daily`` starts at the first trade day (before that nothing has been traded and the "portfolio" is
    just idle cash).  The first row holds the entry cost and the rf return of the idle cash.

Missing data
    * ``NaN`` return of a held stock *before* its last valid return -> treated as a 0% return.
    * First ``NaN`` day *after* its last valid return (series ended / delisted): the position is sold at
      the last price into cash (the stock earns nothing that day, the cash earns ``rf``) and a trade
      with reason ``'delist'`` is logged.  This forced liquidation is **not** charged a cost and does not
      count as turnover (a cash-out at the last quoted price is not a market trade); put a delisting
      return into ``returns`` if you want one.
    * A target weight on a ticker that has no valid return on the trade day (not yet listed, series
      already ended, or ticker absent from ``returns``) is dropped: the weight stays in cash.  The drop
      is logged (``logging``) and listed in ``BacktestResult.dropped``.  "Valid on the trade day" means
      ``first_valid_return_day <= trade_day <= last_valid_return_day``.

Stop-loss (``cfg.stop_loss = x``)
    For every position the engine tracks the *total-return* (``returns`` come from Adj Close, so
    dividends are included) cumulative performance since the position's entry; entry is the close of
    the trade day on which the book was (re)built, i.e. the entry reference resets at **every
    rebalance** for every name in the new target (HZZ-style "from the rebalance execution price").
    If at a day's close ``cum_return <= -x`` the name is sold at that close (day's return is earned,
    cost applies), the proceeds sit in cash until the next rebalance, reason ``'stop'``.

Trend exit (``cfg.trend_exit_daily`` and ``close``/``sma`` passed)
    If ``close < sma`` at a day's close for a held name it is sold at that close, reason ``'trend'``
    (``NaN`` in either frame -> no exit).  Stops are evaluated before trend exits.  The name can only
    come back at the next rebalance.  On a rebalance day exits are applied to surviving sleeves before
    the book is re-equalized and the net trade is booked as ``'rebalance'`` (to avoid charging a sale
    and a purchase of the same name twice); the freshly built book is never exited on its entry day.

Volatility targeting (``cfg.vol_target``)
    At each rebalance the target book is back-cast over the previous ``vol_lookback`` daily returns
    (rows ``[t-L+1 .. t]`` of ``returns``, ``t`` = signal day, nothing later is touched):
    ``r_book = R_window @ w_target`` (``NaN`` returns -> 0, weights as given, so a target with cash is
    less volatile than a fully invested one), ``vol = sqrt(252 * mean(r_book**2))`` (uncentered),
    ``scalar = min(vol_cap, vol_target / vol)``; all target weights are multiplied by the scalar and the
    rest goes to cash.  If fewer than ``min(vol_lookback, 21)`` observations exist, or the book has
    exactly zero volatility, no information is available and the scalar is ``min(1, vol_cap)`` or
    ``vol_cap`` respectively.  The scalar is computed from signal-date information only (names dropped
    on the trade day do not feed back into it).  ``daily['vol_scalar']`` carries the scalar of the most
    recent rebalance (1.0 when vol targeting is off); ``daily['exposure']`` is the end-of-day sum of
    stock weights (equals ``scalar * sum(target)`` right after a rebalance and drifts afterwards).

Sleeves (``run_sleeves``)
    Each signal opens a sleeve; a sleeve is live for ``hold_months`` signals (it is closed on the trade
    day of the ``hold_months``-th following signal).  At every trade day the live sleeves (including the
    new one) each get ``1/K`` of NAV; an old sleeve keeps its own drifted composition (buy-and-hold since
    its entry) and is only scaled.  While fewer than ``hold_months`` sleeves exist capital is split
    equally across the ones that exist.  Costs, turnover and trades are computed on the *aggregate* net
    change of the book.  ``run`` is the special case of one slot (``hold_months = 1``).
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

logger = logging.getLogger(__name__)

_ANN = 252                 # trading days per year (vol annualisation)
_EPS = 1e-12               # weights below this are "zero"
_MIN_VOL_OBS = 21          # minimum back-cast observations for the vol scalar
_DAILY_COLUMNS = ["ret_gross", "ret_net", "cost", "turnover", "exposure", "n_holdings",
                  "cash_weight", "vol_scalar", "rebalance"]
_TRADE_COLUMNS = ["date", "ticker", "side", "weight_traded", "reason"]
_DROPPED_COLUMNS = ["date", "ticker", "weight", "reason"]


# --------------------------------------------------------------------------------------------------
# public containers
# --------------------------------------------------------------------------------------------------
@dataclass
class BacktestConfig:
    """Simulation settings.  See the module docstring for the exact semantics of every field."""

    exec_lag: int = 1                 # trading days between signal close and trade close
    cost_bps: float = 10.0            # one-way, on every buy and every sell
    stop_loss: float | None = None    # e.g. 0.15 -> sell a name once cumulative return since entry <= -15%
    trend_exit_daily: bool = False    # sell a name when close < sma (needs `close` and `sma` passed to run)
    vol_target: float | None = None   # annualized; exposure = min(vol_cap, vol_target / realized vol)
    vol_lookback: int = 126
    vol_cap: float = 1.0
    cash_earns_rf: bool = True

    def __post_init__(self) -> None:
        if int(self.exec_lag) != self.exec_lag or self.exec_lag < 0:
            raise ValueError(f"exec_lag must be a non-negative integer, got {self.exec_lag!r}")
        if self.cost_bps < 0:
            raise ValueError("cost_bps must be >= 0")
        if self.stop_loss is not None and not (0.0 < self.stop_loss < 1.0):
            raise ValueError("stop_loss must be in (0, 1) or None")
        if self.vol_target is not None and self.vol_target <= 0:
            raise ValueError("vol_target must be > 0 or None")
        if int(self.vol_lookback) != self.vol_lookback or self.vol_lookback < 2:
            raise ValueError("vol_lookback must be an integer >= 2")
        if self.vol_cap <= 0:
            raise ValueError("vol_cap must be > 0")


@dataclass
class BacktestResult:
    """Output of :func:`run` / :func:`run_sleeves`.

    daily    index = trading day from the first trade day on.  Columns: ``ret_gross``, ``ret_net``
             (= gross - cost), ``cost``, ``turnover`` (one-way), ``exposure`` (end-of-day sum of stock
             weights), ``n_holdings``, ``cash_weight``, ``vol_scalar`` (scalar of the latest rebalance),
             ``rebalance`` (bool, True on rebalance trade days).
    weights  end-of-day weights, date x ticker (only tickers ever held; empty if ``store_weights=False``).
    trades   one row per (day, ticker) trade: ``date, ticker, side ('buy'/'sell'), weight_traded``
             (absolute fraction of NAV, > 0) and ``reason`` in {'rebalance','stop','trend','delist'}.
    dropped  target weights that could not be traded (no valid price on the trade day):
             ``date`` (trade day), ``ticker``, ``weight`` (after vol scaling), ``reason``.
    """

    daily: pd.DataFrame
    weights: pd.DataFrame
    trades: pd.DataFrame
    dropped: pd.DataFrame = field(default_factory=lambda: pd.DataFrame(columns=_DROPPED_COLUMNS))

    def monthly(self) -> pd.Series:
        """Net daily returns compounded to calendar months, indexed by calendar month-end dates.

        The first month is partial (the series starts on the first trade day).
        """
        r = self.daily["ret_net"]
        if r.empty:
            return pd.Series(dtype=float, name="ret_net")
        out = (1.0 + r).groupby(r.index.to_period("M")).prod() - 1.0
        out.index = out.index.to_timestamp(how="end").normalize()
        out.name = "ret_net"
        return out


# --------------------------------------------------------------------------------------------------
# public API
# --------------------------------------------------------------------------------------------------
def run(target_weights: pd.DataFrame, returns: pd.DataFrame, rf: pd.Series | None,
        cfg: BacktestConfig | None = None, close: pd.DataFrame | None = None,
        sma: pd.DataFrame | None = None, *, store_weights: bool = True) -> BacktestResult:
    """Simulate a portfolio that is rebuilt to ``target_weights`` on every signal date.

    Parameters
    ----------
    target_weights : index = signal dates, columns = tickers, rows sum to <= 1 (the rest is cash), no
        negative entries (``NaN`` = 0).  An absent date means "hold".
    returns : daily total returns, date x ticker (trading-day index; ``NaN`` where no price).
    rf : daily risk-free rate as a decimal, indexed by date (missing dates -> 0); ``None`` -> 0.
    cfg : :class:`BacktestConfig` (defaults if ``None``).
    close, sma : wide price / moving-average frames, only needed if ``cfg.trend_exit_daily``.
    store_weights : set ``False`` to skip the (date x ticker) weights matrix.

    See the module docstring for all conventions.
    """
    return _simulate(target_weights, 1, returns, rf, cfg or BacktestConfig(), close, sma, store_weights)


def run_sleeves(target_weights: pd.DataFrame, hold_months: int, returns: pd.DataFrame,
                rf: pd.Series | None, cfg: BacktestConfig | None = None,
                close: pd.DataFrame | None = None, sma: pd.DataFrame | None = None, *,
                store_weights: bool = True) -> BacktestResult:
    """Overlapping (Jegadeesh-Titman) sleeves: each signal opens a sleeve held for ``hold_months`` signals.

    The portfolio is the equal-capital combination of the live sleeves, re-equalized at every signal
    trade day (each sleeve keeps its own drifted composition).  With ``hold_months = 1`` this is
    identical to :func:`run`.  Stop-loss / trend exits act per sleeve position.
    """
    if int(hold_months) != hold_months or hold_months < 1:
        raise ValueError("hold_months must be an integer >= 1")
    return _simulate(target_weights, int(hold_months), returns, rf, cfg or BacktestConfig(), close, sma,
                     store_weights)


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
def _empty_result(index: pd.Index) -> BacktestResult:
    daily = pd.DataFrame({c: pd.Series(dtype=float) for c in _DAILY_COLUMNS})
    daily.index = pd.DatetimeIndex([])
    return BacktestResult(daily=daily, weights=pd.DataFrame(index=pd.DatetimeIndex([])),
                          trades=pd.DataFrame(columns=_TRADE_COLUMNS),
                          dropped=pd.DataFrame(columns=_DROPPED_COLUMNS))


def _clean_targets(target_weights: pd.DataFrame) -> pd.DataFrame:
    if not isinstance(target_weights, pd.DataFrame):
        raise TypeError("target_weights must be a DataFrame (signal date x ticker)")
    if not target_weights.columns.is_unique:
        raise ValueError("target_weights has duplicate ticker columns")
    tw = target_weights.copy()
    tw.index = pd.DatetimeIndex(tw.index)
    if not tw.index.is_monotonic_increasing:
        tw = tw.sort_index()
    if not tw.index.is_unique:
        raise ValueError("target_weights has duplicate signal dates")
    vals = tw.to_numpy(dtype=float)
    vals = np.where(np.isnan(vals), 0.0, vals)
    if (vals < 0).any():
        raise ValueError("target_weights must be long-only (negative weights found)")
    if vals.size and (vals.sum(axis=1) > 1.0 + 1e-6).any():
        bad = tw.index[vals.sum(axis=1) > 1.0 + 1e-6][0]
        raise ValueError(f"target_weights row {bad.date()} sums to more than 1")
    return pd.DataFrame(vals, index=tw.index, columns=tw.columns)


def _ns(idx: pd.DatetimeIndex) -> np.ndarray:
    return np.asarray(idx.values).astype("datetime64[ns]")


def _vol_scalar(Rz: np.ndarray, pos_s: int, w: np.ndarray, cfg: BacktestConfig) -> float:
    """Exposure scalar from the target book back-cast over rows [pos_s-L+1, pos_s] (no look-ahead)."""
    L = cfg.vol_lookback
    lo = max(0, pos_s - L + 1)
    if pos_s - lo + 1 < min(L, _MIN_VOL_OBS):
        return min(1.0, cfg.vol_cap)
    nz = np.flatnonzero(w)
    if nz.size == 0:
        return min(1.0, cfg.vol_cap)
    r_book = Rz[lo:pos_s + 1][:, nz] @ w[nz]
    vol = float(np.sqrt(_ANN * np.mean(r_book * r_book)))
    if vol < 1e-12:
        return cfg.vol_cap
    return float(min(cfg.vol_cap, cfg.vol_target / vol))


# --------------------------------------------------------------------------------------------------
# core
# --------------------------------------------------------------------------------------------------
def _simulate(target_weights: pd.DataFrame, hold: int, returns: pd.DataFrame, rf: pd.Series | None,
              cfg: BacktestConfig, close: pd.DataFrame | None, sma: pd.DataFrame | None,
              store_weights: bool) -> BacktestResult:
    # ---------------------------------------------------------------- inputs
    tw = _clean_targets(target_weights)
    if not isinstance(returns, pd.DataFrame):
        raise TypeError("returns must be a DataFrame (date x ticker)")
    if not returns.columns.is_unique:
        raise ValueError("returns has duplicate ticker columns")
    if not returns.index.is_monotonic_increasing:
        returns = returns.sort_index()
    if not returns.index.is_unique:
        raise ValueError("returns has duplicate dates")
    index = pd.DatetimeIndex(returns.index)
    T = len(index)

    use_stop = cfg.stop_loss is not None
    use_trend = bool(cfg.trend_exit_daily)
    if use_trend and (close is None or sma is None):
        raise ValueError("trend_exit_daily=True requires both `close` and `sma`")
    vol_on = cfg.vol_target is not None

    # only tickers that are ever given a weight matter
    cols = [c for c, any_pos in zip(tw.columns, (tw.to_numpy() > 0).any(axis=0)) if any_pos]
    n = len(cols)
    Wt = tw[cols].to_numpy(dtype=float) if n else np.zeros((len(tw), 0))
    R = returns.reindex(columns=cols).to_numpy(dtype=float) if T else np.zeros((0, n))
    valid = ~np.isnan(R)
    Rz = np.where(valid, R, 0.0)
    GR = 1.0 + Rz
    any_valid = valid.any(axis=0) if T else np.zeros(n, dtype=bool)
    first_valid = np.where(any_valid, valid.argmax(axis=0), T) if T else np.zeros(n, dtype=int)
    last_valid = np.where(any_valid, T - 1 - valid[::-1].argmax(axis=0), -1) if T else np.zeros(n, dtype=int)

    delist_at: dict[int, list[int]] = {}
    for j in range(n):
        lv = int(last_valid[j])
        if 0 <= lv < T - 1:
            delist_at.setdefault(lv + 1, []).append(j)

    if rf is None or not cfg.cash_earns_rf:
        rf_v = np.zeros(T)
    else:
        rf_v = pd.Series(rf).reindex(index).fillna(0.0).to_numpy(dtype=float)

    if use_trend:
        Cl = close.reindex(index=index, columns=cols).to_numpy(dtype=float)
        Sm = sma.reindex(index=index, columns=cols).to_numpy(dtype=float)
        with np.errstate(invalid="ignore"):
            TB = Cl < Sm            # NaN compares False -> no exit
        del Cl, Sm

    # ---------------------------------------------------------------- schedule
    events: dict[int, tuple[int, int]] = {}
    if T and len(tw):
        pos_s_all = np.searchsorted(_ns(index), _ns(tw.index), side="right") - 1
        for row, pos_s in enumerate(pos_s_all):
            if pos_s < 0:
                logger.info("signal %s precedes the first trading day; ignored", tw.index[row].date())
                continue
            d = int(pos_s) + int(cfg.exec_lag)
            if d >= T:
                logger.info("signal %s: trade day is beyond the end of the data; ignored",
                            tw.index[row].date())
                continue
            if d in events:
                logger.warning("signals %s and %s map to the same trade day %s; keeping the later",
                               tw.index[events[d][0]].date(), tw.index[row].date(), index[d].date())
            events[d] = (row, int(pos_s))
    if not events:
        logger.warning("no tradable signal dates; empty result")
        return _empty_result(index)

    d0 = min(events)
    T_out = T - d0
    c_rate = cfg.cost_bps / 1e4
    stop_thr = 1.0 - cfg.stop_loss + 1e-12 if use_stop else 0.0

    # ---------------------------------------------------------------- state
    S = hold
    H = np.zeros((S, n))               # per-sleeve stock weights (fractions of total NAV)
    C = np.zeros(S)                    # per-sleeve cash
    E = np.ones((S, n)) if use_stop else None   # per-sleeve cumulative growth since entry
    live = np.zeros(S, dtype=bool)
    idle = 1.0                         # cash before the first trade
    n_events = 0
    cur_scalar = 1.0

    o_gross = np.empty(T_out)
    o_cost = np.zeros(T_out)
    o_turn = np.zeros(T_out)
    o_expo = np.empty(T_out)
    o_cash = np.empty(T_out)
    o_nh = np.empty(T_out, dtype=np.int64)
    o_vs = np.empty(T_out)
    o_reb = np.zeros(T_out, dtype=bool)
    Wmat = np.zeros((T_out, n)) if store_weights else None

    trade_rec: list[tuple[int, int, str, float, str]] = []
    drop_rec: list[tuple[int, int, float]] = []

    def _book_exits(d: int, book: bool) -> float:
        """Apply stop / trend exits at close(d).  Returns total weight sold (NAV fraction)."""
        nonlocal C
        total = 0.0
        held = H > _EPS
        for reason in ("stop", "trend"):
            if reason == "stop":
                if not use_stop:
                    continue
                m = held & (E <= stop_thr)
            else:
                if not use_trend:
                    continue
                m = held & TB[d][None, :]
            if not m.any():
                continue
            sold_j = (H * m).sum(axis=0)
            C += (H * m).sum(axis=1)
            H[m] = 0.0
            held &= ~m
            total += float(sold_j.sum())
            if book:
                for j in np.flatnonzero(sold_j > _EPS):
                    trade_rec.append((d, int(j), "sell", float(sold_j[j]), reason))
        return total

    # ---------------------------------------------------------------- daily loop
    for d in range(d0, T):
        i = d - d0

        # (1) delistings: sell at the last price into cash (first NaN day after the last valid return)
        js = delist_at.get(d)
        if js is not None:
            for j in js:
                col = H[:, j]
                amt = float(col.sum())
                if abs(amt) > _EPS:
                    C += col
                    H[:, j] = 0.0
                    trade_rec.append((d, j, "sell", amt, "delist"))

        # (2) the day's return, earned by the holdings carried in from yesterday
        r = Rz[d]
        f = rf_v[d]
        g = float(H.sum(axis=0) @ r + (C.sum() + idle) * f)
        inv = 1.0 / (1.0 + g)
        H *= GR[d] * inv
        cash_growth = (1.0 + f) * inv
        C *= cash_growth
        idle *= cash_growth
        if use_stop:
            E *= GR[d]

        # (3) trades at the close of d
        cost = 0.0
        turn = 0.0
        ev = events.get(d)
        if ev is None:
            if use_stop or use_trend:
                sold = _book_exits(d, True)
                cost = c_rate * sold
                turn = sold
        else:
            row, pos_s = ev
            pre_w = H.sum(axis=0)
            pre_c = float(C.sum() + idle)
            if use_stop or use_trend:
                _book_exits(d, False)            # silent: the net trade is booked as 'rebalance'
            w_sig = Wt[row]
            scalar = _vol_scalar(Rz, pos_s, w_sig, cfg) if vol_on else 1.0
            w = w_sig * scalar
            tradable = (first_valid <= d) & (last_valid >= d)
            bad = (w > 0) & ~tradable
            if bad.any():
                bad_j = np.flatnonzero(bad)
                for j in bad_j:
                    drop_rec.append((d, int(j), float(w[j])))
                logger.warning("%s: dropped %d target name(s) with no valid price on the trade day "
                               "(weight left in cash): %s", index[d].date(), len(bad_j),
                               ", ".join(str(cols[j]) for j in bad_j[:10]) + (" ..." if len(bad_j) > 10 else ""))
                w = np.where(bad, 0.0, w)

            slot = n_events % S
            n_events += 1
            H[slot] = 0.0
            C[slot] = 0.0
            live[slot] = False
            K = int(live.sum()) + 1
            share_k = 1.0 / K
            if K > 1:
                for k in np.flatnonzero(live):
                    share = float(H[k].sum() + C[k])
                    if share > _EPS:
                        scale = share_k / share
                        H[k] *= scale
                        C[k] *= scale
                    else:                          # wiped-out sleeve: re-capitalise in cash
                        H[k] = 0.0
                        C[k] = share_k
            H[slot] = w * share_k
            C[slot] = (1.0 - float(w.sum())) * share_k
            live[slot] = True
            if use_stop:
                E[slot] = 1.0
            idle = 0.0
            cur_scalar = scalar

            post_w = H.sum(axis=0)
            diff = post_w - pre_w
            abs_diff = np.abs(diff)
            sum_abs = float(abs_diff.sum())
            cost = c_rate * sum_abs
            turn = 0.5 * (sum_abs + abs(float(C.sum()) - pre_c))
            for j in np.flatnonzero(abs_diff > _EPS):
                trade_rec.append((d, int(j), "buy" if diff[j] > 0 else "sell", float(abs_diff[j]),
                                  "rebalance"))
            o_reb[i] = True

        # (4) record end-of-day state
        w_end = H.sum(axis=0)
        o_gross[i] = g
        o_cost[i] = cost
        o_turn[i] = turn
        o_expo[i] = w_end.sum()
        o_cash[i] = C.sum() + idle
        o_nh[i] = np.count_nonzero(w_end > _EPS)
        o_vs[i] = cur_scalar
        if Wmat is not None:
            Wmat[i] = w_end

    # ---------------------------------------------------------------- assemble
    out_index = index[d0:]
    daily = pd.DataFrame({
        "ret_gross": o_gross,
        "ret_net": o_gross - o_cost,
        "cost": o_cost,
        "turnover": o_turn,
        "exposure": o_expo,
        "n_holdings": o_nh,
        "cash_weight": o_cash,
        "vol_scalar": o_vs,
        "rebalance": o_reb,
    }, index=out_index)
    daily.index.name = returns.index.name

    if Wmat is not None:
        keep = (Wmat > _EPS).any(axis=0)
        weights = pd.DataFrame(Wmat[:, keep], index=out_index, columns=[c for c, k in zip(cols, keep) if k])
    else:
        weights = pd.DataFrame(index=out_index)

    if trade_rec:
        tdf = pd.DataFrame(trade_rec, columns=["pos", "j", "side", "weight_traded", "reason"])
        trades = pd.DataFrame({
            "date": index[tdf["pos"].to_numpy()],
            "ticker": [cols[j] for j in tdf["j"].to_numpy()],
            "side": tdf["side"].to_numpy(),
            "weight_traded": tdf["weight_traded"].to_numpy(),
            "reason": tdf["reason"].to_numpy(),
        })
    else:
        trades = pd.DataFrame(columns=_TRADE_COLUMNS)

    if drop_rec:
        ddf = pd.DataFrame(drop_rec, columns=["pos", "j", "weight"])
        dropped = pd.DataFrame({
            "date": index[ddf["pos"].to_numpy()],
            "ticker": [cols[j] for j in ddf["j"].to_numpy()],
            "weight": ddf["weight"].to_numpy(),
            "reason": "no_valid_price_on_trade_day",
        })
    else:
        dropped = pd.DataFrame(columns=_DROPPED_COLUMNS)

    return BacktestResult(daily=daily, weights=weights, trades=trades, dropped=dropped)
