"""Quality signals for the quality-filtered momentum strategy (research/02_quality.md).

Public API
    ARMS                                   arm id -> one-line description incl. evidence label
    quality_table(ctx, date, univ, max_age_days=200) -> DataFrame indexed by cik
    passes(qt, arm, **kw) -> bool Series (index = qt.index)
    blend_score(qt, mom, w) -> float Series  (arm Q4: (1-w)*pct_rank(mom) + w*pct_rank(gpoa))

Everything is point-in-time: fundamentals come from ``ctx.fundamentals(date)`` (filed < date) and the beta
uses daily returns up to and including ``date`` only.

Definitions (research/02 §3, §7.2-7.3). All ratios are decimals, "higher = better" after the sign flips below.
    GP      gross_profit, else revenue - cogs                      (snapshot already does this; re-applied defensively)
    GPOA    GP / assets                         GMAR  GP / revenue
    ROA     net_income_ttm / assets             ROE   net_income_ttm / book equity, MISSING when book equity <= 0
    CFOA    (cfo - capex) / assets              ACC   (cfo - net_income) / assets   (higher = lower accruals = better)
    LEV     -total_debt / assets                (missing debt stays missing, never 0)
    EVOL    snapshot `evol` (std of quarterly NI/assets, >= 12 quarters); z-score uses -EVOL
    beta    252-day daily beta vs SPY (>= 120 obs), shrunk 0.6*beta + 0.4; BAB = -beta
    book equity = equity_parent (else equity_total - minority_interest) - preferred (missing preferred = 0)

    z(x) = (rank(x) - mean(rank)) / std(rank), average ties, over the eligible non-missing names (population std).
    P  = z(mean_avail[z_gpoa, z_roe, z_roa, z_cfoa, z_gmar, z_acc])   needs >= 3 of 6
    S  = z(mean_avail[z_bab, z_lev, z_evol])                           needs >= 2 of 3
    QL = z(P + S)                                                      NaN if P or S is NaN

Eligible cross-section: every name in ``univ`` with a usable snapshot (assets > 0) EXCEPT GICS sector
'Financials' (if the sector is unknown, SIC 6000-6999 is treated as financial). Financials stay in the table
(raw ratios shown for audit) with ``eligible=False``; their z-scores/percentiles are NaN and ``passes`` is False
for them under every arm, including Q0.

Percentiles are in [0, 100]: pct = (rank - 1) / (n - 1) * 100 with average ties over the n non-missing eligible
names, so the median is 50 and "top 30%" is ``pct >= 70``.

Missing-data policy for ``passes``: a condition that cannot be evaluated (NaN input) is False (cannot verify =>
does not pass). This also applies to the junk veto Q5.
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

EXCLUDE_SECTORS = ("Financials", "Real Estate")   # REITs were GICS Financials until 2016-08-31
MIN_IND_FIRMS = 10          # industry-relative stats need >= 10 firms, else GICS industry group, else sector
BETA_WINDOW = 252           # trading days
BETA_MIN_OBS = 120
BETA_SHRINK = 0.6           # beta_shrunk = 0.6 * beta + 0.4 * 1
MARKET_TICKER = "SPY"
MIN_P_COMPONENTS = 3
MIN_S_COMPONENTS = 2

P_Z = ["z_gpoa", "z_roe", "z_roa", "z_cfoa", "z_gmar", "z_acc"]
S_Z = ["z_bab", "z_lev", "z_evol"]

ARMS: dict[str, str] = {
    "Q0": "No quality filter (control; still excludes Financials) [baseline]",
    "Q1-50": "GP/A percentile >= 50 (top half) [research-backed: Novy-Marx 2013]",
    "Q1-70": "GP/A percentile >= 70 (top 30%) [research-backed: Novy-Marx 2013 / PMU-QMJ breakpoints]",
    "Q1i-50": "Industry-demeaned GP/A percentile >= 50 [research-backed: Novy-Marx 2013 Table 1 Panel B]",
    "Q1i-70": "Industry-demeaned GP/A percentile >= 70 [research-backed: Novy-Marx 2013 Table 1 Panel B]",
    "Q2-P50": "QMJ-lite profitability composite P >= median [research-backed: AFP 2019 profitability block, EDGAR proxies]",
    "Q2-Q50": "QMJ-lite quality QL=z(P+S) >= median [research-backed in spirit: AFP 2019; no Growth/Payout, proxies]",
    "Q2-Q70": "QMJ-lite quality QL >= 70th pct (top 30%) [research-backed in spirit: AFP 2019 30/70 breakpoints]",
    "Q5-veto30": "Drop only the bottom 30% of QL (junk veto) [research-backed rationale (AFP Table 3), exact rule is heuristic]",
    "Q3a": "Team rule: NI_ttm>0 AND debt/equity<=X (equity>0, X=1.0) AND (GM>=ind. median OR ROE>=ind. median) [heuristic]",
    "Q3b": "NI_ttm>0 AND (ND/EBITDA<Y with EBITDA>0, or net debt<=0; Y=3.0) AND GP/A>=ind. median [heuristic]",
    "Q3c": "Q3b AND CFO_ttm>0 [heuristic]",
    "Q6": "Q1-50 AND Q3b (belt and braces) [heuristic combination]",
    "Q4-0.25": "No hard filter; rank on 0.75*pct(mom)+0.25*pct(GP/A) via blend_score [partly research-backed: Novy-Marx & Velikov 2016]",
    "Q4-0.5": "No hard filter; rank on 0.5*pct(mom)+0.5*pct(GP/A) via blend_score [partly research-backed: Novy-Marx & Velikov 2016]",
}

# columns returned by quality_table (order); extras beyond the required contract are appended at the end
QT_COLUMNS = [
    "yf_ticker", "gics_sector", "gics_industry", "period_end", "filed",
    "gpoa", "gmar", "roe", "roa", "cfoa", "acc", "lev", "debt_to_equity", "nd_ebitda", "evol", "beta",
    "net_income_ttm", "cfo_ttm", "ebitda_ttm",
    "z_gpoa", "z_roe", "z_roa", "z_cfoa", "z_gmar", "z_acc", "z_bab", "z_lev", "z_evol",
    "P", "S", "QL",
    "gpoa_pct", "gpoa_ind_pct", "ql_pct", "p_pct",
    "gmar_ge_ind_med", "roe_ge_ind_med", "gpoa_ge_ind_med",
    "eligible", "gics_industry_group", "beta_raw", "assets", "gross_profit_ttm", "book_equity", "total_debt",
    "net_debt", "s_pct", "n_p", "n_s",
]


# ------------------------------------------------------------------------------------------------ helpers
def _num(frame: pd.DataFrame, name: str) -> pd.Series:
    """Float column from `frame` (NaN series if absent); +-inf -> NaN."""
    if name in frame.columns:
        s = pd.to_numeric(frame[name], errors="coerce").astype("float64")
    else:
        s = pd.Series(np.nan, index=frame.index, dtype="float64")
    return s.replace([np.inf, -np.inf], np.nan)


def _ratio(num: pd.Series, den: pd.Series) -> pd.Series:
    out = num / den.where(den > 0)
    return out.replace([np.inf, -np.inf], np.nan)


def rank_z(s: pd.Series) -> pd.Series:
    """QMJ standardisation: (rank - mean rank) / std rank, average ties, NaN stays NaN (population std)."""
    x = pd.to_numeric(s, errors="coerce").astype("float64").replace([np.inf, -np.inf], np.nan)
    out = pd.Series(np.nan, index=x.index, dtype="float64")
    valid = x.notna()
    if not valid.any():
        return out
    r = x[valid].rank(method="average")
    sd = r.std(ddof=0)
    out[valid] = (r - r.mean()) / sd if sd > 0 else 0.0
    return out


def pct_rank(s: pd.Series, scale: float = 100.0) -> pd.Series:
    """(rank - 1) / (n - 1) * scale with average ties over non-missing values (n == 1 -> scale / 2)."""
    x = pd.to_numeric(s, errors="coerce").astype("float64").replace([np.inf, -np.inf], np.nan)
    out = pd.Series(np.nan, index=x.index, dtype="float64")
    valid = x.notna()
    n = int(valid.sum())
    if n == 0:
        return out
    if n == 1:
        out[valid] = scale / 2
        return out
    out[valid] = (x[valid].rank(method="average") - 1.0) / (n - 1.0) * scale
    return out


def _group_stat(x: pd.Series, levels: list[pd.Series], stat: str, min_n: int = MIN_IND_FIRMS) -> pd.Series:
    """Group statistic of `x` with fallback: first level whose group has >= min_n non-missing values
    (finest -> coarsest); the coarsest level accepts any group size; leftover rows get the overall statistic."""
    out = pd.Series(np.nan, index=x.index, dtype="float64")
    for i, key in enumerate(levels):
        need = 1 if i == len(levels) - 1 else min_n
        g = x.groupby(key)
        cnt = g.transform("count")
        val = g.transform(stat)
        use = out.isna() & (cnt >= need)
        out[use] = val[use]
    if out.isna().any() and x.notna().any():
        out = out.fillna(getattr(x, stat)())
    return out


# ------------------------------------------------------------------------------------------------ beta
def _beta_cache(ctx) -> dict:
    try:
        return ctx.__dict__.setdefault("_quality_beta_cache", {})
    except AttributeError:      # exotic ctx without __dict__: no caching
        return {}


def betas(ctx, date) -> pd.Series:
    """Raw 252-day daily OLS beta vs SPY for every column of ctx.returns, using data up to and including `date`.

    Pairwise-complete observations; needs >= BETA_MIN_OBS. If SPY is not in the returns panel the
    equal-weighted mean of all columns is used as the market proxy. Cached per (date, returns panel) on ctx.
    """
    date = pd.Timestamp(date).normalize()
    rets = ctx.returns
    cache = _beta_cache(ctx)
    key = (date, id(rets))
    if key in cache:
        return cache[key]
    sub = rets.loc[:date].iloc[-BETA_WINDOW:]
    if len(sub) == 0 or rets.shape[1] == 0:
        out = pd.Series(np.nan, index=rets.columns, dtype="float64")
        cache[key] = out
        return out
    if MARKET_TICKER in sub.columns:
        m = sub[MARKET_TICKER].to_numpy(dtype="float64")
    else:
        log.warning("%s not in returns panel; using equal-weighted market proxy", MARKET_TICKER)
        m = sub.mean(axis=1).to_numpy(dtype="float64")
    x = sub.to_numpy(dtype="float64")
    ok = np.isfinite(x) & np.isfinite(m)[:, None]
    x0 = np.where(ok, x, 0.0)
    m0 = np.where(ok, m[:, None], 0.0)
    n = ok.sum(axis=0).astype("float64")
    sx, sm = x0.sum(axis=0), m0.sum(axis=0)
    sxm, smm = (x0 * m0).sum(axis=0), (m0 * m0).sum(axis=0)
    with np.errstate(divide="ignore", invalid="ignore"):
        cov = (sxm - sm * sx / n) / (n - 1.0)
        var = (smm - sm * sm / n) / (n - 1.0)
        b = cov / var
    b[(n < BETA_MIN_OBS) | ~np.isfinite(b)] = np.nan
    out = pd.Series(b, index=sub.columns, dtype="float64")
    cache[key] = out
    return out


# ------------------------------------------------------------------------------------------------ main table
def quality_table(ctx, date, univ: pd.DataFrame, max_age_days: int = 200) -> pd.DataFrame:
    """Per-company quality metrics, QMJ-lite z-scores/composites and industry comparisons at `date`.

    `univ` is ``ctx.universe(date, 'SP1500')`` (needs cik, yf_ticker, gics_sector, gics_industry; optional
    gics_industry_group, sic). Returns a frame indexed by cik with the columns in ``QT_COLUMNS``.
    """
    date = pd.Timestamp(date).normalize()
    fund = ctx.fundamentals(date, max_age_days)

    u = univ.dropna(subset=["cik"]).copy()
    u["cik"] = u["cik"].astype("int64")
    u = u.drop_duplicates("cik").set_index("cik")
    keep = u.index.intersection(fund.index)
    u, f = u.loc[keep], fund.loc[keep]

    assets = _num(f, "assets")
    usable = assets > 0
    u, f, assets = u[usable], f[usable], assets[usable]
    idx = u.index

    qt = pd.DataFrame(index=idx)
    qt.index.name = "cik"
    qt["yf_ticker"] = u["yf_ticker"] if "yf_ticker" in u.columns else f.get("yf_ticker")
    for c in ("gics_sector", "gics_industry", "gics_industry_group"):
        qt[c] = u[c] if c in u.columns else pd.Series(np.nan, index=idx, dtype="object")
    qt["period_end"] = pd.to_datetime(f["period_end"]) if "period_end" in f.columns else pd.NaT
    qt["filed"] = pd.to_datetime(f["filed"]) if "filed" in f.columns else pd.NaT

    # eligibility: not Financials (SIC 6xxx if the sector is unknown)
    sector = qt["gics_sector"]
    fin = sector.isin(EXCLUDE_SECTORS)
    if "sic" in u.columns:
        sic = pd.to_numeric(u["sic"], errors="coerce")
        fin = fin | (sector.isna() & (sic >= 6000) & (sic < 7000))
    elig = ~fin.astype(bool)
    qt["eligible"] = elig

    # ---- raw accounting quantities
    rev, cogs = _num(f, "revenue"), _num(f, "cogs")
    gp = _num(f, "gross_profit")
    gp = gp.where(gp.notna(), rev - cogs)
    ni, cfo, capex = _num(f, "net_income"), _num(f, "cfo"), _num(f, "capex")
    debt = _num(f, "total_debt")
    cash = _num(f, "cash")
    sti = _num(f, "st_investments")
    ebitda = _num(f, "ebitda")
    ebitda = ebitda.where(ebitda.notna(), _num(f, "opinc") + _num(f, "da"))

    eq_par, eq_tot = _num(f, "equity_parent"), _num(f, "equity_total")
    be = eq_par.where(eq_par.notna(), eq_tot - _num(f, "minority_interest").fillna(0.0))
    be = be - _num(f, "preferred").fillna(0.0)

    qt["assets"] = assets
    qt["gross_profit_ttm"] = gp
    qt["book_equity"] = be
    qt["total_debt"] = debt
    qt["gpoa"] = gp / assets
    qt["gmar"] = _ratio(gp, rev)
    qt["roa"] = ni / assets
    qt["roe"] = _ratio(ni, be)                       # NaN when book equity <= 0
    qt["cfoa"] = (cfo - capex.abs()) / assets      # capex is a positive outflow; a few filers tag it negative
    qt["acc"] = (cfo - ni) / assets
    qt["lev"] = -debt / assets                       # NaN when debt is NaN
    qt["debt_to_equity"] = _ratio(debt, be)          # NaN when equity <= 0 or debt missing
    has_debt = debt.notna()
    net_debt = (debt - cash.fillna(0.0) - sti.fillna(0.0)).where(has_debt)
    qt["net_debt"] = net_debt
    qt["nd_ebitda"] = (net_debt / ebitda.where(ebitda > 0)).replace([np.inf, -np.inf], np.nan)
    qt["evol"] = _num(f, "evol")
    qt["net_income_ttm"] = ni
    qt["cfo_ttm"] = cfo
    qt["ebitda_ttm"] = ebitda

    # ---- beta (raw + shrunk)
    tick = qt["yf_ticker"]
    if len(idx):
        b_all = betas(ctx, date)
        beta_raw = pd.Series(tick.map(b_all).to_numpy(dtype="float64"), index=idx)
    else:
        beta_raw = pd.Series(np.nan, index=idx, dtype="float64")
    qt["beta_raw"] = beta_raw
    qt["beta"] = BETA_SHRINK * beta_raw + (1.0 - BETA_SHRINK)

    # ---- z-scores over the eligible cross-section
    def e(s: pd.Series) -> pd.Series:   # restrict to eligible names
        return s.where(elig)

    qt["z_gpoa"] = rank_z(e(qt["gpoa"]))
    qt["z_roe"] = rank_z(e(qt["roe"]))
    qt["z_roa"] = rank_z(e(qt["roa"]))
    qt["z_cfoa"] = rank_z(e(qt["cfoa"]))
    qt["z_gmar"] = rank_z(e(qt["gmar"]))
    qt["z_acc"] = rank_z(e(qt["acc"]))
    qt["z_bab"] = rank_z(e(-qt["beta"]))
    qt["z_lev"] = rank_z(e(qt["lev"]))
    qt["z_evol"] = rank_z(e(-qt["evol"]))

    pz, sz = qt[P_Z], qt[S_Z]
    qt["n_p"] = pz.notna().sum(axis=1)
    qt["n_s"] = sz.notna().sum(axis=1)
    p_raw = pz.mean(axis=1, skipna=True).where(qt["n_p"] >= MIN_P_COMPONENTS)
    s_raw = sz.mean(axis=1, skipna=True).where(qt["n_s"] >= MIN_S_COMPONENTS)
    qt["P"] = rank_z(e(p_raw))
    qt["S"] = rank_z(e(s_raw))
    qt["QL"] = rank_z(e(qt["P"] + qt["S"]))

    # ---- percentiles
    qt["gpoa_pct"] = pct_rank(e(qt["gpoa"]))
    qt["ql_pct"] = pct_rank(e(qt["QL"]))
    qt["p_pct"] = pct_rank(e(qt["P"]))
    qt["s_pct"] = pct_rank(e(qt["S"]))

    # ---- industry-relative quantities (eligible names only; fallback industry -> industry group -> sector)
    levels = [qt["gics_industry"], qt["gics_industry_group"], qt["gics_sector"]]
    levels = [lv for lv in levels if lv.notna().any()] or [pd.Series("all", index=idx)]
    gpoa_e = e(qt["gpoa"])
    ind_mean = _group_stat(gpoa_e, levels, "mean")
    qt["gpoa_ind_pct"] = pct_rank(e(qt["gpoa"] - ind_mean))
    for col, src in (("gmar_ge_ind_med", "gmar"), ("roe_ge_ind_med", "roe"), ("gpoa_ge_ind_med", "gpoa")):
        x = e(qt[src])
        med = _group_stat(x, levels, "median")
        qt[col] = ((x >= med) & x.notna() & med.notna()).astype(bool)

    qt = qt[QT_COLUMNS]
    return qt


# ------------------------------------------------------------------------------------------------ filters
def _true(qt: pd.DataFrame) -> pd.Series:
    return pd.Series(True, index=qt.index)


def _ge(s: pd.Series, thr: float) -> pd.Series:
    return (s >= thr).fillna(False).astype(bool)


def passes(qt: pd.DataFrame, arm: str, **kw) -> pd.Series:
    """Boolean pass/fail per cik for a filter arm of research/02 §7.4. NaN inputs => False.

    Optional keywords: Q3a ``X`` (max debt/equity, default 1.0); Q3b/Q3c/Q6 ``Y`` (ND/EBITDA cap, default 3.0);
    Q5-veto30 ``veto`` (bottom share of QL to drop in percent, default 30). Q4-* arms apply no hard filter
    (they return the eligible names with a GP/A value; rank them with ``blend_score``).
    """
    if arm not in ARMS:
        raise ValueError(f"unknown quality arm {arm!r}; choose from {sorted(ARMS)}")
    elig = qt["eligible"].astype(bool)

    def q3b(Y: float) -> pd.Series:
        lev_ok = (qt["net_debt"] <= 0) | ((qt["ebitda_ttm"] > 0) & (qt["nd_ebitda"] < Y))
        return (elig & (qt["net_income_ttm"] > 0) & lev_ok.fillna(False).astype(bool)
                & qt["gpoa_ge_ind_med"].astype(bool)).astype(bool)

    if arm == "Q0":
        out = elig
    elif arm in ("Q1-50", "Q1-70"):
        out = elig & _ge(qt["gpoa_pct"], float(arm.split("-")[1]))
    elif arm in ("Q1i-50", "Q1i-70"):
        out = elig & _ge(qt["gpoa_ind_pct"], float(arm.split("-")[1]))
    elif arm == "Q2-P50":
        out = elig & _ge(qt["p_pct"], 50.0)
    elif arm in ("Q2-Q50", "Q2-Q70"):
        out = elig & _ge(qt["ql_pct"], float(arm.split("-")[1][1:]))
    elif arm == "Q5-veto30":
        out = elig & _ge(qt["ql_pct"], float(kw.get("veto", 30.0)))
    elif arm == "Q3a":
        X = float(kw.get("X", 1.0))
        lev_ok = (qt["debt_to_equity"] <= X).fillna(False)
        rel = qt["gmar_ge_ind_med"].astype(bool) | qt["roe_ge_ind_med"].astype(bool)
        out = elig & (qt["net_income_ttm"] > 0) & lev_ok.astype(bool) & rel
    elif arm == "Q3b":
        out = q3b(float(kw.get("Y", 3.0)))
    elif arm == "Q3c":
        out = q3b(float(kw.get("Y", 3.0))) & (qt["cfo_ttm"] > 0)
    elif arm == "Q6":
        out = _ge(qt["gpoa_pct"], 50.0) & q3b(float(kw.get("Y", 3.0)))
    else:  # Q4-*: no hard filter
        out = elig & qt["gpoa"].notna()
    out = out.fillna(False).astype(bool)
    out.name = arm
    return out


def blend_score(qt: pd.DataFrame, mom: pd.Series, w: float) -> pd.Series:
    """Arm Q4: (1-w)*pct_rank(mom) + w*pct_rank(gpoa), both ranked in [0, 1] over the eligible names of `qt`.

    `mom` is indexed by cik (any superset/subset of qt.index; momentum is ranked only over names in qt that are
    eligible). Names with a missing momentum or GP/A (for 0 < w < 1) get NaN. Higher = better.
    """
    if not 0.0 <= w <= 1.0:
        raise ValueError("w must be in [0, 1]")
    if len(qt) and len(mom) and mom.index.intersection(qt.index).empty:
        raise ValueError("mom shares no index labels with qt (mom must be indexed by cik)")
    elig = qt["eligible"].astype(bool)
    m = mom[~mom.index.duplicated(keep="first")].reindex(qt.index)
    mp = pct_rank(m.where(elig), scale=1.0)
    gpp = pct_rank(qt["gpoa"].where(elig), scale=1.0)
    if w == 0.0:
        out = mp
    elif w == 1.0:
        out = gpp
    else:
        out = (1.0 - w) * mp + w * gpp
    out.name = f"Q4-{w:g}"
    return out
