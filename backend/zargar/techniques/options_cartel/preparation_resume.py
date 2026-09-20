"""Reuse compatible saved analyses across interrupted retry checkpoints."""
from sqlalchemy import select

from ...models import TechniqueRun
from .automatic_plans import PreparationPolicy


async def saved_work(engine, prior):
    if prior is None:
        return {}, {}, {}
    lineage=[];seen=set();source=prior
    policy=PreparationPolicy.model_validate(prior.config['policy'])
    async with engine.sf() as session:
        while source is not None and source.id not in seen and len(lineage)<32:
            if source.technique!='options_cartel' or source.mode!='preparation' or source.as_of!=prior.as_of \
                    or source.result.get('userCancelled') or any(source.config.get(k)!=prior.config.get(k)
                        for k in ('session','workspace','portfolioId','coverageVersion')) \
                    or PreparationPolicy.model_validate(source.config.get('policy',{}))!=policy:
                break
            seen.add(source.id);lineage.append(source)
            parent=source.result.get('resumedFrom')
            source=await session.get(TechniqueRun,parent) if parent else None
        rows={};pending={};reused={}
        for source in reversed(lineage):
            for row in source.result.get('rows',[]):
                if row.get('analysisId') and row.get('status') in ('candidate','filtered','research_only'):
                    rows[row['symbol']]=row;reused[row['symbol']]=row['analysisId']
            for row in source.result.get('shortlist',[]):
                if row.get('status')=='awaiting_contract': pending[row['symbol']]=row
                else: pending.pop(row['symbol'],None)
            children=(await session.execute(select(TechniqueRun.symbol,TechniqueRun.id).where(
                TechniqueRun.technique=='options_cartel',TechniqueRun.parent_run_id==source.id,
                TechniqueRun.mode=='analysis',TechniqueRun.config['inputs']['as_of_ms'].as_string()==str(prior.as_of),
                TechniqueRun.result['collection']['historyCacheVersion'].as_integer()==1
                ).order_by(TechniqueRun.created_at,TechniqueRun.id))).all()
            for child in children:
                if rows.get(child.symbol,{}).get('analysisId')!=child.id:
                    rows.pop(child.symbol,None)  # no filtered shortcut for a different revision
                reused[child.symbol]=child.id
    return rows,pending,reused
