from __future__ import annotations

from pathlib import Path

from fastapi import FastAPI
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles


def webui_root() -> Path:
    return Path(__file__).resolve().parent.parent / "webui"


def webui_assets_root() -> Path:
    return webui_root() / "assets"


def dashboard_html() -> str:
    path = webui_root() / "index.html"
    return path.read_text(encoding="utf-8")


def mount_webui_assets(app: FastAPI, mount_path: str = "/assets") -> None:
    app.mount(mount_path, StaticFiles(directory=str(webui_assets_root())), name="assets")


def create_web_app() -> FastAPI:
    app = FastAPI(title="imonitor web", version="0.4.0")
    mount_webui_assets(app)

    @app.get("/", response_class=HTMLResponse)
    def index() -> str:
        return dashboard_html()

    return app


app = create_web_app()
