"""Middleware de cabeceras de seguridad (HSTS, nosniff, X-Frame-Options, Referrer-Policy, CSP).

La CSP se restringe al mismo origen; `connect-src` añade el host de Supabase (supabase-js hace
fetch + realtime/websocket). Solo son cabeceras HTTP: no afecta la invariante #1."""
from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware

from apu_tool import config


def construir_csp() -> str:
    conn = ["'self'"]
    base = config.supabase_url()
    if base:
        host = urlparse(base).netloc
        if host:
            conn.append(f"https://{host}")
            conn.append(f"wss://{host}")
    return "; ".join([
        "default-src 'self'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",   # estilos inline de la SPA/Tailwind
        "script-src 'self'",
        f"connect-src {' '.join(conn)}",
    ])


class CabecerasSeguridad(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._csp = construir_csp()   # se calcula una vez al arrancar (lee config/env)

    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy", self._csp)
        return resp
