"""Real indexer/Bridge interleaving; no model, provider or original-data writes."""
import asyncio
from contextlib import asynccontextmanager
import os
from unittest.mock import AsyncMock

import numpy as np
import pytest
from sqlalchemy import text
from sqlalchemy.exc import DBAPIError
from sqlalchemy.sql.dml import Update

from test_audit_postgres import database, seed
from interviewlens.agent import processing
from interviewlens.api import routes_bridge
from interviewlens.api.schemas import BridgeGenerateRequest
from interviewlens.embedding import backfill

pytestmark=pytest.mark.skipif(not os.environ.get('IL_TEST_BACKFILL_DSN'),reason='isolated PostgreSQL DSN required')


@pytest.mark.parametrize('database',[False,True],indirect=True,ids=['old-014','guarded-015'])
async def test_real_indexer_and_bridge_writes(database,monkeypatch,request):
    scope,engine=database
    await seed(scope,count=2)
    await processing.claim(1,'indexer','synthetic-source')
    first_done=asyncio.Event()
    bridge_started=asyncio.Event()
    errors=[]
    pid=[None]
    updates=[0]

    class Proxy:
        def __init__(self,session,kind): self.session,self.kind=session,kind
        def __getattr__(self,name): return getattr(self.session,name)
        async def execute(self,statement,*args,**kwargs):
            is_update=isinstance(statement,Update) and statement.table.name=='questions'
            if self.kind=='index' and is_update:
                updates[0]+=1
                if updates[0]==2:
                    await asyncio.wait_for(bridge_started.wait(),3)
                    async with engine.connect() as probe:
                        for _ in range(100):
                            waiting=(await probe.execute(text('SELECT wait_event_type FROM pg_stat_activity WHERE pid=:pid'),{'pid':pid[0]})).scalar()
                            if waiting=='Lock': break
                            await asyncio.sleep(.01)
                        else: raise AssertionError('Bridge never waited on the competing transaction')
            if self.kind=='bridge' and str(statement).startswith('UPDATE questions'):
                pid[0]=await self.session.scalar(text('SELECT pg_backend_pid()'))
                bridge_started.set()
            try:
                result=await self.session.execute(statement,*args,**kwargs)
            except DBAPIError as error:
                errors.append(getattr(error.orig,'sqlstate',None))
                raise
            if self.kind=='index' and is_update and updates[0]==1:
                first_done.set()
            return result

    @asynccontextmanager
    async def index_scope():
        async with scope() as session: yield Proxy(session,'index')
    @asynccontextmanager
    async def bridge_scope():
        async with scope() as session: yield Proxy(session,'bridge')
    monkeypatch.setattr(backfill,'session_scope',index_scope)
    monkeypatch.setattr(routes_bridge,'session_scope',bridge_scope)
    monkeypatch.setattr(routes_bridge,'generate_one',AsyncMock(return_value='synthetic-answer'))
    vectors=np.zeros((2,1024),dtype=np.float32); vectors[:,0]=1
    monkeypatch.setattr(backfill,'embed_texts',AsyncMock(return_value=vectors))

    async def generate():
        await asyncio.wait_for(first_done.wait(),3)
        return await routes_bridge.generate_answers(BridgeGenerateRequest(question_ids=[2],regenerate=True))
    results=await asyncio.wait_for(asyncio.gather(
        backfill.backfill_embeddings(force=True,post_ids=[1],batch_size=2,processing_owner='indexer'),
        generate(),return_exceptions=True),12)
    if request.node.callspec.params['database']:
        assert not errors and not any(isinstance(result,BaseException) for result in results)
        async with scope() as session:
            assert (await session.execute(text("SELECT answer_ai FROM questions WHERE id=2"))).scalar()=='synthetic-answer'
            assert results[0].embedded==2
    else:
        assert '40P01' in errors  # Same application functions, migration 014 only.


async def test_lease_renewal_and_rejected_claim_do_not_invalidate(database):
    scope,_=database
    await seed(scope)
    await processing.claim(1,'owner','source')
    async def revision():
        async with scope() as session:
            return (await session.execute(text('SELECT revision FROM il_read_revision'))).scalar_one()
    before=await revision()
    await processing.renew('owner')
    assert await processing.claim(1,'other','source') is None
    await processing.release('other')
    assert await revision()==before
    await processing.checkpoint(1,'owner','normalize')
    assert await revision()>before


async def test_generation_rolls_back_with_business_write(database):
    scope,_=database
    await seed(scope)
    async with scope() as session:
        before=(await session.execute(text('SELECT revision FROM il_read_revision'))).scalar_one()
    with pytest.raises(RuntimeError):
        async with scope() as session:
            await session.execute(text("UPDATE questions SET answer_ai='rollback' WHERE id=1"))
            raise RuntimeError('synthetic rollback')
    async with scope() as session:
        assert (await session.execute(text('SELECT revision FROM il_read_revision'))).scalar_one()==before
        assert (await session.execute(text('SELECT answer_ai FROM questions WHERE id=1'))).scalar() is None
