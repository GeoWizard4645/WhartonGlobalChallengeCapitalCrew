"""Tests for quant/strategies/quality_momentum.py on a synthetic DataContext (no cache files needed).

The fake context mimics the real one: wide price panels, point-in-time universe with GICS, point-in-time
fundamentals (``filed < date``), split factors.  The real quality module (quant/signals/quality.py) and the real
backtest engine are used, so the tests cover the wiring end to end.
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant.backtest import engine, grid
from quant.signals import quality as Q
from quant.signals import technical as T
from quant.strategies import quality_momentum as qm

N_DAYS = 900
IDX = pd.bdate_range("2015-01-01", periods=N_DAYS)
SECTORS = ["Information Technology", "Health Care", "Industrials", "Consumer Staples", "Financials"]
N_STOCKS = 60


# --------------------------------------------------------------------------------------------------
# synthetic world
# --------------------------------------------------------------------------------------------------
class FakeCtx:
    def __init__(self, close, adjclose, universe, filings, splits=None):
        self.close, self.adjclose = close, adjclose
        self.volume = close * 0 + 1e6
        self.returns = adjclose.pct_change()
        self.rf = pd.Series(0.00005, index=close.index)
        self.dates = close.index
        self.snaps = filings
        self._universe = universe
        self._filings = filings            # DataFrame: cik, filed, period_end, + fundamentals columns
        self._splits = splits or {}
        self.splits = pd.DataFrame([dict(yf_ticker=tk, date=pd.Timestamp(d), ratio=r, genuine=True)
                                    for tk, lst in self._splits.items() for d, r in lst],
                                   columns=["yf_ticker", "date", "ratio", "genuine"])
        self.fund_requests: list[pd.Timestamp] = []

    def trading_day_on_or_before(self, d):
        d = pd.Timestamp(d)
        i = self.dates.searchsorted(d, side="right") - 1
        if i < 0:
            raise ValueError("before first date")
        return self.dates[i]

    def month_ends(self, start, end):
        d = self.dates[(self.dates >= pd.Timestamp(start)) & (self.dates <= pd.Timestamp(end))]
        s = pd.Series(d, index=d)
        return list(s.groupby([d.year, d.month]).max())

    def universe(self, date, name="SP1500"):
        date = self.trading_day_on_or_before(date)
        df = self._universe.copy()
        df = df[df["yf_ticker"].isin(self.close.columns)]
        px = self.close.loc[date, df["yf_ticker"]].to_numpy()
        return df[np.isfinite(px) & (px > 0)].reset_index(drop=True)

    def fundamentals(self, date, max_age_days=200):
        date = pd.Timestamp(date)
        self.fund_requests.append(date)
        f = self._filings
        f = f[(f["filed"] < date) & (f["period_end"] >= date - pd.Timedelta(days=max_age_days))]
        f = f.sort_values("filed").groupby("cik").tail(1).set_index("cik")
        return f

    def split_factor_after(self, ticker, d):
        fac = 1.0
        for sd, ratio in self._splits.get(ticker, []):
            if pd.Timestamp(sd) > pd.Timestamp(d):
                fac *= ratio
        return fac


def make_world(seed=0, n_stocks=N_STOCKS, ret_overrides=None, late_listing=None, price_scale=None,
               bad_ni=(), high_debt=(), splits=None, filing_overrides=None):
    """Random-walk prices (drift rises with the stock number), universe table, quarterly filings."""
    rng = np.random.default_rng(seed)
    tick = [f"S{i:02d}" for i in range(n_stocks)]
    mu = np.array([-0.0004 + 0.0008 * i / (n_stocks - 1) for i in range(n_stocks)])
    r = mu[None, :] + 0.012 * rng.standard_normal((N_DAYS, n_stocks))
    r[0] = 0.0
    spy = 0.0003 + 0.01 * rng.standard_normal(N_DAYS)
    for (tk, lo, hi), val in (ret_overrides or {}).items():
        r[lo:hi, tick.index(tk)] = val
    p0 = np.full(n_stocks, 50.0)
    for tk, s in (price_scale or {}).items():
        p0[tick.index(tk)] = s
    adj = pd.DataFrame(p0[None, :] * np.exp(np.cumsum(r, axis=0)), index=IDX, columns=tick)
    for tk, lo in (late_listing or {}).items():
        adj.loc[adj.index[:lo], tk] = np.nan
    adj["SPY"] = 100 * np.exp(np.cumsum(spy))
    close = adj.copy()                      # no dividends: split-adjusted == total-return adjusted

    ciks = 1000 + np.arange(n_stocks)
    uni = pd.DataFrame({
        "cik": ciks, "yf_ticker": tick, "name": [f"Company {i}" for i in range(n_stocks)],
        "gics_sector": [SECTORS[i % 5] for i in range(n_stocks)],
        "gics_industry_group": [SECTORS[i % 5] + " grp" for i in range(n_stocks)],
        "gics_industry": [SECTORS[i % 5] + " ind" for i in range(n_stocks)],
        "sic": 3570, "index": "SP500"})

    rows = []
    for k, (cik, tk) in enumerate(zip(ciks, tick)):
        for q in range(14):
            filed = pd.Timestamp("2014-11-15") + pd.Timedelta(days=91 * q)
            ni = -50.0 if tk in bad_ni else 100.0
            debt = 1500.0 if tk in high_debt else 100.0
            rows.append(dict(cik=cik, filed=filed, period_end=filed - pd.Timedelta(days=45), assets=1000.0,
                             revenue=800.0, gross_profit=400.0, net_income=ni, cfo=120.0, capex=20.0,
                             total_debt=debt, cash=50.0, equity_parent=500.0, ebitda=150.0, yf_ticker=tk))
    fil = pd.DataFrame(rows)
    for (tk, filed), upd in (filing_overrides or {}).items():
        m = (fil["yf_ticker"] == tk) & (fil["filed"] == pd.Timestamp(filed))
        assert m.any(), (tk, filed)
        for c, v in upd.items():
            fil.loc[m, c] = v
    return FakeCtx(close, adj, uni, fil, splits)


def month_end(ctx, y, m):
    """Last trading day of calendar month (y, m)."""
    first = pd.Timestamp(y, m, 1)
    return ctx.month_ends(first, first + pd.offsets.MonthEnd(0))[-1]


@pytest.fixture(autouse=True)
def _small_world_thresholds(monkeypatch):
    """The synthetic world has ~48 eligible names; the production gate asks for >= 100."""
    monkeypatch.setattr(qm, "MIN_UNIVERSE", 20)


def prm(**kw):
    return dict(qm.DEFAULT, **kw)


# --------------------------------------------------------------------------------------------------
# reference implementation (independent numpy) of the Q0 pipeline
# --------------------------------------------------------------------------------------------------
def rsi_ref(c, n=14):
    c = np.asarray(c, float)
    d = np.diff(c)
    g, l = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    ag, al = g[:n].mean(), l[:n].mean()
    for i in range(n, len(d)):
        ag, al = (ag * (n - 1) + g[i]) / n, (al * (n - 1) + l[i]) / n
    if al == 0:
        return 100.0 if ag > 0 else 50.0
    return 100 - 100 / (1 + ag / al)


def reference_q0(ctx, t, N, technical, order="MF", shortlist=0.2):
    pos = ctx.close.index.get_loc(t)
    u = ctx.universe(t)
    rows = []
    for _, r in u.iterrows():
        if r["gics_sector"] == "Financials":
            continue
        tk = r["yf_ticker"]
        c = ctx.close[tk].to_numpy()
        a = ctx.adjclose[tk].to_numpy()
        first = int(np.argmax(~np.isnan(c)))
        if pos - first + 1 < 253:
            continue
        price = c[pos] * ctx.split_factor_after(tk, t)
        if not price >= 5:
            continue
        win = a[pos - 252: pos - 21 + 1]
        if np.isnan(win).sum() > 0.1 * len(win) or np.isnan(a[pos - 21]) or np.isnan(a[pos - 252]):
            continue
        rows.append(dict(tk=tk, mom=a[pos - 21] / a[pos - 252] - 1, sma_ok=c[pos] > np.nanmean(c[pos - 199: pos + 1]),
                         rsi=rsi_ref(c[first: pos + 1]) if technical == "sma_rsi" else np.nan))
    df = pd.DataFrame(rows).sort_values(["mom", "tk"], ascending=[False, True]).reset_index(drop=True)
    if order == "MF":
        df = df.iloc[: int(np.ceil(shortlist * len(df) - 1e-9))]
    if technical in ("sma", "sma_rsi"):
        df = df[df["sma_ok"]]
    if technical == "sma_rsi":
        df = df[(df["rsi"] >= 50) & (df["rsi"] <= 70)]
    return df["tk"].tolist()


# --------------------------------------------------------------------------------------------------
# grid / params
# --------------------------------------------------------------------------------------------------
def test_grid_shape_default_in_grid_and_json_serializable():
    assert len(qm.GRID) == 216 == 3 * 3 * 3 * 2 * 4
    assert qm.DEFAULT in qm.GRID
    assert len({json.dumps(c, sort_keys=True) for c in qm.GRID}) == 216
    json.dumps(qm.GRID)
    assert qm.DEFAULT == dict(order="MF", shortlist=0.2, x_debt=1.0, N=10, quality="Q3a", technical="sma_rsi",
                              stop_loss="none", vol_target="none")
    assert qm.AXES == {"N": [5, 10, 20], "stop_loss": ["none", 0.15, 0.10]}
    assert qm.CATEGORICAL["quality"] == ["Q0", "Q3a", "Q1-50", "Q2-Q50"]


def test_preregister_roundtrip_and_run_grid_accepts_the_registered_cells(tmp_path):
    path = qm.register(out_dir=tmp_path)
    doc = json.loads(path.read_text())
    assert doc["n_cells"] == 216 and doc["default"] == qm.DEFAULT
    assert grid.grid_hash(qm.GRID) == doc["grid_hash"]
    assert qm.register(out_dir=tmp_path) == path                 # idempotent
    lay = grid._Layout.build(qm.GRID, qm.AXES, qm.CATEGORICAL, qm.DEFAULT)
    assert lay.default_pos is not None


def test_params_normalisation_and_validation():
    p = qm._params({"stop_loss": None, "vol_target": "none", "N": 7})
    assert p["stop_loss"] is None and p["vol_target"] is None and p["N"] == 7
    p = qm._params({"stop_loss": 0.15, "vol_target": 0.2})
    assert p["stop_loss"] == 0.15 and p["vol_target"] == 0.2
    for bad in ({"technical": "rsi"}, {"order": "XX"}, {"quality": "Q9"}, {"nonsense": 1}, {"N": 0},
                {"shortlist": 0.0}):
        with pytest.raises(ValueError):
            qm._params(bad)


# --------------------------------------------------------------------------------------------------
# pipeline vs independent reference (Q0 control, no fundamentals involved)
# --------------------------------------------------------------------------------------------------
@pytest.mark.parametrize("technical", ["none", "sma", "sma_rsi"])
@pytest.mark.parametrize("order", ["MF", "QF"])
def test_signal_matches_independent_reference_q0(technical, order):
    ctx = make_world(seed=3)
    for t in [month_end(ctx, 2016, 6), month_end(ctx, 2017, 3), month_end(ctx, 2017, 11)]:
        p = qm._params(prm(quality="Q0", technical=technical, order=order, N=10))
        got = qm._signal(ctx, t, p)["tickers"]
        want = reference_q0(ctx, t, 10, technical, order)
        assert got == want, (t, technical, order)


def test_eligibility_financials_price_history_and_split_adjustment():
    """S03: split-adjusted close ~$3 but a 4:1 split happens AFTER t, so the price at t was ~$13 -> eligible.
    S06: split-adjusted ~$22 but a 1:10 reverse split happens after t, so the price at t was ~$2.2 -> excluded.
    S09 is a Financial (i % 5 == 4), S10 lists late (< 253 days of history at t), S12 trades at ~$3 throughout."""
    split_row = 800
    splits = {"S03": [(IDX[split_row], 4.0)], "S06": [(IDX[split_row], 0.1)]}
    ctx = make_world(seed=1, late_listing={"S10": 500}, splits=splits)
    ramp = 1 + 0.0002 * np.arange(N_DAYS)
    for tk, level in (("S03", 3.0), ("S06", 22.0), ("S12", 3.0)):
        ctx.close[tk] = level * ramp
        ctx.adjclose[tk] = ctx.close[tk]
    ctx.returns = ctx.adjclose.pct_change()
    t = month_end(ctx, 2016, 12)
    pos = ctx.close.index.get_loc(t)
    assert pos < split_row and pos - 500 + 1 < 253
    assert ctx.close.loc[t, "S03"] < 5 <= ctx.close.loc[t, "S03"] * 4
    assert ctx.close.loc[t, "S06"] > 5 > ctx.close.loc[t, "S06"] * 0.1
    F = qm._frame(ctx, t)
    names = set(F["yf_ticker"])
    assert "S03" in names                 # raw price >= 5 although the split-adjusted close is < 5
    assert "S06" not in names             # raw price < 5 although the split-adjusted close is > 5
    assert "S09" not in names             # Financials
    assert "S10" not in names             # too little history
    assert "S12" not in names             # $3 stock
    assert F.attrs["n_fin"] < F.attrs["n_sp1500"]
    assert F["mom"].notna().all()
    assert list(F["mom_rank"]) == list(range(1, len(F) + 1))
    assert F["mom"].is_monotonic_decreasing


def test_price_floor_uses_all_yahoo_adjustments_including_non_genuine_splits():
    """Yahoo back-adjusts prices for spin-off "splits" (ratio 2.044) too; the share-count factor of the context
    ignores them, but the $5 floor must restore the price actually quoted on t."""
    ctx = make_world(seed=1, splits={"S03": [(IDX[800], 2.0)]})
    ramp = 1 + 0.0002 * np.arange(N_DAYS)
    ctx.close["S03"] = 2.6 * ramp                       # ~$2.9 at t; x2.044 -> ~$5.9 as traded, genuine-only -> 2.9
    ctx.adjclose["S03"] = ctx.close["S03"]
    ctx.returns = ctx.adjclose.pct_change()
    ctx.splits = pd.DataFrame([dict(yf_ticker="S03", date=IDX[800], ratio=2.044, genuine=False)])
    ctx.split_factor_after = lambda tk, d: 1.0          # the context's genuine-only share-count factor
    t = month_end(ctx, 2016, 12)
    assert ctx.close.loc[t, "S03"] < 5 <= ctx.close.loc[t, "S03"] * 2.044
    qm.clear_cache(ctx)
    assert "S03" in set(qm._frame(ctx, t)["yf_ticker"])


# --------------------------------------------------------------------------------------------------
# filters: each rule removes the planted name
# --------------------------------------------------------------------------------------------------
def test_technical_filters_remove_planted_names_and_q0_keeps_them():
    base = make_world(seed=5)
    t = month_end(base, 2017, 3)
    pos = base.close.index.get_loc(t)
    # three highest-drift non-financials get planted short-term paths (all inside the skipped month / last 14 days
    # so their 12-1 momentum is unchanged)
    over = {("S58", pos - 9, pos + 1): 0.03,       # RSI far above 70 (very hot last 10 days)
            ("S57", pos - 20, pos + 1): -0.03,     # collapses below the 200-day average in the skip month
            ("S56", pos - 13, pos + 1): -0.004}    # mild 14-day slide: above SMA200 but RSI < 50
    ctx = make_world(seed=5, ret_overrides=over)
    mom_new = T.mom_12_1(ctx.adjclose).loc[t]
    mom_old = T.mom_12_1(base.adjclose).loc[t]
    for tk in ("S58", "S57", "S56"):                 # momentum untouched (changes sit inside the skipped month)
        assert mom_new[tk] == pytest.approx(mom_old[tk], rel=1e-9)
    F = qm._frame(ctx, t)
    row = F.set_index("yf_ticker")
    assert row.loc["S58", "rsi14"] > 70
    assert row.loc["S57", "close"] < row.loc["S57", "sma200"]
    assert row.loc["S56", "close"] > row.loc["S56", "sma200"] and row.loc["S56", "rsi14"] < 50

    # pipeline with N large so the cap does not matter; order QF so the shortlist does not hide them
    kw = dict(quality="Q0", order="QF", N=40)
    none = qm._signal(ctx, t, qm._params(prm(technical="none", **kw)))["tickers"]
    sma = qm._signal(ctx, t, qm._params(prm(technical="sma", **kw)))["tickers"]
    both = qm._signal(ctx, t, qm._params(prm(technical="sma_rsi", **kw)))["tickers"]
    for tk in ("S58", "S57", "S56"):
        assert tk in none
    assert "S57" not in sma and "S58" in sma and "S56" in sma
    assert "S57" not in both and "S58" not in both and "S56" not in both
    assert set(both) <= set(sma) <= set(none)


def test_quality_q3a_removes_loss_makers_and_high_debt_names_and_q0_does_not():
    ctx = make_world(seed=7, bad_ni=("S58",), high_debt=("S57",))
    t = month_end(ctx, 2017, 3)
    kw = dict(technical="none", order="QF", N=40)
    q0 = qm._signal(ctx, t, qm._params(prm(quality="Q0", **kw)))["tickers"]
    q3 = qm._signal(ctx, t, qm._params(prm(quality="Q3a", **kw)))["tickers"]
    assert {"S58", "S57"} <= set(q0)
    assert "S58" not in q3 and "S57" not in q3
    assert set(q3) == set(q0) - {"S58", "S57"}                    # everyone else is "good" in this world
    # the order of the survivors is still by momentum
    F = qm._frame(ctx, t).set_index("yf_ticker")
    assert [F.loc[tk, "mom"] for tk in q3] == sorted([F.loc[tk, "mom"] for tk in q3], reverse=True)


def test_order_mf_shortlists_before_quality_qf_after():
    """MF: top 20% by momentum first, so quality-filtering the shortlist can leave FEWER than N names; QF takes
    the best N among ALL quality names."""
    bad = tuple(f"S{i:02d}" for i in range(40, 60) if i % 5 != 4)         # all top-drift non-financials lose money
    ctx = make_world(seed=11, bad_ni=bad)
    t = month_end(ctx, 2017, 3)
    F = qm._frame(ctx, t)
    k = int(np.ceil(0.2 * len(F)))
    shortlist = set(F["yf_ticker"].iloc[:k])
    mf = qm._signal(ctx, t, qm._params(prm(quality="Q3a", technical="none", order="MF", N=10)))
    qf = qm._signal(ctx, t, qm._params(prm(quality="Q3a", technical="none", order="QF", N=10)))
    assert mf["n_shortlist"] == k
    assert set(mf["tickers"]) <= shortlist
    assert not set(mf["tickers"]) & set(bad)
    assert set(qf["tickers"]) >= set(mf["tickers"])
    assert len(qf["tickers"]) >= len(mf["tickers"])
    assert qf["n_shortlist"] == len(F)


def test_no_backfill_fewer_than_n_hold_survivors_at_1_over_n_and_rest_is_cash():
    # N = 20 but the quality arm leaves only a handful inside the MF shortlist
    ctx = make_world(seed=2, bad_ni=tuple(f"S{i:02d}" for i in range(0, 60, 2)))
    dates = [month_end(ctx, 2016, 9), month_end(ctx, 2017, 3)]
    p = prm(quality="Q3a", technical="sma_rsi", N=20)
    sg = [qm._signal(ctx, d, qm._params(p)) for d in dates]
    assert all(s["n_tech"] < 20 for s in sg)
    tw = qm.target_weights(ctx, p, dates)
    for d, s in zip(dates, sg):
        row = tw.loc[d]
        assert (row > 0).sum() == s["n_tech"]
        assert row[row > 0].eq(1 / 20).all()
        assert row.sum() == pytest.approx(s["n_tech"] / 20) and row.sum() < 1
    dg = qm.diagnostics(ctx, p, dates=dates)
    assert (dg["n_held"] == [s["n_tech"] for s in sg]).all()
    assert dg["cash_weight"].tolist() == pytest.approx([1 - s["n_tech"] / 20 for s in sg])


def test_target_weights_full_book_equal_weight_and_columns():
    ctx = make_world(seed=4)
    dates = ctx.month_ends("2016-03-01", "2017-06-30")
    tw = qm.target_weights(ctx, prm(quality="Q0", technical="none", N=10), dates)
    assert list(tw.index) == dates
    assert (tw.sum(axis=1) <= 1 + 1e-12).all()
    assert (tw.gt(0).sum(axis=1) == 10).all()
    assert tw.max().max() == pytest.approx(0.1)
    assert all(c in ctx.close.columns for c in tw.columns)
    tw5 = qm.target_weights(ctx, prm(quality="Q0", technical="none", N=5), dates)
    for d in dates:                                              # N is a pure slice of the same ranking
        assert set(tw5.loc[d][tw5.loc[d] > 0].index) <= set(tw.loc[d][tw.loc[d] > 0].index)


# --------------------------------------------------------------------------------------------------
# no look-ahead
# --------------------------------------------------------------------------------------------------
def test_signals_at_t_ignore_prices_after_t_and_filings_filed_on_or_after_t():
    t = month_end(make_world(seed=9), 2017, 3)
    # (1) future prices garbage after t
    ctx_a = make_world(seed=9, bad_ni=("S58",))
    ctx_b = make_world(seed=9, bad_ni=("S58",))
    pos = ctx_b.close.index.get_loc(t)
    rng = np.random.default_rng(0)
    junk = 1 + 0.5 * rng.standard_normal((N_DAYS - pos - 1, ctx_b.close.shape[1]))
    ctx_b.close.iloc[pos + 1:] = ctx_b.close.iloc[pos + 1:] * np.abs(junk)
    ctx_b.adjclose.iloc[pos + 1:] = ctx_b.close.iloc[pos + 1:]
    ctx_b.returns = ctx_b.adjclose.pct_change()
    # (2) fundamentals filed on/after t flip every company to a loss maker
    mask = ctx_b._filings["filed"] >= t
    ctx_b._filings = ctx_b._filings.copy()
    ctx_b._filings.loc[mask, "net_income"] = -999.0
    p = qm._params(prm(quality="Q3a", technical="sma_rsi", N=10))
    a = qm._signal(ctx_a, t, p)
    b = qm._signal(ctx_b, t, p)
    assert a["tickers"] == b["tickers"] and len(a["tickers"]) > 0
    assert (a["n_universe"], a["n_shortlist"], a["n_quality"], a["n_tech"]) == (b["n_universe"], b["n_shortlist"], b["n_quality"], b["n_tech"])
    assert max(ctx_a.fund_requests) <= t and max(ctx_b.fund_requests) <= t     # never asked for a later date


def test_filing_filed_exactly_on_signal_date_is_not_used_but_is_used_next_month():
    ctx0 = make_world(seed=13)
    filings = ctx0._filings
    # pick a month-end t and make S58's filing land exactly on t with a loss
    t = month_end(ctx0, 2017, 3)
    # shift S58's filing schedule so one filing is filed exactly on t
    f58 = filings[filings["yf_ticker"] == "S58"]["filed"]
    cand = f58[(f58 <= t)].max()
    shift = t - cand
    ctx = make_world(seed=13)
    m = ctx._filings["yf_ticker"] == "S58"
    ctx._filings.loc[m, "filed"] = ctx._filings.loc[m, "filed"] + shift
    ctx._filings.loc[m, "period_end"] = ctx._filings.loc[m, "period_end"] + shift
    m_t = m & (ctx._filings["filed"] == t)
    assert m_t.any()
    ctx._filings.loc[m_t, "net_income"] = -100.0
    p = qm._params(prm(quality="Q3a", technical="none", order="QF", N=40))
    on_t = qm._signal(ctx, t, p)["tickers"]
    nxt = ctx.dates[ctx.dates.get_loc(t) + 1]
    next_day = qm._signal(ctx, nxt, p)["tickers"]
    assert "S58" in on_t                    # filed == t is not yet usable (strictly earlier filings only)
    assert "S58" not in next_day            # usable the day after


def test_technicals_cache_panel_is_causal_for_the_strategy_frame():
    ctx_full = make_world(seed=21)
    t = month_end(ctx_full, 2016, 10)
    cut = make_world(seed=21)
    pos = cut.close.index.get_loc(t)
    for name in ("close", "adjclose", "volume", "returns"):
        setattr(cut, name, getattr(cut, name).iloc[: pos + 1])
    cut.dates = cut.close.index
    a = qm._frame(ctx_full, t)
    b = qm._frame(cut, t)
    pd.testing.assert_frame_equal(a, b)


# --------------------------------------------------------------------------------------------------
# caching
# --------------------------------------------------------------------------------------------------
def test_signal_frames_and_quality_tables_are_reused_across_cells(monkeypatch):
    ctx = make_world(seed=6)
    calls = {"n": 0}
    real = Q.quality_table

    def counting(*a, **k):
        calls["n"] += 1
        return real(*a, **k)
    monkeypatch.setattr(Q, "quality_table", counting)
    dates = ctx.month_ends("2016-06-01", "2016-12-31")          # 7 month-ends
    cells = [prm(N=n, stop_loss=sl, vol_target=vt, quality=q)
             for n in (5, 10, 20) for sl in ("none", 0.1) for vt in ("none", 0.2) for q in ("Q3a", "Q1-50", "Q2-Q50")]
    for c in cells:
        qm.target_weights(ctx, c, dates)
    assert calls["n"] == len(dates)                              # ONE quality table per date for every arm / cell
    n_sig = len(qm._cache(ctx)["sig"])
    for c in cells:
        qm.target_weights(ctx, c, dates)
    assert len(qm._cache(ctx)["sig"]) == n_sig and calls["n"] == len(dates)
    assert n_sig == len(dates) * 3                               # 3 arms (N / stop / vol are slices & engine config)


def test_q0_does_not_touch_fundamentals():
    ctx = make_world(seed=6)
    qm.target_weights(ctx, prm(quality="Q0", technical="sma_rsi"), ctx.month_ends("2016-06-01", "2016-08-31"))
    assert ctx.fund_requests == []


# --------------------------------------------------------------------------------------------------
# backtest wiring
# --------------------------------------------------------------------------------------------------
def test_backtest_timing_window_and_holdings():
    ctx = make_world(seed=8)
    start, end = pd.Timestamp("2016-06-01"), pd.Timestamp("2017-03-31")
    res = qm.backtest(ctx, prm(quality="Q0", technical="none", N=10), start, end, cost_bps=10, common_start=False)
    sig_dates = ctx.month_ends(start, end)
    assert res.daily.index[0] == ctx.dates[ctx.dates.get_loc(sig_dates[0]) + 1]          # trade at close of t+1
    assert res.daily.index[-1] <= end                                                    # nothing after `end`
    # the last signal (2017-03-31) cannot trade inside the window
    assert res.trades["date"].max() <= end
    reb = res.daily[res.daily["rebalance"]]
    assert len(reb) == len(sig_dates) - 1
    assert (reb["n_holdings"] == 10).all()
    assert res.daily["ret_net"].notna().all()
    assert (reb["cost"] > 0).all()
    # first rebalance is a 100% one-way entry
    assert reb["turnover"].iloc[0] == pytest.approx(1.0)
    assert (reb["turnover"].iloc[1:] < 1.0).all()


def test_backtest_matches_manual_engine_run():
    ctx = make_world(seed=8)
    p = prm(quality="Q3a", technical="sma_rsi", N=10)
    start, end = pd.Timestamp("2016-06-01"), pd.Timestamp("2017-06-30")
    res = qm.backtest(ctx, p, start, end, common_start=False)
    dates = ctx.month_ends(start, end)
    tw = qm.target_weights(ctx, p, dates)
    ref = engine.run(tw, ctx.returns.loc[:end], ctx.rf, engine.BacktestConfig(cost_bps=10.0))
    pd.testing.assert_series_equal(res.daily["ret_net"], ref.daily["ret_net"])


def test_stop_loss_and_vol_target_are_passed_to_the_engine():
    ctx = make_world(seed=8)
    start, end = "2016-06-01", "2017-06-30"
    a = qm.backtest(ctx, prm(quality="Q0", technical="none", N=10, vol_target=0.05), start, end, common_start=False)
    assert (a.daily["vol_scalar"] < 1.0).any()
    assert a.daily["exposure"].max() <= 1.0 + 1e-9
    b = qm.backtest(ctx, prm(quality="Q0", technical="none", N=10, stop_loss=0.02), start, end, common_start=False)
    assert (b.trades["reason"] == "stop").any()
    c = qm.backtest(ctx, prm(quality="Q0", technical="none", N=10), start, end, common_start=False)
    assert (c.trades["reason"] != "stop").all() and (c.daily["vol_scalar"] == 1.0).all()


def test_trend_exit_daily_option_reaches_the_engine():
    ctx = make_world(seed=8)
    r = qm.backtest(ctx, dict(prm(quality="Q0", technical="none", N=10), trend_exit_daily=True),
                    "2016-06-01", "2017-06-30", common_start=False)
    assert (r.trades["reason"] == "trend").any()
    r0 = qm.backtest(ctx, prm(quality="Q0", technical="none", N=10), "2016-06-01", "2017-06-30", common_start=False)
    assert (r0.trades["reason"] != "trend").all()


def test_vol_scalar_in_live_picks_equals_engine_scalar():
    ctx = make_world(seed=8)
    p = prm(quality="Q0", technical="none", N=10, vol_target=0.05)
    t = month_end(ctx, 2017, 3)
    lp = qm.live_picks(ctx, p, t)
    res = qm.backtest(ctx, p, "2016-06-01", "2017-06-30", common_start=False)
    trade_day = ctx.dates[ctx.dates.get_loc(t) + 1]
    assert res.daily.loc[trade_day, "vol_scalar"] == pytest.approx(lp.attrs["vol_scalar"], rel=1e-12)
    assert lp.attrs["vol_scalar"] < 1.0 and lp.attrs["book_vol"] > 0.05
    sel = lp[lp["selected"]]
    assert sel["weight_after_vol"].sum() == pytest.approx(lp.attrs["vol_scalar"])


def test_first_signal_date_waits_for_fundamentals_coverage():
    ctx = make_world(seed=10)
    # no filings before 2016-04-01: coverage only starts when the first filing is out
    ctx._filings = ctx._filings[ctx._filings["filed"] >= pd.Timestamp("2016-04-01")].copy()
    d = qm.first_signal_date(ctx, "2015-06-01", min_coverage=0.7, min_universe=20)

    def coverage(t):
        F = qm._frame(ctx, t)
        return F["cik"].isin(ctx.fundamentals(t).index).mean()
    months = ctx.month_ends("2015-06-01", d)
    assert months[-1] == d and coverage(d) >= 0.7 and all(len(qm._frame(ctx, m)) < 20 or coverage(m) < 0.7
                                                                               for m in months[:-1])
    assert d > ctx._filings["filed"].min()
    # backtest() starts there for every quality arm (common start), whatever the arm needs
    r0 = qm.backtest(ctx, prm(quality="Q0", technical="none"), "2015-06-01", "2017-01-31")
    r3 = qm.backtest(ctx, prm(quality="Q3a", technical="none"), "2015-06-01", "2017-01-31")
    assert r0.daily.index[0] == r3.daily.index[0] == ctx.dates[ctx.dates.get_loc(d) + 1]
    # opting out keeps the requested start
    early = qm.backtest(ctx, prm(quality="Q0", technical="none"), "2015-12-01", "2017-01-31", common_start=False)
    assert early.daily.index[0] < r0.daily.index[0]


def test_month_complete_rule():
    assert qm._month_complete(pd.Timestamp("2018-12-31"))
    assert qm._month_complete(pd.Timestamp("2018-03-29"))        # Good Friday 2018-03-30 closed
    assert qm._month_complete(pd.Timestamp("2021-05-28"))        # Memorial Day 2021-05-31 closed
    assert not qm._month_complete(pd.Timestamp("2026-10-27"))
    assert not qm._month_complete(pd.Timestamp("2026-10-16"))
    assert qm._month_complete(pd.Timestamp("2026-10-30"))


def test_monthly_returns_is_monthly_net_and_drops_a_partial_last_month():
    ctx = make_world(seed=12)
    p = prm(quality="Q0", technical="none")
    full_month = month_end(ctx, 2017, 6)
    m_full = qm.monthly_returns(p, ctx=ctx, start="2016-03-01", end=full_month)
    assert m_full.index.is_monotonic_increasing and m_full.notna().all()
    assert m_full.index[-1] == pd.Timestamp(full_month.year, full_month.month, 30)          # June is complete
    m_mid = qm.monthly_returns(p, ctx=ctx, start="2016-03-01", end=pd.Timestamp("2017-06-15"))
    assert m_mid.index[-1] == pd.Timestamp("2017-05-31")                                    # partial June dropped
    pd.testing.assert_series_equal(m_mid, m_full.iloc[:-1])
    assert (m_full.abs() < 0.5).all()
    ref = qm.backtest(ctx, p, "2016-03-01", full_month).monthly()
    pd.testing.assert_series_equal(m_full, ref)


# --------------------------------------------------------------------------------------------------
# diagnostics / live picks
# --------------------------------------------------------------------------------------------------
def test_diagnostics_funnel_is_monotone_and_consistent():
    ctx = make_world(seed=14, bad_ni=("S58", "S55"))
    dg = qm.diagnostics(ctx, prm(), start="2016-03-01", end="2017-06-30", common_start=False)
    assert list(dg.columns) == ["n_sp1500", "n_universe", "n_shortlist", "n_quality", "n_tech", "n_held", "cash_weight"]
    assert (dg["n_sp1500"] >= dg["n_universe"]).all()
    assert (dg["n_universe"] >= dg["n_shortlist"]).all() and (dg["n_shortlist"] >= dg["n_quality"]).all()
    assert (dg["n_quality"] >= dg["n_tech"]).all()
    assert (dg["n_held"] == dg["n_tech"].clip(upper=10)).all()
    assert dg["cash_weight"].tolist() == pytest.approx((1 - dg["n_held"] / 10).tolist())


def test_live_picks_table_has_every_input_and_matches_target_weights():
    ctx = make_world(seed=15, bad_ni=("S58",))
    t = month_end(ctx, 2017, 3)
    p = prm(quality="Q3a", technical="none", N=10)
    lp = qm.live_picks(ctx, p, t)
    tw = qm.target_weights(ctx, p, [t]).loc[t]
    sel = lp[lp["selected"]]
    assert set(sel["ticker"]) == set(tw[tw > 0].index)
    assert sel["rank"].tolist() == list(range(1, len(sel) + 1))                  # selected first, in rank order
    assert sel["weight"].eq(0.1).all() and lp.loc[~lp["selected"], "weight"].eq(0).all()
    for c in ("ticker", "name", "gics_sector", "mom_12_1", "sma200", "sma200_gap", "rsi14", "gpoa", "roe",
              "debt_to_equity", "nd_ebitda", "pass_quality", "pass_sma200", "pass_rsi", "rank", "weight",
              "dropped_by", "filed", "period_end"):
        assert c in lp.columns, c
    assert lp.attrs["funnel"]["n_held"] == len(sel)
    assert set(lp.attrs["dropped"]) == {"quality", "sma200", "rsi", "beyond_N"}
    # the planted loss maker, if it is in the shortlist, is listed as dropped by quality
    if "S58" in set(lp["ticker"]):
        assert "S58" in set(lp.attrs["dropped"]["quality"]["ticker"])
    assert lp.attrs["vol_scalar"] == 1.0


def test_live_picks_default_asof_is_latest_and_lists_dropped_names_by_filter():
    ctx = make_world(seed=16)
    lp = qm.live_picks(ctx, prm(quality="Q0", technical="sma_rsi", N=5))
    assert lp.attrs["asof"] == ctx.dates[-1]
    dr = lp.attrs["dropped"]
    n_by = {k: len(v) for k, v in dr.items()}
    assert sum(n_by.values()) + lp.attrs["n_held"] == len(lp)          # every row is selected or dropped by one filter
    assert (lp.loc[lp["selected"], "dropped_by"] == "").all()


# --------------------------------------------------------------------------------------------------
# blend arm
# --------------------------------------------------------------------------------------------------
def test_blend_arm_ranks_by_blend_score_not_momentum():
    ctx = make_world(seed=17)
    # make gross profitability anti-correlated with the stock number so the blend reshuffles the order
    f = ctx._filings
    f["gross_profit"] = 100.0 + 5.0 * (59 - (f["cik"] - 1000))
    t = month_end(ctx, 2017, 3)
    p = qm._params(prm(quality="Q4-0.5", technical="none", N=10))
    sg = qm._signal(ctx, t, p)
    F = qm._frame(ctx, t).set_index("yf_ticker")
    assert len(sg["tickers"]) > 10
    mom_order = [tk for tk in F.index if tk in set(sg["tickers"])]
    assert sg["tickers"] != mom_order
    pure_mom = qm._signal(ctx, t, qm._params(prm(quality="Q4-0.25", technical="none", N=10)))["tickers"]
    assert pure_mom != sg["tickers"]
