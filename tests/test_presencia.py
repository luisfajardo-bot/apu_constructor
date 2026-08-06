"""Presencia: quién está usando la app ahora mismo.

El reloj se inyecta (`ahora=`) en vez de dormir: un test que espera 91 segundos
reales no lo corre nadie.
"""
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import presencia


def _perfil(uid="u1", email="ana@obra.co", nombre="Ana"):
    return Perfil(user_id=uid, email=email, rol="editor", estado="activo", nombre=nombre)


def setup_function():
    presencia._vistos.clear()


def test_marcar_deja_al_usuario_en_linea():
    presencia.marcar(_perfil(), ahora=1000.0)
    assert presencia.en_linea(ahora=1000.0) == [
        {"user_id": "u1", "email": "ana@obra.co", "nombre": "Ana"}]


def test_pasada_la_ventana_ya_no_esta_en_linea():
    presencia.marcar(_perfil(), ahora=1000.0)
    assert presencia.en_linea(ahora=1000.0 + presencia.VENTANA_S + 1) == []


def test_un_latido_dentro_de_la_ventana_lo_mantiene():
    """El frontend late cada 45 s con ventana de 90 s: dos latidos de margen, así
    una petición perdida no apaga el punto."""
    presencia.marcar(_perfil(), ahora=1000.0)
    presencia.marcar(_perfil(), ahora=1045.0)
    assert len(presencia.en_linea(ahora=1091.0)) == 1


def test_varios_usuarios_ordenados_por_nombre():
    presencia.marcar(_perfil("u1", "zoe@obra.co", "Zoe"), ahora=1000.0)
    presencia.marcar(_perfil("u2", "ana@obra.co", "Ana"), ahora=1000.0)
    assert [p["nombre"] for p in presencia.en_linea(ahora=1000.0)] == ["Ana", "Zoe"]


def test_sin_nombre_ordena_y_muestra_por_correo():
    """Un usuario invitado que todavía no puso su nombre no puede quedar invisible."""
    presencia.marcar(_perfil("u1", "beto@obra.co", ""), ahora=1000.0)
    en_linea = presencia.en_linea(ahora=1000.0)
    assert en_linea == [{"user_id": "u1", "email": "beto@obra.co", "nombre": ""}]


def test_el_mismo_usuario_no_se_duplica():
    presencia.marcar(_perfil(), ahora=1000.0)
    presencia.marcar(_perfil(), ahora=1010.0)
    assert len(presencia.en_linea(ahora=1010.0)) == 1
