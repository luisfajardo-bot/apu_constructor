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
from typing import Optional

from fastapi import Depends, Request, HTTPException

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auditoria import registrar_auditoria
from apu_tool.servicio.dependencias import get_almacen

RANGO = {"consulta": 1, "editor": 2, "admin": 3}

# Proveedores externos cuya verificación de identidad aceptamos para adoptar un
# perfil por email. Solo Google está habilitado en Supabase hoy.
_PROVEEDORES_CONFIABLES = {"google"}
_METODOS_PROVEEDOR = {"oauth"}


def _proveedores_de_cuenta(claims: dict) -> list[str]:
    """Proveedores vinculados a la CUENTA según `app_metadata`, validados como `str`.

    Solo cambia con la service_role (nunca desde el cliente): describe la cuenta, no
    la sesión que está entrando ahora mismo."""
    app = claims.get("app_metadata")
    if not isinstance(app, dict):
        return []
    providers = app.get("providers")
    if not isinstance(providers, list):
        provider = app.get("provider")
        providers = [provider] if isinstance(provider, str) else []
    return [p for p in providers if isinstance(p, str)]


def _senal_identidad(claims: dict) -> Optional[str]:
    """Etiqueta de qué señal respalda ESTA sesión, o None si ninguna es confiable.

    Única fuente de la lógica: `identidad_verificada()` se define en términos de esta
    función, así que agregar la etiqueta (para auditoría) no duplica la política.

    - Exige SIEMPRE un proveedor confiable vinculado a la cuenta (`app_metadata`). Sin
      eso, no hay nada que respalde la identidad, sin importar qué traiga `amr`.
    - Si la sesión trae `amr` como una lista NO vacía, ESTRECHA lo anterior: exige que
      alguno de sus métodos sea un método de proveedor externo (`oauth`). Una cuenta con
      Google vinculado que entró por contraseña (`amr=[{"method": "password"}]`) no
      cuenta como respaldada por Google, aunque `app_metadata.providers` incluya
      `"google"` — y una entrada de `amr` con forma inesperada (`method` que no es
      `str`) tampoco matchea, así que tampoco cuenta: no es lo mismo que "sin amr".
    - Solo si `amr` viene vacío o ausente (no una lista NO vacía) se queda con la sola
      señal de cuenta.
    """
    confiables = [p for p in _proveedores_de_cuenta(claims) if p in _PROVEEDORES_CONFIABLES]
    if not confiables:
        return None
    amr = claims.get("amr")
    if isinstance(amr, list) and amr:
        metodos = [m.get("method") for m in amr if isinstance(m, dict)]
        de_proveedor = [m for m in metodos if isinstance(m, str) and m in _METODOS_PROVEEDOR]
        if not de_proveedor:
            return None
        return f"amr:{de_proveedor[0]}"
    return f"app_metadata:{confiables[0]}"


def identidad_verificada(claims: dict) -> bool:
    """True si un proveedor externo confiable (Google) respalda ESTA sesión.

    Lee solo claims que pone GoTrue y el usuario no puede escribir:

    - `app_metadata.provider(s)`: los proveedores vinculados a la cuenta. Solo se
      cambian con la service_role. Es condición NECESARIA: sin un proveedor
      confiable acá, no hay nada que respalde la identidad.
    - `amr`: los métodos de autenticación de ESTA sesión (`[{method, timestamp}]`).
      Estrecha lo anterior: una cuenta con Google vinculado que entró por
      contraseña NO cuenta como respaldada por Google. Si el token no trae `amr`,
      queda solo la señal de cuenta.

    NUNCA lee `user_metadata`: ese bolsillo lo escribe el propio usuario con
    `updateUser({data})` y la anon key pública, así que no sirve para autorizar
    (invariante del repo: docs/auditoria-codigo-2026-07-01.md).
    """
    return _senal_identidad(claims) is not None


def _adoptar_por_email(alm: Almacen, user_id: str, email: str,
                       senal: Optional[str] = None) -> Optional[Perfil]:
    """Re-clava a `user_id` el perfil de ese email, si hay EXACTAMENTE uno y está activo.

    Es lo que permite que un invitado entre con Google cuando Supabase le entrega un
    `user_id` distinto al que creó la invitación. El llamador ya verificó que la
    identidad viene respaldada por un proveedor externo: sin eso, alguien que declare su
    propio `user_metadata.email_verified = true` (algo que puede hacer con la anon key,
    sin que nadie lo confirme) se quedaría con el perfil de otro y su rol.

    Con dos perfiles del mismo email no se adivina: devuelve None y el llamador deniega.
    `perfiles.email` no es UNIQUE y en producción ya hubo usuarios duplicados.

    Un perfil inactivo no se adopta: no tiene sentido re-clavar una fila muerta (en
    producción hay perfiles huérfanos de usuarios borrados en Supabase), y así esta
    puerta no toca nada en el caso que de todos modos va a terminar denegando (cae en
    el mismo 403 de "no invitado" de siempre).

    `senal` es la etiqueta de `_senal_identidad()` (p.ej. "amr:oauth"), solo para dejar
    registro en la auditoría de qué prueba disparó la adopción; no cambia la decisión.
    """
    email = (email or "").strip().lower()
    if not email:
        return None
    candidatos = alm.perfiles.get_por_email(email)
    if len(candidatos) != 1:
        return None
    viejo = candidatos[0]
    if viejo.estado != "activo":
        return None
    with alm.transaccion("seguridad") as conn:
        movido = alm.perfiles.reasignar_user_id(viejo.user_id, user_id, conn=conn)
        if not movido:
            # El UPDATE no movió ninguna fila (carrera con otra adopción concurrente,
            # p.ej. varias llamadas en paralelo tras un login): no hay nada que auditar
            # y la puerta deniega, fail-closed, en vez de fabricar un Perfil o dejar
            # una fila de auditoría de un vínculo que no ocurrió.
            return None
        registrar_auditoria(alm, conn, None, "usuario.vincular_identidad", "usuario",
                            user_id, antes={"user_id": viejo.user_id, "email": viejo.email},
                            despues={"user_id": user_id, "email": viejo.email,
                                     "rol": viejo.rol},
                            contexto={"email_sesion": email, "senal": senal})
    return alm.perfiles.get(user_id)


def resolver_perfil(alm: Almacen, user_id: str, email: str,
                    identidad_verificada: bool = False,
                    senal_identidad: Optional[str] = None) -> Perfil:
    """Devuelve el Perfil activo del usuario; bootstrap admin por APU_ADMIN_EMAILS.

    `identidad_verificada` es true solo si un proveedor externo (Google) respalda esta
    sesión — la arma la función `identidad_verificada()` de este mismo módulo a partir
    de los claims del JWT (`amr`/`app_metadata`, nunca `user_metadata`). Solo con eso en
    true se intenta la adopción por email. El default es False para que la ausencia de
    prueba nunca adopte nada.

    `senal_identidad` es la etiqueta de auditoría de esa misma prueba (`_senal_identidad()`,
    p.ej. "amr:oauth"); parámetro opcional puramente informativo, para que la fila de
    auditoría diga QUÉ señal disparó la adopción sin que esta función tenga que saber de
    JWTs. El default `None` no cambia el comportamiento de llamadas existentes con 3 o 4
    argumentos (los tests de este módulo la siguen llamando así).

    Lanza ErrorAuth si el usuario está inactivo o no está autorizado (no invitado).
    """
    p = alm.perfiles.get(user_id)
    if p is None and identidad_verificada:
        p = _adoptar_por_email(alm, user_id, email, senal_identidad)
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
    senal = _senal_identidad(claims)
    try:
        return resolver_perfil(alm, user_id, email, senal is not None, senal)
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
