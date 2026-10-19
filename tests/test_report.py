"""Tests for quant.backtest.report (tear sheet, grid figures, PBO and correlation charts) on synthetic data."""
from __future__ import annotations

import itertools

import numpy as np
import pandas as pd
import pytest

from quant.backtest import grid, report

DAYS = pd.bdate_range("2011-06-01", "2020-12-31")
MONTHS = pd.date_range("2011-06-30", "2020-12-31", freq="ME")


def _daily(seed: int, mu_ann: float, vol_ann: float, common=None, w=0.0) -> pd.Series:
    rng = np.random.default_rng(seed)
    r = mu_ann / 252 + vol_ann / np.sqrt(252) * rng.standard_normal(len(DAYS))
    if common is not None:
        r = (1 - w) * r + w * common
    return pd.Series(r, index=DAYS)


@pytest.fixture(scope="module")
def inputs():
    mkt = _daily(1, 0.10, 0.16)
    spy = mkt.rename("SPY")
    rsp = _daily(2, 0.09, 0.17, common=mkt.values, w=0.8)
    ew = _daily(3, 0.095, 0.17, common=mkt.values, w=0.8)
    net = _daily(4, 0.13, 0.18, common=mkt.values, w=0.6)
    gross = net + 0.0004                                         # costs of ~10 bps/yr... plenty visible as gross > net
    rf = pd.Series(0.015 / 252, index=DAYS)
    rng = np.random.default_rng(9)
    fac = pd.DataFrame(rng.normal(0.004, 0.03, (len(MONTHS), 7)),
                       columns=["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF"], index=MONTHS)
    fac["RF"] = 0.0012
    turnover = pd.Series(0.0, index=DAYS)
    turnover[turnover.index.is_month_end] = 0.25
    holdings = pd.Series(20.0, index=DAYS)
    return dict(net=net, gross=gross, benchmarks={"SPY": spy, "RSP": rsp, "EW-universe": ew}, rf=rf, factors=fac,
                turnover=turnover, holdings=holdings)


@pytest.fixture(scope="module")
def windows():
    return report.standard_windows(DAYS[0], DAYS[-1], train_end="2016-12-31", test_start="2017-01-01")


def test_standard_windows_are_clipped_and_labelled(windows):
    assert list(windows)[:4] == ["Full", "Train", "Test", "Last 36m"]
    assert windows["Train"] == (None, "2016-12-31") and windows["Test"] == ("2017-01-01", None)
    assert "2010-14" in windows and "2015-18" in windows and "2019-21" in windows
    assert "2022-26" not in windows                                  # data end in 2020


def test_tearsheet_end_to_end(tmp_path, inputs, windows):
    header = {"universe": "synthetic 500 names", "params": {"top_n": 20, "quality": "off"}, "costs": "10 bps per side",
              "survivorship": "synthetic data: none", "trials": 54}
    md = report.tearsheet("Toy Strategy", inputs["net"], inputs["gross"], inputs["benchmarks"], inputs["rf"],
                          inputs["factors"], windows, tmp_path, header, turnover=inputs["turnover"],
                          holdings=inputs["holdings"], n_boot=50, horizon_B=40,
                          extra_sections={"T3 Overfitting": "| N | DSR |\n|---|---|\n| 54 | 0.5 |"})
    assert md == tmp_path / "toy_strategy_tearsheet.md" and md.exists()
    text = md.read_text()
    for needle in ("# Toy Strategy: tear sheet", "synthetic 500 names", "top_n=20", "10 bps per side", "trials", "54",
                   "## T1 Performance", "## T2 Factor regressions", "## T7 Short-horizon", "P(beat)",
                   "Forward expectation", "T3 Overfitting", "McLean", "SPY", "RSP", "EW-universe", "Strategy (net)",
                   "Strategy (gross)", "FF5+MOM", "CAPM", "Sharpe 95% CI", "MaxDD (daily)", "Annual one-way turnover",
                   "Avg holdings", "Cost drag"):
        assert needle in text, needle
    # one T1 panel per window
    for w in windows:
        assert f"### {w} (" in text
    # no formatting leftovers
    assert "nan" not in text.lower().replace("financial", "") or "–" in text
    pngs = {p.name for p in tmp_path.glob("*.png")}
    for tag in ("C1_growth", "C2_underwater", "C3_rolling", "C4_calendar", "C5_horizons", "C8_loadings"):
        assert f"toy_strategy_{tag}.png" in pngs, tag
        assert f"toy_strategy_{tag}.png" in text                      # linked from the markdown
    assert all(p.stat().st_size > 5_000 for p in tmp_path.glob("*.png"))
    csvs = {p.name for p in tmp_path.glob("*.csv")}
    assert {"toy_strategy_T1_performance.csv", "toy_strategy_T2_factor_regressions.csv",
            "toy_strategy_T7_short_horizon.csv"} <= csvs
    t7 = pd.read_csv(tmp_path / "toy_strategy_T7_short_horizon.csv")
    assert set(t7["horizon"]) == {"13d", "63d", "126d"} and (t7["vs"] == "SPY").any()
    t2 = pd.read_csv(tmp_path / "toy_strategy_T2_factor_regressions.csv")
    assert {"CAPM", "FF3+MOM", "FF5+MOM"} <= set(t2["model"])
    assert t2["y"].str.startswith("active").any()


def test_tearsheet_return_all_and_minimal_inputs(tmp_path, inputs, windows):
    paths = report.tearsheet("Min", inputs["net"], None, {"SPY": inputs["benchmarks"]["SPY"]}, None, None,
                             {"Full": (None, None)}, tmp_path, {"universe": "u"}, n_boot=20, horizon_B=20, return_all=True)
    assert paths[0].name == "min_tearsheet.md" and all(p.exists() for p in paths)
    text = paths[0].read_text()
    assert "No factor data supplied" in text
    assert "NOT STATED" in text                                       # survivorship note is mandatory in the header
    assert not any("C8" in p.name for p in paths)


def test_tearsheet_factor_aliases_and_short_window(tmp_path, inputs):
    fac = inputs["factors"].rename(columns={"Mkt-RF": "MKT_RF", "Mom": "UMD"}).drop(columns="RF")
    fac.index = fac.index.to_period("M").to_timestamp()                 # month-START stamps like the French files
    win = {"Full": (None, None), "Tiny": ("2020-09-01", "2020-12-31")}
    md = report.tearsheet("Alias", inputs["net"], inputs["gross"], {"SPY": inputs["benchmarks"]["SPY"]}, inputs["rf"], fac,
                          win, tmp_path, {"survivorship": "n/a"}, n_boot=20, horizon_B=20, factor_windows=["Full", "Tiny"])
    text = md.read_text()
    assert "FF5+MOM" in text
    assert "Tiny: only" in text                                       # too few months for a regression: noted, not fatal
    assert "### Tiny (" in text


# ----------------------------------------------------------------------------------------------
# grid figures
# ----------------------------------------------------------------------------------------------
IDX = pd.date_range("2011-01-31", periods=96, freq="ME")
Z = np.random.default_rng(0).standard_normal(96)
Z = (Z - Z.mean()) / Z.std(ddof=1)


def _grid_result(tmp_path, levels_a=(1, 2, 3), levels_b=(10, 20, 30), levels_c=(0.1, 0.2), cats=("off", "on")):
    cells = [dict(a=a, b=b, c=c, size=s) for a, b, c, s in itertools.product(levels_a, levels_b, levels_c, cats)]

    def fn(cell):
        sr = 0.5 + 0.1 * cell["a"] - 0.002 * abs(cell["b"] - 20) + (0.3 if cell["size"] == "on" else 0) - 0.5 * cell["c"]
        return pd.Series(sr * 0.04 / np.sqrt(12) + 0.04 * Z, index=IDX)

    default = dict(a=2, b=20, c=0.1, size="on")
    gr = grid.run_grid("toyg", cells, fn, ledger=grid.Ledger(tmp_path / "ledger.csv"),
                       axes={"a": list(levels_a), "b": list(levels_b), "c": list(levels_c)}, categorical={"size": list(cats)},
                       default=default, out_dir=tmp_path / "toyg", check_prereg=False)
    return gr


def test_grid_figures_one_file_per_facet_combination(tmp_path):
    gr = _grid_result(tmp_path)
    sel = gr.select(train=("2011-01-01", "2016-12-31"), stability_B=20)
    paths = report.grid_figures(gr, ("2011-01-01", "2016-12-31"), x_axis="a", y_axis="b", facet_axes=["c", "size"],
                                out_dir=tmp_path / "figs", selected=sel, label="train")
    names = [p.name for p in paths]
    heat = [n for n in names if "C6_heatmap" in n and "overview" not in n]
    surf = [n for n in names if "C6_surface" in n]
    assert len(heat) == 4 and len(surf) == 4                         # 2 (c) x 2 (size) combinations
    assert any("overview" in n for n in names)
    assert all(p.exists() and p.stat().st_size > 5_000 for p in paths)
    assert len(set(names)) == len(names)


def test_grid_figures_without_selection_and_percent_metric(tmp_path):
    gr = _grid_result(tmp_path, levels_c=(0.1,))
    paths = report.grid_figures(gr, None, x_axis="a", y_axis="b", facet_axes=["size"], out_dir=tmp_path / "figs",
                                metric="cagr", surface=False)
    assert len(paths) == 3                                            # 2 facets + overview, no surfaces
    assert all(p.exists() for p in paths)
    with pytest.raises(ValueError):
        report.grid_figures(gr, None, x_axis="a", y_axis="a", out_dir=tmp_path / "figs")
    with pytest.raises(ValueError):
        report.grid_figures(gr, None, x_axis="a", y_axis="b", out_dir=tmp_path / "figs", metric="nope")


def test_grid_figures_two_level_axis_skips_degenerate_surface(tmp_path):
    gr = _grid_result(tmp_path, levels_a=(1, 2), levels_c=(0.1,))
    paths = report.grid_figures(gr, None, x_axis="a", y_axis="b", facet_axes=[], out_dir=tmp_path / "figs")
    assert any("heatmap_all" in p.name for p in paths) and all(p.exists() for p in paths)


# ----------------------------------------------------------------------------------------------
# PBO and correlation
# ----------------------------------------------------------------------------------------------
def test_pbo_figure(tmp_path):
    gr = _grid_result(tmp_path, levels_c=(0.1,))
    res = gr.pbo(S=8)
    paths = report.pbo_figure(res, tmp_path / "figs")
    assert len(paths) == 1 and paths[0].exists() and paths[0].stat().st_size > 5_000
    # also accepts a raw stats.cscv_pbo result
    raw = {k: res[k] for k in ("pbo", "logits", "sr_is", "sr_oos", "prob_loss")}
    assert report.pbo_figure(raw, tmp_path / "figs", name="C7_raw")[0].exists()


def test_correlation_figure(tmp_path):
    rng = np.random.default_rng(3)
    m = pd.date_range("2011-01-31", periods=96, freq="ME")
    base = rng.standard_normal(96) * 0.04
    series = {"SPY": pd.Series(base, index=m),
              "QM": pd.Series(base * 0.8 + rng.standard_normal(96) * 0.02, index=m),
              "MF": pd.Series(base * 0.7 + rng.standard_normal(96) * 0.02, index=m),
              "TC": pd.Series(base * 0.6 + rng.standard_normal(96) * 0.03, index=m)}
    p1 = report.correlation_figure(series, tmp_path)
    assert len(p1) == 1 and p1[0].exists() and p1[0].stat().st_size > 5_000
    p2 = report.correlation_figure({k: v for k, v in series.items() if k != "SPY"}, tmp_path, name="C10_nobench")
    assert p2[0].exists()
    with pytest.raises(ValueError):
        report.correlation_figure({"QM": series["QM"]}, tmp_path)


def test_md_table_formats_missing_cells():
    df = pd.DataFrame({"a": ["1", float("nan")], "b": ["x|y", "z"]}, index=["r1", "r2"])
    out = report._md_table(df, index_name="row")
    assert out.splitlines()[0] == "| row | a | b |"
    assert "–" in out and "x/y" in out


def test_markdown_fragments(tmp_path):
    gr = _grid_result(tmp_path, levels_c=(0.1,))
    train, test = ("2011-01-01", "2016-12-31"), ("2017-01-01", "2018-12-31")
    sel = gr.select(train=train, stability_B=20)
    conf = gr.confirm(test, sel)
    md = report.selection_markdown(sel, conf)
    for needle in ("chosen:", "bootstrap stability", "Neighbourhood", "Plateau result per categorical level",
                   "Confirmation on the untouched test window", "grid_median", "Spearman"):
        assert needle in md, needle
    d = gr.dsr(sel, train)
    pb = gr.pbo(train, S=8)
    t3 = report.overfitting_markdown(d, pb)
    for needle in ("Trials N (ledger", "DSR at N =", "PBO (CSCV, S=8", "Bonferroni haircut", "PSR(0)"):
        assert needle in t3, needle
    t4 = report.regression_markdown(gr.regression_table(train, B=20))
    assert "coef / SD" in t4 and "a*b" in t4 and "R2 =" in t4
    # they plug straight into a tear sheet
    days = pd.bdate_range("2011-06-01", "2016-12-31")
    r = pd.Series(np.random.default_rng(1).normal(0.0004, 0.01, len(days)), index=days)
    b = pd.Series(np.random.default_rng(2).normal(0.0003, 0.01, len(days)), index=days)
    out = report.tearsheet("Frag", r, None, {"SPY": b}, None, None, {"Full": (None, None)}, tmp_path / "ts",
                           {"survivorship": "n/a"}, n_boot=10, horizon_B=10,
                           extra_sections={"T3 Overfitting": t3, "T4 Parameters": t4, "Selection": md})
    text = out.read_text()
    assert "## T3 Overfitting" in text and "## T4 Parameters" in text and "## Selection" in text
