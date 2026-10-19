"""Tests for quant/data/universe.py.

Pure-function tests run anywhere. Tests on the built products (cache/universe/*.parquet) are skipped until
``python -m quant.data.universe build`` has been run.
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant.data import universe as U

built = pytest.mark.skipif(not U.MEMBERSHIP_PATH.exists(), reason="universe not built (run build_all)")


# ---------------------------------------------------------------------------------------------------
# pure helpers
# ---------------------------------------------------------------------------------------------------
def test_to_yf_formats_class_shares():
    assert U.to_yf("BRK.B") == "BRK-B"
    assert U.to_yf("bf.b") == "BF-B"
    assert U.to_yf(" GOOGL ") == "GOOGL"
    assert U.to_yf(None) is None


def test_clean_ticker_strips_footnotes_and_prefixes():
    assert U.clean_ticker("NYSE: MMM[1]") == "MMM"
    assert U.clean_ticker("brk.b") == "BRK.B"
    assert U.clean_ticker(float("nan")) is None


def test_noncommon_suffixes():
    for t in ["ASB-PE", "NE-WT", "PORT-UN", "ABC-RI", "XYZ-P"]:
        assert U.is_noncommon_ticker(t)
    for t in ["BRK-B", "BF-B", "UHAL-B", "CWEN-A", "AAPL"]:
        assert not U.is_noncommon_ticker(t)


def test_quarter_ends():
    q = U.quarter_ends(pd.Timestamp("2009-12-31"), pd.Timestamp("2011-06-30"))
    assert q[0] == pd.Timestamp("2009-12-31") and q[-1] == pd.Timestamp("2011-06-30")
    assert len(q) == 7


def test_gics_structure_counts_and_code_consistency():
    g = U.build_gics()
    n = g.groupby("era").size().to_dict()
    assert n == {"2008": 155, "2016": 157, "2018": 158, "2023": 163}
    assert (g["sub_industry_code"].str[:2] == g["sector_code"]).all()
    assert (g["sub_industry_code"].str[:4] == g["industry_group_code"]).all()
    assert (g["sub_industry_code"].str[:6] == g["industry_code"]).all()
    assert (g["sub_industry_code"].str.len() == 8).all()
    # exactly the documented effective dates
    assert U.gics_era_for("2016-08-31") == "2008" and U.gics_era_for("2016-09-01") == "2016"
    assert U.gics_era_for("2018-09-21") == "2016" and U.gics_era_for("2018-09-22") == "2018"
    assert U.gics_era_for("2023-03-17") == "2018" and U.gics_era_for("2023-03-18") == "2023"


def test_gics_mapper_era_dependent_hierarchy():
    gm = U.GicsMapper()
    old = gm.map_sub("Advertising", "Consumer Discretionary", "2015-01-01")
    new = gm.map_sub("Advertising", "Communication Services", "2020-01-01")
    assert (old["sector_code"], old["sub_industry_code"]) == ("25", "25401010")
    assert (new["sector_code"], new["sub_industry_code"]) == ("50", "50201010")
    reit_old = gm.map_sub("Retail REITs", "Financials", "2014-06-30")
    reit_new = gm.map_sub("Retail REITs", "Real Estate", "2020-06-30")
    assert reit_old["gics_sector"] == "Financials"
    assert reit_new["gics_sector"] == "Real Estate"
    # spelling / case / dash variants resolve
    assert gm.map_sub("multi-line insurance", "Financials", "2015-01-01")["sub_industry_code"] == "40301030"
    assert gm.map_sub("Nonexistent Thing", "Financials", "2015-01-01")["gics_flag"] == "unmapped"
    # sector only
    s = gm.map_sector("Telecommunications Services", "2012-01-01")
    assert s["sector_code"] == "50" and s["gics_sub_industry"] is None


def test_name_matching_keys():
    assert dict(U.name_keys("Bard (C.R.) Inc.")).get("F") == dict(U.name_keys("BARD C R INC /NJ/")).get("F")
    assert dict(U.name_keys("Coca-Cola Company (The)"))["F"] == dict(U.name_keys("COCA COLA CO"))["F"]
    assert dict(U.name_keys("Kraft Heinz Co"))["F"] == dict(U.name_keys("KRAFT HEINZ CO"))["F"]
    assert U.name_sim("Apple Inc.", "APPLE INC") == 1.0


def test_fja_spells_and_patch():
    h = pd.DataFrame({
        "date": pd.to_datetime(["2009-12-01", "2010-03-01", "2010-06-01"]),
        "tickers": [frozenset({"A", "B"}), frozenset({"A", "C"}), frozenset({"A", "C", "D"})],
    })
    sp = U.fja_spells(h, start=pd.Timestamp("2009-12-31"))
    got = {r.ticker_fja: (r.start, r.end) for r in sp.itertuples()}
    assert got["A"] == (pd.Timestamp("2009-12-31"), pd.NaT)
    assert got["B"][0] == pd.Timestamp("2009-12-31") and got["B"][1] == pd.Timestamp("2010-03-01")
    assert got["C"] == (pd.Timestamp("2010-03-01"), pd.NaT)
    assert got["D"][0] == pd.Timestamp("2010-06-01")
    cur = pd.DataFrame({"ticker_raw": ["A", "C", "E"], "date_added": [None, None, "2011-01-05"]})
    h2, info = U.patch_fja_with_current(h, cur, pd.Timestamp("2011-02-01"))
    assert info["adds"] == ["E"] and info["removes"] == ["D"] and info["final_equals_current"]
    assert set(h2["tickers"].iloc[-1]) == {"A", "C", "E"}


def test_parse_constituents_variants():
    html = """
    <table><tr><th>Ticker symbol</th><th>Company</th><th>GICS Sector</th></tr>
    <tr><td>MMM</td><td>3M Company</td><td>Industrials</td></tr>
    <tr><td>BRK.B</td><td>Berkshire[2]</td><td>Financials</td></tr></table>
    <table><tr><th>Date</th><th>Added Ticker</th><th>Removed Ticker</th><th>Reason</th></tr>
    <tr><td>2020-01-01</td><td>X</td><td>Y</td><td>z</td></tr></table>"""
    d = U.parse_constituents(html)
    assert list(d["ticker_raw"]) == ["MMM", "BRK.B"]
    assert d["gics_sub_industry"].isna().all() and d["name"].tolist() == ["3M Company", "Berkshire"]


# ---------------------------------------------------------------------------------------------------
# built products
# ---------------------------------------------------------------------------------------------------
@built
def test_members_recent_is_about_1500():
    m = U.members("2026-10-01")
    assert 1380 <= len(m) <= 1560, len(m)
    by = m["index"].value_counts()
    assert 480 <= by["SP500"] <= 510
    assert 380 <= by["SP400"] <= 410
    assert 560 <= by["SP600"] <= 620
    assert list(m.columns[:13]) == U.MEMBERS_COLS
    assert m["cik"].notna().mean() > 0.97
    assert m["cik"].dropna().is_unique


@built
def test_sp500_2015_about_500():
    m = U.members("2015-06-30", indexes=("SP500",))
    assert 485 <= len(m) <= 510, len(m)
    raw = U.members("2015-06-30", indexes=("SP500",), dedupe=False)
    assert 495 <= len(raw) <= 510


@built
def test_no_future_information():
    # Tesla joined the S&P 500 effective 2020-12-21; Moderna 2020-07-21; Zebra 2019-12-23
    tsla = 1318605
    before = U.members("2020-12-18", indexes=("SP500",))
    after = U.members("2020-12-21", indexes=("SP500",))
    assert tsla not in set(before["cik"].dropna().astype(int))
    assert tsla in set(after["cik"].dropna().astype(int))
    assert tsla not in set(U.members("2018-06-29")["cik"].dropna().astype(int))
    mem = U.load_membership()
    # snapshots are never dated before the information existed: wikipedia revisions precede the snapshot date
    w = mem[mem["source"] == "wikipedia"].dropna(subset=["rev_ts"])
    cur = w["snapshot_date"] >= pd.Timestamp.today().normalize() - pd.Timedelta(days=1)
    assert (w.loc[~cur, "rev_ts"] <= w.loc[~cur, "snapshot_date"] + pd.Timedelta(days=1)).mean() > 0.9
    # fallback_next rows are flagged (one-quarter look-ahead), nothing else may point to a later snapshot
    assert set(mem["snapshot_quality"].unique()) <= {"ok", "fja_exact", "derived_sp1000_minus_sp400"} | \
        {q for q in mem["snapshot_quality"].unique() if str(q).startswith("fallback_")}


@built
def test_membership_gics_codes_consistent():
    mem = U.load_membership()
    x = mem.dropna(subset=["sub_industry_code"])
    assert len(x) > 0.9 * len(mem)
    assert (x["sub_industry_code"].str[:2] == x["sector_code"]).all()
    assert (x["sub_industry_code"].str[:4] == x["industry_group_code"]).all()
    assert (x["sub_industry_code"].str[:6] == x["industry_code"]).all()
    # sector-only rows (early pages) still carry a sector code
    y = mem[mem["sub_industry_code"].isna() & mem["gics_sector"].notna()]
    assert (y["sector_code"].str.len() == 2).all()
    # every label that appears maps to a gics.parquet row of the same era
    g = U.load_gics()
    keyset = set(zip(g["era"], g["sub_industry_code"]))
    assert all((e, c) in keyset for e, c in zip(x["gics_era"], x["sub_industry_code"]))


@built
def test_gics_point_in_time_reclassifications():
    ms = {d: U.members(d) for d in ["2015-06-30", "2017-06-30", "2020-06-30", "2024-06-28"]}

    def sector(cik, d):
        r = ms[d][ms[d]["cik"] == cik]
        return None if r.empty else r["gics_sector"].iloc[0]

    visa, alphabet, spg = 1403161, 1652044, 1063761
    assert sector(visa, "2015-06-30") == "Information Technology"
    assert sector(visa, "2024-06-28") == "Financials"
    r = ms["2015-06-30"]
    assert sector(spg, "2015-06-30") == "Financials"          # before Real Estate became a sector (2016-09)
    assert sector(spg, "2017-06-30") == "Real Estate"
    goog = r[r["cik"].isin([alphabet, 1288776])]
    assert not goog.empty and goog["gics_sector"].iloc[0] == "Information Technology"
    g20 = ms["2020-06-30"]
    assert g20[g20["cik"].isin([alphabet])]["gics_sector"].iloc[0] == "Communication Services"
    assert g20[g20["cik"].isin([alphabet])]["sector_code"].iloc[0] == "50"


@built
def test_yf_ticker_formatting_and_ticker_reuse_guard():
    mem = U.load_membership()
    y = mem["yf_ticker"].dropna()
    assert (y == y.str.upper()).all()
    assert not y.str.contains(r"[.\s/]").any()
    m = U.members("2015-06-30")
    assert "BRK-B" in set(m["yf_ticker"]) or "BRK-A" in set(m["yf_ticker"])
    # renamed ticker recovered through the CIK: Facebook (FB then) -> META
    fb = m[m["cik"] == 1326801]
    assert len(fb) == 1 and fb["yf_ticker"].iloc[0] == "META" and fb["ticker_raw"].iloc[0] == "FB"
    # 'S' (Sprint in 2012) must not resolve to SentinelOne's prices
    m12 = U.members("2012-06-29", indexes=("SP500",), dedupe=False)
    sprint = m12[m12["ticker_raw"] == "S"]
    assert sprint.empty or sprint["yf_ticker"].isna().all()


@built
def test_security_master_and_price_tickers():
    sm = U.load_security_master()
    for c in ["cik", "yf_ticker", "name", "sic", "exchange", "is_listed_now", "ever_sp1500", "first_price_date",
              "last_price_date"]:
        assert c in sm.columns
    assert sm["cik"].dropna().is_unique
    assert sm["first_price_date"].isna().all() and sm["last_price_date"].isna().all()
    assert sm["ever_sp1500"].sum() > 1500 and (~sm.loc[sm["ever_sp1500"], "is_listed_now"]).sum() > 300
    txt = U.PRICE_TICKERS_PATH.read_text().split()
    assert len(txt) == len(set(txt)) and txt == sorted(txt)
    from quant.settings import BENCHMARKS
    assert set(BENCHMARKS) <= set(txt)
    mem = U.load_membership()
    assert set(mem["yf_ticker"].dropna()) <= set(txt)
    us = U.us_all()
    assert set(us["yf_ticker"]) <= set(txt)
    assert 3000 < len(us) < 7000 and us["yf_ticker"].is_unique and us["cik"].is_unique
    assert set(us["exchange"]) <= {"NYSE", "Nasdaq", "NYSE American"}
