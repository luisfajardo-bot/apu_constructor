"""Frontera de privacidad del chat de consulta."""
from types import SimpleNamespace

import pytest

from apu_tool.dominio import privacy


@pytest.mark.parametrize("texto", [
    "vale $45.000",
    "unos 45.000",
    "1,250,000 en total",
    "cerca de 3 millones",
    "como 200 mil",
    "45k",
    "en pesos colombianos 12",
    "USD 30",
])
def test_cifra_monetaria_ataja_las_senales_fuertes(texto):
    assert privacy.cifra_monetaria(texto)


@pytest.mark.parametrize("texto", [
    "El costo de la Calle 13 es ",                # número de proyecto junto a «costo»
    "Contractual de la corrida 12: ",
    "Tubería PVC de 6 pulgadas",
    "Concreto de 3000 psi",
    "Hay 3 coincidencias para «tubería»",
    "8 horas de cuadrilla, 4 kg de alambre",
    "3 milímetros",
])
def test_cifra_monetaria_deja_pasar_texto_normal_del_agente(texto):
    assert privacy.cifra_monetaria(texto) is None


def test_helpers_de_consulta_no_llevan_dinero():
    ins = SimpleNamespace(id=7, codigo="8001", nombre="TUBERIA PVC", unidad="ML",
                          grupo="MAT", precio=35000, fuente_precio="COSTO INTERNO")
    meta = SimpleNamespace(id=3, nombre="", archivo="calle13.xlsx",
                           estado="en_revision", modo="activa")
    salida = [privacy.insumo_consulta_to_dict(ins),
              privacy.apu_consulta_to_dict("A1", "MEZCLA", "DIURNO"),
              privacy.corrida_consulta_to_dict(meta, "CALLE 13"),
              privacy.capitulo_consulta_to_dict(3, "2", "REDES HUMEDAS", 4)]
    privacy.assert_no_money(salida)
    texto = privacy.safe_json(salida)
    assert "35000" not in texto and "COSTO INTERNO" not in texto
    assert [s["ref"] for s in salida] == [
        "insumo:7", "apu:A1|DIURNO", "corrida:3", "capitulo:3:2"]
    assert salida[2]["nombre"] == "calle13"          # sin alias: el archivo sin extensión


def test_calidades_con_alerta_cubre_los_cruces_que_alertan():
    from apu_tool.dominio.alertas import CALIDADES_CON_ALERTA, _MOTIVO_CRUCE
    from apu_tool.nucleo.models import CALIDAD_SIN_PRECIO_LISTA
    assert set(_MOTIVO_CRUCE) <= CALIDADES_CON_ALERTA
    assert CALIDAD_SIN_PRECIO_LISTA in CALIDADES_CON_ALERTA
    assert "exacto" not in CALIDADES_CON_ALERTA
