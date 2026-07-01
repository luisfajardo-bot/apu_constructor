import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, CorridaMeta, Perfil


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_crear_apu_con_conn_rollback(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(RuntimeError):
        with alm.transaccion("apus") as conn:
            alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO"), [], conn=conn)
            raise RuntimeError("aborta")
    assert alm.apus.get_apu("A1", "DIURNO") is None       # rollback


def test_eliminar_corrida_con_conn_commit(tmp_path):
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    with alm.transaccion("corridas") as conn:
        ok = alm.corridas.eliminar_corrida(cid, conn=conn)
    assert ok is True and alm.corridas.get_corrida(cid) is None


def test_set_rol_con_conn_rollback(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    with pytest.raises(RuntimeError):
        with alm.transaccion("seguridad") as conn:
            alm.perfiles.set_rol("u1", "admin", conn=conn)
            raise RuntimeError("aborta")
    assert alm.perfiles.get("u1").rol == "consulta"       # rollback
