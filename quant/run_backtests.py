"""End-to-end backtest runner for the three strategies (quality momentum, Magic Formula, trading comps).

    .venv/bin/python -m quant.run_backtests [--strategy qm|mf|tc|all] [--no-live]

Per strategy (research/06 sections 5-8):
  1. verify ``output/<strategy>/preregistration.json`` against the module GRID (never re-registers);
  2. ``grid.run_grid`` over the whole pre-registered grid, monthly NET returns, full period, serial (n_jobs=1);
  3. ``select()`` on TRAIN only (plateau rule), ONE ``confirm()`` on TEST for the chosen cell; no re-selection;
  4. PBO (CSCV, S=16, train), DSR (ledger N), grid regression table, heat-map / surface / PBO figures;
  5. full-period backtests for the chosen and the literature-default parameters, benchmarks (SPY, RSP and the
     same-universe equal-weight benchmark), tear sheets, robustness trials (every run is a ledger trial);
  6. evidence ladder (7 criteria, section 5.7), short-horizon P(beat) (13 / 63 / 126 trading days);
  7. live picks for the chosen and default parameters at the latest trading day in the data.
Then the equal-weight blend of the three chosen strategies, ``output/survivorship.md`` and ``output/summary.json``.

Windows: TRAIN = strategy start .. 2018-12-31, TEST = 2019-01-01 .. 2026-09-30 (last complete month).
Nothing here edits another module; if a strategy module is wrong the runner reports it instead of patching it.

Other options
  --live-only            only recompute the live picks from the parameters stored in output/summary.json
  --reuse-grid           reload the grid's monthly returns from output/<strategy>/grid_monthly_returns.csv
                         instead of recomputing (development only; the ledger is not re-written)
  --blend                recompute the blend from the saved daily series (automatic with --strategy all)
  --blend-only           only the blend (+ survivorship), from the daily series saved by earlier runs
  --no-forward-pe        skip the yfinance forwardPE information column of the comps live table (network, ~2 min)
  --note TEXT            recorded in output/<strategy>/changelog.md (every run appends an entry comparing with the previous run)
  --live-max-age-days N  relax the fundamentals-staleness limit of the live screens for QM and MF (their
                         live_picks do not expose max_age_days; QM's quality table and MF's
                         SNAPSHOT_MAX_AGE_DAYS are overridden at run time only, nothing on disk changes)
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import math
import sys
import time
import traceback
from contextlib import contextmanager
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd

from quant import settings
from quant.backtest import grid, metrics, report, stats
from quant.data import factors as factors_mod
from quant.data import universe as universe_mod
from quant.data.context import get_context
from quant.strategies import magic_formula as mf
from quant.strategies import quality_momentum as qm
from quant.strategies import trading_comps as tc

LOGGER_NAME = "quant.run_backtests"
log = logging.getLogger(LOGGER_NAME)

ROOT = settings.ROOT
OUT = Path(settings.OUTPUT)
TRAIN_END = pd.Timestamp(settings.TRAIN_END)
TEST_START = pd.Timestamp(settings.TEST_START)
DEFAULT_END = pd.Timestamp("2026-09-30")          # last complete month
BASE_COST = 10.0
HORIZONS = (13, 63, 126)
SURV_START = "2011-01-01"
SUBPERIODS = {"2011-14": ("2011-01-01", "2014-12-31"), "2015-18": ("2015-01-01", "2018-12-31"),
              "2019-22": ("2019-01-01", "2022-12-31"), "2023-26": ("2023-01-01", "2026-12-31")}
EW_NAME = "EW-SP900"


# ======================================================================================================
# logging / small utilities
# ======================================================================================================
class _Dedupe(logging.Filter):
    """Keep the log file readable: a message from a library logger is written at most ``limit`` times."""

    def __init__(self, limit: int = 5):
        super().__init__()
        self.limit, self.counts = limit, {}

    def filter(self, rec: logging.LogRecord) -> bool:
        if rec.name == LOGGER_NAME or rec.levelno >= logging.ERROR:
            return True
        key = (rec.name, rec.getMessage()[:160])
        self.counts[key] = n = self.counts.get(key, 0) + 1
        return n <= self.limit


class _RunnerOnly(logging.Filter):
    def filter(self, rec: logging.LogRecord) -> bool:
        return rec.name == LOGGER_NAME or rec.levelno >= logging.ERROR


def setup_logging() -> None:
    OUT.mkdir(parents=True, exist_ok=True)
    fmt = logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s", "%H:%M:%S")
    fh = logging.FileHandler(OUT / "run_backtests.log", mode="a")
    fh.setFormatter(fmt)
    fh.setLevel(logging.INFO)
    fh.addFilter(_Dedupe())
    ch = logging.StreamHandler(sys.stdout)
    ch.setFormatter(fmt)
    ch.setLevel(logging.INFO)
    ch.addFilter(_RunnerOnly())
    root = logging.getLogger()
    root.handlers = [fh, ch]
    root.setLevel(logging.WARNING)
    log.setLevel(logging.INFO)


class Timer:
    def __init__(self):
        self.t = {}

    @contextmanager
    def __call__(self, name: str):
        t0 = time.time()
        try:
            yield
        finally:
            self.t[name] = round(time.time() - t0, 1)
            log.info("[time] %s: %.1fs", name, self.t[name])


def jsonable(o):
    """Recursively convert numpy / pandas / NaN to strict-JSON friendly objects."""
    if o is None or isinstance(o, str):
        return o
    if isinstance(o, (bool, np.bool_)):
        return bool(o)
    if isinstance(o, (int, np.integer)):
        return int(o)
    if isinstance(o, (float, np.floating)):
        return float(o) if math.isfinite(float(o)) else None
    if isinstance(o, (pd.Timestamp, datetime)):
        return None if pd.isna(o) else pd.Timestamp(o).isoformat()
    if isinstance(o, pd.Period):
        return str(o)
    if isinstance(o, dict):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, (list, tuple, set)):
        return [jsonable(v) for v in o]
    if isinstance(o, np.ndarray):
        return [jsonable(v) for v in o.tolist()]
    if isinstance(o, pd.Series):
        return {str(k): jsonable(v) for k, v in o.items()}
    if isinstance(o, pd.DataFrame):
        return [jsonable(r) for r in o.reset_index().to_dict("records")]
    if o is pd.NaT:
        return None
    return str(o)


def write_json(path: Path, obj) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(json.dumps(jsonable(obj), indent=2, allow_nan=False) + "\n")
    tmp.replace(path)


def fnum(x, kind: str = "num2") -> str:
    if x is None or (isinstance(x, (float, np.floating)) and not np.isfinite(x)):
        return "–"
    if isinstance(x, str):
        return x
    return {"pct": f"{x * 100:.1f}%", "pct2": f"{x * 100:.2f}%", "pct0": f"{x * 100:.0f}%", "num3": f"{x:.3f}",
            "int": f"{int(x)}", "bps": f"{x * 1e4:.0f}"}.get(kind, f"{x:.2f}")


def md_table(rows: list[dict], cols: list[str] | None = None) -> str:
    if not rows:
        return "(none)"
    cols = cols or list(rows[0])
    lines = ["| " + " | ".join(cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in rows:
        lines.append("| " + " | ".join(str(r.get(c, "")).replace("|", "/") for c in cols) + " |")
    return "\n".join(lines)


def params_str(p: dict) -> str:
    return ", ".join(f"{k}={(f'{v:g}' if isinstance(v, (int, float)) and not isinstance(v, bool) else v)}"
                     for k, v in p.items())


def git_head() -> str:
    """Commit hash read from .git without running git (best effort)."""
    try:
        g = ROOT / ".git"
        head = (g / "HEAD").read_text().strip()
        if head.startswith("ref:"):
            ref = head.split(" ", 1)[1]
            p = g / ref
            if p.exists():
                return p.read_text().strip()[:10]
            for line in (g / "packed-refs").read_text().splitlines():
                if line.strip().endswith(ref):
                    return line.split()[0][:10]
        return head[:10]
    except Exception:  # noqa: BLE001
        return "unknown"


# ======================================================================================================
# strategy specifications
# ======================================================================================================
@dataclass
class Spec:
    key: str
    name: str                                    # name used in the preregistration / ledger / output folder
    title: str
    short: str                                   # tear-sheet name (also the file-name stem)
    module: object
    excluded: tuple                              # GICS sectors excluded by the strategy (also from its EW benchmark)
    universe_note: str
    start_fn: Callable                           # ctx -> first signal month-end
    grid_fn: Callable                            # (ctx, start, end) -> fn(cell) -> monthly net returns
    backtest_fn: Callable                        # (ctx, params, start, end, cost_bps|None) -> BacktestResult
    fig: dict                                    # x / y / facets for grid_figures
    expected_factors: tuple                      # (factor, sign) pairs the strategy is meant to load on (ladder #4)
    robust_fn: Callable                          # chosen params -> list of (name, params, cost_bps|None, kind)
    live_fn: Callable                            # (ctx, params, asof, forward_pe) -> DataFrame
    picks_fn: Callable                           # live DataFrame -> DataFrame[ticker, weight, rank]
    cost_names: dict = field(default_factory=dict)   # {25: robustness name, ...} used by the ladder


def _qm_robust(chosen: dict) -> list:
    out = [("cost 0 bps", chosen, 0.0, "cost"), ("cost 25 bps", chosen, 25.0, "cost"), ("cost 50 bps", chosen, 50.0, "cost"),
           ("quality arm Q4-0.25 (blend)", {**chosen, "quality": "Q4-0.25"}, BASE_COST, "variant"),
           ("quality arm Q4-0.5 (blend)", {**chosen, "quality": "Q4-0.5"}, BASE_COST, "variant"),
           ("order QF (quality first)", {**chosen, "order": "QF"}, BASE_COST, "variant"),
           ("trend_exit_daily (sell below SMA200 daily)", {**chosen, "trend_exit_daily": True}, BASE_COST, "variant")]
    return out


def _mf_robust(chosen: dict) -> list:
    abl = mf.ablation_params(chosen)
    out = [("cost 0 bps", {**chosen, "cost_bps": 0.0}, None, "cost")]
    for nm, p in abl.items():
        out.append((f"ablation {nm}", p, None, "cost" if nm.startswith("cost_") else "variant"))
    return out


def _tc_robust(chosen: dict) -> list:
    return [("cost 0 bps", chosen, 0.0, "cost"), ("cost 25 bps", chosen, 25.0, "cost"), ("cost 50 bps", chosen, 50.0, "cost"),
            ("basis LFY (last fiscal year)", {**chosen, "basis": "LFY"}, BASE_COST, "variant")]


def _qm_picks(df: pd.DataFrame) -> pd.DataFrame:
    s = df[df["selected"]].sort_values("rank")
    w = s["weight_after_vol"] if "weight_after_vol" in s.columns else s["weight"]
    return pd.DataFrame({"ticker": s["ticker"].to_numpy(), "weight": w.to_numpy(), "rank": s["rank"].to_numpy()})


def _mf_picks(df: pd.DataFrame) -> pd.DataFrame:
    s = df[df["pick"] == "PICK"].sort_values("final_rank")
    n = max(len(s), 1)
    return pd.DataFrame({"ticker": s["yf_ticker"].to_numpy(), "weight": 1.0 / n, "rank": s["final_rank"].to_numpy()})


def _tc_picks(df: pd.DataFrame) -> pd.DataFrame:
    if not len(df) or "status" not in df.columns:
        return pd.DataFrame({"ticker": [], "weight": [], "rank": []})
    s = df[(df["status"] == "BUY") & df["selected"]].sort_values("rank")
    return pd.DataFrame({"ticker": s["ticker"].to_numpy(), "weight": s["weight"].to_numpy(), "rank": s["rank"].to_numpy()})


def _budgeted_forward_fetch(budget_s: float = 300.0):
    """yfinance forwardPE lookups for the comps live table (information only), stopped after ``budget_s`` seconds."""
    def fetch(tickers):
        t0, out = time.time(), {}
        tickers = list(tickers)
        for i in range(0, len(tickers), 25):
            if time.time() - t0 > budget_s:
                log.warning("forward P/E: time budget (%.0fs) used up after %d of %d tickers; the rest are blank", budget_s, i, len(tickers))
                break
            out.update(tc._yf_forward_pe(tickers[i:i + 25], retries=1, pause=1.0))
        log.info("forward P/E fetched for %d tickers in %.0fs", len(out), time.time() - t0)
        return out
    return fetch


SPECS: dict[str, Spec] = {
    "qm": Spec(
        key="qm", name=qm.STRATEGY, title="Quality-filtered momentum", short="Quality momentum", module=qm,
        excluded=("Financials", "Real Estate"),
        universe_note="point-in-time S&P 900 (S&P 500 + MidCap 400) ex GICS Financials and Real Estate, raw price >= $5",
        start_fn=lambda ctx: qm.first_signal_date(ctx),
        grid_fn=lambda ctx, start, end: (lambda cell: qm.monthly_returns(cell, ctx=ctx, start=start, end=end)),
        backtest_fn=lambda ctx, p, start, end, cost: qm.backtest(ctx, p, start, end, cost_bps=BASE_COST if cost is None else cost,
                                                                  store_weights=False),
        fig=dict(x="N", y="stop_loss", facets=("technical", "vol_target", "quality")),
        expected_factors=(("Mom", 1), ("RMW", 1)),
        robust_fn=_qm_robust,
        live_fn=lambda ctx, p, asof, fwd: qm.live_picks(ctx, p, asof),
        picks_fn=_qm_picks, cost_names={25: "cost 25 bps"}),
    "mf": Spec(
        key="mf", name=mf.STRATEGY, title="Magic Formula", short="Magic formula", module=mf,
        excluded=tuple(mf.EXCLUDED_SECTORS),
        universe_note="point-in-time S&P 900 (S&P 500 + MidCap 400) ex GICS Financials, Real Estate and Utilities, raw price >= $5",
        start_fn=lambda ctx: mf.common_start(ctx),
        grid_fn=lambda ctx, start, end: mf.make_grid_fn(ctx, start=start, end=end),
        backtest_fn=lambda ctx, p, start, end, cost: mf.backtest(ctx, p, start, end, cost_bps=cost, store_weights=False),
        fig=dict(x="n", y="min_cap", facets=("holding",)),
        expected_factors=(("HML", 1), ("RMW", 1)),
        robust_fn=_mf_robust,
        live_fn=lambda ctx, p, asof, fwd: mf.live_picks(ctx, p, asof),
        picks_fn=_mf_picks, cost_names={25: "ablation cost_25bps"}),
    "tc": Spec(
        key="tc", name=tc.STRATEGY, title="Trading comps", short="Trading comps", module=tc,
        excluded=tuple(tc.C.EXCLUDED_SECTORS),
        universe_note="point-in-time S&P 900 (S&P 500 + MidCap 400) ex GICS Financials and Real Estate, mcap >= $300M, raw price >= $5",
        start_fn=lambda ctx: pd.Timestamp(tc.TRAIN_START),
        grid_fn=lambda ctx, start, end: (lambda cell: tc.monthly_returns(cell, ctx=ctx, start=start, end=end)),
        backtest_fn=lambda ctx, p, start, end, cost: tc.backtest(ctx, p, start=start, end=end,
                                                                  cost_bps=BASE_COST if cost is None else cost, store_weights=False),
        fig=dict(x="pe_cap", y="ev_cap", facets=("theta", "size_filter")),
        expected_factors=(("HML", 1),),
        robust_fn=_tc_robust,
        live_fn=lambda ctx, p, asof, fwd: tc.live_picks(ctx, p, asof, forward_check=fwd,
                                                         fetch_forward=_budgeted_forward_fetch() if fwd else None),
        picks_fn=_tc_picks, cost_names={25: "cost 25 bps"}),
}
KEYS = {"qm": "qm", "mf": "mf", "tc": "tc", "quality_momentum": "qm", "magic_formula": "mf", "trading_comps": "tc"}


class PreregMismatch(RuntimeError):
    pass


def verify_prereg(spec: Spec) -> dict:
    """The registration on disk must equal the module's GRID / axes / categorical / default. Never re-registers."""
    reg = grid.load_preregistration(spec.name)
    if reg is None:
        raise PreregMismatch(f"{spec.name}: output/{spec.name}/preregistration.json does not exist")
    mod = spec.module
    problems = []
    if grid.grid_hash(mod.GRID) != reg["grid_hash"]:
        problems.append(f"grid hash {grid.grid_hash(mod.GRID)} != registered {reg['grid_hash']}")
    if len(mod.GRID) != reg["n_cells"]:
        problems.append(f"{len(mod.GRID)} cells in the module vs {reg['n_cells']} registered")
    core = grid._core_content(mod.GRID, mod.AXES, mod.CATEGORICAL, mod.DEFAULT, reg["primary_metric"])
    chash = hashlib.sha256(grid._canon(core).encode()).hexdigest()[:16]
    if chash != reg["content_hash"]:
        problems.append(f"content hash (grid+axes+categorical+default+metric) {chash} != registered {reg['content_hash']}")
    if problems:
        raise PreregMismatch(f"{spec.name}: " + "; ".join(problems))
    return reg


# ======================================================================================================
# performance numbers
# ======================================================================================================
def monthly_rf(ctx) -> pd.Series:
    rf = ctx.rf
    out = (1.0 + rf).groupby(rf.index.to_period("M")).prod() - 1.0
    out.index = out.index.to_timestamp(how="end").normalize()
    return out


def to_m(daily: pd.Series) -> pd.Series:
    """Calendar-month compounded returns, month-end labels (same routine the tear sheet uses)."""
    return report._monthly(pd.Series(daily).astype(float).dropna())


def _mask(index: pd.DatetimeIndex, window) -> np.ndarray:
    m = np.ones(len(index), dtype=bool)
    if window is None:
        return m
    s, e = window
    if s is not None:
        m &= np.asarray(index >= pd.Timestamp(s))
    if e is not None:
        m &= np.asarray(index <= pd.Timestamp(e))
    return m


def perf_windows(end: pd.Timestamp) -> dict:
    return {"full": (None, None), "train": (None, TRAIN_END), "test": (TEST_START, None),
            "last36": ((end - pd.DateOffset(months=36) + pd.Timedelta(days=1)).normalize(), None)}


def perf_block(r_m: pd.Series, rf_m: pd.Series, window, daily: pd.Series | None = None,
               benches: dict | None = None) -> dict:
    """Net performance of a monthly series over a window (+ daily max drawdown and benchmark-relative numbers)."""
    r = r_m[_mask(r_m.index, window)].dropna()
    out: dict = {"n_months": int(len(r))}
    if len(r) < 3:
        return out
    rf = rf_m.reindex(r.index).fillna(0.0)
    out.update(first=r.index[0], last=r.index[-1], cagr=metrics.cagr(r.to_numpy(), 12), vol=metrics.ann_vol(r.to_numpy(), 12),
               sharpe=metrics.sharpe(r.to_numpy(), rf.to_numpy(), 12), sortino=metrics.sortino(r.to_numpy(), rf.to_numpy(), 12),
               total_return=float(np.prod(1.0 + r.to_numpy()) - 1.0))
    if daily is not None:
        d = daily[_mask(daily.index, window)].dropna()
        out["maxdd_daily"] = metrics.max_drawdown(d.to_numpy()) if len(d) else float("nan")
        mdd = out["maxdd_daily"]
        out["calmar"] = out["cagr"] / abs(mdd) if np.isfinite(mdd) and mdd < 0 else float("nan")
    for k, b in (benches or {}).items():
        bb = b.reindex(r.index)
        out[f"vs_{k}"] = dict(ir=metrics.information_ratio(r.to_numpy(), bb.to_numpy(), 12),
                              active_cagr=metrics.active_cagr(r.to_numpy(), bb.to_numpy(), 12),
                              te=metrics.tracking_error(r.to_numpy(), bb.to_numpy(), 12),
                              beta=metrics.beta(r.to_numpy(), bb.to_numpy(), rf.to_numpy()),
                              hit_rate=metrics.hit_rate(r.to_numpy(), bb.to_numpy()))
    return out


def ff_alpha(r_m: pd.Series, rf_m: pd.Series, F: pd.DataFrame, window=None, model: str = "ff5mom", lags: int = 4) -> dict:
    """Monthly regression of (net return - rf) on French factors with Newey-West HAC errors."""
    r = r_m[_mask(r_m.index, window)].dropna()
    y = (r - rf_m.reindex(r.index).fillna(0.0)).dropna()
    if len(y) < 24:
        return {"n": int(len(y)), "error": "fewer than 24 months"}
    try:
        res = stats.factor_regression(y, F, model=model, lags=lags)
    except (ValueError, KeyError) as exc:
        return {"n": int(len(y)), "error": str(exc)}
    return dict(model=model, n=res["n"], lags=res["lags"], start=res["start"], end=res["end"], alpha_ann=res["alpha_ann"],
                alpha_ann_se=res["alpha_ann_se"], t_alpha=res["t_alpha"], loadings=res["loadings"], t_loadings=res["t_loadings"],
                r2=res["r2"])


def horizon_block(strat_d: pd.Series, bench_d: dict, window, B: int = 1000, hs=HORIZONS) -> dict:
    out: dict = {}
    for bn, b in bench_d.items():
        d = pd.concat([strat_d, b.reindex(strat_d.index)], axis=1).dropna()
        d = d[_mask(d.index, window)]
        for h in hs:
            if len(d) < h + 5:
                continue
            rep = metrics.horizon_report(d.iloc[:, 0].to_numpy(), d.iloc[:, 1].to_numpy(), h, B=B, seed=0)
            out.setdefault(bn, {})[str(h)] = dict(
                n_windows=rep["n_windows"], n_independent=rep["n_independent"], p_beat=rep["p_beat"], p_beat_ci=list(rep["p_beat_ci"]),
                p_loss=rep["p_loss"], p_beat_margin=rep["p_beat_margin"], mean_excess=rep["mean_excess"],
                median_excess=rep["median_excess"], worst_excess=rep["worst_excess"], best_excess=rep["best_excess"],
                excess_quantiles={str(k): v for k, v in rep["excess_quantiles"].items()},
                return_quantiles={str(k): v for k, v in rep["return_quantiles"].items()})
    return out


def turnover_stats(daily: pd.DataFrame) -> dict:
    yrs = max(len(daily) / 252.0, 1e-9)
    return dict(ann_turnover=float(daily["turnover"].fillna(0.0).sum() / yrs), avg_holdings=float(daily["n_holdings"].mean()),
                avg_cash_weight=float(daily["cash_weight"].mean()), cost_drag_bps=float(daily["cost"].sum() / yrs * 1e4))


# ======================================================================================================
# shared inputs (context, factors, benchmarks, survivorship)
# ======================================================================================================
class Shared:
    def __init__(self, end: pd.Timestamp):
        self.end = end
        t0 = time.time()
        self.ctx = get_context()
        self.rf_m = monthly_rf(self.ctx)
        self.rf_d = self.ctx.rf
        try:
            self.F = factors_mod.ff_factors_for_regression("M")
        except Exception as exc:  # noqa: BLE001
            log.error("French factors unavailable (%s); regressions will be skipped", exc)
            self.F = None
        self.spy = self.ctx.returns["SPY"].loc[:end].dropna()
        self.rsp = self.ctx.returns["RSP"].loc[:end].dropna()
        self._surv = None
        log.info("context loaded in %.1fs: prices %s .. %s, factors to %s", time.time() - t0, self.ctx.dates[0].date(),
                 self.ctx.dates[-1].date(), None if self.F is None else self.F.index[-1].date())

    # ---- survivorship ----------------------------------------------------------------------------------
    def survivorship(self) -> dict:
        if self._surv is not None:
            return self._surv
        ctx = self.ctx
        data_end = ctx.dates[-1]
        rows = []
        for d in ctx.month_ends(SURV_START, data_end):
            m = universe_mod.members(d, indexes=("SP500", "SP400"))
            n = len(m)
            tick = m["yf_ticker"].dropna()
            tick = tick[tick.isin(ctx.close.columns)]
            px = ctx.close.loc[d].reindex(tick.to_numpy()).to_numpy(float)
            ok = int(np.sum(np.isfinite(px) & (px > 0)))
            rows.append((d, n, ok))
        m_df = pd.DataFrame(rows, columns=["date", "members", "with_price"]).set_index("date")
        m_df["share"] = m_df["with_price"] / m_df["members"]
        yr = m_df.groupby(m_df.index.year).agg(members=("members", "mean"), with_price=("with_price", "mean"),
                                               share_mean=("share", "mean"), share_min=("share", "min"))
        ew9 = ctx.ew_universe(SURV_START, data_end, "SP900")
        ew5 = ctx.ew_universe(SURV_START, data_end, "SP500")
        rsp = ctx.returns["RSP"]
        series = {"ew900": ew9.daily["ret_net"], "ew500": ew5.daily["ret_net"]}
        idx = series["ew900"].index.intersection(series["ew500"].index).intersection(rsp.dropna().index)
        D = pd.DataFrame({"ew900": series["ew900"].reindex(idx), "ew500": series["ew500"].reindex(idx), "rsp": rsp.reindex(idx)})
        ann = D.groupby(D.index.year).apply(lambda g: np.expm1(np.log1p(g).sum()))
        ann["days"] = D.groupby(D.index.year).size()
        tab = yr.join(ann)
        tab["ew900_minus_rsp"] = tab["ew900"] - tab["rsp"]
        tab["ew500_minus_rsp"] = tab["ew500"] - tab["rsp"]
        full_years = tab[tab["days"] >= 240]
        cagr = {c: metrics.cagr(D[c].to_numpy(), 252) for c in D.columns}
        out = dict(table=tab, monthly=m_df, share_mean=float(m_df["share"].mean()), share_min=float(m_df["share"].min()),
                   gap900_mean=float(full_years["ew900_minus_rsp"].mean()), gap500_mean=float(full_years["ew500_minus_rsp"].mean()),
                   cagr=cagr, gap900_cagr=cagr["ew900"] - cagr["rsp"], gap500_cagr=cagr["ew500"] - cagr["rsp"],
                   first=idx[0], last=idx[-1], data_end=data_end)
        self._surv = out
        return out

    def survivorship_header(self) -> str:
        s = self.survivorship()
        return (f"SURVIVORSHIP-BIASED (yfinance has no delisted names): {s['share_mean']:.1%} of point-in-time S&P 900 members have a "
                f"price history (monthly mean 2011-2026, minimum {s['share_min']:.1%}); EW-SP900 minus RSP = "
                f"{s['gap900_cagr'] * 100:+.1f}%/yr CAGR gap (EW-SP500 minus RSP {s['gap500_cagr'] * 100:+.1f}%/yr, the like-for-like "
                f"bias proxy; the S&P 900 gap also contains the mid-cap premium); see output/survivorship.md")


def write_survivorship(sh: Shared) -> None:
    s = sh.survivorship()
    t = s["table"]
    rows = []
    for y, r in t.iterrows():
        rows.append({"year": f"{y}{'*' if r['days'] < 240 else ''}", "S&P900 members (avg)": f"{r['members']:.0f}",
                     "with prices (avg)": f"{r['with_price']:.0f}", "share with prices": fnum(r["share_mean"], "pct"),
                     "min month": fnum(r["share_min"], "pct"), "EW-SP900": fnum(r["ew900"], "pct"), "EW-SP500": fnum(r["ew500"], "pct"),
                     "RSP": fnum(r["rsp"], "pct"), "EW-SP900 minus RSP": fnum(r["ew900_minus_rsp"], "pct"),
                     "EW-SP500 minus RSP": fnum(r["ew500_minus_rsp"], "pct")})
    txt = [
        "# Survivorship audit (research/06 section 6, S1 and S2)", "",
        f"Generated {datetime.now(timezone.utc):%Y-%m-%d %H:%M UTC}; prices to {s['data_end']:%Y-%m-%d}; data in output/survivorship.csv.", "",
        "## What the numbers are", "",
        "- **share with prices**: members of the point-in-time S&P 500 + MidCap 400 (`universe.members`, one row per company) whose Yahoo "
        "symbol maps to a price series with a positive close on the month-end; averaged over the month-ends of each year. The missing share "
        "is the part of the historical index that the data cannot trade (delisted, acquired, ticker re-use). `ctx.universe` silently drops "
        "these names, so every backtest here is survivorship-biased in the direction of the missing names' (usually poor) returns.",
        "- **EW-SP900 / EW-SP500**: equal-weight, monthly-rebalanced portfolios of all priced members (price >= $5, 10 bps one-way, "
        "`ctx.ew_universe`), i.e. the same data problem as the strategies and no signal. **RSP** is the Invesco S&P 500 equal-weight ETF, "
        "which held the true historical constituents (net of its 0.20% fee).",
        "- **bias proxy** = EW minus RSP. Only the EW-SP500 column is like for like (same index as RSP). EW-SP900 includes the 400 mid caps "
        "and therefore also carries the size premium, so its gap overstates the bias; it is shown because the strategies trade the S&P 900.", "",
        "## By year (`*` = partial year)", "", md_table(rows), "",
        "## Summary", "",
        f"- Mean share of S&P 900 members with prices, monthly 2011-2026: **{s['share_mean']:.1%}** (worst month {s['share_min']:.1%}).",
        f"- Full-sample CAGR: EW-SP900 {fnum(s['cagr']['ew900'], 'pct')}, EW-SP500 {fnum(s['cagr']['ew500'], 'pct')}, RSP {fnum(s['cagr']['rsp'], 'pct')} "
        f"(common days {s['first']:%Y-%m-%d} to {s['last']:%Y-%m-%d}).",
        f"- CAGR gap EW-SP900 minus RSP **{s['gap900_cagr'] * 100:+.2f}%/yr**; EW-SP500 minus RSP **{s['gap500_cagr'] * 100:+.2f}%/yr** "
        f"(add back RSP's 0.20% fee: {(s['gap500_cagr'] - 0.002) * 100:+.2f}%/yr is the survivorship+look-ahead estimate of research/06 S2).",
        f"- Mean of the full-year gaps: SP900 {s['gap900_mean'] * 100:+.2f}%, SP500 {s['gap500_mean'] * 100:+.2f}%.",
        "- Every strategy tear sheet reports `strategy minus EW-universe` (bias-neutral to first order) next to strategy minus SPY / RSP, and "
        "the evidence ladder's criterion 6 asks whether FF5+MOM alpha survives a 150 bps/yr drag.", "",
        "Caveats: RSP rebalances quarterly, the EW portfolios monthly; S&P 400 membership is quarter-end granular (it can lag a mid-quarter "
        "change by up to a quarter, never look ahead); delisted names that DO exist in the price file end without a delisting return.", ""]
    (OUT / "survivorship.md").write_text("\n".join(txt))
    t.reset_index(names="year").to_csv(OUT / "survivorship.csv", index=False)
    s["monthly"].to_csv(OUT / "survivorship_monthly_coverage.csv")


# ======================================================================================================
# per-strategy pipeline
# ======================================================================================================
def analyze(label: str, res, sh: Shared, bench_d: dict, bench_m: dict, wins: dict) -> dict:
    """All headline numbers of one daily backtest result (net)."""
    d = res.daily
    net, gross = d["ret_net"], d["ret_gross"]
    m = to_m(net)
    out = {"label": label, "monthly": m, "metrics": {}, "factor": {}}
    for wn, w in wins.items():
        out["metrics"][wn] = perf_block(m, sh.rf_m, w, net, {k: v for k, v in bench_m.items()})
        if sh.F is not None:
            out["factor"][wn] = ff_alpha(m, sh.rf_m, sh.F, w)
        out["metrics"][wn]["gross_cagr"] = perf_block(to_m(gross), sh.rf_m, w)["cagr"] if out["metrics"][wn]["n_months"] >= 3 else float("nan")
    out["turnover"] = turnover_stats(d)
    return out


def sub_grid_for_figures(gr: grid.GridResult, chosen: dict, default: dict, rf_m: pd.Series) -> grid.GridResult:
    """View of the grid restricted to the chosen and default levels of each categorical axis (facets stay readable)."""
    cat = {}
    for k, lv in gr.categorical.items():
        keep = [v for v in lv if grid._same_level(v, chosen[k]) or grid._same_level(v, default[k])]
        cat[k] = keep
    idx = [i for i, c in enumerate(gr.cells) if all(any(grid._same_level(c[k], v) for v in cat[k]) for k in cat)]
    ids = [gr.cell_ids[i] for i in idx]
    sub = grid.GridResult(gr.strategy, [gr.cells[i] for i in idx], gr.M[ids], rf=rf_m, ledger=None, axes=gr.axes,
                          categorical=cat, default=gr.default, out_dir=gr.out_dir)
    return sub


def run_strategy(spec: Spec, sh: Shared, args, summary: dict) -> dict:
    ctx, end = sh.ctx, sh.end
    T = Timer()
    odir = OUT / spec.name
    odir.mkdir(parents=True, exist_ok=True)
    reg = verify_prereg(spec)
    led = grid.Ledger()
    mod = spec.module
    prev = (load_summary().get("strategies") or {}).get(spec.name) or {}
    log.info("=== %s: %d cells, preregistered %s ===", spec.name, reg["n_cells"], reg["timestamp"])

    with T("start_date"):
        start = pd.Timestamp(spec.start_fn(ctx))
    log.info("%s: start (first signal month-end) %s, end %s", spec.name, start.date(), end.date())

    # ---- 2. grid ------------------------------------------------------------------------------------
    cells = mod.GRID
    grid_csv = odir / "grid_monthly_returns.csv"
    with T("grid"):
        if args.reuse_grid and grid_csv.exists():
            M = pd.read_csv(grid_csv, index_col=0, parse_dates=True)
            ids = [grid.cell_id(c) for c in cells]
            if list(M.columns) != ids:
                raise RuntimeError("--reuse-grid: cached grid does not match the module GRID")
            gr = grid.GridResult(spec.name, cells, M, rf=sh.rf_m, ledger=led, axes=reg["axes"], categorical=reg["categorical"],
                                 default=reg["default"], out_dir=odir)
            log.info("%s: grid reloaded from %s (no new ledger rows)", spec.name, grid_csv.name)
        else:
            fn = spec.grid_fn(ctx, start, end)
            gr = grid.run_grid(spec.name, cells, fn, n_jobs=1, rf=sh.rf_m, ledger=led, axes=reg["axes"],
                               categorical=reg["categorical"], default=reg["default"], out_dir=odir, check_prereg=True,
                               on_error="raise", notes="grid (run_backtests)" + (f": {args.note}" if args.note else ""))
    M = gr.M
    first_m, last_m = M.index[0], M.index[-1]
    log.info("%s: grid months %s .. %s (%d), errors=%d", spec.name, first_m.date(), last_m.date(), len(M), len(gr.errors))
    train = (first_m, TRAIN_END)
    test = (TEST_START.strftime("%Y-%m-%d"), end.strftime("%Y-%m-%d"))

    # ---- 3. select on TRAIN, ONE confirm on TEST -------------------------------------------------------
    with T("select_confirm"):
        sel = gr.select(train, axes=mod.AXES, categorical=mod.CATEGORICAL, default=mod.DEFAULT, lam=reg["lam"],
                        tie_tol=reg["tie_tol"], stability_B=reg["stability"]["B"], peak_ratio_max=reg["peak_ratio_max"],
                        cat_margin=reg["cat_margin"], min_share_within_one=reg["stability"]["min_share_within_one_step"])
        chosen, default = sel["chosen"], sel["default"]
        log.info("%s: CHOSEN %s | default %s | fallback=%s | train Sharpe %.2f (default %.2f)", spec.name, params_str(chosen),
                 params_str(default), sel["fallback"], sel["sharpe"], sel["default_sharpe"])
        conf = gr.confirm(test, sel, default=default, train=train)           # the single look at TEST
    cid, did = sel["cell_id"], sel["default_cell_id"]

    # ---- 4. overfitting diagnostics ---------------------------------------------------------------------
    with T("pbo_regression"):
        pbo = pbo_arg = None
        pbo_S = 16
        for S in (16, 12, 8):
            try:
                pbo = gr.pbo(window=train, S=S)
                pbo_S = S
                break
            except ValueError as exc:
                log.warning("%s: PBO with S=%d failed: %s", spec.name, S, exc)
        if pbo is not None:
            try:
                pbo_arg = gr.pbo(window=train, S=pbo_S, selector="argmax")
            except ValueError as exc:
                log.warning("%s: argmax PBO failed: %s", spec.name, exc)
        try:
            reg_tab = gr.regression_table(window=train, B=500)
        except ValueError as exc:
            log.warning("%s: regression table failed: %s", spec.name, exc)
            reg_tab = None
        gr.to_csv(odir, windows={"train": train, "test": test, "full": None})

    # ---- 4b. grid figures ---------------------------------------------------------------------------------
    fig_paths: list[Path] = []
    with T("grid_figures"):
        try:
            fgr = sub_grid_for_figures(gr, chosen, default, sh.rf_m) if spec.key == "qm" else gr
            fig_paths += report.grid_figures(fgr, train, spec.fig["x"], spec.fig["y"], spec.fig["facets"], odir, selected=sel,
                                             default=default, label="train", surface=True)
            fig_paths += report.grid_figures(fgr, test, spec.fig["x"], spec.fig["y"], spec.fig["facets"], odir, selected=sel,
                                             default=default, label="test", surface=False)
            if spec.key == "qm":      # the whole quality x technical landscape (vol_target held at the default level)
                fig_paths += report.grid_figures(gr, train, spec.fig["x"], spec.fig["y"], ("technical", "quality"), odir / "grid_all",
                                                 selected=sel, default=default, label="train_all", surface=False)
                fig_paths += report.grid_figures(gr, test, spec.fig["x"], spec.fig["y"], ("technical", "quality"), odir / "grid_all",
                                                 selected=sel, default=default, label="test_all", surface=False)
        except Exception as exc:  # noqa: BLE001
            log.error("%s: grid figures failed: %s\n%s", spec.name, exc, traceback.format_exc())
        if pbo is not None:
            try:
                fig_paths += report.pbo_figure(pbo, odir)
            except Exception as exc:  # noqa: BLE001
                log.error("%s: PBO figure failed: %s", spec.name, exc)

    # ---- 5. final backtests + benchmarks --------------------------------------------------------------------
    with T("final_backtests"):
        res_c = spec.backtest_fn(ctx, chosen, start, end, BASE_COST if spec.key != "mf" else None)
        res_d = res_c if sel["is_default"] else spec.backtest_fn(ctx, default, start, end, BASE_COST if spec.key != "mf" else None)
    mc = res_c.monthly()
    chk = (mc.reindex(M.index) - M[cid]).abs().max()
    log.info("%s: consistency check, max |daily-engine monthly - grid column| = %.2e", spec.name, chk)
    with T("benchmarks"):
        ew = ctx.ew_universe(start, end, "SP900", exclude_sectors=spec.excluded)
        ew_d = ew.daily["ret_net"].loc[:end]
    net_c, net_d = res_c.daily["ret_net"], res_d.daily["ret_net"]
    bench_d = {"SPY": sh.spy.reindex(net_c.index), "RSP": sh.rsp.reindex(net_c.index), EW_NAME: ew_d.reindex(net_c.index)}
    bench_m = {k: to_m(v) for k, v in bench_d.items()}
    wins = perf_windows(end)
    with T("analysis"):
        A_c = analyze("chosen", res_c, sh, bench_d, bench_m, wins)
        A_d = A_c if sel["is_default"] else analyze("default", res_d, sh, bench_d, bench_m, wins)
        A_b = {k: {"metrics": {wn: perf_block(bench_m[k], sh.rf_m, w, bench_d[k]) for wn, w in wins.items()}} for k in bench_d}
        for k in bench_d:
            if sh.F is not None:
                A_b[k]["factor"] = {wn: ff_alpha(bench_m[k], sh.rf_m, sh.F, w) for wn, w in wins.items() if wn != "last36"}
    for tag, res in (("chosen", res_c), ("default", res_d)):
        res.daily.to_csv(odir / f"daily_{tag}.csv")
    pd.DataFrame(bench_d).to_csv(odir / "daily_benchmarks.csv")

    # ---- 8. robustness (every run is a trial) ----------------------------------------------------------------
    rob_rows, rob_daily = [], {}
    with T("robustness"):
        base_row = _rob_row("chosen (base, 10 bps)", chosen, "base", A_c, sh, wins)
        rob_rows.append(base_row)
        for name, p, cost, kind in spec.robust_fn(chosen):
            t0 = time.time()
            try:
                r = spec.backtest_fn(ctx, p, start, end, cost)
            except Exception as exc:  # noqa: BLE001  (module may not accept the variant: skip gracefully)
                log.warning("%s: robustness '%s' skipped (%s: %s)", spec.name, name, type(exc).__name__, exc)
                rob_rows.append({"name": name, "params": p, "kind": kind, "error": f"{type(exc).__name__}: {exc}"})
                continue
            A = analyze(name, r, sh, bench_d, bench_m, {"full": wins["full"], "train": wins["train"], "test": wins["test"]})
            row = _rob_row(name, p, kind, A, sh, wins)
            rob_rows.append(row)
            rob_daily[name] = r.daily["ret_net"]
            led.log(spec.name, p, window="full", n_months=row.get("n_months"), sharpe=row.get("sharpe_full"), cagr=row.get("cagr_full"),
                    maxdd=row.get("maxdd_full"), notes=f"robustness: {name}", variant=f"robust:{name}")
            log.info("%s: robustness '%s': CAGR %s Sharpe %s (%.0fs)", spec.name, name, fnum(row.get("cagr_full"), "pct"),
                     fnum(row.get("sharpe_full")), time.time() - t0)

    # ---- 4c. DSR (ledger N now includes the robustness trials) --------------------------------------------------
    dsr_tr = gr.dsr(sel, window=train)
    dsr_full = gr.dsr(sel, window=None)

    # ---- 10. evidence ladder ---------------------------------------------------------------------------------
    ladder = build_ladder(spec, sel, pbo, dsr_tr, A_c, A_b, bench_m, rob_rows, sh, wins)
    log.info("%s: LADDER %d/7 -> %s", spec.name, ladder["score"], ladder["verdict"])

    # ---- 11. short horizon -----------------------------------------------------------------------------------------
    with T("horizon"):
        hz_bench = {"SPY": bench_d["SPY"], "RSP": bench_d["RSP"], EW_NAME: bench_d[EW_NAME]}
        horizon = {"chosen": {"full": horizon_block(net_c, hz_bench, None), "test": horizon_block(net_c, hz_bench, wins["test"])}}
        horizon["default"] = horizon["chosen"] if sel["is_default"] else {
            "full": horizon_block(net_d, hz_bench, None), "test": horizon_block(net_d, hz_bench, wins["test"])}

    # ---- 7. tear sheets -------------------------------------------------------------------------------------------------
    surv_txt = sh.survivorship_header()
    ts_wins = {"Full": (None, None), "Train": (None, TRAIN_END.strftime("%Y-%m-%d")), "Test": (TEST_START.strftime("%Y-%m-%d"), None),
               "Last 36m": (wins["last36"][0].strftime("%Y-%m-%d"), None)}
    for lab, (a, b) in {"2011-14": SUBPERIODS["2011-14"], "2015-18": SUBPERIODS["2015-18"], "2019-22": SUBPERIODS["2019-22"],
                        "2023-26": SUBPERIODS["2023-26"]}.items():
        if pd.Timestamp(b) >= first_m and pd.Timestamp(a) <= end:
            ts_wins[lab] = (a, b)
    ts_paths: dict[str, list[Path]] = {}
    with T("tearsheets"):
        extra = {
            "T3 Overfitting diagnostics (train window)": report.overfitting_markdown(dsr_tr, pbo) if pbo is not None else "(PBO unavailable)",
            "T3b DSR on the full sample (ledger N)": report.overfitting_markdown(dsr_full),
            "T4 Parameter selection (train) and one-look confirmation (test)": report.selection_markdown(sel, conf),
            "T4b Parameter regression over the grid (train)": report.regression_markdown(reg_tab) if reg_tab is not None else "(unavailable)",
            "T5 Robustness (each run is a ledger trial)": robustness_md(rob_rows),
            "T6 Bias stress and survivorship": bias_md(ladder, sh),
            "Evidence ladder (research/06 section 5.7)": ladder_md(ladder),
        }
        if spec.key == "mf" and isinstance(res_c, mf.AnnualResult):
            try:
                extra["Annual rebalance: start-month spread (date luck)"] = md_df(mf.date_luck(res_c, ctx, test), 3)
            except Exception as exc:  # noqa: BLE001
                log.warning("date_luck failed: %s", exc)
        for tag, res, A in (("chosen", res_c, A_c), ("default", res_d, A_d)):
            if tag == "default" and sel["is_default"]:
                continue
            p = chosen if tag == "chosen" else default
            origin = ("literature default (plateau rule fell back)" if sel["fallback"] else "literature default (= plateau choice)") \
                if (tag == "chosen" and sel["is_default"]) else ("plateau_v1 choice" if tag == "chosen" else "literature default (doc-faithful)")
            header = {
                "strategy": f"{spec.title} ({spec.name})", "parameter set": f"{params_str(p)}  [{origin}]",
                "literature default": params_str(default), "universe": spec.universe_note,
                "windows": f"train {first_m:%Y-%m} to {TRAIN_END:%Y-%m}; test {TEST_START:%Y-%m} to {end:%Y-%m} (single look); data end {ctx.dates[-1]:%Y-%m-%d}",
                "trials N (ledger, distinct)": led.count(spec.name), "grid": f"{len(cells)} pre-registered cells, registered {reg['timestamp']}",
                "costs": f"{BASE_COST:g} bps one-way on every buy and sell (robustness 0/25/50)",
                "timing": "signal at the close of the month-end, trade at the next close; filings usable only if filed strictly before the signal date",
                "survivorship": surv_txt, "benchmarks": f"SPY, RSP, {EW_NAME} = equal-weight S&P 900 with the strategy's sector exclusions "
                                                       f"({', '.join(spec.excluded)}), 10 bps",
                "git commit": git_head(), "tear sheet for": tag,
            }
            try:
                ts_paths[tag] = report.tearsheet(
                    f"{spec.short} ({tag})", res.daily["ret_net"], res.daily["ret_gross"],
                    {"SPY": bench_d["SPY"], "RSP": bench_d["RSP"], EW_NAME: bench_d[EW_NAME]}, sh.rf_d, sh.F, ts_wins, odir, header,
                    turnover=res.daily["turnover"], holdings=res.daily["n_holdings"], extra_sections=extra, return_all=True)
            except Exception as exc:  # noqa: BLE001
                log.error("%s: tear sheet (%s) failed: %s\n%s", spec.name, tag, exc, traceback.format_exc())

    # ---- 13. live picks ------------------------------------------------------------------------------------------------------
    live = None
    if not args.no_live:
        with T("live"):
            live = run_live(spec, sh, chosen, default, sel["is_default"], args)

    # ---- results ---------------------------------------------------------------------------------------------------------------
    result = dict(
        key=spec.key, name=spec.name, title=spec.title, status="ok", generated=datetime.now(timezone.utc), n_cells=len(cells),
        ledger_trials=led.count(spec.name), start=start, end=end, first_month=first_m, last_month=last_m, train=list(train), test=list(test),
        chosen=chosen, default=default, chosen_is_default=sel["is_default"], chosen_cell_id=cid, default_cell_id=did,
        selection=dict(fallback=sel["fallback"], fallback_reason=sel["fallback_reason"], score=sel["score"], peak_ratio=sel["peak_ratio"],
                       train_sharpe=sel["sharpe"], default_train_sharpe=sel["default_sharpe"], plateau_width=sel["plateau_width"],
                       stability=sel["stability"], variants=sel["variants"], reasons=sel["reasons"], n_train_months=sel["n_train_months"]),
        confirm=dict(table=conf["table"], chosen_minus_default_sharpe=conf["chosen_minus_default_sharpe"],
                     chosen_minus_median_sharpe=conf["chosen_minus_median_sharpe"], chosen_rank_pct=conf["chosen_rank_pct"],
                     spearman_train_test=conf.get("spearman_train_test"), test_over_train_sharpe=conf.get("test_over_train_sharpe"),
                     criteria=conf["criteria"], notes=conf["notes"]),
        consistency_max_abs_diff=float(chk),
        metrics=dict(chosen=A_c["metrics"], default=A_d["metrics"], **{k: A_b[k]["metrics"] for k in A_b}),
        factor=dict(chosen=A_c["factor"], default=A_d["factor"], **{k: A_b[k].get("factor") for k in A_b}),
        turnover=dict(chosen=A_c["turnover"], default=A_d["turnover"]),
        pbo=None if pbo is None else {k: pbo[k] for k in ("pbo", "prob_loss", "degradation_slope", "n_combos", "S", "selector", "n_cells",
                                                           "n_months", "window")},
        pbo_argmax=None if pbo_arg is None else {k: pbo_arg[k] for k in ("pbo", "prob_loss", "degradation_slope", "n_combos", "S", "selector")},
        dsr_train=dsr_tr, dsr_full=dsr_full,
        regression=None if reg_tab is None else dict(r2=reg_tab.attrs.get("r2"), table=reg_tab),
        ladder=ladder, horizon=horizon, robustness=rob_rows,
        live=live, runtime_seconds=T.t, paths=dict(
            folder=str(odir.relative_to(OUT.parent)), tearsheets={k: [str(p.relative_to(OUT.parent)) for p in v] for k, v in ts_paths.items()},
            figures=[str(p.relative_to(OUT.parent)) for p in fig_paths]),
    )
    result["headline"] = make_headline(result)
    write_changelog(spec, odir, result, prev, args.note)
    write_results_md(spec, sh, result, odir, ts_paths, fig_paths, conf, sel, pbo, dsr_tr, reg_tab)
    summary.setdefault("strategies", {})[spec.name] = result
    update_summary(lambda cur: cur.setdefault("strategies", {}).__setitem__(spec.name, jsonable(result)))
    log.info("%s: DONE in %.0fs; CHOSEN %s; test Sharpe %.2f vs SPY %.2f", spec.name, sum(T.t.values()), params_str(chosen),
             A_c["metrics"]["test"].get("sharpe", float("nan")), A_b["SPY"]["metrics"]["test"].get("sharpe", float("nan")))
    # free the strategy caches before the next strategy (live picks are done)
    try:
        if spec.key == "mf":
            mf.clear_cache()
        elif spec.key == "qm":
            qm.clear_cache(ctx)
        else:
            tc.clear_cache(ctx)
    except Exception:  # noqa: BLE001
        pass
    return result


# ======================================================================================================
# robustness / ladder / bias markdown helpers
# ======================================================================================================
def _rob_row(name: str, params: dict, kind: str, A: dict, sh: Shared, wins: dict) -> dict:
    mfull, mtr, mte = A["metrics"]["full"], A["metrics"]["train"], A["metrics"]["test"]
    fa = A["factor"].get("full", {}) if A.get("factor") else {}
    return dict(name=name, params=params, kind=kind, n_months=mfull.get("n_months"), cagr_full=mfull.get("cagr"),
                sharpe_full=mfull.get("sharpe"), maxdd_full=mfull.get("maxdd_daily"), sharpe_train=mtr.get("sharpe"),
                sharpe_test=mte.get("sharpe"), cagr_test=mte.get("cagr"), ann_turnover=A["turnover"]["ann_turnover"],
                alpha_ann=fa.get("alpha_ann"), t_alpha=fa.get("t_alpha"),
                ir_vs_ew_full=(mfull.get(f"vs_{EW_NAME}") or {}).get("ir"), ir_vs_spy_full=(mfull.get("vs_SPY") or {}).get("ir"))


def robustness_md(rows: list[dict]) -> str:
    tab = []
    for r in rows:
        if "error" in r:
            tab.append({"run": r["name"], "note": f"skipped: {r['error']}"})
            continue
        tab.append({"run": r["name"], "full CAGR": fnum(r["cagr_full"], "pct"), "full Sharpe": fnum(r["sharpe_full"]),
                    "train Sharpe": fnum(r["sharpe_train"]), "test Sharpe": fnum(r["sharpe_test"]), "test CAGR": fnum(r["cagr_test"], "pct"),
                    "MaxDD": fnum(r["maxdd_full"], "pct"), "turnover/yr": fnum(r["ann_turnover"], "pct0"),
                    "FF5+MOM alpha": f"{fnum(r['alpha_ann'], 'pct')} (t={fnum(r['t_alpha'])})", "IR vs SPY": fnum(r["ir_vs_spy_full"]),
                    "IR vs EW": fnum(r["ir_vs_ew_full"])})
    return ("Full-period net results of one-at-a-time changes around the chosen cell. Every run is logged in the ledger as an extra trial "
            "(it raises N for the DSR).\n\n" + md_table(tab, ["run", "full CAGR", "full Sharpe", "train Sharpe", "test Sharpe", "test CAGR", "MaxDD",
                                                              "turnover/yr", "FF5+MOM alpha", "IR vs SPY", "IR vs EW", "note"]
                                                             if any("note" in t for t in tab) else None))


def md_df(df: pd.DataFrame, nd: int = 2) -> str:
    rows = []
    for ix, r in df.iterrows():
        rows.append({"": ix, **{c: (f"{v:.{nd}f}" if isinstance(v, (float, np.floating)) else v) for c, v in r.items()}})
    return md_table(rows)


def build_ladder(spec: Spec, sel: dict, pbo: dict | None, dsr_tr: dict, A_c: dict, A_b: dict, bench_m: dict, rob_rows: list,
                 sh: Shared, wins: dict) -> dict:
    crit = []
    m = A_c["metrics"]
    ir_tr = (m["train"].get(f"vs_{EW_NAME}") or {}).get("ir")
    ir_te = (m["test"].get(f"vs_{EW_NAME}") or {}).get("ir")
    ok1 = bool(ir_tr is not None and ir_te is not None and np.isfinite(ir_tr) and np.isfinite(ir_te) and ir_tr > 0 and ir_te > 0)
    crit.append(dict(n=1, name="Direction replicates: net IR vs same-universe EW > 0 on train AND test", passed=ok1,
                     detail=f"IR train {fnum(ir_tr)}, test {fnum(ir_te)}"))
    stab = sel.get("stability") or {}
    ok2 = bool((not sel["fallback"]) and (stab.get("passed", True)))
    crit.append(dict(n=2, name="Plateau: chosen cell passes the 5.4 eligibility and bootstrap stability", passed=ok2,
                     detail=("passed" if ok2 else f"FALLBACK to default: {sel['fallback_reason']}") +
                            (f"; stability {fnum(stab.get('share_within_one'), 'pct0')} within one step" if stab else "")))
    cost25 = next((r for r in rob_rows if r.get("name") == spec.cost_names.get(25) and "error" not in r), None)
    a25 = None if cost25 is None else cost25.get("alpha_ann")
    t25 = None if cost25 is None else cost25.get("t_alpha")
    ok3 = bool(a25 is not None and np.isfinite(a25) and a25 > 0)
    crit.append(dict(n=3, name="Costs: FF5+MOM net alpha still > 0 at 25 bps one-way", passed=ok3,
                     detail=f"alpha {fnum(a25, 'pct')}/yr (t={fnum(t25)}) at 25 bps; buy/hold-spread check for momentum not run"))
    fa = A_c["factor"].get("full") or {}
    alpha, t_alpha = fa.get("alpha_ann"), fa.get("t_alpha")
    expected = []
    for fac, sign in spec.expected_factors:
        beta = (fa.get("loadings") or {}).get(fac)
        tb = (fa.get("t_loadings") or {}).get(fac)
        if beta is not None and tb is not None and sign * tb > 2.0:
            expected.append(f"{fac} {beta:.2f} (t={tb:.1f})")
    ok4 = bool(alpha is not None and np.isfinite(alpha) and (alpha > 0 or (t_alpha > -1.0 and expected)))
    crit.append(dict(n=4, name="Factor view: FF5+MOM alpha > 0, or explained by the expected factors with no large negative alpha", passed=ok4,
                     detail=f"alpha {fnum(alpha, 'pct')}/yr (t={fnum(t_alpha)}, full sample to {(pd.Timestamp(fa['end']).strftime('%Y-%m') if fa.get('end') is not None else 'n/a')}, French data end 2026-08); expected-factor loadings with abs(t) > 2: "
                            f"{', '.join(expected) if expected else 'none'}"))
    pbo_v = None if pbo is None else pbo["pbo"]
    ok5 = bool(pbo_v is not None and pbo_v < 0.5 and np.isfinite(dsr_tr.get("dsr_neff", np.nan)) and "haircut_sharpe" in dsr_tr)
    crit.append(dict(n=5, name="Overfitting: PBO < 0.5 (DSR at N_hat and haircut Sharpe reported)", passed=ok5,
                     detail=f"PBO {fnum(pbo_v, 'pct')}; DSR(ledger N={dsr_tr['N_used']}) {fnum(dsr_tr['dsr'], 'num3')}, DSR(N_hat={fnum(dsr_tr['N_eff'])}) "
                            f"{fnum(dsr_tr['dsr_neff'], 'num3')}; haircut Sharpe {fnum(dsr_tr.get('haircut_sharpe'))} (train, aim DSR > 0.5: "
                            f"{'met' if dsr_tr['dsr_neff'] > 0.5 else 'not met'})"))
    se = fa.get("alpha_ann_se")
    drags = [0.0, 0.005, 0.01, 0.015, 0.02, 0.03]
    drag_tab = [dict(drag_bps=int(d * 1e4), alpha_ann=(alpha - d) if alpha is not None else None,
                     t=((alpha - d) / se) if (alpha is not None and se) else None) for d in drags]
    ok6 = bool(alpha is not None and np.isfinite(alpha) and alpha - 0.015 > 0)
    ew_act = (m["full"].get(f"vs_{EW_NAME}") or {}).get("active_cagr")
    crit.append(dict(n=6, name="Bias stress: FF5+MOM alpha survives a 150 bps/yr survivorship drag", passed=ok6,
                     detail=f"break-even drag {fnum(alpha, 'bps')} bps/yr (alpha {fnum(alpha, 'pct2')}); active CAGR vs EW-SP900 {fnum(ew_act, 'pct')}"))
    # 7: subperiods (active return vs SPY, geometric)
    sub_rows, npos = [], 0
    r_all = A_c["monthly"]
    rf = sh.rf_m
    for lab, w in SUBPERIODS.items():
        r = r_all[_mask(r_all.index, w)].dropna()
        if len(r) < 6:
            continue
        row = {"period": lab, "months": len(r)}
        for bn in ("SPY", "RSP", EW_NAME):
            b = bench_m[bn].reindex(r.index)
            row[bn] = metrics.active_cagr(r.to_numpy(), b.to_numpy(), 12)
        sub_rows.append(row)
        npos += int(row["SPY"] > 0)
    b_spy = bench_m["SPY"].reindex(r_all.index)
    pair = pd.concat([r_all, b_spy], axis=1, keys=["r", "b"]).dropna()
    worst12 = float("nan")
    if len(pair) > 12:
        e = metrics.rolling_compound(pair["r"].to_numpy(), 12) - metrics.rolling_compound(pair["b"].to_numpy(), 12)
        worst12 = float(np.min(e))
    ok7 = bool(len(sub_rows) >= 4 and npos >= 3) or bool(len(sub_rows) < 4 and npos >= math.ceil(0.75 * max(len(sub_rows), 1)))
    crit.append(dict(n=7, name="Subperiods: positive active return vs SPY in at least 3 of 4 subperiods", passed=ok7,
                     detail=f"{npos} of {len(sub_rows)} positive (" + ", ".join(f"{r['period']} {fnum(r['SPY'], 'pct')}" for r in sub_rows) +
                            f"); worst 12m active return vs SPY {fnum(worst12, 'pct')}"))
    score = sum(int(c["passed"]) for c in crit)
    verdict = "works" if score >= 5 else ("mixed" if score >= 3 else "does not work")
    failed = [str(c["n"]) for c in crit if not c["passed"]]
    text = (f"{score}/7 criteria passed -> {verdict}" + (f" (failed: #{', #'.join(failed)})" if failed else "") +
            ("" if score >= 5 else "; fewer than 5/7: do not claim it works, hold it as a research hypothesis at a modest weight"))
    return dict(score=score, verdict=verdict, text=text, criteria=crit, drag_table=drag_tab, subperiods=sub_rows,
                worst_12m_active_vs_spy=worst12, break_even_drag_bps=(alpha * 1e4 if alpha is not None else None))


def ladder_md(ladder: dict) -> str:
    rows = [{"#": c["n"], "criterion": c["name"], "pass": "yes" if c["passed"] else "NO", "evidence": c["detail"]} for c in ladder["criteria"]]
    return f"**{ladder['text']}**\n\n" + md_table(rows)


def bias_md(ladder: dict, sh: Shared) -> str:
    s = sh.survivorship()
    rows = [{"assumed drag (bps/yr)": d["drag_bps"], "FF5+MOM alpha after drag": fnum(d["alpha_ann"], "pct2"), "t": fnum(d["t"])}
            for d in ladder["drag_table"]]
    return (sh.survivorship_header() + "\n\nBreak-even drag (alpha = 0): " + fnum((ladder["break_even_drag_bps"] or float("nan")) / 1e4, "bps") +
            " bps/yr.\n\n" + md_table(rows) + f"\n\nCoverage by year and the EW-minus-RSP gap are in `output/survivorship.md`. "
            f"Overall: share with prices {s['share_mean']:.1%}; EW-SP900 minus RSP {s['gap900_cagr'] * 100:+.2f}%/yr.")


# ======================================================================================================
# live picks
# ======================================================================================================
@contextmanager
def live_age_override(days: int | None):
    """Run-time only override of the fundamentals-staleness limits used by QM's quality table and MF's eligibility."""
    if days is None:
        yield
        return
    from quant.signals import quality as qmod
    orig_q, orig_mf = qmod.quality_table, mf.SNAPSHOT_MAX_AGE_DAYS

    def patched(ctx, date, univ, max_age_days=200):
        return orig_q(ctx, date, univ, max_age_days=days)

    qmod.quality_table, mf.SNAPSHOT_MAX_AGE_DAYS = patched, days
    try:
        yield
    finally:
        qmod.quality_table, mf.SNAPSHOT_MAX_AGE_DAYS = orig_q, orig_mf


def _dump_attrs(df: pd.DataFrame, base: Path) -> dict:
    """Write every DataFrame attr as CSV and return the JSON-able rest."""
    rest = {}
    for k, v in df.attrs.items():
        if isinstance(v, pd.DataFrame):
            p = base.parent / f"{base.name}_{k}.csv"
            v.to_csv(p)
            rest[k] = f"see {p.name}"
        elif isinstance(v, dict) and v and all(isinstance(x, pd.DataFrame) for x in v.values()):
            for kk, vv in v.items():
                p = base.parent / f"{base.name}_{k}_{kk}.csv"
                vv.to_csv(p, index=False)
            rest[k] = {kk: f"{len(vv)} rows, see {base.name}_{k}_{kk}.csv" for kk, vv in v.items()}
        else:
            rest[k] = v
    return rest


def run_live(spec: Spec, sh: Shared, chosen: dict, default: dict, same: bool, args) -> dict:
    ctx = sh.ctx
    asof = ctx.dates[-1]
    if asof != pd.Timestamp("2026-10-16"):
        log.warning("latest trading day in the data is %s (expected 2026-10-16 for this run)", asof.date())
    live_dir = OUT / "live"
    live_dir.mkdir(parents=True, exist_ok=True)
    out = dict(asof=asof, max_age_days_override=args.live_max_age_days, forward_pe=bool(args.forward_pe))
    cache = {}
    for tag, p in (("chosen", chosen), ("default", default)):
        key = json.dumps(jsonable(p), sort_keys=True)
        if key in cache:
            df, picks = cache[key]
        else:
            with live_age_override(args.live_max_age_days):
                df = spec.live_fn(ctx, p, asof, bool(args.forward_pe))
            picks = spec.picks_fn(df)
            cache[key] = (df, picks)
        base = live_dir / f"{spec.name}_{tag}"
        df.to_csv(base.with_suffix(".csv"), index=False)
        rest = _dump_attrs(df, base)
        age = _age_stats(df, asof)
        write_json(live_dir / f"{spec.name}_{tag}_diagnostics.json", dict(strategy=spec.name, variant=tag, params=p, asof=asof,
                                                                           picks=picks.to_dict("records"), age=age, attrs=rest))
        out[tag] = dict(params=p, tickers=picks["ticker"].tolist(), weights=picks["weight"].round(6).tolist(), n=int(len(picks)),
                        age=age, csv=str(base.with_suffix(".csv").relative_to(OUT.parent)))
        log.info("%s live (%s): %d picks: %s", spec.name, tag, len(picks), ", ".join(picks["ticker"].astype(str).tolist()[:30]))
    return out


def _age_stats(df: pd.DataFrame, asof: pd.Timestamp) -> dict:
    sel = df
    if "selected" in df.columns:
        sel = df[df["selected"].fillna(False).astype(bool)]
    elif "pick" in df.columns:
        sel = df[df["pick"] == "PICK"]
    if "age_days" in sel.columns:
        ages = pd.to_numeric(sel["age_days"], errors="coerce")
    elif "period_end" in sel.columns:
        ages = (asof - pd.to_datetime(sel["period_end"], errors="coerce")).dt.days.astype(float)
    else:
        return {}
    if not len(ages):
        return {}
    return dict(max_age_days=float(ages.max()), median_age_days=float(ages.median()), n_older_than_150=int((ages > 150).sum()),
                n_older_than_200=int((ages > 200).sum()))


def refresh_overview(summary: dict) -> None:
    rows = []
    for name, r in summary.get("strategies", {}).items():
        lv = r.get("live")
        if not lv:
            continue
        for tag in ("chosen", "default"):
            v = lv.get(tag) or {}
            for i, (t, w) in enumerate(zip(v.get("tickers", []), v.get("weights", [])), 1):
                rows.append(dict(strategy=name, variant=tag, rank=i, ticker=t, weight=w, asof=lv.get("asof")))
    if rows:
        pd.DataFrame(rows).to_csv(OUT / "live" / "picks_overview.csv", index=False)


# ======================================================================================================
# results.md
# ======================================================================================================
def _mrow(label: str, m: dict, f: dict | None = None) -> dict:
    row = {"series": label, "months": m.get("n_months"), "CAGR": fnum(m.get("cagr"), "pct"), "vol": fnum(m.get("vol"), "pct"),
           "Sharpe": fnum(m.get("sharpe")), "MaxDD (daily)": fnum(m.get("maxdd_daily"), "pct")}
    if f is not None:
        row["FF5+MOM alpha (t)"] = (f"{fnum(f.get('alpha_ann'), 'pct')} ({fnum(f.get('t_alpha'))})" if f and "alpha_ann" in f else "–")
    return row


def write_changelog(spec: Spec, odir: Path, R: dict, prev: dict, note: str | None) -> None:
    """Append one entry to output/<strategy>/changelog.md: what ran, what changed against the previous run."""
    path = odir / "changelog.md"
    H = R["headline"]
    ph = (prev or {}).get("headline") or {}

    def g(d, *keys):
        for k in keys:
            d = (d or {}).get(k) if isinstance(d, dict) else None
        return d

    def pair(new, old, kind="num2"):
        return f"{fnum(new, kind)}" + (f" (previous run {fnum(old, kind)})" if old is not None else "")

    lines = [f"## {R['generated']:%Y-%m-%d %H:%M UTC} · git `{git_head()}` · data to {R['end']:%Y-%m-%d}", ""]
    if note:
        lines += [f"- note: {note}"]
    lines += ["- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the "
              "TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST",
              f"- chosen: `{params_str(R['chosen'])}`" + (" (= literature default)" if R["chosen_is_default"] else ""),
              f"- previous run chosen: " + (f"`{params_str(ph['chosen'])}` -> " + ("UNCHANGED" if ph["chosen"] == R["chosen"] else "CHANGED")
                                            if ph.get("chosen") else "none on file (first run)"),
              f"- train Sharpe chosen {pair(g(H, 'train', 'chosen', 'sharpe'), g(ph, 'train', 'chosen', 'sharpe'))}; "
              f"test Sharpe chosen {pair(g(H, 'test', 'chosen', 'sharpe'), g(ph, 'test', 'chosen', 'sharpe'))}; "
              f"test CAGR chosen {pair(g(H, 'test', 'chosen', 'cagr'), g(ph, 'test', 'chosen', 'cagr'), 'pct')}",
              f"- test Sharpe default {pair(g(H, 'test', 'default', 'sharpe'), g(ph, 'test', 'default', 'sharpe'))}; SPY "
              f"{pair(g(H, 'test', 'SPY', 'sharpe'), g(ph, 'test', 'SPY', 'sharpe'))}",
              f"- FF5+MOM alpha (full) {pair(g(H, 'full', 'chosen', 'ff5mom_alpha_ann'), g(ph, 'full', 'chosen', 'ff5mom_alpha_ann'), 'pct2')}",
              f"- PBO {pair(H.get('pbo'), ph.get('pbo'), 'pct')}; DSR train (ledger N) {pair(H.get('dsr_train_ledger_N'), ph.get('dsr_train_ledger_N'), 'num3')}",
              f"- evidence ladder {H['ladder_score']}/7 -> {H['verdict']}" + (f" (previous run {ph['ladder_score']}/7 -> {ph.get('verdict')})"
                                                                              if ph.get("ladder_score") is not None else ""),
              f"- ledger trials N = {R['ledger_trials']} (distinct cell ids; re-running a cell does not raise N)",
              f"- live picks (chosen): {', '.join(H.get('live_chosen_tickers', [])) or 'not computed'}", ""]
    head = "" if path.exists() else f"# {spec.title}: changelog\n\nOne entry per run of `quant/run_backtests.py` (newest last).\n\n"
    with open(path, "a") as fh:
        fh.write(head.replace("\\n", "\n") + "\n".join(lines) + "\n")


def make_headline(R: dict) -> dict:
    """Compact per-strategy digest (the full detail stays in the other keys of the summary)."""
    def row(m: dict, f: dict | None) -> dict:
        return dict(sharpe=m.get("sharpe"), cagr=m.get("cagr"), vol=m.get("vol"), maxdd_daily=m.get("maxdd_daily"),
                    ff5mom_alpha_ann=(f or {}).get("alpha_ann"), ff5mom_alpha_t=(f or {}).get("t_alpha"),
                    ir_vs_spy=(m.get("vs_SPY") or {}).get("ir"), ir_vs_ew=(m.get(f"vs_{EW_NAME}") or {}).get("ir"))
    out: dict = dict(chosen=R["chosen"], default=R["default"], chosen_is_default=R["chosen_is_default"],
                     fallback=R["selection"]["fallback"], fallback_reason=R["selection"]["fallback_reason"])
    for wn in ("train", "test", "full"):
        out[wn] = {"chosen": row(R["metrics"]["chosen"][wn], (R["factor"]["chosen"] or {}).get(wn)),
                   "default": row(R["metrics"]["default"][wn], (R["factor"]["default"] or {}).get(wn))}
        for b in ("SPY", "RSP", EW_NAME):
            out[wn][b] = row(R["metrics"][b][wn], ((R["factor"].get(b) or {}).get(wn)))
    out["pbo"] = (R["pbo"] or {}).get("pbo")
    out["pbo_argmax"] = (R["pbo_argmax"] or {}).get("pbo")
    out["dsr_train_ledger_N"] = R["dsr_train"]["dsr"]
    out["dsr_train_Nhat"] = R["dsr_train"]["dsr_neff"]
    out["dsr_full_ledger_N"] = R["dsr_full"]["dsr"]
    out["haircut_sharpe_train"] = R["dsr_train"].get("haircut_sharpe")
    out["n_trials_ledger"] = R["ledger_trials"]
    out["ladder_score"] = R["ladder"]["score"]
    out["verdict"] = R["ladder"]["verdict"]
    out["ladder_text"] = R["ladder"]["text"]
    out["confirm_criteria"] = R["confirm"]["criteria"]
    out["spearman_train_test"] = R["confirm"]["spearman_train_test"]
    out["p_beat_spy"] = {win: {h: ((R["horizon"]["chosen"][win].get("SPY") or {}).get(h) or {}).get("p_beat") for h in ("13", "63", "126")}
                         for win in ("full", "test")}
    if R.get("live"):
        out["live_asof"] = R["live"]["asof"]
        out["live_chosen_tickers"] = R["live"]["chosen"]["tickers"]
        out["live_default_tickers"] = R["live"]["default"]["tickers"]
    return out


def write_results_md(spec: Spec, sh: Shared, R: dict, odir: Path, ts_paths: dict, fig_paths: list, conf: dict, sel: dict, pbo, dsr_tr, reg_tab) -> None:
    L: list[str] = [f"# {spec.title}: results", "",
                    f"Generated {R['generated']:%Y-%m-%d %H:%M UTC} · git `{git_head()}` · data to {sh.ctx.dates[-1]:%Y-%m-%d}, backtest to {R['end']:%Y-%m-%d} · "
                    f"{R['n_cells']} pre-registered cells · {R['ledger_trials']} trials in the ledger.", "",
                    f"**Universe**: {spec.universe_note}. Net of {BASE_COST:g} bps one-way costs, signal at month-end close, trade at the next close.", "",
                    f"## Verdict: {R['ladder']['text']}", ""]
    L += ["## Parameters", "",
          f"- **Chosen** ({'= literature default' if R['chosen_is_default'] else 'plateau_v1 choice'}"
          f"{'; FALLBACK: ' + str(sel['fallback_reason']) if sel['fallback'] else ''}): `{params_str(R['chosen'])}`",
          f"- **Literature default**: `{params_str(R['default'])}`",
          f"- Train {R['first_month']:%Y-%m} to {TRAIN_END:%Y-%m} ({sel['n_train_months']} months): chosen Sharpe {fnum(sel['sharpe'])}, default {fnum(sel['default_sharpe'])}; "
          f"plateau width {sel['plateau_width']} cells; bootstrap stability: "
          + (f"{fnum((sel['stability'] or {}).get('share_within_one'), 'pct0')} within one step" if sel.get("stability") else "n/a"), ""]
    for wn, title in (("train", "Train"), ("test", "Test (single look)"), ("full", "Full period"), ("last36", "Last 36 months")):
        rows = []
        mm, ff = R["metrics"], R["factor"]
        rows.append(_mrow("chosen", mm["chosen"][wn], (ff["chosen"] or {}).get(wn)))
        if not R["chosen_is_default"]:
            rows.append(_mrow("default", mm["default"][wn], (ff["default"] or {}).get(wn)))
        for b in ("SPY", "RSP", EW_NAME):
            rows.append(_mrow(b, mm[b][wn], ((ff.get(b) or {}).get(wn))))
        L += [f"### {title}", "", md_table(rows), ""]
    c = R["confirm"]["table"]
    L += ["## Selection and confirmation", "", report.selection_markdown(sel, conf), ""]
    L += ["## Overfitting diagnostics (train)", "", report.overfitting_markdown(dsr_tr, pbo) if pbo is not None else "(PBO unavailable)", ""]
    L += ["DSR on the full sample:", "", report.overfitting_markdown(R["dsr_full"]), ""]
    if reg_tab is not None:
        L += ["## Grid regression (train)", "", report.regression_markdown(reg_tab), ""]
    L += ["## Robustness (each run is a ledger trial)", "", robustness_md(R["robustness"]), ""]
    L += ["## Evidence ladder", "", ladder_md(R["ladder"]), "", "## Bias stress", "", bias_md(R["ladder"], sh), ""]
    L += ["## Short horizon (daily net returns, chosen parameters)", ""]
    rows = []
    for win in ("full", "test"):
        for h in HORIZONS:
            x = ((R["horizon"]["chosen"][win].get("SPY") or {}).get(str(h)))
            if not x:
                continue
            q, rq = x["excess_quantiles"], x["return_quantiles"]
            rows.append({"window": win, "horizon": f"{h}d", "P(beat SPY)": f"{x['p_beat'] * 100:.1f}% [{x['p_beat_ci'][0] * 100:.0f}-{x['p_beat_ci'][1] * 100:.0f}]",
                         "P(loss)": fnum(x["p_loss"], "pct"), "excess 5%/median/95%": f"{q['5'] * 100:.1f} / {q['50'] * 100:.1f} / {q['95'] * 100:.1f} pts",
                         "return 5%/median/95%": f"{rq['5'] * 100:.1f} / {rq['50'] * 100:.1f} / {rq['95'] * 100:.1f}%"})
    L += [md_table(rows), ""]
    if R.get("live"):
        lv = R["live"]
        L += [f"## Live picks (as of {pd.Timestamp(lv['asof']):%Y-%m-%d})", "",
              f"- chosen ({lv['chosen']['n']}): {', '.join(lv['chosen']['tickers'])}",
              f"- default ({lv['default']['n']}): {', '.join(lv['default']['tickers'])}",
              f"- tables: `{lv['chosen']['csv']}`, `{lv['default']['csv']}` (+ diagnostics JSON in `output/live/`)",
              f"- fundamentals age of the chosen picks: {lv['chosen'].get('age')}", ""]
    L += ["## Files", ""]
    for tag, paths in ts_paths.items():
        if paths:
            L.append(f"- tear sheet ({tag}): [{paths[0].name}]({paths[0].name})")
    L += ["- grid: `grid_cells.csv`, `grid_monthly_returns.csv`, `grid_metrics_{train,test,full}.csv`", "- daily series: `daily_chosen.csv`, `daily_default.csv`, `daily_benchmarks.csv`", ""]
    pngs = [p for p in list(fig_paths) + [q for v in ts_paths.values() for q in v if q.suffix == ".png"]]
    seen = set()
    L += ["## Figures", ""]
    for p in pngs:
        try:
            rel = p.relative_to(odir)
        except ValueError:
            rel = Path(p.name)
        if len(rel.parts) > 1 and "overview" not in rel.name:
            continue                      # the many single-facet files of grid_all/ stay on disk; only overviews are embedded
        if str(rel) in seen:
            continue
        seen.add(str(rel))
        L += [f"![{rel.stem}]({rel})", ""]
    L += ["## Runtime (seconds)", "", md_table([R["runtime_seconds"]]), ""]
    (odir / "results.md").write_text("\n".join(L))


# ======================================================================================================
# blend
# ======================================================================================================
def run_blend(sh: Shared, summary: dict) -> dict | None:
    ctx, end = sh.ctx, sh.end
    names = [SPECS[k].name for k in ("qm", "mf", "tc")]
    daily = {}
    for n in names:
        p = OUT / n / "daily_chosen.csv"
        if not p.exists():
            log.warning("blend skipped: %s missing (run that strategy first)", p)
            return None
        daily[n] = pd.read_csv(p, index_col=0, parse_dates=True)
    idx = None
    for d in daily.values():
        idx = d.index if idx is None else idx.intersection(d.index)
    net = pd.concat([daily[n]["ret_net"].reindex(idx) for n in names], axis=1).mean(axis=1)
    gross = pd.concat([daily[n]["ret_gross"].reindex(idx) for n in names], axis=1).mean(axis=1)
    turn = pd.concat([daily[n]["turnover"].reindex(idx) for n in names], axis=1).mean(axis=1)
    hold = pd.concat([daily[n]["n_holdings"].reindex(idx) for n in names], axis=1).sum(axis=1)
    odir = OUT / "blend"
    odir.mkdir(parents=True, exist_ok=True)
    start = idx[0]
    excl = ("Financials", "Real Estate")
    ew = ctx.ew_universe(start - pd.Timedelta(days=5), end, "SP900", exclude_sectors=excl).daily["ret_net"].loc[:end]
    bench_d = {"SPY": sh.spy.reindex(idx), "RSP": sh.rsp.reindex(idx), EW_NAME: ew.reindex(idx)}
    bench_m = {k: to_m(v) for k, v in bench_d.items()}
    wins = perf_windows(end)
    m = to_m(net)
    comp_m = {SPECS[k].key.upper(): to_m(daily[SPECS[k].name]["ret_net"].reindex(idx)) for k in ("qm", "mf", "tc")}
    res = dict(components=names, start=idx[0], end=idx[-1], n_days=len(idx), metrics={}, factor={}, component_metrics={})
    for wn, w in wins.items():
        res["metrics"][wn] = perf_block(m, sh.rf_m, w, net, bench_m)
        if sh.F is not None:
            res["factor"][wn] = ff_alpha(m, sh.rf_m, sh.F, w)
        for ck, cm in comp_m.items():
            res["component_metrics"].setdefault(ck, {})[wn] = perf_block(cm, sh.rf_m, w, daily[SPECS[ck.lower()].name]["ret_net"].reindex(idx), bench_m)
    res["benchmarks"] = {k: {wn: perf_block(bench_m[k], sh.rf_m, w, bench_d[k]) for wn, w in wins.items()} for k in bench_m}
    res["horizon"] = {"full": horizon_block(net, bench_d, None), "test": horizon_block(net, bench_d, wins["test"])}
    # correlations (monthly returns and active returns vs SPY) on full / train / test
    series = {**comp_m, "Blend": m, "SPY": bench_m["SPY"], "RSP": bench_m["RSP"]}
    corr = {}
    df = pd.DataFrame(series).dropna()
    for wn in ("full", "train", "test"):
        d = df[_mask(df.index, wins[wn])]
        act = d.drop(columns=["SPY"]).sub(d["SPY"], axis=0)
        corr[wn] = dict(returns=d.corr(), active_vs_spy=act.corr(), months=len(d))
        ew_m = bench_m[EW_NAME].reindex(d.index)
        act_ew = d.drop(columns=[EW_NAME], errors="ignore")[["QM", "MF", "TC", "Blend"]].sub(ew_m, axis=0)
        corr[wn]["active_vs_ew"] = act_ew.corr()
        # tail dependence: correlation of the three components in the worst 10% SPY months
        worst = d["SPY"] <= d["SPY"].quantile(0.10)
        corr[wn]["worst10pct_spy_months_returns"] = d.loc[worst, ["QM", "MF", "TC"]].corr() if worst.sum() >= 5 else None
    res["correlation"] = corr
    ts_wins = {"Full": (None, None), "Train": (None, TRAIN_END.strftime("%Y-%m-%d")), "Test": (TEST_START.strftime("%Y-%m-%d"), None),
               "Last 36m": (wins["last36"][0].strftime("%Y-%m-%d"), None)}
    for lab, (a, b) in SUBPERIODS.items():
        if pd.Timestamp(b) >= idx[0] and pd.Timestamp(a) <= end:
            ts_wins[lab] = (a, b)
    chosen_txt = "; ".join(f"{SPECS[k].key.upper()}: {params_str(summary['strategies'][SPECS[k].name]['chosen'])}"
                           if SPECS[k].name in summary.get("strategies", {}) else f"{SPECS[k].key.upper()}: (see its summary)" for k in ("qm", "mf", "tc"))
    n_tr = sum(grid.Ledger().count(n) for n in names)
    header = {"strategy": "Blend: equal-weight QM + MF + TC (chosen parameters)", "components": chosen_txt,
              "construction": "arithmetic average of the three strategies' DAILY net returns (1/3 each, daily re-equalised): approximates a monthly-rebalanced "
                              "equal-dollar blend; the re-equalisation cost between strategies is ignored; common period only (all three live)",
              "universe": "the three strategies' universes (point-in-time S&P 900)", "windows": f"{idx[0]:%Y-%m-%d} to {idx[-1]:%Y-%m-%d}; train to {TRAIN_END:%Y-%m}, test from {TEST_START:%Y-%m}",
              "trials N (sum of the three ledgers)": n_tr, "costs": f"{BASE_COST:g} bps one-way inside each strategy; turnover = average of the three, holdings = sum (overlaps not netted)",
              "survivorship": sh.survivorship_header(),
              "benchmarks": f"SPY, RSP, {EW_NAME} (equal-weight S&P 900 ex Financials and Real Estate, 10 bps)", "git commit": git_head()}
    corr_md = ["Monthly return correlation (full):\n\n" + md_df(corr["full"]["returns"]), "Active-return correlation vs SPY (full):\n\n" + md_df(corr["full"]["active_vs_spy"]),
               "Active-return correlation vs SPY (test):\n\n" + md_df(corr["test"]["active_vs_spy"])]
    comp_rows = []
    for ck in comp_m:
        for wn in ("train", "test", "full"):
            mm = res["component_metrics"][ck][wn]
            comp_rows.append({"series": ck, "window": wn, "CAGR": fnum(mm.get("cagr"), "pct"), "Sharpe": fnum(mm.get("sharpe")), "MaxDD": fnum(mm.get("maxdd_daily"), "pct")})
    for wn in ("train", "test", "full"):
        mm = res["metrics"][wn]
        comp_rows.append({"series": "Blend", "window": wn, "CAGR": fnum(mm.get("cagr"), "pct"), "Sharpe": fnum(mm.get("sharpe")), "MaxDD": fnum(mm.get("maxdd_daily"), "pct")})
    extra = {"Blend vs components": md_table(comp_rows), "C10 / correlations": "\n\n".join(corr_md) + "\n\n![C10 correlation](C10_correlation.png)"}
    paths = []
    try:
        paths += report.correlation_figure(series, odir, benchmark="SPY")
    except Exception as exc:  # noqa: BLE001
        log.error("correlation figure failed: %s", exc)
    try:
        ts = report.tearsheet("Blend QM+MF+TC", net, gross, {"SPY": bench_d["SPY"], "RSP": bench_d["RSP"], EW_NAME: bench_d[EW_NAME]}, sh.rf_d, sh.F,
                              ts_wins, odir, header, turnover=turn, holdings=hold, extra_sections=extra, return_all=True)
        res["tearsheet"] = str(ts[0].relative_to(OUT.parent))
    except Exception as exc:  # noqa: BLE001
        log.error("blend tear sheet failed: %s\n%s", exc, traceback.format_exc())
    pd.DataFrame({"ret_net": net, "ret_gross": gross, "turnover": turn, "n_holdings": hold}).to_csv(odir / "daily_blend.csv")
    res["figures"] = [str(p.relative_to(OUT.parent)) for p in paths]
    mm = res["metrics"]
    log.info("blend: test Sharpe %.2f CAGR %.1f%% | full Sharpe %.2f | FF5+MOM alpha (full) %s", mm["test"].get("sharpe", np.nan),
             100 * mm["test"].get("cagr", np.nan), mm["full"].get("sharpe", np.nan), (res["factor"].get("full") or {}).get("alpha_ann"))
    return res


# ======================================================================================================
# main
# ======================================================================================================
def update_summary(mutate) -> dict:
    """Reload output/summary.json, apply ``mutate(summary)`` and write it back (keeps other strategies' entries)."""
    cur = load_summary()
    mutate(cur)
    write_json(OUT / "summary.json", cur)
    return cur


def load_summary() -> dict:
    p = OUT / "summary.json"
    if p.exists():
        try:
            return json.loads(p.read_text())
        except Exception:  # noqa: BLE001
            log.warning("summary.json unreadable; starting a fresh one")
    return {}


def live_only(spec: Spec, sh: Shared, args, summary: dict) -> None:
    s = (summary.get("strategies") or {}).get(spec.name)
    if not s or "chosen" not in s:
        log.error("%s: no stored parameters in summary.json (run the full pipeline first)", spec.name)
        return
    chosen, default = s["chosen"], s["default"]
    live = run_live(spec, sh, chosen, default, bool(s.get("chosen_is_default")), args)
    s["live"] = jsonable(live)
    summary["strategies"][spec.name] = s
    def upd(cur):
        st = cur.setdefault("strategies", {}).setdefault(spec.name, {})
        st["live"] = jsonable(live)
        hl = st.setdefault("headline", {})
        hl["live_asof"] = jsonable(live["asof"])
        hl["live_chosen_tickers"] = live["chosen"]["tickers"]
        hl["live_default_tickers"] = live["default"]["tickers"]

    update_summary(upd)


def main(argv=None) -> int:
    ap = argparse.ArgumentParser(description=__doc__.split("\n")[0], formatter_class=argparse.RawDescriptionHelpFormatter, epilog=__doc__)
    ap.add_argument("--strategy", default="all", help="qm | mf | tc | all (default all)")
    ap.add_argument("--no-live", action="store_true", help="skip the live picks")
    ap.add_argument("--live-only", action="store_true", help="only recompute live picks from output/summary.json")
    ap.add_argument("--reuse-grid", action="store_true", help="development: reload grid monthly returns from disk")
    ap.add_argument("--blend", action="store_true", help="after the selected strategies, recompute the blend from saved daily series")
    ap.add_argument("--blend-only", action="store_true", help="only recompute the blend (and survivorship) from saved daily series")
    ap.add_argument("--no-forward-pe", dest="forward_pe", action="store_false",
                    help="do not fetch yfinance forwardPE (information column) for the comps live table")
    ap.add_argument("--live-max-age-days", type=int, default=None, help="relax fundamentals staleness for QM/MF live screens (e.g. 215)")
    ap.add_argument("--note", default=None, help="free text recorded in output/<strategy>/changelog.md and the ledger notes "
                                                 "(e.g. the reason for a re-run after a data-layer fix)")
    ap.add_argument("--end", default=str(DEFAULT_END.date()), help="last month-end of the backtest (default 2026-09-30)")
    args = ap.parse_args(argv)
    setup_logging()
    keys = ["qm", "mf", "tc"] if args.strategy == "all" else [KEYS[args.strategy.lower()]]
    if args.blend_only:
        keys = []
    end = pd.Timestamp(args.end)
    t_start = time.time()
    # 1. verify every registration before any work
    try:
        for k in keys:
            verify_prereg(SPECS[k])
            log.info("%s: preregistration matches the module GRID", SPECS[k].name)
    except PreregMismatch as exc:
        log.error("STOP: %s", exc)
        print(f"PREREGISTRATION MISMATCH: {exc}", file=sys.stderr)
        return 2
    sh = Shared(end)
    summary = load_summary()
    if summary and not args.live_only:
        (OUT / "summary_previous_run.json").write_text(json.dumps(summary, indent=2) + "\n")
    summary.update(generated=datetime.now(timezone.utc), data_end=sh.ctx.dates[-1], backtest_end=end,
                   windows=dict(train_end=TRAIN_END, test_start=TEST_START), git_commit=git_head())
    failures = []
    if not args.live_only:
        t0 = time.time()
        write_survivorship(sh)
        log.info("survivorship audit written in %.0fs", time.time() - t0)
        summary["survivorship"] = {k: v for k, v in sh.survivorship().items() if k not in ("table", "monthly")}
        summary["survivorship"]["by_year"] = sh.survivorship()["table"].reset_index(names="year")
    for k in keys:
        spec = SPECS[k]
        try:
            if args.live_only:
                live_only(spec, sh, args, summary)
            else:
                run_strategy(spec, sh, args, summary)
        except Exception as exc:  # noqa: BLE001
            failures.append(spec.name)
            log.error("%s FAILED: %s\n%s", spec.name, exc, traceback.format_exc())
            msg = f"failed: {type(exc).__name__}: {exc}"
            update_summary(lambda cur: cur.setdefault("strategies", {}).setdefault(spec.name, {}).__setitem__("status", msg))
    if (args.strategy == "all" or args.blend or args.blend_only) and not args.live_only:
        try:
            b = run_blend(sh, summary)
            if b is not None:
                summary["blend"] = b
        except Exception as exc:  # noqa: BLE001
            failures.append("blend")
            log.error("blend FAILED: %s\n%s", exc, traceback.format_exc())
    total = round(time.time() - t_start, 1)

    def finish(cur):
        for k in ("generated", "data_end", "backtest_end", "windows", "git_commit"):
            cur[k] = jsonable(summary[k])
        if "survivorship" in summary and not args.live_only:
            cur["survivorship"] = jsonable(summary["survivorship"])
        if "blend" in summary:
            cur["blend"] = jsonable(summary["blend"])
        cur.setdefault("runs", []).append(dict(at=jsonable(datetime.now(timezone.utc)), strategies=keys, live_only=args.live_only,
                                               seconds=total, failures=failures))

    final = update_summary(finish)
    if not args.no_live:
        refresh_overview(final)
    log.info("finished in %.0fs; failures: %s", time.time() - t_start, failures or "none")
    return 1 if failures else 0


if __name__ == "__main__":
    sys.exit(main())
