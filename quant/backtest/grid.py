"""Trial ledger, pre-registered grid runner, plateau parameter selection, train/test confirmation.

Implements the parameter-selection protocol of research/06_backtest_methodology.md sections 4-5
(and research/04_trading_comps.md section 7):

1. ``preregister`` writes ``output/<strategy>/preregistration.json`` (timestamped) BEFORE any run and
   refuses to overwrite a different grid unless ``force=True``.
2. ``run_grid`` evaluates every cell (``fn(cell) -> monthly NET return series``), builds the
   months x cells matrix ``M`` and appends every cell to the append-only :class:`Ledger`
   (every evaluated cell is a trial; ``Ledger.count`` is N for the Deflated Sharpe Ratio).
3. ``GridResult.select`` applies the plateau rule (section 5.4) on the TRAIN window: plateau within each
   categorical level, categorical tie-break preferring the literature default unless better by
   ``cat_margin`` Sharpe, tie-break toward the default within ``tie_tol``, bootstrap stability check,
   fallback to the default when nothing is eligible or the choice is unstable.
4. ``GridResult.confirm`` looks at the TEST window once (chosen vs default vs grid median).
5. ``GridResult.pbo`` / ``dsr`` / ``regression_table`` wrap ``stats.cscv_pbo`` / ``stats.dsr`` /
   ``stats.grid_regression_bootstrap``.

All statistics (Sharpe, CAGR, PBO, DSR, plateau rule, regression bootstrap) come from
``quant.backtest.metrics`` / ``quant.backtest.stats``; this module only orchestrates them.
"""
from __future__ import annotations

import csv
import hashlib
import itertools
import json
import logging
import pickle
from collections import deque
from concurrent.futures import ProcessPoolExecutor
from concurrent.futures.process import BrokenProcessPool
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Callable, Iterable, Sequence

import numpy as np
import pandas as pd

from . import metrics, stats

log = logging.getLogger(__name__)

PPY = 12  # grid evaluation is on monthly returns
LEDGER_COLUMNS = ["timestamp", "strategy", "cell_id", "params", "window", "n_months",
                  "sharpe", "cagr", "maxdd", "notes"]
PREREG_FILENAME = "preregistration.json"
SELECTION_RULE = "plateau_v1"

__all__ = ["Ledger", "GridResult", "PreregistrationError", "preregister", "run_grid",
           "cell_id", "grid_hash", "load_preregistration"]


class PreregistrationError(ValueError):
    """Raised when a grid differs from what was pre-registered."""


# ----------------------------------------------------------------------------------------------
# helpers
# ----------------------------------------------------------------------------------------------
def _json_default(o: Any):
    if isinstance(o, (np.integer,)):
        return int(o)
    if isinstance(o, (np.floating,)):
        return float(o)
    if isinstance(o, (np.bool_,)):
        return bool(o)
    if isinstance(o, np.ndarray):
        return o.tolist()
    if isinstance(o, (pd.Timestamp, datetime)):
        return o.isoformat()
    if isinstance(o, Path):
        return str(o)
    return str(o)


def _canon(obj: Any) -> str:
    """Canonical JSON (sorted keys, numpy-safe) used for hashing and ledger storage."""
    return json.dumps(obj, sort_keys=True, default=_json_default, separators=(",", ":"))


def cell_id(params: dict, variant: str = "") -> str:
    """Stable 10-hex-char identifier of a parameter dict (plus an optional free-text variant tag)."""
    h = hashlib.sha1((_canon(params) + "|" + variant).encode()).hexdigest()
    return h[:10]


def grid_hash(cells: Sequence[dict]) -> str:
    """Order-insensitive hash of a list of cells."""
    lines = sorted(_canon(c) for c in cells)
    return hashlib.sha256("\n".join(lines).encode()).hexdigest()[:16]


def _utcnow() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="seconds")


def _default_out_dir(strategy: str) -> Path:
    from quant import settings
    return Path(settings.OUTPUT) / strategy


def _to_ts(x, end: bool = False) -> pd.Timestamp | None:
    """Parse a window bound. 'YYYY' / 'YYYY-MM' ends extend to the end of the year / month."""
    if x is None:
        return None
    if isinstance(x, str):
        s = x.strip()
        if end and len(s) == 4 and s.isdigit():
            return pd.Timestamp(year=int(s), month=12, day=31)
        if end and len(s) == 7 and s[4] == "-":
            return pd.Period(s, freq="M").end_time.normalize()
    return pd.Timestamp(x).normalize()


def _window_mask(index: pd.DatetimeIndex, window) -> np.ndarray:
    if window is None:
        return np.ones(len(index), dtype=bool)
    start, end = window
    s, e = _to_ts(start), _to_ts(end, end=True)
    m = np.ones(len(index), dtype=bool)
    if s is not None:
        m &= np.asarray(index >= s)
    if e is not None:
        m &= np.asarray(index <= e)
    return m


def _window_label(window) -> str:
    if window is None:
        return "full"
    s, e = window
    return f"{'' if s is None else pd.Timestamp(_to_ts(s)).date()}..{'' if e is None else pd.Timestamp(_to_ts(e, True)).date()}"


def _sharpe_vec(X: np.ndarray, min_obs: int = 12, ppy: int = PPY) -> np.ndarray:
    """Annualised Sharpe of every column of an (n x k) matrix of EXCESS returns (NaN-aware).

    Identical to ``metrics.sharpe`` column by column; vectorised because the bootstrap-stability check
    and the CSCV selector call it thousands of times.
    """
    with np.errstate(invalid="ignore", divide="ignore"):
        cnt = np.sum(np.isfinite(X), axis=0)
        mu = np.nanmean(X, axis=0)
        sd = np.nanstd(X, axis=0, ddof=1)
        out = mu / sd * np.sqrt(ppy)
    out = np.where((cnt >= min_obs) & np.isfinite(out) & (sd > 0), out, np.nan)
    return out


# ----------------------------------------------------------------------------------------------
# Ledger
# ----------------------------------------------------------------------------------------------
class Ledger:
    """Append-only CSV log of every configuration ever evaluated (research/06 section 4.3).

    Columns: timestamp, strategy, cell_id, params (JSON), window, n_months, sharpe, cagr, maxdd, notes.
    ``count(strategy)`` is the number of DISTINCT configurations (cell ids) evaluated for a strategy,
    i.e. the N used for the Deflated Sharpe Ratio; re-running or re-reading the same cell does not inflate
    it, while any new parameter set, follow-up test or exploratory variant does.
    """

    def __init__(self, path: str | Path | None = None):
        if path is None:
            from quant import settings
            path = Path(settings.OUTPUT) / "ledger.csv"
        self.path = Path(path)

    # -- writing -------------------------------------------------------------------------------
    def log(self, strategy: str, params: dict, window: str = "full", n_months: int | None = None,
            sharpe: float | None = None, cagr: float | None = None, maxdd: float | None = None,
            notes: str = "", cell_id_: str | None = None, variant: str = "") -> str:
        """Append one trial. Returns its cell id."""
        cid = cell_id_ or cell_id(params, variant)
        self.log_rows([dict(strategy=strategy, cell_id=cid, params=params, window=window,
                            n_months=n_months, sharpe=sharpe, cagr=cagr, maxdd=maxdd, notes=notes)])
        return cid

    def log_rows(self, rows: Iterable[dict]) -> int:
        rows = list(rows)
        if not rows:
            return 0
        self.path.parent.mkdir(parents=True, exist_ok=True)
        new = not self.path.exists() or self.path.stat().st_size == 0
        ts = _utcnow()
        with open(self.path, "a", newline="") as fh:
            w = csv.writer(fh)
            if new:
                w.writerow(LEDGER_COLUMNS)
            for r in rows:
                params = r.get("params", {})
                w.writerow([
                    r.get("timestamp", ts), r["strategy"], r.get("cell_id") or cell_id(params),
                    params if isinstance(params, str) else _canon(params), r.get("window", "full"),
                    "" if r.get("n_months") is None else int(r["n_months"]),
                    _fmt(r.get("sharpe")), _fmt(r.get("cagr")), _fmt(r.get("maxdd")), r.get("notes", ""),
                ])
        return len(rows)

    # -- reading -------------------------------------------------------------------------------
    def read(self, strategy: str | None = None) -> pd.DataFrame:
        if not self.path.exists() or self.path.stat().st_size == 0:
            return pd.DataFrame(columns=LEDGER_COLUMNS)
        df = pd.read_csv(self.path, dtype={"cell_id": str, "params": str, "window": str, "notes": str,
                                           "strategy": str})
        if strategy is not None:
            df = df[df["strategy"] == strategy]
        return df.reset_index(drop=True)

    def count(self, strategy: str | None = None, distinct: bool = True) -> int:
        """Number of trials for ``strategy`` (all strategies if None). ``distinct`` counts unique cell ids."""
        df = self.read(strategy)
        if df.empty:
            return 0
        if distinct:
            return int(df[["strategy", "cell_id"]].drop_duplicates().shape[0])
        return int(len(df))

    def __len__(self) -> int:
        return len(self.read())


def _fmt(x) -> str:
    if x is None:
        return ""
    try:
        if np.isnan(x):
            return ""
    except TypeError:
        return str(x)
    return f"{float(x):.6g}"


# ----------------------------------------------------------------------------------------------
# Pre-registration
# ----------------------------------------------------------------------------------------------
def _norm_level(v):
    if isinstance(v, (np.integer,)):
        return int(v)
    if isinstance(v, (np.floating,)):
        return float(v)
    if isinstance(v, (np.bool_,)):
        return bool(v)
    return v


def _same_level(a, b) -> bool:
    """Level equality that keeps bool distinct from int and tolerates float noise (0.1 + 0.05 vs 0.15)."""
    a, b = _norm_level(a), _norm_level(b)
    if isinstance(a, bool) or isinstance(b, bool):
        return isinstance(a, bool) and isinstance(b, bool) and a == b
    if isinstance(a, (int, float)) and isinstance(b, (int, float)):
        return bool(np.isclose(a, b, rtol=1e-9, atol=1e-12))
    return a == b


def _level_index(levels: Sequence, value) -> int:
    for i, lv in enumerate(levels):
        if _same_level(lv, value):
            return i
    raise KeyError(f"value {value!r} not among levels {list(levels)!r}")


def _core_content(grid, axes, categorical, default, primary_metric) -> dict:
    return dict(grid=sorted((json.loads(_canon(c)) for c in grid), key=_canon),
                axes=json.loads(_canon(axes)), categorical=json.loads(_canon(categorical)),
                default=json.loads(_canon(default)), primary_metric=primary_metric)


def _validate_design(grid: Sequence[dict], axes: dict, categorical: dict, default: dict) -> None:
    keys = list(axes) + list(categorical)
    if not set(axes).isdisjoint(categorical):
        raise ValueError("an axis cannot be both ordinal and categorical")
    seen = {}
    for c in grid:
        for k in keys:
            if k not in c:
                raise ValueError(f"cell {c!r} is missing parameter {k!r}")
            lv = axes.get(k, categorical.get(k))
            try:
                _level_index(lv, c[k])
            except KeyError:
                raise ValueError(f"cell value {k}={c[k]!r} not among declared levels {list(lv)!r}") from None
        sig = _canon({k: c[k] for k in keys})
        if sig in seen:
            raise ValueError(f"two cells share the same axis/categorical coordinates: {sig}")
        seen[sig] = True
    dsig = {}
    for k in keys:
        if k not in default:
            raise ValueError(f"default is missing parameter {k!r}")
        dsig[k] = default[k]
    if _canon({k: _norm_level(dsig[k]) for k in keys}) not in {
            _canon({k: _norm_level(c[k]) for k in keys}) for c in grid}:
        raise ValueError(f"the default {dsig!r} is not a cell of the grid")


def preregister(strategy: str, grid: list[dict], axes: dict[str, list], categorical: dict[str, list],
                default: dict, primary_metric: str = "net_sharpe", out_dir: str | Path | None = None,
                force: bool = False, extra: dict | None = None) -> Path:
    """Write ``<out_dir>/preregistration.json`` (default ``output/<strategy>/``) BEFORE any run.

    * ``grid``: the full list of cell dicts (each cell is a trial; ``len(grid)`` is the minimum N for DSR).
    * ``axes``: ordinal axes -> ordered levels (smoothed/neighbourhood-compared by the plateau rule).
    * ``categorical``: categorical axes -> levels (NOT smoothed; plateau is run within each level).
    * ``default``: literature default (the fallback); must be a cell of the grid.

    If a file already exists with the same content, it is left untouched (the original timestamp is kept).
    If it holds a different grid/axes/categorical/default/primary metric, a :class:`PreregistrationError`
    is raised unless ``force=True`` (then the old registration is kept in ``history``).
    """
    grid = [dict(c) for c in grid]
    axes = {k: list(v) for k, v in axes.items()}
    categorical = {k: list(v) for k, v in categorical.items()}
    _validate_design(grid, axes, categorical, default)
    out_dir = Path(out_dir) if out_dir is not None else _default_out_dir(strategy)
    path = out_dir / PREREG_FILENAME
    core = _core_content(grid, axes, categorical, default, primary_metric)
    chash = hashlib.sha256(_canon(core).encode()).hexdigest()[:16]

    history: list[dict] = []
    if path.exists():
        old = json.loads(path.read_text())
        if old.get("content_hash") == chash:
            log.info("preregistration for %s already on file (%s); unchanged", strategy, old.get("timestamp"))
            return path
        if not force:
            raise PreregistrationError(
                f"{path} already holds a DIFFERENT pre-registration (hash {old.get('content_hash')} vs {chash}, "
                f"registered {old.get('timestamp')}). Changing a registered grid after the fact defeats the "
                f"protocol; pass force=True to supersede it (the old one is kept in 'history').")
        history = list(old.get("history", [])) + [dict(timestamp=old.get("timestamp"),
                                                       content_hash=old.get("content_hash"),
                                                       n_cells=old.get("n_cells"),
                                                       grid_hash=old.get("grid_hash"))]
    from quant import settings
    doc = dict(
        strategy=strategy, timestamp=_utcnow(), primary_metric=primary_metric,
        selection_rule=SELECTION_RULE, lam=1.0, peak_ratio_max=1.25, tie_tol=0.02, cat_margin=0.10,
        stability=dict(B=500, min_share_within_one_step=0.5),
        split=dict(train_end=settings.TRAIN_END, test_start=settings.TEST_START),
        test_window_policy="single_look",
        n_cells=len(grid), grid_hash=grid_hash(grid), content_hash=chash,
        axes=axes, categorical=categorical, default=default, grid=grid,
        extra=extra or {}, history=history,
    )
    out_dir.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(doc, indent=2, default=_json_default) + "\n")
    log.info("pre-registered %d cells for %s -> %s", len(grid), strategy, path)
    return path


def load_preregistration(strategy: str, out_dir: str | Path | None = None) -> dict | None:
    out_dir = Path(out_dir) if out_dir is not None else _default_out_dir(strategy)
    path = out_dir / PREREG_FILENAME
    return json.loads(path.read_text()) if path.exists() else None


# ----------------------------------------------------------------------------------------------
# Grid layout (maps flat cell list <-> ordinal ndarray per categorical combination)
# ----------------------------------------------------------------------------------------------
@dataclass
class _Layout:
    axes: dict[str, list]
    cats: dict[str, list]
    pos: dict[tuple, np.ndarray]          # categorical key -> int array over ordinal axes (-1 = no cell)
    key_of: list[tuple]                   # per cell position: (cat_key, ordinal index tuple)
    default_ck: tuple | None = None
    default_ix: tuple | None = None
    default_pos: int | None = None

    @property
    def shape(self) -> tuple:
        return tuple(len(v) for v in self.axes.values())

    @classmethod
    def build(cls, cells: Sequence[dict], axes: dict[str, list], categorical: dict[str, list],
              default: dict | None) -> "_Layout":
        if not axes:
            raise ValueError("plateau selection needs at least one ordinal axis")
        axes = {k: list(v) for k, v in axes.items()}
        categorical = {k: list(v) for k, v in (categorical or {}).items()}
        shape = tuple(len(v) for v in axes.values())
        cat_keys = list(itertools.product(*[range(len(v)) for v in categorical.values()])) or [()]
        pos = {ck: np.full(shape, -1, dtype=int) for ck in cat_keys}
        key_of: list[tuple] = []
        for i, c in enumerate(cells):
            ix = tuple(_level_index(lv, c[k]) for k, lv in axes.items())
            ck = tuple(_level_index(lv, c[k]) for k, lv in categorical.items())
            if pos[ck][ix] != -1:
                raise ValueError(f"cells {pos[ck][ix]} and {i} share coordinates {ix}/{ck}; the grid must be unique "
                                 f"over the ordinal+categorical axes (put fixed params outside the axes)")
            pos[ck][ix] = i
            key_of.append((ck, ix))
        lay = cls(axes, categorical, pos, key_of)
        if default is not None:
            try:
                lay.default_ix = tuple(_level_index(lv, default[k]) for k, lv in axes.items())
                lay.default_ck = tuple(_level_index(lv, default[k]) for k, lv in categorical.items())
                p = int(pos[lay.default_ck][lay.default_ix])
                lay.default_pos = p if p >= 0 else None
            except (KeyError, IndexError):
                lay.default_ix = lay.default_ck = lay.default_pos = None
        return lay

    def array(self, v: np.ndarray, ck: tuple) -> np.ndarray:
        p = self.pos[ck]
        f = np.full(p.shape, np.nan)
        m = p >= 0
        f[m] = v[p[m]]
        return f

    def neighbors(self, ix: tuple) -> list[tuple[int, int, tuple]]:
        """Von Neumann neighbours: (axis, step, index)."""
        out = []
        for ax in range(len(ix)):
            for d in (-1, 1):
                j = list(ix)
                j[ax] += d
                if 0 <= j[ax] < self.shape[ax]:
                    out.append((ax, d, tuple(j)))
        return out


@dataclass
class _Pick:
    pos: int
    ck: tuple
    ix: tuple
    score: float
    peak: float
    per_cat: dict = field(default_factory=dict)   # ck -> (ix, score, peak, n_eligible)


def _plateau_pick(v: np.ndarray, lay: _Layout, *, lam: float, floor: float, peak_ratio_max: float,
                  tie_tol: float, cat_margin: float) -> _Pick | None:
    """Section 5.4 on one vector of per-cell metric values; None if no cell is eligible anywhere."""
    per_cat: dict[tuple, tuple] = {}
    for ck in lay.pos:
        f = lay.array(v, ck)
        if not np.isfinite(f).any():
            continue
        ix, sc, pk, diag = stats.plateau_select(
            f, lam=lam, min_nbrs=2, require_pos=True, floor=floor, peak_ratio_max=peak_ratio_max,
            default_index=lay.default_ix, tie_tol=tie_tol)
        if ix is None:
            continue
        per_cat[ck] = (tuple(ix), float(sc), float(pk), int(np.sum(diag["eligible"])))
    if not per_cat:
        return None
    best_ck = max(per_cat, key=lambda k: per_cat[k][1])
    ck = best_ck
    if lay.default_ck in per_cat and best_ck != lay.default_ck:
        # categorical tie-break: keep the default category unless the other is better by >= cat_margin
        if per_cat[best_ck][1] < per_cat[lay.default_ck][1] + cat_margin:
            ck = lay.default_ck
    ix, sc, pk, _n = per_cat[ck]
    return _Pick(pos=int(lay.pos[ck][ix]), ck=ck, ix=ix, score=sc, peak=pk, per_cat=per_cat)


def _plateau_width(f: np.ndarray, ix: tuple, thr: float) -> int:
    """Number of cells connected to ``ix`` (von Neumann) with f >= thr."""
    seen = {ix}
    dq = deque([ix])
    shape = f.shape
    while dq:
        cur = dq.popleft()
        for ax in range(len(cur)):
            for d in (-1, 1):
                j = list(cur)
                j[ax] += d
                if 0 <= j[ax] < shape[ax]:
                    t = tuple(j)
                    if t not in seen and np.isfinite(f[t]) and f[t] >= thr:
                        seen.add(t)
                        dq.append(t)
    return len(seen)


# ----------------------------------------------------------------------------------------------
# GridResult
# ----------------------------------------------------------------------------------------------
class GridResult:
    """Container for a pre-registered grid evaluation.

    Attributes
    ----------
    M : DataFrame, months x cells (columns = cell ids), monthly NET returns.
    params : DataFrame indexed by cell id with one column per parameter key.
    cells : list of the cell dicts, in column order.
    rf : monthly risk-free Series (or None => Sharpe on raw returns).
    """

    def __init__(self, strategy: str, cells: list[dict], M: pd.DataFrame, rf: pd.Series | None = None,
                 ledger: Ledger | None = None, errors: dict | None = None, axes: dict | None = None,
                 categorical: dict | None = None, default: dict | None = None,
                 out_dir: str | Path | None = None, primary_metric: str = "net_sharpe"):
        self.strategy = strategy
        self.cells = [dict(c) for c in cells]
        self.M = M
        self.cell_ids = list(M.columns)
        self.params = pd.DataFrame(self.cells, index=self.cell_ids)
        self.ledger = ledger
        self.errors = errors or {}
        self.axes = {k: list(v) for k, v in (axes or {}).items()}
        self.categorical = {k: list(v) for k, v in (categorical or {}).items()}
        self.default = dict(default) if default else None
        self.out_dir = Path(out_dir) if out_dir is not None else None
        self.primary_metric = primary_metric
        self.rf = self._align_rf(rf)
        self.last_selection: dict | None = None
        self.test_looks: list[dict] = []

    # -- plumbing ------------------------------------------------------------------------------
    def _align_rf(self, rf: pd.Series | None) -> np.ndarray:
        n = len(self.M)
        if rf is None:
            return np.zeros(n)
        s = rf.copy()
        s.index = pd.DatetimeIndex(s.index).to_period("M")
        s = s[~s.index.duplicated(keep="last")]
        al = s.reindex(self.M.index.to_period("M"))
        miss = int(al.isna().sum())
        if miss:
            log.warning("rf missing for %d of %d grid months; forward-filled (0 before first value)", miss, n)
            al = al.ffill().fillna(0.0)
        return al.to_numpy(float)

    def set_design(self, axes: dict | None = None, categorical: dict | None = None,
                   default: dict | None = None) -> None:
        if axes is not None:
            self.axes = {k: list(v) for k, v in axes.items()}
        if categorical is not None:
            self.categorical = {k: list(v) for k, v in categorical.items()}
        if default is not None:
            self.default = dict(default)

    def _design(self, axes=None, categorical=None, default=None):
        axes = self.axes if axes is None else {k: list(v) for k, v in axes.items()}
        categorical = self.categorical if categorical is None else {k: list(v) for k, v in categorical.items()}
        default = self.default if default is None else dict(default)
        return axes, categorical, default

    def _layout(self, axes=None, categorical=None, default=None) -> _Layout:
        axes, categorical, default = self._design(axes, categorical, default)
        return _Layout.build(self.cells, axes, categorical, default)

    def _mask(self, window) -> np.ndarray:
        return _window_mask(self.M.index, window)

    def _excess(self, window=None) -> np.ndarray:
        m = self._mask(window)
        return self.M.to_numpy(float)[m] - self.rf[m][:, None]

    def resolve(self, chosen) -> str:
        """cell id from: a cell id string, a params dict, or a ``select()`` result."""
        if isinstance(chosen, str):
            if chosen not in self.cell_ids:
                raise KeyError(f"unknown cell id {chosen!r}")
            return chosen
        if isinstance(chosen, dict) and "cell_id" in chosen and "chosen" in chosen:
            return self.resolve(chosen["cell_id"])
        if isinstance(chosen, dict):
            keys = list(self.axes) + list(self.categorical)
            keys = [k for k in keys if k in chosen] or list(chosen)
            hits = []
            for cid, c in zip(self.cell_ids, self.cells):
                if all(k in c and _same_level(c[k], chosen[k]) for k in keys):
                    hits.append(cid)
            if len(hits) != 1:
                raise KeyError(f"{len(hits)} grid cells match {chosen!r}")
            return hits[0]
        raise TypeError(f"cannot resolve {type(chosen)} to a grid cell")

    # -- per-cell metrics ------------------------------------------------------------------------
    def metrics(self, window=None, with_params: bool = False) -> pd.DataFrame:
        """Per-cell net metrics over ``window = (start, end)`` (None bound = open; None = whole sample).

        Columns: sharpe (annualised, excess of rf), cagr, vol, maxdd, tstat (of mean excess return), n_months.
        """
        m = self._mask(window)
        idx = self.M.index[m]
        rf = self.rf[m]
        rows = []
        for cid in self.cell_ids:
            r = self.M[cid].to_numpy(float)[m]
            ok = np.isfinite(r)
            n = int(ok.sum())
            if n < 3:
                rows.append(dict(cell_id=cid, sharpe=np.nan, cagr=np.nan, vol=np.nan, maxdd=np.nan,
                                 tstat=np.nan, n_months=n))
                continue
            rr, ff = r[ok], rf[ok]
            x = rr - ff
            sd = x.std(ddof=1)
            rows.append(dict(
                cell_id=cid, sharpe=float(metrics.sharpe(rr, ff, PPY)), cagr=float(metrics.cagr(rr, PPY)),
                vol=float(metrics.ann_vol(rr, PPY)), maxdd=float(metrics.max_drawdown(rr)),
                tstat=float(x.mean() / (sd / np.sqrt(n))) if sd > 0 else np.nan, n_months=n))
        out = pd.DataFrame(rows).set_index("cell_id")
        out.attrs["window"] = _window_label(window)
        out.attrs["first"], out.attrs["last"] = (idx[0], idx[-1]) if len(idx) else (None, None)
        return out.join(self.params) if with_params else out

    def sharpes(self, window=None) -> np.ndarray:
        return _sharpe_vec(self._excess(window))

    # -- selection (research/06 section 5.4) -----------------------------------------------------
    def select(self, train: tuple, axes: dict | None = None, categorical: dict | None = None,
               default: dict | None = None, lam: float = 1.0, floor: float | None = None,
               tie_tol: float = 0.02, stability_B: int = 500, *, peak_ratio_max: float = 1.25,
               cat_margin: float = 0.10, min_share_within_one: float = 0.5, mean_block: float = 6,
               seed: int = 0) -> dict:
        """Plateau selection on the TRAIN window (see module docstring). Never looks at any other window.

        ``floor`` is the eligibility floor on the neighbourhood minimum (benchmark Sharpe on the same
        window, or None for the absolute rule 0). Returns a dict with keys: chosen (params), cell_id,
        is_default, fallback, fallback_reason, score, sharpe, peak_ratio, plateau_width, neighborhood
        (DataFrame), per_category (DataFrame), stability (dict or None), variants, reasons, default, ...
        """
        axes, categorical, default = self._design(axes, categorical, default)
        self.set_design(axes, categorical, default)
        if default is None:
            raise ValueError("a literature default is required (it is the fallback)")
        lay = self._layout()
        if lay.default_pos is None:
            raise ValueError(f"default {default!r} is not a cell of the grid")
        floor_v = 0.0 if floor is None else float(floor)
        kw = dict(floor=floor_v, peak_ratio_max=peak_ratio_max, tie_tol=tie_tol, cat_margin=cat_margin)
        X = self._excess(train)
        n_train = X.shape[0]
        v = _sharpe_vec(X)
        reasons: list[str] = [f"train window {_window_label(train)}: {n_train} months, {int(np.isfinite(v).sum())} "
                              f"of {len(v)} cells evaluable; metric = net Sharpe (annualised, excess of rf)"]
        default_pos = lay.default_pos

        pick = _plateau_pick(v, lay, lam=lam, **kw)
        stability = None
        fallback, why = False, None
        if pick is None:
            fallback, why = True, "no cell is eligible (needs >=2 neighbours, neighbourhood min > floor, peak ratio <= max)"
            reasons.append("FALLBACK to literature default: " + why)
            pos = default_pos
        else:
            pos = pick.pos
            reasons.append(f"plateau pick: score {pick.score:.3f}, peak ratio {pick.peak:.2f} (max {peak_ratio_max})")
            if len(lay.pos) > 1:
                reasons.append("categorical plateau scores: " + "; ".join(
                    f"{self._cat_label(ck)}={sc:.3f}" for ck, (_i, sc, _p, _n) in pick.per_cat.items())
                    + f" (default category kept unless another beats it by >= {cat_margin:.2f})")
            if stability_B and stability_B > 0:
                stability = self._stability(X, lay, pick, lam, kw, stability_B, mean_block, seed, default_pos)
                ok = stability["share_within_one"] >= min_share_within_one
                stability["passed"] = bool(ok)
                reasons.append(f"bootstrap stability (B={stability_B}): {stability['share_exact']:.0%} exactly this cell, "
                               f"{stability['share_within_one']:.0%} within one grid step "
                               f"(need >= {min_share_within_one:.0%}) -> {'pass' if ok else 'FAIL'}")
                if not ok:
                    fallback, why = True, "bootstrap stability check failed"
                    reasons.append("FALLBACK to literature default: " + why)
                    pos = default_pos

        cid = self.cell_ids[pos]
        ck, ix = lay.key_of[pos]
        f_ck = lay.array(v, ck)
        sel_sharpe = float(v[pos])
        width = (_plateau_width(f_ck, ix, 0.9 * sel_sharpe) if np.isfinite(sel_sharpe) and sel_sharpe > 0 else 0)
        out = dict(
            chosen=dict(self.cells[pos]), cell_id=cid, is_default=bool(pos == default_pos), fallback=fallback,
            fallback_reason=why, score=(pick.score if pick else float("nan")),
            peak_ratio=(pick.peak if pick else float("nan")), sharpe=sel_sharpe,
            default=dict(self.cells[default_pos]), default_cell_id=self.cell_ids[default_pos],
            default_sharpe=float(v[default_pos]), plateau_width=int(width),
            neighborhood=self._neighborhood(v, lay, pos, pick),
            per_category=self._per_category(v, lay, pick),
            stability=stability, reasons=reasons, train=tuple(train), n_train_months=int(n_train),
            lam=lam, floor=floor_v, tie_tol=tie_tol, peak_ratio_max=peak_ratio_max, cat_margin=cat_margin,
            variants=self._variants(v, lay, pos, kw),
        )
        self.last_selection = out
        return out

    def _cat_label(self, ck: tuple) -> str:
        if not self.categorical:
            return "all"
        return ",".join(f"{k}={lv[i]}" for (k, lv), i in zip(self.categorical.items(), ck))

    def _stability(self, X, lay: _Layout, pick: _Pick, lam, kw, B, mean_block, seed, default_pos) -> dict:
        rng = np.random.default_rng(seed)
        n = X.shape[0]
        exact = within = fell = 0
        sel_ck, sel_ix = pick.ck, np.array(pick.ix)
        counts: dict[int, int] = {}
        for _ in range(B):
            idx = stats.stationary_bootstrap_idx(n, mean_block, rng)
            p = _plateau_pick(_sharpe_vec(X[idx]), lay, lam=lam, **kw)
            if p is None:
                fell += 1
                pos = default_pos
                ck, ix = lay.key_of[pos]
            else:
                pos, ck, ix = p.pos, p.ck, p.ix
            counts[pos] = counts.get(pos, 0) + 1
            if pos == pick.pos:
                exact += 1
            if ck == sel_ck and int(np.abs(np.array(ix) - sel_ix).sum()) <= 1:
                within += 1
        top = sorted(counts.items(), key=lambda kv: -kv[1])[:5]
        return dict(B=B, share_exact=exact / B, share_within_one=within / B, share_fallback=fell / B,
                    top_cells=[(self.cell_ids[p], c / B) for p, c in top], mean_block=mean_block)

    def _neighborhood(self, v, lay: _Layout, pos: int, pick: _Pick | None) -> pd.DataFrame:
        ck, ix = lay.key_of[pos]
        axis_names = list(lay.axes)
        rows = [self._nb_row(pos, "self", "", 0, v)]
        for ax, d, j in lay.neighbors(ix):
            p = int(lay.pos[ck][j])
            if p >= 0:
                rows.append(self._nb_row(p, "neighbor", axis_names[ax], d, v))
        df = pd.DataFrame(rows)
        df.attrs["score"] = pick.score if pick else float("nan")
        return df

    def _nb_row(self, p: int, role: str, axis: str, step: int, v) -> dict:
        keys = list(self.axes) + list(self.categorical)
        row = dict(role=role, axis=axis, step=step, cell_id=self.cell_ids[p])
        row.update({k: self.cells[p][k] for k in keys})
        row["sharpe"] = float(v[p])
        return row

    def _per_category(self, v, lay: _Layout, pick: _Pick | None) -> pd.DataFrame:
        rows = []
        for ck in lay.pos:
            f = lay.array(v, ck)
            row = {"category": self._cat_label(ck), "n_cells": int(np.isfinite(f).sum()),
                   "is_default_category": ck == lay.default_ck}
            if pick is not None and ck in pick.per_cat:
                ix, sc, pk, ne = pick.per_cat[ck]
                row.update(n_eligible=ne, best_cell_id=self.cell_ids[int(lay.pos[ck][ix])], score=sc,
                           peak_ratio=pk, sharpe=float(f[ix]), chosen=(ck == pick.ck))
            else:
                row.update(n_eligible=0, best_cell_id=None, score=np.nan, peak_ratio=np.nan, sharpe=np.nan,
                           chosen=False)
            rows.append(row)
        return pd.DataFrame(rows)

    def _variants(self, v, lay: _Layout, pos: int, kw) -> dict:
        """Sensitivity (not selection): plain argmax and lambda=0 neighbourhood mean."""
        _ck, ix = lay.key_of[pos]

        def near(p):
            if p is None:
                return None
            ck2, ix2 = lay.key_of[p]
            return bool(ck2 == lay.key_of[pos][0] and int(np.abs(np.array(ix2) - np.array(ix)).sum()) <= 1)

        out = {}
        if np.isfinite(v).any():
            p = int(np.nanargmax(v))
            out["argmax"] = dict(cell_id=self.cell_ids[p], sharpe=float(v[p]), within_one_step=near(p))
        p0 = _plateau_pick(v, lay, lam=0.0, **kw)
        if p0 is not None:
            out["lam0"] = dict(cell_id=self.cell_ids[p0.pos], sharpe=float(v[p0.pos]), within_one_step=near(p0.pos))
        return out

    # -- confirmation (test window; single look) ---------------------------------------------------
    def confirm(self, test: tuple, chosen, default: dict | None = None, train: tuple | None = None) -> dict:
        """Test-window metrics for chosen vs literature default vs grid median.

        ``chosen`` is a ``select()`` result, a params dict or a cell id. Returns a dict with ``table``
        (rows chosen / default / grid_median; columns sharpe, cagr, vol, maxdd, tstat, n_months) and
        ``chosen_rank_pct`` (share of cells with a lower test Sharpe), ``spearman_train_test`` (landscape
        persistence, across cells), ``test_over_train_sharpe`` plus the criteria of research/04 7.3.
        Calling it twice on the same window with different choices is flagged: the test window is burned.
        """
        cid = self.resolve(chosen)
        dflt = default if default is not None else (
            chosen.get("default") if isinstance(chosen, dict) and "default" in chosen else self.default)
        if dflt is None:
            raise ValueError("no default available for comparison")
        did = self.resolve(dflt)
        mt = self.metrics(test)
        if train is None and isinstance(chosen, dict) and "train" in chosen:
            train = chosen["train"]
        if train is None and self.last_selection is not None:
            train = self.last_selection["train"]
        cols = ["sharpe", "cagr", "vol", "maxdd", "tstat", "n_months"]
        med = mt[cols].median()
        med["n_months"] = float(mt["n_months"].max())
        table = pd.DataFrame([mt.loc[cid, cols], mt.loc[did, cols], med], index=["chosen", "default", "grid_median"])
        table.attrs["cells"] = dict(chosen=cid, default=did)
        s = mt["sharpe"]
        valid = s.dropna()
        out = dict(table=table, chosen_id=cid, default_id=did, test=tuple(test),
                   chosen_minus_default_sharpe=float(table.loc["chosen", "sharpe"] - table.loc["default", "sharpe"]),
                   chosen_minus_median_sharpe=float(table.loc["chosen", "sharpe"] - table.loc["grid_median", "sharpe"]),
                   chosen_rank_pct=float((valid < s[cid]).mean()) if np.isfinite(s[cid]) else float("nan"),
                   notes=[])
        if train is not None:
            mtr = self.metrics(train)
            both = pd.concat([mtr["sharpe"], s], axis=1, keys=["train", "test"]).dropna()
            if len(both) >= 4 and both["train"].std() > 0 and both["test"].std() > 0:
                out["spearman_train_test"] = float(both.corr(method="spearman").iloc[0, 1])
            else:
                out["spearman_train_test"] = float("nan")
            tr = mtr.loc[cid, "sharpe"]
            out["train_sharpe_chosen"] = float(tr)
            out["test_over_train_sharpe"] = float(table.loc["chosen", "sharpe"] / tr) if tr and np.isfinite(tr) and tr > 0 else float("nan")
        # research/04 7.3 confirmation criteria that can be evaluated here
        out["criteria"] = dict(
            test_sharpe_positive=bool(table.loc["chosen", "sharpe"] > 0),
            test_ge_half_train=bool(out.get("test_over_train_sharpe", np.nan) >= 0.5),
            landscape_persists=bool(out.get("spearman_train_test", np.nan) > 0),
            beats_grid_median=bool(out["chosen_minus_median_sharpe"] > 0),
        )
        key = _window_label(test)
        prev = [lk for lk in self.test_looks if lk["window"] == key]
        if prev and any(lk["cell_id"] != cid for lk in prev):
            out["notes"].append("TEST WINDOW BURNED: confirm() was already called on this window with a different "
                                "cell; record it in the ledger and treat the test as in-sample (research/06 5.2).")
            log.warning(out["notes"][-1])
        self.test_looks.append(dict(window=key, cell_id=cid, timestamp=_utcnow()))
        if self.ledger is not None:
            self.ledger.log(self.strategy, self.cells[self.cell_ids.index(cid)], window=key,
                            n_months=int(table.loc["chosen", "n_months"]), sharpe=float(table.loc["chosen", "sharpe"]),
                            cagr=float(table.loc["chosen", "cagr"]), maxdd=float(table.loc["chosen", "maxdd"]),
                            notes="confirm (test look)", cell_id_=cid)
        return out

    # -- overfitting diagnostics -------------------------------------------------------------------
    def pbo(self, window=None, S: int = 16, selector: str | Callable = "plateau", seed: int = 0,
            **plateau_kw) -> dict:
        """Probability of Backtest Overfitting (CSCV) via ``stats.cscv_pbo`` on the NET excess returns.

        ``selector='plateau'`` (default) uses THIS module's plateau rule (with default fallback) as the IS
        selection, so PBO measures the team's actual procedure; ``'argmax'`` is the paper's selector.
        Extra keyword args (lam, floor, tie_tol, ...) are passed to the plateau rule. Returns the
        ``stats.cscv_pbo`` dict plus S, selector, window, annualised Sharpes (``sr_is_ann``/``sr_oos_ann``).
        """
        X = self._excess(window)
        ok = np.isfinite(X).all(axis=1)
        if ok.sum() < S * 2:
            raise ValueError(f"only {int(ok.sum())} complete months in window; need >= {2 * S} for S={S}")
        X = X[ok]
        if callable(selector):
            sel, sel_name = selector, getattr(selector, "__name__", "custom")
        elif selector == "argmax":
            sel, sel_name = None, "argmax"
        elif selector == "plateau":
            lay = self._layout()
            kw = dict(lam=plateau_kw.pop("lam", 1.0), floor=float(plateau_kw.pop("floor", 0.0) or 0.0),
                      peak_ratio_max=plateau_kw.pop("peak_ratio_max", 1.25), tie_tol=plateau_kw.pop("tie_tol", 0.02),
                      cat_margin=plateau_kw.pop("cat_margin", 0.10))
            dpos = lay.default_pos if lay.default_pos is not None else 0
            scale = np.sqrt(PPY)

            def sel(R):
                R = np.asarray(R, float)
                p = _plateau_pick(np.where(np.isfinite(R), R * scale, np.nan), lay, **kw)
                return int(dpos if p is None else p.pos)
            sel_name = "plateau"
        else:
            raise ValueError(f"unknown selector {selector!r}")
        res = dict(stats.cscv_pbo(X, S=S, selector=sel))
        res.update(S=S, selector=sel_name, window=_window_label(window), n_cells=X.shape[1], n_months=int(X.shape[0]),
                   ppy=PPY, sr_is_ann=np.asarray(res["sr_is"], float) * np.sqrt(PPY),
                   sr_oos_ann=np.asarray(res["sr_oos"], float) * np.sqrt(PPY))
        return res

    def dsr(self, chosen, window=None, N: int | None = None) -> dict:
        """Deflated Sharpe Ratio of ``chosen`` over ``window`` with N = the LEDGER trial count.

        Reports DSR at N = ledger count (headline), at N_eff = ``stats.effective_trials`` of the grid
        cells' returns (research/06 4.3), and at N = number of grid cells; also PSR(0), t-stat and the
        Bonferroni-haircut Sharpe for the same N. The variance of trial Sharpes is the empirical cross-
        sectional variance of the grid cells' per-period Sharpes in ``window``.
        """
        cid = self.resolve(chosen)
        X = self._excess(window)
        j = self.cell_ids.index(cid)
        r = X[:, j]
        r = r[np.isfinite(r)]
        T = len(r)
        sr_per_all = _sharpe_vec(X, ppy=1)
        trial_sr = sr_per_all[np.isfinite(sr_per_all)]
        n_led = self.ledger.count(self.strategy) if self.ledger is not None else 0
        n_cells = int(np.isfinite(sr_per_all).sum())
        N_use = int(N) if N is not None else max(n_led, n_cells, 1)
        full = X[np.isfinite(X).all(axis=1)]
        try:
            n_eff = float(stats.effective_trials(full)) if full.shape[0] > 3 and full.shape[1] > 1 else float(n_cells)
        except Exception as exc:  # pragma: no cover - defensive
            log.warning("effective_trials failed: %s", exc)
            n_eff = float("nan")
        d_main, sr0_main = stats.dsr(r, trial_sr, N=N_use)
        d_grid, sr0_grid = stats.dsr(r, trial_sr, N=max(n_cells, 1))
        if np.isfinite(n_eff):
            d_eff, sr0_eff = stats.dsr(r, trial_sr, N=n_eff)
        else:
            d_eff, sr0_eff = float("nan"), float("nan")
        sr_ann = float(r.mean() / r.std(ddof=1) * np.sqrt(PPY)) if T > 2 and r.std(ddof=1) > 0 else float("nan")
        years = T / PPY
        out = dict(cell_id=cid, window=_window_label(window), n_months=T, sr_ann=sr_ann, t_stat=sr_ann * np.sqrt(years),
                   N_ledger=n_led, N_used=N_use, N_cells=n_cells, N_eff=n_eff,
                   dsr=float(d_main), sr0_per=float(sr0_main), sr0_ann=float(sr0_main * np.sqrt(PPY)),
                   dsr_neff=float(d_eff), sr0_neff_ann=float(sr0_eff * np.sqrt(PPY)),
                   dsr_ncells=float(d_grid), trial_sharpe_sd_ann=float(np.std(trial_sr, ddof=1) * np.sqrt(PPY))
                   if len(trial_sr) > 1 else float("nan"))
        if T > 3 and np.isfinite(sr_ann):
            from scipy import stats as sps
            sr_per = float(r.mean() / r.std(ddof=1))
            sk, ku = float(sps.skew(r)), float(sps.kurtosis(r, fisher=False))
            out["psr0"] = float(stats.psr(sr_per, 0.0, T, sk, ku))
            out["min_trl_years"] = float(stats.min_track_record_len(sr_per, 0.0, sk, ku)) / PPY
        if np.isfinite(sr_ann) and sr_ann > 0:
            try:
                sr_adj, hc = stats.haircut_sharpe_bonferroni(sr_ann, years, N_use)
                out.update(haircut_sharpe=float(sr_adj), haircut=float(hc))
            except Exception as exc:  # pragma: no cover - defensive
                log.warning("haircut failed: %s", exc)
        return out

    def regression_table(self, window=None, B: int = 500, mean_block: float = 6, seed: int = 0,
                         axes: dict | None = None, categorical: dict | None = None) -> pd.DataFrame:
        """Sharpe-on-parameters regression over the grid (research/06 5.5) via ``stats.grid_regression_bootstrap``.

        Ordinal axes enter as their position scaled to [-1, 1] (levels, squares, interactions); categorical
        axes as dummies (first sorted level dropped). Returns a DataFrame (coef, boot_sd, t_boot) indexed by
        term with ``attrs['r2']``. Bootstrap SDs resample months jointly across cells; OLS p-values would be
        meaningless because the cells overlap.
        """
        axes, categorical, _ = self._design(axes, categorical, None)
        X = self._excess(window)
        ok = np.isfinite(X).all(axis=1)
        if ok.sum() < 24:
            raise ValueError("need >= 24 complete months across all cells")
        Rx = X[ok]            # EXCESS returns: the bootstrap's response is each cell's net Sharpe
        levels: dict[str, np.ndarray] = {}
        for k, lv in axes.items():
            levels[k] = np.array([_level_index(lv, c[k]) for c in self.cells], dtype=float)
        for k in categorical:
            levels[k] = np.array([str(c[k]) for c in self.cells])
        res = stats.grid_regression_bootstrap(Rx, levels, list(axes), cat=tuple(categorical), B=B,
                                              mean_block=mean_block, seed=seed)
        coef, sd = np.asarray(res["coef"], float), np.asarray(res["boot_sd"], float)
        tab = pd.DataFrame({"coef": coef, "boot_sd": sd, "t_boot": np.divide(coef, sd, out=np.full_like(coef, np.nan), where=sd > 0)},
                           index=list(res["names"]))
        tab.attrs.update(r2=float(res["r2"]), n_cells=len(self.cells), window=_window_label(window), B=B)
        return tab

    # -- output -------------------------------------------------------------------------------------
    def to_csv(self, out_dir: str | Path | None = None, windows: dict | None = None) -> list[Path]:
        """Write cells.csv (params), monthly_returns.csv (M) and metrics_<window>.csv; returns the paths."""
        out_dir = Path(out_dir) if out_dir is not None else (self.out_dir or _default_out_dir(self.strategy))
        out_dir.mkdir(parents=True, exist_ok=True)
        paths = []
        p = out_dir / "grid_cells.csv"
        self.params.rename_axis("cell_id").to_csv(p)
        paths.append(p)
        p = out_dir / "grid_monthly_returns.csv"
        self.M.rename_axis("date").to_csv(p)
        paths.append(p)
        wins = {"full": None} if windows is None else windows
        for name, w in wins.items():
            p = out_dir / f"grid_metrics_{name}.csv"
            self.metrics(w, with_params=True).to_csv(p)
            paths.append(p)
        return paths


# ----------------------------------------------------------------------------------------------
# run_grid
# ----------------------------------------------------------------------------------------------
def _call_fn(args):
    fn, cell = args
    return fn(cell)


def _clean_series(s, cid: str) -> pd.Series:
    if not isinstance(s, pd.Series):
        raise TypeError(f"fn must return a pandas Series of monthly net returns (cell {cid})")
    s = s.astype(float).copy()
    s.index = pd.DatetimeIndex(s.index)
    if s.index.tz is not None:
        s.index = s.index.tz_localize(None)
    s.index = s.index.normalize()
    s = s.sort_index()
    if s.index.has_duplicates:
        raise ValueError(f"duplicate dates in the return series of cell {cid}")
    if len(s) >= 3:
        gap = np.median(np.diff(s.index.values).astype("timedelta64[D]").astype(float))
        if gap < 20:
            raise ValueError(f"cell {cid}: series looks non-monthly (median gap {gap:.0f} days); "
                             f"aggregate with metrics.to_monthly first")
    return s


def run_grid(strategy: str, cells: list[dict], fn: Callable[[dict], pd.Series], n_jobs: int = 1, *,
             rf: pd.Series | None = None, ledger: Ledger | None | bool = None,
             axes: dict | None = None, categorical: dict | None = None, default: dict | None = None,
             out_dir: str | Path | None = None, check_prereg: bool = True, on_error: str = "raise",
             notes: str = "grid") -> GridResult:
    """Evaluate every cell with ``fn(cell) -> monthly NET return Series`` and log each one as a trial.

    * ``n_jobs > 1`` uses a ProcessPoolExecutor (``fn`` must be picklable, e.g. a module-level function or a
      ``functools.partial`` of one); on any pickling/pool problem it falls back to serial execution.
    * ``rf``: monthly risk-free Series so Sharpe ratios are excess of rf (None => raw returns).
    * ``ledger``: a :class:`Ledger` (default ``output/ledger.csv``); ``False`` disables logging (tests only).
    * If ``<out_dir>/preregistration.json`` exists, ``cells`` must equal the registered grid
      (:class:`PreregistrationError` otherwise; ``check_prereg=False`` disables). ``axes``, ``categorical``,
      ``default`` are filled from it when not given.
    * ``on_error='nan'`` records a failing cell as an all-NaN column (listed in ``GridResult.errors``).
    """
    if on_error not in ("raise", "nan"):
        raise ValueError("on_error must be 'raise' or 'nan'")
    cells = [dict(c) for c in cells]
    if not cells:
        raise ValueError("empty grid")
    out_dir_p = Path(out_dir) if out_dir is not None else _default_out_dir(strategy)
    reg = load_preregistration(strategy, out_dir_p)
    if reg is not None:
        if check_prereg and grid_hash(cells) != reg["grid_hash"]:
            raise PreregistrationError(
                f"cells (hash {grid_hash(cells)}, n={len(cells)}) differ from the pre-registered grid "
                f"(hash {reg['grid_hash']}, n={reg['n_cells']}, {reg['timestamp']}). Every extra cell is a new "
                f"trial: pre-register it, or pass check_prereg=False for an explicitly exploratory run.")
        axes = axes if axes is not None else reg.get("axes")
        categorical = categorical if categorical is not None else reg.get("categorical")
        default = default if default is not None else reg.get("default")
    elif check_prereg:
        log.warning("no preregistration.json for %s in %s: run preregister() BEFORE the first backtest", strategy, out_dir_p)
    ids = [cell_id(c) for c in cells]
    if len(set(ids)) != len(ids):
        raise ValueError("duplicate cells in the grid")

    results: dict[int, pd.Series | Exception] = {}
    todo = list(range(len(cells)))
    if n_jobs and n_jobs > 1 and len(cells) > 1:
        try:
            pickle.dumps(fn)
            with ProcessPoolExecutor(max_workers=min(int(n_jobs), len(cells))) as ex:
                futs = {i: ex.submit(_call_fn, (fn, cells[i])) for i in todo}
                for i, f in futs.items():
                    try:
                        results[i] = f.result()
                    except BrokenProcessPool:
                        raise
                    except Exception as exc:  # error raised inside fn
                        results[i] = exc
        except (pickle.PicklingError, AttributeError, TypeError, BrokenProcessPool, OSError, PermissionError,
                NotImplementedError) as exc:
            log.warning("parallel execution unavailable (%s: %s); running serially", type(exc).__name__, exc)
            results = {i: r for i, r in results.items() if not isinstance(r, BrokenProcessPool)}
        todo = [i for i in todo if i not in results]
    for i in todo:
        try:
            results[i] = fn(dict(cells[i]))
        except Exception as exc:
            results[i] = exc

    errors: dict[str, str] = {}
    series: dict[str, pd.Series] = {}
    for i, cid in enumerate(ids):
        r = results[i]
        if isinstance(r, Exception):
            if on_error == "raise":
                raise RuntimeError(f"cell {cells[i]!r} failed: {r!r}") from r
            errors[cid] = repr(r)
            log.error("cell %s failed: %r", cells[i], r)
            continue
        series[cid] = _clean_series(r, cid)
    if not series:
        raise RuntimeError("every cell failed")
    M = pd.concat(series, axis=1).sort_index()
    M = M.reindex(columns=ids)

    if ledger is None:
        led: Ledger | None = Ledger()
    elif ledger is False:
        led = None
    else:
        led = ledger
    gr = GridResult(strategy, cells, M, rf=rf, ledger=led, errors=errors, axes=axes, categorical=categorical,
                    default=default, out_dir=out_dir_p)
    if led is not None:
        mt = gr.metrics(None)
        window = _window_label((M.index.min(), M.index.max()))
        led.log_rows([dict(strategy=strategy, cell_id=cid, params=c, window=window, n_months=int(mt.loc[cid, "n_months"]),
                           sharpe=mt.loc[cid, "sharpe"], cagr=mt.loc[cid, "cagr"], maxdd=mt.loc[cid, "maxdd"], notes=notes)
                      for cid, c in zip(ids, cells)])
    return gr
