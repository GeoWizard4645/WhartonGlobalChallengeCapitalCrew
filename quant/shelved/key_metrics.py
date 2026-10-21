"""Key-metric gates and flags for the trading-comps strategy (research/04_trading_comps.md sections 4.2-4.5, 5.1 rows K1-K3, R10).

One public function::

    key_metrics_table(ctx, date, univ, params=None) -> pd.DataFrame      # index = cik

For every company in ``univ`` that has a usable point-in-time snapshot at ``date`` (``ctx.fundamentals(date)``,
i.e. latest filing with ``filed < date``) it returns the numbers behind each gate, the gates, and the recent IPO /
recent merger flags.  Everything uses only information available at ``date``.

Gates (all must hold for ``pass_all``)::

    leverage  ND/EBITDA = (total_debt - cash - st_investments) / ebitda_ttm, defined only if ebitda_ttm > 0
              labels: <0 'net cash', 0..1 'low', 1..nd_max 'ok', > nd_max 'high', undefined 'n/a'; pass if <= nd_max
    quality   fcf_ok    = FCF_ttm > 0 and >= fcf_min_pos of the last fcf_years fiscal years have FCF > 0
              margin_ok = >= 3 fiscal years of operating margin, OLS slope (pp/yr) >= slope_tol_pp,
                          om_ttm >= latest fiscal-year margin - recent_drop_pp, om_ttm > 0
    roic      ROIC = NOPAT / average(IC now, IC 4 quarters ago) > WACC  (see _wacc below)

Flags (reported, NOT part of ``pass_all``; the strategy applies them via research/04 R10)::

    recent_ipo     listing_age_days < ipo_days, listing start = min(first valid price date, first SEC filing date)
    recent_merger  acq_intensity >= acq_thr  or  share_jump >= share_thr  or  (asset_jump >= asset_thr and an
                   8-K Item 2.01 filed in the 365 days before ``date``)

Decisions that the spec leaves open (all documented in the returned columns / fail_reasons):
  * Missing data fails the gate (never imputed): a company whose capex, cash, EBITDA, ... is missing cannot pass.
    Short-term investments missing is treated as 0 (many firms have none); acquisitions missing is treated as 0.
  * The snapshot has no ``st_investments_4q``; IC four quarters ago uses today's short-term investments (a stable
    cash-like balance), so that IC(now) and IC(4q) subtract the same cash concept.
  * Interest expense <= 0 or missing is "missing" => Kd = rf + 2%.
  * share_jump: shares_diluted and shares_diluted_4q are put on one split basis with ``ctx.split_factor_after``
    (splits between filed-365d and filed).  The builder normally supplies the year-ago count restated in the current
    filing (same basis, ~97% of rows with a split in the window) but sometimes as originally reported (pre-split).
    When a split lies in the window the split-adjusted ratio replaces the plain ratio only if the split fully
    explains the change (residual |adj-1| <= 6%); otherwise the plain ratio is kept, so a merger that coincides with
    a split is still flagged.  Zero share counts are treated as missing.

  * total_debt missing in the latest snapshot (common for 10-Qs of filers that tag debt with XBRL dimensions, e.g.
    Caterpillar) is carried from the same company's most recent EARLIER filing with a value whose period_end is
    within ``debt_carry_days`` (default 400) of ``date``; ``debt_carried`` marks those rows.  Point-in-time safe
    (only filings with filed < date).  Set ``debt_carry_days=0`` to switch it off.

  * capex missing makes FCF undefined and fails the FCF test (many large filers use capex tags the snapshot builder
    does not map); ``capex_missing='cfo'`` is a sensitivity that uses CFO as the FCF proxy instead.

Extra (optional) keys read from ``params`` beyond DEFAULT_PARAMS: ``max_age_days`` (default 200, passed to
``ctx.fundamentals``), ``debt_carry_days`` (default 400), ``capex_missing`` ('fail' default | 'cfo') and
``rf_10y`` (scalar override of the 10-year yield, used in tests / what-if runs).
"""
from __future__ import annotations

import logging

import numpy as np
import pandas as pd

log = logging.getLogger(__name__)

DEFAULT_PARAMS = dict(nd_max=3.0, fcf_years=3, fcf_min_pos=2, margin_years=4, slope_tol_pp=-0.5, recent_drop_pp=1.0,
                      erp=0.05, beta_weeks=104, beta_min_weeks=90, ipo_days=730, acq_thr=0.10, share_thr=0.25,
                      asset_thr=0.40)

BLUME_W = 0.67                     # beta_adj = 0.67 * beta_raw + 0.33
TAX_LO, TAX_HI = 0.10, 0.35        # clip for the effective tax rate
STATUTORY_PRE_2018, STATUTORY_POST_2018 = 0.35, 0.21
SPLIT_RESIDUAL_TOL = 0.06          # a split "explains" a share-count change only if what is left is within +-6%
KD_CAP = 0.12                      # cost of debt cap
KD_SPREAD_FALLBACK = 0.02          # Kd = rf + 2% when debt is tiny or interest is missing
KD_MIN_DEBT_SHARE = 0.01           # debt < 1% of market cap => fallback
MIN_MARGIN_YEARS = 3
DEBT_CARRY_DAYS = 400              # a missing total_debt may be carried from the same company's earlier filing
ITEM_201_WINDOW_DAYS = 365
MARKET_TICKER = "SPY"
RF_FALLBACK = 0.04                 # only if the 10y yield cannot be loaded at all (logged)

COLUMNS = [
    "yf_ticker", "gics_sector", "mcap",
    # leverage
    "total_debt", "debt_carried", "cash_total", "ebitda_ttm", "nd_ebitda", "nd_label", "pass_leverage",
    # quality
    "fcf_ttm", "fcf_pos_years", "fcf_ok", "om_ttm", "om_fy1", "om_fy2", "om_fy3", "om_fy4", "om_fy5", "om_n",
    "om_slope_pp", "margin_ok", "quality_ok",
    # ROIC / WACC
    "tax_rate", "nopat", "ic_now", "ic_avg", "capital_light", "roic", "beta_raw", "beta_n", "beta_adj", "rf_10y",
    "ke", "kd", "wacc", "pass_roic",
    # flags
    "first_price_date", "first_filing_date", "listing_age_days", "recent_ipo", "acq_intensity", "share_jump",
    "asset_jump", "has_item_201", "recent_merger",
    # verdict
    "pass_all", "fail_reasons",
]


# ----------------------------------------------------------------------------------------------
# Small helpers
# ----------------------------------------------------------------------------------------------
def _col(df: pd.DataFrame, name: str) -> pd.Series:
    """Column as float Series, all-NaN when the snapshot lacks it."""
    if name in df.columns:
        return pd.to_numeric(df[name], errors="coerce").astype(float)
    return pd.Series(np.nan, index=df.index, dtype=float)


def _safe_div(a, b) -> pd.Series:
    a = pd.Series(a)
    b = pd.Series(b)
    with np.errstate(divide="ignore", invalid="ignore"):
        out = a / b.where(b != 0)
    return out.replace([np.inf, -np.inf], np.nan)


def row_ols_slope(y: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    """OLS slope of each row of ``y`` (columns = equally spaced time, oldest first) ignoring NaN.

    Returns (slope per step, number of valid points).  Rows with < 2 valid points give NaN.
    """
    y = np.asarray(y, dtype=float)
    v = np.isfinite(y)
    n = v.sum(axis=1)
    x = np.broadcast_to(np.arange(y.shape[1], dtype=float), y.shape)
    with np.errstate(divide="ignore", invalid="ignore"):
        mx = np.where(v, x, 0.0).sum(axis=1) / n
        my = np.where(v, y, 0.0).sum(axis=1) / n
        dx = np.where(v, x - mx[:, None], 0.0)
        dy = np.where(v, y - my[:, None], 0.0)
        slope = (dx * dy).sum(axis=1) / (dx * dx).sum(axis=1)
    slope[n < 2] = np.nan
    return slope, n


def statutory_tax(date) -> float:
    return STATUTORY_PRE_2018 if pd.Timestamp(date) < pd.Timestamp("2018-01-01") else STATUTORY_POST_2018


# ----------------------------------------------------------------------------------------------
# Auxiliary SEC tables (loaded lazily, once per process; tests monkeypatch the two loaders)
# ----------------------------------------------------------------------------------------------
_AUX: dict = {}


def _load_first_filing() -> pd.Series:
    """cik -> first_filing_date (any form) from quant.data.sec.load_companies()."""
    from quant.data import sec

    c = sec.load_companies()
    s = pd.Series(pd.to_datetime(c["first_filing_date"]).to_numpy(), index=c["cik"].astype("int64").to_numpy())
    return s[~s.index.duplicated(keep="first")]


def _load_item_201() -> pd.DataFrame:
    """All 8-K filings reporting Item 2.01 (completion of acquisition or disposition): columns cik, filing_date."""
    from quant.data import sec

    f = sec.load_filings(forms=["8-K"])
    m = f["items"].astype("string").str.contains(r"(?:^|,)\s*2\.01\s*(?:,|$)", regex=True, na=False)
    out = f.loc[m.to_numpy(dtype=bool), ["cik", "filing_date"]].copy()
    out["cik"] = out["cik"].astype("int64")
    return out.sort_values("filing_date").reset_index(drop=True)


def _aux_first_filing() -> pd.Series:
    if "first_filing" not in _AUX:
        try:
            _AUX["first_filing"] = _load_first_filing()
        except Exception as e:  # missing cache => IPO flag falls back to prices only
            log.warning("first_filing_date unavailable (%s); IPO age uses first price date only", e)
            _AUX["first_filing"] = pd.Series(dtype="datetime64[ns]")
    return _AUX["first_filing"]


def _aux_item_201() -> pd.DataFrame:
    if "item201" not in _AUX:
        try:
            _AUX["item201"] = _load_item_201()
        except Exception as e:
            log.warning("8-K Item 2.01 table unavailable (%s); merger flag ignores the 8-K condition", e)
            _AUX["item201"] = pd.DataFrame({"cik": pd.Series(dtype="int64"),
                                            "filing_date": pd.Series(dtype="datetime64[ns]")})
    return _AUX["item201"]


def clear_aux_cache() -> None:
    _AUX.clear()


def _ctx_cache(ctx) -> dict:
    """Per-context scratch dict (weekly return matrix, first price dates, beta by date)."""
    c = getattr(ctx, "_km_cache", None)
    if c is None:
        c = {}
        try:
            setattr(ctx, "_km_cache", c)
        except Exception:  # frozen / slotted context: no caching
            pass
    return c


# ----------------------------------------------------------------------------------------------
# Beta
# ----------------------------------------------------------------------------------------------
def weekly_returns(daily_returns: pd.DataFrame) -> pd.DataFrame:
    """Compound daily total returns into Friday-to-Friday weekly returns (label = the week's Friday).

    A week whose Friday is a holiday ends on the previous trading day.  A (stock, week) with no valid daily
    return stays NaN.
    """
    lr = np.log1p(daily_returns.clip(lower=-0.999))
    wk = lr.index.to_period("W-FRI")
    w = lr.groupby(wk).sum(min_count=1)
    w.index = w.index.end_time.normalize()
    return np.expm1(w)


def _weekly(ctx) -> tuple[pd.DatetimeIndex, np.ndarray, dict, np.ndarray | None]:
    cache = _ctx_cache(ctx)
    if "weekly" not in cache:
        w = weekly_returns(ctx.returns)
        mkt = w[MARKET_TICKER].to_numpy(dtype=float) if MARKET_TICKER in w.columns else None
        cache["weekly"] = (w.index, w.to_numpy(dtype=float), {t: i for i, t in enumerate(w.columns)}, mkt)
    return cache["weekly"]


def betas_at(ctx, date, tickers, weeks: int = 104, min_weeks: int = 90) -> pd.DataFrame:
    """Raw OLS beta of weekly (Fri-Fri) total returns vs SPY over the last ``weeks`` complete weeks ending <= date.

    Returns a frame indexed like ``tickers`` with beta_raw and beta_n (number of paired weeks); beta_raw is NaN when
    fewer than ``min_weeks`` paired observations exist.  Vectorised over all tickers; cached per (date, window).
    """
    tickers = pd.Index(tickers)
    widx, W, col_pos, mkt = _weekly(ctx)
    out = pd.DataFrame({"beta_raw": np.nan, "beta_n": 0}, index=tickers)
    if mkt is None or len(widx) == 0:
        return out
    date = pd.Timestamp(date).normalize()
    cache = _ctx_cache(ctx)
    key = ("beta", date, weeks, min_weeks)
    if key not in cache:
        j = int(widx.searchsorted(date, side="right"))          # weeks with Friday label <= date
        lo = max(0, j - weeks)
        X, y = W[lo:j], mkt[lo:j]
        v = np.isfinite(X) & np.isfinite(y)[:, None]
        n = v.sum(axis=0)
        Xz = np.where(v, X, 0.0)
        yz = np.where(v, y[:, None], 0.0)
        with np.errstate(divide="ignore", invalid="ignore"):
            mx, my = Xz.sum(0) / n, yz.sum(0) / n
            sxy = (Xz * yz).sum(0) - n * mx * my
            syy = (yz * yz).sum(0) - n * my * my
            beta = sxy / syy
        beta[(n < min_weeks) | ~np.isfinite(beta)] = np.nan
        cache[key] = (beta, n)
    beta, n = cache[key]
    pos = np.array([col_pos.get(t, -1) for t in tickers])
    ok = pos >= 0
    out.loc[ok, "beta_raw"] = beta[pos[ok]]
    out.loc[ok, "beta_n"] = n[pos[ok]]
    return out


# ----------------------------------------------------------------------------------------------
# Listing age / split basis
# ----------------------------------------------------------------------------------------------
def _first_price_dates(ctx) -> pd.Series:
    cache = _ctx_cache(ctx)
    if "first_price" not in cache:
        close = ctx.close
        valid = close.notna().to_numpy()
        has = valid.any(axis=0)
        first = pd.Series(pd.NaT, index=close.columns, dtype="datetime64[ns]")
        idx = valid.argmax(axis=0)
        first[has] = close.index[idx[has]]
        cache["first_price"] = first
    return cache["first_price"]


def _split_adjusted_share_ratio(ctx, tickers: pd.Series, now: pd.Series, prev: pd.Series,
                                filed: pd.Series) -> pd.Series:
    """shares_now / shares_year_ago on a common split basis (see module docstring)."""
    r = _safe_div(now, prev)
    f = pd.Series(1.0, index=r.index)
    sf = getattr(ctx, "split_factor_after", None)
    if sf is not None:
        for cik in r.index[r.notna()]:
            t, d = tickers.get(cik), filed.get(cik)
            if t is None or pd.isna(t) or pd.isna(d):
                continue
            f_now = sf(t, d)
            f_prev = sf(t, pd.Timestamp(d) - pd.Timedelta(days=365))
            f.at[cik] = f_now / f_prev if f_prev else 1.0
    adj = r * f
    use_adj = (f != 1.0) & ((adj - 1).abs() <= SPLIT_RESIDUAL_TOL) & ((adj - 1).abs() < (r - 1).abs())
    return r.where(~use_adj, adj)


def _debt_with_carry(ctx, fund: pd.DataFrame, date, max_days: int) -> tuple[pd.Series, pd.Series]:
    """total_debt, filling NaN from the same company's latest EARLIER filing (filed < date) that has one.

    Some filers (e.g. Caterpillar) tag consolidated debt with dimensions in 10-Qs, so only the 10-K snapshot has an
    undimensioned total.  The carried value must come from a filing whose period_end is within ``max_days`` of
    ``date``.  Returns (debt, carried_flag).  ``max_days <= 0`` or a context without ``snaps`` disables it.
    """
    debt = _col(fund, "total_debt")
    carried = pd.Series(False, index=fund.index)
    snaps = getattr(ctx, "snaps", None)
    miss = debt.index[debt.isna()]
    if max_days <= 0 or snaps is None or len(miss) == 0 or "total_debt" not in snaps.columns:
        return debt, carried
    cache = _ctx_cache(ctx)
    if "debt_hist" not in cache:
        h = snaps.loc[snaps["total_debt"].notna(), ["cik", "filed", "period_end", "total_debt"]]
        cache["debt_hist"] = h.sort_values("filed").reset_index(drop=True)
    h = cache["debt_hist"]
    m = (h["cik"].isin(miss) & (h["filed"] < date) & (h["period_end"] >= date - pd.Timedelta(days=int(max_days))))
    last = h[m].groupby("cik")["total_debt"].last()
    fill = last.reindex(miss).dropna()
    debt = debt.copy()
    debt.loc[fill.index] = fill.to_numpy()
    carried.loc[fill.index] = True
    return debt, carried


# ----------------------------------------------------------------------------------------------
# Market cap adapter
# ----------------------------------------------------------------------------------------------
def _market_cap(ctx, date, univ: pd.DataFrame, params: dict) -> pd.Series:
    args = (date, univ) if "max_age_days" not in params else (date, univ, params["max_age_days"])
    mc = ctx.market_cap(*args)
    if isinstance(mc, pd.DataFrame):
        mc = mc["mcap"]
    return pd.to_numeric(mc, errors="coerce").astype(float)


def _rf(date, params: dict) -> float:
    if params.get("rf_10y") is not None:
        return float(params["rf_10y"])
    try:
        from quant.data import rates

        return float(rates.ten_year(date))
    except Exception as e:
        log.warning("10y Treasury yield unavailable (%s); using %.2f%%", e, RF_FALLBACK * 100)
        return RF_FALLBACK


# ----------------------------------------------------------------------------------------------
# Main entry point
# ----------------------------------------------------------------------------------------------
def key_metrics_table(ctx, date, univ: pd.DataFrame, params: dict | None = None) -> pd.DataFrame:
    P = {**DEFAULT_PARAMS, **(params or {})}
    date = ctx.trading_day_on_or_before(date) if hasattr(ctx, "trading_day_on_or_before") else pd.Timestamp(date)
    date = pd.Timestamp(date).normalize()

    u = univ.dropna(subset=["cik"]).copy()
    u["cik"] = u["cik"].astype("int64")
    u = u.drop_duplicates("cik")
    fund = ctx.fundamentals(date, P.get("max_age_days", 200))
    fund = fund[fund.index.isin(u["cik"])]
    u = u.set_index("cik")
    if fund.empty:
        return pd.DataFrame(columns=COLUMNS).rename_axis("cik")
    idx = fund.index
    tick = u["yf_ticker"].reindex(idx)
    out = pd.DataFrame(index=idx)
    out["yf_ticker"] = tick
    out["gics_sector"] = u["gics_sector"].reindex(idx) if "gics_sector" in u.columns else np.nan

    mcap = _market_cap(ctx, date, u.reset_index(), P).reindex(idx)
    out["mcap"] = mcap

    # ------------------------------------------------------------------ leverage (K1)
    debt, debt_carried = _debt_with_carry(ctx, fund, date, int(P.get("debt_carry_days", DEBT_CARRY_DAYS)))
    cash_tot = _col(fund, "cash") + _col(fund, "st_investments").fillna(0.0)
    opinc = _col(fund, "opinc")
    ebitda = _col(fund, "ebitda")
    ebitda = ebitda.fillna(opinc + _col(fund, "da"))
    nd = debt - cash_tot
    nd_ebitda = (nd / ebitda.where(ebitda > 0)).replace([np.inf, -np.inf], np.nan)
    nd_max = float(P["nd_max"])
    label = np.select(
        [nd_ebitda.isna(), nd_ebitda < 0, nd_ebitda > nd_max, nd_ebitda <= 1.0],
        ["n/a", "net cash", "high", "low"], default="ok")
    out["total_debt"], out["debt_carried"], out["cash_total"], out["ebitda_ttm"] = debt, debt_carried, cash_tot, ebitda
    out["nd_ebitda"] = nd_ebitda
    out["nd_label"] = label
    pass_lev = (nd_ebitda <= nd_max).fillna(False).astype(bool)
    out["pass_leverage"] = pass_lev

    # ------------------------------------------------------------------ free cash flow (K2a)
    capex_fill = 0.0 if P.get("capex_missing", "fail") == "cfo" else np.nan        # 'cfo': FCF proxy = CFO if no capex
    fcf_ttm = _col(fund, "cfo") - _col(fund, "capex").abs().fillna(capex_fill)
    n_fcf = int(P["fcf_years"])
    pos = np.zeros(len(idx), dtype=int)
    for k in range(1, n_fcf + 1):
        f_k = _col(fund, f"cfo_fy{k}") - _col(fund, f"capex_fy{k}").abs().fillna(capex_fill)
        pos += (f_k > 0).to_numpy()
    fcf_ok = ((fcf_ttm > 0) & (pos >= int(P["fcf_min_pos"]))).fillna(False).astype(bool)
    out["fcf_ttm"], out["fcf_pos_years"], out["fcf_ok"] = fcf_ttm, pos, fcf_ok

    # ------------------------------------------------------------------ operating-margin stability (K2b)
    rev = _col(fund, "revenue")
    om_ttm = _safe_div(opinc, rev.where(rev > 0))
    n_om = int(P["margin_years"])
    om_cols = {}
    for k in range(1, 6):
        if k <= n_om:
            rk = _col(fund, f"revenue_fy{k}")
            om_cols[k] = _safe_div(_col(fund, f"opinc_fy{k}"), rk.where(rk > 0))
        else:
            om_cols[k] = pd.Series(np.nan, index=idx)
        out[f"om_fy{k}"] = om_cols[k]
    Y = np.column_stack([om_cols[k].to_numpy() for k in range(n_om, 0, -1)])        # oldest first
    slope, n_valid = row_ols_slope(Y)
    slope_pp = slope * 100.0
    latest_fy = pd.DataFrame({k: om_cols[k] for k in range(1, n_om + 1)}).bfill(axis=1).iloc[:, 0]
    min_years = min(MIN_MARGIN_YEARS, n_om)
    drop = float(P["recent_drop_pp"]) / 100.0
    margin_ok = pd.Series((n_valid >= min_years) & (slope_pp >= float(P["slope_tol_pp"]))       # NaN compares False
                          & (om_ttm >= latest_fy - drop).to_numpy() & (om_ttm > 0).to_numpy(), index=idx)
    out["om_ttm"], out["om_n"], out["om_slope_pp"], out["margin_ok"] = om_ttm, n_valid, slope_pp, margin_ok
    quality_ok = fcf_ok & margin_ok
    out["quality_ok"] = quality_ok

    # ------------------------------------------------------------------ ROIC and WACC (K3)
    pretax, taxx = _col(fund, "pretax"), _col(fund, "tax")
    eff = _safe_div(taxx, pretax.where(pretax > 0))
    t = eff.clip(TAX_LO, TAX_HI).fillna(statutory_tax(date))
    nopat = opinc * (1.0 - t)
    ic_now = debt + _col(fund, "equity_total") - cash_tot
    ic_prev = _col(fund, "total_debt_4q") + _col(fund, "equity_total_4q") - _col(fund, "cash_4q") \
        - _col(fund, "st_investments").fillna(0.0)
    ic_avg = pd.concat([ic_now, ic_prev], axis=1).mean(axis=1, skipna=True)            # falls back to the one known
    capital_light = ((ic_avg <= 0) & (nopat > 0)).fillna(False).astype(bool)
    roic = _safe_div(nopat, ic_avg.where(ic_avg > 0))
    roic = roic.where(~capital_light, np.inf)
    out["tax_rate"], out["nopat"], out["ic_now"], out["ic_avg"] = t, nopat, ic_now, ic_avg
    out["capital_light"], out["roic"] = capital_light, roic

    bet = betas_at(ctx, date, tick.to_numpy(), int(P["beta_weeks"]), int(P["beta_min_weeks"]))
    beta_raw = pd.Series(bet["beta_raw"].to_numpy(), index=idx)
    beta_adj = BLUME_W * beta_raw + (1.0 - BLUME_W)
    rf = _rf(date, P)
    ke = rf + beta_adj * float(P["erp"])
    debt_prev = _col(fund, "total_debt_4q")
    avg_debt = pd.concat([debt, debt_prev], axis=1).mean(axis=1, skipna=True).where(debt.notna())
    intexp = _col(fund, "interest_exp")
    kd_raw = _safe_div(intexp.where(intexp > 0), avg_debt.where(avg_debt > 0))
    kd = kd_raw.clip(lower=rf, upper=KD_CAP)
    fallback = kd_raw.isna() | (debt < KD_MIN_DEBT_SHARE * mcap)
    kd = kd.where(~fallback, rf + KD_SPREAD_FALLBACK)
    V = mcap + debt
    wacc = (mcap / V) * ke + (debt / V) * kd * (1.0 - t)
    wacc = wacc.where((mcap > 0) & debt.notna() & ke.notna())
    pass_roic = (roic > wacc).fillna(False).astype(bool)
    out["beta_raw"], out["beta_n"], out["beta_adj"] = beta_raw, bet["beta_n"].to_numpy(), beta_adj
    out["rf_10y"], out["ke"], out["kd"], out["wacc"], out["pass_roic"] = rf, ke, kd, wacc, pass_roic

    # ------------------------------------------------------------------ recent IPO (R10)
    fp = _first_price_dates(ctx).reindex(tick.to_numpy())
    fp.index = idx
    ff = _aux_first_filing().reindex(idx)
    start = pd.concat([fp, ff], axis=1).min(axis=1)
    age = (date - start).dt.days
    recent_ipo = (age < int(P["ipo_days"])).fillna(False).astype(bool)
    out["first_price_date"], out["first_filing_date"] = fp, ff
    out["listing_age_days"], out["recent_ipo"] = age, recent_ipo

    # ------------------------------------------------------------------ recent merger (R10)
    acq = _col(fund, "acquisitions").abs().fillna(0.0)                                # missing => 0 (low confidence)
    assets_prev = _col(fund, "assets_4q").where(_col(fund, "assets_4q") > 0)
    acq_int = _safe_div(acq, assets_prev)
    filed = pd.to_datetime(fund["filed"]) if "filed" in fund.columns else pd.Series(pd.NaT, index=idx)
    sh_now, sh_prev = _col(fund, "shares_diluted"), _col(fund, "shares_diluted_4q")
    jump = (_split_adjusted_share_ratio(ctx, tick, sh_now.where(sh_now > 0), sh_prev.where(sh_prev > 0), filed)
            - 1.0).abs()                                                              # zero counts are data errors
    assets = _col(fund, "assets")
    asset_jump = _safe_div(assets, assets_prev) - 1.0
    i201 = _aux_item_201()
    lo = date - pd.Timedelta(days=ITEM_201_WINDOW_DAYS)
    fd = i201["filing_date"]
    recent_ciks = set(i201.loc[(fd >= lo) & (fd < date), "cik"].astype("int64"))       # strictly before `date`
    has201 = pd.Series(idx.isin(list(recent_ciks)), index=idx)
    recent_merger = ((acq_int >= float(P["acq_thr"])) | (jump >= float(P["share_thr"]))
                     | ((asset_jump >= float(P["asset_thr"])) & has201)).fillna(False).astype(bool)
    out["acq_intensity"], out["share_jump"], out["asset_jump"] = acq_int, jump, asset_jump
    out["has_item_201"], out["recent_merger"] = has201, recent_merger

    # ------------------------------------------------------------------ verdict
    pass_all = pass_lev & quality_ok & pass_roic
    out["pass_all"] = pass_all
    out["fail_reasons"] = _fail_reasons(
        out, nd_max, P, fcf_ttm=fcf_ttm, slope_pp=slope_pp, latest_fy=latest_fy, drop=drop, min_years=min_years)
    out = out[COLUMNS]
    out.index.name = "cik"
    return out


def _fail_reasons(o: pd.DataFrame, nd_max: float, P: dict, *, fcf_ttm, slope_pp, latest_fy, drop, min_years) -> pd.Series:
    reasons = pd.Series("", index=o.index, dtype=object)

    def add(mask, text):
        nonlocal reasons
        m = pd.Series(np.asarray(mask), index=o.index).fillna(False).astype(bool)
        reasons = reasons.where(~m, reasons + text + ";")

    nd_na = o["nd_ebitda"].isna()
    add(nd_na & (o["ebitda_ttm"] <= 0), "ebitda<=0")
    add(nd_na & ~(o["ebitda_ttm"] <= 0), "nd_n/a")
    add(o["nd_ebitda"] > nd_max, f"nd_ebitda>{nd_max:g}")
    add(fcf_ttm.isna(), "fcf_n/a")
    add(fcf_ttm <= 0, "fcf_ttm<=0")
    add(o["fcf_pos_years"] < int(P["fcf_min_pos"]), f"fcf_pos_years<{int(P['fcf_min_pos'])}")
    add(o["om_n"] < min_years, "margin_history<3y")
    enough = o["om_n"] >= min_years
    add(enough & (slope_pp < float(P["slope_tol_pp"])), "margin_slope")
    add(enough & (o["om_ttm"] < latest_fy - drop), "margin_recent_drop")
    add(o["om_ttm"].isna(), "om_ttm_n/a")
    add(o["om_ttm"] <= 0, "om_ttm<=0")
    add(o["wacc"].isna(), "wacc_n/a")
    add(o["roic"].isna() & ~o["capital_light"], "roic_n/a")
    add(o["wacc"].notna() & o["roic"].notna() & ~(o["roic"] > o["wacc"]), "roic<=wacc")
    return reasons.str.rstrip(";")
