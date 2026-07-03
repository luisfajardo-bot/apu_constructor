"""Cliente de la Admin API de Supabase Auth, tras una interfaz (fake en tests).

Solo se usa server-side con la service_role key. Llama por HTTPS (443), así que
funciona aunque los puertos de BD estén bloqueados.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from apu_tool import config


@runtime_checkable
class AdminSupabase(Protocol):
    def invitar(self, email: str) -> str:
        """Invita/crea el usuario en Supabase Auth; devuelve su user_id (UUID)."""
        ...


class AdminSupabaseHTTP:
    """Implementación real contra la Admin API de Supabase."""

    def invitar(self, email: str) -> str:
        base = config.supabase_url()
        key = config.supabase_service_role_key()
        if not base or not key:
            raise RuntimeError("Falta SUPABASE_URL/SERVICE_ROLE_KEY para invitar.")
        headers = {"Authorization": f"Bearer {key}", "apikey": key,
                   "Content-Type": "application/json"}
        # redirect_to explícito -> el correo de invitación aterriza en /definir-clave
        # (así la Site URL de Supabase puede quedar en la raíz). Debe estar en la lista
        # de Redirect URLs permitidas del proyecto.
        pub = config.public_url()
        params = {"redirect_to": f"{pub}/definir-clave"} if pub else None
        r = httpx.post(f"{base}/auth/v1/invite", headers=headers, params=params,
                       json={"email": email}, timeout=20.0)
        r.raise_for_status()
        return r.json()["id"]


class AdminSupabaseFake:
    """Fake para tests: no llama a la red; asigna ids deterministas."""

    def __init__(self, id_por_email: dict | None = None):
        self._ids = id_por_email or {}
        self.invitados: list[str] = []

    def invitar(self, email: str) -> str:
        self.invitados.append(email)
        return self._ids.get(email, f"fake-{email}")
