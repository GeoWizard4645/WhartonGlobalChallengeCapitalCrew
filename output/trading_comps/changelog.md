# Trading comps: changelog

One entry per run of `quant/run_backtests.py` (newest last).

## 2026-10-19 03:05 UTC · git `2c7657cd70` · data to 2026-09-30

- note: test window recomputed after data-layer bug fix (share counts / spin-off ratios / negative debt / capex sign / GICS look-ahead); selection rule unchanged (plateau_v1 on TRAIN only)
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `theta=0.1, pe_cap=40, ev_cap=35, size_filter=False, basis=TTM`
- previous run chosen: `theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis=TTM` -> CHANGED
- train Sharpe chosen 0.53 (previous run 0.34); test Sharpe chosen 0.53 (previous run 0.40); test CAGR chosen 13.5% (previous run 10.0%)
- test Sharpe default 0.48 (previous run 0.40); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) -1.90% (previous run -5.39%)
- PBO 31.4% (previous run 36.4%); DSR train (ledger N) 0.635 (previous run 0.541)
- evidence ladder 3/7 -> mixed (previous run 1/7 -> does not work)
- ledger trials N = 62 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): GAP, HPQ, MMS, ANF, AA, UHS, HRB, G, GEN, KBR, ENS, BAH, THC, SFM, INCY, MU, ZTS, PNR, SON, CRUS

## 2026-10-19 03:18 UTC · git `2c7657cd70` · data to 2026-09-30

- note: re-run after independent data audit fixes (spin-off repair limited to split+dividend events, bankruptcy splice cut, split-basis share counts, successor-CIK stitching, CIK overrides NVE/LSI/TBL, NI fallback order, SEC data-set patch 2023-2026); selection rule unchanged
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis=TTM` (= literature default)
- previous run chosen: `theta=0.1, pe_cap=40, ev_cap=35, size_filter=False, basis=TTM` -> CHANGED
- train Sharpe chosen 0.16 (previous run 0.53); test Sharpe chosen 0.47 (previous run 0.53); test CAGR chosen 11.9% (previous run 13.5%)
- test Sharpe default 0.47 (previous run 0.48); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) -5.63% (previous run -1.90%)
- PBO 31.5% (previous run 31.4%); DSR train (ledger N) 0.261 (previous run 0.635)
- evidence ladder 1/7 -> does not work (previous run 3/7 -> mixed)
- ledger trials N = 62 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): UHS, THC, G, GAP, HRB, MMS, BAH, SNA, BKNG, MLI, GEN, DBX, CDW, GEHC, BSX, LVS, PNR, EHC, PTC

## 2026-10-19 04:15 UTC · git `2c7657cd70` · data to 2026-09-30

- note: final re-run after re-audit fixes (FY diluted-share band +-25%, market-cap/assets plausibility guard, LSI override end date); selection rule unchanged
- selection rule: plateau_v1 on the TRAIN window only (rule, grid and pre-registration unchanged); exactly one `confirm()` on the TEST window per run, for the cell chosen on TRAIN; no re-selection after seeing TEST
- chosen: `theta=0.1, pe_cap=40, ev_cap=35, size_filter=False, basis=TTM`
- previous run chosen: `theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis=TTM` -> CHANGED
- train Sharpe chosen 0.55 (previous run 0.16); test Sharpe chosen 0.51 (previous run 0.47); test CAGR chosen 13.0% (previous run 11.9%)
- test Sharpe default 0.47 (previous run 0.47); SPY 0.89 (previous run 0.89)
- FF5+MOM alpha (full) -1.97% (previous run -5.63%)
- PBO 32.1% (previous run 31.5%); DSR train (ledger N) 0.663 (previous run 0.261)
- evidence ladder 3/7 -> mixed (previous run 1/7 -> does not work)
- ledger trials N = 62 (distinct cell ids; re-running a cell does not raise N)
- live picks (chosen): GAP, HPQ, MMS, ANF, AA, UHS, HRB, G, GEN, KBR, ENS, BAH, THC, SFM, INCY, MU, ZTS, PNR, SON, CRUS

