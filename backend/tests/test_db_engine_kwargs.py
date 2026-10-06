"""DB engine construction (2026-10-05 loop profile: connection churn was ~25% of the main thread)."""
from zargar.db import MAX_OVERFLOW, POOL_SIZE, engine_kwargs, make_engine


def test_loopback_postgres_skips_tls_and_gets_a_real_pool():
    kw = engine_kwargs("postgresql+asyncpg://zargar:zargar@127.0.0.1:5432/zargar")
    assert kw["connect_args"] == {"ssl": False}
    assert kw["pool_size"] == POOL_SIZE and kw["max_overflow"] == MAX_OVERFLOW and kw["pool_pre_ping"]
    assert engine_kwargs("postgresql+asyncpg://z@localhost/z")["connect_args"] == {"ssl": False}


def test_an_explicit_ssl_setting_or_a_remote_host_is_left_alone():
    assert "connect_args" not in engine_kwargs("postgresql+asyncpg://z@127.0.0.1/z?ssl=require")
    assert "connect_args" not in engine_kwargs("postgresql+asyncpg://z@127.0.0.1/z?sslmode=verify-full")
    assert "connect_args" not in engine_kwargs("postgresql+asyncpg://z@db.example.com/z")


async def test_the_engine_connects_with_the_new_kwargs():
    import os
    from sqlalchemy import text
    url = os.environ.get("ZARGAR_TEST_DATABASE_URL", "postgresql+asyncpg://zargar@127.0.0.1:5433/zargar_test")
    eng = make_engine(url)
    try:
        async with eng.connect() as c:
            assert (await c.execute(text("select 1"))).scalar() == 1
        assert eng.pool.size() == POOL_SIZE
    finally:
        await eng.dispose()
