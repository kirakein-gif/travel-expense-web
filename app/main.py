from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from app.routes.travel import router as travel_router

APP_VERSION = "1.25.5"

app = FastAPI(title="딸깍 여비정산서", version=APP_VERSION)
app.mount("/static", StaticFiles(directory="app/static"), name="static")
templates = Jinja2Templates(directory="app/templates")


@app.get("/", response_class=HTMLResponse)
async def home(request: Request):
    return templates.TemplateResponse(
        "index.html",
        {"request": request, "app_version": APP_VERSION},
    )


@app.get("/health")
async def health():
    return {"status": "ok", "version": APP_VERSION}


app.include_router(travel_router, prefix="/api")
