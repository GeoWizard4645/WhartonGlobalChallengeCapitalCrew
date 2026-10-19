"""Turn the three strategies' live picks into an order list for WInS.

Reads output/live/<strategy>_chosen.csv (written by `python -m quant.run_backtests --live-only`), applies a
dollar budget per strategy, merges names that appear in more than one strategy, sizes whole shares at the
latest close, and checks the competition constraints (price >= $5, order <= 2x average daily volume).

    .venv/bin/python -m quant.trade_plan --mf 37500 --qm 22500 --tc 15000 [--exclude TICK,TICK] [--commission 25]

Writes output/live/orders.csv, output/live/orders.md and output/TRADE_PLAN.md. Budgets are the team's decision; the
defaults split the repo case's 25% stock sleeve of the $300,000 WInS account ($75,000) 50/30/20 across MF/QM/TC.
"""
from __future__ import annotations

import argparse
import math
import pathlib

import pandas as pd

from quant import settings

LIVE = settings.OUTPUT / "live"
MIN_PRICE = 5.0


def load_picks(exclude: set[str] = frozenset()) -> dict[str, pd.DataFrame]:
    """Strategy -> DataFrame(ticker, name, sector, weight, note) of the chosen-parameter live picks.

    A name in `exclude` (an audit BLOCK: pending takeover, EBIT that includes a divested business, ...) is
    replaced by the next-ranked name that passed ALL of that strategy's own filters, which is what the rule
    would select if the excluded name's data were correct: quality momentum -> next by 12-1 momentum among
    names passing quality/SMA/RSI; Magic Formula -> next by combined rank. Trading comps has no further BUY
    signals (every BUY is already held), so its excluded weight stays in cash, as in the backtest.
    """
    q = pd.read_csv(LIVE / "quality_momentum_chosen.csv").sort_values("rank")
    n_q = int((q["weight"] > 0).sum())
    pool = q[(q["weight"] > 0) | (q["dropped_by"] == "beyond_N")]
    pool = pool[~pool["ticker"].isin(exclude)].head(n_q)
    qm = pd.DataFrame({"ticker": pool["ticker"], "name": pool["name"], "sector": pool["gics_sector"],
                       "weight": 1.0 / n_q,
                       "note": ["replacement (next by momentum)" if w == 0 else "" for w in pool["weight"]]})

    m = pd.read_csv(LIVE / "magic_formula_chosen.csv")
    m = m[m["pick"].isin(["PICK", "ALT"])].sort_values("final_rank")
    n_m = int((m["pick"] == "PICK").sum())
    pool = m[~m["yf_ticker"].isin(exclude)].head(n_m)
    mf = pd.DataFrame({"ticker": pool["yf_ticker"], "name": pool["name"], "sector": pool["gics_sector"],
                       "weight": 1.0 / n_m,
                       "note": ["replacement (next by combined rank)" if k == "ALT" else "" for k in pool["pick"]]})

    t = pd.read_csv(LIVE / "trading_comps_chosen.csv")
    t = t[t["selected"] == True]  # noqa: E712 - CSV bools
    t = t[~t["ticker"].isin(exclude)]
    tc = pd.DataFrame({"ticker": t["ticker"], "name": t["name"], "sector": t["sector"], "weight": t["weight"],
                       "note": ""})
    return {"QM": qm, "MF": mf, "TC": tc}


def build_orders(budgets: dict[str, float], exclude: set[str], commission: float = 0.0) -> pd.DataFrame:
    from quant.data import prices

    picks = load_picks(exclude)
    rows = []
    for strat, df in picks.items():
        b = budgets.get(strat, 0.0)
        if b <= 0:
            continue
        for r in df.itertuples():
            rows.append((r.ticker, r.name, r.sector, strat, b * r.weight, r.note))
    o = pd.DataFrame(rows, columns=["ticker", "name", "sector", "strategy", "dollars", "note"])
    if o.empty:
        return o
    g = o.groupby("ticker").agg(name=("name", "first"), sector=("sector", "first"),
                                strategies=("strategy", lambda s: "+".join(sorted(s))),
                                dollars=("dollars", "sum"),
                                note=("note", lambda s: "; ".join(x for x in s if x))).reset_index()
    close = prices.load_close()
    vol = prices.load_volume()
    last = close.index[-1]
    g["price"] = close.loc[last, g["ticker"]].to_numpy()
    g["adv_shares_20d"] = vol[g["ticker"]].iloc[-20:].mean().to_numpy()
    g["shares"] = [math.floor(d / p) if p > 0 else 0 for d, p in zip(g["dollars"], g["price"])]
    g["order_value"] = g["shares"] * g["price"]
    g["commission"] = commission
    g["ok_price"] = g["price"] >= MIN_PRICE
    g["ok_volume"] = g["shares"] <= 2 * g["adv_shares_20d"]
    g["price_date"] = last.date()
    return g.sort_values(["strategies", "dollars"], ascending=[True, False]).reset_index(drop=True)


# --------------------------------------------------------------------------------------------------
# TRADE_PLAN.md
# --------------------------------------------------------------------------------------------------
SLEEVE_WEIGHTS = {"MF": 0.50, "QM": 0.30, "TC": 0.20}     # evidence-tilted split (see TRADE_PLAN.md section 1)


def _audit() -> pd.DataFrame:
    path = settings.OUTPUT / "audit" / "live_picks_audit.csv"
    if not path.exists():
        return pd.DataFrame(columns=["status", "reason", "next_earnings_date", "earnings_in_window_oct21_nov6"])
    a = pd.read_csv(path)
    return a.drop_duplicates("ticker", keep="last").set_index("ticker")


def _status(a, tk):
    return a.at[tk, "status"] if tk in a.index else "NOT AUDITED"


def _earn(a, tk):
    if tk not in a.index or pd.isna(a.at[tk, "next_earnings_date"]):
        return ""
    w = str(a.at[tk, "earnings_in_window_oct21_nov6"]).lower() in ("true", "1", "yes")
    return str(a.at[tk, "next_earnings_date"])[:10] + (" ⚠" if w else "")


def _pct(x, d=0):
    return f"{x * 100:.{d}f}%"


def pick_tables(picks: dict[str, pd.DataFrame], orders: pd.DataFrame, a: pd.DataFrame) -> str:
    import numpy as np

    q = pd.read_csv(LIVE / "quality_momentum_chosen.csv").set_index("ticker")
    m = pd.read_csv(LIVE / "magic_formula_chosen.csv").set_index("yf_ticker")
    t = pd.read_csv(LIVE / "trading_comps_chosen.csv").set_index("ticker")
    L = []
    nq = len(picks["QM"])
    L += [f"### Quality-filtered momentum (QM): {nq} names, equal weight", "",
          "| # | Ticker | Company | Sector | 12-1 momentum | vs 200-DMA | RSI(14) | Debt/Equity | ROE | Audit | Next earnings |",
          "|---|---|---|---|---:|---:|---:|---:|---:|---|---|"]
    for i, r0 in enumerate(picks["QM"].itertuples(), 1):
        r = q.loc[r0.ticker]
        note = " (replacement)" if r0.note else ""
        L.append(f"| {i} | **{r0.ticker}**{note} | {r['name']} | {r['gics_sector']} | {r['mom_12_1'] * 100:+.0f}% | "
                 f"{r['sma200_gap'] * 100:+.0f}% | {r['rsi14']:.1f} | {r['debt_to_equity']:.2f} | {_pct(r['roe'])} | "
                 f"{_status(a, r0.ticker)} | {_earn(a, r0.ticker)} |")
    L += ["", f"### Magic Formula (MF): {len(picks['MF'])} names, equal weight", "",
          "| # | Ticker | Company | Sector | Earnings yield (EBIT/EV) | Return on capital | Mkt cap ($B) | Audit | Next earnings |",
          "|---|---|---|---|---:|---:|---:|---|---|"]
    for i, r0 in enumerate(picks["MF"].itertuples(), 1):
        r = m.loc[r0.ticker]
        note = " (replacement)" if r0.note else ""
        L.append(f"| {i} | **{r0.ticker}**{note} | {r['name']} | {r['gics_sector']} | {_pct(r['ey'], 1)} | "
                 f"{_pct(r['roc'])} | {r['mcap'] / 1e9:.1f} | {_status(a, r0.ticker)} | {_earn(a, r0.ticker)} |")
    w_tc = picks["TC"]["weight"]
    L += ["", f"### Trading comps (TC): {len(picks['TC'])} BUY signals, {1 / w_tc.iloc[0]:.0f}-way equal weight "
          f"(weights sum to {w_tc.sum():.0%}; any remainder stays in cash)", "",
          "| # | Ticker | Company | GICS sub-industry | P/E vs peer median | EV/EBITDA vs peer median | Peer level | ND/EBITDA | ROIC vs WACC | Audit | Next earnings |",
          "|---|---|---|---|---|---|---|---:|---|---|---|"]
    for i, r0 in enumerate(picks["TC"].itertuples(), 1):
        r = t.loc[r0.ticker]
        roic = "∞" if not np.isfinite(r["roic"]) else _pct(r["roic"])
        L.append(f"| {i} | **{r0.ticker}** | {r['name']} | {r['sub_industry']} | {r['pe']:.1f} vs {r['pe_bench']:.1f} "
                 f"(−{r['pe_disc'] * 100:.0f}%) | {r['ev_ebitda']:.1f} vs {r['ev_bench']:.1f} (−{r['ev_disc'] * 100:.0f}%) | "
                 f"{r['pe_level']} | {r['nd_ebitda']:.2f} | {roic} vs {_pct(r['wacc'], 1)} | {_status(a, r0.ticker)} | "
                 f"{_earn(a, r0.ticker)} |")
    tot = orders["order_value"].sum()
    L += ["", f"### Combined order list ({len(orders)} orders, ~${tot:,.0f}; prices = close of "
          f"{orders['price_date'].iloc[0]})", "",
          "| Ticker | Strategy | Shares | ~Price | ~Value |", "|---|---|---:|---:|---:|"]
    for r in orders.sort_values(["strategies", "order_value"], ascending=[True, False]).itertuples():
        L.append(f"| {r.ticker} | {r.strategies} | {r.shares} | ${r.price:,.2f} | ${r.order_value:,.0f} |")
    cau = [tk for tk in orders["ticker"] if _status(a, tk) == "CAUTION"]
    na = [tk for tk in orders["ticker"] if _status(a, tk) == "NOT AUDITED"]
    L += ["", "### CAUTION names in the order list (the rules keep them; read the note before writing the trading note)", ""]
    L += [f"- **{tk}**: {a.at[tk, 'reason']}" for tk in cau]
    if na:
        L += ["", "### Not yet audited (check for pending takeovers / one-off gains before trading)", "",
              ", ".join(na)]
    return "\n".join(L)


def write_trade_plan(budgets: dict[str, float], exclude: set[str], orders: pd.DataFrame) -> pathlib.Path:
    import json

    s = json.load(open(settings.OUTPUT / "summary.json"))["strategies"]
    a = _audit()
    picks = load_picks(exclude)
    H = {k: s[v]["headline"] for k, v in (("QM", "quality_momentum"), ("MF", "magic_formula"), ("TC", "trading_comps"))}

    def te(k, who="chosen", w="test"):
        return H[k][w][who]

    def desc(k):
        c = H[k]["chosen"]
        if k == "QM":
            return (f"N={c['N']}, quality {c['quality']}, {c['technical'].replace('_', ' + ')}, stop {c['stop_loss']}, "
                    f"vol-target {c['vol_target']}")
        if k == "MF":
            return f"n={c['n']}, market cap ≥ ${c['min_cap'] / 1e9:.0f}B, {c['holding']}"
        return (f"discount > {c['theta']:.0%} on BOTH P/E and EV/EBITDA, caps {c['pe_cap']}/{c['ev_cap']}, "
                f"size filter {'on' if c['size_filter'] else 'off'}")

    def lab(k):
        return "doc default" if H[k]["chosen_is_default"] else "plateau pick"

    spy, ew = te("MF", "SPY"), te("MF", "EW-SP900")
    rows = []
    for k, name in (("MF", "Magic Formula"), ("QM", "Quality-filtered momentum"), ("TC", "Trading comps")):
        c, f = te(k), H[k]["full"]["chosen"]
        rows.append(f"| {name} ({lab(k)}: {desc(k)}) | {len(picks[k])} | **{H[k].get('verdict')}** | "
                    f"{c['sharpe']:.2f} / {_pct(c['cagr'], 1)} | {_pct(f['ff5mom_alpha_ann'], 1)} (t {f['ff5mom_alpha_t']:.2f}) | "
                    f"{H[k].get('pbo', float('nan')):.0%} | **{SLEEVE_WEIGHTS[k]:.0%}** (${budgets[k]:,.0f}) |")
    excl = []
    for tk in sorted(exclude):
        reason = a.at[tk, "reason"] if tk in a.index else ""
        excl.append(f"| {tk} | {reason} |")
    tot = orders["order_value"].sum()
    sect = orders.groupby("sector")["order_value"].sum().sort_values(ascending=False) / tot
    sect_txt = ", ".join(f"{k} {v:.0%}" for k, v in sect.items())
    excl_flag = ",".join(sorted(exclude))
    text = f"""# Wednesday 2026-10-21 trade plan: what each strategy buys

Generated by `python -m quant.trade_plan` from data through the **{orders['price_date'].iloc[0]} close**. Re-run Tuesday evening
(section 5) so picks and share counts use the Oct 20 close. These are the outputs of the team's three rule-based
strategies for the WInS simulated portfolio, not personal financial advice. Full evidence: `output/REPORT.md`.

## 1. Bottom line

| Strategy (parameters used) | Names | Backtest verdict | Test 2019-26 net Sharpe / CAGR | Full-period FF5+MOM alpha | PBO | Suggested share of the stock sleeve |
|---|---:|---|---|---|---:|---|
{chr(10).join(rows)}

Same test window: SPY Sharpe {spy['sharpe']:.2f} / CAGR {_pct(spy['cagr'], 1)}; equal-weight S&P 900 {ew['sharpe']:.2f} / {_pct(ew['cagr'], 1)}.
**None of the three beat SPY risk-adjusted in 2019-2026**, which matches the decay the papers' own authors and McLean &
Pontiff (2016) predict. Use them as a documented, tested process, not as a promised edge.

Why 50 / 30 / 20: the split comes from the training-window evidence (2011-2018) only. Magic Formula had the best training
record (Sharpe {te('MF', 'chosen', 'train')['sharpe']:.2f}, CAGR {_pct(te('MF', 'chosen', 'train')['cagr'], 1)}) and by far the most stable parameter plateau.
Quality momentum is the diversifier (its returns correlate only ~0.05-0.16 with the other two), but it runs hot (28% volatility in the test window)
and is in a crash regime. Trading comps is the weakest: the doc-default cell had significantly negative alpha in training
({_pct(te('TC', 'default', 'train')['ff5mom_alpha_ann'], 1)}/yr, t {te('TC', 'default', 'train')['ff5mom_alpha_t']:.2f}), and its parameter choice flipped between the default and the 10%/no-size-filter cell as data
bugs were fixed. A strict-evidence alternative is MF 60% / QM 40% / TC 0%. Over the 13 trading days before the Nov 6
freeze each strategy's chance of beating SPY is roughly a coin flip (REPORT section 6). The weights matter for the IPS story, not the WInS score.

Example sizing: the repo case keeps 25% of the $300,000 WInS account in stocks = **${sum(budgets.values()):,.0f}**
(MF ${budgets['MF']:,.0f} / QM ${budgets['QM']:,.0f} / TC ${budgets['TC']:,.0f}). Whole sleeve by dollars: {sect_txt}.
The combined sleeve ran **~15% annualized volatility** over the last 6-12 months (each strategy alone 18-24%), inside the ~15-18%
stock-sleeve budget that the case's 10% portfolio cap allows (`research/07_competition_rules.md` §8).

## 2. Names removed by the live-pick audit (do NOT buy)

The rules replace a removed name with the next-ranked name that passed all of that strategy's filters (QM, MF). TC has no
further BUY signals, so its weight stays in cash.

| Ticker | Why |
|---|---|
{chr(10).join(excl)}

Full audit: `output/audit/live_picks_audit.md` (prices match Yahoo to the cent; momentum/RSI recompute exactly; ⚠ marks
earnings inside the Oct 21-Nov 6 window).

## 3. The picks, strategy by strategy

{pick_tables(picks, orders, a)}

## 4. Risks to put in the trading notes

- **Momentum crash regime.** French's winners decile fell 15.4% in July 2026 and our QM backtest's worst drawdown (−40%) was
  Jun-Jul 2026. The pre-registered grid did not select volatility scaling, so the plan follows the doc default.
- **Concentration.** QM is mostly Energy and Materials (oil, refining, steel, fertilizer move together). MF leans IT.
- **Earnings inside the window** (⚠): event risk, not a reason to skip. The backtests always held through earnings.
- **Data caveats.** Some "return on capital" values are huge because working capital is negative or invested capital is tiny
  (capital-floor artefacts; the earnings yield is fine). We exclude operating leases from debt, so a few EV/EBITDA values are lower than Yahoo's.

## 5. Before you place the orders (Tuesday evening, after 4 pm ET)

```
.venv/bin/python -m quant.data.prices update
.venv/bin/python -m quant.run_backtests --strategy all --live-only
.venv/bin/python -m quant.trade_plan --mf {budgets['MF']:.0f} --qm {budgets['QM']:.0f} --tc {budgets['TC']:.0f} --exclude {excl_flag}
```
Any name marked NOT AUDITED after the refresh needs the audit's checks: pending takeover? one-off gain or divested business
inside trailing EBIT or net income? Read the latest 8-K/10-Q headlines.

WInS checklist (`research/07_competition_rules.md` §7):
- [ ] Confirm the $300,000 cash balance and read the rules panel (position limit, commission). At ~$25 per trade, {len(orders)} orders cost ~${25 * len(orders):,}.
- [ ] Every ticker resolves in WInS and trades at ≥ $5. Orders placed before 9:30 am ET fill at Wednesday's open. Whole shares only.
- [ ] At least one ETF in the overall portfolio (bond/fund sleeves are outside this plan).
- [ ] Write a Trading Note for each decision before entering it (Oct 23: pick 3). Good candidates: a clean Magic Formula name
      (high earnings yield and return on capital), a momentum name walked through its RSI and 200-DMA filters, and one rejection
      (an audit BLOCK) that shows the process at work.

*Model outputs for a simulated competition portfolio, not personalized investment advice.*
"""
    out = settings.OUTPUT / "TRADE_PLAN.md"
    out.write_text(text)
    return out


def main(argv=None) -> None:
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    ap.add_argument("--qm", type=float, default=75000 * SLEEVE_WEIGHTS["QM"])
    ap.add_argument("--mf", type=float, default=75000 * SLEEVE_WEIGHTS["MF"])
    ap.add_argument("--tc", type=float, default=75000 * SLEEVE_WEIGHTS["TC"])
    ap.add_argument("--exclude", default="", help="comma-separated tickers to skip (e.g. audit BLOCKs)")
    ap.add_argument("--commission", type=float, default=0.0, help="per-trade commission shown on the WInS preview")
    ap.add_argument("--no-plan", action="store_true", help="only write orders.csv / orders.md, not output/TRADE_PLAN.md")
    a = ap.parse_args(argv)
    ex = {x.strip().upper() for x in a.exclude.split(",") if x.strip()}
    budgets = {"QM": a.qm, "MF": a.mf, "TC": a.tc}
    o = build_orders(budgets, ex, a.commission)
    LIVE.mkdir(parents=True, exist_ok=True)
    o.to_csv(LIVE / "orders.csv", index=False)
    tot, n = o["order_value"].sum(), len(o)
    lines = [f"# Order list (prices: close of {o['price_date'].iloc[0]})", "",
             f"Budgets: QM ${a.qm:,.0f}, MF ${a.mf:,.0f}, TC ${a.tc:,.0f}. Excluded: {', '.join(sorted(ex)) or 'none'}.",
             f"{n} buy orders, ${tot:,.0f} invested" + (f", commissions ${n * a.commission:,.0f}" if a.commission else "") + ".",
             "", "| Ticker | Name | Sector | Strategy | Shares | ~Price | ~Value | Note |",
             "|---|---|---|---|---:|---:|---:|---|"]
    for r in o.itertuples():
        flag = "" if (r.ok_price and r.ok_volume) else " (CHECK)"
        lines.append(f"| {r.ticker}{flag} | {r.name} | {r.sector} | {r.strategies} | {r.shares} | "
                     f"${r.price:,.2f} | ${r.order_value:,.0f} | {r.note} |")
    (LIVE / "orders.md").write_text("\n".join(lines) + "\n")
    print("\n".join(lines))
    if not a.no_plan:
        print("wrote", write_trade_plan(budgets, ex, o))


if __name__ == "__main__":
    main()
