import pytest
from pydantic import ValidationError

from app.schemas import RegisterRequest


def payload(full_name):
    return RegisterRequest(
        email="employee@example.ru",
        code="123456",
        full_name=full_name,
        password="Strong-password-2026",
        department="Центр программ",
        phone="+7 999 000-00-00",
    )


@pytest.mark.parametrize("value", [
    "Петров Александр Игоревич",
    "Петров А. И.",
    "Петров Александр И.",
])
def test_registration_accepts_full_and_abbreviated_names(value):
    assert payload(value).full_name == value


@pytest.mark.parametrize("value", ["Петров", "123 456", "Петров @лександр"])
def test_registration_rejects_incomplete_or_invalid_names(value):
    with pytest.raises(ValidationError):
        payload(value)
