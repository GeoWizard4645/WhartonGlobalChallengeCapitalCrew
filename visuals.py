# Team charts for the plan we adopted (config.ADOPTED_SPLIT + config.ADOPTED_FUNDED), in plain language, one question per chart.
# Run: .venv/bin/python visuals.py        (about 1 minute; same simulation as optimize.py)
# Writes output/team/: 1_plan.png ... 12_cppi_ranges.png (charts 8-12 need cppi_options_grid.csv from optimize.py)
import os

import matplotlib
matplotlib.use("Agg")
matplotlib.rcParams["text.parse_math"] = False      # many labels contain two $ signs
import matplotlib.pyplot as plt  # noqa: E402
import numpy as np  # noqa: E402
from matplotlib.patches import FancyBboxPatch, Rectangle  # noqa: E402

import config  # noqa: E402
import optimize as o  # noqa: E402
from goal import dollars  # noqa: E402

OUT = os.path.join(o.OUT, "team")
INK, INK2, SURFACE, GRID = "#0b0b0b", "#52514e", "#fcfcfb", "#d9d8d3"
BLUE, DARK, MID, LIGHT = "#2a78d6", "#184f95", "#6da7ec", "#cde2fb"
ORANGE, ORANGE_LIGHT = "#eb6834", "#fbe3d6"
SPLIT = np.array(config.ADOPTED_SPLIT)
F_LO, F_HI = config.ADOPTED_FUNDED
K = lambda v: f"${v / 1e3:,.0f}k"
FLEX = 1 - config.FLEX_PCT
NOTE = (f"Simulated on {config.MC_PATHS:,} futures drawn from 7 market scenarios (crash decade to melt-up), 6 years of deposits 2027-2033. "
        f"Reserve = ten ${config.PAYMENT / 1e3:,.0f}k payments as a Treasury ladder ({config.PLANNING_YIELD:.1%}), {o.dollars(o.RESERVE)}.")


def setup(ax, grid="y"):
    ax.set_facecolor(SURFACE)
    for s in ax.spines.values():
        s.set_color(GRID)
    ax.spines["top"].set_visible(False)
    ax.spines["right"].set_visible(False)
    ax.tick_params(colors=INK2, labelsize=10)
    if grid:
        ax.grid(axis=grid, color=GRID, lw=0.7)
        ax.set_axisbelow(True)


def page(title, sub=None, size=(13.5, 7.4), note=None):
    fig = plt.figure(figsize=size, facecolor=SURFACE)
    fig.text(0.035, 0.955, title, fontsize=17, fontweight="bold", color=INK, va="top", ha="left")
    if sub:
        fig.text(0.035, 0.905, sub, fontsize=11.5, color=INK2, va="top", ha="left")
    fig.text(0.035, 0.018, note or NOTE, fontsize=8.3, color=INK2, ha="left", va="bottom")
    return fig


def save(fig, name):
    fig.savefig(os.path.join(OUT, name), dpi=150, facecolor=SURFACE)
    plt.close(fig)


# ---------- numbers ----------

def compute():
    import pandas as pd  # noqa: F401
    rng = np.random.default_rng(config.SEED)
    h, info = o.fill_stocks(o.load_history(), rng)
    X, slices, _ = o.simulate_returns(h, info, rng)
    Xt = np.ascontiguousarray(X.astype(np.float64).transpose(1, 0, 2))
    d = {"h": h, "slices": slices, "X": X}
    v, r, bonds, vpath = o.adaptive_run(Xt, SPLIT[None, :], F_LO, F_HI, track=True)
    d.update(v=v[:, 0], bonds=bonds[:, :, 0], vpath=vpath[:, :, 0], ratios={k: float(r[k][0]) for k in ("sharpe", "sortino", "treynor", "vol")})
    d["x"] = np.maximum(d["v"] - o.RESERVE, 0)

    # every starting split in the team bounds, same nudge rule, on a third of the futures (as in optimize.py)
    w, in_bounds = o.make_grid()
    w0 = w[in_bounds]
    Xs = np.ascontiguousarray(Xt[:, ::len(X) // config.STEADY_SEARCH_PATHS, :])
    rows = []
    for c0 in range(0, len(w0), 40):
        wc = w0[c0:c0 + 40]
        vv, rr, _, _ = o.adaptive_run(Xs, wc, F_LO, F_HI)
        xx = np.maximum(vv - o.RESERVE, 0)
        for j in range(len(wc)):
            rows.append({"bonds": wc[j, 0], "funds": wc[j, 1], "stocks": wc[j, 2], "profit": xx[:, j].mean(), "p_short": float((vv[:, j] < o.RESERVE).mean()),
                         "low": np.percentile(xx[:, j], o.RLO), **{k: float(rr[k][j]) for k in ("sharpe", "sortino", "treynor")}})
    import pandas as pd
    d["grid"] = pd.DataFrame(rows)

    # real history
    sleeves = h[o.NAMES + ["Mkt"]].to_numpy()
    starts = np.arange(len(h) - o.MONTHS + 1)
    Xh = np.ascontiguousarray(sleeves[starts[:, None] + np.arange(o.MONTHS)].transpose(1, 0, 2))
    vh = o.adaptive_run(Xh, SPLIT[None, :], F_LO, F_HI)[0][:, 0]
    d.update(vh=vh, hstart=h.index[starts], hend=h.index[o.MONTHS - 1:])

    # other options, same futures
    none = (-np.inf, np.inf)
    opts = {}
    for name, split in (("Plan-doc split\n37.5 / 37.5 / 25", [0.375, 0.375, 0.25]), ("Earlier pick\n50 / 10 / 40", [0.5, 0.1, 0.4]),
                        ("Very safe\n70 / 10 / 20", [0.7, 0.1, 0.2])):
        opts[name] = o.adaptive_run(Xt, np.array([split]), *none)[0][:, 0]
    opts["Reserve-first CPPI\n(rejected: big swings)"] = o.run_reserve_first(o.grow_returns(X, 0.5), 2.0)[0]
    adopted = "ADOPTED\n" + " / ".join(f"{x * 100:g}" for x in SPLIT)
    d["options"] = {**{k: v_ for k, v_ in opts.items()}, adopted: d["v"]}
    d["adopted_name"] = adopted
    return d


# ---------- 1. the plan ----------

def chart_plan(d):
    x = d["x"]
    st = o.x_stats(d["v"])
    fig = page("The plan: one split now, nudge Bonds by at most 5 points a year",
               "Set it once in 2027. Each January from 2028, only move if the cushion over the reserve has clearly shrunk or grown.")
    gs = fig.add_gridspec(1, 3, left=0.035, right=0.975, top=0.84, bottom=0.1, wspace=0.12, width_ratios=[1.05, 1.15, 1])
    # (a) start split
    a = fig.add_subplot(gs[0])
    a.set_xlim(0, 1)
    a.set_ylim(0, 1)
    a.axis("off")
    a.text(0, 0.97, "1  Start with this split", fontsize=13.5, fontweight="bold", color=INK, va="top")
    parts = [("Bonds", SPLIT[0], DARK, "bond funds and Treasuries: steady, pays the bills"), ("Funds", SPLIT[1], MID, "S&P 500 index funds: the diversified core"),
             ("Stocks", SPLIT[2], BLUE, "our momentum + Magic Formula picks")]
    y = 0.86
    for name, wt, col, desc in parts:
        a.add_patch(Rectangle((0, y - 0.1), wt * 0.9, 0.1, color=col))
        a.text(wt * 0.9 + 0.02, y - 0.05, f"{wt:.1%}".replace(".0%", "%"), fontsize=20, fontweight="bold", color=INK, va="center")
        a.text(0, y - 0.14, f"{name}: {desc}", fontsize=10.5, color=INK2, va="center")
        y -= 0.22
    a.text(0, 0.03, f"Rebalanced to these targets every month.\nReserve to cover: {o.dollars(o.RESERVE)} (ten payments of {K(config.PAYMENT)}).", fontsize=10.5, color=INK2, va="bottom", linespacing=1.5)

    # (b) nudge rule
    b = fig.add_subplot(gs[1])
    b.set_xlim(0.9, 2.0)
    b.set_ylim(0, 1)
    b.axis("off")
    b.text(0.9, 0.97, "2  Each January, check the cushion", fontsize=13.5, fontweight="bold", color=INK, va="top")
    b.text(0.9, 0.89, "Funded ratio = portfolio value / what must be set aside today\nto cover the 2033 reserve", fontsize=10.3, color=INK2, va="top", linespacing=1.5)
    zones = [(0.9, F_LO, ORANGE_LIGHT, f"under {F_LO:g}", "Bonds\n+5 points", "thin cushion:\nadd safety"),
             (F_LO, F_HI, "#eceae4", f"{F_LO:g} to {F_HI:g}", "no change", "on track"),
             (F_HI, 2.0, LIGHT, f"over {F_HI:g}", "Bonds\n-5 points", "big cushion:\nmore growth")]
    for x0, x1, col, rng_, act, why in zones:
        b.add_patch(Rectangle((x0, 0.5), x1 - x0, 0.2, color=col, ec=SURFACE, lw=2))
        b.text((x0 + x1) / 2, 0.6, act, ha="center", va="center", fontsize=12, fontweight="bold", color=INK, linespacing=1.3)
        b.text((x0 + x1) / 2, 0.47, rng_, ha="center", va="top", fontsize=10.5, color=INK, fontweight="bold")
        b.text((x0 + x1) / 2, 0.40, why, ha="center", va="top", fontsize=9, color=INK2, linespacing=1.3)
    floor = lambda t: o.RESERVE / (1 + config.PLANNING_YIELD) ** ((o.MONTHS - t) / 12)
    med = [np.median(d["vpath"][12 * k] / floor(12 * k)) for k in range(1, 6)]
    b.text(0.9, 0.25, "Median funded ratio in the simulations:\n" + "   ".join(f"{o.FIRST_YEAR + k + 1}: {m:.2f}" for k, m in enumerate(med)), fontsize=9.6, color=INK2, va="top", linespacing=1.5)
    b.text(0.9, 0.09, "Only Bonds move; Funds and Stocks keep\ntheir ratio to each other.", fontsize=9.6, color=INK2, va="top", linespacing=1.5)

    # (c) tiles
    c = fig.add_subplot(gs[2])
    c.set_xlim(0, 1)
    c.set_ylim(0, 1)
    c.axis("off")
    c.text(0, 0.97, "3  What it means", fontsize=13.5, fontweight="bold", color=INK, va="top")
    tiles = [(K(st["x_median"]), "median extra contribution in 2033 (x)", BLUE),
             (f"{K(st['x_range_lo'])} to {K(st['x_range_hi'])}", f"{o.RC:.0%} of futures land in this range", BLUE),
             (f"{1 - st['p_shortfall']:.1%}", "of futures fully cover the reserve", DARK),
             (f"{K(np.percentile(x * FLEX, o.RLO))} to {K(np.percentile(x * FLEX, o.RHI))}", f"range to tell co-sponsors, after keeping {config.FLEX_PCT:.0%} back", DARK)]
    y = 0.9
    for big, small, col in tiles:
        c.add_patch(FancyBboxPatch((0.005, y - 0.185), 0.99, 0.185, boxstyle="round,pad=0.003,rounding_size=0.02", fc="white", ec=GRID, lw=1))
        c.add_patch(Rectangle((0.005, y - 0.185), 0.018, 0.185, color=col))
        c.text(0.07, y - 0.065, big, fontsize=19, fontweight="bold", color=INK, va="center")
        c.text(0.07, y - 0.14, small, fontsize=9.6, color=INK2, va="center")
        y -= 0.215
    save(fig, "1_plan.png")


# ---------- 2. projection ----------

def chart_projection(d):
    vp = d["vpath"]
    yrs = o.FIRST_YEAR + np.arange(o.MONTHS + 1) / 12
    floor = o.RESERVE / (1 + config.PLANNING_YIELD) ** ((o.MONTHS - np.arange(o.MONTHS + 1)) / 12)
    pc = np.percentile(vp, [o.RLO, 25, 50, 75, o.RHI], axis=1) / 1e3
    fig = page(f"Where the portfolio goes: it stays above what the reserve needs in {1 - o.x_stats(d['v'])['p_shortfall']:.0%} of futures",
               f"Portfolio value, {SPLIT[0]:.1%} Bonds / {SPLIT[1]:.1%} Funds / {SPLIT[2]:.1%} Stocks, with deposits of {K(300000)} (2027) and {K(150000)} (2028)")
    ax = fig.add_axes([0.07, 0.12, 0.78, 0.7])
    ax.fill_between(yrs, pc[0], pc[4], color=LIGHT, lw=0, label=f"{o.RC:.0%} of futures")
    ax.fill_between(yrs, pc[1], pc[3], color=MID, lw=0, label="middle half of futures")
    ax.plot(yrs, pc[2], color=DARK, lw=2.6, label="median future")
    ax.plot(yrs, floor / 1e3, color=INK, lw=1.8, ls="--", label="what the reserve needs (present value)")
    ax.set_xlim(yrs[0], yrs[-1])
    ax.set_ylabel("$ thousands", fontsize=11, color=INK2)
    ax.legend(loc="upper left", frameon=False, fontsize=10.5, labelcolor=INK2)
    ax.annotate("$300k goes in", (2027, 300), (2027.08, 395), fontsize=10.5, color=INK, arrowprops=dict(arrowstyle="-", color=INK2))
    ax.annotate("+$150k goes in", (2028, 462), (2027.3, 560), fontsize=10.5, color=INK, arrowprops=dict(arrowstyle="-", color=INK2))
    setup(ax)
    for val, lab, col in ((pc[4, -1], f"top of range {K(pc[4, -1] * 1e3)}", INK2), (pc[2, -1], f"median {K(pc[2, -1] * 1e3)}", DARK),
                          (pc[0, -1], f"bottom of range {K(pc[0, -1] * 1e3)}", INK2), (floor[-1] / 1e3, f"reserve needed {K(floor[-1])}", INK)):
        fig.text(0.855, 0.12 + 0.7 * (val - ax.get_ylim()[0]) / (ax.get_ylim()[1] - ax.get_ylim()[0]), lab, fontsize=10.2, color=col, va="center", fontweight="bold" if col in (DARK, INK) else "normal")
    save(fig, "2_projection.png")


# ---------- 3. x ----------

def chart_x(d):
    x, slices = d["x"], d["slices"]
    st = o.x_stats(d["v"])
    fig = page(f"The extra contribution in 2033 (x): median {K(st['x_median'])}, and {o.RC:.0%} of futures land between {K(st['x_range_lo'])} and {K(st['x_range_hi'])}",
               f"x = what is left above the {o.dollars(o.RESERVE)} reserve. After keeping {config.FLEX_PCT:.0%} back for flexibility the quotable range is "
               f"{K(st['x_range_lo'] * FLEX)} to {K(st['x_range_hi'] * FLEX)}.", size=(14.5, 7.4))
    gs = fig.add_gridspec(1, 2, left=0.055, right=0.975, top=0.82, bottom=0.12, wspace=0.28, width_ratios=[1, 1.1])
    a = fig.add_subplot(gs[0])
    pos = x[x > 0] / 1e3
    bins = np.arange(0, 901, 25)
    cnt, _ = np.histogram(pos, bins=bins)
    pct = cnt / len(x) * 100
    a.axvspan(st["x_range_lo"] / 1e3, st["x_range_hi"] / 1e3, color=LIGHT, alpha=0.7, lw=0)
    a.bar(bins[:-1] + 12.5, pct, width=22, color=BLUE)
    a.bar(-20, st["p_shortfall"] * 100, width=22, color=ORANGE)
    a.axvline(st["x_median"] / 1e3, color=INK, lw=1.6, ls="--")
    a.text(st["x_median"] / 1e3 + 8, pct.max() * 1.02, f"median {K(st['x_median'])}", fontsize=10.5, color=INK, va="bottom")
    a.text(-20, st["p_shortfall"] * 100 + 0.25, f"reserve\nshort\n{st['p_shortfall']:.1%}", fontsize=9.5, color=ORANGE, ha="center", va="bottom", fontweight="bold", linespacing=1.2)
    a.text(st["x_range_hi"] / 1e3 - 10, pct.max() * 0.88, f"{o.RC:.0%} of futures", fontsize=10, color=DARK, ha="right")
    a.set_xlabel("x, extra contribution in 2033 ($ thousands)", fontsize=10.5, color=INK2)
    a.set_ylabel("% of futures", fontsize=10.5, color=INK2)
    a.set_title("How the 30,000 futures are spread", fontsize=12.5, fontweight="bold", color=INK, loc="left")
    a.set_xlim(-75, 900)
    a.set_ylim(0, pct.max() * 1.18)
    setup(a)
    b = fig.add_subplot(gs[1])
    names = list(config.SCENARIOS)
    parts = [(f"All futures", x)] + [(f"{n}  ({config.SCENARIOS[n][3]:.0%} likely)", x[s0:s1]) for n, (s0, s1) in zip(names, slices)]
    parts = parts[::-1]
    y = np.arange(len(parts))
    for yi, (n, xv) in zip(y, parts):
        lo, q1, md, q3, hi = np.percentile(xv, [o.RLO, 25, 50, 75, o.RHI]) / 1e3
        strong = n == "All futures"
        b.hlines(yi, lo, hi, color=MID if not strong else DARK, lw=2.2)
        b.hlines(yi, q1, q3, color=BLUE if not strong else DARK, lw=9)
        b.scatter(md, yi, color="white", edgecolors=INK, s=55, zorder=4)
        b.text(hi + 12, yi, f"median {md:,.0f}k", fontsize=9.6, color=INK2, va="center")
        short = (d["v"][slice(*dict(zip(names, slices))[n.split("  (")[0]])] < o.RESERVE).mean() if not strong else st["p_shortfall"]
        b.text(1085, yi, f"{short:.1%}" if strong else f"{short:.0%}", fontsize=10.5, color=ORANGE if short > 1 - config.SAFETY_PROB else INK2, va="center", ha="right",
               fontweight="bold" if short > 1 - config.SAFETY_PROB else "normal")
    b.set_yticks(y, [n for n, _ in parts], fontsize=10, color=INK2)
    b.set_xlabel(f"x ($ thousands): thin line = {o.RC:.0%} range, thick bar = middle half, dot = median", fontsize=10, color=INK2)
    b.set_title("If the market is bad, ok, or great", fontsize=12.5, fontweight="bold", color=INK, loc="left")
    b.set_xlim(-20, 1090)
    b.text(1085, len(parts) - 0.35, "reserve\nshort", fontsize=9.3, color=INK2, va="bottom", ha="right", linespacing=1.2)
    b.set_ylim(-0.6, len(parts) + 0.35)
    setup(b, "x")
    save(fig, "3_extra_contribution.png")


# ---------- 4. heatmaps ----------

def chart_heatmaps(d):
    g = d["grid"]
    step = config.OPT_STEP
    bs = np.round(np.arange(g.bonds.min(), g.bonds.max() + 1e-9, step), 4)
    ss = np.round(np.arange(g.stocks.min(), g.stocks.max() + 1e-9, step), 4)
    ext = [bs[0] * 100 - step * 50, bs[-1] * 100 + step * 50, ss[0] * 100 - step * 50, ss[-1] * 100 + step * 50]
    from matplotlib.colors import LinearSegmentedColormap
    blue = LinearSegmentedColormap.from_list("b", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
    orange = LinearSegmentedColormap.from_list("o", ["#fbe3d6", "#f4a37c", "#eb6834", "#b84a1f", "#7a2e10"])
    panels = [("profit", "Profit: average extra contribution ($k)", "higher is better", blue, 1e-3),
              ("sharpe", "Sharpe: return per unit of total risk", "higher is better", blue, 1),
              ("sortino", "Sortino: return per unit of downside risk", "higher is better", blue, 1),
              ("treynor", "Treynor: return per unit of market risk", "higher is better", blue, 1),
              ("p_short", "Chance the reserve is short (%)", "lower is better; the black line is our 5% limit", orange, 100),
              ("low", f"Low end of the {o.RC:.0%} range of x ($k)", "higher is better", blue, 1e-3)]
    fig = page(f"Where {SPLIT[0] * 100:g} / {SPLIT[1] * 100:g} / {SPLIT[2] * 100:g} sits among every starting split we tested",
               "Each square is one starting Bonds / Funds / Stocks split inside our bounds (Funds is the rest). Light gray = fails the 95% reserve rule. "
               "Black dot = adopted, star = best safe split on that measure.", size=(16.5, 9.4))
    safe_cut = 1 - config.SAFETY_PROB
    gs = fig.add_gridspec(2, 3, left=0.05, right=0.965, top=0.83, bottom=0.1, hspace=0.38, wspace=0.22)
    unsafe = np.zeros((len(ss), len(bs), 4))
    idx = {}
    for r in g.itertuples():
        i, j = int(np.argmin(abs(ss - r.stocks))), int(np.argmin(abs(bs - r.bonds)))
        idx[r.Index] = (i, j)
        if r.p_short > safe_cut:
            unsafe[i, j] = (0.83, 0.82, 0.79, 1.0)
    safe = g[g.p_short <= safe_cut]
    for k, (col, ttl, hint, cmap, scale) in enumerate(panels):
        ax = fig.add_subplot(gs[k // 3, k % 3])
        z = np.full((len(ss), len(bs)), np.nan)
        for r in g.itertuples():
            i, j = idx[r.Index]
            if col == "p_short" or r.p_short <= safe_cut:
                z[i, j] = getattr(r, col) * scale
        sv = np.array([getattr(r, col) * scale for r in safe.itertuples()])
        lo, hi = (np.nanpercentile(sv, [5, 99]) if col != "p_short" else (0, np.nanpercentile(z, 99)))
        im = ax.imshow(z, origin="lower", cmap=cmap, vmin=lo, vmax=hi, aspect="auto", interpolation="nearest", extent=ext)
        if col != "p_short":
            ax.imshow(unsafe, origin="lower", aspect="auto", interpolation="nearest", extent=ext)
        else:
            xc, yc = np.linspace(ext[0] + step * 50, ext[1] - step * 50, len(bs)), np.linspace(ext[2] + step * 50, ext[3] - step * 50, len(ss))
            ax.contour(xc, yc, np.nan_to_num(z, nan=99), levels=[safe_cut * 100], colors=[INK], linewidths=2)
        if col != "p_short":
            best = safe[col].idxmax()
            ax.scatter(g.at[best, "bonds"] * 100, g.at[best, "stocks"] * 100, marker="*", s=260, c="white", edgecolors=INK, linewidths=1.2, zorder=6)
        ax.scatter(SPLIT[0] * 100, SPLIT[2] * 100, marker="o", s=95, c=INK, edgecolors="white", linewidths=1.4, zorder=7)
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.ax.tick_params(colors=INK2, labelsize=9)
        cb.outline.set_edgecolor(GRID)
        ax.set_title(ttl, fontsize=11.5, fontweight="bold", color=INK, loc="left", pad=16)
        ax.text(0, 1.015, hint, transform=ax.transAxes, fontsize=9, color=INK2, va="bottom")
        ax.set_xlabel("Bonds % at the start", fontsize=9.5, color=INK2)
        ax.set_ylabel("Stocks % at the start", fontsize=9.5, color=INK2)
        setup(ax, None)
    save(fig, "4_heatmaps.png")


# ---------- 5. history ----------

def chart_history(d):
    vh, st_, en = d["vh"], d["hstart"], d["hend"]
    xh = np.maximum(vh - o.RESERVE, 0) / 1e3
    fig = page(f"Replaying real history: {'every' if (vh >= o.RESERVE).all() else 'most'} 6-year stretch since 1993 would have covered the reserve",
               f"x for each possible 2027-2033 style stretch, by the month it starts. Lowest {K(xh.min() * 1e3)}, median {K(np.median(xh) * 1e3)}, highest {K(xh.max() * 1e3)}.")
    ax = fig.add_axes([0.07, 0.14, 0.9, 0.66])
    ax.fill_between(st_, 0, xh, color=LIGHT, lw=0)
    ax.plot(st_, xh, color=DARK, lw=2.2)
    ax.axhline(np.median(xh), color=INK, lw=1.2, ls="--")
    ax.text(st_[0], np.median(xh) + 12, f"median {K(np.median(xh) * 1e3)}", fontsize=10, color=INK)
    import pandas as pd
    for lbl, end, off in (("ends in the dot-com bust\n(Oct 2002)", "2002-10", 190), ("ends in the financial crisis\n(Feb 2009)", "2009-02", 300),
                          ("ends at the COVID crash\n(Mar 2020)", "2020-03", 190), ("ends in the 2022 bear market\n(Sep 2022)", "2022-09", -150)):
        hit = np.where(en.strftime("%Y-%m") == end)[0]
        if len(hit):
            j = int(hit[0])
            ax.scatter(st_[j], xh[j], s=60, color=ORANGE, zorder=5, edgecolors="white")
            ax.annotate(f"stretch {lbl}\n{K(xh[j] * 1e3)}", (st_[j], xh[j]), (st_[j], xh[j] + off), fontsize=9.3, color=INK, ha="center", va="center",
                        arrowprops=dict(arrowstyle="-", color=INK2))
    cutoff = pd.Timestamp("2011-07-31")
    ax.axvline(cutoff, color=INK2, lw=1.2, ls=":")
    ax.text(cutoff + pd.Timedelta(days=90), xh.max() * 1.07, "right of this line: real strategy returns for the whole stretch\nleft of it: stock picks are modeled from the market",
            fontsize=8.8, color=INK2, va="top")
    ax.set_xlabel("month the 6-year stretch starts", fontsize=10.5, color=INK2)
    ax.set_ylabel("x, extra contribution ($ thousands)", fontsize=10.5, color=INK2)
    ax.set_ylim(-60, xh.max() * 1.1)
    setup(ax)
    save(fig, "5_history.png")


# ---------- 6. nudges ----------

def chart_nudges(d):
    bp = d["bonds"] * 100
    yrs = o.FIRST_YEAR + np.arange(bp.shape[0])
    fig = page("Year to year the split moves by 5 points at most", f"Bonds weight each January under the nudge rule (at most {config.ADJUST_STEP:.0%} a year). Funds and Stocks keep their ratio to each other.")
    gs = fig.add_gridspec(1, 2, left=0.06, right=0.975, top=0.8, bottom=0.18, wspace=0.18)
    a = fig.add_subplot(gs[0])
    q = np.percentile(bp, [0, 25, 50, 75, 100], axis=1)
    q = np.concatenate([q, q[:, -1:]], axis=1)
    yx = np.append(yrs, yrs[-1] + 1)
    a.fill_between(yx, q[0], q[4], step="post", color="#b7d3f6", lw=0, label="lowest to highest future")
    a.fill_between(yx, q[1], q[3], step="post", color=MID, lw=0, label="middle half of futures")
    a.step(yx, q[2], where="post", color=DARK, lw=2.6, label="median future")
    a.set_xlim(yx[0], yx[-1])
    a.set_ylabel("% of the portfolio in Bonds", fontsize=10.5, color=INK2)
    a.set_title("Bonds weight each January", fontsize=12.5, fontweight="bold", color=INK, loc="left")
    a.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3, frameon=False, fontsize=10, labelcolor=INK2)
    for yr, m in zip(yrs, q[2][:-1]):
        a.text(yr + 0.5, m + 0.4, f"{m:.1f}%", fontsize=9.5, color=DARK, ha="center", fontweight="bold")
    setup(a)
    b = fig.add_subplot(gs[1])
    labels, up, same, down = [], [], [], []
    for k in range(1, bp.shape[0]):
        dlt = bp[k] - bp[k - 1]
        up.append((dlt > 1e-6).mean() * 100)
        down.append((dlt < -1e-6).mean() * 100)
        same.append(100 - up[-1] - down[-1])
        labels.append(str(yrs[k]))
    xs = np.arange(len(labels))
    b.bar(xs, down, color=MID, label="Bonds down", width=0.62)
    b.bar(xs, same, bottom=down, color="#e4e2dc", label="no change", width=0.62)
    b.bar(xs, up, bottom=np.array(down) + np.array(same), color=ORANGE, label="Bonds up", width=0.62)
    for i in xs:
        if down[i] > 4:
            b.text(i, down[i] / 2, f"{down[i]:.0f}%", ha="center", va="center", fontsize=9.5, color=INK)
        b.text(i, down[i] + same[i] / 2, f"{same[i]:.0f}%", ha="center", va="center", fontsize=9.5, color=INK2)
        if up[i] > 4:
            b.text(i, down[i] + same[i] + up[i] / 2, f"{up[i]:.0f}%", ha="center", va="center", fontsize=9.5, color=INK)
    b.set_xticks(xs, labels, fontsize=10, color=INK2)
    b.set_ylabel("% of futures", fontsize=10.5, color=INK2)
    b.set_ylim(0, 100)
    b.set_title("What happened in each January", fontsize=12.5, fontweight="bold", color=INK, loc="left")
    b.legend(loc="upper center", bbox_to_anchor=(0.5, -0.08), ncol=3, frameon=False, fontsize=10, labelcolor=INK2)
    setup(b)
    save(fig, "6_nudges.png")


# ---------- 7. options ----------

def chart_options(d):
    opts = d["options"]
    fig = page("Why this split: the others leave the reserve short too often, or give up too much",
               f"Dot = median extra contribution x. Thin line = {o.RC:.0%} range. Right column = chance the reserve is short (our limit is {1 - config.SAFETY_PROB:.0%}).")
    ax = fig.add_axes([0.2, 0.12, 0.6, 0.68])
    names = list(opts)[::-1]
    y = np.arange(len(names))
    for yi, n in zip(y, names):
        st = o.x_stats(opts[n])
        hi = n == d["adopted_name"]
        ax.hlines(yi, st["x_range_lo"] / 1e3, st["x_range_hi"] / 1e3, color=DARK if hi else MID, lw=3 if hi else 2)
        ax.hlines(yi, st["x_p25"] / 1e3, st["x_p75"] / 1e3, color=DARK if hi else BLUE, lw=11)
        ax.scatter(st["x_median"] / 1e3, yi, s=95, color="white", edgecolors=INK, zorder=4)
        ax.text(st["x_median"] / 1e3, yi + 0.3, f"median {K(st['x_median'])}", fontsize=9.6, color=INK, ha="center")
        bad = st["p_shortfall"] > 1 - config.SAFETY_PROB
        fig.text(0.84, 0.12 + 0.68 * (yi + 0.5) / len(names), f"{st['p_shortfall']:.1%}", fontsize=15, fontweight="bold", color=ORANGE if bad else INK, va="center")
        fig.text(0.925, 0.12 + 0.68 * (yi + 0.5) / len(names), "too risky" if bad else "ok", fontsize=10, color=ORANGE if bad else INK2, va="center")
    ax.set_yticks(y, names, fontsize=10.5, color=INK)
    for t in ax.get_yticklabels():
        if t.get_text().startswith("ADOPTED"):
            t.set_fontweight("bold")
    ax.set_xlim(left=-15)
    ax.set_ylim(-0.6, len(names) - 0.4)
    ax.set_xlabel("x, extra contribution in 2033 ($ thousands; thick bar = middle half)", fontsize=10.5, color=INK2)
    fig.text(0.84, 0.82, "Reserve short", fontsize=10.5, fontweight="bold", color=INK2)
    setup(ax, "x")
    save(fig, "7_options.png")


# ---------- 8-11: zero-risk CPPI options (5% buffer, committed 2028 deposit counted) ----------

BUF = config.CPPI_BUFFER
RES_BUF = o.RESERVE * (1 + BUF)
NOTE_CPPI = (f"Reserve target = {o.dollars(o.RESERVE)} x {1 + BUF:.2f} = {o.dollars(RES_BUF)}; x is what is left above that. Zero risk = reserve short in at most {config.CPPI_ZERO_RISK:.2%} of {config.MC_PATHS:,} simulated futures. "
             f"The $150k deposit in 2028 is counted as a safe asset (it is in the case timeline).")


def cppi_data(d):
    import pandas as pd
    c = pd.read_csv(os.path.join(o.OUT_DIR, "cppi_options_grid.csv"))
    menu = o.pick_menu(c)
    paths = {}
    for letter, i in menu.items():
        r = c.loc[i]
        v, _, share = o.run_reserve_first(o.grow_returns(d["X"], r.stock_share_of_growth), float(r.multiplier), reserve=RES_BUF, count_future=True)
        paths[letter] = {"v": v, "bonds": 1 - share[:, ::12]}
    def stats(v, res):
        x = np.maximum(v - res, 0)
        return {"x_median": np.median(x), "x_range_lo": np.percentile(x, o.RLO), "x_range_hi": np.percentile(x, o.RHI), "x_p25": np.percentile(x, 25),
                "x_p75": np.percentile(x, 75), "p_short": float((v < res).mean())}
    d["steady_ref"] = stats(d["v"], RES_BUF)               # adopted steady split against the buffered reserve (approx.)
    d["steady_orig"] = stats(d["v"], o.RESERVE)            # adopted steady split, original basis (no buffer)
    # reserve-first CPPI from the earlier work: m=2, 50/50 growth, deposit not counted (starts 100% bonds)
    g50 = o.grow_returns(d["X"], 0.5)
    v0, _, sh0 = o.run_reserve_first(g50, 2.0)
    d["cppi_orig"] = {**stats(v0, o.RESERVE), "bonds": 1 - sh0[:, ::12]}
    d["cppi_orig_v"] = v0
    vb, _, _ = o.run_reserve_first(g50, 2.0, reserve=RES_BUF)
    d["cppi_orig_buf"] = stats(vb, RES_BUF)
    d["cppi_orig_buf_v"] = vb
    return c, menu, paths


def chart_cppi_frontier(d, c, menu):
    from matplotlib.colors import LinearSegmentedColormap, Normalize
    cmap = LinearSegmentedColormap.from_list("b", ["#9ec5f4", "#3987e5", "#184f95", "#0d366b"])
    sub = c[(c.buffer == BUF) & c.count_deposit]
    std = c[(c.buffer == BUF) & ~c.count_deposit & c.zero_risk]
    fig = page("CPPI no longer has to start at 100% bonds, and it still never misses the reserve",
               f"Each dot = one CPPI setting with the {BUF:.0%} buffer. Further right = starts with less in bonds; higher = bigger median extra contribution.", note=NOTE_CPPI)
    ax = fig.add_axes([0.075, 0.13, 0.72, 0.7])
    nz = sub[~sub.zero_risk]
    ax.scatter(nz.start_bonds * 100, nz.x_median / 1e3, s=22, facecolors="none", edgecolors="#b9b7b0", lw=0.9, label="reserve can be short (not allowed)", zorder=2)
    ok = sub[sub.zero_risk]
    sc = ax.scatter(ok.start_bonds * 100, ok.x_median / 1e3, s=34, c=ok.multiplier, cmap=cmap, norm=Normalize(1, 6), zorder=3, label="zero risk")
    ax.scatter(std.start_bonds * 100, std.x_median / 1e3, s=60, marker="s", c=ORANGE, zorder=4, label="standard CPPI (2028 deposit not counted): all start at 100% bonds")
    ref = d["steady_ref"]
    ax.axhline(ref["x_median"] / 1e3, color=INK2, lw=1.2, ls="--")
    ax.text(60, ref["x_median"] / 1e3 - 2.5, f"dashed line: adopted steady split against the buffered reserve\n(approx.): median {K(ref['x_median'])}, reserve short {ref['p_short']:.1%}", fontsize=9, color=INK2, va="top", linespacing=1.4)
    so, co = d["steady_orig"], d["cppi_orig"]
    ax.scatter(SPLIT[0] * 100, so["x_median"] / 1e3, s=190, marker="D", c=INK, zorder=6)
    ax.annotate(f"REF  adopted steady split 55/12.5/32.5, original basis (no buffer):\nmedian {K(so['x_median'])}, reserve short {so['p_short']:.1%}", (SPLIT[0] * 100, so["x_median"] / 1e3),
                (50, so["x_median"] / 1e3 + 9), fontsize=9.2, color=INK, va="center", arrowprops=dict(arrowstyle="-", color=INK2))
    ax.scatter(100, co["x_median"] / 1e3, s=190, marker="s", c="white", edgecolors=INK, linewidths=1.8, zorder=6)
    ax.annotate(f"REF  reserve CPPI m=2 (earlier work), original basis:\nmedian {K(co['x_median'])}, starts at 100% bonds", (100, co["x_median"] / 1e3),
                (93, co["x_median"] / 1e3 + 14), fontsize=9.2, color=INK, va="center", arrowprops=dict(arrowstyle="-", color=INK2))
    for letter, i in menu.items():
        r = c.loc[i]
        ax.scatter(r.start_bonds * 100, r.x_median / 1e3, s=330, marker="o", c="white", edgecolors=INK, linewidths=1.6, zorder=6)
        ax.text(r.start_bonds * 100, r.x_median / 1e3, letter, ha="center", va="center", fontsize=11, fontweight="bold", color=INK, zorder=7)
    ax.set_xlim(104, -4)
    ax.set_xlabel("Bonds % in 2027 (the starting split)", fontsize=11, color=INK2)
    ax.set_ylabel("median extra contribution x ($ thousands)", fontsize=11, color=INK2)
    ax.legend(loc="lower right", frameon=False, fontsize=9.5, labelcolor=INK2)
    setup(ax, "both")
    cb = fig.colorbar(sc, ax=ax, fraction=0.035, pad=0.02)
    cb.set_label("CPPI multiplier", fontsize=10, color=INK2)
    cb.ax.tick_params(colors=INK2, labelsize=9)
    cb.outline.set_edgecolor(GRID)
    t = fig.add_axes([0.83, 0.13, 0.16, 0.7])
    t.axis("off")
    t.text(0, 1, "The options", fontsize=12.5, fontweight="bold", color=INK, va="top")
    y = 0.93
    for letter, i in menu.items():
        r = c.loc[i]
        t.text(0, y, f"{letter}  m={r.multiplier:g}", fontsize=10.5, fontweight="bold", color=INK, va="top")
        t.text(0, y - 0.045, f"start {r.start_bonds:.0%} bonds\nmedian x {K(r.x_median)}", fontsize=9.3, color=INK2, va="top", linespacing=1.4)
        y -= 0.17
    save(fig, "8_cppi_options.png")


def chart_cppi_heatmaps(d, c, menu):
    from matplotlib.colors import LinearSegmentedColormap
    blue = LinearSegmentedColormap.from_list("b", ["#cde2fb", "#86b6ef", "#3987e5", "#1c5cab", "#0d366b"])
    orange = LinearSegmentedColormap.from_list("o", ["#fbe3d6", "#f4a37c", "#eb6834", "#b84a1f", "#7a2e10"])
    sub = c[(c.buffer == BUF) & c.count_deposit]
    cols = sorted(sub.multiplier.unique())
    rows = sorted(sub.stock_share_of_growth.unique())
    panels = [("start_bonds", "Bonds % in 2027 (the start)", blue, 100, "{:.0f}"), ("x_median", "Median extra contribution x ($k)", blue, 1e-3, "{:.0f}"),
              ("x_range_lo", f"Low end of the {o.RC:.0%} range of x ($k)", blue, 1e-3, "{:.0f}"), ("p_shortfall", "Chance the reserve is short (%)", orange, 100, "{:.2f}"),
              ("sharpe", "Sharpe ratio", blue, 1, "{:.2f}"), ("sortino", "Sortino ratio", blue, 1, "{:.2f}"), ("treynor", "Treynor ratio", blue, 1, "{:.3f}"),
              ("chg_after", "Typical yearly move in the split after 2028 (points)", blue, 100, "{:.0f}")]
    fig = page(f"Every CPPI setting we tried with the {BUF:.0%} buffer and the 2028 deposit counted",
               "Columns = CPPI multiplier (how hard we lean into stocks and funds). Rows = how much of the growth part is stocks (rest funds). Gray = reserve can be short. Circled letters = the options.",
               size=(21, 10.4), note=NOTE_CPPI)
    gs = fig.add_gridspec(2, 4, left=0.04, right=0.985, top=0.83, bottom=0.1, hspace=0.38, wspace=0.38)
    for k, (col, ttl, cmap, scale, fmt) in enumerate(panels):
        ax = fig.add_subplot(gs[k // 4, k % 4])
        z = np.full((len(rows), len(cols)), np.nan)
        bad = np.zeros((len(rows), len(cols), 4))
        for r in sub.itertuples():
            i, j = rows.index(r.stock_share_of_growth), cols.index(r.multiplier)
            z[i, j] = getattr(r, col) * scale
            if not r.zero_risk and col != "p_shortfall":
                bad[i, j] = (0.83, 0.82, 0.79, 1.0)
        good = z[bad[:, :, 3] == 0]
        lo, hi = (np.nanpercentile(good, [3, 99]) if col != "p_shortfall" else (0, np.nanmax(z))) if len(good) else (0, 1)
        im = ax.imshow(z, origin="lower", cmap=cmap, vmin=lo, vmax=hi, aspect="auto", interpolation="nearest")
        ax.imshow(bad, origin="lower", aspect="auto", interpolation="nearest")
        for i in range(len(rows)):
            for j in range(len(cols)):
                if np.isfinite(z[i, j]) and bad[i, j, 3] == 0:
                    dark = (z[i, j] - lo) / (hi - lo + 1e-12) > 0.55
                    ax.text(j, i, fmt.format(z[i, j]), ha="center", va="center", fontsize=6.6, color="white" if dark else INK)
        for letter, idx in menu.items():
            r = c.loc[idx]
            j, i = cols.index(r.multiplier), rows.index(r.stock_share_of_growth)
            ax.scatter(j, i, s=210, c="white", edgecolors=INK, linewidths=1.5, zorder=5)
            ax.text(j, i, letter, ha="center", va="center", fontsize=9, fontweight="bold", color=INK, zorder=6)
        ax.set_xticks(range(len(cols)), [f"{m:g}" for m in cols], fontsize=8, color=INK2)
        ax.set_yticks(range(len(rows)), [f"{x:.0%}" for x in rows], fontsize=8, color=INK2)
        ax.set_xlabel("CPPI multiplier", fontsize=9, color=INK2)
        ax.set_ylabel("stocks share of growth part", fontsize=9, color=INK2)
        ax.set_title(ttl, fontsize=11, fontweight="bold", color=INK, loc="left")
        cb = fig.colorbar(im, ax=ax, fraction=0.046, pad=0.03)
        cb.ax.tick_params(colors=INK2, labelsize=8)
        cb.outline.set_edgecolor(GRID)
        setup(ax, None)
    save(fig, "9_cppi_heatmaps.png")


def chart_cppi_menu(d, c, menu, paths):
    rows = []                                              # (label, start split, x quantiles, P(short), group)
    for letter, i in menu.items():
        r = c.loc[i]
        rows.append((f"{letter}   CPPI m={r.multiplier:g}, 5% buffer", (r.start_bonds, r.start_funds, r.start_stocks),
                     (r.x_range_lo, r.x_p25, r.x_median, r.x_p75, r.x_range_hi), r.p_shortfall, "new"))
    def q(st):
        return (st["x_range_lo"], st["x_p25"], st["x_median"], st["x_p75"], st["x_range_hi"])
    rows.append(("REF 1   Adopted steady split 55/12.5/32.5\n        original basis: no buffer", tuple(SPLIT), q(d["steady_orig"]), d["steady_orig"]["p_short"], "ref"))
    rows.append(("REF 1b   same split, 5% buffer (approx.)", tuple(SPLIT), q(d["steady_ref"]), d["steady_ref"]["p_short"], "ref"))
    rows.append(("REF 2   Reserve CPPI m=2, 50/50 growth\n        original basis: no buffer", (1.0, 0.0, 0.0), q(d["cppi_orig"]), d["cppi_orig"]["p_short"], "ref"))
    rows.append(("REF 2b   same CPPI, 5% buffer", (1.0, 0.0, 0.0), q(d["cppi_orig_buf"]), d["cppi_orig_buf"]["p_short"], "ref"))
    n_new = sum(1 for r in rows if r[4] == "new")
    ypos, y = [], len(rows) + 1.0
    for k, r in enumerate(rows):
        y -= 1
        if k == n_new:
            y -= 0.7                                       # gap before the references
        ypos.append(y)
    fig = page("The options side by side, with the earlier plans kept as references",
               f"Start split = Bonds / Funds / Stocks in 2027. Payoff = extra contribution x ({o.RC:.0%} range, middle half, median).\nNew options and the REF b-rows are measured above the {BUF:.0%}-buffered reserve; REF 1 and REF 2 are exactly as first reported.",
               note=NOTE_CPPI + "\nREF 1b is approximate (its January rule was tuned for the unbuffered reserve). REF 2 starts 100% bonds and moves to about 57% in 2028 and 44% by 2032.", size=(16, 8.6))
    gs = fig.add_gridspec(1, 3, left=0.25, right=0.975, top=0.8, bottom=0.12, wspace=0.08, width_ratios=[1, 1.25, 0.28])
    a = fig.add_subplot(gs[0])
    for yi, r in zip(ypos, rows):
        left = 0
        for val, col in zip(r[1], (DARK, MID, BLUE)):
            a.barh(yi, val * 100, left=left, color=col, height=0.62, alpha=1 if r[4] == "new" else 0.78)
            if val >= 0.07:
                a.text(left + val * 50, yi, f"{val * 100:.0f}", ha="center", va="center", fontsize=9.5, color="white", fontweight="bold")
            left += val * 100
    a.set_yticks(ypos, [r[0] for r in rows], fontsize=9.8, color=INK)
    a.axhline((ypos[n_new - 1] + ypos[n_new]) / 2, color=GRID, lw=1.5)
    a.text(100, (ypos[n_new - 1] + ypos[n_new]) / 2 + 0.08, "REFERENCES (kept from the earlier work)", ha="right", va="bottom", fontsize=9, color=INK2, fontweight="bold")
    a.set_ylim(min(ypos) - 0.6, max(ypos) + 0.6)
    a.set_xlim(0, 100)
    a.set_xlabel("start split, % (dark = Bonds, light = Funds, blue = Stocks)", fontsize=9.5, color=INK2)
    a.set_title("Start in 2027", fontsize=12, fontweight="bold", color=INK, loc="left")
    setup(a, None)
    b = fig.add_subplot(gs[1], sharey=a)
    for yi, r in zip(ypos, rows):
        lo, q1, md, q3, hi = r[2]
        col = (MID, BLUE) if r[4] == "new" else ("#b9b7b0", "#8a8983")
        b.hlines(yi, lo / 1e3, hi / 1e3, color=col[0], lw=2.4)
        b.hlines(yi, q1 / 1e3, q3 / 1e3, color=col[1], lw=11)
        b.scatter(md / 1e3, yi, s=85, color="white", edgecolors=INK, zorder=4)
        b.text(hi / 1e3 + 10, yi, f"median {K(md)}", fontsize=9.6, color=INK2, va="center")
    plt.setp(b.get_yticklabels(), visible=False)
    b.set_xlabel("x, extra contribution in 2033 ($ thousands)", fontsize=9.5, color=INK2)
    b.set_title("Payoff", fontsize=12, fontweight="bold", color=INK, loc="left")
    b.set_xlim(-10, 880)
    setup(b, "x")
    r_ = fig.add_subplot(gs[2], sharey=a)
    r_.axis("off")
    r_.set_title("Reserve short", fontsize=12, fontweight="bold", color=INK, loc="left")
    for yi, r in zip(ypos, rows):
        bad = r[3] > config.CPPI_ZERO_RISK
        r_.text(0, yi, f"{r[3]:.1%}" if bad else "0%", fontsize=15, fontweight="bold", color=ORANGE if bad else INK, va="center")
    save(fig, "10_cppi_menu.png")


def chart_cppi_glide(d, c, menu, paths):
    yrs = o.FIRST_YEAR + np.arange(o.MONTHS // 12)
    panels = [("REF 2  Reserve CPPI m=2\n(earlier work)", d["cppi_orig"]["bonds"], True),
              ("REF 1  Adopted steady split\n55 / 12.5 / 32.5", d["bonds"].T, True)]
    for letter, i in menu.items():
        panels.append((f"{letter}   CPPI m={c.loc[i].multiplier:g}\n5% buffer", paths[letter]["bonds"], False))
    n = len(panels)
    fig = page("How the split moves over time: the earlier plans (gray) next to the new options",
               "Bonds weight at the start of each year. Line = median future, band = middle half (light = 5th to 95th percentile). The 2028 jump is the $150k deposit arriving as safe money.",
               size=(22, 6.8), note=NOTE_CPPI)
    gs = fig.add_gridspec(1, n, left=0.04, right=0.99, top=0.73, bottom=0.16, wspace=0.12)
    for k, (title, bonds, ref) in enumerate(panels):
        ax = fig.add_subplot(gs[k], sharey=None if k == 0 else fig.axes[0])
        bp = bonds * 100
        q = np.percentile(bp, [5, 25, 50, 75, 95], axis=0)
        yx = np.append(yrs, yrs[-1] + 1)
        qx = np.concatenate([q, q[:, -1:]], axis=1)
        cl, cm, cd = ("#e4e2dc", "#bdbbb4", "#52514e") if ref else (LIGHT, MID, DARK)
        ax.fill_between(yx, qx[0], qx[4], step="post", color=cl, lw=0)
        ax.fill_between(yx, qx[1], qx[3], step="post", color=cm, lw=0)
        ax.step(yx, qx[2], where="post", color=cd, lw=2.4)
        ax.text(yrs[0] + 0.05, q[2][0] + (3 if q[2][0] < 90 else -9), f"{q[2][0]:.0f}%", fontsize=10, color=cd, fontweight="bold")
        ax.text(yrs[-1] + 0.05, q[2][-1] + 3, f"{q[2][-1]:.0f}%", fontsize=10, color=cd, fontweight="bold")
        ax.set_title(title, fontsize=10, fontweight="bold", color=INK, loc="left")
        ax.set_ylim(0, 100)
        ax.set_xlim(yx[0], yx[-1])
        ax.set_xticks(yrs[::2], [str(y) for y in yrs[::2]], fontsize=9, color=INK2)
        if k == 0:
            ax.set_ylabel("Bonds % of the portfolio", fontsize=10, color=INK2)
        else:
            plt.setp(ax.get_yticklabels(), visible=False)
        setup(ax)
    save(fig, "11_cppi_glide.png")


def chart_cppi_ranges(d, c, menu, paths):
    """Numbers, not pictures: the range of x at every 10% confidence level and the odds of reaching fixed amounts, for every option and reference."""
    cols = [("REF 1", "Steady 55/12.5/32.5", "no buffer", d["v"], o.RESERVE, True), ("REF 1b", "same split*", "5% buffer", d["v"], RES_BUF, True),
            ("REF 2", "CPPI m=2 (earlier)", "no buffer", d["cppi_orig_v"], o.RESERVE, True), ("REF 2b", "same CPPI", "5% buffer", d["cppi_orig_buf_v"], RES_BUF, True)]
    for letter, i in menu.items():
        r = c.loc[i]
        cols.append((letter, f"CPPI m={r.multiplier:g}", f"start {r.start_bonds:.0%} bonds", paths[letter]["v"], RES_BUF, False))
    xs = [np.maximum(col[3] - col[4], 0) for col in cols]
    levels = [0.1, 0.2, 0.3, 0.4, 0.5, 0.6, 0.7, 0.8, 0.9, 0.95]
    amounts = [50e3, 100e3, 150e3, 200e3, 300e3, 400e3]
    n, nr1, nr2 = len(cols), len(levels) + 1, len(amounts) + 1
    fig = page("What x could be, by multiplier: the range at every confidence level, and the odds of reaching an amount",
               "Top table: the range that holds x that share of the time (80% = from the 10th to the 90th percentile). Bottom table: chance x is at least that amount. All in $ thousands.",
               size=(19.5, 11.6), note=NOTE_CPPI + "\n*REF 1b is approximate (its January rule was tuned for the unbuffered reserve). REF rows keep the earlier plans; 'no buffer' rows are exactly as first reported.")
    ax = fig.add_axes([0, 0.05, 1, 0.82])
    ax.set_xlim(0, 1)
    ax.set_ylim(0, 1)
    ax.axis("off")
    x0, cw = 0.15, (0.975 - 0.15) / n
    total = 3 + nr1 + nr2 + 2.2                              # header + two titles + rows + gaps
    rh = 1 / total
    y = 1.0
    # column headers
    for j, col in enumerate(cols):
        gx = x0 + j * cw
        ax.add_patch(Rectangle((gx + 0.002, y - 2.4 * rh), cw - 0.004, 2.4 * rh, color="#e4e2dc" if col[5] else LIGHT, lw=0))
        ax.text(gx + cw / 2, y - 0.5 * rh, col[0], ha="center", va="center", fontsize=13, fontweight="bold", color=INK)
        ax.text(gx + cw / 2, y - 1.15 * rh, col[1], ha="center", va="center", fontsize=9.3, color=INK)
        ax.text(gx + cw / 2, y - 1.75 * rh, col[2], ha="center", va="center", fontsize=8.8, color=INK2)
    y -= 2.6 * rh

    def block(title, labels, cells, shade, note_fmt=None):
        nonlocal y
        ax.text(0.005, y - 0.45 * rh, title, fontsize=12, fontweight="bold", color=INK, va="center")
        y -= 0.9 * rh
        from matplotlib.colors import LinearSegmentedColormap
        cm = LinearSegmentedColormap.from_list("b", ["#f3f8fe", "#9ec5f4", "#3987e5", "#184f95"])
        allv = np.array(shade, dtype=float)
        lo_, hi_ = np.nanmin(allv), np.nanmax(allv)
        for i, (lab, row, sh) in enumerate(zip(labels, cells, shade)):
            ax.text(x0 - 0.008, y - 0.5 * rh, lab, ha="right", va="center", fontsize=10.5, color=INK, fontweight="bold" if lab.startswith("Median") else "normal")
            for j, (txt, v) in enumerate(zip(row, sh)):
                t = (v - lo_) / (hi_ - lo_ + 1e-12)
                ax.add_patch(Rectangle((x0 + j * cw + 0.002, y - rh + 0.0015), cw - 0.004, rh - 0.003, color=cm(t * 0.92), lw=0))
                ax.text(x0 + j * cw + cw / 2, y - 0.5 * rh, txt, ha="center", va="center", fontsize=10, color="white" if t > 0.6 else INK)
            y -= rh
        y -= 0.35 * rh

    labels, cells, shade = ["Median (50%)"], [[f"{np.median(x) / 1e3:,.0f}" for x in xs]], [[np.median(x) for x in xs]]
    for cl in levels:
        lo_p, hi_p = (1 - cl) / 2 * 100, (1 + cl) / 2 * 100
        labels.append(f"{cl:.0%} range  ({lo_p:g}th to {hi_p:g}th pct)")
        cells.append([f"{np.percentile(x, lo_p) / 1e3:,.0f} to {np.percentile(x, hi_p) / 1e3:,.0f}" for x in xs])
        shade.append([np.percentile(x, lo_p) for x in xs])
    block("Range of x at each confidence level ($ thousands; shade = how high the low end is)", labels, cells, shade)
    labels2, cells2, shade2 = ["Reserve fully covered"], [[f"{1 - float((col[3] < col[4]).mean()):.1%}" for col in cols]], [[1 - float((col[3] < col[4]).mean()) for col in cols]]
    for a in amounts:
        labels2.append(f"x at least ${a / 1e3:,.0f}k")
        cells2.append([f"{float((x >= a).mean()):.0%}" for x in xs])
        shade2.append([float((x >= a).mean()) for x in xs])
    block("Chance of reaching at least this extra contribution (shade = higher chance)", labels2, cells2, shade2)
    save(fig, "12_cppi_ranges.png")


def main():
    os.makedirs(OUT, exist_ok=True)
    d = compute()
    for fn in (chart_plan, chart_projection, chart_x, chart_heatmaps, chart_history, chart_nudges, chart_options):
        fn(d)
    if os.path.exists(os.path.join(o.OUT_DIR, "cppi_options_grid.csv")):
        c, menu, paths = cppi_data(d)
        chart_cppi_frontier(d, c, menu)
        chart_cppi_heatmaps(d, c, menu)
        chart_cppi_menu(d, c, menu, paths)
        chart_cppi_glide(d, c, menu, paths)
        chart_cppi_ranges(d, c, menu, paths)
    else:
        print("Charts 8-12 need output/allocation/cppi_options_grid.csv: run optimize.py first.")
    print("Wrote", OUT)


if __name__ == "__main__":
    main()
