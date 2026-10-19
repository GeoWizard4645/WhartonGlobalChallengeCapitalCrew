"""Daily prices (Yahoo Finance via yfinance) -> wide parquet matrices, splits, meta, returns, risk-free.

Outputs (cache/prices/, schemas in quant/ARCHITECTURE.md)
    close.parquet      split-adjusted, NOT dividend-adjusted   (date x yf_ticker, float64)
    adjclose.parquet   split + dividend adjusted               (date x yf_ticker, float64)
    open.parquet       split-adjusted open
    volume.parquet     shares, as quoted by Yahoo (Yahoo restates history for splits)
    returns.parquet    daily total return = adjclose pct change, cleaned (rules R1-R7 below)
    splits.parquet     yf_ticker, date, ratio, genuine      (4.0 = 4:1 split, 0.1 = 1:10 reverse split)
    meta.parquet       yf_ticker, first_date, last_date, n_obs, status ('ok'/'empty'/'error'), note
                       (+ extras: max_gap_days, n_splits, n_nongenuine_splits, n_attempts, last_attempt)
    rf.parquet         date, rf_annual (decimal), rf_daily (= rf_annual / 252)   (+ rf_info.json)
    cleaning_log.csv   one row per cell changed by the cleaning rules
    attempts.parquet   download ledger (status of every ticker ever tried; drives resumability)
    raw/               source of truth: ``base.parquet`` + per-batch ``seg-NNNNNN-{full,upd}.parquet`` (long format)

Index of every matrix: ``date`` = trading days, tz-naive ``datetime64[ns]`` (yfinance returns ``[s]``, SEC data
``[us]``; ns avoids pandas-3 merge_asof unit clashes). Columns: ``yf_ticker`` (Yahoo symbol, class dots -> dashes).

Download strategy (measured, see research/05_data_sources.md and output/data_audit/price_coverage.md)
    * ``yf.download(batch, start, auto_adjust=False, actions=True, group_by='ticker', threads=True)`` in batches of
      ~150 tickers: ~4.5 s per batch with 20 threads, full 2007+ history of 5,551 tickers in 3.3 min with a 1 s pause
      between batches and no rate limiting; a 2-week ``update()`` of 5,500 tickers takes 2.5 min. The private ``yfinance.multi._download_impl`` is used so the
      per-ticker error text is available (to tell "Yahoo has nothing" = ``empty`` from "rate limit / timeout" =
      ``error``); a log-capturing fallback on the public ``yf.download`` is used if that API changes.
    * Rate limit / timeout errors are retried in-run with exponential backoff; tickers still failing are stored as
      ``error`` and retried by later runs (up to ``MAX_ERROR_ATTEMPTS`` runs). ``empty`` tickers (delisted names, Yahoo
      "possibly delisted; no timezone found") are recorded and NOT retried unless ``retry_empty=True``/``force``.
    * Every batch is written atomically as a segment (``raw/seg-*.parquet``) and the ledger is rewritten, so an
      interrupted run resumes where it stopped. ``rebuild()`` resolves base+segments, cleans, writes all outputs and
      compacts the segments into ``raw/base.parquet``.
    * ``update()`` (used before each trading day) re-downloads a ~2 week window for every still-trading ticker. Yahoo
      re-bases Adj Close (and Close for splits) after every dividend/split, so a cached history can never be appended
      blindly: the overlap with the cache is compared; if close/adjclose moved (new dividend, split, restatement)
      the whole ticker is re-downloaded, otherwise only the new rows are upserted.
    * A bar dated "today" is dropped by ``update`` before 16:30 New York time (partial bar); run after the close.

Cleaning rules (all changes are logged to cleaning_log.csv: yf_ticker, date, field, rule, old_value, new_value, detail)
    R1  A bar whose Close is NaN/<= 0 is dropped entirely (all fields NaN); a bar with both Close and Adj Close NaN
        (no trade / not yet published) is dropped silently. A bar with a valid Close but NaN/<= 0 Adj Close (Yahoo's
        dividend adjustment overshoots when a, often mis-scaled, dividend exceeds the price: NFE, DEC, CBIO, VATE)
        keeps its Close and gets adjclose = close * f, f = adj/close of the next valid bar (else previous): price-only
        returns inside the broken stretch, continuity at the splice (logged per cell as R1_adjclose_rebuilt).
    R2  Open <= 0 -> NaN (open only).  Volume < 0 -> NaN.  (Volume == 0 is kept as quoted.)
    R3  Duplicate (ticker, date) rows: the last one wins.
    R4  Calendar: only dates on which at least ``MIN_TICKERS_PER_DATE`` tickers have a bar are kept (drops stray
        non-trading-day bars Yahoo emits for a handful of symbols).
    R5  Bad ticks (applied separately to Close and to Adj Close): a bar at ``t`` whose move into ``t`` is above
        +300% or below -90% (versus the previous valid price within ``MAX_BRIDGE`` bars) and that is reversed on the
        next valid bar by at least 75% in log terms (|ln(P[t+1]/P[t])| >= 0.75*|ln(P[t]/P[t-1])|, opposite sign) is
        a one-day spike. Its price is set to NaN (up to 3 passes, to catch nested cases). Consequence: the return
        into ``t`` is NaN and the return out of ``t`` is the bridged return P[t+1]/P[t-1]-1, so the two bad returns
        are neutralised without discarding the genuine net move. (Task spec: "set the two returns to NaN"; this is
        the same filter with the bridged return kept instead of zeroed.)
    R7  Unrepaired splits: if Yahoo lists a split (|ln ratio| >= ln 1.9) but Close jumps across the ex-date by about
        1/ratio (z = ln jump / -ln ratio in [0.7, 1.3]; typically recent reverse splits of penny stocks, e.g. NFE
        1:50 on 2026-09-14), the bars before the ex-date are rescaled (prices / ratio, volume * ratio). One log row per
        event; this runs before R5/R6.
    R6  returns = AdjClose / (previous valid AdjClose, at most ``MAX_BRIDGE``=5 bars back) - 1. Gaps longer than
        that give NaN for the first bar after the gap. NaN at a missing day, so the engine (NaN inside a series = 0
        return, NaN after the last valid price = delisted) sees the real structure. No gap is ever filled with zeros
        or forward-filled in any matrix.
    Not touched (reported in the audit): non-reverting extreme moves, Yahoo scale errors, reused tickers.

Splits and the ``genuine`` flag
    Yahoo reports some spin-offs / special distributions as fractional "splits" (ASH 2.044). ``genuine`` is True when
    the ratio is within 0.5% of a simple fraction p/q (p, q <= 20, p != q: 2, 3, 3/2, 5/4, 1/10 ...) or of an integer
    N >= 2 or 1/N, N >= 2, of any size (1:25, 1:100 reverse splits, 50:1). ``split_factor_after`` /
    ``split_factors_after`` use genuine splits only by default (share counts); pass ``genuine_only=False`` for the
    factor that undoes *all* of Yahoo's price adjustments (unadjusted price = close * factor).

Public API
    download(tickers=None, start='2007-01-01', force=False, ...)  update(through=None, ...)  rebuild()
    load_close/adjclose/open/volume/returns(tickers=None, start=None, end=None)   load_splits()   load_meta()
    split_factor_after(ticker, date, genuine_only=True) -> float
    split_factors_after(tickers, dates, genuine_only=True) -> np.ndarray
    load_rf() -> DataFrame[rf_annual, rf_daily]   rf_daily() -> Series      build_rf()
    default_tickers() / sec_tickers() / read_price_tickers()      audit() -> writes output/data_audit/price_coverage.md
CLI:  .venv/bin/python -m quant.data.prices {download|update|rebuild|rf|audit|status} [options]

Refresh recipe (e.g. Tue 2026-10-20 evening, after the 16:00 ET close; never during market hours)
    .venv/bin/python -m quant.data.prices update     # new tickers + 2-week window + re-base check + rebuild + rf
    .venv/bin/python -m quant.data.prices audit      # regenerates output/data_audit/price_coverage.md
    .venv/bin/python -m quant.data.prices download   # only: pick up tickers newly added to price_tickers.txt
"""
from __future__ import annotations

import argparse
import contextlib
import datetime as dt
import fcntl
import json
import logging
import os
import re
import time
from pathlib import Path
from typing import Iterable, Sequence

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.parquet as pq

from quant import settings

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------------------
PRICE_DIR: Path = settings.PRICE_DIR           # module attribute so tests can monkeypatch it
START_DEFAULT = "2007-01-01"
TICKER_FILE = settings.UNIV_DIR / "price_tickers.txt"
AUDIT_PATH = settings.OUTPUT / "data_audit" / "price_coverage.md"

BATCH_SIZE = 150
SLEEP_BETWEEN = 1.0                 # seconds between batches
MAX_ERROR_ATTEMPTS = 3              # runs after which an 'error' ticker is left alone
MAX_ROUNDS = 4                      # in-run retry rounds for transient errors
REQUEST_TIMEOUT = 30
MAX_BRIDGE = 5                      # max bars bridged when computing returns / spike context
SPIKE_UP, SPIKE_DOWN, SPIKE_REV = 3.0, 0.9, 0.75
MIN_TICKERS_PER_DATE = 30
ACTIVE_DAYS = 10                    # a ticker whose last bar is within this many days of the latest is "trading"
UPDATE_WINDOW_DAYS = 14
UPDATE_TOL = 1e-6                   # relative close/adjclose mismatch in the overlap that forces a full re-download
GENUINE_TOL = 0.005
RF_DIVISOR = 252

EXTRA_BENCHMARKS = ["IWB", "IWV"]
FIELDS = ["open", "close", "adjclose", "volume"]
RAW_COLS = ["yf_ticker", "date", "open", "close", "adjclose", "volume", "dividend", "split"]


def _p(name: str) -> Path:
    return PRICE_DIR / name


def _raw_dir() -> Path:
    d = PRICE_DIR / "raw"
    d.mkdir(parents=True, exist_ok=True)
    return d


# --------------------------------------------------------------------------------------
# small helpers: atomic writes, lock, tickers
# --------------------------------------------------------------------------------------
def _tmp(path: Path) -> Path:
    return path.with_name(f".{path.name}.tmp{os.getpid()}")


def _atomic_table(table: pa.Table, path: Path, **kw) -> None:
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    kw.setdefault("compression", "zstd")
    kw.setdefault("compression_level", 3)
    pq.write_table(table, tmp, **kw)
    os.replace(tmp, path)


def _atomic_df(df: pd.DataFrame, path: Path, **kw) -> None:
    _atomic_table(pa.Table.from_pandas(df, preserve_index=False), path, **kw)


def _atomic_text(text: str, path: Path) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = _tmp(path)
    tmp.write_text(text)
    os.replace(tmp, path)


_lock_depth = 0


@contextlib.contextmanager
def _lock():
    """Exclusive, re-entrant, non-blocking process lock: one writer at a time."""
    global _lock_depth
    if _lock_depth > 0:
        _lock_depth += 1
        try:
            yield
        finally:
            _lock_depth -= 1
        return
    PRICE_DIR.mkdir(parents=True, exist_ok=True)
    f = open(PRICE_DIR / ".lock", "w")
    try:
        fcntl.flock(f, fcntl.LOCK_EX | fcntl.LOCK_NB)
    except BlockingIOError as e:
        f.close()
        raise RuntimeError("another quant.data.prices process is writing cache/prices") from e
    _lock_depth = 1
    try:
        yield
    finally:
        _lock_depth = 0
        fcntl.flock(f, fcntl.LOCK_UN)
        f.close()


_TICKER_OK = re.compile(r"^[\^A-Z0-9][A-Z0-9\-=\^]{0,14}$")


def normalize_ticker(t) -> str | None:
    """Yahoo symbol: upper case, class dots -> dashes (BRK.B -> BRK-B); None if not a plausible symbol."""
    if t is None or (isinstance(t, float) and np.isnan(t)):
        return None
    s = str(t).strip().upper().replace(".", "-").replace("/", "-").replace(" ", "")
    return s if _TICKER_OK.match(s) else None


def _norm_list(items: Iterable) -> list[str]:
    seen, out = set(), []
    for t in items:
        s = normalize_ticker(t)
        if s and s not in seen:
            seen.add(s)
            out.append(s)
    return out


def sec_tickers() -> list[str]:
    """Current NYSE/Nasdaq(/NYSE American) listed operating companies with >=1 10-K (SEC companies table).
    ``tickers`` and ``exchanges`` are pipe-joined and positionally aligned."""
    from quant.data import sec

    c = sec.load_companies()
    c = c[(c["n_10k"] > 0) & (c["tickers"].fillna("") != "")]
    out = []
    for tk, ex in zip(c["tickers"], c["exchanges"].fillna("")):
        ts = tk.split("|")
        es = ex.split("|")
        es = (es + [""] * len(ts))[: len(ts)]
        out += [t for t, e in zip(ts, es) if e in ("NYSE", "Nasdaq", "NYSE American", "AMEX")]
    return _norm_list(out)


def read_price_tickers() -> list[str]:
    """Tickers written by the universe builder (cache/universe/price_tickers.txt); [] if the file is absent."""
    if not TICKER_FILE.exists():
        return []
    lines = [ln.split("#")[0].strip() for ln in TICKER_FILE.read_text().splitlines()]
    return _norm_list(ln for ln in lines if ln)


def default_tickers() -> list[str]:
    """benchmarks + price_tickers.txt (if present) + SEC-derived current listings (deduplicated, order kept)."""
    items = list(settings.BENCHMARKS) + EXTRA_BENCHMARKS + read_price_tickers()
    try:
        items += sec_tickers()
    except Exception as e:  # SEC cache not built yet
        log.warning("sec_tickers() unavailable: %s", e)
    return _norm_list(items)


# --------------------------------------------------------------------------------------
# download ledger
# --------------------------------------------------------------------------------------
_ATT_COLS = ["status", "note", "n_attempts", "last_attempt"]


def _load_attempts() -> pd.DataFrame:
    path = _p("attempts.parquet")
    if not path.exists():
        return pd.DataFrame(
            {"status": pd.Series(dtype="str"), "note": pd.Series(dtype="str"),
             "n_attempts": pd.Series(dtype="int64"), "last_attempt": pd.Series(dtype="str")},
            index=pd.Index([], name="yf_ticker", dtype="str"),
        )
    df = pd.read_parquet(path).set_index("yf_ticker")
    df["note"] = df["note"].fillna("")
    return df


def _save_attempts(att: pd.DataFrame) -> None:
    _atomic_df(att.reset_index().rename(columns={"index": "yf_ticker"}), _p("attempts.parquet"))


# --------------------------------------------------------------------------------------
# fetching
# --------------------------------------------------------------------------------------
_TRANSIENT = re.compile(
    r"rate.?limit|too many requests|\b429\b|timed? ?out|timeout|connection|curl|ssl|temporar|\b50[0-4]\b|"
    r"reset by peer|failed to perform|network|unreachable|try again|expecting value|jsondecode", re.I)
_EMPTY = re.compile(r"delist|no timezone|no price data|not found|\b404\b|no data found|invalid|symbol", re.I)


def classify_error(err: str | None) -> str:
    """'error' (transient: retry) or 'empty' (Yahoo has nothing for the symbol)."""
    if not err:
        return "empty"
    if _TRANSIENT.search(err):
        return "error"
    return "empty"


def _frame_to_long(tk: str, df: pd.DataFrame) -> pd.DataFrame | None:
    """One ticker's yfinance frame -> long raw schema. None if it holds no price bar."""
    if df is None or len(df) == 0:
        return None
    n = len(df)

    def col(name):
        return df[name].to_numpy(dtype="float64", na_value=np.nan) if name in df.columns else np.full(n, np.nan)

    idx = pd.DatetimeIndex(df.index)
    if idx.tz is not None:
        idx = idx.tz_localize(None)
    out = pd.DataFrame({
        "yf_ticker": tk,
        "date": idx.normalize().astype("datetime64[ns]"),
        "open": col("Open"), "close": col("Close"), "adjclose": col("Adj Close"), "volume": col("Volume"),
        "dividend": np.nan_to_num(col("Dividends")), "split": np.nan_to_num(col("Stock Splits")),
    })
    out = out[out["close"].notna() | out["adjclose"].notna()]
    if out.empty:
        return None
    out = out.drop_duplicates("date", keep="last").sort_values("date", kind="stable").reset_index(drop=True)
    out["yf_ticker"] = out["yf_ticker"].astype("str")
    return out


def _parse_yf_log_errors(records: list[str]) -> dict[str, str]:
    errs: dict[str, str] = {}
    for m in records:
        mm = re.match(r"^\s*\[(.*?)\]:\s*(.*)$", m, re.S)
        if mm:
            for s in re.findall(r"'([^']+)'", mm.group(1)):
                errs[s.upper()] = mm.group(2)
    return errs


def _fetch(tickers: Sequence[str], start, end, timeout: float = REQUEST_TIMEOUT):
    """Download one batch. Returns (frames: ticker -> long df or None, errors: ticker -> text)."""
    import yfinance as yf

    yflog = logging.getLogger("yfinance")
    old_level = yflog.level
    yflog.setLevel(logging.CRITICAL)           # we report errors ourselves
    errors: dict[str, str] = {}
    try:
        data = None
        try:
            from yfinance import multi as _multi

            ctx = _multi._DownloadCtx()
            data = _multi._download_impl(
                ctx, list(tickers), start=start, end=end, actions=True, threads=True, ignore_tz=True,
                group_by="ticker", auto_adjust=False, back_adjust=False, repair=False, keepna=False,
                progress=False, interval="1d", prepost=False, rounding=False, timeout=timeout, session=None,
                multi_level_index=True)
            errors = {k.upper(): str(v) for k, v in ctx.errors.items()}
        except (AttributeError, TypeError) as e:
            log.warning("yfinance private API unavailable (%s); falling back to yf.download", e)
            records: list[str] = []

            class _H(logging.Handler):
                def emit(self, record):
                    records.append(record.getMessage())

            h = _H()
            yflog.setLevel(logging.ERROR)
            yflog.addHandler(h)
            try:
                data = yf.download(list(tickers), start=start, end=end, auto_adjust=False, actions=True,
                                   group_by="ticker", threads=True, progress=False, timeout=timeout,
                                   multi_level_index=True)
            finally:
                yflog.removeHandler(h)
            errors = _parse_yf_log_errors(records)
    finally:
        yflog.setLevel(old_level)

    frames: dict[str, pd.DataFrame | None] = {}
    have = set(data.columns.get_level_values(0)) if data is not None and isinstance(data.columns, pd.MultiIndex) else set()
    for tk in tickers:
        key = tk.upper()
        frames[tk] = _frame_to_long(tk, data[key]) if key in have else None
        if tk not in errors and key in errors:
            errors[tk] = errors[key]
    return frames, errors


def _fetch_resilient(batch: Sequence[str], start, end, max_rounds: int = MAX_ROUNDS):
    """Fetch with in-run retries of transient failures. Returns {ticker: (status, long_df|None, note)}."""
    results: dict[str, tuple] = {}
    todo = list(batch)
    for rnd in range(max_rounds):
        try:
            frames, errs = _fetch(todo, start, end)
        except Exception as e:  # whole call failed (network down, ...)
            log.warning("batch call failed (%s: %s)", type(e).__name__, e)
            frames, errs = {t: None for t in todo}, {t: repr(e) for t in todo}
        retry = []
        for tk in todo:
            df = frames.get(tk)
            if df is not None and len(df):
                results[tk] = ("ok", df, "")
                continue
            err = errs.get(tk, "")
            st = classify_error(err)
            if st == "error" and rnd < max_rounds - 1:
                retry.append(tk)
            else:
                results[tk] = (st, None, (err or "no rows returned")[:200])
        if not retry:
            break
        heavy = len(retry) > 0.2 * len(batch)
        wait = (30 * 2 ** rnd) if heavy else (3 * 2 ** rnd)
        log.warning("round %d: %d/%d tickers hit transient errors; sleeping %ds", rnd + 1, len(retry), len(batch), wait)
        time.sleep(wait)
        todo = retry
    return results


# --------------------------------------------------------------------------------------
# raw store (long format)
# --------------------------------------------------------------------------------------
_SEG_RE = re.compile(r"^seg-(\d{6})-(full|upd)\.parquet$")
_RAW_SCHEMA = pa.schema([
    ("yf_ticker", pa.string()), ("date", pa.timestamp("ns")),
    ("open", pa.float64()), ("close", pa.float64()), ("adjclose", pa.float64()),
    ("volume", pa.float64()), ("dividend", pa.float64()), ("split", pa.float64()),
])


def _list_segments() -> list[tuple[int, str, Path]]:
    out = []
    for f in _raw_dir().iterdir():
        m = _SEG_RE.match(f.name)
        if m:
            out.append((int(m.group(1)), m.group(2), f))
    return sorted(out)


def _write_segment(df: pd.DataFrame, kind: str) -> Path:
    assert kind in ("full", "upd")
    segs = _list_segments()
    seq = (segs[-1][0] + 1) if segs else 1
    path = _raw_dir() / f"seg-{seq:06d}-{kind}.parquet"
    t = pa.Table.from_pandas(df[RAW_COLS], schema=_RAW_SCHEMA, preserve_index=False)
    _atomic_table(t, path)
    return path


def _read_raw(path: Path) -> pd.DataFrame:
    df = pq.read_table(path).to_pandas()
    df["date"] = df["date"].astype("datetime64[ns]")
    return df


def _read_resolved_long() -> pd.DataFrame:
    """base + segments -> one long frame. A 'full' segment replaces all earlier rows of its tickers; an 'upd'
    segment upserts rows (later wins on (ticker, date))."""
    items: list[tuple[int, str, Path]] = []
    base = _raw_dir() / "base.parquet"
    if base.exists():
        items.append((0, "full", base))
    items += _list_segments()
    if not items:
        return pd.DataFrame({c: pd.Series(dtype="float64") for c in RAW_COLS})
    frames = [(seq, kind, _read_raw(path)) for seq, kind, path in items]
    latest_full: dict[str, int] = {}
    for seq, kind, df in frames:
        if kind == "full" and seq > 0:
            for t in df["yf_ticker"].unique():
                latest_full[t] = max(latest_full.get(t, 0), seq)
    pieces, any_upd = [], False
    for seq, kind, df in frames:
        stale = [t for t, s in latest_full.items() if s > seq]
        if stale and seq < max(latest_full.values()):
            df = df[~df["yf_ticker"].isin(stale)]
        any_upd |= kind == "upd"
        pieces.append(df)
    L = pd.concat(pieces, ignore_index=True)
    if any_upd or len(pieces) > 1:
        L = L.drop_duplicates(["yf_ticker", "date"], keep="last")
    return L


def _write_base(L: pd.DataFrame) -> None:
    codes = pd.factorize(L["yf_ticker"], sort=True)[0]
    order = np.lexsort((L["date"].to_numpy(), codes))
    S = L.iloc[order].reset_index(drop=True)
    t = pa.Table.from_pandas(S[RAW_COLS], schema=_RAW_SCHEMA, preserve_index=False)
    _atomic_table(t, _raw_dir() / "base.parquet", row_group_size=1_000_000)


# --------------------------------------------------------------------------------------
# download
# --------------------------------------------------------------------------------------
def _now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _record_attempts(att: pd.DataFrame, results: dict) -> pd.DataFrame:
    now = _now_iso()
    rows = {}
    for tk, (st, _df, note) in results.items():
        n = int(att.loc[tk, "n_attempts"]) + 1 if tk in att.index else 1
        rows[tk] = {"status": st, "note": note, "n_attempts": n, "last_attempt": now}
    new = pd.DataFrame.from_dict(rows, orient="index", columns=_ATT_COLS)
    new.index.name = "yf_ticker"
    att = att.drop(index=[t for t in new.index if t in att.index])
    return pd.concat([att, new]).sort_index()


def _pending(want: list[str], att: pd.DataFrame, force: bool, retry_empty: bool) -> list[str]:
    if force:
        return list(want)
    out = []
    for t in want:
        if t not in att.index:
            out.append(t)
            continue
        st, n = att.at[t, "status"], int(att.at[t, "n_attempts"])
        if st == "error" and n < MAX_ERROR_ATTEMPTS:
            out.append(t)
        elif st == "empty" and retry_empty and n < 2:
            out.append(t)
    return out


def download(tickers: Sequence[str] | None = None, start: str = START_DEFAULT, force: bool = False, *,
             retry_empty: bool = False, max_tickers: int | None = None, batch_size: int = BATCH_SIZE,
             sleep: float = SLEEP_BETWEEN, rebuild: bool = True) -> dict:
    """Download full daily history (``start``..today) for tickers not yet attempted.

    tickers=None -> ``default_tickers()`` (benchmarks + price_tickers.txt + SEC current listings). Tickers with status
    'ok' (or 'empty', unless ``retry_empty``) are never re-downloaded unless ``force``; 'error' tickers are retried
    up to MAX_ERROR_ATTEMPTS runs. ``max_tickers`` limits one call (chunked runs). Returns a summary dict."""
    t0 = time.time()
    with _lock():
        want = _norm_list(tickers) if tickers is not None else default_tickers()
        att = _load_attempts()
        todo = _pending(want, att, force, retry_empty)
        if max_tickers is not None:
            todo = todo[:max_tickers]
        summ = {"requested": len(want), "todo": len(todo), "ok": 0, "empty": 0, "error": 0}
        log.info("download: %d requested, %d to fetch (batch=%d)", len(want), len(todo), batch_size)
        nb = (len(todo) + batch_size - 1) // batch_size
        for b in range(nb):
            batch = todo[b * batch_size:(b + 1) * batch_size]
            tb = time.time()
            res = _fetch_resilient(batch, start, None)
            frames = [df for (st, df, _n) in res.values() if st == "ok"]
            if frames:
                _write_segment(pd.concat(frames, ignore_index=True), "full")
            att = _record_attempts(att, res)
            _save_attempts(att)
            c = {s: sum(1 for v in res.values() if v[0] == s) for s in ("ok", "empty", "error")}
            for s in c:
                summ[s] += c[s]
            log.info("batch %d/%d  ok=%d empty=%d error=%d  (%.1fs)  cumulative ok=%d empty=%d error=%d",
                     b + 1, nb, c["ok"], c["empty"], c["error"], time.time() - tb, summ["ok"], summ["empty"], summ["error"])
            if b < nb - 1:
                time.sleep(sleep)
        if rebuild and (todo or not _p("close.parquet").exists()):
            rebuild_outputs()
        summ["seconds"] = round(time.time() - t0, 1)
        return summ


def _market_partial_date() -> pd.Timestamp | None:
    """The calendar date whose daily bar is still partial (US market open or just closed), else None."""
    from zoneinfo import ZoneInfo

    now = dt.datetime.now(ZoneInfo("America/New_York"))
    if now.weekday() < 5 and (now.hour, now.minute) < (16, 30):
        return pd.Timestamp(now.date())
    return None


def update(through=None, *, include_new: bool = True, batch_size: int = BATCH_SIZE, drop_partial: bool = True,
           sleep: float = SLEEP_BETWEEN, rebuild: bool = True) -> dict:
    """Append the latest bars for every still-trading ticker (run after the close, e.g. Tue evening).

    * include_new: first download any default-list ticker never attempted (new IPOs, new universe members).
    * Window: last ``UPDATE_WINDOW_DAYS`` days before the latest cached date .. ``through`` (default today).
    * Per ticker, the overlap with the cache is checked: if close/adjclose differ by more than ``UPDATE_TOL``
      (dividend or split re-based Yahoo history, or a data restatement) the full history is re-downloaded,
      else the new rows are upserted.
    * drop_partial: a bar dated today is dropped before 16:30 New York time.
    """
    t0 = time.time()
    with _lock():
        summ: dict = {}
        if include_new:
            summ["new"] = download(rebuild=False, batch_size=batch_size, sleep=sleep)
        L = _read_resolved_long()
        if L.empty:
            raise RuntimeError("no price data cached; run download() first")
        last = L.groupby("yf_ticker")["date"].max()
        latest = last.max()
        active = last[last >= latest - pd.Timedelta(days=ACTIVE_DAYS)].index.tolist()
        start_fetch = (latest - pd.Timedelta(days=UPDATE_WINDOW_DAYS)).normalize()
        if through is None:
            end_date = pd.Timestamp(dt.date.today())
        else:
            end_date = pd.Timestamp(through).normalize()
        end_fetch = end_date + pd.Timedelta(days=1)
        partial = _market_partial_date() if drop_partial else None
        win = L[L["date"] >= start_fetch][["yf_ticker", "date", "close", "adjclose"]]
        cached = {t: g.set_index("date") for t, g in win.groupby("yf_ticker")}
        del L
        log.info("update: latest cached %s, %d active tickers, window %s..%s (partial bar dropped: %s)",
                 latest.date(), len(active), start_fetch.date(), end_date.date(), partial.date() if partial is not None else None)

        upd_parts, refresh, n_new_rows, n_noop = [], [], 0, 0
        nb = (len(active) + batch_size - 1) // batch_size
        for b in range(nb):
            batch = active[b * batch_size:(b + 1) * batch_size]
            res = _fetch_resilient(batch, start_fetch, end_fetch)
            for tk, (st, df, _note) in res.items():
                if st != "ok":
                    n_noop += 1
                    continue
                if partial is not None:
                    df = df[df["date"] != partial]
                df = df[df["date"] <= end_date]
                if df.empty:
                    n_noop += 1
                    continue
                c = cached.get(tk)
                ov = df.merge(c.reset_index(), on="date", suffixes=("", "_c")) if c is not None else df.iloc[:0]
                if ov.empty:
                    refresh.append(tk)
                    continue
                if len(ov) > 1:
                    ov = ov[ov["date"] < c.index.max()]
                rel = np.nanmax(np.r_[(ov["close"] / ov["close_c"] - 1).abs(), (ov["adjclose"] / ov["adjclose_c"] - 1).abs()])
                if not np.isfinite(rel) or rel > UPDATE_TOL:
                    refresh.append(tk)
                    continue
                upd_parts.append(df)
                n_new_rows += int((df["date"] > c.index.max()).sum())
            log.info("update batch %d/%d: %d upserts so far, %d to refresh", b + 1, nb, len(upd_parts), len(refresh))
            if b < nb - 1:
                time.sleep(sleep)
        if upd_parts:
            _write_segment(pd.concat(upd_parts, ignore_index=True), "upd")
        summ.update({"active": len(active), "upserted": len(upd_parts), "new_rows": n_new_rows, "no_data": n_noop,
                     "refresh": len(refresh)})
        if refresh:
            log.info("update: %d tickers re-based by Yahoo (dividend/split/restatement) -> full re-download", len(refresh))
            summ["refresh_run"] = download(refresh, force=True, rebuild=False, batch_size=batch_size, sleep=sleep)
        if rebuild:
            rebuild_outputs()
            try:
                build_rf()
            except Exception as e:  # keep prices even if the rate source is down
                log.warning("rf refresh failed: %s", e)
        summ["seconds"] = round(time.time() - t0, 1)
        return summ


# --------------------------------------------------------------------------------------
# cleaning
# --------------------------------------------------------------------------------------
LOG_COLS = ["yf_ticker", "date", "field", "rule", "old_value", "new_value", "detail"]


def _log_rows(ticker, date, field, rule, old, new, detail="") -> pd.DataFrame:
    vals = {"yf_ticker": ticker, "date": date, "field": field, "rule": rule, "old_value": old,
            "new_value": new, "detail": detail}
    n = max([len(v) for v in vals.values() if isinstance(v, (list, tuple, np.ndarray, pd.Series))] or [1])
    return pd.DataFrame(vals, index=range(n))


def clean_long(L: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rules R1-R4 on the long frame. Returns (clean long, log rows)."""
    logs: list[pd.DataFrame] = []
    L = L[L["date"].notna()]
    n0 = len(L)
    L = L.drop_duplicates(["yf_ticker", "date"], keep="last")
    if len(L) < n0:
        logs.append(_log_rows("*", pd.NaT, "row", "R3_duplicate", float(n0 - len(L)), np.nan, "duplicate (ticker,date) rows dropped"))

    c, a = L["close"].to_numpy(), L["adjclose"].to_numpy()
    both_nan = np.isnan(c) & np.isnan(a)
    c_bad = np.isnan(c) | (c <= 0) | np.isinf(c)
    a_bad = np.isnan(a) | (a <= 0) | np.isinf(a)
    drop = both_nan | (c_bad & ~both_nan)               # no usable Close
    logged = c_bad & ~both_nan
    if logged.any():
        B = L[logged]
        logs.append(_log_rows(B["yf_ticker"].to_numpy(), B["date"].to_numpy(), "close/adjclose", "R1_bad_price_row",
                              B["close"].to_numpy(), B["adjclose"].to_numpy(), "row dropped (old=close, new=adjclose)"))
    L = L[~drop].copy()
    # valid Close but non-positive/NaN Adj Close (Yahoo's dividend adjustment overshoots when a (mis-scaled) dividend
    # exceeds the price: NFE, DEC, CBIO, VATE): rebuild adjclose = close * f, f = adj/close of the next valid bar
    # (else the previous one), i.e. price-only returns inside the broken stretch, continuity at the splice.
    a = L["adjclose"].to_numpy()
    a_bad = np.isnan(a) | (a <= 0) | np.isinf(a)
    if a_bad.any():
        tk_bad = L.loc[a_bad, "yf_ticker"].unique()
        sub = L[L["yf_ticker"].isin(tk_bad)]
        ratio = (sub["adjclose"] / sub["close"]).where(sub["adjclose"] > 0)
        ratio = ratio.groupby(sub["yf_ticker"]).bfill()
        ratio = ratio.groupby(sub["yf_ticker"]).ffill().fillna(1.0)
        fix = sub.index[~(sub["adjclose"] > 0)]
        new = (sub.loc[fix, "close"] * ratio.loc[fix]).to_numpy()
        logs.append(_log_rows(sub.loc[fix, "yf_ticker"].to_numpy(), sub.loc[fix, "date"].to_numpy(), "adjclose",
                              "R1_adjclose_rebuilt", sub.loc[fix, "adjclose"].to_numpy(), new,
                              "adjclose <= 0/NaN with valid close: rebuilt as close * adj/close of neighbouring valid bar"))
        L.loc[fix, "adjclose"] = new

    o = L["open"].to_numpy()
    bad_o = ~np.isnan(o) & ((o <= 0) | np.isinf(o))
    if bad_o.any():
        B = L[bad_o]
        logs.append(_log_rows(B["yf_ticker"].to_numpy(), B["date"].to_numpy(), "open", "R2_bad_open", B["open"].to_numpy(), np.nan))
        L.loc[bad_o, "open"] = np.nan
    v = L["volume"].to_numpy()
    bad_v = ~np.isnan(v) & ((v < 0) | np.isinf(v))
    if bad_v.any():
        B = L[bad_v]
        logs.append(_log_rows(B["yf_ticker"].to_numpy(), B["date"].to_numpy(), "volume", "R2_bad_volume", B["volume"].to_numpy(), np.nan))
        L.loc[bad_v, "volume"] = np.nan

    cnt = L.groupby("date")["yf_ticker"].transform("size")
    off = cnt < MIN_TICKERS_PER_DATE
    if off.any():
        B = L[off]
        logs.append(_log_rows(B["yf_ticker"].to_numpy(), B["date"].to_numpy(), "row", "R4_off_calendar", B["close"].to_numpy(), np.nan,
                              f"date has < {MIN_TICKERS_PER_DATE} tickers with a bar"))
        L = L[~off]
    out = pd.concat(logs, ignore_index=True) if logs else pd.DataFrame(columns=LOG_COLS)
    return L.reset_index(drop=True), out


SPLIT_REPAIR_MIN_LOG = float(np.log(1.9))     # only ratios <= 1/1.9 or >= 1.9 are checked
SPLIT_REPAIR_Z = (0.7, 1.3)                   # observed log-jump / expected unadjusted log-jump


def repair_unadjusted_splits(L: pd.DataFrame, sp: pd.DataFrame) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Rule R7. Yahoo records a split but sometimes has not re-based the history before it (recent reverse splits
    of penny stocks, some old OTC names): Close jumps by ~1/ratio across the ex-date (NFE 2026-09-14, 1:50, +4100%).
    For every split event with |ln ratio| >= ln 1.9 compare the log jump of Close across the ex-date with the
    log jump an unadjusted split would show (-ln ratio): z = ln(J) / -ln(ratio). If 0.7 <= z <= 1.3 every bar before
    the ex-date is rescaled (open/close/adjclose divided by ratio, volume multiplied by ratio). One log row per event.
    ``L`` must be clean (positive prices)."""
    if sp.empty or L.empty:
        return L, pd.DataFrame(columns=LOG_COLS)
    codes = pd.factorize(L["yf_ticker"], sort=True)[1]
    tpos = pd.factorize(L["yf_ticker"], sort=True)[0]
    order = np.lexsort((L["date"].to_numpy(), tpos))
    L = L.iloc[order].reset_index(drop=True)
    tpos = tpos[order]
    bounds = np.searchsorted(tpos, np.arange(len(codes) + 1))
    start_of = {t: (bounds[i], bounds[i + 1]) for i, t in enumerate(codes)}
    dates = L["date"].to_numpy()
    close = L["close"].to_numpy()
    cols = {c: L[c].to_numpy().copy() for c in ("open", "close", "adjclose", "volume")}
    logs = []
    cand = sp[(np.abs(np.log(sp["ratio"])) >= SPLIT_REPAIR_MIN_LOG)]
    for t, d, rho in zip(cand["yf_ticker"], cand["date"].to_numpy(), cand["ratio"].to_numpy()):
        se = start_of.get(t)
        if se is None:
            continue
        s0, s1 = se
        pos = s0 + int(np.searchsorted(dates[s0:s1], d, side="left"))
        if pos <= s0 or pos >= s1:
            continue
        if (dates[pos] - d) > np.timedelta64(7, "D") or (dates[pos] - dates[pos - 1]) > np.timedelta64(12, "D"):
            continue
        J = close[pos] / close[pos - 1]
        z = np.log(J) / (-np.log(rho))
        if SPLIT_REPAIR_Z[0] <= z <= SPLIT_REPAIR_Z[1]:
            for c in ("open", "close", "adjclose"):
                cols[c][s0:pos] = cols[c][s0:pos] / rho
            cols["volume"][s0:pos] = cols["volume"][s0:pos] * rho
            close = cols["close"]
            logs.append(_log_rows(t, pd.Timestamp(d), "open/close/adjclose/volume", "R7_unadjusted_split", float(J),
                                  float(cols["close"][pos] / cols["close"][pos - 1]),
                                  f"ratio={rho:.6g} z={z:.2f}: {pos - s0} bars before ex-date rescaled (prices/ratio, volume*ratio); old=close jump, new=jump after repair"))
    for c, v in cols.items():
        L[c] = v
    out = pd.concat(logs, ignore_index=True) if logs else pd.DataFrame(columns=LOG_COLS)
    return L, out


def _spike_mask(P: pd.DataFrame) -> pd.DataFrame:
    """Bad-tick detector (rule R5) for a date x ticker price frame."""
    prev = P.ffill(limit=MAX_BRIDGE).shift(1)
    nxt = P.bfill(limit=MAX_BRIDGE).shift(-1)
    with np.errstate(all="ignore"):
        a = P / prev
        b = nxt / P
        la, lb = np.log(a), np.log(b)
        jump = (a > 1 + SPIKE_UP) | (a < 1 - SPIKE_DOWN)
        rev = (np.sign(la) * np.sign(lb) < 0) & (lb.abs() >= SPIKE_REV * la.abs())
    return jump & rev


def remove_spikes(P: pd.DataFrame, field: str, max_pass: int = 3) -> tuple[pd.DataFrame, pd.DataFrame]:
    """Apply R5 to a price frame; returns (cleaned frame, log rows)."""
    P = P.copy()
    logs = []
    for ps in range(1, max_pass + 1):
        m = _spike_mask(P)
        if not m.to_numpy().any():
            break
        ii, jj = np.nonzero(m.to_numpy())
        vals = P.to_numpy()[ii, jj]
        prev = P.ffill(limit=MAX_BRIDGE).shift(1).to_numpy()[ii, jj]
        nxt = P.bfill(limit=MAX_BRIDGE).shift(-1).to_numpy()[ii, jj]
        logs.append(_log_rows(P.columns.to_numpy()[jj], P.index.to_numpy()[ii], field, "R5_bad_tick", vals, np.nan,
                              [f"pass{ps} prev={p:.6g} next={n:.6g}" for p, n in zip(prev, nxt)]))
        P = P.mask(m)
    out = pd.concat(logs, ignore_index=True) if logs else pd.DataFrame(columns=LOG_COLS)
    return P, out


def compute_returns(adj: pd.DataFrame) -> pd.DataFrame:
    """Rule R6: adjclose / previous valid adjclose (<= MAX_BRIDGE bars back) - 1; NaN where adjclose is NaN."""
    return adj / adj.ffill(limit=MAX_BRIDGE).shift(1) - 1.0


def is_genuine_split(ratio) -> np.ndarray:
    """True for real split ratios: within 0.5% of p/q (p,q<=20, p!=q) or of N / 1/N (N>=2, any size)."""
    r = np.atleast_1d(np.asarray(ratio, dtype="float64"))
    ok = np.zeros(r.shape, dtype=bool)
    good = np.isfinite(r) & (r > 0)
    if not good.any():
        return ok
    x = r[good]
    fr = np.array(sorted({p / q for p in range(1, 21) for q in range(1, 21) if p != q}))
    near = (np.abs(x[:, None] / fr[None, :] - 1.0) <= GENUINE_TOL).any(axis=1)
    n = np.round(x)
    near_int = (n >= 2) & (np.abs(x / np.where(n > 0, n, 1) - 1.0) <= GENUINE_TOL)
    m = np.round(1.0 / x)
    near_rec = (m >= 2) & (np.abs(x * np.where(m > 0, m, 1) - 1.0) <= GENUINE_TOL)
    ok[good] = near | near_int | near_rec
    return ok


# --------------------------------------------------------------------------------------
# rebuild: raw -> cleaned wide matrices + returns + splits + meta
# --------------------------------------------------------------------------------------
def _write_wide(arr: np.ndarray, dates: np.ndarray, tickers: Sequence[str], path: Path) -> None:
    cols = {"date": pa.array(dates.astype("datetime64[ns]"))}
    for j, t in enumerate(tickers):
        cols[t] = pa.array(arr[:, j], from_pandas=True)
    _atomic_table(pa.table(cols), path, row_group_size=len(dates) or 1)


def _chunks(n: int, size: int):
    for s in range(0, n, size):
        yield s, min(n, s + size)


def rebuild_outputs(compact: bool = True) -> dict:
    """Resolve the raw store, clean it (R1-R7) and (re)write every derived file. Returns a small summary."""
    t0 = time.time()
    with _lock():
        L = _read_resolved_long()
        if L.empty:
            raise RuntimeError("raw store is empty; run download() first")
        log.info("rebuild: %d raw rows, %d tickers", len(L), L["yf_ticker"].nunique())
        if compact:
            _write_base(L)
            for _seq, _kind, path in _list_segments():
                path.unlink()

        # splits come from the raw rows (before price-row cleaning)
        sp = L.loc[(L["split"] > 0) & np.isfinite(L["split"]) & (L["split"] != 1.0), ["yf_ticker", "date", "split"]]
        sp = sp.rename(columns={"split": "ratio"}).drop_duplicates(["yf_ticker", "date"], keep="last")
        sp = sp.sort_values(["yf_ticker", "date"]).reset_index(drop=True)
        sp["genuine"] = is_genuine_split(sp["ratio"].to_numpy())
        sp["yf_ticker"] = sp["yf_ticker"].astype("str")

        L, logs = clean_long(L)
        logs = [logs]
        L, lg7 = repair_unadjusted_splits(L, sp)
        logs.append(lg7)
        codes, tickers = pd.factorize(L["yf_ticker"], sort=True)
        dates = np.sort(L["date"].unique())
        di = np.searchsorted(dates, L["date"].to_numpy())
        nd, nt = len(dates), len(tickers)
        log.info("rebuild: matrix %d dates x %d tickers (%.0f MB per field)", nd, nt, nd * nt * 8 / 1e6)
        tick_index = pd.Index(tickers, dtype="str")
        date_index = pd.DatetimeIndex(dates, name="date")

        def wide(field):
            arr = np.full((nd, nt), np.nan)
            arr[di, codes] = L[field].to_numpy()
            return arr

        # --- prices with R5 (chunked over columns to bound memory)
        cleaned = {}
        for field in ("close", "adjclose"):
            arr = wide(field)
            for s, e in _chunks(nt, 1000):
                P = pd.DataFrame(arr[:, s:e], index=date_index, columns=tick_index[s:e])
                P2, lg = remove_spikes(P, field)
                arr[:, s:e] = P2.to_numpy()
                if len(lg):
                    logs.append(lg)
            cleaned[field] = arr
        # drop rows' companion fields where the price is gone? no: open/volume are kept as quoted.
        # returns (R6) from cleaned adjclose
        ret = np.full((nd, nt), np.nan)
        for s, e in _chunks(nt, 1000):
            P = pd.DataFrame(cleaned["adjclose"][:, s:e], index=date_index, columns=tick_index[s:e])
            ret[:, s:e] = compute_returns(P).to_numpy()
        _write_wide(cleaned["close"], dates, tickers, _p("close.parquet"))
        _write_wide(cleaned["adjclose"], dates, tickers, _p("adjclose.parquet"))
        _write_wide(ret, dates, tickers, _p("returns.parquet"))
        del ret
        for field in ("open", "volume"):
            _write_wide(wide(field), dates, tickers, _p(f"{field}.parquet"))

        # --- meta
        valid = ~np.isnan(cleaned["close"])
        n_obs = valid.sum(axis=0)
        first_i = valid.argmax(axis=0)
        last_i = nd - 1 - valid[::-1].argmax(axis=0)
        d_int = (dates.astype("datetime64[D]").astype("int64"))
        max_gap = np.zeros(nt)
        for j in range(nt):
            if n_obs[j] > 1:
                max_gap[j] = np.diff(d_int[valid[:, j]]).max()
        latest = dates[-1]
        meta = pd.DataFrame({
            "yf_ticker": tickers.astype("str"),
            "first_date": dates[first_i], "last_date": dates[last_i], "n_obs": n_obs.astype("int64"),
            "max_gap_days": max_gap.astype("int64"),
        })
        meta.loc[meta["n_obs"] == 0, ["first_date", "last_date"]] = pd.NaT
        att = _load_attempts()
        meta = _merge_meta(meta, att, sp, latest)
        meta = _flag_late_starts(meta)
        logs = pd.concat([x for x in logs if len(x)], ignore_index=True) if any(len(x) for x in logs) else pd.DataFrame(columns=LOG_COLS)
        logs = logs.sort_values(["yf_ticker", "date"], kind="stable")
        _atomic_text(logs.to_csv(index=False, date_format="%Y-%m-%d"), _p("cleaning_log.csv"))
        _atomic_df(sp, _p("splits.parquet"))
        _atomic_df(meta, _p("meta.parquet"))
        summ = {"dates": nd, "tickers": nt, "latest": str(pd.Timestamp(latest).date()), "log_rows": len(logs),
                "splits": len(sp), "nongenuine_splits": int((~sp["genuine"]).sum()), "seconds": round(time.time() - t0, 1)}
        log.info("rebuild done: %s", summ)
        _splits_cache.clear()
        return summ


def _merge_meta(meta: pd.DataFrame, att: pd.DataFrame, sp: pd.DataFrame, latest) -> pd.DataFrame:
    """Add status/note/attempt info; tickers without a price matrix column come from the ledger."""
    att = att.reset_index()
    spn = sp.groupby("yf_ticker").agg(n_splits=("ratio", "size"), n_nongenuine_splits=("genuine", lambda s: int((~s).sum())))
    m = att.merge(meta, on="yf_ticker", how="outer")
    m = m.merge(spn, left_on="yf_ticker", right_index=True, how="left")
    m["n_obs"] = m["n_obs"].fillna(0).astype("int64")
    for c in ("n_splits", "n_nongenuine_splits", "max_gap_days", "n_attempts"):
        m[c] = m[c].fillna(0).astype("int64")
    status = m["status"].fillna("ok")
    note = m["note"].fillna("")
    has = m["n_obs"] > 0
    status = status.where(~(has & (status != "ok")), "ok")
    lost = (~has) & (status == "ok")
    status = status.where(~lost, "empty")
    note = note.where(~lost, "no valid rows after cleaning")
    notes = []
    for st, nt_, hs, ld, gap, ng in zip(status, note, has, m["last_date"], m["max_gap_days"], m["n_nongenuine_splits"]):
        parts = [nt_] if nt_ else []
        if hs:
            if pd.Timestamp(latest) - ld > pd.Timedelta(days=ACTIVE_DAYS):
                parts.append(f"inactive since {ld.date()}")
            if gap > 45:
                parts.append(f"gap {gap}d")
            if ng:
                parts.append(f"{ng} non-genuine split(s)")
        notes.append("; ".join(parts))
    m["status"], m["note"] = status, notes
    m["last_attempt"] = m["last_attempt"].fillna("")
    cols = ["yf_ticker", "first_date", "last_date", "n_obs", "status", "note", "max_gap_days", "n_splits",
            "n_nongenuine_splits", "n_attempts", "last_attempt"]
    m = m[cols].sort_values("yf_ticker").reset_index(drop=True)
    for c in ("first_date", "last_date"):
        m[c] = pd.to_datetime(m[c]).astype("datetime64[ns]")
    return m


def _flag_late_starts(meta: pd.DataFrame) -> pd.DataFrame:
    """Best effort ticker-reuse flag: price history that begins well AFTER the ticker's first S&P membership."""
    path = settings.UNIV_DIR / "membership.parquet"
    if not path.exists():
        return meta
    try:
        mem = pd.read_parquet(path, columns=["snapshot_date", "yf_ticker"])
        first = mem.groupby("yf_ticker")["snapshot_date"].min()
        first.index = first.index.astype("str")
        f = meta["yf_ticker"].map(first)
        late = meta["first_date"].notna() & f.notna() & (meta["first_date"] > pd.to_datetime(f) + pd.Timedelta(days=45))
        meta.loc[late, "note"] = (meta.loc[late, "note"] + "; late_start(first_price=" +
                                  meta.loc[late, "first_date"].dt.strftime("%Y-%m-%d") + ", member_since=" +
                                  pd.to_datetime(f[late]).dt.strftime("%Y-%m-%d") + ")").str.lstrip("; ")
    except Exception as e:
        log.warning("late-start flag skipped: %s", e)
    return meta


# --------------------------------------------------------------------------------------
# risk-free
# --------------------------------------------------------------------------------------
FRED_URL = "https://fred.stlouisfed.org/graph/fredgraph.csv?id=DTB3"


def _fetch_dtb3(retries: int = 3) -> pd.Series | None:
    import io

    import requests

    for k in range(retries):
        try:
            # NB: FRED stalls requests carrying a custom User-Agent; the default one answers in 0.1s.
            r = requests.get(FRED_URL, timeout=(10, 40))
            r.raise_for_status()
            df = pd.read_csv(io.StringIO(r.text))
            dcol, vcol = df.columns[0], df.columns[1]
            s = pd.Series(pd.to_numeric(df[vcol], errors="coerce").to_numpy() / 100.0,
                          index=pd.to_datetime(df[dcol]).astype("datetime64[ns]")).dropna()
            if len(s) > 1000:
                return s
        except Exception as e:
            log.warning("FRED DTB3 attempt %d failed: %s", k + 1, e)
            time.sleep(2 * (k + 1))
    return None


def _fetch_irx(start: str = START_DEFAULT) -> pd.Series | None:
    import yfinance as yf

    try:
        d = yf.download("^IRX", start=start, auto_adjust=False, progress=False, multi_level_index=False)
        s = d["Close"].dropna() / 100.0
        s.index = pd.DatetimeIndex(s.index).tz_localize(None).astype("datetime64[ns]")
        return s
    except Exception as e:
        log.warning("^IRX download failed: %s", e)
        return None


def build_rf(index: pd.DatetimeIndex | None = None) -> pd.DataFrame:
    """rf.parquet: FRED DTB3 (3m T-bill, decimal) with the days after its last observation filled from ^IRX, forward
    filled onto the trading-day index (default: the close matrix dates); rf_daily = rf_annual / 252."""
    with _lock():
        if index is None:
            index = load_close(tickers=["SPY"]).index
        dtb3 = _fetch_dtb3()
        irx = _fetch_irx()
        if dtb3 is None and irx is None:
            raise RuntimeError("neither FRED DTB3 nor ^IRX could be downloaded")
        if dtb3 is None:
            src, series = "^IRX", irx
        else:
            series = dtb3
            src = "FRED DTB3"
            if irx is not None:
                extra = irx[irx.index > dtb3.index.max()]
                if len(extra):
                    series = pd.concat([dtb3, extra])
                    src = f"FRED DTB3 + ^IRX after {dtb3.index.max().date()}"
        series = series[~series.index.duplicated(keep="last")].sort_index()
        full = series.reindex(series.index.union(index)).ffill()
        rf = full.reindex(index)
        rf = rf.bfill()
        out = pd.DataFrame({"date": index.astype("datetime64[ns]"), "rf_annual": rf.to_numpy(),
                            "rf_daily": rf.to_numpy() / RF_DIVISOR})
        _atomic_df(out, _p("rf.parquet"))
        _atomic_text(json.dumps({"source": src, "last_observation": str(series.index.max().date()),
                                 "fetched_at": _now_iso(), "divisor": RF_DIVISOR}, indent=1), _p("rf_info.json"))
        log.info("rf: %s, last obs %s, %d days", src, series.index.max().date(), len(out))
        return out.set_index("date")


# --------------------------------------------------------------------------------------
# loaders
# --------------------------------------------------------------------------------------
def _load_wide(name: str, tickers: Sequence[str] | None = None, start=None, end=None) -> pd.DataFrame:
    path = _p(f"{name}.parquet")
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run `python -m quant.data.prices download`")
    cols = None
    if tickers is not None:
        have = set(pq.ParquetFile(path).schema_arrow.names)
        cols = ["date"] + [t for t in _norm_list(tickers) if t in have and t != "date"]
    df = pq.read_table(path, columns=cols).to_pandas()
    df["date"] = df["date"].astype("datetime64[ns]")
    df = df.set_index("date")
    if start is not None or end is not None:
        df = df.loc[start:end]
    return df


def load_close(tickers=None, start=None, end=None) -> pd.DataFrame:
    """Split-adjusted (not dividend-adjusted) close; date x yf_ticker."""
    return _load_wide("close", tickers, start, end)


def load_adjclose(tickers=None, start=None, end=None) -> pd.DataFrame:
    """Split + dividend adjusted close."""
    return _load_wide("adjclose", tickers, start, end)


def load_open(tickers=None, start=None, end=None) -> pd.DataFrame:
    return _load_wide("open", tickers, start, end)


def load_volume(tickers=None, start=None, end=None) -> pd.DataFrame:
    return _load_wide("volume", tickers, start, end)


def load_returns(tickers=None, start=None, end=None) -> pd.DataFrame:
    """Daily total returns (decimal) from adjclose, cleaned (R5-R7). NaN = no valid return."""
    if _p("returns.parquet").exists():
        return _load_wide("returns", tickers, start, end)
    return compute_returns(load_adjclose(tickers, start, end))


def load_splits() -> pd.DataFrame:
    """yf_ticker, date, ratio, genuine."""
    df = pd.read_parquet(_p("splits.parquet"))
    df["date"] = df["date"].astype("datetime64[ns]")
    return df


def load_meta() -> pd.DataFrame:
    return pd.read_parquet(_p("meta.parquet"))


def load_rf() -> pd.DataFrame:
    """DataFrame indexed by trading date with rf_annual (decimal) and rf_daily (= rf_annual / 252)."""
    df = pd.read_parquet(_p("rf.parquet"))
    df["date"] = df["date"].astype("datetime64[ns]")
    return df.set_index("date")


def rf_daily() -> pd.Series:
    return load_rf()["rf_daily"]


# --------------------------------------------------------------------------------------
# split factors
# --------------------------------------------------------------------------------------
_OFFSET = 400_000          # days; keeps (code, day) keys non-negative
_BIG = 1 << 21
_splits_cache: dict = {}


class _SplitIndex:
    def __init__(self, df: pd.DataFrame):
        df = df.sort_values(["yf_ticker", "date"]).reset_index(drop=True)
        self.code_of = {t: i for i, t in enumerate(pd.unique(df["yf_ticker"]))}
        code = df["yf_ticker"].map(self.code_of).to_numpy(dtype="int64")
        day = df["date"].to_numpy().astype("datetime64[D]").astype("int64") + _OFFSET
        self.keys = code * _BIG + day
        self.code = code
        suf = df.iloc[::-1].groupby(code[::-1])["ratio"].cumprod().iloc[::-1]
        self.suffix = suf.to_numpy(dtype="float64")


def _split_index(genuine_only: bool) -> _SplitIndex:
    path = _p("splits.parquet")
    stamp = (path.stat().st_mtime_ns, str(path), genuine_only) if path.exists() else (None, str(path), genuine_only)
    hit = _splits_cache.get("idx")
    if hit is not None and hit[0] == stamp:
        return hit[1]
    if path.exists():
        sp = load_splits()
    else:
        sp = pd.DataFrame({"yf_ticker": pd.Series(dtype="str"), "date": pd.Series(dtype="datetime64[ns]"),
                           "ratio": pd.Series(dtype="float64"), "genuine": pd.Series(dtype="bool")})
    if genuine_only:
        sp = sp[sp["genuine"]]
    idx = _SplitIndex(sp)
    _splits_cache["idx"] = (stamp, idx)
    return idx


def split_factors_after(tickers, dates, genuine_only: bool = True) -> np.ndarray:
    """Vectorised: for each (ticker, date) pair the product of split ratios with ex-date STRICTLY after ``date``
    (1.0 if none or ticker unknown; NaN if the date is missing). ``tickers`` and ``dates`` are array-likes of equal
    length; either may be a scalar (broadcast). genuine_only=True uses only genuine splits (share-count factor);
    False includes Yahoo's fractional spin-off adjustments (factor that undoes all price adjustments)."""
    tk = np.atleast_1d(np.asarray(tickers, dtype=object))
    dd = pd.DatetimeIndex(pd.to_datetime(pd.Index(np.atleast_1d(np.asarray(dates, dtype=object))))).astype("datetime64[ns]")
    tk, dd = np.broadcast_arrays(tk, np.asarray(dd.values))
    idx = _split_index(genuine_only)
    codes = np.array([idx.code_of.get(normalize_ticker(t) or "", -1) for t in tk], dtype="int64")
    nat = np.isnat(dd)
    day = np.where(nat, 0, dd.astype("datetime64[D]").astype("int64")) + _OFFSET
    out = np.ones(len(codes), dtype="float64")
    if len(idx.keys):
        q = codes * _BIG + day
        i = np.searchsorted(idx.keys, q, side="right")
        ic = np.minimum(i, len(idx.keys) - 1)
        has = (codes >= 0) & (i < len(idx.keys)) & (idx.code[ic] == codes)
        out = np.where(has, idx.suffix[ic], 1.0)
    out = np.where(nat, np.nan, out)
    return out


def split_factor_after(ticker: str, date, genuine_only: bool = True) -> float:
    """Product of split ratios with ex-date strictly after ``date`` (1.0 if none)."""
    return float(split_factors_after([ticker], [date], genuine_only=genuine_only)[0])


# --------------------------------------------------------------------------------------
# audit report
# --------------------------------------------------------------------------------------
def _md_table(df: pd.DataFrame) -> str:
    def cell(v):
        if isinstance(v, (pd.Timestamp, np.datetime64)):
            return str(pd.Timestamp(v).date())
        if isinstance(v, float):
            return f"{v:.6g}"
        return str(v).replace("|", "/")

    rows = ["| " + " | ".join(map(str, df.columns)) + " |", "|" + "---|" * len(df.columns)]
    rows += ["| " + " | ".join(cell(v) for v in r) + " |" for r in df.itertuples(index=False, name=None)]
    return "\n".join(rows)


def _human(n: float) -> str:
    for u in ("B", "KB", "MB", "GB"):
        if n < 1024 or u == "GB":
            return f"{n:.1f} {u}" if u != "B" else f"{int(n)} B"
        n /= 1024
    return str(n)


def _pit_members(date) -> tuple[dict | None, str]:
    """PIT index members at ``date`` -> ({index_name: (tickers_with_symbol, n_members_total)}, source).
    Uses quant.data.universe.members (one row per company; rows with a null yf_ticker have no safe Yahoo symbol and
    count as members without price data), else cache/universe/membership.parquet directly. (None, '') if neither."""
    idxs = ("SP500", "SP400", "SP600")
    try:
        from quant.data import universe

        out = {}
        for ix in idxs:
            res = universe.members(pd.Timestamp(date), indexes=(ix,))
            col = res["yf_ticker"] if "yf_ticker" in res.columns else pd.Series(dtype="object")
            out[ix] = ([str(x) for x in col.dropna().unique()], int(len(res)))
        return out, "quant.data.universe.members"
    except Exception as e:
        log.debug("universe.members unavailable: %s", e)
    path = settings.UNIV_DIR / "membership.parquet"
    if path.exists():
        try:
            m = pd.read_parquet(path, columns=["snapshot_date", "index", "yf_ticker"])
            m = m[m["snapshot_date"] <= pd.Timestamp(date)]
            out = {}
            for ix in idxs:
                mi = m[m["index"] == ix]
                if mi.empty:
                    out[ix] = ([], 0)
                    continue
                mi = mi[mi["snapshot_date"] == mi["snapshot_date"].max()]
                out[ix] = ([str(x) for x in mi["yf_ticker"].dropna().unique()], int(len(mi)))
            return out, "cache/universe/membership.parquet"
        except Exception as e:
            log.warning("membership read failed: %s", e)
    f = settings.UNIV_DIR / "fja05680" / "sp500_hist_updated.csv"        # provisional: S&P 500 only
    if f.exists():
        try:
            h = pd.read_csv(f)
            h["date"] = pd.to_datetime(h["date"])
            h = h[h["date"] <= pd.Timestamp(date)]
            if len(h):
                tks = [normalize_ticker(t) for t in h["tickers"].iloc[-1].split(",")]
                tks = [t for t in tks if t]
                return {"SP500": (tks, len(tks)), "SP400": ([], 0), "SP600": ([], 0)}, "cache/universe/fja05680/sp500_hist_updated.csv (S&P 500 only; provisional)"
        except Exception as e:
            log.warning("fja membership read failed: %s", e)
    return None, ""


def _cagr(s: pd.Series) -> float:
    s = s.dropna()
    yrs = (s.index[-1] - s.index[0]).days / 365.25
    return float((s.iloc[-1] / s.iloc[0]) ** (1 / yrs) - 1)


def audit(path: Path | None = None) -> str:
    """Validation + coverage report -> output/data_audit/price_coverage.md. Returns the markdown."""
    path = Path(path) if path else AUDIT_PATH
    meta = load_meta()
    sp = load_splits()
    close = load_close()
    adj = load_adjclose()
    ret = load_returns()
    latest = close.index[-1]
    L: list[str] = []
    w = L.append
    chk: list[tuple[str, bool, str]] = []

    w("# Price coverage and validation (Yahoo Finance via yfinance)\n")
    w(f"Generated {dt.datetime.now().strftime('%Y-%m-%d %H:%M')} by `quant/data/prices.py` (`python -m quant.data.prices audit`). "
      f"Source of truth: `cache/prices/raw/`; derived matrices in `cache/prices/`.\n")

    # ---- 1. counts
    vc = meta["status"].value_counts()
    ok = meta[meta["status"] == "ok"]
    w("## 1. Download status\n")
    w(f"* Tickers attempted: **{len(meta):,}**; ok **{int(vc.get('ok', 0)):,}**, empty **{int(vc.get('empty', 0)):,}** "
      f"(Yahoo has nothing: delisted/renamed), error **{int(vc.get('error', 0)):,}** (transient failures after retries).")
    w(f"* Matrix: **{close.shape[0]:,} trading days x {close.shape[1]:,} tickers**, "
      f"{close.index[0].date()} .. **{latest.date()}** (latest bar).")
    stale = ok[ok["last_date"] < latest - pd.Timedelta(days=ACTIVE_DAYS)]
    w(f"* Still trading (last bar within {ACTIVE_DAYS} days of the latest): {len(ok) - len(stale):,}; "
      f"stopped trading / delisted but still on Yahoo: {len(stale):,}.")
    w(f"* History length of ok tickers (trading days): median {int(ok['n_obs'].median()):,}, "
      f"p10 {int(ok['n_obs'].quantile(.1)):,}, p90 {int(ok['n_obs'].quantile(.9)):,}; full 2007 start: "
      f"{int((ok['first_date'] <= pd.Timestamp('2007-01-10')).sum()):,}.")
    err = meta[meta["status"] == "error"]
    if len(err):
        w(f"* Error tickers (first 30): {', '.join(err['yf_ticker'].head(30))}")
    w("")
    w("Files:\n")
    w("| file | size |\n|---|---|")
    for name in ["close", "adjclose", "open", "volume", "returns", "splits", "meta", "rf"]:
        f = _p(f"{name}.parquet")
        if f.exists():
            w(f"| `cache/prices/{name}.parquet` | {_human(f.stat().st_size)} |")
    raw = sum(f.stat().st_size for f in _raw_dir().glob("*.parquet"))
    w(f"| `cache/prices/raw/` (long source of truth) | {_human(raw)} |")
    f = _p("cleaning_log.csv")
    if f.exists():
        w(f"| `cache/prices/cleaning_log.csv` | {_human(f.stat().st_size)} |")
    w("")

    # ---- 2. validation
    w("## 2. Validation\n")
    # splits
    for tk, d, ratio in (("AAPL", "2020-08-31", 4.0), ("NVDA", "2024-06-10", 10.0)):
        row = sp[(sp["yf_ticker"] == tk) & (sp["date"] == pd.Timestamp(d))]
        okk = len(row) == 1 and abs(row["ratio"].iloc[0] - ratio) < 1e-9 and bool(row["genuine"].iloc[0])
        before = close[tk].loc[:pd.Timestamp(d) - pd.Timedelta(days=1)].dropna().iloc[-1]
        on = close[tk].loc[pd.Timestamp(d)]
        jump = on / before - 1
        chk.append((f"{tk} {ratio:g}:1 split on {d} in splits.parquet", okk, f"found={len(row) == 1}"))
        chk.append((f"{tk} close continuous across split (|1-day move| < 15%)", abs(jump) < 0.15,
                    f"close {before:.2f} -> {on:.2f} ({jump:+.1%}); unadjusted would be {before * ratio:.2f} -> {on:.2f}"))
    for tk, d, expect in (("NVDA", "2024-01-01", 10.0), ("AAPL", "2019-01-01", 4.0), ("AAPL", "2013-01-01", 28.0),
                          ("NVDA", "2025-01-01", 1.0), ("AAPL", "2020-08-31", 1.0), ("AAPL", "2020-08-28", 4.0)):
        v = split_factor_after(tk, d)
        chk.append((f"split_factor_after('{tk}', '{d}') == {expect:g}", abs(v - expect) < 1e-9, f"got {v:g}"))
    vv = split_factors_after(["NVDA", "AAPL", "ZZZZ"], ["2024-01-01", "2019-01-01", "2020-01-01"])
    chk.append(("split_factors_after vectorised (NVDA, AAPL, unknown)", np.allclose(vv, [10, 4, 1]), str(vv.tolist())))
    # adj <= close for dividend payers
    payers = [t for t in ("KO", "JNJ", "PG", "XOM", "MSFT", "PEP", "WMT", "MCD", "SPY", "T") if t in close.columns]
    viol = {}
    for t in payers:
        r = (adj[t] / close[t]).dropna()
        viol[t] = float((r > 1 + 1e-6).mean())
    chk.append(("Adj Close <= Close for dividend payers (share of days violating)", max(viol.values()) < 0.001,
                ", ".join(f"{t} {v:.2%}" for t, v in viol.items())))
    last_ratio = {t: float((adj[t] / close[t]).dropna().iloc[-1]) for t in payers}
    chk.append(("Adj/Close ratio is 1 at the latest bar and shrinks into the past",
                all(abs(v - 1) < 1e-6 for v in last_ratio.values()), "latest adj/close = " +
                ", ".join(f"{t} {v:.6f}" for t, v in last_ratio.items())))
    # SPY CAGR
    spy = adj["SPY"].loc["2014-12-31":"2024-12-31"].dropna()
    cagr = _cagr(spy)
    chk.append(("SPY total-return CAGR 2015-01-01..2024-12-31 within 0.5%/yr of ~13%", abs(cagr - 0.13) < 0.005,
                f"{cagr:.2%} (adjclose {spy.index[0].date()} -> {spy.index[-1].date()}); price-only {_cagr(close['SPY'].loc['2014-12-31':'2024-12-31']):.2%}"))
    # rf
    rf = load_rf()
    info = json.loads(_p("rf_info.json").read_text()) if _p("rf_info.json").exists() else {}
    chk.append(("rf covers every trading day through the latest price date",
                bool((rf.index == close.index).all()) and rf["rf_annual"].notna().all(),
                f"{info.get('source', '?')}; last observation {info.get('last_observation', '?')}; latest rf_annual {rf['rf_annual'].iloc[-1]:.4f} ({rf['rf_daily'].iloc[-1]:.6f}/day)"))
    chk.append(("latest bar is Fri 2026-10-16 (expected as of Sun 2026-10-18)", latest >= pd.Timestamp("2026-10-16"), f"latest = {latest.date()} ({latest.day_name()})"))
    # matrix integrity
    pos = bool(((close.to_numpy() > 0) | np.isnan(close.to_numpy())).all() and ((adj.to_numpy() > 0) | np.isnan(adj.to_numpy())).all())
    chk.append(("no non-positive prices in close/adjclose", pos, ""))
    chk.append(("index unique, sorted, datetime64[ns]; columns unique", close.index.is_unique and close.index.is_monotonic_increasing
                and str(close.index.dtype) == "datetime64[ns]" and close.columns.is_unique, str(close.index.dtype)))
    w("| check | result | detail |\n|---|---|---|")
    for name, okk, det in chk:
        w(f"| {name} | {'PASS' if okk else '**FAIL**'} | {det} |")
    w("")

    # ---- 3. splits
    w("## 3. Splits\n")
    ng = sp[~sp["genuine"]]
    w(f"{len(sp):,} split events in {sp['yf_ticker'].nunique():,} tickers; **{len(ng)} non-genuine** (ratio not within 0.5% of a simple fraction "
      f"p/q with p,q<=20 or of N / 1/N: Yahoo spin-off adjustments). `split_factor_after` ignores them by default; "
      f"`genuine_only=False` includes them.\n")
    small = ng[(ng["ratio"] > 0.9) & (ng["ratio"] < 1.1)]
    large = ng.drop(small.index)
    w(f"{len(small)} of them are small stock dividends / distributions (ratio within 10% of 1, e.g. "
      + ", ".join(f"{r.yf_ticker} {r.ratio:g}" for _, r in small.drop_duplicates('yf_ticker').head(6).iterrows())
      + f"); the other {len(large)} are listed below (full list: filter `genuine == False` in `splits.parquet`).\n")
    if len(large):
        w("| ticker | date | ratio |\n|---|---|---|")
        for _, r in large.sort_values(["yf_ticker", "date"]).iterrows():
            w(f"| {r.yf_ticker} | {r.date.date()} | {r.ratio:.6g} |")
        w("")
    big = sp[sp["genuine"] & ((sp["ratio"] > 20) | (sp["ratio"] < 1 / 20))]
    if len(big):
        w(f"Genuine splits beyond 20:1 / 1:20 (accepted by the N / 1/N rule): "
          + ", ".join(f"{r.yf_ticker} {r.date.date()} {r.ratio:g}" for _, r in big.head(40).iterrows()) + (" ..." if len(big) > 40 else "") + "\n")

    # ---- 4. cleaning
    w("## 4. Cleaning log\n")
    f = _p("cleaning_log.csv")
    if f.exists():
        cl = pd.read_csv(f)
        if len(cl):
            w(_md_table(cl.groupby(["rule", "field"]).size().rename("rows").reset_index()))
            w("")
            bt = cl[cl["rule"] == "R5_bad_tick"]
            if len(bt):
                w(f"Bad-tick spikes removed (R5): {len(bt)} price cells in {bt['yf_ticker'].nunique()} tickers. First 15 rows (all rows: `cache/prices/cleaning_log.csv`):\n")
                w(_md_table(bt.head(15)))
                w("")
        else:
            w("No cells changed.\n")
    rr = ret.to_numpy()
    n_big = int((np.abs(rr) > 1.0).sum())
    w(f"After cleaning: {int(np.isfinite(rr).sum()):,} daily returns; |return| > 100%: {n_big:,}; > 300%: {int((np.abs(rr) > 3).sum()):,}. "
      f"Non-reverting extremes are NOT altered (genuine events or unflagged Yahoo errors). Top 15 by |return|:\n")
    flat = pd.DataFrame({"ret": ret.stack().to_numpy()}, index=ret.stack().index) if n_big < 5_000_000 else None
    if flat is not None:
        top = flat.reindex(flat["ret"].abs().sort_values(ascending=False).index).head(15)
        w("| ticker | date | return |\n|---|---|---|")
        for (d, t), r in top["ret"].items():
            w(f"| {t} | {d.date()} | {r:+,.0%} |")
        w("")

    # dividend anomalies (Yahoo mis-scaled dividends corrupt Adj Close)
    try:
        t = pq.read_table(_raw_dir() / "base.parquet", columns=["yf_ticker", "date", "close", "dividend"],
                          filters=[("dividend", ">", 0)]).to_pandas()
        t["yld"] = t["dividend"] / t["close"]
        an = t[t["yld"] > 0.3].sort_values("yld", ascending=False)
        w(f"Suspicious dividends (cash dividend > 30% of the close on the ex-date, likely mis-scaled by Yahoo, distort that day's total return): "
          f"{len(an)} events in {an['yf_ticker'].nunique()} tickers" + (": " + ", ".join(f"{r.yf_ticker} {r.date.date()} ({r.yld:.0%})" for r in an.head(20).itertuples()) if len(an) else "") + ".\n")
    except Exception as e:
        log.warning("dividend audit skipped: %s", e)

    # ---- 5. survivorship coverage
    w("## 5. Survivorship coverage (PIT S&P 1500 members with price data at each year-end)\n")
    rows, src_used = [], ""
    ye_dates = []
    for y in range(2010, latest.year + 1):
        cand = close.index[close.index <= pd.Timestamp(f"{y}-12-31")]
        if len(cand) == 0:
            continue
        ye_dates.append(cand[-1] if y < latest.year else latest)
    for d in ye_dates:
        mem, src = _pit_members(d)
        if mem is None:
            continue
        src_used = src
        has = close.loc[:d].iloc[-6:].notna().any(axis=0)        # priced on that day or within the previous 5 bars
        rec = {"date": d, "avail": int(close.loc[d].notna().sum())}
        tot_n = tot_g = 0
        for ix, (tks, n_total) in mem.items():
            got = sum(1 for t in set(tks) if t in has.index and bool(has[t]))
            rec[ix] = (n_total, got)
            tot_n += n_total
            tot_g += got
        rec["ALL"] = (tot_n, tot_g)
        rows.append(rec)
    if rows:
        w(f"Membership source: `{src_used}`. A member counts as covered if its `close` is non-NaN on the year-end date "
          f"(or any of the previous 5 bars). Members whose Yahoo symbol is unknown/unsafe (ticker re-use nulled by the universe builder) "
          f"are in the denominator and count as not covered. Cells show `covered/members (share)`.\n")
        w("| year-end | S&P 1500 | S&P 500 | S&P 400 | S&P 600 | tickers with a price that day |\n|---|---|---|---|---|---|")
        def cell(t):
            n, g = t
            return f"{g:,}/{n:,} ({g / n:.1%})" if n else "n/a"
        for r in rows:
            w(f"| {r['date'].date()} | **{cell(r['ALL'])}** | {cell(r['SP500'])} | {cell(r['SP400'])} | {cell(r['SP600'])} | {r['avail']:,} |")
        w("")
    else:
        w("PIT membership is not available yet (`quant.data.universe.members` / `cache/universe/membership.parquet` missing); "
          "rerun `python -m quant.data.prices audit` after the universe is built.\n")
        lst = read_price_tickers()
        if lst:
            st = meta.set_index("yf_ticker")["status"]
            w(f"Fallback on `price_tickers.txt` ({len(lst):,} tickers, no dates): ok {int((st.reindex(lst) == 'ok').sum()):,}, "
              f"empty {int((st.reindex(lst) == 'empty').sum()):,}, error {int((st.reindex(lst) == 'error').sum()):,}, "
              f"not attempted {int(st.reindex(lst).isna().sum()):,}.\n")
    # late starts
    ls = meta[meta["note"].str.contains("late_start", na=False)]
    w(f"**Ticker-reuse suspects** (price history starts >45 days after the ticker's first S&P membership): {len(ls)}.")
    if len(ls):
        w("\n" + ", ".join(f"{r.yf_ticker} (first price {r.first_date.date()})" for r in ls.head(60).itertuples()) + (" ..." if len(ls) > 60 else ""))
    gaps = ok[ok["max_gap_days"] > 45]
    w(f"\nTickers with an internal gap > 45 calendar days (possible recycled symbol): {len(gaps)}"
      + (": " + ", ".join(f"{r.yf_ticker} ({r.max_gap_days}d)" for r in gaps.head(40).itertuples()) if len(gaps) else "") + "\n")

    # ---- 6. caveats / refresh
    w("## 6. Caveats\n")
    w("* Yahoo has **no history for most delisted/acquired companies** (status `empty`); the available universe is survivor-biased. "
      "Benchmark against the equal-weight return of the same available universe (research/05_data_sources.md section 4.4).")
    w("* Ticker reuse: some symbols (FB, S, SE, STI ...) return another company's prices. The universe builder is responsible for nulling those; "
      "`meta.note` flags `late_start(...)` and long gaps as hints.")
    w("* `Adj Close` is re-based by Yahoo after every dividend: never append to a cached adjclose history. `update()` detects this and re-downloads "
      "the affected tickers.")
    w("* Volume is as quoted by Yahoo (split-adjusted share count). Prices are rounded float32-like values as served by Yahoo.\n")
    w("## 7. Refresh (Tuesday 2026-10-20 evening, after the 16:00 ET close)\n")
    w("```\n.venv/bin/python -m quant.data.prices update      # window re-download, re-base check, rebuild, rf\n"
      ".venv/bin/python -m quant.data.prices audit       # regenerate this report\n```")
    text = "\n".join(L) + "\n"
    _atomic_text(text, path)
    return text


# --------------------------------------------------------------------------------------
# status + CLI
# --------------------------------------------------------------------------------------
def status() -> dict:
    att = _load_attempts()
    vc = att["status"].value_counts().to_dict() if len(att) else {}
    want = default_tickers()
    return {"attempted": len(att), **{k: int(v) for k, v in vc.items()}, "default_list": len(want),
            "pending": len(_pending(want, att, False, False)), "segments": len(_list_segments())}


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(prog="python -m quant.data.prices", description=__doc__.split("\n")[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    d = sub.add_parser("download", help="download tickers not yet attempted (resumable)")
    d.add_argument("--force", action="store_true")
    d.add_argument("--retry-empty", action="store_true")
    d.add_argument("--max-tickers", type=int)
    d.add_argument("--batch-size", type=int, default=BATCH_SIZE)
    d.add_argument("--sleep", type=float, default=SLEEP_BETWEEN)
    d.add_argument("--no-rebuild", action="store_true")
    d.add_argument("--tickers", nargs="*")
    u = sub.add_parser("update", help="append latest bars (run after the close)")
    u.add_argument("--through")
    u.add_argument("--no-new", action="store_true")
    u.add_argument("--keep-partial", action="store_true")
    sub.add_parser("rebuild", help="rebuild matrices/meta/splits from the raw store")
    sub.add_parser("rf", help="refresh risk-free (FRED DTB3 + ^IRX)")
    sub.add_parser("audit", help="write output/data_audit/price_coverage.md")
    sub.add_parser("status", help="ledger summary")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(message)s", datefmt="%H:%M:%S")
    if a.cmd == "download":
        print(download(a.tickers, force=a.force, retry_empty=a.retry_empty, max_tickers=a.max_tickers,
                       batch_size=a.batch_size, sleep=a.sleep, rebuild=not a.no_rebuild))
    elif a.cmd == "update":
        print(update(a.through, include_new=not a.no_new, drop_partial=not a.keep_partial))
    elif a.cmd == "rebuild":
        print(rebuild_outputs())
    elif a.cmd == "rf":
        print(build_rf().tail())
    elif a.cmd == "audit":
        audit()
        print(f"wrote {AUDIT_PATH}")
    elif a.cmd == "status":
        print(status())


if __name__ == "__main__":
    main()
