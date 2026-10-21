"""Run the three strategies end to end.

For each strategy: evaluate every pre-registered parameter combination, pick the parameters on the 2011-2018
train window (plateau rule, never the single best cell), check them once on 2019-2026, compare with SPY and an
equal-weight portfolio of the same universe, and list what the strategy holds today.

    .venv/bin/python -m quant.run              # everything (~5 minutes)
    .venv/bin/python -m quant.run --live-only  # only today's picks, with the parameters already chosen

Writes to output/:
    results.csv              performance (net of costs) of each strategy - the team doc's rules and the improved
                             version - and the benchmarks, for train / test / full period
    performance.png          growth of $1
    chosen_params.json       parameters picked on the train window (read by --live-only)
    <strategy>/grid.csv      every pre-registered parameter combination with its train and test Sharpe
    <strategy>/picks.csv     what the strategy holds today, plus next-ranked alternates
    <strategy>/preregistration.json   the grid, written down before it was run
"""
from __future__ import annotations

import argparse
import json
import logging
import time

import matplotlib
matplotlib.use("Agg")
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
import pandas as pd  # noqa: E402

from quant import settings  # noqa: E402
from quant.backtest import grid, metrics, stats  # noqa: E402
from quant.strategies import magic_formula as mf  # noqa: E402
from quant.strategies import quality_momentum as qm  # noqa: E402
from quant.strategies import momentum_mf as mm  # noqa: E402

log = logging.getLogger("quant.run")

TRAIN_END = pd.Timestamp(settings.TRAIN_END)
TEST_START = pd.Timestamp(settings.TEST_START)
LEDGER = settings.CACHE / "ledger.csv"          # every configuration ever evaluated (trial count for DSR)
PARAMS_FILE = settings.OUTPUT / "chosen_params.json"

STRATEGIES = {
    "quality_momentum": dict(
        label="Quality momentum", mod=qm, excluded=("Financials", "Real Estate"),
        start=lambda ctx: qm.first_signal_date(ctx),
        fn=lambda ctx, st, end: (lambda cell: qm.monthly_returns(cell, ctx=ctx, start=st, end=end))),
    "magic_formula": dict(
        label="Magic Formula", mod=mf, excluded=("Financials", "Real Estate", "Utilities"),
        start=lambda ctx: mf.common_start(ctx),
        fn=lambda ctx, st, end: mf.make_grid_fn(ctx, start=st, end=end)),
    "momentum_mf": dict(
        label="Momentum + Magic Formula", mod=mm, excluded=("Financials", "Real Estate"),
        start=lambda ctx: mm.first_signal_date(ctx),
        fn=lambda ctx, st, end: (lambda cell: mm.monthly_returns(cell, ctx=ctx, start=st, end=end))),
}
# Trading comps was researched and backtested but did not beat its benchmarks; its code is in quant/shelved/.


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
def last_complete_month_end(ctx) -> pd.Timestamp:
    me = ctx.month_ends(ctx.dates[0], ctx.dates[-1])
    last = me[-1]
    # a month is complete only if its last trading day is not the last day of data mid-month
    return me[-2] if last == ctx.dates[-1] and (last + pd.offsets.BDay(1)).month == last.month else last


def monthly_rf(ctx) -> pd.Series:
    out = (1.0 + ctx.rf).groupby(ctx.rf.index.to_period("M")).prod() - 1.0
    out.index = out.index.to_timestamp(how="end").normalize()
    return out


def _align_rf(r: pd.Series, rf: pd.Series) -> pd.Series:
    rf_m = rf.copy()
    rf_m.index = rf_m.index.to_period("M")
    return pd.Series(rf_m.reindex(r.index.to_period("M")).fillna(0.0).to_numpy(), index=r.index)


def window_stats(r: pd.Series, rf: pd.Series, factors: pd.DataFrame, start, end) -> dict:
    """CAGR, volatility, Sharpe, max drawdown and Fama-French 5 + momentum alpha of monthly net returns."""
    x = r.loc[start:end].dropna()
    if len(x) < 12:
        return {}
    rfx = _align_rf(x, rf)
    out = dict(cagr=metrics.cagr(x, 12), vol=metrics.ann_vol(x, 12), sharpe=metrics.sharpe(x, rfx, 12),
               max_drawdown=metrics.max_drawdown(x), months=len(x))
    try:
        reg = stats.factor_regression(x - rfx, factors, model="ff5mom", lags=4)
        out.update(alpha=reg["alpha_ann"], alpha_t=reg["t_alpha"])
    except Exception as e:                       # factor file ends a month or two before the price data
        log.warning("factor regression failed: %s", e)
    return out


def ew_benchmark(ctx, start, end, excluded) -> pd.Series:
    """Equal-weight portfolio of the same point-in-time universe (no signal): the like-for-like benchmark."""
    res = ctx.ew_universe(start, end, "SP900", exclude_sectors=excluded)
    return metrics.to_monthly(res.daily["ret_net"])


def spy_monthly(ctx) -> pd.Series:
    return metrics.to_monthly(ctx.returns["SPY"].dropna())


# --------------------------------------------------------------------------------------------------
# one strategy
# --------------------------------------------------------------------------------------------------
def run_strategy(ctx, name: str, end: pd.Timestamp, rf: pd.Series, factors: pd.DataFrame) -> dict:
    spec = STRATEGIES[name]
    mod = spec["mod"]
    t0 = time.time()
    start = pd.Timestamp(spec["start"](ctx))
    fn = spec["fn"](ctx, start, end)
    log.info("%s: %d pre-registered cells, %s .. %s", name, len(mod.GRID), start.date(), end.date())
    gr = grid.run_grid(name, mod.GRID, fn, rf=rf, ledger=grid.Ledger(LEDGER), notes="grid v2")
    sel = gr.select(train=(None, TRAIN_END))
    chosen = sel["chosen"]
    gr.confirm(test=(TEST_START, end), chosen=sel)
    pbo = gr.pbo(window=(None, TRAIN_END))["pbo"]
    dsr = gr.dsr(sel, window=(None, TRAIN_END)).get("dsr", float("nan"))

    # grid table: every cell's train and test Sharpe (the doc asked for "every permutation")
    tr, te = gr.metrics((None, TRAIN_END)), gr.metrics((TEST_START, end))
    g = gr.params.join(tr[["sharpe", "cagr"]].add_prefix("train_")).join(te[["sharpe", "cagr"]].add_prefix("test_"))
    g["chosen"] = g.index == sel["cell_id"]
    (settings.OUTPUT / name).mkdir(parents=True, exist_ok=True)
    g.round(4).to_csv(settings.OUTPUT / name / "grid.csv", index=False)

    # returns of the improved (chosen) version and of the team doc's original rules, same start date
    series = {"improved": gr.M[sel["cell_id"]].dropna()}
    if hasattr(mod, "DOC_DEFAULT"):
        series["doc rules"] = fn(dict(mod.DOC_DEFAULT)).dropna()
    series["equal-weight universe"] = ew_benchmark(ctx, start, end, spec["excluded"])
    log.info("%s: chosen %s (fallback=%s) in %.0fs", name, chosen, sel["fallback"], time.time() - t0)
    return dict(name=name, label=spec["label"], chosen=chosen, fallback=bool(sel["fallback"]),
                fallback_reason=sel.get("fallback_reason"), pbo=pbo, dsr=dsr, series=series, start=start)


def add_comparison(runs: list[dict]) -> None:
    """Put momentum alone, Magic Formula alone and a 50/50 split of the two next to the merged strategy,
    on the months all of them cover (the Magic Formula starts last)."""
    by = {r["name"]: r for r in runs}
    if not {"quality_momentum", "magic_formula", "momentum_mf"} <= set(by):
        return
    q, m = by["quality_momentum"]["series"]["improved"], by["magic_formula"]["series"]["improved"]
    both = pd.concat([q, m], axis=1).dropna()
    merged = by["momentum_mf"]
    merged["start"] = max(merged["start"], both.index[0])
    merged["series"] = {"merged": merged["series"]["improved"], "momentum alone": q, "Magic Formula alone": m,
                        "50/50 split": both.mean(axis=1),          # two half-portfolios, rebalanced monthly
                        "equal-weight universe": merged["series"]["equal-weight universe"]}


def results_table(runs: list[dict], spy: pd.Series, end, rf, factors) -> pd.DataFrame:
    rows = []
    windows = {"train": (None, TRAIN_END), "test": (TEST_START, end), "full": (None, end)}
    for run in runs:
        start = run["start"]
        for version, r in run["series"].items():
            for w, (a, b) in windows.items():
                s = window_stats(r, rf, factors, a or start, b)
                rows.append(dict(strategy=run["label"], version=version, window=w, **s))
        for w, (a, b) in windows.items():
            rows.append(dict(strategy=run["label"], version="SPY", window=w,
                             **window_stats(spy, rf, factors, a or start, b)))
    df = pd.DataFrame(rows)
    pct = ["cagr", "vol", "max_drawdown", "alpha"]
    df[pct] = (df[pct] * 100).round(1)
    df[["sharpe", "alpha_t"]] = df[["sharpe", "alpha_t"]].round(2)
    return df.rename(columns={"cagr": "cagr_%", "vol": "vol_%", "max_drawdown": "max_drawdown_%", "alpha": "alpha_%"})


def chart(runs: list[dict], spy: pd.Series, path) -> None:
    fig, axes = plt.subplots(1, len(runs), figsize=(5.2 * len(runs), 4.2), sharey=True)
    for ax, run in zip(np.atleast_1d(axes), runs):
        start = run["start"]
        series = dict(run["series"], SPY=spy)
        style = {"improved": dict(lw=2.2, color="#1f6f8b"), "doc rules": dict(lw=1.4, color="#e07b39", ls="--"),
                 "merged": dict(lw=2.2, color="#6a3d9a"), "momentum alone": dict(lw=1.4, color="#1f6f8b"),
                 "Magic Formula alone": dict(lw=1.4, color="#2f7d4f"), "50/50 split": dict(lw=1.4, color="#c9a227", ls="--"),
                 "equal-weight universe": dict(lw=1.2, color="#7a7a7a"), "SPY": dict(lw=1.2, color="#222222", ls=":")}
        for k, r in series.items():
            x = r.loc[start:].dropna()
            ax.plot((1 + x).cumprod(), label=k, **style[k])
        ax.axvline(TEST_START, color="#999999", lw=0.8)
        ax.set_yscale("log")
        ax.text(TEST_START, 0.98, "  test period →", transform=ax.get_xaxis_transform(), fontsize=8,
                color="#666666", va="top")
        ax.set_title(run["label"], fontsize=11)
        ax.grid(alpha=0.25)
        ax.legend(fontsize=7.5, loc="upper left")
    np.atleast_1d(axes)[0].set_ylabel("growth of $1, net of costs (log)")
    fig.tight_layout()
    fig.savefig(path, dpi=130)
    plt.close(fig)


# --------------------------------------------------------------------------------------------------
# today's picks
# --------------------------------------------------------------------------------------------------
def picks(ctx, name: str, params: dict) -> pd.DataFrame:
    """What the strategy holds today (weight > 0) plus next-ranked alternates (weight 0, alternate=True)."""
    asof = ctx.dates[-1]
    if name in ("quality_momentum", "momentum_mf"):
        t = (qm if name == "quality_momentum" else mm).live_picks(ctx, params, asof)
        t.attrs = {}
        held = t[t["selected"]]
        alt = t[t["dropped_by"] == "beyond_N"].head(5)
        cols = ["ticker", "name", "gics_sector", "price", "mom_12_1", "mom_score", "sma200_gap", "gpoa", "roe",
                "debt_to_equity", "mf_pct"]
        out = pd.concat([held.assign(alternate=False), alt.assign(alternate=True, weight=0.0)])
        out = out[["rank", "weight", "alternate"] + [c for c in cols if c in out.columns]]
    elif name == "magic_formula":
        t = mf.live_picks(ctx, params, asof)
        t.attrs = {}
        n = int((t["pick"] == "PICK").sum())
        t = t[t["pick"].isin(["PICK", "ALT"])].rename(columns={"yf_ticker": "ticker", "final_rank": "rank"})
        t["weight"] = np.where(t["pick"] == "PICK", 1.0 / max(n, 1), 0.0)
        t["alternate"] = t["pick"] == "ALT"
        cols = ["ticker", "name", "gics_sector", "price_raw", "ey", "roc", "mcap", "mom_12_1"]
        out = t[["rank", "weight", "alternate"] + [c for c in cols if c in t.columns]]
    out = out.reset_index(drop=True)
    out.insert(0, "asof", asof.date())
    return out


def write_picks(ctx, chosen: dict[str, dict]) -> None:
    for name, params in chosen.items():
        p = picks(ctx, name, params)
        p.to_csv(settings.OUTPUT / name / "picks.csv", index=False)
        held = p.loc[~p["alternate"], "ticker"].tolist()
        print(f"{STRATEGIES[name]['label']} ({len(held)}): {', '.join(held)}")


# --------------------------------------------------------------------------------------------------
def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Backtest the three strategies and list today's picks.")
    ap.add_argument("--live-only", action="store_true", help="only recompute today's picks (stored parameters)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")

    from quant.data.context import get_context
    from quant.data import factors as factors_mod
    ctx = get_context()

    if a.live_only:
        write_picks(ctx, json.loads(PARAMS_FILE.read_text()))
        return

    end = last_complete_month_end(ctx)
    rf = monthly_rf(ctx)
    factors = factors_mod.ff_factors_for_regression("M")
    runs = [run_strategy(ctx, name, end, rf, factors) for name in STRATEGIES]
    add_comparison(runs)
    spy = spy_monthly(ctx)

    res = results_table(runs, spy, end, rf, factors)
    res.to_csv(settings.OUTPUT / "results.csv", index=False)
    chart(runs, spy, settings.OUTPUT / "performance.png")
    chosen = {r["name"]: r["chosen"] for r in runs}
    PARAMS_FILE.write_text(json.dumps(chosen, indent=2, default=str) + "\n")
    meta = {r["name"]: dict(fallback=r["fallback"], fallback_reason=r["fallback_reason"],
                            pbo=round(float(r["pbo"]), 3), dsr=round(float(r["dsr"]), 3)) for r in runs}
    (settings.OUTPUT / "selection.json").write_text(json.dumps(meta, indent=2) + "\n")
    from quant import exits
    hs = exits.write_stats(ctx, chosen, end)            # what picks returned under the exit rules

    show = res[res["window"].isin(["train", "test"])].pivot_table(
        index=["strategy", "version"], columns="window", values=["sharpe", "cagr_%"], sort=False)
    print(show.round(2).to_string())
    print(json.dumps(meta, indent=1))
    print(hs[hs["window"] == exits.CLEAN_WINDOW].drop(columns="window").to_string(index=False))
    write_picks(ctx, chosen)


if __name__ == "__main__":
    main()
