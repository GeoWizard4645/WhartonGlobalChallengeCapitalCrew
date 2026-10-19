# Quality-filtered momentum: changelog

One entry per run of `quant/run_backtests.py` (newest last).

## 2026-10-19 02:59 UTC · git `2c7657cd70` · data to 2026-09-30

- note: PROVISIONAL run before the lead's data-layer fixes (changelog test)
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` (= literature default)
- previous run chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` -> UNCHANGED
- train Sharpe chosen 0.54 (previous run 0.54); test Sharpe chosen 0.69 (previous run 0.69); test CAGR chosen 20.0% (previous run 20.0%)
- test Sharpe default 0.69 (previous run 0.69); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) 0.37% (previous run 0.37%)
- PBO 71.7% (previous run 73.7%); DSR train (ledger N) 0.662 (previous run 0.663)
- evidence ladder 1/7 -> does not work (previous run 1/7 -> does not work)
- ledger trials N = 223 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): not computed

## 2026-10-19 03:00 UTC · git `2c7657cd70` · data to 2026-09-30

- note: test window recomputed after data-layer bug fix (share counts / spin-off ratios / negative debt / capex sign / GICS look-ahead); selection rule unchanged (plateau_v1 on TRAIN only)
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` (= literature default)
- previous run chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` -> UNCHANGED
- train Sharpe chosen 0.54 (previous run 0.54); test Sharpe chosen 0.69 (previous run 0.69); test CAGR chosen 20.0% (previous run 20.0%)
- test Sharpe default 0.69 (previous run 0.69); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) 0.37% (previous run 0.37%)
- PBO 71.7% (previous run 71.7%); DSR train (ledger N) 0.662 (previous run 0.662)
- evidence ladder 1/7 -> does not work (previous run 1/7 -> does not work)
- ledger trials N = 223 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): PBF, ILMN, VLO, APA, NUE, ANF, SN, STLD, CHRD, VAL

## 2026-10-19 03:14 UTC · git `2c7657cd70` · data to 2026-09-30

- note: re-run after independent data audit fixes (spin-off repair limited to split+dividend events, bankruptcy splice cut, split-basis share counts, successor-CIK stitching, CIK overrides NVE/LSI/TBL, NI fallback order, SEC data-set patch 2023-2026); selection rule unchanged
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` (= literature default)
- previous run chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` -> UNCHANGED
- train Sharpe chosen 0.53 (previous run 0.54); test Sharpe chosen 0.69 (previous run 0.69); test CAGR chosen 20.0% (previous run 20.0%)
- test Sharpe default 0.69 (previous run 0.69); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) 0.29% (previous run 0.37%)
- PBO 70.8% (previous run 71.7%); DSR train (ledger N) 0.649 (previous run 0.662)
- evidence ladder 1/7 -> does not work (previous run 1/7 -> does not work)
- ledger trials N = 223 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): PBF, ILMN, VLO, APA, NUE, ANF, SN, STLD, CHRD, VAL

## 2026-10-19 04:11 UTC · git `2c7657cd70` · data to 2026-09-30

- note: final re-run after re-audit fixes (FY diluted-share band +-25%, market-cap/assets plausibility guard, LSI override end date); selection rule unchanged
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` (= literature default)
- previous run chosen: `order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none` -> UNCHANGED
- train Sharpe chosen 0.53 (previous run 0.53); test Sharpe chosen 0.69 (previous run 0.69); test CAGR chosen 20.0% (previous run 20.0%)
- test Sharpe default 0.69 (previous run 0.69); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) 0.29% (previous run 0.29%)
- PBO 70.8% (previous run 70.8%); DSR train (ledger N) 0.649 (previous run 0.649)
- evidence ladder 1/7 -> does not work (previous run 1/7 -> does not work)
- ledger trials N = 223 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): PBF, ILMN, VLO, APA, NUE, ANF, SN, STLD, CHRD, VAL

