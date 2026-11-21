"""Reading OpenCode Go subscription usage: the HTTP call, parsing, and cache.

OpenCode's own client reads Go usage from an undocumented internal endpoint with a
bearer key and an `x-opencode-org-id` workspace header. The response holds three
rolling windows, each reporting the percent *used* and when it resets.

Nothing here writes to the provider, the key never leaves the server, and a
response that cannot be read is an error rather than a zero.
"""

from __future__ import annotations

import asyncio
import hashlib
import json
import logging
import math
import time
from dataclasses import dataclass, replace
from datetime import UTC, datetime
from typing import Any
from urllib.parse import quote

import httpx

from .config import GoAccountConfig, Settings

logger = logging.getLogger("vitals.opencode_go")

# The windows in the order the console shows them. The key is the provider's
# field name; the label is what the dashboard prints.
WINDOWS = (
    ("rolling", "پنجره ۵ ساعته"),
    ("weekly", "هفتگی"),
    ("monthly", "ماهانه"),
)
ALLOWED_STATUS = {"ok", "rate-limited"}
WARN_PERCENT = 70.0
DANGER_PERCENT = 90.0


@dataclass(frozen=True)
class Meter:
    key: str
    label: str
    percent: float
    status: str
    resets_at: datetime

    @property
    def limited(self) -> bool:
        return self.status == "rate-limited"

    @property
    def remaining(self) -> float:
        """Quota left in the window, so the bar starts full and drains with use."""
        return 100.0 - self.percent

    @property
    def note_label(self) -> str:
        """The window name as it reads after «پنجرهٔ» in the note."""
        return "۵ ساعته" if self.key == "rolling" else self.label

    @property
    def tone(self) -> str:
        """A bar class suffix; the draining bar turns bad as the quota runs out."""
        if self.limited or self.percent >= DANGER_PERCENT:
            return "danger"
        if self.percent >= WARN_PERCENT:
            return "warn"
        return ""


@dataclass(frozen=True)
class GoUsage:
    slot: str
    label: str
    workspace_id: str
    configured: bool
    state: str
    meters: tuple[Meter, ...]
    missing: tuple[str, ...]
    error: str
    source: str
    fetched_at: datetime | None

    @property
    def usage_url(self) -> str:
        if not self.workspace_id:
            return ""
        return (
            "https://opencode.ai/console/"
            f"{quote(self.workspace_id, safe='')}/activity/overview"
        )

    @property
    def chip_text(self) -> str:
        if not self.configured:
            return "تنظیم نشده"
        return {
            "healthy": "سالم",
            "near": "نزدیک سقف",
            "limited": "محدودشده",
            "unsubscribed": "بدون اشتراک",
            "unreadable": "ناخوانا",
        }.get(self.state, "نامشخص")

    @property
    def chip_tone(self) -> str:
        if not self.configured:
            return "muted"
        return {
            "healthy": "ok",
            "near": "warn",
            "limited": "danger",
            "unsubscribed": "danger",
            "unreadable": "warn",
        }.get(self.state, "warn")

    @property
    def source_text(self) -> str:
        if not self.configured:
            return "تنظیم نشده"
        return {
            "live": "دریافت زنده از OpenCode",
            "cache": "از حافظهٔ موقت",
            "stale": "آخرین دریافت موفق",
            "none": "دریافت ناموفق",
        }.get(self.source, "دریافت ناموفق")

    @property
    def limit_note(self) -> str:
        """Name the window that is actually closest to stopping work."""
        if not self.meters:
            return ""
        limited = [meter for meter in self.meters if meter.limited]
        if limited:
            meter = max(limited, key=lambda item: item.percent)
            return f"پنجرهٔ {meter.note_label} محدود شده و تا بازنشانی باید صبر کرد."
        peak = max(self.meters, key=lambda item: item.percent)
        if peak.percent <= 0:
            return "هنوز از سهمیهٔ این حساب استفاده نشده است."
        return f"بیشترین مصرف در پنجرهٔ {peak.note_label} است: {peak.percent:.0f}٪."


class ParseError(ValueError):
    """The response did not have the shape the card can trust."""


class FetchError(Exception):
    """The provider could not be read. The message is safe to show to the user."""

    def __init__(self, message: str, *, state: str = "unreadable") -> None:
        super().__init__(message)
        self.state = state


# --- parsing -----------------------------------------------------------------


def _percent(value: Any) -> float:
    """Percent used must be a finite number inside 0..100.

    Strings are rejected rather than coerced: a changed response shape should be
    visible as unreadable, not silently turned into a number.
    """
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ParseError("percent is not a number")
    try:
        number = float(value)
    except OverflowError as exc:
        raise ParseError("percent is out of range") from exc
    if not math.isfinite(number) or not 0 <= number <= 100:
        raise ParseError("percent is out of range")
    return number


def _status(value: Any) -> str:
    if not isinstance(value, str) or value not in ALLOWED_STATUS:
        raise ParseError("status is not recognized")
    return value


def _timestamp(value: Any) -> datetime:
    if not isinstance(value, str) or not value:
        raise ParseError("resetsAt is missing")
    text = value[:-1] + "+00:00" if value.endswith("Z") else value
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError as exc:
        raise ParseError("resetsAt is not a timestamp") from exc
    if parsed.tzinfo is None or parsed.utcoffset() is None:
        raise ParseError("resetsAt has no timezone")
    return parsed


def parse_usage(payload: Any) -> tuple[Meter, ...]:
    """Validate the whole response and return the three windows in display order.

    All or nothing: a missing or malformed window makes the card unreadable rather
    than showing a partly invented gauge.
    """
    if not isinstance(payload, dict):
        raise ParseError("payload is not an object")
    usage = payload.get("usage")
    if not isinstance(usage, dict):
        raise ParseError("usage is not an object")

    meters: list[Meter] = []
    for key, label in WINDOWS:
        raw = usage.get(key)
        if not isinstance(raw, dict):
            raise ParseError(f"{key} is not an object")
        meters.append(
            Meter(
                key=key,
                label=label,
                percent=_percent(raw.get("percent")),
                status=_status(raw.get("status")),
                resets_at=_timestamp(raw.get("resetsAt")),
            )
        )
    return tuple(meters)


def _state(meters: tuple[Meter, ...]) -> str:
    if any(meter.limited for meter in meters):
        return "limited"
    peak = max(meter.percent for meter in meters)
    if peak >= DANGER_PERCENT:
        return "limited"
    if peak >= WARN_PERCENT:
        return "near"
    return "healthy"


def analyze(
    payload: Any,
    *,
    source: str,
    fetched_at: datetime | None,
    error: str = "",
) -> GoUsage:
    """Turn a provider payload into the rows the dashboard shows."""
    meters = parse_usage(payload)
    return GoUsage(
        slot="",
        label="",
        workspace_id="",
        configured=True,
        state=_state(meters),
        meters=meters,
        missing=(),
        error=error,
        source=source,
        fetched_at=fetched_at,
    )


def _with_identity(usage: GoUsage, account: GoAccountConfig) -> GoUsage:
    return replace(
        usage,
        slot=account.slot,
        label=account.label,
        workspace_id=account.workspace_id,
    )


def _unconfigured(account: GoAccountConfig) -> GoUsage:
    return GoUsage(
        slot=account.slot,
        label=account.label,
        workspace_id=account.workspace_id,
        configured=False,
        state="unconfigured",
        meters=(),
        missing=account.missing_env,
        error="",
        source="none",
        fetched_at=None,
    )


def _unavailable(
    account: GoAccountConfig,
    error: str,
    *,
    state: str = "unreadable",
    fetched_at: datetime | None = None,
) -> GoUsage:
    return GoUsage(
        slot=account.slot,
        label=account.label,
        workspace_id=account.workspace_id,
        configured=True,
        state=state,
        meters=(),
        missing=(),
        error=error,
        source="none",
        fetched_at=fetched_at,
    )


# --- fetching ----------------------------------------------------------------


@dataclass
class _CacheEntry:
    payload: dict[str, Any] | None
    fetched_at: datetime | None
    fetched_mono: float
    error: str = ""
    error_mono: float = 0.0
    error_state: str = "unreadable"


class GoUsageService:
    """Fetches both Go accounts concurrently, with its own in-memory cache.

    The cache keeps redraws off the provider, and a failed read is remembered for
    `VITALS_RETRY_AFTER`. A stale payload survives a failure and is labelled as the
    last successful read. A caller that asks for `live` data — the dashboard's
    refresh button — skips both waits and reads the endpoint now.
    """

    def __init__(self, settings: Settings) -> None:
        self._settings = settings
        self._client = httpx.AsyncClient(
            timeout=httpx.Timeout(settings.http_timeout, connect=5.0),
            follow_redirects=False,
            # Do not let an environment proxy silently receive the API keys.
            trust_env=False,
            headers={"Accept": "application/json", "User-Agent": "vitals/0.1"},
        )
        self._cache: dict[str, _CacheEntry] = {}
        self._locks: dict[str, asyncio.Lock] = {}
        self._accounts = (settings.go_personal, settings.go_company)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def summary(self, *, live: bool = False) -> tuple[GoUsage, ...]:
        return tuple(
            await asyncio.gather(
                *(self.get(account, live=live) for account in self._accounts)
            )
        )

    async def get(
        self, account: GoAccountConfig, *, live: bool = False
    ) -> GoUsage:
        if account.missing_env:
            return _unconfigured(account)

        # Key the lock and cache by a hash of both credentials, never by the key
        # itself, so the process does not keep it in a dictionary.
        digest = hashlib.sha256(
            f"{account.workspace_id}\0{account.key}".encode("utf-8")
        ).hexdigest()[:16]
        lock = self._locks.setdefault(digest, asyncio.Lock())

        async with lock:
            now_mono = time.monotonic()
            entry = self._cache.get(digest)
            # A live read is the user asking to retry now, so neither the TTL nor
            # the failure backoff applies. The lock still serializes it with any
            # other request for the same credentials.
            if entry is not None and not live:
                if entry.error:
                    # A remembered failure keeps the last good numbers, and once
                    # its backoff expires the provider is retried even if that
                    # payload is still inside the longer Go cache. Otherwise the
                    # warning would vanish while the read stayed broken.
                    if now_mono - entry.error_mono < self._settings.retry_after:
                        if entry.payload is not None:
                            return _with_identity(
                                analyze(
                                    entry.payload,
                                    source="stale",
                                    fetched_at=entry.fetched_at,
                                    error=entry.error,
                                ),
                                account,
                            )
                        return _unavailable(
                            account,
                            entry.error,
                            state=entry.error_state,
                            fetched_at=entry.fetched_at,
                        )
                elif (
                    entry.payload is not None
                    and now_mono - entry.fetched_mono < self._settings.go_cache_ttl
                ):
                    return _with_identity(
                        analyze(
                            entry.payload,
                            source="cache",
                            fetched_at=entry.fetched_at,
                        ),
                        account,
                    )

            try:
                payload = await self._fetch(account)
            except FetchError as exc:
                message = str(exc)
                previous = entry.payload if entry else None
                self._cache[digest] = _CacheEntry(
                    payload=previous,
                    fetched_at=(entry.fetched_at if entry else None),
                    fetched_mono=(entry.fetched_mono if entry else 0.0),
                    error=message,
                    error_mono=now_mono,
                    error_state=exc.state,
                )
                if previous is not None:
                    return _with_identity(
                        analyze(
                            previous,
                            source="stale",
                            fetched_at=entry.fetched_at,
                            error=message,
                        ),
                        account,
                    )
                return _unavailable(account, message, state=exc.state)

            fetched_at = datetime.now(UTC)
            try:
                usage = analyze(payload, source="live", fetched_at=fetched_at)
            except Exception as exc:
                # The response is untrusted: one unreadable account must degrade
                # to its own card, never take the whole dashboard down.
                if isinstance(exc, ParseError):
                    logger.warning(
                        "could not parse the OpenCode Go response for %s: %s",
                        account.slot,
                        exc,
                    )
                else:
                    logger.exception(
                        "could not parse the OpenCode Go response for %s", account.slot
                    )
                message = "پاسخ OpenCode قابل خواندن نبود."
                previous = entry.payload if entry else None
                self._cache[digest] = _CacheEntry(
                    payload=previous,
                    fetched_at=(entry.fetched_at if entry else None),
                    fetched_mono=(entry.fetched_mono if entry else 0.0),
                    error=message,
                    error_mono=now_mono,
                )
                if previous is not None:
                    return _with_identity(
                        analyze(
                            previous,
                            source="stale",
                            fetched_at=entry.fetched_at,
                            error=message,
                        ),
                        account,
                    )
                return _unavailable(account, message, state="unreadable")

            self._cache[digest] = _CacheEntry(
                payload=payload,
                fetched_at=fetched_at,
                fetched_mono=now_mono,
            )
            return _with_identity(usage, account)

    async def _fetch(self, account: GoAccountConfig) -> dict[str, Any]:
        try:
            response = await self._client.get(
                self._settings.go_endpoint,
                headers={
                    "Authorization": f"Bearer {account.key}",
                    "x-opencode-org-id": account.workspace_id,
                },
            )
        except httpx.TimeoutException as exc:
            raise FetchError("OpenCode در زمان مقرر پاسخ نداد.") from exc
        except httpx.InvalidURL as exc:
            logger.warning("OpenCode Go endpoint is not a valid URL")
            raise FetchError("آدرس OpenCode معتبر نیست.") from exc
        except httpx.HTTPError as exc:
            logger.warning("OpenCode Go request failed: %s", type(exc).__name__)
            raise FetchError("دسترسی به OpenCode برقرار نشد.") from exc

        if response.status_code == 401:
            raise FetchError("کلید رد شد (پاسخ 401).")
        if response.status_code == 403:
            raise FetchError(
                "این workspace اشتراک OpenCode Go ندارد یا شناسهٔ workspace "
                "با کلید هم‌خوان نیست.",
                state="unsubscribed",
            )
        if response.status_code >= 400:
            raise FetchError(f"OpenCode پاسخ {response.status_code} داد.")
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise FetchError("پاسخ OpenCode قابل خواندن نبود.") from exc
        if not isinstance(payload, dict):
            raise FetchError("پاسخ OpenCode شکل مورد انتظار را نداشت.")
        return payload
