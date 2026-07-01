"""Endurecimiento de tráfico: límite de tamaño de subida (aquí) y rate limiting (Task 6).

El límite de subida rechaza por `Content-Length` ANTES de leer el cuerpo → no se carga a memoria
un archivo enorme. Solo mira cabeceras/tamaño: no afecta la invariante #1."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse

from slowapi import Limiter
from slowapi.util import get_remote_address

# Limiter global keyeado por IP remota. `enabled` se fija en create_app desde config
# (default true; los tests lo apagan). default_limits aplica a TODA ruta vía SlowAPIMiddleware.
# Nota: el storage por defecto es en memoria y por-proceso; con varios workers de
# gunicorn el límite efectivo es POR WORKER (mitigación de abuso, no una cuota global exacta).
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])


class LimiteSubida(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > self.max_bytes:
                    return JSONResponse(status_code=413,
                                        content={"detail": "Archivo demasiado grande."})
            except ValueError:
                pass  # Content-Length no numérico: dejar seguir (lo valida el endpoint)
        return await call_next(request)
