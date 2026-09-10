"""La fachada de IA de la composición: una llamada, contrato v2, degradado explícito.

No se llama a la API real: se sustituye `_pedir_al_sdk`, la ÚNICA puerta al SDK, con
el mismo truco que usan los tests de `revision.py`.
"""
import json
from types import SimpleNamespace

import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.ai_assist import PROMPT_VERSION, ApuAdvisor, IANoDisponible
from apu_tool.dominio.compose import CandidateInsumo, RendimientoObservado
from apu_tool.nucleo.models import DePricedApu, DePricedComponent, LicitacionItem

ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL", "M3", 120.0, 180000.0, "DIURNO")
INSUMOS = [CandidateInsumo("4279", "CUADRILLA", "HR", "MO")]
EJEMPLOS = [DePricedApu("A1", "UNO", "M3", "DIURNO", "EXCAVACIONES",
                        (DePricedComponent("4279", "CUADRILLA", "HR", 0.62),))]
OBS = {"4279": RendimientoObservado("4279", "HR", 14, 0.40, 0.62, 1.10)}

BUENA = {"componentes": [{"codigo": "4279", "tipo": "insumo",
                          "funcion": "mano_de_obra", "rendimiento": 0.62,
                          "origen": "copiado_de_antecedente",
                          "referencias": [{"apu_codigo": "A1", "turno": "DIURNO"}],
                          "hipotesis": {}, "calculo": None, "justificacion": "j",
                          "nivel_evidencia": "alto"}],
         "supuestos": [], "incertidumbre_declarada": 0.3, "justificacion": "g"}


class AdvisorFalso(ApuAdvisor):
    """Sustituye la única puerta al SDK. `texto` es lo que 'devuelve' el modelo."""

    def __init__(self, texto: str):
        self.enabled = True
        self._client = object()
        self.model = "falso"
        self.texto = texto
        self.contenido_enviado = None

    def _pedir_al_sdk(self, system, schema, contenido, effort):
        self.contenido_enviado = contenido
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.texto)])


def test_devuelve_una_propuesta_parseada():
    a = AdvisorFalso(json.dumps(BUENA))
    p = a.componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert len(p.componentes) == 1
    assert p.componentes[0].codigo == "4279"
    assert p.incertidumbre_declarada == 0.3


def test_no_le_manda_el_precio_contractual_al_modelo():
    a = AdvisorFalso(json.dumps(BUENA))
    a.componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert "180000" not in a.contenido_enviado


def test_revienta_antes_de_tocar_la_red_si_hay_dinero(monkeypatch):
    """La PrivacyViolation NO se traga: sale del try, como en revision.Revisor._pedir."""
    a = AdvisorFalso(json.dumps(BUENA))
    monkeypatch.setattr(privacy, "payload_composicion",
                        lambda *_a, **_k: {"actividad": {"precio_contractual": 1}})
    with pytest.raises(privacy.PrivacyViolation):
        a.componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert a.contenido_enviado is None      # nunca llegó al SDK


@pytest.mark.parametrize("texto", ["", "no soy json", "{", "[1,2]", '"ok"', "42",
                                   "{}", '{"componentes": []}'])
def test_una_respuesta_ilegible_o_vacia_da_propuesta_vacia_no_revienta(texto):
    p = AdvisorFalso(texto).componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert p.componentes == ()


def test_sin_credencial_levanta_ia_no_disponible():
    a = ApuAdvisor(enabled=False)
    with pytest.raises(IANoDisponible):
        a.componer(ITEM, INSUMOS, EJEMPLOS, OBS)


def test_sin_insumos_candidatos_levanta_valueerror():
    """No hay lista blanca: pedirle algo al modelo sería invitarlo a inventar."""
    with pytest.raises(ValueError):
        AdvisorFalso(json.dumps(BUENA)).componer(ITEM, [], EJEMPLOS, OBS)


def test_la_version_del_prompt_esta_declarada():
    assert PROMPT_VERSION.startswith("composicion/")


def test_un_401_del_sdk_se_convierte_en_ia_no_disponible():
    class Rota(AdvisorFalso):
        def _pedir_al_sdk(self, *a, **k):
            raise type("E", (Exception,), {"status_code": 401})()

    with pytest.raises(IANoDisponible):
        Rota("").componer(ITEM, INSUMOS, EJEMPLOS, OBS)


def test_un_429_del_sdk_no_se_confunde_con_falta_de_credencial():
    class Lenta(AdvisorFalso):
        def _pedir_al_sdk(self, *a, **k):
            raise type("E", (Exception,), {"status_code": 429})()

    with pytest.raises(Exception) as exc:
        Lenta("").componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert not isinstance(exc.value, IANoDisponible)


def test_el_esquema_declara_los_vocabularios_cerrados():
    """Si el esquema y el parser se desincronizan, el modelo puede mandar un valor
    que el esquema acepta y el parser degrada en silencio."""
    from apu_tool.dominio.ai_assist import _ESQUEMA_COMPOSICION
    from apu_tool.dominio.composicion import (
        FUNCIONES, NIVELES_EVIDENCIA, OPERACIONES, ORIGENES, TIPOS,
    )
    props = _ESQUEMA_COMPOSICION["properties"]["componentes"]["items"]["properties"]
    assert props["funcion"]["enum"] == list(FUNCIONES)
    assert props["origen"]["enum"] == list(ORIGENES)
    assert props["nivel_evidencia"]["enum"] == list(NIVELES_EVIDENCIA)
    assert props["tipo"]["enum"] == list(TIPOS)
    assert props["calculo"]["properties"]["operacion"]["enum"] == list(OPERACIONES)
