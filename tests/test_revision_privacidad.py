"""La revisión también respeta el invariante #1: la IA nunca ve dinero."""
import pytest

from apu_tool.dominio import privacy, revision
from tests.test_revision_motor import _ClienteFalso
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


def test_payload_de_barrido_lleva_exactamente_estas_claves():
    """Conjunto EXACTO, no lista negra: muerde ante cualquier campo nuevo (el score,
    la confianza o la explicacion del matcher, o un monto con nombre no vetado)."""
    p = revision.payload_barrido(_fila())
    assert set(p) == {"seq", "actividad", "apu_asignado", "candidatos"}
    assert set(p["apu_asignado"]) == {"codigo", "nombre", "unidad", "shift"}
    assert set(p["candidatos"][0]) == {"codigo", "nombre"}


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
    for entrada in idx:
        assert set(entrada) == {"seq", "descripcion", "unidad", "apu"}


def test_payload_profundo_no_lleva_dinero():
    """Nada de buscar la subcadena "precio": un insumo real puede llamarse asi
    ("PRECIO IDU" es una fuente de este repo) y ademas pasaria si renombran la clave.
    Se afirma el conjunto EXACTO de claves, en el payload y en cada sub-dict."""
    dp = _apu()
    p = revision.payload_profundo(_fila(), asignado=dp, candidatos=[dp])
    privacy.assert_no_money(p)
    assert "999999" not in privacy.safe_json(p)
    assert set(p) == {"seq", "actividad", "apu_asignado", "candidatos"}
    for apu in [p["apu_asignado"], *p["candidatos"]]:
        assert set(apu) == {"codigo", "nombre", "unidad", "shift", "grupo",
                            "componentes"}
        for c in apu["componentes"]:
            assert set(c) == {"insumo_codigo", "insumo_nombre", "unidad",
                              "rendimiento", "tipo"}


def test_un_precio_colado_revienta():
    p = revision.payload_barrido(_fila())
    p["actividad"]["costo_unitario"] = 12345
    with pytest.raises(privacy.PrivacyViolation):
        privacy.safe_json(p)


def test_veredicto_serializa_plano():
    v = revision.Veredicto(seq=3, dictamen="cambiar", apu_sugerido="200",
                           turno_sugerido="DIURNO", confianza=0.8,
                           justificacion="la actividad es mecanica", nivel="barrido",
                           apu_evaluado="100")
    d = v.to_dict()
    privacy.assert_no_money(d)
    assert d["seq"] == 3 and d["dictamen"] == "cambiar"
    assert v.dictamen in revision.DICTAMENES


# --------------------------------------------- la frontera en la ruta REAL de `_pedir`
# Los demás tests sustituyen `_pedir` entero y dejan su cuerpo sin ejecutar; ahí vive
# `privacy.safe_json`, que es donde el invariante #1 se aplica en runtime. Estos dos
# corren `_pedir` de verdad contra un cliente falso: si alguien cambiara `safe_json`
# por `json.dumps`, muerden.
def test_pedir_no_le_manda_el_precio_contractual_al_cliente():
    c = _ClienteFalso('{"filas": []}')
    r = revision.Revisor(enabled=True)
    r._client = c
    r._pedir("sistema", {}, revision.payload_barrido(_fila()), "low")
    assert "999999" not in c.visto["messages"][0]["content"]
    assert "precio_contractual" not in c.visto["messages"][0]["content"]


def test_pedir_revienta_antes_de_llamar_al_cliente_si_hay_dinero():
    """Preferimos fallar a filtrar: la excepción sale ANTES de tocar la red."""
    c = _ClienteFalso('{"filas": []}')
    r = revision.Revisor(enabled=True)
    r._client = c
    payload = revision.payload_barrido(_fila())
    payload["actividad"]["costo_unitario"] = 12345
    with pytest.raises(privacy.PrivacyViolation):
        r._pedir("sistema", {}, payload, "low")
    assert c.llamadas == 0
