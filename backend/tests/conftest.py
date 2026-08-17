import asyncio
import os

import pytest

from zargar.config import AppConfig
from zargar.db import create_all, make_engine
from zargar.engine import Engine
from zargar.models import Base

TEST_DB_URL = os.environ.get(
    "ZARGAR_TEST_DATABASE_URL",
    "postgresql+asyncpg://zargar:zargar@127.0.0.1:5433/zargar_test",
)


def make_test_config(**overrides) -> AppConfig:
    defaults = dict(
        database_url=TEST_DB_URL,
        broker="sim",
        sim_tick_interval=0.03,
        sim_seed=42,
        sim_history_minutes=30,
        auth_token="",
        anthropic_api_key="",
        telegram_bot_token="",
    )
    defaults.update(overrides)
    return AppConfig(**defaults)


@pytest.fixture
async def fresh_db():
    """Drop and recreate all tables for isolation."""
    engine = make_engine(TEST_DB_URL)
    async with engine.begin() as conn:
        await conn.run_sync(Base.metadata.drop_all)
        await conn.run_sync(Base.metadata.create_all)
    await engine.dispose()
    yield


@pytest.fixture
async def engine(fresh_db):
    """A started Engine on the sim broker with a fresh database."""
    eng = Engine(make_test_config())
    await eng.start()
    try:
        yield eng
    finally:
        await eng.stop()


async def wait_for(predicate, timeout: float = 8.0, interval: float = 0.05):
    """Await an (async or sync) predicate becoming truthy."""
    loop = asyncio.get_event_loop()
    deadline = loop.time() + timeout
    while loop.time() < deadline:
        result = predicate()
        if asyncio.iscoroutine(result):
            result = await result
        if result:
            return result
        await asyncio.sleep(interval)
    raise TimeoutError("condition not met in time")
