"""Acquire the cache-generation lock before explicit business row locks.

Migration 015 acquires the same transaction advisory lock BEFORE DML. Reads
do not take it. Explicit row/post locks must acquire this first; otherwise a
writer can hold a business row while another writer holds the generation.
Keep model/network calls outside these short write transactions.
"""
from sqlalchemy import text


async def lock_write_generation(session):
    await session.execute(text("SELECT pg_advisory_xact_lock(73420, 0)"))
