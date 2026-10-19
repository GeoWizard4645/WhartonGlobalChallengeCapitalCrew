# Survivorship audit (research/06 section 6, S1 and S2)

Generated 2026-10-19 04:10 UTC; prices to 2026-10-16; data in output/survivorship.csv.

## What the numbers are

- **share with prices**: members of the point-in-time S&P 500 + MidCap 400 (`universe.members`, one row per company) whose Yahoo symbol maps to a price series with a positive close on the month-end; averaged over the month-ends of each year. The missing share is the part of the historical index that the data cannot trade (delisted, acquired, ticker re-use). `ctx.universe` silently drops these names, so every backtest here is survivorship-biased in the direction of the missing names' (usually poor) returns.
- **EW-SP900 / EW-SP500**: equal-weight, monthly-rebalanced portfolios of all priced members (price >= $5, 10 bps one-way, `ctx.ew_universe`), i.e. the same data problem as the strategies and no signal. **RSP** is the Invesco S&P 500 equal-weight ETF, which held the true historical constituents (net of its 0.20% fee).
- **bias proxy** = EW minus RSP. Only the EW-SP500 column is like for like (same index as RSP). EW-SP900 includes the 400 mid caps and therefore also carries the size premium, so its gap overstates the bias; it is shown because the strategies trade the S&P 900.

## By year (`*` = partial year)

| year | S&P900 members (avg) | with prices (avg) | share with prices | min month | EW-SP900 | EW-SP500 | RSP | EW-SP900 minus RSP | EW-SP500 minus RSP |
|---|---|---|---|---|---|---|---|---|---|
| 2011* | 896 | 571 | 63.7% | 63.2% | -2.6% | -2.5% | -2.7% | 0.1% | 0.3% |
| 2012 | 889 | 576 | 64.9% | 64.4% | 19.8% | 19.4% | 17.2% | 2.7% | 2.3% |
| 2013 | 881 | 584 | 66.4% | 65.5% | 36.6% | 36.9% | 35.5% | 1.1% | 1.4% |
| 2014 | 892 | 608 | 68.2% | 67.9% | 12.8% | 14.9% | 14.1% | -1.2% | 0.9% |
| 2015 | 892 | 626 | 70.2% | 68.5% | -2.7% | -1.7% | -2.7% | -0.0% | 1.0% |
| 2016 | 885 | 646 | 73.0% | 71.8% | 20.7% | 15.8% | 14.5% | 6.2% | 1.3% |
| 2017 | 897 | 704 | 78.5% | 77.1% | 19.1% | 20.7% | 18.5% | 0.6% | 2.2% |
| 2018 | 896 | 726 | 81.0% | 80.0% | -9.0% | -7.6% | -7.8% | -1.1% | 0.3% |
| 2019 | 895 | 749 | 83.8% | 82.8% | 29.2% | 30.6% | 28.9% | 0.3% | 1.7% |
| 2020 | 890 | 773 | 86.8% | 86.2% | 13.4% | 12.6% | 12.7% | 0.8% | -0.0% |
| 2021 | 898 | 799 | 89.0% | 88.1% | 28.7% | 30.0% | 29.4% | -0.7% | 0.6% |
| 2022 | 899 | 816 | 90.7% | 89.9% | -10.9% | -11.2% | -11.6% | 0.7% | 0.4% |
| 2023 | 900 | 835 | 92.9% | 91.9% | 17.0% | 15.9% | 13.7% | 3.3% | 2.2% |
| 2024 | 900 | 852 | 94.7% | 94.0% | 11.8% | 13.0% | 12.8% | -1.0% | 0.2% |
| 2025 | 900 | 871 | 96.8% | 95.9% | 9.3% | 11.0% | 11.2% | -1.9% | -0.2% |
| 2026* | 899 | 890 | 98.9% | 97.9% | 11.5% | 12.8% | 13.1% | -1.6% | -0.3% |

## Summary

- Mean share of S&P 900 members with prices, monthly 2011-2026: **81.0%** (worst month 63.2%).
- Full-sample CAGR: EW-SP900 12.3%, EW-SP500 12.7%, RSP 11.8% (common days 2011-02-01 to 2026-10-16).
- CAGR gap EW-SP900 minus RSP **+0.48%/yr**; EW-SP500 minus RSP **+0.86%/yr** (add back RSP's 0.20% fee: +0.66%/yr is the survivorship+look-ahead estimate of research/06 S2).
- Mean of the full-year gaps: SP900 +0.69%, SP500 +1.01%.
- Every strategy tear sheet reports `strategy minus EW-universe` (bias-neutral to first order) next to strategy minus SPY / RSP, and the evidence ladder's criterion 6 asks whether FF5+MOM alpha survives a 150 bps/yr drag.

Caveats: RSP rebalances quarterly, the EW portfolios monthly; S&P 400 membership is quarter-end granular (it can lag a mid-quarter change by up to a quarter, never look ahead); delisted names that DO exist in the price file end without a delisting return.
