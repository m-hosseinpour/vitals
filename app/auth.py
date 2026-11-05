"""Password checking, session state and CSRF tokens."""

from __future__ import annotations

import hashlib
import hmac
import secrets
import time

from argon2 import PasswordHasher
from argon2.exceptions import InvalidHashError, VerificationError, VerifyMismatchError
from starlette.requests import Request

from .config import Settings

_hasher = PasswordHasher()

CSRF_SESSION_KEY = "csrf"
AUTH_SESSION_KEY = "auth"


def password_fingerprint(password_hash: str) -> str:
    """Ties a session to the current password hash, so rotating the password logs
    every existing session out without needing a server-side session store."""
    return hashlib.sha256(password_hash.encode("utf-8")).hexdigest()[:16]


def verify_password(settings: Settings, candidate: str) -> bool:
    # Argon2 cost is paid per attempt, so never feed it an unbounded string.
    if not candidate or len(candidate) > 256:
        return False
    try:
        return _hasher.verify(settings.password_hash, candidate)
    except (VerifyMismatchError, VerificationError, InvalidHashError):
        return False


def new_csrf_token() -> str:
    return secrets.token_urlsafe(32)


def csrf_token(request: Request) -> str:
    token = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(token, str) or len(token) < 32:
        token = new_csrf_token()
        request.session[CSRF_SESSION_KEY] = token
    return token


def csrf_valid(request: Request, submitted: str | None) -> bool:
    expected = request.session.get(CSRF_SESSION_KEY)
    if not isinstance(expected, str) or not isinstance(submitted, str):
        return False
    return hmac.compare_digest(expected, submitted)


def is_authenticated(request: Request, settings: Settings) -> bool:
    session = request.session
    if session.get(AUTH_SESSION_KEY) is not True:
        return False
    if session.get("pw") != password_fingerprint(settings.password_hash):
        session.clear()
        return False
    issued_at = session.get("iat")
    if (
        not isinstance(issued_at, int)
        or time.time() - issued_at > settings.session_seconds
    ):
        session.clear()
        return False
    return True


def start_session(request: Request, settings: Settings) -> None:
    """Rotate the session on login: a fresh id and a fresh CSRF token."""
    request.session.clear()
    request.session[AUTH_SESSION_KEY] = True
    request.session[CSRF_SESSION_KEY] = new_csrf_token()
    request.session["iat"] = int(time.time())
    request.session["pw"] = password_fingerprint(settings.password_hash)


def end_session(request: Request) -> None:
    request.session.clear()
