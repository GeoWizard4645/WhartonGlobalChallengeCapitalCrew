# Data-layer audit: quant.data (SEC fundamentals, prices, universe, market cap)

Auditor: independent data audit, 2026-10-18 (code under audit = working tree of that evening). No repo code was modified; only this file was written. All independent parsers and scripts are in the session scratch directory `.../scratchpad/audit_data/` (indep.py = own companyfacts + FSDS parser that does not import `quant.*`; check1.py ... mcap_series.py etc.).

**State of the code.** `quant/data/context.py` was edited while this audit ran (mtime 22:55-22:56): it now (a) picks share counts with a point-in-time reference (`_cover_reference`), (b) separates `price_factor_after` (all Yahoo ratios) from `split_factor_after` (genuine splits) for market cap, (c) adds `_repair_spinoff_returns`, (d) NaNs negative debt. I measured the pre-patch behaviour (panel built 22:46) and re-measured after the patch (panel built ~22:57). Every finding below says which state it refers to. `fundamentals.py`, `sec.py`, `prices.py`, `universe.py` and all cache files were unchanged during the audit (mtimes 22:06-22:25).

## 0. Scorecard

| # | Check | Result | Severity of what remains |
|---|---|---|---|
| 1 | Fundamentals accuracy vs independent XBRL parse (179 (cik, date) pairs, 7 metrics) | **PASS** (assets / equity / cash 100% within 1%; revenue 97%, NI 98%, EBIT 95%, debt 91% within 1%, every miss classified) | Low-Medium: NI fallback includes preferred dividends; EBIT proxy breaks when the interest tag is missing in one TTM piece (582 snapshot-quarters); stale finance-lease carry-forward |
| 2 | Look-ahead in fundamentals (84 (cik, date) pairs, 42 of them stress dates on a filing day) | **PASS** (0 differences in any column) | none found. Minor look-ahead in GICS labels (section 6.3) |
| 3 | Market cap | **FAIL before the 22:55 patch, PARTIAL after** | **High** (details 4.3): 1.16% of S&P 900 member-months have no market cap (V, BRK-B, STZ, HSY, GEF ...), GOOGL 2022-07..09 is 20x too high, ~0.15% still mis-scaled, 3 wrong CIK mappings |
| 4 | Prices / returns | Price levels and TR: **PASS** (20/20 tickers identical to a fresh Yahoo download). Return artefacts: **FAIL** | **High**: Yahoo spin-off double adjustment (DHR +61%) was in the data; the new `_repair_spinoff_returns` fixes DHR/HR but turns 9 legitimate special-dividend days into false -16% to -82% returns (KDP -82%, BKR -35%, GEN -40%, MDLZ -34% ...). Bankruptcy-emergence splice CHRD +25,733% |
| 5 | Universe | Index facts: **PASS**. Counts: PASS. GICS: **PARTIAL** (NFLX wrong 2010-2018, REIT 'Real Estate' label back-filled). Coverage: **FAIL (known)** | **High**: survivorship (only 73% of S&P 500 / 57% of S&P 400 members have prices in 2012). Medium: 3 wrong CIKs (NVE, LSI, TBL), successor registrants not stitched (BLK, BG, NWE, PNFP now; GOOGL 2016, ACE/Chubb 2016) |
| 6 | Risk-free rate | **PASS** | none |

## 1. Most important problems first (with fixes)

| Rank | Problem | Evidence (short) | Fix |
|---|---|---|---|
| 1 | `_repair_spinoff_returns` (context.py) rewrites large **special-dividend** days to price returns | 13 SP900-window cells changed: 2 right (DHR, HR), 1 still implausible (XRX), 9 wrong special-dividend days (plus EXPE 2011, ambiguous): KDP 2018-07-10 +11.5% -> **-82.1%**, BKR -7.3% -> -35.4%, GEN 2020 +4.4% -> -39.7%, LDOS, MDLZ 2012, KLAC, CXW, AIV, GEN 2016 (table in 5.3); 152 more changed cells outside SP900 windows (DXC 2015 among them). Yahoo's adjclose was right on all of them (dividend = 16-84% of price in the raw file). Only DHR and HR are real repairs; XRX is still +19.8%; DXC 2015 (outside the universe) probably wrong (-20.5%) | Restrict the repair to dates where raw Yahoo has **split != 0 AND dividend > 0 on the same ex-date** (104 such events in `cache/prices/raw/base.parquet`, only DHR, XRX, EXPE, TMUS in SP900 windows have a total-vs-price gap > 10pp). Never touch dividend-only days. Better: do it in `prices.py` (new rule R8) and log to cleaning_log.csv |
| 2 | Market cap missing / mis-scaled (`DataContext.shares_on`, `market_cap`) | NaN for 1,503 of 129,457 member-months (1.16%): V, STZ, GEF 100%, BRK-B 96%, TR, COKE, HSY 57%, SPG 42% ... (no undimensioned cover count and no diluted count). Pre-patch 828 rows had mcap < $100M (COP 91 months, MCD, KO, GRMN, DLR, BRKR, ...), 714 rows used the 'cover scale error' branch and 93% of those were off by > 100x. After the patch 179 rows < $100M remain (FOXA 2019-22, APA 2022, LIN 2018-19, ECHO 2024-26, FND 2017, NXST 2012, BRK-B 2012 ...) | (a) Fallback chain for multi-class issuers: sum of per-class dei counts (FSDS `num.txt` keeps the `segments` column), else balance-sheet `CommonStockSharesOutstanding` by class, else carry the last good count up to 400 days. (b) Reject any count that moves > 5x vs the PIT reference and is not explained by a split. (c) Add `mcap < 1e8 and index member` as a hard assertion in tests |
| 3 | Split-basis bug: cover/period-end date before a split but filing after it (`shares_on`) | GOOGL 2022-07-29, 08-31, 09-30: mcap **$25-30 trillion** (20x), still present after the patch. SHW 2021-04..06 (3x), NKE 2013, OGE, TJX, EMN, GOOGL 2014 were wrong before and are fixed by the new reference logic; AOS 2017 (2 months) and PII 2012 remain | If a genuine split falls in (shares_out_date, filed], compare cover vs cover x F against the filing-date diluted count (already restated) or the PIT reference and keep the closer one; apply the same test to the `shares_bs` (balance-sheet count) source, which is what GOOGL uses |
| 4 | Survivorship in `ctx.universe` | Priced share of true members: 2012 S&P 500 73.0% / S&P 400 57.1%; 2016 83% / 63.5%; 2020 91.6% / 83.2%; 2024 97.4% / 94.0%; 2026 99.8% / 100%. EA, LEG, AVB, QRVO, WBS, WBD ... have a single stray 2026 bar and so vanish from the universe for their whole membership | Known limitation; keep `ew_universe` control, and **report it per year** in every tear sheet. Optionally add a 'delisted' pseudo-return (acquired: last close; bankrupt: -100%) for members with no price after their last bar |
| 5 | Wrong CIK matches (`universe.CikMapper`, name-only matches) | NVE ('NV Energy') -> cik 101594 (US Energy / Big Sky Industrial, BSIN) 2012-2015: 14 quarters with assets $136M. LSI Corp (S&P 500 until 2014) -> LSI Industries (LYTS) 10 quarters. TBL ('Timberland Co A') -> Timberland Bancorp (TSBK) 2012-2013, still listed 2 years after VF bought Timberland | Add `CIK_OVERRIDES`: NVE -> 741508, LSI -> LSI Corp cik, TBL -> none; add a guard: a name-only match whose SEC assets (or mcap) is < 10% of the cohort median is rejected |
| 6 | Successor-registrant CIKs not stitched | `cache/universe/cik_aliases.csv` exists but `fundamentals()` does not use it: at 2026-09-30 BLK, BG, NWE, PNFP have **no fundamentals** (old CIK stopped filing 2023-24); GOOGL has no fundamentals at the 2016-04-29 and 2016-05-31 rebalances and a quarter-stale row before (Google Inc cik 1288776 -> Alphabet 1652044 on 2016-06-03, not in aliases); ACE/Chubb (cik 896159) is **absent from SP500 2016-01-01..2016-03-02** (missing at the 2016-01-29 and 2016-02-29 rebalances) while the acquired Chubb Corp (20171) is carried to 2016-02-22 | In `DataContext.fundamentals`, append rows of `cik_successor` registrants under the old CIK (or the reverse) and add 1288776->1652044 to `CIK_ALIASES`; fix `sp500_rows_from_fja` so ticker CB switches company on 2016-01-15 |
| 7 | Bankruptcy-emergence splice | CHRD 2020-11-20 return +25,733% (Oasis $0.12 -> new equity $31), SP400 member through the 2020-09-30 snapshot. Not caught by cleaning rule R5 (not a reversing spike) | New cleaning rule: abs(ret) > 1000% or (abs(ret) > 300% and volume < 5% of 20d median on the day before) -> set the day to NaN and invalidate pre-break prices. Backtests are protected only because the $5 price floor excludes the $0.12 stock |
| 8 | Fundamentals definitions (fundamentals.py) | (a) `R_ni` falls back to `NetIncomeLossAvailableToCommonStockholdersBasic` before `ProfitLoss - NCI`: NI after preferred dividends (WELL -19.6%, TFC -5.6%, ETR -1.5%). (b) `R_opinc` proxy `pretax + interest` sums the interest per period; if the interest tag is missing in the current YTD but present in FY and prior YTD, TTM EBIT is understated by the prior-YTD interest (OI 2014-06: 520 vs 591, -12%; 582 snapshot-quarters differ > 5% from pretax+interest, 266 of them non-financials in 46 companies). (c) `carry_fwd` of finance leases from stale filings (ALGN Q3-2019: 56.1M carried from Q1-2019, true ~10M after 45.8M of principal payments). (d) `_maxof` picked an intersegment line for MHK 2013-14 (revenue -$107M) | (a) reorder fallbacks. (b) compute the proxy only when the interest value exists for every piece, else fall back to `ebit_proxy_costs` / NaN. (c) drop carried lease items when the current filing has any lease tag. (d) exclude negative revenue candidates |
| 9 | GICS labels | NFLX is 'Information Technology / Internet Software & Services' in 2015-2018-09 (true: Consumer Discretionary). 505 rows before 2016-09-01 (HCN, HCP, HST, VTR ...) carry the 'Real Estate' sector that did not exist yet (taken from a later reference, `gics_source = asof_next`; 28,082 S&P 500 rows (18%) get GICS from a later snapshot) | Override NFLX; map pre-2016-09 REITs to 'Financials' (GICS of that date) or document that sector exclusions treat them as Real Estate |
| 10 | Completeness holes | companyfacts lacks 5 periodic filings of ever-members since 2023 (SPGI FY2024 10-K filed 2025-02-11, AOS FY2024 10-K, BWXT Q2-2026 10-Q, CR FY2022 10-K, FLG Q1-2025 10-Q); S&P 400 snapshot 2013-09-30 has only 376 names (-24) and 2021-03-31 has 396; 0.52% of SP900 member-months have no snapshot (REG, MAA, SKT, HST dual registrants, STE, WCN, AVGO) | Extend `build_fsds_patch` quarters to 2025q1 / 2023q1 for those accessions; gap-fill the two short SP400 snapshots from neighbours |

## 2. Check 1: fundamentals accuracy

**Method.** Independent parser (`indep.py`): reads `CIK##########.json` straight from `cache/sec/companyfacts.zip` (plus FSDS `num.txt` for accessions missing from the zip when the date is in 2026), keeps 10-K/10-Q/-A/-KT/-QT facts with `filed < date`, takes the latest vintage per (tag, start, end), classifies durations (quarter 70-110 d, H1 160-200, 9M 250-290, FY 350-380) and builds TTM as FY, FY_prev + YTD - YTD_prior, or the sum of four quarters. Revenue = merged per-period series over six revenue tags; NI = NetIncomeLoss, else ProfitLoss - NCI, else NetIncomeLossAvailableToCommonStockholdersBasic; EBIT = OperatingIncomeLoss else pretax + InterestExpense; balance sheet items at the latest `Assets` instant; debt = LongTermDebt(Noncurrent) + current debt + ShortTermBorrowings + CommercialPaper + NotesPayableCurrent (+ finance leases). Sample: 30 random (cik, month-end) pairs among point-in-time S&P 900 members, 2 per year 2012-2026 and sectors cycled over all 11 GICS sectors (seed fixed), then 149 more (10 per year, same stratification) to get power. Each pair compares `ctx.fundamentals(date)`: revenue, net_income, opinc, assets, equity_parent, cash, total_debt.

Percent differences, (ctx - independent) / independent. `mine n/a` = my simple parser found no usable tag (checked by hand where ctx had a value, see below); `ours n/a` = ctx has NaN.

### 2.1 The 30 required samples

| # | date | ticker | GICS sector | filing used (form, filed) | Rev | NI | EBIT | Assets | Equity | Cash | Debt |
|---|---|---|---|---|---|---|---|---|---|---|---|
| 1 | 2012-04-30 | LOW | Consumer Discretionary | 10-K/A 2012-04-10 | 0.00 | 0.00 | mine n/a | 0.00 | mine n/a | 0.00 | 0.00 |
| 2 | 2012-06-29 | NBR | Energy | 10-Q 2012-05-04 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 3 | 2013-02-28 | OKE | Utilities | 10-K 2013-02-26 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | +12.52 |
| 4 | 2013-08-30 | SRE | Utilities | 10-Q 2013-08-06 | ours n/a | 0.00 | mine n/a | 0.00 | 0.00 | 0.00 | mine n/a |
| 5 | 2014-09-30 | CBOE | Financials | 10-Q 2014-08-06 | 0.00 | +0.22 | 0.00 | 0.00 | mine n/a | 0.00 | both n/a |
| 6 | 2014-12-31 | DOC | Real Estate | 10-Q 2014-11-04 | 0.00 | 0.00 | mine n/a | 0.00 | 0.00 | 0.00 | 0.00 |
| 7 | 2015-02-27 | OLN | Materials | 10-K 2015-02-25 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | +0.53 |
| 8 | 2015-04-30 | MS | Financials | 10-K 2015-03-02 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 9 | 2016-01-29 | ES | Utilities | 10-Q 2015-11-06 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a | 0.00 |
| 10 | 2016-10-31 | DOC | Real Estate | 10-Q 2016-08-09 | 0.00 | 0.00 | mine n/a | 0.00 | 0.00 | 0.00 | 0.00 |
| 11 | 2017-05-31 | ABT | Health Care | 10-Q 2017-05-03 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 12 | 2017-12-29 | CSX | Industrials | 10-Q 2017-10-18 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a | 0.00 | mine n/a |
| 13 | 2018-10-31 | ULTA | Consumer Discretionary | 10-Q 2018-08-30 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a |
| 14 | 2018-03-29 | BFH | Information Technology | 10-K 2018-02-27 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 15 | 2019-12-31 | ECL | Materials | 10-Q 2019-10-31 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a |
| 16 | 2019-09-30 | NFLX | Communication Services | 10-Q 2019-07-19 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 17 | 2020-09-30 | GIS | Consumer Staples | 10-Q 2020-09-23 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 18 | 2020-01-31 | ALGN | Health Care | 10-Q 2019-10-31 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a |
| 19 | 2021-04-30 | ACIW | Information Technology | 10-K 2021-02-25 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 20 | 2021-03-31 | MO | Consumer Staples | 10-K 2021-02-26 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 21 | 2022-11-30 | MDLZ | Consumer Staples | 10-Q 2022-11-01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a | mine n/a |
| 22 | 2022-02-28 | WMB | Energy | 10-Q 2021-11-01 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a |
| 23 | 2023-02-28 | JPM | Financials | 10-K 2023-02-21 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a | mine n/a |
| 24 | 2023-10-31 | CSCO | Information Technology | 10-K 2023-09-07 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |
| 25 | 2024-04-30 | CW | Industrials | 10-K 2024-02-20 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a | 0.00 |
| 26 | 2024-10-31 | XPO | Industrials | 10-Q 2024-10-30 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | +7.27 |
| 27 | 2025-04-30 | DIS | Communication Services | 10-Q 2025-02-05 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | +0.42 |
| 28 | 2025-09-30 | WSM | Consumer Discretionary | 10-Q 2025-08-29 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a |
| 29 | 2026-09-30 | DVA | Health Care | 10-Q 2026-08-04 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | mine n/a |
| 30 | 2026-02-27 | DTM | Energy | 10-K 2026-02-19 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 | 0.00 |

### 2.2 All 179 pairs

| metric | pairs compared | within 1% | over 1% | mine n/a (parser could not find tag) | ours n/a | both n/a |
|---|---|---|---|---|---|---|
| revenue | 171 | 166 | 5 | 1 | 3 | 4 |
| net_income | 177 | 174 | 3 | 0 | 1 | 1 |
| opinc | 155 | 148 | 7 | 19 | 2 | 3 |
| assets | 178 | 178 | 0 | 0 | 1 | 0 |
| equity_parent | 163 | 163 | 0 | 15 | 1 | 0 |
| cash | 165 | 165 | 0 | 9 | 1 | 4 |
| debt | 108 | 98 | 10 | 65 | 0 | 6 |

157 of 179 pairs (88%) have every comparable metric within 1%; the rest are classified here.

| Pair | Metric | Diff | Class | Explanation |
|---|---|---|---|---|
| OKE 2013-02 | Debt | +12.5% | definitional | ctx includes `ShortTermBankLoansAndNotesPayable` 817M (7,343 = 6,515 + 11 + 817); my parser had no tag for it |
| NDSN 2015-05, J 2015-03, EVRG 2022-07, AZO 2026-01 | Debt | +24.4 / +6.3 / +14.6 / +4.6% | definitional | ctx adds `DebtCurrent` / short-term borrowings and commercial paper that my simple sum omitted |
| XPO 2024-10 | Debt | +7.3% | ours slightly off | 3,586 = 3,343 + 243 finance lease carried from the 10-K; the filing's `DebtAndCapitalLeaseObligations` is 3,519 (+1.9%) |
| OLN 2015-02, DIS 2025-04 | Debt | +0.5 / +0.4% | definitional | finance/capital leases included (research/03 s5.2) |
| WELL 2014-12, TFC 2020-11, ETR 2019-05 | NI | -19.6 / -5.6 / -1.5% | **ours (minor)** | `NetIncomeLossAvailableToCommonStockholdersBasic` fallback = NI after preferred dividends; should use ProfitLoss - NCI first |
| HR 2019-04 | Revenue | +5,535% | my parser | my merge preferred a 8M sub-line; ctx 450.4M is correct (`_maxof`) |
| OXY 2018-10, LUMN 2018-08 | Revenue | +2.1 / +3.1% | definitional | ASC 606 transition: FY_prev (old tag) + YTD (new tag) - prior YTD (recast); the documented 'mixed tags' limitation |
| EVRG 2022-07, EQT 2025-01 | Revenue | +3.3 / +13.5% | definitional | ctx takes the larger 'Revenues' (total operating revenues incl. alternative revenue / derivative gains) over `RevenueFromContract...` |
| OI 2014-06 | EBIT | **-12.0%** | **ours (bug)** | proxy pretax + interest with `InterestExpense` absent in Q1-2014: TTM = (FY13 pretax + 239) + (Q1-14 pretax + 0) - (Q1-13 pretax + 71); true 591 vs ctx 520 |
| MET 2012-04 | EBIT | -5.3% | proxy | insurer, pretax + interest proxy differences |
| GPC 2019-09, RLI 2021-04 | EBIT | -1.4 / +2.1% | proxy | same family as OI |
| JCI 2017-04, OXY 2018-10, BXP 2020-03 | EBIT | +100 / +109 / +15% | my parser | I used a stale `OperatingIncomeLoss`; ctx proxies equal my own proxy to the dollar |
| SRE 2013-08, SWX 2026-06, KRC 2016-04 | Revenue | ours NaN | coverage gap | the registrants tag only dimensioned revenues in those filings |

Remaining `mine n/a` items were verified by hand: CSX / WMB / MDLZ / ECL / JPM / DVA total debt equals `LongTermDebtAndCapitalLeaseObligations(+Current)`, `DebtAndCapitalLeaseObligations` or `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities` (+ ShortTermBorrowings) in the filing; ULTA and WSM have no borrowings. ALGN 2019-Q3 finance lease: see problem 8c. The 2026 pairs (DVA 2026-09-30, DTM) were recomputed from FSDS and match, which validates the `facts_patch/` partitions for those filings. Balance-sheet sanity over 43,055 SP900 member-quarters sampled every third month: cash > assets, current assets > assets, equity > assets: 0 violations; assets <= 0: 2 (BKR 2017 shell registrant); revenue < 0: 7 (MHK 2013-14, CNX).

**Coverage of the snapshot fields (SP900 non-financial/non-REIT members, per year, from `ctx.fundamentals`):** revenue 92% (2012) -> 94% (2016) -> 98-99% (2020+); gross profit 71-76% (many filers do not report COGS); opinc 95-98%; total_debt 92-95% (NaN, not 0, when unmapped); shares_out 91-94% (rest falls back to diluted); `evol` 30% in 2012 (needs 12 quarters). Overall 0.52% of SP900 member-months have no snapshot at all.

## 3. Check 2: look-ahead

84 (cik, date) pairs (79 distinct companies, 2012-01-31 .. 2026-08-31). 42 are 'stress' dates: the signal date is a filing date of that company (or the day after), and 32 of the 84 had a filing dated exactly on the signal date. For every pair:

1. the snapshot row used by `asof` has `filed < date` (84/84);
2. I loaded all facts for the cik (`sec.load_facts`, includes the FSDS patch), kept only `filed < date`, ran `fundamentals.snapshots_from_facts` and applied `asof`: it returns the same accession (84/84) and **all numeric columns (~80) and the text/date columns (flags, ttm_method, fiscal_period, period_end, fy_end_date, shares_out_date) are identical** (tolerance 1e-6 relative);
3. rebuilding from the full facts gives the identical row for the same accession (0 differences).

Result: **PASS**. The per-company anchor calendar, restatement vintages and the 'running maximum' period_end logic do not leak later information into earlier rows. Completeness cross-check: 99.8%+ of 10-K/10-Q accessions listed in `submissions` for 1,119 ever-members are present in facts+patch (2012: 98.8%, 2013+: 99.6-100%); 5 missing since 2023 (problem 10).

## 4. Check 3: market cap

### 4.1 Current large/mid caps vs Yahoo (`fast_info['market_cap']`, 2026-10-16 close, code state after the patch)

39 priced S&P 900 members (20 S&P 500 and 14 S&P 400 drawn at random, plus GOOGL, BRK-B, META, NVDA, AMZN, TSLA). Prices identical for 39/39; 38 have a market cap on both sides. Market cap ours/Yahoo: median 1.0000, 27 within 0.1%, 33 within 0.5%, 36 within 1%, 37 within 3%; BRK-B NaN. Yahoo's share counts come from the same SEC cover page, so this validates plumbing and splits, not the SEC counts themselves (see 4.3 for an independent test). Largest deviations:

| ticker | ours ($B) | Yahoo fast_info ($B) | ours/Yahoo | price ours/Yahoo | share source |
|---|---|---|---|---|---|
| INTC | 453.2 | 472.1 | 0.9599 | 1.0000 | cover |
| SN | 26.3 | 26.4 | 0.9954 | 1.0000 | cover |
| NVDA | 5,160.5 | 5,170.6 | 0.9981 | 1.0000 | cover |
| VMC | 33.3 | 33.4 | 0.9986 | 1.0000 | cover |
| VRSN | 27.3 | 27.3 | 0.9989 | 1.0000 | cover |
| KNX | 10.6 | 10.6 | 0.9999 | 1.0000 | cover |
| NOV | 6.8 | 6.8 | 1.0023 | 1.0000 | cover |
| ACN | 141.4 | 140.6 | 1.0060 | 1.0000 | diluted |
| META | 1,820.1 | 1,807.0 | 1.0073 | 1.0000 | diluted |
| BR | 20.0 | 19.8 | 1.0099 | 1.0000 | cover |
| CVNA | 43.5 | 42.4 | 1.0278 | 1.0000 | diluted |
| BRK-B |  | 1,138.9 |  | 1.0000 | missing |

INTC (-4.0%) is staleness: cover count 5.044B at 2026-07-17 vs a newer Yahoo count. CVNA / META / ACN use the diluted fallback (multi-class cover pages). BRK-B has no share count at all (problem 2).

### 4.2 Historical values and split handling

Reference values are well-known approximate market caps recalled from memory (not looked up), so +-3% is the expected tolerance; the 'before patch' column lists ratios that were wrong before 22:55.

| ticker | date | reference mcap ($B, approx. from memory) | ctx.market_cap ($B, current code) | ratio | ratio before 22:55 patch (if it differed) | share source | note |
|---|---|---|---|---|---|---|---|
| AAPL | 2020-08-28 | 2,130 | 2,134.5 | 1.002 |  | cover | AAPL 4:1 split 2020-08-31 (ex-date after) |
| NVDA | 2024-06-07 | 2,970 | 2,973.8 | 1.001 |  | cover | NVDA 10:1 split 2024-06-10 |
| MSFT | 2015-12-31 | 440 | 443.2 | 1.007 |  | cover |  |
| XOM | 2014-06-30 | 430 | 432.4 | 1.005 |  | cover |  |
| AMZN | 2021-12-31 | 1,690 | 1,691.0 | 1.001 |  | cover | AMZN 20:1 split 2022-06-06 |
| TSLA | 2020-12-31 | 668 | 668.9 | 1.001 |  | cover | TSLA 5:1 2020-08, 3:1 2022-08 |
| GOOGL | 2021-12-31 | 1,920 | 1,925.6 | 1.003 |  | cover | Alphabet 20:1 split 2022-07-18; dual class |
| GOOGL | 2022-07-15 | 1,480 | 1,472.7 | 0.995 |  | cover | day before 20:1 split |
| NVDA | 2021-06-30 | 500 | 498.5 | 0.997 |  | cover | NVDA 4:1 split 2021-07-20 |
| NFLX | 2015-12-31 | 49 | 48.9 | 0.998 |  | cover | NFLX 7:1 split 2015-07 |
| JNJ | 2015-12-31 | 285 | 284.2 | 0.997 |  | cover |  |
| WMT | 2016-12-30 | 210 | 212.4 | 1.012 |  | cover |  |
| GE | 2017-12-29 | 152 | 151.3 | 0.996 | 0.957 | cover |  |
| META | 2018-12-31 | 380 | 381.9 | 1.005 |  | diluted | FB |
| KO | 2019-12-31 | 237 | 237.1 | 1.001 |  | cover |  |
| BRK-B | 2019-12-31 | 515 | NaN (shares missing) |  |  | missing | Berkshire multi-class |
| AAPL | 2015-12-31 | 586 | 586.9 | 1.001 |  | cover | AAPL pre-2020 4:1 and 2014 7:1 |
| AMZN | 2015-12-31 | 318 | 316.8 | 0.996 |  | cover |  |
| V | 2018-12-31 | 305 | NaN (shares missing) |  |  | missing | Visa |
| XOM | 2019-12-31 | 300 | 295.2 | 0.984 |  | cover |  |
| SMCI | 2024-03-28 | 54 | 56.5 | 1.046 |  | cover | SMCI 10:1 split 2024-10-01, mcap ~54B |
| AAPL | 2012-12-31 | 500 | 500.6 | 1.001 |  | cover | AAPL 2012 year-end |
| MSFT | 2020-12-31 | 1,680 | 1,681.6 | 1.001 |  | cover |  |
| NFLX | 2021-12-31 | 267 | 266.9 | 0.999 |  | cover |  |
| TSLA | 2021-12-31 | 1,060 | 1,061.3 | 1.001 |  | cover | TSLA pre 3:1 (Aug 2022) |
| NVDA | 2023-12-29 | 1,220 | 1,223.2 | 1.003 |  | cover | NVDA pre 10:1 (Jun 2024) |
| SHW | 2021-06-30 | 70 | 73.7 | 1.053 | 3.105 | diluted(cover mis-scaled vs history) | SHW 3:1 split 2021-04-01 (filed after split) |
| ABT | 2012-12-31 | 103 | 103.5 | 1.005 | 0.482 | cover | ABT/ABBV spin 2013-01-02 |
| IBM | 2012-12-31 | 216 | 216.4 | 1.002 | 0.892 | cover | IBM/Kyndryl pseudo-split |
| GOOGL | 2022-08-31 | 1,500 | 28,306.0 | 18.871 | 18.870 | cover | Alphabet 20:1 split 2022-07-18 |

Clean checks (AAPL 4:1 2020 and 2014, NVDA 4:1 2021 and 10:1 2024, TSLA 5:1 2020 and 3:1 2022, AMZN 20:1 2022, NFLX 7:1 2015, GOOGL 20:1 2022 at the two dates around the split, SMCI 10:1 2024) are all within 1.5% of the reference. The remaining failures are GOOGL 2022-08-31 (20x, problem 3) and BRK-B / V (NaN, problem 2). Pre-patch, ABT 2012 (-52%, ABBV spin), IBM 2012 (-11%, Kyndryl), GE 2017 (-4%), SHW 2021 (3.1x) were wrong and are fixed in the current code.

### 4.3 Population-wide test on all S&P 900 member-months (2012-01 .. 2026-09, 129,457 rows)

| Defect | Before patch | After patch |
|---|---|---|
| mcap NaN (no share count) | 1,503 (1.16%), 29 tickers | 1,503 (unchanged) |
| mcap < $100M for an index member | 828 (0.64%); 678 of them from the 'cover scale error' branch | 179 (0.14%) |
| mcap > $10T | 10 | 3 (GOOGL 2022 split-basis) |
| rows using the 'diluted(cover scale error?)' branch | 714; of 497 with a cover reference 93.4% were > 100x off | 0 (branch replaced) |
| spin-off/pseudo-split price inconsistency (Yahoo `Close` back-adjusted by non-genuine ratios, share counts not) | 3,538 member-months (2.7%), 40 tickers; median error -19%, ABT -52%, AIV -87%, TDW +3,126%, PNR -33% | fixed for the cases tested (ABT 1.005, IBM 1.002, GE 0.996) |
| genuine split between cover date and filing (shares x split twice) | 21 member-months (GOOGL 2014 and 2022, SHW, NKE, OGE, TJX, AOS, EMN) | 6 (GOOGL 2022 x3, AOS x2, PII x1) |

Independent level test with the SEC cover field `dei:EntityPublicFloat` (non-affiliate market value at the last business day of Q2 in every 10-K): 3,658 observations on 297 randomly drawn S&P 900 companies 2012-2025, comparing `ctx.market_cap` on the float date. Median mcap / float = 1.016 (P5 0.98, P25 1.003, P75 1.097, P95 1.68; > 1 because affiliates are excluded). Cases with ratio < 0.01: 34 before the patch, 21 after, of which 15 are the filer's float being 1000x too large in SEC data (NOVT, CXW, DXCM, KTOS, SITM, TRMK, WT) and 6 are ours (LIN 2018-06, BRK-B 2012-06, ECHO 2024 and 2025, NXST 2012, FND 2017) = 0.16% of observations. The SEC data itself contains 1000x scale errors in `EntityPublicFloat` (EBAY, HXL, PKG, CBT ...), confirming that cover-count scale errors exist upstream and justifying the reference logic.

## 5. Check 4: prices and returns

### 5.1 Total return vs a fresh Yahoo download

20 tickers (the 15 asked for plus MMM, DIS, ABT, DD, HPQ), `ctx.adjclose` vs `yf.download(auto_adjust=True)` today, 2015-01-02 .. 2025-12-31 (2,765 common days each). Largest absolute CAGR difference = 0.00001 pp, largest daily-return difference 1.5e-6, zero days differing by more than 10 bp. **PASS.** (Both come from Yahoo, so this proves cache fidelity and rebasing, not Yahoo's accuracy; spot checks of raw levels against well-known closes: AAPL 2020-08-28 499.23, NVDA 2024-06-07 1,208.88, MSFT 2015-12-31 55.48, SMCI 2024-03-28 1,010.03, IBM 2012-12-31 191.55 (Yahoo `Close` shows 183.13 because it back-adjusts for the Kyndryl spin), ABT 2012-12-31 65.50 (Yahoo 31.43), all as expected.)

| ticker | TR ctx 2015-01-02..2025-12-31 (%) | TR yfinance now (%) | CAGR ctx (%) | CAGR yf (%) | dCAGR (pp) | max abs daily-return diff |
|---|---|---|---|---|---|---|
| AAPL | 1021.60 | 1021.60 | 24.59 | 24.59 | 0.00000 | 1.3e-06 |
| MSFT | 1113.30 | 1113.30 | 25.48 | 25.48 | 0.00001 | 1.1e-06 |
| JPM | 589.70 | 589.70 | 19.20 | 19.20 | 0.00000 | 1.1e-06 |
| XOM | 107.80 | 107.80 | 6.88 | 6.88 | 0.00000 | 1.1e-06 |
| JNJ | 168.90 | 168.90 | 9.41 | 9.41 | 0.00000 | 9.3e-07 |
| KO | 134.70 | 134.70 | 8.07 | 8.07 | 0.00000 | 1.2e-06 |
| TSLA | 2975.90 | 2975.90 | 36.56 | 36.56 | 0.00000 | 0.0e+00 |
| NVDA | 38511.90 | 38511.90 | 71.89 | 71.89 | 0.00001 | 1.3e-06 |
| AMZN | 1396.30 | 1396.30 | 27.90 | 27.90 | 0.00000 | 0.0e+00 |
| GOOGL | 1091.10 | 1091.10 | 25.27 | 25.27 | 0.00000 | 6.6e-07 |
| IBM | 201.90 | 201.90 | 10.57 | 10.57 | 0.00000 | 1.0e-06 |
| GE | 200.30 | 200.30 | 10.52 | 10.52 | -0.00000 | 1.5e-06 |
| T | 113.10 | 113.10 | 7.12 | 7.12 | -0.00000 | 1.0e-06 |
| F | 53.80 | 53.80 | 4.00 | 4.00 | 0.00000 | 1.0e-06 |
| BRK-B | 237.00 | 237.00 | 11.68 | 11.68 | 0.00000 | 0.0e+00 |
| MMM | 66.60 | 66.60 | 4.75 | 4.75 | 0.00000 | 1.2e-06 |
| DIS | 33.30 | 33.30 | 2.65 | 2.65 | 0.00000 | 5.0e-07 |
| ABT | 244.00 | 244.00 | 11.89 | 11.89 | -0.00001 | 1.1e-06 |
| DD | 91.70 | 91.70 | 6.10 | 6.10 | -0.00000 | 1.0e-06 |
| HPQ | 74.30 | 74.30 | 5.18 | 5.18 | -0.00000 | 1.1e-06 |

### 5.2 Returns beyond 50% in absolute value among S&P 900 members (36 events, adjclose returns, before any repair)

| ticker | date | adjclose return (%) | split-adj close return (%) | assessment |
|---|---|---|---|---|
| VRTX | 2012-05-07 | 55.40 | 55.40 | volume spike; not independently verified |
| VRTX | 2013-04-19 | 61.90 | 61.90 | persists, volume 17x; not independently verified |
| MTUS | 2016-01-29 | 75.00 | 75.00 | persists, volume 10x; not independently verified |
| AMD | 2016-04-22 | 52.30 | 52.30 | real (Q1 earnings, +52%) |
| DHR | 2016-07-05 | 61.20 | 3.60 | ARTIFACT: Yahoo books Fortive spin as split 1.319 AND dividend 24.56 (double adjustment); true TR about +3.6% |
| PCG | 2019-01-14 | -52.40 | -52.40 | real (bankruptcy warning) |
| PCG | 2019-01-24 | 74.60 | 74.60 | real/volatile; volume 82M |
| APA | 2020-03-09 | -53.90 | -53.90 | real (oil price war) |
| OXY | 2020-03-09 | -52.00 | -53.40 | real |
| MTDR | 2020-03-09 | -64.10 | -64.10 | real |
| CHRD | 2020-03-09 | -61.60 | -61.60 | real |
| CHRD | 2020-03-13 | 170.30 | 170.30 | real (rebound) |
| CHRD | 2020-03-16 | -58.00 | -58.00 | real |
| FLR | 2020-03-19 | 76.20 | 76.20 | March 2020 volatility, not verified |
| SVC | 2020-03-19 | 50.60 | 50.60 | March 2020 |
| CNK | 2020-03-19 | 73.10 | 73.10 | March 2020 |
| NUS | 2020-03-19 | 57.40 | 57.40 | March 2020 |
| CHRD | 2020-04-23 | 131.00 | 131.00 | penny-stock (Oasis, $0.1-0.4) in bankruptcy; real moves |
| RIG | 2020-06-05 | 50.60 | 50.60 | June 2020 energy rally; not independently verified |
| CHRD | 2020-06-05 | 125.00 | 125.00 | penny stock |
| CHRD | 2020-06-08 | 61.90 | 61.90 | penny stock |
| CHRD | 2020-11-11 | 88.90 | 88.90 | penny stock |
| CHRD | 2020-11-20 | 25733.30 | 25733.30 | ARTIFACT: old Oasis equity ($0.12) spliced to the post-emergence CHRD shares ($31): +25,733%. Ticker was an SP400 member until the 2020-09-30 snapshot |
| PRG | 2021-04-07 | 66.70 | 66.70 | not independently verified |
| CAR | 2021-11-02 | 108.30 | 108.30 | real (Avis short squeeze, +108%) |
| SHC | 2023-01-10 | 99.70 | 99.70 | persists, volume 49M vs 1M; not independently verified |
| VICR | 2023-07-26 | 57.70 | 57.70 | persists |
| CPRI | 2023-08-10 | 55.70 | 55.70 | real (Tapestry bid) |
| GL | 2024-04-11 | -53.10 | -53.10 | real (short report, -53%) |
| GME | 2024-05-13 | 74.40 | 74.40 | real (Roaring Kitty) |
| GME | 2024-05-14 | 60.10 | 60.10 | real |
| MEDP | 2025-07-22 | 54.70 | 54.70 | real (earnings) |
| ECHO | 2025-08-26 | 70.20 | 70.20 | real (spectrum sale, +70%) |
| KD | 2026-02-09 | -54.90 | -54.90 | after my knowledge; volume spike |
| STRL | 2026-05-05 | 52.20 | 52.20 | after my knowledge; volume spike |
| MRNA | 2026-08-19 | 177.00 | 177.00 | after my knowledge; volume 199M vs 4M and persists next days |

Two true data artefacts (DHR, CHRD); everything else is a real event with a volume spike that persists. Rule R5 of the cleaning pass only removes one-day spikes that reverse, so neither artefact is caught. 36 events in 14.7 years of ~800 names is a clean series otherwise.

### 5.3 Yahoo spin-off artefacts and the new repair

Yahoo books many spin-offs as 'split + dividend' on the same ex-date and then adjusts `Adj Close` for both (raw file: DHR 2016-07-05 dividend 24.56 AND split 1.319; XRX 2017-01-03 2.98 + 1.518; EXPE 2011-12-21 15.125 + 0.5; TMUS 2013-05-01 4.06 + 0.5). 104 such events exist in the whole file, 4 with a > 10pp effect in S&P 900 windows. The 22:55 patch `_repair_spinoff_returns` instead replaces **any** day where abs(total return - price return) > 15% by the price return, which also hits legitimate special dividends:

| ticker | date | original adjclose return (%) | split-adj close return (%) | ctx.returns after _repair_spinoff_returns (%) | assessment |
|---|---|---|---|---|---|
| DHR | 2016-07-05 | +61.2 | +3.6 | +3.6 | correct repair (Yahoo split 1.319 + dividend 24.56 double count) |
| HR | 2022-07-21 | +25.9 | +0.9 | +0.9 | plausible repair (HTA/HR merger 'dividend' 4.82 = 20% of price) |
| XRX | 2017-01-03 | +37.6 | +19.8 | +19.8 | still implausible: Conduent spin (split 1.518 + dividend 2.98); Yahoo's 1.518 factor looks too large |
| KDP | 2018-07-10 | +11.5 | -82.1 | -82.1 | FALSE LOSS: $103.75 special dividend (84% of price); Yahoo adjclose was right |
| BKR | 2017-07-05 | -7.3 | -35.4 | -35.4 | FALSE LOSS: $17.50 special dividend (30% of price) |
| GEN | 2020-02-03 | +4.4 | -39.7 | -39.7 | FALSE LOSS: $12 special dividend (42% of price) |
| GEN | 2016-03-04 | +0.6 | -19.0 | -19.0 | FALSE LOSS: special dividend |
| LDOS | 2016-08-17 | +1.2 | -25.5 | -25.5 | FALSE LOSS: $13.64 special dividend |
| MDLZ | 2012-10-02 | -1.2 | -34.1 | -34.1 | FALSE LOSS: Kraft spin-off/dividend 14.17 (33% of price) |
| KLAC | 2014-11-26 | -0.5 | -20.0 | -20.0 | FALSE LOSS: special dividend 1.65 (split-adj. basis, 19.6% of price) |
| CXW | 2013-04-17 | -2.0 | -17.9 | -17.9 | FALSE LOSS: special dividend 6.63 |
| AIV | 2020-11-03 | +12.7 | -16.1 | -16.1 | FALSE LOSS: special dividend 1.09 (25% of price) |
| DXC (outside universe) | 2015-11-30 | +8.4 | -20.5 | -20.5 | Likely false loss: CSRA spin booked as dividend 9.08, Close history NOT back-adjusted (34.09 -> 27.10) |

EXPE 2011-12-21 (original -33.6%, repaired -51.2%) is the 13th changed in-window cell; it predates the 2012 backtest start and I could not decide which value is right. In the raw file the KDP day has `dividend = 103.75`, `close` 123.66 -> 22.19, adjclose +11.5%; the same pattern holds for every row marked FALSE LOSS. The patch changes 165 cells in total (13 in S&P 900 windows).

## 6. Check 5: universe

### 6.1 Index events

| name | event | what ctx/membership says | result |
|---|---|---|---|
| TSLA | 2020-12-21 | absent 2020-12-18 / 2020-11-30, present 2020-12-21 / 2020-12-31 | PASS |
| META (FB) | 2013-12-23 | absent 2013-12-20, present 2013-12-23 and 2014-06-30; present 2022-06-30 as META | PASS |
| SMCI | 2024-03-18 | absent 2024-03-15, present 2024-03-18 | PASS |
| UBER | 2023-12-18 | absent 2023-12-15, present 2023-12-18 | PASS |
| PLTR, DELL | 2024-09-23 | absent 09-20, present 09-23 (AAL leaves on 09-23) | PASS |
| COIN / DASH / APP | 2025-05-19 / 2025-03-24 / 2025-09-22 | absent before, present on date | PASS |
| KMI, NFLX | 2012-05-25 / 2010-12-20 | absent before, present after | PASS |
| GPS (Gap) | removed 2022-02-02 | ours: last in SP500 snapshot 2022-01-10, gone from 2022-02-02 snapshot; independent fja05680 file: end 2022-02-02. (The 2018 date in the task brief is not what any source shows.) | PASS |
| TWTR, SIVB, FRC, WBA | 2022-11-01 / 2023-03-15 / 2023-05-04 / 2025-08-28 | match fja05680 end dates | PASS |

In addition, the live Wikipedia constituents table (503 current members, fetched once) lists 'Date added' for 236 members added since 2010: ours matches the exact day for 206, within 7 days for 218, within 31 days for 221. The rest are successor-registrant or re-listing artefacts of Wikipedia's own column (CB, JCI, GOOG, AVGO, HWM, D, SRE, TROW, HUM, MDLZ, FOX/NWS ...), except ACE/Chubb 2016 (problem 6). 4 of 503 current members cannot be matched by CIK to Wikipedia (BLK, BG, XOM, SKYD: new registrants, handled by `cik_aliases` but not in fundamentals).

### 6.2 Counts per index and date

`membership.parquet`: S&P 500 snapshots have 498-507 rows (mean 503.1, 335 snapshots, one per change date); S&P 400 376-401 (mean 399.7; **2013-09-30 has 376, 2021-03-31 has 396**); S&P 600 596-626 (from 2018-06). After requiring a usable price the tradable universe is smaller:

| date | S&P 500 members | S&P 500 priced | S&P 500 % priced | S&P 400 members | S&P 400 priced | S&P 400 % priced |
|---|---|---|---|---|---|---|
| 2012-12-31 | 500 | 365 | 73.00 | 399 | 228 | 57.10 |
| 2013-12-31 | 500 | 373 | 74.60 | 400 | 240 | 60.00 |
| 2014-12-31 | 500 | 378 | 75.60 | 400 | 239 | 59.80 |
| 2015-12-31 | 500 | 393 | 78.60 | 400 | 253 | 63.20 |
| 2016-12-30 | 500 | 415 | 83.00 | 400 | 254 | 63.50 |
| 2017-12-29 | 499 | 430 | 86.20 | 400 | 289 | 72.20 |
| 2018-12-31 | 500 | 441 | 88.20 | 401 | 307 | 76.60 |
| 2019-12-31 | 500 | 450 | 90.00 | 400 | 327 | 81.80 |
| 2020-12-31 | 500 | 458 | 91.60 | 400 | 333 | 83.20 |
| 2021-12-31 | 500 | 466 | 93.20 | 400 | 343 | 85.80 |
| 2022-12-30 | 500 | 475 | 95.00 | 400 | 351 | 87.80 |
| 2023-12-29 | 500 | 481 | 96.20 | 400 | 361 | 90.20 |
| 2024-12-31 | 500 | 487 | 97.40 | 400 | 376 | 94.00 |
| 2025-12-31 | 500 | 494 | 98.80 | 400 | 387 | 96.80 |
| 2026-09-30 | 500 | 499 | 99.80 | 400 | 400 | 100.00 |

### 6.3 GICS

93 targeted (ticker, date) probes of well-known reclassifications (8 could not be evaluated: delisted names without prices or my own wrong expectation, e.g. TMUS joined the index in 2019, SBAC in 2017): GOOGL, META, TWTR, EA, ATVI, TTWO, OMC, IPG, DISH, NWSA, DIS, CMCSA, CHTR, T, CTL, TRIP IT/CD/Telecom -> Communication Services on 2018-09-28 (all correct on both sides); V, MA, PYPL, FIS, FISV, GPN IT -> Financials on 2023-03 (all correct); AMT, PLD, SPG, PSA, EQIX Financials/IT -> Real Estate on 2016-09 (correct); sector for AAPL, MSFT, AMZN, TSLA, XOM, JPM, JNJ, KO, NEE, CAT, LIN, CME correct. Failures: **NFLX = Information Technology on 2015-06, 2017-06, 2018-06 (should be Consumer Discretionary)**; CCI 2016-06 shows Telecommunication Services (I believe Financials/REIT, not certain). Agreement of the current sector and sub-industry with live Wikipedia: 499/499 (not independent). No Communication Services label before 2018-09-28 and no Telecommunication Services label after (0 rows each). Look-ahead in labels: 505 rows before 2016-09-01 carry 'Real Estate' (S&P 500 REITs 2011-2016 and S&P 400 LHO 2015-16) because `gics_source = asof_next`; 28,082 S&P 500 rows (18%) use a later reference snapshot, mostly 2011-2016.

### 6.4 No future members

`universe.members(d)` only reads snapshots with `snapshot_date <= d` (code read and tested around 14 additions). Cross-checks: members before the company's first SEC filing: 1 row (ETN 2012-06-05, 17 days, new Eaton plc registrant). Members whose Yahoo series starts later than the snapshot (4,049 rows, 57 tickers): all are delisted names whose symbol was later re-used or whose history Yahoo no longer serves (EA, LEG, AVB, QRVO, WBS, WBD ...), and `ctx.universe` drops them because it requires a price on the day, so there is no leak, only survivorship. Mapping errors that attach another company's data to a member are listed in problem 5.

## 7. Check 6: risk-free rate

`cache/prices/rf.parquet` (FRED DTB3, ^IRX after 2026-10-15; 4,979 days, no NaN, `rf_daily = rf_annual / 252` to machine precision).

| year | mean rf_annual (%) | compounded rf_daily (%) | Ken French monthly RF, compounded (%) |
|---|---|---|---|
| 2011 | 0.052 | 0.053 | 0.040 |
| 2012 | 0.088 | 0.087 | 0.060 |
| 2013 | 0.057 | 0.057 | 0.000 |
| 2014 | 0.033 | 0.033 | 0.000 |
| 2015 | 0.052 | 0.052 | 0.010 |
| 2016 | 0.317 | 0.317 | 0.210 |
| 2017 | 0.935 | 0.935 | 0.793 |
| 2018 | 1.939 | 1.950 | 1.805 |
| 2019 | 2.059 | 2.080 | 2.141 |
| 2020 | 0.353 | 0.355 | 0.451 |
| 2021 | 0.045 | 0.045 | 0.010 |
| 2022 | 2.038 | 2.051 | 1.408 |
| 2023 | 5.073 | 5.161 | 4.938 |
| 2024 | 4.966 | 5.091 | 5.252 |
| 2025 | 4.063 | 4.113 | 4.251 |
| 2026 YTD | 3.697 | 2.426 | 2.405 |

Annual levels match the expected regime (0.05% 2011-15, 2.06% 2019, 5.07% 2023, 4.97% 2024, 4.06% 2025, 4.07% on 2026-10-16). Against Ken French's monthly RF (1-month bills, independent file in `cache/factors`) the mean absolute monthly difference is 1.4 bp and the maximum 9.7 bp (2022-07, 3m vs 1m bills in a rising-rate month). Small negative values (-0.05% in 2020, -0.02% in 2015) are genuine secondary-market bill yields. FRED itself timed out during the audit, so no direct DTB3 comparison. **PASS.**

## 8. Other observations (not scored)

* `quant/ARCHITECTURE.md` documents `market_cap(date, ciks) -> pd.Series`; the code takes a universe DataFrame and returns a DataFrame with `price`, `price_raw`, `mcap`.
* TC's `min_mcap = 3e8` and `price_raw >= 5` filters silently remove every company whose share count is mis-scaled low (COP was dropped for 91 months before the patch).
* `ctx.fundamentals` NaNs negative `total_debt` (patch); 241 such rows were reported by the earlier spec audit, not re-verified here.
* The SEC `EntityPublicFloat` and `WeightedAverageNumberOfDilutedSharesOutstanding` facts carry 1000x scale errors for several large filers (EBAY, PKG, COP FY2021 diluted = 1,328,151 vs 1.328B): any future use of those tags needs the PIT-reference guard that `shares_on` now has.
* Reproduction: every number above comes from scripts in the scratch directory (check1.py, check2.py, check3a/3b.py, mcap_series.py, mcap_an2.py, float_check.py, check4a-d.py, check5a-c.py, surv.py, namecheck.py, ebit_proxy.py, complete.py, sanity.py); raw outputs are the CSV/JSON files next to them.