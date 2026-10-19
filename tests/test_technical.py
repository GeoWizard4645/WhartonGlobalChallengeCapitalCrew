"""Tests for quant/signals/technical.py (synthetic prices, hand-computed expectations)."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.signals import technical as T


def _idx(n, start="2015-01-01"):
    return pd.bdate_range(start, periods=n)


def _frame(cols: dict, n=None):
    n = n or max(len(v) for v in cols.values())
    idx = _idx(n)
    data = {}
    for k, v in cols.items():
        arr = np.full(n, np.nan)
        arr[: len(v)] = v
        data[k] = arr
    return pd.DataFrame(data, index=idx)


# --------------------------------------------------------------------------------------------------
# RSI
# --------------------------------------------------------------------------------------------------
def test_rsi_hand_computed_n3():
    """closes 10, 11, 10.5, 11.5, 11, 12 with n=3.

    changes +1, -.5, +1, -.5, +1.  Seed (first 3): avg_gain = 2/3, avg_loss = 1/6 -> RS 4 -> RSI 80.
    Next (-.5): ag = (2/3*2 + 0)/3 = 4/9, al = (1/6*2 + .5)/3 = 5/18 -> RS 1.6 -> RSI 61.538...
    Next (+1):  ag = (4/9*2 + 1)/3 = 17/27, al = 5/18*2/3 = 5/27 -> RS 3.4 -> RSI 77.2727...
    """
    r = T.rsi_wilder(pd.Series([10, 11, 10.5, 11.5, 11, 12.0]), 3)
    assert np.isnan(r.iloc[:3]).all()
    assert r.iloc[3] == pytest.approx(80.0, abs=1e-12)
    assert r.iloc[4] == pytest.approx(100 - 100 / 2.6, abs=1e-12)
    assert r.iloc[5] == pytest.approx(100 - 100 / (1 + 3.4), abs=1e-12)


def test_rsi_published_wilder_example():
    """The widely reproduced 14-period worked example (full-precision closes); first RSI 70.53, then 66.32 ..."""
    closes = [44.3389, 44.0902, 44.1497, 43.6124, 44.3278, 44.8264, 45.0955, 45.4245, 45.8433, 46.0826, 45.8931,
              46.0328, 45.6140, 46.2820, 46.2820, 46.0028, 46.0328, 46.4116, 46.2222, 45.6439, 46.2122, 46.2521,
              45.7137, 46.4515, 45.7835, 45.3548, 44.0288, 44.1783, 44.2181, 44.5672, 43.4205, 42.6628, 43.1314]
    expected = [70.53, 66.32, 66.55, 69.41, 66.36, 57.97, 62.93, 63.26, 56.06, 62.38, 54.71, 50.42, 39.99, 41.46,
                41.87, 45.46, 37.30, 33.08, 37.77]
    r = T.rsi_wilder(pd.Series(closes), 14)
    assert np.isnan(r.iloc[:14]).all()
    np.testing.assert_allclose(r.iloc[14:].to_numpy(), expected, atol=0.006)


def _rsi_scalar(close, n):
    """Independent scalar implementation (research/01 §6.1 listing)."""
    close = np.asarray(close, float)
    d = np.diff(close)
    gain, loss = np.where(d > 0, d, 0.0), np.where(d < 0, -d, 0.0)
    out = np.full(len(close), np.nan)
    ag, al = gain[:n].mean(), loss[:n].mean()

    def f(ag, al):
        return (100.0 if ag > 0 else 50.0) if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    out[n] = f(ag, al)
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + gain[i]) / n
        al = (al * (n - 1) + loss[i]) / n
        out[i + 1] = f(ag, al)
    return out


def test_rsi_matches_scalar_reference_on_random_walks_with_late_starts():
    rng = np.random.default_rng(1)
    n = 400
    base = 100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=(n, 3)), axis=0))
    start = [0, 37, 120]
    df = pd.DataFrame(base, index=_idx(n), columns=list("ABC"))
    for j, s in enumerate(start):
        df.iloc[:s, j] = np.nan
    out = T.rsi_wilder(df, 14)
    for j, s in enumerate(start):
        ref = np.full(n, np.nan)
        ref[s:] = _rsi_scalar(base[s:, j], 14)
        np.testing.assert_allclose(out.iloc[:, j].to_numpy(), ref, rtol=0, atol=1e-9, equal_nan=True)


def test_rsi_all_up_is_100_flat_is_50_all_down_is_0():
    up = pd.Series(np.arange(1.0, 31.0))
    flat = pd.Series(np.full(30, 5.0))
    down = pd.Series(np.arange(30.0, 0.0, -1.0))
    assert T.rsi_wilder(up, 14).iloc[-1] == 100.0          # avg_loss == 0 -> 100
    assert T.rsi_wilder(flat, 14).iloc[-1] == 50.0         # both averages zero
    assert T.rsi_wilder(down, 14).iloc[-1] == 0.0


def test_rsi_missing_row_is_nan_and_next_change_is_vs_last_valid():
    c = np.array([10, 11, 10.5, 11.5, 11, 12.0, 11.0])
    full = T.rsi_wilder(pd.Series(c), 3)
    gap = c.copy().astype(float)
    gap[5] = np.nan                                         # row 5 missing
    out = T.rsi_wilder(pd.Series(gap), 3)
    assert np.isnan(out.iloc[5])
    # row 6 compares 11.0 with the last valid close (11.5 is row 3; 11.0 is row 4): change = 11.0 - 11.0 = 0
    ag, al = 4 / 9, 5 / 18
    ag, al = ag * 2 / 3, al * 2 / 3                         # zero change -> pure decay
    assert out.iloc[6] == pytest.approx(100 - 100 / (1 + ag / al))
    assert out.iloc[:5].equals(full.iloc[:5]) or np.allclose(out.iloc[:5], full.iloc[:5], equal_nan=True)


# --------------------------------------------------------------------------------------------------
# momentum 12-1
# --------------------------------------------------------------------------------------------------
def test_mom_12_1_offsets_and_first_valid_row():
    n = 400
    p = 100 * 1.001 ** np.arange(n)
    # break the geometric pattern so that wrong offsets would be detected
    p = p * (1 + 0.05 * np.sin(np.arange(n)))
    df = pd.DataFrame({"A": p}, index=_idx(n))
    m = T.mom_12_1(df)
    assert m["A"].iloc[:252].isna().all()
    assert m["A"].notna().iloc[252:].all()
    for t in (252, 300, 399):
        assert m["A"].iloc[t] == pytest.approx(p[t - 21] / p[t - 252] - 1.0, rel=1e-12)


def test_mom_12_1_skips_the_last_month_and_uses_adjclose_input_as_is():
    n = 300
    p = np.full(n, 100.0)
    p[-1] = 1000.0                                          # a jump on the formation day itself
    p[-5] = 1000.0                                          # and within the skipped month
    df = pd.DataFrame({"A": p}, index=_idx(n))
    assert T.mom_12_1(df)["A"].iloc[-1] == pytest.approx(0.0)


def test_mom_12_1_requires_90pct_valid_days_in_window():
    n = 300
    p = 100 * 1.002 ** np.arange(n)
    t = 280
    lo, hi = t - 252, t - 21                                # window rows, inclusive (232 rows)
    win = hi - lo + 1
    assert win == 232
    ok = pd.DataFrame({"A": p.copy()}, index=_idx(n))
    ok.iloc[lo + 1: lo + 1 + 23, 0] = np.nan                # 23 missing -> 209 valid >= 0.9*232 = 208.8
    bad = pd.DataFrame({"A": p.copy()}, index=_idx(n))
    bad.iloc[lo + 1: lo + 1 + 24, 0] = np.nan               # 24 missing -> 208 valid < 208.8
    assert T.mom_12_1(ok)["A"].iloc[t] == pytest.approx(p[hi] / p[lo] - 1)
    assert np.isnan(T.mom_12_1(bad)["A"].iloc[t])


def test_mom_12_1_nan_if_endpoint_missing():
    n = 300
    p = 100 * 1.002 ** np.arange(n)
    df = pd.DataFrame({"A": p}, index=_idx(n))
    df.iloc[280 - 21, 0] = np.nan
    assert np.isnan(T.mom_12_1(df)["A"].iloc[280])


# --------------------------------------------------------------------------------------------------
# SMA / 52w high / vol
# --------------------------------------------------------------------------------------------------
def test_sma_includes_today_and_needs_full_window():
    n = 260
    p = np.arange(1.0, n + 1)
    df = pd.DataFrame({"A": p}, index=_idx(n))
    s = T.sma(df, 200)
    assert s["A"].iloc[:199].isna().all()
    assert s["A"].iloc[199] == pytest.approx(p[:200].mean())
    assert s["A"].iloc[259] == pytest.approx(p[60:260].mean())      # last 200 closes including today


def test_sma_tolerates_few_missing_but_not_many():
    n = 260
    p = np.arange(1.0, n + 1)
    few = pd.DataFrame({"A": p.copy()}, index=_idx(n))
    few.iloc[100:110, 0] = np.nan                                    # 10 of the 200 days missing (95% valid)
    many = pd.DataFrame({"A": p.copy()}, index=_idx(n))
    many.iloc[100:130, 0] = np.nan                                   # 30 missing (85% valid)
    assert T.sma(few, 200)["A"].iloc[259] == pytest.approx(np.nanmean(few["A"].iloc[60:260]))
    assert np.isnan(T.sma(many, 200)["A"].iloc[259])


def test_sma_new_listing_is_nan():
    n = 300
    df = _frame({"A": np.arange(1.0, n + 1), "B": np.arange(1.0, 101.0)}, n=n)   # B has only 100 prices
    assert T.sma(df, 200)["B"].isna().all()


def test_high_52w_ratio():
    n = 300
    p = np.concatenate([np.linspace(50, 100, 150), np.linspace(100, 80, 150)])
    df = pd.DataFrame({"A": p}, index=_idx(n))
    h = T.high_52w_ratio(df)
    assert h["A"].iloc[:251].isna().all()
    assert h["A"].iloc[299] == pytest.approx(p[299] / p[48:300].max())
    assert (h["A"].dropna() <= 1.0 + 1e-12).all()


def test_realized_vol_is_uncentered_annualised():
    rng = np.random.default_rng(3)
    r = pd.Series(rng.normal(0.001, 0.01, 200), index=_idx(200))
    v = T.realized_vol(r, 126)
    assert v.iloc[:112].isna().all()                                 # < 0.9 * 126 = 113.4 observations
    manual = np.sqrt(252 * np.mean(r.iloc[74:200].to_numpy() ** 2))
    assert v.iloc[199] == pytest.approx(manual, rel=1e-12)
    centered = r.iloc[74:200].std(ddof=0) * np.sqrt(252)
    assert abs(v.iloc[199] - centered) > 1e-6                       # really uncentered (mean 0.1%/day)


# --------------------------------------------------------------------------------------------------
# no look-ahead and caching
# --------------------------------------------------------------------------------------------------
def test_signals_are_causal_truncating_the_panel_changes_nothing_at_t():
    rng = np.random.default_rng(7)
    n = 500
    px = pd.DataFrame(100 * np.exp(np.cumsum(rng.normal(0, 0.02, size=(n, 4)), axis=0)), index=_idx(n),
                      columns=list("ABCD"))
    px.iloc[:60, 3] = np.nan
    px.iloc[200:210, 1] = np.nan
    t = 420
    full = (T.mom_12_1(px), T.sma(px), T.rsi_wilder(px), T.high_52w_ratio(px))
    part_px = px.iloc[: t + 1]
    part = (T.mom_12_1(part_px), T.sma(part_px), T.rsi_wilder(part_px), T.high_52w_ratio(part_px))
    for f, p in zip(full, part):
        np.testing.assert_allclose(f.iloc[: t + 1].to_numpy(), p.to_numpy(), rtol=0, atol=1e-12, equal_nan=True)


def test_get_technicals_is_cached_on_the_context():
    class Ctx:
        pass
    n = 300
    ctx = Ctx()
    ctx.close = pd.DataFrame({"A": 100 * 1.001 ** np.arange(n)}, index=_idx(n))
    ctx.adjclose = ctx.close * 1.0
    ctx.returns = ctx.adjclose.pct_change()
    a = T.get_technicals(ctx)
    assert T.get_technicals(ctx) is a
    assert a.mom is a.mom                                           # lazy property computed once
    assert a.rsi14.shape == ctx.close.shape
    assert a.vol126().shape == ctx.close.shape


# --------------------------------------------------------------------------------------------------
# residual momentum (Blitz, Huij & Martens 2011)
# --------------------------------------------------------------------------------------------------
def _residual_world(seed=0, n_months=60):
    rng = np.random.default_rng(seed)
    days = pd.bdate_range("2015-01-01", periods=n_months * 21 + 5)
    months = days.to_period("M")
    mend = pd.Series(days, index=days).groupby(months).max()
    f = pd.DataFrame({"Mkt-RF": rng.normal(0.008, 0.04, len(mend)), "SMB": rng.normal(0, 0.02, len(mend)),
                      "HML": rng.normal(0, 0.02, len(mend)), "RF": 0.001}, index=mend.to_numpy())
    rets = {}
    recent = np.arange(len(mend)) >= len(mend) - 12        # the last 12 months (formation period)
    for tk, beta, drift in (("HI_BETA", 2.0, 0.0), ("ALPHA", 1.0, 0.02), ("PLAIN", 1.0, 0.0)):
        # ALPHA outperforms what the factors explain only recently: residual momentum should rank it first
        # (a constant all-window drift would be absorbed by the regression intercept, as in the paper)
        rets[tk] = 0.001 + beta * f["Mkt-RF"].to_numpy() + drift * recent + rng.normal(0, 0.01, len(mend))
    m = pd.DataFrame(rets, index=mend.to_numpy())
    # daily prices that hit the monthly returns exactly at month-ends (flat within the month)
    px = (1 + m).cumprod()
    adj = px.reindex(days).bfill().ffill()
    return adj, f


def test_residual_momentum_ranks_idiosyncratic_drift_not_market_beta():
    adj, f = _residual_world()
    rm = T.residual_momentum(adj, f)
    last = rm.iloc[-1]
    # ALPHA earns 2%/month the factors cannot explain -> top score; HI_BETA only has market exposure
    assert last["ALPHA"] > last["PLAIN"] and last["ALPHA"] > last["HI_BETA"]
    assert abs(last["HI_BETA"]) < last["ALPHA"]


def test_residual_momentum_uses_only_past_data():
    adj, f = _residual_world(seed=1)
    full = T.residual_momentum(adj, f)
    me = adj.groupby(adj.index.to_period("M")).tail(1).index
    t = me[45]
    cut = T.residual_momentum(adj.loc[:t], f)            # no prices after t
    pd.testing.assert_series_equal(full.loc[t], cut.loc[t])
    shocked = adj.copy()
    shocked.loc[shocked.index > t] *= 3.0                   # future prices change, past signal must not
    pd.testing.assert_series_equal(T.residual_momentum(shocked, f).loc[t], full.loc[t])


def test_residual_momentum_needs_a_full_window():
    adj, f = _residual_world(n_months=30)                   # shorter than the 36-month regression window
    assert T.residual_momentum(adj, f).isna().all().all()
