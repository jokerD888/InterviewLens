"""Safe Docker Compose backup/restore/release operations (Linux or Windows).

Never redirects binary pg_dump output through PowerShell. Restores always
create a NEW database; no --clean, overwrite, or volume deletion is supported.
Backup files are private; schedule 'backup' daily with your OS scheduler.
"""
from __future__ import annotations

import argparse
from datetime import datetime, timezone
import hashlib
import json
import os
from pathlib import Path
import re
import subprocess
import uuid
from private_files import private_directory, private_file


def invoke(command, **kwargs):
    result = subprocess.run(command, capture_output=True, **kwargs)
    if result.returncode:
        raise RuntimeError("Operation failed; command output withheld because it may include credentials")
    return result.stdout


def compose(root: Path):
    return ["docker", "compose", "--env-file", str(root / ".env.production"), "-f", str(root / "compose.production.yml")]


def file_sha256(path: Path):
    digest = hashlib.sha256()
    with path.open("rb") as stream:
        for chunk in iter(lambda: stream.read(1_048_576), b""):
            digest.update(chunk)
    return digest.hexdigest()


class Database:
    def __init__(self, root: Path, container: str | None = None, distro: str | None = None):
        self.docker = ["wsl", "-d", distro, "-u", "root", "--", "docker"] if distro else ["docker"]
        self.wsl = bool(distro)
        if container:
            if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}", container):
                raise ValueError("Invalid container name")
            value = invoke(self.docker + ["inspect", "--format", "{{.Id}}", container], text=True).strip()
        else:
            prefix = self.docker + compose(root)[1:]
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


def backup(base: Database, destination: Path):
    if destination in (Path(destination.anchor), Path.home(), Path.cwd(), Path(__file__).resolve().parents[1]):
        raise ValueError("Use a dedicated backup subdirectory")
    destination.mkdir(parents=True, mode=0o700, exist_ok=True)
    private_directory(destination)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + "-" + uuid.uuid4().hex[:6]
    target = destination / f"interviewlens-{stamp}.dump"
    remote = f"/tmp/interviewlens-{stamp}.dump"
    before = counts(base, "interviewlens")
    container = base.container
    if not re.fullmatch(r"[0-9a-f]{12,64}", container):
        raise RuntimeError("PostgreSQL service must be running")
    try:
        base.exec("pg_dump", "-U", "il", "-d", "interviewlens", "-Fc", "--no-owner", "--no-acl", "-f", remote)
        base.exec("pg_restore", "--list", remote)
        base.cp(f"{container}:{remote}", str(target))
    finally:
        base.exec("rm", "-f", remote)
    private_file(target)
    digest = file_sha256(target)
    after = counts(base, "interviewlens")
    manifest = {"created_utc": stamp, "file": target.name, "sha256": digest,
                "before": before, "after": after, "counts_stable": before == after}
    sidecar = target.with_suffix(".json")
    sidecar.touch(mode=0o600, exist_ok=False)
    private_file(sidecar)
    sidecar.write_text(json.dumps(manifest, indent=2), encoding="utf-8")
    print(json.dumps({"backup": str(target), "counts_stable": before == after}))


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
    finally:
        base.exec("rm", "-f", remote)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--deploy-root", type=Path, default=Path(__file__).resolve().parents[1] / "deploy")
    parser.add_argument("--container", help="Existing local PostgreSQL container (otherwise use Compose)")
    parser.add_argument("--wsl-distro", help="Run Docker inside this WSL distribution")
    commands = parser.add_subparsers(dest="action", required=True)
    b = commands.add_parser("backup")
    b.add_argument("--directory", type=Path, required=True)
    r = commands.add_parser("restore")
    r.add_argument("--file", type=Path, required=True)
    r.add_argument("--database", required=True)
    args = parser.parse_args()
    try:
        base = Database(args.deploy_root.resolve(), args.container, args.wsl_distro)
        if args.action == "backup":
            backup(base, args.directory.resolve())
        else:
            restore(base, args.file.resolve(), args.database)
    except Exception as error:
        print(f"Operation stopped ({type(error).__name__}); no credentials printed.")
        raise SystemExit(1) from None
