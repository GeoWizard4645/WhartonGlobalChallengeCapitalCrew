"""Magic Formula (Greenblatt): ROC + earnings-yield rank sum, equal weight, 12-month holds.

Implements ``research/03_magic_formula.md`` ("Spec v1", sections 2.2, 2.3, 4, 6, 7, 8) on top of the
shared data layer.  Strategy contract (quant/ARCHITECTURE.md): ``DEFAULT``, ``GRID``,
``target_weights``, ``backtest``, ``live_picks``.  Extras: ``mf_table`` (full audit table),
``monthly_returns`` (grid input), ``ABLATIONS``, ``diagnostics``, ``coverage_start`` and ``preregister``.

Formula (per signal date t; CA = current assets, CL = current liabilities)
    EBIT          TTM operating income (snapshot ``opinc``; the data layer already falls back to
                  pretax + interest and flags it).  Ablation ``ebit='pretax_interest'``: pretax + interest.
    cash          cash + short-term investments
    excess_cash   max(0, min(cash, CA - CL))                (variants: 'all_cash', 'ratio2')
    NWC           (CA - excess_cash) - (CL - debt_current - op_lease_current), floored at 0
    capital       max(NWC + net PP&E, 1% of total assets)    (missing PP&E -> 0 with a flag)
    ROC           EBIT / capital
    EV            market cap + preferred + max(0, NCI) + total debt - excess_cash
    EY            EBIT / EV
    ranks         descending, 1 = best, average ties, among ELIGIBLE names only; score = r_ROC + r_EY;
                  final rank by (score asc, EY desc, market cap desc); buy the N best, equal weight.

Eligibility (all must hold; each failure is a named reason, see ``REASONS``)
    GICS sector not in {Financials, Real Estate, Utilities} (point-in-time sector from the universe row; if
    that is unmapped, the same company's sector at the nearest earlier/later snapshot, then the EDGAR SIC rule
    6000-6999 / 4900-4999 except 4950-4959; unknown => excluded), snapshot present and <= 200 days old,
    classified balance sheet (CA and CL), TTM EBIT > 0, debt mapped (or explicit zero), EV > 0, capital > 0,
    RAW (split-unadjusted) price >= $5 on the signal date, market cap >= ``min_cap``.

Universe
    ``'SP900'`` (primary): point-in-time S&P 500 + 400 members (S&P 600 history starts 2018-09), which limits survivorship bias (only
    names with a Yahoo price history can be traded, see the data audit for the coverage).
    ``'US_ALL'`` (robustness): today's listed US companies.  SURVIVORSHIP-BIASED: names that died or
    were acquired are missing, so its backtest is optimistic.  Never use it for headline numbers.

Start date of a tier (``coverage_start``)
    research/03 section 5.3: start when the data is complete enough.  Raw eligible counts are a poor yardstick
    (they rise with the market level and with index additions), so the default measure is the share of the
    formula-relevant population (non-excluded sector, price >= $5, market cap >= tier) that has complete usable
    inputs; a tier starts at the first month-end where this share is >= 90% of its 2014-2018 median and stays so
    for 3 more months.  The literal "eligible count >= 90% of plateau" rule is available (``column='elig'``).
    It only uses data availability, never returns.

Portfolio mechanics (signals at month-end close t, trades at the close of t+1, 10 bps one-way)
    ``holding='staggered'``  every month a sleeve buys the top N and holds 12 months
                             (``engine.run_sleeves(hold_months=12)``, the Jegadeesh-Titman cohort view).
    ``holding='annual'``     one rebalance per year, holding the top N for 12 months, run for all 12
                             possible start months.  The monthly return series used for the GRID is the
                             AVERAGE of the 12 start-month daily series (equal capital in each, months
                             in which fewer than 12 portfolios exist are averaged over those that do,
                             which is exactly the staggered ramp-up).  Note that by construction this is
                             almost the same object as the staggered view (same 12 live cohorts, same
                             monthly equalization); the useful extra output is the start-month spread
                             (``date_luck``), i.e. the date risk of a single-date annual rebalance.

No look-ahead: universe, GICS, fundamentals (``filed < t``), splits and shares all come from the
``DataContext`` as of ``t``; prices are closes of ``t``.
"""
from __future__ import annotations

import logging
import weakref
from dataclasses import dataclass, field
from pathlib import Path

import numpy as np
import pandas as pd

from quant import settings
from quant.backtest import engine, grid, metrics

log = logging.getLogger(__name__)

STRATEGY = "magic_formula"

# --------------------------------------------------------------------------------------------------
# constants (specification; not tuned)
# --------------------------------------------------------------------------------------------------
EXCLUDED_SECTORS = ("Financials", "Real Estate", "Utilities")   # point-in-time GICS sector names
PRICE_FLOOR = 5.0                  # raw (unadjusted) price on the signal date, USD
CAP_FLOOR_FRAC = 0.01              # capital >= 1% of total assets (research/03 section 4)
SNAPSHOT_MAX_AGE_DAYS = 200        # period_end older than this => stale => not eligible
SNAPSHOT_FETCH_AGE_DAYS = 400      # fetch window so stale names can be counted/audited
STALE_FLAG_DAYS = 150              # live table: flag period_end older than this
HOLD_MONTHS = 12
HIGH_EY_REVIEW = 0.40              # live table: manual-review flag (research/03 section 8.2)
INTEREST_TO_DEBT_REVIEW = 0.20     # live table: TTM interest / total debt above this => debt may be understated
# snapshot flags (quant/data/fundamentals.py) that matter for the formula inputs; shown in ``review_flags``
REVIEW_SNAP_FLAGS = ("ebit_proxy", "ebit_proxy_costs", "ebit_proxy_gp", "debt_zero_inferred", "debt_lowconf",
                     "debt_current_only", "ltd_excl_current", "ppe_derived", "cash_alt", "shares_stale",
                     "shares_bs", "multi_class_sum", "shares_scale_dropped", "amend_anchor")
COVERAGE_FRAC = 0.90               # start a tier when eligible count >= 90% of its plateau ...
COVERAGE_PLATEAU = ("2014-01-01", "2018-12-31")   # ... plateau = median count over this TRAIN window
COVERAGE_PERSIST = 3               # ... and it stays there for the next 3 month-ends
COVERAGE_SEARCH_FROM = "2009-12-31"

RANKINGS = ("MF", "EY", "ROC", "GPA")
HOLDINGS = ("staggered", "annual")
EXCESS_CASH_MODES = ("min_ca_cl", "all_cash", "ratio2")
EBIT_MODES = ("opinc", "pretax_interest")

# Exclusion reasons, in the priority order used for the mutually exclusive ``first_reason``.
REASONS = ("sector", "no_snapshot", "stale", "no_classified_bs", "mcap_missing", "price_lt_floor",
           "mcap_lt_min", "ebit_missing", "ebit_nonpos", "debt_unmapped", "ev_nonpos", "capital_nonpos",
           "gp_missing", "mom_low", "comps", "other")
_STRUCTURAL = ("sector", "no_snapshot", "stale", "no_classified_bs", "mcap_missing", "price_lt_floor",
               "ebit_missing", "ebit_nonpos", "debt_unmapped", "ev_nonpos", "capital_nonpos")

_EXCL_LOWER = {s.lower() for s in EXCLUDED_SECTORS}

UNIVERSE_NOTES = {
    "SP900": "point-in-time S&P 500 + MidCap 400 members (limits survivorship bias; S&P 600 history starts 2018-09)",
    "SP1500": "point-in-time S&P 500 + 400 + 600 members (600 only from 2018-09)",
    "US_ALL": "SURVIVORSHIP-BIASED: today's listed US companies only (dead/acquired names are missing)",
}

# --------------------------------------------------------------------------------------------------
# pre-registered design
# --------------------------------------------------------------------------------------------------
# v1 (doc) grid, run 2026-10-19: n {20,25,30} x min cap {$50M,$1B,$5B} x holding {staggered, annual};
# selected n=25, min cap $5B, staggered (the plateau was stable; the settings barely mattered).
# v2 grid (below): keeps the v1 choice and adds the value-trap momentum filter (Asness, Moskowitz & Pedersen 2013)
# and gross profit/assets as the quality rank (Novy-Marx 2013). Default = the v1 choice.
DEFAULT: dict = {
    "ranking": "MF",               # combined ROC + EY rank
    "n": 25,
    "min_cap": 5e9,                # USD
    "holding": "staggered",
    "universe": "SP900",
    "cost_bps": 10.0,              # one-way
    "excess_cash": "min_ca_cl",
    "ebit": "opinc",
    "mom_filter": 0.0,             # drop names in the bottom X of 12-1 momentum (value-trap guard); 0 = off
}

DOC_DEFAULT: dict = dict(DEFAULT, n=30, min_cap=1e9)
AXES: dict = {"n": [20, 25, 30], "mom_filter": [0.0, 0.3, 0.5]}      # ordinal
CATEGORICAL: dict = {"ranking": ["MF", "GPA"]}

GRID: list[dict] = [dict(DEFAULT, n=n, mom_filter=m, ranking=r)
                    for r in CATEGORICAL["ranking"] for n in AXES["n"] for m in AXES["mom_filter"]]

# One-at-a-time robustness around the SELECTED cell.  Name -> overrides; use ``ablation_params(base)``.
# Each one the lead runs is a trial in the ledger.
ABLATIONS: dict[str, dict] = {
    "ey_only": {"ranking": "EY"},
    "roc_only": {"ranking": "ROC"},
    "gpa_quality": {"ranking": "GPA"},                 # gross profit / assets instead of ROC
    "us_all_universe": {"universe": "US_ALL"},         # survivorship-biased
    "sp1500_universe": {"universe": "SP1500"},         # adds S&P 600 from 2018-09 only
    "all_cash": {"excess_cash": "all_cash"},
    "ebit_pretax_interest": {"ebit": "pretax_interest"},
    "cost_25bps": {"cost_bps": 25.0},
    "cost_50bps": {"cost_bps": 50.0},
}


def ablation_params(base: dict | None = None) -> dict[str, dict]:
    """Full parameter dicts of every ablation applied to ``base`` (default: ``DEFAULT``)."""
    base = dict(DEFAULT if base is None else base)
    return {name: {**base, **ov} for name, ov in ABLATIONS.items()}


def preregister(force: bool = False, out_dir=None) -> Path:
    """Write ``output/magic_formula/preregistration.json`` (idempotent; refuses a different grid)."""
    extra = dict(
        description="Magic Formula (research/03 Spec v1). 18-cell grid: n x min_cap x holding; ranking fixed at MF.",
        fixed={"ranking": "MF", "universe": "SP900", "cost_bps": 10.0, "excess_cash": "min_ca_cl",
               "ebit": "opinc", "hold_months": HOLD_MONTHS, "price_floor": PRICE_FLOOR,
               "capital_floor_frac_of_assets": CAP_FLOOR_FRAC, "max_snapshot_age_days": SNAPSHOT_MAX_AGE_DAYS,
               "excluded_gics_sectors": list(EXCLUDED_SECTORS)},
        ablations={k: v for k, v in ABLATIONS.items()},
        annual_cell_definition="mean of the 12 start-month daily return series (equal capital each); "
                               "start-month range reported separately (date_luck)",
        coverage_start_rule=dict(frac=COVERAGE_FRAC, plateau_window=list(COVERAGE_PLATEAU),
                                 persist_months=COVERAGE_PERSIST),
        train_window=[settings.BACKTEST_START, settings.TRAIN_END],
    )
    return grid.preregister(STRATEGY, GRID, axes=AXES, categorical=CATEGORICAL, default=DEFAULT,
                            out_dir=out_dir, force=force, extra=extra)


# --------------------------------------------------------------------------------------------------
# parameters
# --------------------------------------------------------------------------------------------------
def _params(params: dict | None) -> dict:
    p = {**DEFAULT, **(params or {})}
    if p["ranking"] not in RANKINGS:
        raise ValueError(f"ranking must be one of {RANKINGS}, got {p['ranking']!r}")
    if p["holding"] not in HOLDINGS:
        raise ValueError(f"holding must be one of {HOLDINGS}, got {p['holding']!r}")
    if p["excess_cash"] not in EXCESS_CASH_MODES:
        raise ValueError(f"excess_cash must be one of {EXCESS_CASH_MODES}, got {p['excess_cash']!r}")
    if p["ebit"] not in EBIT_MODES:
        raise ValueError(f"ebit must be one of {EBIT_MODES}, got {p['ebit']!r}")
    p["n"] = int(p["n"])
    if p["n"] < 1:
        raise ValueError("n must be >= 1")
    p["min_cap"] = float(p["min_cap"])
    p["cost_bps"] = float(p["cost_bps"])
    p["mom_filter"] = float(p["mom_filter"])
    if not 0.0 <= p["mom_filter"] < 1.0:
        raise ValueError("mom_filter must be in [0, 1)")
    return p


def universe_label(params: dict) -> str:
    u = _params(params)["universe"]
    return f"{u}: {UNIVERSE_NOTES.get(u, '')}".strip()


# --------------------------------------------------------------------------------------------------
# audit table
# --------------------------------------------------------------------------------------------------
_BASE_CACHE: "weakref.WeakKeyDictionary" = weakref.WeakKeyDictionary()


def clear_cache() -> None:
    """Drop the per-context caches (base tables, coverage counts)."""
    _BASE_CACHE.clear()


def _store(ctx) -> dict:
    d = _BASE_CACHE.get(ctx)
    if d is None:
        d = {}
        _BASE_CACHE[ctx] = d
    return d


def _clean_univ(univ: pd.DataFrame) -> pd.DataFrame:
    u = univ.copy()
    if "cik" not in u.columns:
        raise ValueError("universe frame needs a 'cik' column")
    u = u[u["cik"].notna()].copy()
    u["cik"] = u["cik"].astype("int64")
    u = u.drop_duplicates("cik", keep="first").set_index("cik")
    return u


def _col(df: pd.DataFrame, name: str, kind: str = "num") -> pd.Series:
    if name in df.columns:
        s = df[name]
        return pd.to_numeric(s, errors="coerce") if kind == "num" else s
    return pd.Series(np.nan if kind == "num" else None, index=df.index, dtype="float64" if kind == "num" else object)


def _sic(u: pd.DataFrame) -> pd.Series:
    if "sic" not in u.columns:
        return pd.Series(np.nan, index=u.index, dtype="float64")
    return pd.to_numeric(u["sic"], errors="coerce").astype("float64")


def _sector_history(ctx) -> dict:
    """cik -> (sorted snapshot dates, sectors) from every mapped SP1500 universe snapshot (quarter-ends).

    Used only to fill GICS sectors that the universe builder left unmapped (e.g. 2013-2016 Wikipedia pages).
    """
    st = _store(ctx)
    if "sector_hist" in st:
        return st["sector_hist"]
    frames = []
    dates = list(pd.date_range(ctx.dates[0], ctx.dates[-1], freq="QE")) + [ctx.dates[-1]]
    for d in dates:
        try:
            u = ctx.universe(d, "SP1500")   # sector back-fill only: widest label history
        except Exception:                                       # before the first price date, no membership, ...
            continue
        if "gics_sector" not in u.columns or "cik" not in u.columns:
            continue
        v = u[u["cik"].notna() & u["gics_sector"].notna()]
        frames.append(pd.DataFrame({"cik": v["cik"].astype("int64").to_numpy(),
                                    "date": ctx.trading_day_on_or_before(d), "sector": v["gics_sector"].to_numpy()}))
    hist: dict = {}
    if frames:
        allm = pd.concat(frames, ignore_index=True).drop_duplicates(["cik", "date"]).sort_values(["cik", "date"])
        for cik, g in allm.groupby("cik"):
            hist[int(cik)] = (g["date"].to_numpy(dtype="datetime64[ns]"), g["sector"].to_numpy(dtype=object))
    st["sector_hist"] = hist
    return hist


def _sic_map(ctx) -> pd.Series:
    """cik -> SIC from the US_ALL frame (static, current EDGAR SIC); empty if unavailable."""
    st = _store(ctx)
    if "sic_map" not in st:
        try:
            ua = ctx.universe(ctx.dates[-1], "US_ALL")
            st["sic_map"] = pd.Series(_sic(ua).to_numpy(), index=ua["cik"].astype("int64").to_numpy())
        except Exception:
            st["sic_map"] = pd.Series(dtype="float64")
    return st["sic_map"]


def _sector_info(ctx, date: pd.Timestamp, u: pd.DataFrame) -> tuple[pd.Series, pd.Series, pd.Series]:
    """(sector label, source, excluded?) per company.

    Source order: 'gics' (point-in-time sector in the universe row) -> 'gics_prev' / 'gics_next' (same company's
    sector at the nearest earlier / later mapped snapshot; only when the row's GICS is missing, which happens
    in the 2013-2016 universe) -> 'sic' (EDGAR SIC rule: exclude 6000-6999 and 4900-4999 except 4950-4959) ->
    'unknown' (excluded: we cannot show that it is not a financial or utility).
    """
    idx = u.index
    has_col = "gics_sector" in u.columns
    raw = u["gics_sector"] if has_col else pd.Series(np.nan, index=idx, dtype=object)
    lab = raw.fillna("").astype(str).str.strip()
    known = ~lab.str.lower().isin(["", "nan", "none"])
    sector = pd.Series(np.where(known, lab, ""), index=idx, dtype=object)
    source = pd.Series(np.where(known, "gics", ""), index=idx, dtype=object)
    if has_col and (~known).any():
        hist = _sector_history(ctx)
        dt = np.datetime64(pd.Timestamp(date), "ns")
        for cik in idx[~known.to_numpy()]:
            h = hist.get(int(cik))
            if h is None:
                continue
            ds, ss = h
            i = int(np.searchsorted(ds, dt, side="right"))
            sector[cik], source[cik] = (ss[i - 1], "gics_prev") if i > 0 else (ss[0], "gics_next")
    sic = _sic(u)
    miss = (source == "").to_numpy() & sic.isna().to_numpy()
    if miss.any():
        sm = _sic_map(ctx)
        if len(sm):
            sic = sic.where(~pd.Series(miss, index=idx), pd.Series(idx, index=idx).map(sm))
    sic_known = sic.notna()
    base_label = sector.str.lower().str.replace(r"\s*\(.*\)\s*$", "", regex=True)    # "Financials (Financial Services)"
    excl_gics = base_label.isin(_EXCL_LOWER)
    excl_sic = ((sic >= 6000) & (sic <= 6999)) | ((sic >= 4900) & (sic <= 4999) & ~((sic >= 4950) & (sic <= 4959)))
    unresolved = (source == "")
    use_sic = unresolved & sic_known
    excluded = np.where(~unresolved, excl_gics, np.where(use_sic, excl_sic, True))
    source = source.where(~use_sic, "sic").where(~(unresolved & ~sic_known), "unknown")
    return sector, source, pd.Series(excluded, index=idx).astype(bool)


def _excess_cash(mode: str, cash: pd.Series, ca: pd.Series, cl: pd.Series) -> pd.Series:
    c, a, l = cash.to_numpy(float), ca.to_numpy(float), cl.to_numpy(float)
    if mode == "min_ca_cl":
        out = np.maximum(0.0, np.minimum(c, a - l))
    elif mode == "all_cash":
        out = c
    elif mode == "ratio2":                                  # quant-investing style: only if CA > 2 x CL
        out = np.where(a > 2.0 * l, np.minimum(c, a - 2.0 * l), 0.0)
        out = np.where(np.isnan(a) | np.isnan(l), np.nan, out)
    else:  # pragma: no cover - validated in _params
        raise ValueError(mode)
    return pd.Series(out, index=cash.index)


def _build_base(ctx, date: pd.Timestamp, univ: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Everything that does not depend on min_cap / ranking: inputs, ROC, EV, EY and structural flags."""
    u = _clean_univ(univ)
    idx = u.index
    fund = ctx.fundamentals(date, max_age_days=SNAPSHOT_FETCH_AGE_DAYS).reindex(idx)
    mc = ctx.market_cap(date, u.reset_index(), max_age_days=SNAPSHOT_FETCH_AGE_DAYS).reindex(idx)

    def g(name: str) -> pd.Series:
        return _col(fund, name)

    has_snap = fund["period_end"].notna() if "period_end" in fund.columns else pd.Series(False, index=idx)
    period_end = pd.to_datetime(fund["period_end"] if "period_end" in fund.columns else pd.Series(pd.NaT, index=idx))
    filed = pd.to_datetime(fund["filed"] if "filed" in fund.columns else pd.Series(pd.NaT, index=idx))
    age_days = (date - period_end).dt.days.astype("float64")

    # ---- earnings
    if p["ebit"] == "pretax_interest":
        ebit = g("pretax") + g("interest_exp").fillna(0.0)
    else:
        ebit = g("opinc")

    # ---- balance sheet pieces
    ca, cl, assets = g("current_assets"), g("current_liabilities"), g("assets")
    cash_raw, sti = g("cash"), g("st_investments")
    cash = cash_raw.add(sti, fill_value=0.0)
    cash_missing = has_snap & cash.isna()
    cash = cash.where(~has_snap | cash.notna(), 0.0)
    excess = _excess_cash(p["excess_cash"], cash, ca, cl)
    dcur = g("debt_current").fillna(0.0)
    opl = g("op_lease_current").fillna(0.0)
    nwc_raw = (ca - excess) - (cl - dcur - opl)
    nwc = nwc_raw.clip(lower=0.0)
    ppe_raw = g("ppe_net")
    ppe_missing = has_snap & ppe_raw.isna()
    # Missing PP&E used to become 0, which pushed capital to the 1%-of-assets floor and made ROC explode for
    # producers that tag fixed assets with custom tags (APA: 4 of the top 8 live picks were E&Ps).
    # Conservative proxy instead: non-current tangible assets = assets - current assets - goodwill - intangibles.
    # It is an UPPER bound on net fixed assets, so it can only lower ROC, never inflate it.
    tangible_nc = (assets - ca - g("goodwill").fillna(0.0) - g("intangibles").fillna(0.0)).clip(lower=0.0)
    ppe = ppe_raw.fillna(tangible_nc).fillna(0.0)
    cap_raw = nwc + ppe
    floor_val = CAP_FLOOR_FRAC * assets
    capital = pd.Series(np.fmax(cap_raw.to_numpy(float), floor_val.to_numpy(float)), index=idx)
    capital = capital.where(cap_raw.notna())
    cap_floored = cap_raw.notna() & floor_val.notna() & (floor_val > cap_raw)
    with np.errstate(divide="ignore", invalid="ignore"):
        roc = pd.Series(np.where(capital > 0, ebit / capital, np.nan), index=idx)

    # ---- enterprise value
    def mcol(name: str) -> pd.Series:
        return pd.to_numeric(mc[name], errors="coerce").astype("float64") if name in mc.columns \
            else pd.Series(np.nan, index=idx, dtype="float64")

    price, shares, mcap = mcol("price"), mcol("shares_today_basis"), mcol("mcap")
    shares_source = mc["shares_source"] if "shares_source" in mc.columns else pd.Series(None, index=idx, dtype=object)
    tick = u["yf_ticker"]
    sf = np.array([(ctx.price_factor_after(t, date) if hasattr(ctx, "price_factor_after")
                    else ctx.split_factor_after(t, date)) if np.isfinite(pr) else np.nan
                   for t, pr in zip(tick.to_numpy(), price.to_numpy(float))])
    price_raw = pd.Series(price.to_numpy(float) * sf, index=idx)
    debt = g("total_debt")
    pref = g("preferred").fillna(0.0)
    nci_raw = g("minority_interest").fillna(0.0)
    nci = nci_raw.clip(lower=0.0)
    ev = mcap + pref + nci + debt - excess
    with np.errstate(divide="ignore", invalid="ignore"):
        ey = pd.Series(np.where(ev > 0, ebit / ev, np.nan), index=idx)
        gp = g("gross_profit")
        gpa = pd.Series(np.where(assets > 0, gp / assets, np.nan), index=idx)

    # ---- sector
    sec_label, sec_src, sec_excl = _sector_info(ctx, date, u)

    # ---- structural failures
    fail = {
        "sector": sec_excl,
        "no_snapshot": ~has_snap,
        "stale": has_snap & ~(age_days <= SNAPSHOT_MAX_AGE_DAYS),
        "no_classified_bs": has_snap & (ca.isna() | cl.isna()),
        "mcap_missing": ~np.isfinite(mcap),
        "price_lt_floor": price_raw.notna() & (price_raw < PRICE_FLOOR),
        "ebit_missing": has_snap & ebit.isna(),
        "ebit_nonpos": ebit.notna() & ~(ebit > 0),
        "debt_unmapped": has_snap & debt.isna(),
        "ev_nonpos": ev.notna() & ~(ev > 0),
        "capital_nonpos": capital.notna() & ~(capital > 0),
    }
    ok_struct = pd.Series(True, index=idx)
    for k in _STRUCTURAL:
        ok_struct &= ~fail[k].astype(bool)
    ok_struct &= np.isfinite(roc) & np.isfinite(ey)

    out = pd.DataFrame({
        "yf_ticker": tick,
        "name": u["name"] if "name" in u.columns else None,
        "gics_sector": sec_label.where(sec_label != "", None),
        "sector_source": sec_src,
        "sic": _sic(u),
        "period_end": period_end,
        "filed": filed,
        "age_days": age_days,
        "form": _col(fund, "form", "obj"),
        "snap_flags": _col(fund, "flags", "obj"),
        "ebit_ttm": ebit,
        "interest_exp": g("interest_exp"),
        "current_assets": ca,
        "current_liabilities": cl,
        "assets": assets,
        "cash_st": cash,
        "cash_missing": cash_missing,
        "excess_cash": excess,
        "debt_current": dcur,
        "op_lease_current": opl,
        "nwc_raw": nwc_raw,
        "nwc": nwc,
        "ppe_net": ppe,
        "ppe_missing": ppe_missing,
        "capital": capital,
        "capital_floored": cap_floored,
        "roc": roc,
        "gross_profit": gp,
        "gpa": gpa,
        "price": price,
        "price_raw": price_raw,
        "shares": shares,
        "shares_source": shares_source,
        "mcap": mcap,
        "total_debt": debt,
        "preferred": pref,
        "minority_interest": nci,
        "minority_interest_raw": nci_raw,
        "ev": ev,
        "ey": ey,
        "mom_12_1": _momentum(ctx, date, tick),
    }, index=idx)
    for k in _STRUCTURAL:
        out[f"fail_{k}"] = fail[k].astype(bool).to_numpy()
    out["ok_struct"] = ok_struct.to_numpy()
    return out


def _momentum(ctx, date: pd.Timestamp, tickers) -> np.ndarray:
    """12-1 total-return momentum P[t-21]/P[t-252]-1 on ``date`` (same signal as the momentum strategy)."""
    from quant.signals import technical as tech
    mom = tech.get_technicals(ctx).mom
    if date not in mom.index:
        return np.full(len(tickers), np.nan)
    return mom.loc[date].reindex(pd.Index(tickers)).to_numpy(dtype="float64")


def _rank_desc(s: pd.Series, mask: pd.Series) -> pd.Series:
    r = pd.Series(np.nan, index=s.index, dtype="float64")
    r[mask] = s[mask].rank(ascending=False, method="average")
    return r


def _finish(base: pd.DataFrame, p: dict) -> pd.DataFrame:
    """Apply the min_cap / ranking dependent part: eligibility, ranks, score, final rank."""
    t = base.copy()
    t["fail_mcap_lt_min"] = (t["mcap"].notna() & (t["mcap"] < p["min_cap"])).to_numpy()
    if p["ranking"] == "GPA":
        t["fail_gp_missing"] = (~np.isfinite(t["gpa"])).to_numpy()
    else:
        t["fail_gp_missing"] = False
    # Value-trap guard (Asness, Moskowitz & Pedersen 2013: value and momentum are negatively correlated, and
    # cheap stocks that are still falling keep falling): drop names in the bottom `mom_filter` fraction of 12-1
    # momentum, ranked across the whole universe on that date. Off when mom_filter == 0.
    if p["mom_filter"] > 0:
        pct = t["mom_12_1"].rank(pct=True)
        t["fail_mom_low"] = (~(pct >= p["mom_filter"])).to_numpy()      # NaN momentum fails
    else:
        t["fail_mom_low"] = False
    # optional second check with trading comps (too expensive vs GICS peers / fails the doc's key metrics)
    t["fail_comps"] = (~t["comps_ok"].astype(bool)).to_numpy() if "comps_ok" in t.columns else False
    t["eligible"] = (t["ok_struct"] & ~t["fail_mcap_lt_min"] & ~t["fail_gp_missing"] & ~t["fail_mom_low"]
                     & ~t["fail_comps"])
    named = np.column_stack([t[f"fail_{r}"].to_numpy(bool) for r in REASONS if r != "other"]).any(axis=1)
    t["fail_other"] = (~t["eligible"].to_numpy(bool)) & ~named          # ineligible without a named reason

    # reasons: all failing checks (non-exclusive) and the first one by priority (exclusive)
    fails = np.column_stack([t[f"fail_{r}"].to_numpy(bool) for r in REASONS])
    names = np.array(REASONS, dtype=object)
    t["reasons"] = [";".join(names[row]) for row in fails]
    first = np.where(fails.any(axis=1), names[fails.argmax(axis=1)], "")
    t["first_reason"] = first

    elig = t["eligible"]
    t["rank_roc"] = _rank_desc(t["roc"], elig)
    t["rank_ey"] = _rank_desc(t["ey"], elig)
    t["rank_gpa"] = _rank_desc(t["gpa"], elig) if p["ranking"] == "GPA" else np.nan
    mode = p["ranking"]
    if mode == "MF":
        score = t["rank_roc"] + t["rank_ey"]
    elif mode == "GPA":
        score = t["rank_gpa"] + t["rank_ey"]
    elif mode == "EY":
        score = t["rank_ey"]
    else:  # ROC
        score = t["rank_roc"]
    t["score"] = score
    order = t[elig].sort_values(["score", "ey", "mcap"], ascending=[True, False, False], kind="mergesort").index
    t["final_rank"] = np.nan
    t.loc[order, "final_rank"] = np.arange(1, len(order) + 1, dtype="float64")
    t["selected"] = t["final_rank"] <= p["n"]
    t = t.drop(columns=["ok_struct"])
    # eligible by final rank first, then the rest by market cap
    t = t.assign(_o=t["final_rank"].fillna(1e12), _m=-t["mcap"].fillna(0.0)).sort_values(["_o", "_m"]).drop(
        columns=["_o", "_m"])
    return t


def _universe(ctx, date: pd.Timestamp, p: dict) -> pd.DataFrame:
    return ctx.universe(date, p["universe"])


def _base_cached(ctx, date: pd.Timestamp, p: dict) -> pd.DataFrame:
    key = ("base", date, p["universe"], p["excess_cash"], p["ebit"])
    st = _store(ctx)
    b = st.get(key)
    if b is None:
        b = _build_base(ctx, date, _universe(ctx, date, p), p)
        st[key] = b
    return b


def _comps_on(p: dict) -> bool:
    return str(p.get("comps_max_premium", "none")).lower() != "none" or bool(p.get("comps_km", False))


def _table(ctx, date, p: dict) -> pd.DataFrame:
    d = ctx.trading_day_on_or_before(date)
    base = _base_cached(ctx, d, p)
    if _comps_on(p):
        from quant.shelved import trading_comps as tc
        mp = p.get("comps_max_premium", "none")
        ok = tc.check_mask(ctx, d, base.index, None if str(mp).lower() == "none" else float(mp),
                           bool(p.get("comps_km", False)))
        base = base.assign(comps_ok=ok.to_numpy(bool))
    return _finish(base, p)


# --------------------------------------------------------------------------------------------------
# Magic Formula as a veto on another strategy's picks (used by the merged momentum + MF strategy)
# --------------------------------------------------------------------------------------------------
# Score every business above the doc's $50M floor, with no momentum filter (momentum is the other strategy's job).
SCREEN_PARAMS: dict = dict(DEFAULT, min_cap=50e6, mom_filter=0.0, ranking="MF")


def screen(ctx, date) -> pd.DataFrame:
    """Magic Formula verdict on every universe stock on ``date`` (index = cik).

    mf_pct: percentile of the combined ROC + earnings-yield rank among the stocks MF can rank (0 = best,
    1 = worst; NaN when MF cannot rank it: excluded sector or missing data).
    mf_bad: EBIT, enterprise value or invested capital not positive, i.e. not a good business at any price.
    """
    d = ctx.trading_day_on_or_before(date)
    st = _store(ctx)
    key = ("screen", d)
    if key not in st:
        t = _table(ctx, d, _params(SCREEN_PARAMS))
        el = t["eligible"].astype(bool)
        pct = t.loc[el, "score"].rank(pct=True, method="average")      # lower score = better business + price
        st[key] = pd.DataFrame({
            "mf_pct": pct.reindex(t.index),
            "mf_bad": (t["fail_ebit_nonpos"].astype(bool) | t["fail_ev_nonpos"].astype(bool)
                       | t["fail_capital_nonpos"].astype(bool)),
        }, index=t.index)
    return st[key]


def keep_mask(scr: pd.DataFrame, ciks, cut: float) -> pd.Series:
    """True = the Magic Formula does not veto the stock.

    Vetoed: mf_bad, or a combined rank in the worst ``cut`` fraction (cut=0.5 drops the bottom half). Stocks MF
    cannot rank (excluded sector, missing data) are kept, since there is nothing to judge them on.
    """
    s = scr.reindex(pd.Index(ciks))
    keep = ~s["mf_bad"].fillna(False).astype(bool)
    keep &= ~(s["mf_pct"] > 1.0 - float(cut))                         # NaN percentile -> kept
    return keep


def mf_table(ctx, date, univ, params: dict | None = None) -> pd.DataFrame:
    """Full audit table for ``date`` (index = cik; best-ranked first, ineligible names last).

    ``univ`` is a universe frame (``ctx.universe(date, name)``) or a universe name, or ``None`` for the
    universe in ``params``.  Every input and output of the formula is a column; ``eligible``,
    ``reasons``/``first_reason`` and ``fail_*`` explain every exclusion; ``rank_roc``, ``rank_ey``,
    ``score``, ``final_rank`` and ``selected`` are the result.
    """
    p = _params(params)
    d = ctx.trading_day_on_or_before(date)
    if univ is None:
        univ = _universe(ctx, d, p)
    elif isinstance(univ, str):
        univ = ctx.universe(d, univ)
    return _finish(_build_base(ctx, d, univ, p), p)


# --------------------------------------------------------------------------------------------------
# dates
# --------------------------------------------------------------------------------------------------
def _is_complete_month_end(ctx, d: pd.Timestamp) -> bool:
    """True if ``d`` is the last trading day of its calendar month (or a data end within 4 days of it)."""
    pos = ctx.dates.searchsorted(d)
    if pos + 1 < len(ctx.dates):
        nxt = ctx.dates[pos + 1]
        return (nxt.year, nxt.month) != (d.year, d.month)
    return (d.to_period("M").end_time.normalize() - d).days <= 4


def signal_dates(ctx, start=None, end=None) -> list[pd.Timestamp]:
    """Month-end signal dates in [start, end]; a trailing incomplete month is dropped."""
    s = pd.Timestamp(start) if start is not None else ctx.dates[0]
    e = pd.Timestamp(end) if end is not None else ctx.dates[-1]
    me = list(ctx.month_ends(s, e))
    while me and not _is_complete_month_end(ctx, me[-1]):
        me = me[:-1]
    return me


# --------------------------------------------------------------------------------------------------
# coverage (when does a tier have enough data?)
# --------------------------------------------------------------------------------------------------
def _cap_label(mc: float) -> str:
    if mc >= 1e9 and mc % 1e9 == 0:
        return f"{int(mc / 1e9)}B"
    if mc >= 1e6 and mc % 1e6 == 0:
        return f"{int(mc / 1e6)}M"
    return f"{mc:g}"


def coverage_counts(ctx, universe: str = "SP900", caps=(50e6, 1e9, 5e9), start=COVERAGE_SEARCH_FROM,
                    end=COVERAGE_PLATEAU[1], params: dict | None = None) -> pd.DataFrame:
    """Per month-end data-coverage statistics for each market-cap tier (no returns involved).

    ``n_universe``/``n_snapshot``: universe size and names with a snapshot.  Per tier ``<cap>``:
    ``elig_<cap>`` eligible count (all rules, i.e. what the portfolio can pick from);
    ``pop_<cap>`` formula-relevant population = names outside the excluded sectors with raw price >= $5 and
    market cap >= tier (names whose market cap is unknown, e.g. no filing yet, stay in the population);
    ``cov_<cap>`` = share of that population with complete usable inputs (fresh snapshot, classified balance
    sheet, TTM EBIT, mapped debt, market cap).  ``cov`` is size- and universe-composition neutral, which raw
    eligible counts are not (they rise with the market level and with index additions).
    Ends at the TRAIN window end by default.
    """
    p = _params({**(params or {}), "universe": universe})
    rows = {}
    for d in signal_dates(ctx, start, end):
        b = _base_cached(ctx, ctx.trading_day_on_or_before(d), p)
        ok = b["ok_struct"]
        data_ok = ~(b["fail_no_snapshot"] | b["fail_stale"] | b["fail_no_classified_bs"] | b["fail_ebit_missing"]
                    | b["fail_debt_unmapped"] | b["fail_mcap_missing"])
        pop_base = ~b["fail_sector"] & ~b["fail_price_lt_floor"]
        row = {"n_universe": len(b), "n_snapshot": int((~b["fail_no_snapshot"]).sum())}
        for mc in caps:
            lab = _cap_label(mc)
            pop = pop_base & ~(b["mcap"] < mc)
            row[f"elig_{lab}"] = int((ok & (b["mcap"] >= mc)).sum())
            row[f"pop_{lab}"] = int(pop.sum())
            row[f"cov_{lab}"] = float((pop & data_ok).sum() / pop.sum()) if pop.sum() else np.nan
        rows[d] = row
    return pd.DataFrame.from_dict(rows, orient="index")


def coverage_start(ctx, min_cap: float, universe: str = "SP900", frac: float = COVERAGE_FRAC,
                   plateau=COVERAGE_PLATEAU, persist: int = COVERAGE_PERSIST,
                   search_from=COVERAGE_SEARCH_FROM, params: dict | None = None,
                   column: str = "cov") -> pd.Timestamp:
    """First month-end whose coverage is >= ``frac`` x its plateau and stays so for ``persist`` more months.

    ``column='cov'`` (default): the data-completeness share of ``coverage_counts`` (size/composition neutral).
    ``column='elig'``: the literal "eligible count reaches 90% of its plateau" rule of research/03 section 5.3,
    which is distorted here by market appreciation and index additions (reported for comparison only).
    plateau = median over ``plateau`` (a window inside TRAIN, after the XBRL phase-in).  The rule never looks
    at returns.
    """
    cnt = coverage_counts(ctx, universe, caps=(min_cap,), start=search_from, end=plateau[1], params=params)
    s = cnt[f"{column}_{_cap_label(min_cap)}"]
    ref = s[(s.index >= pd.Timestamp(plateau[0])) & (s.index <= pd.Timestamp(plateau[1]))]
    if ref.empty or not ref.median() > 0:
        raise ValueError("no coverage in the plateau window; cannot determine a coverage start")
    thr = frac * float(ref.median())
    ok = (s >= thr).to_numpy()
    for i in range(len(ok) - persist):
        if ok[i:i + persist + 1].all():
            return pd.Timestamp(s.index[i])
    raise ValueError("coverage threshold never reached")


def tier_start(ctx, params: dict | None = None) -> pd.Timestamp:
    p = _params(params)
    key = ("start", p["universe"], p["min_cap"], p["excess_cash"], p["ebit"])
    st = _store(ctx)
    if key not in st:
        st[key] = coverage_start(ctx, p["min_cap"], p["universe"], params=p)
    return st[key]


# --------------------------------------------------------------------------------------------------
# weights
# --------------------------------------------------------------------------------------------------
def target_weights(ctx, params: dict, dates: list) -> pd.DataFrame:
    """Equal-weight top-N book for each signal date (index = ``dates``, columns = yf_ticker).

    If fewer than N names are eligible the available ones share the book equally (fully invested).
    Which dates are used (monthly for 'staggered', one month per year for 'annual') is the caller's
    choice; see ``backtest``.
    """
    p = _params(params)
    idx = pd.DatetimeIndex([pd.Timestamp(d) for d in dates])
    rows: dict[pd.Timestamp, pd.Series] = {}
    for d in idx:
        t = _table(ctx, d, p)
        sel = t[t["selected"]].drop_duplicates("yf_ticker")
        m = len(sel)
        if m == 0:
            log.warning("%s: no eligible names; sleeve is cash", d.date())
            rows[d] = pd.Series(dtype=float)
            continue
        if m < p["n"]:
            log.warning("%s: only %d eligible names (< N=%d); equal weight over those", d.date(), m, p["n"])
        rows[d] = pd.Series(1.0 / m, index=sel["yf_ticker"].to_numpy())
    if not rows:
        return pd.DataFrame(index=idx, dtype=float)
    w = pd.DataFrame(rows).T.reindex(idx).fillna(0.0)
    w.index = idx
    return w.sort_index(axis=1).astype(float)


# --------------------------------------------------------------------------------------------------
# backtest
# --------------------------------------------------------------------------------------------------
@dataclass
class AnnualResult(engine.BacktestResult):
    """Annual-rebalance result: ``daily`` is the mean over the live start-month portfolios.

    ``by_start`` maps start month (1..12) to that portfolio's own ``BacktestResult``.  ``trades`` stacks
    the 12 trade logs (weights are fractions of the respective portfolio NAV; column ``start_month``).
    ``weights`` is left empty.  ``n_holdings`` in ``daily`` is the mean per start-month portfolio.
    """

    by_start: dict = field(default_factory=dict)


def _combine_annual(by_start: dict[int, engine.BacktestResult]) -> AnnualResult:
    frames = {s: r.daily for s, r in by_start.items() if len(r.daily)}
    if not frames:
        empty = engine._empty_result(pd.DatetimeIndex([]))
        return AnnualResult(daily=empty.daily, weights=empty.weights, trades=empty.trades, dropped=empty.dropped,
                            by_start=by_start)
    cat = pd.concat(frames, names=["start_month", "date"])
    num = [c for c in cat.columns if c != "rebalance"]
    daily = cat[num].groupby(level="date").mean()
    daily["rebalance"] = cat["rebalance"].groupby(level="date").any()
    daily["ret_net"] = daily["ret_gross"] - daily["cost"]
    daily = daily[engine._DAILY_COLUMNS]
    tr = [r.trades.assign(start_month=s) for s, r in by_start.items() if len(r.trades)]
    trades = pd.concat(tr, ignore_index=True) if tr else pd.DataFrame(columns=engine._TRADE_COLUMNS + ["start_month"])
    dr = [r.dropped.assign(start_month=s) for s, r in by_start.items() if len(r.dropped)]
    dropped = pd.concat(dr, ignore_index=True) if dr else pd.DataFrame(columns=engine._DROPPED_COLUMNS)
    return AnnualResult(daily=daily, weights=pd.DataFrame(index=daily.index), trades=trades, dropped=dropped,
                        by_start=by_start)


def backtest(ctx, params: dict, start=None, end=None, cost_bps: float | None = None, *,
             store_weights: bool = True) -> engine.BacktestResult:
    """Run the strategy.  ``start=None`` uses the coverage start of the tier (``tier_start``).

    ``cost_bps=None`` uses ``params['cost_bps']`` (default 10); an explicit value overrides it.
    'staggered' -> ``engine.run_sleeves(hold_months=12)``; 'annual' -> ``AnnualResult`` (12 start-month
    portfolios via ``engine.run``, averaged).  The universe label is logged: US_ALL is survivorship-biased.
    """
    p = _params(params)
    if cost_bps is not None and abs(float(cost_bps) - p["cost_bps"]) > 1e-12:
        log.info("explicit cost_bps=%s overrides params cost_bps=%s", cost_bps, p["cost_bps"])
    cost = p["cost_bps"] if cost_bps is None else float(cost_bps)
    if p["universe"] != "SP900":
        log.warning("universe %s", universe_label(p))
    s = pd.Timestamp(start) if start is not None else tier_start(ctx, p)
    dates = signal_dates(ctx, s, end)
    cfg = engine.BacktestConfig(cost_bps=cost)
    tw = target_weights(ctx, p, dates)
    # the simulation window ends at `end`: later returns must not be earned by the last books
    returns, rf = (ctx.returns, ctx.rf) if end is None else (ctx.returns.loc[:pd.Timestamp(end)],
                                                              ctx.rf.loc[:pd.Timestamp(end)])
    if p["holding"] == "staggered":
        return engine.run_sleeves(tw, HOLD_MONTHS, returns, rf, cfg, store_weights=store_weights)
    by_start = {}
    for m in range(1, 13):
        sub = tw[tw.index.month == m]
        if sub.empty:
            continue
        by_start[m] = engine.run(sub, returns, rf, cfg, store_weights=False)
    return _combine_annual(by_start)


def monthly_returns(ctx, params: dict, start=None, end=None, cost_bps: float | None = None) -> pd.Series:
    """Monthly NET return series of the cell (what ``grid.run_grid`` expects).

    Starts at the coverage start of the tier unless ``start`` is given.  The annual cell is the average
    of the 12 start-month portfolios (see module docstring).  A trailing incomplete month is dropped.
    """
    res = backtest(ctx, params, start, end, cost_bps, store_weights=False)
    r = res.monthly()
    last_day = ctx.dates[-1] if end is None else min(ctx.dates[-1], pd.Timestamp(end))
    if len(r) and last_day < r.index[-1] - pd.Timedelta(days=4):          # trailing incomplete month
        r = r.iloc[:-1]
    p = _params(params)
    r.name = f"mf_{p['holding']}_n{p['n']}_cap{_cap_label(p['min_cap'])}"
    return r


def make_grid_fn(ctx, start="common", end=None, cost_bps: float | None = None):
    """``fn(cell) -> monthly net returns`` closure for ``grid.run_grid`` (serial; not picklable).

    ``start='common'`` (default) gives every cell the same first signal month, ``common_start(ctx)`` (the latest
    tier coverage start in GRID), so the cells' return matrix is aligned; ``None`` = each cell's own tier start;
    or an explicit date.
    """
    st = common_start(ctx) if isinstance(start, str) and start == "common" else start

    def fn(cell: dict) -> pd.Series:
        return monthly_returns(ctx, cell, st, end, cost_bps)
    return fn


def common_start(ctx, cells: list[dict] | None = None) -> pd.Timestamp:
    """Latest tier coverage start across ``cells`` (default GRID): a start every cell can share."""
    cells = GRID if cells is None else cells
    return max(tier_start(ctx, c) for c in cells)


def _monthly_rf(ctx) -> pd.Series:
    rf = ctx.rf
    out = (1.0 + rf).groupby(rf.index.to_period("M")).prod() - 1.0
    out.index = out.index.to_timestamp(how="end").normalize()
    return out


def date_luck(res: AnnualResult, ctx=None, window=None) -> pd.DataFrame:
    """Start-month spread of the annual rebalance: CAGR / Sharpe / max drawdown per start month.

    Computed on the months common to all start-month portfolios (all 12 live), optionally clipped to
    ``window=(start, end)``.  Rows 1..12 are calendar start months; the last rows summarise (mean, min,
    max, range).  This is the "date luck" of a single annual rebalance.
    """
    series = {m: r.monthly() for m, r in res.by_start.items() if len(r.daily)}
    if not series:
        return pd.DataFrame()
    first = max(s.index[0] for s in series.values())
    last = min(s.index[-1] for s in series.values())
    if window is not None:
        lo, hi = (pd.Timestamp(window[0]) if window[0] is not None else first,
                  pd.Timestamp(window[1]) if window[1] is not None else last)
        first, last = max(first, lo), min(last, hi)
    rfm = _monthly_rf(ctx) if ctx is not None else None
    rows = {}
    for m, s in sorted(series.items()):
        x = s[(s.index >= first) & (s.index <= last)]
        f = rfm.reindex(x.index).fillna(0.0).to_numpy() if rfm is not None else 0.0
        rows[m] = dict(n_months=len(x), cagr=metrics.cagr(x, 12), sharpe=metrics.sharpe(x, f, 12),
                       maxdd=metrics.max_drawdown(x))
    df = pd.DataFrame(rows).T
    df.index.name = "start_month"
    summ = pd.DataFrame({"mean": df.mean(), "min": df.min(), "max": df.max(), "range": df.max() - df.min()}).T
    out = pd.concat([df, summ])
    out.attrs.update(window=(first, last))
    return out


# --------------------------------------------------------------------------------------------------
# diagnostics
# --------------------------------------------------------------------------------------------------
def diagnostics(ctx, params: dict, dates: list | None = None, start=None, end=None) -> pd.DataFrame:
    """Per signal date: universe size, eligible count, # excluded by each reason.

    ``first_<reason>`` columns are mutually exclusive (first failing check in ``REASONS`` order) and sum
    to ``n_universe - n_eligible``; ``fail_<reason>`` columns count every name failing that check.
    """
    p = _params(params)
    if dates is None:
        dates = signal_dates(ctx, start if start is not None else tier_start(ctx, p), end)
    rows = {}
    for d in dates:
        t = _table(ctx, d, p)
        row = {"n_universe": len(t), "n_snapshot": int((~t["fail_no_snapshot"]).sum()),
               "n_eligible": int(t["eligible"].sum()), "n_selected": int(t["selected"].sum())}
        sel = t[t["selected"]]
        row["median_mcap_selected"] = float(sel["mcap"].median()) if len(sel) else np.nan
        for r in REASONS:
            row[f"first_{r}"] = int((t["first_reason"] == r).sum())
        for r in REASONS:
            row[f"fail_{r}"] = int(t[f"fail_{r}"].sum())
        rows[pd.Timestamp(d)] = row
    return pd.DataFrame.from_dict(rows, orient="index")


def sector_mix(ctx, params: dict, dates: list) -> pd.DataFrame:
    """Average share of the selected names by GICS sector across ``dates`` (and the eligible-universe share)."""
    p = _params(params)
    picks, elig = [], []
    for d in dates:
        t = _table(ctx, d, p)
        picks.append(t.loc[t["selected"], "gics_sector"].fillna("unknown").value_counts(normalize=True))
        elig.append(t.loc[t["eligible"], "gics_sector"].fillna("unknown").value_counts(normalize=True))
    pk = pd.concat(picks, axis=1).fillna(0.0).mean(axis=1)
    el = pd.concat(elig, axis=1).fillna(0.0).mean(axis=1)
    return pd.DataFrame({"picks": pk, "eligible_universe": el}).fillna(0.0).sort_values("picks", ascending=False)


# --------------------------------------------------------------------------------------------------
# live
# --------------------------------------------------------------------------------------------------
LIVE_COLUMNS = ["pick", "final_rank", "yf_ticker", "name", "gics_sector", "mcap", "price_raw", "ey", "roc",
                "rank_ey", "rank_roc", "score", "ebit_ttm", "interest_exp", "ev", "capital", "nwc", "ppe_net", "assets",
                "current_assets", "current_liabilities", "cash_st", "excess_cash", "debt_current",
                "op_lease_current", "total_debt", "preferred", "minority_interest", "shares", "shares_source", "period_end", "filed", "age_days", "stale_flag", "review_flags", "snap_flags"]


def live_picks(ctx, params: dict, asof, n_alternates: int = 10) -> pd.DataFrame:
    """Top-N table as of ``asof`` plus the next ``n_alternates`` names, every input shown for audit.

    Columns include ``pick`` ('PICK' / 'ALT'), the formula inputs/outputs, ``age_days`` of the balance
    sheet, ``stale_flag`` (> 150 days) and ``review_flags`` (stale, EY > 40%, EBIT fallback, missing
    PP&E, inferred zero debt, shares not from the cover page, capital floored, negative NWC floored).
    ``.attrs`` carries ``sector_counts`` (picks / alternates / eligible universe by sector) and ``summary``.
    """
    p = _params(params)
    d = ctx.trading_day_on_or_before(asof)
    t = _table(ctx, d, p)
    el = t[t["eligible"]]
    top = el.nsmallest(p["n"] + n_alternates, "final_rank").copy()
    top["pick"] = np.where(top["final_rank"] <= p["n"], "PICK", "ALT")
    top["stale_flag"] = np.where(top["age_days"] > STALE_FLAG_DAYS, f"STALE>{STALE_FLAG_DAYS}d", "")

    def flags(r) -> str:
        f = []
        if r["age_days"] > STALE_FLAG_DAYS:
            f.append("stale")
        if r["ey"] > HIGH_EY_REVIEW:
            f.append("EY>40%")
        sf = set(str(r["snap_flags"]).split(";")) if pd.notna(r["snap_flags"]) else set()
        f.extend(f"snap:{k}" for k in REVIEW_SNAP_FLAGS if k in sf)
        if r["total_debt"] > 0 and r["interest_exp"] / r["total_debt"] > INTEREST_TO_DEBT_REVIEW:
            f.append("interest/debt>20%")
        if r["ppe_missing"]:
            f.append("ppe_missing")
        if r["capital_floored"]:
            f.append("capital_floored")
        if r["nwc_raw"] < 0:
            f.append("nwc<0")
        if r["shares_source"] != "cover":
            f.append(f"shares:{r['shares_source']}")
        if r["cash_missing"]:
            f.append("cash_missing")
        return ";".join(f)

    top["review_flags"] = [flags(r) for _, r in top.iterrows()]
    cols = [c for c in LIVE_COLUMNS if c in top.columns]
    out = top[cols].copy()
    out.index.name = "cik"
    sec_all = el["gics_sector"].fillna("unknown")
    picks = out[out["pick"] == "PICK"]
    alts = out[out["pick"] == "ALT"]
    sc = pd.DataFrame({
        "picks": picks["gics_sector"].fillna("unknown").value_counts(),
        "alternates": alts["gics_sector"].fillna("unknown").value_counts(),
        "eligible_universe": sec_all.value_counts(),
    }).fillna(0).astype(int).sort_values("picks", ascending=False)
    out.attrs["sector_counts"] = sc
    out.attrs["summary"] = dict(
        asof=d, params=p, universe=universe_label(p), n_universe=len(t), n_eligible=int(len(el)),
        n_picks=len(picks), n_alternates=len(alts), n_stale=int((picks["age_days"] > STALE_FLAG_DAYS).sum()),
        median_age_days=float(picks["age_days"].median()) if len(picks) else np.nan,
        excluded_by_first_reason=t.loc[~t["eligible"], "first_reason"].value_counts().to_dict())
    return out
