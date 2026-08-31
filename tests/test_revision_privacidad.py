"""La revisión también respeta el invariante #1: la IA nunca ve dinero."""
import pytest

from apu_tool.dominio import privacy, revision
from apu_tool.nucleo.models import (
    CorridaItemRow, DePricedApu, DePricedComponent, LicitacionItem,
)


def _fila(seq=0):
    return CorridaItemRow(
        seq=seq,
        item=LicitacionItem(item="1", descripcion="EXCAVACION MANUAL", unidad="M3",
                            cantidad=12.5, precio_contractual=999999, shift="DIURNO"),
        status="auto", apu_codigo="100", apu_nombre="EXCAVACION MANUAL", unidad="M3",
        shift="DIURNO", origen="historico", confianza=0.9, explicacion="",
        componentes=[], candidatos=[{"apu_codigo": "200", "apu_nombre": "EXCAVACION MECANICA",
                                     "score": 0.71, "motivo": ""}])


def _apu():
    return DePricedApu(
        codigo="100", nombre="EXCAVACION MANUAL", unidad="M3", shift="DIURNO",
        grupo="MOV",
        componentes=(DePricedComponent(insumo_codigo="4279", insumo_nombre="CUADRILLA",
                                       unidad="HR", rendimiento=1.0, tipo="insumo"),))


def test_payload_de_barrido_no_lleva_dinero():
    p = revision.payload_barrido(_fila())
    privacy.assert_no_money(p)            # no lanza
    texto = privacy.safe_json(p)
    assert "precio_contractual" not in texto
    assert "999999" not in texto


def test_payload_de_barrido_no_lleva_el_score_del_matcher():
    """Si le damos la nota del fuzzy, la copia en vez de pensar."""
    texto = privacy.safe_json(revision.payload_barrido(_fila()))
    assert "score" not in texto
    assert "0.71" not in texto


def test_indice_de_corrida_no_lleva_dinero():
    filas = [_fila(0), _fila(1)]
    idx = revision.indice_corrida(filas)
    privacy.assert_no_money(idx)
    texto = privacy.safe_json(idx)
    assert "999999" not in texto
    assert "score" not in texto
    assert [f["seq"] for f in idx] == [0, 1]


def test_payload_profundo_no_lleva_dinero():
    dp = _apu()
    p = revision.payload_profundo(_fila(), asignado=dp, candidatos=[dp])
    privacy.assert_no_money(p)
    assert "precio" not in privacy.safe_json(p).lower()


def test_un_precio_colado_revienta():
    p = revision.payload_barrido(_fila())
    p["actividad"]["costo_unitario"] = 12345
    with pytest.raises(privacy.PrivacyViolation):
        privacy.safe_json(p)


def test_veredicto_serializa_plano():
    v = revision.Veredicto(seq=3, dictamen="cambiar", apu_sugerido="200",
                           turno_sugerido="DIURNO", confianza=0.8,
                           justificacion="la actividad es mecanica", nivel="barrido")
    d = v.to_dict()
    privacy.assert_no_money(d)
    assert d["seq"] == 3 and d["dictamen"] == "cambiar"
    assert v.dictamen in revision.DICTAMENES
