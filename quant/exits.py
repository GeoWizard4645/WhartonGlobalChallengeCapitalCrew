"""When to sell what the strategies buy, what such a pick returned in the backtest, and a check of open positions.

    .venv/bin/python -m quant.exits check      # what to do today with each position in output/orders.csv
    .venv/bin/python -m quant.exits stats      # recompute output/holding_stats.csv (quant.run also writes it)

Exit rules: exactly what the backtests did (nothing here was tuned).
  quality_momentum  Re-ranked at every month-end close. Still in the top N: hold another month. Dropped out: sell at
                    the next day's close. No stop loss (the backtests had none).
  magic_formula     Hold 12 months (Greenblatt): sell at the close after the first month-end at least 12 months
                    after the purchase. No early exit on price.
  both              Sell at the next close if a takeover is announced (the price is pinned to the deal) or the
                    screen's inputs prove wrong; such names go in DO_NOT_BUY (quant/trade_plan.py).

Expected returns (output/holding_stats.csv): for every month-end signal in the backtest, each pick's total return
from the trade (the next close) over its first month and to its exit under the rules above (until it drops out of
the top N for momentum, 12 months for the Magic Formula), next to the average stock the strategy could have
bought over the same days. Summarized for the 5 best-ranked picks and for all picks, over 2011-2026 and 2019-2026.
Before 2019 the price data misses many companies that were later delisted, so 2019-2026 is the cleaner window.
"""
from __future__ import annotations

import argparse
import json
import logging

import numpy as np
import pandas as pd
from pandas.tseries.holiday import (AbstractHolidayCalendar, GoodFriday, Holiday, USLaborDay, USMartinLutherKingJr,
                                    USMemorialDay, USPresidentsDay, USThanksgivingDay, nearest_workday,
                                    sunday_to_monday)
from pandas.tseries.offsets import CustomBusinessDay, CustomBusinessMonthEnd

from quant import settings

log = logging.getLogger(__name__)

STATS_FILE = settings.OUTPUT / "holding_stats.csv"
ORDERS_FILE = settings.OUTPUT / "orders.csv"
PARAMS_FILE = settings.OUTPUT / "chosen_params.json"
MF_HOLD_MONTHS = 12
TOP = 5                      # the "top5" rows of the stats: picks ranked 1-5 at the signal
CLEAN_WINDOW = "2019-2026"   # the window trade_plan quotes expected returns from

RULES = {
    "quality_momentum": "re-ranked each month-end: hold while in the top N, sell at the next close once it drops out",
    "magic_formula": "hold 12 months: sell at the close after the first month-end 12 months on; no exit on price",
}
RULES["momentum_mf"] = RULES["quality_momentum"]
EARLY_EXIT = "either: sell at the next close if a takeover is announced or the screen's inputs prove wrong"


# --------------------------------------------------------------------------------------------------
# trading calendar (future dates: review days, planned sales)
# --------------------------------------------------------------------------------------------------
class NYSECalendar(AbstractHolidayCalendar):
    rules = [
        Holiday("New Year's Day", month=1, day=1, observance=sunday_to_monday),   # no Friday holiday on Dec 31
        USMartinLutherKingJr, USPresidentsDay, GoodFriday, USMemorialDay,
        Holiday("Juneteenth", month=6, day=19, start_date="2022-01-01", observance=nearest_workday),
        Holiday("Independence Day", month=7, day=4, observance=nearest_workday),
        USLaborDay, USThanksgivingDay,
        Holiday("Christmas", month=12, day=25, observance=nearest_workday),
    ]


_DAY = CustomBusinessDay(calendar=NYSECalendar())
_MONTH_END = CustomBusinessMonthEnd(calendar=NYSECalendar())


def next_trading_day(d) -> pd.Timestamp:
    return pd.Timestamp(d).normalize() + _DAY


def month_end_on_or_after(d) -> pd.Timestamp:
    """The last trading day of ``d``'s month (``d`` itself if it is that day), else of the next month."""
    return _MONTH_END.rollforward(pd.Timestamp(d).normalize())


def review_after(entry, n: int = 1) -> pd.Timestamp:
    """The ``n``-th month-end review after a purchase on ``entry`` (a sale after it happens at the next close)."""
    r = month_end_on_or_after(next_trading_day(entry))
    for _ in range(n - 1):
        r = month_end_on_or_after(next_trading_day(r))
    return r


def exit_plan(strategy: str, entry) -> dict:
    """Dates for a position bought on ``entry``: the first month-end review and the planned sale date.

    Momentum has no planned sale: each review decides, and a sale happens at the close after the review.
    """
    entry = pd.Timestamp(entry).normalize()
    if strategy == "magic_formula":
        review = month_end_on_or_after(entry + pd.DateOffset(months=MF_HOLD_MONTHS))
        return dict(first_review=review, planned_sale=next_trading_day(review))
    return dict(first_review=review_after(entry), planned_sale=pd.NaT)


# --------------------------------------------------------------------------------------------------
# what picks returned in the backtest
# --------------------------------------------------------------------------------------------------
def _trade_day(dates: pd.DatetimeIndex, t) -> pd.Timestamp | None:
    i = dates.searchsorted(pd.Timestamp(t), side="right")
    return dates[i] if i < len(dates) else None


def fwd_returns(P: pd.DataFrame, tickers, a, b) -> pd.Series:
    """Total return from the close of ``a`` to the close of ``b``; a name delisted in between exits at its last
    price (as in the engine). Names without a price on ``a`` are left out."""
    w = P.loc[a:b, [t for t in dict.fromkeys(tickers) if t in P.columns]]
    if w.empty:
        return pd.Series(dtype=float)
    first, last = w.iloc[0], w.ffill().iloc[-1]
    ok = first.notna() & (first > 0)
    return (last[ok] / first[ok] - 1.0).astype(float)


def _qm_rows(ctx, params: dict, end) -> list[dict]:
    from quant.strategies import quality_momentum as qm

    p = qm._params(params)
    sig = [qm._snap(ctx, d) for d in ctx.month_ends(qm.first_signal_date(ctx), end)]
    held = [qm._signal(ctx, t, p)["tickers"][: p["N"]] for t in sig]
    held_sets = [set(h) for h in held]
    univ = [qm._frame(ctx, t, p["mom_type"])["yf_ticker"].tolist() for t in sig]
    trade = [_trade_day(ctx.dates, t) for t in sig]
    P, rows, ucache = ctx.adjclose, [], {}

    def univ_ret(i, j):
        if (i, j) not in ucache:
            ucache[(i, j)] = float(fwd_returns(P, univ[i], trade[i], trade[j]).mean())
        return ucache[(i, j)]

    for i in range(len(sig) - 1):
        if trade[i] is None or trade[i + 1] is None:
            continue
        r1 = fwd_returns(P, held[i], trade[i], trade[i + 1])
        for k, tk in enumerate(held[i], start=1):
            if tk not in r1.index:
                continue
            base = dict(strategy="quality_momentum", signal=sig[i], rank=k, ticker=tk, entry=trade[i])
            rows.append(dict(base, horizon="first_month", exit=trade[i + 1], months=1, ret=r1[tk],
                             universe=univ_ret(i, i + 1)))
            j = i + 1
            while j < len(sig) and tk in held_sets[j]:
                j += 1
            if j < len(sig) and trade[j] is not None:            # still held at the last signal: not finished
                r = fwd_returns(P, [tk], trade[i], trade[j])
                rows.append(dict(base, horizon="to_exit", exit=trade[j], months=j - i,
                                 ret=float(r.iloc[0]) if len(r) else np.nan, universe=univ_ret(i, j)))
    return rows


def _mf_rows(ctx, params: dict, end) -> list[dict]:
    from quant.strategies import magic_formula as mf

    p = mf._params(params)
    dates = mf.signal_dates(ctx, mf.common_start(ctx), end)
    snap = [ctx.trading_day_on_or_before(d) for d in dates]
    trade = [_trade_day(ctx.dates, t) for t in snap]
    P, rows = ctx.adjclose, []
    for i, d in enumerate(dates):
        if trade[i] is None or i + 1 >= len(dates) or trade[i + 1] is None:
            continue
        tab = mf._table(ctx, d, p)
        picks = tab[tab["selected"]].drop_duplicates("yf_ticker").sort_values("final_rank")["yf_ticker"].tolist()
        univ = tab.loc[tab["eligible"].astype(bool), "yf_ticker"].unique().tolist()
        horizons = [("first_month", i + 1, 1)]
        if i + MF_HOLD_MONTHS < len(dates) and trade[i + MF_HOLD_MONTHS] is not None:
            horizons.append(("to_exit", i + MF_HOLD_MONTHS, MF_HOLD_MONTHS))
        for h, j, months in horizons:
            r = fwd_returns(P, picks, trade[i], trade[j])
            u = float(fwd_returns(P, univ, trade[i], trade[j]).mean())
            for k, tk in enumerate(picks, start=1):
                if tk in r.index:
                    rows.append(dict(strategy="magic_formula", signal=snap[i], rank=k, ticker=tk, entry=trade[i],
                                     horizon=h, exit=trade[j], months=months, ret=r[tk], universe=u))
    return rows


def pick_returns(ctx, chosen: dict, end) -> pd.DataFrame:
    """One row per (signal, pick, horizon) of the chosen settings' backtests."""
    rows = _qm_rows(ctx, chosen["quality_momentum"], end) + _mf_rows(ctx, chosen["magic_formula"], end)
    return pd.DataFrame(rows)


def summarize(rows: pd.DataFrame) -> pd.DataFrame:
    out = []
    rows = rows.dropna(subset=["ret"])
    for (strategy, horizon), g in rows.groupby(["strategy", "horizon"], sort=False):
        for picks, gg in ((f"top{TOP}", g[g["rank"] <= TOP]), ("all", g)):
            for window, w in (("2011-2026", gg), (CLEAN_WINDOW, gg[gg["entry"] >= pd.Timestamp(settings.TEST_START)])):
                x = w["ret"]
                out.append(dict(strategy=strategy, horizon=horizon, picks=picks, window=window, n=len(w),
                                months_avg=w["months"].mean(), months_median=w["months"].median(),
                                mean=x.mean(), median=x.median(), p25=x.quantile(0.25), p75=x.quantile(0.75),
                                pct_positive=(x > 0).mean(), mean_vs_universe=(x - w["universe"]).mean()))
    df = pd.DataFrame(out)
    num = ["months_avg", "mean", "median", "p25", "p75", "pct_positive", "mean_vs_universe"]
    df[num] = df[num].astype(float).round(4)
    return df


def write_stats(ctx, chosen: dict, end) -> pd.DataFrame:
    s = summarize(pick_returns(ctx, chosen, end))
    s.to_csv(STATS_FILE, index=False)
    return s


def load_stats() -> pd.DataFrame | None:
    return pd.read_csv(STATS_FILE) if STATS_FILE.exists() else None


def expected(stats: pd.DataFrame | None, strategy: str, horizon: str, picks: str = f"top{TOP}",
             window: str = CLEAN_WINDOW) -> dict:
    """The stats row for a pick like this one ({} if the stats have not been computed)."""
    if stats is None:
        return {}
    r = stats[(stats["strategy"] == strategy) & (stats["horizon"] == horizon) & (stats["picks"] == picks)
              & (stats["window"] == window)]
    return r.iloc[0].to_dict() if len(r) else {}


# --------------------------------------------------------------------------------------------------
# position check
# --------------------------------------------------------------------------------------------------
def _qm_status(ctx, p: dict, tk: str, entry: pd.Timestamp, today: pd.Timestamp) -> tuple[str, str]:
    from quant.strategies import quality_momentum as qm

    def rank_on(t):
        tick = qm._signal(ctx, qm._snap(ctx, t), p)["tickers"]
        return tick.index(tk) + 1 if tk in tick else None

    review = review_after(entry)
    while review <= today:                       # every month-end review since the purchase
        r = rank_on(review)
        if r is None or r > p["N"]:
            sell = next_trading_day(review)
            when = "now (overdue)" if sell <= today else f"at the close on {sell.date()}"
            return "SELL", f"dropped out of the top {p['N']} at the {review.date()} review (rank {r or '-'}); sell {when}"
        review = month_end_on_or_after(next_trading_day(review))
    r = rank_on(today)
    now = f"rank {r}" if r else "not ranked"
    verdict = "would stay" if r and r <= p["N"] else "would be sold"
    return "HOLD", f"next review {review.date()}; today {now} of top {p['N']} ({verdict} if that were the review)"


def _mf_status(tk: str, entry: pd.Timestamp, today: pd.Timestamp) -> tuple[str, str]:
    plan = exit_plan("magic_formula", entry)
    if today >= plan["first_review"]:
        sell = plan["planned_sale"]
        when = "now (overdue)" if sell <= today else f"at the close on {sell.date()}"
        return "SELL", f"12 months are up; sell {when}"
    return "HOLD", f"planned sale {plan['planned_sale'].date()} ({(plan['planned_sale'] - today).days} days)"


def check(orders_path=ORDERS_FILE) -> pd.DataFrame:
    """Action for every position in the order list as of the latest close: HOLD, SELL or REVIEW, with the reason."""
    from quant.data.context import get_context
    from quant.strategies import quality_momentum as qm
    from quant.trade_plan import DO_NOT_BUY

    o = pd.read_csv(orders_path, parse_dates=["entry_date"])
    ctx = get_context()
    today = ctx.dates[-1]
    qp = qm._params(json.loads(PARAMS_FILE.read_text())["quality_momentum"])
    rows = []
    for r in o.itertuples(index=False):
        entry = pd.Timestamp(r.entry_date)
        if entry > today:
            rows.append(dict(ticker=r.ticker, strategy=r.strategies, action="NOT YET BOUGHT", since_entry=np.nan,
                             reason=f"entry {entry.date()} is after the latest close {today.date()}"))
            continue
        ret = fwd_returns(ctx.adjclose, [r.ticker], entry, today)
        acts = []
        for s in str(r.strategies).split("+"):
            acts.append(_qm_status(ctx, qp, r.ticker, entry, today) if s == "quality_momentum"
                        else _mf_status(r.ticker, entry, today))
        action = "SELL" if all(a == "SELL" for a, _ in acts) else "HOLD"     # held for two strategies: both must sell
        reason = " | ".join(f"{s}: {why}" for s, (_, why) in zip(str(r.strategies).split("+"), acts))
        if r.ticker in DO_NOT_BUY:
            action, reason = "REVIEW", f"{DO_NOT_BUY[r.ticker]} | {reason}"
        rows.append(dict(ticker=r.ticker, strategy=r.strategies, action=action,
                         since_entry=float(ret.iloc[0]) if len(ret) else np.nan, reason=reason))
    out = pd.DataFrame(rows)
    pd.set_option("display.width", 220)
    pd.set_option("display.max_colwidth", 140)
    show = out.assign(since_entry=(out["since_entry"] * 100).round(1))
    print(f"Positions as of the {today.date()} close (since_entry = % total return from the entry-day close)")
    print(show.to_string(index=False))
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Exit rules: check open positions, or recompute the holding stats.")
    ap.add_argument("cmd", choices=["check", "stats"])
    ap.add_argument("--orders", default=str(ORDERS_FILE), help="order list to check (default output/orders.csv)")
    a = ap.parse_args(argv)
    logging.basicConfig(level=logging.INFO, format="%(asctime)s %(message)s", datefmt="%H:%M:%S")
    if a.cmd == "check":
        check(a.orders)
        return
    from quant.data.context import get_context
    from quant.run import last_complete_month_end
    ctx = get_context()
    s = write_stats(ctx, json.loads(PARAMS_FILE.read_text()), last_complete_month_end(ctx))
    print(s.to_string(index=False))


if __name__ == "__main__":
    main()
