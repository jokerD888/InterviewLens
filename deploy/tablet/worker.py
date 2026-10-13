"""Native solo worker. Share the API's ONNX model instead of loading a copy."""
import sys

import httpx
import numpy as np

ROOT = '/opt/interviewlens-trial'
sys.path.insert(0, ROOT + '/app/src')
from interviewlens.config import settings
from interviewlens.embedding import bge_m3


class SharedModel:
    def encode(self, texts, **kwargs):
        result = []
        # Bound each RPC so public searches get opportunities between chunks.
        with httpx.Client(timeout=120) as client:
            for start in range(0, len(texts), 4):
                response = client.post(
                    'http://127.0.0.1:18800/internal/embed',
                    headers={'Authorization': 'Bearer ' + settings.admin_api_token},
                    json={'texts': texts[start:start + 4]},
                )
                response.raise_for_status()
                values = np.asarray(response.json()['vectors'], dtype=np.float32)
                if values.shape != (len(texts[start:start + 4]), settings.embedding_dim) or not np.isfinite(values).all():
                    raise ValueError('Invalid embedding RPC response')
                result.extend(values)
        return np.asarray(result, dtype=np.float32)


async def get_shared_model():
    return SharedModel()


bge_m3.get_model = get_shared_model
import interviewlens.embedding
interviewlens.embedding.get_model = get_shared_model
from interviewlens.tasks import celery_app

# An explicit diagnostics task: no crawl, paid LLM call, or database mutation.
@celery_app.task(name='il.tablet_readiness')
def tablet_readiness():
    from interviewlens.tasks.pipeline import _run_async
    from interviewlens.db import session_scope
    from sqlalchemy import text

    async def check():
        async with session_scope() as session:
            count = (await session.execute(text('SELECT count(*) FROM questions'))).scalar_one()
        vectors = await interviewlens.embedding.embed_texts(['Redis cache penetration'])
        return {'questions': count, 'embedding_dim': int(vectors.shape[1]), 'norm': float(np.linalg.norm(vectors[0]))}
    return _run_async(check())


if __name__ == '__main__':
    celery_app.worker_main(['worker', '--pool=solo', '--concurrency=1', '--hostname=tablet@%h', '--loglevel=INFO', '--without-gossip', '--without-mingle'])
