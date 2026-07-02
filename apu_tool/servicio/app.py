"""App FastAPI: monta /api y, si existe el build, sirve el frontend (web/dist)."""
from __future__ import annotations

import logging
from typing import Optional

from fastapi import FastAPI, Request
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import limites
from apu_tool.servicio import rutas
from apu_tool.servicio.limites import LimiteSubida
from apu_tool.servicio.seguridad_headers import CabecerasSeguridad

logger = logging.getLogger("apu_tool")

WEB_DIST = config.PROJECT_ROOT / "web" / "dist"


def _crear_almacen() -> Almacen:
    alm = Almacen()
    alm.init_schema()
    return alm


def create_app(almacen: Optional[Almacen] = None) -> FastAPI:
    from contextlib import asynccontextmanager

    @asynccontextmanager
    async def lifespan(app: FastAPI):
        yield
        app.state.almacen.cerrar()  # cierra el pool Postgres (no-op en SQLite)

    _docs = config.docs_enabled()
    app = FastAPI(title="Armador de APUs", lifespan=lifespan,
                  docs_url="/docs" if _docs else None,
                  redoc_url="/redoc" if _docs else None,
                  openapi_url="/openapi.json" if _docs else None)
    app.state.almacen = almacen or _crear_almacen()
    app.include_router(rutas.router, prefix="/api")
    # add_middleware PREPENDE: el último agregado queda MÁS AFUERA. Por eso
    # CabecerasSeguridad se registra AL FINAL, para envolver a LimiteSubida y
    # SlowAPIMiddleware y así poner cabeceras en TODA respuesta (incl. 413/429
    # y estáticos). Excepción: un 500 desde el handler de Exception sale por
    # ServerErrorMiddleware de Starlette, que está por fuera de TODO middleware
    # de usuario — ninguna cabecera de usuario puede alcanzarlo (límite de Starlette).
    app.add_middleware(LimiteSubida, max_bytes=config.max_upload_mb() * 1024 * 1024)
    limites.limiter.enabled = config.ratelimit_enabled()
    app.state.limiter = limites.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
    app.add_middleware(CabecerasSeguridad)

    @app.exception_handler(ValueError)
    async def _manejar_valor(request: Request, exc: ValueError):
        logger.warning("ValueError no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=400, content={"detail": "Solicitud inválida."})

    @app.exception_handler(Exception)
    async def _manejar_error(request: Request, exc: Exception):
        # Traza completa SOLO al log server-side; al cliente, mensaje genérico.
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Error interno."})

    if WEB_DIST.exists():
        app.mount("/assets", StaticFiles(directory=WEB_DIST / "assets"), name="assets")

        # IMPORTANTE: esta ruta DEBE ser la ULTIMA registrada. Al ser greedy
        # ({full_path:path}), cualquier ruta /api/* o de FastAPI (/docs,
        # /openapi.json) añadida DESPUES de este decorador quedaría ensombrecida
        # y devolvería index.html en lugar de su handler real.
        @app.get("/{full_path:path}")
        def spa(full_path: str):
            return FileResponse(WEB_DIST / "index.html")
    return app


app = create_app()
