from apu_tool import config


def test_admin_emails_parsea_lista(monkeypatch):
    monkeypatch.setenv("APU_ADMIN_EMAILS", " Jefe@Obra.CO ,  admin2@obra.co ")
    assert config.admin_emails() == {"jefe@obra.co", "admin2@obra.co"}


def test_admin_emails_vacio(monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    assert config.admin_emails() == set()


def test_urls_derivadas_del_ref(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abc123")
    assert config.supabase_url() == "https://abc123.supabase.co"
    assert config.supabase_issuer() == "https://abc123.supabase.co/auth/v1"
    assert config.supabase_jwks_url() == "https://abc123.supabase.co/auth/v1/.well-known/jwks.json"


def test_sin_config_devuelve_none(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PROJECT_REF", raising=False)
    assert config.supabase_url() is None
    assert config.supabase_jwks_url() is None
