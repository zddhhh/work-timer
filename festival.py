"""2026 中秋限定：皮肤与日程只在节期内主动现身，过季自动让位。"""
from __future__ import annotations

from datetime import date, datetime

MIDAUTUMN_ID = "midautumn"
MIDAUTUMN_THEME_ID = "midautumn"
MIDAUTUMN_TITLE = "中秋"
MIDAUTUMN_DATE = "2026-09-25"
MIDAUTUMN_HOUR = 19
MIDAUTUMN_MINUTE = 0
SEASON_START = date(2026, 9, 1)
SEASON_END = date(2026, 9, 27)
DEFAULT_THEME_IDS = frozenset({"ghost", "auto"})
BONUS_PIN_IDS = frozenset({MIDAUTUMN_ID})


def _when(now: datetime | None) -> datetime:
    return now or datetime.now()


def in_season(now: datetime | None = None) -> bool:
    d = _when(now).date()
    return SEASON_START <= d <= SEASON_END


def past_season(now: datetime | None = None) -> bool:
    return _when(now).date() > SEASON_END
