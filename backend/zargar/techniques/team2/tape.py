"""C6 canonical inputs. Snapshots retain exact rows across correction/restart."""
from dataclasses import asdict
from sqlalchemy.dialects.postgresql import insert
from ...domain import Bar
from ...marketdata import hash_bars
from ...models import Team2TapeSnapshot


async def save_snapshot(sf, bars: list[Bar]) -> str:
    by_symbol = {}
    for b in bars:
        by_symbol.setdefault(b.symbol, []).append(b)
    identity = hash_bars(by_symbol)
    payload = {"identity": identity, "bars": [asdict(b) for b in bars]}
    async with sf() as session:
        await session.execute(insert(Team2TapeSnapshot).values(id=identity["hash"], payload=payload)
                              .on_conflict_do_nothing(index_elements=["id"]))
        await session.commit()
    return identity["hash"]


async def load_snapshot(sf, identity: str) -> list[Bar]:
    async with sf() as session:
        row = await session.get(Team2TapeSnapshot, identity)
        if row is None:
            raise ValueError(f"C6: missing input snapshot {identity}")
        bars = [Bar(**b) for b in row.payload["bars"]]
    grouped = {}
    for b in bars:
        grouped.setdefault(b.symbol, []).append(b)
    if hash_bars(grouped)["hash"] != identity:
        raise ValueError("C6: snapshot content hash mismatch")
    return bars
