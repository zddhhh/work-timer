"""节日限定：皮肤与不可删除日程只在节期内现身，过季自动删日程并让位。"""
from __future__ import annotations

from datetime import date, datetime

MIDAUTUMN_ID = "midautumn"
MIDAUTUMN_THEME_ID = "midautumn"
MIDAUTUMN_TITLE = "中秋"
MIDAUTUMN_DATE = "2026-09-25"
MIDAUTUMN_HOUR = 19
MIDAUTUMN_MINUTE = 0
MIDAUTUMN_SEASON_START = date(2026, 9, 1)
MIDAUTUMN_SEASON_END = date(2026, 9, 27)

NATIONAL_ID = "nationalday"
NATIONAL_THEME_ID = "nationalday"
NATIONAL_TITLE = "国庆"
NATIONAL_DATE = "2026-10-01"
NATIONAL_HOUR = 8
NATIONAL_MINUTE = 0
NATIONAL_SEASON_START = date(2026, 9, 28)
NATIONAL_SEASON_END = date(2026, 10, 8)

DEFAULT_THEME_IDS = frozenset({"ghost", "auto"})
BONUS_PIN_IDS = frozenset({MIDAUTUMN_ID, NATIONAL_ID})

# 兼容旧调用：默认指中秋
SEASON_START = MIDAUTUMN_SEASON_START
SEASON_END = MIDAUTUMN_SEASON_END


def _when(now: datetime | None) -> datetime:
    return now or datetime.now()


def midautumn_in_season(now: datetime | None = None) -> bool:
    d = _when(now).date()
    return MIDAUTUMN_SEASON_START <= d <= MIDAUTUMN_SEASON_END


def midautumn_past_season(now: datetime | None = None) -> bool:
    return _when(now).date() > MIDAUTUMN_SEASON_END


def national_in_season(now: datetime | None = None) -> bool:
    d = _when(now).date()
    return NATIONAL_SEASON_START <= d <= NATIONAL_SEASON_END


def national_past_season(now: datetime | None = None) -> bool:
    return _when(now).date() > NATIONAL_SEASON_END


def in_season(now: datetime | None = None) -> bool:
    return midautumn_in_season(now)


def past_season(now: datetime | None = None) -> bool:
    return midautumn_past_season(now)


def locked_title(sid: str) -> str | None:
    if sid == MIDAUTUMN_ID:
        return MIDAUTUMN_TITLE
    if sid == NATIONAL_ID:
        return NATIONAL_TITLE
    return None


def is_locked(sid: str) -> bool:
    return sid in BONUS_PIN_IDS
