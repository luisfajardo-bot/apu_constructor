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
    """Autenticación inválida (token ausente/expirado/firma mala). → 401."""


def verificar_token(token: str, public_key, *, issuer: str,
                    audience: str = "authenticated") -> dict:
    """Verifica firma + exp + aud + iss con una llave pública dada.

    Unidad testeable sin red (los tests inyectan la llave). Lanza ErrorAuth.
    """
    try:
        return jwt.decode(
            token, public_key, algorithms=_ALGOS, audience=audience, issuer=issuer,
            options={"require": ["exp", "aud", "iss"]})
    except jwt.InvalidTokenError as e:
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
