"""Persistencia de la clasificación de transporte de la biblioteca."""
from apu_tool.datos.apus_db import ApusDB
from apu_tool.nucleo.models import Apu, ApuComponent, ClaseTransporte


def _db(tmp_path):
    db = ApusDB(tmp_path / "apus.db")
    db.init_schema()
    db.insert_apus([Apu(codigo="4200", nombre="MEZCLA MD20", unidad="M3",
                        shift="DIURNO", grupo="PAVIMENTOS")])
    db.insert_components([
        ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                     insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=900.0),
        ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo="7172",
                     insumo_nombre="MEZCLA ASFALTICA MD20", unidad="M3",
                     rendimiento=1.0, precio_unitario_hist=500000.0),
    ])
    return db


def test_clasificacion_vacia_al_inicio(tmp_path):
    assert _db(tmp_path).get_clasificacion_transporte() == []


def test_upsert_y_lectura(tmp_path):
    db = _db(tmp_path)
    fila = ClaseTransporte(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                           insumo_nombre="TRANSPORTE DE BASES ASFALTICAS",
                           categoria="mezclas", volumen=1.05, km_base=25.0)
    assert db.set_clasificacion_transporte([fila], actualizado_por="yo@test.co") == 1
    leidas = db.get_clasificacion_transporte()
    assert len(leidas) == 1
    assert (leidas[0].categoria, leidas[0].volumen, leidas[0].km_base) == ("mezclas", 1.05, 25.0)
    # Reescribir la misma clave actualiza, no duplica.
    db.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", categoria="mezclas",
        volumen=1.30, km_base=20.0)])
    leidas = db.get_clasificacion_transporte()
    assert len(leidas) == 1 and leidas[0].volumen == 1.30


def test_candidatos_solo_las_filas_m3_km(tmp_path):
    db = _db(tmp_path)
    cands = db.componentes_transporte_candidatos()
    assert [c["insumo_codigo"] for c in cands] == ["6878"]
    c = cands[0]
    assert c["apu_codigo"] == "4200" and c["apu_nombre"] == "MEZCLA MD20"
    assert c["rendimiento"] == 26.25 and c["unidad"] == "M3-KM"


from apu_tool.datos.carpetas_db import CarpetasDB
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.nucleo.models import AjusteProyecto, ParametrosProyecto


def _carpetas(tmp_path):
    CorridasDB(tmp_path / "c.db").init_schema()      # crea el esquema compartido
    return CarpetasDB(tmp_path / "c.db")


def test_parametros_inexistentes_son_none(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Calle 13")
    assert car.get_parametros(cid) is None


def test_set_y_get_parametros(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Metro")
    car.set_parametros(ParametrosProyecto(
        carpeta_id=cid, km_botadero=34, km_mezclas=28, km_granulares=32,
        peaje_aplica=True, peaje_valor=12400), actualizado_por="yo@test.co")
    p = car.get_parametros(cid)
    assert (p.km_botadero, p.km_mezclas, p.km_granulares) == (34, 28, 32)
    assert p.peaje_aplica is True and p.peaje_valor == 12400
    assert p.actualizado_en and p.actualizado_por == "yo@test.co"
    # Reescribir actualiza, no duplica.
    car.set_parametros(ParametrosProyecto(carpeta_id=cid, km_botadero=21,
                                         peaje_aplica=False))
    p = car.get_parametros(cid)
    assert p.km_botadero == 21 and p.peaje_aplica is False and p.km_mezclas is None


def test_crud_de_ajustes(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Metro")
    assert car.listar_ajustes(cid) == []
    aid = car.crear_ajuste(AjusteProyecto(
        carpeta_id=cid, apu_codigo="4390", shift="DIURNO", accion="agregar",
        insumo_codigo="9001", insumo_nombre="GEOTEXTIL NT 2000", unidad="M2",
        rendimiento=1.1, nota="lo exige la especificación"), creado_por="yo@test.co")
    ajustes = car.listar_ajustes(cid)
    assert len(ajustes) == 1 and ajustes[0].id == aid
    assert ajustes[0].accion == "agregar" and ajustes[0].rendimiento == 1.1
    assert car.borrar_ajuste(cid, aid) is True
    assert car.listar_ajustes(cid) == []
    assert car.borrar_ajuste(cid, aid) is False


def test_borrar_la_carpeta_borra_sus_parametros_y_ajustes(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Temporal")
    car.set_parametros(ParametrosProyecto(carpeta_id=cid, km_botadero=30))
    car.crear_ajuste(AjusteProyecto(carpeta_id=cid, apu_codigo="1", shift="DIURNO",
                                    accion="quitar", insumo_codigo="9",
                                    insumo_nombre="X"))
    assert car.eliminar(cid) is True
    assert car.get_parametros(cid) is None and car.listar_ajustes(cid) == []


def test_reeditar_un_ajuste_conserva_su_id(tmp_path):
    """Guardar dos veces el mismo ajuste actualiza la fila y DEVUELVE EL MISMO id: un
    id nuevo dejaria colgado el que la UI ya tiene (y su borrado fallaria callado)."""
    car = _carpetas(tmp_path)
    cid = car.crear("Metro")
    def _aj(rend):
        return AjusteProyecto(carpeta_id=cid, apu_codigo="4390", shift="DIURNO",
                              accion="rendimiento", insumo_codigo="6722",
                              insumo_nombre="SUBBASE GRANULAR B-400", rendimiento=rend)
    primero = car.crear_ajuste(_aj(1.1))
    segundo = car.crear_ajuste(_aj(1.25))
    assert primero == segundo
    ajustes = car.listar_ajustes(cid)
    assert len(ajustes) == 1 and ajustes[0].rendimiento == 1.25
    assert car.borrar_ajuste(cid, primero) is True


def test_candidatos_tolera_una_unidad_escrita_distinto(tmp_path):
    """La regla de costeo normaliza la unidad (colapsa el guion), asi que la pantalla
    de clasificacion tiene que ver las mismas filas: si no, esa fila alerta como "sin
    clasificar" y no hay forma de resolverla."""
    db = _db(tmp_path)
    db.insert_components([
        ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="m3 - km",
                     rendimiento=26.25, precio_unitario_hist=1000.0)])
    codigos = [c["insumo_codigo"] for c in db.componentes_transporte_candidatos()]
    assert codigos == ["6878", "7462"]


def test_reset_borra_la_clasificacion_igual_que_postgres(tmp_path):
    """`seed --force` (reset_catalogo) tiene que dejar la misma foto en los dos
    backends: ApusPg.reset() hace DROP SCHEMA CASCADE, que se lleva la tabla."""
    db = _db(tmp_path)
    db.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", categoria="mezclas",
        volumen=1.05, km_base=25.0)])
    assert len(db.get_clasificacion_transporte()) == 1
    db.reset()
    assert db.get_clasificacion_transporte() == []
