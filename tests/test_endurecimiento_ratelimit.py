from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from apu_tool.servicio import rutas
from apu_tool.servicio.supabase_admin import AdminSupabaseFake
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    app = create_app(almacen=alm)
    fake = AdminSupabaseFake(id_por_email={"a@obra.co": "u-a", "b@obra.co": "u-b",
                                           "c@obra.co": "u-c", "d@obra.co": "u-d"})
    app.dependency_overrides[rutas.get_admin_supabase] = lambda: fake
    return app


def test_invitar_supera_limite_da_429(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "true")   # activarlo para ESTE test
    cli = cliente(_app(tmp_path), rol="admin")
    correos = ["a@obra.co", "b@obra.co", "c@obra.co", "d@obra.co"]
    codigos = [cli.post("/api/usuarios/invitar",
                        json={"email": e, "rol": "consulta", "nombre": ""}).status_code
               for e in correos]
    assert codigos[:3] == [200, 200, 200]     # los 3 primeros pasan (límite 3/minute)
    assert codigos[3] == 429                  # el 4º es rechazado
