# 02 - The QUALITY side of "quality-filtered momentum"

Prepared 2026-10-18 (Sun) for Capital Crew. Scope: formulas, benchmark numbers, factor-data URLs, SEC XBRL tag map, and a testable filter spec.
The momentum side is covered by a separate file. Picks are due Wed 2026-10-21.

Evidence tags used below:
- **[V]** = number or formula read directly in the paper text (or the live web page / live SEC feed) during this session.
- **[S]** = only seen in an abstract or a secondary summary; not verified in the paper itself.
- **[M]** = from my memory / convention, not verified in this session. Check before relying on it.
- **[H]** = heuristic / my own design, not from a paper.

---

## 0. Bottom line (read this first)

1. **Research-backed quality signals exist and are well documented, but they are long-short factor results.** The team's exact sketch ("high gross margins or ROE, low debt, positive earnings") is only partly supported:
   - **Gross profits / assets (GP/A)** is the strongest single profitability signal in Novy-Marx (2013). **Gross margin alone did NOT earn a raw return premium** (high-minus-low gross-margin quintile: +0.01 %/month, t = 0.13; Table A.4 [V]), and **earnings/book-equity (ROE-like) added nothing once GP/A was in the regression** (0.08, t = 0.31; Table 1 [V]). So "gross margin OR ROE" is weaker than "GP/A".
   - **"Low debt"** is a component of AQR's *Safety* score (LEV, Z-score, O-score, earnings volatility, beta) [V], not a separately validated screen. **"Positive earnings"** has indirect support (loss-making/failure-prone firms sit in the junk decile; Novy-Marx finds low profitability drives the failure-probability and O-score anomalies [V]) but no standalone test in the papers I read.
   - **Net debt/EBITDA < 3** is a team heuristic (no paper); keep it as a labelled heuristic arm.
2. **Quality as an overlay on momentum has only indirect evidence.** The best direct number I found: Novy-Marx & Velikov (2016) rank-sum of value + momentum + gross profitability earned 0.99 %/month net of trading costs (t = 5.18) versus 0.51 %/month (t = 2.67) for value + momentum alone [V, Aug-2015 working-paper version, long-short, includes value]. Profitability is roughly orthogonal to momentum (profitability factor's UMD loading +0.05, t = 4.56: statistically significant but economically small; QMJ's UMD loading -0.09 [V]). There is NO paper I could verify showing a hard quality filter reduces *long-only* momentum crashes. Daniel-Moskowitz show crashes come from the short (loser) leg rebounding [V], which a long-only team does not hold. Details in section 5.
3. **A backtest on EDGAR data cannot prove the filter helps** (about 15 years of usable data, top-5/10 portfolios; see the power note in section 8). Use the literature for the prior and the backtest for implementation sanity, robustness across neighboring parameters, and regression checks against Fama-French / AQR factors.
4. **Recommended primary arms** (details in section 7): `Q1` = GP/A percentile filter (top 50% / top 30%, optionally industry-adjusted); `Q2` = "QMJ-lite" composite z-score (profitability + safety pieces computable from EDGAR) above median; `Q5` = "junk veto" (drop only the bottom 30% on QMJ-lite). Team heuristic `Q3` (NI > 0, leverage cap, margin/ROE vs sector) is run as a comparator, and `Q4` is a soft rank blend of momentum and GP/A.
5. **Biggest implementation risk is XBRL data plumbing**, not the finance. In a scan of 96 large SEC registrants, only 35% had a `GrossProfit` tag and ~37% had neither `GrossProfit` nor a COGS tag (about 18% of the US-GAAP non-financials). Stale tags, tag migrations, YTD cash-flow facts and ticker-to-CIK changes all bit in my own test run (section 6). A working point-in-time reference implementation is in Appendix A.
6. **Regime warning (live data):** Ken French's library page shows the profitability factor RMW at **-4.08% in Aug 2026 and -16.44% over the last 12 months**; "Big Weak" returned +26.85% vs "Big Robust" +18.10% over the same 12 months (page parsed by a fetch tool, column alignment inferred; re-check on the page). A quality tilt has been a headwind lately; that does not invalidate the long-run evidence but the team should expect to be asked about it.

---

## 1. Provenance: what I actually read

| Source | Version actually read | How |
|---|---|---|
| Novy-Marx (2013) JFE 108(1):1-28 | **June 2012 working-paper PDF** ("The Other Side of Value: The Gross Profitability Premium"), full text including tables and appendix. The published JFE text was not accessible; numbers may differ slightly. | PDF text extraction [V] |
| Novy-Marx (2015) "Fundamentally, Momentum is Fundamental Momentum" | NBER WP 20984 (Feb 2015), intro + Table 1 | [V]; I did not find a journal version |
| Novy-Marx & Velikov (2016) RFS 29(1):104-147 | August 2015 working-paper PDF, Tables 3-4, appendix B | [V] |
| Asness, Frazzini, Pedersen (2019) RAST 24(1):34-112 | Published open-access version (CBS repository PDF), Sections 3-6 + Appendix 1 | [V] |
| Fama & French (2015) JFE 116:1-22 | Full PDF copy (22 pages) | [V] |
| Daniel & Moskowitz (2016) JFE 122(2):221-247 | NBER WP 20439, abstract + intro | [V] |
| Avramov et al. (2007), Bhootra (2018), Bandarchuk & Hilscher (2013), Ball et al. (2015/2016), Hou-Xue-Zhang (2020), Piotroski-So (2012) | abstracts / search summaries only | [S] |
| AQR dataset pages, Ken French data-library pages, Novy-Marx data-library pages, SEC API docs | live web pages fetched 2026-10-18 | [V] for what the page says; file layouts not verified (I did not download the data files) |
| SEC EDGAR `companyfacts` / `submissions` JSON | live API, queried 2026-10-18 with User-Agent "CapitalCrew Student Research Project research@capitalcrew-project.org" | [V] empirical tag-coverage tests below |

---

## 2. Novy-Marx (2013) "The Other Side of Value: The Gross Profitability Premium"

Links: JFE abstract page <https://www.sciencedirect.com/science/article/abs/pii/S0304405X13000044>; DOI 10.1016/j.jfineco.2013.01.003; working paper read <https://www.johnhcochrane.com/s/Novy_marx_OSoV.pdf> (redirects to a squarespace copy); earlier NBER draft <https://www.nber.org/papers/w15940>.

### 2.1 Exact definitions [V]

- **Gross profits** = total revenue minus cost of goods sold = Compustat `REVT - COGS` (also available as Compustat `GP`). Compustat COGS "represents all expenses directly related to production, including the cost of materials and direct labor, amortization of software and capital with a useful life of less than two years, license fees, lease payments, maintenance and repairs, taxes other than income taxes, and expenses related to distribution and warehousing, and heat, lights, and power" (footnote 2).
- **GP/A = (REVT - COGS) / AT**, where AT = total assets. The paper writes it this way in Table 2 and Table A.1 with no lagging or averaging (averaging total assets appears only for Sloan accruals). So: *same-fiscal-year total assets, end of year*, as written.
- Why assets, not equity: "gross profits are an asset level measure of earnings. They are not reduced by interest payments, and are thus independent of leverage."
- Other profitability variables used for comparison: earnings = `IB` (income before extraordinary items) scaled by *book equity*; free cash flow = `NI + DP - WCAPCH - CAPX` scaled by book equity; EBITDA/AT; XSGA/AT; asset turnover = `REVT/AT`; gross margin = `(REVT - COGS)/REVT`.
- Book equity (for B/M): `SEQ` if available, else `CEQ + PSTX`, else `AT - LT`; plus deferred taxes (`TXDITC`), minus preferred (`PSTKR`, else `PSTKRL`, else `PSTK`). Market equity for B/M is lagged six months to avoid taking unintended momentum positions.

### 2.2 Timing, universe, sorts [V]

- Compustat from 1962 (AMEX inclusion). "I ... employ accounting data for a given fiscal year starting at the end of June of the following calendar year." So FY ending in calendar year t-1 is used from end of June t until end of June t+1 (stale by 6 to 18 months). Asset-pricing tests cover **July 1963 to December 2010**.
- **Financials excluded** (one-digit SIC = 6, i.e. SIC 6000-6999), "though retaining financials has little impact on the results" for the Fama-MacBeth tests. For the quintile sort, including financials cuts the H-L raw spread to 0.25 %/mo (t = 1.82) but raises the FF3 alpha to 0.61 %/mo (t = 5.62), because most financials land in the lowest GP/A quintile (footnote 4).
- Variables in Fama-MacBeth regressions are trimmed at the 1st and 99th percentiles.
- Sorts: **quintiles on NYSE breakpoints**, value-weighted, rebalanced each end of June. Factor construction (PMU) uses the Fama-French style 2x3: size split at NYSE median, profitable/unprofitable = top/bottom 30% of GP/A (NYSE breaks).
- Quarterly version (appendix A.4): `(REVTQ - COGSQ)/ATQ` (data from 1972), refreshed monthly using the latest quarter, assumed available at the end of the month after the earnings report date (`RDQ`). It earned about twice as much: PMU-high-frequency 0.63 %/mo (t = 3.73) vs annual PMU 0.33 %/mo (t = 2.06) over Jan 1972-Dec 2010 (Table A.6). Novy-Marx deliberately uses the annual measure for his main tests because the quarterly one mixes in earnings-surprise (PEAD) effects.

### 2.3 Key results [V]

Table 2, Panel A: value-weighted portfolios sorted on GP/A (NYSE quintiles, July 1963-Dec 2010, ex-financials). Excess returns and FF3 alphas in % per month, t-stats in brackets:

| GP/A quintile | avg GP/A | avg B/M | excess return | FF3 alpha | HML loading |
|---|---|---|---|---|---|
| Low | 0.10 | 1.10 | 0.31 [1.65] | -0.18 [-2.54] | +0.15 |
| 2 | 0.20 | 0.98 | 0.41 [2.08] | -0.11 [-1.65] | +0.20 |
| 3 | 0.30 | 1.00 | 0.52 [2.60] | +0.02 [0.27] | +0.12 |
| 4 | 0.42 | 0.53 | 0.41 [1.94] | +0.05 [0.83] | -0.24 |
| High | 0.68 | 0.33 | 0.62 [3.12] | +0.34 [5.01] | -0.29 |
| **High - Low** | | | **0.31 [2.49]** | **0.52 [4.49]** | **-0.44 [-10.8]** |

- For comparison the book-to-market sort: H-L 0.41 [2.95], FF3 alpha -0.06 [-0.71]. Spearman rank correlation of GP/A with B/M is -0.18.
- The long (high-GP/A) leg carries 0.34 of the 0.52 %/mo FF3 alpha (about 65%); the short leg carries -0.18.
- Fama-MacBeth (Table 1, July 1963-Dec 2010, slopes x10^2 = % per month per unit of the variable): GP/A alone **0.75 [5.49]**, comparable in significance to log(B/M) 0.35 [5.98]; momentum r(12,2) 0.76 [3.87]. Earnings/BE 0.22 [0.84]; FCF/BE 0.27 [2.28]. With GP/A and earnings together: GP/A 0.69 [5.22], earnings 0.08 [0.31]. **GP/A subsumes earnings and mostly subsumes FCF.** Industry-demeaned GP/A (Fama-French 49 industries) is stronger: 1.00 [8.99].
- DuPont split (Tables A.3, A.4): GP/A = asset turnover x gross margin. Both have some power alone, but **neither has power once GP/A is included**. Sorting on asset turnover: H-L 0.34 [2.51] raw. **Sorting on gross margin: H-L +0.01 [0.13] raw**, FF3 alpha 0.37 [4.35]. "High asset turnover primarily drives the high average returns of profitable firms, while high gross margins are the distinguishing characteristic of 'good growth' stocks."
- Persistence: GP/A predicts growth in gross profits, earnings, FCF and payouts at 3- and 10-year horizons (Table A.7).
- Controls: GP/A keeps its power after controlling for accruals and R&D/market (Table A.5: GP/A 0.85 [5.21] alone, 0.68 [3.59] with both).

### 2.4 Value interaction ("hedge for value") [V]

- Profitability strategy mean 0.31 %/mo (sd 2.94), value strategy mean 0.41 %/mo (sd 3.27), **correlation -0.57**. Running both: mean 0.71 %/mo, sd 2.89 (lower than either alone despite doubling gross exposure), t = 5.87, **annual Sharpe 0.85 vs 0.34 for the market**; "the strategy is orthogonal to momentum." The 50/50 mix never lost money over any five-year window (Fig. 1).
- Double sorts (Table 6): average value spread across GP/A quintiles 0.68 %/mo (vs 0.41 unconditional); average profitability spread across B/M quintiles 0.54 %/mo (vs 0.31).
- Conditional factors (Table 8, 1963-2010): HML conditioned on GP 0.54 [5.01] vs plain HML 0.40 [3.25]; PMU conditioned on B/M 0.48 [5.35].
- **Large-cap robustness**: among the 500 largest non-financial stocks the profitability spread is 0.27 %/mo [2.33], FF3 alpha 0.40 [3.75] (Table 7A); Sharpe of the large-cap profitability + value 50/50 mix 0.44. Simple combined-rank strategy (GP/A rank + B/M rank, long top 150 / short bottom 150 of 500): 0.62 %/mo [5.11], FF3 alpha 0.37 [3.67], annual Sharpe 0.74; "Only one-third of each side of the strategy turns over each year."

### 2.5 What the 2013 paper says about momentum [V]

- Fama-MacBeth regressions include prior-year return r(12,2) as a control; GP/A and momentum are both significant side by side (t = 5.49 and 3.87).
- Industry-adjusted factors (July 1973-Dec 2010, Table 9): PMU* excess return 0.27 [4.88]; loads on UMD only +0.05 [4.56]; four-factor alpha 0.35 [6.90]. UMD* 0.58 [4.17]. The text calls the profitability factors "essentially orthogonal to momentum."
- The paper does **not** test momentum within profitable firms or a quality filter on momentum.

### 2.6 Follow-ups by the same author

- **Novy-Marx (2015), NBER WP 20984** [V]: earnings momentum (SUE, 3-day earnings-announcement return CAR3) subsumes price momentum in Fama-MacBeth regressions (Jan 1975-Dec 2012); coefficient on r(2,12) falls from 0.59 [2.84] to 0.15 [0.70] once SUE and CAR3 are added. GP/A stays strongly significant alongside: 0.91 [6.82] in the price-momentum-only specification and still 0.75 [5.60] when SUE and CAR3 are added (0.74 [4.17] and 0.77 [3.79] in the 1975-93 and 1994-2012 halves). Earnings-momentum strategies that control for past performance have lower volatility and "none of the negative skew." Take-away for us: a fundamentals-based overlay can matter more than price momentum itself; SUE is computable from EDGAR (needs 8 quarters of YoY EPS changes) and is a candidate extra arm, but it is outside the "quality" brief.
- **Novy-Marx & Velikov (2016), RFS** [V, Aug-2015 WP]: GP/A decile H-L (value-weighted, annual rebalance) gross 0.40 %/mo [2.94], FF4 alpha 0.52 [3.83], average long/short-side turnover 1.96 %/mo, trading costs 0.03 %/mo, **net 0.37 [2.74]**. ValMomProf (rank-sum of B/M, GP/A and 12-1 momentum, monthly): gross 1.43 [7.41], 26.8% monthly turnover, cost 0.43, **net 0.99 [5.18]**; ValMom: gross 0.93 [4.81], net 0.51 [2.67]. With a buy/hold spread the ValMomProf net return is 1.02 %/mo [6.19]. The paper's intro cites McLean-Pontiff's 35% post-publication decay (their 2014 draft number) and Harvey-Liu-Zhu's "t > 3" hurdle. Caveat: long-short, three-signal rank-sum, 1963/1973-2012 sample.

---

## 3. Asness, Frazzini, Pedersen - "Quality Minus Junk" (QMJ)

Links: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2312432>, DOI 10.1007/s11142-018-9470-2, open-access PDF read: <https://research-api.cbs.dk/ws/portalfiles/portal/60211462/lasse_heje_pedersen_et_al_quality_minus_junk_publishersversion.pdf>. The authors are at AQR (the paper's acknowledgment says AQR "may or may not apply similar investment techniques"); worth one line in the "why" write-up as a source-independence note.

### 3.1 Standardization [V]

Each month, for each variable x, rank cross-sectionally (ascending, so "better" = higher) and standardize the *ranks*:

```
r_i  = rank(x_i)                       (cross-section, each date)
z(x) = (r - mean(r)) / std(r)          (mean and std of the ranks across stocks)
```
Equal-weights across measures; the same `z(.)` is applied again when aggregating. If a measure is missing, "we simply average the remaining ones." Using ranks limits outlier influence.

### 3.2 Components [V] (Appendix 1; variable names are CRSP/Compustat)

**Profitability** = z( z_gpoa + z_roe + z_roa + z_cfoa + z_gmar + z_acc )
- GPOA = (REVT - COGS)/AT
- ROE = IB/BE (income before extraordinary items / book equity; BE = shareholders' equity minus preferred)
- ROA = IB/AT
- CFOA = (NI + DP - dWC - CAPX)/AT  (note: this is net income + D&A - change in working capital - capex, i.e. a free-cash-flow measure, not reported CFO)
- GMAR = (REVT - COGS)/SALE
- ACC = -(dWC - DP)/AT, with WC = ACT - LCT - CHE + DLC + TXP (high = low accruals)

**Growth** = z( z_dgpoa + z_droe + z_droa + z_dcfoa + z_dgmar ): five-year change in each *residual, per-share* profitability measure, e.g. [(gp_t - rf*at_{t-1}) - (gp_{t-5} - rf*at_{t-6})] / at_{t-5}; gross margin growth (gp_t - gp_{t-5})/sale_{t-5}; no accruals term.

**Safety** = z( z_bab + z_lev + z_o + z_z + z_evol )
- BAB = minus market beta (Frazzini-Pedersen betas: rolling 1-yr daily volatility times rolling 5-yr 3-day correlation)
- LEV = -(DLTT + DLC + MIBT + PSTK)/AT (minus total debt incl. minority interest and preferred over assets)
- O = -(Ohlson O-score) with Ohlson's printed terms: -1.32 - 0.407 log(ADJASSET/CPI) + 6.03 TLTA - 1.43 WCTA + 0.076 CLCA - 1.72 OENEG - 2.37 NITA - 1.83 FUTL + 0.285 INTWO - 0.521 CHIN; ADJASSET = AT + 0.1(ME - BE); TLTA = (DLC + DLTT)/ADJASSET as printed; OENEG = 1(LT > AT); INTWO = 1(max(IB_t, IB_{t-1}) < 0)
- Z = Altman Z as printed: (1.2 WC + 1.4 RE + 3.3 EBIT + 0.6 ME + SALE)/AT (the paper divides every term by AT; Altman's original uses ME/total liabilities)
- EVOL = std of quarterly ROE over the past 60 quarters (>= 12 non-missing); if quarterly data are missing, std of annual ROE over 5 years (>= 5)

**Quality** = z( Profitability + Growth + Safety ). Payout (EISS, DISS, NPOP) is an optional fourth block in the Appendix (Table 23); the headline QMJ excludes it.

### 3.3 Portfolio construction [V]

- Data: CRSP/Compustat common stocks (SHRCD 10/11), OTC excluded, **financials not excluded** (no exclusion appears in the text I read); US sample June 1957-Dec 2016, 24 developed countries from June 1989 (the paper labels the global start as 1998 in some table headers and 1989 in the text and captions).
- Quality-sorted portfolios: 10 deciles, NYSE breakpoints, value-weighted, **rebalanced monthly**.
- QMJ factor: six portfolios (size split at NYSE median; quality top/bottom 30% breakpoints within each size group): QMJ = 1/2 (Small Quality + Big Quality) - 1/2 (Small Junk + Big Junk).
- Timing: the data section says accounting variables are aligned "at the end of the firm's fiscal year ending anywhere in calendar year t-1 to June of calendar year t" (Fama-French convention), while portfolios are refreshed every calendar month. The paper text I read does not spell out the intra-year update lag used for the monthly portfolios.

### 3.4 Key results [V]

Quality-sorted deciles, US long sample 7/1957-12/2016 (Table 3), % per month:

| | P1 (junk) | P10 (quality) | P10 - P1 |
|---|---|---|---|
| Excess return | 0.28 [1.09] | 0.70 [4.11] | **0.42 [2.56]** |
| CAPM alpha | -0.44 [-3.72] | 0.20 [3.11] | 0.64 [4.26] |
| 3-factor alpha | -0.57 [-6.52] | 0.31 [5.90] | 0.88 [8.23] |
| 4-factor alpha (MKT, SMB, HML, UMD) | **-0.59 [-6.30]** | **0.46 [8.59]** | **1.05 [9.31]** |
| Market beta | 1.28 | 0.92 | -0.36 |
| Sharpe (annual) | 0.14 | 0.53 | 0.33 (info ratio 1.31) |

Global 7/1998(89)-12/2016: P10-P1 0.52 [2.49], 4-factor alpha 0.99 [6.67].

QMJ factor (Table 4), US 7/1957-12/2016: excess return **0.29 %/mo [3.62]**; CAPM / 3F / 4F alpha **0.39 [5.43] / 0.51 [8.90] / 0.60 [9.95]**; Sharpe 0.47; info ratio 1.40; loadings MKT -0.20, SMB -0.26, HML -0.37, **UMD -0.09 [-4.34]**. Components: Profitability 0.25 [3.69] (Sharpe 0.48), Safety 0.23 [2.44] (0.32), Growth 0.17 [2.46] (0.32). Global QMJ 0.38 [3.33], 4F alpha 0.61 [8.07], Sharpe 0.64. Positive in 23 of 24 countries.

Against Fama-French 5 factors (Table 5, US 7/1963-12/2016): 5-factor alpha 0.38 [7.71], 6-factor (adds UMD) 0.33 [6.81]; QMJ loads +0.55 on RMW [24.07]. "Controlling for quality eliminates the alpha of RMW."

Other: QMJ shows flight-to-quality (positive but insignificant convexity in market down-states; quadratic term t = 2.4 for the profitability piece); 63% QMJ / 37% HML is the max-Sharpe mix, and "QARP" (quality at a reasonable price) has Sharpe about 0.7 US / 0.9 global; a low "price of quality" predicts higher future QMJ returns (Table 8).

Observation for a long-only team: in the decile table, **56% of the 4-factor alpha spread (0.59 of 1.05) and 69% of the CAPM alpha spread (0.44 of 0.64) comes from the junk side being bad**, so avoiding junk captures a large share of the effect without shrinking the momentum candidate pool as aggressively as a "top quality only" filter.

### 3.5 AQR data library [V for page content; file layout not verified]

Index: <https://www.aqr.com/Insights/Datasets> (the pages show a date of **July 31, 2026**, so the files run through about mid-2026). All four items carry the description "updated data for the paper 'Quality Minus Junk' (Asness, Frazzini and Pedersen, 2014)". Files are Excel (.xlsx):

| Dataset | Page | File (relative to https://www.aqr.com) |
|---|---|---|
| QMJ: Factors, Monthly | <https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-Factors-Monthly> | `/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Monthly.xlsx` |
| QMJ: Factors, Daily | <https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-Factors-Daily> | `/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Daily.xlsx` |
| QMJ: Six Portfolios Formed on Size and Quality, Monthly | <https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-Six-Portfolios-Formed-on-Size-and-Quality-Monthly> | `.../Quality-Minus-Junk-Six-Portfolios-Formed-on-Size-and-Quality-Monthly.xlsx` |
| QMJ: 10 Quality-Sorted Portfolios, Monthly (long-only deciles) | <https://www.aqr.com/Insights/Datasets/Quality-Minus-Junk-10-QualitySorted-Portfolios-Monthly> | `.../Quality-Minus-Junk-10-QualitySorted-Portfolios-Monthly.xlsx` |

- The Factors files hold long/short QMJ for the US and 23 international markets plus reference global factors, "built from the intersection of six value-weighted portfolios formed on size and quality."
- **Caveat on definition**: the AQR web page says quality is defined with "profitability, growth, safety, and payout" whereas the paper's headline QMJ excludes payout (payout variant in Appendix Table 23). Expect the dataset to differ a little from the paper's numbers; read the NOTES sheet in the file.
- [M] Layout from past use, **not verified**: a few header/notes rows, then a date column (MM/DD/YYYY) and one column per country (`USA`, `Global`, `Global Ex USA`, ...); factor returns in decimals. Open the file once and check before writing a parser.
- **Use for us**: (i) correlate our computed long-short quality score with the `USA` QMJ column; (ii) compare our *long-only* top-quality buckets with the "10 Quality-Sorted Portfolios" P10 series; (iii) use `USA` QMJ as a regressor when testing whether the filter adds anything beyond generic quality. Also note it ends mid-2026, so Sep-Oct 2026 cannot be validated.

---

## 4. Fama & French (2015) "A Five-Factor Asset Pricing Model"

Links: <https://www.sciencedirect.com/science/article/pii/S0304405X14002323>, JFE 116(1):1-22; copy read <https://tevgeniou.github.io/EquityRiskFactors/bibliography/FiveFactor.pdf>.

### 4.1 Definitions [V]

- **Operating profitability, OP** (June of year t uses fiscal year ending in t-1) = **(annual revenues - cost of goods sold - selling, general and administrative expenses - interest expense) / book equity at the end of fiscal year t-1**. They note "we call this variable operating profitability, OP, but it is operating profitability minus interest expense."
- **Investment, Inv** = (total assets at end of FY t-1 - total assets at end of FY t-2) / total assets at end of FY t-2 (asset growth). Replications with book-equity growth give similar results; asset-growth sorts give slightly larger spreads.
- **Timing/universe**: sorts at the end of each June; B/M uses book equity of FY t-1 and market cap at end of December t-1; NYSE, AMEX, NASDAQ common stocks (share codes 10/11) on CRSP and Compustat; breakpoints from NYSE stocks only. Data-library page adds: positive book equity required for SMB/HML/RMW; revenues plus at least one of COGS/SG&A/interest expense must be non-missing for RMW; total assets for t-2 and t-1 for CMA.
- **Factor construction (2x3, the version on the data library)**: size split at NYSE median; OP and Inv groups at NYSE 30th/70th percentiles.
  - RMW = (Small Robust + Big Robust)/2 - (Small Weak + Big Weak)/2
  - CMA = (Small Conservative + Big Conservative)/2 - (Small Aggressive + Big Aggressive)/2
  - HML = (Small High + Big High)/2 - (Small Low + Big Low)/2; SMB = average of the three size spreads (B/M, OP, Inv).
  - Value-weighted portfolios, rebalanced annually in June.
- **Model**: R_it - RF_t = a_i + b_i (RM-RF) + s_i SMB + h_i HML + r_i RMW + c_i CMA + e_it.

### 4.2 Benchmark numbers [V] (Table 4, July 1963-Dec 2013, 606 months, 2x3 factors, % per month)

| Factor | Mean | Std dev | t-stat |
|---|---|---|---|
| Rm-Rf | 0.50 | 4.49 | 2.74 |
| SMB | 0.29 | 3.07 | 2.31 |
| HML | 0.37 | 2.88 | 3.20 |
| **RMW** | **0.25** | 2.14 | **2.92** |
| **CMA** | **0.33** | 2.01 | **4.07** |

- With the other four factors in the regression, HML "seems to become redundant" (the authors caution this "may be specific to this sample"). The main model failure is small stocks that behave like high-investment, low-profitability firms.
- The profitability effect is evident in every size quintile; among megacaps average returns rise more smoothly across OP quintiles.
- RMW's correlation with HML is only 0.08 in the 2x3 version; with CMA 0.11 (Table 4C).

### 4.3 Ken French data library files [V for names/URLs from the library page]

Library: <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html> (latest month on the page: **August 2026**; "Beginning with the January 2025 data release, we use the new ... CIZ files"). Page for the 5 factors: <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_5_factors_2x3.html> (monthly July 1963-Aug 2026; annual 1964-2025).

| Data | Zip URL (as listed on the library page, http) |
|---|---|
| 5 factors 2x3, monthly | `http://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_CSV.zip` |
| 5 factors 2x3, **daily** | `http://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Research_Data_5_Factors_2x3_daily_CSV.zip` |
| Momentum factor (Mom), monthly | `http://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/F-F_Momentum_Factor_CSV.zip` |
| Momentum factor, daily | `.../ftp/F-F_Momentum_Factor_daily_CSV.zip` [M, same naming pattern] |
| 49-industry SIC definitions | `.../ftp/Siccodes49.zip` (relative link `../ftp/Siccodes49.zip` on <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_49_ind_port.html>) |

- Mom: 2x3 on size (NYSE median) and prior (2-12) return (NYSE 30/70 breakpoints), value-weighted, formed monthly [V per `det_mom_factor.html`].
- pandas-datareader dataset names [M]: `F-F_Research_Data_5_Factors_2x3`, `F-F_Research_Data_5_Factors_2x3_daily`, `F-F_Momentum_Factor`, `F-F_Momentum_Factor_daily`.
- [M] CSV layout (unverified, check once): a few text header lines, then rows `YYYYMM` (monthly) or `YYYYMMDD` (daily) with columns `Mkt-RF, SMB, HML, RMW, CMA, RF` **in percent**; the monthly file has an "Annual Factors" block after a blank line; missing = -99.99. Divide by 100 before regressing.
- Novy-Marx also posts his factors: PMU etc. at <https://mysimon.rochester.edu/novy-marx/data_lib/OSoV/index.html> (`pmu.xlsx`, `Ind_adj_fac_ret.xlsx`, `Intra_ind_fac_ret.xlsx`; the construction page says July 1963-Dec 2012, so only useful for overlap with our 2009+ data and for checking our GP/A factor definition; layout not verified).

### 4.4 Alpha-regression spec for our strategies

```
(r_p,t - RF_t) = a + b1 (Mkt-RF) + b2 SMB + b3 HML + b4 RMW + b5 CMA + b6 Mom + e      (monthly; daily for crash analysis)
```
Report a with Newey-West standard errors (e.g. 6 monthly lags; 5-10 daily lags [H]). Do the same for the *difference* portfolio (filtered top-N minus unfiltered top-N) to isolate what the filter adds; expect a positive RMW (and QMJ) loading and a roughly unchanged Mom loading if the filter works as intended.

---

## 5. Does quality improve momentum? Evidence ledger (honest version)

| # | Evidence | What it says | Strength for our use |
|---|---|---|---|
| 1 | Novy-Marx & Velikov (2016) [V, Aug-2015 WP]: rank-sum of B/M + GP/A + momentum vs B/M + momentum | Net 0.99 vs 0.51 %/mo (t 5.18 vs 2.67); best net-of-cost strategy in a 23-anomaly study | Moderate: direct combination of profitability with momentum, but long-short, three signals, includes value (profitability also hedges value, which may drive part of it) |
| 2 | Novy-Marx (2013) [V] | Profitability factor "orthogonal to momentum"; PMU* UMD loading +0.05; GP/A and r(12,2) both significant in Fama-MacBeth | Moderate: supports using both signals (diversification); not a test of a filter |
| 3 | Novy-Marx (2015) [V] | GP/A stays significant alongside price momentum and earnings surprises; earnings momentum subsumes price momentum; controlling for past performance removes earnings-momentum crashes | Moderate for "fundamentals matter"; says nothing about quality filtering of price momentum |
| 4 | QMJ [V] | Quality has low/negative beta, UMD loading -0.09, positive convexity in down markets; junk decile 4F alpha -0.59 | Moderate/indirect: suggests quality should reduce market-panic damage, but not tested within a momentum portfolio |
| 5 | Daniel & Moskowitz (2016) [V] | Crashes occur in "panic" states (after market declines, high vol, as markets rebound). 1932: losers +232% vs winners +32% (Jul-Aug); Mar-May 2009: market +26%, **losers +163%, winners only +8%**. "They are a crash where the short side of the portfolio - the losers - are 'crashing up'." Loser decile was highly levered and option-like | Strong on mechanism; **implication: a long-only winners portfolio avoids the worst of the crash**. Its risk is lagging a junk-led rebound (winners were defensive firms in 2009), and a quality filter would tilt even more defensive. Do not sell the filter as "crash protection" |
| 6 | Avramov, Chordia, Jostova, Philipov (2007) JF [S] | Momentum profits are concentrated in low-credit-rated firms (reported 2.35%/mo for worst tercile vs insignificant 0.27% for best); losers dominate | Cuts against a hard quality filter for *long-short* momentum; for long-only winners the effect on the winner leg is unclear. Treat as a reason to test, not as a result |
| 7 | Bhootra (2018) Managerial Finance [S, abstract] | Independent double sorts on GP/A x momentum; combined strategy reported as superior ("2.75x" momentum alone, metric unnamed) | Weak: paywalled, couldn't verify sample, long-only vs long-short, or costs |
| 8 | Bandarchuk & Hilscher (2013) RoF [S] | Gains from conditioning momentum on firm characteristics largely vanish after controlling for the *extremity of past returns* | Warning: when you filter on quality, check whether you are really just changing how extreme the past returns are. Include "past-return z-score of holdings" in diagnostics |
| 9 | Hou, Xue, Zhang (2020) RFS [S]; McLean-Pontiff (2016) JF [S/V via NM&V intro] | Most anomalies shrink or fail replication once microcaps are handled; published anomalies decay after publication (35% in the 2014 draft, quoted by NM&V; the final JF numbers may differ) | Prior should be shaded down: expect smaller effects than the 1963-2010 samples |
| 10 | Ball, Gerakos, Linnainmaa, Nikolaev (2015 JFE; 2016 JFE) [S] | Cash-based "operating profitability" (excludes accruals; subtracts SG&A) predicts returns more strongly than GP/A and subsumes accruals | Supports adding SG&A-adjusted and cash-based profitability to the composite (QMJ already includes CFOA and ACC) |
| 11 | Piotroski & So (2012) RFS [S] | F-score helps within value/glamour classification | Not a momentum paper; skip as support for this strategy |
| 12 | Ken French library [V] | RMW -16.44% over the last 12 months to Aug 2026 | Regime caution (see section 0) |

Where this leaves the "why" for the team: *quality (profitability + safety) is a well-documented, mostly independent return source; momentum is another; combining them via ranks is the best-supported design; a hard filter is a reasonable, simpler implementation but is not what any verified paper tested.* Say that plainly in the write-up, and let the backtest show robustness (not "optimality").

---

## 6. SEC EDGAR XBRL: tag map, pitfalls, point-in-time conventions

API facts [V from SEC page and live calls]: `https://data.sec.gov/api/xbrl/companyfacts/CIK##########.json` (all facts for a company), `companyconcept/CIK##########/us-gaap/<Tag>.json`, `frames/us-gaap/<Tag>/USD/CY2019Q1I.json` (one fact per company "using the last filing that best fits" - **not point-in-time, do not use for backtests**), `submissions/CIK##########.json` (metadata incl. `sic`, `sicDescription`, `tickers`, `category`, `fiscalYearEnd`, and per-filing `filingDate`, `reportDate`, `acceptanceDateTime`, `form`). Bulk files updated nightly ~3 a.m. ET: `https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip` and `https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip`. SEC wants a declared User-Agent with contact info and (fair-access policy) at most 10 requests/second [M]; the page itself did not state the rate. Docs: <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>.

Each fact in `companyfacts` has: `start` (flows only), `end`, `val`, `accn`, `fy`, `fp`, `form`, `filed`, and sometimes `frame`.

### 6.1 Tag map (priority order; first available **for that period** wins)

Coverage numbers are from my 2026-10-18 scan of 96 large US-listed SEC registrants with us-gaap facts (the first ~110 entries of SEC's `company_tickers.json`, roughly market-cap order, not random; counts of firms with a 10-K annual value for FY ending >= 2024-06). They include foreign filers and financials, so read them as rough.

| Quantity | Tags (priority order) | Coverage in scan / notes |
|---|---|---|
| Revenue | `RevenueFromContractWithCustomerExcludingAssessedTax`, `Revenues`, `SalesRevenueNet`, `RevenueFromContractWithCustomerIncludingAssessedTax`, `SalesRevenueGoodsNet` (+ `SalesRevenueServicesNet`), banks: `RevenuesNetOfInterestExpense` | 84/96 any tag; 52 use ASC-606 tag, 38 `Revenues`. **Tag migration**: pre-2018 filings use `SalesRevenueNet`; Amazon has no `Revenues`; NVIDIA uses `Revenues` throughout but also `RevenueFromContract...` through FY2022. Coalesce **per period**, never per company |
| COGS | `CostOfGoodsAndServicesSold`, `CostOfRevenue`, `CostOfGoodsSold`, `CostOfServices`, (`CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization`) | 60/96 (41 `CostOfGoodsAndServicesSold`, 19 `CostOfRevenue`). **Never use `CostsAndExpenses`** (= total costs incl. opex; Exxon's only cost tag in my scan, and Meta/Alphabet tag it next to `CostOfRevenue`). Product + service splits without a total (e.g. a company reporting `CostOfGoodsSold` and `CostOfServices` separately) must be summed |
| Gross profit | `GrossProfit` | Only 34/96. Use as the first choice when present *and current*, else REV - COGS. **Stale-tag trap: Costco's `GrossProfit` last appears for FY2019**; my first run used it. Require the same period end as revenue (Appendix A) |
| SG&A (for FF-style OP) | `SellingGeneralAndAdministrativeExpense`, else `GeneralAndAdministrativeExpense` + `SellingAndMarketingExpense` | 72/96 |
| Operating income | `OperatingIncomeLoss` | **Only 63/96** (many firms - banks, insurers, some industrials - do not tag it) |
| Net income | `NetIncomeLoss` (parent) or `ProfitLoss` (incl. non-controlling) | 80 / 44. Pair `NetIncomeLoss` with `StockholdersEquity`, `ProfitLoss` with `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`. Ford's `NetIncomeLoss` stopped appearing after 2025-06 in my pull, only `ProfitLoss` current |
| Total assets | `Assets` | 84/84 US-GAAP filers |
| Book equity | `StockholdersEquity`, else `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest`, else `Assets - Liabilities` (`Liabilities`), minus `PreferredStockValue` if present | 75 / 50. Procter & Gamble in my scan only had the "including NCI" tag. **Negative or tiny equity** (buyback-heavy firms; typical examples McDonald's, Boeing, Starbucks [M]; Apple's test value is ROE = 120%) makes ROE meaningless: set ROE = missing when BE <= 0 |
| Long-term debt (non-current) | `LongTermDebtNoncurrent`, `LongTermDebtAndCapitalLeaseObligations` (non-current), else `LongTermDebt` minus `LongTermDebtCurrent`, `DebtAndCapitalLeaseObligations`, `SeniorNotes`, `LongTermNotesPayable`, `ConvertibleNotesPayableNoncurrent`, `OtherLongTermDebtNoncurrent`, `LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities` | 75/96 had any non-current debt tag: `LongTermDebt` 47, `LongTermDebtNoncurrent` 45, `...CapitalLeaseObligations` 22. [M] taxonomy definitions: `LongTermDebt` includes current maturities; `LongTermDebtNoncurrent` excludes. **Confirm in the us-gaap taxonomy before coding** to avoid double counting |
| Short-term / current debt | `DebtCurrent` (if present it already includes current LTD - do not add `LongTermDebtCurrent`), else `LongTermDebtCurrent` + `ShortTermBorrowings` + `CommercialPaper` (+`NotesPayableCurrent`, `LineOfCreditCurrent`) | 72/96 any. `LongTermDebtCurrent` 37, `DebtCurrent` 26, `ShortTermBorrowings` 25, `CommercialPaper` 24 |
| Missing debt tags | **Do not silently treat as zero.** In my scan 19 of 96 firms had no non-current or current debt tag from my candidate list (including Palantir, Arista, ServiceNow, Intuitive Surgical, Palo Alto, Berkshire, Exxon's new holding-company CIK, many foreign filers). Absence can mean "no debt" or "debt under a tag or extension I did not list" (Ford, a captive-finance consolidator, showed only a stale 2020 tag). Rule [H]: treat as 0 only if the firm has no debt-like tag in the last 8 quarters AND interest expense is ~0; otherwise leave missing and let the composite use the remaining pieces | |
| Cash & ST investments | `CashAndCashEquivalentsAtCarryingValue` + `MarketableSecuritiesCurrent` or `ShortTermInvestments`; (`CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents` is the cash-flow-statement total, includes restricted) | |
| CFO | `NetCashProvidedByUsedInOperatingActivities` (`...ContinuingOperations` fallback) | 84/84 |
| Capex | `PaymentsToAcquirePropertyPlantAndEquipment`, `PaymentsToAcquireProductiveAssets` | 76/96 |
| D&A (cash-flow statement) | `DepreciationDepletionAndAmortization`, `DepreciationAndAmortization`, `DepreciationAmortizationAndAccretionNet`, `Depreciation` (+`AmortizationOfIntangibleAssets` if only depreciation is given) | Messy: `Depreciation` 53, `DepreciationDepletionAndAmortization` 43. `Depreciation` is often only a note disclosure. EBITDA from this is approximate |
| Interest expense | `InterestExpense`, `InterestExpenseNonoperating` (common since ~2022), `InterestExpenseDebt`, `InterestAndDebtExpense` | 74/96 any |
| Pre-tax income | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` (older: `...MinorityInterestAndIncomeLossFromEquityMethodInvestments`) | For EBITDA fallback = pretax + interest + D&A |
| Working capital pieces (QMJ ACC) | `AssetsCurrent`, `LiabilitiesCurrent`, cash+ST inv, `DebtCurrent`, `TaxesPayableCurrent`/`IncomeTaxesPayableCurrent` | I did not scan coverage. Prefer the cash-flow proxy `(CFO - NI)/A` [H] |
| Shares outstanding | `dei:EntityCommonStockSharesOutstanding` (cover page, in the `dei` namespace, not us-gaap), `dei:EntityPublicFloat` | Multi-class firms (Alphabet, Meta) have several values at one date with no class label in `companyfacts`. Get market cap from the price vendor instead |
| Industry / filer type | `submissions`: `sic`, `sicDescription`, `category` ("Large accelerated filer" etc.) | Verified on Apple: sic 3571, "Large accelerated filer". Map SIC to Fama-French 49 with `Siccodes49.zip` |

Foreign private issuers file 20-F/6-K (IFRS or US GAAP), not 10-K/10-Q, so they have no quarterly XBRL fundamentals on EDGAR (ASML, Alibaba, Toyota, BHP, TotalEnergies, Santander, Petrobras in my scan). Decide up front whether they are in the universe.

### 6.2 Pitfalls found (several reproduced in my own run)

1. **Every fact is repeated in each later filing that shows it as a comparative**, and carries the *filing's* `fy`/`fp`, not the fact's own period (e.g. Apple's period 2022-09-25 to 2023-09-30 appears with `fy` 2023, 2024 and 2025). Key on `(start, end)` and on `filed`, never on `fy`/`fp`.
2. **Point-in-time**: use only facts with `filed <= as_of_date` (use `submissions.acceptanceDateTime` if you want to be strict: filings accepted after 5:30 pm ET are dated the next business day [M]). Among duplicates of the same period choose the latest `filed <= as_of` ("as known then, including restatements"); also compute an "as first reported" variant for sensitivity.
3. **Cash-flow items are year-to-date only** in 10-Qs (3M, 6M, 9M cumulative; Q4 is never filed separately). Income-statement items have both 3M and YTD columns. TTM = FY_last + YTD_current - YTD_prior_year (formula in section 7.2).
4. **52/53-week fiscal years**: Apple's "annual" period above is 371 days; use duration windows, not exact day counts (annual 350-380, YTD windows 80-110 / 170-200 / 255-290).
5. **Stale tags**: a tag can exist in the history but be discontinued (Costco `GrossProfit` FY2019; Walmart `CommercialPaper` 2009; Microsoft `ShortTermBorrowings` 2018; NVIDIA `MarketableSecuritiesCurrent` last at 2025-10). **Same-period rule**: every component used at a given as-of date must have its period end within about 5 days of the reference period end, else treat as missing.
6. **Ticker-to-CIK drift**: on 2026-10-18 SEC's `company_tickers.json` maps `XOM` to CIK 2115436 "ExxonMobil Holdings Corp", while the long history sits under Exxon Mobil Corporation's old CIK 34088. Key your database on CIK history (keep predecessor CIKs), not on ticker; this also matters for delisted/renamed names in a backtest (survivorship).
7. **Restatements/amendments**: `10-K/A` and `10-Q/A` forms are in the feed; decide to include them (they are PIT-valid once filed).
8. **XBRL phase-in** [M, SEC Release 33-9002]: the largest filers started with periods after June 15, 2009, other large accelerated filers June 2010, all remaining filers June 2011. So the first fully broad cross-section is mid-2011. Early (2009-2010) samples are large-cap only.
9. **No COGS at all** for many service/telecom/utility/energy/restaurant/railroad/industrial names: in my scan of 96 names, 36 had neither `GrossProfit` nor a current COGS tag: JPM, BAC, GS, MS, WFC, C, AXP, V, MA, BLK, SCHW, BRK-B (financials/payments, excluded anyway), 11 foreign filers, and 13 US non-financials (XOM [holding-co CIK issue], ORCL, GE, TMO, RTX, DIS, VZ, T, TMUS, MCD, UNP, DE, NEE). That is about 18% of the US-GAAP non-financials. Compustat fills COGS for most of these; XBRL does not. Fallback ladder [H]: (a) GrossProfit; (b) REV - COGS; (c) missing, and compute the composite from the remaining measures (QMJ's own rule); optionally (d) for GP/A-only arms use (OperatingIncomeLoss + D&A + SG&A)/A as a documented proxy and flag it.
10. **Captive finance distortion**: Ford/GM/Caterpillar/Deere/GE consolidate finance arms, so assets are huge and GP/A is tiny (Ford test value 0.054). Industry-adjusted GP/A helps; or exclude these names. Novy-Marx's sample includes them (SIC 3711 is not 6xxx).
11. Units: use `USD` facts only; shares are in `shares`; EPS in `USD/shares`.
12. Dimensioned (segment/class) facts are not in `companyfacts`.
13. Filing lag: 10-K due 60/75/90 days after FYE (large accelerated / accelerated / non-accelerated), 10-Q 40/40/45 days after quarter end [M]. On 2026-10-21 most calendar-year firms' latest filing is the 10-Q for the quarter ended 2026-06-30 (filed Jul-Aug), i.e. 3 to 4 months stale; September-quarter 10-Qs mostly arrive late Oct-Nov.
14. EDGAR numbers are "as reported" and will not match Compustat-standardized numbers one-for-one (COGS definitions especially). Expect rank correlations below 1 versus the papers.

### 6.3 Test vectors (computed with Appendix A as of 2026-10-20 from the live feed on 2026-10-18)

| Ticker | Period used | GP ($B) | Assets ($B) | GP/A | ROE (NI/BE) | Debt/Assets | ND/EBITDA | Notes |
|---|---|---|---|---|---|---|---|---|
| AAPL | TTM to 2026-06-27 | 227.123 | 383.266 | **0.5926** | 1.199 | 0.220 | 0.13 | `GrossProfit` tag; TTM = FY25 + 9M FY26 - 9M FY25; equity only $107.5B so ROE is 120% (buybacks) |
| MSFT | FY to 2026-06-30 | 225.465 | 758.376 | **0.2973** | 0.302 | 0.053 | -0.19 | 10-K period, no TTM adjustment needed |
| WMT | TTM to 2026-07-31 | 178.283 | 293.914 | **0.6066** | 0.225 | 0.172 | 0.82 | no `GrossProfit` tag; REV 728.466 - COGS 550.183 (`CostOfRevenue`) |
| NVDA | TTM to 2026-07-26 | 226.241 | 320.272 | **0.7064** | 0.842 | 0.104 | 0.05 | revenue tag is `Revenues` |
| COST | FY to 2026-08-30 | 38.875 | 89.045 | **0.4366** | 0.258 | 0.069 | -1.05 | `GrossProfit` tag stale (FY2019): must use REV - COGS |
| F | TTM to 2026-03-31 | 15.272 | 282.434 | **0.0541** | -0.162 | n/a | n/a | captive-finance distortion; no standard debt tags; NI via `ProfitLoss` |

Same code as of 2024-10-20 gave AAPL 0.5345, MSFT 0.3339, WMT 0.6202, NVDA 0.8585, COST 0.4596, F 0.0903 (note it correctly used the 10-Q periods because the next 10-Ks were not yet filed).

---

## 7. Recommended filter specification

Assumptions: long-only, monthly (or team cadence) rebalance, top 5-10 names by 12-1 momentum (the other file defines momentum), data from EDGAR plus a price vendor (yfinance). Keep the code stdlib-friendly like the rest of the repo; ranks and z-scores need only `statistics`/sorting.

### 7.1 Universe and timing

- **Universe** [H, consistent with the papers]: US-listed common stocks, **exclude SIC 6000-6999** (Novy-Marx, Fama-French exclude financials; GP/A and COGS are not meaningful for them). Add a liquidity/size floor matched to the momentum file (e.g. price >= $5 and market cap >= ~$1B [H]); Novy-Marx's large-cap results (top 500, spread 0.27 %/mo [2.33]) show the effect survives among big stocks but is smaller.
- **Ranking population**: compute percentiles/z-scores over the *eligible universe at each rebalance date* (aim for >= 300 names), not just over the momentum shortlist.
- **Point-in-time rule**: at rebalance date t, use only filings with `filed <= t - 1 business day`; trade at the next open/close after that. Academic papers use fiscal-year data from end of June of the next year (6-18 month lag); our filing-date approach is *less* stale, which is fine, but results will not match the papers' numbers.
- **Backtest start**: first signal date mid-2011 (phase-in finished); 5-year growth terms push the Growth component to 2016+, so **omit Growth** from the main composite (see 7.3).

### 7.2 Accounting quantities (all in USD)

TTM for flow item X at date t (`X` in REV, COGS, GP, NI, CFO, CAPEX, OPINC, DA, SG&A, interest):

```
if newest filing's period is a full fiscal year:   TTM = FY value
else (10-Q, cumulative YTD value over k months):    TTM = FY_last + YTD_current(k months) - YTD_prior_year(same k months)
```
Stocks (A, BE, DEBT, CASH) = latest balance sheet at the same period end as the flows. No averaging of assets or equity (matches Novy-Marx's and QMJ's use of year-end values).

```
GP      = GrossProfit_ttm   if available and same period, else REV_ttm - COGS_ttm
GPOA    = GP / A                                 [Novy-Marx 2013; QMJ]
GMAR    = GP / REV_ttm                           [QMJ]
ROA     = NI_ttm / A                             [QMJ]
ROE     = NI_ttm / BE   if BE > 0 else missing   [QMJ; Fama-French require positive BE]
CFOA    = (CFO_ttm - CAPEX_ttm) / A              [proxy for QMJ CFOA = (NI+DP-dWC-CAPX)/AT; CFO also includes stock comp etc.]
ACC     = (CFO_ttm - NI_ttm) / A                 [proxy for QMJ ACC (low accruals = high); Sloan-style cash-flow version]
OP_FF   = (REV - COGS - SGA - INTEXP)_ttm / BE   [Fama-French 2015 OP; optional arm]
DEBT    = noncurrent LT debt + current debt (no double count) [+ minority interest + preferred as in QMJ LEV, optional]
LEV     = -DEBT / A                              [QMJ]
NDEBT   = DEBT - CASH_and_ST_investments
EBITDA  = OPINC_ttm + DA_ttm (fallback: pretax income + interest + DA)
EVOL    = std of quarterly NI_q / A_{q-1} over the last 20 quarters (>= 12) [H; QMJ uses quarterly ROE over 60 quarters, >= 12]
BAB     = -beta  (daily returns vs market; Frazzini-Pedersen: 1-yr daily vol x 5-yr 3-day correlation; shrinkage 0.6*beta+0.4 [M])
```
Optional Safety pieces: Altman Z and Ohlson O exactly as in section 3.2 (extra inputs: retained earnings `RetainedEarningsAccumulatedDeficit`, `LiabilitiesCurrent`, `AssetsCurrent`, pretax income `IncomeLossFromContinuingOperationsBeforeIncomeTaxes...`, total liabilities `Liabilities`, CPI). Skip O-score in the first pass.

Rank-and-standardize helper (QMJ section 3.1): `z(x) = (rank(x) - mean(rank)) / std(rank)` over eligible, non-missing names, ties = average rank, "higher = better".

### 7.3 Composite scores (QMJ-lite)

```
P  = z( mean_avail[ z(GPOA), z(ROE), z(ROA), z(CFOA), z(GMAR), z(ACC) ] )      need >= 3 of 6 available
S  = z( mean_avail[ z(BAB), z(LEV), z(-EVOL), (z(Z), z(O) optional) ] )        need >= 2 available
QL = z( P + S )                                                                  "Quality-lite"
```
(QMJ adds Growth = five-year changes; drop it for the main spec because EDGAR gives <= ~15 years and the 5-year changes would remove the first 5 years of the sample. Offer it only as a late-sample sensitivity.)

### 7.4 Filter arms and parameter grid

`pct(.)` = cross-sectional percentile within the eligible universe at the rebalance date. "Order" = apply the quality rule to the whole universe before taking the top-N momentum names (`QF`), or take the momentum shortlist first (top 10% or top 40 by 12-1) then apply quality then take top N by momentum (`MF`); the team's sketch is `MF`.

| ID | Rule | Evidence label |
|---|---|---|
| **Q0** | No quality filter (control) | baseline |
| **Q1-50 / Q1-70** | keep if pct(GPOA) >= 50 / >= 70 (top 50% / top 30%) | **Research-backed**: Novy-Marx 2013 (GP/A sorts; 30/70 breakpoints in PMU); top-30% mirrors PMU/QMJ breakpoints |
| **Q1i-50 / Q1i-70** | same, with GPOA demeaned by Fama-French 49 industry (mean; need >= 10 firms else parent group) | **Research-backed**: Novy-Marx Table 1 Panel B (t 8.99 vs 5.49); also neutralizes captive-finance and asset-light industry effects |
| **Q2-P50** | P >= median | **Research-backed** (QMJ profitability block; EDGAR proxies for CFOA/ACC) |
| **Q2-Q50 / Q2-Q70** | QL >= median / >= 70th pct (top 30%) | **Research-backed** in spirit (QMJ top 30% breakpoint); our QL omits Growth/Payout and uses proxies |
| **Q5-veto30** | drop only the bottom 30% of QL; rank the rest on momentum | **Research-backed rationale** (QMJ Table 3: junk decile has -0.59 %/mo 4F alpha; 56% of spread on the junk side) but this exact rule is mine [H] |
| **Q3a** | TTM NI > 0 AND DEBT/BE <= X AND (GMAR >= industry median OR ROE >= industry median); X in {0.5, 1.0, 2.0} (BE > 0 required) | **Heuristic** (team sketch) |
| **Q3b** | TTM NI > 0 AND NDEBT/EBITDA < Y (EBITDA > 0, or NDEBT <= 0) AND GPOA >= industry median; Y in {2, 3, 4} | **Heuristic** (team doc's ND/EBITDA < 3, with research-backed GP/A in place of margin/ROE) |
| **Q3c** | Q3b plus TTM CFO > 0 | **Heuristic** |
| **Q4-w** | no hard filter; sort on `(1-w) * rank(12-1 momentum) + w * rank(GPOA)`, w in {0.25, 0.5} | **Partly research-backed**: rank-sum design of Novy-Marx & Velikov (2016) (they also include B/M) |
| **Q6** | Q1-50 AND Q3b (belt and braces) | Heuristic combination |

Other grid axes (keep the same across arms): N holdings in {5, 10, 20}; order in {QF, MF} for hard filters only; rebalance frequency from the momentum file. That is about 11 arms x 3 N x 2 orders = ~66 runs. **Gate it**: Stage 1 = factor-level checks of the signals alone (7.5/8.1), no portfolios; Stage 2 = a pre-registered short list (Q0, Q1-50, Q1-70, Q1i-50, Q2-Q50, Q5-veto30, Q3b, Q4-0.5) at N = 10 only; Stage 3 = neighbors (N = 5, 20; thresholds +/- one step) for the winners. Report the number of configurations tried (Harvey-Liu-Zhu's "t > 3" hurdle is quoted in the Novy-Marx-Velikov introduction).

### 7.5 What each part of the team's sketch maps to

| Team sketch | Verdict |
|---|---|
| "high gross margins" | Weakly supported as a *level* signal (gross-margin sort raw H-L +0.01, t 0.13); use **GP/A** (margin x asset turnover) instead. Keep GMAR only as one block of QL |
| "or return on equity" | ROE is a QMJ component and Fama-French's OP/book equity works as RMW, but plain NI/BE adds nothing beyond GP/A in Novy-Marx Table 1 and is distorted by buybacks/negative equity. Use inside QL, not as a standalone pass condition |
| "low debt" | Part of QMJ Safety (LEV, Z, O, EVOL, beta); no standalone test in the papers read. Keep as heuristic arm (Q3) and inside QL |
| "positive earnings" | Indirect support (junk decile, O-score INTWO dummy, failure-probability anomalies explained by low profitability). Keep as part of Q3 |
| "ND/EBITDA < 3" | Pure heuristic; EBITDA is hard to build from XBRL (OperatingIncomeLoss tagged for only ~2/3 of firms) |
| "momentum among financially strong companies" | The overall idea (momentum x quality) is supported only indirectly; see the ledger in section 5 |

---

## 8. Evaluation protocol and validation data

### 8.1 Factor-level validation before any portfolio (Stage 1)

1. Build long-short GP/A deciles on our EDGAR universe (value-weighted or equal-weighted; no NYSE breakpoints available, so use the universe median size). Compare monthly return series with Fama-French `RMW` and Novy-Marx `PMU` (overlap 2011-2012 only for PMU). Expect positive correlation, not identity (our GP/A vs their OP/book-equity and COGS definitions differ).
2. Build the QL long-short (top 30% minus bottom 30%) and correlate with AQR `QMJ USA` (monthly). Expect a clearly positive correlation; low correlation signals a pipeline bug (stale tags, wrong sign on LEV/EVOL/BAB, mixing TTM/period ends). No published benchmark for the correlation of a "lite" version; I will not guess a number.
3. Compare our long-only top-quality bucket with AQR's "10 Quality-Sorted Portfolios" decile 10 and the market.
4. Spot-check 25 firms' GPOA, debt, NI_ttm against a second source (company 10-K or a vendor); tolerance 1-2%.

### 8.2 Portfolio tests (Stage 2/3)

- Walk-forward with only PIT inputs. Development window 2011-07 to 2019-12; **holdout 2020-01 to latest, opened once**.
- Report vs the Q0 control at the same N: CAGR, vol, Sharpe, max drawdown, worst month, worst 3 months, turnover, average holdings' quality percentile and past-return z-score (Bandarchuk-Hilscher check).
- Regress strategy and the **difference portfolio (filtered minus Q0)** on FF5 + Mom (daily or monthly) and on `QMJ USA`; look for RMW/QMJ loading rising while Mom loading stays similar.
- "Panic state" check (Daniel-Moskowitz): months when the trailing 24-month market return is negative and the current market return is large and positive; compare filtered vs Q0 drawdowns and rebound lag.
- Use stationary block bootstrap (blocks about 6 months) on the monthly difference series for confidence intervals; add random tie-breaking and multiple rebalance-day offsets because top-10 portfolios are noisy.

### 8.3 Power (my arithmetic, assumptions flagged)

Usable monthly sample Jul 2011-Sep 2026 is about 183 months. If the filtered-minus-unfiltered top-10 tracking error is ~3 %/month [H, not measured], the standard error of the mean difference is about 3/sqrt(183) = 0.22 %/month, so a difference needs to be about 0.44 %/month (~5 %/year) to reach |t| = 2. Novy-Marx's *long-short* quintile spread is 0.31 %/mo and the QMJ factor is 0.29 %/mo, and the long-only share is smaller. **A backtest on this sample cannot confirm a quality-filter edge of literature size.** Say so, and frame results as "no evidence of harm, loadings move as designed, robust to neighbors".

### 8.4 Known limits

- Published sample ends 2010 (Novy-Marx), 2013 (FF5), 2016 (QMJ); post-publication decay and recent weak RMW are real; 
- XBRL differs from Compustat; 
- idiosyncratic risk of a 5-10 stock book (single-stock vol 30-40% / sqrt(10) = roughly 10-13% annual idiosyncratic [H]) will swamp factor premia in any one season; 
- the QMJ authors work at an asset manager (see section 3 note), and QMJ definitions changed between draft versions (the paper notes it dropped an explicit payout block).

---

## 9. Not verified / open items

- Published JFE text of Novy-Marx (2013): I read the June 2012 working paper only.
- AQR `.xlsx` and Ken French `.csv` layouts: not downloaded; layout notes are [M]. Download requires an explicit team decision (I did not download data files).
- us-gaap tag definitions (current vs total debt) in section 6.1: from memory plus empirical behavior; confirm in the taxonomy viewer.
- SEC fair-access rate limit (10 requests/second) and the XBRL phase-in dates: from memory.
- Abstract-only items: Avramov et al. (2007), Bhootra (2018), Bandarchuk-Hilscher (2013), Ball et al. (2015, 2016), Hou-Xue-Zhang (2020), Piotroski-So (2012), McLean-Pontiff (final JF numbers).
- No primary-source test found of "hard quality filter on long-only price momentum" (neither the Sharpe nor the crash claim). If a teacher asks, the answer is: indirect evidence, which is why we pre-register the test.
- The Ken French RMW 12-month figure comes from a page-parsing tool; re-read the page.

---

## 10. Sources (URLs)

- Novy-Marx (2013): <https://www.sciencedirect.com/science/article/abs/pii/S0304405X13000044> ; WP <https://www.johnhcochrane.com/s/Novy_marx_OSoV.pdf> ; NBER draft <https://www.nber.org/papers/w15940>
- Novy-Marx (2015): <https://www.nber.org/papers/w20984>
- Novy-Marx & Velikov (2016): <https://www.nber.org/papers/w20721> ; WP read <https://mysimon.rochester.edu/novy-marx/research/ToAatTC.pdf>
- Novy-Marx factor data: <https://mysimon.rochester.edu/novy-marx/data_lib/OSoV/index.html> ; PMU details <https://mysimon.rochester.edu/novy-marx/data_lib/OSoV/pmu_details.html>
- Asness-Frazzini-Pedersen: <https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2312432> ; <https://doi.org/10.1007/s11142-018-9470-2> ; <https://ideas.repec.org/a/spr/reaccs/v24y2019i1d10.1007_s11142-018-9470-2.html>
- AQR datasets: <https://www.aqr.com/Insights/Datasets>
- Fama-French (2015): <https://www.sciencedirect.com/science/article/pii/S0304405X14002323> ; <https://tevgeniou.github.io/EquityRiskFactors/bibliography/FiveFactor.pdf>
- Ken French data library: <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html> ; <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_5_factors_2x3.html> ; <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_mom_factor.html> ; <https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/det_49_ind_port.html>
- Daniel & Moskowitz (2016): <https://www.nber.org/papers/w20439> ; <https://www.sciencedirect.com/science/article/pii/S0304405X16301490>
- Avramov et al. (2007): <https://www.johnhcochrane.com/s/avramov_etal_momentum.pdf>
- Bhootra (2018): <https://www.emerald.com/insight/content/doi/10.1108/MF-11-2017-0444/full/html>
- Bandarchuk & Hilscher (2013): <https://ideas.repec.org/p/brd/wpaper/38.html>
- Ball et al.: <https://papers.ssrn.com/abstract=2414543>
- Hou-Xue-Zhang (2020): <https://ideas.repec.org/a/oup/rfinst/v33y2020i5p2019-2133..html>
- Piotroski & So (2012): <https://ideas.repec.org/a/oup/rfinst/v25y2012i9p2841-2875.html>
- McLean & Pontiff (2016): <https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365>
- Jegadeesh & Titman (1993) (momentum, other file): <https://onlinelibrary.wiley.com/doi/abs/10.1111/j.1540-6261.1993.tb04702.x>
- SEC EDGAR APIs: <https://www.sec.gov/search-filings/edgar-application-programming-interfaces>

---

## Appendix A - reference implementation (point-in-time TTM from SEC companyfacts, stdlib only)

Tested 2026-10-18 on AAPL, MSFT, WMT, NVDA, COST, F (outputs in section 6.3). It is a sketch for validating the team's own pipeline, not production code: no caching, no retry, no rate limit, and the debt logic needs the taxonomy check in section 6.1.

```python
"""Point-in-time TTM + balance-sheet extraction from SEC 'companyfacts' JSON (stdlib only).
Sketch for the quality filter: python3 pit_fundamentals.py 2026-10-20
SEC asks for a declared User-Agent and <=10 requests/second."""
import json, sys, urllib.request
from datetime import date

UA = "CapitalCrew Student Research Project research@capitalcrew-project.org"   # replace with a real team contact
FLOW = {   # tag priority lists (first tag that has a value for the *period* wins; never coalesce per company)
 "rev":   ["RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
           "RevenueFromContractWithCustomerIncludingAssessedTax", "SalesRevenueGoodsNet"],
 "cogs":  ["CostOfGoodsAndServicesSold", "CostOfRevenue", "CostOfGoodsSold", "CostOfServices"],
 "gp":    ["GrossProfit"],
 "ni":    ["NetIncomeLoss", "ProfitLoss"],
 "cfo":   ["NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations"],
 "capex": ["PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets"],
 "opinc": ["OperatingIncomeLoss"],
 "da":    ["DepreciationDepletionAndAmortization", "DepreciationAndAmortization",
           "DepreciationAmortizationAndAccretionNet", "Depreciation"],
}
STOCK = {
 "assets": ["Assets"],
 "equity": ["StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest"],
 "ltd_nc": ["LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations"],
 "debt_c": ["DebtCurrent"],
 "ltd_c":  ["LongTermDebtCurrent"],
 "cp":     ["CommercialPaper"],
 "stb":    ["ShortTermBorrowings"],
 "cash":   ["CashAndCashEquivalentsAtCarryingValue"],
 "sti":    ["MarketableSecuritiesCurrent", "ShortTermInvestments"],
}
def D(s): return date.fromisoformat(s)
def days(a, b): return (D(b) - D(a)).days

def pit_periods(cf, tags, asof):
    """{(start,end): dict(val,tag,filed)}: best tag priority per period; latest filing with filed <= asof."""
    best, g = {}, cf["facts"]["us-gaap"]
    for pri, t in enumerate(tags):
        node = g.get(t)
        if not node or "USD" not in node["units"]: continue
        for r in node["units"]["USD"]:
            if r["filed"] > asof or r["form"] not in ("10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT"): continue
            k = (r.get("start"), r["end"])
            if k not in best or pri < best[k]["pri"] or (pri == best[k]["pri"] and r["filed"] > best[k]["filed"]):
                best[k] = dict(val=r["val"], pri=pri, tag=t, filed=r["filed"])
    return best

def ttm(cf, tags, asof, want_end=None):
    """TTM = FY_last + YTD_cur - YTD_prior (or the 10-K value if the newest period is a full year)."""
    fl = {k: v for k, v in pit_periods(cf, tags, asof).items() if k[0]}
    ok = lambda n: 80 <= n <= 110 or 170 <= n <= 200 or 255 <= n <= 290 or 350 <= n <= 380
    cands = [k for k in fl if ok(days(*k))]
    if not cands: return None
    E = want_end or max(k[1] for k in cands)
    cur = [k for k in cands if abs(days(k[1], E)) <= 5]
    if not cur: return None                       # SAME-PERIOD RULE: stale/discontinued tags are rejected here
    cur = max(cur, key=lambda k: days(*k))
    if 350 <= days(*cur) <= 380: return fl[cur]["val"]
    fy = [k for k in cands if 350 <= days(*k) <= 380 and abs(days(k[1], cur[0])) <= 8]
    pr = [k for k in cands if abs(days(k[0], cur[0]) - 365) <= 12 and abs(days(k[1], cur[1]) - 365) <= 12
          and abs(days(*k) - days(*cur)) <= 10]
    if not fy or not pr: return None
    return fl[max(fy, key=lambda k: k[1])]["val"] + fl[cur]["val"] - fl[pr[0]]["val"]

def stock(cf, tags, asof, want_end):
    per = {k: v for k, v in pit_periods(cf, tags, asof).items() if not k[0]}
    ks = [k for k in per if abs(days(k[1], want_end)) <= 5]       # same date as total assets, else treat as missing
    return per[max(ks, key=lambda k: k[1])]["val"] if ks else None

def snapshot(cf, asof):
    A = pit_periods(cf, STOCK["assets"], asof)
    inst = [k for k in A if not k[0]]
    if not inst: return None
    end = max(k[1] for k in inst)
    s = {n: stock(cf, t, asof, end) for n, t in STOCK.items()}
    f = {n: ttm(cf, t, asof) for n, t in FLOW.items()}
    rev = ttm(cf, FLOW["rev"], asof)
    # same-period rule for flows: re-run with want_end = period end implied by revenue
    ends = [k[1] for k in pit_periods(cf, FLOW["rev"], asof) if k[0]]
    if ends: 
        E = max(ends)
        f = {n: ttm(cf, t, asof, want_end=E) for n, t in FLOW.items()}
    gp = f["gp"] if f["gp"] is not None else (f["rev"] - f["cogs"] if f["rev"] is not None and f["cogs"] is not None else None)
    debt_cur = s["debt_c"] if s["debt_c"] is not None else sum(x or 0 for x in (s["ltd_c"], s["cp"], s["stb"]))
    debt = None if s["ltd_nc"] is None and s["debt_c"] is None and s["ltd_c"] is None else (s["ltd_nc"] or 0) + debt_cur
    cash = (s["cash"] or 0) + (s["sti"] or 0)
    ebitda = f["opinc"] + (f["da"] or 0) if f["opinc"] is not None else None
    return dict(period_end=end, gp=gp, assets=s["assets"], gpa=gp / s["assets"] if gp is not None else None,
                roe=f["ni"] / s["equity"] if f["ni"] is not None and s["equity"] and s["equity"] > 0 else None,
                roa=f["ni"] / s["assets"] if f["ni"] is not None else None,
                cfoa=(f["cfo"] - (f["capex"] or 0)) / s["assets"] if f["cfo"] is not None else None,
                debt=debt, debt_to_assets=debt / s["assets"] if debt is not None else None,
                nd_ebitda=(debt - cash) / ebitda if debt is not None and ebitda and ebitda > 0 else None, ni=f["ni"])

def get(cik):
    req = urllib.request.Request(f"https://data.sec.gov/api/xbrl/companyfacts/CIK{cik:010d}.json",
                                 headers={"User-Agent": UA, "Accept-Encoding": "identity"})
    return json.load(urllib.request.urlopen(req, timeout=60))

if __name__ == "__main__":
    asof = sys.argv[1]
    for name, cik in [("AAPL", 320193), ("MSFT", 789019), ("WMT", 104169), ("NVDA", 1045810), ("COST", 909832), ("F", 37996)]:
        snap = snapshot(get(cik), asof)
        print(name, {k: (round(v, 4) if isinstance(v, float) else v) for k, v in snap.items()})
```
