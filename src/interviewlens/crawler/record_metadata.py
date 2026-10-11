"""Publication metadata shared by discovery, exports and date repair."""

from __future__ import annotations

import hashlib
import json
from datetime import UTC, datetime


def publication_ms(record: dict) -> int | None:
    # createTime is the discussion publication date; editTime/showTime are not.
    for body, field in (("momentData", "createdAt"), ("contentData", "createTime")):
        fields = record.get(body)
        if not isinstance(fields, dict):
            continue
        value = fields.get(field)
        if isinstance(value, bool):
            continue
        try:
            timestamp = int(value)
        except (ValueError, TypeError, OverflowError):
            continue
        if 946684800000 <= timestamp <= int(datetime.now(UTC).timestamp() * 1000) + 86400000:
            return timestamp
    return None


def publication_datetime(record: dict) -> datetime | None:
    timestamp = publication_ms(record)
    return datetime.fromtimestamp(timestamp / 1000, UTC) if timestamp else None


def page_fingerprint(records: list[dict]) -> str | None:
    """Order-independent identity set, unaffected by likes and other volatile fields."""
    if not records:
        return None
    from .tab_crawler import build_detail_url

    identities = [build_detail_url(record) for record in records]
    if any(identity is None for identity in identities):
        # Never call unrelated unidentifiable pages equal.
        return None
    return hashlib.sha256(json.dumps(sorted(set(identities))).encode()).hexdigest()
