"""Momentum + Magic Formula: momentum picks the stocks, the Magic Formula vetoes some of them.

Momentum stays the guide. Candidates are exactly the quality-momentum strategy's: residual 12-1 momentum
(Blitz, Huij & Martens 2011), the top 20% of the universe by momentum, and the Novy-Marx gross-profitability
screen, ranked by momentum. The Magic Formula then removes candidates it rates as poor businesses or poor value:
  * EBIT, enterprise value or invested capital not positive, or
  * a combined return-on-capital + earnings-yield rank in the worst ``mf_cut`` of the S&P 500 + MidCap 400
    (ranked over every stock above the doc's $50M floor; financials, real estate and utilities, which the formula
    cannot judge, are not vetoed).
The top N survivors are held at equal weight and rebalanced monthly. If fewer than N survive, the rest stays in
cash: the gap is never filled with weaker-momentum names.

Grid (pre-registered with ``register()`` before any run): veto strength ``mf_cut`` in {0, 25%, 50%, 75%}
(0 = only veto non-positive EBIT / EV / capital) x N in {10, 20, 30}. Default = the design as proposed:
mf_cut 50%, N 20.
"""
from __future__ import annotations

import itertools

import pandas as pd

from quant.backtest import grid
from quant.strategies import magic_formula as mf
from quant.strategies import quality_momentum as qm

STRATEGY = "momentum_mf"

# the quality-momentum strategy's selected (v2) settings: the merged strategy starts from these candidates
BASE: dict = dict(qm.FIXED, quality="Q1-50", technical="none", mom_type="residual")

AXES: dict = {"mf_cut": [0.0, 0.25, 0.5, 0.75], "N": [10, 20, 30]}     # ordinal: veto strength, holdings
CATEGORICAL: dict = {}
DEFAULT: dict = dict(BASE, mf_cut=0.5, N=20)
GRID: list[dict] = [dict(BASE, mf_cut=c, N=n) for c, n in itertools.product(AXES["mf_cut"], AXES["N"])]


def register(force: bool = False, out_dir=None):
    """Write ``output/momentum_mf/preregistration.json`` before any run (idempotent; refuses a changed grid)."""
    extra = dict(description="momentum leads (quality-momentum v2 candidates), Magic Formula vetoes; monthly, "
                             "top-N equal weight, point-in-time S&P 900",
                 veto="EBIT/EV/capital <= 0, or combined ROC+EY rank in the worst mf_cut of the universe "
                      "(min cap $50M, no momentum filter); stocks MF cannot rank are not vetoed")
    return grid.preregister(STRATEGY, GRID, axes=AXES, categorical=CATEGORICAL, default=DEFAULT,
                            force=force, out_dir=out_dir, extra=extra)


def first_signal_date(ctx):
    return qm.first_signal_date(ctx)


def target_weights(ctx, params: dict, dates) -> pd.DataFrame:
    return qm.target_weights(ctx, dict(DEFAULT, **(params or {})), dates)


def backtest(ctx, params: dict, start=qm.START, end=None, cost_bps: float = 10.0, **kw):
    return qm.backtest(ctx, dict(DEFAULT, **(params or {})), start, end, cost_bps, **kw)


def monthly_returns(params: dict, ctx=None, start=qm.START, end=None, cost_bps: float = 10.0) -> pd.Series:
    return qm.monthly_returns(dict(DEFAULT, **(params or {})), ctx=ctx, start=start, end=end, cost_bps=cost_bps)


def live_picks(ctx, params: dict, asof=None) -> pd.DataFrame:
    """The quality-momentum live table with the Magic Formula verdict added (mf_pct: 0 = best, mf_bad)."""
    p = dict(DEFAULT, **(params or {}))
    t = qm.live_picks(ctx, p, asof)
    scr = mf.screen(ctx, t.attrs["asof"])
    v = scr.reindex(pd.to_numeric(t["cik"], errors="coerce").to_numpy())
    t["mf_pct"] = v["mf_pct"].to_numpy()
    t["mf_bad"] = v["mf_bad"].to_numpy()
    return t
