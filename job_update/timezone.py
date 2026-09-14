"""Europe/London helpers that work on hosts without an installed tzdata wheel."""

from __future__ import annotations

from calendar import monthcalendar
from datetime import date, datetime, timedelta, tzinfo
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError


class _UnitedKingdomFallback(tzinfo):
    """Small fallback for Windows Python installations without the IANA bundle.

    The UK rules used here are stable for the current operating model: GMT from
    the last Sunday in October to the last Sunday in March, BST otherwise.
    ``ZoneInfo`` remains preferred whenever available.
    """

    @staticmethod
    def _last_sunday(year: int, month: int) -> date:
        weeks = monthcalendar(year, month)
        for week in reversed(weeks):
            if week[6]:
                return date(year, month, week[6])
        raise ValueError(f"month has no Sunday: {year}-{month}")

    @classmethod
    def _is_bst(cls, value: date) -> bool:
        return cls._last_sunday(value.year, 3) < value < cls._last_sunday(value.year, 10)

    def utcoffset(self, dt: datetime | None) -> timedelta:
        if dt is None:
            return timedelta(0)
        return timedelta(hours=1 if self._is_bst(dt.date()) else 0)

    def dst(self, dt: datetime | None) -> timedelta:
        return self.utcoffset(dt)

    def tzname(self, dt: datetime | None) -> str:
        return "BST" if dt is not None and self._is_bst(dt.date()) else "GMT"


def london_timezone() -> tzinfo:
    try:
        return ZoneInfo("Europe/London")
    except ZoneInfoNotFoundError:
        return _UnitedKingdomFallback()


def london_now() -> datetime:
    return datetime.now(london_timezone())
