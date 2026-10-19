# Trading comps (default): tear sheet

| item | value |
|---|---|
| Generated | 2026-10-19 04:14 UTC |
| Data | 2012-02-01 to 2026-09-30 (3,687 trading days) |
| Benchmarks | SPY, RSP, EW-SP900 (reference: SPY) |
| strategy | Trading comps (trading_comps) |
| parameter set | theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis=TTM  [literature default (doc-faithful)] |
| literature default | theta=0.15, pe_cap=40, ev_cap=35, size_filter=True, basis=TTM |
| universe | point-in-time S&P 900 (S&P 500 + MidCap 400) ex GICS Financials and Real Estate, mcap >= $300M, raw price >= $5 |
| windows | train 2012-02 to 2018-12; test 2019-01 to 2026-09 (single look); data end 2026-10-16 |
| trials N (ledger, distinct) | 62 |
| grid | 54 pre-registered cells, registered 2026-10-19T02:29:30+00:00 |
| costs | 10 bps one-way on every buy and sell (robustness 0/25/50) |
| timing | signal at the close of the month-end, trade at the next close; filings usable only if filed strictly before the signal date |
| survivorship | SURVIVORSHIP-BIASED (yfinance has no delisted names): 81.0% of point-in-time S&P 900 members have a price history (monthly mean 2011-2026, minimum 63.2%); EW-SP900 minus RSP = +0.5%/yr CAGR gap (EW-SP500 minus RSP +0.9%/yr, the like-for-like bias proxy; the S&P 900 gap also contains the mid-cap premium); see output/survivorship.md |
| benchmarks | SPY, RSP, EW-SP900 = equal-weight S&P 900 with the strategy's sector exclusions (Financials, Real Estate), 10 bps |
| git commit | 2c7657cd70 |
| tear sheet for | default |

## T1 Performance, net of costs

Monthly statistics from calendar-month compounded daily returns (partial leading/trailing months dropped); MaxDD is daily. Benchmark-relative rows are vs SPY; Sharpe CI = stationary bootstrap (mean block 6, B=500).

### Full (2012-02 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 176 | 176 | 176 | 176 | 176 |
| CAGR | 7.3% | 8.1% | 14.7% | 12.2% | 12.9% |
| AnnVol | 20.5% | 20.5% | 13.9% | 15.1% | 16.2% |
| Sharpe | 0.37 | 0.40 | 0.94 | 0.73 | 0.73 |
| Sharpe 95% CI | [0.01, 0.77] | [0.04, 0.81] | [0.56, 1.47] | [0.36, 1.21] | [0.36, 1.21] |
| Sortino | 0.55 | 0.61 | 1.51 | 1.13 | 1.14 |
| MaxDD (daily) | -52.7% | -51.8% | -33.7% | -39.0% | -40.1% |
| MaxDD peak>trough | 2018-01-26 > 2020-03-23 | 2018-01-26 > 2020-03-23 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.14 | 0.16 | 0.44 | 0.31 | 0.32 |
| Beta vs SPY | 1.18 | 1.18 | – | 1.02 | 1.08 |
| TE vs SPY | 12.4% | 12.4% | – | 5.2% | 6.2% |
| IR vs SPY | -0.45 | -0.39 | – | -0.39 | -0.21 |
| ActiveCAGR vs SPY | -6.5% | -5.8% | – | -2.2% | -1.6% |
| HitRate 1m | 44% | 45% | – | 46% | 47% |
| HitRate 3m | 43% | 43% | – | 40% | 41% |
| HitRate 6m | 32% | 33% | – | 39% | 44% |
| Up capture vs SPY | 94% | 96% | – | 95% | 100% |
| Down capture vs SPY | 131% | 129% | – | 106% | 110% |
| IR vs RSP | -0.36 | – | – | – | – |
| IR vs EW-SP900 | -0.46 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 79 | – | – | – | – |
| Avg holdings | 14.32 | – | – | – | – |
| Annual one-way turnover | 390% | – | – | – | – |

### Train (2012-02 to 2018-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 83 | 83 | 83 | 83 | 83 |
| CAGR | 2.4% | 3.1% | 12.0% | 11.2% | 11.9% |
| AnnVol | 15.5% | 15.5% | 10.6% | 11.1% | 11.7% |
| Sharpe | 0.20 | 0.25 | 1.08 | 0.97 | 0.98 |
| Sharpe 95% CI | [-0.53, 1.09] | [-0.48, 1.15] | [0.39, 2.03] | [0.24, 1.99] | [0.24, 1.99] |
| Sortino | 0.28 | 0.35 | 1.71 | 1.52 | 1.53 |
| MaxDD (daily) | -37.5% | -37.0% | -19.3% | -19.8% | -21.3% |
| MaxDD peak>trough | 2018-01-26 > 2018-12-24 | 2018-01-26 > 2018-12-24 | 2018-09-20 > 2018-12-24 | 2018-09-21 > 2018-12-24 | 2018-09-21 > 2018-12-24 |
| Calmar | 0.06 | 0.09 | 0.62 | 0.57 | 0.56 |
| Beta vs SPY | 1.10 | 1.10 | – | 1.02 | 1.04 |
| TE vs SPY | 10.3% | 10.3% | – | 2.6% | 3.9% |
| IR vs SPY | -0.81 | -0.74 | – | -0.25 | 0.01 |
| ActiveCAGR vs SPY | -8.6% | -7.9% | – | -0.7% | -0.1% |
| HitRate 1m | 40% | 42% | – | 45% | 51% |
| HitRate 3m | 36% | 36% | – | 43% | 46% |
| HitRate 6m | 29% | 32% | – | 45% | 56% |
| Up capture vs SPY | 66% | 68% | – | 98% | 102% |
| Down capture vs SPY | 111% | 109% | – | 102% | 104% |
| IR vs RSP | -0.82 | – | – | – | – |
| IR vs EW-SP900 | -0.96 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 75 | – | – | – | – |
| Avg holdings | 10.70 | – | – | – | – |
| Annual one-way turnover | 406% | – | – | – | – |

### Test (2019-01 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 93 | 93 | 93 | 93 | 93 |
| CAGR | 11.9% | 12.7% | 17.2% | 13.1% | 13.7% |
| AnnVol | 24.0% | 24.0% | 16.4% | 17.9% | 19.4% |
| Sharpe | 0.47 | 0.51 | 0.89 | 0.63 | 0.62 |
| Sharpe 95% CI | [-0.04, 1.09] | [-0.01, 1.12] | [0.35, 1.59] | [0.10, 1.33] | [0.10, 1.28] |
| Sortino | 0.73 | 0.78 | 1.44 | 0.97 | 0.97 |
| MaxDD (daily) | -46.3% | -46.3% | -33.7% | -39.0% | -40.1% |
| MaxDD peak>trough | 2020-01-16 > 2020-03-23 | 2020-01-16 > 2020-03-23 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.26 | 0.27 | 0.51 | 0.34 | 0.34 |
| Beta vs SPY | 1.21 | 1.21 | – | 1.02 | 1.10 |
| TE vs SPY | 14.1% | 14.1% | – | 6.8% | 7.6% |
| IR vs SPY | -0.22 | -0.17 | – | -0.49 | -0.33 |
| ActiveCAGR vs SPY | -4.6% | -3.8% | – | -3.5% | -3.0% |
| HitRate 1m | 47% | 48% | – | 47% | 44% |
| HitRate 3m | 48% | 48% | – | 35% | 36% |
| HitRate 6m | 34% | 35% | – | 32% | 36% |
| Up capture vs SPY | 110% | 112% | – | 93% | 99% |
| Down capture vs SPY | 142% | 141% | – | 107% | 114% |
| IR vs RSP | 0.01 | – | – | – | – |
| IR vs EW-SP900 | -0.07 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 84 | – | – | – | – |
| Avg holdings | 17.56 | – | – | – | – |
| Annual one-way turnover | 375% | – | – | – | – |

### Last 36m (2023-10 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 36 | 36 | 36 | 36 | 36 |
| CAGR | 13.5% | 14.3% | 22.8% | 15.5% | 14.0% |
| AnnVol | 17.0% | 17.0% | 12.4% | 12.9% | 14.0% |
| Sharpe | 0.57 | 0.62 | 1.37 | 0.85 | 0.70 |
| Sharpe 95% CI | [-0.13, 1.28] | [-0.09, 1.32] | [0.60, 2.16] | [0.19, 1.64] | [-0.02, 1.55] |
| Sortino | 0.98 | 1.07 | 2.86 | 1.38 | 1.11 |
| MaxDD (daily) | -22.2% | -21.9% | -18.8% | -17.8% | -21.1% |
| MaxDD peak>trough | 2024-11-06 > 2025-04-08 | 2024-11-06 > 2025-04-08 | 2025-02-19 > 2025-04-08 | 2024-11-29 > 2025-04-08 | 2024-11-25 > 2025-04-08 |
| Calmar | 0.61 | 0.65 | 1.21 | 0.87 | 0.66 |
| Beta vs SPY | 0.79 | 0.79 | – | 0.84 | 0.91 |
| TE vs SPY | 14.1% | 14.1% | – | 7.8% | 8.3% |
| IR vs SPY | -0.52 | -0.46 | – | -0.78 | -0.88 |
| ActiveCAGR vs SPY | -7.5% | -6.8% | – | -5.9% | -7.1% |
| HitRate 1m | 42% | 42% | – | 47% | 33% |
| HitRate 3m | 44% | 44% | – | 26% | 21% |
| HitRate 6m | 26% | 29% | – | 16% | 23% |
| Up capture vs SPY | 97% | 98% | – | 84% | 84% |
| Down capture vs SPY | 177% | 175% | – | 116% | 132% |
| IR vs RSP | -0.12 | – | – | – | – |
| IR vs EW-SP900 | 0.00 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 85 | – | – | – | – |
| Avg holdings | 18.71 | – | – | – | – |
| Annual one-way turnover | 376% | – | – | – | – |

### 2011-14 (2012-02 to 2014-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 35 | 35 | 35 | 35 | 35 |
| CAGR | 9.9% | 10.6% | 19.1% | 20.3% | 19.9% |
| AnnVol | 12.1% | 12.1% | 9.1% | 9.9% | 10.2% |
| Sharpe | 0.84 | 0.89 | 1.97 | 1.92 | 1.83 |
| Sharpe 95% CI | [0.05, 1.65] | [0.10, 1.70] | [1.23, 3.02] | [1.08, 3.10] | [0.97, 2.99] |
| Sortino | 1.57 | 1.69 | 3.74 | 3.61 | 3.51 |
| MaxDD (daily) | -12.2% | -12.2% | -9.7% | -11.2% | -10.4% |
| MaxDD peak>trough | 2014-09-18 > 2014-10-13 | 2014-09-18 > 2014-10-13 | 2012-04-02 > 2012-06-04 | 2012-03-26 > 2012-06-04 | 2012-03-26 > 2012-06-04 |
| Calmar | 0.81 | 0.87 | 1.97 | 1.81 | 1.91 |
| Beta vs SPY | 0.75 | 0.76 | – | 1.06 | 1.04 |
| TE vs SPY | 10.2% | 10.2% | – | 2.4% | 3.7% |
| IR vs SPY | -0.77 | -0.71 | – | 0.47 | 0.21 |
| ActiveCAGR vs SPY | -7.7% | -7.2% | – | 1.0% | 0.7% |
| HitRate 1m | 31% | 37% | – | 51% | 54% |
| HitRate 3m | 33% | 33% | – | 61% | 48% |
| HitRate 6m | 37% | 37% | – | 67% | 67% |
| Up capture vs SPY | 59% | 61% | – | 106% | 106% |
| Down capture vs SPY | 65% | 62% | – | 105% | 110% |
| IR vs RSP | -0.90 | – | – | – | – |
| IR vs EW-SP900 | -0.93 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 64 | – | – | – | – |
| Avg holdings | 8.56 | – | – | – | – |
| Annual one-way turnover | 363% | – | – | – | – |

### 2015-18 (2015-01 to 2018-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 48 | 48 | 48 | 48 | 48 |
| CAGR | -2.8% | -1.9% | 7.1% | 5.0% | 6.4% |
| AnnVol | 17.6% | 17.6% | 11.5% | 11.7% | 12.6% |
| Sharpe | -0.12 | -0.07 | 0.58 | 0.41 | 0.49 |
| Sharpe 95% CI | [-0.90, 0.89] | [-0.86, 0.95] | [-0.25, 1.98] | [-0.42, 1.70] | [-0.36, 1.83] |
| Sortino | -0.15 | -0.09 | 0.86 | 0.58 | 0.71 |
| MaxDD (daily) | -37.5% | -37.0% | -19.3% | -19.8% | -21.3% |
| MaxDD peak>trough | 2018-01-26 > 2018-12-24 | 2018-01-26 > 2018-12-24 | 2018-09-20 > 2018-12-24 | 2018-09-21 > 2018-12-24 | 2018-09-21 > 2018-12-24 |
| Calmar | -0.07 | -0.05 | 0.37 | 0.25 | 0.30 |
| Beta vs SPY | 1.26 | 1.26 | – | 0.99 | 1.04 |
| TE vs SPY | 10.5% | 10.5% | – | 2.8% | 4.1% |
| IR vs SPY | -0.84 | -0.76 | – | -0.71 | -0.13 |
| ActiveCAGR vs SPY | -9.2% | -8.5% | – | -1.9% | -0.7% |
| HitRate 1m | 46% | 46% | – | 40% | 48% |
| HitRate 3m | 35% | 35% | – | 28% | 41% |
| HitRate 6m | 21% | 26% | – | 23% | 47% |
| Up capture vs SPY | 72% | 75% | – | 90% | 98% |
| Down capture vs SPY | 130% | 129% | – | 101% | 102% |
| IR vs RSP | -0.75 | – | – | – | – |
| IR vs EW-SP900 | -0.98 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 81 | – | – | – | – |
| Avg holdings | 12.26 | – | – | – | – |
| Annual one-way turnover | 438% | – | – | – | – |

### 2019-22 (2019-01 to 2022-12)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 48 | 48 | 48 | 48 | 48 |
| CAGR | 8.3% | 9.1% | 13.1% | 13.5% | 14.5% |
| AnnVol | 28.6% | 28.6% | 19.4% | 21.4% | 23.2% |
| Sharpe | 0.38 | 0.41 | 0.67 | 0.65 | 0.65 |
| Sharpe 95% CI | [-0.25, 1.31] | [-0.22, 1.34] | [-0.06, 1.74] | [-0.06, 1.78] | [-0.03, 1.73] |
| Sortino | 0.56 | 0.60 | 1.03 | 0.99 | 1.02 |
| MaxDD (daily) | -46.3% | -46.3% | -33.7% | -39.0% | -40.1% |
| MaxDD peak>trough | 2020-01-16 > 2020-03-23 | 2020-01-16 > 2020-03-23 | 2020-02-19 > 2020-03-23 | 2020-02-12 > 2020-03-23 | 2020-01-16 > 2020-03-23 |
| Calmar | 0.18 | 0.20 | 0.39 | 0.35 | 0.36 |
| Beta vs SPY | 1.33 | 1.33 | – | 1.06 | 1.14 |
| TE vs SPY | 13.8% | 13.8% | – | 5.6% | 7.1% |
| IR vs SPY | -0.15 | -0.10 | – | 0.14 | 0.29 |
| ActiveCAGR vs SPY | -4.2% | -3.5% | – | 0.4% | 1.3% |
| HitRate 1m | 50% | 52% | – | 50% | 54% |
| HitRate 3m | 48% | 48% | – | 46% | 50% |
| HitRate 6m | 30% | 30% | – | 49% | 49% |
| Up capture vs SPY | 119% | 120% | – | 104% | 110% |
| Down capture vs SPY | 141% | 140% | – | 103% | 108% |
| IR vs RSP | -0.28 | – | – | – | – |
| IR vs EW-SP900 | -0.45 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 81 | – | – | – | – |
| Avg holdings | 16.37 | – | – | – | – |
| Annual one-way turnover | 371% | – | – | – | – |

### 2023-26 (2023-01 to 2026-09)

| metric | Strategy (net) | Strategy (gross) | SPY | RSP | EW-SP900 |
|---|---|---|---|---|---|
| Months | 45 | 45 | 45 | 45 | 45 |
| CAGR | 15.8% | 16.6% | 21.7% | 12.7% | 12.9% |
| AnnVol | 18.3% | 18.3% | 12.5% | 13.6% | 14.6% |
| Sharpe | 0.65 | 0.69 | 1.29 | 0.62 | 0.60 |
| Sharpe 95% CI | [0.03, 1.31] | [0.08, 1.35] | [0.70, 2.10] | [-0.00, 1.29] | [-0.05, 1.27] |
| Sortino | 1.25 | 1.34 | 2.58 | 1.00 | 0.98 |
| MaxDD (daily) | -22.2% | -21.9% | -18.8% | -17.8% | -21.1% |
| MaxDD peak>trough | 2024-11-06 > 2025-04-08 | 2024-11-06 > 2025-04-08 | 2025-02-19 > 2025-04-08 | 2024-11-29 > 2025-04-08 | 2024-11-25 > 2025-04-08 |
| Calmar | 0.71 | 0.76 | 1.16 | 0.71 | 0.61 |
| Beta vs SPY | 0.89 | 0.90 | – | 0.90 | 0.98 |
| TE vs SPY | 14.5% | 14.5% | – | 7.7% | 8.0% |
| IR vs SPY | -0.29 | -0.24 | – | -1.00 | -0.92 |
| ActiveCAGR vs SPY | -4.9% | -4.2% | – | -7.4% | -7.3% |
| HitRate 1m | 44% | 44% | – | 44% | 33% |
| HitRate 3m | 47% | 47% | – | 21% | 19% |
| HitRate 6m | 35% | 38% | – | 12% | 18% |
| Up capture vs SPY | 99% | 101% | – | 80% | 84% |
| Down capture vs SPY | 144% | 142% | – | 120% | 130% |
| IR vs RSP | 0.32 | – | – | – | – |
| IR vs EW-SP900 | 0.30 | – | – | – | – |
| Cost drag (bps/yr, gross CAGR - net CAGR) | 88 | – | – | – | – |
| Avg holdings | 18.83 | – | – | – | – |
| Annual one-way turnover | 379% | – | – | – | – |

## T2 Factor regressions (monthly, Newey-West HAC)

alpha is annualised (12 x monthly intercept); loadings show beta (HAC t, L=4). t at L=6 / L=12 are robustness checks; excess = strategy minus rf, active = strategy minus the reference benchmark.

| window | y | model | n | alpha (ann %) | t (L=4) | t (L=6) | t (L=12) | Mkt-RF | SMB | HML | RMW | CMA | Mom | R2 | adj R2 |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| Full | excess vs rf | CAPM | 175 | -7.38 | -2.71 | -2.91 | -2.86 | 1.15 (12.7) |  |  |  |  |  | 0.66 | 0.66 |
| Full | excess vs rf | FF3+MOM | 175 | -4.50 | -2.10 | -2.27 | -2.25 | 1.03 (14.3) | 0.18 (2.0) | 0.28 (5.0) |  |  | -0.34 (-4.0) | 0.78 | 0.77 |
| Full | excess vs rf | FF5+MOM | 175 | -5.16 | -2.41 | -2.53 | -2.47 | 1.04 (16.4) | 0.34 (3.3) | 0.18 (2.3) | 0.42 (4.2) | 0.09 (0.6) | -0.28 (-4.1) | 0.80 | 0.80 |
| Full | active vs SPY | FF5+MOM | 175 | -4.97 | -2.28 | -2.40 | -2.37 | 0.05 (0.8) | 0.46 (4.4) | 0.16 (1.9) | 0.37 (3.5) | 0.07 (0.5) | -0.29 (-4.0) | 0.45 | 0.43 |
| Train | excess vs rf | CAPM | 83 | -9.58 | -2.63 | -2.72 | -2.58 | 1.08 (9.1) |  |  |  |  |  | 0.59 | 0.58 |
| Train | excess vs rf | FF3+MOM | 83 | -7.32 | -2.11 | -2.20 | -2.05 | 1.00 (7.7) | 0.19 (1.2) | 0.01 (0.1) |  |  | -0.24 (-2.1) | 0.62 | 0.60 |
| Train | excess vs rf | FF5+MOM | 83 | -7.75 | -2.21 | -2.26 | -2.17 | 1.04 (8.2) | 0.33 (1.7) | -0.04 (-0.2) | 0.48 (2.0) | 0.17 (0.6) | -0.21 (-2.2) | 0.65 | 0.62 |
| Train | active vs SPY | FF5+MOM | 83 | -7.43 | -2.12 | -2.18 | -2.11 | 0.05 (0.4) | 0.45 (2.3) | -0.03 (-0.1) | 0.44 (1.8) | 0.13 (0.5) | -0.21 (-2.2) | 0.19 | 0.12 |
| Test | excess vs rf | CAPM | 92 | -5.02 | -1.25 | -1.37 | -1.46 | 1.17 (10.3) |  |  |  |  |  | 0.70 | 0.69 |
| Test | excess vs rf | FF3+MOM | 92 | -2.22 | -0.80 | -0.81 | -0.85 | 1.03 (14.1) | 0.12 (1.3) | 0.37 (6.8) |  |  | -0.42 (-4.1) | 0.86 | 0.85 |
| Test | excess vs rf | FF5+MOM | 92 | -2.95 | -1.04 | -1.04 | -1.03 | 1.04 (15.6) | 0.29 (2.8) | 0.25 (2.6) | 0.33 (3.1) | 0.10 (0.7) | -0.35 (-4.2) | 0.87 | 0.86 |
| Test | active vs SPY | FF5+MOM | 92 | -2.85 | -0.96 | -0.96 | -0.96 | 0.06 (0.8) | 0.41 (3.9) | 0.22 (2.1) | 0.29 (2.4) | 0.09 (0.5) | -0.35 (-4.0) | 0.60 | 0.57 |


## T7 Short-horizon behaviour (rolling windows from the backtest)

Overlapping compounded windows on daily net returns; excess = strategy minus benchmark. Effective independent windows (`indep.`) are about n/h, so the binomial uncertainty of P(beat) is large; the bracket is a stationary-bootstrap 95% CI.

| vs | window | horizon | windows | indep. | mean excess | 5% | 25% | median | 75% | 95% | worst | P(beat) | P(loss) | P(beat by >2pt) |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| SPY | Full | 13d | 3675 | 284 | -0.27% | -4.56% | -1.92% | -0.28% | 1.37% | 4.02% | -13.78% | 45.2% [40-50] | 43.1% | 18.4% |
| SPY | Full | 63d | 3625 | 59 | -1.31% | -10.14% | -5.26% | -1.22% | 2.79% | 7.56% | -22.93% | 42.7% [32-52] | 38.1% | 29.5% |
| SPY | Full | 126d | 3562 | 29 | -2.96% | -14.35% | -7.30% | -3.30% | 1.23% | 9.01% | -20.57% | 31.2% [20-46] | 33.4% | 22.0% |
| SPY | Test | 13d | 1935 | 150 | -0.17% | -5.44% | -2.12% | -0.15% | 1.87% | 4.61% | -13.78% | 47.9% [40-53] | 41.8% | 23.7% |
| SPY | Test | 63d | 1885 | 31 | -0.99% | -11.93% | -5.23% | -0.36% | 3.55% | 9.11% | -22.93% | 48.2% [34-61] | 39.4% | 34.7% |
| SPY | Test | 126d | 1822 | 15 | -2.45% | -14.68% | -7.33% | -2.74% | 2.21% | 10.90% | -20.57% | 34.2% [24-56] | 32.3% | 25.6% |
| RSP | Full | 13d | 3675 | 284 | -0.17% | -3.54% | -1.53% | -0.17% | 1.20% | 3.36% | -8.78% | 46.6% [40-51] | 43.1% | 14.4% |
| RSP | Full | 63d | 3625 | 59 | -0.86% | -8.62% | -4.30% | -0.66% | 2.28% | 6.76% | -17.68% | 44.0% [33-53] | 38.1% | 27.0% |
| RSP | Full | 126d | 3562 | 29 | -2.01% | -11.96% | -6.07% | -2.48% | 2.44% | 8.27% | -21.06% | 35.6% [22-52] | 33.4% | 26.5% |
| EW-SP900 | Full | 13d | 3675 | 284 | -0.21% | -3.38% | -1.46% | -0.16% | 1.04% | 3.01% | -8.13% | 45.8% [40-50] | 43.1% | 11.9% |
| EW-SP900 | Full | 63d | 3625 | 59 | -1.08% | -8.29% | -4.18% | -0.85% | 1.95% | 5.81% | -18.22% | 41.4% [31-51] | 38.1% | 24.6% |
| EW-SP900 | Full | 126d | 3562 | 29 | -2.46% | -12.39% | -6.20% | -2.52% | 1.56% | 6.88% | -20.72% | 33.3% [21-49] | 33.4% | 23.4% |

### Forward expectation: P(beat SPY) = Phi(IR x sqrt(h/252))

Backtest IR (full sample, monthly) = -0.45. Haircuts follow McLean & Pontiff (2016): a self-tuned strategy can decay by more than their 26% data-mining cap, so treat these as optimistic.

| scenario | IR | 13d | 63d | 126d |
|---|---|---|---|---|
| IR = 0 (no skill) | 0.00 | 50.0% | 50.0% | 50.0% |
| backtest IR, no haircut | -0.45 | 45.9% | 41.1% | 37.5% |
| haircut 26% (data-mining only) | -0.33 | 47.0% | 43.4% | 40.7% |
| haircut 58% (post-publication) | -0.19 | 48.3% | 46.2% | 44.7% |

## Charts

### C1 Growth of $1

![C1 Growth of $1](trading_comps_default_C1_growth.png)

### C2 Underwater

![C2 Underwater](trading_comps_default_C2_underwater.png)

### C3 Rolling excess and IR

![C3 Rolling excess and IR](trading_comps_default_C3_rolling.png)

### C4 Calendar-year returns

![C4 Calendar-year returns](trading_comps_default_C4_calendar.png)

### C5 Rolling-horizon excess-return histograms

![C5 Rolling-horizon excess-return histograms](trading_comps_default_C5_horizons.png)

### C8 Factor loadings

![C8 Factor loadings](trading_comps_default_C8_loadings.png)

## T3 Overfitting diagnostics (train window)

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

## T3b DSR on the full sample (ledger N)

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

## T4 Parameter selection (train) and one-look confirmation (test)

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

## T4b Parameter regression over the grid (train)

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

## T5 Robustness (each run is a ledger trial)

Full-period net results of one-at-a-time changes around the chosen cell. Every run is logged in the ledger as an extra trial (it raises N for the DSR).

| run | full CAGR | full Sharpe | train Sharpe | test Sharpe | test CAGR | MaxDD | turnover/yr | FF5+MOM alpha | IR vs SPY | IR vs EW |
|---|---|---|---|---|---|---|---|---|---|---|
| chosen (base, 10 bps) | 10.6% | 0.51 | 0.55 | 0.51 | 13.0% | -52.4% | 355% | -2.0% (t=-0.87) | -0.19 | -0.12 |
| cost 0 bps | 11.4% | 0.54 | 0.59 | 0.54 | 13.8% | -51.7% | 355% | -1.3% (t=-0.57) | -0.14 | -0.05 |
| cost 25 bps | 9.5% | 0.46 | 0.48 | 0.47 | 11.9% | -53.5% | 355% | -3.0% (t=-1.32) | -0.28 | -0.22 |
| cost 50 bps | 7.6% | 0.38 | 0.36 | 0.40 | 10.0% | -55.2% | 355% | -4.7% (t=-2.06) | -0.41 | -0.40 |
| basis LFY (last fiscal year) | 12.4% | 0.60 | 0.68 | 0.57 | 14.5% | -46.3% | 349% | -0.4% (t=-0.19) | -0.08 | 0.04 |

## T6 Bias stress and survivorship

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

## Evidence ladder (research/06 section 5.7)

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

## Assumptions and limitations

- Returns are net of the stated trading costs (per side, on traded notional); signals at the close of day t, trades at the close of t+1; point-in-time rule: filings usable only if filed strictly before the signal date.
- Survivorship, XBRL tag mapping and a short test window limit what can be concluded; see the header and the coverage audit.
- Sharpe ratios are annualised from monthly data with sqrt(12), exact only for iid returns; HAC t-statistics over-reject in short samples.
- Expected decay: published anomalies lose roughly a quarter to a half of their returns out of sample and after publication (McLean & Pontiff 2016, Journal of Finance 71(1)); parameters were fixed on the train window with a pre-registered plateau rule and confirmed once on the test window, so the live result should be expected to be smaller than the backtest.

