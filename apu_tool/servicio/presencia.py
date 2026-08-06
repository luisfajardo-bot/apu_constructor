"""Quién está usando la app ahora mismo.

Un `dict` en el proceso web, no una tabla: el dato caduca en 90 segundos, así que no
tiene sentido pagarle a Supabase un write por usuario por minuto ni una migración para
guardarlo. `marcar` lo llama el propio endpoint `GET /api/presencia`, que el frontend
pide cada 45 s: el latido es el poll.

NO toca la DB ni dinero (no recibe el Almacen; Invariante #1 fuera de discusión).

ponytail: dict en el proceso — si algún día hay 2 instances, cada uno ve su mitad de la
gente. El upgrade es una tabla `presencia` (user_id, visto_en) con upsert por latido.
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
    """Los vistos dentro de la ventana, ordenados por nombre (o correo si no tiene)."""
    t = time.time() if ahora is None else ahora
    corte = t - VENTANA_S
    vivos = [
        {"user_id": uid, "email": email, "nombre": nombre}
        for uid, (visto, email, nombre) in _vistos.items()
        if visto > corte
    ]
    return sorted(vivos, key=lambda p: (p["nombre"] or p["email"]).lower())
