"""Performance statistics for periodic return series (research/06 sections 2 and 7).

Conventions
-----------
* ``r`` = simple periodic total returns (decimals), ``b`` = benchmark returns, ``rf`` = risk-free
  return *per period* (a scalar or an array/Series aligned with ``r``), ``ppy`` = periods per year
  (12 monthly, 252 daily).  ``sd`` uses ddof=1.
* Inputs may be numpy arrays, lists or pandas Series.  Functions return plain floats or ndarrays.
* NaN rule: single-series statistics (cagr, ann_vol, drawdowns, ...) drop NaN observations, so the
  annualisation uses the number of *valid* periods.  Two-series statistics (beta, tracking_error,
  information_ratio, hit_rate, capture_ratios, active_cagr, sharpe/sortino with an ``rf`` array,
  horizon_report) use pairwise-complete observations: a period is dropped if *any* input is NaN.
* If every input that is non-scalar is a pandas Series with different indexes, they are aligned on
  the intersection of their indexes (inner join); with ndarrays alignment is positional and the
  lengths must match.
* Ratios whose denominator is (numerically) zero return NaN, never inf.
"""
from __future__ import annotations

import logging
from typing import Mapping

import numpy as np
import pandas as pd

from .stats import align_to_index, stationary_bootstrap_idx

log = logging.getLogger(__name__)

_EPS = 1e-12            # std / downside deviation below this is treated as zero
_NAN = float("nan")

T1_ROWS = ["CAGR", "AnnVol", "Sharpe", "Sortino", "MaxDD", "Calmar", "Beta", "TE", "IR", "ActiveCAGR",
           "HitRate"]


# ---------------------------------------------------------------------------------------------
# input handling
# ---------------------------------------------------------------------------------------------
def _pair(*xs) -> tuple[np.ndarray, ...]:
    """Return equal-length float arrays with every row containing a NaN removed.

    Scalars are broadcast.  Several Series with unequal indexes are inner-joined on the index;
    otherwise inputs are matched by position (lengths must agree).
    """
    series = [x for x in xs if isinstance(x, pd.Series)]
    has_array = any(not isinstance(x, pd.Series) and np.ndim(x) > 0 for x in xs)
    vals = list(xs)
    if len(series) >= 2 and not has_array:
        idx = series[0].index
        if not all(s.index.equals(idx) for s in series[1:]):
            for s in series[1:]:
                idx = idx.intersection(s.index, sort=False)
            if len(idx) == 0:
                log.warning("series share no index labels; result will be empty/NaN "
                            "(monthly series stamped differently? use stats.align_to_index)")
            vals = [x.reindex(idx) if isinstance(x, pd.Series) else x for x in vals]
    n, cols = None, []
    for x in vals:
        if np.ndim(x) == 0:
            cols.append(float(x))
        else:
            a = np.asarray(x, dtype=float).reshape(-1)
            if n is not None and len(a) != n:
                raise ValueError(f"inputs have different lengths ({n} vs {len(a)})")
            n = len(a)
            cols.append(a)
    n = 1 if n is None else n
    cols = [np.full(n, c) if isinstance(c, float) else c for c in cols]
    keep = np.ones(n, dtype=bool)
    for c in cols:
        keep &= ~np.isnan(c)
    return tuple(c[keep] for c in cols)


def _ratio(num: float, den: float) -> float:
    """num/den, NaN when the denominator is (numerically) zero or not finite."""
    return float(num / den) if np.isfinite(den) and den > _EPS else _NAN


def _cagr(x: np.ndarray, ppy: float) -> float:
    n = len(x)
    if n == 0:
        return _NAN
    if np.any(x <= -1.0):                      # wealth hit zero
        return -1.0
    return float(np.expm1(ppy / n * np.log1p(x).sum()))


def _wealth(x: np.ndarray) -> np.ndarray:
    """Wealth path including the starting value: [1, W_1, ..., W_n]."""
    return np.r_[1.0, np.cumprod(1.0 + np.maximum(x, -1.0))]


def _dd_from_wealth(w: np.ndarray) -> np.ndarray:
    return w / np.maximum.accumulate(w) - 1.0


# ---------------------------------------------------------------------------------------------
# return, risk and risk-adjusted performance
# ---------------------------------------------------------------------------------------------
def cagr(r, ppy: float) -> float:
    """Compound annual growth rate:  CAGR = W_n^(ppy/n) - 1,  W_n = prod(1 + r_t)."""
    (x,) = _pair(r)
    return _cagr(x, ppy)


def ann_vol(r, ppy: float) -> float:
    """Annualised volatility:  sd(r) * sqrt(ppy)."""
    (x,) = _pair(r)
    return float(x.std(ddof=1) * np.sqrt(ppy)) if len(x) > 1 else _NAN


def sharpe(r, rf=0.0, ppy: float = 12) -> float:
    """Annualised Sharpe ratio of excess returns:  mean(r - rf) / sd(r - rf) * sqrt(ppy).

    ``rf`` is a per-period scalar or an array/Series aligned with ``r``.
    """
    x, f = _pair(r, rf)
    x = x - f
    if len(x) < 2:
        return _NAN
    sd = x.std(ddof=1)
    return float(x.mean() / sd * np.sqrt(ppy)) if sd > _EPS else _NAN


def sortino(r, rf=0.0, ppy: float = 12) -> float:
    """Annualised Sortino ratio:  mean(r - rf) / DD * sqrt(ppy),  DD = sqrt(mean(min(r - rf, 0)^2)).

    The downside deviation uses the minimum acceptable return rf, the denominator is the number of
    *all* observations (not only the negative ones).  NaN if there is no downside.
    """
    x, f = _pair(r, rf)
    x = x - f
    if len(x) < 2:
        return _NAN
    dd = np.sqrt(np.mean(np.minimum(x, 0.0) ** 2))
    return float(x.mean() / dd * np.sqrt(ppy)) if dd > _EPS else _NAN


def drawdown_series(r) -> np.ndarray:
    """Drawdown path,  DD_t = W_t / max_{s<=t} W_s - 1  (<= 0), measured from the starting wealth 1."""
    (x,) = _pair(r)
    return _dd_from_wealth(_wealth(x))[1:]


def max_drawdown(r) -> float:
    """Maximum drawdown (a negative number, 0.0 if wealth never falls below a prior high)."""
    dd = drawdown_series(r)
    return float(dd.min()) if len(dd) else _NAN


def max_drawdown_dates(r: pd.Series) -> dict:
    """Maximum drawdown with its dates, for a pandas Series (index = period labels).

    Returns dict(max_dd, peak, trough, recovery, peak_is_start):
      peak      label of the last high before the trough (if the high is the pre-sample starting
                wealth, the first index label is returned and ``peak_is_start`` is True),
      trough    label of the lowest wealth relative to its running peak,
      recovery  first label after the trough at which wealth is back at the peak (None if never).
    A series that never draws down has peak = trough = recovery = None and max_dd = 0.0.
    """
    s = pd.Series(r).astype(float).dropna()
    if s.empty:
        return dict(max_dd=_NAN, peak=None, trough=None, recovery=None, peak_is_start=False)
    w = _wealth(s.to_numpy())
    pk = np.maximum.accumulate(w)
    dd = w / pk - 1.0
    i_tr = int(np.argmin(dd[1:])) + 1
    if dd[i_tr] >= 0.0:
        return dict(max_dd=0.0, peak=None, trough=None, recovery=None, peak_is_start=False)
    i_pk = int(np.nonzero(w[: i_tr + 1] == pk[i_tr])[0][-1])
    after = np.nonzero(w[i_tr + 1:] >= pk[i_tr])[0]
    label = lambda i: s.index[max(i - 1, 0)]          # w[i] is the wealth after period i-1 (0-based)
    return dict(max_dd=float(dd[i_tr]), peak=label(i_pk), trough=label(i_tr),
                recovery=label(i_tr + 1 + int(after[0])) if len(after) else None,
                peak_is_start=(i_pk == 0))


def calmar(r, ppy: float) -> float:
    """Calmar ratio:  CAGR / |MaxDD|  (NaN if there is no drawdown)."""
    mdd = max_drawdown(r)
    return _ratio(cagr(r, ppy), abs(mdd)) if np.isfinite(mdd) else _NAN


# ---------------------------------------------------------------------------------------------
# benchmark-relative statistics
# ---------------------------------------------------------------------------------------------
def beta(r, b, rf=0.0) -> float:
    """CAPM beta:  Cov(r - rf, b - rf) / Var(b - rf)  (OLS slope on excess returns)."""
    x, m, f = _pair(r, b, rf)
    if len(x) < 2:
        return _NAN
    x, m = x - f, m - f
    var = m.var(ddof=1)
    return float(np.cov(x, m, ddof=1)[0, 1] / var) if var > _EPS ** 2 else _NAN


def tracking_error(r, b, ppy: float) -> float:
    """Annualised tracking error:  sd(r - b) * sqrt(ppy)."""
    x, m = _pair(r, b)
    return float((x - m).std(ddof=1) * np.sqrt(ppy)) if len(x) > 1 else _NAN


def information_ratio(r, b, ppy: float) -> float:
    """Annualised information ratio:  mean(r - b) / sd(r - b) * sqrt(ppy)."""
    x, m = _pair(r, b)
    if len(x) < 2:
        return _NAN
    a = x - m
    sd = a.std(ddof=1)
    return float(a.mean() / sd * np.sqrt(ppy)) if sd > _EPS else _NAN


def active_cagr(r, b, ppy: float) -> float:
    """Geometric active return:  (1 + CAGR_r) / (1 + CAGR_b) - 1  over the common valid periods."""
    x, m = _pair(r, b)
    cb = _cagr(m, ppy)
    return float((1.0 + _cagr(x, ppy)) / (1.0 + cb) - 1.0) if len(x) and cb > -1.0 else _NAN


def hit_rate(r, b) -> float:
    """Share of periods with r_t > b_t (strictly greater; ties do not count)."""
    x, m = _pair(r, b)
    return float(np.mean(x > m)) if len(x) else _NAN


def capture_ratios(r, b) -> tuple[float, float]:
    """(up, down) capture:  mean(r | b > 0) / mean(b | b > 0)  and  mean(r | b < 0) / mean(b | b < 0).

    Arithmetic-mean version.  A side with no observations returns NaN.
    """
    x, m = _pair(r, b)

    def side(mask):
        if not mask.any():
            return _NAN
        den = m[mask].mean()
        return float(x[mask].mean() / den) if abs(den) > _EPS else _NAN

    return side(m > 0), side(m < 0)


# ---------------------------------------------------------------------------------------------
# turnover and trading costs
# ---------------------------------------------------------------------------------------------
def drifted_weights(w_prev_target, asset_returns, cash_return: float = 0.0) -> np.ndarray:
    """Pre-trade weights after the assets drift for one period (research/06 section 2.3).

        w_pre_i = w_i (1 + r_i) / (1 + r_p),   1 + r_p = sum_i w_i (1 + r_i) + (1 - sum_i w_i)(1 + r_cash)

    ``w_prev_target`` are the previous *target* weights of the risky assets; whatever does not sum
    to one is cash earning ``cash_return`` (so the result still sums to less than one and the
    implied cash weight is ``1 - sum``).  NaN asset returns are treated as 0 (no price move).
    Bug fixed vs Appendix A: it divided by ``sum(w (1+r))`` alone, which silently rescaled a
    partially invested book to 100% invested (a pure-cash residual vanished).  With weights that
    sum to one (cash held as an explicit asset) the two agree.
    """
    w = np.asarray(w_prev_target, dtype=float)
    g = 1.0 + np.nan_to_num(np.asarray(asset_returns, dtype=float), nan=0.0)
    if w.shape != g.shape:
        raise ValueError("weights and returns must have the same shape")
    total = float((w * g).sum() + (1.0 - w.sum()) * (1.0 + cash_return))
    return w * g / total


def turnover_oneway(w_target, w_pre_trade) -> float:
    """One-way turnover:  0.5 * sum_i |w_target_i - w_pre_i|  (100% = the whole book replaced once).

    Only the supplied (risky) positions count; the cash residual is the offsetting leg.  With a flat
    per-side cost c the trading cost is ``c * sum|dw| = 2 c * turnover_oneway``.
    """
    a, b = np.asarray(w_target, dtype=float), np.asarray(w_pre_trade, dtype=float)
    if a.shape != b.shape:
        raise ValueError("weight vectors must have the same shape")
    return float(0.5 * np.abs(a - b).sum())


def apply_costs(gross_r, dw, cost_bps_per_side) -> np.ndarray:
    """Net returns after trading costs:  r_net,t = r_gross,t - sum_i c_i |dw_it|.

    ``dw`` is (T, n_assets) signed trades as fractions of NAV (or (T,) for one asset), the cost is
    per side in bps of traded notional: a scalar or one value per asset.  So a flat 10 bps with 0.2
    of NAV traded costs 2 bps.  NaN trades are treated as no trade; NaN gross returns stay NaN.
    """
    g = np.asarray(gross_r, dtype=float).reshape(-1)
    d = np.nan_to_num(np.asarray(dw, dtype=float), nan=0.0)
    if d.ndim == 1:
        d = d[:, None]
    if d.shape[0] != len(g):
        raise ValueError(f"dw has {d.shape[0]} rows but gross_r has {len(g)}")
    c = np.asarray(cost_bps_per_side, dtype=float) / 1e4
    if c.ndim > 0 and c.size not in (1, d.shape[1]):
        raise ValueError("cost_bps_per_side must be a scalar or have one entry per asset")
    return g - (np.abs(d) * c).sum(axis=1)


# ---------------------------------------------------------------------------------------------
# rolling windows and short-horizon evaluation (research/06 section 7)
# ---------------------------------------------------------------------------------------------
def rolling_compound(r, h: int) -> np.ndarray:
    """Overlapping h-period compounded returns,  R_h(t) = prod_{s=t-h+1..t}(1 + r_s) - 1.

    Returns an array of length n - h + 1 (window ending at observation h-1, ..., n-1); empty if
    h > n.  A window containing a NaN is NaN.  Computed from cumulative log returns, O(n).
    """
    x = np.asarray(r, dtype=float).reshape(-1)
    h = int(h)
    if h < 1:
        raise ValueError("h must be >= 1")
    if h > len(x):
        return np.empty(0)
    nan = np.isnan(x)
    lg = np.where(nan, 0.0, np.log1p(np.maximum(x, -1.0 + 1e-12)))
    c = np.r_[0.0, np.cumsum(lg)]
    k = np.r_[0, np.cumsum(nan)]
    out = np.expm1(c[h:] - c[:-h])
    out[(k[h:] - k[:-h]) > 0] = np.nan
    return out


def horizon_report(r, b, h: int, mean_block: float | None = None, B: int = 2000, seed: int = 0,
                   alpha: float = 0.05, margin: float = 0.02) -> dict:
    """Rolling h-period excess-return distribution and P(beat) (research/06 section 7.1).

    With overlapping compounded windows R_h and E_h = R_h(strategy) - R_h(benchmark)::

        P(beat) = mean(E_h > 0),   P(loss) = mean(R_h < 0),   P(beat by > margin) = mean(E_h > margin)

    The confidence interval for P(beat) (and P(loss)) is a percentile interval from ``B``
    stationary-bootstrap resamples of the *periodic* returns (rows of r and b resampled jointly,
    windows recomputed on each resample), mean block ``mean_block`` (default ``max(h, 3)``, i.e.
    at least the window length).  Windows that straddle a resampling seam are artificial but the
    effect is the same across resamples.  Pairwise-complete NaN handling.

    Returns dict(h, n_obs, n_windows, n_independent (= n_obs/h), mean_block, p_beat, p_beat_ci,
    p_loss, p_loss_ci, p_beat_margin, margin, mean_excess, median_excess, worst_excess, best_excess,
    excess_quantiles {5,25,50,75,95}, return_quantiles {5,25,50,75,95}).
    """
    x, m = _pair(r, b)
    n = len(x)
    if n < h:
        raise ValueError(f"series has {n} valid periods, fewer than the horizon h={h}")
    mean_block = float(mean_block) if mean_block else float(max(h, 3))
    qs = [5, 25, 50, 75, 95]

    Rp, Rb = rolling_compound(x, h), rolling_compound(m, h)
    E = Rp - Rb
    rng = np.random.default_rng(seed)
    beat, loss = np.empty(B), np.empty(B)
    for i in range(B):
        idx = stationary_bootstrap_idx(n, mean_block, rng)
        rp, rb = rolling_compound(x[idx], h), rolling_compound(m[idx], h)
        beat[i] = np.mean(rp - rb > 0)
        loss[i] = np.mean(rp < 0)
    lo, hi = alpha / 2.0, 1.0 - alpha / 2.0
    return dict(
        h=int(h), n_obs=n, n_windows=len(E), n_independent=n / h, mean_block=mean_block,
        p_beat=float(np.mean(E > 0)), p_beat_ci=(float(np.quantile(beat, lo)), float(np.quantile(beat, hi))),
        p_loss=float(np.mean(Rp < 0)), p_loss_ci=(float(np.quantile(loss, lo)), float(np.quantile(loss, hi))),
        p_beat_margin=float(np.mean(E > margin)), margin=margin,
        mean_excess=float(E.mean()), median_excess=float(np.median(E)),
        worst_excess=float(E.min()), best_excess=float(E.max()),
        excess_quantiles={q: float(v) for q, v in zip(qs, np.percentile(E, qs))},
        return_quantiles={q: float(v) for q, v in zip(qs, np.percentile(Rp, qs))},
    )


# ---------------------------------------------------------------------------------------------
# pandas conveniences
# ---------------------------------------------------------------------------------------------
def to_monthly(daily_returns: pd.Series) -> pd.Series:
    """Compound daily simple returns to calendar-month returns.

    Each month is  prod(1 + r_d) - 1  over the days present in that month (NaN days are skipped; a
    month with no valid day is dropped).  The result is labelled with the *last observed date* of
    each month (last trading day), matching ``DataContext.month_ends``.  The final month may be a
    partial month if the data stop mid-month.
    """
    s = pd.Series(daily_returns).astype(float)
    if not isinstance(s.index, pd.DatetimeIndex):
        raise TypeError("daily_returns needs a DatetimeIndex")
    s = s.sort_index()
    per = s.index.to_period("M")
    lg = np.log1p(s.clip(lower=-1.0 + 1e-12))
    total = lg.groupby(per).sum(min_count=1)
    last = s.index.to_series().groupby(per).max()
    out = pd.Series(np.expm1(total.to_numpy()), index=pd.DatetimeIndex(last.to_numpy()), name=s.name)
    return out.dropna()


def _as_series(x, name: str) -> pd.Series:
    if not isinstance(x, pd.Series) or not isinstance(x.index, pd.DatetimeIndex):
        raise TypeError(f"{name} must be a pandas Series with a DatetimeIndex")
    x = x.astype(float)
    return x if x.index.is_monotonic_increasing else x.sort_index()


def summary_table(r: pd.Series, b: pd.Series | None, rf, ppy: float,
                  windows: Mapping[str, tuple] | None = None) -> pd.DataFrame:
    """Table T1 (research/06 section 8): one column per window, one row per statistic.

    Rows: CAGR, AnnVol, Sharpe, Sortino, MaxDD, Calmar, Beta, TE, IR, ActiveCAGR, HitRate.
    ``r``/``b`` are Series with a DatetimeIndex (``b=None`` leaves the benchmark rows NaN); ``rf`` is a
    per-period scalar, a Series (aligned to ``r``; month-stamp mismatches handled by
    ``align_to_index``) or None (= 0).  ``windows`` maps a label to ``(start, end)`` (inclusive,
    either may be None for open-ended; strings or Timestamps); default is the full sample.  MaxDD and
    Calmar use the frequency of the input (monthly input -> monthly drawdown; use daily returns for
    the "MaxDD (daily)" row).  Statistics are computed on the window's valid observations; the number
    of periods per window is in ``df.attrs['n_periods']``.
    """
    r = _as_series(r, "r")
    bs = None if b is None else align_to_index(r.index, _as_series(b, "b"))
    if rf is None:
        rf = 0.0
    rfs = align_to_index(r.index, _as_series(rf, "rf")) if isinstance(rf, pd.Series) else float(rf)
    if windows is None:
        windows = {"Full": (None, None)}

    data, n_periods = {}, {}
    for name, (start, end) in windows.items():
        rw = r.loc[start:end]
        bw = None if bs is None else bs.loc[start:end]
        fw = rfs.loc[start:end] if isinstance(rfs, pd.Series) else rfs
        col = dict(
            CAGR=cagr(rw, ppy), AnnVol=ann_vol(rw, ppy), Sharpe=sharpe(rw, fw, ppy), Sortino=sortino(rw, fw, ppy),
            MaxDD=max_drawdown(rw), Calmar=calmar(rw, ppy),
            Beta=_NAN, TE=_NAN, IR=_NAN, ActiveCAGR=_NAN, HitRate=_NAN,
        )
        if bw is not None:
            col.update(Beta=beta(rw, bw, fw), TE=tracking_error(rw, bw, ppy),
                       IR=information_ratio(rw, bw, ppy), ActiveCAGR=active_cagr(rw, bw, ppy),
                       HitRate=hit_rate(rw, bw))
        data[name] = col
        n_periods[name] = int(rw.notna().sum())
    df = pd.DataFrame(data, index=T1_ROWS, dtype=float)
    df.attrs["n_periods"] = n_periods
    return df
