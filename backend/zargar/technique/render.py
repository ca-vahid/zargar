"""Render OHLCV bars to a PNG for the vision passes and the chat surface.

The image the model sees is drawn from the same bars the deterministic layer
measured, so a level the model points at in the picture corresponds to a real
price in `facts`. Overlays are optional so the same renderer serves both the
"clean chart" passes and the "here is what we found" answer images.
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
    from matplotlib import dates as mdates  # noqa: F401
    return plt


UP = "#1fa35a"
DOWN = "#d84a4a"
BG = "#101418"
FG = "#d7dde3"
GRID = "#242b33"
LEVEL_SUP = "#3aa0ff"
LEVEL_RES = "#ffb020"
ENTRY = "#5b8cff"
STOP = "#ff4d4d"
TARGET = "#27c46b"
WEDGE = "#e040fb"


def _fmt_ts(ts_ms: int, tf: str) -> str:
    d = datetime.fromtimestamp(ts_ms / 1000, _MARKET_TZ)
    if tf in ("1d",):
        return d.strftime("%m-%d")
    if tf in ("1h",):
        return d.strftime("%m-%d %H:%M")
    return d.strftime("%H:%M")


def render_chart(
    bars: list[Bar],
    *,
    title: str = "",
    tf: str = "1m",
    levels: list[dict] | None = None,
    wedge: dict | None = None,
    setup: dict | None = None,
    width: int = 1280,
    height: int = 720,
    show_volume: bool = True,
    mark_last: bool = True,
) -> bytes:
    """Return PNG bytes. `levels`/`wedge`/`setup` take the to_dict() shapes
    produced by the technique modules."""
    plt = _mpl()
    if not bars:
        raise ValueError("no bars to render")

    n = len(bars)
    xs = list(range(n))
    dpi = 100
    fig = plt.figure(figsize=(width / dpi, height / dpi), dpi=dpi, facecolor=BG)
    if show_volume:
        gs = fig.add_gridspec(2, 1, height_ratios=[4, 1], hspace=0.04)
        ax = fig.add_subplot(gs[0])
        axv = fig.add_subplot(gs[1], sharex=ax)
    else:
        ax = fig.add_subplot(111)
        axv = None

    for a in (ax, axv):
        if a is None:
            continue
        a.set_facecolor(BG)
        a.tick_params(colors=FG, labelsize=9)
        for s in a.spines.values():
            s.set_color(GRID)
        a.grid(True, color=GRID, linewidth=0.6, alpha=0.6)

    # --- candles -----------------------------------------------------------
    body_w = 0.7
    for i, b in enumerate(bars):
        color = UP if b.close >= b.open else DOWN
        ax.vlines(i, b.low, b.high, color=color, linewidth=1)
        lo, hi = sorted((b.open, b.close))
        h = max(hi - lo, (b.high - b.low) * 0.02 or 1e-6)
        ax.add_patch(plt.Rectangle((i - body_w / 2, lo), body_w, h,
                                   facecolor=color, edgecolor=color, linewidth=0.8))
    ax.set_xlim(-1, n + max(6, n * 0.08))     # right margin for labels
    lo_all = min(b.low for b in bars)
    hi_all = max(b.high for b in bars)
    pad = (hi_all - lo_all) * 0.06 or 1.0
    ax.set_ylim(lo_all - pad, hi_all + pad)

    # --- levels ------------------------------------------------------------
    for lv in levels or []:
        price = float(lv["price"])
        kind = lv.get("kind", "support")
        color = LEVEL_SUP if kind == "support" else LEVEL_RES
        ax.axhline(price, color=color, linewidth=1.1, alpha=0.9,
                   linestyle="-" if lv.get("strong") else "--")
        label = f"{kind[:3].upper()} {price:.2f} ×{lv.get('touches', '?')}"
        ax.text(n + 0.5, price, label, color=color, fontsize=8, va="center")

    # --- wedge -------------------------------------------------------------
    if wedge:
        for key, col in (("upperTrendline", WEDGE), ("lowerTrendline", WEDGE)):
            line = wedge.get(key)
            if not line:
                continue
            x0 = int(wedge.get("startIndex", 0))
            x1 = int(wedge.get("endIndex", n - 1))
            y0 = line["intercept"] + line["slope"] * x0
            y1 = line["intercept"] + line["slope"] * x1
            ax.plot([x0, x1], [y0, y1], color=col, linewidth=1.4)

    # --- setup -------------------------------------------------------------
    if setup:
        e = setup.get("entry", {}).get("price")
        s = setup.get("stop", {}).get("price")
        if e is not None:
            ax.axhline(float(e), color=ENTRY, linewidth=1.4)
            ax.text(n + 0.5, float(e), f"ENTRY {float(e):.2f}", color=ENTRY, fontsize=8, va="center")
        if s is not None:
            ax.axhline(float(s), color=STOP, linewidth=1.2, linestyle="--")
            ax.text(n + 0.5, float(s), f"STOP {float(s):.2f}", color=STOP, fontsize=8, va="center")
        for i, t in enumerate(setup.get("targets") or []):
            p = float(t["price"])
            ax.axhline(p, color=TARGET, linewidth=1.0, linestyle=":")
            ax.text(n + 0.5, p, f"TP{i + 1} {p:.2f}", color=TARGET, fontsize=8, va="center")

    if mark_last:
        last = bars[-1]
        ax.annotate(f"{last.close:.2f}", xy=(n - 1, last.close), xytext=(n + 0.5, last.close),
                    color=FG, fontsize=8, va="center",
                    bbox=dict(boxstyle="round,pad=0.2", fc=GRID, ec="none"))

    # --- volume ------------------------------------------------------------
    if axv is not None:
        cols = [UP if b.close >= b.open else DOWN for b in bars]
        axv.bar(xs, [b.volume for b in bars], color=cols, width=0.7, alpha=0.85)
        axv.set_ylabel("vol", color=FG, fontsize=8)
        plt.setp(ax.get_xticklabels(), visible=False)

    # --- x ticks -----------------------------------------------------------
    step = max(1, n // 10)
    ticks = list(range(0, n, step))
    tgt = axv if axv is not None else ax
    tgt.set_xticks(ticks)
    tgt.set_xticklabels([_fmt_ts(bars[i].ts, tf) for i in ticks], rotation=0)

    if title:
        ax.set_title(f"{title}  ({_TZ_LABEL})", color=FG, fontsize=11, loc="left")

    buf = io.BytesIO()
    fig.savefig(buf, format="png", facecolor=BG, bbox_inches="tight")
    plt.close(fig)
    return buf.getvalue()
