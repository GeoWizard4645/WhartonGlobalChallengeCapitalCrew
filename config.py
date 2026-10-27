import os

DATA_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "data")

# Each bucket is a dict of ticker -> weight inside the bucket (weights sum to 1).
# These are long-history PROXIES used to measure how each bucket behaves, not what you must buy:
#   VFINX = S&P 500 index fund (1980)       VBMFX = total bond market fund (1986)
#   VFITX = intermediate Treasury (1991)    VFICX = intermediate investment-grade corporate (1993)
#   VEIPX = equity-income fund (1988)
# The history used is limited by the NEWEST ticker here, so one young ticker shortens everything.
# The stock tickers are PLACEHOLDERS - swap in whatever the stock screen picks.
BUCKETS = {
    "Bonds":  {"VBMFX": 0.40, "VFITX": 0.30, "VFICX": 0.30},
    "Funds":  {"VFINX": 0.60, "VEIPX": 0.40},
    "Stocks": {"JNJ": 0.25, "PG": 0.25, "KO": 0.25, "PEP": 0.25},
}
BENCHMARK = "VFINX"
CASH_TICKER = "^IRX"    # 13-week T-bill yield, gives the cash rate for every date in history

# Starting guess from the plan doc: 37.5% bonds / 37.5% funds / 25% stocks
BASELINE = [0.375, 0.375, 0.25]

RISK_FREE = 0.04        # annual, used for Sharpe / Sortino (edit to current T-bill rate)
REBALANCE_DAYS = 21     # rebalance between buckets about once a month

# Monte Carlo
N_PATHS = 5000
HORIZON_YEARS = 5       # only used by montecarlo.py / buckets.py (lump-sum tools)
START_VALUE = 100000    # only used by montecarlo.py / buckets.py
TARGET_CAGR = 0.07      # only used by montecarlo.py
SEED = 42

# Bucket search grid
GRID_STEP = 0.05
BOUNDS = [(0.10, 0.70),   # Bonds  min, max
          (0.10, 0.70),   # Funds
          (0.10, 0.40)]   # Stocks
# Max 1-year loss we accept 95% of the time (buckets.py only)
RISK_PROFILES = {"Conservative": 0.08, "Moderate": 0.15, "Aggressive": 0.25}

# ---------------------------------------------------------------------------
# LAURA GAO CASE (allocate.py / plan.py)
# ---------------------------------------------------------------------------
TARGET_YEAR = 2033                      # reserve is set aside at the START of this year
CONTRIBUTIONS = {2027: 300000, 2028: 150000}   # start-of-year deposits
PAYMENT = 50000                         # fixed, not inflation adjusted
N_PAYMENTS = 10                         # 2033 ... 2042, first one at start of 2033

# How the average return of each bucket is projected (all calculated from the downloaded data):
#   "premium": expected = today's cash rate + the bucket's average return ABOVE cash over history.
#              Separates "how much extra this bucket pays for its risk" (fairly stable) from
#              "what the level of interest rates was" (not stable: ~0% in 2011-2021, ~4% now).
#   "history": expected = plain historical average.
RETURN_METHOD = "premium"
# Optional manual override per bucket (annual, e.g. 0.05). None = use the method above.
# Only use this to stress-test a different future.
EXPECTED_RETURNS = {"Bonds": None, "Funds": None, "Stocks": None}
# Average returns are measured with error (stdev / sqrt(years)). True = each simulated future
# draws its own average from that uncertainty, so outcomes spread out realistically.
PARAM_UNCERTAINTY = True
VOL_REGIME = True            # scale risk up/down if recent volatility differs from long-run
VOL_HALF_LIFE_MONTHS = 6     # how fast a volatility spike fades back to normal
VOL_RATIO_CLAMP = (0.7, 1.6)

PLANNING_YIELD = 0.035       # conservative Treasury yield we assume the reserve is bought at in 2033
INFLATION = 0.025            # only used to show contribution in today's dollars

# Reserve (the 10 payments)
RESERVE_CONFIDENCE = 0.99    # our definition of "high degree of certainty"
RESERVE_MIX = {"Bonds": 0.8, "Funds": 0.2, "Stocks": 0.0}   # what the risky sleeve of the reserve holds
RESERVE_RISKY_START = 0.0    # share of reserve in RESERVE_MIX in 2033, fading to 0 by the last payment. 0 = pure Treasury ladder

# Facility contribution
FLEX_PCT = 0.20              # share of (portfolio - reserve) Laura keeps back for flexibility
TARGET_FACILITY = 100000     # the contribution we would like to be able to make (team decision)
TARGET_SWEEP = [50000, 100000, 150000, 200000, 250000, 300000, 350000]   # targets.py tests all of these
# Cautious return view for targets.py to run next to the data-driven one (annual averages, our judgement):
CAUTIOUS_RETURNS = {"Bonds": 0.045, "Funds": 0.070, "Stocks": 0.070}
SAFETY_PROB = 0.99           # chance the portfolio covers the reserve in 2033
GOAL_PROB = 0.65             # chance we want of reaching TARGET_FACILITY
MAX_VOL = 0.10               # never recommend a split riskier than this (annual volatility), even to chase the target
RANGE_LOW_PCT = 0.10         # co-sponsor range: low end = 10th percentile (90% chance we beat it)
RANGE_HIGH_PCT = 0.50        # high end = median (50% chance we beat it)

# Windows for the backtest stress table
STRESS = {
    "Dot-com bust":    ("2000-03-24", "2002-10-09"),
    "2008 crisis":     ("2007-10-09", "2009-03-09"),
    "Q4 2018 selloff": ("2018-10-01", "2018-12-24"),
    "COVID crash":     ("2020-02-19", "2020-03-23"),
    "2022 bear":       ("2022-01-03", "2022-10-12"),
}

# ---------------------------------------------------------------------------
# ALLOCATION OPTIMIZER (optimize.py): backtest + Monte Carlo of every bonds / funds / stocks split
# ---------------------------------------------------------------------------
OPT_STEP = 0.025             # grid step for the full 0-100% splits
MC_PATHS = 30000
BLOCK_MONTHS = 6             # bootstrap draws 6-month blocks of history, keeping vol clustering and correlation
STOCK_ALPHA_KEEP = 0.5       # share of the stock strategy's backtested alpha (+2.2%/yr, t=0.8) we count on going forward
MAX_SHORTFALL = 0.05         # the "risk-limited" pick must leave at most this chance of ending 2033 below the reserve
# Reserve-first strategies (optimize.py): a Treasury sleeve that is guaranteed to grow into the operating reserve, plus a growth sleeve.
# CPPI puts (multiplier x cushion) in the growth sleeve, where cushion = portfolio value minus the PV of the reserve.
CPPI_MULTIPLIERS = [1, 2, 3, 4, 5, 6]
RISKY_STOCK_STEP = 0.1       # growth sleeve is funds/stocks; try every stock share in steps of this
MAX_STOCK_SHARE_OF_GROWTH = 0.5   # diversification rule: the stock strategy is at most half the growth sleeve, index funds the rest
MIN_X_90 = 50000             # we want to be 90% sure x (surplus above the reserve, before the flexibility hold-back) is at least this
# Futures the Monte Carlo draws from: (S&P 500 compound return, bond-sleeve compound return, volatility multiplier, probability).
# Funds and Stocks follow the S&P 500 through their historical betas (Stocks also get a share of the strategy's alpha).
# The mix is meant to span the real 6-year range (S&P 0% to 21%/yr at the 5th-95th percentile) and go a bit worse on the downside.
SCENARIOS = {
    "Crash decade":  (-0.03, 0.030, 1.3, 0.05),  # lost decade, flight to bonds
    "Terrible":      (0.015, 0.015, 1.2, 0.10),   # stagflation: stocks flat, bonds lose to inflation
    "Below average": (0.045, 0.035, 1.1, 0.15),
    "Expected":      (0.075, 0.045, 1.0, 0.35),
    "Good":          (0.105, 0.050, 0.95, 0.17),
    "Above average": (0.14, 0.055, 0.9, 0.13),
    "Insane":        (0.19, 0.060, 1.0, 0.05),    # late-1990s / 2010s style melt-up
}

ALL_TICKERS = sorted({t for b in BUCKETS.values() for t in b} | {BENCHMARK})
