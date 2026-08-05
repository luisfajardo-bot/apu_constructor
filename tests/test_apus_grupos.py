"""Vocabulario de grupos de APU: lista base de config ∪ grupos en uso."""
from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu
from apu_tool.servicio import apus as apus_svc
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_incluye_la_lista_base_con_la_biblioteca_vacia(tmp_path):
    alm = _alm(tmp_path)
    assert apus_svc.grupos(alm) == sorted(config.GRUPOS_APU_BASE)


def test_suma_los_grupos_en_uso(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "OBRA ESPECIAL SL5")])
    out = apus_svc.grupos(alm)
    assert "OBRA ESPECIAL SL5" in out
    assert set(config.GRUPOS_APU_BASE) <= set(out)
    assert out == sorted(out)


def test_dedup_insensible_a_mayusculas_y_tildes_gana_config(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "señalizacion")])
    out = apus_svc.grupos(alm)
    assert out.count("SEÑALIZACIÓN") == 1
    assert "señalizacion" not in out          # gana la ortografía de config


def test_un_grupo_sin_apus_desaparece(tmp_path):
    """La autolimpieza es la propiedad por la que se eligió no tener tabla."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "TYPEO RARO")])
    assert "TYPEO RARO" in apus_svc.grupos(alm)
    alm.apus.borrar_apu("A1", "DIURNO")
    assert "TYPEO RARO" not in apus_svc.grupos(alm)


def test_endpoint_devuelve_el_vocabulario(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "OBRA ESPECIAL SL5")])
    cli = cliente(create_app(almacen=alm), rol="consulta")
    r = cli.get("/api/apus/grupos")
    assert r.status_code == 200, r.text
    assert "OBRA ESPECIAL SL5" in r.json()
    assert "PAVIMENTOS" in r.json()
