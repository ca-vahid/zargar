"""Short-transaction lease for a preparation owner; no long-lived transaction."""
from sqlalchemy import update
from sqlalchemy.dialects.postgresql import insert

from ...models import CartelPreparationLease


async def claim(engine, workspace, owner, now):
    async with engine.sf() as session, session.begin():
        stmt = insert(CartelPreparationLease).values(workspace=workspace, owner=owner, expires_at=now+120000)
        obtained = await session.scalar(stmt.on_conflict_do_update(index_elements=['workspace'],
            set_={'owner':owner,'expires_at':now+120000}, where=CartelPreparationLease.expires_at<=now).returning(CartelPreparationLease.owner))
        if obtained != owner:
            raise ValueError('Preparation lease is active; retry after its checkpoint or restart recovery window')


async def renew(engine, workspace, owner, now):
    async with engine.sf() as session, session.begin():
        changed = await session.execute(update(CartelPreparationLease).where(
            CartelPreparationLease.workspace==workspace, CartelPreparationLease.owner==owner,
            CartelPreparationLease.expires_at>now).values(expires_at=now+120000))
        if changed.rowcount != 1:
            raise ValueError('Preparation ownership expired or changed; this worker cannot publish arms')


async def release(engine, workspace, owner):
    async with engine.sf() as session, session.begin():
        await session.execute(update(CartelPreparationLease).where(CartelPreparationLease.workspace==workspace,
            CartelPreparationLease.owner==owner).values(expires_at=0))
