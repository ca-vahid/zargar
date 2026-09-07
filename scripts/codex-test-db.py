"""Create only the Codex test database on the local test server; never start an engine."""
import asyncio

import asyncpg


async def main():
    conn = await asyncpg.connect(
        host="127.0.0.1", port=5433, user="zargar", password="zargar",
        database="postgres", timeout=5,
    )
    try:
        exists = await conn.fetchval(
            "SELECT 1 FROM pg_database WHERE datname = $1", "zargar_test_codex"
        )
        if not exists:
            await conn.execute('CREATE DATABASE "zargar_test_codex" OWNER "zargar"')
    finally:
        await conn.close()
    conn = await asyncpg.connect(
        host="127.0.0.1", port=5433, user="zargar", password="zargar",
        database="zargar_test_codex", timeout=5,
    )
    try:
        print("Verified:", await conn.fetchval("SELECT current_database()"))
    finally:
        await conn.close()


if __name__ == "__main__":
    asyncio.run(main())
