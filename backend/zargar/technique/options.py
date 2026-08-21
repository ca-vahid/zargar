"""Options chain data and contract selection per spec module T5.

Providers (all normalize to the same row shape, so `select_contract` is
provider-agnostic):

* **CBOE** (default) — the free delayed-quotes JSON at
  `cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json`. No account,
  no token, works from Canada (Tradier's developer signup needs a US address).
  One request returns the whole chain **with greeks and IV** (delta/gamma/
  theta/vega per contract) plus the underlying's current price, ~15-min
  delayed. Verified live 2026-08-21.
* **Tradier** — kept for anyone with a token (`ZARGAR_TRADIER_TOKEN`);
  real-time, greeks via ORATS.
* IBKR native slots in here once the account activates (reqSecDefOptParams).

The T5 rules these make checkable:

    T5.1 strike just OTM            T5.3 do not buy elevated IV
    T5.2 current-week Friday / 0DTE T5.4 avoid wide spreads, poor greeks
"""
from __future__ import annotations

import datetime as dt
import logging
import re
import time
from dataclasses import dataclass, field

import httpx

log = logging.getLogger("zargar.technique.options")

TRADIER_PROD_BASE = "https://api.tradier.com/v1"
TRADIER_SANDBOX_BASE = "https://sandbox.tradier.com/v1"
CBOE_URL = "https://cdn.cboe.com/api/global/delayed_quotes/options/{symbol}.json"
UA = ("Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
      "(KHTML, like Gecko) Chrome/127.0.0.0 Safari/537.36")

# T5.4 heuristics — the book gives no numbers; these are ours (spec §10).
MAX_SPREAD_PCT = 10.0       # (ask-bid)/mid
MIN_OPEN_INTEREST = 100
MIN_VOLUME = 10
LOW_DELTA = 0.25
ELEVATED_IV = 0.60          # absolute mid IV; percentile needs history we lack


class OptionsError(RuntimeError):
    pass


@dataclass
class ContractPick:
    symbol: str
    underlying: str
    expiry: str
    strike: float
    option_type: str            # call | put
    bid: float
    ask: float
    mid: float
    spread_pct: float
    volume: int
    open_interest: int
    delta: float | None
    theta: float | None
    iv: float | None
    dte: int
    is_0dte: bool
    warnings: list[str] = field(default_factory=list)
    rules: list[str] = field(default_factory=list)

    def to_dict(self) -> dict:
        return {
            "symbol": self.symbol, "underlying": self.underlying, "expiry": self.expiry,
            "strike": self.strike, "optionType": self.option_type,
            "bid": self.bid, "ask": self.ask, "mid": round(self.mid, 4),
            "spreadPct": round(self.spread_pct, 2), "volume": self.volume,
            "openInterest": self.open_interest, "delta": self.delta, "theta": self.theta,
            "iv": self.iv, "dte": self.dte, "is0dte": self.is_0dte,
            "warnings": list(self.warnings), "rules": list(self.rules),
        }


# --- OCC symbology ------------------------------------------------------------

_OCC_RE = re.compile(r"^(?P<root>.+?)(?P<date>\d{6})(?P<cp>[CP])(?P<strike>\d{8})$")


def parse_occ(symbol: str) -> tuple[str, str, str, float] | None:
    """'SPY260821C00360000' → ('SPY', '2026-08-21', 'call', 360.0)."""
    m = _OCC_RE.match(symbol.strip().upper())
    if not m:
        return None
    d = m.group("date")
    expiry = f"20{d[0:2]}-{d[2:4]}-{d[4:6]}"
    cp = "call" if m.group("cp") == "C" else "put"
    strike = int(m.group("strike")) / 1000.0
    return m.group("root"), expiry, cp, strike


# --- CBOE (default; free, no credentials, works from Canada) --------------------

class CboeClient:
    """Free delayed chain with greeks. One ~6 MB fetch covers every expiry, so
    responses are cached per symbol for a short TTL."""

    name = "cboe"
    CACHE_TTL = 60.0

    def __init__(self, client: httpx.AsyncClient | None = None) -> None:
        self._http = client or httpx.AsyncClient(timeout=30, headers={"User-Agent": UA},
                                                 follow_redirects=True)
        self._cache: dict[str, tuple[float, dict]] = {}

    @property
    def available(self) -> bool:
        return True

    async def _payload(self, symbol: str) -> dict:
        sym = symbol.upper().strip()
        if "." in sym:
            raise OptionsError(f"{sym}: CBOE lists US options only (no .TO/.V symbols)")
        hit = self._cache.get(sym)
        now = time.time()
        if hit and now - hit[0] < self.CACHE_TTL:
            return hit[1]
        r = await self._http.get(CBOE_URL.format(symbol=sym))
        if r.status_code == 404:
            raise OptionsError(f"no US-listed options for {sym} (CBOE 404)")
        if r.status_code >= 400:
            raise OptionsError(f"CBOE HTTP {r.status_code}")
        data = (r.json() or {}).get("data") or {}
        if not data.get("options"):
            raise OptionsError(f"CBOE returned no contracts for {sym}")
        self._cache[sym] = (now, data)
        return data

    @staticmethod
    def _normalize(row: dict, underlying: str) -> dict | None:
        occ = parse_occ(row.get("option") or "")
        if occ is None:
            return None
        _root, expiry, cp, strike = occ
        iv = row.get("iv")
        return {
            "symbol": row.get("option"),
            "underlying": underlying,
            "expiry": expiry,
            "option_type": cp,
            "strike": strike,
            "bid": row.get("bid") or 0.0,
            "ask": row.get("ask") or 0.0,
            "volume": int(row.get("volume") or 0),
            "open_interest": int(row.get("open_interest") or 0),
            "greeks": {
                "delta": row.get("delta"),
                "theta": row.get("theta"),
                "mid_iv": iv if iv else None,   # CBOE reports 0.0 for deep ITM
            },
        }

    async def expirations(self, symbol: str) -> list[str]:
        data = await self._payload(symbol)
        out: set[str] = set()
        for row in data.get("options") or []:
            occ = parse_occ(row.get("option") or "")
            if occ:
                out.add(occ[1])
        return sorted(out)

    async def chain(self, symbol: str, expiry: str) -> list[dict]:
        data = await self._payload(symbol)
        sym = symbol.upper().strip()
        rows = []
        for row in data.get("options") or []:
            n = self._normalize(row, sym)
            if n and n["expiry"] == expiry:
                rows.append(n)
        return rows

    async def spot(self, symbol: str) -> float | None:
        data = await self._payload(symbol)
        v = data.get("current_price") or data.get("close")
        return float(v) if v else None

    async def aclose(self) -> None:
        await self._http.aclose()


# --- Tradier (optional; needs a token, US-only signup) ---------------------------

class TradierClient:
    name = "tradier"

    def __init__(self, token: str, *, sandbox: bool = False,
                 client: httpx.AsyncClient | None = None) -> None:
        self._token = token
        self._base = TRADIER_SANDBOX_BASE if sandbox else TRADIER_PROD_BASE
        self._http = client or httpx.AsyncClient(timeout=15)

    @property
    def available(self) -> bool:
        return bool(self._token)

    async def _get(self, path: str, params: dict) -> dict:
        if not self._token:
            raise OptionsError("Tradier token not configured (ZARGAR_TRADIER_TOKEN)")
        r = await self._http.get(f"{self._base}{path}", params=params, headers={
            "Authorization": f"Bearer {self._token}", "Accept": "application/json"})
        if r.status_code == 401:
            raise OptionsError("Tradier rejected the token (401)")
        if r.status_code >= 400:
            raise OptionsError(f"Tradier HTTP {r.status_code}: {r.text[:200]}")
        return r.json() or {}

    async def expirations(self, symbol: str) -> list[str]:
        data = await self._get("/markets/options/expirations",
                               {"symbol": symbol.upper(), "includeAllRoots": "true"})
        exp = (data.get("expirations") or {}).get("date") or []
        if isinstance(exp, str):
            exp = [exp]
        return sorted(exp)

    async def chain(self, symbol: str, expiry: str) -> list[dict]:
        data = await self._get("/markets/options/chains",
                               {"symbol": symbol.upper(), "expiration": expiry, "greeks": "true"})
        opts = (data.get("options") or {}).get("option") or []
        if isinstance(opts, dict):
            opts = [opts]
        out = []
        for c in opts:
            g = c.get("greeks") or {}
            out.append({
                "symbol": c.get("symbol"),
                "underlying": c.get("underlying") or c.get("root_symbol") or symbol.upper(),
                "expiry": expiry,
                "option_type": (c.get("option_type") or "").lower(),
                "strike": float(c.get("strike") or 0),
                "bid": c.get("bid") or 0.0,
                "ask": c.get("ask") or 0.0,
                "volume": int(c.get("volume") or 0),
                "open_interest": int(c.get("open_interest") or 0),
                "greeks": {"delta": g.get("delta"), "theta": g.get("theta"),
                           "mid_iv": g.get("mid_iv") or g.get("smv_vol")},
            })
        return out

    async def spot(self, symbol: str) -> float | None:
        data = await self._get("/markets/quotes", {"symbols": symbol.upper(), "greeks": "false"})
        q = (data.get("quotes") or {}).get("quote") or {}
        if isinstance(q, list):
            q = q[0] if q else {}
        v = q.get("last") or q.get("close")
        return float(v) if v else None

    async def aclose(self) -> None:
        await self._http.aclose()


# --- selection (provider-agnostic) ------------------------------------------------

def choose_expiry(expirations: list[str], today: dt.date) -> tuple[str | None, bool]:
    """T5.2 — same-day (0DTE) if listed, else the nearest expiry on/before this
    week's Friday, else the very next expiry."""
    dates = []
    for s in expirations:
        try:
            dates.append(dt.date.fromisoformat(s))
        except ValueError:
            continue
    dates = sorted(d for d in dates if d >= today)
    if not dates:
        return None, False
    if dates[0] == today:
        return dates[0].isoformat(), True
    friday = today + dt.timedelta(days=(4 - today.weekday()) % 7)
    this_week = [d for d in dates if d <= friday]
    pick = this_week[-1] if this_week else dates[0]
    return pick.isoformat(), False


def select_contract(chain: list[dict], spot: float, direction: str, *, expiry: str,
                    today: dt.date, is_0dte: bool) -> ContractPick | None:
    """T5.1 — the first strike just OTM in the trade direction, with T5.3/T5.4
    warnings attached. Returns None if the chain has no usable contract."""
    want = "call" if direction == "long" else "put"
    rows = [c for c in chain if (c.get("option_type") or "").lower() == want]
    if not rows:
        return None
    if want == "call":
        otm = [c for c in rows if float(c.get("strike", 0)) > spot]
        otm.sort(key=lambda c: float(c["strike"]))
    else:
        otm = [c for c in rows if float(c.get("strike", 0)) < spot]
        otm.sort(key=lambda c: -float(c["strike"]))
    if not otm:
        return None
    c = otm[0]
    bid = float(c.get("bid") or 0.0)
    ask = float(c.get("ask") or 0.0)
    mid = (bid + ask) / 2 if (bid or ask) else 0.0
    spread_pct = ((ask - bid) / mid * 100) if mid > 0 else 999.0
    g = c.get("greeks") or {}
    delta = g.get("delta")
    theta = g.get("theta")
    iv = g.get("mid_iv")
    try:
        exp_d = dt.date.fromisoformat(expiry)
        dte = (exp_d - today).days
    except ValueError:
        dte = -1

    warnings: list[str] = []
    rules = ["T5.1", "T5.2"]
    if spread_pct > MAX_SPREAD_PCT:
        warnings.append(f"T5.4 wide spread {spread_pct:.1f}% (bid {bid} / ask {ask})")
    if int(c.get("open_interest") or 0) < MIN_OPEN_INTEREST:
        warnings.append(f"T5.4 thin open interest {c.get('open_interest')}")
    if int(c.get("volume") or 0) < MIN_VOLUME:
        warnings.append(f"T5.4 low volume today {c.get('volume')}")
    if delta is not None and abs(float(delta)) < LOW_DELTA:
        warnings.append(f"T5.4 low delta {float(delta):.2f}")
    if iv is not None and float(iv) >= ELEVATED_IV:
        warnings.append(f"T5.3 elevated IV {float(iv):.2f} — IV-crush risk")
    if is_0dte:
        warnings.append("T5.2 0DTE: use reduced size")
    if warnings:
        rules.extend(sorted({w.split()[0] for w in warnings}))

    return ContractPick(
        symbol=str(c.get("symbol")), underlying=str(c.get("underlying") or ""),
        expiry=expiry, strike=float(c["strike"]), option_type=want,
        bid=bid, ask=ask, mid=mid, spread_pct=spread_pct,
        volume=int(c.get("volume") or 0), open_interest=int(c.get("open_interest") or 0),
        delta=float(delta) if delta is not None else None,
        theta=float(theta) if theta is not None else None,
        iv=float(iv) if iv is not None else None,
        dte=dte, is_0dte=is_0dte, warnings=warnings, rules=sorted(set(rules)),
    )


async def pick_for_setup(client, symbol: str, spot: float, direction: str,
                         *, today: dt.date | None = None) -> dict:
    """End-to-end: expirations → expiry choice → chain → contract. `client` is
    any provider exposing expirations()/chain() with normalized rows. Never
    raises for 'no contract'; returns a dict with `error` for hard failures."""
    today = today or dt.date.today()
    try:
        exps = await client.expirations(symbol)
        expiry, is_0dte = choose_expiry(exps, today)
        if not expiry:
            return {"error": "no expirations listed", "available": False,
                    "provider": getattr(client, "name", "?")}
        chain = await client.chain(symbol, expiry)
        pick = select_contract(chain, spot, direction, expiry=expiry, today=today, is_0dte=is_0dte)
        if pick is None:
            return {"error": f"no {('call' if direction == 'long' else 'put')} just OTM at {expiry}",
                    "expiry": expiry, "available": True, "provider": getattr(client, "name", "?")}
        d = pick.to_dict()
        d["available"] = True
        d["chainSize"] = len(chain)
        d["provider"] = getattr(client, "name", "?")
        return d
    except OptionsError as exc:
        return {"error": str(exc), "available": False, "provider": getattr(client, "name", "?")}
    except httpx.HTTPError as exc:
        return {"error": f"network: {exc}", "available": False, "provider": getattr(client, "name", "?")}
