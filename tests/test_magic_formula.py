"""Tests for quant.strategies.magic_formula on synthetic data (no cache files needed).

The context is the real ``DataContext`` (so ``market_cap``, split handling, ``month_ends`` are the production
code) with ``fundamentals`` and ``universe`` replaced by in-memory versions that follow the same PIT rules
(``filed < date``, ``period_end >= date - max_age_days``).
"""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant.backtest import engine, grid
from quant.data.context import DataContext
from quant.strategies import magic_formula as mf

T0 = pd.Timestamp("2012-06-29")
NO_SPLITS = pd.DataFrame({"yf_ticker": pd.Series(dtype=object), "date": pd.Series(dtype="datetime64[ns]"),
                          "ratio": pd.Series(dtype=float)})


# ------------------------------------------------------------------------------------------------
# synthetic world
# ------------------------------------------------------------------------------------------------
class FakeCtx(DataContext):
    def __init__(self, close, snaps, members, splits=None):
        returns = close.pct_change()
        rf = pd.Series(0.0, index=close.index)
        super().__init__(close, close, close * 0 + 1e6, returns, rf, snaps,
                         NO_SPLITS if splits is None else splits)
        self.members = members

    def fundamentals(self, date, max_age_days=200):
        date = pd.Timestamp(date)
        s = self.snaps
        s = s[(s["filed"] < date) & (s["period_end"] >= date - pd.Timedelta(days=max_age_days))]
        s = s.sort_values(["filed", "period_end"]).groupby("cik").tail(1)
        return s.set_index("cik")

    def universe(self, date, name="SP1500"):
        date = self.trading_day_on_or_before(date)
        m = self.members[name] if isinstance(self.members, dict) else self.members
        m = m[m["yf_ticker"].isin(self.close.columns)]
        px = self.close.loc[date, m["yf_ticker"]].to_numpy()
        return m[np.isfinite(px) & (px > 0)].reset_index(drop=True)


def snap(cik, filed="2012-05-10", period_end="2012-03-31", **kw):
    row = dict(cik=cik, accn=f"a{cik}", form="10-Q", filed=pd.Timestamp(filed), period_end=pd.Timestamp(period_end),
               fiscal_period="Q1", opinc=84.0, pretax=80.0, interest_exp=4.0, gross_profit=300.0, assets=1000.0,
               current_assets=500.0, current_liabilities=300.0, cash=100.0, st_investments=50.0, ppe_net=200.0,
               debt_current=20.0, op_lease_current=10.0, total_debt=300.0, preferred=20.0, minority_interest=-5.0,
               shares_out=100.0, shares_out_date=pd.Timestamp(period_end) + pd.Timedelta(days=30),
               shares_diluted=100.0, flags="")
    row.update(kw)
    return row


def member(cik, tick, sector="Information Technology", sic=3570, name=None):
    return dict(cik=cik, yf_ticker=tick, name=name or f"Co{cik}", gics_sector=sector, sic=sic)


def flat_close(tickers, px=10.0, start="2012-01-02", end="2012-12-31"):
    d = pd.bdate_range(start, end)
    return pd.DataFrame({t: px for t in tickers} if np.isscalar(px) else px, index=d).astype(float)


def one_firm_ctx(**snap_kw):
    ctx_kw = {k: snap_kw.pop(k) for k in ("sector", "sic") if k in snap_kw}
    snaps = pd.DataFrame([snap(1, **snap_kw)])
    mem = pd.DataFrame([member(1, "A", **ctx_kw)])
    return FakeCtx(flat_close(["A"]), snaps, mem)


P = dict(min_cap=1e3, n=1)       # tiny cap floor so the default fixture (mcap = 10 * 100 = 1000) is eligible


def row_of(ctx, **params):
    t = mf.mf_table(ctx, T0, None, {**P, **params})
    return t.loc[1]


# ------------------------------------------------------------------------------------------------
# formula arithmetic
# ------------------------------------------------------------------------------------------------
def test_roc_ey_arithmetic_with_excess_cash():
    r = row_of(one_firm_ctx())
    # cash 150, CA-CL 200 -> excess 150;  NWC = (500-150) - (300-20-10) = 80;  capital = 80 + 200 = 280
    assert r["cash_st"] == 150.0
    assert r["excess_cash"] == 150.0
    assert r["nwc"] == 80.0
    assert r["capital"] == 280.0
    assert r["roc"] == pytest.approx(84.0 / 280.0)
    # mcap 10 * 100 = 1000;  EV = 1000 + pref 20 + max(0, -5) + debt 300 - excess 150
    assert r["mcap"] == pytest.approx(1000.0)
    assert r["minority_interest"] == 0.0 and r["minority_interest_raw"] == -5.0
    assert r["ev"] == pytest.approx(1170.0)
    assert r["ey"] == pytest.approx(84.0 / 1170.0)
    assert bool(r["eligible"])


def test_excess_cash_limited_by_current_surplus_and_zero_when_ca_below_cl():
    r = row_of(one_firm_ctx(current_assets=400.0, current_liabilities=350.0))     # CA-CL = 50 < cash 150
    assert r["excess_cash"] == 50.0
    assert r["nwc"] == (400 - 50) - (350 - 20 - 10)                                  # 30
    r = row_of(one_firm_ctx(current_assets=400.0, current_liabilities=450.0))      # CA < CL
    assert r["excess_cash"] == 0.0


def test_positive_nci_and_preferred_enter_ev_negative_nci_is_floored():
    r = row_of(one_firm_ctx(minority_interest=40.0, preferred=10.0))
    assert r["ev"] == pytest.approx(1000 + 10 + 40 + 300 - 150)
    r = row_of(one_firm_ctx(minority_interest=-400.0, preferred=0.0))
    assert r["ev"] == pytest.approx(1000 + 0 + 0 + 300 - 150)


def test_nwc_floored_at_zero_and_capital_is_ppe_only():
    r = row_of(one_firm_ctx(current_assets=300.0, current_liabilities=600.0, cash=0.0, st_investments=0.0,
                            debt_current=0.0, op_lease_current=0.0))
    assert r["nwc_raw"] == -300.0 and r["nwc"] == 0.0
    assert r["capital"] == 200.0
    assert r["roc"] == pytest.approx(84.0 / 200.0)
    assert not bool(r["capital_floored"])


def test_capital_floor_is_one_percent_of_assets():
    r = row_of(one_firm_ctx(current_assets=300.0, current_liabilities=600.0, cash=0.0, st_investments=0.0,
                            ppe_net=1.0, assets=2000.0))
    assert r["capital"] == pytest.approx(20.0)                       # 1% of 2000 beats NWC 0 + PPE 1
    assert bool(r["capital_floored"])
    assert r["roc"] == pytest.approx(84.0 / 20.0)


def test_missing_ppe_uses_conservative_noncurrent_tangible_proxy_with_flag():
    # missing PP&E -> assets - current assets - goodwill - intangibles (an upper bound: ROC can only go down)
    r = row_of(one_firm_ctx(current_assets=300.0, current_liabilities=600.0, cash=0.0, st_investments=0.0,
                            ppe_net=np.nan, assets=2000.0))
    assert bool(r["ppe_missing"])
    assert r["ppe_net"] == pytest.approx(2000.0 - 300.0)
    assert r["capital"] == pytest.approx(1700.0)
    assert not bool(r["capital_floored"])
    assert r["roc"] == pytest.approx(84.0 / 1700.0)


def test_operating_lease_and_current_debt_are_stripped_from_current_liabilities():
    a = row_of(one_firm_ctx(op_lease_current=0.0, debt_current=0.0))
    b = row_of(one_firm_ctx(op_lease_current=30.0, debt_current=50.0))
    assert b["nwc"] == pytest.approx(a["nwc"] + 80.0)                # CL net of financing items is smaller -> NWC larger


def test_all_cash_excess_cash_variant_and_pretax_interest_ebit_variant():
    ctx = one_firm_ctx(current_assets=400.0, current_liabilities=350.0)   # min rule -> 50, all_cash -> 150
    assert row_of(ctx, excess_cash="all_cash")["excess_cash"] == 150.0
    assert row_of(ctx, excess_cash="min_ca_cl")["excess_cash"] == 50.0
    r = row_of(ctx, ebit="pretax_interest")
    assert r["ebit_ttm"] == 84.0                                      # pretax 80 + interest 4
    r = row_of(one_firm_ctx(opinc=10.0), ebit="pretax_interest")
    assert r["ebit_ttm"] == 84.0 and row_of(one_firm_ctx(opinc=10.0))["ebit_ttm"] == 10.0


def test_ratio2_excess_cash_variant():
    ctx = one_firm_ctx(current_assets=900.0, current_liabilities=300.0)   # CA > 2 CL: min(150, 300) = 150
    assert row_of(ctx, excess_cash="ratio2")["excess_cash"] == 150.0
    ctx = one_firm_ctx(current_assets=500.0, current_liabilities=300.0)   # CA < 2 CL: 0
    assert row_of(ctx, excess_cash="ratio2")["excess_cash"] == 0.0


# ------------------------------------------------------------------------------------------------
# ranking
# ------------------------------------------------------------------------------------------------
def fake_base(roc, ey, mcap=None, gpa=None):
    n = len(roc)
    idx = pd.Index(range(1, n + 1), name="cik")
    b = pd.DataFrame({"roc": roc, "ey": ey, "gpa": gpa if gpa is not None else [np.nan] * n,
                      "mcap": mcap if mcap is not None else [1e9] * n, "ok_struct": True}, index=idx, dtype=float)
    b["ok_struct"] = True
    for r in mf._STRUCTURAL:
        b[f"fail_{r}"] = False
    return b


def test_rank_sum_with_average_ties_and_tiebreak_by_ey():
    b = fake_base(roc=[0.5, 0.4, 0.4, 0.3, 0.2], ey=[0.1, 0.2, 0.05, 0.3, 0.3])
    t = mf._finish(b, mf._params({"n": 2, "min_cap": 0}))
    assert t["rank_roc"].to_dict() == {1: 1.0, 2: 2.5, 3: 2.5, 4: 4.0, 5: 5.0}
    assert t["rank_ey"].to_dict() == {1: 4.0, 2: 3.0, 3: 5.0, 4: 1.5, 5: 1.5}
    assert t["score"].to_dict() == {1: 5.0, 2: 5.5, 3: 7.5, 4: 5.5, 5: 6.5}
    # scores 2 and 4 tie at 5.5: higher EY (firm 4) goes first
    assert t["final_rank"].to_dict() == {1: 1.0, 4: 2.0, 2: 3.0, 5: 4.0, 3: 5.0}
    assert list(t.index[:2]) == [1, 4] and t["selected"].sum() == 2


def test_final_rank_tiebreak_falls_back_to_larger_market_cap():
    b = fake_base(roc=[0.3, 0.3], ey=[0.1, 0.1], mcap=[1e9, 5e9])
    t = mf._finish(b, mf._params({"n": 1, "min_cap": 0}))
    assert t.loc[2, "final_rank"] == 1.0 and t.loc[1, "final_rank"] == 2.0


def test_ranks_are_computed_among_eligible_names_only():
    b = fake_base(roc=[9.0, 0.5, 0.4], ey=[9.0, 0.2, 0.1])
    b.loc[1, "fail_sector"] = True
    b.loc[1, "ok_struct"] = False
    t = mf._finish(b, mf._params({"n": 2, "min_cap": 0}))
    assert np.isnan(t.loc[1, "rank_roc"]) and np.isnan(t.loc[1, "final_rank"])
    assert t.loc[2, "rank_roc"] == 1.0 and t.loc[3, "rank_roc"] == 2.0
    assert t.loc[1, "first_reason"] == "sector" and list(t.index)[-1] == 1


def test_ranking_modes_ey_roc_gpa():
    b = fake_base(roc=[0.9, 0.5, 0.1], ey=[0.05, 0.10, 0.30], gpa=[0.1, 0.9, 0.2])
    p = lambda k: mf._params({"ranking": k, "n": 1, "min_cap": 0})
    assert mf._finish(b, p("EY")).index[0] == 3
    assert mf._finish(b, p("ROC")).index[0] == 1
    # MF: score = [1+3, 2+2, 3+1] = [4, 4, 4] -> tie, highest EY wins
    assert mf._finish(b, p("MF")).index[0] == 3
    t = mf._finish(b, p("GPA"))                   # r_gpa = [3, 1, 2];  r_ey = [3, 2, 1]  -> scores [6, 3, 3]
    assert t["score"].to_dict() == {1: 6.0, 2: 3.0, 3: 3.0}
    assert t.index[0] == 3                        # tie between 2 and 3 -> higher EY


def test_gpa_mode_requires_gross_profit_and_assets():
    b = fake_base(roc=[0.9, 0.5], ey=[0.05, 0.10], gpa=[np.nan, 0.5])
    t = mf._finish(b, mf._params({"ranking": "GPA", "n": 2, "min_cap": 0}))
    assert not bool(t.loc[1, "eligible"]) and t.loc[1, "first_reason"] == "gp_missing"
    t = mf._finish(b, mf._params({"ranking": "MF", "n": 2, "min_cap": 0}))
    assert bool(t.loc[1, "eligible"])


# ------------------------------------------------------------------------------------------------
# eligibility and exclusions
# ------------------------------------------------------------------------------------------------
def many_firms_ctx():
    """Fourteen firms each hitting (at most) one exclusion; firm 1 is a clean eligible control."""
    specs = {
        1: dict(),
        2: dict(sector="Financials"),
        3: dict(sector="Real Estate"),
        4: dict(sector="Utilities"),
        5: dict(snap=dict(period_end="2011-10-01", filed="2011-11-10")),        # 272 days old -> stale
        6: dict(snap=dict(opinc=-5.0, pretax=-6.0)),                              # negative EBIT
        7: dict(snap=dict(total_debt=np.nan)),                                    # unmapped debt
        8: dict(snap=dict(current_assets=np.nan)),                                # unclassified balance sheet
        9: dict(px=4.0),                                                          # price below $5
        10: dict(snap=dict(shares_out=1.0, shares_diluted=1.0)),                  # market cap 10 < min cap
        11: dict(snap=dict(cash=500.0, st_investments=0.0, current_assets=1000.0, current_liabilities=200.0,
                           total_debt=0.0, shares_out=10.0, shares_diluted=10.0), mcap_ok=True),   # EV <= 0
        12: dict(sector=None, sic=6199),                                          # SIC fallback: finance
        13: dict(sector=None, sic=4953),                                          # SIC fallback: waste services -> ok
        14: dict(sector=None, sic=None),                                          # sector unknown -> excluded
    }
    rows, mem, px = [], [], {}
    for cik, s in specs.items():
        tick = f"T{cik}"
        rows.append(snap(cik, **s.get("snap", {})))
        mem.append(member(cik, tick, sector=s.get("sector", "Information Technology"), sic=s.get("sic", 3570)))
        px[tick] = s.get("px", 10.0)
    mem.append(member(99, "NOSNAP"))            # in the universe but no filing at all
    px["NOSNAP"] = 10.0
    close = flat_close(list(px), px=px)
    return FakeCtx(close, pd.DataFrame(rows), pd.DataFrame(mem))


def test_every_exclusion_reason_and_the_clean_control():
    ctx = many_firms_ctx()
    t = mf.mf_table(ctx, T0, None, {"min_cap": 50.0, "n": 30})
    fr = t["first_reason"].to_dict()
    assert fr[1] == "" and bool(t.loc[1, "eligible"])
    assert fr[2] == fr[3] == fr[4] == "sector"
    assert fr[5] == "stale"
    assert fr[6] == "ebit_nonpos"
    assert fr[7] == "debt_unmapped"
    assert fr[8] == "no_classified_bs"
    assert fr[9] == "price_lt_floor"
    assert fr[10] == "mcap_lt_min"
    assert fr[11] == "ev_nonpos"
    assert fr[12] == "sector" and t.loc[12, "sector_source"] == "sic"
    assert bool(t.loc[13, "eligible"]) and t.loc[13, "sector_source"] == "sic"      # SIC 4953 is kept
    assert fr[14] == "sector" and t.loc[14, "sector_source"] == "unknown"
    assert fr[99] == "no_snapshot" and "mcap_missing" in t.loc[99, "reasons"]
    assert int(t["eligible"].sum()) == 2                                             # firms 1 and 13
    assert set(t.index[t["selected"]]) == {1, 13}
    assert not t.loc[~t["eligible"], "final_rank"].notna().any()


class DatedMembersCtx(FakeCtx):
    """Universe frames that change with the date: ``members`` = {Timestamp: DataFrame}; latest <= date wins."""

    def universe(self, date, name="SP1500"):
        date = self.trading_day_on_or_before(date)
        keys = sorted(k for k in self.members if k <= date)
        m = self.members[keys[-1]] if keys else next(iter(self.members.values())).iloc[0:0]
        m = m[m["yf_ticker"].isin(self.close.columns)]
        return m.reset_index(drop=True)


def test_unmapped_gics_sector_is_filled_from_the_same_company_at_nearby_snapshots():
    """Banks left unmapped in the middle snapshot must still be excluded; industrials must stay in."""
    full = pd.DataFrame([member(1, "BANK", sector="Financials"), member(2, "IND", sector="Industrials")])
    gap = pd.DataFrame([member(1, "BANK", sector=None, sic=None), member(2, "IND", sector=None, sic=None),
                        member(3, "NEWB", sector=None, sic=6022)])           # never mapped anywhere, SIC says bank
    members = {pd.Timestamp("2012-01-02"): full, pd.Timestamp("2012-04-02"): gap,
               pd.Timestamp("2012-10-01"): pd.DataFrame([member(1, "BANK", sector="Financials"),
                                                          member(2, "IND", sector="Industrials")])}
    snaps = pd.DataFrame([snap(1), snap(2), snap(3)])
    ctx = DatedMembersCtx(flat_close(["BANK", "IND", "NEWB"]), snaps, members)
    t = mf.mf_table(ctx, T0, None, {"min_cap": 0.0})
    assert t.loc[1, "sector_source"] == "gics_prev" and t.loc[1, "gics_sector"] == "Financials"
    assert t.loc[1, "first_reason"] == "sector"
    assert t.loc[2, "sector_source"] == "gics_prev" and bool(t.loc[2, "eligible"])
    assert t.loc[3, "sector_source"] == "sic" and t.loc[3, "first_reason"] == "sector"          # SIC 6022 = bank
    # carrying backwards from a LATER snapshot when nothing earlier exists
    early = pd.Timestamp("2012-02-01")
    early_snaps = pd.DataFrame([snap(1, filed="2012-01-10", period_end="2011-09-30"),
                                snap(2, filed="2012-01-10", period_end="2011-09-30")])
    t2 = mf.mf_table(DatedMembersCtx(flat_close(["BANK", "IND"]), early_snaps,
                                     {pd.Timestamp("2012-01-02"): gap.iloc[:2],
                                      pd.Timestamp("2012-10-01"): full}), early, None, {"min_cap": 0.0})
    assert t2.loc[1, "sector_source"] == "gics_next" and t2.loc[1, "gics_sector"] == "Financials"


def test_snapshot_older_than_200_days_is_not_eligible_but_160_days_is():
    ctx = FakeCtx(flat_close(["A", "B"]), pd.DataFrame([
        snap(1, period_end="2011-12-31", filed="2012-02-15"),            # 181 days old at 2012-06-29
        snap(2, period_end="2011-12-01", filed="2012-02-15")]),          # 211 days old
        pd.DataFrame([member(1, "A"), member(2, "B")]))
    t = mf.mf_table(ctx, T0, None, {"min_cap": 0})
    assert bool(t.loc[1, "eligible"]) and not bool(t.loc[2, "eligible"])
    assert t.loc[2, "first_reason"] == "stale" and t.loc[2, "age_days"] == 211


def test_price_floor_uses_unadjusted_price_and_market_cap_is_split_consistent():
    """Adjusted close 3 with a later 4:1 split => raw price 12 (>= $5); cover shares (pre-split) x4."""
    close = flat_close(["A"], px=3.0)
    splits = pd.DataFrame({"yf_ticker": ["A"], "date": [pd.Timestamp("2012-09-04")], "ratio": [4.0]})
    ctx = FakeCtx(close, pd.DataFrame([snap(1)]), pd.DataFrame([member(1, "A")]), splits)
    r = mf.mf_table(ctx, T0, None, {"min_cap": 0}).loc[1]
    assert r["price_raw"] == pytest.approx(12.0) and bool(r["eligible"])
    assert r["mcap"] == pytest.approx(12.0 * 100.0)                   # raw price x raw shares, = 3 x (100 x 4)


def test_explicit_zero_debt_counts_as_mapped():
    r = row_of(one_firm_ctx(total_debt=0.0))
    assert bool(r["eligible"]) and r["ev"] == pytest.approx(1000 + 20 + 0 + 0 - 150)


def test_negative_ev_and_nonpositive_ebit_are_flagged_not_ranked():
    t = mf.mf_table(many_firms_ctx(), T0, None, {"min_cap": 0.0})
    assert t.loc[6, "rank_roc"] != t.loc[6, "rank_roc"]                   # NaN
    assert bool(t.loc[11, "fail_ev_nonpos"]) and t.loc[11, "ev"] < 0


def test_min_cap_flag_only_depends_on_params():
    ctx = many_firms_ctx()
    lo = mf.mf_table(ctx, T0, None, {"min_cap": 0.0})
    hi = mf.mf_table(ctx, T0, None, {"min_cap": 1e6})
    assert lo["eligible"].sum() > hi["eligible"].sum() == 0
    assert hi["first_reason"].loc[1] == "mcap_lt_min"


def test_mf_table_accepts_universe_frame_or_name():
    ctx = many_firms_ctx()
    a = mf.mf_table(ctx, T0, ctx.universe(T0, "SP1500"), {"min_cap": 50.0})
    b = mf.mf_table(ctx, T0, "SP1500", {"min_cap": 50.0})
    pd.testing.assert_frame_equal(a, b)


# ------------------------------------------------------------------------------------------------
# no look-ahead
# ------------------------------------------------------------------------------------------------
def test_filing_on_the_signal_date_is_not_used_but_next_day_is():
    old = snap(1, filed="2012-05-10", period_end="2012-03-31", opinc=84.0)
    new = snap(1, filed="2012-06-29", period_end="2012-06-30", opinc=999.0)
    new["accn"] = "a1-new"
    ctx = FakeCtx(flat_close(["A"]), pd.DataFrame([old, new]), pd.DataFrame([member(1, "A")]))
    assert mf.mf_table(ctx, "2012-06-29", None, {"min_cap": 0}).loc[1, "ebit_ttm"] == 84.0
    assert mf.mf_table(ctx, "2012-07-02", None, {"min_cap": 0}).loc[1, "ebit_ttm"] == 999.0


def test_table_and_weights_ignore_everything_after_the_signal_date():
    rng = np.random.default_rng(0)
    d = pd.bdate_range("2012-01-02", "2012-12-31")
    tick = [f"T{i}" for i in range(6)]
    close = pd.DataFrame(10 * np.exp(np.cumsum(rng.normal(0, 0.01, (len(d), 6)), axis=0)), index=d, columns=tick)
    snaps = pd.DataFrame([snap(i, opinc=50.0 + 10 * i) for i in range(6)] +
                         [snap(i, filed="2012-08-15", period_end="2012-06-30", opinc=500.0 - 70 * i, accn=f"b{i}")
                          for i in range(6)])
    mem = pd.DataFrame([member(i, tick[i]) for i in range(6)])
    base = FakeCtx(close, snaps, mem)
    close2 = close.copy()
    close2.loc[close2.index > T0] *= rng.uniform(0.1, 3.0, (int((close.index > T0).sum()), 6))
    pert = FakeCtx(close2, snaps[snaps["filed"] <= T0], mem)
    pa = {"min_cap": 0, "n": 3}
    pd.testing.assert_frame_equal(mf.mf_table(base, T0, None, pa), mf.mf_table(pert, T0, None, pa))
    pd.testing.assert_frame_equal(mf.target_weights(base, pa, [T0]), mf.target_weights(pert, pa, [T0]))


# ------------------------------------------------------------------------------------------------
# weights and portfolio mechanics
# ------------------------------------------------------------------------------------------------
def test_target_weights_equal_weight_top_n():
    ctx = many_firms_ctx()
    w = mf.target_weights(ctx, {"min_cap": 50.0, "n": 30}, [T0])
    assert set(w.columns[w.iloc[0] > 0]) == {"T1", "T13"}
    assert w.iloc[0].sum() == pytest.approx(1.0) and w.iloc[0].max() == pytest.approx(0.5)
    w = mf.target_weights(ctx, {"min_cap": 50.0, "n": 1}, [T0])
    assert (w.iloc[0] > 0).sum() == 1 and w.iloc[0].sum() == pytest.approx(1.0)


def world(n_firms=10, start="2010-01-01", end="2013-06-28", seed=1):
    """Random-walk prices and quarterly filings (filed 35 days after quarter end) with drifting fundamentals."""
    rng = np.random.default_rng(seed)
    d = pd.bdate_range(start, end)
    tick = [f"T{i}" for i in range(n_firms)]
    close = pd.DataFrame(10 * np.exp(np.cumsum(rng.normal(0.0004, 0.01, (len(d), n_firms)), axis=0)),
                         index=d, columns=tick)
    qe = pd.date_range("2009-09-30", end, freq="QE")
    rows = []
    for i in range(n_firms):
        for q in qe:
            rows.append(snap(i, filed=q + pd.Timedelta(days=35), period_end=q,
                             opinc=float(rng.uniform(40, 120)), ppe_net=float(rng.uniform(100, 400)),
                             accn=f"{i}-{q.date()}", shares_out=1000.0, shares_diluted=1000.0,
                             shares_out_date=q + pd.Timedelta(days=30)))
    mem = pd.DataFrame([member(i, tick[i]) for i in range(n_firms)])
    return FakeCtx(close, pd.DataFrame(rows), mem)


@pytest.fixture(scope="module")
def wctx():
    return world()


PW = {"min_cap": 0.0, "n": 3, "cost_bps": 10.0}


def test_staggered_rebalances_monthly_with_a_growing_then_constant_number_of_sleeves(wctx):
    res = mf.backtest(wctx, {**PW, "holding": "staggered"}, "2010-06-30", "2012-12-31")
    sigs = mf.signal_dates(wctx, "2010-06-30", "2012-12-31")
    # the last signal is on `end` itself, so its trade (next close) falls outside the window and is ignored
    assert sigs[-1] == pd.Timestamp("2012-12-31") and int(res.daily["rebalance"].sum()) == len(sigs) - 1
    assert (res.daily["exposure"] <= 1.0 + 1e-9).all()
    # first trade is the close of the day after the first signal
    assert res.daily.index[0] == wctx.dates[wctx.dates.searchsorted(sigs[0]) + 1]
    nh = res.daily["n_holdings"]
    assert nh.iloc[0] == 3 and nh.max() <= 10 and nh.iloc[-1] >= nh.iloc[0]


def rotating_world(n_signals=26):
    """Firm k is the unique best name (huge EBIT) at the k-th month-end signal; everything else is equal."""
    d = pd.bdate_range("2010-01-04", "2012-12-31")
    me = pd.Series(d, index=d).groupby([d.year, d.month]).max()
    sig = [t for t in me if t >= pd.Timestamp("2010-06-30")][:n_signals]
    rng = np.random.default_rng(3)
    tick = [f"R{k}" for k in range(n_signals)]
    close = pd.DataFrame(10 * np.exp(np.cumsum(rng.normal(0.0003, 0.008, (len(d), n_signals)), axis=0)),
                         index=d, columns=tick)
    rows = []
    for k, t in enumerate(sig):
        fd = t - pd.Timedelta(days=15)
        for i in range(n_signals):
            rows.append(snap(i, filed=fd, period_end=fd - pd.Timedelta(days=45), opinc=1000.0 if i == k else 10.0,
                             accn=f"{i}-{k}", shares_out=1000.0, shares_diluted=1000.0,
                             shares_out_date=fd - pd.Timedelta(days=20)))
    mem = pd.DataFrame([member(i, tick[i]) for i in range(n_signals)])
    return FakeCtx(close, pd.DataFrame(rows), mem), sig


def test_staggered_sleeve_is_held_exactly_twelve_signals():
    ctx, sig = rotating_world()
    p = {"min_cap": 0.0, "n": 1, "holding": "staggered", "cost_bps": 0.0}
    w = mf.target_weights(ctx, p, sig)
    assert [w.columns[int(np.argmax(w.iloc[k].to_numpy()))] for k in range(len(sig))] == [f"R{k}" for k in range(len(sig))]
    res = mf.backtest(ctx, p, sig[0], sig[-1])
    trade_day = lambda k: ctx.dates[ctx.dates.searchsorted(sig[k]) + 1]
    W = res.weights
    for k in (11, 12, 20):
        row = W.loc[trade_day(k)]
        held = set(row.index[row > 1e-9])
        assert held == {f"R{j}" for j in range(max(0, k - 11), k + 1)}, k           # 12 live sleeves, oldest = k - 11
        assert all(row[h] == pytest.approx(1 / 12) for h in held)
    assert W.loc[trade_day(12), "R0"] == 0.0 and W.loc[trade_day(11), "R0"] > 0.0   # R0 sold at the 12th following signal


def test_annual_start_month_portfolio_holds_a_name_twelve_months_then_replaces_it():
    ctx, sig = rotating_world()
    p = {"min_cap": 0.0, "n": 1, "holding": "annual", "cost_bps": 0.0}
    res = mf.backtest(ctx, p, sig[0], sig[-1])
    trade_day = lambda k: ctx.dates[ctx.dates.searchsorted(sig[k]) + 1]
    k = 3
    m = sig[k].month
    tr = res.by_start[m].trades
    buy = tr[(tr["ticker"] == f"R{k}") & (tr["side"] == "buy")]["date"]
    sell = tr[(tr["ticker"] == f"R{k}") & (tr["side"] == "sell")]["date"]
    assert list(buy) == [trade_day(k)] and list(sell) == [trade_day(k + 12)]
    assert tr[(tr["ticker"] == f"R{k + 12}") & (tr["side"] == "buy")]["date"].tolist() == [trade_day(k + 12)]
    assert res.by_start[m].daily["rebalance"].sum() == 2                              # signals k and k+12 only


def test_annual_runs_all_twelve_start_months_and_rebalances_once_a_year_each(wctx):
    res = mf.backtest(wctx, {**PW, "holding": "annual"}, "2010-06-30", "2012-12-31")
    assert isinstance(res, mf.AnnualResult)
    assert sorted(res.by_start) == list(range(1, 13))
    for m, r in res.by_start.items():
        sig_months = {d.month for d in r.daily.index[r.daily["rebalance"]]}
        n_reb = int(r.daily["rebalance"].sum())
        assert 2 <= n_reb <= 3                                           # 2010-06 .. 2012-12: 2 or 3 annual signals
        # trades happen the day after a signal at the month-end of month m (first trading day of m+1)
        assert sig_months <= {m % 12 + 1}
    # the combined daily series is the mean of the live start-month portfolios
    cat = pd.concat({m: r.daily["ret_gross"] for m, r in res.by_start.items()}, axis=1, sort=True)
    pd.testing.assert_series_equal(res.daily["ret_gross"], cat.mean(axis=1), check_names=False, check_freq=False)
    assert res.daily["n_holdings"].max() == 3


def test_annual_and_staggered_are_close_with_zero_costs(wctx):
    """Same 12 live cohorts and monthly equalization => nearly the same monthly series (documented)."""
    kw = dict(PW, cost_bps=0.0)
    a = mf.monthly_returns(wctx, {**kw, "holding": "annual"}, "2010-06-30", "2012-12-31")
    s = mf.monthly_returns(wctx, {**kw, "holding": "staggered"}, "2010-06-30", "2012-12-31")
    both = pd.concat([a, s], axis=1).dropna()
    assert len(both) > 24
    assert (both.iloc[:, 0] - both.iloc[:, 1]).abs().max() < 0.01
    assert both.corr().iloc[0, 1] > 0.99


def test_costs_are_charged_and_explicit_cost_overrides_params(wctx):
    r0 = mf.backtest(wctx, {**PW, "cost_bps": 0.0}, "2010-06-30", "2011-12-31")
    r10 = mf.backtest(wctx, {**PW, "cost_bps": 10.0}, "2010-06-30", "2011-12-31")
    r50 = mf.backtest(wctx, {**PW, "cost_bps": 10.0}, "2010-06-30", "2011-12-31", cost_bps=50.0)
    assert r0.daily["cost"].sum() == 0.0
    assert 0 < r10.daily["cost"].sum() < r50.daily["cost"].sum()
    assert r50.daily["cost"].sum() == pytest.approx(5 * r10.daily["cost"].sum(), rel=1e-6)


def test_date_luck_summary_has_twelve_start_months_and_mean_range_rows(wctx):
    res = mf.backtest(wctx, {**PW, "holding": "annual"}, "2010-06-30", "2012-12-31")
    dl = mf.date_luck(res, wctx)
    assert list(dl.index[:12]) == list(range(1, 13))
    assert list(dl.index[12:]) == ["mean", "min", "max", "range"]
    assert dl.loc["range", "cagr"] == pytest.approx(dl.loc[list(range(1, 13)), "cagr"].max()
                                                    - dl.loc[list(range(1, 13)), "cagr"].min())


def test_backtest_window_ends_at_end_date(wctx):
    for hold in ("staggered", "annual"):
        res = mf.backtest(wctx, {**PW, "holding": hold}, "2010-06-30", "2011-03-31", store_weights=False)
        assert res.daily.index[-1] <= pd.Timestamp("2011-03-31")
        assert res.monthly().index[-1] == pd.Timestamp("2011-03-31")
    r = mf.monthly_returns(wctx, {**PW}, "2010-06-30", "2011-03-15")          # mid-month end: last month partial -> dropped
    assert r.index[-1] == pd.Timestamp("2011-02-28")


def test_monthly_returns_drop_trailing_incomplete_month():
    ctx = world(end="2012-03-14")
    r = mf.monthly_returns(ctx, {**PW}, "2010-06-30", None)
    assert r.index[-1] == pd.Timestamp("2012-02-29")


def test_signal_dates_are_complete_month_ends():
    ctx = world(end="2012-03-14")
    sd = mf.signal_dates(ctx, "2012-01-01", None)
    assert sd == [pd.Timestamp("2012-01-31"), pd.Timestamp("2012-02-29")]


# ------------------------------------------------------------------------------------------------
# coverage and diagnostics
# ------------------------------------------------------------------------------------------------
def test_coverage_start_picks_first_month_at_90pct_of_plateau_with_persistence(monkeypatch):
    idx = pd.date_range("2010-01-31", periods=12, freq="ME")
    counts = pd.DataFrame({"cov_1B": [0, 10, 60, 91, 80, 95, 95, 100, 100, 100, 100, 100]}, index=idx)
    monkeypatch.setattr(mf, "coverage_counts", lambda *a, **k: counts)
    # plateau = median over the last 6 months = 100 -> threshold 90; month 3 (91) then drops to 80 => not persistent
    st = mf.coverage_start(None, 1e9, plateau=("2010-07-01", "2010-12-31"), persist=3)
    assert st == pd.Timestamp("2010-06-30")
    st = mf.coverage_start(None, 1e9, plateau=("2010-07-01", "2010-12-31"), persist=0)
    assert st == pd.Timestamp("2010-04-30")


def test_diagnostics_exclusive_reason_counts_sum_to_universe_minus_eligible():
    ctx = many_firms_ctx()
    d = mf.diagnostics(ctx, {"min_cap": 50.0}, [T0])
    row = d.iloc[0]
    firsts = sum(row[f"first_{r}"] for r in mf.REASONS)
    assert row["n_universe"] == 15 and row["n_eligible"] == 2
    assert firsts == row["n_universe"] - row["n_eligible"]
    assert row["first_sector"] == 4 + 1 + 1 + 0 or row["first_sector"] >= 5      # firms 2,3,4,12,14 (5)
    assert row["n_snapshot"] == 14


def test_coverage_counts_per_tier(wctx):
    cnt = mf.coverage_counts(wctx, "SP1500", caps=(0.0, 1e12), start="2010-06-30", end="2010-12-31")
    assert (cnt["elig_0"] > 0).all() and (cnt["elig_1000B"] == 0).all()
    assert (cnt["cov_0"] == 1.0).all() and (cnt["pop_1000B"] == 0).all()           # all inputs present in the world


def test_coverage_ratio_counts_missing_filers_as_uncovered():
    ctx = FakeCtx(flat_close(["A", "B", "C"]), pd.DataFrame([snap(1), snap(2, ebit_missing=0, opinc=np.nan)]),
                  pd.DataFrame([member(1, "A"), member(2, "B"), member(3, "C")]))
    cnt = mf.coverage_counts(ctx, "SP1500", caps=(0.0,), start="2012-06-29", end="2012-06-29")
    # A complete; B has no TTM EBIT; C never filed -> 1 of 3 covered
    assert cnt["pop_0"].iloc[0] == 3 and cnt["cov_0"].iloc[0] == pytest.approx(1 / 3)


# ------------------------------------------------------------------------------------------------
# live table
# ------------------------------------------------------------------------------------------------
def test_live_picks_shape_alternates_staleness_and_sector_summary():
    n = 8
    d = pd.bdate_range("2012-01-02", "2012-12-31")
    rows, mem = [], []
    for i in range(n):
        rows.append(snap(i, opinc=40.0 + 10 * i, period_end="2012-01-31" if i == 0 else "2012-03-31",
                         filed="2012-03-01" if i == 0 else "2012-05-10"))
        mem.append(member(i, f"T{i}", sector="Health Care" if i % 2 else "Industrials"))
    ctx = FakeCtx(flat_close([f"T{i}" for i in range(n)]), pd.DataFrame(rows), pd.DataFrame(mem))
    lp = mf.live_picks(ctx, {"min_cap": 0, "n": 3}, T0, n_alternates=2)
    assert list(lp["pick"]) == ["PICK"] * 3 + ["ALT"] * 2
    assert list(lp["final_rank"]) == [1, 2, 3, 4, 5]
    for c in ("ey", "roc", "ev", "capital", "excess_cash", "period_end", "age_days", "review_flags"):
        assert c in lp.columns
    sc = lp.attrs["sector_counts"]
    assert sc["picks"].sum() == 3 and sc["alternates"].sum() == 2 and sc["eligible_universe"].sum() == n
    # the firm whose balance sheet ends 2012-01-31 is 150+ days old at 2012-06-29 (150 days: not > 150)
    full = mf.live_picks(ctx, {"min_cap": 0, "n": 8}, T0, n_alternates=0)
    old = full.loc[0]
    assert old["age_days"] == 150 and old["stale_flag"] == ""
    ctx2 = FakeCtx(flat_close([f"T{i}" for i in range(n)]), pd.DataFrame(rows), pd.DataFrame(mem))
    full2 = mf.live_picks(ctx2, {"min_cap": 0, "n": 8}, "2012-07-02", n_alternates=0)
    assert full2.loc[0, "stale_flag"].startswith("STALE") and "stale" in full2.loc[0, "review_flags"]
    assert full2.attrs["summary"]["n_stale"] == 1


# ------------------------------------------------------------------------------------------------
# pre-registered design
# ------------------------------------------------------------------------------------------------
def test_grid_is_18_unique_cells_and_contains_default():
    # v2 grid: n x momentum filter x ranking, around the v1 choice (n=25, >= $5B, staggered)
    assert len(mf.GRID) == 18
    keys = [(c["n"], c["mom_filter"], c["ranking"]) for c in mf.GRID]
    assert len(set(keys)) == 18
    assert mf.DEFAULT in mf.GRID
    assert mf.DEFAULT["n"] == 25 and mf.DEFAULT["min_cap"] == 5e9 and mf.DEFAULT["holding"] == "staggered"
    assert mf.DEFAULT["ranking"] == "MF" and mf.DEFAULT["universe"] == "SP900" and mf.DEFAULT["cost_bps"] == 10
    assert mf.DEFAULT["mom_filter"] == 0.0
    assert all(c["min_cap"] == 5e9 and c["holding"] == "staggered" for c in mf.GRID)
    assert mf.DOC_DEFAULT["n"] == 30 and mf.DOC_DEFAULT["min_cap"] == 1e9
    json.dumps(mf.GRID)                                            # JSON-serializable


def test_ablations_each_change_one_thing():
    ap = mf.ablation_params()
    assert set(ap) == {"ey_only", "roc_only", "gpa_quality", "us_all_universe", "sp1500_universe", "all_cash",
                       "ebit_pretax_interest", "cost_25bps", "cost_50bps"}
    for name, p in ap.items():
        diff = {k for k in p if p[k] != mf.DEFAULT[k]}
        assert len(diff) == 1, (name, diff)
        mf._params(p)                                               # valid
    assert mf.ablation_params({**mf.DEFAULT, "n": 20})["cost_25bps"]["n"] == 20


def test_preregistration_roundtrip_and_validates_against_grid_module(tmp_path):
    path = mf.preregister(out_dir=tmp_path)
    doc = json.loads(path.read_text())
    assert doc["n_cells"] == 18 and doc["default"] == mf.DEFAULT
    assert doc["axes"] == {"n": [20, 25, 30], "mom_filter": [0.0, 0.3, 0.5]}
    assert doc["categorical"] == {"ranking": ["MF", "GPA"]}
    assert set(doc["extra"]["ablations"]) == set(mf.ABLATIONS)
    mtime = path.stat().st_mtime_ns
    assert mf.preregister(out_dir=tmp_path) == path and path.stat().st_mtime_ns == mtime     # idempotent
    assert grid.load_preregistration("magic_formula", tmp_path)["grid_hash"] == grid.grid_hash(mf.GRID)


def test_param_validation():
    for bad in ({"ranking": "XX"}, {"holding": "weekly"}, {"excess_cash": "x"}, {"ebit": "x"}, {"n": 0}):
        with pytest.raises(ValueError):
            mf._params(bad)
    assert "SURVIVORSHIP" in mf.universe_label({"universe": "US_ALL"})


def test_grid_fn_runs_through_run_grid_on_synthetic_world(wctx, tmp_path):
    cells = [dict(mf.DEFAULT, n=n, min_cap=0.0, holding=h) for n in (2, 3) for h in ("staggered", "annual")]
    fn = mf.make_grid_fn(wctx, start="2010-06-30", end="2012-12-31")
    out = grid.run_grid("mf_test", cells, fn, ledger=False, check_prereg=False, out_dir=tmp_path)
    assert out.M.shape[1] == 4 and out.M.notna().all().all()
