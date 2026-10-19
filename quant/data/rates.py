"""10-year Treasury constant-maturity yield (risk-free rate for Ke / WACC).

Source of truth: FRED series DGS10 (https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10), a daily series in
percent that FRED leaves blank on bond-market holidays.  It is cached to ``cache/prices/dgs10.parquet`` as a decimal
(0.0425 = 4.25%) and forward-filled over holidays, so ``ten_year(date)`` is a plain as-of lookup:

    ten_year(date)  -> float, the last yield observed on or before ``date`` (None -> latest available)
    load_dgs10()    -> pd.Series, index = date (daily, ascending), values = decimal yield

Fallback (only when FRED is unreachable): Yahoo's ``^TNX`` (CBOE 10-year yield index, quoted in percent), which
tracks DGS10 to within a couple of basis points.  The cache records which source produced it (``source`` column);
FRED is retried (once per process) when the cache is older than ``MAX_AGE_DAYS`` days of data (at most every 6 h) or
came from the fallback (at most every 24 h).  Point-in-time note: the value on day t is the yield at the close of t (H.15 publishes it the next
morning, but the number is observable at the close from any market feed), consistent with prices being usable
through the close of t.

No look-ahead: ``ten_year(date)`` never returns an observation dated after ``date``.
"""
from __future__ import annotations

import io
import logging
import os
import time

import numpy as np
import pandas as pd

from quant.settings import PRICE_DIR

log = logging.getLogger(__name__)

FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DGS10"
DGS10_PATH = PRICE_DIR / "dgs10.parquet"
MAX_AGE_DAYS = 7                    # re-download when the cache is older than this (and we are online)
FRED_TIMEOUT = (5, 20)              # (connect, read) seconds; FRED is occasionally slow
USER_AGENT = "CapitalCrewResearch/1.0 (student investment-competition project)"

_MEM: dict[str, pd.Series] = {}     # in-process cache
_TRIED_REFRESH = {"done": False}    # at most one network refresh attempt per process


# ----------------------------------------------------------------------------------------------
# Parsing / cleaning (pure functions, unit-tested without network)
# ----------------------------------------------------------------------------------------------
def parse_fred_csv(text: str) -> pd.Series:
    """FRED graph CSV -> decimal series (NaN where FRED has '.').  Accepts 'DATE' or 'observation_date' headers."""
    df = pd.read_csv(io.StringIO(text), na_values=[".", ""])
    dcol = df.columns[0]
    vcol = "DGS10" if "DGS10" in df.columns else df.columns[1]
    s = pd.Series(pd.to_numeric(df[vcol], errors="coerce").to_numpy() / 100.0,
                  index=pd.to_datetime(df[dcol]).dt.normalize(), name="dgs10")
    s = s[~s.index.duplicated(keep="last")].sort_index()
    return s


def clean_daily(s: pd.Series) -> pd.Series:
    """Drop impossible values (unit mistakes), sort, forward-fill holidays and drop leading gaps."""
    s = s.astype(float).sort_index()
    s = s[~s.index.duplicated(keep="last")]
    s[(s <= -0.05) | (s > 0.30)] = np.nan
    return s.ffill().dropna().rename("dgs10")


# ----------------------------------------------------------------------------------------------
# Download
# ----------------------------------------------------------------------------------------------
def _download_fred() -> pd.Series:
    import requests

    r = requests.get(FRED_URL, timeout=FRED_TIMEOUT, headers={"User-Agent": USER_AGENT})
    r.raise_for_status()
    s = parse_fred_csv(r.text)
    if s.dropna().shape[0] < 1000:
        raise ValueError("FRED DGS10 download looks truncated")
    return s


def _download_yahoo() -> pd.Series:
    import yfinance as yf

    d = yf.download("^TNX", start="2008-01-01", progress=False, auto_adjust=False)
    if d is None or len(d) == 0:
        raise ValueError("Yahoo ^TNX returned nothing")
    c = d["Close"]
    if isinstance(c, pd.DataFrame):
        c = c.iloc[:, 0]
    s = (c.astype(float) / 100.0).round(6)             # ^TNX is quoted in percent (4.25 = 4.25%)
    s.index = pd.to_datetime(s.index).tz_localize(None).normalize()
    return s.rename("dgs10")


def _write_cache(s: pd.Series, source: str) -> None:
    DGS10_PATH.parent.mkdir(parents=True, exist_ok=True)
    out = s.rename("dgs10").rename_axis("date").reset_index()
    out["source"] = source
    tmp = DGS10_PATH.with_name(DGS10_PATH.name + f".tmp{os.getpid()}")
    out.to_parquet(tmp, index=False)
    os.replace(tmp, DGS10_PATH)                       # atomic: concurrent readers never see a partial file


def _read_cache() -> tuple[pd.Series, str] | None:
    if not DGS10_PATH.exists():
        return None
    df = pd.read_parquet(DGS10_PATH)
    s = pd.Series(df["dgs10"].to_numpy(dtype=float), index=pd.to_datetime(df["date"]), name="dgs10")
    src = str(df["source"].iloc[0]) if "source" in df.columns and len(df) else "unknown"
    return s.sort_index(), src


def refresh_dgs10() -> pd.Series:
    """Download (FRED, falling back to Yahoo ^TNX), clean, cache to parquet, and return the series."""
    source, raw = "fred", None
    try:
        raw = _download_fred()
    except Exception as e:  # network down / blocked / FRED slow
        log.warning("FRED DGS10 download failed (%s: %s); falling back to Yahoo ^TNX", type(e).__name__, e)
        source = "yahoo_tnx"
        raw = _download_yahoo()
    s = clean_daily(raw)
    _write_cache(s, source)
    log.info("DGS10 cached from %s: %d obs, %s .. %s", source, len(s), s.index[0].date(), s.index[-1].date())
    return s


# ----------------------------------------------------------------------------------------------
# Public API
# ----------------------------------------------------------------------------------------------
def load_dgs10(refresh: bool = False) -> pd.Series:
    """Daily 10-year yield as a decimal Series (index = date, forward-filled over holidays).

    Uses the parquet cache; downloads when it is missing, when ``refresh`` is True, or (once per process) when the
    cache is older than ``MAX_AGE_DAYS`` or came from the Yahoo fallback.
    """
    if not refresh and "s" in _MEM:
        return _MEM["s"]
    cached = _read_cache()
    need = refresh or cached is None
    if cached is not None and not need and not _TRIED_REFRESH["done"]:
        s0, src = cached
        file_age = time.time() - DGS10_PATH.stat().st_mtime
        stale = (pd.Timestamp.today().normalize() - s0.index[-1]).days > MAX_AGE_DAYS
        # retry the network at most every 6 h when stale, every 24 h when the cache came from the Yahoo fallback
        if (stale and file_age > 6 * 3600) or (src != "fred" and file_age > 24 * 3600):
            need = True
    if need:
        _TRIED_REFRESH["done"] = True
        try:
            s = refresh_dgs10()
            _MEM["s"] = s
            return s
        except Exception as e:
            if cached is None:
                raise RuntimeError(f"cannot load DGS10: no cache and download failed ({e})") from e
            log.warning("DGS10 refresh failed (%s); using the cache", e)
    s = cached[0] if cached is not None else load_dgs10(refresh=True)
    _MEM["s"] = s
    return s


def ten_year(date=None) -> float:
    """10-year Treasury yield (decimal) as of ``date`` (last observation on or before it); None -> latest."""
    s = load_dgs10()
    if date is None:
        return float(s.iloc[-1])
    d = pd.Timestamp(date).normalize()
    i = s.index.searchsorted(d, side="right") - 1
    if i < 0:
        return float(s.iloc[0])           # before the first observation: use the first one (1962+ in FRED)
    return float(s.iloc[i])
