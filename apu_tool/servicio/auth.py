"""Autenticación (Supabase Auth) y autorización (RBAC) para la API.

Verifica el JWT localmente contra el JWKS asimétrico de Supabase (PyJWT). La
autorización por roles vive en la tabla `perfiles` (ver resolver_perfil).
NO toca dinero: fuera de la frontera de la IA.
"""
from __future__ import annotations

import jwt
from jwt import PyJWKClient

from apu_tool import config

_ALGOS = ["ES256", "RS256"]


class ErrorAuth(Exception):
    """Fallos de autenticación (token inválido → 401) y autorización (inactivo/no invitado → 403)."""


def verificar_token(token: str, public_key, *, issuer: str,
                    audience: str = "authenticated") -> dict:
    """Verifica firma + exp + aud + iss con una llave pública dada.

    Unidad testeable sin red (los tests inyectan la llave). Lanza ErrorAuth.
    """
    try:
        return jwt.decode(
            token, public_key, algorithms=_ALGOS, audience=audience, issuer=issuer,
            options={"require": ["exp", "aud", "iss"]})
    except jwt.PyJWTError as e:
        raise ErrorAuth(str(e)) from e


_jwks_client: PyJWKClient | None = None


def _cliente_jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = config.supabase_jwks_url()
        if not url:
            raise ErrorAuth("Auth no configurada (falta SUPABASE_PROJECT_REF/URL).")
        _jwks_client = PyJWKClient(url)  # cachea llaves; refresca por kid desconocido
    return _jwks_client


def obtener_claims(token: str) -> dict:
    """Producción: resuelve la llave del JWKS de Supabase y verifica el token."""
    issuer = config.supabase_issuer()
    if not issuer:
        raise ErrorAuth("Auth no configurada.")
    try:
        signing_key = _cliente_jwks().get_signing_key_from_jwt(token)
    except Exception as e:  # PyJWKClientError, red, kid inválido → auth inválida
        raise ErrorAuth(f"No se pudo resolver la llave de firma: {e}") from e
    return verificar_token(token, signing_key.key, issuer=issuer)


import datetime as _dt

from fastapi import Depends, Request, HTTPException

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auditoria import registrar_auditoria
from apu_tool.servicio.dependencias import get_almacen

RANGO = {"consulta": 1, "editor": 2, "admin": 3}


def resolver_perfil(alm: Almacen, user_id: str, email: str) -> Perfil:
    """Devuelve el Perfil activo del usuario; bootstrap admin por APU_ADMIN_EMAILS.

    Lanza ErrorAuth si el usuario está inactivo o no está autorizado (no invitado).
    """
    p = alm.perfiles.get(user_id)
    if p is not None:
        if p.estado != "activo":
            raise ErrorAuth("Usuario inactivo.")
        return p
    if (email or "").strip().lower() in config.admin_emails():
        nuevo = Perfil(user_id=user_id, email=email, rol="admin", estado="activo",
                       nombre="", creado_en=_dt.date.today().isoformat())
        with alm.transaccion("seguridad") as conn:
            alm.perfiles.upsert(nuevo, conn=conn)
            registrar_auditoria(alm, conn, None, "usuario.bootstrap_admin", "usuario", user_id,
                                antes=None,
                                despues={"email": email, "rol": "admin", "estado": "activo"})
        return nuevo
    raise ErrorAuth("Usuario no autorizado (no invitado).")


def _extraer_bearer(request: Request) -> str:
    h = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not h.lower().startswith("bearer "):
        raise ErrorAuth("Falta el token Bearer.")
    return h[7:].strip()


def usuario_actual(request: Request, alm: Almacen = Depends(get_almacen)) -> Perfil:
    """Dependencia FastAPI: verifica el JWT y resuelve el perfil. 401/403."""
    try:
        token = _extraer_bearer(request)
        claims = obtener_claims(token)
    except ErrorAuth as e:
        raise HTTPException(status_code=401, detail=str(e))
    user_id = claims.get("sub", "")
    email = claims.get("email", "")
    try:
        return resolver_perfil(alm, user_id, email)
    except ErrorAuth as e:
        raise HTTPException(status_code=403, detail=str(e))


def requiere_rol(minimo: str):
    """Fábrica de dependencia: exige rol >= minimo (jerarquía). 403 si no."""
    min_rango = RANGO[minimo]

    def _dep(usuario: Perfil = Depends(usuario_actual)) -> Perfil:
        if RANGO.get(usuario.rol, 0) < min_rango:
            raise HTTPException(status_code=403, detail="Permiso insuficiente.")
        return usuario
    return _dep
