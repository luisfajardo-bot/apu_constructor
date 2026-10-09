"""Los esquemas de salida estructurada que se le mandan a la IA tienen que ser
CERRADOS: la API rechaza con 400 cualquier objeto sin `additionalProperties: false`.

Pasó en producción (2026-10-09): `hipotesis` era un dict abierto y la composición
asistida respondía «additionalProperties: true is not supported» en cada intento.
"""
import pytest

from apu_tool.dominio import ai_assist, revision
from apu_tool.dominio.composicion import propuesta_desde_json


def _objetos(nodo, ruta="$"):
    if isinstance(nodo, dict):
        tipos = nodo.get("type")
        tipos = tipos if isinstance(tipos, list) else [tipos]
        if "object" in tipos:
            yield ruta, nodo
        for k, v in nodo.items():
            yield from _objetos(v, f"{ruta}.{k}")
    elif isinstance(nodo, list):
        for i, v in enumerate(nodo):
            yield from _objetos(v, f"{ruta}[{i}]")


@pytest.mark.parametrize("nombre,esquema", [
    ("composicion", ai_assist._ESQUEMA_COMPOSICION),
    ("barrido", revision._ESQUEMA_BARRIDO),
    ("profundo", revision._ESQUEMA_PROFUNDO),
])
def test_todo_objeto_del_esquema_es_cerrado(nombre, esquema):
    abiertos = [r for r, o in _objetos(esquema) if o.get("additionalProperties") is not False]
    assert abiertos == [], f"{nombre}: objetos sin additionalProperties:false en {abiertos}"


def _crudo(hipotesis):
    return {"componentes": [{
        "codigo": "100", "tipo": "insumo", "funcion": "material", "rendimiento": 1.0,
        "origen": "antecedente", "referencias": [], "hipotesis": hipotesis,
        "calculo": None, "justificacion": "j", "nivel_evidencia": "alto"}],
        "supuestos": [], "incertidumbre_declarada": 0.1, "justificacion": "j"}


def test_la_hipotesis_en_pares_se_lee_como_dict():
    p = propuesta_desde_json(_crudo([
        {"clave": "horas_jornada", "valor": 8},
        {"clave": "unidad_produccion", "valor": "m3/dia"},
        {"clave": "valor_m3", "valor": 180000},          # raíz monetaria: no entra
    ]))
    assert p.componentes[0].hipotesis == {"horas_jornada": 8, "unidad_produccion": "m3/dia"}
