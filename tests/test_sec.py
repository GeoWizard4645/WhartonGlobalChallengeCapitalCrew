"""Tests for quant/data/sec.py.

Two groups:
  * synthetic: tiny fake zips in tmp_path exercise the filters / schemas / idempotency (no cache needed)
  * real cache: read single partitions of the built cache (skipped if the cache is not built)
"""
from __future__ import annotations

import json
import time
import zipfile

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq
import pytest

from quant.data import sec

APPLE = 320193
MSFT = 789019

REAL_CACHE = (
    all(sec._part_path(p).exists() for p in range(sec.N_PARTS))
    and sec.COMPANIES_PATH.exists()
    and sec.FILINGS_PATH.exists()
)
needs_cache = pytest.mark.skipif(not REAL_CACHE, reason="SEC cache not built (run python -m quant.data.sec)")

CATEGORICAL_COLS = ["taxonomy", "tag", "unit", "form", "fp"]


# ----------------------------------------------------------------------------------------
# synthetic fixtures
# ----------------------------------------------------------------------------------------
def _fact(end, val, form="10-K", filed="2021-03-01", start=None, fy=2020, fp="FY", accn="0000000001-21-000001"):
    r = {"end": end, "val": val, "accn": accn, "fy": fy, "fp": fp, "form": form, "filed": filed}
    if start is not None:
        r["start"] = start
    return r


def _company(cik, name, facts):
    return {"cik": cik, "entityName": name, "facts": facts}


def _write_zip(path, members: dict):
    with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as zf:
        for name, obj in members.items():
            zf.writestr(name, json.dumps(obj))


@pytest.fixture()
def fake_sec(tmp_path, monkeypatch):
    """Point the module at two tiny fake zips; returns the cik list."""
    facts = {
        # cik 1 and 65 share partition 1; 2 is partition 2; 3 has no usable facts; 4 has no 'facts' key
        "CIK0000000001.json": _company(1, "Alpha", {
            "us-gaap": {
                "Revenues": {"units": {
                    "USD": [
                        _fact("2020-12-31", 100, start="2020-01-01"),
                        _fact("2020-12-31", 101, form="10-K/A", filed="2021-05-01", start="2020-01-01"),
                        _fact("2020-12-31", 102, form="8-K", filed="2021-06-01", start="2020-01-01"),   # dropped form
                        _fact("0202-02-01", 7, start="2019-01-01"),                                       # bad end -> dropped
                    ],
                    "CAD": [_fact("2020-12-31", 5, start="2020-01-01")],                                 # dropped unit
                }},
                "Assets": {"units": {"USD": [_fact("2020-12-31", 1e12)]}},                                # instant
                "NotInRegistry": {"units": {"USD": [_fact("2020-12-31", 1)]}},
                "EarningsPerShareDiluted": {"units": {"USD/shares": [_fact("2020-12-31", 1.5, start="2020-01-01", fp="CY")]}},
            },
            "dei": {"EntityCommonStockSharesOutstanding": {"units": {"shares": [_fact("2021-02-20", 10**25)]}}},
            "ifrs-full": {"Revenue": {"units": {"USD": [_fact("2020-12-31", 1)]}}},
        }),
        "CIK0000000065.json": _company(65, "Beta", {
            "us-gaap": {"Assets": {"units": {"USD": [_fact("2019-12-31", 5, filed="2020-03-01", fy=2019),
                                                      _fact("2018-12-31", 4, filed="2019-03-01", fy=2018)]}}}}),
        "CIK0000000002.json": _company(2, "Gamma", {
            "us-gaap": {"Liabilities": {"units": {"USD": [_fact("2020-12-31", 3, form="10-Q", fp="Q3")]}}}}),
        "CIK0000000003.json": _company(3, "Delta", {"us-gaap": {"NotInRegistry": {"units": {"USD": [_fact("2020-12-31", 1)]}}}}),
        "CIK0000000004.json": {"cik": 4, "entityName": "Epsilon"},
    }
    cf = tmp_path / "companyfacts.zip"
    _write_zip(cf, facts)

    def sub(cik, name, sic, recent, files=None, extra=None):
        d = {"cik": f"{cik:010d}", "entityType": "operating", "sic": sic, "sicDescription": "Test Industry",
             "name": name, "tickers": ["AA", "AB"], "exchanges": ["NYSE", None], "category": "Large accelerated filer",
             "fiscalYearEnd": "1231", "stateOfIncorporation": "DE", "formerNames": [{"name": "OLD", "from": "x", "to": "y"}],
             "filings": {"recent": recent, "files": files or []}}
        d.update(extra or {})
        return d

    def rec(rows):
        keys = ["accessionNumber", "filingDate", "reportDate", "acceptanceDateTime", "form", "items"]
        return {k: [r[i] for r in rows] for i, k in enumerate(keys)}

    recent1 = rec([
        ("a-1", "2021-03-01", "2020-12-31", "2021-03-01T21:30:00.000Z", "10-K", ""),
        ("a-2", "2021-04-01", "", "2021-04-01T12:00:00.000Z", "8-K", "2.02,9.01"),
        ("a-3", "2021-04-02", "", "2021-04-02T12:00:00.000Z", "4", ""),             # not kept
        ("a-4", "2021-05-01", "2021-03-31", "2021-05-01T12:00:00.000Z", "10-Q", ""),
        ("a-5", "2021-06-01", "2020-12-31", "2021-06-01T12:00:00.000Z", "10-K/A", ""),
    ])
    overflow1 = rec([
        ("a-0", "1995-02-01", "1994-12-31", "1995-02-01T12:00:00.000Z", "10-K405", ""),
        ("a-00", "1996-02-01", "1995-12-31", "", "10-K", ""),
        ("a-000", "1996-06-01", "", "1996-06-01T12:00:00.000Z", "25-NSE", ""),
    ])
    subs = {
        "CIK0000000001.json": sub(1, "Alpha Corp", "3571", recent1, files=[{"name": "CIK0000000001-submissions-001.json"}]),
        "CIK0000000001-submissions-001.json": overflow1,
        "CIK0000000002.json": sub(2, "Gamma Inc", "0000", rec([("g-1", "2020-01-02", "2019-09-30", "2020-01-02T00:00:00.000Z", "10-Q", "")])),
        "CIK0000000003.json": sub(3, "Delta", "", rec([])),
        "CIK0000000004.json": sub(4, "Epsilon", "6199", rec([("e-1", "2019-01-02", "", "2019-01-02T00:00:00.000Z", "S-1", "")])),
        "CIK0000000065.json": sub(65, "Beta", "7372", rec([("b-1", "2020-03-01", "2019-12-31", "2020-03-01T00:00:00.000Z", "10-K", "")])),
        "CIK0000999999.json": sub(999999, "Not in companyfacts", "1000", rec([("z-1", "2020-03-01", "", "2020-03-01T00:00:00.000Z", "10-K", "")])),
    }
    sz = tmp_path / "submissions.zip"
    _write_zip(sz, subs)

    monkeypatch.setattr(sec, "COMPANYFACTS_ZIP", cf)
    monkeypatch.setattr(sec, "SUBMISSIONS_ZIP", sz)
    monkeypatch.setattr(sec, "SEC_DIR", tmp_path)
    monkeypatch.setattr(sec, "FACTS_DIR", tmp_path / "facts")
    monkeypatch.setattr(sec, "COMPANIES_PATH", tmp_path / "companies.parquet")
    monkeypatch.setattr(sec, "FILINGS_PATH", tmp_path / "filings.parquet")
    monkeypatch.setattr(sec, "_SUBS_BUILT_THIS_PROCESS", False)
    return tmp_path


# ----------------------------------------------------------------------------------------
# registry / helpers (no cache needed)
# ----------------------------------------------------------------------------------------
def test_tags_registry():
    flat = [t for tags in sec.TAGS.values() for t in tags]
    assert len(flat) == len(set(flat)), "duplicate tags"
    assert set(sec.TAGS) == {"us-gaap", "dei"}
    for t in ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "GrossProfit", "OperatingIncomeLoss",
              "NetIncomeLoss", "Assets", "LongTermDebtNoncurrent", "DebtCurrent", "OperatingLeaseLiability",
              "EarningsPerShareDiluted", "PaymentsToAcquirePropertyPlantAndEquipment"]:
        assert t in sec.TAGS["us-gaap"], t
    assert sec.TAGS["dei"] == ["EntityCommonStockSharesOutstanding", "EntityPublicFloat"]
    assert sec.UNITS == {"USD", "shares", "USD/shares", "pure"}
    assert "10-K" in sec.FORMS and "8-K" not in sec.FORMS


def test_cik_to_partition():
    assert sec.cik_to_partition(APPLE) == APPLE % 64 == 1
    assert sec.cik_to_partition(64) == 0
    assert sec.cik_to_partition("65") == 1


def test_to_ts_handles_bad_dates():
    out = sec._to_ts(["2020-01-01", "", None, "0202-02-01", "2020-13-45", "2023-09-30"]).to_pylist()
    assert out[0] == pd.Timestamp("2020-01-01") and out[5] == pd.Timestamp("2023-09-30")
    assert out[1:5] == [None, None, None, None]


# ----------------------------------------------------------------------------------------
# synthetic end-to-end
# ----------------------------------------------------------------------------------------
def test_build_facts_synthetic(fake_sec):
    d = sec.build_facts(n_jobs=1)
    assert d == sec.FACTS_DIR
    p1 = pq.read_table(sec._part_path(1))
    assert p1.schema.equals(sec.FACTS_SCHEMA)
    df = sec.load_facts([1, 65, 2])
    assert set(df.cik) == {1, 65, 2}
    a = df[df.cik == 1]
    # kept: Revenues 10-K + 10-K/A (8-K, CAD and bad-end rows dropped), Assets, EPS, dei shares
    assert sorted(a.tag.astype(str).unique()) == ["Assets", "EarningsPerShareDiluted", "EntityCommonStockSharesOutstanding", "Revenues"]
    rev = a[a.tag == "Revenues"].sort_values("filed")
    assert rev.val.tolist() == [100.0, 101.0]
    assert rev.form.astype(str).tolist() == ["10-K", "10-K/A"]
    assert rev.start.notna().all()
    assets = a[a.tag == "Assets"]
    assert assets.start.isna().all() and assets.val.iloc[0] == 1e12
    dei = a[a.tag == "EntityCommonStockSharesOutstanding"]
    assert dei.taxonomy.astype(str).iloc[0] == "dei" and dei.unit.astype(str).iloc[0] == "shares" and dei.val.iloc[0] == 1e25
    assert a[a.tag == "EarningsPerShareDiluted"].fp.astype(str).iloc[0] == "CY"
    assert set(df.loc[df.cik == 65, "end"]) == {pd.Timestamp("2018-12-31"), pd.Timestamp("2019-12-31")}
    assert set(df.loc[df.cik == 2, "form"].astype(str)) == {"10-Q"}
    # filters
    only = sec.load_facts([1], tags=["Assets"], columns=["cik", "tag", "val"])
    assert only.columns.tolist() == ["cik", "tag", "val"] and len(only) == 1
    assert sec.load_facts([1], tags=["Liabilities"]).empty
    assert sec.load_facts([]).empty
    # sorted by cik within a partition (cik 1 then 65)
    assert pq.read_table(sec._part_path(1), columns=["cik"])["cik"].to_pylist() == sorted(
        pq.read_table(sec._part_path(1), columns=["cik"])["cik"].to_pylist())


def test_build_facts_idempotent_and_force(fake_sec):
    sec.build_facts(n_jobs=1)
    paths = [sec._part_path(p) for p in range(sec.N_PARTS)]
    assert all(p.exists() for p in paths)
    before = {p: p.stat().st_mtime_ns for p in paths}
    sec.build_facts(n_jobs=1)           # no-op
    assert {p: p.stat().st_mtime_ns for p in paths} == before
    sec.build_facts(force=True, n_jobs=1)
    assert any(p.stat().st_mtime_ns != before[p] for p in paths)


def test_build_submissions_synthetic(fake_sec):
    sec.build_companies(n_jobs=1)
    assert sec.COMPANIES_PATH.exists() and sec.FILINGS_PATH.exists()   # one pass writes both
    c = sec.load_companies().set_index("cik")
    assert sorted(c.index) == [1, 2, 3, 4, 65]                          # restricted to companyfacts CIKs
    a = c.loc[1]
    assert a["name"] == "Alpha Corp" and a["sic"] == 3571
    assert a["tickers"] == "AA|AB" and a["exchanges"] == "NYSE|"
    assert a["first_filing_date"] == pd.Timestamp("1995-02-01")         # from the overflow file
    assert a["n_10k"] == 3 and a["n_10q"] == 1                          # 10-K405 + 10-K + 10-K ; amendments excluded
    assert a["last_filing_date"] == pd.Timestamp("2021-06-01")
    assert a["last_periodic_filing_date"] == pd.Timestamp("2021-06-01")
    assert json.loads(a["former_names"])[0]["name"] == "OLD"
    assert pd.isna(c.loc[2, "sic"]) and pd.isna(c.loc[3, "sic"])         # '0000' and '' -> null
    assert pd.isna(c.loc[3, "first_filing_date"])
    assert str(sec.load_companies()["sic"].dtype) == "Int64"

    f = sec.load_filings()
    assert 999999 not in set(f.cik)
    assert "4" not in set(f.form.astype(str))                           # unlisted form dropped
    fa = f[f.cik == 1].sort_values("filing_date")
    # a-0 is a 10-K405 (counted in n_10k but not a kept form); a-3 is a Form 4 (not kept)
    assert fa.accn.tolist() == ["a-00", "a-000", "a-1", "a-2", "a-4", "a-5"]
    assert fa["items"].tolist()[3] == "2.02,9.01" and pd.isna(fa["items"].iloc[0])
    assert fa.acceptance_datetime.iloc[2] == pd.Timestamp("2021-03-01 21:30:00")   # UTC, naive
    assert pd.isna(fa.acceptance_datetime.iloc[0]) and pd.isna(fa.report_date.iloc[1])
    assert set(sec.load_filings(forms=["25-NSE"]).cik) == {1}
    # second call is a no-op for both builders
    m = sec.FILINGS_PATH.stat().st_mtime_ns
    sec.build_filings()
    assert sec.FILINGS_PATH.stat().st_mtime_ns == m


# ----------------------------------------------------------------------------------------
# real cache (single partitions -> fast)
# ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def apple_part():
    return sec.load_partition(sec.cik_to_partition(APPLE))


@needs_cache
def test_partition_schema_and_dtypes(apple_part):
    path = sec._part_path(1)
    schema = pq.read_schema(path)
    assert schema.names == sec.FACTS_COLUMNS
    for name in CATEGORICAL_COLS:
        assert pa.types.is_dictionary(schema.field(name).type), name
    df = apple_part
    assert df.cik.dtype == np.int64
    assert df.val.dtype == np.float64 and df.fy.dtype == np.float64
    for c in ("start", "end", "filed"):
        assert df[c].dtype == np.dtype("datetime64[ns]"), c
    for c in CATEGORICAL_COLS:
        assert isinstance(df[c].dtype, pd.CategoricalDtype), c
    assert pd.api.types.is_string_dtype(df.accn.dtype)
    # content invariants
    assert (df.cik % sec.N_PARTS == 1).all()
    assert set(df.unit.astype(str)) <= sec.UNITS
    assert set(df.form.astype(str)) <= sec.FORMS
    assert set(df.taxonomy.astype(str)) <= {"us-gaap", "dei"}
    assert set(df.tag.astype(str)) <= {t for tags in sec.TAGS.values() for t in tags}
    assert df.end.notna().all() and df.filed.notna().all() and df.val.notna().all()
    assert df.cik.is_monotonic_increasing                      # sorted -> row-group pruning on cik works
    assert len(df) > 100_000
    assert pq.read_metadata(path).num_row_groups >= 1
    assert schema.metadata[b"sec_sig"].decode() == sec._facts_signature()


@needs_cache
def test_apple_revenue_fy2023(apple_part):
    a = apple_part[apple_part.cik == APPLE]
    r = a[(a.tag == "RevenueFromContractWithCustomerExcludingAssessedTax")
          & (a.start == "2022-09-25") & (a.end == "2023-09-30") & (a.unit == "USD")]
    assert not r.empty
    assert (r.val == 383_285_000_000).all()
    first = r.sort_values("filed").iloc[0]
    assert first.filed == pd.Timestamp("2023-11-03")
    assert str(first.form) == "10-K" and str(first.fp) == "FY" and first.fy == 2023
    assert first.accn == "0000320193-23-000106"
    # the same period re-appears as a comparative in later 10-Ks
    assert r.filed.nunique() >= 2


@needs_cache
def test_apple_dei_shares_outstanding(apple_part):
    d = apple_part[(apple_part.cik == APPLE) & (apple_part.tag == "EntityCommonStockSharesOutstanding")]
    assert len(d) >= 10
    assert set(d.taxonomy.astype(str)) == {"dei"} and set(d.unit.astype(str)) == {"shares"}
    assert d.start.isna().all()
    assert (d.val > 5e8).all()    # pre-2014-split values are ~9e8, latest ~1.46e10


@needs_cache
def test_microsoft_operating_income():
    m = sec.load_facts([MSFT], tags=["OperatingIncomeLoss"])
    assert len(m) > 100 and set(m.cik) == {MSFT}
    assert m.val.max() > 1e10 and set(m.tag.astype(str)) == {"OperatingIncomeLoss"}


@needs_cache
def test_load_facts_filtering():
    tags = ["Assets", "Revenues"]
    df = sec.load_facts([APPLE, MSFT], tags=tags)
    assert set(df.cik) == {APPLE, MSFT}
    assert set(df.tag.astype(str)) <= set(tags) and "Assets" in set(df.tag.astype(str))
    # columns projection (filter columns need not be projected)
    sub = sec.load_facts([APPLE], tags=["Assets"], columns=["end", "val"])
    assert sub.columns.tolist() == ["end", "val"] and len(sub) > 20
    # instants have no start
    assets = sec.load_facts([APPLE], tags=["Assets"])
    assert assets.start.isna().all()
    # categories are the global fixed dictionary
    assert df.unit.cat.categories.tolist() == sec._UNIT_LIST
    # unknown cik -> empty; unknown column -> error
    assert sec.load_facts([1], tags=["Assets"]).empty
    with pytest.raises(KeyError):
        sec.load_facts([APPLE], columns=["nope"])


@needs_cache
def test_build_facts_is_noop_when_current():
    paths = [sec._part_path(p) for p in range(sec.N_PARTS)]
    before = [p.stat().st_mtime_ns for p in paths]
    t0 = time.time()
    sec.build_facts()
    assert time.time() - t0 < 10
    assert [p.stat().st_mtime_ns for p in paths] == before


@needs_cache
def test_companies_basics():
    c = sec.load_companies()
    assert list(c.columns[:14]) == ["cik", "name", "tickers", "exchanges", "sic", "sic_description", "category",
                                    "fiscal_year_end", "entity_type", "state_of_inc", "first_filing_date",
                                    "n_10k", "n_10q", "former_names"]
    assert len(c) == 20472 and c.cik.is_unique
    a = c[c.cik == APPLE].iloc[0]
    assert a["sic"] == 3571 and a["name"] == "Apple Inc."
    assert "AAPL" in a["tickers"].split("|") and a["exchanges"].split("|")[0] == "Nasdaq"
    assert a["fiscal_year_end"] == "0926" and a["category"] == "Large accelerated filer"
    assert a["first_filing_date"] == pd.Timestamp("1994-01-26")       # needs the overflow file
    assert a["n_10k"] >= 30 and a["n_10q"] >= 90
    assert isinstance(json.loads(a["former_names"]), list)
    assert str(c["sic"].dtype) == "Int64" and c.first_filing_date.dtype == np.dtype("datetime64[ns]")
    assert c[c.cik == MSFT].iloc[0]["sic"] == 7372
    # every company with facts is in companies
    facts_ciks = pd.Series(sec.load_partition(1, columns=["cik"]).cik.unique())
    assert facts_ciks.isin(c.cik).all()


@needs_cache
def test_filings_basics():
    f = sec.load_filings(ciks=[APPLE])
    assert f.columns.tolist() == ["cik", "accn", "form", "filing_date", "report_date", "acceptance_datetime", "items"]
    assert f.filing_date.dtype == np.dtype("datetime64[ns]") and isinstance(f.form.dtype, pd.CategoricalDtype)
    assert set(f.form.astype(str)) <= set(sec.FILING_FORMS)
    k = f[(f.form == "10-K") & (f.filing_date == "2023-11-03")]
    assert len(k) == 1 and k.accn.iloc[0] == "0000320193-23-000106"
    assert k.report_date.iloc[0] == pd.Timestamp("2023-09-30")
    assert f.filing_date.min() == pd.Timestamp("1994-01-26")            # overflow file included
    eightk = f[f.form == "8-K"]
    assert len(eightk) > 50 and eightk["items"].notna().any()
    # delisting / deregistration notices are present across the universe
    dl = sec.load_filings(forms=["25", "25-NSE", "15-12B", "15-12G"])
    assert len(dl) > 10_000 and dl.cik.nunique() > 3_000
    assert set(dl.form.astype(str)) <= {"25", "25-NSE", "15-12B", "15-12G"}
