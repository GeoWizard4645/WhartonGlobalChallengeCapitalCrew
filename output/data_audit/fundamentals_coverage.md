# Fundamentals snapshots: validation and coverage audit

Generated 2026-10-18 by the audit script on `cache/fundamentals/snapshots.parquet` (module `quant/data/fundamentals.py`, build version 3). All numbers below are computed from the built table, not hand-entered, except the commentary.

## 1. Build summary

- Table: **397,540 rows x 94 columns**, 15,166 CIKs (14,004 with at least one 10-K), `filed` from 2009-04-15 to 2026-10-16, 98 MB parquet.
- Full rebuild: **~16 s** wall-clock with 8 worker processes on a 10-core Mac (one SEC facts partition per task, about 1 s of CPU per partition; the 39M fact rows are ingested exactly once per company). The target was < 20 minutes.
- One row per (cik, filing date): no duplicate (cik, filed). Forms: 10-Q 292,049, 10-K 94,146, 10-Q/A 7,553, 10-K/A 3,410, 10-KT 287, 10-QT 67, 10-KT/A 23, 10-QT/A 5.
- Variant `cache/fundamentals/snapshots_first.parquet` (`build_snapshots(first_filed=True)`): same rows, but every (tag, period) keeps its EARLIEST vintage, i.e. restatements never leak into later snapshots. It differs from the default (latest vintage <= filed) by more than 0.5% in 2.9% of snapshots for revenue, 5.7% for operating income and 3.9% for net income (balance-sheet items: 0.12%).
- PIT rule: `asof(snaps, date)` uses `filed < date` strictly; `period_end` is monotone per CIK (a late amendment of an old period carries the newest balance sheet already known, flag `amend_anchor`), so the latest filing is always the freshest period.

## 2. Research test vectors

GP/A = `gross_profit / assets` from `asof(snaps, date)` (research/02 s6.3). Ford as of 2026-10-20 needs `max_age_days=250` because Ford's Q2-2026 10-Q is missing from companyfacts (latest period 2026-03-31, 203 days old); everything else uses the default 200.

| as_of | ticker | period_end | gross_profit_bn | assets_bn | GPA | expected | diff_pct | gp_source |
|---|---|---|---|---|---|---|---|---|
| 2026-10-20 | AAPL | 2026-06-27 | 227.123 | 383.266 | 0.5926 | 0.5926 | -0.000 | GrossProfit tag |
| 2026-10-20 | MSFT | 2026-06-30 | 225.465 | 758.376 | 0.2973 | 0.2973 | -0.000 | GrossProfit tag |
| 2026-10-20 | WMT | 2026-07-31 | 178.283 | 293.914 | 0.6066 | 0.6066 | -0.003 | rev-cogs |
| 2026-10-20 | NVDA | 2026-07-26 | 226.241 | 320.272 | 0.7064 | 0.7064 | +0.000 | GrossProfit tag |
| 2026-10-20 | COST | 2026-08-30 | 38.875 | 89.045 | 0.4366 | 0.4366 | -0.005 | rev-cogs |
| 2026-10-20 | F | 2026-03-31 | 15.272 | 282.434 | 0.0541 | 0.0541 | -0.050 | rev-cogs |
| 2024-10-20 | AAPL | 2024-06-29 | 177.231 | 331.612 | 0.5345 | 0.5345 | -0.009 | GrossProfit tag |
| 2024-10-20 | MSFT | 2024-06-30 | 171.008 | 512.163 | 0.3339 | 0.3339 | -0.002 | GrossProfit tag |
| 2024-10-20 | WMT | 2024-07-31 | 157.809 | 254.440 | 0.6202 | 0.6202 | +0.003 | rev-cogs |
| 2024-10-20 | NVDA | 2024-07-28 | 73.170 | 85.227 | 0.8585 | 0.8585 | +0.004 | GrossProfit tag |
| 2024-10-20 | COST | 2024-09-01 | 32.095 | 69.831 | 0.4596 | 0.4596 | +0.002 | rev-cogs |
| 2024-10-20 | F | 2024-06-30 | 24.973 | 276.586 | 0.0903 | 0.0903 | -0.011 | rev-cogs |

All 12 vectors match within 0.050% (limit 0.5%). COST uses revenue - cogs (its `GrossProfit` tag stopped after FY2019) and WMT uses the ASC606 net-sales tag (see s7, revenue tag choice).

Research/03 values:

| item | ours_bn | expected_bn | diff_pct |
|---|---|---|---|
| AAPL TTM opinc as of 2026-10-18 (period 2026-06-27) | 154.859 | 154.859 | +0.00 |
| AAPL total_debt ex finance lease (LongTermDebt 82.300 + CommercialPaper 1.997) | 84.297 | 84.297 | +0.00 |
| AAPL total_debt incl. finance lease 1.230bn carried from the FY2025 10-K | 85.527 | 84.297 | +1.46 |

The 1.4% difference of the last row is the finance lease the spec asks to add ("+ finance leases if any"); Apple tags it only in the 10-K, so it is carried forward (flag `carry_fwd`).

## 3. Independent spot check against Yahoo (yfinance, run 2026-10-18)

Percentages are `ours / Yahoo - 1`. Revenue, net income and operating income: EDGAR TTM (`FY + YTD - YTD_prior`) vs the sum of the last four Yahoo quarterly statements. Debt: our `total_debt` (operating leases excluded, finance leases included) vs Yahoo "Total Debt" of the latest quarterly balance sheet; Yahoo includes operating leases for most firms, so the second debt column adds our `op_lease_*` columns to ours.

| ticker | EDGAR period | Yahoo latest q | same period | revenue % | net income % | op. income % | debt % | debt + op.leases % | comment |
|---|---|---|---|---|---|---|---|---|---|
| AAPL | 2026-06-27 | 2026-06-30 | True | +0.0 | +0.0 | +0.0 | +1.4 | +16.2 | debt: finance lease 1.23bn (10-K, carried) is in ours, not in Yahoo |
| MSFT | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 | +0.0 | +88.1 | +117.2 | debt: ours adds 66.6bn finance leases (Yahoo excludes them; Yahoo = debt + 16.5bn operating leases) |
| AMZN | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 |  | -30.1 | +15.8 | Yahoo balance sheet is the 2026-03-31 quarter and its last-4-quarter flows are NaN; not comparable |
| GOOGL | 2026-06-30 | 2026-06-30 | True | -0.0 | +0.0 | +0.0 | -8.9 | +7.1 | debt: Yahoo adds operating leases (18.0bn); ours adds 2.6bn finance leases |
| META | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 | -0.0 | -24.5 | +1.1 | debt: ours + operating leases = Yahoo within 1.1% |
| NVDA | 2026-07-26 | 2026-07-31 | True | +0.0 | +0.0 | +0.0 | -13.0 | +1.3 | period 2026-07-26 vs Yahoo calendar-month 07-31 |
| TSLA | 2026-06-30 | 2026-06-30 | True | +0.0 | -0.1 | -8.4 | -42.3 | -0.4 | opinc: EDGAR arithmetic checks (FY25 4.355 + H1-26 1.339 - H1-25 1.322); Yahoo Q3/Q4-25 quarters differ from the filed values |
| WMT | 2026-07-31 | 2026-07-31 | True | -1.0 | +0.0 | +0.0 | -22.5 | -0.1 | revenue: ASC606 net sales 728.5 vs total revenues incl. membership 735.8 (Yahoo); both tags exist, see s7 |
| KO | 2026-04-03 | 2026-06-30 | False | -1.7 | -4.3 | -9.3 | +0.6 | +4.6 | EDGAR is one quarter behind: the Q2-2026 10-Q is missing from companyfacts |
| PG | 2026-06-30 | 2026-06-30 | True | -0.0 | +1.9 | -0.0 | -2.5 | -0.0 | ni: Yahoo "common" deducts preferred dividends; debt + operating leases = Yahoo |
| JNJ | 2026-06-28 | 2026-06-30 | True | +0.0 | +0.0 | -0.2 | +0.0 | +2.9 |  |
| XOM | 2026-03-31 | 2026-06-30 | False | -7.4 | -22.7 | -3.6 | +12.5 | +28.6 | history sits under CIK 34088 (latest 10-Q 2026-03-31); the successor CIK 2115436 has the Q2 filing but no history |
| CVX | 2026-06-30 | 2026-06-30 | True | +1.9 | +0.0 | +24.2 | +0.0 | +16.1 | no OperatingIncomeLoss: ebit_proxy = pretax + interest (includes equity income); revenue tag `Revenues` includes other income |
| HD | 2026-08-02 | 2026-07-31 | True | +0.0 | +0.0 | +0.0 | -15.5 | +0.0 | debt + operating leases = Yahoo |
| COST | 2026-08-30 | 2026-05-31 | False | +3.3 | +4.4 | +4.1 | -6.9 | +25.1 | Yahoo still on the 2026-05-31 quarter; EDGAR has the FY ending 2026-08-30 (ours = research value) |
| CAT | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 | +0.0 |  |  | segment-presented balance sheet: no non-dimensional interim debt, total_debt NaN by design |
| BA | 2026-06-30 | 2026-06-30 | True | +0.0 | +16.6 |  | -2.9 | +1.9 | ni: EDGAR = FY25 2.235 + H1-26 - H1-25 = 2.435bn (also the sum of discrete quarters); Yahoo figure differs |
| PFE | 2026-06-28 | 2026-06-30 | True | +0.0 | +0.0 | -59.4 | +0.0 | +4.1 | no operating income line: ebit_proxy = pretax + interest (after IPR&D and other deductions); Yahoo reports a pre-other-deductions figure |
| MRK | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 | +10.1 | +0.0 | +2.2 | ebit_proxy (no operating income line) |
| NKE | 2026-08-31 | 2026-05-31 | False | -1.1 | -0.5 | +1.5 | -28.5 | +0.4 | EDGAR already has the Q1 FY27 10-Q (2026-08-31); Yahoo is on 2026-05-31 |
| MCD | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 | +1.1 | -22.7 | +4.3 | debt: Yahoo = ours - finance leases + operating leases |
| HON | 2026-06-30 | 2026-06-30 | True | +5.3 | +0.0 | +40.3 | +0.2 | +3.0 | revenue/opinc: spin-off recast. TTM = FY25 as originally reported + recast 2026/2025 YTD, Yahoo sums recast quarters |
| LIN | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 | -2.4 | +0.8 | +3.9 | debt: previously double counted commercial paper (nested in short-term borrowings); fixed via the combined-debt tag |
| UNP | 2026-06-30 | 2026-06-30 | True | +0.0 | +0.0 | +0.0 | -2.7 | +0.0 | debt + operating leases = Yahoo |
| LLY | 2026-06-30 | 2026-06-30 | True | +0.0 | -0.0 | -14.2 | +0.0 | +2.5 | no operating income line: ebit_proxy |
| ORCL | 2026-08-31 | 2026-08-31 | True | -0.0 | +1.0 | -6.2 |  |  | non-current notes untagged in the 10-Q: total_debt left NaN (flag debt_nc_missing) instead of a 17bn understatement |

On the 22 names with the same period, **revenue is within 0.1% for 19, net income within 0.1% for 19**, and debt (ours + operating leases) within 5% for 15. The remaining gaps are explained in the comment column: definitions (Yahoo operating leases, finance leases, `Revenues` vs net sales, preferred dividends, operating income proxies for firms with no operating-income line), restated comparatives (HON), different periods (KO, XOM, COST, NKE) or untagged debt (CAT, ORCL).

## 4. Coverage by filing year

`shares_any` = `shares_out` if present else `shares_diluted`. Share (%) of snapshots with a non-null value, snapshots by `filed` year. Population: companies with at least one 10-K snapshot (blank-section filers such as ABS trusts without any 10-K are excluded). 2010-2011 is the XBRL phase-in (large accelerated filers first, everyone after mid-2011), so the early rows are structurally lower. 2026 is partial (through 2026-10-16). The dip in 2021-2022 in table 4a is the SPAC wave (blank-check shells: no revenue, SIC 6770); table 4b is unaffected.

### 4a. All companies with at least one 10-K

| year | n | revenue | gross_profit | opinc | net_income | da | cfo | capex | total_debt | cash | ppe_net | current_assets | shares_out | shares_diluted | shares_any |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010 | 3669 | 44 | 29 | 46 | 51 | 45 | 50 | 42 | 87 | 97 | 88 | 81 | 96 | 76 | 98 |
| 2011 | 16681 | 29 | 20 | 32 | 40 | 31 | 34 | 28 | 87 | 97 | 79 | 76 | 93 | 57 | 96 |
| 2012 | 30065 | 63 | 42 | 80 | 89 | 72 | 86 | 58 | 81 | 96 | 75 | 76 | 94 | 52 | 96 |
| 2013 | 29123 | 67 | 46 | 85 | 94 | 77 | 92 | 61 | 80 | 96 | 76 | 76 | 94 | 54 | 96 |
| 2014 | 28658 | 67 | 46 | 85 | 94 | 77 | 92 | 61 | 81 | 96 | 76 | 77 | 93 | 54 | 96 |
| 2015 | 27603 | 69 | 47 | 87 | 95 | 79 | 93 | 62 | 82 | 96 | 77 | 77 | 93 | 55 | 96 |
| 2016 | 25724 | 70 | 47 | 89 | 96 | 81 | 94 | 64 | 83 | 97 | 78 | 77 | 92 | 56 | 96 |
| 2017 | 24600 | 70 | 48 | 90 | 96 | 81 | 94 | 64 | 83 | 96 | 78 | 77 | 92 | 56 | 96 |
| 2018 | 23922 | 70 | 47 | 90 | 96 | 82 | 94 | 64 | 84 | 97 | 79 | 77 | 92 | 57 | 96 |
| 2019 | 23192 | 77 | 49 | 92 | 96 | 83 | 95 | 65 | 83 | 97 | 79 | 78 | 91 | 57 | 95 |
| 2020 | 22547 | 77 | 49 | 92 | 96 | 83 | 95 | 65 | 84 | 97 | 78 | 78 | 90 | 57 | 94 |
| 2021 | 25503 | 69 | 44 | 83 | 87 | 73 | 86 | 57 | 80 | 98 | 73 | 80 | 85 | 56 | 90 |
| 2022 | 26558 | 70 | 46 | 89 | 93 | 75 | 91 | 60 | 79 | 98 | 73 | 82 | 83 | 66 | 89 |
| 2023 | 24907 | 73 | 48 | 92 | 96 | 79 | 96 | 62 | 84 | 98 | 75 | 80 | 87 | 77 | 93 |
| 2024 | 23167 | 75 | 50 | 91 | 97 | 81 | 96 | 62 | 83 | 98 | 76 | 78 | 89 | 83 | 95 |
| 2025 | 22305 | 75 | 49 | 89 | 96 | 81 | 95 | 61 | 83 | 98 | 75 | 77 | 88 | 85 | 95 |
| 2026 | 16317 | 74 | 50 | 90 | 96 | 80 | 95 | 61 | 83 | 98 | 73 | 78 | 87 | 84 | 94 |

### 4b. Non-financial companies (SIC outside 6000-6999) with assets >= $1bn

| year | n | revenue | gross_profit | opinc | net_income | da | cfo | capex | total_debt | cash | ppe_net | current_assets | shares_out | shares_diluted | shares_any |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010 | 2508 | 53 | 38 | 54 | 58 | 53 | 57 | 51 | 93 | 99 | 97 | 98 | 95 | 78 | 98 |
| 2011 | 4628 | 71 | 54 | 75 | 78 | 74 | 78 | 71 | 93 | 99 | 95 | 97 | 91 | 80 | 96 |
| 2012 | 5587 | 87 | 64 | 94 | 95 | 92 | 95 | 86 | 94 | 98 | 96 | 97 | 89 | 80 | 95 |
| 2013 | 5824 | 89 | 64 | 95 | 96 | 93 | 95 | 87 | 94 | 99 | 96 | 97 | 88 | 80 | 95 |
| 2014 | 6032 | 89 | 64 | 95 | 95 | 93 | 95 | 87 | 95 | 99 | 96 | 97 | 88 | 80 | 95 |
| 2015 | 6102 | 90 | 65 | 96 | 96 | 93 | 96 | 88 | 96 | 99 | 96 | 97 | 88 | 80 | 94 |
| 2016 | 5993 | 91 | 66 | 98 | 98 | 95 | 97 | 90 | 96 | 99 | 96 | 97 | 88 | 82 | 95 |
| 2017 | 5936 | 91 | 68 | 97 | 97 | 95 | 97 | 90 | 96 | 99 | 97 | 97 | 88 | 83 | 95 |
| 2018 | 5981 | 92 | 67 | 97 | 98 | 95 | 97 | 90 | 96 | 99 | 97 | 97 | 88 | 83 | 95 |
| 2019 | 6067 | 97 | 69 | 98 | 98 | 95 | 98 | 91 | 96 | 99 | 97 | 97 | 88 | 84 | 95 |
| 2020 | 6014 | 97 | 73 | 98 | 99 | 95 | 98 | 90 | 95 | 99 | 95 | 97 | 88 | 84 | 95 |
| 2021 | 6284 | 95 | 72 | 96 | 96 | 93 | 96 | 88 | 93 | 99 | 97 | 97 | 88 | 86 | 96 |
| 2022 | 6590 | 97 | 73 | 98 | 98 | 96 | 98 | 90 | 93 | 99 | 97 | 97 | 87 | 91 | 97 |
| 2023 | 6470 | 97 | 74 | 98 | 99 | 96 | 99 | 90 | 95 | 100 | 97 | 97 | 87 | 92 | 97 |
| 2024 | 6326 | 97 | 74 | 98 | 99 | 96 | 99 | 89 | 95 | 100 | 97 | 97 | 87 | 93 | 97 |
| 2025 | 6332 | 97 | 74 | 98 | 99 | 97 | 99 | 89 | 95 | 100 | 96 | 97 | 87 | 93 | 97 |
| 2026 | 4666 | 98 | 75 | 99 | 99 | 97 | 99 | 89 | 94 | 99 | 96 | 97 | 86 | 93 | 97 |

### 4c. Financial companies (SIC 6000-6999), for reference

| year | n | revenue | gross_profit | opinc | net_income | da | cfo | capex | total_debt | cash | ppe_net | current_assets | shares_out | shares_diluted | shares_any |
|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2010 | 766 | 30 | 4 | 35 | 45 | 34 | 44 | 26 | 85 | 91 | 57 | 17 | 96 | 68 | 98 |
| 2011 | 4129 | 19 | 3 | 25 | 34 | 24 | 30 | 17 | 78 | 91 | 58 | 17 | 90 | 45 | 92 |
| 2012 | 7291 | 38 | 7 | 75 | 89 | 66 | 87 | 49 | 73 | 91 | 57 | 19 | 90 | 47 | 92 |
| 2013 | 6964 | 40 | 8 | 77 | 92 | 68 | 89 | 49 | 75 | 90 | 56 | 19 | 91 | 55 | 93 |
| 2014 | 6673 | 41 | 8 | 77 | 93 | 70 | 89 | 49 | 75 | 91 | 57 | 18 | 90 | 58 | 93 |
| 2015 | 6503 | 43 | 9 | 80 | 94 | 72 | 90 | 50 | 78 | 91 | 57 | 18 | 90 | 59 | 94 |
| 2016 | 6130 | 44 | 9 | 82 | 95 | 74 | 92 | 51 | 79 | 91 | 57 | 18 | 90 | 60 | 93 |
| 2017 | 5872 | 45 | 9 | 83 | 95 | 75 | 92 | 50 | 79 | 91 | 57 | 18 | 89 | 61 | 93 |
| 2018 | 5712 | 45 | 9 | 83 | 95 | 75 | 93 | 50 | 80 | 91 | 57 | 17 | 89 | 61 | 92 |
| 2019 | 5444 | 58 | 13 | 85 | 96 | 77 | 94 | 50 | 81 | 92 | 57 | 17 | 89 | 63 | 92 |
| 2020 | 5344 | 60 | 13 | 84 | 95 | 77 | 93 | 48 | 81 | 93 | 56 | 18 | 87 | 63 | 91 |
| 2021 | 6720 | 46 | 10 | 67 | 76 | 59 | 75 | 37 | 74 | 94 | 46 | 34 | 73 | 54 | 77 |
| 2022 | 7284 | 43 | 10 | 76 | 85 | 55 | 83 | 36 | 74 | 95 | 42 | 43 | 67 | 54 | 73 |
| 2023 | 6056 | 51 | 12 | 86 | 96 | 65 | 95 | 42 | 81 | 95 | 49 | 33 | 78 | 66 | 84 |
| 2024 | 5496 | 55 | 13 | 85 | 95 | 72 | 93 | 44 | 81 | 94 | 53 | 27 | 83 | 73 | 90 |
| 2025 | 5503 | 55 | 13 | 80 | 90 | 70 | 88 | 43 | 80 | 94 | 52 | 27 | 82 | 74 | 89 |
| 2026 | 4258 | 52 | 13 | 79 | 90 | 66 | 87 | 39 | 77 | 93 | 47 | 32 | 77 | 68 | 84 |

Banks and insurers have no gross profit, current assets or COGS in XBRL by construction; the strategies exclude them (SIC 6000-6999).

### 4d. Other fields (all companies with a 10-K; non-null %)

| field | all | non-fin >= $1bn |
|---|---|---|
| assets | 100.0 | 100.0 |
| equity_parent | 95.8 | 95.7 |
| equity_total | 98.7 | 98.1 |
| liabilities | 98.7 | 98.1 |
| current_liabilities | 77.4 | 96.8 |
| goodwill | 48.5 | 84.4 |
| intangibles | 36.7 | 60.5 |
| st_investments | 15.0 | 21.1 |
| preferred | 34.0 | 36.3 |
| minority_interest | 27.9 | 46.7 |
| finance_lease | 21.2 | 38.2 |
| op_lease_current | 25.8 | 42.9 |
| retained_earnings | 89.7 | 93.2 |
| sga | 72.3 | 83.0 |
| interest_exp | 61.7 | 78.3 |
| pretax | 65.0 | 88.1 |
| tax | 64.2 | 93.2 |
| eps_diluted | 76.3 | 84.8 |
| ebitda | 74.0 | 91.9 |
| evol | 65.3 | 78.8 |
| shares_basic | 65.5 | 85.4 |
| assets_4q | 88.7 | 94.5 |
| total_debt_4q | 73.7 | 89.3 |
| revenue_ttm_4q | 67.9 | 91.2 |
| revenue_fy1 | 70.9 | 92.2 |
| revenue_fy5 | 49.4 | 74.8 |

## 5. `ttm_method`, `fiscal_period` and flag distributions

| ttm_method | snapshots | share % |
|---|---|---|
| YTD | 265546 | 66.8 |
| FY | 94042 | 23.7 |
| none | 34812 | 8.8 |
| 4Q | 3140 | 0.8 |

`FY` = annual fact ends at period_end; `YTD` = FY_prev + YTD_cur - YTD_prior_year; `4Q` = sum of four discrete quarters (Q4 = FY - 9M) for the first available of revenue / net income / operating income / CFO; `none` = no TTM computable. `none` is concentrated in the first two or three snapshots of each company (the pre-XBRL 10-K has no facts to difference against: 10,796 in 2011 alone) plus fresh-start / predecessor-successor periods, transition reports and subsidiary filers.

`none` snapshots that are among the company's first 3 filings: 82%.

fiscal_period: Q2 102,576, Q3 98,920, Q1 98,376, FY 94,287, nan 3,381

| flag | snapshots | share % | meaning |
|---|---|---|---|
| mixed_tags | 112743 | 28.4 | TTM pieces of at least one concept came from different tags (tag migration, e.g. SalesRevenueNet -> ASC606) |
| carry_fwd | 74651 | 18.8 | goodwill / intangibles / leases carried from a 10-K <= 400 days old |
| liab_derived | 73080 | 18.4 | Liabilities derived as L&SE - equity |
| debt_lowconf | 68432 | 17.2 | debt from note-type tags only (SeniorNotes, NotesPayable, ...) |
| debt_zero_inferred | 64366 | 16.2 | no non-zero debt tag in 8 quarters and interest ~0 (reported or via the opinc - pretax bridge); tiny filers without interest data |
| ebit_proxy | 58998 | 14.8 | no OperatingIncomeLoss: pretax + interest |
| acq_fill0 | 48304 | 12.2 | acquisitions: missing pieces filled with 0 |
| gp_derived | 45996 | 11.6 | gross profit = revenue - cogs (GrossProfit tag absent/stale) |
| cash_alt | 44712 | 11.2 | cash from the restricted-cash or `Cash` tag |
| sh_dil_q4derived | 42431 | 10.7 | 10-K diluted shares: Q4 derived as 4*FY - (Q1+Q2+Q3) |
| ni_fallback | 31837 | 8.0 | parent net income from a fallback tag (ProfitLoss - NCI, ...) |
| eq_derived | 31574 | 7.9 | equity derived from the other equity tag / A - L |
| mix_da | 29628 | 7.5 | mixed_tags for this concept |
| mix_net_income_incl_nci | 23358 | 5.9 | mixed_tags for this concept |
| debt_current_only | 19344 | 4.9 | only current debt tagged (no non-current debt tag in 8 quarters) |
| int_net_fallback | 18436 | 4.6 | interest expense = -net interest |
| mix_revenue | 17200 | 4.3 | mixed_tags for this concept |
| mix_cfo | 16945 | 4.3 | mixed_tags for this concept |
| mix_eps_diluted | 14818 | 3.7 | mixed_tags for this concept |
| sh_dil_annual | 12777 | 3.2 | 10-K diluted shares = annual weighted average |
| mix_interest_exp | 12135 | 3.1 | mixed_tags for this concept |
| mix_net_income | 10113 | 2.5 | mixed_tags for this concept |
| mix_pretax | 9970 | 2.5 | mixed_tags for this concept |
| debt_nc_missing | 9801 | 2.5 | non-current debt tag seen in last 8 quarters but absent at period_end: total_debt NaN |
| ttm_4q | 7987 | 2.0 | at least one concept used the 4-quarter fallback |
| shares_scale_dropped | 7891 | 2.0 | cover-page share count rejected as a scale error (x1000 ... x1e6) |
| mix_cogs | 7029 | 1.8 | mixed_tags for this concept |
| shares_bs | 5752 | 1.4 | no cover count: balance-sheet shares |
| shares_mismatch | 5658 | 1.4 | shares_out vs shares_diluted differ > 8x (one is mis-scaled) |
| mix_sga | 5290 | 1.3 | mixed_tags for this concept |
| mix_opinc | 5087 | 1.3 | mixed_tags for this concept |
| ebit_proxy_costs | 3594 | 0.9 | EBIT = revenue - CostsAndExpenses |
| shares_stale | 3547 | 0.9 | older cover count (<= 400 days) |
| amend_anchor | 2864 | 0.7 | late amendment of an older period |
| assets_from_lse | 2793 | 0.7 | assets from LiabilitiesAndStockholdersEquity |
| ebit_proxy_gp | 2632 | 0.7 | EBIT = GrossProfit - OperatingExpenses |
| mix_capex | 2369 | 0.6 | mixed_tags for this concept |
| ltd_excl_current | 1295 | 0.3 | LongTermDebt excludes the current portion for this filer |
| ppe_derived | 1195 | 0.3 | PP&E = gross - accumulated depreciation |
| sh_dil_ytd | 783 | 0.2 | diluted shares from YTD fact |

## 6. Staleness: latest snapshot per CIK, and a hole in companyfacts

- CIKs with a filing in the last 12 months: 6,046; of these **743 have a latest `period_end` before 2026-06-01** (12.3%).
- **Large accelerated filers** (EDGAR `category`, filing in the last 12 months): 2,070; **226 have a latest `period_end` < 2026-06-01** (10.9%). 71 of those have no current ticker (acquired / delisted after their last 10-Q, fine); **155 are currently listed** (140 of them stuck on a March-2026 quarter).
- **101 of those 155 listed large filers have a 10-Q filed 2026-07-22 .. 2026-08-06 in the SEC submissions data (`filings.parquet`) that is NOT in companyfacts / the facts cache**, so their newest snapshot is the March-2026 quarter. This reproduces and enlarges the research/05 s2.10 finding (12 names): the hole is in the SEC companyfacts feed, not in the builder.

Periodic filings (10-K/10-Q/KT/QT) of XBRL CIKs listed in submissions but absent from the snapshots (baseline 1-2% = filings without a balance sheet / without XBRL; July 2026 is the anomaly):

| filing month | filings | missing | missing % |
|---|---|---|---|
| 2026-01 | 299 | 9 | 3.0 |
| 2026-02 | 2524 | 18 | 0.7 |
| 2026-03 | 2529 | 43 | 1.7 |
| 2026-04 | 1150 | 33 | 2.9 |
| 2026-05 | 4382 | 33 | 0.8 |
| 2026-06 | 436 | 18 | 4.1 |
| 2026-07 | 1073 | 130 | 12.1 |
| 2026-08 | 4213 | 35 | 0.8 |
| 2026-09 | 402 | 6 | 1.5 |
| 2026-10 | 148 | 6 | 4.1 |

Consequences for the 2026-10-21 live screen: (i) `asof(snaps, "2026-10-20")` with the default `max_age_days=200` drops every company whose newest facts are the March-2026 quarter (203-204 days old on 2026-10-20), i.e. these ~101 large filers disappear from the universe; use `max_age_days=215` for the live run (the stale companies are then flagged by `period_end`) or re-download companyfacts (SEC rebuilds it nightly; the hole may be fixed upstream) and rebuild (takes ~16 s). (ii) Their TTM is one quarter old.

Listed large accelerated filers whose Q2-2026 10-Q exists in submissions but not in the facts:

```
ABT, ACHC, AMKR, AVTR, AXS, AXTA, BDN, BE, BG, BIIB, C, CAR, CARR, CB, CDNS, CHEF, CLH, CLVT, CLX, CSTM, CTS, CTSH, CURB, ELS, ENPH, ESI, EXLS, F, FE, FELE, FNMA, FRME, FTV, GD, GEF, GEHC, GRMN, GTX, HAYW, HBAN, HCA, HIW, HTO, HUBB, HUM, HURN, INCY, IQV, JCI, KN, KNSA, KNX, KO, KRC, LAZ, LFUS, LII, LSTR, MAS, MCRI, MDLZ, NOV, NXPI, OGE, OMC, ONB, OPCH, OSK, PDM, PFG, PII, PNR, POOL, PPG, PSN, PYPL, QRVO, QURE, REYN, RMBS, ROG, RS, SHEN, SITE, SMTC, SON, SPGI, STAG, SUI, TRU, TWO-PC, UDR, V, VFC, VICR, VLTO, VMC, VRSK, WELL, XIFR, ZWS
```

`asof(snaps, 2026-10-20)` returns 5,397 companies with the default `max_age_days=200` (period_end >= 2026-04-03) and 5,693 with 215.

## 7. Known gaps and limitations (read before building on this table)

1. **Revenue tag choice.** `revenue` takes the LARGEST of `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet` (priority alone picks a sub-line or a zero for ETN, PG, CCK), except that a higher-priority tag within 3% of the largest wins. That keeps WMT on net sales (728.5bn, the basis of the research GP/A vector 0.6066) instead of total revenues incl. membership (735.8bn, Yahoo's number).
2. **Restated comparatives.** TTM = FY_prev + YTD - YTD_prior mixes the FY_prev as originally filed with the (possibly recast) prior-year YTD comparative. After spin-offs / discontinued operations the result can differ from the sum of recast quarters (HON +5% revenue). Use `snapshots_first.parquet` for strict as-originally-reported numbers; the default uses the latest vintage known at the filing date.
3. **Debt.** `total_debt` = interest-bearing debt + finance leases, operating leases never included (`op_lease_*` separate). It is NaN, not 0, when unmapped; zero is inferred (`debt_zero_inferred`) only with no non-zero debt tag in 8 quarters AND positive evidence of ~0 interest (reported interest expense, or the bridge true OperatingIncomeLoss - pretax), or a tiny filer (< $250m assets) with no interest data. Segment-presented balance sheets (CAT, F) have no interim debt facts: NaN. Where a non-current debt tag existed in the last 8 quarters but is untagged now (ORCL 10-Q) the total is NaN (`debt_nc_missing`) rather than an understatement. Commercial paper nested in `ShortTermBorrowings` and `LongTermDebt` that excludes the current portion are resolved from the combined-debt / `DebtInstrumentCarryingAmount` tags when present; otherwise the documented default is used. `finance_lease` is also in the table: subtract it to get Yahoo-style debt (MSFT carries 66.6bn).
4. **EBIT.** 59k snapshots use the pretax + interest proxy (JNJ, OXY, XOM, ETN, PFE, LLY, CVX ... have no OperatingIncomeLoss). The proxy includes equity income and other non-operating items, so it differs from Yahoo's operating income by -60% (PFE) to +24% (CVX). Flag `ebit_proxy`.
5. **Shares.** `shares_out` is the dei cover count of THIS filing. Multi-class issuers (Alphabet, Meta, Ford, Berkshire, Comcast ...) have no undimensioned cover count in companyfacts: Alphabet falls back to the balance-sheet count (`shares_bs`), Meta/Ford end up NaN with `shares_diluted` as the only share count. Cover counts with scale errors (x1000, x1e6; 2% of snapshots, mostly 2010-2013) are rejected using the company's own previous cover counts (point-in-time, trailing 4) and replaced by the last sane count (`shares_stale`). `shares_diluted` itself is sometimes tagged in thousands by the filer (flag `shares_mismatch`): prefer `shares_out`. Residual: filers that mis-scale EVERY filing consistently cannot be caught by a history test (176 snapshots with shares_out > 5e10 and 2,867 with < 1000 shares, mostly shells / consistently mis-scaled filers); 95% of the cases where shares_out exceeds 8x shares_diluted carry `shares_mismatch`. Always cross-check market cap against the traded price scale before ranking.
6. **Coverage ramps with XBRL.** 2010 is large filers only; broad coverage starts with 2011-06 and full TTM history in 2012 (first 10-K with comparatives). `ttm_method == none` snapshots are mostly the first two filings of a company.
7. **Companyfacts gaps.** About 101 listed large filers (and ~174 filings in total) filed in July-August 2026 are missing from companyfacts (s6): those companies are one quarter stale and fall out of `asof` at the default 200 days. XOM history is under CIK 34088; the successor CIK 2115436 has one snapshot (balance sheet only).
8. **Odd values.** A small number of filings tag signs or scales wrongly (negative revenue in 925 snapshots, gross profit above revenue in 923, total_debt above total assets in 5.8% of snapshots: mostly genuinely levered or negative-equity companies, a few mis-scaled filings). Nothing is winsorised: apply sanity filters in the strategy layer.
9. **fiscal_period / ttm_method meaning.** `fiscal_period` is the longest duration class ending at period_end among the core flows (10-Q forms never claim FY). `ttm_method` is that of the first available of revenue, net income, operating income, CFO; individual concepts can use a different method (flag `ttm_4q`).
10. **evol.** Std (ddof=1) of discrete quarterly net income / same-quarter-end assets over up to 20 quarters, >= 12 required, computed from the vintage known at the filing date (Q4 = FY - 9M).
