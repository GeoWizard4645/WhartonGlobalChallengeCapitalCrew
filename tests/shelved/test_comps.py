"""Tests for quant/signals/comps.py on hand-made synthetic universes (no data layer needed)."""
from __future__ import annotations

import math

import numpy as np
import pandas as pd
import pytest

from quant.shelved import comps as C

D0 = pd.Timestamp("2020-06-30")


# --------------------------------------------------------------------------------------------------
# synthetic universe helpers (also used by tests/test_trading_comps.py)
# --------------------------------------------------------------------------------------------------
def comp(t, sub="S1", ind="I1", sector="Industrials", mc=1000.0, pe=15.0, ev=10.0, age=60, price=50.0, **kw):
    """One company row.  ``pe``/``ev`` are the multiples: debt = cash = 0 so EV = mcap, NI = mc/pe, EBITDA = mc/ev.
    ``pe=-5`` gives a loss-maker (negative net income), ``pe=None`` a missing net income."""
    ni = None if pe is None else mc / pe
    eb = None if ev is None else mc / ev
    row = dict(yf_ticker=t, name=f"{t} Corp", gics_sector=sector, gics_industry_group="G", gics_industry=ind,
               gics_sub_industry=sub, sub_industry_code=sub, industry_code=ind, mcap=mc, price=price,
               net_income=ni, ebitda=eb, net_income_lfy=ni, ebitda_lfy=eb, total_debt=0.0, cash=0.0,
               preferred=0.0, minority_interest=0.0, st_investments=0.0, age=age)
    row.update(kw)
    return row


class FakeCtx:
    """Duck-typed DataContext: universe / fundamentals / market_cap / trading_day_on_or_before (+ prices).

    ``rows_by_date`` = {date: rows} replaces the company table from that date on (ciks are stable per ticker).
    """

    def __init__(self, rows, date=D0, splits=None, ndays=900, seed=0, rows_by_date=None):
        tickers: list = []
        for r in list(rows) + [x for rs in (rows_by_date or {}).values() for x in rs]:
            if r["yf_ticker"] not in tickers:
                tickers.append(r["yf_ticker"])
        self.cik_of = {t: 1000 + i for i, t in enumerate(tickers)}
        self._frames = [(pd.Timestamp("1900-01-01"), self._mk(rows))]
        for d, rs in sorted((rows_by_date or {}).items()):
            self._frames.append((pd.Timestamp(d), self._mk(rs)))
        self.df = self._frames[0][1]
        self.date = pd.Timestamp(date)
        self.splits = splits or {}
        self.dates = pd.bdate_range(end=self.date + pd.Timedelta(days=380), periods=ndays)
        rng = np.random.default_rng(seed)
        self.close = pd.DataFrame(50.0 + rng.normal(0, 0.1, (ndays, len(tickers))).cumsum(0), index=self.dates,
                                  columns=tickers)
        self.returns = self.close.pct_change()
        self.rf = pd.Series(0.00005, index=self.dates)
        self.fund_calls = 0
        self.universe_names: list = []

    def _mk(self, rows):
        df = pd.DataFrame(rows)
        df.insert(0, "cik", [self.cik_of[t] for t in df["yf_ticker"]])
        return df

    def _df(self, date):
        date = pd.Timestamp(date)
        cur = self._frames[0][1]
        for d, f in self._frames:
            if d <= date:
                cur = f
        return cur

    # -- DataContext surface used by the strategy ---------------------------------------------------
    def trading_day_on_or_before(self, date):
        date = pd.Timestamp(date)
        i = self.dates.searchsorted(date, side="right") - 1
        return self.dates[i]

    def month_ends(self, start, end):
        d = self.dates[(self.dates >= pd.Timestamp(start)) & (self.dates <= pd.Timestamp(end))]
        s = pd.Series(d, index=d)
        return list(s.groupby([d.year, d.month]).max())

    def universe(self, date, name="SP1500"):
        self.universe_names.append(name)
        df = self._df(date)
        cols = [c for c in ("cik", "yf_ticker", "name", "gics_sector", "gics_industry_group", "gics_industry",
                            "gics_sub_industry", "sub_industry_code", "industry_code") if c in df.columns]
        return df[cols].copy().reset_index(drop=True)

    def fundamentals(self, date, max_age_days=200):
        self.fund_calls += 1
        date = pd.Timestamp(date)
        df = self._df(date).set_index("cik")
        f = df[["net_income", "ebitda", "net_income_lfy", "ebitda_lfy", "total_debt", "cash",
                "preferred", "minority_interest", "st_investments"]].copy()
        f["period_end"] = date - pd.to_timedelta(df["age"], unit="D")
        f["filed"] = f["period_end"] + pd.Timedelta(days=30)
        return f

    def market_cap(self, date, univ=None, max_age_days=200):
        d = self._df(date).set_index("cik")
        if univ is not None:
            d = d.loc[d.index.intersection(univ["cik"])]
        out = pd.DataFrame({"yf_ticker": d["yf_ticker"], "price": d["price"],
                            "shares_today_basis": d["mcap"] / d["price"], "mcap": d["mcap"]})
        return out

    def split_factor_after(self, ticker, d):
        return float(self.splits.get(ticker, 1.0))


def make_ctx(rows, **kw):
    return FakeCtx(rows, **kw)


def run_signals(rows, params=None, km=None, return_peers=True, ctx=None):
    ctx = ctx or make_ctx(rows)
    univ = ctx.universe(D0)
    mt = C.multiples_table(ctx, D0, univ, (params or {}).get("basis", "TTM"))
    sig = C.comps_signals(ctx, D0, univ, params or {}, km, mt=mt, return_peers=return_peers)
    sig = sig.set_index("yf_ticker", drop=False)
    return ctx, mt, sig


def km_frame(ctx, **overrides):
    """key-metric table with every gate open; ``overrides`` = {ticker: {col: value}}."""
    d = ctx.df
    km = pd.DataFrame(index=pd.Index(d["cik"], name="cik"))
    km["yf_ticker"] = d["yf_ticker"].to_numpy()
    for c, v in (("pass_leverage", True), ("quality_ok", True), ("pass_roic", True),
                 ("recent_ipo", False), ("recent_merger", False)):
        km[c] = v
    km["nd_ebitda"] = 1.0
    for tk, cols in overrides.items():
        for c, v in cols.items():
            km.loc[km["yf_ticker"] == tk, c] = v
    return km.drop(columns="yf_ticker")


def peers_of(sig, t, m="pe", kept=False):
    return set(sig.loc[t, f"{m}_kept" if kept else f"{m}_peers"])


def base_group(target_pe=10.0, target_ev=6.0, peers=5, mc=1000.0, pe=15.0, ev=10.0, prefix="P", **kw):
    """Target 'T' plus ``peers`` same-sub-industry peers of equal size and identical multiples."""
    rows = [comp("T", mc=mc, pe=target_pe, ev=target_ev, **kw)]
    rows += [comp(f"{prefix}{i}", mc=mc * (1 + 0.01 * i), pe=pe, ev=ev, **kw) for i in range(peers)]
    return rows


# --------------------------------------------------------------------------------------------------
# multiples table (section 4.1)
# --------------------------------------------------------------------------------------------------
def test_multiples_formulas_ev_pe_ev_ebitda():
    r = comp("A", mc=1000.0, pe=20.0, ev=10.0)
    r.update(total_debt=300.0, preferred=50.0, minority_interest=20.0, cash=120.0, st_investments=30.0,
             net_income=40.0, ebitda=200.0)
    ctx = make_ctx([r])
    mt = C.multiples_table(ctx, D0, ctx.universe(D0))
    row = mt.iloc[0]
    assert row["ev"] == pytest.approx(1000 + 300 + 50 + 20 - 120 - 30)        # 1220
    assert row["pe"] == pytest.approx(1000 / 40)
    assert row["ev_ebitda"] == pytest.approx(1220 / 200)
    assert row["pe_valid"] and row["ev_valid"] and row["fresh"]
    assert row["mcap"] == 1000.0 and row["price_raw"] == 50.0


def test_nonpositive_denominators_and_ev_are_invalid_never_zero():
    rows = [comp("NEGNI", pe=-5.0), comp("ZERONI", pe=15.0, net_income=0.0), comp("NEGEB", ev=-4.0),
            comp("ZEROEB", ev=10.0, ebitda=0.0), comp("NEGEV", ev=10.0, cash=5000.0), comp("OK")]
    ctx = make_ctx(rows)
    mt = C.multiples_table(ctx, D0, ctx.universe(D0)).set_index("yf_ticker")
    assert not mt.loc["NEGNI", "pe_valid"] and np.isnan(mt.loc["NEGNI", "pe"])
    assert not mt.loc["ZERONI", "pe_valid"] and np.isnan(mt.loc["ZERONI", "pe"])
    assert not mt.loc["NEGEB", "ev_valid"] and np.isnan(mt.loc["NEGEB", "ev_ebitda"])
    assert not mt.loc["ZEROEB", "ev_valid"]
    assert not mt.loc["NEGEV", "ev_valid"] and mt.loc["NEGEV", "ev"] < 0          # EV <= 0 -> invalid
    assert mt.loc["NEGNI", "ev_valid"] and mt.loc["NEGEB", "pe_valid"]            # the other multiple is unaffected
    assert mt.loc["OK", "pe_valid"] and mt.loc["OK", "ev_valid"]


def test_missing_debt_or_cash_drops_ev_but_optional_components_default_to_zero():
    rows = [comp("NODEBT", total_debt=np.nan), comp("NOCASH", cash=np.nan),
            comp("OPT", preferred=np.nan, minority_interest=np.nan, st_investments=np.nan)]
    ctx = make_ctx(rows)
    mt = C.multiples_table(ctx, D0, ctx.universe(D0)).set_index("yf_ticker")
    assert np.isnan(mt.loc["NODEBT", "ev"]) and not mt.loc["NODEBT", "ev_valid"]      # R9: drop, don't impute
    assert np.isnan(mt.loc["NOCASH", "ev"]) and not mt.loc["NOCASH", "ev_valid"]
    assert mt.loc["OPT", "ev"] == pytest.approx(mt.loc["OPT", "mcap"]) and mt.loc["OPT", "ev_valid"]
    assert mt.loc["NODEBT", "pe_valid"]                                                # P/E does not need debt


def test_staleness_135_days_boundary():
    rows = [comp("FRESH", age=135), comp("STALE", age=136), comp("NEW", age=1)]
    ctx = make_ctx(rows)
    mt = C.multiples_table(ctx, D0, ctx.universe(D0)).set_index("yf_ticker")
    assert mt.loc["FRESH", "fresh"] and not mt.loc["STALE", "fresh"] and mt.loc["NEW", "fresh"]
    mt2 = C.multiples_table(ctx, D0, ctx.universe(D0), stale_days=200).set_index("yf_ticker")
    assert mt2.loc["STALE", "fresh"]


def test_lfy_basis_uses_last_fiscal_year_flows():
    r = comp("A", mc=1000.0, pe=10.0, ev=5.0)
    r.update(net_income_lfy=25.0, ebitda_lfy=100.0)
    ctx = make_ctx([r])
    ttm = C.multiples_table(ctx, D0, ctx.universe(D0), "TTM").iloc[0]
    lfy = C.multiples_table(ctx, D0, ctx.universe(D0), "LFY").iloc[0]
    assert ttm["pe"] == pytest.approx(10.0) and lfy["pe"] == pytest.approx(40.0)
    assert ttm["ev_ebitda"] == pytest.approx(5.0) and lfy["ev_ebitda"] == pytest.approx(10.0)
    with pytest.raises(ValueError):
        C.multiples_table(ctx, D0, ctx.universe(D0), "FWD")


def test_price_raw_undoes_split_adjustment():
    r = comp("SPL", price=2.0)           # split-adjusted close 2.0; a 4:1 split happened after D0 -> traded at 8.0
    ctx = make_ctx([r], splits={"SPL": 4.0})
    mt = C.multiples_table(ctx, D0, ctx.universe(D0))
    assert mt.iloc[0]["price"] == 2.0 and mt.iloc[0]["price_raw"] == pytest.approx(8.0)


def test_group_codes_ints_names_and_derived_industry():
    u = pd.DataFrame({"sub_industry_code": [25504040, 25504050.0, "25201010", None]})
    sub, ind = C.group_codes(u)
    assert list(sub[:3]) == ["25504040", "25504050", "25201010"] and pd.isna(sub[3])
    assert list(ind[:3]) == ["255040", "255040", "252010"] and pd.isna(ind[3])
    u2 = pd.DataFrame({"gics_sub_industry": ["A", "B", None], "gics_industry": ["X", "X", "Y"]})
    sub2, ind2 = C.group_codes(u2)
    assert list(sub2[:2]) == ["A", "B"] and pd.isna(sub2[2]) and list(ind2) == ["X", "X", "Y"]


def test_exclude_sector_mask_by_name_and_code():
    u = pd.DataFrame({"gics_sector": ["Financials", "Real Estate", "Health Care", "financials ", None],
                      "sub_industry_code": ["40101015", "60104010", "35101010", "40301020", "45103010"]})
    m = C.exclude_sector_mask(u)
    assert list(m) == [True, True, False, True, False]
    u2 = pd.DataFrame({"gics_sector": ["Information Technology"], "sub_industry_code": ["60101010"]})
    assert C.exclude_sector_mask(u2).iloc[0]                     # excluded by sector code alone
    assert not C.exclude_sector_mask(u2, names=(), codes=()).iloc[0]
    # a custom sector list gets its own codes (Utilities = 55)
    u3 = pd.DataFrame({"gics_sector": ["Utilities", "Financials", None], "sub_industry_code": ["55101010", "40101015", "55102010"]})
    assert list(C.exclude_sector_mask(u3, names=("Utilities",))) == [True, False, True]
    assert not C.exclude_sector_mask(u3, names=()).any()               # toggle: nothing excluded


# --------------------------------------------------------------------------------------------------
# peer selection (R1-R4)
# --------------------------------------------------------------------------------------------------
def test_basic_sub_industry_peers_median_and_discount():
    rows = [comp("T", mc=1000, pe=10, ev=6)]
    rows += [comp(f"P{i}", mc=m, pe=pe, ev=ev) for i, (m, pe, ev) in
             enumerate([(600, 14, 9), (800, 15, 10), (1200, 16, 11), (1500, 17, 12), (1900, 18, 13)])]
    rows += [comp("OTHERSUB", sub="S2", mc=1000, pe=2, ev=2)]            # other sub-industry: never a peer
    _, _, sig = run_signals(rows)
    t = sig.loc["T"]
    assert t["pe_level"] == "sub" and t["ev_level"] == "sub"
    assert peers_of(sig, "T") == {"P0", "P1", "P2", "P3", "P4"}
    assert t["pe_median"] == 16 and t["pe_bench"] == 16 and t["pe_disc"] == pytest.approx(1 - 10 / 16)
    assert t["ev_bench"] == 11 and t["ev_disc"] == pytest.approx(1 - 6 / 11)
    assert t["pe_npeers"] == 5 and t["pe_nkept"] == 5
    assert t["comps_buy"] and t["score"] == pytest.approx(((1 - 10 / 16) + (1 - 6 / 11)) / 2)
    assert "T" not in peers_of(sig, "T")                                  # R1: target never its own peer


def test_size_window_boundaries_are_inclusive_0p5_to_2x_and_closest_five_kept():
    mcs = {"A499": 499, "A500": 500, "A520": 520, "A900": 900, "A1100": 1100, "A1300": 1300, "A1800": 1800,
           "A2000": 2000, "A2001": 2001}
    rows = [comp("T", mc=1000, pe=10, ev=6)] + [comp(k, mc=v, pe=15, ev=10) for k, v in mcs.items()]
    _, _, sig = run_signals(rows)
    # window = 500..2000 inclusive -> 499 and 2001 are out; 7 in the window, the 5 closest in |ln(mc_j/mc_i)|
    assert sig.loc["T", "pe_npool"] == 7
    assert peers_of(sig, "T") == {"A1100", "A900", "A1300", "A1800", "A520"}
    assert sig.loc["T", "pe_npeers"] == 5
    # nearest first
    assert sig.loc["T", "pe_peers"][:3] == ["A1100", "A900", "A1300"]


def test_size_filter_off_uses_all_valid_peers_no_cap_no_window():
    mcs = [10, 100, 400, 900, 1100, 1800, 5000, 90000]
    rows = [comp("T", mc=1000, pe=10, ev=6)] + [comp(f"A{m}", mc=m, pe=15, ev=10) for m in mcs]
    _, _, off = run_signals(rows, {"size_filter": False})
    _, _, on = run_signals(rows, {"size_filter": True})
    assert off.loc["T", "pe_npeers"] == 8 and off.loc["T", "pe_npool"] == 8 and off.loc["T", "pe_level"] == "sub"
    assert peers_of(off, "T") == {f"A{m}" for m in mcs}            # no window, no cap on the number of peers
    # size filter on: only 900, 1100, 1800 are inside 500..2000 -> 3 < 4 peers -> no signal
    assert on.loc["T", "pe_npool"] == 3 and on.loc["T", "pe_level"] == "none"
    # six in-window peers: the cap of 5 applies only when the filter is on
    rows2 = [comp("T", mc=1000, pe=10, ev=6)] + [comp(f"B{i}", mc=700 + 100 * i, pe=15, ev=10) for i in range(6)]
    _, _, on2 = run_signals(rows2, {"size_filter": True})
    _, _, off2 = run_signals(rows2, {"size_filter": False})
    assert on2.loc["T", "pe_npool"] == 6 and on2.loc["T", "pe_npeers"] == 5
    assert off2.loc["T", "pe_npeers"] == 6


def test_fewer_than_four_in_window_falls_back_to_industry_then_none():
    # sub S1 has 3 in-window peers, sub S2 (same industry) adds 2 in-window peers -> industry level, 5 peers
    rows = [comp("T", mc=1000, pe=10, ev=6)]
    rows += [comp(f"S1_{i}", mc=800 + 100 * i, pe=15, ev=10) for i in range(3)]
    rows += [comp(f"S2_{i}", sub="S2", mc=900 + 100 * i, pe=16, ev=11) for i in range(2)]
    rows += [comp("OTHERIND", sub="S3", ind="I2", mc=1000, pe=1, ev=1)]
    _, _, sig = run_signals(rows)
    t = sig.loc["T"]
    assert t["pe_level"] == "industry" and t["pe_npeers"] == 5 and t["ev_level"] == "industry"
    assert "OTHERIND" not in peers_of(sig, "T") and sig.loc["T", "pe_bench"] == 15

    # sub-industry has 4 peers but only 3 inside the size window; the far one is out -> fallback needed
    rows2 = [comp("T", mc=1000, pe=10, ev=6)] + [comp(f"S1_{i}", mc=800 + 100 * i, pe=15, ev=10) for i in range(3)]
    rows2 += [comp("FAR", mc=50000, pe=15, ev=10)]
    _, _, sig2 = run_signals(rows2)
    assert sig2.loc["T", "pe_level"] == "none" and sig2.loc["T", "pe_status"] == "no_peers"
    assert not sig2.loc["T", "comps_buy"] and np.isnan(sig2.loc["T", "pe_bench"])
    # ... but with the size filter off the 4 sub-industry peers are enough
    _, _, sig3 = run_signals(rows2, {"size_filter": False})
    assert sig3.loc["T", "pe_level"] == "sub" and sig3.loc["T", "pe_npeers"] == 4


def test_exactly_three_or_four_peers_threshold_k_min():
    for n, level in ((3, "none"), (4, "sub")):
        _, _, sig = run_signals(base_group(peers=n))
        assert sig.loc["T", "pe_level"] == level, n


def test_single_sub_industry_industry_gives_no_fallback_and_is_flagged():
    rows = base_group(peers=2)                                       # sub S1 = industry I1 : 2 peers only
    _, _, sig = run_signals(rows)
    t = sig.loc["T"]
    assert t["pe_level"] == "none" and t["pe_fallback_tried"] and t["pe_npool"] == 2


def test_industry_pool_includes_the_sub_industry_peers_themselves():
    rows = [comp("T", mc=1000, pe=10, ev=6)] + [comp(f"S1_{i}", mc=900 + 50 * i, pe=15, ev=10) for i in range(2)]
    rows += [comp(f"S2_{i}", sub="S2", mc=1000 + 50 * i, pe=15, ev=10) for i in range(3)]
    _, _, sig = run_signals(rows)
    assert sig.loc["T", "pe_level"] == "industry"
    assert peers_of(sig, "T") == {"S1_0", "S1_1", "S2_0", "S2_1", "S2_2"}


def test_peers_never_cross_industries_or_sectors():
    rows = base_group(peers=4) + [comp("X", ind="I2", sub="S9", mc=1000, pe=15, ev=10)]
    _, _, sig = run_signals(rows)
    assert "X" not in peers_of(sig, "T")


# --------------------------------------------------------------------------------------------------
# trimming (R11)
# --------------------------------------------------------------------------------------------------
def _pe_group(pes, target_pe=5.0, evs=None):
    rows = [comp("T", mc=1000, pe=target_pe, ev=3)]
    for i, v in enumerate(pes):
        rows.append(comp(f"P{i}", mc=1000 + 10 * i, pe=v, ev=10 if evs is None else evs[i]))
    return rows


def test_trim_drops_peers_beyond_2x_median_and_benchmark_is_median_of_kept():
    _, _, sig = run_signals(_pe_group([10, 11, 12, 13, 38]), {"pe_cap": 40})        # median 12 -> 38 > 24 trimmed
    t = sig.loc["T"]
    assert t["pe_median"] == 12 and t["pe_npeers"] == 5 and t["pe_nkept"] == 4
    assert peers_of(sig, "T", kept=True) == {"P0", "P1", "P2", "P3"}
    assert t["pe_bench"] == pytest.approx(11.5)


def test_trim_drops_peers_below_half_the_median():
    _, _, sig = run_signals(_pe_group([4, 20, 22, 24, 26]))                           # median 22 -> 4 < 11 trimmed
    t = sig.loc["T"]
    assert t["pe_median"] == 22 and t["pe_nkept"] == 4 and t["pe_bench"] == pytest.approx(23.0)
    # exactly at the trim bounds is kept (inclusive): median 20, peers 10 and 40 sit on the bounds
    _, _, sig2 = run_signals(_pe_group([10, 20, 20, 40], target_pe=5.0, evs=None), {"pe_cap": 50})
    assert sig2.loc["T", "pe_median"] == 20 and sig2.loc["T", "pe_nkept"] == 4


def test_fewer_than_three_kept_means_no_signal_and_no_fallback_after_trim():
    # 5 sub-industry peers: median 10, kept only {10}: 1 < 3 -> trim_fail.  The industry has plenty of
    # tight peers but the pseudo-code never falls back after a failed trim.
    rows = _pe_group([1, 3, 10, 30, 45], target_pe=2.0)
    rows += [comp(f"I{i}", sub="S2", mc=1000, pe=10, ev=10) for i in range(6)]
    _, _, sig = run_signals(rows, {"pe_cap": 50})
    t = sig.loc["T"]
    assert t["pe_level"] == "sub" and t["pe_status"] == "trim_fail" and np.isnan(t["pe_bench"])
    assert t["pe_nkept"] == 1 and not t["pe_pass"] and not t["comps_buy"]


def test_exactly_three_kept_is_enough():
    _, _, sig = run_signals(_pe_group([10, 10, 10, 1000], target_pe=5.0))              # 1000 > cap -> only 3 peers
    assert sig.loc["T", "pe_level"] == "none"                                         # <4 peers after the cap
    _, _, sig2 = run_signals(_pe_group([10, 11, 12, 100, 100], target_pe=5.0), {"pe_cap": 200})
    assert sig2.loc["T", "pe_nkept"] == 3 and sig2.loc["T", "pe_bench"] == 11


# --------------------------------------------------------------------------------------------------
# caps, negatives, staleness, IPO/merger (R6-R10)
# --------------------------------------------------------------------------------------------------
def test_caps_apply_to_peers_and_to_targets_boundary_inclusive():
    pes = [14, 15, 16, 17, 45]
    rows = _pe_group(pes, target_pe=8.0)
    _, _, sig = run_signals(rows, {"pe_cap": 40})
    assert "P4" not in peers_of(sig, "T") and sig.loc["T", "pe_npeers"] == 4          # peer above the cap dropped
    assert sig.loc["T", "pe_bench"] == 15.5
    _, _, sig50 = run_signals(rows, {"pe_cap": 50})
    assert "P4" in peers_of(sig50, "T") and sig50.loc["T", "pe_npeers"] == 5
    # a cheap-looking target above the cap can never be a BUY
    rows2 = [comp("T", mc=1000, pe=45, ev=5)] + [comp(f"P{i}", mc=1000, pe=90, ev=10) for i in range(5)]
    _, _, s2 = run_signals(rows2, {"pe_cap": 40})
    assert not s2.loc["T", "ok_pe"] and s2.loc["T", "pe_status"] == "ineligible" and not s2.loc["T", "comps_buy"]
    # ... and a target exactly at the cap is eligible
    rows3 = [comp("T", mc=1000, pe=40, ev=5)] + [comp(f"P{i}", mc=1000, pe=30 + i, ev=10) for i in range(5)]
    _, _, s3 = run_signals(rows3, {"pe_cap": 40})
    assert s3.loc["T", "ok_pe"]
    # EV/EBITDA cap is independent of the P/E cap
    rows4 = [comp("T", mc=1000, pe=5, ev=36)] + [comp(f"P{i}", mc=1000, pe=15, ev=40 + i) for i in range(5)]
    _, _, s4 = run_signals(rows4, {"pe_cap": 40, "ev_cap": 35})
    assert s4.loc["T", "ok_pe"] and not s4.loc["T", "ok_ev"] and not s4.loc["T", "comps_buy"]


def test_negative_multiples_are_ignored_not_zero():
    rows = _pe_group([14, 15, 16, 17], target_pe=8.0) + [comp("LOSS", mc=1010, pe=-3.0, ev=10)]
    _, _, sig = run_signals(rows)
    assert "LOSS" not in peers_of(sig, "T") and sig.loc["T", "pe_npeers"] == 4
    assert sig.loc["T", "pe_bench"] == 15.5                       # a zero-filled loss-maker would drag the median down
    assert not sig.loc["LOSS", "ok_pe"] and sig.loc["LOSS", "ok_ev"]
    # with one valid peer fewer, 3 positive + 1 loss-maker is NOT 4 peers
    rows2 = _pe_group([14, 15, 16], target_pe=8.0) + [comp("LOSS", mc=1010, pe=-3.0, ev=10)]
    _, _, sig2 = run_signals(rows2)
    assert sig2.loc["T", "pe_level"] == "none"
    # a loss-making target has no P/E signal
    _, _, sig3 = run_signals([comp("T", pe=-4.0, ev=3)] + [comp(f"P{i}", mc=1000, pe=15, ev=10) for i in range(5)])
    assert sig3.loc["T", "pe_status"] == "ineligible" and not sig3.loc["T", "comps_buy"]


def test_stale_peer_dropped_and_stale_target_has_no_signal():
    rows = base_group(peers=4)
    rows[1]["age"] = 200                                          # one stale peer -> only 3 left
    _, _, sig = run_signals(rows)
    assert sig.loc["T", "pe_level"] == "none"
    rows2 = base_group(peers=5)
    rows2[1]["age"] = 200
    _, _, sig2 = run_signals(rows2)
    assert sig2.loc["T", "pe_npeers"] == 4 and "P0" not in peers_of(sig2, "T")
    rows3 = base_group(peers=5)
    rows3[0]["age"] = 136
    _, _, sig3 = run_signals(rows3)
    assert not sig3.loc["T", "ok_pe"] and not sig3.loc["T", "ok_ev"] and not sig3.loc["T", "comps_buy"]


def test_recent_ipo_and_merger_excluded_as_peer_and_as_target():
    ctx = make_ctx(base_group(peers=5))
    km = km_frame(ctx, P0={"recent_ipo": True})
    _, _, sig = run_signals(None, km=km, ctx=ctx)
    assert "P0" not in peers_of(sig, "T") and sig.loc["T", "pe_npeers"] == 4
    assert not sig.loc["P0", "ok_pe"] and not sig.loc["P0", "ok_ev"] and sig.loc["P0", "recent_ipo"]
    km2 = km_frame(ctx, P1={"recent_merger": True}, T={"recent_ipo": True})
    _, _, sig2 = run_signals(None, km=km2, ctx=ctx)
    assert "P1" not in peers_of(sig2, "T")
    assert sig2.loc["T", "pe_status"] == "ineligible" and not sig2.loc["T", "comps_buy"]
    # two flagged peers out of 5 -> 3 left -> no signal
    km3 = km_frame(ctx, P0={"recent_ipo": True}, P2={"recent_merger": True})
    _, _, sig3 = run_signals(None, km=km3, ctx=ctx)
    assert sig3.loc["T", "pe_level"] == "none"


def test_key_metric_flags_nan_count_as_not_flagged():
    ctx = make_ctx(base_group(peers=5))
    km = km_frame(ctx)
    km["recent_ipo"] = km["recent_ipo"].astype(object)
    km.loc[km.index[1], "recent_ipo"] = np.nan
    _, _, sig = run_signals(None, km=km, ctx=ctx)
    assert sig.loc["T", "pe_npeers"] == 5


# --------------------------------------------------------------------------------------------------
# discount test, AND rule, score (R5, R12)
# --------------------------------------------------------------------------------------------------
def test_discount_is_strict_at_exactly_theta():
    peers = [comp(f"P{i}", mc=1000, pe=10, ev=10) for i in range(5)]
    for pe_t, expect in ((8.5, False), (8.49, True), (9.0, False)):
        _, _, sig = run_signals([comp("T", mc=1000, pe=pe_t, ev=1)] + peers, {"theta": 0.15})
        assert bool(sig.loc["T", "pe_pass"]) is expect, pe_t
    _, _, sig = run_signals([comp("T", mc=1000, pe=8.9, ev=1)] + peers, {"theta": 0.10})
    assert sig.loc["T", "pe_pass"]
    _, _, sig = run_signals([comp("T", mc=1000, pe=8.0, ev=1)] + peers, {"theta": 0.20})
    assert not sig.loc["T", "pe_pass"]                              # 8.0 is exactly 0.8x: not strictly below


def test_and_rule_requires_both_multiples_and_score_is_average_discount():
    peers = [comp(f"P{i}", mc=1000, pe=20, ev=10) for i in range(5)]
    _, _, a = run_signals([comp("T", mc=1000, pe=10, ev=9.9)] + peers)         # P/E cheap, EV/EBITDA not
    assert a.loc["T", "pe_pass"] and not a.loc["T", "ev_pass"] and not a.loc["T", "comps_buy"]
    _, _, b = run_signals([comp("T", mc=1000, pe=19.9, ev=5)] + peers)         # EV/EBITDA cheap, P/E not
    assert not b.loc["T", "pe_pass"] and b.loc["T", "ev_pass"] and not b.loc["T", "comps_buy"]
    _, _, c = run_signals([comp("T", mc=1000, pe=10, ev=5)] + peers)
    assert c.loc["T", "comps_buy"] and c.loc["T", "score"] == pytest.approx((0.5 + 0.5) / 2)
    _, _, d = run_signals([comp("T", mc=1000, pe=12, ev=6)] + peers)
    assert d.loc["T", "score"] == pytest.approx(((1 - 12 / 20) + (1 - 6 / 10)) / 2)
    # a target with an invalid EV/EBITDA cannot be a BUY and has no score
    _, _, e = run_signals([comp("T", mc=1000, pe=10, ev=-3)] + peers)
    assert not e.loc["T", "comps_buy"] and np.isnan(e.loc["T", "score"])


def test_multiples_have_independent_peer_sets():
    # P0 has a valid P/E but a negative EV/EBITDA: it is a P/E peer, not an EV/EBITDA peer
    rows = [comp("T", mc=1000, pe=10, ev=5)] + [comp(f"P{i}", mc=1000, pe=20, ev=10) for i in range(4)]
    rows += [comp("P4", mc=1000, pe=20, ev=-2)]
    _, _, sig = run_signals(rows)
    assert sig.loc["T", "pe_npeers"] == 5 and sig.loc["T", "ev_npeers"] == 4
    assert "P4" in peers_of(sig, "T", "pe") and "P4" not in peers_of(sig, "T", "ev")


# --------------------------------------------------------------------------------------------------
# key-metric gates (K1-K3, M1)
# --------------------------------------------------------------------------------------------------
def test_gates_apply_to_target_only_and_final_eligibility():
    rows = [comp("T", mc=1000, pe=10, ev=5)] + [comp(f"P{i}", mc=1000, pe=20, ev=10) for i in range(5)]
    ctx = make_ctx(rows)
    # peers failing every gate still count as peers (M1)
    km = km_frame(ctx, **{f"P{i}": {"pass_leverage": False, "quality_ok": False, "pass_roic": False} for i in range(5)})
    _, _, s = run_signals(None, km=km, ctx=ctx)
    assert s.loc["T", "pe_npeers"] == 5 and s.loc["T", "eligible"] and s.loc["T", "comps_buy"]
    for gate in ("pass_leverage", "quality_ok", "pass_roic"):
        _, _, s2 = run_signals(None, km=km_frame(ctx, T={gate: False}), ctx=ctx)
        assert s2.loc["T", "comps_buy"] and not s2.loc["T", "eligible"], gate
        assert s2.loc["T", "n_fail"] == 1
    _, _, s3 = run_signals(None, km=km_frame(ctx, T={"pass_leverage": False, "pass_roic": False}), ctx=ctx)
    assert s3.loc["T", "n_fail"] == 2 and bool(s3.loc["T", "st_leverage"]) is False
    # stage flags are cumulative
    _, _, s4 = run_signals(None, km=km_frame(ctx, T={"quality_ok": False}), ctx=ctx)
    assert s4.loc["T", "st_leverage"] and not s4.loc["T", "st_quality"] and not s4.loc["T", "eligible"]
    # a target missing from km fails all gates; km=None leaves the gates open (comps-only)
    km_missing = km_frame(ctx).drop(index=ctx.df.loc[ctx.df.yf_ticker == "T", "cik"])
    _, _, s5 = run_signals(None, km=km_missing, ctx=ctx)
    assert s5.loc["T", "comps_buy"] and not s5.loc["T", "eligible"]
    _, _, s6 = run_signals(None, km=None, ctx=ctx)
    assert s6.loc["T", "eligible"]


def test_gates_param_can_switch_a_gate_off():
    rows = [comp("T", mc=1000, pe=10, ev=5)] + [comp(f"P{i}", mc=1000, pe=20, ev=10) for i in range(5)]
    ctx = make_ctx(rows)
    km = km_frame(ctx, T={"pass_roic": False})
    _, _, on = run_signals(None, {"gates": ("leverage", "quality", "roic")}, km=km, ctx=ctx)
    _, _, off = run_signals(None, {"gates": ("leverage", "quality")}, km=km, ctx=ctx)
    assert not on.loc["T", "eligible"] and off.loc["T", "eligible"]


def test_nd_ebitda_from_km_with_fallback_to_table():
    rows = [comp("T", mc=1000, pe=10, ev=5, total_debt=400.0, cash=100.0, st_investments=50.0)]
    rows += [comp(f"P{i}", mc=1000, pe=20, ev=10) for i in range(5)]
    ctx = make_ctx(rows)
    _, mt, s = run_signals(None, km=None, ctx=ctx)
    assert s.loc["T", "nd_ebitda"] == pytest.approx((400 - 100 - 50) / mt.set_index("yf_ticker").loc["T", "ebitda"])
    km = km_frame(ctx)
    km.loc[km.index[0], "nd_ebitda"] = 2.5
    _, _, s2 = run_signals(None, km=km, ctx=ctx)
    assert s2.loc["T", "nd_ebitda"] == 2.5


# --------------------------------------------------------------------------------------------------
# caching across theta / diagnostics
# --------------------------------------------------------------------------------------------------
def test_cache_is_reused_across_theta_and_changes_nothing():
    rows = [comp("T", mc=1000, pe=10, ev=5), comp("T2", mc=1000, pe=17, ev=9)]
    rows += [comp(f"P{i}", mc=1000, pe=20, ev=10) for i in range(5)]
    ctx = make_ctx(rows)
    univ = ctx.universe(D0)
    mt = C.multiples_table(ctx, D0, univ)
    km = km_frame(ctx)
    cache: dict = {}
    for theta in (0.10, 0.15, 0.20):
        a = C.comps_signals(ctx, D0, univ, {"theta": theta}, km, mt=mt, cache=cache)
        b = C.comps_signals(ctx, D0, univ, {"theta": theta}, km, mt=mt)
        pd.testing.assert_frame_equal(a, b)
        assert len(cache) == 2                                     # one entry per multiple (same caps/size filter)
    C.comps_signals(ctx, D0, univ, {"pe_cap": 50}, km, mt=mt, cache=cache)
    assert len(cache) == 3                                         # new P/E cap -> only P/E recomputed
    C.comps_signals(ctx, D0, univ, {"size_filter": False}, km, mt=mt, cache=cache)
    assert len(cache) == 5
    # return_peers upgrades a cached entry
    sig = C.comps_signals(ctx, D0, univ, {"theta": 0.10}, km, mt=mt, cache=cache, return_peers=True)
    assert "pe_peers" in sig.columns


def test_stage_counts_are_monotone_and_fallback_rate_defined():
    rows = base_group(peers=5) + [comp("LOSS", pe=-1.0, ev=3, mc=900), comp("LONE", sub="Z1", ind="Z", mc=1000)]
    ctx, _, sig = run_signals(rows, km=None, ctx=make_ctx(rows))
    d = C.stage_counts(sig)
    assert d["n_valid_both"] <= d["n_mt"]
    assert d["n_has_bench"] <= d["n_has_peers"] <= d["n_valid_both"]
    assert d["n_after_roic"] <= d["n_after_quality"] <= d["n_after_leverage"] <= d["n_comps_buy"]
    assert d["n_ok_pe"] == d["n_mt"] - 1                        # the loss-maker
    assert d["fallback_rate"] == 0.0 and d["avg_peers"] == pytest.approx(5.0)
    assert d["no_peer_rate_pe"] > 0                              # LONE has no peers


# --------------------------------------------------------------------------------------------------
# brute-force reference implementation of research/04 section 5.3 (pick_peers + trim)
# --------------------------------------------------------------------------------------------------
def _reference(mt, km, p, multiple):
    col = {"pe": "pe", "ev": "ev_ebitda"}[multiple]
    cap = p[f"{multiple}_cap"]
    ipo = km["recent_ipo"].reindex(mt.index).fillna(False).astype(bool) if km is not None else pd.Series(False, index=mt.index)
    mer = km["recent_merger"].reindex(mt.index).fillna(False).astype(bool) if km is not None else pd.Series(False, index=mt.index)
    ok = {}
    for cik, r in mt.iterrows():
        x = r[col]
        ok[cik] = bool(r["fresh"] and not ipo[cik] and not mer[cik] and np.isfinite(x) and 0 < x <= cap)
    res = {}
    for i in mt.index:
        if not ok[i]:
            res[i] = None
            continue
        out = ("none", [], np.nan)
        for level, code in (("sub", "sub_code"), ("industry", "ind_code")):
            if pd.isna(mt.loc[i, code]):
                continue
            pool = [j for j in mt.index if j != i and ok[j] and mt.loc[j, code] == mt.loc[i, code]]
            if p["size_filter"]:
                pool = [j for j in pool if p["size_lo"] <= mt.loc[j, "mcap"] / mt.loc[i, "mcap"] <= p["size_hi"]]
            if len(pool) >= p["k_min"]:
                if p["size_filter"] and len(pool) > p["k_max"]:
                    pool = sorted(pool, key=lambda j: abs(math.log(mt.loc[j, "mcap"] / mt.loc[i, "mcap"])))[:p["k_max"]]
                m0 = float(np.median([mt.loc[j, col] for j in pool]))
                kept = [j for j in pool if p["trim_lo"] * m0 <= mt.loc[j, col] <= p["trim_hi"] * m0]
                b = float(np.median([mt.loc[j, col] for j in kept])) if len(kept) >= p["k_trim_min"] else np.nan
                out = (level, sorted(pool), b)
                break
        res[i] = out
    return res


@pytest.mark.parametrize("size_filter", [True, False])
@pytest.mark.parametrize("seed", [0, 1, 2])
def test_vectorised_matches_bruteforce_reference_on_random_universe(size_filter, seed):
    rng = np.random.default_rng(seed)
    rows = []
    subs = [("S1", "I1"), ("S2", "I1"), ("S3", "I1"), ("S4", "I2"), ("S5", "I2"), ("S6", "I3"), ("S7", "I3"),
            ("S8", "I3"), ("S9", "I4")]
    probs = np.array([30, 30, 6, 30, 8, 30, 30, 5, 9], dtype=float)
    probs /= probs.sum()
    for n in range(260):
        sub, ind = subs[rng.choice(len(subs), p=probs)]
        mc = float(np.exp(rng.normal(7.0, 1.0)))
        pe = float(np.exp(rng.normal(2.7, 0.55))) * (-1 if rng.random() < 0.06 else 1)
        ev = float(np.exp(rng.normal(2.3, 0.5))) * (-1 if rng.random() < 0.06 else 1)
        rows.append(comp(f"X{n}", sub=sub, ind=ind, mc=mc, pe=pe, ev=ev, age=int(rng.integers(10, 160))))
    ctx = make_ctx(rows)
    km = km_frame(ctx)
    flag = rng.random(len(km)) < 0.08
    km["recent_ipo"] = flag
    km["recent_merger"] = rng.random(len(km)) < 0.05
    p = C.merge_params({"size_filter": size_filter, "pe_cap": 40, "ev_cap": 35})
    univ = ctx.universe(D0)
    mt = C.multiples_table(ctx, D0, univ)
    sig = C.comps_signals(ctx, D0, univ, p, km, mt=mt, return_peers=True)
    for m in ("pe", "ev"):
        ref = _reference(mt, km, p, m)
        n_checked = 0
        for cik, r in ref.items():
            if r is None:
                assert sig.loc[cik, f"{m}_status"] == "ineligible"
                continue
            level, peers, b = r
            assert sig.loc[cik, f"{m}_level"] == level, (m, cik)
            assert sorted(sig.loc[cik, f"{m}_peer_ciks"]) == peers, (m, cik)
            if np.isnan(b):
                assert np.isnan(sig.loc[cik, f"{m}_bench"])
            else:
                assert sig.loc[cik, f"{m}_bench"] == pytest.approx(b, rel=1e-12)
            n_checked += level != "none"
        assert n_checked > 100                                    # the comparison is not vacuous
    # fallback is actually exercised
    assert (sig["pe_level"] == "industry").any() or not size_filter


def test_scalar_pick_peers_and_trim_peers_agree_with_vectorised_path():
    rng = np.random.default_rng(7)
    rows = []
    for n in range(120):
        sub, ind = [("S1", "I1"), ("S2", "I1"), ("S3", "I2"), ("S4", "I2")][rng.integers(4)]
        rows.append(comp(f"Y{n}", sub=sub, ind=ind, mc=float(np.exp(rng.normal(7, 0.9))),
                         pe=float(np.exp(rng.normal(2.7, 0.5))), ev=float(np.exp(rng.normal(2.3, 0.5)))))
    ctx = make_ctx(rows)
    univ = ctx.universe(D0)
    mt = C.multiples_table(ctx, D0, univ)
    for sf in (True, False):
        p = C.merge_params({"size_filter": sf})
        sig = C.comps_signals(ctx, D0, univ, p, None, mt=mt, return_peers=True)
        for m in ("pe", "ev"):
            ok = C.multiple_eligibility(mt, None, m, p[f"{m}_cap"])
            col = {"pe": "pe", "ev": "ev_ebitda"}[m]
            for cik in mt.index[:60]:
                peers, level = C.pick_peers(mt, ok, cik, m, sf, p)
                assert level == (sig.loc[cik, f"{m}_level"] if ok[mt.index.get_loc(cik)] else "na")
                assert peers == list(sig.loc[cik, f"{m}_peer_ciks"])                     # same set, nearest first
                if peers:
                    kept, m0, b = C.trim_peers(mt.loc[peers, col].to_numpy(), p)
                    assert m0 == pytest.approx(sig.loc[cik, f"{m}_median"])
                    if np.isnan(b):
                        assert np.isnan(sig.loc[cik, f"{m}_bench"])
                    else:
                        assert b == pytest.approx(sig.loc[cik, f"{m}_bench"])
                    assert [c for c, k in zip(peers, kept) if k] == [c for c in peers if c in set(sig.loc[cik, f"{m}_kept_ciks"])]


def test_trim_peers_inclusive_bounds_and_minimum_kept():
    kept, m0, b = C.trim_peers([10, 20, 20, 40])
    assert m0 == 20 and kept.all() and b == 20
    kept, m0, b = C.trim_peers([1, 10, 11, 12, 100])
    assert m0 == 11 and list(kept) == [False, True, True, True, False] and b == 11
    kept, m0, b = C.trim_peers([1, 10, 30])
    assert np.isnan(b)                                                   # only 1 kept


def test_coverage_by_sector_table():
    rows = base_group(peers=5) + [comp(f"H{i}", sub="H1", ind="H", sector="Health Care", mc=1000, pe=15, ev=10)
                                  for i in range(2)]
    _, _, sig = run_signals(rows, km=None)
    cov = C.coverage_by_sector(sig)
    assert cov.loc["Industrials", "n"] == 6 and cov.loc["Health Care", "n"] == 2
    assert cov.loc["Industrials", "bench_both"] == 1.0 and cov.loc["Health Care", "bench_both"] == 0.0
    assert cov.loc["Industrials", "n_comps_buy"] == 1 and cov.loc["Industrials", "fallback"] == 0.0


def test_input_frames_are_not_mutated():
    ctx = make_ctx(base_group(peers=5))
    univ = ctx.universe(D0)
    mt = C.multiples_table(ctx, D0, univ)
    km = km_frame(ctx)
    mt0, km0, univ0 = mt.copy(), km.copy(), univ.copy()
    C.comps_signals(ctx, D0, univ, {}, km, mt=mt, return_peers=True)
    pd.testing.assert_frame_equal(mt, mt0)
    pd.testing.assert_frame_equal(km, km0)
    pd.testing.assert_frame_equal(univ, univ0)
