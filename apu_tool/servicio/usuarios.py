"""Lógica de gestión de usuarios (solo-Admin). Mutaciones sensibles: ganchos para
auditoría del Plan 3. No toca dinero."""
from __future__ import annotations

import datetime as dt

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.supabase_admin import AdminSupabase

_ROLES = {"admin", "editor", "consulta"}
_ESTADOS = {"activo", "inactivo"}


def listar(alm: Almacen) -> list[dict]:
    return [{"user_id": p.user_id, "email": p.email, "rol": p.rol,
             "estado": p.estado, "nombre": p.nombre} for p in alm.perfiles.listar()]


def invitar(alm: Almacen, admin: AdminSupabase, email: str, rol: str,
            nombre: str = "") -> dict:
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("El email es obligatorio.")
    if rol not in _ROLES:
        raise ValueError(f"Rol inválido: {rol}.")
    user_id = admin.invitar(email)
    alm.perfiles.upsert(Perfil(user_id=user_id, email=email, rol=rol, estado="activo",
                               nombre=nombre, creado_en=dt.date.today().isoformat()))
    return {"user_id": user_id, "email": email, "rol": rol, "estado": "activo"}


def _existe(alm: Almacen, user_id: str) -> Perfil:
    p = alm.perfiles.get(user_id)
    if p is None:
        raise ValueError("Usuario no encontrado.")
    return p


def _proteger_ultimo_admin(alm: Almacen, objetivo: Perfil) -> None:
    """Impide dejar el sistema sin ningún admin activo."""
    if objetivo.rol == "admin" and objetivo.estado == "activo" \
            and alm.perfiles.contar_admins_activos() <= 1:
        raise ValueError("No se puede degradar/desactivar al último Admin activo.")


def cambiar_rol(alm: Almacen, actor: Perfil, user_id: str, rol: str) -> dict:
    if rol not in _ROLES:
        raise ValueError(f"Rol inválido: {rol}.")
    objetivo = _existe(alm, user_id)
    if rol != "admin":
        _proteger_ultimo_admin(alm, objetivo)
    alm.perfiles.set_rol(user_id, rol)
    return {"user_id": user_id, "rol": rol}


def cambiar_estado(alm: Almacen, actor: Perfil, user_id: str, estado: str) -> dict:
    if estado not in _ESTADOS:
        raise ValueError(f"Estado inválido: {estado}.")
    objetivo = _existe(alm, user_id)
    if estado == "inactivo":
        _proteger_ultimo_admin(alm, objetivo)
    alm.perfiles.set_estado(user_id, estado)
    return {"user_id": user_id, "estado": estado}
