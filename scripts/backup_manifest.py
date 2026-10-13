"""Validate generated backup pairs without trusting mutable sidecar mtimes."""
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
import hashlib
import json
from pathlib import Path
import re


def file_sha256(path: Path):
    digest = hashlib.sha256()
    with path.open('rb') as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b''):
            digest.update(chunk)
    return digest.hexdigest()


def timestamp(value: str):
    if not isinstance(value, str):
        raise ValueError('Backup timestamp required')
    if re.fullmatch(r'\d{8}T\d{6}Z-[0-9a-f]{6}', value):
        return datetime.strptime(value[:16], '%Y%m%dT%H%M%SZ').replace(tzinfo=timezone.utc)
    parsed = datetime.fromisoformat(value.replace('Z', '+00:00'))
    if parsed.tzinfo is None:
        raise ValueError('Backup timestamp must include a timezone')
    return parsed.astimezone(timezone.utc)


@dataclass(frozen=True)
class Backup:
    dump: Path
    database: str
    created: datetime
    verified: bool


def read_backup(dump: Path, *, verify_hash=True, now=None):
    sidecar = dump.with_suffix('.json')
    if dump.is_symlink() or sidecar.is_symlink() or not dump.is_file() or not sidecar.is_file():
        raise ValueError('A regular backup pair is required')
    if not re.fullmatch(r'interviewlens-\d{8}T\d{6}Z-[0-9a-f]{6}\.dump', dump.name):
        raise ValueError('Unrecognised generated backup')
    metadata = json.loads(sidecar.read_text(encoding='utf-8'))
    if not isinstance(metadata, dict):
        raise ValueError('Backup manifest must be an object')
    database = metadata.get('database')
    if not isinstance(database, str) or not re.fullmatch(r'[a-zA-Z_][a-zA-Z0-9_]{0,62}', database):
        raise ValueError('Backup source database required')
    if metadata.get('file') != dump.name or metadata.get('counts_stable') is not True:
        raise ValueError('Stable source and matching filename required')
    digest = metadata.get('sha256')
    if not isinstance(digest, str) or not re.fullmatch(r'[0-9a-f]{64}', digest):
        raise ValueError('Backup checksum required')
    size = dump.stat().st_size
    if size <= 0 or ('size_bytes' in metadata and metadata['size_bytes'] != size):
        raise ValueError('Backup size mismatch')
    current = now or datetime.now(timezone.utc)
    created = timestamp(metadata.get('created_utc'))
    if created.strftime('%Y%m%dT%H%M%SZ') != dump.name[len('interviewlens-'):len('interviewlens-')+16]:
        raise ValueError('Backup creation time differs from generated filename')
    if created > current + timedelta(minutes=5):
        raise ValueError('Backup creation time is in the future')
    verified = False
    if metadata.get('restore_verified_at'):
        restored = timestamp(metadata['restore_verified_at'])
        verified = created <= restored <= current + timedelta(minutes=5)
    if verify_hash and file_sha256(dump) != digest:
        raise ValueError('Backup checksum mismatch')
    return Backup(dump, database, created, verified)
