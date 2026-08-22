from __future__ import annotations

import logging

from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncEngine, AsyncSession, async_sessionmaker, create_async_engine
from sqlalchemy.schema import CreateColumn

from .models import Base

log = logging.getLogger("zargar.db")


def make_engine(url: str, echo: bool = False) -> AsyncEngine:
    return create_async_engine(url, echo=echo, pool_pre_ping=True)


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
    return added


async def create_all(engine: AsyncEngine) -> None:
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.create_all)
        added = await conn.run_sync(_ensure_columns_sync)
    if added:
        log.info("schema: added columns %s", ", ".join(added))
