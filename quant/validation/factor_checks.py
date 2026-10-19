"""Long-history, survivorship-free academic evidence for the three strategy ideas (Ken French / AQR data).

Run:  ``.venv/bin/python -m quant.validation.factor_checks [--refresh]``

Writes to ``output/academic/``: ``academic_evidence.md`` (the report), PNG charts and CSV tables.

What it shows
-------------
a. Momentum: winners decile (D10) and WML (D10-D1) over sub-periods and around the Jegadeesh-Titman (1993)
   publication; Barroso-Santa-Clara volatility scaling (WML, and a long-only winners decile); the
   Daniel-Moskowitz bear state and the worst WML months; the current volatility regime.
b. Profitability / quality: RMW and AQR QMJ, and how they co-move with momentum.
c. "Good and cheap" (Magic Formula proxy): the 25 B/M x OP portfolios and E/P sorts.
d. Value (trading comps buy stocks cheap vs peers): HML since 1926.
e. McLean & Pontiff style decay table: in-sample vs out-of-sample vs post-publication mean returns.

All inputs are CRSP-based (French) or AQR portfolios of all listed stocks, so there is no survivorship bias, but
they are factor/portfolio level and gross of costs; they are NOT a test of our stock-level 2011-2026 backtests.
"""
from __future__ import annotations

import argparse
import logging
from dataclasses import dataclass
from pathlib import Path

import matplotlib

matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import matplotlib.ticker as mticker  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from scipy import stats as sps  # noqa: E402

from quant.data import factors as F  # noqa: E402
from quant.settings import OUTPUT  # noqa: E402

try:  # shared implementations from the backtest layer (research/06 appendix A); private fallbacks below
    from quant.backtest import metrics as _bt_metrics  # noqa: E402
    from quant.backtest import stats as _bt_stats  # noqa: E402
except Exception:  # pragma: no cover - the backtest layer is optional for this module
    _bt_metrics = _bt_stats = None

log = logging.getLogger(__name__)

OUT_DIR = OUTPUT / "academic"
TRADING_DAYS = 252
BSC_TARGET = 0.12  # Barroso & Santa-Clara annualized volatility target for the WML spread
BSC_WINDOW = 126  # trading days of daily returns used to estimate volatility
LONG_ONLY_TARGET = 0.20  # annualized volatility target for the long-only winners decile

# Chart palette (reference palette of the dataviz skill, light surface)
C_BLUE, C_ORANGE, C_AQUA, C_VIOLET, C_RED = "#2a78d6", "#eb6834", "#1baf7a", "#6250d6", "#e34948"
C_INK, C_INK2, C_GRID, C_SURFACE = "#0b0b0b", "#52514e", "#e4e3df", "#fcfcfb"


# =====================================================================================
# Statistics helpers (shared quant.backtest.stats / metrics when importable; private fallbacks otherwise)
# =====================================================================================
def newey_west_lags(n: int) -> int:
    """Newey-West (1994) plug-in rule floor(4 (T/100)^(2/9)), at least 4 (research/06 section 3.3 default)."""
    return max(4, int(np.floor(4.0 * (max(n, 1) / 100.0) ** (2.0 / 9.0))))


def _ols_hac_np(y: np.ndarray, X: np.ndarray, lags: int) -> dict:
    """Private fallback: OLS with Newey-West (Bartlett) HAC standard errors, small-sample factor T/(T-k).

    Same estimator as ``quant.backtest.stats.ols_hac`` (and statsmodels ``use_correction=True``).
    ``X`` must already contain the constant column. Returns beta, se, t, r2, n."""
    y = np.asarray(y, dtype=float)
    X = np.asarray(X, dtype=float)
    T, k = X.shape
    xtx_inv = np.linalg.inv(X.T @ X)
    beta = xtx_inv @ X.T @ y
    e = y - X @ beta
    xe = X * e[:, None]
    S = xe.T @ xe
    for lag in range(1, min(lags, T - 1) + 1):
        w = 1.0 - lag / (lags + 1.0)
        G = xe[lag:].T @ xe[:-lag]
        S += w * (G + G.T)
    V = xtx_inv @ S @ xtx_inv * (T / (T - k))
    se = np.sqrt(np.diag(V))
    tss = float(((y - y.mean()) ** 2).sum())
    r2 = 1.0 - float(e @ e) / tss if tss > 0 else np.nan
    return dict(beta=beta, se=se, t=beta / se, r2=r2, n=T)


def ols_hac(y: np.ndarray, X: np.ndarray, lags: int) -> dict:
    """HAC regression via ``quant.backtest.stats.ols_hac`` when importable, else the private fallback."""
    if _bt_stats is not None:
        o = _bt_stats.ols_hac(y, X, lags=lags)
        return dict(beta=o["beta"], se=o["se"], t=o["t"], r2=o["r2"], n=o["n"])
    return _ols_hac_np(y, X, lags)


def regress(y: pd.Series, X: pd.DataFrame, lags: int | None = None) -> dict | None:
    """y on a constant and the columns of X (aligned on dates), HAC t-stats. None if too few observations."""
    d = pd.concat([y.rename("__y__"), X], axis=1, sort=True).dropna()
    T, k = len(d), X.shape[1] + 1
    if T < k + 8:
        return None
    L = lags if lags is not None else newey_west_lags(T)
    Xm = np.column_stack([np.ones(T), d[list(X.columns)].to_numpy()])
    res = ols_hac(d["__y__"].to_numpy(), Xm, L)
    out = dict(
        n=T, lags=L, alpha=res["beta"][0], alpha_t=res["t"][0], r2=res["r2"],
        loadings={c: res["beta"][i + 1] for i, c in enumerate(X.columns)},
        loading_t={c: res["t"][i + 1] for i, c in enumerate(X.columns)},
    )
    return out


def mean_hac(x: pd.Series) -> tuple[float, float]:
    """Mean of a series and its Newey-West t-statistic (regression on a constant)."""
    x = x.dropna()
    if len(x) < 10:
        return float(x.mean()) if len(x) else np.nan, np.nan
    res = ols_hac(x.to_numpy(), np.ones((len(x), 1)), newey_west_lags(len(x)))
    return float(res["beta"][0]), float(res["t"][0])


def _max_drawdown_np(r: pd.Series | np.ndarray) -> float:
    a = np.asarray(r, dtype=float)
    if a.size == 0:
        return np.nan
    w = np.concatenate([[1.0], np.cumprod(1.0 + a)])
    return float((w / np.maximum.accumulate(w) - 1.0).min())


def max_drawdown(r: pd.Series | np.ndarray) -> float:
    """Maximum peak-to-trough drawdown of the compounded return series (wealth starts at 1)."""
    a = np.asarray(r, dtype=float)
    if a.size == 0:
        return np.nan
    return float(_bt_metrics.max_drawdown(a)) if _bt_metrics is not None else _max_drawdown_np(a)


def cagr(r: pd.Series, ppy: int = 12) -> float:
    a = np.asarray(r, dtype=float)
    if a.size == 0:
        return np.nan
    if _bt_metrics is not None:
        return float(_bt_metrics.cagr(a, ppy))
    return float(np.prod(1.0 + a) ** (ppy / a.size) - 1.0)


def perf_row(
    r: pd.Series,
    dd_r: pd.Series | None = None,
    mkt_ex: pd.Series | None = None,
    ff3: pd.DataFrame | None = None,
) -> dict:
    """Monthly performance summary of ``r`` (excess return, or a zero-cost long-short spread).

    ``dd_r`` is the series compounded for the drawdown (total return for long-only legs; defaults to ``r``).
    Alpha rows regress ``r`` on Mkt-RF (CAPM) and optionally on Mkt-RF, SMB, HML (FF3), with HAC t-stats."""
    r = r.dropna()
    n = len(r)
    if n < 2:
        return dict(n=n)
    mean, sd = float(r.mean()), float(r.std(ddof=1))
    row = dict(
        n=n,
        start=r.index[0].strftime("%Y-%m"),
        end=r.index[-1].strftime("%Y-%m"),
        mean_pct_m=100 * mean,
        t_mean=mean / (sd / np.sqrt(n)) if sd > 0 else np.nan,
        ann_mean_pct=1200 * mean,
        ann_vol_pct=100 * sd * np.sqrt(12),
        sharpe=mean / sd * np.sqrt(12) if sd > 0 else np.nan,
        worst_month_pct=100 * float(r.min()),
        max_dd_pct=100 * max_drawdown((dd_r if dd_r is not None else r).reindex(r.index).dropna()),
        skew=float(sps.skew(r.to_numpy(), bias=False)) if n > 3 else np.nan,
    )
    if mkt_ex is not None:
        c = regress(r, mkt_ex.rename("MKT").to_frame())
        if c:
            row.update(capm_alpha_pct_yr=1200 * c["alpha"], capm_alpha_t=c["alpha_t"], capm_beta=c["loadings"]["MKT"])
    if ff3 is not None:
        c = regress(r, ff3[["Mkt-RF", "SMB", "HML"]])
        if c:
            row.update(ff3_alpha_pct_yr=1200 * c["alpha"], ff3_alpha_t=c["alpha_t"])
    return row


def slice_period(x: pd.Series | pd.DataFrame, start: str | None, end: str | None):
    return x.loc[start:end]


def perf_table(
    series: dict[str, tuple[pd.Series, pd.Series | None]],
    periods: list[tuple[str, str | None, str | None]],
    mkt_ex: pd.Series | None,
    ff3: pd.DataFrame | None = None,
) -> pd.DataFrame:
    rows = []
    for name, (r, dd_r) in series.items():
        for label, a, b in periods:
            rr = slice_period(r, a, b)
            dd = slice_period(dd_r, a, b) if dd_r is not None else None
            is_mkt = name.startswith("Market")
            row = perf_row(rr, dd, None if is_mkt else mkt_ex, None if is_mkt else ff3)
            row.update(series=name, period=label)
            rows.append(row)
    df = pd.DataFrame(rows)
    first = ["series", "period", "start", "end", "n"]
    return df[first + [c for c in df.columns if c not in first]]


# =====================================================================================
# Momentum building blocks
# =====================================================================================
def _last_obs_per_month(s: pd.Series) -> pd.Series:
    """Value on the last daily observation of each calendar month, indexed by the calendar month-end."""
    last = s.groupby(s.index.to_period("M")).tail(1)
    last.index = last.index.to_period("M").to_timestamp(how="end").normalize()
    return last


def compound_daily_to_monthly(daily: pd.Series) -> pd.Series:
    """Compound daily returns into calendar-month returns, indexed by the calendar month-end."""
    m = (1.0 + daily).groupby(daily.index.to_period("M")).prod() - 1.0
    m.index = m.index.to_timestamp(how="end").normalize()
    return m


def trailing_vol_ann(daily: pd.Series, window: int = BSC_WINDOW) -> pd.Series:
    """Annualized trailing volatility from the last ``window`` daily returns, UNCENTERED:
    sqrt(252 * mean(r_d^2)) (research/01 section 4.1: 21 * sum(r_d^2)/126 is the monthly variance, x12 annualizes)."""
    var = (daily**2).rolling(window, min_periods=window).mean()
    return np.sqrt(TRADING_DAYS * var)


def bsc_weights(
    daily: pd.Series, target: float = BSC_TARGET, window: int = BSC_WINDOW, cap: float | None = None
) -> pd.Series:
    """Barroso & Santa-Clara weights, indexed by the month in which they APPLY.

    w_t = target / sigma_hat, where sigma_hat uses the previous ``window`` daily returns ending on the last
    trading day of month t-1 (so the weight for month t is fully known at the end of month t-1: no look-ahead).
    ``cap`` (e.g. 1.0) turns it into a no-leverage rule for a long-only book."""
    sig = _last_obs_per_month(trailing_vol_ann(daily, window))
    full = pd.date_range(sig.index[0], sig.index[-1] + pd.offsets.MonthEnd(1), freq="ME")
    sig = sig.reindex(full)
    w = target / sig
    if cap is not None:
        w = w.clip(upper=cap)
    w = w.shift(1)  # decided at the end of the previous month, applied to this month's return
    return w.rename("weight")


def prior_market_return(mkt: pd.Series, window: int = 24) -> pd.Series:
    """Cumulative market return over the previous ``window`` months (months t-window .. t-1), indexed by t.

    Daniel-Moskowitz bear state at month t: this is < 0. The French file starts 1926-07, so for 1927-01..1928-05 the
    available shorter history is used (this reproduces DM's 183 bear months out of 1,035 for 1927-01..2013-03)."""
    cum = np.expm1(np.log1p(mkt).rolling(window, min_periods=1).sum())
    return cum.shift(1).rename("prior24")


# =====================================================================================
# Publication specs (for annotated charts and the McLean-Pontiff table)
# =====================================================================================
@dataclass(frozen=True)
class PubSpec:
    """Original-paper sample and publication month. ``pub`` is the FIRST month counted as post-publication."""

    label: str
    is_start: str
    is_end: str
    pub: str
    source: str


JT93 = PubSpec("JT93", "1965-01", "1989-12", "1993-03", "Jegadeesh & Titman, J. Finance, Mar 1993; sample 1965-1989")
FF92 = PubSpec("FF92", "1963-07", "1990-12", "1992-06", "Fama & French, J. Finance, Jun 1992; sample 1963-1990")
NM13 = PubSpec("NM13", "1963-07", "2010-12", "2013-04", "Novy-Marx, J. Financial Economics 108(1), Apr 2013; sample 1963-2010")
FF15 = PubSpec("FF15", "1963-07", "2013-12", "2015-04", "Fama & French, J. Financial Economics 116(1), Apr 2015; sample 1963-2013")
QMJ13 = PubSpec("QMJ13", "1957-07", "2012-12", "2013-10", "Asness-Frazzini-Pedersen, SSRN working paper Oct 2013; sample to 2012")
QMJ19 = PubSpec("QMJ19", "1957-07", "2016-12", "2019-01", "Asness-Frazzini-Pedersen, Rev. Accounting Studies 24(1), 2019; sample to 2016")
GB05 = PubSpec("GB05", "1988-01", "2004-12", "2005-11", "Greenblatt book (late 2005; month approximate); sample 1988-2004")

MOM_PERIODS: list[tuple[str, str | None, str | None]] = [
    ("Full sample", None, None),
    ("1927-1964 (before JT sample)", "1927-01", "1964-12"),
    ("1965-1989 (JT93 sample)", "1965-01", "1989-12"),
    ("1990-2008", "1990-01", "2008-12"),
    ("2009-2026", "2009-01", None),
    ("2012-2026", "2012-01", None),
    ("1927-2011 (BSC sample)", "1927-01", "2011-12"),
    ("Pre-publication (to 1993-02)", None, "1993-02"),
    ("Post-publication (1993-03 on)", "1993-03", None),
]


# =====================================================================================
# Report writer
# =====================================================================================
def md_table(df: pd.DataFrame, fmt: dict[str, str] | None = None, default: str = "{:.2f}") -> str:
    fmt = fmt or {}
    cols = list(df.columns)
    out = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join("---" for _ in cols) + "|"]
    for tup in df.itertuples(index=False, name=None):
        cells = []
        for c, v in zip(cols, tup):
            if isinstance(v, (float, np.floating)):
                cells.append("n/a" if not np.isfinite(v) else fmt.get(c, default).format(v))
            elif isinstance(v, (int, np.integer)) and not isinstance(v, (bool, np.bool_)):
                cells.append(str(v))
            else:
                cells.append("" if v is None else str(v))
        out.append("| " + " | ".join(cells) + " |")
    return "\n".join(out)


class Report:
    def __init__(self, outdir: Path):
        self.outdir = outdir
        outdir.mkdir(parents=True, exist_ok=True)
        self.parts: list[str] = []
        self.tables: dict[str, pd.DataFrame] = {}
        self.refs: list[dict] = []
        self.charts: list[str] = []

    def md(self, text: str = "") -> None:
        self.parts.append(text)

    def h(self, level: int, text: str) -> None:
        self.parts.append("\n" + "#" * level + " " + text + "\n")

    def table(self, name: str, df: pd.DataFrame, show: list[str] | None = None, fmt: dict[str, str] | None = None,
              rename: dict[str, str] | None = None, caption: str | None = None) -> None:
        self.tables[name] = df
        df.to_csv(self.outdir / f"{name}.csv", index=False, float_format="%.6g")
        v = df[show] if show else df
        if rename:
            v = v.rename(columns=rename)
            fmt = {rename.get(k, k): f for k, f in (fmt or {}).items()}
        if caption:
            self.parts.append(f"**{caption}**\n")
        self.parts.append(md_table(v, fmt) + f"\n\n*CSV: `{name}.csv`*\n")

    def image(self, fname: str, alt: str) -> None:
        self.charts.append(fname)
        self.parts.append(f"![{alt}]({fname})\n")

    def ref(self, item: str, ours: float, theirs: float, tol: float, unit: str = "", note: str = "") -> None:
        ok = bool(np.isfinite(ours) and abs(ours - theirs) <= tol)
        self.refs.append(dict(item=item, ours=ours, research=theirs, diff=ours - theirs, tol=tol, unit=unit, match="OK" if ok else "DIFF", note=note))

    def save(self, fname: str = "academic_evidence.md") -> Path:
        path = self.outdir / fname
        path.write_text("\n".join(self.parts) + "\n", encoding="utf-8")
        return path


# =====================================================================================
# Chart helpers
# =====================================================================================
def _style() -> None:
    plt.rcParams.update({
        "figure.facecolor": C_SURFACE, "axes.facecolor": C_SURFACE, "savefig.facecolor": C_SURFACE,
        "axes.edgecolor": C_GRID, "axes.labelcolor": C_INK2, "text.color": C_INK, "xtick.color": C_INK2,
        "ytick.color": C_INK2, "axes.grid": True, "grid.color": C_GRID, "grid.linewidth": 0.6,
        "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False, "font.size": 8.5, "axes.titlesize": 9.5,
        "axes.titleweight": "bold", "legend.frameon": False, "lines.linewidth": 1.6,
    })


def _pub_lines(ax, spec: PubSpec | None, label: bool = True) -> None:
    if spec is None:
        return
    ax.axvline(pd.Timestamp(spec.is_end) + pd.offsets.MonthEnd(0), color=C_INK2, lw=0.9, ls=":", zorder=1)
    ax.axvline(pd.Timestamp(spec.pub), color=C_RED, lw=1.1, ls="--", zorder=1)
    if label:
        ax.text(pd.Timestamp(spec.pub), 0.98, f" pub {spec.pub}", transform=ax.get_xaxis_transform(), color=C_RED,
                fontsize=7, va="top", ha="left")


def _wealth_axis(ax) -> None:
    """Log-scale y axis for growth-of-$1 charts with readable tick labels (call after plotting)."""
    ax.set_yscale("log")
    lo, hi = ax.get_ylim()
    subs = (1.0, 2.0, 5.0) if hi / lo < 100 else (1.0,)
    ax.yaxis.set_major_locator(mticker.LogLocator(base=10, subs=subs))
    ax.yaxis.set_major_formatter(mticker.FuncFormatter(lambda v, _: f"{v:,.0f}" if v >= 1 else f"{v:g}"))
    ax.yaxis.set_minor_locator(mticker.NullLocator())
    ax.yaxis.set_minor_formatter(mticker.NullFormatter())


def _save(fig, outdir: Path, fname: str) -> str:
    fig.savefig(outdir / fname, dpi=140, bbox_inches="tight")
    plt.close(fig)
    return fname


# =====================================================================================
# Data bundle
# =====================================================================================
@dataclass
class Data:
    dec_vw: pd.DataFrame
    dec_ew: pd.DataFrame
    dec_vw_d: pd.DataFrame
    dec_ew_d: pd.DataFrame
    ff3: pd.DataFrame
    ff5: pd.DataFrame
    mom: pd.Series
    mkt: pd.Series  # total market return
    mkt_ex: pd.Series  # Mkt-RF
    rf: pd.Series
    bmop_vw: pd.DataFrame
    bmop_ew: pd.DataFrame
    ep_vw: pd.DataFrame
    ep_ew: pd.DataFrame
    qmj: pd.Series | None
    qmj_error: str


def load_data(refresh: bool = False) -> Data:
    kw = dict(force=refresh)
    ff3 = F.ff3("M", **kw)
    try:
        q = F.qmj("M", "USA", **kw)
        qerr = ""
    except Exception as exc:  # AQR may block downloads: continue without QMJ
        q, qerr = None, str(exc)
        log.warning("AQR QMJ unavailable: %s", exc)
    return Data(
        dec_vw=F.mom_deciles("M", "vw", **kw), dec_ew=F.mom_deciles("M", "ew", **kw),
        dec_vw_d=F.mom_deciles("D", "vw", **kw), dec_ew_d=F.mom_deciles("D", "ew", **kw),
        ff3=ff3, ff5=F.ff5("M", **kw), mom=F.mom("M", **kw)["Mom"],
        mkt=(ff3["Mkt-RF"] + ff3["RF"]).rename("Mkt"), mkt_ex=ff3["Mkt-RF"], rf=ff3["RF"],
        bmop_vw=F.bm_op_25("M", "vw", **kw), bmop_ew=F.bm_op_25("M", "ew", **kw),
        ep_vw=F.ep_portfolios("vw", **kw), ep_ew=F.ep_portfolios("ew", **kw), qmj=q, qmj_error=qerr,
    )


def _pct(x: float, d: int = 1) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{d}f}%"


def _fmt_perf_show() -> tuple[list[str], dict[str, str], dict[str, str]]:
    show = ["period", "n", "mean_pct_m", "t_mean", "ann_vol_pct", "sharpe", "worst_month_pct", "max_dd_pct", "capm_alpha_pct_yr", "capm_alpha_t"]
    ren = {"period": "Period", "mean_pct_m": "Mean %/mo", "t_mean": "t(mean)", "ann_vol_pct": "Vol %/yr", "sharpe": "Sharpe",
           "worst_month_pct": "Worst mo %", "max_dd_pct": "Max DD %", "capm_alpha_pct_yr": "CAPM a %/yr", "capm_alpha_t": "t(a, NW)"}
    fmt = {"Mean %/mo": "{:.2f}", "t(mean)": "{:.1f}", "Vol %/yr": "{:.1f}", "Sharpe": "{:.2f}", "Worst mo %": "{:.1f}",
           "Max DD %": "{:.1f}", "CAPM a %/yr": "{:.1f}", "t(a, NW)": "{:.1f}"}
    return show, ren, fmt


def _row(df: pd.DataFrame, series: str, period: str) -> pd.Series:
    sub = df[(df["series"] == series) & (df["period"] == period)]
    return sub.iloc[0]


# =====================================================================================
# a. Momentum
# =====================================================================================
def section_momentum(R: Report, D: Data, K: dict) -> None:
    R.h(2, "A. Momentum (Jegadeesh-Titman 1993; Daniel-Moskowitz 2016; Barroso-Santa-Clara 2015)")
    dm, dme = D.dec_vw, D.dec_ew
    wml, wml_ew = dm["D10"] - dm["D1"], dme["D10"] - dme["D1"]
    d10x, d10x_ew = dm["D10"] - D.rf, dme["D10"] - D.rf
    mkt_ex = D.mkt_ex

    # ---- A1: performance by period
    series = {
        "WML (D10-D1, VW)": (wml, None),
        "Winners D10 (VW), excess": (d10x, dm["D10"]),
        "WML (D10-D1, EW)": (wml_ew, None),
        "Winners D10 (EW), excess": (d10x_ew, dme["D10"]),
        "French Mom 2x3": (D.mom, None),
        "Market (Mkt-RF)": (mkt_ex, D.mkt),
    }
    perf = perf_table(series, MOM_PERIODS, mkt_ex, D.ff3)
    R.h(3, "A1. Winners decile and WML across periods")
    R.md(
        "Source: Ken French `10_Portfolios_Prior_12_2` (monthly, formed on months -12..-2, NYSE/AMEX/NASDAQ, CRSP). D1 = losers, D10 = winners; "
        "WML = D10 - D1. Winners are measured as EXCESS returns over the one-month T-bill; WML and Mom 2x3 are zero-cost spreads. "
        "Max DD is on the compounded total return for long-only legs and on the spread itself for WML. CAPM alpha regresses the series on Mkt-RF "
        "with Newey-West t (lags max(4, NW rule)). t(mean) is the plain i.i.d. t-statistic. No costs.\n"
    )
    show, ren, fmt = _fmt_perf_show()
    for name in series:
        sub = perf[perf["series"] == name]
        R.md(f"**{name}**\n")
        R.md(md_table(sub[show].rename(columns=ren), fmt) + "\n")
    R.tables["momentum_performance"] = perf
    perf.to_csv(R.outdir / "momentum_performance.csv", index=False, float_format="%.6g")
    R.md("*CSV: `momentum_performance.csv` (all series, all periods, incl. FF3 alpha columns)*\n")

    # reference checks vs research/01 section 9 and section 8
    refs = {
        ("WML (D10-D1, VW)", "Full sample"): (13.6, 27.6, 0.49, -77.7, -95.6),
        ("WML (D10-D1, VW)", "1927-2011 (BSC sample)"): (15.0, 27.4, 0.55, -77.7, -95.6),
        ("WML (D10-D1, VW)", "1965-1989 (JT93 sample)"): (19.7, 19.2, 1.03, -19.7, -29.0),
        ("WML (D10-D1, VW)", "1990-2008"): (18.9, 26.5, 0.71, -41.8, -51.6),
        ("WML (D10-D1, VW)", "2009-2026"): (0.8, 32.1, 0.03, -45.2, -80.8),
    }
    for (s, p), (m, v, sh, w, dd) in refs.items():
        r = _row(perf, s, p)
        R.ref(f"WML VW {p}: mean %/yr", r["ann_mean_pct"], m, 0.2)
        R.ref(f"WML VW {p}: vol %/yr", r["ann_vol_pct"], v, 0.2)
        R.ref(f"WML VW {p}: Sharpe", r["sharpe"], sh, 0.02)
        R.ref(f"WML VW {p}: worst month %", r["worst_month_pct"], w, 0.2)
        R.ref(f"WML VW {p}: max DD %", r["max_dd_pct"], dd, 0.3)
    refs_w = {
        "Full sample": (15.0, 22.6, 0.66, 8.3, 0.45, 7.4, 0.45),
        "1927-2011 (BSC sample)": (14.5, 22.8, 0.64, 7.4, 0.39, 8.2, 0.49),
        "1965-1989 (JT93 sample)": (13.5, 21.9, 0.62, 4.3, 0.27, 9.9, 0.80),
        "1990-2008": (11.5, 21.9, 0.52, 4.4, 0.29, 11.1, 0.68),
        "2009-2026": (16.8, 22.0, 0.76, 13.9, 0.91, -0.8, -0.05),
    }
    for p, (m, v, sh, mm, msh, momm, momsh) in refs_w.items():
        r = _row(perf, "Winners D10 (VW), excess", p)
        R.ref(f"Winners D10 VW excess {p}: mean %/yr", r["ann_mean_pct"], m, 0.2)
        R.ref(f"Winners D10 VW excess {p}: vol %/yr", r["ann_vol_pct"], v, 0.2)
        R.ref(f"Winners D10 VW excess {p}: Sharpe", r["sharpe"], sh, 0.02)
        r = _row(perf, "Market (Mkt-RF)", p)
        R.ref(f"Market excess {p}: mean %/yr", r["ann_mean_pct"], mm, 0.2)
        R.ref(f"Market excess {p}: Sharpe", r["sharpe"], msh, 0.02)
        r = _row(perf, "French Mom 2x3", p)
        R.ref(f"French Mom 2x3 {p}: mean %/yr", r["ann_mean_pct"], momm, 0.2)
        R.ref(f"French Mom 2x3 {p}: Sharpe", r["sharpe"], momsh, 0.02)
    r = _row(perf, "Winners D10 (EW), excess", "Full sample")
    R.ref("Winners D10 EW excess Full sample: mean %/yr", r["ann_mean_pct"], 17.6, 0.2)
    R.ref("Winners D10 EW excess Full sample: vol %/yr", r["ann_vol_pct"], 25.2, 0.2)
    R.ref("Winners D10 EW excess Full sample: Sharpe", r["sharpe"], 0.70, 0.02)
    R.ref("Winners D10 EW Full sample: max DD %", r["max_dd_pct"], -73.0, 1.0)
    R.ref("Winners D10 EW excess 1965-1989: Sharpe", _row(perf, "Winners D10 (EW), excess", "1965-1989 (JT93 sample)")["sharpe"], 0.71, 0.02)
    R.ref("Winners D10 EW excess 2009-2026: Sharpe", _row(perf, "Winners D10 (EW), excess", "2009-2026")["sharpe"], 0.60, 0.02)
    r = _row(perf, "WML (D10-D1, EW)", "Full sample")
    R.ref("WML EW Full sample: mean %/yr", r["ann_mean_pct"], 10.1, 0.2)
    R.ref("WML EW Full sample: vol %/yr", r["ann_vol_pct"], 26.2, 0.2)
    R.ref("WML EW Full sample: Sharpe", r["sharpe"], 0.39, 0.02)
    R.ref("WML EW Full sample: worst month %", r["worst_month_pct"], -87.0, 1.0)
    # winners-decile alpha by period (research/01 section 8)
    alpha_ref = {"1927-1964 (before JT sample)": (7.5, 3.8), "1965-1989 (JT93 sample)": (8.3, 3.9), "1990-2008": (6.3, 2.1),
                 "2009-2026": (0.9, 0.3), "2012-2026": (2.1, 0.6)}
    for p, (a, t) in alpha_ref.items():
        r = _row(perf, "Winners D10 (VW), excess", p)
        R.ref(f"Winners D10 VW CAPM alpha {p}: %/yr", r["capm_alpha_pct_yr"], a, 0.3)
        R.ref(f"Winners D10 VW CAPM alpha {p}: t (NW)", r["capm_alpha_t"], t, 0.3)
    R.ref("Winners D10 VW FF3 alpha 2009-2026: %/yr", _row(perf, "Winners D10 (VW), excess", "2009-2026")["ff3_alpha_pct_yr"], 0.7, 0.3)

    pre_w, post_w = _row(perf, "WML (D10-D1, VW)", "Pre-publication (to 1993-02)"), _row(perf, "WML (D10-D1, VW)", "Post-publication (1993-03 on)")
    pre_d, post_d = _row(perf, "Winners D10 (VW), excess", "Pre-publication (to 1993-02)"), _row(perf, "Winners D10 (VW), excess", "Post-publication (1993-03 on)")
    full_w, rec_w = _row(perf, "WML (D10-D1, VW)", "Full sample"), _row(perf, "WML (D10-D1, VW)", "2009-2026")
    K.update(
        wml_full_sharpe=full_w["sharpe"], wml_full_mean=full_w["ann_mean_pct"], wml_09_sharpe=rec_w["sharpe"], wml_09_mean=rec_w["ann_mean_pct"],
        wml_pre_sharpe=pre_w["sharpe"], wml_post_sharpe=post_w["sharpe"], wml_pre_mean=pre_w["ann_mean_pct"], wml_post_mean=post_w["ann_mean_pct"],
        d10_alpha_9026=_row(perf, "Winners D10 (VW), excess", "2009-2026")["capm_alpha_pct_yr"],
        d10_alpha_9026_t=_row(perf, "Winners D10 (VW), excess", "2009-2026")["capm_alpha_t"],
        d10_alpha_pre=pre_d["capm_alpha_pct_yr"], d10_alpha_pre_t=pre_d["capm_alpha_t"],
        d10_alpha_post=post_d["capm_alpha_pct_yr"], d10_alpha_post_t=post_d["capm_alpha_t"],
        d10_alpha_6589=_row(perf, "Winners D10 (VW), excess", "1965-1989 (JT93 sample)")["capm_alpha_pct_yr"],
        d10_sharpe_09=_row(perf, "Winners D10 (VW), excess", "2009-2026")["sharpe"],
        mkt_sharpe_09=_row(perf, "Market (Mkt-RF)", "2009-2026")["sharpe"],
        d10_sharpe_full=_row(perf, "Winners D10 (VW), excess", "Full sample")["sharpe"],
        mkt_sharpe_full=_row(perf, "Market (Mkt-RF)", "Full sample")["sharpe"],
        d10ew_sharpe_full=_row(perf, "Winners D10 (EW), excess", "Full sample")["sharpe"],
    )

    # ---- A2: Barroso & Santa-Clara vol scaling of WML
    R.h(3, "A2. Barroso-Santa-Clara volatility-scaled WML")
    dwml = D.dec_vw_d["D10"] - D.dec_vw_d["D1"]
    w = bsc_weights(dwml, BSC_TARGET, BSC_WINDOW)
    scaled = (w * wml).dropna()
    static = wml.reindex(scaled.index)
    bsc_periods = [
        ("1927-05..2011-12 (BSC sample)", "1927-01", "2011-12"),
        ("Full sample (to latest)", None, None),
        ("1965-1989 (JT93 sample)", "1965-01", "1989-12"),
        ("1990-2008", "1990-01", "2008-12"),
        ("2009-2026", "2009-01", None),
        ("2012-2026", "2012-01", None),
    ]
    rows = []
    for label, a, b in bsc_periods:
        s_r, p_r = slice_period(static, a, b), slice_period(scaled, a, b)
        ww = w.reindex(p_r.index)
        ps, pp = perf_row(s_r), perf_row(p_r)
        rows.append(dict(
            period=label, start=ps["start"], end=ps["end"], n=ps["n"],
            static_mean_pct_yr=ps["ann_mean_pct"], static_vol_pct=ps["ann_vol_pct"], static_sharpe=ps["sharpe"],
            static_worst_pct=ps["worst_month_pct"], static_max_dd_pct=ps["max_dd_pct"],
            scaled_mean_pct_yr=pp["ann_mean_pct"], scaled_vol_pct=pp["ann_vol_pct"], scaled_sharpe=pp["sharpe"],
            scaled_worst_pct=pp["worst_month_pct"], scaled_max_dd_pct=pp["max_dd_pct"],
            avg_weight=float(ww.mean()), min_weight=float(ww.min()), max_weight=float(ww.max()),
        ))
    bsc = pd.DataFrame(rows)
    R.md(
        f"Rule (research/01 section 4.1): weight for month t = {BSC_TARGET:.0%} / sigma_hat, sigma_hat = sqrt(252 x mean of the squared daily WML returns over the "
        f"previous {BSC_WINDOW} trading days up to the last day of month t-1) (uncentered, no cap). Daily WML = D10 - D1 from the daily VW decile file "
        "(formed on days -250..-21); the monthly return that is scaled is the monthly-file D10 - D1. Weights start "
        f"{w.dropna().index[0].strftime('%Y-%m')} (first month with {BSC_WINDOW} prior daily observations). Gross of costs; the leverage is on the long-short spread.\n"
    )
    show = ["period", "n", "static_mean_pct_yr", "static_vol_pct", "static_sharpe", "static_worst_pct", "static_max_dd_pct",
            "scaled_mean_pct_yr", "scaled_vol_pct", "scaled_sharpe", "scaled_worst_pct", "scaled_max_dd_pct", "avg_weight", "max_weight"]
    ren = {"period": "Period", "static_mean_pct_yr": "Static mean %", "static_vol_pct": "vol %", "static_sharpe": "Sharpe",
           "static_worst_pct": "worst mo %", "static_max_dd_pct": "max DD %", "scaled_mean_pct_yr": "Scaled mean %",
           "scaled_vol_pct": "vol % ", "scaled_sharpe": "Sharpe ", "scaled_worst_pct": "worst mo % ", "scaled_max_dd_pct": "max DD % ",
           "avg_weight": "avg w", "max_weight": "max w"}
    R.table("momentum_vol_scaling_wml", bsc, show=show, rename=ren,
            fmt={"static_mean_pct_yr": "{:.1f}", "static_vol_pct": "{:.1f}", "static_sharpe": "{:.2f}", "static_worst_pct": "{:.1f}",
                 "static_max_dd_pct": "{:.1f}", "scaled_mean_pct_yr": "{:.1f}", "scaled_vol_pct": "{:.1f}", "scaled_sharpe": "{:.2f}",
                 "scaled_worst_pct": "{:.1f}", "scaled_max_dd_pct": "{:.1f}", "avg_weight": "{:.2f}", "max_weight": "{:.2f}"})
    b0 = bsc.iloc[0]
    for item, ours, theirs, tol in [
        ("BSC 1927-2011 static WML: Sharpe", b0["static_sharpe"], 0.54, 0.02), ("BSC 1927-2011 scaled WML: Sharpe", b0["scaled_sharpe"], 1.00, 0.03),
        ("BSC 1927-2011 static: mean %/yr", b0["static_mean_pct_yr"], 14.9, 0.3), ("BSC 1927-2011 scaled: mean %/yr", b0["scaled_mean_pct_yr"], 16.7, 0.3),
        ("BSC 1927-2011 scaled: vol %/yr", b0["scaled_vol_pct"], 16.8, 0.3), ("BSC 1927-2011 scaled: worst month %", b0["scaled_worst_pct"], -24.2, 0.5),
        ("BSC 1927-2011 scaled: max DD %", b0["scaled_max_dd_pct"], -43.8, 0.5), ("BSC 1927-2011 static: max DD %", b0["static_max_dd_pct"], -95.6, 0.5),
        ("BSC 1927-2011: max weight", b0["max_weight"], 2.09, 0.05),
    ]:
        R.ref(item, ours, theirs, tol)
    b1, b2, b3 = bsc.iloc[1], bsc.iloc[2], bsc.iloc[5]
    R.ref("BSC full sample static: Sharpe", b1["static_sharpe"], 0.49, 0.02)
    R.ref("BSC full sample scaled: Sharpe", b1["scaled_sharpe"], 0.92, 0.03)
    R.ref("BSC full sample: avg weight", b1["avg_weight"], 0.84, 0.03)
    R.ref("BSC 1965-1989 scaled: Sharpe", b2["scaled_sharpe"], 1.32, 0.03)
    R.ref("BSC 2012-2026 static: Sharpe", b3["static_sharpe"], 0.20, 0.03)
    R.ref("BSC 2012-2026 scaled: Sharpe", b3["scaled_sharpe"], 0.37, 0.03)
    R.ref("BSC 2012-2026: avg weight", b3["avg_weight"], 0.50, 0.03)
    K.update(bsc_static_sharpe=b0["static_sharpe"], bsc_scaled_sharpe=b0["scaled_sharpe"], bsc_full_static=b1["static_sharpe"], bsc_full_scaled=b1["scaled_sharpe"],
             bsc_12_static=b3["static_sharpe"], bsc_12_scaled=b3["scaled_sharpe"], bsc_09_static=bsc.iloc[4]["static_sharpe"], bsc_09_scaled=bsc.iloc[4]["scaled_sharpe"],
             bsc_first=w.dropna().index[0].strftime("%Y-%m"), bsc_worst_static=b1["static_worst_pct"], bsc_worst_scaled=b1["scaled_worst_pct"])

    # ---- A3: long-only winners decile with vol control
    R.h(3, "A3. Long-only winners decile with volatility control (cash = T-bill)")
    d10_d = D.dec_vw_d["D10"]
    w20 = bsc_weights(d10_d, LONG_ONLY_TARGET, BSC_WINDOW, cap=1.0)
    wgauge = bsc_weights(dwml, BSC_TARGET, BSC_WINDOW, cap=1.0)
    n_bh, n_own = "Buy & hold D10 (VW)", f"Vol-target {LONG_ONLY_TARGET:.0%} on own vol, cap 1"
    n_gauge, n_mkt = f"Weight = min(1, {BSC_TARGET:.0%} / WML vol), cap 1", "Market buy & hold"
    bases = [
        ("monthly-file D10 (formed monthly, as in A1/A2)", dm["D10"]),
        ("daily-file D10 compounded to months (formed daily; the basis of research/01 section 8)", compound_daily_to_monthly(d10_d)),
    ]
    lo_periods = [("Full (from first weight)", None, None), ("2009-2026", "2009-01", None), ("1965-1989", "1965-01", "1989-12"), ("1990-2008", "1990-01", "2008-12")]
    rows = []
    strategies: dict[str, pd.Series] = {}
    for bi, (blabel, d10) in enumerate(bases):
        idx = w20.dropna().index.intersection(wgauge.dropna().index).intersection(d10.index)
        strat = {
            n_bh: d10.reindex(idx),
            n_own: (w20 * d10 + (1 - w20) * D.rf).reindex(idx),
            n_gauge: (wgauge * d10 + (1 - wgauge) * D.rf).reindex(idx),
            n_mkt: D.mkt.reindex(idx),
        }
        if bi == 0:
            strategies = strat
        expo = {n_bh: None, n_mkt: None, n_own: w20, n_gauge: wgauge}
        for name, r in strat.items():
            for label, a_, b_ in lo_periods:
                rr = slice_period(r, a_, b_)
                ex = rr - D.rf.reindex(rr.index)
                pr = perf_row(ex, rr, None if name == n_mkt else D.mkt_ex, D.ff3)
                rows.append(dict(d10_basis=blabel, strategy=name, period=label, start=pr["start"], end=pr["end"], n=pr["n"], cagr_pct=100 * cagr(rr),
                                 ann_vol_pct=pr["ann_vol_pct"], sharpe=pr["sharpe"], max_dd_pct=pr["max_dd_pct"], worst_month_pct=100 * float(rr.min()),
                                 capm_alpha_pct_yr=pr.get("capm_alpha_pct_yr", np.nan), capm_alpha_t=pr.get("capm_alpha_t", np.nan),
                                 avg_exposure=1.0 if expo[name] is None else float(expo[name].reindex(rr.index).mean())))
    lo = pd.DataFrame(rows)
    R.md(f"Setup as research/01 section 8: monthly decisions from data through the prior month-end; exposure w in D10 and (1-w) in the T-bill (French RF); no costs; "
         f"decile-level (hundreds of stocks), not a 5-10 stock book. Sharpe is on excess returns over RF. Own-vol rule: w = min(1, {LONG_ONLY_TARGET:.0%} / sigma_hat of D10 daily); "
         f"WML-vol rule: w = min(1, {BSC_TARGET:.0%} / sigma_hat of WML daily). Sample starts with the first available weight ({bsc_first(w20)}). "
         "Two versions of the winners decile are shown because French publishes two: the monthly file (portfolio re-formed once a month) and the daily file (re-formed every day on "
         "the day -250..-21 return); research/01 section 8 used the daily file, so that block is the one that reproduces its numbers.\n")
    lo.to_csv(R.outdir / "momentum_vol_scaling_longonly.csv", index=False, float_format="%.6g")
    R.tables["momentum_vol_scaling_longonly"] = lo
    lo_show = ["strategy", "period", "n", "cagr_pct", "ann_vol_pct", "sharpe", "max_dd_pct", "worst_month_pct", "capm_alpha_pct_yr", "capm_alpha_t", "avg_exposure"]
    lo_ren = {"strategy": "Strategy", "period": "Period", "cagr_pct": "CAGR %", "ann_vol_pct": "Vol %", "sharpe": "Sharpe", "max_dd_pct": "Max DD %",
              "worst_month_pct": "Worst mo %", "capm_alpha_pct_yr": "CAPM a %/yr", "capm_alpha_t": "t(a)", "avg_exposure": "Avg exposure"}
    lo_fmt = {"CAGR %": "{:.1f}", "Vol %": "{:.1f}", "Max DD %": "{:.1f}", "Worst mo %": "{:.1f}", "CAPM a %/yr": "{:.1f}", "t(a)": "{:.1f}", "Avg exposure": "{:.2f}"}
    for blabel, _ in bases:
        R.md(f"**Winners decile = {blabel}**\n")
        R.md(md_table(lo[lo["d10_basis"] == blabel][lo_show].rename(columns=lo_ren), lo_fmt) + "\n")
    R.md("*CSV: `momentum_vol_scaling_longonly.csv`*\n")
    dbasis = bases[1][0]
    for strat, period, cg, sh, dd in [
        (n_bh, "Full (from first weight)", 15.5, 0.61, -83.8), (n_bh, "2009-2026", 16.8, 0.77, -34.3),
        (n_own, "Full (from first weight)", 15.4, 0.67, -74.0), (n_own, "2009-2026", 14.4, 0.82, -22.6),
        (n_gauge, "Full (from first weight)", 14.0, 0.70, -49.7), (n_gauge, "2009-2026", 9.9, 0.83, -17.1),
        (n_mkt, "Full (from first weight)", 10.2, 0.45, -83.9), (n_mkt, "2009-2026", 15.1, 0.91, -24.9),
    ]:
        r = lo[(lo["d10_basis"] == dbasis) & (lo["strategy"] == strat) & (lo["period"] == period)].iloc[0]
        note = "daily-file D10 basis; notes do not specify cash accounting to the digit"
        R.ref(f"Long-only {strat} {period}: CAGR %", r["cagr_pct"], cg, 0.5, note=note)
        R.ref(f"Long-only {strat} {period}: Sharpe", r["sharpe"], sh, 0.04, note=note)
        R.ref(f"Long-only {strat} {period}: max DD %", r["max_dd_pct"], dd, 1.0, note=note)
    full = "Full (from first weight)"
    g = lambda basis, st, col: lo[(lo["d10_basis"] == basis) & (lo["strategy"] == st) & (lo["period"] == full)].iloc[0][col]  # noqa: E731
    K.update(lo_bh_sharpe=g(bases[0][0], n_bh, "sharpe"), lo_vt_sharpe=g(bases[0][0], n_own, "sharpe"), lo_bh_dd=g(bases[0][0], n_bh, "max_dd_pct"), lo_vt_dd=g(bases[0][0], n_own, "max_dd_pct"),
             lod_bh_sharpe=g(dbasis, n_bh, "sharpe"), lod_vt_sharpe=g(dbasis, n_own, "sharpe"), lod_bh_dd=g(dbasis, n_bh, "max_dd_pct"), lod_vt_dd=g(dbasis, n_own, "max_dd_pct"))

    # ---- A4: Daniel-Moskowitz bear state
    R.h(3, "A4. Daniel-Moskowitz bear state and the worst WML months")
    p24 = prior_market_return(D.mkt, 24)
    bear = (p24 < 0)
    in_dm = (bear.index >= "1927-01-01") & (bear.index <= "2013-03-31")
    n_dm, n_bear_dm = int(in_dm.sum()), int(bear[in_dm].sum())
    since27 = bear.loc["1927-01":]
    n_bear_all = int(since27.sum())
    rows = []
    sers = {"WML (D10-D1, VW)": wml, "Winners D10 excess (VW)": d10x, "Losers D1 excess (VW)": dm["D1"] - D.rf, "Winners D10 minus market": dm["D10"] - D.mkt, "Market excess (Mkt-RF)": mkt_ex}
    for name, s in sers.items():
        s = s.loc["1927-01":]
        b = bear.reindex(s.index)
        for state, mask in [("Bear (prior 24m market < 0)", b), ("Non-bear", ~b)]:
            x = s[mask]
            rows.append(dict(series=name, state=state, n=len(x), mean_pct_m=100 * x.mean(), sd_pct_m=100 * x.std(ddof=1), t_mean=x.mean() / (x.std(ddof=1) / np.sqrt(len(x))),
                             worst_pct=100 * x.min(), ann_sharpe=x.mean() / x.std(ddof=1) * np.sqrt(12)))
        tt = sps.ttest_ind(s[b], s[~b], equal_var=False)
        rows[-1]["welch_t_bear_vs_non"] = rows[-2]["welch_t_bear_vs_non"] = float(tt.statistic)
    bear_df = pd.DataFrame(rows)
    R.md(
        f"Bear state at month t = cumulative CRSP market return over the previous 24 months (t-24..t-1) is negative. Count: **{n_bear_dm} bear months out of {n_dm}** in "
        f"1927-01..2013-03 (Daniel-Moskowitz report 183 of 1,035) and {n_bear_all} of {len(since27)} through {since27.index[-1].strftime('%Y-%m')}. Samples start 1927-01.\n"
    )
    R.table("momentum_dm_bear_state", bear_df,
            show=["series", "state", "n", "mean_pct_m", "sd_pct_m", "t_mean", "worst_pct", "welch_t_bear_vs_non"],
            rename={"series": "Series", "state": "State", "mean_pct_m": "Mean %/mo", "sd_pct_m": "SD %/mo", "t_mean": "t(mean)", "worst_pct": "Worst mo %", "welch_t_bear_vs_non": "Welch t (bear vs non)"},
            fmt={"mean_pct_m": "{:.2f}", "sd_pct_m": "{:.1f}", "t_mean": "{:.1f}", "worst_pct": "{:.1f}", "welch_t_bear_vs_non": "{:.1f}"})
    bw = bear_df[(bear_df["series"] == "WML (D10-D1, VW)")]
    R.ref("DM bear months 1927-01..2013-03", n_bear_dm, 183, 0, "months")
    R.ref("DM months in sample 1927-01..2013-03", n_dm, 1035, 0, "months")
    R.ref("Bear months 1927-01..latest", n_bear_all, 191, 0, "months")
    R.ref("WML mean in bear states %/mo", bw.iloc[0]["mean_pct_m"], -1.11, 0.03)
    R.ref("WML sd in bear states %/mo", bw.iloc[0]["sd_pct_m"], 14.1, 0.2)
    R.ref("WML mean in non-bear states %/mo", bw.iloc[1]["mean_pct_m"], 1.56, 0.03)
    R.ref("WML sd in non-bear states %/mo", bw.iloc[1]["sd_pct_m"], 6.1, 0.2)
    wd = bear_df[bear_df["series"] == "Winners D10 excess (VW)"]
    R.ref("Winners D10 excess mean bear %/mo", wd.iloc[0]["mean_pct_m"], 0.78, 0.03)
    R.ref("Winners D10 excess mean non-bear %/mo", wd.iloc[1]["mean_pct_m"], 1.34, 0.03)
    wm = bear_df[bear_df["series"] == "Winners D10 minus market"]
    R.ref("Winners minus market bear %/mo", wm.iloc[0]["mean_pct_m"], 0.04, 0.03)
    R.ref("Winners minus market non-bear %/mo", wm.iloc[1]["mean_pct_m"], 0.66, 0.03)

    worst = wml.sort_values().head(15)
    wdf = pd.DataFrame({
        "month": [d.strftime("%Y-%m") for d in worst.index], "wml_pct": 100 * worst.to_numpy(),
        "losers_D1_pct": 100 * dm["D1"].reindex(worst.index).to_numpy(), "winners_D10_pct": 100 * dm["D10"].reindex(worst.index).to_numpy(),
        "market_pct": 100 * D.mkt.reindex(worst.index).to_numpy(), "prior24m_market_pct": 100 * p24.reindex(worst.index).to_numpy(),
    })
    wdf["bear_state"] = np.where(wdf["prior24m_market_pct"] < 0, "yes", "no")
    n_bear_worst = int((wdf["prior24m_market_pct"] < 0).sum())
    n_mkt_up = int((wdf["market_pct"] > 0).sum())
    n_d10_down = int((wdf["winners_D10_pct"] < 0).sum())
    R.md(f"\n**The 15 worst WML months** ({n_bear_worst} of 15 are in a bear state, {n_mkt_up} of 15 had a rising market, the winners decile fell in {n_d10_down} of 15; "
         "Daniel-Moskowitz: 14 of 15 in a bear state, all in rising markets):\n")
    R.table("momentum_worst15_wml", wdf,
            rename={"month": "Month", "wml_pct": "WML %", "losers_D1_pct": "D1 %", "winners_D10_pct": "D10 %", "market_pct": "Market %", "prior24m_market_pct": "Prior-24m mkt %", "bear_state": "Bear"},
            fmt={"wml_pct": "{:.1f}", "losers_D1_pct": "{:.1f}", "winners_D10_pct": "{:.1f}", "market_pct": "{:.1f}", "prior24m_market_pct": "{:.1f}"})
    # Like-for-like with Daniel-Moskowitz: their sample ends 2013-03 (our list also contains 2020-21 and 2026 months)
    dm_worst = wml.loc["1927-01":"2013-03"].sort_values().head(15)
    n_bear_dm15 = int((p24.reindex(dm_worst.index) < 0).sum())
    dm_paper_top10 = ["1932-08", "1932-07", "2001-01", "2009-04", "1939-09", "1933-04", "2009-03", "2002-11", "1938-06", "2009-08"]
    ours15 = {d.strftime("%Y-%m") for d in dm_worst.index}
    overlap = sorted(set(dm_paper_top10) & ours15)
    exc_txt = ", ".join(d.strftime("%Y-%m") for d in dm_worst.index if not p24.loc[d] < 0) or "none"
    R.md(f"Within Daniel-Moskowitz's own window (1927-01..2013-03) the 15 worst WML months are {n_bear_dm15} of 15 in a bear state (they report 14 of 15, the exception being 2001-01; ours: {exc_txt}). "
         f"{len(overlap)} of the 10 worst months in their Table 2 appear among our 15 worst in that window ({', '.join(overlap)}); magnitudes differ (e.g. 1932-08: ours "
         f"{100*wml.loc['1932-08-31']:.1f}% vs their -74.4%; 2002-11: ours {100*wml.loc['2002-11-30']:.1f}% vs -37.0%) because they build their own deciles from CRSP while French's use NYSE "
         "breakpoints and a newer CRSP vintage, so these are listed for orientation and are not counted as reference checks.\n")
    R.ref("15 worst WML months (1927-01..2013-03) in bear state", n_bear_dm15, 14, 0, "months")
    K.update(n_bear_dm15=n_bear_dm15, n_bear_dm=n_bear_dm, n_dm=n_dm, n_bear_worst=n_bear_worst, n_d10_down=n_d10_down, n_mkt_up=n_mkt_up,
             wml_bear=bw.iloc[0]["mean_pct_m"], wml_nonbear=bw.iloc[1]["mean_pct_m"], d10_bear=wd.iloc[0]["mean_pct_m"], d10_nonbear=wd.iloc[1]["mean_pct_m"],
             d10mkt_bear=wm.iloc[0]["mean_pct_m"], d10mkt_nonbear=wm.iloc[1]["mean_pct_m"])

    # ---- A5: current regime
    R.h(3, "A5. Current momentum volatility regime")
    sig_wml, sig_d10 = trailing_vol_ann(dwml), trailing_vol_ann(d10_d)
    mom_d = F.mom("D")["Mom"]
    sig_mom = trailing_vol_ann(mom_d)
    last_d = dwml.index[-1]
    cur_wml, cur_d10, cur_mom = float(sig_wml.iloc[-1]), float(sig_d10.iloc[-1]), float(sig_mom.iloc[-1])
    lr_wml, lr_d10, lr_mom = float(np.sqrt(TRADING_DAYS * (dwml**2).mean())), float(np.sqrt(TRADING_DAYS * (d10_d**2).mean())), float(np.sqrt(TRADING_DAYS * (mom_d**2).mean()))
    pct_wml = float((sig_wml.dropna() <= cur_wml).mean())
    pct_d10 = float((sig_d10.dropna() <= cur_d10).mean())
    p24_next = float(np.expm1(np.log1p(D.mkt).iloc[-24:].sum()))
    ff3_d = F.ff3("D")
    p504 = float((1.0 + (ff3_d["Mkt-RF"] + ff3_d["RF"]).iloc[-504:]).prod() - 1.0)
    lrm_wml, lrm_d10 = float(wml.std(ddof=1) * np.sqrt(12)), float(d10x.std(ddof=1) * np.sqrt(12))
    cur = pd.DataFrame([
        dict(metric="Last daily observation", value=str(last_d.date())),
        dict(metric=f"WML ({BSC_WINDOW}d) annualized vol", value=f"{100*cur_wml:.1f}%"),
        dict(metric="WML long-run vol: monthly-file spread (1927-2026) / daily-file, all days", value=f"{100*lrm_wml:.1f}% / {100*lr_wml:.1f}%"),
        dict(metric="WML vol percentile vs own daily history", value=f"{100*pct_wml:.0f}th"),
        dict(metric=f"BSC weight on WML ({BSC_TARGET:.0%} target, uncapped)", value=f"{BSC_TARGET / cur_wml:.2f}"),
        dict(metric=f"Winners D10 ({BSC_WINDOW}d) annualized vol", value=f"{100*cur_d10:.1f}%"),
        dict(metric="Winners D10 long-run vol: monthly-file / daily-file, all days", value=f"{100*lrm_d10:.1f}% / {100*lr_d10:.1f}%"),
        dict(metric="Winners D10 vol percentile vs own daily history", value=f"{100*pct_d10:.0f}th"),
        dict(metric=f"Long-only weight, {LONG_ONLY_TARGET:.0%} own-vol target, cap 1", value=f"{min(1.0, LONG_ONLY_TARGET / cur_d10):.2f}"),
        dict(metric=f"Long-only weight, min(1, {BSC_TARGET:.0%}/WML vol)", value=f"{min(1.0, BSC_TARGET / cur_wml):.2f}"),
        dict(metric=f"French Mom 2x3 ({BSC_WINDOW}d) annualized vol (daily-file long-run {100*lr_mom:.1f}%)", value=f"{100*cur_mom:.1f}%"),
        dict(metric="Market return, last 24 calendar months (Daniel-Moskowitz definition)", value=f"{100*p24_next:.1f}%"),
        dict(metric="Market return, last 504 trading days (the window research/01 section 13 used)", value=f"{100*p504:.1f}%"),
        dict(metric="DM bear state for the NEXT month", value="yes" if p24_next < 0 else "no"),
        dict(metric="WML last 3 monthly returns (oldest..latest)", value=", ".join(f"{100*x:.1f}%" for x in wml.iloc[-3:])),
        dict(metric="Winners D10 last 3 monthly returns", value=", ".join(f"{100*x:.1f}%" for x in dm["D10"].iloc[-3:])),
    ])
    R.md(f"Computed from the daily decile files through {last_d.date()} (French data lag the calendar by about a month; recompute from daily prices before the live decision).\n")
    R.table("momentum_current_regime", cur, rename={"metric": "Metric", "value": "Value"})
    R.ref("Current WML 126d vol %", 100 * cur_wml, 53.0, 0.5)
    R.ref("WML long-run vol % (monthly-file spread)", 100 * lrm_wml, 27.6, 0.3)
    R.ref("Current BSC weight on WML", BSC_TARGET / cur_wml, 0.23, 0.01)
    R.ref("Current winners D10 126d vol %", 100 * cur_d10, 41.6, 0.5)
    R.ref("Winners D10 20% target weight now", min(1.0, LONG_ONLY_TARGET / cur_d10), 0.48, 0.02)
    R.ref("French Mom 2x3 126d vol %", 100 * cur_mom, 24.0, 1.5)
    R.ref("Market return over last 504 trading days %", 100 * p504, 41.7, 0.5, note="research/01 section 13 calls this the 24-month return; the calendar-24-month figure (DM definition) is lower")
    K.update(lrm_wml=lrm_wml, cur_wml=cur_wml, cur_d10=cur_d10, cur_w=BSC_TARGET / cur_wml, last_daily=str(last_d.date()), lr_wml=lr_wml, lr_d10=lr_d10, cur_w_lo=min(1.0, LONG_ONLY_TARGET / cur_d10),
             pct_wml=pct_wml, p24_now=p24_next)

    # ---- charts
    fig, axes = plt.subplots(3, 1, figsize=(9, 9), sharex=True, gridspec_kw={"height_ratios": [2.2, 1.3, 1.1]})
    ax = axes[0]
    ax.plot((1 + static).cumprod(), color=C_ORANGE, label="WML static")
    ax.plot((1 + scaled).cumprod(), color=C_BLUE, label=f"WML vol-scaled ({BSC_TARGET:.0%} target)")
    _wealth_axis(ax)
    ax.set_title("Barroso-Santa-Clara: static vs volatility-scaled WML (D10-D1, VW), growth of $1")
    ax.legend(loc="upper left")
    ax = axes[1]
    ax.plot((1 + static).cumprod() / (1 + static).cumprod().cummax() - 1, color=C_ORANGE, label="static")
    ax.plot((1 + scaled).cumprod() / (1 + scaled).cumprod().cummax() - 1, color=C_BLUE, label="vol-scaled")
    ax.set_title("Drawdown")
    ax.yaxis.set_major_formatter(mticker.PercentFormatter(1.0, decimals=0))
    ax = axes[2]
    ax.plot(w.reindex(scaled.index), color=C_BLUE, lw=1.0)
    ax.axhline(1.0, color=C_INK2, lw=0.8, ls=":")
    ax.set_title("Weight applied to WML (12% / trailing 126-day vol)")
    fig.tight_layout()
    R.image(_save(fig, R.outdir, "momentum_wml_static_vs_volscaled.png"), "WML static vs vol-scaled")

    fig, ax = plt.subplots(figsize=(9, 4.5))
    cols = {"Buy & hold D10 (VW)": C_ORANGE, f"Vol-target {LONG_ONLY_TARGET:.0%} on own vol, cap 1": C_BLUE,
            f"Weight = min(1, {BSC_TARGET:.0%} / WML vol), cap 1": C_AQUA, "Market buy & hold": C_INK2}
    for name, r in strategies.items():
        ax.plot((1 + r).cumprod(), color=cols[name], label=name, lw=1.4)
    _wealth_axis(ax)
    ax.set_title("Long-only winners decile with volatility control (total return, no costs), growth of $1")
    ax.legend(loc="upper left")
    fig.tight_layout()
    R.image(_save(fig, R.outdir, "momentum_longonly_volcontrol.png"), "Long-only winners decile with vol control")


def bsc_first(w: pd.Series) -> str:
    return w.dropna().index[0].strftime("%Y-%m")


# =====================================================================================
# b. Profitability / quality
# =====================================================================================
def section_quality(R: Report, D: Data, K: dict) -> None:
    R.h(2, "B. Profitability and quality (Novy-Marx 2013; Fama-French 2015; AQR QMJ)")
    rmw = D.ff5["RMW"]
    wml = D.dec_vw["D10"] - D.dec_vw["D1"]
    ff4 = pd.concat([D.ff3[["Mkt-RF", "SMB", "HML"]], D.mom.rename("Mom")], axis=1, sort=True).dropna()
    periods_rmw = [
        ("Full sample (1963-07 on)", None, None),
        ("Original sample 1963-07..2010-12 (Novy-Marx)", "1963-07", "2010-12"),
        ("Pre-2013 (to 2012-12)", None, "2012-12"),
        ("Post-2013 (2013-01 on)", "2013-01", None),
        ("Post-FF5 paper (2015-04 on)", "2015-04", None),
        ("2009-2026", "2009-01", None),
    ]
    periods_q = [
        ("Full sample (1957-07 on)", None, None),
        ("Pre-2013 (to 2012-12)", None, "2012-12"),
        ("Post-2013 (2013-01 on)", "2013-01", None),
        ("2009-2026", "2009-01", None),
    ]
    rows = []

    def add(name: str, s: pd.Series, periods) -> None:
        for label, a, b in periods:
            rr = slice_period(s, a, b)
            pr = perf_row(rr, None, D.mkt_ex, D.ff3)
            c4 = regress(rr, ff4)
            pr.update(series=name, period=label, ff4_alpha_pct_yr=1200 * c4["alpha"] if c4 else np.nan, ff4_alpha_t=c4["alpha_t"] if c4 else np.nan,
                      ff4_mom_loading=c4["loadings"]["Mom"] if c4 else np.nan)
            rows.append(pr)

    add("RMW (FF5 2x3)", rmw, periods_rmw)
    if D.qmj is not None:
        add("QMJ (AQR, USA)", D.qmj, periods_q)
    qual = pd.DataFrame(rows)
    first = ["series", "period", "start", "end", "n"]
    qual = qual[first + [c for c in qual.columns if c not in first]]
    R.md(
        "RMW = robust minus weak operating profitability (French 2x3, value-weighted, formed each June). QMJ = AQR's quality-minus-junk (USA column of "
        "'Quality Minus Junk: Factors, Monthly'; value-weighted long-short, self-financing; AQR notes its web dataset also uses a payout component and is rebuilt "
        "on each update, so it differs slightly from the paper). Both are zero-cost spreads: mean/Sharpe are on the spread itself. a(CAPM) regresses on Mkt-RF; "
        "a(4F) on Mkt-RF, SMB, HML and Mom (French FF3 file and Mom 2x3), Newey-West t.\n"
    )
    if D.qmj is None:
        R.md(f"> **AQR QMJ could not be downloaded** ({D.qmj_error}); QMJ rows are omitted.\n")
    show = ["series", "period", "n", "mean_pct_m", "t_mean", "ann_vol_pct", "sharpe", "max_dd_pct", "capm_alpha_pct_yr", "capm_alpha_t", "ff4_alpha_pct_yr", "ff4_alpha_t", "ff4_mom_loading"]
    R.table("quality_performance", qual, show=show,
            rename={"series": "Series", "period": "Period", "mean_pct_m": "Mean %/mo", "t_mean": "t(mean)", "ann_vol_pct": "Vol %/yr", "sharpe": "Sharpe", "max_dd_pct": "Max DD %",
                    "capm_alpha_pct_yr": "a(CAPM) %/yr", "capm_alpha_t": "t", "ff4_alpha_pct_yr": "a(4F) %/yr", "ff4_alpha_t": "t ", "ff4_mom_loading": "Mom load"},
            fmt={"mean_pct_m": "{:.2f}", "t_mean": "{:.1f}", "ann_vol_pct": "{:.1f}", "sharpe": "{:.2f}", "max_dd_pct": "{:.1f}", "capm_alpha_pct_yr": "{:.1f}",
                 "capm_alpha_t": "{:.1f}", "ff4_alpha_pct_yr": "{:.1f}", "ff4_alpha_t": "{:.1f}", "ff4_mom_loading": "{:.2f}"})
    # reference: FF2015 Table 4 (1963-07..2013-12): RMW 0.25 %/mo, t 2.92 ; QMJ Table 4 (1957-07..2016-12) 0.29 %/mo, t 3.62
    r_ff = perf_row(slice_period(rmw, "1963-07", "2013-12"))
    R.ref("RMW 1963-07..2013-12 mean %/mo (FF2015 Table 4)", r_ff["mean_pct_m"], 0.25, 0.02)
    R.ref("RMW 1963-07..2013-12 t-stat (FF2015 Table 4)", r_ff["t_mean"], 2.92, 0.15)
    R.ref("HML 1963-07..2013-12 mean %/mo (FF2015 Table 4)", perf_row(slice_period(D.ff5["HML"], "1963-07", "2013-12"))["mean_pct_m"], 0.37, 0.02)
    R.ref("HML 1963-07..2013-12 t-stat (FF2015 Table 4)", perf_row(slice_period(D.ff5["HML"], "1963-07", "2013-12"))["t_mean"], 3.20, 0.25, note="2026 CRSP vintage vs the 2015 paper")
    R.ref("Mkt-RF 1963-07..2013-12 mean %/mo (FF2015 Table 4)", perf_row(slice_period(D.ff5["Mkt-RF"], "1963-07", "2013-12"))["mean_pct_m"], 0.50, 0.02)
    if D.qmj is not None:
        r_q = perf_row(slice_period(D.qmj, "1957-07", "2016-12"))
        R.ref("QMJ USA 1957-07..2016-12 mean %/mo (AFP Table 4)", r_q["mean_pct_m"], 0.29, 0.05, note="AQR web dataset is rebuilt on each update and adds a payout component, so it is not the paper's series")
        R.ref("QMJ USA 1957-07..2016-12 t-stat (AFP Table 4)", r_q["t_mean"], 3.62, 0.5, note="same: dataset differs from the paper's series")
    rm_full, rm_pre, rm_post = qual.iloc[0], qual.iloc[2], qual.iloc[3]
    K.update(rmw_full_mean=rm_full["ann_mean_pct"], rmw_full_sharpe=rm_full["sharpe"], rmw_full_t=rm_full["t_mean"], rmw_pre_sharpe=rm_pre["sharpe"], rmw_post_sharpe=rm_post["sharpe"],
             rmw_pre_mean=rm_pre["ann_mean_pct"], rmw_post_mean=rm_post["ann_mean_pct"], rmw_post_t=rm_post["t_mean"])
    if D.qmj is not None:
        q = qual[qual["series"].str.startswith("QMJ")]
        K.update(qmj_full_sharpe=q.iloc[0]["sharpe"], qmj_full_mean=q.iloc[0]["ann_mean_pct"], qmj_full_t=q.iloc[0]["t_mean"], qmj_pre_sharpe=q.iloc[1]["sharpe"], qmj_post_sharpe=q.iloc[2]["sharpe"],
                 qmj_pre_mean=q.iloc[1]["ann_mean_pct"], qmj_post_mean=q.iloc[2]["ann_mean_pct"], qmj_post_t=q.iloc[2]["t_mean"], qmj_09_sharpe=q.iloc[3]["sharpe"])

    # ---- quality vs momentum
    R.h(3, "B2. Does quality hedge momentum?")
    cols = {"WML (D10-D1, VW)": wml, "Mom 2x3": D.mom, "RMW": rmw, "HML": D.ff3["HML"], "Mkt-RF": D.mkt_ex}
    if D.qmj is not None:
        cols["QMJ"] = D.qmj
    panel = pd.concat(cols, axis=1, sort=True).dropna()
    corr_rows = []
    for label, a, b in [("Full common sample", None, None), ("2009-2026", "2009-01", None)]:
        c = slice_period(panel, a, b).corr()
        for i in c.index:
            for j in c.columns:
                corr_rows.append(dict(period=label, a=i, b=j, corr=c.loc[i, j], n=len(slice_period(panel, a, b))))
    corr = pd.DataFrame(corr_rows)
    full_c = slice_period(panel, None, None).corr()
    rec_c = slice_period(panel, "2009-01", None).corr()
    R.md(f"Common sample {panel.index[0].strftime('%Y-%m')}..{panel.index[-1].strftime('%Y-%m')} (n={len(panel)}). Correlations of monthly returns:\n")
    cm = full_c.copy()
    cm.insert(0, "", cm.index)
    R.md(md_table(cm, default="{:.2f}") + "\n")
    cm2 = rec_c.copy()
    cm2.insert(0, "2009-2026", cm2.index)
    R.md("\n" + md_table(cm2, default="{:.2f}") + "\n")
    R.tables["quality_momentum_correlation"] = corr
    corr.to_csv(R.outdir / "quality_momentum_correlation.csv", index=False, float_format="%.6g")
    R.md("*CSV: `quality_momentum_correlation.csv`*\n")

    # tail behaviour
    panel2 = panel.copy()
    q_cut = panel2["Mom 2x3"].quantile(0.05)
    worst_mom = panel2[panel2["Mom 2x3"] <= q_cut]
    wml_cut = panel2["WML (D10-D1, VW)"].sort_values().head(10).index
    tails = []
    for label, sub in [("All months", panel2), (f"Worst 5% Mom 2x3 months (n={len(worst_mom)})", worst_mom), ("10 worst WML (VW) months in the sample", panel2.loc[wml_cut])]:
        row = {"months": label}
        for c in panel2.columns:
            row[c + " mean %/mo"] = 100 * sub[c].mean()
        tails.append(row)
    tail_df = pd.DataFrame(tails)
    R.md("\nAverage monthly returns (%) of each factor in momentum's worst months (a hedge would show up as positive RMW/QMJ numbers there):\n")
    R.table("quality_momentum_tails", tail_df, fmt={c: "{:.2f}" for c in tail_df.columns if c != "months"})

    # combos
    combos = {"Mom 2x3": panel2["Mom 2x3"], "WML (D10-D1, VW)": panel2["WML (D10-D1, VW)"], "RMW": panel2["RMW"],
              "50/50 Mom 2x3 + RMW": 0.5 * panel2["Mom 2x3"] + 0.5 * panel2["RMW"]}
    if "QMJ" in panel2:
        combos["QMJ"] = panel2["QMJ"]
        combos["50/50 Mom 2x3 + QMJ"] = 0.5 * panel2["Mom 2x3"] + 0.5 * panel2["QMJ"]
        combos["50/50 WML + QMJ"] = 0.5 * panel2["WML (D10-D1, VW)"] + 0.5 * panel2["QMJ"]
    crow = []
    for label, a, b in [("Full common sample", None, None), ("2009-2026", "2009-01", None)]:
        for name, s in combos.items():
            pr = perf_row(slice_period(s, a, b))
            crow.append(dict(sample=label, series=name, n=pr["n"], ann_mean_pct=pr["ann_mean_pct"], ann_vol_pct=pr["ann_vol_pct"], sharpe=pr["sharpe"], max_dd_pct=pr["max_dd_pct"], worst_month_pct=pr["worst_month_pct"]))
    combo_df = pd.DataFrame(crow)
    R.md("\nSimple 50/50 blends of zero-cost factor returns (no leverage adjustment, no costs):\n")
    R.table("quality_momentum_combos", combo_df, rename={"sample": "Sample", "series": "Series", "ann_mean_pct": "Mean %/yr", "ann_vol_pct": "Vol %/yr", "sharpe": "Sharpe", "max_dd_pct": "Max DD %", "worst_month_pct": "Worst mo %"},
            fmt={"ann_mean_pct": "{:.1f}", "ann_vol_pct": "{:.1f}", "sharpe": "{:.2f}", "max_dd_pct": "{:.1f}", "worst_month_pct": "{:.1f}"})
    K.update(corr_mom_rmw=full_c.loc["Mom 2x3", "RMW"], corr_wml_rmw=full_c.loc["WML (D10-D1, VW)", "RMW"], corr_mom_qmj=full_c.loc["Mom 2x3", "QMJ"] if "QMJ" in full_c else np.nan,
             corr_wml_qmj=full_c.loc["WML (D10-D1, VW)", "QMJ"] if "QMJ" in full_c else np.nan,
             tail_rmw=tail_df.iloc[1]["RMW mean %/mo"], tail_qmj=tail_df.iloc[1]["QMJ mean %/mo"] if "QMJ mean %/mo" in tail_df else np.nan,
             tail_rmw_wml=tail_df.iloc[2]["RMW mean %/mo"], tail_qmj_wml=tail_df.iloc[2]["QMJ mean %/mo"] if "QMJ mean %/mo" in tail_df else np.nan,
             panel_start=panel.index[0].strftime("%Y-%m"), panel_end=panel.index[-1].strftime("%Y-%m"))
    cf = combo_df[combo_df["sample"] == "Full common sample"].set_index("series")["sharpe"]
    K.update(sh_mom=cf["Mom 2x3"], sh_rmw=cf["RMW"], sh_mom_rmw=cf["50/50 Mom 2x3 + RMW"], sh_qmj=cf.get("QMJ", np.nan), sh_mom_qmj=cf.get("50/50 Mom 2x3 + QMJ", np.nan))


# =====================================================================================
# c. Good and cheap
# =====================================================================================
GC_PERIODS: list[tuple[str, str | None, str | None]] = [
    ("Full sample (1963-07 on)", None, None),
    ("1988-2004 (Greenblatt sample)", "1988-01", "2004-12"),
    ("Pre-publication (to 2005-10)", None, "2005-10"),
    ("Post-publication (2005-11 on)", "2005-11", None),
    ("2010-2026", "2010-01", None),
]


def _gc_series(bm: pd.DataFrame) -> dict[str, pd.Series]:
    corner = bm["BM5_OP5"]
    corner4 = bm[["BM4_OP4", "BM4_OP5", "BM5_OP4", "BM5_OP5"]].mean(axis=1)
    ew25 = bm.mean(axis=1)
    return {"BM5-OP5 corner": corner, "Top-2 x top-2 corner (avg of 4)": corner4, "Equal-weight avg of all 25": ew25}


def section_good_and_cheap(R: Report, D: Data, K: dict) -> None:
    R.h(2, "C. \"Good and cheap\": Magic Formula proxy from B/M x operating profitability and E/P sorts")
    R.md(
        "The Magic Formula buys stocks that are both cheap (high EBIT/EV, an earnings yield) and profitable (high ROC). Ken French's `25_Portfolios_BEME_OP_5x5` sorts "
        "all stocks on book-to-market (BM1..BM5, 5 = cheapest) and operating profitability (OP1..OP5, 5 = most profitable), so BM5_OP5 is the closest long-history "
        "analogue of 'cheap AND good'. The 'top-2 x top-2 corner' is the equal-weight average of BM4/BM5 x OP4/OP5 (four portfolios, the cheapest-and-best 16% of the "
        "grid). The 25-portfolio equal-weight average is a crude 'universe' benchmark; the CRSP value-weighted market is the other. All series are TOTAL returns of "
        "re-formed-each-June portfolios, no costs, no short positions. B/M and OP are not EBIT/EV and ROC: this is a style proxy, not a replication of Greenblatt.\n"
    )
    all_rows = []
    active_rows = []
    for w, bm in [("vw", D.bmop_vw), ("ew", D.bmop_ew)]:
        base = _gc_series(bm)
        base["Market (CRSP VW)"] = D.mkt.reindex(bm.index)
        for label, a, b in GC_PERIODS:
            for name, s in base.items():
                r = slice_period(s, a, b)
                ex = r - D.rf.reindex(r.index)
                is_mkt = name.startswith("Market")
                pr = perf_row(ex, r, None if is_mkt else D.mkt_ex, None if is_mkt else D.ff3)
                pr.update(weighting=w.upper(), series=name, period=label)
                all_rows.append(pr)
            for name in ["BM5-OP5 corner", "Top-2 x top-2 corner (avg of 4)"]:
                for bname in ["Market (CRSP VW)", "Equal-weight avg of all 25"]:
                    d = slice_period(base[name] - base[bname], a, b).dropna()
                    sd = d.std(ddof=1)
                    _, t_nw = mean_hac(d)
                    active_rows.append(dict(
                        weighting=w.upper(), series=f"{name} minus {bname}", period=label, n=len(d), mean_pct_m=100 * d.mean(), t_nw=t_nw,
                        ann_mean_pct=1200 * d.mean(), tracking_error_pct=100 * sd * np.sqrt(12), info_ratio=d.mean() / sd * np.sqrt(12),
                        hit_rate=float((d > 0).mean())))
    gc = pd.DataFrame(all_rows)
    first = ["weighting", "series", "period", "start", "end", "n"]
    gc = gc[first + [c for c in gc.columns if c not in first]]
    act = pd.DataFrame(active_rows)
    show = ["series", "period", "n", "mean_pct_m", "t_mean", "ann_vol_pct", "sharpe", "max_dd_pct", "capm_alpha_pct_yr", "capm_alpha_t", "ff3_alpha_pct_yr", "ff3_alpha_t"]
    ren = {"series": "Series", "period": "Period", "mean_pct_m": "Excess mean %/mo", "t_mean": "t", "ann_vol_pct": "Vol %/yr", "sharpe": "Sharpe", "max_dd_pct": "Max DD %",
           "capm_alpha_pct_yr": "a(CAPM) %/yr", "capm_alpha_t": "t ", "ff3_alpha_pct_yr": "a(FF3) %/yr", "ff3_alpha_t": "t  "}
    fm = {"mean_pct_m": "{:.2f}", "t_mean": "{:.1f}", "ann_vol_pct": "{:.1f}", "sharpe": "{:.2f}", "max_dd_pct": "{:.1f}", "capm_alpha_pct_yr": "{:.1f}", "capm_alpha_t": "{:.1f}",
          "ff3_alpha_pct_yr": "{:.1f}", "ff3_alpha_t": "{:.1f}"}
    R.md("Excess returns over RF; Max DD on total return; alphas regress the excess return on Mkt-RF (CAPM) and Mkt-RF/SMB/HML (FF3) with Newey-West t.\n")
    for w in ("VW", "EW"):
        sub = gc[gc["weighting"] == w]
        self_tab = sub[show].rename(columns=ren)
        R.md(f"**{'Value-weighted' if w == 'VW' else 'Equal-weighted'} portfolios**\n")
        R.md(md_table(self_tab, {ren.get(k, k): v for k, v in fm.items()}) + "\n")
    R.tables["good_and_cheap_performance"] = gc
    gc.to_csv(R.outdir / "good_and_cheap_performance.csv", index=False, float_format="%.6g")
    R.md("*CSV: `good_and_cheap_performance.csv`*\n")

    R.md("\n**Active return of the corners versus the market and versus the 25-portfolio average** (NW t of the mean difference):\n")
    R.table("good_and_cheap_active", act, show=["weighting", "series", "period", "n", "mean_pct_m", "t_nw", "ann_mean_pct", "tracking_error_pct", "info_ratio"],
            rename={"weighting": "Wt", "series": "Active series", "period": "Period", "mean_pct_m": "Mean %/mo", "t_nw": "t(NW)", "ann_mean_pct": "Mean %/yr", "tracking_error_pct": "TE %/yr", "info_ratio": "IR"},
            fmt={"mean_pct_m": "{:.2f}", "t_nw": "{:.1f}", "ann_mean_pct": "{:.1f}", "tracking_error_pct": "{:.1f}", "info_ratio": "{:.2f}"})

    def gget(w, s, p, col):
        return gc[(gc["weighting"] == w) & (gc["series"] == s) & (gc["period"] == p)].iloc[0][col]

    def aget(w, s, p, col):
        return act[(act["weighting"] == w) & (act["series"] == s) & (act["period"] == p)].iloc[0][col]

    K.update(
        c5_full_sharpe=gget("VW", "BM5-OP5 corner", GC_PERIODS[0][0], "sharpe"), mkt_gc_full_sharpe=gget("VW", "Market (CRSP VW)", GC_PERIODS[0][0], "sharpe"),
        c5_pre_alpha=gget("VW", "BM5-OP5 corner", GC_PERIODS[2][0], "capm_alpha_pct_yr"), c5_pre_alpha_t=gget("VW", "BM5-OP5 corner", GC_PERIODS[2][0], "capm_alpha_t"),
        c5_post_alpha=gget("VW", "BM5-OP5 corner", GC_PERIODS[3][0], "capm_alpha_pct_yr"), c5_post_alpha_t=gget("VW", "BM5-OP5 corner", GC_PERIODS[3][0], "capm_alpha_t"),
        c5_10_alpha=gget("VW", "BM5-OP5 corner", GC_PERIODS[4][0], "capm_alpha_pct_yr"), c5_10_alpha_t=gget("VW", "BM5-OP5 corner", GC_PERIODS[4][0], "capm_alpha_t"),
        c5_ff3_pre=gget("VW", "BM5-OP5 corner", GC_PERIODS[2][0], "ff3_alpha_pct_yr"), c5_ff3_post=gget("VW", "BM5-OP5 corner", GC_PERIODS[3][0], "ff3_alpha_pct_yr"),
        c5_ff3_post_t=gget("VW", "BM5-OP5 corner", GC_PERIODS[3][0], "ff3_alpha_t"),
        c5_act_full=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[0][0], "ann_mean_pct"), c5_act_full_t=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[0][0], "t_nw"),
        c5_act_post=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[3][0], "ann_mean_pct"), c5_act_post_t=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[3][0], "t_nw"),
        c5_act_pre=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[2][0], "ann_mean_pct"), c5_act_pre_t=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[2][0], "t_nw"),
        c5_act_10=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[4][0], "ann_mean_pct"), c5_act_10_t=aget("VW", "BM5-OP5 corner minus Market (CRSP VW)", GC_PERIODS[4][0], "t_nw"),
        c4_act_full=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[0][0], "ann_mean_pct"),
        c4_act_full_t=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[0][0], "t_nw"),
        c4_act_10=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[4][0], "ann_mean_pct"),
        c4_act_10_t=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[4][0], "t_nw"),
        c4_sharpe_full=gget("VW", "Top-2 x top-2 corner (avg of 4)", GC_PERIODS[0][0], "sharpe"),
        c4_sharpe_post=gget("VW", "Top-2 x top-2 corner (avg of 4)", GC_PERIODS[3][0], "sharpe"),
        mkt_sharpe_post=gget("VW", "Market (CRSP VW)", GC_PERIODS[3][0], "sharpe"),
        c4_act_post=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[3][0], "ann_mean_pct"),
        c4_act_post_t=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[3][0], "t_nw"),
        c4_act_pre=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[2][0], "ann_mean_pct"),
        c4_act_pre_t=aget("VW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[2][0], "t_nw"),
        c4ew_act_post=aget("EW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[3][0], "ann_mean_pct"),
        c4ew_act_pre=aget("EW", "Top-2 x top-2 corner (avg of 4) minus Market (CRSP VW)", GC_PERIODS[2][0], "ann_mean_pct"),
    )

    # ---- E/P
    R.h(3, "C2. Earnings-to-price sorts (positive earnings only: quintiles formed on E/P, 1951-07 on)")
    ep_rows = []
    ep_periods = [("Full sample (1951-07 on)", None, None), ("Pre-publication (to 2005-10)", None, "2005-10"), ("Post-publication (2005-11 on)", "2005-11", None), ("2010-2026", "2010-01", None)]
    for w, ep in [("VW", D.ep_vw), ("EW", D.ep_ew)]:
        ser = {"Top quintile Q5 (highest E/P)": ep["Q5"], "Bottom quintile Q1 (lowest positive E/P)": ep["Q1"], "Negative earnings (E<=0)": ep["neg"], "Q5 minus Q1": ep["Q5"] - ep["Q1"], "Q5 minus market": ep["Q5"] - D.mkt}
        for label, a_, b_ in ep_periods:
            for name, s in ser.items():
                r = slice_period(s, a_, b_)
                if name in ("Q5 minus Q1", "Q5 minus market"):
                    pr = perf_row(r, None, D.mkt_ex, D.ff3)
                else:
                    pr = perf_row(r - D.rf.reindex(r.index), r, D.mkt_ex, D.ff3)
                pr.update(weighting=w, series=name, period=label)
                ep_rows.append(pr)
    epd = pd.DataFrame(ep_rows)
    first = ["weighting", "series", "period", "start", "end", "n"]
    epd = epd[first + [c for c in epd.columns if c not in first]]
    R.md("Excess returns over RF for the single quintiles; the two 'minus' rows are zero-cost spreads / active returns. CAPM and FF3 alphas, Newey-West t.\n")
    sel = epd[epd["weighting"] == "VW"]
    R.md("**Value-weighted**\n")
    R.md(md_table(sel[show].rename(columns=ren), {ren.get(k, k): v for k, v in fm.items()}) + "\n")
    sel = epd[epd["weighting"] == "EW"]
    R.md("**Equal-weighted**\n")
    R.md(md_table(sel[show].rename(columns=ren), {ren.get(k, k): v for k, v in fm.items()}) + "\n")
    R.tables["ep_quintiles"] = epd
    epd.to_csv(R.outdir / "ep_quintiles.csv", index=False, float_format="%.6g")
    R.md("*CSV: `ep_quintiles.csv`*\n")

    def e(w, s, p, col):
        return epd[(epd["weighting"] == w) & (epd["series"] == s) & (epd["period"] == p)].iloc[0][col]

    K.update(ep_spread_full=e("VW", "Q5 minus Q1", ep_periods[0][0], "ann_mean_pct"), ep_spread_full_t=e("VW", "Q5 minus Q1", ep_periods[0][0], "t_mean"),
             ep_spread_pre=e("VW", "Q5 minus Q1", ep_periods[1][0], "ann_mean_pct"), ep_spread_post=e("VW", "Q5 minus Q1", ep_periods[2][0], "ann_mean_pct"),
             ep_spread_post_t=e("VW", "Q5 minus Q1", ep_periods[2][0], "t_mean"), ep_spread_10=e("VW", "Q5 minus Q1", ep_periods[3][0], "ann_mean_pct"),
             ep_spread_10_t=e("VW", "Q5 minus Q1", ep_periods[3][0], "t_mean"),
             ep_ew_spread_pre=e("EW", "Q5 minus Q1", ep_periods[1][0], "ann_mean_pct"), ep_ew_spread_post=e("EW", "Q5 minus Q1", ep_periods[2][0], "ann_mean_pct"))

    # chart
    fig, ax = plt.subplots(figsize=(9, 4.8))
    base = _gc_series(D.bmop_vw)
    for (name, s), col in zip(list(base.items()) + [("Market (CRSP VW)", D.mkt.reindex(D.bmop_vw.index))], [C_BLUE, C_VIOLET, C_AQUA, C_INK2]):
        ax.plot((1 + s).cumprod(), color=col, label=name)
    _wealth_axis(ax)
    ax.axvline(pd.Timestamp(GB05.pub), color=C_RED, lw=1.1, ls="--")
    ax.text(pd.Timestamp(GB05.pub), 0.04, " Greenblatt book", transform=ax.get_xaxis_transform(), color=C_RED, fontsize=7)
    ax.set_title("'Good and cheap' corners vs market (VW, total return, no costs), growth of $1 from 1963-07")
    ax.legend(loc="upper left")
    fig.tight_layout()
    R.image(_save(fig, R.outdir, "good_and_cheap_growth.png"), "Good and cheap corners vs market")


# =====================================================================================
# d. Value
# =====================================================================================
def section_value(R: Report, D: Data, K: dict) -> None:
    R.h(2, "D. Value (relevant to trading comps): HML since 1926")
    hml = D.ff3["HML"]
    periods = [
        ("Full sample (1926-07 on)", None, None),
        ("1926-07..1963-06 (before FF sample)", None, "1963-06"),
        ("1963-07..1991-12 (FF92 sample and after)", "1963-07", "1991-12"),
        ("Pre-publication (to 1992-05)", None, "1992-05"),
        ("Post-publication (1992-06 on)", "1992-06", None),
        ("1992-2009", "1992-01", "2009-12"),
        ("2010-2026", "2010-01", None),
        ("2007-2018 (weak-value decade)", "2007-01", "2018-12"),
    ]
    tab = perf_table({"HML (FF3)": (hml, None)}, periods, D.mkt_ex, None)
    R.md(
        "HML (value minus growth, French's size x B/M 2x3 sorts, value-weighted) from the 3-factor file. Zero-cost spread; CAPM alpha on Mkt-RF with Newey-West t. "
        "This is the plain, across-industry B/M factor.\n"
    )
    show, ren, fmt = _fmt_perf_show()
    R.table("value_hml", tab, show=show, rename=ren, fmt=fmt)
    R.md(
        "**Caveat for the trading-comps idea.** Trading comps buys stocks that are cheap versus their GICS industry peers, i.e. an industry-RELATIVE value signal. The "
        "literature summarized in `research/04_trading_comps.md` finds most of the value effect is within industries (Asness-Porter-Stevens 2000 and Cohen-Polk-Vuolteenaho 2003 "
        "are cited there; the \"about 80% of B/M information is industry-relative\" figure is quoted from that literature and is NOT verified here), and that industry-adjusted HML "
        "was statistically indistinguishable from zero in 2007-2018 (Lev & Srivastava, as quoted in research/04). An industry-neutral value series **cannot be built from the "
        "French files used here** (they sort across all stocks); French's separate industry-portfolio files (49 industries) would be needed to approximate it, and even then they "
        "are not comps-multiple-based. Treat HML as an upper-level sanity check for 'cheap beats expensive', not as evidence for the 0.85x-peer-median rule.\n"
    )
    full, pre, post, rec, wk = tab.iloc[0], tab.iloc[3], tab.iloc[4], tab.iloc[6], tab.iloc[7]
    K.update(hml_full_mean=full["ann_mean_pct"], hml_full_t=full["t_mean"], hml_full_sharpe=full["sharpe"], hml_pre_mean=pre["ann_mean_pct"], hml_post_mean=post["ann_mean_pct"],
             hml_post_t=post["t_mean"], hml_post_sharpe=post["sharpe"], hml_pre_sharpe=pre["sharpe"], hml_10_mean=rec["ann_mean_pct"], hml_10_t=rec["t_mean"], hml_10_sharpe=rec["sharpe"],
             hml_wk_mean=wk["ann_mean_pct"], hml_wk_t=wk["t_mean"])


# =====================================================================================
# e. McLean & Pontiff decay table
# =====================================================================================
def _mp_windows(s: pd.Series, spec: PubSpec) -> dict[str, pd.Series]:
    s = s.dropna()
    is_end = pd.Timestamp(spec.is_end) + pd.offsets.MonthEnd(0)
    is_start = pd.Timestamp(spec.is_start) + pd.offsets.MonthEnd(0)
    pub = pd.Timestamp(spec.pub) + pd.offsets.MonthEnd(0)
    return {
        "pre_sample": s[s.index < is_start],
        "in_sample": s[(s.index >= is_start) & (s.index <= is_end)],
        "oos_prepub": s[(s.index > is_end) & (s.index < pub)],
        "post_pub": s[s.index >= pub],
    }


def section_mclean_pontiff(R: Report, D: Data, K: dict) -> None:
    R.h(2, "E. Post-publication decay (McLean & Pontiff 2016 style)")
    wml = D.dec_vw["D10"] - D.dec_vw["D1"]
    wml_ew = D.dec_ew["D10"] - D.dec_ew["D1"]
    bm = _gc_series(D.bmop_vw)["BM5-OP5 corner"]
    specs: list[tuple[str, pd.Series, PubSpec]] = [
        ("WML D10-D1 (VW)", wml, JT93), ("WML D10-D1 (EW)", wml_ew, JT93), ("Mom 2x3 (French)", D.mom, JT93),
        ("HML (FF3)", D.ff3["HML"], FF92), ("RMW (Novy-Marx dates)", D.ff5["RMW"], NM13), ("RMW (FF2015 dates)", D.ff5["RMW"], FF15),
    ]
    if D.qmj is not None:
        specs += [("QMJ USA (SSRN Oct 2013)", D.qmj, QMJ13), ("QMJ USA (RAST 2019)", D.qmj, QMJ19)]
    specs += [("BM5-OP5 minus market (VW)", bm - D.mkt, GB05)]
    rows = []
    for name, s, spec in specs:
        win = _mp_windows(s, spec)
        ins, oos, post, pre = win["in_sample"], win["oos_prepub"], win["post_pub"], win["pre_sample"]
        m_is = 100 * ins.mean()
        # regression r = a + b1*OOS + b2*POST (+ pre-sample dummy if any): b1, b2 are mean differences vs in-sample; HAC t
        d = pd.concat([ins, oos, post, pre]).sort_index()
        X = pd.DataFrame({"oos": d.index.isin(oos.index).astype(float), "post": d.index.isin(post.index).astype(float)}, index=d.index)
        if len(pre):
            X["pre_sample"] = d.index.isin(pre.index).astype(float)
        if len(oos) == 0:
            X = X.drop(columns="oos")
        reg = regress(d, X)
        m_oos = 100 * oos.mean() if len(oos) else np.nan
        m_post = 100 * post.mean()
        row = dict(
            factor=name, in_sample=f"{spec.is_start}..{spec.is_end}", published=spec.pub, n_is=len(ins), n_oos=len(oos), n_post=len(post), n_pre=len(pre),
            mean_pre_sample_pct_m=100 * pre.mean() if len(pre) else np.nan, mean_in_sample_pct_m=m_is,
            t_in_sample=ins.mean() / (ins.std(ddof=1) / np.sqrt(len(ins))) if len(ins) > 1 else np.nan,
            mean_oos_prepub_pct_m=m_oos, mean_post_pub_pct_m=m_post,
            t_post=post.mean() / (post.std(ddof=1) / np.sqrt(len(post))) if len(post) > 1 else np.nan,
            decline_oos_pct=100 * (1 - m_oos / m_is) if len(oos) and m_is else np.nan,
            decline_post_pct=100 * (1 - m_post / m_is) if m_is else np.nan,
            sharpe_in_sample=ins.mean() / ins.std(ddof=1) * np.sqrt(12), sharpe_post=post.mean() / post.std(ddof=1) * np.sqrt(12) if len(post) > 1 else np.nan,
            t_post_vs_is=reg["loading_t"]["post"] if reg else np.nan,
            source=spec.source,
        )
        rows.append(row)
    mp = pd.DataFrame(rows)
    R.md(
        "For each factor: average monthly return (%) in the original-paper sample, in the gap between the sample end and publication (out-of-sample, pre-publication), "
        "and after publication, with the percentage decline vs in-sample = 1 - mean(window)/mean(in-sample). With a single factor, McLean-Pontiff's regression "
        "r = a + b1 OOS + b2 POST reduces to these differences in means (b1 = mean(OOS) - mean(IS), b2 = mean(POST) - mean(IS)); `t(post vs IS)` is the Newey-West t of b2. "
        "McLean-Pontiff (97 equal-weighted long-short anomalies, 1926-2013): in-sample mean 58.2 bps/month; 26% lower out-of-sample and 58% lower post-publication "
        "(raw means 40.2 and 26.4 bps; research/06 section 1). Publication months: JT93 Mar 1993 (J. Finance), FF92 Jun 1992, Novy-Marx Apr 2013 (JFE 108(1)), Fama-French "
        "Apr 2015, QMJ SSRN Oct 2013 / RAST 2019, Greenblatt book late 2005; these dates come from memory and the research notes, not from the papers, so treat them "
        "as +-1 year. 'Pre-sample' is the history BEFORE the original sample, a free extra out-of-sample check that McLean-Pontiff do not use. Windows with fewer than about 24 months (see the n columns: the pre-publication gap is only 9-38 months for most factors) are too short to interpret and are shown for completeness.\n"
    )
    R.table("mclean_pontiff", mp,
            show=["factor", "in_sample", "published", "n_is", "n_oos", "n_post", "mean_pre_sample_pct_m", "mean_in_sample_pct_m", "t_in_sample", "mean_oos_prepub_pct_m", "mean_post_pub_pct_m", "decline_oos_pct", "decline_post_pct", "t_post", "t_post_vs_is", "sharpe_in_sample", "sharpe_post"],
            rename={"factor": "Factor", "in_sample": "In-sample", "published": "Pub", "n_is": "n IS", "n_oos": "n OOS", "n_post": "n post", "mean_pre_sample_pct_m": "Pre-sample %/mo",
                    "mean_in_sample_pct_m": "IS %/mo", "t_in_sample": "t IS", "mean_oos_prepub_pct_m": "OOS pre-pub %/mo", "mean_post_pub_pct_m": "Post-pub %/mo", "decline_oos_pct": "Decline OOS %",
                    "decline_post_pct": "Decline post %", "t_post": "t post", "t_post_vs_is": "t(post vs IS)", "sharpe_in_sample": "Sharpe IS", "sharpe_post": "Sharpe post"},
            fmt={"mean_pre_sample_pct_m": "{:.2f}", "mean_in_sample_pct_m": "{:.2f}", "t_in_sample": "{:.1f}", "mean_oos_prepub_pct_m": "{:.2f}", "mean_post_pub_pct_m": "{:.2f}",
                 "decline_oos_pct": "{:.0f}", "decline_post_pct": "{:.0f}", "t_post": "{:.1f}", "t_post_vs_is": "{:.1f}", "sharpe_in_sample": "{:.2f}", "sharpe_post": "{:.2f}"})
    sub = mp.set_index("factor")
    K["mp"] = sub
    primary = ["WML D10-D1 (VW)", "HML (FF3)", "RMW (Novy-Marx dates)", "BM5-OP5 minus market (VW)"] + (["QMJ USA (SSRN Oct 2013)"] if D.qmj is not None else [])
    avg_post = float(sub.loc[primary, "decline_post_pct"].mean())
    K.update(mp_avg_post_decline=avg_post, mp_wml_post_decline=sub.loc["WML D10-D1 (VW)", "decline_post_pct"], mp_hml_post_decline=sub.loc["HML (FF3)", "decline_post_pct"],
             mp_rmw_post_decline=sub.loc["RMW (Novy-Marx dates)", "decline_post_pct"], mp_c5_post_decline=sub.loc["BM5-OP5 minus market (VW)", "decline_post_pct"])
    if D.qmj is not None:
        K["mp_qmj_post_decline"] = sub.loc["QMJ USA (SSRN Oct 2013)", "decline_post_pct"]

    # bar chart
    fig, ax = plt.subplots(figsize=(10, 4.8))
    x = np.arange(len(mp))
    wdt = 0.27
    ax.bar(x - wdt, mp["mean_in_sample_pct_m"], wdt - 0.02, color=C_BLUE, label="Original sample")
    ax.bar(x, mp["mean_oos_prepub_pct_m"], wdt - 0.02, color=C_ORANGE, label="Out-of-sample, pre-publication")
    ax.bar(x + wdt, mp["mean_post_pub_pct_m"], wdt - 0.02, color=C_AQUA, label="Post-publication")
    for i, v in enumerate(mp["mean_post_pub_pct_m"]):
        ax.text(i + wdt, v + (0.03 if v >= 0 else -0.03), f"{v:.2f}", ha="center", va="bottom" if v >= 0 else "top", fontsize=6.5, color=C_INK2)
    ax.set_xticks(x)
    ax.set_xticklabels([n.replace(" (", "\n(") for n in mp["factor"]], fontsize=6.5, rotation=0)
    ax.axhline(0, color=C_INK2, lw=0.8)
    ax.set_ylabel("Mean monthly return, %")
    ax.set_title("Mean monthly factor return by window: original sample, out-of-sample before publication, after publication")
    ax.legend(loc="upper right")
    fig.tight_layout()
    R.image(_save(fig, R.outdir, "mclean_pontiff_decay.png"), "In-sample vs out-of-sample vs post-publication means")


# =====================================================================================
# Cross-factor charts
# =====================================================================================
def charts_factor_grid(R: Report, D: Data) -> None:
    wml = D.dec_vw["D10"] - D.dec_vw["D1"]
    corner = _gc_series(D.bmop_vw)["BM5-OP5 corner"]
    panels: list[tuple[str, pd.Series, PubSpec]] = [
        ("WML D10-D1 (VW)", wml, JT93), ("Mom 2x3 (French)", D.mom, JT93), ("RMW (profitability)", D.ff5["RMW"], NM13),
        ("HML (value)", D.ff3["HML"], FF92), ("BM5-OP5 minus market", corner - D.mkt, GB05),
    ]
    if D.qmj is not None:
        panels.insert(3, ("QMJ (AQR USA)", D.qmj, QMJ13))
    n = len(panels)
    ncols = 3
    nrows = int(np.ceil(n / ncols))
    for kind in ("cum", "sharpe"):
        fig, axes = plt.subplots(nrows, ncols, figsize=(12, 3.3 * nrows), sharex=False)
        axes = np.atleast_1d(axes).ravel()
        for ax, (title, s, spec) in zip(axes, panels):
            s = s.dropna()
            if kind == "cum":
                ax.plot((1 + s).cumprod(), color=C_BLUE)
                _wealth_axis(ax)
                ax.set_title(title)
            else:
                rs = s.rolling(36).mean() / s.rolling(36).std() * np.sqrt(12)
                ax.plot(rs, color=C_BLUE, lw=1.2)
                ax.axhline(0, color=C_INK2, lw=0.8)
                ax.set_title(title)
            _pub_lines(ax, spec)
        for ax in axes[n:]:
            ax.axis("off")
        sup = ("Growth of $1 compounding each factor's monthly return (log scale; dotted = original sample end, dashed red = publication)" if kind == "cum"
               else "Rolling 36-month Sharpe ratio, annualized (dotted = original sample end, dashed red = publication)")
        fig.suptitle(sup, fontsize=10, color=C_INK2, y=1.0)
        fig.tight_layout()
        R.charts.append(_save(fig, R.outdir, "factors_cumulative_growth.png" if kind == "cum" else "factors_rolling_sharpe_36m.png"))


# =====================================================================================
# Report assembly
# =====================================================================================
def _data_sources_table(D: Data) -> pd.DataFrame:
    items = [
        ("Mom deciles monthly VW/EW", "10_Portfolios_Prior_12_2_CSV.zip", D.dec_vw), ("Mom deciles daily VW/EW", "10_Portfolios_Prior_12_2_Daily_CSV.zip", D.dec_vw_d),
        ("FF3 monthly", "F-F_Research_Data_Factors_CSV.zip", D.ff3), ("FF5 (2x3) monthly", "F-F_Research_Data_5_Factors_2x3_CSV.zip", D.ff5),
        ("Mom 2x3 monthly", "F-F_Momentum_Factor_CSV.zip", D.mom.to_frame()), ("25 BM x OP monthly VW/EW", "25_Portfolios_BEME_OP_5x5_CSV.zip", D.bmop_vw),
        ("E/P portfolios monthly VW/EW", "Portfolios_Formed_on_E-P_CSV.zip", D.ep_vw),
    ]
    rows = [dict(dataset=a, source=b, first=x.index[0].strftime("%Y-%m-%d"), last=x.index[-1].strftime("%Y-%m-%d"), rows=len(x), status="ok") for a, b, x in items]
    if D.qmj is not None:
        rows.append(dict(dataset="AQR QMJ USA monthly", source="aqr.com Quality-Minus-Junk-Factors-Monthly.xlsx (sheet 'QMJ Factors', column USA)", first=D.qmj.index[0].strftime("%Y-%m-%d"),
                         last=D.qmj.index[-1].strftime("%Y-%m-%d"), rows=len(D.qmj), status="ok"))
    else:
        rows.append(dict(dataset="AQR QMJ USA monthly", source="aqr.com Quality-Minus-Junk-Factors-Monthly.xlsx", first="", last="", rows=0, status=f"UNAVAILABLE: {D.qmj_error[:120]}"))
    return pd.DataFrame(rows)


def _f(x: float, d: int = 2) -> str:
    return "n/a" if x is None or not np.isfinite(x) else f"{x:.{d}f}"


def takeaways(K: dict, D: Data) -> list[str]:
    t = []
    t.append(
        f"**Momentum is real in the long sample and mostly gone since 2009.** Decile WML (D10-D1, VW) earned {_f(K['wml_full_mean'],1)}%/yr with Sharpe {_f(K['wml_full_sharpe'])} over 1927-2026 "
        f"and Sharpe {_f(K['wml_pre_sharpe'])} before JT93's March 1993 publication versus {_f(K['wml_post_sharpe'])} after; 2009-2026 Sharpe is {_f(K['wml_09_sharpe'])}. "
        f"The long-only winners decile (VW) had CAPM alpha {_f(K['d10_alpha_6589'],1)}%/yr in the JT sample, {_f(K['d10_alpha_pre'],1)}%/yr (t {_f(K['d10_alpha_pre_t'],1)}) before 1993-03 and "
        f"{_f(K['d10_alpha_post'],1)}%/yr (t {_f(K['d10_alpha_post_t'],1)}) after; in 2009-2026 it is {_f(K['d10_alpha_9026'],1)}%/yr (t {_f(K['d10_alpha_9026_t'],1)}) and its Sharpe "
        f"({_f(K['d10_sharpe_09'])}) is below the market's ({_f(K['mkt_sharpe_09'])}). Equal-weighted winners did better than value-weighted ones over the full sample "
        f"(Sharpe {_f(K['d10ew_sharpe_full'])} vs {_f(K['d10_sharpe_full'])}) but also lost their alpha after 2009."
    )
    t.append(
        f"**Volatility scaling works and still helps out of sample.** Barroso-Santa-Clara scaling of WML moves Sharpe {_f(K['bsc_static_sharpe'])} -> {_f(K['bsc_scaled_sharpe'])} (1927-2011; "
        f"research/01 replication: 0.54 -> 1.00) and {_f(K['bsc_12_static'])} -> {_f(K['bsc_12_scaled'])} in 2012-2026, with the worst month cut from {_f(K['bsc_worst_static'],1)}% to {_f(K['bsc_worst_scaled'],1)}%. "
        f"For the long-only winners decile a 20% own-vol target (cap 1) lifts full-sample Sharpe {_f(K['lod_bh_sharpe'])} -> {_f(K['lod_vt_sharpe'])} and cuts max drawdown {_f(K['lod_bh_dd'],1)}% -> {_f(K['lod_vt_dd'],1)}% "
        f"(daily-formed decile, research/01 section 8: 0.61 -> 0.67, -83.8% -> -74.0%); on the monthly-formed decile {_f(K['lo_bh_sharpe'])} -> {_f(K['lo_vt_sharpe'])}, {_f(K['lo_bh_dd'],1)}% -> {_f(K['lo_vt_dd'],1)}%. "
        "The gain is modest for a long-only book: most of the 1930s drawdown is the market's."
    )
    t.append(
        f"**Crashes are a bear-state, short-leg phenomenon.** {K['n_bear_dm']} of {K['n_dm']} months in 1927-01..2013-03 are bear states (DM: 183 of 1,035). WML averages {_f(K['wml_bear'])}%/mo in bear "
        f"states vs {_f(K['wml_nonbear'])}%/mo otherwise; the winners decile beats the market by {_f(K['d10mkt_bear'])}%/mo in bear vs {_f(K['d10mkt_nonbear'])}%/mo in non-bear months. "
        f"{K['n_bear_dm15']} of the 15 worst WML months up to 2013-03 are in bear states (DM: 14); across the whole sample the winners decile fell in only {K['n_d10_down']} of the 15 worst WML months, "
        f"while {K['n_mkt_up']} of 15 were months of rising markets."
    )
    t.append(
        f"**Current regime ({K['last_daily']}).** 126-day WML volatility is {_f(100*K['cur_wml'],1)}% against a long-run {_f(100*K['lrm_wml'],1)}% (monthly-file spread; {_f(100*K['pct_wml'],0)}th percentile of its own daily history): "
        f"the BSC weight on WML is {_f(K['cur_w'])}; winners-decile vol is {_f(100*K['cur_d10'],1)}% (20%-target long-only weight {_f(K['cur_w_lo'])}). The market's prior-24-month return is {_f(100*K['p24_now'],1)}%, "
        f"so the DM bear flag is {'ON' if K['p24_now'] < 0 else 'off'}: a volatility-driven, not bear-driven, momentum stress. French data end {K['last_daily']}; recompute from daily prices before trading."
    )
    t.append(
        f"**Profitability and quality are positive but have weakened.** RMW earned {_f(K['rmw_full_mean'],1)}%/yr (Sharpe {_f(K['rmw_full_sharpe'])}, t {_f(K['rmw_full_t'],1)}) in 1963-2026; Sharpe is "
        f"{_f(K['rmw_pre_sharpe'])} before 2013 and {_f(K['rmw_post_sharpe'])} since (mean {_f(K['rmw_pre_mean'],1)}% -> {_f(K['rmw_post_mean'],1)}%/yr, post-2013 t {_f(K['rmw_post_t'],1)})."
        + (f" AQR QMJ (USA): {_f(K['qmj_full_mean'],1)}%/yr, Sharpe {_f(K['qmj_full_sharpe'])} (t {_f(K['qmj_full_t'],1)}) from 1957; Sharpe {_f(K['qmj_pre_sharpe'])} to 2012 vs {_f(K['qmj_post_sharpe'])} since 2013."
           if D.qmj is not None else " AQR QMJ was not available.")
        + f" Quality is a diversifier for momentum, not a crash hedge: RMW's correlation with Mom 2x3 is {_f(K['corr_mom_rmw'])}"
        + (f" and QMJ's is {_f(K['corr_mom_qmj'])}" if D.qmj is not None else "")
        + f"; in the worst 5% Mom months RMW averaged {_f(K['tail_rmw'])}%/mo"
        + (f" and QMJ {_f(K['tail_qmj'])}%/mo" if D.qmj is not None else "")
        + f". A 50/50 Mom+RMW blend has Sharpe {_f(K['sh_mom_rmw'])} vs {_f(K['sh_mom'])} (Mom) and {_f(K['sh_rmw'])} (RMW) over {K['panel_start']}..{K['panel_end']}"
        + (f"; Mom+QMJ {_f(K['sh_mom_qmj'])}." if D.qmj is not None else ".")
    )
    t.append(
        f"**'Good and cheap' (B/M x profitability corners, VW)**: the top-2 x top-2 corner (4 portfolios) beat the market by {_f(K['c4_act_full'],1)}%/yr over 1963-2026 (t {_f(K['c4_act_full_t'],1)}), "
        f"{_f(K['c4_act_pre'],1)}%/yr (t {_f(K['c4_act_pre_t'],1)}) before the 2005 Greenblatt book, {_f(K['c4_act_post'],1)}%/yr (t {_f(K['c4_act_post_t'],1)}) after, and {_f(K['c4_act_10'],1)}%/yr (t {_f(K['c4_act_10_t'],1)}) in 2010-2026. "
        f"The extreme BM5-OP5 corner is noisier (excess vs market {_f(K['c5_act_full'],1)}%/yr, t {_f(K['c5_act_full_t'],1)} full; {_f(K['c5_act_post'],1)}%/yr post-2005; {_f(K['c5_act_10'],1)}%/yr in 2010-2026): "
        f"CAPM alpha {_f(K['c5_pre_alpha'],1)}%/yr (t {_f(K['c5_pre_alpha_t'],1)}) before vs {_f(K['c5_post_alpha'],1)}%/yr (t {_f(K['c5_post_alpha_t'],1)}) after, FF3 alpha after {_f(K['c5_ff3_post'],1)}%/yr (t {_f(K['c5_ff3_post_t'],1)}). "
        f"The E/P top-minus-bottom quintile spread (VW) is {_f(K['ep_spread_pre'],1)}%/yr before and {_f(K['ep_spread_post'],1)}%/yr after 2005-11 ({_f(K['ep_spread_10'],1)}%/yr in 2010-2026). "
        "Honest read: cheap-and-profitable beat the market for four decades and has not since the book appeared; this matches research/03's post-2010 evidence, so the Magic Formula should be justified by process, not by a recent edge."
    )
    t.append(
        f"**Value (HML)**: {_f(K['hml_full_mean'],1)}%/yr (t {_f(K['hml_full_t'],1)}) over 1926-2026; {_f(K['hml_pre_mean'],1)}%/yr before FF92 publication (1992-06) vs {_f(K['hml_post_mean'],1)}%/yr after "
        f"(t {_f(K['hml_post_t'],1)}); {_f(K['hml_10_mean'],1)}%/yr in 2010-2026 (t {_f(K['hml_10_t'],1)}) and {_f(K['hml_wk_mean'],1)}%/yr in 2007-2018. The plain across-industry value factor has been flat for a decade or more, "
        "which is a headwind for the comps idea; industry-relative value (what comps actually buys) cannot be built from these files."
    )
    t.append(
        f"**Decay after publication** (mean monthly return, post vs original sample): WML {_f(K['mp_wml_post_decline'],0)}%, HML {_f(K['mp_hml_post_decline'],0)}%, RMW {_f(K['mp_rmw_post_decline'],0)}%"
        + (f", QMJ {_f(K['mp_qmj_post_decline'],0)}%" if 'mp_qmj_post_decline' in K else "")
        + f", BM5-OP5-minus-market {_f(K['mp_c5_post_decline'],0)}% (average of these {_f(K['mp_avg_post_decline'],0)}%), against McLean-Pontiff's 58% post-publication (26% out-of-sample) "
        "for 97 anomalies. These are single factors with wide error bands (post-vs-in-sample t-stats are mostly below 2 in magnitude); the pattern, not any one percentage, is the evidence."
    )
    return t


def build(refresh: bool = False, outdir: Path | None = None) -> Path:
    _style()
    R = Report(outdir or OUT_DIR)
    D = load_data(refresh)
    K: dict = {}
    section_momentum(R, D, K)
    section_quality(R, D, K)
    section_good_and_cheap(R, D, K)
    section_value(R, D, K)
    section_mclean_pontiff(R, D, K)
    charts_factor_grid(R, D)

    # ---- assemble the final markdown in the right order
    body = R.parts
    R.parts = []
    R.md("# Academic evidence: do the three strategy ideas work at the factor level?")
    R.md(
        f"Generated by `quant/validation/factor_checks.py` from Ken French's data library (CRSP, vintage `202608`; data through {D.ff3.index[-1].strftime('%Y-%m')}) and AQR's QMJ dataset"
        f"{'' if D.qmj is not None else ' (UNAVAILABLE in this run)'}. These are long-history, survivorship-free CRSP portfolios (1926-2026), so they test the IDEAS at factor/decile level; "
        "they are **not** a test of our stock-level S&P-style backtests (2011-2026), they are gross of costs, and French's momentum deciles are not 5-10 stock books. "
        "All returns are decimals in the code and shown here in percent. Sharpe ratios are annualized from monthly arithmetic means (mean/sd x sqrt(12)).\n"
    )
    R.h(2, "Key findings")
    for line in takeaways(K, D):
        R.md(f"- {line}")
    R.md("")
    R.md("![Cumulative growth](factors_cumulative_growth.png)\n")
    R.md("![Rolling Sharpe](factors_rolling_sharpe_36m.png)\n")
    R.parts.extend(body)

    # reference check section
    refs = pd.DataFrame(R.refs)
    R.h(2, "Sanity check against the research notes")
    n_ok = int((refs["match"] == "OK").sum())
    R.md(f"Our numbers vs the reference values written in `research/01_momentum.md` sections 3, 4, 8, 9, 13 (the notes' own replication on the same French files) and the Fama-French / AQR paper tables quoted in "
         f"`research/02_quality.md`. Tolerance reflects the rounding used in the notes. **{n_ok} of {len(refs)} checks match.** DIFF rows are listed in full; matching rows are in `reference_checks.csv`.\n")
    diffs = refs[refs["match"] != "OK"]
    if len(diffs):
        R.md(md_table(diffs[["item", "ours", "research", "diff", "tol", "note"]], {"ours": "{:.3f}", "research": "{:.3f}", "diff": "{:+.3f}", "tol": "{:.2f}"}) + "\n")
    else:
        R.md("All checks within tolerance.\n")
    refs.to_csv(R.outdir / "reference_checks.csv", index=False, float_format="%.6g")
    K["n_ref_ok"], K["n_ref"] = n_ok, len(refs)

    R.h(2, "Data sources and download status")
    ds = _data_sources_table(D)
    R.table("data_sources", ds)
    R.h(2, "Method notes and limits")
    R.md(
        "- **Sampling.** Monthly returns are indexed by month-end; the 126-day volatility uses French's daily decile files (6-day trading weeks before 1952 are in the data as published).\n"
        "- **Daily vs monthly deciles.** The monthly deciles are formed on months -12..-2; the daily deciles on days -250..-21. We scale the monthly-file spread with volatility from the daily-file spread, as in the research notes.\n"
        "- **Newey-West.** `quant.backtest.stats.ols_hac` (Bartlett kernel, small-sample factor T/(T-k); a private equivalent is the fallback); lags = max(4, floor(4 (T/100)^(2/9))).\n"
        "- **Alpha units.** Alpha %/yr = 12 x monthly alpha; t-stats are HAC. The mean t-stat in the tables is i.i.d.\n"
        "- **Max drawdown** compounds monthly returns (including for zero-cost spreads, where it is a convention, not an investable path).\n"
        "- **Not tested here:** industry-relative value, transaction costs, shorting costs, the long-only 5-10 stock concentration, and anything after the data end. Daily data end with the monthly files; "
        "recompute the current-regime numbers from daily prices through the decision date.\n"
        "- **McLean-Pontiff comparison** is indicative: they pool 97 equal-weighted long-short portfolios; here each factor is one noisy series with value-weighted spreads (apart from the EW WML row).\n"
    )
    path = R.save()
    log.info("wrote %s (%d charts, %d tables)", path, len(R.charts), len(R.tables))
    return path


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    ap.add_argument("--refresh", action="store_true", help="re-download all factor files")
    ap.add_argument("--out", type=Path, default=None, help=f"output directory (default {OUT_DIR})")
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(levelname)s %(name)s: %(message)s")
    path = build(args.refresh, args.out)
    print(f"wrote {path}")


if __name__ == "__main__":
    main()
