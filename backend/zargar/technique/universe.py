"""The trading universe — which symbols the technique plans, sheets and arms.

The book trades "mega cap stocks" (p. 8) where "wide bid/ask spreads are rarely
an issue" (p. 31) and open interest "is always enough" (p. 28). Three days of
live data (docs/techniques/enhanced-market/METHOD-REVIEW-2026-08-26.md §0.6) showed half our friction
came from names outside that world (T's 13-cent stop, CHPT at $6). The user's
decision (2026-08-26): a LARGE default set of big, famous, heavily-traded names,
refreshed daily from what is actually trading, plus anything they add by hand.

Three layers, merged by `resolve()`:

* **core**  — `technique.walkforward.symbols`: the curated list (index/sector
  ETFs with daily or M/W/F expiries, mega caps, the most active single-name
  options), ranked by one day's consolidated options volume (CBOE chains,
  2026-08-26) so the front of the list is the most liquid.
* **auto**  — the day's most-active US stocks (Alpaca screener when keys are
  set, else Yahoo's predefined `most_actives` screener), filtered to price >=
  `technique.universe.min_price`, real US equities, not excluded. Refreshed
  once per session before the evening sheet and on demand.
* **extra** — `technique.universe.extra`: the user's own additions, always in.

`technique.universe.exclude` removes a symbol from every layer. The resolved
list (with provenance per symbol) is cached in `technique.universe.resolved`.
"""
from __future__ import annotations

import datetime as dt
import logging
import re

import httpx

log = logging.getLogger("zargar.technique.universe")

# Curated 2026-08-26 (research: CBOE chain volume per underlying, S&P 100 /
# Nasdaq-100 membership, TipRanks most-active options, price >= $20). Most
# options-liquid first. Non-US listings (.TO/.V) never belong here — CBOE has
# no chain for them.
CORE_UNIVERSE: list[str] = [
    "SPY", "QQQ", "TSLA", "NVDA", "META", "AAPL", "IWM", "INTC", "AMZN", "MU",
    "TLT", "IBIT", "MSFT", "GLD", "AMD", "GOOGL", "PLTR", "SLV", "MSTR", "AVGO",
    "GDX", "HYG", "ORCL", "TQQQ", "XLE", "NKE", "NFLX", "SOXL", "WMT", "USO",
    "GOOG", "CRWD", "MRNA", "SMH", "SMCI", "CRM", "HOOD", "UBER", "EEM", "LQD",
    "BABA", "MRVL", "BAC", "COIN", "PFE", "XLF", "INTU", "OKLO", "TSM", "DELL",
    "NOW", "LLY", "KO", "ARM", "FXI", "CVNA", "BA", "KWEB", "VZ", "FCX",
    "XOP", "JPM", "XOM", "UPS", "RDDT", "CSCO", "QCOM", "ANET", "UNH", "T",
    "ARKK", "DIS", "SCHW", "VRT", "CVX", "SQQQ", "PANW", "XBI", "AMAT", "CCL",
    "DIA", "GS", "TXN", "KRE", "C", "XLU", "V", "LRCX", "WFC", "BRK.B",
    "SOXX", "PYPL", "APP", "ADBE", "MCD", "VST", "XLK", "FSLR", "ABT", "AMGN",
    "COST", "PG", "XLP", "AXP", "SOXS", "XLI", "PEP", "OXY", "DAL", "JNJ",
    "MRK", "HD", "GM", "MS", "CAT", "XLV", "SBUX",
]

ALPACA_MOST_ACTIVES = "https://data.alpaca.markets/v1beta1/screener/stocks/most-actives"
ALPACA_SNAPSHOTS = "https://data.alpaca.markets/v2/stocks/snapshots"
YAHOO_MOST_ACTIVES = ("https://query1.finance.yahoo.com/v1/finance/screener/predefined/saved"
                      "?formatted=false&lang=en-US&region=US&scrIds=most_actives&start=0&count=250")
_UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) zargar/1.0"}

_SYMBOL_OK = re.compile(r"^[A-Z]{1,5}(\.[A-Z])?$")


def _clean(symbols) -> list[str]:
    out: list[str] = []
    for s in symbols or []:
        s = str(s or "").strip().upper()
        if s and s not in out:
            out.append(s)
    return out


def is_us_optionable_symbol(sym: str) -> bool:
    """US-listed common stock / ETF ticker shape (BRK.B allowed); no .TO/.V,
    no FX (=X), no warrants/units, no OCC option symbols."""
    s = (sym or "").upper()
    if not _SYMBOL_OK.match(s):
        return False
    if s.endswith((".TO", ".V", ".CN", ".NE")):
        return False
    return True


async def fetch_most_actives(*, alpaca_key: str = "", alpaca_secret: str = "", top: int = 100,
                             client: httpx.AsyncClient | None = None) -> list[dict]:
    """Today's most-active US stocks: `[{symbol, volume, price?, source}]`.
    Alpaca's SIP screener when keys are configured (falls through to Yahoo on
    any error), else Yahoo's predefined `most_actives` screener (no auth, needs
    a User-Agent; pre-filtered to day volume > 5M and market cap > $2B)."""
    own = client is None
    client = client or httpx.AsyncClient(timeout=15.0)
    try:
        if alpaca_key and alpaca_secret:
            try:
                hdr = {"APCA-API-KEY-ID": alpaca_key, "APCA-API-SECRET-KEY": alpaca_secret}
                # by=trades: how many people traded it today — the "famous" signal; raw
                # share volume is dominated by sub-$5 names the price floor removes anyway
                r = await client.get(ALPACA_MOST_ACTIVES, params={"by": "trades", "top": min(100, max(1, top))},
                                     headers=hdr)
                r.raise_for_status()
                rows = (r.json() or {}).get("most_actives") or []
                out = [{"symbol": str(x.get("symbol") or "").upper(), "volume": int(x.get("volume") or 0),
                        "trades": int(x.get("trade_count") or 0), "price": None, "source": "alpaca"}
                       for x in rows if x.get("symbol")]
                if out:
                    # the screener carries no price; one snapshot call prices the whole list
                    syms = [o["symbol"] for o in out]
                    for i in range(0, len(syms), 100):
                        chunk = syms[i:i + 100]
                        try:
                            rs = await client.get(ALPACA_SNAPSHOTS, params={"symbols": ",".join(chunk), "feed": "sip"},
                                                  headers=hdr)
                            rs.raise_for_status()
                            snaps = rs.json() or {}
                            for o in out:
                                sn = snaps.get(o["symbol"]) or {}
                                px = ((sn.get("latestTrade") or {}).get("p") or (sn.get("dailyBar") or {}).get("c")
                                      or (sn.get("prevDailyBar") or {}).get("c"))
                                if px:
                                    o["price"] = float(px)
                        except Exception as exc:  # pragma: no cover - network
                            log.warning("alpaca snapshots failed (%s); auto rows without a price are skipped", exc)
                    return out
            except Exception as exc:  # pragma: no cover - network
                log.warning("alpaca most-actives failed (%s); falling back to Yahoo", exc)
        r = await client.get(YAHOO_MOST_ACTIVES, headers=_UA)
        r.raise_for_status()
        res = ((r.json() or {}).get("finance") or {}).get("result") or []
        quotes = (res[0].get("quotes") if res else None) or []
        out = []
        for q in quotes:
            sym = str(q.get("symbol") or "").upper()
            if not sym:
                continue
            out.append({"symbol": sym, "volume": int(q.get("regularMarketVolume") or 0),
                        "price": float(q.get("regularMarketPrice") or 0) or None,
                        "avgVolume": int(q.get("averageDailyVolume3Month") or 0),
                        "marketCap": float(q.get("marketCap") or 0) or None, "source": "yahoo"})
        out.sort(key=lambda x: -x["volume"])
        return out[:top]
    finally:
        if own:
            await client.aclose()


def resolve(*, core: list[str], extra: list[str], exclude: list[str], auto: list[dict],
            min_price: float = 20.0, auto_top: int = 40, prices: dict[str, float] | None = None,
            flow: list[str] | None = None) -> dict:
    """Merge the layers into the working universe. Order: core (already ranked
    by liquidity) -> extras -> flow (symbols the options-flow scanner is
    tracking — docs/techniques/flow/UI-PLAN.md F5) -> auto additions not
    already present. Auto rows need a price >= `min_price` (from the row or
    `prices`) and a US-equity symbol shape; anything in `exclude` is dropped
    from every layer.
    Returns {"symbols": [...], "provenance": {sym: "core|extra|flow|auto"}, "dropped": [...]}."""
    ex = set(_clean(exclude))
    prices = prices or {}
    symbols: list[str] = []
    prov: dict[str, str] = {}
    dropped: list[dict] = []

    def add(sym: str, why: str) -> None:
        if sym in ex:
            dropped.append({"symbol": sym, "reason": "excluded"})
            return
        if sym not in prov:
            symbols.append(sym)
            prov[sym] = why

    for s in _clean(core):
        add(s, "core")
    for s in _clean(extra):
        add(s, "extra")
    for s in _clean(flow or []):
        if is_us_optionable_symbol(s):
            add(s, "flow")
    n_auto = 0
    for row in auto or []:
        sym = str(row.get("symbol") or "").upper()
        if not sym or sym in prov:
            continue
        if n_auto >= auto_top:
            break
        if not is_us_optionable_symbol(sym):
            dropped.append({"symbol": sym, "reason": "not a US equity symbol"})
            continue
        px = row.get("price") or prices.get(sym)
        if px is not None and float(px) < min_price:
            dropped.append({"symbol": sym, "reason": f"price {float(px):.2f} < {min_price:g}"})
            continue
        if px is None:
            dropped.append({"symbol": sym, "reason": "no price to check the floor"})
            continue
        add(sym, "auto")
        n_auto += 1
    return {"symbols": symbols, "provenance": prov, "dropped": dropped,
            "counts": {"core": sum(1 for v in prov.values() if v == "core"),
                       "extra": sum(1 for v in prov.values() if v == "extra"),
                       "flow": sum(1 for v in prov.values() if v == "flow"),
                       "auto": sum(1 for v in prov.values() if v == "auto")}}


def today_key() -> str:
    from .rulebook import ET
    return dt.datetime.now(ET).strftime("%Y-%m-%d")
