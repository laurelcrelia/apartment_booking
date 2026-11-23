"""Date handling shared by the services.

Date ranges are half-open: [check_in, check_out). A booking checking out on
the same day another checks in does not overlap with it.
"""
from __future__ import annotations

from datetime import date

from .errors import BookingError


def parse_date(value: str) -> date:
    try:
        return date.fromisoformat(value)
    except (TypeError, ValueError):
        raise BookingError(f"Invalid date '{value}', expected YYYY-MM-DD") from None


def parse_range(check_in: str, check_out: str) -> tuple[date, date]:
    d_in, d_out = parse_date(check_in), parse_date(check_out)
    validate_range(d_in, d_out)
    return d_in, d_out


def validate_range(check_in: date, check_out: date) -> None:
    if check_out <= check_in:
        raise BookingError("Check-out date must be after check-in date")
