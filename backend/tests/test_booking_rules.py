from datetime import date, timedelta, time
import pytest
from fastapi import HTTPException
from app.services.bookings import validate_booking_window
def test_valid_window():
    validate_booking_window(date.today() + timedelta(days=1), time(9), time(10, 30))
@pytest.mark.parametrize("start,end", [(time(7,30), time(9)), (time(21), time(22,30)), (time(10,15), time(11)), (time(10), time(10))])
def test_invalid_windows(start, end):
    with pytest.raises(HTTPException): validate_booking_window(date.today() + timedelta(days=1), start, end)
def test_past_date():
    with pytest.raises(HTTPException): validate_booking_window(date.today() - timedelta(days=1), time(10), time(11))
