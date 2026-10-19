"""Tests for quant/signals/quality.py (synthetic frames, hand-computed expectations)."""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from quant.signals import quality as Q
from quant.signals.quality import ARMS, blend_score, passes, pct_rank, quality_table, rank_z

DATE = pd.Timestamp("2020-06-30")


# --------------------------------------------------------------------------------------------------
# helpers
# --------------------------------------------------------------------------------------------------
class StubCtx:
    """Minimal DataContext stand-in: fundamentals(date) and returns."""

    def __init__(self, fund: pd.DataFrame, returns: pd.DataFrame | None = None):
        self._fund = fund
        self.returns = returns if returns is not None else pd.DataFrame(index=pd.bdate_range("2019-01-01", DATE))
        self.calls = []

    def fundamentals(self, date, max_age_days=200):
        self.calls.append((pd.Timestamp(date), max_age_days))
        return self._fund


_DEFAULT = dict(assets=100.0, revenue=100.0, cogs=80.0, gross_profit=np.nan, net_income=5.0, cfo=8.0, capex=3.0,
                total_debt=20.0, cash=5.0, st_investments=0.0, ebitda=15.0, evol=0.01, equity_parent=40.0,
                preferred=0.0, minority_interest=0.0)


def world(rows: list[dict]):
    """rows: dicts with cik, sector, group, industry + any fundamentals override. Returns (univ, fund)."""
    u, f = [], []
    for i, r in enumerate(rows):
        cik = r["cik"]
        u.append(dict(cik=cik, yf_ticker=r.get("ticker", f"T{cik}"), gics_sector=r.get("sector", "S1"),
                      gics_industry_group=r.get("group", "G1"), gics_industry=r.get("industry", "I1"),
                      sic=r.get("sic", 3571)))
        d = dict(_DEFAULT)
        d.update({k: v for k, v in r.items() if k in _DEFAULT})
        if "gpoa" in r:  # convenience: gross profit = gpoa * assets via revenue - cogs
            d["revenue"], d["cogs"] = 100.0, 100.0 - r["gpoa"] * d["assets"]
        d.update(cik=cik, period_end=pd.Timestamp("2020-03-31"), filed=pd.Timestamp("2020-05-05"))
        f.append(d)
    univ = pd.DataFrame(u)
    fund = pd.DataFrame(f).set_index("cik")
    return univ, fund


def table(rows, returns=None):
    univ, fund = world(rows)
    return quality_table(StubCtx(fund, returns), DATE, univ)


# --------------------------------------------------------------------------------------------------
# z-score / percentile math
# --------------------------------------------------------------------------------------------------
def test_rank_z_basic():
    z = rank_z(pd.Series([10.0, 20.0, 30.0, 40.0]))
    sd = np.sqrt(1.25)
    np.testing.assert_allclose(z.to_numpy(), np.array([-1.5, -0.5, 0.5, 1.5]) / sd)
    assert abs(z.mean()) < 1e-12 and abs(z.std(ddof=0) - 1) < 1e-12


def test_rank_z_ties_nan_and_inf():
    z = rank_z(pd.Series([1.0, 1.0, 5.0, np.nan, np.inf]))
    # ranks of the 3 finite values: 1.5, 1.5, 3 -> mean 2, pop std sqrt(0.5)
    np.testing.assert_allclose(z.iloc[:3].to_numpy(), np.array([-0.5, -0.5, 1.0]) / np.sqrt(0.5))
    assert z.iloc[3:].isna().all()


def test_rank_z_degenerate():
    assert (rank_z(pd.Series([3.0, 3.0, 3.0])) == 0).all()
    assert rank_z(pd.Series([np.nan, np.nan])).isna().all()
    assert rank_z(pd.Series([], dtype=float)).empty


def test_pct_rank_range_and_ties():
    p = pct_rank(pd.Series([3.0, 1.0, 2.0, np.nan, 2.0]))
    # values 1,2,2,3 -> ranks 1, 2.5, 2.5, 4 -> (r-1)/3*100
    np.testing.assert_allclose(p.iloc[[1, 2, 4, 0]].to_numpy(), [0.0, 50.0, 50.0, 100.0])
    assert np.isnan(p.iloc[3])
    assert pct_rank(pd.Series([7.0])).iloc[0] == 50.0


# --------------------------------------------------------------------------------------------------
# metric definitions
# --------------------------------------------------------------------------------------------------
def test_metric_formulas_and_gp_fallback():
    rows = [dict(cik=1, assets=200.0, revenue=100.0, cogs=60.0, gross_profit=np.nan, net_income=10.0, cfo=30.0,
                 capex=10.0, total_debt=50.0, cash=20.0, st_investments=10.0, ebitda=20.0, equity_parent=100.0,
                 preferred=0.0),
            dict(cik=2, assets=200.0, revenue=100.0, cogs=60.0, gross_profit=70.0, net_income=-4.0, cfo=1.0,
                 capex=2.0, total_debt=0.0, cash=0.0, st_investments=0.0, ebitda=-5.0, equity_parent=100.0)]
    qt = table(rows)
    a = qt.loc[1]
    assert a["gpoa"] == pytest.approx(40.0 / 200.0)          # revenue - cogs fallback
    assert a["gmar"] == pytest.approx(0.4)
    assert a["roa"] == pytest.approx(10.0 / 200.0)
    assert a["roe"] == pytest.approx(0.10)
    assert a["cfoa"] == pytest.approx((30.0 - 10.0) / 200.0)
    assert a["acc"] == pytest.approx((30.0 - 10.0) / 200.0)  # (cfo - ni) / assets
    assert a["lev"] == pytest.approx(-50.0 / 200.0)
    assert a["debt_to_equity"] == pytest.approx(0.5)
    assert a["nd_ebitda"] == pytest.approx((50.0 - 30.0) / 20.0)
    assert a["net_income_ttm"] == 10.0 and a["cfo_ttm"] == 30.0 and a["ebitda_ttm"] == 20.0
    b = qt.loc[2]
    assert b["gpoa"] == pytest.approx(70.0 / 200.0)          # reported GrossProfit wins over rev - cogs
    assert b["lev"] == 0.0 or b["lev"] == pytest.approx(0.0)  # zero debt is zero, not missing
    assert b["debt_to_equity"] == pytest.approx(0.0)
    assert np.isnan(b["nd_ebitda"])                          # EBITDA <= 0 -> undefined
    assert b["net_debt"] == pytest.approx(0.0)


def test_negative_equity_makes_roe_and_de_missing():
    rows = [dict(cik=i, gpoa=0.1 + 0.01 * i) for i in range(1, 6)]
    rows.append(dict(cik=6, equity_parent=-10.0, total_debt=30.0))
    rows.append(dict(cik=7, equity_parent=0.0))
    qt = table(rows)
    assert np.isnan(qt.loc[6, "roe"]) and np.isnan(qt.loc[6, "debt_to_equity"])
    assert np.isnan(qt.loc[7, "roe"]) and np.isnan(qt.loc[7, "debt_to_equity"])
    assert np.isnan(qt.loc[6, "z_roe"])
    assert qt.loc[6, "roa"] == pytest.approx(0.05)           # ROA unaffected
    assert not np.isnan(qt.loc[6, "z_roa"]) and not np.isnan(qt.loc[6, "P"])   # P from the other components
    assert not passes(qt, "Q3a").loc[6]                      # D/E undefined -> cannot pass the team rule


def test_book_equity_fallbacks_and_preferred():
    rows = [dict(cik=1, equity_parent=np.nan, assets=100.0),
            dict(cik=2, equity_parent=60.0, preferred=10.0)]
    univ, fund = world(rows)
    fund["equity_total"] = [45.0, 70.0]
    fund["minority_interest"] = [5.0, 0.0]
    qt = quality_table(StubCtx(fund), DATE, univ)
    assert qt.loc[1, "book_equity"] == pytest.approx(40.0)    # total - minority
    assert qt.loc[2, "book_equity"] == pytest.approx(50.0)    # parent - preferred
    assert qt.loc[2, "roe"] == pytest.approx(5.0 / 50.0)


def test_missing_debt_stays_missing():
    rows = [dict(cik=i, gpoa=0.1 + 0.01 * i) for i in range(1, 7)]
    rows.append(dict(cik=7, total_debt=np.nan))
    rows.append(dict(cik=8, total_debt=0.0))
    qt = table(rows)
    assert np.isnan(qt.loc[7, "lev"]) and np.isnan(qt.loc[7, "z_lev"]) and np.isnan(qt.loc[7, "net_debt"])
    assert np.isnan(qt.loc[7, "nd_ebitda"]) and np.isnan(qt.loc[7, "debt_to_equity"])
    assert qt.loc[8, "lev"] == pytest.approx(0.0) and not np.isnan(qt.loc[8, "z_lev"])
    # zero-debt firm has the best leverage z of all
    assert qt.loc[8, "z_lev"] == qt["z_lev"].max()
    for arm in ("Q3a", "Q3b", "Q3c", "Q6"):
        assert not passes(qt, arm).loc[7]
    # S is still formed from beta/evol? beta is NaN here (no returns) -> only evol -> S missing
    assert qt.loc[7, "n_s"] == 1 and np.isnan(qt.loc[7, "S"]) and np.isnan(qt.loc[7, "QL"])


def test_composite_minimum_components():
    rows = [dict(cik=i, gpoa=0.1 + 0.01 * i, net_income=2.0 + i) for i in range(1, 9)]
    # cik 9: revenue/cogs/cfo missing -> only roe, roa left (2 of 6) -> P missing
    rows.append(dict(cik=9, revenue=np.nan, cogs=np.nan, cfo=np.nan))
    # cik 10: cfo present, revenue missing -> roe, roa, cfoa, acc = 4 -> P defined
    rows.append(dict(cik=10, revenue=np.nan, cogs=np.nan))
    qt = table(rows)
    assert qt.loc[9, "n_p"] == 2 and np.isnan(qt.loc[9, "P"]) and np.isnan(qt.loc[9, "QL"])
    assert qt.loc[10, "n_p"] == 4 and not np.isnan(qt.loc[10, "P"])
    assert (qt.loc[1:8, "n_p"] == 6).all()


def test_p_and_s_are_averages_of_available_zscores_then_rezscored():
    rng = np.random.default_rng(1)
    rows = [dict(cik=i, gpoa=rng.uniform(0.05, 0.6), net_income=rng.normal(5, 4), cfo=rng.normal(8, 5),
                 capex=rng.uniform(0, 6), total_debt=rng.uniform(0, 50), evol=rng.uniform(0.005, 0.05),
                 equity_parent=rng.uniform(10, 80), cash=rng.uniform(0, 10)) for i in range(1, 41)]
    qt = table(rows)
    expect_p = rank_z(qt[Q.P_Z].mean(axis=1))
    np.testing.assert_allclose(qt["P"].to_numpy(), expect_p.to_numpy(), atol=1e-12)
    # no beta here (no returns) -> S built from lev and evol
    expect_s = rank_z(qt[["z_lev", "z_evol"]].mean(axis=1))
    np.testing.assert_allclose(qt["S"].to_numpy(), expect_s.to_numpy(), atol=1e-12)
    np.testing.assert_allclose(qt["QL"].to_numpy(), rank_z(qt["P"] + qt["S"]).to_numpy(), atol=1e-12)
    for c in ["z_gpoa", "z_roe", "z_roa", "z_cfoa", "z_gmar", "z_acc", "z_lev", "z_evol", "P", "S", "QL"]:
        assert abs(qt[c].mean()) < 1e-9
        assert abs(qt[c].std(ddof=0) - 1) < 1e-9


def test_sign_conventions():
    rows = [dict(cik=1, total_debt=10.0, evol=0.01, net_income=5.0, cfo=10.0),
            dict(cik=2, total_debt=60.0, evol=0.05, net_income=5.0, cfo=2.0),
            dict(cik=3, total_debt=30.0, evol=0.03, net_income=5.0, cfo=6.0)]
    qt = table(rows)
    assert qt.loc[1, "z_lev"] > qt.loc[3, "z_lev"] > qt.loc[2, "z_lev"]       # less debt = better
    assert qt.loc[1, "z_evol"] > qt.loc[3, "z_evol"] > qt.loc[2, "z_evol"]    # lower vol = better
    assert qt.loc[1, "z_acc"] > qt.loc[3, "z_acc"] > qt.loc[2, "z_acc"]       # more cash earnings = better


def test_percentiles_in_range_and_monotone():
    rng = np.random.default_rng(2)
    rows = [dict(cik=i, gpoa=rng.uniform(0.0, 0.8)) for i in range(1, 51)]
    qt = table(rows)
    for c in ("gpoa_pct", "gpoa_ind_pct", "ql_pct", "p_pct"):
        assert qt[c].min() == pytest.approx(0.0) and qt[c].max() == pytest.approx(100.0)
    order = qt.sort_values("gpoa")["gpoa_pct"].to_numpy()
    assert (np.diff(order) > 0).all()
    assert qt["gpoa_pct"].median() == pytest.approx(50.0, abs=1.0)


# --------------------------------------------------------------------------------------------------
# eligibility / universe handling
# --------------------------------------------------------------------------------------------------
def test_financials_excluded_from_cross_section_and_filters():
    rows = [dict(cik=i, gpoa=0.1 + 0.02 * i) for i in range(1, 9)]
    rows.append(dict(cik=100, sector="Financials", industry="Banks", group="Banks", gpoa=0.99))
    rows.append(dict(cik=101, sector=None, industry=None, group=None, sic=6022, gpoa=0.98))
    rows.append(dict(cik=102, sector=None, industry=None, group=None, sic=3571, gpoa=0.2))   # unknown sector, non-fin
    qt = table(rows)
    assert not qt.loc[100, "eligible"] and not qt.loc[101, "eligible"]
    assert qt.loc[102, "eligible"] and qt.loc[1, "eligible"]
    for c in ("z_gpoa", "z_roa", "P", "QL", "gpoa_pct", "ql_pct"):
        assert qt.loc[[100, 101], c].isna().all()
    assert qt.loc[100, "gpoa"] == pytest.approx(0.99)         # raw ratio still shown for audit
    # ranking ignores financials: top eligible name has pct 100 even though a financial has higher GP/A
    assert qt.loc[qt["eligible"], "gpoa_pct"].max() == pytest.approx(100.0)
    assert qt.loc[8, "gpoa_pct"] == pytest.approx(100.0)
    for arm in ARMS:
        assert not passes(qt, arm).loc[[100, 101]].any(), arm


def test_only_universe_names_with_usable_snapshot():
    rows = [dict(cik=1), dict(cik=2), dict(cik=3, assets=0.0), dict(cik=4, assets=np.nan)]
    univ, fund = world(rows)
    univ = pd.concat([univ, pd.DataFrame([dict(cik=999, yf_ticker="ZZZ", gics_sector="S1",
                                               gics_industry_group="G1", gics_industry="I1", sic=1)])])
    extra = fund.iloc[[0]].copy()
    extra.index = [555]            # snapshot exists but not in the universe
    fund = pd.concat([fund, extra])
    qt = quality_table(StubCtx(fund), DATE, univ)
    assert sorted(qt.index) == [1, 2]
    assert qt.index.name == "cik"
    # contract columns
    for c in ["yf_ticker", "gics_sector", "gics_industry", "period_end", "filed", "gpoa", "gmar", "roe", "roa",
              "cfoa", "acc", "lev", "debt_to_equity", "nd_ebitda", "evol", "beta", "net_income_ttm", "cfo_ttm",
              "ebitda_ttm", "z_gpoa", "z_roe", "z_roa", "z_cfoa", "z_gmar", "z_acc", "z_bab", "z_lev", "z_evol",
              "P", "S", "QL", "gpoa_pct", "gpoa_ind_pct", "ql_pct", "p_pct", "gmar_ge_ind_med", "roe_ge_ind_med",
              "gpoa_ge_ind_med"]:
        assert c in qt.columns, c


def test_empty_inputs_return_empty_frame_with_columns():
    univ, fund = world([dict(cik=1)])
    qt = quality_table(StubCtx(fund.iloc[0:0]), DATE, univ)
    assert qt.empty and "QL" in qt.columns and "gpoa_ge_ind_med" in qt.columns
    assert passes(qt, "Q0").empty and passes(qt, "Q3b").empty


def test_passes_max_age_forwarded():
    univ, fund = world([dict(cik=1)])
    ctx = StubCtx(fund)
    quality_table(ctx, DATE, univ, max_age_days=123)
    assert ctx.calls == [(DATE, 123)]


# --------------------------------------------------------------------------------------------------
# industry-relative stats with fallback (industry >= 10, else group >= 10, else sector)
# --------------------------------------------------------------------------------------------------
def _industry_world():
    rows = []
    cik = 1
    # IndA: 12 firms (group GA, sector S1): gpoa 0.10..0.21 -> median 0.155
    for k in range(12):
        rows.append(dict(cik=cik, sector="S1", group="GA", industry="IndA", gpoa=0.10 + 0.01 * k)); cik += 1
    # IndB: 3 firms, IndC: 8 firms, both group GB (11 firms) sector S1
    for g in (0.30, 0.35, 0.40):
        rows.append(dict(cik=cik, sector="S1", group="GB", industry="IndB", gpoa=g)); cik += 1
    for k in range(8):
        rows.append(dict(cik=cik, sector="S1", group="GB", industry="IndC", gpoa=0.50 + 0.01 * k)); cik += 1
    # IndD: 2 firms (group GD, sector S2); IndE: 3 firms (group GE, sector S2) -> sector S2 has 5 firms
    for g in (0.2, 0.4):
        rows.append(dict(cik=cik, sector="S2", group="GD", industry="IndD", gpoa=g)); cik += 1
    for g in (0.1, 0.6, 0.7):
        rows.append(dict(cik=cik, sector="S2", group="GE", industry="IndE", gpoa=g)); cik += 1
    # a Financials name with a huge GP/A must not move any median
    rows.append(dict(cik=cik, sector="Financials", group="Banks", industry="Banks", gpoa=0.95))
    return rows


def test_industry_median_fallback_chain():
    qt = table(_industry_world())
    ge = qt["gpoa_ge_ind_med"]
    # IndA (>= 10 firms): median 0.155 -> top 6 pass
    a = qt[qt["gics_industry"] == "IndA"].sort_values("gpoa")
    assert a["gpoa_ge_ind_med"].tolist() == [False] * 6 + [True] * 6
    # IndB (3 firms) and IndC (8 firms) fall back to group GB: median of 11 values = 0.52
    b = qt[qt["gics_industry"] == "IndB"]
    assert not b["gpoa_ge_ind_med"].any()
    c = qt[qt["gics_industry"] == "IndC"].sort_values("gpoa")
    assert c["gpoa_ge_ind_med"].tolist() == [False, False, True, True, True, True, True, True]   # >= 0.52
    # IndD / IndE: groups too small -> sector S2 median of [0.1, 0.2, 0.4, 0.6, 0.7] = 0.4
    d = qt[qt["gics_industry"] == "IndD"].sort_values("gpoa")
    assert d["gpoa_ge_ind_med"].tolist() == [False, True]
    e = qt[qt["gics_industry"] == "IndE"].sort_values("gpoa")
    assert e["gpoa_ge_ind_med"].tolist() == [False, True, True]
    assert not ge.loc[qt["gics_sector"] == "Financials"].any()


def test_gpoa_industry_demeaning_uses_fallback_mean():
    qt = table(_industry_world())
    elig = qt[qt["eligible"]]
    # reconstruct the demeaned GP/A by hand
    means = {}
    for ind, grp in elig.groupby("gics_industry"):
        means[ind] = grp["gpoa"].mean() if len(grp) >= 10 else np.nan
    gb = elig[elig["gics_industry_group"] == "GB"]["gpoa"].mean()
    s2 = elig[elig["gics_sector"] == "S2"]["gpoa"].mean()
    means.update({"IndB": gb, "IndC": gb, "IndD": s2, "IndE": s2})
    dm = elig["gpoa"] - elig["gics_industry"].map(means)
    expected = pct_rank(dm)
    np.testing.assert_allclose(qt.loc[elig.index, "gpoa_ind_pct"].to_numpy(), expected.to_numpy(), atol=1e-9)
    # a mid-level GP/A firm in a high-GP/A industry ranks lower industry-adjusted than unadjusted
    assert qt.loc[qt["gpoa"].idxmin(), "gpoa_ind_pct"] > 0   # sanity: defined


def test_roe_and_gmar_comparisons_are_false_when_missing():
    rows = [dict(cik=i, gpoa=0.1 + 0.01 * i) for i in range(1, 12)]
    rows.append(dict(cik=12, equity_parent=-5.0))
    rows.append(dict(cik=13, revenue=np.nan))
    qt = table(rows)
    assert not qt.loc[12, "roe_ge_ind_med"]
    assert not qt.loc[13, "gmar_ge_ind_med"] and not qt.loc[13, "gpoa_ge_ind_med"]


# --------------------------------------------------------------------------------------------------
# beta
# --------------------------------------------------------------------------------------------------
def _returns(n_days=300, seed=0):
    rng = np.random.default_rng(seed)
    idx = pd.bdate_range(end=DATE, periods=n_days)
    spy = rng.normal(0.0005, 0.01, n_days)
    cols = {"SPY": spy}
    cols["T1"] = 1.5 * spy + rng.normal(0, 0.005, n_days)
    cols["T2"] = 0.5 * spy + rng.normal(0, 0.005, n_days)
    cols["T3"] = 2.0 * spy + rng.normal(0, 0.005, n_days)
    return pd.DataFrame(cols, index=idx)


def test_beta_matches_ols_and_is_shrunk():
    rets = _returns()
    qt = table([dict(cik=1, ticker="T1"), dict(cik=2, ticker="T2"), dict(cik=3, ticker="T3")], returns=rets)
    win = rets.iloc[-252:]
    for cik, t in ((1, "T1"), (2, "T2"), (3, "T3")):
        slope = np.polyfit(win["SPY"], win[t], 1)[0]
        assert qt.loc[cik, "beta_raw"] == pytest.approx(slope, rel=1e-9)
        assert qt.loc[cik, "beta"] == pytest.approx(0.6 * slope + 0.4, rel=1e-9)
    # BAB: low beta = good -> z_bab ordering T2 > T1 > T3
    assert qt.loc[2, "z_bab"] > qt.loc[1, "z_bab"] > qt.loc[3, "z_bab"]


def test_beta_point_in_time_and_min_obs():
    rets = _returns()
    future = pd.DataFrame(np.random.default_rng(5).normal(0, 0.2, (5, rets.shape[1])),
                          index=pd.bdate_range(DATE + pd.Timedelta(days=1), periods=5), columns=rets.columns)
    both = pd.concat([rets, future])
    rows = [dict(cik=1, ticker="T1"), dict(cik=2, ticker="T2")]
    a = table(rows, returns=rets)
    b = table(rows, returns=both)                    # data after `date` must be ignored
    np.testing.assert_allclose(a["beta_raw"].to_numpy(), b["beta_raw"].to_numpy(), atol=1e-14)
    short = rets.copy()
    short.loc[short.index[:-100], "T2"] = np.nan     # only 100 observations < 120
    c = table(rows, returns=short)
    assert np.isnan(c.loc[2, "beta_raw"]) and not np.isnan(c.loc[1, "beta_raw"])
    # unknown ticker -> NaN beta, nothing breaks
    d = table([dict(cik=1, ticker="NOPE")], returns=rets)
    assert np.isnan(d.loc[1, "beta"])


def test_beta_cached_per_date():
    rets = _returns()
    univ, fund = world([dict(cik=1, ticker="T1")])
    ctx = StubCtx(fund, rets)
    b1 = Q.betas(ctx, DATE)
    b2 = Q.betas(ctx, DATE)
    assert b1 is b2
    assert Q.betas(ctx, DATE - pd.Timedelta(days=30)) is not b1


def test_beta_market_proxy_when_spy_missing():
    rets = _returns().drop(columns="SPY")
    b = Q.betas(StubCtx(world([dict(cik=1)])[1], rets), DATE)
    assert np.isfinite(b["T1"]) and b["T3"] > b["T2"]


# --------------------------------------------------------------------------------------------------
# arms
# --------------------------------------------------------------------------------------------------
def handmade_qt():
    cols = ["eligible", "gpoa", "gpoa_pct", "gpoa_ind_pct", "p_pct", "ql_pct", "net_income_ttm", "cfo_ttm",
            "ebitda_ttm", "net_debt", "nd_ebitda", "debt_to_equity", "gmar_ge_ind_med", "roe_ge_ind_med",
            "gpoa_ge_ind_med"]
    rows = {
        # id: eligible, gpoa, gpoa_pct, gind, p, ql, ni, cfo, ebitda, nd, nde, de, gm, roe, gp
        1: [True, .5, 90, 80, 90, 95, 10, 12, 20, 30, 1.5, 0.5, True, False, True],      # strong, passes everything
        2: [True, .4, 60, 55, 60, 65, 5, 4, 10, 40, 4.0, 0.8, False, True, True],        # ND/EBITDA 4 > 3
        3: [True, .3, 40, 45, 40, 28, -2, 3, 8, 10, 1.25, 0.2, True, True, True],        # negative NI, junk
        4: [True, .2, 20, 72, 20, 55, 3, -1, 6, -5, -0.8, 1.5, False, False, False],     # net cash, D/E 1.5, below medians
        5: [True, .45, 50, 50, 50, 70, 4, 5, -3, 25, np.nan, np.nan, True, False, True], # EBITDA<0, D/E missing
        6: [True, .6, np.nan, np.nan, np.nan, np.nan, 7, 9, 12, 5, 0.4, 0.9, False, False, False],  # NaN pcts
        7: [False, .9, np.nan, np.nan, np.nan, np.nan, 50, 60, 80, -10, -0.1, 0.1, True, True, True],  # financial
    }
    return pd.DataFrame.from_dict(rows, orient="index", columns=cols).astype(
        {"eligible": bool, "gmar_ge_ind_med": bool, "roe_ge_ind_med": bool, "gpoa_ge_ind_med": bool})


def ids(s: pd.Series) -> list[int]:
    return sorted(s.index[s].tolist())


def test_arm_q0_and_threshold_arms():
    qt = handmade_qt()
    assert ids(passes(qt, "Q0")) == [1, 2, 3, 4, 5, 6]                    # everyone eligible, financials out
    assert ids(passes(qt, "Q1-50")) == [1, 2, 5]                           # pct >= 50 (name 6 NaN -> False)
    assert ids(passes(qt, "Q1-70")) == [1]
    assert ids(passes(qt, "Q1i-50")) == [1, 2, 4, 5]
    assert ids(passes(qt, "Q1i-70")) == [1, 4]
    assert ids(passes(qt, "Q2-P50")) == [1, 2, 5]
    assert ids(passes(qt, "Q2-Q50")) == [1, 2, 4, 5]
    assert ids(passes(qt, "Q2-Q70")) == [1, 5]                           # ql 95, 70 (>= 70 inclusive)
    assert ids(passes(qt, "Q5-veto30")) == [1, 2, 4, 5]                    # 3 (ql 28) vetoed, NaN -> False
    assert ids(passes(qt, "Q5-veto30", veto=60)) == [1, 2, 5]   # custom veto level


def test_arm_q3a_team_rule():
    qt = handmade_qt()
    # NI>0, D/E<=1.0, (GM>=med OR ROE>=med): 1 yes; 2 yes (roe); 3 NI<0; 4 D/E 1.5; 5 D/E missing; 6 neither rel; 7 fin
    assert ids(passes(qt, "Q3a")) == [1, 2]
    assert ids(passes(qt, "Q3a", X=2.0)) == [1, 2]                        # 4 still fails the relative test
    assert ids(passes(qt, "Q3a", X=0.5)) == [1]
    qt.loc[6, "gmar_ge_ind_med"] = True
    assert 6 in ids(passes(qt, "Q3a"))


def test_arm_q3b_q3c_q6():
    qt = handmade_qt()
    # Q3b: NI>0 & (net_debt<=0 or (ebitda>0 & nd/ebitda<3)) & gpoa>=ind median
    #  1 pass; 2 ND/EBITDA 4 fail; 3 NI<0; 4 net cash but gpoa below median; 5 EBITDA<0 & net debt>0 fail
    #  6 gpoa below median; 7 financial
    assert ids(passes(qt, "Q3b")) == [1]
    assert ids(passes(qt, "Q3b", Y=4.5)) == [1, 2]
    assert ids(passes(qt, "Q3b", Y=1.0)) == []
    qt.loc[5, "net_debt"] = -2.0                                           # net cash rescues negative EBITDA
    assert ids(passes(qt, "Q3b")) == [1, 5]
    qt.loc[5, "cfo_ttm"] = -1.0
    assert ids(passes(qt, "Q3c")) == [1]                                   # CFO must be positive
    assert ids(passes(qt, "Q6")) == [1, 5]                                 # Q1-50 (gpoa_pct>=50) AND Q3b


def test_arm_q4_has_no_hard_filter_and_unknown_arm_raises():
    qt = handmade_qt()
    assert ids(passes(qt, "Q4-0.5")) == [1, 2, 3, 4, 5, 6]
    with pytest.raises(ValueError):
        passes(qt, "Q99")
    for arm, desc in ARMS.items():
        assert isinstance(desc, str) and desc
        s = passes(qt, arm)
        assert s.dtype == bool and s.index.equals(qt.index)
    # evidence labels present
    assert all(("research-backed" in d) or ("heuristic" in d) or ("baseline" in d) for d in ARMS.values())
    assert {"Q0", "Q1-50", "Q1-70", "Q1i-50", "Q1i-70", "Q2-P50", "Q2-Q50", "Q2-Q70", "Q5-veto30", "Q3a", "Q3b",
            "Q3c", "Q6"} <= set(ARMS)


def test_pass_rates_on_real_shaped_table_are_nested():
    rng = np.random.default_rng(3)
    rows = [dict(cik=i, gpoa=rng.uniform(0, 0.8), net_income=rng.normal(3, 6), total_debt=rng.uniform(0, 70),
                 evol=rng.uniform(0.005, 0.06), equity_parent=rng.uniform(5, 80), cash=rng.uniform(0, 15),
                 ebitda=rng.normal(10, 8), cfo=rng.normal(6, 6), capex=rng.uniform(0, 5),
                 industry=f"I{i % 4}", group=f"G{i % 2}") for i in range(1, 301)]
    qt = table(rows)
    n = len(qt)
    p = {a: passes(qt, a) for a in ARMS}
    assert p["Q0"].sum() == n
    assert p["Q1-70"].sum() < p["Q1-50"].sum() < n
    assert (p["Q1-70"] & ~p["Q1-50"]).sum() == 0
    assert (p["Q2-Q70"] & ~p["Q2-Q50"]).sum() == 0
    assert (p["Q3c"] & ~p["Q3b"]).sum() == 0 and (p["Q6"] & ~p["Q3b"]).sum() == 0 and (p["Q6"] & ~p["Q1-50"]).sum() == 0
    # percentile arms keep about the right share
    assert 0.45 < p["Q1-50"].mean() < 0.55
    assert 0.25 < p["Q1-70"].mean() < 0.36
    assert 0.65 < p["Q5-veto30"].mean() < 0.75


# --------------------------------------------------------------------------------------------------
# Q4 blend
# --------------------------------------------------------------------------------------------------
def test_blend_score():
    rows = [dict(cik=i, gpoa=0.1 * i) for i in range(1, 6)]
    rows.append(dict(cik=6, sector="Financials", industry="Banks", group="Banks", gpoa=0.9))
    qt = table(rows)
    mom = pd.Series({1: 0.5, 2: 0.4, 3: 0.3, 4: 0.2, 5: 0.1, 6: 9.9, 77: 1.0})   # extra/fin names are ignored
    gp_rank = pd.Series({1: 0.0, 2: 0.25, 3: 0.5, 4: 0.75, 5: 1.0})
    mom_rank = pd.Series({1: 1.0, 2: 0.75, 3: 0.5, 4: 0.25, 5: 0.0})
    b = blend_score(qt, mom, 0.25)
    np.testing.assert_allclose(b.loc[1:5].to_numpy(), (0.75 * mom_rank + 0.25 * gp_rank).to_numpy())
    assert np.isnan(b.loc[6])                                                      # financials get no score
    np.testing.assert_allclose(blend_score(qt, mom, 0.0).loc[1:5].to_numpy(), mom_rank.to_numpy())
    np.testing.assert_allclose(blend_score(qt, mom, 1.0).loc[1:5].to_numpy(), gp_rank.to_numpy())
    assert b.index.equals(qt.index)
    # missing momentum -> NaN blend; other names re-ranked among available momentum values
    mom2 = mom.drop(3)
    b2 = blend_score(qt, mom2, 0.5)
    assert np.isnan(b2.loc[3]) and b2.loc[[1, 2, 4, 5]].notna().all()
    with pytest.raises(ValueError):
        blend_score(qt, mom, 1.5)
    with pytest.raises(ValueError):
        blend_score(qt, pd.Series({"AAA": 1.0, "BBB": 2.0}), 0.5)


# --------------------------------------------------------------------------------------------------
# speed
# --------------------------------------------------------------------------------------------------
def test_speed_1500_names():
    rng = np.random.default_rng(7)
    n = 1500
    rows = []
    for i in range(1, n + 1):
        rows.append(dict(cik=i, ticker=f"T{i}", sector=f"S{i % 10}", group=f"G{i % 25}", industry=f"I{i % 60}",
                         assets=rng.uniform(50, 1000), revenue=rng.uniform(50, 1000), cogs=rng.uniform(10, 500),
                         net_income=rng.normal(10, 30), cfo=rng.normal(20, 40), capex=rng.uniform(0, 30),
                         total_debt=rng.uniform(0, 300), cash=rng.uniform(0, 80), ebitda=rng.normal(40, 40),
                         evol=rng.uniform(0.005, 0.05), equity_parent=rng.normal(100, 80)))
    idx = pd.bdate_range("2012-01-02", DATE)
    R = pd.DataFrame(rng.normal(0, 0.015, (len(idx), n + 1)), index=idx, columns=["SPY"] + [f"T{i}" for i in range(1, n + 1)])
    R.iloc[:200, 5:300] = np.nan
    univ, fund = world(rows)
    ctx = StubCtx(fund, R)
    quality_table(ctx, DATE, univ)                      # warm (also fills beta cache)
    dates = [DATE - pd.Timedelta(days=30 * k) for k in range(1, 6)]
    t0 = time.perf_counter()
    for d in dates:                                      # uncached dates incl. beta computation
        quality_table(ctx, d, univ)
    per = (time.perf_counter() - t0) / len(dates)
    assert per < 0.5, f"{per:.3f}s per call"
