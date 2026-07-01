from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, Perfil
from apu_tool.servicio import autoria
from apu_tool.servicio import insumos as insumos_svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _actor():
    return Perfil("u-ed", "ed@obra.co", "editor", "activo")


def test_aplicar_cambios_audita_por_entidad(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    out = insumos_svc.aplicar_cambios(alm, [{"insumo_id": iid, "precio": 1500, "fuente": "COSTO INTERNO"}],
                                      actor=_actor())
    assert out["aplicados"] == 1
    items, total = alm.auditoria.listar(accion="precio.editar")
    assert total == 1
    ev = items[0]
    assert ev["entidad_tipo"] == "insumo" and ev["entidad_id"] == str(iid)
    assert ev["antes"]["precio"] == 1000 and ev["despues"]["precio"] == 1500
    assert ev["contexto"]["origen"] == "edicion" and ev["contexto"]["lote_id"]
    assert ev["user_id"] == "u-ed"


def test_aplicar_cambios_partial_success_no_audita_el_malo(tmp_path):
    alm = _alm(tmp_path)
    iid = alm.precios.crear_insumo(Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU"))
    out = insumos_svc.aplicar_cambios(alm, [
        {"insumo_id": iid, "precio": 1500, "fuente": "X"},
        {"insumo_id": 99999, "precio": 10, "fuente": "Y"},   # no existe → error
    ], actor=_actor())
    assert out["aplicados"] == 1 and len(out["errores"]) == 1
    _, total = alm.auditoria.listar()
    assert total == 1                                        # solo el válido dejó auditoría


def test_crear_insumo_audita(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_insumo(alm, {"codigo": "200", "nombre": "ARENA", "unidad": "M3",
                               "grupo": "MAT", "precio": 500, "fuente": "PRECIO IDU"}, actor=_actor())
    items, total = alm.auditoria.listar(accion="insumo.crear")
    assert total == 1 and items[0]["despues"]["codigo"] == "200"


def test_crear_apu_audita(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "AP1", "nombre": "MURO", "unidad": "M2",
                            "turno": "DIURNO", "grupo": "OC", "componentes": []}, actor=_actor())
    items, total = alm.auditoria.listar(accion="apu.crear")
    assert total == 1 and items[0]["entidad_tipo"] == "apu" and items[0]["entidad_id"] == "AP1"


def test_importar_insumos_audita_con_lote_y_origen(tmp_path):
    alm = _alm(tmp_path)
    csv = b"codigo,nombre,unidad,grupo,precio,fuente\n300,GRAVA,M3,MAT,700,PRECIO IDU\n"
    autoria.aplicar_importar_insumos(alm, csv, "insumos.csv", actor=_actor())
    items, total = alm.auditoria.listar(accion="insumo.crear")
    assert total == 1
    assert items[0]["contexto"]["origen"] == "import" and items[0]["contexto"]["lote_id"]
    assert items[0]["contexto"]["archivo"] == "insumos.csv"
