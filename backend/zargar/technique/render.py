"""Render OHLCV bars to a PNG for the vision passes and the chat surface.

The image the model sees is drawn from the same bars the deterministic layer
measured, so a level the model points at in the picture corresponds to a real
price in `facts`.

Framing rules (learned the hard way): levels far outside the bars' price range
are dropped rather than drawn, every label is clipped to the axes, and the
figure is saved on a fixed canvas. Drawing a label at a price outside `ylim`
with `bbox_inches="tight"` makes matplotlib grow the saved canvas to contain
it, which produced charts that were mostly empty space.
"""
from __future__ import annotations

import io
from datetime import datetime, timezone

from ..domain import Bar

try:  # US market clock for axis labels; UTC if the tz database is absent
    from zoneinfo import ZoneInfo
    _MARKET_TZ = ZoneInfo("America/New_York")
    _TZ_LABEL = "ET"
except Exception:  # pragma: no cover
    _MARKET_TZ = timezone.utc
    _TZ_LABEL = "UTC"

# Matplotlib is imported lazily: it is heavy and only the technique layer uses it.


def _mpl():
    import matplotlib
    matplotlib.use("Agg", force=False)
    import matplotlib.pyplot as plt  # noqa: WPS433
    return plt


UP = "#1fa35a"
DOWN = "#d84a4a"
BG = "#101418"
PANEL = "#151b21"
FG = "#d7dde3"
DIM = "#8b97a3"
GRID = "#242b33"
LEVEL_SUP = "#3aa0ff"
LEVEL_RES = "#ffb020"
ENTRY = "#5b8cff"
STOP = "#ff4d4d"
TARGET = "#27c46b"
WEDGE = "#e040fb"
REJECT = "#7a828c"

# Levels further than this multiple of the bar range are off-chart and dropped.
LEVEL_RANGE_MULT = 0.5


def _fmt_ts(ts_ms: int, tf: str, *, with_date: bool = False) -> str:
    d = datetime.fromtimestamp(ts_ms / 1000, _MARKET_TZ)
    if tf == "1d":
        return d.strftime("%m-%d")
    if with_date or tf == "1h":
        # Intraday windows spanning sessions must show the day, or the ticks
        # read as jumbled times (…15:55, 10:45…) across the overnight gap.
        return d.strftime("%m-%d") + "\n" + d.strftime("%H:%M")
    return d.strftime("%H:%M")


def _visible_levels(levels: list[dict], lo: float, hi: float) -> tuple[list[dict], int]:
    """Keep levels near the price action; report how many were dropped."""
    span = max(hi - lo, 1e-9)
    lo_ok, hi_ok = lo - span * LEVEL_RANGE_MULT, hi + span * LEVEL_RANGE_MULT
    keep = [lv for lv in levels or [] if lo_ok <= float(lv["price"]) <= hi_ok]
    return keep, len(levels or []) - len(keep)


def _draw_labels(ax, items: list[dict], y_lo: float, y_hi: float,
                 min_gap: float = 0.026) -> None:
    """Draw right-margin labels, nudged apart so none overlap.

    Positions are solved in axes-fraction space: sort by price, then sweep
    upward enforcing a minimum gap, then sweep down from the top to fix any
    overflow. Labels moved off their true price get a leader line back to it.
    """
    if not items:
        return
    span = max(y_hi - y_lo, 1e-9)
    for it in items:
        it["y0"] = (it["price"] - y_lo) / span
    # Higher-priority (lower number) items keep their spot; sort by position.
    items.sort(key=lambda i: i["y0"])
    ys = [it["y0"] for it in items]
    for i in range(1, len(ys)):
        if ys[i] - ys[i - 1] < min_gap:
            ys[i] = ys[i - 1] + min_gap
    if ys and ys[-1] > 1.0:
        ys[-1] = 1.0
        for i in range(len(ys) - 2, -1, -1):
            if ys[i + 1] - ys[i] < min_gap:
                ys[i] = ys[i + 1] - min_gap
    for it, y in zip(items, ys):
        kw = {}
        if it.get("box"):
            kw["bbox"] = dict(boxstyle="round,pad=0.25", fc=FG, ec="none")
        ax.annotate(it["text"], xy=(1.004, y), xycoords="axes fraction",
                    color=it["color"], fontsize=8, va="center", ha="left",
                    fontweight=it["weight"], annotation_clip=False, **kw)
        if abs(y - it["y0"]) > min_gap * 0.55:
            ax.annotate("", xy=(1.0, it["y0"]), xytext=(1.003, y),
                        xycoords="axes fraction", textcoords="axes fraction",
                        arrowprops=dict(arrowstyle="-", color=it["color"],
                                        lw=0.6, alpha=0.5),
                        annotation_clip=False)


def render_chart(
    bars: list[Bar],
    *,
    title: str = "",
    tf: str = "1m",
    levels: list[dict] | None = None,
    wedge: dict | None = None,
    setup: dict | None = None,
    rejected: dict | None = None,
    caption: str = "",
    width: int = 1280,
    height: int = 720,
    show_volume: bool = True,
    mark_last: bool = True,
) -> bytes:
    """Return PNG bytes.

    `levels`/`wedge`/`setup` take the to_dict() shapes from the technique
    modules. `rejected` draws a *candidate that failed* — entry/stop/targets in
    muted dashes — so a "no setup" chart shows what was considered and why,
    rather than just asserting a verdict. `caption` is drawn in the corner.
    """
    plt = _mpl()
    if not bars:
        raise ValueError("no bars to render")

    n = len(bars)
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=BG)
    if show_volume:
        gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.05,
                              left=0.055, right=0.86, top=0.93, bottom=0.09)
        ax = fig.add_subplot(gs[0])
        axv = fig.add_subplot(gs[1], sharex=ax)
    else:
        ax = fig.add_axes([0.055, 0.09, 0.805, 0.84])
        axv = None

    for a in (ax, axv):
        if a is None:
            continue
        a.set_facecolor(PANEL)
        a.tick_params(colors=DIM, labelsize=9)
        for s in a.spines.values():
            s.set_color(GRID)
        a.grid(True, color=GRID, linewidth=0.6, alpha=0.55)

    # --- price window --------------------------------------------------------
    lo_all = min(b.low for b in bars)
    hi_all = max(b.high for b in bars)
    vis_levels, dropped = _visible_levels(levels or [], lo_all, hi_all)

    # Expand the window to fit the levels we kept, so the capping resistance is
    # actually on screen — that is usually the reason a setup was rejected.
    y_lo, y_hi = lo_all, hi_all
    for lv in vis_levels:
        y_lo = min(y_lo, float(lv["price"]))
        y_hi = max(y_hi, float(lv["price"]))
    for blk in (setup, rejected):
        for key in ("entry", "stop"):
            v = (blk or {}).get(key, {}).get("price")
            if v is not None:
                y_lo, y_hi = min(y_lo, float(v)), max(y_hi, float(v))
        for t in (blk or {}).get("targets") or []:
            y_lo, y_hi = min(y_lo, float(t["price"])), max(y_hi, float(t["price"]))
    pad = (y_hi - y_lo) * 0.06 or 1.0
    ax.set_ylim(y_lo - pad, y_hi + pad)
    ax.set_xlim(-1, n)

    # --- candles -------------------------------------------------------------
    body_w = 0.7
    for i, b in enumerate(bars):
        color = UP if b.close >= b.open else DOWN
        ax.vlines(i, b.low, b.high, color=color, linewidth=0.9)
        blo, bhi = sorted((b.open, b.close))
        h = max(bhi - blo, (hi_all - lo_all) * 0.0015)
        ax.add_patch(plt.Rectangle((i - body_w / 2, blo), body_w, h,
                                   facecolor=color, edgecolor=color, linewidth=0.7))

    # Labels are collected, then de-collided and drawn at the end: several
    # markers legitimately share a price (entry sits ON a level, by design) and
    # drawing them at the same y makes an unreadable pile.
    pending: list[dict] = []

    def label(price: float, text: str, color: str, weight: str = "normal",
              *, box: bool = False, priority: int = 5) -> None:
        pending.append({"price": price, "text": text, "color": color,
                        "weight": weight, "box": box, "priority": priority})

    # --- levels --------------------------------------------------------------
    for lv in vis_levels:
        price = float(lv["price"])
        kind = lv.get("effectiveKind") or lv.get("kind", "support")
        color = LEVEL_SUP if kind == "support" else LEVEL_RES
        strong = bool(lv.get("strong")) or int(lv.get("touches", 0)) >= 3
        ax.axhline(price, color=color, linewidth=1.3 if strong else 0.9,
                   alpha=0.95 if strong else 0.6, linestyle="-" if strong else "--")
        label(price, f"{kind[:3].upper()} {price:.2f} ×{lv.get('touches', '?')}", color,
              priority=6 if strong else 7)

    # --- wedge ---------------------------------------------------------------
    if wedge:
        for key in ("upperTrendline", "lowerTrendline"):
            line = wedge.get(key)
            if not line:
                continue
            x0 = max(0, int(wedge.get("startIndex", 0)))
            x1 = min(n - 1, int(wedge.get("endIndex", n - 1)))
            y0 = line["intercept"] + line["slope"] * x0
            y1 = line["intercept"] + line["slope"] * x1
            ax.plot([x0, x1], [y0, y1], color=WEDGE, linewidth=1.5, alpha=0.9)

    # --- trade plan (accepted or rejected) -------------------------------------
    def draw_plan(blk: dict, *, muted: bool) -> None:
        e_col = REJECT if muted else ENTRY
        s_col = REJECT if muted else STOP
        t_col = REJECT if muted else TARGET
        ls = ":" if muted else "-"
        alpha = 0.75 if muted else 1.0
        e = (blk.get("entry") or {}).get("price")
        s = (blk.get("stop") or {}).get("price")
        if e is not None:
            ax.axhline(float(e), color=e_col, linewidth=1.8, linestyle=ls, alpha=alpha)
            label(float(e), f"{'✗ ' if muted else ''}ENTRY {float(e):.2f}", e_col, "bold", priority=1)
        if s is not None:
            ax.axhline(float(s), color=s_col, linewidth=1.3, linestyle="--", alpha=alpha)
            label(float(s), f"STOP {float(s):.2f}", s_col, priority=2)
        if e is not None and s is not None and not muted:
            ax.axhspan(float(s), float(e), color=STOP, alpha=0.07)
        for i, t in enumerate(blk.get("targets") or []):
            p = float(t["price"])
            ax.axhline(p, color=t_col, linewidth=1.0, linestyle=":", alpha=alpha)
            label(p, f"TP{i + 1} {p:.2f}", t_col, priority=3)
        if e is not None and (blk.get("targets") or []) and not muted:
            ax.axhspan(float(e), float(blk["targets"][-1]["price"]), color=TARGET, alpha=0.06)

    if setup:
        draw_plan(setup, muted=False)
    if rejected:
        draw_plan(rejected, muted=True)

    if mark_last:
        label(bars[-1].close, f"{bars[-1].close:.2f}", "#0f1419", "bold", box=True, priority=0)

    # --- de-collide and draw the right-margin labels ------------------------------
    _draw_labels(ax, pending, y_lo - pad, y_hi + pad)

    # --- caption / dropped-level note --------------------------------------------
    notes = []
    if caption:
        notes.append(caption)
    if dropped:
        notes.append(f"{dropped} level(s) outside this price window not drawn")
    if notes:
        ax.text(0.008, 0.975, "\n".join(notes), transform=ax.transAxes, color=FG,
                fontsize=8.5, va="top", ha="left", linespacing=1.5,
                bbox=dict(boxstyle="round,pad=0.4", fc="#0d1116", ec=GRID, alpha=0.92))

    # --- volume ---------------------------------------------------------------
    if axv is not None:
        cols = [UP if b.close >= b.open else DOWN for b in bars]
        axv.bar(range(n), [b.volume for b in bars], color=cols, width=0.7, alpha=0.85)
        axv.set_ylabel("vol", color=DIM, fontsize=8)
        axv.set_xlim(-1, n)
        plt.setp(ax.get_xticklabels(), visible=False)

    # --- x ticks ---------------------------------------------------------------
    step = max(1, n // 10)
    ticks = list(range(0, n, step))
    tgt = axv if axv is not None else ax
    tgt.set_xticks(ticks)
    # Mark the first tick of each session with its date; a window that spans
    # sessions is otherwise unreadable at HH:MM alone.
    day_of = [datetime.fromtimestamp(b.ts / 1000, _MARKET_TZ).date() for b in bars]
    multiday = day_of[0] != day_of[-1]
    labels = []
    prev_day = None
    for i in ticks:
        show_date = multiday and day_of[i] != prev_day
        labels.append(_fmt_ts(bars[i].ts, tf, with_date=show_date))
        prev_day = day_of[i]
    tgt.set_xticklabels(labels, fontsize=8)

    # Vertical rule at each session boundary.
    if multiday:
        for i in range(1, n):
            if day_of[i] != day_of[i - 1]:
                for a in (ax, axv):
                    if a is not None:
                        a.axvline(i - 0.5, color=GRID, linewidth=1.0, alpha=0.9)

    if title:
        ax.set_title(f"{title}   ({_TZ_LABEL})", color=FG, fontsize=11, loc="left", pad=8)

    buf = io.BytesIO()
    # Fixed canvas — never "tight", which would grow to fit stray artists.
    fig.savefig(buf, format="png", facecolor=BG)
    plt.close(fig)
    return buf.getvalue()
