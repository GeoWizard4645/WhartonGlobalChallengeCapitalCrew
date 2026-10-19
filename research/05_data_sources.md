# 05 - Free data sources: tested findings, pipeline design, gotchas

Written Sun 2026-10-18 for trades on Wed 2026-10-21. Everything below was run, not assumed. Environment: Python 3.14.6, pandas 3.0.6, yfinance 1.7.0. About 300 SEC requests at 6 to 7 per second with `User-Agent: CapitalCrew Student Research Project research@capitalcrew-project.org`. Test sample: 18 hand-picked companies (AAPL, MSFT, JNJ, WMT, CAT, BOOT, JPM, XOM, TSM, NVDA, COST, KO, SHOP, ETSY, GOOGL, BRK-B, O, CRVL) plus a random draw of 50 S&P 500, 30 S&P 400, 40 S&P 600 names (about 135 usable US operating companies after dropping TSM, SHOP and the new XOM and VYLR CIKs). The bulk files `cache/sec/companyfacts.zip` and `submissions.zip` were not touched.

---

## 0. Decisions in one table

| Topic | Decision | Key evidence |
|---|---|---|
| Fundamentals source | SEC XBRL `companyfacts` (bulk zip for the backtest, per-company API for refreshing a few names) | Revenue, net income, CFO, assets, equity available for 95-100% of sampled non-financials at every test date 2012-2026 (section 2.7) |
| Point-in-time rule | Availability = `filed` date; a signal on date T may use facts with `filed < T`. Use the FIRST filed value of every period for backtests | Later vintages differ by more than 5% for TTM revenue in 5.3% of company-quarters (section 2.8) |
| Quarterly / TTM | Discrete quarters from reported 3M facts, else YTD differences; Q4 = FY minus 9M; TTM = 4 consecutive quarters | Derived Q2/Q3 equal the reported discrete quarter within 0.5% in 98% of cases (section 2.6) |
| Universe | PIT S&P 500 from `fja05680/sp500` (covers to 2026-08-18) patched with today's Wikipedia list; S&P 400/600 only as today's lists | 12 index changes since the last fja snapshot (section 4.2) |
| Prices | `yfinance`, `auto_adjust=False`; store Close, Adj Close, Volume, Dividends, Splits; compute returns from Adj Close, market caps from Close | Adj Close equals self-computed dividend-reinvested return (section 5) |
| Survivorship | yfinance has **zero** price history for delisted names: 0 of 179 dead ex-S&P 500 names. Benchmark every strategy against the equal-weight return of the SAME available universe and report the measured gap to RSP | Available-universe EW beats RSP by 1.13%/yr over 2010-2026 and 1.9%/yr over 2010-14 (section 4.4) |
| Market cap | `Close x Prod(Yahoo splits after T)` (unadjusted price) times as-reported shares times only the genuine splits between the filing date and T | Cuts spurious overnight share-count breaks from 47 (naive) to 24 (the rest are real mergers and spin-offs) (section 6) |
| Live signals | Use EDGAR (same code path as the backtest) plus the last close. Use Yahoo `.info` only as a cross-check and freshness flag | EDGAR TTM revenue and net income equal Yahoo to 0.0% in 9 of 12 period-matched names; Yahoo can be a few weeks fresher around earnings (JNJ), EDGAR can be a quarter behind when companyfacts omits a filing (KO) (section 7) |
| Risk-free and factors | FRED `DTB3` or `^IRX` for rates; Ken French daily 5 factors plus momentum (ends 2026-08-31) | Section 8 |

---

## 1. Rate and identity rules used

- Every SEC call sent the required header; throttled to at most about 7 requests per second (sleep 0.15 s between calls). No personal email anywhere.
- Wikipedia calls used the same project User-Agent.
- Helper (tested):

```python
import requests, time, json
UA = "CapitalCrew Student Research Project research@capitalcrew-project.org"
_last = [0.0]
def sec_get(url, min_interval=0.15):
    wait = min_interval - (time.time() - _last[0])
    if wait > 0: time.sleep(wait)
    r = requests.get(url, headers={"User-Agent": UA, "Accept-Encoding": "gzip, deflate"}, timeout=60)
    _last[0] = time.time(); r.raise_for_status()
    return r.json()
```

---

## 2. SEC XBRL `companyfacts`

### 2.1 Structure (verified on AAPL, 18 companies)

`https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` returns `{cik, entityName, facts: {taxonomy: {tag: {label, description, units: {unit: [obs, ...]}}}}}`. An observation is `{start?, end, val, accn, fy, fp, form, filed, frame?}`. `start` is absent for instant (balance sheet and cover-page) facts. Taxonomies seen: `us-gaap` (300 to 900 tags per company), `dei` (cover page), `ifrs-full` (TSM), `srt`, `ecd`, `ffd`, `invest`. File sizes: 0.9 to 8 MB typical (mean 3.9 MB over 120 downloads), 0.3 to 0.5 s per call.

Facts that matter, with evidence:

1. **`fy` and `fp` describe the filing, not the fact's period.** AAPL's Q3 FY25 revenue ($94.036B, 2025-03-30 to 2025-06-28) appears once with `fy=2025, fp=Q3` (accn 0000320193-25-000073, filed 2025-08-01) and again as a comparative with `fy=2026, fp=Q3` (accn 0000320193-26-000020, filed 2026-07-31). Never group on fy/fp. Group on `(start, end)`.
2. **The same period is repeated in every later filing that shows it** (AAPL FY2023 revenue appears in the 2023, 2024 and 2025 10-Ks). `frame` is set on only one filing per period (the newest), so frames are not usable for point-in-time work. The `frames` API (`/api/xbrl/frames/us-gaap/Revenues/USD/CY2023.json`, 2,679 companies in 0.2 s) is a handy cross-section but is latest-vintage only.
3. **Forms are not only periodic filings.** In the 18-company sample: 10-Q 259,697 rows, 10-K 143,944, 8-K 10,550, 20-F 5,834, 424B2 4,042, 40-F 2,677, 10-Q/A 2,045, 10-K/A 1,108, 6-K 501, DEF 14A 340. Filter to `{10-K, 10-K/A, 10-KT, 10-Q, 10-Q/A, 10-QT, 20-F, 40-F, and /A variants}`.
4. **Duration classes** (day count of `end - start + 1`): discrete quarter 80 to 100 (89k obs), 6M YTD 160 to 190, 9M YTD 250 to 280, FY 360 to 379 (also 52/53-week years at 364 and 371). Use windows 77-105, 160-200, 250-290, 340-380.
5. **Cash flow facts are YTD only.** 73% of CFO quarters had to be derived (income statement items: 13%).
6. **Non-dimensional facts only.** Dimension-qualified values are dropped. Consequences: (a) multi-class companies lack the cover-page share count; (b) companies whose 10-Q balance sheet is split by segment have no interim debt (CAT).
7. **Early XBRL ramps by filer size**: large accelerated from periods after mid-2009, other large 2010, everyone else after 2011-06-15. First-filed dates in the sample: AAPL 2009-10, CCK 2010-08, CRVL 2011-08. Plan the backtest to start in 2012 for a broad universe.
8. **Fetched latest filing in sample data: 2026-10-08.** Costco's 10-K for FY ending 2026-08-30 (filed 2026-10-07) is already in.

### 2.2 Tag priority lists (first = preferred)

"Cov" = share of sampled companies with a fresh value (period end within 230 days) at 2026-10-18: non-financials n=116 / financials n=19. Tags marked * are what the sample actually used for the latest period.

| Item | Tags in fallback order | Cov non-fin / fin | Notes |
|---|---|---|---|
| Revenue | `Revenues`*, `RevenueFromContractWithCustomerExcludingAssessedTax`*, `RevenueFromContractWithCustomerIncludingAssessedTax`*, `SalesRevenueNet`, `SalesRevenueGoodsNet`, `SalesRevenueServicesNet`, `RegulatedAndUnregulatedOperatingRevenue`* (utilities), `RevenuesNetOfInterestExpense`* (banks) | 100% / 84% | Take the LARGEST of {Revenues, ...ExcludingAssessedTax, SalesRevenueNet} within the earliest filing. Priority alone picked the wrong tag in 17 of 1,709 annual periods (ETN `Revenues`=0 next to `SalesRevenueNet`=$22.0B; PG $29.4B vs $83.1B; CCK $261M vs $8.7B) |
| COGS | `CostOfRevenue`*, `CostOfGoodsAndServicesSold`*, `CostOfGoodsSold`, `CostOfServices`, `CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization`* | 73% / 5% | Many service, software, biotech and bank filers never report it |
| Gross profit | `GrossProfit`; else Revenue - COGS | 73% / 5% | Gross-profitability screens must tolerate about 27% missing |
| Operating income (EBIT) | `OperatingIncomeLoss`*; else Pretax + interest expense | 98% / 100% | JNJ, OXY, XOM, ETN, CRVL, EHC, O do not tag OperatingIncomeLoss; fallback used for 9 of 116 |
| Net income | `NetIncomeLoss`*, `ProfitLoss`, `NetIncomeLossAvailableToCommonStockholdersBasic` | 100% / 100% | `NetIncomeLoss` = parent; `ProfitLoss` includes NCI |
| D&A | `DepreciationDepletionAndAmortization`*, `DepreciationAndAmortization`*, `DepreciationAmortizationAndAccretionNet`, `UtilitiesOperatingExpenseDepreciationAndAmortization`, `DepreciationAmortizationAndOther`, `Depreciation`*, `DepreciationNonproduction` | 99% / 68% | `Depreciation` alone omits amortization (understates EBITDA); keep last |
| Interest expense | `InterestExpense`*, `InterestExpenseNonoperating`*, `InterestExpenseDebt`*, `InterestAndDebtExpense`*, `InterestExpenseLongTermDebt`, `InterestExpenseOperating`*; fallback `-InterestIncomeExpenseNonoperatingNet` or `-InterestIncomeExpenseNet` (negative = net expense) | 91% / 84% | AAPL stopped tagging interest expense; the net-interest fallback recovers it |
| Income tax | `IncomeTaxExpenseBenefit` | 99% / 100% | |
| Pretax income | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest`*, `...MinorityInterestAndIncomeLossFromEquityMethodInvestments`* | 94% / 100% | |
| CFO | `NetCashProvidedByUsedInOperatingActivities`*, `...ContinuingOperations` | 100% / 100% | YTD only |
| Capex | `PaymentsToAcquirePropertyPlantAndEquipment`*, `PaymentsToAcquireProductiveAssets`*, `PaymentsForCapitalImprovements`, `PaymentsToAcquireOtherPropertyPlantAndEquipment`, `PaymentsToAcquireRealEstate`, `PaymentsToDevelopRealEstateAssets`* | 97% / 63% | REITs and utilities use real-estate or plant tags |
| Total assets | `Assets` | 100% / 100% | |
| Current assets / liabilities | `AssetsCurrent`, `LiabilitiesCurrent` | 94% / 11% | Unclassified balance sheets (banks, insurers, some REITs) lack both |
| Total liabilities | `Liabilities` | about 70% non-fin | Compute as Assets - Equity incl. NCI when missing |
| Cash | `CashAndCashEquivalentsAtCarryingValue`*, `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents`*, `CashAndDueFromBanks`, `Cash` | 99% / 100% | |
| Short-term investments | `ShortTermInvestments`*, `MarketableSecuritiesCurrent`*, `AvailableForSaleSecuritiesDebtSecuritiesCurrent`*, `DebtSecuritiesCurrent`*, `AvailableForSaleSecuritiesCurrent`, `OtherShortTermInvestments`*; combined alternative `CashCashEquivalentsAndShortTermInvestments`* | 32% / 26% | Optional (absent means 0). Tag drift: NVDA moved from MarketableSecuritiesCurrent (last used Oct 2025) to DebtSecuritiesCurrent |
| PP&E net | `PropertyPlantAndEquipmentNet`*, `PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization`* | 97% / 58% | |
| Equity (parent) | `StockholdersEquity`*; else `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` - `MinorityInterest` | 100% / 100% | |
| Preferred | `PreferredStockValue`*, `PreferredStockValueOutstanding`, `PreferredStockCarryingValue` | 41% / 53% | Carrying (par) value, not liquidation value. Absent means 0 |
| Noncontrolling interest | `MinorityInterest` | 38% / 47% | Absent means 0 |
| Shares | 1) `dei:EntityCommonStockSharesOutstanding` (cover page), 2) `CommonStockSharesOutstanding` (balance sheet), 3) `WeightedAverageNumberOfDilutedSharesOutstanding` (latest discrete quarter) | 98% / 95% | Section 2.5 |
| EPS diluted | `EarningsPerShareDiluted` (discrete 3M only; never difference it) | about 97% | Prefer NI / market cap based ratios; EPS is per as-reported shares and breaks on splits |

**Total debt (composite, tested).** Current part: `DebtCurrent`; if absent, `ShortTermBorrowings + CommercialPaper + LongTermDebtCurrent` (or `LongTermDebtAndCapitalLeaseObligationsCurrent`). If both `DebtCurrent` and `LongTermDebtCurrent` exist and `DebtCurrent >= LongTermDebtCurrent`, the former already includes the latter. Non-current part, first hit wins: `LongTermDebtNoncurrent`* (69 of 116), `LongTermDebtAndCapitalLeaseObligations`* (20; already contains finance leases), `LongTermDebt - LongTermDebtCurrent` (5), sum of `SeniorNotes, SecuredDebt, UnsecuredDebt, ConvertibleNotesPayable, ConvertibleLongTermNotesPayable, ConvertibleDebtNoncurrent, LongTermNotesPayable, LongTermLineOfCredit, LineOfCredit, OtherLongTermDebtNoncurrent` (9), `DebtAndCapitalLeaseObligations` (3). Add `FinanceLeaseLiability` (or current + noncurrent) unless the non-current tag already includes leases. **Freshness guard:** a component only counts if its period end is within 120 days of the latest `Assets` date; otherwise BOOT would carry 2016 debt and CAT carry 2025-12 debt forever. Result: 88% of non-financials get a debt figure; 14 of 116 have no debt tags at all (mostly truly debt-free: MPWR, POWI, PEGA, MEDP, CRVL, RHI). Operating lease liabilities are NOT included (Yahoo includes them, which is why Yahoo `totalDebt` is higher for WMT, MSFT, COST: section 7).

**Derived definitions.** EBITDA = EBIT + D&A. FCF = CFO - capex. EV = market cap + total debt + preferred + NCI - cash - short-term investments. Magic Formula ROC denominator: (current assets - cash) - (current liabilities - short-term debt) + net PP&E.

### 2.3 Point-in-time algorithm (pseudo-code; tested code in Appendix A)

```
INPUT  facts: rows(tag, unit, start, end, val, accn, form, filed) for periodic forms only
FOR each concept (revenue, net_income, cfo, ...), FLOW or INSTANT:

 1. CANDIDATES: rows whose tag is in the concept's priority list and unit == USD (shares / USD-per-share where relevant)

 2. ONE ROW PER PERIOD (mode = FIRST):
      key = (start, end) for flows, (end) for instants
      keep only the EARLIEST-filed filing that reports the key (ties on date: smaller accn)
      inside that filing choose the tag: largest value if tag in the revenue max-group, else best list priority
    (mode = LATEST, for live use: for each (tag,start,end) keep the newest vintage with filed <= today, then same tag choice)

 3. FLOW ONLY - classify days = end-start+1:
      cls1 77-105 discrete quarter   cls2 160-200 H1   cls3 250-290 9M   cls4 340-380 FY
    collapse start-date jitter: rows with the same (end, cls) -> keep earliest filed
      (CCK reports the same Q2 with start 2012-03-31 in one filing and 2012-04-01 in another)
    cluster fiscal-year start dates within 6 days so Q1/H1/9M/FY chain together
    candidates for each quarter end:
      reported: cls1 row, availability = its filed
      derived Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M     availability = max(filed of the two rows)
      derived Q4 = FY - (Q1+Q2+Q3 discrete) if no 9M row
    pick per quarter end: FIRST mode -> earliest availability (tie: reported); LATEST mode -> reported else derived
      (Q4 is only reported discretely in the NEXT year's 10-K; FY-minus-9M is known at the 10-K date. Taking
       "reported first" delayed Q4 by a year and cut revenue coverage to 77% (2012) and 90% (2018);
       fixed: 95% and 100%)

 4. TTM at quarter end E = sum of the 4 consecutive quarters ending E
      require gaps between quarter ends 70-125 days (Costco Q4 is 16 weeks) and span 350-380 days
      availability(E) = max(filed of the 4 quarters)
    ANNUAL-ONLY FALLBACK: FY rows (20-F/40-F filers, early XBRL) enter the same table with basis='fy'

 5. NON-ADDITIVE items (EPS, weighted shares): take the reported discrete 3M value; never difference YTD

 6. INSTANTS: one value per balance-sheet date; availability = its filed

 7. MONOTONE FILTER: sort by filed; keep a row only if its period end > every earlier-filed end
      -> "latest row with filed < T" == "latest period known at T"

QUERY value(concept, T):   row = last row with filed < T          (strict: nothing filed on T or later)
      stale -> NaN if T - end > 230 days (flows, balance sheet) or 400 days (cover-page shares)
```

Verified output, AAPL TTM revenue, first-filed: as of 2025-07-31 $400.366B (period end 2025-03-29), as of 2025-08-04 $408.625B (10-Q filed 2025-08-01 now visible), 2025-10-30 $408.625B, 2025-11-03 **$416.161B** (10-K filed 2025-10-31), 2026-02-02 $435.617B. Derived Q4 FY25 revenue $102.466B (FY minus 9M) matches Apple's reported $102.5B. Costco FY26 TTM revenue $303.154B equals Yahoo's `totalRevenue` to the dollar.

### 2.4 How to get "first-filed" and "as-of" vintages

- **First-filed (backtests):** `build_company(facts, mode="first")` reads the earliest filing for every period, so restatements and recasts never leak backwards. Use `filed < T` (strict, one-day safety lag). `submissions` JSON also carries `acceptanceDateTime`; filings accepted after 17:30 ET are dated the next business day, so strict `<` is conservative enough.
- **As-of vintage (live signals / sensitivity):** `build_company(facts, mode="latest", asof=T)` keeps the newest vintage filed on or before T. For a monthly backtest this means rebuilding per date; use first-filed unless you specifically study restatement impact.
- Amendments: `10-K/A` and `10-Q/A` are INCLUDED in "first" (1,554 sample periods were first reported inside an amendment, e.g. BWXT's 2026-06-30 10-Q/A). Where an amendment disagrees with the original (715 of 5,011 comparable periods, 14%, differ by more than 0.5%), first-filed ignores the correction. That is the safe, no-look-ahead choice but it carries the original error.

### 2.5 Share counts (tested)

| Source | Result |
|---|---|
| `dei:EntityCommonStockSharesOutstanding` (cover page; freshest) | Present for 104 of 116 non-financial sample names. Missing for multi-class issuers because the per-class facts are dimensional: GOOGL, BRK-B, CMCSA, UPS, NYT, PTON, SAH, DDOG, KNTK, WSO, PLNT, JBSS, YOU |
| `CommonStockSharesOutstanding` (balance sheet) | Present for about 65%; median difference to the cover count 0.00% (p10 -0.22%, p90 +0.09%) |
| `WeightedAverageNumberOfDilutedSharesOutstanding` | Present for 103 of 104; the cover count is a median 0.76% BELOW it (p10 -3.3%, p90 +0.2%); used as the third fallback (9 names) |
| Cover date vs balance sheet date | Cover count is a median 27 days newer |

Fallback chain actually used for the 116 non-financials: cover 104, weighted-diluted 9, balance-sheet 1, none 2. For multi-class names use total as-converted shares times the price of the traded class; Yahoo `.info.impliedSharesOutstanding` is a good live cross-check (GOOGL: `sharesOutstanding` 5.87B is Class A only; `impliedSharesOutstanding` 12.23B is total and reproduces `marketCap`). De-duplicate dual-class tickers by CIK (GOOGL/GOOG, FOXA/FOX, NWSA/NWS).

**Scale errors in cover counts.** 6 values in 4 of 123 companies were off by 1,000x to 1e6x (PKG 89,932,185,000 vs 89,915,081 neighbours, three times; ORCL 4.8e15; ETN 100; LMAT 1,991,347). Left in, they make market caps absurd. Filter: drop a count that is more than 8x away from the rolling median of its 5 neighbours (`clean_counts` in the appendix).

### 2.6 Validation of the derivation

- YTD difference equals the reported discrete quarter, same filing, within 0.5%: revenue Q2 98.1% (n=1,721), Q3 97.9% (n=1,639); net income Q2 98.6% (n=1,809), Q3 98.9% (n=1,720). The rest are Q1 numbers that were restated inside the Q2 10-Q.
- Q4 derived at the 10-K versus the Q4 that the next year's 10-K reports discretely: within 0.5% for 71% (n=69). The gap is later restatement, not arithmetic.
- Source mix, revenue: 87% reported, 13% derived. CFO: 27% reported, 73% derived.
- Availability lag (quarter end to first filing), 2013+: median 36 days; 10-Q quarters median 35 (p90 54); 10-K quarters median 54 (p90 60); long tail to 789 days only for early-XBRL backfills.

### 2.7 Coverage at historical as-of dates (non-financials with at least 1 year of XBRL history; first-filed)

| Item | 2012-12 | 2015-12 | 2018-12 | 2021-12 | 2024-12 | 2026-10 |
|---|---|---|---|---|---|---|
| n companies | 83 | 91 | 100 | 109 | 115 | 116 |
| Revenue | 95% | 95% | 95% | 100% | 100% | 100% |
| EBIT (with fallback) | 96% | 99% | 98% | 96% | 98% | 98% |
| D&A | 96% | 97% | 96% | 97% | 98% | 99% |
| Net income | 99% | 99% | 99% | 100% | 100% | 100% |
| CFO | 99% | 99% | 99% | 100% | 100% | 100% |
| Capex | 95% | 97% | 96% | 96% | 97% | 97% |
| Total assets / equity | 99-100% | 100% | 100% | 100% | 100% | 100% |
| Cash | 96% | 97% | 99% | 100% | 100% | 99% |
| Total debt (composite) | 80% | 88% | 88% | 88% | 86% | 88% |
| Shares | 100% | 100% | 99% | 99% | 97% | 98% |
| Gross profit | 75% | 76% | 73% | 73% | 72% | 73% |

### 2.8 Restatements are material (same-tag comparison, first-filed vs latest vintage, 2012+)

| TTM item | Differs >0.5% | >5% | >20% | Companies hit (>5%) |
|---|---|---|---|---|
| Revenue | 9.5% | 5.3% | 2.2% | 33 of 133 |
| Operating income | 14.5% | 7.4% | 4.0% | 45 of 116 |
| Net income | 7.3% | 3.6% | 1.8% | 44 of 135 |
| CFO | 7.9% | 3.2% | 1.5% | 35 of 135 |

Largest cases are divestitures and discontinued operations (ROIV, GEN). Backtesting on today's restated numbers would hide the divested, loss-making pieces that investors actually saw.

An earlier version of this comparison showed far bigger gaps (ETN $13.7B vs $1.35B); that was a tag-selection artefact, not a restatement, and is why the largest-of-group revenue rule exists.

### 2.9 Foreign filers (20-F / 40-F)

- **TSM** (20-F only): taxonomy `ifrs-full`, units TWD plus a USD convenience translation, **annual data only**, tags `Revenue, CostOfSales, GrossProfit, ProfitLossFromOperatingActivities, ProfitLoss, FinanceCosts, IncomeTaxExpenseContinuingOperations, ProfitLossBeforeTax, CashFlowsFromUsedInOperatingActivities, PurchaseOfPropertyPlantAndEquipmentClassifiedAsInvestingActivities, Assets, Equity, CashAndCashEquivalents`; no D&A tag of the usual name; `dei` exposes only the cover share count. No quarterly facts exist because quarterly results go in 6-K without full XBRL. The facts also lag: filings run to 2026-04-16 but the newest period tagged is 2024-12-31, so a 20-F filer's TTM is stale by more than a year.
- **SHOP**: 40-F/20-F annual until FY2021, then 10-K/10-Q with `us-gaap`. The annual-only fallback (`basis='fy'`) yields TTM from FY rows for those years; a 230-day staleness limit turns it NaN between filings, so raise the limit to about 400 days for `basis='fy'` rows.
- Recommendation: leave 20-F/40-F names and anything reporting in non-USD currency out of the quant universe; log them (all 135 sampled 10-K filers reported in USD).

### 2.10 SEC data-quality traps found

1. **companyfacts silently omitted recent filings.** 12 of 1,486 XBRL periodic filings listed in `submissions` since 2024 (0.8%) were missing from `companyfacts` even on a fresh pull: all Q2-2026 10-Qs filed 2026-07-28 to 2026-08-26 (CB, ESI, EXLS, MDLZ, PNR, KO, MAS, PSN, VLTO, DLR, MGEE, SMTC). That leaves 8.9% of sampled companies one quarter stale today. The bulk zip is built from the same data and probably has the same hole. **Add a reconciliation job:** for every CIK compare the newest `reportDate` of a periodic filing with `isXBRL=1` in `submissions` with the newest period in the facts; flag and exclude (or patch from Yahoo quarterly statements) the mismatches.
2. **Successor CIKs after holding-company reorganisations.** `company_tickers.json` maps `XOM` to CIK 2115436 (ExxonMobil Holdings Corp): 94 tags, 2 quarters of history. The 15 years of history sit on CIK 34088 (now `tickers: []`). `VYLR` (CIK 2128626) has zero facts yet. Rule: a name that has been in the S&P index for more than two years but has fewer than 8 quarters of facts needs a manual predecessor CIK in a `cik_aliases.csv`; concatenate facts across the chain.
3. **Segment-presented balance sheets** (CAT, similar: DE, GE, F, GM) have no non-dimensional interim debt; only the 10-K values exist.
4. **Tag drift** (ASC 606 revenue tags in 2018, DebtSecuritiesCurrent, AAPL dropping InterestExpense): every concept needs a freshness test and a monitor listing companies whose newest value is older than 120 days.
5. **Start-date jitter** (same fiscal period with `start` differing by 1 to 2 days across filings) overwrote earlier availability dates until fixed; see algorithm step 3.
6. **pandas 3 datetime units.** `merge_asof` raises `incompatible merge keys [0] dtype('<M8[s]') and dtype('<M8[us]')` when joining yfinance (seconds) with SEC (microseconds). Cast both to `datetime64[ns]` first.

---

## 3. Ticker, CIK and SIC mapping

- `https://www.sec.gov/files/company_tickers.json` (dict of `{cik_str, ticker, title}`) and `company_tickers_exchange.json` (`fields: [cik, name, ticker, exchange]`) are the same 10,443 rows; 8,029 unique CIKs; 1,444 CIKs carry several tickers (share classes `BRK-B`, preferreds `ASB-PE`, `WRB-PF`). Exchange split: Nasdaq 4,372, NYSE 3,273, OTC 2,572, CBOE 44, TXSE 10, blank 172. The files list CURRENT tickers only; SEC uses `-` for classes (`BRK-B`), Yahoo uses the same, Wikipedia and fja05680 use `.`: convert `.` to `-`.
- Of 1,506 current S&P 500/400/600 rows, 1,502 map to a CIK (unmapped: CWEN-A, HLX, LEG, QRVO, all caused by recent corporate events).
- EDGAR cannot resolve historical or renamed tickers: `cgi-bin/browse-edgar?CIK=FB` and 9 other delisted/renamed tickers (TWX, BRCM, CELG, ETFC, JCP, RAI, ANTM, KRFT, CVH) all failed. Keep your own `ticker_aliases.csv` (old ticker, new ticker, CIK, valid-from, valid-to).
- **SIC** comes from `https://data.sec.gov/submissions/CIK##########.json` (`sic`, `sicDescription`, `category`, `fiscalYearEnd`, `stateOfIncorporation`, `tickers`, `exchanges`, `formerNames`, `filings.recent` with `acceptanceDateTime`, `reportDate`, `isXBRL`). It is the CURRENT SIC only (no history). Fetch time about 0.4 s each; `filings.files` lists older pages.
  - Exclusion rule check on 136 names: SIC 6000-6799 captured 18 of 19 GICS Financials (miss: SEZL, SIC 7389) and all 8 GICS Real Estate; SIC 4900-4999 captured all 4 GICS Utilities. Exceptions: KNTK (SIC 4922 pipeline, GICS Energy), CRVL (SIC 6411 insurance services, GICS Health Care), VAC (SIC 6531, GICS Consumer Discretionary). REITs are 6798.
  - Recommended rule: for today's index members use GICS from Wikipedia (current); for historical dates use SIC 6000-6799 and 4900-4999 as the financials and utilities proxy (SIC changes rarely) and keep a small override list.
- There is **no free point-in-time GICS**. Using today's GICS sub-industry for 2012 peer groups is look-ahead (reclassifications in 2016, 2018, 2023). For the trading-comps strategy consider SIC-4 peer groups as the PIT-safe alternative and report both.

---

## 4. Universe and survivorship

### 4.1 Current index lists (Wikipedia, fetched with the project User-Agent)

| Page | Table | Rows | Columns | Notes |
|---|---|---|---|---|
| List of S&P 500 companies | `id="constituents"` | 503 | Symbol, Security, GICS Sector, GICS Sub-Industry, Headquarters Location, Date added, CIK, Founded | latest `Date added` 2026-10-06; 11 sectors; GOOGL/GOOG, FOXA/FOX, NWSA/NWS are separate rows with the same CIK. The "Selected changes" table is **not on the page any more** (only 2 tables parsed) |
| List of S&P 400 companies | table 0 | 400 | Symbol, Security, GICS Sector, GICS Sub-Industry, Headquarters Location, SEC filings | **no CIK column**; changes table (623 rows back to 2012-01-13) is table 1 |
| List of S&P 600 companies | table 0 | 603 | same + CIK | changes table (491 rows back to 2019-12-17) is table 1 |

1,506 rows, 1,503 unique tickers (3 appear in two indices). Locate tables by `id` or by columns, not position; `pd.read_html(io.StringIO(html))` works with lxml. Convert `.` to `-` for Yahoo.

### 4.2 Historical S&P 500 membership: `fja05680/sp500`

- Raw URL (tested, 5.5 MB): `https://raw.githubusercontent.com/fja05680/sp500/master/S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv`. Columns `date, tickers` (comma list). 2,720 snapshots, **1996-01-02 to 2026-08-18**, 487 to 507 tickers per snapshot (mean 497; share-class lines count separately). Snapshots exist only on change dates: look up with "last snapshot on or before T".
- Also: `sp500_ticker_start_end.csv` (1,262 ticker spells with start/end dates), `sp500_changes_since_2019.csv` (125 rows, last 2026-08-18), the original 1996-2019 file with `-YYYYMM` suffixes on reused tickers (7.8 MB).
- Spot checks pass: TSLA start 2020-12-21, FB 2013-12-23 to 2022-06-09 then META from 2022-06-09, ABMD end 2022-12-22.
- **Staleness:** against today's Wikipedia list the last fja snapshot is missing 6 additions (BE, ILMN, P, SKYD, TWLO, VYLR) and 6 removals (BLDR, CTVA, PSKY, TAP, TTD, WBD). Patch by treating the Wikipedia list as the authoritative snapshot for 2026-10-18.
- Quirks: tickers are the symbols as of each date (FB, ANTM, UTX); defunct names carry post-bankruptcy Q symbols (LEHMQ, WAMUQ, EKDKQ, RSHCQ); some 2008 names are absent (LEH, FNM, FRE). A same-day "remove X, add Y" pair is only a hint of a rename (551 such pairs since 2010; true renames among them: ANTM to ELV, FB to META, WLTW to WTW, BLL to BALL, ARNC to HWM, BHGE to BKR, DISCA to WBD, TMK to GL; false ones: FBHS to FSLR, GPS to CEG).

### 4.3 Broader universe lists

- **NASDAQ Trader** `https://www.nasdaqtrader.com/dynamic/SymDir/nasdaqlisted.txt` and `otherlisted.txt` (pipe-delimited, 349,723 and 543,140 bytes, stamped 2026-10-16 21:31): 13,308 rows (Nasdaq 5,634; NYSE 2,905; NYSE Arca 2,750; Cboe BZX 1,680; NYSE American 314). Flags: `ETF` (5,789 = Y), `Test Issue` (37 = Y), Nasdaq `Financial Status` (D deficient 310, E 21, H 6). After keeping Nasdaq/NYSE/NYSE American, ETF=N, Test=N, status N, and dropping names with whole-word warrants, rights, units, preferred, notes, funds: **4,819** listings; S&P 1500 coverage 98.9%; 99.6% have a SEC CIK. Name-based filtering is brittle (a first attempt that required "common stock" in the name and matched `unit` as a substring dropped AT&T, UnitedHealth, UPS, Altria, GE: 5% of the S&P 1500). Better: define the universe by (listed on an exchange) AND (has 10-K XBRL facts) AND (price/market-cap thresholds).
- **Russell 1000/3000**: the iShares IWB/IWV holdings URL returned an HTML page, not CSV, so it is not scriptable here; there is no free point-in-time Russell membership. Do not plan on Russell. S&P 1500 (current) plus S&P 500 history is the realistic scope.

### 4.4 Survivorship test: how many removed S&P 500 names can yfinance price?

Population: tickers whose last S&P 500 membership ended 2010-01-01 to 2022-12-31 (not currently in the index): **271** (acquired, bankrupt, merged, or simply shrunk).

| Outcome | Count | Share |
|---|---|---|
| Valid price history covering at least 95% of the membership window | 66 | 24% |
| Yahoo returns data but it is another company (ticker reuse, e.g. FB, S, SE, STI, APC, ADT, BBBY, LEG) or only partial | 27 | 10% |
| No data at all ("possibly delisted; no timezone found") | 178 | 66% |

**None of the 179 tickers that no longer trade has usable history** (the single hit, LEG, is a reused symbol). Every one of the 66 valid series belongs to a company that left the index but is still listed. By removal year, names with any data: 2010 4 of 16, 2013 4 of 14, 2016 12 of 26, 2019 13 of 28, 2022 7 of 24.

Danger: a ticker-only join silently attaches another company's prices (27 cases). Require the price series to overlap the membership window (overlap of at least 95%) before accepting it.

Roughly 15 to 25 of the 178 missing names are renames of survivors whose history exists under the new ticker (ANTM to ELV, UTX to RTX, DISCA/DISCK/VIAB/CBS to WBD/PARA, WLTW to WTW, BLL to BALL, ARNC to HWM, BHGE to BKR, HCP to DOC, TMK to GL, FBHS to FBIN, HFC to DINO, CTL to LUMN, MYL to VTRS; my manual estimate). An alias table recovers these.

**Bias measurement.** Monthly equal-weight return of the PIT S&P 500 members that have yfinance prices (852 tickers ever in the index since 2009-12, 649 priced) versus RSP, 2010-01 to 2026-09:

| Year | Priced share of PIT members | Year | Priced share |
|---|---|---|---|
| 2010 | 66% | 2019 | 84% |
| 2012 | 68% | 2020 | 87% |
| 2014 | 72% | 2022 | 92% |
| 2016 | 76% | 2024 | 96% |
| 2018 | 81% | 2026 | 99% |

| Period (monthly returns, through 2026-09) | Available-universe EW (CAGR) | RSP (CAGR) | Gap |
|---|---|---|---|
| 2010 to 2026 | 13.79% | 12.66% | **+1.13 pp/yr** |
| 2010 to 2014 | 19.91% | 18.02% | +1.89 pp |
| 2015 to 2019 | 11.00% | 9.43% | +1.57 pp |
| 2020 to 2026 | 11.59% | 11.30% | +0.29 pp |

Monthly correlation 0.998. RSP's roughly 0.20% fee and its quarterly (not monthly) rebalancing explain a little of the gap; the rest is survivorship. It is the bias for a plain equal-weight S&P 500; deep-value or low-quality tilts (Magic Formula) probably suffer more because distressed names are the ones missing.

**Mitigation plan**
1. Report every strategy against two benchmarks: (a) equal-weight of the SAME available universe (apples to apples), (b) RSP. Quote excess return vs (a) as the headline.
2. Show the strategy's excess return after subtracting the measured year-by-year gap (EW-available minus RSP) as a conservative haircut: about 1.9 pp/yr before 2015, about 1.6 pp for 2015-19, about 0.3 pp since 2020.
3. Start the primary evaluation window at 2015 (coverage at least 73%) or 2018 (at least 81%) and show 2012-2014 as a flagged robustness period.
4. Keep rename aliases (about 20) and accept only price series that overlap the membership window.
5. Optional repair, not tested because each needs an account or a download I did not make: Tiingo (free tier 500 symbols per month, includes delisted tickers: 178 dead names fit in one month; returns `403 Please supply a token` without a key), Alpha Vantage (25 calls per day), EODHD (401 without key), Financial Modeling Prep (401), the Quandl/Nasdaq Data Link WIKI archive (frozen 2018-03; endpoint behind a bot wall). The team would register their own free keys, keep them in environment variables, and never commit them.
6. **Stooq** (`stooq.com/q/d/l/?s=twx.us&i=d`) now returns a JavaScript bot-verification page for every symbol including live ones; not scriptable, and I did not attempt to bypass it.

---

## 5. Prices with yfinance

Tested recipe:

```python
import yfinance as yf
d = yf.download(tickers, start="2009-01-01", auto_adjust=False, actions=True,
                threads=True, progress=False, group_by="ticker")   # chunks of 250
# columns per ticker: Open High Low Close "Adj Close" Volume Dividends "Stock Splits"; index tz-naive
```

- Speed: 100 tickers, full history, 4.6 s. 857 tickers in four chunks 30 s. 271 mostly-dead tickers 8.4 s. `.info` for 136 tickers 25 s (0.18 s each). Quarterly statements: 12 tickers x 4 statements 9.1 s.
- Pass `auto_adjust` explicitly; yfinance 1.x defaults to True. Convert `BRK.B` to `BRK-B`. Dead tickers print "possibly delisted; no timezone found" and come back all-NaN: drop columns that are all NaN.
- `Close` (auto_adjust=False) is **split-adjusted only**: AAPL 2020-08-28 Close $124.81 (= $499.23 / 4), Adj Close $120.96. `Adj Close` is split plus dividend adjusted; `auto_adjust=True` Close equals Adj Close. NVDA 2024-06-07 Close $120.89, Adj Close $120.54; 10-for-1 split recorded as `Stock Splits = 10.0` on 2024-06-10 (reverse splits appear as fractions).
- **Total return check:** reinvesting `Dividends` on the ex-date close reproduces `Adj Close` growth: 2010-01-04 to 2026-10-16 CAGR SPY 14.03%/14.03%, KO 10.68%/10.68%, JNJ 11.72%/11.72%, AAPL 26.79%/26.79%, WMT 14.16%/14.16%, CAT 19.07%/19.07%, XOM 9.84%/9.83%, NVDA 44.93%/44.93% (own TR / Adj Close). Price-only would understate SPY by 2.0 pp/yr.
- **Recommendation:** store Close, Dividends, Splits and Volume, and compute returns yourself (append-safe). Yahoo recomputes `Adj Close` relative to the latest bar, so every new dividend rescales the whole past and a cached Adj Close history must never be appended to (documented Yahoo behaviour; two downloads taken today with different end dates matched exactly, which shows the adjustment is always relative to the present, so staleness cannot be reproduced in one session). Use Adj Close (or own TR) for returns, unadjusted prices for market caps.
- Data lag: last bar 2026-10-16 (Friday). For Wed 10-21 trades the last completed bar will be Tue 10-20; do not run during market hours or the last bar can be partial.
- Benchmarks (Adj Close, from 2010-01-04 to 2026-10-16, CAGR; first date): SPY 14.03% (1993-01-29), RSP 12.30% (2003-05-01), IWM 10.44% (2000-05-26), MDY 11.30% (1995-05-04), IJR 11.42% (2000-05-26). `^GSPC` is price-only (12.06%).

---

## 6. Market cap and splits (price x shares)

Problem: yfinance `Close` is adjusted for every later split but the SEC share count is as reported at the time. Naive `Close x shares` is wrong by exactly the split factor: NVDA on 2024-06-07 gives $297.4B instead of **$2,973.8B**; AAPL on 2020-08-28 gives $533.6B instead of **$2,134.5B**.

Method (tested over 123 companies, 403,074 company-days, 40 splits since 2012 in 31 companies):

```
unadj_T   = Close_T(auto_adjust=False) * Prod(all Yahoo split ratios with ex-date > T)     # undoes Yahoo's adjustments
shares_T  = latest cleaned cover-page count with filed < T
            * Prod( genuine split ratios with  filed < ex-date <= T )                      # split after the filing, before T
mcap_T    = unadj_T * shares_T
genuine   = ratio is a "nice" split (2,3,1.5,10,... or 1/2,1/10,...);  odd fractions (ASH 2.044, a spin-off adjustment)
            change prices but must not change share counts
```

Why `filed` and not the XBRL `end` date: for NFLX the Q2-2015 cover count (426.0M, filed 2015-07-17, XBRL end 2015-06-30) was already post-split (7-for-1 effective 2015-07-15). Cutting at the `end` date adjusts it again (x7 error). Splits that happened before the filing are already in the reported count (ASC 260 also restates share data for splits between period end and filing).

Result, count of overnight effective-share breaks larger than 30% (all remaining ones are genuine mergers, spin-offs or large issuance: ALB, CB, CBOE, IR, JBTM, MTB, O, WSFS, ASH):

| Method | Breaks |
|---|---|
| Naive: adjusted Close x as-reported shares | 47 |
| Factor on splits after the XBRL `end` date | 31 |
| Final: unadjusted price, filed-date rule, nice ratios only, scale-error filter | 24 |

Simpler alternative if you prefer: always use the unadjusted close and as-reported shares and only multiply by splits that occurred between the filing and T. It is the same thing written differently.

Also: EPS and other per-share data in first-filed vintages are pre-split; later vintages restate them. Prefer ratios built from totals (net income / market cap) and avoid mixing per-share data across vintages.

---

## 7. Live signals: Yahoo fundamentals vs EDGAR

`Ticker.info` (187 keys; 0.18 s per call): `marketCap`, `enterpriseValue`, `trailingPE`, `forwardPE`, `enterpriseToEbitda`, `enterpriseToRevenue`, `totalRevenue`, `ebitda`, `totalDebt`, `totalCash`, `netIncomeToCommon`, `sharesOutstanding`, `impliedSharesOutstanding`, `floatShares`, `sector`, `industry`, `mostRecentQuarter`, `lastFiscalYearEnd`, `currentPrice`.

- `sector`/`industry` are Yahoo/Morningstar, **not GICS**. Mapped to GICS names, sector agreement is 90.4% (123 of 136); mismatches include PAYX, UBER, G, EXLS, PSN ("Technology" vs GICS Industrials), CRVL ("Financial Services" vs Health Care), PKG, CCK, OI ("Consumer Cyclical" vs Materials), WDFC, ARMK, UPBD. Industry labels differ entirely (72 Yahoo industries vs 79 GICS sub-industries in the sample). Take GICS from Wikipedia.
- Statements: `quarterly_income_stmt` only 5 to 6 quarters, `quarterly_balance_sheet` 5 to 7, `quarterly_cashflow` 5 to 6, annual 4 to 5, plus `ttm_income_stmt`. Dates are shifted to calendar month-ends (AAPL 2026-06-27 shown as 2026-06-30). Not usable for backtests; only for live checks.
- **EDGAR vs Yahoo today, period-matched** (final code, `mode="latest"`):

| Name | EDGAR period end | Revenue diff | Net income diff | EBITDA diff | Comment |
|---|---|---|---|---|---|
| AAPL | 2026-06-27 | 0.0% | 0.0% | 0.0% | |
| MSFT | 2026-06-30 | 0.0% | 0.0% | -2.4% | Yahoo debt includes operating leases (-17%) |
| WMT, CAT, BOOT, NVDA, COST, CRVL, GOOGL | match | 0.0% | 0.0% | 0.0 to 7.5% | cash and debt gaps are mostly definitions (operating leases inside Yahoo debt, short-term-investment tags); COST TTM now correct after the 16-week-Q4 fix |
| JNJ | 2026-06-28 vs Yahoo 2026-09-27 | -1.4% | n/a | -0.6% | Yahoo already has Q3 from the earnings press release; the 10-Q is not filed |
| KO | 2026-04-03 vs 2026-07-03 | -1.7% | -4.3% | -8.8% | EDGAR is missing the 2026-07-29 10-Q (section 2.10) |
| ETSY | 2026-06-30 | -2.8% | -43.7% | +18.5% | EDGAR TTM NI $209.3M = sum of Yahoo's own four quarterly statements; Yahoo's `.info.netIncomeToCommon` ($371M) is inconsistent |

- **Freshness:** on 2026-10-18, 85% of sampled non-financials still sit on a quarter ending on or before 2026-06-30, median TTM period age 110 days, only 0.9% already on a September quarter. During earnings season Yahoo is up to a few weeks ahead of EDGAR because press releases precede 10-Qs (JNJ). Companies reporting Q3 between now and 10-21 will still show Q2 TTM numbers on EDGAR.

**Recommendation:** compute live signals from EDGAR (same tags, same TTM and EV code, same strict `filed < T` rule as the backtest) plus the last completed close. That keeps live and backtest definitions identical. Then:
1. refresh the top 100 to 150 screened candidates through the per-company API on 10-20 (one request each);
2. run the reconciliation from 2.10 and mark names whose newest EDGAR period is older than their `submissions` `reportDate`;
3. for each candidate also read Yahoo `mostRecentQuarter`; if it is later than the EDGAR period end, print Yahoo's TTM revenue and EBITDA next to the EDGAR figure and decide by hand (do not blend the two in the score);
4. take sector from Wikipedia GICS, and use `impliedSharesOutstanding` only as a sanity check on share counts.

---

## 8. Risk-free rate, factors, benchmarks

- **Ken French** (all fetched, HTTP 200): base `https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/`
  - `F-F_Research_Data_5_Factors_2x3_daily_CSV.zip` (150 KB): Mkt-RF, SMB, HML, RMW, CMA, RF; 15,897 rows, 1963-07-01 to **2026-08-31**.
  - `F-F_Momentum_Factor_daily_CSV.zip` (85 KB): Mom; 26,216 rows from 1926-11-03 to 2026-08-31.
  - Monthly versions `F-F_Research_Data_5_Factors_2x3_CSV.zip` (758 months to 2026-08) and `F-F_Momentum_Factor_CSV.zip` (1,196 months); 3-factor daily from 1926 also available.
  - Values are percent, not decimals. No -99.99 missing codes in these files. They lag by about 7 weeks (publication runs 1 to 2 months behind): factor regressions end 2026-08-31.
  - Parse (tested): the CSV has a text preamble; keep lines that start with an 8-digit (daily) or 6-digit (monthly) date and stop at the first blank line after data (the monthly files append an annual block).

```python
import zipfile, re, pandas as pd
def read_french(path, daily=True):
    z = zipfile.ZipFile(path); txt = z.read(z.namelist()[0]).decode("latin-1").splitlines()
    pat = re.compile(r"^\s*(\d{8}|\d{6})\s*,"); rows, hdr = [], None
    for i, l in enumerate(txt):
        if pat.match(l):
            if hdr is None:
                j = i - 1
                while not txt[j].strip(): j -= 1
                hdr = [c.strip() for c in txt[j].split(",")]
            rows.append([c.strip() for c in l.split(",")])
        elif rows and not l.strip():
            break
    df = pd.DataFrame(rows, columns=["date"] + hdr[1:][:len(rows[0]) - 1])
    df["date"] = pd.to_datetime(df["date"], format="%Y%m%d" if daily else "%Y%m")
    return df.set_index("date").astype(float)        # percent units
```
- **T-bills:** FRED `https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3` (columns `observation_date, DTB3`, percent, daily since 1954, last 2026-10-15 = 4.10, blanks on holidays, use `to_numeric(errors="coerce")`). `^IRX` on yfinance is the same series quoted one day fresher (last 2026-10-16 = 4.070): correlation 1.000, mean difference -0.006 pp. Use `^IRX` for the live risk-free number and DTB3 for history. Convert to a daily rate with `rate/100/252` (or act/360); Ken French's `RF` is about the same (daily RF vs DTB3/360 correlation 0.96 because RF is rounded to 0.01).
- **Benchmarks:** SPY, RSP, IWM, MDY, IJR, IWB, IWV: all available from yfinance with dividends (see section 5).

---

## 9. Recommended pipeline (download, parse, cache)

```
cache/
  sec/            companyfacts.zip, submissions.zip   (bulk, read-only)  + company_tickers*.json (dated copies)
  universe/       sp500_hist_fja.csv (raw), sp500_wikipedia_YYYYMMDD.csv, sp400_*.csv, sp600_*.csv, nasdaqlisted.txt,
                  otherlisted.txt, cik_aliases.csv, ticker_aliases.csv, universe_pit.parquet
  fundamentals/   fund_long.parquet      first-filed PIT: cik, concept, end, filed, val, tag, basis
                  fund_live.parquet      latest vintage as of the run date
                  meta.parquet           cik, name, sic, category, fye, first_xbrl_filed, newest_period_in_facts,
                                         newest_xbrl_period_in_submissions, stale_flag
  prices/         prices_long.parquet    ticker, date, close, adj_close, volume, dividends, splits
  factors/        ff5_daily.parquet, mom_daily.parquet, rf_daily.parquet (DTB3 + IRX)
  bench/          bench_total_return.parquet
  panels/         pit_panel_monthly.parquet     (date x cik: all concepts + market cap + EV, strict filed < T)
```

1. `build_universe`: fja CSV + Wikipedia patch, ticker aliases and CIK aliases, drop dual-class duplicates by CIK, attach SIC and current GICS.
2. `build_fundamentals`: stream `companyfacts` members from the zip (`zipfile.ZipFile(...).open("CIK0000320193.json")`), call `pit.load_facts` and `pit.build_company`, write long parquet. Measured: 0.44 s per company, 10.9 KB per company in zstd parquet (6,000 companies is about 44 minutes single-core or about 10 minutes on 4 to 6 processes and about 65 MB).
3. `reconcile`: compare facts against `submissions` (section 2.10) and write the stale flag.
4. `fetch_prices`: yfinance in chunks of 250, `auto_adjust=False, actions=True`, accept a series only if it overlaps the membership window.
5. `build_panel`: vectorised as-of join (tested: 177 month-ends x 135 companies x 8 concepts in 1.2 s):

```python
grid = pd.MultiIndex.from_product([dates, ciks], names=["T", "cik"]).to_frame(index=False)
grid["Teff"] = grid["T"] - pd.Timedelta(days=1)                       # strictly earlier filings only
d = L[L.concept == "revenue"][["cik", "end", "filed", "val"]].sort_values("filed")
m = pd.merge_asof(grid.sort_values("Teff"), d, left_on="Teff", right_on="filed", by="cik", direction="backward")
m.loc[(m["T"] - m["end"]).dt.days > 230, "val"] = np.nan             # staleness cut
```
6. `signals`: factor definitions (quality momentum, Magic Formula, comps) read only the panel; `live_signals` reads the same panel builder with `mode="latest"` and today's date.

Sizes: companyfacts averages 3.9 MB per company over the API (about 6 GB for 1,500 names) so use the bulk zip rather than 1,500 API calls; the API is for refreshing a handful of names.

---

## 10. Gotcha checklist

1. `fy`/`fp` are filing labels; group on `(start, end)`.
2. Only use periodic forms; ignore 8-K/424B2/DEF 14A rows.
3. First filed wins; amendments count; availability is `filed`, compared with strict `<`.
4. Q4 comes from FY minus 9M at the 10-K date; the reported discrete Q4 arrives a year later.
5. Start dates jitter by 1 to 2 days across filings; collapse on `(end, duration class)`.
6. Retail calendars: 12-12-12-16 week quarters, 52/53-week years; allow 70 to 125 days between quarter ends.
7. Cash-flow items are YTD only; EPS and weighted shares are not additive.
8. Pick the largest of the total-revenue tags, not the first (ETN, PG, CCK).
9. Tag drift and missing interim facts need freshness guards (CAT debt, NVDA investments, AAPL interest).
10. Multi-class share counts are missing from companyfacts; scale-error counts exist (PKG, ORCL).
11. Successor CIKs (XOM, VYLR) and `company_tickers.json` is current-only; EDGAR cannot resolve old tickers.
12. companyfacts can miss recent filings (12 Q2-2026 10-Qs); reconcile with `submissions`.
13. yfinance: zero delisted history; ticker reuse attaches the wrong company; `Adj Close` is re-based after each dividend; pass `auto_adjust` explicitly; `.info` fields can contradict Yahoo's own statements (ETSY).
14. Market cap: unadjust price, adjust shares only for genuine splits after the filing; Yahoo logs spin-offs as odd fractional splits.
15. pandas 3: yfinance dates are `datetime64[s]`, SEC dates `[us]`; cast to `[ns]` before `merge_asof`.
16. Wikipedia: S&P 500 changes table is gone; S&P 400 has no CIK column; use `id`/columns to find tables.
17. Financials and utilities: SIC 6000-6799 and 4900-4999 (REITs are 6798); no free historical GICS.
18. Q3 earnings season: EDGAR lags press releases; flag stale periods in the live run.
19. French factors end 2026-08-31; extend risk-free with DTB3 or `^IRX`.
20. Never put any key or personal email in the repo; the only SEC identity string is the project User-Agent.

---

## Appendix A - tested reference implementation (`pit.py`)

All numbers above were produced with exactly this code (prototype lived in the session scratchpad, not in the repo).

```python
"""pit.py - point-in-time fundamentals from SEC companyfacts JSON (final prototype, tested).

build_company(facts)  -> {concept: DataFrame}   (first-filed, as-originally-reported; run once, cache to parquet)
asof(built, T)        -> dict of latest values known strictly BEFORE date T
Live signals: build_company(facts, mode="latest", asof=today) = latest restated vintage known today.
"""
import numpy as np
import pandas as pd

PERIODIC = {"10-K", "10-K/A", "10-KT", "10-KT/A", "10-K405", "10-Q", "10-Q/A", "10-QT",
            "20-F", "20-F/A", "40-F", "40-F/A"}

# ---- FLOW concepts: tag fallback order (first = preferred) ------------------------------
FLOW = {
    "revenue": ["Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax",
                "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueNet",
                "SalesRevenueGoodsNet", "SalesRevenueServicesNet", "RegulatedAndUnregulatedOperatingRevenue",
                "RevenuesNetOfInterestExpense"],
    "cogs": ["CostOfRevenue", "CostOfGoodsAndServicesSold", "CostOfGoodsSold", "CostOfServices",
             "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"],
    "gross_profit": ["GrossProfit"],
    "op_income": ["OperatingIncomeLoss"],
    "net_income": ["NetIncomeLoss", "ProfitLoss", "NetIncomeLossAvailableToCommonStockholdersBasic"],
    "da": ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "UtilitiesOperatingExpenseDepreciationAndAmortization",
           "DepreciationAmortizationAndOther", "Depreciation", "DepreciationNonproduction"],
    "interest_expense": ["InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt",
                         "InterestAndDebtExpense", "InterestExpenseLongTermDebt", "InterestExpenseOperating"],
    "interest_net": ["InterestIncomeExpenseNonoperatingNet", "InterestIncomeExpenseNet"],   # NEGATIVE = net expense
    "tax": ["IncomeTaxExpenseBenefit"],
    "pretax": ["IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
               "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments"],
    "cfo": ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
    "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
              "PaymentsForCapitalImprovements", "PaymentsToAcquireOtherPropertyPlantAndEquipment",
              "PaymentsToAcquireRealEstate", "PaymentsToDevelopRealEstateAssets"],
}
# non-additive duration items: take the reported 3M (or FY) value, never difference/sum
NONADD = {"eps_diluted": ["EarningsPerShareDiluted"], "wtd_sh_diluted": ["WeightedAverageNumberOfDilutedSharesOutstanding"]}

INSTANT = {
    "assets": ["Assets"], "cur_assets": ["AssetsCurrent"], "cur_liab": ["LiabilitiesCurrent"],
    "liabilities": ["Liabilities"],
    "cash": ["CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
             "CashAndDueFromBanks", "Cash"],
    "st_inv": ["ShortTermInvestments", "MarketableSecuritiesCurrent", "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
               "DebtSecuritiesCurrent", "AvailableForSaleSecuritiesCurrent", "OtherShortTermInvestments"],
    "cash_sti": ["CashCashEquivalentsAndShortTermInvestments"],
    "ppe_net": ["PropertyPlantAndEquipmentNet",
                "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization"],
    "equity": ["StockholdersEquity"],
    "equity_incl_nci": ["StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
    "pref": ["PreferredStockValue", "PreferredStockValueOutstanding", "PreferredStockCarryingValue"],
    "nci": ["MinorityInterest"],
    # --- debt pieces ---
    "debt_current": ["DebtCurrent"], "st_borrow": ["ShortTermBorrowings"], "cp": ["CommercialPaper"],
    "ltd_current": ["LongTermDebtCurrent", "LongTermDebtAndCapitalLeaseObligationsCurrent"],
    "ltd_nc": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
    "ltd_total": ["LongTermDebt"],
    "other_nc_debt": ["SeniorNotes", "SecuredDebt", "UnsecuredDebt", "ConvertibleNotesPayable",
                      "ConvertibleLongTermNotesPayable", "ConvertibleDebtNoncurrent", "LongTermNotesPayable",
                      "LongTermLineOfCredit", "LineOfCredit", "OtherLongTermDebtNoncurrent", "NotesPayableNoncurrent"],
    "debt_and_lease_total": ["DebtAndCapitalLeaseObligations"],
    "fin_lease": ["FinanceLeaseLiability"], "fin_lease_cur": ["FinanceLeaseLiabilityCurrent"],
    "fin_lease_nc": ["FinanceLeaseLiabilityNoncurrent"],
    "sh_bs": ["CommonStockSharesOutstanding"],
}
DEI_SHARES = ["EntityCommonStockSharesOutstanding"]
# Total-revenue candidates: when several co-exist in the same filing take the LARGEST (priority alone picked a zero /
# sub-line 'Revenues' for ETN, PG, CCK, MTRN, OXY in 1% of annual periods). 'Including assessed tax' is excluded on purpose.
MAXGROUP = {"revenue": {"Revenues", "RevenueFromContractWithCustomerExcludingAssessedTax", "SalesRevenueNet"}}
UNIT = {"eps_diluted": "USD/shares", "wtd_sh_diluted": "shares", "sh_bs": "shares"}


def load_facts(cf, taxonomies=("us-gaap", "dei")):
    rows = []
    for tx in taxonomies:
        for tag, v in cf["facts"].get(tx, {}).items():
            for unit, lst in v["units"].items():
                for x in lst:
                    rows.append((tx, tag, unit, x.get("start"), x["end"], x["val"], x["accn"], x.get("fy"),
                                 x.get("fp"), x["form"], x["filed"]))
    df = pd.DataFrame(rows, columns=["tax", "tag", "unit", "start", "end", "val", "accn", "fy", "fp", "form", "filed"])
    for c in ("start", "end", "filed"):
        df[c] = pd.to_datetime(df[c])
    return df[df["form"].isin(PERIODIC)].copy()


def pick(facts, tags, unit="USD", tax="us-gaap", mode="first", asof=None, maxgroup=None):
    """One row per period (start,end).
    mode='first' : the EARLIEST filing that reported the period wins (as-originally-reported); inside that filing the
                   tag is chosen by `maxgroup` (largest value) else by list priority.
    mode='latest': latest vintage filed <= asof of every candidate tag; tag chosen by maxgroup else priority."""
    d = facts[(facts["tax"] == tax) & facts["tag"].isin(tags) & (facts["unit"] == unit)]
    if asof is not None:
        d = d[d["filed"] <= pd.Timestamp(asof)]
    if d.empty:
        return d
    d = d.sort_values(["tag", "start", "end", "filed", "accn"])
    k = ["tag", "start", "end"]
    d = (d.groupby(k, as_index=False, dropna=False).first() if mode == "first"
         else d.groupby(k, as_index=False, dropna=False).last())
    prio = {t: i for i, t in enumerate(tags)}
    d["prio"] = d["tag"].map(prio)
    pk = ["start", "end"] if d["start"].notna().any() else ["end"]
    if mode == "first":
        d = d[d["filed"] == d.groupby(pk, dropna=False)["filed"].transform("min")]       # earliest filing only
    inmax = d["tag"].isin(maxgroup) if maxgroup else pd.Series(False, index=d.index)
    d = d.assign(k1=(~inmax).astype(int), k2=np.where(inmax, -d["val"].abs(), d["prio"]))
    d = d.sort_values(pk + ["k1", "k2", "filed"], na_position="last")
    return d.groupby(pk, as_index=False, dropna=False).first().drop(columns=["k1", "k2"])


def _cls(days):
    return 1 if 77 <= days <= 105 else 2 if 160 <= days <= 200 else 3 if 250 <= days <= 290 else 4 if 340 <= days <= 380 else 0


def quarters(obs, mode="first"):
    """obs: rows per (start,end) [flow]. Returns discrete quarters: start,end,val,filed,src.
    Handles (a) start-date jitter across filings (same period, start differs by 1-2 days) by collapsing on
    (end, duration-class), and (b) YTD chains whose start dates jitter by clustering starts within 6 days."""
    o = obs.copy()
    o["days"] = (o["end"] - o["start"]).dt.days + 1
    o["cls"] = o["days"].map(_cls)
    o = o[o["cls"] > 0].sort_values(["end", "cls", "filed", "accn"])
    g = o.groupby(["end", "cls"], as_index=False)
    o = (g.first() if mode == "first" else g.last())
    # cluster fiscal-year start dates (jitter <= 6 days)
    st = np.sort(o["start"].unique())
    cid, last, c = {}, None, 0
    for d in st:
        if last is not None and (d - last).astype("timedelta64[D]").astype(int) > 6:
            c += 1
        cid[d] = c
        last = d
    o["skey"] = o["start"].map(cid)
    cand = []                                                     # (end, filed, pref, row)
    for r in o[o["cls"] == 1].itertuples():                       # reported discrete quarter (or Q1 YTD)
        cand.append(dict(start=r.start, end=r.end, val=r.val, filed=r.filed, src="reported", pref=0))
    for s_, gg in o.groupby("skey"):                              # YTD chains sharing a fiscal-year start
        c_ = {k: x.iloc[0] for k, x in gg.groupby("cls")}
        for hi, lo in ((2, 1), (3, 2), (4, 3)):
            if hi in c_ and lo in c_:
                h, l = c_[hi], c_[lo]
                cand.append(dict(start=l["end"] + pd.Timedelta(days=1), end=h["end"], val=h["val"] - l["val"],
                                 filed=max(h["filed"], l["filed"]), src=f"derived_{hi}-{lo}", pref=1))
        if 4 in c_ and 3 not in c_:                               # Q4 = FY - (Q1+Q2+Q3 discrete) when no 9M row
            fy = c_[4]
            ins = [v for v in cand if v["pref"] == 0 and fy["start"] - pd.Timedelta(days=6) <= v["start"]
                   and v["end"] < fy["end"]]
            if len(ins) == 3:
                cand.append(dict(start=max(i["end"] for i in ins) + pd.Timedelta(days=1), end=fy["end"],
                                 val=fy["val"] - sum(i["val"] for i in ins),
                                 filed=max([fy["filed"]] + [i["filed"] for i in ins]), src="derived_FY-3Q", pref=1))
    if not cand:
        return pd.DataFrame()
    c = pd.DataFrame(cand)
    # first-filed: whichever source became available EARLIEST wins (a Q4 reported discretely only shows up in
    # next year's 10-K, but FY-minus-9M is knowable at the 10-K). latest: prefer reported, then derived.
    c = c.sort_values(["end", "filed", "pref"] if mode == "first" else ["end", "pref", "filed"])
    return c.groupby("end", as_index=False).first().drop(columns="pref").sort_values("end").reset_index(drop=True)


def ttm(q):
    """4 consecutive quarters (gaps 70-125d: 12-12-12-16wk retailers ok; total span 350-380d)."""
    if q is None or len(q) < 4:
        return pd.DataFrame(columns=["end", "val", "filed"])
    rows = []
    for i in range(3, len(q)):
        w = q.iloc[i - 3:i + 1]
        gaps = w["end"].diff().dt.days.dropna()
        span = (w["end"].iloc[-1] - w["start"].iloc[0]).days + 1
        if gaps.between(70, 125).all() and 350 <= span <= 380:
            rows.append((w["end"].iloc[-1], w["val"].sum(), w["filed"].max()))
    return pd.DataFrame(rows, columns=["end", "val", "filed"])


def _monotone(t):
    """keep rows whose period end exceeds every earlier-filed row's end (so 'latest filed<=T' == 'latest end known')"""
    if t.empty:
        return t
    t = t.sort_values(["filed", "end"]).reset_index(drop=True)
    prev = t["end"].cummax().shift(1)            # NaT for the first row -> comparison False -> handled below
    keep = (t["end"] > prev) | prev.isna()
    return t[keep].reset_index(drop=True)


def build_company(facts, mode="first", asof=None):
    """-> {concept: DataFrame[end,val,filed(,tag)]}. Cache this as parquet (long format)."""
    B = {}
    for c, tags in FLOW.items():
        o = pick(facts, tags, "USD", "us-gaap", mode, asof, MAXGROUP.get(c))
        if o.empty:
            continue
        qq = quarters(o, mode)
        t = ttm(qq)
        fy = o.assign(days=(o["end"] - o["start"]).dt.days + 1)
        fy = fy[fy["days"].between(340, 380)][["end", "val", "filed"]]       # annual rows (also all a 20-F/40-F filer has)
        t = pd.concat([t.assign(basis="ttm"), fy.assign(basis="fy")]).sort_values(["filed", "end", "basis"], ascending=[True, True, False])
        if len(t):
            B[c] = _monotone(t.drop_duplicates(["end", "filed"]))
        if len(qq):
            B[c + "_q"] = _monotone(qq[["end", "val", "filed"]])      # last discrete quarter (for latest-quarter use)
    for c, tags in NONADD.items():
        o = pick(facts, tags, UNIT[c], "us-gaap", mode, asof)
        if o.empty:
            continue
        o = o.assign(days=(o["end"] - o["start"]).dt.days + 1)
        o = o[o["days"].between(77, 105)]                          # discrete 3M only (never difference)
        if len(o):
            B[c] = _monotone(o[["end", "val", "filed"]])
    for c, tags in INSTANT.items():
        o = pick(facts, tags, UNIT.get(c, "USD"), "us-gaap", mode, asof)
        if len(o):
            B[c] = _monotone(o[["end", "val", "filed", "tag"]])
    o = pick(facts, DEI_SHARES, "shares", "dei", mode, asof)
    if len(o):
        B["sh_dei"] = _monotone(o[["end", "val", "filed"]])
    return B


def _last(B, c, T, max_age_days=None):
    t = B.get(c)
    if t is None or t.empty:
        return np.nan, pd.NaT
    t = t[t["filed"] < pd.Timestamp(T)]            # strict: filed the day before or earlier
    if t.empty:
        return np.nan, pd.NaT
    r = t.iloc[-1]
    if max_age_days is not None and (pd.Timestamp(T) - r["end"]).days > max_age_days:
        return np.nan, r["end"]
    return r["val"], r["end"]


def total_debt(B, T, bs_end, fresh_days=120):
    """Composite interest-bearing debt with freshness guard. Returns (value, how)."""
    g = lambda c: (lambda v, e: v if (not pd.isna(e) and (bs_end - e).days <= fresh_days) else np.nan)(*_last(B, c, T))
    z = lambda x: 0.0 if pd.isna(x) else x
    dc, ltdc, stb, cp = g("debt_current"), g("ltd_current"), g("st_borrow"), g("cp")
    cur = (dc if (pd.isna(ltdc) or dc >= ltdc) else dc + ltdc) if not pd.isna(dc) else z(stb) + z(cp) + z(ltdc)
    nc, how = g("ltd_nc"), "ltd_nc"
    if pd.isna(nc) and not pd.isna(g("ltd_total")):
        nc, how = g("ltd_total") - z(ltdc), "ltd_total-cur"
    if pd.isna(nc):
        nc, how = g("other_nc_debt"), "other_nc"
    if pd.isna(nc):
        nc, how = g("debt_and_lease_total"), "debt_and_lease_total"
    if pd.isna(nc) and cur == 0:
        return np.nan, "none"
    t = B.get("ltd_nc")
    incl_lease = False
    if t is not None and not t.empty and (t["filed"] < pd.Timestamp(T)).any():
        incl_lease = t[t["filed"] < pd.Timestamp(T)].iloc[-1].get("tag") == "LongTermDebtAndCapitalLeaseObligations"
    fl = 0.0
    if not incl_lease:
        f = g("fin_lease")
        fl = z(f) if not pd.isna(f) else z(g("fin_lease_cur")) + z(g("fin_lease_nc"))
    return z(cur) + z(nc) + fl, how


def asof(B, T, flow_max_age=230, inst_max_age=230):
    """Everything knowable strictly before T from the built (first-filed) tables."""
    o = {}
    for c in FLOW:
        o[c], o[c + "_end"] = _last(B, c, T, flow_max_age)
    # derived items with fallbacks
    ie = o["interest_expense"]
    if pd.isna(ie):
        ie = max(-o["interest_net"], 0) if not pd.isna(o["interest_net"]) else np.nan
    o["interest_exp_final"] = ie
    if pd.isna(o["op_income"]) and not pd.isna(o["pretax"]):
        o["ebit"], o["ebit_src"] = o["pretax"] + (0 if pd.isna(ie) else ie), "pretax+int"
    else:
        o["ebit"], o["ebit_src"] = o["op_income"], "OperatingIncomeLoss"
    o["gross_profit_final"] = (o["gross_profit"] if not pd.isna(o["gross_profit"])
                               else (o["revenue"] - o["cogs"] if not (pd.isna(o["revenue"]) or pd.isna(o["cogs"])) else np.nan))
    o["ebitda"] = o["ebit"] + o["da"] if not (pd.isna(o["ebit"]) or pd.isna(o["da"])) else np.nan
    o["fcf"] = o["cfo"] - o["capex"] if not (pd.isna(o["cfo"]) or pd.isna(o["capex"])) else np.nan
    for c in ("assets", "cur_assets", "cur_liab", "liabilities", "cash", "st_inv", "ppe_net", "equity", "equity_incl_nci",
              "pref", "nci", "sh_bs", "cash_sti"):
        o[c], o[c + "_end"] = _last(B, c, T, inst_max_age)
    if pd.isna(o["equity"]) and not pd.isna(o["equity_incl_nci"]):
        o["equity"] = o["equity_incl_nci"] - (0 if pd.isna(o["nci"]) else o["nci"])
    o["debt"], o["debt_src"] = total_debt(B, T, o["assets_end"]) if not pd.isna(o["assets_end"]) else (np.nan, "none")
    o["sh_dei"], o["sh_dei_end"] = _last(B, "sh_dei", T, 400)
    o["sh_wtd"], _ = _last(B, "wtd_sh_diluted", T, 230)
    # share-count fallback chain
    for src in ("sh_dei", "sh_bs", "sh_wtd"):
        if not pd.isna(o[src]):
            o["shares"], o["shares_src"] = o[src], src
            break
    else:
        o["shares"], o["shares_src"] = np.nan, "none"
    return o


# ================= market cap (split-safe) =================================================
def clean_counts(s, k=8.0):
    """Drop share counts that are >k x away from the rolling median of neighbours (XBRL scale errors, e.g. PKG, ORCL)."""
    if s is None or len(s) < 3:
        return s
    s = s.sort_values("filed").reset_index(drop=True)
    lv = np.log(s["val"].astype(float).clip(lower=1))
    med = lv.rolling(5, center=True, min_periods=3).median()
    return s[(lv - med).abs() <= np.log(k)].reset_index(drop=True)


def nice_ratio(r):
    """True for genuine split ratios (2,3,1.5,10,... and reverses 1/2,1/10,...). Yahoo also logs spin-off price
    adjustments as odd fractional 'splits' (e.g. ASH 2017: 2.044) that must NOT touch share counts."""
    r = float(r)
    x = r if r >= 1 else 1.0 / r
    return abs(x * 2 - round(x * 2)) < 0.02 and round(x * 2) >= 3


def daily_market_cap(close_adj, splits, counts):
    """close_adj: Series(date->Close, auto_adjust=False, split-adjusted only).  splits: Series(ex-date->ratio, >0).
    counts: DataFrame[filed,val] of cover-page share counts (cleaned, first-filed).
    mcap_T = unadj_T * shares_as_reported * prod(nice splits with  filed < ex <= T)."""
    d = close_adj.dropna().to_frame("close").sort_index()
    d.index = pd.DatetimeIndex(d.index).astype("datetime64[ns]")      # pandas 3: yfinance=[s], SEC=[us] -> merge_asof needs same unit
    d.index.name = "date"
    if len(splits):
        splits = splits.copy(); splits.index = pd.DatetimeIndex(splits.index).astype("datetime64[ns]")
    idx = d.index
    s_all = pd.Series(1.0, index=idx)                             # split ratio on its ex-date (next trading day)
    for ex, r in (splits.items() if len(splits) else []):
        j = idx.searchsorted(ex)
        if j < len(idx):
            s_all.iloc[j] *= r
    C = s_all.cumprod()                                           # prod of all splits with ex <= t
    Cn = s_all.where([nice_ratio(x) if x != 1 else True for x in s_all], 1.0).cumprod()
    d["unadj"] = d["close"] * (C.iloc[-1] / C)                    # undo every Yahoo split/spin-off adjustment
    cts = counts.sort_values("filed")[["filed", "val"]].rename(columns={"filed": "cnt_filed"})
    cts["cnt_filed"] = pd.DatetimeIndex(cts["cnt_filed"]).astype("datetime64[ns]")
    m = pd.merge_asof(d.reset_index().sort_values("date"), cts,
                      left_on="date", right_on="cnt_filed", direction="backward", allow_exact_matches=False)
    m = m.set_index("date")
    Cn_at_filed = Cn.reindex(Cn.index.union(m["cnt_filed"].dropna().unique())).sort_index().ffill()
    base = Cn_at_filed.reindex(m["cnt_filed"].values).values
    m["shares_eff"] = m["val"] * (Cn.reindex(m.index).values / base)
    m["mcap"] = m["unadj"] * m["shares_eff"]
    return m
```
