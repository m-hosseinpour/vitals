"""Display helpers used by the templates."""

from __future__ import annotations

import hashlib
from datetime import UTC, datetime
from pathlib import Path
from zoneinfo import ZoneInfo

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


def countdown(value: datetime | None) -> str:
    """Precise time left until a reset: hours and minutes, or days and hours."""
    if value is None:
        return "—"
    seconds = (value.astimezone(UTC) - datetime.now(UTC)).total_seconds()
    if seconds <= 0:
        return "همین حالا"
    if seconds < 86400:
        hours, minutes = divmod(int(seconds // 60), 60)
        if hours and minutes:
            return f"{hours} ساعت و {minutes} دقیقه"
        if hours:
            return f"{hours} ساعت"
        return f"{minutes} دقیقه" if minutes else "کمتر از یک دقیقه"
    days, hours = divmod(int(seconds // 3600), 24)
    return f"{days} روز و {hours} ساعت" if hours else f"{days} روز"


def short_countdown(value: datetime | None) -> str:
    """A one-line time-to-reset for the compact Go strip.

    The full phrase stays in the row's title, so the strip can show the countdown
    and the clock side by side without wrapping. Values keep Latin digits like the
    other data fields.
    """
    if value is None:
        return "—"
    seconds = (value.astimezone(UTC) - datetime.now(UTC)).total_seconds()
    if seconds <= 0:
        return "حالا"
    if seconds < 86400:
        hours, minutes = divmod(int(seconds // 60), 60)
        if hours:
            return f"{hours}:{minutes:02d}"
        return f"{minutes} دقیقه" if minutes else "کمتر از یک دقیقه"
    days, minutes = divmod(int(seconds // 60), 1440)
    hours, minutes = divmod(minutes, 60)
    # A day or two left is close enough that the hours still matter; a weekly or
    # monthly window only needs one decimal to stay compact and unambiguous.
    if days < 2:
        if hours:
            return f"{days} روز {hours}:{minutes:02d}"
        return f"{days} روز"
    text = f"{days + hours / 24 + minutes / 1440:.1f}".rstrip("0").rstrip(".")
    return f"{text} روز"


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
