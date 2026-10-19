# 06 - Backtest methodology and evaluation spec

Prepared 2026-10-18 for Capital Crew (Wharton Global High School Investment Competition 2026-27; first trades Wed 2026-10-21).
Audience: (a) the programmer who will write `metrics.py` / `stats.py`, (b) the teammates who write the report.
Scope: items 1-7 of the brief (McLean-Pontiff, performance statistics, factor regressions, overfitting statistics, parameter-selection protocol, survivorship/look-ahead, short-horizon evaluation). Vol-scaling (Barroso-Santa-Clara) and Daniel-Moskowitz are covered elsewhere and skipped.

All math below is plain text. Conventions: `r` = vector of simple periodic returns, `rf` = periodic risk-free return, `b` = benchmark return, `ppy` = periods per year (12 monthly, 252 daily), `Phi` = standard normal CDF, `Phi^-1` its inverse, `sd` uses n-1 (ddof=1) unless said otherwise.

---

## 0. Read this first

### 0.1 Ten-line summary

1. McLean & Pontiff (2016): 97 published cross-sectional predictors. Average long-short return is 58.2 bps/month in the original samples. Regression estimates say returns are 26% lower after the original sample ends (an UPPER BOUND on data-mining/statistical bias) and 58% lower after publication; the 32-point gap (58 - 26) is attributed to publication-informed trading. Details and caveats in section 1.
2. Honest use of the paper: it is a reason to (i) test on a window that is mostly AFTER publication, (ii) haircut expected alpha, (iii) insist on out-of-sample confirmation. It is NOT a reason to say that a strategy the team tuned itself is immune from decay. A self-tuned strategy has its own, probably larger, data-mining bias that the 26% figure does not cap (section 1.4).
3. With ~15.75 years of monthly data (2010-01 to 2026-09) the team cannot "prove" a long-only strategy beats the market in the Harvey-Liu-Zhu sense (t > 3 needs an annualized Sharpe of 0.76 on the full sample, 1.08 on a 7.75-year test window). Pure noise, searched over a 54-cell grid on 7.75 years, produces a best-cell Sharpe of about 0.83 (Table 4.A). The defensible claim is "consistent with published evidence, robust to nearby parameters, survives costs and an untouched test window, and we expect it to decay."
4. Use the DSR and PBO diagnostics, but report them as diagnostics, with the trial count written down BEFORE running (section 4.3).
5. Parameters: pre-register grids; choose on 2010-2018 (train) with the plateau rule in section 5.4; confirm once on 2019-2026-09 (test). Settings already in `quant/settings.py` (TRAIN_END 2018-12-31, TEST_START 2019-01-01) match this.
6. Costs: charge cost per side on traded notional (cost = c * sum|dw| = 2 * c * one-way turnover). Base 10 bps/side large caps, 20-30 bps mid/small; stress 2.5x. Monthly top-10 momentum is the strategy most exposed to cost.
7. Biggest practical bias risks in the data stack: survivorship (delisted names missing), look-ahead from `frames`/restated XBRL values, current index membership/GICS used for 2010, and split-basis mismatch between yfinance prices and EDGAR share counts (section 6).
8. The competition window is dominated by noise, and it may be much shorter than "a few months": the sibling file `07_competition_rules.md` (citing the official Wharton "Trading Details" page; I did not verify it) says trading is frozen on Fri 2026-11-06, which leaves only 13 trading days after the Wed 2026-10-21 trades. With a true information ratio of 0.3 and 6% tracking error, P(beat the S&P 500) is 52.7% over 13 trading days, 56% over 3 months and 58% over 6 months (Table 7.A). Expected 13-day active return is 0.09% against a standard deviation of 1.4%; at 3 months, 0.45% against 3.0%.
9. Blending three strategies helps only to the extent their ACTIVE returns are uncorrelated; if they are 0.8 correlated the combined IR is only 7% above a single strategy's (section 7.3).
10. Before Wed 2026-10-21 do only the "minimum viable" list in section 10; everything else is for the written report.

### 0.2 What was verified, and how

| Item | Status |
|---|---|
| McLean-Pontiff headline numbers (26%, 58%, 32%), 58.2 bps in-sample mean, regression coefficients -0.150 / -0.337, time-FE result, Figure 2 timing text | Verified from the text of the AUTHORS' "Journal of Finance, Forthcoming" PDF (copy hosted at counterpointfunds.com). Wiley's page returned HTTP 403 so I did NOT read the typeset JF version; the abstract numbers are identical in every source I saw. |
| JSTOR 43869094 is the same paper | NOT verified. The JSTOR page failed to load (script error); Crossref's record for DOI 10.1111/jofi.12365 does not list a JSTOR id; a web search for "43869094" returned nothing relevant. It is very likely the JSTOR copy of the same Journal of Finance article (JSTOR hosts JF), but the team should click it and confirm the title reads "Does Academic Research Destroy Stock Return Predictability?" |
| JF citation: vol 71, issue 1, pp 5-32, DOI 10.1111/jofi.12365 | Verified (Crossref API and AFA issue page). Online 2016-01-14, print issue dated February 2016. |
| DSR / PSR / expected-max-Sharpe formulas | The paper's PDF text lost its math symbols in extraction, so the algebra below is from my memory of the paper, BUT I verified it numerically: my implementation reproduces the paper's own worked example (N=100 -> DSR 0.90; N=46 -> 0.9505; Normal returns cross 0.95 at N=88). |
| CSCV / PBO algorithm | Verified from the text of Bailey-Borwein-Lopez de Prado-Zhu (Feb 2015 draft). |
| N_eff = rho + (1 - rho) * M for correlated trials | NOT verified (Appendix 3 text did not extract; I saw only that its Exhibit 4 plots N against average correlation and M). From memory. Report DSR at both N=M and N_eff. |
| Harvey-Liu-Zhu: abstract, "t > 3.0", Bonferroni 3.78 by 2012, BHY 3.39 (1% FDR), minimum 3.18, 316 factors | Verified from the text of NBER WP 20592. |
| Harvey-Liu (2015) "Backtesting" haircut method | Abstract-level only (via search summaries). The authors explicitly argue AGAINST a flat 50% haircut; they convert Sharpe -> t -> p, adjust p for the number of tests, convert back. Details of their other adjustments not verified. |
| Frazzini-Israel-Moskowitz trading costs | Numbers below come from the Dec 2012 PRELIMINARY draft (NBER conference PDF; 19 markets, 1998-2011). The later SSRN version "Trading Costs" (SSRN 3229719) says 21 markets, 1998-2016, ~$1.7T of trades, costs an order of magnitude below prior studies; I only saw that abstract-level summary, not its tables. |
| Lo (2002): iid SE formula | Verified (formula reproduces the paper's own table values: T=60, SR=1.5 -> 0.188; SR=3.0 -> 0.303). The autocorrelation annualization factor eta(q) is from a secondary source plus memory. |
| Ken French / AQR data facts | Verified from the websites on 2026-10-18: FF3 monthly starts July 1926; FF5 (2x3) monthly starts July 1963; French's files run through August 2026; AQR's QMJ page says "U.S. long sample (starting 1956)". Start date of the French Momentum file was not on the pages I fetched (commonly January 1927; unverified). |
| SEC deadlines (10-K 60/75/90 days; 10-Q 40/40/45) | Verified via SEC Fast Answers (Form 10-Q) summary and Release 33-8644. A 2026 SEC document in the results is a PROPOSED rule restating the same figures; check nothing has changed. |
| SEC `frames` API uses the entity's last-filed fact | Verified on sec.gov/edgar/sec-api-documentation. The page does NOT list the fact-record fields (`end, val, accn, fy, fp, form, filed, frame`); I rely on practitioner knowledge that they exist. |
| XBRL phase-in: periods ending on/after 2010-06-15 (other large accelerated) and 2011-06-15 (all remaining) | Verified in SEC staff guidance snippets. The first-phase date (mid-June 2009, >$5B float) is NOT confirmed to the day. |
| Survivorship magnitudes (Elton-Gruber-Blake ~0.9%/yr; Shumway -30%) | Secondary sources only (Wikipedia/summary sites). Shumway-Warther's -55% correction for missing performance-related Nasdaq delisting returns was verified from the abstract on IDEAS. Treat all as indicative. |
| Sortino/Calmar/ERC/Pardo WFE/Kiefer-Vogelsang conventions | From memory; flagged where used. |
| Code | Every function in Appendix A was executed against synthetic data (see "Tests run"); HAC output was checked against a brute-force loop implementation, NOT against statsmodels (not installed in my sandbox). |

---

## 1. McLean & Pontiff (2016)

### 1.1 What the two links are

- https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365 = R. David McLean and Jeffrey Pontiff, "Does Academic Research Destroy Stock Return Predictability?", Journal of Finance 71(1), February 2016, pp. 5-32. DOI 10.1111/jofi.12365. (University of Alberta / Boston College.) Winner of the 2016 Amundi Smith Breeden Prize per a secondary source.
- https://www.jstor.org/stable/43869094 = probably the JSTOR copy of the same article (see 0.2, unverified). If it is, cite the paper once, not twice.

### 1.2 The numbers (from the authors' forthcoming-version text)

Design: 97 cross-sectional predictors (from roughly 80 published papers) turned into equal-weighted long-short portfolios of extreme quintiles (value-weighted only for Ang et al. 2006). Data 1926-2013. Each predictor is observed in three regimes: (i) original study sample, (ii) after the sample ends but before publication, (iii) after publication. Average gaps: sample end to publication 56 months; average original sample 323 months; average post-publication span 156 months.

| Quantity | Value |
|---|---|
| Average in-sample long-short return | 58.2 bps/month (0.582%) |
| Raw average, out-of-sample but pre-publication | 40.2 bps/month |
| Raw average, post-publication | 26.4 bps/month |
| Regression (eq. 1, Table II col. 1): out-of-sample dummy | -15.0 bps/month => 15.0 / 58.2 = 26% decline |
| Regression: post-publication dummy | -33.7 bps/month => 33.7 / 58.2 = 58% decline |
| Publication-specific effect | (33.7 - 15.0) / 58.2 = 32% ("publication-informed trading") |
| Same, dropping the 12 predictors with in-sample t < 1.5 (85 left) | -18.0 and -38.7 bps |
| With month fixed effects (all time-series decay absorbed; Table III col. 4) | -17.9 bps out-of-sample, -31.0 bps post-publication => 53% post-publication decline |

Regression (their eq. 1, as I read it): R(i,t) = a(i) + b1 * PostSample(i,t) + b2 * PostPublication(i,t) + e(i,t), predictor fixed effects a(i), standard errors robust to contemporaneous cross-sectional correlation. Each coefficient is measured relative to in-sample months. The authors state b1 (26%) is an UPPER bound on pure statistical bias "since some traders are likely to learn about the predictor before publication", and 58% - 26% = 32% is a LOWER bound on the publication effect. Note the raw means in their Table I imply smaller gaps (40.2/58.2 = -31%, 26.4/58.2 = -55%); the 26%/58% headline comes from the fixed-effects regression, not the raw means.

Timing (their Figure 2, which the authors caution has low power): returns in the first 12 months after the sample ends look like in-sample (coefficient about zero); the last 12 in-sample months are unusually strong (possible sample-end selection); afterwards returns are more than 20 bps lower; decay is 40.8 bps in publication year 3, 43.3 bps in year 4, 20.5 bps in year 5, and about 33.9 bps lower than in-sample after year 5.

Cross-section (abstract and text): decay is larger for predictors with higher in-sample returns and in-sample t-statistics; larger for predictors built from price/trading data only; post-publication returns are lower for portfolios of liquid, low-idiosyncratic-risk stocks (cheap to arbitrage) and relatively preserved in illiquid, high-idiosyncratic-risk stocks. After publication volume, variance and short interest in predictor stocks rise, and predictor portfolios become more correlated with other published predictors.

Caveats from the paper itself: results are gross of trading costs and shorting costs; the 97 are averages (individual strategies, e.g. momentum and value, behaved differently); and there are alternative explanations (rising hedge fund presence, falling trading costs) that the time-trend and time-fixed-effect checks only partly rule out. A secondary summary says the earlier 2013 working paper (82 predictors) reported smaller declines (about 10% out-of-sample, 35% post-publication); I did not verify that, but it shows the headline is sample-sensitive.

### 1.3 What it means for Capital Crew's three strategies

- Momentum (Jegadeesh-Titman 1993), profitability/quality (Novy-Marx 2013; Asness-Frazzini-Pedersen), earnings-yield/ROC value (Greenblatt, book 2005) were all public long before 2010. A 2010-2026 backtest is therefore mostly a POST-PUBLICATION test. If the premia show up there, that is evidence of persistence after publication (good). If they are weaker than the original papers, that is exactly what McLean-Pontiff predict (expected, not alarming).
- The paper's numbers are long-short, equal-weighted, gross. Team portfolios are long-only, concentrated, net of costs. Do not transplant 26% / 58% mechanically; use them as a plausible RANGE for the shrinkage of expected alpha.

Planning haircut (a heuristic, not a result from the paper): IR_forward = IR_backtest * (1 - d), d in {0.26 (optimistic, data-mining only), 0.58 (post-publication)}. Example: backtest IR 0.5 -> forward IR 0.37 (d=0.26) to 0.21 (d=0.58); with 6% tracking error, expected 3-month active return is 0.55% to 0.32%.

### 1.4 The Atrina note: how to use the argument honestly

The note says: if we pick a strategy we backtested ourselves rather than a published one, "we could say it strengthens our strategy" using the 2016 paper. Assessment:

- Partly right: a variant that has not been published has not been through the publication-driven 32% decay; and out-of-sample confirmation (test window, then the live window) does strengthen any claim. Part of the 58% is pure arbitrage by readers of papers.
- Where it breaks: (a) the team's variants are close cousins of published signals (relative P/E and EV/EBITDA are value ratios; momentum + gross profitability are published), so the publication effect is already priced into the signal class; (b) the 26% out-of-sample decline is the average data-mining haircut of ONE specification per paper that cleared t > ~2; the team's grid (up to 54-108 cells, plus RSI/200DMA/size filters) has far more researcher degrees of freedom, so its data-mining bias can be much larger and is not capped by 26%; (c) a self-built strategy has zero out-of-sample history until the test window and the live period.
- Honest framing: "Published anomalies lose roughly a quarter to a half of their returns out of sample and after publication (McLean & Pontiff 2016). We therefore (1) evaluate on 2010-2026, mostly post-publication; (2) fix parameters on 2010-2018 with a pre-registered plateau rule and confirm them untouched on 2019-2026; (3) report returns net of trading costs and adjust Sharpe ratios for the number of variants we tried (Deflated Sharpe Ratio, Probability of Backtest Overfitting); and (4) plan around alpha smaller than the backtest shows."
- Do not claim: "our own backtest strengthens the case" or "decay does not apply to us".

---

## 2. Performance statistics (exact formulas)

### 2.1 Conventions

- Returns: simple periodic total returns (dividends reinvested). Prices from yfinance with `auto_adjust=True` (Close = split- and dividend-adjusted, a total-return index). Do not use dividend-adjusted prices for valuation (section 6.4).
- Frequency: monthly (ppy=12) for all inference (regressions, bootstrap, DSR, PBO). Daily (ppy=252) only for max drawdown, VaR-type stats, and the short-horizon windows. Monthly max drawdown understates the daily one; label which you report.
- Risk-free: Ken French `RF` (monthly, percent -> divide by 100) so Sharpe and the factor regressions use the same rf. For daily work use ^IRX converted: rf_daily = (1 + y/100)^(1/252) - 1 (approximation).
- Benchmarks (always show all three): SPY total return (the market), RSP (equal-weight S&P 500; inception 2003-04-24, 0.20% expense ratio, rebalanced quarterly), and EW-universe (equal-weight of exactly the stocks the strategy could have chosen from, no signal). The last one separates "signal" from "universe".
- Windows: Full, Train (2010-2018), Test (2019-2026-09), last 36 months, plus calendar subperiods (2010-14, 2015-18, 2019-21, 2022-26).

### 2.2 Formulas

```text
n          = number of periods
W_t        = prod_{s<=t} (1 + r_s),  W_0 = 1

CAGR       = W_n^(ppy/n) - 1
AnnVol     = sd(r) * sqrt(ppy)
Sharpe     = mean(r - rf) / sd(r - rf) * sqrt(ppy)            (arithmetic mean of excess returns)
SE(SR)     = sqrt((1 + 0.5*SR_p^2) / n)  per period (iid, Lo 2002), SR_p = non-annualized SR;
             annualized SE = SE * sqrt(ppy)
Sortino    = mean(r - rf) / DD * sqrt(ppy)
             DD = sqrt( (1/n) * sum_t min(r_t - rf_t, 0)^2 )   (denominator n, all observations; matches utils.summarize)
Drawdown_t = W_t / max_{s<=t} W_s - 1
MaxDD      = min_t Drawdown_t
Calmar     = CAGR / |MaxDD|                                    (full sample; also report on trailing 36 months)
HitRate    = (1/n) * #{t : r_t > b_t}                          (monthly; also for rolling 3m / 6m windows)
Active_t   = r_t - b_t
TE         = sd(Active) * sqrt(ppy)
IR         = mean(Active) / sd(Active) * sqrt(ppy)
ActiveCAGR = (1 + CAGR_p) / (1 + CAGR_b) - 1                   (geometric; also show CAGR_p - CAGR_b)
Beta       = Cov(r - rf, b - rf) / Var(b - rf)                 (OLS slope; CAPM alpha = intercept * ppy)
Capture    = mean(r | b > 0) / mean(b | b > 0) (up);  mean(r | b < 0) / mean(b | b < 0) (down)
```

Annualization caveat (Lo 2002): Sharpe * sqrt(12) is exact only for iid returns. With serial correlation rho_k use eta(q) = q / sqrt(q + 2 * sum_{k=1}^{q-1} (q - k) * rho_k) in place of sqrt(q) (q = 12). Run a Ljung-Box check; if significant, report both. Lo reports overstatement of up to 65% for hedge-fund monthly Sharpe ratios; for these equity strategies expect it to be small.

### 2.3 Turnover and costs

```text
Drifted (pre-trade) weights at rebalance date t, using the PREVIOUS target weights w_{t-1}:
    w_pre(i,t) = w(i,t-1) * (1 + r(i,t)) / (1 + r_p(t))          (cash is an asset with return rf)
Trade:           dw(i,t) = w_target(i,t) - w_pre(i,t)
One-way turnover TO_t = 0.5 * sum_i |dw(i,t)|                     (100% = replace the whole portfolio once)
Annual one-way turnover = sum of TO_t over the year (monthly rebalance: roughly 12 * average TO_t)
Cost (fraction of NAV):  Cost_t = sum_i c(i) * |dw(i,t)|          c(i) = cost per SIDE per unit notional, bps/1e4
                         flat c:  Cost_t = c * sum|dw| = 2 * c * TO_t
Net return:       r_net,t = r_gross,t - Cost_t                    (charged in the period the trade executes)
```

Pitfalls: (a) use DRIFTED weights, not last period's target; (b) a "10 bps one-way" cost means 10 bps on every buy AND every sell, so replacing a whole portfolio costs 20 bps; (c) execute at t+1 close for signals at t close (`EXEC_LAG_DAYS = 1` in `quant/settings.py`).

Drag table (bps of NAV per year = 2 * c * annual one-way turnover):

| Annual one-way turnover | c = 10 bps | c = 25 bps | c = 50 bps |
|---|---|---|---|
| 50% | 10 | 25 | 50 |
| 100% (annual rebalance, Magic Formula-like) | 20 | 50 | 100 |
| 360% (monthly top-10, ~30% of names replaced per month) | 72 | 180 | 360 |
| 600% | 120 | 300 | 600 |

Cost schedule (per side, base / stress = 2.5x): mega/large (top ~500 by market cap) 10 / 25 bps; mid ($2-10B) 20 / 50; small ($0.3-2B) 30 / 75; micro (< $0.3B) 50 / 125 or exclude and add a minimum average dollar volume filter (suggest >= $5M/day). Always report gross AND net, and net Sharpe/alpha at c = 0 / 10 / 25 / 50 bps.

Evidence for these magnitudes (Frazzini, Israel & Moskowitz, preliminary Dec 2012 draft, live AQR trades, 1998-2011, 19 developed markets): mean market impact 12.18 bps and implementation shortfall 13.0 bps per trade (median 7.98 / 10.34); dollar-weighted means 18.65 / 20.20 bps; large caps 11.21 bps versus small caps 21.27 bps; long-only trades about 16 bps versus about 10 bps for long-short; roughly 70% of impact is permanent; measured against VWAP the average is only 3.7 bps (9.4 bps against the arrival/theoretical price). Execution prices include commissions. The same draft computed annual cost drag for institutional-size long-short strategies of about 1.5% (value, 68% monthly turnover), 3.5% (momentum, 127% monthly turnover) and 6.75% (short-term reversal, 305%) - momentum is the cost-sensitive one. These traders were institutions moving billions, so for a student-size portfolio in liquid names 10 bps/side is conservative to reasonable; for small/micro caps it may be optimistic. Novy-Marx & Velikov (RFS 2016, 29(1):104-147): anomalies with under 50% monthly turnover tend to keep significant net spreads when built to limit costs, and a buy/hold spread (stricter rule to enter than to stay) is the most effective mitigation - adopt it for momentum (enter on top-10 rank, exit only when rank > 30). Note their costs use effective bid-ask spreads (small trader) and every cost reduces significance, which worsens the data-snooping problem.

---

## 3. Factor regressions

### 3.1 Data

- Ken French data library (https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html): `F-F_Research_Data_Factors_CSV.zip` (Mkt-RF, SMB, HML, RF; monthly from July 1926), `F-F_Research_Data_5_Factors_2x3_CSV.zip` (Mkt-RF, SMB, HML, RMW, CMA, RF; monthly from July 1963), `F-F_Momentum_Factor_CSV.zip` (Mom). All values are in PERCENT: divide by 100. Files run through August 2026 on the day I looked, so the September 2026 return month will not have factors; truncate regressions to the common sample. French notes the current US monthly returns use CRSP's "CIZ" format from the January 2025 release, so re-download rather than mixing old cached files.
- Factor definitions (French's page): Mkt-RF = value-weighted CRSP US market minus 1-month T-bill; SMB = average of small-minus-big across the B/M, OP and INV sorts; HML = average of two value minus two growth portfolios; RMW = robust minus weak operating profitability; CMA = conservative minus aggressive investment; portfolios formed each June (July t to June t+1) with accounting data lagged to t-1.
- AQR (https://www.aqr.com/Insights/Datasets): Quality Minus Junk (US sample starting 1956 per AQR's page), Betting Against Beta, etc. Useful as an alternative quality factor and for long-history checks of the factor premia themselves (not for the 2010-2026 strategy backtest).
- For the 1920s-1960s "factor-level checks": FF3 + momentum are the long histories (1926/27 onward); FF5 starts 1963; QMJ 1956.

### 3.2 Models (monthly, excess returns, y = r_p - rf)

```text
CAPM        y = a + b_M*MKT + e
FF3         y = a + b_M*MKT + b_S*SMB + b_H*HML + e
FF3+MOM     (Carhart 1997 form) + b_U*MOM
FF5         y = a + b_M*MKT + b_S*SMB + b_H*HML + b_R*RMW + b_C*CMA + e   (Fama-French 2015, JFE 116(1):1-22)
FF5+MOM     FF5 + b_U*MOM    <- the headline specification
```

Also run the benchmark-relative version: y = r_p - r_SPY on the same factors, to see which tilts explain the active return of a long-only strategy (beta - 1 shows up on MKT).

### 3.3 Inference: Newey-West HAC

```text
OLS:   b = (X'X)^-1 X'y,   e = y - Xb
HAC:   V = (X'X)^-1 * S * (X'X)^-1  * [T/(T-k)]            (small-sample factor, as statsmodels use_correction=True)
       S = G_0 + sum_{l=1}^{L} w_l * (G_l + G_l'),   w_l = 1 - l/(L+1)  (Bartlett)
       G_l = sum_{t=l+1}^{T} e_t * e_{t-l} * x_t * x_{t-l}'
t_j   = b_j / sqrt(V_jj)
```

Lag choice L (monthly data, T = 93-190): Newey-West (1994) rule L = floor(4 * (T/100)^(2/9)) gives 3 for T = 93 and 4 for T = 108-190. Alternatives: Stock-Watson 0.75 * T^(1/3) (3-4; from memory), T^(1/4) (3). Use L = 4 as the default and report L = 6 and 12 as robustness (momentum-type strategies can have persistent alpha autocorrelation). If you regress on overlapping multi-month returns, L >= horizon - 1. HAC t-statistics over-reject in samples this short; also report t with T - k degrees of freedom and a stationary-bootstrap CI for alpha (section 4.7). Optionally fixed-b critical values (Kiefer-Vogelsang; not verified here).

statsmodels (docs verified: `maxlags` is REQUIRED for HAC, default kernel Bartlett, `use_correction` option, `use_t` defaults to False for robust covariances):

```python
import statsmodels.api as sm
X = sm.add_constant(F[["MKT_RF","SMB","HML","RMW","CMA","MOM"]])
res = sm.OLS(y, X).fit(cov_type="HAC", cov_kwds={"maxlags": 4, "use_correction": True}, use_t=True)
```

`ols_hac` in Appendix A implements the same estimator in numpy (matches a brute-force loop; not cross-checked against statsmodels).

### 3.4 Alpha annualization and reading the output

```text
alpha_ann   = 12 * alpha_monthly                (arithmetic; alt. (1 + alpha_m)^12 - 1, nearly identical for small alpha)
se(alpha_ann) = 12 * se(alpha_monthly);  t-stat unchanged
```

Report for each model: alpha (annualized %), its HAC t, loadings with HAC t, R^2, adjusted R^2, n, L. Interpretation guide:

- Alpha is the average return the factor exposures do not explain. alpha > 0 with HAC t > 2 (but see HLZ: t > 3 for "discoveries") means the strategy earned more than its measured factor tilts predict.
- It is NORMAL and fine for a quality-momentum strategy to load on MOM and RMW and show alpha near zero in FF5+MOM; that says "we harvested known premia", which is the thesis. Expected loadings: quality-momentum: +MOM, +RMW; Magic Formula: +HML, +RMW, possibly +SMB; trading comps: +HML (cheap vs peers).
- FF (2015) find HML becomes redundant for describing average returns once RMW and CMA are included, so do not over-interpret an insignificant HML loading in FF5.
- The market beta of a long-only strategy will be near 1; compare R^2 and the active-return regression to see whether anything is left.
- Factors are gross and long-short; the strategy return should be NET of costs.

---

## 4. Statistical significance and overfitting

### 4.1 t-statistic of the mean excess return and of the Sharpe ratio

```text
t_mean = mean(r - rf) / ( sd(r - rf) / sqrt(n) )       (= SR_p * sqrt(n) = SR_ann * sqrt(Y), Y = years)
t_active = mean(r - b) / ( sd(r - b) / sqrt(n) )        (= IR * sqrt(Y))
```

Required Sharpe for a given t: SR_ann = t / sqrt(Y). With Y = 15.75: t = 2 needs 0.50, t = 3 needs 0.76. With Y = 7.75 (test window): 0.72 and 1.08. For the active return the same applies with IR: a long-only stock-picking strategy with IR above 0.5 is rare, so t_active > 2 over a decade is hard even for a real edge (Table 5.A has the minimum detectable alpha).

### 4.2 Harvey, Liu & Zhu (2016)

"... and the Cross-Section of Expected Returns", Review of Financial Studies 29(1):5-68 (NBER WP 20592). They catalogue 316 factors from 313 papers/working papers and argue that, because of multiple testing, a newly discovered factor needs a t-ratio above 3.0 (not 2.0). Their multiple-testing thresholds: Bonferroni 1.96 in 1967 rising to 3.78 by 2012 (4.00 by 2032); BHY (false discovery rate control, 1%) stabilizes at 3.39 after 2010; if unobserved failed tests are included the minimum is 3.18 (BHY, 5%). Use: this hurdle is for NEW factor discoveries. The team is mostly replicating known premia, so t = 3 is not required to say "consistent with the literature", but it IS the right yardstick if the team claims that its tuned parameter set is better. Report t against 2.0 / 3.0 / 3.39 and be honest when it falls short.

Multiple-testing adjustments (implemented in `adjust_pvalues`):

```text
Bonferroni:  p_adj(i) = min(M * p_i, 1)
Holm:        sort p_(1) <= ... <= p_(M);  p_adj(k) = max_{j<=k} min((M - j + 1) * p_(j), 1)
BH (FDR):    p_adj(k) = min_{j>=k} min(M * p_(j) / j, 1)
BHY:         BH with M replaced by M * c(M),  c(M) = sum_{j=1}^{M} 1/j     (valid under dependence)
```

Haircut Sharpe (Harvey-Liu 2015 recipe, Bonferroni version): t = SR_ann * sqrt(Y); p = 2 * (1 - Phi(t)); p_adj = min(M * p, 1); t_adj = Phi^-1(1 - p_adj/2); SR_adj = t_adj / sqrt(Y); haircut = 1 - SR_adj / SR_ann. Example (Y = 15.75): SR 0.8 with M = 54 tests -> adjusted 0.44 (45% haircut); SR 1.0 -> 0.73 (27%); SR 0.6 -> 0.02 (essentially nothing survives). Harvey and Liu stress that the haircut is nonlinear (small Sharpe ratios are penalized heavily, large ones modestly), unlike the "cut by 50%" rule of thumb. M must be the number of distinct specifications tried (section 4.3).

### 4.3 Probabilistic and Deflated Sharpe Ratio (Bailey & Lopez de Prado)

Reference: "The Deflated Sharpe Ratio: Correcting for Selection Bias, Backtest Overfitting and Non-Normality", Journal of Portfolio Management 40(5):94-107 (2014), SSRN 2460551. Probabilistic Sharpe Ratio from Bailey & Lopez de Prado, Journal of Risk 15(2) (2012).

All Sharpe ratios below are PER-PERIOD (monthly, not annualized); T = number of observations; skew = g3, kurt = g4 (RAW kurtosis, Normal = 3).

```text
PSR(SR*) = Phi(  (SR_hat - SR*) * sqrt(T - 1)
                 / sqrt( 1 - g3 * SR_hat + ((g4 - 1)/4) * SR_hat^2 )  )

E[max_N SR]  =  SR0  =  sqrt( V[{SR_n}] ) * (  (1 - gamma) * Phi^-1(1 - 1/N)  +  gamma * Phi^-1(1 - 1/(N*e)) )
                 gamma = 0.5772156649 (Euler-Mascheroni);  e = 2.71828...
                 V[{SR_n}] = cross-sectional variance of the N trials' Sharpe estimates (same periodicity)
                 N = number of INDEPENDENT trials;  N = 1 -> SR0 = 0

DSR      = PSR(SR0)       (probability that the selected strategy's true Sharpe exceeds the best Sharpe you would expect from N null trials)
```

Check (from the paper's example, reproduced by my code): annualized SR 2.5, T = 1250 daily obs, V[SR_ann] = 0.5, skew -3, kurt 10: N = 100 -> DSR 0.90; N = 46 -> 0.95 (threshold); with Normal returns the 0.95 threshold is reached at N = 88.

Minimum track-record length (inverting PSR; my derivation from the formula): T_min = 1 + (1 - g3*SR_hat + ((g4-1)/4)*SR_hat^2) * (Phi^-1(conf) / (SR_hat - SR*))^2. Normal returns, SR* = 0, 95% confidence: SR 0.3 -> 30 years; 0.5 -> 11.0 years; 0.8 -> 4.4 years; 1.0 -> 2.9 years.

What to count as N (write it down BEFORE running):
- Keep a trial ledger (append-only CSV: timestamp, strategy, parameter dict, universe, window, gross/net Sharpe). N = every configuration ever evaluated for that strategy family, including exploratory runs and dropped variants. Also count choosing among the 3 strategies as 3 more trials at the family level.
- N_eff (correlated grid cells): N_hat = rho_bar + (1 - rho_bar) * M, with rho_bar = average off-diagonal correlation of the M trial return series (from memory of the paper's Appendix 3; unverified). Always report DSR at N = M (conservative) and N = N_hat. Use the empirical variance across the ledger for V[{SR_n}].
- Because grid cells share the same stocks and the same market, rho_bar will be high (0.5-0.95), so N_hat << M; but the variance term shrinks too, so DSR is not as punishing as an independent-trial count.

Table 4.A - best annualized Sharpe you would see from N zero-skill, independent trials (V[SR_ann] = 1/Y, using the SR0 formula):

| N trials | Y = 7.75 (test/train size) | Y = 9 | Y = 12 | Y = 15.75 (full) |
|---|---|---|---|---|
| 1 | 0.00 | 0.00 | 0.00 | 0.00 |
| 3 | 0.31 | 0.28 | 0.25 | 0.21 |
| 9 | 0.55 | 0.51 | 0.44 | 0.38 |
| 27 | 0.73 | 0.68 | 0.59 | 0.51 |
| 54 | 0.83 | 0.77 | 0.67 | 0.58 |
| 108 | 0.92 | 0.85 | 0.74 | 0.64 |
| 216 | 1.00 | 0.93 | 0.81 | 0.70 |

Read: the S&P 500's own Sharpe over 2010-2026 is likely near or above these values, so a best-of-54 Sharpe below roughly 0.8 on a 7-9 year window is indistinguishable from luck. This is why the plateau rule and out-of-sample test matter more than any p-value.

### 4.4 Probability of Backtest Overfitting via CSCV (Bailey, Borwein, Lopez de Prado & Zhu)

"The Probability of Backtest Overfitting", Journal of Computational Finance 20(4), 2017 (SSRN 2326253). Algorithm (verified against the paper):

```text
Input: matrix M (T x N) of per-period returns, column n = trial n (all N parameter configurations,
       same dates). Metric R (default: Sharpe ratio) computable on any sub-sample of rows.
1. Partition rows into S disjoint, equal-size, time-ordered blocks (S even). Trim the earliest remainder rows.
2. Form all C(S, S/2) combinations c of S/2 blocks. (S = 16 -> 12,870 combinations.)
3. For each combination c:
   a. Training set J  = the S/2 blocks in c (original order).      Test set J_bar = the complement.
   b. R_c    = vector of metric values (length N) on J       (in-sample, IS); r_c = ranks of R_c.
      R_bar_c = same metric on J_bar                            (out-of-sample, OOS);  r_bar_c = ranks.
   c. n* = argmax_n R_c[n]                  (the strategy chosen in-sample; use YOUR selection rule here)
   d. omega_c = r_bar_c[n*] / (N + 1)       (relative OOS rank of the IS winner; rank 1 = worst)
   e. lambda_c = ln( omega_c / (1 - omega_c) )   (logit; lambda > 0 means IS winner beat the OOS median)
4. f(lambda) = empirical distribution of lambda_c over all combinations.
   PBO = integral_{-inf}^{0} f(lambda) d lambda = fraction of combinations with lambda_c <= 0.
```

Companion outputs from the same run: (i) performance degradation = slope of OOS Sharpe on IS Sharpe of the chosen n* across combinations (negative slope = overfit); (ii) probability of loss = P(R_bar_c[n*] < 0); (iii) the logit histogram. The paper's customary rejection rule is PBO > 0.05 (Neyman-Pearson style); with a few hundred monthly observations the estimate is coarse, so treat PBO > 0.5 as "selection procedure no better than coin-flip", 0.2-0.5 as "caution", and always show the histogram. My heuristic, not the paper's.

Team-specific rules:
- S = 16 (about 11-12 months per block over 2010-2026); sensitivity S = 8 and 12. Use only whole blocks; drop the oldest remainder.
- The selector must be the team's ACTUAL selection rule. If the team picks with the plateau rule (section 5.4), pass `selector=` a function that applies it; PBO then measures the overfitting of THEIR procedure, not of argmax.
- Run on the full grid of trials that includes exploratory variants (ledger), on net-of-cost returns. Compute on the train window (is the choice stable?) and on the full sample (secondary).
- CSCV treats IS/OOS blocks as exchangeable, so it misses regime change; it complements, not replaces, the chronological test window.

Tested behavior: pure-noise trials (T=192, N=54, S=16) gave PBO 0.43 (expected about 0.5, with sampling noise); adding one genuine +2%/month trial gave PBO 0.02.

### 4.5 White's Reality Check and Hansen's SPA (brief)

Question: after searching K strategies, is the best one better than the benchmark by more than chance? With d(k,t) = L_bench(t) - L_k(t) (loss = negative return, lower is better):

```text
White RC statistic:  V = max_k sqrt(n) * mean_t d(k,t)
Hansen SPA:          T  = max( 0, max_k sqrt(n) * mean_t d(k,t) / omega_k )   (studentized; omega_k = bootstrap std of the mean)
p-value: stationary-bootstrap the date index jointly across all strategies, recompute the statistic on re-centered data
         (SPA re-centers only strategies that are not clearly worse than the benchmark, which restores power vs RC)
```

References: White, Econometrica 68(5):1097-1126 (2000); Hansen, JBES 23(4):365-380 (2005). Implementation (docs verified): `arch.bootstrap.SPA(benchmark_losses, model_losses, block_size=None, reps=1000, bootstrap="stationary", studentize=True)`; `.compute()`; `.pvalues` gives lower/consistent/upper (report "consistent"). Inputs are LOSSES (use negative returns; confirm sign in the arch source). Use on all grid cells vs EW-universe, on the test-free (train) window or full sample. Not run in my sandbox (arch not installed).

### 4.6 Stationary block bootstrap (Politis & Romano 1994)

JASA 89(428):1303-1313. Resamples blocks of RANDOM length (geometric with mean b_bar = 1/p) from the circularly wrapped series, which keeps the resampled series stationary:

```text
idx[0] = Uniform{0..n-1}
for t = 1..n-1:   with prob p = 1/b_bar:  idx[t] = Uniform{0..n-1}      (start a new block)
                  otherwise:              idx[t] = (idx[t-1] + 1) mod n   (continue the block)
resampled series = data[idx]     (resample ROWS jointly: strategy, benchmark, rf, factors)
```

Use for confidence intervals of Sharpe, Sharpe difference vs benchmark (paired rows), IR, alpha (resample rows of [y, factors] and re-run OLS), and hit rates. B = 5,000-10,000; percentile intervals (2.5%, 97.5%). Max drawdown is path-dependent: its bootstrap is only indicative.

Block length b_bar (mean): Politis-White (2004) automatic selection with the Patton-Politis-White (2009) correction; `arch.bootstrap.optimal_block_length(x)` returns `b_sb` (stationary) and `b_cb` (circular). For monthly equity returns this is usually 2-6; floor it at 3, sanity-check against n^(1/3) (n=108 -> 4.8; n=189 -> 5.7), and show b_bar = 3, 6, 12 as sensitivity. For statistics on h-month rolling windows use b_bar >= h. For the grid-wide bootstrap (section 5.5) use ONE index vector for all cells, with b_bar = the median of the cells' optimal values or 6.

Sanity: on iid data the bootstrap SD of the annualized Sharpe (0.241) matched the Lo iid formula (0.254) in my test.

---

## 5. Parameter-selection protocol

### 5.1 Pre-registration (do this before any run; commit the file to git)

`research/prereg_<strategy>.yaml`, one per strategy, written BEFORE the first backtest result is viewed:

```yaml
strategy: trading_comps
primary_metric: net_sharpe_train        # or net_IR_vs_SPY; pick ONE
benchmark_set: [SPY, RSP, EW_universe]
universe: {index_membership: point_in_time_or_flagged, exclude: [financials, utilities], min_mktcap_usd: 3e8, min_adv_usd: 5e6}
execution: {signal_at: close_t, trade_at: close_t+1, rebalance: monthly, weighting: equal, n_holdings: 20}   # FIXED, not tuned
costs_bps_per_side: {large: 10, mid: 20, small: 30}
grid:                                    # ordinal axes only; each axis equally spaced
  discount_threshold: [0.10, 0.15, 0.20]
  pe_cap: [30, 40, 50]
  ev_ebitda_cap: [25, 35, 45]
  size_filter: [off, on]                 # categorical -> stratify, not smoothed
  # ttm_vs_forward: DROPPED - forward estimates are not available point-in-time from EDGAR/yfinance
n_cells: 54
literature_default: {discount_threshold: 0.15, pe_cap: 40, ev_ebitda_cap: 35, size_filter: on}
split: {train: [2010-01-01, 2018-12-31], test: [2019-01-01, 2026-09-30]}
selection_rule: plateau_v1               # section 5.4, lam = 1.0
test_window_policy: single_look          # if the test window is used to change ANY choice, it is burned; log it
```

Rules: (1) the number of cells is the N for DSR/haircut; (2) fix everything not in the grid (holdings count, rebalance frequency, weighting, exit rule) from the literature or common sense, not by search - each hidden knob is a researcher degree of freedom; (3) cap the grid at roughly 30 cells per strategy where possible (Table 4.A); (4) log every extra run in the ledger.

Specific flags on the team's own plans:
- Trading comps: the doc lists threshold (10/15/20%), P/E cap (30/40/50), EV/EBITDA cap (25/35/45), size filter (with/without), TTM vs forward = 3*3*3*2*2 = 108 cells. Forward multiples require analyst estimates, which EDGAR XBRL and yfinance cannot supply point-in-time, so drop "forward" (54 cells). The number of holdings, rebalance frequency, peer count (4-5), and the 0.5x-2x peer-multiple band are further hidden degrees of freedom - fix them in the file.
- Quality momentum: 12-1 lookback is the published default (Jegadeesh-Titman 1993) - FIX it. Quality filter, RSI 50-70, 200-day MA and top 5-10 are many knobs; tune at most two (e.g., quality cutoff, number of holdings) and run RSI/200DMA as an on/off robustness table, not a tuned parameter. Concentration (5-10 names) means tracking error of perhaps 10-15%, which makes the strategy statistically almost undetectable (Table 5.A); evaluate the SIGNAL on 20-30 names even if the live book is concentrated.
- Magic Formula: ROC = EBIT / (net working capital + net fixed assets) and EY = EBIT / EV need XBRL tag mapping decisions (which tags for NWC, PP&E, debt, cash) - freeze the mapping before looking at returns. Tune at most holdings (20/25/30) and a market-cap floor. Use staggered monthly tranches (1/12 of the book re-ranked each month) so results do not depend on the calendar month of the annual rebalance.

### 5.2 Train / test split (and why the test window is short)

| Window | Dates | Months | Notes |
|---|---|---|---|
| Train (select parameters) | 2010-01 to 2018-12 | 108 | Effective start is later: XBRL phased in by filer size (periods ending on/after 2010-06-15 for other large accelerated filers, 2011-06-15 for all remaining), and TTM needs four quarters. Expect ~84-96 usable months. Mostly a long bull market, with 2011, 2015-16 and Q4 2018 as the drawdowns. |
| Test (confirm once, untouched) | 2019-01 to 2026-09 | 93 | Contains the 2020 crash, 2022 bear market, the 2023-26 narrow mega-cap rally. French factors available only through 2026-08 for regressions. |
| Live | 2026-10-21 onward (official freeze 2026-11-06 per `07_competition_rules.md`, unverified by me) | - | The only truly out-of-sample data. Keep a dated signal/holdings log from now on. |

Power warning: on a 7.75-year test window with 6% tracking error, the minimum annual active return detectable at t = 2 is 2 * 6% / sqrt(7.75) = 4.3% per year (Table 5.A). So the test window can reject a clearly broken strategy and can confirm the DIRECTION and approximate size of an effect, but it cannot "prove" a 2-3% edge. State this in the report.

Table 5.A - minimum detectable annual active return at t = 2 (= 2 * TE / sqrt(Y)):

| Window | TE 4% | TE 6% | TE 8% |
|---|---|---|---|
| Y = 7.75 (test) | 2.9% | 4.3% | 5.7% |
| Y = 9.0 (train) | 2.7% | 4.0% | 5.3% |
| Y = 15.75 (full) | 2.0% | 3.0% | 4.0% |

Single-look discipline: the test window is looked at once per strategy after the parameters are frozen. If the team peeks and then changes anything, record it in the ledger and downgrade the test to "in-sample". Purging is not needed for 1-month holding periods (signals use only past data); for 12-month holds evaluate each window on returns realized inside the window.

After a successful confirmation, the final live parameters may be re-estimated on the full sample ONLY if the plateau choice moves by at most one grid step; otherwise keep the train choice.

Walk-forward alternative (use when the team wants one long out-of-sample series): anchored/expanding window. Re-run the plateau selection each December using data to that month (first selection after 2011-2014 data), trade the chosen parameters for the next calendar year, stitch the yearly out-of-sample pieces into ONE continuous series (about 2015-2026). Evaluate that stitched series with the full tear sheet; its Sharpe is a legitimate out-of-sample estimate of "the procedure", and the DSR trial count is the grid size. Walk-forward efficiency (Pardo; from memory) = annualized OOS return / annualized IS return of the selected configurations; values far below ~0.5 signal overfitting. Also log how often the selected parameters change between years (stability).

### 5.3 Primary metric

Pre-register ONE metric for selection: annualized NET Sharpe on the train window (net of the base cost schedule). Use net IR vs SPY as the secondary/confirmatory metric. Do not select on gross returns, on max return, or on a metric chosen after seeing results.

### 5.4 Plateau selection rule (exact)

Setting: an ordinal grid with k axes (e.g., discount threshold, P/E cap, EV/EBITDA cap), metric f(theta) on the train window for every cell. Categorical choices (size filter on/off) are NOT smoothed: run the rule separately within each category, then pick the category by a pre-registered tie-break (prefer the literature default unless the other category's best plateau score is higher by at least 0.10 Sharpe).

```text
N[theta] = { theta } union { theta +/- one grid step along each ordinal axis }        (up to 2k + 1 cells; von Neumann neighborhood)
Eligible(theta):  (a) at least 2 neighbors exist (not isolated); prefer interior cells;
                  (b) min_{phi in N[theta]} f(phi) > f_floor            (f_floor = benchmark Sharpe on the same window; if the team wants an absolute rule, 0)
                  (c) peak ratio  f(theta) / mean_{phi in N[theta], phi != theta} f(phi)  <=  1.25     (else flag "spike")
Score(theta) = mean_{phi in N[theta]} f(phi)  -  lambda * sd_{phi in N[theta]} f(phi)      lambda = 1.0, sd with ddof = 0
theta* = argmax Score over eligible cells.
Tie-break: if scores are within 0.02 Sharpe, take the cell closest (in grid steps) to the literature default.
Fallback: if no cell is eligible, or the stability check below fails, USE THE LITERATURE DEFAULT. ("When in doubt, don't optimize.")
```

Variants to print for sensitivity (not for selection): lambda = 0 (mean of neighborhood, the brief's first suggestion), median of neighborhood, and maximin (best worst-neighbor). If they pick different cells by more than one step, the surface is flat or noisy and the default wins.

Selection-stability check: B = 500 stationary-bootstrap resamples of the train months (same indices for all cells); rerun the rule on each; report the share of draws choosing theta* and the share choosing a cell within one step of theta*. Require >= 50% within one step; otherwise fall back to the default. Report plateau width = number of connected cells with f >= 0.9 * f(theta*).

The code (`plateau_select`, Appendix A) was tested on a grid with an isolated spike (0.90) next to weaker cells: plain argmax picks the spike, the rule picks a broad region.

### 5.5 Regression table over the grid

Purpose: describe how the metric responds to each parameter, i.e. whether there is a plateau or a knife-edge. Response y(g) = annualized net Sharpe (or net alpha) of grid cell g. Scale each ordinal parameter to [-1, 1] over its pre-registered range, z_j.

```text
y(g) = b0 + sum_j b_j z_j + sum_j c_j z_j^2 + sum_{j<l} d_jl z_j z_l + sum_c kappa_c D_c + e(g)
       (D_c = dummies for categorical parameters, first level dropped)
```

Reading: b_j = change in Sharpe from the grid midpoint to its upper edge (sensitivity); c_j < 0 = interior optimum (a plateau/hill), c_j > 0 = optimum at the edge (extend the grid or distrust it); d_jl = interaction. Report also R^2 and partial R^2 per parameter (drop-one). A flat surface (small |b|, |c|, |d|, low R^2) is GOOD news: results do not depend on the knobs.

Inference caveat: the 54 cells are computed from the same months and stocks, so they are not independent observations and ordinary OLS p-values are meaningless. Get uncertainty by bootstrapping the months: for b = 1..B resample months with the stationary bootstrap (one index vector for all cells), recompute every cell's Sharpe, refit, and report the bootstrap SD of each coefficient. `grid_regression_bootstrap` (Appendix A) does this; in a synthetic test (54 cells, a smooth true effect on only two parameters, cells sharing one common factor) no coefficient was more than about 2 bootstrap SDs from zero, including the parameter with a true effect, and R^2 was only 0.19. Expect similar behavior in real data: individual parameter effects are usually statistically indistinguishable from noise, which supports choosing a plateau/default rather than a "best" cell.

### 5.6 3D interpolated surface (visualization only)

- Pick the TWO most important ordinal parameters from the regression table for the x/y axes; facet by the remaining ones (small multiples: rows = third parameter, columns = size filter). Z = metric.
- Interpolating between discrete grid points is for readability only; there are no strategy results between grid points. Label the plot "interpolated; grid points marked".
- With only 3 levels per axis (9 points) a thin-plate surface through the points is invented structure. Options in order of preference: (1) a heatmap with the numbers printed in each cell; (2) add intermediate levels on the two surface axes (5x5 = 25 cells) as a separately logged visualization run that counts toward N; (3) plot the fitted quadratic regression surface from 5.5 (smooth by construction) with the actual points as markers.
- Method: scipy `RBFInterpolator` (SciPy >= 1.7; default kernel `thin_plate_spline`; with `smoothing=0` it fits the data exactly and a larger `smoothing` pulls it toward a polynomial fit). Rescale both axes to [0, 1] first so the kernel is isotropic; use `smoothing > 0` (start at 0.5); mask points outside the convex hull (extrapolation) - the helper does this with a Delaunay test. `scipy.interpolate.griddata(method="cubic")` is the no-smoothing alternative and returns NaN outside the hull.
- Markers: scatter the actual grid points (black), the selected theta* (star), and the literature default (diamond); draw the plateau region (cells with f >= 0.9 * f(theta*)) as a contour. Same color scale in every facet. Add vertical stems from points to the surface so the reader sees how far the interpolation is from data.
- Also give the 2D heatmap as the primary figure, the 3D as secondary (3D hides values behind the surface).

### 5.7 Evidence ladder for "this strategy goes in the live book" (my recommended heuristics, not literature standards)

1. Direction replicates: net IR vs EW-universe > 0 on train AND test.
2. Plateau: chosen cell passes 5.4 eligibility and stability.
3. Costs: net alpha still > 0 at 25 bps/side (and for momentum with buy/hold spread).
4. Factor view (section 3): the returns are explained by the right factors (or alpha > 0); no large negative alpha.
5. Overfitting diagnostics: PBO < 0.5; DSR at N_hat reported (aim > 0.5, but expect it to be low; report honestly); haircut Sharpe reported.
6. Bias stress (section 6): alpha survives an assumed survivorship drag of at least 150 bps/yr (break-even reported).
7. Subperiods: positive active return in at least 3 of 4 subperiods; worst 12-month active return reported.
Pass fewer than 5 of 7 -> do not claim the strategy "works"; describe it as a research hypothesis held at a modest weight.

---

## 6. Survivorship and look-ahead bias

### 6.1 Why current-index membership inflates returns

- Survivorship: companies that went bankrupt, were delisted, or shrank out of the index are absent; the sample is made of winners. Brown, Goetzmann, Ibbotson & Ross (RFS 5(4):553-580, 1992) show truncating on survival can create apparent predictability; Elton, Gruber & Blake (RFS 9(4):1097-1120, 1996) is the standard estimate for mutual funds (about 0.9%/yr per a secondary source I could not confirm in the primary text; Carhart 1997 finds roughly 0.4-1%/yr depending on horizon); Kothari, Shanken & Sloan (JF 50(1):185-224, 1995) conjecture Compustat selection bias exaggerated early book-to-market results (abstract-level); Shumway (JF 52(1):327-340, 1997) and Shumway & Warther (JF 54(6):2361-2379, 1999) show missing delisting returns are large and negative (-55% assigned to missing performance-related Nasdaq delistings removes the apparent Nasdaq size effect). A 2026 arXiv study of India's Nifty Smallcap 250 (2016-2025) found survivor-only returns 4.94 points per year too high (26.17% vs 21.23%) - a different market, so only indicative.
- Look-ahead through membership: a company is in TODAY's S&P 500 largely because its price rose in the past (inclusion follows success). Using the current list for 2010 selects future winners; it flatters momentum, growth and quality, and it also hides the stocks that were in the index in 2010 and later dropped out.
- Look-ahead through classification: GICS sectors/sub-industries changed (2018 and 2023 restructurings); using today's GICS to form 2010 peer groups is mild look-ahead.
- Not uniform across strategies: value/high-earnings-yield/distressed-tilted books (Magic Formula, comps) hold names with higher delisting probability than the average stock, so the same-universe comparison UNDERSTATES their bias; momentum holds recent winners that are less likely to be about to fail (inference, not from a paper).

### 6.2 How to quantify it with delisted stocks missing

S1. Coverage audit (cheap, do first). For each year, count (a) EDGAR 10-K filers with XBRL in the universe definition and (b) those with a usable yfinance price series. Report coverage ratio = (b)/(a) by year and by size bucket; the missing share is an estimate of the annual attrition you cannot see. Map securities by CIK, not ticker (tickers get reused/changed; do not rely on the SEC's current ticker file for history - from memory that it lists active tickers only). If you reconstruct historical S&P 500 membership from Wikipedia's additions/removals table (walk back from the current list), that fixes the look-ahead part and quantifies how many historical members have no price data.

S2. Same-universe control. Compute EW-universe (equal-weight of the same eligible stocks, same filters, same rebalancing, no signal). Report strategy minus EW-universe: it nets out universe-level survivorship because both share it. Then compare EW-universe with RSP over the overlap (2003-04 to 2026):

```text
universe_bias_hat = CAGR(EW_universe, S&P-500-type universe) - ( CAGR(RSP total return) + 0.20% fee add-back )
```

RSP holds the historical constituents, including names that later left, so a positive gap is a rough estimate of survivorship plus look-ahead in the data (caveats: RSP rebalances quarterly vs the team's monthly; the team's universe composition may differ from the S&P 500). Report the gap for the S&P-500-restricted universe only, where the comparison is meaningful.

S3. Delisting-loss stress test (a calculation, not an estimate of truth):

```text
annual_bias(h) ~ h * ( mean_annual_return_of_a_held_name - R_delist )         h = annual probability a held name would have been lost
R_delist = -0.30 to -0.55 (Shumway; Shumway-Warther), mean_annual_return ~ 0.10
h = 1%/yr -> ~0.65%/yr ; h = 3%/yr -> ~2.0%/yr
```

Show a break-even chart: strategy alpha net of cost as a function of assumed drag (0, 50, 100, 150, 200, 300 bps/yr) and report the drag at which alpha hits zero. Use the S1 coverage gap to choose a plausible h.

S4. Mega-cap replication. Re-run the strategies restricted to the largest ~100-200 names by point-in-time market cap, where delisting for performance reasons within a year is rare (acquisition targets are usually bought out at a premium). If alpha is similar here, survivorship is not driving it. If it collapses, the result lives in the small/illiquid names where the data is least reliable.

S5. Forward test. Anything after the data snapshot is free of survivorship bias. Start a dated, append-only log of signals and hypothetical holdings now.

Disclose in the report: "Prices come from yfinance; delisted securities are largely unavailable, so all results are survivorship-biased; we quantify this with S1-S4."

### 6.3 Point-in-time fundamentals from SEC EDGAR (look-ahead control)

- The companyfacts JSON contains, for each concept and period, the original value and every later re-filing/restatement as separate records, each with a `filed` date and `accn` (accession number); the same period appears again as a comparative in later filings. For a decision on date D use only records with `filed` < D (strictly earlier calendar day; filings after the close are not tradable until the next session), and for each (concept, period end) take the record with the LATEST `filed` among those. That is "as known on D", including restatements that had been published by D.
- Do NOT use the SEC `frames` endpoint for backtests: per SEC's documentation it returns the entity's LAST-filed fact for a period, i.e. restated values that were not known at the time.
- Do not trust `fy` / `fp` to identify a fact's period: in companyfacts they describe the filing's fiscal year/period (comparatives inherit them; practitioner knowledge, verify on your parsed data). Identify periods by `start` and `end` dates (duration facts) or `end` (instant facts), and build quarterly series by differencing year-to-date values (Q4 = FY - 9M YTD).
- TTM flow = sum of the last four discrete quarters (or FY + current YTD - prior-year YTD) using only as-known records. Balance-sheet items = latest as-known instant.
- Fallback when `filed` is missing: period end + 45 days for 10-Q and + 90 days for 10-K (the longest SEC deadlines; large accelerated filers have 60 days for 10-K, accelerated 75, non-accelerated 90; 10-Q 40/40/45 days). Another conservative convention is a flat 3-4 month lag (Fama-French use a 6-month lag for annual accounting data).
- Robustness test: add one extra quarter (about 90 days) to every availability date. If results collapse, the strategy leans on fresh information the market has already priced, or on look-ahead you did not notice; if they hold, good.
- Amended filings (10-K/A) and later restatements are handled automatically by the as-of rule; keep `form` so you can inspect.

### 6.4 Other data traps

- Split basis. yfinance with `auto_adjust=True` gives prices adjusted for later splits and dividends. EDGAR share counts (e.g., dei:EntityCommonStockSharesOutstanding) are as reported at the time and are NOT restated for later splits. Market cap = adjusted price x historical shares is wrong for any stock that later split. Use as-traded prices (reconstruct from the split-adjusted Close and the split table: price_asof_d = Close_d * product of split ratios after d) with as-reported shares, or put both on the same basis. Needed for market-cap filters, peer 0.5x-2x size bands and EV.
- Use total-return (adjusted) prices for returns, as-traded prices for valuation.
- Returns of delisted/halted tickers that DO exist in yfinance may end abruptly with no delisting return; apply the S3 delisting convention to those.
- Execute at t+1 after a signal at t close; no same-bar execution.
- Use the same rf and the same date alignment (month-end) for strategy and factor series.
- Benchmark must be total return (SPY adjusted close).

---

## 7. Short-horizon evaluation for the competition window

### 7.1 Rolling 3- and 6-month windows from the backtest

```text
R_h(t)   = prod_{s=t-h+1..t} (1 + r_s) - 1         (overlapping h-period compounded returns; on DAILY data h = 13 trading days
                                                     [the Oct 21 -> Nov 6 window, if the sibling finding holds], 63 [3 months], 126 [6 months];
                                                     on monthly data h = 3, 6)
E_h(t)   = R_h^strategy(t) - R_h^benchmark(t)       (benchmark = SPY; also RSP, EW-universe)
Report:  mean, median, 5/25/75/95th percentiles, min, max of R_h and E_h;
         P(beat) = (1/m) * #{t : E_h(t) > 0};   P(loss) = P(R_h < 0);   P(beat by > 2 points);   worst E_h
```

Overlapping windows are highly dependent: effective independent windows are about n/h (monthly n = 189 -> 63 windows at h = 3 months, 32 at h = 6; test window n = 93 -> 31 and 16; daily, 15.75 years -> about 305 independent 13-day windows on the full sample and 150 on the test window). The binomial SE of a hit rate near 60% is therefore about 6 points (h = 3 months, full sample) to 12 points (h = 6 months, test window); for 13-day windows near 53% it is about 3 points (full) to 4 points (test). Always give a stationary-bootstrap CI with mean block >= h. Also show the calendar-aligned version (windows starting each Oct 21 and ending each Nov 6, or about Jan 21 / Apr 21 if the window is longer): only ~15 observations - show as a strip plot, do not infer from it. Compute on daily data (use `rolling_compound`) so windows can start on any trading day.

### 7.2 Why a few months of alpha is mostly noise

```text
t  ~  (alpha / sigma_active) * sqrt(T)  =  IR * sqrt(T_years)        (alpha = annual mean active return, sigma_active = annual tracking error)
Expected active return over h months:   IR * TE * (h/12)
SD of active return over h months:      TE * sqrt(h/12)
P(beat benchmark over h months)  ~  Phi( IR * sqrt(h/12) )            (normal approximation)
Months of data for 80% power at 5% (one-sided):  IR needed = (1.645 + 0.842) / sqrt(h/12)
```

Table 7.A - P(beat benchmark) = Phi(IR * sqrt(h/12)) (h in months; the 13-day column uses sqrt(13/252) = 0.227 in place of sqrt(h/12)):

| True IR | 13 trading days (Oct 21 -> Nov 6) | h = 1 month | h = 3 | h = 6 | h = 12 | h = 24 |
|---|---|---|---|---|---|---|
| 0.0 | 50% | 50% | 50% | 50% | 50% | 50% |
| 0.2 | 51.8% | 52% | 54% | 56% | 58% | 61% |
| 0.3 | 52.7% | 53% | 56% | 58% | 62% | 66% |
| 0.5 | 54.5% | 56% | 60% | 64% | 69% | 76% |
| 0.75 | 56.8% | 59% | 65% | 70% | 77% | 86% |

IR needed for 80% power: 13 days -> 10.9, h = 3 -> 5.0, h = 6 -> 3.5, h = 12 -> 2.5. With TE = 6%: SD of the 13-day active return 1.4% (2.3% at TE 10%), of the 3-month 3.0%, of the 6-month 4.2%; expected active return at IR 0.3 is 0.09% over 13 days and 0.45% over 3 months.

After the McLean-Pontiff style haircut (section 1.3) a backtest IR of 0.5 becomes 0.21-0.37, giving P(beat) of only 52-53% over 13 trading days, 54-57% over 3 months and 56-60% over 6 months. Message for the report: the competition-window outcome will be dominated by market direction, factor/sector tilts and stock-specific luck; present the strategies as long-horizon research and show the live result with the confidence band, not as proof. Window-length discrepancy: the brief to me said "a few months"; `07_competition_rules.md` says the portfolio is frozen on 2026-11-06 (13 trading days after Oct 21). Whichever is right, the table covers it; with only 13 days the result says almost nothing about skill and mostly reflects risk exposure and luck.

### 7.3 Combining the three strategies

Diversification arithmetic (Grinold-Kahn): with active returns a_i (IR_i each) and correlation matrix P, the best combination has IR_combo = sqrt( IR' P^-1 IR ). For three strategies with equal IR 0.3 and equal pairwise active-return correlation rho:

| rho | 0 | 0.3 | 0.5 | 0.8 | 0.95 |
|---|---|---|---|---|---|
| IR_combo | 0.52 | 0.41 | 0.37 | 0.32 | 0.305 |

So the benefit is real only if the strategies' ACTIVE returns are not highly correlated. Measure: correlation matrix of monthly returns and, more importantly, of active returns vs SPY (and vs EW-universe), on train and test; also correlation in the worst 10% of benchmark months (tail dependence). Expect high raw correlation (all long-only US equity) and moderate active correlation (momentum vs value are typically negatively related; unverified for these specific implementations).

Equal-risk blend:

```text
Inverse-vol:  w_i = (1/sigma_i) / sum_j (1/sigma_j)          (sigma_i from trailing 36-month monthly vol, lagged one month)
Equal risk contribution (ERC): choose w >= 0, sum w = 1 such that  w_i * (Sigma w)_i  is equal for all i
   convex form (log-barrier): minimize 0.5 * w' Sigma w - b * sum_i ln(w_i), then rescale w to sum to 1   (first-order condition gives w_i (Sigma w)_i = b)
Blend return: r_blend = sum_i w_i r_i   with weights set at each rebalance using information available then.
```

ERC references: Maillard, Roncalli & Teiletche, "The Properties of Equally Weighted Risk Contribution Portfolios", JPM 36(4), 2010 (from memory, unverified). Report the blend's full tear sheet, and the blend vs equal-dollar-weight blend; check the weights are stable (3 strategies, so estimation error is modest, but correlations from 93 months are noisy: use the same weights for train and test as pre-registered).

---

## 8. Recommended tear-sheet layout (one per strategy + one for the blend)

Header (always): strategy name; parameter set and whether it is `plateau_v1` choice, literature default or other; data window; universe definition; N trials in ledger; cost schedule; "SURVIVORSHIP-BIASED: coverage ratio X% (S1)"; point-in-time rule; signal/execution timing; date generated; git commit hash.

Tables
- T1 Performance, net of costs: columns = Strategy, SPY, RSP, EW-universe; rows = CAGR, AnnVol, Sharpe (with 95% bootstrap CI), Sortino, MaxDD (daily) and dates, Calmar, Beta, TE, IR, ActiveCAGR, hit rate (monthly / 3m / 6m), up/down capture, avg holdings, one-way annual turnover, cost drag (bps), gross vs net CAGR. Panels: Full | Train | Test | Last 36m | four calendar subperiods.
- T2 Factor regressions: CAPM, FF3, FF3+MOM, FF5, FF5+MOM, plus active-return version; alpha (ann %), HAC t (L=4; also L=6/12), loadings with t, R^2, n.
- T3 Overfitting diagnostics: N trials (ledger), N_hat, SR (ann), t-stat vs 2.0 / 3.0 / 3.39, PSR(0), SR0, DSR at N and N_hat, Bonferroni haircut Sharpe, PBO (S=16; S=8, 12), OOS probability of loss, degradation slope, MinTRL, SPA p-value.
- T4 Parameter regression table (section 5.5) with bootstrap SDs, plus selected-cell neighborhood table.
- T5 Sensitivity: net alpha/Sharpe at cost 0 / 10 / 25 / 50 bps; availability lag +0 / +1 quarter; holdings count; universe (all / mega-cap only).
- T6 Bias stress: coverage ratio by year, universe_bias_hat vs RSP, break-even drag.
- T7 Short horizon: rolling 13-trading-day / 3m / 6m excess return quantiles, P(beat) with bootstrap CI, Table 7.A style forward expectations.

Charts
- C1 Growth of $1 (log), net, strategy vs SPY, RSP, EW-universe; train/test shading.
- C2 Underwater (drawdown) strategy vs SPY.
- C3 Rolling 12-month excess return vs SPY and rolling 36-month IR.
- C4 Calendar-year returns (bars) strategy vs SPY.
- C5 Rolling 13-day / 3m / 6m excess-return histograms with P(beat) annotated.
- C6 Parameter heatmap (primary) + 3D interpolated surface (secondary) with grid points, selected cell, default, plateau contour.
- C7 PBO logit histogram and IS vs OOS Sharpe scatter (degradation line).
- C8 Factor loadings bar chart with HAC 95% intervals; cumulative alpha.
- C9 Coverage ratio and bias break-even curve.
- C10 Correlation heatmap of the three strategies' returns and active returns; blend vs components.

Footer: assumptions, data sources with retrieval dates, known limitations (survivorship, short test window, XBRL tag mapping), and the McLean-Pontiff expected-decay statement.

---

## 9. Recommended module API

`metrics.py` (numpy; pandas Series accepted and converted):

```python
cagr(r, ppy) -> float
ann_vol(r, ppy) -> float
sharpe(r, rf=0.0, ppy=12) -> float
sortino(r, rf=0.0, ppy=12) -> float
drawdown_series(r) -> np.ndarray
max_drawdown(r) -> float
calmar(r, ppy) -> float
beta(r, b, rf=0.0) -> float
tracking_error(r, b, ppy) -> float
information_ratio(r, b, ppy) -> float
active_cagr(r, b, ppy) -> float                       # (1+cagr_p)/(1+cagr_b) - 1
hit_rate(r, b) -> float
capture_ratios(r, b) -> (up, down)
drifted_weights(w_prev_target, asset_returns) -> np.ndarray
turnover_oneway(w_target, w_pre_trade) -> float
apply_costs(gross_r, dw, cost_bps_per_side) -> np.ndarray   # dw: (T x n_assets) trades; cost = sum c_i |dw_i|
rolling_compound(r, h) -> np.ndarray
horizon_report(r, b, h, mean_block=None, B=2000, seed=0) -> dict   # quantiles, P(beat), P(loss), bootstrap CIs
summary_table(r, b, rf, ppy, windows: dict) -> pd.DataFrame   # assembles T1 from the functions above (NOT in Appendix A)
```

`stats.py`:

```python
newey_west_lags(T) -> int
ols_hac(y, X, lags=None, small_sample=True) -> dict(beta, se, t, p, r2, lags, n)
factor_regression(excess_r, factors_df, model="ff5mom", lags=4) -> dict     # alpha_ann, t_alpha, loadings, r2
sharpe_se_iid(sr_per, T) -> float ; sharpe_t(sr_ann, years) -> float
psr(sr_hat, sr_star, T, skew, kurt_raw) -> float
expected_max_sr(var_sr, N) -> float
effective_trials(M_returns) -> float                 # rho_bar + (1 - rho_bar) * M   (unverified formula; report both)
dsr(r_selected, trial_sharpes_per, N=None) -> (dsr, sr0)
min_track_record_len(sr_hat, sr_star, skew, kurt_raw, conf=0.95) -> float
adjust_pvalues(p, method="holm") -> np.ndarray       # bonferroni | holm | bh | bhy
haircut_sharpe_bonferroni(sr_ann, years, n_tests) -> (sr_adj, haircut)
stationary_bootstrap_idx(n, mean_block, rng) -> np.ndarray
bootstrap_ci(stat_fn, data, mean_block, B=5000, alpha=0.05, seed=0) -> (ci, draws)
optimal_block(x) -> float                            # thin wrapper on arch.bootstrap.optimal_block_length (b_sb), floor at 3 (NOT in Appendix A)
cscv_pbo(M, S=16, selector=None) -> dict(pbo, logits, sr_is, sr_oos, prob_loss, degradation_slope, n_combos)
spa_test(bench_losses, model_losses, block_size, reps=1000) -> dict      # thin wrapper on arch.bootstrap.SPA (NOT in Appendix A)
plateau_select(f, lam=1.0, min_nbrs=2, require_pos=True) -> (index, score, peak_ratio)
grid_design(levels, cont, cat=()) -> (X, names)
grid_regression_bootstrap(Mret, levels, cont, cat=(), B=500, mean_block=6) -> dict
surface_grid(x, y, z, n=50, smoothing=0.5) -> (gx, gy, gz)
erc_weights(cov) -> np.ndarray
```

Dependencies: numpy, scipy, pandas, statsmodels (optional cross-check), arch (optimal_block_length, SPA), matplotlib. The existing top-level repo scripts are stdlib-only; keep the new package separate (`quant/`).

---

## 10. Minimum viable plan before Wed 2026-10-21 (3 days)

Must do:
1. Freeze pre-registration files (section 5.1) and the cost schedule; start the trial ledger.
2. Build the tear-sheet table T1 (net of costs, gross vs net, vs SPY/RSP/EW-universe) for each strategy on train, test and full, using `metrics.py`.
3. Run the plateau selection on the train window for each strategy's small grid; confirm once on test; write down what changed vs the default.
4. FF5+MOM regression (T2) with HAC L=4 for each strategy.
5. DSR/haircut using the ledger N, and PBO with S=16 on the train grid.
6. Coverage audit (S1) and the same-universe control (S2); write the survivorship disclosure.
7. Rolling 13-day / 3m / 6m P(beat) tables (T7) and the honest expectation statement from section 7.2.

If time remains: SPA, mega-cap replication (S4), +1 quarter availability lag, bootstrap CIs for everything, 3D surfaces, walk-forward, blend tear sheet.

---

## 11. Sources and verification notes

Primary / near-primary (read in this session):
- McLean & Pontiff, JF 71(1):5-32 (2016), DOI 10.1111/jofi.12365; Wiley https://onlinelibrary.wiley.com/doi/abs/10.1111/jofi.12365 (HTTP 403 to my fetcher); text read from authors' forthcoming-version PDF https://counterpointfunds.com/wp-content/uploads/2017/07/PredictabilityMcleanPontiff.pdf ; Crossref https://api.crossref.org/works/10.1111/jofi.12365 ; AFA issue page https://afajof.org/issue/volume-71-issue-1/ ; secondary summaries https://www.cxoadvisory.com/big-ideas/effects-of-market-adaptation and https://rpc.cfainstitute.org/research/cfa-digest/2016/06/does-academic-research-destroy-stock-return-predictability-digest-summary
- JSTOR link given by team (unverified): https://www.jstor.org/stable/43869094
- Bailey & Lopez de Prado, Deflated Sharpe Ratio, JPM 40(5):94-107 (2014): https://papers.ssrn.com/abstract=2460551 ; PDF text read from https://www.davidhbailey.com/dhbpapers/deflated-sharpe.pdf
- Bailey, Borwein, Lopez de Prado & Zhu, Probability of Backtest Overfitting, J. Computational Finance 20(4) (2017): https://papers.ssrn.com/abstract=2326253 ; PDF text read from https://escholarship.org/content/qt4w1110bb/qt4w1110bb.pdf
- Harvey, Liu & Zhu, RFS 29(1):5-68 (2016), NBER WP 20592: https://www.nber.org/papers/w20592.pdf (read) ; https://papers.ssrn.com/abstract=2513152
- Harvey & Liu, "Backtesting", JPM 42(1):13-28 (2015): https://people.duke.edu/~charvey/Research/Published_Papers/P120_Backtesting.PDF (abstract-level via search)
- Frazzini, Israel & Moskowitz, "Trading Costs of Asset Pricing Anomalies" (Dec 2012 draft, read): https://conference.nber.org/conf_papers/f68262/f68262.pdf ; later version "Trading Costs": https://papers.ssrn.com/abstract=3229719 (403 to my fetcher; abstract via search)
- Novy-Marx & Velikov, RFS 29(1):104-147 (2016): https://www.nber.org/papers/w20721 (via search summaries)
- Lo, "The Statistics of Sharpe Ratios", FAJ 58(4):36-52 (2002): https://traders.studentorg.berkeley.edu/papers/The-Statistics-of-Sharpe-Ratios.pdf (read)
- Fama & French, "A Five-Factor Asset Pricing Model", JFE 116(1):1-22 (2015), DOI 10.1016/j.jfineco.2014.10.010: https://papers.ssrn.com/sol3/papers.cfm?abstract_id=2287202
- Ken French data library: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/data_library.html ; 5 factors: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_5_factors_2x3.html ; 3 factors: https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/Data_Library/f-f_factors.html
- AQR datasets: https://www.aqr.com/Insights/Datasets
- Carhart, JF 52(1):57-82 (1997), DOI 10.1111/j.1540-6261.1997.tb03808.x
- Newey & West, Econometrica 55(3):703-708 (1987), DOI 10.2307/1913610 ; Newey & West, Review of Economic Studies 61(4):631-653 (1994), https://ideas.repec.org/a/oup/restud/v61y1994i4p631-653..html
- Politis & Romano, "The Stationary Bootstrap", JASA 89(428):1303-1313 (1994), DOI 10.1080/01621459.1994.10476870 ; Patton, Politis & White, Econometric Reviews 28(4):372-375 (2009): https://public.econ.duke.edu/~ap172/Patton_Politis_White_2009.pdf
- White, "A Reality Check for Data Snooping", Econometrica 68(5):1097-1126 (2000), DOI 10.1111/1468-0262.00152 ; Hansen, JBES 23(4):365-380 (2005)
- arch docs: https://arch.readthedocs.io/en/latest/bootstrap/generated/arch.bootstrap.optimal_block_length.html , https://arch.readthedocs.io/en/latest/multiple-comparison/generated/arch.bootstrap.SPA.html
- statsmodels HAC docs: https://www.statsmodels.org/stable/generated/statsmodels.regression.linear_model.RegressionResults.get_robustcov_results.html
- SciPy RBFInterpolator: https://docs.scipy.org/doc/scipy/reference/generated/scipy.interpolate.RBFInterpolator.html
- Survivorship: Brown, Goetzmann, Ibbotson & Ross, RFS 5(4):553-580 (1992) https://ideas.repec.org/a/oup/rfinst/v5y1992i4p553-80.html ; Elton, Gruber & Blake, RFS 9(4):1097-1120 (1996) https://ideas.repec.org/a/oup/rfinst/v9y1996i4p1097-1120.html (0.9%/yr per secondary source); Carhart (1997) mutual-fund survivorship https://www.evidenceinvestor.com/wp-content/uploads/2016/08/Mutual-Fund-Survivorship-Mark-M.-Carhart-May-1997.pdf ; Kothari, Shanken & Sloan, JF 50(1):185-224 (1995) https://ideas.repec.org/a/bla/jfinan/v50y1995i1p185-224.html ; Shumway, JF 52(1):327-340 (1997) https://ideas.repec.org/a/bla/jfinan/v52y1997i1p327-40.html ; Shumway & Warther, JF 54(6):2361-2379 (1999) https://ideas.repec.org/a/bla/jfinan/v54y1999i6p2361-2379.html ; Nifty Smallcap 250 study https://arxiv.org/pdf/2603.19380
- SEC: filing deadlines https://www.sec.gov/fast-answers/answersform10qhtm.html and Release 33-8644 https://www.sec.gov/files/rules/final/33-8644.pdf ; XBRL APIs https://www.sec.gov/edgar/sec-api-documentation ; interactive-data phase-in guidance https://www.sec.gov/rules-regulations/staff-guidance/compliance-disclosure-interpretations/interactive-data-cdi
- RSP: https://invesco.com/us/en/etf/sp-500-equal-weight-rsp.html (0.20% expense ratio, quarterly rebalance per search summaries; inception 2003-04-24 per TradingView)

Not verified in any primary source (treat as author's knowledge): Sortino and Calmar conventions; Pardo walk-forward efficiency; Maillard-Roncalli-Teiletche ERC details; Kiefer-Vogelsang; Stock-Watson lag; N_eff formula; momentum factor file start date; companyfacts field names; ticker-file behavior.

---

## Appendix A - Tested reference implementation (numpy + scipy)

Executed on synthetic data in the research sandbox. Tests run and results:
- DSR example from the paper: N=100 -> 0.9004, N=46 -> 0.9505, Normal N=88 -> 0.9505 (paper: 0.90 / 0.95 / 0.95).
- `ols_hac` standard errors equal a brute-force double-loop Newey-West implementation; with lags=0 they equal HC0 times T/(T-k).
- `cscv_pbo`: pure noise (T=192, N=54, S=16, 12,870 combinations) PBO = 0.43; with one truly skilled trial PBO = 0.02.
- `adjust_pvalues` Bonferroni/Holm/BH match hand calculations on [0.001, 0.01, 0.02, 0.2].
- `plateau_select` rejects an isolated spike that argmax would choose.
- `grid_regression_bootstrap` and `surface_grid` run end to end; the Sharpe bootstrap SD matched the iid formula on iid data.
- `apply_costs` (0.2 traded notional at 10 bps = 2 bps), `factor_regression`, `capture_ratios`, `active_cagr`, `horizon_report` run end to end; `erc_weights` gives exactly equal risk contributions (33.3% each) on a 3-asset example.
Not tested: plotting, `arch` wrappers (`optimal_block`, `spa_test`), `summary_table`, a statsmodels cross-check, real data.

```python
"""Reference implementations for the spec (tested in test_ref.py). numpy + scipy only."""
import itertools
import numpy as np
from scipy.stats import norm, rankdata, skew as _skew, kurtosis as _kurt

EULER_GAMMA = 0.5772156649015329


def _a(x):
    return np.asarray(x, dtype=float)


# ---------------- metrics ----------------
def cagr(r, ppy):
    r = _a(r)
    return float(np.prod(1.0 + r) ** (ppy / len(r)) - 1.0)


def ann_vol(r, ppy):
    return float(np.std(_a(r), ddof=1) * np.sqrt(ppy))


def sharpe(r, rf=0.0, ppy=12):
    x = _a(r) - _a(rf)
    return float(x.mean() / x.std(ddof=1) * np.sqrt(ppy))


def sortino(r, rf=0.0, ppy=12):
    x = _a(r) - _a(rf)
    dd = np.sqrt(np.mean(np.minimum(x, 0.0) ** 2))
    return float(x.mean() / dd * np.sqrt(ppy))


def drawdown_series(r):
    w = np.r_[1.0, np.cumprod(1.0 + _a(r))]
    peak = np.maximum.accumulate(w)
    return (w / peak - 1.0)[1:]


def max_drawdown(r):
    return float(drawdown_series(r).min())


def calmar(r, ppy):
    mdd = max_drawdown(r)
    return float(cagr(r, ppy) / abs(mdd)) if mdd < 0 else float("nan")


def tracking_error(r, b, ppy):
    return float((_a(r) - _a(b)).std(ddof=1) * np.sqrt(ppy))


def information_ratio(r, b, ppy):
    a = _a(r) - _a(b)
    return float(a.mean() / a.std(ddof=1) * np.sqrt(ppy))


def beta(r, b, rf=0.0):
    x, m = _a(r) - _a(rf), _a(b) - _a(rf)
    return float(np.cov(x, m, ddof=1)[0, 1] / np.var(m, ddof=1))


def hit_rate(r, b):
    return float(np.mean(_a(r) > _a(b)))


def drifted_weights(w_prev_target, asset_returns):
    g = 1.0 + _a(asset_returns)
    v = _a(w_prev_target) * g
    return v / v.sum()


def turnover_oneway(w_target, w_pre_trade):
    return float(0.5 * np.abs(_a(w_target) - _a(w_pre_trade)).sum())


def rolling_compound(r, h):
    c = np.r_[0.0, np.cumsum(np.log1p(_a(r)))]
    return np.expm1(c[h:] - c[:-h])


# ---------------- sharpe inference ----------------
def sharpe_se_iid(sr_per, T):
    return float(np.sqrt((1.0 + 0.5 * sr_per ** 2) / T))


def psr(sr_hat, sr_star, T, skew_, kurt_raw):
    """All Sharpe ratios per-period (non-annualised). kurt_raw: normal = 3."""
    denom = np.sqrt(1.0 - skew_ * sr_hat + (kurt_raw - 1.0) / 4.0 * sr_hat ** 2)
    return float(norm.cdf((sr_hat - sr_star) * np.sqrt(T - 1.0) / denom))


def expected_max_sr(var_sr, N):
    if N <= 1:
        return 0.0
    return float(np.sqrt(var_sr) * ((1 - EULER_GAMMA) * norm.ppf(1 - 1.0 / N)
                                    + EULER_GAMMA * norm.ppf(1 - 1.0 / (N * np.e))))


def dsr(r_selected, trial_sharpes_per, N=None):
    r = _a(r_selected)
    T = len(r)
    sr_hat = r.mean() / r.std(ddof=1)
    ts = _a(trial_sharpes_per)
    N = len(ts) if N is None else N
    sr0 = expected_max_sr(np.var(ts, ddof=1), N)
    return psr(sr_hat, sr0, T, float(_skew(r)), float(_kurt(r, fisher=False))), sr0


def min_track_record_len(sr_hat, sr_star, skew_, kurt_raw, conf=0.95):
    z = norm.ppf(conf)
    return 1.0 + (1.0 - skew_ * sr_hat + (kurt_raw - 1.0) / 4.0 * sr_hat ** 2) * (z / (sr_hat - sr_star)) ** 2


def adjust_pvalues(p, method="holm"):
    p = _a(p)
    m = len(p)
    order = np.argsort(p)
    ps = p[order]
    if method == "bonferroni":
        adj = np.minimum(ps * m, 1.0)
    elif method == "holm":
        adj = np.maximum.accumulate(np.minimum((m - np.arange(m)) * ps, 1.0))
    elif method in ("bh", "bhy"):
        c = 1.0 if method == "bh" else float(np.sum(1.0 / np.arange(1, m + 1)))
        adj = np.minimum.accumulate((ps * m * c / np.arange(1, m + 1))[::-1])[::-1]
        adj = np.minimum(adj, 1.0)
    else:
        raise ValueError(method)
    out = np.empty(m)
    out[order] = adj
    return out


def haircut_sharpe_bonferroni(sr_ann, years, n_tests):
    t = sr_ann * np.sqrt(years)
    p = 2 * norm.sf(t)
    p_adj = min(n_tests * p, 1.0)
    t_adj = norm.isf(p_adj / 2)
    sr_adj = t_adj / np.sqrt(years)
    return float(sr_adj), float(1 - sr_adj / sr_ann)


# ---------------- HAC regression ----------------
def newey_west_lags(T):
    return int(np.floor(4.0 * (T / 100.0) ** (2.0 / 9.0)))


def ols_hac(y, X, lags=None, small_sample=True):
    y, X = _a(y), _a(X)
    T, k = X.shape
    XtX_inv = np.linalg.inv(X.T @ X)
    b = XtX_inv @ X.T @ y
    e = y - X @ b
    L = newey_west_lags(T) if lags is None else int(lags)
    Xe = X * e[:, None]
    S = Xe.T @ Xe
    for l in range(1, L + 1):
        G = Xe[l:].T @ Xe[:-l]
        S += (1.0 - l / (L + 1.0)) * (G + G.T)
    V = XtX_inv @ S @ XtX_inv
    if small_sample:
        V = V * T / (T - k)
    se = np.sqrt(np.diag(V))
    t = b / se
    r2 = 1.0 - (e @ e) / (((y - y.mean()) ** 2).sum())
    return dict(beta=b, se=se, t=t, p=2 * norm.sf(np.abs(t)), r2=r2, lags=L, n=T)


# ---------------- bootstrap ----------------
def stationary_bootstrap_idx(n, mean_block, rng):
    p = 1.0 / mean_block
    new = rng.random(n) < p
    starts = rng.integers(n, size=n)
    idx = np.empty(n, dtype=np.int64)
    idx[0] = starts[0]
    for t in range(1, n):
        idx[t] = starts[t] if new[t] else (idx[t - 1] + 1) % n
    return idx


def bootstrap_ci(stat_fn, data, mean_block, B=5000, alpha=0.05, seed=0):
    data = _a(data)
    rng = np.random.default_rng(seed)
    n = len(data)
    draws = np.array([stat_fn(data[stationary_bootstrap_idx(n, mean_block, rng)]) for _ in range(B)])
    return np.quantile(draws, [alpha / 2, 1 - alpha / 2]), draws


# ---------------- CSCV / PBO ----------------
def cscv_pbo(M, S=16, selector=None, seed=0):
    """M: T x N matrix of per-period returns for N trials. Returns dict.
    selector(R_is) -> index of the 'optimal' trial; default argmax (the paper's choice)."""
    M = _a(M)
    T, N = M.shape
    n_per = T // S
    M = M[T - n_per * S:]                       # drop earliest remainder so blocks are equal
    blocks = [M[i * n_per:(i + 1) * n_per] for i in range(S)]
    sums = np.array([b.sum(0) for b in blocks])
    sqs = np.array([(b ** 2).sum(0) for b in blocks])

    def sr_from(idx):
        n = n_per * len(idx)
        s1, s2 = sums[list(idx)].sum(0), sqs[list(idx)].sum(0)
        mu = s1 / n
        var = (s2 - n * mu ** 2) / (n - 1)
        return mu / np.sqrt(var)

    if selector is None:
        selector = lambda R: int(np.argmax(R))
    logits, sr_is, sr_oos = [], [], []
    allb = set(range(S))
    for c in itertools.combinations(range(S), S // 2):
        comp = sorted(allb - set(c))
        R_is, R_oos = sr_from(c), sr_from(comp)
        ns = selector(R_is)
        w = rankdata(R_oos)[ns] / (N + 1.0)
        logits.append(np.log(w / (1.0 - w)))
        sr_is.append(R_is[ns])
        sr_oos.append(R_oos[ns])
    logits, sr_is, sr_oos = map(np.array, (logits, sr_is, sr_oos))
    slope = np.polyfit(sr_is, sr_oos, 1)[0] if sr_is.std() > 0 else float("nan")
    return dict(pbo=float(np.mean(logits <= 0)), logits=logits, sr_is=sr_is, sr_oos=sr_oos,
                prob_loss=float(np.mean(sr_oos < 0)), degradation_slope=float(slope),
                n_combos=len(logits))


# ---------------- plateau selection ----------------
def plateau_select(f, lam=1.0, min_nbrs=2, require_pos=True):
    """f: ndarray over an ordinal grid (NaN = infeasible). Neighbourhood = self + axis-wise +/-1 cells.
    Returns (best_index, score_array, peak_ratio_array)."""
    f = _a(f)
    score = np.full(f.shape, np.nan)
    peak = np.full(f.shape, np.nan)
    for ix in np.ndindex(f.shape):
        if np.isnan(f[ix]):
            continue
        vals = [f[ix]]
        for ax in range(f.ndim):
            for d in (-1, 1):
                j = list(ix)
                j[ax] += d
                if 0 <= j[ax] < f.shape[ax] and not np.isnan(f[tuple(j)]):
                    vals.append(f[tuple(j)])
        if len(vals) - 1 < min_nbrs:
            continue
        vals = np.array(vals)
        if require_pos and vals.min() <= 0:
            continue
        score[ix] = vals.mean() - lam * vals.std(ddof=0)
        peak[ix] = f[ix] / vals[1:].mean() if vals[1:].mean() != 0 else np.nan
    if np.all(np.isnan(score)):
        return None, score, peak
    return np.unravel_index(np.nanargmax(score), f.shape), score, peak


# ---------------- grid regression + surface ----------------
def grid_design(levels, cont, cat=()):
    """levels: dict name -> 1D array of grid values per cell (len = n_cells).
    cont: names of ordinal/continuous params -> scaled to [-1,1]; adds z, z^2 and pairwise z*z.
    cat: names of categorical params -> dummies (first level dropped). Returns X (with const), colnames."""
    cols, names = [np.ones(len(next(iter(levels.values()))))], ["const"]
    Z = {}
    for c in cont:
        v = _a(levels[c]); lo, hi = v.min(), v.max()
        Z[c] = (2 * (v - lo) / (hi - lo) - 1) if hi > lo else np.zeros_like(v)
        cols.append(Z[c]); names.append(c)
    for c in cont:
        cols.append(Z[c] ** 2); names.append(c + "^2")
    for i, a in enumerate(cont):
        for b in cont[i + 1:]:
            cols.append(Z[a] * Z[b]); names.append(a + "*" + b)
    for c in cat:
        v = np.asarray(levels[c]); u = sorted(set(v.tolist()))
        for lev in u[1:]:
            cols.append((v == lev).astype(float)); names.append("%s=%s" % (c, lev))
    return np.column_stack(cols), names


def grid_regression_bootstrap(Mret, levels, cont, cat=(), B=500, mean_block=6, seed=0, ppy=12):
    """Mret: T x n_cells monthly returns per grid cell. Response = annualised Sharpe of each cell.
    Same resampled months for every cell (keeps cross-cell dependence). Returns coef, boot_sd, r2."""
    Mret = _a(Mret); T = Mret.shape[0]
    X, names = grid_design(levels, cont, cat)
    pinv = np.linalg.pinv(X)
    def cell_sr(M):
        return M.mean(0) / M.std(0, ddof=1) * np.sqrt(ppy)
    y0 = cell_sr(Mret); coef = pinv @ y0
    r2 = 1 - ((y0 - X @ coef) ** 2).sum() / ((y0 - y0.mean()) ** 2).sum()
    rng = np.random.default_rng(seed); draws = []
    for _ in range(B):
        idx = stationary_bootstrap_idx(T, mean_block, rng)
        draws.append(pinv @ cell_sr(Mret[idx]))
    return dict(names=names, coef=coef, boot_sd=np.array(draws).std(0), r2=float(r2))


def surface_grid(x, y, z, n=50, smoothing=0.5, kernel="thin_plate_spline"):
    """Smooth surface over two continuous parameters (visualisation only). Axes rescaled to [0,1] so the
    kernel is isotropic; smoothing>0 stops it interpolating noise exactly; points outside the convex hull masked."""
    from scipy.interpolate import RBFInterpolator
    from scipy.spatial import Delaunay
    x, y, z = _a(x), _a(y), _a(z)
    u = np.c_[(x - x.min()) / np.ptp(x), (y - y.min()) / np.ptp(y)]
    gx, gy = np.meshgrid(np.linspace(0, 1, n), np.linspace(0, 1, n))
    P = np.c_[gx.ravel(), gy.ravel()]
    zz = RBFInterpolator(u, z, kernel=kernel, smoothing=smoothing)(P)
    inside = Delaunay(u).find_simplex(P) >= 0
    zz[~inside] = np.nan
    return (x.min() + gx * np.ptp(x), y.min() + gy * np.ptp(y), zz.reshape(n, n))


# ---------------- extra helpers ----------------
def active_cagr(r, b, ppy):
    return (1.0 + cagr(r, ppy)) / (1.0 + cagr(b, ppy)) - 1.0


def capture_ratios(r, b):
    r, b = _a(r), _a(b)
    up = r[b > 0].mean() / b[b > 0].mean()
    dn = r[b < 0].mean() / b[b < 0].mean()
    return float(up), float(dn)


def apply_costs(gross_r, dw, cost_bps_per_side):
    """gross_r: (T,) ; dw: (T, n_assets) signed trades as fractions of NAV ; cost_bps_per_side: scalar or (n_assets,)."""
    c = _a(cost_bps_per_side) / 1e4
    return _a(gross_r) - (np.abs(_a(dw)) * c).sum(axis=1)


def sharpe_t(sr_ann, years):
    return float(sr_ann * np.sqrt(years))


def effective_trials(M):
    """rho_bar + (1 - rho_bar) * N  (Bailey-Lopez de Prado DSR, Appendix 3 -- from memory, unverified)."""
    C = np.corrcoef(_a(M).T)
    n = C.shape[0]
    rho = (C.sum() - n) / (n * (n - 1))
    return float(rho + (1.0 - rho) * n)


def factor_regression(excess_r, F, lags=None, periods=12):
    """excess_r: (T,) strategy minus rf ; F: (T,k) factor returns in DECIMALS. Returns alpha (annualised) + loadings."""
    X = np.column_stack([np.ones(len(excess_r)), _a(F)])
    o = ols_hac(excess_r, X, lags=lags)
    return dict(alpha_ann=float(periods * o["beta"][0]), alpha_ann_se=float(periods * o["se"][0]),
                t_alpha=float(o["t"][0]), loadings=o["beta"][1:], t_loadings=o["t"][1:],
                r2=float(o["r2"]), lags=o["lags"], n=o["n"])


def horizon_report(r, b, h, mean_block=None, B=2000, seed=0):
    """Overlapping h-period compounded returns; P(beat), P(loss), quantiles, bootstrap CI for P(beat).
    mean_block defaults to max(h, 3). Resamples the underlying periodic returns (stationary bootstrap)."""
    r, b = _a(r), _a(b)
    mean_block = mean_block or max(h, 3)
    def stats(rr, bb):
        Rp, Rb = rolling_compound(rr, h), rolling_compound(bb, h)
        E = Rp - Rb
        return Rp, Rb, E
    Rp, Rb, E = stats(r, b)
    rng = np.random.default_rng(seed)
    n = len(r); pb = []
    for _ in range(B):
        idx = stationary_bootstrap_idx(n, mean_block, rng)
        pb.append(np.mean(stats(r[idx], b[idx])[2] > 0))
    return dict(n_windows=len(E), p_beat=float(np.mean(E > 0)), p_beat_ci=tuple(np.quantile(pb, [0.025, 0.975])),
                p_loss=float(np.mean(Rp < 0)), excess_quantiles=dict(zip([5, 25, 50, 75, 95], np.percentile(E, [5, 25, 50, 75, 95]))),
                worst_excess=float(E.min()), best_excess=float(E.max()), mean_excess=float(E.mean()))
```

Additional snippet (equal-risk-contribution weights; not executed against real data):

```python
import numpy as np
from scipy.optimize import minimize

def erc_weights(cov):
    """Equal risk contribution via the convex log-barrier form: min 0.5 w'Sw - b*sum(ln w); then rescale to sum 1."""
    cov = np.asarray(cov, float); n = len(cov); b = 1.0 / n
    f = lambda w: 0.5 * w @ cov @ w - b * np.log(w).sum()
    g = lambda w: cov @ w - b / w
    res = minimize(f, np.full(n, 1.0 / n), jac=g, bounds=[(1e-9, None)] * n, method="L-BFGS-B")
    w = res.x
    return w / w.sum()
```
