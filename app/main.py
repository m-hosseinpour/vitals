"""The FastAPI application: two routes of data, one login, one logout."""

from __future__ import annotations

import logging
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import (
    HTMLResponse,
    JSONResponse,
    PlainTextResponse,
    RedirectResponse,
)
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from starlette.datastructures import FormData
from starlette.middleware.sessions import SessionMiddleware
from starlette.middleware.trustedhost import TrustedHostMiddleware

from . import auth
from .avalai import AccountCredit, CreditService
from .config import Settings, load_settings
from .formatting import ago, asset, clock, duration, money, percent
from .security import LoginThrottle, SecurityHeadersMiddleware

logger = logging.getLogger("vitals")

BASE_DIR = Path(__file__).resolve().parent
MAX_FORM_BYTES = 4096

templates = Jinja2Templates(directory=str(BASE_DIR / "templates"))
templates.env.filters.update(
    {
        "money": money,
        "percent": percent,
        "duration": duration,
        "ago": ago,
        "clock": clock,
    }
)
templates.env.globals["asset"] = asset


def _client_ip(request: Request) -> str:
    return request.client.host if request.client else "unknown"


def _render(
    request: Request,
    name: str,
    context: dict,
    *,
    status_code: int = 200,
    headers: dict[str, str] | None = None,
) -> HTMLResponse:
    return templates.TemplateResponse(
        request,
        name,
        {"request": request, **context},
        status_code=status_code,
        headers=headers,
    )


async def _read_form(request: Request) -> FormData | None:
    """Read a small urlencoded form, refusing anything that could be an upload."""
    content_type = request.headers.get("content-type", "")
    if not content_type.startswith("application/x-www-form-urlencoded"):
        return None
    raw_length = request.headers.get("content-length")
    if raw_length is not None:
        try:
            if int(raw_length) > MAX_FORM_BYTES:
                return None
        except ValueError:
            return None
    try:
        return await request.form(max_fields=10, max_part_size=2048)
    except Exception:  # noqa: BLE001 - malformed body is a refused request
        return None


def _latest(accounts: tuple[AccountCredit, ...]):
    stamps = [
        account.fetched_at for account in accounts if account.fetched_at is not None
    ]
    return max(stamps) if stamps else None


def create_app(settings: Settings | None = None) -> FastAPI:
    settings = settings or load_settings()
    throttle = LoginThrottle()
    cookie_name = "__Host-vitals" if settings.cookie_secure else "vitals_session"

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        app.state.credit = CreditService(settings)
        try:
            yield
        finally:
            await app.state.credit.aclose()

    app = FastAPI(
        title="Vitals",
        docs_url=None,
        redoc_url=None,
        openapi_url=None,
        lifespan=lifespan,
    )

    @app.get("/", response_class=HTMLResponse)
    async def dashboard(request: Request) -> HTMLResponse:
        if not auth.is_authenticated(request, settings):
            return RedirectResponse("/login", status_code=303)
        accounts = await request.app.state.credit.summary()
        return _render(
            request,
            "dashboard.html",
            {
                "accounts": accounts,
                "csrf": auth.csrf_token(request),
                "packages_url": settings.packages_url,
                "updated_at": _latest(accounts),
            },
        )

    @app.get("/partials/body", response_class=HTMLResponse)
    async def dashboard_body(request: Request) -> HTMLResponse:
        if not auth.is_authenticated(request, settings):
            # A redirect here would be followed by fetch() and swap the login page
            # into the dashboard. A 401 lets the client navigate instead.
            return JSONResponse({"error": "unauthenticated"}, status_code=401)
        accounts = await request.app.state.credit.summary()
        return _render(
            request,
            "_body.html",
            {"accounts": accounts, "updated_at": _latest(accounts)},
        )

    @app.get("/login", response_class=HTMLResponse)
    async def login_page(request: Request) -> HTMLResponse:
        if auth.is_authenticated(request, settings):
            return RedirectResponse("/", status_code=303)
        return _render(
            request, "login.html", {"csrf": auth.csrf_token(request), "error": ""}
        )

    @app.post("/login")
    async def login_submit(request: Request):
        ip = _client_ip(request)
        wait = throttle.retry_after(ip)
        if wait:
            return _render(
                request,
                "login.html",
                {
                    "csrf": auth.csrf_token(request),
                    "error": f"تلاش‌های ناموفق زیاد بوده است. {duration(wait)} دیگر دوباره امتحان کنید.",
                },
                status_code=429,
                headers={"Retry-After": str(wait)},
            )

        form = await _read_form(request)
        if form is None:
            return _render(
                request,
                "login.html",
                {
                    "csrf": auth.csrf_token(request),
                    "error": "درخواست قابل خواندن نبود.",
                },
                status_code=400,
            )

        if not auth.csrf_valid(request, form.get("csrf")):
            return _render(
                request,
                "login.html",
                {
                    "csrf": auth.csrf_token(request),
                    "error": "نشست منقضی شده است؛ صفحه را دوباره باز کنید.",
                },
                status_code=403,
            )

        password = form.get("password")
        if not isinstance(password, str) or not auth.verify_password(
            settings, password
        ):
            throttle.record_failure(ip)
            logger.warning("failed dashboard login from %s", ip)
            wait = throttle.retry_after(ip)
            if wait:
                return _render(
                    request,
                    "login.html",
                    {
                        "csrf": auth.csrf_token(request),
                        "error": f"تلاش‌های ناموفق زیاد بوده است. {duration(wait)} دیگر دوباره امتحان کنید.",
                    },
                    status_code=429,
                    headers={"Retry-After": str(wait)},
                )
            return _render(
                request,
                "login.html",
                {"csrf": auth.csrf_token(request), "error": "رمز عبور نادرست است."},
                status_code=401,
            )

        throttle.record_success(ip)
        auth.start_session(request, settings)
        logger.info("successful dashboard login from %s", ip)
        return RedirectResponse("/", status_code=303)

    @app.post("/logout")
    async def logout(request: Request):
        form = await _read_form(request)
        if form is None or not auth.csrf_valid(request, form.get("csrf")):
            return PlainTextResponse("درخواست معتبر نیست.", status_code=403)
        auth.end_session(request)
        return RedirectResponse("/login", status_code=303)

    app.add_middleware(
        TrustedHostMiddleware, allowed_hosts=list(settings.allowed_hosts)
    )
    app.add_middleware(
        SessionMiddleware,
        secret_key=settings.secret_key,
        session_cookie=cookie_name,
        max_age=settings.session_seconds,
        path="/",
        same_site="lax",
        https_only=settings.cookie_secure,
    )
    app.add_middleware(SecurityHeadersMiddleware, hsts=settings.cookie_secure)

    app.mount("/static", StaticFiles(directory=str(BASE_DIR / "static")), name="static")
    return app


app = create_app()
