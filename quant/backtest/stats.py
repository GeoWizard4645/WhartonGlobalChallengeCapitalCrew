"""Statistical inference and overfitting diagnostics for backtests (research/06 sections 3-5).

Everything here works on plain numpy arrays; pandas objects are accepted and converted.
Conventions (same as ``metrics.py``):

* ``r`` is a vector of simple periodic returns; Sharpe ratios are *per period* unless the
  argument or function name says ``ann``.
* ``sd`` uses ddof=1 unless stated otherwise.
* NaN rule: single-series statistics drop NaN observations; regressions drop any row that has
  a NaN in ``y`` or in ``X`` (listwise deletion); the CSCV trial matrix drops any row with a NaN.

Contents
--------
HAC / factor regressions : newey_west_lags, ols_hac, factor_regression, align_to_index
Sharpe inference         : sharpe_se_iid, sharpe_t, psr, expected_max_sr, effective_trials, dsr,
                           min_track_record_len, adjust_pvalues, haircut_sharpe_bonferroni
Bootstrap                : stationary_bootstrap_idx, bootstrap_ci, optimal_block
Overfitting              : cscv_pbo, spa_test
Parameter grids          : plateau_select, grid_design, grid_regression_bootstrap, surface_grid
Portfolio                : erc_weights
"""
from __future__ import annotations

import itertools
import logging
from typing import Callable, Sequence

import numpy as np
import pandas as pd
from scipy import stats as sps

log = logging.getLogger(__name__)

EULER_GAMMA = 0.5772156649015329

# Factor sets for the supported regression models (names as in the Ken French files, decimals).
FACTOR_MODELS: dict[str, list[str]] = {
    "capm": ["Mkt-RF"],
    "ff3": ["Mkt-RF", "SMB", "HML"],
    "ff3mom": ["Mkt-RF", "SMB", "HML", "Mom"],
    "ff5": ["Mkt-RF", "SMB", "HML", "RMW", "CMA"],
    "ff5mom": ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"],
}


# ---------------------------------------------------------------------------------------------
# small helpers
# ---------------------------------------------------------------------------------------------
def _a(x) -> np.ndarray:
    """Float ndarray view of anything array-like (Series, DataFrame, list)."""
    return np.asarray(x, dtype=float)


def _clean(x) -> np.ndarray:
    """1-D float array with NaNs removed."""
    a = _a(x).reshape(-1)
    return a[~np.isnan(a)]


def _rng(seed) -> np.random.Generator:
    """Accept a Generator, an int seed or None."""
    return seed if isinstance(seed, np.random.Generator) else np.random.default_rng(seed)


def align_to_index(target: pd.Index, obj: pd.Series | pd.DataFrame):
    """Reindex ``obj`` onto the dates in ``target``; uncovered dates become NaN (callers drop them).

    If both indexes are DatetimeIndex with at most one observation per calendar month (i.e. both
    are monthly), rows are matched by calendar month.  This reconciles "last trading day of the
    month" (strategy returns) with "calendar month-end" or "first of month" stamps (Ken French
    files); an exact-date match would silently lose the months where the two conventions differ.
    In every other case (daily data, integer indexes, ...) the match is on exact labels.
    If ``obj`` has two rows in one month the last wins.
    """
    monthly = (
        isinstance(target, pd.DatetimeIndex) and isinstance(obj.index, pd.DatetimeIndex)
        and target.to_period("M").is_unique and obj.index.to_period("M").is_unique
    )
    if not monthly:
        return obj.reindex(target)
    tmp = obj.copy()
    tmp.index = obj.index.to_period("M")
    out = tmp.reindex(target.to_period("M"))
    out.index = target
    return out


# ---------------------------------------------------------------------------------------------
# HAC regression
# ---------------------------------------------------------------------------------------------
def newey_west_lags(T: int) -> int:
    """Newey-West (1994) plug-in bandwidth: L = floor(4 * (T/100)^(2/9)).

    T = 93 -> 3, T = 108..190 -> 4.
    """
    return int(np.floor(4.0 * (max(T, 1) / 100.0) ** (2.0 / 9.0)))


def ols_hac(y, X, lags: int | None = None, small_sample: bool = True) -> dict:
    """OLS with Newey-West (Bartlett kernel) HAC standard errors.

    Estimator (research/06 section 3.3)::

        b  = (X'X)^-1 X'y,          e = y - Xb
        V  = (X'X)^-1 S (X'X)^-1 * [T/(T-k)]             (factor only if small_sample=True)
        S  = G_0 + sum_{l=1..L} w_l (G_l + G_l'),  w_l = 1 - l/(L+1)
        G_l = sum_{t=l+1..T} e_t e_{t-l} x_t x_{t-l}'

    ``small_sample=True`` reproduces ``statsmodels`` ``cov_type='HAC'`` with ``use_correction=True``
    exactly (same lags); ``small_sample=False`` matches ``use_correction=False``.

    Parameters
    ----------
    y : (T,) array-like.   X : (T,k) or (T,) array-like, include a constant column yourself.
    lags : Bartlett truncation lag L (``None`` -> ``newey_west_lags(T)``; capped at T-1).

    Returns
    -------
    dict(beta, se, t, p, p_t, r2, adj_r2, lags, n, k, resid, cov)
      ``p`` uses the normal distribution (statsmodels ``use_t=False``); ``p_t`` uses Student-t with
      T-k degrees of freedom (``use_t=True``), recommended for the short samples used here.
      ``r2`` is centered when X contains a constant column, uncentered otherwise (as statsmodels).
    Rows with NaN in ``y`` or ``X`` are dropped (listwise).
    """
    y = _a(y).reshape(-1)
    X = _a(X)
    if X.ndim == 1:
        X = X[:, None]
    if X.shape[0] != len(y):
        raise ValueError(f"y has {len(y)} rows but X has {X.shape[0]}")
    ok = ~np.isnan(y) & ~np.isnan(X).any(axis=1)
    y, X = y[ok], X[ok]
    T, k = X.shape
    if T <= k:
        raise ValueError(f"need more observations ({T}) than regressors ({k})")

    # pinv(X) = (X'X)^+ X'  ->  beta, and (X'X)^+ = pinv(X) pinv(X)'  (robust to collinearity)
    pinv = np.linalg.pinv(X)
    b = pinv @ y
    XtX_inv = pinv @ pinv.T
    e = y - X @ b

    L = newey_west_lags(T) if lags is None else int(lags)
    L = max(0, min(L, T - 1))
    Xe = X * e[:, None]                                   # score contributions x_t * e_t
    S = Xe.T @ Xe                                         # G_0
    for l in range(1, L + 1):
        G = Xe[l:].T @ Xe[:-l]
        S += (1.0 - l / (L + 1.0)) * (G + G.T)            # Bartlett weight
    V = XtX_inv @ S @ XtX_inv
    if small_sample:
        V = V * T / (T - k)
    se = np.sqrt(np.diag(V))
    with np.errstate(divide="ignore", invalid="ignore"):
        t = b / se

    has_const = bool(np.any((X.max(axis=0) == X.min(axis=0)) & (X[0] != 0)))
    ssr = float(e @ e)
    tss = float(((y - y.mean()) ** 2).sum()) if has_const else float((y ** 2).sum())
    r2 = 1.0 - ssr / tss if tss > 0 else float("nan")
    adj_r2 = 1.0 - (T - int(has_const)) / (T - k) * (1.0 - r2)
    return dict(beta=b, se=se, t=t, p=2.0 * sps.norm.sf(np.abs(t)), p_t=2.0 * sps.t.sf(np.abs(t), T - k),
                r2=float(r2), adj_r2=float(adj_r2), lags=L, n=T, k=k, resid=e, cov=V)


def factor_regression(excess_r, factors_df: pd.DataFrame, model: str = "ff5mom",
                      lags: int | None = None, ppy: int = 12, small_sample: bool = True) -> dict:
    """Time-series factor regression with HAC errors (research/06 section 3).

        y_t = alpha + sum_j beta_j F_jt + e_t,        y = strategy return - rf

    ``excess_r`` must already be an excess return (strategy minus rf, or minus the benchmark for
    the active-return version).  ``factors_df`` has columns 'Mkt-RF','SMB','HML','RMW','CMA','Mom'
    in decimals.  Models: capm | ff3 | ff3mom | ff5 | ff5mom.

    Alignment: if ``excess_r`` is a Series and ``factors_df`` a DataFrame they are aligned on the
    index (``align_to_index``: by calendar month for monthly data); the regression uses the common
    sample, so a strategy running past the last factor month is truncated.  If ``excess_r`` is an
    ndarray it must have the same length as ``factors_df`` (positional).

    ``lags=None`` -> Newey-West rule; research/06 recommends reporting L = 4 (and 6, 12 as
    robustness), so pass ``lags=4`` explicitly for the headline table.

    Returns dict(model, factors, n, lags, start, end, alpha, alpha_ann, alpha_ann_se, t_alpha,
    p_alpha, p_alpha_t, loadings, se_loadings, t_loadings, r2, adj_r2).
    ``alpha_ann = ppy * alpha`` (arithmetic); ``loadings`` etc. are dicts keyed by factor name.
    """
    key = model.lower().replace("+", "").replace("_", "").replace("-", "")
    if key not in FACTOR_MODELS:
        raise ValueError(f"unknown model {model!r}; choose from {sorted(FACTOR_MODELS)}")
    cols = FACTOR_MODELS[key]
    missing = [c for c in cols if c not in factors_df.columns]
    if missing:
        raise KeyError(f"factors_df is missing columns {missing} (has {list(factors_df.columns)})")

    if isinstance(excess_r, pd.Series):
        Fv = align_to_index(excess_r.index, factors_df[cols]).to_numpy(dtype=float)
        y = excess_r.to_numpy(dtype=float)
        index = excess_r.index
    else:
        y = _a(excess_r).reshape(-1)
        Fv = _a(factors_df[cols])
        index = None
    X = np.column_stack([np.ones(len(y)), Fv])
    o = ols_hac(y, X, lags=lags, small_sample=small_sample)
    ok = ~np.isnan(y) & ~np.isnan(Fv).any(axis=1)
    start = end = None
    if index is not None and ok.any():
        start, end = index[ok][0], index[ok][-1]
    b, se, t = o["beta"], o["se"], o["t"]
    return dict(
        model=key, factors=list(cols), n=o["n"], lags=o["lags"], start=start, end=end,
        alpha=float(b[0]), alpha_ann=float(ppy * b[0]), alpha_ann_se=float(ppy * se[0]),
        t_alpha=float(t[0]), p_alpha=float(o["p"][0]), p_alpha_t=float(o["p_t"][0]),
        loadings=dict(zip(cols, map(float, b[1:]))),
        se_loadings=dict(zip(cols, map(float, se[1:]))),
        t_loadings=dict(zip(cols, map(float, t[1:]))),
        r2=o["r2"], adj_r2=o["adj_r2"],
    )


# ---------------------------------------------------------------------------------------------
# Sharpe-ratio inference (all Sharpe ratios PER PERIOD unless named *_ann)
# ---------------------------------------------------------------------------------------------
def sharpe_se_iid(sr_per: float, T: int) -> float:
    """Lo (2002) iid standard error of a per-period Sharpe ratio: sqrt((1 + SR^2/2) / T)."""
    return float(np.sqrt((1.0 + 0.5 * sr_per ** 2) / T))


def sharpe_t(sr_ann: float, years: float) -> float:
    """t-statistic of the mean excess return: t = SR_ann * sqrt(years) (= SR_per * sqrt(n))."""
    return float(sr_ann * np.sqrt(years))


def psr(sr_hat: float, sr_star: float, T: int, skew: float, kurt_raw: float) -> float:
    """Probabilistic Sharpe Ratio (Bailey & Lopez de Prado 2012).

        PSR(SR*) = Phi( (SR - SR*) sqrt(T-1) / sqrt(1 - g3 SR + (g4-1)/4 SR^2) )

    All Sharpe ratios per period (not annualised); ``kurt_raw`` is raw kurtosis (Normal = 3).
    Returns NaN if the variance term is not positive (extreme skew with large SR).
    """
    var_term = 1.0 - skew * sr_hat + (kurt_raw - 1.0) / 4.0 * sr_hat ** 2
    if not var_term > 0:
        return float("nan")
    return float(sps.norm.cdf((sr_hat - sr_star) * np.sqrt(T - 1.0) / np.sqrt(var_term)))


def expected_max_sr(var_sr: float, N: float) -> float:
    """Expected maximum Sharpe of N independent zero-skill trials (the DSR benchmark SR0).

        SR0 = sqrt(V) * ( (1-gamma) Phi^-1(1 - 1/N) + gamma Phi^-1(1 - 1/(N e)) )

    ``var_sr`` is the cross-sectional variance of the trials' Sharpe estimates, same periodicity as
    the Sharpe being tested.  N <= 1 -> 0.  Non-integer N (e.g. N_eff) is allowed.
    """
    if N <= 1:
        return 0.0
    return float(np.sqrt(var_sr) * ((1.0 - EULER_GAMMA) * sps.norm.ppf(1.0 - 1.0 / N)
                                    + EULER_GAMMA * sps.norm.ppf(1.0 - 1.0 / (N * np.e))))


def effective_trials(M_returns) -> float:
    """Effective number of independent trials, N_hat = rho + (1 - rho) * M.

    ``M_returns`` is a (T x M) matrix of trial return series; rho is the average off-diagonal
    correlation.  Formula is from memory of Bailey & Lopez de Prado Appendix 3 (unverified);
    report DSR at both N = M and N = N_hat.  Deviation from Appendix A: rho is clipped to [0, 1]
    so that N_hat cannot exceed M when the average correlation is negative.  Rows with NaN are
    dropped; M = 1 returns 1.
    """
    A = _a(M_returns)
    A = A[~np.isnan(A).any(axis=1)]
    n = A.shape[1]
    if n <= 1:
        return 1.0
    C = np.corrcoef(A.T)
    rho = float((np.nansum(C) - n) / (n * (n - 1)))
    rho = min(max(rho, 0.0), 1.0)
    return float(rho + (1.0 - rho) * n)


def dsr(r_selected, trial_sharpes_per, N: float | None = None) -> tuple[float, float]:
    """Deflated Sharpe Ratio = PSR evaluated at SR0 = E[max of N null Sharpes].

    ``r_selected``: periodic (excess) returns of the chosen strategy; its per-period Sharpe,
    skewness and raw kurtosis are estimated from them (scipy biased moments).
    ``trial_sharpes_per``: per-period Sharpe ratios of all trials, computed the same way (their
    variance sets the scale of SR0).  ``N`` defaults to ``len(trial_sharpes_per)``; pass
    ``effective_trials(...)`` for the N_hat version.  Returns ``(dsr, sr0_per_period)``.
    """
    r = _clean(r_selected)
    T = len(r)
    sr_hat = float(r.mean() / r.std(ddof=1))
    ts = _clean(trial_sharpes_per)
    n_trials = len(ts) if N is None else N
    var_sr = float(np.var(ts, ddof=1)) if len(ts) > 1 else 0.0
    sr0 = expected_max_sr(var_sr, n_trials)
    return psr(sr_hat, sr0, T, float(sps.skew(r)), float(sps.kurtosis(r, fisher=False))), sr0


def min_track_record_len(sr_hat: float, sr_star: float, skew: float, kurt_raw: float,
                         conf: float = 0.95) -> float:
    """Minimum track-record length (in observations) so that PSR(SR*) >= conf.

        T_min = 1 + (1 - g3 SR + (g4-1)/4 SR^2) * (Phi^-1(conf) / (SR - SR*))^2

    Per-period Sharpe ratios in, number of periods out.  ``inf`` if SR <= SR*.
    """
    if sr_hat <= sr_star:
        return float("inf")
    z = sps.norm.ppf(conf)
    var_term = 1.0 - skew * sr_hat + (kurt_raw - 1.0) / 4.0 * sr_hat ** 2
    return float(1.0 + var_term * (z / (sr_hat - sr_star)) ** 2)


def adjust_pvalues(p, method: str = "holm") -> np.ndarray:
    """Multiple-testing adjusted p-values, returned in the input order.

    bonferroni : min(M p_i, 1)
    holm       : p_adj(k) = max_{j<=k} min((M-j+1) p_(j), 1)        (sorted ascending)
    bh         : p_adj(k) = min_{j>=k} min(M p_(j)/j, 1)            (Benjamini-Hochberg FDR)
    bhy        : BH with M replaced by M * sum_{j<=M} 1/j            (Benjamini-Yekutieli)
    """
    p = _a(p).reshape(-1)
    m = len(p)
    order = np.argsort(p, kind="stable")
    ps = p[order]
    j = np.arange(1, m + 1)
    if method == "bonferroni":
        adj = np.minimum(ps * m, 1.0)
    elif method == "holm":
        adj = np.maximum.accumulate(np.minimum((m - j + 1) * ps, 1.0))
    elif method in ("bh", "bhy"):
        c = 1.0 if method == "bh" else float(np.sum(1.0 / j))
        adj = np.minimum.accumulate((ps * m * c / j)[::-1])[::-1]
        adj = np.minimum(adj, 1.0)
    else:
        raise ValueError(f"unknown method {method!r}")
    out = np.empty(m)
    out[order] = adj
    return out


def haircut_sharpe_bonferroni(sr_ann: float, years: float, n_tests: int) -> tuple[float, float]:
    """Harvey-Liu style Bonferroni haircut of an annualised Sharpe ratio.

        t = SR sqrt(Y);  p = 2 (1 - Phi(t));  p_adj = min(M p, 1);  t_adj = Phi^-1(1 - p_adj/2)
        SR_adj = t_adj / sqrt(Y);  haircut = 1 - SR_adj / SR

    Returns ``(sr_adj, haircut)``.  For SR <= 0 there is nothing to haircut: ``(0.0, nan)``.
    """
    if sr_ann <= 0:
        return 0.0, float("nan")
    t = sr_ann * np.sqrt(years)
    p_adj = min(n_tests * 2.0 * sps.norm.sf(t), 1.0)
    t_adj = sps.norm.isf(p_adj / 2.0)
    sr_adj = t_adj / np.sqrt(years)
    return float(sr_adj), float(1.0 - sr_adj / sr_ann)


# ---------------------------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------------------------
def stationary_bootstrap_idx(n: int, mean_block: float, rng=None) -> np.ndarray:
    """Politis-Romano (1994) stationary-bootstrap indices (circular, geometric block lengths).

        idx[0] ~ U{0..n-1};  idx[t] = U{0..n-1} w.p. p = 1/mean_block, else (idx[t-1]+1) mod n

    Vectorised (no Python loop): every position inherits the start of its block and adds its
    offset within the block.  ``mean_block`` < 1 is treated as 1 (iid bootstrap).  ``rng`` may be a
    ``numpy.random.Generator``, an int seed or None.  Resample *rows* jointly: data[idx].
    """
    if n < 1:
        raise ValueError("n must be >= 1")
    rng = _rng(rng)
    p = 1.0 / max(float(mean_block), 1.0)
    new = rng.random(n) < p
    new[0] = True
    starts = rng.integers(0, n, size=n)
    pos = np.arange(n)
    block_start_pos = np.maximum.accumulate(np.where(new, pos, 0))     # position where block began
    return ((starts[block_start_pos] + (pos - block_start_pos)) % n).astype(np.int64)


def bootstrap_ci(stat_fn: Callable[[np.ndarray], float], data, mean_block: float, B: int = 5000,
                 alpha: float = 0.05, seed=0) -> tuple[np.ndarray, np.ndarray]:
    """Percentile confidence interval of ``stat_fn(data[idx])`` under the stationary bootstrap.

    ``data`` is (n,) or (n, d); rows are resampled jointly (strategy, benchmark, rf, factors...).
    Returns ``(ci, draws)`` with ``ci = [alpha/2, 1-alpha/2]`` quantiles of the B draws (NaN draws
    are ignored).
    """
    data = _a(data)
    rng = _rng(seed)
    n = len(data)
    draws = np.array([stat_fn(data[stationary_bootstrap_idx(n, mean_block, rng)]) for _ in range(B)],
                     dtype=float)
    return np.nanquantile(draws, [alpha / 2.0, 1.0 - alpha / 2.0]), draws


def optimal_block(x) -> float:
    """Mean block length for the stationary bootstrap (Politis-White 2004 / Patton-Politis-White 2009).

    Thin wrapper on ``arch.bootstrap.optimal_block_length`` (its 'stationary' column, called b_sb in
    older arch versions).  For a 2-D input the median across columns is returned.  The result is
    floored at 3 and capped at n (research/06 section 4.6).
    """
    from arch.bootstrap import optimal_block_length

    a = _a(x)
    if a.ndim == 1:
        a = a[~np.isnan(a)]
    else:
        a = a[~np.isnan(a).any(axis=1)]
    res = optimal_block_length(a)
    col = "stationary" if "stationary" in res.columns else "b_sb"
    b = float(np.nanmedian(res[col].to_numpy(dtype=float)))
    if not np.isfinite(b):
        b = 3.0
    return float(min(max(b, 3.0), len(a)))


# ---------------------------------------------------------------------------------------------
# Probability of backtest overfitting (CSCV)
# ---------------------------------------------------------------------------------------------
def cscv_pbo(M, S: int = 16, selector: Callable[[np.ndarray], int] | None = None) -> dict:
    """Probability of Backtest Overfitting by combinatorially symmetric cross-validation
    (Bailey, Borwein, Lopez de Prado & Zhu 2017; research/06 section 4.4).

    ``M`` is (T x N): per-period returns of N trials on the same dates (rows with NaN are dropped).
    Rows are cut into S equal time-ordered blocks (the earliest remainder rows are dropped); for
    each of the C(S, S/2) choices of S/2 training blocks the metric (Sharpe ratio) is computed
    in-sample (IS) and on the complement (OOS)::

        n*       = selector(R_IS)                     (default argmax; pass YOUR selection rule)
        omega    = rank_OOS(n*) / (N + 1)             (rank 1 = worst; average ranks on ties)
        lambda   = ln(omega / (1 - omega))
        PBO      = share of combinations with lambda <= 0

    Note ``<= 0`` follows the paper; with odd N a median-ranked pick has lambda = 0 exactly and
    counts as overfit.  ``selector`` receives the length-N IS Sharpe vector and returns an index.

    Returns dict(pbo, logits, sr_is, sr_oos, prob_loss, degradation_slope, n_combos, selected):
    ``sr_is``/``sr_oos`` are the per-period Sharpe of the selected trial in each combination,
    ``prob_loss = P(sr_oos < 0)``, ``degradation_slope`` = OLS slope of sr_oos on sr_is (negative
    means overfit), ``selected`` = chosen column in each combination.
    """
    A = _a(M)
    if A.ndim != 2:
        raise ValueError("M must be 2-D (T x N)")
    keep = ~np.isnan(A).any(axis=1)
    if not keep.all():
        log.warning("cscv_pbo: dropping %d rows containing NaN", int((~keep).sum()))
        A = A[keep]
    T, N = A.shape
    if S < 2 or S % 2:
        raise ValueError("S must be an even integer >= 2")
    n_per = T // S
    if n_per < 2:
        raise ValueError(f"need at least 2 rows per block: T={T}, S={S}")
    A = A[T - n_per * S:]                                  # drop the earliest remainder rows
    blocks = A.reshape(S, n_per, N)
    sums = blocks.sum(axis=1)                               # (S, N)
    sqs = (blocks ** 2).sum(axis=1)

    combos = np.array(list(itertools.combinations(range(S), S // 2)))      # (C, S/2)
    C = len(combos)
    ind = np.zeros((C, S))
    ind[np.arange(C)[:, None], combos] = 1.0                # indicator of training blocks
    n_obs = n_per * (S // 2)                                # same size for IS and OOS

    def sharpe_from(s1, s2):
        mu = s1 / n_obs
        var = (s2 - n_obs * mu ** 2) / (n_obs - 1)
        with np.errstate(divide="ignore", invalid="ignore"):
            sr = mu / np.sqrt(var)
        return np.where(np.isfinite(sr), sr, -np.inf)       # undefined Sharpe never wins

    tot1, tot2 = sums.sum(axis=0), sqs.sum(axis=0)
    is1, is2 = ind @ sums, ind @ sqs                         # (C, N) sums over training blocks
    R_is = sharpe_from(is1, is2)
    R_oos = sharpe_from(tot1 - is1, tot2 - is2)

    if selector is None:
        sel = np.argmax(R_is, axis=1)
    else:
        sel = np.array([int(selector(R_is[c])) for c in range(C)])
    rows = np.arange(C)
    ranks = sps.rankdata(R_oos, axis=1)                      # 1 = worst OOS
    w = ranks[rows, sel] / (N + 1.0)
    logits = np.log(w / (1.0 - w))
    sr_is, sr_oos = R_is[rows, sel], R_oos[rows, sel]
    ok = np.isfinite(sr_is) & np.isfinite(sr_oos)
    slope = float(np.polyfit(sr_is[ok], sr_oos[ok], 1)[0]) if ok.sum() > 2 and sr_is[ok].std() > 0 \
        else float("nan")
    return dict(pbo=float(np.mean(logits <= 0)), logits=logits, sr_is=sr_is, sr_oos=sr_oos,
                prob_loss=float(np.mean(sr_oos < 0)), degradation_slope=slope, n_combos=int(C),
                selected=sel)


def spa_test(bench_losses, model_losses, block_size: int | None = None, reps: int = 1000,
             seed: int | None = 0) -> dict:
    """Hansen (2005) Superior Predictive Ability test (wrapper on ``arch.bootstrap.SPA``).

    Inputs are LOSSES (lower is better): use ``-returns``.  H0: no model has lower expected loss
    than the benchmark.  ``bench_losses`` is (T,), ``model_losses`` is (T,) or (T,K); rows with a NaN
    are dropped.  ``block_size=None`` -> ``optimal_block`` of the mean loss differential.
    Stationary bootstrap, studentised.

    Returns dict(p_lower, p_consistent, p_upper, best_model, n_models, n_obs, block_size);
    report ``p_consistent``.  ``best_model`` is the column with the lowest mean loss.
    """
    from arch.bootstrap import SPA

    b = _a(bench_losses).reshape(-1)
    m = _a(model_losses)
    if m.ndim == 1:
        m = m[:, None]
    if m.shape[0] != len(b):
        raise ValueError("bench_losses and model_losses must have the same number of rows")
    keep = ~np.isnan(b) & ~np.isnan(m).any(axis=1)
    b, m = b[keep], m[keep]
    if block_size is None:
        block_size = int(round(optimal_block(b - m.mean(axis=1))))
    spa = SPA(b, m, block_size=int(block_size), reps=int(reps), bootstrap="stationary", studentize=True,
              seed=seed)
    spa.compute()
    pv = spa.pvalues
    return dict(p_lower=float(pv["lower"]), p_consistent=float(pv["consistent"]), p_upper=float(pv["upper"]),
                best_model=int(np.argmin(m.mean(axis=0))), n_models=int(m.shape[1]), n_obs=int(len(b)),
                block_size=int(block_size))


# ---------------------------------------------------------------------------------------------
# Plateau selection on an ordinal parameter grid
# ---------------------------------------------------------------------------------------------
def plateau_select(f, lam: float = 1.0, min_nbrs: int = 2, require_pos: bool = True,
                   floor: float | None = None, peak_ratio_max: float | None = 1.25,
                   default_index: Sequence[int] | None = None, tie_tol: float = 0.02):
    """Plateau rule of research/06 section 5.4 on a k-dimensional array ``f`` of metric values.

    ``f`` is indexed by ordinal grid coordinates (one axis per parameter, equally spaced, NaN =
    infeasible).  Run it separately per level of any categorical parameter.

    Neighbourhood (von Neumann): N[theta] = {theta} + the existing, non-NaN cells one step away along
    each axis (up to 2k+1 cells).  A cell is eligible iff
      (a) it has at least ``min_nbrs`` neighbours (not isolated);
      (b) min over N[theta] of f > threshold, where threshold = max(``floor`` if given, 0 if
          ``require_pos``) (no condition when both are off);
      (c) peak ratio f(theta) / mean_{phi != theta in N} f(phi) <= ``peak_ratio_max`` (else "spike").
          If the neighbours' mean is <= 0 the ratio is undefined (NaN) and the cell is a spike iff it
          exceeds that mean.  ``peak_ratio_max=None`` disables (c).
    Score(theta) = mean_N f - lam * sd_N f   (ddof = 0);   theta* = argmax Score over eligible cells.
    Tie-break: with ``default_index`` given, all eligible cells with Score >= best - ``tie_tol``
    compete and the one closest to the default in grid steps (L1 distance) wins (then more
    neighbours, then higher score).  Without it, exact ties go to the cell with more neighbours.
    If no cell is eligible the index is None -> the caller must fall back to the literature default
    ("when in doubt, don't optimise").

    Returns ``(index, score, peak_ratio, diag)``: the chosen cell (tuple of ints or None), its score
    and peak ratio (scalars, NaN if None) and a dict with the full-grid arrays ``score``, ``peak_ratio``,
    ``n_nbrs``, ``status`` ('ok' | 'nan' | 'isolated' | 'below_floor' | 'spike'), ``eligible``
    (bool), plus ``tied`` (cells within ``tie_tol`` of the best), ``threshold`` and ``reason``.
    """
    f = _a(f)
    if f.ndim == 0:
        raise ValueError("f must have at least one axis")
    score = np.full(f.shape, np.nan)
    peak = np.full(f.shape, np.nan)
    nnb = np.zeros(f.shape, dtype=int)
    status = np.full(f.shape, "nan", dtype="<U12")
    thr = -np.inf
    if floor is not None:
        thr = float(floor)
    if require_pos:
        thr = max(thr, 0.0)

    for ix in np.ndindex(f.shape):
        v = f[ix]
        if np.isnan(v):
            continue
        nbrs = []
        for ax in range(f.ndim):
            for d in (-1, 1):
                j = list(ix)
                j[ax] += d
                if 0 <= j[ax] < f.shape[ax] and not np.isnan(f[tuple(j)]):
                    nbrs.append(f[tuple(j)])
        nnb[ix] = len(nbrs)
        vals = np.array([v] + nbrs)
        score[ix] = vals.mean() - lam * vals.std(ddof=0)
        nb_mean = float(np.mean(nbrs)) if nbrs else np.nan
        if nb_mean > 0:
            peak[ix] = v / nb_mean
        if len(nbrs) < min_nbrs:
            status[ix] = "isolated"
        elif vals.min() <= thr:
            status[ix] = "below_floor"
        elif peak_ratio_max is not None and (
            (nb_mean > 0 and v / nb_mean > peak_ratio_max) or (nb_mean <= 0 and v > nb_mean)
        ):
            status[ix] = "spike"
        else:
            status[ix] = "ok"

    eligible = status == "ok"
    diag = dict(score=score, peak_ratio=peak, n_nbrs=nnb, status=status, eligible=eligible,
                threshold=thr, tied=[], reason="")
    if not eligible.any():
        diag["reason"] = "no eligible cell"
        return None, float("nan"), float("nan"), diag

    sc = np.where(eligible, score, -np.inf)
    best = float(sc.max())
    tol = tie_tol if default_index is not None else 1e-12
    tied = [ix for ix in np.ndindex(f.shape) if eligible[ix] and score[ix] >= best - tol]
    diag["tied"] = tied

    def rank_key(ix):
        dist = (sum(abs(a - b) for a, b in zip(ix, default_index)) if default_index is not None else 0)
        return (dist, -nnb[ix], -round(float(score[ix]), 12), ix)     # rounding: ties must not hinge on fp noise

    choice = min(tied, key=rank_key)
    return tuple(int(i) for i in choice), float(score[choice]), float(peak[choice]), diag


# ---------------------------------------------------------------------------------------------
# Grid regression and surface
# ---------------------------------------------------------------------------------------------
def _grid_design(levels, cont: Sequence[str], cat: Sequence[str] = ()):
    """Design matrix plus, for every column, the set of parameters it involves."""
    first = (list(cont) + list(cat))[0]
    n = len(np.asarray(levels[first]))
    cols, names, owners = [np.ones(n)], ["const"], [frozenset()]
    Z, n_lev = {}, {}
    for c in cont:
        v = _a(levels[c])
        lo, hi = v.min(), v.max()
        Z[c] = (2.0 * (v - lo) / (hi - lo) - 1.0) if hi > lo else np.zeros_like(v)
        n_lev[c] = len(np.unique(v))
        cols.append(Z[c]); names.append(c); owners.append(frozenset([c]))
    for c in cont:
        if n_lev[c] >= 3:        # with 2 levels z^2 == 1 is collinear with the constant
            cols.append(Z[c] ** 2); names.append(c + "^2"); owners.append(frozenset([c]))
    for i, a in enumerate(cont):
        for b in cont[i + 1:]:
            cols.append(Z[a] * Z[b]); names.append(a + "*" + b); owners.append(frozenset([a, b]))
    for c in cat:
        v = np.asarray(levels[c])
        try:
            u = sorted(set(v.tolist()))
        except TypeError:
            u = list(pd.unique(v))
        for lev in u[1:]:        # first level is the baseline
            cols.append((v == lev).astype(float)); names.append(f"{c}={lev}"); owners.append(frozenset([c]))
    return np.column_stack(cols), names, owners


def grid_design(levels, cont: Sequence[str], cat: Sequence[str] = ()) -> tuple[np.ndarray, list[str]]:
    """Design matrix for the grid regression of research/06 section 5.5.

        y(g) = b0 + sum_j b_j z_j + sum_j c_j z_j^2 + sum_{j<l} d_jl z_j z_l + sum_c kappa_c D_c

    ``levels``: dict (or DataFrame) name -> one value per grid cell.  ``cont`` names are scaled to
    [-1, 1] over their range; ``cat`` names become dummies (first sorted level dropped).  Returns
    ``(X, names)`` with a leading constant.  Deviation from Appendix A: the z^2 term is skipped for
    an axis with fewer than 3 distinct levels (it would be collinear with the constant).
    """
    X, names, _ = _grid_design(levels, cont, cat)
    return X, names


def grid_regression_bootstrap(Mret, levels, cont: Sequence[str], cat: Sequence[str] = (), B: int = 500,
                              mean_block: float = 6, seed: int = 0, ppy: int = 12) -> dict:
    """Regress each grid cell's annualised Sharpe on the grid parameters; bootstrap the months.

    ``Mret`` is (T x n_cells) periodic returns, one column per grid cell (same order as ``levels``).
    The response is the annualised Sharpe of each cell.  One stationary-bootstrap index vector per
    replicate is applied to *all* cells, so cross-cell dependence is preserved (the cells share
    months and stocks; ordinary OLS p-values are meaningless).  Rows of ``Mret`` with NaN are dropped
    and cells with undefined Sharpe are excluded from each fit.

    Returns dict(names, coef, boot_sd, r2, partial_r2, y, draws): ``partial_r2[param]`` is the share of
    the residual variance removed by the param's terms (drop-one), ``draws`` is (B, p).
    """
    M = _a(Mret)
    M = M[~np.isnan(M).any(axis=1)]
    T, n_cells = M.shape
    X, names, owners = _grid_design(levels, cont, cat)
    if X.shape[0] != n_cells:
        raise ValueError(f"levels describe {X.shape[0]} cells but Mret has {n_cells} columns")

    def cell_sr(A):
        with np.errstate(divide="ignore", invalid="ignore"):
            return A.mean(axis=0) / A.std(axis=0, ddof=1) * np.sqrt(ppy)

    def fit(y, cols=None):
        ok = np.isfinite(y)
        Xc = X if cols is None else X[:, cols]
        coef = np.linalg.lstsq(Xc[ok], y[ok], rcond=None)[0]
        ssr = float(((y[ok] - Xc[ok] @ coef) ** 2).sum())
        return coef, ssr, ok

    y0 = cell_sr(M)
    coef, ssr, ok = fit(y0)
    tss = float(((y0[ok] - y0[ok].mean()) ** 2).sum())
    r2 = 1.0 - ssr / tss if tss > 0 else float("nan")

    partial = {}
    for prm in list(cont) + list(cat):
        keep = [i for i, o in enumerate(owners) if prm not in o]
        _, ssr_red, _ = fit(y0, keep)
        partial[prm] = (ssr_red - ssr) / ssr_red if ssr_red > 0 else float("nan")

    rng = _rng(seed)
    draws = np.empty((B, X.shape[1]))
    pinv = np.linalg.pinv(X) if np.isfinite(y0).all() else None
    for i in range(B):
        yb = cell_sr(M[stationary_bootstrap_idx(T, mean_block, rng)])
        draws[i] = pinv @ yb if (pinv is not None and np.isfinite(yb).all()) else fit(yb)[0]
    return dict(names=names, coef=coef, boot_sd=draws.std(axis=0), r2=float(r2), partial_r2=partial,
                y=y0, draws=draws)


def surface_grid(x, y, z, n: int = 50, smoothing: float = 0.5, kernel: str = "thin_plate_spline"):
    """Smooth surface z(x, y) for visualisation only (research/06 section 5.6).

    Scipy ``RBFInterpolator`` on axes rescaled to [0, 1] (isotropic kernel); ``smoothing > 0``
    stops it interpolating noise exactly (0 = exact interpolation).  Grid cells outside the convex
    hull of the data are NaN (no extrapolation).  Returns ``(gx, gy, gz)``, each (n, n), in the
    original units of x and y.  Non-finite z points are ignored.
    """
    from scipy.interpolate import RBFInterpolator
    from scipy.spatial import Delaunay, QhullError

    x, y, z = _a(x).reshape(-1), _a(y).reshape(-1), _a(z).reshape(-1)
    ok = np.isfinite(x) & np.isfinite(y) & np.isfinite(z)
    x, y, z = x[ok], y[ok], z[ok]
    if len(z) < 3:
        raise ValueError("need at least 3 finite points")
    rx, ry = np.ptp(x), np.ptp(y)
    if rx == 0 or ry == 0:
        raise ValueError("x and y must each vary")
    u = np.c_[(x - x.min()) / rx, (y - y.min()) / ry]
    gx, gy = np.meshgrid(np.linspace(0.0, 1.0, n), np.linspace(0.0, 1.0, n))
    P = np.c_[gx.ravel(), gy.ravel()]
    zz = RBFInterpolator(u, z, kernel=kernel, smoothing=smoothing)(P)
    try:
        inside = Delaunay(u).find_simplex(P) >= 0
    except QhullError as exc:                                  # collinear points
        raise ValueError("points are degenerate (collinear); cannot form a convex hull") from exc
    zz[~inside] = np.nan
    return x.min() + gx * rx, y.min() + gy * ry, zz.reshape(n, n)


# ---------------------------------------------------------------------------------------------
# Portfolio helper
# ---------------------------------------------------------------------------------------------
def erc_weights(cov, tol: float = 1e-12, max_iter: int = 200) -> np.ndarray:
    """Equal-risk-contribution (risk parity) weights (Maillard-Roncalli-Teiletche 2010).

    Solves the strictly convex log-barrier problem  min_w 0.5 w'Sw - b sum_i ln w_i  (b = 1/n) by
    damped Newton iteration; its first-order condition is w_i (Sw)_i = b for every i, i.e. equal
    risk contributions.  The solution is rescaled to sum to one.  ``cov`` only needs to be positive
    semi-definite (the barrier makes the Hessian positive definite) and is internally normalised so
    that tolerances do not depend on its units.
    """
    S = _a(cov)
    n = S.shape[0]
    if S.shape != (n, n):
        raise ValueError("cov must be square")
    if n == 1:
        return np.ones(1)
    S = S / np.mean(np.diag(S))                              # weights are scale invariant
    b = 1.0 / n
    w = 1.0 / np.sqrt(np.diag(S))
    w = w / np.sqrt(w @ S @ w)                               # start at the barrier solution's scale

    def F(v):
        return 0.5 * v @ S @ v - b * np.log(v).sum()

    for _ in range(max_iter):
        g = S @ w - b / w
        if np.max(np.abs(g)) < tol:
            break
        d = np.linalg.solve(S + np.diag(b / w ** 2), g)      # Newton direction
        t, f0 = 1.0, F(w)
        while t > 1e-14:                                     # backtracking: stay positive, decrease F
            wn = w - t * d
            if np.all(wn > 0) and F(wn) <= f0 - 1e-4 * t * (g @ d):
                break
            t *= 0.5
        w = wn if t > 1e-14 else w
        if t <= 1e-14:
            break
    return w / w.sum()
