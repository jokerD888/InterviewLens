import asyncio, os, sys
sys.path.insert(0,'/opt/interviewlens-trial/app/src')
from onnx_adapter import Model
from interviewlens.embedding import bge_m3

async def get_trial_model():
    if bge_m3._model is None:
        async with bge_m3._load_lock:
            if bge_m3._model is None:
                bge_m3._model=await asyncio.to_thread(Model)
    return bge_m3._model

# The trial uses the existing API, routing, authorization and search SQL.
bge_m3.get_model=get_trial_model
import interviewlens.embedding
interviewlens.embedding.get_model=get_trial_model
from interviewlens.db import session
from sqlalchemy.ext.asyncio import create_async_engine
from interviewlens.config import settings
session._engine=create_async_engine(settings.database_url,pool_size=3,max_overflow=0,pool_pre_ping=True,
    connect_args={'server_settings':{'statement_timeout':'15000','lock_timeout':'3000',
                                    'hnsw.ef_search':'200','hnsw.iterative_scan':'strict_order'}})
from interviewlens.api.app import app

from fastapi import Depends
from pydantic import BaseModel, Field
from interviewlens.api.security import require_admin

class EmbeddingRequest(BaseModel):
    texts: list[str] = Field(min_length=1, max_length=4)

@app.post('/internal/embed', dependencies=[Depends(require_admin)])
async def internal_embed(req: EmbeddingRequest):
    if any(len(t)>10000 for t in req.texts):
        from fastapi import HTTPException
        raise HTTPException(422, 'Embedding input too long')
    model=await get_trial_model()
    vectors=await asyncio.to_thread(model.encode,req.texts)
    return {'vectors':vectors.tolist()}

if __name__=='__main__':
    import uvicorn
    uvicorn.run(app,host='127.0.0.1',port=18800,workers=1,proxy_headers=False,
                limit_concurrency=16,timeout_keep_alive=5)
