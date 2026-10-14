# WhartonGlobalChallengeCapitalCrew

Plain Python (standard library only, no installs). Goal-based planning: $300k in 2027, $150k in 2028, then a funded operating reserve (10 x $50k from 2033) and a facility contribution.

## Setup
```
python3 fetch_data.py     # downloads price history + T-bill rate into data/ (re-run to refresh); prints each ticker's first date
```
Edit `config.py` first: tickers per bucket (the youngest ticker limits how much history you get), planning yield, risk limits. Expected returns are calculated from the data; `EXPECTED_RETURNS` is only for stress tests.

## Main scripts
```
python3 allocate.py YEAR VALUE [bonds funds stocks]   # bucket split for where the portfolio is right now
python3 plan.py YEAR VALUE                            # allocation + reserve + facility range + glide path
python3 targets.py YEAR VALUE                         # tests many facility targets under two return views: risk vs reward of each
```
Examples: `python3 allocate.py 2027 300000`, `python3 allocate.py 2029 520000 0.40 0.40 0.20`.
Re-run with the real portfolio value and refreshed data whenever you re-evaluate.

## Supporting tools
```
python3 backtest.py [bonds funds stocks]     # how a split behaved historically
python3 montecarlo.py [bonds funds stocks]   # lump-sum Monte Carlo on historical averages
python3 buckets.py                           # risk/reward map of every split
python3 dcf.py                               # DCF + margin of safety for stock picks
```
