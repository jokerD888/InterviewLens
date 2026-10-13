from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path

import pytest


@pytest.fixture
def ops(monkeypatch):
    monkeypatch.syspath_prepend(str(Path(__file__).parents[1] / 'scripts'))
    import production_ops
    return production_ops


def pair(directory, number, *, days=0, database='active', verified=False, corrupt=False):
    created=datetime.now(timezone.utc)-timedelta(days=days)
    stamp=created.strftime('%Y%m%dT%H%M%SZ')+f'-{number:06x}'
    dump=directory/f'interviewlens-{stamp}.dump'
    dump.write_bytes(b'synthetic')
    metadata={'created_utc':stamp,'database':database,'file':dump.name,
              'sha256':hashlib.sha256(b'synthetic').hexdigest(),'counts_stable':True,
              'size_bytes':len(b'synthetic')}
    if verified:
        metadata['restore_verified_at']=datetime.now(timezone.utc).isoformat()
    dump.with_suffix('.json').write_text(json.dumps(metadata),encoding='utf-8')
    if corrupt:
        dump.write_bytes(b'corrupted')
    return dump


def monitor(monkeypatch, root):
    import production_check
    config={'services':{'api':{'environment':{'DATABASE_URL':'postgresql://dummy/active'}}}}
    monkeypatch.setattr(production_check,'invoke',lambda cmd,**kw:json.dumps(config) if 'config' in cmd else b'ready')
    return lambda: production_check.check(root,root)


def test_restore_does_not_make_old_backup_recent(ops,monkeypatch,tmp_path):
    pair(tmp_path,1,days=7,verified=True)
    with pytest.raises(RuntimeError,match='recent intact'):
        monitor(monkeypatch,tmp_path)()


def test_monitor_requires_matching_source_and_intact_dump(ops,monkeypatch,tmp_path,capsys):
    pair(tmp_path,1,database='other')
    pair(tmp_path,2,corrupt=True)
    check=monitor(monkeypatch,tmp_path)
    with pytest.raises(RuntimeError):
        check()
    pair(tmp_path,3)
    check()
    assert json.loads(capsys.readouterr().out)['recent_backup'] is True


def test_monitor_rejects_future_or_mismatched_manifest(ops,monkeypatch,tmp_path):
    pair(tmp_path,1,days=-2)
    dump=pair(tmp_path,2)
    metadata=json.loads(dump.with_suffix('.json').read_text())
    metadata['file']='different.dump'
    dump.with_suffix('.json').write_text(json.dumps(metadata))
    with pytest.raises(RuntimeError):
        monitor(monkeypatch,tmp_path)()


def test_retention_protects_each_database_independently(ops,tmp_path):
    backups=[pair(tmp_path,i,days=20+i,database='a',verified=True) for i in range(4)]
    sole=pair(tmp_path,4,days=30,database='b',verified=True)
    ops.retention(tmp_path.resolve(),apply=True)
    assert all(dump.exists() for dump in backups[:3])
    assert not backups[3].exists() and sole.exists()


def test_invalid_verified_dump_cannot_unlock_pruning(ops,tmp_path):
    dumps=[pair(tmp_path,i,days=20+i,verified=True,corrupt=i==2) for i in range(4)]
    # Three declared restores, but only two intact files: preserve every pair.
    metadata=json.loads(dumps[3].with_suffix('.json').read_text())
    metadata.pop('restore_verified_at')
    dumps[3].with_suffix('.json').write_text(json.dumps(metadata))
    ops.retention(tmp_path.resolve(),apply=True)
    assert all(dump.exists() for dump in dumps)


def test_retention_uses_creation_time_not_touched_files(ops,tmp_path):
    from os import utime
    dumps=[pair(tmp_path,i,days=20+i,verified=True) for i in range(4)]
    # Touch oldest dump and sidecar as a restore drill might. It stays oldest.
    utime(dumps[3],None)
    utime(dumps[3].with_suffix('.json'),None)
    ops.retention(tmp_path.resolve(),apply=True)
    assert not dumps[3].exists() and all(dump.exists() for dump in dumps[:3])
