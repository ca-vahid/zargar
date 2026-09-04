"""FastAPI application factory.

NOTE: no `from __future__ import annotations` here — FastAPI must resolve the
locally-scoped Pydantic request models, which stringified annotations break.
"""
import logging
import time
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import Depends, FastAPI, HTTPException, Query, Request, Response, WebSocket
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel
from sqlalchemy import select

from .. import events as ev
from ..brokers.yahoo import RANGE_TFS, YahooQuoteFeed, search_symbols
from ..auth import COOKIE, AuthError, AuthService, cookie_kwargs
from ..config import AppConfig
from ..domain import new_id
from ..engine import Engine
from ..models import Event, Portfolio, Watchlist
from ..orders import OrderIntent
from .ws import WSHub

log = logging.getLogger("zargar.api")


def create_app(config: AppConfig, engine: Engine | None = None) -> FastAPI:
    eng = engine or Engine(config)
    hub = WSHub(eng)

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        if not eng.started:
            await eng.start()
        # signal layer (proposals/ingestion) attaches itself if available
        from ..signals.service import attach_signal_layer
        await attach_signal_layer(eng)
        from ..approvals.telegram import attach_telegram
        await attach_telegram(eng)
        from ..technique.service import attach_technique_layer
        await attach_technique_layer(eng)
        from ..techniques.flow.service import attach_flow_layer
        attach_flow_layer(eng)
        from ..techniques.tip.runner import attach_tip_runner
        await attach_tip_runner(eng)
        from ..techniques.team2.runner import attach_team2_runner
        await attach_team2_runner(eng)
        from ..desk import attach_desk
        attach_desk(eng)                      # morning report + roll watchdog + nightly soak
        await hub.start()
        yield
        await hub.stop()
        if getattr(eng, "tip_runner", None) is not None:
            await eng.tip_runner.stop()
        if getattr(eng, "flow_service", None) is not None:
            await eng.flow_service.stop()
        if eng.technique is not None:
            await eng.technique.stop()
        await eng.stop()

    app = FastAPI(title="Zargar", version="0.1.0", lifespan=lifespan)
    app.state.engine = eng
    app.state.hub = hub

    app.add_middleware(
        CORSMiddleware,
        allow_origins=[o.strip() for o in config.cors_origins.split(",") if o.strip()],
        allow_credentials=True,
        allow_methods=["*"],
        allow_headers=["*"],
    )

    # --- auth ----------------------------------------------------------------
    auth_svc: AuthService = getattr(eng, "auth", None) or AuthService(config, eng.settings)
    eng.auth = auth_svc

    async def require_auth(request: Request) -> None:
        if not auth_svc.required:
            return
        header = request.headers.get("authorization", "")
        bearer = header.removeprefix("Bearer ").strip() if header else ""
        user = auth_svc.authenticate(bearer=bearer or None, cookie=request.cookies.get(COOKIE),
                                     query_token=request.query_params.get("token") or None)
        if user is None:
            raise HTTPException(status_code=401, detail="sign in required")
        request.state.user = user

    auth = Depends(require_auth)

    class GoogleCredential(BaseModel):
        credential: str

    @app.get("/api/auth/config")
    async def auth_config():
        return auth_svc.public_config()

    @app.get("/api/auth/me")
    async def auth_me(request: Request):
        header = request.headers.get("authorization", "")
        bearer = header.removeprefix("Bearer ").strip() if header else ""
        user = auth_svc.authenticate(bearer=bearer or None, cookie=request.cookies.get(COOKIE),
                                     query_token=request.query_params.get("token") or None)
        return {"required": auth_svc.required, "user": user}

    # the sign-in endpoint is the one thing the public internet can poke at (Funnel):
    # 10 attempts per minute per client ip, then 429 — Google tokens are not guessable,
    # this just keeps a scripted hammering from burning CPU on JWKS verification
    auth_attempts: dict[str, list[float]] = {}

    def client_ip(request: Request) -> str:
        fwd = request.headers.get("x-forwarded-for", "")
        return (fwd.split(",")[0].strip() if fwd else (request.client.host if request.client else "?"))

    @app.post("/api/auth/google")
    async def auth_google(body: GoogleCredential, request: Request, response: Response):
        ip = client_ip(request)
        now = time.monotonic()
        recent = [t for t in auth_attempts.get(ip, []) if now - t < 60]
        if len(recent) >= 10:
            raise HTTPException(status_code=429, detail="too many sign-in attempts — wait a minute")
        recent.append(now)
        auth_attempts[ip] = recent
        if len(auth_attempts) > 1000:   # never grow without bound
            auth_attempts.clear()
        if len(body.credential) > 4096:
            raise HTTPException(status_code=400, detail="credential too large")
        try:
            user = auth_svc.sign_in_google(body.credential)
        except AuthError as exc:
            raise HTTPException(status_code=exc.status, detail=str(exc))
        token = auth_svc.issue_session(user)
        response.set_cookie(COOKIE, token, **cookie_kwargs(config, https=request.url.scheme == "https"))
        await eng.journal.append("AuthSignIn", {"email": user["email"], "provider": "google",
                                                 "client": request.headers.get("x-zargar-client", "desktop")})
        return {"user": user, "token": token}

    @app.post("/api/auth/logout")
    async def auth_logout(response: Response):
        response.delete_cookie(COOKIE, path="/")
        return {"ok": True}

    # --- health / state -----------------------------------------------------
    @app.get("/api/health")
    async def health(request: Request):
        from .. import __version__
        out = {"ok": True, "started": eng.started, "version": __version__}
        # the restart guard (scripts/start.ps1) runs on this machine and must see whether
        # paid analyst reads / armed plans are in flight even though the API is closed.
        # Loopback AND no proxy headers = a local caller (Tailscale serve/funnel proxies
        # from 127.0.0.1 too, but always with X-Forwarded-For).
        local = bool(request.client and request.client.host in ("127.0.0.1", "::1"))             and not request.headers.get("x-forwarded-for")
        if local:
            svc = getattr(eng, "technique", None)
            running = armed = 0
            if svc is not None:
                try:
                    st = await svc.status()
                    running = len(st.get("running") or [])
                    armed = len(st.get("armed") or [])
                except Exception:
                    log.debug("health: technique status unavailable", exc_info=True)
            out["local"] = {"techniqueRunning": running, "armed": armed}
        return out

    @app.get("/api/state", dependencies=[auth])
    async def state():
        return await eng.snapshot()

    # --- orders ---------------------------------------------------------------
    @app.post("/api/orders", dependencies=[auth])
    async def place_order(intent: OrderIntent, request: Request):
        # the client class is a server-side fact, never trusted from the body
        client = (request.headers.get("x-zargar-client") or "desktop").lower()
        intent.client = client if client in ("phone", "tablet", "desktop") else "desktop"
        try:
            order = await eng.orders.place(intent)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return order

    @app.post("/api/orders/{order_id}/cancel", dependencies=[auth])
    async def cancel_order(order_id: str):
        try:
            return await eng.orders.cancel(order_id)
        except ValueError as exc:
            raise HTTPException(status_code=404, detail=str(exc))

    @app.get("/api/orders", dependencies=[auth])
    async def list_orders(
        portfolio: str | None = None,
        open_only: bool = Query(default=False, alias="open"),
        limit: int = 200,
    ):
        return await eng.orders.list_orders(portfolio, open_only, limit)

    @app.get("/api/executions", dependencies=[auth])
    async def list_executions(portfolio: str | None = None, limit: int = 200):
        return await eng.orders.list_executions(portfolio, limit)

    # --- portfolios ------------------------------------------------------------
    class PortfolioCreate(BaseModel):
        name: str
        kind: str = "sim"
        starting_cash: float = 10_000.0
        source_name: str | None = None

    @app.get("/api/portfolios", dependencies=[auth])
    async def portfolios():
        out = []
        for p in eng.positions.portfolios():
            eq = await eng.positions.equity(p["id"])
            today = await eng.positions.daily_loss_pct(p["id"])
            # open positions ride along, marked to the live quote — equity above
            # cash with an empty positions list read as an accounting error
            # (Practice's BBAI LEAP, 2026-08-31)
            pos = [x for x in eng.positions.positions_list(p["id"]) if abs(x.get("qty", 0)) > 1e-9]
            out.append({**p, "equity": round(eq, 2), "cash": round(p["cash"], 2),
                        "todayPct": round(today, 2) if today is not None else None,
                        "positions": pos})
        return out

    @app.post("/api/portfolios", dependencies=[auth])
    async def create_portfolio(body: PortfolioCreate):
        if body.kind not in ("sim", "shadow", "paper", "live"):
            raise HTTPException(status_code=400, detail="invalid kind")
        row = Portfolio(
            id=new_id(), name=body.name, kind=body.kind,
            starting_cash=body.starting_cash, cash=body.starting_cash,
            source_name=body.source_name)
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        eng.positions.register_portfolio(row)
        return {"id": row.id, "name": row.name, "kind": row.kind,
                "cash": row.cash, "startingCash": row.starting_cash}

    @app.delete("/api/portfolios/{pid}", dependencies=[auth])
    async def remove_portfolio(pid: str):
        """Shadow research books ONLY (demo/test cleanup) — sim/paper/live are
        never deletable; the journal keeps the audit trail."""
        try:
            info = await eng.positions.remove_shadow(pid)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"ok": True, "removed": info.get("name")}

    @app.get("/api/portfolios/{pid}/equity", dependencies=[auth])
    async def equity_series(pid: str, limit: int = 2000, since: int = 0, points: int = 0):
        return await eng.positions.equity_series(pid, limit, since=since or None, points=points)

    # --- market data --------------------------------------------------------
    # (symbol, tf, range) -> (monotonic ts, rows): a chart re-render within a
    # few seconds must not cost another Yahoo call
    chart_cache: dict[tuple[str, str, str], tuple[float, list]] = {}
    CHART_CACHE_SECONDS = 20

    @app.get("/api/chart/{symbol}", dependencies=[auth])
    async def chart(symbol: str, tf: str = "1m", limit: int = 500,
                    rng: str | None = Query(default=None, alias="range")):
        symbol = symbol.upper()
        await eng.ensure_symbol(symbol)
        # explicit range -> real exchange history from Yahoo. The Hybrid feed
        # delegates fetch_bars to its Yahoo half; before it was included here,
        # 1d/5d charts silently fell back to the in-memory quote-built store
        # (restart seams, seed fragments and bad-print wicks included).
        from ..brokers.alpaca import HybridQuoteFeed as _Hybrid
        if rng and isinstance(eng.feed, (YahooQuoteFeed, _Hybrid)):
            if rng not in RANGE_TFS or tf not in RANGE_TFS[rng]:
                raise HTTPException(
                    status_code=400, detail=f"unsupported range/timeframe: {rng}/{tf}")
            key = (symbol, tf, rng)
            hit = chart_cache.get(key)
            if hit is not None and time.monotonic() - hit[0] < CHART_CACHE_SECONDS:
                rows = hit[1]
            else:
                bars = await eng.feed.fetch_bars(
                    symbol, tf=tf, range_=rng, include_pre_post=rng in ("1d", "5d"))
                rows = [b.to_row() for b in bars]
                if rows:
                    chart_cache[key] = (time.monotonic(), rows)
            if rows:
                return {"symbol": symbol, "tf": tf, "range": rng, "source": "yahoo",
                        "bars": rows}
            # Yahoo miss (cooldown, unknown symbol) -> fall back to local bars
        try:
            bars = eng.bars.bars(symbol, tf=tf, limit=limit)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return {"symbol": symbol, "tf": tf, "range": rng, "source": "local",
                "bars": [b.to_row() for b in bars]}

    @app.get("/api/quotes", dependencies=[auth])
    async def quotes(symbols: str = ""):
        wanted = [s.strip().upper() for s in symbols.split(",") if s.strip()]
        all_quotes = eng.quotes.all()
        if wanted:
            return {s: all_quotes[s].to_dict() for s in wanted if s in all_quotes}
        return {s: q.to_dict() for s, q in all_quotes.items()}

    class WatchBody(BaseModel):
        symbol: str

    @app.post("/api/watch", dependencies=[auth])
    async def watch(body: WatchBody):
        await eng.ensure_symbol(body.symbol)
        return {"ok": True, "symbol": body.symbol.upper()}

    # --- web push (phones) ----------------------------------------------------
    class PushSub(BaseModel):
        endpoint: str
        keys: dict = {}
        label: str = ""

    @app.get("/api/push/vapid", dependencies=[auth])
    async def push_vapid():
        svc = eng.push
        if svc is None or not svc.available:
            return {"available": False, "publicKey": None, "subscriptions": 0}
        return {"available": True, "publicKey": svc.public_key(), "subscriptions": len(svc.subscriptions())}

    @app.post("/api/push/subscribe", dependencies=[auth])
    async def push_subscribe(body: PushSub):
        if eng.push is None or not eng.push.available:
            raise HTTPException(status_code=503, detail="web push unavailable (pywebpush not installed)")
        n = await eng.push.subscribe({"endpoint": body.endpoint, "keys": body.keys}, body.label)
        return {"ok": True, "subscriptions": n}

    @app.delete("/api/push/subscribe", dependencies=[auth])
    async def push_unsubscribe(endpoint: str):
        if eng.push is None:
            return {"ok": True, "subscriptions": 0}
        return {"ok": True, "subscriptions": await eng.push.unsubscribe(endpoint)}

    @app.post("/api/push/test", dependencies=[auth])
    async def push_test():
        if eng.push is None:
            return {"sent": 0}
        return {"sent": await eng.push.send("Zargar", "push notifications are working", url="/armed", tag="test")}

    @app.get("/api/symbols/search", dependencies=[auth])
    async def symbols_search(q: str = Query(min_length=1, max_length=64)):
        try:
            results = await search_symbols(q.strip())
        except Exception:
            log.warning("symbol search failed for %r", q, exc_info=True)
            raise HTTPException(status_code=502, detail="symbol search unavailable")
        return {"results": results}

    # --- watchlists -----------------------------------------------------------
    class WatchlistBody(BaseModel):
        name: str
        symbols: list[str] = []

    @app.get("/api/watchlists", dependencies=[auth])
    async def get_watchlists():
        async with eng.sf() as session:
            rows = (await session.execute(select(Watchlist).order_by(Watchlist.sort))).scalars().all()
        return [{"id": w.id, "name": w.name, "sort": w.sort, "symbols": w.symbols or []} for w in rows]

    @app.post("/api/watchlists", dependencies=[auth])
    async def create_watchlist(body: WatchlistBody):
        row = Watchlist(id=new_id(), name=body.name,
                        symbols=[s.upper() for s in body.symbols])
        async with eng.sf() as session:
            session.add(row)
            await session.commit()
        return {"id": row.id, "name": row.name, "sort": row.sort, "symbols": row.symbols}

    @app.put("/api/watchlists/{wid}", dependencies=[auth])
    async def update_watchlist(wid: str, body: WatchlistBody):
        async with eng.sf() as session:
            row = await session.get(Watchlist, wid)
            if row is None:
                raise HTTPException(status_code=404, detail="watchlist not found")
            row.name = body.name
            row.symbols = [s.upper() for s in body.symbols]
            await session.commit()
        for s in body.symbols:
            await eng.ensure_symbol(s)
        return {"id": row.id, "name": row.name, "sort": row.sort, "symbols": row.symbols}

    @app.delete("/api/watchlists/{wid}", dependencies=[auth])
    async def delete_watchlist(wid: str):
        async with eng.sf() as session:
            row = await session.get(Watchlist, wid)
            if row is not None:
                await session.delete(row)
                await session.commit()
        return {"ok": True}

    # --- brokerages (SnapTrade) ----------------------------------------------
    @app.get("/api/brokerages", dependencies=[auth])
    async def brokerages():
        if eng.snaptrade_sync is None:
            return {"enabled": False, "lastSyncAt": None, "providers": []}
        return eng.snaptrade_sync.payload()

    class ImpactBody(BaseModel):
        portfolio_id: str
        symbol: str
        side: str
        qty: float
        order_type: str = "MKT"
        limit_price: float | None = None

    @app.post("/api/brokerages/impact", dependencies=[auth])
    async def order_impact(body: ImpactBody):
        """Broker-verified pre-trade impact (exact commission + forex fees).

        Read-only at the brokerage: SnapTrade validates without reserving
        funds; the returned trade id expires in ~5 minutes and we discard it.
        """
        if eng.snaptrade_sync is None or eng.snaptrade is None:
            raise HTTPException(status_code=503, detail="SnapTrade is not configured")
        account_id = eng.snaptrade_sync.account_for(body.portfolio_id)
        if account_id is None:
            raise HTTPException(status_code=400,
                                detail="portfolio is not a SnapTrade account")
        from ..brokers.snaptrade import SnapTradeError
        try:
            result = await eng.snaptrade.order_impact(
                account_id, symbol=body.symbol, side=body.side, qty=body.qty,
                order_type=body.order_type, limit_price=body.limit_price)
        except SnapTradeError as exc:
            # a broker-side verdict ("Not enough cash", "market closed") is an
            # answer, not a failure — hand it to the UI as one
            detail = exc.body if isinstance(exc.body, str) else (
                exc.body.get("detail") or exc.body.get("message") or str(exc.body))
            return {"error": str(detail)}
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"impact check failed: {exc}")
        return result

    @app.post("/api/brokerages/refresh", dependencies=[auth])
    async def refresh_brokerages():
        if eng.snaptrade_sync is None:
            raise HTTPException(
                status_code=503,
                detail="SnapTrade is not configured (credentials + snaptrade.enabled)")
        try:
            return await eng.snaptrade_sync.sync_once()
        except Exception as exc:
            raise HTTPException(status_code=502, detail=f"sync failed: {exc}")

    # --- settings ------------------------------------------------------------
    # --- the morning desk surface (POST-SOAK Phase 1) -------------------------
    @app.get("/api/desk/morning", dependencies=[auth])
    async def desk_morning():
        if getattr(eng, "desk", None) is None:
            raise HTTPException(status_code=503, detail="desk not attached")
        return await eng.desk.morning_report()

    @app.get("/api/desk/ledger", dependencies=[auth])
    async def desk_ledger(days: int = 30):
        """The plain-language money view: round trips, gains, corrections,
        open positions — real books only."""
        if getattr(eng, "desk", None) is None:
            raise HTTPException(status_code=503, detail="desk not attached")
        return await eng.desk.ledger(days=max(1, min(days, 365)))

    @app.post("/api/desk/morning/send", dependencies=[auth])
    async def desk_morning_send():
        """Manual trigger: compose + push + Telegram now (the scheduler does the
        same at desk.morning_at)."""
        if getattr(eng, "desk", None) is None:
            raise HTTPException(status_code=503, detail="desk not attached")
        return await eng.desk.morning_send()

    @app.get("/api/settings", dependencies=[auth])
    async def get_settings():
        return eng.settings.all()

    @app.patch("/api/settings", dependencies=[auth])
    async def patch_settings(body: dict):
        try:
            await eng.settings.set_many(body)
        except KeyError as exc:
            raise HTTPException(status_code=400, detail=str(exc))
        return eng.settings.all()

    # --- kill switch / system --------------------------------------------------
    class HaltBody(BaseModel):
        reason: str = "manual halt"

    @app.post("/api/halt", dependencies=[auth])
    async def halt(body: HaltBody):
        return await eng.engage_halt(body.reason, source="app")

    @app.post("/api/resume", dependencies=[auth])
    async def resume():
        return await eng.release_halt(source="app")

    @app.get("/api/events", dependencies=[auth])
    async def events(
        type: str | None = None,
        aggregate_id: str | None = None,
        portfolio: str | None = None,
        limit: int = 200,
    ):
        async with eng.sf() as session:
            stmt = select(Event).order_by(Event.id.desc()).limit(min(limit, 1000))
            if type:
                stmt = stmt.where(Event.type == type)
            if aggregate_id:
                stmt = stmt.where(Event.aggregate_id == aggregate_id)
            if portfolio:
                stmt = stmt.where(Event.portfolio_id == portfolio)
            rows = (await session.execute(stmt)).scalars().all()
        return [{
            "id": e.id, "ts": e.ts.isoformat(), "type": e.type,
            "aggregateType": e.aggregate_type, "aggregateId": e.aggregate_id,
            "portfolioId": e.portfolio_id, "payload": e.payload,
        } for e in rows]

    # --- websocket -----------------------------------------------------------
    @app.websocket("/ws")
    async def ws_endpoint(ws: WebSocket):
        if auth_svc.required:
            user = auth_svc.authenticate(query_token=ws.query_params.get("token") or None,
                                         cookie=ws.cookies.get(COOKIE))
            if user is None:
                await ws.close(code=4401)
                return
        await hub.handle(ws)

    # --- signal ingestion + proposals routes (phase 4/5) ------------------------
    from .routes_signals import build_signal_routes
    build_signal_routes(app, eng, auth, config)

    # --- technique pipeline + chat ------------------------------------------------
    from .routes_technique import build_technique_routes
    build_technique_routes(app, eng, auth, config)

    from .routes_options import build_options_routes
    build_options_routes(app, eng, auth, config)

    from .routes_flow import build_flow_routes
    build_flow_routes(app, eng, auth, config)

    from .routes_team2 import build_team2_routes
    build_team2_routes(app, eng, auth, config)

    # --- static SPA -----------------------------------------------------------
    if config.frontend_dist and Path(config.frontend_dist).is_dir():
        dist = Path(config.frontend_dist)
        app.mount("/assets", StaticFiles(directory=dist / "assets"), name="assets")

        dist_root = dist.resolve()

        @app.get("/{path:path}", include_in_schema=False)
        async def spa(path: str):
            # Deep links (/technique/run/<id>) fall through to index.html, but the
            # path is attacker-controlled: resolve it and refuse anything that
            # escapes the dist directory, or `../../backend/.env` is served.
            if path:
                candidate = (dist_root / path).resolve()
                if candidate.is_relative_to(dist_root) and candidate.is_file():
                    return FileResponse(candidate)
            return FileResponse(dist_root / "index.html")

    return app
