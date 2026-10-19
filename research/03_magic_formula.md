# Magic Formula (Greenblatt): exact spec, evidence, XBRL mapping, backtest design

Prepared 2026-10-18 for Capital Crew (Wharton Global High School Investment Competition 2026-27).
Purpose: implement the Magic Formula from SEC EDGAR XBRL (us-gaap, with filing dates) plus yfinance prices, backtest it rigorously, and produce live picks for Wed 2026-10-21.

## 0. How to read this document (evidence grades)

Every factual claim carries a grade. Please keep the grades if you copy numbers into slides.

| Tag | Meaning |
|---|---|
| [P] | Primary: I opened the author's/site's own page (magicformulainvesting.com, SEC.gov, Wharton). |
| [S] | Secondary: I opened a paper/thesis/article that reports the claim (it may be quoting Greenblatt). |
| [S*] | Secondary seen only as a search-result snippet, or a page I could not open (403, paywall, unreadable PDF). Treat as a lead, not a fact. |
| [D] | Data I pulled myself from the SEC XBRL APIs on 2026-10-18 (scripts in the session scratchpad, not committed to the repo). |
| [U] | Unverified / my own design choice / from memory. Always flagged. |

**Important limitation.** I could not access the text of *The Little Book That Beats the Market* (archive.org copies are lending-restricted; Google Books blocked automated access). Greenblatt's exact definitions below therefore come from [P] magicformulainvesting.com plus [S] theses and articles that read the book. Where those sources disagree or are silent, I say so. In particular, **Greenblatt's definition of "excess cash" is not public** (two independent secondary sources say so), so any excess-cash rule is our own convention.

---

## 1. Bottom line

1. **Formula (documented):** ROC = EBIT / (net working capital + net fixed assets); EY = EBIT / EV; rank all eligible stocks on each (1 = best), add the two ranks, buy the lowest sums; equal dollar weights; 20-30 stocks; hold about one year; exclude financials, utilities, foreign/ADRs and (in the backtests) stocks below ~$50M market cap.
2. **Original claim:** top 30 of the largest ~3,500 US stocks returned 30.8%/yr vs 12.4% for the S&P 500 over 1988-2004 (before costs and taxes); 22.9%/yr for the largest 1,000 (market cap > ~$1B). The 2010 edition extends to 1988-2009: 23.8%/yr vs about 9.5-9.6% for the S&P 500 (3,500 universe). [S]
3. **Independent replications give smaller numbers** (ClariFI: 28% and 17.5% vs Greenblatt's 30.8% and 22.9%; Haugen: 10% vs 16.4% for 1996-2002 on the largest 1,000). [S]
4. **Most of the edge comes from the cheapness leg (EBIT/EV), not from ROC.** Several tests find EBIT/EV alone matches or beats the combined formula (Larkin 2009; Gray & Carlisle 2012; Davydov et al. 2016; Montier/DrKW 2006). [S]/[S*]
5. **Post-publication evidence is mixed to weak for the US.** Kreft (2022, Compustat/CRSP, 1987-2021) finds significant alpha until 2009 and none in 2010-2021; Martin (2020) finds roughly index-like returns after 2010 (about 12% vs 13%). Schwartz & Hanauer (2024) still find a positive but decayed effect with large relative drawdowns in 2018-2020. **Be honest in the competition write-up: it has probably not delivered 20-30%/yr since publication.** [S]
6. **EBIT/TEV is the best single value metric in Gray & Carlisle's book, but the Gray & Vogel (2012) paper's headline metric is EBITDA/TEV, not EBIT/TEV.** EBIT/TEV results (14.55% CAGR, 1964-2011, vs 13.72% for EBITDA/TEV) are from the *Quantitative Value* book as relayed by Alpha Architect [S*]. Please correct that attribution in the team doc.
7. **With free data (EDGAR XBRL + yfinance) we can only test about 2011/2012 onward**, which is entirely post-publication; we cannot reproduce 1988-2004. yfinance has no delisted tickers, so survivorship bias must be measured and bounded (Section 6.6).
8. **Recommended primary backtest configuration (pre-registered):** MF combined rank, N = 30, minimum market cap $1B, 12 monthly staggered sleeves, 12-month hold, equal weight, costs 10-25 bps per side; everything else is sensitivity. Report all 36 grid cells, not the best one (Section 7).
9. **Competition horizon caution.** Per the team's sibling note `research/07_competition_rules.md` (which cites official 2026-27 Wharton pages; I did not re-verify them), trading runs 2026-09-28 to 2026-11-06 and the portfolio freezes on Nov 6, so positions bought on Oct 21 are held for only 13 trading days inside the simulator, with $300,000 starting cash and a stock sleeve of roughly $75,000. Over 13 trading days the Magic Formula is statistically indistinguishable from any other reasonable cheap-and-profitable screen (Greenblatt himself says it trails the market in about one 1-year period in four and recommends 3+ year horizons [S]); its value here is as a documented, rules-based selection process for the IPS and Trading Notes, plus the multi-year plan the case describes, not as a short-run return engine.

---

## 2. The exact specification

### 2.1 What is documented vs not documented

| Item | What the sources say | Grade |
|---|---|---|
| ROC | EBIT divided by tangible capital employed = net working capital + net fixed assets | [S] Persson & Selander (P&S) 2009 summarising the book; [S] AAII 2006; [S] CFA Institute book review |
| EBIT | "12 month trailing pre-tax operating profits" (P&S). AAII's own screen used pre-tax income + interest expense (12m) | [S] |
| Net fixed assets | Net PP&E (PP&E less accumulated depreciation) | [S] AAII 2006 |
| Goodwill / intangibles | Excluded from tangible capital | [S] P&S; Huber (Saber Capital) |
| Excess cash | Excluded from capital employed; deducted in EV. **How Greenblatt computes it is undisclosed** | [S] P&S ("Greenblatt's unrevealed definition of excess cash"); [S] quant-investing glossary ("does not disclose") |
| Net working capital | Receivables + inventory + (operating) cash needed, less payables; if negative, 0 is used. Statement that NWC excludes excess cash and short-term interest-bearing debt is consistent with all secondary sources but I could not see the book's footnote | [S] AAII 2006, GuruFocus; [U] exact book wording |
| EV | Market value of equity (including preferred) + net interest-bearing debt + minority interest (P&S footnote, derived from the book). AAII: market cap + preferred + total debt - excess cash | [S] |
| EY | EBIT / EV; Greenblatt calls it an "inverted, slightly adjusted P/E" | [S] |
| Period | Earnings = latest 12 months; balance sheet = most recent; price = most recent close | [S] P&S section 3.2.1 |
| Universe | US-listed; excludes financials, utilities, foreign companies (ADRs). Backtest universes: largest 3,500 (cap > $50M), 2,500 (> $200M), 1,000 (> $1B) | [S] P&S; AAII; Wikipedia |
| Website | magicformulainvesting.com: database of US-listed equities only; financials and utilities excluded "because of the nature of their financial statements"; no plans for non-US; data source named as "S&P Compustat"; screen shows 30 or 50 stocks; free-text minimum market cap (millions); FAQ suggests ">$1 billion" to reduce volatility, at least 20 stocks, equal dollar amounts, hold about one year "to maximize your after-tax return", assumes you hold a stock the full year even if it leaves the list; prices update on trading days, financial data quarterly; describes its ratios as "low P/E" and "high return on capital" with "slight accounting adjustments" | [P] FAQ page, About the Book and home page, fetched 2026-10-18 |
| Website does NOT say | EY definition, ROC definition, ADR treatment, TTM vs fiscal year, specific tax-loss rules | [P] (absent from the fetched pages) |
| Schedule | Build the portfolio by buying 5-7 stocks every 2-3 months until 20-30 held; sell each after about one year | [S] AAII 2006 |
| Tax timing | Sell losers a few days (AAII) to one week (Wikipedia) before the 1-year mark, winners just after | [S] AAII; Wikipedia |

### 2.2 "Spec v1": our XBRL implementation (every choice flagged)

Notation: CA = AssetsCurrent, CL = LiabilitiesCurrent, all balance-sheet items are the latest filed quarter-end on or before the signal date; flows are trailing twelve months (TTM).

```
# Operating earnings
EBIT         = TTM OperatingIncomeLoss                      (fallback chain, Section 5.1)

# Cash and "excess" cash   (Greenblatt's rule is undisclosed -> our convention [U])
Cash         = CashAndCashEquivalents + ShortTermInvestments + MarketableSecuritiesCurrent   (current assets only)
ExcessCash   = max(0, min(Cash, CA - CL))
               # algebraically identical to the team's "cash - max(0, CL - CA + cash)":
               # cash counts as excess only to the extent current assets exceed current liabilities.

# Capital employed (denominator of ROC)
NWC          = (CA - ExcessCash) - (CL - CurrentDebt - OperatingLeaseLiabilityCurrent)
NWC_used     = max(NWC, 0)                                   (GuruFocus/AAII convention [S]; our floor)
NFA          = PropertyPlantAndEquipmentNet                  (excludes goodwill, intangibles, ROU assets)
Capital      = max(NWC_used + NFA, 0.01 * Assets)            (floor is our design [U]; prevents noise from near-zero denominators)
ROC          = EBIT / Capital

# Enterprise value (denominator of EY)
MarketCap    = Price * SharesOutstanding                     (Section 8 for what is live)
Debt         = interest-bearing debt incl. current portion and finance leases; excludes operating leases (Section 5.3)
EV           = MarketCap + PreferredStock + max(0, NoncontrollingInterest) + Debt - ExcessCash
EY           = EBIT / EV

# Eligibility (all must hold, else the stock is not ranked)
EBIT > 0 ; EV > 0 ; Capital > 0 ; classified balance sheet exists (CA and CL both reported)
Price >= $5 (Wharton 2025-26 rule; confirm 2026-27) ; MarketCap >= floor (grid) ; median 60-day dollar volume >= $250k [U]
10-K/10-Q filer, US-dollar reporter, common stock listed on NYSE/Nasdaq/NYSE American ; one share class per CIK
Not SIC 6000-6999 (finance, insurance, real estate incl. REITs, SPAC 6770) ; not SIC 4900-4999 (utilities) except 4950-4959 waste services [U]

# Ranking
r_ROC  = rank(ROC, descending)      r_EY = rank(EY, descending)     (1 = best, average rank for ties)
Score  = r_ROC + r_EY               choose the N lowest Score; tie-break: higher EY, then larger market cap
```

Notes on the design choices:
- **Ranks are computed among eligible stocks only.** Dropping negative-EBIT stocks does not change the ordering at the top (they rank at the bottom on both measures), so this is harmless and Greenblatt-consistent. The ambiguous cases are zero/negative capital and EV <= 0, handled by the floors/exclusions above.
- **OperatingIncomeLoss, not pre-tax income + interest expense, is the primary EBIT** because EV subtracts excess cash: an EBIT that includes interest income on that cash would count the cash twice. AAII's screen used pre-tax income + interest expense [S]; we keep it as a fallback and as a robustness variant.
- Greenblatt's "Capital floor" and the $5 / dollar-volume filters are not in the documented formula; they are implementation hygiene [U].

### 2.3 Purchase and sale schedule (documented, then adapted)

Documented [S]: buy 5-7 stocks every 2-3 months until 20-30 held; equal dollars; sell each position about one year after purchase (losers a few days to a week before 12 months, winners just after, for tax reasons); proceeds go into the next top-ranked names. Persson & Selander and the Greenblatt backtests effectively used rolling one-year holding periods starting every month (Greenblatt reports 193 rolling 1-year and 169 rolling 3-year periods for 1988-2004) [S].

Our adaptation for backtests: **12 monthly sleeves** (Section 6). Tax timing is irrelevant in a virtual competition and is not modelled (Reasonable Deviations also skipped it).

---

## 3. Evidence: reported results

### 3.1 Greenblatt's own numbers

| Universe (2005-edition backtest, 1988-2004, top 30, annual rebalance, before costs/taxes) | Magic Formula | Market average | S&P 500 | Grade |
|---|---|---|---|---|
| Largest 3,500 (cap > ~$50M) | 30.8%/yr | 12.3% | 12.4% | [S] P&S tables 3.1-3.3; [S] AAII; [S] Nasdaq/Validea |
| Largest 2,500 (cap > ~$200M) | 23.7%/yr | 12.4% | 12.4% | [S] P&S, AAII |
| Largest 1,000 (cap > ~$1B) | 22.9%/yr | 11.7% | 12.4% | [S] P&S, AAII |

- Annual return range, 3,500 universe: -4.4% to +79.9% (S&P: -22.1% to +37.6%). [S] (Validea/Nasdaq summaries; P&S table shows 2002: -4.0% and 2003: +79.9%, i.e. the worst-year figure differs by source; I did not reconcile.)
- Rolling windows, largest-1,000 universe: underperformed the market average in about 25% of 1-year windows (75% outperform, 193 windows) and about 17% of 2-year windows; beat the market in 95% of 3-year windows (160 of 169), with positive returns in all 169. In the 3,500 universe the formula beat the market in every 3-year window. [S] P&S, AAII
- Deciles (Feb 1994-Nov 2004, largest 1,000, annual rebalance): top decile 18.43%/yr, bottom decile 1.49%/yr, market 9.38%. [S] P&S Table 3.6
- **2010 edition ("The Little Book That Still Beats the Market"), 1988-2009:** 23.8%/yr (3,500 universe) vs 9.5% (Kreft) or 9.6% (other secondary sources) for the S&P 500; 19.7%/yr for the largest 1,000 (single source: Kreft). Decile figures converted to monthly: top decile 1.2%/month, bottom 0.0%. [S] Kreft 2022; [S*] Seeking Alpha/HedgeFundAlpha snippets
- Greenblatt used Compustat, which he states is point-in-time, and says he did not data-mine the two factors. [S] P&S. Note that these are *claims about method*, and Kreft says the book "does not clearly describe the methods used" for the backtest. [S]

### 3.2 Independent replications and academic tests

| Study | Market / period | Universe and construction | Result | Methodology notes | Grade |
|---|---|---|---|---|---|
| ClariFI (cited in P&S) | US, ~1988-2004 | Largest 3,500 / 1,000 | 28% / 17.5% vs Greenblatt 30.8% / 22.9% | Differences possibly due to excess-cash definition | [S] |
| Haugen (cited in P&S) | US 1996-2002, largest 1,000 | Point-in-time Bloomberg data | MF 10%/yr vs 16.4% reported in the book; his own 65-factor model 17% | Different database, holdings, ranking, rebalancing | [S] |
| Larkin (2009), "Can Individual Investors Capture the Value Premium?", J. Business & Economic Research (Patrick J. Larkin) | US, Dec 1998-2006 (97 monthly start dates, 1-yr holds) | Cap > $50M, top 30 equal-weight, eight strategies | MF about 23.9%/yr average; EBIT/EV alone and E/P alone "similar"; B/M-and-size 26.2% with very high volatility; MF never negative over any 3- or 5-year window, trailed the market in 7 of 73 rolling 3-yr and 2 of 49 rolling 5-yr windows | Gross of costs; short, heavily overlapping sample; tilts to small caps. Original PDF unreadable; figures from CXO Advisory summary | [S*] |
| Persson & Selander (2009), SSE | Nordic 1998-2007 | Monthly ranking, 2 stocks/month, 24 stocks, 12-month hold; Datastream | Portfolio I (Greenblatt-style ROC) CAGR 14.68% vs MSCI Nordic 9.28%, S&P 500 4.23%; 11.98% after transaction costs; alphas not significant at 5% (CAPM or Fama-French) even before costs. Variant with ROC on total capital employed (incl. intangibles) 26.09% (23.14% after costs) | Authors note Greenblatt's exact items are unclear; Sharpe above benchmarks | [S] (opened thesis) |
| Goumas & Kallstrom (2010), Lund | Sweden Mar 1999-Jan 2010 | | Annual excess return 14.1% under Fama-French 3-factor for 1999-2007; Sharpe/Treynor above OMX SPI | Bachelor thesis | [S*] |
| Gray & Carlisle, *Quantitative Value* (2012) | US 1964-2011 | | Magic Formula CAGR 12.79% vs "quality and price" 15.31% (Greenbackd summary); pure EBIT/TEV value portfolio 14.55% vs EBITDA/TEV 13.72% (Alpha Architect summary); CFA Institute review: a cheapness-only (EBIT/EV) portfolio returned 15.95%/yr and beat the Magic Formula by more than 2%/yr; "the Magic Formula's outperformance comes entirely from its cheapness metric" | Different universes per comparison are not stated on the pages I opened | [S] CFA review, Greenbackd; [S*] Alpha Architect (403) |
| Gray & Vogel (2012), "Analyzing Valuation Measures: A Performance Horse-Race over the Past 40 Years", J. Portfolio Management Fall 2012 | US July 1971-Dec 2010, CRSP/Compustat | Excludes financials, utilities, ADRs, REITs; excludes firms below the 10th NYSE market-equity percentile; one-year, annually rebalanced equal-weight quintiles | **EBITDA/TEV** was best: cheapest quintile 17.66%/yr, 3-factor alpha 2.91%; E/M 15.23% (no alpha); B/M 15.03% (no alpha); the cheap-minus-expensive spread 9.69% for EBITDA/TEV vs 5.82% for E/M | TEV = market cap + short-term debt (DLC) + long-term debt (DLTT) + preferred (PSTKRV) - cash and short-term investments (CHE), i.e. *all* cash, not excess cash. EBIT/TEV was left out of this paper | [S] (opened PDF) |
| Montier / Lancetti, DrKW (2006) | US, Europe ex-UK, UK, Japan, 1993-2005 | | EBIT/TEV alone beat the Magic Formula in every region except Japan | Only described qualitatively | [S] Greenbackd; P&S cite it |
| Alpha Architect (Gray), 2011 posts | US | Large/mid-cap tilted universe | Own replication showed strong outperformance but "nowhere near" the book's ~31%; attributes the gap to size universe and sensitivity to assumptions | Pages returned 403; relayed by search snippets only | [S*] |
| Davydov, Tikkanen & Aijo (2016), Nordic J. Business 65(3-4) | Finland 1991-2013 | 0.5% transaction-cost assumption | MF 19.26% vs OMXH CAP GI 13.63%; **EBIT/EV alone 20.57%** | | [S*] via Poznan literature review and Wikipedia |
| Max & Svanberg (2019) | Sweden 2002-2019 | | 19.2% vs 5.7% (OMXSPI) | | [S*] Poznan review |
| Sistonen (2014), Aalto | Nordics 2000-2011 | | 29.4% net of costs/taxes vs 7.6% FTSE Nordic Value | | [S*] Poznan review |
| Vestre & Wikheim (2022), NHH | Norway 2003-2022 | Cap > NOK 200M | 20.8% vs 12.8% (OSEAX); monthly CAPM alpha 0.50%, significant only at 10% after realistic transaction costs | | [S*] Poznan review |
| Postma (2015), Erasmus | Benelux 1995-2014 | Datastream | Average annual premium about 7.7% | | [S*] search snippet |
| Blackburn & Cakici (2017; J. Investment Management 2021) | 23 developed markets 1991-2016 | Monthly; rank on 7-month-lagged data; quintile long-short; EW and VW | North America gross monthly long-short excess return: **MF -0.36% (EW) / 0.29% (VW)**; gross-profit-to-assets variant ("Improved MF") 0.79% / 0.88%. Europe MF 0.95% / 0.59%. Standard MF not statistically significant globally; gross-profit version is | Gross of costs and shorting costs; long-short | [S] CXO summary |
| Olin (2011), Aalto, "Value investing in the Finnish stock market" | Finland | | Keywords include "magic formula"; abstract not retrieved | | [S*] could not verify content |
| Blij (2011) | Netherlands | | **Could not locate.** Closest: Daggenvoorde (Erasmus, Dutch stocks 1989-2010; results not retrieved) | | [U] |

### 3.3 Post-publication and US evidence (the part that matters for 2026)

| Study | Period | Method | Result | Grade |
|---|---|---|---|---|
| Kreft (2022), Erasmus MSc, "Unravelling the magic of Magic Formula investing" | US 1987-2021 | Compustat/CRSP; Greenblatt definitions (ROC = EBIT/(NWC + net fixed assets); EV = market equity + net interest-bearing debt); excludes financials and utilities; decile portfolios, monthly, value-weighted and equal-weighted; fundamentals assumed available 4 months after the period | Long-short (decile 1 minus 10) +0.9%/month full sample, **+1.3%/month 1987-2009, 0.0%/month 2010-2021**; alpha vs Carhart and Fama-French 5-factor significant until 2009, not significant after. Adding momentum or replacing EBIT with gross profit changes nothing significantly. Monthly-rebalanced decile turnover is about 15.8% of the long-short book per month; at 50 bps one-way (1% round trip) he reports costs of "0.16%" and calls them annual, but 15.76% x 1% = 0.16% is a *per-month* figure (about 1.9%/yr), so his wording looks like a slip. Evidence that the ranking predicts earnings surprises is weak | [S] (opened PDF) |
| Martin (2020), Reasonable Deviations, "A critical look at Greenblatt's Magic Formula" | US July 2003-Dec 2015 (Quantopian) | Cap > $100M, excludes financials and utilities, buys 2 stocks/month at 1/24 of capital each, 12-month hold (about 24 names), 5 bps slippage, no tax timing | 11.4%/yr (Sharpe 0.60) vs S&P 500 8.7% (0.54); pre-mid-2007 about 26% vs 18%; 2007-2010 drawdown 57% vs 55%; **post-2010 about 12% vs 13%**; 2012: -5% vs SPY +10% | [S] |
| Schwartz & Hanauer (Dec 2024), "Formula Investing", SSRN 5043197 | US 1963-2022 | Quarterly decile sorts; excludes stocks below the 20th NYSE market-cap percentile; fundamentals lagged 6 months; long-only 40-stock portfolios for 2000-2022 | All four formulas (F-Score, Magic Formula, Acquirer's Multiple, Conservative Formula) have significant returns, mainly via value/quality exposure; top-minus-bottom raw returns 5.6-6.4%/yr; MF kept the highest alpha after factor adjustment; performance decayed after 2000; all had large relative drawdowns in 2018-2020. A quant-investing.com write-up of the paper reports MF top-40, quarterly rebalanced, capped value-weight, 2000-2022: 17.2%/yr vs 8.0% for the value-weighted universe, Sharpe 0.69 (that write-up's own caveats: it "retyped the table", costs not discussed) | [S*] Quantpedia, CXO, quant-investing summaries; paper itself returned 403 |
| Hongratanawong (2014) | Thailand 1993-2012 (and US) | | Better risk-adjusted returns in Thailand; no significant difference vs the market for the US | [S*] via Kreft's literature review |
| Alberg & Seckler (2015) | US 1973-2012 | | EY drove nearly all outperformance in pessimistic markets; ROC contributed little | [S*] via Poznan review; original not located |
| Commercial blog analyses (ShareScope UK 2022-23; invest-like 2024; Seeking Alpha 2018) | various | | Report lagging the S&P 500 for most of the 2010s and a "clean" top-30 portfolio trailing by about 6 points annualised over the five years to Dec 2024; none could be verified (undisclosed methods, survivorship caveats stated by ShareScope) | [S*] / [U] |

**Honest summary of post-publication performance:** there is no clean, independently audited US live record that I could find. The best-quality academic evidence (Kreft; Martin; Schwartz & Hanauer) says the effect was strong in 1987-2009, weak or absent in 2010-2021 for the original small-cap-inclusive formula, and that it behaves like a value-plus-profitability factor tilt with long drawdowns. Results are sensitive to the market-cap floor: microcaps drive a large share of the headline numbers (Greenblatt's own universe table drops from 30.8% to 22.9% going from $50M to $1B; Schwartz & Hanauer exclude the smallest 20% of NYSE-size stocks and report lower returns than the original studies). [S]

### 3.4 What drives the result: cheapness, not ROC

- Gray & Carlisle / CFA review: EBIT/EV alone beats the two-factor formula by more than 2%/yr; the formula's edge "comes entirely" from the cheapness leg. [S]
- Larkin 2009, Davydov 2016, Montier 2006, Alberg & Seckler 2015 point the same way. [S]/[S*]
- Blackburn & Cakici: replacing EBIT by gross profit in the quality leg is what restores significance in North America; Kreft finds the gross-profit swap makes no significant difference. [S]
- Practical consequence for our grid: **always report EY-only and ROC-only next to the combined ranking** (Section 7).

### 3.5 Methodology choices that explain different results

Universe/size floor (biggest driver); point-in-time vs lagged fundamentals (6-month lag in Schwartz & Hanauer, 4-month in Kreft, 7-month in Blackburn & Cakici, actual filing dates in our design); equal vs value weighting; rank-only vs threshold screens; whether excess cash is subtracted or all cash; EBIT definition; TTM vs last fiscal year; survivorship and delisting treatment; transaction costs (Davydov 0.5% assumption; Kreft 0.5% one-way; P&S cost-adjusted CAGR 11.98% vs 14.68% gross); weighting of overlapping windows. [S]

---

## 4. Practical handling rules (decisions for Spec v1)

| Situation | Rule in Spec v1 | Rationale / source |
|---|---|---|
| EBIT <= 0 | Not ranked (ineligible) | Ranks them last anyway; avoids negative-yield artefacts. Greenblatt's text I could access does not specify. [U] |
| NWC < 0 | NWC_used = 0 (capital = net fixed assets only) | GuruFocus and AAII describe 0 for negative NWC [S] |
| Capital (NWC + NFA) <= 0 or tiny | Floor at 1% of total assets; robustness run with 0.5% / 2% / no floor | Asset-light firms can have ROC in the thousands of percent; ordinal ranking tolerates it but noisy denominators (a few $100k of PP&E) would otherwise grab rank 1. [U] |
| EV <= 0 with EBIT > 0 | Exclude and log (count them) | Usually data errors or cash shells; with conservative excess-cash rules rare. [U] |
| Excess cash | Primary: max(0, min(Cash, CA - CL)). Variants: (a) all cash + short-term investments (what Gray & Vogel's TEV, AAII's custom screen, Postma use); (b) quant-investing rule: if CA > 2 x CL, excess = min(Cash, CA - 2 x CL), else 0 (**their** rule, adapted from Graham, not Greenblatt's) | Greenblatt's is undisclosed [S] |
| Short-term interest-bearing debt in NWC | Remove from CL before computing NWC (it is financing, and it is in EV via Debt) | Consistent with the "NWC excludes short-term interest-bearing debt" description [S, exact wording U] |
| Operating leases (ASC 842, effective 2019 for public companies) | Treat as operating: **do not** add operating lease liabilities to debt, **do not** put ROU assets into net fixed assets, and strip OperatingLeaseLiabilityCurrent out of CL so 2019 introduces no discontinuity. Lease cost stays inside EBIT (it did before and after 842) | Keeps 2011-2018 and 2019+ series comparable [U]. Magnitude: among 3,104 filers with both tags (Dec 2025), ROU assets exceed PP&E for 35.7% (median ROU/PP&E 0.53, upper quartile 1.76) [D], so the choice matters for retail/restaurant ROC; run a "lease-capitalised" variant as robustness |
| Finance (capital) leases | Include in Debt (they were debt before 842 and PP&E includes the asset) | [U] |
| EBIT proxy | Primary TTM OperatingIncomeLoss; fallback pre-tax income from continuing operations + interest expense; fallback 2: revenue - total costs | OperatingIncomeLoss present for 93.7% of classified-balance-sheet filers with net income (Dec 2025) [D] |
| Non-recurring items | Do not adjust in v1 (impairments and gains stay in EBIT); robustness: add back GoodwillImpairmentLoss | Greenblatt's screen is mechanical; cyclicals/peak earnings are a known weakness (Kreft's discussion) |
| TTM vs fiscal year | TTM (sum of last four quarters) | P&S: Greenblatt used latest 12 months [S]. Robustness: last fiscal year |
| TTM construction | TTM = FY(latest 10-K) + YTD(current 10-Q) - YTD(prior-year same period). If the latest filing is a 10-K, TTM = FY. Q4 is never reported on its own | Validated: for Apple as of 2026-10-18 this gives 154.859B, identical to the sum of four discrete quarters (32.427 + 50.852 + 35.885 + 35.695) [D] |
| Fiscal-year changes, transition periods | Require period lengths 350-380 days (annual), 85-100 (Q), 175-190 (6M), 265-280 (9M); otherwise NaN | [U] |
| Missing PP&E tag | NFA = 0 with a flag; Capital floor applies | 821 of 4,826 classified filers (17%) have neither PP&E tag [D]; many are services/biotech, some use custom tags |
| Missing debt tags | Debt = 0 only if no standard debt tag AND TTM interest expense is ~0; if interest expense > 0 and no debt tag, mark "debt unmapped" and exclude (live: manual check) | 29% of classified filers have no standard debt tag [D]; of those only 179 (12.7%) report interest expense, and only 18 have interest > 5% of EBIT [D] |
| Financials / utilities | By SIC from EDGAR submissions (`sic`): exclude 6000-6999 and 4900-4999 (keep 4950-4959 waste services) | GICS "Financials/Utilities" is not available free; SIC is a documented proxy [U]. Real-estate (65xx) and REITs (6798) excluded under 6000-6999 |
| Foreign / ADR | Only 10-K/10-Q filers (foreign private issuers file 20-F/40-F so ADRs drop out naturally); USD-reporting only | [S] Greenblatt excludes ADRs |
| Multiple share classes | One security per CIK; market cap must include all classes (Section 8) | Alphabet's dei:EntityCommonStockSharesOutstanding is absent from companyfacts [D] |
| Price floor | $5 | Wharton 2025-26 rule [S*]; AAII screen also used $5 [S]. Confirm 2026-27 |

---

## 5. XBRL (us-gaap) mapping with fallbacks

Coverage numbers below: `data.sec.gov/api/xbrl/frames` pulled 2026-10-18, instant frame CY2025Q4I (Dec-2025 balance sheets) and duration frame CY2025. Denominators: 6,167 entities reporting Assets; 4,826 with a classified balance sheet (both AssetsCurrent and LiabilitiesCurrent, i.e. 78%); 4,362 of those with FY2025 net income. Frames return one fact per entity and are approximate calendar alignments, so counts under-represent non-December year-ends. [D]

### 5.1 Income statement (flows, need TTM)

| Input | Primary tag | Fallbacks (in order) | Coverage / note [D] |
|---|---|---|---|
| EBIT | `OperatingIncomeLoss` | (1) `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` (alt `...MinorityInterestAndIncomeLossFromEquityMethodInvestments`) + `InterestExpense` (alt `InterestExpenseNonoperating`, `InterestExpenseDebt`, `InterestAndDebtExpense`); (2) `Revenues` or `RevenueFromContractWithCustomerExcludingAssessedTax` minus `CostsAndExpenses`; (3) `GrossProfit` minus `OperatingExpenses` | 4,663 report OperatingIncomeLoss (CY2025). Of 4,362 classified filers with net income: 4,088 (93.7%) have it; 95 fall to fallback 1 with an interest tag; 115 have pre-tax income but no interest tag (assume no interest); 64 have neither |
| Interest expense (for fallback + sanity) | `InterestExpense` | `InterestExpenseNonoperating`, `InterestExpenseDebt`, `InterestAndDebtExpense`, `-InterestIncomeExpenseNonoperatingNet` | 1,090 / 502 / 677 / 205 filers |
| Net income (sanity only) | `NetIncomeLoss` | `ProfitLoss` | 5,690 |

### 5.2 Balance sheet (instants; latest filed quarter-end)

| Input | Primary tag | Fallbacks / companions | Coverage (of 6,167 unless noted) [D] |
|---|---|---|---|
| Current assets (CA) | `AssetsCurrent` | none (unclassified balance sheet -> exclude) | 4,875 (79.0%) |
| Current liabilities (CL) | `LiabilitiesCurrent` | none | 4,869 (79.0%) |
| Total assets | `Assets` | | 6,167 |
| Cash | `CashAndCashEquivalentsAtCarryingValue` | `CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` (includes restricted cash, slight overstatement), `Cash` | 4,933 (80.0%) / 4,912 |
| Short-term investments | `ShortTermInvestments` | add `MarketableSecuritiesCurrent` if present; use `AvailableForSaleSecuritiesDebtSecuritiesCurrent` only if neither is present (overlap risk) | 662 / 385 / 275. Exclude non-current marketable securities (e.g. Apple's large long-term securities) |
| Net fixed assets | `PropertyPlantAndEquipmentNet` | `PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization` (post-2019); or `PropertyPlantAndEquipmentGross` minus `AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment` | 4,211 (68.3%) / 584 |
| (Excluded) goodwill, intangibles, ROU | `Goodwill`, `IntangibleAssetsNetExcludingGoodwill`, `OperatingLeaseRightOfUseAsset` | not part of capital | 2,910 / 2,357 / 4,309 |
| Current debt | `DebtCurrent` (short-term debt plus current maturities) | else sum of `LongTermDebtCurrent`, `ShortTermBorrowings`, `CommercialPaper`, `NotesPayableCurrent`, `ConvertibleNotesPayableCurrent`, `LoansPayableCurrent`, `LongTermDebtAndCapitalLeaseObligationsCurrent`; plus `FinanceLeaseLiabilityCurrent` or pre-2019 `CapitalLeaseObligationsCurrent` | 359 / 1,415 / 738 / 85 / 470 / 348 |
| Long-term debt | `LongTermDebt` (total incl. current maturities) | `LongTermDebtNoncurrent` (+ current debt above); then `LongTermNotesPayable`, `ConvertibleNotesPayable`/`ConvertibleDebtNoncurrent`, `SeniorNotes`, `LongTermLineOfCredit`, `LineOfCredit`, `SecuredDebt`, `UnsecuredDebt`, `LongTermDebtAndCapitalLeaseObligations`, `DebtAndCapitalLeaseObligations`, `NotesPayable`, `LoansPayable`, `OtherLongTermDebt`, `SubordinatedDebt`; **last resort, low confidence:** `DebtInstrumentCarryingAmount`; plus `FinanceLeaseLiabilityNoncurrent` / `CapitalLeaseObligationsNoncurrent` | 2,120 / 1,723 / ... Group coverage among classified filers (cumulative): standard tags 56.7%; plus note/line/secured/unsecured/DebtInstrument tags 62.3%; plus lease-inclusive variants 64.1%; plus the long tail above 70.8% |
| Operating lease items (strip, do not count as debt) | `OperatingLeaseLiabilityCurrent`, `OperatingLeaseLiabilityNoncurrent`, `OperatingLeaseLiability` | n/a before 2019 | 3,576 / 3,514 / 3,882 |
| Preferred stock | `PreferredStockValue` | `PreferredStockValueOutstanding`; redeemable preferred in mezzanine: `TemporaryEquityCarryingAmountAttributableToParent`, `PreferredStockRedemptionAmount` | tag in 1,924 filers but only 344 non-zero |
| Noncontrolling interest | `MinorityInterest` | `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` minus `StockholdersEquity`; `RedeemableNoncontrollingInterestEquityCarryingAmount` | 1,524, of which 1,443 non-zero and 253 negative (floor at 0) |
| Shares outstanding | `dei:EntityCommonStockSharesOutstanding` (cover page, as of a date within weeks after the quarter-end) | `CommonStockSharesOutstanding` (balance sheet), then `WeightedAverageNumberOfSharesOutstandingBasic` (flagged) | dei frame CY2026Q1I: 4,613 filers. **Multi-class companies often have no undimensioned value (Alphabet's is absent from companyfacts)**; Berkshire's exists only for the old single-class period [D] |
| SIC code, filer category, exchange | EDGAR `submissions` JSON: `sic`, `category` (e.g. "Large accelerated filer"), `exchanges`, `tickers`, `fiscalYearEnd`; `company_tickers_exchange.json` (cik, name, ticker, exchange) | | verified fields on Apple's submissions file [D] |

Debt-tag semantics I measured [D], so you do not double count:
- When `LongTermDebt`, `LongTermDebtNoncurrent` and `LongTermDebtCurrent` are all present (921 filers), `LongTermDebt` equals noncurrent + current (within 1%) for 754 (82%); i.e. `LongTermDebt` normally **already includes the current portion**.
- `DebtCurrent` is usually the larger concept: where both it and `LongTermDebtCurrent` exist (146), DebtCurrent >= LongTermDebtCurrent in 137. Where it also coexists with `ShortTermBorrowings` (43), it equals LTD-current + short-term borrowings in 25 and equals LTD-current in 12.
- Therefore: if `LongTermDebt` is present, Debt = LongTermDebt + short-term borrowings/commercial paper/notes payable current (not LongTermDebtCurrent, not DebtCurrent); else Debt = LongTermDebtNoncurrent + DebtCurrent (or the sum of its parts if DebtCurrent is absent). Example: Apple at 2026-06-27 has LongTermDebt 82.300B (= noncurrent 71.340B + current 11.007B, within rounding) plus CommercialPaper 1.997B -> Debt 84.297B, plus finance leases if any. [D]
- Sanity checks to code: Debt <= Liabilities; Cash + STI <= CA; ExcessCash <= Cash; EV <= 3 x (MarketCap + Debt); public-float cross-check (MarketCap vs dei:EntityPublicFloat within a factor of about 5).

### 5.3 Point-in-time (PIT) rules for companyfacts

Each companyfacts record has: `start` (flows only), `end`, `val`, `accn`, `fy`, `fp`, `form`, `filed`, `frame`. [D] Apple example confirms:
1. **Use `filed`, not period end, to decide what was knowable.** For each (start, end) choose the record with the greatest `filed` <= signal date minus 1 trading day (so 10-K/10-Q filed after hours is not used same day). Prior periods re-appear as comparatives in later filings with later `filed` dates, sometimes restated; this rule reproduces what a user would have seen then.
2. **`fy` and `fp` describe the filing, not the period.** Comparative values carry the later filing's fy/fp (e.g. a 2025 quarter appears with fy=2026). Identify periods by `start`/`end` and day-count only.
3. **`frame` is attached to one record per period** (often the latest filing); do not use it for PIT logic.
4. Only forms 10-K, 10-Q, 10-K/A, 10-Q/A, 10-KT, 10-QT.
5. **Core balance items must come from the anchor balance-sheet date** (the `end` of the latest filing's AssetsCurrent). Optional items that appear only in 10-Ks (lease liabilities, goodwill; Apple's `OperatingLeaseLiabilityCurrent` was last tagged at 2025-09-27 and its Goodwill at 2017-12-30) may be carried forward up to ~400 days; otherwise treat as 0 and flag.
6. **XBRL coverage ramps up over time** (SEC Release 33-9002, effective 2009-04-13 [S]): large accelerated filers with float > $5B from periods after 2009-06-15; all other large accelerated filers after 2010-06-15; all remaining filers (including small caps) after 2011-06-15. [S] Law-firm summaries (Willkie, Baker Donelson, DWT); I did not open the SEC release itself. Frame counts of Assets at Dec year-ends are 1,425 (2009), 6,512 (2010), 8,166 (2011), 7,851 (2012), 7,018 (2015), 6,305 (2018), 6,180 (2019), 6,167 (2025) [D], but the early counts include comparatives from later filings, so they overstate what was *point-in-time available then*.
   - Consequence: **>$1B tier from about April 2011 (after FY2010 10-Ks for phase 1-2 filers); all-size tier from about April-June 2012** (after FY2011 10-Ks give small filers their first full TTM). Build a monthly coverage diagnostic (eligible count per month) and start each tier when it reaches about 90% of its plateau.
7. Filing deadlines (for staleness logic) [S]: 10-Q due 40 days after quarter-end for large accelerated and accelerated filers, 45 days for others; 10-K due 60 / 75 / 90 days (large accelerated / accelerated / others); NT filings add 5 (10-Q) or 15 (10-K) days.
8. SEC fair access: at most 10 requests/second and a declared User-Agent. [P] Use `CapitalCrew Student Research Project research@capitalcrew-project.org` as the User-Agent. For the full universe, download the nightly `companyfacts.zip` and `submissions.zip` bulk files (the SEC API page recommends them) instead of ~6,000 individual calls. [P]

### 5.4 Reference pseudo-code (validated on Apple)

```python
def pit(rows, asof):                      # rows = companyfacts units list for one tag
    best = {}
    for r in rows:
        if r["form"] not in FORMS or date(r["filed"]) >= asof: continue
        k = (r.get("start"), r["end"])
        if k not in best or r["filed"] > best[k]["filed"]: best[k] = r
    return list(best.values())

def ttm(rows, asof):
    rs = [r for r in pit(rows, asof) if "start" in r]
    latest_end = max(r["end"] for r in rs)
    cur = max((r for r in rs if r["end"] == latest_end), key=duration)      # longest YTD ending at latest_end
    if 350 <= duration(cur) <= 380: return cur["val"]                       # latest filing is a 10-K
    fy  = the 350-380 day record whose end is within 10 days of cur["start"] # prior fiscal year
    pyt = the record with same length as cur ending ~364 days earlier       # prior-year YTD
    return fy["val"] + cur["val"] - pyt["val"]
```

---

## 6. Backtest design

### 6.1 Data layer
- Fundamentals: EDGAR bulk `companyfacts.zip` (PIT rules above) + `submissions.zip` (SIC, category, exchange).
- Prices: yfinance daily history; use unadjusted-for-dividend `Close` for market cap and `Adj Close` for total returns. **Split consistency:** XBRL cover-page shares are as of the cover date, while yfinance `Close` is split-adjusted to today, so multiply shares by the cumulative split factor of every split after the cover date, or compute market cap as raw (unadjusted) price x raw shares. This is a classic silent error.
- Ticker mapping: EDGAR gives *current* tickers only (`company_tickers_exchange.json`). Companies that delisted, merged, or changed tickers are missing or mismapped (reused tickers). Cross-check price-implied market cap against `dei:EntityPublicFloat` and reject mismatches.

### 6.2 Dates and portfolio mechanics
- Signal dates: last trading day of each month. Fundamentals use only filings with `filed` earlier than the signal date; execute at the next day's close (or the same close if you prefer a conservative 1-day lag on prices). 
- **Staggered monthly sleeves (core design):** each month t, rank, buy the top N, hold 12 months, then sell. The portfolio return is the equal-weighted average of the 12 live sleeves. This (a) mirrors "buy a few every couple of months" and Greenblatt's 193 rolling one-year periods, (b) removes the rebalance-date luck, which is large for a concentrated 30-stock strategy. Two reporting views:
  - **Cohort view (statistical):** each sleeve holds the full top-N; average across sleeves. Not literally implementable (12 x N names) but the right object for inference.
  - **Implementable view:** buy about N/12 new names per month (for N = 30 alternate 3,2,3,2...; for N = 20 use 2,2,1 repeating), skipping names already held, so about N names are held in steady state (Persson & Selander and Reasonable Deviations used 2 per month = 24 names).
- **Annual rebalance variant:** one date per year, hold 12 months. Compute it for **all 12 possible start months** and report the mean and the range (this range is the "date luck" and is probably large).
- Weights: equal dollars at purchase, buy-and-hold drift inside a sleeve; sleeves equal-weighted monthly. Also report a capped value-weighted version for the top-N as a size-sensitivity check (Schwartz & Hanauer use it).
- Delistings: if a held name stops trading before 12 months, hold the last price in cash if the exit was a merger/acquisition (common among cheap stocks); otherwise apply a delisting return assumption (Section 6.6).

### 6.3 Costs
Report gross and net. One-way cost grid: 0, 10, 25, 50, and 100 bps (the 100 bps case approximates a flat $25-per-trade commission on $2,500-$3,750 positions; commission amount unconfirmed) (Kreft uses 50 bps one-way as conservative; Davydov uses 0.5%; Martin used 5 bps slippage). Default: 10 bps for >= $1B tiers, 25 bps for the $50M tier; apply to every buy and sell. Turnover is roughly 100%/yr for annual rebalance, lower if names persist.

### 6.4 Benchmarks (use several, report all)
1. S&P 500 total return (SPY or ^SP500TR).
2. **Equal-weight universe benchmark**: all eligible stocks of the same tier, equal-weighted, rebalanced on the same monthly-sleeve schedule (the like-for-like size/value-neutral comparison; MF equal-weight top-N has a size tilt).
3. Size-matched ETFs by tier: $50M tier vs Russell 2000 (IWM) and Russell 3000 (IWV); $1B tier vs Russell 1000 / S&P MidCap 400 (IJH); $5B tier vs S&P 500 and equal-weight S&P 500 (RSP). Use Adj Close.
4. **Random-portfolio test:** 1,000 draws of N random names from the same eligible universe on the same schedule; report the percentile of the MF result. Cheap and very informative given the heavy overlap and tilts.
5. Factor regressions using Ken French's monthly factors (Mkt-RF, SMB, HML, RMW, CMA, Mom; free data library): alpha, loadings, Newey-West t-stats. Kreft and Persson & Selander both use this.

### 6.5 Metrics
CAGR, annualised volatility, Sharpe (risk-free: 13-week T-bill, ^IRX is already in the repo's data), Sortino, max drawdown, worst 12-month return, hit rate vs each benchmark over rolling 12/36 months (Greenblatt's headline stats), turnover, number of holdings, average market cap, sector concentration, yearly table, and the split into first half / second half (2011/12-2018, 2019-2026) given the documented decay. With roughly 14 years of data and an annualised tracking error of about 8%, the standard error on average excess return is about 2% a year, so only excess returns above roughly 4% a year can be distinguished from zero; say this explicitly. [illustrative, U]

### 6.6 Survivorship and other biases
- **yfinance has no (or incomplete) data for delisted tickers.** Measure, per tier and year, the share of PIT-eligible EDGAR filers with no usable price history; report it. Bound the bias with scenarios: (i) drop them (optimistic); (ii) assume a -30% terminal return for names that vanish without an identifiable acquisition (the common convention from Shumway 1997; Nasdaq performance delistings were worse in Shumway & Warther 1999; both from memory, not re-verified here [U]); (iii) assume -100% for the missing share of the bottom size tier as a stress case. Bias is smaller for the $1B and $5B tiers (most delistings are takeovers at a premium) and larger for $50M.
- Look-ahead: avoided by `filed` dates; verify with a leakage test (re-run with an extra 30-day lag; results should change only slightly).
- Restatements: PIT rule uses the version known then.
- Data-snooping: the grid is 36 cells; Section 7 requires reporting all of them and judging by the median across the grid, not the maximum.
- Backtest start cannot precede about 2011/2012 (Section 5.3). Everything is post-publication; we cannot confirm or refute Greenblatt's 1988-2004 numbers. Alternatives for earlier data (CRSP/Compustat via WRDS, Sharadar, Norgate) are paid or institutional; a school or university library might provide WRDS access (unverified).

---

## 7. Parameter grid

### 7.1 Core grid (36 cells = 2 x 3 x 2 x 3)

| Dimension | Values |
|---|---|
| Portfolio size N | 20, 30 |
| Minimum market cap | $50M, $1B, $5B |
| Holding scheme | annual rebalance (averaged over the 12 start months), 12 monthly staggered sleeves |
| Ranking | MF combined (ROC rank + EY rank), EY only (EBIT/EV), ROC only |

Run each cell gross and net of costs. Primary cell (declare before looking at results): **MF combined, N = 30, $1B floor, staggered monthly, net of 10 bps per side**. Keep the $50M tier in the grid because the team doc and Greenblatt's 30.8% use it, but expect it to carry the survivorship and liquidity risk and the largest headline numbers.

### 7.2 One-factor-at-a-time robustness (around the primary cell, not a full cross)
- Excess cash: primary, all cash, 2x current-ratio rule (3 values).
- EBIT: OperatingIncomeLoss vs pre-tax + interest expense (2).
- Earnings window: TTM vs last fiscal year (2).
- NWC floor on/off; Capital floor 0.5% / 1% / 2% / none (4).
- Lease treatment: operating (primary) vs lease-capitalised (2).
- Costs: 0 / 10 / 25 / 50 / 100 bps one-way (5).
- Quality leg alternative: gross profit / total assets (Novy-Marx; Blackburn & Cakici) instead of ROC (1).
- Price floor $5 vs none; liquidity filter on/off (2).
- Start/end sub-periods (2-3 splits), and "excluding 2020" as a sanity check.

### 7.3 What would count as evidence for using MF live
Not a single number: require (a) net CAGR above the equal-weight same-universe benchmark in the primary cell, (b) the MF combined result in the top half of the random-portfolio distribution, (c) positive sign in at least ~70% of the 36 grid cells and in both halves of the sample, (d) alpha t-stat above 2 after Fama-French 5 + momentum for at least the $1B tier. If these fail, say so in the write-up; the literature above makes failure plausible.

---

## 8. Live signals for Wed 2026-10-21

### 8.1 Which inputs need current market data
| Input | Source | Freshness |
|---|---|---|
| Price | yfinance last close (run the final screen after the 2026-10-20 close; fresh prices matter only for MarketCap/EV and thus EY) | live |
| Shares outstanding | Latest `dei:EntityCommonStockSharesOutstanding` (cover page, up to ~4 months old) cross-checked against yfinance `sharesOutstanding`/`marketCap`; for multi-class companies sum the classes or use yfinance `marketCap` and flag; adjust for splits since the cover date | semi-live |
| Debt, cash, preferred, NCI, CA, CL, PP&E | Latest filed 10-Q/10-K on or before the signal date | stale by construction (balance-sheet date to ~4.5 months) |
| EBIT TTM | FY + YTD - prior YTD from the latest filings | stale by construction |
| SIC, exchange, filer category | EDGAR submissions | static |

Only price (and a few share counts) is truly live; EV is therefore a hybrid of today's equity value and a months-old balance sheet. That is also how Compustat-based screens (including magicformulainvesting.com: "financial data updates quarterly") work. [P]

### 8.2 Stale quarterly data on 2026-10-21
- Calendar-year companies: the latest balance sheet is the 2026-06-30 quarter (10-Qs were due by about 2026-08-10 for large/accelerated filers and 2026-08-14 for others), so data is about 113 days old; a few early reporters will already have filed Sept-quarter 10-Qs. Non-December year-ends are mixed (for example Apple's latest is 2026-06-27, filed 2026-07-31 [D]).
- Q3 earnings season is just starting: most companies will report within the next 3-5 weeks, so EBIT can change materially right after purchase. Record "expected next earnings date" (yfinance calendar) and report how many picks report within 14 days. Greenblatt's approach ignores this; treat it as a risk note, not a rule.
- Staleness rules: use the most recent filing with `filed` <= signal date; compute age = signal date - balance-sheet end; flag > 150 days; drop > 200 days (delinquent filers or missing data). Do not mix periods between tags (Section 5.3 item 5).
- Because the formula uses 12-month earnings and ranks are rough, take the top 40-50 ranked names as a candidate list and apply a documented manual review (restatements, going-concern language, pending mergers, one-off gains in EBIT, custom-tag debt, reverse-merger or SPAC-like issuers, extremely high EY, say above 40%). magicformulainvesting.com's own FAQ allows removing stocks for any reason while keeping at least 20. [P]
- Sanity cross-check: the team can register on magicformulainvesting.com (free; I did not create an account) and compare its top 30 at the same minimum market cap with our list; expect partial overlap (different data vendor and "slight accounting adjustments").

### 8.3 Fit with the competition
- Buying 5-7 names every 2-3 months (the book's schedule) does not fit a trading window that ends 2026-11-06 (13 trading days after Oct 21, per `research/07_competition_rules.md`, which cites official 2026-27 Wharton pages; I did not re-verify). Practical choice: buy the whole list on Oct 21 (or over Oct 21-23) and describe the 12-month staggered schedule in the IPS as the intended long-run process; the backtest's annual-rebalance start-month range quantifies the date risk of buying everything at once.
- Rules to respect (same note; 2026-27 specifics are partly unconfirmed there): stocks priced at $5 or more (2025-26 rule; comply anyway), US-listed common stock searchable in WInS, no margin/shorting. Sleeve size is roughly $75,000 (25% of $300,000), so 20-30 names means about $2,500-$3,750 per position; liquidity is not a constraint, but a reported $25-per-trade commission (third-party, unconfirmed) would be about 0.7-1.0% per side at that size, so run the cost grid up to 100 bps one-way for the live-implementation case and prefer fewer, larger positions (the note itself suggests 12-25 stocks).
- Over a 13-trading-day window the Magic Formula is a noisy bet on "cheap and profitable"; present it as a process, not a forecast.

---

## 9. Not verified / open items

1. Greenblatt's book text: exact footnote wording for net working capital, excess cash, minority interest and the treatment of negative EBIT/NWC was not accessible. Two independent secondary sources say excess cash is undisclosed.
2. Gray & Carlisle book tables and Alpha Architect pages (403): EBIT/TEV 14.55% vs EBITDA/TEV 13.72% (1964-2011), the 12.79% vs 15.31% comparison, and Alpha Architect's 2011 replication numbers are relayed by snippets and a blog (Greenbackd).
3. Schwartz & Hanauer (2024) SSRN paper was blocked (403); quantitative claims come from Quantpedia, CXO, and quant-investing.com summaries (the last is a vendor).
4. Larkin (2009) identified as Patrick J. Larkin, JBER; the PDF was password-protected, so figures come from the CXO Advisory summary. Blij (2011) not found; Olin (2011) content not retrieved; Davydov et al., Max & Svanberg, Sistonen, Vestre & Wikheim, Alberg & Seckler are from the Poznan literature review, not originals.
5. XBRL phase-in dates come from law-firm summaries, not the SEC release.
6. The 2010-edition figures (19.7% for the 1,000 universe; S&P 9.5% vs 9.6%) differ across sources.
7. Shumway delisting-return conventions cited from memory.
8. 2026-27 Wharton trading rules: I did not verify them myself; I rely on `research/07_competition_rules.md` (trading window 2026-09-28 to 2026-11-06, $300,000 cash, $5 minimum price unconfirmed for 2026-27, commission unconfirmed). Re-read the WInS rules panel before ordering.
9. Tag coverage statistics are for Dec-2025 and Dec year-end filers; early years (2011-2014) have different tag mixes (for example pre-2019 capital-lease tags: `CapitalLeaseObligationsCurrent` 682 and `CapitalLeaseObligationsNoncurrent` 675 filers at Dec 2011). Re-run the coverage script on each backtest year before trusting a fallback chain.
10. Suggested next step: build the PIT fundamentals table for Dec 2025 first and compare a handful of names by hand against 10-Qs before scaling.

---

## 10. Sources

Primary [P]
- Magic Formula Investing, FAQ: https://www.magicformulainvesting.com/Home/Faqs
- Magic Formula Investing, How it Works: https://www.magicformulainvesting.com/Home/HowItWorks
- Magic Formula Investing, About the Book / home: https://www.magicformulainvesting.com/Home/AboutTheBook , https://www.magicformulainvesting.com/
- SEC, EDGAR APIs (frames, companyfacts, bulk zips): https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- SEC, Accessing EDGAR Data (10 requests/second, User-Agent): https://www.sec.gov/search-filings/edgar-search-assistance/accessing-edgar-data
- SEC XBRL data pulled 2026-10-18: https://data.sec.gov/api/xbrl/frames/ , https://data.sec.gov/api/xbrl/companyfacts/ , https://data.sec.gov/submissions/ , https://www.sec.gov/files/company_tickers_exchange.json
- Wharton Global Youth, investment competition: https://globalyouth.wharton.upenn.edu/investment-competition/about , https://globalyouth.wharton.upenn.edu/?p=16670 (both state trading starts 2026-09-28 and that detailed trading requirements go to registered teams)
- Sibling team note with the official 2026-27 trading window, cash and rules (not re-verified by me): research/07_competition_rules.md

Secondary [S]
- Persson & Selander (2009), Back testing "The Magic Formula" in the Nordic region, SSE: https://arc.hhs.se/download.aspx?MediumId=769
- Kreft (2022), Unravelling the magic of Magic Formula investing, Erasmus: https://thesis.eur.nl/pub/65582/MasterThesis_MartijnKreft_474788.pdf
- Gray & Vogel (2012), Analyzing Valuation Measures, JPM Fall 2012: https://alphaarchitect.com/wp-content/uploads/2022/11/AAJPMFall12AnalyzingValuationMeasures.pdf
- Martin (2020), A critical look at Greenblatt's Magic Formula: https://reasonabledeviations.com/2020/06/08/greenblatt-magic-formula/
- AAII (2006), The Magic Formula Approach to Stockpicking: https://www.aaii.com/journal/article/the-magic-formula-approach-to-stockpicking ; AAII, Magic Formula stocks (screen definitions): https://www.aaii.com/journal/article/magic-formula-stocks
- CFA Institute review of Quantitative Value: https://blogs.cfainstitute.org/insideinvesting/2013/05/16/quant-magic-a-book-review-of-quantitative-value-by-wesley-gray-and-tobias-carlisle
- Greenbackd, Magic Formula tag (Quantitative Value comparisons, Montier): https://greenbackd.com/tag/magic-formula/
- CXO Advisory, Larkin (2009) summary: https://www.cxoadvisory.com/?p=2290 ; Larkin paper: https://www.clutejournals.com/index.php/JBER/article/view/2287
- CXO Advisory, Blackburn & Cakici summary: https://www.cxoadvisory.com/?p=29765 ; JOIM: https://joim.com/the-magic-formula-value-profitability-and-the-cross-section-of-global-stock-returns
- Poznan University literature review (Podgorski): https://journals.ue.poznan.pl/REF/article/view/2790
- Wikipedia, Magic formula investing (reference list): https://en.wikipedia.org/wiki/Magic_formula_investing
- Saber Capital / Huber on ROC: https://sabercapitalmgt.com/thoughts-on-return-on-capital-and-greenblatts-magic-formula-part-1/
- Quant-investing glossary, excess cash: https://www.quant-investing.com/glossary/excess-cash ; Magic Formula guide: https://www.quant-investing.com/blog/magic-formula-complete-guide/ ; US 2000-2022 backtest summary: https://www.quant-investing.com/blog/magic-formula-performance-backtest-2000-2022 ; investment strategy back test (Eurozone, vendor): https://quant-investing.com/blog/magic-formula-investment-strategy-back-test
- Quantpedia on Schwartz & Hanauer: https://quantpedia.com/out-of-sample-test-of-formula-investing-strategies/ ; CXO: https://www.cxoadvisory.com/strategic-allocation/extended-tests-of-four-popular-stock-screening-strategies ; SSRN (403): https://papers.ssrn.com/sol3/papers.cfm?abstract_id=5043197
- Postma (2015) Benelux: https://www.quant-investing.com/media/ax3ae4ig/magic-formula-investing-in-the-benelux-pim-postma.pdf
- ShareScope (2023): https://knowledge.sharescope.co.uk/2023/10/18/time-to-move-on-from-magic-formula-investing/
- Filing deadlines (SEC form 10-Q page and law-firm summaries): https://www.sec.gov/answers/form10q.htm
- XBRL phase-in (law-firm summaries of SEC Release 33-9002): https://www.willkie.com/publications/2009/02/sec-issues-final-rules-mandating-xbrl-filings , https://www.bakerdonelson.com/SEC-Adopts-Final-Rules-Interactive-Data-to-Improve-Financial-Reporting-02-10-2009 , https://dwt.com/insights/2009/02/sec-adopts-final-rules-on-xbrl-mandates-use-of-int

Seen only as search snippets or unopened [S*]
- Alpha Architect: https://alphaarchitect.com/quantitative-value-research-a-summary-of-various-value-metrics-1013/ , https://alphaarchitect.com/how-magic-is-the-magic-formula/ , https://alphaarchitect.com/formulaic-investing/
- Lund (Goumas & Kallstrom): https://lup.lub.lu.se/student-papers/record/1604111
- Olin (2011), Aalto: https://epub.lib.aalto.fi/en/ethesis/id/12770
- Daggenvoorde (Erasmus, Dutch stocks): https://thesis.eur.nl/pub/8041/Daggenvoorde,%20S%20%28312929%29.pdf
- Vestre & Wikheim (NHH): https://openaccess.nhh.no/nhh-xmlui/handle/11250/3052180
