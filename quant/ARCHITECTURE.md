# quant/ — build plan and module contracts

This package implements, backtests and live-screens the three strategies from the team doc:
1. **Quality-filtered momentum** (QM)
2. **Magic Formula** (MF)
3. **Trading comps with GICS peers** (TC)

Research specs live in `research/01..07_*.md`. They are the source of truth for formulas.
This file is the source of truth for **module boundaries, data schemas and function signatures**.
If you are a build agent: implement *your* module exactly to the contract below, do not edit other
agents' modules, and put tests in `tests/test_<module>.py` (pytest).

Python: `.venv/bin/python` (3.14, pandas 3.x, numpy 2.x, scipy, statsmodels, matplotlib, yfinance, pyarrow, requests).
Run tests: `.venv/bin/python -m pytest tests -q`.

## Global conventions

- **Paths/constants**: `quant/settings.py` (ROOT, CACHE, OUTPUT, SEC_DIR, FUND_DIR, PRICE_DIR, UNIV_DIR, FACTOR_DIR, user agents, dates, costs).
- **Big data** goes in `cache/` (gitignored). **Team-facing results** go in `output/` (committed): CSV tables, PNG charts, markdown.
- **Identifiers**: companies are keyed by SEC `cik` (int). Price series are keyed by `yf_ticker` (Yahoo symbol, e.g. `BRK-B`).
  The security master maps cik <-> yf_ticker.
- **Dates**: `pd.Timestamp` normalized (no tz). Daily price index = NYSE trading days from yfinance.
- **Point-in-time (PIT) rule**: at signal date `t` (a trading day close), a filing is usable only if `filed < t`
  (strictly earlier calendar day). Prices are usable through the close of `t`.
- **Execution**: signals at close of `t` (last trading day of month for monthly strategies), trades at the close of `t+1`
  (`EXEC_LAG_DAYS = 1`). Returns are daily total returns from Adj Close.
- **Costs**: one-way cost in bps of traded notional, applied on every buy and sell. Base 10 bps, stress 25 bps.
- **No look-ahead anywhere**: index membership, GICS, fundamentals, splits, shares must all be as known at `t`.
- Money in USD, ratios as decimals (0.15 = 15%).
- Logging: use `logging.getLogger(__name__)`; no prints in library code (scripts may print).

## Data products (cache/)

| File | Producer | Schema (columns) |
|---|---|---|
| `cache/sec/facts/part-XX.parquet` (64 parts by `cik % 64`) | `quant/data/sec.py` | cik:int64, taxonomy:str ('us-gaap'/'dei'), tag:str, unit:str, start:datetime64 (NaT for instants), end:datetime64, val:float64, filed:datetime64, form:str, fy:float (nullable), fp:str, accn:str |
| `cache/sec/companies.parquet` | `quant/data/sec.py` | cik, name, tickers (pipe-joined current tickers), exchanges (pipe-joined), sic:int (nullable), sic_description, category, fiscal_year_end (MMDD str), entity_type, state_of_inc, first_filing_date, n_10k, n_10q, former_names (json str) |
| `cache/sec/filings.parquet` | `quant/data/sec.py` | cik, accn, form, filing_date, report_date, acceptance_datetime, items (8-K item codes, str) — all forms incl. 8-K, S-1, 424B* |
| `cache/fundamentals/snapshots.parquet` | `quant/data/fundamentals.py` | one row per (cik, filing that changes fundamentals); see *Snapshot schema* |
| `cache/universe/membership.parquet` | `quant/data/universe.py` | snapshot_date, index ('SP500'/'SP400'/'SP600'), ticker_raw, yf_ticker, cik (nullable int), name, gics_sector, gics_industry_group, gics_industry, gics_sub_industry (names as of that snapshot), sub_industry_code, industry_code, source |
| `cache/universe/gics.parquet` | `quant/data/universe.py` | sub_industry, sub_industry_code(8), industry, industry_code(6), industry_group, industry_group_code(4), sector, sector_code(2), valid_from, valid_to, is_legacy |
| `cache/universe/security_master.parquet` | `quant/data/universe.py` | cik, yf_ticker, name, sic, exchange, is_listed_now, ever_sp1500, first_price_date, last_price_date |
| `cache/prices/{close,adjclose,open,volume}.parquet` | `quant/data/prices.py` | wide: index=date, columns=yf_ticker, float64. `close` = split-adjusted (not dividend-adjusted), `adjclose` = split+dividend adjusted |
| `cache/prices/splits.parquet` | `quant/data/prices.py` | yf_ticker, date, ratio (e.g. 4.0 for a 4:1 split) |
| `cache/prices/meta.parquet` | `quant/data/prices.py` | yf_ticker, first_date, last_date, n_obs, status ('ok'/'empty'/'error'), note |
| `cache/prices/rf.parquet` | `quant/data/prices.py` | date, rf_annual (decimal, 3m T-bill), rf_daily |
| `cache/factors/*.parquet` | `quant/data/factors.py` | Ken French / AQR series in decimals |

### Snapshot schema (`cache/fundamentals/snapshots.parquet`)

One row per company per filing (10-K, 10-Q, their /A amendments, 10-KT/10-QT) that was **filed** and has
financial facts. Values are what an investor could compute **on the filed date**: for every (tag, start, end)
take the fact with the greatest `filed <= this filing's filed`. Flows are TTM unless suffixed.

Keys / meta: `cik, accn, form, filed, period_end` (balance-sheet anchor = latest AssetsCurrent/Assets instant end),
`fiscal_period` ('FY','Q1','Q2','Q3'), `fy_end_date` (end date of the latest 10-K fiscal year), `ttm_method` ('FY','YTD','4Q','none'), `flags` (semicolon list of fallbacks used).

TTM flows (USD): `revenue, cogs, gross_profit, sga, opinc, pretax, interest_exp, tax, net_income, net_income_incl_nci, da, cfo, capex, acquisitions, ebitda` (= opinc + da), `eps_diluted`.
Last-fiscal-year flows (suffix `_lfy`): `revenue_lfy, opinc_lfy, net_income_lfy, da_lfy, ebitda_lfy, cfo_lfy, capex_lfy`.
Balance sheet at `period_end`: `assets, current_assets, current_liabilities, cash, st_investments, ppe_net, goodwill, intangibles, liabilities, equity_parent, equity_total, preferred, minority_interest, debt_current, debt_noncurrent, total_debt, finance_lease, op_lease_current, op_lease_noncurrent, retained_earnings`.
`total_debt` is NaN (not 0) when unmapped, except the explicit "no debt" rule from research/03 §4 (no debt tag in last 8 quarters and interest expense ~0) which sets 0 and flags `debt_zero_inferred`.
Shares: `shares_out` (dei cover page, undimensioned, single value), `shares_out_date` (its instant date), `shares_diluted` (3-month WeightedAverageNumberOfDilutedSharesOutstanding of latest quarter; for 10-K use the Q4 derived or annual value), `shares_basic`.
History (as known at the filing): `assets_4q, total_debt_4q, equity_total_4q, cash_4q, shares_diluted_4q, opinc_ttm_4q, revenue_ttm_4q` (values from the period ~1 year before `period_end`),
fiscal-year history `revenue_fy1..fy5, opinc_fy1..fy5, cfo_fy1..fy5, capex_fy1..fy5, net_income_fy1..fy5, fyend_fy1..fy5` (fy1 = latest completed fiscal year),
earnings volatility `evol` = std of quarterly NI / assets over the last up-to-20 quarters (>= 12 needed, else NaN).

Helper API (`quant/data/fundamentals.py`):
```python
build_snapshots(ciks: list[int] | None = None, n_jobs: int = 8, force: bool = False) -> Path
load_snapshots(columns: list[str] | None = None) -> pd.DataFrame
asof(snaps: pd.DataFrame, date, max_age_days: int = 200) -> pd.DataFrame  # index=cik; latest row with filed < date and period_end >= date - max_age_days
```

## Integration layer (written by the lead, `quant/data/context.py`)

```python
class DataContext:
    close, adjclose, volume: pd.DataFrame          # wide, date x yf_ticker
    returns: pd.DataFrame                          # daily total returns from adjclose (cleaned)
    rf: pd.Series                                  # daily rf
    snaps: pd.DataFrame                            # snapshots
    def month_ends(start, end) -> list[pd.Timestamp]          # last trading day of each month
    def fundamentals(date, max_age_days=200) -> pd.DataFrame   # asof(), index=cik, plus yf_ticker column
    def universe(date, name) -> pd.DataFrame                   # name in {'SP1500','SP500','US_ALL'}; columns: cik, yf_ticker, gics_* , sic, index
    def market_cap(date, ciks) -> pd.Series                    # split-consistent: close(t) * shares * split_factor_after(shares_date)
    def benchmark_returns(tickers) -> pd.DataFrame
```
Strategy modules receive a `DataContext` and must not read cache files directly.

## Backtest layer (`quant/backtest/`)

- `metrics.py`, `stats.py`: API exactly as in research/06 §9 (port Appendix A; it is tested reference code).
- `engine.py`:
```python
@dataclass
class BacktestConfig:
    exec_lag: int = 1                 # trading days between signal close and trade close
    cost_bps: float = 10.0            # one-way
    stop_loss: float | None = None    # e.g. 0.15 -> sell a name when close <= entry_price*(1-0.15); proceeds to cash until next rebalance
    trend_exit_daily: bool = False    # sell a name when close < its 200d SMA (needs `sma` passed to run)
    vol_target: float | None = None   # annualized; exposure = min(vol_cap, vol_target / realized vol of the target book over vol_lookback days)
    vol_lookback: int = 126
    vol_cap: float = 1.0
    cash_earns_rf: bool = True

@dataclass
class BacktestResult:
    daily: pd.DataFrame      # index=date: ret_gross, ret_net, cost, turnover, exposure, n_holdings, cash_weight
    weights: pd.DataFrame    # end-of-day weights (date x ticker), optional/sparse
    trades: pd.DataFrame     # date, ticker, side, weight_traded, reason ('rebalance','stop','trend','delist')
    def monthly(self) -> pd.Series   # monthly net returns

def run(target_weights: pd.DataFrame, returns: pd.DataFrame, rf: pd.Series, cfg: BacktestConfig,
        close: pd.DataFrame | None = None, sma: pd.DataFrame | None = None) -> BacktestResult
    # target_weights: index = signal dates, columns = tickers, rows sum <= 1 (rest is cash). Missing row = hold.
def run_sleeves(target_weights: pd.DataFrame, hold_months: int, returns, rf, cfg) -> BacktestResult
    # each signal date opens a sleeve held `hold_months`; portfolio = equal weight of live sleeves (Jegadeesh-Titman overlap)
```
- `grid.py`: trial ledger + grid runner + plateau selection + train/test evaluation (wraps stats.py).
- `report.py`: tear sheet tables/charts per research/06 §8 (matplotlib, PNG into `output/<strategy>/`).

## Strategy layer

Each strategy module exposes:
```python
DEFAULT: dict                         # literature default parameters (the fallback)
GRID: list[dict]                      # pre-registered grid (also written to output/<strategy>/preregistration.json before running)
def target_weights(ctx: DataContext, params: dict, dates: list[pd.Timestamp]) -> pd.DataFrame
def backtest(ctx, params, start, end, cost_bps=10) -> BacktestResult
def live_picks(ctx, params, asof: pd.Timestamp) -> pd.DataFrame   # ranked picks with every input shown for audit
```
- QM: `quant/signals/technical.py`, `quant/signals/quality.py`, `quant/strategies/quality_momentum.py`
- MF: `quant/strategies/magic_formula.py`
- TC: `quant/signals/comps.py` (peers, multiples, discounts), `quant/signals/key_metrics.py` (ND/EBITDA, FCF, margin stability, ROIC, WACC, IPO/merger flags), `quant/strategies/trading_comps.py`
- Academic factor validation: `quant/data/factors.py`, `quant/validation/factor_checks.py`

## Evaluation protocol (all strategies)

Train window: first usable month (XBRL phase-in, ~2011-06) to 2018-12. Test window: 2019-01 to latest month.
Selection metric: net Sharpe on train. Plateau rule from research/06 §5.4. Confirm once on test.
Report: tear sheet (research/06 §8), FF5+MOM regression (HAC), DSR with the ledger's trial count, PBO (CSCV),
survivorship coverage audit and same-universe equal-weight benchmark, 13-day / 3m / 6m P(beat SPY).
