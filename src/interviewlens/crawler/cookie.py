"""Parse a raw `Cookie:` header value into Playwright-compatible cookies."""
from __future__ import annotations

from typing import Iterable


def parse_cookie_header(raw: str, *, domain: str = ".nowcoder.com") -> list[dict]:
    """Convert "k1=v1; k2=v2" into Playwright cookie dicts.

    Notes:
    - Playwright requires either ``url`` or ``(domain, path)``. We use domain so
      the cookie applies to all paths under the host.
    - Empty pairs and malformed entries are silently skipped.
    """
    cookies: list[dict] = []
    if not raw:
        return cookies

    for chunk in raw.split(";"):
        chunk = chunk.strip()
        if not chunk or "=" not in chunk:
            continue
        name, _, value = chunk.partition("=")
        name = name.strip()
        value = value.strip()
        if not name:
            continue
        cookies.append(
            {
                "name": name,
                "value": value,
                "domain": domain,
                "path": "/",
                "httpOnly": False,
                "secure": True,
                "sameSite": "Lax",
            }
        )
    return cookies


def domains_for_host(host: str) -> Iterable[str]:
    """Return both the bare host and a leading-dot variant for cookie domain."""
    yield host
    if not host.startswith("."):
        yield "." + host
