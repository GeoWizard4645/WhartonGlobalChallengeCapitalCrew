"""Trading-comps signal: multiples, GICS peer selection, trimmed peer benchmark, discounts.

Implements research/04_trading_comps.md sections 4.1 (market cap, EV, P/E, EV/EBITDA), 5.1 (rules R1-R12,
K1-K3, M1-M2) and 5.3 (step-by-step procedure, ``pick_peers``).  Everything is point-in-time: the inputs
are the frames a ``DataContext`` hands out for the decision date (``ctx.fundamentals`` keeps only filings
with ``filed < date``; ``ctx.universe`` carries the GICS classification as it was on that date).

Public API
----------
``multiples_table(ctx, date, univ, basis='TTM') -> DataFrame``
    one row per company (index = cik): market cap, EV, P/E, EV/EBITDA, validity and staleness flags.
``pick_peers(mt, ok, cik, multiple, size_filter, params)`` / ``trim_peers(values, params)``
    scalar reference versions of section 5.3 (hand checks; the tests assert they equal the vectorised path).
``peer_benchmark(mt, ok, multiple, size_filter, params) -> PeerBench``
    the (theta-independent, key-metric-independent) core of section 5.3 for ONE multiple: peers, level,
    pre-trim median, trimmed benchmark.  Depends only on (size_filter, cap of that multiple) and the
    eligibility mask, which is what lets the 54-cell grid share the expensive part.
``comps_signals(ctx, date, univ, params, km, mt=None, cache=None, return_peers=False) -> DataFrame``
    per target: peer level / count / medians / discounts / pass flags / ``comps_buy`` / ``score`` and, after
    that, the key-metric gates from ``km`` (target only) and the final ``eligible`` flag.
``stage_counts(sig)``
    the per-rebalance diagnostics (counts at each stage, fallback rate, average peer count).

Doc rule -> code (see also tests/test_comps.py)
-----------------------------------------------
R1  peers = same GICS sub-industry code, target excluded                          ``_eval_block`` (M diagonal)
R2  size filter ON: keep the 5 peers closest in |ln(mc_j/mc_i)|, need >= 4;
    OFF: all valid peers, need >= 4, no cap                                       ``_eval_block``
R3  market-cap window 0.5x-2x (inclusive) when the size filter is ON              ``_eval_block``
R4  < 4 peers at sub-industry level -> same rule at GICS industry level;
    else no signal                                                                ``peer_benchmark``
R5  both multiples must pass (AND); score = average of the two discounts          ``comps_signals``
R6  TTM for target and peers at the same date; latest period_end within 135 days  ``multiples_table`` (fresh)
R7  negative / zero P/E, EV/EBITDA (or EV <= 0) are invalid, never set to 0       ``multiples_table``
R8  P/E > pe_cap, EV/EBITDA > ev_cap -> invalid as a peer AND as a target         ``multiple_eligibility``
R9  missing data is dropped (never imputed) before peers are counted              ``multiples_table``/``eligibility``
R10 recent IPO / recent merger (from km) excluded as peer and target              ``multiple_eligibility``
R11 peers whose multiple is outside [0.5, 2.0] x pre-trim median dropped, need
    >= 3 kept, benchmark = median of kept                                         ``_eval_block``
R12 BUY if multiple < (1 - theta) x benchmark (strict)                            ``comps_signals``
K1-K3 key-metric gates (target only) read from ``km``                             ``comps_signals``
M2  sectors Financials/Real Estate out, mcap/price floors                         ``exclude_sector_mask``
"""
from __future__ import annotations

import logging
from dataclasses import dataclass, field

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------------------------------
COMPS_DEFAULTS: dict = dict(
    theta=0.15, pe_cap=40.0, ev_cap=35.0, size_filter=True, basis="TTM",
    size_lo=0.5, size_hi=2.0, k_min=4, k_max=5, trim_lo=0.5, trim_hi=2.0, k_trim_min=3,
    stale_days=135, gates=("leverage", "quality", "roic"),
)

MULTIPLES = ("pe", "ev")
_COL = {"pe": "pe", "ev": "ev_ebitda"}            # multiple key -> column of the multiples table
_CAP = {"pe": "pe_cap", "ev": "ev_cap"}           # multiple key -> parameter holding its cap
_LEVELS = np.array(["none", "sub", "industry"], dtype=object)
GICS_NAME_COLS = ["gics_sector", "gics_industry_group", "gics_industry", "gics_sub_industry"]
EXCLUDED_SECTORS = ("Financials", "Real Estate")
EXCLUDED_SECTOR_CODES = ("40", "60")
SECTOR_CODES = {"Energy": "10", "Materials": "15", "Industrials": "20", "Consumer Discretionary": "25",
                "Consumer Staples": "30", "Health Care": "35", "Financials": "40", "Information Technology": "45",
                "Communication Services": "50", "Telecommunication Services": "50", "Utilities": "55",
                "Real Estate": "60"}
_GATE_COLS = {"leverage": "pass_leverage", "quality": "quality_ok", "roic": "pass_roic"}


def merge_params(params: dict | None = None) -> dict:
    """COMPS_DEFAULTS overlaid with ``params`` (unknown keys are kept)."""
    p = dict(COMPS_DEFAULTS)
    if params:
        p.update(params)
    if str(p["basis"]).upper() not in ("TTM", "LFY"):
        raise ValueError(f"basis must be 'TTM' or 'LFY', got {p['basis']!r}")
    p["basis"] = str(p["basis"]).upper()
    if int(p["k_min"]) < 1:
        raise ValueError("k_min must be >= 1")
    return p


# --------------------------------------------------------------------------------------------------
# small helpers
# --------------------------------------------------------------------------------------------------
def _num(df: pd.DataFrame, col: str, index: pd.Index) -> pd.Series:
    """Float column ``col`` of ``df`` aligned on ``index`` (all-NaN if the column does not exist)."""
    if col in df.columns:
        return pd.to_numeric(df[col], errors="coerce").reindex(index).astype(float)
    return pd.Series(np.nan, index=index, dtype=float)


def _code_str(s: pd.Series) -> pd.Series:
    """GICS codes as plain strings ('25504040'); missing -> None.  Accepts ints, floats and strings."""
    def f(v):
        if v is None or v is pd.NA or (not isinstance(v, str) and pd.isna(v)):
            return None
        if isinstance(v, (int, np.integer)):
            return str(int(v))
        if isinstance(v, (float, np.floating)):
            return str(int(v))
        v = str(v).strip()
        if v.endswith(".0"):
            v = v[:-2]
        return v or None
    return s.astype(object).map(f)


def _name_str(s: pd.Series) -> pd.Series:
    return s.astype(object).map(lambda v: None if v is None or v is pd.NA or (not isinstance(v, str) and pd.isna(v))
                                else (str(v).strip() or None))


def group_codes(u: pd.DataFrame) -> tuple[pd.Series, pd.Series]:
    """(sub-industry key, industry key) per row of a universe frame.

    Uses the 8-/6-digit GICS codes when the frame has them (``sub_industry_code``/``industry_code``),
    else the GICS names.  The industry key falls back to the first 6 digits of the sub-industry code.
    """
    idx = u.index
    if "sub_industry_code" in u.columns:
        sub = _code_str(u["sub_industry_code"])
    elif "gics_sub_industry" in u.columns:
        sub = _name_str(u["gics_sub_industry"])
    else:
        sub = pd.Series([None] * len(u), index=idx, dtype=object)
    if "industry_code" in u.columns:
        ind = _code_str(u["industry_code"])
        if "sub_industry_code" in u.columns:      # fill gaps from the sub-industry code
            ind = ind.where(ind.notna(), sub.map(lambda v: v[:6] if isinstance(v, str) and len(v) >= 8 else None))
    elif "sub_industry_code" in u.columns:
        ind = sub.map(lambda v: v[:6] if isinstance(v, str) and len(v) >= 8 else None)
    elif "gics_industry" in u.columns:
        ind = _name_str(u["gics_industry"])
    else:
        ind = pd.Series([None] * len(u), index=idx, dtype=object)
    # No classification look-ahead (backtest audit F2): the universe builder back-fills some pre-2017 labels from a
    # LATER Wikipedia snapshot (gics_source 'asof_next' / 'backfill_next' / 'era_next'). A label we could not have
    # known on the date is treated as unknown, so such a company can be neither a target nor a peer.
    if "gics_source" in u.columns:
        future = u["gics_source"].astype(str).str.endswith("_next").to_numpy()
        if future.any():
            sub = sub.where(~future, None)
            ind = ind.where(~future, None)
    return sub.astype(object), ind.astype(object)


def exclude_sector_mask(u: pd.DataFrame, names=EXCLUDED_SECTORS, codes=None) -> pd.Series:
    """True for rows in an excluded GICS sector (Financials 40, Real Estate 60 by default; M2).

    Matches on the sector name as of the snapshot (case-insensitive) and on the 2-digit sector code of the
    GICS code columns (derived from ``names`` unless ``codes`` is given), so a pre-2016 REIT that GICS then
    filed under Financials is excluded too.
    """
    names = tuple(names or ())
    if codes is None:
        codes = tuple(SECTOR_CODES[n] for n in names if n in SECTOR_CODES)
    m = pd.Series(False, index=u.index)
    if "gics_sector" in u.columns and names:
        low = {str(n).lower() for n in names}
        m |= u["gics_sector"].astype(object).map(lambda v: isinstance(v, str) and v.strip().lower() in low)
    if codes:
        for col in ("sub_industry_code", "industry_code"):
            if col in u.columns:
                m |= _code_str(u[col]).map(lambda v: isinstance(v, str) and v[:2] in codes)
    return m.astype(bool)


# --------------------------------------------------------------------------------------------------
# multiples table (section 4.1)
# --------------------------------------------------------------------------------------------------
def multiples_table(ctx, date, univ: pd.DataFrame, basis: str = "TTM", stale_days: int = 135,
                    mcap: pd.DataFrame | None = None) -> pd.DataFrame:
    """Market cap, EV, P/E and EV/EBITDA for every company of ``univ`` that has fundamentals and a price.

    ``basis``  'TTM' uses ``net_income``/``ebitda``; 'LFY' uses ``net_income_lfy``/``ebitda_lfy`` (market cap
               and balance sheet are always the latest ones available at ``date``).
    ``mcap``   optional precomputed ``ctx.market_cap(date, univ)`` result.

    EV = mcap + total_debt + preferred + minority_interest - cash - st_investments.  ``total_debt`` and
    ``cash`` are required (NaN -> EV NaN, never imputed); ``preferred``, ``minority_interest`` and
    ``st_investments`` default to 0 when absent (a missing tag means the company has none).
    P/E = mcap / net income (valid only if net income > 0); EV/EBITDA = EV / EBITDA (valid only if EBITDA > 0
    and EV > 0).  ``fresh`` = latest balance-sheet period end within ``stale_days`` of ``date``.

    Returns index = cik (sorted) with columns: yf_ticker, name, gics_*, sub_code, ind_code, price (split-
    adjusted close), price_raw (as traded at ``date``), mcap, period_end, age_days, fresh, net_income, ebitda,
    total_debt, preferred, minority_interest, cash, st_investments, ev, pe, ev_ebitda, pe_valid, ev_valid.
    """
    date = pd.Timestamp(date).normalize()
    basis = str(basis).upper()
    if basis not in ("TTM", "LFY"):
        raise ValueError(f"basis must be 'TTM' or 'LFY', got {basis!r}")
    ni_col, eb_col = ("net_income", "ebitda") if basis == "TTM" else ("net_income_lfy", "ebitda_lfy")

    u = univ.dropna(subset=["cik"]).drop_duplicates("cik").copy()
    u["cik"] = u["cik"].astype("int64")
    u = u.set_index("cik")
    fund = ctx.fundamentals(date)
    mc = mcap if mcap is not None else ctx.market_cap(date, univ)
    if isinstance(mc, pd.Series):
        mc = mc.to_frame("mcap")
    idx = u.index.intersection(mc.index).intersection(fund.index)
    idx = pd.Index(sorted(idx), name="cik")
    u = u.reindex(idx)
    mc = mc.reindex(idx)
    fund = fund.reindex(idx)

    t = pd.DataFrame(index=idx)
    t["yf_ticker"] = u["yf_ticker"].astype(object) if "yf_ticker" in u.columns else mc.get("yf_ticker")
    t["name"] = u["name"].astype(object) if "name" in u.columns else None
    for c in GICS_NAME_COLS:
        t[c] = u[c].astype(object) if c in u.columns else None
    sub, ind = group_codes(u)
    t["sub_code"], t["ind_code"] = sub, ind
    t["price"] = _num(mc, "price", idx)
    mcap_s = _num(mc, "mcap", idx)
    t["mcap"] = mcap_s.where(mcap_s > 0)
    # as-traded price: yfinance Close is split-adjusted to today, a $5 floor must use the price of the day
    raw = t["price"].copy()
    sf = getattr(ctx, "price_factor_after", None) or getattr(ctx, "split_factor_after", None)
    if sf is not None and len(t):
        fac = np.array([sf(tk, date) for tk in t["yf_ticker"]], dtype=float)
        raw = t["price"] * fac
    t["price_raw"] = raw

    pe_end = pd.to_datetime(fund["period_end"], errors="coerce") if "period_end" in fund.columns \
        else pd.Series(pd.NaT, index=idx)
    t["period_end"] = pe_end
    t["age_days"] = (date - pe_end).dt.days.astype(float)
    t["fresh"] = (t["age_days"] <= stale_days) & (t["age_days"] >= 0)

    ni = _num(fund, ni_col, idx)
    eb = _num(fund, eb_col, idx)
    debt = _num(fund, "total_debt", idx)
    cash = _num(fund, "cash", idx)
    pref = _num(fund, "preferred", idx).fillna(0.0)
    mi = _num(fund, "minority_interest", idx).fillna(0.0)
    sti = _num(fund, "st_investments", idx).fillna(0.0)
    t["net_income"], t["ebitda"] = ni, eb
    t["total_debt"], t["cash"] = debt, cash
    t["preferred"], t["minority_interest"], t["st_investments"] = pref, mi, sti

    t["ev"] = t["mcap"] + debt + pref + mi - cash - sti          # NaN if mcap, debt or cash is missing
    with np.errstate(divide="ignore", invalid="ignore"):
        pe = t["mcap"] / ni
        evx = t["ev"] / eb
    t["pe_valid"] = (ni > 0) & t["mcap"].notna() & np.isfinite(pe)
    t["ev_valid"] = (eb > 0) & (t["ev"] > 0) & np.isfinite(evx)
    t["pe"] = pe.where(t["pe_valid"])
    t["ev_ebitda"] = evx.where(t["ev_valid"])
    t.attrs["basis"] = basis
    return t


# --------------------------------------------------------------------------------------------------
# eligibility (R6-R10)
# --------------------------------------------------------------------------------------------------
def _flag(km: pd.DataFrame | None, col: str, index: pd.Index) -> np.ndarray:
    if km is None or col not in km.columns:
        return np.zeros(len(index), dtype=bool)
    return km[col].reindex(index).fillna(False).astype(bool).to_numpy()


def multiple_eligibility(mt: pd.DataFrame, km: pd.DataFrame | None, multiple: str, cap: float | None) -> np.ndarray:
    """ok_m(j) = fresh and not recent IPO/merger and 0 < x_m(j) <= cap_m (peers AND targets, R6-R10)."""
    x = mt[_COL[multiple]].to_numpy(float)
    with np.errstate(invalid="ignore"):
        ok = mt["fresh"].to_numpy(bool) & np.isfinite(x) & (x > 0)
        if cap is not None and np.isfinite(cap):
            ok &= x <= float(cap)
    ok &= ~_flag(km, "recent_ipo", mt.index)
    ok &= ~_flag(km, "recent_merger", mt.index)
    return ok


# --------------------------------------------------------------------------------------------------
# peer selection + benchmark (section 5.3 pick_peers + trim)
# --------------------------------------------------------------------------------------------------
@dataclass
class PeerBench:
    """Result of ``peer_benchmark`` for one multiple; all arrays are aligned with the rows of ``mt``.

    level        0 = no signal (no level reached k_min peers), 1 = sub-industry, 2 = industry (fallback)
    n_pool       candidate peers at the deciding level before the closest-k cut (size window applied)
    n_peers      peers actually selected (closest k_max if the size filter is on, else all)
    m0           pre-trim median of the selected peers
    n_kept       peers within [trim_lo, trim_hi] x m0
    bench        median of the kept peers (NaN if fewer than k_trim_min were kept or no peers)
    fallback_tried  True if the sub-industry level failed and the industry level was tried
    sel_pos / kept_pos  (optional) positional indices into ``mt`` of the selected / kept peers per target
    """
    level: np.ndarray
    n_pool: np.ndarray
    n_peers: np.ndarray
    n_kept: np.ndarray
    m0: np.ndarray
    bench: np.ndarray
    fallback_tried: np.ndarray
    sel_pos: list | None = field(default=None, repr=False)
    kept_pos: list | None = field(default=None, repr=False)


def _eval_block(t_pos: np.ndarray, p_pos: np.ndarray, mc: np.ndarray, x: np.ndarray, size_filter: bool,
                p: dict, want_peers: bool):
    """Peer selection for targets ``t_pos`` against candidate peers ``p_pos`` (all positions into mt).

    Returns (n_pool, sat, sub) where ``sub`` is None if no target is satisfied, else a dict of arrays over the
    satisfied targets (``rows`` = indices into t_pos): n_sel, m0, nk, bench, and lists of selected / kept
    positions when ``want_peers``.
    """
    r, c = t_pos.size, p_pos.size
    mp = mc[p_pos][None, :]
    M = t_pos[:, None] != p_pos[None, :]                      # R1: the target is never its own peer
    if size_filter:                                            # R3: 0.5x <= mc_j / mc_i <= 2x
        ratio = mp / mc[t_pos][:, None]
        M &= (ratio >= p["size_lo"]) & (ratio <= p["size_hi"])
    n_pool = M.sum(axis=1)
    sat = n_pool >= int(p["k_min"])                            # R2/R4: need at least k_min peers
    if not sat.any():
        return n_pool, sat, None
    rows = np.flatnonzero(sat)
    Ms = M[rows]
    D = np.abs(np.log(mp) - np.log(mc[t_pos[rows]])[:, None])
    Dm = np.where(Ms, D, np.inf)
    if size_filter:                                            # R2: keep the k_max closest (ties: lower cik)
        order = np.argsort(Dm, axis=1, kind="stable")
        rank = np.argsort(order, axis=1, kind="stable")
        sel = Ms & (rank < int(p["k_max"]))
    else:                                                      # size filter off: all valid peers, no cap
        sel = Ms
    xp = x[p_pos][None, :]
    X = np.where(sel, xp, np.nan)
    n_sel = sel.sum(axis=1)
    m0 = np.nanmedian(X, axis=1)                               # pre-trim median
    kept = sel & (xp >= p["trim_lo"] * m0[:, None]) & (xp <= p["trim_hi"] * m0[:, None])   # R11
    nk = kept.sum(axis=1)
    bench = np.full(rows.size, np.nan)
    good = nk >= int(p["k_trim_min"])
    if good.any():
        bench[good] = np.nanmedian(np.where(kept[good], xp, np.nan), axis=1)
    out = dict(rows=rows, n_sel=n_sel, m0=m0, nk=nk, bench=bench)
    if want_peers:
        sel_l, kept_l = [], []
        for i in range(rows.size):
            js = np.flatnonzero(sel[i])
            js = js[np.argsort(Dm[i, js], kind="stable")]
            sel_l.append(p_pos[js])
            kept_l.append(p_pos[js[kept[i, js]]])
        out["sel_pos"], out["kept_pos"] = sel_l, kept_l
    return n_pool, sat, out


def peer_benchmark(mt: pd.DataFrame, ok: np.ndarray, multiple: str, size_filter: bool,
                   params: dict | None = None, return_peers: bool = False) -> PeerBench:
    """Section 5.3 ``pick_peers`` + trim for one multiple.

    ``ok`` is the eligibility mask of that multiple (``multiple_eligibility``): the same predicate defines
    who may be a peer and who may be a target.  For every eligible target: sub-industry peers first, then
    the industry if fewer than k_min qualify; the size window / closest-k rule is applied at each level;
    the selected peers are trimmed to [trim_lo, trim_hi] x their median; the benchmark is the median of
    those kept (NaN if fewer than k_trim_min).  No fallback is attempted after a failed trim (5.3).
    """
    p = merge_params(params)
    n = len(mt)
    x = mt[_COL[multiple]].to_numpy(float)
    mc = mt["mcap"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        ok = np.asarray(ok, dtype=bool) & np.isfinite(x) & (x > 0) & np.isfinite(mc) & (mc > 0)
    level = np.zeros(n, dtype=np.int8)
    n_pool = np.zeros(n, dtype=np.int32)
    n_peers = np.zeros(n, dtype=np.int32)
    n_kept = np.zeros(n, dtype=np.int32)
    m0 = np.full(n, np.nan)
    bench = np.full(n, np.nan)
    tried = np.zeros(n, dtype=bool)
    sel_pos = [None] * n if return_peers else None
    kept_pos = [None] * n if return_peers else None
    ok_pos = np.flatnonzero(ok)
    done = np.zeros(n, dtype=bool)
    if ok_pos.size:
        for lv, col in ((1, "sub_code"), (2, "ind_code")):
            if lv == 2:
                tried[ok & ~done] = True
            codes = mt[col].to_numpy(object)[ok_pos]
            fac, _ = pd.factorize(codes)                       # missing code -> -1 (no peer group)
            order = np.argsort(fac, kind="stable")
            cuts = np.flatnonzero(np.diff(fac[order])) + 1
            for chunk in np.split(order, cuts):
                if fac[chunk[0]] < 0:
                    continue
                members = ok_pos[chunk]
                targets = members if lv == 1 else members[~done[members]]
                if targets.size == 0:
                    continue
                npool, sat, sub = _eval_block(targets, members, mc, x, bool(size_filter), p, return_peers)
                n_pool[targets] = npool
                if sub is None:
                    continue
                tg = targets[sub["rows"]]
                level[tg] = lv
                n_peers[tg] = sub["n_sel"]
                n_kept[tg] = sub["nk"]
                m0[tg] = sub["m0"]
                bench[tg] = sub["bench"]
                done[tg] = True
                if return_peers:
                    for k, tpos in enumerate(tg):
                        sel_pos[tpos] = sub["sel_pos"][k]
                        kept_pos[tpos] = sub["kept_pos"][k]
    return PeerBench(level, n_pool, n_peers, n_kept, m0, bench, tried, sel_pos, kept_pos)


def pick_peers(mt: pd.DataFrame, ok: np.ndarray, cik, multiple: str, size_filter: bool = True,
               params: dict | None = None) -> tuple[list, str]:
    """Scalar reference version of the 5.3 ``pick_peers`` for ONE target (hand checks / audits).

    Returns (peer ciks, nearest first, level) with level in {'sub', 'industry', 'none'} ('na' if the target is
    not eligible for the multiple).  ``peer_benchmark`` is the vectorised version used by ``comps_signals``
    (tests assert they agree on a random universe).
    """
    p = merge_params(params)
    ok = np.asarray(ok, dtype=bool)
    x = mt[_COL[multiple]].to_numpy(float)
    mc = mt["mcap"].to_numpy(float)
    with np.errstate(invalid="ignore"):
        ok = ok & np.isfinite(x) & (x > 0) & np.isfinite(mc) & (mc > 0)
    pos = mt.index.get_loc(cik)
    if not ok[pos]:
        return [], "na"
    for level, col in (("sub", "sub_code"), ("industry", "ind_code")):
        codes = mt[col].to_numpy(object)
        code = codes[pos]
        if code is None or pd.isna(code):
            continue
        pool = np.flatnonzero(ok & np.array([c == code for c in codes]))
        pool = pool[pool != pos]
        if size_filter:
            ratio = mc[pool] / mc[pos]
            pool = pool[(ratio >= p["size_lo"]) & (ratio <= p["size_hi"])]
        if len(pool) >= int(p["k_min"]):
            dist = np.abs(np.log(mc[pool] / mc[pos]))
            pool = pool[np.argsort(dist, kind="stable")]
            if size_filter and len(pool) > int(p["k_max"]):
                pool = pool[: int(p["k_max"])]
            return list(mt.index[pool]), level
    return [], "none"


def trim_peers(values, params: dict | None = None) -> tuple[np.ndarray, float, float]:
    """R11 on a set of peer multiples: (kept mask, pre-trim median, benchmark = median of kept or NaN)."""
    p = merge_params(params)
    x = np.asarray(values, dtype=float)
    m0 = float(np.median(x))
    kept = (x >= p["trim_lo"] * m0) & (x <= p["trim_hi"] * m0)
    bench = float(np.median(x[kept])) if kept.sum() >= int(p["k_trim_min"]) else float("nan")
    return kept, m0, bench


def _bench_key(multiple: str, size_filter: bool, p: dict) -> tuple:
    cap = p[_CAP[multiple]]
    return (multiple, bool(size_filter), None if cap is None else float(cap), p["size_lo"], p["size_hi"],
            int(p["k_min"]), int(p["k_max"]), p["trim_lo"], p["trim_hi"], int(p["k_trim_min"]))


# --------------------------------------------------------------------------------------------------
# signals (R5, R12, K1-K3)
# --------------------------------------------------------------------------------------------------
def comps_signals(ctx, date, univ: pd.DataFrame | None, params: dict | None, km: pd.DataFrame | None,
                  mt: pd.DataFrame | None = None, cache: dict | None = None,
                  return_peers: bool = False) -> pd.DataFrame:
    """Comps signal for every company of ``univ`` at ``date`` (research/04 section 5.3, steps 2-4).

    Parameters
    ----------
    params  theta, pe_cap, ev_cap, size_filter, basis (+ the fixed knobs of ``COMPS_DEFAULTS``).
    km      ``key_metrics_table`` output (index = cik): recent_ipo, recent_merger (peer AND target exclusion),
            pass_leverage, quality_ok, pass_roic (target only gates), nd_ebitda.  ``None`` = no flags, gates open.
    mt      precomputed ``multiples_table`` (otherwise built from ``ctx``/``univ``).
    cache   optional dict, valid only for ONE (mt, km) pair: reuses the peer benchmarks across calls that
            differ only in theta (and in whichever cap/size_filter combinations were already computed).
    return_peers  also return the peer tickers/ciks (``pe_peers``/``ev_peers`` = selected, ``*_kept`` = kept).

    Returns index = cik with identity columns, the two multiples, and per multiple m in {pe, ev}:
    ``ok_m, m_level ('sub'/'industry'/'none'/'na'), m_npool, m_npeers, m_nkept, m_median (pre-trim),
    m_bench, m_disc, m_pass, m_status``; then ``comps_buy`` (AND), ``score``, the three gates, ``n_fail``,
    ``eligible`` and ``nd_ebitda``.
    """
    p = merge_params(params)
    if mt is None:
        mt = multiples_table(ctx, date, univ, p["basis"], p["stale_days"])
    cache = {} if cache is None else cache
    n = len(mt)
    out = pd.DataFrame(index=mt.index)
    for c in ("yf_ticker", "name", "gics_sector", "gics_sub_industry", "sub_code", "ind_code", "mcap"):
        out[c] = mt[c] if c in mt.columns else None
    out["pe"], out["ev_ebitda"] = mt["pe"], mt["ev_ebitda"]

    theta = float(p["theta"])
    for m in MULTIPLES:
        x = mt[_COL[m]].to_numpy(float)
        ok = multiple_eligibility(mt, km, m, p[_CAP[m]])
        key = _bench_key(m, p["size_filter"], p)
        pb = cache.get(key)
        if pb is None or (return_peers and pb.sel_pos is None):
            pb = peer_benchmark(mt, ok, m, bool(p["size_filter"]), p, return_peers)
            cache[key] = pb
        bench = pb.bench
        with np.errstate(invalid="ignore", divide="ignore"):
            disc = 1.0 - x / bench
            # R12: multiple < (1 - theta) x benchmark, strict
            passed = ok & np.isfinite(bench) & (x < (1.0 - theta) * bench)
        lvl = _LEVELS[pb.level].astype(object)
        lvl = np.where(ok, lvl, "na")
        status = np.where(~ok, "ineligible", np.where(pb.level == 0, "no_peers",
                                                      np.where(np.isfinite(bench), "ok", "trim_fail")))
        out[f"ok_{m}"] = ok
        out[f"{m}_level"] = lvl
        out[f"{m}_npool"] = pb.n_pool
        out[f"{m}_npeers"] = pb.n_peers
        out[f"{m}_nkept"] = pb.n_kept
        out[f"{m}_median"] = pb.m0
        out[f"{m}_bench"] = bench
        out[f"{m}_disc"] = np.where(ok & np.isfinite(bench), disc, np.nan)
        out[f"{m}_pass"] = passed
        out[f"{m}_status"] = status
        out[f"{m}_fallback_tried"] = pb.fallback_tried
        if return_peers:
            tick = mt["yf_ticker"].to_numpy(object)
            ciks = mt.index.to_numpy()
            out[f"{m}_peers"] = [list(tick[s]) if s is not None else [] for s in pb.sel_pos]
            out[f"{m}_kept"] = [list(tick[s]) if s is not None else [] for s in pb.kept_pos]
            out[f"{m}_peer_ciks"] = [list(ciks[s]) if s is not None else [] for s in pb.sel_pos]
            out[f"{m}_kept_ciks"] = [list(ciks[s]) if s is not None else [] for s in pb.kept_pos]

    out["comps_buy"] = out["pe_pass"] & out["ev_pass"]                  # R5: AND
    both = out["pe_disc"].notna() & out["ev_disc"].notna()
    out["score"] = ((out["pe_disc"] + out["ev_disc"]) / 2.0).where(both)

    # key-metric gates (K1-K3), target only (M1)
    gates = tuple(p.get("gates", ()))
    for g, col in _GATE_COLS.items():
        if km is not None and col in km.columns:
            v = km[col].reindex(mt.index).fillna(False).astype(bool).to_numpy()
        else:
            v = np.zeros(n, dtype=bool) if km is not None else np.ones(n, dtype=bool)
        out[col] = v if g in gates else np.ones(n, dtype=bool)
    if km is not None and "nd_ebitda" in km.columns:
        out["nd_ebitda"] = pd.to_numeric(km["nd_ebitda"], errors="coerce").reindex(mt.index)
    else:
        with np.errstate(divide="ignore", invalid="ignore"):
            nd = (mt["total_debt"] - mt["cash"] - mt["st_investments"]) / mt["ebitda"]
        out["nd_ebitda"] = nd.where(mt["ebitda"] > 0)
    out["recent_ipo"] = _flag(km, "recent_ipo", mt.index)
    out["recent_merger"] = _flag(km, "recent_merger", mt.index)
    out["st_leverage"] = out["comps_buy"] & out["pass_leverage"]
    out["st_quality"] = out["st_leverage"] & out["quality_ok"]
    out["eligible"] = out["st_quality"] & out["pass_roic"]
    # number of failed gates among: P/E discount, EV/EBITDA discount, leverage, quality, ROIC
    out["n_fail"] = (5 - out[["pe_pass", "ev_pass", "pass_leverage", "quality_ok", "pass_roic"]].sum(axis=1)).astype(int)
    return out


# --------------------------------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------------------------------
def stage_counts(sig: pd.DataFrame) -> dict:
    """Counts at each stage + fallback rate + average peer count for one rebalance date."""
    n = len(sig)
    d: dict = {"n_mt": int(n)}
    d["n_ok_pe"], d["n_ok_ev"] = int(sig["ok_pe"].sum()), int(sig["ok_ev"].sum())
    both = sig["ok_pe"] & sig["ok_ev"]
    d["n_valid_both"] = int(both.sum())
    hp_pe, hp_ev = sig["pe_level"].isin(["sub", "industry"]), sig["ev_level"].isin(["sub", "industry"])
    d["n_peers_pe"], d["n_peers_ev"] = int(hp_pe.sum()), int(hp_ev.sum())
    d["n_has_peers"] = int((both & hp_pe & hp_ev).sum())
    hb_pe, hb_ev = sig["pe_bench"].notna(), sig["ev_bench"].notna()
    d["n_has_bench"] = int((both & hb_pe & hb_ev).sum())
    d["n_pe_pass"], d["n_ev_pass"] = int(sig["pe_pass"].sum()), int(sig["ev_pass"].sum())
    d["n_comps_buy"] = int(sig["comps_buy"].sum())
    d["n_after_leverage"] = int(sig["st_leverage"].sum())
    d["n_after_quality"] = int(sig["st_quality"].sum())
    d["n_after_roic"] = int(sig["eligible"].sum())
    # fallback rate: share of targets that found peers (valid on the multiple) which needed the industry level
    for m, hp in (("pe", hp_pe), ("ev", hp_ev)):
        ok = sig[f"ok_{m}"] & hp
        d[f"fallback_rate_{m}"] = float((sig.loc[ok, f"{m}_level"] == "industry").mean()) if ok.any() else np.nan
        okv = sig[f"ok_{m}"]
        d[f"no_peer_rate_{m}"] = float((sig.loc[okv, f"{m}_level"] == "none").mean()) if okv.any() else np.nan
        d[f"avg_peers_{m}"] = float(sig.loc[ok, f"{m}_npeers"].mean()) if ok.any() else np.nan
        d[f"avg_kept_{m}"] = float(sig.loc[ok & sig[f"{m}_bench"].notna(), f"{m}_nkept"].mean()) \
            if (ok & sig[f"{m}_bench"].notna()).any() else np.nan
    both_hp = both & hp_pe & hp_ev
    if both_hp.any():
        used_fb = (sig.loc[both_hp, "pe_level"] == "industry") | (sig.loc[both_hp, "ev_level"] == "industry")
        d["fallback_rate"] = float(used_fb.mean())
        d["avg_peers"] = float((sig.loc[both_hp, "pe_npeers"] + sig.loc[both_hp, "ev_npeers"]).mean() / 2.0)
    else:
        d["fallback_rate"] = d["avg_peers"] = np.nan
    return d


def coverage_by_sector(sig: pd.DataFrame) -> pd.DataFrame:
    """Per GICS sector: names, share with an eligible P/E / EV/EBITDA, share with a benchmark for both,
    fallback share, BUY candidates and final eligibles (research/04 5.3 step 6 'coverage by sector')."""
    d = pd.DataFrame({
        "sector": sig["gics_sector"].astype(object).fillna("n/a"),
        "ok_pe": sig["ok_pe"], "ok_ev": sig["ok_ev"],
        "bench_both": sig["pe_bench"].notna() & sig["ev_bench"].notna(),
        "fallback": (sig["pe_level"] == "industry") | (sig["ev_level"] == "industry"),
        "comps_buy": sig["comps_buy"], "eligible": sig["eligible"]})
    g = d.groupby("sector")
    out = pd.DataFrame({"n": g.size(), "ok_pe": g["ok_pe"].mean(), "ok_ev": g["ok_ev"].mean(),
                        "bench_both": g["bench_both"].mean(),
                        "fallback": g["fallback"].sum() / g["bench_both"].sum().replace(0, np.nan),
                        "n_comps_buy": g["comps_buy"].sum(), "n_eligible": g["eligible"].sum()})
    return out.sort_values("n", ascending=False)
