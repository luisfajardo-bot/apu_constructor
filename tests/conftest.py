"""Fixtures compartidos de tests. Override de auth para los tests de API."""
from fastapi.testclient import TestClient

from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auth import usuario_actual


def perfil_de_prueba(rol: str = "admin") -> Perfil:
    return Perfil(user_id=f"test-{rol}", email=f"{rol}@test.co", rol=rol, estado="activo")


def cliente(app, rol: str = "admin") -> TestClient:
    """TestClient con usuario_actual sobreescrito por un perfil de prueba."""
    app.dependency_overrides[usuario_actual] = lambda: perfil_de_prueba(rol)
    return TestClient(app)
