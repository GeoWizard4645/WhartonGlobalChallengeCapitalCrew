# Re-audit: do the lead's fixes work, and do the numbers in `output/summary.json` reproduce?

Auditor: independent re-audit, run after the lead's fixes to the data layer. No repo code was modified and git was not used. Only this file was written to the repo.
Scripts and raw outputs are in the session scratch directory `.../scratchpad/reaudit/` (s1* market cap, s2* returns, s3* fundamentals, s4* comps, s5* reproducibility, s6* sensitivity). Earlier auditors' scripts (`audit_data/`, `audit_bt/`) were reused: `indep.py`, `check1.py`, `float_check.py`, `split_basis_new.py`, `mysim.py`.

Code and data state audited: `quant/data/context.py` mtime 23:09:46, `fundamentals.py` 23:09:21, `universe.py` 23:09:21, `sec.py` 23:22:01, `comps.py`/`quality.py` 22:56, `snapshots.parquet` 23:12:15, `summary.json` 23:19. `quality_momentum.py` (23:41:01) and `quality_momentum/preregistration.json` (23:41:01) were touched after the final run; section 5 shows the edit changed no backtest number.

## 0. Scorecard

| # | Item | Result |
|---|------|--------|
| 1 | Market cap (`shares_on` / `market_cap`) | **PARTIAL PASS.** Large improvement (mcap NaN 1,503 -> 1,122; < $100M 828 -> 147; > $10T 10 -> 0; GOOGL 2022, SHW 2021, ABT/IBM 2012 fixed; spin-off consistency fixed). New or unfixed defects remain on 0.2-0.9% of member-months (section 1.3). They touch 0 of 4,525 held name-months in the chosen Magic Formula (MF) book and 2 of 2,542 in the chosen Trading comps (TC) book. |
| 2 | Returns repair / splice cut | **PASS.** DHR repaired, special-dividend days untouched, CHRD splice removed. Caveat: the splice cut deletes CHRD's whole pre-2020 history (no effect on chosen cells, tested). |
| 3 | Fundamentals | **PASS** on all eight listed fixes. Residuals: APA FY2023 PP&E, a too-broad LSI override, and the Chubb Jan-Feb 2016 gap (not on the fix list, still open). |
| 4 | Comps look-ahead | **PASS.** 0 of 17,595 `*_next` rows receive a peer-group code. Side effects in 4.2. |
| 5 | Reproducibility of `summary.json` | **PASS.** All 45 (strategy, series, window) blocks recompute to 7e-13. Independent simulator reproduces the 4 chosen/default daily net-return series to 6.3e-16. |
| 6 | Test suite | **PASS.** `.venv/bin/python -m pytest tests -q`: 548 passed in 33.5 s. |

## 1. Market cap

### 1.1 Population test, all S&P 900 member-months 2012-01 .. 2026-09 (129,435 rows with a snapshot, plus 576 members with no fundamentals row at all = 130,011)

| Defect (data_audit.md 4.3) | Pre-patch | Post-patch (22:57) | FINAL |
|---|---|---|---|
| mcap NaN | 1,503 (1.16%), 29 tickers | 1,503 | **1,122 (0.87%), 22 tickers** |
| mcap < $100M | 828 | 179 | **147** (FOXA 32, BKR 25, GRMN 15, ECHO 10, BRK-B 7, APA 7, ICE 6, ...) |
| mcap > $10T | 10 | 3 | **0**, but LAMR 2012-11..2014-04 is 18 months at $3.6-5.1 TRILLION (1000x), see 1.3 |
| rows from the old "cover scale error?" branch | 714 (93% off by > 100x) | 0 | 0 (replaced by 389 `diluted(cover mis-scaled vs history)` and 876 `cover(diluted mis-scaled)` rows, validated only indirectly by the float test) |
| spin-off / pseudo-split inconsistency | 3,538 rows, 40 tickers | fixed for ABT/IBM/GE | 3,327 rows (2.57%, 40 tickers) now carry the later-ratio correction (median 24%, TDW x0.031, AIV x7.5). Implied-share continuity flags 0.33% of them vs 0.23% base rate, so the correction is right. AIV 2018-12 $6.8B, TDW 2013-06 $2.8B, DD 2015-06 $46.3B, FDX $48.4B, T $184B all plausible |
| genuine split between cover date and filing | 21 rows | 6 | **4** (AOS 2017-02/03, PII 2012-01, MDU 2024-11); GOOGL 2022 x3 fixed |

`EntityPublicFloat` ratio test (same 297 CIKs, 3,694 observations; mcap on the float date over SEC non-affiliate float): median 1.016 (P5 0.978, P25 1.003, P75 1.098, P95 1.681), unchanged from post-patch (1.016 / 0.980 / 1.003 / 1.097 / 1.678). Ratio < 0.01: pre 42, post 29, FINAL 33; ratio > 100: 3 / 2 / 2. 23 of the 35 outliers are SEC float values mis-scaled by a power of 1000 (ratio ~1 after rescaling); 9 are ours (NXST 2012, FND 2017, LIN 2018-06, ECHO 2024 and 2025, BRK-B 2012-15 x4 = 0.24% of observations). The BRK-B 2013-15 values are new: they were NaN before and the new fallback produced mcaps of $0.18-0.22B instead of ~$235B. Only 2 of 3,696 comparable observations changed by more than 1% between post-patch and FINAL (SHW 2021-06 and GOOGL 2014-06, both improvements).

### 1.2 Spot checks (market cap, $B; price_raw x shares)

| name, date | FINAL | before | note |
|---|---|---|---|
| GOOGL 2022-07-15 / 07-18 / 07-29 / 08-31 / 09-30 | 1,473 / 1,437 / 1,521 / 1,415 / 1,251 | 28,306 on 08-31 (x19) | = price x 13.08-13.18B shares |
| SHW 2021-03-31 / 04-30 / 05-28 / 06-30 | 66.1 / 72.8 / 75.4 / 72.5 | 3.1x too high | pre-split $738 x 89.6M = $66B |
| ABT 2012-12-31 | 103.5 | 48 | price $65.50 x 1.581B |
| IBM 2012-12-31 | 216.4 | 193 | $191.55 x 1.130B |
| AAPL 2020-08-28 | 2,134.5 | ok | $499.23 x 4.28B |
| NVDA 2024-06-07 | 2,973.8 | ok | |
| BLK / BG / NWE / PNFP 2026-09-30 | 164.0 / 20.8 / 4.2 / 14.2 | no fundamentals | stitched, plausible price x shares |
| HSY | 0 NaN of 177 months (101 `carried`, 63 `cover`) | 57% NaN | 2020-01 $32.6B |

(My reference values for GOOGL/SHW were from memory and rough; the checks above are price x share-count arithmetic, which is what matters.)

### 1.3 What is still wrong (all found with an implied-share continuity test: S = mcap / price_raw compared with its +-6 month median, excluding months within 250 days of a genuine split)

295 member-months (0.23%, 117 tickers) have implied shares more than 1.4x above or 0.71x below the local median: 211 over-stated, 84 under-stated, 48 of the 1000x type. By source: 187 `diluted(multi-class?)`, 55 `cover`, 24 `diluted`, 23 `diluted(cover mis-scaled vs history)`.

1. **Diluted share count doubled in 10-K snapshots (NEW, not in earlier audits; medium-low).** 283 of 24,407 FY snapshots (1.16%) have `shares_diluted` between 1.4x and 2.6x the cover count, 272 of them flagged `sh_dil_q4derived`. Cause: `fundamentals.Company.shares_wavg` (cls == 4 branch, ~line 824) derives Q4 as `4*FY - (q1+q2+q3)` and accepts anything in `[0.5*FY, 2.0*FY]`. A split inside the fiscal year (pre-split quarterly counts, post-split FY) or one mis-scaled quarter leaves d ~ 2*FY (NVDA FY2025: 47.1B vs true 24.8B; AMZN FY2022: 19.7B vs 10.3B; AXP FY2019 1.657B vs 0.83B). `shares_on` then takes the `diluted(multi-class?)` branch (ratio 1.2-3x) and market cap is 1.4-2.1x too high for the 2-3 months until the next 10-Q: 217 member-months, 76 tickers (NVDA 2022-03/04 and 2025-02/04 (up to $5.9T vs true ~$3.3T), AMZN 2023-02/04, KO 2013, AXP 2020, TJX 2019, ORLY 2026, CMG 2025, PANW 2025). **Fix:** accept the Q4 derivation only if `0.8*FY <= d <= 1.25*FY` (or just return FY); do not rely on the reference test in the multi-class branch because GOOGL/META legitimately differ from the single-class cover count.
2. **1000x scale errors with no reference (low).** LAMR 2012-11..2014-04 (diluted tag 9.4e10, no cover count, `_cover_reference` NaN): $3.6-5.1T. 1000x too low: GRMN 2017-02..10 and 2019-02..07 (cover history itself mis-scaled so the reference agrees), FOXA 2019-06..2022-01 (the `rescaled` branch produced $16M), BKR 2017-07..2019-07 (`carried`, $2k), BRK-B (all 50 priced months, 2012-01..2016-02, are ~1000x too low: diluted count is in class-A equivalents, mcap $0.1-0.2B; the other 127 months are NaN, so Berkshire has no valid market cap in any month), ECHO 2024-26, ICE 2013-08..2014-01, LIN 2018-11..2019-02. **Catch-all fix:** reject any share count that implies mcap/total assets outside [0.003, 100]. On the whole population a [0.003, 100] band flags 189 rows (LAMR 18, BRK-B 43, 128 below $100M) and no legitimate row; the only near miss is PLTR 2024-09 at 64x (a [0.003, 60] band would flag it).
3. **Missing market cap (low).** 1,122 member-months, 22 tickers, mostly large multi-class names: STZ 177/177, GEF 177, V 164/177, BRK-B 127, SPG 75, COKE 49, WSO 45, PLNT 40, BKR 39 (2019-08..2023-01), ERIE 36, DDS 36, WMG 27, HLNE 25, KMI 21, UAA 21. Fix as suggested earlier: sum the per-class dei counts (FSDS `num.txt` keeps `segments`).
4. 177 `carried` rows: CRWD 2020-07 is 0.26x of the SEC float (class A only); stale-by-construction for dual-class issuers.

**Materiality, tested.** Held name-months touching a flagged row: QM 4 of 1,838 (QM does not use market cap), TC 2 of 2,542 (TRN 2015-02/03), MF 0 of 4,525. I rebuilt a context in which 584 flagged rows are repaired with the local median share count and re-ran the three chosen cells (`s6_sens.py`): MF train Sharpe 1.1243 -> 1.1224, CAGR 16.36% -> 16.33%; TC train Sharpe 0.1557 -> 0.1665, CAGR 1.73% -> 1.90%; test Sharpe within +0.002 for both; QM unchanged. These defects do not move the headline numbers.

## 2. Returns

Raw `prices.load_returns()` vs `ctx.returns`, every cell compared (4,979 x 5,588):

* `_repair_spinoff_returns` changes **14 cells** in total (104 split+dividend events exist in the raw file). Inside S&P 900 member windows: **EXPE 2011-12-21 -33.6% -> -51.2%, TMUS 2013-05-01 -15.8% -> -30.2%, DHR 2016-07-05 +61.2% -> +3.6% (correct), XRX 2017-01-03 +37.6% -> +19.8%** (data audit called this still implausible). The other 10 are outside the universe (MPB, RIG, SITC x2, SBRA, ATRO, PRSU, DXC 2015-11-30 -> -20.5%, LENZ, IPDN). None of the four in-universe repairs was in a live book of any chosen cell.
* **Not altered (confirmed equal to raw):** KDP 2018-07-10 (+11.5%), BKR 2017-07-05 (-7.3%), GEN 2020-02-03 and 2016-03-04, MDLZ 2012-10-02, LDOS 2016-08-17, KLAC 2014-11-26, CXW 2013-04-17, AIV 2020-11-03. The chosen MF book held KDP on 2018-07-10 (signal 2017-10-31) and the default MF book held LDOS on 2016-08-17, both with the correct unaltered total return. HR 2022-07-21 (+25.9% vs price return +0.9%) is also untouched (REIT, excluded from all strategies).
* `_cut_splices` blanks **76,100 cells in 50 tickers** (49 micro-caps with no index membership, plus CHRD 2,627 cells, 604 of them in S&P 900 windows 2018-07..2020-11). CHRD 2020-11-20 (+25,733%) is NaN and all earlier CHRD returns and prices are NaN. Side effect: Oasis Petroleum's 28 index member-months (price $13 -> $0.12, total return -99.2% since 2011) vanish from the universe. I restored the pre-splice history in a copy of the context and re-ran the three chosen cells: no change at all (`s6_sens.py`, "chrd" and "both" scenarios). Better rule: NaN only the splice-day return and treat the old series as ending there.
* Remaining |daily return| > 50% among S&P 900 members: **28 events** (36 before: DHR and the 8 CHRD days gone, EXPE now -51%). All volume-confirmed real events per the data audit classification (VRTX 2012-05/2013-04, MTUS 2016-01, AMD 2016-04, PCG 2019-01 x2, March 2020 oil/COVID names, CAR 2021-11, SHC 2023-01, GME 2024-05 x2, CPRI, GL, MEDP, ECHO, KD, STRL, MRNA 2026-08); full list in `returns_gt50.csv`.

## 3. Fundamentals

Re-ran the 179-pair accuracy test (`check1.py` against an independent companyfacts parser). Within 1%: net income 176/177 (was 174/177), revenue 166/171, EBIT 148/155, assets 178/178, equity 163/163, cash 165/165, debt 98/108. EBIT proxy error OI 2014-06 (-12%) and the other classified debt/revenue definitional gaps are unchanged (not on the fix list).

| Fix | Evidence |
|---|---|
| NI fallback order | WELL 2014-12-31 = 335.164M = ProfitLoss - NCI (was -19.6%); TFC 2020-11 = 3,874M (was -5.6%); ETR 2019-05 -1.06% remains because `NetIncomeLoss` (first in chain) excludes subsidiary preferred dividends, which is the right tag |
| Capex coverage | Non-financial snapshots with assets >= $1bn, share with capex: 2012 92% (was 86), 2016 95% (90), 2020 96% (90), 2024 95% (89), 2026 95% (89). LLY, VZ, ADP, GLW 100% of 59 snapshots each since 2012, values equal the independent tags (LLY FY2025 7,841M, VZ FY2024 17,090M, ADP FY2026 196.6M, GLW FY2024 965M) |
| Oil and gas PP&E | MGY 2019-12 3.12B (O&G net), RRC 2014-12 8.02B (7.98B O&G + 38M other, flag `ppe_plus_oilgas`), DVN unchanged own PP&E line. **Residual:** APA FY2023 ppe_net 0.22B vs assets 16.9B (only the gross O&G tag exists) |
| Gross-margin guard | 0 snapshot rows outside [-100%, 95%] (9,503 set to NaN, flag `gp_implausible`) |
| Negative debt | 241 negative `total_debt` in raw snapshots -> 0 of 912,794 rows of `ctx.fundamentals` over all month-ends |
| Successor stitching | BLK, BG, NWE, PNFP all have fundamentals at 2026-09-30 (absent from the raw `asof`); GOOGL has fundamentals at 2016-04-29 and 2016-05-31 (cik 1288776 -> 1652044 on 2016-06). Members with no fundamentals row: 576 of 130,011 (0.44%, was 0.52%); 2026-09-30 only OZK. **Not fixed:** Chubb (cik 896159) is absent from the S&P 500 for the 2016-01-29 and 2016-02-29 month-ends (old Chubb Corp row has yf_ticker NaN until 2016-02-22, ACE absent from 2015-12-29 to 2016-03-02) |
| CIK overrides | NVE -> 741508 (assets $11.5-12.3B; was a $136M registrant), TBL -> 814361 (no filings after 2011, so no stale fundamentals). **Defect:** the `LSI` override (`valid_from/valid_to = None`) also maps Life Storage Inc (S&P 400, 27 snapshots 2016-12..2023-06) to LSI Corp's cik 703360, which stopped filing in 2014. REIT, excluded everywhere, but wrong. Fix: `("LSI", None, "2014-12-31", 703360, ...)` |
| FSDS patch | KO 10-Q (filed 2026-07-29), V 10-Q (2026-07-29, fiscal_period Q3), ABT 10-Q (2026-07-28) present; SPGI FY2024 10-K (2025-02-11), AOS FY2024 10-K (2025-02-11), BWXT Q2-2026 10-Q/A (2026-08-05), CR FY2022 10-K (2023-03-01), FLG Q1-2025 10-Q (2025-05-09) present |

Point-in-time and cache consistency: 40 random (cik, date) pairs (half on filing days): the row used has `filed < date` 40/40, a rebuild from facts truncated at `date` returns the same accession and identical values 40/40; a full rebuild reproduces the cached `snapshots.parquet` rows for 39 CIKs (2,520 rows, 0 differences), so the later `sec.py` edit (23:22) did not leave the cache stale.

## 4. Comps look-ahead

### 4.1 Guard
Over 189 month-end S&P 900 universes (2011-01 .. 2026-09; 136,859 rows) 17,595 rows (12.9%) carry a `gics_source` ending `_next`; `quant.signals.comps.group_codes` returns a null sub-industry and industry key for **all** of them (0 violations). TC holdings with a `_next` label: 0 of 2,542.

### 4.2 Consequences to state in the write-up
* The guard removes a large part of the early TC universe: share of the ex-Financials/Real-Estate universe with no peer group code: 2011 61%, 2012 62%, 2013 26%, 2014 11%, 2015 12%, 2016 18%, 2017 3%, 2023 16% (126 names), otherwise below 4%. TC's train window (2012-2018) is therefore run on a materially thinner universe in 2012-2013.
* QM (`quality_table` industry medians on `gics_industry` / `gics_industry_group`) and MF (sector exclusion, and a `gics_next` sector fallback) are not guarded: 14.4% of QM chosen held name-months and 14.7% of MF chosen carry `_next` labels (QM 70% in 2012, MF 99% in 2011-12). Industry/sector labels change rarely, so I rate this low, but it is the remaining label look-ahead.

## 5. Reproducibility of the headline numbers

**Convention used by `summary.json` (verified):** daily net returns from the engine -> compounded to calendar months (a leading or trailing month with < 60% of its business days is dropped) -> Sharpe = mean(r - rf) / sd (ddof 1) x sqrt(12) with monthly rf = compounded DTB3/252 daily; CAGR = geometric over n months with 12 periods per year; max drawdown from the daily series. Train = months ending <= 2018-12-31, test = months ending >= 2019-01-31. This monthly Sharpe is higher than a daily-based Sharpe (below).

1. **Metrics from `daily_chosen.csv`, `daily_default.csv`, `daily_benchmarks.csv`:** my own re-implementation reproduces n_months, CAGR, vol, Sharpe, Sortino, total return and max drawdown for all 45 (strategy x {chosen, default, SPY, RSP, EW-SP900} x {full, train, test}) blocks, max abs difference **7.1e-13**, no n_months mismatch. The chosen cell's monthly series equals the `grid_monthly_returns.csv` column to 1.7e-15 and `grid_metrics_train/test.csv` to 6 decimals; `consistency_max_abs_diff` is 0.0 for all three.
2. **Independent simulator:** target weights regenerated from the current strategy modules for the chosen cells over the full period (start dates from summary, end 2026-09-30, 10 bps), run through `mysim.simulate` (own dollar-ledger simulator, sleeves of 12 for MF). Max abs difference of daily `ret_net` vs the stored CSV: **QM 4.8e-16, TC 4.8e-16, MF chosen 5.7e-16, MF default 6.3e-16** (also gross, cost, turnover below 6e-16); cumulative net returns +655.47% (QM), +168.51% (TC), +700.46% (MF chosen), +707.79% (MF default) agree to 1e-13. Because weights are rebuilt from today's code and data, the 23:41 edit of `quality_momentum.py` changed no number, and `snapshots.parquet` matches the code.
3. **Benchmarks:** SPY and RSP columns equal `ctx.returns` (1e-16); EW-SP900 re-simulated per strategy (sector exclusions as in the runner, as-traded price >= $5, 10 bps) matches to 6.7e-16.
4. **Alpha and t-stats:** FF5+MOM regressions with statsmodels (OLS, HAC lags 4, small-sample correction) reproduce `alpha_ann`, t and n exactly for all 9 (strategy, window) combinations (e.g. QM train -3.02% / t -0.757 / n 95; TC train -8.70% / t -2.241 / n 83).

| Chosen cell | Train Sharpe / CAGR (monthly) | Test Sharpe / CAGR (monthly) | Daily convention train / test Sharpe |
|---|---|---|---|
| QM (= default; plateau rule fell back, stability check failed) | 0.526 / 7.99% | 0.692 / 20.01% | 0.456 / 0.675 |
| MF (n=25, min cap $5B, staggered; default n=30, $1B: 1.017 / 15.57% train, 0.631 / 14.36% test) | 1.124 / 16.36% | 0.611 / 13.51% | 1.096 / 0.583 |
| TC (= default; fallback) | 0.156 / 1.73% | 0.474 / 11.87% | 0.156 / 0.467 |
| SPY (same test window) | | 0.889 / 17.19% | |

**Verdict: the headline numbers in `summary.json` reproduce exactly (to floating point) from the saved daily series and from an independent simulator driven by the current code and data. They are not independent of the survivorship bias, which this re-audit did not change (priced share of true members 81% on average, minimum 63%; EW-SP900 minus RSP +0.5 %/yr CAGR).**

## 6. Process observations (no numerical effect found)

* The test window was evaluated in at least five full runs (voided provisional runs 02:43 and 02:46 UTC per the pre-registration notes, then 02:59-03:05 and 03:14-03:19 per the changelogs) while data-layer bugs were being fixed. The TC chosen cell moved from the default (train Sharpe 0.34) to theta 0.10 / no size filter (0.53) and back to the default (0.16) as data fixes landed, so TC's train number is highly data-definition dependent. In the final grid the 7 best cells (all theta 0.10, no size filter) have train Sharpe 0.53-0.60, but the pre-registered bootstrap stability check forced the fallback to the default, whose train Sharpe is 0.156 (grid median 0.357, 54 cells).
* `quality_momentum/preregistration.json` was rewritten at 23:41:01 (after the final run; the embedded timestamp 02:57:36 UTC and grid hash are unchanged). The registrations for QM and MF were re-stamped at 02:57:36 UTC after two voided provisional runs; the notes disclose this and the grid content and selection rule did not change.
* `summary.json` records `git_commit 2c7657cd70`, but `quant/`, `tests/`, `research/` and `output/` were untracked or modified at the start of this session, so the hash does not identify the code that produced the numbers. Commit or tag the audited tree.

## 7. Recommended fixes (priority order)

1. `fundamentals.Company.shares_wavg`: tighten the Q4-derived acceptance band to +-25% of FY (finding 1.3-1).
2. `DataContext.shares_on` / `market_cap`: reject any share count with mcap/assets outside [0.003, 100]; fall back to the previous snapshot's count when `_cover_reference` is NaN (LAMR, BRK-B, GRMN, FOXA, BKR); sum per-class counts for dual-class issuers (STZ, V, GEF, BRK-B, SPG).
3. `universe.CIK_OVERRIDES`: add `valid_to` to the LSI override; fix the Chubb ticker switch on 2016-01-15 in `sp500_rows_from_fja`.
4. `context._cut_splices`: blank only the splice day.
5. APA PP&E: use gross minus accumulated DD&A for the successful-efforts tags.
6. Disclose in the write-up that TC's 2012-13 universe is thinned by the `_next` guard and that QM/MF still use `_next` labels.
