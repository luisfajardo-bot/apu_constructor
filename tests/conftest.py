"""Fixtures compartidos de tests. Override de auth para los tests de API."""
import os

import pytest
from fastapi.testclient import TestClient

from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auth import usuario_actual


def perfil_de_prueba(rol: str = "admin") -> Perfil:
    return Perfil(user_id=f"test-{rol}", email=f"{rol}@test.co", rol=rol, estado="activo")


def cliente(app, rol: str = "admin") -> TestClient:
    """TestClient con usuario_actual sobreescrito por un perfil de prueba."""
    app.dependency_overrides[usuario_actual] = lambda: perfil_de_prueba(rol)
    return TestClient(app)


@pytest.fixture(autouse=True)
def _nunca_postgres_del_entorno(monkeypatch):
    """Los tests corren SIEMPRE contra el SQLite temporal que ellos mismos crean.

    `Almacen` elige el backend con `config.db_backend()`, que devuelve 'postgres' con
    solo que exista `DATABASE_URL` en el entorno — y entonces IGNORA los
    `precios_path/apus_path/corridas_path` que el test le pasó. En una máquina que tiene
    la `DATABASE_URL` de producción exportada (el caso de la máquina de desarrollo), un
    `pytest` suelto le escribe los fixtures a la base real. Ya pasó: el 2026-08-18 dos
    corridas de un test nuevo escribieron APUs, insumos, corridas y una lista de precios
    de fixture contra la Supabase de producción.

    Los tests de Postgres no dependen de esta variable: se saltan o no según
    `TEST_DATABASE_URL` y construyen su propia `Conexion` con ella.
    """
    monkeypatch.delenv("DATABASE_URL", raising=False)
    monkeypatch.delenv("APU_DB_BACKEND", raising=False)


@pytest.fixture(autouse=True)
def _sin_ratelimit(monkeypatch):
    """El rate-limit se apaga por defecto en tests para no volverlos flaky.
    El test de 429 lo reactiva con su propio monkeypatch.setenv."""
    if "APU_RATELIMIT_ENABLED" not in os.environ:
        monkeypatch.setenv("APU_RATELIMIT_ENABLED", "false")
