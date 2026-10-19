"""Vectorised technical signals for the quality-filtered momentum strategy (research/01_momentum.md §6, §11).

Every function takes the WIDE price matrices (index = trading days, columns = yf_ticker) and returns a frame
of the same shape, so a signal for all dates and all names is computed once and read by position later.

Conventions
-----------
* Offsets are TRADING-DAY row offsets of the matrix (a row is a trading day of the NYSE calendar).
* Only the past is used: row ``t`` of every output depends on rows ``<= t`` of the input (tested: truncating
  the panel at ``t`` gives identical values at ``t``).
* ``mom_12_1`` uses ``adjclose`` (split + dividend adjusted, i.e. total return).  ``sma``, ``rsi_wilder`` and
  ``high_52w_ratio`` use the split-adjusted ``close`` (not dividend adjusted).  Reason: these are price-level
  indicators that traders read off the raw chart; a dividend adjustment would shift every historical price by
  the cumulated yield and make "price > 200-day average" slightly easier to pass for high payers in the
  past.  The error from using ``close`` is the ex-dividend price gap (a few %/yr at most), small relative to the
  200-day average and to the RSI band, and it is the same series a live user would see on a chart.
* NaN policy: a window with fewer than 90% valid observations gives NaN (``MIN_VALID_FRAC``), and every NaN
  makes the corresponding filter FAIL downstream ("cannot verify => does not pass").

Definitions
-----------
mom_12_1(t)   = P[t-21] / P[t-252] - 1                    (research §0 item 1; French "12-2", DM "t-12..t-2")
sma(t)        = mean of the last n closes, today included  (research §6.2)
rsi_wilder    exact Wilder (1978): seed = simple average of the first n gains / losses, then
              avg = (avg_prev * (n-1) + cur) / n; RSI = 100 - 100 / (1 + avg_gain / avg_loss);
              avg_loss == 0 -> 100 (50 if avg_gain is also 0)   (research §6.1)
high_52w_ratio(t) = P[t] / max(P[t-251 .. t])              (George & Hwang 2004, adapted)
realized_vol  = sqrt(252 * mean(r^2)) over the last `window` daily returns, UNCENTERED (Barroso-Santa-Clara)
residual_momentum  Blitz, Huij & Martens (2011): at month-end t regress each stock's monthly excess returns over
              months t-36..t-1 on the Fama-French 3 factors; score = sum of the residuals of months t-11..t-1
              divided by their standard deviation (12-1 convention, most recent month skipped)

``get_technicals(ctx)`` returns a lazily evaluated :class:`TechnicalPanel` cached on the DataContext, so the
216 grid cells and every month-end read the same arrays.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

MOM_SKIP = 21
MOM_LOOKBACK = 252
MIN_VALID_FRAC = 0.90
SMA_WINDOW = 200
RSI_WINDOW = 14
RSI_BAND = (50.0, 70.0)
HIGH_WINDOW = 252
VOL_WINDOW = 126
ANN = 252
RESID_WINDOW = 36        # months in the factor regression (Blitz, Huij & Martens 2011)
RESID_FORM = 11          # months t-11..t-1 of residuals summed (skip month t, like 12-1 momentum)


# --------------------------------------------------------------------------------------------------
# momentum
# --------------------------------------------------------------------------------------------------
def mom_12_1(adjclose: pd.DataFrame, skip: int = MOM_SKIP, lookback: int = MOM_LOOKBACK,
             min_valid: float = MIN_VALID_FRAC) -> pd.DataFrame:
    """12-1 momentum ``P[t-skip] / P[t-lookback] - 1`` (trading-day row offsets).

    NaN when either endpoint is missing or when fewer than ``min_valid`` of the days in the formation window
    ``[t-lookback, t-skip]`` (``lookback - skip + 1`` rows) have a price.
    """
    if not 0 <= skip < lookback:
        raise ValueError("need 0 <= skip < lookback")
    P = adjclose.astype("float64")
    P = P.where(P > 0)
    win = lookback - skip + 1
    valid = P.notna().astype("float64").rolling(win, min_periods=win).sum().shift(skip)
    out = P.shift(skip) / P.shift(lookback) - 1.0
    out = out.where(valid >= min_valid * win - 1e-9)
    return out.replace([np.inf, -np.inf], np.nan)


# --------------------------------------------------------------------------------------------------
# moving average / 52-week high / vol
# --------------------------------------------------------------------------------------------------
def sma(close: pd.DataFrame, n: int = SMA_WINDOW, min_frac: float = MIN_VALID_FRAC) -> pd.DataFrame:
    """Simple moving average of the last ``n`` closes (today included).

    Rows with fewer than ``n`` trading days of panel history are NaN; inside a full window the mean is taken
    over the available prices if at least ``min_frac * n`` of them exist (a few missing vendor days do not
    knock a stock out of the screen), else NaN.
    """
    mp = int(np.ceil(min_frac * n - 1e-9))
    out = close.astype("float64").rolling(n, min_periods=mp).mean()
    if n > 1 and len(out):
        out.iloc[: n - 1] = np.nan
    return out


def high_52w_ratio(close: pd.DataFrame, window: int = HIGH_WINDOW, min_frac: float = MIN_VALID_FRAC) -> pd.DataFrame:
    """``P[t] / max(P[t-window+1 .. t])`` in (0, 1]; NaN if the window has < ``min_frac`` valid prices."""
    c = close.astype("float64")
    mp = int(np.ceil(min_frac * window - 1e-9))
    hi = c.rolling(window, min_periods=mp).max()
    if len(hi):
        hi.iloc[: window - 1] = np.nan
    return c / hi


def realized_vol(returns: pd.DataFrame | pd.Series, window: int = VOL_WINDOW, min_frac: float = MIN_VALID_FRAC,
                 ann: int = ANN):
    """Annualised UNCENTERED realised vol ``sqrt(ann * mean(r^2))`` over the last ``window`` returns.

    NaN returns are skipped; the result is NaN with fewer than ``min_frac * window`` observations.
    """
    mp = int(np.ceil(min_frac * window - 1e-9))
    r = returns.astype("float64")
    return np.sqrt(ann * (r * r).rolling(window, min_periods=mp).mean())


# --------------------------------------------------------------------------------------------------
# Wilder RSI
# --------------------------------------------------------------------------------------------------
def rsi_wilder(close: pd.DataFrame | pd.Series, n: int = RSI_WINDOW):
    """Exact Wilder RSI(n) for every column, vectorised across columns (loop over rows only).

    Per column: the first RSI sits ``n`` price changes after the first valid price (seed = simple average of
    those n gains / n losses), later values use Wilder smoothing ``avg = (avg * (n-1) + x) / n``.  A missing
    price row gives NaN and leaves the state untouched; the next valid close is compared with the last valid
    close.  ``avg_loss == 0`` -> 100 (or 50 if ``avg_gain`` is 0 too).
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    if isinstance(close, pd.Series):
        return rsi_wilder(close.to_frame("x"), n)["x"]
    C = close.to_numpy(dtype="float64", copy=False)
    T, N = C.shape
    out = np.full((T, N), np.nan)
    last = np.full(N, np.nan)
    cnt = np.zeros(N, dtype=np.int64)
    sg = np.zeros(N)
    sl = np.zeros(N)
    ag = np.full(N, np.nan)
    al = np.full(N, np.nan)
    with np.errstate(invalid="ignore", divide="ignore"):
        for i in range(T):
            c = C[i]
            v = ~np.isnan(c)
            m = v & ~np.isnan(last)
            d = np.where(m, c - last, 0.0)
            g = np.where(d > 0.0, d, 0.0)
            l = np.where(d < 0.0, -d, 0.0)
            seeded = ~np.isnan(ag)
            upd = m & seeded
            ag = np.where(upd, (ag * (n - 1) + g) / n, ag)
            al = np.where(upd, (al * (n - 1) + l) / n, al)
            s = m & ~seeded
            if s.any():
                sg = np.where(s, sg + g, sg)
                sl = np.where(s, sl + l, sl)
                cnt = cnt + s
                done = s & (cnt == n)
                if done.any():
                    ag = np.where(done, sg / n, ag)
                    al = np.where(done, sl / n, al)
            ok = v & ~np.isnan(ag)
            if ok.any():
                rs = ag / al
                r = 100.0 - 100.0 / (1.0 + rs)
                r = np.where(al == 0.0, np.where(ag > 0.0, 100.0, 50.0), r)
                out[i] = np.where(ok, r, np.nan)
            last = np.where(v, c, last)
    return pd.DataFrame(out, index=close.index, columns=close.columns)


# --------------------------------------------------------------------------------------------------
# cached panel
# --------------------------------------------------------------------------------------------------
class TechnicalPanel:
    """Lazily computed, cached technical matrices for one set of price panels (same shape as ``close``)."""

    def __init__(self, close: pd.DataFrame, adjclose: pd.DataFrame | None = None,
                 returns: pd.DataFrame | None = None, sma_n: int = SMA_WINDOW, rsi_n: int = RSI_WINDOW):
        self.close = close
        self.adjclose = adjclose if adjclose is not None else close
        self.returns = returns
        self.sma_n = sma_n
        self.rsi_n = rsi_n
        self._cache: dict[str, pd.DataFrame] = {}

    def _get(self, key: str, fn):
        if key not in self._cache:
            self._cache[key] = fn()
        return self._cache[key]

    @property
    def mom(self) -> pd.DataFrame:
        return self._get("mom", lambda: mom_12_1(self.adjclose))

    @property
    def sma200(self) -> pd.DataFrame:
        return self._get("sma", lambda: sma(self.close, self.sma_n))

    @property
    def rsi14(self) -> pd.DataFrame:
        return self._get("rsi", lambda: rsi_wilder(self.close, self.rsi_n))

    @property
    def hi52(self) -> pd.DataFrame:
        return self._get("hi52", lambda: high_52w_ratio(self.close))

    def vol126(self) -> pd.DataFrame:
        if self.returns is None:
            raise ValueError("no returns panel attached")
        return self._get("vol", lambda: realized_vol(self.returns))


def residual_momentum(adjclose: pd.DataFrame, ff3_monthly: pd.DataFrame, window: int = RESID_WINDOW,
                      form: int = RESID_FORM) -> pd.DataFrame:
    """Residual (idiosyncratic) momentum of Blitz, Huij & Martens (2011), same shape as ``adjclose``.

    Momentum ranked on a stock's OWN return after stripping out what the market, size and value factors explain.
    Ordinary momentum loads on whatever factor just ran, so it crashes when that factor reverses (Daniel &
    Moskowitz 2016); residual momentum roughly doubles the risk-adjusted return and avoids most of those crashes.

    For each month-end row t (last trading day of a month): regress the monthly excess returns of months
    t-window..t-1 on [1, Mkt-RF, SMB, HML] (one regression per stock, all stocks solved at once); the score is the
    sum of the residuals of the last ``form`` months of the window divided by their standard deviation. Only
    data through month t-1 is used. Stocks with a missing month in the window get NaN. Values are forward-filled
    to the following days, so a mid-month date reads the latest month-end signal.
    """
    me = adjclose.groupby(adjclose.index.to_period("M")).tail(1)          # last trading day of every month
    mret = me.pct_change(fill_method=None)
    periods = me.index.to_period("M")
    f = ff3_monthly.copy()
    f.index = pd.DatetimeIndex(f.index).to_period("M")
    cols = ["Mkt-RF", "SMB", "HML"]
    out = np.full(me.shape, np.nan)
    R = mret.to_numpy(dtype="float64")
    for i in range(window + 1, len(periods)):
        win = periods[i - window:i]
        if not win.isin(f.index).all():
            continue
        F = f.loc[win]
        X = np.column_stack([np.ones(window), F[cols].to_numpy(dtype="float64")])
        Y = R[i - window:i] - F["RF"].to_numpy(dtype="float64")[:, None]
        ok = np.isfinite(Y).all(axis=0)
        if not ok.any():
            continue
        B, *_ = np.linalg.lstsq(X, Y[:, ok], rcond=None)
        E = (Y[:, ok] - X @ B)[-form:]
        sd = E.std(axis=0, ddof=1)
        out[i, ok] = np.where(sd > 0, E.sum(axis=0) / np.where(sd > 0, sd, 1.0), np.nan)
    sig = pd.DataFrame(out, index=me.index, columns=adjclose.columns)
    return sig.reindex(adjclose.index).ffill()


def get_residual_momentum(ctx) -> pd.DataFrame:
    """:func:`residual_momentum` of a DataContext with Ken French's monthly FF3 factors, cached on the context."""
    store = ctx.__dict__.setdefault("_residual_momentum", {})
    key = id(ctx.adjclose)
    if key not in store:
        from quant.data import factors
        store.clear()
        store[key] = residual_momentum(ctx.adjclose, factors.ff3("M"))
    return store[key]


def get_technicals(ctx) -> TechnicalPanel:
    """The :class:`TechnicalPanel` of a DataContext, computed once and cached on the context object."""
    try:
        store = ctx.__dict__.setdefault("_technical_panel", {})
    except AttributeError:               # exotic ctx without __dict__: no caching
        store = {}
    key = (id(ctx.close), id(ctx.adjclose))
    if key not in store:
        store.clear()
        store[key] = TechnicalPanel(ctx.close, ctx.adjclose, getattr(ctx, "returns", None))
    return store[key]
