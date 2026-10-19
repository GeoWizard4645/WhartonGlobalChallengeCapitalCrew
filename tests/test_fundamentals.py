"""Tests for quant/data/fundamentals.py.

Two groups:
  * synthetic: tiny hand-built facts frames -> ``snapshots_from_facts`` (no cache needed, milliseconds)
  * real cache: research test vectors (research/02 s6.3, research/03 s5.2), skipped if the SEC cache is missing
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.data import fundamentals as F
from quant.data import sec

NAN = float("nan")


# ----------------------------------------------------------------------------------------
# real cache availability (used by the tests below)
# ----------------------------------------------------------------------------------------
REAL = all(sec._part_path(p).exists() for p in range(sec.N_PARTS)) and sec.COMPANIES_PATH.exists()
needs_cache = pytest.mark.skipif(not REAL, reason="SEC cache not built (run python -m quant.data.sec)")

CIKS = dict(AAPL=320193, MSFT=789019, WMT=104169, NVDA=1045810, COST=909832, F=37996, XOM_NEW=2115436, XOM_OLD=34088,
            GOOGL=1652044)


@pytest.fixture(scope="module")
def real(tmp_path_factory):
    out = tmp_path_factory.mktemp("fund") / "subset.parquet"
    F.build_snapshots(ciks=list(CIKS.values()), n_jobs=1, out_path=out)
    return F.load_snapshots(path=out)



# ----------------------------------------------------------------------------------------
# fact builder
# ----------------------------------------------------------------------------------------
class Facts:
    """Collects SEC-style fact rows for one or more companies."""

    def __init__(self):
        self.rows = []
        self._n = 0

    def add(self, cik, tag, end, val, filed, accn, form="10-K", start=None):
        self.rows.append(dict(cik=cik, tag=tag, unit=F.TAG_UNIT.get(tag, "USD"), start=start, end=end, val=float(val),
                              filed=filed, form=form, accn=accn))

    def filing(self, cik, accn, filed, form, pe, inst=(), flows=(), extra_inst=(), dei=()):
        """inst: [(tag, value)] at `pe`; extra_inst: [(tag, end, value)] comparatives;
        flows: [(tag, start, end, value)]; dei: [(end, value)]."""
        for tag, v in inst:
            self.add(cik, tag, pe, v, filed, accn, form)
        for tag, end, v in extra_inst:
            self.add(cik, tag, end, v, filed, accn, form)
        for tag, st, en, v in flows:
            self.add(cik, tag, en, v, filed, accn, form, start=st)
        for en, v in dei:
            self.add(cik, F.DEI_TAG, en, v, filed, accn, form)

    def frame(self) -> pd.DataFrame:
        return pd.DataFrame(self.rows)


def snaps(facts: Facts, **kw) -> pd.DataFrame:
    return F.snapshots_from_facts(facts.frame(), **kw)


def row(df: pd.DataFrame, filed: str, cik=None) -> pd.Series:
    m = df["filed"] == pd.Timestamp(filed)
    if cik is not None:
        m &= df["cik"] == cik
    assert m.sum() == 1, f"expected exactly one snapshot filed {filed}, got {m.sum()}"
    return df[m].iloc[0]


def flagset(r) -> set[str]:
    return set(filter(None, r["flags"].split(";")))


# ----------------------------------------------------------------------------------------
# company A: Dec fiscal year, restated comparative in 2022
# ----------------------------------------------------------------------------------------
def company_a() -> Facts:
    f = Facts()
    c = 1
    R, NI, OP, CG = "Revenues", "NetIncomeLoss", "OperatingIncomeLoss", "CostOfRevenue"
    # FY2020 10-K
    f.filing(c, "A-K20", "2021-02-26", "10-K", "2020-12-31",
             inst=[("Assets", 1000), ("AssetsCurrent", 400)], extra_inst=[("Assets", "2019-12-31", 900)],
             flows=[(R, "2020-01-01", "2020-12-31", 400), (R, "2019-01-01", "2019-12-31", 360),
                    (NI, "2020-01-01", "2020-12-31", 40), (OP, "2020-01-01", "2020-12-31", 60),
                    (CG, "2020-01-01", "2020-12-31", 250)])
    # Q1 2021
    f.filing(c, "A-Q121", "2021-05-05", "10-Q", "2021-03-31",
             inst=[("Assets", 1020)], extra_inst=[("Assets", "2020-12-31", 1000)],
             flows=[(R, "2021-01-01", "2021-03-31", 110), (R, "2020-01-01", "2020-03-31", 90),
                    (NI, "2021-01-01", "2021-03-31", 12), (NI, "2020-01-01", "2020-03-31", 9),
                    (OP, "2021-01-01", "2021-03-31", 18), (OP, "2020-01-01", "2020-03-31", 12)])
    # Q2 2021 (3M and 6M YTD, with prior-year comparatives)
    f.filing(c, "A-Q221", "2021-08-05", "10-Q", "2021-06-30",
             inst=[("Assets", 1050)],
             flows=[(R, "2021-04-01", "2021-06-30", 120), (R, "2021-01-01", "2021-06-30", 230),
                    (R, "2020-04-01", "2020-06-30", 90), (R, "2020-01-01", "2020-06-30", 180),
                    (NI, "2021-04-01", "2021-06-30", 14), (NI, "2021-01-01", "2021-06-30", 26),
                    (NI, "2020-04-01", "2020-06-30", 10), (NI, "2020-01-01", "2020-06-30", 19),
                    (OP, "2021-04-01", "2021-06-30", 20), (OP, "2021-01-01", "2021-06-30", 38),
                    (OP, "2020-04-01", "2020-06-30", 14), (OP, "2020-01-01", "2020-06-30", 26)])
    # Q3 2021
    f.filing(c, "A-Q321", "2021-11-04", "10-Q", "2021-09-30",
             inst=[("Assets", 1080)],
             flows=[(R, "2021-07-01", "2021-09-30", 125), (R, "2021-01-01", "2021-09-30", 355),
                    (R, "2020-07-01", "2020-09-30", 100), (R, "2020-01-01", "2020-09-30", 280),
                    (NI, "2021-07-01", "2021-09-30", 15), (NI, "2021-01-01", "2021-09-30", 41),
                    (NI, "2020-01-01", "2020-09-30", 30)])
    # FY2021 10-K: FY2020 comparative RESTATED 400 -> 380
    f.filing(c, "A-K21", "2022-02-25", "10-K", "2021-12-31",
             inst=[("Assets", 1100)], extra_inst=[("Assets", "2020-12-31", 1000)],
             flows=[(R, "2021-01-01", "2021-12-31", 480), (R, "2020-01-01", "2020-12-31", 380),
                    (NI, "2021-01-01", "2021-12-31", 58), (NI, "2020-01-01", "2020-12-31", 40),
                    (OP, "2021-01-01", "2021-12-31", 80), (OP, "2020-01-01", "2020-12-31", 60)])
    # Q1 2022: Q1 2021 comparative RESTATED 110 -> 100
    f.filing(c, "A-Q122", "2022-05-05", "10-Q", "2022-03-31",
             inst=[("Assets", 1120)],
             flows=[(R, "2022-01-01", "2022-03-31", 130), (R, "2021-01-01", "2021-03-31", 100),
                    (NI, "2022-01-01", "2022-03-31", 16), (NI, "2021-01-01", "2021-03-31", 12)])
    return f


@pytest.fixture(scope="module")
def sa():
    return snaps(company_a())


def test_one_row_per_filing_and_schema(sa):
    assert list(sa.columns) == F.COLUMNS
    assert len(sa) == 6
    assert sa["filed"].is_monotonic_increasing and not sa.duplicated(["cik", "filed"]).any()
    # ARCHITECTURE.md snapshot schema
    needed = ("cik accn form filed period_end fiscal_period fy_end_date ttm_method flags revenue cogs gross_profit sga "
              "opinc pretax interest_exp tax net_income net_income_incl_nci da cfo capex acquisitions ebitda eps_diluted "
              "revenue_lfy opinc_lfy net_income_lfy da_lfy ebitda_lfy cfo_lfy capex_lfy assets current_assets "
              "current_liabilities cash st_investments ppe_net goodwill intangibles liabilities equity_parent equity_total "
              "preferred minority_interest debt_current debt_noncurrent total_debt finance_lease op_lease_current "
              "op_lease_noncurrent retained_earnings shares_out shares_out_date shares_diluted shares_basic assets_4q "
              "total_debt_4q equity_total_4q cash_4q shares_diluted_4q opinc_ttm_4q revenue_ttm_4q evol").split()
    needed += [f"{c}_fy{i}" for c in ("revenue", "opinc", "cfo", "capex", "net_income") for i in range(1, 6)]
    needed += [f"fyend_fy{i}" for i in range(1, 6)]
    assert set(needed) == set(sa.columns)
    assert sa["cik"].dtype == np.int64 and str(sa["filed"].dtype) == "datetime64[ns]"
    assert all(str(sa[c].dtype) == "float64" for c in ("revenue", "total_debt", "evol", "shares_out"))


def test_ttm_formula_ytd_and_fy(sa):
    # FY snapshot: the annual fact
    r = row(sa, "2021-02-26")
    assert (r["revenue"], r["ttm_method"], r["fiscal_period"]) == (400, "FY", "FY")
    assert r["fy_end_date"] == pd.Timestamp("2020-12-31") and r["period_end"] == pd.Timestamp("2020-12-31")
    # TTM = FY_prev + YTD_cur - YTD_prior_year
    for filed, fp, want in (("2021-05-05", "Q1", 400 + 110 - 90), ("2021-08-05", "Q2", 400 + 230 - 180),
                            ("2021-11-04", "Q3", 400 + 355 - 280)):
        r = row(sa, filed)
        assert r["revenue"] == want, filed
        assert r["ttm_method"] == "YTD" and r["fiscal_period"] == fp
    r = row(sa, "2021-08-05")
    assert r["net_income"] == 40 + 26 - 19
    assert r["opinc"] == 60 + 38 - 26
    assert r["period_end"] == pd.Timestamp("2021-06-30") and r["fy_end_date"] == pd.Timestamp("2020-12-31")
    # gross profit derived from revenue - cogs only where cogs exists (FY2020 10-K)
    r = row(sa, "2021-02-26")
    assert r["cogs"] == 250 and r["gross_profit"] == 150 and "gp_derived" in flagset(r)


def test_history_columns(sa):
    r = row(sa, "2022-05-05")
    assert r["assets_4q"] == 1020                      # balance sheet ~1 year before period_end (2021-03-31)
    assert r["revenue_fy1"] == 480 and r["revenue_fy2"] == 380 and r["revenue_lfy"] == 480
    assert r["fyend_fy1"] == pd.Timestamp("2021-12-31") and r["fyend_fy2"] == pd.Timestamp("2020-12-31")
    assert r["revenue_fy3"] == 360 and r["fyend_fy3"] == pd.Timestamp("2019-12-31")   # comparative column of the FY2020 10-K
    assert np.isnan(r["revenue_fy4"]) and pd.isna(r["fyend_fy4"])


def test_restatement_later_snapshot_uses_restated_earlier_keeps_original(sa):
    # earlier snapshots never see the restated FY2020 (380): they keep 400
    assert row(sa, "2021-05-05")["revenue_fy1"] == 400
    assert row(sa, "2021-11-04")["revenue_fy1"] == 400
    # the FY2021 10-K restates FY2020: revenue_fy2 = 380 from then on
    r = row(sa, "2022-02-25")
    assert r["revenue"] == 480 and r["revenue_fy2"] == 380
    # Q1 2022 TTM = FY2021 + Q1'22 - Q1'21 where the Q1'21 comparative was restated to 100 in that same filing
    r = row(sa, "2022-05-05")
    assert r["revenue"] == 480 + 130 - 100
    # ... while the original Q1 2021 snapshot still reflects the original numbers
    assert row(sa, "2021-05-05")["revenue"] == 400 + 110 - 90


def test_first_filed_variant_ignores_restatements():
    s_first = snaps(company_a(), first_filed=True)
    assert row(s_first, "2022-05-05")["revenue"] == 480 + 130 - 110       # original Q1'21 comparative
    assert row(s_first, "2022-02-25")["revenue_fy2"] == 400               # original FY2020
    # unaffected snapshots are identical
    assert row(s_first, "2021-08-05")["revenue"] == 450


# ----------------------------------------------------------------------------------------
# stale tag rule
# ----------------------------------------------------------------------------------------
def test_stale_gross_profit_tag_not_used():
    f = Facts()
    c = 2
    # FY2019 10-K still has GrossProfit
    f.filing(c, "B-K19", "2020-03-01", "10-K", "2019-12-31", inst=[("Assets", 500)],
             flows=[("Revenues", "2019-01-01", "2019-12-31", 300), ("CostOfRevenue", "2019-01-01", "2019-12-31", 200),
                    ("GrossProfit", "2019-01-01", "2019-12-31", 100), ("NetIncomeLoss", "2019-01-01", "2019-12-31", 20)])
    # 10-Q 2020 Q1: no GrossProfit any more
    f.filing(c, "B-Q120", "2020-05-05", "10-Q", "2020-03-31", inst=[("Assets", 510)],
             flows=[("Revenues", "2020-01-01", "2020-03-31", 80), ("Revenues", "2019-01-01", "2019-03-31", 70),
                    ("CostOfRevenue", "2020-01-01", "2020-03-31", 54), ("CostOfRevenue", "2019-01-01", "2019-03-31", 48),
                    ("NetIncomeLoss", "2020-01-01", "2020-03-31", 6), ("NetIncomeLoss", "2019-01-01", "2019-03-31", 5)])
    # FY2020 10-K: revenue 330, cogs 215, GrossProfit tag stale (not reported)
    f.filing(c, "B-K20", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 520)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 330), ("Revenues", "2019-01-01", "2019-12-31", 300),
                    ("CostOfRevenue", "2020-01-01", "2020-12-31", 215), ("CostOfRevenue", "2019-01-01", "2019-12-31", 200),
                    ("NetIncomeLoss", "2020-01-01", "2020-12-31", 25)])
    s = snaps(f)
    r19 = row(s, "2020-03-01")
    assert r19["gross_profit"] == 100 and "gp_derived" not in flagset(r19)
    # Q1 2020: stale GrossProfit must NOT be combined into a TTM: GP = revenue_ttm - cogs_ttm
    r = row(s, "2020-05-05")
    assert r["revenue"] == 300 + 80 - 70 and r["cogs"] == 200 + 54 - 48
    assert r["gross_profit"] == r["revenue"] - r["cogs"] == 104 and "gp_derived" in flagset(r)
    r = row(s, "2021-03-01")
    assert r["gross_profit"] == 115 and "gp_derived" in flagset(r)


def test_revenue_picks_largest_not_subline_and_priority_within_tolerance():
    f = Facts()
    # ETN-style: Revenues tag is a zero / sub-line, SalesRevenueNet is the total
    f.filing(3, "C-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 0), ("SalesRevenueNet", "2020-01-01", "2020-12-31", 22.0)])
    # WMT-style: ASC606 net sales vs total revenues (+1%): the higher-priority ASC606 tag wins within 3%
    f.filing(4, "D-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100)],
             flows=[("RevenueFromContractWithCustomerExcludingAssessedTax", "2020-01-01", "2020-12-31", 100.0),
                    ("Revenues", "2020-01-01", "2020-12-31", 101.0)])
    # PG-style: `Revenues` is a sub-line far below the ASC606 total
    f.filing(5, "E-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100)],
             flows=[("RevenueFromContractWithCustomerExcludingAssessedTax", "2020-01-01", "2020-12-31", 83.0),
                    ("Revenues", "2020-01-01", "2020-12-31", 29.0)])
    s = snaps(f)
    assert row(s, "2021-03-01", 3)["revenue"] == 22.0
    assert row(s, "2021-03-01", 4)["revenue"] == 100.0
    assert row(s, "2021-03-01", 5)["revenue"] == 83.0


def test_tag_migration_per_period_mixed_tags_flag():
    f = Facts()
    c = 6
    f.filing(c, "M-K17", "2018-03-01", "10-K", "2017-12-31", inst=[("Assets", 100)],
             flows=[("SalesRevenueNet", "2017-01-01", "2017-12-31", 200.0)])
    f.filing(c, "M-Q118", "2018-05-04", "10-Q", "2018-03-31", inst=[("Assets", 101)],
             flows=[("RevenueFromContractWithCustomerExcludingAssessedTax", "2018-01-01", "2018-03-31", 55.0),
                    ("RevenueFromContractWithCustomerExcludingAssessedTax", "2017-01-01", "2017-03-31", 50.0)])
    s = snaps(f)
    r = row(s, "2018-05-04")
    assert r["revenue"] == 200 + 55 - 50
    assert {"mixed_tags", "mix_revenue"} <= flagset(r)


# ----------------------------------------------------------------------------------------
# calendar quirks: start jitter, 16-week quarter, 10-K/A anchor
# ----------------------------------------------------------------------------------------
def test_start_date_jitter_and_16_week_quarter():
    f = Facts()
    c = 7
    # FY2020 ended 2021-01-30 (52 weeks); Q1 FY21 = 16 weeks (112 days) ending 2021-05-22
    f.filing(c, "K-K20", "2021-03-31", "10-K", "2021-01-30", inst=[("Assets", 100)],
             flows=[("Revenues", "2020-02-02", "2021-01-30", 1000.0), ("NetIncomeLoss", "2020-02-02", "2021-01-30", 50.0)])
    f.filing(c, "K-Q121", "2021-06-24", "10-Q", "2021-05-22", inst=[("Assets", 105)],
             flows=[("Revenues", "2021-01-31", "2021-05-22", 400.0),
                    ("Revenues", "2020-02-03", "2020-05-23", 380.0),            # prior-year start jittered by +1 day
                    ("NetIncomeLoss", "2021-01-31", "2021-05-22", 20.0), ("NetIncomeLoss", "2020-02-02", "2020-05-23", 15.0)])
    s = snaps(f)
    r = row(s, "2021-06-24")
    assert r["fiscal_period"] == "Q1" and r["ttm_method"] == "YTD"
    assert r["revenue"] == 1000 + 400 - 380 and r["net_income"] == 50 + 20 - 15


def test_amendment_of_old_period_does_not_regress_period_end():
    f = company_a()
    # 10-K/A for FY2020 filed after the Q1 2022 10-Q, restating nothing but carrying the full 2020 statements
    f.filing(1, "A-K20A", "2022-06-15", "10-K/A", "2020-12-31", inst=[("Assets", 1000)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 379.0), ("NetIncomeLoss", "2020-01-01", "2020-12-31", 40.0)])
    s = snaps(f)
    r = row(s, "2022-06-15")
    assert r["form"] == "10-K/A"
    assert r["period_end"] == pd.Timestamp("2022-03-31")       # newest balance sheet known, not 2020-12-31
    assert "amend_anchor" in flagset(r)
    assert r["revenue_fy2"] == 379                              # the amendment's value is now the latest vintage
    assert (s["period_end"].diff().dropna() >= pd.Timedelta(0)).all()


# ----------------------------------------------------------------------------------------
# debt
# ----------------------------------------------------------------------------------------
def one_bs(inst, extra_flows=(), cik=10, assets=1000.0, prior=None):
    """FY snapshot with a given balance sheet; returns the single row."""
    f = Facts()
    if prior:
        f.filing(cik, "P-K", "2020-03-01", "10-K", "2019-12-31", inst=[("Assets", assets)] + list(prior),
                 flows=[("Revenues", "2019-01-01", "2019-12-31", 500.0), ("NetIncomeLoss", "2019-01-01", "2019-12-31", 10.0)])
    f.filing(cik, "D-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", assets)] + list(inst),
             flows=[("Revenues", "2020-01-01", "2020-12-31", 500.0), ("NetIncomeLoss", "2020-01-01", "2020-12-31", 10.0)]
             + list(extra_flows))
    return snaps(f).iloc[-1]


def test_debt_apple_pattern_no_double_count():
    # Apple 2026-06-27: LongTermDebt (incl. current) + CommercialPaper; LongTermDebtCurrent / Noncurrent shown separately
    r = one_bs([("LongTermDebt", 82300), ("LongTermDebtNoncurrent", 71340), ("LongTermDebtCurrent", 11007),
                ("CommercialPaper", 1997)])
    assert r["total_debt"] == 82300 + 1997                      # NOT + LongTermDebtCurrent / DebtCurrent
    assert r["debt_noncurrent"] == 71340 and r["debt_current"] == 82300 + 1997 - 71340


def test_debt_debtcurrent_plus_noncurrent_includes_ltd_current_once():
    r = one_bs([("DebtCurrent", 5000), ("LongTermDebtCurrent", 3000), ("LongTermDebtNoncurrent", 20000)])
    assert r["total_debt"] == 25000
    assert r["debt_current"] == 5000 and r["debt_noncurrent"] == 20000
    # without DebtCurrent: current = LongTermDebtCurrent + short-term borrowings + commercial paper
    r = one_bs([("LongTermDebtCurrent", 3000), ("ShortTermBorrowings", 400), ("CommercialPaper", 100),
                ("LongTermDebtNoncurrent", 20000)])
    assert r["total_debt"] == 20000 + 3000 + 400 + 100


def test_debt_finance_lease_added_operating_lease_excluded():
    r = one_bs([("DebtCurrent", 5000), ("LongTermDebtCurrent", 3000), ("LongTermDebtNoncurrent", 20000),
                ("FinanceLeaseLiability", 2000), ("OperatingLeaseLiabilityCurrent", 500),
                ("OperatingLeaseLiabilityNoncurrent", 4500)])
    assert r["total_debt"] == 27000 and r["finance_lease"] == 2000
    assert r["op_lease_current"] == 500 and r["op_lease_noncurrent"] == 4500
    # combined debt+lease tag already contains finance leases: do not add them twice
    r = one_bs([("LongTermDebtAndCapitalLeaseObligations", 18000), ("FinanceLeaseLiability", 1000)])
    assert r["total_debt"] == 18000


def test_debt_commercial_paper_nested_in_short_term_borrowings_uses_combined_tag():
    # Linde pattern: ShortTermBorrowings already contains CommercialPaper; the combined tag settles it
    r = one_bs([("LongTermDebt", 23152), ("ShortTermBorrowings", 4861), ("CommercialPaper", 4531),
                ("DebtLongtermAndShorttermCombinedAmount", 28013)])
    assert r["total_debt"] == 28013
    # no evidence -> default: the two are separate lines
    r = one_bs([("LongTermDebt", 1000), ("ShortTermBorrowings", 200), ("CommercialPaper", 100)])
    assert r["total_debt"] == 1300


def test_debt_longtermdebt_excluding_current_detected():
    # TSLA pattern: LongTermDebt is the non-current part; the instrument total settles it
    r = one_bs([("LongTermDebt", 7721), ("DebtCurrent", 1340), ("DebtInstrumentCarryingAmount", 9080)])
    assert r["total_debt"] == 7721 + 1340 and "ltd_excl_current" in flagset(r)


def test_debt_missing_is_nan_except_explicit_zero_rule():
    # no debt tag, no interest evidence, big company -> NaN (not 0)
    r = one_bs([], assets=5e9)
    assert np.isnan(r["total_debt"]) and "debt_zero_inferred" not in flagset(r)
    # no debt tag + interest expense reported ~0 -> 0, flagged
    r = one_bs([], extra_flows=[("InterestExpense", "2020-01-01", "2020-12-31", 0.0)], assets=5e9)
    assert r["total_debt"] == 0 and "debt_zero_inferred" in flagset(r)
    # no debt tag but real interest expense -> NaN
    r = one_bs([], extra_flows=[("InterestExpense", "2020-01-01", "2020-12-31", 40.0)], assets=1000.0)
    assert np.isnan(r["total_debt"])
    # no debt tag, no interest tag, tiny filer -> 0 flagged
    r = one_bs([], assets=1e6)
    assert r["total_debt"] == 0 and "debt_zero_inferred" in flagset(r)
    # income-statement bridge: true operating income well above pretax income => interest burden => NaN
    r = one_bs([], extra_flows=[("OperatingIncomeLoss", "2020-01-01", "2020-12-31", 100.0),
                               ("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                                "2020-01-01", "2020-12-31", 60.0)], assets=1000.0)
    assert np.isnan(r["total_debt"])


def test_debt_noncurrent_missing_in_a_later_filing_is_nan_not_understated():
    f = Facts()
    f.filing(11, "O-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 1000), ("LongTermDebtNoncurrent", 100),
                                                                 ("DebtCurrent", 10)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 500.0), ("NetIncomeLoss", "2020-01-01", "2020-12-31", 10.0)])
    f.filing(11, "O-Q1", "2021-05-05", "10-Q", "2021-03-31", inst=[("Assets", 1010), ("NotesPayableCurrent", 8)],
             flows=[("Revenues", "2021-01-01", "2021-03-31", 120.0), ("NetIncomeLoss", "2021-01-01", "2021-03-31", 3.0)])
    s = snaps(f)
    assert row(s, "2021-03-01")["total_debt"] == 110
    r = row(s, "2021-05-05")
    assert np.isnan(r["total_debt"]) and "debt_nc_missing" in flagset(r)


# ----------------------------------------------------------------------------------------
# balance-sheet items
# ----------------------------------------------------------------------------------------
def test_cash_sti_equity_items():
    r = one_bs([("CashAndCashEquivalentsAtCarryingValue", 50), ("ShortTermInvestments", 20), ("MarketableSecuritiesCurrent", 5),
                ("AvailableForSaleSecuritiesDebtSecuritiesCurrent", 999), ("StockholdersEquity", 400),
                ("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", 430),
                ("AssetsCurrent", 300), ("LiabilitiesCurrent", 200), ("Liabilities", 570)])
    assert r["cash"] == 50 and r["st_investments"] == 25            # AFS only if neither STI tag exists
    assert r["equity_parent"] == 400 and r["equity_total"] == 430 and r["minority_interest"] == 30
    assert r["current_assets"] == 300 and r["current_liabilities"] == 200 and r["liabilities"] == 570
    r = one_bs([("CashAndCashEquivalentsAtCarryingValue", 50), ("AvailableForSaleSecuritiesDebtSecuritiesCurrent", 70)])
    assert r["st_investments"] == 70


def test_goodwill_and_leases_carried_forward_from_10k():
    f = Facts()
    f.filing(12, "G-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100), ("Goodwill", 40),
                                                                 ("OperatingLeaseLiabilityNoncurrent", 9)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 50.0), ("NetIncomeLoss", "2020-01-01", "2020-12-31", 5.0)])
    f.filing(12, "G-Q1", "2021-05-05", "10-Q", "2021-03-31", inst=[("Assets", 101)],
             flows=[("Revenues", "2021-01-01", "2021-03-31", 13.0), ("Revenues", "2020-01-01", "2020-03-31", 12.0),
                    ("NetIncomeLoss", "2021-01-01", "2021-03-31", 1.0), ("NetIncomeLoss", "2020-01-01", "2020-03-31", 1.0)])
    r = row(snaps(f), "2021-05-05")
    assert r["goodwill"] == 40 and r["op_lease_noncurrent"] == 9 and "carry_fwd" in flagset(r)


# ----------------------------------------------------------------------------------------
# shares
# ----------------------------------------------------------------------------------------
def shares_company(cik=20):
    f = Facts()
    for i, (filed, pe, n) in enumerate([("2020-03-01", "2019-12-31", 100.0), ("2020-05-05", "2020-03-31", 101.0),
                                        ("2020-08-05", "2020-06-30", 102.0), ("2020-11-05", "2020-09-30", 103.0)]):
        form = "10-K" if i == 0 else "10-Q"
        if form == "10-K":
            flows = [("Revenues", "2019-01-01", "2019-12-31", 100.0), ("NetIncomeLoss", "2019-01-01", "2019-12-31", 5.0)]
        else:
            qs = pd.Timestamp(pe) - pd.offsets.MonthBegin(3)
            flows = [("Revenues", qs.strftime("%Y-%m-%d"), pe, 25.0), ("NetIncomeLoss", qs.strftime("%Y-%m-%d"), pe, 1.0),
                     ("WeightedAverageNumberOfDilutedSharesOutstanding", qs.strftime("%Y-%m-%d"), pe, n * 1e6)]
        f.filing(cik, f"S{i}", filed, form, pe, inst=[("Assets", 200.0)], flows=flows,
                 dei=[(pd.Timestamp(filed) - pd.Timedelta(days=10), n * 1e6)])
    return f


def test_shares_out_cover_page_and_dates():
    s = snaps(shares_company())
    r = row(s, "2020-05-05")
    assert r["shares_out"] == 101e6 and r["shares_out_date"] == pd.Timestamp("2020-04-25")
    assert r["shares_diluted"] == 101e6


def test_shares_multi_class_sum_flag():
    f = shares_company()
    f.add(20, F.DEI_TAG, "2020-07-26", 40e6, "2020-08-05", "S2", "10-Q")         # a second class, same cover date
    r = row(snaps(f), "2020-08-05")
    assert r["shares_out"] == 102e6 + 40e6 and "multi_class_sum" in flagset(r)


def test_shares_scale_error_dropped_and_stale_fallback():
    f = shares_company()
    # replace the Q3 cover count by a x1000 scale error (PKG / ORCL pattern)
    f.rows = [x for x in f.rows if not (x["tag"] == F.DEI_TAG and x["accn"] == "S3")]
    f.add(20, F.DEI_TAG, "2020-10-26", 103e9, "2020-11-05", "S3", "10-Q")
    r = row(snaps(f), "2020-11-05")
    assert "shares_scale_dropped" in flagset(r)
    assert r["shares_out"] == 102e6 and "shares_stale" in flagset(r)             # last sane cover count


def test_shares_genuine_split_kept_when_diluted_supports_it():
    f = shares_company()
    f.rows = [x for x in f.rows if not (x["accn"] == "S3" and x["tag"] in (F.DEI_TAG, "WeightedAverageNumberOfDilutedSharesOutstanding"))]
    f.add(20, F.DEI_TAG, "2020-10-26", 103e6 * 10, "2020-11-05", "S3", "10-Q")                    # 10-for-1 split
    f.add(20, "WeightedAverageNumberOfDilutedSharesOutstanding", "2020-09-30", 103e6 * 10, "2020-11-05", "S3", "10-Q",
          start="2020-07-01")
    r = row(snaps(f), "2020-11-05")
    assert r["shares_out"] == 1030e6 and "shares_scale_dropped" not in flagset(r)


def test_shares_balance_sheet_fallback_when_no_cover_page():
    f = Facts()
    f.filing(21, "BS-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100), ("CommonStockSharesOutstanding", 12.088e9)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 50.0), ("NetIncomeLoss", "2020-01-01", "2020-12-31", 5.0)])
    r = snaps(f).iloc[0]
    assert r["shares_out"] == 12.088e9 and r["shares_out_date"] == pd.Timestamp("2020-12-31") and "shares_bs" in flagset(r)


# ----------------------------------------------------------------------------------------
# EBIT fallback, EBITDA, discrete quarters, evol
# ----------------------------------------------------------------------------------------
def test_ebit_proxy_and_ebitda():
    f = Facts()
    pt = "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest"
    f.filing(30, "E-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 500.0), (pt, "2020-01-01", "2020-12-31", 80.0),
                    ("InterestExpense", "2020-01-01", "2020-12-31", 20.0), ("DepreciationDepletionAndAmortization",
                                                                            "2020-01-01", "2020-12-31", 15.0)])
    r = snaps(f).iloc[0]
    assert r["opinc"] == 100 and "ebit_proxy" in flagset(r)
    assert r["ebitda"] == 115 and r["da"] == 15 and r["pretax"] == 80 and r["interest_exp"] == 20
    # true OperatingIncomeLoss wins and no flag
    f.filing(31, "E-K2", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 500.0), ("OperatingIncomeLoss", "2020-01-01", "2020-12-31", 90.0)])
    r = row(snaps(f), "2021-03-01", 31)
    assert r["opinc"] == 90 and "ebit_proxy" not in flagset(r) and np.isnan(r["ebitda"])


def test_da_depreciation_plus_amortization_and_cfo_ytd_ttm():
    f = Facts()
    c = 32
    f.filing(c, "C-K", "2021-03-01", "10-K", "2020-12-31", inst=[("Assets", 100)],
             flows=[("Revenues", "2020-01-01", "2020-12-31", 500.0), ("Depreciation", "2020-01-01", "2020-12-31", 10.0),
                    ("AmortizationOfIntangibleAssets", "2020-01-01", "2020-12-31", 4.0),
                    ("NetCashProvidedByUsedInOperatingActivities", "2020-01-01", "2020-12-31", 70.0),
                    ("PaymentsToAcquirePropertyPlantAndEquipment", "2020-01-01", "2020-12-31", 20.0)])
    f.filing(c, "C-Q2", "2021-08-05", "10-Q", "2021-06-30", inst=[("Assets", 101)],
             flows=[("Revenues", "2021-01-01", "2021-06-30", 260.0), ("Revenues", "2020-01-01", "2020-06-30", 240.0),
                    ("NetCashProvidedByUsedInOperatingActivities", "2021-01-01", "2021-06-30", 40.0),
                    ("NetCashProvidedByUsedInOperatingActivities", "2020-01-01", "2020-06-30", 30.0),
                    ("PaymentsToAcquirePropertyPlantAndEquipment", "2021-01-01", "2021-06-30", 12.0),
                    ("PaymentsToAcquirePropertyPlantAndEquipment", "2020-01-01", "2020-06-30", 8.0)])
    s = snaps(f)
    assert row(s, "2021-03-01")["da"] == 14
    r = row(s, "2021-08-05")
    assert r["cfo"] == 70 + 40 - 30 and r["capex"] == 20 + 12 - 8
    assert np.isnan(r["da"])                                  # no D&A facts in the 10-Q: not stitched from a stale period


def test_evol_and_discrete_q4_derivation():
    f = Facts()
    c = 40
    rng = np.random.default_rng(0)
    ni = rng.normal(10, 3, size=20)
    assets = 1000 + 10 * np.arange(20)
    qi = 0
    last = None
    expected = []
    for y in range(2016, 2021):
        ytd = 0.0
        for q in range(4):
            pe = ["03-31", "06-30", "09-30", "12-31"][q]
            ytd += ni[qi]
            expected.append(ni[qi] / assets[qi])
            if q < 3:
                start = f"{y}-01-01"
                qs = ["01-01", "04-01", "07-01"][q]
                flows = [("NetIncomeLoss", f"{y}-{qs}", f"{y}-{pe}", ni[qi]), ("Revenues", f"{y}-{qs}", f"{y}-{pe}", 100.0)]
                if q > 0:
                    flows += [("NetIncomeLoss", start, f"{y}-{pe}", ytd), ("Revenues", start, f"{y}-{pe}", 100.0 * (q + 1))]
                f.filing(c, f"V{y}{q}", f"{y}-{['05-05', '08-05', '11-05'][q]}", "10-Q", f"{y}-{pe}",
                         inst=[("Assets", assets[qi])], flows=flows)
            else:
                f.filing(c, f"V{y}K", f"{y + 1}-02-25", "10-K", f"{y}-12-31", inst=[("Assets", assets[qi])],
                         flows=[("NetIncomeLoss", f"{y}-01-01", f"{y}-12-31", ytd), ("Revenues", f"{y}-01-01", f"{y}-12-31", 400.0)])
            qi += 1
    s = snaps(f)
    r = s.iloc[-1]
    assert r["fiscal_period"] == "FY"
    assert r["evol"] == pytest.approx(np.std(expected, ddof=1))
    # needs >= 12 quarters: the 8th snapshot only has 8 quarters of history
    assert np.isnan(s.iloc[7]["evol"])
    assert not np.isnan(s.iloc[11]["evol"])


# ----------------------------------------------------------------------------------------
# no look-ahead: a snapshot rebuilt from ONLY the facts filed <= its date is identical
# ----------------------------------------------------------------------------------------
def _same_row(a: pd.Series, b: pd.Series) -> list[str]:
    diff = []
    for col in F.COLUMNS:
        x, y = a[col], b[col]
        if pd.isna(x) and pd.isna(y):
            continue
        if pd.isna(x) != pd.isna(y):
            diff.append(col)
        elif isinstance(x, (str, pd.Timestamp)):
            if x != y:
                diff.append(col)
        elif abs(x - y) > 1e-6 * max(1.0, abs(x), abs(y)):
            diff.append(col)
    return diff


def test_snapshot_is_identical_when_future_facts_are_removed_synthetic():
    facts = company_a().frame()
    full = F.snapshots_from_facts(facts)
    for d in full["filed"]:
        trunc = F.snapshots_from_facts(facts[pd.to_datetime(facts["filed"]) <= d])
        assert _same_row(trunc[trunc["filed"] == d].iloc[0], full[full["filed"] == d].iloc[0]) == [], d
        assert len(trunc) == int((full["filed"] <= d).sum())


@needs_cache
def test_snapshot_is_identical_when_future_facts_are_removed_real(real):
    rng = np.random.default_rng(3)
    for cik in CIKS.values():
        fs = real[real["cik"] == cik]
        if len(fs) < 5:
            continue
        facts = sec.load_facts(ciks=[cik])
        for d in fs["filed"].iloc[rng.choice(len(fs), 3, replace=False)]:
            trunc = F.snapshots_from_facts(facts[facts["filed"] <= d])
            assert _same_row(trunc[trunc["filed"] == d].iloc[0], fs[fs["filed"] == d].iloc[0]) == [], (cik, d)


# ----------------------------------------------------------------------------------------
# asof
# ----------------------------------------------------------------------------------------
def test_asof_strict_no_lookahead_and_staleness(sa):
    day = pd.Timestamp("2021-08-05")                                    # Q2 2021 10-Q filed this day
    a = F.asof(sa, day)
    assert a.index.name == "cik" and list(a.index) == [1]
    assert a.loc[1, "filed"] == pd.Timestamp("2021-05-05")              # filed == date is NOT usable
    a = F.asof(sa, day + pd.Timedelta(days=1))
    assert a.loc[1, "filed"] == day and a.loc[1, "period_end"] == pd.Timestamp("2021-06-30")
    assert {"filed", "period_end", "revenue"} <= set(a.columns)
    # before the first filing: empty
    assert len(F.asof(sa, "2021-02-26")) == 0
    assert len(F.asof(sa, "2021-02-27")) == 1
    # staleness: latest period_end is 2022-03-31 -> 427 days old on 2023-06-01
    assert len(F.asof(sa, "2022-08-01")) == 1
    assert len(F.asof(sa, "2023-06-01")) == 0
    assert len(F.asof(sa, "2023-06-01", max_age_days=500)) == 1
    # boundary: period_end >= date - max_age_days is inclusive
    assert len(F.asof(sa, pd.Timestamp("2022-03-31") + pd.Timedelta(days=200))) == 1
    assert len(F.asof(sa, pd.Timestamp("2022-03-31") + pd.Timedelta(days=201))) == 0


def test_asof_multiple_companies_picks_latest_per_cik():
    s = pd.concat([snaps(company_a()), snaps(shares_company())], ignore_index=True)
    a = F.asof(s, "2021-12-31", max_age_days=10_000)
    assert sorted(a.index) == [1, 20]
    assert a.loc[1, "filed"] == pd.Timestamp("2021-11-04") and a.loc[20, "filed"] == pd.Timestamp("2020-11-05")
    # unsorted input is handled
    b = F.asof(s.sample(frac=1.0, random_state=1), "2021-12-31", max_age_days=10_000)
    assert b.loc[1, "filed"] == a.loc[1, "filed"]


# ----------------------------------------------------------------------------------------
# real cache
# ----------------------------------------------------------------------------------------
@needs_cache
def test_subset_build_does_not_touch_main_file(real):
    assert list(real.columns) == F.COLUMNS
    assert set(real["cik"]) == set(CIKS.values())


@needs_cache
@pytest.mark.parametrize("date,max_age,expected", [
    ("2026-10-20", 250, dict(AAPL=0.5926, MSFT=0.2973, WMT=0.6066, NVDA=0.7064, COST=0.4366, F=0.0541)),
    ("2024-10-20", 200, dict(AAPL=0.5345, MSFT=0.3339, WMT=0.6202, NVDA=0.8585, COST=0.4596)),
])
def test_gpa_vectors_research_02(real, date, max_age, expected):
    a = F.asof(real, date, max_age)
    for t, want in expected.items():
        r = a.loc[CIKS[t]]
        got = r["gross_profit"] / r["assets"]
        assert got == pytest.approx(want, rel=0.005), (t, got, want)


@needs_cache
def test_apple_ttm_ebit_and_debt_research_03(real):
    a = F.asof(real, "2026-10-18").loc[CIKS["AAPL"]]
    assert a["period_end"] == pd.Timestamp("2026-06-27")
    assert a["opinc"] == pytest.approx(154.859e9, rel=0.005)
    ex_lease = a["total_debt"] - (a["finance_lease"] if a["finance_lease"] == a["finance_lease"] else 0.0)
    assert ex_lease == pytest.approx(84.297e9, rel=0.005)         # LongTermDebt 82.300 + CommercialPaper 1.997
    assert a["total_debt"] >= ex_lease


@needs_cache
def test_costco_uses_revenue_minus_cogs_not_stale_gross_profit(real):
    r = F.asof(real, "2026-10-20").loc[CIKS["COST"]]
    assert "gp_derived" in set(r["flags"].split(";"))
    assert r["gross_profit"] == pytest.approx(r["revenue"] - r["cogs"])


@needs_cache
def test_both_xom_ciks_build(real):
    old = real[real["cik"] == CIKS["XOM_OLD"]]
    new = real[real["cik"] == CIKS["XOM_NEW"]]
    assert len(old) > 50 and len(new) >= 1
    assert "ebit_proxy" in set(";".join(old["flags"]).split(";"))      # XOM has no OperatingIncomeLoss


@needs_cache
def test_alphabet_shares_from_balance_sheet(real):
    r = F.asof(real, "2026-10-20").loc[CIKS["GOOGL"]]
    assert 11e9 < r["shares_out"] < 13e9 and "shares_bs" in set(r["flags"].split(";"))


@needs_cache
def test_full_table_invariants_if_built():
    if not F.SNAP_PATH.exists():
        pytest.skip("full snapshot table not built")
    s = F.load_snapshots(columns=["cik", "filed", "period_end", "ttm_method"])
    assert not s.duplicated(["cik", "filed"]).any()
    assert (s["period_end"] <= s["filed"] + pd.Timedelta(days=6)).all()
    assert set(s["ttm_method"]) <= {"FY", "YTD", "4Q", "none"}


@needs_cache
def test_build_is_idempotent_and_loader_columns(tmp_path):
    out = tmp_path / "s.parquet"
    p1 = F.build_snapshots(ciks=[CIKS["AAPL"]], n_jobs=1, out_path=out)
    assert p1 == out and out.exists()
    sub = F.load_snapshots(columns=["cik", "filed", "revenue"], path=out)
    assert list(sub.columns) == ["cik", "filed", "revenue"] and set(sub["cik"]) == {CIKS["AAPL"]}
    assert not any(tmp_path.glob("*_parts"))                         # per-partition files are cleaned up
    first = F.build_snapshots(ciks=[CIKS["AAPL"]], n_jobs=1, out_path=tmp_path / "f.parquet", first_filed=True)
    assert len(F.load_snapshots(path=first)) == len(sub)
