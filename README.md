# WhartonGlobalChallengeCapitalCrew

Plain Python. The model itself uses only the standard library; only `fetch_data.py` (price download) needs one install, `yfinance`. Goal-based planning: $300k in 2027, $150k in 2028, then a funded operating reserve (10 x $50k from 2033) and a facility contribution.

## Setup (Mac, in Terminal)
1. Check you have Python 3 and git (both print a version number; if macOS offers to install developer tools, accept):
```
python3 --version
git --version
```
2. Clone the repository and move into it:
```
git clone https://github.com/GeoWizard4645/WhartonGlobalChallengeCapitalCrew.git
cd WhartonGlobalChallengeCapitalCrew
```
3. Check you are in the right place (you should see `allocate.py`, `config.py`, `data` and the other files):
```
ls
```
4. The price history in `data/` comes with the repo, so you can skip to the scripts below and run them right away. To refresh it with the latest prices and T-bill rate, install the one library it needs and run it (needs internet; prints each ticker's first date):
```
pip3 install yfinance
```
```
python3 fetch_data.py
```
If `pip3 install` says the environment is "externally managed", make a private environment first, then install and run inside it:
```
python3 -m venv .venv
source .venv/bin/activate
pip install yfinance
python fetch_data.py
```
Later, to pick up teammates' changes: `git pull`.

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
.venv/bin/python optimize.py                 # backtest + Monte Carlo of every bonds/funds/stocks split; heatmaps and the range of x
```
`optimize.py` (settings: the ALLOCATION OPTIMIZER block in `config.py`) uses the stock strategy's monthly returns in `output/stock_sleeve.csv`
(`python -m quant.run --sleeve-only` refreshes it) and writes `output/allocation/`: `grid.csv` (every split), `scenarios.csv`,
`x_projection.csv` (95% interval, IQR, median, mean of x), `cppi_grid.csv` and the heatmap / x-range charts.
It also runs the reserve-first strategies: a Treasury ladder that is guaranteed to grow into the operating reserve plus a growth sleeve, with a CPPI multiplier deciding how much of the surplus is risked.

## Stock strategies (`quant/`)

Quality momentum, Magic Formula and the two merged (momentum picks, Magic Formula vetoes), backtested on the
point-in-time S&P 500 + MidCap 400 (2011-2026) with SEC filing data. Results are in `output/results.csv` and
`output/performance.png`; today's picks in `output/<strategy>/picks.csv`; the order list in `output/orders.csv`.
Trading comps did not beat its benchmarks and is set aside in `quant/shelved/`.

```
python3 -m venv .venv && .venv/bin/pip install -r requirements.txt
.venv/bin/python -m quant.data.build       # one-time data download (~15 min, ~5 GB, into cache/)
.venv/bin/python -m quant.run              # backtest everything and list today's picks (~5 min)
.venv/bin/python -m quant.trade_plan       # turn the picks into WInS orders
```
Before trading, refresh prices after the close, then re-list the picks and orders:
```
.venv/bin/python -m quant.data.prices update
.venv/bin/python -m quant.run --live-only
.venv/bin/python -m quant.trade_plan                       # add --top 5 for the 5 best names per strategy
```
Every order carries its exit plan (`quant/exits.py`): momentum holdings are re-ranked at each month-end and sold
once out of the top 20; Magic Formula holdings are sold after 12 months. To see what to hold or sell:
```
.venv/bin/python -m quant.exits check
```
