import base64
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock

import numpy as np
import pytest
from starlette.requests import Request

from interviewlens.api import cache, routes_health, routes_search, routes_admin
from interviewlens.api import resource_guard as guard
from interviewlens.answerer import answerer
from interviewlens.config import settings
from interviewlens.tasks import celery_app


def request(model_ready=True):
    return Request({"type": "http", "app": SimpleNamespace(state=SimpleNamespace(embedding_ready=model_ready))})


@pytest.mark.parametrize("model,db,redis,expected", [(True,True,True,200),(False,True,True,503),(True,False,True,503),(True,True,False,503)])
async def test_readiness_checks_all_required_dependencies(monkeypatch, model, db, redis, expected):
    monkeypatch.setattr(routes_health, "database_ready", AsyncMock(return_value=db))
    monkeypatch.setattr(routes_health, "get_redis", lambda: SimpleNamespace(ping=AsyncMock(return_value=redis)))
    assert (await routes_health.ready(request(model))).status_code == expected
    assert await routes_health.live() == {"status": "alive"}


async def test_readiness_failure_is_redacted(monkeypatch):
    monkeypatch.setattr(routes_health, "database_ready", AsyncMock(side_effect=RuntimeError("synthetic-secret")))
    monkeypatch.setattr(routes_health, "get_redis", lambda: SimpleNamespace(ping=AsyncMock(return_value=True)))
    response = await routes_health.ready(request())
    assert response.status_code == 503 and b"synthetic-secret" not in response.body


async def test_stuck_inference_marks_not_ready(monkeypatch):
    monkeypatch.setattr(routes_health,"inference_healthy",lambda:False)
    assert (await routes_health.ready(request())).status_code == 503


@pytest.mark.parametrize("vector", [np.ones(3),np.zeros(1024),np.full(1024,np.nan),np.full(1024,np.inf),np.full(1024,1e35),np.ones(1024)])
async def test_bad_embedding_cache_is_deleted_and_misses(monkeypatch, vector):
    r=SimpleNamespace(get=AsyncMock(return_value=base64.b64encode(vector.astype(np.float32).tobytes())), delete=AsyncMock())
    monkeypatch.setattr(routes_search, "get_redis", lambda:r)
    assert await routes_search._embed_cache_get("synthetic") is None
    r.delete.assert_awaited_once_with("synthetic")


async def test_force_refresh_bypasses_old_answer_but_updates_cache(monkeypatch):
    old=AsyncMock(return_value={"answer":"old"})
    create=AsyncMock(return_value=SimpleNamespace(choices=[SimpleNamespace(message=SimpleNamespace(content="new"),finish_reason="stop")],usage=None))
    put=AsyncMock()
    monkeypatch.setattr(answerer,"cache_get",old)
    monkeypatch.setattr(answerer,"cache_set",put)
    monkeypatch.setattr(answerer,"get_langfuse",lambda:None)
    monkeypatch.setattr(answerer,"get_client",lambda:SimpleNamespace(chat=SimpleNamespace(completions=SimpleNamespace(create=create))))
    assert await answerer.generate_one(content="synthetic",category=None,use_cache=False)=="new"
    old.assert_not_awaited()
    create.assert_awaited_once()
    put.assert_awaited_once()


async def test_database_commit_invalidates_even_if_redis_invalidation_unavailable(monkeypatch):
    values={}
    revision=["epoch:1"]
    async def generation(): return revision[0]
    async def get(key): return values.get(key)
    async def put(key,value,**kwargs): values[key]=value
    redis=SimpleNamespace(get=get,set=put)
    monkeypatch.setattr(cache,"read_revision",generation)
    assert await cache.cache_json_get("key",redis_client=redis) is None
    await cache.cache_json_set("key",["old"],ttl_seconds=30,redis_client=redis)
    revision[0]="epoch:2"  # atomically committed in PostgreSQL, no Redis write
    await cache.invalidate_read_caches()
    assert await cache.cache_json_get("key",redis_client=redis) is None
    await cache.cache_json_set("key",["new"],ttl_seconds=30,redis_client=redis)
    assert await cache.cache_json_get("key",redis_client=redis)==["new"]


def test_jobs_uses_broker_database_and_priority_lists(monkeypatch):
    clients={}
    def client(url,**kwargs):
        obj=MagicMock()
        obj.llen.side_effect=lambda key: 2 if url.endswith('/1') else 0
        obj.scan_iter.return_value=[]
        clients[url]=obj
        return obj
    monkeypatch.setattr(settings,"redis_url","redis://synthetic/0")
    monkeypatch.setattr(settings,"celery_broker_url","redis://synthetic/1")
    monkeypatch.setattr(routes_admin.redis.Redis,"from_url",client)
    monkeypatch.setattr(celery_app.control,"inspect",lambda **kwargs:SimpleNamespace(active=lambda:{}))
    assert routes_admin.jobs().queues["celery"]==8
    assert clients[settings.redis_url].llen.call_count==0
    clients[settings.celery_broker_url].close.assert_called_once()


def test_backup_uses_configured_source_and_rejects_other_database(monkeypatch,tmp_path):
    import sys
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/"scripts"))
    import production_ops as ops
    calls=[]
    base=SimpleNamespace(configured_database="restore_active",container="a"*64,
        exec=lambda *args,**kwargs:calls.append(args),
        cp=lambda src,dst:Path(dst).write_bytes(b"synthetic-dump"))
    monkeypatch.setattr(ops,"counts",lambda base,db:{"database":db})
    with pytest.raises(ValueError,match="differs"):
        ops.backup(base,tmp_path/'wrong',"interviewlens")
    ops.backup(base,tmp_path/'valid',"restore_active")
    dump=next(item for item in calls if item[0]=='pg_dump')
    assert dump[dump.index('-d')+1]=="restore_active"
    metadata=json.loads(next((tmp_path/'valid').glob('*.json')).read_text())
    assert metadata['database']=="restore_active"


def test_retention_dry_run_then_preserves_verified_and_latest(monkeypatch,tmp_path):
    from pathlib import Path
    import os,time
    import hashlib
    from datetime import datetime,timezone
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'scripts'))
    import production_ops as ops
    for number in range(6):
        old=time.time()-(20+number)*86400
        stamp=datetime.fromtimestamp(old,timezone.utc).strftime('%Y%m%dT%H%M%SZ')
        dump=tmp_path/f'interviewlens-{stamp}-{number:06x}.dump'
        dump.write_bytes(b'synthetic')
        metadata={'restore_verified_at':datetime.now(timezone.utc).isoformat()} if number in (1,2,3,4) else {}
        metadata.update(database='active',file=dump.name,sha256=hashlib.sha256(b'synthetic').hexdigest(),
                        counts_stable=True,created_utc=datetime.fromtimestamp(old,timezone.utc).isoformat())
        dump.with_suffix('.json').write_text(json.dumps(metadata))
        os.utime(dump,(old,old))
    ops.retention(tmp_path.resolve())
    assert len(list(tmp_path.glob('*.dump')))==6
    ops.retention(tmp_path.resolve(),apply=True)
    assert {int(path.stem[-6:],16) for path in tmp_path.glob('*.dump')}=={0,1,2,3}


def test_retention_never_deletes_before_three_restore_drills(monkeypatch,tmp_path):
    from pathlib import Path
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1]/'scripts'))
    import production_ops as ops
    dump=tmp_path/'interviewlens-20250101T000000Z-000001.dump'
    dump.write_bytes(b'synthetic')
    dump.with_suffix('.json').write_text('{}')
    ops.retention(tmp_path.resolve(),apply=True)
    assert dump.exists()


async def test_ssr_and_proxy_charge_same_visitor_bucket_without_trusting_other_peers(monkeypatch):
    monkeypatch.setattr(settings,'trusted_search_proxy','caddy,web')
    monkeypatch.setattr(guard,'_proxy_refreshed',0)
    def addresses(name,port):
        return [(2,1,6,'',('172.22.0.2' if name=='caddy' else '172.22.0.3',0))]
    monkeypatch.setattr(guard.socket,'getaddrinfo',addresses)
    r=SimpleNamespace(eval=AsyncMock(return_value=[1,60]))
    monkeypatch.setattr(guard,'get_redis',lambda:r)
    def incoming(peer):
        return Request({'type':'http','path':'/companies','query_string':b'',
            'method':'GET','scheme':'http','server':('api',8000),'client':(peer,123),
            'headers':[(b'x-il-client-ip',b'203.0.113.15')]})
    await guard.check_rate(incoming('172.22.0.2'))
    proxy_key=r.eval.call_args.args[2]
    await guard.check_rate(incoming('172.22.0.3'))
    assert r.eval.call_args.args[2]==proxy_key
    await guard.check_rate(incoming('198.51.100.7'))
    assert r.eval.call_args.args[2]!=proxy_key
