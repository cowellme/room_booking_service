"""Periodic booking lifecycle processing, independent of HTTP reads.

Each cycle owns its Session. A transaction-level PostgreSQL advisory lock
elects one worker per database, even with several Uvicorn processes. Existing
row locks/SKIP LOCKED protect decisions already in progress and make retries
idempotent. No separate scheduler, Redis or external service is required.
"""
import asyncio
import logging

from sqlalchemy import text

from ..database import SessionLocal
from .booking_lifecycle import expire_pending_requests

logger = logging.getLogger("room_booking.lifecycle")
# Two-key lock namespace is separate from one-key room/day advisory locks.
LIFECYCLE_LOCK_NAMESPACE = 671204
LIFECYCLE_LOCK_KEY = 1


def run_lifecycle_once(session_factory=None) -> dict:
    factory = session_factory or SessionLocal
    with factory() as db:
        try:
            if db.get_bind().dialect.name == "postgresql":
                db.execute(text("SET LOCAL lock_timeout = '5s'"))
                db.execute(text("SET LOCAL statement_timeout = '30s'"))
                acquired = db.execute(text("SELECT pg_try_advisory_xact_lock(:namespace, :key)"),
                                      {"namespace": LIFECYCLE_LOCK_NAMESPACE, "key": LIFECYCLE_LOCK_KEY}).scalar_one()
                if not acquired:
                    return {"ran": False, "expired": 0}
            expired = expire_pending_requests(db)
            return {"ran": True, "expired": expired}
        except Exception:
            db.rollback()
            raise


async def lifecycle_loop(stop: asyncio.Event, interval_seconds: float = 30, cycle=None) -> None:
    if interval_seconds <= 0:
        raise ValueError("Lifecycle interval must be positive")
    cycle = cycle or run_lifecycle_once
    # The cycle runs immediately at startup, and catches up after any downtime.
    while not stop.is_set():
        try:
            result = await asyncio.to_thread(cycle)
            logger.debug("Booking lifecycle cycle completed: %s", result)
        except Exception:
            # The failed transaction is rolled back by run_lifecycle_once. Do
            # not silently lose the worker after a temporary database outage.
            logger.exception("Booking lifecycle cycle failed; retrying after the interval")
        try:
            await asyncio.wait_for(stop.wait(), timeout=interval_seconds)
        except TimeoutError:
            pass
