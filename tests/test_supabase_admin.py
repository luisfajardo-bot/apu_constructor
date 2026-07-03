"""AdminSupabaseHTTP.invitar: debe pasar redirect_to=<APU_PUBLIC_URL>/definir-clave
para que el correo de invitación aterrice en la pantalla de definir contraseña."""
import apu_tool.servicio.supabase_admin as sa
from apu_tool.servicio.supabase_admin import AdminSupabaseHTTP


class _Resp:
    def __init__(self, data):
        self._d = data

    def raise_for_status(self):
        pass

    def json(self):
        return self._d


def test_invitar_pasa_redirect_to(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.setenv("APU_PUBLIC_URL", "https://armador-apus.onrender.com/")  # con slash sobrante
    cap = {}

    def fake_post(url, headers=None, params=None, json=None, timeout=None):
        cap["url"] = url
        cap["params"] = params
        cap["json"] = json
        return _Resp({"id": "uuid-1"})

    monkeypatch.setattr(sa.httpx, "post", fake_post)
    uid = AdminSupabaseHTTP().invitar("nuevo@empresa.com")
    assert uid == "uuid-1"
    assert cap["url"] == "https://proj.supabase.co/auth/v1/invite"
    assert cap["params"] == {"redirect_to": "https://armador-apus.onrender.com/definir-clave"}
    assert cap["json"] == {"email": "nuevo@empresa.com"}


def test_invitar_sin_public_url_no_manda_redirect(monkeypatch):
    monkeypatch.setenv("SUPABASE_URL", "https://proj.supabase.co")
    monkeypatch.setenv("SUPABASE_SERVICE_ROLE_KEY", "svc")
    monkeypatch.delenv("APU_PUBLIC_URL", raising=False)
    cap = {}

    def fake_post(url, headers=None, params=None, json=None, timeout=None):
        cap["params"] = params
        return _Resp({"id": "uuid-2"})

    monkeypatch.setattr(sa.httpx, "post", fake_post)
    AdminSupabaseHTTP().invitar("x@y.co")
    assert cap["params"] is None
