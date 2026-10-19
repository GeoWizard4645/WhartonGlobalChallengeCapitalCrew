"""Tests for quant/data/factors.py (French/AQR parsing, caching) and quant/validation/factor_checks.py (formulas).

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
from quant.validation import factor_checks as fc

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
    reason="cache/factors not built (run `python -m quant.validation.factor_checks` once)",
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


def test_bsc_uncentered_vol_identity():
    """21 * sum(r_d^2) / 126 is the monthly variance; x12 = 252 * mean(r_d^2): the formula in research/01 section 4.1."""
    r = _daily().iloc[:126]
    monthly_var = 21 * (r**2).sum() / 126
    assert np.sqrt(12 * monthly_var) == pytest.approx(np.sqrt(252 * (r**2).mean()))
    vol = fc.trailing_vol_ann(_daily(), 126)
    assert vol.iloc[:125].isna().all() and vol.iloc[125] == pytest.approx(np.sqrt(252 * (_daily().iloc[:126] ** 2).mean()))


def test_bsc_weight_constant_volatility_synthetic():
    n, s = 700, 0.01
    idx = pd.bdate_range("2019-12-02", periods=n)
    r = pd.Series(np.where(np.arange(n) % 2 == 0, s, -s), index=idx)  # r^2 == s^2 on every day
    w = fc.bsc_weights(r, target=0.12, window=126).dropna()
    expected = 0.12 / (s * np.sqrt(252))
    assert len(w) > 20 and np.allclose(w.to_numpy(), expected)
    assert w.index[0] == pd.Timestamp("2020-06-30")  # first full 126-day window ends in May, applied to June
    assert (w.index == w.index + pd.offsets.MonthEnd(0)).all()
    # cap turns the rule into a no-leverage rule
    assert fc.bsc_weights(r, 0.50, 126, cap=1.0).dropna().max() == pytest.approx(1.0)
    # higher target -> proportionally bigger weight
    assert fc.bsc_weights(r, 0.24, 126).dropna().iloc[-1] == pytest.approx(2 * expected)


def test_bsc_weight_matches_manual_formula_on_random_data():
    r = _daily(n=900, seed=3, sd=0.012)
    w = fc.bsc_weights(r, 0.12, 126)
    for month_end in [pd.Timestamp("2021-03-31"), pd.Timestamp("2022-07-31"), pd.Timestamp("2023-02-28")]:
        prev_end = (month_end - pd.offsets.MonthEnd(1))
        last_day = r.index[r.index <= prev_end][-1]  # last trading day of the previous month
        window = r.loc[:last_day].iloc[-126:]
        manual = 0.12 / np.sqrt(252 * np.mean(window.to_numpy() ** 2))
        assert w.loc[month_end] == pytest.approx(manual, rel=1e-12)


def test_bsc_weight_has_no_look_ahead():
    r = _daily(n=900, seed=5)
    w0 = fc.bsc_weights(r)
    shocked = r.copy()
    month = pd.Period("2021-06", "M")
    in_month = shocked.index.to_period("M") == month
    shocked[in_month] = shocked[in_month] * 6.0
    w1 = fc.bsc_weights(shocked)
    m_end, next_end = pd.Timestamp("2021-06-30"), pd.Timestamp("2021-07-31")
    assert w1.loc[m_end] == pytest.approx(w0.loc[m_end])  # weight for June cannot see June returns
    assert w1.loc[next_end] < 0.9 * w0.loc[next_end]  # July's weight reacts to the volatile June
    assert w1.loc[: m_end].equals(w0.loc[: m_end]) or np.allclose(w1.loc[:m_end].dropna(), w0.loc[:m_end].dropna())


def test_compound_daily_to_monthly_and_last_obs():
    idx = pd.bdate_range("2020-01-27", "2020-03-04")
    r = pd.Series(0.001, index=idx)
    m = fc.compound_daily_to_monthly(r)
    assert list(m.index) == [pd.Timestamp("2020-01-31"), pd.Timestamp("2020-02-29"), pd.Timestamp("2020-03-31")]
    jan_days = int((idx.month == 1).sum())
    assert m.loc["2020-01-31"] == pytest.approx(1.001**jan_days - 1)
    last = fc._last_obs_per_month(pd.Series(np.arange(len(idx), dtype=float), index=idx))
    assert last.loc["2020-01-31"] == float(np.flatnonzero(idx.month == 1)[-1])


# --------------------------------------------------------------------------------------
# Statistics helpers
# --------------------------------------------------------------------------------------
def test_ols_hac_matches_statsmodels_and_private_fallback():
    sm = pytest.importorskip("statsmodels.api")
    rng = np.random.default_rng(1)
    T = 240
    x = rng.normal(size=(T, 2))
    e = rng.normal(size=T)
    e = e + 0.5 * np.r_[0.0, e[:-1]]  # autocorrelated errors so the HAC correction matters
    y = 0.4 + x @ np.array([1.2, -0.7]) + e
    X = np.column_stack([np.ones(T), x])
    for L in (0, 4, 8):
        mine = fc.ols_hac(y, X, L)
        ref = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": L, "use_correction": True})
        np.testing.assert_allclose(mine["beta"], ref.params, rtol=1e-10)
        np.testing.assert_allclose(mine["se"], ref.bse, rtol=1e-8)
        np.testing.assert_allclose(mine["t"], ref.tvalues, rtol=1e-8)
        priv = fc._ols_hac_np(y, X, L)
        np.testing.assert_allclose(priv["se"], ref.bse, rtol=1e-8)
        assert priv["r2"] == pytest.approx(ref.rsquared) and priv["n"] == T


def test_regress_and_lags():
    assert fc.newey_west_lags(93) == 4 and fc.newey_west_lags(1000) == 6  # floor of 4 (research/06 default L=4)
    rng = np.random.default_rng(2)
    idx = pd.date_range("2000-01-31", periods=200, freq="ME")
    mkt = pd.Series(rng.normal(0.005, 0.04, 200), index=idx, name="MKT")
    y = 0.002 + 1.3 * mkt + pd.Series(rng.normal(0, 0.01, 200), index=idx)
    res = fc.regress(y, mkt.to_frame())
    assert res["alpha"] == pytest.approx(0.002, abs=0.002) and res["loadings"]["MKT"] == pytest.approx(1.3, abs=0.05)
    assert fc.regress(y.iloc[:5], mkt.iloc[:5].to_frame()) is None  # too few observations
    m, t = fc.mean_hac(pd.Series(rng.normal(0.01, 0.02, 300)))
    assert 0.0 < m < 0.02 and t > 3


def test_max_drawdown_cagr_and_perf_row():
    assert fc.max_drawdown(np.array([0.1, -0.5, 0.2])) == pytest.approx(0.55 / 1.1 - 1.0)
    assert fc.max_drawdown(np.array([0.01, 0.02])) == pytest.approx(0.0)
    assert fc._max_drawdown_np(np.array([0.1, -0.5, 0.2])) == pytest.approx(-0.5)
    assert fc.cagr(pd.Series([0.01] * 12)) == pytest.approx(1.01**12 - 1)
    idx = pd.date_range("2001-01-31", periods=60, freq="ME")
    r = pd.Series(np.tile([0.03, -0.01], 30), index=idx)
    row = fc.perf_row(r)
    assert row["n"] == 60 and row["start"] == "2001-01" and row["end"] == "2005-12"
    assert row["mean_pct_m"] == pytest.approx(1.0) and row["ann_mean_pct"] == pytest.approx(12.0)
    assert row["sharpe"] == pytest.approx(r.mean() / r.std() * np.sqrt(12)) and row["worst_month_pct"] == pytest.approx(-1.0)


def test_prior_market_return_and_bear_flag():
    idx = pd.date_range("2000-01-31", periods=40, freq="ME")
    up = pd.Series(0.01, index=idx)
    p = fc.prior_market_return(up, 24)
    assert np.isnan(p.iloc[0]) and p.iloc[1] == pytest.approx(0.01)  # short history is used at the start
    assert p.iloc[30] == pytest.approx(1.01**24 - 1)  # months t-24..t-1, excluding month t itself
    path = pd.Series([0.05] * 10 + [-0.05] * 30, index=idx)
    p = fc.prior_market_return(path, 24)
    assert (p.iloc[10:20] > 0).all() and p.iloc[39] == pytest.approx(0.95**24 - 1) and p.iloc[39] < 0
    # the flag at month t must not depend on month t's own return
    shocked = path.copy()
    shocked.iloc[39] = 5.0
    assert fc.prior_market_return(shocked, 24).iloc[39] == pytest.approx(p.iloc[39])


def test_mclean_pontiff_windows_partition():
    idx = pd.date_range("1990-01-31", "2010-12-31", freq="ME")
    s = pd.Series(np.arange(len(idx), dtype=float), index=idx)
    spec = fc.PubSpec("T", "1995-01", "1999-12", "2002-06", "test")
    w = fc._mp_windows(s, spec)
    assert w["pre_sample"].index[-1] == pd.Timestamp("1994-12-31")
    assert w["in_sample"].index[0] == pd.Timestamp("1995-01-31") and w["in_sample"].index[-1] == pd.Timestamp("1999-12-31")
    assert w["oos_prepub"].index[0] == pd.Timestamp("2000-01-31") and w["oos_prepub"].index[-1] == pd.Timestamp("2002-05-31")
    assert w["post_pub"].index[0] == pd.Timestamp("2002-06-30") and w["post_pub"].index[-1] == pd.Timestamp("2010-12-31")
    assert sum(len(v) for v in w.values()) == len(s)  # disjoint and exhaustive


def test_md_table_formats_numbers():
    df = pd.DataFrame({"a": ["x", "y"], "n": [3, 4], "v": [1.23456, np.nan]})
    out = fc.md_table(df, {"v": "{:.1f}"})
    assert "| x | 3 | 1.2 |" in out and "| y | 4 | n/a |" in out


def test_shared_hac_agrees_with_private_if_available():
    stats = pytest.importorskip("quant.backtest.stats")
    rng = np.random.default_rng(7)
    X = np.column_stack([np.ones(150), rng.normal(size=150)])
    y = X @ np.array([0.1, 0.5]) + rng.normal(size=150)
    a = stats.ols_hac(y, X, lags=4)
    b = fc._ols_hac_np(y, X, 4)
    np.testing.assert_allclose(a["se"], b["se"], rtol=1e-9)
    np.testing.assert_allclose(a["beta"], b["beta"], rtol=1e-9)
