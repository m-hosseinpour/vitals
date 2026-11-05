"""Reading AvalAI credit: the HTTP call, the response analysis, and a small cache.

The endpoint is `GET /user/v1/credit` with a bearer key. An account can hold
several packages of different kinds, and requests are paid from a package before
the main balance is touched, so the analysis keeps each package and reports the
sum of what is actually spendable now.

Nothing here writes to the provider, and the key never leaves the server.
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

import httpx

from .config import AccountConfig, Settings

logger = logging.getLogger("vitals.avalai")

TIERS = ("daily", "weekly", "other")
TIER_FA = {"daily": "روزانه", "weekly": "هفتگی", "other": "سایر"}
TIER_RANK = {"daily": 0, "weekly": 1, "other": 2}


@dataclass(frozen=True)
class Package:
    name: str
    tier: str
    remaining: float | None
    amount: float | None
    end_date: datetime | None
    expires_in: float | None
    spendable: bool
    percent: float | None


@dataclass(frozen=True)
class Tier:
    remaining: float
    count: int
    unread: int
    expires_in: float | None


@dataclass(frozen=True)
class AccountCredit:
    slot: str
    label: str
    configured: bool
    state: str
    active_tier: str | None
    main_balance: float | None
    packages: tuple[Package, ...]
    tiers: dict[str, Tier]
    warnings: tuple[str, ...]
    error: str
    source: str
    fetched_at: datetime | None
    total_remaining: float | None

    @property
    def packages_remaining(self) -> float:
        return sum(tier.remaining for tier in self.tiers.values())

    @property
    def chip_text(self) -> str:
        if not self.configured:
            return "تنظیم نشده"
        if self.state == "package" and self.active_tier:
            return f"بسته‌ی {TIER_FA[self.active_tier]} فعال"
        return {
            "main": "از اعتبار اصلی",
            "empty": "تمام‌شده",
            "unknown": "نامشخص",
        }.get(self.state, "نامشخص")

    @property
    def chip_tone(self) -> str:
        if not self.configured:
            return "muted"
        return {
            "package": "ok",
            "main": "ok",
            "empty": "danger",
            "unknown": "warn",
        }.get(self.state, "warn")

    @property
    def source_text(self) -> str:
        if not self.configured:
            return "کلید تنظیم نشده"
        return {
            "live": "دریافت زنده از AvalAI",
            "cache": "از حافظه‌ی موقت",
            "stale": "آخرین دریافت موفق",
            "none": "دریافت ناموفق",
        }.get(self.source, "دریافت ناموفق")


class FetchError(Exception):
    """The provider could not be read. The message is safe to show to the user."""


# --- parsing -----------------------------------------------------------------


def _num(value: Any) -> float | None:
    """Amounts arrive as strings inside packages and as numbers at the top level.

    Booleans, NaN and Infinity are not amounts: json.loads accepts bare NaN, and a
    balance of nan must not become a verdict.
    """
    if isinstance(value, bool):
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    return number if math.isfinite(number) else None


def _dt(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value))
    except ValueError:
        return None
    return parsed if parsed.tzinfo else parsed.replace(tzinfo=UTC)


def _tier(package: dict[str, Any]) -> str:
    template = str(package.get("template_id") or "")
    name = str(package.get("name") or "")
    if template.startswith("d-") or "روزانه" in name:
        return "daily"
    if template.startswith("w-") or "هفتگی" in name:
        return "weekly"
    return "other"


def analyze(
    payload: dict[str, Any],
    *,
    source: str,
    fetched_at: datetime | None,
    error: str = "",
) -> AccountCredit:
    """Turn a provider payload into the numbers the dashboard shows.

    Every container is checked before use: a changed response shape must produce
    "could not read it", never a traceback and never a verdict built on a field
    that was not actually read.
    """
    now = datetime.now(UTC)
    sources_raw = payload.get("credit_sources")
    sources = sources_raw if isinstance(sources_raw, dict) else {}
    packages_raw = sources.get("packages")
    malformed: list[str] = []
    if sources_raw is not None and not isinstance(sources_raw, dict):
        malformed.append("credit_sources")
    if "packages" in sources and not isinstance(packages_raw, list):
        malformed.append("credit_sources.packages")
    raw_packages = packages_raw if isinstance(packages_raw, list) else []

    packages: list[Package] = []
    for raw in raw_packages:
        if not isinstance(raw, dict):
            continue
        end = _dt(raw.get("end_date"))
        remaining = _num(raw.get("remaining_irt"))
        amount = _num(raw.get("amount_irt"))
        expires_in = (end - now).total_seconds() if end else None
        spendable = (remaining or 0) > 0 and (end is None or end > now)
        percent = None
        if remaining is not None and amount and amount > 0:
            percent = max(0.0, min(100.0, remaining / amount * 100))
        packages.append(
            Package(
                name=str(raw.get("name") or ""),
                tier=_tier(raw),
                remaining=remaining,
                amount=amount,
                end_date=end,
                expires_in=expires_in,
                spendable=spendable,
                percent=percent,
            )
        )
    packages.sort(
        key=lambda p: (
            TIER_RANK[p.tier],
            p.expires_in if p.expires_in is not None else float("inf"),
        )
    )

    tiers: dict[str, Tier] = {}
    for tier in TIERS:
        tier_packages = [p for p in packages if p.tier == tier]
        live = [p for p in tier_packages if p.spendable]
        tiers[tier] = Tier(
            remaining=sum(p.remaining or 0 for p in live),
            count=len(live),
            unread=sum(1 for p in tier_packages if p.remaining is None),
            expires_in=min(
                (p.expires_in for p in live if p.expires_in is not None),
                default=None,
            ),
        )

    active = next((tier for tier in TIERS if tiers[tier].remaining > 0), None)
    unread = sum(tiers[tier].unread for tier in TIERS)
    main = _num(payload.get("remaining_irt"))
    if active is not None:
        state = "package"
    elif main is None or unread or malformed:
        state = "unknown"
    elif main > 0:
        state = "main"
    else:
        state = "empty"

    warnings: list[str] = []
    if main is None:
        warnings.append("فیلد اعتبار اصلی در پاسخ AvalAI خوانده نشد؛ صفر فرض نشد.")
    if unread:
        warnings.append(f"مبلغ {unread} بسته خوانده نشد و در جمع نیامده است.")
    if malformed:
        warnings.append("این بخش‌های پاسخ خوانده نشد: " + "، ".join(malformed) + ".")
    grants = sources.get("grants")
    if isinstance(grants, list) and grants:
        warnings.append(
            f"این حساب {len(grants)} آیتم دیگر در grants دارد که نمایش داده نمی‌شود."
        )
    # Money paid for and never used deserves to be visible rather than hidden
    # behind the tier's "out" line.
    burned = [
        p
        for p in packages
        if not p.spendable and (p.remaining or 0) > 0 and (p.expires_in or 0) <= 0
    ]
    if burned:
        total = sum(p.remaining or 0 for p in burned)
        warnings.append(
            f"{len(burned)} بسته منقضی شده و {total:,.0f} تومان از آن استفاده نشده."
        )

    total_remaining: float | None
    if state == "unknown":
        total_remaining = None
    else:
        total_remaining = sum(t.remaining for t in tiers.values()) + (main or 0)

    return AccountCredit(
        slot="",
        label="",
        configured=True,
        state=state,
        active_tier=active,
        main_balance=main,
        packages=tuple(packages),
        tiers=tiers,
        warnings=tuple(warnings),
        error=error,
        source=source,
        fetched_at=fetched_at,
        total_remaining=total_remaining,
    )


def _with_identity(credit: AccountCredit, account: AccountConfig) -> AccountCredit:
    return replace(credit, slot=account.slot, label=account.label)


def _unconfigured(account: AccountConfig) -> AccountCredit:
    return AccountCredit(
        slot=account.slot,
        label=account.label,
        configured=False,
        state="unknown",
        active_tier=None,
        main_balance=None,
        packages=(),
        tiers={tier: Tier(0, 0, 0, None) for tier in TIERS},
        warnings=(),
        error="",
        source="none",
        fetched_at=None,
        total_remaining=None,
    )


def _unavailable(
    account: AccountConfig,
    error: str,
    source: str = "none",
    fetched_at: datetime | None = None,
) -> AccountCredit:
    return AccountCredit(
        slot=account.slot,
        label=account.label,
        configured=True,
        state="unknown",
        active_tier=None,
        main_balance=None,
        packages=(),
        tiers={tier: Tier(0, 0, 0, None) for tier in TIERS},
        warnings=(),
        error=error,
        source=source,
        fetched_at=fetched_at,
        total_remaining=None,
    )


# --- fetching ----------------------------------------------------------------


@dataclass
class _CacheEntry:
    payload: dict[str, Any] | None
    fetched_at: datetime | None
    fetched_mono: float
    error: str = ""
    error_mono: float = 0.0


class CreditService:
    """Fetches both accounts concurrently, with a short in-memory cache.

    The cache keeps the dashboard from hitting AvalAI on every redraw, and a failed
    fetch is remembered for a while so a broken provider is not retried in a tight
    loop. Cached data is always labelled as such in the UI.
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
        self._accounts = (settings.personal, settings.company)

    async def aclose(self) -> None:
        await self._client.aclose()

    async def summary(self) -> tuple[AccountCredit, ...]:
        return tuple(
            await asyncio.gather(*(self.get(account) for account in self._accounts))
        )

    async def get(self, account: AccountConfig) -> AccountCredit:
        if not account.key:
            return _unconfigured(account)

        # The same key may be configured for both slots; the hash keys the cache
        # without keeping the key itself in a dictionary.
        digest = hashlib.sha256(account.key.encode("utf-8")).hexdigest()[:16]
        lock = self._locks.setdefault(digest, asyncio.Lock())

        async with lock:
            now_mono = time.monotonic()
            entry = self._cache.get(digest)
            if entry is not None:
                if (
                    entry.payload is not None
                    and now_mono - entry.fetched_mono < self._settings.cache_ttl
                ):
                    return _with_identity(
                        analyze(
                            entry.payload,
                            source="cache",
                            fetched_at=entry.fetched_at,
                        ),
                        account,
                    )
                if (
                    entry.error
                    and now_mono - entry.error_mono < self._settings.retry_after
                ):
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
                        account, entry.error, source="none", fetched_at=entry.fetched_at
                    )

            try:
                payload = await self._fetch(account.key)
            except FetchError as exc:
                message = str(exc)
                self._cache[digest] = _CacheEntry(
                    payload=(entry.payload if entry else None),
                    fetched_at=(entry.fetched_at if entry else None),
                    fetched_mono=(entry.fetched_mono if entry else 0.0),
                    error=message,
                    error_mono=now_mono,
                )
                if entry is not None and entry.payload is not None:
                    return _with_identity(
                        analyze(
                            entry.payload,
                            source="stale",
                            fetched_at=entry.fetched_at,
                            error=message,
                        ),
                        account,
                    )
                return _unavailable(account, message)

            fetched_at = datetime.now(UTC)
            self._cache[digest] = _CacheEntry(
                payload=payload,
                fetched_at=fetched_at,
                fetched_mono=now_mono,
            )
            try:
                credit = analyze(payload, source="live", fetched_at=fetched_at)
            except Exception:
                logger.exception(
                    "could not analyze the AvalAI response for %s", account.slot
                )
                return _unavailable(
                    account, "پاسخ AvalAI قابل خواندن نبود.", source="none"
                )
            return _with_identity(credit, account)

    async def _fetch(self, key: str) -> dict[str, Any]:
        try:
            response = await self._client.get(
                self._settings.endpoint,
                headers={"Authorization": f"Bearer {key}"},
            )
        except httpx.TimeoutException as exc:
            raise FetchError("AvalAI در زمان مقرر پاسخ نداد.") from exc
        except httpx.HTTPError as exc:
            logger.warning("AvalAI request failed: %s", type(exc).__name__)
            raise FetchError("دسترسی به AvalAI برقرار نشد.") from exc

        if response.status_code in (401, 403):
            raise FetchError(f"کلید رد شد (پاسخ {response.status_code}).")
        if response.status_code >= 400:
            raise FetchError(f"AvalAI پاسخ {response.status_code} داد.")
        try:
            payload = response.json()
        except (json.JSONDecodeError, ValueError) as exc:
            raise FetchError("پاسخ AvalAI قابل خواندن نبود.") from exc
        if not isinstance(payload, dict):
            raise FetchError("پاسخ AvalAI شکل مورد انتظار را نداشت.")
        return payload
