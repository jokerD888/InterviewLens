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
    )}
    values.update(PUBLIC_DOMAIN=domain, ACME_EMAIL=email,
                  ADMIN_NETWORKS=" ".join(str(item) for item in checked),
                  APP_IMAGE=f"interviewlens-api:{release}", WEB_IMAGE=f"interviewlens-web:{release}")
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


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--domain", required=True)
    parser.add_argument("--email", required=True)
    parser.add_argument("--admin-network", action="append", required=True)
    parser.add_argument("--release", required=True)
    parser.add_argument("--directory", type=Path, default=Path(__file__).resolve().parents[1] / "deploy")
    args = parser.parse_args()
    create(args.directory, args.domain, args.email, args.admin_network, args.release)
