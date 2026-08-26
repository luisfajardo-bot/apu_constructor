import os

from apu_tool import config


def test_los_tests_nunca_ven_la_database_url_del_entorno():
    """Si esta prueba falla, un `pytest` en esta máquina le escribe a producción.

    `db_backend()` devuelve 'postgres' con solo que exista DATABASE_URL, y ahí `Almacen`
    ignora los paths SQLite del test. El fixture autouse `_nunca_postgres_del_entorno`
    (tests/conftest.py) la borra; esto verifica que siga haciéndolo.
    """
    assert os.environ.get("DATABASE_URL") is None
    assert os.environ.get("APU_DB_BACKEND") is None
    assert config.db_backend() == "sqlite"


def test_max_upload_mb_default(monkeypatch):
    monkeypatch.delenv("APU_MAX_UPLOAD_MB", raising=False)
    assert config.max_upload_mb() == 15


def test_max_upload_mb_env(monkeypatch):
    monkeypatch.setenv("APU_MAX_UPLOAD_MB", "25")
    assert config.max_upload_mb() == 25
    monkeypatch.setenv("APU_MAX_UPLOAD_MB", "basura")
    assert config.max_upload_mb() == 15   # fallback ante valor inválido


def test_ratelimit_enabled(monkeypatch):
    monkeypatch.delenv("APU_RATELIMIT_ENABLED", raising=False)
    assert config.ratelimit_enabled() is True
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "false")
    assert config.ratelimit_enabled() is False
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "0")
    assert config.ratelimit_enabled() is False


def test_web_concurrency(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert config.web_concurrency() == 2
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    assert config.web_concurrency() == 4
