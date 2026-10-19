"""Tests for quant/data/factors.py (French/AQR parsing, caching).

No network access is needed: parsing is tested on embedded snippets in French's real multi-block layout,
HTTP/caching on fakes, and the Barroso-Santa-Clara weights on synthetic daily returns. One integration test uses
the parquet cache in cache/factors/ and is skipped when the cache has not been built.
"""
from __future__ import annotations

import io
import zipfile

import numpy as np
import pandas as pd
import pytest

from quant.data import factors as F

# --------------------------------------------------------------------------------------
# Embedded French-format snippets
# --------------------------------------------------------------------------------------
FF3_SNIPPET = """This file was created using the 202608 CRSP database.
The 1-month TBill rate data until 202405 are from Ibbotson Associates.
The annual TBill return is compounded from the monthly T-bill rates from January to December.

,Mkt-RF,SMB,HML,RF
192607,    2.89,   -2.42,   -2.75,    0.22
192608,    2.64,   -1.17,    3.81,    0.25
192609,    0.38,   -1.40,   -0.05,    0.23
192610,  -99.99,   -0.07,  -99.99,    0.32
192611,    2.56,   -999,    -0.45,    0.31

Annual Factors: January-December
,Mkt-RF,SMB,HML,RF
1927,   29.44,   -3.05,   -3.36,    3.12
1928,   35.59,   -4.04,   -5.14,    3.08

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

DECILE_COLS = ",Lo PRIOR,PRIOR 2,PRIOR 3,PRIOR 4,PRIOR 5,PRIOR 6,PRIOR 7,PRIOR 8,PRIOR 9,Hi PRIOR"
DECILE_SNIPPET = f"""This file was created using the 202608 CRSP database.
It contains value- and equal-weighted returns for  10 prior-return portfolios.

Missing data are indicated by -99.99 or -999.


Value Weight Returns -- Monthly
{DECILE_COLS}
192701,  -3.32,  -4.54,   2.67,  -0.29,  -0.41,   0.97,   0.29,   0.71,  -0.14,  -0.24
192702,   7.39,   6.01,   7.03,   7.46,   4.69,   3.72,   2.99,   3.20,   4.14,   7.04
192703,  -99.99,   1.00,   2.00,   3.00,   4.00,   5.00,   6.00,   7.00,   8.00,   9.00


Average Equal Weighted Returns -- Monthly
{DECILE_COLS}
192701,  -0.47,   0.88,   4.10,   2.51,  -0.29,   3.08,   0.98,   0.98,  -0.39,   1.30
192702,   6.00,   5.00,   4.00,   3.00,   2.00,   1.00,   0.00,  -1.00,  -2.00,  -3.00


Average Value Weighted Returns -- Annual
{DECILE_COLS}
1927,  13.05,   8.26,  18.79,  23.59,  33.27,  23.26,  36.19,  28.44,  39.55,  66.00


Number of Firms in Portfolios
{DECILE_COLS}
192701,     47,     47,     48,     47,     47,     47,     47,     48,     47,     47

Copyright 2026 Eugene F. Fama and Kenneth R. French
"""

DAILY_SNIPPET = """This file was created by using the 202608 CRSP database.

,Mom
19261103,   0.55
19261104,   0.71
19261105,  -99.99
19261108,   0.10
"""


# --------------------------------------------------------------------------------------
# French parsing
# --------------------------------------------------------------------------------------
def test_multiblock_parse_finds_all_blocks_and_frequencies():
    blocks = F.parse_french_blocks(FF3_SNIPPET)
    assert [b.freq for b in blocks] == ["M", "A"]
    assert list(blocks[0].data.columns) == ["Mkt-RF", "SMB", "HML", "RF"]
    assert len(blocks[0].data) == 5 and len(blocks[1].data) == 2
    assert "Annual Factors" in blocks[1].title

    blocks = F.parse_french_blocks(DECILE_SNIPPET)
    assert [b.freq for b in blocks] == ["M", "M", "A", "M"]
    assert [b.title for b in blocks][:3] == [
        "Value Weight Returns -- Monthly", "Average Equal Weighted Returns -- Monthly", "Average Value Weighted Returns -- Annual"]


def test_decimal_conversion():
    m = F.parse_french_csv(FF3_SNIPPET, "M")
    assert m.loc["1926-07-31", "Mkt-RF"] == pytest.approx(0.0289)
    assert m.loc["1926-07-31", "RF"] == pytest.approx(0.0022)
    assert m.loc["1926-08-31", "HML"] == pytest.approx(0.0381)
    assert float(m.abs().max().max()) < 0.1  # everything is a decimal, not a percent


def test_missing_codes_become_nan():
    m = F.parse_french_csv(FF3_SNIPPET, "M")
    assert np.isnan(m.loc["1926-10-31", "Mkt-RF"]) and np.isnan(m.loc["1926-10-31", "HML"])  # -99.99
    assert np.isnan(m.loc["1926-11-30", "SMB"])  # -999
    assert m.loc["1926-10-31", "SMB"] == pytest.approx(-0.0007)  # neighbours untouched
    assert int(m.isna().sum().sum()) == 3
    d = F.parse_french_csv(DAILY_SNIPPET, "D")
    assert np.isnan(d.loc["1926-11-05", "Mom"])


def test_monthly_index_is_month_end_aligned_and_sorted():
    m = F.parse_french_csv(FF3_SNIPPET, "M")
    idx = m.index
    assert idx.is_monotonic_increasing and idx.is_unique
    assert (idx == idx + pd.offsets.MonthEnd(0)).all()  # every stamp is already a month-end
    assert (idx == idx.normalize()).all() and idx.tz is None
    assert idx[0] == pd.Timestamp("1926-07-31") and idx[-1] == pd.Timestamp("1926-11-30")
    assert idx.name == "date"
    # month-end, including leap-year February
    snip = ",A\n192802,  1.0\n192803,  2.0\n192902,  3.0\n"
    leap = F.parse_french_csv(snip, "M").index
    assert list(leap) == [pd.Timestamp("1928-02-29"), pd.Timestamp("1928-03-31"), pd.Timestamp("1929-02-28")]


def test_daily_index_is_trading_day():
    d = F.parse_french_csv(DAILY_SNIPPET, "D")
    assert list(d.index) == [pd.Timestamp("1926-11-03"), pd.Timestamp("1926-11-04"), pd.Timestamp("1926-11-05"), pd.Timestamp("1926-11-08")]
    assert d.loc["1926-11-03", "Mom"] == pytest.approx(0.0055)


def test_annual_block_is_year_end():
    a = F.parse_french_csv(FF3_SNIPPET, "A")
    assert list(a.index) == [pd.Timestamp("1927-12-31"), pd.Timestamp("1928-12-31")]
    assert a.loc["1927-12-31", "Mkt-RF"] == pytest.approx(0.2944)


def test_vw_and_ew_blocks_are_selected_by_title():
    vw = F.parse_french_csv(DECILE_SNIPPET, "M", F._ret_title("vw", "M"))
    ew = F.parse_french_csv(DECILE_SNIPPET, "M", F._ret_title("ew", "M"))
    assert len(vw) == 3 and len(ew) == 2
    assert vw.iloc[0, 0] == pytest.approx(-0.0332) and ew.iloc[0, 0] == pytest.approx(-0.0047)
    assert np.isnan(vw.loc["1927-03-31", "Lo PRIOR"])
    # the 'Number of Firms' and annual blocks must never be returned for a monthly returns request
    assert vw.iloc[0].abs().max() < 0.1
    with pytest.raises(ValueError):
        F.parse_french_csv(DECILE_SNIPPET, "D", F._ret_title("vw", "D"))
    # real-file title variants
    import re
    for title in ["Average Value Weighted Returns -- Monthly", "Value Weight Returns -- Monthly", "  value weight returns -- monthly"]:
        assert re.search(F._ret_title("vw", "M"), title.strip(), re.I)
    for title in ["Average Equal Weighted Returns -- Monthly", "Equal Weight Returns -- Monthly"]:
        assert re.search(F._ret_title("ew", "M"), title, re.I)
    assert not re.search(F._ret_title("vw", "M"), "Value-Weighted Average of Prior Returns", re.I)
    assert not re.search(F._ret_title("vw", "M"), "Average Value Weighted Returns -- Annual", re.I)


def test_decile_bmop_and_ep_column_naming():
    vw = F.parse_french_csv(DECILE_SNIPPET, "M", F._ret_title("vw", "M"))
    vw.columns = F._decile_cols(list(vw.columns))
    assert list(vw.columns) == [f"D{i}" for i in range(1, 11)]
    assert vw.loc["1927-01-31", "D1"] == pytest.approx(-0.0332) and vw.loc["1927-01-31", "D10"] == pytest.approx(-0.0024)

    names = F._bmop_cols([f"c{i}" for i in range(25)])
    assert names[0] == "BM1_OP1" and names[4] == "BM1_OP5" and names[5] == "BM2_OP1" and names[24] == "BM5_OP5" and len(set(names)) == 25
    with pytest.raises(ValueError):
        F._bmop_cols(["a", "b"])

    ep = F._ep_cols([f"c{i}" for i in range(19)])
    assert ep[0] == "neg" and ep[8] == "Q5" and ep[9] == "D1" and ep[18] == "D10"


def test_ragged_and_blank_cells_do_not_break_the_parser():
    snip = ",A,B,C\n200001,  1.0,  2.0\n200002,  1.0,,  3.0\n200003,  5.0,  6.0,  7.0,  8.0\n"
    df = F.parse_french_csv(snip, "M")
    assert df.shape == (3, 3)
    assert np.isnan(df.iloc[0, 2]) and np.isnan(df.iloc[1, 1])
    assert df.iloc[2, 2] == pytest.approx(0.07)


# --------------------------------------------------------------------------------------
# Download / cache plumbing (fakes, no network)
# --------------------------------------------------------------------------------------
class _Resp:
    def __init__(self, code: int, content: bytes = b""):
        self.status_code, self.content = code, content


def test_http_get_retries_then_succeeds(monkeypatch):
    calls = []
    seq = [F.requests.ConnectionError("boom"), _Resp(503), _Resp(200, b"payload")]

    def fake_get(url, headers=None, timeout=None):
        calls.append((url, headers))
        item = seq[len(calls) - 1]
        if isinstance(item, Exception):
            raise item
        return item

    monkeypatch.setattr(F.requests, "get", fake_get)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    assert F.http_get("https://example.test/x.zip", retries=4) == b"payload"
    assert len(calls) == 3
    ua = calls[0][1]["User-Agent"]
    assert ua.startswith("Mozilla/5.0") and "python-requests" not in ua  # a normal browser User-Agent


def test_http_get_gives_up_and_does_not_retry_404(monkeypatch):
    n = {"calls": 0}

    def fake_404(url, headers=None, timeout=None):
        n["calls"] += 1
        return _Resp(404)

    monkeypatch.setattr(F.requests, "get", fake_404)
    monkeypatch.setattr(F.time, "sleep", lambda s: None)
    with pytest.raises(RuntimeError):
        F.http_get("https://example.test/missing.zip", retries=4)
    assert n["calls"] == 1

    def fake_500(url, headers=None, timeout=None):
        n["calls"] += 1
        return _Resp(500)

    n["calls"] = 0
    monkeypatch.setattr(F.requests, "get", fake_500)
    with pytest.raises(RuntimeError):
        F.http_get("https://example.test/down.zip", retries=3)
    assert n["calls"] == 3


def test_zip_text_reads_in_memory():
    buf = io.BytesIO()
    with zipfile.ZipFile(buf, "w") as z:
        z.writestr("F-F_Research_Data_Factors.csv", FF3_SNIPPET)
    text = F._zip_text(buf.getvalue())
    assert text.startswith("This file was created")
    assert F.parse_french_csv(text, "M").shape == (5, 4)
    empty = io.BytesIO()
    with zipfile.ZipFile(empty, "w") as z:
        z.writestr("readme.pdf", b"x")
    with pytest.raises(ValueError):
        F._zip_text(empty.getvalue())


def test_cache_roundtrip_staleness_and_fallback(tmp_path, monkeypatch):
    import os
    import time

    monkeypatch.setattr(F, "FACTOR_DIR", tmp_path)
    df = F.parse_french_csv(FF3_SNIPPET, "M")
    calls = {"n": 0}

    def builder():
        calls["n"] += 1
        return df

    out = F._cached("unit", builder, force=False, max_age_days=30)
    assert calls["n"] == 1 and (tmp_path / "unit.parquet").exists()
    pd.testing.assert_frame_equal(out, df, check_freq=False)
    F._cached("unit", builder, force=False, max_age_days=30)
    assert calls["n"] == 1  # fresh cache is used
    F._cached("unit", builder, force=True, max_age_days=30)
    assert calls["n"] == 2  # force re-downloads

    old = time.time() - 90 * 86400
    os.utime(tmp_path / "unit.parquet", (old, old))

    def failing():
        raise RuntimeError("network down")

    stale = F._cached("unit", failing, force=False, max_age_days=30)  # stale copy beats nothing
    pd.testing.assert_frame_equal(stale, df, check_freq=False)
    with pytest.raises(F.FactorDataUnavailable):
        F._cached("never_cached", failing, force=False, max_age_days=30)


def test_aqr_qmj_sheet_parser():
    openpyxl = pytest.importorskip("openpyxl")
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.title = "QMJ Factors"
    ws.append(["AQR Capital Management - Quality Minus Junk: Factors, Monthly"])
    ws.append([None])
    ws.append([None, "EQUITIES"])
    ws.append(["DATE", "AUS", "USA", "Global"])
    ws.append(["07/31/1957", None, 0.011154, None])
    ws.append(["08/31/1957", None, 0.004877, None])
    ws.append(["02/28/1958", None, -0.0123, 0.001])
    wb.create_sheet("Definition")
    buf = io.BytesIO()
    wb.save(buf)
    df = F._read_aqr_qmj(buf.getvalue())
    assert list(df.columns) == ["USA", "Global"]  # all-empty AUS column dropped
    assert list(df.index) == [pd.Timestamp("1957-07-31"), pd.Timestamp("1957-08-31"), pd.Timestamp("1958-02-28")]
    assert df.loc["1957-07-31", "USA"] == pytest.approx(0.011154) and df.loc["1958-02-28", "USA"] == pytest.approx(-0.0123)
    with pytest.raises(ValueError):
        F._read_aqr_qmj(b"<html>blocked</html>")


def test_qmj_rejects_non_monthly():
    with pytest.raises(ValueError):
        F.qmj("D")


# --------------------------------------------------------------------------------------
# Integration with the real cache (skipped when cache/factors is empty)
# --------------------------------------------------------------------------------------
needs_cache = pytest.mark.skipif(
    not all((F.FACTOR_DIR / f"{k}.parquet").exists() for k in ("ff5_M", "ff3_M", "mom_M", "mom_deciles_M_vw")),
    reason="cache/factors not built (run factors.download_all() once)",
)


@needs_cache
def test_cached_factors_shapes_and_reference_values():
    big = 1e9  # never trigger a refresh in a test
    f5 = F.ff5("M", max_age_days=big)
    assert list(f5.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "RF"]
    assert f5.index[0] == pd.Timestamp("1963-07-31") and (f5.index == f5.index + pd.offsets.MonthEnd(0)).all()
    assert float(f5.abs().max().max()) < 1.0
    reg = F.ff_factors_for_regression("M", max_age_days=big)
    assert list(reg.columns) == ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF"] and not reg.isna().any().any()
    dec = F.mom_deciles("M", "vw", max_age_days=big)
    assert list(dec.columns) == [f"D{i}" for i in range(1, 11)] and dec.index[0] == pd.Timestamp("1927-01-31")
    wml = dec["D10"] - dec["D1"]
    # research/01 section 9: WML mean 13.6%/yr, vol 27.6%, Sharpe 0.49 over 1927-01..2026-08
    sub = wml.loc["1927-01":"2026-08"]
    assert 12 * sub.mean() == pytest.approx(0.136, abs=0.002)
    assert sub.std() * np.sqrt(12) == pytest.approx(0.276, abs=0.002)
    ew = F.mom_deciles("M", "ew", max_age_days=big)
    assert not np.allclose(ew.to_numpy(), dec.to_numpy())  # EW and VW blocks are different data
    mk = F.market("M", max_age_days=big)
    ff3 = F.ff3("M", max_age_days=big)
    assert (mk - ff3["Mkt-RF"] - ff3["RF"]).abs().max() < 1e-12


# --------------------------------------------------------------------------------------
# Barroso & Santa-Clara weights
# --------------------------------------------------------------------------------------
def _daily(n=700, start="2019-12-02", seed=0, sd=0.01):
    idx = pd.bdate_range(start, periods=n)
    return pd.Series(np.random.default_rng(seed).normal(0.0, sd, n), index=idx)












# --------------------------------------------------------------------------------------
# Statistics helpers
# --------------------------------------------------------------------------------------












