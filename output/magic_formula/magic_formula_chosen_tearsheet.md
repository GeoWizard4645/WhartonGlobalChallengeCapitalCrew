# Magic formula (chosen): tear sheet

| item | value |
|---|---|
| Generated | 2026-10-19 04:12 UTC |
| Data | 2011-10-03 to 2026-09-30 (3,770 trading days) |
| Benchmarks | SPY, RSP, EW-SP900 (reference: SPY) |
| strategy | Magic Formula (magic_formula) |
| parameter set | ranking=MF, n=25, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc  [plateau_v1 choice] |
| literature default | ranking=MF, n=30, min_cap=1e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc |
| universe | point-in-time S&P 900 (S&P 500 + MidCap 400) ex GICS Financials, Real Estate and Utilities, raw price >= $5 |
| windows | train 2011-10 to 2018-12; test 2019-01 to 2026-09 (single look); data end 2026-10-16 |
| trials N (ledger, distinct) | 38 |
| grid | 18 pre-registered cells, registered 2026-10-19T02:57:36+00:00 |
| costs | 10 bps one-way on every buy and sell (robustness 0/25/50) |
| timing | signal at the close of the month-end, trade at the next close; filings usable only if filed strictly before the signal date |
| survivorship | SURVIVORSHIP-BIASED (yfinance has no delisted names): 81.0% of point-in-time S&P 900 members have a price history (monthly mean 2011-2026, minimum 63.2%); EW-SP900 minus RSP = +0.5%/yr CAGR gap (EW-SP500 minus RSP +0.9%/yr, the like-for-like bias proxy; the S&P 900 gap also contains the mid-cap premium); see output/survivorship.md |
| benchmarks | SPY, RSP, EW-SP900 = equal-weight S&P 900 with the strategy's sector exclusions (Financials, Real Estate, Utilities), 10 bps |
| git commit | 2c7657cd70 |
| tear sheet for | chosen |

## T1 Performance, net of costs

Monthly statistics from calendar-month compounded daily returns (partial leading/trailing months dropped); MaxDD is daily. Benchmark-relative rows are vs SPY; Sharpe CI = stationary bootstrap (mean block 6, B=500).

### Full (2011-10 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 180 | 180 | 180 | 180 | 180 |
| CAGR | 14.9% | 15.0% | 15.6% | 13.2% | 14.7% |
| AnnVol | 16.9% | 16.9% | 14.0% | 15.3% | 17.5% |
| Sharpe | 0.81 | 0.82 | 0.99 | 0.78 | 0.78 |
| Sharpe 95% CI | [0.38, 1.25] | [0.39, 1.26] | [0.52, 1.51] | [0.34, 1.26] | [0.34, 1.24] |
| Sortino | 1.40 | 1.41 | 1.62 | 1.24 | 1.29 |
| MaxDD (daily) | -35.3% | -35.2% | -33.7% | -39.0% | -40.5% |
| MaxDD peak>trough | 2020-01-16 > 2020-03-23 | 2020-01-16 > 2020-03-23 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.42 | 0.43 | 0.46 | 0.34 | 0.36 |
| Beta vs SPY | 1.06 | 1.06 | – | 1.02 | 1.15 |
| TE vs SPY | 8.0% | 8.0% | – | 5.2% | 6.9% |
| IR vs SPY | -0.02 | -0.00 | – | -0.36 | -0.03 |
| ActiveCAGR vs SPY | -0.6% | -0.4% | – | -2.0% | -0.7% |
| HitRate 1m | 47% | 47% | – | 46% | 48% |
| HitRate 3m | 47% | 47% | – | 39% | 44% |
| HitRate 6m | 47% | 47% | – | 38% | 48% |
| Up capture vs SPY | 104% | 104% | – | 96% | 106% |
| Down capture vs SPY | 109% | 109% | – | 106% | 115% |
| IR vs RSP | 0.26 | – | – | – | – |
| IR vs EW-SP900 | 0.01 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 14 | – | – | – | – |
| Avg holdings | 47.58 | – | – | – | – |
| Annual one-way turnover | 64% | – | – | – | – |

### Train (2011-10 to 2018-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 87 | 87 | 87 | 87 | 87 |
| CAGR | 16.4% | 16.5% | 13.8% | 13.3% | 15.5% |
| AnnVol | 13.9% | 13.9% | 11.1% | 11.9% | 14.2% |
| Sharpe | 1.13 | 1.13 | 1.18 | 1.07 | 1.05 |
| Sharpe 95% CI | [0.55, 2.04] | [0.55, 2.05] | [0.62, 2.09] | [0.50, 1.85] | [0.53, 1.83] |
| Sortino | 2.12 | 2.14 | 2.01 | 1.84 | 1.91 |
| MaxDD (daily) | -25.6% | -25.5% | -19.3% | -19.8% | -22.7% |
| MaxDD peak>trough | 2018-01-26 > 2018-12-24 | 2018-01-26 > 2018-12-24 | 2018-09-20 > 2018-12-24 | 2018-09-21 > 2018-12-24 | 2018-09-20 > 2018-12-24 |
| Calmar | 0.64 | 0.65 | 0.72 | 0.67 | 0.68 |
| Beta vs SPY | 1.13 | 1.13 | – | 1.04 | 1.20 |
| TE vs SPY | 6.2% | 6.3% | – | 2.7% | 5.5% |
| IR vs SPY | 0.41 | 0.43 | – | -0.14 | 0.33 |
| ActiveCAGR vs SPY | 2.2% | 2.3% | – | -0.5% | 1.4% |
| HitRate 1m | 51% | 51% | – | 45% | 51% |
| HitRate 3m | 55% | 55% | – | 42% | 49% |
| HitRate 6m | 62% | 62% | – | 44% | 61% |
| Up capture vs SPY | 106% | 106% | – | 99% | 112% |
| Down capture vs SPY | 87% | 87% | – | 103% | 110% |
| IR vs RSP | 0.54 | – | – | – | – |
| IR vs EW-SP900 | 0.15 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 14 | – | – | – | – |
| Avg holdings | 45.11 | – | – | – | – |
| Annual one-way turnover | 67% | – | – | – | – |

### Test (2019-01 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 93 | 93 | 93 | 93 | 93 |
| CAGR | 13.6% | 13.7% | 17.2% | 13.1% | 14.0% |
| AnnVol | 19.3% | 19.3% | 16.4% | 17.9% | 20.1% |
| Sharpe | 0.61 | 0.62 | 0.89 | 0.63 | 0.62 |
| Sharpe 95% CI | [0.13, 1.16] | [0.14, 1.16] | [0.35, 1.59] | [0.10, 1.33] | [0.09, 1.27] |
| Sortino | 1.02 | 1.03 | 1.44 | 0.97 | 0.98 |
| MaxDD (daily) | -35.3% | -35.2% | -33.7% | -39.0% | -40.5% |
| MaxDD peak>trough | 2020-01-16 > 2020-03-23 | 2020-01-16 > 2020-03-23 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.38 | 0.39 | 0.51 | 0.34 | 0.35 |
| Beta vs SPY | 1.03 | 1.03 | – | 1.02 | 1.14 |
| TE vs SPY | 9.4% | 9.4% | – | 6.8% | 8.0% |
| IR vs SPY | -0.29 | -0.27 | – | -0.49 | -0.26 |
| ActiveCAGR vs SPY | -3.1% | -3.0% | – | -3.5% | -2.7% |
| HitRate 1m | 43% | 43% | – | 47% | 45% |
| HitRate 3m | 40% | 40% | – | 35% | 37% |
| HitRate 6m | 36% | 36% | – | 32% | 39% |
| Up capture vs SPY | 102% | 102% | – | 93% | 102% |
| Down capture vs SPY | 122% | 122% | – | 107% | 118% |
| IR vs RSP | 0.08 | – | – | – | – |
| IR vs EW-SP900 | -0.07 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 14 | – | – | – | – |
| Avg holdings | 49.89 | – | – | – | – |
| Annual one-way turnover | 61% | – | – | – | – |

### Last 36m (2023-10 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 36 | 36 | 36 | 36 | 36 |
| CAGR | 15.0% | 15.2% | 22.8% | 15.5% | 13.8% |
| AnnVol | 15.6% | 15.6% | 12.4% | 12.9% | 14.4% |
| Sharpe | 0.70 | 0.71 | 1.37 | 0.85 | 0.67 |
| Sharpe 95% CI | [0.06, 1.33] | [0.07, 1.34] | [0.60, 2.16] | [0.19, 1.64] | [-0.09, 1.52] |
| Sortino | 1.18 | 1.20 | 2.86 | 1.38 | 1.05 |
| MaxDD (daily) | -15.5% | -15.5% | -18.8% | -17.8% | -22.2% |
| MaxDD peak>trough | 2025-02-19 > 2025-04-08 | 2025-02-19 > 2025-04-08 | 2025-02-19 > 2025-04-08 | 2024-11-29 > 2025-04-08 | 2024-11-25 > 2025-04-08 |
| Calmar | 0.97 | 0.98 | 1.21 | 0.87 | 0.62 |
| Beta vs SPY | 0.95 | 0.95 | – | 0.84 | 0.96 |
| TE vs SPY | 10.2% | 10.2% | – | 7.8% | 8.2% |
| IR vs SPY | -0.61 | -0.59 | – | -0.78 | -0.91 |
| ActiveCAGR vs SPY | -6.3% | -6.2% | – | -5.9% | -7.3% |
| HitRate 1m | 31% | 31% | – | 47% | 33% |
| HitRate 3m | 35% | 35% | – | 26% | 24% |
| HitRate 6m | 26% | 26% | – | 16% | 23% |
| Up capture vs SPY | 100% | 100% | – | 84% | 86% |
| Down capture vs SPY | 175% | 174% | – | 116% | 142% |
| IR vs RSP | -0.01 | – | – | – | – |
| IR vs EW-SP900 | 0.14 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 14 | – | – | – | – |
| Avg holdings | 49.11 | – | – | – | – |
| Annual one-way turnover | 61% | – | – | – | – |

### 2011-14 (2011-10 to 2014-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 39 | 39 | 39 | 39 | 39 |
| CAGR | 29.8% | 30.0% | 22.7% | 24.4% | 28.0% |
| AnnVol | 14.0% | 14.1% | 10.3% | 11.7% | 14.6% |
| Sharpe | 1.94 | 1.95 | 2.05 | 1.94 | 1.77 |
| Sharpe 95% CI | [1.31, 2.89] | [1.31, 2.90] | [1.36, 2.83] | [1.24, 2.86] | [1.17, 2.75] |
| Sortino | 6.04 | 6.08 | 4.64 | 4.50 | 4.90 |
| MaxDD (daily) | -10.0% | -10.0% | -9.7% | -11.2% | -11.4% |
| MaxDD peak>trough | 2012-04-02 > 2012-06-01 | 2012-04-02 > 2012-06-01 | 2012-04-02 > 2012-06-04 | 2012-03-26 > 2012-06-04 | 2012-03-26 > 2012-06-04 |
| Calmar | 2.99 | 3.01 | 2.34 | 2.17 | 2.45 |
| Beta vs SPY | 1.25 | 1.25 | – | 1.11 | 1.33 |
| TE vs SPY | 6.2% | 6.2% | – | 2.6% | 6.2% |
| IR vs SPY | 1.00 | 1.01 | – | 0.59 | 0.78 |
| ActiveCAGR vs SPY | 5.8% | 6.0% | – | 1.4% | 4.3% |
| HitRate 1m | 56% | 56% | – | 51% | 51% |
| HitRate 3m | 68% | 68% | – | 57% | 57% |
| HitRate 6m | 68% | 68% | – | 62% | 65% |
| Up capture vs SPY | 118% | 119% | – | 107% | 120% |
| Down capture vs SPY | 80% | 80% | – | 107% | 111% |
| IR vs RSP | 0.84 | – | – | – | – |
| IR vs EW-SP900 | 0.28 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 16 | – | – | – | – |
| Avg holdings | 41.05 | – | – | – | – |
| Annual one-way turnover | 78% | – | – | – | – |

### 2015-18 (2015-01 to 2018-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 48 | 48 | 48 | 48 | 48 |
| CAGR | 6.4% | 6.6% | 7.1% | 5.0% | 6.2% |
| AnnVol | 13.4% | 13.4% | 11.5% | 11.7% | 13.5% |
| Sharpe | 0.47 | 0.48 | 0.58 | 0.41 | 0.45 |
| Sharpe 95% CI | [-0.44, 1.73] | [-0.43, 1.74] | [-0.25, 1.98] | [-0.42, 1.70] | [-0.40, 1.76] |
| Sortino | 0.70 | 0.71 | 0.86 | 0.58 | 0.65 |
| MaxDD (daily) | -25.6% | -25.5% | -19.3% | -19.8% | -22.7% |
| MaxDD peak>trough | 2018-01-26 > 2018-12-24 | 2018-01-26 > 2018-12-24 | 2018-09-20 > 2018-12-24 | 2018-09-21 > 2018-12-24 | 2018-09-20 > 2018-12-24 |
| Calmar | 0.25 | 0.26 | 0.37 | 0.25 | 0.27 |
| Beta vs SPY | 1.03 | 1.03 | – | 0.99 | 1.10 |
| TE vs SPY | 6.2% | 6.2% | – | 2.8% | 4.7% |
| IR vs SPY | -0.07 | -0.05 | – | -0.71 | -0.14 |
| ActiveCAGR vs SPY | -0.6% | -0.5% | – | -1.9% | -0.9% |
| HitRate 1m | 46% | 46% | – | 40% | 50% |
| HitRate 3m | 43% | 43% | – | 28% | 41% |
| HitRate 6m | 53% | 53% | – | 23% | 58% |
| Up capture vs SPY | 92% | 92% | – | 90% | 102% |
| Down capture vs SPY | 90% | 90% | – | 101% | 109% |
| IR vs RSP | 0.29 | – | – | – | – |
| IR vs EW-SP900 | 0.04 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 12 | – | – | – | – |
| Avg holdings | 48.41 | – | – | – | – |
| Annual one-way turnover | 57% | – | – | – | – |

### 2019-22 (2019-01 to 2022-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 48 | 48 | 48 | 48 | 48 |
| CAGR | 14.4% | 14.5% | 13.1% | 13.5% | 14.8% |
| AnnVol | 22.1% | 22.1% | 19.4% | 21.4% | 24.0% |
| Sharpe | 0.67 | 0.67 | 0.67 | 0.65 | 0.65 |
| Sharpe 95% CI | [0.00, 1.52] | [0.01, 1.53] | [-0.06, 1.74] | [-0.06, 1.78] | [-0.03, 1.71] |
| Sortino | 1.10 | 1.11 | 1.03 | 0.99 | 1.02 |
| MaxDD (daily) | -35.3% | -35.2% | -33.7% | -39.0% | -40.5% |
| MaxDD peak>trough | 2020-01-16 > 2020-03-23 | 2020-01-16 > 2020-03-23 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.41 | 0.41 | 0.39 | 0.35 | 0.37 |
| Beta vs SPY | 1.04 | 1.04 | – | 1.06 | 1.18 |
| TE vs SPY | 8.8% | 8.8% | – | 5.6% | 7.8% |
| IR vs SPY | 0.19 | 0.20 | – | 0.14 | 0.32 |
| ActiveCAGR vs SPY | 1.2% | 1.3% | – | 0.4% | 1.5% |
| HitRate 1m | 54% | 54% | – | 50% | 54% |
| HitRate 3m | 46% | 46% | – | 46% | 50% |
| HitRate 6m | 49% | 49% | – | 49% | 53% |
| Up capture vs SPY | 108% | 109% | – | 104% | 114% |
| Down capture vs SPY | 106% | 106% | – | 103% | 111% |
| IR vs RSP | 0.11 | – | – | – | – |
| IR vs EW-SP900 | -0.11 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 14 | – | – | – | – |
| Avg holdings | 51.06 | – | – | – | – |
| Annual one-way turnover | 62% | – | – | – | – |

### 2023-26 (2023-01 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 45 | 45 | 45 | 45 | 45 |
| CAGR | 12.7% | 12.8% | 21.7% | 12.7% | 13.1% |
| AnnVol | 16.1% | 16.1% | 12.5% | 13.6% | 15.1% |
| Sharpe | 0.55 | 0.55 | 1.29 | 0.62 | 0.60 |
| Sharpe 95% CI | [-0.02, 1.11] | [-0.01, 1.12] | [0.70, 2.10] | [-0.00, 1.29] | [-0.04, 1.28] |
| Sortino | 0.93 | 0.94 | 2.58 | 1.00 | 0.99 |
| MaxDD (daily) | -15.5% | -15.5% | -18.8% | -17.8% | -22.2% |
| MaxDD peak>trough | 2025-02-19 > 2025-04-08 | 2025-02-19 > 2025-04-08 | 2025-02-19 > 2025-04-08 | 2024-11-29 > 2025-04-08 | 2024-11-25 > 2025-04-08 |
| Calmar | 0.82 | 0.83 | 1.16 | 0.71 | 0.59 |
| Beta vs SPY | 1.01 | 1.01 | – | 0.90 | 1.02 |
| TE vs SPY | 9.9% | 9.9% | – | 7.7% | 8.1% |
| IR vs SPY | -0.74 | -0.73 | – | -1.00 | -0.87 |
| ActiveCAGR vs SPY | -7.4% | -7.3% | – | -7.4% | -7.1% |
| HitRate 1m | 31% | 31% | – | 44% | 36% |
| HitRate 3m | 30% | 30% | – | 21% | 21% |
| HitRate 6m | 20% | 20% | – | 12% | 18% |
| Up capture vs SPY | 94% | 94% | – | 80% | 87% |
| Down capture vs SPY | 162% | 162% | – | 120% | 136% |
| IR vs RSP | 0.04 | – | – | – | – |
| IR vs EW-SP900 | -0.03 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 14 | – | – | – | – |
| Avg holdings | 48.64 | – | – | – | – |
| Annual one-way turnover | 61% | – | – | – | – |

## T2 Factor regressions (monthly, Newey-West HAC)

alpha is annualised (12 x monthly intercept); loadings show beta (HAC t, L=4). t at L=6 / L=12 are robustness checks; excess = strategy minus rf, active = strategy minus the reference benchmark.

| window | y | model | n | alpha (ann %) | t (L=4) | t (L=6) | t (L=12) | Mkt-RF | SMB | HML | RMW | CMA | Mom | R2 | adj R2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Full | excess vs rf | CAPM | 179 | -0.16 | -0.08 | -0.08 | -0.08 | 1.02 (19.7) |  |  |  |  |  | 0.79 | 0.79 |
| Full | excess vs rf | FF3+MOM | 179 | 0.98 | 0.49 | 0.49 | 0.51 | 0.97 (16.5) | 0.06 (1.1) | 0.16 (2.2) |  |  | -0.14 (-2.1) | 0.82 | 0.82 |
| Full | excess vs rf | FF5+MOM | 179 | 0.56 | 0.29 | 0.29 | 0.30 | 0.99 (16.5) | 0.15 (2.3) | 0.05 (0.6) | 0.22 (2.8) | 0.15 (1.4) | -0.12 (-2.1) | 0.84 | 0.83 |
| Full | active vs SPY | FF5+MOM | 179 | 0.75 | 0.39 | 0.39 | 0.40 | 0.00 (0.0) | 0.27 (4.1) | 0.03 (0.4) | 0.17 (2.3) | 0.13 (1.2) | -0.13 (-2.1) | 0.26 | 0.23 |
| Train | excess vs rf | CAPM | 87 | 0.86 | 0.46 | 0.45 | 0.42 | 1.10 (12.8) |  |  |  |  |  | 0.83 | 0.83 |
| Train | excess vs rf | FF3+MOM | 87 | 1.64 | 0.79 | 0.79 | 0.78 | 1.06 (12.2) | 0.09 (1.0) | -0.07 (-0.8) |  |  | -0.07 (-1.2) | 0.83 | 0.82 |
| Train | excess vs rf | FF5+MOM | 87 | 1.46 | 0.78 | 0.77 | 0.74 | 1.08 (12.6) | 0.20 (2.0) | -0.06 (-0.5) | 0.37 (2.3) | -0.02 (-0.2) | -0.07 (-1.2) | 0.85 | 0.83 |
| Train | active vs SPY | FF5+MOM | 87 | 1.78 | 0.94 | 0.95 | 0.91 | 0.09 (1.1) | 0.32 (3.1) | -0.05 (-0.4) | 0.34 (2.1) | -0.06 (-0.4) | -0.07 (-1.3) | 0.21 | 0.15 |
| Test | excess vs rf | CAPM | 92 | -1.62 | -0.51 | -0.55 | -0.61 | 0.99 (16.7) |  |  |  |  |  | 0.77 | 0.77 |
| Test | excess vs rf | FF3+MOM | 92 | -0.55 | -0.18 | -0.19 | -0.20 | 0.93 (12.6) | -0.01 (-0.1) | 0.23 (2.7) |  |  | -0.22 (-2.8) | 0.84 | 0.84 |
| Test | excess vs rf | FF5+MOM | 92 | -0.91 | -0.32 | -0.33 | -0.39 | 0.95 (13.2) | 0.07 (0.8) | 0.10 (0.9) | 0.13 (1.5) | 0.22 (1.6) | -0.21 (-2.8) | 0.85 | 0.84 |
| Test | active vs SPY | FF5+MOM | 92 | -0.80 | -0.28 | -0.29 | -0.34 | -0.04 (-0.6) | 0.19 (2.1) | 0.07 (0.6) | 0.09 (1.1) | 0.20 (1.4) | -0.21 (-2.7) | 0.36 | 0.31 |


## T7 Short-horizon behaviour (rolling windows from the backtest)

Overlapping compounded windows on daily net returns; excess = strategy minus benchmark. Effective independent windows (`indep.`) are about n/h, so the binomial uncertainty of P(beat) is large; the bracket is a stationary-bootstrap 95% CI.

| vs | window | horizon | windows | indep. | mean excess | 5% | 25% | median | 75% | 95% | worst | P(beat) | P(loss) | P(beat by >2pt) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | Full | 13d | 3758 | 290 | -0.02% | -2.97% | -1.07% | 0.00% | 1.02% | 2.78% | -6.75% | 50.2% [45-55] | 37.6% | 10.6% |
| SPY | Full | 63d | 3708 | 60 | -0.16% | -6.33% | -2.58% | -0.21% | 2.33% | 5.85% | -12.80% | 47.5% [38-59] | 27.7% | 27.3% |
| SPY | Full | 126d | 3645 | 30 | -0.49% | -9.22% | -4.15% | -0.31% | 2.87% | 8.76% | -15.45% | 47.7% [35-64] | 20.9% | 31.5% |
| SPY | Test | 13d | 1935 | 150 | -0.14% | -3.55% | -1.57% | -0.16% | 1.26% | 3.39% | -6.75% | 47.0% [40-54] | 39.3% | 14.9% |
| SPY | Test | 63d | 1885 | 31 | -0.74% | -8.08% | -3.77% | -1.23% | 2.11% | 7.49% | -12.80% | 41.0% [29-55] | 32.5% | 26.0% |
| SPY | Test | 126d | 1822 | 15 | -1.70% | -10.47% | -6.04% | -2.05% | 2.15% | 9.49% | -15.45% | 38.4% [20-56] | 24.8% | 26.0% |
| RSP | Full | 13d | 3758 | 290 | 0.07% | -2.10% | -0.75% | 0.09% | 0.90% | 2.35% | -9.70% | 52.6% [48-58] | 37.6% | 7.6% |
| RSP | Full | 63d | 3708 | 60 | 0.29% | -4.53% | -1.64% | 0.25% | 2.05% | 5.30% | -10.56% | 53.5% [44-65] | 27.7% | 25.6% |
| RSP | Full | 126d | 3645 | 30 | 0.48% | -6.77% | -2.21% | 0.44% | 2.98% | 7.81% | -12.22% | 55.6% [41-71] | 20.9% | 33.3% |
| EW-SP900 | Full | 13d | 3758 | 290 | 0.01% | -2.08% | -0.86% | -0.02% | 0.87% | 2.30% | -10.54% | 49.3% [45-55] | 37.6% | 7.9% |
| EW-SP900 | Full | 63d | 3708 | 60 | -0.01% | -5.65% | -1.80% | 0.10% | 1.96% | 5.39% | -16.36% | 51.7% [40-61] | 27.7% | 24.5% |
| EW-SP900 | Full | 126d | 3645 | 30 | -0.08% | -8.48% | -2.86% | 0.47% | 2.68% | 7.48% | -19.85% | 54.9% [39-67] | 20.9% | 32.4% |

### Forward expectation: P(beat SPY) = Phi(IR x sqrt(h/252))

Backtest IR (full sample, monthly) = -0.02. Haircuts follow McLean & Pontiff (2016): a self-tuned strategy can decay by more than their 26% data-mining cap, so treat these as optimistic.

| scenario | IR | 13d | 63d | 126d |
|---|---|---|---|---|
| IR = 0 (no skill) | 0.00 | 50.0% | 50.0% | 50.0% |
| backtest IR, no haircut | -0.02 | 49.8% | 49.6% | 49.5% |
| haircut 26% (data-mining only) | -0.01 | 49.9% | 49.7% | 49.6% |
| haircut 58% (post-publication) | -0.01 | 49.9% | 49.8% | 49.8% |

## Charts

### C1 Growth of $1

![C1 Growth of $1](magic_formula_chosen_C1_growth.png)

### C2 Underwater

![C2 Underwater](magic_formula_chosen_C2_underwater.png)

### C3 Rolling excess and IR

![C3 Rolling excess and IR](magic_formula_chosen_C3_rolling.png)

### C4 Calendar-year returns

![C4 Calendar-year returns](magic_formula_chosen_C4_calendar.png)

### C5 Rolling-horizon excess-return histograms

![C5 Rolling-horizon excess-return histograms](magic_formula_chosen_C5_horizons.png)

### C8 Factor loadings

![C8 Factor loadings](magic_formula_chosen_C8_loadings.png)

## T3 Overfitting diagnostics (train window)

| diagnostic | value |
|---|---|
| Months / window | 87 / 2011-10-31..2018-12-31 |
| Trials N (ledger, distinct configurations) | 38 |
| Cells in grid / effective trials N_hat | 18 / 1.20 |
| Net Sharpe (annualised) | 1.13 |
| t-stat of mean excess return | 3.03  (vs 2.0: pass; 3.0: pass; 3.39: fail) |
| PSR(0) | 0.999 |
| Expected max Sharpe SR0 of N null trials (annualised) | 0.13 |
| DSR at N = 38 (ledger) | 0.996 |
| DSR at N_hat = 1.20 | 0.999 |
| DSR at N = 18 (grid cells) | 0.996 |
| Bonferroni haircut Sharpe (annualised) / haircut | 0.63 / 44% |
| Minimum track record for PSR(0) >= 95% (years) | 2.28 |
| PBO (CSCV, S=16, selector: plateau) | 30.1%  (12,870 splits) |
| P(OOS Sharpe < 0) of the selected trial | 0.6% |
| Degradation slope (OOS on IS Sharpe; negative = overfit) | -0.91 |

## T3b DSR on the full sample (ledger N)

| diagnostic | value |
|---|---|
| Months / window | 180 / full |
| Trials N (ledger, distinct configurations) | 38 |
| Cells in grid / effective trials N_hat | 18 / 1.16 |
| Net Sharpe (annualised) | 0.81 |
| t-stat of mean excess return | 3.15  (vs 2.0: pass; 3.0: pass; 3.39: fail) |
| PSR(0) | 0.999 |
| Expected max Sharpe SR0 of N null trials (annualised) | 0.04 |
| DSR at N = 38 (ledger) | 0.998 |
| DSR at N_hat = 1.16 | 0.999 |
| DSR at N = 18 (grid cells) | 0.999 |
| Bonferroni haircut Sharpe (annualised) / haircut | 0.48 / 41% |
| Minimum track record for PSR(0) >= 95% (years) | 4.25 |

## T4 Parameter selection (train) and one-look confirmation (test)

- chosen: **ranking=MF, n=25, min_cap=5e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc** (plateau_v1 choice)
- default: ranking=MF, n=30, min_cap=1e+09, holding=staggered, universe=SP900, cost_bps=10, excess_cash=min_ca_cl, ebit=opinc (train Sharpe 1.02)
- train Sharpe of chosen 1.13; plateau score 1.070; peak ratio 1.02; plateau width 7 cells (>= 90% of chosen)
- bootstrap stability (B=500, mean block 6): 35% select exactly this cell, 90% within one grid step -> pass
- sensitivity (not used for selection): argmax -> f3ac97b076 (Sharpe 1.16, MORE THAN one step); lam0 -> d6b4cbd46c (Sharpe 1.13, within one step)

Reasons:
- train window 2011-10-31..2018-12-31: 87 months, 18 of 18 cells evaluable; metric = net Sharpe (annualised, excess of rf)
- plateau pick: score 1.070, peak ratio 1.02 (max 1.25)
- categorical plateau scores: holding=staggered=1.070; holding=annual=1.080 (default category kept unless another beats it by >= 0.10)
- bootstrap stability (B=500): 35% exactly this cell, 90% within one grid step (need >= 50%) -> pass

Neighbourhood of the chosen cell (train):

| role | axis | step | n | min_cap | holding | sharpe |
|---|---|---|---|---|---|---|
| self |  | 0 | 25 | 5000000000.0 | staggered | 1.13 |
| neighbor | n | -1 | 20 | 5000000000.0 | staggered | 1.15 |
| neighbor | n | 1 | 30 | 5000000000.0 | staggered | 1.13 |
| neighbor | min_cap | -1 | 25 | 1000000000.0 | staggered | 1.04 |

Plateau result per categorical level:

| category | n_cells | is_default_category | n_eligible | score | peak_ratio | sharpe | chosen |
|---|---|---|---|---|---|---|---|
| holding=staggered | 9 | True | 9 | 1.07 | 1.02 | 1.13 | True |
| holding=annual | 9 | False | 9 | 1.08 | 1.02 | 1.14 | False |

Confirmation on the untouched test window 2019-01-01 to 2026-09-30:

| cell | sharpe | cagr | vol | maxdd | tstat | n_months |
|---|---|---|---|---|---|---|
| chosen | 0.61 | 13.6% | 19.3% | -22.7% | 1.71 | 93 |
| default | 0.63 | 14.4% | 20.2% | -24.8% | 1.75 | 93 |
| grid_median | 0.63 | 14.3% | 20.2% | -24.3% | 1.75 | 93 |

- chosen minus default Sharpe: -0.02; chosen minus grid median: -0.01; rank percentile among cells: 17%
- Spearman(train Sharpe, test Sharpe) across cells: -0.81; test/train Sharpe of the chosen cell: 0.54
- criteria: test_sharpe_positive=yes, test_ge_half_train=yes, landscape_persists=NO, beats_grid_median=NO

## T4b Parameter regression over the grid (train)

Response: net Sharpe of each of 18 grid cells on 2011-10-31..2018-12-31; ordinal parameters scaled to [-1, 1]; R2 = 0.99. Bootstrap SDs resample months jointly across cells (B=500); cells overlap, so OLS p-values would be meaningless. A flat surface (small coefficients, low R2) is good news.

| term | coef | bootstrap SD | coef / SD |
|---|---|---|---|
| const | 1.046 | 0.380 | 2.8 |
| n | -0.019 | 0.022 | -0.8 |
| min_cap | 0.063 | 0.032 | 2.0 |
| n^2 | 0.012 | 0.008 | 1.6 |
| min_cap^2 | 0.030 | 0.030 | 1.0 |
| n*min_cap | 0.005 | 0.010 | 0.5 |
| holding=staggered | -0.010 | 0.012 | -0.8 |

## T5 Robustness (each run is a ledger trial)

Full-period net results of one-at-a-time changes around the chosen cell. Every run is logged in the ledger as an extra trial (it raises N for the DSR).

| run | full CAGR | full Sharpe | train Sharpe | test Sharpe | test CAGR | MaxDD | turnover/yr | FF5+MOM alpha | IR vs SPY | IR vs EW |
|---|---|---|---|---|---|---|---|---|---|---|
| chosen (base, 10 bps) | 14.9% | 0.81 | 1.13 | 0.61 | 13.6% | -35.3% | 64% | 0.6% (t=0.29) | -0.02 | 0.01 |
| cost 0 bps | 15.0% | 0.82 | 1.13 | 0.62 | 13.7% | -35.2% | 64% | 0.7% (t=0.35) | -0.00 | 0.03 |
| ablation ey_only | 11.5% | 0.54 | 0.76 | 0.42 | 10.7% | -53.1% | 68% | -2.2% (t=-0.87) | -0.16 | -0.21 |
| ablation roc_only | 14.5% | 0.82 | 1.32 | 0.52 | 11.3% | -34.6% | 43% | 0.5% (t=0.24) | -0.08 | -0.04 |
| ablation gpa_quality | 13.9% | 0.71 | 0.92 | 0.61 | 14.6% | -42.8% | 59% | -1.2% (t=-0.63) | -0.08 | -0.08 |
| ablation us_all_universe | 13.3% | 0.72 | 1.09 | 0.49 | 11.1% | -36.0% | 67% | -0.7% (t=-0.40) | -0.19 | -0.19 |
| ablation sp1500_universe | 14.8% | 0.81 | 1.13 | 0.61 | 13.4% | -35.3% | 64% | 0.5% (t=0.25) | -0.03 | -0.00 |
| ablation all_cash | 14.8% | 0.81 | 1.15 | 0.60 | 13.1% | -34.5% | 62% | 0.6% (t=0.30) | -0.03 | -0.01 |
| ablation ebit_pretax_interest | 15.4% | 0.85 | 1.14 | 0.66 | 14.3% | -33.9% | 65% | 1.0% (t=0.52) | 0.02 | 0.06 |
| ablation cost_25bps | 14.7% | 0.80 | 1.12 | 0.60 | 13.4% | -35.3% | 64% | 0.4% (t=0.20) | -0.04 | -0.02 |
| ablation cost_50bps | 14.4% | 0.78 | 1.10 | 0.59 | 13.0% | -35.3% | 64% | 0.1% (t=0.05) | -0.08 | -0.06 |

## T6 Bias stress and survivorship

SURVIVORSHIP-BIASED (yfinance has no delisted names): 81.0% of point-in-time S&P 900 members have a price history (monthly mean 2011-2026, minimum 63.2%); EW-SP900 minus RSP = +0.5%/yr CAGR gap (EW-SP500 minus RSP +0.9%/yr, the like-for-like bias proxy; the S&P 900 gap also contains the mid-cap premium); see output/survivorship.md

Break-even drag (alpha = 0): 56 bps/yr.

| assumed drag (bps/yr) | FF5+MOM alpha after drag | t |
|---|---|---|
| 0 | 0.56% | 0.29 |
| 50 | 0.06% | 0.03 |
| 100 | -0.44% | -0.23 |
| 150 | -0.94% | -0.50 |
| 200 | -1.44% | -0.76 |
| 300 | -2.44% | -1.28 |

Coverage by year and the EW-minus-RSP gap are in `output/survivorship.md`. Overall: share with prices 81.0%; EW-SP900 minus RSP +0.48%/yr.

## Evidence ladder (research/06 section 5.7)

**4/7 criteria passed -> mixed (failed: #1, #6, #7); fewer than 5/7: do not claim it works, hold it as a research hypothesis at a modest weight**

| # | criterion | pass | evidence |
|---|---|---|---|
| 1 | Direction replicates: net IR vs same-universe EW > 0 on train AND test | NO | IR train 0.15, test -0.07 |
| 2 | Plateau: chosen cell passes the 5.4 eligibility and bootstrap stability | yes | passed; stability 90% within one step |
| 3 | Costs: FF5+MOM net alpha still > 0 at 25 bps one-way | yes | alpha 0.4%/yr (t=0.20) at 25 bps; buy/hold-spread check for momentum not run |
| 4 | Factor view: FF5+MOM alpha > 0, or explained by the expected factors with no large negative alpha | yes | alpha 0.6%/yr (t=0.29, full sample to 2026-08, French data end 2026-08); expected-factor loadings with abs(t) > 2: RMW 0.22 (t=2.8) |
| 5 | Overfitting: PBO < 0.5 (DSR at N_hat and haircut Sharpe reported) | yes | PBO 30.1%; DSR(ledger N=38) 0.996, DSR(N_hat=1.20) 0.999; haircut Sharpe 0.63 (train, aim DSR > 0.5: met) |
| 6 | Bias stress: FF5+MOM alpha survives a 150 bps/yr survivorship drag | NO | break-even drag 56 bps/yr (alpha 0.56%); active CAGR vs EW-SP900 0.2% |
| 7 | Subperiods: positive active return vs SPY in at least 3 of 4 subperiods | NO | 2 of 4 positive (2011-14 5.8%, 2015-18 -0.6%, 2019-22 1.2%, 2023-26 -7.4%); worst 12m active return vs SPY -19.0% |

## Assumptions and limitations

- Returns are net of the stated trading costs (per side, on traded notional); signals at the close of day t, trades at the close of t+1; point-in-time rule: filings usable only if filed strictly before the signal date.
- Survivorship, XBRL tag mapping and a short test window limit what can be concluded; see the header and the coverage audit.
- Sharpe ratios are annualised from monthly data with sqrt(12), exact only for iid returns; HAC t-statistics over-reject in short samples.
- Expected decay: published anomalies lose roughly a quarter to a half of their returns out of sample and after publication (McLean & Pontiff 2016, Journal of Finance 71(1)); parameters were fixed on the train window with a pre-registered plateau rule and confirmed once on the test window, so the live result should be expected to be smaller than the backtest.

