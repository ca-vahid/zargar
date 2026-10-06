from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateColumn

from .models import Base

log = logging.getLogger("zargar.db")


_LOOPBACK = {"127.0.0.1", "localhost", "::1"}

# 2026-10-05 (py-spy, market hours): ~25% of the event loop's main thread went to OPENING Postgres connections -
# the default pool keeps 5 and closes every overflow connection on return, and each new asyncpg connection under the
# default sslmode=prefer builds an SSLContext, resolves ~/.postgresql/* cert paths (Windows realpath) and tries TLS
# before falling back on a server with ssl=off. A pool that covers the app's concurrency keeps connections reused.
POOL_SIZE = 30            # minute-bar bursts (armed plans, positions, bar flush) stay on held connections
MAX_OVERFLOW = 10         # <= 40 total of the server's 100 (tools + tests share it)


def engine_kwargs(url: str) -> dict:
    """create_async_engine kwargs: a pool sized for the engine's concurrency, and no TLS attempt to a LOOPBACK
    database whose URL does not ask for it (an explicit ssl/sslmode in the URL always wins)."""
    from sqlalchemy.engine import make_url
    kw: dict = {"pool_pre_ping": True, "pool_size": POOL_SIZE, "max_overflow": MAX_OVERFLOW}
    try:
        u = make_url(url)
    except Exception:  # noqa: BLE001 - let create_async_engine report a bad URL
        return kw
    query = {k.lower() for k in (u.query or {})}
    if u.get_backend_name() == "postgresql" and (u.host or "") in _LOOPBACK and not ({"ssl", "sslmode"} & query):
        kw["connect_args"] = {"ssl": False}
    return kw


def make_engine(url: str, echo: bool = False) -> AsyncEngine:
    return create_async_engine(url, echo=echo, **engine_kwargs(url))


def make_session_factory(engine: AsyncEngine) -> async_sessionmaker[AsyncSession]:
    return async_sessionmaker(engine, expire_on_commit=False)


def _python_default(col):
    """The column's Python-side default as a value (None when there is none)."""
    d = col.default
    if d is None:
        return None
    arg = getattr(d, "arg", None)
    if callable(arg):
        try:
            return arg(None)          # context-taking callables (dict, list, utcnow)
        except TypeError:
            return arg()
    return arg


def _ensure_columns_sync(conn) -> list[str]:
    """Additive schema migration: add any mapped column that the live table
    lacks. `create_all` only creates *missing tables*, so a new column on an
    existing table would otherwise silently break the first query. Only
    additions are performed (never drops / type changes) — removing a column
    is a deliberate, manual step.

    Non-nullable columns are added nullable, back-filled with the mapped
    Python default (e.g. `{}` for JSON columns), then tightened to NOT NULL,
    so tables that already hold rows migrate cleanly."""
    insp = inspect(conn)
    existing_tables = set(insp.get_table_names())
    added: list[str] = []
    for table in Base.metadata.sorted_tables:
        if table.name not in existing_tables:
            continue
        have = {c["name"] for c in insp.get_columns(table.name)}
        for col in table.columns:
            if col.name in have:
                continue
            loose = col._copy()
            loose.nullable = True
            ddl = CreateColumn(loose).compile(dialect=conn.dialect)
            conn.execute(text(f"ALTER TABLE {table.name} ADD COLUMN {ddl}"))
            if not col.nullable:
                default = _python_default(col)
                if default is not None:
                    conn.execute(table.update().where(col.is_(None)).values({col.name: default}))
                    conn.execute(text(f"ALTER TABLE {table.name} ALTER COLUMN {col.name} SET NOT NULL"))
            added.append(f"{table.name}.{col.name}")
        # declared indexes the live table lacks (a unique index on a column added
        # above is what makes a research observation's identity enforceable in
        # the DB, HOLD142-02 2026-09-15); additive only, never dropped here
        have_idx = {i["name"] for i in insp.get_indexes(table.name)}
        for idx in table.indexes:
            if idx.name and idx.name not in have_idx and all(c.name in have or c.name in
                                                                {a.split(".", 1)[1] for a in added if a.startswith(table.name + ".")}
                                                                for c in idx.columns):
                idx.create(conn)
                added.append(f"{table.name}:{idx.name}")
    return added


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        added = await conn.run_sync(_ensure_columns_sync)
    if added:
        log.info("schema: added columns %s", ", ".join(added))
