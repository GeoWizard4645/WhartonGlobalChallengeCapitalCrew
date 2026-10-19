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
```

## Stock strategies: research, backtests and live picks (`quant/`)

The three stock strategies from the team doc (quality-filtered momentum, Magic Formula, GICS trading comps) are
implemented and backtested point-in-time in `quant/` (needs the packages in `requirements.txt`, unlike the
stdlib-only planning scripts above). Start with **`output/REPORT.md`** (results, verdicts, limitations) and
**`output/TRADE_PLAN.md`** (what each strategy buys now). Research notes with the math and sources are in `research/`.

Setup (once):
```
python3 -m venv .venv
.venv/bin/pip install -r requirements.txt
```
Rebuild the data (downloads SEC XBRL bulk files ~3 GB, Ken French/AQR factors, Wikipedia index history, Yahoo prices; ~15 min):
```
mkdir -p cache/sec && cd cache/sec
curl -H "User-Agent: CapitalCrew Student Research Project research@capitalcrew-project.org" -O https://www.sec.gov/Archives/edgar/daily-index/xbrl/companyfacts.zip
curl -H "User-Agent: CapitalCrew Student Research Project research@capitalcrew-project.org" -O https://www.sec.gov/Archives/edgar/daily-index/bulkdata/submissions.zip
cd ../..
.venv/bin/python -m quant.data.sec all
.venv/bin/python -m quant.data.universe build
.venv/bin/python -m quant.data.prices download
.venv/bin/python -c "from quant.data import sec, fundamentals as F; sec.build_fsds_patch(); F.build_snapshots()"
```
Run everything (pre-registered grids, train/test selection, tear sheets, live picks; ~6 min):
```
.venv/bin/python -m quant.run_backtests
.venv/bin/python -m quant.validation.factor_checks      # long-history academic evidence
.venv/bin/python -m pytest tests -q                       # 548 tests
```
Before trading (after the 4 pm close): refresh prices, recompute the live picks, size the orders:
```
.venv/bin/python -m quant.data.prices update
.venv/bin/python -m quant.run_backtests --strategy all --live-only
.venv/bin/python -m quant.trade_plan --qm 25000 --mf 25000 --tc 25000
```
