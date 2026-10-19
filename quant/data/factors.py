"""Ken French and AQR factor data: download, cache (parquet) and parse into DECIMAL returns.

Everything here is the long-history, survivorship-free (CRSP-based) academic evidence layer.
It is used to sanity-check the three strategy ideas at the factor level (1926-2026) and to
measure how much each premium decayed after publication (see ``quant/validation/factor_checks.py``).

Conventions
-----------
* All returns are DECIMALS (0.01 = 1%). French's files are in percent; we divide by 100.
* ``-99.99`` / ``-999`` (French's missing-data codes) become NaN.
* Monthly series are indexed by the MONTH-END calendar date (``Timestamp`` normalized, no tz);
  daily series by the trading day.
* Portfolio columns are renamed to short stable names (``D1..D10``, ``BM1_OP1..BM5_OP5``, ...).
* Parsed frames are cached as parquet in ``cache/factors/`` (``FACTOR_DIR``). A cache entry younger
  than ``max_age_days`` is used as is; an older one is refreshed, and if the refresh fails the stale
  copy is used with a warning. ``force=True`` always re-downloads.

Public API (all return pandas objects; ``freq`` is ``'M'`` or ``'D'``)
----------------------------------------------------------------------
``ff5(freq)``                 Mkt-RF, SMB, HML, RMW, CMA, RF      (2x3 sorts, from 1963-07)
``ff3(freq)``                 Mkt-RF, SMB, HML, RF                (from 1926-07)
``mom(freq)``                 DataFrame with one column ``Mom``   (French 2x3 factor, from 1927-01 / 1926-11-03)
``market(freq)``              Series ``Mkt`` = Mkt-RF + RF (total market return)
``mom_deciles(freq, weighting='vw'|'ew')``  D1 (losers) .. D10 (winners), TOTAL returns (not excess)
``bm_op_25(freq='M', weighting='vw')``      25 portfolios ``BM{1..5}_OP{1..5}`` (BM5_OP5 = high B/M, high OP), from 1963-07
``ep_portfolios(weighting='vw')``           E/P sorts: ``neg, Lo30, Med40, Hi30, Q1..Q5, D1..D10`` (from 1951-07)
``qmj(freq='M', region='USA')``             AQR Quality-Minus-Junk factor, Series ``QMJ`` (monthly only, from 1957-07)
``ff_factors_for_regression(freq)``         Mkt-RF, SMB, HML, RMW, CMA, Mom, RF
``download_all(force)``                     fetch everything, return a status table (never raises)
"""
from __future__ import annotations

import io
import logging
import re
import time
import zipfile
from dataclasses import dataclass
from pathlib import Path
from typing import Callable

import numpy as np
import pandas as pd
import requests

from quant.settings import FACTOR_DIR

log = logging.getLogger(__name__)

FRENCH_BASE = "https://mba.tuck.dartmouth.edu/pages/faculty/ken.french/ftp/"
AQR_QMJ_MONTHLY_URL = (
    "https://www.aqr.com/-/media/AQR/Documents/Insights/Data-Sets/Quality-Minus-Junk-Factors-Monthly.xlsx"
)
# A normal browser User-Agent (some CDNs reject python-requests' default).
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0 Safari/537.36"
)
DEFAULT_MAX_AGE_DAYS = 30.0
_MAX_UNCOMPRESSED_BYTES = 400 * 1024 * 1024

# French file names (zip) on the data library.
F_FF5_M = "F-F_Research_Data_5_Factors_2x3_CSV.zip"
F_FF5_D = "F-F_Research_Data_5_Factors_2x3_daily_CSV.zip"
F_FF3_M = "F-F_Research_Data_Factors_CSV.zip"
F_FF3_D = "F-F_Research_Data_Factors_daily_CSV.zip"
F_MOM_M = "F-F_Momentum_Factor_CSV.zip"
F_MOM_D = "F-F_Momentum_Factor_daily_CSV.zip"
F_DEC_M = "10_Portfolios_Prior_12_2_CSV.zip"
F_DEC_D = "10_Portfolios_Prior_12_2_Daily_CSV.zip"
F_BMOP_M = "25_Portfolios_BEME_OP_5x5_CSV.zip"
F_BMOP_D = "25_Portfolios_BEME_OP_5x5_daily_CSV.zip"
F_EP_M = "Portfolios_Formed_on_E-P_CSV.zip"


class FactorDataUnavailable(RuntimeError):
    """A factor dataset could not be downloaded and no cached copy exists."""


# --------------------------------------------------------------------------------------
# Parsing of French's multi-block CSV files
# --------------------------------------------------------------------------------------
_DATA_ROW = re.compile(r"^\s*(\d{4}|\d{6}|\d{8})\s*,(.*)$")
_FREQ_BY_KEYLEN = {4: "A", 6: "M", 8: "D"}


@dataclass
class FrenchBlock:
    """One block of a French CSV: a title line, a column header line and a run of data rows."""

    title: str
    freq: str  # 'A' annual, 'M' monthly, 'D' daily
    data: pd.DataFrame  # DECIMAL values, NaN for missing, DatetimeIndex


def _keys_to_index(keys: list[int], freq: str) -> pd.DatetimeIndex:
    s = pd.Series(keys).astype(str)
    if freq == "M":
        idx = pd.to_datetime(s, format="%Y%m") + pd.offsets.MonthEnd(0)
    elif freq == "D":
        idx = pd.to_datetime(s, format="%Y%m%d")
    elif freq == "A":
        idx = pd.to_datetime(s, format="%Y") + pd.offsets.YearEnd(0)
    else:  # pragma: no cover
        raise ValueError(freq)
    return pd.DatetimeIndex(idx, name="date")


def _row_values(rest: str, ncols: int) -> list[float]:
    parts = [p.strip() for p in rest.split(",")]
    out = []
    for p in parts[:ncols]:
        try:
            out.append(float(p) if p != "" else np.nan)
        except ValueError:
            out.append(np.nan)
    out += [np.nan] * (ncols - len(out))
    return out


def parse_french_blocks(text: str) -> list[FrenchBlock]:
    """Split the text of a French CSV into blocks (annual blocks, monthly blocks, EW/VW blocks, ...).

    A block is a column header line (starts with a comma), directly followed by data rows whose first
    field is YYYY (annual), YYYYMM (monthly) or YYYYMMDD (daily). The block ends at the first line that
    is not a data row. The title is the nearest non-empty text line before the header. Values are
    converted from percent to decimals; ``-99.99`` and ``-999`` (anything <= -99) become NaN.
    """
    lines = text.splitlines()
    n = len(lines)
    blocks: list[FrenchBlock] = []
    last_title = ""
    i = 0
    while i < n:
        s = lines[i].strip()
        if s.startswith(",") and i + 1 < n and _DATA_ROW.match(lines[i + 1]):
            cols = [c.strip() for c in s.split(",")[1:]]
            keys: list[int] = []
            rows: list[list[float]] = []
            j = i + 1
            keylen = len(_DATA_ROW.match(lines[j]).group(1))
            while j < n:
                m = _DATA_ROW.match(lines[j])
                if not m or len(m.group(1)) != keylen:
                    break
                keys.append(int(m.group(1)))
                rows.append(_row_values(m.group(2), len(cols)))
                j += 1
            freq = _FREQ_BY_KEYLEN[keylen]
            arr = np.array(rows, dtype=float)
            arr[arr <= -99.0] = np.nan
            df = pd.DataFrame(arr / 100.0, index=_keys_to_index(keys, freq), columns=cols)
            df = df[~df.index.duplicated(keep="first")].sort_index()
            blocks.append(FrenchBlock(title=last_title, freq=freq, data=df))
            i = j
            continue
        if s and not s.startswith(","):
            last_title = s
        i += 1
    return blocks


def parse_french_csv(text: str, freq: str = "M", title: str | None = None) -> pd.DataFrame:
    """Return the first block of the given frequency whose title matches the regex ``title``
    (case-insensitive ``re.search``); ``title=None`` accepts any block of that frequency."""
    blocks = parse_french_blocks(text)
    pat = re.compile(title, re.I) if title else None
    for b in blocks:
        if b.freq == freq and (pat is None or pat.search(b.title)):
            return b.data.copy()
    raise ValueError(
        f"no {freq!r} block with title ~ {title!r}; found "
        f"{[(b.freq, b.title) for b in blocks][:12]}"
    )


def _ret_title(weighting: str, freq: str) -> str:
    """Regex for the title of the returns block: 'Average Value Weighted Returns -- Monthly',
    'Value Weight Returns -- Monthly', 'Equal Weight Returns -- Daily', ..."""
    f = {"M": "monthly", "D": "daily"}[freq]
    w = r"value[- ]weight(?:ed)?" if weighting == "vw" else r"equal[- ]weight(?:ed)?"
    return rf"^(?:average\s+)?{w}\s+returns\s*--\s*{f}"


# --------------------------------------------------------------------------------------
# Download + cache plumbing
# --------------------------------------------------------------------------------------
def http_get(url: str, retries: int = 4, timeout: float = 90.0) -> bytes:
    """GET with a browser User-Agent and exponential-backoff retries on network errors, 429 and 5xx."""
    headers = {"User-Agent": USER_AGENT, "Accept": "*/*"}
    last: Exception | None = None
    for attempt in range(retries):
        try:
            r = requests.get(url, headers=headers, timeout=timeout)
            if r.status_code == 200 and r.content:
                return r.content
            if r.status_code in (429, 500, 502, 503, 504):
                last = RuntimeError(f"HTTP {r.status_code} for {url}")
            else:
                raise RuntimeError(f"HTTP {r.status_code} for {url}")
        except requests.RequestException as exc:
            last = exc
        if attempt < retries - 1:
            time.sleep(2.0 ** attempt)
    raise RuntimeError(f"download failed after {retries} attempts: {url}: {last}")


def _zip_text(content: bytes) -> str:
    """Decode the single CSV/TXT member of a downloaded zip (in memory; nothing is extracted to disk)."""
    with zipfile.ZipFile(io.BytesIO(content)) as z:
        members = [i for i in z.infolist() if i.filename.lower().endswith((".csv", ".txt"))]
        if not members:
            raise ValueError("zip has no csv/txt member")
        info = members[0]
        if info.file_size > _MAX_UNCOMPRESSED_BYTES:
            raise ValueError(f"refusing to read {info.file_size} bytes from {info.filename}")
        return z.read(info).decode("latin-1")


_TEXT_MEMO: dict[str, str] = {}


def _french_text(fname: str, force: bool = False) -> str:
    """Text of a French zip, downloaded at most once per process (unless ``force``)."""
    if force:
        _TEXT_MEMO.pop(fname, None)
    if fname not in _TEXT_MEMO:
        _TEXT_MEMO[fname] = _zip_text(http_get(FRENCH_BASE + fname))
    return _TEXT_MEMO[fname]


def _cache_path(key: str) -> Path:
    return FACTOR_DIR / f"{key}.parquet"


def _cached(key: str, builder: Callable[[], pd.DataFrame], force: bool, max_age_days: float) -> pd.DataFrame:
    path = _cache_path(key)
    if path.exists() and not force:
        age_days = (time.time() - path.stat().st_mtime) / 86400.0
        if age_days <= max_age_days:
            return pd.read_parquet(path)
    try:
        df = builder()
    except Exception as exc:  # network, parsing, layout change ...
        if path.exists():
            log.warning("refresh of %s failed (%s); using stale cache %s", key, exc, path)
            return pd.read_parquet(path)
        raise FactorDataUnavailable(f"{key}: {exc}") from exc
    FACTOR_DIR.mkdir(parents=True, exist_ok=True)
    df.to_parquet(path)
    log.info("cached %s (%d rows, %s .. %s)", key, len(df), df.index.min().date(), df.index.max().date())
    return df


def _check_freq(freq: str) -> str:
    f = str(freq).upper()
    if f not in ("M", "D"):
        raise ValueError(f"freq must be 'M' or 'D', got {freq!r}")
    return f


def _check_weighting(weighting: str) -> str:
    w = str(weighting).lower()
    if w not in ("vw", "ew"):
        raise ValueError(f"weighting must be 'vw' or 'ew', got {weighting!r}")
    return w


def _french_frame(
    key: str,
    fname: str,
    freq: str,
    title: str | None = None,
    rename: Callable[[list[str]], list[str]] | None = None,
    *,
    force: bool = False,
    max_age_days: float = DEFAULT_MAX_AGE_DAYS,
) -> pd.DataFrame:
    def build() -> pd.DataFrame:
        df = parse_french_csv(_french_text(fname, force=force), freq=freq, title=title)
        if rename is not None:
            df.columns = rename(list(df.columns))
        if df.index.has_duplicates or not df.index.is_monotonic_increasing:
            raise ValueError(f"{fname}: index not unique/monotonic")
        return df

    return _cached(key, build, force, max_age_days)


# --------------------------------------------------------------------------------------
# Column naming
# --------------------------------------------------------------------------------------
def _decile_cols(cols: list[str]) -> list[str]:
    if len(cols) != 10:
        raise ValueError(f"expected 10 decile columns, got {cols}")
    return [f"D{i}" for i in range(1, 11)]  # D1 = 'Lo PRIOR' (losers) ... D10 = 'Hi PRIOR' (winners)


def _bmop_cols(cols: list[str]) -> list[str]:
    if len(cols) != 25:
        raise ValueError(f"expected 25 BM x OP columns, got {len(cols)}")
    # French's order: BM1 OP1..OP5, BM2 OP1..OP5, ... BM5 OP1..OP5 (first and last labelled LoBM LoOP ... HiBM HiOP)
    return [f"BM{b}_OP{o}" for b in range(1, 6) for o in range(1, 6)]


_EP_COLS = (
    ["neg", "Lo30", "Med40", "Hi30"] + ["Q1", "Q2", "Q3", "Q4", "Q5"] + [f"D{i}" for i in range(1, 11)]
)


def _ep_cols(cols: list[str]) -> list[str]:
    if len(cols) != len(_EP_COLS):
        raise ValueError(f"expected {len(_EP_COLS)} E/P columns, got {cols}")
    return list(_EP_COLS)


# --------------------------------------------------------------------------------------
# Public API
# --------------------------------------------------------------------------------------
def ff5(freq: str = "M", *, force: bool = False, max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> pd.DataFrame:
    """Fama-French 5 factors (2x3): Mkt-RF, SMB, HML, RMW, CMA, RF. Monthly from 1963-07, daily from 1963-07-01."""
    f = _check_freq(freq)
    return _french_frame(f"ff5_{f}", F_FF5_M if f == "M" else F_FF5_D, f, force=force, max_age_days=max_age_days)


def ff3(freq: str = "M", *, force: bool = False, max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> pd.DataFrame:
    """Fama-French 3 factors: Mkt-RF, SMB, HML, RF. Monthly from 1926-07, daily from 1926-07-01."""
    f = _check_freq(freq)
    return _french_frame(f"ff3_{f}", F_FF3_M if f == "M" else F_FF3_D, f, force=force, max_age_days=max_age_days)


def mom(freq: str = "M", *, force: bool = False, max_age_days: float = DEFAULT_MAX_AGE_DAYS) -> pd.DataFrame:
    """French's momentum factor (2x3 on size and prior 12-2 return; DataFrame with one column ``Mom``).

    NOT the decile spread D10-D1 (that is built from :func:`mom_deciles`; it has about 1.7x the volatility)."""
    f = _check_freq(freq)
    df = _french_frame(f"mom_{f}", F_MOM_M if f == "M" else F_MOM_D, f, force=force, max_age_days=max_age_days)
    df.columns = ["Mom"]
    return df


def market(freq: str = "M", **kw) -> pd.Series:
    """Total CRSP value-weighted market return (``Mkt-RF + RF``), 1926-07 onwards."""
    f = ff3(freq, **kw)
    return (f["Mkt-RF"] + f["RF"]).rename("Mkt")


def mom_deciles(
    freq: str = "M", weighting: str = "vw", *, force: bool = False, max_age_days: float = DEFAULT_MAX_AGE_DAYS
) -> pd.DataFrame:
    """10 portfolios formed on prior 12-2 return. ``D1`` = losers, ``D10`` = winners; TOTAL (not excess) returns.

    Monthly from 1927-01 (formed monthly on months -12..-2); daily from 1926-11-03 (formed daily on days -250..-21).
    ``weighting``: ``'vw'`` value-weighted (Daniel-Moskowitz / Barroso-Santa-Clara) or ``'ew'`` equal-weighted."""
    f, w = _check_freq(freq), _check_weighting(weighting)
    return _french_frame(
        f"mom_deciles_{f}_{w}", F_DEC_M if f == "M" else F_DEC_D, f, _ret_title(w, f), _decile_cols,
        force=force, max_age_days=max_age_days,
    )


def bm_op_25(
    freq: str = "M", weighting: str = "vw", *, force: bool = False, max_age_days: float = DEFAULT_MAX_AGE_DAYS
) -> pd.DataFrame:
    """25 portfolios formed on B/M x operating profitability (5x5, formed each June). Total returns.

    Columns ``BM{b}_OP{o}`` with b, o in 1..5 (5 = highest). ``BM5_OP5`` = high B/M and high profitability."""
    f, w = _check_freq(freq), _check_weighting(weighting)
    return _french_frame(
        f"bm_op_25_{f}_{w}", F_BMOP_M if f == "M" else F_BMOP_D, f, _ret_title(w, f), _bmop_cols,
        force=force, max_age_days=max_age_days,
    )


def ep_portfolios(
    weighting: str = "vw", *, force: bool = False, max_age_days: float = DEFAULT_MAX_AGE_DAYS
) -> pd.DataFrame:
    """Monthly portfolios formed on E/P (positive-earnings sorts, formed each June), from 1951-07. Total returns.

    Columns: ``neg`` (E/P <= 0), ``Lo30, Med40, Hi30``, quintiles ``Q1..Q5`` (Q5 = highest E/P), deciles ``D1..D10``."""
    w = _check_weighting(weighting)
    return _french_frame(
        f"ep_portfolios_M_{w}", F_EP_M, "M", _ret_title(w, "M"), _ep_cols, force=force, max_age_days=max_age_days
    )


def _read_aqr_qmj(content: bytes) -> pd.DataFrame:
    """Parse AQR's 'QMJ Factors' sheet (header row starts with 'DATE'; columns are country / region codes)."""
    if content[:2] != b"PK":
        raise ValueError("AQR response is not an xlsx file (blocked or moved?)")
    raw = pd.read_excel(io.BytesIO(content), sheet_name="QMJ Factors", header=None)
    hdr = raw.index[raw.iloc[:, 0].astype(str).str.strip().str.upper() == "DATE"]
    if len(hdr) == 0:
        raise ValueError("no DATE header row in the 'QMJ Factors' sheet")
    h = int(hdr[0])
    cols = [str(c).strip() for c in raw.iloc[h]]
    df = raw.iloc[h + 1 :].copy()
    df.columns = cols
    dates = pd.to_datetime(df["DATE"], errors="coerce")
    df = df.loc[dates.notna()].drop(columns=["DATE"]).apply(pd.to_numeric, errors="coerce")
    df.index = pd.DatetimeIndex(dates[dates.notna()] + pd.offsets.MonthEnd(0), name="date").normalize()
    return df.loc[:, ~df.isna().all()].sort_index()


def qmj(
    freq: str = "M", region: str = "USA", *, force: bool = False, max_age_days: float = DEFAULT_MAX_AGE_DAYS
) -> pd.Series:
    """AQR Quality Minus Junk factor (long/short, self-financing, value-weighted), Series named ``QMJ``.

    Monthly only (AQR also posts a daily file; not used). ``region`` is a column of AQR's sheet: ``'USA'`` (from
    1957-07), ``'Global'``, ``'Global Ex USA'``, country codes ... Raises :class:`FactorDataUnavailable` if the
    download is blocked and nothing is cached."""
    if _check_freq(freq) != "M":
        raise ValueError("qmj() supports freq='M' only")
    df = _cached("aqr_qmj_M", lambda: _read_aqr_qmj(http_get(AQR_QMJ_MONTHLY_URL)), force, max_age_days)
    if region not in df.columns:
        raise KeyError(f"region {region!r} not in {list(df.columns)}")
    return df[region].dropna().rename("QMJ")


def ff_factors_for_regression(freq: str = "M", **kw) -> pd.DataFrame:
    """Mkt-RF, SMB, HML, RMW, CMA, Mom, RF (decimals), common sample of the FF5 and momentum files (from 1963-07)."""
    f5 = ff5(freq, **kw)
    m = mom(freq, **kw)
    df = f5.join(m, how="inner")
    return df[["Mkt-RF", "SMB", "HML", "RMW", "CMA", "Mom", "RF"]].dropna()


def download_all(force: bool = False) -> pd.DataFrame:
    """Fetch/refresh every dataset and return a status table (name, ok, rows, first, last, error). Never raises."""
    jobs: list[tuple[str, Callable[[], pd.DataFrame | pd.Series]]] = [
        ("ff5_M", lambda: ff5("M", force=force)),
        ("ff5_D", lambda: ff5("D", force=force)),
        ("ff3_M", lambda: ff3("M", force=force)),
        ("ff3_D", lambda: ff3("D", force=force)),
        ("mom_M", lambda: mom("M", force=force)),
        ("mom_D", lambda: mom("D", force=force)),
        ("mom_deciles_M_vw", lambda: mom_deciles("M", "vw", force=force)),
        ("mom_deciles_M_ew", lambda: mom_deciles("M", "ew", force=force)),
        ("mom_deciles_D_vw", lambda: mom_deciles("D", "vw", force=force)),
        ("mom_deciles_D_ew", lambda: mom_deciles("D", "ew", force=force)),
        ("bm_op_25_M_vw", lambda: bm_op_25("M", "vw", force=force)),
        ("bm_op_25_M_ew", lambda: bm_op_25("M", "ew", force=force)),
        ("ep_portfolios_M_vw", lambda: ep_portfolios("vw", force=force)),
        ("ep_portfolios_M_ew", lambda: ep_portfolios("ew", force=force)),
        ("aqr_qmj_USA_M", lambda: qmj("M", "USA", force=force)),
    ]
    rows = []
    for name, fn in jobs:
        try:
            obj = fn()
            rows.append(dict(name=name, ok=True, rows=len(obj), first=obj.index.min(), last=obj.index.max(), error=""))
        except Exception as exc:  # report, never raise
            log.warning("download of %s failed: %s", name, exc)
            rows.append(dict(name=name, ok=False, rows=0, first=pd.NaT, last=pd.NaT, error=str(exc)[:300]))
    return pd.DataFrame(rows)
