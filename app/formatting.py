"""Display helpers used by the templates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

import jdatetime

TEHRAN = ZoneInfo("Asia/Tehran")
STATIC_DIR = Path(__file__).resolve().parent / "static"


def money(value: float | None) -> str:
    return "—" if value is None else f"{value:,.0f}"


def percent(value: float | None) -> str:
    return "—" if value is None else f"{value:.0f}٪"


def duration(seconds: float | None) -> str:
    """A rounded Persian duration: 2.99 hours reads as 3 ساعت, not 2."""
    if seconds is None:
        return "نامعلوم"
    if seconds <= 0:
        return "تمام‌شده"
    if seconds < 3600:
        return f"{round(seconds / 60)} دقیقه"
    if seconds < 86400:
        return f"{round(seconds / 3600)} ساعت"
    return f"{seconds / 86400:.1f} روز"


def ago(value: datetime | None) -> str:
    if value is None:
        return "—"
    seconds = (datetime.now(UTC) - value.astimezone(UTC)).total_seconds()
    if seconds < 60:
        return "همین حالا"
    if seconds < 3600:
        return f"{int(seconds // 60)} دقیقه پیش"
    if seconds < 86400:
        return f"{int(seconds // 3600)} ساعت پیش"
    return f"{seconds / 86400:.1f} روز پیش"


def jalali(value: datetime | None) -> str:
    if value is None:
        return "—"
    local = value.astimezone(TEHRAN)
    converted = jdatetime.datetime.fromgregorian(datetime=local)
    month = jdatetime.date.j_months_fa[converted.month - 1]
    return f"{converted.day} {month} {converted.year}"


def clock(value: datetime | None) -> str:
    if value is None:
        return "—"
    return value.astimezone(TEHRAN).strftime("%H:%M")


_VERSION_CACHE: dict[str, str] = {}


def asset(name: str) -> str:
    """A cache-busting URL for a file under static/."""
    version = _VERSION_CACHE.get(name)
    if version is None:
        try:
            version = hashlib.sha256((STATIC_DIR / name).read_bytes()).hexdigest()[:10]
        except OSError:
            version = "0"
        _VERSION_CACHE[name] = version
    return f"/static/{name}?v={version}"
