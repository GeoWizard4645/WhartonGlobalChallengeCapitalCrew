"""One object that hands strategies everything they need, point-in-time.

Strategies never read cache files directly; they ask a DataContext:
    ctx = DataContext.load()
    ctx.universe(date, "SP1500")      -> who was in the index on that date, with the GICS they had then
    ctx.fundamentals(date)            -> latest SEC filing data available before that date (filed < date)
    ctx.market_cap(date, ciks)        -> split-consistent market cap on that date
    ctx.close / ctx.adjclose / ctx.returns / ctx.rf

Market cap convention (research/03 §6.1, research/05): yfinance `Close` is split-adjusted to TODAY,
while SEC share counts are as reported on their own date. With F(d) = product of split ratios
with ex-date after d:
    close_adj(t) = P_raw(t) / F(t)          shares(t) = shares(d) * F(d) / F(t)
    market cap(t) = P_raw(t) * shares(t) = close_adj(t) * shares(d) * F(d)
"""
from __future__ import annotations

import logging
from functools import lru_cache

import numpy as np
import pandas as pd

from quant import settings

log = logging.getLogger(__name__)

SHARES_MAX_AGE_DAYS = 400       # cover-page share counts older than this are not trusted
MULTI_CLASS_RATIO = 1.2         # diluted shares this much above cover shares => cover page missed a class
MCAP_ASSETS_RANGE = (0.003, 100.0)  # market cap / total assets outside this => share-count scale error
SCALE_ERROR_RATIO = 3.0         # cover shares this much above diluted shares => cover value mis-scaled


class DataContext:
    def __init__(self, close, adjclose, volume, returns, rf, snaps, splits, meta=None):
        self.close = close
        self.adjclose = adjclose
        self.volume = volume
        self.returns = returns
        self.rf = rf
        self.snaps = snaps
        self.splits = splits
        self.meta = meta
        self.dates = close.index
        self._fund_cache: dict = {}
        self._snap_by_cik = None          # lazily built per-CIK cover-share history (market-cap sanity reference)
        self._aliases = None               # successor-registrant CIK pairs, loaded lazily
        self._univ_cache: dict = {}
        # ticker -> sorted split dates and suffix products, for F(d)
        # Two split indices. Yahoo back-adjusts `close` for EVERY ratio it reports, including spin-offs disguised as
        # fractional "splits" (ASH 2.044); only genuine splits change the share count. So:
        #   share counts -> today's basis with genuine splits only        (split_factor_after)
        #   close -> price as quoted on the day with all ratios             (price_factor_after)
        self._split_index = self._build_split_index(
            splits[splits["genuine"].astype(bool)] if "genuine" in splits.columns else splits)
        self._split_index_all = self._build_split_index(splits)

    @staticmethod
    def _build_split_index(splits: pd.DataFrame) -> dict:
        out = {}
        for t, g in splits.groupby("yf_ticker"):
            g = g.sort_values("date")
            d = g["date"].to_numpy(dtype="datetime64[ns]")
            r = g["ratio"].to_numpy(dtype=float)
            suffix = np.cumprod(r[::-1])[::-1]          # suffix[i] = product of ratios i..end
            out[t] = (d, np.append(suffix, 1.0))
        return out

    # ------------------------------------------------------------------ loading
    @classmethod
    def load(cls) -> "DataContext":
        from quant.data import fundamentals, prices

        close = prices.load_close()
        adjclose = prices.load_adjclose()
        volume = prices.load_volume()
        returns = _repair_spinoff_returns(prices.load_returns(), close)
        returns, close, adjclose = _cut_splices(returns, close, adjclose)
        rf = prices.rf_daily().reindex(close.index).ffill().fillna(0.0)
        snaps = fundamentals.load_snapshots()
        splits = prices.load_splits()
        try:
            meta = prices.load_meta()
        except Exception:  # meta is optional
            meta = None
        return cls(close, adjclose, volume, returns, rf, snaps, splits, meta)

    # ------------------------------------------------------------------ calendar
    def trading_day_on_or_before(self, date) -> pd.Timestamp:
        date = pd.Timestamp(date)
        i = self.dates.searchsorted(date, side="right") - 1
        if i < 0:
            raise ValueError(f"{date.date()} is before the first price date")
        return self.dates[i]

    def month_ends(self, start, end) -> list[pd.Timestamp]:
        """Last trading day of each calendar month in [start, end]."""
        d = self.dates[(self.dates >= pd.Timestamp(start)) & (self.dates <= pd.Timestamp(end))]
        s = pd.Series(d, index=d)
        return list(s.groupby([d.year, d.month]).max())

    # ------------------------------------------------------------------ fundamentals
    def fundamentals(self, date, max_age_days: int = 200) -> pd.DataFrame:
        """Latest snapshot per CIK with filed < date and period_end within max_age_days of date."""
        from quant.data.fundamentals import asof

        key = (pd.Timestamp(date), max_age_days)
        if key not in self._fund_cache:
            f = asof(self.snaps, key[0], max_age_days=max_age_days)
            # Sanitize (spec audit): negative debt is a tagging artefact (241 rows, e.g. DD 2019-21); it would pass
            # leverage gates and understate EV, so treat it as unknown.
            if "total_debt" in f.columns:
                neg = f["total_debt"] < 0
                if neg.any():
                    f = f.copy()
                    f.loc[neg, "total_debt"] = np.nan
            f = self._stitch_successors(f)
            self._fund_cache[key] = f
        return self._fund_cache[key]

    def _stitch_successors(self, f: pd.DataFrame) -> pd.DataFrame:
        """Successor registrants (holding-company reorganisations: XOM, BLK, BG, NWE, PNFP, Google -> Alphabet ...)
        file under a new CIK while index lists may still carry the old one (or vice versa). If one side of an
        alias pair has no usable snapshot on the date, reuse the other side's row (data audit item 6)."""
        if self._aliases is None:
            pairs = [(1288776, 1652044)]                       # Google Inc -> Alphabet (2016-06)
            path = settings.UNIV_DIR / "cik_aliases.csv"
            if path.exists():
                a = pd.read_csv(path)
                pairs += list(zip(a["old_cik"].astype(int), a["new_cik"].astype(int)))
            self._aliases = pairs
        add = {}
        for old, new in self._aliases:
            if old in f.index and new not in f.index:
                add[new] = f.loc[old]
            elif new in f.index and old not in f.index:
                add[old] = f.loc[new]
        if add:
            f = pd.concat([f, pd.DataFrame(add).T.astype(f.dtypes.to_dict(), errors="ignore")])
        return f

    # ------------------------------------------------------------------ universe
    def universe(self, date, name: str = "SP1500") -> pd.DataFrame:
        """Point-in-time universe with a usable price on `date`.

        SP1500 / SP900 / SP500 / SP400 / SP600: index members as of the latest snapshot <= date, with the GICS
        they had then. SP900 (= S&P 500 + MidCap 400) is the backtest universe: Wikipedia has S&P 400 history
        from 2011-03 but S&P 600 only from 2018-09, so SP1500 would change composition at the train/test split. US_ALL: today's listed US operating companies (survivorship-biased; secondary use only).
        """
        from quant.data import universe as U

        date = self.trading_day_on_or_before(date)
        key = (date, name)
        if key in self._univ_cache:
            return self._univ_cache[key]
        if name == "US_ALL":
            df = U.us_all().copy()
        else:
            idx = {"SP1500": ("SP500", "SP400", "SP600"), "SP900": ("SP500", "SP400"), "SP500": ("SP500",),
                   "SP400": ("SP400",), "SP600": ("SP600",)}[name]
            df = U.members(date, indexes=idx).copy()
        df = df[df["yf_ticker"].isin(self.close.columns)]
        px = self.close.loc[date, df["yf_ticker"]].to_numpy()
        df = df[np.isfinite(px) & (px > 0)]
        # one row per company (dual share classes): keep the first listed ticker
        if "cik" in df.columns:
            df = df.sort_values("yf_ticker").drop_duplicates("cik", keep="first")
        df = df.reset_index(drop=True)
        self._univ_cache[key] = df
        return df

    # ------------------------------------------------------------------ prices / market cap
    def price_factor_after(self, ticker: str, d) -> float:
        """Product of ALL Yahoo split ratios (incl. spin-off ratios) after d: close(d) * this = quoted price."""
        entry = self._split_index_all.get(ticker)
        if entry is None or pd.isna(d):
            return 1.0
        dates, suffix = entry
        i = np.searchsorted(dates, np.datetime64(pd.Timestamp(d), "ns"), side="right")
        return float(suffix[i])

    def split_factor_after(self, ticker: str, d) -> float:
        """Product of GENUINE split ratios with ex-date strictly after d (1.0 if none)."""
        entry = self._split_index.get(ticker)
        if entry is None or pd.isna(d):
            return 1.0
        dates, suffix = entry
        i = np.searchsorted(dates, np.datetime64(pd.Timestamp(d), "ns"), side="right")
        return float(suffix[i])

    def _cover_reference(self, cik: int, ticker: str, filed) -> float:
        """Median cover-page share count (today's split basis) over the company's filings in the 2 years
        before `filed` (strictly earlier, so point-in-time). NaN if none."""
        if self._snap_by_cik is None:
            cols = ["cik", "filed", "shares_out", "shares_out_date"]
            g = self.snaps[cols].dropna(subset=["shares_out", "shares_out_date"]).sort_values(["cik", "filed"])
            self._snap_by_cik = {c: d for c, d in g.groupby("cik")}
        h = self._snap_by_cik.get(cik)
        if h is None:
            return np.nan
        h = h[(h["filed"] < filed) & (h["filed"] >= filed - pd.Timedelta(days=730)) & (h["shares_out"] > 0)]
        if h.empty:
            return np.nan
        vals = [v * self.split_factor_after(ticker, d) for v, d in zip(h["shares_out"], h["shares_out_date"])]
        return float(np.median(vals))

    def shares_on(self, fund: pd.DataFrame, tickers: pd.Series) -> pd.DataFrame:
        """Pick a share count per company and put it on the current split basis.

        Returns columns shares_today_basis, shares_source. `fund` is a fundamentals() frame (index=cik)
        and `tickers` maps cik -> yf_ticker.

        Split basis dates: cover-page shares are counted on their cover date; weighted diluted shares are
        restated for any split that happens before the filing is issued (GAAP), so their basis date is the
        filing date, not the period end (research/05: NFLX 2015 is over-adjusted otherwise).

        Choice rule (fixed after the spec audit found 243 picks of a mis-scaled count):
          * cover and diluted within 20%: cover (more recent count).
          * diluted 1.2x-3x cover: diluted (cover page listed only one share class, e.g. GOOGL, META).
          * they disagree by more than 3x (one is mis-scaled by ~1e3/1e6, e.g. PKG cover x1000, KO/MCD diluted
            tagged in thousands): take the one closest (in log terms) to the company's own median cover count
            over the prior two years (point-in-time); with no history, trust the builder-vetted cover count.
          * only one available: use it, unless it is >5x away from that reference, in which case it is
            rescaled by the power of 1000 that brings it back (flag 'rescaled').
        """
        out = []
        for cik, row in fund.iterrows():
            t = tickers.get(cik)
            if t is None:
                continue
            cover, cover_d = row.get("shares_out"), row.get("shares_out_date")
            dil, dil_d = row.get("shares_diluted"), row.get("filed")
            cover_ok = pd.notna(cover) and cover > 0 and pd.notna(cover_d) and \
                (row["filed"] - cover_d).days <= SHARES_MAX_AGE_DAYS
            dil_ok = pd.notna(dil) and dil > 0
            cover_adj = cover * self.split_factor_after(t, cover_d) if cover_ok else np.nan
            dil_adj = dil * self.split_factor_after(t, dil_d) if dil_ok else np.nan
            if cover_ok and self.split_factor_after(t, cover_d) != self.split_factor_after(t, row["filed"]):
                # a genuine split happened between the count's date and the filing: some filers report the
                # count pre-split, others restate it (GOOGL 2022-07 balance-sheet count, 20x off otherwise).
                # Keep whichever basis agrees with the filing-date diluted count (or the share history).
                alt = cover * self.split_factor_after(t, row["filed"])
                anchor = dil_adj if dil_ok else self._cover_reference(cik, t, row["filed"])
                if np.isfinite(anchor) and anchor > 0 and abs(np.log(alt / anchor)) < abs(np.log(cover_adj / anchor)):
                    cover_adj = alt
            if not dil_ok:                                     # basic weighted shares as a second fallback
                bas = row.get("shares_basic")
                if pd.notna(bas) and bas > 0:
                    dil_ok, dil_adj = True, bas * self.split_factor_after(t, dil_d)
            if cover_ok and dil_ok:
                r = dil_adj / cover_adj
                if 1 / MULTI_CLASS_RATIO <= r <= MULTI_CLASS_RATIO:
                    shares, src = cover_adj, "cover"
                elif MULTI_CLASS_RATIO < r <= SCALE_ERROR_RATIO:
                    shares, src = dil_adj, "diluted(multi-class?)"
                else:
                    ref = self._cover_reference(cik, t, row["filed"])
                    if np.isfinite(ref) and ref > 0 and abs(np.log(dil_adj / ref)) < abs(np.log(cover_adj / ref)):
                        shares, src = dil_adj, "diluted(cover mis-scaled vs history)"
                    else:
                        shares, src = cover_adj, "cover(diluted mis-scaled)"
            elif cover_ok or dil_ok:
                shares, src = (cover_adj, "cover") if cover_ok else (dil_adj, "diluted")
                ref = self._cover_reference(cik, t, row["filed"])
                if np.isfinite(ref) and ref > 0 and abs(np.log10(shares / ref)) > np.log10(5):
                    k = round(np.log10(ref / shares) / 3) * 3          # nearest power of 1000
                    if k != 0 and abs(np.log10(shares * 10.0 ** k / ref)) < np.log10(2):
                        shares, src = shares * 10.0 ** k, src + "(rescaled)"
            else:
                ref = self._cover_reference(cik, t, row["filed"])   # carry the company's recent count (PIT)
                shares, src = (ref, "carried") if np.isfinite(ref) and ref > 0 else (np.nan, "missing")
            out.append((cik, t, shares, src))
        return pd.DataFrame(out, columns=["cik", "yf_ticker", "shares_today_basis", "shares_source"]).set_index("cik")

    def market_cap(self, date, univ: pd.DataFrame | None = None, max_age_days: int = 200) -> pd.DataFrame:
        """Market cap on `date` for every company in `univ` (default SP1500) that has fundamentals.

        Returns index=cik with yf_ticker, price (split-adjusted close), shares_today_basis, shares_source, mcap.
        """
        date = self.trading_day_on_or_before(date)
        if univ is None:
            univ = self.universe(date, "SP1500")
        fund = self.fundamentals(date, max_age_days)
        tick = univ.set_index("cik")["yf_ticker"]
        fund = fund[fund.index.isin(tick.index)]
        sh = self.shares_on(fund, tick)
        sh["price"] = self.close.loc[date, sh["yf_ticker"]].to_numpy()
        f_all = np.array([self.price_factor_after(t, date) for t in sh["yf_ticker"]])
        f_gen = np.array([self.split_factor_after(t, date) for t in sh["yf_ticker"]])
        sh["price_raw"] = sh["price"] * f_all                      # as quoted on `date`
        # shares are on today's GENUINE-split basis; put them back on `date`'s basis (/ f_gen) and use the quoted
        # price. Equivalent to price * shares when no spin-off ratio follows `date` (backtest audit F3).
        sh["mcap"] = sh["price_raw"] * sh["shares_today_basis"] / f_gen
        # Plausibility guard (re-audit): market value outside [0.003x, 100x] of book assets is a share-count scale
        # error (LAMR 2012-14 at $4T, GRMN/FOXA/BKR 1000x low), not a valuation. Treat as unknown.
        assets = fund.reindex(sh.index)["assets"] if "assets" in fund.columns else None
        if assets is not None:
            ratio = sh["mcap"] / assets
            bad = assets.gt(0) & sh["mcap"].notna() & ~ratio.between(MCAP_ASSETS_RANGE[0], MCAP_ASSETS_RANGE[1])
            if bad.any():
                sh.loc[bad, "shares_source"] = sh.loc[bad, "shares_source"].astype(str) + "(implausible: dropped)"
                sh.loc[bad, "mcap"] = np.nan
        return sh

    def as_traded_price(self, date, tickers) -> pd.Series:
        """Price as it was quoted on `date` (undo later splits): split-adjusted close * F(date)."""
        date = self.trading_day_on_or_before(date)
        tickers = pd.Index(tickers)
        px = self.close.loc[date, tickers]
        f = np.array([self.price_factor_after(t, date) for t in tickers])
        return pd.Series(px.to_numpy() * f, index=tickers)

    def benchmark_returns(self, tickers) -> pd.DataFrame:
        return self.returns[[t for t in tickers if t in self.returns.columns]]

    def ew_universe(self, start, end, name: str = "SP1500", min_price: float = 5.0,
                    exclude_sectors: tuple = (), cost_bps: float = 10.0):
        """Same-universe equal-weight benchmark, rebalanced monthly with the engine's timing.

        This is the like-for-like control for survivorship bias (research/06 §6.2): it has the same
        missing-delisted-stock problem as the strategies, so strategy minus this is roughly bias-neutral.
        Returns the engine BacktestResult.
        """
        from quant.backtest import engine

        rows = {}
        for d in self.month_ends(start, end):
            u = self.universe(d, name)
            if exclude_sectors and "gics_sector" in u.columns:
                u = u[~u["gics_sector"].isin(exclude_sectors)]
            px = self.as_traded_price(d, u["yf_ticker"])
            tick = px[px >= min_price].index
            if len(tick):
                rows[d] = pd.Series(1.0 / len(tick), index=tick)
        w = pd.DataFrame(rows).T.fillna(0.0)
        return engine.run(w, self.returns, self.rf, engine.BacktestConfig(cost_bps=cost_bps))


def _spinoff_events() -> set:
    """(ticker, date) where raw Yahoo books BOTH a split ratio and a dividend on one ex-date: that is how Yahoo
    records many spin-offs (DHR 2016-07-05: split 1.319 + dividend 24.56) and then double-adjusts Adj Close."""
    import pyarrow.dataset as ds

    path = settings.PRICE_DIR / "raw" / "base.parquet"
    if not path.exists():
        return set()
    t = ds.dataset(path).to_table(columns=["yf_ticker", "date", "dividend", "split"],
                                  filter=(ds.field("dividend") > 0) & (ds.field("split") > 0)).to_pandas()
    return {(r.yf_ticker, pd.Timestamp(r.date).normalize()) for r in t.itertuples()}


def _repair_spinoff_returns(returns: pd.DataFrame, close: pd.DataFrame, tol: float = 0.10) -> pd.DataFrame:
    """Repair Yahoo's double adjustment at spin-offs booked as split + dividend on the same ex-date (DHR 2016,
    XRX 2017, EXPE 2011, TMUS 2013): on those days only, if total and price return differ by more than `tol`,
    keep the price return (`close` is already continuous across the event). Ordinary special dividends are
    NOT touched (data audit: a blanket rule turned KDP 2018-07-10 into -82%)."""
    events = _spinoff_events()
    n = 0
    returns = returns.copy()
    for tk, d in events:
        if tk not in returns.columns or d not in returns.index:
            continue
        i = close.index.get_loc(d)
        if i == 0:
            continue
        c0, c1 = close[tk].iloc[i - 1], close[tk].iloc[i]
        if not (np.isfinite(c0) and np.isfinite(c1) and c0 > 0):
            continue
        rc = c1 / c0 - 1
        ra = returns.at[d, tk]
        if np.isfinite(ra) and abs(ra - rc) > tol:
            returns.at[d, tk] = rc
            n += 1
    if n:
        log.info("repaired %d double-adjusted spin-off returns", n)
    return returns


def _cut_splices(returns: pd.DataFrame, close: pd.DataFrame, adjclose: pd.DataFrame, limit: float = 10.0):
    """A one-day return above +1000% is not a trade, it is two securities spliced together (CHRD 2020-11-20:
    old Oasis equity at $0.12 joined to the post-bankruptcy shares at $31, +25,733%). Treat the series as a
    new security from that day: drop the jump and all earlier prices."""
    hits = np.argwhere(returns.to_numpy() > limit)
    if len(hits):
        log.info("cut %d spliced price histories (one-day returns above +%.0f%%, almost all microcaps)",
                 len(hits), 100 * limit)
    for i, j in hits:
        tk, d = returns.columns[j], returns.index[i]
        log.debug("splice cut: %s %s return %.0f%%", tk, d.date(), 100 * returns.iat[i, j])
        returns.iloc[: i + 1, j] = np.nan
        close.loc[:returns.index[i - 1] if i else d, tk] = np.nan
        adjclose.loc[:returns.index[i - 1] if i else d, tk] = np.nan
    return returns, close, adjclose


@lru_cache(maxsize=1)
def get_context() -> DataContext:
    """Process-wide cached context (loading prices + snapshots takes a few seconds)."""
    return DataContext.load()
