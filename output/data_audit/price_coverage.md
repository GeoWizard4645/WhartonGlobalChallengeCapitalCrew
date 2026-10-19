# Price coverage and validation (Yahoo Finance via yfinance)

Generated 2026-10-18 22:10 by `quant/data/prices.py` (`python -m quant.data.prices audit`). Source of truth: `cache/prices/raw/`; derived matrices in `cache/prices/`.

## 1. Download status

* Tickers attempted: **6,169**; ok **5,588**, empty **581** (Yahoo has nothing: delisted/renamed), error **0** (transient failures after retries).
* Matrix: **4,979 trading days x 5,588 tickers**, 2007-01-03 .. **2026-10-16** (latest bar).
* Still trading (last bar within 10 days of the latest): 5,531; stopped trading / delisted but still on Yahoo: 57.
* History length of ok tickers (trading days): median 2,316, p10 174, p90 4,979; full 2007 start: 1,821.

Files:

| file | size |
|---|---|
| `cache/prices/close.parquet` | 47.4 MB |
| `cache/prices/adjclose.parquet` | 57.3 MB |
| `cache/prices/open.parquet` | 47.2 MB |
| `cache/prices/volume.parquet` | 51.2 MB |
| `cache/prices/returns.parquet` | 117.1 MB |
| `cache/prices/splits.parquet` | 32.6 KB |
| `cache/prices/meta.parquet` | 79.4 KB |
| `cache/prices/rf.parquet` | 56.9 KB |
| `cache/prices/raw/` (long source of truth) | 175.9 MB |
| `cache/prices/cleaning_log.csv` | 1.1 MB |

## 2. Validation

| check | result | detail |
|---|---|---|
| AAPL 4:1 split on 2020-08-31 in splits.parquet | PASS | found=True |
| AAPL close continuous across split (|1-day move| < 15%) | PASS | close 124.81 -> 129.04 (+3.4%); unadjusted would be 499.23 -> 129.04 |
| NVDA 10:1 split on 2024-06-10 in splits.parquet | PASS | found=True |
| NVDA close continuous across split (|1-day move| < 15%) | PASS | close 120.89 -> 121.79 (+0.7%); unadjusted would be 1208.88 -> 121.79 |
| split_factor_after('NVDA', '2024-01-01') == 10 | PASS | got 10 |
| split_factor_after('AAPL', '2019-01-01') == 4 | PASS | got 4 |
| split_factor_after('AAPL', '2013-01-01') == 28 | PASS | got 28 |
| split_factor_after('NVDA', '2025-01-01') == 1 | PASS | got 1 |
| split_factor_after('AAPL', '2020-08-31') == 1 | PASS | got 1 |
| split_factor_after('AAPL', '2020-08-28') == 4 | PASS | got 4 |
| split_factors_after vectorised (NVDA, AAPL, unknown) | PASS | [10.0, 4.0, 1.0] |
| Adj Close <= Close for dividend payers (share of days violating) | PASS | KO 0.00%, JNJ 0.00%, PG 0.00%, XOM 0.00%, MSFT 0.00%, PEP 0.00%, WMT 0.00%, MCD 0.00%, SPY 0.00%, T 0.00% |
| Adj/Close ratio is 1 at the latest bar and shrinks into the past | PASS | latest adj/close = KO 1.000000, JNJ 1.000000, PG 1.000000, XOM 1.000000, MSFT 1.000000, PEP 1.000000, WMT 1.000000, MCD 1.000000, SPY 1.000000, T 1.000000 |
| SPY total-return CAGR 2015-01-01..2024-12-31 within 0.5%/yr of ~13% | PASS | 13.00% (adjclose 2014-12-31 -> 2024-12-31); price-only 11.05% |
| rf covers every trading day through the latest price date | PASS | FRED DTB3 + ^IRX after 2026-10-15; last observation 2026-10-16; latest rf_annual 0.0407 (0.000162/day) |
| latest bar is Fri 2026-10-16 (expected as of Sun 2026-10-18) | PASS | latest = 2026-10-16 (Friday) |
| no non-positive prices in close/adjclose | PASS |  |
| index unique, sorted, datetime64[ns]; columns unique | PASS | datetime64[ns] |

## 3. Splits

2,925 split events in 1,550 tickers; **225 non-genuine** (ratio not within 0.5% of a simple fraction p/q with p,q<=20 or of N / 1/N: Yahoo spin-off adjustments). `split_factor_after` ignores them by default; `genuine_only=False` includes them.

146 of them are small stock dividends / distributions (ratio within 10% of 1, e.g. ABCB 1.00769, AGEN 1.019, AHT 1.012, AIM 1.031, AROW 1.03, BCSF 1.019); the other 79 are listed below (full list: filter `genuine == False` in `splits.parquet`).

| ticker | date | ratio |
|---|---|---|
| ABT | 2013-01-02 | 2.0842 |
| ABVC | 2016-04-11 | 3.14 |
| AGIG | 2020-08-03 | 0.08 |
| AHT | 2013-11-20 | 1.49 |
| AIV | 2020-12-01 | 0.807 |
| AIV | 2020-12-15 | 9.295 |
| ASH | 2017-05-15 | 2.044 |
| AUUD | 2026-04-01 | 0.129 |
| AYTU | 2015-06-10 | 0.082 |
| BBWI | 2021-08-03 | 1.237 |
| CFFN | 2010-12-22 | 2.2637 |
| CXT | 2023-04-04 | 2.879 |
| DD | 2019-04-02 | 1.487 |
| DELL | 2021-11-02 | 1.973 |
| DHR | 2016-07-05 | 1.319 |
| DOV | 2018-05-09 | 1.238 |
| DXC | 2015-11-30 | 1.7412 |
| EHC | 2022-07-01 | 1.257 |
| EPC | 2015-07-01 | 1.349 |
| FDX | 2026-06-01 | 1.241 |
| FTI | 2021-02-16 | 1.344 |
| FWONA | 2014-11-05 | 1.321 |
| FWONK | 2014-11-05 | 1.323 |
| GHC | 2015-07-01 | 1.655 |
| GPUS | 2023-06-23 | 1.318 |
| GYRO | 2015-09-01 | 0.09 |
| HBIO | 2013-11-04 | 1.319 |
| HLT | 2017-01-04 | 0.487329 |
| IBO | 2026-09-23 | 0.079 |
| ILLR | 2024-10-02 | 1.936 |
| INVA | 2014-06-03 | 1.241 |
| IRWD | 2019-04-02 | 1.194 |
| ITT | 2011-11-01 | 3.01568 |
| JCI | 2012-10-01 | 2.01167 |
| JTAI | 2026-07-15 | 10.548 |
| LBTYA | 2014-03-04 | 1.957 |
| LBTYA | 2024-11-13 | 1.941 |
| LBTYB | 2014-03-04 | 1.948 |
| LBTYK | 2024-11-13 | 1.91 |
| LDOS | 2013-09-30 | 0.405 |
| LILA | 2026-06-17 | 1.472 |
| LILAK | 2026-06-17 | 1.472 |
| MATX | 2012-07-02 | 2.08551 |
| MDXG | 2008-04-02 | 0.3235 |
| MIDD | 2026-07-07 | 1.243 |
| MNTS | 2025-12-18 | 0.056 |
| MSI | 2011-01-04 | 0.247372 |
| MTW | 2016-03-04 | 4.41584 |
| NC | 2012-10-01 | 3.04878 |
| NC | 2017-10-02 | 4.377 |
| NECB | 2021-07-13 | 1.34 |
| NI | 2015-07-02 | 2.545 |
| NTGR | 2019-01-02 | 1.612 |
| OPLN | 2019-06-28 | 2.642 |
| PBHC | 2014-10-17 | 1.647 |
| PENN | 2013-11-04 | 4.423 |
| PNR | 2018-05-01 | 1.489 |
| POST | 2022-03-11 | 1.528 |
| PPLI | 2020-07-01 | 3.054 |
| PROP | 2023-10-16 | 0.034 |
| QNRX | 2022-08-01 | 0.08 |
| REZI | 2026-08-04 | 1.437 |
| SAFE | 2023-03-31 | 0.16 |
| SER | 2024-03-15 | 0.028 |
| SPB | 2018-07-16 | 0.162 |
| SPXC | 2015-09-28 | 3.971 |
| SRXH | 2025-04-30 | 1.35 |
| STWD | 2014-02-03 | 1.2402 |
| T | 2022-04-11 | 1.324 |
| TDW | 2017-08-01 | 0.031 |
| TNXP | 2023-05-10 | 0.16 |
| VIP | 2021-09-15 | 0.207 |
| VNO | 2017-07-18 | 1.237 |
| WDC | 2025-02-24 | 1.323 |
| WKHS | 2025-03-17 | 0.08 |
| WNEB | 2007-01-04 | 3.28138 |
| WTW | 2016-01-05 | 0.3775 |
| XPO | 2022-11-01 | 1.683 |
| XRX | 2017-01-03 | 1.518 |

Genuine splits beyond 20:1 / 1:20 (accepted by the N / 1/N rule): ABEO 2014-10-24 0.02, ABEO 2022-07-05 0.04, ABVC 2015-08-13 0.0002, ACON 2025-01-30 0.00298507, ACON 2025-03-28 0.037037, ADIL 2023-08-07 0.04, ADIL 2026-02-06 0.04, ADV 2026-03-27 0.04, AEMD 2015-04-14 0.02, AEON 2025-02-26 0.0138889, AEYE 2018-08-08 0.04, AGL 2026-03-31 0.04, AGPU 2014-10-28 0.0133333, AGPU 2016-10-28 0.04, AIM 2019-06-11 0.0227273, AIM 2025-06-12 0.01, AIRE 2026-04-30 0.04, AIRI 2010-10-14 0.0025, AKTX 2026-03-31 0.025, ALGS 2024-08-19 0.04, ALLR 2023-03-27 0.0285714, ALLR 2023-06-29 0.025, ALLR 2024-09-11 0.0333333, ALLY 2014-04-10 310, ALT 2018-09-14 0.0333333, AMIX 2026-06-24 0.047619, AMOD 2026-06-15 0.025, ANIX 2015-06-26 0.04, APVO 2024-03-06 0.0227273, APVO 2024-12-04 0.027027, ARMP 2015-08-07 0.02, ASBP 2026-01-16 0.025, ASTC 2022-12-05 0.0333333, ASTI 2023-09-12 0.005, ASTI 2024-08-15 0.01, ATCH 2024-12-31 0.0166667, ATCH 2025-01-02 0.0166667, ATNM 2020-08-11 0.0333333, ATPC 2026-02-10 0.02, ATRA 2024-06-20 0.04 ...

## 4. Cleaning log

| rule | field | rows |
|---|---|---|
| R1_adjclose_rebuilt | adjclose | 6638 |
| R1_bad_price_row | close/adjclose | 3 |
| R2_bad_open | open | 46 |
| R5_bad_tick | adjclose | 72 |
| R5_bad_tick | close | 72 |
| R7_unadjusted_split | open/close/adjclose/volume | 5 |

Bad-tick spikes removed (R5): 144 price cells in 28 tickers. First 15 rows (all rows: `cache/prices/cleaning_log.csv`):

| yf_ticker | date | field | rule | old_value | new_value | detail |
|---|---|---|---|---|---|---|
| APRE | 2023-02-13 | close | R5_bad_tick | 0.474 | nan | pass1 prev=9.48 next=8.2 |
| APRE | 2023-02-13 | adjclose | R5_bad_tick | 0.474 | nan | pass1 prev=9.48 next=8.2 |
| ASTH | 2013-11-07 | close | R5_bad_tick | 100.1 | nan | pass1 prev=5.4 next=5.4 |
| ASTH | 2013-11-07 | adjclose | R5_bad_tick | 100.1 | nan | pass1 prev=5.4 next=5.4 |
| ASTH | 2015-04-28 | close | R5_bad_tick | 0.45 | nan | pass1 prev=4.5 next=5 |
| ASTH | 2015-04-28 | adjclose | R5_bad_tick | 0.45 | nan | pass1 prev=4.5 next=5 |
| BRTX | 2026-07-29 | close | R5_bad_tick | 4.942 | nan | pass1 prev=0.2666 next=0.2255 |
| BRTX | 2026-07-29 | adjclose | R5_bad_tick | 4.942 | nan | pass1 prev=0.2666 next=0.2255 |
| BRTX | 2026-08-04 | close | R5_bad_tick | 4.2 | nan | pass1 prev=0.1979 next=0.21 |
| BRTX | 2026-08-04 | adjclose | R5_bad_tick | 4.2 | nan | pass1 prev=0.1979 next=0.21 |
| BRTX | 2026-08-07 | close | R5_bad_tick | 4.08 | nan | pass1 prev=0.2084 next=0.201 |
| BRTX | 2026-08-07 | adjclose | R5_bad_tick | 4.08 | nan | pass1 prev=0.2084 next=0.201 |
| BRTX | 2026-08-10 | close | R5_bad_tick | 0.201 | nan | pass1 prev=4.08 next=4.2 |
| BRTX | 2026-08-10 | adjclose | R5_bad_tick | 0.201 | nan | pass1 prev=4.08 next=4.2 |
| BRTX | 2026-08-11 | close | R5_bad_tick | 4.2 | nan | pass1 prev=0.201 next=0.2123 |

After cleaning: 14,919,506 daily returns; |return| > 100%: 2,030; > 300%: 325. Non-reverting extremes are NOT altered (genuine events or unflagged Yahoo errors). Top 15 by |return|:

| ticker | date | return |
|---|---|---|
| PPCB | 2025-01-29 | +6,249,900% |
| ABVC | 2015-09-17 | +416,567% |
| NCPL | 2020-11-11 | +266,567% |
| SRXH | 2012-11-30 | +99,900% |
| SRXH | 2014-05-13 | +36,567% |
| CHRD | 2020-11-20 | +25,733% |
| AMPY | 2016-10-24 | +16,079% |
| POCI | 2010-08-23 | +14,900% |
| ATXG | 2022-08-31 | +8,654% |
| BESS | 2025-02-10 | +7,043% |
| COSM | 2022-12-16 | +6,873% |
| NIXX | 2015-03-20 | +4,900% |
| DFTX | 2019-12-27 | +4,700% |
| CELZ | 2016-04-28 | +4,445% |
| SILO | 2022-09-19 | +4,165% |

Suspicious dividends (cash dividend > 30% of the close on the ex-date, likely mis-scaled by Yahoo, distort that day's total return): 115 events in 79 tickers: SSP 2008-07-01 (1274%), ELME 2026-01-08 (530%), KDP 2018-07-10 (468%), NFE 2023-01-03 (415%), GYRO 2013-12-31 (361%), GYRE 2022-09-21 (286%), NX 2008-04-24 (239%), MO 2008-03-31 (230%), CBIO 2022-09-21 (223%), VATE 2013-08-28 (214%), CENT 2007-02-06 (199%), WY 2010-07-20 (166%), VATE 2020-05-14 (162%), VHC 2023-04-18 (159%), MBI 2023-12-26 (120%), CMCT 2014-03-26 (118%), BXMT 2012-12-21 (110%), VYX 2007-10-01 (109%), DEC 2023-11-30 (101%), VISN 2026-04-28 (101%).

## 5. Survivorship coverage (PIT S&P 1500 members with price data at each year-end)

Membership source: `quant.data.universe.members`. A member counts as covered if its `close` is non-NaN on the year-end date (or any of the previous 5 bars). Members whose Yahoo symbol is unknown/unsafe (ticker re-use nulled by the universe builder) are in the denominator and count as not covered. Cells show `covered/members (share)`.

| year-end | S&P 1500 | S&P 500 | S&P 400 | S&P 600 | tickers with a price that day |
|---|---|---|---|---|---|
| 2010-12-31 | **572/897 (63.8%)** | 344/497 (69.2%) | 228/400 (57.0%) | n/a | 2,089 |
| 2011-12-30 | **581/897 (64.8%)** | 353/497 (71.0%) | 228/400 (57.0%) | n/a | 2,145 |
| 2012-12-31 | **590/896 (65.8%)** | 364/497 (73.2%) | 226/399 (56.6%) | n/a | 2,246 |
| 2013-12-31 | **612/897 (68.2%)** | 373/497 (75.1%) | 239/400 (59.8%) | n/a | 2,354 |
| 2014-12-31 | **615/897 (68.6%)** | 378/497 (76.1%) | 237/400 (59.2%) | n/a | 2,495 |
| 2015-12-31 | **645/898 (71.8%)** | 393/498 (78.9%) | 252/400 (63.0%) | n/a | 2,612 |
| 2016-12-30 | **665/900 (73.9%)** | 413/500 (82.6%) | 252/400 (63.0%) | n/a | 2,703 |
| 2017-12-29 | **716/899 (79.6%)** | 428/499 (85.8%) | 288/400 (72.0%) | n/a | 2,866 |
| 2018-12-31 | **1,133/1,497 (75.7%)** | 439/500 (87.8%) | 307/401 (76.6%) | 387/596 (64.9%) | 3,051 |
| 2019-12-31 | **1,166/1,521 (76.7%)** | 450/500 (90.0%) | 328/399 (82.2%) | 388/622 (62.4%) | 3,236 |
| 2020-12-31 | **1,179/1,520 (77.6%)** | 457/500 (91.4%) | 332/400 (83.0%) | 390/620 (62.9%) | 3,504 |
| 2021-12-31 | **1,284/1,499 (85.7%)** | 465/500 (93.0%) | 342/399 (85.7%) | 477/600 (79.5%) | 3,977 |
| 2022-12-30 | **1,315/1,500 (87.7%)** | 474/500 (94.8%) | 348/400 (87.0%) | 493/600 (82.2%) | 4,110 |
| 2023-12-29 | **1,356/1,500 (90.4%)** | 480/500 (96.0%) | 358/400 (89.5%) | 518/600 (86.3%) | 4,241 |
| 2024-12-31 | **1,407/1,500 (93.8%)** | 486/500 (97.2%) | 375/400 (93.8%) | 546/600 (91.0%) | 4,477 |
| 2025-12-31 | **1,454/1,500 (96.9%)** | 494/500 (98.8%) | 386/400 (96.5%) | 574/600 (95.7%) | 4,932 |
| 2026-10-16 | **1,497/1,500 (99.8%)** | 500/500 (100.0%) | 400/400 (100.0%) | 597/600 (99.5%) | 5,370 |

**Ticker-reuse suspects** (price history starts >45 days after the ticker's first S&P membership): 62.

ACV (first price 2015-05-21), ASRT (first price 2026-06-15), AVB (first price 2026-08-14), BBBY (first price 2026-07-17), BEC (first price 2026-06-30), BEZ (first price 2026-02-11), BLFS (first price 2026-10-07), BRKL (first price 2026-07-07), BTU (first price 2017-04-03), CAM (first price 2025-10-06), CBL (first price 2021-11-02), CIR (first price 2026-07-07), CR (first price 2023-03-29), CRC (first price 2020-10-28), CSRA (first price 2026-08-12), DBD (first price 2023-08-14), DRIV (first price 2018-04-17), EA (first price 2026-08-04), EHAB (first price 2026-05-14), EMC (first price 2023-05-15), ENR (first price 2015-06-12), EXE (first price 2021-02-10), FLOW (first price 2023-07-13), FOX (first price 2019-03-13), GPOR (first price 2021-05-18), HF (first price 2023-08-03), HWM (first price 2016-11-01), INFO (first price 2024-10-10), JAVA (first price 2021-10-05), KHC (first price 2015-07-06), KODK (first price 2013-09-23), LEG (first price 2026-08-26), LESL (first price 2026-07-17), LMNX (first price 2026-08-27), LNW (first price 2026-10-14), LPSN (first price 2026-09-03), NE (first price 2021-06-09), NFBK (first price 2026-07-20), NFX (first price 2026-07-07), ONTO (first price 2019-10-28), OPI (first price 2026-06-18), PCL (first price 2025-08-05), PINC (first price 2026-06-11), QRVO (first price 2026-10-02), RMAX (first price 2026-08-24), SBNY (first price 2024-08-15), SFD (first price 2025-01-28), SHLD (first price 2023-09-14), SLP (first price 2026-10-07), SPLS (first price 2026-01-16), THOR (first price 2026-06-23), TIME (first price 2022-01-28), TLN (first price 2023-06-02), TWOD (first price 2025-05-16), ULTI (first price 2025-10-31), VAL (first price 2021-05-03), WBD (first price 2026-10-05), WBS (first price 2026-08-19), WH (first price 2018-05-21), WOLF (first price 2025-09-29) ...

Tickers with an internal gap > 45 calendar days (possible recycled symbol): 3: PCG-PC (107d), PCG-PI (189d), PW-PA (196d)

## 6. Caveats

* Yahoo has **no history for most delisted/acquired companies** (status `empty`); the available universe is survivor-biased. Benchmark against the equal-weight return of the same available universe (research/05_data_sources.md section 4.4).
* Ticker reuse: some symbols (FB, S, SE, STI ...) return another company's prices. The universe builder is responsible for nulling those; `meta.note` flags `late_start(...)` and long gaps as hints.
* `Adj Close` is re-based by Yahoo after every dividend: never append to a cached adjclose history. `update()` detects this and re-downloads the affected tickers.
* Volume is as quoted by Yahoo (split-adjusted share count). Prices are rounded float32-like values as served by Yahoo.

## 7. Refresh (Tuesday 2026-10-20 evening, after the 16:00 ET close)

```
.venv/bin/python -m quant.data.prices update      # window re-download, re-base check, rebuild, rf
.venv/bin/python -m quant.data.prices audit       # regenerate this report
```
