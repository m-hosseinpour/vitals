"""The bot's pulse: what the Bale crier last did, job by job.

The crier writes one line to its run log after every completed run, quiet runs
included. Reading that file is how the dashboard tells a dead timer from a quiet
day: the age of a row is the signal, not a threshold this app invents.

The file is read on every request. A missing file, a malformed line or a field of
the wrong type must never break the page, and nothing that was not actually read
may be shown as a healthy run.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path

# Fixed rows, in the order the owner reads them. The names are the producer names
# the crier records; `note` is matched by the ordinary run (no `--only`) instead.
ROWS = (
    ("note", "یادداشت روزانه"),
    ("credit", "اعتبار AvalAI"),
    ("disk", "فضای دیسک"),
    ("changedetection", "صفحه‌های تغییر"),
    ("news", "خبرنامه"),
)

CHIP_TEXT = {
    "never": "هرگز اجرا نشده",
    "failed": "ارسال ناموفق",
    "unbuilt": "چیزی ساخته نشد",
    "ok": "اجرا شد",
}

CHIP_TONE = {
    "never": "muted",
    "failed": "danger",
    "unbuilt": "warn",
    "ok": "ok",
}

NO_REASON = "بدون توضیح"


@dataclass(frozen=True)
class RunRecord:
    """One line of the crier's run log, reduced to what the card shows."""

    ts: datetime
    only: list[str] | None
    producers: list[str]
    sent: int
    failed: int
    errors: list[str]


@dataclass(frozen=True)
class PulseRow:
    name: str
    label: str
    record: RunRecord | None

    @property
    def state(self) -> str:
        if self.record is None:
            return "never"
        if self.record.failed > 0:
            return "failed"
        if not self.record.producers:
            return "unbuilt"
        return "ok"

    @property
    def chip_text(self) -> str:
        return CHIP_TEXT[self.state]

    @property
    def chip_tone(self) -> str:
        return CHIP_TONE[self.state]

    @property
    def count_text(self) -> str:
        if self.record is None:
            return "—"
        if self.record.sent == 0:
            return "بی‌صدا"
        return f"{self.record.sent} پیام"

    @property
    def error(self) -> str:
        """The first reason the sender gave, for the failed state only."""
        if self.state != "failed":
            return ""
        assert self.record is not None
        return self.record.errors[0] if self.record.errors else NO_REASON


@dataclass(frozen=True)
class Pulse:
    # "unconfigured" | "missing" | "error" | "ok"
    state: str
    rows: tuple[PulseRow, ...] = ()
    ignored: int = 0
    error: str = ""


def _timestamp(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    try:
        parsed = datetime.fromisoformat(value)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return parsed.replace(tzinfo=UTC)
    return parsed.astimezone(UTC)


def _names(value: object) -> list[str] | None:
    if not isinstance(value, list) or not all(isinstance(item, str) for item in value):
        return None
    return value


def _count(value: object) -> int | None:
    # bool is an int in Python; a `true` count is not a count.
    if isinstance(value, bool) or not isinstance(value, int) or value < 0:
        return None
    return value


def parse_line(line: str) -> RunRecord | None:
    """One line of the log, or ``None`` when it cannot be read as a run record."""
    try:
        raw = json.loads(line)
    except ValueError:
        return None
    if not isinstance(raw, dict):
        return None

    ts = _timestamp(raw.get("ts"))
    if ts is None:
        return None

    # A missing `only` is not read as null: that would let an unreadable line claim
    # the ordinary note run.
    if "only" not in raw:
        return None
    only = raw["only"]
    if only is not None:
        only = _names(only)
        if only is None:
            return None

    producers = _names(raw.get("producers"))
    if producers is None:
        return None

    sent = _count(raw.get("sent"))
    failed = _count(raw.get("failed"))
    if sent is None or failed is None:
        return None

    errors = _names(raw.get("errors", []))
    if errors is None:
        return None

    return RunRecord(
        ts=ts, only=only, producers=producers, sent=sent, failed=failed, errors=errors
    )


def _newest(records: list[RunRecord], match) -> RunRecord | None:
    newest: RunRecord | None = None
    for record in records:
        if match(record) and (newest is None or record.ts >= newest.ts):
            newest = record
    return newest


def _match_name(name: str):
    if name == "note":
        # The ordinary note run is the only run without `--only`. A deploy check is
        # also an ordinary-shaped run, but it is not the note job: ignore it.
        return lambda record: record.only is None and "smoke" not in record.producers
    return lambda record: name in record.producers or name in (record.only or [])


def build_rows(records: list[RunRecord]) -> tuple[PulseRow, ...]:
    return tuple(
        PulseRow(name=name, label=label, record=_newest(records, _match_name(name)))
        for name, label in ROWS
    )


def read_pulse(path: str) -> Pulse:
    if not path.strip():
        return Pulse(state="unconfigured")

    try:
        text = Path(path).read_text(encoding="utf-8")
    except FileNotFoundError:
        return Pulse(state="missing")
    except (OSError, UnicodeError) as exc:
        reason = getattr(exc, "strerror", None) or str(exc)
        return Pulse(
            state="error", error=f"خواندن فایل نبض ربات ممکن نشد: {reason}"
        )

    records: list[RunRecord] = []
    ignored = 0
    for line in text.splitlines():
        if not line.strip():
            continue
        record = parse_line(line)
        if record is None:
            ignored += 1
        else:
            records.append(record)

    return Pulse(state="ok", rows=build_rows(records), ignored=ignored)
