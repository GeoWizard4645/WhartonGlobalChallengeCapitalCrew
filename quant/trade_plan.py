"""Turn the strategies' picks into one order list for WInS.

    .venv/bin/python -m quant.trade_plan                       # default budgets below
    .venv/bin/python -m quant.trade_plan --qm 37500 --mf 37500 --mm 0

Reads output/<strategy>/picks.csv (written by `python -m quant.run`), skips the names in DO_NOT_BUY (replacing
them with the strategy's next-ranked alternate, as the rules would), merges names held by more than one strategy,
sizes whole shares at the latest close, checks price >= $5 and order <= 2x daily volume, and writes
output/orders.csv.
"""
from __future__ import annotations

import argparse
import math

import pandas as pd

from quant import settings

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
}

# Default budgets: the repo case keeps 25% of the $300,000 WInS account in stocks ($75,000). Split between the
# two strategies that beat their benchmarks in BOTH the 2011-18 and 2019-26 backtests (trading comps did not and is
# shelved). The merged momentum + Magic Formula strategy can be given a budget with --mm.
BUDGETS = {"quality_momentum": 37500, "magic_formula": 37500, "momentum_mf": 0}
MIN_PRICE = 5.0


def strategy_orders(name: str, budget: float, exclude: dict) -> pd.DataFrame:
    p = pd.read_csv(settings.OUTPUT / name / "picks.csv")
    held = p[~p["alternate"]]
    n_slots = len(held)
    keep = held[~held["ticker"].isin(exclude)]
    alts = p[p["alternate"] & ~p["ticker"].isin(exclude)]
    n_missing = n_slots - len(keep)
    chosen = pd.concat([keep, alts.head(n_missing)])          # replacements in rank order; none left => cash
    weight = held["weight"].iloc[0] if n_slots else 0.0
    return pd.DataFrame({"ticker": chosen["ticker"], "name": chosen["name"], "sector": chosen["gics_sector"],
                         "strategy": name, "dollars": budget * weight,
                         "replacement": chosen["alternate"].to_numpy()})


def build_orders(budgets: dict, exclude: dict) -> pd.DataFrame:
    from quant.data import prices

    parts = [strategy_orders(n, b, exclude) for n, b in budgets.items() if b > 0]
    o = pd.concat(parts, ignore_index=True)
    o = o.groupby("ticker").agg(name=("name", "first"), sector=("sector", "first"),
                                strategies=("strategy", lambda s: "+".join(sorted(set(s)))),
                                dollars=("dollars", "sum"), replacement=("replacement", "any")).reset_index()
    close, vol = prices.load_close(), prices.load_volume()
    o["price"] = close.loc[close.index[-1], o["ticker"]].to_numpy()
    o["shares"] = [math.floor(d / px) for d, px in zip(o["dollars"], o["price"])]
    o["value"] = (o["shares"] * o["price"]).round(2)
    o["price_ok"] = o["price"] >= MIN_PRICE
    o["volume_ok"] = o["shares"] <= 2 * vol[o["ticker"]].iloc[-20:].mean().to_numpy()
    o["price_date"] = close.index[-1].date()
    return o.sort_values(["strategies", "value"], ascending=[True, False]).reset_index(drop=True)


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description="Build the WInS order list from the strategies' picks.")
    ap.add_argument("--qm", type=float, default=BUDGETS["quality_momentum"], help="quality momentum budget ($)")
    ap.add_argument("--mf", type=float, default=BUDGETS["magic_formula"], help="Magic Formula budget ($)")
    ap.add_argument("--mm", type=float, default=BUDGETS["momentum_mf"], help="momentum + Magic Formula budget ($)")
    a = ap.parse_args(argv)
    o = build_orders({"quality_momentum": a.qm, "magic_formula": a.mf, "momentum_mf": a.mm}, DO_NOT_BUY)
    o.to_csv(settings.OUTPUT / "orders.csv", index=False)
    pd.set_option("display.width", 160)
    print(o[["ticker", "name", "strategies", "shares", "price", "value"]].to_string(index=False))
    print(f"\n{len(o)} orders, ${o['value'].sum():,.0f} at the {o['price_date'].iloc[0]} close. "
          f"Skipped: {', '.join(sorted(DO_NOT_BUY))}. Written to output/orders.csv")
    bad = o[~(o["price_ok"] & o["volume_ok"])]
    if len(bad):
        print("CHECK (price < $5 or order > 2x daily volume):", ", ".join(bad["ticker"]))


if __name__ == "__main__":
    main()
