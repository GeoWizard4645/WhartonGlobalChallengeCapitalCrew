"""Tests for quant.backtest.grid (ledger, pre-registration, grid runner, plateau selection, confirmation)."""
from __future__ import annotations

import itertools
import json

import numpy as np
import pandas as pd
import pytest

from quant.backtest import grid, metrics

N_MONTHS = 120
IDX = pd.date_range("2011-01-31", periods=N_MONTHS, freq="ME")
SIGMA = 0.04


def _std_normal(seed: int, n: int = N_MONTHS) -> np.ndarray:
    z = np.random.default_rng(seed).standard_normal(n)
    return (z - z.mean()) / z.std(ddof=1)          # exactly mean 0, sd 1 => Sharpe of mu + SIGMA*z is exact


Z = _std_normal(0)

A_LEVELS = [1, 2, 3, 4, 5]
B_LEVELS = [1, 2, 3]
SIZE_LEVELS = ["off", "on"]
AXES = {"a": A_LEVELS, "b": B_LEVELS}
CATS = {"size": SIZE_LEVELS}
DEFAULT = {"a": 4, "b": 2, "size": "on"}
CELLS = [dict(a=a, b=b, size=s) for a, b, s in itertools.product(A_LEVELS, B_LEVELS, SIZE_LEVELS)]
SPIKE = {"a": 1, "b": 3, "size": "on"}


def target_sharpe(cell: dict) -> float:
    """Broad plateau for size='on' at a>=3, an isolated spike at (1, 3), weaker flat surface for size='off'."""
    if cell["size"] == "off":
        return 0.30
    if (cell["a"], cell["b"]) == (SPIKE["a"], SPIKE["b"]):
        return 1.50
    if cell["a"] >= 3:
        return {3: 0.88, 4: 0.92, 5: 0.90}[cell["a"]]
    return 0.50


def exact_series(sr_annual: float) -> pd.Series:
    mu = sr_annual * SIGMA / np.sqrt(12)
    return pd.Series(mu + SIGMA * Z, index=IDX)


def fn_plateau(cell: dict) -> pd.Series:           # module level => picklable for n_jobs > 1
    return exact_series(target_sharpe(cell))


def fn_negative(cell: dict) -> pd.Series:
    return exact_series(-0.2)


def fn_noise(cell: dict) -> pd.Series:
    """Zero-mean independent noise for every cell: nothing real to find."""
    seed = 1000 + CELLS.index(cell)
    return pd.Series(SIGMA * _std_normal(seed), index=IDX)


@pytest.fixture()
def ledger(tmp_path):
    return grid.Ledger(tmp_path / "ledger.csv")


def _run(fn, tmp_path, ledger, strategy="toy", **kw):
    return grid.run_grid(strategy, CELLS, fn, ledger=ledger, axes=AXES, categorical=CATS, default=DEFAULT,
                         out_dir=tmp_path / strategy, check_prereg=False, **kw)


TRAIN = ("2011-01-01", "2016-12-31")
TEST = ("2017-01-01", "2020-12-31")


# ----------------------------------------------------------------------------------------------
# ledger
# ----------------------------------------------------------------------------------------------
def test_ledger_counts_distinct_trials(tmp_path):
    led = grid.Ledger(tmp_path / "ledger.csv")
    assert led.count("s1") == 0 and len(led.read()) == 0
    led.log("s1", {"a": 1}, n_months=10, sharpe=0.5, cagr=0.1, maxdd=-0.2, notes="x")
    led.log("s1", {"a": 2}, n_months=10, sharpe=0.4)
    led.log("s1", {"a": 1}, window="test", sharpe=0.3)          # same configuration seen on another window
    led.log("s2", {"a": 1})
    assert led.count("s1") == 2                                   # distinct configurations
    assert led.count("s1", distinct=False) == 3                   # raw rows
    assert led.count("s2") == 1
    assert led.count() == 3
    led.log("s1", {"a": 1}, variant="cost=25bp")                  # a new variant is a new trial
    assert led.count("s1") == 3
    df = led.read("s1")
    assert list(df.columns) == grid.LEDGER_COLUMNS
    assert json.loads(df.loc[0, "params"]) == {"a": 1}
    # append-only: a fresh Ledger on the same file sees everything and header is written once
    assert grid.Ledger(tmp_path / "ledger.csv").count("s1") == 3
    assert (tmp_path / "ledger.csv").read_text().count("timestamp") == 1


def test_run_grid_logs_every_cell_as_a_trial(tmp_path, ledger):
    gr = _run(fn_plateau, tmp_path, ledger)
    assert gr.M.shape == (N_MONTHS, len(CELLS))
    assert ledger.count("toy") == len(CELLS)
    _run(fn_plateau, tmp_path, ledger)                            # re-running does not inflate N...
    assert ledger.count("toy") == len(CELLS)
    assert ledger.count("toy", distinct=False) == 2 * len(CELLS)  # ...but is on the record
    row = ledger.read("toy").iloc[0]
    for col in ("timestamp", "cell_id", "params", "window", "n_months", "sharpe", "cagr", "maxdd", "notes"):
        assert col in row.index and str(row[col]) != "nan"


# ----------------------------------------------------------------------------------------------
# pre-registration
# ----------------------------------------------------------------------------------------------
def test_preregistration_refuses_changed_grid(tmp_path):
    out = tmp_path / "toy"
    p = grid.preregister("toy", CELLS, AXES, CATS, DEFAULT, out_dir=out)
    assert p == out / "preregistration.json" and p.exists()
    doc = json.loads(p.read_text())
    assert doc["n_cells"] == len(CELLS) and doc["timestamp"] and doc["default"] == DEFAULT
    assert doc["primary_metric"] == "net_sharpe" and doc["selection_rule"] == "plateau_v1"

    # same content again: accepted, original timestamp kept
    grid.preregister("toy", list(reversed(CELLS)), AXES, CATS, DEFAULT, out_dir=out)
    assert json.loads(p.read_text())["timestamp"] == doc["timestamp"]

    # different grid: refused, file untouched
    with pytest.raises(grid.PreregistrationError):
        grid.preregister("toy", CELLS[:-2], AXES, CATS, DEFAULT, out_dir=out)
    with pytest.raises(grid.PreregistrationError):                # different default is a different registration
        grid.preregister("toy", CELLS, AXES, CATS, {"a": 3, "b": 2, "size": "on"}, out_dir=out)
    assert json.loads(p.read_text())["n_cells"] == len(CELLS)

    # force=True supersedes and keeps the old one in history
    new_cells = [c for c in CELLS if not (c["a"] == 5 and c["b"] == 3)]
    grid.preregister("toy", new_cells, AXES, CATS, DEFAULT, out_dir=out, force=True)
    doc2 = json.loads(p.read_text())
    assert doc2["n_cells"] == len(new_cells) and len(doc2["history"]) == 1
    assert doc2["history"][0]["content_hash"] == doc["content_hash"]


def test_preregistration_validates_design(tmp_path):
    with pytest.raises(ValueError):                               # default not in the grid
        grid.preregister("toy", CELLS, AXES, CATS, {"a": 99, "b": 2, "size": "on"}, out_dir=tmp_path / "x")
    bad = CELLS + [dict(a=7, b=1, size="on")]                     # level not declared
    with pytest.raises(ValueError):
        grid.preregister("toy", bad, AXES, CATS, DEFAULT, out_dir=tmp_path / "y")


def test_run_grid_enforces_registered_grid(tmp_path, ledger):
    out = tmp_path / "toy"
    grid.preregister("toy", CELLS, AXES, CATS, DEFAULT, out_dir=out)
    gr = grid.run_grid("toy", CELLS, fn_plateau, ledger=ledger, out_dir=out)      # axes/default come from the file
    assert gr.default == DEFAULT and set(gr.axes) == {"a", "b"}
    with pytest.raises(grid.PreregistrationError):
        grid.run_grid("toy", CELLS[:10], fn_plateau, ledger=ledger, out_dir=out)
    assert ledger.count("toy") == len(CELLS)                       # the refused run logged nothing


# ----------------------------------------------------------------------------------------------
# runner
# ----------------------------------------------------------------------------------------------
def test_run_grid_metrics_match_metrics_module(tmp_path, ledger):
    rf = pd.Series(0.002, index=IDX)
    gr = _run(fn_plateau, tmp_path, ledger, rf=rf)
    m = gr.metrics(TRAIN)
    assert set(["sharpe", "cagr", "vol", "maxdd", "tstat", "n_months"]) <= set(m.columns)
    cid = gr.cell_ids[7]
    r = gr.M[cid].loc["2011-01-01":"2016-12-31"]
    assert m.loc[cid, "sharpe"] == pytest.approx(metrics.sharpe(r.values, 0.002, 12))
    assert m.loc[cid, "n_months"] == 72
    assert m.loc[cid, "cagr"] == pytest.approx(metrics.cagr(r.values, 12))
    # vectorised Sharpe used by the bootstrap/CSCV equals the metrics module
    v = grid._sharpe_vec(gr._excess(TRAIN))
    np.testing.assert_allclose(v, m["sharpe"].to_numpy(), rtol=1e-9)
    assert gr.metrics(TRAIN, with_params=True)[["a", "b", "size"]].shape[0] == len(CELLS)


def test_run_grid_parallel_matches_serial(tmp_path, ledger):
    serial = _run(fn_plateau, tmp_path, ledger)
    par = _run(fn_plateau, tmp_path, ledger, n_jobs=2)            # falls back to serial if the pool is unavailable
    pd.testing.assert_frame_equal(serial.M, par.M)
    # an unpicklable function must not crash n_jobs > 1
    closure = _run(lambda c: fn_plateau(c), tmp_path, ledger, n_jobs=2)
    pd.testing.assert_frame_equal(serial.M, closure.M)


def test_run_grid_error_handling(tmp_path, ledger):
    def boom(cell):
        if cell["a"] == 3 and cell["b"] == 1 and cell["size"] == "on":
            raise RuntimeError("no data")
        return fn_plateau(cell)
    with pytest.raises(RuntimeError):
        _run(boom, tmp_path, ledger)
    gr = _run(boom, tmp_path, ledger, on_error="nan")
    assert len(gr.errors) == 1 and gr.M.isna().all().sum() == 1
    daily = lambda c: pd.Series(0.001, index=pd.bdate_range("2012-01-02", periods=300))  # noqa: E731
    with pytest.raises(ValueError, match="monthly"):
        _run(daily, tmp_path, ledger)


# ----------------------------------------------------------------------------------------------
# plateau selection
# ----------------------------------------------------------------------------------------------
def test_select_prefers_broad_plateau_over_isolated_spike(tmp_path, ledger):
    gr = _run(fn_plateau, tmp_path, ledger)
    res = gr.select(train=TRAIN, stability_B=100, seed=1)
    spike_id = gr.resolve(SPIKE)
    # the plain argmax is the spike ...
    assert res["variants"]["argmax"]["cell_id"] == spike_id
    # ... the plateau rule is not fooled
    assert res["cell_id"] != spike_id
    assert res["chosen"]["size"] == "on" and res["chosen"]["a"] >= 3
    assert not res["fallback"] and res["fallback_reason"] is None
    assert res["sharpe"] == pytest.approx(gr.metrics(TRAIN).loc[res["cell_id"], "sharpe"])
    assert res["plateau_width"] >= 6
    assert res["peak_ratio"] <= 1.25
    # neighbourhood table: self row first, then one-step neighbours along the ordinal axes only
    nb = res["neighborhood"]
    assert nb.iloc[0]["role"] == "self" and (nb["role"].iloc[1:] == "neighbor").all()
    assert {"a", "b", "size", "sharpe", "cell_id"} <= set(nb.columns)
    assert 3 <= len(nb) <= 5
    # stability
    st = res["stability"]
    assert st["B"] == 100 and st["share_within_one"] >= 0.5 and st["passed"]
    # categorical handling: both levels evaluated, 'on' kept (default level and better)
    pc = res["per_category"]
    assert set(pc["category"]) == {"size=off", "size=on"}
    assert pc.set_index("category").loc["size=on", "chosen"]
    assert any("stability" in r for r in res["reasons"])
    assert gr.last_selection is res


def test_select_categorical_tiebreak_prefers_default_unless_clearly_better(tmp_path, ledger):
    # 'off' level plateau is better than 'on' by only 0.05 (< 0.10 margin): the default category 'on' must win
    def fn(cell):
        base = 0.80 if cell["size"] == "on" else 0.85
        return exact_series(base)
    gr = _run(fn, tmp_path, ledger)
    res = gr.select(train=TRAIN, stability_B=0)
    assert res["chosen"]["size"] == "on"
    # a 0.30 better 'off' level wins
    def fn2(cell):
        return exact_series(0.80 if cell["size"] == "on" else 1.10)
    gr2 = _run(fn2, tmp_path, ledger)
    res2 = gr2.select(train=TRAIN, stability_B=0)
    assert res2["chosen"]["size"] == "off"
    assert res2["stability"] is None                              # B=0 skips the check


def test_select_tie_breaks_toward_default(tmp_path, ledger):
    gr = _run(lambda c: exact_series(0.9), tmp_path, ledger)      # perfectly flat surface
    res = gr.select(train=TRAIN, stability_B=0)
    assert res["cell_id"] == res["default_cell_id"]


def test_select_falls_back_to_default_without_eligible_cell(tmp_path, ledger):
    gr = _run(fn_negative, tmp_path, ledger)
    res = gr.select(train=TRAIN, stability_B=50)
    assert res["fallback"] and res["is_default"] and res["chosen"] == DEFAULT
    assert "eligible" in res["fallback_reason"]
    assert any("FALLBACK" in r for r in res["reasons"])


def test_select_falls_back_to_default_on_noise(tmp_path, ledger):
    gr = _run(fn_noise, tmp_path, ledger)
    res = gr.select(train=("2011-01-01", "2020-12-31"), stability_B=100, seed=3)
    # pure noise: either nothing is eligible or the selection is unstable under resampling -> default
    assert res["fallback"], res["reasons"]
    assert res["chosen"] == DEFAULT and res["is_default"]
    assert res["fallback_reason"]


def test_select_requires_default_in_grid(tmp_path, ledger):
    gr = _run(fn_plateau, tmp_path, ledger)
    with pytest.raises(ValueError):
        gr.select(train=TRAIN, default={"a": 99, "b": 2, "size": "on"})


# ----------------------------------------------------------------------------------------------
# confirmation and diagnostics
# ----------------------------------------------------------------------------------------------
def test_confirm_output_shape(tmp_path, ledger):
    gr = _run(fn_plateau, tmp_path, ledger)
    sel = gr.select(train=TRAIN, stability_B=50)
    c = gr.confirm(TEST, sel)
    tab = c["table"]
    assert list(tab.index) == ["chosen", "default", "grid_median"]
    assert list(tab.columns) == ["sharpe", "cagr", "vol", "maxdd", "tstat", "n_months"]
    assert tab.loc["chosen", "n_months"] == 48
    mt = gr.metrics(TEST)
    assert tab.loc["chosen", "sharpe"] == pytest.approx(mt.loc[sel["cell_id"], "sharpe"])
    assert tab.loc["default", "sharpe"] == pytest.approx(mt.loc[sel["default_cell_id"], "sharpe"])
    assert tab.loc["grid_median", "sharpe"] == pytest.approx(mt["sharpe"].median())
    for k in ("chosen_id", "default_id", "chosen_minus_default_sharpe", "chosen_rank_pct",
              "spearman_train_test", "test_over_train_sharpe", "criteria", "notes"):
        assert k in c
    assert 0.0 <= c["chosen_rank_pct"] <= 1.0
    assert c["spearman_train_test"] == pytest.approx(1.0)         # identical landscape in both windows
    assert c["test_over_train_sharpe"] > 0.5
    assert c["criteria"]["test_sharpe_positive"] and not c["notes"]
    # accepts a params dict too
    c2 = gr.confirm(TEST, sel["chosen"])
    assert c2["chosen_id"] == c["chosen_id"]
    # looking again with a different choice burns the window
    c3 = gr.confirm(TEST, gr.resolve({"a": 1, "b": 1, "size": "off"}))
    assert any("BURNED" in n for n in c3["notes"])


def test_dsr_uses_ledger_trial_count(tmp_path, ledger):
    rng = np.random.default_rng(5)
    def fn(cell):
        sr = 0.6 if (cell["a"], cell["size"]) == (4, "on") else 0.1
        return exact_series(sr) + pd.Series(0.01 * rng.standard_normal(N_MONTHS), index=IDX)
    gr = _run(fn, tmp_path, ledger)
    for i in range(20):                                           # 20 extra exploratory trials in the ledger
        ledger.log("toy", {"explore": i}, notes="exploratory")
    best = gr.resolve({"a": 4, "b": 2, "size": "on"})
    d = gr.dsr(best, window=None)
    assert d["N_ledger"] == len(CELLS) + 20 and d["N_used"] == d["N_ledger"]
    assert d["N_cells"] == len(CELLS)
    assert 1.0 <= d["N_eff"] <= len(CELLS)
    for k in ("dsr", "dsr_neff", "dsr_ncells", "sr0_ann", "sr_ann", "t_stat", "haircut_sharpe"):
        assert k in d and np.isfinite(d[k])
    assert 0.0 <= d["dsr"] <= 1.0
    # more trials => lower DSR
    d_small = gr.dsr(best, N=2)
    assert d_small["dsr"] >= d["dsr"]


def test_pbo_and_regression_and_csv(tmp_path, ledger):
    def fn(cell):
        seed = 77 + CELLS.index(cell)
        rng = np.random.default_rng(seed)
        return pd.Series(0.004 + 0.04 * rng.standard_normal(N_MONTHS), index=IDX)
    gr = _run(fn, tmp_path, ledger)
    res = gr.pbo(S=8)                                             # plateau selector (default)
    assert 0.0 <= res["pbo"] <= 1.0 and res["n_combos"] == 70 and res["selector"] == "plateau"
    assert len(res["logits"]) == 70 and len(res["sr_is_ann"]) == 70
    res_am = gr.pbo(S=8, selector="argmax")
    assert res_am["selector"] == "argmax" and 0.0 <= res_am["pbo"] <= 1.0

    tab = gr.regression_table(None, B=30)
    assert {"coef", "boot_sd", "t_boot"} <= set(tab.columns)
    assert "const" in tab.index and "a" in tab.index and "b" in tab.index and "a*b" in tab.index
    assert "size=on" in tab.index
    assert 0.0 <= tab.attrs["r2"] <= 1.0 and tab.attrs["n_cells"] == len(CELLS)
    assert (tab["boot_sd"] > 0).all()

    paths = gr.to_csv(tmp_path / "csv", windows={"train": TRAIN, "test": TEST})
    names = {p.name for p in paths}
    assert {"grid_cells.csv", "grid_monthly_returns.csv", "grid_metrics_train.csv", "grid_metrics_test.csv"} <= names
    assert all(p.exists() for p in paths)
    m = pd.read_csv(tmp_path / "csv" / "grid_metrics_train.csv", index_col=0)
    assert len(m) == len(CELLS) and "sharpe" in m.columns and "size" in m.columns
