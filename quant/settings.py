"""Shared paths and constants for the strategy research package.

Everything heavy (raw downloads, parquet panels) lives under cache/ (gitignored).
Results meant for the team (tables, charts, reports) go to output/.
"""
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
CACHE = ROOT / "cache"
OUTPUT = ROOT / "output"

SEC_DIR = CACHE / "sec"                 # companyfacts.zip, submissions.zip, parsed parquet
FUND_DIR = CACHE / "fundamentals"       # point-in-time fundamental panels
PRICE_DIR = CACHE / "prices"            # wide price matrices (date x ticker)
UNIV_DIR = CACHE / "universe"           # index membership, GICS, security master
FACTOR_DIR = CACHE / "factors"          # Ken French / AQR factor files

for _d in (CACHE, OUTPUT, SEC_DIR, FUND_DIR, PRICE_DIR, UNIV_DIR, FACTOR_DIR):
    _d.mkdir(parents=True, exist_ok=True)

# SEC fair-access policy: identify the client. Project contact only, no personal emails.
SEC_USER_AGENT = "CapitalCrew Student Research Project research@capitalcrew-project.org"
SEC_MAX_RPS = 8

# Wikipedia API etiquette (it rate limits hard: 429s); identify and back off.
WIKI_USER_AGENT = "CapitalCrewResearch/1.0 (student investment-competition project)"

# Backtest calendar
BACKTEST_START = "2010-01-01"           # XBRL coverage for large filers starts 2009-2011
TRAIN_END = "2018-12-31"                # parameters are chosen on the train window only...
TEST_START = "2019-01-01"               # ...and confirmed on this untouched window
LIVE_TRADE_DATE = "2026-10-21"          # Wednesday morning trades

TRADING_DAYS = 252
EXEC_LAG_DAYS = 1                       # signals at close of day t, trades at close of t+1
COST_BPS_ONE_WAY = 10                   # base case trading cost, large/mid caps
COST_BPS_STRESS = 25                    # stress case

BENCHMARKS = ["SPY", "RSP", "IVV", "MDY", "IJR", "IWM", "QQQ"]
