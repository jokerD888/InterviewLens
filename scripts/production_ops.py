"""Safe Docker Compose backup/restore/release operations (Linux or Windows).

Never redirects binary pg_dump output through PowerShell. Restores always
create a NEW database; no --clean, overwrite, or volume deletion is supported.
Backup files are private; schedule 'backup' daily with your OS scheduler.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from private_files import private_directory, private_file
from urllib.parse import urlsplit
from backup_manifest import file_sha256, read_backup


def invoke(command, **kwargs):
    result = subprocess.run(command, capture_output=True, timeout=kwargs.pop("timeout", 900), **kwargs)
    if result.returncode:
        raise RuntimeError("Operation failed; command output withheld because it may include credentials")
    return result.stdout


def compose(root: Path):
    return ["docker", "compose", "--env-file", str(root / ".env.production"), "-f", str(root / "compose.production.yml")]


class Database:
    def __init__(self, root: Path, container: str | None = None, distro: str | None = None):
        self.docker = ["wsl", "-d", distro, "-u", "root", "--", "docker"] if distro else ["docker"]
        self.wsl = bool(distro)
        self.configured_database = None
        if container:
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}", container):
                raise ValueError("Invalid container name")
            value = invoke(self.docker + ["inspect", "--format", "{{.Id}}", container], text=True).strip()
        else:
            prefix = self.docker + compose(root)[1:]
            configuration = json.loads(invoke(prefix + ["config", "--format", "json"], text=True))
            url = configuration["services"]["api"]["environment"]["DATABASE_URL"]
            self.configured_database = urlsplit(url).path.lstrip("/")
            value = invoke(prefix + ["ps", "-q", "postgres"], text=True).strip()
        if not re.fullmatch(r"[0-9a-f]{12,64}", value):
            raise RuntimeError("PostgreSQL container must be running")
        self.container = value

    def exec(self, *args, **kwargs):
        return invoke(self.docker + ["exec", self.container, *args], **kwargs)

    def cp(self, source: str, target: str):
        if self.wsl:
            def host_path(value):
                if re.match(r"^[a-zA-Z]:[\\/]", value):
                    return f"/mnt/{value[0].lower()}/" + value[3:].replace("\\", "/")
                return value
            source, target = host_path(source), host_path(target)
        return invoke(self.docker + ["cp", source, target])


def counts(base: Database, database: str):
    sql = """SELECT json_build_object('posts',(SELECT count(*) FROM posts),
      'questions',(SELECT count(*) FROM questions),'vectors',(SELECT count(*) FROM questions WHERE embedding IS NOT NULL),
      'summaries',(SELECT count(*) FROM summaries),'profiles',(SELECT count(*) FROM post_position_profiles),
      'company_links',(SELECT count(*) FROM post_companies),'question_links',(SELECT count(*) FROM question_interviews),
      'posts_fingerprint',(SELECT md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY id)) FROM posts t),
      'questions_fingerprint',(SELECT md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY id)) FROM questions t),
      'profiles_fingerprint',(SELECT md5(string_agg(md5(row_to_json(t)::text),'' ORDER BY post_id,ordinal)) FROM post_position_profiles t))"""
    raw = base.exec("psql", "-U", "il", "-d", database, "-XAt", "-c", sql, text=True)
    return json.loads(raw.strip())


def backup(base: Database, destination: Path, database: str):
    if not re.fullmatch(r"[a-zA-Z_][a-zA-Z0-9_]{0,62}", database):
        raise ValueError("Invalid backup database")
    if base.configured_database and database != base.configured_database:
        raise ValueError("Backup database differs from the application target")
    if destination in (Path(destination.anchor), Path.home(), Path.cwd(), Path(__file__).resolve().parents[1]):
        raise ValueError("Use a dedicated backup subdirectory")
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    private_directory(destination)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    target = destination / f"interviewlens-{stamp}.dump"
    remote = f"/tmp/interviewlens-{stamp}.dump"
    before = counts(base, database)
    container = base.container
    if not re.fullmatch(r"[0-9a-f]{12,64}", container):
        raise RuntimeError("PostgreSQL service must be running")
    try:
        base.exec("pg_dump", "-U", "il", "-d", database, "-Fc", "--no-owner", "--no-acl", "-f", remote)
        base.exec("pg_restore", "--list", remote)
        base.cp(f"{container}:{remote}", str(target))
    finally:
        base.exec("rm", "-f", remote)
    private_file(target)
    digest = file_sha256(target)
    after = counts(base, database)
    manifest = {"created_utc": stamp, "file": target.name, "sha256": digest,
                "database": database, "size_bytes": target.stat().st_size,
                "before": before, "after": after, "counts_stable": before == after}
    sidecar = target.with_suffix(".json")
    sidecar.touch(mode=0o600, exist_ok=False)
    private_file(sidecar)
    sidecar.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(target), "counts_stable": before == after}))
    if before != after:
        raise RuntimeError("Backup retained but verification failed: pause writes and retry")


def restore(base: Database, source: Path, database: str):
    if not re.fullmatch(r"restore_[a-z0-9_]{1,48}", database):
        raise ValueError("Restore database must have a NEW restore_... name")
    metadata = json.loads(source.with_suffix(".json").read_text(encoding="utf-8"))
    if file_sha256(source) != metadata["sha256"]:
        raise ValueError("Backup checksum mismatch")
    # createdb refuses to overwrite any existing database (including prior drills).
    base.exec("createdb", "-U", "il", database)
    container = base.container
    remote = f"/tmp/{database}-{uuid.uuid4().hex}.dump"
    try:
        base.cp(str(source), f"{container}:{remote}")
        base.exec("pg_restore", "-U", "il", "-d", database, "--exit-on-error", "--single-transaction", "--no-owner", "--no-acl", remote)
        restored = counts(base, database)
        if metadata["counts_stable"] and restored != metadata["after"]:
            raise RuntimeError("Restored counts do not match stable source snapshot")
        print(json.dumps({"restored_database": database, "counts": restored, "verified": metadata["counts_stable"]}))
        if metadata["counts_stable"]:
            metadata["restore_verified_at"] = datetime.now(timezone.utc).isoformat()
            private_file(source.with_suffix(".json"))
            source.with_suffix(".json").write_text(json.dumps(metadata, indent=2), encoding="utf-8")
    finally:
        base.exec("rm", "-f", remote)


def retention(directory: Path, keep_days: int = 14, apply: bool = False):
    """Keep the newest and 3 intact, restored dumps per source database.

    Never remove symlinks, paths outside the dedicated directory, recent files,
    or the newest backup. Each database requires 3 intact restore drills first.
    """
    if keep_days < 14 or directory in (Path(directory.anchor), Path.home(), Path.cwd()):
        raise ValueError("Dedicated directory and at least 14 days are required")
    entries=[]
    skipped=0
    for dump in directory.glob('interviewlens-*.dump'):
        sidecar=dump.with_suffix('.json')
        if dump.is_symlink() or sidecar.is_symlink() or not sidecar.is_file():
            continue
        if dump.resolve().parent != directory or sidecar.resolve().parent != directory:
            raise ValueError('Backup path escapes the dedicated directory')
        if not re.fullmatch(r'interviewlens-\d{8}T\d{6}Z-[0-9a-f]{6}\.dump',dump.name):
            continue
        try:
            entry=read_backup(dump)
        except (ValueError,OSError):
            skipped+=1
            continue
        entries.append(entry)
    groups={}
    for entry in entries:
        groups.setdefault(entry.database,[]).append(entry)
    cutoff=datetime.now(timezone.utc).timestamp()-keep_days*86400
    candidates=[]
    for group in groups.values():
        group.sort(key=lambda entry:entry.created,reverse=True)
        verified=[entry for entry in group if entry.verified]
        if len(verified)<3:
            continue
        protected={entry.dump for entry in verified[:3]}
        protected.add(group[0].dump)
        candidates.extend(entry for entry in group if entry.created.timestamp()<cutoff and entry.dump not in protected)
    for entry in candidates:
        if apply:
            # Resolved paths were verified above; no recursive deletion.
            entry.dump.unlink(); entry.dump.with_suffix('.json').unlink()
    print(json.dumps({'candidates':len(candidates),'pruned':len(candidates) if apply else 0,
                      'dry_run':not apply,'databases':len(groups),'skipped_unverified_pairs':skipped}))


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy-root", type=Path, default=Path(__file__).resolve().parents[1] / "deploy")
    parser.add_argument("--container", help="Existing local PostgreSQL container (otherwise use Compose)")
    parser.add_argument("--wsl-distro", help="Run Docker inside this WSL distribution")
    commands = parser.add_subparsers(dest="action", required=True)
    b = commands.add_parser("backup")
    b.add_argument("--directory", type=Path, required=True)
    b.add_argument("--database", help="Defaults to the configured API target; required with --container")
    r = commands.add_parser("restore")
    r.add_argument("--file", type=Path, required=True)
    r.add_argument("--database", required=True)
    p = commands.add_parser("prune")
    p.add_argument("--directory", type=Path, required=True)
    p.add_argument("--keep-days", type=int, default=14)
    p.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        if args.action == 'prune':
            retention(args.directory.resolve(),args.keep_days,args.apply)
            raise SystemExit(0)
        base = Database(args.deploy_root.resolve(), args.container, args.wsl_distro)
        if args.action == "backup":
            database = args.database or base.configured_database
            if not database:
                raise ValueError("Explicit --database is required with --container")
            backup(base, args.directory.resolve(), database)
        else:
            restore(base, args.file.resolve(), args.database)
    except Exception as error:
        print(f"Operation stopped ({type(error).__name__}); no credentials printed.")
        raise SystemExit(1) from None
