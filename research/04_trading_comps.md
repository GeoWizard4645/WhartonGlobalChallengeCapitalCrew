# 04 - Trading Comps as a systematic, backtestable stock-selection strategy

Prepared 2026-10-18 for Capital Crew (Wharton Global High School Investment Competition 2026-27). First trades: Wed 2026-10-21.
Scope: turn the "Trading Comps" and "Key Metrics" sections of the team planning doc into (1) research-backed design choices, (2) exact formulas, (3) an unambiguous algorithm, (4) a pre-registered grid and train/test protocol.

Evidence tags used throughout (be strict about these when you cite this file to judges):

| Tag | Meaning |
|---|---|
| [V] | Verified by me in the primary text (PDF text extracted and read this session) |
| [S] | Reported by a secondary source that I read (a later paper, thesis or review quoting the original) - original not read |
| [A] | Only the abstract / bibliographic page was available |
| [D] | Verified directly on data in this session (Wikipedia HTML, SEC files in `cache/sec`, installed packages) |
| [M] | From my memory / general knowledge - NOT verified this session; check before relying on it |

---

## 0. Bottom line

1. **What the literature supports.** Peer multiples from a tight, sensible industry classification value stocks reasonably well (median absolute error ~22-29% for P/E on S&P 1500 names [V KKP 2017]; interquartile range of pricing error ~0.32 for 2-year-forward P/E and ~0.52 for last-fiscal-year GAAP P/E in the classic Liu-Nissim-Thomas study [V]). GICS is the best-validated classification for this purpose [A Bhojraj-Lee-Oler 2003; V Chan-Lakonishok-Swaminathan 2007 on GICS levels].
2. **What it does NOT show.** Valuation accuracy is not return predictability. Liu-Nissim-Thomas explicitly assume efficient markets and do not study mispricing (their footnote 2) [V]. I found **no paper that tests the exact rule "buy if own multiple < 0.85 x peer median"**. The closest return evidence is that the value effect is mostly a *within-industry* effect (Asness-Porter-Stevens 2000; Cohen-Polk-Vuolteenaho 2003 [V]) - good news for an industry-relative rule - but the post-2007 value premium is weak (industry-adjusted HML averaged +0.65%/yr in 2007-2018, not different from zero [V Lev-Srivastava]), and published anomalies decay by 26% out-of-sample / 58% post-publication on average [S McLean-Pontiff 2016]. Expect the live edge to be small; the backtest is there to decide, not to decorate.
3. **Three citations in the team doc need fixing** (Section 1): "Nissim & Thomas (2002)" is Liu, Nissim & Thomas (2002) and it does **not** use TTM; Alford (1992) says *narrower* industries are better (not that expanding to a wider level is better) and found size/ROE add nothing beyond industry; and a "forward" multiple cannot be backtested honestly with free data.
4. **Recommended spec in one paragraph.** Universe = current S&P 500/400/600 (1,503 unique tickers on 2026-10-18 [D]) minus Financials and Real Estate. At each month-end, for each stock and for each of P/E (TTM) and EV/EBITDA (TTM): peers = same GICS sub-industry, valid, positive, under the cap, not a recent IPO/merger, market cap within 0.5x-2x (closest 5); fall back to the GICS industry if fewer than 4; drop peers more than 2x or less than 0.5x the peer median; benchmark = median of what is left (need >= 3). BUY candidate if **both** multiples are at least `theta` below their benchmark. Then apply the key-metric gates (Net Debt/EBITDA <= 3x, FCF and margin-stability quality check, ROIC > WACC). Rank survivors by average discount, hold up to 20 equal-weight, rebalance monthly. Choose `theta`, P/E cap, EV/EBITDA cap and size filter from a pre-registered 3x3x3x2 = 54-cell grid on 2012-2018, pick the stable plateau (not the max), confirm once on 2019-2026.
5. **Biggest honesty issues in the backtest** (Section 9): survivorship (current constituents), current GICS applied to history, no analyst forward estimates, no point-in-time index membership for the S&P 500, 54+ trials on ~7 years of data (Sharpe standard error ~0.36-0.38 per window, so differences between cells under ~0.4 are noise).

---

## 1. Corrections and flags on the team doc

| # | Team doc says | What I found | Consequence |
|---|---|---|---|
| C1 | "TTM ... (Nissim & Thomas 2002)" | The paper is **Liu, Nissim & Thomas (2002), "Equity Valuation Using Multiples", JAR 40(1): 135-172** (also confirmed by IDEAS record). It uses accounting data for the *previous fiscal year* and prices as of April; a text search of the whole paper for "trailing", "TTM", "twelve" returns nothing [V]. Its headline result is that **forward** earnings multiples are the most accurate [V]. | TTM is a sound practical choice (it aligns companies with different fiscal year-ends and is point-in-time verifiable), but it is **not** a finding of that paper. A TTM implementation that *is* documented: Knudsen-Kold-Plenborg (2017) built TTM from "the last four quarterly reports published before 31 March" for S&P 1500 stocks [V]. Cite KKP for TTM, LNT for "forward is best". |
| C2 | "expands to the GICS industry level since industry-matched peers value more accurately (Alford 1992)" | Alford: pricing errors fall as the industry definition is narrowed from 1-digit to 2- and 3-digit SIC, with no further gain at 4-digit; adding size (total assets) or ROE to industry did not significantly improve accuracy [S via Lie-Lie 2002, LNT 2002 section 2 (V for LNT's description), Cooper-Lambertides 2023]. | Fallback from sub-industry to industry is a necessary compromise when the peer set is too small; it is *not* supported as an accuracy improvement. Alford gives no support for the 0.5x-2x market-cap window, which is why "size filter: with vs without" is a legitimate grid dimension. |
| C3 | "TTM vs forward" in the pre-registered grid | Historical consensus forward EPS (I/B/E/S) is not freely available. | Backtest TTM vs last-fiscal-year (LFY); show forward P/E from yfinance for the live date as a cross-check only (Section 8). Do **not** use realized future earnings as a proxy (look-ahead). |
| C4 | Net Debt/EBITDA: "negative = great, 1x-3x ok, above 3x no" | 0x-1x is not specified. EBITDA <= 0 makes the ratio meaningless. | Interpretation: pass if EBITDA > 0 and ND/EBITDA <= 3.0 (negative and 0-1x pass automatically). |
| C5 | "No P/E above 40, no EV/EBITDA above 35" | No paper supplies fixed caps. LNT trimmed the 1st and 99th percentiles of the pooled sample [V]; KKP winsorized at 0.5% / 99.5% [V]. | Caps are judgment parameters -> correctly put in the grid. |
| C6 | "(HAS TO BE <50 million market valuation)" | This line sits under the Magic Formula section and reads like a typo for ">= $50M". | Not applied to comps; S&P 1500 constituents are far above this anyway [M]. A $300M floor is used only as a data-quality guard. |
| C7 | Atrina's note about the 2016 "academic research destroyed predictability" paper | McLean & Pontiff (2016, JF): across 97 published predictors, returns are **26% lower out-of-sample** and **58% lower post-publication** [S]. | Honest framing for judges: our own backtest is evidence about the *parameters*; the premise (relative cheapness) is published and so likely partly arbitraged. |
| C8 | Multiples "cover each other's blind spots (debt distortion vs capital spending)" | In LNT, EV-based EBITDA multiples were *less* accurate than equity-based EBITDA and than historical P/E; in KKP (S&P 1500) EV/EBIT beat P/E. Mixed. | Keep both, treat the AND/OR/average combination as a tested design choice (Section 7.5). |

---

## 2. Paper findings (with numbers)

### 2.1 Alford (1992)

Alford, A.W. (1992), "The Effect of the Set of Comparable Firms on the Accuracy of the Price-Earnings Valuation Method", *Journal of Accounting Research* 30(1): 94-108. DOI 10.2307/2491093. JSTOR was not accessible, so everything below is from papers that describe it. [S]

- **Question:** how should the "comparable firms" for a P/E valuation be chosen?
- **Candidate peer sets (seven):** industry (SIC digits), size (total assets), ROE/earnings-growth proxies, and combinations. Sample: **4,698 companies from 1978, 1982 and 1986** [S Lie & Lie 2002, FAJ].
- **Accuracy metric:** absolute prediction error scaled by price, |P_hat - P| / P; LNT note that Alford defines the signed error as "predicted minus price" and they flip it [V LNT footnote 9]; the **median** is the headline statistic [S].
- **Result 1:** best accuracy when peers are chosen by industry alone or industry combined with ROE or total assets; accuracy improves as the SIC definition is narrowed to 3 digits, no extra gain at 4 digits [S Lie & Lie; V LNT's description in section 2].
- **Result 2:** adding size, leverage or earnings growth on top of industry "does not reduce valuation errors" [V LNT section 2; S Cooper-Lambertides]. Analysts' long-term growth forecast was the single most useful extra variable but added "little or no" accuracy beyond industry [S Cooper-Lambertides].
- **Result 3:** accuracy is positively related to firm size (bigger target = smaller error) [S Lie & Lie].
- **Magnitude:** median percentage errors of **23.9% to 25.3%** across the peer-set definitions [S Lie & Lie].
- **Mechanics:** median of peer P/Es; six comparable companies [S KKP, Lund thesis].

Mapping to GICS: 3-digit SIC is roughly comparable in granularity to GICS **sub-industry** (8-digit, 163 sub-industries), 2-digit SIC to GICS **industry** (6-digit, 74) [M: SIC has on the order of 80 two-digit and 400 three-digit groups].

### 2.2 Liu, Nissim & Thomas (2002) and (2007)

LNT (2002), JAR 40(1): 135-172, DOI 10.1111/1475-679X.00042. [V - full text read]

- **Design.** Each April 1982-1999, value a target as (peer multiple) x (target value driver) using comparables from the same industry, with the target removed from the comparable set. **Peer definition = the middle level of the I/B/E/S Sector/Industry/Group classification**, requiring at least 5 firms per industry-year. Positive values only; pooled 1%/99% trimming of each ratio; price >= $2. 26,613 firm-years before the extra screens, **19,879 in the final sample, 81 industries**.
- **Error metric.** Proportional pricing error = (price - predicted value) / price; main dispersion measure = **interquartile range (IQR)**; also 90-10 and 95-5 spreads. Using the harmonic mean makes the average error ~0 by construction.
- **Ranking by IQR (industry peers, harmonic mean, Table 2 panel A):**

| Value driver | IQR |
|---|---|
| 2-yr-ahead forward EPS | 0.317 |
| 1-yr-ahead forward EPS | 0.348 |
| I/B/E/S historical "core" EPS | 0.442 |
| Compustat historical EPS (before extraordinary items) | 0.518 |
| EBITDA (equity-value multiple, P/EBITDA) | 0.553 |
| Book value of equity | 0.602 |
| EBITDA (**enterprise-value** multiple, EV/EBITDA) | **0.619** |
| Sales (equity) | 0.738 |
| Operating cash flow | 0.777 |
| Sales (EV) | 0.901 |

  So: forward earnings > historical earnings > {cash flow, book} > sales, and **EV/EBITDA was worse than historical P/E** and slightly worse than equity-based EBITDA ("surprising", the authors "are unable to provide any rationale"; Alford found the same). The ranking held in almost all industries (forward EPS ranked first in 66 of 81 industries; EBITDA's modal rank was 4th) and over time.
- **Absolute accuracy.** Forward EPS valuations are within 15-17% of price for about half the sample; within +/-20% for ~60% of firm-years. Historical-earnings multiples are far worse (IQR 0.44-0.52 means half of firms are within roughly 22-26%).
- **Industry vs whole cross-section (panel B).** IQR with all firms as comparables: EPS1 0.452, EPS2 0.388, Compustat EPS 0.625, EBITDA/P 0.692, EV/EBITDA 0.704. So using same-industry peers cut the IQR by 23% (EPS1), 18% (EPS2), 17% (GAAP EPS), 20% (EBITDA/P), 12% (EV/EBITDA) - the case for peer groups.
- **Harmonic mean vs median (panel C, medians):** IQR EPS1 0.350 (vs 0.348), EPS2 0.320 (0.317), I/B/E/S EPS 0.450 (0.442), GAAP EPS **0.513 (0.518 - median slightly better)**, EBITDA/P 0.581 (0.553), EV/EBITDA 0.629 (0.619), book 0.649 (0.602), CFO 0.903 (0.777). The improvement from the harmonic mean "is inversely related to the absolute performance of that multiple, and the improvement for forward earnings multiples is quite small"; the simple mean is much worse. Takeaway: **median is fine for P/E; harmonic mean helps mainly for EBITDA/cash-flow type multiples**. Harmonic mean of P/E = n / sum(1/PE) = 1 / mean(E/P).
- **Intercept-adjusted multiples** help mostly the poorly performing drivers; for forward EPS the gain is minimal.
- **Caveats stated by the authors:** results only cover I/B/E/S-covered, positive-earnings firms; they assume market efficiency and **do not examine mispricing** (footnote 2). WACC-like inputs they used: 10-year Treasury yield as risk-free, **5% equity premium**, betas from **60 monthly returns** (median beta of the beta decile) [V].
- **EV definition used:** price + book value of debt per share (long-term debt + debt in current liabilities + preferred stock...), **no cash subtracted, no minority interest** [V]. Our EV is the textbook one.

LNT (2007), "Is Cash Flow King in Valuations?", *Financial Analysts Journal* 63(2): 56-68, DOI 10.2469/faj.v63.n2.4522 [A]: earnings-based multiples beat operating-cash-flow and dividend-based ones in every comparison tested (forecasts vs reported numbers, within industries, non-US markets). Supports using earnings multiples rather than cash-flow multiples for relative valuation (EBITDA was not part of that comparison); FCF is used here only as a quality gate.

### 2.3 Industry classification: Bhojraj-Lee-Oler (2003), Chan-Lakonishok-Swaminathan (2007), Bhojraj-Lee (2002)

- **Bhojraj, Lee & Oler (2003), JAR 41(5): 745-774** [A]: compares SIC, NAICS, Fama-French (1997) and GICS. "GICS classifications are significantly better at explaining stock return comovements, as well as cross-sectional variations in valuation multiples, forecasted and realized growth rates, R&D expenditures, and key financial ratios"; the advantage is consistent year to year and strongest among large firms; the other three schemes differ little from each other. A secondary summary says only 56% of GICS-defined samples overlap SIC-defined ones. I could not access the tables, so **I cannot give R-squared magnitudes** from this paper.
- **Chan, Lakonishok & Swaminathan (2007), FAJ 63(6)** [V - full text]: S&P-universe study of GICS levels. Mean within-industry correlation of returns in 2000-2004: 0.34 (Fama-French) / 0.36 (4-digit GICS industry group) / **0.41 (6-digit industry)** / **0.43 (8-digit sub-industry)**, vs an outside-industry correlation of ~0.18; "little is gained from further detail" beyond 6-digit. For excess returns the share of an average stock's extra-market return variance explained by one industry peer was 3.24% (FF) vs 5.26% (6-digit GICS). Industry effects are **stronger for large caps than small caps**. Implication: falling back from sub-industry to industry costs little in homogeneity; peers for S&P 600 names are noisier.
- **Bhojraj & Lee (2002), "Who Is My Peer?", JAR 40(2): 407-439** [A]: "warranted multiple" peers (regress EV/Sales or P/B on profitability, growth and risk proxies; peers = closest warranted multiples) predict 1-3 year-ahead EV/Sales and P/B better than industry peers. It predicts future *multiples*, not returns. A thesis summary says the regressions used 8 explanatory variables over 1982-1998 [S].
- **Katselas, Sidhu & Yu (2017), Accounting & Finance, DOI 10.1111/acfi.12285** [A]: matching on *time-series (dynamic)* GICS gives better-specified performance measures than matching on static GICS (Australian data) - the formal version of the "current GICS applied to history" worry in Section 9.

### 2.4 How many peers, and which variables pick them

- **Knudsen, Kold & Plenborg (2017), "Stick to the Fundamentals and Discover Your Peers", FAJ 73(3): 85-105** [V]. Universe: **S&P 500 + MidCap 400 + SmallCap 600**, valuation date 31 March each year 1995-2014, **TTM** from the last four quarterly reports, 12,350 company-years, six peers, harmonic mean, GICS-6 industries with >= 16 companies. Median absolute % error of the estimated multiple:

| Peer rule (6 peers) | P/E | EV/EBIT | P/B | EV/Sales |
|---|---|---|---|---|
| 6 random peers from the same GICS-6 industry | 0.286 | 0.255 | 0.349 | 0.407 |
| Within the industry, closest on ROE only | 0.247 | 0.244 | 0.247 | 0.380 |
| ... + net debt/EBIT | 0.244 | 0.219 | 0.249 | 0.364 |
| ... + market cap (size) | 0.241 | 0.215 | 0.243 | 0.344 |
| ... + analyst growth | 0.228 | 0.206 | 0.240 | 0.338 |
| ... + EBIT margin | **0.225** | **0.203** | 0.241 | 0.271 |

  So choosing peers by fundamentals *within* the industry cuts P/E error by ~21% (0.286 -> 0.225); **the size step alone buys only 0.003 for P/E (0.244 -> 0.241)** and the big gains come from ROE (0.286 -> 0.247) and growth. Median error was minimised at 6-16 peers depending on the multiple, and accuracy fell as more (less-similar) peers were added. This is the strongest available evidence that the doc's *size* filter is the weakest peer-selection criterion and that ROE/margin similarity is better. (Extension E5 below.)
- **Cooper & Lambertides (2023), *European Financial Management* 29(4): 1025-1053, DOI 10.1111/eufm.12405** [V]: with forward earnings and the harmonic mean, **10 closest peers (by analyst growth) are as accurate as the entire industry; 5 are only slightly worse**; practitioners typically use 4-6 peers (brokers' reports). "More information is not necessarily better" when weak peers get weight. The key is closeness of growth rates (not available free). Sample 1982-2014.
- Schreiner (2007) suggests 4-8 peers [S, Lund thesis]. Alford used six [S].

### 2.5 Evidence that "cheap relative to industry peers" predicts returns (the alpha mechanism)

| Source | Finding | Magnitude | Tag |
|---|---|---|---|
| Asness, Porter & Stevens (2000), "Predicting Stock Returns Using Industry-Relative Firm Characteristics", GSAM/AQR working paper; all NYSE/AMEX/Nasdaq stocks, June 1963 - Nov 1998 | Splits each characteristic (book-to-equity, cash flow-to-price, past returns) into **within-industry** and across-industry parts; within-industry momentum is significant; says industry-relative sorting is "possibly better" for stock selection | The AQR abstract page and PDF contain **no numbers**. Lev & Srivastava describe it as finding "much stronger value effects within industries than across industries" [V]. A search snippet attributes to Novy-Marx (2013) the statement that industry-adjusted strategies do not raise average returns but lower volatility - I could not find that sentence in the working-paper text I downloaded. | [A]/[S]/[M] |
| Cohen, Polk & Vuolteenaho (2003), "The Value Spread", JF 58(2) | Decomposes the book-to-market ratio. The book-to-market effect in returns "is mostly an intraindustry effect", confirming Cohen-Polk (1998), Lewellen (1999) and APS (2000) | "Roughly **80 percent** of the information in the raw BE/ME ratios concerns the firm's behavior relative to its industry"; one-year-ahead coefficient on intraindustry return **2.1%** vs **0.55%** for industry return; intraindustry ROE coefficient ~9x the industry one | [V] |
| Chou, Ho & Ko (2012), J. Banking & Finance 36(2): 355-370 | Book-to-market effect is an intra-industry phenomenon | abstract only | [A] |
| Lev & Srivastava (2021/22), "Explaining the Recent Failure of Value Investing" | Using Fama-French-12 industry-relative B/M cutoffs "improves overall returns, consistent with Asness et al. (2000)", but the value payoff still collapsed | **Average industry-adjusted HML in 2007-2018 is +0.65%/yr, statistically indistinguishable from zero**; 10 of 12 industries had HML > 4% in 1970-1988, only 2 in 2007-2018 | [V] |
| Rhodes-Kropf, Robinson & Viswanathan (2005), JFE 77(3), "Valuation waves and merger activity" | Decomposes market-to-book into **firm-specific error** (deviation from contemporaneous *sector* multiples - conceptually our "discount to peer median"), sector-timing error and long-run value-to-book; sector-level cross-sectional regressions (Fama-French 12 sectors) explain 80-94% of within-sector variation in market values | Evidence is about **mergers** (misvaluation drives who buys whom), not stock-return prediction | [V] |
| Avramov, Ge, Li & Linton (2024/2026), "Decoding Cross-Stock Predictability: Peer Strength versus Firm-Peer Disparities" -> JFE 2026 "Dual peer effects and cross-stock predictability" | A "peer-deviation index" (firm characteristics minus industry averages) is used to predict next-month returns; 94 firm + 8 industry characteristics, 1980-2022, top 80% by market cap | Results paywalled; I could not read spreads. Direction: peer-relative information predicts returns | [A] |
| Yoon (2015), Duke honors thesis "Multiples Valuation and Abnormal Returns" (2-digit SIC peers, harmonic mean, fiscal-year multiples, 1962-2013) | Portfolios formed on P/E, EV/EBITDA, EV/Sales peer-implied value earned positive CAPM alphas | CAPM alphas of roughly 0.3-0.7% per month across equal- and value-weighted designs, decaying with holding period (e.g. 0.68% -> 0.46% from 1-year to 3-year hold for one equal-weighted multiple); concentrated in small firms; value-weighted alphas lose significance after controlling size and value. **Undergraduate thesis - weak evidence** | [V] (weak) |
| McLean & Pontiff (2016) | Anomaly decay | -26% out-of-sample, -58% post-publication | [S] |

Read this table as: the *direction* (industry-relative cheapness is where the value premium lives) is well supported; the *magnitude for a 0.85x-of-median rule on a high-quality large/mid/small-cap universe in 2012-2026* is unknown and is what the backtest must estimate. Small, young, illiquid names carry much of the historical anomaly profit, and the S&P 1500 excludes them.

### 2.6 Evidence vs each rule in the doc

| Doc rule | Best evidence | Strength |
|---|---|---|
| GICS sub-industry peers | BLO 2003 (A), CLS 2007 (V) | Moderate-strong |
| 4-5 peers | Alford six peers (S), Cooper-Lambertides 5 vs 10 (V), KKP 6-16 optimum (V) | Moderate; 4-5 is at the low end -> test 8 as extension |
| Market cap 0.5x-2x | Alford: size adds nothing beyond industry (S); KKP: size step adds ~1% (V) | **Weak** -> keep as grid dimension |
| Expand to industry if < 4 | CLS 2007: 6-digit nearly as homogeneous as 8-digit (V) | Moderate (as a fallback) |
| P/E and EV/EBITDA | LNT: P/E (historical) better than EV/EBITDA (V); KKP: EV/EBIT better than P/E (V) | Mixed -> test combination rules |
| TTM | KKP built TTM (V); LNT used last fiscal year (V) | Practical, not "proven" |
| Ignore negatives | LNT required positive values (V) | Standard |
| Caps 40 / 35 | none (LNT trimmed 1%/99%) | Judgment -> grid |
| Drop peers with missing data | LNT required non-missing core data (V) | Standard |
| Exclude recent IPOs/mergers | No paper in this set; general argument that TTM numbers are unstable | Judgment; define it testably |
| Peer multiples within 0.5x-2x of median | none; analogous to outlier trimming | Judgment |
| Discount threshold 0.85 | none | Grid |
| Harmonic mean vs median | LNT: tiny difference for earnings, bigger for EBITDA (V) | Add as extension |
| Net Debt/EBITDA, FCF, margins, ROIC>WACC | Quality overlays; KKP uses net debt/EBIT and EBIT margin as peer-selection variables (V). Quality-minus-junk/profitability literature is cited in the team doc, not verified here | Plausible; test with/without |

---

## 3. Data sources and what I verified about them

### 3.1 GICS constituents from Wikipedia [D] (fetched 2026-10-18)

| Page | Constituents table columns | Rows |
|---|---|---|
| https://en.wikipedia.org/wiki/List_of_S%26P_500_companies | Symbol, Security, **GICS Sector, GICS Sub-Industry**, Headquarters Location, Date added, CIK, Founded | 503 (500 companies, some dual-class) |
| https://en.wikipedia.org/wiki/List_of_S%26P_400_companies | Symbol, Security, **GICS Sector, GICS Sub-Industry**, Headquarters Location, SEC filings (no CIK column) | 400 |
| https://en.wikipedia.org/wiki/List_of_S%26P_600_companies | Symbol, Security, **GICS Sector, GICS Sub-Industry**, Headquarters Location, SEC filings, CIK | 603 |

- All three tables have the Sector and Sub-Industry columns. Union = **1,506 rows, 1,503 unique tickers** (CORT, EAT, FORM appear in two indexes; keep the higher-tier index), **154 distinct sub-industries**, 11 sectors.
- Sub-industry sizes in the union: **42 of 154 have fewer than 4 members**, 56 have 4-9, 56 have >= 10 (largest: Regional Banks 90, Industrial Machinery 44, Application Software 41, Health Care Equipment 34, Semiconductors 32). 91.2% of rows have >= 4 *other* same-sub-industry names **before** any size screening; after a 0.5x-2x market-cap window the share will be much lower (needs market caps; log it as diagnostic D1: "fallback rate").
- Names that are used by the tables but not in the Wikipedia 2023 hierarchy: `Specialty Stores` (legacy name; the 2023 name for code 25504040 is `Other Specialty Retail` [M]) -> add an alias. Ten 2023 sub-industries have no members in the 1,500 (Airport Services, Brewers, Diversified Real Estate Activities, Drug Retail, Forest Products, Highways & Railtracks, Marine Ports & Services, Precious Metals & Minerals, Real Estate Operating Companies, Textiles).
- Tickers contain dots (`BRK.B`, `BF.B`, `MOG.A`, `CWEN.A`); yfinance uses dashes (`BRK-B`). Dual-class issuers (GOOGL/GOOG, FOX/FOXA, NWS/NWSA, ...): de-duplicate by CIK and keep one line.
- Point-in-time membership: the S&P 400 page has a changes table (Date / Added / Removed / Reason; 623 rows, dates **2012-01-13 to 2026-09-21**), the S&P 600 page has one (491 rows, **2019-12-17 to 2026-08-04** only). The S&P 500 page as fetched had **no** changes table (verify on a fresh fetch). So historical membership can be only partially reconstructed; keep that in the bias list.
- Scraping: use a descriptive User-Agent, cache the HTML, and snapshot the date; the pages change daily.

### 3.2 GICS hierarchy (2023 structure; 11 sectors / 25 industry groups / 74 industries / 163 sub-industries) [D]

Parsed from https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard (table of codes) and cross-checked against the counts in the 2016 and 2023 revision notices. The industry (6-digit) is `sub_industry_code[:6]`; the industry group is `[:4]`; the sector is `[:2]`.

```
10 Energy
  1010 Energy
    101010 Energy Equipment & Services: 10101010 Oil & Gas Drilling; 10101020 Oil & Gas Equipment & Services
    101020 Oil, Gas & Consumable Fuels: 10102010 Integrated Oil & Gas; 10102020 Oil & Gas Exploration & Production; 10102030 Oil & Gas Refining & Marketing; 10102040 Oil & Gas Storage & Transportation; 10102050 Coal & Consumable Fuels
15 Materials
  1510 Materials
    151010 Chemicals: 15101010 Commodity Chemicals; 15101020 Diversified Chemicals; 15101030 Fertilizers & Agricultural Chemicals; 15101040 Industrial Gases; 15101050 Specialty Chemicals
    151020 Construction Materials: 15102010 Construction Materials
    151030 Containers & Packaging: 15103010 Metal, Glass & Plastic Containers; 15103020 Paper & Plastic Packaging Products & Materials
    151040 Metals & Mining: 15104010 Aluminum; 15104020 Diversified Metals & Mining; 15104025 Copper; 15104030 Gold; 15104040 Precious Metals & Minerals; 15104045 Silver; 15104050 Steel
    151050 Paper & Forest Products: 15105010 Forest Products; 15105020 Paper Products
20 Industrials
  2010 Capital Goods
    201010 Aerospace & Defense: 20101010 Aerospace & Defense
    201020 Building Products: 20102010 Building Products
    201030 Construction & Engineering: 20103010 Construction & Engineering
    201040 Electrical Equipment: 20104010 Electrical Components & Equipment; 20104020 Heavy Electrical Equipment
    201050 Industrial Conglomerates: 20105010 Industrial Conglomerates
    201060 Machinery: 20106010 Construction Machinery & Heavy Transportation Equipment; 20106015 Agricultural & Farm Machinery; 20106020 Industrial Machinery & Supplies & Components
    201070 Trading Companies & Distributors: 20107010 Trading Companies & Distributors
  2020 Commercial & Professional Services
    202010 Commercial Services & Supplies: 20201010 Commercial Printing; 20201050 Environmental & Facilities Services; 20201060 Office Services & Supplies; 20201070 Diversified Support Services; 20201080 Security & Alarm Services
    202020 Professional Services: 20202010 Human Resource & Employment Services; 20202020 Research & Consulting Services; 20202030 Data Processing & Outsourced Services
  2030 Transportation
    203010 Air Freight & Logistics: 20301010 Air Freight & Logistics
    203020 Passenger Airlines: 20302010 Passenger Airlines
    203030 Marine Transportation: 20303010 Marine Transportation
    203040 Ground Transportation: 20304010 Rail Transportation; 20304030 Cargo Ground Transportation; 20304040 Passenger Ground Transportation
    203050 Transportation Infrastructure: 20305010 Airport Services; 20305020 Highways & Railtracks; 20305030 Marine Ports & Services
25 Consumer Discretionary
  2510 Automobiles & Components
    251010 Automobile Components: 25101010 Automotive Parts & Equipment; 25101020 Tires & Rubber
    251020 Automobiles: 25102010 Automobile Manufacturers; 25102020 Motorcycle Manufacturers
  2520 Consumer Durables & Apparel
    252010 Household Durables: 25201010 Consumer Electronics; 25201020 Home Furnishings; 25201030 Homebuilding; 25201040 Household Appliances; 25201050 Housewares & Specialties
    252020 Leisure Products: 25202010 Leisure Products
    252030 Textiles, Apparel & Luxury Goods: 25203010 Apparel, Accessories & Luxury Goods; 25203020 Footwear; 25203030 Textiles
  2530 Consumer Services
    253010 Hotels, Restaurants & Leisure: 25301010 Casinos & Gaming; 25301020 Hotels, Resorts & Cruise Lines; 25301030 Leisure Facilities; 25301040 Restaurants
    253020 Diversified Consumer Services: 25302010 Education Services; 25302020 Specialized Consumer Services
  2550 Consumer Discretionary Distribution & Retail
    255010 Distributors: 25501010 Distributors
    255030 Broadline Retail: 25503030 Broadline Retail
    255040 Specialty Retail: 25504010 Apparel Retail; 25504020 Computer & Electronics Retail; 25504030 Home Improvement Retail; 25504040 Other Specialty Retail; 25504050 Automotive Retail; 25504060 Homefurnishing Retail
30 Consumer Staples
  3010 Consumer Staples Distribution & Retail
    301010 Consumer Staples Distribution & Retail: 30101010 Drug Retail; 30101020 Food Distributors; 30101030 Food Retail; 30101040 Consumer Staples Merchandise Retail
  3020 Food, Beverage & Tobacco
    302010 Beverages: 30201010 Brewers; 30201020 Distillers & Vintners; 30201030 Soft Drinks & Non-alcoholic Beverages
    302020 Food Products: 30202010 Agricultural Products & Services; 30202030 Packaged Foods & Meats
    302030 Tobacco: 30203010 Tobacco
  3030 Household & Personal Products
    303010 Household Products: 30301010 Household Products
    303020 Personal Care Products: 30302010 Personal Care Products
35 Health Care
  3510 Health Care Equipment & Services
    351010 Health Care Equipment & Supplies: 35101010 Health Care Equipment; 35101020 Health Care Supplies
    351020 Health Care Providers & Services: 35102010 Health Care Distributors; 35102015 Health Care Services; 35102020 Health Care Facilities; 35102030 Managed Health Care
    351030 Health Care Technology: 35103010 Health Care Technology
  3520 Pharmaceuticals, Biotechnology & Life Sciences
    352010 Biotechnology: 35201010 Biotechnology
    352020 Pharmaceuticals: 35202010 Pharmaceuticals
    352030 Life Sciences Tools & Services: 35203010 Life Sciences Tools & Services
40 Financials
  4010 Banks
    401010 Banks: 40101010 Diversified Banks; 40101015 Regional Banks
  4020 Financial Services
    402010 Financial Services: 40201020 Diversified Financial Services; 40201030 Multi-Sector Holdings; 40201040 Specialized Finance; 40201050 Commercial & Residential Mortgage Finance; 40201060 Transaction & Payment Processing Services
    402020 Consumer Finance: 40202010 Consumer Finance
    402030 Capital Markets: 40203010 Asset Management & Custody Banks; 40203020 Investment Banking & Brokerage; 40203030 Diversified Capital Markets; 40203040 Financial Exchanges & Data
    402040 Mortgage Real Estate Investment Trusts (REITs): 40204010 Mortgage REITs
  4030 Insurance
    403010 Insurance: 40301010 Insurance Brokers; 40301020 Life & Health Insurance; 40301030 Multi-line Insurance; 40301040 Property & Casualty Insurance; 40301050 Reinsurance
45 Information Technology
  4510 Software & Services
    451020 IT Services: 45102010 IT Consulting & Other Services; 45102030 Internet Services & Infrastructure
    451030 Software: 45103010 Application Software; 45103020 Systems Software
  4520 Technology Hardware & Equipment
    452010 Communications Equipment: 45201020 Communications Equipment
    452020 Technology Hardware, Storage & Peripherals: 45202030 Technology Hardware, Storage & Peripherals
    452030 Electronic Equipment, Instruments & Components: 45203010 Electronic Equipment & Instruments; 45203015 Electronic Components; 45203020 Electronic Manufacturing Services; 45203030 Technology Distributors
  4530 Semiconductors & Semiconductor Equipment
    453010 Semiconductors & Semiconductor Equipment: 45301010 Semiconductor Materials & Equipment; 45301020 Semiconductors
50 Communication Services
  5010 Telecommunication Services
    501010 Diversified Telecommunication Services: 50101010 Alternative Carriers; 50101020 Integrated Telecommunication Services
    501020 Wireless Telecommunication Services: 50102010 Wireless Telecommunication Services
  5020 Media & Entertainment
    502010 Media: 50201010 Advertising; 50201020 Broadcasting; 50201030 Cable & Satellite; 50201040 Publishing
    502020 Entertainment: 50202010 Movies & Entertainment; 50202020 Interactive Home Entertainment
    502030 Interactive Media & Services: 50203010 Interactive Media & Services
55 Utilities
  5510 Utilities
    551010 Electric Utilities: 55101010 Electric Utilities
    551020 Gas Utilities: 55102010 Gas Utilities
    551030 Multi-Utilities: 55103010 Multi-Utilities
    551040 Water Utilities: 55104010 Water Utilities
    551050 Independent Power and Renewable Electricity Producers: 55105010 Independent Power Producers & Energy Traders; 55105020 Renewable Electricity
60 Real Estate
  6010 Equity Real Estate Investment Trusts (REITs)
    601010 Diversified REITs: 60101010 Diversified REITs
    601025 Industrial REITs: 60102510 Industrial REITs
    601030 Hotel & Resort REITs: 60103010 Hotel & Resort REITs
    601040 Office REITs: 60104010 Office REITs
    601050 Health Care REITs: 60105010 Health Care REITs
    601060 Residential REITs: 60106010 Multi-Family Residential REITs; 60106020 Single-Family Residential REITs
    601070 Retail REITs: 60107010 Retail REITs
    601080 Specialized REITs: 60108010 Other Specialized REITs; 60108020 Self-Storage REITs; 60108030 Telecom Tower REITs; 60108040 Timber REITs; 60108050 Data Center REITs
  6020 Real Estate Management & Development
    602010 Real Estate Management & Development: 60201010 Diversified Real Estate Activities; 60201020 Real Estate Operating Companies; 60201030 Real Estate Development; 60201040 Real Estate Services
```

Implementation: build `sub_name -> (code8, industry6, group4, sector2)` from this table, map each Wikipedia row by name (names are unique across the 163 sub-industries), apply the alias `Specialty Stores -> Other Specialty Retail`, and fail loudly on any other unmapped name. Note that the 6-digit "industry" is one row of this list; several industries contain a single sub-industry (e.g. 201010, 201020, 201030, 201050, 201070, 203010 ...), in which case the industry fallback adds **no** new peers - fallback will fail for those and the stock gets no signal. Log that case separately.

### 3.3 Historical GICS changes and what they imply

| Change | Effective | What moved | Source |
|---|---|---|---|
| Real Estate becomes its own (11th) sector | after close 2016-08-31 (index implementation 2016-09-16) | Equity REITs and Real Estate Management & Development leave Financials; Mortgage REITs stay in Financials; structure became 11 sectors / 24 industry groups / 68 industries / 157 sub-industries | S&P DJI press release [S] |
| Communication Services replaces Telecommunication Services | after close 2018-09-21 | Media industry group moves out of Consumer Discretionary (Netflix named in the sources; Disney and Comcast from memory [M]) and interactive media (Alphabet, Facebook) out of Information Technology into a new Media & Entertainment industry group (Media, Entertainment, Interactive Media & Services) | ASX notice / S&P DJI [S] |
| 2023 revisions | after close 2023-03-17 | "Data Processing & Outsourced Services" discontinued: Visa, Mastercard, PayPal, Fiserv, FIS, Global Payments, FleetCor, Jack Henry move IT -> Financials (new sub-industry "Transaction & Payment Processing Services"); payroll processors (ADP, Paychex) -> Industrials; Amazon from "Internet & Direct Marketing Retail" to new "Broadline Retail"; Target, Dollar General, Dollar Tree from Consumer Discretionary to Consumer Staples; renamings such as "Airlines" -> "Passenger Airlines" and "Road & Rail" -> "Ground Transportation" (old names from memory [M]; the new names are in the parsed table [D]). Only 14 S&P 500 stocks changed sector (3.7% of index weight) | SSGA / Indexology articles [S] |

**Bias from using today's GICS for 2012-2026:** peers are assigned with hindsight. (a) Reclassified names have the "wrong-for-the-time" peer group before their change dates; (b) mergers/spin-offs and business-model drift (a company's sub-industry today may not reflect what it did in 2013); (c) 154 sub-industry labels are re-cut in 2018/2023 so historical peer sets are cleaner than anything a real-time user had. Sign of the bias is ambiguous (peer sets are probably *more* accurate than real-time ones, which flatters the comps signal). Historical point-in-time GICS exists only in paid data (S&P Capital IQ / Compustat historical GICS) [A - Springer RQFA description of the S&P "spgicm" history]. Mitigations that fit a free-data project: (i) a sensitivity run that drops the stocks and sub-industries touched by the 2018 and 2023 reshuffles (list above), (ii) report results for pre-2018 and post-2018 separately, (iii) state the limitation. Katselas-Sidhu-Yu (2017) show dynamic vs static GICS matters in practice [A].

### 3.4 SEC EDGAR XBRL data (already cached in the repo) [D]

- `cache/sec/companyfacts.zip` (20,472 files, `CIK##########.json`, newest file dates in Oct 2026) and `cache/sec/submissions.zip` (994,773 files incl. pagination files `CIK..-submissions-00N.json`) are present. SEC says companyfacts.zip is rebuilt nightly (~3 a.m. ET) and recommends the bulk files for large pulls [S SEC API page]. SEC's fair-access policy asks automated clients to declare a User-Agent with a contact and to stay under about 10 requests per second [M - the API page I fetched does not state this]; put a **team/organization contact** there, not a personal email. The bulk files avoid the rate-limit issue entirely.
- **companyfacts record shape:** `{"start","end","val","accn","fy","fp","form","filed","frame"}` per fact; flows are duration facts (3-month, 6-month YTD, 9-month YTD, 12-month), balance-sheet items are instants (no `start`). Cash-flow items in 10-Qs are **cumulative YTD**, so TTM must be built by differencing. Q4 is never reported on its own.
- **Point-in-time rule:** use only facts with `filed` <= decision date; when the same (tag, start, end) appears in several filings (restatements, comparatives), take the one with the latest `filed` <= decision date. For intraday precision join `accn` to `submissions` -> `acceptanceDateTime` (UTC; verified present) and treat filings accepted after 16:00 ET as available the next trading day.
- **Phase-in:** XBRL began with fiscal periods ending after 2009-06-15 (large accelerated filers > $5B float), 2010-06-15 (other large accelerated) and 2011-06-15 (everyone else, incl. most S&P 600 names) [S Willkie / Husch Blackwell]. This limits the backtest start to early 2012 at the earliest.
- **Tag drift is real (verified on Apple, Exxon, Alphabet in the cache):**
  - Apple's revenue appears under `SalesRevenueNet` (to 2018), `Revenues` (to 2018) and `RevenueFromContractWithCustomerExcludingAssessedTax` (2017+); `InterestExpense` stops in 2023.
  - Exxon has **no `OperatingIncomeLoss`** at all and no `LongTermDebt`; it has `DebtCurrent`, `LongTermDebtNoncurrent` (ends 2017), `DepreciationDepletionAndAmortization`.
  - Alphabet has **no `DepreciationDepletionAndAmortization`** (it exposes `Depreciation` and `AmortizationOfIntangibleAssets`), no `EntityCommonStockSharesOutstanding` in `dei` (multi-class issuers drop the cover-page share count), and no `PaymentsToAcquireBusinessesNetOfCashAcquired`.
  - Therefore every metric needs a **fallback chain** and a logged coverage audit (Section 5.2).
- **`submissions` fields available:** `sic`, `sicDescription`, `fiscalYearEnd`, `category`, per-filing `form`, `filingDate`, `reportDate`, `acceptanceDateTime`, `items` (8-K item numbers, e.g. "2.02,9.01"), `isXBRL`. Useful for the SIC-3 robustness peer definition (Alford's own definition) and for merger flags (8-K item 2.01).

### 3.5 Prices, rates and factors

- **Prices:** yfinance 1.7.0 is installed in the repo `.venv` [D] (with pandas 3.0.6, numpy 2.5.4, scipy 1.18.1, statsmodels 0.15.0, matplotlib 3.11.2, pyarrow). Use `auto_adjust=False` to get raw `Close` (split-adjusted by Yahoo, not dividend-adjusted), `Adj Close` for total returns, and `Stock Splits` for share-count alignment. Yahoo drops many delisted tickers -> survivorship (Section 9).
- **yfinance for the live cross-check:** `Ticker.info` (Yahoo fields such as `forwardPE`, `trailingPE`, `marketCap`, `enterpriseValue`, `ebitda`, `totalDebt`, `totalCash`, `beta` - names come from Yahoo's API and should be checked at runtime [M]); `Ticker.earnings_estimate`, `eps_trend`, `revenue_estimate`, `growth_estimates`, `quarterly_income_stmt`, `quarterly_balance_sheet`, `quarterly_cash_flow` exist as properties in the installed version [D]. Yahoo statements cover only the most recent ~4-5 quarters, so **yfinance cannot supply the history needed for the backtest** [M].
- **Risk-free rate:** FRED `DGS10` (10-year Treasury constant maturity, percent) for WACC; the repo already stores the 13-week bill (`data/IRX.csv`) for the cash leg and Sharpe.
- **Factors:** Ken French library (data through **August 2026** [D]): 5-factor (2x3) monthly `F-F_Research_Data_5_Factors_2x3_CSV.zip`, momentum `F-F_Momentum_Factor_CSV.zip` at http://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html.

---

## 4. Exact formulas

Conventions: `d` = decision date (month-end trading day); all inputs use only information available at `d` (Section 3.4). TTM for a flow item X = FY(last 10-K) + YTD(current 10-Q) - YTD(same period last year) (if no 10-Q since the last 10-K, TTM = FY). Balance-sheet items are the latest instant fact on or before `d`.

### 4.1 Market cap, EV, P/E, EV/EBITDA

```
shares_rep   = WeightedAverageNumberOfDilutedSharesOutstanding of the latest quarter (3-month fact)    # covers all share classes
               fallback: dei:EntityCommonStockSharesOutstanding (cover page, single-class issuers only)
split_adj    = product of split ratios with ex-date AFTER the filing date of that fact (through today)  # puts shares in the same units as yfinance's split-adjusted Close
MarketCap    = Close_d(raw, split-adjusted) * shares_rep * split_adj

P/E (TTM)    = MarketCap / NetIncomeLoss_TTM            (attributable to parent; equals Price / diluted EPS_TTM up to share-count timing)
Debt         = DebtCurrent + LongTermDebtNoncurrent + FinanceLeaseLiability(current+noncurrent)
               (fallback chains in 5.2; exclude operating-lease liabilities because operating-lease cost is already inside EBITDA)
Cash         = CashAndCashEquivalents + ShortTermInvestments / MarketableSecuritiesCurrent
EV           = MarketCap + Debt + PreferredStock(book) + NoncontrollingInterest(book) - Cash
EBIT_TTM     = OperatingIncomeLoss_TTM          fallback: IncomeLossFromContinuingOperationsBeforeIncomeTaxes... + InterestExpense (flag 'ebit_proxy')
DA_TTM       = DepreciationDepletionAndAmortization_TTM   (cash-flow statement)   fallback chain in 5.2
EBITDA_TTM   = EBIT_TTM + DA_TTM
EV/EBITDA    = EV / EBITDA_TTM
```

A multiple is **valid** only if its denominator is > 0 (and EV > 0); a negative or zero multiple is "ignored" per the doc, never set to 0.

LFY (last fiscal year) variant: same formulas with the FY facts of the most recent 10-K instead of TTM; market cap is still current.

### 4.2 Net Debt / EBITDA

```
NetDebt = Debt - Cash                         # Debt incl. finance leases, Cash incl. short-term investments
ND_EBITDA = NetDebt / EBITDA_TTM              # defined only if EBITDA_TTM > 0
pass_leverage = (EBITDA_TTM > 0) and (ND_EBITDA <= 3.0)
labels: ND_EBITDA < 0 "net cash (great)";  0 <= x <= 1 "low";  1 < x <= 3 "ok";  x > 3 reject
```
Interpretation: "years of EBITDA to repay net debt". Sensitivities: cash-only (no short-term investments); cut-offs 2.0 / 3.0 / 4.0 / none.

### 4.3 Free cash flow and quality

```
FCF_p = NetCashProvidedByUsedInOperatingActivities_p - Capex_p       # Capex = PaymentsToAcquirePropertyPlantAndEquipment (fallback PaymentsToAcquireProductiveAssets)
FCF_ok = (FCF_TTM > 0) and (number of the last 3 completed fiscal years with FCF > 0 is >= 2)

OM_k   = OperatingIncomeLoss_FYk / Revenue_FYk,  k = 0..3  (four most recent completed fiscal years, oldest first), TTM margin OM_ttm
slope  = OLS slope of OM_k on year index (percentage points per year)
margin_ok = (n_years >= 3) and (slope >= -0.5 pp/yr) and (OM_ttm >= OM_FY0 - 1.0 pp) and (OM_ttm > 0)
quality_ok = FCF_ok and margin_ok
```
Why not "slope >= 0"? For a company whose margin is pure noise around a constant, slope < 0 half the time, so a strict rule rejects ~50% of genuinely stable companies. The tolerance (-0.5 pp/yr, i.e. ~-2 pp over 4 years; and no more than 1 pp recent drop) is the "stable" part; positive slopes are "improving". Window = 4 fiscal years (the doc says 3-5; sensitivities 3 and 5). Revenue chain: `RevenueFromContractWithCustomerExcludingAssessedTax` -> `Revenues` -> `SalesRevenueNet` (pick, per fiscal year, the first tag that exists).

### 4.4 ROIC and WACC

```
t_eff   = IncomeTaxExpenseBenefit_TTM / PretaxIncome_TTM
t       = clip(t_eff, 0.10, 0.35)  if PretaxIncome_TTM > 0 else statutory (0.35 before 2018, 0.21 from 2018)
NOPAT   = EBIT_TTM * (1 - t)
IC      = Debt + TotalEquity(including noncontrolling interest) - Cash                 # financing approach (Damodaran-style: book debt + book equity - cash [S])
IC_avg  = average of IC at the latest quarter-end and IC four quarters earlier
ROIC    = NOPAT / IC_avg        (if IC_avg <= 0 and NOPAT > 0: treat as ROIC = +inf, flag 'capital_light')

beta_raw = OLS slope of weekly total returns (Wed-Wed or Fri-Fri) on SPY weekly total returns, last 104 weeks, min 90   (60-month version is the sensitivity: LNT used 60 monthly, min 30 [V])
beta_adj = 0.67 * beta_raw + 0.33                                    # Blume adjustment (Blume 1971; the 0.67/0.33 weights are the usual convention [S/M])
Ke      = Rf + beta_adj * ERP,   Rf = 10y Treasury yield on d,   ERP = 5.0%     # LNT also used 5% [V]
Kd      = clip(InterestExpense_TTM / average(Debt now, Debt 4 quarters ago), Rf, 12%);  if Debt < 1% of MarketCap or interest missing -> Rf + 2%
E = MarketCap;  D = Debt;  V = E + D
WACC    = (E/V)*Ke + (D/V)*Kd*(1 - t)
pass_roic = ROIC > WACC
```
Watch-outs: (i) Rf was ~1.5-2.5% in 2012-2021 and 4%+ since 2022 [M], so the same filter is tighter in the test period - report its pass rate by year; (ii) the 2-year beta window is deliberately matched to the 2-year IPO rule; (iii) goodwill stays inside invested capital (it measures return on what was actually paid).

### 4.5 Definitions: recent IPO and recent merger

```
listing_age_days = d - min(first_available_price_date (yfinance), first_filing_date_of_any_form for the CIK (submissions))
recent_ipo       = listing_age_days < 730            # 2 years; sensitivities 365 / 1095; also implies fewer than 104 weekly returns -> no beta

acq_intensity    = PaymentsToAcquireBusinessesNetOfCashAcquired_TTM / Assets(4 quarters ago)
share_jump       = |diluted shares_now / diluted shares 4 quarters ago - 1|
asset_jump       = Assets_now / Assets(4 quarters ago) - 1
recent_merger    = (acq_intensity >= 0.10) or (share_jump >= 0.25) or (asset_jump >= 0.40 and an 8-K with Item 2.01 filed in the last 4 quarters)
```
Rationale: TTM earnings contain a partial year of the acquired business while EV already contains the acquired debt/equity, so the multiple is biased until four reported quarters have passed - that is exactly how long the flag lasts (the deal quarter is inside the TTM window). The 10% / 25% / 40% thresholds are judgment values (not from a paper); run 5%/10%/20% as a sensitivity. 8-K Item 2.01 ("Completion of Acquisition or Disposition of Assets") comes from `submissions.items` [D: field exists]. Apply both flags to peers **and** targets.

---

## 5. Algorithm specification

### 5.1 Doc rule -> code-level interpretation (every rule)

| ID | Doc rule | Interpretation implemented | Justification |
|---|---|---|---|
| R1 | GICS sub-industry peers | `peers0 = {j != i : sub(j) == sub(i)}` (8-digit code). Target is always excluded from its own benchmark. | LNT: target removed from comparables [V]; BLO/CLS support GICS. |
| R2 | 4-5 peers | If size filter ON: keep up to **5** peers (the ones closest to the target in `abs(ln(mc_j/mc_i))`); need **>= 4**. If size filter OFF: use **all** valid same-sub-industry peers (need >= 4), no cap. | Alford 6, Schreiner 4-8, Cooper-Lambertides 5-10 [S/V]; the doc itself says 4-5. Max-peers sensitivity {5, 8, 10}. |
| R3 | Market cap 0.5x-2x | If size filter ON: `0.5 <= mc_j/mc_i <= 2.0`. | Doc rule; grid dimension (evidence for it is weak, 2.6). |
| R4 | <4 peers after size filtering -> expand to GICS industry | Recompute `peers0` with the 6-digit industry code and re-apply the same size rule; need >= 4; else no signal for that multiple. Log `peer_level in {sub, industry, none}`. | Doc rule; CLS 2007: 6-digit nearly as homogeneous as 8-digit [V]. |
| R5 | P/E and EV/EBITDA, both | Each multiple has its own eligibility and peer set. **BUY comps signal requires both multiples to pass the discount test (AND).** Rank by the average of the two discounts. Alternatives (OR, average-only, P/E-only, EV-only) are pre-registered extensions. | "Cover each other's blind spots" reads as confirmation; AND is the conservative reading. |
| R6 | Same time periods; TTM and years | Primary = TTM for target **and** all peers at the same decision date `d`; secondary = last fiscal year (LFY). Staleness gate: the latest balance sheet/TTM period end must be within **135 days** of `d` for the target and for every peer. | Aligns firms with different fiscal year-ends; KKP did TTM [V]. |
| R7 | Ignore negative P/E, EV/EBITDA | Any company (peer or target) with `NI_TTM <= 0` is invalid for P/E; `EBITDA_TTM <= 0` or `EV <= 0` invalid for EV/EBITDA. Never replaced by 0. | LNT require positive values [V]. |
| R8 | Outliers: P/E > 40, EV/EBITDA > 35 | `pe > PE_CAP` or `ev_ebitda > EV_CAP` -> company invalid for that multiple, **as a peer and as a target** (a capped target cannot be a BUY). Caps are grid values {30,40,50} and {25,35,45}. | Exclusion not winsorization: the doc says "don't use". |
| R9 | Drop peers with missing data | Missing = any required field absent, stale (R6) or failing the tag-fallback chain. **Drop, never impute or carry forward.** Dropping happens *before* counting peers, so a drop can trigger R4. | LNT/KKP drop incomplete observations [V]. |
| R10 | Exclude recent IPOs and mergers | `recent_ipo` / `recent_merger` flags (4.5) exclude the company as peer and as target. | Doc rationale (unstable numbers). |
| R11 | Multiples within 0.5x-2x of median | After R2-R4 select the peer set, compute `m0 = median(x_j)`; keep `0.5*m0 <= x_j <= 2.0*m0`; need **>= 3 kept** (else no signal); the benchmark is `B = median(kept)`. Single pass, no iteration. Optional E6: also require `x_i >= 0.5*B` for the target (guards against one-off gains and data errors). | Doc wording is ambiguous; this is the standard outlier-trim reading. |
| R12 | BUY if target multiple < 0.85 x median | `disc_m = 1 - x_i / B_m`; `pass_m = disc_m > theta` with `theta in {0.10, 0.15, 0.20}`; 0.85x corresponds to `theta = 0.15`. | Doc rule. |
| R13 | Pre-register the grid | Section 7.1. | Doc rule. |
| R14 | Build on one period, confirm on another | Train 2012-2018, test 2019-2026 (Section 7.3). | Doc rule. |
| R15 | Stable plateau, not the single best | Neighbourhood-average rule (7.4). | Doc rule. |
| R16 | Regression tables, all permutations, 3D interpolation | 7.5-7.6. | Doc rule. |
| K1 | Net debt/EBITDA | 4.2: pass if `EBITDA > 0` and `ND/EBITDA <= 3.0`. Applies to the **target only**. | Fills the 0-1x gap in the doc. |
| K2 | Quality: free cash flow, margins stable/improving over 3-5 yrs | 4.3. Target only. | Precise and testable. |
| K3 | ROIC > WACC | 4.4. Target only. | |
| M1 | Key-metric filters do not apply to peers | Peers must only have valid, positive, in-cap multiples. | Peer medians should describe the industry, not only its best companies (LNT use all industry firms [V]). |
| M2 | Universe | S&P 500/400/600 constituents; exclude GICS sectors 40 (Financials) and 60 (Real Estate): leverage, EBITDA and P/E are not comparable for banks/insurers/REITs. Utilities (55) stay in (they mostly fail K1 as targets but give clean peer sets). Market-cap floor $300M for data quality and, for the live screen only, a $5 minimum share price (competition rule reported in `research/07_competition_rules.md`). | The doc's "no financials/utilities" line sits under the Magic Formula section; make utilities a toggle. |

### 5.2 Tag fallback chains (in priority order; log which one was used)

| Item | Chain |
|---|---|
| Revenue | `RevenueFromContractWithCustomerExcludingAssessedTax` -> `Revenues` -> `SalesRevenueNet` -> `SalesRevenueGoodsNet` |
| Operating income | `OperatingIncomeLoss` -> (`IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` + `InterestExpense`) flagged `ebit_proxy` |
| D&A (cash-flow) | `DepreciationDepletionAndAmortization` -> `DepreciationAndAmortization` -> `DepreciationAmortizationAndAccretionNet` -> `Depreciation` + `AmortizationOfIntangibleAssets` (Alphabet pattern) |
| Net income | `NetIncomeLoss` (parent). Not `ProfitLoss` (includes NCI) |
| Pretax income | `IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest` -> `...MinorityInterestAndIncomeLossFromEquityMethodInvestments` |
| Interest expense | `InterestExpense` -> `InterestExpenseNonoperating` -> `InterestExpenseDebt` |
| CFO / Capex | `NetCashProvidedByUsedInOperatingActivities`; `PaymentsToAcquirePropertyPlantAndEquipment` -> `PaymentsToAcquireProductiveAssets` |
| Debt | (a) `DebtCurrent` + `LongTermDebtNoncurrent`; (b) `LongTermDebt` + `ShortTermBorrowings` + `CommercialPaper`; (c) `LongTermDebtNoncurrent` + `LongTermDebtCurrent` + `ShortTermBorrowings` + `CommercialPaper`; plus `FinanceLeaseLiabilityCurrent` + `FinanceLeaseLiabilityNoncurrent` |
| Cash | `CashAndCashEquivalentsAtCarryingValue` (+ `ShortTermInvestments` or `MarketableSecuritiesCurrent` or `AvailableForSaleSecuritiesDebtSecuritiesCurrent`) |
| Equity | `StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest` -> `StockholdersEquity` + `MinorityInterest` |
| Acquisitions | `PaymentsToAcquireBusinessesNetOfCashAcquired` (missing = 0, but flag low confidence) |
| Shares | `WeightedAverageNumberOfDilutedSharesOutstanding` (3-month fact) -> `dei:EntityCommonStockSharesOutstanding` |

Run a **coverage audit** on the first full pass: percent of (company, quarter) with each field found, overall and by sector; any field below ~85% coverage in a sector needs a better chain before trusting results. Cross-check 20 random names against yfinance `totalDebt`, `ebitda`, `enterpriseValue` (tolerance ~15%).

### 5.3 Step-by-step procedure for one decision date `d`

```
INPUT: d, universe table U (ticker, cik, sector, sub_code8, industry_code6), params P
P = {theta, pe_cap, ev_cap, size_filter, basis in {TTM, LFY}, size_lo=0.5, size_hi=2.0, k_min=4, k_max=5, trim_lo=0.5, trim_hi=2.0, k_trim_min=3,
     nd_max=3.0, stale_days=135, ipo_days=730, topN=20, min_hold=5}

STEP 1  Snapshot (point-in-time). For every company j in U (excluding sectors 40, 60; mc >= 300M):
        build price, shares, MarketCap_j, flows (TTM or LFY), balance-sheet items, using only filings available at d.
        Compute: pe_j, evebitda_j, ipo/merger flags, staleness flag.
STEP 2  Eligibility per multiple m in {pe, ev}:
        ok_m(j) = fresh and not recent_ipo and not recent_merger and x_m(j) is defined and 0 < x_m(j) <= cap_m
STEP 3  For each stock i with ok_pe(i) and ok_ev(i):                      # stocks failing either multiple cannot be BUY under AND
          for m in {pe, ev}:
            peers, level = pick_peers(i, m)                               # sub-industry, then industry fallback; size window; closest k_max; need >= k_min
            if peers is None: no_signal(i); break
            m0 = median(x_m[peers]);  kept = {j: trim_lo*m0 <= x_m(j) <= trim_hi*m0}
            if len(kept) < k_trim_min: no_signal(i); break
            B_m = median(x_m[kept]);  disc_m = 1 - x_m(i)/B_m;  pass_m = disc_m > theta
          comps_buy(i) = pass_pe and pass_ev;   score(i) = (disc_pe + disc_ev)/2
STEP 4  Key-metric gates on comps_buy stocks:  ND/EBITDA <= nd_max ; quality_ok ; ROIC > WACC    (all must pass)
STEP 5  Portfolio: sort survivors by score desc, ties by lower ND/EBITDA; take top topN;
        weights w = 1/max(k, min_hold) each; remainder (if k < min_hold) in cash (T-bill)
STEP 6  Log diagnostics: counts at each stage, fallback rate (level != sub), average peer count, coverage by sector, tag chain usage.
OUTPUT: weights, diagnostics.
```

`pick_peers(i, m)`:
```
for level in ["sub", "industry"]:
    pool = [j for j in U if j != i and ok_m(j) and code_at(j, level) == code_at(i, level)]
    if size_filter: pool = [j for j in pool if size_lo <= mc[j]/mc[i] <= size_hi]
    if len(pool) >= k_min:
        if size_filter and len(pool) > k_max: pool = sorted(pool, key=lambda j: abs(log(mc[j]/mc[i])))[:k_max]
        return pool, level
return None, "none"
```

### 5.4 Edge cases and decisions to record in the pre-registration

1. Two share classes of one company count once (by CIK); use the more liquid class for trading; market cap uses all-class diluted shares.
2. A target whose sub-industry is the only one inside its industry (single-sub-industry industries) gets no fallback; count it in the diagnostics.
3. Staleness: a stock that has not filed within 135 days of period end (e.g. March-quarter reporter at an Oct-20 decision date with no June filing yet) is treated as missing.
4. Negative or tiny denominators: P/E denominators < 1% of market cap are not special-cased; the 40x cap handles the extreme.
5. All ties and thresholds use strict inequalities as written (`>` for discount).
6. No hysteresis in the main spec (a name that stops qualifying is sold at the next rebalance). A turnover-reducing exit buffer (hold while discount > theta/2) is extension E7.

---

## 6. Backtest design

- **Universe/time:** current S&P 500/400/600 constituents (survivorship caveat, Section 9); signals at the last trading day of each month from **2012-01-31** to **2026-08-31** (XBRL phase-in and the 2-year price/4-fiscal-year history requirements prevent an honest 2011 start; Ken French data end August 2026). First signal month uses whatever 3+ fiscal years exist.
- **Timing:** signal uses data available at the close of `d` (filings accepted after 16:00 ET count from the next day); **trade at the close of the next trading day**; hold one month (to the close of the next month's `d+1`). Returns from `Adj Close` (dividends reinvested).
- **Portfolio:** top-N (N = 20) by average discount among stocks passing everything; equal weight; `min_hold = 5`; unfilled slots in cash earning the 13-week bill. Sensitivities: N in {10, 20, 30, all}.
- **Costs:** 10 bp per side as the default for S&P 1500 names; also 0 and 25 bp. Report turnover (average monthly one-way), average holdings, and share of months with k < 5.
- **Benchmarks:** (1) equal-weighted universe of all stocks with valid data on `d` (the comparator that cancels most survivorship), (2) SPY, (3) the same pipeline without the comps signal but with the key-metric gates (to isolate what comps add), (4) a naive "lowest P/E in each sub-industry" rule.
- **Statistics per cell:** annualised return, volatility, Sharpe (excess of the bill rate), Sortino, max drawdown, hit rate, turnover, number of positions; excess return and information ratio vs benchmark (1); CAPM alpha and **FF5 + momentum alpha** with Newey-West (3 lags) standard errors. Sharpe standard error is roughly sqrt((1 + SR^2/2)/years) [M Lo 2002] = **~0.38 for 7 years, ~0.36 for 7.7 years**: differences between cells smaller than ~0.4 are noise.
- **Holding-horizon check:** the sibling file `research/07_competition_rules.md` (another agent; I did not re-verify it) reports that the 2026-27 WInS trading window runs Sep 28 - Nov 6, 2026, so picks made on Oct 21 are held only ~12 trading days inside the contest, and that judging stresses the articulation and discipline of the strategy more than the P&L. A monthly-rebalance backtest therefore answers a slightly different question than the contest; also report non-overlapping 10-, 21-, 42- and 63-trading-day holding returns for the chosen cell, and lead with process (pre-registration, plateau, train/test) rather than backtest return.
- **Multiple-testing bookkeeping:** keep a counter of every configuration evaluated (54 grid cells + about 40 sensitivities and extensions); report the **Deflated Sharpe Ratio** (Bailey & Lopez de Prado 2014) of the chosen cell with that trial count, and prefer to quote the test-period result only once [A for DSR; Harvey-Liu-Zhu t > 3 hurdle is [M]].

---

## 7. Parameter grid and selection protocol

### 7.1 Pre-registered grid (write this into a dated file BEFORE running anything; commit it)

| Parameter | Levels | Doc value |
|---|---|---|
| `theta` (discount threshold) | 10%, 15%, 20% | 15% (0.85x) |
| `PE_CAP` | 30, 40, 50 | 40 |
| `EV_CAP` (EV/EBITDA) | 25, 35, 45 | 35 |
| `SIZE_FILTER` | on (0.5x-2x, closest 5) / off (all valid sub-industry peers) | on |
| `BASIS` | TTM (main grid); LFY as a follow-up test only | TTM |

Main grid = 3 x 3 x 3 x 2 = **54 cells** (TTM). Forward multiples are **explicitly pre-registered as "not backtestable"**.

Fixed (not tuned) in the main grid: key-metric thresholds (ND/EBITDA 3.0; FCF rule; margin tolerance; ROIC > WACC), IPO 730 days, merger thresholds, staleness 135 days, trim band 0.5x-2x, N = 20, 10 bp costs.

### 7.2 Follow-up tests (run ONLY at the selected cell and its neighbours; report all; never used for selection)

E1 LFY instead of TTM. E2 harmonic-mean benchmark instead of median. E3 combination rule: OR, average-discount-only, P/E only, EV/EBITDA only. E4 key-metric gates off one at a time (comps-only, +leverage, +quality, +ROIC) to measure each one's contribution; leverage cut-off {2, 3, 4, none}. E5 ROE-closest peers (KKP-style, same sub-industry, 5 closest on |ROE_i - ROE_j| and size) in place of the market-cap window. E6 target floor `x_i >= 0.5 B`. E7 exit buffer. E8 max peers {5, 8, 10}; trim band {0.33-3, 0.5-2, 0.67-1.5}; market-cap window {0.33-3, 0.5-2, 0.75-1.33}. E9 SIC-3 (from `submissions.sic`) peers instead of GICS. E10 drop reclassified names (2018/2023 lists). E11 pre-2018 vs post-2018. E12 N in {10, 20, 30, all}; costs {0, 10, 25 bp}. E13 quality window 3 / 4 / 5 years; beta window 104 weeks vs 60 months; ERP {4%, 5%, 6%}.

### 7.3 Train / test

- **Train:** signals 2012-01-31 ... 2018-12-31 (84 months). **Test:** 2019-01-31 ... 2026-08-31 (92 months). Rationale: the first window needs the XBRL phase-in to finish; the second contains the pandemic, the 2022 rate shock and the weak-value regime (Lev-Srivastava).
- **Confirmation criteria (written before looking):** for the cell chosen on train: (a) test excess return vs the equal-weighted universe > 0; (b) test Sharpe >= 50% of train Sharpe (a 50% haircut is already what McLean-Pontiff report as typical); (c) test FF5+MOM alpha positive; (d) across all 54 cells the Spearman correlation between train and test Sharpe is > 0 (parameter landscape persists). If (a)-(d) fail, report that the comps rule is **not validated** and use it only as a screening overlay.
- **Reverse check (optional):** train 2019-2026, test 2012-2018; plus an expanding-window walk-forward that re-selects every January using only past data.
- **Parsimony rule:** if the plateau cell does not beat the doc default (0.15 / 40 / 35 / size on) by more than one standard error of the Sharpe difference on train, keep the doc default.

### 7.4 Plateau selection rule

For each size-filter setting separately (treat it as a categorical, not a neighbour dimension): neighbours of a cell are cells differing by one step in exactly one of (`theta`, `PE_CAP`, `EV_CAP`), i.e. up to 6 in the interior (3 or 4 at corners/faces).

```
P(g)      = mean Sharpe_train over {g} union neighbours(g)
spread(g) = max - min of Sharpe_train over the same set
eligible  = cells with min Sharpe_train over the neighbourhood > 0, IR vs EW universe (neighbourhood mean) > 0, and months with k >= 5 at least 80% of the time
choose    g* = argmax P(g) over eligible cells; ties -> smaller spread, then closest to the doc default
flag      'spike' if Sharpe(g*) - P(g*) > 0.25 (the winner is much better than its neighbours)
```
With only 3 levels per axis the only interior cell is the centre (0.15 / 40 / 35), so edge cells have fewer neighbours; that is accepted, the `spread` tie-break and the `spike` flag protect against edge flukes. Pick the size-filter setting with the higher `P(g*)`; if within 0.1, prefer "on" only if it also improves the test-free diagnostic "average number of positions >= 10".

```python
import numpy as np, pandas as pd
def plateau_pick(cells: pd.DataFrame):          # columns: theta, pe_cap, ev_cap, size, sharpe_train, ir_train, share_k5
    out = []
    for size, df in cells.groupby("size"):
        idx = {(r.theta, r.pe_cap, r.ev_cap): r for r in df.itertuples()}
        ax = [sorted(df[c].unique()) for c in ("theta", "pe_cap", "ev_cap")]
        for key, r in idx.items():
            nb = [key]
            for a in range(3):
                i = ax[a].index(key[a])
                for j in (i - 1, i + 1):
                    if 0 <= j < len(ax[a]):
                        k2 = list(key); k2[a] = ax[a][j]; nb.append(tuple(k2))
            s = np.array([idx[k].sharpe_train for k in nb]); ir = np.mean([idx[k].ir_train for k in nb])
            out.append(dict(size=size, key=key, P=s.mean(), spread=s.max() - s.min(), minS=s.min(), ir=ir,
                            ok=(s.min() > 0 and ir > 0 and r.share_k5 >= 0.8), spike=(r.sharpe_train - s.mean()) > 0.25))
    res = pd.DataFrame(out)
    return res[res.ok].sort_values(["P", "spread"], ascending=[False, True]).head(5)
```

### 7.5 Regression tables

(a) **Cell-level**, 54 rows (train and test separately), dummy-coded with the doc's values as the reference category:
```python
import statsmodels.formula.api as smf
m = smf.ols("sharpe ~ C(theta, Treatment(0.15)) + C(pe_cap, Treatment(40)) + C(ev_cap, Treatment(35)) + C(size, Treatment('on'))",
            data=cells).fit(cov_type="HC3")
# add interaction terms (theta:size, pe_cap:ev_cap) as a second table; repeat with monthly alpha vs the EW universe as the dependent variable
```
(b) **Cell-month panel** (inference that respects the near-perfect overlap between cells): `ret_excess ~ same dummies`, cluster by month:
```python
panel["m"] = pd.factorize(panel["month"])[0]
m2 = smf.ols("ret_excess ~ C(theta, Treatment(0.15)) + C(pe_cap, Treatment(40)) + C(ev_cap, Treatment(35)) + C(size, Treatment('on'))",
             data=panel).fit(cov_type="cluster", cov_kwds={"groups": panel["m"]})
```
Cells are overlapping portfolios built from the same stocks, so table (a)'s standard errors are descriptive, not inferential; (b) is the one to quote. Report coefficients as "effect of moving this parameter from the doc value", with the train and test tables side by side.

### 7.6 3-D interpolated surface

Axes: `PE_CAP` (x), `EV_CAP` (y), Sharpe or alpha (z); one panel per `theta` (3 columns) and per size filter (2 rows) = 6 surfaces, train and test shown separately (the *difference* surface is the most informative picture of overfitting). With only 3x3 nodes per panel, interpolation is cosmetic: use a thin-plate spline with smoothing, and always show the heat-map of the raw 3x3 values next to it. Selection stays on the pre-registered nodes; do **not** pick an interpolated optimum between nodes.
```python
from scipy.interpolate import RBFInterpolator
import matplotlib.pyplot as plt, numpy as np
pts = df[["pe_cap", "ev_cap"]].to_numpy(float); z = df["sharpe"].to_numpy(float)
rbf = RBFInterpolator(pts, z, kernel="thin_plate_spline", smoothing=1e-2)
gx, gy = np.meshgrid(np.linspace(30, 50, 41), np.linspace(25, 45, 41))
gz = rbf(np.c_[gx.ravel(), gy.ravel()]).reshape(gx.shape)
ax = plt.figure().add_subplot(projection="3d"); ax.plot_surface(gx, gy, gz, cmap="viridis", alpha=0.85)
ax.scatter(pts[:, 0], pts[:, 1], z, color="k")
```
If you want a smoother picture, run a denser (visualisation-only) grid of caps (e.g. 20-60 / 15-55 in steps of 5) but treat it as exploratory and add its cell count to the trial counter.

---

## 8. Live signal for Wed 2026-10-21

1. **Timing.** Compute on Tue 2026-10-20 after the close with filings accepted through that afternoon; refresh `companyfacts.zip` / `submissions.zip` that evening (SEC rebuilds it nightly). Trade on 2026-10-21.
2. **Earnings-season staleness.** In the third week of October only a minority of S&P 1500 companies have reported September-quarter results, and XBRL arrives with the 10-Q (days to weeks after the press release). TTM is therefore through June 30, 2026 for most calendar-year firms (112 days old at 10-20) and through March/April 2026 for some off-cycle fiscal years; the 135-day staleness gate will drop March-quarter reporters that have not filed their June quarter. Do not "fix" this with press-release numbers in the quantitative signal; list those names separately for manual review.
3. **Parameters.** Use the cell selected on train and confirmed on test (Section 7.3). If the confirmation fails, use the doc defaults only as a screen and say so.
4. **Forward cross-check (information only, not tuned, not backtested).** For each candidate: yfinance `forwardPE` vs the median `forwardPE` of the same peers, EPS estimate revision (`eps_trend`), and `earnings_estimate` growth. Flag "forward-confirmed" if forward P/E < peer-median forward P/E; flag "value-trap risk" if the next-year EPS estimate is falling over 90 days. LNT show forward earnings multiples are the most accurate value drivers (IQR 0.317 vs 0.518 for GAAP EPS) [V], which is why the check is useful even though it cannot be backtested.
5. **Sanity checks before trusting a pick.** (i) Recompute the candidate's P/E, EV/EBITDA, net debt/EBITDA from the filings and compare with yfinance `trailingPE`, `enterpriseValue`/`ebitda`, `totalDebt`/`totalCash` (tolerate ~15%); (ii) read the latest 8-K Item 2.02 release for one-off gains/charges that distort TTM net income; (iii) confirm the peers in the printed peer table are real competitors; (iv) check the competition's tradable-universe rules - `research/07_competition_rules.md` reports (not verified by me): up to 200 trades, each trade <= 2x the security's daily volume, orders placed before 9:30 a.m. ET fill at the open, whole shares, comply with a $5 minimum price and US exchange-listed common stock only (the S&P 1500 satisfies the listing condition; apply the $5 price floor in the live screen).
6. **Output table per candidate:** ticker, sub-industry, peer level (sub/industry), peers used (names, market caps), P/E and EV/EBITDA vs benchmark and discount, ND/EBITDA, FCF flags, margin slope, ROIC vs WACC, forward cross-check flags, data-quality flags (tag fallbacks, `ebit_proxy`).

---

## 9. Biases, limitations and what I could not verify

**Biases that will inflate the backtest (state them to judges):**
1. **Survivorship / look-ahead universe:** only today's index members are in the universe and yfinance has gaps for delisted names; "cheap and later failed or removed" stocks are underrepresented, which hurts a value rule's *measured* risk more than a market-cap-weighted benchmark. Comparing with the equal-weighted same universe partially cancels it.
2. **Current GICS applied to history** (Section 3.3).
3. **Current index membership** includes companies added *because* they grew; S&P 400/600 change tables (2012+/2019+) allow partial correction only.
4. **No analyst forward estimates** -> the backtested signal is the weaker trailing one (LNT: the IQR of forward-P/E pricing errors is roughly 28-39% tighter than for historical-earnings P/E, 0.317 vs 0.518/0.442).
5. **Overfitting:** 54 cells + ~40 follow-ups on ~7-year windows; Sharpe standard error ~0.4.
6. **XBRL data quality:** tag drift (verified), restatements, multi-class share counts, mid-year fiscal-year changes; coverage audit is mandatory.
7. **Regime:** value and the quality premium behaved differently across 2012-2018 and 2019-2026; ROIC-WACC filter pass rate changes with Rf.
8. **Factor exposure:** equal-weighted S&P 1500 is tilted to small/value; judge alpha on FF5+MOM, not on raw return.
9. **Transaction costs / capacity** are not an issue at this scale but spreads in S&P 600 names are not zero.

**Not verified (do not cite as fact without checking):**
- Alford (1992) primary text (JSTOR) - only secondary descriptions. The "23.9-25.3%" and "4,698 firms" come from Lie & Lie (2002); a thesis quotes 24.41%-49.1% as the range across studies.
- Bhojraj-Lee-Oler (2003) and Bhojraj-Lee (2002) beyond their abstracts (no R-squared or error magnitudes).
- Asness-Porter-Stevens (2000) numbers; Cohen-Polk (1998) (relied on Cohen-Polk-Vuolteenaho's description); Avramov et al. magnitudes (paywalled); the Novy-Marx statement about industry adjustment.
- Damodaran's exact ROIC/tax-rate convention (secondary sources only); the Blume 0.67/0.33 weights as written in the 1971 paper; Harvey-Liu-Zhu t > 3 hurdle; Lo (2002) Sharpe standard-error formula (standard, from memory).
- Historical level of Rf by year; the 2026-27 competition's exact rules and horizon (taken from the sibling file `research/07_competition_rules.md`, not re-verified here).
- The share of S&P 1500 targets for which the sub-industry-with-size-window rule will find >= 4 peers (needs market caps; first diagnostic to run).
- The `submissions`-based IPO/merger flags and tag chains were designed from spot checks on three companies, not audited across 20,000 filers.

---

## 10. Suggested module layout (for whoever implements it)

(Not created in the repo; the repo currently has no research code. All of these libraries are already in `.venv`.)

```
comps/universe.py     scrape 3 Wikipedia tables, map sub-industry names -> codes (hierarchy above), dedupe by CIK, ticker->CIK via SEC company_tickers.json
comps/xbrl_pit.py     load companyfacts per CIK, apply tag chains, build point-in-time TTM/LFY/instant series with filed<=d and acceptance-time shift
comps/prices.py       yfinance download (auto_adjust=False), split table, weekly returns, cache to parquet
comps/signal.py       pick_peers, trim, discounts, key-metric gates, flags (5.3)
comps/backtest.py     monthly loop, costs, benchmarks, stats, FF5+MOM regressions (statsmodels)
comps/grid.py         54-cell runner, plateau_pick, dummy OLS, cell-month cluster OLS, surfaces
comps/live.py         Oct-20 run, forward P/E cross-check, candidate table
prereg_04.md          the dated, committed pre-registration (Section 7.1-7.3)
```
Unit tests worth writing first: (1) TTM builder on Apple (check against a hand calculation from the 10-K/10-Q), (2) split-adjusted market cap on a stock with a split (e.g. AAPL 2020-08), (3) peer selection on a hand-made 8-stock table including the fallback and trim branches, (4) PIT test that a restated value filed after `d` is never used.

---

## 11. References and URLs

Papers and primary sources I read (full text extracted):
- Liu, Nissim & Thomas (2002), "Equity Valuation Using Multiples", JAR 40(1): 135-172 - https://business.columbia.edu/sites/default/files-efs/pubfiles/318/Equity_Valuation_Using_Multiples.pdf ; record https://ideas.repec.org/a/bla/joares/v40y2002i1p135-172.html
- Knudsen, Kold & Plenborg (2017), "Stick to the Fundamentals and Discover Your Peers", FAJ 73(3): 85-105 - http://gregmccall.s3.amazonaws.com/Stick+to+the+Fundamentals+and+Discover+Your+Peers.pdf (CFA Institute copy marked "for personal use")
- Cooper & Lambertides (2023), "Optimal equity valuation using multiples: the number of comparable firms", EFM 29(4) - https://lbsresearch.london.edu/id/eprint/2712/1/Euro%20Fin%20Management%20-%202022%20-%20Cooper%20-%20Optimal%20equity%20valuation%20using%20multiples%20%20The%20number%20of%20comparable%20firms.pdf
- Chan, Lakonishok & Swaminathan (2007), "Industry Classifications and Return Comovement", FAJ 63(6) - https://www.lsvasset.com/pdf/research-papers/industry_FAJ.pdf
- Cohen, Polk & Vuolteenaho (2003), "The Value Spread", JF 58(2) - https://personal.lse.ac.uk/polk/research/jofi_5802005.pdf
- Lev & Srivastava, "Explaining the Recent Failure of Value Investing" - https://cfr.ivo-welch.org/forthcoming/papers/lev2021explaining.pdf
- Rhodes-Kropf, Robinson & Viswanathan (2005), JFE 77(3) - https://drupalgsb-test.paas.cc.columbia.edu/sites/default/files-efs/pubfiles/1706/mergers_jfe_copyedit.pdf ; https://scholars.duke.edu/publication/796083
- Yoon (2015), "Multiples Valuation and Abnormal Returns" (honors thesis) - https://sites.duke.edu/djepapers/files/2016/10/junyoon-dje.original.pdf
- Lie & Lie (2002), "Multiples Used to Estimate Corporate Value", FAJ 58(2) - https://www.biz.uiowa.edu/faculty/elie/ValByMult.pdf (source of the Alford description)
- Theses quoting Alford: https://lup.lub.lu.se/luur/download?fileOId=8877532&func=downloadFile&recordOId=8877531 ; https://repositorio-aberto.up.pt/bitstream/10216/130873/2/433629.pdf

Abstract/record pages only:
- Alford (1992), JAR 30(1): 94-108, DOI 10.2307/2491093 - https://ideas.repec.org/a/bla/joares/v30y1992i1p94-108.html ; https://www.jstor.org/stable/2491093 (not accessible)
- Bhojraj, Lee & Oler (2003), JAR 41(5): 745-774 - https://ideas.repec.org/a/bla/joares/v41y2003i5p745-774.html ; https://onlinelibrary.wiley.com/doi/abs/10.1046/j.1475-679X.2003.00122.x ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=356840
- Bhojraj & Lee (2002), JAR 40(2): 407-439 - https://ideas.repec.org/a/bla/joares/v40y2002i2p407-439.html
- Liu, Nissim & Thomas (2007), FAJ 63(2): 56-68 - https://ideas.repec.org/a/taf/ufajxx/v63y2007i2p56-68.html
- Asness, Porter & Stevens (2000) - https://www.aqr.com/Insights/Research/Working-Paper/Predicting-Stock-Returns-Using-IndustryRelative-Firm-Characteristics ; https://papers.ssrn.com/sol3/papers.cfm?abstract_id=213872
- Chou, Ho & Ko (2012), JBF 36(2) - https://scholars.ncu.edu.tw/en/publications/do-industries-matter-in-explaining-stock-returns-and-asset-pricin/
- Avramov, Ge, Li & Linton - https://www.cxoadvisory.com/fundamental-valuation/using-peer-firm-information-relationships-to-rank-stocks ; https://www.repository.cam.ac.uk/items/c9345bde-eace-4e97-b666-094549a2bda0
- Katselas, Sidhu & Yu (2017), Accounting & Finance - https://openresearch-repository.anu.edu.au/items/23749149-091e-45f8-9ee4-f3a2f8338498
- McLean & Pontiff (2016), JF - https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365 ; copy https://Www.Gwern.net/doc/economics/2016-mclean.pdf
- Bailey & Lopez de Prado (2014), "The Deflated Sharpe Ratio", JPM 40(5): 94-107 - https://papers.ssrn.com/abstract=2460551
- Blume (1971), "On the Assessment of Risk", JF 26(1): 1-10 - https://econbiz.de/Record/on-the-assessment-of-risk-blume-marshall/10001936883 ; 0.67/0.33 convention e.g. https://www.iese.edu/research/pdfs/DI-0825-E.pdf

Data and GICS:
- Wikipedia constituents: https://en.wikipedia.org/wiki/List_of_S%26P_500_companies ; https://en.wikipedia.org/wiki/List_of_S%26P_400_companies ; https://en.wikipedia.org/wiki/List_of_S%26P_600_companies
- GICS structure: https://en.wikipedia.org/wiki/Global_Industry_Classification_Standard
- 2016 revision: https://press.spglobal.com/2016-03-08-S-P-Dow-Jones-Indices-And-MSCI-Revisions-To-The-Global-Industry-Classification-Standard-GICS-Structure
- 2018 revision: https://press.spglobal.com/2017-11-15-S-P-Dow-Jones-Indices-And-MSCI-Announce-Revisions-To-The-Global-Industry-Classification-Standard-GICS-R-Structure-In-2018 ; https://www.asxonline.com/content/asxonline/public/notices/2018/mar/0264.18.03.html
- 2023 revision: https://www.ssga.com/us/en/individual/etfs/insights/2023-gics-changes-companies-impacted-and-what-you-need-to-know ; https://or.indexologyblog.com/2023/02/03/2023-gics-changes-sp-500-impact-analysis/
- SEC APIs and bulk files: https://www.sec.gov/search-filings/edgar-application-programming-interfaces
- XBRL phase-in: https://www.willkie.com/publications/2009/02/sec-issues-final-rules-mandating-xbrl-filings ; https://www.huschblackwell.com/newsandinsights/mandatory-interactive-data-reporting-xbrl-arrives-02-23-2009
- Ken French data library: http://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html
- FRED 10-year Treasury (DGS10): https://fred.stlouisfed.org/series/DGS10 [M - not fetched]
