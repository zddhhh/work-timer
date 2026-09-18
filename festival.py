"""节日限定：皮肤与不可删除日程只在节期内现身，过季自动删日程并让位。

日期按年查表（农历节日没法算，只能列）；表里没有的年份视为「今年没有这个节」，
宁可不上也不要上错日子。国庆固定 10-01，节期 09-28 ~ 10-08。
"""
from __future__ import annotations

from datetime import date, datetime, timedelta

MIDAUTUMN_ID = "midautumn"
MIDAUTUMN_THEME_ID = "midautumn"
MIDAUTUMN_TITLE = "中秋"
MIDAUTUMN_HOUR = 19
MIDAUTUMN_MINUTE = 0
# 农历八月十五对应公历（来源：万年历）；新增年份往这里加一行即可
_MIDAUTUMN_BY_YEAR: dict[int, date] = {
    2025: date(2025, 10, 6),
    2026: date(2026, 9, 25),
    2027: date(2027, 9, 15),
    2028: date(2028, 10, 3),
    2029: date(2029, 9, 22),
    2030: date(2030, 9, 12),
    2031: date(2031, 10, 1),
    2032: date(2032, 9, 19),
}
_MIDAUTUMN_LEAD_DAYS = 24  # 节前多少天开始进节期（2026: 09-01）
_MIDAUTUMN_TAIL_DAYS = 2  # 节后保留几天（2026: 09-27）

NATIONAL_ID = "nationalday"
NATIONAL_THEME_ID = "nationalday"
NATIONAL_TITLE = "国庆"
NATIONAL_HOUR = 8
NATIONAL_MINUTE = 0
_NATIONAL_LEAD_DAYS = 3  # 09-28
_NATIONAL_TAIL_DAYS = 7  # 10-08

DEFAULT_THEME_IDS = frozenset({"ghost"})
BONUS_PIN_IDS = frozenset({MIDAUTUMN_ID, NATIONAL_ID})

# 节日流程里写进 cfg 的易失键（过季时统一清掉，来年才会重新触发一次自动换皮）
STATE_KEY_SUFFIXES = ("_theme_offered", "_theme_auto", "_unpinned", "_kinetic_done", "_dismissed")


def _when(now: datetime | None) -> datetime:
    return now or datetime.now()


def _iso(d: date) -> str:
    return d.strftime("%Y-%m-%d")


# ---------- 中秋 ----------


def midautumn_day(year: int) -> date | None:
    return _MIDAUTUMN_BY_YEAR.get(int(year))


def midautumn_season(year: int) -> tuple[date, date] | None:
    d = midautumn_day(year)
    if d is None:
        return None
    return d - timedelta(days=_MIDAUTUMN_LEAD_DAYS), d + timedelta(days=_MIDAUTUMN_TAIL_DAYS)


def midautumn_date(now: datetime | None = None) -> str:
    """今年中秋的 YYYY-MM-DD；查不到返回空串。"""
    d = midautumn_day(_when(now).year)
    return _iso(d) if d else ""


def midautumn_in_season(now: datetime | None = None) -> bool:
    today = _when(now).date()
    season = midautumn_season(today.year)
    return bool(season) and season[0] <= today <= season[1]


def midautumn_past_season(now: datetime | None = None) -> bool:
    """节期之外一律视为「过季」：跨年残留的日程/皮肤也要清。"""
    return not midautumn_in_season(now)


# ---------- 国庆 ----------


def national_day(year: int) -> date:
    return date(int(year), 10, 1)


def national_season(year: int) -> tuple[date, date]:
    d = national_day(year)
    return d - timedelta(days=_NATIONAL_LEAD_DAYS), d + timedelta(days=_NATIONAL_TAIL_DAYS)


def national_date(now: datetime | None = None) -> str:
    return _iso(national_day(_when(now).year))


def national_in_season(now: datetime | None = None) -> bool:
    today = _when(now).date()
    a, b = national_season(today.year)
    return a <= today <= b


def national_past_season(now: datetime | None = None) -> bool:
    return not national_in_season(now)


# ---------- 通用 ----------


def locked_title(sid: str) -> str | None:
    if sid == MIDAUTUMN_ID:
        return MIDAUTUMN_TITLE
    if sid == NATIONAL_ID:
        return NATIONAL_TITLE
    return None


def is_locked(sid: str) -> bool:
    return sid in BONUS_PIN_IDS


def clear_state(cfg: dict, sid: str) -> bool:
    """过季清理该节日写进 cfg 的所有状态键；返回是否有改动。"""
    changed = False
    for suf in STATE_KEY_SUFFIXES:
        if cfg.pop(f"{sid}{suf}", None) is not None:
            changed = True
    if cfg.pop(f"theme_before_{sid}", None) is not None:
        changed = True
    return changed


# 兼容旧引用（2026 年常量）；新代码请用 *_date()/*_season()
MIDAUTUMN_DATE = midautumn_date(datetime(2026, 1, 1))
NATIONAL_DATE = national_date(datetime(2026, 1, 1))
MIDAUTUMN_SEASON_START, MIDAUTUMN_SEASON_END = midautumn_season(2026)  # type: ignore[misc]
NATIONAL_SEASON_START, NATIONAL_SEASON_END = national_season(2026)
