"""Tear sheet tables and charts (research/06 section 8): matplotlib (Agg) PNGs + markdown into ``output/<strategy>/``.

Public API (every function returns the paths it wrote)
-------------------------------------------------------
``tearsheet(name, strat_daily_net, strat_daily_gross, benchmarks, rf, factors_monthly, windows, out_dir, header,
turnover=None, holdings=None, ...) -> Path``
    T1 performance per window (net, gross, SPY / RSP / EW-universe columns), T2 factor regressions
    (CAPM, FF3+MOM, FF5+MOM, HAC; plus the active-return version), T7 short-horizon table (13 / 63 / 126 trading
    days: P(beat), quantiles) and its forward-expectation companion, charts C1 growth of $1, C2 underwater,
    C3 rolling 12m excess + 36m IR, C4 calendar years, C5 horizon histograms (+ C8 factor loadings).
    Returns the markdown path (``return_all=True`` returns every written path, markdown first).
``grid_figures(grid_result, window, x_axis, y_axis, facet_axes, out_dir, ...) -> list[Path]``
    C6 heatmaps (numbers printed in each cell; primary) and 3D interpolated surfaces (secondary; grid points,
    selected cell and default marked), one file per facet combination, plus a small-multiples overview.
``pbo_figure(pbo_result, out_dir) -> list[Path]``      C7 logit histogram + IS vs OOS Sharpe scatter.
``correlation_figure(series_dict, out_dir) -> list[Path]``   C10 correlation heatmaps (returns, active returns).
``standard_windows(first, last) -> dict``     the Full / Train / Test / Last 36m / calendar sub-period windows.

Statistics come from ``metrics`` / ``stats``; nothing is re-implemented here. Colours follow the dataviz skill's
validated categorical order (blue, orange, aqua, yellow, ...) with line style as the secondary encoding.
"""
from __future__ import annotations

import itertools
import logging
import re
import warnings
from datetime import datetime, timezone
from pathlib import Path
from typing import Mapping, Sequence

import matplotlib

matplotlib.use("Agg")  # noqa: E402  (must precede pyplot import)
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402
from matplotlib.colors import LinearSegmentedColormap, TwoSlopeNorm, Normalize  # noqa: E402
from matplotlib.lines import Line2D  # noqa: E402
from matplotlib.ticker import FuncFormatter, LogLocator, MaxNLocator, NullLocator, PercentFormatter  # noqa: E402
from scipy.stats import norm  # noqa: E402

from . import metrics, stats  # noqa: E402
from .grid import _level_index, _same_level, _to_ts, _window_label  # noqa: E402

log = logging.getLogger(__name__)

__all__ = ["tearsheet", "grid_figures", "pbo_figure", "correlation_figure", "standard_windows",
           "selection_markdown", "overfitting_markdown", "regression_markdown"]

# ----------------------------------------------------------------------------------------------
# style
# ----------------------------------------------------------------------------------------------
SURFACE, INK, INK2, GRIDC = "#fcfcfb", "#0b0b0b", "#52514e", "#e4e3df"
SERIES = ["#2a78d6", "#eb6834", "#1baf7a", "#eda100", "#e87ba4", "#008300", "#6250d6", "#e34948"]
BLUE_RAMP = ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"]       # sequential (palette steps 100..700)
DIV_NEG, DIV_MID, DIV_POS = "#e34948", "#f0efec", "#2a78d6"                 # diverging: red <- gray -> blue
TRAIN_TINT, TEST_TINT = "#cde2fb", "#fbe3d2"
SEQ_CMAP = LinearSegmentedColormap.from_list("seq_blue", BLUE_RAMP)
DIV_CMAP = LinearSegmentedColormap.from_list("div_rb", [DIV_NEG, DIV_MID, DIV_POS])
RC = {
    "figure.facecolor": SURFACE, "axes.facecolor": SURFACE, "savefig.facecolor": SURFACE,
    "axes.edgecolor": GRIDC, "axes.labelcolor": INK2, "axes.titlecolor": INK, "text.color": INK,
    "xtick.color": INK2, "ytick.color": INK2, "grid.color": GRIDC, "grid.linewidth": 0.7,
    "axes.grid": True, "axes.axisbelow": True, "axes.spines.top": False, "axes.spines.right": False,
    "font.size": 10, "axes.titlesize": 12, "axes.titleweight": "bold", "axes.labelsize": 10,
    "legend.frameon": False, "legend.fontsize": 9, "lines.linewidth": 1.6, "figure.dpi": 100,
}
DPI = 150

M_ROW_ORDER = ["Months", "CAGR", "AnnVol", "Sharpe", "Sharpe 95% CI", "Sortino", "MaxDD (daily)", "MaxDD peak>trough",
               "Calmar", "Beta", "TE", "IR", "ActiveCAGR", "HitRate 1m", "HitRate 3m", "HitRate 6m",
               "Up capture", "Down capture"]
FACTOR_ALIASES = {"mktrf": "Mkt-RF", "mkt_rf": "Mkt-RF", "mktminusrf": "Mkt-RF", "smb": "SMB", "hml": "HML",
                  "rmw": "RMW", "cma": "CMA", "mom": "Mom", "umd": "Mom", "wml": "Mom", "momentum": "Mom"}
FACTOR_ORDER = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
MODEL_LABELS = {"capm": "CAPM", "ff3mom": "FF3+MOM", "ff5mom": "FF5+MOM"}


# ----------------------------------------------------------------------------------------------
# small utilities
# ----------------------------------------------------------------------------------------------
def _slug(s: str) -> str:
    return re.sub(r"[^a-z0-9]+", "_", str(s).lower()).strip("_") or "x"


def _save(fig, path: Path) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    with warnings.catch_warnings():
        warnings.simplefilter("ignore")
        fig.savefig(path, dpi=DPI, bbox_inches="tight")
    plt.close(fig)
    return path


def _nan(x) -> bool:
    return x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x))


def _f(x, kind: str = "num2") -> str:
    """Format a number for a table cell; missing -> en dash."""
    if _nan(x):
        return "–"
    if isinstance(x, str):
        return x
    if kind == "pct":
        return f"{x * 100:.1f}%"
    if kind == "pct0":
        return f"{x * 100:.0f}%"
    if kind == "pct2":
        return f"{x * 100:.2f}%"
    if kind == "num3":
        return f"{x:.3f}"
    if kind == "num0":
        return f"{x:,.0f}"
    if kind == "int":
        return f"{int(x)}"
    return f"{x:.2f}"


def _md_table(df: pd.DataFrame, index: bool = True, index_name: str = "") -> str:
    """Pipe table (no external dependency). Cells are expected to be strings already."""
    cols = list(df.columns)
    head = ([index_name or (df.index.name or "")] if index else []) + [str(c) for c in cols]
    lines = ["| " + " | ".join(head) + " |", "|" + "|".join(["---"] * len(head)) + "|"]
    for ix, row in df.iterrows():
        cells = ([str(ix)] if index else []) + ["–" if (isinstance(v, float) and not np.isfinite(v)) else str(v)
                                                for v in row.tolist()]
        lines.append("| " + " | ".join(c.replace("|", "/") for c in cells) + " |")
    return "\n".join(lines)


def _style_ax(ax, title=None, xlabel=None, ylabel=None):
    if title:
        ax.set_title(title, loc="left")
    if xlabel:
        ax.set_xlabel(xlabel)
    if ylabel:
        ax.set_ylabel(ylabel)


def _pct_axis(ax, axis="y", decimals=0):
    fmt = PercentFormatter(1.0, decimals=decimals)
    (ax.yaxis if axis == "y" else ax.xaxis).set_major_formatter(fmt)


def _clean_daily(s, label: str) -> pd.Series:
    s = pd.Series(s).astype(float).copy()
    idx = pd.DatetimeIndex(s.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    s.index = idx.normalize()
    s = s[~s.index.duplicated(keep="last")].sort_index()
    s.name = label
    return s


def _monthly(daily: pd.Series) -> pd.Series:
    """Calendar-month returns labelled by calendar month end; a leading/trailing month with < 60% of its business days is dropped."""
    d = daily.dropna()
    if d.empty:
        return pd.Series(dtype=float)
    m = metrics.to_monthly(d)
    per = d.index.to_period("M")
    cnt = d.groupby(per).size()
    m.index = m.index.to_period("M")
    m = m.groupby(level=0).last()
    keep = np.ones(len(m), dtype=bool)
    for pos in (0, len(m) - 1):
        p = m.index[pos]
        expected = np.busday_count(p.start_time.date(), (p + 1).start_time.date())
        if expected > 0 and cnt.get(p, 0) < 0.6 * expected:
            keep[pos] = False
    m = m[keep]
    m.index = m.index.to_timestamp(how="end").normalize()      # calendar month-end labels
    return m


def _mask_dates(index: pd.DatetimeIndex, window) -> np.ndarray:
    if window is None:
        return np.ones(len(index), dtype=bool)
    s, e = _to_ts(window[0]), _to_ts(window[1], end=True)
    m = np.ones(len(index), dtype=bool)
    if s is not None:
        m &= np.asarray(index >= s)
    if e is not None:
        m &= np.asarray(index <= e)
    return m


def _mask_periods(month_ends: pd.DatetimeIndex, window) -> np.ndarray:
    """Months (labelled by month end) that overlap ``window``."""
    if window is None:
        return np.ones(len(month_ends), dtype=bool)
    s, e = _to_ts(window[0]), _to_ts(window[1], end=True)
    m = np.ones(len(month_ends), dtype=bool)
    if s is not None:
        m &= np.asarray(month_ends >= s)
    if e is not None:
        m &= np.asarray(month_ends.to_period("M").start_time <= e)
    return m


def _wlabel(label: str, window, first, last) -> str:
    s, e = window if window is not None else (None, None)
    s = first if s is None else max(pd.Timestamp(_to_ts(s)), pd.Timestamp(first))
    e = last if e is None else min(pd.Timestamp(_to_ts(e, end=True)), pd.Timestamp(last))
    return f"{label} ({pd.Timestamp(s):%Y-%m} to {pd.Timestamp(e):%Y-%m})"


def standard_windows(first, last, train_end: str | None = None, test_start: str | None = None) -> dict:
    """Full / Train / Test / Last 36m plus calendar sub-periods (research/06 section 2.1), clipped to the data."""
    if train_end is None or test_start is None:
        from quant import settings
        train_end = train_end or settings.TRAIN_END
        test_start = test_start or settings.TEST_START
    first, last = pd.Timestamp(first), pd.Timestamp(last)
    w = {"Full": (None, None), "Train": (None, train_end), "Test": (test_start, None),
         "Last 36m": ((last - pd.DateOffset(months=36) + pd.Timedelta(days=1)).strftime("%Y-%m-%d"), None)}
    for a, b in [(2010, 2014), (2015, 2018), (2019, 2021), (2022, 2026)]:
        if pd.Timestamp(year=b, month=12, day=31) >= first and pd.Timestamp(year=a, month=1, day=1) <= last:
            w[f"{a}-{str(b)[2:]}"] = (f"{a}-01-01", f"{b}-12-31")
    return w


def _canon_factors(F: pd.DataFrame | None) -> pd.DataFrame | None:
    if F is None or len(F) == 0:
        return None
    ren = {}
    for c in F.columns:
        key = re.sub(r"[^a-z_]", "", str(c).lower().replace("-", "_").replace(" ", "_"))
        key2 = key.replace("_", "")
        for k in (key, key2):
            if k in FACTOR_ALIASES:
                ren[c] = FACTOR_ALIASES[k]
                break
    return F.rename(columns=ren)


# ----------------------------------------------------------------------------------------------
# data bundle
# ----------------------------------------------------------------------------------------------
class _Bundle:
    """Aligned daily and monthly return frames for the strategy (net / gross) and the benchmarks."""

    def __init__(self, net, gross, benchmarks: Mapping[str, pd.Series], rf, primary: str):
        net = _clean_daily(net, "Strategy (net)")
        self.cols = ["Strategy (net)", "Strategy (gross)"] + list(benchmarks)
        gross = net if gross is None else _clean_daily(gross, "Strategy (gross)").reindex(net.index)
        data = {"Strategy (net)": net, "Strategy (gross)": gross}
        for k, v in benchmarks.items():
            data[k] = _clean_daily(v, k).reindex(net.index)
        self.D = pd.DataFrame(data)
        self.bench_names = list(benchmarks)
        self.primary = primary
        if rf is None:
            self.rf_d = pd.Series(0.0, index=net.index)
        else:
            self.rf_d = _clean_daily(rf, "rf").reindex(net.index).fillna(0.0)
        self.Mo = pd.DataFrame({c: _monthly(self.D[c]) for c in self.cols})
        self.rf_m = _monthly(self.rf_d).reindex(self.Mo.index).fillna(0.0)
        self.first, self.last = net.index[0], net.index[-1]

    def monthly(self, col, window=None):
        s = self.Mo[col]
        return s[_mask_periods(self.Mo.index, window)]

    def monthly_frame(self, cols, window=None) -> pd.DataFrame:
        df = self.Mo[list(cols)]
        df = df[_mask_periods(df.index, window)]
        return df

    def daily(self, col, window=None) -> pd.Series:
        s = self.D[col]
        return s[_mask_dates(s.index, window)]

    def rfm(self, window=None) -> pd.Series:
        return self.rf_m[_mask_periods(self.rf_m.index, window)]


# ----------------------------------------------------------------------------------------------
# T1 performance
# ----------------------------------------------------------------------------------------------
def _sharpe_ci(excess: np.ndarray, B: int, seed: int) -> tuple[float, float] | None:
    x = excess[np.isfinite(excess)]
    if len(x) < 18 or B <= 0:
        return None
    fn = lambda a: float(a.mean() / a.std(ddof=1) * np.sqrt(12)) if a.std(ddof=1) > 0 else np.nan  # noqa: E731
    ci, _ = stats.bootstrap_ci(fn, x, mean_block=6, B=B, seed=seed)
    return float(ci[0]), float(ci[1])


def _dd_str(d: pd.Series) -> tuple[float, str]:
    r = metrics.max_drawdown_dates(d)
    if _nan(r["max_dd"]):
        return np.nan, "–"
    if r["trough"] is None:
        return 0.0, "–"
    pk = "start" if r.get("peak_is_start") else f"{pd.Timestamp(r['peak']):%Y-%m-%d}"
    return float(r["max_dd"]), f"{pk} > {pd.Timestamp(r['trough']):%Y-%m-%d}"


def _t1_window(bun: _Bundle, window, n_boot: int, seed: int, turnover, holdings) -> pd.DataFrame:
    """One T1 panel: rows = statistics, columns = Strategy (net/gross) + benchmarks (numbers or strings)."""
    prim = bun.primary
    out = {}
    rf_all = bun.rfm(window)
    summ = {}
    for c in bun.cols:
        b = None if c == prim else bun.monthly(prim, window)
        summ[c] = metrics.summary_table(bun.monthly(c, window).dropna(), b, rf_all, 12, {"w": (None, None)})["w"]
    for c in bun.cols:
        s = summ[c]
        rm = bun.monthly(c, window)
        bm = bun.monthly(prim, window)
        pair = pd.concat([rm, bm, rf_all], axis=1, keys=["r", "b", "rf"]).dropna()
        col = {"Months": int(rm.notna().sum()),
               "CAGR": s["CAGR"], "AnnVol": s["AnnVol"], "Sharpe": s["Sharpe"], "Sortino": s["Sortino"],
               "Beta": s["Beta"], "TE": s["TE"], "IR": s["IR"], "ActiveCAGR": s["ActiveCAGR"], "HitRate 1m": s["HitRate"]}
        ci = _sharpe_ci((pair["r"] - pair["rf"]).to_numpy(), n_boot, seed)
        col["Sharpe 95% CI"] = "–" if ci is None else f"[{ci[0]:.2f}, {ci[1]:.2f}]"
        dd, dd_s = _dd_str(bun.daily(c, window))
        col["MaxDD (daily)"] = dd
        col["MaxDD peak>trough"] = dd_s
        col["Calmar"] = s["CAGR"] / abs(dd) if np.isfinite(dd) and dd < 0 and np.isfinite(s["CAGR"]) else np.nan
        if c != prim and len(pair) >= 6:
            for h in (3, 6):
                if len(pair) > h:
                    e = metrics.rolling_compound(pair["r"].to_numpy(), h) - metrics.rolling_compound(pair["b"].to_numpy(), h)
                    col[f"HitRate {h}m"] = float(np.mean(e > 0))
            up, dn = metrics.capture_ratios(pair["r"].to_numpy(), pair["b"].to_numpy())
            col["Up capture"], col["Down capture"] = up, dn
        out[c] = col
    df = pd.DataFrame(out).reindex(M_ROW_ORDER + [])
    df.index.name = "metric"
    # strategy-only extras
    extras = {}
    for other in bun.bench_names:
        if other == prim:
            continue
        rm = bun.monthly("Strategy (net)", window)
        pair = pd.concat([rm, bun.monthly(other, window)], axis=1).dropna()
        extras[f"IR vs {other}"] = metrics.information_ratio(pair.iloc[:, 0], pair.iloc[:, 1], 12) if len(pair) > 2 else np.nan
    g, n = summ["Strategy (gross)"]["CAGR"], summ["Strategy (net)"]["CAGR"]
    extras["Cost drag (bps/yr, gross CAGR - net CAGR)"] = (g - n) * 1e4 if np.isfinite(g) and np.isfinite(n) else np.nan
    dmask = _mask_dates(bun.D.index, window)
    ndays = int(dmask.sum())
    years = max(ndays / 252.0, 1e-9)
    if holdings is not None:
        h = holdings.reindex(bun.D.index)[dmask]
        extras["Avg holdings"] = float(h.mean()) if h.notna().any() else np.nan
    if turnover is not None:
        t = turnover.reindex(bun.D.index)[dmask]
        extras["Annual one-way turnover"] = float(t.fillna(0.0).sum() / years) if t.notna().any() else np.nan
    for k, v in extras.items():
        df.loc[k] = {"Strategy (net)": v}
    df = df.rename(index={"Beta": f"Beta vs {prim}", "TE": f"TE vs {prim}", "IR": f"IR vs {prim}",
                          "ActiveCAGR": f"ActiveCAGR vs {prim}", "HitRate 1m": "HitRate 1m", "Up capture": f"Up capture vs {prim}",
                          "Down capture": f"Down capture vs {prim}"})
    return df


_T1_KINDS = [("Cost drag", "num0"), ("Months", "int"), ("Annual one-way turnover", "pct0"), ("Avg holdings", "num2"),
             ("MaxDD", "pct"), ("CAGR", "pct"), ("ActiveCAGR", "pct"), ("AnnVol", "pct"), ("TE", "pct"), ("HitRate", "pct0"),
             ("Up capture", "pct0"), ("Down capture", "pct0")]


def _kind_for(metric: str) -> str:
    for prefix, kind in _T1_KINDS:
        if metric.startswith(prefix):
            return kind
    return "num2"                                                    # Sharpe, Sortino, Calmar, Beta, IR


def _fmt_t1(df: pd.DataFrame) -> pd.DataFrame:
    out = df.copy().astype(object)
    for ix in out.index:
        k = _kind_for(str(ix))
        out.loc[ix] = [(_f(v, k) if not isinstance(v, str) else v) for v in df.loc[ix].tolist()]
    return out


# ----------------------------------------------------------------------------------------------
# T2 factor regressions
# ----------------------------------------------------------------------------------------------
def _t2_rows(bun: _Bundle, F: pd.DataFrame, windows: dict, min_months: int = 36):
    notes: list[str] = []
    rows = []
    prim = bun.primary
    for wlabel, win in windows.items():
        rm = bun.monthly("Strategy (net)", win)
        rf = bun.rfm(win)
        y_ex = (rm - rf).dropna()
        y_act = (rm - bun.monthly(prim, win)).dropna()
        for y_name, y in (("excess vs rf", y_ex), (f"active vs {prim}", y_act)):
            if len(y) < min_months:
                notes.append(f"{wlabel}: only {len(y)} months, regressions skipped")
                break
            ys = y
            models = ("capm", "ff3mom", "ff5mom") if y_name.startswith("excess") else ("ff5mom",)
            for mdl in models:
                need = stats.FACTOR_MODELS[mdl]
                if any(c not in F.columns for c in need):
                    notes.append(f"{wlabel}/{MODEL_LABELS[mdl]}: factors lack {[c for c in need if c not in F.columns]}")
                    continue
                try:
                    r4 = stats.factor_regression(ys, F, model=mdl, lags=4)
                    r6 = stats.factor_regression(ys, F, model=mdl, lags=6)
                    r12 = stats.factor_regression(ys, F, model=mdl, lags=12)
                except (ValueError, KeyError) as exc:
                    notes.append(f"{wlabel}/{MODEL_LABELS[mdl]}: {exc}")
                    continue
                rows.append((wlabel, y_name, mdl, r4, r6, r12))
    return rows, notes


def _t2_table(rows) -> pd.DataFrame:
    recs = []
    for wlabel, y_name, mdl, r4, r6, r12 in rows:
        rec = {"window": wlabel, "y": y_name, "model": MODEL_LABELS[mdl], "n": r4["n"],
               "alpha (ann %)": f"{r4['alpha_ann'] * 100:.2f}", "t (L=4)": f"{r4['t_alpha']:.2f}",
               "t (L=6)": f"{r6['t_alpha']:.2f}", "t (L=12)": f"{r12['t_alpha']:.2f}"}
        for fac in FACTOR_ORDER:
            rec[fac] = (f"{r4['loadings'][fac]:.2f} ({r4['t_loadings'][fac]:.1f})" if fac in r4["loadings"] else "")
        rec["R2"] = f"{r4['r2']:.2f}"
        rec["adj R2"] = f"{r4['adj_r2']:.2f}"
        recs.append(rec)
    return pd.DataFrame(recs)


# ----------------------------------------------------------------------------------------------
# T7 short horizon
# ----------------------------------------------------------------------------------------------
def _t7(bun: _Bundle, windows: dict, horizons: Sequence[int], B: int, seed: int, prim_only_windows: Sequence[str]):
    rows, store = [], {}
    prim = bun.primary
    for bench in bun.bench_names:
        for wl, win in windows.items():
            if bench != prim and wl != next(iter(windows)):
                continue                                           # other benchmarks: first window only
            d = pd.concat([bun.daily("Strategy (net)", win), bun.daily(bench, win)], axis=1).dropna()
            for h in horizons:
                if len(d) < h + 5:
                    continue
                r = metrics.horizon_report(d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy(), h, B=B, seed=seed)
                store[(bench, wl, h)] = r
                q = r["excess_quantiles"]
                rows.append({"vs": bench, "window": wl, "horizon": {13: "13d"}.get(h, f"{h}d"), "windows": r["n_windows"],
                             "indep.": f"{r['n_independent']:.0f}", "mean excess": _f(r["mean_excess"], "pct2"),
                             "5%": _f(q[5], "pct2"), "25%": _f(q[25], "pct2"), "median": _f(q[50], "pct2"),
                             "75%": _f(q[75], "pct2"), "95%": _f(q[95], "pct2"), "worst": _f(r["worst_excess"], "pct2"),
                             "P(beat)": f"{r['p_beat'] * 100:.1f}% [{r['p_beat_ci'][0] * 100:.0f}-{r['p_beat_ci'][1] * 100:.0f}]",
                             "P(loss)": f"{r['p_loss'] * 100:.1f}%", "P(beat by >2pt)": f"{r['p_beat_margin'] * 100:.1f}%"})
    return pd.DataFrame(rows), store


def _forward_table(ir_bt: float, horizons: Sequence[int]) -> pd.DataFrame:
    """P(beat) = Phi(IR * sqrt(h/252)) for the backtest IR and McLean-Pontiff style haircuts (research/06 sections 1.3, 7.2)."""
    recs = []
    for lab, ir in [("IR = 0 (no skill)", 0.0), ("backtest IR, no haircut", ir_bt),
                    ("haircut 26% (data-mining only)", ir_bt * (1 - 0.26)), ("haircut 58% (post-publication)", ir_bt * (1 - 0.58))]:
        rec = {"scenario": lab, "IR": f"{ir:.2f}"}
        for h in horizons:
            rec[f"{h}d"] = "–" if not np.isfinite(ir) else f"{norm.cdf(ir * np.sqrt(h / 252.0)) * 100:.1f}%"
        recs.append(rec)
    return pd.DataFrame(recs).set_index("scenario")


# ----------------------------------------------------------------------------------------------
# charts
# ----------------------------------------------------------------------------------------------
def _colors(bun: _Bundle) -> dict:
    c = {"Strategy (net)": SERIES[0], "Strategy (gross)": "#86b6ef"}
    for i, b in enumerate(bun.bench_names):
        c[b] = SERIES[1 + i % (len(SERIES) - 1)]
    return c


def _linestyle(col: str) -> str:
    return {"Strategy (net)": "-", "Strategy (gross)": "--"}.get(col, "-")


def _shade(ax, windows: dict, bun: _Bundle, with_labels: bool = True):
    for key, tint in (("train", TRAIN_TINT), ("test", TEST_TINT)):
        for lab, win in windows.items():
            if lab.strip().lower() == key:
                s = _to_ts(win[0]) or bun.first
                e = _to_ts(win[1], end=True) or bun.last
                s, e = max(pd.Timestamp(s), bun.first), min(pd.Timestamp(e), bun.last)
                if e > s:
                    ax.axvspan(s, e, color=tint, alpha=0.45, lw=0, zorder=0)
                    if with_labels:
                        ax.text(s + (e - s) * 0.02, 0.97, lab.title(), transform=ax.get_xaxis_transform(), va="top",
                                ha="left", fontsize=8, color=INK2)


def _c1_growth(bun, windows, name, path):
    col = _colors(bun)
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(10, 5.2))
        _shade(ax, windows, bun)
        for c in bun.cols:
            r = bun.D[c]
            first = r.first_valid_index()
            if first is None:
                continue
            w = (1 + r.fillna(0.0)).cumprod()
            w = w / w.loc[first] if first != r.index[0] else w
            w[w.index < first] = np.nan
            ax.plot(w.index, w.values, color=col[c], ls=_linestyle(c), lw=2.2 if c == "Strategy (net)" else 1.4,
                    label=c, zorder=3 if c == "Strategy (net)" else 2)
        ax.set_yscale("log")
        ax.yaxis.set_major_locator(LogLocator(base=10, subs=(1.0, 1.5, 2.0, 3.0, 5.0, 7.0), numticks=20))
        ax.yaxis.set_major_formatter(FuncFormatter(lambda v, _: f"${v:,.0f}" if v >= 10 else f"${v:,.2g}"))
        ax.yaxis.set_minor_locator(NullLocator())
        _style_ax(ax, f"{name}: growth of $1 (net of costs, log scale)", None, "Portfolio value")
        ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.9), ncol=1)
        _save(fig, path)
    return path


def _c2_underwater(bun, windows, name, path):
    col = _colors(bun)
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(10, 4.2))
        _shade(ax, windows, bun, with_labels=False)
        for c in ["Strategy (net)", bun.primary]:
            r = bun.D[c].dropna()
            dd = pd.Series(metrics.drawdown_series(r), index=r.index)
            if c == "Strategy (net)":
                ax.fill_between(dd.index, dd.values, 0, color=col[c], alpha=0.35, lw=0)
            ax.plot(dd.index, dd.values, color=col[c], lw=1.5 if c == "Strategy (net)" else 1.3, label=c)
        _pct_axis(ax)
        _style_ax(ax, f"{name}: underwater (daily drawdown from prior peak)", None, "Drawdown")
        ax.legend(loc="lower left")
        _save(fig, path)
    return path


def _c3_rolling(bun, name, path):
    col = _colors(bun)
    prim = bun.primary
    pair = pd.concat([bun.Mo["Strategy (net)"], bun.Mo[prim]], axis=1, keys=["r", "b"]).dropna()
    with plt.rc_context(RC):
        fig, (a1, a2) = plt.subplots(2, 1, figsize=(10, 6.4), sharex=True, gridspec_kw={"height_ratios": [1.2, 1]})
        if len(pair) >= 13:
            ex = pd.Series(metrics.rolling_compound(pair["r"].to_numpy(), 12) - metrics.rolling_compound(pair["b"].to_numpy(), 12),
                           index=pair.index[11:]).copy()
            x = ex.index
            a1.fill_between(x, ex.values, 0, where=ex.values >= 0, color=col["Strategy (net)"], alpha=0.35, lw=0, interpolate=True)
            a1.fill_between(x, ex.values, 0, where=ex.values < 0, color=SERIES[7], alpha=0.35, lw=0, interpolate=True)
            a1.plot(x, ex.values, color=col["Strategy (net)"], lw=1.5, label=f"12m excess vs {prim}")
            a1.axhline(0, color=INK2, lw=0.8)
            a1.legend(loc="upper left")
        _pct_axis(a1)
        _style_ax(a1, f"{name}: rolling 12-month excess return vs {prim} (net)", None, "Excess return")
        if len(pair) >= 37:
            act = pair["r"] - pair["b"]
            ir = act.rolling(36).mean() / act.rolling(36).std() * np.sqrt(12)
            x = ir.index
            a2.plot(x, ir.values, color=SERIES[6], lw=1.5, label=f"36m information ratio vs {prim}")
            a2.axhline(0, color=INK2, lw=0.8)
            a2.legend(loc="upper left")
        _style_ax(a2, f"Rolling 36-month information ratio vs {prim}", "Date", "IR (annualised)")
        _save(fig, path)
    return path


def _calendar_returns(r: pd.Series) -> pd.DataFrame:
    d = r.dropna()
    lg = np.log1p(d.clip(lower=-1 + 1e-12))
    ret = np.expm1(lg.groupby(d.index.year).sum())
    cnt = d.groupby(d.index.year).size()
    return pd.DataFrame({"ret": ret, "n": cnt})


def _c4_calendar(bun, name, path):
    col = _colors(bun)
    prim = bun.primary
    a = _calendar_returns(bun.D["Strategy (net)"])
    b = _calendar_returns(bun.D[prim].reindex(bun.D["Strategy (net)"].dropna().index))
    yrs = a.index
    x = np.arange(len(yrs))
    w = 0.38
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(max(8, 0.65 * len(yrs) + 3), 4.8))
        ax.bar(x - w / 2, a["ret"].values, w, color=col["Strategy (net)"], label="Strategy (net)")
        ax.bar(x + w / 2, b["ret"].reindex(yrs).values, w, color=col[prim], label=prim)
        for xi, v in zip(x - w / 2, a["ret"].values):
            ax.text(xi, v + (0.006 if v >= 0 else -0.006), f"{v * 100:.0f}", ha="center", va="bottom" if v >= 0 else "top",
                    fontsize=7, color=INK2)
        partial = [(y, n) for y, n in a["n"].items() if n < 200]
        ax.set_xticks(x)
        ax.set_xticklabels([f"{y}*" if n < 200 else str(y) for y, n in a["n"].items()], rotation=0)
        ax.axhline(0, color=INK2, lw=0.8)
        _pct_axis(ax)
        ttl = f"{name}: calendar-year returns, net (labels = strategy %)"
        _style_ax(ax, ttl, None, "Return")
        if partial:
            ax.text(0.99, 0.02, "* partial year", transform=ax.transAxes, ha="right", fontsize=8, color=INK2)
        ax.legend(loc="upper left")
        ax.grid(axis="x", visible=False)
        _save(fig, path)
    return path


def _c5_hist(bun, store, horizons, window_label, name, path):
    prim = bun.primary
    present = [h for h in horizons if (prim, window_label, h) in store]
    if not present:
        return None
    win = None
    d = pd.concat([bun.D["Strategy (net)"], bun.D[prim]], axis=1).dropna()
    with plt.rc_context(RC):
        fig, axes = plt.subplots(1, len(present), figsize=(5.2 * len(present), 4.4), squeeze=False, layout="constrained")
        for ax, h in zip(axes[0], present):
            rep = store[(prim, window_label, h)]
            e = metrics.rolling_compound(d.iloc[:, 0].to_numpy(), h) - metrics.rolling_compound(d.iloc[:, 1].to_numpy(), h)
            lo, hi = np.percentile(e, [0.5, 99.5])
            bins = np.linspace(lo, hi, 41)
            ax.hist(e[(e >= lo) & (e <= hi)], bins=bins, color=SERIES[0], alpha=0.75, lw=0)
            ax.axvline(0, color=INK, lw=1.2)
            ax.axvline(rep["excess_quantiles"][50], color=SERIES[1], lw=1.4, ls="--", label=f"median {rep['excess_quantiles'][50] * 100:.2f}%")
            ax.axvspan(rep["excess_quantiles"][5], rep["excess_quantiles"][95], color=SERIES[1], alpha=0.08, lw=0,
                       label="5th-95th pct")
            ax.xaxis.set_major_formatter(PercentFormatter(1.0, decimals=1 if h <= 20 else 0))
            ax.xaxis.set_major_locator(MaxNLocator(6))
            lbl = {13: "13 trading days", 63: "63 days (~3 months)", 126: "126 days (~6 months)"}.get(h, f"{h} days")
            _style_ax(ax, f"Rolling {lbl}", f"Excess return vs {prim}", "Number of windows")
            ax.text(0.98, 0.97, f"P(beat) = {rep['p_beat'] * 100:.1f}%\n95% CI [{rep['p_beat_ci'][0] * 100:.0f}, {rep['p_beat_ci'][1] * 100:.0f}]\n"
                                f"P(loss) = {rep['p_loss'] * 100:.1f}%\nn = {rep['n_windows']:,} overlapping",
                    transform=ax.transAxes, ha="right", va="top", fontsize=9, color=INK,
                    bbox=dict(boxstyle="round,pad=0.35", fc=SURFACE, ec=GRIDC, alpha=0.92))
            ax.legend(loc="upper left", fontsize=8)
            ax.margins(y=0.30)
        fig.suptitle(f"{name}: rolling excess-return distributions vs {prim} ({window_label} window, net)", x=0.01, ha="left",
                     fontsize=12, fontweight="bold")
        _save(fig, path)
    return path


def _c8_loadings(rows, name, path):
    pick = [r for r in rows if r[2] == "ff5mom" and r[1].startswith("excess")]
    if not pick:
        return None
    wlabel, _y, _m, r4, _r6, _r12 = pick[0]
    facs = list(r4["loadings"])
    beta = np.array([r4["loadings"][f] for f in facs])
    se = np.array([r4["se_loadings"][f] for f in facs])
    with plt.rc_context(RC):
        fig, ax = plt.subplots(figsize=(8, 4.2))
        x = np.arange(len(facs))
        ax.bar(x, beta, color=SERIES[0], alpha=0.85)
        ax.errorbar(x, beta, yerr=1.96 * se, fmt="none", ecolor=INK, capsize=4, lw=1.2)
        ax.axhline(0, color=INK2, lw=0.8)
        ax.set_xticks(x)
        ax.set_xticklabels(facs)
        _style_ax(ax, f"{name}: FF5+MOM loadings, {wlabel}", None, "Loading")
        ax.text(0.99, 0.97, f"bars = beta, whiskers = HAC 95% CI\nalpha = {r4['alpha_ann'] * 100:.2f}%/yr (t = {r4['t_alpha']:.2f}, L = {r4['lags']})\nR2 = {r4['r2']:.2f}, n = {r4['n']}",
                transform=ax.transAxes, ha="right", va="top", fontsize=9)
        ax.grid(axis="x", visible=False)
        _save(fig, path)
    return path


# ----------------------------------------------------------------------------------------------
# tearsheet
# ----------------------------------------------------------------------------------------------
def _fmt_header_value(v) -> str:
    if isinstance(v, Mapping):
        return "; ".join(f"{k}={_fmt_header_value(x)}" for k, x in v.items())
    if isinstance(v, (list, tuple, set)):
        return ", ".join(_fmt_header_value(x) for x in v)
    if isinstance(v, float):
        return f"{v:g}"
    return str(v)


def tearsheet(name: str, strat_daily_net: pd.Series, strat_daily_gross: pd.Series | None,
              benchmarks: dict[str, pd.Series], rf: pd.Series | None, factors_monthly: pd.DataFrame | None,
              windows: dict, out_dir: str | Path, header: dict, turnover: pd.Series | None = None,
              holdings: pd.Series | None = None, *, primary: str | None = None, horizons: Sequence[int] = (13, 63, 126),
              horizon_windows: Sequence[str] | None = None, factor_windows: Sequence[str] | None = None,
              n_boot: int = 500, horizon_B: int = 500, seed: int = 0, extra_sections: Mapping[str, str] | None = None,
              return_all: bool = False) -> Path | list[Path]:
    """Write the tear sheet (markdown + PNGs + CSV tables) for one strategy into ``out_dir``.

    Parameters
    ----------
    strat_daily_net / strat_daily_gross : daily simple returns (decimals); gross may be None.
    benchmarks : name -> daily returns, e.g. {'SPY': ..., 'RSP': ..., 'EW-universe': ...}; the first one named
        ``primary`` (default 'SPY' or else the first) is the reference for beta / TE / IR / hit rates / P(beat).
    rf : daily risk-free return (decimal per day) or None.
    factors_monthly : French factors in decimals (columns Mkt-RF, SMB, HML, RMW, CMA, Mom; common aliases are accepted).
    windows : label -> (start, end) with None = open; labels 'Train' / 'Test' are shaded in C1 and C2.
    header : ordered items printed at the top (universe, params, costs, survivorship, trials, ...).
    turnover : daily ONE-WAY turnover; holdings : daily number of holdings.
    extra_sections : title -> markdown appended before the footer (e.g. T3 overfitting table, T4 parameter table).
    """
    if not benchmarks:
        raise ValueError("at least one benchmark is required")
    out_dir = Path(out_dir)
    out_dir.mkdir(parents=True, exist_ok=True)
    slug = _slug(name)
    primary = primary or ("SPY" if "SPY" in benchmarks else next(iter(benchmarks)))
    if primary not in benchmarks:
        raise ValueError(f"primary benchmark {primary!r} not in benchmarks")
    bun = _Bundle(strat_daily_net, strat_daily_gross, benchmarks, rf, primary)
    windows = dict(windows) if windows else {"Full": (None, None)}
    written: list[Path] = []
    md: list[str] = []

    def png(tag: str) -> Path:
        return out_dir / f"{slug}_{tag}.png"

    # ---- header -------------------------------------------------------------------------------
    md.append(f"# {name}: tear sheet\n")
    hdr = dict(header or {})
    if not any(k.lower().startswith("surviv") for k in hdr):
        hdr["survivorship"] = "NOT STATED: add the coverage ratio / audit result (research/06 section 6)"
    rows = [("Generated", datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")),
            ("Data", f"{bun.first:%Y-%m-%d} to {bun.last:%Y-%m-%d} ({int(bun.D['Strategy (net)'].notna().sum()):,} trading days)"),
            ("Benchmarks", ", ".join(benchmarks) + f" (reference: {primary})")]
    rows += [(str(k), _fmt_header_value(v)) for k, v in hdr.items()]
    md.append(_md_table(pd.DataFrame(rows, columns=["item", "value"]).set_index("item"), index=True, index_name="item"))
    md.append("")

    # ---- T1 -----------------------------------------------------------------------------------
    md.append("## T1 Performance, net of costs\n")
    md.append(f"Monthly statistics from calendar-month compounded daily returns (partial leading/trailing months dropped); "
              f"MaxDD is daily. Benchmark-relative rows are vs {primary}; Sharpe CI = stationary bootstrap (mean block 6, B={n_boot}).\n")
    t1_long = []
    for wl, win in windows.items():
        try:
            raw = _t1_window(bun, win, n_boot, seed, turnover, holdings)
        except Exception as exc:  # a short window must not kill the whole sheet
            log.warning("T1 window %s failed: %s", wl, exc)
            md.append(f"### {wl}\n\n(not computable: {exc})\n")
            continue
        fm = _fmt_t1(raw.dropna(how="all"))
        md.append(f"### {_wlabel(wl, win, bun.first, bun.last)}\n")
        md.append(_md_table(fm, index_name="metric"))
        md.append("")
        long = fm.copy()
        long.insert(0, "window", wl)
        t1_long.append(long)
    if t1_long:
        p = out_dir / f"{slug}_T1_performance.csv"
        pd.concat(t1_long).to_csv(p, index_label="metric")
        written.append(p)

    # ---- T2 -----------------------------------------------------------------------------------
    F = _canon_factors(factors_monthly)
    md.append("## T2 Factor regressions (monthly, Newey-West HAC)\n")
    if F is None:
        md.append("No factor data supplied; T2 skipped.\n")
        t2_rows = []
    else:
        fw_labels = list(factor_windows) if factor_windows else [k for k in windows if k.lower() in ("full", "train", "test")] or list(windows)[:1]
        fw = {k: windows[k] for k in fw_labels if k in windows}
        t2_rows, t2_notes = _t2_rows(bun, F, fw)
        if t2_rows:
            t2 = _t2_table(t2_rows)
            md.append("alpha is annualised (12 x monthly intercept); loadings show beta (HAC t, L=4). "
                      "t at L=6 / L=12 are robustness checks; excess = strategy minus rf, active = strategy minus the reference benchmark.\n")
            md.append(_md_table(t2, index=False))
            md.append("")
            p = out_dir / f"{slug}_T2_factor_regressions.csv"
            t2.to_csv(p, index=False)
            written.append(p)
        for n in t2_notes:
            md.append(f"- note: {n}")
        md.append("")

    # ---- T7 -----------------------------------------------------------------------------------
    md.append("## T7 Short-horizon behaviour (rolling windows from the backtest)\n")
    hw_labels = list(horizon_windows) if horizon_windows else [k for k in windows if k.lower() in ("full", "test")] or list(windows)[:1]
    hw = {k: windows[k] for k in hw_labels if k in windows}
    t7, store = _t7(bun, hw, horizons, horizon_B, seed, hw_labels)
    if len(t7):
        md.append("Overlapping compounded windows on daily net returns; excess = strategy minus benchmark. Effective independent windows "
                  "(`indep.`) are about n/h, so the binomial uncertainty of P(beat) is large; the bracket is a stationary-bootstrap 95% CI.\n")
        md.append(_md_table(t7, index=False))
        md.append("")
        p = out_dir / f"{slug}_T7_short_horizon.csv"
        t7.to_csv(p, index=False)
        written.append(p)
        full_label = hw_labels[0]
        ir_bt = np.nan
        pair = pd.concat([bun.Mo["Strategy (net)"], bun.Mo[primary]], axis=1).dropna()
        if len(pair) > 12:
            ir_bt = metrics.information_ratio(pair.iloc[:, 0], pair.iloc[:, 1], 12)
        fwd = _forward_table(ir_bt, horizons)
        md.append(f"### Forward expectation: P(beat {primary}) = Phi(IR x sqrt(h/252))\n")
        md.append(f"Backtest IR (full sample, monthly) = {_f(ir_bt)}. Haircuts follow McLean & Pontiff (2016): a self-tuned strategy can "
                  f"decay by more than their 26% data-mining cap, so treat these as optimistic.\n")
        md.append(_md_table(fwd, index_name="scenario"))
        md.append("")
    else:
        md.append("Not enough data for the requested horizons.\n")

    # ---- charts -------------------------------------------------------------------------------
    md.append("## Charts\n")
    charts = []
    charts.append(("C1 Growth of $1", _c1_growth(bun, windows, name, png("C1_growth"))))
    charts.append(("C2 Underwater", _c2_underwater(bun, windows, name, png("C2_underwater"))))
    charts.append(("C3 Rolling excess and IR", _c3_rolling(bun, name, png("C3_rolling"))))
    charts.append(("C4 Calendar-year returns", _c4_calendar(bun, name, png("C4_calendar"))))
    if len(t7):
        charts.append(("C5 Rolling-horizon excess-return histograms", _c5_hist(bun, store, horizons, hw_labels[0], name, png("C5_horizons"))))
    if t2_rows:
        charts.append(("C8 Factor loadings", _c8_loadings(t2_rows, name, png("C8_loadings"))))
    for title, p in charts:
        if p is not None:
            written.append(p)
            md.append(f"### {title}\n\n![{title}]({p.name})\n")

    # ---- extra sections + footer ----------------------------------------------------------------
    for title, body in (extra_sections or {}).items():
        md.append(f"## {title}\n\n{body}\n")
    md.append("## Assumptions and limitations\n")
    md.append("- Returns are net of the stated trading costs (per side, on traded notional); signals at the close of day t, trades at the close of t+1; "
              "point-in-time rule: filings usable only if filed strictly before the signal date.\n"
              "- Survivorship, XBRL tag mapping and a short test window limit what can be concluded; see the header and the coverage audit.\n"
              "- Sharpe ratios are annualised from monthly data with sqrt(12), exact only for iid returns; HAC t-statistics over-reject in short samples.\n"
              "- Expected decay: published anomalies lose roughly a quarter to a half of their returns out of sample and after publication "
              "(McLean & Pontiff 2016, Journal of Finance 71(1)); parameters were fixed on the train window with a pre-registered plateau rule and "
              "confirmed once on the test window, so the live result should be expected to be smaller than the backtest.\n")
    mdp = out_dir / f"{slug}_tearsheet.md"
    mdp.write_text("\n".join(md) + "\n")
    written.insert(0, mdp)
    return written if return_all else mdp


# ----------------------------------------------------------------------------------------------
# C6 grid figures
# ----------------------------------------------------------------------------------------------
_METRIC_LABEL = {"sharpe": "Net Sharpe (annualised)", "cagr": "Net CAGR", "vol": "Annualised volatility",
                 "maxdd": "Max drawdown (monthly)", "tstat": "t-stat of mean excess return"}
_METRIC_PCT = {"cagr", "vol", "maxdd"}


def _levels_of(gr, name: str) -> list:
    if name in gr.axes:
        return list(gr.axes[name])
    if name in gr.categorical:
        return list(gr.categorical[name])
    vals = list(pd.unique(gr.params[name]))
    try:
        return sorted(vals)
    except TypeError:
        return vals


def _is_selected(cell: dict | None, params: dict) -> bool:
    if cell is None:
        return False
    return all(k in cell and _same_level(cell[k], v) for k, v in params.items())


def _resolve_marker(gr, x) -> dict | None:
    if x is None:
        return None
    if isinstance(x, dict) and "chosen" in x:
        return dict(x["chosen"])
    if isinstance(x, dict):
        return dict(x)
    if isinstance(x, str):
        return dict(gr.cells[gr.cell_ids.index(x)])
    raise TypeError("selected/default must be a params dict, a cell id or a select() result")


def _fmt_level(v) -> str:
    return f"{v:g}" if isinstance(v, (int, float, np.floating)) and not isinstance(v, bool) else str(v)


def _norm_for(vmin: float, vmax: float):
    if vmin < 0 < vmax:
        return TwoSlopeNorm(vmin=vmin, vcenter=0.0, vmax=vmax), DIV_CMAP
    if vmax <= 0:
        return Normalize(vmin=vmin, vmax=min(vmax, 0.0) if vmax > vmin else vmin + 1e-9), DIV_CMAP
    return Normalize(vmin=min(vmin, vmax - 1e-9), vmax=vmax), SEQ_CMAP


def _draw_heatmap(ax, Z, xl, yl, norm_, cmap, fmt, sel_rc, dflt_rc, plateau_thr, x_name, y_name, title):
    ny, nx = Z.shape
    im = ax.imshow(np.ma.masked_invalid(Z), origin="lower", cmap=cmap, norm=norm_, aspect="auto")
    for i in range(ny):
        for j in range(nx):
            v = Z[i, j]
            if not np.isfinite(v):
                ax.text(j, i, "–", ha="center", va="center", color=INK2)
                continue
            rgba = cmap(norm_(v))
            lum = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
            ax.text(j, i, fmt(v), ha="center", va="center", fontsize=11, fontweight="bold" if (i, j) == sel_rc else "normal",
                    color="#ffffff" if lum < 0.5 else INK)
            if plateau_thr is not None and v >= plateau_thr:
                ax.add_patch(plt.Rectangle((j - 0.5, i - 0.5), 1, 1, fill=False, ec=INK, lw=1.6, ls="--"))
    if dflt_rc is not None:
        ax.plot(dflt_rc[1], dflt_rc[0] + 0.30, marker="D", ms=9, mfc="white", mec=INK, mew=1.4, ls="none")
    if sel_rc is not None:
        ax.plot(sel_rc[1], sel_rc[0] - 0.28, marker="*", ms=17, mfc=SERIES[3], mec=INK, mew=1.0, ls="none")
    ax.set_xticks(range(nx))
    ax.set_xticklabels(xl)
    ax.set_yticks(range(ny))
    ax.set_yticklabels(yl)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_xlabel(x_name)
    ax.set_ylabel(y_name)
    ax.set_title(title, loc="left", fontsize=10.5)
    return im


def grid_figures(grid_result, window, x_axis: str, y_axis: str, facet_axes: Sequence[str] = (), out_dir: str | Path | None = None,
                 *, metric: str = "sharpe", selected=None, default=None, smoothing: float = 0.5, label: str | None = None,
                 surface: bool = True, plateau_frac: float = 0.9) -> list[Path]:
    """C6: heatmaps (primary) and 3D interpolated surfaces (secondary) of ``metric`` over two ordinal axes.

    One heatmap PNG and one surface PNG per combination of ``facet_axes`` levels, plus an overview heatmap with every
    facet and a shared colour scale. Parameters that are neither x, y nor facet are held at the default cell's level.
    ``selected`` (a ``select()`` result / params dict / cell id) defaults to ``grid_result.last_selection``; ``default``
    defaults to ``grid_result.default``. Selected = star, default = diamond, plateau region (metric >= 0.9 x selected)
    = dashed outline. Surfaces are labelled "interpolated; grid points marked": the heatmap shows the real numbers.
    """
    gr = grid_result
    out_dir = Path(out_dir) if out_dir is not None else (gr.out_dir or Path("."))
    out_dir.mkdir(parents=True, exist_ok=True)
    mt = gr.metrics(window)
    if metric not in mt.columns:
        raise ValueError(f"metric must be one of {list(mt.columns)}")
    vals = mt[metric].reindex(gr.cell_ids).to_numpy(float)
    P = gr.params
    for k in (x_axis, y_axis, *facet_axes):
        if k not in P.columns:
            raise KeyError(f"unknown parameter {k!r}; have {list(P.columns)}")
    if x_axis == y_axis or {x_axis, y_axis} & set(facet_axes):
        raise ValueError("x_axis, y_axis and facet_axes must be distinct")
    sel = _resolve_marker(gr, selected if selected is not None else gr.last_selection)
    dflt = _resolve_marker(gr, default if default is not None else (gr.default or (gr.last_selection or {}).get("default")))
    xl, yl = _levels_of(gr, x_axis), _levels_of(gr, y_axis)
    others = [c for c in P.columns if c not in (x_axis, y_axis, *facet_axes) and c in (list(gr.axes) + list(gr.categorical))]
    fixed = {}
    for c in others:
        lv = _levels_of(gr, c)
        if dflt is not None and c in dflt:
            fixed[c] = dflt[c]
        else:
            fixed[c] = lv[0]
    facet_levels = [_levels_of(gr, c) for c in facet_axes]
    finite = vals[np.isfinite(vals)]
    if finite.size == 0:
        raise ValueError("no finite metric values in this window")
    norm_, cmap = _norm_for(float(finite.min()), float(finite.max()))
    pct = metric in _METRIC_PCT
    fmt = (lambda v: f"{v * 100:.1f}%") if pct else (lambda v: f"{v:.2f}")
    mlabel = _METRIC_LABEL.get(metric, metric)
    wlab = label or _window_label(window)
    prefix = _slug(f"{gr.strategy}_{label or ('window_' + _slug(wlab))}")
    held = ", ".join(f"{k}={_fmt_level(v)}" for k, v in fixed.items())
    sel_thr = None
    if sel is not None:
        sid = gr.resolve(sel)
        sv = float(vals[gr.cell_ids.index(sid)])
        if np.isfinite(sv) and sv > 0:
            sel_thr = plateau_frac * sv

    def slice_for(combo):
        """Z[y, x] for one facet combination, plus (row, col) of selected and default if on this slice."""
        want = dict(zip(facet_axes, combo))
        want.update(fixed)
        Z = np.full((len(yl), len(xl)), np.nan)
        for pos, row in enumerate(gr.cells):
            if not all(_same_level(row[k], v) for k, v in want.items()):
                continue
            try:
                Z[_level_index(yl, row[y_axis]), _level_index(xl, row[x_axis])] = vals[pos]
            except KeyError:
                continue
        def rc(cell):
            if cell is None or not all(k in cell and _same_level(cell[k], v) for k, v in want.items()):
                return None
            try:
                return _level_index(yl, cell[y_axis]), _level_index(xl, cell[x_axis])
            except KeyError:
                return None
        return Z, rc(sel), rc(dflt)

    combos = list(itertools.product(*facet_levels)) if facet_axes else [()]
    xlab, ylab = [_fmt_level(v) for v in xl], [_fmt_level(v) for v in yl]
    written: list[Path] = []

    def ftitle(combo):
        tag = ", ".join(f"{k}={_fmt_level(v)}" for k, v in zip(facet_axes, combo))
        return tag

    # per-facet heatmaps ------------------------------------------------------------------------------
    for combo in combos:
        Z, sel_rc, dflt_rc = slice_for(combo)
        tag = _slug("_".join(f"{k}_{_fmt_level(v)}" for k, v in zip(facet_axes, combo))) if combo else "all"
        with plt.rc_context(RC):
            fig, ax = plt.subplots(figsize=(1.3 * len(xl) + 3.2, 1.0 * len(yl) + 3.0))
            ttl = f"{gr.strategy}: {mlabel}, {wlab}" + (f"\n{ftitle(combo)}" if combo else "")
            im = _draw_heatmap(ax, Z, xlab, ylab, norm_, cmap, fmt, sel_rc, dflt_rc, sel_thr if sel_rc is not None else None,
                               x_axis, y_axis, ttl)
            cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
            cb.set_label(mlabel)
            if pct:
                cb.formatter = PercentFormatter(1.0)
                cb.update_ticks()
            handles = [Line2D([], [], marker="*", ls="none", mfc=SERIES[3], mec=INK, ms=13, label="selected (plateau rule)"),
                       Line2D([], [], marker="D", ls="none", mfc="white", mec=INK, ms=8, label="literature default"),
                       Line2D([], [], marker="s", ls="none", mfc="none", mec=INK, ms=9, label=f"plateau: >= {plateau_frac:.0%} of selected")]
            ax.legend(handles=handles, loc="upper center", bbox_to_anchor=(0.5, -0.18), ncol=1, fontsize=8)
            if held:
                ax.text(0.0, -0.13 - 0.0, f"held at: {held}", transform=ax.transAxes, fontsize=8, color=INK2, va="top")
            fig.tight_layout()
            written.append(_save(fig, out_dir / f"{prefix}_C6_heatmap_{tag}.png"))

    # overview with every facet ----------------------------------------------------------------------
    if len(combos) > 1:
        ncol = min(len(combos), max(len(facet_levels[-1]), 1) if facet_levels else 1, 4) or 1
        nrow = int(np.ceil(len(combos) / ncol))
        with plt.rc_context(RC):
            fig, axes = plt.subplots(nrow, ncol, figsize=(3.6 * ncol + 1.6, 3.4 * nrow + 1.0), squeeze=False, layout="constrained")
            im = None
            for ax, combo in zip(axes.ravel(), combos):
                Z, sel_rc, dflt_rc = slice_for(combo)
                im = _draw_heatmap(ax, Z, xlab, ylab, norm_, cmap, fmt, sel_rc, dflt_rc, sel_thr if sel_rc is not None else None,
                                   x_axis, y_axis, ftitle(combo))
            for ax in axes.ravel()[len(combos):]:
                ax.set_visible(False)
            cb = fig.colorbar(im, ax=axes.ravel().tolist(), fraction=0.03, pad=0.02)
            cb.set_label(mlabel)
            if pct:
                cb.formatter = PercentFormatter(1.0)
                cb.update_ticks()
            fig.suptitle(f"{gr.strategy}: {mlabel}, {wlab}  (star = selected, diamond = default"
                         + (f"; held at {held}" if held else "") + ")", x=0.01, ha="left", fontsize=11, fontweight="bold")
            written.append(_save(fig, out_dir / f"{prefix}_C6_heatmap_overview.png"))

    # 3D surfaces -------------------------------------------------------------------------------------
    if surface:
        zlo, zhi = float(finite.min()), float(finite.max())
        pad = 0.05 * (zhi - zlo if zhi > zlo else 1.0)
        for combo in combos:
            Z, sel_rc, dflt_rc = slice_for(combo)
            ii, jj = np.where(np.isfinite(Z))
            tag = _slug("_".join(f"{k}_{_fmt_level(v)}" for k, v in zip(facet_axes, combo))) if combo else "all"
            if len(ii) < 4 or len(set(ii)) < 2 or len(set(jj)) < 2:
                log.warning("surface skipped for %s: too few grid points", tag)
                continue
            try:
                gx, gy, gz = stats.surface_grid(jj.astype(float), ii.astype(float), Z[ii, jj], n=40, smoothing=smoothing)
            except (ValueError, Exception) as exc:  # degenerate geometry -> no surface, heatmap still exists
                log.warning("surface skipped for %s: %s", tag, exc)
                continue
            with plt.rc_context(RC):
                fig = plt.figure(figsize=(8.2, 6.4))
                ax = fig.add_subplot(projection="3d")
                ax.set_facecolor(SURFACE)
                ax.plot_surface(gx, gy, np.ma.masked_invalid(gz), cmap=cmap, norm=norm_, alpha=0.85, linewidth=0, antialiased=True,
                                rstride=1, cstride=1)
                zpts = Z[ii, jj]
                gi = np.clip(np.rint(jj / max(len(xl) - 1, 1) * (gx.shape[1] - 1)).astype(int), 0, gx.shape[1] - 1)
                gj = np.clip(np.rint(ii / max(len(yl) - 1, 1) * (gy.shape[0] - 1)).astype(int), 0, gy.shape[0] - 1)
                zsurf = gz[gj, gi]
                for xj, yi, zp, zs in zip(jj, ii, zpts, zsurf):
                    if np.isfinite(zs):
                        ax.plot([xj, xj], [yi, yi], [zp, zs], color=INK2, lw=0.8, alpha=0.8)
                ax.scatter(jj, ii, zpts, color="black", s=26, depthshade=False, label="grid point", zorder=5)
                lift = 0.03 * (zhi - zlo if zhi > zlo else 1.0)
                if sel_rc is not None:
                    ax.scatter([sel_rc[1]], [sel_rc[0]], [Z[sel_rc] + lift], marker="*", s=260, color=SERIES[3], edgecolor=INK,
                               depthshade=False, label="selected", zorder=6)
                if dflt_rc is not None:
                    ax.scatter([dflt_rc[1]], [dflt_rc[0]], [Z[dflt_rc] + lift], marker="D", s=70, color="white", edgecolor=INK,
                               depthshade=False, label="literature default", zorder=6)
                if sel_rc is not None and sel_thr is not None:
                    try:
                        with warnings.catch_warnings():
                            warnings.simplefilter("ignore")
                            ax.contour(gx, gy, np.ma.masked_invalid(gz), levels=[sel_thr], zdir="z", offset=zlo - pad,
                                       colors=[INK], linestyles="--", linewidths=1.4)
                    except Exception:  # pragma: no cover - contour level outside the surface range
                        pass
                ax.set_zlim(zlo - pad, zhi + pad)
                ax.set_xticks(range(len(xl)))
                ax.set_xticklabels(xlab)
                ax.set_yticks(range(len(yl)))
                ax.set_yticklabels(ylab)
                ax.set_xlabel(x_axis, labelpad=8)
                ax.set_ylabel(y_axis, labelpad=8)
                ax.set_zlabel(mlabel, labelpad=6)
                if pct:
                    ax.zaxis.set_major_formatter(PercentFormatter(1.0))
                ax.view_init(elev=26, azim=-58)
                ax.set_title(f"{gr.strategy}: {mlabel}, {wlab}" + (f"\n{ftitle(combo)}" if combo else "")
                             + "\ninterpolated; grid points marked", loc="left", fontsize=10.5)
                ax.legend(loc="upper left", bbox_to_anchor=(0.0, 0.95), fontsize=8)
                written.append(_save(fig, out_dir / f"{prefix}_C6_surface_{tag}.png"))
    return written


# ----------------------------------------------------------------------------------------------
# C7 PBO
# ----------------------------------------------------------------------------------------------
def pbo_figure(pbo_result: dict, out_dir: str | Path, name: str = "C7_pbo") -> list[Path]:
    """C7: histogram of CSCV logits (PBO = mass at or below 0) and IS vs OOS Sharpe of the selected trial with the
    degradation line. ``pbo_result`` is ``GridResult.pbo()`` or the raw ``stats.cscv_pbo`` dict."""
    out_dir = Path(out_dir)
    lam = np.asarray(pbo_result["logits"], float)
    is_ann = pbo_result.get("sr_is_ann")
    oos_ann = pbo_result.get("sr_oos_ann")
    per_period = is_ann is None
    x = np.asarray(pbo_result["sr_is"] if per_period else is_ann, float)
    y = np.asarray(pbo_result["sr_oos"] if per_period else oos_ann, float)
    ok = np.isfinite(x) & np.isfinite(y)
    pbo = float(pbo_result["pbo"])
    sel = pbo_result.get("selector", "argmax")
    with plt.rc_context(RC):
        fig, (a1, a2) = plt.subplots(1, 2, figsize=(12, 4.6))
        finite = lam[np.isfinite(lam)]
        bins = np.linspace(finite.min() - 1e-9, finite.max() + 1e-9, 31) if finite.size and finite.max() > finite.min() else 20
        a1.hist(finite, bins=bins, color=SERIES[0], alpha=0.8, lw=0)
        a1.axvline(0, color=INK, lw=1.4)
        a1.axvspan(min(finite.min(), 0) - 0.5 if finite.size else -1, 0, color=SERIES[7], alpha=0.12, lw=0)
        _style_ax(a1, "Logit of the OOS rank of the in-sample pick", "logit  (< 0: in-sample winner is below the OOS median)",
                  "Number of IS/OOS splits")
        a1.text(0.03, 0.95, f"PBO = {pbo * 100:.1f}%\n({len(lam):,} splits, selector: {sel})", transform=a1.transAxes, ha="left",
                va="top", fontsize=10, color=INK, bbox=dict(boxstyle="round,pad=0.35", fc=SURFACE, ec=GRIDC, alpha=0.92))
        n_ok = int(ok.sum())
        a2.scatter(x[ok], y[ok], s=7 if n_ok > 2000 else 22, alpha=float(np.clip(400 / max(n_ok, 1), 0.15, 0.8)),
                   color=SERIES[0], lw=0, rasterized=True, label=f"{n_ok:,} IS/OOS splits")
        if ok.sum() > 2 and np.std(x[ok]) > 0:
            slope, icpt = np.polyfit(x[ok], y[ok], 1)
            xs = np.linspace(x[ok].min(), x[ok].max(), 50)
            a2.plot(xs, slope * xs + icpt, color=SERIES[1], lw=2.0, label=f"OOS = {icpt:.2f} {slope:+.2f} x IS")
        lo = float(min(x[ok].min(), y[ok].min())) if ok.any() else -1
        hi = float(max(x[ok].max(), y[ok].max())) if ok.any() else 1
        a2.plot([lo, hi], [lo, hi], color=INK2, lw=1.0, ls="--", label="no degradation (OOS = IS)")
        a2.axhline(0, color=INK2, lw=0.8)
        a2.axvline(0, color=INK2, lw=0.8)
        unit = "per-period" if per_period else "annualised"
        _style_ax(a2, "Selected trial: in-sample vs out-of-sample Sharpe", f"In-sample Sharpe ({unit})", f"Out-of-sample Sharpe ({unit})")
        pl = pbo_result.get("prob_loss")
        if pl is not None:
            a2.text(0.97, 0.05, f"P(OOS Sharpe < 0) = {float(pl) * 100:.1f}%", transform=a2.transAxes, fontsize=9, ha="right",
                    bbox=dict(boxstyle="round,pad=0.3", fc=SURFACE, ec=GRIDC, alpha=0.92))
        a2.legend(loc="upper right", fontsize=8, frameon=True, facecolor=SURFACE, edgecolor=GRIDC, framealpha=0.92)
        fig.suptitle("Probability of backtest overfitting (CSCV)", x=0.01, ha="left", fontsize=12, fontweight="bold")
        fig.tight_layout()
        return [_save(fig, out_dir / f"{name}.png")]


# ----------------------------------------------------------------------------------------------
# C10 correlation
# ----------------------------------------------------------------------------------------------
def _corr_ax(ax, C: pd.DataFrame, title: str):
    n = len(C)
    im = ax.imshow(C.to_numpy(), cmap=DIV_CMAP, norm=TwoSlopeNorm(vmin=-1, vcenter=0, vmax=1), aspect="equal")
    for i in range(n):
        for j in range(n):
            v = C.iloc[i, j]
            rgba = DIV_CMAP(TwoSlopeNorm(vmin=-1, vcenter=0, vmax=1)(v))
            lum = 0.299 * rgba[0] + 0.587 * rgba[1] + 0.114 * rgba[2]
            ax.text(j, i, f"{v:.2f}", ha="center", va="center", fontsize=11, color="#ffffff" if lum < 0.45 else INK)
    ax.set_xticks(range(n))
    ax.set_xticklabels(C.columns, rotation=30, ha="right")
    ax.set_yticks(range(n))
    ax.set_yticklabels(C.index)
    ax.grid(False)
    for sp in ax.spines.values():
        sp.set_visible(False)
    ax.set_title(title, loc="left", fontsize=10.5)
    return im


def correlation_figure(series: Mapping[str, pd.Series], out_dir: str | Path, benchmark: str | None = "SPY",
                       window=None, name: str = "C10_correlation") -> list[Path]:
    """C10: correlation heatmaps of monthly returns and of active returns vs ``benchmark`` (if it is a key of ``series``
    and at least two other series exist). Series are inner-joined on their month."""
    if len(series) < 2:
        raise ValueError("need at least two series")
    out_dir = Path(out_dir)
    cols = {}
    for k, s in series.items():
        s = pd.Series(s).astype(float)
        idx = pd.DatetimeIndex(s.index)
        s = s.copy()
        s.index = idx.to_period("M")
        cols[k] = s[~s.index.duplicated(keep="last")]
    df = pd.DataFrame(cols).dropna()
    df.index = df.index.to_timestamp(how="end").normalize()
    df = df[_mask_periods(df.index, window)]
    if len(df) < 6:
        raise ValueError(f"only {len(df)} common months")
    panels = [("Monthly returns", df.corr())]
    if benchmark in df.columns and df.shape[1] >= 3:
        act = df.drop(columns=[benchmark]).sub(df[benchmark], axis=0)
        panels.append((f"Active returns vs {benchmark}", act.corr()))
    with plt.rc_context(RC):
        fig, axes = plt.subplots(1, len(panels), figsize=(5.6 * len(panels) + 0.8, 5.2), squeeze=False, layout="constrained")
        im = None
        for ax, (ttl, C) in zip(axes[0], panels):
            im = _corr_ax(ax, C, ttl)
        cb = fig.colorbar(im, ax=axes.ravel().tolist(), fraction=0.03, pad=0.03)
        cb.set_label("Correlation")
        fig.suptitle(f"Correlation of strategy returns ({len(df)} common months, {df.index[0]:%Y-%m} to {df.index[-1]:%Y-%m})",
                     x=0.01, ha="left", fontsize=12, fontweight="bold")
        return [_save(fig, out_dir / f"{name}.png")]


# ----------------------------------------------------------------------------------------------
# markdown fragments for tearsheet(extra_sections=...): T3 overfitting, T4 parameter regression + selection
# ----------------------------------------------------------------------------------------------
def _params_str(p: Mapping) -> str:
    return ", ".join(f"{k}={_fmt_level(v)}" for k, v in p.items())


def selection_markdown(sel: dict, conf: dict | None = None) -> str:
    """Markdown for a ``GridResult.select()`` result (and, optionally, its ``confirm()`` result): chosen cell, reasons,
    neighbourhood table, per-category table, stability, and the test-window comparison (research/06 T4)."""
    out = [f"- chosen: **{_params_str(sel['chosen'])}** ({'literature default' if sel['is_default'] else 'plateau_v1 choice'}"
           f"{'; FALLBACK: ' + sel['fallback_reason'] if sel.get('fallback') else ''})",
           f"- default: {_params_str(sel['default'])} (train Sharpe {_f(sel['default_sharpe'])})",
           f"- train Sharpe of chosen {_f(sel['sharpe'])}; plateau score {_f(sel['score'], 'num3')}; peak ratio {_f(sel['peak_ratio'])}; "
           f"plateau width {sel['plateau_width']} cells (>= 90% of chosen)"]
    st = sel.get("stability")
    if st:
        out.append(f"- bootstrap stability (B={st['B']}, mean block {st['mean_block']:g}): {st['share_exact'] * 100:.0f}% select exactly this cell, "
                   f"{st['share_within_one'] * 100:.0f}% within one grid step -> {'pass' if st['passed'] else 'FAIL'}")
    v = sel.get("variants", {})
    if v:
        out.append("- sensitivity (not used for selection): " + "; ".join(
            f"{k} -> {d['cell_id']} (Sharpe {_f(d['sharpe'])}, {'within' if d['within_one_step'] else 'MORE THAN'} one step)" for k, d in v.items()))
    out.append("")
    out.append("Reasons:\n" + "\n".join(f"- {r}" for r in sel["reasons"]))
    nb = sel["neighborhood"].copy()
    nb["sharpe"] = nb["sharpe"].map(lambda x: _f(x))
    out.append("\nNeighbourhood of the chosen cell (train):\n\n" + _md_table(nb.drop(columns=["cell_id"]), index=False))
    pc = sel["per_category"].copy()
    for c in ("score", "peak_ratio", "sharpe"):
        pc[c] = pc[c].map(lambda x: _f(x))
    out.append("\nPlateau result per categorical level:\n\n" + _md_table(pc.drop(columns=["best_cell_id"], errors="ignore"), index=False))
    if conf is not None:
        t = conf["table"].copy().astype(object)
        for ix in t.index:
            t.loc[ix] = [_f(t.loc[ix, "sharpe"]), _f(t.loc[ix, "cagr"], "pct"), _f(t.loc[ix, "vol"], "pct"), _f(t.loc[ix, "maxdd"], "pct"),
                         _f(t.loc[ix, "tstat"]), _f(t.loc[ix, "n_months"], "int")]
        crit = conf["criteria"]
        out.append(f"\nConfirmation on the untouched test window {conf['test'][0]} to {conf['test'][1]}:\n\n" + _md_table(t, index_name="cell"))
        out.append(f"\n- chosen minus default Sharpe: {_f(conf['chosen_minus_default_sharpe'])}; chosen minus grid median: {_f(conf['chosen_minus_median_sharpe'])}; "
                   f"rank percentile among cells: {_f(conf['chosen_rank_pct'], 'pct0')}\n"
                   f"- Spearman(train Sharpe, test Sharpe) across cells: {_f(conf.get('spearman_train_test', np.nan))}; "
                   f"test/train Sharpe of the chosen cell: {_f(conf.get('test_over_train_sharpe', np.nan))}\n"
                   f"- criteria: " + ", ".join(f"{k}={'yes' if v else 'NO'}" for k, v in crit.items()))
        for n in conf.get("notes", []):
            out.append(f"- WARNING: {n}")
    return "\n".join(out)


def overfitting_markdown(dsr_res: dict, pbo_res: dict | None = None) -> str:
    """T3 overfitting diagnostics from ``GridResult.dsr()`` (and optionally ``GridResult.pbo()``)."""
    d = dsr_res
    t = d["t_stat"]
    rows = [("Months / window", f"{d['n_months']} / {d['window']}"),
            ("Trials N (ledger, distinct configurations)", f"{d['N_ledger']}"),
            ("Cells in grid / effective trials N_hat", f"{d['N_cells']} / {_f(d['N_eff'])}"),
            ("Net Sharpe (annualised)", _f(d["sr_ann"])),
            ("t-stat of mean excess return", f"{_f(t)}  (vs 2.0: {'pass' if t > 2 else 'fail'}; 3.0: {'pass' if t > 3 else 'fail'}; 3.39: {'pass' if t > 3.39 else 'fail'})"),
            ("PSR(0)", _f(d.get("psr0", np.nan), "num3")),
            ("Expected max Sharpe SR0 of N null trials (annualised)", _f(d["sr0_ann"])),
            (f"DSR at N = {d['N_used']} (ledger)", _f(d["dsr"], "num3")),
            (f"DSR at N_hat = {_f(d['N_eff'])}", _f(d["dsr_neff"], "num3")),
            (f"DSR at N = {d['N_cells']} (grid cells)", _f(d["dsr_ncells"], "num3")),
            ("Bonferroni haircut Sharpe (annualised) / haircut", f"{_f(d.get('haircut_sharpe', np.nan))} / {_f(d.get('haircut', np.nan), 'pct0')}"),
            ("Minimum track record for PSR(0) >= 95% (years)", _f(d.get("min_trl_years", np.nan), "num2"))]
    if pbo_res is not None:
        rows += [(f"PBO (CSCV, S={pbo_res['S']}, selector: {pbo_res['selector']})", f"{_f(pbo_res['pbo'], 'pct')}  ({pbo_res['n_combos']:,} splits)"),
                 ("P(OOS Sharpe < 0) of the selected trial", _f(pbo_res["prob_loss"], "pct")),
                 ("Degradation slope (OOS on IS Sharpe; negative = overfit)", _f(pbo_res["degradation_slope"]))]
    df = pd.DataFrame(rows, columns=["diagnostic", "value"]).set_index("diagnostic")
    return _md_table(df, index_name="diagnostic")


def regression_markdown(tab: pd.DataFrame) -> str:
    """T4 parameter regression table (``GridResult.regression_table()``): coefficient, bootstrap SD and ratio."""
    df = pd.DataFrame({"coef": tab["coef"].map(lambda x: f"{x:.3f}"), "bootstrap SD": tab["boot_sd"].map(lambda x: f"{x:.3f}"),
                       "coef / SD": tab["t_boot"].map(lambda x: f"{x:.1f}")}, index=tab.index)
    head = (f"Response: net Sharpe of each of {tab.attrs.get('n_cells', len(tab))} grid cells on {tab.attrs.get('window', '')}; ordinal parameters scaled to "
            f"[-1, 1]; R2 = {tab.attrs.get('r2', float('nan')):.2f}. Bootstrap SDs resample months jointly across cells (B={tab.attrs.get('B', '?')}); "
            f"cells overlap, so OLS p-values would be meaningless. A flat surface (small coefficients, low R2) is good news.\n\n")
    return head + _md_table(df, index_name="term")
