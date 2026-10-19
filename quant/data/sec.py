"""SEC EDGAR bulk data -> parquet caches.

Inputs (already downloaded, never modified here):
    cache/sec/companyfacts.zip   one ``CIK##########.json`` per filer (XBRL "company facts")
    cache/sec/submissions.zip    ``CIK##########.json`` (+ overflow ``CIK##########-submissions-NNN.json``)

Outputs (schemas in quant/ARCHITECTURE.md):
    cache/sec/facts/part-XX.parquet   64 partitions by ``cik % 64``; long format, one row per
                                      (cik, tag, unit, start, end, filed, accn) fact
    cache/sec/companies.parquet       one row per CIK in companyfacts
    cache/sec/filings.parquet         selected form types (10-K/10-Q/8-K/S-1/25/15-12B/...)

Public API
    TAGS                                   registry taxonomy -> tags that are kept
    build_facts(force=False, n_jobs=8)     -> Path of the facts directory
    build_companies(force=False)           -> Path
    build_filings(force=False)             -> Path
    load_facts(ciks=None, tags=None, columns=None) -> pd.DataFrame
    load_companies() / load_filings(forms=None) / cik_to_partition(cik)

Design notes
    * The zips are streamed: every worker process opens the zip itself and handles a list of member
      names, nothing is ever extracted or held in RAM as a whole.
    * facts: one task per output partition (all CIKs with ``cik % 64 == p``), so each worker writes its
      partition file directly (tmp file + atomic rename); no shard concatenation is needed.
    * Low-cardinality string columns (taxonomy, tag, unit, form, fp) are stored as arrow dictionary
      columns with *global fixed dictionaries*, so they load as pandas ``category`` with identical
      categories in every partition.
    * Rows inside a partition are sorted by (cik, tag, unit, end, start, filed) and written in row
      groups of 250k rows, so the parquet min/max statistics prune cik filters effectively.
    * Idempotent: a partition is skipped if it already exists with the same build signature (hash of
      TAGS/units/forms/schema/zip fingerprint); ``force=True`` rebuilds everything.
"""
from __future__ import annotations

import argparse
import hashlib
import json
import logging
import multiprocessing as mp
import os
import re
import time
import zipfile
from collections import Counter
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from quant.settings import SEC_DIR

log = logging.getLogger(__name__)

# --------------------------------------------------------------------------------------
# Paths / constants
# --------------------------------------------------------------------------------------
COMPANYFACTS_ZIP = SEC_DIR / "companyfacts.zip"
SUBMISSIONS_ZIP = SEC_DIR / "submissions.zip"
FACTS_DIR = SEC_DIR / "facts"
COMPANIES_PATH = SEC_DIR / "companies.parquet"
FILINGS_PATH = SEC_DIR / "filings.parquet"

N_PARTS = 64
SCHEMA_VERSION = 1
ROW_GROUP_SIZE = 250_000
FLUSH_ROWS = 400_000          # worker converts python lists -> arrow every this many rows

UNITS = frozenset({"USD", "shares", "USD/shares", "pure"})
FORMS = frozenset({"10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "10-QT", "10-KT/A", "10-QT/A"})

# fixed dictionaries (global categories for the dictionary-encoded columns)
_TAXONOMY_LIST = ["us-gaap", "dei"]
_UNIT_LIST = ["USD", "shares", "USD/shares", "pure"]
_FORM_LIST = ["10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "10-QT", "10-KT/A", "10-QT/A"]
_FP_LIST = ["FY", "Q1", "Q2", "Q3", "Q4", "H1", "H2", "CY", "T1", "T2", "T3"]

# --------------------------------------------------------------------------------------
# Tag registry (taxonomy -> tag names kept). Order inside a group is only documentation; the
# fundamentals builder decides the actual fallback priority (see research/02 s6.1, 03 s5, 04 s5.2).
# --------------------------------------------------------------------------------------
TAGS: dict[str, list[str]] = {
    "us-gaap": [
        # --- revenue
        "RevenueFromContractWithCustomerExcludingAssessedTax",
        "Revenues",
        "SalesRevenueNet",
        "RevenueFromContractWithCustomerIncludingAssessedTax",
        "SalesRevenueGoodsNet",
        "SalesRevenueServicesNet",
        "RevenuesNetOfInterestExpense",
        "InterestIncomeExpenseNet",
        # --- cost of revenue / profit / opex
        "CostOfGoodsAndServicesSold",
        "CostOfRevenue",
        "CostOfGoodsSold",
        "CostOfServices",
        "CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization",
        "GrossProfit",
        "SellingGeneralAndAdministrativeExpense",
        "GeneralAndAdministrativeExpense",
        "SellingAndMarketingExpense",
        "ResearchAndDevelopmentExpense",
        "OperatingIncomeLoss",
        "CostsAndExpenses",
        "OperatingExpenses",
        "NonoperatingIncomeExpense",
        # --- earnings
        "NetIncomeLoss",
        "ProfitLoss",
        "NetIncomeLossAvailableToCommonStockholdersBasic",
        "NetIncomeLossAttributableToNoncontrollingInterest",
        "IncomeLossFromContinuingOperations",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
        "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments",
        "IncomeTaxExpenseBenefit",
        # --- interest
        "InterestExpense",
        "InterestExpenseNonoperating",
        "InterestExpenseDebt",
        "InterestAndDebtExpense",
        "InterestIncomeExpenseNonoperatingNet",
        "InvestmentIncomeInterest",
        # --- D&A
        "DepreciationDepletionAndAmortization",
        "DepreciationAndAmortization",
        "DepreciationAmortizationAndAccretionNet",
        "Depreciation",
        "AmortizationOfIntangibleAssets",
        # --- cash flow
        "NetCashProvidedByUsedInOperatingActivities",
        "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations",
        "PaymentsToAcquirePropertyPlantAndEquipment",
        "PaymentsToAcquireProductiveAssets",
        "PaymentsToAcquireOtherPropertyPlantAndEquipment",
        "PaymentsToAcquireOtherProductiveAssets",
        "PaymentsForCapitalImprovements",
        "PaymentsToAcquireOilAndGasPropertyAndEquipment",
        "PaymentsToAcquireOilAndGasProperty",
        "PaymentsToExploreAndDevelopOilAndGasProperties",
        "PaymentsForProceedsFromProductiveAssets",
        "PaymentsToAcquireBusinessesNetOfCashAcquired",
        "PaymentsOfDividends",
        "PaymentsOfDividendsCommonStock",
        "PaymentsForRepurchaseOfCommonStock",
        "ProceedsFromIssuanceOfCommonStock",
        "ShareBasedCompensation",
        "InterestPaidNet",
        "InterestPaid",
        "IncomeTaxesPaidNet",
        "IncomeTaxesPaid",
        # --- per share / share counts
        "EarningsPerShareDiluted",
        "EarningsPerShareBasic",
        "EarningsPerShareBasicAndDiluted",
        "CommonStockDividendsPerShareDeclared",
        "CommonStockDividendsPerShareCashPaid",
        "WeightedAverageNumberOfDilutedSharesOutstanding",
        "WeightedAverageNumberOfSharesOutstandingBasic",
        "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted",
        "CommonStockSharesOutstanding",
        "CommonStockSharesIssued",
        # --- balance sheet: totals, working capital
        "Assets",
        "AssetsCurrent",
        "LiabilitiesCurrent",
        "Liabilities",
        "LiabilitiesAndStockholdersEquity",
        "InventoryNet",
        "AccountsReceivableNetCurrent",
        "AccountsPayableCurrent",
        "TaxesPayableCurrent",
        "AccruedIncomeTaxesCurrent",
        # --- cash & investments
        "CashAndCashEquivalentsAtCarryingValue",
        "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents",
        "Cash",
        "ShortTermInvestments",
        "MarketableSecuritiesCurrent",
        "AvailableForSaleSecuritiesDebtSecuritiesCurrent",
        # --- fixed assets & intangibles
        "PropertyPlantAndEquipmentNet",
        "OilAndGasPropertySuccessfulEffortMethodNet",
        "OilAndGasPropertyFullCostMethodNet",
        "OilAndGasPropertySuccessfulEffortMethodGross",
        "OilAndGasPropertySuccessfulEffortMethodAccumulatedDepreciationDepletionAmortizationAndImpairment",
        "OilAndGasPropertyFullCostMethodGross",
        "OilAndGasPropertyFullCostMethodAccumulatedDepreciationDepletionAmortizationAndImpairment",
        "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization",
        "PropertyPlantAndEquipmentGross",
        "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment",
        "Goodwill",
        "IntangibleAssetsNetExcludingGoodwill",
        "OperatingLeaseRightOfUseAsset",
        # --- equity
        "StockholdersEquity",
        "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
        "MinorityInterest",
        "RedeemableNoncontrollingInterestEquityCarryingAmount",
        "PreferredStockValue",
        "PreferredStockValueOutstanding",
        "PreferredStockRedemptionAmount",
        "TemporaryEquityCarryingAmountAttributableToParent",
        "RetainedEarningsAccumulatedDeficit",
        # --- debt
        "LongTermDebt",
        "LongTermDebtNoncurrent",
        "LongTermDebtCurrent",
        "DebtCurrent",
        "ShortTermBorrowings",
        "CommercialPaper",
        "NotesPayableCurrent",
        "LineOfCreditCurrent",
        "ConvertibleNotesPayableCurrent",
        "LoansPayableCurrent",
        "LongTermDebtAndCapitalLeaseObligations",
        "LongTermDebtAndCapitalLeaseObligationsCurrent",
        "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities",
        "DebtAndCapitalLeaseObligations",
        "LongTermNotesPayable",
        "ConvertibleNotesPayable",
        "ConvertibleDebt",
        "ConvertibleDebtNoncurrent",
        "DebtLongtermAndShorttermCombinedAmount",
        "SeniorNotes",
        "LongTermLineOfCredit",
        "LineOfCredit",
        "SecuredDebt",
        "UnsecuredDebt",
        "NotesPayable",
        "LoansPayable",
        "OtherLongTermDebtNoncurrent",
        "OtherLongTermDebt",
        "SubordinatedDebt",
        "DebtInstrumentCarryingAmount",
        "ShortTermBankLoansAndNotesPayable",
        # --- leases
        "FinanceLeaseLiabilityCurrent",
        "FinanceLeaseLiabilityNoncurrent",
        "FinanceLeaseLiability",
        "CapitalLeaseObligationsCurrent",
        "CapitalLeaseObligationsNoncurrent",
        "CapitalLeaseObligations",
        "OperatingLeaseLiabilityCurrent",
        "OperatingLeaseLiabilityNoncurrent",
        "OperatingLeaseLiability",
    ],
    "dei": [
        "EntityCommonStockSharesOutstanding",
        "EntityPublicFloat",
    ],
}

_TAG_LIST: list[str] = [t for tags in TAGS.values() for t in tags]
if len(set(_TAG_LIST)) != len(_TAG_LIST):  # pragma: no cover - registry sanity
    raise ValueError("duplicate tag names in TAGS: %s" % [t for t, c in Counter(_TAG_LIST).items() if c > 1])
_TAG_IDX = {t: i for i, t in enumerate(_TAG_LIST)}
_TAX_IDX = {t: i for i, t in enumerate(_TAXONOMY_LIST)}
_UNIT_IDX = {t: i for i, t in enumerate(_UNIT_LIST)}


def _dict_type(index_type=pa.int8()) -> pa.DataType:
    return pa.dictionary(index_type, pa.string())


FACTS_SCHEMA = pa.schema(
    [
        pa.field("cik", pa.int64()),
        pa.field("taxonomy", _dict_type()),
        pa.field("tag", _dict_type(pa.int16())),
        pa.field("unit", _dict_type()),
        pa.field("start", pa.timestamp("ns")),
        pa.field("end", pa.timestamp("ns")),
        pa.field("val", pa.float64()),
        pa.field("filed", pa.timestamp("ns")),
        pa.field("form", _dict_type()),
        pa.field("fy", pa.float64()),
        pa.field("fp", _dict_type()),
        pa.field("accn", pa.string()),
    ]
)
FACTS_COLUMNS = FACTS_SCHEMA.names

# ----- submissions-derived tables
ANNUAL_FORMS = frozenset({"10-K", "10-K405", "10-KT"})     # original annual reports (no /A, no 10-KSB)
QUARTERLY_FORMS = frozenset({"10-Q", "10-QT"})              # original quarterly reports (no /A)

FILING_FORMS = [
    "10-K", "10-Q", "10-K/A", "10-Q/A", "10-KT", "10-QT", "8-K", "8-K/A", "S-1", "S-1/A", "F-1",
    "424B1", "424B4", "20-F", "40-F", "25", "25-NSE", "15-12B", "15-12G",
]
_FILING_FORM_SET = frozenset(FILING_FORMS)

FILINGS_SCHEMA = pa.schema(
    [
        pa.field("cik", pa.int64()),
        pa.field("accn", pa.string()),
        pa.field("form", _dict_type()),
        pa.field("filing_date", pa.timestamp("ns")),
        pa.field("report_date", pa.timestamp("ns")),
        pa.field("acceptance_datetime", pa.timestamp("ns")),   # UTC, tz-naive
        pa.field("items", pa.string()),
    ]
)

COMPANIES_SCHEMA = pa.schema(
    [
        pa.field("cik", pa.int64()),
        pa.field("name", pa.string()),
        pa.field("tickers", pa.string()),
        pa.field("exchanges", pa.string()),
        pa.field("sic", pa.int32()),
        pa.field("sic_description", pa.string()),
        pa.field("category", pa.string()),
        pa.field("fiscal_year_end", pa.string()),
        pa.field("entity_type", pa.string()),
        pa.field("state_of_inc", pa.string()),
        pa.field("first_filing_date", pa.timestamp("ns")),
        pa.field("n_10k", pa.int32()),
        pa.field("n_10q", pa.int32()),
        pa.field("former_names", pa.string()),
        pa.field("last_filing_date", pa.timestamp("ns")),            # extra: survivorship helper
        pa.field("last_periodic_filing_date", pa.timestamp("ns")),   # extra: last 10-K*/10-Q* of any kind
    ]
)


# --------------------------------------------------------------------------------------
# Small helpers
# --------------------------------------------------------------------------------------
_ZIP_CACHE: dict[str, zipfile.ZipFile] = {}


def _get_zip(path: str) -> zipfile.ZipFile:
    """Per-process cached ZipFile handle (each worker opens the zip itself)."""
    zf = _ZIP_CACHE.get(path)
    if zf is None:
        zf = zipfile.ZipFile(path)
        _ZIP_CACHE[path] = zf
    return zf


def _init_worker(*paths: str) -> None:
    for p in paths:
        _get_zip(p)


_CF_NAME = re.compile(r"^CIK(\d{10})\.json$")


def cik_to_partition(cik: int) -> int:
    """Partition number (0..63) holding the facts of ``cik``."""
    return int(cik) % N_PARTS


def _part_path(part: int) -> Path:
    return FACTS_DIR / f"part-{part:02d}.parquet"


def _to_ts(values: list) -> pa.Array:
    """list of 'YYYY-MM-DD' / ISO strings (None/'' allowed) -> timestamp[ns] arrow array.
    Unparseable / out-of-range values (e.g. typos like '0202-02-01' in SEC data) become null."""
    vals = [v or None for v in values]
    try:
        return pa.array(vals, type=pa.string()).cast(pa.timestamp("ns"))
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
        pass

    def _ok_year(v) -> bool:
        try:
            return v is not None and 1900 <= int(v[:4]) <= 2200
        except ValueError:
            return False

    vals = [v if _ok_year(v) else None for v in vals]
    try:
        return pa.array(vals, type=pa.string()).cast(pa.timestamp("ns"))
    except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
        pass
    out = []
    for v in vals:  # last resort: element-wise (month 13, day 45, ...)
        try:
            out.append(pa.scalar(v, type=pa.string()).cast(pa.timestamp("ns")).as_py() if v else None)
        except (pa.ArrowInvalid, pa.ArrowNotImplementedError):
            out.append(None)
    return pa.array(out, type=pa.timestamp("ns"))


def _dict_array(indices: np.ndarray | pa.Array, categories: list[str], index_type) -> pa.DictionaryArray:
    if not isinstance(indices, pa.Array):
        indices = pa.array(indices)
    return pa.DictionaryArray.from_arrays(indices.cast(index_type), pa.array(categories, type=pa.string()))


def _index_in(strings: pa.Array, categories: list[str], index_type) -> pa.Array:
    """Map a string array to its integer code in ``categories`` (null for unknown / null)."""
    return pc.index_in(strings, value_set=pa.array(categories, type=pa.string())).cast(index_type)


def _fmt_bytes(n: float) -> str:
    for unit in ("B", "KB", "MB", "GB"):
        if abs(n) < 1024 or unit == "GB":
            return f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} GB"


def _atomic_replace(tmp: Path, final: Path) -> None:
    os.replace(tmp, final)


# --------------------------------------------------------------------------------------
# facts: companyfacts.zip -> cache/sec/facts/part-XX.parquet
# --------------------------------------------------------------------------------------
def _facts_signature() -> str:
    st = COMPANYFACTS_ZIP.stat()
    payload = json.dumps(
        {
            "v": SCHEMA_VERSION,
            "tags": TAGS,
            "units": sorted(UNITS),
            "forms": sorted(FORMS),
            "zip": [st.st_size, int(st.st_mtime)],
            "parts": N_PARTS,
            "dicts": [_TAXONOMY_LIST, _UNIT_LIST, _FORM_LIST, _FP_LIST],
        },
        sort_keys=True,
    )
    return hashlib.sha1(payload.encode()).hexdigest()


def _part_is_current(part: int, sig: str) -> bool:
    p = _part_path(part)
    if not p.exists():
        return False
    try:
        md = pq.read_schema(p).metadata or {}
    except Exception:  # corrupt / partial file
        return False
    return md.get(b"sec_sig", b"").decode() == sig


class _Acc:
    """Python-list accumulator for one worker; converted to arrow in batches."""

    __slots__ = ("run_cik", "run_tax", "run_tag", "run_unit", "run_len",
                 "start", "end", "val", "filed", "form", "fy", "fp", "accn", "n")

    def __init__(self) -> None:
        self.reset()

    def reset(self) -> None:
        self.run_cik: list[int] = []
        self.run_tax: list[int] = []
        self.run_tag: list[int] = []
        self.run_unit: list[int] = []
        self.run_len: list[int] = []
        self.start: list = []
        self.end: list = []
        self.val: list = []
        self.filed: list = []
        self.form: list = []
        self.fy: list = []
        self.fp: list = []
        self.accn: list = []
        self.n = 0


def _acc_to_table(acc: _Acc, st: Counter) -> pa.Table | None:
    """Convert the accumulator to an arrow table with *integer* code columns (tax_i, tag_i, ...)."""
    if acc.n == 0:
        return None
    lens = np.asarray(acc.run_len, dtype=np.int64)
    try:
        val = np.asarray(acc.val, dtype=np.float64)
    except (TypeError, ValueError, OverflowError):  # pragma: no cover - exotic values
        val = np.array([float(v) if v is not None else np.nan for v in acc.val], dtype=np.float64)
    form_s = pa.array(acc.form, type=pa.string())
    fp_raw = pa.array([x or None for x in acc.fp], type=pa.string())
    fp_i = _index_in(fp_raw, _FP_LIST, pa.int8())
    unk = pc.and_(pc.is_null(fp_i), pc.is_valid(fp_raw))
    unknown_fp = pc.sum(unk).as_py() or 0
    if unknown_fp:
        st["fp_unknown_to_null"] += unknown_fp
        for v in pc.filter(fp_raw, unk).unique().to_pylist():
            st["fp_unknown_value:" + v] += 1
    start_raw = pa.array([x or None for x in acc.start], type=pa.string())
    start_ts = _to_ts(acc.start)
    n_bad_start = pc.sum(pc.and_(pc.is_valid(start_raw), pc.is_null(start_ts))).as_py() or 0
    if n_bad_start:
        st["start_unparseable_to_null"] += n_bad_start
    t = pa.table(
        {
            "cik": np.repeat(np.asarray(acc.run_cik, dtype=np.int64), lens),
            "tax_i": np.repeat(np.asarray(acc.run_tax, dtype=np.int8), lens),
            "tag_i": np.repeat(np.asarray(acc.run_tag, dtype=np.int16), lens),
            "unit_i": np.repeat(np.asarray(acc.run_unit, dtype=np.int8), lens),
            "start": start_ts,
            "end": _to_ts(acc.end),
            "val": val,
            "filed": _to_ts(acc.filed),
            "form_i": _index_in(form_s, _FORM_LIST, pa.int8()),
            "fy": pa.array(acc.fy, type=pa.float64()),
            "fp_i": fp_i,
            "accn": pa.array(acc.accn, type=pa.string()),
        }
    )
    ok = pc.and_(pc.is_valid(t["end"]), pc.is_valid(t["filed"]))
    n_bad = t.num_rows - pc.sum(ok.cast(pa.int64())).as_py()
    if n_bad:
        st["dropped_bad_end_or_filed"] += n_bad
        t = t.filter(ok)
    return t


def _extract_company(d: dict, cik: int, acc: _Acc, st: Counter) -> None:
    facts = d.get("facts") or {}
    if not facts:
        st["ciks_without_facts"] += 1
        return
    for tax, taglist in TAGS.items():
        tx = facts.get(tax)
        if not tx:
            continue
        tax_i = _TAX_IDX[tax]
        for tag in taglist:
            node = tx.get(tag)
            if node is None:
                continue
            tag_i = _TAG_IDX[tag]
            for unit, rows in node.get("units", {}).items():
                st["rows_in_kept_tags"] += len(rows)
                if unit not in UNITS:
                    st["dropped_unit"] += len(rows)
                    continue
                sel = [r for r in rows if r["form"] in FORMS]
                st["dropped_form"] += len(rows) - len(sel)
                m = len(sel)
                if not m:
                    continue
                acc.run_cik.append(cik)
                acc.run_tax.append(tax_i)
                acc.run_tag.append(tag_i)
                acc.run_unit.append(_UNIT_IDX[unit])
                acc.run_len.append(m)
                acc.start.extend([r.get("start") for r in sel])
                acc.end.extend([r["end"] for r in sel])
                acc.val.extend([r["val"] for r in sel])
                acc.filed.extend([r["filed"] for r in sel])
                acc.form.extend([r["form"] for r in sel])
                acc.fy.extend([r.get("fy") for r in sel])
                acc.fp.extend([r.get("fp") for r in sel])
                acc.accn.extend([r["accn"] for r in sel])
                acc.n += m


def _facts_partition_worker(task: tuple[int, list[str], str]) -> dict:
    """Process every companyfacts member of one partition and write ``part-XX.parquet``."""
    part, names, sig = task
    t0 = time.time()
    zf = _get_zip(str(COMPANYFACTS_ZIP))
    st: Counter = Counter(ciks=0, ciks_with_rows=0, ciks_without_facts=0)
    acc = _Acc()
    tables: list[pa.Table] = []
    for name in names:
        raw = zf.read(name)
        st["bytes_in"] += len(raw)
        d = json.loads(raw)
        del raw
        cik = int(d.get("cik") or _CF_NAME.match(name).group(1))
        st["ciks"] += 1
        before = acc.n
        _extract_company(d, cik, acc, st)
        if acc.n > before:
            st["ciks_with_rows"] += 1
        del d
        if acc.n >= FLUSH_ROWS:
            t = _acc_to_table(acc, st)
            acc.reset()
            if t is not None:
                tables.append(t)
    t = _acc_to_table(acc, st)
    acc.reset()
    if t is not None:
        tables.append(t)

    path = _part_path(part)
    tmp = path.with_suffix(".parquet.tmp")
    if tables:
        full = pa.concat_tables(tables).combine_chunks()
        full = full.sort_by([("cik", "ascending"), ("tag_i", "ascending"), ("unit_i", "ascending"),
                             ("end", "ascending"), ("start", "ascending"), ("filed", "ascending")])
        out = pa.table(
            {
                "cik": full["cik"],
                "taxonomy": _dict_array(full["tax_i"].combine_chunks(), _TAXONOMY_LIST, pa.int8()),
                "tag": _dict_array(full["tag_i"].combine_chunks(), _TAG_LIST, pa.int16()),
                "unit": _dict_array(full["unit_i"].combine_chunks(), _UNIT_LIST, pa.int8()),
                "start": full["start"],
                "end": full["end"],
                "val": full["val"],
                "filed": full["filed"],
                "form": _dict_array(full["form_i"].combine_chunks(), _FORM_LIST, pa.int8()),
                "fy": full["fy"],
                "fp": _dict_array(full["fp_i"].combine_chunks(), _FP_LIST, pa.int8()),
                "accn": full["accn"],
            },
            schema=FACTS_SCHEMA,
        )
        del full, tables
    else:  # pragma: no cover - empty partition
        out = FACTS_SCHEMA.empty_table()
    out = out.replace_schema_metadata({"sec_sig": sig, "part": str(part), "n_rows": str(out.num_rows)})
    pq.write_table(out, tmp, compression="zstd", compression_level=6, row_group_size=ROW_GROUP_SIZE,
                   use_dictionary=True, write_statistics=True)
    _atomic_replace(tmp, path)
    res = dict(st)
    res.update(part=part, rows=out.num_rows, out_bytes=path.stat().st_size, seconds=time.time() - t0,
               n_unique_ciks=pc.count_distinct(out["cik"]).as_py() if out.num_rows else 0)
    return res


def _companyfacts_members() -> dict[int, list[str]]:
    """partition -> list of member names (also validates the names)."""
    with zipfile.ZipFile(COMPANYFACTS_ZIP) as zf:
        infos = [i for i in zf.infolist() if _CF_NAME.match(i.filename)]
    parts: dict[int, list] = {p: [] for p in range(N_PARTS)}
    for i in infos:
        cik = int(_CF_NAME.match(i.filename).group(1))
        parts[cik_to_partition(cik)].append((i.filename, i.file_size))
    return parts


def build_facts(force: bool = False, n_jobs: int = 8) -> Path:
    """Build ``cache/sec/facts/part-00..63.parquet`` from companyfacts.zip. Returns the directory."""
    if not COMPANYFACTS_ZIP.exists():
        raise FileNotFoundError(COMPANYFACTS_ZIP)
    FACTS_DIR.mkdir(parents=True, exist_ok=True)
    sig = _facts_signature()
    todo = [p for p in range(N_PARTS) if force or not _part_is_current(p, sig)]
    if not todo:
        log.info("facts: all %d partitions up to date in %s (use force=True to rebuild)", N_PARTS, FACTS_DIR)
        return FACTS_DIR
    for stale in FACTS_DIR.glob("*.tmp"):
        stale.unlink()
    members = _companyfacts_members()
    # largest partitions first -> better load balance
    todo.sort(key=lambda p: -sum(s for _, s in members[p]))
    tasks = [(p, [n for n, _ in members[p]], sig) for p in todo]
    total_in = sum(s for p in todo for _, s in members[p])
    log.info("facts: building %d/%d partitions from %d CIK files (%s uncompressed), n_jobs=%d",
             len(todo), N_PARTS, sum(len(members[p]) for p in todo), _fmt_bytes(total_in), n_jobs)
    t0 = time.time()
    totals: Counter = Counter()
    done = 0

    def _handle(res: dict) -> None:
        nonlocal done
        done += 1
        for k, v in res.items():
            if k not in ("part", "seconds") and isinstance(v, (int, float)):
                totals[k] += v
        log.info("facts: part-%02d done (%d/%d): %d ciks, %d rows, %s, %.0fs | elapsed %.0fs",
                 res["part"], done, len(todo), res["ciks"], res["rows"], _fmt_bytes(res["out_bytes"]),
                 res["seconds"], time.time() - t0)

    if n_jobs <= 1:
        for task in tasks:
            _handle(_facts_partition_worker(task))
    else:
        ctx = mp.get_context("spawn")
        with ctx.Pool(n_jobs, initializer=_init_worker, initargs=(str(COMPANYFACTS_ZIP),)) as pool:
            for res in pool.imap_unordered(_facts_partition_worker, tasks, chunksize=1):
                _handle(res)

    elapsed = time.time() - t0
    log.info(
        "facts: DONE in %.0fs | ciks=%d (with rows %d, without facts %d) | rows in kept tags=%d, "
        "dropped unit=%d, dropped form=%d, dropped bad end/filed=%d, bad start->null=%d, "
        "fp unknown->null=%d %s | kept rows=%d | parquet %s",
        elapsed, totals["ciks"], totals["ciks_with_rows"], totals["ciks_without_facts"],
        totals["rows_in_kept_tags"], totals["dropped_unit"], totals["dropped_form"],
        totals["dropped_bad_end_or_filed"], totals["start_unparseable_to_null"], totals["fp_unknown_to_null"],
        sorted(k.split(":", 1)[1] for k in totals if k.startswith("fp_unknown_value:")), totals["rows"],
        _fmt_bytes(totals["out_bytes"]),
    )
    manifest = {"sig": sig, "built_unix": int(time.time()), "elapsed_s": round(elapsed, 1),
                "totals": {k: int(v) for k, v in totals.items()}}
    (FACTS_DIR / "_manifest.json").write_text(json.dumps(manifest, indent=1))
    return FACTS_DIR


# --------------------------------------------------------------------------------------
# companies + filings: submissions.zip -> companies.parquet, filings.parquet
# --------------------------------------------------------------------------------------
_SUBS_BUILT_THIS_PROCESS = False


def _clean(s) -> str | None:
    if s is None:
        return None
    s = str(s).strip()
    return s or None


def _submissions_chunk_worker(ciks: list[int]) -> tuple[list[dict], pa.Table, dict]:
    zf = _get_zip(str(SUBMISSIONS_ZIP))
    st: Counter = Counter()
    comps: list[dict] = []
    c_cik: list[int] = []
    c_accn: list[str] = []
    c_form: list[str] = []
    c_fd: list = []
    c_rd: list = []
    c_ad: list = []
    c_items: list = []
    for cik in ciks:
        name = f"CIK{cik:010d}.json"
        try:
            main = json.loads(zf.read(name))
        except KeyError:
            st["missing_main"] += 1
            continue
        filings = main.get("filings") or {}
        blocks = [filings.get("recent") or {}]
        for f in filings.get("files") or []:
            try:
                blocks.append(json.loads(zf.read(f["name"])))
                st["overflow_files"] += 1
            except KeyError:
                st["missing_overflow"] += 1
        n_10k = n_10q = 0
        first = last = last_per = None
        for b in blocks:
            forms = b.get("form") or []
            n = len(forms)
            if not n:
                continue
            fdates = [x or "" for x in (b.get("filingDate") or [""] * n)]
            accns = b.get("accessionNumber") or [""] * n
            rdates = [x or "" for x in (b.get("reportDate") or [""] * n)]
            adates = [x or "" for x in (b.get("acceptanceDateTime") or [""] * n)]
            items = b.get("items") or [""] * n
            valid_dates = [x for x in fdates if x]
            if valid_dates:
                lo, hi = min(valid_dates), max(valid_dates)
                first = lo if first is None or lo < first else first
                last = hi if last is None or hi > last else last
            for i, f in enumerate(forms):
                if f in ANNUAL_FORMS:
                    n_10k += 1
                elif f in QUARTERLY_FORMS:
                    n_10q += 1
                if f.startswith(("10-K", "10-Q")) and fdates[i] and (last_per is None or fdates[i] > last_per):
                    last_per = fdates[i]
            idx = [i for i, f in enumerate(forms) if f in _FILING_FORM_SET]
            if idx:
                c_cik.extend([cik] * len(idx))
                c_accn.extend([accns[i] for i in idx])
                c_form.extend([forms[i] for i in idx])
                c_fd.extend([fdates[i] for i in idx])
                c_rd.extend([rdates[i] for i in idx])
                c_ad.extend([(adates[i][:-1] if adates[i].endswith("Z") else adates[i]) for i in idx])
                c_items.extend([items[i] or None for i in idx])
        sic_raw = _clean(main.get("sic"))
        sic = int(sic_raw) if sic_raw and sic_raw.isdigit() and int(sic_raw) > 0 else None
        tickers = main.get("tickers") or []
        exchanges = main.get("exchanges") or []
        comps.append(
            dict(
                cik=cik,
                name=_clean(main.get("name")),
                tickers="|".join(t for t in tickers if t),
                exchanges="|".join((e or "") for e in exchanges),
                sic=sic,
                sic_description=_clean(main.get("sicDescription")),
                category=_clean(main.get("category")),
                fiscal_year_end=_clean(main.get("fiscalYearEnd")),
                entity_type=_clean(main.get("entityType")),
                state_of_inc=_clean(main.get("stateOfIncorporation")),
                first_filing_date=first,
                n_10k=n_10k,
                n_10q=n_10q,
                former_names=json.dumps(main.get("formerNames") or []),
                last_filing_date=last,
                last_periodic_filing_date=last_per,
            )
        )
        st["ciks"] += 1
        st["filings_total_rows_kept"] += len(c_cik)
    form_i = _index_in(pa.array(c_form, type=pa.string()), FILING_FORMS, pa.int8())
    t = pa.table(
        {
            "cik": pa.array(c_cik, type=pa.int64()),
            "accn": pa.array(c_accn, type=pa.string()),
            "form": _dict_array(form_i, FILING_FORMS, pa.int8()),
            "filing_date": _to_ts(c_fd),
            "report_date": _to_ts(c_rd),
            "acceptance_datetime": _to_ts(c_ad),
            "items": pa.array(c_items, type=pa.string()),
        },
        schema=FILINGS_SCHEMA,
    )
    if t.num_rows:
        t = t.sort_by([("cik", "ascending"), ("filing_date", "ascending"), ("accn", "ascending")])
    return comps, t, dict(st)


def _build_submissions(n_jobs: int = 8) -> None:
    """One pass over submissions.zip that writes both companies.parquet and filings.parquet."""
    global _SUBS_BUILT_THIS_PROCESS
    if not SUBMISSIONS_ZIP.exists():
        raise FileNotFoundError(SUBMISSIONS_ZIP)
    members = _companyfacts_members()
    ciks = sorted(int(_CF_NAME.match(n).group(1)) for names in members.values() for n, _ in names)
    chunks = [ciks[i:i + 100] for i in range(0, len(ciks), 100)]
    log.info("submissions: reading %d CIKs (those in companyfacts) in %d chunks, n_jobs=%d",
             len(ciks), len(chunks), n_jobs)
    t0 = time.time()
    SEC_DIR.mkdir(parents=True, exist_ok=True)
    tmp_f = FILINGS_PATH.with_suffix(".parquet.tmp")
    comps: list[dict] = []
    totals: Counter = Counter()
    n_rows = 0
    writer = pq.ParquetWriter(tmp_f, FILINGS_SCHEMA, compression="zstd", compression_level=6)
    try:
        if n_jobs <= 1:
            results = (_submissions_chunk_worker(c) for c in chunks)
            pool = None
        else:
            ctx = mp.get_context("spawn")
            pool = ctx.Pool(n_jobs, initializer=_init_worker, initargs=(str(SUBMISSIONS_ZIP),))
            results = pool.imap(_submissions_chunk_worker, chunks, chunksize=1)
        try:
            for k, (c, t, st) in enumerate(results, 1):
                comps.extend(c)
                totals.update(st)
                if t.num_rows:
                    writer.write_table(t, row_group_size=200_000)
                    n_rows += t.num_rows
                if k % 20 == 0 or k == len(chunks):
                    log.info("submissions: chunk %d/%d | companies %d | filing rows %d | %.0fs",
                             k, len(chunks), len(comps), n_rows, time.time() - t0)
        finally:
            if pool is not None:
                pool.terminate()
                pool.join()
    finally:
        writer.close()
    _atomic_replace(tmp_f, FILINGS_PATH)

    df = pd.DataFrame(comps).sort_values("cik").reset_index(drop=True)
    for c in ("first_filing_date", "last_filing_date", "last_periodic_filing_date"):
        df[c] = pd.to_datetime(df[c], format="%Y-%m-%d", errors="coerce").astype("datetime64[ns]")
    table = pa.Table.from_pandas(df, schema=COMPANIES_SCHEMA, preserve_index=False)
    tmp_c = COMPANIES_PATH.with_suffix(".parquet.tmp")
    pq.write_table(table, tmp_c, compression="zstd")
    _atomic_replace(tmp_c, COMPANIES_PATH)
    _SUBS_BUILT_THIS_PROCESS = True
    log.info(
        "submissions: DONE in %.0fs | companies=%d (missing main json: %d) | overflow files read=%d "
        "(missing %d) | filings rows=%d (%s) | companies %s",
        time.time() - t0, len(df), totals["missing_main"], totals["overflow_files"], totals["missing_overflow"],
        n_rows, _fmt_bytes(FILINGS_PATH.stat().st_size), _fmt_bytes(COMPANIES_PATH.stat().st_size),
    )


def build_companies(force: bool = False, n_jobs: int = 8) -> Path:
    """Build ``cache/sec/companies.parquet`` (one pass over submissions.zip also writes filings.parquet)."""
    if COMPANIES_PATH.exists() and FILINGS_PATH.exists() and not force:
        log.info("companies: %s exists (use force=True to rebuild)", COMPANIES_PATH)
        return COMPANIES_PATH
    if force and _SUBS_BUILT_THIS_PROCESS:
        log.info("companies: already rebuilt in this process; skipping second pass")
        return COMPANIES_PATH
    _build_submissions(n_jobs=n_jobs)
    return COMPANIES_PATH


def build_filings(force: bool = False, n_jobs: int = 8) -> Path:
    """Build ``cache/sec/filings.parquet`` (one pass over submissions.zip also writes companies.parquet)."""
    if COMPANIES_PATH.exists() and FILINGS_PATH.exists() and not force:
        log.info("filings: %s exists (use force=True to rebuild)", FILINGS_PATH)
        return FILINGS_PATH
    if force and _SUBS_BUILT_THIS_PROCESS:
        log.info("filings: already rebuilt in this process; skipping second pass")
        return FILINGS_PATH
    _build_submissions(n_jobs=n_jobs)
    return FILINGS_PATH


def build_all(force: bool = False, n_jobs: int = 8) -> None:
    build_facts(force=force, n_jobs=n_jobs)
    build_companies(force=force, n_jobs=n_jobs)
    build_filings(force=force, n_jobs=n_jobs)


# --------------------------------------------------------------------------------------
# Loaders
# --------------------------------------------------------------------------------------
def _read_filters(ciks, tags) -> pc.Expression | None:
    expr = None
    if ciks is not None:
        e = pc.field("cik").isin(pa.array([int(c) for c in ciks], type=pa.int64()))
        expr = e if expr is None else expr & e
    if tags is not None:
        e = pc.field("tag").isin(pa.array(list(tags), type=pa.string()))
        expr = e if expr is None else expr & e
    return expr


def _check_columns(columns) -> list[str] | None:
    if columns is None:
        return None
    columns = list(columns)
    bad = [c for c in columns if c not in FACTS_COLUMNS]
    if bad:
        raise KeyError(f"unknown facts columns {bad}; available: {FACTS_COLUMNS}")
    return columns


def list_partitions() -> list[int]:
    """Partition numbers that exist on disk."""
    return [p for p in range(N_PARTS) if _part_path(p).exists()]


def load_partition(part: int, tags: list[str] | None = None, columns: list[str] | None = None,
                   ciks: list[int] | None = None) -> pd.DataFrame:
    """One facts partition as a DataFrame (use this to stream through all facts without loading 100M rows)."""
    path = _part_path(part)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run quant.data.sec.build_facts()")
    table = _read_with_patch(part, _check_columns(columns), _read_filters(ciks, tags))
    return table.to_pandas()


def load_facts(ciks: list[int] | None = None, tags: list[str] | None = None, columns=None) -> pd.DataFrame:
    """Facts for ``ciks`` (default: all) and ``tags`` (default: all kept tags).

    Only the partitions that can contain the requested CIKs are opened; ``ciks=None`` reads all 64
    partitions (~100M rows: filter by ``tags`` and/or ``columns`` or iterate with ``load_partition``).
    Dictionary columns (taxonomy, tag, unit, form, fp) come back as pandas ``category``.
    """
    columns = _check_columns(columns)
    if ciks is not None:
        ciks = sorted({int(c) for c in ciks})
        parts = sorted({cik_to_partition(c) for c in ciks})
    else:
        parts = list_partitions() if FACTS_DIR.exists() else []
        if not parts:
            raise FileNotFoundError(f"no facts partitions in {FACTS_DIR}; run quant.data.sec.build_facts()")
    if tags is not None:
        tags = list(dict.fromkeys(tags))
        unknown = [t for t in tags if t not in _TAG_IDX]
        if unknown:
            log.warning("load_facts: tags not in TAGS registry (will return no rows for them): %s", unknown)
    filt = _read_filters(ciks, tags)
    if not parts:  # ciks == []
        schema = FACTS_SCHEMA if columns is None else pa.schema([FACTS_SCHEMA.field(c) for c in columns])
        return schema.empty_table().to_pandas()
    tables = []
    for p in parts:
        path = _part_path(p)
        if not path.exists():
            raise FileNotFoundError(f"{path} missing; run quant.data.sec.build_facts()")
        tables.append(_read_with_patch(p, columns, filt))
    table = pa.concat_tables(tables) if len(tables) > 1 else tables[0]
    return table.to_pandas()


def load_companies() -> pd.DataFrame:
    """companies.parquet as a DataFrame (``sic`` is nullable Int64)."""
    if not COMPANIES_PATH.exists():
        raise FileNotFoundError(f"{COMPANIES_PATH} missing; run quant.data.sec.build_companies()")
    df = pq.read_table(COMPANIES_PATH).to_pandas()
    df["sic"] = df["sic"].astype("Int64")
    return df


def load_filings(forms: list[str] | None = None, ciks: list[int] | None = None) -> pd.DataFrame:
    """filings.parquet (optionally restricted to form types and/or CIKs). ``form`` is a category."""
    if not FILINGS_PATH.exists():
        raise FileNotFoundError(f"{FILINGS_PATH} missing; run quant.data.sec.build_filings()")
    expr = None
    if forms is not None:
        expr = pc.field("form").isin(pa.array(list(forms), type=pa.string()))
    if ciks is not None:
        e = pc.field("cik").isin(pa.array([int(c) for c in ciks], type=pa.int64()))
        expr = e if expr is None else expr & e
    return pq.read_table(FILINGS_PATH, filters=expr).to_pandas()


# --------------------------------------------------------------------------------------
# CLI:  .venv/bin/python -m quant.data.sec [facts|companies|filings|all] [--force] [--jobs N]
# --------------------------------------------------------------------------------------

# --------------------------------------------------------------------------------------
# Patch: filings that companyfacts.zip is missing (SEC Financial Statement Data Sets)
# --------------------------------------------------------------------------------------
# companyfacts silently omits some filings (e.g. ~100 large filers' Q2-2026 10-Qs: KO, V, ABT, ...; the live
# companyfacts API lacks them too). SEC's quarterly Financial Statement Data Sets (FSDS) carry the same XBRL
# numbers per filing. For every 10-K/10-Q in an FSDS quarter whose accession number is absent from our facts,
# we convert its non-dimensional, non-coregistrant rows for registry tags into the facts schema and store them
# as `facts_patch/part-XX.parquet`; the loaders append them transparently.
FSDS_DIR = SEC_DIR / "fsds"
PATCH_DIR = SEC_DIR / "facts_patch"
FSDS_URL = "https://www.sec.gov/files/dera/data/financial-statement-data-sets/{q}.zip"


def _patch_path(part: int) -> Path:
    return PATCH_DIR / f"part-{part:02d}.parquet"


FSDS_QUARTERS = tuple(f"{y}q{q}" for y in range(2023, 2027) for q in range(1, 5) if (y, q) <= (2026, 3))


def build_fsds_patch(quarters: tuple[str, ...] = FSDS_QUARTERS, force: bool = False) -> int:
    """Download FSDS quarters and write patch partitions for filings missing from companyfacts. Returns rows."""
    import io
    import requests

    from quant import settings

    FSDS_DIR.mkdir(parents=True, exist_ok=True)
    PATCH_DIR.mkdir(parents=True, exist_ok=True)
    if not force and any(PATCH_DIR.glob("part-*.parquet")):
        log.info("fsds patch exists; use force=True to rebuild")
        return -1
    frames = []
    for q in quarters:
        zpath = FSDS_DIR / f"{q}.zip"
        if not zpath.exists():
            r = requests.get(FSDS_URL.format(q=q), headers={"User-Agent": settings.SEC_USER_AGENT}, timeout=600)
            r.raise_for_status()
            zpath.write_bytes(r.content)
        with zipfile.ZipFile(zpath) as z:
            sub = pd.read_csv(io.BytesIO(z.read("sub.txt")), sep="\t", dtype=str,
                              usecols=["adsh", "cik", "form", "filed", "fy", "fp"])
            sub = sub[sub["form"].isin(FORMS)]
            sub["cik"] = sub["cik"].astype("int64")
            # accession numbers already present in our facts for these CIKs
            have = set()
            for part in sorted({cik_to_partition(c) for c in sub["cik"].unique()}):
                t = pq.read_table(_part_path(part), columns=["accn"],
                                  filters=pc.field("cik").isin(pa.array(sub["cik"].unique(), type=pa.int64())))
                have.update(pc.unique(t["accn"]).to_pylist())
            missing = sub[~sub["adsh"].isin(have)].set_index("adsh")
            log.info("fsds %s: %d periodic filings, %d missing from companyfacts", q, len(sub), len(missing))
            if missing.empty:
                continue
            keep = set(_TAG_LIST)
            with z.open("num.txt") as fh:
                for chunk in pd.read_csv(fh, sep="\t", dtype=str, chunksize=2_000_000,
                                         usecols=["adsh", "tag", "version", "ddate", "qtrs", "uom",
                                                  "segments", "coreg", "value"],
                                         keep_default_na=False, na_values=[""]):
                    c = chunk[chunk["adsh"].isin(missing.index) & chunk["tag"].isin(keep)
                              & chunk["segments"].isna() & chunk["coreg"].isna() & chunk["uom"].isin(UNITS)
                              & chunk["value"].notna()]
                    if c.empty:
                        continue
                    c = c.copy()
                    c["taxonomy"] = c["version"].str.split("/").str[0]
                    c = c[c["taxonomy"].isin(_TAXONOMY_LIST)]
                    frames.append(c.join(missing, on="adsh"))
    if not frames:
        return 0
    df = pd.concat(frames, ignore_index=True)
    # registry tags are unique across taxonomies, so trust our registry's taxonomy for each tag
    tag_tax = {t: tax for tax, tags in TAGS.items() for t in tags}
    df = df[df["tag"].map(tag_tax) == df["taxonomy"]]
    end = pd.to_datetime(df["ddate"], format="%Y%m%d")
    qtrs = df["qtrs"].astype(int)
    # FSDS gives duration in quarters, not a start date; months*3 back + 1 day lands in the same duration class
    start = pd.Series(pd.NaT, index=df.index, dtype="datetime64[ns]")
    dur = qtrs > 0
    start[dur] = [e - pd.DateOffset(months=3 * q) + pd.Timedelta(days=1) for e, q in zip(end[dur], qtrs[dur])]
    out = pd.DataFrame({
        "cik": df["cik"].astype("int64"),
        "taxonomy": df["taxonomy"], "tag": df["tag"], "unit": df["uom"],
        "start": start.astype("datetime64[ns]"), "end": end.astype("datetime64[ns]"),
        "val": df["value"].astype(float),
        "filed": pd.to_datetime(df["filed"], format="%Y%m%d").astype("datetime64[ns]"),
        "form": df["form"], "fy": pd.to_numeric(df["fy"], errors="coerce").astype(float),
        "fp": df["fp"].where(df["fp"].isin(_FP_LIST)), "accn": df["adsh"],
    }).drop_duplicates(["cik", "tag", "unit", "start", "end", "accn"])
    for f in PATCH_DIR.glob("part-*.parquet"):
        f.unlink()
    n = 0
    for part, g in out.groupby(out["cik"] % N_PARTS):
        table = pa.table({
            "cik": pa.array(g["cik"].to_numpy(), type=pa.int64()),
            "taxonomy": _dict_array(_index_in(pa.array(g["taxonomy"]), _TAXONOMY_LIST, pa.int8()), _TAXONOMY_LIST, pa.int8()),
            "tag": _dict_array(_index_in(pa.array(g["tag"]), _TAG_LIST, pa.int16()), _TAG_LIST, pa.int16()),
            "unit": _dict_array(_index_in(pa.array(g["unit"]), _UNIT_LIST, pa.int8()), _UNIT_LIST, pa.int8()),
            "start": pa.array(g["start"], type=pa.timestamp("ns")),
            "end": pa.array(g["end"], type=pa.timestamp("ns")),
            "val": pa.array(g["val"].to_numpy(), type=pa.float64()),
            "filed": pa.array(g["filed"], type=pa.timestamp("ns")),
            "form": _dict_array(_index_in(pa.array(g["form"]), _FORM_LIST, pa.int8()), _FORM_LIST, pa.int8()),
            "fy": pa.array(g["fy"].to_numpy(), type=pa.float64()),
            "fp": _dict_array(_index_in(pa.array(g["fp"], type=pa.string()), _FP_LIST, pa.int8()), _FP_LIST, pa.int8()),
            "accn": pa.array(g["accn"], type=pa.string()),
        }, schema=FACTS_SCHEMA)
        pq.write_table(table, _patch_path(int(part)))
        n += table.num_rows
    log.info("fsds patch: %d rows for %d filings / %d CIKs", n, out["accn"].nunique(), out["cik"].nunique())
    return n


def _read_with_patch(part: int, columns, filt) -> pa.Table:
    t = pq.read_table(_part_path(part), columns=columns, filters=filt)
    pp = _patch_path(part)
    if pp.exists():
        t = pa.concat_tables([t, pq.read_table(pp, columns=columns, filters=filt)])
        if "cik" in t.column_names:    # keep partitions cik-sorted (stable sort keeps tag/unit/end order)
            t = t.take(pc.sort_indices(t, sort_keys=[("cik", "ascending")]))
    return t


def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("what", nargs="?", default="all", choices=["facts", "companies", "filings", "all"])
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    args = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(levelname)s %(name)s: %(message)s")
    if args.what == "facts":
        build_facts(args.force, args.jobs)
    elif args.what == "companies":
        build_companies(args.force, args.jobs)
    elif args.what == "filings":
        build_filings(args.force, args.jobs)
    else:
        build_all(args.force, args.jobs)


if __name__ == "__main__":
    main()
