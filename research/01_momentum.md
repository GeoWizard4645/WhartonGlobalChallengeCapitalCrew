# 01 - Momentum side of "Quality-filtered momentum": papers, exact math, benchmarks, spec

Prepared Sunday 2026-10-18 for Capital Crew (Wharton Global High School Investment Competition 2026-27).
Scope: the momentum / technical / risk-management half only. The quality / profitability papers are covered separately.

Legend used throughout
- **[P]** = I read the primary source text (PDF) and the number/formula is from it.
- **[S]** = secondary source only (summary site, replication paper, search abstract). Treat as unverified against the original.
- **[OWN]** = my own computation on Ken French data (vintage "202608 CRSP", data through 2026-08-31). Not peer reviewed. Reproduction recipe in section 9.
- **[H]** = practitioner heuristic with no primary academic source.

---

## 0. One-page summary (read this first)

1. **Signal.** 12-1 momentum = return from ~12 months ago to ~1 month ago. In price terms at formation day `t`: `MOM = P[t-21] / P[t-252] - 1` (trading-day offsets, adjusted closes). This is exactly Ken French's "Prior 12-2" (his daily files use day -250 to -21) and Daniel-Moskowitz's "t-12 to t-2" ranking window with a one-month gap. [P]
2. **Momentum is real but conditional.** Jegadeesh-Titman (1993): 6-month formation / 6-month hold earned about 1%/month long-short (0.95% no skip, 1.10% with a one-week skip), t about 3-3.6, 1965-89. [P] Our reproduction on French data: 1927-2008 the winners decile has CAPM alpha of 6-8%/yr (t 2-5); **2009-2026 it is 0.9%/yr (t 0.3)** and long-short WML Sharpe is about 0.03. [OWN]
3. **Crashes** (Daniel-Moskowitz 2016): happen in "panic" states = past-24-month market return negative AND high market volatility, and coincide with sharp market rebounds. 14 of the 15 worst WML months had a negative lagged 2-year market return. Worst: Aug 1932 (-74%), Jul 1932 (-61%), Apr 2009 (-46%). The crash is mostly the SHORT leg (losers "crash up": +232% Jul-Aug 1932, +163% Mar-May 2009); winners rose +32% and +8% over the same windows. [P]
4. **Vol-scaling** (Barroso & Santa-Clara 2015): `w_t = sigma_target / sigma_hat_t`, sigma_hat from the previous **126 daily returns**, annualized, target **12%**. Sharpe 0.53 -> 0.97 (1927-2011), worst month about -80% -> -28%. [S] I reproduced it from French data: Sharpe 0.54 -> 1.00, average weight 0.90, weight range 0.14-2.09. [OWN] Daniel-Moskowitz's dynamic version (w proportional to forecast mean / forecast variance) reached Sharpe 1.19 vs 1.02 (constant-vol) vs 0.59 (static WML), all at 19% vol. [P]
5. **For a LONG-ONLY top-N book the problem is different.** Crash losses sit mostly on the short side, so long-only winners "lag" in rebounds instead of crashing, but they still carry market beta (winners decile max drawdown 1927-32 was -84%, same as the market). [OWN] My decile-level tests of crash controls on the long-only winners decile (section 8): vol-scaling raised Sharpe and cut drawdown in both eras; a DM bear-state flag cut drawdown only in the full sample and hurt Sharpe in 2009-2026; a 200-day trend exit cut drawdown but cost Sharpe; portfolio-level stop-loss did not help.
6. **Stop-loss** (Han-Zhou-Zhu, SSRN working paper): 10%/15%/20% stops from the start-of-month price, checked daily, proceeds to T-bills; cut the worst monthly loss of equal-weighted long-short momentum from about -50% to about -11% to -17% and roughly doubled the gross Sharpe. Gross of costs, long-short, and details are [S] only. Evidence for a long-only book is thin.
7. **RSI 50-70 band is a heuristic [H].** No primary paper supports that exact band. Technical-rule evidence is mixed after data-snooping and costs. The 200-day MA has index-level support (Faber 2007 [P], Brock-Lakonishok-LeBaron 1992 [S]) and some stock-level support (Han-Yang-Zhou 2013 [S]).
8. **Current regime warning (as of 2026-08-31, [OWN], French data).** Momentum was in an extreme-volatility regime: 126-day annualized vol of the daily decile WML = 53% (long-run 27.6%), of the winners decile = 41.6% (long-run about 22%); BSC weight on WML = 0.23; winners decile -15.4% in Jul 2026 and about 0% in Aug 2026 while the long-short factor lost -22.7% and -14.4%. Market was NOT in a bear state (24-month return +41.7%). See section 10. Recompute through Oct 20 before trading Wed Oct 21.

---

## 1. What I could and could not verify (honest status table)

| Source | What I did | Status |
|---|---|---|
| Jegadeesh & Titman 1993 (JF 48:65-91) | OCR'd the full JSTOR scan at the bauer.uh.edu URL (28 pages), read all tables | **[P] fully read** (OCR; a few t-stats garbled, flagged below) |
| Daniel & Moskowitz (JFE 122:221-247, 2016) | Read the full text of the **Aug 8, 2014 working paper** (51 pp., Columbia-hosted PDF). Not the 2016 print version | **[P] working-paper version.** Final JFE numbers may differ slightly. Two internal inconsistencies noted in section 3 |
| Barroso & Santa-Clara (JFE 116:111-120, 2015) | SSRN and ScienceDirect return HTTP 403; the Nova repository page has no PDF | **[S] only.** Formula restated in a replication paper (GARP white paper); numbers from CXO Advisory's summary; independently replicated by me on French data |
| Han, Zhou, Zhu "Taming Momentum Crashes" (SSRN 2407199) | Paper not accessible. Used Quantpedia (abstract of 2014 version) and CXO Advisory (later version) | **[S] only.** Versions differ (sample to 2011 vs 2013). Execution details are CXO's description |
| Faber 2007 (SSRN 962461) | Read the full 2013-update PDF from mebfaber.com | **[P]** |
| Brock, Lakonishok, LeBaron 1992 | Search abstracts only | **[S]** |
| George & Hwang 2004 (JF 59:2145) | Read full PDF (bauer.uh.edu) | **[P]** |
| Novy-Marx 2012 (JFE 103:429) | Abstract only (IDEAS) | **[S]**; no table numbers |
| Da, Gurun, Warachka 2014 (RFS 27:2171) | Abstract only (IDEAS, Chapman digital commons) | **[S]**; ID formula below is from my recollection, flagged |
| Frazzini, Israel, Moskowitz trading costs | Read the NBER conference draft (Dec 5, 2012, "preliminary and incomplete") | **[P] for the draft**; the later published version may differ |
| Korajczyk & Sadka 2004, Lesmond-Schill-Zhou, McLean & Pontiff 2016, Fama-French 2012, Sullivan-Timmermann-White 1999, Park & Irwin 2007, Kaminski & Lo 2014 | Search abstracts / secondary summaries | **[S]** |
| Ken French data library | Downloaded six US files, parsed them, matched DM's "183 bear months" exactly | **[P] (data verified)** |
| RSI 50-70 band | Searched; no primary support | **[H]** |

Note on downloads: besides the papers (read-only, in the session scratchpad), I downloaded six small US files from Ken French's library solely to verify file names/structure and run the sanity checks. Nothing was placed in the repo.

---

## 2. Jegadeesh & Titman (1993) - exact construction and results [P]

URL: https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf (DOI 10.1111/j.1540-6261.1993.tb04702.x)

### 2.1 Construction
- Universe: NYSE and AMEX stocks, CRSP daily file; sample Jan 1965 - Dec 1989 (first full year is 1965 because 12/12 needs 23 months of lagged data). All stocks with return data in the J formation months are included. Monthly returns = compounded daily returns.
- J-month/K-month strategy (J, K in {3, 6, 9, 12}) = 16 strategies, plus 16 more that **skip one week** between the end of formation and the start of holding (to avoid bid-ask bounce, price pressure, lagged reaction; Jegadeesh 1990, Lehmann 1990).
- At the beginning of each month `t`: rank all stocks on their past-J-month return; form **ten decile portfolios, equally weighted**; buy the top decile (winners), sell the bottom decile (losers); hold K months.
- **Overlapping portfolios:** in any month the strategy holds K cohorts (formed in months t, t-1, ..., t-K+1). Each month it closes the cohort formed in t-K and opens a new one, so **1/K of the book is revised each month**. Equal-weighted rebalanced-monthly and buy-and-hold versions gave very similar results; the paper reports rebalanced.
- (Text oddity: the paper's prose says ascending ranking with "top decile = losers"; every table caption states lowest past-return decile = sell/loser and highest = buy/winner. Use the captions.)

### 2.2 Table I - Buy minus Sell, monthly return (t-stat), 1965-89
No skip (Panel A) / skip one week (Panel B):

| J (formation) | K=3 A | K=6 A | K=9 A | K=12 A | K=3 B | K=6 B | K=9 B | K=12 B |
|---|---|---|---|---|---|---|---|---|
| 3 | 0.32% (1.10) | 0.58% (2.29) | 0.61% (2.69) | 0.69% (3.53) | 0.73% (2.61) | 0.78% (3.16) | 0.74% (3.36) | 0.77% (4.00) |
| 6 | 0.84% (2.44) | **0.95% (3.07)** | 1.02% (3.76) | 0.86% (3.36) | 1.14% (3.37) | **1.10% (3.61)** | 1.08% (4.01) | 0.90% (3.54) |
| 9 | 1.09% (3.03) | 1.21% (3.78) | 1.05% (3.47) | 0.82% (2.89) | 1.35% (3.85) | 1.30% (4.09) | 1.09% (3.67) | 0.85% (~3.0, OCR garbled) |
| 12 | **1.31% (3.74)** | 1.14% (3.40) | 0.93% (2.95) | 0.68% (2.25) | **1.49% (4.28)** | 1.21% (3.65) | 0.96% (3.09) | 0.69% (2.31) |

- Best strategy: 12/3, 1.31%/mo (no skip) and 1.49%/mo (skip a week); 6-month formation gives about 1%/mo regardless of K. Every zero-cost return is positive; all significant except 3/3 without skip. Bonferroni: P(single t >= 4.28 among 32 tests) < 0.0006.
- **Skipping a week helps slightly** (Panel B > Panel A in almost every cell).
- Long-only side (winner decile, monthly raw return): 6/6 = 1.74% (t 4.33) no-skip, 1.78% (t 4.41) skip; 12/3 = 1.92% / 1.96%. The average of all ten deciles for 6/6 is about 1.31%/mo, so the **winners decile beat the average stock by about 0.42%/mo (about 5%/yr), EW, 1965-89** (computed from Table III "All" column).
- 6/6 decile detail (Table III, "All"): P1 (losers) 0.79%/mo, P10 (winners) 1.74%/mo, P10-P1 0.95% (t 3.07). Post-ranking betas (Table II): P1 1.36, P10 1.28, so the long-short beta is -0.08. Average market cap of winners $495M vs losers $208M (1965-89 dollars).
- Risk-adjusted (CAPM intercept vs value-weighted index): P10-P1 about 1.00%/mo (t 3.23). Profits are from the buy side vs the VW benchmark (winners alpha 0.70%/mo, t 3.24; losers not significant).

### 2.3 Size / robustness
- 6/6 within size terciles, P10-P1: small S1 0.99% (t 2.77), medium S2 1.26% (t 4.57), **large S3 0.75% (t 3.03)**. Large-cap winners alone: 1.57%/mo (t 4.41). So momentum is weaker but present in large caps. Monotonic in beta (low-beta 0.62%, high-beta 1.08%).
- Not explained by systematic risk or lead-lag to a common factor; source is delayed reaction to firm-specific information.
- Transaction costs: turnover 84.8% semiannually (buy side 86.6%, sell side 83.1%); after **0.5% one-way cost** the risk-adjusted return is **9.29%/yr** (still reliably positive; also in each size tercile). JT call 0.5% conservative (cite 23 bp institutional estimate).

### 2.4 Seasonality (6/6 long-short, 1965-89)
- **January: -6.86% average (t -3.52)**; positive in only 24% of Januaries. Feb-Dec average +1.66%/mo (t 6.67). Large-cap tercile January: -1.61% (t -1.28, not significant); small caps -7.97%.
- Other months: April +3.33% (positive in 24 of 25 years), November +3.72%, December +2.64%, October +1.37%, August +0.27% (weakest). Positive in 67% of months overall (71% excluding January).
- Reversing positions in January only would have produced about 25%/yr abnormal return (their footnote).
- My check on French data [OWN]: WML January mean is -2.2%/mo full sample and about -1.2% 1990-2026, but **winners-minus-market in January is about 0 (VW)**: the January penalty is a loser-leg phenomenon, so it matters little for a long-only top-N book.

### 2.5 Long-horizon reversal (Table VII, 6-month formation, event time)
- Cumulative long-short return peaks at **+9.5% at month 12**, then monthly returns are negative in each month 13-30 (about -0.1% to -0.6%/mo, mostly about -0.3%), reaching about +4.1% by month 36. Loses more than half of the gain in the following 24 months, although the year-2/3 loss is not statistically significant (t -1.27) and **all of it occurs in Januaries**; non-January returns beyond month 12 are about zero.
- 1927-1940 (Table VIII): month-1 return -4.95%, cumulative -40.8% at month 36 (t -2.0). Mechanism: mean-reverting, very volatile market; strategy beta about -0.5; e.g. Jul 1932 market +43% after a 40% six-month decline and the 6/6 strategy lost 40%; the next month the market rose another 66% and the strategy lost 68%. 1941-64: similar to 1965-89 (positive months 2-8, negative from month 12, 12-month gain nearly gone by month 24).
- Implication for us: hold horizon of 3-12 months is where the premium lives; do not hold a winner "forever". Monthly re-ranking handles this.

### 2.6 Out-of-sample note
Jegadeesh & Titman (2001, NBER w7159, https://www.nber.org/papers/w7159) report momentum persisted in 1990-98 [S: abstract; DM's footnote also says so [P]].

---

## 3. Daniel & Moskowitz (2016) "Momentum Crashes" [P: Aug 2014 working paper]

Read PDF: https://business.columbia.edu/sites/default/files-efs/pubfiles/4607/mom11.pdf. Published: https://www.sciencedirect.com/science/article/pii/S0304405X16301490 (NBER w20439: https://www.nber.org/papers/w20439).

### 3.1 Construction
- CRSP NYSE/AMEX/NASDAQ common shares (share code 10/11); monthly and daily decile portfolios rebalanced at month-end; require valid price and shares at formation and **at least 8 monthly returns in the 11-month window**.
- Rank on cumulative return from **t-12 to t-2** (skipping t-1: "one month gap ... to avoid short-term reversals"), decile 10 = Winners, decile 1 = Losers, **value-weighted**; WML = D10 - D1. Close-to-close returns.

### 3.2 Table 1 (monthly excess returns, 1927:01-2013:03, annualized %)
| | Losers D1 | Winners D10 | WML | Market |
|---|---|---|---|---|
| mean excess | -2.5 | 15.3 | 17.9 | 7.7 |
| sigma | 36.5 | 23.7 | 30.0 | 18.8 |
| Sharpe | -0.07 | 0.65 | 0.60 | 0.41 |
| beta | 1.61 | 1.03 | -0.58 | 1 |
| monthly skew | 0.09 | -0.82 | **-4.70** | -0.57 |

(The text says WML Sharpe 0.71 / alpha 22.3%, but Table 1 prints 0.60 / 22.2%; Fig. 5 labels the 19%-vol-scaled WML 0.59. The draft is internally inconsistent; use 0.59-0.60.) Winners are MORE negatively skewed than losers; the most extreme deciles are the most skewed.

### 3.3 When crashes happen
- **Bear-market indicator** `I_B,t-1 = 1` if the cumulative CRSP VW market return over the previous **24 months is negative**, else 0. In 1927:01-2013:03: 183 bear months of 1,035. (**I reproduced "183" exactly from French data, so my parsing/definition matches.** [OWN])
- **Worst WML months (Table 2):** 1932-08 -74.36% (prior-2y market -67.77%, same-month market +36.49%); 1932-07 -60.98%; 2001-01 -49.19% (prior-2y market +10.74%, the exception); 2009-04 -45.52%; 1939-09 -43.83%; 1933-04 -43.14%; 2009-03 -42.28%; 2002-11 -37.04%; 1938-06 -33.36%; 2009-08 -30.54%. **14 of the 15 worst months have a negative lagged 2-year market return; all occur in months when the market rose.** Crashes are slow (multi-month), clustered, not Poisson jumps.
- Magnitude: Jul-Aug 1932 loser decile **+232%**, winner decile +32%, market +82%. Mar-May 2009: loser decile **+163%**, winners +8%, market +26%. Two drawdown periods: Jun 1932 - Dec 1939 and Mar 2009 - Mar 2013.
- **Mechanism (why):** after a bear market, losers are high-beta, levered, near-bankrupt firms (beta of loser decile can exceed 3, up to 4-5 in the plots; winners can fall below 0.5). In bear states WML behaves like a **written call option on the market**: Table 3 spec (3): beta = -0.69 in down-market months, **-1.51 in up-market months**. Optionality is in the losers (D1: down-beta 1.56, up-beta 2.16) and only in bear states.
- Table 3 (WML on market, bear dummy): alpha0 = 1.98%/mo (t 7.8); beta_B (bear x market) = -0.661 (t -5.0); beta_B,U = -0.815 (t -4.5); the bear alpha shift itself is insignificant (+0.58, t 0.7). (The body text quotes -1.796 for the bear up-market beta; Table 3 sums to -1.51. I use -1.51.)
- Table 5: WML next-month return regressed on `I_B` and market variance `sigma2_m` (variance of daily market returns over the 126 days before month t): both predict lower WML returns; column (5) with the interaction: gamma0 = 2.129, gamma_B = 0.023, gamma_sigma2 = -0.088 (t -0.8), **gamma_int(I_B x sigma2) = -0.323 (t -2.2)**. Table 6 (daily, 1990-2013): WML earns about 31% per year outside panic states; in volatile bear markets (weighted average) about **59% per year lower**.
- Ex-ante hedging of WML beta (42-day betas) did **not** avoid the crash; the Grundy-Martin ex-post hedge looks great only because it uses future betas (look-ahead).

### 3.4 Optimal dynamic weight (exact math, Appendix C/D)
Maximizing the unconditional Sharpe ratio of a managed portfolio with weight `w_t` in the risky asset gives

```
w*_{t-1} = (1 / (2*lambda)) * mu_{t-1} / sigma^2_{t-1}
mu_{t-1}      = E_{t-1}[R_WML,t]            (conditional mean forecast for next month)
sigma^2_{t-1} = E_{t-1}[(R_WML,t - mu_{t-1})^2]   (conditional variance forecast)
lambda        = scalar that sets the unconditional vol (they pick it so in-sample annual vol = 19% = market's)
```
- **Mean forecast:** fitted values of the Table 5 column (5) regression, `R_WML,t = g0 + gB*I_B + gs*sigma2_m + gint*I_B*sigma2_m`.
- **Vol forecast:** two steps.
  1. Fit GJR-GARCH(1,1) to daily WML (MLE over the full sample): `R_t = mu + eps_t`, `eps_t ~ N(0, s2_t)`, `s2_t = omega + beta*s2_{t-1} + (alpha + gamma*1[eps_{t-1}<0]) * eps_{t-1}^2`. US estimates: mu = 0.86e-3, omega = 1.17e-6, alpha = 0.111, gamma = -0.016, beta = 0.896.
  2. Regress the realized 22-day WML vol on the GARCH vol and the 126-day trailing WML vol: `sigma_22,t+1 = 0.0010 + 0.6114*sigma_GARCH,t + 0.2640*sigma_126,t` (adj R2 = 0.617).
- **Look-ahead caveat:** GARCH and regression parameters and lambda are estimated over the full sample ("implementable" only loosely). BSC's rule below needs only the trailing 126 days and one free scale; it is the more honest ex-ante rule.
- If the Sharpe ratio were constant, w would be proportional to 1/sigma and DM's rule collapses to BSC's constant-vol rule. The point of DM is that WML's mean falls precisely when its variance is high, so the dynamic rule de-risks more than constant-vol does.

### 3.5 Performance (Figure 5 labels; all strategies scaled to 19% annual vol)
| Period | static WML | constant-vol (cvol) | dynamic (dyn) |
|---|---|---|---|
| 1927:07-2013:03 | 0.59 | 1.02 | **1.19** |
| 1927-1949 | 0.25 | 0.61 | 0.67 |
| 1950-1974 | 1.13 | 1.33 | 1.48 |
| 1975-1999 | 1.18 | 1.36 | 1.48 |
| 2000-2013 | 0.22 | 0.50 | 0.76 |

Spanning (Table 7, daily, vol-matched at 23%): dyn alpha vs Mkt+WML = 23.74%/yr (t 11.99); dyn vs Mkt+cvol = 7.27%/yr (t 6.86); cvol vs dyn = -0.72% (t -0.66), so dyn spans cvol but not vice versa. Dynamic skewness turns positive. International/other assets (Table 10, annualized Sharpe, WML / cvol / dyn): US 1972-2013 0.28 / 0.52 / 0.65; Japan 0.07 / 0.16 / 0.42; global all-asset combination 0.75 / 0.94 / 1.14.

### 3.6 Long-only winners vs long-short (what DM implies for us)
- "The crash performance is mostly attributable to the short side ... the losers are crashing up." Winners' monthly skew is -0.82, but the *crash events* are not the winners' losses.
- My decile data [OWN, French monthly file]: in the 15 worst WML months the winners decile fell in only 4 (Apr 2009 -0.1%, Jan 2001 -5.8%, Feb 2021 -2.8%, Jul 2026 -15.4%) and otherwise rose 0.2% to 29%, but in the 1930s/2009 rebound months it **lagged the market by roughly 4-21 points** (e.g. Aug 1932 +16% vs market +37%; Apr 2009 -0.1% vs +10.2%). The worst months for the winners decile are market crashes (May 1940 -28.3%, Oct 1929 -27.1%, Oct 1987 -26.7%, Nov 2000 -24.5%).
- In bear states (24-month market return < 0) [OWN, 1927-2026, 191 bear months]: WML averages **-1.11%/mo (sd 14.1)** vs **+1.56%/mo (sd 6.1)** otherwise; winners decile excess return 0.78%/mo vs 1.34%/mo; **winners minus market +0.04%/mo in bear vs +0.66%/mo otherwise**. The long-only momentum edge over the market is earned almost entirely in non-bear states; in bear states winners just earn market-like returns with more volatility.

---

## 4. Barroso & Santa-Clara (2015) "Momentum Has Its Moments" [S]

SSRN: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2041429 ; JFE doi 10.1016/j.jfineco.2014.11.010. **Primary text not accessible to me** (403). Formula restated in a replication paper (GARP white paper, https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054xSXUAY.pdf, its eq. 1-3); numbers from CXO Advisory's summary (https://www.cxoadvisory.com/momentum-investing/avoiding-momentum-strategy-crashes/).

### 4.1 Exact rule
Building block is plain momentum WML = D10 - D1 of value-weighted deciles on prior 12-2 returns (French data). Daily WML returns `r_d`, monthly `r_WML,t`.

```
sigma_hat^2_{t-1}  = 21 * sum_{j=0..125} r_d,(t-1 end - j)^2 / 126      # realized variance of previous 126 trading days (~6 months), scaled to monthly
sigma_hat_ann      = sqrt(12) * sqrt(sigma_hat^2)  =  sqrt(252 * mean(r_d^2 over last 126 days))
w_t                = sigma_target / sigma_hat_ann        # sigma_target = 12% annualized  (GARP's replication writes the target variance as c = 1.44% = 12%^2)
r*_WML,t           = w_t * r_WML,t                       # weight decided at the END of month t-1, applied to month t
```
- The sigma_target constant does not change the Sharpe ratio (it only rescales).
- The rule is fully ex ante: uses only the previous 126 daily returns (squared returns, **uncentered**, not demeaned).
- Weights are not capped in the paper as summarized (CXO: scale factor averages 0.90, range 0.13 to 2.00). My replication: average 0.90, range 0.14-2.09. The leverage is on the long-short spread (both legs scaled).
- Variance of momentum is highly predictable (CXO: monthly AR R2 0.58); past market volatility explains 23% of momentum vol.
- Window sensitivity (R-bloggers replication, https://www.r-bloggers.com/2015/09/hypothesis-driven-development-part-iv-testing-the-barrososanta-clara-rule/): 126-252 day windows "fairly robust", very short windows perform poorly. [S, blog]

### 4.2 Reported results (CXO summary of the paper; sample reported by CXO as Jul 1926 - Dec 2011, gross of costs)
| | Plain WML | Risk-managed WML* |
|---|---|---|
| mean annual return | 14.5% | 16.5% |
| annualized vol (CXO labels it "std dev") | 27.5% | 17.0% |
| Sharpe | **0.53** | **0.97** |
| worst 1-month | about -80% | about -28.4% |
| worst peak-to-trough | about -97% | about -45.2% |

CXO's caveats: gross of costs; monthly scaling raises turnover; shorting loser stocks and leverage constraints are ignored; few crashes so results are statistically fragile; a long-only version raises capital reserve and leverage-cost issues.

### 4.3 My replication on French data [OWN] (decile WML, daily vol from the daily deciles)
| Sample | Plain WML (mean / vol / Sharpe / worst month / max DD) | Scaled to 12% target |
|---|---|---|
| 1927-05..2011-12 | 14.9% / 27.4% / 0.54 / -77.7% / -95.6% | 16.7% / 16.8% / **1.00** / -24.2% / -43.8% |
| 1927-05..2026-08 | 13.5% / 27.7% / 0.49 / -77.7% / -95.6% | 14.9% / 16.2% / 0.92 / -24.2% / -43.8% |
| 1965-1989 | 19.7% / 19.2% / 1.03 / -19.7% / -29.0% | 25.3% / 19.2% / 1.32 / -16.9% / -24.1% |
| 2012-2026 (post-publication) | 5.7% / 28.9% / 0.20 / -32.1% / -64.8% | 4.6% / 12.2% / **0.37** / -12.5% / -23.0% |
Weights: average 0.84 (full), 0.50 in 2012-26 (momentum vol stayed high), max 2.09. Capping weights at 2.0 changes nothing.
=> The published effect replicates closely, still improves Sharpe out of sample, but the absolute premium in 2009-2026 is near zero. (Caveat: independent critics, e.g. Cederburg et al. 2020, find vol-managed portfolios are not universally better [S: search snippet].)

### 4.4 Applying vol-scaling to a long-only portfolio
BSC scale a zero-cost long-short factor with leverage up to 2x. A long-only top-N stock book cannot use the short leg, and a team may not be able to lever. Options and what the evidence says:

| Option | Rule | Evidence |
|---|---|---|
| A. Own-vol targeting, cap 1 | `w = min(1, s_tgt / s_hat)` with s_hat from the previous 126 daily returns of the strategy's own (back-cast) portfolio; remainder in T-bill | Adaptation of BSC; no paper tests it on long-only decile. [OWN] test on winners decile (section 8) |
| B. WML-vol as the risk gauge | `w = min(1, 12% / s_hat_WML)`, where s_hat_WML is the 126-day vol of a long-short momentum proxy (e.g. French WML or one built in our universe) | Closest to BSC/DM logic: the signal that crashes are coming is momentum-factor vol / panic state. [OWN] test |
| C. DM regime flag | `w = 0` or `0.5` when the 24-month market return is negative | DM show this state is where WML premium dies; for long-only the evidence is weaker. [OWN] test |
BSC's own 12% target is for WML whose unconditional vol is about 27%; for a long-only book (vol about 22%) a target of 12% would hold the book at about half exposure on average, so use a target near the strategy's long-run vol (15-25%) if you want vol-scaling to bind only in stress.

---

## 5. Stop-loss and trend-break evidence

### 5.1 Han, Zhou & Zhu "Taming Momentum Crashes: A Simple Stop-Loss Strategy" (SSRN 2407199) [S]
URLs: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2407199 ; Quantpedia summary https://vvv.quantpedia.com/?p=558 ; CXO summary https://www.cxoadvisory.com/?p=25071. **I could not open the paper**; two summary sources describe two versions.

- Rule (per CXO's description of the later version): each month rank into deciles on past six-month return, long winners / short losers, **equal-weighted**, skip one month, hold one month. **Stop-loss = % move from the portfolio-formation (start-of-month) price**: a winner is stopped if it falls below the threshold; a loser is stopped if it rises above it. Thresholds tested: **10%, 15%, 20%**. Checked **daily** (closes, highs, lows); execution via next-day limit orders and a close-out if the threshold is still breached (details are CXO's, unverified). Liquidation proceeds earn the **T-bill rate** for the rest of the month; re-entry at next month's portfolio formation.
- Reported results:
  - Quantpedia (abstract of 2014 version; Jan 1926-Dec 2011, 10% stop): worst monthly loss of equal-weighted momentum from **-49.79% to -11.34%**; value-weighted from -65.34% to -23.69% (-14.85% excluding 1932); "average returns and Sharpe ratios ... more than doubled"; conclusion: momentum profits "unlikely explained by crash risk".
  - CXO (later version, Jan 1926-Dec 2013, gross): baseline mean 0.99%/mo; Sharpe 0.17 baseline vs **0.50 (10% stop), 0.40 (15%), 0.32 (20%)**; worst month -49.8% vs -15.4% / -17.4% / -16.8%; 15% stop mean 1.93%/mo. **Units:** a baseline mean of 0.99%/mo with Sharpe 0.17 implies monthly Sharpe ratios (monthly vol about 5.8%); annualized (x sqrt(12)) these are about 0.59 and 1.73. Do not compare these with annualized Sharpe numbers in other papers. (Inference, not stated in the summaries.)
  - Alpha Architect's summary of the later version (search snippet only): worst losses -11.36% (EW) and -23.28% (VW), gross; suggests taking 300-600 bp off for costs.
- Caveats from the same sources: gross of costs; stop trades are in stressed, illiquid names; data-snooping and dependence on a few crashes; the stop is applied to **both legs** of a long-short portfolio, and most of the benefit appears in rebound months when the SHORT leg spikes.
- Related theory (Kaminski & Lo 2014, https://dspace.mit.edu/handle/1721.1/114876, JFM 18:234-254) [S]: under a random walk simple stop-loss rules reduce expected return; they can add value under momentum / regime-switching. Their empirical test is on index futures.

### 5.2 Trend-break exits (price below a moving average)
- No paper I found tests "exit an individual momentum stock when it breaks its 200-day MA" within a long-only momentum book. Closest primary evidence is index-level (Faber, below) and stock-sorted MA timing (Han-Yang-Zhou).
- My decile-level test [OWN, section 8]: exiting the winners decile to T-bills when its own (or the market's) 200-day SMA breaks cut max drawdown (-84% to -55%/-63%) but **lowered Sharpe** (0.61 to 0.58-0.60 full sample; 0.77 to 0.66-0.67 in 2009-2026).

### 5.3 Portfolio-level stop-loss test on the long-only winners decile [OWN]
Switching to T-bills for the rest of the month when the winners decile's month-to-date return reaches -10% / -15%: Sharpe 0.56 / 0.55 vs 0.61 buy-and-hold (full sample), 0.55 / 0.63 vs 0.77 (2009-2026). Max drawdown not improved. Caveat: portfolio-level stops trigger far less often than stock-level stops (single stocks hit -10% constantly), so this is not a test of HZZ's rule; a stock-level stop in a 5-10 name book will whipsaw. Test it explicitly.

---

## 6. Technical filters

### 6.1 Wilder RSI(14) - exact formulas
Source for the algorithm: Wilder (1978) "New Concepts in Technical Trading Systems"; restated in Traders' Tips (Oct 2002) https://traders.com/documentation/FEEDbk_docs/2002/10/TradersTips/TradersTips.html and TC2000 help https://help.tc2000.com/a/747071 [S]. Wilder smoothing = exponential average with alpha = 1/n; **not** a simple average after the seed.

```
change_i  = close_i - close_{i-1}
gain_i    = max(change_i, 0);  loss_i = max(-change_i, 0)
seed (first n=14 changes): avg_gain_14 = mean(gain_1..gain_14);  avg_loss_14 = mean(loss_1..loss_14)
for i > 14:  avg_gain_i = (avg_gain_{i-1} * 13 + gain_i) / 14     # = avg_gain_{i-1} + (gain_i - avg_gain_{i-1})/14
             avg_loss_i = (avg_loss_{i-1} * 13 + loss_i) / 14
RS  = avg_gain / avg_loss
RSI = 100 - 100 / (1 + RS)          # RSI = 100 if avg_loss = 0 and avg_gain > 0 (define 50 if both are 0)
```
Practical: pandas `ewm(alpha=1/14, adjust=False)` gives the same recursion except for the seed; the difference decays as (13/14)^k, negligible after about 150 days. Use at least 250 days of history per stock. Python (numpy) implementation, tested:

```python
import numpy as np

def rsi_wilder(close, n=14):
    close = np.asarray(close, float); d = np.diff(close)
    gain = np.where(d > 0, d, 0.0); loss = np.where(d < 0, -d, 0.0)
    out = np.full(len(close), np.nan)
    if len(d) < n: return out
    ag, al = gain[:n].mean(), loss[:n].mean()            # simple-average seed
    def f(ag, al): return (100.0 if ag > 0 else 50.0) if al == 0 else 100.0 - 100.0 / (1.0 + ag / al)
    out[n] = f(ag, al)
    for i in range(n, len(d)):
        ag = (ag * (n - 1) + gain[i]) / n; al = (al * (n - 1) + loss[i]) / n   # Wilder smoothing
        out[i + 1] = f(ag, al)
    return out

def sma(close, n=200):                                  # includes today's close
    close = np.asarray(close, float); out = np.full(len(close), np.nan)
    c = np.cumsum(np.insert(close, 0, 0.0)); out[n - 1:] = (c[n:] - c[:-n]) / n
    return out

def mom_12_1(adj_close, i):                             # formation day index i
    return adj_close[i - 21] / adj_close[i - 252] - 1.0

def bsc_sigma_ann(daily_ret, i):                        # 126-day uncentered realized vol, annualized
    w = np.asarray(daily_ret)[i - 125: i + 1]
    return float(np.sqrt(252.0 * np.mean(w ** 2)))
```

**Evidence on RSI (be honest: thin).** The 70/30 overbought/oversold levels come from Wilder; the "50-70 band" in the team doc is a practitioner heuristic [H]. I found no peer-reviewed study of RSI 50-70 combined with 12-1 momentum. General technical-analysis literature: Park & Irwin (2007, https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html) tally about 56 of 95 modern studies positive, but most suffer from data snooping/ex-post rule selection and profits fall after costs [S]. Sullivan, Timmermann & White (1999, JF 54:1647, https://doi.org/10.1111/0022-1082.00163) re-test Brock et al.'s rules with White's Reality Check on 100 years of Dow data [S: I could not verify their conclusion from the abstract]. CXO's out-of-sample test of 2-day-RSI rules: mixed, tiny sample [S]. A plausible *rationale* for the upper bound (not evidence): RSI(14) looks at the last ~3 weeks, which is the window 12-1 momentum deliberately skips; RSI > 70 flags stocks that just spiked, the group exposed to the 1-month reversal that Jegadeesh (1990) and Lehmann (1990) document. The lower bound (RSI >= 50 = recent net gains) is a trend-confirmation heuristic with no direct support. **Treat the band as an ablation, not a claim.**

### 6.2 200-day SMA
- Definition: `SMA200_t = (1/200) * sum_{k=0..199} P_{t-k}` (today included). Faber's monthly equivalent: month-end price vs the mean of the last **10 month-end** prices ("closest to the 200-day").
- **Faber (2007; read 2013 update) [P]**: https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf (SSRN 962461). Rule: buy when monthly price > 10-month SMA, else cash; updated once a month at the close of the last day; total-return series; cash = 90-day T-bill; taxes/commissions/slippage excluded. S&P 500 1901-2012: timing CAGR **10.18% vs 9.32%** buy-and-hold, about 70% invested, less than one round trip a year, **max drawdown 83.66% -> 42.24%**; correlation with S&P in negative years -0.38 vs +0.83 in positive years. Five-asset-class GTAA 1973-2012: drawdown from 46% to under 10%; 2006-2012 out-of-sample beat buy-and-hold by over 2 pts/yr. MA lengths 3-12 months "work similarly". Cites Siegel (2008): DJIA 1886-2006, buy when close >= 1% above the 200-day MA, sell to T-bills when >= 1% below. **All of this is index/asset-class timing, not an individual-stock filter.**
- **Brock, Lakonishok & LeBaron (1992, JF 47:1731, https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html) [S]**: Dow Jones 1897-1986; variable-length MA and trading-range-break rules (short MAs 1/2/5 days vs long MAs 50/150/200 days); buy-signal returns higher and less volatile than sell-signal returns; rejects random walk, AR(1), GARCH-M, EGARCH nulls via bootstrap. Later work finds weaker results post-1986 and after snooping/costs [S].
- **Han, Yang & Zhou (2013, JFQA 48:1433, https://resolve.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/new-anomaly-the-crosssectional-profitability-of-technical-analysis/B9E41049F2E55B4F274D46E72ECA8E29) [S: abstract]**: MA timing (10-, 20-, 50-, 100-, 200-day) applied to volatility-sorted US stock portfolios 1963-2009; timing portfolios outperform buy-and-hold, strongest in high-volatility stocks, abnormal returns higher than momentum's, and MA and momentum profits are surprisingly **uncorrelated**. This is the best stock-level support for "above its MA" as a signal.

---

## 7. Refinements

### 7.1 52-week-high momentum (George & Hwang 2004) [P]
https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf (JF 59:2145-2176, DOI 10.1111/j.1540-6261.2004.00695.x)
- Rank on `P_{i,t-1} / high_{i,t-1}` where `high` = highest price in the 12 months ending the last day of month t-1. Winners/losers = top/bottom **30%**, equal-weighted, (6,6) overlapping design like JT. CRSP, Jul 1963-Dec 2001.
- Table I (6,6, no skip): JT individual momentum 0.48%/mo (t 2.35); industry momentum 0.45% (3.43); **52-week-high 0.45% (2.00)**. Fama-MacBeth with controls (skip a month): 52-week-high winner dummy **0.65%/mo (1.06% excl. January)** vs JT 0.38% (0.46%) and MG 0.25% (0.22%). Nearness to the high "dominates" past-return momentum and its predicted returns do **not** reverse long-run (unlike JT's).
- Use: add `P_t / max(P_{t-252..t}) >= 0.90` or rank by it. It also correlates with "above 200DMA", so partially redundant with our trend filter.

### 7.2 Novy-Marx (2012) "Is momentum really momentum?" [S: abstract]
https://ideas.repec.org/a/eee/jfinec/v103y2012i3p429-453.html (JFE 103:429-453). Momentum is driven mainly by performance **12 to 7 months before formation**, not by the most recent 6 months; recent-past strategies are less profitable, especially among the **largest, most liquid** stocks. Patterns also hold in international indices, commodities, currencies. **I have no table numbers.** Practitioner commentary (Alpha Architect, secondary) says 12-2 and 12-7 looked similar for long-only investors. Test: 12-7 (`P[t-147]/P[t-252] - 1`, i.e. skip 7 months) vs 12-1 vs 6-1.

### 7.3 Frog-in-the-pan / information discreteness (Da, Gurun, Warachka 2014, RFS 27:2171-2218) [S]
https://ideas.repec.org/a/oup/rfinst/v27y2014i7p2171-2218..html . Abstract: continuous information produces strong continuation that does not reverse; "momentum falls monotonically from 5.94% for stocks with continuous information to -2.07% for stocks with discrete information" (holding-period/units not stated in the abstract). **Formula (my recollection of the paper, unverified here):** `ID = sign(PRET) * (%neg - %pos)` where PRET is the formation-period cumulative return and %neg/%pos are the fractions of negative/positive daily returns in the formation window; lower ID = more continuous. Use: among top-MOM names prefer low ID (steady gainers over jump-driven gainers). Verify against the full text before citing the formula.

---

## 8. Our own decile-level tests of crash controls on the LONG-ONLY winners decile [OWN]

Setup: Ken French US 10 portfolios formed on prior 12-2 (daily files: formed daily on day -250 to -21), value-weighted, winners = decile 10 (D10), excess over French RF; monthly decisions use data through the prior month-end (no look-ahead); remainder of exposure in T-bills (French RF); **no transaction costs**; decile-level (hundreds of stocks), not a 5-10 stock book. 1927-05..2026-08 and 2009-01..2026-08.

| Rule applied to D10 | Full: CAGR / Sharpe / MaxDD | 2009-2026: CAGR / Sharpe / MaxDD |
|---|---|---|
| Buy and hold D10 (monthly) | 15.5% / 0.61 / -83.8% | 16.8% / 0.77 / -34.3% |
| Vol-target 25% own vol, cap 1 | 15.8% / 0.66 / -78.9% | 15.5% / 0.80 / -27.9% |
| Vol-target 20% own vol, cap 1 | 15.4% / 0.67 / -74.0% | 14.4% / 0.82 / -22.6% |
| Vol-target 15% own vol, cap 1 | 14.0% / 0.69 / -64.3% | 12.2% / 0.85 / -17.9% |
| Weight = min(1, 18% / WML-vol), cap 1 | 15.5% / 0.69 / -66.4% | 12.9% / 0.80 / -23.5% |
| Weight = min(1, 15% / WML-vol), cap 1 | 15.0% / 0.69 / -58.8% | 11.6% / 0.81 / -21.2% |
| Weight = min(1, 12% / WML-vol), cap 1 | 14.0% / 0.70 / -49.7% | 9.9% / 0.83 / -17.1% |
| DM bear flag (24m mkt < 0) -> T-bill | 14.7% / 0.63 / -55.9% | 14.6% / 0.73 / -34.3% |
| DM bear flag -> 50% | 15.2% / 0.63 / -67.1% | 15.8% / 0.77 / -34.3% |
| Exit when D10 < its own 200d SMA | 12.9% / 0.58 / -54.9% | 11.7% / 0.67 / -29.9% |
| Exit when market < its 200d SMA | 13.5% / 0.60 / -62.7% | 11.8% / 0.66 / -28.7% |
| Portfolio stop 10% from month start | 14.3% / 0.56 / -76.7% | 12.0% / 0.55 / -47.4% |
| Portfolio stop 15% from month start | 14.1% / 0.55 / -80.9% | 13.9% / 0.63 / -36.5% |
| (Market buy and hold, for reference) | 10.2% / 0.45 / -83.9% | 15.1% / 0.91 / -24.9% |

Reading it honestly:
- Every vol-scaling variant raised Sharpe (0.61 to 0.66-0.70) and cut max drawdown in both eras, at some cost in CAGR in 2009-2026. WML-vol is a better crash gauge than the portfolio's own vol (drawdown -50% vs -74%), but the 1930s drawdown is mostly the market's, and it was nearly impossible to avoid with a slow signal.
- Trend exits and stop-losses lowered Sharpe. They protected drawdown only in the 200-day case.
- **Post-2009 the winners decile did not beat the market on a risk-adjusted basis** (Sharpe 0.77 vs 0.91; CAPM alpha 0.9%/yr, t 0.3; FF3 alpha 0.7%/yr, t 0.2). Winners-decile CAPM alpha by period: 1927-64 7.5% (t 3.8); 1965-89 8.3% (t 3.9); 1990-2008 6.3% (t 2.1); 2009-26 0.9% (t 0.3); 2012-26 2.1% (t 0.6). [OWN]
- All of this is at the decile level; none of it substitutes for the stock-level backtest.

---

## 9. Ken French data library - exact files for the long-history sanity check

Library page: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html . Direct file base: `https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/<file>`. Files marked (D) I downloaded and parsed (data through Aug 2026); the others are listed on the library page but I did not download them.

| Purpose | File (CSV/TXT variants exist) | Detail page |
|---|---|---|
| Monthly Mom factor (D) | `F-F_Momentum_Factor_CSV.zip` (also `_TXT.zip`), 1927-01 to 2026-08, percent | `.../Data_Library/det_mom_factor.html` |
| Daily Mom factor (D) | `F-F_Momentum_Factor_daily_CSV.zip` (also `_TXT.zip`), from 1926-11-03; prior return day -250 to -21 | `.../det_mom_factor_daily.html` |
| **10 portfolios on prior 12-2, monthly (D)** | `10_Portfolios_Prior_12_2_CSV.zip` (also `_TXT.zip`). First block = **Value Weight** monthly, then **Equal Weight** monthly, annual blocks, number of firms, average firm size, VW average prior return | `.../det_10_port_form_pr_12_2.html` |
| **10 portfolios on prior 12-2, daily (D)** | `10_Portfolios_Prior_12_2_Daily_CSV.zip` (also `_TXT.zip`): VW daily block, then EW daily block; formed daily on day -250 to -21 | `.../det_10_port_form_pr_12_2_daily.html` |
| Market, RF, SMB, HML monthly / daily (D) | `F-F_Research_Data_Factors_CSV.zip` / `F-F_Research_Data_Factors_daily_CSV.zip` | |
| Size x momentum | `6_Portfolios_ME_Prior_12_2_CSV.zip`, `25_Portfolios_ME_Prior_12_2_CSV.zip` (+ `_Daily_CSV.zip`) | `det_6_port_form_sz_pr_12_2.html`, `det_25_port_form_sz_pr_12_2.html` |
| Short-term reversal portfolios / factor | `10_Portfolios_Prior_1_0_CSV.zip`, `F-F_ST_Reversal_Factor_CSV.zip` | |
| Long-term reversal | `10_Portfolios_Prior_60_13_CSV.zip`, `F-F_LT_Reversal_Factor_CSV.zip` | |
| Other regions | `Developed_Mom_Factor_CSV.zip`, `Europe_Mom_Factor_CSV.zip`, `North_America_Mom_Factor_CSV.zip`, `Developed_ex_US_Mom_Factor_CSV.zip` | |

Format notes: values are in **percent**; `-99.99`/`-999` = missing; each CSV has a prose header, first column YYYYMM (monthly) or YYYYMMDD (daily); the daily Mom file has no column header row; multiple blocks per file (parse only the first block after the "Value Weight"/"Average Value Weighted" heading).
**Important:** French's "Mom" factor is the **2x3** factor (average of big and small winners minus losers, 30/70 NYSE breakpoints), vol about 16%, **not** the decile spread D10-D1 used by Barroso-Santa-Clara and Daniel-Moskowitz (vol about 27%). Reproduce BSC/DM with the 10-portfolio files.

### Reference values from these files [OWN] (annualized, excess for portfolios, WML = D10 - D1 zero-cost)
| Period | WML (VW) mean / vol / Sharpe / worst month / max DD | Winners D10 excess mean / vol / Sharpe | Market excess mean / Sharpe | French 2x3 Mom mean / Sharpe |
|---|---|---|---|---|
| 1927-2026 | 13.6% / 27.6% / 0.49 / -77.7% / -95.6% | 15.0% / 22.6% / 0.66 | 8.3% / 0.45 | 7.4% / 0.45 |
| 1927-2011 | 15.0% / 27.4% / 0.55 / -77.7% / -95.6% | 14.5% / 22.8% / 0.64 | 7.4% / 0.39 | 8.2% / 0.49 |
| 1965-1989 (JT sample) | 19.7% / 19.2% / 1.03 / -19.7% / -29.0% | 13.5% / 21.9% / 0.62 | 4.3% / 0.27 | 9.9% / 0.80 |
| 1990-2008 | 18.9% / 26.5% / 0.71 / -41.8% / -51.6% | 11.5% / 21.9% / 0.52 | 4.4% / 0.29 | 11.1% / 0.68 |
| 2009-2026 | 0.8% / 32.1% / **0.03** / -45.2% / -80.8% | 16.8% / 22.0% / 0.76 | 13.9% / 0.91 | -0.8% / -0.05 |
Equal-weighted deciles (closer to what an equal-weighted top-N book resembles), 1927-2026: EW D10 excess 17.6% / vol 25.2% / Sharpe 0.70 / max DD -73%; EW WML 10.1% / 26.2% / 0.39 (worst month -87%). EW D10 1965-89: Sharpe 0.71; 2009-26: 0.60. Treat any large-cap stock-level backtest that beats EW D10 by a wide margin as suspect (survivorship / look-ahead).

Minimal stdlib reader (verified: reproduces WML mean 13.62%, vol 27.61%, Sharpe 0.49 for 1927-01..2026-08):

```python
import io, re, zipfile, urllib.request
BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
def read_french_block(fname, header_contains, ncols, keylen):
    z = zipfile.ZipFile(io.BytesIO(urllib.request.urlopen(BASE + fname).read()))
    text = z.read(z.namelist()[0]).decode("latin-1"); out, on = {}, False
    for line in text.splitlines():
        if not on: on = header_contains in line; continue
        m = re.match(r"^(\d{%d}),(.*)$" % keylen, line.strip())
        if m: out[int(m.group(1))] = [None if v <= -99 else v/100 for v in map(float, m.group(2).split(","))][:ncols]
        elif out and not line.strip().startswith(","): break
    return out
deciles = read_french_block("10_Portfolios_Prior_12_2_CSV.zip", "Value Weight Returns -- Monthly", 10, 6)
ff      = read_french_block("F-F_Research_Data_Factors_CSV.zip", ",Mkt-RF", 4, 6)   # Mkt-RF, SMB, HML, RF
wml = {k: v[9] - v[0] for k, v in deciles.items()}                                  # D10 - D1
```
(`header_contains` strings are checked against line text; the first match of "Value Weight Returns -- Monthly" is the VW monthly block.)

---

## 10. Practical portfolio issues

### 10.1 Holding only 5-10 stocks
- Idiosyncratic risk dominates. Classic diversification studies: Evans & Archer (1968) most unsystematic risk removed by about 8-10 stocks; Statman (1987) about 30-40; Campbell, Lettau, Malkiel & Xu (2001, https://www.nber.org/papers/w7590.pdf) idiosyncratic volatility rose so more stocks (about 50) are needed [S for Evans-Archer/Statman via a review at https://businessperspectives.org/images/pdf/applications/publishing/templates/article/assets/3162/imfi_en_2010_01_Benjelloun.pdf; the NBER paper's abstract states the trend].
- Back-of-envelope (my arithmetic, **assumption sigma_idio = 30% annual per stock, independent residuals**): tracking error vs the factor portfolio `~ sigma_idio / sqrt(N)` = 13.4% (N=5), 9.5% (N=10), 6.7% (N=20), 4.2% (N=50). If the true momentum edge over the market is 6%/yr (1927-2008 alpha), over the live window (Oct 21 to Nov 6 = 13 trading days, per `research/07_competition_rules.md`, written by another agent and not verified by me) expected alpha is about 0.31% (6% x 13/252) against tracking noise of 9.5% x sqrt(13/252) = 2.2% for N=10, so P(beat benchmark) is only about 56% (about 51% if alpha is the post-2009 0.9%/yr). **With 5-10 names and a single 13-day holding period, the live result will be dominated by luck; the backtest's job is to justify the rule, not to forecast the outcome.**

### 10.2 Rebalance frequency, turnover, costs
- JT93: overlapping K-month cohorts revise 1/K of the book monthly; 6/6 long-short turnover 84.8% semiannually; 0.5% one-way costs still leave 9.29%/yr risk-adjusted.
- Frazzini-Israel-Moskowitz (NBER draft, Dec 2012, https://conference.nber.org/conf_papers/f68262/f68262.pdf) [P: draft]: live trade data of one large manager, 19 markets, 1998-2011: actual costs "less than a tenth" of earlier estimates; US long-short momentum break-even size **$52B** (global $89B); non-optimized long-short UMD trading cost about **4.78%/yr** (optimized 2.14%) per the draft's cost table (I did not re-verify its sample/size assumptions); for the Korajczyk-Sadka long-only top-decile momentum portfolio they get break-even about $33.5B (vs about $2B using K&S's own TAQ-based cost model); **realized price impact in the manager's live long-only momentum funds: 8.0 bp (large cap), 18.2 bp (small cap), 5.9 bp (international)** since Jul 2009.
- Korajczyk & Sadka (2004, JF 59:1039; https://ideas.repec.org/p/wpa/wuwpfi/0308004.html) [S: abstract]: equal-weighted momentum does best before costs and worst after costs; liquidity-weighted / hybrid strategies have break-even size of about $5B+. Lesmond-Schill-Zhou (2004) argue costs eliminate momentum profits [S, via FIM's literature review].
- At the team's size capacity is irrelevant; spreads, slippage and **fixed commissions** matter. Per `research/07_competition_rules.md` (other agent; a third-party report of **$25 per stock trade**, unconfirmed for 2026-27) the WInS starting cash is $300,000; if the stock sleeve is about 25% ($75k) and holds 10 names, each position is about $7.5k and $25 is about **33 bp per side**, larger than spread/impact for liquid large caps. Model cost as `10 bp * traded value + $25 per trade`, grid 0 / (10 bp) / (10 bp + $25). Actual turnover of a top-N monthly rebalanced book is unknown until you backtest it; report it.

### 10.3 Large caps vs small caps
JT93: 6/6 P10-P1 large tercile 0.75%/mo vs medium 1.26%, small 0.99%; January loss concentrated in small caps. Fama-French (2012, JFE 105:457, https://www.johnhcochrane.com/s/Fama_French_size_value_momentum_JFE.pdf) [S: abstract]: momentum spreads **decrease with size** everywhere except Japan; Novy-Marx: recent-past momentum weakest in the largest stocks. FIM live price impact is roughly half for large caps (8.0 bp) vs small caps (18.2 bp). Practical consequence: our S&P 500 style universe has a smaller but cheaper-to-capture premium than the CRSP-wide deciles.

### 10.4 Post-publication decay
McLean & Pontiff (2016, JF; https://www.gwern.net/doc/economics/2016-mclean.pdf) [S: abstract]: 97 predictors, portfolio returns **26% lower out-of-sample and 58% lower post-publication** (about 32 points attributed to publication-informed trading). Chordia, Subrahmanyam & Tong (2014, JAE 58) find most anomalies attenuated after decimalization [S; later challenged by Auer & Rottmann 2018]. Momentum-specific [OWN]: winners-decile alpha about 6-8%/yr to 2008, about 1%/yr after; WML Sharpe about 0 in 2009-2026 and 0.20 in 2012-26. Daniel-Moskowitz's 2000-2013 static WML Sharpe was 0.22 [P].
Note for the team's argument in the planning doc ("a backtested-by-us strategy strengthens our case and we can cite the 2016 paper"): McLean-Pontiff cut both ways. Their out-of-sample decline is an upper bound for data mining; our own parameter search is exposed to the same selection bias, so shrink our in-sample numbers and prefer parameters from broad plateaus.

---

## 11. Recommended implementation spec - monthly rebalanced, long-only (v1)

Conventions
- Prices: split- and dividend-adjusted daily closes. Business-day index `i`; formation day `t`.
- Backtest: rebalance at the last trading day of each month, signal uses closes through `t`, trade at the **open of t+1** (matches WInS, where per `research/07_competition_rules.md` orders placed while the market is closed fill at the next open; sensitivities: close of t+1, close of t). Live: signal through the Tue Oct 20, 2026 close, enter pre-open orders for the Wed Oct 21 open (or run the preview on Fri Oct 16 data). Also run the backtest with rebalance dates shifted by 0-20 trading days to show the result does not depend on the calendar offset (live trade is mid-month).
- Universe: liquid US large caps (S&P 500 or Russell 1000), **point-in-time membership if you can get it**; price >= $5; at least 253 trading days of history (excludes recent IPOs, consistent with DM's minimum-history rule); exclude names with pending M&A. Competition constraints (per `research/07_competition_rules.md`, not verified by me): long-only, no margin/short/derivatives, US-listed stocks/ETFs/Treasuries, $300,000 cash, price >= $5 (2025-26 rule, comply anyway), order <= 2x daily volume, a WInS per-stock position limit may exist. The spec assumes long-only, cash allowed, no leverage; **verify the WInS rules panel**.

Step 1 - signal
- `MOM_i = P_i[t-21] / P_i[t-252] - 1` (12-1; matches French "12-2" and DM "t-12..t-2"). Require valid prices at both ends and at least 90% non-missing days.

Step 2 - hard filters (all must pass; each is ablated in the grid)
1. Quality filter: defined in the separate quality doc (point-in-time fundamentals, lagged by reporting delay).
2. Trend: `P_i[t] > SMA200_i[t]` (optional +/-1% band, Siegel).
3. RSI: `50 <= RSI14_i[t] <= 70`, Wilder smoothing, computed on adjusted closes through `t`. [H]
4. (Optional) 52-week-high ratio `P[t] / max(P[t-251..t]) >= 0.90`. [George-Hwang, adapted]

Step 3 - rank and select
- Rank survivors by `MOM` descending; hold the top **N = 10** (grid 5 / 10 / 20). If fewer than N pass, hold only those that pass at weight 1/N and leave the remainder in cash (**never backfill with names that failed a filter**).

Step 4 - weights
- Equal weight `1/N` of the equity sleeve (JT, DM, French all use equal/value-weighted deciles; equal weight is the natural analog for top-N).

Step 5 - exposure scalar (vol-scaling), base ON
- `w_t = min(1, s_tgt / s_hat_t)`; `s_hat_t = sqrt(252 * mean(r^2))` over the previous 126 daily returns of the strategy's own back-cast portfolio (the equal-weighted portfolio of the names selected at `t`, run over the last 126 days) [adaptation of BSC; uncentered; annualized]. Base `s_tgt = 20%` (near the long-run vol of the winners decile; so it binds only in stress). Remainder `1 - w_t` in T-bills (`^IRX`, as the repo does) or cash.
- Alternative gauge (grid): `s_hat` = 126-day vol of a long-short momentum proxy; BSC's 12% target; cap 1.
- Evidence level: research-backed for long-short WML (BSC, DM); adapted for long-only, supported by my decile-level test (Sharpe up, drawdown down in both eras) but not by a paper.

Step 6 - exits between rebalances
- Base: **month-end trend-break exit only** - re-apply the Step 2 filters (at least the 200-day condition) at each rebalance; a stock that fails is sold. Equivalent to Faber's monthly rule applied per stock.
- Grid: (a) daily 200-day check (sell next close, stay in cash until next rebalance), (b) stop-loss at 10% / 15% / 20% from the rebalance execution price, checked daily on closes, proceeds to cash, no re-entry until next rebalance (HZZ-style).
- Evidence level: stop-loss research-backed for long-short only; trend exit research-backed for indices; **both unproven for a long-only 5-10 stock book and both reduced Sharpe in my decile-level tests**.

Step 7 - costs and accounting
- Cost base: 10 bp of traded value plus $25 per trade (see 10.2); grid 0 / 10 bp / 10 bp + $25 / 25 bp. Report turnover, average number of holdings, % of months partly in cash, and the Step-5 average weight.

Step 8 - what NOT to do
- Do not use centered or shorter-than-63-day vol windows; do not size from the best backtest cell; do not let filters use post-formation information (fundamentals reported after `t`, index membership after `t`).

---

## 12. Parameter grid (with evidence labels)

Run (1) one-at-a-time ablations around the base, then (2) a limited factorial on the five main knobs: N {5, 10, 20} x 200DMA {off, on} x RSI {off, 50-70} x exit {month-end, stop 10, stop 15} x vol-scale {off, own-vol 20%} = 72 configs. Report the surface, not the argmax.

| Knob | Values | Support |
|---|---|---|
| Formation window | **12-1 (base)**, 6-1, 12-7 | 12-1: R (JT93 12/3 best at 1.31-1.49%/mo; DM/French convention). 6-1: R (JT93 headline 6/6 about 1%/mo; also the (6,6) baseline in George-Hwang). 12-7: R (Novy-Marx, abstract only) |
| Skip | **21 days**, 5 days, 0 | R (JT93: skip a week slightly better; DM/French skip a month) |
| Top-N | 5, **10**, 20 (+ decile of universe as reference) | 5-10: [H] team doc. 20+: R-ish (diversification literature: 30-50 for full idio diversification) |
| Weighting | **equal**, inverse-vol | equal: R; inverse-vol: [H] |
| Rebalance | **monthly**, staggered K=3 tranches, quarterly | monthly: R (JT/DM/BSC/French); staggered: R (JT93 overlap design) |
| 200-day SMA filter | off, **on**; band 0 / 1% | on: R-index-level (Faber, BLL [S], Siegel) + stock-sorted (Han-Yang-Zhou [S]); band: R (Siegel via Faber) |
| RSI(14) band | off, **50-70**, `<=70` only | **[H] practitioner heuristic**; upper bound has a plausible reversal rationale (not evidence) |
| 52-week-high >= 90% | off, on | R (George-Hwang 2004) |
| Frog-in-the-pan ID filter | off, low-ID half | R-weak (abstract only; formula unverified) |
| Stop-loss | **off**, 10%, 15%, 20% | R for long-short only (HZZ, [S], gross); long-only unproven |
| Trend-break exit | month-end (base), daily | month-end: R-index (Faber); daily: R-BLL-style [S] |
| Vol-scaling | off, **own-vol 20% cap 1**, own-vol 15%, WML-gauge 12% cap 1 | R for long-short (BSC, DM); long-only adaptation = [OWN] evidence only |
| DM regime flag | off, bear -> 50%, bear -> cash | R for WML (DM); weak for long-only [OWN] |
| One-way cost | 0, 10 bp, **10 bp + $25/trade**, 25 bp | JT93 50 bp conservative; FIM 8-18 bp live price impact for long-only momentum; $25/trade is a third-party report of WInS commissions (unconfirmed) |
| Rebalance-date offset | 0-20 trading days | method (robustness) |

### Backtest hygiene (what judges will ask)
1. **Survivorship:** yfinance only has current tickers; momentum on today's survivors is inflated. Use point-in-time membership, or treat the stock-level backtest as relative only and anchor absolute levels on the French deciles.
2. **Look-ahead:** fundamentals lagged by reporting delay; signals use data through `t` only; trades at t+1.
3. **Multiple testing:** the grid above has 72+ configs; split time (e.g., choose on 2000-2014, confirm 2015-2026), prefer neighbors that agree, report the number of trials (deflated Sharpe, Bailey & Lopez de Prado 2014 [not fetched]).
4. **Benchmarks:** SPY, equal-weight universe, French EW D10 and VW D10 (section 9), plus the same strategy with all filters off.
5. **Regime splits:** pre/post 2009, 2020, 2022 and the Apr-Aug 2026 swings (section 13).
6. **Metrics:** CAGR, vol, Sharpe, Sortino, max drawdown, Calmar, worst month, turnover, holdings count, cash share, alpha/beta vs market (and vs FF3 + Mom).

---

## 13. Regime snapshot for the Oct 21, 2026 decision [OWN; French data through 2026-08-31]

- 126-day annualized (uncentered) vol on 2026-08-31: **decile WML 53.0%** (long-run 27.6%; BSC weight at 12% target = **0.23**, vs 0.84 average), **winners decile 41.6%** (long-run about 22%; a 20% own-vol target would imply weight about 0.48), French 2x3 Mom factor about 24% (long-run 16%).
- Monthly decile returns (French monthly file): winners D10 Apr +31.7%, May +20.0%, Jun +8.4%, **Jul -15.4%**, Aug -0.06%; losers D1 Jul +7.3%, Aug **+14.3%**; WML Jul -22.7%, Aug -14.4%; market Jul -0.3%, Aug +2.9%. Daily WML best/worst in the last 126 days: +10.9% (Jul 30) and -8.5% (Jul 28).
- DM state: 24-month market return +41.7% (not bear), winners and market both above their own 200-day SMAs. So this is a **high-vol momentum crash in a non-bear market**, a state DM's regression does not flag; BSC/DM-style vol rules do.
- Implication (decision input, not advice): a vol-scaled rule would currently run well below full exposure; unscaled top-N momentum is carrying about double the usual risk. French data end Aug 31, so **recompute from daily prices through Oct 20** (in-universe long-short proxy or the strategy's back-cast portfolio) before Wed.

---

## 14. Not verified / open items
1. BSC primary text (formula wording, exact sample dates, skewness/kurtosis, whether any weight cap/winsorization is used). Numbers above are from CXO's summary and my replication, which agree closely.
2. HZZ primary text (formation window for the baseline, exact execution/limit-order rule, how results differ between the 2014 and later versions, units of the Sharpe ratios).
3. DM final JFE 2016 numbers (I read the Aug 2014 draft).
4. BLL 1992 and Siegel (2008) numbers; Novy-Marx table values; Da-Gurun-Warachka ID formula and units; Korajczyk-Sadka details; McLean-Pontiff beyond the abstract; Fama-French (2012) regional table; Sullivan-Timmermann-White conclusion; diversification-count studies beyond summaries.
5. No academic source for RSI 50-70 + momentum.
6. All [OWN] numbers use Ken French's decile data (value-weighted, NYSE/AMEX/NASDAQ, formed on 12-2), not our S&P-500-style universe, with no costs. They are sanity checks and priors, not predictions.
7. Competition rules (cash/short/leverage, commissions, position limits, minimum holdings, data timing) are taken from the other agent's `research/07_competition_rules.md` and need confirming in the WInS rules panel; the spec assumes long-only, cash allowed, no leverage. That doc also says the live holding window after Oct 21 is only 13 trading days and the stock sleeve is meant as a long-horizon allocation, so the monthly-rebalance backtest justifies the *rule*; it does not describe the live P&L.

---

## 15. Source list (URLs)

Primary / read
- Jegadeesh & Titman 1993: https://www.bauer.uh.edu/rsusmel/phd/jegadeesh-titman93.pdf ; https://doi.org/10.1111/j.1540-6261.1993.tb04702.x
- Daniel & Moskowitz (working paper Aug 2014, read): https://business.columbia.edu/sites/default/files-efs/pubfiles/4607/mom11.pdf ; published: https://www.sciencedirect.com/science/article/pii/S0304405X16301490 ; NBER: https://www.nber.org/papers/w20439
- Faber 2007: https://mebfaber.com/wp-content/uploads/2016/05/SSRN-id962461.pdf
- George & Hwang 2004: https://www.bauer.uh.edu/tgeorge/papers/gh4-paper.pdf
- Frazzini, Israel, Moskowitz (Dec 2012 draft): https://conference.nber.org/conf_papers/f68262/f68262.pdf
- Ken French data library: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html

Secondary / abstract-level
- Barroso & Santa-Clara: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2041429 ; https://doi.org/10.1016/j.jfineco.2014.11.010 ; https://novaresearch.unl.pt/en/publications/momentum-has-its-moments/ ; CXO: https://www.cxoadvisory.com/momentum-investing/avoiding-momentum-strategy-crashes/ ; GARP replication: https://www.garp.org/hubfs/Whitepapers/a1Z1W0000054xSXUAY.pdf ; R-bloggers: https://www.r-bloggers.com/2015/09/hypothesis-driven-development-part-iv-testing-the-barrososanta-clara-rule/
- Han, Zhou, Zhu: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2407199 ; Quantpedia https://vvv.quantpedia.com/?p=558 ; CXO https://www.cxoadvisory.com/?p=25071 ; Alpha Architect https://alphaarchitect.com/2016/08/taming-the-momentum-roller-coaster-fact-or-fiction/
- Kaminski & Lo 2014: https://dspace.mit.edu/handle/1721.1/114876
- Brock, Lakonishok, LeBaron 1992: https://ideas.repec.org/a/bla/jfinan/v47y1992i5p1731-64.html
- Sullivan, Timmermann, White 1999: https://doi.org/10.1111/0022-1082.00163 ; Park & Irwin 2007: https://ideas.repec.org/a/bla/jecsur/v21y2007i4p786-826.html
- Han, Yang, Zhou 2013 (JFQA): https://resolve.cambridge.org/core/journals/journal-of-financial-and-quantitative-analysis/article/new-anomaly-the-crosssectional-profitability-of-technical-analysis/B9E41049F2E55B4F274D46E72ECA8E29
- Novy-Marx 2012: https://ideas.repec.org/a/eee/jfinec/v103y2012i3p429-453.html
- Da, Gurun, Warachka 2014: https://ideas.repec.org/a/oup/rfinst/v27y2014i7p2171-2218..html ; https://digitalcommons.chapman.edu/business_articles/115/
- Jegadeesh & Titman 2001: https://www.nber.org/papers/w7159
- Korajczyk & Sadka 2004: https://ideas.repec.org/p/wpa/wuwpfi/0308004.html ; https://www.kellogg.northwestern.edu/faculty/korajczy/htm/korajczyk%20sadka.jf2004.pdf
- McLean & Pontiff 2016: https://www.gwern.net/doc/economics/2016-mclean.pdf ; Chordia, Subrahmanyam, Tong 2014: https://quantpedia.com/does-high-market-liquidity-cause-vanishing-equity-anomaly-returns/
- Fama & French 2012: https://www.johnhcochrane.com/s/Fama_French_size_value_momentum_JFE.pdf
- Diversification: Campbell, Lettau, Malkiel, Xu 2001: https://www.nber.org/papers/w7590.pdf ; review of Evans-Archer / Statman: https://businessperspectives.org/images/pdf/applications/publishing/templates/article/assets/3162/imfi_en_2010_01_Benjelloun.pdf
- Wilder RSI algorithm: https://traders.com/documentation/FEEDbk_docs/2002/10/TradersTips/TradersTips.html ; https://help.tc2000.com/a/747071 ; RSI(2) out-of-sample test (CXO): https://www.cxoadvisory.com/technical-trading/out-of-sample-tests-of-bullish-regime-2-day-rsi-signals
