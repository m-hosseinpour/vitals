"""The host's free disk space, read from the filesystem the dashboard runs on.

This is the same figure the Bale disk watcher alerts on (`shutil.disk_usage`), kept
here as a permanent view: a chat alert scrolls away, and the card still says how much
room is left. Nothing leaves the machine, and a read that fails is an error, never a
zero.
"""

from __future__ import annotations

import math
import shutil
from dataclasses import dataclass
from datetime import UTC, datetime

GIB = 1024**3


def _trim(text: str) -> str:
    return text.rstrip("0").rstrip(".") if "." in text else text


@dataclass(frozen=True)
class DiskStatus:
    path: str
    free: int | None
    total: int | None
    threshold: int
    error: str
    fetched_at: datetime | None

    @property
    def low(self) -> bool:
        return self.free is not None and self.free < self.threshold

    @property
    def used_percent(self) -> float | None:
        if self.free is None or not self.total:
            return None
        # Reserved blocks belong to neither the free space nor the owner's share,
        # so counting them as used matches what `df` reports and what the owner sees.
        # A network or FUSE mount can report inconsistent numbers; a gauge outside
        # 0..100 is a broken reading, not a bar to draw past its end.
        raw = (self.total - self.free) / self.total * 100
        return min(100.0, max(0.0, raw))

    @property
    def chip_text(self) -> str:
        if self.free is None:
            return "نامشخص"
        return "کمتر از آستانه" if self.low else "فضای کافی"

    @property
    def chip_tone(self) -> str:
        if self.free is None or self.low:
            return "warn"
        return "ok"

    @property
    def free_text(self) -> str:
        # Floored: 1.999 GiB must not read as "2" beside a 2 GiB threshold.
        value = math.floor(self.free / GIB * 100) / 100 if self.free is not None else None
        return "—" if value is None else _trim(f"{value:.2f}")

    @property
    def total_text(self) -> str:
        return "—" if self.total is None else _trim(f"{self.total / GIB:.1f}")

    @property
    def threshold_text(self) -> str:
        return _trim(f"{self.threshold / GIB:.2f}")


def read_disk(path: str, threshold_gib: float) -> DiskStatus:
    threshold = round(threshold_gib * GIB)
    try:
        usage = shutil.disk_usage(path)
    except OSError as exc:
        reason = exc.strerror or str(exc)
        return DiskStatus(
            path=path,
            free=None,
            total=None,
            threshold=threshold,
            error=f"خواندن فضای دیسک ممکن نشد: {reason}",
            fetched_at=None,
        )
    if usage.total <= 0:
        # Pseudo-filesystems (/proc, /sys, cgroups) report no size at all. A zero
        # gauge would read as a full disk; the honest answer is that there is no
        # space figure to show.
        return DiskStatus(
            path=path,
            free=None,
            total=None,
            threshold=threshold,
            error="این مسیر اندازهٔ فایل‌سیستم ندارد؛ فضای دیسک قابل خواندن نیست.",
            fetched_at=None,
        )
    return DiskStatus(
        path=path,
        free=usage.free,
        total=usage.total,
        threshold=threshold,
        error="",
        fetched_at=datetime.now(UTC),
    )
