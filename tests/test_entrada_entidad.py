"""Registro entidad -> lector. Un diccionario, no una jerarquía de clases."""
import json

import openpyxl
import pytest

from apu_tool.dominio import entrada
from apu_tool.nucleo.models import EntidadOrigen
from tests.fixtures_idu import escribir_formulario


def test_el_enum_tiene_las_seis_entidades():
    assert {e.value for e in EntidadOrigen} == {
        "IDU", "METRO_BOGOTA", "INVIAS", "OTRA_PUBLICA", "PRIVADA", "NO_IDENTIFICADA"}


def test_el_enum_serializa_como_texto():
    # str, Enum como MatchStatus: sobrevive a asdict() y a json.dumps().
    assert json.dumps({"e": EntidadOrigen.IDU}) == '{"e": "IDU"}'


def test_parse_entidad_tolera_minusculas_y_espacios():
    assert entrada.parse_entidad("idu") is EntidadOrigen.IDU
    assert entrada.parse_entidad("  IDU  ") is EntidadOrigen.IDU
    assert entrada.parse_entidad("METRO_BOGOTA") is EntidadOrigen.METRO_BOGOTA


def test_parse_entidad_rechaza_lo_desconocido():
    # Valor estable, no texto libre: una entidad inventada es un error del llamador.
    # Si fuera silencioso, un typo mandaría un Formulario 1 por el importador genérico
    # y el usuario vería una corrida sin capítulos sin saber por qué.
    with pytest.raises(ValueError):
        entrada.parse_entidad("ALCALDIA DE CHIA")
    with pytest.raises(ValueError):
        entrada.parse_entidad("")


def test_todas_las_entidades_tienen_lector():
    # Si mañana se agrega una entidad al enum y se olvida el lector, esto falla acá y
    # no en producción con un KeyError.
    assert set(entrada.LECTORES) == set(EntidadOrigen)


def test_solo_idu_exige_confirmacion_hoy():
    assert entrada.requiere_confirmacion(EntidadOrigen.IDU) is True
    for otra in EntidadOrigen:
        if otra is not EntidadOrigen.IDU:
            assert entrada.requiere_confirmacion(otra) is False


def test_formato_de_distingue_idu_del_generico():
    assert entrada.formato_de(EntidadOrigen.IDU) == "idu_formulario_1"
    assert entrada.formato_de(EntidadOrigen.INVIAS) == "generico"


def test_idu_lee_el_formulario_1_con_capitulos(tmp_path):
    lec = entrada.leer(EntidadOrigen.IDU, escribir_formulario(tmp_path / "f1.xlsx"))
    assert len(lec.capitulos) == 2
    assert len(lec.items) == 5
    assert lec.errores == []


def _plana(path):
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO", "TURNO"])
    ws.append(["1", "EXCAVACION MANUAL", "M3", 10, 45000, "DIURNO"])
    wb.save(path)
    return path


def test_las_demas_entidades_usan_el_importador_generico(tmp_path):
    # Una lista plana normal: sin capítulos, sin conciliación, y NO se rompe.
    p = _plana(tmp_path / "plana.xlsx")
    for e in (EntidadOrigen.METRO_BOGOTA, EntidadOrigen.INVIAS,
              EntidadOrigen.OTRA_PUBLICA, EntidadOrigen.PRIVADA,
              EntidadOrigen.NO_IDENTIFICADA):
        lec = entrada.leer(e, p)
        assert lec.errores == [], e
        assert len(lec.items) == 1
        assert lec.capitulos == []
        assert lec.items[0].capitulo_codigo == ""


def test_el_generico_traduce_el_fallo_de_lectura_a_error(tmp_path):
    malo = tmp_path / "no-es.xlsx"
    malo.write_bytes(b"no soy un zip")
    lec = entrada.leer(EntidadOrigen.PRIVADA, malo)
    assert lec.items == []
    assert lec.errores != []


def test_el_generico_exige_turno_como_siempre(tmp_path):
    # `require_turno=True` es el comportamiento que la web ya tenía; no cambia.
    p = tmp_path / "sin_turno.xlsx"
    wb = openpyxl.Workbook()
    ws = wb.active
    ws.append(["ITEM", "DESCRIPCION", "UNIDAD", "CANTIDAD", "PRECIO"])
    ws.append(["1", "EXCAVACION MANUAL", "M3", 10, 45000])
    wb.save(p)
    lec = entrada.leer(EntidadOrigen.PRIVADA, p)
    assert lec.items == []
    assert any("turno" in e.lower() for e in lec.errores)
