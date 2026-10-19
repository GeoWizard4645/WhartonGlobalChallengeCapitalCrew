# Trading comps: results

Generated 2026-10-19 04:15 UTC · git `2c7657cd70` · data to 2026-10-16, backtest to 2026-09-30 · 54 pre-registered cells · 62 trials in the ledger.

**Universe**: point-in-time S&P 900 (S&P 500 + MidCap 400) ex GICS Financials and Real Estate, mcap >= $300M, raw price >= $5. Net of 10 bps one-way costs, signal at month-end close, trade at the next close.

## Verdict: 3/7 criteria passed -> mixed (failed: #1, #3, #6, #7); fewer than 5/7: do not claim it works, hold it as a research hypothesis at a modest weight

## Parameters

- **Chosen** (plateau_v1 choice): `theta=0.1, pe_cap=40, ev_cap=35, size_filter=False, basis=TTM`
- **Literature default**: `theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis=TTM`
- Train 2012-02 to 2018-12 (83 months): chosen Sharpe 0.55, default 0.20; plateau width 12 cells; bootstrap stability: 74% within one step

### Train

| series | months | CAGR | vol | Sharpe | MaxDD (daily) | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|
| chosen | 83 | 8.0% | 15.3% | 0.55 | -33.3% | -3.2% (-1.00) |
| default | 83 | 2.4% | 15.5% | 0.20 | -37.5% | -7.8% (-2.21) |
| SPY | 83 | 12.0% | 10.6% | 1.08 | -19.3% | -0.3% (-1.42) |
| RSP | 83 | 11.2% | 11.1% | 0.97 | -19.8% | -0.2% (-0.31) |
| EW-SP900 | 83 | 11.9% | 11.7% | 0.98 | -21.3% | 0.5% (0.54) |

### Test (single look)

| series | months | CAGR | vol | Sharpe | MaxDD (daily) | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|
| chosen | 93 | 13.0% | 24.6% | 0.51 | -46.6% | -1.5% (-0.46) |
| default | 93 | 11.9% | 24.0% | 0.47 | -46.3% | -3.0% (-1.04) |
| SPY | 93 | 17.2% | 16.4% | 0.89 | -33.7% | -0.1% (-0.34) |
| RSP | 93 | 13.1% | 17.9% | 0.63 | -39.0% | -2.0% (-1.70) |
| EW-SP900 | 93 | 13.7% | 19.4% | 0.62 | -40.1% | -1.9% (-1.45) |

### Full period

| series | months | CAGR | vol | Sharpe | MaxDD (daily) | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|
| chosen | 176 | 10.6% | 20.7% | 0.51 | -52.4% | -2.0% (-0.87) |
| default | 176 | 7.3% | 20.5% | 0.37 | -52.7% | -5.2% (-2.41) |
| SPY | 176 | 14.7% | 13.9% | 0.94 | -33.7% | -0.2% (-0.94) |
| RSP | 176 | 12.2% | 15.1% | 0.73 | -39.0% | -1.1% (-1.43) |
| EW-SP900 | 176 | 12.9% | 16.2% | 0.73 | -40.1% | -0.8% (-0.98) |

### Last 36 months

| series | months | CAGR | vol | Sharpe | MaxDD (daily) | FF5+MOM alpha (t) |
|---|---|---|---|---|---|---|
| chosen | 36 | 14.1% | 16.6% | 0.62 | -18.6% | 5.6% (1.12) |
| default | 36 | 13.5% | 17.0% | 0.57 | -22.2% | -3.1% (-0.69) |
| SPY | 36 | 22.8% | 12.4% | 1.37 | -18.8% |  |
| RSP | 36 | 15.5% | 12.9% | 0.85 | -17.8% |  |
| EW-SP900 | 36 | 14.0% | 14.0% | 0.70 | -21.1% |  |

## Selection and confirmation

- chosen: **theta=0.1, pe_cap=40, ev_cap=35, size_filter=False, basis=TTM** (plateau_v1 choice)
- default: theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis=TTM (train Sharpe 0.20)
- train Sharpe of chosen 0.55; plateau score 0.516; peak ratio 1.00; plateau width 12 cells (>= 90% of chosen)
- bootstrap stability (B=500, mean block 6): 45% select exactly this cell, 74% within one grid step -> pass
- sensitivity (not used for selection): argmax -> 84c50070ba (Sharpe 0.61, MORE THAN one step); lam0 -> 296dff0554 (Sharpe 0.61, within one step)

Reasons:
- train window 2012-02-29..2018-12-31: 83 months, 54 of 54 cells evaluable; metric = net Sharpe (annualised, excess of rf)
- plateau pick: score 0.516, peak ratio 1.00 (max 1.25)
- categorical plateau scores: size_filter=True=0.247; size_filter=False=0.516 (default category kept unless another beats it by >= 0.10)
- bootstrap stability (B=500): 45% exactly this cell, 74% within one grid step (need >= 50%) -> pass

Neighbourhood of the chosen cell (train):

| role | axis | step | theta | pe_cap | ev_cap | size_filter | sharpe |
|---|---|---|---|---|---|---|---|
| self |  | 0 | 0.1 | 40 | 35 | False | 0.55 |
| neighbor | theta | 1 | 0.15 | 40 | 35 | False | 0.50 |
| neighbor | pe_cap | -1 | 0.1 | 30 | 35 | False | 0.61 |
| neighbor | pe_cap | 1 | 0.1 | 50 | 35 | False | 0.53 |
| neighbor | ev_cap | -1 | 0.1 | 40 | 25 | False | 0.56 |
| neighbor | ev_cap | 1 | 0.1 | 40 | 45 | False | 0.54 |

Plateau result per categorical level:

| category | n_cells | is_default_category | n_eligible | score | peak_ratio | sharpe | chosen |
|---|---|---|---|---|---|---|---|
| size_filter=True | 27 | True | 24 | 0.25 | 1.14 | 0.34 | False |
| size_filter=False | 27 | False | 27 | 0.52 | 1.00 | 0.55 | True |

Confirmation on the untouched test window 2019-01-01 to 2026-09-30:

| cell | sharpe | cagr | vol | maxdd | tstat | n_months |
|---|---|---|---|---|---|---|
| chosen | 0.51 | 13.0% | 24.6% | -38.7% | 1.42 | 93 |
| default | 0.47 | 11.9% | 24.0% | -35.9% | 1.32 | 93 |
| grid_median | 0.48 | 12.1% | 24.5% | -37.9% | 1.34 | 93 |

- chosen minus default Sharpe: 0.04; chosen minus grid median: 0.03; rank percentile among cells: 59%
- Spearman(train Sharpe, test Sharpe) across cells: 0.12; test/train Sharpe of the chosen cell: 0.93
- criteria: test_sharpe_positive=yes, test_ge_half_train=yes, landscape_persists=yes, beats_grid_median=yes

## Overfitting diagnostics (train)

| diagnostic | value |
|---|---|
| Months / window | 83 / 2012-02-29..2018-12-31 |
| Trials N (ledger, distinct configurations) | 62 |
| Cells in grid / effective trials N_hat | 54 / 4.86 |
| Net Sharpe (annualised) | 0.55 |
| t-stat of mean excess return | 1.44  (vs 2.0: fail; 3.0: fail; 3.39: fail) |
| PSR(0) | 0.918 |
| Expected max Sharpe SR0 of N null trials (annualised) | 0.38 |
| DSR at N = 62 (ledger) | 0.663 |
| DSR at N_hat = 4.86 | 0.818 |
| DSR at N = 54 (grid cells) | 0.671 |
| Bonferroni haircut Sharpe (annualised) / haircut | 0.00 / 100% |
| Minimum track record for PSR(0) >= 95% (years) | 9.63 |
| PBO (CSCV, S=16, selector: plateau) | 32.1%  (12,870 splits) |
| P(OOS Sharpe < 0) of the selected trial | 17.4% |
| Degradation slope (OOS on IS Sharpe; negative = overfit) | -0.69 |

DSR on the full sample:

| diagnostic | value |
|---|---|
| Months / window | 176 / full |
| Trials N (ledger, distinct configurations) | 62 |
| Cells in grid / effective trials N_hat | 54 / 3.13 |
| Net Sharpe (annualised) | 0.51 |
| t-stat of mean excess return | 1.96  (vs 2.0: fail; 3.0: fail; 3.39: fail) |
| PSR(0) | 0.971 |
| Expected max Sharpe SR0 of N null trials (annualised) | 0.16 |
| DSR at N = 62 (ledger) | 0.900 |
| DSR at N_hat = 3.13 | 0.952 |
| DSR at N = 54 (grid cells) | 0.903 |
| Bonferroni haircut Sharpe (annualised) / haircut | 0.00 / 100% |
| Minimum track record for PSR(0) >= 95% (years) | 11.13 |

## Grid regression (train)

Response: net Sharpe of each of 54 grid cells on 2012-02-29..2018-12-31; ordinal parameters scaled to [-1, 1]; R2 = 0.94. Bootstrap SDs resample months jointly across cells (B=500); cells overlap, so OLS p-values would be meaningless. A flat surface (small coefficients, low R2) is good news.

| term | coef | bootstrap SD | coef / SD |
|---|---|---|---|
| const | 0.486 | 0.469 | 1.0 |
| theta | -0.080 | 0.031 | -2.6 |
| pe_cap | 0.023 | 0.029 | 0.8 |
| ev_cap | -0.002 | 0.005 | -0.4 |
| theta^2 | 0.038 | 0.023 | 1.7 |
| pe_cap^2 | -0.035 | 0.033 | -1.1 |
| ev_cap^2 | -0.006 | 0.003 | -1.7 |
| theta*pe_cap | 0.015 | 0.011 | 1.4 |
| theta*ev_cap | 0.001 | 0.003 | 0.4 |
| pe_cap*ev_cap | 0.000 | 0.004 | 0.1 |
| size_filter=True | -0.275 | 0.152 | -1.8 |

## Robustness (each run is a ledger trial)

Full-period net results of one-at-a-time changes around the chosen cell. Every run is logged in the ledger as an extra trial (it raises N for the DSR).

| run | full CAGR | full Sharpe | train Sharpe | test Sharpe | test CAGR | MaxDD | turnover/yr | FF5+MOM alpha | IR vs SPY | IR vs EW |
|---|---|---|---|---|---|---|---|---|---|---|
| chosen (base, 10 bps) | 10.6% | 0.51 | 0.55 | 0.51 | 13.0% | -52.4% | 355% | -2.0% (t=-0.87) | -0.19 | -0.12 |
| cost 0 bps | 11.4% | 0.54 | 0.59 | 0.54 | 13.8% | -51.7% | 355% | -1.3% (t=-0.57) | -0.14 | -0.05 |
| cost 25 bps | 9.5% | 0.46 | 0.48 | 0.47 | 11.9% | -53.5% | 355% | -3.0% (t=-1.32) | -0.28 | -0.22 |
| cost 50 bps | 7.6% | 0.38 | 0.36 | 0.40 | 10.0% | -55.2% | 355% | -4.7% (t=-2.06) | -0.41 | -0.40 |
| basis LFY (last fiscal year) | 12.4% | 0.60 | 0.68 | 0.57 | 14.5% | -46.3% | 349% | -0.4% (t=-0.19) | -0.08 | 0.04 |

## Evidence ladder

**3/7 criteria passed -> mixed (failed: #1, #3, #6, #7); fewer than 5/7: do not claim it works, hold it as a research hypothesis at a modest weight**

| # | criterion | pass | evidence |
|---|---|---|---|
| 1 | Direction replicates: net IR vs same-universe EW > 0 on train AND test | NO | IR train -0.37, test 0.05 |
| 2 | Plateau: chosen cell passes the 5.4 eligibility and bootstrap stability | yes | passed; stability 74% within one step |
| 3 | Costs: FF5+MOM net alpha still > 0 at 25 bps one-way | NO | alpha -3.0%/yr (t=-1.32) at 25 bps; buy/hold-spread check for momentum not run |
| 4 | Factor view: FF5+MOM alpha > 0, or explained by the expected factors with no large negative alpha | yes | alpha -2.0%/yr (t=-0.87, full sample to 2026-08, French data end 2026-08); expected-factor loadings with abs(t) > 2: HML 0.20 (t=2.6) |
| 5 | Overfitting: PBO < 0.5 (DSR at N_hat and haircut Sharpe reported) | yes | PBO 32.1%; DSR(ledger N=62) 0.663, DSR(N_hat=4.86) 0.818; haircut Sharpe 0.00 (train, aim DSR > 0.5: met) |
| 6 | Bias stress: FF5+MOM alpha survives a 150 bps/yr survivorship drag | NO | break-even drag -197 bps/yr (alpha -1.97%); active CAGR vs EW-SP900 -2.0% |
| 7 | Subperiods: positive active return vs SPY in at least 3 of 4 subperiods | NO | 0 of 4 positive (2011-14 -1.1%, 2015-18 -5.4%, 2019-22 -2.4%, 2023-26 -4.8%); worst 12m active return vs SPY -28.1% |

## Bias stress

SURVIVORSHIP-BIASED (yfinance has no delisted names): 81.0% of point-in-time S&P 900 members have a price history (monthly mean 2011-2026, minimum 63.2%); EW-SP900 minus RSP = +0.5%/yr CAGR gap (EW-SP500 minus RSP +0.9%/yr, the like-for-like bias proxy; the S&P 900 gap also contains the mid-cap premium); see output/survivorship.md

Break-even drag (alpha = 0): -197 bps/yr.

| assumed drag (bps/yr) | FF5+MOM alpha after drag | t |
|---|---|---|
| 0 | -1.97% | -0.87 |
| 50 | -2.47% | -1.09 |
| 100 | -2.97% | -1.31 |
| 150 | -3.47% | -1.54 |
| 200 | -3.97% | -1.76 |
| 300 | -4.97% | -2.20 |

Coverage by year and the EW-minus-RSP gap are in `output/survivorship.md`. Overall: share with prices 81.0%; EW-SP900 minus RSP +0.48%/yr.

## Short horizon (daily net returns, chosen parameters)

| window | horizon | P(beat SPY) | P(loss) | excess 5%/median/95% | return 5%/median/95% |
|---|---|---|---|---|---|
| full | 13d | 47.3% [42-52] | 41.7% | -4.6 / -0.2 / 4.5 pts | -6.1 / 0.7 / 7.3% |
| full | 63d | 45.2% [35-55] | 31.0% | -9.8 / -0.5 / 8.9 pts | -11.2 / 3.3 / 16.3% |
| full | 126d | 40.1% [26-56] | 27.7% | -12.7 / -1.9 / 12.4 pts | -13.9 / 6.2 / 24.4% |
| test | 13d | 47.7% [41-54] | 42.2% | -5.4 / -0.2 / 5.2 pts | -7.0 / 0.8 / 8.2% |
| test | 63d | 45.2% [32-60] | 33.4% | -11.3 / -0.8 / 10.0 pts | -11.0 / 3.0 / 17.6% |
| test | 126d | 38.1% [23-61] | 27.7% | -14.6 / -2.3 / 11.3 pts | -14.5 / 6.2 / 28.3% |

## Live picks (as of 2026-10-16)

- chosen (20): GAP, HPQ, MMS, ANF, AA, UHS, HRB, G, GEN, KBR, ENS, BAH, THC, SFM, INCY, MU, ZTS, PNR, SON, CRUS
- default (19): UHS, THC, G, GAP, HRB, MMS, BAH, SNA, BKNG, MLI, GEN, DBX, CDW, GEHC, BSX, LVS, PNR, EHC, PTC
- tables: `output/live/trading_comps_chosen.csv`, `output/live/trading_comps_default.csv` (+ diagnostics JSON in `output/live/`)
- fundamentals age of the chosen picks: {'max_age_days': 111.0, 'median_age_days': 108.0, 'n_older_than_150': 0, 'n_older_than_200': 0}

## Files

- tear sheet (chosen): [trading_comps_chosen_tearsheet.md](trading_comps_chosen_tearsheet.md)
- tear sheet (default): [trading_comps_default_tearsheet.md](trading_comps_default_tearsheet.md)
- grid: `grid_cells.csv`, `grid_monthly_returns.csv`, `grid_metrics_{train,test,full}.csv`
- daily series: `daily_chosen.csv`, `daily_default.csv`, `daily_benchmarks.csv`

## Figures

![trading_comps_train_C6_heatmap_theta_0_1_size_filter_true](trading_comps_train_C6_heatmap_theta_0_1_size_filter_true.png)

![trading_comps_train_C6_heatmap_theta_0_1_size_filter_false](trading_comps_train_C6_heatmap_theta_0_1_size_filter_false.png)

![trading_comps_train_C6_heatmap_theta_0_15_size_filter_true](trading_comps_train_C6_heatmap_theta_0_15_size_filter_true.png)

![trading_comps_train_C6_heatmap_theta_0_15_size_filter_false](trading_comps_train_C6_heatmap_theta_0_15_size_filter_false.png)

![trading_comps_train_C6_heatmap_theta_0_2_size_filter_true](trading_comps_train_C6_heatmap_theta_0_2_size_filter_true.png)

![trading_comps_train_C6_heatmap_theta_0_2_size_filter_false](trading_comps_train_C6_heatmap_theta_0_2_size_filter_false.png)

![trading_comps_train_C6_heatmap_overview](trading_comps_train_C6_heatmap_overview.png)

![trading_comps_train_C6_surface_theta_0_1_size_filter_true](trading_comps_train_C6_surface_theta_0_1_size_filter_true.png)

![trading_comps_train_C6_surface_theta_0_1_size_filter_false](trading_comps_train_C6_surface_theta_0_1_size_filter_false.png)

![trading_comps_train_C6_surface_theta_0_15_size_filter_true](trading_comps_train_C6_surface_theta_0_15_size_filter_true.png)

![trading_comps_train_C6_surface_theta_0_15_size_filter_false](trading_comps_train_C6_surface_theta_0_15_size_filter_false.png)

![trading_comps_train_C6_surface_theta_0_2_size_filter_true](trading_comps_train_C6_surface_theta_0_2_size_filter_true.png)

![trading_comps_train_C6_surface_theta_0_2_size_filter_false](trading_comps_train_C6_surface_theta_0_2_size_filter_false.png)

![trading_comps_test_C6_heatmap_theta_0_1_size_filter_true](trading_comps_test_C6_heatmap_theta_0_1_size_filter_true.png)

![trading_comps_test_C6_heatmap_theta_0_1_size_filter_false](trading_comps_test_C6_heatmap_theta_0_1_size_filter_false.png)

![trading_comps_test_C6_heatmap_theta_0_15_size_filter_true](trading_comps_test_C6_heatmap_theta_0_15_size_filter_true.png)

![trading_comps_test_C6_heatmap_theta_0_15_size_filter_false](trading_comps_test_C6_heatmap_theta_0_15_size_filter_false.png)

![trading_comps_test_C6_heatmap_theta_0_2_size_filter_true](trading_comps_test_C6_heatmap_theta_0_2_size_filter_true.png)

![trading_comps_test_C6_heatmap_theta_0_2_size_filter_false](trading_comps_test_C6_heatmap_theta_0_2_size_filter_false.png)

![trading_comps_test_C6_heatmap_overview](trading_comps_test_C6_heatmap_overview.png)

![C7_pbo](C7_pbo.png)

![trading_comps_chosen_C1_growth](trading_comps_chosen_C1_growth.png)

![trading_comps_chosen_C2_underwater](trading_comps_chosen_C2_underwater.png)

![trading_comps_chosen_C3_rolling](trading_comps_chosen_C3_rolling.png)

![trading_comps_chosen_C4_calendar](trading_comps_chosen_C4_calendar.png)

![trading_comps_chosen_C5_horizons](trading_comps_chosen_C5_horizons.png)

![trading_comps_chosen_C8_loadings](trading_comps_chosen_C8_loadings.png)

![trading_comps_default_C1_growth](trading_comps_default_C1_growth.png)

![trading_comps_default_C2_underwater](trading_comps_default_C2_underwater.png)

![trading_comps_default_C3_rolling](trading_comps_default_C3_rolling.png)

![trading_comps_default_C4_calendar](trading_comps_default_C4_calendar.png)

![trading_comps_default_C5_horizons](trading_comps_default_C5_horizons.png)

![trading_comps_default_C8_loadings](trading_comps_default_C8_loadings.png)

## Runtime (seconds)

| start_date | grid | select_confirm | pbo_regression | grid_figures | final_backtests | benchmarks | analysis | robustness | horizon | tearsheets | live |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 0.0 | 86.8 | 0.3 | 6.1 | 1.8 | 2.3 | 0.4 | 0.0 | 11.7 | 3.6 | 3.1 | 61.0 |
