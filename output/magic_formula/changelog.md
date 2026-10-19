# Magic Formula: changelog

One entry per run of `quant/run_backtests.py` (newest last).

## 2026-10-19 03:02 UTC · git `2c7657cd70` · data to 2026-09-30

- note: test window recomputed after data-layer bug fix (share counts / spin-off ratios / negative debt / capex sign / GICS look-ahead); selection rule unchanged (plateau_v1 on TRAIN only)
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `ranking=MF, n=25, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc`
- previous run chosen: `ranking=MF, n=20, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc` -> CHANGED
- train Sharpe chosen 1.13 (previous run 1.12); test Sharpe chosen 0.61 (previous run 0.60); test CAGR chosen 13.6% (previous run 13.4%)
- test Sharpe default 0.63 (previous run 0.63); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) 0.55% (previous run 0.61%)
- PBO 21.1% (previous run 29.8%); DSR train (ledger N) 0.996 (previous run 0.996)
- evidence ladder 4/7 -> mixed (previous run 4/7 -> mixed)
- ledger trials N = 38 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): GEN, HRB, ADBE, CROX, CI, GDDY, ACN, MO, HON, MU, IT, INCY, TPR, BMY, SAIC, BAH, G, SOLV, SNDK, CTSH, TTEK, HPQ, BKNG, ANF, LDOS

## 2026-10-19 03:16 UTC · git `2c7657cd70` · data to 2026-09-30

- note: re-run after independent data audit fixes (spin-off repair limited to split+dividend events, bankruptcy splice cut, split-basis share counts, successor-CIK stitching, CIK overrides NVE/LSI/TBL, NI fallback order, SEC data-set patch 2023-2026); selection rule unchanged
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `ranking=MF, n=25, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc`
- previous run chosen: `ranking=MF, n=25, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc` -> UNCHANGED
- train Sharpe chosen 1.12 (previous run 1.13); test Sharpe chosen 0.61 (previous run 0.61); test CAGR chosen 13.5% (previous run 13.6%)
- test Sharpe default 0.63 (previous run 0.63); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) 0.53% (previous run 0.55%)
- PBO 24.5% (previous run 21.1%); DSR train (ledger N) 0.996 (previous run 0.996)
- evidence ladder 4/7 -> mixed (previous run 4/7 -> mixed)
- ledger trials N = 38 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): GEN, HRB, ADBE, CROX, CI, GDDY, ACN, MO, HON, MU, IT, INCY, TPR, BMY, SAIC, BAH, G, SOLV, SNDK, CTSH, TTEK, HPQ, BKNG, ANF, LDOS

## 2026-10-19 04:13 UTC · git `2c7657cd70` · data to 2026-09-30

- note: final re-run after re-audit fixes (FY diluted-share band +-25%, market-cap/assets plausibility guard, LSI override end date); selection rule unchanged
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `ranking=MF, n=25, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc`
- previous run chosen: `ranking=MF, n=25, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc` -> UNCHANGED
- train Sharpe chosen 1.13 (previous run 1.12); test Sharpe chosen 0.61 (previous run 0.61); test CAGR chosen 13.6% (previous run 13.5%)
- test Sharpe default 0.63 (previous run 0.63); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) 0.56% (previous run 0.53%)
- PBO 30.1% (previous run 24.5%); DSR train (ledger N) 0.996 (previous run 0.996)
- evidence ladder 4/7 -> mixed (previous run 4/7 -> mixed)
- ledger trials N = 38 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): GEN, HRB, ADBE, CROX, CI, GDDY, ACN, MO, HON, MU, IT, INCY, TPR, BMY, SAIC, BAH, G, SOLV, SNDK, CTSH, TTEK, HPQ, BKNG, ANF, LDOS

