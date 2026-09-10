"""Persistencia de la composición: append-only por versión, en los dos backends.

Este archivo prueba SQLite. La paridad con Postgres la fija
`tests/test_composiciones_paridad.py` (tarea 8) con los mismos casos.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.datos.repositorio import VersionYaExiste
from apu_tool.nucleo.models import ComposicionRow


def fila(**kw) -> ComposicionRow:
    base = dict(
        id=None, corrida_id=1, seq=7, version=1, estado="propuesta",
        actividad={"item": "1.3", "descripcion": "EXCAVACION", "unidad": "M3",
                   "cantidad": 120.0, "shift": "DIURNO"},
        ficha=None,
        propuesta={"componentes": [{"codigo": "4279", "rendimiento": 0.62}],
                   "supuestos": [], "incertidumbre_declarada": 0.3,
                   "justificacion": "g"},
        validacion={"valido": True, "errores": [], "advertencias": [],
                    "metricas": {"superadas": 9, "totales": 9}},
        confianza="alta",
        confianza_motivos=[{"senal": "respaldo_de_componentes", "detalle": "1 de 1",
                            "aporte": 2}],
        antecedentes={"codigos_permitidos": ["4279"], "apus_referencia": ["A1"]},
        modelo="claude-sonnet-5", prompt_version="composicion/v3",
        apu_codigo=None, apu_turno=None, autor="luis@test.co",
        creada_en="2026-09-10T10:00:00", motivo=None)
    base.update(kw)
    return ComposicionRow(**base)


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.init_schema()
    # Las corridas se crean de verdad: `composicion.corrida_id` tiene FK con CASCADE,
    # igual que `corrida_item`, así que un id inventado no falla por la lógica de
    # versiones sino por falta de fila padre — y ese caso tiene su propio test.
    # Quedan con id 1 y 2 (AUTOINCREMENT arranca en 1), que es lo que usan las filas.
    from apu_tool.nucleo.models import CorridaMeta
    for _ in range(2):
        a.corridas.crear_corrida(CorridaMeta(
            id=None, creada_en="2026-09-10T09:00:00", archivo="lic.xlsx",
            turno_def="DIURNO", use_ai=False, estado="en_revision"))
    return a


def test_guarda_y_recupera_la_vigente(alm):
    alm.composiciones.agregar(fila())
    v = alm.composiciones.vigente(1, 7)
    assert v is not None
    assert v.version == 1
    assert v.estado == "propuesta"
    assert v.propuesta["componentes"][0]["codigo"] == "4279"
    assert v.confianza == "alta"
    assert v.modelo == "claude-sonnet-5"
    assert v.prompt_version == "composicion/v3"


def test_la_vigente_es_la_de_mayor_version(alm):
    alm.composiciones.agregar(fila(version=1, estado="propuesta"))
    alm.composiciones.agregar(fila(version=2, estado="editada"))
    assert alm.composiciones.vigente(1, 7).estado == "editada"


def test_el_historial_viene_en_orden(alm):
    for n, est in enumerate(("propuesta", "editada", "aprobada"), start=1):
        alm.composiciones.agregar(fila(version=n, estado=est))
    assert [f.estado for f in alm.composiciones.historial(1, 7)] == [
        "propuesta", "editada", "aprobada"]


def test_repetir_una_version_choca(alm):
    """La protección del doble clic es el índice único, no un if."""
    alm.composiciones.agregar(fila(version=1))
    with pytest.raises(VersionYaExiste):
        alm.composiciones.agregar(fila(version=1, estado="aprobada"))


def test_sin_composicion_la_vigente_es_none(alm):
    assert alm.composiciones.vigente(1, 99) is None
    assert alm.composiciones.historial(1, 99) == []


def test_cada_fila_es_de_su_corrida_y_su_seq(alm):
    alm.composiciones.agregar(fila(corrida_id=1, seq=7))
    alm.composiciones.agregar(fila(corrida_id=1, seq=8))
    alm.composiciones.agregar(fila(corrida_id=2, seq=7))
    assert alm.composiciones.vigente(1, 8).seq == 8
    assert alm.composiciones.vigente(2, 7).corrida_id == 2


def test_los_campos_opcionales_aceptan_none(alm):
    alm.composiciones.agregar(fila(ficha=None, propuesta=None, validacion=None,
                                   confianza=None, confianza_motivos=None,
                                   antecedentes=None, estado="error",
                                   motivo="la IA no contestó"))
    v = alm.composiciones.vigente(1, 7)
    assert v.estado == "error" and v.motivo == "la IA no contestó"
    assert v.propuesta is None and v.confianza_motivos is None


def test_la_aprobada_guarda_el_apu_creado(alm):
    alm.composiciones.agregar(fila(estado="aprobada", apu_codigo="9001",
                                   apu_turno="DIURNO"))
    v = alm.composiciones.vigente(1, 7)
    assert (v.apu_codigo, v.apu_turno) == ("9001", "DIURNO")


def test_la_fila_persistida_no_lleva_dinero(alm):
    """Toda la fila es reinyectable en un payload: por eso `actividad` guarda la
    vista des-monetizada y no el LicitacionItem crudo."""
    from apu_tool.dominio import privacy
    alm.composiciones.agregar(fila())
    privacy.assert_no_money(alm.composiciones.vigente(1, 7).to_dict())


def test_no_hay_columna_para_el_razonamiento_del_modelo(alm):
    """No se guarda cadena de pensamiento: criterio 36."""
    from dataclasses import fields
    nombres = {f.name for f in fields(ComposicionRow)}
    assert not (nombres & {"thinking", "razonamiento", "pensamiento", "reasoning"})


def test_una_corrida_borrada_no_se_reporta_como_choque_de_version(alm):
    """Las dos violaciones son IntegrityError pero significan cosas distintas: un
    choque de versión manda al usuario a buscar un conflicto de edición, y acá lo
    que pasó es que la corrida ya no está."""
    from apu_tool.datos.repositorio import CorridaEliminada
    with pytest.raises(CorridaEliminada):
        alm.composiciones.agregar(fila(corrida_id=9999))
