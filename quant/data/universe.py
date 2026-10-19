"""Point-in-time S&P 1500 universe (S&P 500 + MidCap 400 + SmallCap 600) with historical GICS.

Outputs (schemas in quant/ARCHITECTURE.md; extra audit columns are appended), all under ``cache/universe/``
    membership.parquet       one row per (snapshot_date, index, ticker): S&P 500 at every change date 2009-12-31..today
                             (fja05680 file + Wikipedia tail/gap-fill), S&P 400/600 at quarter-ends (Wikipedia revisions)
    gics.parquet             GICS hierarchy of the four structures in force 2010-2026 (era column; is_legacy)
    security_master.parquet  cik <-> yf_ticker master (ever_sp1500, is_listed_now, successor CIK, ...)
    us_all.parquet           broad current US universe (NYSE / Nasdaq operating companies with a 10-K)
    price_tickers.txt        de-duplicated union of all Yahoo tickers the price loader must fetch
    snapshots_meta.parquet   per (index, quarter) revision id, row counts, GICS/CIK coverage, status
    cik_aliases.csv          successor-registrant CIK swaps (old_cik, new_cik, note)
    wiki/, fja05680/         raw caches (every Wikipedia API response, the GitHub CSVs): reruns are free
    ../../output/data_audit/universe_report.md   audit report

Public API
    build_all(force=False)            build everything (CLI: ``python -m quant.data.universe build [--force]``)
    load_membership() / load_gics() / load_security_master() / us_all()
    members(date, indexes=('SP500','SP400','SP600')) -> DataFrame   point-in-time constituents with GICS

Method (details and caveats are written to output/data_audit/universe_report.md)
    1. Wikipedia revision history -> the last revision on or before every quarter-end for the three "List of S&P ...
       companies" pages (WikiClient: one request at a time, >= 2.6 s apart, 429 back-off, everything cached);
       constituent tables parsed with pandas.read_html; snapshots checked for row counts / GICS coverage with
       fall-backs (earlier revision if vandalised, previous/next usable snapshot, S&P 1000 minus S&P 400 for 2018-20).
    2. S&P 500 exact membership from fja05680/sp500 (spells -> per-date CIK through FjaResolver, because the file
       back-fills later tickers); omissions found by comparing with Wikipedia are gap-filled; agreement is reported.
    3. GICS by structural era (2008/2016/2018/2023 structures) and a label resolver that copes with the sector-only,
       industry-level and typo labels of old Wikipedia revisions; a missing sub-industry is back-filled from the
       nearest other snapshot of the same company and flagged in ``gics_source``.
    4. ticker -> CIK (CikMapper): Wikipedia CIK column, SEC current tickers, normalized company names with
       former-name date validity, documented manual overrides (CIK_OVERRIDES) and successor aliases (CIK_ALIASES).
    5. yf_ticker: the company's CURRENT SEC ticker if it still files (FB -> META), else its historical ticker unless
       another company owns that symbol today (ticker re-use -> null).

Point-in-time rule: ``members(date)`` uses the latest snapshot with ``snapshot_date <= date`` per index (quarterly
for SP400/SP600, so up to one quarter stale but never forward-looking, except the flagged ``fallback_next`` quarters).
"""
from __future__ import annotations

import argparse
import datetime as dt
import gzip
import hashlib
import io
import json
import logging
import os
import re
import sys
import time
import unicodedata
from email.utils import parsedate_to_datetime
from pathlib import Path

import numpy as np
import pandas as pd
import requests

from quant.settings import BENCHMARKS, CACHE, OUTPUT, UNIV_DIR, WIKI_USER_AGENT

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------------------
WIKI_DIR = UNIV_DIR / "wiki"
FJA_DIR = UNIV_DIR / "fja05680"
MEMBERSHIP_PATH = UNIV_DIR / "membership.parquet"
SP500_INTERVALS_PATH = UNIV_DIR / "sp500_intervals.parquet"
GICS_PATH = UNIV_DIR / "gics.parquet"
MASTER_PATH = UNIV_DIR / "security_master.parquet"
US_ALL_PATH = UNIV_DIR / "us_all.parquet"
PRICE_TICKERS_PATH = UNIV_DIR / "price_tickers.txt"
SNAPSHOT_META_PATH = UNIV_DIR / "snapshots_meta.parquet"
REPORT_PATH = CACHE / "reports" / "universe_report.md"

WIKI_API = "https://en.wikipedia.org/w/api.php"
PAGES = {
    "SP500": "List of S&P 500 companies",
    "SP400": "List of S&P 400 companies",
    "SP600": "List of S&P 600 companies",
}
GICS_PAGE = "Global Industry Classification Standard"
EXPECTED_ROWS = {"SP500": 500, "SP400": 400, "SP600": 600}
INDEXES = ("SP500", "SP400", "SP600")
INDEX_RANK = {"SP500": 0, "SP400": 1, "SP600": 2}   # tie-break when a ticker is listed in two indexes

HIST_START = pd.Timestamp("2009-12-31")
FJA_BASE = "https://raw.githubusercontent.com/fja05680/sp500/master/"
FJA_FILES = {
    "sp500_hist_updated.csv": "S%26P%20500%20Historical%20Components%20%26%20Changes%20(Updated).csv",
    "sp500_ticker_start_end.csv": "sp500_ticker_start_end.csv",
    "sp500_current.csv": "sp500.csv",
}

MIN_INTERVAL_S = 2.6          # minimum spacing between Wikipedia requests (one at a time)
MAX_RETRIES = 9


def quarter_ends(start: pd.Timestamp = HIST_START, end: pd.Timestamp | None = None) -> list[pd.Timestamp]:
    """Calendar quarter-ends from ``start`` through the last quarter-end <= ``end`` (default: today)."""
    end = pd.Timestamp(end) if end is not None else pd.Timestamp(dt.date.today())
    qs = pd.date_range(start, end, freq="QE")
    return [pd.Timestamp(q).normalize() for q in qs]


# --------------------------------------------------------------------------------------
# Rate-limited, cached HTTP (Wikipedia API)
# --------------------------------------------------------------------------------------
class WikiClient:
    """One-request-at-a-time Wikipedia API client with disk cache and 429/5xx back-off."""

    def __init__(self, cache_dir: Path = WIKI_DIR, min_interval: float = MIN_INTERVAL_S):
        self.cache_dir = cache_dir
        self.cache_dir.mkdir(parents=True, exist_ok=True)
        self.min_interval = min_interval
        self._last = 0.0
        self.session = requests.Session()
        self.session.headers.update({"User-Agent": WIKI_USER_AGENT, "Accept-Encoding": "gzip"})
        self.n_net = 0
        self.n_cached = 0

    # ---- low level ----
    def _sleep_until_ok(self) -> None:
        wait = self._last + self.min_interval - time.monotonic()
        if wait > 0:
            time.sleep(wait)

    def _request(self, params: dict) -> dict:
        p = dict(params)
        p.setdefault("format", "json")
        p.setdefault("formatversion", "2")
        p.setdefault("maxlag", "5")
        delay = 20.0
        for attempt in range(MAX_RETRIES):
            self._sleep_until_ok()
            try:
                r = self.session.get(WIKI_API, params=p, timeout=90)
            except requests.RequestException as e:      # network hiccup
                self._last = time.monotonic()
                log.warning("wiki request error %s (attempt %d)", e, attempt + 1)
                time.sleep(min(delay, 300))
                delay *= 2
                continue
            self._last = time.monotonic()
            self.n_net += 1
            if r.status_code in (429, 503):
                ra = r.headers.get("Retry-After")
                try:
                    wait = float(ra) if ra is not None else None
                except ValueError:
                    try:
                        wait = max(0.0, (parsedate_to_datetime(ra) - dt.datetime.now(dt.timezone.utc)).total_seconds())
                    except Exception:
                        wait = None
                if wait is None:
                    wait = delay
                wait = min(max(wait, 5.0), 900.0)
                log.warning("wiki HTTP %s, sleeping %.0fs (attempt %d)", r.status_code, wait, attempt + 1)
                time.sleep(wait)
                delay = min(delay * 2, 600)
                continue
            if r.status_code >= 500:
                log.warning("wiki HTTP %s, sleeping %.0fs", r.status_code, delay)
                time.sleep(min(delay, 300))
                delay *= 2
                continue
            r.raise_for_status()
            data = r.json()
            if "error" in data and data["error"].get("code") == "maxlag":
                time.sleep(10)
                continue
            return data
        raise RuntimeError(f"Wikipedia request failed after {MAX_RETRIES} attempts: {params}")

    def _key(self, params: dict) -> str:
        return hashlib.sha1(json.dumps(params, sort_keys=True).encode()).hexdigest()[:16]

    # ---- cached JSON ----
    def get_json(self, params: dict, tag: str) -> dict:
        path = self.cache_dir / f"{tag}_{self._key(params)}.json"
        if path.exists():
            self.n_cached += 1
            return json.loads(path.read_text())
        data = self._request(params)
        tmp = path.with_suffix(".tmp")
        tmp.write_text(json.dumps(data))
        os.replace(tmp, path)
        return data

    # ---- cached rendered HTML of one revision ----
    def get_html(self, revid: int) -> str:
        path = self.cache_dir / f"html_{revid}.html.gz"
        if path.exists():
            self.n_cached += 1
            return gzip.decompress(path.read_bytes()).decode("utf-8")
        data = self._request({"action": "parse", "oldid": int(revid), "prop": "text", "format": "json",
                              "formatversion": "2"})
        if "parse" not in data:
            raise RuntimeError(f"parse of revision {revid} failed: {str(data)[:300]}")
        html = data["parse"]["text"]
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(gzip.compress(html.encode("utf-8"), 6))
        os.replace(tmp, path)
        return html

    # ---- revisions ----
    def revision_history(self, title: str, start: str = "2009-10-01T00:00:00Z",
                         end: str = "2026-10-01T00:00:00Z") -> pd.DataFrame:
        """All revisions of ``title`` between start and end (ids, timestamps, size), oldest first."""
        rows: list[dict] = []
        params = {"action": "query", "prop": "revisions", "titles": title, "rvlimit": "500",
                  "rvdir": "newer", "rvstart": start, "rvend": end, "rvprop": "ids|timestamp|size"}
        cont: dict = {}
        while True:
            q = dict(params, **cont)
            data = self.get_json(q, "revs")
            pages = data.get("query", {}).get("pages", [])
            if not pages or "revisions" not in pages[0]:
                break
            rows.extend(pages[0]["revisions"])
            if "continue" in data:
                cont = {k: v for k, v in data["continue"].items()}
            else:
                break
        df = pd.DataFrame(rows)
        if df.empty:
            return df
        df["timestamp"] = pd.to_datetime(df["timestamp"], utc=True).dt.tz_localize(None)
        return df.sort_values("timestamp").reset_index(drop=True)

    def revision_at(self, title: str, ts: str) -> dict | None:
        """Last revision on or before ISO timestamp ``ts`` (single query, rvdir=older)."""
        params = {"action": "query", "prop": "revisions", "titles": title, "rvlimit": "1", "rvdir": "older",
                  "rvstart": ts, "rvprop": "ids|timestamp|size"}
        data = self.get_json(params, "revat")
        pages = data.get("query", {}).get("pages", [])
        if not pages or "revisions" not in pages[0]:
            return None
        return pages[0]["revisions"][0]

    def latest_revision(self, title: str, day: str | None = None) -> dict:
        """Newest revision (cache key includes the day so reruns on another day refresh)."""
        day = day or dt.date.today().isoformat()
        params = {"action": "query", "prop": "revisions", "titles": title, "rvlimit": "1", "rvdir": "older",
                  "rvprop": "ids|timestamp|size", "_day": day}
        # the "_day" key only varies the cache key; it is not a real API parameter, so strip it for the call
        path = self.cache_dir / f"latest_{self._key(params)}.json"
        if path.exists():
            self.n_cached += 1
            data = json.loads(path.read_text())
        else:
            real = {k: v for k, v in params.items() if k != "_day"}
            data = self._request(real)
            tmp = path.with_suffix(".tmp")
            tmp.write_text(json.dumps(data))
            os.replace(tmp, path)
        return data["query"]["pages"][0]["revisions"][0]


# --------------------------------------------------------------------------------------
# Wikipedia table parsing
# --------------------------------------------------------------------------------------
_FOOTNOTE = re.compile(r"\[[^\]]*\]")


def _flat_cols(df: pd.DataFrame) -> list[str]:
    out = []
    for c in df.columns:
        if isinstance(c, tuple):
            parts = []
            for x in c:
                x = str(x)
                if x not in parts and not x.startswith("Unnamed"):
                    parts.append(x)
            out.append(" ".join(parts))
        else:
            out.append(str(c))
    return out


def _find_col(cols: list[str], patterns: list[str]) -> int | None:
    for pat in patterns:
        rx = re.compile(pat, re.I)
        for i, c in enumerate(cols):
            if rx.search(_FOOTNOTE.sub("", c).strip()):
                return i
    return None


def clean_ticker(x) -> str | None:
    """Raw Wikipedia ticker cell -> upper-case ticker (footnotes / exchange prefixes removed)."""
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    s = _FOOTNOTE.sub("", str(x)).strip()
    s = re.sub(r"^(NYSE|NASDAQ|Nasdaq|NYSE MKT|NYSE American|AMEX|NYSE Arca)\s*[:\-]\s*", "", s)
    s = s.split()[0] if s.split() else ""
    s = s.upper().replace("–", "-").replace("‑", "-").strip(".")
    return s or None


def _clean_name(x) -> str | None:
    if x is None or (isinstance(x, float) and np.isnan(x)):
        return None
    s = _FOOTNOTE.sub("", str(x)).replace("\xa0", " ").strip()
    return re.sub(r"\s+", " ", s) or None


def parse_constituents(html: str) -> pd.DataFrame:
    """Parse the constituents table(s) of one rendered "List of S&P ... companies" page.

    Returns columns: ticker_raw, name, gics_sector, gics_sub_industry, cik, date_added (missing -> None).
    Tables of index changes (columns "Added"/"Removed") and navboxes are ignored. Several matching
    tables (old pages split the list by letter / sector) are concatenated.
    """
    try:
        tables = pd.read_html(io.StringIO(html))
    except ValueError:
        return pd.DataFrame(columns=["ticker_raw", "name", "gics_sector", "gics_sub_industry", "cik", "date_added"])
    parts = []
    for t in tables:
        cols = _flat_cols(t)
        low = [c.lower() for c in cols]
        if any(c.startswith(("added", "removed")) or "reason" in c for c in low):
            continue
        it = _find_col(cols, [r"^(ticker symbol|ticker|symbol|trading symbol)\b"])
        iname = _find_col(cols, [r"^(security|company|company name|name)\b"])
        if it is None or iname is None:
            continue
        isec = _find_col(cols, [r"gics\s*(?:economic\s*)?sector", r"^(?:economic\s*)?sector"])
        isub = _find_col(cols, [r"gics\s*sub.?industry", r"sub.?industry", r"^industry"])
        icik = _find_col(cols, [r"^cik"])
        idate = _find_col(cols, [r"date\s*(first\s*)?added"])
        d = pd.DataFrame({
            "ticker_raw": t.iloc[:, it].map(clean_ticker),
            "name": t.iloc[:, iname].map(_clean_name),
            "gics_sector": t.iloc[:, isec].map(_clean_name) if isec is not None else None,
            "gics_sub_industry": t.iloc[:, isub].map(_clean_name) if isub is not None else None,
            "cik": pd.to_numeric(t.iloc[:, icik], errors="coerce") if icik is not None else np.nan,
            "date_added": t.iloc[:, idate].map(_clean_name) if idate is not None else None,
        })
        parts.append(d)
    if not parts:
        return pd.DataFrame(columns=["ticker_raw", "name", "gics_sector", "gics_sub_industry", "cik", "date_added"])
    out = pd.concat(parts, ignore_index=True)
    out = out[out["ticker_raw"].notna() & (out["ticker_raw"] != "")]
    out = out[out["ticker_raw"].str.fullmatch(r"[A-Z][A-Z0-9.\-]{0,9}")]
    return out.reset_index(drop=True)


PARSER_VERSION = 2          # bump to invalidate cached parsed tables


def _parsed_path(revid: int) -> Path:
    return WIKI_DIR / f"parsed_v{PARSER_VERSION}_{revid}.parquet"


def load_parsed(client: WikiClient, revid: int) -> pd.DataFrame:
    """Parsed constituents of one revision (cached as parquet)."""
    p = _parsed_path(revid)
    if p.exists():
        return pd.read_parquet(p)
    df = parse_constituents(client.get_html(revid))
    df["cik"] = pd.to_numeric(df["cik"], errors="coerce")
    for c in ["date_added", "gics_sector", "gics_sub_industry", "name", "ticker_raw"]:
        df[c] = df[c].astype("object")
    tmp = p.with_suffix(".tmp")
    df.to_parquet(tmp)
    os.replace(tmp, p)
    return df


def snapshot_quality(df: pd.DataFrame, index: str) -> dict:
    n = int(df["ticker_raw"].nunique()) if len(df) else 0
    exp = EXPECTED_ROWS[index]
    gics = float(df["gics_sub_industry"].notna().mean()) if len(df) else 0.0
    sect = float(df["gics_sector"].notna().mean()) if len(df) else 0.0
    return {"n_rows": n, "gics_cov": gics, "sector_cov": sect, "ok_rows": 0.8 * exp <= n <= 1.25 * exp}


# --------------------------------------------------------------------------------------
# Snapshot selection (quarter-end revisions with sanity fall-back)
# --------------------------------------------------------------------------------------
MAX_BACKSTEP = 6


def select_snapshots(client: WikiClient, index: str, qdates: list[pd.Timestamp],
                     fetch: bool = True) -> list[dict]:
    """For each quarter-end pick the last revision <= end of that day whose table parses sanely.

    Falls back to up to MAX_BACKSTEP earlier revisions when the chosen one is vandalised / broken.
    Returns one dict per quarter: index, snapshot_date, revid, rev_ts, n_rows, gics_cov, sector_cov, ok_rows,
    backsteps, and (parsed) df.
    """
    title = PAGES[index]
    hist = client.revision_history(title)
    out = []
    for q in qdates:
        cutoff = q + pd.Timedelta(hours=23, minutes=59, seconds=59)
        cand = hist[hist["timestamp"] <= cutoff]
        if cand.empty:
            out.append({"index": index, "snapshot_date": q, "revid": None, "rev_ts": pd.NaT, "n_rows": 0,
                        "gics_cov": 0.0, "sector_cov": 0.0, "ok_rows": False, "backsteps": 0, "df": None})
            continue
        cand = cand.iloc[::-1].reset_index(drop=True)
        best = None
        for k in range(min(MAX_BACKSTEP + 1, len(cand))):
            revid = int(cand.loc[k, "revid"])
            if not fetch and not (WIKI_DIR / f"html_{revid}.html.gz").exists() and not _parsed_path(revid).exists():
                break
            df = load_parsed(client, revid)
            qual = snapshot_quality(df, index)
            rec = {"index": index, "snapshot_date": q, "revid": revid, "rev_ts": cand.loc[k, "timestamp"],
                   **qual, "backsteps": k, "df": df}
            if best is None or rec["n_rows"] > best["n_rows"]:
                best = rec
            if qual["ok_rows"]:
                best = rec
                break
            if index == "SP600" and 900 <= qual["n_rows"] <= 1100:     # combined S&P 1000 list: not vandalism, keep
                best = rec
                break
        if best is None:
            best = {"index": index, "snapshot_date": q, "revid": None, "rev_ts": pd.NaT, "n_rows": 0,
                    "gics_cov": 0.0, "sector_cov": 0.0, "ok_rows": False, "backsteps": 0, "df": None}
        log.info("%s %s rev %s (%s) rows=%s gics=%.2f ok=%s back=%s", index, q.date(), best["revid"],
                 best["rev_ts"], best["n_rows"], best["gics_cov"], best["ok_rows"], best["backsteps"])
        out.append(best)
    return out


GICS_REV_DATES = ["2017-06-30T23:59:59Z", "2019-06-30T23:59:59Z", "2022-06-30T23:59:59Z"]


def fetch_wiki(client: WikiClient | None = None) -> dict:
    """Download (and cache) everything needed from Wikipedia. Safe to rerun; cached responses are free."""
    client = client or WikiClient()
    qs = quarter_ends()
    info: dict = {"gics_revs": {}, "snapshots": {}}
    # GICS structure pages (few requests)
    for ts in GICS_REV_DATES:
        rev = client.revision_at(GICS_PAGE, ts)
        if rev:
            client.get_html(rev["revid"])
            info["gics_revs"][ts[:10]] = rev
    rev = client.latest_revision(GICS_PAGE)
    client.get_html(rev["revid"])
    info["gics_revs"]["latest"] = rev
    # three index pages: current + all quarter-ends
    for index, title in PAGES.items():
        rev = client.latest_revision(title)
        df = load_parsed(client, rev["revid"])
        log.info("%s current rev %s rows=%d", index, rev["revid"], len(df))
        sel = select_snapshots(client, index, qs, fetch=True)
        info["snapshots"][index] = [{k: v for k, v in s.items() if k != "df"} for s in sel]
    log.info("fetch done: network=%d cached=%d", client.n_net, client.n_cached)
    return info


# --------------------------------------------------------------------------------------
# Ticker helpers, SEC company tables, US_ALL
# --------------------------------------------------------------------------------------
LISTED_EXCHANGES = ("NYSE", "Nasdaq", "NYSE American", "NYSE MKT", "NYSE Arca", "CBOE")
US_ALL_EXCHANGES = ("NYSE", "Nasdaq", "NYSE American")      # the SEC file only emits NYSE / Nasdaq / OTC / CBOE
# non-common share classes: preferred (-P, -PA..), warrants (-W, -WS, -WT), units (-U, -UN), rights (-R, -RT, -RI, -RW)
_NONCOMMON_SUFFIX = re.compile(r"-(P[A-Z]?|W[A-Z]?|WS[A-Z]?|WT[A-Z]?|U|UN|R|RT|RI|RW|RTW|WI|N)$")
_FUNDISH_NAME = re.compile(r"\b(?:ETF|ETN|FUND|FUNDS|TRUST UNITS?|INDEX|ISHARES|SPDR|PROSHARES|VANECK|INVESCO DB|"
                           r"GRAYSCALE|BITCOIN|ETHER|COMMODITY|CURRENCYSHARES|BULLION)\b", re.I)
EXCLUDE_SIC = {6770, 6221, 6189}        # blank-check shells, commodity pools / grantor trusts, asset-backed issuers


def to_yf(t: str | None) -> str | None:
    """Wikipedia / SEC ticker -> Yahoo symbol: upper-case, class-share dots become dashes (BRK.B -> BRK-B)."""
    if t is None or (isinstance(t, float) and np.isnan(t)):
        return None
    t = str(t).strip().upper().replace(".", "-").replace("/", "-").replace(" ", "-")
    return t or None


def is_noncommon_ticker(t: str) -> bool:
    return bool(_NONCOMMON_SUFFIX.search(t))


def load_sec_companies() -> pd.DataFrame:
    """quant.data.sec.load_companies() plus parsed ticker/exchange pairs."""
    from quant.data import sec
    c = sec.load_companies().copy()
    c["cik"] = c["cik"].astype("int64")
    return c


def _ticker_pairs(row_tickers: str | None, row_exch: str | None) -> list[tuple[str, str]]:
    tk = [x for x in (row_tickers or "").split("|") if x]
    ex = (row_exch or "").split("|") if row_exch else []
    if len(ex) != len(tk):
        ex = [""] * len(tk) if len(ex) < len(tk) else ex[:len(tk)]
    return list(zip(tk, ex))


def current_ticker_table(companies: pd.DataFrame) -> pd.DataFrame:
    """One row per (cik, ticker) in the CURRENT SEC ticker file, in SEC order: cik, ticker, exchange, rank."""
    rows = []
    for r in companies[["cik", "tickers", "exchanges"]].itertuples(index=False):
        for k, (t, e) in enumerate(_ticker_pairs(r.tickers, r.exchanges)):
            rows.append((int(r.cik), t, e, k))
    return pd.DataFrame(rows, columns=["cik", "ticker", "exchange", "rank"])


def build_us_all(companies: pd.DataFrame | None = None, as_of: pd.Timestamp | None = None) -> pd.DataFrame:
    """Broad current US universe: listed operating companies with a 10-K and a recent periodic filing.

    One row per CIK; ``yf_ticker`` is the first valid common-stock ticker the SEC lists (e.g. GOOGL, BRK-B),
    other listed classes are kept in ``alt_tickers``.
    """
    companies = companies if companies is not None else load_sec_companies()
    as_of = pd.Timestamp(as_of) if as_of is not None else pd.Timestamp(dt.date.today())
    tt = current_ticker_table(companies)
    tt = tt[tt["exchange"].isin(US_ALL_EXCHANGES)]
    tt = tt[~tt["ticker"].map(is_noncommon_ticker)]
    c = companies.set_index("cik")
    ok = (c["entity_type"].eq("operating") & (c["n_10k"] > 0)
          & ~c["sic"].isin(EXCLUDE_SIC)
          & (c["last_periodic_filing_date"] >= as_of - pd.Timedelta(days=730)))
    tt = tt[tt["cik"].map(ok).fillna(False)]
    tt = tt[~tt["cik"].map(c["name"]).fillna("").str.contains(_FUNDISH_NAME)]
    tt = tt.sort_values(["cik", "rank"])
    first = tt.groupby("cik", sort=False).first()
    alts = tt.groupby("cik")["ticker"].apply(lambda s: "|".join(to_yf(x) for x in s.iloc[1:]))
    out = pd.DataFrame({
        "cik": first.index.astype("int64"),
        "yf_ticker": first["ticker"].map(to_yf).values,
        "name": first.index.map(c["name"]).values,
        "sic": first.index.map(c["sic"]).values,
        "exchange": first["exchange"].values,
        "alt_tickers": first.index.map(alts).values,
    })
    out["sic"] = out["sic"].astype("Int64")
    out = out.drop_duplicates("yf_ticker").sort_values("yf_ticker").reset_index(drop=True)
    return out


def _atomic_write_text(path: Path, text: str) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    tmp.write_text(text)
    os.replace(tmp, path)


def _atomic_write_parquet(df: pd.DataFrame, path: Path) -> None:
    tmp = path.with_suffix(path.suffix + ".tmp")
    df.to_parquet(tmp, index=False)
    os.replace(tmp, path)


def write_price_tickers(tickers) -> Path:
    """De-duplicated, sorted ticker list for the price loader (atomic write)."""
    s = sorted({str(t).strip() for t in tickers if isinstance(t, str) and t.strip()})
    _atomic_write_text(PRICE_TICKERS_PATH, "\n".join(s) + "\n")
    log.info("price_tickers.txt: %d tickers", len(s))
    return PRICE_TICKERS_PATH


def write_early_price_tickers(client: WikiClient | None = None) -> Path:
    """First version of price_tickers.txt: US_ALL + CURRENT S&P 500/400/600 lists + benchmarks.

    Superseded by the full list (all historical snapshots) written at the end of ``build_all``.
    """
    client = client or WikiClient()
    companies = load_sec_companies()
    us = build_us_all(companies)
    _atomic_write_parquet(us, US_ALL_PATH)
    tick = set(us["yf_ticker"])
    for index, title in PAGES.items():
        rev = client.latest_revision(title)
        df = load_parsed(client, rev["revid"])
        tick.update(to_yf(t) for t in df["ticker_raw"])
    tick.update(BENCHMARKS)
    return write_price_tickers(tick)


# --------------------------------------------------------------------------------------
# GICS hierarchy by structural era
# --------------------------------------------------------------------------------------
# Four structures were in force in 2010-2026. Dates are the "after the close of" effective dates:
#   2008 structure  -> until 2016-08-31 (Real Estate split out of Financials on 2016-09-01)
#   2016 structure  -> 2016-09-01 .. 2018-09-21 (Communication Services created after close 2018-09-21)
#   2018 structure  -> 2018-09-22 .. 2023-03-17
#   2023 structure  -> from 2023-03-18
# Sources: "2016", "2018" are the Wikipedia "Global Industry Classification Standard" revisions 779592898 (2017-05)
# and 1095269436 (2022-06); "2023" equals research/04 section 3.2 (checked identical to the live page);
# "2008" is derived from the 2016 structure by undoing the 2016 changes (Real Estate sector, Financial Exchanges &
# Data, Copper/Silver, Agricultural & Farm Machinery, Technology Hardware merge, Internet & Direct Marketing
# Retail merge) from memory of the S&P/MSCI 2008 structure - treat legacy codes as best-effort (names are exact
# only where they appear in a Wikipedia snapshot; the report lists any mismatch with the snapshot's own sector).
GICS_ERAS = [
    # era, valid_from, valid_to (inclusive), is_legacy
    ("2008", None, "2016-08-31", True),
    ("2016", "2016-09-01", "2018-09-21", True),
    ("2018", "2018-09-22", "2023-03-17", True),
    ("2023", "2023-03-18", None, False),
]
_GICS_TEXT = {
    "2008": """\
10 Energy
  1010 Energy
    101010 Energy Equipment & Services: 10101010 Oil & Gas Drilling; 10101020 Oil & Gas Equipment & Services
    101020 Oil, Gas & Consumable Fuels: 10102010 Integrated Oil & Gas; 10102020 Oil & Gas Exploration & Production; 10102030 Oil & Gas Refining & Marketing; 10102040 Oil & Gas Storage & Transportation; 10102050 Coal & Consumable Fuels
15 Materials
  1510 Materials
    151010 Chemicals: 15101010 Commodity Chemicals; 15101020 Diversified Chemicals; 15101030 Fertilizers & Agricultural Chemicals; 15101040 Industrial Gases; 15101050 Specialty Chemicals
    151020 Construction Materials: 15102010 Construction Materials
    151030 Containers & Packaging: 15103010 Metal & Glass Containers; 15103020 Paper Packaging
    151040 Metals & Mining: 15104010 Aluminum; 15104020 Diversified Metals & Mining; 15104030 Gold; 15104040 Precious Metals & Minerals; 15104050 Steel
    151050 Paper & Forest Products: 15105010 Forest Products; 15105020 Paper Products
20 Industrials
  2010 Capital Goods
    201010 Aerospace & Defense: 20101010 Aerospace & Defense
    201020 Building Products: 20102010 Building Products
    201030 Construction & Engineering: 20103010 Construction & Engineering
    201040 Electrical Equipment: 20104010 Electrical Components & Equipment; 20104020 Heavy Electrical Equipment
    201050 Industrial Conglomerates: 20105010 Industrial Conglomerates
    201060 Machinery: 20106010 Construction & Farm Machinery & Heavy Trucks; 20106020 Industrial Machinery
    201070 Trading Companies & Distributors: 20107010 Trading Companies & Distributors
  2020 Commercial & Professional Services
    202010 Commercial Services & Supplies: 20201010 Commercial Printing; 20201050 Environmental & Facilities Services; 20201060 Office Services & Supplies; 20201070 Diversified Support Services; 20201080 Security & Alarm Services
    202020 Professional Services: 20202010 Human Resource & Employment Services; 20202020 Research & Consulting Services
  2030 Transportation
    203010 Air Freight & Logistics: 20301010 Air Freight & Logistics
    203020 Airlines: 20302010 Airlines
    203030 Marine: 20303010 Marine
    203040 Road & Rail: 20304010 Railroads; 20304020 Trucking
    203050 Transportation Infrastructure: 20305010 Airport Services; 20305020 Highways & Railtracks; 20305030 Marine Ports & Services
25 Consumer Discretionary
  2510 Automobiles & Components
    251010 Auto Components: 25101010 Auto Parts & Equipment; 25101020 Tires & Rubber
    251020 Automobiles: 25102010 Automobile Manufacturers; 25102020 Motorcycle Manufacturers
  2520 Consumer Durables & Apparel
    252010 Household Durables: 25201010 Consumer Electronics; 25201020 Home Furnishings; 25201030 Homebuilding; 25201040 Household Appliances; 25201050 Housewares & Specialties
    252020 Leisure Equipment & Products: 25202010 Leisure Products; 25202020 Photographic Products
    252030 Textiles, Apparel & Luxury Goods: 25203010 Apparel, Accessories & Luxury Goods; 25203020 Footwear; 25203030 Textiles
  2530 Consumer Services
    253010 Hotels, Restaurants & Leisure: 25301010 Casinos & Gaming; 25301020 Hotels, Resorts & Cruise Lines; 25301030 Leisure Facilities; 25301040 Restaurants
    253020 Diversified Consumer Services: 25302010 Education Services; 25302020 Specialized Consumer Services
  2540 Media
    254010 Media: 25401010 Advertising; 25401020 Broadcasting; 25401025 Cable & Satellite; 25401030 Movies & Entertainment; 25401040 Publishing
  2550 Retailing
    255010 Distributors: 25501010 Distributors
    255020 Internet & Catalog Retail: 25502010 Catalog Retail; 25502020 Internet Retail
    255030 Multiline Retail: 25503010 Department Stores; 25503020 General Merchandise Stores
    255040 Specialty Retail: 25504010 Apparel Retail; 25504020 Computer & Electronics Retail; 25504030 Home Improvement Retail; 25504040 Specialty Stores; 25504050 Automotive Retail; 25504060 Homefurnishing Retail
30 Consumer Staples
  3010 Food & Staples Retailing
    301010 Food & Staples Retailing: 30101010 Drug Retail; 30101020 Food Distributors; 30101030 Food Retail; 30101040 Hypermarkets & Super Centers
  3020 Food, Beverage & Tobacco
    302010 Beverages: 30201010 Brewers; 30201020 Distillers & Vintners; 30201030 Soft Drinks
    302020 Food Products: 30202010 Agricultural Products; 30202030 Packaged Foods & Meats
    302030 Tobacco: 30203010 Tobacco
  3030 Household & Personal Products
    303010 Household Products: 30301010 Household Products
    303020 Personal Products: 30302010 Personal Products
35 Health Care
  3510 Health Care Equipment & Services
    351010 Health Care Equipment & Supplies: 35101010 Health Care Equipment; 35101020 Health Care Supplies
    351020 Health Care Providers & Services: 35102010 Health Care Distributors; 35102015 Health Care Services; 35102020 Health Care Facilities; 35102030 Managed Health Care
    351030 Health Care Technology: 35103010 Health Care Technology
  3520 Pharmaceuticals, Biotechnology & Life Sciences
    352010 Biotechnology: 35201010 Biotechnology
    352020 Pharmaceuticals: 35202010 Pharmaceuticals
    352030 Life Sciences Tools & Services: 35203010 Life Sciences Tools & Services
40 Financials
  4010 Banks
    401010 Commercial Banks: 40101010 Diversified Banks; 40101015 Regional Banks
    401020 Thrifts & Mortgage Finance: 40102010 Thrifts & Mortgage Finance
  4020 Diversified Financials
    402010 Diversified Financial Services: 40201010 Other Diversified Financial Services; 40201020 Multi-Sector Holdings; 40201030 Specialized Finance
    402020 Consumer Finance: 40202010 Consumer Finance
    402030 Capital Markets: 40203010 Asset Management & Custody Banks; 40203020 Investment Banking & Brokerage; 40203030 Diversified Capital Markets
  4030 Insurance
    403010 Insurance: 40301010 Insurance Brokers; 40301020 Life & Health Insurance; 40301030 Multi-line Insurance; 40301040 Property & Casualty Insurance; 40301050 Reinsurance
  4040 Real Estate
    404010 Real Estate Investment Trusts (REITs): 40401010 Diversified REITs; 40401020 Industrial REITs; 40401030 Mortgage REITs; 40401040 Office REITs; 40401050 Residential REITs; 40401060 Retail REITs; 40401070 Specialized REITs
    404020 Real Estate Management & Development: 40402010 Diversified Real Estate Activities; 40402020 Real Estate Operating Companies; 40402030 Real Estate Development; 40402040 Real Estate Services
45 Information Technology
  4510 Software & Services
    451010 Internet Software & Services: 45101010 Internet Software & Services
    451020 IT Services: 45102010 IT Consulting & Other Services; 45102020 Data Processing & Outsourced Services
    451030 Software: 45103010 Application Software; 45103020 Systems Software; 45103030 Home Entertainment Software
  4520 Technology Hardware & Equipment
    452010 Communications Equipment: 45201020 Communications Equipment
    452020 Computers & Peripherals: 45202010 Computer Hardware; 45202020 Computer Storage & Peripherals
    452030 Electronic Equipment, Instruments & Components: 45203010 Electronic Equipment & Instruments; 45203015 Electronic Components; 45203020 Electronic Manufacturing Services; 45203030 Technology Distributors
    452040 Office Electronics: 45204010 Office Electronics
  4530 Semiconductors & Semiconductor Equipment
    453010 Semiconductors & Semiconductor Equipment: 45301010 Semiconductor Equipment; 45301020 Semiconductors
50 Telecommunication Services
  5010 Telecommunication Services
    501010 Diversified Telecommunication Services: 50101010 Alternative Carriers; 50101020 Integrated Telecommunication Services
    501020 Wireless Telecommunication Services: 50102010 Wireless Telecommunication Services
55 Utilities
  5510 Utilities
    551010 Electric Utilities: 55101010 Electric Utilities
    551020 Gas Utilities: 55102010 Gas Utilities
    551030 Multi-Utilities: 55103010 Multi-Utilities
    551040 Water Utilities: 55104010 Water Utilities
    551050 Independent Power and Renewable Electricity Producers: 55105010 Independent Power Producers & Energy Traders; 55105020 Renewable Electricity
""",
    "2016": """\
10 Energy
  1010 Energy
    101010 Energy Equipment & Services: 10101010 Oil & Gas Drilling; 10101020 Oil & Gas Equipment & Services
    101020 Oil, Gas & Consumable Fuels: 10102010 Integrated Oil & Gas; 10102020 Oil & Gas Exploration & Production; 10102030 Oil & Gas Refining & Marketing; 10102040 Oil & Gas Storage & Transportation; 10102050 Coal & Consumable Fuels
15 Materials
  1510 Materials
    151010 Chemicals: 15101010 Commodity Chemicals; 15101020 Diversified Chemicals; 15101030 Fertilizers & Agricultural Chemicals; 15101040 Industrial Gases; 15101050 Specialty Chemicals
    151020 Construction Materials: 15102010 Construction Materials
    151030 Containers & Packaging: 15103010 Metal & Glass Containers; 15103020 Paper Packaging
    151040 Metals & Mining: 15104010 Aluminum; 15104020 Diversified Metals & Mining; 15104025 Copper; 15104030 Gold; 15104040 Precious Metals & Minerals; 15104045 Silver; 15104050 Steel
    151050 Paper & Forest Products: 15105010 Forest Products; 15105020 Paper Products
20 Industrials
  2010 Capital Goods
    201010 Aerospace & Defense: 20101010 Aerospace & Defense
    201020 Building Products: 20102010 Building Products
    201030 Construction & Engineering: 20103010 Construction & Engineering
    201040 Electrical Equipment: 20104010 Electrical Components & Equipment; 20104020 Heavy Electrical Equipment
    201050 Industrial Conglomerates: 20105010 Industrial Conglomerates
    201060 Machinery: 20106010 Construction Machinery & Heavy Trucks; 20106015 Agricultural & Farm Machinery; 20106020 Industrial Machinery
    201070 Trading Companies & Distributors: 20107010 Trading Companies & Distributors
  2020 Commercial & Professional Services
    202010 Commercial Services & Supplies: 20201010 Commercial Printing; 20201050 Environmental & Facilities Services; 20201060 Office Services & Supplies; 20201070 Diversified Support Services; 20201080 Security & Alarm Services
    202020 Professional Services: 20202010 Human Resource & Employment Services; 20202020 Research & Consulting Services
  2030 Transportation
    203010 Air Freight & Logistics: 20301010 Air Freight & Logistics
    203020 Airlines: 20302010 Airlines
    203030 Marine: 20303010 Marine
    203040 Road & Rail: 20304010 Railroads; 20304020 Trucking
    203050 Transportation Infrastructure: 20305010 Airport Services; 20305020 Highways & Railtracks; 20305030 Marine Ports & Services
25 Consumer Discretionary
  2510 Automobiles & Components
    251010 Auto Components: 25101010 Auto Parts & Equipment; 25101020 Tires & Rubber
    251020 Automobiles: 25102010 Automobile Manufacturers; 25102020 Motorcycle Manufacturers
  2520 Consumer Durables & Apparel
    252010 Household Durables: 25201010 Consumer Electronics; 25201020 Home Furnishings; 25201030 Homebuilding; 25201040 Household Appliances; 25201050 Housewares & Specialties
    252020 Leisure Products: 25202010 Leisure Products
    252030 Textiles, Apparel & Luxury Goods: 25203010 Apparel, Accessories & Luxury Goods; 25203020 Footwear; 25203030 Textiles
  2530 Consumer Services
    253010 Hotels, Restaurants & Leisure: 25301010 Casinos & Gaming; 25301020 Hotels, Resorts & Cruise Lines; 25301030 Leisure Facilities; 25301040 Restaurants
    253020 Diversified Consumer Services: 25302010 Education Services; 25302020 Specialized Consumer Services
  2540 Media
    254010 Media: 25401010 Advertising; 25401020 Broadcasting; 25401025 Cable & Satellite; 25401030 Movies & Entertainment; 25401040 Publishing
  2550 Retailing
    255010 Distributors: 25501010 Distributors
    255020 Internet & Direct Marketing Retail: 25502020 Internet & Direct Marketing Retail
    255030 Multiline Retail: 25503010 Department Stores; 25503020 General Merchandise Stores
    255040 Specialty Retail: 25504010 Apparel Retail; 25504020 Computer & Electronics Retail; 25504030 Home Improvement Retail; 25504040 Specialty Stores; 25504050 Automotive Retail; 25504060 Homefurnishing Retail
30 Consumer Staples
  3010 Food & Staples Retailing
    301010 Food & Staples Retailing: 30101010 Drug Retail; 30101020 Food Distributors; 30101030 Food Retail; 30101040 Hypermarkets & Super Centers
  3020 Food, Beverage & Tobacco
    302010 Beverages: 30201010 Brewers; 30201020 Distillers & Vintners; 30201030 Soft Drinks
    302020 Food Products: 30202010 Agricultural Products; 30202030 Packaged Foods & Meats
    302030 Tobacco: 30203010 Tobacco
  3030 Household & Personal Products
    303010 Household Products: 30301010 Household Products
    303020 Personal Products: 30302010 Personal Products
35 Health Care
  3510 Health Care Equipment & Services
    351010 Health Care Equipment & Supplies: 35101010 Health Care Equipment; 35101020 Health Care Supplies
    351020 Health Care Providers & Services: 35102010 Health Care Distributors; 35102015 Health Care Services; 35102020 Health Care Facilities; 35102030 Managed Health Care
    351030 Health Care Technology: 35103010 Health Care Technology
  3520 Pharmaceuticals, Biotechnology & Life Sciences
    352010 Biotechnology: 35201010 Biotechnology
    352020 Pharmaceuticals: 35202010 Pharmaceuticals
    352030 Life Sciences Tools & Services: 35203010 Life Sciences Tools & Services
40 Financials
  4010 Banks
    401010 Banks: 40101010 Diversified Banks; 40101015 Regional Banks
    401020 Thrifts & Mortgage Finance: 40102010 Thrifts & Mortgage Finance
  4020 Diversified Financials
    402010 Diversified Financial Services: 40201020 Other Diversified Financial Services; 40201030 Multi-Sector Holdings; 40201040 Specialized Finance
    402020 Consumer Finance: 40202010 Consumer Finance
    402030 Capital Markets: 40203010 Asset Management & Custody Banks; 40203020 Investment Banking & Brokerage; 40203030 Diversified Capital Markets; 40203040 Financial Exchanges & Data
    402040 Mortgage Real Estate Investment Trusts (REITs): 40204010 Mortgage REITs
  4030 Insurance
    403010 Insurance: 40301010 Insurance Brokers; 40301020 Life & Health Insurance; 40301030 Multi-line Insurance; 40301040 Property & Casualty Insurance; 40301050 Reinsurance
45 Information Technology
  4510 Software & Services
    451010 Internet Software & Services: 45101010 Internet Software & Services
    451020 IT Services: 45102010 IT Consulting & Other Services; 45102020 Data Processing & Outsourced Services
    451030 Software: 45103010 Application Software; 45103020 Systems Software; 45103030 Home Entertainment Software
  4520 Technology Hardware & Equipment
    452010 Communications Equipment: 45201020 Communications Equipment
    452020 Technology Hardware, Storage & Peripherals: 45202030 Technology Hardware, Storage & Peripherals
    452030 Electronic Equipment, Instruments & Components: 45203010 Electronic Equipment & Instruments; 45203015 Electronic Components; 45203020 Electronic Manufacturing Services; 45203030 Technology Distributors
  4530 Semiconductors & Semiconductor Equipment
    453010 Semiconductors & Semiconductor Equipment: 45301010 Semiconductor Equipment; 45301020 Semiconductors
50 Telecommunication Services
  5010 Telecommunication Services
    501010 Diversified Telecommunication Services: 50101010 Alternative Carriers; 50101020 Integrated Telecommunication Services
    501020 Wireless Telecommunication Services: 50102010 Wireless Telecommunication Services
55 Utilities
  5510 Utilities
    551010 Electric Utilities: 55101010 Electric Utilities
    551020 Gas Utilities: 55102010 Gas Utilities
    551030 Multi-Utilities: 55103010 Multi-Utilities
    551040 Water Utilities: 55104010 Water Utilities
    551050 Independent Power and Renewable Electricity Producers: 55105010 Independent Power Producers & Energy Traders; 55105020 Renewable Electricity
60 Real Estate
  6010 Real Estate
    601010 Equity Real Estate Investment Trusts (REITs): 60101010 Diversified REITs; 60101020 Industrial REITs; 60101030 Hotel & Resort REITs; 60101040 Office REITs; 60101050 Health Care REITs; 60101060 Residential REITs; 60101070 Retail REITs; 60101080 Specialized REITs
    601020 Real Estate Management & Development: 60102010 Diversified Real Estate Activities; 60102020 Real Estate Operating Companies; 60102030 Real Estate Development; 60102040 Real Estate Services
""",
    "2018": """\
10 Energy
  1010 Energy
    101010 Energy Equipment & Services: 10101010 Oil & Gas Drilling; 10101020 Oil & Gas Equipment & Services
    101020 Oil, Gas & Consumable Fuels: 10102010 Integrated Oil & Gas; 10102020 Oil & Gas Exploration & Production; 10102030 Oil & Gas Refining & Marketing; 10102040 Oil & Gas Storage & Transportation; 10102050 Coal & Consumable Fuels
15 Materials
  1510 Materials
    151010 Chemicals: 15101010 Commodity Chemicals; 15101020 Diversified Chemicals; 15101030 Fertilizers & Agricultural Chemicals; 15101040 Industrial Gases; 15101050 Specialty Chemicals
    151020 Construction Materials: 15102010 Construction Materials
    151030 Containers & Packaging: 15103010 Metal & Glass Containers; 15103020 Paper Packaging
    151040 Metals & Mining: 15104010 Aluminum; 15104020 Diversified Metals & Mining; 15104025 Copper; 15104030 Gold; 15104040 Precious Metals & Minerals; 15104045 Silver; 15104050 Steel
    151050 Paper & Forest Products: 15105010 Forest Products; 15105020 Paper Products
20 Industrials
  2010 Capital Goods
    201010 Aerospace & Defense: 20101010 Aerospace & Defense
    201020 Building Products: 20102010 Building Products
    201030 Construction & Engineering: 20103010 Construction & Engineering
    201040 Electrical Equipment: 20104010 Electrical Components & Equipment; 20104020 Heavy Electrical Equipment
    201050 Industrial Conglomerates: 20105010 Industrial Conglomerates
    201060 Machinery: 20106010 Construction Machinery & Heavy Trucks; 20106015 Agricultural & Farm Machinery; 20106020 Industrial Machinery
    201070 Trading Companies & Distributors: 20107010 Trading Companies & Distributors
  2020 Commercial & Professional Services
    202010 Commercial Services & Supplies: 20201010 Commercial Printing; 20201050 Environmental & Facilities Services; 20201060 Office Services & Supplies; 20201070 Diversified Support Services; 20201080 Security & Alarm Services
    202020 Professional Services: 20202010 Human Resource & Employment Services; 20202020 Research & Consulting Services
  2030 Transportation
    203010 Air Freight & Logistics: 20301010 Air Freight & Logistics
    203020 Airlines: 20302010 Airlines
    203030 Marine: 20303010 Marine
    203040 Road & Rail: 20304010 Railroads; 20304020 Trucking
    203050 Transportation Infrastructure: 20305010 Airport Services; 20305020 Highways & Railtracks; 20305030 Marine Ports & Services
25 Consumer Discretionary
  2510 Automobiles & Components
    251010 Auto Components: 25101010 Auto Parts & Equipment; 25101020 Tires & Rubber
    251020 Automobiles: 25102010 Automobile Manufacturers; 25102020 Motorcycle Manufacturers
  2520 Consumer Durables & Apparel
    252010 Household Durables: 25201010 Consumer Electronics; 25201020 Home Furnishings; 25201030 Homebuilding; 25201040 Household Appliances; 25201050 Housewares & Specialties
    252020 Leisure Products: 25202010 Leisure Products
    252030 Textiles, Apparel & Luxury Goods: 25203010 Apparel, Accessories & Luxury Goods; 25203020 Footwear; 25203030 Textiles
  2530 Consumer Services
    253010 Hotels, Restaurants & Leisure: 25301010 Casinos & Gaming; 25301020 Hotels, Resorts & Cruise Lines; 25301030 Leisure Facilities; 25301040 Restaurants
    253020 Diversified Consumer Services: 25302010 Education Services; 25302020 Specialized Consumer Services
  2550 Retailing
    255010 Distributors: 25501010 Distributors
    255020 Internet & Direct Marketing Retail: 25502020 Internet & Direct Marketing Retail
    255030 Multiline Retail: 25503010 Department Stores; 25503020 General Merchandise Stores
    255040 Specialty Retail: 25504010 Apparel Retail; 25504020 Computer & Electronics Retail; 25504030 Home Improvement Retail; 25504040 Specialty Stores; 25504050 Automotive Retail; 25504060 Homefurnishing Retail
30 Consumer Staples
  3010 Food & Staples Retailing
    301010 Food & Staples Retailing: 30101010 Drug Retail; 30101020 Food Distributors; 30101030 Food Retail; 30101040 Hypermarkets & Super Centers
  3020 Food, Beverage & Tobacco
    302010 Beverages: 30201010 Brewers; 30201020 Distillers & Vintners; 30201030 Soft Drinks
    302020 Food Products: 30202010 Agricultural Products; 30202030 Packaged Foods & Meats
    302030 Tobacco: 30203010 Tobacco
  3030 Household & Personal Products
    303010 Household Products: 30301010 Household Products
    303020 Personal Products: 30302010 Personal Products
35 Health Care
  3510 Health Care Equipment & Services
    351010 Health Care Equipment & Supplies: 35101010 Health Care Equipment; 35101020 Health Care Supplies
    351020 Health Care Providers & Services: 35102010 Health Care Distributors; 35102015 Health Care Services; 35102020 Health Care Facilities; 35102030 Managed Health Care
    351030 Health Care Technology: 35103010 Health Care Technology
  3520 Pharmaceuticals, Biotechnology & Life Sciences
    352010 Biotechnology: 35201010 Biotechnology
    352020 Pharmaceuticals: 35202010 Pharmaceuticals
    352030 Life Sciences Tools & Services: 35203010 Life Sciences Tools & Services
40 Financials
  4010 Banks
    401010 Banks: 40101010 Diversified Banks; 40101015 Regional Banks
    401020 Thrifts & Mortgage Finance: 40102010 Thrifts & Mortgage Finance
  4020 Diversified Financials
    402010 Diversified Financial Services: 40201020 Other Diversified Financial Services; 40201030 Multi-Sector Holdings; 40201040 Specialized Finance
    402020 Consumer Finance: 40202010 Consumer Finance
    402030 Capital Markets: 40203010 Asset Management & Custody Banks; 40203020 Investment Banking & Brokerage; 40203030 Diversified Capital Markets; 40203040 Financial Exchanges & Data
    402040 Mortgage Real Estate Investment Trusts (REITs): 40204010 Mortgage REITs
  4030 Insurance
    403010 Insurance: 40301010 Insurance Brokers; 40301020 Life & Health Insurance; 40301030 Multi-line Insurance; 40301040 Property & Casualty Insurance; 40301050 Reinsurance
45 Information Technology
  4510 Software & Services
    451020 IT Services: 45102010 IT Consulting & Other Services; 45102020 Data Processing & Outsourced Services; 45102030 Internet Services & Infrastructure
    451030 Software: 45103010 Application Software; 45103020 Systems Software
  4520 Technology Hardware & Equipment
    452010 Communications Equipment: 45201020 Communications Equipment
    452020 Technology Hardware, Storage & Peripherals: 45202030 Technology Hardware, Storage & Peripherals
    452030 Electronic Equipment, Instruments & Components: 45203010 Electronic Equipment & Instruments; 45203015 Electronic Components; 45203020 Electronic Manufacturing Services; 45203030 Technology Distributors
  4530 Semiconductors & Semiconductor Equipment
    453010 Semiconductors & Semiconductor Equipment: 45301010 Semiconductor Equipment; 45301020 Semiconductors
50 Communication Services
  5010 Telecommunication Services
    501010 Diversified Telecommunication Services: 50101010 Alternative Carriers; 50101020 Integrated Telecommunication Services
    501020 Wireless Telecommunication Services: 50102010 Wireless Telecommunication Services
  5020 Media & Entertainment
    502010 Media: 50201010 Advertising; 50201020 Broadcasting; 50201030 Cable & Satellite; 50201040 Publishing
    502020 Entertainment: 50202010 Movies & Entertainment; 50202020 Interactive Home Entertainment
    502030 Interactive Media & Services: 50203010 Interactive Media & Services
55 Utilities
  5510 Utilities
    551010 Electric Utilities: 55101010 Electric Utilities
    551020 Gas Utilities: 55102010 Gas Utilities
    551030 Multi-Utilities: 55103010 Multi-Utilities
    551040 Water Utilities: 55104010 Water Utilities
    551050 Independent Power and Renewable Electricity Producers: 55105010 Independent Power Producers & Energy Traders; 55105020 Renewable Electricity
60 Real Estate
  6010 Real Estate
    601010 Equity Real Estate Investment Trusts (REITs): 60101010 Diversified REITs; 60101020 Industrial REITs; 60101030 Hotel & Resort REITs; 60101040 Office REITs; 60101050 Health Care REITs; 60101060 Residential REITs; 60101070 Retail REITs; 60101080 Specialized REITs
    601020 Real Estate Management & Development: 60102010 Diversified Real Estate Activities; 60102020 Real Estate Operating Companies; 60102030 Real Estate Development; 60102040 Real Estate Services
""",
    "2023": """\
10 Energy
  1010 Energy
    101010 Energy Equipment & Services: 10101010 Oil & Gas Drilling; 10101020 Oil & Gas Equipment & Services
    101020 Oil, Gas & Consumable Fuels: 10102010 Integrated Oil & Gas; 10102020 Oil & Gas Exploration & Production; 10102030 Oil & Gas Refining & Marketing; 10102040 Oil & Gas Storage & Transportation; 10102050 Coal & Consumable Fuels
15 Materials
  1510 Materials
    151010 Chemicals: 15101010 Commodity Chemicals; 15101020 Diversified Chemicals; 15101030 Fertilizers & Agricultural Chemicals; 15101040 Industrial Gases; 15101050 Specialty Chemicals
    151020 Construction Materials: 15102010 Construction Materials
    151030 Containers & Packaging: 15103010 Metal, Glass & Plastic Containers; 15103020 Paper & Plastic Packaging Products & Materials
    151040 Metals & Mining: 15104010 Aluminum; 15104020 Diversified Metals & Mining; 15104025 Copper; 15104030 Gold; 15104040 Precious Metals & Minerals; 15104045 Silver; 15104050 Steel
    151050 Paper & Forest Products: 15105010 Forest Products; 15105020 Paper Products
20 Industrials
  2010 Capital Goods
    201010 Aerospace & Defense: 20101010 Aerospace & Defense
    201020 Building Products: 20102010 Building Products
    201030 Construction & Engineering: 20103010 Construction & Engineering
    201040 Electrical Equipment: 20104010 Electrical Components & Equipment; 20104020 Heavy Electrical Equipment
    201050 Industrial Conglomerates: 20105010 Industrial Conglomerates
    201060 Machinery: 20106010 Construction Machinery & Heavy Transportation Equipment; 20106015 Agricultural & Farm Machinery; 20106020 Industrial Machinery & Supplies & Components
    201070 Trading Companies & Distributors: 20107010 Trading Companies & Distributors
  2020 Commercial & Professional Services
    202010 Commercial Services & Supplies: 20201010 Commercial Printing; 20201050 Environmental & Facilities Services; 20201060 Office Services & Supplies; 20201070 Diversified Support Services; 20201080 Security & Alarm Services
    202020 Professional Services: 20202010 Human Resource & Employment Services; 20202020 Research & Consulting Services; 20202030 Data Processing & Outsourced Services
  2030 Transportation
    203010 Air Freight & Logistics: 20301010 Air Freight & Logistics
    203020 Passenger Airlines: 20302010 Passenger Airlines
    203030 Marine Transportation: 20303010 Marine Transportation
    203040 Ground Transportation: 20304010 Rail Transportation; 20304030 Cargo Ground Transportation; 20304040 Passenger Ground Transportation
    203050 Transportation Infrastructure: 20305010 Airport Services; 20305020 Highways & Railtracks; 20305030 Marine Ports & Services
25 Consumer Discretionary
  2510 Automobiles & Components
    251010 Automobile Components: 25101010 Automotive Parts & Equipment; 25101020 Tires & Rubber
    251020 Automobiles: 25102010 Automobile Manufacturers; 25102020 Motorcycle Manufacturers
  2520 Consumer Durables & Apparel
    252010 Household Durables: 25201010 Consumer Electronics; 25201020 Home Furnishings; 25201030 Homebuilding; 25201040 Household Appliances; 25201050 Housewares & Specialties
    252020 Leisure Products: 25202010 Leisure Products
    252030 Textiles, Apparel & Luxury Goods: 25203010 Apparel, Accessories & Luxury Goods; 25203020 Footwear; 25203030 Textiles
  2530 Consumer Services
    253010 Hotels, Restaurants & Leisure: 25301010 Casinos & Gaming; 25301020 Hotels, Resorts & Cruise Lines; 25301030 Leisure Facilities; 25301040 Restaurants
    253020 Diversified Consumer Services: 25302010 Education Services; 25302020 Specialized Consumer Services
  2550 Consumer Discretionary Distribution & Retail
    255010 Distributors: 25501010 Distributors
    255030 Broadline Retail: 25503030 Broadline Retail
    255040 Specialty Retail: 25504010 Apparel Retail; 25504020 Computer & Electronics Retail; 25504030 Home Improvement Retail; 25504040 Other Specialty Retail; 25504050 Automotive Retail; 25504060 Homefurnishing Retail
30 Consumer Staples
  3010 Consumer Staples Distribution & Retail
    301010 Consumer Staples Distribution & Retail: 30101010 Drug Retail; 30101020 Food Distributors; 30101030 Food Retail; 30101040 Consumer Staples Merchandise Retail
  3020 Food, Beverage & Tobacco
    302010 Beverages: 30201010 Brewers; 30201020 Distillers & Vintners; 30201030 Soft Drinks & Non-alcoholic Beverages
    302020 Food Products: 30202010 Agricultural Products & Services; 30202030 Packaged Foods & Meats
    302030 Tobacco: 30203010 Tobacco
  3030 Household & Personal Products
    303010 Household Products: 30301010 Household Products
    303020 Personal Care Products: 30302010 Personal Care Products
35 Health Care
  3510 Health Care Equipment & Services
    351010 Health Care Equipment & Supplies: 35101010 Health Care Equipment; 35101020 Health Care Supplies
    351020 Health Care Providers & Services: 35102010 Health Care Distributors; 35102015 Health Care Services; 35102020 Health Care Facilities; 35102030 Managed Health Care
    351030 Health Care Technology: 35103010 Health Care Technology
  3520 Pharmaceuticals, Biotechnology & Life Sciences
    352010 Biotechnology: 35201010 Biotechnology
    352020 Pharmaceuticals: 35202010 Pharmaceuticals
    352030 Life Sciences Tools & Services: 35203010 Life Sciences Tools & Services
40 Financials
  4010 Banks
    401010 Banks: 40101010 Diversified Banks; 40101015 Regional Banks
  4020 Financial Services
    402010 Financial Services: 40201020 Diversified Financial Services; 40201030 Multi-Sector Holdings; 40201040 Specialized Finance; 40201050 Commercial & Residential Mortgage Finance; 40201060 Transaction & Payment Processing Services
    402020 Consumer Finance: 40202010 Consumer Finance
    402030 Capital Markets: 40203010 Asset Management & Custody Banks; 40203020 Investment Banking & Brokerage; 40203030 Diversified Capital Markets; 40203040 Financial Exchanges & Data
    402040 Mortgage Real Estate Investment Trusts (REITs): 40204010 Mortgage REITs
  4030 Insurance
    403010 Insurance: 40301010 Insurance Brokers; 40301020 Life & Health Insurance; 40301030 Multi-line Insurance; 40301040 Property & Casualty Insurance; 40301050 Reinsurance
45 Information Technology
  4510 Software & Services
    451020 IT Services: 45102010 IT Consulting & Other Services; 45102030 Internet Services & Infrastructure
    451030 Software: 45103010 Application Software; 45103020 Systems Software
  4520 Technology Hardware & Equipment
    452010 Communications Equipment: 45201020 Communications Equipment
    452020 Technology Hardware, Storage & Peripherals: 45202030 Technology Hardware, Storage & Peripherals
    452030 Electronic Equipment, Instruments & Components: 45203010 Electronic Equipment & Instruments; 45203015 Electronic Components; 45203020 Electronic Manufacturing Services; 45203030 Technology Distributors
  4530 Semiconductors & Semiconductor Equipment
    453010 Semiconductors & Semiconductor Equipment: 45301010 Semiconductor Materials & Equipment; 45301020 Semiconductors
50 Communication Services
  5010 Telecommunication Services
    501010 Diversified Telecommunication Services: 50101010 Alternative Carriers; 50101020 Integrated Telecommunication Services
    501020 Wireless Telecommunication Services: 50102010 Wireless Telecommunication Services
  5020 Media & Entertainment
    502010 Media: 50201010 Advertising; 50201020 Broadcasting; 50201030 Cable & Satellite; 50201040 Publishing
    502020 Entertainment: 50202010 Movies & Entertainment; 50202020 Interactive Home Entertainment
    502030 Interactive Media & Services: 50203010 Interactive Media & Services
55 Utilities
  5510 Utilities
    551010 Electric Utilities: 55101010 Electric Utilities
    551020 Gas Utilities: 55102010 Gas Utilities
    551030 Multi-Utilities: 55103010 Multi-Utilities
    551040 Water Utilities: 55104010 Water Utilities
    551050 Independent Power and Renewable Electricity Producers: 55105010 Independent Power Producers & Energy Traders; 55105020 Renewable Electricity
60 Real Estate
  6010 Equity Real Estate Investment Trusts (REITs)
    601010 Diversified REITs: 60101010 Diversified REITs
    601025 Industrial REITs: 60102510 Industrial REITs
    601030 Hotel & Resort REITs: 60103010 Hotel & Resort REITs
    601040 Office REITs: 60104010 Office REITs
    601050 Health Care REITs: 60105010 Health Care REITs
    601060 Residential REITs: 60106010 Multi-Family Residential REITs; 60106020 Single-Family Residential REITs
    601070 Retail REITs: 60107010 Retail REITs
    601080 Specialized REITs: 60108010 Other Specialized REITs; 60108020 Self-Storage REITs; 60108030 Telecom Tower REITs; 60108040 Timber REITs; 60108050 Data Center REITs
  6020 Real Estate Management & Development
    602010 Real Estate Management & Development: 60201010 Diversified Real Estate Activities; 60201020 Real Estate Operating Companies; 60201030 Real Estate Development; 60201040 Real Estate Services
""",
}


def _parse_gics_text(era: str, txt: str) -> pd.DataFrame:
    rows = []
    sec = grp = None
    for line in txt.strip("\n").splitlines():
        ind = len(line) - len(line.lstrip())
        s = line.strip()
        if ind == 0:
            sec = tuple(s.split(" ", 1))
        elif ind == 2:
            grp = tuple(s.split(" ", 1))
        else:
            head, subs = s.split(": ", 1)
            ic, inn = head.split(" ", 1)
            for sub in subs.split("; "):
                sc, sn = sub.split(" ", 1)
                rows.append((sn, sc, inn, ic, grp[1], grp[0], sec[1], sec[0], era))
    return pd.DataFrame(rows, columns=["sub_industry", "sub_industry_code", "industry", "industry_code",
                                       "industry_group", "industry_group_code", "sector", "sector_code", "era"])


def build_gics() -> pd.DataFrame:
    """cache/universe/gics.parquet: every sub-industry of every structural era (schema in ARCHITECTURE.md + era)."""
    parts = []
    for era, vfrom, vto, legacy in GICS_ERAS:
        d = _parse_gics_text(era, _GICS_TEXT[era])
        d["valid_from"] = pd.Timestamp(vfrom) if vfrom else pd.NaT
        d["valid_to"] = pd.Timestamp(vto) if vto else pd.NaT
        d["is_legacy"] = legacy
        parts.append(d)
    g = pd.concat(parts, ignore_index=True)
    for c in ["valid_from", "valid_to"]:
        g[c] = g[c].astype("datetime64[ns]")
    return g[["sub_industry", "sub_industry_code", "industry", "industry_code", "industry_group",
              "industry_group_code", "sector", "sector_code", "valid_from", "valid_to", "is_legacy", "era"]]


def gics_era_for(date) -> str:
    d = pd.Timestamp(date)
    for era, vfrom, vto, _ in GICS_ERAS:
        if (vfrom is None or d >= pd.Timestamp(vfrom)) and (vto is None or d <= pd.Timestamp(vto)):
            return era
    return GICS_ERAS[-1][0]


def norm_gics(s) -> str:
    """Spelling/case/dash-insensitive key for a GICS name."""
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return ""
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode().lower()
    s = _FOOTNOTE.sub("", s).replace("&", " and ")
    s = re.sub(r"\band\b", " ", s)
    return re.sub(r"[^a-z0-9]+", "", s)


# Wikipedia spelling variants of SECTOR names -> canonical
GICS_NAME_ALIASES: dict[str, str] = {
    "Telecommunications Services": "Telecommunication Services",
    "Healthcare": "Health Care",
    "Information Technology Services": "IT Services",
    "Finances": "Financials",
}
_GICS_ALIAS_KEYS = {norm_gics(k): norm_gics(v) for k, v in GICS_NAME_ALIASES.items()}

# Labels found in the "GICS Sub-Industry" column of old Wikipedia revisions that are NOT sub-industry names
# (2013-2016 S&P 500 revisions and the S&P 400 pages until 2020 mix typos, industry / industry-group names and
# non-GICS phrases).  raw label -> (level, canonical name); level 'drop' = unusable label (treated as missing and
# back-filled from another snapshot of the same company).  Industry / industry-group names that match the GICS
# structure need no alias (they resolve at their own level).
GICS_LABEL_ALIASES: dict[str, tuple[str, str]] = {
    "Life Sciences Tolls & Services": ("sub", "Life Sciences Tools & Services"),
    "Life Sciences Tool & Service": ("sub", "Life Sciences Tools & Services"),
    "Life Sciences Tools & Service": ("sub", "Life Sciences Tools & Services"),
    "Life Sciences Tool & Equipment": ("sub", "Life Sciences Tools & Services"),
    "Specialty Bust Chemicals": ("sub", "Specialty Chemicals"),
    "Specialty Chemical": ("sub", "Specialty Chemicals"),
    "Data Processing & Outsources Services": ("sub", "Data Processing & Outsourced Services"),
    "Hotel, Resorts and Cruise Lines": ("sub", "Hotels, Resorts & Cruise Lines"),
    "Fertilizer and Agricultural Chemicals": ("sub", "Fertilizers & Agricultural Chemicals"),
    "Hotel & Resorts REITs": ("sub", "Hotel & Resort REITs"),
    "Human Resources & Employment Services": ("sub", "Human Resource & Employment Services"),
    "Lumber & Wood Production": ("sub", "Forest Products"),
    "IT Consulting & Outsourced Services": ("sub", "IT Consulting & Other Services"),
    "IT Consulting & Services": ("sub", "IT Consulting & Other Services"),
    "Networking Equipment": ("sub", "Communications Equipment"),
    "Telecommunications Equipment": ("sub", "Communications Equipment"),
    "Communication Equipment": ("sub", "Communications Equipment"),
    "Integrated Telecommunications Services": ("sub", "Integrated Telecommunication Services"),
    "Wireless Telecommunications Services": ("sub", "Wireless Telecommunication Services"),
    "Multi-Utilities & Unregulated Power": ("sub", "Multi-Utilities"),
    "Environmental Services": ("sub", "Environmental & Facilities Services"),
    "Diversified Facilities & Environmental": ("sub", "Environmental & Facilities Services"),
    "Specialty REITS": ("sub", "Specialized REITs"),
    "Education": ("sub", "Education Services"),
    "Coal": ("sub", "Coal & Consumable Fuels"),
    "Health Care Equipment & Sales": ("industry", "Health Care Equipment & Supplies"),
    "Broadcasting & Cable TV": ("industry", "Media"),
    "Oil & Gas Refining & Marketing & Transportation": ("industry", "Oil, Gas & Consumable Fuels"),
    "Health Care Distribution & Services": ("industry", "Health Care Providers & Services"),
    "Electronic Equipment Manufacturers": ("industry", "Electronic Equipment, Instruments & Components"),
    "Construction & Farm Equipment & Heavy Trucks": ("industry", "Machinery"),
    "REITs": ("industry", "Real Estate Investment Trusts (REITs)"),
    "REITS": ("industry", "Real Estate Investment Trusts (REITs)"),
    "Health Care Distributors & Services": ("drop", ""),
    "Diversified Commercial Services": ("drop", ""),
    "Data Processing Services": ("drop", ""),
    "Industrial Materials": ("drop", ""),
    "Financial Services": ("drop", ""),
    "Construction": ("drop", ""),
    "Military/Government/Technical": ("drop", ""),
    "Technology, Hardware, Software and Supplies": ("drop", ""),
    "Credit Card Services": ("drop", ""),
}
_LABEL_ALIAS_KEYS = {norm_gics(k): v for k, v in GICS_LABEL_ALIASES.items()}


class GicsMapper:
    """sub-industry (or sector) name + snapshot date -> full GICS hierarchy valid at that date."""

    def __init__(self, gics: pd.DataFrame | None = None):
        g = gics if gics is not None else build_gics()
        self.g = g
        self.eras = [e[0] for e in GICS_ERAS]
        self.by_era_sub: dict[str, dict[str, dict]] = {e: {} for e in self.eras}
        self.by_era_sector: dict[str, dict[str, dict]] = {e: {} for e in self.eras}
        self.by_era_ind: dict[str, dict[str, dict]] = {e: {} for e in self.eras}
        self.by_era_grp: dict[str, dict[str, dict]] = {e: {} for e in self.eras}
        for r in g.to_dict("records"):
            self.by_era_sub[r["era"]][norm_gics(r["sub_industry"])] = r
            self.by_era_sector[r["era"]].setdefault(norm_gics(r["sector"]), r)
            self.by_era_ind[r["era"]].setdefault(norm_gics(r["industry"]), r)
            self.by_era_grp[r["era"]].setdefault(norm_gics(r["industry_group"]), r)

    def _order(self, era: str) -> list[str]:
        i = self.eras.index(era)
        return sorted(self.eras, key=lambda e: (abs(self.eras.index(e) - i), self.eras.index(e)))

    @staticmethod
    def _out(r: dict | None, flag: str) -> dict:
        if r is None:
            return {"gics_sector": None, "gics_industry_group": None, "gics_industry": None, "gics_sub_industry": None,
                    "sector_code": None, "industry_group_code": None, "industry_code": None,
                    "sub_industry_code": None, "gics_era": None, "gics_flag": flag}
        return {"gics_sector": r["sector"], "gics_industry_group": r["industry_group"], "gics_industry": r["industry"],
                "gics_sub_industry": r["sub_industry"], "sector_code": r["sector_code"],
                "industry_group_code": r["industry_group_code"], "industry_code": r["industry_code"],
                "sub_industry_code": r["sub_industry_code"], "gics_era": r["era"], "gics_flag": flag}

    def map_sub(self, sub_name, sector_name, date) -> dict:
        """Hierarchy for a snapshot's sub-industry label as of ``date``.

        gics_flag: '' exact in the era valid at ``date``; 'alias' after a spelling alias; 'era_fallback:<era>' the
        name only exists in another era (typically Wikipedia lagging a GICS change); 'sector_mismatch' the mapped
        sector differs from the snapshot's own sector column; 'unmapped'.
        """
        k = norm_gics(sub_name)
        if not k:
            return self._out(None, "no_sub_industry")
        k = _GICS_ALIAS_KEYS.get(k, k)
        era = gics_era_for(date)
        sk = _GICS_ALIAS_KEYS.get(norm_gics(sector_name), norm_gics(sector_name)) if sector_name else ""
        cands = [(e, self.by_era_sub[e][k]) for e in self._order(era) if k in self.by_era_sub[e]]
        if not cands:
            return self._out(None, "unmapped")
        # prefer the era valid at date; else a candidate whose sector agrees with the snapshot's sector
        e0, r0 = cands[0]
        if e0 == era:
            flag = "" if (not sk or norm_gics(r0["sector"]) == sk) else "sector_mismatch"
            if flag == "sector_mismatch":
                agree = [c for c in cands[1:] if norm_gics(c[1]["sector"]) == sk]
                if agree:
                    return self._out(agree[0][1], f"era_fallback:{agree[0][0]}")
            return self._out(r0, flag)
        agree = [c for c in cands if sk and norm_gics(c[1]["sector"]) == sk]
        e1, r1 = (agree[0] if agree else cands[0])
        return self._out(r1, f"era_fallback:{e1}" + ("" if (agree or not sk) else "+sector_mismatch"))

    def map_label(self, label, sector, date, force_level: str | None = None) -> dict:
        """Resolve a raw "GICS Sub-Industry" column value of any quality.

        Returns the map_sub-style dict plus ``gics_level`` in {'sub', 'industry', 'group', 'sector', 'none'}; only
        the fields down to that level are filled.  Order: alias table, sub-industry, industry, industry group,
        sector.  ``force_level`` skips the alias table and searches one level only (used for canonical names).
        """
        k = norm_gics(label)
        flag_prefix = ""
        forced = force_level
        if forced is None and k in _LABEL_ALIAS_KEYS:
            lv, canon = _LABEL_ALIAS_KEYS[k]
            if lv == "drop":
                out = self._out(None, "bad_label")
                out["gics_level"] = "none"
                return out
            forced, k, flag_prefix = lv, norm_gics(canon), "alias"
        if not k:
            out = self._out(None, "no_sub_industry")
            out["gics_level"] = "none"
            return out
        k = _GICS_ALIAS_KEYS.get(k, k)
        era = gics_era_for(date)
        sk = norm_gics(sector) if sector else ""
        sk = _GICS_ALIAS_KEYS.get(sk, sk)
        tables = {"sub": self.by_era_sub, "industry": self.by_era_ind, "group": self.by_era_grp,
                  "sector": self.by_era_sector}
        levels = [forced] if forced else ["sub", "industry", "group", "sector"]
        # pass 0: the era valid at ``date`` (all levels); pass 1: the other eras by distance (Wikipedia lag)
        for era_pass in (0, 1):
            for level in levels:
                eras_try = [era] if era_pass == 0 else self._order(era)[1:]
                cands = [(e, tables[level][e][k]) for e in eras_try if k in tables[level][e]]
                if not cands:
                    continue
                agree = [c for c in cands if sk and norm_gics(c[1]["sector"]) == sk]
                if era_pass == 0:
                    e1, r1 = cands[0]
                    flag = "" if (not sk or norm_gics(r1["sector"]) == sk) else "sector_mismatch"
                else:
                    e1, r1 = (agree[0] if agree else cands[0])
                    flag = f"era_fallback:{e1}" + ("" if (agree or not sk) else "+sector_mismatch")
                if flag_prefix:
                    flag = flag_prefix + ("+" + flag if flag else "")
                out = self._out(r1, flag)
                keep = {"sub": 4, "industry": 3, "group": 2, "sector": 1}[level]
                order = ["gics_sector", "gics_industry_group", "gics_industry", "gics_sub_industry"]
                codes = ["sector_code", "industry_group_code", "industry_code", "sub_industry_code"]
                for i in range(keep, 4):
                    out[order[i]] = None
                    out[codes[i]] = None
                out["gics_level"] = level
                return out
        out = self._out(None, "unmapped")
        out["gics_level"] = "none"
        return out

    def map_sector(self, sector_name, date) -> dict:
        """Sector-only label (early snapshots without a sub-industry column)."""
        sk = _GICS_ALIAS_KEYS.get(norm_gics(sector_name), norm_gics(sector_name))
        if not sk:
            return self._out(None, "no_sector")
        for e in self._order(gics_era_for(date)):
            r = self.by_era_sector[e].get(sk)
            if r is not None:
                out = self._out(r, "sector_only" if e == gics_era_for(date) else f"sector_only:era_fallback:{e}")
                for c in ["gics_industry_group", "gics_industry", "gics_sub_industry", "industry_group_code",
                          "industry_code", "sub_industry_code"]:
                    out[c] = None
                return out
        return self._out(None, "unmapped_sector")


# --------------------------------------------------------------------------------------
# ticker / name -> SEC CIK
# --------------------------------------------------------------------------------------
_LEGAL = {"inc", "incorporated", "corp", "corporation", "co", "company", "ltd", "limited", "plc", "llc", "lp", "l",
          "p", "sa", "nv", "ag", "se", "the", "de", "new", "cl", "class", "ii", "iii"}
_SOFT = {"holdings", "holding", "group", "international", "intl", "trust", "cos", "companies", "technologies",
         "technology", "systems", "industries", "enterprises", "worldwide", "global", "financial", "bancorp",
         "bancorporation", "partners", "and", "of", "us", "usa", "america", "american"}
_STATE_TAG = re.compile(r"/[a-z]{2,6}/?", re.I)


_ABBREV = {"intl": "international", "int": "international", "inti": "international", "hldg": "holdings",
           "hldgs": "holdings", "hlds": "holdings", "mfg": "manufacturing", "pharm": "pharmaceuticals",
           "labs": "laboratories", "svcs": "services", "svc": "services", "fin": "financial", "grp": "group",
           "natl": "national", "ent": "entertainment", "res": "resources", "cos": "companies"}
_INITIALS_PAREN = re.compile(r"\(\s*((?:[A-Za-z]\.){1,4}[A-Za-z]?\.?)\s*\)")


def name_tokens(s) -> list[str]:
    """Lower-case alphanumeric tokens of a company name (parentheticals, state tags and footnotes removed).

    "Bard (C.R.) Inc." keeps the initials (SEC writes "BARD C R INC /NJ/"); abbreviations are expanded.
    """
    if s is None or (isinstance(s, float) and np.isnan(s)):
        return []
    s = unicodedata.normalize("NFKD", str(s)).encode("ascii", "ignore").decode()
    s = _FOOTNOTE.sub(" ", s)
    s = _INITIALS_PAREN.sub(lambda m: " " + m.group(1).replace(".", " ") + " ", s)
    s = re.sub(r"\([^)]*\)", " ", s)
    s = _STATE_TAG.sub(" ", s)
    s = s.lower().replace("&", " and ").replace("'", "")
    toks = [_ABBREV.get(t, t) for t in re.findall(r"[a-z0-9]+", s)]
    # trailing share-class designators: "... Co B", "... Cl. A", "Inc-A"
    while len(toks) > 2 and (toks[-1] in ("a", "b", "c") or (toks[-2] in ("cl", "class") and len(toks[-1]) == 1)):
        toks = toks[:-1]
    while len(toks) > 2 and toks[-1] in ("cl", "class"):
        toks = toks[:-1]
    return toks


def name_keys(s) -> list[tuple[str, str]]:
    """Match keys, strongest first: legal-suffix-stripped (joined / token-set), then soft-stripped."""
    tk = name_tokens(s)
    full = [t for t in tk if t not in _LEGAL]
    soft = [t for t in full if t not in _SOFT]
    keys = []
    if full:
        keys += [("F", "".join(full)), ("FS", " ".join(sorted(full)))]
    if soft and soft != full:
        keys += [("S", "".join(soft)), ("SS", " ".join(sorted(soft)))]
    return keys


def name_sim(a, b) -> float:
    ta, tb = {t for t in name_tokens(a) if t not in _LEGAL | _SOFT}, {t for t in name_tokens(b) if t not in _LEGAL | _SOFT}
    if not ta or not tb:
        return 0.0
    return len(ta & tb) / len(ta | tb)


# Hand-checked fixes for names the automatic matcher cannot resolve (each documented; see the report).
# (ticker_raw, valid_from, valid_to, cik, note). Dates inclusive; None = open.
CIK_OVERRIDES: list[tuple[str, str | None, str | None, int, str]] = [
    # lead fixes after the independent data audit (name-only matches had picked unrelated small registrants)
    ("NVE", None, None, 741508, "NV Energy, Inc. (name match had picked US Energy / Big Sky Industrial)"),
    ("LSI", None, "2014-12-31", 703360, "LSI Corp (formerly LSI Logic, acquired by Avago 2014-05); name match had "
     "picked LSI Industries (LYTS). Ticker LSI was later Life Storage (2016-23), which must not inherit this CIK"),
    ("TBL", None, None, 814361, "The Timberland Co; name match had picked Timberland Bancorp (TSBK)"),
    ("AABA", None, None, 1011006, "fja ticker for Yahoo! Inc. after the 2017 rename to Altaba (CIK unchanged)"),
    ("BHGE", None, "2017-06-30", 808362, "fja back-fills the Baker Hughes GE ticker over Baker Hughes Inc. (BHI)"),
    ("BTUUQ", None, None, 1064728, "Peabody Energy: post-bankruptcy Q symbol used by fja"),
    ("ANRZQ", None, None, 1301063, "Alpha Natural Resources: post-bankruptcy Q symbol used by fja"),
    ("EKDKQ", None, None, 31235, "Eastman Kodak: post-bankruptcy Q symbol used by fja"),
    ("SUNEQ", None, None, 945436, "SunEdison (formerly MEMC): post-bankruptcy Q symbol used by fja"),
    ("DXC", None, "2017-03-31", 23082, "fja back-fills DXC over Computer Sciences Corp. (CSC, CIK 23082)"),
    ("EVHC", "2016-06-01", "2019-12-31", 1678531, "Envision Healthcare Corp (post-AmSurg merger registrant)"),
    ("AVGO", "2015-01-01", "2018-10-31", 1441634, "Avago / Broadcom Ltd before Broadcom Inc. (CIK 1730168) took over in 2018-11"),
    ("JEF", None, "2018-06-30", 96223, "fja back-fills JEF over Leucadia National (LUK, CIK 96223 = Jefferies Financial Group)"),
    ("IFF", None, None, 51253, "International Flavors & Fragrances (abbreviated Wikipedia name)"),
    ("DD", None, "2017-08-31", 30554, "E. I. du Pont de Nemours (EIDP, CIK 30554) before the DowDuPont merger"),
    ("PBCT", None, None, 1378946, "People's United Financial"),
    ("NLSN", None, None, 1492633, "Nielsen Holdings plc"),
    ("WIN", None, None, 1282266, "Windstream Holdings / Windstream Corp (Wikipedia name: Windstream Communications)"),
    ("TUP", None, None, 1008654, "Tupperware Brands"),
    ("WDR", None, None, 1052100, "Waddell & Reed Financial (abbreviated Wikipedia name)"),
    ("SNH", None, None, 1075415, "Senior Housing Properties Trust = Diversified Healthcare Trust"),
    ("HPT", None, None, 945394, "Hospitality Properties Trust = Service Properties Trust"),
    ("MDRX", None, None, 1124804, "Allscripts Healthcare Solutions = Veradigm"),
    ("FNFG", None, None, 1051741, "First Niagara Financial Group (abbreviated Wikipedia name)"),
    ("HMA", None, None, 792985, "Health Management Associates"),
    ("WBS", None, None, 801337, "Webster Financial (Wikipedia name: Webster Bank)"),
    ("IRT", None, None, 1466085, "Independence Realty Trust (Wikipedia name: IRT Living)"),
    ("X", None, None, 1163302, "United States Steel"),
    ("PPDI", None, None, 1003124, "Pharmaceutical Product Development"),
    ("KCI", None, None, 831967, "Kinetic Concepts"),
    ("PCH", None, None, 1338749, "Potlatch = PotlatchDeltic"),
    ("APOL", None, None, 929887, "Apollo Group = Apollo Education Group"),
    ("HYH", None, None, 1606498, "Halyard Health = Avanos Medical"),
    ("SMCI", None, None, 1375365, "Super Micro Computer (Wikipedia name: Supermicro)"),
    ("FICO", None, None, 814547, "Fair Isaac (Wikipedia name: FICO)"),
    ("UMPQ", None, None, 1077771, "Umpqua Holdings"),
    ("UTR", None, None, 860748, "Unitrin = Kemper Corp"),
    ("CNL", None, None, 1089819, "Cleco Corporation (Wikipedia typo: CLECO Coporation)"),
    ("AMWD", None, None, 794619, "American Woodmark"),
    ("APEI", None, None, 1201792, "American Public Education"),
    ("AAXN", None, None, 1069183, "Axon Enterprise (formerly TASER)"),
    ("CDAY", None, None, 1725057, "Ceridian HCM = Dayforce"),
    ("ACET", None, None, 2034, "Aceto Corp"),
    ("RDK", None, None, 85704, "Ruddick Corp = Harris Teeter Supermarkets"),
    ("VCLK", None, None, 1080034, "ValueClick = Conversant"),
    ("OZK", None, None, 1038205, "Bank OZK (Bank of the Ozarks; files with the FDIC after 2022)"),
    ("DTV", "2009-12-01", "2015-07-31", 1465112, "DIRECTV (public parent after the 2009 Liberty Entertainment merger)"),
]

# Re-domiciled holding companies / successor registrants: history lives under the OLD cik, SEC's current ticker
# file points to the NEW one.  (old_cik, new_cik, note).  Written to cache/universe/cik_aliases.csv.
CIK_ALIASES: list[tuple[int, int, str]] = [
    (34088, 2115436, "Exxon Mobil holding-company reorganisation 2026-07: SEC ticker file points to the new registrant "
                     "(2 quarters of history), the 30-year history is under the old CIK"),
    (1364742, 2012383, "BlackRock, Inc. new registrant after the 2024-02 reorganisation (old CIK renamed BlackRock Finance, Inc.)"),
    (1144519, 1996862, "Bunge Limited -> Bunge Global SA redomiciliation 2023-11"),
    (73088, 1993004, "NorthWestern Corp -> NorthWestern Energy Group holding company 2023-10"),
    (1620280, 2020795, "Uniti Group (old registrant, now Uniti Group LLC) -> new Uniti Group Inc. after the Windstream merger 2024-05"),
    (1115055, 2082866, "Pinnacle Financial Partners -> new registrant after the Synovus merger 2025-08"),
    (811532, 1999001, "Cedar Fair L.P. -> Six Flags Entertainment Corporation (ticker FUN continues) 2023-11"),
    (813828, 2041610, "Paramount Global (CBS / ViacomCBS / PARA) -> Paramount Skydance (new registrant 2024-11; PSKY, now SKYD)"),
]


class CikMapper:
    """Resolve (ticker, name, date[, Wikipedia CIK]) to an SEC CIK with an audit trail (``method``)."""

    def __init__(self, companies: pd.DataFrame):
        self.today = pd.Timestamp(dt.date.today())
        c = companies.copy()
        self.c = c.set_index("cik")
        tt = current_ticker_table(c)
        tt = tt.assign(n10k=tt["cik"].map(self.c["n_10k"]))
        tt = tt.sort_values(["n10k", "rank"], ascending=[False, True]).drop_duplicates("ticker")
        self.tick2cik: dict[str, int] = dict(zip(tt["ticker"], tt["cik"]))
        self.tick2cik_yf: dict[str, int] = {to_yf(t): k for t, k in self.tick2cik.items()}
        self.first_filing = self.c["first_filing_date"].to_dict()
        # last 10-K/10-Q date (subsidiaries and shells keep filing 8-Ks long after the operating company moved on)
        lp = self.c["last_periodic_filing_date"].where(self.c["last_periodic_filing_date"].notna(), self.c["last_filing_date"])
        self.last_filing = lp.to_dict()
        self.n10k = self.c["n_10k"].to_dict()
        self.names_by_cik: dict[int, list[tuple[str, pd.Timestamp, pd.Timestamp]]] = {}
        index: dict[str, list[tuple[int, pd.Timestamp, pd.Timestamp]]] = {}
        for r in c[["cik", "name", "former_names", "first_filing_date", "last_filing_date"]].itertuples(index=False):
            cik = int(r.cik)
            fn = []
            try:
                fn = json.loads(r.former_names) if r.former_names else []
            except Exception:
                fn = []
            spans = []
            for f in fn:
                try:
                    a = pd.Timestamp(f["from"]).tz_localize(None) if f.get("from") else pd.Timestamp("1990-01-01")
                    b = pd.Timestamp(f["to"]).tz_localize(None) if f.get("to") else self.today
                except Exception:
                    continue
                spans.append((f["name"], a.normalize(), b.normalize()))
            cur_from = max([b for _, _, b in spans], default=pd.Timestamp(r.first_filing_date)
                           if pd.notna(r.first_filing_date) else pd.Timestamp("1990-01-01"))
            cur_to = self.today + pd.Timedelta(days=3650)
            if pd.notna(r.last_filing_date):         # the current name is not valid after the company stopped filing
                cur_to = min(cur_to, pd.Timestamp(r.last_filing_date) + pd.Timedelta(days=90))
            spans.append((r.name, cur_from, cur_to))
            self.names_by_cik[cik] = spans
            for nm, a, b in spans:
                for lvl, k in name_keys(nm):
                    index.setdefault(k, []).append((cik, a, b))
        self.name_index = index
        self.overrides = CIK_OVERRIDES
        self._partners: dict[int, tuple] = {}
        for o, n, _ in CIK_ALIASES:
            self._partners[o] = (n,)
            self._partners[n] = (o,)
        # inverted token index for the subset fallback (current + former names)
        tok: dict[str, set[int]] = {}
        self.cik_tokens: dict[int, list[frozenset]] = {}
        for cik, spans in self.names_by_cik.items():
            sets = []
            for nm, _, _ in spans:
                ts = frozenset(t for t in name_tokens(nm) if t not in _LEGAL)
                if ts:
                    sets.append(ts)
                    for t in ts:
                        tok.setdefault(t, set()).add(cik)
            self.cik_tokens[cik] = sets
        self.tok_index = tok

    # ---- helpers ----
    def _override(self, ticker_raw: str, date) -> int | None:
        for t, a, b, cik, _ in self.overrides:
            if t == ticker_raw and (a is None or date >= pd.Timestamp(a)) and (b is None or date <= pd.Timestamp(b)):
                return cik
        return None

    def name_candidates(self, name, date, slack_days: int = 400) -> list[tuple[int, int, bool]]:
        """[(cik, key_rank, exact_validity)] sorted best first."""
        found: dict[int, tuple[int, bool]] = {}
        slack = pd.Timedelta(days=slack_days)
        for rank, (lvl, k) in enumerate(name_keys(name)):
            for cik, a, b in self.name_index.get(k, ()):
                exact = a <= date <= b
                ok = exact or (a - slack <= date <= b + slack)
                if not ok:
                    continue
                prev = found.get(cik)
                cand = (rank, not exact)
                if prev is None or cand < (prev[0], not prev[1]):
                    found[cik] = (rank, exact)
        out = [(cik, r, e) for cik, (r, e) in found.items()]

        def still_filing(cik: int) -> int:
            lf = self.last_filing.get(cik)
            return 0 if (pd.notna(lf) and lf >= date - pd.Timedelta(days=60)) else 1

        out.sort(key=lambda x: (not x[2], x[1], still_filing(x[0]), -int(self.n10k.get(x[0], 0) or 0)))
        return out

    def subset_candidate(self, name, date) -> int | None:
        """Unique company that filed around ``date`` whose name tokens contain all of the (>= 2) name tokens."""
        want = frozenset(t for t in name_tokens(name) if t not in _LEGAL and t not in _SOFT)
        if len(want) < 2:
            return None
        cand: set[int] | None = None
        for t in want:
            ids = self.tok_index.get(t)
            if not ids:
                return None
            cand = set(ids) if cand is None else cand & ids
            if not cand:
                return None
        cand = {c for c in cand if self.plausible_by_date(c, date, 365) and (self.n10k.get(c) or 0) >= 1
                and any(want <= ts for ts in self.cik_tokens[c])}
        if not cand:
            return None
        best = sorted(cand, key=lambda c: (min(len(ts - want) for ts in self.cik_tokens[c] if want <= ts),
                                           -(self.n10k.get(c) or 0)))
        if len(best) > 1:
            e0 = min(len(ts - want) for ts in self.cik_tokens[best[0]] if want <= ts)
            e1 = min(len(ts - want) for ts in self.cik_tokens[best[1]] if want <= ts)
            if e0 == e1:
                return None
        return best[0]

    def plausible_by_date(self, cik: int, date, slack_days: int = 120) -> bool:
        s = pd.Timedelta(days=slack_days)
        for c in (cik, *self._partners.get(cik, ())):      # old / new registrant of a CIK alias count as one company
            a, b = self.first_filing.get(c), self.last_filing.get(c)
            if pd.notna(a) and pd.notna(b) and (a - s <= date) and (b + s >= date):
                return True
        return False

    def best_name_sim(self, cik: int, name) -> float:
        return max((name_sim(nm, name) for nm, _, _ in self.names_by_cik.get(cik, [])), default=0.0)

    # ---- main entry ----
    def resolve(self, ticker_raw: str, name, date, wiki_cik=None) -> tuple[int | None, str]:
        date = pd.Timestamp(date)
        ov = self._override(ticker_raw, date)
        if ov is not None:
            return ov, "override"
        wc = None
        if wiki_cik is not None and not (isinstance(wiki_cik, float) and np.isnan(wiki_cik)) and int(wiki_cik) in self.n10k:
            wc = int(wiki_cik)
            if self.plausible_by_date(wc, date, 120):
                return wc, "wiki_cik"
        yf = to_yf(ticker_raw)
        t = self.tick2cik_yf.get(yf)
        nc = self.name_candidates(name, date) if name else []
        exact = [c for c in nc if c[2]]
        if t is not None and name:
            if any(t == c for c, _, _ in exact):
                return t, "ticker+name"
        if exact and exact[0][1] <= 1:           # exact-validity match on the legal-suffix-stripped name
            return exact[0][0], "name"
        if t is not None and name:
            if any(t == c for c, _, _ in nc):
                return t, "ticker+name_loose"
            if self.best_name_sim(t, name) >= 0.5 and self.plausible_by_date(t, date):
                return t, "ticker+fuzzy"
        if nc:
            return nc[0][0], "name_soft" if nc[0][2] else "name_loose"
        if t is not None and not name and self.plausible_by_date(t, date):
            return t, "ticker_date"
        if t is not None and name and self.plausible_by_date(t, date) and self.best_name_sim(t, name) >= 0.25:
            return t, "ticker+fuzzy_low"
        if name:
            sub = self.subset_candidate(name, date)
            if sub is not None:
                return sub, "name_subset"
        if wc is not None:
            return wc, "wiki_cik_implausible"
        return None, "unmapped_conflict" if t is not None else "unmapped"


# --------------------------------------------------------------------------------------
# S&P 500 exact membership (fja05680/sp500) -> spells -> CIK
# --------------------------------------------------------------------------------------
def download_fja(force: bool = False) -> None:
    FJA_DIR.mkdir(parents=True, exist_ok=True)
    sess = requests.Session()
    sess.headers["User-Agent"] = WIKI_USER_AGENT
    for local, remote in FJA_FILES.items():
        path = FJA_DIR / local
        if path.exists() and not force:
            continue
        r = sess.get(FJA_BASE + remote, timeout=120)
        r.raise_for_status()
        tmp = path.with_suffix(".tmp")
        tmp.write_bytes(r.content)
        os.replace(tmp, path)
        time.sleep(1.0)


def load_fja_history() -> pd.DataFrame:
    """date, tickers(set) rows of 'S&P 500 Historical Components & Changes (Updated)'."""
    download_fja()
    h = pd.read_csv(FJA_DIR / "sp500_hist_updated.csv")
    h["date"] = pd.to_datetime(h["date"]).astype("datetime64[ns]")
    h["tickers"] = h["tickers"].map(lambda s: frozenset(x.strip() for x in str(s).split(",") if x.strip()))
    return h.sort_values("date").reset_index(drop=True)


def patch_fja_with_current(h: pd.DataFrame, cur: pd.DataFrame, cur_date: pd.Timestamp) -> tuple[pd.DataFrame, dict]:
    """Append synthetic snapshots so the fja history ends at the CURRENT Wikipedia S&P 500 table.

    Adds take the table's "Date added" (if after the last fja snapshot, else ``cur_date``); removals are paired in
    sorted order with the add dates (the exact removal dates are not published) and any leftover removals take
    ``cur_date``.  Returns (history, info).
    """
    last = h["date"].iloc[-1]
    s_last = set(h["tickers"].iloc[-1])
    w = set(cur["ticker_raw"])
    adds, rems = sorted(w - s_last), sorted(s_last - w)
    info = {"fja_last": last, "adds": adds, "removes": rems}
    if not adds and not rems:
        return h, info
    da = cur.set_index("ticker_raw")["date_added"].to_dict()
    add_dates = {}
    for t in adds:
        d = pd.to_datetime(da.get(t), errors="coerce")
        add_dates[t] = d.normalize() if pd.notna(d) and d.normalize() > last else cur_date
    events: dict[pd.Timestamp, tuple[list, list]] = {}
    order = sorted(adds, key=lambda t: (add_dates[t], t))
    for i, t in enumerate(order):
        d = add_dates[t]
        ev = events.setdefault(d, ([], []))
        ev[0].append(t)
        if i < len(rems):
            ev[1].append(rems[i])
    for t in rems[len(order):]:
        events.setdefault(cur_date, ([], []))[1].append(t)
    cur_set = set(s_last)
    new_rows = []
    for d in sorted(events):
        a, r = events[d]
        cur_set = (cur_set - set(r)) | set(a)
        new_rows.append({"date": d, "tickers": frozenset(cur_set)})
    info["final_equals_current"] = cur_set == w
    return pd.concat([h, pd.DataFrame(new_rows)], ignore_index=True), info


def fja_spells(h: pd.DataFrame, start: pd.Timestamp = HIST_START) -> pd.DataFrame:
    """Maximal runs of consecutive snapshots in which a ticker is a member: ticker_fja, start, end (exclusive; NaT=open)."""
    h = h.sort_values("date").reset_index(drop=True)
    i0 = int(np.searchsorted(h["date"].values, np.datetime64(start), side="right")) - 1
    i0 = max(i0, 0)
    h = h.iloc[i0:].reset_index(drop=True)
    dates = list(h["date"])
    dates[0] = max(dates[0], start) if dates[0] < start else dates[0]
    if h["date"].iloc[0] < start:
        dates[0] = start
    open_: dict[str, pd.Timestamp] = {}
    out = []
    prev: frozenset = frozenset()
    for d, s in zip(dates, h["tickers"]):
        for t in s - prev:
            open_[t] = d
        for t in prev - s:
            out.append((t, open_.pop(t), d))
        prev = s
    for t, d0 in open_.items():
        out.append((t, d0, pd.NaT))
    sp = pd.DataFrame(out, columns=["ticker_fja", "start", "end"])
    sp["source"] = "fja05680"
    for c in ["start", "end"]:
        sp[c] = sp[c].astype("datetime64[ns]")
    return sp.sort_values(["start", "ticker_fja"]).reset_index(drop=True)


class FjaResolver:
    """Resolve an fja ticker string at a date to the company (CIK) valid on that date.

    The 'Updated' fja file back-fills later tickers into early years (ANTM for 2010 WellPoint, ARNC for 2009
    Alcoa) and restructured issuers change CIK over time (Medtronic Inc -> plc), so a spell-level CIK is wrong
    for part of the sample.  Evidence, in order: manual override; the Wikipedia rows (any index) with the same
    ticker, nearest in time first, accepting the first whose CIK was filing on that date; the SEC current ticker
    file if that company was filing on that date.
    """

    def __init__(self, wiki_rows: pd.DataFrame, mapper: CikMapper):
        self.m = mapper
        wr = wiki_rows[wiki_rows["cik"].notna()][["ticker_raw", "snapshot_date", "cik", "name"]]
        self.by_t = {t: (g["snapshot_date"].to_numpy(), g["cik"].astype("int64").to_numpy(), g["name"].to_numpy())
                     for t, g in wr.sort_values("snapshot_date").groupby("ticker_raw")}
        self.cache: dict = {}

    def resolve(self, ticker: str, date: pd.Timestamp) -> tuple[int | None, str, str | None]:
        key = (ticker, date.to_period("M"))
        if key in self.cache:
            return self.cache[key]
        out: tuple = (None, "unmapped", None)
        ov = self.m._override(ticker, date)
        if ov is not None:
            out = (ov, "override", None)
        else:
            ev = self.by_t.get(ticker)
            if ev is not None:
                dts, ciks, names = ev
                delta = (dts - np.datetime64(date)).astype("timedelta64[D]").astype(int)
                # contemporaneous rows first, then LATER rows (the file back-fills later tickers), then earlier rows
                prio = np.where(np.abs(delta) <= 100, 0, np.where(delta > 0, 1, 2))
                order = np.lexsort((np.abs(delta), prio))
                seen = set()
                for k in order:
                    c = int(ciks[k])
                    if c in seen:
                        continue
                    seen.add(c)
                    if self.m.plausible_by_date(c, date, 120):
                        out = (c, "wiki_near", names[k])
                        break
            if out[0] is None:
                tc = self.m.tick2cik_yf.get(to_yf(ticker))
                if tc is not None and self.m.plausible_by_date(tc, date, 120):
                    out = (tc, "sec_ticker", None)
        self.cache[key] = out
        return out


# --------------------------------------------------------------------------------------
# Snapshot collection (with fall-backs) and CIK / GICS attachment
# --------------------------------------------------------------------------------------
FALLBACK_MAX_PREV_Q = 6      # an unusable quarter may reuse an earlier usable snapshot up to this many quarters old
FALLBACK_MAX_NEXT_Q = 1      # ... or (flagged, one-quarter look-ahead) a later one up to this many quarters ahead


def collect_snapshots(client: WikiClient, fetch: bool = True) -> tuple[pd.DataFrame, pd.DataFrame]:
    """All Wikipedia snapshots -> (meta, rows).

    meta: one row per (index, snapshot_date) incl. the CURRENT page (snapshot_date = today): revid, rev_ts, n_rows,
          gics_cov, sector_cov, usable, status ('ok' | 'derived_sp1000_minus_sp400' | 'fallback_prev:<date>' |
          'fallback_next:<date>' | 'missing').
    rows: constituent rows (ticker_raw, name, raw gics labels, wiki cik, date_added) with snapshot_date of the
          quarter they represent (fallback rows are copies of the donor snapshot).

    In 2018-2019 the "List of S&P 600 companies" page actually held the combined S&P 1000 (~995 rows); those
    snapshots are turned into an S&P 600 list by removing the tickers of the contemporaneous S&P 400 snapshot.
    """
    qs = quarter_ends()
    today = pd.Timestamp(dt.date.today())
    sels: dict[str, list[dict]] = {}
    for index in INDEXES:
        sel = select_snapshots(client, index, qs, fetch=fetch)
        rev = client.latest_revision(PAGES[index])
        cdf = load_parsed(client, rev["revid"])
        sel.append({"index": index, "snapshot_date": today, "revid": rev["revid"],
                    "rev_ts": pd.to_datetime(rev["timestamp"], utc=True).tz_localize(None),
                    **snapshot_quality(cdf, index), "backsteps": 0, "df": cdf})
        sels[index] = sel
    # combined S&P 1000 pages stored under the S&P 600 title -> S&P 600 = S&P 1000 minus S&P 400
    for s6, s4 in zip(sels["SP600"], sels["SP400"]):
        if s6["df"] is not None and 900 <= s6["n_rows"] <= 1100 and s4["df"] is not None and s4["ok_rows"]:
            d6 = s6["df"]
            d6 = d6[~d6["ticker_raw"].isin(set(s4["df"]["ticker_raw"]))].reset_index(drop=True)
            s6["df"] = d6
            s6.update(snapshot_quality(d6, "SP600"))
            s6["derived"] = True
    meta_rows, row_parts = [], []
    for index in INDEXES:
        sel = sels[index]
        for s in sel:
            s["usable"] = bool(s["df"] is not None and s["ok_rows"] and s["sector_cov"] >= 0.8)
        usable_idx = [i for i, s in enumerate(sel) if s["usable"]]
        for i, s in enumerate(sel):
            donor, status = s, ("derived_sp1000_minus_sp400" if s.get("derived") and s["usable"] else "ok")
            if not s["usable"]:
                prev = [j for j in usable_idx if j < i and i - j <= FALLBACK_MAX_PREV_Q]
                nxt = [j for j in usable_idx if j > i and j - i <= FALLBACK_MAX_NEXT_Q]
                if prev:
                    donor = sel[prev[-1]]
                    status = f"fallback_prev:{donor['snapshot_date'].date()}"
                elif nxt:
                    donor = sel[nxt[0]]
                    status = f"fallback_next:{donor['snapshot_date'].date()}"
                else:
                    donor, status = None, "missing"
            meta_rows.append({
                "index": index, "snapshot_date": s["snapshot_date"], "revid": s["revid"], "rev_ts": s["rev_ts"],
                "n_rows": s["n_rows"], "gics_cov": s["gics_cov"], "sector_cov": s["sector_cov"],
                "usable": s["usable"], "backsteps": s["backsteps"], "status": status,
                "stale_days": (s["snapshot_date"] - s["rev_ts"]).days if pd.notna(s["rev_ts"]) else np.nan})
            if donor is not None and donor["df"] is not None:
                d = donor["df"].copy()
                d["index"] = index
                d["snapshot_date"] = s["snapshot_date"]
                d["revid"] = donor["revid"]
                d["rev_ts"] = donor["rev_ts"]
                d["snapshot_quality"] = status
                row_parts.append(d)
    meta = pd.DataFrame(meta_rows)
    rows = pd.concat(row_parts, ignore_index=True)
    for c in ["snapshot_date", "rev_ts"]:
        meta[c] = meta[c].astype("datetime64[ns]")
        rows[c] = rows[c].astype("datetime64[ns]")
    rows = rows.rename(columns={"cik": "cik_wiki"})
    # some pages list dual-class lines twice; keep one row per (snapshot, index, ticker)
    rows = rows.drop_duplicates(["index", "snapshot_date", "ticker_raw"]).reset_index(drop=True)
    return meta, rows


def flag_stale_listings(wrows: pd.DataFrame, mapper: CikMapper, days: int = 200) -> pd.Series:
    """True for rows of the derived S&P 1000-minus-S&P 400 snapshots whose company stopped filing > ``days`` earlier.

    The combined S&P 1000 page was poorly maintained between late 2018 and 2020: by mid-2020 about 10% of its rows are
    companies that had already stopped filing.  They are flagged (and excluded by ``members(drop_stale=True)``), so the
    derived S&P 600 for 2019-2020 is understated.
    """
    derived = wrows["snapshot_quality"] == "derived_sp1000_minus_sp400"
    last = wrows["cik"].map(lambda c: mapper.last_filing.get(int(c), pd.NaT) if pd.notna(c) else pd.NaT)
    last = pd.to_datetime(last)
    return (derived & last.notna() & (last < wrows["snapshot_date"] - pd.Timedelta(days=days))).astype(bool)


def attach_ciks(rows: pd.DataFrame, mapper: CikMapper, date_col: str = "snapshot_date") -> pd.DataFrame:
    """Add cik / cik_method to Wikipedia rows (cached per unique (ticker, name, cik_wiki, quarter))."""
    key = list(zip(rows["ticker_raw"], rows["name"], rows["cik_wiki"], rows[date_col].dt.to_period("Q")))
    cache: dict = {}
    ciks, methods = [], []
    dates = rows[date_col].to_list()
    for k, d in zip(key, dates):
        if k not in cache:
            cache[k] = mapper.resolve(k[0], k[1], d, k[2])
        c, m = cache[k]
        ciks.append(c)
        methods.append(m)
    out = rows.copy()
    out["cik"] = pd.array(ciks, dtype="Int64")
    out["cik_method"] = methods
    return out


def apply_cik_aliases(df: pd.DataFrame, col: str = "cik") -> pd.DataFrame:
    """Map successor registrants back to the long-history CIK (see CIK_ALIASES)."""
    if not CIK_ALIASES:
        df["cik_successor"] = pd.array([pd.NA] * len(df), dtype="Int64")
        return df
    new2old = {n: o for o, n, _ in CIK_ALIASES}
    old2new = {o: n for o, n, _ in CIK_ALIASES}
    c = df[col].astype("Int64")
    df["cik_successor"] = c.map(lambda x: old2new.get(int(x), pd.NA) if pd.notna(x) else pd.NA).astype("Int64")
    mapped = c.map(lambda x: new2old.get(int(x), x) if pd.notna(x) else x)
    df["cik_successor"] = df["cik_successor"].fillna(c.where(c.isin(list(new2old)))).astype("Int64")
    df[col] = mapped.astype("Int64")
    return df


def sp500_rows_from_fja(spells: pd.DataFrame, wiki_rows: pd.DataFrame, mapper: CikMapper) -> pd.DataFrame:
    """One row per (change date, ticker) from the fja spells, with the company valid at that date.

    ticker_raw / name are the time-correct values from the nearest Wikipedia row of the same company.
    """
    sp = spells.copy()
    dates = sorted(set(sp["start"]) | set(sp["end"].dropna()))
    parts = []
    for d in dates:
        m = sp[(sp["start"] <= d) & (sp["end"].isna() | (sp["end"] > d))]
        parts.append(m.assign(snapshot_date=d))
    r = pd.concat(parts, ignore_index=True)
    res = FjaResolver(wiki_rows, mapper)
    got = [res.resolve(t, d) for t, d in zip(r["ticker_fja"], r["snapshot_date"])]
    r["cik"] = pd.array([g[0] for g in got], dtype="Int64")
    r["cik_method"] = [g[1] for g in got]
    r["name_wiki"] = [g[2] for g in got]
    new2old = {n: o for o, n, _ in CIK_ALIASES}
    r["_cik_old"] = r["cik"].map(lambda x: new2old.get(int(x), int(x)) if pd.notna(x) else pd.NA).astype("Int64")
    r["index"] = "SP500"
    r["snapshot_date"] = r["snapshot_date"].astype("datetime64[ns]")
    # time-correct ticker / name: the Wikipedia row (any index) within 250 days that has the SAME ticker string, else
    # the nearest Wikipedia row of the same company (renamed tickers: fja says ANTM, Wikipedia WLP)
    w = wiki_rows[wiki_rows["cik"].notna()][["cik", "snapshot_date", "ticker_raw", "name"]].copy()
    w["cik"] = w["cik"].astype("int64")
    w = w.sort_values("snapshot_date")
    left = r[r["_cik_old"].notna()][["snapshot_date", "ticker_fja", "_cik_old"]].drop_duplicates().rename(columns={"_cik_old": "cik"})
    left["cik"] = left["cik"].astype("int64")
    left = left.sort_values("snapshot_date")
    tol = pd.Timedelta(days=250)
    w1 = w.rename(columns={"ticker_raw": "ticker_fja", "name": "name_same"})[["cik", "snapshot_date", "ticker_fja", "name_same"]]
    m1 = pd.merge_asof(left, w1, on="snapshot_date", by=["cik", "ticker_fja"], tolerance=tol, direction="nearest")
    w2 = w.rename(columns={"ticker_raw": "ticker_wiki", "name": "name_nearest"})[["cik", "snapshot_date", "ticker_wiki", "name_nearest"]]
    m2 = pd.merge_asof(left, w2, on="snapshot_date", by="cik", tolerance=tol, direction="nearest")
    m = m1.merge(m2[["snapshot_date", "ticker_fja", "cik", "ticker_wiki", "name_nearest"]],
                 on=["snapshot_date", "ticker_fja", "cik"], how="left")
    m["ticker_wiki"] = np.where(m["name_same"].notna(), m["ticker_fja"], m["ticker_wiki"])
    m["name_nearest"] = m["name_same"].where(m["name_same"].notna(), m["name_nearest"])
    r = r.merge(m[["snapshot_date", "ticker_fja", "ticker_wiki", "name_nearest"]]
                .drop_duplicates(["snapshot_date", "ticker_fja"]), on=["snapshot_date", "ticker_fja"], how="left")
    r["ticker_raw"] = r["ticker_wiki"].fillna(r["ticker_fja"])
    r["name"] = r["name_nearest"].fillna(r["name_wiki"])
    return r.drop(columns=["ticker_wiki", "name_nearest", "name_wiki", "_cik_old"])


_GICS_OUT_COLS = ["gics_sector", "gics_industry_group", "gics_industry", "gics_sub_industry", "sector_code",
                  "industry_group_code", "industry_code", "sub_industry_code", "gics_era", "gics_flag", "gics_level"]


def _level_name(r: dict) -> str | None:
    return {"sub": r["gics_sub_industry"], "industry": r["gics_industry"], "group": r["gics_industry_group"],
            "sector": r["gics_sector"]}.get(r["gics_level"])


def attach_gics(m: pd.DataFrame, timeline: pd.DataFrame, mapper: GicsMapper) -> pd.DataFrame:
    """Fill the GICS hierarchy of membership rows ``m``.

    m needs: cik (Int64), snapshot_date, own_sector, own_sub (raw labels of the row's own Wikipedia snapshot; null
    for the fja S&P 500 rows).  timeline: Wikipedia rows with a cik (cik, snapshot_date, gics_sector,
    gics_sub_industry).

    Every raw label is first resolved to a level (sub-industry / industry / industry group / sector) and canonical
    name; early revisions carry sector-only labels and many 2013-2020 revisions carry industry-level or non-GICS
    labels in the sub-industry column.  Because Wikipedia lagged GICS re-structurings by weeks to months, a label is
    "in-era" only if its name belongs to the structure valid at the row's date.  Source of the label:
      * ``snapshot``: the row's own label is a sub-industry of the era valid at the row's date;
      * ``era_prev`` / ``era_next``: own label is from the previous structure (lag) and was replaced by the nearest
        earlier / later in-era label of the same company;
      * ``asof_prev`` / ``asof_next`` (fja rows): nearest earlier / later Wikipedia sub-industry label of the same
        company (in-era preferred);
      * ``backfill_prev`` / ``backfill_next``: own label coarse or unusable (sector-only early pages, industry-level
        or non-GICS labels), sub-industry taken from another snapshot of the same company and mapped into the
        structure valid at the row's date.  ``*_next`` is classification look-ahead and is flagged;
      * ``coarse_industry`` / ``coarse_group`` / ``sector_only`` / ``none`` when nothing better exists.
    """
    m = m.copy().reset_index(drop=True)
    cache: dict = {}

    def lab(label, sector, date, level=None):
        k = (label, sector, gics_era_for(date), level)
        r = cache.get(k)
        if r is None:
            r = mapper.map_label(label, sector, date, force_level=level)
            cache[k] = r
        return r

    def sec_name(sector, date):
        k = ("sec", sector, gics_era_for(date))
        r = cache.get(k)
        if r is None:
            r = mapper.map_sector(sector, date)["gics_sector"] if isinstance(sector, str) else None
            cache[k] = r
        return r

    def resolve3(label, sector, date):
        """-> (level, canonical name, canonical sector, era the name was found in)."""
        l = label if isinstance(label, str) else None
        sct = sector if isinstance(sector, str) else None
        r = lab(l, sct, date) if l is not None else None
        sc = sec_name(sct, date)
        if r is not None and r["gics_level"] != "none":
            return r["gics_level"], _level_name(r), r["gics_sector"] or sc, r["gics_era"]
        if sc:
            return "sector", sc, sc, gics_era_for(date)
        return "none", None, None, None

    tl = timeline[timeline["cik"].notna()].copy()
    tl["cik"] = tl["cik"].astype("int64")
    res3 = [resolve3(l, sct, d) for l, sct, d in zip(tl["gics_sub_industry"], tl["gics_sector"], tl["snapshot_date"])]
    tl["t_level"] = [r[0] for r in res3]
    tl["t_name"] = [r[1] for r in res3]
    tl["t_sector"] = [r[2] for r in res3]
    tl["era"] = [r[3] for r in res3]
    tl["t_date"] = tl["snapshot_date"]
    tl = tl.sort_values("snapshot_date")
    tl_sub = tl[tl["t_level"] == "sub"][["cik", "snapshot_date", "t_date", "t_name", "era"]]
    tl_any = tl[tl["t_level"] != "none"][["cik", "snapshot_date", "t_date", "t_level", "t_name", "t_sector"]]

    n = len(m)
    dates = m["snapshot_date"].to_list()
    row_era = np.array([gics_era_for(d) for d in dates], dtype=object)
    own_level = np.array(["none"] * n, dtype=object)
    own_name = np.array([None] * n, dtype=object)
    own_era = np.array([None] * n, dtype=object)
    ctx_sector = np.array([None] * n, dtype=object)
    source = np.array([""] * n, dtype=object)
    labs, secs = m["own_sub"].to_list(), m["own_sector"].to_list()
    has_label = np.zeros(n, dtype=bool)
    for i in range(n):
        if not isinstance(labs[i], str) and not isinstance(secs[i], str):
            continue
        has_label[i] = True
        own_level[i], own_name[i], ctx_sector[i], own_era[i] = resolve3(labs[i], secs[i], dates[i])
        if own_level[i] == "sub" and own_era[i] == row_era[i]:
            source[i] = "snapshot"
    has_cik = m["cik"].notna().to_numpy()

    # sector / coarse context for rows without any own label (fja rows)
    need_ctx = np.where(~has_label & has_cik)[0]
    if len(need_ctx):
        left = m.loc[need_ctx, ["cik", "snapshot_date"]].copy()
        left["cik"] = left["cik"].astype("int64")
        left["_i"] = need_ctx
        left = left.sort_values("snapshot_date")
        got = np.zeros(n, dtype=bool)
        for direction in ("backward", "forward"):
            pend = left[~got[left["_i"].to_numpy()]]
            if pend.empty:
                break
            j = pd.merge_asof(pend, tl_any, on="snapshot_date", by="cik", direction=direction)
            for i, lv, nm, sc, td in zip(j["_i"], j["t_level"], j["t_name"], j["t_sector"], j["t_date"]):
                if pd.isna(td):
                    continue
                got[i] = True
                ctx_sector[i] = sc
                if lv in ("industry", "group", "sector"):
                    own_level[i], own_name[i] = lv, nm

    # candidate search for rows that need a (better) sub-industry label
    def search(idx, passes) -> dict:
        found: dict[int, tuple] = {}
        if len(idx) == 0 or tl_sub.empty:
            return found
        base = m.loc[idx, ["cik", "snapshot_date"]].copy()
        base["cik"] = base["cik"].astype("int64")
        base["_i"] = idx
        base["era"] = row_era[idx]
        base = base.sort_values("snapshot_date")
        for direction, same_era, tag in passes:
            pend = base[~base["_i"].isin(list(found))]
            if pend.empty:
                break
            if same_era:
                j = pd.merge_asof(pend, tl_sub, on="snapshot_date", by=["cik", "era"], direction=direction)
            else:
                j = pd.merge_asof(pend, tl_sub.drop(columns="era"), on="snapshot_date", by="cik", direction=direction)
            j = j[j["t_date"].notna()]
            for i, nm in zip(j["_i"], j["t_name"]):
                found[int(i)] = (tag, nm)
        return found

    fja_idx = np.where(~has_label & has_cik)[0]
    lag_idx = np.where(has_label & has_cik & (own_level == "sub") & (own_era != row_era))[0]
    coarse_idx = np.where(has_label & has_cik & (own_level != "sub"))[0]
    found: dict[int, tuple] = {}
    found.update(search(fja_idx, [("backward", True, "asof_prev"), ("forward", True, "asof_next"),
                                  ("backward", False, "asof_prev"), ("forward", False, "asof_next")]))
    found.update(search(lag_idx, [("backward", True, "era_prev"), ("forward", True, "era_next")]))
    found.update(search(coarse_idx, [("backward", True, "backfill_prev"), ("forward", True, "backfill_next"),
                                     ("backward", False, "backfill_prev"), ("forward", False, "backfill_next")]))

    out = {c: [None] * n for c in _GICS_OUT_COLS}
    for i in range(n):
        r = None
        if i in found:
            tag, nm = found[i]
            r = lab(nm, None, dates[i], "sub")
            if r["gics_level"] == "sub":
                source[i] = tag
            else:
                r = None
        if r is None:
            if own_level[i] == "none":
                r = GicsMapper._out(None, "no_gics")
                r["gics_level"] = "none"
                source[i] = "none"
            else:
                r = lab(own_name[i], ctx_sector[i], dates[i], own_level[i])
                if not source[i]:
                    source[i] = {"sub": "snapshot_lagged_era", "industry": "coarse_industry",
                                 "group": "coarse_group", "sector": "sector_only"}.get(own_level[i], "none")
        for c in _GICS_OUT_COLS:
            out[c][i] = r[c]
    for c in _GICS_OUT_COLS:
        m[c] = out[c]
    m["gics_source"] = source
    return m


# --------------------------------------------------------------------------------------
# yf_ticker assignment and security master
# --------------------------------------------------------------------------------------
SUCCESSION_WINDOW_DAYS = 400


def build_yf_map(mem: pd.DataFrame, companies: pd.DataFrame, mapper: CikMapper) -> pd.DataFrame:
    """One row per company key (cik, or unmapped ticker): yf_ticker, yf_status, is_listed_now, successor info.

    yf_ticker: the company's CURRENT SEC ticker if it is listed and still files (recovers FB -> META); else its last
    historical ticker, but only if no OTHER company owns that symbol today (ticker re-use would attach another
    company's prices): re-use is waved through only with explicit succession evidence (cik alias, or the current
    owner enters the index within ``SUCCESSION_WINDOW_DAYS`` of this company leaving and never overlaps it).
    """
    today = pd.Timestamp(dt.date.today())
    c = companies.set_index("cik")
    tt = current_ticker_table(companies)
    tt = tt[tt["exchange"].isin(LISTED_EXCHANGES) & ~tt["ticker"].map(is_noncommon_ticker)]
    cur_ticker = tt.sort_values("rank").drop_duplicates("cik").set_index("cik")["ticker"].map(to_yf).to_dict()
    old2new = {o: n for o, n, _ in CIK_ALIASES}
    mm = mem[mem["cik"].notna()].copy()
    mm["cik"] = mm["cik"].astype("int64")
    span = mm.groupby("cik")["snapshot_date"].agg(["min", "max"])
    latest = mem["snapshot_date"].max()
    last_tick = (mm.sort_values("snapshot_date").groupby("cik")["ticker_raw"].last().map(to_yf))
    rows = []
    for cik, g in span.iterrows():
        eff = old2new.get(cik, cik)           # ticker/filing status come from the successor registrant if aliased
        lp = c["last_periodic_filing_date"].get(eff, pd.NaT)
        files = pd.notna(lp) and lp >= today - pd.Timedelta(days=400)
        ct = cur_ticker.get(eff)
        # in today's index table => trading, even if the SEC ticker file lacks the company (LEG, WBS, OZK, ...)
        in_index_now = g["max"] >= latest - pd.Timedelta(days=45)
        listed = (bool(ct) and files) or in_index_now
        yf, status = None, ""
        if bool(ct) and files:
            yf, status = ct, "current_sec_ticker"
        else:
            h = last_tick.get(cik)
            owner = mapper.tick2cik_yf.get(h)
            if owner is None or owner == cik or owner == eff:
                yf, status = h, "historical_ticker"
            else:
                o_span = span.loc[owner] if owner in span.index else None
                if o_span is not None and o_span["min"] >= g["max"] - pd.Timedelta(days=100) \
                        and o_span["min"] <= g["max"] + pd.Timedelta(days=SUCCESSION_WINDOW_DAYS):
                    yf, status = h, "historical_ticker_successor"
                else:
                    yf, status = None, "blocked_ticker_reuse"
        rows.append({"cik": cik, "yf_ticker": yf, "yf_status": status, "is_listed_now": bool(listed),
                     "first_member": g["min"], "last_member": g["max"], "last_ticker_raw": last_tick.get(cik),
                     "cik_successor": old2new.get(cik)})
    out = pd.DataFrame(rows)
    out["cik"] = out["cik"].astype("Int64")
    return out


def resolve_merger_ticker_conflicts(mem: pd.DataFrame, window_days: int = 100) -> pd.DataFrame:
    """Row-level fix for a ticker handed from one S&P 500 member to another.

    ACE took the CB symbol from Chubb Corp in 2016 and Tyco International took JCI from Johnson Controls Inc: the
    SEC's current ticker for the surviving CIK would attach the OTHER company's Yahoo history to its pre-merger
    rows, and which series Yahoo keeps is not knowable from SEC data.  Detected as: CIK ``o`` holds the current
    symbol T; another S&P 500 CIK ``A`` used T until within ``window_days`` of the day ``o`` started using T, and the
    two were S&P 500 members at the same time for more than ``window_days`` before the hand-over.  ``o``'s rows
    from before the hand-over keep their own historical symbol (``merger_ticker_conflict``); ``A`` stays blocked.
    """
    mm = mem[mem["cik"].notna() & (mem["index"] == "SP500")]
    span = mm.groupby("cik")["snapshot_date"].agg(["min", "max"])
    mm = mm.assign(_t=mm["ticker_raw"].map(to_yf))
    first_t = mm.groupby(["cik", "_t"])["snapshot_date"].min()
    last_t = mm.groupby(["cik", "_t"])["snapshot_date"].max()
    users = mm.groupby("_t")["cik"].unique()
    cur = mem[mem["yf_status"] == "current_sec_ticker"].groupby("cik")["yf_ticker"].first()
    mem = mem.copy()
    flagged = []
    for cik, t in cur.items():
        if cik not in span.index or (cik, t) not in first_t.index:
            continue
        o_first = first_t[(cik, t)]
        for a in users.get(t, []):
            if a == cik or (a, t) not in last_t.index:
                continue
            handover = abs((last_t[(a, t)] - o_first).days) <= window_days
            overlap = (min(o_first, last_t[(a, t)]) - max(span.loc[cik, "min"], span.loc[a, "min"])).days
            if handover and overlap > window_days:
                flagged.append((cik, t, o_first))
                break
    for cik, t, o_first in flagged:
        rows = mem.index[(mem["cik"] == cik) & (mem["snapshot_date"] < o_first) & (mem["ticker_raw"].map(to_yf) != t)]
        mem.loc[rows, "yf_ticker"] = mem.loc[rows, "ticker_raw"].map(to_yf)
        mem.loc[rows, "yf_status"] = "merger_ticker_conflict"
    return mem


def finalize_yf_for_unmapped(mem: pd.DataFrame, mapper: CikMapper) -> pd.Series:
    """yf_ticker for rows without a CIK: raw ticker unless another company owns that symbol today."""
    yf = mem["ticker_raw"].map(to_yf)
    owned = yf.map(lambda t: mapper.tick2cik_yf.get(t) if t else None)
    return yf.where(owned.isna(), None), owned.notna()


# --------------------------------------------------------------------------------------
# Cross-checks
# --------------------------------------------------------------------------------------
def gapfill_spells(meta: pd.DataFrame, wrows: pd.DataFrame, sp500: pd.DataFrame, min_run: int = 2) -> pd.DataFrame:
    """Companies that Wikipedia lists in >= ``min_run`` consecutive quarter-end S&P 500 tables but fja omits.

    The fja file is missing a few real constituents in 2010-2016 (ACE and Tyco International, for example, because
    their later tickers collapse onto other lines).  Each such run becomes a synthetic spell
    [first quarter-end, last quarter-end + 1 day) marked ``wikipedia_gapfill``; single-quarter disagreements are
    treated as timing noise and ignored.
    """
    today = pd.Timestamp(dt.date.today())
    qs = meta[(meta["index"] == "SP500") & (meta["status"] == "ok") & (meta["snapshot_date"] < today)]["snapshot_date"]
    qs = sorted(qs)
    snaps = sp500["snapshot_date"].drop_duplicates().sort_values()
    miss: dict[int, list[int]] = {}
    tick: dict[tuple[int, int], str] = {}
    for k, q in enumerate(qs):
        w = wrows[(wrows["index"] == "SP500") & (wrows["snapshot_date"] == q) & wrows["cik"].notna()]
        s = snaps[snaps <= q]
        if w.empty or s.empty:
            continue
        f = sp500[sp500["snapshot_date"] == s.iloc[-1]]
        have = set(f["cik"].dropna().astype("int64"))
        have_t = set(f["ticker_raw"]) | set(f["ticker_fja"] if "ticker_fja" in f else [])
        for c, t in zip(w["cik"].astype("int64"), w["ticker_raw"]):
            # same ticker present in fja => an identity (CIK) disagreement, not a missing constituent
            if c not in have and t not in have_t:
                miss.setdefault(int(c), []).append(k)
                tick[(int(c), k)] = t
    rows = []
    for c, ks in miss.items():
        run = [ks[0]]
        for k in ks[1:] + [None]:
            if k is not None and k == run[-1] + 1:
                run.append(k)
                continue
            if len(run) >= min_run:
                rows.append((tick[(c, run[-1])], qs[run[0]], qs[run[-1]] + pd.Timedelta(days=1), "wikipedia_gapfill"))
            run = [k] if k is not None else []
    out = pd.DataFrame(rows, columns=["ticker_fja", "start", "end", "source"])
    for c in ["start", "end"]:
        out[c] = out[c].astype("datetime64[ns]")
    return out


def crosscheck_sp500(meta: pd.DataFrame, wrows: pd.DataFrame, sp500: pd.DataFrame) -> pd.DataFrame:
    """Agreement between Wikipedia quarter-end S&P 500 tables and the fja exact membership (company level)."""
    def keyset(df: pd.DataFrame) -> set:
        return {(f"c{int(c)}" if pd.notna(c) else f"t{t}") for c, t in zip(df["cik"], df["ticker_raw"])}
    snaps = sp500["snapshot_date"].drop_duplicates().sort_values()
    rows = []
    wq = meta[(meta["index"] == "SP500") & (meta["status"] == "ok")]["snapshot_date"]
    for q in wq:
        w = wrows[(wrows["index"] == "SP500") & (wrows["snapshot_date"] == q)]
        s = snaps[snaps <= q]
        if w.empty or s.empty:
            continue
        f = sp500[sp500["snapshot_date"] == s.iloc[-1]]
        kw, kf = keyset(w), keyset(f)
        rows.append({"snapshot_date": q, "n_wiki": len(kw), "n_fja": len(kf), "both": len(kw & kf),
                     "wiki_only": len(kw - kf), "fja_only": len(kf - kw),
                     "jaccard": len(kw & kf) / max(1, len(kw | kf))})
    return pd.DataFrame(rows)


# --------------------------------------------------------------------------------------
# build_all
# --------------------------------------------------------------------------------------
def _finalize_types(mem: pd.DataFrame) -> pd.DataFrame:
    mem = mem.copy()
    mem["snapshot_date"] = mem["snapshot_date"].astype("datetime64[ns]")
    mem["cik"] = mem["cik"].astype("Int64")
    mem["cik_successor"] = mem["cik_successor"].astype("Int64")
    for c in ["sector_code", "industry_group_code", "industry_code", "sub_industry_code"]:
        mem[c] = mem[c].astype("object").where(mem[c].notna(), None)
    return mem


def build_all(force: bool = False) -> dict:
    """Build every artifact under cache/universe/ and the audit report. Idempotent (cached Wikipedia responses)."""
    needed = [MEMBERSHIP_PATH, GICS_PATH, MASTER_PATH, US_ALL_PATH, PRICE_TICKERS_PATH, SNAPSHOT_META_PATH, REPORT_PATH]
    if not force and all(p.exists() for p in needed):
        log.info("universe artifacts exist; use force=True to rebuild")
        return {}
    today = pd.Timestamp(dt.date.today())
    client = WikiClient()
    fetch_wiki(client)
    download_fja()
    companies = load_sec_companies()

    gics = build_gics()
    _atomic_write_parquet(gics, GICS_PATH)
    gm = GicsMapper(gics)
    mapper = CikMapper(companies)

    us = build_us_all(companies)
    _atomic_write_parquet(us, US_ALL_PATH)
    write_early_price_tickers(client)

    # ---- Wikipedia snapshots ----
    meta, wrows = collect_snapshots(client)
    wrows = attach_ciks(wrows, mapper)
    wrows = apply_cik_aliases(wrows)
    wrows["stale_listing"] = flag_stale_listings(wrows, mapper)
    cur500 = wrows[(wrows["index"] == "SP500") & (wrows["snapshot_date"] == today)]
    cur_date = pd.Timestamp(meta[(meta["index"] == "SP500") & (meta["snapshot_date"] == today)]["rev_ts"].iloc[0]).normalize()

    # ---- S&P 500 exact membership ----
    h = load_fja_history()
    h2, patch_info = patch_fja_with_current(h, cur500, cur_date)
    spells = fja_spells(h2)
    sp500 = apply_cik_aliases(sp500_rows_from_fja(spells, wrows, mapper))
    cross_raw = crosscheck_sp500(meta, wrows, sp500)
    gaps = gapfill_spells(meta, wrows, sp500)
    if len(gaps):
        spells = pd.concat([spells, gaps], ignore_index=True)
        sp500 = apply_cik_aliases(sp500_rows_from_fja(spells, wrows, mapper))
    sp500 = sp500.rename(columns={"ticker_fja": "ticker_src"})
    sp500["snapshot_quality"] = "fja_exact"
    sp500["revid"] = pd.NA
    sp500["rev_ts"] = pd.NaT
    sp500["own_sector"] = None
    sp500["own_sub"] = None
    cross = crosscheck_sp500(meta, wrows, sp500)

    # ---- S&P 400 / 600 quarterly snapshots ----
    w = wrows[wrows["index"].isin(["SP400", "SP600"])].copy()
    w["source"] = "wikipedia"
    w["ticker_src"] = w["ticker_raw"]
    w["own_sector"] = w["gics_sector"]
    w["own_sub"] = w["gics_sub_industry"]
    sp500["stale_listing"] = False
    keep = ["snapshot_date", "index", "ticker_raw", "name", "cik", "cik_method", "cik_successor", "source",
            "ticker_src", "snapshot_quality", "revid", "rev_ts", "own_sector", "own_sub", "stale_listing"]
    # the fja file sometimes lists one company under two tickers (KORS and CPRI, UA and UAA): one row per ticker_raw
    sp500 = sp500.drop_duplicates(["snapshot_date", "ticker_raw", "cik"])
    mem = pd.concat([sp500[keep], w[keep]], ignore_index=True)
    mem["cik"] = mem["cik"].astype("Int64")

    # ---- GICS ----
    timeline = wrows[wrows["snapshot_quality"].isin(["ok", "derived_sp1000_minus_sp400"])][["cik", "snapshot_date", "gics_sector", "gics_sub_industry"]]
    mem = attach_gics(mem, timeline, gm)
    mem = mem.drop(columns=["own_sector", "own_sub"])

    # ---- Yahoo tickers / security master ----
    ymap = build_yf_map(mem, companies, mapper)
    mem = mem.merge(ymap[["cik", "yf_ticker", "yf_status"]], on="cik", how="left")
    nocik = mem["cik"].isna()
    if nocik.any():
        yf_nc, owned = finalize_yf_for_unmapped(mem[nocik], mapper)
        mem.loc[nocik, "yf_ticker"] = yf_nc.values
        mem.loc[nocik, "yf_status"] = np.where(owned.values, "blocked_ticker_reuse_nocik", "raw_ticker_nocik")
    mem = resolve_merger_ticker_conflicts(mem)
    mem = _finalize_types(mem)
    col_order = ["snapshot_date", "index", "ticker_raw", "yf_ticker", "cik", "name", "gics_sector",
                 "gics_industry_group", "gics_industry", "gics_sub_industry", "sub_industry_code", "industry_code",
                 "industry_group_code", "sector_code", "source", "ticker_src", "cik_method", "cik_successor",
                 "gics_source", "gics_flag", "gics_era", "snapshot_quality", "stale_listing", "yf_status", "revid", "rev_ts"]
    mem = mem[col_order].sort_values(["index", "snapshot_date", "ticker_raw"]).reset_index(drop=True)
    mem["revid"] = mem["revid"].astype("Int64")
    _atomic_write_parquet(mem, MEMBERSHIP_PATH)

    master = build_security_master(mem, ymap, us, companies)
    _atomic_write_parquet(master, MASTER_PATH)
    meta["cik_rate"] = meta.apply(lambda r: _cik_rate(wrows, r), axis=1)
    sf = wrows.groupby(["index", "snapshot_date"])["stale_listing"].mean().rename("stale_frac").reset_index()
    meta = meta.merge(sf, on=["index", "snapshot_date"], how="left")
    _atomic_write_parquet(meta, SNAPSHOT_META_PATH)
    pd.DataFrame(CIK_ALIASES, columns=["old_cik", "new_cik", "note"]).to_csv(UNIV_DIR / "cik_aliases.csv", index=False)

    tickers = set(mem["yf_ticker"].dropna()) | set(us["yf_ticker"]) | set(BENCHMARKS)
    write_price_tickers(tickers)
    ctx = {"meta": meta, "wrows": wrows, "mem": mem, "master": master, "cross": cross, "cross_raw": cross_raw,
           "gaps": gaps, "patch": patch_info,
           "spells": spells, "us": us, "gics": gics, "companies": companies}
    try:
        write_report(ctx)
    except Exception:       # the report must never block the data products
        log.exception("report generation failed")
    return ctx


def _cik_rate(wrows: pd.DataFrame, r) -> float:
    w = wrows[(wrows["index"] == r["index"]) & (wrows["snapshot_date"] == r["snapshot_date"])]
    return float(w["cik"].notna().mean()) if len(w) else np.nan


def build_security_master(mem: pd.DataFrame, ymap: pd.DataFrame, us: pd.DataFrame, companies: pd.DataFrame) -> pd.DataFrame:
    c = companies.set_index("cik")
    tt = current_ticker_table(companies)
    tt = tt.sort_values("rank").drop_duplicates("cik").set_index("cik")
    latest_name = (mem[mem["cik"].notna()].sort_values("snapshot_date").groupby("cik")["name"].last())
    rows = []
    for r in ymap.itertuples(index=False):
        cik = int(r.cik)
        eff = int(r.cik_successor) if pd.notna(r.cik_successor) else cik
        nm = c["name"].get(eff) if eff in c.index else (c["name"].get(cik) if cik in c.index else None)
        rows.append({"cik": cik, "yf_ticker": r.yf_ticker, "name": nm if isinstance(nm, str) else latest_name.get(cik),
                     "sic": c["sic"].get(eff) if eff in c.index else np.nan,
                     "exchange": tt["exchange"].get(eff) if r.is_listed_now else None,
                     "is_listed_now": bool(r.is_listed_now), "ever_sp1500": True, "yf_status": r.yf_status,
                     "first_index_date": r.first_member, "last_index_date": r.last_member,
                     "cik_successor": r.cik_successor})
    m1 = pd.DataFrame(rows)
    # members without a CIK (keyed by their raw ticker)
    nc = mem[mem["cik"].isna()].groupby("ticker_raw").agg(name=("name", "last"), yf_ticker=("yf_ticker", "last"),
                                                          yf_status=("yf_status", "last"),
                                                          first_index_date=("snapshot_date", "min"),
                                                          last_index_date=("snapshot_date", "max")).reset_index()
    m2 = pd.DataFrame({"cik": pd.array([pd.NA] * len(nc), dtype="Int64"), "yf_ticker": nc["yf_ticker"],
                       "name": nc["name"], "sic": np.nan, "exchange": None, "is_listed_now": False,
                       "ever_sp1500": True, "yf_status": nc["yf_status"], "first_index_date": nc["first_index_date"],
                       "last_index_date": nc["last_index_date"], "cik_successor": pd.array([pd.NA] * len(nc), dtype="Int64")})
    # US_ALL companies that never were in the S&P 1500
    rest = us[~us["cik"].isin(ymap["cik"].astype("int64"))]
    m3 = pd.DataFrame({"cik": rest["cik"].astype("Int64"), "yf_ticker": rest["yf_ticker"], "name": rest["name"],
                       "sic": rest["sic"].astype(float), "exchange": rest["exchange"], "is_listed_now": True,
                       "ever_sp1500": False, "yf_status": "current_sec_ticker", "first_index_date": pd.NaT,
                       "last_index_date": pd.NaT, "cik_successor": pd.array([pd.NA] * len(rest), dtype="Int64")})
    master = pd.concat([m1, m2, m3], ignore_index=True)
    master["cik"] = master["cik"].astype("Int64")
    master["sic"] = pd.to_numeric(master["sic"], errors="coerce").astype("Int64")
    master["cik_successor"] = master["cik_successor"].astype("Int64")
    master["first_price_date"] = pd.Series(pd.NaT, index=master.index, dtype="datetime64[ns]")
    master["last_price_date"] = pd.Series(pd.NaT, index=master.index, dtype="datetime64[ns]")
    for c_ in ["first_index_date", "last_index_date"]:
        master[c_] = master[c_].astype("datetime64[ns]")
    dup = master["yf_ticker"].notna() & master.duplicated("yf_ticker", keep=False)
    master["yf_shared"] = dup
    return master[["cik", "yf_ticker", "name", "sic", "exchange", "is_listed_now", "ever_sp1500", "first_price_date",
                   "last_price_date", "yf_status", "yf_shared", "first_index_date", "last_index_date",
                   "cik_successor"]]


# --------------------------------------------------------------------------------------
# Public loaders / point-in-time API
# --------------------------------------------------------------------------------------
_CACHE: dict = {}


def _load(path: Path):
    key = (str(path), path.stat().st_mtime_ns)
    if key not in _CACHE:
        for k in [k for k in _CACHE if k[0] == str(path)]:
            del _CACHE[k]
        _CACHE[key] = pd.read_parquet(path)
    return _CACHE[key]


def load_membership() -> pd.DataFrame:
    """cache/universe/membership.parquet (snapshot rows of all three indexes)."""
    return _load(MEMBERSHIP_PATH)


def load_gics() -> pd.DataFrame:
    return _load(GICS_PATH)


def load_security_master() -> pd.DataFrame:
    return _load(MASTER_PATH)


def us_all() -> pd.DataFrame:
    """Broad current US universe: cik, yf_ticker, name, sic, exchange (+ alt_tickers)."""
    return _load(US_ALL_PATH)


MEMBERS_COLS = ["cik", "yf_ticker", "ticker_raw", "name", "index", "gics_sector", "gics_industry_group",
                "gics_industry", "gics_sub_industry", "sector_code", "industry_group_code", "industry_code",
                "sub_industry_code"]


def members(date, indexes=("SP500", "SP400", "SP600"), dedupe: bool = True, drop_stale: bool = True) -> pd.DataFrame:
    """Point-in-time index members as known at ``date`` (latest snapshot with snapshot_date <= date, per index).

    SP500 comes from the exact change-date list (fja05680 + Wikipedia tail); SP400/SP600 from quarter-end Wikipedia
    revisions, so they can lag a mid-quarter change by up to one quarter but never look ahead.
    dedupe=True keeps one row per company (dual-class lines such as GOOG/GOOGL collapse; a stock listed in two
    indexes keeps its higher tier). drop_stale=True removes rows of the 2018-2020 derived S&P 600 lists that belong
    to companies which had stopped filing (the list is then incomplete, see the report). Rows whose ``yf_ticker``
    is null have no safe Yahoo symbol (ticker re-use).
    Columns: MEMBERS_COLS + extra audit columns (snapshot_date, gics_source, gics_flag, cik_method, yf_status).
    """
    d = pd.Timestamp(date).normalize()
    mem = load_membership()
    parts = []
    for ix in indexes:
        m = mem[mem["index"] == ix]
        snaps = m["snapshot_date"]
        ok = snaps[snaps <= d]
        if ok.empty:
            continue
        parts.append(m[m["snapshot_date"] == ok.max()])
    cols = MEMBERS_COLS + ["snapshot_date", "gics_source", "gics_flag", "cik_method", "yf_status", "snapshot_quality"]
    if not parts:
        return pd.DataFrame(columns=cols)
    out = pd.concat(parts, ignore_index=True)
    if drop_stale:
        out = out[~out["stale_listing"].astype(bool)]
    if dedupe:
        out["_rank"] = out["index"].map(INDEX_RANK)
        yb = out["ticker_raw"].map(to_yf)
        out["_prim"] = (yb != out["yf_ticker"]).astype(int)
        out = out.sort_values(["_rank", "_prim", "ticker_raw"])
        has = out["cik"].notna()
        out = pd.concat([out[has].drop_duplicates("cik"), out[~has].drop_duplicates("ticker_raw")])
        out = out.sort_values(["_rank", "ticker_raw"]).drop(columns=["_rank", "_prim"])
    return out[cols].reset_index(drop=True)


# --------------------------------------------------------------------------------------
# Audit report
# --------------------------------------------------------------------------------------
def _md_table(df: pd.DataFrame, floatfmt: str = "{:.3f}") -> str:
    if df.empty:
        return "_(none)_\n"
    cols = list(df.columns)
    lines = ["| " + " | ".join(str(c) for c in cols) + " |", "|" + "|".join(["---"] * len(cols)) + "|"]
    for r in df.itertuples(index=False):
        cells = []
        for v in r:
            if isinstance(v, (float, np.floating)):
                cells.append("" if pd.isna(v) else floatfmt.format(v))
            elif isinstance(v, pd.Timestamp):
                cells.append("" if pd.isna(v) else str(v.date()))
            else:
                cells.append("" if v is None or (not isinstance(v, str) and pd.isna(v)) else str(v))
        lines.append("| " + " | ".join(cells) + " |")
    return "\n".join(lines) + "\n"


def _members_at(mem: pd.DataFrame, d: pd.Timestamp, indexes=INDEXES) -> pd.DataFrame:
    parts = []
    for ix in indexes:
        m = mem[mem["index"] == ix]
        ok = m["snapshot_date"][m["snapshot_date"] <= d]
        if len(ok):
            parts.append(m[m["snapshot_date"] == ok.max()])
    return pd.concat(parts, ignore_index=True) if parts else mem.iloc[0:0]


def write_report(ctx: dict, path: Path = REPORT_PATH) -> Path:
    meta, wrows, mem, master = ctx["meta"], ctx["wrows"], ctx["mem"], ctx["master"]
    cross, patch, us, gics = ctx["cross"], ctx["patch"], ctx["us"], ctx["gics"]
    today = pd.Timestamp(dt.date.today())
    L: list[str] = []
    A = L.append
    A("# Point-in-time S&P 1500 universe: build report\n")
    A(f"Generated {today.date()} by `quant/data/universe.py` (`build_all`). Products in `cache/universe/`: "
      "`membership.parquet`, `gics.parquet`, `security_master.parquet`, `us_all.parquet`, `price_tickers.txt`, "
      "`snapshots_meta.parquet`, `cik_aliases.csv`; raw Wikipedia/GitHub responses in `wiki/`, `fja05680/`.\n")

    # ---- headline numbers
    qd = [q for q in quarter_ends() if q >= pd.Timestamp("2010-01-01")]
    sizes = []
    for q in qd:
        m = _members_at(mem, q)
        sizes.append({"date": q, **{ix: int((m["index"] == ix).sum()) for ix in INDEXES}, "total_unique_cik": int(m["cik"].nunique())})
    sizes = pd.DataFrame(sizes)
    ever = mem[mem["snapshot_date"] >= pd.Timestamp("2010-01-01")]
    key = ever["cik"].astype("object").where(ever["cik"].notna(), "t:" + ever["ticker_raw"].astype(str))
    n_ever = key.nunique()
    mk = master[master["ever_sp1500"]]
    n_nolist = int((~mk["is_listed_now"]).sum())
    A("## 1. Headline\n")
    A(f"- Distinct companies that were in the S&P 500, 400 or 600 at any snapshot since 2010: **{n_ever}** "
      f"({int(ever['cik'].nunique())} distinct CIKs + {int(ever['cik'].isna().groupby(ever['ticker_raw']).any().sum())} "
      "unmapped tickers).")
    A(f"- Of the {len(mk)} security-master rows with `ever_sp1500`, **{n_nolist} ({n_nolist / max(1, len(mk)):.1%}) are no longer "
      "listed/filing today** (survivorship exposure: their prices are mostly unavailable on Yahoo, see section 7).")
    A(f"- Wikipedia revisions used: {int(meta['usable'].sum())} usable of {len(meta)} (index, quarter) snapshots; "
      f"US_ALL: {len(us)} companies; `price_tickers.txt`: {len(PRICE_TICKERS_PATH.read_text().split())} tickers.\n")
    A("Index sizes at quarter-ends (`members(date, dedupe=False)`):\n")
    A(_md_table(sizes.iloc[::2]))

    # ---- coverage / gaps
    A("## 2. Coverage by index and known gaps\n")
    cov = []
    for ix in INDEXES:
        m = meta[meta["index"] == ix]
        good = m[m["status"].isin(["ok", "derived_sp1000_minus_sp400"])]
        cov.append({"index": ix, "snapshots": len(m), "ok": int((m["status"] == "ok").sum()),
                    "derived": int((m["status"] == "derived_sp1000_minus_sp400").sum()),
                    "fallback": int(m["status"].str.startswith("fallback").sum()),
                    "missing": int((m["status"] == "missing").sum()),
                    "first_real_snapshot": good["snapshot_date"].min() if len(good) else pd.NaT})
    A(_md_table(pd.DataFrame(cov)))
    A("- **S&P 500**: exact daily membership (fja05680 file, tail patched from the live Wikipedia table: "
      f"{', '.join(patch.get('adds', []))} added and {', '.join(patch.get('removes', []))} removed after "
      f"{pd.Timestamp(patch.get('fja_last')).date() if patch.get('fja_last') is not None else 'n/a'}; removal dates are "
      "paired with add dates because they are not published).")
    A("- **S&P 400**: the Wikipedia page only starts in late 2010; quarters without a usable revision fall back as shown "
      "in the snapshot table (`status`).")
    A("- **S&P 600**: the page title held the combined S&P 1000 (~995 rows) until 2020-12; those snapshots are split "
      "as S&P 1000 minus the contemporaneous S&P 400 list. That list was poorly maintained after 2018: the share of rows "
      "belonging to companies that had already stopped filing grows from 0% (2018-09) to about 10% (2020; the `defunct` column; "
      "dropped by `drop_stale`, flagged `stale_listing`), so the **S&P 600 is understated (544-590 names instead of 600) from 2019 "
      "to 2020-12** and misses additions the page never recorded. "
      "There is **no Wikipedia revision before 2018**, so "
      "`members(date)` returns no S&P 600 rows before the first real snapshot above (the S&P 1500 is effectively the "
      "S&P 900 before that date).")
    A("- Sub-industry labels: Wikipedia's S&P 500 table lists only the sector until 2012-12 (and some S&P 400 rows lack "
      "them 2013-12..2015-03); missing sub-industries are back-filled from the nearest other snapshot of the same "
      "company and flagged in `gics_source` (`backfill_prev` / `backfill_next` = classification look-ahead).")
    A("- S&P 400/600 membership is quarter-end granular: a mid-quarter addition appears at the next quarter-end "
      "snapshot (never early); `stale_days` in the snapshot table shows how old each revision was.\n")

    # ---- snapshot table
    A("## 3. Snapshot table\n")
    A("`rows` = constituent rows parsed, `GICS` = share with a sub-industry label, `CIK` = share mapped to an SEC CIK, "
      "`stale` = days between the quarter-end and the revision used, `defunct` = share of derived S&P 600 rows whose company had stopped filing (excluded by `members(drop_stale=True)`).\n")
    for ix in INDEXES:
        m = meta[meta["index"] == ix].copy()
        m["snapshot"] = m["snapshot_date"].dt.date.astype(str)
        t = m[["snapshot", "revid", "rev_ts", "n_rows", "gics_cov", "cik_rate", "stale_days", "stale_frac", "status"]].rename(
            columns={"rev_ts": "revision", "n_rows": "rows", "gics_cov": "GICS", "cik_rate": "CIK", "stale_days": "stale",
                     "stale_frac": "defunct"})
        t["revision"] = pd.to_datetime(t["revision"]).dt.date.astype(str)
        t["stale"] = t["stale"].round(0)
        t["revid"] = t["revid"].astype("Int64").astype(str)
        A(f"### {ix}\n")
        A(_md_table(t, "{:.2f}"))

    # ---- SP500 cross-check
    A("## 4. S&P 500: Wikipedia quarter-end tables vs fja05680 exact membership\n")
    if len(cross):
        raw = ctx.get("cross_raw")
        if raw is not None and len(raw):
            A(f"Before the gap-fill below the mean Jaccard was {raw['jaccard'].mean():.3f} (min {raw['jaccard'].min():.3f}).\n")
        gaps = ctx.get("gaps")
        if gaps is not None and len(gaps):
            g2 = gaps.merge(wrows[["ticker_raw", "name"]].drop_duplicates("ticker_raw"), left_on="ticker_fja",
                            right_on="ticker_raw", how="left")
            A(f"fja omits {len(gaps)} S&P 500 runs that Wikipedia lists in >= 2 consecutive quarter-end tables; they are added as "
              "`source = wikipedia_gapfill` rows for the span shown (quarter-end to quarter-end):\n")
            A(_md_table(g2[["ticker_fja", "name", "start", "end"]].rename(columns={"ticker_fja": "ticker"})))
        c = cross.copy()
        c["year"] = c["snapshot_date"].dt.year
        by = c.groupby("year").agg(n=("jaccard", "size"), mean_jaccard=("jaccard", "mean"),
                                   mean_wiki_only=("wiki_only", "mean"), mean_fja_only=("fja_only", "mean")).reset_index()
        A(f"Company-level (CIK) Jaccard agreement, mean over {len(c)} quarter-ends: **{c['jaccard'].mean():.3f}** "
          f"(min {c['jaccard'].min():.3f}, median {c['jaccard'].median():.3f}). Differences are timing "
          "(Wikipedia lags changes), unresolved identities in the early years, and fja data gaps "
          "(for example the ACE and Tyco lines are missing from fja before 2016).\n")
        A(_md_table(by))
        A("Worst quarters:\n")
        A(_md_table(c.nsmallest(6, "jaccard")[["snapshot_date", "n_wiki", "n_fja", "both", "wiki_only", "fja_only", "jaccard"]]))

    # ---- CIK mapping
    A("## 5. Ticker -> CIK mapping\n")
    rates = []
    for y in range(2010, today.year + 1):
        row = {"year": y}
        tot_n = tot_k = 0
        for ix in INDEXES:
            ns, ks = 0, 0
            for q in [pd.Timestamp(f"{y}-03-31"), pd.Timestamp(f"{y}-06-30"), pd.Timestamp(f"{y}-09-30"), pd.Timestamp(f"{y}-12-31")]:
                q = min(q, today)
                m = _members_at(mem, q, (ix,))
                ns += len(m)
                ks += int(m["cik"].notna().sum())
            row[ix] = ks / ns if ns else np.nan
            tot_n += ns
            tot_k += ks
        row["all"] = tot_k / tot_n if tot_n else np.nan
        rates.append(row)
    A("Share of member rows with an SEC CIK (quarter-end snapshots, `dedupe=False`):\n")
    A(_md_table(pd.DataFrame(rates)))
    A("Method counts (all membership rows):\n")
    A(_md_table(mem.groupby("cik_method").size().sort_values(ascending=False).rename("rows").reset_index()))
    un = mem[mem["cik"].isna()].groupby(["ticker_raw", "index"]).agg(
        name=("name", "last"), rows=("snapshot_date", "size"), first=("snapshot_date", "min"), last=("snapshot_date", "max")
    ).reset_index().sort_values("rows", ascending=False)
    A(f"### Unmapped members ({len(un)} ticker/index pairs without a CIK; mostly pre-XBRL acquisitions and bank filers outside EDGAR)\n")
    A(_md_table(un.head(60)))
    A("### Manual CIK overrides in use\n")
    A(_md_table(pd.DataFrame(CIK_OVERRIDES, columns=["ticker", "from", "to", "cik", "note"])))
    A("### CIK aliases (successor registrants mapped back to the long-history CIK)\n")
    A(_md_table(pd.DataFrame(CIK_ALIASES, columns=["old_cik", "new_cik", "note"])))

    # ---- GICS
    A("## 6. GICS\n")
    g = gics.groupby("era").agg(sub_industries=("sub_industry", "size"), industries=("industry", "nunique"),
                                groups=("industry_group", "nunique"), sectors=("sector", "nunique"),
                                valid_from=("valid_from", "first"), valid_to=("valid_to", "first")).reset_index()
    A(_md_table(g))
    unm = wrows[wrows["gics_sub_industry"].notna()].copy()
    gm = GicsMapper(gics)
    seen = unm.assign(era=unm["snapshot_date"].map(gics_era_for)).drop_duplicates(["gics_sub_industry", "gics_sector", "era"])
    res = [gm.map_label(r.gics_sub_industry, r.gics_sector, r.snapshot_date) for r in seen.itertuples()]
    seen = seen.assign(level=[r["gics_level"] for r in res], flag=[r["gics_flag"] for r in res])
    lv = seen.groupby("level").size()
    bad = sorted({(r.gics_sub_industry, r.era) for r in seen.itertuples() if r.flag == "unmapped"})
    A(f"Distinct (label, sector, era) combinations found in the Wikipedia 'GICS Sub-Industry' column: {len(seen)}. Resolved as "
      f"sub-industry: {int(lv.get('sub', 0))}, industry: {int(lv.get('industry', 0))}, industry group: {int(lv.get('group', 0))}, "
      f"sector: {int(lv.get('sector', 0))}, dropped as non-GICS junk: {int((seen['flag'] == 'bad_label').sum())}; "
      f"**unmapped: {len(bad)}** {bad if bad else ''}\n")
    A("The 2013-2020 revisions mix sub-industry names with industry / industry-group names, typos and non-GICS phrases "
      "(for example `Banks`, `REITs`, `Health Care Equipment & Services`, `Broadcasting & Cable TV`, `Life Sciences Tolls & "
      "Services`); `GICS_LABEL_ALIASES` in the module lists every alias applied. Such rows are resolved at their own level and the "
      "sub-industry is back-filled from the nearest other snapshot of the same company (see `gics_source`). Wikipedia's "
      "sub-industry labels also contain editor errors that cannot be detected (e.g. Visa/Mastercard are `Internet Software & "
      "Services` from 2013 to 2019), so the sector level is more reliable than the sub-industry level before 2019.\n")
    fl = mem.assign(year=mem["snapshot_date"].dt.year).groupby(["year", "gics_source"]).size().unstack(fill_value=0)
    A("Source of the GICS label by membership-row year (rows):\n")
    A(_md_table(fl.reset_index()))
    flg = mem["gics_flag"].fillna("").replace("", "exact (valid era)").value_counts().rename("rows").reset_index()
    A("Mapping flags (`era_fallback:*` = the label only exists in another era, typically Wikipedia lagging a GICS "
      "change; `sector_mismatch` = mapped sector differs from the snapshot's sector column):\n")
    A(_md_table(flg))

    # ---- yahoo
    A("## 7. Yahoo tickers and survivorship exposure\n")
    A(_md_table(mem.groupby("yf_status").size().sort_values(ascending=False).rename("rows").reset_index()))
    blk = master[master["yf_status"].fillna("").str.startswith("blocked")]
    A(f"Company keys with a **blocked** (re-used) symbol: {len(blk)}; their `yf_ticker` is null so no wrong prices are attached. "
      "Examples:\n")
    A(_md_table(blk[["cik", "name", "first_index_date", "last_index_date"]].head(25)))
    rows = []
    for y in range(2010, today.year + 1):
        q = min(pd.Timestamp(f"{y}-12-31"), today)
        m = _members_at(mem, q)
        m = m.merge(master.dropna(subset=["cik"])[["cik", "is_listed_now"]], on="cik", how="left")
        rows.append({"year_end": q.date(), "members": len(m),
                     "not_listed_today": float((~m["is_listed_now"].fillna(False).astype(bool)).mean()),
                     "yf_ticker_null": float(m["yf_ticker"].isna().mean())})
    A("Share of each year-end S&P 1500 that is no longer listed today / has no safe Yahoo symbol:\n")
    A(_md_table(pd.DataFrame(rows)))

    # ---- US_ALL
    shared = master[master["yf_shared"]]
    A(f"Symbols claimed by more than one CIK in `security_master` (`yf_shared`): {int(shared['yf_ticker'].nunique())} symbols / {len(shared)} "
      "keys. Most are sequential tenants of a re-used symbol or successor registrants; the price loader must check that the "
      "Yahoo series overlaps the membership window of the key it is attached to.\n")
    mc = mem[mem["yf_status"] == "merger_ticker_conflict"]
    if len(mc):
        A("Rows where a symbol moved between two simultaneous S&P 500 members (the pre-merger rows keep their own historical "
          "symbol instead of the surviving company's current one, because Yahoo's pre-merger history may belong to the other "
          "party):\n")
        A(_md_table(mc.groupby(["ticker_raw", "name", "yf_ticker"]).agg(rows=("cik", "size"), first=("snapshot_date", "min"),
                                                                       last=("snapshot_date", "max")).reset_index()))
    A("## 8. US_ALL and price ticker list\n")
    A(f"US_ALL: {len(us)} operating companies on NYSE/Nasdaq (SEC lists NYSE American issuers under 'NYSE') with at least "
      "one 10-K, a periodic filing in the last 2 years, no warrant/unit/right/preferred line, no blank-check/commodity-trust "
      "SIC. Exchange counts:\n")
    A(_md_table(us.groupby("exchange").size().rename("n").reset_index()))
    A("\n`price_tickers.txt` = every non-null `yf_ticker` in `membership.parquet` + US_ALL + `settings.BENCHMARKS`.\n")
    A("## 9. Known gaps and caveats\n")
    A("- **S&P 600 before 2018-09 is not available** (the Wikipedia page was created 2018-08; no free point-in-time source "
      "was found). A possible fix is the quarterly holdings of the iShares S&P SmallCap 600 fund (IJR) in its N-Q / N-CSR filings "
      "on EDGAR; not implemented. S&P 400 starts 2011-03 (page created 2010-12).")
    A("- S&P 400 / 600 membership is quarter-end granular (see `stale_days`); S&P 500 is exact to the change date, but the "
      "fja file lacks a few real constituents (gap-filled from Wikipedia, see section 4) and its early-year tickers are the "
      "companies' LATER tickers (identity is resolved per date through Wikipedia rows, see `FjaResolver`).")
    A("- The last ~2 months of S&P 500 changes (after the fja file ends) are patched from the live Wikipedia table; removal "
      "dates there are approximate.")
    A("- GICS before 2019 comes from Wikipedia and is sector-reliable but sub-industry-noisy; there is no free point-in-time "
      "GICS. Sub-industries back-filled with `*_next` use a later snapshot (mild classification look-ahead); filter on "
      "`gics_source` if that matters. Legacy (2008-structure) codes are best-effort reconstructions; names are exact where "
      "they occur in a snapshot.")
    A("- Companies that file with the FDIC instead of the SEC (Signature Bank, First Republic, Bank OZK after 2022, ...) have "
      "no CIK. Pre-XBRL acquisitions in the early S&P 500 snapshots (Sun Microsystems, Millipore, ...) are absent from the "
      "SEC company table and stay unmapped.")
    A("- Successor registrants: CIK aliases above map the new registrant back to the long-history CIK "
      "(`cik_successor` holds the new one). Older inversions (Medtronic Inc -> plc, Google -> Alphabet, ...) are NOT merged: "
      "each CIK is used in the dates it was filing.")
    A("- Yahoo coverage of delisted names is poor (research/05: about a third of removed S&P 500 names have usable data); "
      "keep them in the universe and measure coverage, do not drop them.")
    _atomic_write_text(path, "\n".join(L) + "\n") if path.parent.exists() else (path.parent.mkdir(parents=True, exist_ok=True), _atomic_write_text(path, "\n".join(L) + "\n"))
    return path


# --------------------------------------------------------------------------------------
# CLI (the fetch step is long and is run as its own process)
# --------------------------------------------------------------------------------------
def _setup_logging(level=logging.INFO) -> None:
    logging.basicConfig(level=level, format="%(asctime)s %(levelname)s %(name)s: %(message)s",
                        datefmt="%H:%M:%S", stream=sys.stdout)


def main(argv: list[str] | None = None) -> None:  # pragma: no cover
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("cmd", choices=["fetch-wiki", "build"], help="fetch-wiki: download Wikipedia; build: build_all")
    ap.add_argument("--force", action="store_true")
    a = ap.parse_args(argv)
    _setup_logging()
    if a.cmd == "fetch-wiki":
        fetch_wiki()
    else:
        build_all(force=a.force)


if __name__ == "__main__":  # pragma: no cover
    main()
