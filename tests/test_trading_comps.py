"""Tests for quant/strategies/trading_comps.py (synthetic universes, key-metric table patched)."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant.backtest import grid as grid_mod
from quant.signals import comps as C
from quant.strategies import trading_comps as TC
from tests.test_comps import D0, FakeCtx, comp, km_frame, make_ctx


# --------------------------------------------------------------------------------------------------
# synthetic strategy universe
# --------------------------------------------------------------------------------------------------
def strat_rows(n_sub=26, d0=0.21, step=0.01, extras=True):
    """n_sub sub-industries (each its own industry): 1 cheap target Txx with discount d_i = d0 + step*i versus
    its 5 normal peers (P/E 20, EV/EBITDA 10), so the target's benchmark is exactly 20 / 10 and disc = d_i.
    Extras (excluded or special): Financials / Real Estate, a $200M company, a $3 stock, a split-adjusted stock."""
    rows = []

    def group(tag, d, sector="Health Care", mc=1.0e9, price=50.0, ppeer=50.0, sub=None):
        sub = sub or f"SUB_{tag}"
        ind = f"IND_{tag}"
        out = [comp(f"T_{tag}", sub=sub, ind=ind, mc=mc, pe=20 * (1 - d), ev=10 * (1 - d), sector=sector, price=price)]
        out += [comp(f"N_{tag}_{j}", sub=sub, ind=ind, mc=mc * (1 + 0.01 * j), pe=20, ev=10, sector=sector,
                     price=ppeer) for j in range(5)]
        return out

    for i in range(n_sub):
        rows += group(f"{i:02d}", d0 + step * i)
    if extras:
        rows += group("FIN", 0.40, sector="Financials")
        rows += group("REIT", 0.40, sector="Real Estate")
        rows += group("SMALL", 0.40, mc=2.0e8)
        rows += group("LOWPX", 0.40, price=3.0)
        rows += group("SPLIT", 0.50, price=2.0)
    return rows


def strat_ctx(rows=None, **kw):
    kw.setdefault("splits", {"T_SPLIT": 4.0})                               # the $2 split-adjusted close traded at $8
    ctx = make_ctx(rows if rows is not None else strat_rows(), **kw)
    ctx.km_overrides = {}
    return ctx


@pytest.fixture
def km_calls(monkeypatch):
    calls: list = []

    def fake(ctx, date, univ, km_params=None):
        calls.append(pd.Timestamp(date))
        km = km_frame(ctx, **getattr(ctx, "km_overrides", {}))
        return km.loc[km.index.intersection(univ["cik"])]

    monkeypatch.setattr(TC, "_key_metrics", fake)
    return calls


# --------------------------------------------------------------------------------------------------
# grid / pre-registration
# --------------------------------------------------------------------------------------------------
def test_grid_v2_has_9_unique_cells_around_the_v1_choice():
    # v1 (54 cells: theta x P/E cap x EV/EBITDA cap x size filter) chose theta 10%, caps 40/35, no size filter;
    # v2 keeps that choice and adds the value-trap momentum filter.
    assert len(TC.GRID) == 9
    assert len({grid_mod.cell_id(c) for c in TC.GRID}) == 9
    assert {c["theta"] for c in TC.GRID} == {0.10, 0.15, 0.20}
    assert {c["mom_filter"] for c in TC.GRID} == {0.0, 0.3, 0.5}
    assert {(c["pe_cap"], c["ev_cap"], c["size_filter"], c["basis"]) for c in TC.GRID} == {(40, 35, False, "TTM")}
    assert TC.DEFAULT == TC.V1_CHOSEN == dict(theta=0.10, pe_cap=40, ev_cap=35, size_filter=False, basis="TTM",
                                              mom_filter=0.0)
    assert TC.DOC_DEFAULT["theta"] == 0.15 and TC.DOC_DEFAULT["size_filter"] is True
    assert TC.DEFAULT in TC.GRID
    assert list(TC.AXES) == ["theta", "mom_filter"] and TC.CATEGORICAL == {}
    for c in TC.GRID:
        assert set(c) == set(TC.DEFAULT)


def test_preregistration_roundtrip_idempotent_and_locked(tmp_path):
    path = TC.preregister_grid(out_dir=tmp_path)
    doc = json.loads(path.read_text())
    assert doc["strategy"] == "trading_comps" and doc["n_cells"] == 9 and doc["default"] == TC.DEFAULT
    notes = doc["extra"]["notes"].lower()
    assert "forward" in notes and "not backtestable" in notes and "lfy" in notes
    assert "universe changed to sp900 before any grid run because s&p 600 history starts 2018-09" in notes
    assert doc["extra"]["fixed_params"]["universe"] == "SP900"
    assert doc["extra"]["fixed_params"]["top_n"] == 20 and doc["extra"]["fixed_params"]["min_hold"] == 5
    assert doc["extra"]["windows"]["train_end"] == "2018-12-31"
    stamp = doc["timestamp"]
    TC.preregister_grid(out_dir=tmp_path)                                    # unchanged -> untouched
    assert json.loads(path.read_text())["timestamp"] == stamp
    changed = [dict(c, mom_filter=0.6) if c["mom_filter"] == 0.5 else c for c in TC.GRID]
    with pytest.raises(Exception):
        grid_mod.preregister("trading_comps", changed, axes={**TC.AXES, "mom_filter": [0.0, 0.3, 0.6]},
                             categorical=TC.CATEGORICAL, default=TC.DEFAULT, out_dir=tmp_path)


def test_forced_reregistration_updates_notes_keeps_history(tmp_path, monkeypatch):
    path = TC.preregister_grid(out_dir=tmp_path)
    first = json.loads(path.read_text())
    new_extra = dict(TC.prereg_extra(), notes="amended notes")
    monkeypatch.setattr(TC, "prereg_extra", lambda: new_extra)
    TC.preregister_grid(out_dir=tmp_path)                                    # no force: untouched
    assert json.loads(path.read_text())["extra"]["notes"] == first["extra"]["notes"]
    TC.preregister_grid(out_dir=tmp_path, force=True)
    doc = json.loads(path.read_text())
    assert doc["extra"]["notes"] == "amended notes" and doc["grid_hash"] == first["grid_hash"]
    assert len(doc["history"]) == 1 and doc["history"][0]["timestamp"] == first["timestamp"]
    assert doc["n_cells"] == 9 and doc["default"] == TC.DEFAULT
    TC.preregister_grid(out_dir=tmp_path, force=True)                        # identical again: no new history entry
    assert len(json.loads(path.read_text())["history"]) == 1


def test_grid_is_compatible_with_run_grid_and_plateau_selection(tmp_path):
    TC.preregister_grid(out_dir=tmp_path)
    rng = np.random.default_rng(0)
    idx = pd.date_range("2013-01-31", periods=72, freq="ME")

    def fn(cell):
        shift = 0.002 * (cell["theta"] > 0.1) + 0.001 * (cell["pe_cap"] == 40)
        return pd.Series(rng.normal(0.008 + shift, 0.03, len(idx)), index=idx)

    res = grid_mod.run_grid("trading_comps", TC.GRID, fn, ledger=False, out_dir=tmp_path)
    assert res.M.shape == (72, 9)
    sel = res.select(train=("2013-01", "2018-12"))
    assert "chosen" in sel and set(TC.AXES) <= set(sel["chosen"])
    # cells with the LFY basis are NOT part of the pre-registered grid
    with pytest.raises(Exception):
        grid_mod.run_grid("trading_comps", TC.GRID + [dict(TC.DEFAULT, basis="LFY")], fn, ledger=False,
                          out_dir=tmp_path)


def test_resolve_params_layers_defaults_fixed_and_overrides():
    p = TC.resolve_params()
    assert (p["theta"], p["pe_cap"], p["ev_cap"], p["size_filter"], p["basis"]) == (0.10, 40, 35, False, "TTM")
    assert (p["top_n"], p["min_hold"], p["min_mcap"], p["min_price"]) == (20, 5, 3.0e8, 5.0)
    assert p["k_min"] == 4 and p["k_max"] == 5 and p["trim_lo"] == 0.5 and p["trim_hi"] == 2.0
    q = TC.resolve_params({"theta": 0.2, "basis": "lfy", "top_n": 10})
    assert q["theta"] == 0.2 and q["basis"] == "LFY" and q["top_n"] == 10
    with pytest.raises(ValueError):
        TC.resolve_params({"basis": "forward"})


# --------------------------------------------------------------------------------------------------
# universe
# --------------------------------------------------------------------------------------------------
def test_universe_excludes_financials_real_estate_small_caps_low_price_and_uses_raw_price(km_calls):
    ctx = strat_ctx()
    p = TC.resolve_params()
    st = TC._state(ctx, D0, p)
    tick = set(st.mt["yf_ticker"])
    assert not any(t.endswith(("_FIN", "_REIT")) or "_FIN_" in t or "_REIT_" in t for t in tick)
    assert not any("SMALL" in t for t in tick)                              # $200M < $300M floor
    assert "T_LOWPX" not in tick and "N_LOWPX_0" in tick                    # the $3 stock only; its $50 peers stay
    assert "T_SPLIT" in tick                                                 # split-adjusted $2, as-traded $8
    assert st.counts["n_index"] == len(ctx.df)
    assert st.counts["n_ex_sector"] == len(ctx.df) - 12                      # 2 sectors x 6 names
    assert st.counts["n_universe"] == len(ctx.df) - 12 - 6 - 1               # minus SMALL (6) and T_LOWPX
    assert st.counts["n_no_gics"] == 0
    assert set(ctx.universe_names) == {"SP900"}                                # S&P 500 + 400 only (no S&P 600 history)
    assert st.counts["n_universe"] == len(st.mt) < st.counts["n_mcap"]
    assert set(st.univ["cik"]) == set(st.mt.index)
    assert len(km_calls) == 1
    # without the split record the same stock trades at $2 and is out
    st2 = TC._state(strat_ctx(splits={}), D0, p)
    assert "T_SPLIT" not in set(st2.mt["yf_ticker"])


def test_unclassified_names_are_dropped_and_counted(km_calls):
    rows = strat_rows(n_sub=2, extras=False)
    rows += [comp("NOGICS", sub=None, ind=None, mc=1e9, pe=5, ev=3, sector=None)]
    ctx = strat_ctx(rows)
    st = TC._state(ctx, D0, TC.resolve_params())
    assert "NOGICS" not in set(st.mt["yf_ticker"]) and st.counts["n_no_gics"] == 1
    assert st.counts["n_universe"] == len(ctx.df) - 1


# --------------------------------------------------------------------------------------------------
# portfolio construction
# --------------------------------------------------------------------------------------------------
def _sig(rows):
    df = pd.DataFrame(rows, columns=["yf_ticker", "eligible", "score", "nd_ebitda"])
    df.index = pd.Index(1000 + np.arange(len(df)), name="cik")
    return df


def test_top_n_by_score_equal_weight_and_cash_when_fewer_than_min_hold():
    p = TC.resolve_params()
    sig = _sig([(f"A{i:02d}", True, 0.30 + 0.01 * i, 1.0) for i in range(25)] + [("X", False, 0.99, 0.0)])
    w = TC.portfolio_from_signals(sig, p)
    assert len(w) == 20 and np.allclose(w.values, 0.05) and w.sum() == pytest.approx(1.0)
    assert set(w.index) == {f"A{i:02d}" for i in range(5, 25)}               # highest 20 scores; ineligible X never held
    for k, expect in ((6, 1 / 6), (5, 0.2), (4, 0.2), (2, 0.2), (1, 0.2)):
        w = TC.portfolio_from_signals(_sig([(f"A{i}", True, 0.3 + 0.01 * i, 1.0) for i in range(k)]), p)
        assert len(w) == k and np.allclose(w.values, expect)
        assert w.sum() == pytest.approx(min(1.0, k * expect))                # min_hold: weights 1/max(k,5), rest cash
    assert TC.portfolio_from_signals(_sig([("A", False, 0.5, 1.0)]), p).empty
    assert TC.portfolio_from_signals(_sig([]), p).empty


def test_score_ties_broken_by_lower_nd_ebitda_then_cik():
    p = TC.resolve_params({"top_n": 3})
    sig = _sig([("HIGHND", True, 0.40, 2.5), ("LOWND", True, 0.40, -1.0), ("MIDND", True, 0.40, 0.5),
                ("NAND", True, 0.40, np.nan), ("BEST", True, 0.41, 2.9)])
    ranked = TC.rank_candidates(sig)
    assert list(ranked["yf_ticker"]) == ["BEST", "LOWND", "MIDND", "HIGHND", "NAND"]
    assert set(TC.portfolio_from_signals(sig, p).index) == {"BEST", "LOWND", "MIDND"}
    # float noise below 1e-10 does not defeat the tie-break
    sig2 = _sig([("A", True, 0.4 + 1e-13, 3.0), ("B", True, 0.4, 0.0)])
    assert list(TC.rank_candidates(sig2)["yf_ticker"]) == ["B", "A"]


def test_target_weights_pick_top_20_by_discount_and_exclude_filtered_names(km_calls):
    ctx = strat_ctx()
    tw = TC.target_weights(ctx, TC.DEFAULT, [D0])
    row = tw.iloc[0]
    held = set(row[row > 0].index)
    assert len(held) == 20 and np.allclose(row[row > 0], 0.05)
    # expected: the 20 largest discounts among eligible names: SPLIT (0.5) then T_25 ... T_07
    expect = {"T_SPLIT"} | {f"T_{i:02d}" for i in range(7, 26)}
    assert held == expect
    assert not any(("FIN" in t or "REIT" in t or "SMALL" in t or "LOWPX" in t) for t in held)
    assert row.sum() == pytest.approx(1.0)


def test_theta_changes_the_candidate_set_and_and_rule_is_in_force(km_calls):
    ctx = strat_ctx(strat_rows(n_sub=10, extras=False))                      # discounts 0.21 .. 0.30
    for theta, n in ((0.10, 10), (0.25, 5), (0.30, 0), (0.20, 10)):
        w = TC.target_weights(ctx, dict(TC.DEFAULT, theta=theta), [D0]).iloc[0]
        assert (w > 0).sum() == n, theta
    # the AND rule: make one target's EV/EBITDA expensive (but P/E cheap) -> it drops out
    rows = strat_rows(n_sub=10, extras=False)
    for r in rows:
        if r["yf_ticker"] == "T_05":
            r.update(ebitda=r["mcap"] / 9.9, ebitda_lfy=r["mcap"] / 9.9)
    w = TC.target_weights(strat_ctx(rows), TC.DEFAULT, [D0]).iloc[0]
    assert w.get("T_05", 0.0) == 0.0 and (w > 0).sum() == 9


def test_key_metric_gates_remove_names_and_cash_fills_the_remainder(km_calls):
    ctx = strat_ctx(strat_rows(n_sub=8, extras=False))
    ctx.km_overrides = {f"T_{i:02d}": {"pass_roic": False} for i in range(0, 6)}
    w = TC.target_weights(ctx, TC.DEFAULT, [D0]).iloc[0]
    assert set(w[w > 0].index) == {"T_06", "T_07"} and np.allclose(w[w > 0], 0.2)    # 2 names -> 0.2 each, 60% cash
    assert w.sum() == pytest.approx(0.4)
    ctx.km_overrides = {f"T_{i:02d}": {"recent_ipo": True} for i in range(0, 8)}       # IPO flag on the targets themselves
    TC.clear_cache(ctx)
    w2 = TC.target_weights(ctx, TC.DEFAULT, [D0]).iloc[0]
    assert w2.sum() == 0.0                                                    # empty book = explicit all-cash row


def test_all_cash_rows_are_emitted_and_engine_goes_to_cash(km_calls):
    rows_later = strat_rows(n_sub=8, d0=0.0, step=0.0, extras=False)           # nothing cheap any more
    ctx = FakeCtx(strat_rows(n_sub=8, extras=False), rows_by_date={pd.Timestamp("2020-08-15"): rows_later})
    ctx.km_overrides = {}
    dates = ctx.month_ends("2020-06-01", "2020-10-31")
    tw = TC.target_weights(ctx, TC.DEFAULT, dates)
    assert list(tw.index) == dates
    sums = tw.sum(axis=1)
    assert (sums[:2] > 0).all() and (sums[2:] == 0).all()                      # Jun, Jul invested; Aug+ all cash
    res = TC.backtest(ctx, TC.DEFAULT, start="2020-06-01", end="2020-12-31")
    assert res.daily["n_holdings"].iloc[-1] == 0 and res.daily["cash_weight"].iloc[-1] == pytest.approx(1.0)
    assert (tw.to_numpy() >= 0).all() and (tw.sum(axis=1) <= 1 + 1e-12).all()


# --------------------------------------------------------------------------------------------------
# backtest / diagnostics
# --------------------------------------------------------------------------------------------------
def test_backtest_runs_through_engine_with_diagnostics(km_calls):
    ctx = strat_ctx()
    res = TC.backtest(ctx, TC.DEFAULT, start="2020-01-01", end="2020-09-30", cost_bps=10)
    d = res.diagnostics
    assert len(d) == 9 and d.index.is_monotonic_increasing
    for col in ("n_index", "n_ex_sector", "n_universe", "n_valid_both", "n_has_peers", "n_comps_buy",
                "n_after_leverage", "n_after_quality", "n_after_roic", "n_held", "fallback_rate", "avg_peers",
                "turnover_target", "cash_weight"):
        assert col in d.columns, col
    assert (d["n_held"] == 20).all() and (d["n_comps_buy"] >= d["n_after_roic"]).all()
    assert (d["n_after_roic"] >= d["n_held"]).all()
    assert (d["avg_peers"] <= 5.0).all() and (d["avg_peers"] > 4.9).all()       # N_LOWPX_* lost their cheap sibling: 4 peers
    assert d["fallback_rate"].iloc[0] == 0.0
    assert d["turnover_target"].iloc[0] == pytest.approx(1.0)                  # entering from cash
    assert d["turnover_target"].iloc[1:].abs().max() < 1e-12                   # unchanged book
    assert res.daily["n_holdings"].max() == 20 and (res.daily["cost"] >= 0).all()
    assert res.daily["cost"].iloc[0] == pytest.approx(0.001, rel=1e-6)         # 10 bps on the 100% buy-in
    assert 0.001 < res.daily["cost"].sum() < 0.003                             # later months only re-equalise drift
    m = res.monthly()
    assert isinstance(m, pd.Series) and m.index.is_monotonic_increasing
    # same call again is served from the caches (no new key-metric computations)
    n = len(km_calls)
    TC.backtest(ctx, TC.DEFAULT, start="2020-01-01", end="2020-09-30")
    assert len(km_calls) == n


def test_backtest_never_reads_prices_or_signals_after_end(km_calls):
    ctx = strat_ctx()
    a = TC.backtest(ctx, TC.DEFAULT, start="2020-01-01", end="2020-09-30")
    ctx2 = strat_ctx()
    ctx2.returns.loc["2020-10-01":] = 0.5                                      # wild future data
    ctx2.rf.loc["2020-10-01":] = 0.01
    b = TC.backtest(ctx2, TC.DEFAULT, start="2020-01-01", end="2020-09-30")
    pd.testing.assert_series_equal(a.daily["ret_net"], b.daily["ret_net"])
    assert a.daily.index[-1] <= pd.Timestamp("2020-09-30")


def test_monthly_returns_for_run_grid_drops_incomplete_last_month(km_calls):
    ctx = strat_ctx()
    full = TC.monthly_returns(TC.DEFAULT, ctx=ctx, start="2020-01-01", end="2020-09-30")
    part = TC.monthly_returns(TC.DEFAULT, ctx=ctx, start="2020-01-01", end="2020-09-15")
    assert full.index[-1] == pd.Timestamp("2020-09-30")
    assert part.index[-1] == pd.Timestamp("2020-08-31")
    assert (np.diff(full.index.values).astype("timedelta64[D]").astype(float) >= 28).all()
    cell = dict(TC.GRID[0])
    s = TC.monthly_returns(cell, ctx=ctx, start="2020-01-01", end="2020-09-30")
    assert s.dtype == float and len(s) >= 6


def test_grid_cells_share_the_expensive_work(km_calls, monkeypatch):
    ctx = strat_ctx()
    n_bench = []
    orig = C.peer_benchmark

    def counting(*a, **k):
        n_bench.append(1)
        return orig(*a, **k)

    monkeypatch.setattr(C, "peer_benchmark", counting)
    dates = ctx.month_ends("2020-05-01", "2020-06-30")
    assert len(dates) == 2
    weights = {}
    cells = [c for c in TC.GRID if c["mom_filter"] == 0.0]          # the momentum filter needs real prices
    for cell in cells:
        weights[grid_mod.cell_id(cell)] = TC.target_weights(ctx, cell, dates)
    assert len(km_calls) == 2                                                  # key metrics once per date
    assert ctx.fund_calls == 2                                                 # fundamentals/multiples once per date
    n_before_fresh = len(km_calls)
    # one size setting x (1 P/E cap + 1 EV cap) = 2 benchmark computations per date, shared by every theta
    assert len(n_bench) == 2 * 2
    # all cells together must be identical to fresh single-cell computations
    for cell in (cells[0], cells[-1]):
        fresh = TC.target_weights(strat_ctx(), cell, dates)
        pd.testing.assert_frame_equal(fresh, weights[grid_mod.cell_id(cell)])
    # LFY re-uses the key metrics but builds its own multiples table
    n_after_fresh = len(km_calls)
    TC.target_weights(ctx, dict(TC.DEFAULT, basis="LFY"), dates)
    assert len(km_calls) == n_after_fresh and n_before_fresh == 2


def test_size_filter_off_changes_peers_and_caps_change_eligibility(km_calls):
    # T_00 (cheap) has 5 equal-size peers: identical either way.  Add far-away peers to make the filters differ.
    rows = strat_rows(n_sub=4, extras=False)
    rows += [comp(f"BIG{i}", sub="SUB_00", ind="IND_00", mc=1e11, pe=20, ev=10, sector="Health Care") for i in range(3)]
    ctx = strat_ctx(rows)
    st, sig_on = TC._signals(ctx, D0, TC.resolve_params(dict(size_filter=True)), return_peers=True)
    st, sig_off = TC._signals(ctx, D0, TC.resolve_params(dict(size_filter=False)), return_peers=True)
    t_on = sig_on.set_index("yf_ticker").loc["T_00"]
    t_off = sig_off.set_index("yf_ticker").loc["T_00"]
    assert t_on["pe_npeers"] == 5 and not any(x.startswith("BIG") for x in t_on["pe_peers"])
    assert t_off["pe_npeers"] == 8 and any(x.startswith("BIG") for x in t_off["pe_peers"])
    # P/E cap 30: cheap targets stay below the cap (pe ~15.8), so nothing changes; cap 12 removes everyone
    sig_cap = TC._signals(ctx, D0, TC.resolve_params(dict(pe_cap=12)))[1]
    assert not sig_cap["comps_buy"].any()


# --------------------------------------------------------------------------------------------------
# live picks
# --------------------------------------------------------------------------------------------------
def test_live_picks_audit_table_near_misses_and_diagnostics(km_calls):
    rows = strat_rows(n_sub=8, extras=False)
    # WEAK: P/E only 10% below peers (fails the 15% test), EV/EBITDA 50% below
    rows += [comp("WEAK", sub="SUB_W", ind="IND_W", mc=1e9, pe=18, ev=5, sector="Health Care")]
    rows += [comp(f"W_{j}", sub="SUB_W", ind="IND_W", mc=1e9 * (1 + 0.01 * j), pe=20, ev=10, sector="Health Care")
             for j in range(5)]
    ctx = strat_ctx(rows)
    ctx.km_overrides = {"T_02": {"pass_leverage": False},                                       # one gate failed
                        "T_03": {"pass_leverage": False, "pass_roic": False},                  # two gates failed
                        "T_07": {"nd_ebitda": 0.5}}
    fetch = lambda ts: {t: (10.0 if t.startswith(("T_", "WEAK")) else 15.0) for t in ts}
    tab = TC.live_picks(ctx, TC.DEFAULT, D0, fetch_forward=fetch)
    buys = tab[tab["status"] == "BUY"]
    nm = tab[tab["status"] == "NEAR_MISS"]
    assert set(buys["ticker"]) == {f"T_{i:02d}" for i in (0, 1, 4, 5, 6, 7)}
    assert set(nm["ticker"]) == {"T_02", "WEAK"}                                                 # T_03 failed two gates
    assert dict(zip(nm["ticker"], nm["gate_failed"])) == {"T_02": "leverage", "WEAK": "pe_discount"}
    assert list(buys["rank"]) == [1, 2, 3, 4, 5, 6] and buys.iloc[0]["ticker"] == "T_07"      # highest discount first
    assert buys["selected"].all() and np.allclose(buys["weight"], 1 / 6) and (nm["weight"] == 0).all()
    top = buys.iloc[0]
    assert top["pe_level"] == "sub" and top["pe_npeers"] == 5 and top["pe_bench"] == 20 and top["ev_bench"] == 10
    assert top["pe_disc"] == pytest.approx(0.28) and top["ev_disc"] == pytest.approx(0.28)
    assert top["score"] == pytest.approx(0.28) and top["nd_ebitda"] == 0.5
    assert "N_07_0 20.0x" in top["pe_peers"] and "N_07_4 20.0x" in top["pe_peers"]
    assert "N_07_0 10.0x" in top["ev_peers"] and "[trimmed]" not in top["pe_peers"]
    assert top["fwd_pe_yahoo"] == 10.0 and top["fwd_pe_peer_median"] == 15.0 and bool(top["fwd_below_peers"])
    assert top["sub_industry"] == "SUB_07" and top["name"] == "T_07 Corp"
    assert {"roic", "wacc", "fcf", "margin_slope", "pass_leverage", "quality_ok", "pass_roic"} <= set(tab.columns)
    diag = tab.attrs["diagnostics"]
    assert diag["n_buy"] == 6 and diag["n_near_miss"] == 2 and diag["n_selected"] == 6
    assert diag["cash_weight"] == pytest.approx(0.0, abs=1e-12) and diag["fallback_rate"] == 0.0
    assert diag["avg_peers"] == 5.0 and diag["n_after_roic"] == 6 and diag["n_after_leverage"] == 6
    assert diag["n_comps_buy"] == 8 and diag["n_after_quality"] == 6
    # no network call is made when forward_check is off, and the table still builds
    tab2 = TC.live_picks(ctx, TC.DEFAULT, D0, forward_check=False)
    assert tab2["fwd_pe_yahoo"].isna().all() and len(tab2) == len(tab)


def test_live_picks_shows_trimmed_peers_and_survives_empty_and_failing_forward_fetch(km_calls):
    rows = strat_rows(n_sub=1, extras=False)
    # push one peer of T_00 to 2.25x the median (inside the cap of 50, outside the 2x trim band): it must show up as [trimmed]
    for r in rows:
        if r["yf_ticker"] == "N_00_4":
            r.update(net_income=r["mcap"] / 45.0, net_income_lfy=r["mcap"] / 45.0)
    ctx = strat_ctx(rows)
    cell = dict(TC.DEFAULT, pe_cap=50)
    tab = TC.live_picks(ctx, cell, D0, forward_check=False)
    assert len(tab) == 1 and "N_00_4 45.0x" in tab.iloc[0]["pe_peers"] and "[trimmed]" in tab.iloc[0]["pe_peers"]
    assert tab.iloc[0]["pe_nkept"] == 4 and tab.iloc[0]["pe_npeers"] == 5

    def boom(ts):
        raise RuntimeError("no network")

    tab2 = TC.live_picks(ctx, cell, D0, fetch_forward=boom)
    assert len(tab2) == 1 and np.isnan(tab2.iloc[0]["fwd_pe_yahoo"])
    empty = TC.live_picks(strat_ctx(strat_rows(n_sub=2, d0=0.0, step=0.0, extras=False)), TC.DEFAULT, D0,
                          forward_check=False)
    assert empty.empty and empty.attrs["diagnostics"]["n_buy"] == 0


def test_clear_cache_forces_recomputation(km_calls):
    ctx = strat_ctx(strat_rows(n_sub=3, extras=False))
    TC.target_weights(ctx, TC.DEFAULT, [D0])
    assert len(km_calls) == 1
    TC.target_weights(ctx, TC.DEFAULT, [D0])
    assert len(km_calls) == 1
    TC.clear_cache(ctx)
    TC.target_weights(ctx, TC.DEFAULT, [D0])
    assert len(km_calls) == 2
