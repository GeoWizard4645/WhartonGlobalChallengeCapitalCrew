"""Tests for quant/strategies/momentum_mf.py: the grid, its pre-registration and the Magic Formula veto."""
from __future__ import annotations

import json

import numpy as np
import pandas as pd
import pytest

from quant.strategies import magic_formula as mf
from quant.strategies import momentum_mf as mm
from quant.strategies import quality_momentum as qm


def test_grid_is_mf_cut_by_n_on_the_quality_momentum_base():
    assert len(mm.GRID) == len(mm.AXES["mf_cut"]) * len(mm.AXES["N"]) == 12
    assert mm.DEFAULT in mm.GRID
    for cell in mm.GRID:
        assert {k: cell[k] for k in mm.BASE} == mm.BASE
        assert qm._params(cell)["mf_cut"] == cell["mf_cut"]       # every cell is a valid quality-momentum config


def test_preregister_roundtrip(tmp_path):
    path = mm.register(out_dir=tmp_path)
    doc = json.loads(path.read_text())
    assert doc["strategy"] == "momentum_mf" and len(doc["grid"]) == 12
    assert mm.register(out_dir=tmp_path) == path                 # idempotent


@pytest.mark.parametrize("value, expected", [(None, None), ("none", None), (0, 0.0), (0.5, 0.5)])
def test_mf_cut_is_normalised(value, expected):
    assert qm._params(dict(mf_cut=value))["mf_cut"] == expected


@pytest.mark.parametrize("value", [1.0, -0.1, 2])
def test_mf_cut_outside_zero_one_is_rejected(value):
    with pytest.raises(ValueError):
        qm._params(dict(mf_cut=value))


def _screen():
    # cik 1..5 ranked best..worst; 6 has non-positive EBIT; 7 cannot be ranked (e.g. a bank); 8 is not in the screen
    return pd.DataFrame({"mf_pct": [0.2, 0.4, 0.6, 0.8, 1.0, np.nan, np.nan],
                         "mf_bad": [False, False, False, False, False, True, False]},
                        index=pd.Index([1, 2, 3, 4, 5, 6, 7], name="cik"))


def test_keep_mask_zero_cut_only_vetoes_nonpositive_ebit_ev_or_capital():
    keep = mf.keep_mask(_screen(), [1, 2, 3, 4, 5, 6, 7, 8], 0.0)
    assert keep.tolist() == [True, True, True, True, True, False, True, True]


def test_keep_mask_half_cut_drops_the_worst_half_and_keeps_unrankable_names():
    keep = mf.keep_mask(_screen(), [5, 1, 3, 4, 2, 6, 7, 8], 0.5)
    assert keep.index.tolist() == [5, 1, 3, 4, 2, 6, 7, 8]       # in the caller's order
    assert keep.tolist() == [False, True, False, False, True, False, True, True]


def test_keep_mask_is_monotone_in_the_cut():
    ciks = list(range(1, 9))
    kept = [mf.keep_mask(_screen(), ciks, c).sum() for c in mm.AXES["mf_cut"]]
    assert kept == sorted(kept, reverse=True)
