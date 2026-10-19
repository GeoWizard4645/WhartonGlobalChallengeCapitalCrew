# Capital Crew quant research report

Wharton Global High School Investment Competition 2026-27. Three strategies from the team doc (quality-filtered momentum, Magic Formula, GICS trading comps) were researched, built into a point-in-time backtesting system (`quant/`), tested with a pre-registered train/test protocol, and audited four times (spec, backtest, data, live picks), plus a final re-audit of the fixes.

Run behind every number here: `output/summary.json` (final full re-run 2026-10-19, 04:10-04:16 UTC, after the re-audit fixes), git `2c7657cd70`, prices to 2026-10-16, backtests to 2026-09-30. Every table cites the file it was copied from. Where a table is "computed from" a CSV, it is a simple group-by of that CSV (nothing else was added).

## 0. Reading guide (plain English)

| term | meaning |
|---|---|
| net | after 10 bps (0.10%) trading cost on every buy and sell |
| train / test | the rules were chosen on **train** (start to 2018-12) and checked once per run on **test** (2019-01 to 2026-09, 93 months) |
| Sharpe | return above the T-bill rate per unit of volatility (annualised, from monthly returns). SPY's test Sharpe is 0.89 |
| CAGR / vol / MaxDD | compound annual return / annualised volatility / worst peak-to-trough fall (daily unless said otherwise) |
| EW-SP900 | the *same-universe control*: equal-weight S&P 500 + MidCap 400 (ex the strategy's excluded sectors), no signal. A strategy that cannot beat it has not shown skill, only that it holds stocks |
| FF5+MOM alpha (t) | yearly return left over after removing the five Fama-French factors (market, size, value, profitability, investment) and momentum. **t above 2 or below -2 means unlikely to be luck; between -2 and 2 means we cannot tell from zero** |
| IR | information ratio: yearly excess return over a benchmark divided by the yearly wobble of that excess |
| PBO | probability of backtest overfitting (CSCV, 12,870 splits): how often the best-in-half cell ranks below median in the other half. Below 50% is the ladder's pass line |
| DSR | deflated Sharpe ratio: chance the Sharpe is real after adjusting for how many variants were tried (the ledger count N). The ladder aims for above 0.5 |
| ladder | the 7-criterion evidence ladder (research/06 section 5.7): 5-7 passed = "works", 3-4 = "mixed", 0-2 = "does not work" (`quant/run_backtests.py:955`). "Does not work" means *we cannot claim it works*, not that it was proved useless |

## 1. Executive summary

**What we tested.** The three strategies exactly as far as the team doc specifies them, long-only, monthly signals, on the point-in-time S&P 900 (S&P 500 + MidCap 400). Fundamentals come from SEC filings and are used only after their filing date; index membership and GICS sectors are as of each date; trades happen one day after the signal; costs are 10 bps one way. Each strategy had a grid of the doc's own numbers written down before running (216, 18 and 54 cells). A plateau rule picked the setting on the train window; if the pick was not stable under bootstrap, the pre-registered fallback was the doc's default. The test window was then examined. Overfitting (PBO, DSR), factor regressions, costs, ablations, survivorship stress and short-horizon odds were all reported.

**Headline table** (chosen parameters; test window 2019-01 to 2026-09, net of costs).

| | Quality momentum | Magic Formula | Trading comps | Equal-weight blend of the 3 |
|---|---|---|---|---|
| Parameters used | doc default (fallback) | n=25, min cap $5B (plateau pick) | theta 10%, no size filter (plateau pick) | 1/3 each |
| **Test Sharpe** | **0.69** | **0.61** | **0.51** | **0.76** |
| **Test CAGR** | **20.0%** | **13.6%** | **13.0%** | **16.7%** |
| Test vol / MaxDD | 28.4% / -40.0% | 19.3% / -35.3% | 24.6% / -46.6% | 19.3% / -33.1% |
| SPY same window (Sharpe / CAGR) | 0.89 / 17.2% | 0.89 / 17.2% | 0.89 / 17.2% | 0.89 / 17.2% |
| EW-SP900 same window (Sharpe / CAGR) | 0.62 / 13.7% | 0.62 / 14.0% | 0.62 / 13.7% | 0.62 / 13.7% |
| **FF5+MOM alpha, full sample (t)** | 0.3% (0.07) | 0.6% (0.29) | -2.0% (-0.87) | -0.5% (-0.26) |
| FF5+MOM alpha, test window (t) | 3.8% (0.52) | -0.9% (-0.32) | -1.5% (-0.46) | 0.4% (0.14) |
| **PBO** (train) | **70.8%** | 30.1% | 32.1% | n/a |
| DSR (train, ledger N) | 0.649 (N=223) | 0.996 (N=38) | 0.663 (N=62) | n/a |
| Evidence ladder | 1/7: **does not work** | 4/7: **mixed** | 3/7: **mixed** | n/a |

Sources: `output/quality_momentum/results.md`, `output/magic_formula/results.md`, `output/trading_comps/results.md` (Test, Overfitting, Evidence ladder sections); `output/*/*_T2_factor_regressions.csv`; `output/blend/blend_qm_mf_tc_tearsheet.md`. MF's EW-SP900 control also excludes utilities, hence 14.0%. For comparison the doc's own TC setting (size filter on) has test Sharpe 0.47, test CAGR 11.9% and full-sample alpha -5.2% (t -2.41) (`trading_comps/results.md`, "default" rows).

**Honest verdict per strategy**

- **Quality momentum: does not work (1/7).** It earned 20.0% a year in the test window (SPY 17.2%) with a Sharpe of 0.69 (SPY 0.89, EW-SP900 0.62), at 28.4% volatility and a -40.0% drawdown (peak 2026-06-30, trough 2026-07-29; in July 2026 Ken French's winners decile fell 15.4% and the long-short momentum factor 22.7%, `output/academic/academic_evidence.md` A4). After removing factors its alpha is 0.3% a year (t 0.07) while its momentum loading is 0.70 (t 5.1): it is a momentum bet, not a source of extra return. Turnover is 784% a year (150 bps a year of costs). The stability check on its plateau failed (30% within one step) so the doc default was used, and PBO is 70.8%. It lost to SPY in three of four sub-periods and won in 2023-26 (+8.7%).
- **Magic Formula: mixed (4/7).** The most robust of the three (plateau stable, cheap at 64% turnover, PBO 30.1%, DSR 0.996, alpha not negative at 25 bps costs), but its test result equals the equal-weight universe (Sharpe 0.61 vs 0.62; CAGR 13.6% vs 14.0%) and trails SPY. It fails direction (information ratio vs EW is +0.15 on train, -0.07 on test), the survivorship stress (alpha survives only 56 bps a year of bias) and sub-periods (2 of 4). Best described as a sensible, cheap, rules-based value/quality tilt with no demonstrated recent edge.
- **Trading comps: mixed (3/7), and fragile.** The plateau rule now picks theta 10%, P/E cap 40, EV/EBITDA cap 35, **no size filter** (bootstrap stability 74% within one step, so no fallback). Test window: 13.0% a year, Sharpe 0.51 (EW-SP900 0.62, SPY 0.89); full-sample FF5+MOM alpha -2.0% a year (t -0.87, not distinguishable from zero). It still fails direction (IR vs EW -0.37 train, +0.05 test), costs (alpha -3.0% at 25 bps), the survivorship stress and sub-periods (0 of 4). The doc's own setting (size filter on) is clearly worse: train Sharpe 0.20, test 0.47, full-sample alpha -5.2% (t -2.41), the only significant alpha in the study, and it is negative. **Across runs the selection alternated between the doc default and theta 10%/no size filter as the data were corrected** (ladder 1/7 in some runs, 3/7 in others), and even now 13.8% of bootstrap resamples pick the doc default: the choice is fragile near the stability threshold, so quote it with that warning. No cell of the 54 beats SPY or RSP on Sharpe in either window, none beats EW-SP900 in train, and one (0.623 vs 0.619) does in test.
- **Blend: no better than the market.** Test Sharpe 0.76 / CAGR 16.7% against SPY 0.89 / 17.2%; alpha is +0.4% (t 0.14) in test and -0.5% (t -0.26) over the full sample. Diversification cut volatility (16.6% vs 23.5% for QM alone over 2012-2026), because QM is only 0.34-0.41 correlated with the other two, while MF and TC are 0.86 correlated.

**Main caveats** (details in sections 3 and 5).

1. **Survivorship**: yfinance has no delisted stocks. On average 81.0% of historical S&P 900 members have prices (63.2% at worst, 2011). The like-for-like bias proxy, EW-SP500 minus RSP, is +0.86% a year (EW-SP900 minus RSP +0.48%). A bias of that size would erase the (already insignificant) alpha of QM, whose break-even drag is 29 bps a year, and of MF (56 bps); neither survives the ladder's 150 bps stress, and TC's alpha is already negative (-2.0%) before any drag.
2. **Short test window**: 93 months. Test Sharpe 95% intervals are wide (QM [0.18, 1.24], MF [0.13, 1.16], TC [0.04, 1.16]; SPY [0.35, 1.59]), so the three are statistically indistinguishable from each other and from the control.
3. **Post-publication decay**: the long-history factor evidence (Ken French/AQR, 1927-2026) shows momentum, quality, "good and cheap" value and HML all weaker after publication; momentum's long-short Sharpe is 0.03 in 2009-2026 (0.62 before 1993).
4. **Not a pristine test**: the test window was looked at once per run but the ledger records 16 looks (QM 6, MF 5, TC 5) because data bugs were fixed in between; the selection rule never changed, but four times the chosen cell did (MF once, TC three times; section 2.0).
5. **Over 13 trading days nothing is provable**: P(beat SPY) is 47-50% for every strategy (section 6), so the competition is judged on process, which is what this report documents.
6. **Live picks need a human check**: the live-pick audit of the final 46 names blocked 4 (VAL a takeover target; HON and SOLV EBIT data errors; SON a TC pick that exists only because of a one-off gain) and flagged 18 more (see the Live-pick audit section).

**How to use this in the write-up.** (i) Present the strategies as a documented, tested *process* with an honest result, not as an edge. (ii) Quote the ladder verdicts and the numbers above, including the negative ones; judges reward articulation of strategy and reasoning (research/07 section 4). (iii) Do not claim that "our own backtest strengthens the case" (section 3.4).

---

## 2. The three strategies

### 2.0 Common protocol

| item | what was done | source |
|---|---|---|
| Universe | point-in-time S&P 900 (S&P 500 + MidCap 400). The S&P 600 was dropped because free S&P 600 history starts 2018-09 and would have added about 600 small caps exactly at the train/test boundary. The change was stamped before any grid run | `preregistration.json` (`restamp_reason`) in each strategy folder |
| Signals / trades | signal at the month-end close, trade at the next close (`EXEC_LAG_DAYS = 1`), costs 10 bps one way (robustness 0 / 25 / 50) | `quant/settings.py`, `quant/ARCHITECTURE.md` |
| Train / test | train = first usable month to 2018-12-31 (QM 95 months, MF 87, TC 83); test = 2019-01-01 to 2026-09-30 (93 months) | `results.md` |
| Selection metric | net Sharpe on train. Rule `plateau_v1`: score of a cell = mean minus 1.0 x standard deviation of its neighbourhood (cell plus one step along each axis); cells whose peak is more than 1.25x their neighbours' average are excluded; categorical choices are scored separately and the default is kept unless another category wins by 0.10 or more | `research/06` section 5.4; `preregistration.json` |
| Stability check | 500 stationary-bootstrap resamples of the train months (mean block 6); the rule's pick must stay within one grid step in at least 50% of resamples, otherwise **fall back to the literature (doc) default**; then one `confirm()` on test per run for the chosen cell, no re-selection | `results.md`, `changelog.md` |
| Overfitting | PBO via CSCV (S=16, 12,870 splits, plateau selector); DSR with N = number of distinct configurations in `output/ledger.csv` (QM 223, MF 38, TC 62; blend 323) | `results.md`, `blend_qm_mf_tc_tearsheet.md` |

**What happened across the test looks** (computed from `output/ledger.csv` "confirm (test look)" rows and the three `changelog.md` files; 16 looks in all; the QM (02:43 UTC) and MF (02:46) first-run looks were voided as provisional per the QM pre-registration notes):

| strategy | test looks | chosen cell, in run order |
|---|---|---|
| QM | 6 | the doc default every time (fallback each time) |
| MF | 5 | n=20, n=20, then **n=25** in the last three runs (after data fixes); $5B floor, staggered throughout |
| TC | 5 | doc default (train Sharpe 0.34, ladder 1/7), doc default, **theta 10% / no size filter** (train 0.53, ladder 3/7), **doc default** (plateau pick failed stability at 39% within one step; train 0.16, ladder 1/7), and in the **final run theta 10% / no size filter** (stability 74% within one step; train 0.55, test 0.51, ladder 3/7) |

Reading: the final-run numbers in this report are the ones to quote. **TC's selection alternated between the doc default and theta 10% / no size filter as the data were corrected**; in the final run the pick passes the stability bar (74% against 50% needed, 45% select exactly the cell, 13.8% of resamples still choose the doc default), so its choice is fragile near the stability threshold, and its ladder verdict moved between 1/7 and 3/7. QM and MF were stable across all runs apart from MF's n=20 to 25 (neighbours within 0.04 Sharpe). The data fixes (share counts, spin-off returns, negative debt, capex sign, GICS look-ahead, successor CIKs, bankruptcy splice, and finally the re-audit fixes: FY diluted-share band, market-cap/assets plausibility guard, LSI override end date) were data corrections, not changes of rule or grid, but a reviewer is right to note that the test numbers were visible while the data layer was debugged.

**Evidence ladder, all three strategies** (from each `results.md`, "Evidence ladder"; sub-periods are 2011-14, 2015-18, 2019-22, 2023-26):

| # | criterion | QM | MF | TC |
|---|---|---|---|---|
| 1 | direction: net IR vs EW-SP900 > 0 on train and test | NO (train -0.22, test 0.29) | NO (0.15, -0.07) | NO (-0.37, 0.05) |
| 2 | plateau passes eligibility and bootstrap stability | NO (30% within one step) | yes (90%) | yes (74%) |
| 3 | FF5+MOM alpha still > 0 at 25 bps one way | NO (-2.0%, t -0.48) | yes (0.4%, t 0.20) | NO (-3.0%, t -1.32) |
| 4 | factor view: alpha > 0 or explained by expected factors | yes (alpha 0.3%; Mom 0.70, t 5.1) | yes (alpha 0.6%; RMW 0.22, t 2.8) | yes (alpha -2.0%, t -0.87; HML 0.20, t 2.6) |
| 5 | PBO < 0.5 | NO (70.8%) | yes (30.1%) | yes (32.1%; DSR at N_hat 0.818) |
| 6 | alpha survives 150 bps/yr survivorship drag | NO (break-even 29 bps) | NO (56 bps) | NO (-197 bps) |
| 7 | positive active return vs SPY in at least 3 of 4 sub-periods | NO (1 of 4: -2.8%, -2.6%, -3.2%, +8.7%) | NO (2 of 4: 5.8%, -0.6%, 1.2%, -7.4%) | NO (0 of 4: -1.1%, -5.4%, -2.4%, -4.8%) |
| | passed | **1/7** | **4/7** | **3/7** |

---

### 2.1 Quality-filtered momentum (QM)

#### (a) Idea, exact rules, papers

**Idea.** Buy last year's winners, but only among financially healthy companies, in an uptrend that is not overheated.

**Rules as implemented** (`output/audit/spec_audit.md` rows QM-01 to QM-19, `research/01`, `research/02`):

1. **Universe and timing.** Point-in-time S&P 900 ex GICS Financials and Real Estate; raw price at least $5; at least 253 trading days of history. Signal at the last trading day of each month.
2. **12-1 momentum.** `MOM = P[t-21] / P[t-252] - 1`, adjusted closes, trading-day offsets (skips the most recent month to avoid short-term reversal); at least 90% of days must be valid.
3. **Order of filters ("MF" order).** Take the top 20% of the eligible universe by 12-1 momentum, then apply quality, then trend, then rank the survivors by momentum and hold the top N at equal weight 1/N. If fewer than N survive, the rest stays in cash (never back-filled).
4. **Quality rule Q3a** (the doc's "high gross margin or ROE, low debt, positive earnings"): TTM net income to parent > 0 AND total debt / book equity <= 1.0 AND (gross margin >= its GICS-industry median OR ROE >= its GICS-industry median).
5. **200-day moving average.** `close > SMA200`, mean of the last 200 closes including today.
6. **Wilder RSI(14) between 50 and 70.** Changes `c_i = close_i - close_{i-1}`; gains and losses averaged with Wilder smoothing (`avg_i = (13 x avg_{i-1} + x_i) / 14`, seeded with a simple 14-day mean); `RSI = 100 - 100/(1 + avg_gain/avg_loss)`; bounds inclusive. Checked against an independent implementation: identical.
7. **Optional layers (grid axes).** Stop-loss 10% or 15% below the rebalance price, checked daily on closes (proceeds to cash until next rebalance); volatility scaling `w = min(1, 20% / sigma_hat)` with sigma_hat the annualised 126-day uncentered volatility of the back-cast target book, remainder in T-bills (no leverage).

**Papers behind it.**

| paper | what it contributes | link |
|---|---|---|
| Jegadeesh & Titman (1993) | winners over 3-12 months keep winning; 12-1 convention | https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf |
| Novy-Marx (2013) "The Other Side of Value" | gross profits / assets predicts returns | https://www.sciencedirect.com/science/article/abs/pii/S0304405X13000044 |
| Asness, Frazzini & Pedersen "Quality Minus Junk" (2019) | high-quality stocks beat low-quality | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2312432 |
| Daniel & Moskowitz (2016) "Momentum Crashes" | crashes happen in rebounds after market falls, mostly via the loser leg | https://www.sciencedirect.com/science/article/pii/S0304405X16301490 |
| Barroso & Santa-Clara (2015) "Momentum Has Its Moments" | volatility-scaling roughly doubles long-short Sharpe | https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2041429 |
| Faber (2007); Han, Zhou & Zhu (SSRN 2407199) | 10-month/200-day trend rule (evidence is for indices, not single stocks); stop-loss on long-short momentum (long-only evidence thin) | https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2407199 |

Honesty notes from the research files: the doc's exact quality sketch is only partly supported (gross margin alone earned no premium, ROE added nothing once gross profits/assets was in, "low debt" and "ND/EBITDA < 3" are heuristics) and the RSI 50-70 band is a practitioner rule with no primary paper (`research/01` section 6.1, `research/02` section 0). No verified paper shows a hard quality filter helps *long-only* momentum.

#### (b) How the doc's rules were interpreted (spec audit, INTERPRETED rows)

| doc rule | implemented as | consequence |
|---|---|---|
| "high gross margins or ROE" | at or above the median of the name's GICS industry (falls back to industry group or sector if fewer than 10 firms) | about 25% of names have no gross margin and can pass only via ROE |
| "low debt" | debt (no operating leases) / book equity <= 1.0; equity <= 0 or unmapped debt = fail | X fixed at 1.0 (spec grid 0.5/1/2 not run); 5-7% of names have no mapped debt |
| "rank what is left" | momentum shortlist of the top 20% first (spec said top 10% or top 40), then filters | shortlist not in the grid |
| "trend-break exit" | re-screen at month-end; daily 200-DMA exit only as a robustness run | |
| "volatility-scaled momentum" | long-only own-book version, 20% target, cap 100% | "scale up when low" only restores full exposure |
| "top 5-10" | grid N = 5, 10, 20 | N=20 is outside the doc, a diversification neighbour |
| execution | signal at close, trade at next **close** (research said open); $25 per trade not modelled | small |
| missing data | cannot pass | the gross-profit arm Q1-50 passes about 37% of names, not 50% |

Audit status: 11 EXACT, 8 INTERPRETED, 2 MISSING (research extras, pending-M&A exclusion), 2 WRONG (stale pre-registration text, since corrected: the file now says S&P 900 and carries a `notes_on_timeline` disclosure; CFOA capex sign, low, only the Q2-Q50 arm, fixed per `changelog.md`) out of 23 rows (`output/audit/spec_audit.md`).

#### (c) Pre-registered grid and selection

Grid (`preregistration.json`): **216 cells = 4 quality rules x 3 technical sets x 2 volatility targets x 3 stop-loss levels x 3 N**.

| axis | levels |
|---|---|
| quality | Q0 (none), Q3a (doc), Q1-50 (gross profit/assets in top half), Q2-Q50 (composite quality score in top half) |
| technical | none; 200-DMA only; 200-DMA + RSI 50-70 (doc) |
| vol target | none; 20% |
| stop-loss | none; 15%; 10% |
| N | 5; 10; 20 |
| fixed | order=MF, shortlist 20%, debt/equity cap 1.0 |

**Selection result** (`output/quality_momentum/results.md`). The plateau rule's own pick was the no-trend, no-vol-target gross-profit family (category plateau score 0.73 against 0.48 for the doc's family), **but the bootstrap stability check failed** (18% select exactly that cell, 30% within one step, need 50%), so the pre-registered fallback applied: **the doc default** `N=10, quality=Q3a, technical=sma_rsi, no stop-loss, no vol target`. Train Sharpe 0.53 (bootstrap sensitivity picks: argmax Sharpe 0.81 and lambda-0 Sharpe 0.80, both more than one step away). Test confirmation: Sharpe 0.69, 66th percentile of the 216 cells; Spearman(train Sharpe, test Sharpe) across cells = 0.36; test/train = 1.32.

#### (d) Results

**Net results, chosen = default** (`results.md`; MaxDD daily).

| window | series | months | CAGR | vol | Sharpe | MaxDD | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|---|
| Train 2011-02..2018-12 | **QM** | 95 | 8.0% | 16.4% | 0.53 | -33.0% | -3.0% (-0.76) |
| | SPY | 95 | 11.0% | 11.4% | 0.93 | -19.3% | -0.3% (-1.27) |
| | RSP | 95 | 10.1% | 12.4% | 0.80 | -22.9% | -0.5% (-0.70) |
| | EW-SP900 | 95 | 11.3% | 13.1% | 0.85 | -23.3% | 0.3% (0.36) |
| Test 2019-01..2026-09 | **QM** | 93 | 20.0% | 28.4% | 0.69 | -40.0% | 3.8% (0.52) |
| | SPY | 93 | 17.2% | 16.4% | 0.89 | -33.7% | -0.1% (-0.34) |
| | RSP | 93 | 13.1% | 17.9% | 0.63 | -39.0% | -2.0% (-1.70) |
| | EW-SP900 | 93 | 13.7% | 19.4% | 0.62 | -40.1% | -1.9% (-1.45) |
| Full 2011-02..2026-09 | **QM** | 188 | 13.8% | 23.2% | 0.61 | -40.0% | 0.3% (0.07) |
| | SPY | 188 | 14.0% | 14.1% | 0.90 | -33.7% | -0.2% (-0.88) |
| | RSP | 188 | 11.6% | 15.4% | 0.69 | -39.0% | -1.1% (-1.48) |
| | EW-SP900 | 188 | 12.5% | 16.5% | 0.70 | -40.1% | -0.7% (-0.84) |
| Last 36 months | **QM** | 36 | 36.7% | 37.1% | 0.92 | -40.0% | 5.6% (0.36) |
| | SPY | 36 | 22.8% | 12.4% | 1.37 | -18.8% | |

Test-window details (`quality_momentum_chosen_tearsheet.md`): Sharpe 95% CI [0.18, 1.24]; beta vs SPY 0.87; tracking error vs SPY 24.7%; IR vs SPY 0.21, vs EW-SP900 0.29; down-capture 61%; annual one-way turnover 795%; cost drag 181 bps a year (full sample 784% and 150 bps, `summary.json`). Average 9.7 holdings and 2.7% in cash.

**Factor regression, full sample** (`quality_momentum_chosen_T2_factor_regressions.csv`, n=187 months to 2026-08, Newey-West t in brackets).

| window | alpha (ann %) | Mkt-RF | SMB | HML | RMW | CMA | Mom | R2 |
|---|---|---|---|---|---|---|---|---|
| Full | 0.29 (0.07) | 1.02 (12.1) | 0.19 (1.2) | 0.03 (0.2) | -0.56 (-1.9) | 0.07 (0.2) | **0.70 (5.1)** | 0.53 |
| Train | -3.02 (-0.76) | 0.95 (7.8) | 0.48 (2.8) | 0.08 (0.4) | 0.24 (0.9) | -0.52 (-1.6) | 0.33 (3.2) | 0.63 |
| Test | 3.84 (0.52) | 1.08 (11.1) | 0.16 (0.6) | 0.06 (0.2) | -0.72 (-2.3) | 0.16 (0.4) | 0.83 (4.6) | 0.54 |

Reading: strong, significant momentum exposure (it is a momentum strategy), no significant alpha, and a *negative* profitability (RMW) loading in the test window, i.e. the "quality" filter did not make it look like a quality portfolio.

**Overfitting** (`results.md`).

| diagnostic | train | full sample |
|---|---|---|
| t-stat of mean excess return | 1.48 | 2.41 |
| PSR(0) | 0.920 | 0.990 |
| DSR, N = 223 (ledger) | 0.649 | 0.848 |
| DSR, N_hat (effective trials) | 0.728 (39.61) | 0.903 (41.79) |
| Expected max Sharpe of N null trials | 0.38 | 0.34 |
| Years needed for PSR(0) >= 95% | 10.79 | 7.98 |
| **PBO (CSCV)** | **70.8%** | |
| P(out-of-sample Sharpe < 0) of the pick | 15.3% | |
| degradation slope (negative = overfit) | -0.75 | |

**Robustness** (`results.md`; each run is a ledger trial).

| run | full CAGR | full Sharpe | train Sh. | test Sh. | test CAGR | MaxDD | turnover/yr | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|---|---|
| chosen (10 bps) | 13.8% | 0.61 | 0.53 | 0.69 | 20.0% | -40.0% | 784% | 0.3% (0.07) |
| cost 0 bps | 15.5% | 0.67 | 0.62 | 0.74 | 21.8% | -39.9% | 784% | 1.8% (0.43) |
| cost 25 bps | 11.3% | 0.51 | 0.39 | 0.61 | 17.3% | -40.1% | 784% | -2.0% (-0.48) |
| cost 50 bps | 7.2% | 0.35 | 0.16 | 0.48 | 13.0% | -42.0% | 784% | -5.7% (-1.39) |
| quality arm Q4-0.25 (soft blend) | 11.9% | 0.56 | 0.65 | 0.52 | 13.6% | -37.4% | 753% | -3.1% (-1.06) |
| quality arm Q4-0.5 (soft blend) | 10.8% | 0.55 | 0.70 | 0.46 | 11.0% | -34.1% | 736% | -4.0% (-1.65) |
| order QF (quality first) | 15.0% | 0.65 | 0.57 | 0.74 | 21.6% | -40.0% | 783% | 1.0% (0.23) |
| daily 200-DMA exit | 10.1% | 0.46 | 0.37 | 0.54 | 15.0% | -42.2% | 909% | -3.0% (-0.70) |

Costs matter: the edge is gone at 25 bps. Survivorship stress: break-even drag 29 bps a year; at 150 bps the alpha is -1.21% (t -0.30).

**Regression of Sharpe on the grid parameters** (train, 216 cells, R2 = 0.72; bootstrap SD resamples months jointly; `results.md`). A flat surface is good news.

| term | coef | bootstrap SD | coef/SD |
|---|---|---|---|
| const | 0.444 | 0.358 | 1.2 |
| N | 0.007 | 0.061 | 0.1 |
| **stop_loss** | **-0.106** | 0.047 | **-2.3** |
| N^2 | 0.048 | 0.032 | 1.5 |
| stop_loss^2 | -0.005 | 0.059 | -0.1 |
| N x stop_loss | -0.009 | 0.018 | -0.5 |
| technical = sma | 0.023 | 0.021 | 1.1 |
| technical = sma_rsi | -0.043 | 0.149 | -0.3 |
| vol_target = none | -0.006 | 0.025 | -0.2 |
| quality = Q1-50 | 0.159 | 0.152 | 1.0 |
| quality = Q2-Q50 | -0.007 | 0.124 | -0.1 |
| quality = Q3a | 0.018 | 0.159 | 0.1 |

Only the stop-loss term is more than two bootstrap SDs from zero, and it is negative (tighter stops lowered Sharpe).

**Figures** (heat maps print the numbers; surfaces are interpolated visualisations, grid points marked, not extra results).

![QM growth of $1](quality_momentum/quality_momentum_chosen_C1_growth.png)
![QM train heat maps, all 216 cells](quality_momentum/grid_all/quality_momentum_train_all_C6_heatmap_overview.png)
![QM test heat maps, all 216 cells](quality_momentum/grid_all/quality_momentum_test_all_C6_heatmap_overview.png)
![QM train surface (N x stop-loss, doc technical/quality)](quality_momentum/quality_momentum_train_C6_surface_technical_sma_rsi_vol_target_none_quality_q3a.png)

#### (e) What the backtest says about the doc's own numbers

Mean net Sharpe and CAGR over all grid cells at each level (computed from `grid_metrics_train.csv` and `grid_metrics_test.csv`; 72, 108 or 54 cells per level). Reference: SPY train 0.93 / 11.0%, test 0.89 / 17.2%; EW-SP900 train 0.85 / 11.3%, test 0.62 / 13.7%.

| parameter | level | train Sharpe | test Sharpe | train CAGR | test CAGR |
|---|---|---|---|---|---|
| **200-DMA / RSI** | none | 0.512 | **0.702** | 8.5% | 19.2% |
| | 200-DMA only | 0.535 | 0.643 | 8.8% | 17.3% |
| | **200-DMA + RSI 50-70 (doc)** | 0.469 | 0.517 | 7.1% | 12.8% |
| **stop-loss** | none | **0.610** | **0.694** | 10.0% | 19.0% |
| | 15% | 0.509 | 0.630 | 8.3% | 16.7% |
| | 10% | 0.398 | 0.538 | 6.1% | 13.6% |
| **holdings N** | 5 | 0.514 | 0.639 | 9.2% | 18.5% |
| | **10 (doc 5-10)** | 0.473 | 0.667 | 7.6% | 17.4% |
| | 20 | 0.529 | 0.556 | 7.6% | 13.4% |
| **quality rule** | none (Q0) | 0.463 | **0.708** | 7.6% | 19.2% |
| | **Q3a (doc)** | 0.481 | 0.626 | 7.6% | 16.6% |
| | gross profit/assets top half (Q1-50) | **0.622** | 0.632 | 10.5% | 17.1% |
| | composite quality top half (Q2-Q50) | 0.456 | 0.516 | 6.8% | 12.7% |
| **vol target** | none | 0.503 | 0.655 | 8.4% | 20.2% |
| | 20% | 0.508 | 0.586 | 7.8% | 12.7% |

Plain reading, with the grid-wide caveat that cell differences of a few hundredths of Sharpe are noise (a Sharpe estimated on 7-8 years has a standard error of roughly 0.36, `research/04` section 0):

- **Stop-loss hurt in both windows** and consistently across levels (none > 15% > 10%). The doc's "stop-loss or trend-break exit helps" is not supported here.
- **The RSI 50-70 band hurt**: lowest mean Sharpe in both windows (0.469 train, 0.517 test), and the doc default `sma_rsi` is the worst technical set in test. The plain 200-DMA was neutral to slightly positive in train and below "none" in test.
- **The quality filter did not help out of sample**: no filter had the best mean test Sharpe (0.708 vs 0.626 for the doc's Q3a). In train the gross-profit-over-assets arm (the Novy-Marx variable) was clearly best (0.622) but its test advantage vanished (0.632). This matches the literature: gross profits/assets is the research-backed quality variable, "gross margin or ROE" is not.
- **Number of holdings** had no consistent pattern (5, 10 and 20 within 0.06 of each other in train; 20 worst in test).
- **Volatility scaling** did nothing in train and cost Sharpe in test, because the test window rewarded staying fully invested.
- Across all 216 cells, **no cell beat SPY's Sharpe in train and only 3 of 216 did in test**; 121 of 216 beat EW-SP900 in test, none in train (computed from the grid CSVs and `summary.json`).

### 2.2 Magic Formula (MF)

#### (a) Idea, exact rules, papers

**Idea.** Joel Greenblatt's Magic Formula: rank stocks on how good the business is (return on capital) and how cheap it is (earnings yield), add the ranks, buy the best 20-30, hold about a year.

**Rules as implemented** (`output/audit/spec_audit.md` rows MF-01 to MF-19, `research/03` section 2.2):

1. **Universe.** Point-in-time S&P 900 ex GICS Financials, Real Estate and Utilities; raw price at least $5; market cap at least a floor (grid: $50M, $1B, $5B); latest filing at most 200 days old.
2. **EBIT** = trailing-twelve-month operating income (fallback: pretax income + interest expense; 3.8 of 30 picks a month on average carry that proxy flag).
3. **ROC = EBIT / (net working capital + net fixed assets)**, with `NWC = (current assets - excess cash) - (current liabilities - current debt - current operating-lease liability)` floored at 0, `NFA` = net PP&E, and capital floored at 1% of total assets. Greenblatt's "excess cash" rule is undisclosed; ours is `excess cash = max(0, min(cash + short-term investments, current assets - current liabilities))`.
4. **EY = EBIT / EV**, `EV = market cap + debt (incl. finance leases, no operating leases) + preferred + max(0, minority interest) - excess cash`.
5. **Eligible only if** EBIT > 0, EV > 0, capital > 0, a classified balance sheet exists and debt is mapped (every missing value fails closed).
6. **Rank** ROC (1 = best) and EY (1 = best) among eligible names, add the two ranks, take the N lowest sums (ties: higher EY, then larger market cap), equal weight.
7. **Holding.** 12 monthly sleeves, each held 12 monthly signals ("staggered", the Jegadeesh-Titman overlap view); the "annual" variant is the average of the 12 start-month portfolios.

**Papers behind it.**

| source | what it contributes | link |
|---|---|---|
| Greenblatt, *The Little Book That Beats the Market* (2005; 2010 ed.) | the formula; reports 30.8%/yr vs 12.4% S&P 1988-2004 (largest 3,500), 22.9%/yr for the largest 1,000, before costs and taxes | https://www.magicformulainvesting.com/Home/HowItWorks |
| Persson & Selander (2009), Nordic backtest | independent replication | https://arc.hhs.se/download.aspx?MediumId=769 |
| Gray & Vogel (2012), "Analyzing Valuation Measures" | EBIT/EV is a strong single value metric | https://alphaarchitect.com/wp-content/uploads/2022/11/AAJPMFall12AnalyzingValuationMeasures.pdf |
| Kreft (2022), Erasmus thesis | significant alpha to 2009, none in 2010-2021 | https://thesis.eur.nl/pub/65582/MasterThesis_MartijnKreft_474788.pdf |
| Martin (2020) | roughly index-like returns after 2010 | https://reasonabledeviations.com/2020/06/08/greenblatt-magic-formula/ |
| Schwartz & Hanauer (2024) via Quantpedia | positive but decayed effect, large relative drawdowns 2018-2020 | https://quantpedia.com/out-of-sample-test-of-formula-investing-strategies/ |

From `research/03` section 1: we can only test 2011 onward, which is entirely post-publication; independent replications give smaller numbers than Greenblatt's; "be honest in the write-up: it has probably not delivered 20-30%/yr since publication". Also correct the team doc: the "EBITDA/TEV" headline in Gray & Vogel is EBITDA, not EBIT (`research/03` section 1 point 6), and the doc's "<50 million" is a typo for "exclude below $50 million".

#### (b) How the doc's rules were interpreted (spec audit, INTERPRETED rows)

| doc rule | implemented as | consequence |
|---|---|---|
| "no micro caps (HAS TO BE <50 million)" | exclude names **below** the floor (the typo read the sensible way); floor is a grid axis | the $50M tier never binds inside the S&P 900; effective floors tested are $1B and $5B |
| "hold 20-30 stocks" | N per monthly cohort | the 12-cohort staggered book holds on average **47.6 distinct names** (chosen) and 56.9 (default); the "annual" variant about N (`summary.json` turnover.avg_holdings) |
| "hold about a year, buy 5-7 every 2-3 months" | 12 monthly sleeves of N/12 weight | sleeves re-equalised at every signal; tax timing not modelled |
| "no financials, utilities" | plus Real Estate (lead decision) | |
| missing PP&E tag | fixed assets = assets - current assets - goodwill - intangibles (upper bound) | conservative, can only lower ROC |
| "market cap = price x shares" | split-consistent, filings-based share counts | fixed after the audit found wrong counts for about 1% of names per date |
| core grid 36 cells (spec) | 18 cells (N x floor x holding); ranking choices (MF / EY-only / ROC-only) moved to ablations | |

Audit status: 9 EXACT, 6 INTERPRETED, 3 MISSING (research robustness list, dollar-volume filter, sanity checks), 1 WRONG (share counts, fixed per `changelog.md`) out of 19 rows.

#### (c) Pre-registered grid and selection

Grid (`preregistration.json`): **18 cells = N {20, 25, 30} x market-cap floor {$50M, $1B, $5B} x holding {staggered, annual}**. Fixed: MF ranking, S&P 900, 10 bps, excess-cash convention, operating-income EBIT, 12-month holding, $5 price floor.

**Selection result** (`results.md`). The plateau rule picked **N=25, floor $5B, staggered** (plateau score 1.070, peak ratio 1.02, plateau width 7 cells). Bootstrap stability passed (35% select exactly this cell, 90% within one step), so no fallback. Train Sharpe 1.13 against 1.02 for the doc default (N=30, $1B). Neighbours: N=20 1.15, N=30 1.13, floor $1B 1.04. Staggered (1.07) vs annual (1.08): within the 0.10 margin, default category kept. **Test confirmation: Sharpe 0.61 vs 0.63 for the default and 0.63 for the grid median; rank 17th percentile of the 18 cells; Spearman(train, test) = -0.81; test/train Sharpe 0.54.** Two of the four confirmation criteria failed (landscape did not persist; did not beat the grid median). In plain words: the pick was stable in train but did not carry any advantage into test, and the whole 18-cell grid collapsed to a narrow band of test Sharpes (0.607 to 0.631).

#### (d) Results

**Net results** (`results.md`; MaxDD daily).

| window | series | months | CAGR | vol | Sharpe | MaxDD | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|---|
| Train 2011-10..2018-12 | **MF chosen** | 87 | 16.4% | 13.9% | 1.13 | -25.6% | 1.5% (0.78) |
| | MF default | 87 | 15.7% | 14.9% | 1.02 | -26.4% | 1.1% (0.56) |
| | SPY | 87 | 13.8% | 11.1% | 1.18 | -19.3% | -0.3% (-1.48) |
| | RSP | 87 | 13.3% | 11.9% | 1.07 | -19.8% | -0.3% (-0.45) |
| | EW-SP900 | 87 | 15.5% | 14.2% | 1.05 | -22.7% | 0.4% (0.41) |
| Test 2019-01..2026-09 | **MF chosen** | 93 | 13.6% | 19.3% | 0.61 | -35.3% | -0.9% (-0.32) |
| | MF default | 93 | 14.4% | 20.2% | 0.63 | -37.7% | 0.0% (0.01) |
| | SPY | 93 | 17.2% | 16.4% | 0.89 | -33.7% | -0.1% (-0.34) |
| | RSP | 93 | 13.1% | 17.9% | 0.63 | -39.0% | -2.0% (-1.70) |
| | EW-SP900 | 93 | 14.0% | 20.1% | 0.62 | -40.5% | -1.9% (-1.37) |
| Full 2011-10..2026-09 | **MF chosen** | 180 | 14.9% | 16.9% | 0.81 | -35.3% | 0.6% (0.29) |
| | MF default | 180 | 15.0% | 17.8% | 0.78 | -37.7% | 0.8% (0.46) |
| | SPY | 180 | 15.6% | 14.0% | 0.99 | -33.7% | -0.2% (-0.95) |
| | RSP | 180 | 13.2% | 15.3% | 0.78 | -39.0% | -1.1% (-1.43) |
| | EW-SP900 | 180 | 14.7% | 17.5% | 0.78 | -40.5% | -0.6% (-0.74) |

Turnover is 64% a year (costs 12 bps a year); test-window Sharpe 95% CI [0.13, 1.16] (`magic_formula_chosen_tearsheet.md`).

**Factor regression** (`magic_formula_chosen_T2_factor_regressions.csv`, t in brackets).

| window | alpha (ann %) | Mkt-RF | SMB | HML | RMW | CMA | Mom | R2 |
|---|---|---|---|---|---|---|---|---|
| Full (n=179) | 0.56 (0.29) | 0.99 (16.5) | 0.15 (2.3) | 0.05 (0.6) | **0.22 (2.8)** | 0.15 (1.4) | **-0.12 (-2.1)** | 0.84 |
| Train | 1.46 (0.78) | 1.08 (12.6) | 0.20 (2.0) | -0.06 (-0.5) | 0.37 (2.3) | -0.02 (-0.2) | -0.07 (-1.2) | 0.85 |
| Test | -0.91 (-0.32) | 0.95 (13.2) | 0.07 (0.8) | 0.10 (0.9) | 0.13 (1.5) | 0.22 (1.6) | -0.21 (-2.8) | 0.85 |

Reading: it behaves like the market with a modest profitability (RMW) tilt and a negative momentum loading, which is what a "profitable and cheap" screen should look like; no alpha beyond that.

**Overfitting** (`results.md`).

| diagnostic | train | full sample |
|---|---|---|
| t-stat of mean excess return | 3.03 | 3.15 |
| PSR(0) | 0.999 | 0.999 |
| DSR, N = 38 (ledger) | 0.996 | 0.998 |
| DSR, N_hat (effective trials) | 0.999 (1.20) | 0.999 (1.16) |
| Bonferroni-haircut Sharpe (haircut) | 0.63 (44%) | 0.48 (41%) |
| Years needed for PSR(0) >= 95% | 2.28 | 4.25 |
| **PBO (CSCV)** | **30.1%** | |
| P(out-of-sample Sharpe < 0) of the pick | 0.6% | |
| degradation slope | -0.91 | |

Caution: the 18 cells are near-copies of one strategy (N_hat about 1), so a high DSR reflects a strong train Sharpe, not many independent confirmations; test/train fell to 0.54.

**Robustness** (`results.md`).

| run | full CAGR | full Sharpe | train Sh. | test Sh. | test CAGR | MaxDD | turnover | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|---|---|
| chosen (10 bps) | 14.9% | 0.81 | 1.13 | 0.61 | 13.6% | -35.3% | 64% | 0.6% (0.29) |
| cost 25 bps | 14.7% | 0.80 | 1.12 | 0.60 | 13.4% | -35.3% | 64% | 0.4% (0.20) |
| cost 50 bps | 14.4% | 0.78 | 1.10 | 0.59 | 13.0% | -35.3% | 64% | 0.1% (0.05) |
| EY only (cheapness leg) | 11.5% | 0.54 | 0.76 | 0.42 | 10.7% | -53.1% | 68% | -2.2% (-0.87) |
| ROC only (quality leg) | 14.5% | 0.82 | 1.32 | 0.52 | 11.3% | -34.6% | 43% | 0.5% (0.24) |
| gross profit/assets instead of ROC | 13.9% | 0.71 | 0.92 | 0.61 | 14.6% | -42.8% | 59% | -1.2% (-0.63) |
| all US stocks instead of S&P 900 | 13.3% | 0.72 | 1.09 | 0.49 | 11.1% | -36.0% | 67% | -0.7% (-0.40) |
| all cash counted as excess | 14.8% | 0.81 | 1.15 | 0.60 | 13.1% | -34.5% | 62% | 0.6% (0.30) |
| EBIT = pretax + interest | 15.4% | 0.85 | 1.14 | 0.66 | 14.3% | -33.9% | 65% | 1.0% (0.52) |

(An S&P 1500 universe gives almost the same result as the S&P 900, 14.8% and Sharpe 0.81: S&P 600 membership only exists from 2018-09 and, presumably, few S&P 600 names clear the $5B floor; cost 0 bps gives Sharpe 0.82.) MF is almost cost-insensitive; the combination matters: EY-only is clearly worse than the full formula here, ROC-only matches it overall but is worse in test. Survivorship stress: break-even drag 56 bps a year; at 150 bps alpha is -0.94% (t -0.50).

**Regression of Sharpe on the grid parameters** (train, 18 cells, R2 = 0.99; `results.md`).

| term | coef | bootstrap SD | coef/SD |
|---|---|---|---|
| const | 1.046 | 0.380 | 2.8 |
| n | -0.019 | 0.022 | -0.8 |
| min_cap | 0.063 | 0.032 | 2.0 |
| n^2 | 0.012 | 0.008 | 1.6 |
| min_cap^2 | 0.030 | 0.030 | 1.0 |
| n x min_cap | 0.005 | 0.010 | 0.5 |
| holding = staggered | -0.010 | 0.012 | -0.8 |

Only the market-cap floor shows a train effect (higher floor, higher Sharpe); it does not reappear in test.

**Figures.**

![MF train heat maps](magic_formula/magic_formula_train_C6_heatmap_overview.png)
![MF test heat maps](magic_formula/magic_formula_test_C6_heatmap_overview.png)
![MF train surface (N x floor, staggered)](magic_formula/magic_formula_train_C6_surface_holding_staggered.png)

#### (e) What the backtest says about the doc's own numbers

Mean net Sharpe and CAGR over the cells at each level (computed from `grid_metrics_train.csv` and `grid_metrics_test.csv`; 6 or 9 cells per level). Reference: SPY train 1.18, test 0.89; EW-SP900 train 1.05, test 0.62.

| parameter | level | train Sharpe | test Sharpe | train CAGR | test CAGR |
|---|---|---|---|---|---|
| **holdings N** (doc 20-30) | 20 | 1.092 | 0.615 | 16.2% | 14.0% |
| | 25 | 1.062 | 0.625 | 15.8% | 14.1% |
| | 30 | 1.055 | 0.630 | 15.7% | 14.2% |
| **market-cap floor** (doc: exclude micro caps) | $50M | 1.017 | 0.627 | 15.5% | 14.4% |
| | $1B | 1.049 | 0.626 | 15.9% | 14.3% |
| | $5B | **1.143** | 0.616 | 16.5% | 13.6% |
| **holding** | staggered | 1.065 | 0.623 | 15.9% | 14.1% |
| | annual (~1 year, one start month) | 1.075 | 0.623 | 16.0% | 14.1% |

- **N between 20 and 30 does not matter** (train spread 0.04, test spread 0.015). The doc's range is fine; pick it for diversification, not performance. Note the staggered book holds roughly 48-57 names.
- **A higher size floor looked better in train (1.14 vs 1.02-1.05) and slightly worse in test (0.616 vs 0.626-0.627)**: the pattern did not persist (Spearman -0.81). The $50M floor never binds in the S&P 900.
- **Staggered vs annual holding is a wash**, as it should be.
- Over 18 cells the test Sharpes sit between 0.607 and 0.631, i.e. all about equal to EW-SP900 (0.617); 14 of 18 are numerically above it and none is above SPY (0.889).

### 2.3 Trading comps with GICS peers (TC)

#### (a) Idea, exact rules, papers

**Idea.** Value each stock against its industry peers: buy when it trades at a discount of at least `theta` to the peer median on both P/E and EV/EBITDA, and only if it passes balance-sheet and quality checks.

**Rules as implemented** (`output/audit/spec_audit.md` rows TC-01 to TC-21 and KM-01 to KM-08, `research/04` section 5):

1. **Universe.** Point-in-time S&P 900 ex Financials and Real Estate; market cap at least $300M; raw price at least $5; peers drawn from the same universe.
2. **Multiples (trailing twelve months).** `P/E = market cap / TTM net income to parent`; `EV/EBITDA = EV / TTM EBITDA`, `EV = market cap + debt (incl. finance leases) + preferred + minority interest - (cash + short-term investments)`, `EBITDA = operating income + D&A`. Zero or negative values are ignored (never set to 0). A company (peer or target) with P/E above the P/E cap or EV/EBITDA above the EV cap is invalid for that multiple. Missing or stale data (period end more than 135 days old) drops a peer. Recent IPOs (listing age under 730 days) and mergers (acquisitions at least 10% of prior assets, or share count change at least 25%, or assets up 40% with an 8-K item 2.01) are excluded.
3. **Peers.** Same 8-digit GICS sub-industry as of the date. *Size filter on*: peers with market cap 0.5x to 2x the target's, closest 5, at least 4 needed; if fewer than 4, widen to the 6-digit GICS industry under the same rule. *Size filter off*: all valid sub-industry peers (at least 4, no upper cap).
4. **Outlier trim.** Keep peers whose multiple is within 0.5x to 2x of the peers' median (at least 3 kept); benchmark = median of the kept.
5. **Signal.** BUY if the target's multiple `< (1 - theta) x benchmark` for **both** P/E and EV/EBITDA (theta = 0.15 is the doc's "0.85x the median"); score = average of the two discounts.
6. **Key-metric gates, on the target only.** Net debt / EBITDA at most 3 (EBITDA must be positive); free cash flow positive (`CFO - |capex|` > 0 TTM and in at least 2 of the last 3 fiscal years) and operating margin stable or improving (OLS slope at least -0.5 percentage points a year over 4 fiscal years, TTM margin at least the latest year's minus 1 point, TTM margin positive); ROIC above WACC (NOPAT / average invested capital vs WACC with Blume-adjusted 104-week beta, 5% equity premium, 10-year Treasury).
7. **Portfolio.** Top 20 by average discount, weight `1/max(k, 5)`, monthly. This part is not in the doc.

**Papers behind it** (with the corrections `research/04` section 1 asks us to make).

| source | what it supports / what to fix in the doc | link |
|---|---|---|
| Alford (1992), JAR | industry-matched peers value stocks better; narrower industry is better; size and ROE add nothing beyond industry. (The doc says expanding to the wider level is better; the fallback is a compromise, not an accuracy gain.) | https://ideas.repec.org/a/bla/joares/v30y1992i1p94-108.html |
| Liu, Nissim & Thomas (2002), JAR | multiples accuracy; **this is the paper the doc calls "Nissim & Thomas (2002)"; it does not use TTM and finds forward earnings multiples most accurate** | https://business.columbia.edu/sites/default/files-efs/pubfiles/318/Equity_Valuation_Using_Multiples.pdf |
| Knudsen, Kold & Plenborg (2017), FAJ | documented TTM implementation on the S&P 1500; cite this for TTM | http://gregmccall.s3.amazonaws.com/Stick+to+the+Fundamentals+and+Discover+Your+Peers.pdf |
| Bhojraj, Lee & Oler (2003); Chan, Lakonishok & Swaminathan (2007) | GICS is the best-validated industry classification for peers | https://ideas.repec.org/a/bla/joares/v41y2003i5p745-774.html ; https://www.lsvasset.com/pdf/research-papers/industry_FAJ.pdf |
| Cohen, Polk & Vuolteenaho (2003); Asness, Porter & Stevens (2000); Lev & Srivastava | the value effect is mostly within industries (supports an industry-relative rule); but the industry-adjusted value premium was about zero in 2007-2018 | https://personal.lse.ac.uk/polk/research/jofi_5802005.pdf ; https://cfr.ivo-welch.org/forthcoming/papers/lev2021explaining.pdf |

Honest status from `research/04` section 0: the literature supports peer multiples as *valuation* tools; **no paper tests the exact rule "buy if multiple < 0.85x the peer median"**; valuation accuracy is not return predictability; the P/E and EV/EBITDA caps and the 0.5x-2x size window are judgment parameters, which is exactly why they are in the grid.

#### (b) How the doc's rules were interpreted (spec audit, INTERPRETED rows)

| doc rule | implemented as | consequence |
|---|---|---|
| "4-5 peers" | size on: closest 5, need at least 4; size off: all valid peers, no cap | "without size filter" also removes the 4-5 limit, so the two effects cannot be separated |
| "TTM, same periods" | TTM for the target and every peer on the same date; last-fiscal-year basis as one robustness run | 135-day freshness gate |
| "P/E and EV/EBITDA both" | AND of the two discount tests, ranked by average discount | |
| "ignore negative; drop above 40 / 35" | exclusion (not winsorising), applied to peers **and** targets | |
| "no recent IPOs and mergers" | flags above, applied to peers and targets | flags 7-12% of the universe |
| "0.5x-2x of the median" | single-pass trim around the pre-trim median, at least 3 kept | |
| "0.85x of the median" | strict `<` `(1 - theta) x post-trim median` | |
| key metrics | target-only gates; margin stability = slope at least -0.5 pp/yr (a strict "improving" rule would reject about half of stable firms); ROIC above WACC; negative invested capital counts as passing (14 of 648 names) | the margin test is the binding gate: about 55% of names pass |
| "forward" multiples (TTM vs forward) | **not backtestable**: free data has no historical analyst estimates and realised future earnings would be look-ahead. Pre-registered as not backtestable; yfinance forward P/E is shown only as a live cross-check column | missing by design |
| "backtest all the numbers" | only 4 of about 15 numbers are in the grid (theta, P/E cap, EV/EBITDA cap, size filter); fixed and **not** tested: 4-5 peers, 0.5x-2x size window, 0.5x-2x trim band, ND/EBITDA 3, margin tolerances, 135-day staleness, 730-day IPO rule, top-20 | the audit asks for a pre-registered one-at-a-time sensitivity list; none was run |

Audit status: 13 EXACT, 7 INTERPRETED, 1 MISSING (forward multiples, by design), 0 WRONG out of 21 rows; key metrics 3 EXACT, 4 INTERPRETED, 1 WRONG (negative debt, fixed per `changelog.md`) out of 8 (`output/audit/spec_audit.md`). Thin peer groups: in the audit run about 58% of targets needed the industry fallback and about 60% of names valid on both multiples had no benchmark at all. Since the look-ahead fix, back-filled GICS labels count as unclassified, so 61-62% of names had no peer-group code in 2011-12 and 26% in 2013 (re-audit section 4.2): TC's train window runs on a thin universe in its first two years.

#### (c) Pre-registered grid and selection

Grid (`preregistration.json`): **54 cells = theta {10%, 15%, 20%} x P/E cap {30, 40, 50} x EV/EBITDA cap {25, 35, 45} x size filter {on, off}**, TTM only. Doc default: theta 15%, caps 40 / 35, size filter on.

**Selection result** (`results.md`). The plateau rule picks **theta 10%, P/E cap 40, EV/EBITDA cap 35, size filter off** (plateau score 0.516, peak ratio 1.00, plateau width 12 cells; category score 0.52 for size-filter-off against 0.25 for on). The bootstrap stability check **passes**: 45% of resamples select exactly this cell and 74% a cell within one step (50% needed); 13.8% select the doc default. Train Sharpe 0.55 against 0.20 for the doc default; the pick is not the argmax (6th of 54 in train; the argmax, Sharpe 0.61, has P/E cap 30). Neighbours: theta 15% 0.50, P/E cap 30 0.61, P/E cap 50 0.53, EV cap 25 0.56, EV cap 45 0.54 (10% is the lowest theta level, so it has no lower neighbour). Test confirmation: Sharpe 0.51 vs 0.47 for the doc default and 0.48 for the grid median; 59th percentile of the 54 cells; Spearman(train, test) = 0.12; test/train 0.93; all four confirmation criteria met.

**This pick is fragile.** In the run before the final re-audit fixes the same rule failed its own stability check (7% exact, 39% within one step) and fell back to the doc default, which gave a 1/7 verdict; in other runs it picked theta 10% / no size filter (section 2.0). What stayed constant is the direction: size-filter-off cells beat size-filter-on cells (section (e)). The finer choices (theta 10% vs 15%, P/E cap 30/40/50) move Sharpe by less than the noise (standard error about 0.36 per window), so say "no size filter, with a loose threshold" rather than quoting 10% and 40/35 as discoveries.

#### (d) Results

**Net results** (`results.md`; MaxDD daily).

| window | series | months | CAGR | vol | Sharpe | MaxDD | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|---|
| Train 2012-02..2018-12 | **TC chosen** | 83 | 8.0% | 15.3% | 0.55 | -33.3% | -3.2% (-1.00) |
| | TC doc default | 83 | 2.4% | 15.5% | 0.20 | -37.5% | **-7.8% (-2.21)** |
| | SPY | 83 | 12.0% | 10.6% | 1.08 | -19.3% | -0.3% (-1.42) |
| | RSP | 83 | 11.2% | 11.1% | 0.97 | -19.8% | -0.2% (-0.31) |
| | EW-SP900 | 83 | 11.9% | 11.7% | 0.98 | -21.3% | 0.5% (0.54) |
| Test 2019-01..2026-09 | **TC chosen** | 93 | 13.0% | 24.6% | 0.51 | -46.6% | -1.5% (-0.46) |
| | TC doc default | 93 | 11.9% | 24.0% | 0.47 | -46.3% | -3.0% (-1.04) |
| | SPY | 93 | 17.2% | 16.4% | 0.89 | -33.7% | -0.1% (-0.34) |
| | RSP | 93 | 13.1% | 17.9% | 0.63 | -39.0% | -2.0% (-1.70) |
| | EW-SP900 | 93 | 13.7% | 19.4% | 0.62 | -40.1% | -1.9% (-1.45) |
| Full 2012-02..2026-09 | **TC chosen** | 176 | 10.6% | 20.7% | 0.51 | -52.4% | -2.0% (-0.87) |
| | TC doc default | 176 | 7.3% | 20.5% | 0.37 | -52.7% | **-5.2% (-2.41)** |
| | SPY | 176 | 14.7% | 13.9% | 0.94 | -33.7% | -0.2% (-0.94) |
| | RSP | 176 | 12.2% | 15.1% | 0.73 | -39.0% | -1.1% (-1.43) |
| | EW-SP900 | 176 | 12.9% | 16.2% | 0.73 | -40.1% | -0.8% (-0.98) |

Test-window details (`trading_comps_chosen_tearsheet.md`): Sharpe 95% CI [0.04, 1.16]; beta vs SPY 1.20; tracking error 15.2%; IR vs SPY -0.13, vs EW-SP900 0.05; up-capture 113% but down-capture 140%. Full-sample turnover 355% a year (cost drag 69 bps), average 18.6 holdings and 1.3% cash (`summary.json`). Active return vs SPY is negative in all four sub-periods (-1.1%, -5.4%, -2.4%, -4.8%).

**Factor regression** (`trading_comps_chosen_T2_factor_regressions.csv`, t in brackets).

| window | alpha (ann %) | Mkt-RF | SMB | HML | RMW | CMA | Mom | R2 |
|---|---|---|---|---|---|---|---|---|
| Full (n=175) | -1.97 (-0.87) | 1.03 (14.8) | 0.36 (3.8) | 0.20 (2.6) | 0.52 (5.2) | 0.07 (0.5) | -0.30 (-3.9) | 0.81 |
| Train | -3.22 (-1.00) | 1.08 (11.4) | 0.28 (1.8) | 0.07 (0.4) | 0.48 (2.2) | 0.19 (0.6) | -0.15 (-2.3) | 0.68 |
| Test | -1.55 (-0.46) | 1.01 (12.0) | 0.34 (2.9) | 0.23 (2.8) | 0.47 (4.0) | 0.09 (0.5) | -0.39 (-3.5) | 0.86 |

Reading: the portfolio leans small, value, strongly profitable and anti-momentum (loadings are significant), and after paying for those exposures the leftover is slightly negative and not distinguishable from zero. So "cheap vs peers" shows no premium here. For the doc's own setting the leftover is clearly negative: full-sample alpha -5.16% (t -2.41), train -7.75% (t -2.21), test -2.95% (t -1.04) (`trading_comps_default_T2_factor_regressions.csv`).

**Overfitting** (`results.md`).

| diagnostic | train | full sample |
|---|---|---|
| t-stat of mean excess return | 1.44 | 1.96 |
| PSR(0) | 0.918 | 0.971 |
| DSR, N = 62 (ledger) | 0.663 | 0.900 |
| DSR, N_hat (effective trials) | 0.818 (4.86) | 0.952 (3.13) |
| Expected max Sharpe of N null trials | 0.38 | 0.16 |
| Years needed for PSR(0) >= 95% | 9.63 | 11.13 |
| **PBO (CSCV)** | **32.1%** | |
| P(out-of-sample Sharpe < 0) of the pick | 17.4% | |
| degradation slope | -0.69 | |

**Robustness** (`results.md`).

| run | full CAGR | full Sharpe | train Sh. | test Sh. | test CAGR | MaxDD | turnover | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|---|---|
| chosen (10 bps) | 10.6% | 0.51 | 0.55 | 0.51 | 13.0% | -52.4% | 355% | -2.0% (-0.87) |
| cost 0 bps | 11.4% | 0.54 | 0.59 | 0.54 | 13.8% | -51.7% | 355% | -1.3% (-0.57) |
| cost 25 bps | 9.5% | 0.46 | 0.48 | 0.47 | 11.9% | -53.5% | 355% | -3.0% (-1.32) |
| cost 50 bps | 7.6% | 0.38 | 0.36 | 0.40 | 10.0% | -55.2% | 355% | -4.7% (-2.06) |
| basis: last fiscal year instead of TTM | 12.4% | 0.60 | 0.68 | 0.57 | 14.5% | -46.3% | 349% | -0.4% (-0.19) |

The edge is negative at every cost level and costs matter (at 50 bps the alpha is significantly negative). TTM vs last fiscal year: the LFY basis did better in train, test and full (an extra trial run only at the chosen cell, never used for selection), so TTM has no demonstrated advantage. Survivorship stress: alpha is negative before any drag (break-even -197 bps; at 150 bps -3.47%, t -1.54).

**Regression of Sharpe on the grid parameters** (train, 54 cells, R2 = 0.94; `results.md`).

| term | coef | bootstrap SD | coef/SD |
|---|---|---|---|
| const | 0.486 | 0.469 | 1.0 |
| **theta** | **-0.080** | 0.031 | **-2.6** |
| pe_cap | 0.023 | 0.029 | 0.8 |
| ev_cap | -0.002 | 0.005 | -0.4 |
| theta^2 | 0.038 | 0.023 | 1.7 |
| pe_cap^2 | -0.035 | 0.033 | -1.1 |
| ev_cap^2 | -0.006 | 0.003 | -1.7 |
| theta x pe_cap | 0.015 | 0.011 | 1.4 |
| theta x ev_cap | 0.001 | 0.003 | 0.4 |
| pe_cap x ev_cap | 0.000 | 0.004 | 0.1 |
| size_filter = on | -0.275 | 0.152 | -1.8 |

**Figures** (heat maps print the Sharpe in each cell, star = selected, diamond = doc default; the surfaces are interpolated, grid points marked; with only 3 points per axis they are nearly flat planes and add little beyond the heat maps).

![TC train heat maps, all 6 theta x size-filter panels](trading_comps/trading_comps_train_C6_heatmap_overview.png)
![TC test heat maps](trading_comps/trading_comps_test_C6_heatmap_overview.png)
![TC train surface, theta 0.10, size filter off (selected)](trading_comps/trading_comps_train_C6_surface_theta_0_1_size_filter_false.png)
![TC train surface, theta 0.15, size filter on (doc default)](trading_comps/trading_comps_train_C6_surface_theta_0_15_size_filter_true.png)

#### (e) What the backtest says about the doc's own numbers (threshold 10/15/20%, P/E cap 30/40/50, EV/EBITDA cap 25/35/45, size filter with/without)

The doc asked for "a 'why' we picked" each number. Mean net Sharpe and CAGR over all cells at each level, computed from `grid_metrics_train.csv` (83 months) and `grid_metrics_test.csv` (93 months). Reference: EW-SP900 train Sharpe 0.98, CAGR 11.9%; test Sharpe 0.62, CAGR 13.7%. Per level there are 18 cells (27 for the size filter).

| parameter | level | train Sharpe | test Sharpe | train CAGR | test CAGR |
|---|---|---|---|---|---|
| **threshold theta** | 10% | **0.439** | 0.494 | 6.2% | 12.5% |
| | **15% (doc)** | 0.322 | **0.510** | 4.3% | 13.0% |
| | 20% | 0.280 | 0.493 | 3.6% | 12.5% |
| **P/E cap** | 30 | 0.312 | 0.491 | 4.1% | 12.5% |
| | **40 (doc)** | **0.371** | 0.485 | 5.1% | 12.3% |
| | 50 | 0.358 | **0.521** | 4.9% | 13.2% |
| **EV/EBITDA cap** | 25 | 0.347 | 0.493 | 4.7% | 12.5% |
| | **35 (doc)** | 0.351 | 0.499 | 4.8% | 12.6% |
| | 45 | 0.343 | 0.506 | 4.6% | 12.8% |
| **size filter** | **with (doc)** | 0.210 | 0.481 | 2.6% | 12.1% |
| | without | **0.484** | **0.517** | 6.8% | 13.3% |

Split by the size filter (mean Sharpe; computed from the same CSVs; the three numbers are the three levels in the order shown):

| | train, size filter off | train, size filter on | test, size filter off | test, size filter on |
|---|---|---|---|---|
| theta 10% / 15% / 20% | 0.563 / 0.490 / 0.400 | 0.315 / 0.154 / 0.160 | 0.513 / 0.521 / 0.517 | 0.474 / 0.500 / 0.468 |
| P/E cap 30 / 40 / 50 | 0.488 / 0.487 / 0.479 | 0.136 / 0.255 / 0.238 | 0.454 / 0.513 / 0.584 | 0.528 / 0.457 / 0.458 |
| EV cap 25 / 35 / 45 | 0.493 / 0.485 / 0.475 | 0.201 / 0.216 / 0.211 | 0.495 / 0.520 / 0.536 | 0.490 / 0.477 / 0.476 |

Which choices held up across neighbours, in plain words:

- **EV/EBITDA cap: it does not matter.** 25, 35 and 45 give the same average (train 0.347 / 0.351 / 0.343, test 0.493 / 0.499 / 0.506). Keeping the doc's 35 is as good as any, and we can say we checked.
- **P/E cap: 40 and 50 are equivalent; 30 is a bit worse in train** (0.312 vs 0.371 / 0.358). In test, 50 looks best (0.521), driven by the no-size-filter cells (0.584). The doc's 40 held up in both windows without being the best.
- **Threshold: a stricter threshold did not help.** In train the average Sharpe falls steadily as theta rises (0.439, 0.322, 0.280; regression coefficient -0.080, t -2.6, the only term beyond two bootstrap SDs; the size-filter dummy is at -1.8); in test the three levels are within 0.017. The doc's 15% is the middle choice with nothing to favour it beyond similar test results; 10% is clearly best in train and within 0.016 of 15% in test.
- **Size filter (0.5x-2x peers, max 5): clearly not helpful.** Without it the average train Sharpe is 0.484 against 0.210, and **every one of the 27 size-filter-off cells beats every one of the 27 size-filter-on cells in train** (lowest off 0.372, highest on 0.360); the test average is also higher (0.517 vs 0.481). The direction holds in 17 of the 18 neighbour comparisons (3 theta + 3 P/E + 3 EV levels x 2 windows; the exception is P/E cap 30 in test). (Because "without" also lifts the 4-5 peer cap, we cannot tell whether the size window or the cap is the culprit.) This is the one conclusion that survived every data correction.
- **TTM vs forward**: forward multiples cannot be backtested without paid historical analyst estimates; the live screen shows yfinance forward P/E only as a cross-check. TTM vs last fiscal year: LFY was better in all windows here (robustness table above), i.e. no evidence that TTM is the better basis.
- **The decisive result:** none of the 54 cells is a clear improvement on holding the whole equal-weight universe. Best train Sharpe 0.61 vs EW 0.98 (zero cells above it); best test Sharpe 0.62 vs EW 0.62 (a single cell, 0.623 vs 0.619, a rounding-level difference); no cell beats RSP (0.63) or SPY (0.89) in either window (computed from the grid CSVs and `summary.json`). Parameter choice is therefore a second-order matter; the first-order question, whether peer-discount screening adds value in this universe, has the answer "not shown".

---

## 3. Academic long-history evidence (factor level, 1927/1963-2026) and post-publication decay

**What this is** (`output/academic/academic_evidence.md`, produced by `quant/validation/factor_checks.py`): Ken French's data library (CRSP, vintage 202608, data to 2026-08) and AQR's quality-minus-junk series. These are survivorship-free, long-history **factor or decile portfolios**, gross of costs, so they test whether the *ideas* worked historically. They are **not** a test of our 2011-2026 stock-level backtests, and a French momentum decile is not a 5-10 stock book. 145 of 147 reference checks against the research notes match (the two differences: AQR rebuilds its web series, so it is not the paper's series).

### 3.1 Momentum (idea behind QM)

Long-short winners-minus-losers (WML, decile 10 minus decile 1, value-weighted; `academic_evidence.md` A1):

| period | mean %/month | Sharpe | CAPM alpha %/yr (t) |
|---|---|---|---|
| 1927-2026 (full) | 1.13 | 0.49 | 18.0 (8.3) |
| 1965-1989 (Jegadeesh-Titman sample) | 1.64 | 1.03 | 19.9 (5.3) |
| 1990-2008 | 1.57 | 0.71 | 20.5 (3.8) |
| before publication (to 1993-02) | 1.34 | 0.62 | 20.2 (8.5) |
| after publication (1993-03 on) | 0.72 | 0.29 | 13.9 (3.4) |
| 2009-2026 | 0.07 | **0.03** | 10.0 (1.8) |
| 2012-2026 | 0.47 | 0.20 | 13.0 (2.2) |

- **Long-only winners decile (what a top-N book resembles):** CAPM alpha 7.8%/yr (t 5.4) before 1993-03, 3.2% (t 1.5) after, **0.9% (t 0.3) in 2009-2026**; its Sharpe in 2009-2026 (0.76) is below the market's (0.91).
- **Volatility scaling still helps** (A2, A3): scaled WML Sharpe 0.54 to 1.00 in 1927-2011 and 0.20 to 0.37 in 2012-2026; worst month -77.7% to -24.2% (1927-2011). For the long-only winners decile with a 20% own-volatility target, Sharpe 0.60 to 0.67 and max drawdown -83.8% to -73.8% (daily-formed decile): modest, because most of the 1930s drawdown is the market's. Our own QM grid found no benefit from the 20% target (section 2.1 (e)).
- **Crashes are a bear-state, short-leg phenomenon** (A4): WML averages -1.11%/month in bear states against +1.56% otherwise; in Daniel-Moskowitz's window 14 of the 15 worst WML months were bear states. A long-only book avoids the loser leg but still lags junk-led rebounds.
- **Current regime** (A5, French data to 2026-08-31): 126-day WML volatility 53.0% against 27.6% long-run (97th percentile), the volatility-scaling weight on WML would be 0.23, winners-decile volatility 41.6%; the bear flag is off (market up 39.7% over 24 months). July 2026: WML -22.7%, winners decile -15.4%. QM's -40.0% test drawdown (2026-06-30 to 2026-07-29) sits in that month. Recompute from daily prices before relying on these numbers.

### 3.2 Quality (idea behind QM's filter)

(`academic_evidence.md` B; RMW = Fama-French robust-minus-weak profitability, QMJ = AQR quality-minus-junk USA.)

RMW (1963-07 on): mean 0.25%/month (t 3.0), Sharpe 0.38; 0.43 to 2012 and **0.22 from 2013** (mean 0.15%, t 0.8). QMJ (1957-07 on): 0.33%/month (t 4.0), Sharpe 0.49; 0.56 to 2012 and **0.29 from 2013** (0.25%, t 1.1).

Quality is positive but weaker since 2013 (not significantly different from zero). It is a diversifier for momentum, **not a crash hedge**: correlation with Mom 2x3 is 0.05 for RMW and 0.24 for QMJ, and in the worst 5% momentum months RMW averaged -0.49% and QMJ -1.97% per month. A 50/50 Mom + RMW blend has Sharpe 0.61 against 0.50 (Mom) and 0.39 (RMW) over 1963-07..2026-07, but only 0.10 in 2009-2026.

### 3.3 "Good and cheap" (idea behind MF) and value (idea behind TC)

(`academic_evidence.md` C, D; value-weighted; "top-2 x top-2 corner" = cheapest-and-most-profitable 16% of French's 5x5 book-to-market x profitability grid; this is a style proxy, not Greenblatt's EBIT/EV and ROC.)

| series | window | excess vs market, %/yr (t) |
|---|---|---|
| Top-2 x top-2 corner minus market | 1963-07 on | 4.5 (2.6) |
| | before the 2005 Greenblatt book (to 2005-10) | 6.5 (3.3) |
| | after (2005-11 on) | 0.5 (0.1) |
| | 2010-2026 | -2.3 (-0.7) |
| BM5-OP5 corner minus market | 1963-07 on / after 2005-11 / 2010-2026 | 4.5 (1.4) / 2.0 (0.3) / -5.8 (-0.9) |
| E/P top-minus-bottom quintile (VW) | before 2005-10 / after / 2010-2026 | 7.1 / -0.6 / -1.9 %/yr |
| HML (plain value factor) | 1926-2026 | 4.2 (3.4) |
| | before 1992-05 / after (1992-06 on) | 5.3 / 2.1 (t 1.1) |
| | 2010-2026 / 2007-2018 | -0.6 (-0.2) / -2.6 (-1.0) |

Read: cheap-and-profitable beat the market for four decades and has not since the book appeared; this matches `research/03`, so MF should be justified by process, not by a recent edge. For trading comps, plain value has been flat for a decade or more. **Caveat (written into the file):** comps buy *industry-relative* cheapness; French's files sort across all stocks, so an industry-neutral value series cannot be built here. Treat HML as a sanity check that "cheap beats expensive" once did, not as evidence for the 0.85x-peer-median rule.

![Cumulative growth of the factors](academic/factors_cumulative_growth.png)

### 3.4 McLean and Pontiff (2016) decay table, and how to use it honestly

McLean & Pontiff, "Does Academic Research Destroy Stock Return Predictability?", *Journal of Finance* 71(1), 2016 (https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365; the JSTOR link in the doc, https://www.jstor.org/stable/43869094, is probably the same article, so cite it once; `research/06` section 1.1). For 97 published predictors, equal-weighted long-short, 1926-2013: in-sample mean 58.2 bps a month; returns **26% lower after the sample ends** (an upper bound on pure data-mining bias) and **58% lower after publication**.

Our single-factor version of their test (`academic_evidence.md` E; "decline" = 1 - post mean / in-sample mean; windows with fewer than about 24 months, such as the pre-publication gap, are too short to read):

| factor | original sample | publication | in-sample %/mo (t) | post-publication %/mo | decline after publication | t(post vs in-sample) | Sharpe in-sample to post |
|---|---|---|---|---|---|---|---|
| WML D10-D1 (VW) | 1965-01..1989-12 | 1993-03 | 1.64 (5.1) | 0.72 | 56% | -1.7 | 1.03 to 0.29 |
| WML D10-D1 (EW) | same | 1993-03 | 1.33 (4.8) | 0.72 | 46% | -1.3 | 0.96 to 0.34 |
| Mom 2x3 (French) | same | 1993-03 | 0.82 (4.0) | 0.38 | 53% | -1.4 | 0.80 to 0.28 |
| HML | 1963-07..1990-12 | 1992-06 | 0.42 (3.0) | 0.18 | 58% | -1.0 | 0.58 to 0.19 |
| RMW (Novy-Marx dates) | 1963-07..2010-12 | 2013-04 | 0.28 (2.9) | 0.17 | 38% | -0.5 | 0.42 to 0.25 |
| RMW (FF2015 dates) | 1963-07..2013-12 | 2015-04 | 0.27 (2.9) | 0.20 | 27% | -0.3 | 0.41 to 0.27 |
| QMJ USA (SSRN 2013) | 1957-07..2012-12 | 2013-10 | 0.35 (4.2) | 0.28 | 18% | -0.2 | 0.56 to 0.32 |
| QMJ USA (published 2019) | 1957-07..2016-12 | 2019-01 | 0.36 (4.5) | 0.01 | 98% | -1.0 | 0.58 to 0.01 |
| BM5-OP5 minus market (VW) | 1988-01..2004-12 | 2005-11 | 0.97 (2.6) | 0.17 | 83% | -1.1 | 0.64 to 0.07 |

Average of the headline factors (WML 56, HML 58, RMW 38, QMJ 18, BM5-OP5 83): 51%, close to McLean-Pontiff's 58%. Single factors have wide error bands (post-vs-in-sample t-stats are mostly below 2 in size), so the **pattern, not any one percentage, is the evidence**.

![McLean-Pontiff style decay](academic/mclean_pontiff_decay.png)

**The doc's note about the 2016 paper** ("if we choose a strategy we backtested ourselves rather than a researched one, it strengthens our strategy and we can bring up the 2016 paper"). Verdict from `research/06` section 1.4, which we endorse:

- *Partly right:* a variant that has not been published has not been through the publication-driven part of the decay (about 32 of the 58 points), and any out-of-sample confirmation (our test window, then the live window) does strengthen a claim.
- *Where it breaks:* (i) our variants are close cousins of published signals (relative P/E and EV/EBITDA are value ratios; momentum and gross profitability are published), so publication effects are already in the signal class; (ii) the 26% out-of-sample drop is the data-mining haircut for *one* specification per paper, while our grids have up to 216 cells plus RSI/200-DMA/size options, so our selection bias can be larger; (iii) a self-built strategy has no out-of-sample history other than the test window and the live weeks.
- *Say instead:* "Published anomalies lose roughly a quarter to a half of their return after the sample and after publication (McLean and Pontiff 2016). We therefore tested on 2011-2026, which is almost entirely post-publication; fixed parameters on the train window with a pre-registered plateau rule and a fallback to the literature default; confirmed on 2019-2026; reported returns net of costs; adjusted Sharpe ratios for the number of variants tried (DSR, PBO); and plan around alpha smaller than the backtest shows."
- *Do not claim* "our own backtest strengthens the case" or "decay does not apply to us". Our results are in fact consistent with decay: MF and TC are indistinguishable from or below the equal-weight universe; QM's alpha is zero after factors.

Planning haircut (a heuristic, `research/06` section 1.3): IR_forward = IR_backtest x (1 - d) with d between 0.26 and 0.58. The tear sheets apply it: QM's backtest IR is 0.08, which gives a 13-day P(beat SPY) of 50.3% to 50.7%; the blend's IR is -0.02, giving 49.8% to 49.9% (`*_tearsheet.md`, "Forward expectation").

---

## 4. The blend of the three strategies

Equal-weight (1/3 each) average of the three strategies' **daily** net returns, chosen parameters (QM doc default, MF n=25/$5B, TC theta 10%/no size filter), common period 2012-02-01 to 2026-09-30 (the date TC starts); the re-equalisation cost between strategies is ignored; trials N = 323 (sum of the three ledgers). Component rows below therefore start in 2012-02 and differ slightly from the strategy sections (for example QM full CAGR 15.9% here vs 13.8% from 2011-02). Source: `output/blend/blend_qm_mf_tc_tearsheet.md` and `output/summary.json` (blend).

| window | series | CAGR | vol | Sharpe | MaxDD (daily) |
|---|---|---|---|---|---|
| Full 2012-02..2026-09 (176 months) | QM | 15.9% | 23.5% | 0.68 | -40.0% |
| | MF | 13.4% | 16.3% | 0.75 | -35.3% |
| | TC | 10.6% | 20.7% | 0.51 | -52.4% |
| | **Blend** | **14.1%** | **16.6%** | **0.78** | **-35.8%** |
| | SPY / RSP / EW-SP900 | 14.7% / 12.2% / 12.9% | 13.9% / 15.1% / 16.2% | 0.94 / 0.73 / 0.73 | -33.7% / -39.0% / -40.1% |
| Train 2012-02..2018-12 (83) | QM / MF / TC | 11.4% / 13.3% / 8.0% | 16.3% / 12.3% / 15.3% | 0.72 / 1.04 / 0.55 | -33.0% / -25.6% / -33.3% |
| | **Blend** | **11.1%** | **13.0%** | **0.84** | **-28.7%** |
| | SPY / RSP / EW-SP900 | 12.0% / 11.2% / 11.9% | 10.6% / 11.1% / 11.7% | 1.08 / 0.97 / 0.98 | -19.3% / -19.8% / -21.3% |
| Test 2019-01..2026-09 (93) | QM / MF / TC | 20.0% / 13.6% / 13.0% | 28.4% / 19.3% / 24.6% | 0.69 / 0.61 / 0.51 | -40.0% / -35.3% / -46.6% |
| | **Blend** | **16.7%** | **19.3%** | **0.76** | **-33.1%** |
| | SPY / RSP / EW-SP900 | 17.2% / 13.1% / 13.7% | 16.4% / 17.9% / 19.4% | 0.89 / 0.63 / 0.62 | -33.7% / -39.0% / -40.1% |
| Last 36 months | **Blend** (SPY 22.8%, 1.37; EW-SP900 14.0%, 0.70) | 23.5% | 16.6% | 1.09 | -21.5% |

Blend vs benchmarks (net): information ratio vs SPY -0.02 (full), -0.08 (train), 0.01 (test); vs EW-SP900 0.17 / -0.11 / 0.32; vs RSP 0.26 / 0.03 / 0.40. Beta vs SPY 1.05; up-capture 101%, down-capture 104% (full). Cost drag 87 bps a year, annual one-way turnover 397%, 76 holdings on average (overlaps not netted). **FF5+MOM alpha: -0.5% (t -0.26) full, -1.3% (t -0.58) train, +0.4% (t 0.14) test** (`blend_qm_mf_tc_T2_factor_regressions.csv`); loadings in the full sample: market 1.02, size 0.24 (t 3.3), momentum 0.11 (t 2.5).

**Correlations of monthly returns** (`summary.json` blend.correlation).

| pair | full | train | test |
|---|---|---|---|
| QM - MF | 0.41 | 0.67 | 0.33 |
| QM - TC | 0.34 | 0.62 | 0.26 |
| **MF - TC** | **0.86** | 0.79 | **0.89** |
| QM - SPY / MF - SPY / TC - SPY | 0.55 / 0.88 / 0.79 | 0.71 / 0.89 / 0.77 | 0.50 / 0.87 / 0.80 |
| Blend - SPY | 0.88 | 0.88 | 0.88 |
| *active returns vs SPY:* QM-MF / QM-TC / MF-TC | -0.19 / -0.19 / 0.56 | 0.12 / 0.16 / 0.36 | -0.27 / -0.29 / 0.64 |
| *in the worst 10% SPY months:* QM-MF / QM-TC / MF-TC | 0.32 / 0.10 / 0.78 | 0.72 / 0.80 / 0.85 | 0.07 / -0.18 / 0.80 |

Reading: (1) QM behaves differently from the other two (momentum vs value-quality), so mixing cuts volatility from 23.5% (QM alone) to 16.6%; (2) MF and TC are close to the same bet (0.86 correlated, 0.56 in their active returns), so the blend is effectively two ideas, not three; (3) the blend is an index-like, size-tilted portfolio (market beta 1.02, SMB 0.24) with no alpha and a result slightly below SPY (full Sharpe 0.78 vs 0.94; CAGR 14.1% vs 14.7%), so it is a diversification story and a process story, not a performance story; (4) in the worst SPY months the three are *not* a reliable hedge for each other (MF-TC 0.78 or more throughout; QM's correlation with them is 0.72-0.80 in train and near zero or negative in test). Horizon statistics for the blend are in section 6.

![Blend growth of $1](blend/blend_qm_mf_tc_C1_growth.png)

---

## 5. Data and methodology

### 5.1 How each input is handled (`quant/ARCHITECTURE.md`, `output/data_audit/*.md`)

| input | source | point-in-time handling | main limits |
|---|---|---|---|
| Fundamentals | SEC EDGAR XBRL "company facts" (plus a SEC financial-statement data-set patch for 2023-2026 filings); 397,540 filing snapshots, 15,166 CIKs | each snapshot holds only values known on its filed date (latest vintage of each fact up to that date); a filing is usable at signal date `t` only if `filed < t` strictly; TTM = fiscal year + year-to-date - prior year-to-date | XBRL coverage starts 2009-2011 (full TTM history 2012); EBIT proxy for companies without an operating-income tag (59k snapshots); multi-class share counts; revenue-tag choices; restated comparatives |
| Universe | S&P 500: exact daily membership (public file + Wikipedia for the latest weeks); S&P 400: Wikipedia quarter-end snapshots from 2011-03 (never early, can lag a quarter) | members are as of the date, not today's constituents | S&P 600 excluded (no free history before 2018-09) |
| GICS | Wikipedia snapshots (names and codes as of each snapshot) | as of the snapshot; labels that had to be back-filled from later snapshots are flagged (`*_next`); the comps code treats them as unclassified (no peer group), which thins TC's early universe; QM and MF still use them | sector reliable, sub-industry noisy; no free point-in-time GICS; known mislabels (see 5.3) |
| Prices and returns | Yahoo via yfinance, split- and dividend-adjusted; 4,979 days x 5,588 tickers to 2026-10-16 | daily total returns from adjusted close; verified identical to a fresh download for 20 tickers (largest daily difference 1.5e-6) | single vendor; **no delisted names**; spin-off artefacts repaired only on split-plus-dividend days |
| Risk-free | FRED 3-month T-bill (DTB3; ^IRX from 2026-10-15) | daily | mean absolute monthly gap to Ken French's RF 1.4 bp |
| Factors | Ken French FF5 + momentum monthly, to 2026-08 | n/a | alphas run through 2026-08 (n=175 to 187 months) |
| Timing | signal at the month-end close, **trade at the next close** | a +50% jump on t+1 is not captured with the one-day lag (tested); look-ahead perturbation test passed | competition orders fill at the next open; backtest uses the close; live trade is mid-month, backtest rebalances at month-end |
| Costs | 10 bps one way on every buy and sell (first entry too); forced delisting sales free | cost identity checked to 1e-17 | flat for all caps; no spread or impact model; no $25 per-trade fee; no taxes |

Validation of the fundamentals (`output/audit/data_audit.md`): against an independent parser on 179 (company, date) pairs, assets, equity and cash match within 1% in 100% of cases, revenue 97%, net income 98%, EBIT 95%, debt 91% (every miss classified); for look-ahead, 84 pairs (42 on filing days) gave zero differences in about 80 columns; 12 gross-profit test vectors match within 0.05% (`output/data_audit/fundamentals_coverage.md`).

### 5.2 Survivorship: coverage by year and the equal-weight bias proxy

Share of the point-in-time S&P 900 members that have a price series (the rest are delisted or acquired names Yahoo no longer serves), and the like-for-like bias proxy EW minus RSP (`output/survivorship.md`; * = partial year; EW and RSP are calendar-year returns).

| year | members (avg) | with prices (avg) | share | EW-SP900 | EW-SP500 | RSP | EW-SP900 minus RSP | EW-SP500 minus RSP |
|---|---|---|---|---|---|---|---|---|
| 2011* | 896 | 571 | 63.7% | -2.6% | -2.5% | -2.7% | 0.1% | 0.3% |
| 2012 | 889 | 576 | 64.9% | 19.8% | 19.4% | 17.2% | 2.7% | 2.3% |
| 2013 | 881 | 584 | 66.4% | 36.6% | 36.9% | 35.5% | 1.1% | 1.4% |
| 2014 | 892 | 608 | 68.2% | 12.8% | 14.9% | 14.1% | -1.2% | 0.9% |
| 2015 | 892 | 626 | 70.2% | -2.7% | -1.7% | -2.7% | -0.0% | 1.0% |
| 2016 | 885 | 646 | 73.0% | 20.7% | 15.8% | 14.5% | 6.2% | 1.3% |
| 2017 | 897 | 704 | 78.5% | 19.1% | 20.7% | 18.5% | 0.6% | 2.2% |
| 2018 | 896 | 726 | 81.0% | -9.0% | -7.6% | -7.8% | -1.1% | 0.3% |
| 2019 | 895 | 749 | 83.8% | 29.2% | 30.6% | 28.9% | 0.3% | 1.7% |
| 2020 | 890 | 773 | 86.8% | 13.4% | 12.6% | 12.7% | 0.8% | -0.0% |
| 2021 | 898 | 799 | 89.0% | 28.7% | 30.0% | 29.4% | -0.7% | 0.6% |
| 2022 | 899 | 816 | 90.7% | -10.9% | -11.2% | -11.6% | 0.7% | 0.4% |
| 2023 | 900 | 835 | 92.9% | 17.0% | 15.9% | 13.7% | 3.3% | 2.2% |
| 2024 | 900 | 852 | 94.7% | 11.8% | 13.0% | 12.8% | -1.0% | 0.2% |
| 2025 | 900 | 871 | 96.8% | 9.3% | 11.0% | 11.2% | -1.9% | -0.2% |
| 2026* | 899 | 890 | 98.9% | 11.5% | 12.8% | 13.1% | -1.6% | -0.3% |

Summary: mean share with prices 81.0% (worst month 63.2%); full-sample CAGR EW-SP900 12.3%, EW-SP500 12.7%, RSP 11.8%; **EW-SP900 minus RSP +0.48%/yr, EW-SP500 minus RSP +0.86%/yr** (+0.66%/yr after adding back RSP's 0.20% fee, the survivorship-plus-look-ahead estimate of `research/06`). The S&P 900 gap also carries the mid-cap premium, so the S&P 500 column is the clean proxy. The backtest audit adds: the engine's delisting path is never used because no held name ever vanishes (every name the default strategies ever held is alive on 2026-10-16), so **delisting losses are zero by construction**; survivor-only versions of the S&P 500 beat their ETFs by about 1 to 2.3 points a year and survivor-only S&P 400 lagged by 3.1 (`output/audit/backtest_audit.md` F1), so the benchmark contamination is roughly 1-3%/yr in either direction. Value-style strategies (MF, TC) are probably flattered most, and results before about 2016 (share under 73%) are the least reliable. That is why every tear sheet reports strategy minus EW-SP900, the only clean comparison.

### 5.3 Short summary of the audits

| audit | what it checked | result | key findings |
|---|---|---|---|
| **Spec audit** (`output/audit/spec_audit.md`) | 71 rules against the team doc and research specs (QM 23, MF 19, TC 21, key metrics 8); 196 existing unit tests run | 36 EXACT, 25 INTERPRETED, 6 MISSING, 4 WRONG; **no HIGH finding**, 3 medium | share count picked wrongly when cover-page and diluted counts differ by a power of ten (259 flagged cases, 243 wrong; a coverage hole, no wrong pick found); stale QM pre-registration text; MF "N" counts names per cohort, not names held (about 57 held); TC grids only 4 of about 15 numbers |
| **Backtest audit** (`output/audit/backtest_audit.md`, train data only; nothing from 2019+ was evaluated for performance) | engine, timing, costs, metrics, point-in-time data | checks 1-3 and 5-7 PASS (engine, look-ahead, alignment, costs, metrics, market-cap timing); check 4 (delisting/survivorship) PASS mechanically, FAIL structurally | own simulator reproduces the engine to under 5e-13 over 1,740 days; perturbing all post-`t` data leaves target weights identical; **F1 HIGH survivorship** (349 of 1,176 ever-members 2012-2018 have no prices); F2 medium GICS labels back-filled from later snapshots (19.2% of membership rows); F3 spin-off split ratios distort market caps (TC train CAGR 4.49% to 4.19% when fixed, MF 11.68% to 11.94%); F4 Yahoo double-adjusts some spin-offs (DHR +61.2% day) |
| **Data audit** (`output/audit/data_audit.md`) | fundamentals accuracy, look-ahead, market cap, prices, universe, risk-free | fundamentals PASS; look-ahead PASS; market cap FAIL before / PARTIAL after a mid-audit patch; price levels PASS, return artefacts FAIL; universe index facts PASS, GICS PARTIAL, coverage FAIL (known); rf PASS | 1.16% of member-months with no market cap (multi-class issuers such as V, BRK-B); GOOGL 2022 split-basis error (20x); a spin-off repair rule turned 9 legitimate special-dividend days into false -16% to -82% returns; bankruptcy-emergence splice (CHRD +25,733%); 3 wrong CIK matches (NVE, LSI, TBL); successor registrants not stitched; NFLX labelled IT 2015-2018; pre-2016-09 REITs carry "Real Estate" |
| **Re-audit** (`output/audit/reaudit.md`; audited the run before the final three fixes) | do the lead's fixes work, and does `summary.json` reproduce | market cap PARTIAL PASS; returns PASS; fundamentals PASS (all eight listed fixes); comps look-ahead PASS (0 of 17,595 back-filled-label rows receive a peer group); **reproducibility PASS: all 45 (strategy, series, window) blocks recompute to 7e-13 and an independent simulator matches the daily net returns to 6e-16**; test suite 548 passed | mcap missing 1,503 to 1,122 member-months, below $100M 828 to 147, above $10T 10 to 0; remaining defects touch 0 of 4,525 held MF name-months and 2 of 2,542 TC name-months (repairing 584 flagged rows moved MF train Sharpe 1.1243 to 1.1224, TC 0.1557 to 0.1665); new findings: diluted share count doubled in 1.16% of FY snapshots (NVDA, AMZN), 1000x scale errors (LAMR, BRK-B, GRMN, FOXA), LSI override too broad, Chubb Jan-Feb 2016 gap, CHRD splice removes its pre-2020 history (no effect tested), `git_commit` does not identify the code |

**What was fixed** (the `changelog.md` entries of 2026-10-19 03:00-04:15 UTC list these as applied): share counts and split-basis share handling; spin-off ratios in market caps; negative debt set to missing; capex sign; GICS look-ahead; spin-off return repair limited to days with both a split and a dividend (undoing the false special-dividend losses); bankruptcy-emergence splice cut; successor-CIK stitching; CIK overrides for NVE, LSI and TBL; net-income fallback order (preferred dividends); the SEC data-set patch for 2023-2026 (the data-coverage report had found about 101 large filers whose July-August 2026 10-Qs were missing from the SEC feed; the live picks' filing ages of at most 138 days are consistent with the patch working). **After the re-audit the lead also fixed** the FY diluted-share band (+-25%, the re-audit's finding on doubled Q4-derived share counts), a market-cap/assets plausibility guard, and the end date of the LSI override, then re-ran all three strategies and the blend (04:10-04:16 UTC). The QM and MF pre-registrations carry the re-stamp reason in their file history (QM also a `notes_on_timeline` disclosure of the two voided provisional runs). Effect of the corrections on results: QM unchanged; MF's headline numbers moved by a few hundredths (but PBO 24.5% to 30.1% and Spearman train/test -0.55 to -0.81); TC's selection moved between the doc default and theta 10%/no size filter and its ladder between 1/7 and 3/7 (section 2.0).

**Open or not fixed** (per `output/audit/reaudit.md` unless noted): survivorship; market cap still missing for 1,122 member-months (multi-class names such as STZ, GEF, V, BRK-B, SPG); Chubb Jan-Feb 2016 gap; APA PP&E; the CHRD splice cut removes its pre-2020 history (no effect on the chosen cells, tested); GICS mislabels (NFLX, early REIT labels, `data_audit.md`); back-filled GICS labels still feed QM and MF (14.4% and 14.7% of held name-months); EBIT-proxy edge case when the interest tag is missing in one TTM piece; finance-lease carry-forward; TC sensitivity list not pre-registered; QM shortlist (20%) and debt/equity cap (1.0) not gridded; execution at the close, not the open; `summary.json` records git commit `2c7657cd70`, which does not identify the audited code (the tree was untracked or modified). The re-audit's reproduction checks were run on the run before the final three fixes.

### 5.4 Every known limitation, in one list

1. **Survivorship** (5.2): up to 36.8% of members unpriced in 2011, 1.1% in 2026; zero delisting losses; EW-SP500 minus RSP +0.86%/yr; break-even drags QM 29, MF 56 bps a year.
2. **Universe**: S&P 600 excluded and S&P 400 only from 2011-03 (quarter-granular), so large and mid caps only. **GICS is not truly point-in-time** (sector reliable, sub-industry noisy, back-filled labels flagged, known mislabels); trading comps depends on it most, and since back-filled labels count as unclassified there, TC's 2012-13 train years run on a thin universe (no peer-group code for 62% of names in 2012, 26% in 2013).
3. **Fundamentals data**: EBIT proxy for companies with no operating-income tag; restated comparatives mixed into TTM; multi-class share counts; companyfacts gaps in July-August 2026 (patched); XBRL coverage starts 2011-06. Yahoo spin-off/special-dividend returns were repaired by rule, not hand-checked outside the audited cases.
4. **Short sample and multiple testing**: 93 test months; Sharpe standard error about 0.36-0.38 per window (`research/04`); ledger counts 223, 38 and 62; effective trials are lower (N_hat 39.6, 1.2, 4.9) because cells are correlated; 16 test looks (section 2.0); the 2011-2026 window is almost entirely post-publication (section 3).
5. **Costs and execution**: flat 10 bps, trade at the close, no spreads, no taxes, long-only, no leverage; live execution differs (mid-month, next open).
6. **Interpretation of the doc** (sections 2.1-2.3 (b)): RSI band and quality rule are heuristics; MF "20-30 stocks" holds about 48-57 names when staggered; TC without size filter also drops the 4-5 peer cap; only 4 of about 15 TC numbers were gridded; forward multiples cannot be backtested without paid historical estimates.

---

## 6. Short-horizon reality check: can three weeks of WInS P&L show skill?

Competition facts (`research/07_competition_rules.md` section 3): planned trade Wednesday 2026-10-21; trading ends and the portfolio freezes Friday 2026-11-06, which is **13 trading days**; "success is not determined by portfolio performance"; winners are chosen on the strength and articulation of the investment strategy (IPS due 2026-11-06, Trading Notes Analysis due 2026-10-23).

Backtest probability of beating SPY over every rolling 13-trading-day window (overlapping windows from daily net returns; 95% stationary-bootstrap interval in brackets; excess = strategy minus SPY, in percentage points; sources: each `results.md` "Short horizon" and `blend_qm_mf_tc_tearsheet.md` T7):

| strategy | window | P(beat SPY) | P(loss) | excess 5% / median / 95% | return 5% / median / 95% |
|---|---|---|---|---|---|
| QM | full | 49.7% [45-55] | 41.3% | -6.1 / -0.0 / 6.3 | -8.0 / 0.9 / 8.9% |
| QM | test | 49.8% [44-58] | 41.1% | -7.2 / -0.0 / 9.2 | -8.8 / 1.1 / 11.1% |
| MF | full | 50.2% [45-54] | 37.6% | -3.0 / 0.0 / 2.8 | -5.5 / 0.9 / 6.3% |
| MF | test | 47.0% [40-54] | 39.3% | -3.6 / -0.2 / 3.4 | -5.9 / 1.0 / 6.7% |
| TC | full | 47.3% [42-52] | 41.7% | -4.6 / -0.2 / 4.5 | -6.1 / 0.7 / 7.3% |
| TC | test | 47.7% [41-54] | 42.2% | -5.4 / -0.2 / 5.2 | -7.0 / 0.8 / 8.2% |
| Blend | full | 48.4% [44-54] | 37.5% | -2.8 / -0.1 / 2.9 | -5.7 / 1.0 / 6.2% |
| Blend | test | 48.6% [42-56] | 37.0% | -3.3 / -0.1 / 3.5 | -6.0 / 1.3 / 6.8% |

Longer horizons (P(beat SPY), full / test):

| strategy | 63 trading days | 126 trading days |
|---|---|---|
| QM | 45.5% [38-57] / 44.6% [35-63] | 44.6% [33-58] / 46.6% [29-66] |
| MF | 47.5% [37-59] / 41.0% [30-55] | 47.7% [34-63] / 38.4% [21-57] |
| TC | 45.2% [35-55] / 45.2% [32-60] | 40.1% [26-56] / 38.1% [23-61] |
| Blend | 49.4% [38-60] / 48.9% [35-63] | 46.4% [32-60] / 44.7% [26-63] |

What this says, in plain words:

- Over 13 trading days every strategy beats SPY about **47% to 50% of the time, i.e. a coin flip or worse**, and loses money about 37% to 42% of the time. The typical 13-day excess return ranges from about -3% to +3% (MF, blend) or -5% to +5% (TC) and -6% to +6% and more (QM) in 90% of windows, far larger than any plausible edge.
- Theory agrees (`research/06` section 7.2): if a strategy's true IR were 0.3, its chance of beating the benchmark in 13 days is only 52.7% (0.5 gives 54.5%, 0.75 gives 56.8%); an IR of about 10.9 would be needed for 80% power. Even with a real edge, 13 days cannot show it.
- Therefore the outcome of the Wednesday trades will be dominated by market direction, sector tilts and luck, and **cannot be used as evidence that a strategy works or fails**. This supports what the competition says it judges: the articulated process, risk management and consistency with the IPS. Present the live P&L with these odds next to it.

---

## 7. How to reproduce

From the repo root (`.venv/bin/python` is Python 3.14 with pandas, numpy, scipy, statsmodels, matplotlib, yfinance, pyarrow):

```
.venv/bin/python -m quant.run_backtests                      # grids, selection, test look, PBO/DSR, figures, tear sheets, blend, survivorship, summary.json (about 5-6 minutes for all three)
.venv/bin/python -m quant.run_backtests --strategy qm        # one strategy: qm | mf | tc | all
.venv/bin/python -m quant.validation.factor_checks           # long-history Ken French / AQR evidence -> output/academic/
.venv/bin/python -m pytest tests -q                          # unit tests (the re-audit ran 548 passed)
```

Every full run appends to `output/<strategy>/changelog.md` and to `output/ledger.csv` (re-running a cell does not raise N, but each run adds a test look). Do not re-run the grids casually; do not change a grid or the selection rule after seeing results.

**Tuesday-evening refresh (after the 16:00 ET close on 2026-10-20):**

```
.venv/bin/python -m quant.data.prices update                              # append latest bars, re-base check, rebuild matrices and rf
.venv/bin/python -m quant.run_backtests --strategy all --live-only        # recompute live picks from the parameters stored in output/summary.json
```

`--live-only` does not re-run the grids or re-select parameters (no new test look); useful flags: `--live-max-age-days 215` if some filings are stale, `--no-forward-pe` to skip the network fetch of yfinance forward P/E for comps. Outputs land in `output/live/` (`picks_overview.csv`, one table per strategy and parameter set, diagnostics JSON). The French factor files end in 2026-08, so factor numbers do not update with the refresh.

---

## Wednesday trade plan

See output/TRADE_PLAN.md (written by the lead).

---

## Live-pick audit

Summary of `output/audit/live_picks_audit.md` (audit date 2026-10-18, updated 2026-10-19 for the final TC list; per-ticker numbers in `output/audit/live_picks_audit.csv`; sources and detail in the audit file). Scope: the final live tables (QM 10, MF 25, TC 20; ANF is in all three, BAH, G, GEN, HRB, HPQ, INCY, MU in both MF and TC; signals as of the 2026-10-16 close) = **46 unique tickers: 4 BLOCK, 18 CAUTION, 24 OK**. An earlier pass on the previous 19-name TC list (48 names: 4 / 16 / 28) is superseded; PTC, its TC-only BLOCK, is no longer a pick.

| status | tickers and why |
|---|---|
| **BLOCK** (4) | **VAL** (QM): all-stock takeover by Transocean, trades 0.35% from the deal ratio. **HON** (MF): EBIT $8.40B still includes the spun-off Aerospace business, so EY 8.7% is really about 3-4%. **SOLV** (MF): EBIT includes a $1.52B one-off gain on a divestiture, so EY 10.5% is really about 2.7%. **SON** (TC): TTM net income and EBITDA include a ~$0.38B divestiture gain; on clean figures net debt/EBITDA is about 3.5-3.7x (fails the 3.0x gate) and the EV/EBITDA discount shrinks to 8-13% (below theta 10%), so it would not have been selected |
| CAUTION (18) | takeover talks: GEN, GDDY; falling knives: SNDK (fails the QM RSI screen itself), MU; energy cluster: PBF, VLO, APA, CHRD (5 of 10 QM names are Energy, correlation 0.55; PBF income inflated by unusual gains); thin margins or double counting: ANF (in all three sleeves, about 6.3% of an equal-sleeve portfolio; RSI 69.57 vs cap 70), APA (RSI 69.73); earnings before the fills: STLD (Oct 19 after close); others: ILMN (selected after S&P 500 inclusion, not cheap), GAP (leases excluded from EV), MMS (deteriorating fundamentals, thinnest liquidity), PNR (July profit warning); new TC names: AA (pending $4.1B South32 purchase, unusual gains, mismatched peers), KBR (pending spin-off, unrelated peer set), SFM (guidance risk, reports Oct 28), ZTS (EV/EBITDA benchmark 17.1x in the file vs 8.7x on Yahoo peer multiples, turning a 41% discount into a ~15% premium; guidance cut) |
| OK (24) | inputs match fresh Yahoo data; no deal, spin-off, delisting, restatement or going-private event found (final TC list OK: HRB, UHS, ENS, BAH, THC, INCY, HPQ, G, CRUS) |
| Replacements checked | CF (QM rank 11) CAUTION: 0.47 correlated with the energy names, RSI 52.5 near the 50 floor; RS (QM rank 12) OK, a third steel name reporting the evening of Oct 21; OTIS OK and INTU OK (MF alternates; INTU would be a tenth IT name); PNR CAUTION |

What passed: all prices equal the fresh Yahoo close for 2026-10-16 to the cent; market caps within 4.3% of Yahoo (within 1.7% for the final TC list); the 10 QM inputs (12-1 momentum, SMA200, Wilder RSI14) recomputed from a fresh 3-year history match to 4+ decimals and all 10 still pass the SMA200 and RSI 50-70 screens; odd-looking prices (BKNG $163.45 after a 25-for-1 split, MU $878.84, SNDK $1,299.30, VLO $444.71) are genuine; MF enterprise values within 15% of Yahoo (lease definition); for the final TC list the peer-median arithmetic reproduces all 40 benchmarks, and of 147 peer multiples compared with Yahoo, P/E agrees for 115 of 116 within 25% and EV/EBITDA for 117 of 128 (exceptions concentrated in pharma/biotech peers).

What it means for the research:

- **The screens need a human check.** Neither screen excludes pending M&A or spin-offs (spec audit row QM-21 "MISSING" turned out to matter: VAL, and in TC the AA and KBR situations), and TTM earnings can include one-off gains or spun-off segments (HON, SOLV, SON, AA, PBF). SON shows the TC rule can pass a name only because of a one-off gain.
- **TC discounts of 50-75% are largely sector-mix effects**: most benchmarks are broad GICS groups (KBR vs waste/auction names, AA vs gold/copper/steel miners, GAP/ANF vs off-price retailers); the ZTS EV/EBITDA leg did not survive recomputing peers on Yahoo multiples.
- **Event and concentration risk**: 35 of 46 names report between Oct 21 and Nov 6; the union is 10 IT, 10 Industrials, 8 Health Care, 7 Consumer Discretionary, 5 Energy, 4 Materials, 2 Staples (no Financials, Utilities, Real Estate, Communication Services); the TC sleeve alone has only 0.09 average pairwise correlation; MU, SNDK and CRUS form a memory/semiconductor cluster.
- **Audit suggestions for the trade plan** (decisions belong to the lead): drop the four blocked names and use the audited replacements; decide GEN/GDDY, SNDK/MU and the new TC CAUTIONs; cap the Energy cluster and avoid the ANF triple count; re-run the QM SMA/RSI screen and the TC discount on the Oct 20 close; write each Trading Note at the time of the order (due Oct 23).
- **Limits of the audit**: our prices come from Yahoo too, so equality with Yahoo is a consistency check, not independent proof; events were checked through EDGAR filings and web search; WInS ticker availability was not checked.

---

## Appendix A. Likely judge questions and honest answers

| question | short answer (numbers from this report) |
|---|---|
| Did you beat the market? | No. Test-window Sharpe: QM 0.69, MF 0.61, TC 0.51, blend 0.76 vs SPY 0.89; vs the equal-weight universe 0.62, QM and the blend are above, MF equal, TC below. No strategy has a significant positive alpha (QM 0.3%, t 0.07; MF 0.6%, t 0.29; TC -2.0%, t -0.87; the doc's own TC setting -5.2%, t -2.41). |
| Why use them then? | They are documented, rules-based processes with diversification (QM vs MF/TC correlation 0.38-0.41) and clear risk limits; the ladder's own advice for strategies that pass fewer than 5 of 7 is to hold them as research hypotheses at a modest weight. |
| How do you know you did not overfit? | Grids (216, 18, 54 cells) were written down first; selection used the train window only; an unstable pick falls back to the doc default (QM did; TC's pick is borderline: 74% within one step in the final run, 39% in an earlier one); PBO 70.8% / 30.1% / 32.1% and DSR are reported; the test window was examined once per run. Honest caveat: 16 test looks across runs because data bugs were fixed in between, and TC's choice flipped between runs. |
| Which of the doc's numbers survived? | QM: stop-losses and the RSI band hurt, the quality filter did not help out of sample, N 5-10 is fine. MF: N 20-30 does not matter; a larger size floor helped in train only. TC: EV/EBITDA cap does not matter, P/E cap 40-50 is equivalent, a looser threshold is no worse, the size filter hurt (the one conclusion that survived every data correction). (Sections 2.1-2.3 (e).) |
| Is the academic evidence still valid? | It was strong historically and weaker after publication: WML Sharpe 0.62 before 1993-03 and 0.29 after (0.03 in 2009-2026); cheap-and-profitable beat the market by 6.5%/yr before the 2005 book and 0.5%/yr after. |
| What is survivorship doing to your numbers? | 81.0% of historical members have prices; the like-for-like bias proxy is +0.86%/yr (EW-SP500 minus RSP); QM's alpha would vanish at 29 bps/yr and MF's at 56 bps/yr. |
| What will three weeks of results tell you? | Almost nothing: 13-day P(beat SPY) is 47-50% for every strategy. |

## Appendix B. File map

Headline numbers: `output/summary.json`, `output/ledger.csv`. Per strategy (`output/<strategy>/`): `results.md`, `*_tearsheet.md`, `changelog.md`, `preregistration.json`, `grid_metrics_{train,test,full}.csv`, `grid_cells.csv`, `grid_monthly_returns.csv`, `daily_*.csv`, figures `*_C1..C8_*.png`, `*_C6_*.png` (heat maps, surfaces), `C7_pbo.png`. Blend: `output/blend/`. Academic evidence: `output/academic/`. Survivorship: `output/survivorship.md`. Data reports: `output/data_audit/*.md` (the universe report is titled S&P 1500 because it predates the S&P 900 decision). Audits: `output/audit/*.md`. Live picks: `output/live/`. Research: `research/01..07_*.md`. Code: `quant/` (see `quant/ARCHITECTURE.md`), tests in `tests/`.
