"""Tests for the exit plan dates, forward returns, holding stats and the top-K order split."""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant import exits
from quant.trade_plan import top_k

T = pd.Timestamp


@pytest.mark.parametrize("d, expected", [
    ("2026-10-21", "2026-10-30"),        # Friday Oct 30 is the last trading day of October 2026
    ("2026-10-30", "2026-10-30"),
    ("2027-05-03", "2027-05-28"),        # May 31 2027 is Memorial Day
    ("2026-12-15", "2026-12-31"),
    ("2027-12-01", "2027-12-31"),        # New Year's 2028 falls on a Saturday: no Friday holiday on Dec 31
])
def test_month_end_on_or_after(d, expected):
    assert exits.month_end_on_or_after(d) == T(expected)


def test_next_trading_day_skips_weekends_and_holidays():
    assert exits.next_trading_day("2026-10-30") == T("2026-11-02")
    assert exits.next_trading_day("2026-11-25") == T("2026-11-27")      # Thanksgiving


def test_exit_plan_momentum_reviews_at_month_end_and_mf_holds_twelve_months():
    qm = exits.exit_plan("quality_momentum", "2026-10-21")
    assert qm["first_review"] == T("2026-10-30") and pd.isna(qm["planned_sale"])
    mf = exits.exit_plan("magic_formula", "2026-10-21")
    assert mf["first_review"] == T("2027-10-29") and mf["planned_sale"] == T("2027-11-01")


def test_review_after_counts_month_end_reviews():
    assert exits.review_after("2026-10-21", 1) == T("2026-10-30")
    assert exits.review_after("2026-10-21", 3) == T("2026-12-31")
    assert exits.review_after("2026-10-30", 1) == T("2026-11-30")        # bought on a review day: next one


def test_fwd_returns_exits_a_delisted_name_at_its_last_price():
    idx = pd.bdate_range("2024-01-01", periods=5)
    P = pd.DataFrame({"A": [10, 11, 12, 13, 14.0], "B": [20, 22, np.nan, np.nan, np.nan],
                      "C": [np.nan, 5, 5, 5, 5.0]}, index=idx)
    r = exits.fwd_returns(P, ["A", "B", "C", "Z"], idx[0], idx[-1])
    assert r["A"] == pytest.approx(0.4) and r["B"] == pytest.approx(0.1)
    assert "C" not in r.index and "Z" not in r.index                    # no price on the entry day / unknown


def test_summarize_splits_top_picks_and_windows():
    rows = pd.DataFrame({
        "strategy": "magic_formula", "horizon": "to_exit", "rank": [1, 2, 7, 1],
        "entry": [T("2015-01-02"), T("2015-01-02"), T("2015-01-02"), T("2020-01-02")],
        "months": 12, "ret": [0.10, -0.05, 0.30, 0.20], "universe": [0.05, 0.05, 0.05, 0.10]})
    s = exits.summarize(rows).set_index(["picks", "window"])
    assert s.loc[("top5", "2011-2026"), "n"] == 3
    assert s.loc[("top5", "2011-2026"), "mean"] == pytest.approx(0.25 / 3, abs=1e-4)
    assert s.loc[("all", "2019-2026"), "mean_vs_universe"] == pytest.approx(0.10)
    assert s.loc[("all", "2011-2026"), "pct_positive"] == pytest.approx(0.75)


def test_top_k_gives_each_list_k_different_names():
    lists = {"qm": ["TGT", "CROX", "MRK", "MU", "ILMN", "BMY", "RS"],
             "mf": ["GEN", "CROX", "MO", "MU", "INCY", "BMY", "SAIC"]}
    out = top_k(lists, 5)
    assert out["qm"] == ["TGT", "CROX", "MRK", "ILMN", "BMY"]          # CROX tie -> qm, MU tie -> mf, BMY -> qm
    assert out["mf"] == ["GEN", "MO", "MU", "INCY", "SAIC"]
    assert not set(out["qm"]) & set(out["mf"])


def test_top_k_higher_rank_wins_a_shared_name():
    out = top_k({"a": ["X", "Y", "S"], "b": ["S", "Z", "W"]}, 2)
    assert out == {"a": ["X", "Y"], "b": ["S", "Z"]}
    out = top_k({"a": ["S", "Y", "V"], "b": ["Z", "W", "S"]}, 3)
    assert out == {"a": ["S", "Y", "V"], "b": ["Z", "W"]}                # b ran out of names: fewer than k
