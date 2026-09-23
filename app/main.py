import logging

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse, JSONResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from app.config import ACCESS_CONTROL_ENABLED, ACCESS_COOKIE_NAME, ACCESS_ENTRY_MODE, OWNER_ACCESS_KEY
from app.routes.travel import router as travel_router
from app.services.access_service import (
    OFFICIAL_GUIDE_URL,
    create_session_token,
    is_allowed_referer,
    owner_key_matches,
    verify_session_token,
)

APP_VERSION = "1.29.1"

logger = logging.getLogger("uvicorn.error")

app = FastAPI(title="딸깍 여비정산서", version=APP_VERSION)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")

_PUBLIC_PATHS = {"/enter", "/owner", "/health", "/favicon.ico"}


def _has_access(request: Request) -> bool:
    if not ACCESS_CONTROL_ENABLED:
        return True
    token = request.cookies.get(ACCESS_COOKIE_NAME)
    return verify_session_token(token, OWNER_ACCESS_KEY)


def _grant_access(response):
    token = create_session_token(OWNER_ACCESS_KEY)
    response.set_cookie(
        key=ACCESS_COOKIE_NAME,
        value=token,
        httponly=True,
        secure=True,
        samesite="lax",
        path="/",
    )
    return response


def _access_required(request: Request, status_code: int = 403):
    return templates.TemplateResponse(
        "access_required.html",
        {
            "request": request,
            "official_guide_url": OFFICIAL_GUIDE_URL,
        },
        status_code=status_code,
    )


@app.middleware("http")
async def access_gate(request: Request, call_next):
    path = request.url.path
    if (
        not ACCESS_CONTROL_ENABLED
        or path in _PUBLIC_PATHS
        or path.startswith("/static/")
    ):
        return await call_next(request)

    if _has_access(request):
        return await call_next(request)

    logger.info("[ACCESS] BLOCKED path=%s", path)
    if path.startswith("/api/"):
        return JSONResponse(
            status_code=403,
            content={
                "detail": "공식 사용설명서의 실행 버튼을 통해 접속해 주세요.",
                "guide_url": OFFICIAL_GUIDE_URL,
            },
        )
    return _access_required(request)


@app.get("/enter", response_class=HTMLResponse)
async def official_entry(request: Request):
    if not ACCESS_CONTROL_ENABLED:
        return RedirectResponse(url="/", status_code=303)

    if not OWNER_ACCESS_KEY:
        logger.error("[ACCESS] OWNER_ACCESS_KEY is missing while access control is enabled")
        return HTMLResponse(
            "접근제어 설정이 완료되지 않았습니다. 관리자에게 문의해 주세요.",
            status_code=503,
        )

    referer = request.headers.get("referer")
    if ACCESS_ENTRY_MODE == "referer":
        if not is_allowed_referer(referer):
            logger.info("[ACCESS] ENTRY_REJECTED referer=%s mode=referer", referer or "-")
            return _access_required(request)
        logger.info("[ACCESS] ENTRY_ACCEPTED referer=%s mode=referer", referer)
    else:
        # Some bulletin-board renderers force rel=noreferrer and strip
        # referrerpolicy attributes. In link mode, /enter itself is the
        # official gateway so the guide page only needs a stable link.
        logger.info("[ACCESS] ENTRY_ACCEPTED referer=%s mode=entry-link", referer or "-")

    return _grant_access(RedirectResponse(url="/", status_code=303))


@app.get("/owner", response_class=HTMLResponse)
async def owner_login_page(request: Request):
    if not ACCESS_CONTROL_ENABLED:
        return RedirectResponse(url="/", status_code=303)
    return templates.TemplateResponse(
        "owner.html",
        {"request": request, "error": None},
    )


@app.post("/owner", response_class=HTMLResponse)
async def owner_login(request: Request):
    if not ACCESS_CONTROL_ENABLED:
        return RedirectResponse(url="/", status_code=303)

    if not OWNER_ACCESS_KEY:
        logger.error("[ACCESS] OWNER_ACCESS_KEY is missing while access control is enabled")
        return templates.TemplateResponse(
            "owner.html",
            {
                "request": request,
                "error": "관리자 접속 설정이 완료되지 않았습니다.",
            },
            status_code=503,
        )

    form = await request.form()
    submitted = str(form.get("access_key") or "")
    if not owner_key_matches(submitted, OWNER_ACCESS_KEY):
        logger.warning("[ACCESS] OWNER_LOGIN_FAILED")
        return templates.TemplateResponse(
            "owner.html",
            {
                "request": request,
                "error": "관리자 접속키가 올바르지 않습니다.",
            },
            status_code=403,
        )

    logger.info("[ACCESS] OWNER_LOGIN_OK")
    return _grant_access(RedirectResponse(url="/", status_code=303))


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "app_version": APP_VERSION},
    )


@app.get("/health")
async def health():
    return {
        "status": "ok",
        "version": APP_VERSION,
        "access_control": ACCESS_CONTROL_ENABLED,
    }


app.include_router(travel_router, prefix="/api")
