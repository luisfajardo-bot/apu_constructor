"""Cableado ruta -> servicio del `lista_id`/`lista` (Hallazgo 1 de la revisión de
commit e84c0e1, Task 9).

`tests/test_servicio_autoria.py` y `tests/test_servicio_insumos_lista.py` llaman a
`insumos_svc`/`autoria` DIRECTAMENTE, y `tests/test_api_lista_invalida.py` solo
ejercita el camino del 400 (lista inexistente). Ninguno de los dos va por HTTP con
una lista VÁLIDA verificando dónde cayó el precio: los 9 puntos donde `rutas.py`
reenvía la lista al servicio pueden romperse (un merge mal resuelto, un reorder de
argumentos) sin que la suite se entere, y el daño concreto es que los precios de una
obra se escriban en silencio sobre Principal (el catálogo real de la empresa).

Estos tests van por HTTP y afirman DÓNDE cayó el precio (Principal vs. la lista NP),
para los 9 puntos de reenvío: listar, fuentes, detalle, cambios, importar/preview,
importar, crear, corridas y corridas/stream.
"""
import io

import openpyxl

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.licitacion import write_sample_licitacion
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio.app import create_app
from tests.conftest import cliente

_XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _cli(tmp_path, rol="editor"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 1000.0, "PRECIO IDU")])
    return cliente(create_app(almacen=alm), rol=rol), alm


def _con_apu(alm):
    """Biblioteca no vacía: `POST /corridas` auto-semilla si `counts()["apus"] == 0`
    (rutas.py -> pipeline.ensure_seeded), y ese camino lee el Excel histórico, que no
    existe en CI -> 500. Con un APU en la biblioteca el guard no se dispara, igual que
    en tests/test_api_corridas.py::_cliente. Ojo: ensure_seeded() se arma su propio
    Almacen() por defecto, así que NO mira este almacén inyectado.
    """
    alm.apus.insert_apus([Apu("APU-1", "Concreto 3000 PSI", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent(
        "APU-1", "DIURNO", "100", "Concreto 3000 PSI", "M3", 1.0, 1000.0)])


def _con_lista(alm, iid, precio, fuente="ACTA NP"):
    """Crea una lista NP y le fija a `iid` un precio propio, distinto de Principal."""
    lid = alm.precios.crear_lista("NP Calle 13")
    alm.precios.set_precio_por_id(iid, precio, fuente, lista_id=lid)
    return lid


def _xlsx_upsert_100(precio_nuevo) -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "precio"])
    ws.append(["100", "Concreto 3000 PSI", precio_nuevo])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _xlsx_lic(tmp_path):
    p = tmp_path / "lic.xlsx"
    write_sample_licitacion(p, [LicitacionItem(
        item="1", descripcion="Concreto 3000 PSI", unidad="M3", cantidad=10.0,
        precio_contractual=400000.0, shift="DIURNO")])
    return p


# ------------------------------------------------------------------------ lectura
def test_get_insumos_lista_devuelve_el_precio_de_esa_lista(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    iid = alm.precios.get_candidatos("100")[0].id
    lid = _con_lista(alm, iid, 5000.0)
    en_np = next(i for i in cli.get(f"/api/insumos?lista={lid}").json()["items"]
                 if i["id"] == iid)
    assert en_np["precio"] == 5000.0
    en_principal = next(i for i in cli.get("/api/insumos").json()["items"]
                        if i["id"] == iid)
    assert en_principal["precio"] == 1000.0


def test_get_insumos_fuentes_lista_devuelve_la_fuente_de_esa_lista(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    iid = alm.precios.get_candidatos("100")[0].id
    lid = _con_lista(alm, iid, 5000.0, fuente="ACTA NP")
    assert cli.get(f"/api/insumos/fuentes?lista={lid}").json() == ["ACTA NP"]
    assert cli.get("/api/insumos/fuentes").json() == ["PRECIO IDU"]


def test_get_insumo_detalle_lista_devuelve_precio_de_esa_lista(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    iid = alm.precios.get_candidatos("100")[0].id
    lid = _con_lista(alm, iid, 5000.0)
    d = cli.get(f"/api/insumos/{iid}?lista={lid}").json()
    assert d["insumo"]["precio"] == 5000.0


def test_post_insumos_importar_preview_calcula_contra_la_lista(tmp_path):
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    lid = _con_lista(alm, iid, 5000.0)
    r = cli.post("/api/insumos/importar/preview",
                 data={"lista_id": str(lid)},
                 files={"archivo": ("l.xlsx", _xlsx_upsert_100(6000.0), _XLSX)})
    assert r.status_code == 200, r.text
    c = r.json()["actualizar"][0]
    assert c["precio_actual"] == 5000.0    # de la lista NP, no de Principal (1000.0)


# ------------------------------------------------------------------------ escritura
def test_post_insumos_cambios_escribe_en_la_lista_no_en_principal(tmp_path):
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    lid = alm.precios.crear_lista("NP Calle 13")
    r = cli.post("/api/insumos/cambios", json={
        "cambios": [{"insumo_id": iid, "precio": 4200.0, "fuente": "ACTA NP"}],
        "lista_id": lid})
    assert r.status_code == 200 and r.json()["aplicados"] == 1
    assert alm.precios.get_insumo_por_id(iid, lista_id=lid).precio == 4200.0
    assert alm.precios.get_insumo_por_id(iid).precio == 1000.0   # Principal intacto


def test_post_insumos_crear_escribe_en_la_lista_no_en_principal(tmp_path):
    cli, alm = _cli(tmp_path)
    lid = alm.precios.crear_lista("NP Calle 13")
    r = cli.post("/api/insumos/crear", json={
        "codigo": "NP1", "nombre": "GEOTEXTIL NT 2500", "precio": 8000.0,
        "fuente": "ACTA NP", "lista_id": lid})
    assert r.status_code == 200, r.text
    assert alm.precios.get_candidatos("NP1", lista_id=lid)[0].precio == 8000.0
    assert alm.precios.get_candidatos("NP1")[0].sin_precio is True   # Principal sin tarifa


def test_post_insumos_importar_escribe_en_la_lista_no_en_principal(tmp_path):
    cli, alm = _cli(tmp_path)
    lid = alm.precios.crear_lista("NP Calle 13")
    r = cli.post("/api/insumos/importar",
                 data={"lista_id": str(lid)},
                 files={"archivo": ("l.xlsx", _xlsx_upsert_100(6000.0), _XLSX)})
    assert r.status_code == 200, r.text
    assert r.json()["actualizados"] == 1 and r.json()["errores"] == []
    assert alm.precios.get_candidatos("100", lista_id=lid)[0].precio == 6000.0
    assert alm.precios.get_candidatos("100")[0].precio == 1000.0   # Principal intacto


def test_post_corridas_queda_con_su_lista_precios_id(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    _con_apu(alm)
    lid = alm.precios.crear_lista("NP Calle 13")
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false",
                           "carpeta_id": str(obra["id"]), "lista_id": str(lid)},
                     files={"archivo": ("lic.xlsx", f, _XLSX)})
    assert r.status_code == 200, r.text
    cid = r.json()["id"]
    assert alm.corridas.get_corrida(cid).lista_precios_id == lid


def test_post_corridas_stream_queda_con_su_lista_precios_id(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    _con_apu(alm)
    lid = alm.precios.crear_lista("NP Calle 13")
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas/stream",
                     data={"turno": "DIURNO", "use_ai": "false",
                           "carpeta_id": str(obra["id"]), "lista_id": str(lid)},
                     files={"archivo": ("lic.xlsx", f, _XLSX)})
    assert r.status_code == 200, r.text
    metas = alm.corridas.listar_corridas()
    assert len(metas) == 1 and metas[0].lista_precios_id == lid
