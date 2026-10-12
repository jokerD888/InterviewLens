"""One backend-enforced administrator credential for all privileged routes."""

from __future__ import annotations

import secrets

from fastapi import HTTPException, Request

from ..config import settings


def require_admin(request: Request):
    if not settings.admin_api_token or len(settings.admin_api_token) < 32:
        raise HTTPException(503, "Administrator credential is not configured")
    scheme, _, supplied = request.headers.get("authorization", "").partition(" ")
    if scheme.lower() != "bearer" or not secrets.compare_digest(
        supplied.encode(), settings.admin_api_token.encode()
    ):
        raise HTTPException(
            401, "Administrator login required", headers={"WWW-Authenticate": "Bearer"}
        )
