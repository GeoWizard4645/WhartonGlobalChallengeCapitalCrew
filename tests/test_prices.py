"""Tests for quant/data/prices.py. Offline and fast.

Two groups:
  * synthetic: tiny fake raw stores / frames in tmp_path (no network, no cache needed)
  * real cache: read the built cache/prices parquet files (skipped if the cache is missing)
"""
from __future__ import annotations

import numpy as np
import pandas as pd
import pytest

from quant import settings
from quant.data import prices as P

REAL = all((P.PRICE_DIR / f).exists() for f in ("close.parquet", "adjclose.parquet", "splits.parquet", "meta.parquet", "rf.parquet"))
needs_cache = pytest.mark.skipif(not REAL, reason="price cache not built (run python -m quant.data.prices download)")


# ----------------------------------------------------------------------------------------
# synthetic helpers
# ----------------------------------------------------------------------------------------
def bdays(n, start="2020-01-02"):
    return pd.bdate_range(start, periods=n)


def raw_frame(ticker, dates, prices, adj=None, volume=1000.0, dividend=None, split=None):
    n = len(dates)
    prices = np.asarray(prices, dtype=float)
    adj = prices.copy() if adj is None else np.asarray(adj, dtype=float)
    return pd.DataFrame({
        "yf_ticker": ticker, "date": pd.DatetimeIndex(dates).astype("datetime64[ns]"),
        "open": prices, "close": prices, "adjclose": adj, "volume": np.full(n, volume),
        "dividend": np.zeros(n) if dividend is None else dividend,
        "split": np.zeros(n) if split is None else split,
    })


@pytest.fixture()
def pdir(tmp_path, monkeypatch):
    monkeypatch.setattr(P, "PRICE_DIR", tmp_path)
    monkeypatch.setattr(P, "MIN_TICKERS_PER_DATE", 2)
    P._splits_cache.clear()
    yield tmp_path
    P._splits_cache.clear()


# ----------------------------------------------------------------------------------------
# small pure functions
# ----------------------------------------------------------------------------------------
def test_normalize_ticker():
    assert P.normalize_ticker("brk.b") == "BRK-B"
    assert P.normalize_ticker(" BF.B ") == "BF-B"
    assert P.normalize_ticker("^IRX") == "^IRX"
    assert P.normalize_ticker("") is None
    assert P.normalize_ticker(None) is None
    assert P.normalize_ticker("NOT A TICKER!!") is None
    assert P._norm_list(["aapl", "AAPL", "BRK.B", None, "x y z!"]) == ["AAPL", "BRK-B"]


def test_classify_error():
    assert P.classify_error("YFRateLimitError('Too Many Requests. Rate limited.')") == "error"
    assert P.classify_error("ReadTimeout: timed out") == "error"
    assert P.classify_error("curl: (28) Operation timed out") == "error"
    assert P.classify_error("possibly delisted; no timezone found") == "empty"
    assert P.classify_error("$ZZZ: possibly delisted; no price data found") == "empty"
    assert P.classify_error(None) == "empty"


@pytest.mark.parametrize("ratio,expected", [
    (2.0, True), (3.0, True), (1.5, True), (4.0, True), (10.0, True), (7.0, True), (0.5, True), (0.1, True),
    (1.25, True), (5 / 4, True), (3 / 2, True), (20.0, True), (0.05, True),
    (25.0, True), (0.04, True), (0.02, True), (0.01, True), (100.0, True),   # N / 1/N rule beyond 20
    (2.044, False), (2.0842, False), (1.03, False), (1.0, False), (1.0027, False), (0.0, False), (-2.0, False),
    (np.nan, False), (1.3197, False),
])
def test_is_genuine_split(ratio, expected):
    assert bool(P.is_genuine_split(ratio)[0]) is expected


def test_is_genuine_split_tolerance():
    assert P.is_genuine_split(2.009)[0]          # within 0.5%
    assert not P.is_genuine_split(2.02)[0]       # 1% off


def test_compute_returns_bridges_short_gaps_only():
    idx = bdays(30)
    p = pd.DataFrame({"A": 100.0 * np.arange(1, 31) ** 0.0}, index=idx)
    p["A"] = np.linspace(100, 130, 30)
    p.loc[idx[10:12], "A"] = np.nan                       # 2-bar gap: bridged
    p.loc[idx[20:27], "A"] = np.nan                       # 7-bar gap: not bridged
    r = P.compute_returns(p)["A"]
    assert r.iloc[0] != r.iloc[0]                         # first obs NaN
    assert np.isnan(r.iloc[10]) and np.isnan(r.iloc[11])  # NaN where price is missing
    assert r.iloc[12] == pytest.approx(p["A"].iloc[12] / p["A"].iloc[9] - 1)
    assert np.isnan(r.iloc[27])                           # gap longer than MAX_BRIDGE
    assert r.iloc[28] == pytest.approx(p["A"].iloc[28] / p["A"].iloc[27] - 1)


def test_remove_spikes_up_down_and_keeps_level_shifts():
    idx = bdays(60)
    base = np.full(60, 50.0)
    up = base.copy(); up[20] = 500.0                      # +900% then -90%: bad tick
    down = base.copy(); down[30] = 2.0                    # -96% then +2400%: bad tick
    step = base.copy(); step[40:] = 250.0                 # +400% permanent: real (not reversed)
    modest = base.copy(); modest[10] = 100.0              # +100% then -50%: below threshold, kept
    P_ = pd.DataFrame({"up": up, "down": down, "step": step, "modest": modest}, index=idx)
    cleaned, log = P.remove_spikes(P_, "close")
    assert np.isnan(cleaned["up"].iloc[20]) and cleaned["up"].isna().sum() == 1
    assert np.isnan(cleaned["down"].iloc[30]) and cleaned["down"].isna().sum() == 1
    assert cleaned["step"].isna().sum() == 0
    assert cleaned["modest"].isna().sum() == 0
    assert sorted(log["yf_ticker"]) == ["down", "up"]
    assert set(log["rule"]) == {"R5_bad_tick"}
    # returns after cleaning: the bad day is NaN, the next return is the bridged (flat) one
    r = P.compute_returns(cleaned)
    assert np.isnan(r["up"].iloc[20])
    assert r["up"].iloc[21] == pytest.approx(0.0)
    assert r["step"].iloc[40] == pytest.approx(4.0)


def test_remove_spikes_needs_reversal():
    idx = bdays(30)
    p = pd.DataFrame({"x": np.full(30, 10.0)}, index=idx)
    p.iloc[10, 0] = 80.0                                   # +700%
    p.iloc[11, 0] = 60.0                                   # only -25%: not a reversal -> kept (jump is "real")
    p.iloc[12:, 0] = 60.0
    cleaned, log = P.remove_spikes(p, "close")
    assert cleaned["x"].isna().sum() == 0 and len(log) == 0


def test_clean_long_rules(monkeypatch):
    monkeypatch.setattr(P, "MIN_TICKERS_PER_DATE", 1)
    d = bdays(10)
    a = raw_frame("A", d, np.linspace(10, 11, 10))
    b = raw_frame("B", d, np.linspace(20, 21, 10))
    a.loc[2, "close"] = -1.0                               # R1: no usable close -> row dropped
    b.loc[3, "adjclose"] = -5.0                            # R1: valid close, bad adj -> rebuilt
    b.loc[4, "adjclose"] = np.nan
    a.loc[5, "open"] = 0.0                                 # R2
    b.loc[6, "volume"] = -3.0                              # R2
    dup = a.iloc[[7]].copy(); dup["close"] = 99.0; dup["adjclose"] = 99.0
    L = pd.concat([a, b, dup, raw_frame("C", d[:1], [5.0])], ignore_index=True)
    # rows with both NaN are dropped silently
    L.loc[len(L)] = ["A", d[-1] + pd.Timedelta(days=1), np.nan, np.nan, np.nan, np.nan, 0.0, 0.0]
    out, log = P.clean_long(L)
    assert not ((out["close"] <= 0) | (out["adjclose"] <= 0)).any()
    assert not ((out["yf_ticker"] == "A") & (out["date"] == d[2])).any()
    bad = out[(out["yf_ticker"] == "B") & (out["date"].isin([d[3], d[4]]))]
    assert len(bad) == 2 and (bad["adjclose"] > 0).all()
    assert bad["adjclose"].tolist() == pytest.approx(bad["close"].tolist())   # neighbour ratio is 1
    assert np.isnan(out[(out["yf_ticker"] == "A") & (out["date"] == d[5])]["open"]).all()
    assert np.isnan(out[(out["yf_ticker"] == "B") & (out["date"] == d[6])]["volume"]).all()
    a7 = out[(out["yf_ticker"] == "A") & (out["date"] == d[7])]
    assert len(a7) == 1 and a7["close"].iloc[0] == 99.0     # last duplicate wins
    assert {"R1_bad_price_row", "R1_adjclose_rebuilt", "R2_bad_open", "R2_bad_volume", "R3_duplicate"} <= set(log["rule"])


def test_clean_long_off_calendar_dates(pdir):
    d = bdays(5)
    L = pd.concat([raw_frame("A", d, [1, 2, 3, 4, 5]), raw_frame("B", d[:4], [1, 2, 3, 4])], ignore_index=True)
    out, log = P.clean_long(L)
    assert d[4] not in set(out["date"])                     # only A traded: below MIN_TICKERS_PER_DATE
    assert "R4_off_calendar" in set(log["rule"])


def test_repair_unadjusted_splits():
    d = bdays(40)
    px = np.r_[np.full(20, 0.33), np.full(20, 16.5)]        # 1:50 reverse split on d[20], history NOT re-based
    a = raw_frame("REV", d, px, volume=np.r_[np.full(20, 1e6), np.full(20, 2e4)])
    ok = raw_frame("OK", d, np.full(40, 10.0))               # properly adjusted 2:1 split: continuous
    L = pd.concat([a, ok], ignore_index=True)
    sp = pd.DataFrame({"yf_ticker": ["REV", "OK"], "date": [d[20], d[20]], "ratio": [0.02, 2.0]})
    out, log = P.repair_unadjusted_splits(L, sp)
    rev = out[out["yf_ticker"] == "REV"].sort_values("date")
    assert rev["close"].tolist() == pytest.approx([16.5] * 40)
    assert rev["adjclose"].tolist() == pytest.approx([16.5] * 40)
    assert rev["volume"].iloc[0] == pytest.approx(1e6 * 0.02)
    assert (out[out["yf_ticker"] == "OK"]["close"] == 10.0).all()
    assert list(log["yf_ticker"]) == ["REV"] and log["rule"].iloc[0] == "R7_unadjusted_split"


# ----------------------------------------------------------------------------------------
# split factors (synthetic splits table)
# ----------------------------------------------------------------------------------------
def write_splits(pdir, rows):
    df = pd.DataFrame(rows, columns=["yf_ticker", "date", "ratio"])
    df["date"] = pd.to_datetime(df["date"]).astype("datetime64[ns]")
    df["genuine"] = P.is_genuine_split(df["ratio"].to_numpy())
    P._atomic_df(df, pdir / "splits.parquet")
    P._splits_cache.clear()


def test_split_factor_after_semantics(pdir):
    write_splits(pdir, [
        ("AAPL", "2014-06-09", 7.0), ("AAPL", "2020-08-31", 4.0),
        ("NVDA", "2021-07-20", 4.0), ("NVDA", "2024-06-10", 10.0),
        ("ASH", "2017-05-15", 2.044),                       # spin-off artefact: not genuine
        ("REV", "2022-01-03", 0.1),
    ])
    f = P.split_factor_after
    assert f("NVDA", "2024-01-01") == 10
    assert f("NVDA", "2021-01-01") == 40
    assert f("AAPL", "2019-01-01") == 4
    assert f("AAPL", "2013-01-01") == 28
    assert f("AAPL", "2020-08-31") == 1                     # strictly after: the ex-date itself is excluded
    assert f("AAPL", "2020-08-30") == 4
    assert f("NVDA", "2025-01-01") == 1
    assert f("UNKNOWN", "2010-01-01") == 1
    assert f("REV", "2021-12-31") == pytest.approx(0.1)
    assert f("ASH", "2010-01-01") == 1                      # genuine only by default
    assert f("ASH", "2010-01-01", genuine_only=False) == pytest.approx(2.044)
    assert f("BRK.B", "2010-01-01") == 1                    # normalisation does not crash
    v = P.split_factors_after(["NVDA", "AAPL", "ZZZ", "ASH"], ["2024-01-01", "2019-01-01", "2010-01-01", "2010-01-01"])
    assert v.tolist() == [10.0, 4.0, 1.0, 1.0]
    v = P.split_factors_after(["NVDA", "AAPL"], "2013-01-01")      # scalar date broadcasts
    assert v.tolist() == [40.0, 28.0]
    v = P.split_factors_after("NVDA", pd.to_datetime(["2020-01-01", "2022-01-01", "2025-01-01"]))
    assert v.tolist() == [40.0, 10.0, 1.0]
    v = P.split_factors_after(["NVDA", "NVDA"], [pd.NaT, "2022-01-01"])
    assert np.isnan(v[0]) and v[1] == 10.0


def test_split_factors_after_no_file(pdir):
    assert P.split_factor_after("AAPL", "2010-01-01") == 1.0


# ----------------------------------------------------------------------------------------
# raw store + rebuild end to end (synthetic)
# ----------------------------------------------------------------------------------------
def test_raw_store_resolution_full_replaces_upd_upserts(pdir):
    d = bdays(10)
    P._write_segment(pd.concat([raw_frame("A", d, np.arange(1, 11)), raw_frame("B", d, np.arange(11, 21))], ignore_index=True), "full")
    # upd for A: revise day 9 and add day 11
    new_d = pd.DatetimeIndex([d[9], d[9] + pd.offsets.BDay(1)])
    P._write_segment(raw_frame("A", new_d, [100.0, 101.0]), "upd")
    # full for B replaces everything (shorter history)
    P._write_segment(raw_frame("B", d[:3], [7.0, 8.0, 9.0]), "full")
    L = P._read_resolved_long()
    a = L[L["yf_ticker"] == "A"].sort_values("date")
    b = L[L["yf_ticker"] == "B"].sort_values("date")
    assert len(a) == 11 and a["close"].iloc[9] == 100.0 and a["close"].iloc[10] == 101.0
    assert b["close"].tolist() == [7.0, 8.0, 9.0]
    # compaction through rebuild leaves the same data in base.parquet and no segments
    P.rebuild_outputs()
    assert P._list_segments() == []
    L2 = P._read_resolved_long()
    assert len(L2) == len(L)
    assert sorted(zip(L2["yf_ticker"], L2["date"], L2["close"])) == sorted(zip(L["yf_ticker"], L["date"], L["close"]))


def test_rebuild_outputs_end_to_end(pdir):
    d = bdays(60)
    spike = np.full(60, 20.0); spike[30] = 400.0
    split_px = np.full(60, 12.5)                              # properly adjusted 4:1 split at d[30] (history re-based)
    split_col = np.zeros(60); split_col[30] = 4.0
    spin = np.zeros(60); spin[40] = 2.044
    frames = [
        raw_frame("AAA", d, np.linspace(10, 12, 60), adj=np.linspace(9, 12, 60), dividend=np.r_[np.zeros(59), 0.1]),
        raw_frame("SPK", d, spike),
        raw_frame("SPL", d, split_px, split=split_col),
        raw_frame("SPN", d, np.full(60, 30.0), split=spin),
        raw_frame("SHORT", d[40:], np.full(20, 5.0)),
    ]
    P._write_segment(pd.concat(frames, ignore_index=True), "full")
    att = pd.DataFrame({"status": ["ok"] * 5 + ["empty", "error"], "note": [""] * 5 + ["possibly delisted", "timeout"],
                        "n_attempts": [1] * 5 + [1, 3], "last_attempt": ["x"] * 7},
                       index=pd.Index(["AAA", "SHORT", "SPK", "SPL", "SPN", "DEAD", "FLAKY"], name="yf_ticker"))
    P._save_attempts(att)
    summ = P.rebuild_outputs()
    assert summ["tickers"] == 5 and summ["dates"] == 60
    close = P.load_close()
    assert str(close.index.dtype) == "datetime64[ns]" and close.index.name == "date"
    assert list(close.columns) == ["AAA", "SHORT", "SPK", "SPL", "SPN"]
    assert (close.dtypes == "float64").all()
    assert np.isnan(close["SPK"].iloc[30]) and close["SPK"].notna().sum() == 59        # R5
    assert close["SHORT"].iloc[:40].isna().all() and close["SHORT"].iloc[40:].notna().all()   # no fills
    adj = P.load_adjclose(["AAA"])
    assert list(adj.columns) == ["AAA"] and (adj["AAA"] <= close["AAA"] + 1e-12).all()
    ret = P.load_returns()
    assert np.isnan(ret["SPK"].iloc[30]) and ret["SPK"].iloc[31] == pytest.approx(0.0)
    assert ret["SHORT"].iloc[:41].isna().all()
    assert abs(ret["SPL"].iloc[30]) < 1e-9                                              # continuous across the split
    assert P.load_open(["AAA", "NOPE"]).columns.tolist() == ["AAA"]                    # unknown tickers ignored
    assert P.load_volume().shape == close.shape
    assert P.load_close(start="2020-03-01", end="2020-03-31").index.min() >= pd.Timestamp("2020-03-01")
    sp = P.load_splits()
    assert sp.set_index("yf_ticker")["ratio"].to_dict() == {"SPL": 4.0, "SPN": 2.044}
    assert sp.set_index("yf_ticker")["genuine"].to_dict() == {"SPL": True, "SPN": False}
    assert P.split_factor_after("SPL", d[0]) == 4.0 and P.split_factor_after("SPN", d[0]) == 1.0
    meta = P.load_meta().set_index("yf_ticker")
    assert meta["status"].to_dict() == {"AAA": "ok", "DEAD": "empty", "FLAKY": "error", "SHORT": "ok", "SPK": "ok", "SPL": "ok", "SPN": "ok"}
    assert meta.loc["AAA", "n_obs"] == 60 and meta.loc["SHORT", "n_obs"] == 20 and meta.loc["DEAD", "n_obs"] == 0
    assert meta.loc["SPK", "n_obs"] == 59
    assert meta.loc["SHORT", "first_date"] == d[40] and meta.loc["AAA", "last_date"] == d[-1]
    assert "non-genuine" in meta.loc["SPN", "note"]
    for col in ("yf_ticker", "first_date", "last_date", "n_obs", "status", "note"):
        assert col in P.load_meta().columns
    log = pd.read_csv(pdir / "cleaning_log.csv")
    assert (log["rule"] == "R5_bad_tick").sum() == 2 and set(log["yf_ticker"]) == {"SPK"}
    assert list(log.columns) == P.LOG_COLS


def test_download_ledger_with_mocked_fetch(pdir, monkeypatch):
    d = bdays(50)
    calls = []

    def fake_fetch(tickers, start, end, timeout=30):
        calls.append(list(tickers))
        frames, errs = {}, {}
        for t in tickers:
            if t.startswith("OK"):
                frames[t] = raw_frame(t, d, np.linspace(10, 11, 50))
            elif t.startswith("EMP"):
                frames[t], errs[t] = None, "possibly delisted; no timezone found"
            else:
                frames[t], errs[t] = None, "YFRateLimitError('Too Many Requests')"
        return frames, errs

    monkeypatch.setattr(P, "_fetch", fake_fetch)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    tk = ["OK1", "OK2", "OK3", "EMP1", "ERR1"]
    s = P.download(tk, batch_size=2)
    assert (s["ok"], s["empty"], s["error"]) == (3, 1, 1)
    att = P._load_attempts()
    assert att.loc["OK1", "status"] == "ok" and att.loc["EMP1", "status"] == "empty" and att.loc["ERR1", "status"] == "error"
    assert P.load_meta().set_index("yf_ticker").loc["ERR1", "status"] == "error"
    n_calls = len(calls)
    # second run: ok/empty are never re-downloaded; the error ticker is retried (up to MAX_ERROR_ATTEMPTS runs)
    s = P.download(tk, batch_size=2)
    assert s["todo"] == 1 and calls[-1] == ["ERR1"]
    s = P.download(tk, batch_size=2)
    assert s["todo"] == 1
    s = P.download(tk, batch_size=2)
    assert s["todo"] == 0                                    # 3 attempts used
    assert P._load_attempts().loc["ERR1", "n_attempts"] == 3
    # retry_empty re-tries empties once
    assert P.download(tk, retry_empty=True)["todo"] == 1
    assert P.download(tk, retry_empty=True)["todo"] == 0
    # force re-downloads everything (full segments replace; no duplicate rows)
    s = P.download(["OK1", "OK2"], force=True)
    assert s["todo"] == 2
    assert P.load_close().shape == (50, 3)
    # max_tickers limits a chunk
    s = P.download(["OK7", "OK8", "OK9"], max_tickers=2)
    assert s["todo"] == 2


def test_update_detects_rebased_history(pdir, monkeypatch):
    """Overlap identical -> upsert only the new rows; overlap changed (dividend/split re-base) -> full re-download."""
    d = bdays(80)
    cut = 70                                                # cache holds d[:70]
    base_a = np.linspace(10, 20, 80)
    base_b = np.linspace(30, 40, 80)
    P._write_segment(pd.concat([raw_frame("A", d[:cut], base_a[:cut]), raw_frame("B", d[:cut], base_b[:cut])], ignore_index=True), "full")
    P._save_attempts(pd.DataFrame({"status": ["ok", "ok"], "note": ["", ""], "n_attempts": [1, 1], "last_attempt": ["x", "x"]},
                                  index=pd.Index(["A", "B"], name="yf_ticker")))
    P.rebuild_outputs()
    fetched = []

    def fake_fetch(tickers, start, end, timeout=30):
        fetched.append((list(tickers), pd.Timestamp(start)))
        frames = {}
        for t in tickers:
            full_start = pd.Timestamp(start) <= d[0]
            sel = d >= pd.Timestamp(start)
            if t == "A":
                frames[t] = raw_frame("A", d[sel], base_a[sel])
            else:                                            # B: Yahoo re-based the whole history (dividend)
                frames[t] = raw_frame("B", d[sel], base_b[sel] * 0.98, adj=base_b[sel] * 0.98)
        return frames, {}

    monkeypatch.setattr(P, "_fetch", fake_fetch)
    monkeypatch.setattr(P.time, "sleep", lambda s: None)
    monkeypatch.setattr(P, "_market_partial_date", lambda: None)
    monkeypatch.setattr(P, "build_rf", lambda *a, **k: None)
    out = P.update(through=d[-1], include_new=False)
    assert out["active"] == 2 and out["refresh"] == 1
    assert out["refresh_run"]["ok"] == 1
    close = P.load_close()
    assert close.index[-1] == d[-1] and len(close) == 80
    assert close["A"].iloc[-1] == pytest.approx(base_a[-1])
    assert close["B"].iloc[0] == pytest.approx(base_b[0] * 0.98)    # whole history replaced
    assert any(f[1] <= d[0] for f in fetched[1:])                  # the refresh fetched from the start


def test_partial_bar_guard(monkeypatch):
    import datetime as dt
    from zoneinfo import ZoneInfo

    class FakeDT(dt.datetime):
        _now = None

        @classmethod
        def now(cls, tz=None):
            return cls._now

    monkeypatch.setattr(P.dt, "datetime", FakeDT)
    ny = ZoneInfo("America/New_York")
    FakeDT._now = dt.datetime(2026, 10, 20, 15, 0, tzinfo=ny)         # Tue 15:00: market open
    assert P._market_partial_date() == pd.Timestamp("2026-10-20")
    FakeDT._now = dt.datetime(2026, 10, 20, 18, 30, tzinfo=ny)        # Tue evening: final
    assert P._market_partial_date() is None
    FakeDT._now = dt.datetime(2026, 10, 18, 12, 0, tzinfo=ny)         # Sunday
    assert P._market_partial_date() is None


def test_lock_is_exclusive_across_handles(pdir):
    import fcntl

    with P._lock():
        with P._lock():                                              # re-entrant in-process
            pass
        f = open(pdir / ".lock", "w")
        with pytest.raises(BlockingIOError):
            fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
        f.close()


def test_atomic_write_leaves_no_tmp(pdir):
    P._atomic_df(pd.DataFrame({"a": [1, 2]}), pdir / "x.parquet")
    assert [p.name for p in pdir.iterdir() if p.name != ".lock"] == ["x.parquet"]


def test_read_price_tickers_and_default_list(tmp_path, monkeypatch):
    f = tmp_path / "price_tickers.txt"
    f.write_text("aapl\n\nBRK.B  # class B\n# comment\nmsft\n")
    monkeypatch.setattr(P, "TICKER_FILE", f)
    assert P.read_price_tickers() == ["AAPL", "BRK-B", "MSFT"]
    monkeypatch.setattr(P, "sec_tickers", lambda: ["ZZZ"])
    dl = P.default_tickers()
    for b in settings.BENCHMARKS:
        assert b in dl
    assert {"AAPL", "BRK-B", "ZZZ"} <= set(dl) and len(dl) == len(set(dl))
    monkeypatch.setattr(P, "TICKER_FILE", tmp_path / "missing.txt")
    assert P.read_price_tickers() == []


def test_fetch_resilient_retries_transient_errors_with_backoff(monkeypatch):
    d = bdays(20)
    sleeps, state = [], {"n": 0}

    def fake_fetch(tickers, start, end, timeout=30):
        state["n"] += 1
        frames, errs = {}, {}
        for t in tickers:
            if t == "GOOD":
                frames[t] = raw_frame(t, d, np.linspace(1, 2, 20))
            elif t == "FLAKY" and state["n"] >= 2:
                frames[t] = raw_frame(t, d, np.linspace(1, 2, 20))
            elif t == "DEAD":
                frames[t], errs[t] = None, "possibly delisted; no timezone found"
            else:
                frames[t], errs[t] = None, "YFRateLimitError('Too Many Requests')"
        return frames, errs

    monkeypatch.setattr(P, "_fetch", fake_fetch)
    monkeypatch.setattr(P.time, "sleep", lambda s: sleeps.append(s))
    res = P._fetch_resilient(["GOOD", "FLAKY", "DEAD", "NEVER"], "2007-01-01", None, max_rounds=3)
    assert res["GOOD"][0] == "ok" and res["FLAKY"][0] == "ok"
    assert res["DEAD"][0] == "empty"                       # Yahoo "nothing" is final, no retry
    assert res["NEVER"][0] == "error"                      # still failing after the last round
    assert len(sleeps) == 2 and sleeps[1] > sleeps[0]      # exponential backoff between rounds
    assert state["n"] == 3
    # a whole-call exception is treated as transient for every ticker
    monkeypatch.setattr(P, "_fetch", lambda *a, **k: (_ for _ in ()).throw(ConnectionError("down")))
    res = P._fetch_resilient(["A", "B"], "2007-01-01", None, max_rounds=2)
    assert {v[0] for v in res.values()} == {"error"}


def test_audit_runs_on_real_cache_to_tmp(tmp_path):
    if not REAL:
        pytest.skip("price cache not built")
    out = tmp_path / "cov.md"
    text = P.audit(out)
    assert out.exists() and "## 2. Validation" in text and "FAIL" not in text


# ----------------------------------------------------------------------------------------
# real cache
# ----------------------------------------------------------------------------------------
@pytest.fixture(scope="module")
def real():
    cols = ["SPY", "AAPL", "NVDA", "KO", "JNJ", "PG", "XOM", "MSFT", "PEP", "WMT", "MCD", "T"]
    return {"close": P.load_close(cols), "adj": P.load_adjclose(cols), "splits": P.load_splits(), "meta": P.load_meta(),
            "rf": P.load_rf()}


@needs_cache
def test_real_aapl_nvda_splits_present(real):
    sp = real["splits"]
    for tk, d, r in (("AAPL", "2020-08-31", 4.0), ("AAPL", "2014-06-09", 7.0), ("NVDA", "2024-06-10", 10.0)):
        row = sp[(sp["yf_ticker"] == tk) & (sp["date"] == pd.Timestamp(d))]
        assert len(row) == 1 and row["ratio"].iloc[0] == pytest.approx(r) and bool(row["genuine"].iloc[0])
    assert list(sp.columns[:3]) == ["yf_ticker", "date", "ratio"] and "genuine" in sp.columns
    assert str(sp["date"].dtype) == "datetime64[ns]"


@needs_cache
def test_real_close_continuous_across_splits(real):
    c = real["close"]
    for tk, d in (("AAPL", "2020-08-31"), ("NVDA", "2024-06-10")):
        d = pd.Timestamp(d)
        before = c[tk].loc[:d - pd.Timedelta(days=1)].dropna().iloc[-1]
        on = c[tk].loc[d]
        assert abs(on / before - 1) < 0.15                       # unadjusted data would show -75% / -90%


@needs_cache
def test_real_split_factors(real):
    assert P.split_factor_after("NVDA", "2024-01-01") == 10
    assert P.split_factor_after("AAPL", "2019-01-01") == 4          # 7:1 (2014) is before, 4:1 (2020) after
    assert P.split_factor_after("AAPL", "2013-01-01") == 28
    assert P.split_factor_after("AAPL", "2020-08-31") == 1
    assert P.split_factor_after("NVDA", "2021-01-01") == 40
    v = P.split_factors_after(["NVDA", "AAPL", "KO"], ["2024-01-01", "2019-01-01", "2024-01-01"])
    assert v[0] == 10 and v[1] == 4 and v[2] == 1
    ash = P.split_factor_after("ASH", "2010-01-01", genuine_only=False)
    assert ash == pytest.approx(P.split_factor_after("ASH", "2010-01-01") * 2.044)   # spin-off artefact only in the all-splits factor


@needs_cache
def test_real_adjclose_not_above_close_for_dividend_payers(real):
    for tk in ("KO", "JNJ", "PG", "XOM", "MSFT", "PEP", "WMT", "MCD", "SPY", "T"):
        ratio = (real["adj"][tk] / real["close"][tk]).dropna()
        assert (ratio <= 1 + 1e-6).mean() > 0.999, tk
        assert ratio.iloc[-1] == pytest.approx(1.0)                  # re-based at the latest bar
        assert ratio.iloc[0] < 0.99                                  # dividends compounded since 2007


@needs_cache
def test_real_spy_total_return_cagr(real):
    s = real["adj"]["SPY"].loc["2014-12-31":"2024-12-31"].dropna()
    cagr = (s.iloc[-1] / s.iloc[0]) ** (365.25 / (s.index[-1] - s.index[0]).days) - 1
    assert abs(cagr - 0.13) < 0.005, cagr


@needs_cache
def test_real_matrix_shape_dtypes_and_benchmarks():
    c = P.load_close()
    assert str(c.index.dtype) == "datetime64[ns]" and c.index.is_monotonic_increasing and c.index.is_unique
    assert c.columns.is_unique and (c.dtypes == "float64").all()
    assert c.index[0] <= pd.Timestamp("2007-01-05") and c.index[-1] >= pd.Timestamp("2026-10-16")
    for b in settings.BENCHMARKS:
        assert b in c.columns and c[b].notna().sum() > 1000
    arr = c.to_numpy()
    assert ((arr > 0) | np.isnan(arr)).all()                         # never zero or negative
    assert c["SPY"].isna().sum() == 0                                # SPY defines the calendar
    # no forward fill: a delisted-style series ends with NaN (e.g. a ticker that stopped trading)
    m = P.load_meta()
    stale = m[(m["status"] == "ok") & (m["last_date"] < c.index[-1] - pd.Timedelta(days=30))]
    if len(stale):
        t = stale["yf_ticker"].iloc[0]
        assert c[t].iloc[-1] != c[t].iloc[-1]


@needs_cache
def test_real_matrices_aligned_and_returns_consistent():
    cols = ["SPY", "AAPL", "KO"]
    mats = {n: getattr(P, f"load_{n}")(cols) for n in ("close", "adjclose", "open", "volume", "returns")}
    ref = mats["close"]
    for n, m in mats.items():
        assert m.index.equals(ref.index) and list(m.columns) == list(ref.columns), n
    r = mats["returns"]["SPY"]
    exp = mats["adjclose"]["SPY"].pct_change(fill_method=None)
    assert np.allclose(r.iloc[1:], exp.iloc[1:], equal_nan=True, atol=1e-12)
    assert (mats["volume"]["SPY"].dropna() >= 0).all()


@needs_cache
def test_real_no_residual_bad_ticks():
    for name in ("adjclose", "close"):
        mask = P._spike_mask(getattr(P, f"load_{name}")())
        assert int(mask.to_numpy().sum()) == 0, name           # the filter is idempotent on the cleaned matrices


@needs_cache
def test_real_meta_consistent_with_matrix():
    m = P.load_meta()
    assert m["yf_ticker"].is_unique
    assert set(m["status"]) <= {"ok", "empty", "error"}
    for col in ("yf_ticker", "first_date", "last_date", "n_obs", "status", "note"):
        assert col in m.columns
    c = P.load_close()
    ok = m[m["status"] == "ok"].set_index("yf_ticker")
    assert set(ok.index) == set(c.columns)
    cnt = c.notna().sum()
    assert (cnt.reindex(ok.index) == ok["n_obs"]).all()
    assert (m[m["status"] != "ok"]["n_obs"] == 0).all()
    t = "SPY"
    assert ok.loc[t, "first_date"] == c[t].first_valid_index() and ok.loc[t, "last_date"] == c[t].last_valid_index()


@needs_cache
def test_real_rf(real):
    rf = real["rf"]
    c = P.load_close(["SPY"])
    assert rf.index.equals(c.index) and list(rf.columns) == ["rf_annual", "rf_daily"]
    assert rf["rf_annual"].notna().all()
    assert rf["rf_annual"].between(-0.01, 0.12).all()     # DTB3 was slightly negative in 2015/2020
    assert np.allclose(rf["rf_daily"], rf["rf_annual"] / 252)
    assert P.rf_daily().equals(rf["rf_daily"])
    assert abs(rf["rf_annual"].loc["2021-06-01"] - 0.0005) < 0.0015    # near-zero rates in 2021
    assert 0.03 < rf["rf_annual"].iloc[-1] < 0.06


@needs_cache
def test_real_cleaning_log_schema():
    log = pd.read_csv(P.PRICE_DIR / "cleaning_log.csv")
    assert list(log.columns) == P.LOG_COLS
    assert set(log["rule"]) <= {"R1_bad_price_row", "R1_adjclose_rebuilt", "R2_bad_open", "R2_bad_volume", "R3_duplicate",
                                "R4_off_calendar", "R5_bad_tick", "R7_unadjusted_split"}
