"""Tests for quant/backtest/stats.py (research/06 sections 3-5)."""
import itertools

import numpy as np
import pandas as pd
import pytest
import statsmodels.api as sm
from scipy import stats as sps
from statsmodels.stats.multitest import multipletests

from quant.backtest import stats as st


# ---------------------------------------------------------------------------------------------
# HAC regression
# ---------------------------------------------------------------------------------------------
def _ar_data(T=150, k=3, phi=0.5, seed=0):
    """Regression data with AR(1), heteroskedastic errors."""
    rng = np.random.default_rng(seed)
    X = np.column_stack([np.ones(T), rng.normal(size=(T, k))])
    eps = np.zeros(T)
    shocks = rng.normal(size=T) * (0.5 + np.abs(X[:, 1]))
    for t in range(1, T):
        eps[t] = phi * eps[t - 1] + shocks[t]
    y = X @ np.array([0.3, 1.0, -0.5, 0.2][: k + 1]) + eps
    return y, X


def test_newey_west_lags():
    assert st.newey_west_lags(93) == 3          # research/06 section 3.3
    assert st.newey_west_lags(108) == 4
    assert st.newey_west_lags(190) == 4
    assert st.newey_west_lags(1000) == 6          # floor(4 * 10^(2/9)) = floor(6.67)


@pytest.mark.parametrize("lags", [0, 1, 4, 12])
@pytest.mark.parametrize("small_sample", [True, False])
def test_ols_hac_matches_statsmodels(lags, small_sample):
    """Same lag + same small-sample convention => identical coefficients, SEs, t and p."""
    y, X = _ar_data()
    o = st.ols_hac(y, X, lags=lags, small_sample=small_sample)
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": lags, "use_correction": small_sample})
    np.testing.assert_allclose(o["beta"], res.params, rtol=1e-10, atol=1e-12)
    np.testing.assert_allclose(o["se"], res.bse, rtol=1e-8)
    np.testing.assert_allclose(o["t"], res.tvalues, rtol=1e-8)
    np.testing.assert_allclose(o["p"], res.pvalues, rtol=1e-6, atol=1e-12)     # use_t=False -> normal
    assert o["lags"] == lags and o["n"] == len(y)
    np.testing.assert_allclose(o["r2"], res.rsquared, rtol=1e-10)
    np.testing.assert_allclose(o["adj_r2"], res.rsquared_adj, rtol=1e-10)


def test_ols_hac_t_pvalues_match_statsmodels_use_t():
    y, X = _ar_data(T=100)
    o = st.ols_hac(y, X, lags=4)
    res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 4, "use_correction": True}, use_t=True)
    np.testing.assert_allclose(o["p_t"], res.pvalues, rtol=1e-6, atol=1e-12)


def test_ols_hac_lags0_is_hc1_and_default_lags():
    y, X = _ar_data()
    o = st.ols_hac(y, X, lags=0)
    hc1 = sm.OLS(y, X).fit(cov_type="HC1")
    np.testing.assert_allclose(o["se"], hc1.bse, rtol=1e-8)
    assert st.ols_hac(y, X)["lags"] == st.newey_west_lags(len(y))


def test_ols_hac_brute_force_double_loop():
    """Independent O(T^2 L) implementation of the Newey-West sandwich."""
    y, X = _ar_data(T=60, k=2, seed=3)
    T, k = X.shape
    b = np.linalg.solve(X.T @ X, X.T @ y)
    e = y - X @ b
    L = 3
    S = np.zeros((k, k))
    for t in range(T):
        S += e[t] ** 2 * np.outer(X[t], X[t])
    for l in range(1, L + 1):
        w = 1 - l / (L + 1)
        for t in range(l, T):
            g = e[t] * e[t - l] * np.outer(X[t], X[t - l])
            S += w * (g + g.T)
    A = np.linalg.inv(X.T @ X)
    V = A @ S @ A * T / (T - k)
    np.testing.assert_allclose(st.ols_hac(y, X, lags=L)["se"], np.sqrt(np.diag(V)), rtol=1e-10)


def test_ols_hac_edge_cases():
    y, X = _ar_data(T=40)
    y2, X2 = y.copy(), X.copy()
    y2[5] = np.nan
    X2[10, 1] = np.nan
    o = st.ols_hac(y2, X2, lags=2)
    assert o["n"] == 38                                          # listwise deletion
    keep = np.ones(40, bool)
    keep[[5, 10]] = False
    np.testing.assert_allclose(o["beta"], st.ols_hac(y[keep], X[keep], lags=2)["beta"])
    assert st.ols_hac(y, X, lags=1000)["lags"] == 39              # lags capped at T-1
    assert st.ols_hac(y, X[:, 1])["k"] == 1                       # 1-D X
    with pytest.raises(ValueError):
        st.ols_hac(y[:3], X[:3])


# ---------------------------------------------------------------------------------------------
# factor regression
# ---------------------------------------------------------------------------------------------
def _sim_factors(T=600, seed=1, calendar_stamps=True):
    rng = np.random.default_rng(seed)
    cols = ["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom"]
    cov = 0.03 ** 2 * (0.3 * np.ones((6, 6)) + 0.7 * np.eye(6))
    F = rng.multivariate_normal(np.r_[0.005, 0.002, 0.002, 0.003, 0.002, 0.004], cov, size=T)
    idx = pd.date_range("1970-01-31", periods=T, freq="ME")
    return pd.DataFrame(F, index=idx, columns=cols)


def test_factor_regression_recovers_alpha_and_betas():
    F = _sim_factors()
    alpha, betas = 0.003, np.array([1.1, 0.4, -0.3, 0.5, 0.2, 0.25])

    def simulate(seed):
        noise = np.random.default_rng(seed).normal(0, 0.01, len(F))
        return pd.Series(alpha + F.to_numpy() @ betas + noise, index=F.index)

    # structure of the output on one draw
    out = st.factor_regression(simulate(0), F, model="ff5mom", lags=4)
    assert out["model"] == "ff5mom" and out["n"] == len(F) and out["lags"] == 4
    se_a = out["alpha_ann_se"] / 12
    assert out["alpha_ann"] == pytest.approx(12 * out["alpha"])
    assert out["t_alpha"] == pytest.approx(out["alpha"] / se_a)
    for name in F.columns:
        assert out["t_loadings"][name] == pytest.approx(out["loadings"][name] / out["se_loadings"][name])
    assert 0.5 < out["r2"] < 1 and out["adj_r2"] < out["r2"]
    assert out["start"] == F.index[0] and out["end"] == F.index[-1]

    # recovery: estimates are within ~2 HAC standard errors of the truth in ~95% of simulations
    hits_alpha = hits_beta = 0
    n_sim = 30
    for seed in range(n_sim):
        o = st.factor_regression(simulate(100 + seed), F, model="ff5mom", lags=4)
        hits_alpha += abs(o["alpha"] - alpha) < 2 * o["alpha_ann_se"] / 12
        hits_beta += abs(o["loadings"]["Mkt-RF"] - 1.1) < 2 * o["se_loadings"]["Mkt-RF"]
        assert all(abs(o["loadings"][n] - b) < 0.1 for n, b in zip(F.columns, betas))
    assert hits_alpha >= 25 and hits_beta >= 25


def test_factor_regression_models_use_right_columns_and_match_manual_ols():
    F = _sim_factors(T=300)
    rng = np.random.default_rng(2)
    y = pd.Series(0.001 + 0.9 * F["Mkt-RF"] + 0.3 * F["HML"] + rng.normal(0, 0.01, len(F)), index=F.index)
    expect = {"capm": 1, "ff3": 3, "ff3mom": 4, "ff5": 5, "ff5mom": 6}
    for model, nf in expect.items():
        out = st.factor_regression(y, F, model=model, lags=3)
        assert len(out["loadings"]) == nf
        X = sm.add_constant(F[out["factors"]].to_numpy())
        ref = sm.OLS(y.to_numpy(), X).fit(cov_type="HAC", cov_kwds={"maxlags": 3, "use_correction": True})
        np.testing.assert_allclose(out["alpha"], ref.params[0], rtol=1e-9)
        np.testing.assert_allclose(out["t_alpha"], ref.tvalues[0], rtol=1e-7)
        np.testing.assert_allclose(list(out["t_loadings"].values()), ref.tvalues[1:], rtol=1e-7)
    assert st.factor_regression(y, F, model="FF5+MOM", lags=3)["model"] == "ff5mom"     # spelling tolerant
    with pytest.raises(ValueError):
        st.factor_regression(y, F, model="nope")
    with pytest.raises(KeyError):
        st.factor_regression(y, F.drop(columns="Mom"), model="ff5mom")


def test_factor_regression_alignment_and_truncation():
    """Trading month-end stamps vs calendar month-end stamps, strategy longer than the factors."""
    F = _sim_factors(T=240)
    rng = np.random.default_rng(5)
    y_cal = pd.Series(0.002 + 1.0 * F["Mkt-RF"] + rng.normal(0, 0.01, len(F)), index=F.index)
    # strategy stamped on the last *business* day of each month, plus 6 extra months with no factors
    bd = [d - pd.offsets.BDay(0) if d.weekday() < 5 else d - pd.offsets.BDay(1) for d in y_cal.index]
    extra = pd.date_range(F.index[-1] + pd.offsets.MonthEnd(1), periods=6, freq="ME")
    y = pd.concat([pd.Series(y_cal.to_numpy(), index=pd.DatetimeIndex(bd)),
                   pd.Series(0.01, index=extra)])
    ref = st.factor_regression(y_cal, F, model="capm", lags=4)
    out = st.factor_regression(y, F, model="capm", lags=4)
    assert out["n"] == len(F) == ref["n"]
    np.testing.assert_allclose(out["alpha"], ref["alpha"])
    np.testing.assert_allclose(out["t_alpha"], ref["t_alpha"])

    # plain ndarray input: positional
    arr = st.factor_regression(y_cal.to_numpy(), F, model="capm", lags=4)
    np.testing.assert_allclose(arr["alpha"], ref["alpha"])


# ---------------------------------------------------------------------------------------------
# Sharpe inference, PSR, DSR
# ---------------------------------------------------------------------------------------------
def test_sharpe_se_and_t():
    assert st.sharpe_se_iid(0.0, 100) == pytest.approx(0.1)
    assert st.sharpe_se_iid(1.0, 6) == pytest.approx(np.sqrt(1.5 / 6))
    assert st.sharpe_t(0.5, 15.75) == pytest.approx(0.5 * np.sqrt(15.75))
    assert st.sharpe_t(0.76, 15.75) == pytest.approx(3.0, abs=0.02)         # research/06 section 4.1


def test_psr_basics():
    assert st.psr(0.1, 0.1, 100, 0.0, 3.0) == pytest.approx(0.5)
    hi = st.psr(0.2, 0.0, 120, 0.0, 3.0)
    assert hi == pytest.approx(sps.norm.cdf(0.2 * np.sqrt(119) / np.sqrt(1 + 0.02)))
    # negative skew and fat tails reduce the probability
    assert st.psr(0.2, 0.0, 120, -1.0, 6.0) < hi
    assert np.isnan(st.psr(5.0, 0.0, 100, 5.0, 3.0))                         # 1 - 25 + 12.5 < 0: undefined


def test_expected_max_sr_table_4A():
    assert st.expected_max_sr(1.0, 1) == 0.0
    sr = lambda N, Y: st.expected_max_sr(1.0 / Y, N)                          # annualised, V[SR_ann] = 1/Y
    assert sr(54, 7.75) == pytest.approx(0.83, abs=0.006)
    assert sr(216, 7.75) == pytest.approx(1.00, abs=0.006)
    assert sr(3, 15.75) == pytest.approx(0.21, abs=0.006)
    assert sr(216, 15.75) == pytest.approx(0.70, abs=0.006)
    ns = [2, 5, 10, 50, 200]
    vals = [st.expected_max_sr(0.01, n) for n in ns]
    assert vals == sorted(vals)                                               # increasing in N
    assert st.expected_max_sr(0.01, 100) == pytest.approx(0.1 * st.expected_max_sr(1.0, 100))


def test_dsr_paper_worked_example():
    """Bailey & Lopez de Prado (2014): SR_ann 2.5, T = 1250 daily obs, V[SR_ann] = 0.5, skew -3,
    kurtosis 10.  N = 100 -> DSR 0.90; N = 46 -> 0.95 (threshold); Normal returns hit 0.95 at N = 88."""
    sr_per = 2.5 / np.sqrt(250)
    var_per = 0.5 / 250

    def dsr_paper(N, skew=-3.0, kurt=10.0):
        return st.psr(sr_per, st.expected_max_sr(var_per, N), 1250, skew, kurt)

    assert dsr_paper(100) == pytest.approx(0.9004, abs=5e-4)
    assert round(dsr_paper(100), 2) == 0.90
    assert dsr_paper(46) == pytest.approx(0.9505, abs=5e-4)
    assert dsr_paper(100) < dsr_paper(46)
    # Normal returns: 0.95 is first reached at N = 88
    assert dsr_paper(88, 0.0, 3.0) == pytest.approx(0.9505, abs=5e-4)
    assert dsr_paper(88, 0.0, 3.0) >= 0.95 > dsr_paper(89, 0.0, 3.0)


def test_dsr_function_end_to_end():
    rng = np.random.default_rng(11)
    T, N = 120, 54
    M = rng.normal(0.0, 0.04, (T, N))
    sr_trials = M.mean(0) / M.std(0, ddof=1)
    best = int(np.argmax(sr_trials))
    d, sr0 = st.dsr(M[:, best], sr_trials)                                   # pure noise: best of 54
    assert 0.0 < sr0 < 0.3 and d < 0.9
    # N = 1 means no deflation: sr0 = 0 and DSR == PSR(0)
    d1, sr01 = st.dsr(M[:, best], sr_trials, N=1)
    assert sr01 == 0.0
    r = M[:, best]
    assert d1 == pytest.approx(st.psr(r.mean() / r.std(ddof=1), 0.0, T, sps.skew(r), sps.kurtosis(r, fisher=False)))
    assert d1 > d                                                             # deflation lowers DSR
    # a genuinely strong strategy survives the deflation
    strong = rng.normal(0.03, 0.04, T)
    sr_all = np.r_[sr_trials, strong.mean() / strong.std(ddof=1)]
    assert st.dsr(strong, sr_all)[0] > 0.95
    # NaN in the selected series is ignored
    r_nan = np.r_[r, np.nan]
    assert st.dsr(r_nan, sr_trials)[0] == pytest.approx(d)


def test_effective_trials():
    rng = np.random.default_rng(0)
    base = rng.normal(size=(400, 1))
    assert st.effective_trials(np.repeat(base, 8, axis=1)) == pytest.approx(1.0)
    ind = rng.normal(size=(5000, 10))
    assert st.effective_trials(ind) == pytest.approx(10.0, abs=0.2)
    common = rng.normal(size=(5000, 1))
    mixed = 0.8 * common + 0.6 * rng.normal(size=(5000, 6))                   # average correlation ~ 0.64
    rho = (np.corrcoef(mixed.T).sum() - 6) / 30
    assert st.effective_trials(mixed) == pytest.approx(rho + (1 - rho) * 6)
    neg = np.column_stack([base[:, 0], -base[:, 0]])                          # rho = -1 clipped to 0 -> N_hat = M
    assert st.effective_trials(neg) == pytest.approx(2.0)
    assert st.effective_trials(base) == 1.0


def test_min_track_record_len():
    """research/06 section 4.3: Normal, SR* = 0, 95%: SR 0.3 -> 30 y, 0.5 -> 11.0 y, 0.8 -> 4.4 y, 1.0 -> 2.9 y."""
    for sr_ann, years in [(0.3, 30.3), (0.5, 11.0), (0.8, 4.4), (1.0, 2.9)]:
        t_months = st.min_track_record_len(sr_ann / np.sqrt(12), 0.0, 0.0, 3.0)
        assert t_months / 12 == pytest.approx(years, abs=0.1)
    assert np.isinf(st.min_track_record_len(0.1, 0.2, 0, 3))
    # at T_min the PSR equals the confidence level
    sr, g3, g4 = 0.12, -0.5, 5.0
    T = st.min_track_record_len(sr, 0.0, g3, g4, conf=0.9)
    assert st.psr(sr, 0.0, T, g3, g4) == pytest.approx(0.9)


def test_adjust_pvalues_hand_and_statsmodels():
    p = [0.001, 0.01, 0.02, 0.2]
    np.testing.assert_allclose(st.adjust_pvalues(p, "bonferroni"), [0.004, 0.04, 0.08, 0.8])
    np.testing.assert_allclose(st.adjust_pvalues(p, "holm"), [0.004, 0.03, 0.04, 0.2])
    np.testing.assert_allclose(st.adjust_pvalues(p, "bh"), [0.004, 0.02, 0.08 / 3, 0.2])
    c = 1 + 1 / 2 + 1 / 3 + 1 / 4
    np.testing.assert_allclose(st.adjust_pvalues(p, "bhy"), c * np.array([0.004, 0.02, 0.08 / 3, 0.2]))
    # random, unsorted input incl. ties: same as statsmodels and order preserved
    rng = np.random.default_rng(4)
    q = np.round(rng.uniform(0, 0.2, 25), 3)
    for ours, theirs in [("bonferroni", "bonferroni"), ("holm", "holm"), ("bh", "fdr_bh"), ("bhy", "fdr_by")]:
        np.testing.assert_allclose(st.adjust_pvalues(q, ours), multipletests(q, method=theirs)[1], atol=1e-12)
    with pytest.raises(ValueError):
        st.adjust_pvalues(p, "nope")


def test_haircut_sharpe_bonferroni():
    """research/06 section 4.2 worked example (Y = 15.75, M = 54)."""
    adj, hc = st.haircut_sharpe_bonferroni(0.8, 15.75, 54)
    assert adj == pytest.approx(0.44, abs=0.005) and hc == pytest.approx(0.45, abs=0.01)
    assert st.haircut_sharpe_bonferroni(1.0, 15.75, 54)[0] == pytest.approx(0.73, abs=0.005)
    assert st.haircut_sharpe_bonferroni(0.6, 15.75, 54)[0] == pytest.approx(0.02, abs=0.005)
    assert st.haircut_sharpe_bonferroni(0.8, 15.75, 1)[0] == pytest.approx(0.8)      # one test: no haircut
    assert st.haircut_sharpe_bonferroni(0.1, 5.0, 100) == (0.0, pytest.approx(1.0))  # nothing survives
    assert st.haircut_sharpe_bonferroni(-0.2, 5.0, 3)[0] == 0.0


# ---------------------------------------------------------------------------------------------
# bootstrap
# ---------------------------------------------------------------------------------------------
def test_stationary_bootstrap_idx_validity():
    rng = np.random.default_rng(0)
    n, b = 200_000, 5.0
    idx = st.stationary_bootstrap_idx(n, b, rng)
    assert idx.dtype == np.int64 and idx.shape == (n,)
    assert idx.min() >= 0 and idx.max() < n
    step = (idx[1:] - idx[:-1]) % n
    continued = step == 1                                                   # block continues
    assert np.mean(~continued) == pytest.approx(1 / b, abs=0.01)           # restart prob = 1/mean_block
    assert 1 / np.mean(~continued) == pytest.approx(b, rel=0.05)           # mean block length
    # restarts are uniform over 0..n-1
    starts = idx[1:][~continued]
    assert abs(starts.mean() - n / 2) < 0.02 * n

    # small n: validity, wrap-around, determinism
    small = st.stationary_bootstrap_idx(30, 4, 123)
    assert small.min() >= 0 and small.max() < 30
    np.testing.assert_array_equal(small, st.stationary_bootstrap_idx(30, 4, 123))
    assert not np.array_equal(small, st.stationary_bootstrap_idx(30, 4, 124))
    # a block that runs past the end wraps to 0
    long_blocks = st.stationary_bootstrap_idx(50, 1e9, 0)
    np.testing.assert_array_equal(long_blocks, (long_blocks[0] + np.arange(50)) % 50)
    # mean_block <= 1 is the iid bootstrap; n = 1 edge case
    iid = st.stationary_bootstrap_idx(100_000, 1.0, 1)
    assert np.mean(((iid[1:] - iid[:-1]) % 100_000) == 1) < 0.001
    np.testing.assert_array_equal(st.stationary_bootstrap_idx(1, 5, 0), [0])
    assert len(st.stationary_bootstrap_idx(10, 0.2, 0)) == 10
    with pytest.raises(ValueError):
        st.stationary_bootstrap_idx(0, 3, 0)


def test_stationary_bootstrap_matches_sequential_definition():
    """The vectorised sampler has the same law as the textbook loop (check block-length distribution)."""
    n, b = 100_000, 8.0
    idx = st.stationary_bootstrap_idx(n, b, 2)
    breaks = np.flatnonzero(((idx[1:] - idx[:-1]) % n) != 1) + 1
    lengths = np.diff(np.r_[0, breaks, n])
    # geometric(1/b): mean b, sd sqrt(b(b-1)) -> 7.48
    assert lengths.mean() == pytest.approx(b, rel=0.05)
    assert lengths.std() == pytest.approx(np.sqrt(b * (b - 1)), rel=0.08)


def test_bootstrap_ci_sharpe_matches_iid_formula():
    rng = np.random.default_rng(3)
    r = rng.normal(0.008, 0.04, 216)
    sharpe_ann = lambda x: x.mean() / x.std(ddof=1) * np.sqrt(12)
    ci, draws = st.bootstrap_ci(sharpe_ann, r, mean_block=1.0, B=2000, seed=5)
    assert draws.shape == (2000,) and ci[0] < sharpe_ann(r) < ci[1]
    se_lo = np.sqrt(12) * st.sharpe_se_iid(r.mean() / r.std(ddof=1), len(r))
    assert draws.std() == pytest.approx(se_lo, rel=0.15)
    ci2, _ = st.bootstrap_ci(sharpe_ann, r, mean_block=1.0, B=2000, seed=5)
    np.testing.assert_array_equal(ci, ci2)                                   # seeded
    # multi-column data: rows resampled jointly
    D = np.column_stack([r, r + 0.01])
    ci3, d3 = st.bootstrap_ci(lambda x: (x[:, 1] - x[:, 0]).mean(), D, mean_block=4, B=50)
    assert np.allclose(d3, 0.01)


def test_optimal_block():
    rng = np.random.default_rng(0)
    iid = rng.normal(size=120)
    assert st.optimal_block(iid) == 3.0                                      # floored
    ar = np.zeros(600)
    e = rng.normal(size=600)
    for t in range(1, 600):
        ar[t] = 0.8 * ar[t - 1] + e[t]
    b = st.optimal_block(pd.Series(ar))
    assert isinstance(b, float) and 3.0 < b < 600
    assert st.optimal_block(np.column_stack([ar, iid.repeat(5)])) >= 3.0


# ---------------------------------------------------------------------------------------------
# CSCV / PBO and SPA
# ---------------------------------------------------------------------------------------------
def _pbo_reference(M, S, selector=None):
    """Straightforward loop implementation of the BBLZ algorithm."""
    T, N = M.shape
    n = T // S
    M = M[T - n * S:]
    blocks = [M[i * n:(i + 1) * n] for i in range(S)]
    out = []
    for c in itertools.combinations(range(S), S // 2):
        comp = [i for i in range(S) if i not in c]
        tr, te = np.vstack([blocks[i] for i in c]), np.vstack([blocks[i] for i in comp])
        sr = lambda A: A.mean(0) / A.std(0, ddof=1)
        r_is, r_oos = sr(tr), sr(te)
        k = int(np.argmax(r_is)) if selector is None else selector(r_is)
        w = sps.rankdata(r_oos)[k] / (N + 1)
        out.append((np.log(w / (1 - w)), r_is[k], r_oos[k]))
    return np.array(out)


def _pbo_is_vector(M, S, combo):
    n = M.shape[0] // S
    A = M[M.shape[0] - n * S:]
    tr = np.vstack([A[i * n:(i + 1) * n] for i in combo])
    return tr.mean(0) / tr.std(0, ddof=1)


def test_cscv_pbo_matches_reference_loop():
    rng = np.random.default_rng(1)
    M = rng.normal(0.0, 0.03, (83, 7))                                        # remainder rows are trimmed
    for S in (4, 6, 8):
        ref = _pbo_reference(M, S)
        got = st.cscv_pbo(M, S=S)
        assert got["n_combos"] == len(ref) == len(list(itertools.combinations(range(S), S // 2)))
        np.testing.assert_allclose(got["logits"], ref[:, 0], atol=1e-10)
        np.testing.assert_allclose(got["sr_is"], ref[:, 1], atol=1e-10)
        np.testing.assert_allclose(got["sr_oos"], ref[:, 2], atol=1e-10)
        assert got["pbo"] == pytest.approx(np.mean(ref[:, 0] <= 0))
        assert got["prob_loss"] == pytest.approx(np.mean(ref[:, 2] < 0))


def test_cscv_pbo_noise_is_about_half():
    """Pure-noise trials: the IS winner is a coin flip OOS.  A single PBO draw is very noisy (CSCV
    combinations are strongly dependent: 0.15..0.9 across seeds), so average over seeds."""
    pbos = []
    for seed in range(20):
        M = np.random.default_rng(seed).normal(0.0, 0.04, (192, 54))
        out = st.cscv_pbo(M, S=16)
        assert out["n_combos"] == 12870
        pbos.append(out["pbo"])
    assert 0.35 < np.mean(pbos) < 0.65
    assert 0.0 <= min(pbos) and max(pbos) <= 1.0
    # fields
    assert out["logits"].shape == out["sr_is"].shape == out["sr_oos"].shape == out["selected"].shape == (12870,)
    assert np.isfinite(out["degradation_slope"]) and out["degradation_slope"] < 0.3   # no persistence in noise
    assert 0.2 < out["prob_loss"] < 0.8


def test_cscv_pbo_with_one_genuinely_good_strategy_is_low():
    pbos, losses = [], []
    for seed in range(10):
        M = np.random.default_rng(seed).normal(0.0, 0.04, (192, 54))
        M[:, 17] += 0.02                                                       # +2%/month, Sharpe ~ 0.5/month
        out = st.cscv_pbo(M, S=16)
        pbos.append(out["pbo"])
        losses.append(out["prob_loss"])
        assert np.mean(out["selected"] == 17) > 0.7                            # it is usually the IS winner
    assert np.mean(pbos) < 0.05 and max(pbos) < 0.15
    assert np.mean(losses) < 0.05


def test_cscv_pbo_custom_selector_nan_rows_and_errors():
    rng = np.random.default_rng(2)
    M = rng.normal(0.0, 0.03, (96, 9))
    sel_worst = lambda R: int(np.argmin(R))                                    # anti-selector
    out_w = st.cscv_pbo(M, S=8, selector=sel_worst)
    ref = _pbo_reference(M, 8, selector=sel_worst)
    np.testing.assert_allclose(out_w["logits"], ref[:, 0], atol=1e-10)
    expected_pick = [int(np.argmin(_pbo_is_vector(M, 8, c))) for c in itertools.combinations(range(8), 4)]
    np.testing.assert_array_equal(out_w["selected"], expected_pick)            # selector is honoured
    # NaN rows are dropped, first rows NaN (warm-up) is the typical case
    M_nan = M.copy()
    M_nan[:6, 3] = np.nan
    out_n = st.cscv_pbo(M_nan, S=8)
    np.testing.assert_allclose(out_n["logits"], st.cscv_pbo(M[6:], S=8)["logits"])
    with pytest.raises(ValueError):
        st.cscv_pbo(M, S=7)
    with pytest.raises(ValueError):
        st.cscv_pbo(M[:10], S=8)


def test_spa_test_noise_vs_real_edge():
    rng = np.random.default_rng(0)
    T, K = 240, 8
    bench = rng.normal(0.0, 1.0, T)
    noise_models = rng.normal(0.0, 1.0, (T, K))
    p_noise = st.spa_test(bench, noise_models, block_size=4, reps=500, seed=1)
    assert p_noise["p_consistent"] > 0.1 and p_noise["n_models"] == K and p_noise["n_obs"] == T
    assert p_noise["p_lower"] <= p_noise["p_consistent"] <= p_noise["p_upper"] + 1e-12

    good = noise_models.copy()
    good[:, 3] = bench - 0.3 + 0.5 * rng.normal(size=T)                       # lower loss by 0.3 on average
    p_good = st.spa_test(bench, good, block_size=4, reps=500, seed=1)
    assert p_good["p_consistent"] < 0.05 and p_good["best_model"] == 3
    # the wrapper takes returns-as-negative-losses, 1-D model, DataFrames, NaN rows and auto block size
    p1 = st.spa_test(pd.Series(bench), pd.Series(good[:, 3]), reps=300, seed=2)
    assert p1["p_consistent"] < 0.05 and p1["block_size"] >= 3
    bn = bench.copy()
    bn[0] = np.nan
    assert st.spa_test(bn, good, block_size=4, reps=200, seed=3)["n_obs"] == T - 1


# ---------------------------------------------------------------------------------------------
# plateau selection
# ---------------------------------------------------------------------------------------------
def _spike_grid():
    f = np.full((7, 7), 0.30)
    f[1:4, 1:4] = 0.60 + 0.004 * np.arange(9).reshape(3, 3) % 0.01        # broad region (tiny wiggle)
    f[5, 5] = 0.95                                                       # isolated spike
    f[5, 4] = f[5, 6] = f[4, 5] = f[6, 5] = 0.35
    return f


def test_plateau_select_prefers_broad_region_over_spike():
    f = _spike_grid()
    assert np.unravel_index(np.argmax(f), f.shape) == (5, 5)             # plain argmax takes the spike
    idx, score, peak, diag = st.plateau_select(f)
    assert idx == (2, 2)                                                  # centre of the broad region
    assert score == pytest.approx(diag["score"][2, 2]) and score > 0.55
    assert peak == pytest.approx(diag["peak_ratio"][2, 2]) and peak <= 1.25
    assert diag["status"][5, 5] == "spike" and diag["peak_ratio"][5, 5] > 2
    assert not diag["eligible"][5, 5] and diag["eligible"][2, 2]
    assert diag["n_nbrs"][2, 2] == 4 and diag["n_nbrs"][0, 0] == 2 and diag["n_nbrs"][0, 3] == 3
    # without the spike test the spike's neighbourhood still scores badly (sd penalty), the choice holds
    assert st.plateau_select(f, peak_ratio_max=None)[0] == (2, 2)


def test_plateau_select_score_formula_and_lambda():
    f = np.array([[0.40, 0.50, 0.45],
                  [0.52, 0.60, 0.55],
                  [0.38, 0.48, 0.44]])
    nb = np.array([0.60, 0.50, 0.52, 0.55, 0.48])                         # centre + 4 neighbours (cell (1,1))
    idx, score, peak, _ = st.plateau_select(f, lam=1.0, peak_ratio_max=None)
    assert idx == (1, 1)
    assert score == pytest.approx(nb.mean() - nb.std(ddof=0))
    assert peak == pytest.approx(0.60 / np.mean([0.50, 0.52, 0.55, 0.48]))
    assert st.plateau_select(f, lam=0.0, peak_ratio_max=None)[1] == pytest.approx(nb.mean())


def test_plateau_select_1d_isolated_and_spike():
    f = np.array([0.10, 0.50, 0.52, 0.51, 0.10, 0.90, 0.10])
    idx, score, peak, diag = st.plateau_select(f, require_pos=True)
    assert idx == (2,)
    assert diag["status"][0] == "isolated" or diag["n_nbrs"][0] == 1      # edge cell has one neighbour
    assert diag["status"][5] == "spike" and diag["status"][0] == "isolated"
    assert diag["status"][4] == "ok" and diag["score"][4] < score


def test_plateau_select_no_eligible_cell_returns_none():
    neg = -np.abs(np.random.default_rng(0).normal(size=(4, 4))) - 0.1
    idx, score, peak, diag = st.plateau_select(neg, require_pos=True)
    assert idx is None and np.isnan(score) and np.isnan(peak) and diag["reason"] == "no eligible cell"
    assert (diag["status"] == "below_floor").all()
    # the same grid is fine if positivity is not required
    assert st.plateau_select(neg, require_pos=False, peak_ratio_max=None)[0] is not None
    # explicit floor (e.g. benchmark Sharpe)
    g = np.full((4, 4), 0.5)
    assert st.plateau_select(g, floor=0.4)[0] is not None
    assert st.plateau_select(g, floor=0.5)[0] is None                     # strictly greater than the floor
    assert st.plateau_select(g, floor=0.6)[0] is None
    # all NaN / a single cell: nothing eligible
    assert st.plateau_select(np.full((3, 3), np.nan))[0] is None
    assert st.plateau_select(np.array([[0.5]]))[0] is None


def test_plateau_select_nan_cells_and_min_nbrs():
    f = np.full((5, 5), 0.5)
    f[:, 0] = np.nan                                                     # infeasible column
    idx, score, peak, diag = st.plateau_select(f)
    assert idx is not None and idx[1] != 0 and diag["status"][0, 0] == "nan"
    assert diag["n_nbrs"][2, 1] == 3                                      # NaN neighbour not counted
    # require 4 neighbours -> only interior cells qualify
    idx4 = st.plateau_select(np.full((5, 5), 0.5), min_nbrs=4)[3]
    assert idx4["eligible"][1:4, 1:4].all() and not idx4["eligible"][0, :].any()


def test_plateau_select_ties_and_default_index():
    f = np.full((5, 5), 0.5)                                              # perfectly flat: everything ties
    idx, *_ = st.plateau_select(f)
    assert idx == (1, 1)                                                  # exact tie -> most neighbours, then C-order
    idx_d, _, _, diag = st.plateau_select(f, default_index=(3, 2))
    assert idx_d == (3, 2) and len(diag["tied"]) == 25
    # two equally good clusters 0.015 apart (< tie_tol): the one nearest the default wins
    g = np.full((5, 5), 0.50)
    g[1, 1] = g[3, 3] = 0.515
    kw = dict(lam=0.0, peak_ratio_max=None)
    idx0, sc0, _, d0 = st.plateau_select(g, **kw)                            # no default: plain best score
    assert sc0 == np.nanmax(d0["score"]) and d0["score"][idx0] == sc0
    assert st.plateau_select(g, default_index=(3, 3), **kw)[0] == (3, 3)
    # a cluster that is clearly better (> tie_tol) wins even if the default is far away
    g[1, 1] = 0.80
    idx_far, *_ = st.plateau_select(g, default_index=(3, 3), **kw)
    assert idx_far == (1, 2)                                                 # inside the (1,1) cluster, nearest to (3,3)
    assert sum(abs(a - b) for a, b in zip(idx_far, (1, 1))) <= 1


def test_plateau_select_3d_grid():
    ax = np.arange(5)
    X, Y, Z = np.meshgrid(ax, ax, ax, indexing="ij")
    f = 1.0 - 0.02 * ((X - 2) ** 2 + (Y - 2) ** 2 + (Z - 2) ** 2)         # smooth hill, max at (2,2,2)
    idx, score, peak, diag = st.plateau_select(f, lam=0.5)
    assert idx == (2, 2, 2) and diag["n_nbrs"][2, 2, 2] == 6
    assert peak == pytest.approx(1.0 / np.mean([0.98] * 6))
    # a hill whose maximum is on the edge: the interior neighbour with a full neighbourhood wins under lam > 0
    f2 = 1.0 - 0.02 * ((X - 0) ** 2 + (Y - 2) ** 2 + (Z - 2) ** 2)
    assert st.plateau_select(f2, lam=1.0)[0][0] <= 1


# ---------------------------------------------------------------------------------------------
# grid design / regression / surface
# ---------------------------------------------------------------------------------------------
def _grid_levels():
    cells = list(itertools.product([1, 2, 3], [10, 20, 30], ["off", "on"]))
    return {"a": [c[0] for c in cells], "b": [c[1] for c in cells], "flag": [c[2] for c in cells]}


def test_grid_design_columns_and_scaling():
    lv = _grid_levels()
    X, names = st.grid_design(lv, cont=["a", "b"], cat=["flag"])
    assert names == ["const", "a", "b", "a^2", "b^2", "a*b", "flag=on"]
    assert X.shape == (18, 7)
    np.testing.assert_array_equal(X[:, 0], 1.0)
    za = X[:, 1]
    assert za.min() == -1 and za.max() == 1 and set(np.unique(za)) == {-1.0, 0.0, 1.0}
    np.testing.assert_allclose(X[:, 3], za ** 2)
    np.testing.assert_allclose(X[:, 5], X[:, 1] * X[:, 2])
    np.testing.assert_array_equal(X[:, 6], (np.array(lv["flag"]) == "on").astype(float))
    assert np.linalg.matrix_rank(X) == 7                                 # identified by the 3x3x2 design
    # a 2-level axis gets no squared term (it would equal the constant)
    lv2 = {"a": [0, 0, 1, 1], "b": [1, 2, 1, 2]}
    _, n2 = st.grid_design(lv2, cont=["a", "b"])
    assert n2 == ["const", "a", "b", "a*b"]
    # DataFrame input works and a constant axis is zero-scaled
    X3, _ = st.grid_design(pd.DataFrame({"a": [1, 2, 3], "c": [5, 5, 5]}), cont=["a", "c"])
    assert (X3[:, 2] == 0).all()


def test_grid_regression_bootstrap_detects_real_effect():
    rng = np.random.default_rng(0)
    lv = _grid_levels()
    za = (np.array(lv["a"]) - 2) / 1.0                                    # -1, 0, 1
    T = 240
    common = rng.normal(0, 0.03, (T, 1))                                  # shared factor => cells are dependent
    mu = 0.006 + 0.008 * za                                               # true effect only through parameter a
    M = common + mu + rng.normal(0, 0.03, (T, 18))
    out = st.grid_regression_bootstrap(M, lv, cont=["a", "b"], cat=["flag"], B=200, mean_block=6, seed=1)
    names = out["names"]
    coef = dict(zip(names, out["coef"]))
    sd = dict(zip(names, out["boot_sd"]))
    assert coef["a"] > 0.4 and coef["a"] > 3 * sd["a"]                     # clearly positive
    assert abs(coef["b"]) < 0.3
    assert 0.0 < out["r2"] <= 1.0 and out["draws"].shape == (200, len(names))
    assert out["partial_r2"]["a"] > out["partial_r2"]["b"] and out["partial_r2"]["a"] > 0.3
    assert (out["boot_sd"] > 0).all() and out["y"].shape == (18,)
    # y is the annualised Sharpe of each cell
    np.testing.assert_allclose(out["y"], M.mean(0) / M.std(0, ddof=1) * np.sqrt(12))
    # point estimate is plain least squares on the design matrix
    X, _ = st.grid_design(lv, ["a", "b"], ["flag"])
    np.testing.assert_allclose(out["coef"], np.linalg.lstsq(X, out["y"], rcond=None)[0], atol=1e-10)
    # reproducible
    out2 = st.grid_regression_bootstrap(M, lv, cont=["a", "b"], cat=["flag"], B=200, mean_block=6, seed=1)
    np.testing.assert_array_equal(out["boot_sd"], out2["boot_sd"])
    with pytest.raises(ValueError):
        st.grid_regression_bootstrap(M[:, :5], lv, cont=["a"])


def test_surface_grid_reproduces_plane_and_masks_outside_hull():
    # plane z = 2x - y + 3 is in the polynomial part of the thin-plate spline => recovered exactly
    pts = [(0, 0), (1, 0), (0, 1), (0.5, 0.5), (0.25, 0.25), (0.25, 0.5)]    # triangle (0,0),(1,0),(0,1)
    x = np.array([p[0] for p in pts]) * 10 + 5
    y = np.array([p[1] for p in pts]) * 4 - 2
    z = 2 * x - y + 3
    gx, gy, gz = st.surface_grid(x, y, z, n=21, smoothing=0.5)
    assert gx.shape == gy.shape == gz.shape == (21, 21)
    assert gx.min() == pytest.approx(5) and gx.max() == pytest.approx(15)       # original units
    assert gy.min() == pytest.approx(-2) and gy.max() == pytest.approx(2)
    inside = ~np.isnan(gz)
    np.testing.assert_allclose(gz[inside], (2 * gx - gy + 3)[inside], atol=1e-6)
    assert np.isnan(gz[-1, -1]) and not np.isnan(gz[0, 0])                      # far corner outside the triangle
    frac_inside = inside.mean()
    assert 0.4 < frac_inside < 0.65                                            # about half of the square
    # smoothing=0 interpolates the data exactly at the nodes of a full grid
    gxs, gys = np.meshgrid([0.0, 1.0, 2.0], [0.0, 1.0, 2.0])
    zs = np.sin(gxs) + gys ** 2
    ax, ay, az = st.surface_grid(gxs.ravel(), gys.ravel(), zs.ravel(), n=5, smoothing=0.0)
    np.testing.assert_allclose(az[::2, ::2], zs, atol=1e-8)                    # grid nodes are every 2nd cell
    assert not np.isnan(az).any()                                              # full square is the hull
    with pytest.raises(ValueError):
        st.surface_grid([1, 2], [1, 2], [1, 2])
    with pytest.raises(ValueError):
        st.surface_grid([1, 2, 3], [1, 1, 1], [1, 2, 3])


# ---------------------------------------------------------------------------------------------
# ERC
# ---------------------------------------------------------------------------------------------
def test_erc_weights_equal_risk_contributions():
    A = np.array([[0.04, 0.012, 0.002],
                  [0.012, 0.01, -0.001],
                  [0.002, -0.001, 0.0025]])
    w = st.erc_weights(A)
    assert w.sum() == pytest.approx(1.0) and (w > 0).all()
    rc = w * (A @ w)
    np.testing.assert_allclose(rc / rc.sum(), 1 / 3, atol=1e-8)
    # diagonal covariance: ERC is inverse-volatility
    D = np.diag([0.04, 0.01, 0.0025])
    iv = 1 / np.sqrt(np.diag(D))
    np.testing.assert_allclose(st.erc_weights(D), iv / iv.sum(), atol=1e-9)
    # scale invariance and DataFrame/ndarray input
    np.testing.assert_allclose(st.erc_weights(A * 1e-6), w, atol=1e-8)
    np.testing.assert_allclose(st.erc_weights(pd.DataFrame(A)), w, atol=1e-10)
    assert st.erc_weights(np.array([[0.02]])).tolist() == [1.0]
    # larger, correlated example
    rng = np.random.default_rng(0)
    Z = rng.normal(size=(500, 8)) @ rng.normal(size=(8, 8)) * 0.02
    C = np.cov(Z.T)
    w8 = st.erc_weights(C)
    rc8 = w8 * (C @ w8)
    assert rc8.max() / rc8.min() < 1 + 1e-6
