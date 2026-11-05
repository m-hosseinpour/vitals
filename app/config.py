"""Configuration, loaded once from the environment (and the project's .env file)."""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path

from dotenv import load_dotenv

BASE_DIR = Path(__file__).resolve().parent.parent
ENV_FILE = BASE_DIR / ".env"

# Existing environment variables win: deployment sets them in the unit, and the
# .env file is what a local run reads. Neither should silently override the other.
load_dotenv(ENV_FILE, override=False)

DEFAULT_ENDPOINT = "https://api.avalai.ir/user/v1/credit"


class ConfigError(RuntimeError):
    """A required setting is missing or malformed."""


def _text(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _bool(name: str, default: bool) -> bool:
    raw = _text(name)
    if not raw:
        return default
    lowered = raw.lower()
    if lowered in {"1", "true", "yes", "on"}:
        return True
    if lowered in {"0", "false", "no", "off"}:
        return False
    raise ConfigError(f"{name} must be true or false, got {raw!r}")


def _int(name: str, default: int, *, low: int, high: int) -> int:
    raw = _text(name)
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be an integer, got {raw!r}") from exc
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")
    return value


def _float(name: str, default: float, *, low: float, high: float) -> float:
    raw = _text(name)
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as exc:
        raise ConfigError(f"{name} must be a number, got {raw!r}") from exc
    if not low <= value <= high:
        raise ConfigError(f"{name} must be between {low} and {high}, got {value}")
    return value


@dataclass(frozen=True)
class AccountConfig:
    slot: str
    key: str
    label: str


@dataclass(frozen=True)
class Settings:
    secret_key: str
    password_hash: str
    allowed_hosts: tuple[str, ...]
    cookie_secure: bool
    session_hours: int
    endpoint: str
    cache_ttl: int
    retry_after: int
    http_timeout: float
    personal: AccountConfig
    company: AccountConfig

    @property
    def session_seconds(self) -> int:
        return self.session_hours * 3600


def load_settings() -> Settings:
    """Read and validate every setting. Raises ConfigError with a readable message."""
    secret = _text("VITALS_SECRET_KEY")
    if len(secret) < 32:
        raise ConfigError(
            "VITALS_SECRET_KEY is missing or shorter than 32 characters. "
            "Generate one with: python -c 'import secrets; print(secrets.token_urlsafe(48))'"
        )

    password_hash = _text("VITALS_PASSWORD_HASH")
    if not password_hash.startswith("$argon2"):
        raise ConfigError(
            "VITALS_PASSWORD_HASH is missing or is not an Argon2 hash. "
            "Run: uv run python scripts/set_password.py"
        )

    hosts = tuple(
        h.strip() for h in _text("VITALS_ALLOWED_HOSTS").split(",") if h.strip()
    )
    if not hosts:
        hosts = ("vitals.m-hosseinpour.ir", "localhost", "127.0.0.1")

    endpoint = _text("AVALAI_CREDIT_ENDPOINT", DEFAULT_ENDPOINT)
    if not endpoint.startswith("https://"):
        raise ConfigError("AVALAI_CREDIT_ENDPOINT must be an https:// URL")

    return Settings(
        secret_key=secret,
        password_hash=password_hash,
        allowed_hosts=hosts,
        cookie_secure=_bool("VITALS_COOKIE_SECURE", True),
        session_hours=_int("VITALS_SESSION_HOURS", 12, low=1, high=168),
        endpoint=endpoint,
        cache_ttl=_int("VITALS_CACHE_TTL", 60, low=5, high=3600),
        retry_after=_int("VITALS_RETRY_AFTER", 120, low=5, high=3600),
        http_timeout=_float("VITALS_HTTP_TIMEOUT", 12, low=2, high=60),
        personal=AccountConfig(
            slot="personal",
            key=_text("AVALAI_PERSONAL_API_KEY"),
            label=_text("AVALAI_PERSONAL_LABEL", "کلید من"),
        ),
        company=AccountConfig(
            slot="company",
            key=_text("AVALAI_COMPANY_API_KEY"),
            label=_text("AVALAI_COMPANY_LABEL", "کلید شرکت"),
        ),
    )
