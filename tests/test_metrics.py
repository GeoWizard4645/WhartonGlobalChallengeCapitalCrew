"""Tests for quant/backtest/metrics.py (research/06 sections 2 and 7)."""
import numpy as np
import pandas as pd
import pytest

from quant.backtest import metrics as m


def _monthly_index(n, start="2020-01-31"):
    return pd.date_range(start, periods=n, freq="ME")


# ---------------------------------------------------------------------------------------------
# CAGR, volatility, Sharpe, Sortino (hand-computed)
# ---------------------------------------------------------------------------------------------
def test_cagr_hand_examples():
    assert m.cagr([0.44, 0.0], ppy=1) == pytest.approx(0.20)               # sqrt(1.44) - 1
    assert m.cagr([0.10, 0.21], ppy=1) == pytest.approx(np.sqrt(1.331) - 1)
    assert m.cagr([0.01] * 12, ppy=12) == pytest.approx(1.01 ** 12 - 1)     # one year of 1% months
    assert m.cagr([0.01] * 6, ppy=12) == pytest.approx(1.01 ** 12 - 1)     # annualises a half year
    assert m.cagr([0.0] * 5, ppy=12) == 0.0
    assert m.cagr([-1.0, 0.5], ppy=12) == -1.0                              # total loss
    assert np.isnan(m.cagr([], ppy=12)) and np.isnan(m.cagr([np.nan], ppy=12))
    # long daily series does not overflow the way a naive product would
    assert m.cagr(np.full(25_000, 0.0004), ppy=252) == pytest.approx(1.0004 ** 252 - 1)


def test_ann_vol_hand_example():
    assert m.ann_vol([0.01, 0.03], ppy=12) == pytest.approx(np.sqrt(2) * 0.01 * np.sqrt(12))   # sd = 0.0141421
    assert m.ann_vol([0.01, 0.03], ppy=1) == pytest.approx(0.0141421356)
    assert np.isnan(m.ann_vol([0.01], ppy=12))


def test_sharpe_hand_example_scalar_and_array_rf():
    r = [0.02, 0.04, 0.00, 0.02]
    # excess = [.015, .035, -.005, .015]: mean .015, deviations [0, .02, -.02, 0] -> var = .0008 / 3
    expected = 0.015 / np.sqrt(0.0008 / 3) * np.sqrt(12)
    assert m.sharpe(r, rf=0.005, ppy=12) == pytest.approx(expected)
    assert expected == pytest.approx(3.182, abs=1e-3)
    assert m.sharpe(r, rf=np.full(4, 0.005), ppy=12) == pytest.approx(expected)
    # time-varying rf
    rf = np.array([0.001, 0.003, 0.002, 0.004])
    x = np.array(r) - rf
    assert m.sharpe(r, rf, 12) == pytest.approx(x.mean() / x.std(ddof=1) * np.sqrt(12))
    # default rf = 0, ppy = 12
    assert m.sharpe(r) == pytest.approx(np.mean(r) / np.std(r, ddof=1) * np.sqrt(12))
    # daily annualisation
    assert m.sharpe(r, 0.005, ppy=252) == pytest.approx(expected * np.sqrt(252 / 12))
    # constant series has no volatility -> NaN, not inf
    assert np.isnan(m.sharpe([0.01] * 6))


def test_sharpe_rf_series_alignment_and_nan_rules():
    idx = _monthly_index(6)
    r = pd.Series([0.02, 0.01, np.nan, 0.03, -0.01, 0.02], index=idx)
    rf = pd.Series([0.002] * 6, index=idx).sample(frac=1.0, random_state=0)       # shuffled order
    clean = r.dropna() - 0.002
    expected = clean.mean() / clean.std(ddof=1) * np.sqrt(12)
    assert m.sharpe(r, rf, 12) == pytest.approx(expected)                           # aligned by index, NaN dropped
    assert m.sharpe(r.to_numpy(), 0.002, 12) == pytest.approx(expected)
    assert m.sharpe(list(r), 0.002, 12) == pytest.approx(expected)
    with pytest.raises(ValueError):
        m.sharpe(np.ones(5), np.ones(4))                                            # arrays must match in length


def test_sortino_hand_example():
    r = [0.02, -0.01, 0.03, -0.02]
    # DD = sqrt((0.01^2 + 0.02^2) / 4), denominator counts all four observations
    expected = 0.005 / np.sqrt(0.0005 / 4) * np.sqrt(12)
    assert m.sortino(r, rf=0.0, ppy=12) == pytest.approx(expected)
    assert expected == pytest.approx(1.549, abs=1e-3)
    # rf is the minimum acceptable return
    x = np.array(r) - 0.005
    assert m.sortino(r, 0.005, 12) == pytest.approx(x.mean() / np.sqrt(np.mean(np.minimum(x, 0) ** 2)) * np.sqrt(12))
    assert np.isnan(m.sortino([0.01, 0.02, 0.03]))                                  # no downside


# ---------------------------------------------------------------------------------------------
# drawdowns
# ---------------------------------------------------------------------------------------------
HAND_R = [0.10, -0.20, 0.05, -0.10, 0.30]
# wealth 1.1, 0.88, 0.924, 0.8316, 1.08108 ; running peak 1.1 throughout


def test_max_drawdown_hand_example():
    dd = m.drawdown_series(HAND_R)
    np.testing.assert_allclose(dd, [0.0, -0.20, 0.924 / 1.1 - 1, 0.8316 / 1.1 - 1, 1.08108 / 1.1 - 1])
    assert dd[3] == pytest.approx(-0.244)
    assert m.max_drawdown(HAND_R) == pytest.approx(-0.244)                          # 0.8 * 1.05 * 0.9 - 1
    assert m.max_drawdown([0.01, 0.02, 0.03]) == 0.0                                # never below a high
    assert m.max_drawdown([-0.5]) == pytest.approx(-0.5)                            # measured from starting wealth
    assert m.max_drawdown([-0.1, -0.1]) == pytest.approx(0.81 - 1)
    assert np.isnan(m.max_drawdown([]))
    # NaN observations are skipped, series stays a path of the valid periods
    assert m.max_drawdown([0.10, np.nan, -0.20, 0.05, -0.10, 0.30]) == pytest.approx(-0.244)
    assert len(m.drawdown_series(pd.Series(HAND_R))) == 5


def test_max_drawdown_dates():
    idx = _monthly_index(5)
    out = m.max_drawdown_dates(pd.Series(HAND_R, index=idx))
    assert out["max_dd"] == pytest.approx(-0.244)
    assert out["peak"] == idx[0] and out["trough"] == idx[3]
    assert out["recovery"] is None and not out["peak_is_start"]                     # 1.08108 < 1.1: not recovered

    idx6 = _monthly_index(6)
    out6 = m.max_drawdown_dates(pd.Series(HAND_R + [0.25], index=idx6))             # 1.08108 * 1.25 = 1.351 > 1.1
    assert out6["recovery"] == idx6[5] and out6["trough"] == idx6[3]

    # the high is the pre-sample starting wealth
    out_s = m.max_drawdown_dates(pd.Series([-0.1, 0.02, -0.05], index=_monthly_index(3)))
    assert out_s["peak_is_start"] and out_s["peak"] == _monthly_index(3)[0]
    assert out_s["max_dd"] == pytest.approx(0.9 * 1.02 * 0.95 - 1)
    # no drawdown
    flat = m.max_drawdown_dates(pd.Series([0.01, 0.02], index=_monthly_index(2)))
    assert flat["max_dd"] == 0.0 and flat["peak"] is None and flat["trough"] is None
    # agrees with max_drawdown on random data
    s = pd.Series(np.random.default_rng(0).normal(0.005, 0.04, 200), index=_monthly_index(200))
    assert m.max_drawdown_dates(s)["max_dd"] == pytest.approx(m.max_drawdown(s))
    assert m.max_drawdown_dates(s)["peak"] < m.max_drawdown_dates(s)["trough"]


def test_calmar_hand_example():
    cagr_ = np.prod(1 + np.array(HAND_R)) ** (12 / 5) - 1
    assert m.calmar(HAND_R, ppy=12) == pytest.approx(cagr_ / 0.244)
    assert np.isnan(m.calmar([0.01, 0.02], ppy=12))                                 # no drawdown


# ---------------------------------------------------------------------------------------------
# benchmark-relative statistics
# ---------------------------------------------------------------------------------------------
def test_beta_recovers_slope_with_and_without_rf():
    rng = np.random.default_rng(1)
    b = rng.normal(0.008, 0.04, 120)
    r = 0.002 + 2.0 * b
    assert m.beta(r, b) == pytest.approx(2.0)
    assert m.beta(r, b, rf=0.003) == pytest.approx(2.0)                             # a constant rf does not change the slope
    assert m.beta(r, b, rf=np.full(120, 0.003)) == pytest.approx(2.0)
    noisy = 0.5 * b + rng.normal(0, 0.02, 120)
    assert m.beta(noisy, b) == pytest.approx(np.polyfit(b, noisy, 1)[0])
    # with a time-varying rf the excess-return regression is used
    rf = rng.uniform(0, 0.004, 120)
    assert m.beta(noisy, b, rf) == pytest.approx(np.polyfit(b - rf, noisy - rf, 1)[0])
    assert np.isnan(m.beta(r, np.full(120, 0.01)))                                   # constant benchmark


def test_tracking_error_information_ratio_hit_rate_hand_example():
    r = [0.03, 0.01, 0.02, 0.04]
    b = [0.02, 0.02, 0.01, 0.01]
    # active = [.01, -.01, .01, .03]: mean .01, deviations [0, -.02, 0, .02] -> var .0008/3
    sd = np.sqrt(0.0008 / 3)
    assert m.tracking_error(r, b, 12) == pytest.approx(sd * np.sqrt(12))
    assert m.information_ratio(r, b, 12) == pytest.approx(0.01 / sd * np.sqrt(12))
    assert m.hit_rate(r, b) == pytest.approx(0.75)
    assert m.hit_rate([0.01, 0.02], [0.01, 0.01]) == pytest.approx(0.5)               # ties do not count as beating
    assert np.isnan(m.information_ratio([0.01, 0.02, 0.03], [0.0, 0.01, 0.02], 12))   # constant active return
    assert m.tracking_error(r, r, 12) == 0.0


def test_active_cagr_hand_example():
    # cagr_r = 20%, cagr_b = sqrt(1.21) - 1 = 10%  ->  1.2 / 1.1 - 1
    assert m.active_cagr([0.44, 0.0], [0.21, 0.0], ppy=1) == pytest.approx(1.2 / 1.1 - 1)
    assert m.active_cagr([0.1, 0.1], [0.1, 0.1], ppy=12) == pytest.approx(0.0)
    r, b = [0.02, 0.01, 0.03], [0.01, 0.015, 0.02]
    assert m.active_cagr(r, b, 12) == pytest.approx((1 + m.cagr(r, 12)) / (1 + m.cagr(b, 12)) - 1)


def test_capture_ratios_hand_example():
    b = [0.02, -0.01, 0.04, -0.03]
    r = [0.03, -0.005, 0.02, -0.06]
    up, down = m.capture_ratios(r, b)
    assert up == pytest.approx(0.025 / 0.03)                                         # mean(.03,.02) / mean(.02,.04)
    assert down == pytest.approx(-0.0325 / -0.02)                                    # mean(-.005,-.06) / mean(-.01,-.03)
    up_only = m.capture_ratios([0.01, 0.02], [0.01, 0.02])
    assert up_only[0] == pytest.approx(1.0) and np.isnan(up_only[1])                 # no down months -> NaN
    assert m.capture_ratios(b, b) == (pytest.approx(1.0), pytest.approx(1.0))


def test_pairwise_nan_and_series_alignment():
    idx = _monthly_index(6)
    r = pd.Series([0.02, np.nan, 0.01, 0.03, 0.00, 0.02], index=idx)
    b = pd.Series([0.01, 0.01, np.nan, 0.01, 0.01, 0.02], index=idx)
    keep = [0, 3, 4, 5]
    assert m.hit_rate(r, b) == pytest.approx(np.mean(r.to_numpy()[keep] > b.to_numpy()[keep]))
    assert m.tracking_error(r, b, 12) == pytest.approx(m.tracking_error(r.to_numpy()[keep], b.to_numpy()[keep], 12))
    # different indexes -> inner join on the dates
    b_short = pd.Series([0.01, 0.01, 0.01], index=idx[2:5])
    r_full = pd.Series([0.02, 0.01, 0.03, 0.00, 0.02, 0.01], index=idx)
    assert m.hit_rate(r_full, b_short) == pytest.approx(np.mean(np.array([0.03, 0.00, 0.02]) > 0.01))
    with pytest.raises(ValueError):
        m.hit_rate(np.ones(5), np.ones(4))


# ---------------------------------------------------------------------------------------------
# turnover and costs
# ---------------------------------------------------------------------------------------------
def test_turnover_and_costs_two_asset_hand_example():
    # 50/50 book, asset A +10%, asset B -10%: drifted to 55/45; rebalance back to 50/50
    w_pre = m.drifted_weights([0.5, 0.5], [0.10, -0.10])
    np.testing.assert_allclose(w_pre, [0.55, 0.45])
    target = np.array([0.5, 0.5])
    assert m.turnover_oneway(target, w_pre) == pytest.approx(0.05)                   # 0.5 * (0.05 + 0.05)
    dw = target - w_pre
    np.testing.assert_allclose(dw, [-0.05, 0.05])
    # 10 bps per side on 0.10 traded notional = 1 bp ( = 2 * c * one-way turnover )
    net = m.apply_costs([0.0100], dw[None, :], 10.0)
    assert net[0] == pytest.approx(0.0100 - 0.0001)
    assert 0.0100 - net[0] == pytest.approx(2 * 10e-4 * m.turnover_oneway(target, w_pre) * 1.0)
    # per-asset costs: 10 bps on A, 30 bps on B
    net2 = m.apply_costs([0.0100], dw[None, :], [10.0, 30.0])
    assert net2[0] == pytest.approx(0.0100 - (0.05 * 10e-4 + 0.05 * 30e-4))
    # research/06 example: 0.2 of NAV traded at 10 bps = 2 bps ; replacing the whole book costs 20 bps
    assert 0.0 - m.apply_costs([0.0], [[0.1, -0.1]], 10.0)[0] == pytest.approx(0.0002)
    assert 0.0 - m.apply_costs([0.0], [[-1.0, 1.0]], 10.0)[0] == pytest.approx(0.0020)
    assert m.turnover_oneway([0.0, 1.0], [1.0, 0.0]) == pytest.approx(1.0)           # whole book replaced once


def test_apply_costs_multi_period_and_edge_cases():
    gross = np.array([0.01, 0.02, -0.01])
    dw = np.array([[0.5, -0.5], [0.0, 0.0], [0.1, 0.2]])
    net = m.apply_costs(gross, dw, 25.0)
    np.testing.assert_allclose(net, gross - 25e-4 * np.array([1.0, 0.0, 0.3]))
    # 1-D dw = one asset; NaN trade = no trade; Series input accepted
    np.testing.assert_allclose(m.apply_costs(pd.Series(gross), np.array([0.2, np.nan, -0.2]), 10.0),
                               gross - 10e-4 * np.array([0.2, 0.0, 0.2]))
    with pytest.raises(ValueError):
        m.apply_costs(gross, dw[:2], 10.0)
    with pytest.raises(ValueError):
        m.apply_costs(gross, dw, [1.0, 2.0, 3.0])


def test_drifted_weights_with_cash_residual():
    # 50% A (+20%), 30% B (0%), 20% cash earning 1%: portfolio value 1.102
    w = m.drifted_weights([0.5, 0.3], [0.20, 0.0], cash_return=0.01)
    np.testing.assert_allclose(w, [0.6 / 1.102, 0.3 / 1.102])
    assert w.sum() + 0.2 * 1.01 / 1.102 == pytest.approx(1.0)                         # cash weight is the residual
    # when the book is fully invested the cash term vanishes
    np.testing.assert_allclose(m.drifted_weights([0.25, 0.75], [0.04, -0.02]),
                               np.array([0.26, 0.735]) / (0.26 + 0.735))
    # a non-trading asset (NaN return) keeps its value
    np.testing.assert_allclose(m.drifted_weights([0.5, 0.5], [np.nan, 0.10]), np.array([0.5, 0.55]) / 1.05)
    with pytest.raises(ValueError):
        m.drifted_weights([0.5, 0.5], [0.1])
    with pytest.raises(ValueError):
        m.turnover_oneway([0.5, 0.5], [1.0])


# ---------------------------------------------------------------------------------------------
# rolling windows and horizon report
# ---------------------------------------------------------------------------------------------
def test_rolling_compound_matches_brute_force():
    rng = np.random.default_rng(0)
    r = rng.normal(0.001, 0.01, 60)
    for h in (1, 3, 13, 60):
        got = m.rolling_compound(r, h)
        ref = np.array([np.prod(1 + r[i:i + h]) - 1 for i in range(len(r) - h + 1)])
        np.testing.assert_allclose(got, ref, atol=1e-13)
        assert len(got) == len(r) - h + 1
    assert len(m.rolling_compound(r, 61)) == 0
    # a NaN poisons exactly the windows that contain it
    x = np.array([0.01, 0.02, np.nan, 0.03, 0.01, 0.02])
    out = m.rolling_compound(x, 2)
    assert list(np.isnan(out)) == [False, True, True, False, False]
    assert out[0] == pytest.approx(1.01 * 1.02 - 1) and out[4] == pytest.approx(1.01 * 1.02 - 1)
    # total loss inside a window gives -100%, and later windows are unaffected
    out = m.rolling_compound([0.1, -1.0, 0.1, 0.1], 2)
    assert out[0] == pytest.approx(-1.0, abs=1e-9) and out[1] == pytest.approx(-1.0, abs=1e-9)
    assert out[2] == pytest.approx(1.1 * 1.1 - 1)
    with pytest.raises(ValueError):
        m.rolling_compound(r, 0)


def test_horizon_report_deterministic_cases():
    r = np.full(60, 0.01)
    b = np.full(60, 0.005)
    rep = m.horizon_report(r, b, h=3, B=100)
    assert rep["p_beat"] == 1.0 and rep["p_beat_ci"] == (1.0, 1.0) and rep["p_loss"] == 0.0
    assert rep["n_windows"] == 58 and rep["n_independent"] == pytest.approx(20.0) and rep["h"] == 3
    assert rep["mean_excess"] == pytest.approx(1.01 ** 3 - 1.005 ** 3)
    assert rep["worst_excess"] == pytest.approx(rep["best_excess"])
    rep0 = m.horizon_report(b, r, h=3, B=100)
    assert rep0["p_beat"] == 0.0 and rep0["p_beat_margin"] == 0.0
    rep_l = m.horizon_report(np.full(60, -0.01), np.full(60, -0.02), h=6, B=100)
    assert rep_l["p_loss"] == 1.0 and rep_l["p_beat"] == 1.0
    with pytest.raises(ValueError):
        m.horizon_report(r[:2], b[:2], h=3)


def test_horizon_report_random_data():
    rng = np.random.default_rng(3)
    n, h = 240, 3
    b = rng.normal(0.007, 0.04, n)
    r = b + rng.normal(0.001, 0.02, n)
    rep = m.horizon_report(r, b, h, B=500, seed=1)
    Rp, Rb = m.rolling_compound(r, h), m.rolling_compound(b, h)
    E = Rp - Rb
    assert rep["p_beat"] == pytest.approx(np.mean(E > 0))                          # brute force
    assert rep["p_loss"] == pytest.approx(np.mean(Rp < 0))
    assert rep["p_beat_margin"] == pytest.approx(np.mean(E > 0.02))
    lo, hi = rep["p_beat_ci"]
    assert 0.0 <= lo < rep["p_beat"] < hi <= 1.0
    assert rep["p_loss_ci"][0] < rep["p_loss"] < rep["p_loss_ci"][1]
    q = rep["excess_quantiles"]
    assert list(q) == [5, 25, 50, 75, 95] and list(q.values()) == sorted(q.values())
    assert q[50] == pytest.approx(np.median(E)) and rep["median_excess"] == pytest.approx(np.median(E))
    assert rep["return_quantiles"][5] == pytest.approx(np.percentile(Rp, 5))
    assert rep["worst_excess"] == pytest.approx(E.min()) and rep["mean_excess"] == pytest.approx(E.mean())
    assert rep["mean_block"] == 3.0                                                # max(h, 3)
    assert m.horizon_report(r, b, 6, B=50)["mean_block"] == 6.0
    # reproducible with the same seed, accepts pandas input
    rep2 = m.horizon_report(pd.Series(r), pd.Series(b), h, B=500, seed=1)
    assert rep2["p_beat_ci"] == rep["p_beat_ci"]
    # no skill => P(beat) is about 50%
    nsk = m.horizon_report(rng.normal(0.007, 0.04, 600), rng.normal(0.007, 0.04, 600), 3, B=200)
    assert 0.4 < nsk["p_beat"] < 0.6


# ---------------------------------------------------------------------------------------------
# pandas helpers: to_monthly, summary_table
# ---------------------------------------------------------------------------------------------
def test_to_monthly_compounds_and_labels_last_trading_day():
    idx = pd.bdate_range("2024-01-01", "2024-03-29")
    daily = pd.Series(0.001, index=idx, name="strat")
    out = m.to_monthly(daily)
    assert list(out.index) == [pd.Timestamp("2024-01-31"), pd.Timestamp("2024-02-29"), pd.Timestamp("2024-03-29")]
    n_jan = (idx.month == 1).sum()
    assert out.iloc[0] == pytest.approx(1.001 ** n_jan - 1)
    assert out.name == "strat"
    # the compounded monthly series reproduces total wealth
    assert np.prod(1 + out) == pytest.approx(np.prod(1 + daily))
    # label is the last trading day, not the calendar month end (Feb 2025 ends on Friday the 28th; Mar 31 is Monday)
    idx2 = pd.bdate_range("2025-02-03", "2025-03-31")
    out2 = m.to_monthly(pd.Series(0.001, index=idx2))
    assert list(out2.index) == [pd.Timestamp("2025-02-28"), pd.Timestamp("2025-03-31")]
    # NaN days are skipped; an all-NaN month is dropped; partial final month kept
    d3 = pd.Series([0.01, np.nan, 0.02, np.nan, np.nan, 0.05],
                   index=pd.to_datetime(["2024-01-02", "2024-01-03", "2024-01-04", "2024-02-01", "2024-02-02", "2024-03-01"]))
    out3 = m.to_monthly(d3)
    assert len(out3) == 2 and out3.iloc[0] == pytest.approx(1.01 * 1.02 - 1) and out3.index[0] == pd.Timestamp("2024-01-04")
    assert out3.iloc[1] == pytest.approx(0.05)
    # unsorted input is handled; non-datetime index rejected
    assert m.to_monthly(daily.sample(frac=1.0, random_state=0)).iloc[0] == pytest.approx(out.iloc[0])
    with pytest.raises(TypeError):
        m.to_monthly(pd.Series([0.01, 0.02]))


def _t1_inputs():
    rng = np.random.default_rng(42)
    idx = pd.date_range("2010-01-31", "2023-12-31", freq="ME")
    b = pd.Series(rng.normal(0.008, 0.04, len(idx)), index=idx, name="SPY")
    r = pd.Series(0.001 + 1.1 * b.to_numpy() + rng.normal(0, 0.015, len(idx)), index=idx, name="strat")
    rf = pd.Series(0.0002, index=idx)
    return r, b, rf


def test_summary_table_structure_and_values():
    r, b, rf = _t1_inputs()
    windows = {"Full": (None, None), "Train": ("2010-01-01", "2018-12-31"), "Test": (pd.Timestamp("2019-01-01"), None),
               "Last 36m": (r.index[-36], None)}
    df = m.summary_table(r, b, rf, 12, windows)
    assert list(df.index) == ["CAGR", "AnnVol", "Sharpe", "Sortino", "MaxDD", "Calmar", "Beta", "TE", "IR",
                              "ActiveCAGR", "HitRate"]
    assert list(df.columns) == list(windows)
    assert df.shape == (11, 4) and df.dtypes.eq(float).all()
    assert df.attrs["n_periods"] == {"Full": 168, "Train": 108, "Test": 60, "Last 36m": 36}

    # each cell equals the direct function call on the sliced data
    tr, tb = r.loc["2010":"2018"], b.loc["2010":"2018"]
    assert df.loc["CAGR", "Train"] == pytest.approx(m.cagr(tr, 12))
    assert df.loc["AnnVol", "Train"] == pytest.approx(m.ann_vol(tr, 12))
    assert df.loc["Sharpe", "Train"] == pytest.approx(m.sharpe(tr, 0.0002, 12))
    assert df.loc["Sortino", "Train"] == pytest.approx(m.sortino(tr, 0.0002, 12))
    assert df.loc["MaxDD", "Train"] == pytest.approx(m.max_drawdown(tr))
    assert df.loc["Calmar", "Train"] == pytest.approx(m.calmar(tr, 12))
    assert df.loc["Beta", "Train"] == pytest.approx(m.beta(tr, tb, 0.0002))
    assert df.loc["TE", "Train"] == pytest.approx(m.tracking_error(tr, tb, 12))
    assert df.loc["IR", "Train"] == pytest.approx(m.information_ratio(tr, tb, 12))
    assert df.loc["ActiveCAGR", "Train"] == pytest.approx(m.active_cagr(tr, tb, 12))
    assert df.loc["HitRate", "Train"] == pytest.approx(m.hit_rate(tr, tb))
    assert df.loc["Beta", "Full"] == pytest.approx(1.1, abs=0.08)
    te = r.loc["2019-01-01":]
    assert df.loc["CAGR", "Test"] == pytest.approx(m.cagr(te, 12)) and df.loc["CAGR", "Last 36m"] == pytest.approx(m.cagr(r.iloc[-36:], 12))
    # the windows tile the sample: compounding Train and Test gives the Full wealth
    assert (1 + df.loc["CAGR", "Train"]) ** 9 * (1 + df.loc["CAGR", "Test"]) ** 5 == pytest.approx((1 + df.loc["CAGR", "Full"]) ** 14)


def test_summary_table_defaults_benchmark_row_and_rf_variants():
    r, b, rf = _t1_inputs()
    df = m.summary_table(r, b, 0.0, 12)                                            # default window = Full, scalar rf
    assert list(df.columns) == ["Full"] and df.loc["Sharpe", "Full"] == pytest.approx(m.sharpe(r, 0.0, 12))
    assert m.summary_table(r, b, None, 12).equals(df)                              # None = 0
    # benchmark vs itself: beta 1, no tracking error, IR undefined
    self_df = m.summary_table(b, b, rf, 12)
    assert self_df.loc["Beta", "Full"] == pytest.approx(1.0) and self_df.loc["TE", "Full"] == 0.0
    assert np.isnan(self_df.loc["IR", "Full"]) and self_df.loc["ActiveCAGR", "Full"] == pytest.approx(0.0)
    # no benchmark: benchmark rows are NaN, the rest is filled
    nb = m.summary_table(r, None, rf, 12)
    assert nb.loc[["Beta", "TE", "IR", "ActiveCAGR", "HitRate"], "Full"].isna().all()
    assert nb.loc["CAGR", "Full"] == pytest.approx(m.cagr(r, 12))
    # rf and b stamped on calendar month-end while r uses trading month-ends: aligned by month
    bd = [d if d.weekday() < 5 else d - pd.offsets.BDay(1) for d in r.index]
    r_trading = pd.Series(r.to_numpy(), index=pd.DatetimeIndex(bd))
    df_t = m.summary_table(r_trading, b, rf, 12)
    pd.testing.assert_frame_equal(df_t, m.summary_table(r, b, rf, 12))
    # a window with fewer than 2 observations gives NaNs instead of raising
    short = m.summary_table(r, b, rf, 12, {"One": ("2023-12-01", None), "Empty": ("2030-01-01", None)})
    assert short["Empty"].isna().all()
    assert short.loc[["AnnVol", "Sharpe", "Sortino", "Beta", "TE", "IR"], "One"].isna().all()
    assert short.loc["CAGR", "One"] == pytest.approx((1 + r.iloc[-1]) ** 12 - 1)
    assert short.attrs["n_periods"] == {"One": 1, "Empty": 0}
    # unsorted input and bad types
    shuffled = m.summary_table(r.sample(frac=1.0, random_state=1), b.sample(frac=1.0, random_state=2), rf, 12)
    pd.testing.assert_frame_equal(shuffled, m.summary_table(r, b, rf, 12))
    with pytest.raises(TypeError):
        m.summary_table(r.to_numpy(), b, rf, 12)


def test_summary_table_daily_maxdd_differs_from_monthly():
    """MaxDD uses the input frequency: the daily drawdown is at least as deep as the month-end one."""
    rng = np.random.default_rng(7)
    idx = pd.bdate_range("2015-01-01", "2020-12-31")
    d = pd.Series(rng.normal(0.0004, 0.01, len(idx)), index=idx)
    mon = m.to_monthly(d)
    dd_daily = m.summary_table(d, None, 0.0, 252).loc["MaxDD", "Full"]
    dd_month = m.summary_table(mon, None, 0.0, 12).loc["MaxDD", "Full"]
    assert dd_daily <= dd_month + 1e-12
    # to_monthly preserves total wealth, and the CAGR rows annualise it consistently with each frequency
    cd = m.summary_table(d, None, 0.0, 252).loc["CAGR", "Full"]
    cm = m.summary_table(mon, None, 0.0, 12).loc["CAGR", "Full"]
    assert (1 + cd) ** (len(d) / 252) == pytest.approx(np.prod(1 + d))
    assert (1 + cm) ** (len(mon) / 12) == pytest.approx(np.prod(1 + d))
