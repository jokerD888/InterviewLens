"""Create private production config once; never overwrite existing secrets.

python scripts/init_production.py --domain interviews.example.com
    --email owner@example.com --admin-network YOUR.PUBLIC.IP/32 --release GIT_SHA
The generated files must stay private (gitignored); no credentials are printed.
"""
from __future__ import annotations

import argparse
import ipaddress
from pathlib import Path
import re
import secrets
from private_files import private_directory, private_file


def create(root: Path, domain: str, email: str, networks: list[str], release: str):
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9.-]{0,251}[a-zA-Z0-9]", domain):
        raise ValueError("Supply a DNS hostname without scheme, port or path")
    if not re.fullmatch(r"[^\s=@]+@[^\s=]+", email):
        raise ValueError("Invalid certificate contact email")
    if not re.fullmatch(r"[a-zA-Z0-9][a-zA-Z0-9_.-]{0,80}", release):
        raise ValueError("Invalid release tag")
    checked = [ipaddress.ip_network(item, strict=False) for item in networks]
    if not checked or any(item.prefixlen == 0 for item in checked):
        raise ValueError("Provide specific administrator IP/CIDR ranges, never the whole internet")
    targets = [root / ".env.production", root / "private/redis-state.acl", root / "private/redis-cache.acl"]
    if any(path.exists() for path in targets):
        raise FileExistsError("Production config exists; reuse it instead of rotating credentials on a live volume")
    root.mkdir(parents=True, exist_ok=True)
    private = root / "private"
    private.mkdir(mode=0o700, exist_ok=True)
    private_directory(private)
    values = {key: secrets.token_hex(32) for key in (
        "POSTGRES_PASSWORD", "REDIS_PASSWORD", "REDIS_CACHE_PASSWORD", "ADMIN_API_TOKEN",
        "LANGFUSE_DB_PASSWORD", "LANGFUSE_NEXTAUTH_SECRET", "LANGFUSE_SALT",
        "APP_DB_PASSWORD", "MIGRATION_DB_PASSWORD",
    )}
    values.update(PUBLIC_DOMAIN=domain, ACME_EMAIL=email,
                  ADMIN_NETWORKS=" ".join(str(item) for item in checked),
                  APP_IMAGE=f"interviewlens-api:{release}", WEB_IMAGE=f"interviewlens-web:{release}",
                  WORKER_IMAGE=f"interviewlens-worker:{release}", DATABASE_NAME="interviewlens")
    env = "\n".join(f'{key}="{value}"' for key, value in values.items()) + "\n"
    targets[0].touch(mode=0o600, exist_ok=False)
    private_file(targets[0])
    targets[0].write_text(env, encoding="utf-8")
    for path, password in zip(targets[1:], (values["REDIS_PASSWORD"], values["REDIS_CACHE_PASSWORD"]), strict=True):
        # Hash in ACL files; the authenticated URL exists only in private env.
        import hashlib
        path.touch(mode=0o644, exist_ok=False)
        path.write_text(f"user default on #{hashlib.sha256(password.encode()).hexdigest()} ~* &* +@all\n", encoding="ascii")
    # Parent directory protects hashed ACLs while the Redis UID can read mounts.
    print("Created private deployment configuration. Credentials were not printed.")


def upgrade(root: Path):
    """Add new role credentials without rotating existing secrets/volume auth."""
    path = root / ".env.production"
    source = path.read_text(encoding="utf-8-sig")
    values = dict(line.split("=", 1) for line in source.splitlines() if "=" in line and not line.lstrip().startswith("#"))
    additions = {}
    for key in ("APP_DB_PASSWORD", "MIGRATION_DB_PASSWORD"):
        if key not in values:
            additions[key] = secrets.token_hex(32)
    if "DATABASE_NAME" not in values:
        additions["DATABASE_NAME"] = "interviewlens"
    if "WORKER_IMAGE" not in values:
        release = values["APP_IMAGE"].strip('"').rsplit(":", 1)[1]
        additions["WORKER_IMAGE"] = f"interviewlens-worker:{release}"
    private_file(path)
    if additions:
        path.write_text(source.rstrip() + "\n" + "\n".join(f'{key}="{value}"' for key, value in additions.items()) + "\n", encoding="utf-8")
    print("Updated private configuration; existing credentials preserved.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain")
    parser.add_argument("--email")
    parser.add_argument("--admin-network", action="append")
    parser.add_argument("--release")
    parser.add_argument("--upgrade", action="store_true")
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "deploy")
    args = parser.parse_args()
    if args.upgrade:
        upgrade(args.directory)
    else:
        if not all((args.domain, args.email, args.admin_network, args.release)):
            parser.error("Creating config requires domain, email, admin-network and release")
        create(args.directory, args.domain, args.email, args.admin_network, args.release)
