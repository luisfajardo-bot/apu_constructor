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
def _sin_ratelimit(monkeypatch):
    """El rate-limit se apaga por defecto en tests para no volverlos flaky.
    El test de 429 lo reactiva con su propio monkeypatch.setenv."""
    if "APU_RATELIMIT_ENABLED" not in os.environ:
        monkeypatch.setenv("APU_RATELIMIT_ENABLED", "false")
