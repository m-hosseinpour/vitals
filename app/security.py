"""Response hardening and login throttling."""

from __future__ import annotations

import math
import time
from collections import OrderedDict, deque
from dataclasses import dataclass, field

from starlette.datastructures import MutableHeaders
from starlette.types import ASGIApp, Message, Receive, Scope, Send

# No inline scripts, styles, frames or third-party origins: the app ships its own
# CSS and JS, and its data only comes from this origin.
CONTENT_SECURITY_POLICY = (
    "default-src 'none'; script-src 'self'; style-src 'self'; img-src 'self'; "
    "font-src 'self'; connect-src 'self'; form-action 'self'; "
    "frame-ancestors 'none'; base-uri 'none'; manifest-src 'self'"
)

COMMON_HEADERS = {
    "Content-Security-Policy": CONTENT_SECURITY_POLICY,
    "X-Content-Type-Options": "nosniff",
    "X-Frame-Options": "DENY",
    "Referrer-Policy": "no-referrer",
    "Cross-Origin-Opener-Policy": "same-origin",
    "Cross-Origin-Resource-Policy": "same-origin",
    "Permissions-Policy": "camera=(), microphone=(), geolocation=(), payment=(), usb=()",
    "X-Robots-Tag": "noindex, nofollow, noarchive",
}


class SecurityHeadersMiddleware:
    """Adds the security headers to every response, static files included."""

    def __init__(self, app: ASGIApp, *, hsts: bool) -> None:
        self.app = app
        self.hsts = hsts

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        if scope["type"] != "http":
            await self.app(scope, receive, send)
            return

        is_static = str(scope.get("path", "")).startswith("/static/")

        async def send_wrapper(message: Message) -> None:
            if message["type"] == "http.response.start":
                headers = MutableHeaders(scope=message)
                for name, value in COMMON_HEADERS.items():
                    headers[name] = value
                if self.hsts:
                    headers["Strict-Transport-Security"] = (
                        "max-age=31536000; includeSubDomains"
                    )
                if is_static:
                    # Asset URLs carry a content hash, so a long cache is safe.
                    headers["Cache-Control"] = "public, max-age=86400"
                else:
                    headers["Cache-Control"] = "no-store"
            await send(message)

        await self.app(scope, receive, send_wrapper)


@dataclass
class _Attempts:
    failures: deque[float] = field(default_factory=deque)
    blocked_until: float = 0.0


class LoginThrottle:
    """A small in-process sliding window, keyed by client IP.

    One process serves this dashboard, so an in-memory limiter is enough; a restart
    clears it, which is acceptable for a single-user app.
    """

    def __init__(
        self,
        *,
        max_failures: int = 5,
        window_seconds: int = 600,
        block_seconds: int = 900,
        max_entries: int = 5000,
    ) -> None:
        self.max_failures = max_failures
        self.window = window_seconds
        self.block_seconds = block_seconds
        self.max_entries = max_entries
        self._entries: OrderedDict[str, _Attempts] = OrderedDict()

    def _entry(self, ip: str) -> _Attempts:
        entry = self._entries.get(ip)
        if entry is None:
            if len(self._entries) >= self.max_entries:
                self._entries.popitem(last=False)
            entry = _Attempts()
            self._entries[ip] = entry
        else:
            self._entries.move_to_end(ip)
        return entry

    def retry_after(self, ip: str) -> int:
        """Seconds the caller must wait, or 0 when an attempt may proceed."""
        entry = self._entries.get(ip)
        if entry is None:
            return 0
        now = time.monotonic()
        if entry.blocked_until > now:
            return max(1, math.ceil(entry.blocked_until - now))
        while entry.failures and now - entry.failures[0] > self.window:
            entry.failures.popleft()
        return 0

    def record_failure(self, ip: str) -> None:
        now = time.monotonic()
        entry = self._entry(ip)
        while entry.failures and now - entry.failures[0] > self.window:
            entry.failures.popleft()
        entry.failures.append(now)
        if len(entry.failures) >= self.max_failures:
            entry.blocked_until = now + self.block_seconds
            entry.failures.clear()

    def record_success(self, ip: str) -> None:
        self._entries.pop(ip, None)
