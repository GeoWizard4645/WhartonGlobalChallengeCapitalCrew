# Live picks audit: positions to be entered Wed 2026-10-21 (signals as of the 2026-10-16 close)

Audit date: Sunday 2026-10-18. Scope: the union of `output/live/quality_momentum_chosen.csv` (10 names, weight > 0), `magic_formula_chosen.csv` (25 PICK rows) and `trading_comps_chosen.csv` (19 selected rows) = **48 unique tickers** (1 overlap QM/MF: ANF; 5 overlaps MF/TC: BAH, BKNG, G, GEN, HRB). Per-ticker numbers are in `output/audit/live_picks_audit.csv`. No code or pick files were modified.

**UPDATE 2026-10-19 (final trading-comps list).** The pre-registered TC selection was re-run (theta 0.10, P/E cap 40, EV/EBITDA cap 35, size filter off; 20 names). Sections 2-12 were written against the earlier 19-name TC list: nine TC-only names (PTC, BSX, MLI, CDW, DBX, EHC, GEHC, LVS, SNA) are no longer picks and are marked SUPERSEDED, and seven names are new (AA, KBR, ENS, SFM, ZTS, SON, CRUS). Section 13 audits the final list and gives the final union (46 names: 24 OK, 18 CAUTION, 4 BLOCK). QM and MF picks are unchanged.

## 1. Bottom line

- **Final union (46 names): 4 BLOCK, 18 CAUTION, 24 OK** (the earlier 48-name pass had 4 / 16 / 28; see section 13).
- **BLOCK**: VAL (all-stock takeover by Transocean, price pinned to RIG), HON (MF EBIT includes the spun-off Aerospace business, EY overstated about 2.5x), SOLV (MF EBIT includes a $1.5B one-off gain on sale, EY overstated about 4x), SON (TC: TTM NI and EBITDA include a $0.38B ThermoSafe gain, clean leverage fails the 3.0x gate). PTC (cash takeover by Schneider Electric) was BLOCK in the earlier TC list and is no longer a pick.
- Prices: all of our prices (the 48 in the first pass, the 5 replacements and the 7 new TC names) equal the fresh Yahoo close for 2026-10-16 to the cent; 2026-10-16 is also the latest close available (it is now Monday 2026-10-19 before the open). All market caps are within 4.3% of Yahoo `marketCap` (largest: DBX +4.3%), so no mcap flag at the 5% threshold.
- Quality-momentum inputs recomputed from a fresh 3-year history (12-1 momentum, SMA200, Wilder RSI14) match our file to 4+ decimals for all 10 names, and all 10 still pass the SMA200 and 50-70 RSI screens as of 10-16. The odd-looking prices (BKNG $163, MU $879, SNDK $1,299, BSX $44, VLO $445) are genuine, not split/spin artefacts (section 5).
- Event risk is pervasive: 35 of 46 names in the final union report between Oct 21 and Nov 6. Two report BEFORE the Wednesday fills (STLD Oct 19 after close, MLI Oct 20 before open; MLI is no longer a pick), so STLD's screen should be re-run on the Oct 20 close.
- Concentration (final union of 46): QM is 50% Energy (5 of 10 names, avg pairwise 6-month correlation 0.55; 4 of 9 once VAL is removed); by sector the union is Industrials 10, Information Technology 10, Health Care 8, Consumer Discretionary 7, Energy 5, Materials 4, Consumer Staples 2, with no Financials, Utilities, Real Estate or Communication Services. MF and TC now share eight names and ANF sits in all three sleeves (section 13).
- Replacements for the four BLOCKs (section 12): CF CAUTION (energy-regime correlation, thin RSI margin), RS OK (backup), OTIS OK, INTU OK, PNR CAUTION (profit warning; also downgraded in its TC role).

## 2. Verdict per ticker (BLOCK first, then CAUTION, then OK)

Lists: QM = quality momentum, MF = magic formula, TC = trading comps. Earnings dates are from Yahoo's calendar; the ones marked * were checked against a company press release. ADV30 = 30-day average daily dollar volume.

| Ticker | Lists | Status | Reason | Next earnings | ADV30 ($M) |
|---|---|---|---|---|---|
| HON | MF | **BLOCK** | DATA ERROR: EBIT $8.40B (EY 8.7%) includes Aerospace (spun 2026-06-29, still in Q2 consolidated results) and Yahoo TTM is $5.99B; standalone Honeywell Technologies GAAP op income was $1.17B in FY25 and $662M in Q2-26 (segment profit $985M) so true EY is ~3-4%, not 8.7%. | 2026-10-22 BMO* | 569 |
| SOLV | MF | **BLOCK** | DATA ERROR: EBIT $2.08B includes a $1.52B one-off gain on sale of the Purification & Filtration business (Q3-25); GAAP operating income TTM is $525M (Yahoo), so EY is ~2.7%, not 10.5%. | 2026-11-05 AMC | 84 |
| VAL | QM | **BLOCK** | Being acquired by Transocean (15.235 RIG per VAL, 2026-02-09); VAL $85.32 vs implied $85.62 (-0.35%) so it is a RIG proxy; votes 2026-11-24; QM quality inputs polluted by a $680M tax benefit (Q4-25). | 2026-11-02 AMC | 97 |
| PTC | TC | ~~BLOCK~~ SUPERSEDED (not in final TC list) | Being acquired by Schneider Electric for $205 cash (merger agreement 2026-10-04); price pinned ($192.98, 6% spread), close expected by Q3 2027. | 2026-11-11 AMC | 621 |
| BSX | TC | ~~CAUTION~~ SUPERSEDED (not in final TC list) | 8-K Item 1.05 (cyberattack 2026-08-25): company says it is unlikely to meet Q3/FY26 guidance; revised outlook due on the 2026-10-28 call; stock -55% over 12m, so TTM P/E discount to peers reflects impaired earnings; Yahoo fwd P/E 13.1x is stale. | 2026-10-28 BMO* | 840 |
| GEN | MF/TC | **CAUTION** | FT (2026-09-24): Gen approached GoDaddy (talks early-stage; CEO LinkedIn post 2026-09-28 declines to comment); stock -12% that day, -20% in 1m; reports 2026-10-28; MF ROC 13.5x is a capital-floor artefact and TC EV discount leans on PTC (deal-pinned) as a peer. | 2026-10-28 AMC* | 269 |
| GDDY | MF | **CAUTION** | Rumoured takeover target of Gen Digital (FT 2026-09-24, +8.7% that day); price carries a speculative bid premium that disappears if talks end; no definitive agreement. Reports 2026-10-29. | 2026-10-29 AMC | 228 |
| SNDK | MF | **CAUTION** | Fails the QM RSI screen itself (RSI 29.7, dropped_by=rsi); -44% from 2026-06-25 high, -27% since 10-01, 12-1 mom +1019%; vol 73%; reports 2026-10-29 AMC (options imply about +/-11%); $1,299/share; history only since Feb-2025 spin; 0.85 corr with MU. | 2026-10-29 AMC* | 15,072 |
| MU | MF | **CAUTION** | Price $878.84 is genuine (no split; Yahoo 10-15 close $931.24 matches third-party quote) but -28% from the 2026-06-25 high, -20% since 10-01, 12-1 mom +410%; RSI 34; vol 53%; 0.85 corr with SNDK (two memory names = 8% of MF). | 2026-12-23 AMC | 27,000 |
| PBF | QM | **CAUTION** | Energy cluster (5 of 10 QM names; avg pairwise corr 0.55); TTM NI $1.35B is inflated: Yahoo normalised income is only $0.54B ($1.03B unusual gains) and operating income is concentrated in Q2-26 ($995M vs -$243M to +$185M in the other three quarters); refining-margin peak risk; reports 2026-10-29. | 2026-10-29 BMO | 283 |
| VLO | QM | **CAUTION** | Energy cluster; price $444.71 genuine (+176% in 12m) on extreme diesel cracks; mean-reversion risk and UBS/MS notes flag margin normalisation; reports 2026-10-22 (day after fills). | 2026-10-22 BMO* | 1,375 |
| APA | QM | **CAUTION** | Energy cluster; RSI 69.73 is 0.27 below the 70 cap (will likely fail the screen on any further up-day); gpoa missing (NaN) but passes team quality rule; results 2026-11-04 AMC. | 2026-11-04 AMC* | 255 |
| CHRD | QM | **CAUTION** | Energy cluster; RSI 68.04 near cap; thinnest liquidity in QM (ADV 687k sh, $99M); reports ~2026-11-03. | 2026-11-03 AMC | 99 |
| ANF | QM/MF | **CAUTION** | In BOTH QM (10%) and MF (4%) = 14% combined weight in one name; RSI 69.57 is 0.43 below the 70 cap; +35.7% on 2026-08-26 earnings; at 52w high; MF EV excludes leases (ours 15% below Yahoo EV). | 2026-11-25 BMO | 188 |
| PNR | TC | **CAUTION** | Profit warning 2026-07-15 (2026 adj. EPS guide cut to $4.60-4.80 from $5.30-5.40, sales now -4% to -7%, pool-channel destocking), CFO left 07-10, law firms soliciting a securities class action; stock -52% from high; Q2 operating income -24% y/y so TTM EBIT/EPS overstate run-rate (annualised Q2 EBIT gives EY ~6.5%). Reports 2026-10-27. | 2026-10-27 BMO | 146 |
| STLD | QM | **CAUTION** | Reports Q3 on 2026-10-19 AFTER close, so the price will gap before the Wed fill: re-run SMA/RSI screen on the 10-20 close; CEO Millett retiring 2027-01-01. | 2026-10-19 AMC* | 221 |
| MLI | TC | ~~CAUTION~~ SUPERSEDED (not in final TC list) | Reports 2026-10-20 BEFORE open (one day before fills): re-check TC discount on the new TTM; 2:1 split on 2026-07-01 is correctly adjusted in Yahoo history. | 2026-10-20 BMO | 103 |
| ILMN | QM | **CAUTION** | Not cheap on any metric (P/E 49x, EV/EBITDA 35x) and the QM signal is index-driven: joined S&P 500 on 2026-09-21 after +30% run since 09-10; 12-1 mom +164%; reports 2026-10-29 AMC. | 2026-10-29 AMC* | 930 |
| MMS | TC | **CAUTION** | Fundamentals deteriorating despite cheap multiples: FY26 EPS guide cut (VA contract incentive pause), DSO 98 days, Q3 FCF -$137M, TTM book-to-bill 0.5; lowest dollar liquidity in the union ($42M ADV). | 2026-11-19 BMO | 42 |
| GAP | TC | **CAUTION** | TC discount is partly definitional: EV/EBITDA 3.2x (ours, ex-leases, EBITDA $2.2B) vs Yahoo 7.7x (EV incl. ~$4B leases/other, EBITDA $1.47B); TTM P/E 6.5x vs forward 8.8x implies forward EPS ~21% below TTM. | 2026-11-19 AMC | 135 |
| BAH | MF/TC | **OK** | Closed $720M Ultra Electronics ATS acquisition 2026-08-24; EBIT matches Yahoo; in MF and TC (overlap); earnings 2026-10-23. | 2026-10-23 BMO | 125 |
| BKNG | MF/TC | **OK** | Price $163.45 is genuine: 25-for-1 split effective 2026-04-02 (trading split-adjusted from 04-06); Yahoo history is correctly adjusted (12m-ago $203 = $5,081/25). ROIC=inf is an artefact of negative invested capital from buybacks (not a data error). MF EV $141B vs Yahoo $126.5B (+11%, definitional). | 2026-11-03 AMC | 1,364 |
| G | MF/TC | **OK** | Genpact is holding a 2026-11-10 special meeting to redomesticate Bermuda->Delaware (effective ~2027-03-01), no deal; new CFO 2026-09-09; EBIT/EV/P-E within 5% of Yahoo. | 2026-11-05 AMC | 65 |
| HRB | MF/TC | **OK** | ebit_proxy flag fine (ours $934M vs Yahoo $908M); in MF and TC (overlap); annual meeting 2026-11-10; earnings 2026-11-05. | 2026-11-05 AMC | 87 |
| ACN | MF | **OK** | RSI 72 and +20% in 1m after FQ4 beat (2026-10-01 +15.8%); our fundamentals are one quarter stale (period 2026-05-31) but Yahoo TTM EBIT is within 8%. | 2026-12-17 BMO | 1,368 |
| ADBE | MF | **OK** | CEO succession (Chakravarthy CEO from 2026-12-01, CFO also leaving) and AI-disruption narrative; EBIT $9.27B matches Yahoo exactly; nwc<0 flag is benign. | 2026-12-09 AMC | 1,290 |
| BMY | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-29 BMO | 785 |
| CDW | TC | ~~OK~~ SUPERSEDED (not in final TC list) | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-11-03 BMO | 224 |
| CI | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-11-05 BMO | 441 |
| CROX | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-29 BMO | 134 |
| CTSH | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-29 BMO | 395 |
| DBX | TC | ~~OK~~ SUPERSEDED (not in final TC list) | ROIC 7.97 is an artefact (avg invested capital only $67M after buybacks/deferred revenue); mcap +4.3% vs Yahoo (share count). Earnings 2026-11-05 AMC (reaction on 11-06, last trading day). | 2026-11-05 AMC* | 147 |
| EHC | TC | ~~OK~~ SUPERSEDED (not in final TC list) | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-28 AMC | 112 |
| GEHC | TC | ~~OK~~ SUPERSEDED (not in final TC list) | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-28 BMO | 247 |
| HPQ | MF | **OK** | nwc<0 benign; EBIT $3.22B vs Yahoo $3.88B (-17%, within tolerance); interim CEO since Feb; -13% in 1m; earnings 2026-11-24. | 2026-11-24 AMC | 473 |
| INCY | MF | **OK** | debt_zero_inferred is correct (no debt); CMS/Medicaid price agreement on Jakafi (8-K 2026-08-31) is a policy overhang; ESMO data 2026-10-24; earnings 2026-10-29. | 2026-10-29 BMO* | 201 |
| IT | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-11-03 BMO | 183 |
| LDOS | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-11-03 BMO | 154 |
| LVS | TC | ~~OK~~ SUPERSEDED (not in final TC list) | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-21 AMC | 232 |
| MO | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-29 BMO | 559 |
| NUE | QM | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-26 AMC* | 300 |
| SAIC | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-12-03 BMO | 56 |
| SN | QM | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-11-04 BMO* | 306 |
| SNA | TC | ~~OK~~ SUPERSEDED (not in final TC list) | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-10-22 BMO | 107 |
| THC | TC | **OK** | Data match Yahoo; Yahoo forward P/E 12.7x vs TTM 9.6x (ours) implies forward EPS ~24% below TTM (no one-off gain found: normalised income ~ NI). | 2026-10-29 BMO | 182 |
| TPR | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-11-05 BMO | 335 |
| TTEK | MF | **OK** | Inputs match fresh Yahoo data; no deal, spin-off, delisting or restatement found. | 2026-11-11 AMC | 71 |
| UHS | TC | **OK** | Data match Yahoo (P/E 7.3 vs 7.6). Standing legal risk: Nevada $500M punitive verdict (new trial granted 2026-02-25, retrial/appeal pending); Talkspace acquisition closed 2026-08-17. | 2026-10-27 AMC | 125 |

## 3. The four BLOCKs in detail

**PTC (TC pick #19).** Schneider Electric agreed on 2026-10-04/05 to buy PTC for $205 per share in cash (about $22.6B equity value, $23.7B EV; 42.3% premium; closing expected by Q3 2027 subject to shareholder and regulatory approval). Close on 2026-10-16 was $192.98 (6.2% below the offer), so the stock is a merger-arbitrage position, not a comps-discount trade. PTC was also a peer in GEN's benchmark in the earlier TC list; in the final list it is only in GEN's EV peer set and removing it would raise the median (18.1x to 19.2x), so it does not inflate the discount (section 13). Sources: PTC 8-K Item 1.01 https://www.sec.gov/Archives/edgar/data/857005/000119312526413124/d174191d8k.htm ; https://www.verdict.co.uk/schneider-electric-ptc-acquisition/ .

**VAL (QM pick #10).** Transocean agreed on 2026-02-09 to acquire Valaris for 15.235 Transocean shares per Valaris share (all-stock, Bermuda scheme of arrangement). RIG closed at $5.62 on 10-16, implying $85.62 versus VAL $85.32, a 0.35% spread, so VAL is simply RIG with a delay. Joint proxy (DEFM14A) was filed 2026-10-14; Valaris Court Meeting and Transocean EGM are both on 2026-11-24; a secondary summary (Quartr, 2026-10-14) reports Brazil's competition authority cleared the deal on 2026-10-13; closing is targeted for Q4 2026, after which VAL is delisted. Its quality inputs are also polluted: TTM net income of $940M includes a $680M tax benefit in Q4-25 (operating income TTM is $261M), and it clears the SMA200 screen by only 1.6%. Sources: https://www.sec.gov/Archives/edgar/data/314808/000114036126039488/ny20070137x2_defm14a.htm ; https://www.nasdaq.com/press-release/transocean-acquire-valaris-2026-02-09 .

**HON (MF pick #9; data error).** Our file shows EBIT $8.40B, EV $96.5B, EY 8.7%. Honeywell completed the Aerospace spin-off on 2026-06-29 (new ticker HONA; HON now means Honeywell Technologies, which also did a reverse split that day). The Q2-26 release still presents Aerospace in consolidated continuing operations ("will be reflected as discontinued operations in the third quarter"), so the trailing-twelve-month EBIT combines Aerospace with the businesses that remain, while market cap and EV are post-spin. Standalone Honeywell Technologies reported FY25 segment profit $3.507B and GAAP operating income $1.171B, and Q2-26 segment profit $985M / operating income $662M. On those figures EY is about 3-4%, nowhere near the top-25 cut. Q2 net income also includes a $6.6B one-time Quantinuum deconsolidation gain (Yahoo trailing P/E 7.8x is meaningless). Yahoo's own TTM operating income is $5.99B and its EBIT row is $11.6B, which confirms the series is not clean. Sources: https://www.sec.gov/Archives/edgar/data/0000773840/000077384026000120/exhibit99-q22026earningsre.htm ; https://honeywell.com/us/en/news/press-releases/2026/06/honeywell-aerospace-completes-spin-off-from-honeywell-technologies-and-begins-trading-on-nasdaq .

**SOLV (MF pick #18; data error).** Our EBIT is $2.076B (EY 10.5%). Yahoo's quarterly statement shows GAAP operating income of $525M over the last four quarters (181 + 79 + 93 + 172, $M); the gap is a $1.518B gain on the sale of the Purification & Filtration business booked in the quarter ended 2025-09-30, which is inside the TTM window if EBIT is built from pre-tax income plus interest (snap flags `int_net_fallback`). On operating income EY is about 2.7%. Also a $204M Bair Hugger litigation charge in Q2-26 (secondary source) and a Health Information Systems separation under way. Source: https://www.sec.gov/Archives/edgar/data/0001964738/000196473826000047/solv-20260630.htm .

## 4. Other discrepancies and data-quality notes in our files

| Item | Finding | Impact |
|---|---|---|
| MF EBIT definition | Only HON (+40% vs Yahoo TTM operating income, true gap much larger) and SOLV (+295%) exceed the 25% tolerance on a like-for-like basis. MU shows +68% only because Yahoo's quarterly statement stops at fiscal Q3 (2026-05-31); our $99.3B includes fiscal Q4 (reported 2026-09-30) and is consistent with Yahoo's TTM EBITDA of $108.8B. HPQ -17%, CI +12%, IT -12%, MO -10%, ACN -8% are definitional. | HON, SOLV: remove |
| MF EV | All within +/-15% of Yahoo EV (ANF -15%, BKNG +11.5%, HPQ +9%, IT +8%, CI +7%): our EV excludes operating leases, Yahoo's includes them. | none |
| MF review flags | `capital_floored` (GEN): ROC 13.5x is an artefact of a $156M capital floor; EY (9.4%) is sound and matches Yahoo (9.8%). `nwc<0` (GEN, GDDY, IT, ADBE, CI, MO, HPQ): NWC floored at 0 so capital is PP&E only; ROC is high by construction. `ebit_proxy` (HRB, BMY): ours vs Yahoo -3% / +3% / -1.5%, fine. `debt_zero_inferred` (INCY, ANF): both genuinely have no funded debt (ANF still has leases, see EV note). | benign |
| TC ROIC | BKNG ROIC = inf (negative average invested capital, -$6.8B, from buybacks; `capital_light` flag) and DBX 7.97 (average invested capital $67M) are arithmetic artefacts, not data errors; HRB 1.29 likewise (IC $0.6B). | benign |
| TC P/E and EV/EBITDA | Trailing P/E is within 9% of Yahoo for all 19 (THC -9%, PTC -9%, DBX -7%). EV/EBITDA is within 11% for 18 of 19; GAP is -58% (3.2x ours vs 7.7x Yahoo) because our EV excludes ~$4B of lease and other liabilities that Yahoo includes, and our EBITDA ($2.2B = operating income $1.68B + D&A) is higher than Yahoo's `ebitda` ($1.47B). The comps peers for GAP use the same ex-lease convention (ANF 6.6x, MUSA 10.0x), so the ranking is internally consistent but the headline discount is flattered. | GAP CAUTION |
| One-off gains in TTM NI (known issue) | Compared TTM net income with Yahoo 'Normalized Income' for all 48: the ratio NI / normalised is 6.9x for SOLV (gain on sale), 2.5x for PBF (about $1.03B of unusual gains: NI $1.35B vs $0.54B), 1.6x for HON (Quantinuum gain), 1.17x for CI ($1.15B unusual gains; MF uses EBIT, which is +12% vs Yahoo, fine), 1.09x for VAL (tax benefit) and 1.03-1.06x for TTEK, MLI and SNDK; every other name is between 0.80x and 1.02x. HPQ, IT, BMY, APA, LVS, MO, GEN and ACN carry net unusual CHARGES, so their TTM P/Es are if anything overstated. No TC name is flattered by a one-off gain. GEN's Yahoo forward P/E of 7.3x is non-GAAP and not comparable with its 13.7x trailing. | PBF CAUTION; SOLV, HON BLOCK |
| Screens failed to exclude deal-pinned stocks | PTC (TC) and VAL (QM) are announced takeover targets. Neither screen has an M&A-pending exclusion, and VAL shows up with a 0.35% spread to its deal ratio. Worth adding a rule before the next refresh. | process |
| Stale fundamentals | Yahoo's quarterly statements for ACN and MU stop at fiscal Q3 (2026-05-31). Our MF file already has MU's fiscal Q4 (period 2026-09-03, reported 2026-09-30) but ACN is still at 2026-05-31 although FQ4 was reported on 2026-10-01 (8-K Item 2.02); it will refresh once the 10-K is ingested. ACN EBIT $10.6B vs Yahoo $11.5B (same period, -8%, definitional). | none |

## 5. Price anomalies: all checked

| Ticker | Price | What was checked | Verdict |
|---|---|---|---|
| BKNG | $163.45 | Booking did a 25-for-1 forward split, effective 2026-04-02, trading split-adjusted from 2026-04-06 (10-Q for Q2-26). Yahoo history is split-adjusted: 12-month-ago close $203.23 = $5,081/25; no discontinuity in the series. | Genuine; adjusted history consistent |
| MU | $878.84 | No split in 3 years (Yahoo splits table). Quote cross-check: a third-party page lists $931.24 for 2026-10-15, which equals Yahoo's 10-15 close exactly (the page labels it Oct 16). Price 12 months ago $191.94; high $1,213.56 on 2026-06-25; market cap $994B. | Genuine; volatile (-28% from high) |
| SNDK | $1,299.30 | No split; spun from WDC in Feb-2025 (history starts 2025-02-13). A third-party page lists $1,787.69 for 2026-10-01 = Yahoo's 10-01 close exactly. High $2,335 on 2026-06-25, 12-month-ago $144.30. | Genuine; -44% from high |
| BSX | $44.39 | No split. -55% over 12 months: Feb-2026 guidance miss, Watchman/EP weakness, then a cyberattack on 2026-08-25 (8-K Item 1.05 on 2026-09-08; guidance withdrawn). A trade-press page quotes about $45 on Sep 8. | Genuine; see CAUTION |
| VLO | $444.71 | No split. +176% in 12 months; analyst notes in September cite an all-time high near $400 and diesel cracks far above historical ranges; Q2-26 adjusted EPS $12.54. | Genuine (energy shock) |
| HON | $211.41 | Yahoo history carries two non-split adjustments (1.061 on 2025-10-30 for the Solstice spin, 0.9535 on 2026-06-29 for the Aerospace spin) plus a reverse split. HON is not in QM, so 12-1 momentum is not used, but any momentum read on HON is unreliable. | Price fine, history spliced |
| MLI | $60.07 | 2-for-1 split on 2026-07-01 (and 2023-10-23); adjusted correctly in Yahoo. | Genuine |
| Others | | A scan of all 48 histories found no unexplained one-day move above 35% (largest: ANF +35.7% on 2026-08-26 earnings, PTC +33.5% on the 2026-10-05 deal). Splits/spin factors in the 3-year window: BKNG, HON, ILMN (2024 GRAIL), MLI, TTEK (2024 5-for-1). None falls inside the momentum window of a QM name. | OK |

## 6. Strategy-input recomputation

### Quality momentum (all 10: fresh data, 3-year Yahoo history, close 2026-10-16)

| Ticker | 12-1 mom ours / fresh | SMA200 ours / fresh | Price vs SMA200 | RSI14 ours / fresh | Passes SMA200 + RSI 50-70 |
|---|---|---|---|---|---|
| PBF | 1.7925 / 1.7925 | 51.24 / 51.24 | +64.9% | 55.93 / 55.93 | yes |
| ILMN | 1.6363 / 1.6363 | 169.65 / 169.65 | +54.8% | 53.12 / 53.12 | yes |
| VLO | 1.6169 / 1.6169 | 274.01 / 274.01 | +62.3% | 66.40 / 66.40 | yes |
| APA | 1.0243 / 1.0243 | 36.43 / 36.43 | +34.9% | 69.73 / 69.73 | yes |
| NUE | 0.9568 / 0.9568 | 219.11 / 219.11 | +17.0% | 56.46 / 56.46 | yes |
| ANF | 0.9491 / 0.9491 | 102.54 / 102.54 | +49.5% | 69.57 / 69.57 | yes |
| SN | 0.7524 / 0.7524 | 138.57 / 138.57 | +34.6% | 56.61 / 56.61 | yes |
| STLD | 0.6939 / 0.6939 | 220.13 / 220.13 | +9.3% | 54.06 / 54.06 | yes |
| CHRD | 0.6931 / 0.6931 | 128.17 / 128.17 | +20.6% | 68.04 / 68.04 | yes |
| VAL | 0.6770 / 0.6770 | 83.94 / 83.94 | +1.6% | 55.63 / 55.63 | yes |

Margins to the screen boundaries are thin for APA (RSI 69.73) and ANF (69.57) against the 70 cap, and VAL (+1.6% above SMA200). SNDK (12-1 momentum +1019%) was already dropped by the QM RSI filter (RSI 29.7; listed in `quality_momentum_chosen.csv` with dropped_by = rsi), yet it is an MF pick. Net income TTM for the 10 names agrees with Yahoo's quarterly statements (PBF 1.353B, VLO 7.212B, APA 1.677B, NUE 2.884B, ANF 0.536B, SN 0.695B, STLD 1.607B, CHRD 0.848B, VAL 0.940B).

### Magic formula (EBIT and EV versus Yahoo; $B)

| Ticker | EBIT ours | Yahoo TTM op. income | diff | EV ours | EV Yahoo | diff | EY ours | EY on Yahoo figures | MF review flags |
|---|---|---|---|---|---|---|---|---|---|
| ACN | 10.59 | 11.52 | -8% | 140.8 | 137.9 | +2% | 7.5% | 8.3% | shares:diluted |
| ADBE | 9.27 | 9.27 | 0% | 100.2 | 96.6 | +4% | 9.3% | 9.6% | nwc<0 |
| ANF | 0.73 | 0.73 | 0% | 6.1 | 7.2 | -15% | 12.1% | 10.2% | snap:debt_zero_inferred |
| BAH | 1.05 | 1.05 | 0% | 12.3 | 12.6 | -2% | 8.6% | 8.4% |  |
| BKNG | 9.28 | 9.74 | -5% | 141.0 | 126.5 | +11% | 6.6% | 7.7% |  |
| BMY | 13.64 | 13.84 | -1% | 156.0 | 156.0 | -0% | 8.7% | 8.9% | snap:ebit_proxy |
| CI | 9.96 | 8.91 | 12% | 112.0 | 104.8 | +7% | 8.9% | 8.5% | nwc<0 |
| CROX | 0.84 | 0.84 | 0% | 7.0 | 7.4 | -5% | 11.9% | 11.3% |  |
| CTSH | 3.44 | 3.52 | -2% | 30.4 | 30.8 | -1% | 11.3% | 11.4% | snap:shares_bs |
| G | 0.78 | 0.79 | -1% | 6.9 | 7.2 | -3% | 11.2% | 11.0% |  |
| GDDY | 1.27 | 1.29 | -2% | 17.2 | 16.1 | +7% | 7.4% | 8.0% | snap:cash_alt;nwc<0 |
| GEN | 2.12 | 2.17 | -3% | 22.6 | 22.1 | +2% | 9.4% | 9.8% | snap:cash_alt;capital_floored;nwc<0 |
| HON | 8.40 | 5.99 | 40% | 96.5 | 93.1 | +4% | 8.7% | 6.4% |  |
| HPQ | 3.22 | 3.88 | -17% | 36.2 | 33.2 | +9% | 8.9% | 11.7% | nwc<0 |
| HRB | 0.93 | 0.91 | 3% | 7.4 | 7.1 | +3% | 12.7% | 12.7% | snap:ebit_proxy |
| INCY | 1.78 | 1.84 | -3% | 18.8 | 18.4 | +2% | 9.5% | 10.0% | snap:debt_zero_inferred;snap:shares_bs |
| IT | 1.12 | 1.26 | -11% | 15.9 | 14.8 | +8% | 7.0% | 8.5% | nwc<0 |
| LDOS | 2.03 | 2.08 | -2% | 21.0 | 21.5 | -3% | 9.7% | 9.7% |  |
| MO | 10.97 | 12.26 | -10% | 150.0 | 147.7 | +2% | 7.3% | 8.3% | nwc<0 |
| MU | 99.34 | 59.28 | 68% | 956.1 | 956.1 | +0% | 10.4% | 6.2% |  |
| SAIC | 0.59 | 0.59 | 0% | 7.9 | 8.2 | -3% | 7.5% | 7.3% |  |
| SNDK | 12.39 | 12.47 | -1% | 185.5 | 185.7 | -0% | 6.7% | 6.7% |  |
| SOLV | 2.08 | 0.53 | 295% | 19.8 | 19.5 | +2% | 10.5% | 2.7% |  |
| TPR | 1.91 | n/a | n/a | 25.2 | 26.8 | -6% | 7.6% | n/a |  |
| TTEK | 0.61 | 0.59 | 3% | 9.5 | 9.7 | -2% | 6.5% | 6.1% |  |

TPR: Yahoo's statement lacks operating income for three of four quarters; its EBIT row sums to $1.916B, matching ours ($1.914B). Market caps: all within 1.3% of Yahoo for MF names.

### Trading comps (P/E and EV/EBITDA versus Yahoo)

| Ticker | P/E ours | P/E Yahoo trailing | diff | EV/EBITDA ours | EV/EBITDA Yahoo | diff | Yahoo fwd P/E | P/E discount to peers | ROIC |
|---|---|---|---|---|---|---|---|---|---|
| BAH | 11.5 | 11.7 | -2% | 10.1 | 10.0 | +1% | 11.0 | 57% | 0.20 |
| BKNG | 17.0 | 18.1 | -6% | 12.8 | 12.2 | +5% | 13.2 | 41% | inf |
| BSX | 17.5 | 18.0 | -3% | 13.8 | 13.4 | +3% | 13.1 | 42% | 0.11 |
| CDW | 17.4 | 18.1 | -4% | 12.3 | 12.4 | -1% | 12.5 | 39% | 0.16 |
| DBX | 18.2 | 19.7 | -7% | 12.7 | 12.8 | -1% | 10.8 | 27% | 7.97 |
| EHC | 20.3 | 21.4 | -5% | 10.7 | 11.1 | -4% | 19.1 | 20% | 0.16 |
| G | 10.7 | 11.1 | -3% | 8.0 | 8.1 | -2% | 8.3 | 61% | 0.18 |
| GAP | 6.5 | 7.0 | -6% | 3.2 | 7.7 | -58% | 8.8 | 46% | 0.46 |
| GEHC | 15.9 | 16.0 | -0% | 11.9 | 11.2 | +7% | 12.9 | 41% | 0.11 |
| GEN | 13.7 | 14.1 | -3% | 8.4 | 9.2 | -8% | 7.3 | 22% | 0.14 |
| HRB | 8.2 | 8.6 | -4% | 6.2 | 6.9 | -11% | 7.0 | 55% | 1.29 |
| LVS | 14.3 | 14.8 | -4% | 8.4 | 7.9 | +6% | 11.0 | 23% | 0.18 |
| MLI | 15.6 | 15.6 | -0% | 10.5 | 10.9 | -4% | 12.9 | 39% | 0.39 |
| MMS | 8.7 | 9.1 | -5% | 7.6 | 7.1 | +8% | 7.4 | 57% | 0.13 |
| PNR | 13.3 | 13.8 | -4% | 10.9 | 9.9 | +10% | 10.2 | 41% | 0.14 |
| PTC | 17.1 | 18.7 | -9% | 18.1 | 17.4 | +4% | 21.6 | 16% | 0.20 |
| SNA | 18.4 | 18.7 | -2% | 13.0 | 13.2 | -2% | 17.1 | 44% | 0.19 |
| THC | 9.6 | 10.5 | -9% | 6.7 | 7.6 | -11% | 12.7 | 61% | 0.22 |
| UHS | 7.3 | 7.6 | -5% | 6.0 | 6.0 | -1% | 7.7 | 70% | 0.13 |

## 7. Corporate events (last ~4 months; EDGAR 8-K/S-4/DEFM14A/SC TO scan of all 48 CIKs since 2026-06-01, plus web search)

| Ticker | Event | Date | Source |
|---|---|---|---|
| PTC | Definitive merger agreement with Schneider Electric, $205 cash | 2026-10-04/05 | https://www.sec.gov/Archives/edgar/data/857005/000119312526413124/d174191d8k.htm |
| VAL | Business combination with Transocean (15.235 RIG per share); DEFM14A, meetings 2026-11-24 | 2026-02-09; 2026-10-14 | https://www.sec.gov/Archives/edgar/data/314808/000114036126039488/ny20070137x2_defm14a.htm |
| HON | Aerospace spin-off completed (HONA), reverse split, Quantinuum deconsolidation gain | 2026-06-29 | https://honeywell.com/us/en/news/press-releases/2026/06/honeywell-aerospace-completes-spin-off-from-honeywell-technologies-and-begins-trading-on-nasdaq |
| GEN / GDDY | FT report that Gen approached GoDaddy (early-stage); GEN CEO post declining comment (8-K Item 7.01) | 2026-09-24; 2026-09-28 | https://webhosting.today/2026/09/24/nortons-owner-has-approached-godaddy-the-market-marked-the-target-up-8-7-percent-and-the-bidder-down-6-1/ ; https://www.sec.gov/Archives/edgar/data/849399/000084939926000071/exhibit991.htm |
| BSX | Cybersecurity incident (8-K Item 1.05); guidance unlikely to be met; restructuring $700-800M (Item 2.05, 2026-07-21) | 2026-08-25 / 2026-09-08 | https://www.sec.gov/Archives/edgar/data/885725/000088572526000059/bsx-20260907.htm |
| SOLV | Sold Purification & Filtration (gain in TTM); Bair Hugger charge; HIS separation planned | 2025-09 / 2026-Q2 | https://www.sec.gov/Archives/edgar/data/0001964738/000196473826000047/solv-20260630.htm |
| ILMN | Added to the S&P 500 (replacing Builders FirstSource); credit facility and CP programme 8-Ks | effective 2026-09-21 | https://press.spglobal.com/2026-09-04-Bloom-Energy,-Illumina,-and-Everpure-Set-to-Join-S-P-500-Others-to-Join-S-P-100,-S-P-MidCap-400,-and-S-P-SmallCap-600 |
| G | Special meeting 2026-11-10 to redomesticate Bermuda to Delaware (effective about 2027-03-01); new CFO | 2026-10-07 (424B3) | https://www.sec.gov/Archives/edgar/data/1398659/000114036126038914/ny20078357x5_424b3.htm |
| BAH | Closed $720M acquisition of Ultra Electronics Advanced Tactical Systems | 2026-08-24 | https://www.sec.gov/Archives/edgar/data/1443646/000110465926076094/tm2618424d1_8k.htm |
| UHS | Closed Talkspace acquisition ($835M); Nevada $500M punitive verdict: new trial granted 2026-02-25, outcome pending | 2026-08-17 | https://ir.uhs.com/node/20321/html |
| ADBE | CEO succession (Chakravarthy from 2026-12-01), CFO also exiting | 2026-09-03 | https://www.tikr.com/blog/adobe-adbe-stock-names-anil-chakravarthy-new-ceo |
| INCY | Agreement with CMS to give state Medicaid programs Jakafi at international-reference prices | 2026-08-31 | https://www.sec.gov/Archives/edgar/data/879169/000087916926000058/incy-20260831.htm |
| STLD | CEO Millett to retire 2027-01-01 | 2026-08-03 | https://www.sec.gov/Archives/edgar/data/1022671/000110465926090129/tm2622182d1_8k.htm |
| MMS | FY26 adjusted EPS guide cut to $7.90-8.20 (VA contract incentive pause); DSO 98; FCF -$137M in the quarter | 2026-08-06 | https://www.nasdaq.com/articles/maximus-q3-earnings-beat-estimates-increase-year-over-year |
| HPQ | Interim CEO since February (CEO left for PayPal); -13% in the last month | 2026-02 / 2026-10 | https://business.mammothtimes.com/mammothtimes/article/stockstory-2026-2-3-why-hp-hpq-shares-are-trading-lower-today |
| PNR | Profit warning: 2026 adj. EPS guide cut to $4.60-4.80 (from $5.30-5.40), sales -4% to -7% on pool destocking, CFO departed 07-10; securities class-action solicitations | 2026-07-14/15 | https://www.tradingpedia.com/2026/07/15/pentair-shares-sink-after-sharp-guidance-cut-and-cfo-exit/ ; https://www.glancylaw.com/cases/pentair-plc/ |
| PBF | Refinancing: 9.875% 2030 notes called for 2026-10-26; new notes priced 2026-09-14 | 2026-10-14 | https://www.sec.gov/Archives/edgar/data/1534504/000153450426000035/pbf-20261014.htm |

No bankruptcy, delisting notice (Item 3.01), non-reliance/restatement (Item 4.02), going-private (SC 13E3/SC TO) or index-deletion event was found for any of the other tickers. Routine CEO/CFO/director changes (GEHC, LDOS, VLO, MU, SNDK, CI, IT, SAIC, GAP, MO, CHRD, HRB, CDW, MLI, ANF) and debt refinancings (CTSH, MO, CDW, THC, UHS, SAIC, GDDY, GAP, EHC, DBX, SNDK, ILMN) are not trade-relevant. Lists are not exhaustive for litigation: a 3-month litigation review was limited to 8-K Item 8.01, 10-Q disclosures and press searches.

## 8. Earnings between Oct 21 and Nov 6 (earlier 48-name list: 36 names; the final union is in section 13; AMC = after close, so the price reaction is the next trading day)

| Date | Tickers |
|---|---|
| 2026-10-21 | LVS (AMC) |
| 2026-10-22 | HON (BMO*, BLOCK), SNA (BMO), VLO (BMO*, CAUTION) |
| 2026-10-23 | BAH (BMO) |
| 2026-10-26 | NUE (AMC*) |
| 2026-10-27 | PNR (BMO, CAUTION), UHS (AMC) |
| 2026-10-28 | BSX (BMO*, CAUTION), EHC (AMC), GEHC (BMO), GEN (AMC*, CAUTION) |
| 2026-10-29 | BMY (BMO), CROX (BMO), CTSH (BMO), GDDY (AMC, CAUTION), ILMN (AMC*, CAUTION), INCY (BMO*), MO (BMO), PBF (BMO, CAUTION), SNDK (AMC*, CAUTION), THC (BMO) |
| 2026-11-02 | VAL (AMC, BLOCK) |
| 2026-11-03 | BKNG (AMC), CDW (BMO), CHRD (AMC, CAUTION), IT (BMO), LDOS (BMO) |
| 2026-11-04 | APA (AMC*, CAUTION), SN (BMO*) |
| 2026-11-05 | CI (BMO), DBX (AMC*), G (AMC), HRB (AMC), SOLV (AMC, BLOCK), TPR (BMO) |

Outside the window: ACN Dec 17, ADBE Dec 9, ANF Nov 25, GAP Nov 19, HPQ Nov 24, MMS Nov 19, MU Dec 23 (reported 2026-09-30), PTC Nov 11, SAIC Dec 3, TTEK Nov 11. Before the fills: STLD Oct 19 (after close), MLI Oct 20 (before open). The highest-impact prints for the book are BSX (new outlook, Oct 28), GEN/GDDY (Oct 28/29, deal news possible), SNDK (Oct 29, options imply about +/-11%), the four refiners/E&Ps (VLO Oct 22, PBF Oct 29, CHRD Nov 3, APA Nov 4/5), and ILMN (Oct 29). Many companies had not confirmed dates when Yahoo was queried (unmarked dates), so treat +/-1 day as possible (CTSH was listed as Oct 28 or 29 by different sources; SNDK was listed by one aggregator as Nov 5, but the company confirmed Oct 29).

## 9. Compliance and liquidity

- **Listing**: all 48 are common stock quoted as EQUITY on NYSE (NYQ) or Nasdaq (NMS) per Yahoo; none is an ADR or OTC. Non-US domiciles with US-listed common shares: ACN (Ireland), PNR (Ireland, London HQ), G (Bermuda), VAL (Bermuda, blocked). These are ordinary shares and should be tradable, but confirm each ticker resolves in WInS before the session (HON now trades as Honeywell Technologies while the spun-off Aerospace company is HONA; single-letter tickers G and IT need an exact match).
- **Price floor ($5)**: lowest price in the union is GAP at $23.12; the next are GEN $24.16, HPQ $30.01, G $37.26. All pass with wide margin.
- **Volume (30-day average)**: thinnest dollar volume MMS $42M (748k shares), SAIC $56M (432k), G $65M, TTEK $71M; thinnest share volume SNA 290k, SAIC 432k, CHRD 687k, THC 694k. A $8,000 order is at most 0.019% of average dollar volume (MMS) and 0.0002x average share volume for any name, i.e. the 2x-volume rule is irrelevant at this size. The only practical caveat is that WInS compares the order with the day's actual volume (WInS user guide cited in `research/07_competition_rules.md`), so avoid orders entered in the first minutes of trading for very large tickets; at $1,000-$8,000 even the first minute is enough.
- **Whole-share lots**: MU ($879) and SNDK ($1,299) are each above a $1,000 ticket, so the minimum order is one share; at the MF weight of 4% of $300k ($12,000) they are 13 and 9 shares.
- **Trade count**: removing the 4 blocked names leaves 44 names, well inside the 200-trade cap even with sells.

## 10. Concentration and overlap (earlier 48-name list; the final union is in section 13)

| Sector (GICS in our files) | QM (10) | MF (25) | TC (19) | Union (48) | Union after removing blocks (44) |
|---|---|---|---|---|---|
| Information Technology | 0 | 9 | 4 | 12 | 11 |
| Health Care | 1 | 4 | 5 | 10 | 9 |
| Industrials | 0 | 6 | 6 | 10 | 9 |
| Consumer Discretionary | 2 | 5 | 4 | 8 | 8 |
| Energy | 5 | 0 | 0 | 5 | 4 |
| Materials | 2 | 0 | 0 | 2 | 2 |
| Consumer Staples | 0 | 1 | 0 | 1 | 1 |

- **QM**: 5 Energy (PBF, VLO, APA, CHRD, VAL) = 50% of the sleeve; their 6-month average pairwise correlation is 0.55 versus 0.13 for the sleeve overall, so this is effectively one commodity bet (refining/oil-price regime). Two Materials (NUE, STLD: both steel, report Oct 26 / Oct 19). Dropping VAL leaves 4 of 9 (44%).
- **MF**: 9 IT (GEN, ADBE, GDDY, ACN, MU, IT, SNDK, CTSH, HPQ), with MU and SNDK correlated 0.85 and both in drawdown; GEN and GDDY are linked by the takeover rumour. 6 Industrials, 5 Consumer Discretionary, 4 Health Care.
- **TC**: 6 Industrials, 5 Health Care (UHS, THC, GEHC, BSX, EHC), 4 Consumer Discretionary, 4 IT.
- **Overlaps**: ANF is in QM (10%) and MF (4%): combined 14% of sleeve weight in one name that sits at its 52-week high with RSI 69.6. MF and TC share five names: BAH, BKNG, G, GEN, HRB (each is 4% in MF and 5.3% in TC). No QM/TC overlap. If the three sleeves are equally weighted, the five MF/TC overlaps each carry about 3-4% of the total portfolio.
- **Missing exposures** (relevant to the IPS diversification narrative, not to data quality): no Financials, Utilities, Real Estate or Communication Services; Consumer Staples only via MO.

## 11. Suggested actions before Wednesday

1. Remove PTC, VAL, HON, SOLV (and re-normalise the sleeves: QM 9 names, MF 23, TC 18). The files list next-ranked alternates (QM rank 11 CF; MF ALT rows PNR, OTIS, THC, INTU; TC has no further BUY names: its near-misses failed the quality/leverage gates). The alternates are audited in section 12.
2. Decide on BSX (wait for the Oct 28 outlook, or size down), GEN/GDDY (event risk; hold both or neither), and SNDK/MU (a momentum crash in progress; SNDK fails the QM RSI screen).
3. Cap the Energy cluster (e.g. 3 names or 30% of the QM sleeve) and avoid the ANF double count.
4. Re-run the QM SMA/RSI screen and the TC discount on the Oct 20 close (STLD reported Oct 19 after close, MLI Oct 20 before open, and APA/ANF RSI are within 0.5 of the cap).
5. Record the Trading Note for each trade at the time of the order (Trading Notes Analysis is due Oct 23).

## 12. Replacements (added at the lead's request, same checks as the main list)

Candidates: QM next eligible CF (rank 11) and backup RS (rank 12) for VAL; MF alternates PNR (ALT 26), OTIS (27), INTU (29) for HON and SOLV; THC (ALT 28) is already a TC pick (audited above: OK), so adding it to MF would hold it in two sleeves. All five names trade on NYSE/Nasdaq as ordinary shares, our prices equal the Yahoo 10-16 close, no merger/spin-off/delisting/restatement forms exist in EDGAR since 2026-06-01, and the lowest price is $53.44 (PNR). An $8,000 order is at most 0.008% of average dollar volume for each.

| Ticker | Role | Status | Reason | Next earnings | ADV30 ($M) |
|---|---|---|---|---|---|
| CF | QM next eligible (rank 11) | **CAUTION** | Clean data and no deal/spin, but the swap does not diversify the oil-shock bet: 6-month correlation 0.47 with the QM energy names (fertilizer tied to Hormuz/Iran-ceasefire news; -10% on the April ceasefire), and the screen margin is thin (RSI 52.5 vs 50 floor, +5.6% above SMA200). Q2 EPS missed consensus ($4.73 vs $5.65). 12-1 momentum +59.9%. | 2026-11-04 AMC* | 321 |
| RS | QM backup (rank 12) | **OK** | Clean: all QM inputs reproduce exactly, NI $894M = Yahoo, no deal/spin/one-off. Notes: third steel-linked name (0.79 correlation with NUE/STLD) and it reports 2026-10-21 AFTER close, i.e. the evening of the trade; thinnest share volume of the whole set (264k/day, $104M) but an $8k order is 0.008% of that. | 2026-10-21 AMC* | 104 |
| PNR | MF alternate (ALT rank 26) | **CAUTION** | Not a clean MF replacement: profit warning 2026-07-15 (2026 adj. EPS guide $4.60-4.80 vs $5.30-5.40, sales -4% to -7%, pool destocking), CFO left, securities class-action solicitations; TTM EBIT $813M overstates run-rate (Q2 operating income $166M, -24% y/y; annualised EY ~6.5% vs 8.0% in file). It is already a TC pick, so it would be held in both sleeves. Data otherwise reconcile (EV -0.5%, EBIT -5.6%; snap:shares_stale flag moves mcap only +1.3% vs Yahoo). | 2026-10-27 BMO | 146 |
| OTIS | MF alternate (ALT rank 27) | **OK** | Clean: mcap equals Yahoo, EBIT $2.289B vs Yahoo TTM operating income $2.375B (-3.6%), EV +1.1%, no review flags, NI = normalised income (no one-off), no deal or spin-off found. Notes: FY26 EPS/FCF guide lowered 2026-07-22; CEO Marks retiring on a successor search (8-K 2026-09-15). Earnings 2026-10-28 before open. | 2026-10-28 BMO* | 327 |
| INTU | MF alternate (ALT rank 29; THC at 28 is already a TC pick) | **OK** | Clean: mcap equals Yahoo, EBIT $5.88B vs Yahoo $6.18B (-4.7%), EV +2.0%; fiscal Q4 (2026-07-31) is in. Q4 carries -$397M unusual items (EBIT understated if anything), no gains. No deal found. Notes: -52% from high (software/AI de-rating; -20% on 05-21, -10% on 08-25 FY27 guide), 0.72 correlation with ADBE, would be the 10th IT name in MF. | 2026-11-19 AMC | 1,113 |

Reconciliation (fresh Yahoo vs our files):

| Ticker | Check | Ours | Fresh / Yahoo | Diff |
|---|---|---|---|---|
| CF | 12-1 mom / SMA200 / RSI14 | 0.5987 / 114.42 / 52.49 | 0.5987 / 114.42 / 52.49 | exact; passes SMA200 (+5.6%) and RSI 50-70 |
| RS | 12-1 mom / SMA200 / RSI14 | 0.4907 / 362.61 / 61.55 | 0.4907 / 362.61 / 61.55 | exact; passes SMA200 (+13.4%) and RSI 50-70 |
| PNR | market cap ($B) | 8.64 | 8.53 | +1.3% |
| PNR | EBIT ($B) | 0.81 | 0.86 (TTM operating income) | -5.6% |
| PNR | EV ($B) / EY | 10.2 / 8.0% | 10.2 / 8.4% | -0.5% |
| OTIS | market cap ($B) | 27.15 | 27.15 | -0.0% |
| OTIS | EBIT ($B) | 2.29 | 2.38 (TTM operating income) | -3.6% |
| OTIS | EV ($B) / EY | 35.9 / 6.4% | 35.5 / 6.7% | +1.1% |
| INTU | market cap ($B) | 86.89 | 86.89 | +0.0% |
| INTU | EBIT ($B) | 5.88 | 6.18 (TTM operating income) | -4.7% |
| INTU | EV ($B) / EY | 89.9 / 6.5% | 88.1 / 7.0% | +2.0% |

Net income TTM vs Yahoo: CF $2.099B (file) = $2.099B; RS $0.894B = $0.894B. Yahoo normalised income vs NI: CF 2.01 vs 2.10, RS 0.89 vs 0.89, PNR 0.68 vs 0.65, OTIS 1.52 vs 1.52, INTU 4.78 vs 4.57 (unusual charges), so none contains a one-off gain. Earnings dates marked * are company-confirmed (RS and CF press releases, Otis advisory).

Recommendation: CF is usable but note the energy-regime correlation (0.47) and the thin RSI margin; RS is a clean backup (though a third steel name, correlation 0.79 with NUE/STLD, reporting the evening of Oct 21). For MF prefer OTIS and INTU over PNR: PNR was also downgraded to CAUTION in its TC role because of the July profit warning. INTU adds a tenth IT name (correlation 0.72 with ADBE); OTIS adds a sixth Industrial.

## 13. Final trading-comps list (theta 0.10, P/E cap 40, EV/EBITDA cap 35, size filter off; 20 names at 5% each)

Re-run on 2026-10-19 (signals still as of the 2026-10-16 close; the latest available close is still 2026-10-16). For each name: price and market cap vs Yahoo, our P/E and EV/EBITDA vs Yahoo, one-off gains in TTM NI/EBITDA (TTM NI vs Yahoo `Normalized Income`), pending deals/spin-offs (EDGAR forms and 8-Ks since 2026-06-01 plus web search), earnings date and compliance. Peer-median arithmetic was verified for all 40 benchmarks (median of the non-trimmed peers reproduces `pe_bench` and `ev_bench` to rounding), and the 147 peer multiples were compared with Yahoo: P/E agrees (115 of 116 within 25%, median difference 1.9%; only HL, +55%), EV/EBITDA agrees for 117 of 128 (median 4%) with the exceptions concentrated in pharma/biotech peers (JAZZ, PFE, ELAN, VTRS, BIIB: file multiples about 2x Yahoo's), SMCI, ST, KR, ON, GHC.

| Ticker | Also in | TC-role status | Reason | Next earnings | ADV30 ($M) |
|---|---|---|---|---|---|
| SON | - | **BLOCK** | DATA ERROR: TTM NI ($628M) and EBITDA ($1.56B) include the ~$0.38B gain on the sale of ThermoSafe (Q4-25; closed 2025-11-03). Clean figures: P/E ~11.8x (not 7.8x), EV/EBITDA ~7.4-7.9x (not 5.9x), and net debt/EBITDA ~3.5-3.7x (not 2.8x) which FAILS the 3.0x leverage gate (nd_max = 3.0 in quant/signals/key_metrics.py); the EV/EBITDA discount shrinks to 8-13% vs the 10% theta. Company itself cites net leverage of about 3.0x. Also reports 2026-10-21 after close (evening of the fills). | 2026-10-21 AMC* (in window) | 55 |
| GAP | - | **CAUTION** | TC discount is partly definitional: EV/EBITDA 3.2x (ours, ex-leases, EBITDA $2.2B) vs Yahoo 7.7x (EV incl. ~$4B leases/other); the 76% P/E discount is against off-price retailers (BURL, ROST, TJX at 23-28x); TTM P/E 6.5x vs forward 8.8x means forward EPS ~21% below TTM. Earnings 2026-11-19 (outside window). | 2026-11-19 AMC | 135 |
| PNR | - | **CAUTION** | Profit warning 2026-07-15 (2026 adj. EPS guide $4.60-4.80 from $5.30-5.40, sales -4% to -7%, pool destocking), CFO left, class-action solicitations; Q2 operating income -24% y/y so TTM understates the decline; stock -52% from high. Reports 2026-10-27 before open. | 2026-10-27 BMO (in window) | 146 |
| ZTS | - | **CAUTION** | EV/EBITDA discount leg is not reliable: four of seven EV peers carry file multiples about double Yahoo's (VTRS 12.5x vs 7.8x, JAZZ 17.1x vs 8.2x, ELAN 28.8x vs 15.4x, PFE 16.6x vs 8.7x), so the benchmark is 17.1x in the file but about 8.7x on Yahoo peer multiples, which turns ZTS (10.0x) from a 41% discount into a ~15% premium; the P/E leg survives (benchmark 21.9x file, 26.6x Yahoo). Also guidance cut and de-rating: Q1 miss and 2026 outlook cut on 2026-05-07 (-21.5% that day), Librela FDA safety scrutiny, US companion-animal sales -11%; stock -46% from high, -44% in 12m; law-firm class-action solicitations; reports 2026-11-05 before open (company-confirmed). Data reconcile (P/E -5%, EV/EBITDA +1%); peer P/E median 21.9x includes PFE 38.9x and JNJ 29.3x, so the 43% discount is overstated. | 2026-11-05 BMO* (in window) | 331 |
| MU | MF | **CAUTION** | Data reconcile exactly (P/E 11.7x, EV/EBITDA 8.8x) but price $878.84 is -28% from the 2026-06-25 high, -20% since 10-01; RSI 34; 0.85 correlation with SNDK (MF); also an MF pick (MF 4% + TC 5% = 9% of sleeves in one name); MU and CRUS appear in each other's peer sets. FQ4 already reported; next earnings 2026-12-23. | 2026-12-23 AMC | 27,000 |
| SFM | - | **CAUTION** | Earnings risk inside the window: Q3 EPS guide $1.20-1.24 vs ~$1.30 consensus, comparable sales -1% in Q2, Melius downgrade to Sell; CEO succession (Konat from 2027-01-04), CTO left 2026-10-12; stock -42% from high. Reports 2026-10-28 after close (company-confirmed). Reconciliation: P/E -3%, EV/EBITDA -26% vs Yahoo because ours excludes ~$2.1B of leases (same convention as GAP/ANF). Peer set (grocers/discounters incl. KR 34.7x, CASY 33.0x) gives a 22.4x benchmark. | 2026-10-28 AMC* (in window) | 146 |
| GEN | MF | **CAUTION** | FT (2026-09-24): Gen approached GoDaddy; GEN -12% that day, -20% in 1m; reports 2026-10-28 after close (deal news possible). Also an MF pick (MF 4% + TC 5%). EV benchmark 18.1x equals PTC (deal-pinned), but excluding PTC the median would be higher (19.2x), so no inflation of the discount. Yahoo forward P/E 7.3x is non-GAAP. | 2026-10-28 AMC* (in window) | 269 |
| KBR | - | **CAUTION** | Pending spin-off of Mission Technology Solutions (Trinzic, NYSE: TZIC), targeted 2027-01-04 (outside the window, but afterwards consolidated TTM EBITDA/EPS will no longer describe the remaining company); benchmark peers are unrelated (waste, auctions, pest control: RBA, ROL, CLH, RSG, WM, CPRT; P/E median 27.6x vs government-services names SAIC 14.7x, BAH 11.5x), so the 61% P/E discount is overstated. Yahoo EV/EBITDA 10.5x vs ours 7.6x because Yahoo `ebitda` ($0.67B) is below its own quarterly sum ($0.90B); ours reconciles with the quarterly statements. Earnings 2026-10-29 before open. | 2026-10-29 BMO* (in window) | 53 |
| AA | - | **CAUTION** | Pending acquirer: $4.1B purchase of South32 bauxite/alumina/smelter assets ($3.1B cash + ~17M shares, closing H1 2027, funded by $2.6B of new notes issued 2026-09-23) will lift net debt from ~$0.4B; TTM NI/EBITDA include net +$0.27B unusual gains (normalised P/E ~10.2x not 8.6x, EV/EBITDA ~6.9x not 6.0x; discounts still 55% / 42%); file is one quarter stale (Q3 reported 2026-10-15, Yahoo P/E already 7.2x); peers are gold/copper/steel miners (HL, RS, STLD, NUE, FCX, NEM), not aluminium; -50% from 52w high; aluminium price falling (Q3 $4,527/t vs $4,752). | 2027-01-21 AMC | 197 |
| ANF | QM/MF | **CAUTION** | Now in all three sleeves: QM 10% + MF 4% + TC 5%; RSI 69.57 is 0.43 below the QM cap; +35.7% on 2026-08-26; at 52w high. P/E -8% and EV/EBITDA -16% vs Yahoo (leases excluded in ours). Peers (BURL, ROST, TJX; GAP trimmed) give a 26.7x P/E benchmark. Earnings 2026-11-25 (outside window). | 2026-11-25 BMO | 188 |
| MMS | - | **CAUTION** | Fundamentals deteriorating despite cheap multiples: FY26 EPS guide cut (VA contract incentive pause), DSO 98 days, Q3 FCF -$137M, TTM book-to-bill 0.5; lowest dollar liquidity in the final list ($42M ADV). Peer set is 13 broad data/outsourcing names (median 26.0x). Earnings 2026-11-19 (outside window). | 2026-11-19 BMO | 42 |
| HRB | MF | **OK** | Data reconcile (P/E -4%, EV/EBITDA -11%); also an MF pick (MF 4% + TC 5%); annual meeting 2026-11-10; earnings 2026-11-05 after close. | 2026-11-05 AMC (in window) | 87 |
| UHS | - | **OK** | Data match Yahoo (P/E -5%, EV/EBITDA -1%). Standing legal risk: Nevada $500M punitive verdict (new trial granted 2026-02-25). Earnings 2026-10-27 after close. | 2026-10-27 AMC (in window) | 125 |
| ENS | - | **OK** | Price/mcap/P-E/EV-EBITDA reconcile (P/E -4%, EV/EBITDA +1%); NI has small net charges (normalised $0.41B vs $0.35B), no deal/spin. Notes: benchmark is seven high-multiple automation/electrification names (median 35.1x P/E, 21.3x EV/EBITDA), so the 51% discount mostly reflects lower quality; July strategic review scaled the Greenville lithium-cell plant down to ~1 GWh with a revised DOE grant; -31% from high. Earnings 2026-11-04 after close (Yahoo, unconfirmed). | 2026-11-04 AMC (in window) | 99 |
| BAH | MF | **OK** | Data match Yahoo; closed $720M Ultra Electronics ATS acquisition 2026-08-24; also an MF pick (MF 4% + TC 5%). Earnings 2026-10-23 before open. | 2026-10-23 BMO (in window) | 125 |
| THC | - | **OK** | Data match Yahoo (P/E -9%, EV/EBITDA -11%); normalised income ~ NI (no one-off gain); forward P/E 12.7x vs TTM 9.6x implies forward EPS ~24% lower. Earnings 2026-10-29 before open. | 2026-10-29 BMO (in window) | 182 |
| INCY | MF | **OK** | Data reconcile (P/E -2%, EV/EBITDA +5.5%); no debt (net cash); CMS/Medicaid Jakafi price agreement (8-K 2026-08-31) is a policy overhang; ESMO data 2026-10-24; also an MF pick (MF 4% + TC 5%). Earnings 2026-10-29 before open. | 2026-10-29 BMO* (in window) | 201 |
| HPQ | MF | **OK** | Data reconcile (P/E -3.6%, EV/EBITDA +7.7% vs Yahoo); TTM NI has net unusual charges (normalised $3.04B, so P/E on clean earnings is ~8.9x). Peer set includes AAPL ($5T, 38.9x) and SNDK but the median barely moves without AAPL (25.8x vs 26.2x). Interim CEO since February, -13% in 1m. Also an MF pick (MF 4% + TC 5%). Earnings 2026-11-24 (outside window). | 2026-11-24 AMC | 473 |
| G | MF | **OK** | Data reconcile (P/E -3%, EV/EBITDA -2%); also an MF pick; 2026-11-10 shareholder vote on Bermuda-to-Delaware domestication, no deal; new CFO. Earnings 2026-11-05 after close. | 2026-11-05 AMC (in window) | 65 |
| CRUS | - | **OK** | Reconciles (P/E -4%, EV/EBITDA -1%); NI = normalised income; TTM covers a full seasonal cycle (June-quarter revenue is the trough: record $460M, Sept-quarter guide $510-570M), so the TTM P/E is not flattered. Notes: Apple concentration; 2026-10-13 8-K confirms it was "Party A" bidding for Synaptics but is not pursuing it; bought Inventvm (small) 2026-10-06; MU is in its peer set and vice versa; -40% from high. Earnings 2026-11-04 after close (company-confirmed). | 2026-11-04 AMC* (in window) | 99 |

Earnings dates marked * are company-confirmed. AA already reported Q3 on 2026-10-15 (file TTM is the June quarter).

### Reconciliation with Yahoo (final list)

| Ticker | Price (file = Yahoo 10-16) | Mcap ours / Yahoo ($B) | P/E ours / Yahoo / diff | EV/EBITDA ours / Yahoo / diff | NI / normalised income | P/E disc vs file peers | EV/EBITDA disc vs file peers |
|---|---|---|---|---|---|---|---|
| GAP | 23.12 | 8.12 / 8.12 (-0.0%) | 6.5 / 7.0 / -6% | 3.2 / 7.7 / -58% | 1.25 / 1.25 (1.00x) | 76% | 81% |
| HPQ | 30.01 | 27.06 / 27.06 (+0.0%) | 11.0 / 11.5 / -4% | 7.7 / 7.2 / +8% | 2.45 / 3.04 (0.81x) | 58% | 60% |
| MMS | 61.47 | 3.22 / 3.22 (+0.0%) | 8.7 / 9.1 / -5% | 7.6 / 7.1 / +8% | 0.37 / 0.37 (1.00x) | 67% | 51% |
| ANF | 153.26 | 6.50 / 6.50 (+0.0%) | 12.1 / 13.2 / -8% | 6.6 / 7.8 / -16% | 0.54 / 0.54 (1.00x) | 55% | 61% |
| AA | 41.45 | 10.94 / 10.94 (-0.0%) | 8.6 / 7.2 / +19% | 6.0 / 4.0 / +50% | 1.28 / 1.07 (1.19x) | 62% | 50% |
| UHS | 185.10 | 11.09 / 10.91 (+1.7%) | 7.3 / 7.6 / -5% | 6.0 / 6.0 / -1% | 1.53 / 1.53 (1.00x) | 66% | 44% |
| HRB | 48.67 | 6.00 / 5.96 (+0.6%) | 8.2 / 8.6 / -4% | 6.2 / 6.9 / -11% | 0.73 / 0.74 (1.00x) | 55% | 54% |
| G | 37.26 | 6.26 / 6.23 (+0.5%) | 10.7 / 11.1 / -3% | 8.0 / 8.1 / -2% | 0.58 / 0.58 (1.01x) | 59% | 49% |
| GEN | 24.16 | 14.46 / 14.46 (+0.0%) | 13.7 / 14.1 / -3% | 8.4 / 9.2 / -8% | 1.05 / 1.14 (0.92x) | 54% | 53% |
| KBR | 36.38 | 4.59 / 4.59 (+0.0%) | 10.8 / 10.9 / -1% | 7.6 / 10.5 / -28% | 0.42 / 0.45 (0.95x) | 61% | 40% |
| ENS | 168.72 | 6.08 / 6.08 (+0.0%) | 17.3 / 18.1 / -4% | 10.8 / 10.7 / +1% | 0.35 / 0.40 (0.87x) | 51% | 49% |
| BAH | 74.26 | 8.93 / 8.93 (+0.0%) | 11.5 / 11.7 / -2% | 10.1 / 10.0 / +1% | 0.78 / 0.78 (1.00x) | 59% | 34% |
| THC | 267.25 | 21.52 / 21.52 (+0.0%) | 9.6 / 10.5 / -9% | 6.7 / 7.6 / -11% | 2.24 / 2.37 (0.94x) | 55% | 37% |
| SFM | 65.20 | 6.08 / 6.08 (-0.0%) | 12.1 / 12.5 / -3% | 7.0 / 9.5 / -26% | 0.50 / 0.51 (0.99x) | 46% | 44% |
| INCY | 113.07 | 22.72 / 22.92 (-0.8%) | 14.1 / 14.4 / -2% | 10.0 / 9.5 / +5% | 1.61 / 1.63 (0.99x) | 39% | 51% |
| MU | 878.84 | 994.34 / 994.34 (-0.0%) | 11.7 / 11.8 / -1% | 8.8 / 8.8 / +0% | 50.47 / 50.47 (1.00x) | 37% | 50% |
| ZTS | 79.38 | 32.80 / 32.80 (-0.0%) | 12.4 / 13.1 / -5% | 10.0 / 9.9 / +1% | 2.62 / 2.74 (0.96x) | 43% | 41% |
| PNR | 53.44 | 8.64 / 8.53 (+1.3%) | 13.3 / 13.8 / -4% | 10.9 / 9.9 / +10% | 0.65 / 0.68 (0.96x) | 48% | 37% |
| SON | 49.79 | 4.92 / 4.92 (-0.0%) | 7.8 / 7.7 / +2% | 5.9 / 7.6 / -22% | 0.63 / 0.42 (1.50x) | 53% | 30% |
| CRUS | 107.87 | 5.41 / 5.41 (+0.0%) | 12.6 / 13.1 / -4% | 8.8 / 8.9 / -1% | 0.43 / 0.43 (1.00x) | 33% | 51% |

All 20 prices equal the Yahoo 2026-10-16 close to the cent and no market cap differs from Yahoo by more than 1.7% (UHS). EV/EBITDA gaps of 25% or more: GAP (-58%), KBR (-28%), SFM (-26%) and AA (+50%). GAP and SFM exclude operating leases from EV (Yahoo includes ~$4B and ~$2.1B); KBR is Yahoo's own `ebitda` field disagreeing with its quarterly statements (Yahoo `ebitda` $0.67B vs quarterly sum $0.90B; ours matches the quarterly sum). SON's -22% is the ThermoSafe gain (Yahoo's `ebitda` excludes it; see below). AA (+50%) is a staleness/definition gap: Yahoo's P/E (7.2x) already includes Q3 reported 2026-10-15, and its `ebitda` ($2.86B) is inconsistent with its own quarterly EBITDA ($1.99B).

### The two TTM one-off distortions (the 'known issue')

| Ticker | As in file | Clean basis | Effect |
|---|---|---|---|
| SON | P/E 7.8x, EV/EBITDA 5.9x, ND/EBITDA 2.78x (EBITDA $1.56B incl. ThermoSafe gain; Yahoo Q4-25 EBITDA $651M = operating income $134M + D&A ~$135M + ~$381M gain) | P/E ~11.8x (normalised NI $0.417B), EV/EBITDA ~7.4-7.9x, ND/EBITDA ~3.5-3.7x | Fails the 3.0x leverage gate and the EV/EBITDA discount falls to 8-13% (theta 10%): **would not have been selected**. BLOCK. |
| AA | P/E 8.6x, EV/EBITDA 6.0x (NI $1.28B, EBITDA $1.99B incl. net +$0.27B unusual items) | P/E ~10.2x, EV/EBITDA ~6.9x | Discounts stay large (55% P/E, 42% EV/EBITDA), so still selected; CAUTION for the pending South32 acquisition and a mismatched peer set. |

### Robustness of the peer benchmarks (recomputed with Yahoo multiples for the peers)

Only ZTS changes qualitatively: its EV/EBITDA benchmark falls from 17.1x to 8.7x because four of its seven EV peers are about 2x higher in the file than on Yahoo (VTRS, JAZZ, ELAN, PFE), turning a 41% discount into a ~15% premium; the P/E leg is unaffected (benchmark 21.9x file vs 26.6x Yahoo). INCY (EV discount 51% to 38%), MU/CRUS (50% to 40%), HRB (54% to 44%) and KBR (40% to 34%) shrink but stay above theta. Peer-set quality is a general caveat: most benchmarks are broad GICS groups (e.g. KBR vs waste/auction/pest-control names, AA vs gold/copper/steel miners, GAP/ANF vs off-price retailers, HPQ vs AAPL/DELL/HPE, ENS vs high-multiple electrification names), so discounts of 50-75% are largely sector-mix effects. GEN's EV benchmark (18.1x) equals PTC's deal-pinned multiple, but removing PTC would raise the median to 19.2x, so it does not inflate the discount. MU and CRUS appear in each other's peer sets.

### Re-check of names audited earlier that now also appear in TC

- **HPQ (MF + TC): OK.** Reconciles (P/E -3.6%, EV/EBITDA +7.7%); NI includes net unusual charges, so clean earnings make it cheaper (P/E ~8.9x); AAPL in the peer set does not matter (median 25.8x without it); earnings Nov 24, outside the window.
- **ANF (QM + MF + TC): CAUTION.** Now in all three sleeves (10% + 4% + 5%): with equal sleeves that is about 6.3% of the portfolio; RSI 69.57, at its 52-week high; TC P/E -8% and EV/EBITDA -16% vs Yahoo (lease convention).
- **INCY (MF + TC): OK.** Reconciles (P/E -2%, EV/EBITDA +5.5%), net cash, ESMO data Oct 24, earnings Oct 29; the CMS/Jakafi price agreement is a policy overhang. Its EV benchmark shrinks from 20.3x to 16.0x on Yahoo peers (BIIB), discount 51% to 38%.
- **MU (MF + TC): CAUTION.** Reconciles exactly, but -28% from its high, correlation 0.85 with SNDK; 9% of sleeve weight in one name; MU, SNDK and CRUS now form a 3-name semiconductor cluster (MU-CRUS 0.32, SNDK-CRUS 0.26).
- Unchanged: GAP CAUTION, MMS CAUTION, GEN CAUTION (GDDY approach, earnings Oct 28), PNR CAUTION (July profit warning), UHS/HRB/G/BAH/THC OK. PNR, UHS and THC have no other-sleeve overlap.

### Compliance and liquidity (final list)

All 20 are common stock on NYSE (AA, KBR, ENS, ZTS, SON, GAP, HPQ, MMS, ANF, UHS, HRB, G, THC, PNR, BAH) or Nasdaq (SFM, CRUS, GEN, INCY, MU); none is an ADR or OTC, all are US-domiciled per Yahoo except PNR (Irish plc, London HQ). Lowest price is GAP at $23.12. Thinnest dollar volume: MMS $42M, KBR $53M, SON $55M, G $65M; thinnest share volume ENS 552k/day. An $8,000 order is at most 0.02% of average dollar volume, so the 2x-volume rule does not bind.

### Final union (46 names): status, concentration, overlaps, earnings

- **Status**: 24 OK, 18 CAUTION, 4 BLOCK. BLOCK: HON, SOLV, VAL, SON. CAUTION: GEN, GDDY, SNDK, MU, PBF, VLO, APA, CHRD, ANF, STLD, ILMN, GAP, MMS, AA, KBR, SFM, ZTS, PNR.
- **Sectors** (GICS in our files), union of 46: Industrials 10, Information Technology 10, Health Care 8, Consumer Discretionary 7, Energy 5, Materials 4, Consumer Staples 2; after removing the 4 blocks (42): Information Technology 10, Industrials 9, Consumer Discretionary 7, Health Care 7, Energy 4, Materials 3, Consumer Staples 2. Final TC sleeve alone: Industrials 6 (MMS, G, KBR, ENS, BAH, PNR), Health Care 4 (UHS, THC, INCY, ZTS), Consumer Discretionary 3 (GAP, ANF, HRB), IT 4 (HPQ, GEN, MU, CRUS), Materials 2 (AA, SON), Consumer Staples 1 (SFM). Average pairwise 6-month correlation of the 20 TC names is only 0.09 (UHS-THC 0.64, GAP-ANF 0.50, MMS/G/BAH 0.52-0.56).
- **Overlaps**: MF and TC now share eight names (HPQ, ANF, G, GEN, BAH, HRB, INCY, MU); ANF is in QM, MF and TC; no other QM/TC overlap. If the three sleeves are equally sized, ANF is about 6.3% of the portfolio, MU 3.0%, and the other MF/TC overlaps about 3%.
- **Clusters**: energy (QM: PBF, VLO, APA, CHRD; correlation 0.55) and semiconductors/memory (MU, SNDK, CRUS). Materials now has four names (NUE, STLD, AA, SON), of which AA and SON are blocked/cautioned.
- **Earnings between Oct 21 and Nov 6 (35 of 46 names)**: 2026-10-21: SON (AMC); 2026-10-22: HON (BMO), VLO (BMO); 2026-10-23: BAH (BMO); 2026-10-26: NUE (AMC); 2026-10-27: UHS (AMC), PNR (BMO); 2026-10-28: GEN (AMC), SFM (AMC); 2026-10-29: GDDY (AMC), SNDK (AMC), ILMN (AMC), PBF (BMO), BMY (BMO), CROX (BMO), CTSH (BMO), INCY (BMO), MO (BMO), KBR (BMO), THC (BMO); 2026-11-02: VAL (AMC); 2026-11-03: CHRD (AMC), BKNG (AMC), IT (BMO), LDOS (BMO); 2026-11-04: APA (AMC), ENS (AMC), CRUS (AMC), SN (BMO); 2026-11-05: SOLV (AMC), G (AMC), HRB (AMC), CI (BMO), TPR (BMO), ZTS (BMO). New in the TC list: SON Oct 21 AMC (evening of the fills), SFM Oct 28 AMC, KBR Oct 29 BMO, ENS Nov 4 AMC, CRUS Nov 4 AMC, ZTS Nov 5 BMO. Outside the window in the TC list: GAP Nov 19, MMS Nov 19, HPQ Nov 24, ANF Nov 25, MU Dec 23; AA reported Oct 15.
- **After removing the 4 blocks** the TC sleeve has 19 names (5.26% each if equal-weighted), the QM sleeve 9 (CF/RS replacement per section 12) and the MF sleeve 23 (OTIS/INTU per section 12).

## 14. Method and limitations

- Prices and history: `yfinance` 1.7.0, 3-year daily, `auto_adjust=False` (Close split-adjusted; Adj Close total-return adjusted). 12-1 momentum = Adj Close[t-21]/Adj Close[t-252] - 1 on the common trading calendar; SMA200 on Close; Wilder RSI(14) seeded with the simple average of the first 14 changes. **Our prices come from Yahoo too, so equality with Yahoo is a consistency check, not independent verification**; independent confirmation came from SEC filings (BKNG split, BSX incident, PTC/VAL/HON events) and third-party quotes that matched Yahoo's closes exactly (MU 10-15, SNDK 10-01). Stooq, the other free source tried, blocks scripted requests, and no bot-detection was bypassed.
- Fundamentals: Yahoo `info` (marketCap, enterpriseValue, ebitda, trailingPE, forwardPE, enterpriseToEbitda) and `quarterly_income_stmt` (TTM = sum of last four quarters). Yahoo's quarterly data lags by a quarter for fiscal-year-offset companies (ACN, MU).
- Corporate events: SEC EDGAR submissions API for all 48 CIKs (all 8-K items, S-4, DEFM14A, SC TO, Form 25/15 since 2026-06-01), 8-K bodies read for items 1.01, 1.05, 2.01, 2.05, 5.02, 7.01, 8.01 where the title was not self-explanatory, and web search for press coverage. Search summaries are secondary; the key claims (PTC, VAL, HON, BSX, G) were confirmed against SEC documents. For SOLV the Sept-2025 divestiture of Purification & Filtration is confirmed in the June-2026 10-Q, while the $1.518B gain amount and the $525M operating income come from Yahoo's quarterly income statement (not re-derived from the 10-K).
- Not checked: WInS ticker availability (needs login), real-time pre-market quotes, options-implied moves other than SNDK's, and litigation beyond the items listed.
