"""App FastAPI: monta /api y, si existe el build, sirve el frontend (web/dist)."""
from __future__ import annotations

from typing import Optional

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import rutas

WEB_DIST = config.PROJECT_ROOT / "web" / "dist"


def _crear_almacen() -> Almacen:
    alm = Almacen()
    alm.init_schema()
    return alm


def create_app(almacen: Optional[Almacen] = None) -> FastAPI:
    app = FastAPI(title="Armador de APUs")
    app.state.almacen = almacen or _crear_almacen()
    app.include_router(rutas.router, prefix="/api")
    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        @app.get("/{full_path:path}")
        def spa(full_path: str):
            return FileResponse(WEB_DIST / "index.html")
    return app


app = create_app()
