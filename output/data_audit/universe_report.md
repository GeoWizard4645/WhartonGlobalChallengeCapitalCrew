# Point-in-time S&P 1500 universe: build report

Generated 2026-10-19 by `quant/data/universe.py` (`build_all`). Products in `cache/universe/`: `membership.parquet`, `gics.parquet`, `security_master.parquet`, `us_all.parquet`, `price_tickers.txt`, `snapshots_meta.parquet`, `cik_aliases.csv`; raw Wikipedia/GitHub responses in `wiki/`, `fja05680/`.

## 1. Headline

- Distinct companies that were in the S&P 500, 400 or 600 at any snapshot since 2010: **2450** (2421 distinct CIKs + 29 unmapped tickers).
- Of the 2451 security-master rows with `ever_sp1500`, **759 (31.0%) are no longer listed/filing today** (survivorship exposure: their prices are mostly unavailable on Yahoo, see section 7).
- Wikipedia revisions used: 166 usable of 207 (index, quarter) snapshots; US_ALL: 4011 companies; `price_tickers.txt`: 4648 tickers.

Index sizes at quarter-ends (`members(date, dedupe=False)`):

| date | SP500 | SP400 | SP600 | total_unique_cik |
|---|---|---|---|---|
| 2010-03-31 | 504 | 0 | 0 | 502 |
| 2010-09-30 | 501 | 0 | 0 | 500 |
| 2011-03-31 | 501 | 400 | 0 | 896 |
| 2011-09-30 | 501 | 400 | 0 | 894 |
| 2012-03-31 | 500 | 400 | 0 | 889 |
| 2012-09-30 | 500 | 399 | 0 | 884 |
| 2013-03-31 | 500 | 399 | 0 | 878 |
| 2013-09-30 | 500 | 376 | 0 | 861 |
| 2014-03-31 | 500 | 400 | 0 | 895 |
| 2014-09-30 | 502 | 400 | 0 | 887 |
| 2015-03-31 | 503 | 400 | 0 | 880 |
| 2015-09-30 | 505 | 400 | 0 | 895 |
| 2016-03-31 | 505 | 400 | 0 | 890 |
| 2016-09-30 | 505 | 400 | 0 | 875 |
| 2017-03-31 | 505 | 400 | 0 | 899 |
| 2017-09-30 | 505 | 400 | 0 | 898 |
| 2018-03-31 | 505 | 400 | 0 | 897 |
| 2018-09-30 | 505 | 400 | 596 | 1488 |
| 2019-03-31 | 505 | 400 | 599 | 1482 |
| 2019-09-30 | 505 | 400 | 614 | 1492 |
| 2020-03-31 | 505 | 400 | 626 | 1497 |
| 2020-09-30 | 505 | 400 | 622 | 1483 |
| 2021-03-31 | 505 | 396 | 601 | 1493 |
| 2021-09-30 | 505 | 400 | 601 | 1497 |
| 2022-03-31 | 505 | 400 | 601 | 1496 |
| 2022-09-30 | 503 | 401 | 601 | 1497 |
| 2023-03-31 | 503 | 401 | 601 | 1497 |
| 2023-09-30 | 503 | 401 | 601 | 1487 |
| 2024-03-31 | 503 | 401 | 602 | 1496 |
| 2024-09-30 | 504 | 401 | 602 | 1498 |
| 2025-03-31 | 503 | 401 | 602 | 1498 |
| 2025-09-30 | 503 | 401 | 601 | 1493 |
| 2026-03-31 | 503 | 400 | 603 | 1499 |
| 2026-09-30 | 503 | 400 | 603 | 1497 |

## 2. Coverage by index and known gaps

| index | snapshots | ok | derived | fallback | missing | first_real_snapshot |
|---|---|---|---|---|---|---|
| SP500 | 69 | 69 | 0 | 0 | 0 | 2009-12-31 |
| SP400 | 69 | 64 | 0 | 1 | 4 | 2011-03-31 |
| SP600 | 69 | 24 | 9 | 2 | 34 | 2018-09-30 |

- **S&P 500**: exact daily membership (fja05680 file, tail patched from the live Wikipedia table: BE, ILMN, P, SKYD, TWLO, VYLR added and BLDR, CTVA, PSKY, TAP, TTD, WBD removed after 2026-08-18; removal dates are paired with add dates because they are not published).
- **S&P 400**: the Wikipedia page only starts in late 2010; quarters without a usable revision fall back as shown in the snapshot table (`status`).
- **S&P 600**: the page title held the combined S&P 1000 (~995 rows) until 2020-12; those snapshots are split as S&P 1000 minus the contemporaneous S&P 400 list. That list was poorly maintained after 2018: the share of rows belonging to companies that had already stopped filing grows from 0% (2018-09) to about 10% (2020; the `defunct` column; dropped by `drop_stale`, flagged `stale_listing`), so the **S&P 600 is understated (544-590 names instead of 600) from 2019 to 2020-12** and misses additions the page never recorded. There is **no Wikipedia revision before 2018**, so `members(date)` returns no S&P 600 rows before the first real snapshot above (the S&P 1500 is effectively the S&P 900 before that date).
- Sub-industry labels: Wikipedia's S&P 500 table lists only the sector until 2012-12 (and some S&P 400 rows lack them 2013-12..2015-03); missing sub-industries are back-filled from the nearest other snapshot of the same company and flagged in `gics_source` (`backfill_prev` / `backfill_next` = classification look-ahead).
- S&P 400/600 membership is quarter-end granular: a mid-quarter addition appears at the next quarter-end snapshot (never early); `stale_days` in the snapshot table shows how old each revision was.

## 3. Snapshot table

`rows` = constituent rows parsed, `GICS` = share with a sub-industry label, `CIK` = share mapped to an SEC CIK, `stale` = days between the quarter-end and the revision used, `defunct` = share of derived S&P 600 rows whose company had stopped filing (excluded by `members(drop_stale=True)`).

### SP500

| snapshot | revid | revision | rows | GICS | CIK | stale | defunct | status |
|---|---|---|---|---|---|---|---|---|
| 2009-12-31 | 335120317 | 2009-12-31 | 500 | 0.00 | 0.99 | -1.00 | 0.00 | ok |
| 2010-03-31 | 351374804 | 2010-03-22 | 499 | 0.00 | 0.99 | 8.00 | 0.00 | ok |
| 2010-06-30 | 360899452 | 2010-05-08 | 500 | 0.00 | 1.00 | 52.00 | 0.00 | ok |
| 2010-09-30 | 387239336 | 2010-09-27 | 500 | 0.00 | 1.00 | 2.00 | 0.00 | ok |
| 2010-12-31 | 401121248 | 2010-12-07 | 500 | 0.00 | 1.00 | 23.00 | 0.00 | ok |
| 2011-03-31 | 421482947 | 2011-03-30 | 500 | 0.00 | 1.00 | 0.00 | 0.00 | ok |
| 2011-06-30 | 436893107 | 2011-06-29 | 500 | 0.00 | 1.00 | 0.00 | 0.00 | ok |
| 2011-09-30 | 449094112 | 2011-09-08 | 500 | 0.00 | 1.00 | 21.00 | 0.00 | ok |
| 2011-12-31 | 468828011 | 2011-12-31 | 500 | 0.00 | 1.00 | -1.00 | 0.00 | ok |
| 2012-03-31 | 484386967 | 2012-03-28 | 500 | 0.00 | 1.00 | 2.00 | 0.00 | ok |
| 2012-06-30 | 500104048 | 2012-06-30 | 500 | 0.00 | 1.00 | -1.00 | 0.00 | ok |
| 2012-09-30 | 515161036 | 2012-09-29 | 500 | 0.00 | 1.00 | 0.00 | 0.00 | ok |
| 2012-12-31 | 530268767 | 2012-12-29 | 500 | 0.00 | 1.00 | 1.00 | 0.00 | ok |
| 2013-03-31 | 545248876 | 2013-03-18 | 500 | 1.00 | 1.00 | 12.00 | 0.00 | ok |
| 2013-06-30 | 560385556 | 2013-06-18 | 500 | 1.00 | 1.00 | 11.00 | 0.00 | ok |
| 2013-09-30 | 575022813 | 2013-09-29 | 500 | 0.99 | 1.00 | 0.00 | 0.00 | ok |
| 2013-12-31 | 588150360 | 2013-12-29 | 500 | 0.99 | 1.00 | 1.00 | 0.00 | ok |
| 2014-03-31 | 601413159 | 2014-03-26 | 500 | 1.00 | 1.00 | 4.00 | 0.00 | ok |
| 2014-06-30 | 615063327 | 2014-06-30 | 501 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2014-09-30 | 627538410 | 2014-09-29 | 502 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2014-12-31 | 640147366 | 2014-12-29 | 502 | 1.00 | 1.00 | 1.00 | 0.00 | ok |
| 2015-03-31 | 654387069 | 2015-03-31 | 502 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2015-06-30 | 669156533 | 2015-06-29 | 502 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2015-09-30 | 683545779 | 2015-09-30 | 505 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2015-12-31 | 697200065 | 2015-12-28 | 504 | 1.00 | 1.00 | 2.00 | 0.00 | ok |
| 2016-03-31 | 712739840 | 2016-03-30 | 504 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2016-06-30 | 727141812 | 2016-06-26 | 504 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2016-09-30 | 741981720 | 2016-09-30 | 505 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2016-12-31 | 757478916 | 2016-12-30 | 505 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2017-03-31 | 773052884 | 2017-03-31 | 505 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2017-06-30 | 786648328 | 2017-06-20 | 505 | 1.00 | 1.00 | 9.00 | 0.00 | ok |
| 2017-09-30 | 801637797 | 2017-09-20 | 505 | 1.00 | 1.00 | 9.00 | 0.00 | ok |
| 2017-12-31 | 816702509 | 2017-12-23 | 505 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2018-03-31 | 833052312 | 2018-03-29 | 505 | 1.00 | 1.00 | 1.00 | 0.00 | ok |
| 2018-06-30 | 848091676 | 2018-06-29 | 505 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2018-09-30 | 861235961 | 2018-09-26 | 505 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2018-12-31 | 876091698 | 2018-12-31 | 505 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2019-03-31 | 889061070 | 2019-03-23 | 505 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2019-06-30 | 903160297 | 2019-06-24 | 505 | 1.00 | 1.00 | 5.00 | 0.00 | ok |
| 2019-09-30 | 918683707 | 2019-09-29 | 505 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2019-12-31 | 933395471 | 2019-12-31 | 505 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2020-03-31 | 945114809 | 2020-03-11 | 505 | 1.00 | 1.00 | 19.00 | 0.00 | ok |
| 2020-06-30 | 964964792 | 2020-06-28 | 505 | 1.00 | 1.00 | 1.00 | 0.00 | ok |
| 2020-09-30 | 980783480 | 2020-09-28 | 505 | 1.00 | 1.00 | 1.00 | 0.00 | ok |
| 2020-12-31 | 997494787 | 2020-12-31 | 505 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2021-03-31 | 1014924736 | 2021-03-29 | 505 | 1.00 | 1.00 | 1.00 | 0.00 | ok |
| 2021-06-30 | 1030573330 | 2021-06-26 | 505 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2021-09-30 | 1046858083 | 2021-09-27 | 505 | 1.00 | 1.00 | 2.00 | 0.00 | ok |
| 2021-12-31 | 1062834329 | 2021-12-30 | 505 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2022-03-31 | 1078861896 | 2022-03-23 | 505 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2022-06-30 | 1095558369 | 2022-06-29 | 503 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2022-09-30 | 1113035208 | 2022-09-29 | 503 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2022-12-31 | 1130173030 | 2022-12-28 | 503 | 1.00 | 1.00 | 2.00 | 0.00 | ok |
| 2023-03-31 | 1146429089 | 2023-03-24 | 503 | 1.00 | 1.00 | 6.00 | 0.00 | ok |
| 2023-06-30 | 1160956732 | 2023-06-19 | 503 | 1.00 | 1.00 | 10.00 | 0.00 | ok |
| 2023-09-30 | 1177710839 | 2023-09-29 | 503 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2023-12-31 | 1192789360 | 2023-12-31 | 503 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2024-03-31 | 1216084649 | 2024-03-28 | 503 | 1.00 | 1.00 | 2.00 | 0.00 | ok |
| 2024-06-30 | 1231032496 | 2024-06-26 | 503 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2024-09-30 | 1248679132 | 2024-09-30 | 503 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2024-12-31 | 1265285344 | 2024-12-26 | 503 | 1.00 | 1.00 | 4.00 | 0.00 | ok |
| 2025-03-31 | 1283349047 | 2025-03-31 | 503 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2025-06-30 | 1295035732 | 2025-06-11 | 503 | 1.00 | 1.00 | 18.00 | 0.00 | ok |
| 2025-09-30 | 1314254751 | 2025-09-30 | 503 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2025-12-31 | 1329075976 | 2025-12-23 | 501 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2026-03-31 | 1345606266 | 2026-03-27 | 503 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2026-06-30 | 1361794875 | 2026-06-30 | 503 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2026-09-30 | 1376729338 | 2026-09-25 | 503 | 1.00 | 1.00 | 4.00 | 0.00 | ok |
| 2026-10-19 | 1380159481 | 2026-10-14 | 503 | 1.00 | 1.00 | 4.00 | 0.00 | ok |

### SP400

| snapshot | revid | revision | rows | GICS | CIK | stale | defunct | status |
|---|---|---|---|---|---|---|---|---|
| 2009-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-12-31 | 405139300 | 2010-12-31 | 179 | 0.01 | 0.99 | -1.00 | 0.00 | fallback_next:2011-03-31 |
| 2011-03-31 | 420552357 | 2011-03-24 | 400 | 0.99 | 0.99 | 6.00 | 0.00 | ok |
| 2011-06-30 | 432454911 | 2011-06-04 | 400 | 0.99 | 0.99 | 25.00 | 0.00 | ok |
| 2011-09-30 | 452069833 | 2011-09-23 | 400 | 0.99 | 0.99 | 6.00 | 0.00 | ok |
| 2011-12-31 | 465803600 | 2011-12-14 | 400 | 0.99 | 0.99 | 16.00 | 0.00 | ok |
| 2012-03-31 | 465803600 | 2011-12-14 | 400 | 0.99 | 0.99 | 107.00 | 0.00 | ok |
| 2012-06-30 | 498154581 | 2012-06-18 | 400 | 0.99 | 0.99 | 11.00 | 0.00 | ok |
| 2012-09-30 | 508263325 | 2012-08-20 | 399 | 0.99 | 0.99 | 40.00 | 0.00 | ok |
| 2012-12-31 | 529041475 | 2012-12-21 | 399 | 0.99 | 0.98 | 9.00 | 0.00 | ok |
| 2013-03-31 | 541802782 | 2013-03-02 | 399 | 0.99 | 0.98 | 28.00 | 0.00 | ok |
| 2013-06-30 | 558977951 | 2013-06-08 | 399 | 0.99 | 0.97 | 21.00 | 0.00 | ok |
| 2013-09-30 | 570483518 | 2013-08-28 | 376 | 0.96 | 0.99 | 32.00 | 0.00 | ok |
| 2013-12-31 | 588013284 | 2013-12-28 | 400 | 0.81 | 1.00 | 2.00 | 0.00 | ok |
| 2014-03-31 | 600868735 | 2014-03-23 | 400 | 0.81 | 1.00 | 7.00 | 0.00 | ok |
| 2014-06-30 | 613998919 | 2014-06-22 | 400 | 0.81 | 1.00 | 7.00 | 0.00 | ok |
| 2014-09-30 | 626812857 | 2014-09-23 | 400 | 0.81 | 1.00 | 6.00 | 0.00 | ok |
| 2014-12-31 | 626812857 | 2014-09-23 | 400 | 0.81 | 0.99 | 98.00 | 0.00 | ok |
| 2015-03-31 | 626812857 | 2014-09-23 | 400 | 0.81 | 0.99 | 188.00 | 0.00 | ok |
| 2015-06-30 | 667639485 | 2015-06-19 | 400 | 0.98 | 0.99 | 10.00 | 0.00 | ok |
| 2015-09-30 | 673560561 | 2015-07-29 | 400 | 0.98 | 0.99 | 62.00 | 0.00 | ok |
| 2015-12-31 | 696485515 | 2015-12-23 | 400 | 0.98 | 0.99 | 7.00 | 0.00 | ok |
| 2016-03-31 | 712578473 | 2016-03-29 | 400 | 0.98 | 0.99 | 1.00 | 0.00 | ok |
| 2016-06-30 | 718663041 | 2016-05-04 | 400 | 0.98 | 0.99 | 56.00 | 0.00 | ok |
| 2016-09-30 | 734404564 | 2016-08-14 | 400 | 0.98 | 0.99 | 46.00 | 0.00 | ok |
| 2016-12-31 | 757637907 | 2016-12-31 | 400 | 0.99 | 1.00 | -1.00 | 0.00 | ok |
| 2017-03-31 | 771688614 | 2017-03-22 | 400 | 1.00 | 1.00 | 8.00 | 0.00 | ok |
| 2017-06-30 | 787360767 | 2017-06-24 | 400 | 1.00 | 1.00 | 5.00 | 0.00 | ok |
| 2017-09-30 | 801783306 | 2017-09-21 | 400 | 1.00 | 1.00 | 8.00 | 0.00 | ok |
| 2017-12-31 | 815749728 | 2017-12-16 | 400 | 1.00 | 1.00 | 14.00 | 0.00 | ok |
| 2018-03-31 | 831673729 | 2018-03-21 | 400 | 1.00 | 1.00 | 9.00 | 0.00 | ok |
| 2018-06-30 | 847263506 | 2018-06-24 | 400 | 1.00 | 1.00 | 5.00 | 0.00 | ok |
| 2018-09-30 | 861239585 | 2018-09-26 | 400 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2018-12-31 | 872201966 | 2018-12-05 | 401 | 1.00 | 1.00 | 25.00 | 0.00 | ok |
| 2019-03-31 | 882870181 | 2019-02-11 | 400 | 1.00 | 1.00 | 47.00 | 0.00 | ok |
| 2019-06-30 | 903198571 | 2019-06-24 | 399 | 1.00 | 0.99 | 5.00 | 0.00 | ok |
| 2019-09-30 | 918482817 | 2019-09-28 | 400 | 1.00 | 0.99 | 1.00 | 0.00 | ok |
| 2019-12-31 | 932594637 | 2019-12-27 | 400 | 1.00 | 0.99 | 3.00 | 0.00 | ok |
| 2020-03-31 | 947396937 | 2020-03-26 | 400 | 1.00 | 0.99 | 4.00 | 0.00 | ok |
| 2020-06-30 | 953996133 | 2020-04-30 | 400 | 1.00 | 0.99 | 60.00 | 0.00 | ok |
| 2020-09-30 | 975982402 | 2020-08-31 | 400 | 1.00 | 0.99 | 29.00 | 0.00 | ok |
| 2020-12-31 | 997074539 | 2020-12-29 | 400 | 1.00 | 0.99 | 1.00 | 0.00 | ok |
| 2021-03-31 | 1015305749 | 2021-03-31 | 396 | 1.00 | 0.99 | -1.00 | 0.00 | ok |
| 2021-06-30 | 1029109518 | 2021-06-17 | 400 | 1.00 | 0.99 | 12.00 | 0.00 | ok |
| 2021-09-30 | 1047274178 | 2021-09-30 | 400 | 1.00 | 0.99 | -1.00 | 0.00 | ok |
| 2021-12-31 | 1062911677 | 2021-12-31 | 400 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2022-03-31 | 1080007634 | 2022-03-29 | 400 | 1.00 | 1.00 | 1.00 | 0.00 | ok |
| 2022-06-30 | 1095734928 | 2022-06-30 | 401 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2022-09-30 | 1111632889 | 2022-09-22 | 401 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2022-12-31 | 1130633662 | 2022-12-31 | 401 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2023-03-31 | 1146634056 | 2023-03-26 | 401 | 1.00 | 1.00 | 4.00 | 0.00 | ok |
| 2023-06-30 | 1162115711 | 2023-06-27 | 401 | 0.98 | 1.00 | 2.00 | 0.00 | ok |
| 2023-09-30 | 1177130842 | 2023-09-26 | 401 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2023-12-31 | 1191696148 | 2023-12-25 | 401 | 0.98 | 1.00 | 5.00 | 0.00 | ok |
| 2024-03-31 | 1216447051 | 2024-03-31 | 401 | 0.98 | 1.00 | -1.00 | 0.00 | ok |
| 2024-06-30 | 1231752707 | 2024-06-30 | 401 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2024-09-30 | 1248542737 | 2024-09-30 | 401 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2024-12-31 | 1266277820 | 2024-12-30 | 401 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2025-03-31 | 1283042793 | 2025-03-30 | 401 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2025-06-30 | 1297067213 | 2025-06-24 | 401 | 1.00 | 1.00 | 5.00 | 0.00 | ok |
| 2025-09-30 | 1313200096 | 2025-09-24 | 401 | 1.00 | 1.00 | 5.00 | 0.00 | ok |
| 2025-12-31 | 1329819820 | 2025-12-28 | 401 | 1.00 | 1.00 | 2.00 | 0.00 | ok |
| 2026-03-31 | 1346242889 | 2026-03-30 | 400 | 0.99 | 1.00 | 0.00 | 0.00 | ok |
| 2026-06-30 | 1360492269 | 2026-06-21 | 400 | 0.99 | 1.00 | 8.00 | 0.00 | ok |
| 2026-09-30 | 1376755150 | 2026-09-26 | 400 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2026-10-19 | 1379294000 | 2026-10-09 | 400 | 1.00 | 1.00 | 9.00 | 0.00 | ok |

### SP600

| snapshot | revid | revision | rows | GICS | CIK | stale | defunct | status |
|---|---|---|---|---|---|---|---|---|
| 2009-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2010-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2011-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2011-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2011-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2011-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2012-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2012-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2012-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2012-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2013-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2013-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2013-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2013-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2014-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2014-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2014-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2014-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2015-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2015-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2015-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2015-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2016-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2016-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2016-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2016-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2017-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2017-06-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2017-09-30 |  |  | 0 | 0.00 |  |  |  | missing |
| 2017-12-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2018-03-31 |  |  | 0 | 0.00 |  |  |  | missing |
| 2018-06-30 |  |  | 0 | 0.00 | 1.00 |  | 0.00 | fallback_next:2018-09-30 |
| 2018-09-30 | 861818572 | 2018-09-30 | 596 | 1.00 | 1.00 | -1.00 | 0.00 | derived_sp1000_minus_sp400 |
| 2018-12-31 | 874581312 | 2018-12-20 | 598 | 1.00 | 1.00 | 10.00 | 0.00 | derived_sp1000_minus_sp400 |
| 2019-03-31 | 886469838 | 2019-03-06 | 599 | 1.00 | 1.00 | 24.00 | 0.01 | derived_sp1000_minus_sp400 |
| 2019-06-30 | 903017102 | 2019-06-22 | 599 | 1.00 | 1.00 | 7.00 | 0.02 | derived_sp1000_minus_sp400 |
| 2019-09-30 | 909244833 | 2019-08-04 | 614 | 1.00 | 1.00 | 56.00 | 0.04 | derived_sp1000_minus_sp400 |
| 2019-12-31 | 931837661 | 2019-12-21 | 624 | 1.00 | 1.00 | 9.00 | 0.06 | derived_sp1000_minus_sp400 |
| 2020-03-31 | 944460080 | 2020-03-08 | 626 | 1.00 | 1.00 | 22.00 | 0.08 | derived_sp1000_minus_sp400 |
| 2020-06-30 | 962955134 | 2020-06-16 | 626 | 1.00 | 1.00 | 13.00 | 0.10 | derived_sp1000_minus_sp400 |
| 2020-09-30 | 976486105 | 2020-09-03 | 622 | 0.99 | 1.00 | 26.00 | 0.09 | derived_sp1000_minus_sp400 |
| 2020-12-31 | 996700216 | 2020-12-28 | 756 | 0.88 | 1.00 | 2.00 | 0.00 | fallback_prev:2020-09-30 |
| 2021-03-31 | 1015242871 | 2021-03-31 | 601 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2021-06-30 | 1030576925 | 2021-06-26 | 601 | 1.00 | 1.00 | 3.00 | 0.00 | ok |
| 2021-09-30 | 1045975901 | 2021-09-23 | 601 | 1.00 | 1.00 | 6.00 | 0.00 | ok |
| 2021-12-31 | 1061579576 | 2021-12-22 | 601 | 1.00 | 1.00 | 8.00 | 0.00 | ok |
| 2022-03-31 | 1077485333 | 2022-03-16 | 601 | 1.00 | 1.00 | 14.00 | 0.00 | ok |
| 2022-06-30 | 1094398428 | 2022-06-22 | 601 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2022-09-30 | 1113069686 | 2022-09-29 | 601 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2022-12-31 | 1130398945 | 2022-12-30 | 601 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2023-03-31 | 1147344939 | 2023-03-30 | 601 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2023-06-30 | 1161531950 | 2023-06-23 | 601 | 1.00 | 1.00 | 6.00 | 0.00 | ok |
| 2023-09-30 | 1177744056 | 2023-09-29 | 601 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2023-12-31 | 1190743635 | 2023-12-19 | 602 | 1.00 | 1.00 | 11.00 | 0.00 | ok |
| 2024-03-31 | 1214663565 | 2024-03-20 | 602 | 1.00 | 1.00 | 10.00 | 0.00 | ok |
| 2024-06-30 | 1231006396 | 2024-06-25 | 602 | 1.00 | 1.00 | 4.00 | 0.00 | ok |
| 2024-09-30 | 1248000289 | 2024-09-27 | 602 | 1.00 | 1.00 | 2.00 | 0.00 | ok |
| 2024-12-31 | 1266283308 | 2024-12-30 | 602 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2025-03-31 | 1282499305 | 2025-03-26 | 602 | 1.00 | 1.00 | 4.00 | 0.00 | ok |
| 2025-06-30 | 1297281645 | 2025-06-25 | 602 | 1.00 | 1.00 | 4.00 | 0.00 | ok |
| 2025-09-30 | 1314021341 | 2025-09-29 | 601 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2025-12-31 | 1329058715 | 2025-12-23 | 603 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2026-03-31 | 1346175333 | 2026-03-30 | 603 | 1.00 | 1.00 | 0.00 | 0.00 | ok |
| 2026-06-30 | 1361863284 | 2026-06-30 | 603 | 1.00 | 1.00 | -1.00 | 0.00 | ok |
| 2026-09-30 | 1376148321 | 2026-09-22 | 603 | 1.00 | 1.00 | 7.00 | 0.00 | ok |
| 2026-10-19 | 1379103835 | 2026-10-08 | 603 | 1.00 | 1.00 | 10.00 | 0.00 | ok |

## 4. S&P 500: Wikipedia quarter-end tables vs fja05680 exact membership

Before the gap-fill below the mean Jaccard was 0.993 (min 0.961).

fja omits 8 S&P 500 runs that Wikipedia lists in >= 2 consecutive quarter-end tables; they are added as `source = wikipedia_gapfill` rows for the span shown (quarter-end to quarter-end):

| ticker | name | start | end |
|---|---|---|---|
| ASH | Ashland Inc. | 2009-12-31 | 2010-07-01 |
| CBE | Cooper Industries Ltd. | 2009-12-31 | 2010-07-01 |
| RSH | RadioShack Corp | 2009-12-31 | 2011-10-01 |
| ACT | Actavis Inc | 2009-12-31 | 2013-10-01 |
| MXB | MSCI | 2010-03-31 | 2010-07-01 |
| ACE | ACE Limited | 2010-09-30 | 2016-01-01 |
| TYC | Tyco International | 2010-09-30 | 2016-07-01 |
| ACT | Actavis Inc | 2013-12-31 | 2015-04-01 |

Company-level (CIK) Jaccard agreement, mean over 69 quarter-ends: **0.996** (min 0.969, median 0.996). Differences are timing (Wikipedia lags changes), unresolved identities in the early years, and fja data gaps (for example the ACE and Tyco lines are missing from fja before 2016).

| year | n | mean_jaccard | mean_wiki_only | mean_fja_only |
|---|---|---|---|---|
| 2009 | 1 | 0.969 | 6.000 | 10.000 |
| 2010 | 4 | 0.984 | 2.500 | 5.500 |
| 2011 | 4 | 0.996 | 0.750 | 1.500 |
| 2012 | 4 | 0.998 | 0.500 | 0.750 |
| 2013 | 4 | 0.995 | 1.250 | 1.250 |
| 2014 | 4 | 0.999 | 0.250 | 0.250 |
| 2015 | 4 | 0.999 | 0.250 | 0.500 |
| 2016 | 4 | 0.999 | 0.250 | 0.500 |
| 2017 | 4 | 0.995 | 1.500 | 1.250 |
| 2018 | 4 | 0.996 | 1.000 | 1.000 |
| 2019 | 4 | 0.995 | 1.250 | 1.250 |
| 2020 | 4 | 0.990 | 2.500 | 2.500 |
| 2021 | 4 | 0.996 | 1.000 | 1.000 |
| 2022 | 4 | 0.997 | 0.750 | 0.750 |
| 2023 | 4 | 0.999 | 0.250 | 0.250 |
| 2024 | 4 | 1.000 | 0.000 | 0.250 |
| 2025 | 4 | 0.998 | 0.250 | 0.750 |
| 2026 | 4 | 0.998 | 0.500 | 0.500 |

Worst quarters:

| snapshot_date | n_wiki | n_fja | both | wiki_only | fja_only | jaccard |
|---|---|---|---|---|---|---|
| 2009-12-31 | 498 | 502 | 492 | 6 | 10 | 0.969 |
| 2010-03-31 | 498 | 504 | 494 | 4 | 10 | 0.972 |
| 2010-12-31 | 500 | 501 | 496 | 4 | 5 | 0.982 |
| 2020-06-30 | 500 | 500 | 496 | 4 | 4 | 0.984 |
| 2020-09-30 | 500 | 500 | 496 | 4 | 4 | 0.984 |
| 2010-06-30 | 500 | 504 | 498 | 2 | 6 | 0.984 |

## 5. Ticker -> CIK mapping

Share of member rows with an SEC CIK (quarter-end snapshots, `dedupe=False`):

| year | SP500 | SP400 | SP600 | all |
|---|---|---|---|---|
| 2010 | 0.997 | 0.995 |  | 0.997 |
| 2011 | 0.999 | 0.995 |  | 0.997 |
| 2012 | 1.000 | 0.991 |  | 0.996 |
| 2013 | 1.000 | 0.985 |  | 0.993 |
| 2014 | 1.000 | 0.997 |  | 0.999 |
| 2015 | 1.000 | 0.994 |  | 0.997 |
| 2016 | 1.000 | 0.994 |  | 0.997 |
| 2017 | 1.000 | 0.998 |  | 0.999 |
| 2018 | 1.000 | 0.998 | 0.997 | 0.998 |
| 2019 | 1.000 | 0.996 | 0.997 | 0.998 |
| 2020 | 1.000 | 0.995 | 0.996 | 0.997 |
| 2021 | 1.000 | 0.996 | 0.998 | 0.998 |
| 2022 | 0.998 | 0.998 | 0.998 | 0.998 |
| 2023 | 1.000 | 0.995 | 0.998 | 0.998 |
| 2024 | 1.000 | 0.995 | 0.998 | 0.998 |
| 2025 | 1.000 | 0.998 | 0.998 | 0.999 |
| 2026 | 1.000 | 1.000 | 0.998 | 0.999 |

Method counts (all membership rows):

| cik_method | rows |
|---|---|
| wiki_near | 165944 |
| wiki_cik | 19352 |
| ticker+name | 17855 |
| name | 7329 |
| override | 3329 |
| ticker+fuzzy | 623 |
| name_loose | 471 |
| unmapped | 231 |
| ticker+fuzzy_low | 164 |
| name_subset | 154 |
| ticker+name_loose | 94 |
| wiki_cik_implausible | 76 |
| name_soft | 38 |
| sec_ticker | 20 |
| unmapped_conflict | 13 |

### Unmapped members (31 ticker/index pairs without a CIK; mostly pre-XBRL acquisitions and bank filers outside EDGAR)

| ticker_raw | index | name | rows | first | last |
|---|---|---|---|---|---|
| PFBC | SP600 | Preferred Bank | 35 | 2018-06-30 | 2026-10-19 |
| SBNY | SP400 | Signature Bank | 32 | 2013-12-31 | 2021-09-30 |
| RSHCQ | SP500 |  | 26 | 2009-12-31 | 2011-06-02 |
| SBNY | SP500 |  | 21 | 2021-12-20 | 2023-01-04 |
| CADE | SP400 | Cadence Bank | 17 | 2021-12-31 | 2025-12-31 |
| MIL | SP500 |  | 13 | 2009-12-31 | 2010-07-01 |
| WFSL | SP400 | Washington Fed Inc | 12 | 2010-12-31 | 2013-09-30 |
| AINV | SP400 | Apollo Inv Corp | 11 | 2010-12-31 | 2013-06-30 |
| OPB | SP600 | Opus Bank | 11 | 2018-06-30 | 2020-12-31 |
| BXS | SP400 | BancorpSouth | 10 | 2019-06-30 | 2021-09-30 |
| DV | SP400 | DeVry Inc | 8 | 2014-12-31 | 2016-09-30 |
| NYCB | SP400 | New York Community Bank | 8 | 2023-03-31 | 2024-12-31 |
| RX | SP500 |  | 5 | 2009-12-31 | 2010-02-16 |
| ACV | SP400 | Alberto-Culver Co | 4 | 2012-09-30 | 2013-06-30 |
| AMB | SP400 | AMB Property Corp | 4 | 2012-09-30 | 2013-06-30 |
| PDE | SP400 | Pride Intl Inc | 3 | 2012-12-31 | 2013-06-30 |
| LZ | SP400 | Lubrizol Corp | 3 | 2013-03-31 | 2013-09-30 |
| ACS | SP500 |  | 3 | 2009-12-31 | 2010-01-29 |
| BUCY | SP400 | Bucyrus International Inc | 3 | 2012-12-31 | 2013-06-30 |
| NHP | SP400 | Nationwide Health Properties | 2 | 2013-06-30 | 2013-09-30 |
| FTD | SP600 | FTD Companies, Inc. | 2 | 2020-09-30 | 2020-12-31 |
| TIN | SP400 | Temple-Inland Inc | 2 | 2013-06-30 | 2013-09-30 |
| MDC | SP400 | ] | 1 | 2016-09-30 | 2016-09-30 |
| LPS | SP400 | Lender Processing Services | 1 | 2015-03-31 | 2015-03-31 |
| JAVA | SP500 |  | 1 | 2009-12-31 | 2009-12-31 |
| HME | SP400 | Home Properties of New York | 1 | 2016-09-30 | 2016-09-30 |
| ROSE | SP400 | Rosetta Resources Inc | 1 | 2016-09-30 | 2016-09-30 |
| ENDP | SP400 | Endo Pharmaceuticals Hldg | 1 | 2015-03-31 | 2015-03-31 |
| BEC | SP400 | Beckman Coulter Inc | 1 | 2013-06-30 | 2013-06-30 |
| TRH | SP400 | Transatlantic Hldgs Inc | 1 | 2013-09-30 | 2013-09-30 |
| AAI | SP400 | AirTran Holdings Inc | 1 | 2013-06-30 | 2013-06-30 |

### Manual CIK overrides in use

| ticker | from | to | cik | note |
|---|---|---|---|---|
| NVE |  |  | 741508 | NV Energy, Inc. (name match had picked US Energy / Big Sky Industrial) |
| LSI |  | 2014-12-31 | 703360 | LSI Corp (formerly LSI Logic, acquired by Avago 2014-05); name match had picked LSI Industries (LYTS). Ticker LSI was later Life Storage (2016-23), which must not inherit this CIK |
| TBL |  |  | 814361 | The Timberland Co; name match had picked Timberland Bancorp (TSBK) |
| AABA |  |  | 1011006 | fja ticker for Yahoo! Inc. after the 2017 rename to Altaba (CIK unchanged) |
| BHGE |  | 2017-06-30 | 808362 | fja back-fills the Baker Hughes GE ticker over Baker Hughes Inc. (BHI) |
| BTUUQ |  |  | 1064728 | Peabody Energy: post-bankruptcy Q symbol used by fja |
| ANRZQ |  |  | 1301063 | Alpha Natural Resources: post-bankruptcy Q symbol used by fja |
| EKDKQ |  |  | 31235 | Eastman Kodak: post-bankruptcy Q symbol used by fja |
| SUNEQ |  |  | 945436 | SunEdison (formerly MEMC): post-bankruptcy Q symbol used by fja |
| DXC |  | 2017-03-31 | 23082 | fja back-fills DXC over Computer Sciences Corp. (CSC, CIK 23082) |
| EVHC | 2016-06-01 | 2019-12-31 | 1678531 | Envision Healthcare Corp (post-AmSurg merger registrant) |
| AVGO | 2015-01-01 | 2018-10-31 | 1441634 | Avago / Broadcom Ltd before Broadcom Inc. (CIK 1730168) took over in 2018-11 |
| JEF |  | 2018-06-30 | 96223 | fja back-fills JEF over Leucadia National (LUK, CIK 96223 = Jefferies Financial Group) |
| IFF |  |  | 51253 | International Flavors & Fragrances (abbreviated Wikipedia name) |
| DD |  | 2017-08-31 | 30554 | E. I. du Pont de Nemours (EIDP, CIK 30554) before the DowDuPont merger |
| PBCT |  |  | 1378946 | People's United Financial |
| NLSN |  |  | 1492633 | Nielsen Holdings plc |
| WIN |  |  | 1282266 | Windstream Holdings / Windstream Corp (Wikipedia name: Windstream Communications) |
| TUP |  |  | 1008654 | Tupperware Brands |
| WDR |  |  | 1052100 | Waddell & Reed Financial (abbreviated Wikipedia name) |
| SNH |  |  | 1075415 | Senior Housing Properties Trust = Diversified Healthcare Trust |
| HPT |  |  | 945394 | Hospitality Properties Trust = Service Properties Trust |
| MDRX |  |  | 1124804 | Allscripts Healthcare Solutions = Veradigm |
| FNFG |  |  | 1051741 | First Niagara Financial Group (abbreviated Wikipedia name) |
| HMA |  |  | 792985 | Health Management Associates |
| WBS |  |  | 801337 | Webster Financial (Wikipedia name: Webster Bank) |
| IRT |  |  | 1466085 | Independence Realty Trust (Wikipedia name: IRT Living) |
| X |  |  | 1163302 | United States Steel |
| PPDI |  |  | 1003124 | Pharmaceutical Product Development |
| KCI |  |  | 831967 | Kinetic Concepts |
| PCH |  |  | 1338749 | Potlatch = PotlatchDeltic |
| APOL |  |  | 929887 | Apollo Group = Apollo Education Group |
| HYH |  |  | 1606498 | Halyard Health = Avanos Medical |
| SMCI |  |  | 1375365 | Super Micro Computer (Wikipedia name: Supermicro) |
| FICO |  |  | 814547 | Fair Isaac (Wikipedia name: FICO) |
| UMPQ |  |  | 1077771 | Umpqua Holdings |
| UTR |  |  | 860748 | Unitrin = Kemper Corp |
| CNL |  |  | 1089819 | Cleco Corporation (Wikipedia typo: CLECO Coporation) |
| AMWD |  |  | 794619 | American Woodmark |
| APEI |  |  | 1201792 | American Public Education |
| AAXN |  |  | 1069183 | Axon Enterprise (formerly TASER) |
| CDAY |  |  | 1725057 | Ceridian HCM = Dayforce |
| ACET |  |  | 2034 | Aceto Corp |
| RDK |  |  | 85704 | Ruddick Corp = Harris Teeter Supermarkets |
| VCLK |  |  | 1080034 | ValueClick = Conversant |
| OZK |  |  | 1038205 | Bank OZK (Bank of the Ozarks; files with the FDIC after 2022) |
| DTV | 2009-12-01 | 2015-07-31 | 1465112 | DIRECTV (public parent after the 2009 Liberty Entertainment merger) |

### CIK aliases (successor registrants mapped back to the long-history CIK)

| old_cik | new_cik | note |
|---|---|---|
| 34088 | 2115436 | Exxon Mobil holding-company reorganisation 2026-07: SEC ticker file points to the new registrant (2 quarters of history), the 30-year history is under the old CIK |
| 1364742 | 2012383 | BlackRock, Inc. new registrant after the 2024-02 reorganisation (old CIK renamed BlackRock Finance, Inc.) |
| 1144519 | 1996862 | Bunge Limited -> Bunge Global SA redomiciliation 2023-11 |
| 73088 | 1993004 | NorthWestern Corp -> NorthWestern Energy Group holding company 2023-10 |
| 1620280 | 2020795 | Uniti Group (old registrant, now Uniti Group LLC) -> new Uniti Group Inc. after the Windstream merger 2024-05 |
| 1115055 | 2082866 | Pinnacle Financial Partners -> new registrant after the Synovus merger 2025-08 |
| 811532 | 1999001 | Cedar Fair L.P. -> Six Flags Entertainment Corporation (ticker FUN continues) 2023-11 |
| 813828 | 2041610 | Paramount Global (CBS / ViacomCBS / PARA) -> Paramount Skydance (new registrant 2024-11; PSKY, now SKYD) |

## 6. GICS

| era | sub_industries | industries | groups | sectors | valid_from | valid_to |
|---|---|---|---|---|---|---|
| 2008 | 155 | 68 | 24 | 10 |  | 2016-08-31 |
| 2016 | 157 | 68 | 24 | 11 | 2016-09-01 | 2018-09-21 |
| 2018 | 158 | 69 | 24 | 11 | 2018-09-22 | 2023-03-17 |
| 2023 | 163 | 74 | 25 | 11 | 2023-03-18 |  |

Distinct (label, sector, era) combinations found in the Wikipedia 'GICS Sub-Industry' column: 962. Resolved as sub-industry: 849, industry: 91, industry group: 6, sector: 0, dropped as non-GICS junk: 16; **unmapped: 0** 

The 2013-2020 revisions mix sub-industry names with industry / industry-group names, typos and non-GICS phrases (for example `Banks`, `REITs`, `Health Care Equipment & Services`, `Broadcasting & Cable TV`, `Life Sciences Tolls & Services`); `GICS_LABEL_ALIASES` in the module lists every alias applied. Such rows are resolved at their own level and the sub-industry is back-filled from the nearest other snapshot of the same company (see `gics_source`). Wikipedia's sub-industry labels also contain editor errors that cannot be detected (e.g. Visa/Mastercard are `Internet Software & Services` from 2013 to 2019), so the sector level is more reliable than the sub-industry level before 2019.

Source of the GICS label by membership-row year (rows):

| year | asof_next | asof_prev | backfill_next | backfill_prev | coarse_group | coarse_industry | era_next | era_prev | none | sector_only | snapshot | snapshot_lagged_era |
|---|---|---|---|---|---|---|---|---|---|---|---|---|
| 2009 | 453 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 5 | 45 | 0 | 0 |
| 2010 | 7795 | 0 | 6 | 0 | 0 | 0 | 0 | 0 | 35 | 707 | 394 | 0 |
| 2011 | 9286 | 84 | 24 | 0 | 0 | 0 | 0 | 0 | 8 | 631 | 1576 | 0 |
| 2012 | 8939 | 220 | 24 | 0 | 0 | 0 | 0 | 0 | 0 | 337 | 1574 | 0 |
| 2013 | 2722 | 7098 | 47 | 4 | 72 | 109 | 0 | 0 | 7 | 45 | 1461 | 0 |
| 2014 | 1578 | 5967 | 64 | 11 | 60 | 103 | 0 | 0 | 29 | 27 | 1277 | 0 |
| 2015 | 2710 | 12741 | 218 | 74 | 30 | 176 | 0 | 0 | 8 | 34 | 1195 | 6 |
| 2016 | 4449 | 12106 | 256 | 76 | 2 | 114 | 0 | 0 | 20 | 15 | 1202 | 18 |
| 2017 | 606 | 11507 | 35 | 25 | 0 | 5 | 0 | 0 | 0 | 0 | 1508 | 28 |
| 2018 | 194 | 12426 | 36 | 13 | 0 | 5 | 28 | 0 | 0 | 0 | 3293 | 16 |
| 2019 | 220 | 10892 | 40 | 5 | 0 | 4 | 51 | 5 | 0 | 0 | 3924 | 4 |
| 2020 | 41 | 6530 | 36 | 4 | 0 | 4 | 44 | 5 | 0 | 0 | 3997 | 2 |
| 2021 | 23 | 7046 | 0 | 0 | 0 | 0 | 0 | 0 | 1 | 0 | 4000 | 0 |
| 2022 | 24 | 9530 | 0 | 0 | 0 | 0 | 0 | 0 | 19 | 0 | 4007 | 0 |
| 2023 | 673 | 6368 | 53 | 4 | 0 | 0 | 372 | 0 | 1 | 0 | 3504 | 76 |
| 2024 | 24 | 7019 | 21 | 0 | 0 | 0 | 191 | 0 | 0 | 0 | 3747 | 53 |
| 2025 | 36 | 8014 | 6 | 0 | 0 | 0 | 94 | 0 | 0 | 0 | 3883 | 29 |
| 2026 | 32 | 9024 | 4 | 0 | 0 | 0 | 0 | 0 | 0 | 0 | 3980 | 28 |

Mapping flags (`era_fallback:*` = the label only exists in another era, typically Wikipedia lagging a GICS change; `sector_mismatch` = mapped sector differs from the snapshot's sector column):

| gics_flag | rows |
|---|---|
| exact (valid era) | 213839 |
| era_fallback:2016 | 1472 |
| era_fallback:2018 | 190 |
| no_gics | 133 |
| era_fallback:2008 | 58 |
| era_fallback:2023 | 1 |

## 7. Yahoo tickers and survivorship exposure

| yf_status | rows |
|---|---|
| current_sec_ticker | 177368 |
| historical_ticker | 32368 |
| blocked_ticker_reuse | 3181 |
| historical_ticker_successor | 2291 |
| merger_ticker_conflict | 241 |
| raw_ticker_nocik | 231 |
| blocked_ticker_reuse_nocik | 13 |

Company keys with a **blocked** (re-used) symbol: 80; their `yf_ticker` is null so no wrong prices are attached. Examples:

| cik | name | first_index_date | last_index_date |
|---|---|---|---|
| 2034 | ACETO CORP | 2018-06-30 | 2020-06-30 |
| 5133 | AMERICAN GREETINGS CORP | 2010-12-31 | 2013-06-30 |
| 9984 | BARNES GROUP INC | 2018-06-30 | 2024-12-31 |
| 20171 | CHUBB CORP | 2009-12-31 | 2016-02-22 |
| 21510 | COHERENT INC | 2017-03-31 | 2022-06-30 |
| 26076 | CUBIC CORP /DE/ | 2018-06-30 | 2021-03-31 |
| 29915 | DOW CHEMICAL CO /DE/ | 2009-12-31 | 2017-08-29 |
| 31978 | EL PASO ELECTRIC CO /TX/ | 2018-06-30 | 2020-12-31 |
| 45876 | ENVIRI LLC | 2010-12-31 | 2026-03-31 |
| 53669 | JOHNSON CONTROLS INC | 2009-12-31 | 2016-10-03 |
| 60751 | LUBRIZOL Corp | 2010-12-31 | 2012-12-31 |
| 75208 | OVERSEAS SHIPHOLDING GROUP INC | 2010-12-31 | 2013-06-30 |
| 95304 | SUNOCO INC | 2009-12-31 | 2012-10-02 |
| 101830 | SPRINT LLC | 2009-12-31 | 2013-07-01 |
| 102741 | VALSPAR CORP | 2010-12-31 | 2017-03-31 |
| 201461 | CITY NATIONAL CORP | 2010-12-31 | 2016-09-30 |
| 230498 | Rock-Tenn CO | 2010-12-31 | 2016-09-30 |
| 350077 | WMS INDUSTRIES INC /DE/ | 2010-12-31 | 2015-03-31 |
| 350563 | TECO ENERGY INC | 2009-12-31 | 2016-06-24 |
| 355429 | PROTECTIVE LIFE CORP | 2010-12-31 | 2015-03-31 |
| 721083 | SMITH INTERNATIONAL INC | 2009-12-31 | 2010-07-15 |
| 730255 | CalAmp Corp. | 2018-06-30 | 2022-06-30 |
| 750556 | SUNTRUST BANKS INC | 2009-12-31 | 2019-12-05 |
| 773910 | ANADARKO PETROLEUM CORP | 2009-12-31 | 2019-08-08 |
| 780053 | NATIONWIDE HEALTH PROPERTIES, LLC | 2010-12-31 | 2013-03-31 |

Share of each year-end S&P 1500 that is no longer listed today / has no safe Yahoo symbol:

| year_end | members | not_listed_today | yf_ticker_null |
|---|---|---|---|
| 2010-12-31 | 901 | 0.372 | 0.049 |
| 2011-12-31 | 900 | 0.359 | 0.047 |
| 2012-12-31 | 899 | 0.346 | 0.042 |
| 2013-12-31 | 900 | 0.322 | 0.034 |
| 2014-12-31 | 902 | 0.319 | 0.033 |
| 2015-12-31 | 904 | 0.280 | 0.027 |
| 2016-12-31 | 905 | 0.233 | 0.010 |
| 2017-12-31 | 904 | 0.201 | 0.007 |
| 2018-12-31 | 1504 | 0.241 | 0.015 |
| 2019-12-31 | 1529 | 0.232 | 0.015 |
| 2020-12-31 | 1527 | 0.217 | 0.014 |
| 2021-12-31 | 1506 | 0.141 | 0.008 |
| 2022-12-31 | 1505 | 0.113 | 0.005 |
| 2023-12-31 | 1506 | 0.081 | 0.003 |
| 2024-12-31 | 1506 | 0.058 | 0.001 |
| 2025-12-31 | 1507 | 0.028 | 0.001 |
| 2026-10-19 | 1506 | 0.001 | 0.000 |

Symbols claimed by more than one CIK in `security_master` (`yf_shared`): 66 symbols / 134 keys. Most are sequential tenants of a re-used symbol or successor registrants; the price loader must check that the Yahoo series overlaps the membership window of the key it is attached to.

Rows where a symbol moved between two simultaneous S&P 500 members (the pre-merger rows keep their own historical symbol instead of the surviving company's current one, because Yahoo's pre-merger history may belong to the other party):

| ticker_raw | name | yf_ticker | rows | first | last |
|---|---|---|---|---|---|
| ACE | ACE Limited | ACE | 108 | 2010-09-30 | 2015-12-29 |
| TYC | Tyco International | TYC | 133 | 2010-09-30 | 2016-06-24 |

## 8. US_ALL and price ticker list

US_ALL: 4011 operating companies on NYSE/Nasdaq (SEC lists NYSE American issuers under 'NYSE') with at least one 10-K, a periodic filing in the last 2 years, no warrant/unit/right/preferred line, no blank-check/commodity-trust SIC. Exchange counts:

| exchange | n |
|---|---|
| NYSE | 1640 |
| Nasdaq | 2371 |


`price_tickers.txt` = every non-null `yf_ticker` in `membership.parquet` + US_ALL + `settings.BENCHMARKS`.

## 9. Known gaps and caveats

- **S&P 600 before 2018-09 is not available** (the Wikipedia page was created 2018-08; no free point-in-time source was found). A possible fix is the quarterly holdings of the iShares S&P SmallCap 600 fund (IJR) in its N-Q / N-CSR filings on EDGAR; not implemented. S&P 400 starts 2011-03 (page created 2010-12).
- S&P 400 / 600 membership is quarter-end granular (see `stale_days`); S&P 500 is exact to the change date, but the fja file lacks a few real constituents (gap-filled from Wikipedia, see section 4) and its early-year tickers are the companies' LATER tickers (identity is resolved per date through Wikipedia rows, see `FjaResolver`).
- The last ~2 months of S&P 500 changes (after the fja file ends) are patched from the live Wikipedia table; removal dates there are approximate.
- GICS before 2019 comes from Wikipedia and is sector-reliable but sub-industry-noisy; there is no free point-in-time GICS. Sub-industries back-filled with `*_next` use a later snapshot (mild classification look-ahead); filter on `gics_source` if that matters. Legacy (2008-structure) codes are best-effort reconstructions; names are exact where they occur in a snapshot.
- Companies that file with the FDIC instead of the SEC (Signature Bank, First Republic, Bank OZK after 2022, ...) have no CIK. Pre-XBRL acquisitions in the early S&P 500 snapshots (Sun Microsystems, Millipore, ...) are absent from the SEC company table and stay unmapped.
- Successor registrants: CIK aliases above map the new registrant back to the long-history CIK (`cik_successor` holds the new one). Older inversions (Medtronic Inc -> plc, Google -> Alphabet, ...) are NOT merged: each CIK is used in the dates it was filing.
- Yahoo coverage of delisted names is poor (research/05: about a third of removed S&P 500 names have usable data); keep them in the universe and measure coverage, do not drop them.
