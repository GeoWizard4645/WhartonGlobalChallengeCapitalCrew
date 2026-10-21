"""Turn the strategies' picks into one order list for WInS, with the exit plan of every position.

    .venv/bin/python -m quant.trade_plan                                  # every pick, default budgets below
    .venv/bin/python -m quant.trade_plan --qm 25000 --mf 25000 --top 5    # the 5 best-ranked names per strategy
    .venv/bin/python -m quant.exits check                                 # later: hold or sell each position

Reads output/<strategy>/picks.csv (written by `python -m quant.run`), skips the names in DO_NOT_BUY (replacing
them with the strategy's next-ranked alternate, as the rules would), sizes whole shares at the latest close, checks
price >= $5 and order <= 2x daily volume, and writes output/orders.csv. Without --top, names held by more than one
strategy are merged into one order; with --top every strategy gets K different names (a name both rank goes to the
one that ranks it higher; at equal rank they take turns). Each order carries its exit plan (quant/exits.py): the
first month-end review, the planned sale, the rule, and what picks like it returned in the 2019-2026 backtest.
"""
from __future__ import annotations

import argparse
import math

import numpy as np
import pandas as pd

from quant import exits, settings

# Names the live-pick audit removed. Takeover targets (price pinned to the deal) and trailing earnings that
# include a one-off gain or a business already sold would make the screen's inputs wrong.
DO_NOT_BUY = {
    "VAL": "being acquired by Transocean (all-stock); price tracks the deal",
    "PTC": "being acquired by Schneider Electric for $205 cash",
    "HON": "trailing EBIT still includes Aerospace, spun off 2026-06-29",
    "SOLV": "trailing EBIT includes a $1.5B one-off gain on a divestiture",
    "SON": "trailing earnings include a ~$0.38B gain on the ThermoSafe sale",
    "LNTH": "being acquired by Curium for $102.50 cash + CVR; price pinned to the deal",
    "KVUE": "being acquired by Kimberly-Clark (stock + $3.50 cash); price tracks KMB",
    "ROKU": "being acquired by Fox (cash + FOXA stock); price tracks the deal",
    "NXPI": "trailing EBIT includes a $627M one-off gain on the MEMS sale (Q1 2026)",
    "R": "capital leaves out the ~$10B leased-truck fleet, so return on capital is overstated ~9x",
}

# Default budgets: the repo case keeps 25% of the $300,000 WInS account in stocks ($75,000). Split between the
# two strategies that beat their benchmarks in BOTH the 2011-18 and 2019-26 backtests (trading comps did not and is
# shelved). The merged momentum + Magic Formula strategy can be given a budget with --mm.
BUDGETS = {"quality_momentum": 37500, "magic_formula": 37500, "momentum_mf": 0}
MIN_PRICE = 5.0


def ranked(name: str, exclude: dict) -> pd.DataFrame:
    """The strategy's picks then alternates, best rank first, blocked names removed."""
    p = pd.read_csv(settings.OUTPUT / name / "picks.csv")
    return p[~p["ticker"].isin(exclude)].sort_values(["alternate", "rank"]).reset_index(drop=True)


def top_k(lists: dict[str, list[str]], k: int) -> dict[str, list[str]]:
    """The first ``k`` names of every list with no name in two lists: a name goes to the list that ranks it higher;
    when two lists rank it equally they take turns, and the one that gives it up moves on to its next name."""
    chosen = {s: [] for s in lists}
    taken: set[str] = set()
    turn = 0
    for pos in range(max((len(v) for v in lists.values()), default=0)):
        here = {s: lst[pos] for s, lst in lists.items() if pos < len(lst) and len(chosen[s]) < k}
        order = list(here)
        names = list(here.values())
        if any(names.count(t) > 1 and t not in taken for t in names):
            shift = turn % len(order)
            order = order[shift:] + order[:shift]
            turn += 1
        for s in order:
            if here[s] not in taken:
                chosen[s].append(here[s])
                taken.add(here[s])
    return chosen


def strategy_orders(name: str, budget: float, exclude: dict, tickers: list[str] | None = None) -> pd.DataFrame:
    """Orders for one strategy: the given ``tickers`` at budget / len, else every held slot at its weight with
    blocked names replaced by the next alternates (none left => that slot stays cash)."""
    p = ranked(name, exclude)
    if tickers is not None:
        chosen = p.set_index("ticker").loc[tickers].reset_index()
        dollars = budget / max(len(tickers), 1)
    else:
        allp = pd.read_csv(settings.OUTPUT / name / "picks.csv")
        held = allp[~allp["alternate"]]
        n_slots = len(held)
        keep = p[~p["alternate"]]
        chosen = pd.concat([keep, p[p["alternate"]].head(n_slots - len(keep))])
        dollars = budget * (held["weight"].iloc[0] if n_slots else 0.0)
    return pd.DataFrame({"ticker": chosen["ticker"], "name": chosen["name"], "sector": chosen["gics_sector"],
                         "strategy": name, "rank": chosen["rank"].to_numpy(), "dollars": dollars,
                         "replacement": chosen["alternate"].to_numpy()})


def exit_columns(strategies: str, entry: pd.Timestamp, stats, picks: str) -> dict:
    """Exit plan and backtest expectation for one order (several strategies: each one's, joined by ' | ')."""
    parts = []
    for s in strategies.split("+"):
        plan = exits.exit_plan(s, entry)
        e1 = exits.expected(stats, s, "first_month", picks)
        ex = exits.expected(stats, s, "to_exit", picks)
        months = ex.get("months_median", np.nan)
        if s == "magic_formula":
            sale, months = plan["planned_sale"], exits.MF_HOLD_MONTHS
        elif np.isfinite(months):          # momentum: no fixed date; the backtest's median holding
            sale = exits.next_trading_day(exits.review_after(entry, max(1, round(months))))
        else:
            sale = pd.NaT
        parts.append(dict(first_review=plan["first_review"].date(), expected_sale=sale.date() if pd.notna(sale) else None,
                          exit_rule=exits.RULES[s], exp_1m=e1.get("mean"), exp_to_exit=ex.get("mean"),
                          exp_to_exit_p25=ex.get("p25"), exp_to_exit_p75=ex.get("p75"),
                          pct_positive=ex.get("pct_positive"), months_held_median=months))
    if len(parts) == 1:
        return parts[0]
    return {k: " | ".join(str(p[k]) for p in parts) for k in parts[0]}


def build_orders(budgets: dict, exclude: dict, top: int = 0, entry=None) -> pd.DataFrame:
    from quant.data import prices

    active = {n: b for n, b in budgets.items() if b > 0}
    if top:
        lists = top_k({n: ranked(n, exclude)["ticker"].tolist() for n in active}, top)
        o = pd.concat([strategy_orders(n, b, exclude, lists[n]) for n, b in active.items()], ignore_index=True)
        o = o.rename(columns={"strategy": "strategies"})
    else:
        o = pd.concat([strategy_orders(n, b, exclude) for n, b in active.items()], ignore_index=True)
        o = o.groupby("ticker").agg(name=("name", "first"), sector=("sector", "first"),
                                    strategies=("strategy", lambda s: "+".join(sorted(set(s)))),
                                    rank=("rank", "min"), dollars=("dollars", "sum"),
                                    replacement=("replacement", "any")).reset_index()
    close, vol = prices.load_close(), prices.load_volume()
    o["price"] = close.loc[close.index[-1], o["ticker"]].to_numpy().round(2)
    o["shares"] = [math.floor(d / px) for d, px in zip(o["dollars"], o["price"])]
    o["value"] = (o["shares"] * o["price"]).round(2)
    o["price_ok"] = o["price"] >= MIN_PRICE
    o["volume_ok"] = o["shares"] <= 2 * vol[o["ticker"]].iloc[-20:].mean().to_numpy()
    o["price_date"] = close.index[-1].date()
    entry = pd.Timestamp(entry) if entry is not None else exits.next_trading_day(close.index[-1])
    o["entry_date"] = entry.date()
    stats = exits.load_stats()
    picks = f"top{exits.TOP}" if top and top <= exits.TOP else "all"
    ex = pd.DataFrame([exit_columns(s, entry, stats, picks) for s in o["strategies"]], index=o.index)
    o = pd.concat([o, ex], axis=1)
    return o.sort_values(["strategies", "rank"]).reset_index(drop=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Build the WInS order list from the strategies' picks.")
    ap.add_argument("--qm", type=float, default=BUDGETS["quality_momentum"], help="quality momentum budget ($)")
    ap.add_argument("--mf", type=float, default=BUDGETS["magic_formula"], help="Magic Formula budget ($)")
    ap.add_argument("--mm", type=float, default=BUDGETS["momentum_mf"], help="momentum + Magic Formula budget ($)")
    ap.add_argument("--top", type=int, default=0, help="only the K best-ranked names per strategy (0 = all picks)")
    ap.add_argument("--entry", default=None, help="trade date (default: the next trading day after the latest close)")
    a = ap.parse_args(argv)
    o = build_orders({"quality_momentum": a.qm, "magic_formula": a.mf, "momentum_mf": a.mm}, DO_NOT_BUY,
                     top=a.top, entry=a.entry)
    o.to_csv(settings.OUTPUT / "orders.csv", index=False)
    pd.set_option("display.width", 200)
    show = o[["ticker", "name", "strategies", "rank", "shares", "price", "value", "first_review", "expected_sale"]]
    print(show.to_string(index=False))
    print(f"\n{len(o)} orders, ${o['value'].sum():,.0f} at the {o['price_date'].iloc[0]} close, to trade on "
          f"{o['entry_date'].iloc[0]}. Skipped: {', '.join(sorted(DO_NOT_BUY))}. Written to output/orders.csv")
    bad = o[~(o["price_ok"] & o["volume_ok"])]
    if len(bad):
        print("CHECK (price < $5 or order > 2x daily volume):", ", ".join(bad["ticker"]))


if __name__ == "__main__":
    main()
