import os
from dataclasses import replace

import pytest

os.environ.setdefault("DATABASE_URL", "postgresql+psycopg://test:test@localhost:5432/test")
os.environ.setdefault("SECRET_KEY", "test-secret-key-with-more-than-32-characters")
os.environ.setdefault("COOKIE_SECURE", "false")


@pytest.fixture(autouse=True)
def disable_automatic_worker_in_tests(monkeypatch):
    # HTTP tests may run the application lifespan. Never let them accidentally
    # connect the background worker to a real database; worker tests opt in
    # explicitly and inject an isolated session factory or a fake loop.
    from app import main
    monkeypatch.setattr(main, "settings", replace(main.settings, lifecycle_worker_enabled=False))


@pytest.fixture(autouse=True)
def booking_creation_uses_test_clock(monkeypatch):
    """Keep fixture creation timestamps consistent with the frozen business clock."""
    from datetime import timezone
    from sqlalchemy import event
    from app.models import Booking
    from app.services import bookings, operations
    from app.timeutils import _ZONE
    def timestamp(mapper, connection, target):
        if target.created_at is None:
            target.created_at = bookings.local_now().replace(tzinfo=_ZONE).astimezone(timezone.utc)
    monkeypatch.setattr(operations, 'utc_now', lambda: bookings.local_now().replace(tzinfo=_ZONE).astimezone(timezone.utc))
    event.listen(Booking, 'before_insert', timestamp)
    yield
    event.remove(Booking, 'before_insert', timestamp)
