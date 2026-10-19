"""Tests for quant/backtest/engine.py (synthetic data, hand-computed expectations)."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from quant.backtest.engine import BacktestConfig, BacktestResult, run, run_sleeves

TOL = dict(rtol=1e-10, atol=1e-12)


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
def make_index(n=14, start="2020-01-01"):
    return pd.bdate_range(start, periods=n)


def make_returns(idx, **cols):
    """cols: name -> scalar | list | array (len n); missing tail is padded with 0."""
    data = {}
    for k, v in cols.items():
        if np.isscalar(v):
            data[k] = np.full(len(idx), float(v))
        else:
            arr = np.zeros(len(idx))
            arr[:len(v)] = v
            data[k] = arr
    return pd.DataFrame(data, index=idx)


def make_targets(idx, rows):
    """rows: {position in idx: {ticker: weight}} -> DataFrame indexed by signal date."""
    df = pd.DataFrame([rows[p] for p in rows], index=[idx[p] for p in rows]).fillna(0.0)
    return df


def zero_rf(idx):
    return pd.Series(0.0, index=idx)


def cfg(**kw):
    kw.setdefault("cost_bps", 0.0)
    return BacktestConfig(**kw)


# --------------------------------------------------------------------------------------------------
# timing / no look-ahead
# --------------------------------------------------------------------------------------------------
def test_exec_lag1_new_book_does_not_earn_next_day_jump():
    idx = make_index()
    ret = make_returns(idx, A=0.0)
    ret.iloc[4, 0] = 0.50           # jump on t+1 (t = idx[3])
    ret.iloc[5, 0] = 0.10           # day after the trade: the new book earns this
    tw = make_targets(idx, {3: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg(exec_lag=1))
    assert res.daily.index[0] == idx[4]                       # first trade day = close of t+1
    assert res.trades["date"].tolist() == [idx[4]]
    assert res.daily.loc[idx[4], "ret_net"] == pytest.approx(0.0)   # old book (cash) earned the jump day
    assert res.daily.loc[idx[5], "ret_net"] == pytest.approx(0.10)
    assert res.daily.loc[idx[4], "exposure"] == pytest.approx(1.0)  # but the position exists at that close


def test_exec_lag0_new_book_earns_next_day_jump():
    idx = make_index()
    ret = make_returns(idx, A=0.0)
    ret.iloc[4, 0] = 0.50
    ret.iloc[5, 0] = 0.10
    tw = make_targets(idx, {3: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg(exec_lag=0))
    assert res.daily.index[0] == idx[3]
    assert res.trades["date"].tolist() == [idx[3]]
    assert res.daily.loc[idx[3], "ret_net"] == pytest.approx(0.0)
    assert res.daily.loc[idx[4], "ret_net"] == pytest.approx(0.50)
    assert res.daily.loc[idx[5], "ret_net"] == pytest.approx(0.10)


def test_exec_lag2():
    idx = make_index()
    ret = make_returns(idx, A=[0, 0, 0, 0, 0.3, 0.2])
    tw = make_targets(idx, {3: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg(exec_lag=2))
    assert res.daily.index[0] == idx[5]
    assert res.daily.loc[idx[5], "ret_net"] == pytest.approx(0.0)       # old book on day 5


def test_signal_date_not_a_trading_day_uses_previous_trading_day():
    idx = make_index()                          # 2020-01-01 (Wed) ... business days only
    ret = make_returns(idx, A=0.01)
    sat = pd.Timestamp("2020-01-04")            # Saturday; last trading day <= it is Fri 2020-01-03 = idx[2]
    assert idx[2] == pd.Timestamp("2020-01-03")
    tw = pd.DataFrame({"A": [1.0]}, index=[sat])
    res = run(tw, ret, zero_rf(idx), cfg(exec_lag=1))
    assert res.daily.index[0] == idx[3]         # one trading day after Friday = Monday
    res0 = run(tw, ret, zero_rf(idx), cfg(exec_lag=0))
    assert res0.daily.index[0] == idx[2]


def test_signal_beyond_data_is_ignored_and_empty_result_is_well_formed():
    idx = make_index(5)
    ret = make_returns(idx, A=0.01)
    tw = pd.DataFrame({"A": [1.0]}, index=[idx[4]])        # lag 1 -> trade day beyond the data
    res = run(tw, ret, zero_rf(idx), cfg(exec_lag=1))
    assert res.daily.empty and res.trades.empty
    assert {"ret_gross", "ret_net", "cost", "turnover", "exposure", "n_holdings", "cash_weight"} <= set(res.daily.columns)
    assert res.monthly().empty


def test_gross_return_is_reproducible_from_lagged_end_of_day_weights():
    rng = np.random.default_rng(1)
    idx = make_index(120)
    ret = pd.DataFrame(rng.normal(0, 0.01, (120, 6)), index=idx, columns=list("ABCDEF"))
    rf = pd.Series(0.0001, index=idx)
    rows = {}
    for p in range(5, 100, 17):
        w = rng.dirichlet(np.ones(6)) * 0.9
        rows[p] = dict(zip("ABCDEF", w))
    tw = make_targets(idx, rows)
    res = run(tw, ret, rf, BacktestConfig(cost_bps=10, stop_loss=0.03))
    w = res.weights.reindex(columns=ret.columns, fill_value=0.0)
    prev_w = w.shift(1)
    prev_cash = res.daily["cash_weight"].shift(1)
    expected = (prev_w * ret.loc[w.index]).sum(axis=1) + prev_cash * rf.loc[w.index]
    np.testing.assert_allclose(res.daily["ret_gross"].iloc[1:], expected.iloc[1:], **TOL)
    np.testing.assert_allclose(res.daily["exposure"] + res.daily["cash_weight"], 1.0, atol=1e-12)


# --------------------------------------------------------------------------------------------------
# drift, turnover, costs
# --------------------------------------------------------------------------------------------------
def test_buy_and_hold_drift_between_rebalances():
    idx = make_index()
    ret = make_returns(idx, A=[0, 0, 0.10, 0.0, 0.0], B=[0, 0, 0.0, 0.10, 0.0])
    tw = make_targets(idx, {0: {"A": 0.5, "B": 0.5}})        # trade at idx[1]; only one row => hold afterwards
    res = run(tw, ret, zero_rf(idx), cfg())
    d = res.daily
    # day idx[2]: A +10%
    assert d.loc[idx[2], "ret_gross"] == pytest.approx(0.05)
    wA = 0.5 * 1.1 / 1.05
    assert res.weights.loc[idx[2], "A"] == pytest.approx(wA)
    assert res.weights.loc[idx[2], "B"] == pytest.approx(0.5 / 1.05)
    # day idx[3]: B +10%, earned on the drifted weights
    assert d.loc[idx[3], "ret_gross"] == pytest.approx((0.5 / 1.05) * 0.10)
    # total wealth = 0.5*1.1 + 0.5*1.1 = 1.1 (nothing traded after the first day)
    assert (1 + d["ret_net"]).prod() == pytest.approx(1.1)
    assert d["turnover"].iloc[1:].abs().sum() == 0.0
    assert res.trades["reason"].tolist() == ["rebalance", "rebalance"]    # only the initial entry


def test_turnover_and_cost_two_asset_example():
    idx = make_index()
    # trade 1 at idx[1]: 60/40.  Day idx[2]: A +10%, B 0.  trade 2 at idx[3]: 50/50.
    ret = make_returns(idx, A=[0, 0, 0.10, 0.0], B=0.0)
    tw = make_targets(idx, {0: {"A": 0.6, "B": 0.4}, 2: {"A": 0.5, "B": 0.5}})
    res = run(tw, ret, zero_rf(idx), cfg(cost_bps=10))
    d = res.daily
    # entry from cash: buys of 100% of NAV -> sum|dw| = 1, one-way turnover 1, cost 10 bps
    assert d.loc[idx[1], "turnover"] == pytest.approx(1.0)
    assert d.loc[idx[1], "cost"] == pytest.approx(0.0010)
    assert d.loc[idx[1], "ret_net"] == pytest.approx(-0.0010)
    # day idx[2]: gross = 0.6 * 0.10 = 0.06
    assert d.loc[idx[2], "ret_gross"] == pytest.approx(0.06)
    assert d.loc[idx[2], "cost"] == 0.0
    # trade 2 at idx[3] (no return effect): drifted pre-trade weights 0.66/1.06, 0.40/1.06
    pre_a, pre_b = 0.66 / 1.06, 0.40 / 1.06
    sum_abs = abs(0.5 - pre_a) + abs(0.5 - pre_b)
    assert d.loc[idx[3], "turnover"] == pytest.approx(0.5 * sum_abs)
    assert d.loc[idx[3], "cost"] == pytest.approx(10e-4 * sum_abs)
    assert d.loc[idx[3], "ret_net"] == pytest.approx(d.loc[idx[3], "ret_gross"] - 10e-4 * sum_abs)
    t3 = res.trades[res.trades["date"] == idx[3]].set_index("ticker")
    assert t3.loc["A", "side"] == "sell" and t3.loc["B", "side"] == "buy"
    assert t3.loc["A", "weight_traded"] == pytest.approx(pre_a - 0.5)
    assert t3.loc["B", "weight_traded"] == pytest.approx(0.5 - pre_b)
    assert set(t3["reason"]) == {"rebalance"}
    # post-trade weights are the targets
    assert res.weights.loc[idx[3], "A"] == pytest.approx(0.5)
    assert res.weights.loc[idx[3], "B"] == pytest.approx(0.5)


def test_round_trip_costs_charge_both_sides():
    idx = make_index()
    ret = make_returns(idx, A=0.0, B=0.0)
    tw = make_targets(idx, {0: {"A": 1.0}, 2: {"B": 1.0}})     # swap A -> B at idx[3]
    res = run(tw, ret, zero_rf(idx), cfg(cost_bps=10))
    d = res.daily
    assert d.loc[idx[3], "turnover"] == pytest.approx(1.0)       # whole book replaced once
    assert d.loc[idx[3], "cost"] == pytest.approx(20e-4)         # 10 bps on the sell AND on the buy
    assert d["cost"].sum() == pytest.approx(10e-4 + 20e-4)


def test_vol_scaled_down_to_cash_counts_cash_in_turnover():
    idx = make_index()
    ret = make_returns(idx, A=0.0)
    tw = make_targets(idx, {0: {"A": 1.0}, 2: {"A": 0.5}})      # halve the position at idx[3]
    res = run(tw, ret, zero_rf(idx), cfg(cost_bps=10))
    assert res.daily.loc[idx[3], "turnover"] == pytest.approx(0.5)    # sold 50% of NAV
    assert res.daily.loc[idx[3], "cost"] == pytest.approx(10e-4 * 0.5)


# --------------------------------------------------------------------------------------------------
# cash
# --------------------------------------------------------------------------------------------------
def test_cash_earns_rf_and_rows_below_one_leave_cash():
    idx = make_index()
    ret = make_returns(idx, A=0.02, B=0.0)
    rf = pd.Series(0.001, index=idx)
    tw = make_targets(idx, {0: {"A": 0.3, "B": 0.3}})            # 40% cash
    res = run(tw, ret, rf, cfg())
    d = res.daily
    assert d.loc[idx[1], "ret_gross"] == pytest.approx(0.001)    # idle cash on the first trade day
    assert d.loc[idx[1], "cash_weight"] == pytest.approx(0.4)
    assert d.loc[idx[1], "exposure"] == pytest.approx(0.6)
    assert d.loc[idx[2], "ret_gross"] == pytest.approx(0.3 * 0.02 + 0.4 * 0.001)
    # next day uses drifted weights
    g2 = 0.3 * 0.02 + 0.4 * 0.001
    wa = 0.3 * 1.02 / (1 + g2)
    wb = 0.3 / (1 + g2)
    wc = 0.4 * 1.001 / (1 + g2)
    assert d.loc[idx[2], "cash_weight"] == pytest.approx(wc)
    assert d.loc[idx[3], "ret_gross"] == pytest.approx(wa * 0.02 + wc * 0.001)
    assert wa + wb + wc == pytest.approx(1.0)


def test_cash_does_not_earn_rf_when_disabled():
    idx = make_index()
    ret = make_returns(idx, A=0.02)
    rf = pd.Series(0.001, index=idx)
    tw = make_targets(idx, {0: {"A": 0.5}})
    res = run(tw, ret, rf, cfg(cash_earns_rf=False))
    assert res.daily.loc[idx[1], "ret_gross"] == pytest.approx(0.0)
    assert res.daily.loc[idx[2], "ret_gross"] == pytest.approx(0.5 * 0.02)


def test_rf_missing_dates_count_as_zero_and_rf_none_is_zero():
    idx = make_index()
    ret = make_returns(idx, A=0.0)
    rf = pd.Series(0.001, index=idx[:2])                          # only the first two dates
    tw = make_targets(idx, {0: {"A": 0.0}})                       # all cash
    res = run(tw, ret, rf, cfg())
    assert res.daily.loc[idx[1], "ret_gross"] == pytest.approx(0.001)
    assert res.daily.loc[idx[2], "ret_gross"] == pytest.approx(0.0)
    res2 = run(tw, ret, None, cfg())
    assert res2.daily["ret_gross"].abs().sum() == 0.0


# --------------------------------------------------------------------------------------------------
# missing data / delisting
# --------------------------------------------------------------------------------------------------
def test_delisting_sells_into_cash_at_first_nan_day():
    idx = make_index()
    a = np.full(len(idx), 0.01)
    a[6:] = np.nan                                                  # last valid return on idx[5]
    ret = pd.DataFrame({"A": a, "B": np.full(len(idx), 0.01)}, index=idx)
    rf = pd.Series(0.0002, index=idx)
    tw = make_targets(idx, {0: {"A": 0.5, "B": 0.5}})
    res = run(tw, ret, rf, cfg(cost_bps=10))
    d = res.daily
    # identical returns -> both weights stay 0.5 until the delisting
    assert res.weights.loc[idx[5], "A"] == pytest.approx(0.5, abs=1e-12)
    dl = res.trades[res.trades["reason"] == "delist"]
    assert dl["date"].tolist() == [idx[6]] and dl["ticker"].tolist() == ["A"]
    assert dl["side"].tolist() == ["sell"]
    wA_before = res.weights.loc[idx[5], "A"]
    assert dl["weight_traded"].iloc[0] == pytest.approx(wA_before)
    # day idx[6]: A's weight is cash (earns rf), B earns 1%; no cost, no turnover for the cash-out
    wB = res.weights.loc[idx[5], "B"]
    assert d.loc[idx[6], "ret_gross"] == pytest.approx(wB * 0.01 + wA_before * 0.0002 + (1 - wA_before - wB) * 0.0002)
    assert d.loc[idx[6], "cost"] == 0.0 and d.loc[idx[6], "turnover"] == 0.0
    assert d.loc[idx[6], "n_holdings"] == 1
    assert d.loc[idx[7], "n_holdings"] == 1
    assert d.loc[idx[6], "exposure"] + d.loc[idx[6], "cash_weight"] == pytest.approx(1.0)
    assert d.loc[idx[6], "cash_weight"] > 0.49
    assert "A" not in res.weights.columns or res.weights.loc[idx[6]:, "A"].abs().max() == 0.0
    # subsequent days: A's money keeps earning rf
    wB6 = res.weights.loc[idx[6], "B"]
    assert d.loc[idx[7], "ret_gross"] == pytest.approx(wB6 * 0.01 + (1 - wB6) * 0.0002)


def test_target_on_unpriced_ticker_is_dropped_to_cash_and_logged(caplog):
    idx = make_index()
    a = np.full(len(idx), 0.01)
    a[6:] = np.nan                                                   # A delisted
    c = np.full(len(idx), 0.01)
    c[:4] = np.nan                                                   # C not yet listed on the first trade day
    ret = pd.DataFrame({"A": a, "B": 0.01, "C": c}, index=idx)
    tw = make_targets(idx, {0: {"B": 0.3, "C": 0.3, "ZZZ": 0.2},      # ZZZ not in returns at all
                            7: {"A": 0.4, "B": 0.4}})
    with caplog.at_level("WARNING", logger="quant.backtest.engine"):
        res = run(tw, ret, zero_rf(idx), cfg())
    d = res.daily
    assert d.loc[idx[1], "exposure"] == pytest.approx(0.3)           # only B was bought
    assert d.loc[idx[1], "cash_weight"] == pytest.approx(0.7)
    assert set(res.dropped["ticker"]) == {"C", "ZZZ", "A"}
    first = res.dropped[res.dropped["date"] == idx[1]].set_index("ticker")["weight"]
    assert first["C"] == pytest.approx(0.3) and first["ZZZ"] == pytest.approx(0.2)
    assert res.dropped.loc[res.dropped["ticker"] == "A", "date"].iloc[0] == idx[8]
    # A (delisted before idx[8]) is dropped at the second rebalance: only B (0.4) is held
    assert d.loc[idx[8], "exposure"] == pytest.approx(0.4)
    assert "dropped" in caplog.text
    assert not (res.trades["ticker"].isin(["ZZZ", "C"])).any()


def test_nan_return_inside_a_series_is_a_zero_return_not_a_delisting():
    idx = make_index()
    a = np.full(len(idx), 0.01)
    a[4] = np.nan                                                    # gap, but valid prices later
    ret = pd.DataFrame({"A": a}, index=idx)
    tw = make_targets(idx, {0: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg())
    assert res.trades["reason"].tolist() == ["rebalance"]
    assert res.daily.loc[idx[4], "ret_gross"] == 0.0
    assert res.daily.loc[idx[5], "ret_gross"] == pytest.approx(0.01)
    assert (res.daily["n_holdings"] == 1).all()


def test_series_running_to_the_end_of_the_data_is_not_a_delisting():
    idx = make_index()
    ret = make_returns(idx, A=0.01)
    res = run(make_targets(idx, {0: {"A": 1.0}}), ret, zero_rf(idx), cfg())
    assert "delist" not in set(res.trades["reason"])


# --------------------------------------------------------------------------------------------------
# stop loss / trend exit
# --------------------------------------------------------------------------------------------------
def test_stop_loss_exits_at_trigger_close_and_no_reentry_until_next_rebalance():
    idx = make_index(16)
    a = np.zeros(16)
    a[1] = -0.30                    # before entry: must not count towards the stop
    a[3:6] = -0.05                  # cum: 0.95, 0.9025, 0.857375 -> -14.26% at idx[5] close
    a[6] = 0.20                     # earned by nobody (position is gone)
    a[9] = 0.10                     # re-entered at the idx[8] rebalance: earned
    ret = pd.DataFrame({"A": a}, index=idx)
    # signal idx[1] -> trade idx[2]; signal idx[7] -> trade idx[8]; 50% in A, rest cash
    tw = make_targets(idx, {1: {"A": 0.5}, 7: {"A": 0.5}})
    res = run(tw, ret, zero_rf(idx), cfg(cost_bps=10, stop_loss=0.14))
    d = res.daily
    stops = res.trades[res.trades["reason"] == "stop"]
    assert stops["date"].tolist() == [idx[5]]
    held_value = 0.5 * 0.857375
    w_before_sale = held_value / (held_value + 0.5)
    assert stops["weight_traded"].iloc[0] == pytest.approx(w_before_sale)
    assert stops["side"].iloc[0] == "sell"
    assert d.loc[idx[4], "n_holdings"] == 1                                  # -9.75%: not yet
    assert d.loc[idx[5], "ret_gross"] == pytest.approx(0.5 * 0.9025 * -0.05 / (0.5 * 0.9025 + 0.5))
    assert d.loc[idx[5], "cost"] == pytest.approx(10e-4 * w_before_sale)     # cost applies to the stop sale
    assert d.loc[idx[5], "turnover"] == pytest.approx(w_before_sale)
    assert d.loc[idx[5], "n_holdings"] == 0 and d.loc[idx[5], "cash_weight"] == pytest.approx(1.0)
    assert d.loc[idx[6], "ret_gross"] == 0.0 and d.loc[idx[6], "n_holdings"] == 0   # +20% not earned
    assert (d.loc[idx[6]:idx[7], "n_holdings"] == 0).all()                    # stays out until the rebalance
    assert d.loc[idx[8], "n_holdings"] == 1                                   # next rebalance re-enters
    assert d.loc[idx[9], "ret_gross"] == pytest.approx(0.5 * 0.10)


def test_stop_loss_threshold_is_inclusive_and_entry_reference_resets_at_rebalance():
    idx = make_index(16)
    a = np.zeros(16)
    a[3] = -0.10                    # exactly the stop (cum return = -10%) -> sold at idx[3]
    a[8] = -0.06                    # after the re-entry at idx[6]: -6% and -6% again -> -11.64% -> stop at idx[9]
    a[9] = -0.06
    ret = pd.DataFrame({"A": a}, index=idx)
    tw = make_targets(idx, {1: {"A": 1.0}, 5: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg(stop_loss=0.10))
    stops = res.trades[res.trades["reason"] == "stop"]["date"].tolist()
    assert stops == [idx[3], idx[9]]


def test_kept_name_entry_reference_resets_at_each_rebalance():
    idx = make_index(12)
    a = np.zeros(12)
    a[2] = -0.08                    # -8% since the first entry (idx[1]) ...
    a[5] = -0.05                    # ... but only -5% since the rebalance at idx[4]: no stop at 10%
    ret = pd.DataFrame({"A": a}, index=idx)
    tw = make_targets(idx, {0: {"A": 1.0}, 3: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg(stop_loss=0.10))
    assert "stop" not in set(res.trades["reason"])
    assert (res.daily["n_holdings"] == 1).all()


def test_trend_exit_sells_at_the_close_where_close_drops_below_sma():
    idx = make_index(12)
    ret = make_returns(idx, A=[0, 0, 0.01, 0.01, 0.01, 0.02, 0.10, 0.10])
    close = pd.DataFrame({"A": 100.0}, index=idx)
    sma = pd.DataFrame({"A": 90.0}, index=idx)
    close.iloc[5, 0] = 85.0         # below sma at idx[5]
    close.iloc[9, 0] = 85.0         # again later: nothing held -> no second trade
    tw = make_targets(idx, {0: {"A": 1.0}})
    c = cfg(cost_bps=10, trend_exit_daily=True)
    res = run(tw, ret, zero_rf(idx), c, close=close, sma=sma)
    tr = res.trades[res.trades["reason"] == "trend"]
    assert tr["date"].tolist() == [idx[5]]
    assert res.daily.loc[idx[5], "ret_gross"] == pytest.approx(0.02)         # still earned on the exit day
    assert res.daily.loc[idx[5], "cost"] == pytest.approx(10e-4 * 1.0)
    assert res.daily.loc[idx[6], "ret_gross"] == 0.0                         # +10% not earned
    assert res.daily.loc[idx[6], "n_holdings"] == 0
    # flag off -> never exits
    res2 = run(tw, ret, zero_rf(idx), cfg(trend_exit_daily=False), close=close, sma=sma)
    assert "trend" not in set(res2.trades["reason"])
    assert res2.daily.loc[idx[6], "ret_gross"] == pytest.approx(0.10)


def test_trend_exit_nan_sma_means_no_exit_and_flag_needs_frames():
    idx = make_index(8)
    ret = make_returns(idx, A=0.01)
    close = pd.DataFrame({"A": 80.0}, index=idx)
    sma = pd.DataFrame({"A": np.nan}, index=idx)
    tw = make_targets(idx, {0: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg(trend_exit_daily=True), close=close, sma=sma)
    assert "trend" not in set(res.trades["reason"])
    with pytest.raises(ValueError):
        run(tw, ret, zero_rf(idx), cfg(trend_exit_daily=True))


def test_stop_and_trend_both_apply_and_stop_has_priority_in_the_log():
    idx = make_index(10)
    ret = make_returns(idx, A=[0, 0, -0.2, 0.0], B=[0, 0, 0.0, -0.01])
    close = pd.DataFrame({"A": 100.0, "B": 100.0}, index=idx)
    sma = pd.DataFrame({"A": 90.0, "B": 90.0}, index=idx)
    close.iloc[2, 0] = 80.0
    close.iloc[3, 1] = 80.0
    tw = make_targets(idx, {0: {"A": 0.5, "B": 0.5}})
    res = run(tw, ret, zero_rf(idx), cfg(stop_loss=0.15, trend_exit_daily=True), close=close, sma=sma)
    got = res.trades[res.trades["reason"].isin(["stop", "trend"])].set_index("ticker")["reason"].to_dict()
    assert got == {"A": "stop", "B": "trend"}


# --------------------------------------------------------------------------------------------------
# vol targeting
# --------------------------------------------------------------------------------------------------
def _vol_returns(n=70, sig=40, lookback=20, a_sign=1.0, early=0.30, late=0.90):
    """A alternates +-1% inside the lookback window [sig-lookback+1, sig]; garbage before and after."""
    r = np.empty(n)
    r[:sig - lookback + 1] = early
    r[sig + 1:] = late
    k = np.arange(sig - lookback + 1, sig + 1)
    r[k] = a_sign * np.where((k - k[0]) % 2 == 0, 0.01, -0.01)
    return r


def test_vol_scalar_hand_value_and_only_past_data():
    idx = make_index(70)
    ret = pd.DataFrame({"A": _vol_returns()}, index=idx)
    tw = make_targets(idx, {40: {"A": 1.0}})
    c = cfg(vol_target=0.10, vol_lookback=20)
    res = run(tw, ret, zero_rf(idx), c)
    vol = np.sqrt(252 * 1e-4)                                    # uncentered: every |r| = 1%
    expected = 0.10 / vol
    assert expected == pytest.approx(0.62994, abs=1e-5)
    trade_day = idx[41]
    assert res.daily.index[0] == trade_day
    assert res.daily.loc[trade_day, "vol_scalar"] == pytest.approx(expected)
    assert res.daily.loc[trade_day, "exposure"] == pytest.approx(expected)
    assert res.daily.loc[trade_day, "cash_weight"] == pytest.approx(1 - expected)
    assert res.weights.loc[trade_day, "A"] == pytest.approx(expected)
    # changing anything outside [t-L+1, t] must not move the scalar
    ret2 = ret.copy()
    ret2.iloc[:20, 0] = -0.5
    ret2.iloc[41:, 0] = np.random.default_rng(0).normal(0, 0.2, 29)
    res2 = run(tw, ret2, zero_rf(idx), c)
    assert res2.daily.loc[trade_day, "vol_scalar"] == pytest.approx(expected)
    # changing the last in-window observation (the signal day itself) does move it
    ret3 = ret.copy()
    ret3.iloc[40, 0] = 0.05
    res3 = run(tw, ret3, zero_rf(idx), c)
    assert res3.daily.loc[trade_day, "vol_scalar"] != pytest.approx(expected)
    m = np.mean(np.r_[np.full(19, 1e-4), 0.05 ** 2])
    assert res3.daily.loc[trade_day, "vol_scalar"] == pytest.approx(0.10 / np.sqrt(252 * m))


def test_vol_scalar_is_capped_and_uses_book_weights():
    idx = make_index(70)
    ret = pd.DataFrame({"A": _vol_returns(), "B": _vol_returns(a_sign=-1.0)}, index=idx)
    # hedged book: A and B offset exactly -> zero book vol -> scalar = vol_cap
    tw = make_targets(idx, {40: {"A": 0.5, "B": 0.5}})
    res = run(tw, ret, zero_rf(idx), cfg(vol_target=0.10, vol_lookback=20))
    assert res.daily["vol_scalar"].iloc[0] == pytest.approx(1.0)
    # half-weight single asset: book returns = +-0.5% -> vol = 0.5*0.158745 = 0.0793725 -> 0.1/vol = 1.2599
    tw2 = make_targets(idx, {40: {"A": 0.5}})
    res2 = run(tw2, ret, zero_rf(idx), cfg(vol_target=0.10, vol_lookback=20, vol_cap=1.0))
    assert res2.daily["vol_scalar"].iloc[0] == pytest.approx(1.0)               # capped
    res3 = run(tw2, ret, zero_rf(idx), cfg(vol_target=0.10, vol_lookback=20, vol_cap=2.0))
    expected = 0.10 / (0.5 * np.sqrt(252 * 1e-4))
    assert res3.daily["vol_scalar"].iloc[0] == pytest.approx(expected)
    assert res3.daily["exposure"].iloc[0] == pytest.approx(0.5 * expected)       # weights scaled, rest cash
    # a higher target than the vol -> capped at 1 when the cap is 1
    res4 = run(make_targets(idx, {40: {"A": 1.0}}), ret, zero_rf(idx),
               cfg(vol_target=0.50, vol_lookback=20))
    assert res4.daily["vol_scalar"].iloc[0] == pytest.approx(1.0)
    # same-sign two-asset book has the single-asset vol
    ret_same = pd.DataFrame({"A": _vol_returns(), "B": _vol_returns()}, index=idx)
    res5 = run(make_targets(idx, {40: {"A": 0.5, "B": 0.5}}), ret_same, zero_rf(idx),
               cfg(vol_target=0.10, vol_lookback=20))
    assert res5.daily["vol_scalar"].iloc[0] == pytest.approx(0.10 / np.sqrt(252 * 1e-4))


def test_vol_scalar_without_enough_history_is_one_and_off_by_default():
    idx = make_index(70)
    ret = pd.DataFrame({"A": _vol_returns()}, index=idx)
    res = run(make_targets(idx, {10: {"A": 1.0}}), ret, zero_rf(idx),
              cfg(vol_target=0.05, vol_lookback=20))
    assert res.daily["vol_scalar"].iloc[0] == pytest.approx(1.0)                 # only 11 observations
    res0 = run(make_targets(idx, {40: {"A": 1.0}}), ret, zero_rf(idx), cfg())
    assert (res0.daily["vol_scalar"] == 1.0).all()
    assert res0.daily["exposure"].iloc[0] == pytest.approx(1.0)


def test_vol_scalar_applied_at_every_rebalance_and_recorded_between():
    idx = make_index(70)
    r = _vol_returns()
    ret = pd.DataFrame({"A": r}, index=idx)
    tw = make_targets(idx, {30: {"A": 1.0}, 45: {"A": 1.0}})
    res = run(tw, ret, zero_rf(idx), cfg(vol_target=0.10, vol_lookback=20))
    d = res.daily
    s1, s2 = d.loc[idx[31], "vol_scalar"], d.loc[idx[46], "vol_scalar"]
    assert d.loc[idx[31]:idx[45], "vol_scalar"].eq(s1).all()
    assert d.loc[idx[46]:, "vol_scalar"].eq(s2).all()
    window = r[26:46]
    assert s2 == pytest.approx(min(1.0, 0.10 / np.sqrt(252 * np.mean(window ** 2))))
    assert d.loc[idx[46], "exposure"] == pytest.approx(s2)


# --------------------------------------------------------------------------------------------------
# sleeves
# --------------------------------------------------------------------------------------------------
def _random_case(seed=3, T=260, n=6, step=21, rf_level=0.0001, with_nan=False):
    rng = np.random.default_rng(seed)
    idx = make_index(T)
    ret = pd.DataFrame(rng.normal(0.0004, 0.015, (T, n)), index=idx, columns=list("ABCDEFGH"[:n]))
    rows = {}
    for p in range(10, T - 5, step):
        w = rng.dirichlet(np.ones(n)) * rng.uniform(0.6, 1.0)
        w[rng.random(n) < 0.4] = 0.0
        rows[p] = dict(zip(ret.columns, w))
    return idx, ret, make_targets(idx, rows), pd.Series(rf_level, index=idx)


def test_sleeves_hold_one_equals_run():
    idx, ret, tw, rf = _random_case()
    c = BacktestConfig(cost_bps=15, stop_loss=0.06, vol_target=0.05, vol_lookback=30)
    a = run(tw, ret, rf, c)
    b = run_sleeves(tw, 1, ret, rf, c)
    assert (a.trades["reason"] == "stop").any()
    assert a.daily["vol_scalar"].nunique() > 1
    pd.testing.assert_frame_equal(a.daily, b.daily)
    pd.testing.assert_frame_equal(a.weights, b.weights)
    pd.testing.assert_frame_equal(a.trades, b.trades)


def test_sleeves_hold_one_equals_run_with_delist_and_trend():
    idx, ret, tw, rf = _random_case(seed=5)
    rows_with_b = [d for d in tw.index if tw.loc[d, "B"] > 0 and d > idx[100]]
    pos = idx.get_loc(rows_with_b[0]) + 2                       # first NaN = the day after the trade day
    ret.iloc[pos:, 1] = np.nan                                  # B delists
    close = (1 + ret.fillna(0)).cumprod() * 100
    sma = close.rolling(60, min_periods=60).mean()
    c = BacktestConfig(cost_bps=10, trend_exit_daily=True, stop_loss=0.04)
    a = run(tw, ret, rf, c, close=close, sma=sma)
    b = run_sleeves(tw, 1, ret, rf, c, close=close, sma=sma)
    pd.testing.assert_frame_equal(a.daily, b.daily)
    pd.testing.assert_frame_equal(a.trades, b.trades)
    assert (a.trades["reason"] == "delist").any()
    assert (a.trades["reason"] == "stop").any() and (a.trades["reason"] == "trend").any()


def test_sleeves_three_sleeve_hand_calculation():
    idx = make_index(12)
    ret = make_returns(idx, A=0.10, B=0.0, C=-0.10)
    # signals idx[1], [3], [5], [7] -> trades at idx[2], [4], [6], [8] (lag 1); capital split over live sleeves
    tw = make_targets(idx, {1: {"A": 1.0}, 3: {"B": 1.0}, 5: {"C": 1.0}, 7: {"A": 1.0}})
    res = run_sleeves(tw, 3, ret, zero_rf(idx), cfg(cost_bps=10))
    d, w = res.daily, res.weights
    assert d.index[0] == idx[2]
    # trade 0 (idx[2]): 100% A
    assert d.loc[idx[2], "cost"] == pytest.approx(10e-4)
    assert d.loc[idx[3], "ret_gross"] == pytest.approx(0.10)
    # trade 1 (idx[4]): two sleeves, 50% each; sells half of A, buys B
    assert d.loc[idx[4], "ret_gross"] == pytest.approx(0.10)
    assert d.loc[idx[4], "turnover"] == pytest.approx(0.5)
    assert d.loc[idx[4], "cost"] == pytest.approx(10e-4)                    # sum|dw| = 0.5 + 0.5
    assert w.loc[idx[4], "A"] == pytest.approx(0.5) and w.loc[idx[4], "B"] == pytest.approx(0.5)
    # day idx[5]: 50% A earning 10%
    assert d.loc[idx[5], "ret_gross"] == pytest.approx(0.05)
    assert w.loc[idx[5], "A"] == pytest.approx(0.55 / 1.05)
    # trade 2 (idx[6]): three sleeves, each 1/3 of NAV; sleeve A = 0.605 / sleeve B = 0.5 before equalizing
    g6 = 0.055 / 1.05
    assert d.loc[idx[6], "ret_gross"] == pytest.approx(g6)
    pre_a, pre_b = 0.605 / 1.105, 0.5 / 1.105
    sum_abs = abs(1 / 3 - pre_a) + abs(1 / 3 - pre_b) + 1 / 3
    assert sum_abs == pytest.approx(2 / 3)
    assert d.loc[idx[6], "turnover"] == pytest.approx(1 / 3)
    assert d.loc[idx[6], "cost"] == pytest.approx(10e-4 * sum_abs)
    for t in "ABC":
        assert w.loc[idx[6], t] == pytest.approx(1 / 3)
    # day idx[7]: (0.1 + 0 - 0.1)/3 = 0
    assert d.loc[idx[7], "ret_gross"] == pytest.approx(0.0, abs=1e-15)
    # trade 3 (idx[8]): the first sleeve (A) closes, a new A sleeve opens; others re-equalized to 1/3
    nav8 = (1 / 3) * 1.1 ** 2 + 1 / 3 + (1 / 3) * 0.9 ** 2
    assert d.loc[idx[8], "ret_gross"] == pytest.approx(nav8 - 1)
    pa, pb, pc = (1 / 3) * 1.21 / nav8, (1 / 3) / nav8, (1 / 3) * 0.81 / nav8
    sum_abs8 = abs(1 / 3 - pa) + abs(1 / 3 - pb) + abs(1 / 3 - pc)
    assert d.loc[idx[8], "turnover"] == pytest.approx(0.5 * sum_abs8)
    assert d.loc[idx[8], "cost"] == pytest.approx(10e-4 * sum_abs8)
    for t in "ABC":
        assert w.loc[idx[8], t] == pytest.approx(1 / 3)
    t8 = res.trades[res.trades["date"] == idx[8]].set_index("ticker")
    assert t8.loc["A", "side"] == "sell" and t8.loc["A", "weight_traded"] == pytest.approx(pa - 1 / 3)
    assert t8.loc["B", "side"] == "buy" and t8.loc["C", "side"] == "buy"
    # no cash anywhere: fully invested in the sleeves
    assert d["cash_weight"].abs().max() < 1e-12


def _reference_sleeves(tw, hold, ret, rf, cost_bps, lag):
    """Plain dollar-based reference: per-sleeve holdings, re-equalised at every trade day."""
    idx = ret.index
    trades = {}
    for dt, row in tw.iterrows():
        pos = idx.searchsorted(dt, side="right") - 1
        trades[pos + lag] = row
    d0 = min(trades)
    sleeves = []                          # list of (stock dollars array, cash dollars)
    nav = 1.0
    idle = 1.0
    out = []
    cols = list(ret.columns)
    for d in range(d0, len(idx)):
        r = ret.iloc[d].fillna(0.0).to_numpy()
        f = rf.iloc[d]
        sleeves = [(s * (1 + r), c * (1 + f)) for s, c in sleeves]
        idle *= 1 + f
        gross_nav = sum(s.sum() + c for s, c in sleeves) + idle
        g = gross_nav / nav - 1
        cost = turn = 0.0
        if d in trades:
            pre = sum((s for s, _ in sleeves), np.zeros(len(cols))) / gross_nav
            pre_cash = (sum(c for _, c in sleeves) + idle) / gross_nav
            row = trades[d].to_numpy(dtype=float)
            sleeves = sleeves[-(hold - 1):] if hold > 1 else []
            idle = 0.0
            k = len(sleeves) + 1
            sleeves = [(s * (gross_nav / k) / (s.sum() + c), c * (gross_nav / k) / (s.sum() + c)) for s, c in sleeves]
            sleeves.append((row * gross_nav / k, (1 - row.sum()) * gross_nav / k))
            post = sum((s for s, _ in sleeves), np.zeros(len(cols))) / gross_nav
            post_cash = sum(c for _, c in sleeves) / gross_nav
            sum_abs = np.abs(post - pre).sum()
            cost = cost_bps / 1e4 * sum_abs
            turn = 0.5 * (sum_abs + abs(post_cash - pre_cash))
        nav_next = nav * (1 + g - cost)
        scale = nav_next / gross_nav
        sleeves = [(s * scale, c * scale) for s, c in sleeves]
        idle *= scale
        nav = nav_next
        out.append((idx[d], g, g - cost, cost, turn))
    return pd.DataFrame(out, columns=["date", "ret_gross", "ret_net", "cost", "turnover"]).set_index("date")


@pytest.mark.parametrize("hold", [2, 3, 5, 12])
def test_sleeves_match_independent_dollar_reference(hold):
    idx, ret, tw, rf = _random_case(seed=11 + hold, T=300, step=15)
    res = run_sleeves(tw, hold, ret, rf, BacktestConfig(cost_bps=12))
    ref = _reference_sleeves(tw, hold, ret, rf, 12, 1)
    assert res.daily.index.equals(ref.index)
    for col in ["ret_gross", "ret_net", "cost", "turnover"]:
        np.testing.assert_allclose(res.daily[col], ref[col], rtol=1e-9, atol=1e-11, err_msg=col)
    np.testing.assert_allclose(res.daily["exposure"] + res.daily["cash_weight"], 1.0, atol=1e-12)


def test_sleeves_warmup_splits_capital_over_existing_sleeves_and_stop_is_per_sleeve():
    idx = make_index(16)
    a = np.zeros(16)
    a[3] = -0.20                                       # hits sleeve 0 (A, opened idx[2]) right after entry
    ret = pd.DataFrame({"A": a, "B": 0.01}, index=idx)
    tw = make_targets(idx, {1: {"A": 1.0}, 6: {"B": 1.0}})
    res = run_sleeves(tw, 2, ret, zero_rf(idx), cfg(cost_bps=10, stop_loss=0.10))
    d, w = res.daily, res.weights
    stop = res.trades[res.trades["reason"] == "stop"]
    assert stop["date"].tolist() == [idx[3]] and stop["ticker"].tolist() == ["A"]
    assert d.loc[idx[3], "ret_gross"] == pytest.approx(-0.20)
    assert d.loc[idx[3], "cost"] == pytest.approx(10e-4 * 1.0)             # whole book was A
    assert d.loc[idx[3], "n_holdings"] == 0
    # trade at idx[7]: 2 sleeves -> 50% cash (stopped sleeve) / 50% B
    assert d.loc[idx[7], "exposure"] == pytest.approx(0.5)
    assert w.loc[idx[7], "B"] == pytest.approx(0.5)
    assert d.loc[idx[7], "turnover"] == pytest.approx(0.5)
    assert d.loc[idx[7], "cost"] == pytest.approx(10e-4 * 0.5)
    assert d.loc[idx[8], "ret_gross"] == pytest.approx(0.5 * 0.01)


def test_sleeves_drop_old_sleeve_after_hold_months_signals():
    idx = make_index(20)
    ret = make_returns(idx, A=0.0, B=0.0, C=0.0)
    tw = make_targets(idx, {0: {"A": 1.0}, 3: {"B": 1.0}, 6: {"C": 1.0}})
    res = run_sleeves(tw, 2, ret, zero_rf(idx), cfg())
    w = res.weights
    assert w.loc[idx[4], "A"] == pytest.approx(0.5) and w.loc[idx[4], "B"] == pytest.approx(0.5)
    assert w.loc[idx[7], "B"] == pytest.approx(0.5) and w.loc[idx[7], "C"] == pytest.approx(0.5)
    assert w.loc[idx[7], "A"] == 0.0                                       # sleeve A closed on the 2nd following signal


# --------------------------------------------------------------------------------------------------
# monthly(), validation, performance
# --------------------------------------------------------------------------------------------------
def test_monthly_compounds_to_calendar_month_ends():
    idx = pd.bdate_range("2020-01-27", "2020-03-05")
    daily = pd.DataFrame({"ret_net": 0.01}, index=idx)
    res = BacktestResult(daily=daily, weights=pd.DataFrame(index=idx), trades=pd.DataFrame())
    m = res.monthly()
    assert list(m.index) == [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29"), pd.Timestamp("2020-03-31")]
    n_jan = ((idx.month == 1)).sum()
    n_feb = ((idx.month == 2)).sum()
    assert m.iloc[0] == pytest.approx(1.01 ** n_jan - 1)
    assert m.iloc[1] == pytest.approx(1.01 ** n_feb - 1)
    assert (1 + m).prod() == pytest.approx(1.01 ** len(idx))


def test_monthly_from_engine_run():
    idx = pd.bdate_range("2020-01-02", "2020-03-31")
    ret = pd.DataFrame({"A": 0.001}, index=idx)
    tw = pd.DataFrame({"A": [1.0]}, index=[idx[0]])
    res = run(tw, ret, zero_rf(idx), cfg(exec_lag=0))
    m = res.monthly()
    assert len(m) == 3
    assert (1 + m).prod() == pytest.approx((1 + res.daily["ret_net"]).prod())


def test_input_validation():
    idx = make_index()
    ret = make_returns(idx, A=0.0)
    ok = make_targets(idx, {0: {"A": 1.0}})
    with pytest.raises(ValueError):
        run(make_targets(idx, {0: {"A": 0.7, "B": 0.5}}), ret, zero_rf(idx), cfg())
    with pytest.raises(ValueError):
        run(make_targets(idx, {0: {"A": 1.2, "B": -0.2}}), ret, zero_rf(idx), cfg())
    with pytest.raises(ValueError):
        BacktestConfig(exec_lag=-1)
    with pytest.raises(ValueError):
        BacktestConfig(stop_loss=1.5)
    with pytest.raises(ValueError):
        BacktestConfig(vol_target=-0.1)
    with pytest.raises(ValueError):
        run_sleeves(ok, 0, ret, zero_rf(idx), cfg())
    dup = pd.concat([ok, ok])
    with pytest.raises(ValueError):
        run(dup, ret, zero_rf(idx), cfg())


def test_nan_target_weights_are_zero_and_unsorted_inputs_are_handled():
    idx = make_index()
    ret = make_returns(idx, A=0.01, B=0.02)
    tw = pd.DataFrame({"A": [0.5, np.nan], "B": [np.nan, 0.5]}, index=[idx[6], idx[2]])   # unsorted rows
    res = run(tw, ret.iloc[::-1], zero_rf(idx), cfg())                                   # unsorted returns
    assert res.trades["date"].iloc[0] == idx[3]
    assert res.weights.loc[idx[3], "B"] == pytest.approx(0.5)


def test_performance_15y_3000_tickers_30_names_monthly():
    rng = np.random.default_rng(0)
    T, N = 3780, 3000
    idx = pd.bdate_range("2008-01-01", periods=T)
    cols = [f"T{i:04d}" for i in range(N)]
    ret = pd.DataFrame(rng.normal(0.0003, 0.02, (T, N)), index=idx, columns=cols)
    month_end = pd.Series(idx, index=idx).groupby([idx.year, idx.month]).last().tolist()[12:-1]
    w = np.zeros((len(month_end), N))
    for i in range(len(month_end)):
        w[i, rng.choice(N, 30, replace=False)] = 1 / 30
    tw = pd.DataFrame(w, index=month_end, columns=cols)
    rf = pd.Series(0.00008, index=idx)
    t0 = time.perf_counter()
    res = run(tw, ret, rf, BacktestConfig(cost_bps=10, stop_loss=0.15, vol_target=0.2))
    elapsed = time.perf_counter() - t0
    assert elapsed < 5.0, f"run took {elapsed:.2f}s"
    assert len(res.daily) > 3000 and (res.daily["n_holdings"] > 0).mean() > 0.9
    t0 = time.perf_counter()
    run_sleeves(tw, 12, ret, rf, BacktestConfig(cost_bps=10))
    assert time.perf_counter() - t0 < 10.0
