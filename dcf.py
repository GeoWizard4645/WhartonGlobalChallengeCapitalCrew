# Quick DCF for the stock bucket with a Monte Carlo on the uncertain inputs.
# Run: python3 dcf.py
# The numbers in STOCKS are made up - fill in real ones from each company's 10-K.
import random

from utils import percentile

STOCKS = {
    # price = current share price, fcf = last 12 months free cash flow ($),
    # net_debt = debt - cash ($), shares = diluted shares, growth = FCF growth/yr for the next 5 yrs
    "EXAMPLE": {"price": 100.0, "fcf": 5e9, "net_debt": 10e9, "shares": 1e9, "growth": 0.08, "growth_sd": 0.03},
}

YEARS = 5                 # explicit forecast years
TERMINAL_GROWTH = 0.025   # long run growth after year 5
DISCOUNT = 0.09           # discount rate (WACC)
DISCOUNT_SD = 0.01
MARGIN_OF_SAFETY = 0.25   # only buy if price is at least 25% under intrinsic value
N_SIMS = 10000
rng = random.Random(42)


def intrinsic_per_share(fcf, growth, terminal, rate, net_debt, shares):
    value = 0.0
    cash = fcf
    for t in range(1, YEARS + 1):
        cash *= 1 + growth
        value += cash / (1 + rate) ** t
    value += cash * (1 + terminal) / (rate - terminal) / (1 + rate) ** YEARS   # terminal value
    return (value - net_debt) / shares


for ticker, s in STOCKS.items():
    base = intrinsic_per_share(s["fcf"], s["growth"], TERMINAL_GROWTH, DISCOUNT, s["net_debt"], s["shares"])
    buy_below = base * (1 - MARGIN_OF_SAFETY)

    sims = []
    for _ in range(N_SIMS):
        g = rng.gauss(s["growth"], s["growth_sd"])
        r = max(rng.gauss(DISCOUNT, DISCOUNT_SD), 0.05)
        tg = min(rng.gauss(TERMINAL_GROWTH, 0.005), r - 0.02)   # keep terminal growth below the discount rate
        sims.append(intrinsic_per_share(s["fcf"], g, tg, r, s["net_debt"], s["shares"]))

    print(ticker)
    print(f"  price                   ${s['price']:.2f}")
    print(f"  base intrinsic value    ${base:.2f}")
    print(f"  buy below (-{MARGIN_OF_SAFETY * 100:g}%)       ${buy_below:.2f}   ->", "BUY" if s["price"] <= buy_below else "PASS")
    print(f"  MC intrinsic 5/50/95th  ${percentile(sims, 0.05):.2f} / ${percentile(sims, 0.50):.2f} / ${percentile(sims, 0.95):.2f}")
    print(f"  P(intrinsic > price)    {sum(v > s['price'] for v in sims) / N_SIMS * 100:.1f}%")
    print(f"  P(intrinsic > price/0.75) {sum(v > s['price'] / (1 - MARGIN_OF_SAFETY) for v in sims) / N_SIMS * 100:.1f}%  (margin of safety holds)")
