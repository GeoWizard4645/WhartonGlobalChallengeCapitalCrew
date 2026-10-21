"""Tests for quant/signals/key_metrics.py and quant/data/rates.py on synthetic frames (no network, no cache).

Every gate formula, label, the weekly-beta estimator, the split-basis share jump, the IPO / merger flags (incl. the
no-look-ahead rule for 8-K Item 2.01) and the DGS10 helpers are checked against hand computations.  One integration
test uses the real caches (snapshots / prices / membership) and is skipped when they are not built.
"""
from __future__ import annotations

import time

import numpy as np
import pandas as pd
import pytest

from quant.data import rates
from quant.shelved import key_metrics as km

DATE = pd.Timestamp("2016-06-30")          # a Thursday


# ----------------------------------------------------------------------------------------------
# Synthetic world
# ----------------------------------------------------------------------------------------------
def healthy(cik=1, **kw) -> dict:
    """A company that passes everything at DATE (flat 20% operating margin, positive FCF, modest net debt)."""
    row = dict(
        cik=cik, accn=f"a{cik}", form="10-Q", filed=pd.Timestamp("2016-05-10"), period_end=pd.Timestamp("2016-03-31"),
        revenue=1000.0, opinc=200.0, da=50.0, ebitda=250.0, pretax=190.0, tax=60.0, interest_exp=10.0,
        cfo=180.0, capex=60.0, acquisitions=0.0,
        total_debt=300.0, cash=100.0, st_investments=50.0, equity_total=800.0, assets=1500.0,
        total_debt_4q=280.0, equity_total_4q=750.0, cash_4q=90.0, assets_4q=1400.0,
        shares_diluted=100.0, shares_diluted_4q=100.0,
    )
    for k in range(1, 6):
        row[f"revenue_fy{k}"] = 1000.0
        row[f"opinc_fy{k}"] = 200.0
        row[f"cfo_fy{k}"] = 180.0
        row[f"capex_fy{k}"] = 60.0
    row.update(kw)
    return row


def weekdays(start="2013-01-01", end="2016-12-30") -> pd.DatetimeIndex:
    return pd.bdate_range(start, end)


class FakeCtx:
    """Just enough of DataContext for key_metrics_table."""

    def __init__(self, rows, returns=None, close=None, splits=None, mcap=2000.0):
        self._fund = pd.DataFrame(rows)
        self.returns = returns if returns is not None else pd.DataFrame(index=weekdays())
        self.close = close if close is not None else pd.DataFrame(1.0, index=self.returns.index,
                                                                 columns=self.returns.columns)
        self.splits = splits or {}
        self._mcap = mcap

    @property
    def snaps(self):
        return self._fund

    def trading_day_on_or_before(self, d):
        return pd.Timestamp(d)

    def fundamentals(self, date, max_age_days=200):
        """Latest filing per cik with filed < date (mirrors fundamentals.asof)."""
        f = self._fund[self._fund["filed"] < pd.Timestamp(date)]
        return f.sort_values("filed").groupby("cik").tail(1).set_index("cik").sort_index()

    def market_cap(self, date, univ=None, max_age_days=200):
        f = self.fundamentals(date)
        tick = univ.set_index("cik")["yf_ticker"]
        f = f[f.index.isin(tick.index)]
        mc = self._mcap if isinstance(self._mcap, dict) else None
        vals = [mc[c] if mc else self._mcap for c in f.index]
        return pd.DataFrame({"yf_ticker": tick.reindex(f.index), "mcap": vals}, index=f.index)

    def split_factor_after(self, ticker, d):
        out = 1.0
        for sd, ratio in self.splits.get(ticker, []):
            if pd.Timestamp(sd) > pd.Timestamp(d):
                out *= ratio
        return out


def market_returns(seed=0, idx=None, sigma=0.01) -> pd.Series:
    idx = weekdays() if idx is None else idx
    rng = np.random.default_rng(seed)
    return pd.Series(rng.normal(0.0004, sigma, len(idx)), index=idx, name="SPY")


def build(rows, tickers=None, params=None, date=DATE, ctx_kw=None, extra_returns=None, item201=None,
          first_filing=None, monkeypatch=None):
    """Run key_metrics_table on `rows`; every stock's returns equal SPY's (beta exactly 1) unless overridden."""
    rows = [dict(r) for r in rows]
    tickers = tickers or {r["cik"]: f"T{r['cik']}" for r in rows}
    spy = market_returns()
    ret = pd.DataFrame({"SPY": spy})
    for r in rows:
        ret[tickers[r["cik"]]] = spy
    if extra_returns is not None:
        for c in extra_returns.columns:
            ret[c] = extra_returns[c]
    ctx_kw = dict(ctx_kw or {})
    ctx_kw.setdefault("close", pd.DataFrame(1.0, index=ret.index, columns=ret.columns))
    ctx = FakeCtx(rows, returns=ret, **ctx_kw)
    km.clear_aux_cache()
    km._AUX["first_filing"] = first_filing if first_filing is not None else pd.Series(
        pd.Timestamp("1990-01-01"), index=sorted({r["cik"] for r in rows}))
    km._AUX["item201"] = item201 if item201 is not None else pd.DataFrame(
        {"cik": pd.Series(dtype="int64"), "filing_date": pd.Series(dtype="datetime64[ns]")})
    univ = pd.DataFrame({"cik": [r["cik"] for r in rows], "yf_ticker": [tickers[r["cik"]] for r in rows],
                         "gics_sector": "Information Technology"})
    p = {"rf_10y": 0.03}
    p.update(params or {})
    out = km.key_metrics_table(ctx, date, univ, p)
    km.clear_aux_cache()
    return out


# ----------------------------------------------------------------------------------------------
# API shape
# ----------------------------------------------------------------------------------------------
REQUIRED = ["yf_ticker", "nd_ebitda", "nd_label", "pass_leverage", "fcf_ttm", "fcf_pos_years", "fcf_ok", "om_ttm",
            "om_fy1", "om_fy2", "om_fy3", "om_fy4", "om_slope_pp", "margin_ok", "quality_ok", "tax_rate", "nopat",
            "ic_avg", "roic", "beta_raw", "beta_adj", "rf_10y", "ke", "kd", "wacc", "pass_roic", "listing_age_days",
            "recent_ipo", "acq_intensity", "share_jump", "asset_jump", "recent_merger", "pass_all", "fail_reasons"]


def test_default_params_exact():
    assert km.DEFAULT_PARAMS == dict(
        nd_max=3.0, fcf_years=3, fcf_min_pos=2, margin_years=4, slope_tol_pp=-0.5, recent_drop_pp=1.0, erp=0.05,
        beta_weeks=104, beta_min_weeks=90, ipo_days=730, acq_thr=0.10, share_thr=0.25, asset_thr=0.40)


def test_columns_index_and_healthy_company_passes():
    out = build([healthy(1), healthy(2)])
    assert out.index.name == "cik" and list(out.index) == [1, 2]
    for c in REQUIRED:
        assert c in out.columns, c
    r = out.loc[1]
    assert bool(r.pass_all) and r.fail_reasons == ""
    assert not r.recent_ipo and not r.recent_merger


def test_index_only_universe_members_with_snapshot():
    rows = [healthy(1), healthy(2), healthy(3, filed=pd.Timestamp("2016-07-15"))]   # 3 not filed yet at DATE
    tick = {1: "A", 2: "B", 3: "C"}
    ctx = FakeCtx(rows, returns=pd.DataFrame({"SPY": market_returns(), "A": market_returns(), "B": market_returns()}))
    km._AUX["first_filing"] = pd.Series(pd.Timestamp("1990-01-01"), index=[1, 2, 3])
    km._AUX["item201"] = pd.DataFrame({"cik": pd.Series(dtype="int64"), "filing_date": pd.Series(dtype="datetime64[ns]")})
    univ = pd.DataFrame({"cik": [1, 3, 99], "yf_ticker": ["A", "C", "Z"]})                # 2 not in univ, 99 no data
    out = km.key_metrics_table(ctx, DATE, univ, {"rf_10y": 0.03})
    km.clear_aux_cache()
    assert list(out.index) == [1]


# ----------------------------------------------------------------------------------------------
# Leverage
# ----------------------------------------------------------------------------------------------
@pytest.mark.parametrize("debt,cash,sti,ebitda,exp_nd,exp_label,exp_pass", [
    (100.0, 400.0, 0.0, 200.0, -1.5, "net cash", True),          # (100-400)/200
    (300.0, 100.0, 50.0, 300.0, 0.5, "low", True),               # (300-150)/300 incl. short-term investments
    (500.0, 0.0, 0.0, 500.0, 1.0, "low", True),                  # boundary 1.0 -> low
    (800.0, 100.0, 0.0, 350.0, 2.0, "ok", True),
    (1000.0, 0.0, 0.0, 300.0, 1000.0 / 300.0, "high", False),    # 3.33x
    (900.0, 0.0, 0.0, 300.0, 3.0, "ok", True),                   # boundary exactly nd_max passes
    (1500.0, 100.0, 0.0, 200.0, 7.0, "high", False),
])
def test_leverage_formula_labels(debt, cash, sti, ebitda, exp_nd, exp_label, exp_pass):
    out = build([healthy(1, total_debt=debt, cash=cash, st_investments=sti, ebitda=ebitda)])
    r = out.loc[1]
    assert r.nd_ebitda == pytest.approx(exp_nd, rel=1e-9)
    assert r.nd_label == exp_label
    assert bool(r.pass_leverage) is exp_pass


def test_leverage_undefined_when_ebitda_not_positive_or_missing():
    out = build([healthy(1, ebitda=-10.0), healthy(2, ebitda=0.0), healthy(3, ebitda=np.nan, opinc=np.nan, da=np.nan),
                 healthy(4, total_debt=np.nan)])
    assert (out["nd_label"] == "n/a").all()
    assert out["nd_ebitda"].isna().all()
    assert not out["pass_leverage"].any() and not out["pass_all"].any()
    assert "ebitda<=0" in out.loc[1, "fail_reasons"] and "ebitda<=0" in out.loc[2, "fail_reasons"]
    assert "nd_n/a" in out.loc[3, "fail_reasons"] and "nd_n/a" in out.loc[4, "fail_reasons"]


def test_leverage_ebitda_falls_back_to_opinc_plus_da_and_nd_max_param():
    out = build([healthy(1, ebitda=np.nan, opinc=200.0, da=100.0, total_debt=1000.0, cash=100.0, st_investments=0.0)],
                params={"nd_max": 2.0})
    assert out.loc[1, "ebitda_ttm"] == 300.0
    assert out.loc[1, "nd_ebitda"] == pytest.approx(3.0)
    assert out.loc[1, "nd_label"] == "high" and not out.loc[1, "pass_leverage"]       # 3.0 > nd_max 2.0
    assert "nd_ebitda>2" in out.loc[1, "fail_reasons"]


def test_missing_debt_is_carried_from_an_earlier_filing_point_in_time():
    k10 = healthy(1, filed=pd.Timestamp("2016-02-20"), period_end=pd.Timestamp("2015-12-31"), total_debt=500.0)
    q10 = healthy(1, filed=pd.Timestamp("2016-05-10"), total_debt=np.nan, total_debt_4q=np.nan)
    later = healthy(1, filed=pd.Timestamp("2016-08-10"), period_end=pd.Timestamp("2016-06-30"), total_debt=900.0)
    o = build([k10, q10, later]).loc[1]
    assert o.total_debt == 500.0 and bool(o.debt_carried)                  # the 2016-08 filing is invisible at DATE
    assert o.nd_ebitda == pytest.approx((500.0 - 150.0) / 250.0)
    assert np.isfinite(o.wacc)
    # not carried when switched off, when the earlier value is too old, or when the current filing has a value
    off = build([k10, q10, later], params={"debt_carry_days": 0}).loc[1]
    assert np.isnan(off.total_debt) and not off.debt_carried
    old = healthy(1, filed=pd.Timestamp("2014-02-20"), period_end=pd.Timestamp("2013-12-31"), total_debt=500.0)
    assert np.isnan(build([old, q10]).loc[1, "total_debt"])
    has = build([k10, healthy(1, filed=pd.Timestamp("2016-05-10"), total_debt=300.0)]).loc[1]
    assert has.total_debt == 300.0 and not has.debt_carried


def test_short_term_investments_missing_treated_as_zero_but_missing_cash_is_na():
    out = build([healthy(1, st_investments=np.nan), healthy(2, cash=np.nan)])
    assert out.loc[1, "cash_total"] == 100.0
    assert np.isnan(out.loc[2, "nd_ebitda"])


# ----------------------------------------------------------------------------------------------
# FCF and margins
# ----------------------------------------------------------------------------------------------
def test_fcf_ttm_and_positive_year_count():
    out = build([
        healthy(1, cfo=100.0, capex=30.0),                                          # +70; fy all +120
        healthy(2, cfo=100.0, capex=130.0),                                         # negative TTM
        healthy(3, cfo_fy1=50.0, capex_fy1=80.0, cfo_fy2=50.0, capex_fy2=80.0),     # only fy3 positive -> 1 < 2
        healthy(4, cfo_fy1=50.0, capex_fy1=80.0),                                   # two of three positive -> ok
        healthy(5, capex=np.nan),                                                   # capex missing -> n/a, fails
    ])
    assert out.loc[1, "fcf_ttm"] == 70.0 and out.loc[1, "fcf_pos_years"] == 3 and out.loc[1, "fcf_ok"]
    assert out.loc[2, "fcf_ttm"] == -30.0 and not out.loc[2, "fcf_ok"]
    assert "fcf_ttm<=0" in out.loc[2, "fail_reasons"]
    assert out.loc[3, "fcf_pos_years"] == 1 and not out.loc[3, "fcf_ok"]
    assert "fcf_pos_years<2" in out.loc[3, "fail_reasons"]
    assert out.loc[4, "fcf_pos_years"] == 2 and out.loc[4, "fcf_ok"]
    assert np.isnan(out.loc[5, "fcf_ttm"]) and not out.loc[5, "fcf_ok"]
    assert "fcf_n/a" in out.loc[5, "fail_reasons"]


def test_capex_missing_sensitivity_uses_cfo_as_proxy():
    row = healthy(1, capex=np.nan, capex_fy1=np.nan, capex_fy2=np.nan, capex_fy3=np.nan)
    base = build([row]).loc[1]
    assert np.isnan(base.fcf_ttm) and base.fcf_pos_years == 0 and not base.fcf_ok
    proxy = build([row], params={"capex_missing": "cfo"}).loc[1]
    assert proxy.fcf_ttm == 180.0 and proxy.fcf_pos_years == 3 and proxy.fcf_ok


def test_fcf_params_years_and_min_pos():
    row = healthy(1, cfo_fy1=50.0, capex_fy1=80.0, cfo_fy2=50.0, capex_fy2=80.0, cfo_fy3=50.0, capex_fy3=80.0,
                  cfo_fy4=500.0, capex_fy4=10.0)
    base = build([row]).loc[1]
    assert base.fcf_pos_years == 0 and not base.fcf_ok
    wide = build([row], params={"fcf_years": 4, "fcf_min_pos": 1}).loc[1]
    assert wide.fcf_pos_years == 1 and wide.fcf_ok


def margins_row(oms, ttm=0.20, cik=1, **kw):
    """Fiscal-year margins oms = [fy1(latest), fy2, fy3, fy4]; revenue 1000 each."""
    r = healthy(cik, revenue=1000.0, opinc=ttm * 1000.0, **kw)
    for k, m in enumerate(oms, start=1):
        r[f"revenue_fy{k}"] = 1000.0
        r[f"opinc_fy{k}"] = m * 1000.0 if np.isfinite(m) else np.nan
    return r


def test_row_ols_slope_matches_polyfit_with_nans():
    y = np.array([[0.10, 0.12, 0.15, 0.20], [0.2, np.nan, 0.2, 0.2], [np.nan, np.nan, 0.1, 0.2], [1, 2, 3, np.nan]])
    s, n = km.row_ols_slope(y)
    assert s[0] == pytest.approx(np.polyfit(range(4), y[0], 1)[0])
    assert s[1] == pytest.approx(0.0, abs=1e-15) and n[1] == 3
    assert s[2] == pytest.approx(0.1) and n[2] == 2 and s[3] == pytest.approx(1.0)
    assert np.isnan(km.row_ols_slope(np.array([[1.0, np.nan, np.nan, np.nan]]))[0][0])


@pytest.mark.parametrize("oms,ttm,ok,reason", [
    ([0.20, 0.19, 0.18, 0.17], 0.21, True, ""),                          # improving (fy1 is latest)
    ([0.20, 0.20, 0.20, 0.20], 0.20, True, ""),                          # flat
    ([0.15, 0.16, 0.17, 0.18], 0.15, False, "margin_slope"),             # falling 1pp/yr
    ([0.10, 0.14, 0.18, 0.22], 0.10, False, "margin_slope"),             # -4 pp/yr
    ([0.20, 0.20, 0.20, 0.20], 0.18, False, "margin_recent_drop"),       # slope 0 but ttm 2pp below fy1
    ([0.20, 0.20, 0.20, np.nan], 0.20, True, ""),                        # 3 years is enough
    ([0.20, 0.20, np.nan, np.nan], 0.20, False, "margin_history<3y"),
    ([0.20, 0.20, 0.20, 0.20], 0.0, False, "om_ttm<=0"),
    ([0.20, 0.20, 0.20, 0.20], -0.05, False, "om_ttm<=0"),
])
def test_margin_stability(oms, ttm, ok, reason):
    r = build([margins_row(oms, ttm)]).loc[1]
    assert bool(r.margin_ok) is ok
    if reason:
        assert reason in r.fail_reasons


def test_margin_slope_value_and_columns():
    r = build([margins_row([0.22, 0.20, 0.19, 0.16], 0.22)]).loc[1]
    x = np.arange(4)
    expected = np.polyfit(x, [0.16, 0.19, 0.20, 0.22], 1)[0] * 100
    assert r.om_slope_pp == pytest.approx(expected)
    assert r.om_n == 4 and (r.om_fy1, r.om_fy2, r.om_fy3, r.om_fy4) == pytest.approx((0.22, 0.20, 0.19, 0.16))
    assert r.om_ttm == pytest.approx(0.22)
    assert r.margin_ok


def test_margin_tolerance_boundary_and_params():
    # slope -0.45 pp/yr passes the default tolerance (-0.5), -0.55 fails; a tighter tolerance fails the first
    ok_row = margins_row([0.20, 0.2045, 0.209, 0.2135], 0.20)
    bad_row = margins_row([0.20, 0.2055, 0.211, 0.2165], 0.20)
    assert build([ok_row]).loc[1, "om_slope_pp"] == pytest.approx(-0.45)
    assert build([ok_row]).loc[1, "margin_ok"] and not build([bad_row]).loc[1, "margin_ok"]
    assert not build([ok_row], params={"slope_tol_pp": -0.4}).loc[1, "margin_ok"]
    # a 0.9pp recent drop passes, 1.5pp fails unless recent_drop_pp is relaxed
    assert build([margins_row([0.20] * 4, 0.191)]).loc[1, "margin_ok"]
    assert not build([margins_row([0.20] * 4, 0.185)]).loc[1, "margin_ok"]
    assert build([margins_row([0.20] * 4, 0.185)], params={"recent_drop_pp": 2.0}).loc[1, "margin_ok"]


def test_margin_uses_latest_available_year_when_fy1_missing():
    r = build([margins_row([np.nan, 0.20, 0.20, 0.20], 0.17)]).loc[1]            # ttm 3pp below fy2
    assert not r.margin_ok and "margin_recent_drop" in r.fail_reasons


def test_quality_ok_combines_fcf_and_margin():
    out = build([healthy(1), healthy(2, cfo=10.0, capex=60.0), margins_row([0.10, 0.14, 0.18, 0.22], 0.10, cik=3)])
    assert out["quality_ok"].tolist() == [True, False, False]
    assert out["fcf_ok"].tolist() == [True, False, True] and out["margin_ok"].tolist() == [True, True, False]


# ----------------------------------------------------------------------------------------------
# ROIC / WACC
# ----------------------------------------------------------------------------------------------
def test_tax_rate_clip_and_statutory():
    rows = [healthy(1, pretax=100.0, tax=50.0),      # 50% -> clip 35%
            healthy(2, pretax=100.0, tax=2.0),       # 2% -> clip 10%
            healthy(3, pretax=100.0, tax=20.0),      # 20%
            healthy(4, pretax=-50.0, tax=-5.0),      # loss -> statutory
            healthy(5, pretax=100.0, tax=np.nan)]    # missing tax -> statutory
    o16 = build(rows, date=pd.Timestamp("2016-06-30"))
    assert o16["tax_rate"].tolist() == pytest.approx([0.35, 0.10, 0.20, 0.35, 0.35])
    o20 = build([dict(r, filed=pd.Timestamp("2020-05-10"), period_end=pd.Timestamp("2020-03-31")) for r in rows],
                date=pd.Timestamp("2020-06-30"))
    assert o20["tax_rate"].tolist() == pytest.approx([0.35, 0.10, 0.20, 0.21, 0.21])


def test_roic_nopat_and_average_invested_capital():
    r = build([healthy(1)]).loc[1]
    t = 60.0 / 190.0
    assert r.tax_rate == pytest.approx(t)
    assert r.nopat == pytest.approx(200.0 * (1 - t))
    ic_now = 300 + 800 - 100 - 50
    ic_prev = 280 + 750 - 90 - 50                    # short-term investments carried from today
    assert r.ic_avg == pytest.approx((ic_now + ic_prev) / 2)
    assert r.roic == pytest.approx(200.0 * (1 - t) / ((ic_now + ic_prev) / 2))
    assert not r.capital_light


def test_ic_falls_back_to_current_when_year_ago_missing():
    r = build([healthy(1, total_debt_4q=np.nan, equity_total_4q=np.nan, cash_4q=np.nan)]).loc[1]
    assert r.ic_avg == pytest.approx(300 + 800 - 100 - 50)


def test_capital_light_gives_infinite_roic_and_passes():
    r = build([healthy(1, total_debt=0.0, total_debt_4q=0.0, equity_total=50.0, equity_total_4q=60.0, cash=500.0,
                       cash_4q=500.0, st_investments=0.0)]).loc[1]
    assert r.ic_avg < 0 and r.capital_light and np.isinf(r.roic) and r.roic > 0
    assert r.pass_roic
    r2 = build([healthy(1, total_debt=0.0, total_debt_4q=0.0, equity_total=50.0, equity_total_4q=60.0, cash=500.0,
                        cash_4q=500.0, st_investments=0.0, opinc=-100.0)]).loc[1]
    assert not r2.capital_light and np.isnan(r2.roic) and not r2.pass_roic
    assert "roic_n/a" in r2.fail_reasons


def test_wacc_hand_computation_and_pass_roic():
    # beta of every synthetic stock is exactly 1 (returns identical to SPY) -> beta_adj = 1, Ke = 0.03 + 0.05
    r = build([healthy(1)], ctx_kw=dict(mcap=2000.0)).loc[1]
    assert r.beta_raw == pytest.approx(1.0) and r.beta_adj == pytest.approx(1.0)
    assert r.rf_10y == 0.03 and r.ke == pytest.approx(0.08)
    t = 60.0 / 190.0
    kd = 10.0 / ((300.0 + 280.0) / 2)
    assert r.kd == pytest.approx(kd)
    wacc = 2000 / 2300 * 0.08 + 300 / 2300 * kd * (1 - t)
    assert r.wacc == pytest.approx(wacc)
    assert r.roic > r.wacc and r.pass_roic
    # huge market cap-weighted equity but low operating income => fails
    low = build([healthy(1, opinc=20.0)]).loc[1]
    assert low.roic < low.wacc and not low.pass_roic and "roic<=wacc" in low.fail_reasons and not low.pass_all


def test_kd_clip_and_fallback_rules():
    rf = 0.03
    rows = [healthy(1, interest_exp=2.0),                       # 2/290 = 0.7% -> clipped up to rf
            healthy(2, interest_exp=100.0),                     # 34% -> capped at 12%
            healthy(3, interest_exp=np.nan),                    # missing -> rf + 2%
            healthy(4, interest_exp=0.0),                       # zero => treated as missing
            healthy(5, total_debt=10.0, total_debt_4q=10.0, interest_exp=5.0)]    # debt < 1% of mcap (2000) -> rf+2%
    o = build(rows, ctx_kw=dict(mcap=2000.0))
    assert o["kd"].tolist() == pytest.approx([rf, 0.12, rf + 0.02, rf + 0.02, rf + 0.02])


def test_wacc_nan_without_market_cap_or_debt():
    o = build([healthy(1, total_debt=np.nan)])
    assert np.isnan(o.loc[1, "wacc"]) and not o.loc[1, "pass_roic"]
    o = build([healthy(1)], ctx_kw=dict(mcap=np.nan))
    assert np.isnan(o.loc[1, "wacc"]) and not o.loc[1, "pass_roic"] and "wacc_n/a" in o.loc[1, "fail_reasons"]


def test_erp_param_moves_ke():
    r = build([healthy(1)], params={"erp": 0.06}).loc[1]
    assert r.ke == pytest.approx(0.03 + 0.06)


def test_statutory_tax_function():
    assert km.statutory_tax("2017-12-29") == 0.35 and km.statutory_tax("2018-01-02") == 0.21


# ----------------------------------------------------------------------------------------------
# Beta
# ----------------------------------------------------------------------------------------------
def simulated_returns(betas: dict, noise=0.001, seed=1, start_offset: dict | None = None) -> pd.DataFrame:
    idx = weekdays()
    spy = market_returns(idx=idx)
    rng = np.random.default_rng(seed)
    df = pd.DataFrame({"SPY": spy})
    for t, b in betas.items():
        s = b * spy + rng.normal(0, noise, len(idx))
        if start_offset and t in start_offset:
            s.iloc[:start_offset[t]] = np.nan
        df[t] = s
    return df


def test_beta_recovers_known_values():
    ret = simulated_returns({"HI": 1.5, "LO": 0.5, "NEG": -0.3})
    ctx = FakeCtx([healthy(1)], returns=ret)
    b = km.betas_at(ctx, DATE, ["HI", "LO", "NEG", "MISSING"])
    assert b.loc["HI", "beta_raw"] == pytest.approx(1.5, abs=0.05)
    assert b.loc["LO", "beta_raw"] == pytest.approx(0.5, abs=0.05)
    assert b.loc["NEG", "beta_raw"] == pytest.approx(-0.3, abs=0.05)
    assert np.isnan(b.loc["MISSING", "beta_raw"]) and b.loc["MISSING", "beta_n"] == 0
    assert b.loc["HI", "beta_n"] == 104


def test_beta_matches_statsmodels_style_ols_on_weekly_returns():
    ret = simulated_returns({"X": 1.2}, noise=0.01, seed=5)
    ctx = FakeCtx([healthy(1)], returns=ret)
    w = km.weekly_returns(ret)
    w = w[w.index <= DATE].iloc[-104:]
    ref = np.polyfit(w["SPY"], w["X"], 1)[0]
    assert km.betas_at(ctx, DATE, ["X"]).loc["X", "beta_raw"] == pytest.approx(ref, rel=1e-9)


def test_weekly_returns_compound_and_friday_label():
    idx = pd.bdate_range("2016-06-06", "2016-06-17")             # two full weeks
    d = pd.DataFrame({"A": 0.01}, index=idx)
    w = km.weekly_returns(d)
    assert list(w.index) == [pd.Timestamp("2016-06-10"), pd.Timestamp("2016-06-17")]
    assert w["A"].tolist() == pytest.approx([1.01 ** 5 - 1] * 2)
    idx2 = pd.DatetimeIndex(["2016-06-27", "2016-06-28", "2016-06-29", "2016-06-30"])          # partial week
    w2 = km.weekly_returns(pd.DataFrame({"A": [0.01, np.nan, np.nan, 0.01]}, index=idx2))
    assert w2["A"].iloc[0] == pytest.approx(1.01 ** 2 - 1)
    assert km.weekly_returns(pd.DataFrame({"A": [np.nan] * 4}, index=idx2))["A"].isna().all()


def test_beta_requires_min_weeks():
    ret = simulated_returns({"OLD": 1.0, "NEW": 1.0}, start_offset={"NEW": int(weekdays().searchsorted(pd.Timestamp("2015-05-04")))})
    # NEW starts trading 2015-05-04: about 60 weekly returns exist at DATE (< 90 => no beta)
    ctx = FakeCtx([healthy(1)], returns=ret)
    b = km.betas_at(ctx, DATE, ["OLD", "NEW"])
    assert b.loc["OLD", "beta_n"] == 104 and not np.isnan(b.loc["OLD", "beta_raw"])
    assert b.loc["NEW", "beta_n"] < 90 and np.isnan(b.loc["NEW", "beta_raw"])
    b2 = km.betas_at(ctx, DATE, ["NEW"], min_weeks=int(b.loc["NEW", "beta_n"]))
    assert not np.isnan(b2.loc["NEW", "beta_raw"])


def test_beta_uses_only_last_104_weeks_and_no_lookahead():
    idx = weekdays()
    spy = market_returns(idx=idx)
    cut = idx.searchsorted(pd.Timestamp("2014-06-01"))
    rng = np.random.default_rng(3)
    stock = 2.0 * spy + rng.normal(0, 0.001, len(idx))
    stock.iloc[cut:] = 0.8 * spy.iloc[cut:] + rng.normal(0, 0.001, len(idx) - cut)       # beta shifts to 0.8
    ret = pd.DataFrame({"SPY": spy, "S": stock})
    b = km.betas_at(FakeCtx([healthy(1)], returns=ret), DATE, ["S"]).loc["S", "beta_raw"]
    assert b == pytest.approx(0.8, abs=0.05)                     # the 2.0 regime is outside the 104-week window
    # change everything after DATE: the beta at DATE must not move
    ret2 = ret.copy()
    ret2.loc[ret2.index > DATE, "S"] = -5 * ret2.loc[ret2.index > DATE, "SPY"]
    b2 = km.betas_at(FakeCtx([healthy(1)], returns=ret2), DATE, ["S"]).loc["S", "beta_raw"]
    assert b2 == pytest.approx(b)
    # the partial week containing DATE (Thursday) is excluded: altering Friday-after-DATE data cannot matter either
    ret3 = ret.copy()
    ret3.loc[pd.Timestamp("2016-06-27"):pd.Timestamp("2016-06-30"), "S"] = 0.5
    assert km.betas_at(FakeCtx([healthy(1)], returns=ret3), DATE, ["S"]).loc["S", "beta_raw"] == pytest.approx(b)


def test_blume_adjustment_in_table():
    ret = simulated_returns({"T1": 1.5}, noise=0.0)
    r = build([healthy(1)], tickers={1: "T1"}, extra_returns=ret[["T1"]]).loc[1]
    assert r.beta_raw == pytest.approx(1.5, abs=0.03)
    assert r.beta_adj == pytest.approx(0.67 * r.beta_raw + 0.33)
    assert r.ke == pytest.approx(0.03 + (0.67 * r.beta_raw + 0.33) * 0.05)


def test_beta_cached_per_date():
    ret = simulated_returns({"A": 1.1})
    ctx = FakeCtx([healthy(1)], returns=ret)
    km.betas_at(ctx, DATE, ["A"])
    assert ("beta", DATE, 104, 90) in ctx._km_cache
    assert "weekly" in ctx._km_cache


# ----------------------------------------------------------------------------------------------
# Recent IPO
# ----------------------------------------------------------------------------------------------
def test_recent_ipo_uses_min_of_first_price_and_first_filing():
    idx = weekdays()
    close = pd.DataFrame(1.0, index=idx, columns=["SPY", "T1", "T2", "T3", "T4"])
    close.loc[idx < "2015-09-01", "T1"] = np.nan                  # prices start 2015-09-01 (age 303d at DATE)
    close.loc[idx < "2016-01-04", "T2"] = np.nan                  # prices start 2016-01-04 (age 178d)
    close.loc[idx < "2014-06-02", "T3"] = np.nan                  # prices start 2014-06-02 (age 759d)
    ff = pd.Series({1: pd.Timestamp("2015-06-01"),                # filing before first price: min is the filing
                    2: pd.Timestamp("2010-01-04"),                # long-lived filer: min is the old filing => not IPO
                    3: pd.Timestamp("2014-07-01"),
                    4: pd.Timestamp("1995-01-01")})
    rows = [healthy(i) for i in (1, 2, 3, 4)]
    o = build(rows, ctx_kw=dict(close=close), first_filing=ff)
    ages = o["listing_age_days"].tolist()
    assert ages[0] == (DATE - pd.Timestamp("2015-06-01")).days            # 395
    assert ages[1] == (DATE - pd.Timestamp("2010-01-04")).days
    assert ages[2] == (DATE - pd.Timestamp("2014-06-02")).days            # first price earlier than first filing
    assert ages[3] == (DATE - pd.Timestamp("1995-01-01")).days
    assert o["recent_ipo"].tolist() == [True, False, False, False]
    # ipo_days param: 365 days => company 1 (395d) no longer flagged; 1095 => company 3 (759d) flagged
    assert not build(rows, ctx_kw=dict(close=close), first_filing=ff, params={"ipo_days": 365}).loc[1, "recent_ipo"]
    assert build(rows, ctx_kw=dict(close=close), first_filing=ff, params={"ipo_days": 1095}).loc[3, "recent_ipo"]


def test_recent_ipo_unknown_when_no_dates():
    o = build([healthy(1)], first_filing=pd.Series(dtype="datetime64[ns]"),
              ctx_kw=dict(close=pd.DataFrame(np.nan, index=weekdays(), columns=["SPY", "T1"])))
    assert pd.isna(o.loc[1, "listing_age_days"]) and not o.loc[1, "recent_ipo"]


def test_recent_ipo_does_not_enter_pass_all():
    ff = pd.Series({1: pd.Timestamp("2016-01-04")})
    idx = weekdays()
    close = pd.DataFrame(1.0, index=idx, columns=["SPY", "T1"])
    close.loc[idx < "2016-01-04", "T1"] = np.nan
    o = build([healthy(1)], first_filing=ff, ctx_kw=dict(close=close))
    assert o.loc[1, "recent_ipo"] and o.loc[1, "pass_all"]            # flags are reported, applied by the strategy


# ----------------------------------------------------------------------------------------------
# Recent merger
# ----------------------------------------------------------------------------------------------
def item201(*pairs) -> pd.DataFrame:
    return pd.DataFrame({"cik": pd.Series([p[0] for p in pairs], dtype="int64"),
                         "filing_date": pd.to_datetime([p[1] for p in pairs])})


def test_acquisition_intensity_flag():
    o = build([healthy(1, acquisitions=140.0),                      # 140/1400 = 10% -> flag (>=)
               healthy(2, acquisitions=139.0),
               healthy(3, acquisitions=np.nan),                     # missing => 0
               healthy(4, acquisitions=300.0, assets_4q=np.nan)])   # no denominator => no flag
    assert o["acq_intensity"].iloc[:3].tolist() == pytest.approx([0.10, 139 / 1400, 0.0])
    assert o["recent_merger"].tolist() == [True, False, False, False]
    assert build([healthy(2, acquisitions=139.0)], params={"acq_thr": 0.05}).loc[2, "recent_merger"]


def test_share_jump_same_basis_no_split():
    o = build([healthy(1, shares_diluted=125.0, shares_diluted_4q=100.0),           # +25% -> flag (>=)
               healthy(2, shares_diluted=80.0, shares_diluted_4q=100.0),            # -20%
               healthy(3, shares_diluted=70.0, shares_diluted_4q=100.0),            # -30% buyback -> abs() flags
               healthy(4, shares_diluted=np.nan),
               healthy(5, shares_diluted=0.0)])                                     # zero = data error, not a -100% jump
    assert o["share_jump"].iloc[:3].tolist() == pytest.approx([0.25, 0.20, 0.30])
    assert o["recent_merger"].tolist() == [True, False, True, False, False]


def test_share_jump_split_basis():
    splits = {"SPL": [(pd.Timestamp("2015-12-01"), 4.0)], "RSP": [(pd.Timestamp("2015-12-01"), 0.1)]}
    rows = [healthy(1, shares_diluted=400.0, shares_diluted_4q=100.0),        # year-ago count as originally reported
            healthy(2, shares_diluted=100.0, shares_diluted_4q=100.0),        # year-ago already restated for the split
            healthy(3, shares_diluted=800.0, shares_diluted_4q=100.0),        # 4:1 split AND doubling: not explained
            healthy(4, shares_diluted=10.0, shares_diluted_4q=100.0),         # 1:10 reverse split, raw year-ago
            healthy(5, shares_diluted=150.0, shares_diluted_4q=100.0)]        # no split, +50%
    tick = {1: "SPL", 2: "SPL", 3: "SPL", 4: "RSP", 5: "NOS"}
    o = build(rows, tickers=tick, ctx_kw=dict(splits=splits))
    assert o["share_jump"].tolist() == pytest.approx([0.0, 0.0, 7.0, 0.0, 0.5])      # case 3 keeps the plain ratio
    assert o["recent_merger"].tolist() == [False, False, True, False, True]
    # naive (no split handling) would have flagged companies 1, 2 and 4 -- confirm the split table matters
    naive = build(rows, tickers=tick, ctx_kw=dict(splits={}))
    assert naive["share_jump"].tolist() == pytest.approx([3.0, 0.0, 7.0, 0.9, 0.5])


def test_split_explains_share_change_only_within_tolerance():
    splits = {"SPL": [(pd.Timestamp("2015-12-01"), 4.0)]}
    rows = [healthy(1, shares_diluted=420.0, shares_diluted_4q=100.0),       # adj = 1.05: split explains (buybacks etc.)
            healthy(2, shares_diluted=460.0, shares_diluted_4q=100.0)]       # adj = 1.15: not explained -> plain ratio
    o = build(rows, tickers={1: "SPL", 2: "SPL"}, ctx_kw=dict(splits=splits))
    assert o["share_jump"].tolist() == pytest.approx([0.05, 3.6])
    assert o["recent_merger"].tolist() == [False, True]


def test_asset_jump_needs_item_201_and_is_point_in_time():
    rows = [healthy(i, assets=2100.0, assets_4q=1400.0) for i in (1, 2, 3, 4, 5, 6)]       # +50% assets
    items = item201(
        (1, "2016-03-15"),        # inside the 365-day window -> flag
        (2, "2015-07-01"),        # exactly 365 days before DATE -> inside (inclusive)
        (3, "2015-06-29"),        # 367 days -> too old
        (4, "2016-06-30"),        # filed ON the decision date -> not usable (filed < date)
        (5, "2016-08-01"),        # filed after the decision date -> look-ahead, must be ignored
    )                             # company 6: no 8-K
    o = build(rows, item201=items)
    assert o["asset_jump"].tolist() == pytest.approx([0.5] * 6)
    assert o["has_item_201"].tolist() == [True, True, False, False, False, False]
    assert o["recent_merger"].tolist() == [True, True, False, False, False, False]


def test_asset_jump_below_threshold_or_without_8k_is_not_a_merger():
    items = item201((1, "2016-03-15"), (2, "2016-03-15"))
    o = build([healthy(1, assets=1900.0, assets_4q=1400.0),             # +35.7% < 40% even with an 8-K
               healthy(2, assets=1961.0, assets_4q=1400.0),             # +40.07% with an 8-K -> flag
               healthy(3, assets=3000.0, assets_4q=1400.0)],            # +114%, no 8-K -> organic growth
              item201=items)
    assert o["recent_merger"].tolist() == [False, True, False]


def test_load_item_201_parses_item_codes(monkeypatch):
    from quant.data import sec

    f = pd.DataFrame({
        "cik": [1, 2, 3, 4, 5, 6],
        "form": ["8-K"] * 6,
        "filing_date": pd.to_datetime(["2016-01-05", "2016-01-06", "2016-01-07", "2016-01-08", "2016-01-09",
                                       "2016-01-10"]),
        "items": ["2.01,9.01", "1.01,2.01", "12.01", "2.02,9.01", None, "2.01"],
    })
    monkeypatch.setattr(sec, "load_filings", lambda forms=None, ciks=None: f)
    got = km._load_item_201()
    assert sorted(got["cik"].tolist()) == [1, 2, 6]


def test_fail_reasons_and_pass_all_combination():
    o = build([healthy(1, total_debt=5000.0),                           # leverage fails
               healthy(2, cfo=10.0),                                    # fcf fails
               healthy(3, opinc=5.0, ebitda=55.0),                      # roic fails (and margin recent drop)
               healthy(4)])
    assert o["pass_all"].tolist() == [False, False, False, True]
    assert o.loc[1, "fail_reasons"].startswith("nd_ebitda>3")
    assert "fcf_ttm<=0" in o.loc[2, "fail_reasons"]
    assert "roic<=wacc" in o.loc[3, "fail_reasons"]
    assert o.loc[4, "fail_reasons"] == ""
    assert (o["pass_all"] == (o["pass_leverage"] & o["quality_ok"] & o["pass_roic"])).all()


def test_no_lookahead_in_fundamentals_selection():
    """key_metrics only sees what ctx.fundamentals(date) returns: a later filing changes nothing before it is filed."""
    old = healthy(1, filed=pd.Timestamp("2016-02-20"))
    new = healthy(1, filed=pd.Timestamp("2016-07-20"), opinc=20.0)
    at_date = build([old, new])
    assert at_date.loc[1, "nopat"] > 100                                   # uses the old filing
    later = build([old, new], date=pd.Timestamp("2016-08-01"))
    assert later.loc[1, "nopat"] < 20


# ----------------------------------------------------------------------------------------------
# Performance
# ----------------------------------------------------------------------------------------------
def test_performance_1500_names():
    n = 1500
    rng = np.random.default_rng(0)
    rows = [healthy(i + 1, total_debt=float(rng.uniform(0, 900)), opinc=float(rng.uniform(50, 300)))
            for i in range(n)]
    tick = {r["cik"]: f"T{r['cik']}" for r in rows}
    idx = weekdays("2012-01-02", "2016-12-30")
    spy = market_returns(idx=idx)
    ret = pd.DataFrame({t: rng.uniform(0.2, 1.8) * spy + rng.normal(0, 0.01, len(idx)) for t in tick.values()})
    ret.insert(0, "SPY", spy)
    ctx = FakeCtx(rows, returns=ret, close=pd.DataFrame(1.0, index=idx, columns=ret.columns))
    km.clear_aux_cache()
    km._AUX["first_filing"] = pd.Series(pd.Timestamp("1990-01-01"), index=list(tick))
    km._AUX["item201"] = item201((1, "2016-01-05"))
    univ = pd.DataFrame({"cik": list(tick), "yf_ticker": list(tick.values())})
    t0 = time.time()
    first = km.key_metrics_table(ctx, pd.Timestamp("2016-05-31"), univ, {"rf_10y": 0.02})      # includes weekly build
    t1 = time.time()
    second = km.key_metrics_table(ctx, pd.Timestamp("2016-06-30"), univ, {"rf_10y": 0.02})
    t2 = time.time()
    km.clear_aux_cache()
    assert len(first) == n and len(second) == n
    assert (t2 - t1) < 1.0, f"per-date call took {t2 - t1:.2f}s"
    assert (t1 - t0) < 5.0
    assert second["beta_raw"].notna().all()


# ----------------------------------------------------------------------------------------------
# rates.py
# ----------------------------------------------------------------------------------------------
def test_parse_fred_csv_both_headers_and_dots():
    for hdr in ("DATE", "observation_date"):
        txt = f"{hdr},DGS10\n2016-06-28,1.47\n2016-06-29,.\n2016-06-30,1.49\n"
        s = rates.parse_fred_csv(txt)
        assert s.index.tolist() == pd.to_datetime(["2016-06-28", "2016-06-29", "2016-06-30"]).tolist()
        assert s.iloc[0] == pytest.approx(0.0147) and np.isnan(s.iloc[1]) and s.iloc[2] == pytest.approx(0.0149)


def test_clean_daily_forward_fills_and_drops_garbage():
    s = pd.Series([0.0147, np.nan, 0.0149, 4.9, np.nan],
                  index=pd.to_datetime(["2016-06-28", "2016-06-29", "2016-06-30", "2016-07-01", "2016-07-04"]))
    c = rates.clean_daily(s)
    assert c.loc["2016-06-29"] == pytest.approx(0.0147)               # holiday-style gap forward-filled
    assert c.loc["2016-07-01"] == pytest.approx(0.0149)               # 490% is a unit error -> dropped then filled
    assert not c.isna().any()


def test_ten_year_asof_no_lookahead(monkeypatch):
    s = pd.Series([0.01, 0.02, 0.03], index=pd.to_datetime(["2016-06-27", "2016-06-30", "2016-07-05"]))
    monkeypatch.setitem(rates._MEM, "s", s)
    assert rates.ten_year("2016-06-29") == 0.01                      # before the 30th's print
    assert rates.ten_year("2016-06-30") == 0.02
    assert rates.ten_year("2016-07-02") == 0.02                      # weekend: last observation
    assert rates.ten_year("2016-07-05") == 0.03
    assert rates.ten_year("2030-01-01") == 0.03
    assert rates.ten_year(None) == 0.03
    assert rates.ten_year("2000-01-01") == 0.01                      # before first observation: first value


def test_load_dgs10_uses_cache_without_network(tmp_path, monkeypatch):
    s = pd.Series([0.015, 0.016], index=pd.to_datetime(["2016-06-29", "2016-06-30"]), name="dgs10")
    monkeypatch.setattr(rates, "DGS10_PATH", tmp_path / "dgs10.parquet")
    monkeypatch.setattr(rates, "_MEM", {})
    monkeypatch.setitem(rates._TRIED_REFRESH, "done", True)          # forbid network attempts
    rates._write_cache(s, "fred")
    got = rates.load_dgs10()
    assert got.tolist() == pytest.approx([0.015, 0.016])
    monkeypatch.setattr(rates, "_download_fred", lambda: (_ for _ in ()).throw(AssertionError("network used")))
    assert rates.ten_year("2016-06-30") == pytest.approx(0.016)


def test_refresh_falls_back_to_yahoo_when_fred_fails(tmp_path, monkeypatch):
    monkeypatch.setattr(rates, "DGS10_PATH", tmp_path / "dgs10.parquet")
    monkeypatch.setattr(rates, "_download_fred", lambda: (_ for _ in ()).throw(TimeoutError("down")))
    y = pd.Series([0.015, 0.016], index=pd.to_datetime(["2016-06-29", "2016-06-30"]), name="dgs10")
    monkeypatch.setattr(rates, "_download_yahoo", lambda: y)
    got = rates.refresh_dgs10()
    assert got.tolist() == pytest.approx([0.015, 0.016])
    assert pd.read_parquet(tmp_path / "dgs10.parquet")["source"].iloc[0] == "yahoo_tnx"


# ----------------------------------------------------------------------------------------------
# Integration on the real caches (skipped until the data layer is built)
# ----------------------------------------------------------------------------------------------
def _real_ctx():
    from quant import settings

    need = [settings.FUND_DIR / "snapshots.parquet", settings.PRICE_DIR / "close.parquet",
            settings.UNIV_DIR / "membership.parquet", settings.SEC_DIR / "companies.parquet"]
    if not all(p.exists() for p in need):
        pytest.skip("data layer caches not built yet")
    from quant.data.context import get_context

    return get_context()


def test_real_data_smoke():
    ctx = _real_ctx()
    date = ctx.month_ends("2016-06-01", "2016-06-30")[-1]
    univ = ctx.universe(date, "SP1500")
    t0 = time.time()
    out = km.key_metrics_table(ctx, date, univ)
    elapsed = time.time() - t0
    assert len(out) > 500
    assert set(REQUIRED) <= set(out.columns)
    assert out["pass_all"].dtype == bool
    assert out["nd_label"].isin(["net cash", "low", "ok", "high", "n/a"]).all()
    assert (out["pass_all"] == (out["pass_leverage"] & out["quality_ok"] & out["pass_roic"])).all()
    assert elapsed < 30
