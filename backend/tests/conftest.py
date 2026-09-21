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
        sim_option_sessions=False,   # suites fill options at any hour; EOD-05 gate has its own test
        sim_stock_sessions=False,    # suites fill shares at any hour; the F-HOLD-01 gate has its own test
        auth_token="",
        google_client_id="",       # sign-in off in tests even when backend/.env enables it
        google_allowed_emails="",
        session_secret="",
        anthropic_api_key="",
        telegram_bot_token="",
        persist_sim_bars=True,     # tests bank the sim feed's bars; the runtime refuses them (F75)
        alpaca_key_id="",          # never let a test reach OPRA/SIP with the real .env keys
        alpaca_secret="",
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


@pytest.fixture(autouse=True)
def _em_dispatch_controlled_clock(request, monkeypatch):
    """EM integrated review (2026-09-19): the reviewers' EM dispatch cases (`test_codex_em_final_dispatch_*`, adopted
    unchanged) size ONE $3.00 contract against a 2% budget. EM halves its size on Fridays (`technique.arm.friday_size_mult`),
    so on a Friday the sizer returned 0 contracts and the entry never reached the RiskGate - the cases failed for a
    calendar reason, not for the behaviour they test. They now run on a CONTROLLED clock (a Wednesday, 10:00 ET) through
    the test-pinnable `zargar.clock`. Only those modules are touched; an explicit ZARGAR_TEST_NOW still wins."""
    import os
    name = getattr(getattr(request, "module", None), "__name__", "") or ""
    if "test_codex_em_final_dispatch" in name and not os.environ.get("ZARGAR_TEST_NOW"):
        monkeypatch.setenv("ZARGAR_TEST_NOW", "2026-09-16T10:00:00-04:00")
    yield


@pytest.fixture(autouse=True)
def _team2_study_cli_uses_the_test_database(request, monkeypatch):
    """Team2 selection-study CLI tests start the real operator tool in a SUBPROCESS, which reads ZARGAR_DATABASE_URL (and
    otherwise backend/.env, i.e. the RUNTIME database). For those modules only, the subprocess inherits the test database."""
    name = getattr(getattr(request, "module", None), "__name__", "") or ""
    if "team2_selection" in name or "team2_release_boundaries" in name:
        monkeypatch.setenv("ZARGAR_DATABASE_URL", TEST_DB_URL)
    yield
