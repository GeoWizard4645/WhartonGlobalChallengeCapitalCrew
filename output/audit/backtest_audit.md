# Backtest-integrity audit (engine, timing, costs, metrics, point-in-time data)

Scope: `quant/backtest/engine.py`, `metrics.py`, `stats.py` (CAPM path), `quant/data/context.py`, the three strategies
(`quality_momentum`, `magic_formula`, `trading_comps`) and their signal modules. No repo code was modified.
Strategy-level numbers below are TRAIN ONLY (signals 2012-01-31 .. 2018-12-31, returns cut at 2018-12-31, DEFAULT params,
10 bps one-way). Nothing from 2019+ was evaluated for performance (only data-coverage counts and
price-existence checks touched later dates). Auditor scripts: scratchpad `audit_bt/` (s01..s30, `mysim.py`, `mysim_opts.py`).

## Verdict table

| # | Check | Result | Evidence (short) |
|---|-------|--------|------------------|
| 1 | Independent engine re-implementation | PASS | Own dollar-ledger simulator (no engine import) reproduces daily gross/net/cost/turnover of `engine.run` (QM, TC) and `run_sleeves(12)` (MF) to < 5e-13 over 1,740 days, 83 rebalances. Cum. net: QM +111.26%, TC +35.44%, MF +114.38% (identical). Extra: stop-loss 10%/15%, vol-target 20%, N=5/20, no-filter variants (5 QM param sets): max diff 5e-16. |
| 2 | Look-ahead perturbation | PASS | 3 dates (2014-06-30, 2016-09-30, 2018-03-29) x 3 strategies: with prices after t replaced by random walks (25% of names vanish), all snapshots with filed >= t dropped and membership snapshots > t dropped, target weights identical (max abs dw = 0.0, same names). Reverse sanity: corrupting close(t) changes every portfolio (overlap 6-8/10 QM, 12/20..8/10 TC, 20-24/30 MF); corrupting history before t changes QM completely (0/10 overlap), dropping fundamentals empties every book. (MF unchanged by past prices, TC changed once: they only use close(t) and a beta gate.) Engine causality: replacing returns after 2015-12-31 changes nothing on or before that date (diff 0.0). |
| 3 | Signal/execution alignment | PASS | +50% jump on t+1 is NOT captured with exec_lag=1 (cum 0.0000), captured with exec_lag=0 (0.5000); a +30% on t+2 is captured. Real QM book: gross return on t+1 equals old-book return to 1e-8, new weights first appear at end of t+1. `month_ends` = last trading day per month (Good Friday 2013-03-28/2018-03-29, Memorial Day 2010-05-28 handled); trading days/yr 2012-2018 = 250/252/252/252/252/251/251 = NYSE. Momentum = `adjclose[t-21]/adjclose[t-252]-1`, hand-calc for AMAT/AYI/DHR equals library exactly; RSI = Wilder (own loop: max diff 0.0e0 over 2012-2018 for 3 names; Cutler/SMA RSI would differ by ~0.6 pt). |
| 4 | Delisting / survivorship in engine | PASS mechanically, FAIL structurally | Synthetic test: held name stops trading -> sold at last print into cash, no cost, no turnover, rf on the cash, `delist` trade logged (matches my sim to 3e-16). BUT in the DEFAULT train backtests this never happens (0 `delist` trades, 0 `dropped`), because the price panel contains no delisted names (see F1). |
| 5 | Costs / turnover | PASS | sum(gross-net) = c * sum(weight_traded of rebalance trades) to 1e-17. One-way turnover/mo: QM 64.1%, TC 32.1%, MF 5.7% (static estimate from target changes 61.6% / 30.3% / 4.1%). Cost drag/yr: QM 1.48%, TC 0.76%, MF 0.12%. Cost of 12.3 bp/rebalance at 64% turnover = 2 x 0.64 x 10 bp. Engine's documented simplification (cost deducted from the post-return NAV, not fed back to positions) vs true NAV accounting: <= 4.7e-5 on a trade day, -0.024 pp / -0.003 pp / -0.002 pp cumulative (QM/TC/MF). |
| 6 | Metrics | PASS | QM DEFAULT train, daily: CAGR 11.4403%, vol 18.6434%, Sharpe(excess of rf) 0.648135, MaxDD -32.9826% - library = own to 6 dp. Monthly: CAGR 11.4195%, vol 16.2956%, Sharpe 0.715927 (equal). Monthly series from `BacktestResult.monthly()` equals own calendar-month compounding (83 months). CAPM vs Ken French Mkt-RF: alpha -0.0823%/mo (-0.99%/yr), HAC(L=4) t = -0.209, beta 1.0823 - `stats.factor_regression` = statsmodels HAC = manual OLS. Beta vs SPY 1.0850 equal. KF Mkt-RF vs SPY excess corr 0.993. Note: daily-based Sharpe (0.648) is 10% lower than monthly-based (0.716); grids use monthly. |
| 7 | Market-cap / price filter timing | PASS | `market_cap` uses `close.loc[t]` and snapshots with `filed < t` (max filed used for 2016-09-30 = 2016-09-29; 15 snapshots filed ON t excluded). Spot checks: AAPL as-traded price 561.02 (2013-12-31), 92.93 (2014-06-30), 425.04 (2020-07-31, pre-split); AAPL mcap 2016-09-30 = $609B. Snapshot PIT spot checks vs raw SEC facts: Assets 397/397 equal to the value known at filing date; 10-K revenue_lfy: 105/105 restated-later cases equal the as-known value (0 leaks). |
| 8 | Other | see findings F1-F8 | |

## Findings (ordered by impact on reported numbers)

### F1 (HIGH, structural) Survivorship: the investable universe contains only names still alive today
* 349 of 1,176 tickers that were ever S&P 500/400 members in 2012-2018 (30%) have no Yahoo price history (347 are delisted). The 6 other "early-ending" members are 2026 stubs with a single bar. Yahoo drops history on delisting.
* Share of the point-in-time S&P 500 / S&P 400 members that is tradable (has a price) at month-ends 2012-2018: S&P 500 71% (2012) -> 87% (2018), mean 78.5%; S&P 400 57% -> 76%, mean 63.5%. Backtest SP900 universe at 2012-01-31 = 577 names (of 900 nominal).
* Consequence: no price series in the panel ends before 2019 among 2012-2018 members; every name ever held by the DEFAULT strategies (209 QM / 122 TC / 137 MF in train; 358 / 237 / 238 over 2012-2026) is alive on 2026-10-16. The engine's delisting path (cash at last price, no delisting loss) is never exercised, so delisting losses are 0 by construction.
* Size of the distortion (train, own tests): equal-weight survivors-only S&P 500 (monthly rebalanced, 0 cost) beats RSP (+0.20% fee add-back) by +0.95 %/yr; cap-weighted survivors-only S&P 500 beats SPY by +2.3 %/yr; cap-weighted survivors-only S&P 400 LAGS MDY by -3.1 %/yr (acquired mid-caps are missing; share counts add noise). So the universe is not representative in either direction by roughly +-1-3 %/yr, and benchmark comparisons (SPY/RSP/MDY) are contaminated. Same-universe benchmark (`DataContext.ew_universe`) is the only clean comparison.
* Fix: obtain delisted price histories (CRSP/Norgate/Sharadar/EODHD) or, minimum, add a delisting-return stress (e.g. -30% on non-merger exits) and report strategy minus `ew_universe` as the headline; say so in every table header.

### F2 (MEDIUM, mild look-ahead) GICS sub-industry labels back-filled from LATER snapshots
* `membership.parquet`: 41,455 of 215,693 rows (19.2%) have `gics_source` in {asof_next 39,805; backfill_next 870; era_next 780}; 39,565 of them are S&P 500 rows. (Plus 126,572 `asof_prev`, 44,522 own `snapshot`.)
* SP900 month-end universe: ~61% of rows through 2013-01, then 14-18% (2013-07..2016), 13% (2017-01), 0.8-1.3% from 2017-07. Train mean 22%.
* trading_comps (peer groups use `sub_industry_code`): share of held names with a `*_next` label = 74% in 2012, 30% in 2013, 7% 2014, 3% 2015, 10% 2016, 0% 2017, 1.8% 2018 (mean 18%); 38% of held name-months (489/1,280) have at least one `*_next`-labelled peer in their sub-industry pool. QM (industry-median comparisons in Q3a) and MF (sector exclusion only) hold 22% / 21% `*_next` names (70% / 79% in 2012, 12-14% afterwards).
* Practical impact looks small: among companies with their own Wikipedia labels, sub-industry NAME changed for 0.0% of 313 firms between 2013-09 and 2015-03 (sector 0.0%); the sector change of 7.9% in 2015-03..2016-09 is the REIT carve-out (handled by era mapping). TC re-run with `*_next` rows treated as unclassified: 2013-07..2018-12 CAGR 1.11% -> 1.25% (no change); full train 4.5% -> 2.2% but that is driven by deleting 62% of the 2012 universe, not interpretable.
* Fix: `quant/data/universe.py::attach_gics` - set `gics_source` to a "PIT-safe" boolean and let `trading_comps._state` treat `*_next` rows as unclassified (or start TC at 2013-07 and report 2012 separately).

### F3 (LOW-MEDIUM, data) Spin-off "splits" make market caps wrong by the later non-genuine ratio
* `DataContext.shares_on/market_cap` adjust shares with genuine splits only, but Yahoo `close` is back-adjusted by ALL ratios (225 non-genuine rows, e.g. ABT 2.084 on 2013-01-02, DD 1.487, DOV 1.238, XRX 1.518, BBWI 1.237). Result: mcap (hence EV, P/E, EY, min-cap test) before the event is understated by F_ng = product of later non-genuine ratios (overstated if < 1). MF/TC `price_raw` for the $5 floor has the same inconsistency (QM's price filter correctly uses all ratios).
* 2,400 of 50,400 SP900 name-months (4.8%, 38 tickers) have |F_ng-1| > 2%; held name-months affected: TC 108 (8.4%), MF 186 (7.4%), QM 0.
* Impact when fixed (mcap x F_ng): TC train CAGR 4.49% -> 4.19%, net Sharpe(m) 0.340 -> 0.318, holdings overlap 0.89; MF 11.68% -> 11.94%, Sharpe(m) 0.886 -> 0.907, overlap 0.93. Small, mixed sign.
* Fix: `quant/data/context.py::market_cap` (and `comps.multiples_table`, `magic_formula._build_base`): multiply mcap and as-traded price by `split_factor_after(all)/split_factor_after(genuine)`.

### F4 (LOW, data) Yahoo double-adjusts adjclose at some spin-offs
* DHR 2016-07-05: ret_adjclose +61.2% vs ret_close +3.6% (ratio close/adjclose jumps 1.640 -> 1.054); DXC 2015-11-30 (+8.4% vs -20.5%); XRX 2017-01-03 (+37.6% vs +19.8%). Only 3 events in the S&P 900 train universe with an error > 10 pp.
* No DEFAULT portfolio held them on the event day, but DHR's polluted 12-1 momentum (+97%/+97%/+74%/+87% vs +27%/+26%/+12%/+20% repaired) put it into the QM book in 2016-08, -09, -10 and 2017-02 (replaced by MZTI/CPRT/LRCX/CMI once repaired); QM train CAGR 11.44% -> 11.47%.
* Fix: add rule R8 to `quant/data/prices.py::rebuild_outputs`: when a non-genuine split coincides with a close/adjclose factor jump, rescale pre-event adjclose so that ret_adjclose == ret_close.

### F5 (INFO) Engine design notes (no numeric error found)
* Tradability uses the full return frame: a target whose series ended before the trade day is dropped (1-day-forward delisting knowledge). `dropped` is empty in all three train runs, so no effect.
* Stop-loss executes at the same close that triggers it and the reference price resets at every rebalance; executing at the next close instead would be better by +0.29 pp (stop 10%) / +0.08 pp (15%) CAGR, i.e. the convention is slightly conservative.
* Costs are a flat 10 bp on all trades (no spread/impact differences for mid caps); the first entry costs 10 bp; forced delisting sales are free by design.

### F6 (INFO) MF sector fallbacks
`_sector_info` can use 'gics_next' (first later snapshot) and a static current-EDGAR SIC map when the point-in-time sector is unmapped. In the train tables 99.99% of universe rows and 100% of the 2,520 selected name-months have a direct point-in-time GICS sector, so no effect.

### F7 (INFO) Other data observations
* `returns.parquet` equals `compute_returns(adjclose)` exactly (0 of 14.9M cells differ).
* 880 of 359k snapshots have `shares_out_date` later than `filed` (0.25%), 2 snapshots have `filed < period_end`; harmless for market caps (value comes from the same filing).
* S&P 500 effective-date timing is correct (META absent 2013-12-22, present 2013-12-23; TSLA 2020-12-21).
* First monthly observation of each strategy is a partial month (first trade day is t+1 of the first signal); `monthly()` documents this.

## Reproduction
Scripts in `/private/tmp/claude-501/-Users-vivaanshahani-Downloads-Code-WhartonGlobalChallengeCapitalCrew/0a3c61ed-97de-4872-b667-f7e65d404d83/scratchpad/audit_bt/`:
`s01_weights.py` (weights), `s02_engine_compare.py`/`s08_opts.py` (check 1), `s09_lookahead.py`/`s10_reverse_t.py`/`s28_engine_causal.py` (check 2), `s12_align.py` (check 3), `s13_delist_synth.py`/`s07_delist.py`/`s14_survivor_bias.py`/`s30_capw.py` (check 4, F1), `s03_costs.py` (check 5), `s11_metrics.py` (check 6), `s16_misc.py`/`s15_fund_pit.py`/`s26_fund_pit2.py` (check 7), `s04..s06`, `s19_gics_sens.py` (F2), `s17/s18_*.py` (F3), `s22..s25` (F4), `s20_stoplag.py` (F5).
