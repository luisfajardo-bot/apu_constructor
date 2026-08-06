"""Quién está usando la app ahora mismo.

Un `dict` en el proceso web, no una tabla: el dato caduca en 90 segundos, así que no
tiene sentido pagarle a Supabase un write por usuario por minuto ni una migración para
guardarlo. `marcar` lo llama el propio endpoint `GET /api/presencia`, que el frontend
pide cada 45 s: el latido es el poll.

NO toca la DB ni dinero (no recibe el Almacen; Invariante #1 fuera de discusión).

ponytail: dict en el proceso — si algún día hay más de 1 worker de gunicorn (cada
worker es un proceso con su propio `_vistos`) o más de 1 instance, cada uno ve solo su
porción de la gente. Los vistos vencidos se filtran al leer (`en_linea`) pero nunca se
purgan del dict; inofensivo al volumen de usuarios de hoy, mismo techo que lo de
arriba. El upgrade es una tabla `presencia` (user_id, visto_en) con upsert por latido.
"""
from __future__ import annotations

import time

from apu_tool.nucleo.models import Perfil

VENTANA_S = 90.0
"""Cuánto vale un latido. El frontend late cada 45 s: dos latidos de margen."""

# user_id -> (visto_en, email, nombre)
_vistos: dict[str, tuple[float, str, str]] = {}


def marcar(perfil: Perfil, *, ahora: float | None = None) -> None:
    """Registra que este usuario está activo. Idempotente por usuario."""
    _vistos[perfil.user_id] = (
        time.time() if ahora is None else ahora,
        perfil.email or "",
        perfil.nombre or "",
    )


def en_linea(*, ahora: float | None = None) -> list[dict]:
    """Los vistos dentro de la ventana, ordenados por nombre (o correo si no tiene).

    `list(_vistos.items())` toma una foto antes de iterar: el endpoint es un `def`
    sync, así que Starlette lo corre en el threadpool de anyio, y dos pedidos
    concurrentes pueden cruzarse (un hilo iterando mientras otro inserta un user_id
    nuevo en `marcar`) -> RuntimeError('dictionary changed size during iteration')
    si se itera el dict vivo. No se expone `user_id` (UUID de Supabase Auth): nadie
    lo consume del lado del cliente.
    """
    t = time.time() if ahora is None else ahora
    corte = t - VENTANA_S
    vivos = [
        {"email": email, "nombre": nombre}
        for _uid, (visto, email, nombre) in list(_vistos.items())
        if visto > corte
    ]
    return sorted(vivos, key=lambda p: (p["nombre"] or p["email"]).lower())
