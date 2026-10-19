"""Point-in-time fundamentals snapshots built from the SEC XBRL facts cache (``quant.data.sec``).

Output: ``cache/fundamentals/snapshots.parquet`` -- one row per (cik, filing date) for every 10-K / 10-Q /
10-KT / 10-QT (and /A amendments) that carries a balance sheet. The row holds what an investor could compute
ON that filed date: for every (tag, period) the fact with the greatest ``filed`` <= the snapshot's filed date.
Schema: ``quant/ARCHITECTURE.md`` (*Snapshot schema*).

Public API
    build_snapshots(ciks=None, n_jobs=8, force=False, out_path=None, first_filed=False) -> Path
    load_snapshots(columns=None, path=None, first_filed=False) -> pd.DataFrame
    asof(snaps, date, max_age_days=200) -> pd.DataFrame        # index = cik, strict ``filed < date``
    snapshots_from_facts(facts, first_filed=False) -> pd.DataFrame   # in-memory (tests, notebooks)
    CLI: ``.venv/bin/python -m quant.data.fundamentals [--force] [--jobs N] [--first-filed]``

Algorithm (per company; inside a company everything is dict / bisect lookups, no DataFrame filtering)
    1. Rows are cleaned (unit check, finite value, ``end <= filed + 5d``), flows are classified by duration
       (quarter 70-125 d, 6M 160-200, 9M 240-290, FY 350-380; end - start + 1) and ends are snapped to a
       per-company anchor calendar (ends within 5 d collapse to the most frequent one). Periods are therefore
       identified by (tag, snapped end, duration class), which is immune to 1-2 day start-date jitter and to
       ``fy`` / ``fp`` (which describe the filing, not the period).
    2. Facts are ingested in ``filed`` order into ``state[tag][(end, cls)]``; the latest vintage wins
       (``first_filed=True`` keeps the earliest vintage instead). A snapshot is evaluated after ingesting every
       fact with ``filed <= its filed date`` -- so a later restatement of a prior-year comparative changes later
       snapshots only.
    3. ``period_end`` = max end of the Assets / AssetsCurrent / LiabilitiesAndStockholdersEquity instants carried
       by the filing (running maximum over earlier-filed filings, so a late amendment of an old period still
       reports the newest balance sheet known; flag ``amend_anchor``).
    4. TTM per flow concept, coalescing tag chains PER PERIOD (never per company):
         'FY'  an annual fact ends at period_end
         'YTD' FY_prev + YTD_cur - YTD_prior_year (FY_prev ends within 10 d of YTD_cur.start - 1; prior YTD ends
               within 10 d of period_end - 364 and has the same duration class)
         '4Q'  sum of four discrete quarters (Q2 = H1 - Q1, Q3 = 9M - H1, Q4 = FY - 9M)
       Pieces that come from different tags are allowed but flagged ``mixed_tags``.
    5. Debt follows research/03 s5.2 (measured semantics, no double counting), operating leases never in debt.

Flags (semicolon list in ``flags``; read it with ``df["flags"]`` -- ``df.flags`` is a pandas attribute)
    TTM / tags   mixed_tags (+ mix_<concept>: pieces of that concept's TTM came from different tags), ttm_4q (some concept
                 fell back to four discrete quarters), ebit_proxy / ebit_proxy_costs / ebit_proxy_gp (no
                 OperatingIncomeLoss: pretax + interest | revenue - CostsAndExpenses | GrossProfit - OperatingExpenses),
                 gp_derived (revenue - cogs because GrossProfit is absent / stale for this period), ni_fallback (parent net
                 income from a fallback tag), int_net_fallback (interest expense taken as -net interest), acq_fill0
                 (acquisitions: missing pieces treated as 0), amend_anchor (late amendment of an old period: the snapshot
                 uses the newest balance sheet known at that date)
    balance      carry_fwd (goodwill / intangibles / lease items carried from a 10-K <= 400 days old), cash_alt,
                 ppe_derived, eq_derived, liab_derived, assets_from_lse
    debt         debt_zero_inferred, debt_lowconf (only note-type tags exist), debt_current_only, debt_nc_missing (a
                 non-current debt tag existed in the last 8 quarters but not at period_end -> total_debt left NaN),
                 ltd_excl_current (this filer's LongTermDebt excludes the current portion)
    shares       multi_class_sum, shares_stale (older cover count), shares_bs (balance-sheet count; no cover count),
                 shares_scale_dropped (cover count rejected as a scale error), shares_mismatch (shares_out and
                 shares_diluted disagree by > 8x: one is mis-scaled, trust shares_out), sh_dil_q4derived,
                 sh_dil_annual, sh_dil_ytd

Known limitations (see output/data_audit/fundamentals_coverage.md)
    * TTM = FY_prev + YTD - YTD_prior mixes the original FY_prev with a possibly recast prior-year comparative
      (divestitures / discontinued operations): TTM can differ from Yahoo's sum of recast quarters (HON).
    * Segment-presented balance sheets (CAT, F) have no non-dimensional interim debt: total_debt is NaN, not a stale 10-K value.
    * Multi-class issuers lack the cover-page count: shares_out falls back to the balance-sheet count (flag shares_bs).
    * companyfacts silently omits some recent 10-Qs (KO, MDLZ, CB, ...): those companies are one quarter stale.
    * Fresh-start / predecessor-successor periods, transition periods and subsidiary filers often get ttm_method 'none'.
"""
from __future__ import annotations

import argparse
import bisect
import gc
import logging
import math
import shutil
import time
from concurrent.futures import ProcessPoolExecutor
from pathlib import Path

import numpy as np
import pandas as pd
import pyarrow as pa
import pyarrow.compute as pc
import pyarrow.parquet as pq

from quant.data import sec as _sec
from quant.settings import FUND_DIR

log = logging.getLogger(__name__)

SNAP_PATH = FUND_DIR / "snapshots.parquet"
SNAP_FIRST_PATH = FUND_DIR / "snapshots_first.parquet"
BUILD_VERSION = "3"

NAN = float("nan")
NOSTART = -(10 ** 9)          # start sentinel for instants
ANCHOR_TOL = 5               # days: ends closer than this collapse to one anchor
TTM_TOL = 10                 # days: FY_prev / prior-year YTD matching tolerance
QGAP_LO, QGAP_HI = 70, 125   # days between consecutive quarter ends

# duration classes (days = end - start + 1)
CLS_WINDOWS = ((1, 70, 125), (2, 160, 200), (3, 240, 290), (4, 350, 380))
FISCAL_PERIOD = {4: "FY", 3: "Q3", 2: "Q2", 1: "Q1"}


# ======================================================================================
# Resolvers: (state, key) -> (value, source_id, start_day) | None.   key = end * 8 + cls
# ======================================================================================
def _first(*tags):
    def f(S, key):
        for i, t in enumerate(tags):
            v = S[t].get(key)
            if v is not None:
                return v[0], i, v[1]
        return None
    f.tags = tags
    return f


def _maxof(*tags, tol: float = 0.03):
    """Largest value among `tags` (sub-line / zero tags lose: ETN, PG, CCK), except that a higher-PRIORITY tag
    within `tol` of the largest wins (WMT: net sales vs total revenues incl. membership income)."""
    def f(S, key):
        got = []
        for i, t in enumerate(tags):
            v = S[t].get(key)
            if v is not None:
                got.append((i, v))
        if not got:
            return None
        mx = max(v[0] for _, v in got)
        thr = mx * (1.0 - tol) if mx > 0 else mx
        for i, v in got:                      # priority order
            if v[0] >= thr:
                return v[0], i, v[1]
        return None
    f.tags = tags
    return f


def _sumof(*tags):
    def f(S, key):
        tot = 0.0
        mask = 0
        st = None
        for i, t in enumerate(tags):
            v = S[t].get(key)
            if v is not None:
                tot += v[0]
                mask |= 1 << i
                if st is None:
                    st = v[1]
        if mask == 0:
            return None
        return tot, mask, st
    f.tags = tags
    return f


def _neg(tag):
    def f(S, key):
        v = S[tag].get(key)
        if v is None:
            return None
        return -v[0], 0, v[1]
    f.tags = (tag,)
    return f


def _chain(*fs):
    def f(S, key):
        for ri, g in enumerate(fs):
            r = g(S, key)
            if r is not None:
                return r[0], ri * 16 + r[1], r[2]
        return None
    f.tags = tuple(dict.fromkeys(t for g in fs for t in g.tags))
    return f


# ---- flow concepts ---------------------------------------------------------------
_REV_MAIN = ("RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet")
R_revenue = _chain(
    _maxof(*_REV_MAIN),                                                    # LARGEST of the main tags (ETN/PG/CCK)
    _first("RevenueFromContractWithCustomerIncludingAssessedTax"),
    _sumof("SalesRevenueGoodsNet", "SalesRevenueServicesNet"),
    _first("RevenuesNetOfInterestExpense"),
)
R_cogs = _chain(
    _first("CostOfGoodsAndServicesSold", "CostOfRevenue"),
    _sumof("CostOfGoodsSold", "CostOfServices"),                           # product + service split, no total
    _first("CostOfGoodsAndServiceExcludingDepreciationDepletionAndAmortization"),
)
R_gp = _first("GrossProfit")
R_sga = _chain(_first("SellingGeneralAndAdministrativeExpense"),
               _sumof("GeneralAndAdministrativeExpense", "SellingAndMarketingExpense"))
R_pretax = _first("IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
                  "IncomeLossFromContinuingOperationsBeforeIncomeTaxesMinorityInterestAndIncomeLossFromEquityMethodInvestments")
R_interest = _chain(
    _first("InterestExpense", "InterestExpenseNonoperating", "InterestExpenseDebt", "InterestAndDebtExpense"),
    _neg("InterestIncomeExpenseNonoperatingNet"),                         # negative = net expense
)
R_tax = _first("IncomeTaxExpenseBenefit")
R_opinc_true = _first("OperatingIncomeLoss")


def R_opinc(S, key):
    v = S["OperatingIncomeLoss"].get(key)
    if v is not None:
        return v[0], 0, v[1]
    p = R_pretax(S, key)
    if p is not None:                                                      # EBIT = pretax + interest expense
        i = R_interest(S, key)
        return p[0] + (i[0] if i is not None else 0.0), 16, p[2]
    r = R_revenue(S, key)
    c = S["CostsAndExpenses"].get(key)
    if r is not None and c is not None:
        return r[0] - c[0], 32, c[1]
    g = S["GrossProfit"].get(key)
    o = S["OperatingExpenses"].get(key)
    if g is not None and o is not None:
        return g[0] - o[0], 48, g[1]
    return None


R_opinc.tags = ("OperatingIncomeLoss", "CostsAndExpenses", "GrossProfit", "OperatingExpenses") + R_pretax.tags \
    + R_interest.tags + R_revenue.tags


def _ni_from_profit(S, key):
    p = S["ProfitLoss"].get(key)
    if p is None:
        return None
    n = S["NetIncomeLossAttributableToNoncontrollingInterest"].get(key)
    return p[0] - (n[0] if n is not None else 0.0), 0, p[1]


_ni_from_profit.tags = ("ProfitLoss", "NetIncomeLossAttributableToNoncontrollingInterest")
# ProfitLoss - NCI before the "available to common" tag, which is NI AFTER preferred dividends (WELL -19.6%)
R_ni = _chain(_first("NetIncomeLoss"), _ni_from_profit, _first("NetIncomeLossAvailableToCommonStockholdersBasic"))


def _pl_from_ni(S, key):
    p = S["NetIncomeLoss"].get(key)
    if p is None:
        return None
    n = S["NetIncomeLossAttributableToNoncontrollingInterest"].get(key)
    return p[0] + (n[0] if n is not None else 0.0), 0, p[1]


_pl_from_ni.tags = ("NetIncomeLoss", "NetIncomeLossAttributableToNoncontrollingInterest")
R_pl = _chain(_first("ProfitLoss"), _pl_from_ni)
R_da = _chain(
    _first("DepreciationDepletionAndAmortization", "DepreciationAndAmortization", "DepreciationAmortizationAndAccretionNet"),
    _sumof("Depreciation", "AmortizationOfIntangibleAssets"),
)
R_cfo = _first("NetCashProvidedByUsedInOperatingActivities", "NetCashProvidedByUsedInOperatingActivitiesContinuingOperations")
R_capex = _first("PaymentsToAcquirePropertyPlantAndEquipment", "PaymentsToAcquireProductiveAssets",
                 # LLY/ADP, VZ, GLW/VLO and E&P names use these instead (lead fix after key-metrics coverage audit)
                 "PaymentsToAcquireOtherPropertyPlantAndEquipment", "PaymentsToAcquireOtherProductiveAssets",
                 "PaymentsForCapitalImprovements", "PaymentsToAcquireOilAndGasPropertyAndEquipment",
                 "PaymentsToAcquireOilAndGasProperty", "PaymentsToExploreAndDevelopOilAndGasProperties",
                 "PaymentsForProceedsFromProductiveAssets")
R_acq = _first("PaymentsToAcquireBusinessesNetOfCashAcquired")
R_eps = _first("EarningsPerShareDiluted", "EarningsPerShareBasicAndDiluted")
R_shdil = _first("WeightedAverageNumberOfDilutedSharesOutstanding",
                 "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted")
R_shbas = _first("WeightedAverageNumberOfSharesOutstandingBasic",
                 "WeightedAverageNumberOfSharesOutstandingBasicAndDiluted")

# name -> (resolver, {chain index: flag}, zero_fill)
FLOW_SPECS = {
    "revenue": (R_revenue, {}, False),
    "cogs": (R_cogs, {}, False),
    "sga": (R_sga, {}, False),
    "opinc": (R_opinc, {1: "ebit_proxy", 2: "ebit_proxy_costs", 3: "ebit_proxy_gp"}, False),
    "pretax": (R_pretax, {}, False),
    "interest_exp": (R_interest, {1: "int_net_fallback"}, False),
    "tax": (R_tax, {}, False),
    "net_income": (R_ni, {1: "ni_fallback", 2: "ni_fallback"}, False),
    "net_income_incl_nci": (R_pl, {}, False),
    "da": (R_da, {}, False),
    "cfo": (R_cfo, {}, False),
    "capex": (R_capex, {}, False),
    "acquisitions": (R_acq, {}, True),
    "eps_diluted": (R_eps, {}, False),
}

# ---- instant tag groups ------------------------------------------------------------
T_CASH = ("CashAndCashEquivalentsAtCarryingValue", "CashCashEquivalentsRestrictedCashAndRestrictedCashEquivalents", "Cash")
T_STI = ("ShortTermInvestments", "MarketableSecuritiesCurrent")
T_STI_ALT = ("AvailableForSaleSecuritiesDebtSecuritiesCurrent",)
T_PPE = ("PropertyPlantAndEquipmentNet",
         "PropertyPlantAndEquipmentAndFinanceLeaseRightOfUseAssetAfterAccumulatedDepreciationAndAmortization")
T_PPE_GROSS = ("PropertyPlantAndEquipmentGross", "AccumulatedDepreciationDepletionAndAmortizationPropertyPlantAndEquipment")
T_PREF = ("PreferredStockValue", "PreferredStockValueOutstanding", "TemporaryEquityCarryingAmountAttributableToParent")
T_MI = ("MinorityInterest", "RedeemableNoncontrollingInterestEquityCarryingAmount")
T_ST_OTHER = ("ShortTermBorrowings", "CommercialPaper", "NotesPayableCurrent", "LineOfCreditCurrent",
              "ConvertibleNotesPayableCurrent", "LoansPayableCurrent")
T_NC_ALT_SLOTS = (("SeniorNotes",), ("SecuredDebt",), ("UnsecuredDebt",), ("SubordinatedDebt",),
                  ("ConvertibleNotesPayable", "ConvertibleDebtNoncurrent", "ConvertibleDebt"),
                  ("LongTermNotesPayable",), ("LongTermLineOfCredit", "LineOfCredit"),
                  ("OtherLongTermDebtNoncurrent", "OtherLongTermDebt"))
T_NC_ALT_TOTALS = ("NotesPayable", "LoansPayable")
T_DEBT_LIKE = (
    "LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtCurrent", "DebtCurrent", "ShortTermBorrowings",
    "CommercialPaper", "NotesPayableCurrent", "LineOfCreditCurrent", "ConvertibleNotesPayableCurrent",
    "LoansPayableCurrent", "LongTermDebtAndCapitalLeaseObligations", "LongTermDebtAndCapitalLeaseObligationsCurrent",
    "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities", "DebtAndCapitalLeaseObligations",
    "LongTermNotesPayable", "ConvertibleNotesPayable", "ConvertibleDebt", "ConvertibleDebtNoncurrent",
    "DebtLongtermAndShorttermCombinedAmount", "SeniorNotes", "LongTermLineOfCredit", "LineOfCredit", "SecuredDebt",
    "UnsecuredDebt", "NotesPayable", "LoansPayable", "OtherLongTermDebtNoncurrent", "OtherLongTermDebt",
    "SubordinatedDebt", "DebtInstrumentCarryingAmount", "ShortTermBankLoansAndNotesPayable",
)
_NC_DEBT_TAGS = ("LongTermDebt", "LongTermDebtNoncurrent", "LongTermDebtAndCapitalLeaseObligations",
                 "LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities", "LongTermNotesPayable",
                 "SeniorNotes", "SecuredDebt", "UnsecuredDebt", "ConvertibleNotesPayable", "ConvertibleDebtNoncurrent",
                 "LongTermLineOfCredit", "OtherLongTermDebtNoncurrent", "SubordinatedDebt", "NotesPayable")
T_FIN_LEASE = ("FinanceLeaseLiability", "FinanceLeaseLiabilityCurrent", "FinanceLeaseLiabilityNoncurrent",
               "CapitalLeaseObligations", "CapitalLeaseObligationsCurrent", "CapitalLeaseObligationsNoncurrent")
T_OP_LEASE = ("OperatingLeaseLiability", "OperatingLeaseLiabilityCurrent", "OperatingLeaseLiabilityNoncurrent")
# Oil & gas producers carry their main fixed assets as oil-and-gas property (net, or gross - accumulated DD&A);
# PropertyPlantAndEquipmentNet is then missing (MGY, APA) or only the "other" PP&E (RRC). Lead fix after MF audit.
T_OG_NET = ("OilAndGasPropertySuccessfulEffortMethodNet", "OilAndGasPropertyFullCostMethodNet")
T_OG_GROSS = (("OilAndGasPropertySuccessfulEffortMethodGross",
               "OilAndGasPropertySuccessfulEffortMethodAccumulatedDepreciationDepletionAmortizationAndImpairment"),
              ("OilAndGasPropertyFullCostMethodGross",
               "OilAndGasPropertyFullCostMethodAccumulatedDepreciationDepletionAmortizationAndImpairment"))
T_CARRY = ("Goodwill", "IntangibleAssetsNetExcludingGoodwill") + T_FIN_LEASE + T_OP_LEASE
T_MARKER = ("Assets", "AssetsCurrent", "LiabilitiesAndStockholdersEquity")
T_BS_OTHER = ("Assets", "AssetsCurrent", "LiabilitiesCurrent", "Liabilities", "LiabilitiesAndStockholdersEquity",
              "StockholdersEquity", "StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest",
              "RetainedEarningsAccumulatedDeficit", "CommonStockSharesOutstanding", "Goodwill",
              "IntangibleAssetsNetExcludingGoodwill")

# flow tags used to detect which duration classes exist at an anchor / which ends are fiscal-year ends
CORE_FLOW = ("NetIncomeLoss", "ProfitLoss", "OperatingIncomeLoss", "NetCashProvidedByUsedInOperatingActivities",
             "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
             "RevenueFromContractWithCustomerIncludingAssessedTax", "IncomeTaxExpenseBenefit",
             "IncomeLossFromContinuingOperationsBeforeIncomeTaxesExtraordinaryItemsNoncontrollingInterest",
             "EarningsPerShareDiluted", "CostOfRevenue", "CostOfGoodsAndServicesSold")
ANNUAL_CORE = frozenset(("NetIncomeLoss", "ProfitLoss", "OperatingIncomeLoss", "NetCashProvidedByUsedInOperatingActivities",
                         "RevenueFromContractWithCustomerExcludingAssessedTax", "Revenues", "SalesRevenueNet",
                         "RevenueFromContractWithCustomerIncludingAssessedTax"))

DEI_TAG = "EntityCommonStockSharesOutstanding"

_ALL_RESOLVERS = [v[0] for v in FLOW_SPECS.values()] + [R_gp, R_shdil, R_shbas]
USED_TAGS: tuple[str, ...] = tuple(dict.fromkeys(
    [t for r in _ALL_RESOLVERS for t in r.tags]
    + list(T_OG_NET) + [t for pair in T_OG_GROSS for t in pair]
    + list(T_CASH + T_STI + T_STI_ALT + T_PPE + T_PPE_GROSS + T_PREF + T_MI + T_ST_OTHER + T_DEBT_LIKE
           + T_FIN_LEASE + T_OP_LEASE + T_BS_OTHER + CORE_FLOW)
    + [t for slot in T_NC_ALT_SLOTS for t in slot] + list(T_NC_ALT_TOTALS)
    + [DEI_TAG]
))
_missing = [t for t in USED_TAGS if t not in set(_sec.TAGS["us-gaap"]) | set(_sec.TAGS["dei"])]
if _missing:  # pragma: no cover - registry sanity
    raise ImportError(f"fundamentals.py uses tags that sec.TAGS does not keep: {_missing}")

GAAP_TAGS = tuple(t for t in USED_TAGS if t != DEI_TAG)
TAG_ID = {t: i for i, t in enumerate(USED_TAGS)}
DEI_ID = TAG_ID[DEI_TAG]


def _unit_of(tag: str) -> str:
    if tag.startswith("EarningsPerShare") or "PerShare" in tag:
        return "USD/shares"
    if tag.startswith("WeightedAverageNumber") or tag.startswith("CommonStockShares") or tag == DEI_TAG:
        return "shares"
    return "USD"


TAG_UNIT = {t: _unit_of(t) for t in USED_TAGS}
_TRACK = frozenset(T_DEBT_LIKE) | frozenset(T_CARRY)      # instants whose observation ends we index (bisect)

# ======================================================================================
# Output schema
# ======================================================================================
KEYS = ["cik", "accn", "form", "filed", "period_end", "fiscal_period", "fy_end_date", "ttm_method", "flags"]
TTM_COLS = ["revenue", "cogs", "gross_profit", "sga", "opinc", "pretax", "interest_exp", "tax", "net_income",
            "net_income_incl_nci", "da", "cfo", "capex", "acquisitions", "ebitda", "eps_diluted"]
LFY_COLS = ["revenue_lfy", "opinc_lfy", "net_income_lfy", "da_lfy", "ebitda_lfy", "cfo_lfy", "capex_lfy"]
BS_COLS = ["assets", "current_assets", "current_liabilities", "cash", "st_investments", "ppe_net", "goodwill",
           "intangibles", "liabilities", "equity_parent", "equity_total", "preferred", "minority_interest",
           "debt_current", "debt_noncurrent", "total_debt", "finance_lease", "op_lease_current",
           "op_lease_noncurrent", "retained_earnings"]
SHARE_COLS = ["shares_out", "shares_out_date", "shares_diluted", "shares_basic"]
HIST_COLS = ["assets_4q", "total_debt_4q", "equity_total_4q", "cash_4q", "shares_diluted_4q", "opinc_ttm_4q",
             "revenue_ttm_4q"]
FY_CONCEPTS = ("revenue", "opinc", "cfo", "capex", "net_income")
FYH_COLS = [f"{c}_fy{i}" for c in FY_CONCEPTS for i in range(1, 6)] + [f"fyend_fy{i}" for i in range(1, 6)]
COLUMNS = KEYS + TTM_COLS + LFY_COLS + BS_COLS + SHARE_COLS + HIST_COLS + FYH_COLS + ["evol"]
DATE_COLS = ["filed", "period_end", "fy_end_date", "shares_out_date"] + [f"fyend_fy{i}" for i in range(1, 6)]
STR_COLS = ["accn", "form", "fiscal_period", "ttm_method", "flags"]


def _arrow_schema() -> pa.Schema:
    fields = []
    for c in COLUMNS:
        if c == "cik":
            fields.append(pa.field(c, pa.int64()))
        elif c in STR_COLS:
            fields.append(pa.field(c, pa.string()))
        elif c in DATE_COLS:
            fields.append(pa.field(c, pa.timestamp("ns")))
        else:
            fields.append(pa.field(c, pa.float64()))
    return pa.schema(fields)


# ======================================================================================
# Per-company engine
# ======================================================================================
class _Co:
    """State of one company: latest-vintage facts per (tag, end*8+cls) + calendar helpers."""

    def __init__(self, reps: list[int], dei_entries: list, first_filed: bool):
        self.S = {t: {} for t in GAAP_TAGS}
        self.reps = reps                                   # sorted anchor ends (days)
        self.ends = {t: [] for t in _TRACK}                # sorted instant ends per tracked tag
        self.annual: list[int] = []                        # sorted fiscal-year ends seen in 10-K forms
        self.annual_set: set[int] = set()
        self.dei = dei_entries                             # [(filed, end, total, nrows, accn)] sorted by filed
        self.dei_by_accn = {e[4]: e for e in dei_entries}
        self.first = first_filed

    # ---- calendar ---------------------------------------------------------------
    def cands(self, target: int, tol: int) -> list[int]:
        reps = self.reps
        lo = bisect.bisect_left(reps, target - tol)
        hi = bisect.bisect_right(reps, target + tol)
        c = reps[lo:hi]
        if len(c) > 1:
            c = sorted(c, key=lambda r: abs(r - target))
        return c

    def near1(self, target: int, tol: int):
        c = self.cands(target, tol)
        return c[0] if c else None

    def prev_q(self, rep: int):
        c = self.cands_window(rep - QGAP_HI, rep - QGAP_LO, rep - 91)
        return c

    def cands_window(self, lo: int, hi: int, pref: int):
        reps = self.reps
        i = bisect.bisect_left(reps, lo)
        j = bisect.bisect_right(reps, hi)
        if i >= j:
            return None
        if j - i == 1:
            return reps[i]
        return min(reps[i:j], key=lambda r: abs(r - pref))

    # ---- TTM ------------------------------------------------------------------------
    def find(self, R, target: int, tol: int, cls: int):
        S = self.S
        for r in self.cands(target, tol):
            x = R(S, r * 8 + cls)
            if x is not None:
                return x
        return None

    def discrete(self, R, rep: int):
        """Discrete-quarter value ending at `rep`: reported 3M fact, else YTD difference (same fiscal year)."""
        S = self.S
        r = R(S, rep * 8 + 1)
        if r is not None:
            return r
        for k in (2, 3, 4):
            x = R(S, rep * 8 + k)
            if x is None:
                continue
            for r2 in self._window_all(rep - QGAP_HI, rep - QGAP_LO):
                y = R(S, r2 * 8 + k - 1)
                if y is not None and y[2] is not None and x[2] is not None and abs(y[2] - x[2]) <= 8:
                    return x[0] - y[0], x[1], x[2]
        return None

    def _window_all(self, lo: int, hi: int) -> list[int]:
        reps = self.reps
        return reps[bisect.bisect_left(reps, lo):bisect.bisect_right(reps, hi)]

    def four_q(self, R, A: int):
        vals, srcs = 0.0, []
        rep = A
        for j in range(4):
            d = self.discrete(R, rep)
            if d is None:
                return None
            vals += d[0]
            srcs.append(d[1])
            if j < 3:
                rep = self.prev_q(rep)
                if rep is None:
                    return None
        return vals, "4Q", tuple(srcs)

    def ttm(self, R, A: int, cls: int, start_hint=None, zfill: bool = False):
        """-> (value, method, source_ids) | None."""
        S = self.S
        if cls == 4:
            cur = R(S, A * 8 + 4)
            if cur is not None:
                return cur[0], "FY", (cur[1],)
            if zfill:
                ap = self.near1(A - 364, 20)
                if ap is not None and R(S, ap * 8 + 4) is not None:
                    return 0.0, "FY", (-1,)
        elif cls in (1, 2, 3):
            cur = R(S, A * 8 + cls)
            st = cur[2] if cur is not None else start_hint
            if st is not None:
                fyp = self.find(R, st - 1, TTM_TOL, 4)
                py = self.find(R, A - 364, TTM_TOL, cls)
                if zfill and (cur is not None or fyp is not None or py is not None):
                    cur = cur if cur is not None else (0.0, -1, st)
                    fyp = fyp if fyp is not None else (0.0, -1, None)
                    py = py if py is not None else (0.0, -1, None)
                    if cur[1] == -1 and fyp[1] == -1 and py[1] == -1:
                        return None
                if cur is not None and fyp is not None and py is not None:
                    return fyp[0] + cur[0] - py[0], "YTD", (fyp[1], cur[1], py[1])
        else:
            return None
        return self.four_q(R, A)

    # ---- instants ---------------------------------------------------------------------
    def g(self, tag: str, A: int):
        v = self.S[tag].get(A * 8)
        return None if v is None else v[0]

    def first_of(self, tags, A: int):
        S = self.S
        k = A * 8
        for i, t in enumerate(tags):
            v = S[t].get(k)
            if v is not None:
                return v[0], i
        return None

    def last_before(self, tag: str, A: int):
        e = self.ends.get(tag)
        if not e:
            return None
        i = bisect.bisect_right(e, A)
        return e[i - 1] if i else None

    def gc(self, tag: str, A: int, flags: set, maxdays: int = 400):
        """Same-period value, else carry-forward of the latest earlier observation (<= maxdays old)."""
        v = self.S[tag].get(A * 8)
        if v is not None:
            return v[0]
        le = self.last_before(tag, A - 1)
        if le is not None and A - le <= maxdays:
            v = self.S[tag].get(le * 8)
            if v is not None:
                flags.add("carry_fwd")
                return v[0]
        return None

    def assets(self, A: int, flags: set | None = None):
        a = self.g("Assets", A)
        if a is not None:
            return a
        a = self.g("LiabilitiesAndStockholdersEquity", A)
        if a is not None and flags is not None:
            flags.add("assets_from_lse")
        return a

    def equity(self, A: int, flags: set | None = None):
        """-> (equity_parent, equity_total, minority_interest)."""
        fl = flags if flags is not None else set()
        eq_p = self.g("StockholdersEquity", A)
        eq_t = self.g("StockholdersEquityIncludingPortionAttributableToNoncontrollingInterest", A)
        mi = None
        mi_parts = [self.g(t, A) for t in T_MI]
        if any(x is not None for x in mi_parts):
            mi = sum(x for x in mi_parts if x is not None)
        elif eq_p is not None and eq_t is not None:
            mi = eq_t - eq_p
        if eq_p is None and eq_t is not None:
            eq_p = eq_t - (mi or 0.0)
            fl.add("eq_derived")
        if eq_t is None:
            if eq_p is not None:
                eq_t = eq_p + (mi or 0.0)
            else:
                a = self.g("Assets", A)
                li = self.g("Liabilities", A)
                if a is not None and li is not None:
                    eq_t = a - li
                    fl.add("eq_derived")
        return eq_p, eq_t, mi

    def cash(self, A: int, flags: set | None = None):
        r = self.first_of(T_CASH, A)
        if r is None:
            return None
        if r[1] > 0 and flags is not None:
            flags.add("cash_alt")
        return r[0]

    def finance_lease(self, A: int, flags: set):
        tot = self.gc("FinanceLeaseLiability", A, flags)
        if tot is not None:
            return tot
        c = self.gc("FinanceLeaseLiabilityCurrent", A, flags)
        n = self.gc("FinanceLeaseLiabilityNoncurrent", A, flags)
        if c is not None or n is not None:
            return (c or 0.0) + (n or 0.0)
        tot = self.gc("CapitalLeaseObligations", A, flags)
        if tot is not None:
            return tot
        c = self.gc("CapitalLeaseObligationsCurrent", A, flags)
        n = self.gc("CapitalLeaseObligationsNoncurrent", A, flags)
        if c is not None or n is not None:
            return (c or 0.0) + (n or 0.0)
        return None

    def recent_debt_tag(self, A: int, tags=None) -> bool:
        """Any debt-like tag with a NON-ZERO value observed in the last 8 quarters (A-730, A]?"""
        S = self.S
        for t in (T_DEBT_LIKE if tags is None else tags):
            e = self.ends.get(t)
            if not e:
                continue
            j = bisect.bisect_right(e, A)
            while j > 0:
                j -= 1
                if e[j] <= A - 730:
                    break
                v = S[t].get(e[j] * 8)
                if v is not None and v[0] != 0:
                    return True
        return False

    def debt(self, A: int, flags: set, int_ttm_fn, assets):
        """Total interest-bearing debt per research/03 s5.2.  -> (total, current, noncurrent, finance_lease)."""
        g = self.g
        fl = self.finance_lease(A, flags)
        stb = g("ShortTermBorrowings", A)
        cp = g("CommercialPaper", A)
        st_vals = [g(t, A) for t in T_ST_OTHER]
        st_other = None
        if any(v is not None for v in st_vals):
            st_other = sum(v for v in st_vals if v is not None)
        if st_other is None:
            st_other = g("ShortTermBankLoansAndNotesPayable", A)
        variants = [st_other]
        if stb is not None and cp is not None and cp > 0:
            variants.append(st_other - cp)                    # CommercialPaper nested inside ShortTermBorrowings
        res = []
        for v in variants:
            fv: set[str] = set()
            res.append((self._debt_core(A, fv, v), fv))
        pick = 0
        if len(res) == 2:
            comb = g("DebtLongtermAndShorttermCombinedAmount", A)
            dcur = g("DebtCurrent", A)
            ltdc = g("LongTermDebtCurrent", A)
            if comb is not None and comb > 0:
                errs = [abs((r[0][0] if r[0][0] is not None else 1e30) - comb) / comb for r in res]
                if min(errs) <= 0.02:
                    pick = int(np.argmin(errs))
            elif dcur is not None:
                want = dcur - (ltdc or 0.0)
                errs = [abs((v or 0.0) - want) / max(abs(want), 1.0) for v in variants]
                if min(errs) <= 0.02:
                    pick = int(np.argmin(errs))
        (total, cur, nc, leases_in), fv = res[pick]
        flags |= fv

        if total is None:
            # explicit zero rule (research/03 s4): no non-zero debt tag in the last 8 quarters AND positive evidence
            # that interest expense is ~0: a reported interest TTM, or the income-statement bridge
            # (true OperatingIncomeLoss - pretax); a filer with neither is inferred debt-free only if tiny.
            if not self.recent_debt_tag(A):
                ie = int_ttm_fn()
                thr = 0.0005 * assets if (assets is not None and assets > 0) else 0.0
                if ie is not None:
                    ok = ie <= thr
                else:
                    ok = assets is not None and assets < 2.5e8
                if ok:
                    total, cur, nc = 0.0, 0.0, 0.0
                    flags.add("debt_zero_inferred")
            if total is None:
                return NAN, NAN, NAN, fl
        else:
            if cur is None and nc is not None:
                cur = total - nc
            if nc is None:
                nc = NAN if cur is None else total - cur
        if fl is not None and not leases_in:
            total = total + fl
        return total, (NAN if cur is None else cur), (NAN if nc is None else nc), fl

    def _debt_core(self, A: int, flags: set, st_other):
        """-> (total_ex_finance_lease | None, current, noncurrent, leases_already_included)."""
        g = self.g
        ltd = g("LongTermDebt", A)
        ltd_il = g("LongTermDebtAndCapitalLeaseObligationsIncludingCurrentMaturities", A)
        ltd_nc = g("LongTermDebtNoncurrent", A)
        ltd_c = g("LongTermDebtCurrent", A)
        dcur = g("DebtCurrent", A)
        so = st_other or 0.0
        leases_in = False
        total = cur = nc = None

        if ltd is not None:                                    # LongTermDebt already includes current maturities
            total = ltd + so
            nc = ltd_nc
            if ltd_nc is not None and ltd_c is not None and ltd > 0 and abs(ltd - (ltd_nc + ltd_c)) > 0.02 * ltd \
                    and abs(ltd - ltd_nc) <= 0.01 * ltd:       # this filer's LongTermDebt excludes the current part
                total = ltd + ltd_c + so
                flags.add("ltd_excl_current")
            elif ltd_nc is None:
                # LongTermDebt may be NON-current only (TSLA): arbitrate with an independent total if one exists
                cur_alt = dcur if dcur is not None else ((ltd_c or 0.0) + so if (ltd_c is not None or so) else None)
                ref = g("DebtLongtermAndShorttermCombinedAmount", A)
                if ref is None:
                    ref = g("DebtInstrumentCarryingAmount", A)
                if cur_alt is not None and cur_alt > 0 and ref is not None and ref > 0:
                    incl, excl = ltd + so, ltd + cur_alt
                    if abs(excl - ref) <= 0.01 * ref and abs(incl - ref) > 0.02 * ref:
                        total = excl
                        nc = ltd
                        flags.add("ltd_excl_current")
            if nc is None and ltd_c is not None and "ltd_excl_current" not in flags:
                nc = ltd - ltd_c
        elif ltd_il is not None:
            total = ltd_il + so
            leases_in = True
        else:
            # --- non-current part
            ncv = None
            if ltd_nc is not None:
                ncv = ltd_nc
            else:
                v = g("LongTermDebtAndCapitalLeaseObligations", A)
                if v is not None:
                    ncv, leases_in = v, True
                else:
                    sm = None
                    for slot in T_NC_ALT_SLOTS:
                        for t in slot:
                            x = g(t, A)
                            if x is not None:
                                sm = (sm or 0.0) + x
                                break
                    if sm is None:
                        for t in T_NC_ALT_TOTALS:
                            x = g(t, A)
                            if x is not None:
                                sm = x
                                break
                    if sm is not None:
                        ncv = sm
                        flags.add("debt_lowconf")
                    else:
                        v = g("DebtAndCapitalLeaseObligations", A)
                        if v is not None:
                            ncv, leases_in = v, True
                            flags.add("debt_lowconf")
                        else:
                            v = g("DebtLongtermAndShorttermCombinedAmount", A)
                            if v is not None:
                                total = v
                                flags.add("debt_lowconf")
                            else:
                                v = g("DebtInstrumentCarryingAmount", A)
                                if v is not None:
                                    ncv = v
                                    flags.add("debt_lowconf")
            # --- current part
            curv = None
            ltdc_eff = ltd_c if ltd_c is not None else g("LongTermDebtAndCapitalLeaseObligationsCurrent", A)
            if dcur is not None:
                curv = dcur
                if ltdc_eff is not None:
                    if dcur < ltdc_eff * 0.995:
                        curv = dcur + ltdc_eff            # DebtCurrent does not contain the current LTD
                    elif abs(dcur - ltdc_eff) <= 0.005 * max(abs(ltdc_eff), 1.0) and st_other:
                        curv = dcur + st_other            # DebtCurrent == current LTD only; short-term borrowings separate
            elif ltdc_eff is not None or st_other is not None:
                curv = (ltdc_eff or 0.0) + so
            if total is None:
                if ncv is not None:
                    nc = ncv
                    cur = curv
                    total = ncv + (curv or 0.0)
                elif curv is not None:
                    if self.recent_debt_tag(A, _NC_DEBT_TAGS):
                        flags.add("debt_nc_missing")         # non-current notes untagged at A: do not understate
                    else:
                        total = curv
                        cur = curv
                        flags.add("debt_current_only")
        return total, cur, nc, leases_in

    # ---- shares --------------------------------------------------------------------------
    def shares_wavg(self, R, A: int, cls: int, flags: set | None, tag_prefix: str):
        """3M weighted-average share count of the quarter ending A (Q4 derived for 10-K periods)."""
        S = self.S
        r = R(S, A * 8 + 1)
        if r is not None:
            return r[0]
        if cls in (2, 3):
            r = R(S, A * 8 + cls)
            if r is not None:
                if flags is not None:
                    flags.add(f"{tag_prefix}_ytd")
                return r[0]
            return None
        if cls == 4:
            fy = R(S, A * 8 + 4)
            if fy is None:
                return None
            q, rep = [], A
            for _ in range(3):
                rep = self.prev_q(rep)
                if rep is None:
                    break
                x = R(S, rep * 8 + 1)
                if x is None:
                    break
                q.append(x[0])
            if len(q) == 3:
                d = 4 * fy[0] - sum(q)
                # +-25% of the FY weighted count (re-audit: a [0.5, 2.0] band let ~2x errors through when a
                # quarter's count was tagged on a different basis, e.g. NVDA FY2025 -> mcap $5.9T)
                if 0.75 * fy[0] <= d <= 1.25 * fy[0]:
                    if flags is not None:
                        flags.add(f"{tag_prefix}_q4derived")
                    return d
            if flags is not None:
                flags.add(f"{tag_prefix}_annual")
            return fy[0]
        return None

    def _sane(self, val: float, refs, D: int, own_filed: int) -> bool:
        """Scale-error filter for a cover count (PKG x1000, ORCL x1e6): PIT, uses only earlier information.
        Primary test = the company's own previous cover values (median of the last 4, ratio within 8x).
        A jump beyond 8x is kept only if an independent reference (diluted WASO / balance-sheet count) supports
        it (genuine split).  Without history, drop only if >= 2 references exist and none agrees.
        (Diluted WASO itself is often tagged in thousands, so it must not veto a cover count on its own.)"""
        if not (val > 0 and math.isfinite(val)):
            return False
        refs = [r for r in refs if r is not None and r > 0 and math.isfinite(r)]

        def agree(x):
            return 0.125 <= val / x <= 8.0

        prev = [e[2] for e in self.dei if e[0] < own_filed and e[0] <= D and e[2] > 0][-4:]
        if prev:
            if agree(float(np.median(prev))):
                return True
            return any(agree(r) for r in refs)
        if len(refs) < 2:
            return True
        return any(agree(r) for r in refs)

    def shares_out(self, accn: str, A: int, D: int, sh_dil, flags: set):
        """-> (shares, date_day) | (nan, None).  Own cover count -> balance-sheet count at A -> older cover count."""
        bs = self.S["CommonStockSharesOutstanding"].get(A * 8)
        bsv = None if bs is None else bs[0]
        own = self.dei_by_accn.get(accn)
        if own is not None:
            if self._sane(own[2], [sh_dil, bsv], D, own[0]):
                if own[3] > 1:
                    flags.add("multi_class_sum")
                return own[2], own[1]
            flags.add("shares_scale_dropped")
        if bsv is not None and self._sane(bsv, [sh_dil], D, D + 1):
            flags.add("shares_bs")
            return bsv, A
        for e in reversed(self.dei):                    # sorted by filed
            if e[0] > D:
                continue
            if D - e[1] > 400:
                break
            if e[4] == accn:
                continue
            if self._sane(e[2], [sh_dil, bsv], D, e[0]):
                flags.add("shares_stale")
                return e[2], e[1]
        return NAN, None

    # ---- earnings volatility ---------------------------------------------------------------
    def evol(self, A: int) -> float:
        vals = []
        rep = A
        for _ in range(20):
            d = self.discrete(R_ni, rep)
            a = self.assets(rep)
            if d is not None and a is not None and a > 0:
                vals.append(d[0] / a)
            rep = self.prev_q(rep)
            if rep is None:
                break
        if len(vals) >= 12:
            return float(np.std(vals, ddof=1))
        return NAN


# ======================================================================================
# One company -> snapshot rows
# ======================================================================================
def _fmt_flags(flags: set) -> str:
    return ";".join(sorted(flags))


def _company_rows(cik: int, d: dict, form_names: list[str], first_filed: bool) -> list[list]:
    """d: numpy arrays of the (already cleaned) rows of ONE company."""
    tid = d["tid"]
    is_dei = tid == DEI_ID
    # ---- dei cover-page share counts, aggregated per filing --------------------------
    dei_entries = []
    if is_dei.any():
        agg: dict[str, list] = {}
        di = np.nonzero(is_dei)[0]
        for i in di[np.argsort(d["end"][di], kind="stable")]:
            a = d["accn"][i]
            e = agg.get(a)
            en = int(d["end"][i])
            if e is None or en > e[1]:
                agg[a] = [int(d["filed"][i]), en, float(d["val"][i]), 1, a]
            elif en == e[1]:
                e[2] += float(d["val"][i])
                e[3] += 1
        dei_entries = sorted(agg.values(), key=lambda e: (e[0], e[1]))

    g = ~is_dei
    if not g.any():
        return []
    tid, start, end, cls = tid[g], d["start"][g], d["end"][g], d["cls"][g]
    val, filed, amend, k10 = d["val"][g], d["filed"][g], d["amend"][g], d["k10"][g]
    accn, formc = d["accn"][g], d["formc"][g]

    # ---- anchor calendar: collapse ends within ANCHOR_TOL days --------------------------
    ue, inv, cnt = np.unique(end, return_inverse=True, return_counts=True)
    inv = inv.reshape(-1)
    cl = np.concatenate(([0], np.cumsum(np.diff(ue) > ANCHOR_TOL)))
    order = np.lexsort((ue, cnt, cl))
    cls_sorted = cl[order]
    last = np.r_[cls_sorted[1:] != cls_sorted[:-1], True]
    rep_of_cluster = np.empty(cl[-1] + 1, dtype=np.int64)
    rep_of_cluster[cls_sorted[last]] = ue[order][last]
    rep_u = rep_of_cluster[cl]
    end_snap = rep_u[inv]
    reps = np.unique(rep_of_cluster).tolist()
    snap_of = dict(zip(ue.tolist(), rep_u.tolist()))

    key = end_snap * 8 + cls

    # ---- filings (balance-sheet carriers) ---------------------------------------------
    marker_ids = np.array([TAG_ID[t] for t in T_MARKER])
    mm = np.nonzero(np.isin(tid, marker_ids) & (cls == 0))[0]
    fil: dict[str, list] = {}
    for i in mm:
        a = accn[i]
        e = int(end[i])
        r = fil.get(a)
        if r is None:
            fil[a] = [e, int(filed[i]), int(formc[i]), bool(amend[i])]
        elif e > r[0]:
            r[0] = e
    if not fil:
        return []
    by_filed: dict[int, tuple] = {}
    for a, (pe, f, fc, am) in fil.items():
        cand = (pe, 0 if am else 1, a, fc)
        cur = by_filed.get(f)
        if cur is None or cand > cur:
            by_filed[f] = cand

    # ---- ingestion order -------------------------------------------------------------
    acodes = np.unique(accn, return_inverse=True)[1].reshape(-1)
    srt = np.lexsort((acodes, amend, filed))         # filed, then originals before amendments
    t_l = [USED_TAGS[i] for i in tid[srt].tolist()]
    k_l = key[srt].tolist()
    v_l = val[srt].tolist()
    s_l = start[srt].tolist()
    f_l = filed[srt].tolist()
    track = np.fromiter((USED_TAGS[i] in _TRACK for i in range(len(USED_TAGS))), dtype=bool)
    fg = np.zeros(len(srt), dtype=np.int8)
    fg[(track[tid] & (cls == 0))[srt]] = 1
    ann_ids = np.array([TAG_ID[t] for t in ANNUAL_CORE])
    fg[(np.isin(tid, ann_ids) & (cls == 4) & k10)[srt]] |= 2
    fg_l = fg.tolist()
    n = len(srt)

    co = _Co(reps, dei_entries, first_filed)
    S, ends_by_tag = co.S, co.ends
    insort = bisect.insort

    core_ids = [t for t in CORE_FLOW]
    rows: list[list] = []
    ptr = 0
    anchor_raw = -1
    for D in sorted(by_filed):
        pe_raw, _, accn_s, fc = by_filed[D]
        amend_anchor = pe_raw < anchor_raw
        if pe_raw > anchor_raw:
            anchor_raw = pe_raw
        while ptr < n and f_l[ptr] <= D:
            t = t_l[ptr]
            kk = k_l[ptr]
            dd = S[t]
            new = kk not in dd
            if new or not first_filed:
                dd[kk] = (v_l[ptr], s_l[ptr])
            f = fg_l[ptr]
            if f:
                if (f & 1) and new:
                    insort(ends_by_tag[t], kk >> 3)
                if f & 2:
                    e = kk >> 3
                    if e not in co.annual_set:
                        co.annual_set.add(e)
                        insort(co.annual, e)
            ptr += 1

        form = form_names[fc]
        A = snap_of[anchor_raw]
        flags: set[str] = set()
        if amend_anchor:
            flags.add("amend_anchor")

        # ---- duration class at the anchor --------------------------------------------
        is_q_form = form.startswith("10-Q")
        cls_t = 0
        for c in (4, 3, 2, 1):
            if c == 4 and is_q_form:
                continue
            kc = A * 8 + c
            if any(kc in S[t] for t in core_ids):
                cls_t = c
                break
        row = dict.fromkeys(COLUMNS, NAN)
        row["cik"] = cik
        row["accn"] = accn_s
        row["form"] = form
        row["filed"] = D
        row["period_end"] = anchor_raw
        row["fiscal_period"] = FISCAL_PERIOD.get(cls_t)

        # ---- TTM flows ----------------------------------------------------------------------
        methods: dict[str, str] = {}
        start_hint = None
        if cls_t in (1, 2, 3):
            for R0 in (R_ni, R_revenue, R_opinc, R_cfo):
                x = R0(S, A * 8 + cls_t)
                if x is not None and x[2] is not None:
                    start_hint = x[2]
                    break
        if cls_t:
            for name, (R, fmap, zfill) in FLOW_SPECS.items():
                r = co.ttm(R, A, cls_t, start_hint, zfill)
                if r is None:
                    continue
                v, meth, srcs = r
                row[name] = v
                methods[name] = meth
                if len({s for s in srcs if s >= 0}) > 1:
                    flags.add("mixed_tags")
                    flags.add("mix_" + name)
                for s in srcs:
                    fl_name = fmap.get(s // 16) if s >= 0 else None
                    if fl_name:
                        flags.add(fl_name)
                if zfill and -1 in srcs:
                    flags.add("acq_fill0")
                if meth == "4Q":
                    flags.add("ttm_4q")
            r = co.ttm(R_gp, A, cls_t)
            if r is not None:
                row["gross_profit"] = r[0]
                if r[1] == "4Q":
                    flags.add("ttm_4q")
            elif row["revenue"] == row["revenue"] and row["cogs"] == row["cogs"]:
                row["gross_profit"] = row["revenue"] - row["cogs"]
                flags.add("gp_derived")
            # Sanity guard (lead fix after the quality audit): a gross margin outside [-100%, 95%] means a
            # partial COGS tag (MUSA, CHRW) or a revenue sub-line (CAG 2015), not real economics -> missing.
            gp, rev = row.get("gross_profit"), row.get("revenue")
            if gp == gp and gp is not None and rev == rev and rev is not None:
                if rev <= 0 or not (-1.0 <= gp / rev <= 0.95):
                    row["gross_profit"] = float("nan")
                    flags.add("gp_implausible")
            if row["opinc"] == row["opinc"] and row["da"] == row["da"]:
                row["ebitda"] = row["opinc"] + row["da"]
        tm = "none"
        for nm in ("revenue", "net_income", "opinc", "cfo"):
            if nm in methods:
                tm = methods[nm]
                break
        row["ttm_method"] = tm

        # ---- fiscal-year history --------------------------------------------------------------------
        fy_list = co.annual[:bisect.bisect_right(co.annual, A)]
        fy_vals = {}
        for i in range(1, 6):
            if len(fy_list) < i:
                break
            E = fy_list[-i]
            row[f"fyend_fy{i}"] = E
            kfy = E * 8 + 4
            for c, R in (("revenue", R_revenue), ("opinc", R_opinc), ("cfo", R_cfo), ("capex", R_capex),
                         ("net_income", R_ni)):
                x = R(S, kfy)
                if x is not None:
                    row[f"{c}_fy{i}"] = x[0]
            if i == 1:
                x = R_da(S, kfy)
                if x is not None:
                    fy_vals["da"] = x[0]
        if fy_list:
            row["fy_end_date"] = fy_list[-1]
            row["revenue_lfy"] = row["revenue_fy1"]
            row["opinc_lfy"] = row["opinc_fy1"]
            row["net_income_lfy"] = row["net_income_fy1"]
            row["cfo_lfy"] = row["cfo_fy1"]
            row["capex_lfy"] = row["capex_fy1"]
            if "da" in fy_vals:
                row["da_lfy"] = fy_vals["da"]
                if row["opinc_lfy"] == row["opinc_lfy"]:
                    row["ebitda_lfy"] = row["opinc_lfy"] + fy_vals["da"]

        # ---- balance sheet --------------------------------------------------------------------------
        assets = co.assets(A, flags)
        row["assets"] = NAN if assets is None else assets
        for col, tag in (("current_assets", "AssetsCurrent"), ("current_liabilities", "LiabilitiesCurrent"),
                         ("retained_earnings", "RetainedEarningsAccumulatedDeficit")):
            x = co.g(tag, A)
            if x is not None:
                row[col] = x
        c = co.cash(A, flags)
        if c is not None:
            row["cash"] = c
        sti = [co.g(t, A) for t in T_STI]
        if any(x is not None for x in sti):
            row["st_investments"] = sum(x for x in sti if x is not None)
        else:
            x = co.g(T_STI_ALT[0], A)
            if x is not None:
                row["st_investments"] = x
        r = co.first_of(T_PPE, A)
        if r is not None:
            row["ppe_net"] = r[0]
        else:
            gr, acc = co.g(T_PPE_GROSS[0], A), co.g(T_PPE_GROSS[1], A)
            if gr is not None and acc is not None:
                row["ppe_net"] = gr - acc
                flags.add("ppe_derived")
        og = co.first_of(T_OG_NET, A)
        og = og[0] if og is not None else None
        if og is None:
            for gt, at in T_OG_GROSS:
                gr, acc = co.g(gt, A), co.g(at, A)
                if gr is not None and acc is not None:
                    og = gr - acc
                    break
        if og is not None and og > 0:
            ppe = row.get("ppe_net")
            if ppe is None or ppe != ppe:
                row["ppe_net"] = og
                flags.add("ppe_oilgas")
            elif ppe < 0.9 * og:          # PP&E line is only "other" PP&E (RRC): add the oil & gas properties
                row["ppe_net"] = ppe + og
                flags.add("ppe_plus_oilgas")
        x = co.gc("Goodwill", A, flags)
        if x is not None:
            row["goodwill"] = x
        x = co.gc("IntangibleAssetsNetExcludingGoodwill", A, flags)
        if x is not None:
            row["intangibles"] = x
        eq_p, eq_t, mi = co.equity(A, flags)
        if eq_p is not None:
            row["equity_parent"] = eq_p
        if eq_t is not None:
            row["equity_total"] = eq_t
        if mi is not None:
            row["minority_interest"] = mi
        li = co.g("Liabilities", A)
        if li is None:
            lse = co.g("LiabilitiesAndStockholdersEquity", A)
            if lse is not None and eq_t is not None:
                li = lse - eq_t
                flags.add("liab_derived")
        if li is not None:
            row["liabilities"] = li
        r = co.first_of(T_PREF, A)
        if r is not None:
            row["preferred"] = r[0]

        def int_fn():
            ie = row["interest_exp"]
            if ie == ie:
                return ie
            if "ebit_proxy" not in flags and row["opinc"] == row["opinc"] and row["pretax"] == row["pretax"]:
                return row["opinc"] - row["pretax"]
            return None

        tdebt, dcur, dnc, fl = co.debt(A, flags, int_fn, assets)
        row["total_debt"], row["debt_current"], row["debt_noncurrent"] = tdebt, dcur, dnc
        if fl is not None:
            row["finance_lease"] = fl
        olt = co.gc("OperatingLeaseLiability", A, flags)
        olc = co.gc("OperatingLeaseLiabilityCurrent", A, flags)
        oln = co.gc("OperatingLeaseLiabilityNoncurrent", A, flags)
        if olc is not None:
            row["op_lease_current"] = olc
        if oln is not None:
            row["op_lease_noncurrent"] = oln
        elif olt is not None:
            row["op_lease_noncurrent"] = olt - (olc or 0.0)

        # ---- shares ----------------------------------------------------------------------------------
        sh_dil = co.shares_wavg(R_shdil, A, cls_t, flags, "sh_dil")
        if sh_dil is not None:
            row["shares_diluted"] = sh_dil
        sh_b = co.shares_wavg(R_shbas, A, cls_t, None, "sh_bas")
        if sh_b is not None:
            row["shares_basic"] = sh_b
        so, so_date = co.shares_out(accn_s, A, D, sh_dil, flags)
        row["shares_out"] = so
        if so_date is not None:
            row["shares_out_date"] = so_date
        if so == so and sh_dil is not None and sh_dil > 0 and not 0.125 <= so / sh_dil <= 8.0:
            flags.add("shares_mismatch")                 # one of the two counts is mis-scaled; trust shares_out

        # ---- history ~1 year earlier ------------------------------------------------------------------
        ap = co.near1(A - 364, 20)
        if ap is not None:
            x = co.assets(ap)
            if x is not None:
                row["assets_4q"] = x
            x = co.equity(ap)[1]
            if x is not None:
                row["equity_total_4q"] = x
            x = co.cash(ap)
            if x is not None:
                row["cash_4q"] = x
            fl4: set[str] = set()

            def int_fn4():
                if not cls_t:
                    return None
                ri = co.ttm(R_interest, ap, cls_t, None)
                if ri is not None:
                    return ri[0]
                r1 = co.ttm(R_opinc_true, ap, cls_t, None)
                r2 = co.ttm(R_pretax, ap, cls_t, None)
                if r1 is not None and r2 is not None:
                    return r1[0] - r2[0]
                return None

            td4 = co.debt(ap, fl4, int_fn4, co.assets(ap))[0]
            row["total_debt_4q"] = td4
            if cls_t:
                x = co.shares_wavg(R_shdil, ap, cls_t, None, "sh_dil")
                if x is not None:
                    row["shares_diluted_4q"] = x
                for nm, R in (("opinc", R_opinc), ("revenue", R_revenue)):
                    r = co.ttm(R, ap, cls_t, None)
                    if r is not None:
                        row[f"{nm}_ttm_4q"] = r[0]
        row["evol"] = co.evol(A)

        row["flags"] = _fmt_flags(flags)
        rows.append([row[c] for c in COLUMNS])
    return rows


# ======================================================================================
# Partition / frame level
# ======================================================================================
_LOAD_COLUMNS = ["cik", "tag", "unit", "start", "end", "val", "filed", "form", "accn"]


def _prep_frame(p: pd.DataFrame):
    """Facts DataFrame -> dict of numpy arrays (cleaned, sorted by cik) + form names."""
    tagc = p["tag"] if isinstance(p["tag"].dtype, pd.CategoricalDtype) else p["tag"].astype("category")
    tcats = list(tagc.cat.categories)
    tid_of_cat = np.array([TAG_ID.get(c, -1) for c in tcats], dtype=np.int64)
    tid = tid_of_cat[tagc.cat.codes.to_numpy()]

    unitc = p["unit"] if isinstance(p["unit"].dtype, pd.CategoricalDtype) else p["unit"].astype("category")
    ucats = list(unitc.cat.categories)
    exp_code = np.array([ucats.index(TAG_UNIT[t]) if TAG_UNIT[t] in ucats else -2 for t in USED_TAGS] + [-3])
    unit_ok = unitc.cat.codes.to_numpy() == exp_code[tid]          # tid == -1 -> last slot (-3) -> False

    def days(col):
        a = p[col].to_numpy().astype("datetime64[D]")
        nat = np.isnat(a)
        return a.astype(np.int64), nat

    st, st_nat = days("start")
    en, _ = days("end")
    fi, _ = days("filed")
    st = np.where(st_nat, NOSTART, st)
    val = p["val"].to_numpy(dtype=np.float64)
    dur = en - st + 1
    cls = np.zeros(len(p), dtype=np.int8)
    for c, lo, hi in CLS_WINDOWS:
        cls[(dur >= lo) & (dur <= hi)] = c
    ok = unit_ok & np.isfinite(val) & (en <= fi + 5) & (st_nat | (cls > 0))
    ok &= tid >= 0

    formc = p["form"] if isinstance(p["form"].dtype, pd.CategoricalDtype) else p["form"].astype("category")
    form_names = list(formc.cat.categories)
    fcodes = formc.cat.codes.to_numpy()
    amend_cat = np.array([f.endswith("/A") for f in form_names] + [False])
    k10_cat = np.array([f.startswith("10-K") for f in form_names] + [False])

    cik = p["cik"].to_numpy(dtype=np.int64)
    accn = p["accn"].to_numpy(dtype=object)
    idx = np.nonzero(ok)[0]
    idx = idx[np.argsort(cik[idx], kind="stable")]
    arrays = dict(
        cik=cik[idx], tid=tid[idx], start=st[idx], end=en[idx], cls=cls[idx], val=val[idx], filed=fi[idx],
        amend=amend_cat[fcodes[idx]], k10=k10_cat[fcodes[idx]], formc=fcodes[idx], accn=accn[idx],
    )
    return arrays, form_names


def _rows_to_frame(rows: list[list]) -> pd.DataFrame:
    df = pd.DataFrame(rows, columns=COLUMNS)
    df["cik"] = df["cik"].astype("int64")
    for c in DATE_COLS:
        df[c] = pd.to_datetime(df[c].astype("float64"), unit="D").astype("datetime64[ns]")
    for c in COLUMNS:
        if c not in STR_COLS and c not in DATE_COLS and c != "cik":
            df[c] = df[c].astype("float64")
    for c in STR_COLS:
        df[c] = df[c].astype(object).where(df[c].notna(), None)
    return df


def _frame_snapshots(p: pd.DataFrame, first_filed: bool) -> pd.DataFrame:
    arrays, form_names = _prep_frame(p)
    cik = arrays["cik"]
    if len(cik) == 0:
        return _rows_to_frame([])
    bounds = np.flatnonzero(np.r_[True, cik[1:] != cik[:-1], True])
    rows: list[list] = []
    for a, b in zip(bounds[:-1], bounds[1:]):
        d = {k: v[a:b] for k, v in arrays.items()}
        try:
            rows.extend(_company_rows(int(cik[a]), d, form_names, first_filed))
        except Exception:  # never let one company kill a partition
            log.exception("fundamentals: company %s failed", int(cik[a]))
    df = _rows_to_frame(rows)
    return df.sort_values(["cik", "filed", "period_end"], kind="stable").reset_index(drop=True)


def snapshots_from_facts(facts: pd.DataFrame, first_filed: bool = False) -> pd.DataFrame:
    """Snapshots for an in-memory facts frame (``quant.data.sec`` schema; any number of ciks)."""
    f = facts.copy()
    for c in ("tag", "unit", "form"):
        f[c] = f[c].astype("category")
    for c in ("start", "end", "filed"):
        f[c] = pd.to_datetime(f[c]).astype("datetime64[ns]")
    return _frame_snapshots(f, first_filed)


def _build_partition(args) -> tuple[int, int, str]:
    part, ciks, parts_dir, first_filed = args
    was_enabled = gc.isenabled()
    gc.disable()
    try:
        p = _sec.load_partition(part, tags=list(USED_TAGS), columns=_LOAD_COLUMNS, ciks=ciks)
        df = _frame_snapshots(p, first_filed)
        del p
    finally:
        if was_enabled:
            gc.enable()
    path = Path(parts_dir) / f"part-{part:02d}.parquet"
    table = pa.Table.from_pandas(df, schema=_arrow_schema(), preserve_index=False)
    pq.write_table(table, path, compression="zstd")
    return part, len(df), str(path)


def _is_current(path: Path, first_filed: bool) -> bool:
    try:
        md = pq.read_schema(path).metadata or {}
    except Exception:
        return False
    return md.get(b"fundamentals_version") == BUILD_VERSION.encode() and \
        md.get(b"first_filed") == str(first_filed).encode()


def build_snapshots(ciks: list[int] | None = None, n_jobs: int = 8, force: bool = False,
                    out_path: Path | str | None = None, first_filed: bool = False) -> Path:
    """Build the snapshot table; returns its path.

    ``ciks=None`` builds the whole universe into ``cache/fundamentals/snapshots.parquet`` (or
    ``snapshots_first.parquet`` with ``first_filed=True``: as-originally-reported vintages, no restatement
    leakage). A ``ciks`` subset never touches those files: it goes to ``out_path`` (default
    ``cache/fundamentals/snapshots_subset.parquet``).
    """
    if out_path is not None:
        out = Path(out_path)
    elif ciks is None:
        out = SNAP_FIRST_PATH if first_filed else SNAP_PATH
    else:
        out = FUND_DIR / "snapshots_subset.parquet"
    if ciks is None and out.exists() and not force and _is_current(out, first_filed):
        log.info("fundamentals: %s is current (use force=True to rebuild)", out)
        return out
    out.parent.mkdir(parents=True, exist_ok=True)
    parts_dir = out.parent / (out.stem + "_parts")
    shutil.rmtree(parts_dir, ignore_errors=True)
    parts_dir.mkdir(parents=True)

    if ciks is None:
        tasks = [(p, None, str(parts_dir), first_filed) for p in _sec.list_partitions()]
        if not tasks:
            raise FileNotFoundError("no SEC facts partitions; run quant.data.sec.build_facts()")
    else:
        by_part: dict[int, list[int]] = {}
        for c in sorted({int(c) for c in ciks}):
            by_part.setdefault(_sec.cik_to_partition(c), []).append(c)
        tasks = [(p, cs, str(parts_dir), first_filed) for p, cs in sorted(by_part.items())]

    t0 = time.time()
    results = []
    if n_jobs <= 1 or len(tasks) == 1:
        for t in tasks:
            results.append(_build_partition(t))
    else:
        with ProcessPoolExecutor(max_workers=min(n_jobs, len(tasks))) as ex:
            for i, res in enumerate(ex.map(_build_partition, tasks), 1):
                results.append(res)
                log.info("fundamentals: partition %02d done (%d rows) [%d/%d, %.0fs]", res[0], res[1], i,
                         len(tasks), time.time() - t0)
    schema = _arrow_schema().with_metadata({
        "fundamentals_version": BUILD_VERSION, "first_filed": str(first_filed), "built_at": pd.Timestamp.now().isoformat(),
    })
    tables = [pq.read_table(r[2]) for r in sorted(results)]
    table = pa.concat_tables(tables).cast(_arrow_schema())
    # global sort by (cik, filed, period_end)
    idx = pc.sort_indices(table, sort_keys=[("cik", "ascending"), ("filed", "ascending"),
                                                    ("period_end", "ascending")])
    table = table.take(idx).replace_schema_metadata(schema.metadata)
    tmp = out.with_suffix(".tmp")
    pq.write_table(table, tmp, compression="zstd", row_group_size=200_000)
    tmp.replace(out)
    shutil.rmtree(parts_dir, ignore_errors=True)
    log.info("fundamentals: wrote %s (%d rows, %d cols) in %.0fs", out, table.num_rows, table.num_columns,
             time.time() - t0)
    return out


# ======================================================================================
# Loading / as-of
# ======================================================================================
def load_snapshots(columns: list[str] | None = None, path: Path | str | None = None,
                   first_filed: bool = False) -> pd.DataFrame:
    """The snapshot table (sorted by cik, filed)."""
    path = Path(path) if path is not None else (SNAP_FIRST_PATH if first_filed else SNAP_PATH)
    if not path.exists():
        raise FileNotFoundError(f"{path} missing; run quant.data.fundamentals.build_snapshots()")
    return pq.read_table(path, columns=list(columns) if columns is not None else None).to_pandas()


def asof(snaps: pd.DataFrame, date, max_age_days: int = 200) -> pd.DataFrame:
    """Latest snapshot per cik usable at `date`: ``filed < date`` (strict: a filing dated `date` is NOT usable)
    and ``period_end >= date - max_age_days``. Index = cik; ``filed`` and ``period_end`` stay as columns."""
    d = pd.Timestamp(date).normalize()
    if d.tzinfo is not None:
        d = d.tz_localize(None)
    d = d.as_unit("ns") if hasattr(d, "as_unit") else d
    filed = snaps["filed"]
    sub = snaps[(filed < d).to_numpy()]
    if len(sub) == 0:
        return sub.set_index("cik")
    cik = sub["cik"].to_numpy()
    f = sub["filed"].to_numpy()
    in_order = bool(np.all((cik[1:] > cik[:-1]) | ((cik[1:] == cik[:-1]) & (f[1:] >= f[:-1])))) if len(sub) > 1 else True
    if not in_order:
        sub = sub.sort_values(["cik", "filed", "period_end"], kind="stable")
    last = sub.drop_duplicates("cik", keep="last")
    last = last[(last["period_end"] >= d - pd.Timedelta(days=max_age_days)).to_numpy()]
    return last.set_index("cik")


# ======================================================================================
# CLI
# ======================================================================================
def main(argv: list[str] | None = None) -> None:
    ap = argparse.ArgumentParser(description="Build point-in-time fundamentals snapshots")
    ap.add_argument("--force", action="store_true")
    ap.add_argument("--jobs", type=int, default=8)
    ap.add_argument("--first-filed", action="store_true", help="as-originally-reported vintages")
    ap.add_argument("--ciks", type=int, nargs="*", default=None)
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s")
    t0 = time.time()
    path = build_snapshots(a.ciks or None, n_jobs=a.jobs, force=a.force, first_filed=a.first_filed)
    print(f"{path}  ({time.time() - t0:.0f}s)")


if __name__ == "__main__":
    main()
