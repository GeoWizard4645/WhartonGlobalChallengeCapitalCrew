# Quality momentum (chosen): tear sheet

| item | value |
|---|---|
| Generated | 2026-10-19 04:11 UTC |
| Data | 2011-02-01 to 2026-09-30 (3,939 trading days) |
| Benchmarks | SPY, RSP, EW-SP900 (reference: SPY) |
| strategy | Quality-filtered momentum (quality_momentum) |
| parameter set | order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none  [literature default (plateau rule fell back)] |
| literature default | order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none |
| universe | point-in-time S&P 900 (S&P 500 + MidCap 400) ex GICS Financials and Real Estate, raw price >= $5 |
| windows | train 2011-02 to 2018-12; test 2019-01 to 2026-09 (single look); data end 2026-10-16 |
| trials N (ledger, distinct) | 223 |
| grid | 216 pre-registered cells, registered 2026-10-19T02:57:36+00:00 |
| costs | 10 bps one-way on every buy and sell (robustness 0/25/50) |
| timing | signal at the close of the month-end, trade at the next close; filings usable only if filed strictly before the signal date |
| survivorship | SURVIVORSHIP-BIASED (yfinance has no delisted names): 81.0% of point-in-time S&P 900 members have a price history (monthly mean 2011-2026, minimum 63.2%); EW-SP900 minus RSP = +0.5%/yr CAGR gap (EW-SP500 minus RSP +0.9%/yr, the like-for-like bias proxy; the S&P 900 gap also contains the mid-cap premium); see output/survivorship.md |
| benchmarks | SPY, RSP, EW-SP900 = equal-weight S&P 900 with the strategy's sector exclusions (Financials, Real Estate), 10 bps |
| git commit | 2c7657cd70 |
| tear sheet for | chosen |

## T1 Performance, net of costs

Monthly statistics from calendar-month compounded daily returns (partial leading/trailing months dropped); MaxDD is daily. Benchmark-relative rows are vs SPY; Sharpe CI = stationary bootstrap (mean block 6, B=500).

### Full (2011-02 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 188 | 188 | 188 | 188 | 188 |
| CAGR | 13.8% | 15.5% | 14.0% | 11.6% | 12.5% |
| AnnVol | 23.2% | 23.2% | 14.1% | 15.4% | 16.5% |
| Sharpe | 0.61 | 0.67 | 0.90 | 0.69 | 0.70 |
| Sharpe 95% CI | [0.16, 1.04] | [0.22, 1.11] | [0.49, 1.42] | [0.28, 1.20] | [0.31, 1.21] |
| Sortino | 0.97 | 1.09 | 1.45 | 1.07 | 1.11 |
| MaxDD (daily) | -40.0% | -39.9% | -33.7% | -39.0% | -40.1% |
| MaxDD peak>trough | 2026-06-30 > 2026-07-29 | 2026-06-30 > 2026-07-29 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.34 | 0.39 | 0.42 | 0.30 | 0.31 |
| Beta vs SPY | 0.92 | 0.92 | – | 1.03 | 1.10 |
| TE vs SPY | 19.2% | 19.2% | – | 5.2% | 6.1% |
| IR vs SPY | 0.08 | 0.16 | – | -0.38 | -0.16 |
| ActiveCAGR vs SPY | -0.2% | 1.3% | – | -2.1% | -1.3% |
| HitRate 1m | 49% | 51% | – | 46% | 47% |
| HitRate 3m | 44% | 46% | – | 39% | 42% |
| HitRate 6m | 46% | 48% | – | 37% | 44% |
| Up capture vs SPY | 97% | 101% | – | 96% | 102% |
| Down capture vs SPY | 82% | 78% | – | 107% | 111% |
| IR vs RSP | 0.17 | – | – | – | – |
| IR vs EW-SP900 | 0.12 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 171 | – | – | – | – |
| Avg holdings | 9.72 | – | – | – | – |
| Annual one-way turnover | 784% | – | – | – | – |

### Train (2011-02 to 2018-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 95 | 95 | 95 | 95 | 95 |
| CAGR | 8.0% | 9.6% | 11.0% | 10.1% | 11.3% |
| AnnVol | 16.4% | 16.4% | 11.4% | 12.4% | 13.1% |
| Sharpe | 0.53 | 0.62 | 0.93 | 0.80 | 0.85 |
| Sharpe 95% CI | [-0.30, 1.34] | [-0.21, 1.44] | [0.24, 1.76] | [0.13, 1.65] | [0.16, 1.75] |
| Sortino | 0.78 | 0.93 | 1.51 | 1.27 | 1.37 |
| MaxDD (daily) | -33.0% | -32.7% | -19.3% | -22.9% | -23.3% |
| MaxDD peak>trough | 2018-09-04 > 2018-12-24 | 2018-09-04 > 2018-12-24 | 2018-09-20 > 2018-12-24 | 2011-07-07 > 2011-10-03 | 2011-07-07 > 2011-10-03 |
| Calmar | 0.24 | 0.29 | 0.57 | 0.44 | 0.49 |
| Beta vs SPY | 1.02 | 1.02 | – | 1.06 | 1.10 |
| TE vs SPY | 11.6% | 11.6% | – | 2.8% | 4.1% |
| IR vs SPY | -0.18 | -0.05 | – | -0.24 | 0.12 |
| ActiveCAGR vs SPY | -2.7% | -1.2% | – | -0.8% | 0.3% |
| HitRate 1m | 49% | 51% | – | 45% | 49% |
| HitRate 3m | 46% | 48% | – | 42% | 47% |
| HitRate 6m | 46% | 50% | – | 41% | 54% |
| Up capture vs SPY | 96% | 101% | – | 100% | 106% |
| Down capture vs SPY | 112% | 108% | – | 107% | 107% |
| IR vs RSP | -0.12 | – | – | – | – |
| IR vs EW-SP900 | -0.22 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 162 | – | – | – | – |
| Avg holdings | 9.81 | – | – | – | – |
| Annual one-way turnover | 773% | – | – | – | – |

### Test (2019-01 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 93 | 93 | 93 | 93 | 93 |
| CAGR | 20.0% | 21.8% | 17.2% | 13.1% | 13.7% |
| AnnVol | 28.4% | 28.5% | 16.4% | 17.9% | 19.4% |
| Sharpe | 0.69 | 0.74 | 0.89 | 0.63 | 0.62 |
| Sharpe 95% CI | [0.18, 1.24] | [0.23, 1.29] | [0.35, 1.59] | [0.10, 1.33] | [0.10, 1.28] |
| Sortino | 1.14 | 1.24 | 1.44 | 0.97 | 0.97 |
| MaxDD (daily) | -40.0% | -39.9% | -33.7% | -39.0% | -40.1% |
| MaxDD peak>trough | 2026-06-30 > 2026-07-29 | 2026-06-30 > 2026-07-29 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.50 | 0.55 | 0.51 | 0.34 | 0.34 |
| Beta vs SPY | 0.87 | 0.87 | – | 1.02 | 1.10 |
| TE vs SPY | 24.7% | 24.7% | – | 6.8% | 7.6% |
| IR vs SPY | 0.21 | 0.27 | – | -0.49 | -0.33 |
| ActiveCAGR vs SPY | 2.4% | 3.9% | – | -3.5% | -3.0% |
| HitRate 1m | 49% | 51% | – | 47% | 44% |
| HitRate 3m | 43% | 45% | – | 35% | 36% |
| HitRate 6m | 49% | 49% | – | 32% | 36% |
| Up capture vs SPY | 97% | 101% | – | 93% | 99% |
| Down capture vs SPY | 61% | 58% | – | 107% | 114% |
| IR vs RSP | 0.32 | – | – | – | – |
| IR vs EW-SP900 | 0.29 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 181 | – | – | – | – |
| Avg holdings | 9.63 | – | – | – | – |
| Annual one-way turnover | 795% | – | – | – | – |

### Last 36m (2023-10 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 36 | 36 | 36 | 36 | 36 |
| CAGR | 36.7% | 38.9% | 22.8% | 15.5% | 14.0% |
| AnnVol | 37.1% | 37.2% | 12.4% | 12.9% | 14.0% |
| Sharpe | 0.92 | 0.96 | 1.37 | 0.85 | 0.70 |
| Sharpe 95% CI | [-0.04, 1.86] | [0.01, 1.91] | [0.60, 2.16] | [0.19, 1.64] | [-0.02, 1.55] |
| Sortino | 1.52 | 1.60 | 2.86 | 1.38 | 1.11 |
| MaxDD (daily) | -40.0% | -39.9% | -18.8% | -17.8% | -21.1% |
| MaxDD peak>trough | 2026-06-30 > 2026-07-29 | 2026-06-30 > 2026-07-29 | 2025-02-19 > 2025-04-08 | 2024-11-29 > 2025-04-08 | 2024-11-25 > 2025-04-08 |
| Calmar | 0.92 | 0.97 | 1.21 | 0.87 | 0.66 |
| Beta vs SPY | 1.68 | 1.68 | – | 0.84 | 0.91 |
| TE vs SPY | 31.9% | 32.0% | – | 7.8% | 8.3% |
| IR vs SPY | 0.54 | 0.59 | – | -0.78 | -0.88 |
| ActiveCAGR vs SPY | 11.4% | 13.1% | – | -5.9% | -7.1% |
| HitRate 1m | 58% | 58% | – | 47% | 33% |
| HitRate 3m | 56% | 59% | – | 26% | 21% |
| HitRate 6m | 68% | 68% | – | 16% | 23% |
| Up capture vs SPY | 141% | 145% | – | 84% | 84% |
| Down capture vs SPY | 36% | 31% | – | 116% | 132% |
| IR vs RSP | 0.72 | – | – | – | – |
| IR vs EW-SP900 | 0.79 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 213 | – | – | – | – |
| Avg holdings | 9.95 | – | – | – | – |
| Annual one-way turnover | 784% | – | – | – | – |

### 2011-14 (2011-02 to 2014-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 47 | 47 | 47 | 47 | 47 |
| CAGR | 11.9% | 13.5% | 15.1% | 15.6% | 16.5% |
| AnnVol | 15.7% | 15.7% | 11.3% | 13.1% | 13.6% |
| Sharpe | 0.79 | 0.88 | 1.30 | 1.17 | 1.19 |
| Sharpe 95% CI | [-0.22, 1.93] | [-0.12, 2.03] | [0.40, 2.52] | [0.26, 2.57] | [0.33, 2.50] |
| Sortino | 1.25 | 1.42 | 2.35 | 2.04 | 2.16 |
| MaxDD (daily) | -29.7% | -29.1% | -18.6% | -22.9% | -23.3% |
| MaxDD peak>trough | 2011-04-21 > 2011-11-25 | 2011-07-07 > 2011-11-25 | 2011-04-29 > 2011-10-03 | 2011-07-07 > 2011-10-03 | 2011-07-07 > 2011-10-03 |
| Calmar | 0.40 | 0.46 | 0.81 | 0.68 | 0.71 |
| Beta vs SPY | 0.96 | 0.96 | – | 1.14 | 1.15 |
| TE vs SPY | 11.3% | 11.4% | – | 2.9% | 4.2% |
| IR vs SPY | -0.20 | -0.07 | – | 0.22 | 0.37 |
| ActiveCAGR vs SPY | -2.8% | -1.4% | – | 0.4% | 1.3% |
| HitRate 1m | 49% | 51% | – | 51% | 51% |
| HitRate 3m | 40% | 42% | – | 53% | 51% |
| HitRate 6m | 36% | 36% | – | 52% | 60% |
| Up capture vs SPY | 98% | 102% | – | 109% | 112% |
| Down capture vs SPY | 120% | 115% | – | 115% | 113% |
| IR vs RSP | -0.26 | – | – | – | – |
| IR vs EW-SP900 | -0.34 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 162 | – | – | – | – |
| Avg holdings | 9.87 | – | – | – | – |
| Annual one-way turnover | 745% | – | – | – | – |

### 2015-18 (2015-01 to 2018-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 48 | 48 | 48 | 48 | 48 |
| CAGR | 4.3% | 5.9% | 7.1% | 5.0% | 6.4% |
| AnnVol | 17.1% | 17.1% | 11.5% | 11.7% | 12.6% |
| Sharpe | 0.29 | 0.37 | 0.58 | 0.41 | 0.49 |
| Sharpe 95% CI | [-0.73, 1.45] | [-0.65, 1.56] | [-0.25, 1.98] | [-0.42, 1.70] | [-0.36, 1.83] |
| Sortino | 0.40 | 0.54 | 0.86 | 0.58 | 0.71 |
| MaxDD (daily) | -33.0% | -32.7% | -19.3% | -19.8% | -21.3% |
| MaxDD peak>trough | 2018-09-04 > 2018-12-24 | 2018-09-04 > 2018-12-24 | 2018-09-20 > 2018-12-24 | 2018-09-21 > 2018-12-24 | 2018-09-21 > 2018-12-24 |
| Calmar | 0.13 | 0.18 | 0.37 | 0.25 | 0.30 |
| Beta vs SPY | 1.07 | 1.07 | – | 0.99 | 1.04 |
| TE vs SPY | 11.9% | 11.9% | – | 2.8% | 4.1% |
| IR vs SPY | -0.16 | -0.03 | – | -0.71 | -0.13 |
| ActiveCAGR vs SPY | -2.6% | -1.1% | – | -1.9% | -0.7% |
| HitRate 1m | 50% | 50% | – | 40% | 48% |
| HitRate 3m | 50% | 52% | – | 28% | 41% |
| HitRate 6m | 56% | 63% | – | 23% | 47% |
| Up capture vs SPY | 93% | 100% | – | 90% | 98% |
| Down capture vs SPY | 105% | 102% | – | 101% | 102% |
| IR vs RSP | 0.01 | – | – | – | – |
| IR vs EW-SP900 | -0.11 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 161 | – | – | – | – |
| Avg holdings | 9.76 | – | – | – | – |
| Annual one-way turnover | 800% | – | – | – | – |

### 2019-22 (2019-01 to 2022-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 48 | 48 | 48 | 48 | 48 |
| CAGR | 9.5% | 11.1% | 13.1% | 13.5% | 14.5% |
| AnnVol | 19.2% | 19.2% | 19.4% | 21.4% | 23.2% |
| Sharpe | 0.51 | 0.59 | 0.67 | 0.65 | 0.65 |
| Sharpe 95% CI | [-0.40, 1.60] | [-0.32, 1.69] | [-0.06, 1.74] | [-0.06, 1.78] | [-0.03, 1.73] |
| Sortino | 0.77 | 0.90 | 1.03 | 0.99 | 1.02 |
| MaxDD (daily) | -29.0% | -28.1% | -33.7% | -39.0% | -40.1% |
| MaxDD peak>trough | 2021-11-09 > 2022-09-26 | 2021-11-09 > 2022-09-26 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.33 | 0.40 | 0.39 | 0.35 | 0.36 |
| Beta vs SPY | 0.62 | 0.62 | – | 1.06 | 1.14 |
| TE vs SPY | 16.8% | 16.8% | – | 5.6% | 7.1% |
| IR vs SPY | -0.19 | -0.11 | – | 0.14 | 0.29 |
| ActiveCAGR vs SPY | -3.2% | -1.7% | – | 0.4% | 1.3% |
| HitRate 1m | 44% | 46% | – | 50% | 54% |
| HitRate 3m | 35% | 37% | – | 46% | 50% |
| HitRate 6m | 37% | 37% | – | 49% | 49% |
| Up capture vs SPY | 66% | 69% | – | 104% | 110% |
| Down capture vs SPY | 59% | 57% | – | 103% | 108% |
| IR vs RSP | -0.21 | – | – | – | – |
| IR vs EW-SP900 | -0.27 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 163 | – | – | – | – |
| Avg holdings | 9.33 | – | – | – | – |
| Annual one-way turnover | 820% | – | – | – | – |

### 2023-26 (2023-01 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 45 | 45 | 45 | 45 | 45 |
| CAGR | 32.3% | 34.3% | 21.7% | 12.7% | 12.9% |
| AnnVol | 35.7% | 35.7% | 12.5% | 13.6% | 14.6% |
| Sharpe | 0.85 | 0.89 | 1.29 | 0.62 | 0.60 |
| Sharpe 95% CI | [0.10, 1.64] | [0.13, 1.69] | [0.70, 2.10] | [-0.00, 1.29] | [-0.05, 1.27] |
| Sortino | 1.43 | 1.51 | 2.58 | 1.00 | 0.98 |
| MaxDD (daily) | -40.0% | -39.9% | -18.8% | -17.8% | -21.1% |
| MaxDD peak>trough | 2026-06-30 > 2026-07-29 | 2026-06-30 > 2026-07-29 | 2025-02-19 > 2025-04-08 | 2024-11-29 > 2025-04-08 | 2024-11-25 > 2025-04-08 |
| Calmar | 0.81 | 0.86 | 1.16 | 0.71 | 0.61 |
| Beta vs SPY | 1.51 | 1.51 | – | 0.90 | 0.98 |
| TE vs SPY | 31.0% | 31.0% | – | 7.7% | 8.0% |
| IR vs SPY | 0.45 | 0.50 | – | -1.00 | -0.92 |
| ActiveCAGR vs SPY | 8.7% | 10.3% | – | -7.4% | -7.3% |
| HitRate 1m | 56% | 56% | – | 44% | 33% |
| HitRate 3m | 53% | 56% | – | 21% | 19% |
| HitRate 6m | 68% | 68% | – | 12% | 18% |
| Up capture vs SPY | 137% | 141% | – | 80% | 84% |
| Down capture vs SPY | 66% | 60% | – | 120% | 130% |
| IR vs RSP | 0.68 | – | – | – | – |
| IR vs EW-SP900 | 0.69 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 203 | – | – | – | – |
| Avg holdings | 9.96 | – | – | – | – |
| Annual one-way turnover | 770% | – | – | – | – |

## T2 Factor regressions (monthly, Newey-West HAC)

alpha is annualised (12 x monthly intercept); loadings show beta (HAC t, L=4). t at L=6 / L=12 are robustness checks; excess = strategy minus rf, active = strategy minus the reference benchmark.

| window | y | model | n | alpha (ann %) | t (L=4) | t (L=6) | t (L=12) | Mkt-RF | SMB | HML | RMW | CMA | Mom | R2 | adj R2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Full | excess vs rf | CAPM | 187 | 2.10 | 0.44 | 0.46 | 0.53 | 0.91 (9.3) |  |  |  |  |  | 0.33 | 0.33 |
| Full | excess vs rf | FF3+MOM | 187 | -1.05 | -0.24 | -0.26 | -0.31 | 1.03 (10.9) | 0.40 (2.7) | -0.01 (-0.1) |  |  | 0.78 (4.1) | 0.50 | 0.49 |
| Full | excess vs rf | FF5+MOM | 187 | 0.29 | 0.07 | 0.07 | 0.09 | 1.02 (12.1) | 0.19 (1.2) | 0.03 (0.2) | -0.56 (-1.9) | 0.07 (0.2) | 0.70 (5.1) | 0.53 | 0.51 |
| Full | active vs SPY | FF5+MOM | 187 | 0.46 | 0.11 | 0.12 | 0.14 | 0.04 (0.4) | 0.31 (2.0) | 0.01 (0.1) | -0.61 (-2.1) | 0.05 (0.1) | 0.70 (5.2) | 0.31 | 0.29 |
| Train | excess vs rf | CAPM | 95 | -2.27 | -0.53 | -0.55 | -0.66 | 1.00 (8.8) |  |  |  |  |  | 0.53 | 0.53 |
| Train | excess vs rf | FF3+MOM | 95 | -2.91 | -0.76 | -0.77 | -0.90 | 0.97 (8.8) | 0.43 (2.8) | -0.15 (-1.2) |  |  | 0.33 (3.0) | 0.62 | 0.60 |
| Train | excess vs rf | FF5+MOM | 95 | -3.02 | -0.76 | -0.78 | -0.98 | 0.95 (7.8) | 0.48 (2.8) | 0.08 (0.4) | 0.24 (0.9) | -0.52 (-1.6) | 0.33 (3.2) | 0.63 | 0.61 |
| Train | active vs SPY | FF5+MOM | 95 | -2.75 | -0.69 | -0.71 | -0.89 | -0.04 (-0.3) | 0.60 (3.6) | 0.08 (0.4) | 0.20 (0.8) | -0.56 (-1.7) | 0.33 (3.2) | 0.26 | 0.21 |
| Test | excess vs rf | CAPM | 92 | 6.33 | 0.74 | 0.79 | 0.92 | 0.86 (6.5) |  |  |  |  |  | 0.27 | 0.26 |
| Test | excess vs rf | FF3+MOM | 92 | 2.42 | 0.32 | 0.34 | 0.40 | 1.07 (8.6) | 0.49 (1.9) | -0.03 (-0.1) |  |  | 1.00 (3.9) | 0.49 | 0.47 |
| Test | excess vs rf | FF5+MOM | 92 | 3.84 | 0.52 | 0.55 | 0.71 | 1.08 (11.1) | 0.16 (0.6) | 0.06 (0.2) | -0.72 (-2.3) | 0.16 (0.4) | 0.83 (4.6) | 0.54 | 0.51 |
| Test | active vs SPY | FF5+MOM | 92 | 3.95 | 0.54 | 0.57 | 0.73 | 0.10 (1.0) | 0.28 (1.1) | 0.03 (0.1) | -0.77 (-2.5) | 0.14 (0.3) | 0.83 (4.8) | 0.39 | 0.35 |


## T7 Short-horizon behaviour (rolling windows from the backtest)

Overlapping compounded windows on daily net returns; excess = strategy minus benchmark. Effective independent windows (`indep.`) are about n/h, so the binomial uncertainty of P(beat) is large; the bracket is a stationary-bootstrap 95% CI.

| vs | window | horizon | windows | indep. | mean excess | 5% | 25% | median | 75% | 95% | worst | P(beat) | P(loss) | P(beat by >2pt) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | Full | 13d | 3927 | 303 | 0.06% | -6.06% | -2.10% | -0.03% | 2.16% | 6.34% | -28.13% | 49.7% [45-55] | 41.3% | 26.4% |
| SPY | Full | 63d | 3877 | 63 | 0.31% | -12.46% | -5.03% | -0.80% | 4.16% | 17.11% | -29.32% | 45.5% [38-57] | 36.3% | 34.4% |
| SPY | Full | 126d | 3814 | 31 | 0.99% | -16.99% | -6.98% | -1.30% | 5.84% | 24.22% | -31.16% | 44.6% [33-58] | 29.9% | 36.1% |
| SPY | Test | 13d | 1935 | 150 | 0.23% | -7.21% | -2.55% | -0.02% | 2.84% | 9.19% | -28.13% | 49.8% [44-57] | 41.1% | 31.2% |
| SPY | Test | 63d | 1885 | 31 | 1.28% | -15.04% | -6.41% | -1.17% | 8.24% | 24.44% | -29.32% | 44.6% [34-62] | 36.7% | 37.5% |
| SPY | Test | 126d | 1822 | 15 | 3.37% | -17.48% | -7.53% | -1.47% | 9.99% | 45.49% | -31.16% | 46.6% [29-66] | 32.2% | 42.2% |
| RSP | Full | 13d | 3927 | 303 | 0.16% | -6.35% | -2.03% | 0.14% | 2.27% | 6.77% | -28.59% | 51.9% [47-57] | 41.3% | 27.5% |
| RSP | Full | 63d | 3877 | 63 | 0.78% | -12.91% | -4.92% | -0.29% | 4.74% | 19.81% | -31.20% | 48.0% [41-60] | 36.3% | 36.9% |
| RSP | Full | 126d | 3814 | 31 | 2.01% | -17.45% | -6.59% | -0.35% | 7.21% | 27.38% | -28.79% | 48.0% [36-62] | 29.9% | 39.9% |
| EW-SP900 | Full | 13d | 3927 | 303 | 0.11% | -6.67% | -2.02% | 0.11% | 2.15% | 6.49% | -27.44% | 51.4% [46-57] | 41.3% | 26.8% |
| EW-SP900 | Full | 63d | 3877 | 63 | 0.52% | -13.59% | -4.95% | -0.45% | 4.40% | 19.45% | -29.59% | 47.2% [40-59] | 36.3% | 36.3% |
| EW-SP900 | Full | 126d | 3814 | 31 | 1.47% | -18.31% | -6.46% | -0.69% | 6.77% | 25.90% | -33.39% | 46.6% [35-61] | 29.9% | 38.4% |

### Forward expectation: P(beat SPY) = Phi(IR x sqrt(h/252))

Backtest IR (full sample, monthly) = 0.08. Haircuts follow McLean & Pontiff (2016): a self-tuned strategy can decay by more than their 26% data-mining cap, so treat these as optimistic.

| scenario | IR | 13d | 63d | 126d |
|---|---|---|---|---|
| IR = 0 (no skill) | 0.00 | 50.0% | 50.0% | 50.0% |
| backtest IR, no haircut | 0.08 | 50.7% | 51.6% | 52.2% |
| haircut 26% (data-mining only) | 0.06 | 50.5% | 51.1% | 51.6% |
| haircut 58% (post-publication) | 0.03 | 50.3% | 50.7% | 50.9% |

## Charts

### C1 Growth of $1

![C1 Growth of $1](quality_momentum_chosen_C1_growth.png)

### C2 Underwater

![C2 Underwater](quality_momentum_chosen_C2_underwater.png)

### C3 Rolling excess and IR

![C3 Rolling excess and IR](quality_momentum_chosen_C3_rolling.png)

### C4 Calendar-year returns

![C4 Calendar-year returns](quality_momentum_chosen_C4_calendar.png)

### C5 Rolling-horizon excess-return histograms

![C5 Rolling-horizon excess-return histograms](quality_momentum_chosen_C5_horizons.png)

### C8 Factor loadings

![C8 Factor loadings](quality_momentum_chosen_C8_loadings.png)

## T3 Overfitting diagnostics (train window)

| diagnostic | value |
|---|---|
| Months / window | 95 / 2011-02-28..2018-12-31 |
| Trials N (ledger, distinct configurations) | 223 |
| Cells in grid / effective trials N_hat | 216 / 39.61 |
| Net Sharpe (annualised) | 0.53 |
| t-stat of mean excess return | 1.48  (vs 2.0: fail; 3.0: fail; 3.39: fail) |
| PSR(0) | 0.920 |
| Expected max Sharpe SR0 of N null trials (annualised) | 0.38 |
| DSR at N = 223 (ledger) | 0.649 |
| DSR at N_hat = 39.61 | 0.728 |
| DSR at N = 216 (grid cells) | 0.651 |
| Bonferroni haircut Sharpe (annualised) / haircut | 0.00 / 100% |
| Minimum track record for PSR(0) >= 95% (years) | 10.79 |
| PBO (CSCV, S=16, selector: plateau) | 70.8%  (12,870 splits) |
| P(OOS Sharpe < 0) of the selected trial | 15.3% |
| Degradation slope (OOS on IS Sharpe; negative = overfit) | -0.75 |

## T3b DSR on the full sample (ledger N)

| diagnostic | value |
|---|---|
| Months / window | 188 / full |
| Trials N (ledger, distinct configurations) | 223 |
| Cells in grid / effective trials N_hat | 216 / 41.79 |
| Net Sharpe (annualised) | 0.61 |
| t-stat of mean excess return | 2.41  (vs 2.0: pass; 3.0: fail; 3.39: fail) |
| PSR(0) | 0.990 |
| Expected max Sharpe SR0 of N null trials (annualised) | 0.34 |
| DSR at N = 223 (ledger) | 0.848 |
| DSR at N_hat = 41.79 | 0.903 |
| DSR at N = 216 (grid cells) | 0.849 |
| Bonferroni haircut Sharpe (annualised) / haircut | 0.00 / 100% |
| Minimum track record for PSR(0) >= 95% (years) | 7.98 |

## T4 Parameter selection (train) and one-look confirmation (test)

- chosen: **order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none** (literature default; FALLBACK: bootstrap stability check failed)
- default: order=MF, shortlist=0.2, x_debt=1, N=10, quality=Q3a, technical=sma_rsi, stop_loss=none, vol_target=none (train Sharpe 0.53)
- train Sharpe of chosen 0.53; plateau score 0.732; peak ratio 1.09; plateau width 3 cells (>= 90% of chosen)
- bootstrap stability (B=500, mean block 6): 18% select exactly this cell, 30% within one grid step -> FAIL
- sensitivity (not used for selection): argmax -> 3dcdc52700 (Sharpe 0.81, MORE THAN one step); lam0 -> d12be4383d (Sharpe 0.80, MORE THAN one step)

Reasons:
- train window 2011-02-28..2018-12-31: 95 months, 216 of 216 cells evaluable; metric = net Sharpe (annualised, excess of rf)
- plateau pick: score 0.732, peak ratio 1.09 (max 1.25)
- categorical plateau scores: technical=none,vol_target=none,quality=Q0=0.520; technical=none,vol_target=none,quality=Q3a=0.480; technical=none,vol_target=none,quality=Q1-50=0.732; technical=none,vol_target=none,quality=Q2-Q50=0.538; technical=none,vol_target=0.2,quality=Q0=0.395; technical=none,vol_target=0.2,quality=Q3a=0.507; technical=none,vol_target=0.2,quality=Q1-50=0.705; technical=none,vol_target=0.2,quality=Q2-Q50=0.541; technical=sma,vol_target=none,quality=Q0=0.489; technical=sma,vol_target=none,quality=Q3a=0.536; technical=sma,vol_target=none,quality=Q1-50=0.669; technical=sma,vol_target=none,quality=Q2-Q50=0.545; technical=sma,vol_target=0.2,quality=Q0=0.449; technical=sma,vol_target=0.2,quality=Q3a=0.567; technical=sma,vol_target=0.2,quality=Q1-50=0.654; technical=sma,vol_target=0.2,quality=Q2-Q50=0.549; technical=sma_rsi,vol_target=none,quality=Q0=0.407; technical=sma_rsi,vol_target=none,quality=Q3a=0.479; technical=sma_rsi,vol_target=none,quality=Q1-50=0.570; technical=sma_rsi,vol_target=none,quality=Q2-Q50=0.394; technical=sma_rsi,vol_target=0.2,quality=Q0=0.511; technical=sma_rsi,vol_target=0.2,quality=Q3a=0.491; technical=sma_rsi,vol_target=0.2,quality=Q1-50=0.618; technical=sma_rsi,vol_target=0.2,quality=Q2-Q50=0.411 (default category kept unless another beats it by >= 0.10)
- bootstrap stability (B=500): 18% exactly this cell, 30% within one grid step (need >= 50%) -> FAIL
- FALLBACK to literature default: bootstrap stability check failed

Neighbourhood of the chosen cell (train):

| role | axis | step | N | stop_loss | technical | vol_target | quality | sharpe |
|---|---|---|---|---|---|---|---|---|
| self |  | 0 | 10 | none | sma_rsi | none | Q3a | 0.53 |
| neighbor | N | -1 | 5 | none | sma_rsi | none | Q3a | 0.48 |
| neighbor | N | 1 | 20 | none | sma_rsi | none | Q3a | 0.57 |
| neighbor | stop_loss | 1 | 10 | 0.15 | sma_rsi | none | Q3a | 0.41 |

Plateau result per categorical level:

| category | n_cells | is_default_category | n_eligible | score | peak_ratio | sharpe | chosen |
|---|---|---|---|---|---|---|---|
| technical=none,vol_target=none,quality=Q0 | 9 | False | 9 | 0.52 | 1.24 | 0.68 | False |
| technical=none,vol_target=none,quality=Q3a | 9 | False | 9 | 0.48 | 1.05 | 0.54 | False |
| technical=none,vol_target=none,quality=Q1-50 | 9 | False | 9 | 0.73 | 1.09 | 0.81 | True |
| technical=none,vol_target=none,quality=Q2-Q50 | 9 | False | 9 | 0.54 | 1.19 | 0.65 | False |
| technical=none,vol_target=0.2,quality=Q0 | 9 | False | 8 | 0.40 | 0.95 | 0.49 | False |
| technical=none,vol_target=0.2,quality=Q3a | 9 | False | 9 | 0.51 | 1.06 | 0.59 | False |
| technical=none,vol_target=0.2,quality=Q1-50 | 9 | False | 9 | 0.71 | 1.08 | 0.80 | False |
| technical=none,vol_target=0.2,quality=Q2-Q50 | 9 | False | 9 | 0.54 | 1.21 | 0.68 | False |
| technical=sma,vol_target=none,quality=Q0 | 9 | False | 7 | 0.49 | 0.82 | 0.54 | False |
| technical=sma,vol_target=none,quality=Q3a | 9 | False | 8 | 0.54 | 1.12 | 0.61 | False |
| technical=sma,vol_target=none,quality=Q1-50 | 9 | False | 9 | 0.67 | 1.12 | 0.76 | False |
| technical=sma,vol_target=none,quality=Q2-Q50 | 9 | False | 9 | 0.55 | 1.19 | 0.67 | False |
| technical=sma,vol_target=0.2,quality=Q0 | 9 | False | 7 | 0.45 | 0.85 | 0.52 | False |
| technical=sma,vol_target=0.2,quality=Q3a | 9 | False | 9 | 0.57 | 1.15 | 0.66 | False |
| technical=sma,vol_target=0.2,quality=Q1-50 | 9 | False | 9 | 0.65 | 1.04 | 0.73 | False |
| technical=sma,vol_target=0.2,quality=Q2-Q50 | 9 | False | 9 | 0.55 | 1.20 | 0.68 | False |
| technical=sma_rsi,vol_target=none,quality=Q0 | 9 | False | 8 | 0.41 | 0.89 | 0.46 | False |
| technical=sma_rsi,vol_target=none,quality=Q3a | 9 | True | 9 | 0.48 | 1.15 | 0.57 | False |
| technical=sma_rsi,vol_target=none,quality=Q1-50 | 9 | False | 9 | 0.57 | 1.18 | 0.70 | False |
| technical=sma_rsi,vol_target=none,quality=Q2-Q50 | 9 | False | 8 | 0.39 | 1.18 | 0.48 | False |
| technical=sma_rsi,vol_target=0.2,quality=Q0 | 9 | False | 9 | 0.51 | 1.24 | 0.66 | False |
| technical=sma_rsi,vol_target=0.2,quality=Q3a | 9 | False | 9 | 0.49 | 1.10 | 0.58 | False |
| technical=sma_rsi,vol_target=0.2,quality=Q1-50 | 9 | False | 9 | 0.62 | 1.15 | 0.73 | False |
| technical=sma_rsi,vol_target=0.2,quality=Q2-Q50 | 9 | False | 8 | 0.41 | 1.16 | 0.49 | False |

Confirmation on the untouched test window 2019-01-01 to 2026-09-30:

| cell | sharpe | cagr | vol | maxdd | tstat | n_months |
|---|---|---|---|---|---|---|
| chosen | 0.69 | 20.0% | 28.4% | -32.7% | 1.93 | 93 |
| default | 0.69 | 20.0% | 28.4% | -32.7% | 1.93 | 93 |
| grid_median | 0.64 | 15.0% | 20.4% | -28.8% | 1.78 | 93 |

- chosen minus default Sharpe: 0.00; chosen minus grid median: 0.05; rank percentile among cells: 66%
- Spearman(train Sharpe, test Sharpe) across cells: 0.36; test/train Sharpe of the chosen cell: 1.32
- criteria: test_sharpe_positive=yes, test_ge_half_train=yes, landscape_persists=yes, beats_grid_median=yes

## T4b Parameter regression over the grid (train)

Response: net Sharpe of each of 216 grid cells on 2011-02-28..2018-12-31; ordinal parameters scaled to [-1, 1]; R2 = 0.72. Bootstrap SDs resample months jointly across cells (B=500); cells overlap, so OLS p-values would be meaningless. A flat surface (small coefficients, low R2) is good news.

| term | coef | bootstrap SD | coef / SD |
|---|---|---|---|
| const | 0.444 | 0.358 | 1.2 |
| N | 0.007 | 0.061 | 0.1 |
| stop_loss | -0.106 | 0.047 | -2.3 |
| N^2 | 0.048 | 0.032 | 1.5 |
| stop_loss^2 | -0.005 | 0.059 | -0.1 |
| N*stop_loss | -0.009 | 0.018 | -0.5 |
| technical=sma | 0.023 | 0.021 | 1.1 |
| technical=sma_rsi | -0.043 | 0.149 | -0.3 |
| vol_target=none | -0.006 | 0.025 | -0.2 |
| quality=Q1-50 | 0.159 | 0.152 | 1.0 |
| quality=Q2-Q50 | -0.007 | 0.124 | -0.1 |
| quality=Q3a | 0.018 | 0.159 | 0.1 |

## T5 Robustness (each run is a ledger trial)

Full-period net results of one-at-a-time changes around the chosen cell. Every run is logged in the ledger as an extra trial (it raises N for the DSR).

| run | full CAGR | full Sharpe | train Sharpe | test Sharpe | test CAGR | MaxDD | turnover/yr | FF5+MOM alpha | IR vs SPY | IR vs EW |
|---|---|---|---|---|---|---|---|---|---|---|
| chosen (base, 10 bps) | 13.8% | 0.61 | 0.53 | 0.69 | 20.0% | -40.0% | 784% | 0.3% (t=0.07) | 0.08 | 0.12 |
| cost 0 bps | 15.5% | 0.67 | 0.62 | 0.74 | 21.8% | -39.9% | 784% | 1.8% (t=0.43) | 0.16 | 0.20 |
| cost 25 bps | 11.3% | 0.51 | 0.39 | 0.61 | 17.3% | -40.1% | 784% | -2.0% (t=-0.48) | -0.04 | 0.01 |
| cost 50 bps | 7.2% | 0.35 | 0.16 | 0.48 | 13.0% | -42.0% | 784% | -5.7% (t=-1.39) | -0.24 | -0.18 |
| quality arm Q4-0.25 (blend) | 11.9% | 0.56 | 0.65 | 0.52 | 13.6% | -37.4% | 753% | -3.1% (t=-1.06) | -0.03 | 0.03 |
| quality arm Q4-0.5 (blend) | 10.8% | 0.55 | 0.70 | 0.46 | 11.0% | -34.1% | 736% | -4.0% (t=-1.65) | -0.16 | -0.08 |
| order QF (quality first) | 15.0% | 0.65 | 0.57 | 0.74 | 21.6% | -40.0% | 783% | 1.0% (t=0.23) | 0.14 | 0.18 |
| trend_exit_daily (sell below SMA200 daily) | 10.1% | 0.46 | 0.37 | 0.54 | 15.0% | -42.2% | 909% | -3.0% (t=-0.70) | -0.09 | -0.04 |

## T6 Bias stress and survivorship

SURVIVORSHIP-BIASED (yfinance has no delisted names): 81.0% of point-in-time S&P 900 members have a price history (monthly mean 2011-2026, minimum 63.2%); EW-SP900 minus RSP = +0.5%/yr CAGR gap (EW-SP500 minus RSP +0.9%/yr, the like-for-like bias proxy; the S&P 900 gap also contains the mid-cap premium); see output/survivorship.md

Break-even drag (alpha = 0): 29 bps/yr.

| assumed drag (bps/yr) | FF5+MOM alpha after drag | t |
|---|---|---|
| 0 | 0.29% | 0.07 |
| 50 | -0.21% | -0.05 |
| 100 | -0.71% | -0.17 |
| 150 | -1.21% | -0.30 |
| 200 | -1.71% | -0.42 |
| 300 | -2.71% | -0.66 |

Coverage by year and the EW-minus-RSP gap are in `output/survivorship.md`. Overall: share with prices 81.0%; EW-SP900 minus RSP +0.48%/yr.

## Evidence ladder (research/06 section 5.7)

**1/7 criteria passed -> does not work (failed: #1, #2, #3, #5, #6, #7); fewer than 5/7: do not claim it works, hold it as a research hypothesis at a modest weight**

| # | criterion | pass | evidence |
|---|---|---|---|
| 1 | Direction replicates: net IR vs same-universe EW > 0 on train AND test | NO | IR train -0.22, test 0.29 |
| 2 | Plateau: chosen cell passes the 5.4 eligibility and bootstrap stability | NO | FALLBACK to default: bootstrap stability check failed; stability 30% within one step |
| 3 | Costs: FF5+MOM net alpha still > 0 at 25 bps one-way | NO | alpha -2.0%/yr (t=-0.48) at 25 bps; buy/hold-spread check for momentum not run |
| 4 | Factor view: FF5+MOM alpha > 0, or explained by the expected factors with no large negative alpha | yes | alpha 0.3%/yr (t=0.07, full sample to 2026-08, French data end 2026-08); expected-factor loadings with abs(t) > 2: Mom 0.70 (t=5.1) |
| 5 | Overfitting: PBO < 0.5 (DSR at N_hat and haircut Sharpe reported) | NO | PBO 70.8%; DSR(ledger N=223) 0.649, DSR(N_hat=39.61) 0.728; haircut Sharpe 0.00 (train, aim DSR > 0.5: met) |
| 6 | Bias stress: FF5+MOM alpha survives a 150 bps/yr survivorship drag | NO | break-even drag 29 bps/yr (alpha 0.29%); active CAGR vs EW-SP900 1.1% |
| 7 | Subperiods: positive active return vs SPY in at least 3 of 4 subperiods | NO | 1 of 4 positive (2011-14 -2.8%, 2015-18 -2.6%, 2019-22 -3.2%, 2023-26 8.7%); worst 12m active return vs SPY -32.6% |

## Assumptions and limitations

- Returns are net of the stated trading costs (per side, on traded notional); signals at the close of day t, trades at the close of t+1; point-in-time rule: filings usable only if filed strictly before the signal date.
- Survivorship, XBRL tag mapping and a short test window limit what can be concluded; see the header and the coverage audit.
- Sharpe ratios are annualised from monthly data with sqrt(12), exact only for iid returns; HAC t-statistics over-reject in short samples.
- Expected decay: published anomalies lose roughly a quarter to a half of their returns out of sample and after publication (McLean & Pontiff 2016, Journal of Finance 71(1)); parameters were fixed on the train window with a pre-registered plateau rule and confirmed once on the test window, so the live result should be expected to be smaller than the backtest.

