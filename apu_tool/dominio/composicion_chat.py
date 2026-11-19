"""Chat con el agente en la mesa de composición.

Hermano de `composicion_agente.py`: el agente busca en el catálogo y PROPONE cambios a
la composición de una fila; la persona los aplica (el `PUT` de la mesa) o los
descarta. Acá no se persiste nada.

Dos piezas:
  - `Herramientas`: las búsquedas que el modelo puede pedir. Solo lectura, y todo lo
    que devuelven pasa por los helpers de `privacy` (copia campo por campo, sin
    precio) antes de volver al modelo.
  - `conversar`: el bucle de tool use, como generador de eventos SSE.
"""
from __future__ import annotations

import json
import logging
from dataclasses import replace

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import privacy
from apu_tool.dominio.ai_assist import OPS_CHAT, PROMPT_VERSION_CHAT, IANoDisponible
from apu_tool.dominio.compose import rendimientos_observados
from apu_tool.dominio.composicion import propuesta_desde_json
from apu_tool.dominio.matching import Matcher
from apu_tool.nucleo.relevancia import _tokens

logger = logging.getLogger(__name__)

MAX_RESULTADOS_INSUMOS = 15
MAX_RESULTADOS_APUS = 5


class Herramientas:
    """Las búsquedas del agente. Una instancia por mensaje: el `Matcher` se arma la
    primera vez que se pide `buscar_apus` y se reusa en las siguientes."""

    def __init__(self, almacen: Almacen, shift: str):
        self.alm = almacen
        self.shift = shift
        self._matcher = None

    def ejecutar(self, nombre: str, entrada: dict) -> dict:
        texto = str((entrada or {}).get("texto", "") or "")[:200]
        if nombre == "buscar_insumos":
            return self.buscar_insumos(texto)
        if nombre == "buscar_apus":
            return self.buscar_apus(texto)
        return {"error": f"Herramienta desconocida: {nombre}"}

    def buscar_insumos(self, texto: str) -> dict:
        if not [t for t in _tokens(texto) if len(t) >= 3]:
            return {"consulta": texto, "insumos": []}     # "de la": nada que buscar
        # La misma búsqueda del `BuscadorInsumo` de la mesa: AND de palabras, sin
        # ocultos, rankeada por relevancia, 2 consultas. NO `search_insumos_por_palabras`:
        # hace OR con LIMIT 60 sin orden ("tuberia pvc" casa 1451 insumos en el
        # catálogo real y se rankeaban 60 al azar) y es N+1.
        ordenados, _total = self.alm.precios.list_insumos(
            texto, limit=MAX_RESULTADOS_INSUMOS)
        obs = rendimientos_observados(self.alm, [i.codigo for i in ordenados])
        return {"consulta": texto,
                "insumos": [privacy.insumo_encontrado_to_dict(i, obs.get(i.codigo))
                            for i in ordenados]}

    def buscar_apus(self, texto: str) -> dict:
        if self._matcher is None:
            self._matcher = Matcher(self.alm.apus.apu_index())
        apus = []
        for c in self._matcher.candidates(texto, self.shift,
                                          top_n=MAX_RESULTADOS_APUS):
            dp = self.alm.apus.get_depriced_apu(c.apu_codigo, self.shift)
            if dp is not None:
                apus.append(privacy.depriced_apu_to_dict(dp))
        return {"consulta": texto, "apus": apus}
