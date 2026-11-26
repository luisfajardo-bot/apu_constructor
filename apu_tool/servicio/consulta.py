"""Chat de consulta, el lado CON dinero: reemplaza los marcadores que escribió la IA
por las cifras reales. Nada de lo que pasa acá vuelve al modelo.

Las cifras salen de las MISMAS funciones de la pantalla (`vista_corrida`, que usa
`resumen_por_capitulo`, y `PricingEngine`): es la única forma de que el chat diga el
mismo número que la corrida. Sumar acá sería la tercera suma que `resumen_por_capitulo`
existe para evitar. Spec: docs/superpowers/specs/2026-11-25-chat-consulta-design.md
"""
from __future__ import annotations

import logging
import math
import re
from decimal import ROUND_HALF_UP, Decimal

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import consulta_chat
from apu_tool.dominio.consulta_chat import ApuAdvisor, IANoDisponible
from apu_tool.dominio.alertas import CALIDADES_CON_ALERTA
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.servicio.corridas import vista_corrida

logger = logging.getLogger(__name__)

NO_DISPONIBLE = "[cifra no disponible]"
_RESTO = re.compile(r"\{\{[^{}]*\}{0,2}")   # marcador fuera de la lista cerrada: nunca llaves crudas
SIN_PRECIO = "sin precio en la lista Principal"
MAX_CORRIDAS_POR_RESPUESTA = 5
# Corridas leídas con el lector viejo del IDU: su contractual LLEVA AIU (antes del
# 2026-11-25 el IDU se leía así). El costo interno es costo directo, así que esas
# cifras se marcan para que nadie las compare sin darse cuenta. Spec:
# docs/superpowers/specs/2026-11-25-contractual-sin-aiu-design.md
PARSER_CON_AIU = "idu-f1/1"
CON_AIU = " (con AIU)"
# Marcador → clave en la vista. Ojo: en `totales` la diferencia en pesos se llama
# `margen` y el porcentaje `margen_pct`; en los capítulos, `diferencia` y `margen_pct`.
_CAMPOS_CORRIDA = {"contractual": "contractual", "costo": "costo",
                   "diferencia": "margen", "margen": "margen_pct"}
_CAMPOS_CAPITULO = {"contractual": "contractual", "costo": "costo",
                    "diferencia": "diferencia", "margen": "margen_pct"}


def pesos(v: float) -> str:
    """Como `web/src/lib/moneda.ts`, redondeando medio hacia arriba (regla del repo)."""
    n = math.floor(v + 0.5)                       # semántica de Math.round
    return "$" + f"{n:,}".replace(",", ".")


def pct(v: float) -> str:
    """Como `pct` de `web/src/lib/moneda.ts` («12.3%»): el chat dice lo que dice la pantalla."""
    q = Decimal((v or 0) * 100).quantize(Decimal("0.1"), rounding=ROUND_HALF_UP)
    return f"{q}%"


def _fmt(campo: str, v: float) -> str:
    return pct(v) if campo == "margen" else pesos(v)


def _costeada(it: dict) -> bool:
    """La regla de `report_categorizado._costeada`, sobre la fila de la vista."""
    return bool(it.get("apu_codigo")) or (it.get("costo_unitario") or 0) > 0


def _nota_aiu(v: dict, campo: str) -> str:
    """« (con AIU)» en contractual, diferencia y margen de una corrida vieja del IDU.
    `v["origen"]` es `origen_json` ya parseado, o None (corrida plana)."""
    if campo == "costo":
        return ""
    return CON_AIU if (v.get("origen") or {}).get("parser_version") == PARSER_CON_AIU         else ""


class _Resolutor:
    """Una instancia por respuesta: memo de `vista_corrida` (varios marcadores de la
    misma corrida comparten la vista) y un `PricingEngine` compartido."""

    def __init__(self, alm: Almacen):
        self.alm = alm
        self._vistas: dict[int, dict | None] = {}
        self._pricing: PricingEngine | None = None

    def vista(self, cid: int):
        if cid not in self._vistas:
            # Cada corrida distinta es un `vista_corrida` completo (y egress de
            # Supabase): más de MAX_CORRIDAS_POR_RESPUESTA salen «no disponible».
            if len(self._vistas) >= MAX_CORRIDAS_POR_RESPUESTA:
                return None
            self._vistas[cid] = None    # antes de llamar: si falla, igual cuenta y no se repite
            self._vistas[cid] = vista_corrida(self.alm, cid)
        return self._vistas[cid]

    def cifra(self, campo: str, tipo: str, ident: str) -> str:
        if tipo == "insumo" and campo == "precio":
            return self._insumo(ident)
        if tipo == "apu" and campo == "costo":
            return self._apu(ident)
        if tipo == "corrida" and campo in _CAMPOS_CORRIDA:
            return self._corrida(campo, ident)
        if tipo == "capitulo" and campo in _CAMPOS_CAPITULO:
            return self._capitulo(campo, ident)
        return NO_DISPONIBLE

    def _insumo(self, ident: str) -> str:
        try:
            iid = int(ident)
        except ValueError:
            return NO_DISPONIBLE                       # id ilegible: no es un error
        ins = self.alm.precios.get_insumo_por_id(iid)   # lista Principal
        if ins is None:
            return NO_DISPONIBLE
        if ins.sin_precio or not ins.precio > 0:     # regla "nada en $0"
            return SIN_PRECIO
        return pesos(ins.precio)

    def _apu(self, ident: str) -> str:
        codigo, _, turno = ident.rpartition("|")
        codigo, turno = codigo.strip(), turno.strip()
        if not codigo:
            return NO_DISPONIBLE
        if self._pricing is None:
            self._pricing = PricingEngine(self.alm)            # lista Principal
        costeados, total = self._pricing.cost_apu(codigo, turno.upper())
        if not costeados:
            return NO_DISPONIBLE
        malos = sum(1 for c in costeados
                    if c.costo <= 0 or c.calidad_cruce in CALIDADES_CON_ALERTA)
        if total <= 0:
            return "sin costo: sus componentes no tienen precio"
        nota = (f" (revisar: {malos} de {len(costeados)} componentes con alerta de "
                "costeo)") if malos else ""
        return pesos(total) + nota

    @staticmethod
    def _nota_armado(v: dict) -> str:
        a = v.get("armado")
        return (f" (parcial: armado {a['hechos']} de {a['total']} actividades)"
                if a else "")

    def _corrida(self, campo: str, ident: str) -> str:
        try:
            cid = int(ident)
        except ValueError:
            return NO_DISPONIBLE
        v = self.vista(cid)
        if v is None:
            return NO_DISPONIBLE
        if not v["items"]:                             # regla "nada en $0"
            return "sin actividades"
        s = _fmt(campo, v["totales"][_CAMPOS_CORRIDA[campo]]) + _nota_aiu(v, campo)
        nota = self._nota_armado(v)
        if not nota and campo != "contractual":
            items = v["items"]
            hechas = sum(1 for it in items if _costeada(it))
            if hechas < len(items):
                nota = f" (parcial: {hechas} de {len(items)} actividades costeadas)"
            elif v["totales"].get("n_alertas_costeo"):
                # Mismo criterio que el capítulo: filas con APU pero con algún
                # componente en $0 o con cruce dudoso.
                nota = " (con alertas de costeo)"
        return s + nota

    def _capitulo(self, campo: str, ident: str) -> str:
        cid, _, cod = ident.partition(":")
        cid, cod = cid.strip(), cod.strip()
        try:
            cid = int(cid)
        except ValueError:
            return NO_DISPONIBLE
        v = self.vista(cid)
        if v is None:
            return NO_DISPONIBLE
        cap = next((c for c in v["capitulos"] if c["codigo"] == cod), None)
        if cap is None:
            return NO_DISPONIBLE
        s = _fmt(campo, cap[_CAMPOS_CAPITULO[campo]]) + _nota_aiu(v, campo)
        nota = self._nota_armado(v)
        if not nota and campo != "contractual":
            if cap["sin_apu"]:
                nota = (f" (parcial: {cap['con_apu']} de {cap['actividades']} "
                        "actividades costeadas)")
            elif not cap["completo"]:
                nota = " (con alertas de costeo)"
        return s + nota


def resolver(alm: Almacen, texto: str) -> str:
    """`texto` con cada marcador reemplazado por su cifra. Un marcador que no se puede
    resolver sale como NO_DISPONIBLE: nunca se adivina ni se acerca a otro."""
    r = _Resolutor(alm)

    def uno(m) -> str:
        try:
            return r.cifra(m.group(1).lower(), m.group(2).lower(), m.group(3).strip())
        except Exception:
            logger.exception("No se pudo resolver el marcador %s", m.group(0))
            return NO_DISPONIBLE

    return _RESTO.sub(NO_DISPONIBLE, consulta_chat.MARCADOR.sub(uno, texto or ""))


def _con_cifras(alm: Almacen, eventos):
    for evento, payload in eventos:
        if evento == "respuesta":
            payload = dict(payload, texto=resolver(alm, payload["crudo"]))
        yield evento, payload


def chat_stream(alm: Almacen, datos: dict):
    """El generador SSE del chat de consulta. Lanza IANoDisponible (503) ANTES de
    abrir el stream. No persiste nada."""
    if not config.ai_available():
        raise IANoDisponible(
            "Consultar al agente necesita ANTHROPIC_API_KEY en el servidor.")
    return _con_cifras(alm, consulta_chat.conversar(
        alm, datos.get("mensajes") or [], ApuAdvisor()))
