"""
Capa de IA acotada para COMPONER la estructura de un APU, a pedido.

Qué hace la IA acá:
  - Para una actividad sin APU adecuado en la biblioteca, y SOLO cuando el usuario
    lo pide explícitamente (el orquestador `dominio/composicion_agente.py`), propone
    una composición: qué insumos, con qué rendimiento y POR QUÉ. Es una PROPUESTA;
    se confirma por el alta normal de APUs, nadie la costea a espaldas del usuario.

Qué NO hace la IA:
  - No participa del armado de corridas. El armado es determinístico (assemble.py):
    elige entre los APUs del histórico o deja la fila SIN APU, nunca inventa.
  - No ve precios, costos ni totales (ver privacy.py). Recibe únicamente
    actividades, insumos, unidades y rendimientos.
  - No calcula dinero. El costo lo arma el motor determinístico (pricing.py).

La auditoría de una corrida YA armada vive aparte, en `dominio/revision.py`.

Sin credenciales (ANTHROPIC_API_KEY) `componer` levanta `IANoDisponible` y el ítem
queda manual: el programa nunca depende de la IA para correr.
"""
from __future__ import annotations

import json
from typing import Optional

from apu_tool import config
from apu_tool.dominio import privacy
from apu_tool.dominio.composicion import (
    FUNCIONES, NIVELES_EVIDENCIA, OPERACIONES, ORIGENES, Propuesta,
    propuesta_desde_json,
)


class IANoDisponible(RuntimeError):
    """La IA no se puede usar por CONFIGURACIÓN del servidor: falta
    `ANTHROPIC_API_KEY`, falta el SDK, o la credencial que hay no sirve. Es distinto
    de "la IA no contestó" (un 429, un timeout, un JSON truncado): eso se reintenta,
    esto hay que ir a arreglarlo. Vive acá, en la fachada de la IA, porque las dos
    puertas al SDK la necesitan — `ApuAdvisor.componer` y `revision.Revisor._pedir`."""


MSG_CREDENCIAL = ("La credencial de la IA (ANTHROPIC_API_KEY) no es válida o fue "
                  "revocada: revísala en el servidor.")

# 401 = credencial inválida/revocada; 403 = sin permiso (p. ej. para este modelo).
# Se mira `status_code` y no la clase del SDK a propósito: `anthropic` es dependencia
# OPCIONAL y este módulo se importa siempre, así que no se puede hacer
# `except anthropic.AuthenticationError` sin volverla obligatoria.
_ESTADOS_DE_CREDENCIAL = (401, 403)


def credencial_invalida(exc: BaseException) -> bool:
    """¿Este fallo es de credencial, y no un 429/500/timeout que conviene tragarse?"""
    return getattr(exc, "status_code", None) in _ESTADOS_DE_CREDENCIAL


# Versión del prompt de composición. Se guarda con cada propuesta: sin esto, cuando el
# modelo empiece a proponer distinto no hay forma de saber si cambió el modelo o el
# prompt. Se sube A MANO al tocar `_SISTEMA_COMPOSICION` o `_ESQUEMA_COMPOSICION`.
PROMPT_VERSION = "composicion/v4"

_SISTEMA_COMPOSICION = """\
Eres un ingeniero de costos de obra civil. Te dan una ACTIVIDAD de licitación que no
tiene un APU adecuado en la biblioteca histórica, una lista cerrada de INSUMOS
DISPONIBLES (código, nombre, unidad, grupo), APUs DE REFERENCIA técnicamente cercanos
con su composición, y RENDIMIENTOS OBSERVADOS: con qué cantidades aparece cada insumo
en la biblioteca.

Tu tarea: proponer la composición del APU y EXPLICAR cada componente.

Reglas estrictas:
- Usa ÚNICAMENTE códigos de la lista de insumos disponibles. Un código que no esté ahí
  se rechaza entero: no inventes ninguno.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Los rendimientos son cantidades FÍSICAS por unidad de la actividad.
- En `rendimientos_observados`, `descartados_otra_unidad` cuenta filas del mismo
  insumo medidas en OTRA unidad, que quedaron fuera del rango. Un `n` alto con
  descartes altos es evidencia más débil de lo que parece.
- Cuando derives un rendimiento de una hipótesis de producción, escribe la fórmula en
  `calculo`: la aritmética la verifica un programa y su resultado manda sobre el tuyo;
  esfuérzate en la hipótesis, no en la cuenta.
- `hipotesis` es el razonamiento productivo detrás del rendimiento, en pares
  clave-valor: por ejemplo {"horas_jornada": 8, "produccion_por_jornada": 96,
  "unidad_produccion": "m3/dia"}. No se valida, se le muestra a un ingeniero de costos
  para que pueda discutir el criterio y no solo el número. Si el rendimiento viene
  copiado de un antecedente y no de una hipótesis propia, manda {}.
- `funcion` es el ROL del insumo dentro del APU, del vocabulario cerrado. No es el
  nombre de la actividad; eso va en `justificacion`.
- `origen` dice de dónde sale el rendimiento, y es lo que la plataforma usa para
  medir cuánto respaldo tiene la propuesta. Sé honesto:
  - "copiado_de_antecedente": lo tomaste igual de un APU de referencia. Cítalo.
  - "ajustado_de_antecedente": partiste de uno y lo moviste por una razón que
    explicas en `justificacion`. Cítalo igual. Si además hiciste una cuenta, usa
    este valor y manda igual el `calculo`.
  - "calculado_desde_produccion": lo derivaste de una hipótesis. Manda `calculo`.
  - "supuesto_tecnico": lo pusiste por criterio, sin antecedente ni cuenta. Declara
    el supuesto en `supuestos`.
  - "sin_evidencia": no tienes en qué apoyarte. Es una respuesta legítima y
    preferible a inventar un respaldo.
- `nivel_evidencia` es qué tan firme es ese respaldo: "alto" si el antecedente es
  directamente comparable, "medio" si hay que extrapolar, "bajo" si es analogía
  lejana.
- `referencias` solo puede citar APUs que estén en los de referencia que te dimos.
- Si algún dato que falta cambiaría materialmente la composición, decláralo en
  `supuestos` en vez de inventarlo en silencio: declararlos baja la confianza mucho
  menos que esconderlos.
- `incertidumbre_declarada`: 0 = no tienes ninguna duda, 1 = es pura conjetura. Es lo
  CONTRARIO de una confianza; no lo llenes como si fuera "qué tan seguro estás".
- Incluye típicamente mano de obra o equipo, herramienta y materiales según la
  actividad. Entre 2 y 12 componentes.

Responde EXCLUSIVAMENTE con un JSON válido con el esquema pedido.
"""

_ESQUEMA_COMPOSICION = {
    "type": "object",
    "properties": {
        "componentes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string"},
                    # En esta fase el enum es MÁS CORTO que el vocabulario del
                    # contrato, a propósito: la lista blanca solo lleva códigos de
                    # insumo (el retriever filtra los sub-APUs), así que `tipo="apu"`
                    # y `funcion="sub_apu"` son trampas — el validador los rechaza
                    # siempre. El contrato y el validador SÍ soportan sub-APUs; lo que
                    # falta es que la IA los proponga, y eso es la fase 3. Cuando
                    # llegue, esto vuelve a `list(TIPOS)` y `list(FUNCIONES)`.
                    "tipo": {"type": "string", "enum": ["insumo"]},
                    "funcion": {"type": "string",
                                "enum": [f for f in FUNCIONES if f != "sub_apu"]},
                    "rendimiento": {"type": "number"},
                    "origen": {"type": "string", "enum": list(ORIGENES)},
                    "referencias": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"apu_codigo": {"type": "string"},
                                           "turno": {"type": "string"}},
                            "required": ["apu_codigo", "turno"],
                            "additionalProperties": False,
                        },
                    },
                    "hipotesis": {"type": "object", "additionalProperties": True},
                    "calculo": {
                        "type": ["object", "null"],
                        "properties": {
                            "operacion": {"type": "string",
                                          "enum": list(OPERACIONES)},
                            "numerador": {"type": "number"},
                            "denominador": {"type": "number"},
                            "resultado": {"type": "number"},
                        },
                        "required": ["operacion", "numerador", "denominador",
                                     "resultado"],
                        "additionalProperties": False,
                    },
                    "justificacion": {"type": "string"},
                    "nivel_evidencia": {"type": "string",
                                        "enum": list(NIVELES_EVIDENCIA)},
                },
                "required": ["codigo", "tipo", "funcion", "rendimiento", "origen",
                             "referencias", "hipotesis", "calculo", "justificacion",
                             "nivel_evidencia"],
                "additionalProperties": False,
            },
        },
        "supuestos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"campo": {"type": "string"},
                               "supuesto": {"type": "string"},
                               "impacto": {"type": "string"}},
                "required": ["campo", "supuesto", "impacto"],
                "additionalProperties": False,
            },
        },
        "incertidumbre_declarada": {"type": "number", "minimum": 0, "maximum": 1},
        "justificacion": {"type": "string"},
    },
    "required": ["componentes", "supuestos", "incertidumbre_declarada",
                 "justificacion"],
    "additionalProperties": False,
}


class ApuAdvisor:
    """Fachada sobre la IA. Sin credenciales, `componer` levanta `IANoDisponible`."""

    def __init__(self, enabled: Optional[bool] = None, model: str = config.AI_MODEL):
        self.model = model
        self.enabled = config.ai_available() if enabled is None else enabled
        self._client = None
        # Dos causas de "no se puede", dos mensajes: sin este flag, un SDK no
        # instalado se reportaba como "falta ANTHROPIC_API_KEY" y mandaba a revisar
        # la variable equivocada. Mismo criterio que `Revisor._pedir`.
        self._sdk_ausente = False
        if self.enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception:
                self.enabled = False  # sin SDK -> componer levanta IANoDisponible
                self._sdk_ausente = True

    def componer(self, item, insumos, ejemplos, observados) -> Propuesta:
        """Una llamada al modelo con el contrato v2. Devuelve la propuesta PARSEADA.

        No valida nada: eso es de `dominio/validacion_composicion.py`, que además
        recalcula la aritmética. Acá solo se habla con el modelo y se lee lo que dijo.

        Una respuesta ilegible da una propuesta VACÍA, que el validador rechaza con
        `PROPUESTA_VACIA`. Nadie sale por válido por accidente — misma regla que
        `revision.Revisor.profundizar`, que degrada a "dudoso".
        """
        if not self.enabled or self._client is None:
            if getattr(self, "_sdk_ausente", False):
                raise IANoDisponible(
                    "Componer un APU con IA necesita el SDK de anthropic instalado "
                    "en el servidor.")
            raise IANoDisponible(
                "Componer un APU con IA necesita ANTHROPIC_API_KEY en el servidor.")
        if not insumos:
            # Sin lista blanca no hay nada entre lo que elegir: pedírselo igual sería
            # invitarlo a inventar códigos, que es lo único que el contrato prohíbe.
            raise ValueError("No hay insumos candidatos para esta actividad.")
        payload = privacy.payload_composicion(item, insumos, ejemplos, observados)
        # FUERA del try: el invariante #1 nunca se traga. Adentro, una PrivacyViolation
        # saldría por el `except` de abajo y el usuario leería "la IA no pudo componer"
        # mientras nadie se entera de que saltó el guardián. Mismo criterio que
        # `revision.barrer_lote`.
        contenido = privacy.safe_json(payload)
        try:
            resp = self._pedir_al_sdk(_SISTEMA_COMPOSICION, _ESQUEMA_COMPOSICION,
                                      contenido, "medium")
        except Exception as exc:
            if credencial_invalida(exc):
                raise IANoDisponible(MSG_CREDENCIAL) from exc
            raise
        if getattr(resp, "stop_reason", None) == "max_tokens":
            # Truncada, no vacía. Sin esto el usuario lee "la IA no propuso ningún
            # componente" y va a revisar la actividad, cuando el problema es el techo.
            raise RuntimeError(
                "La respuesta de la IA se cortó por longitud: vuelve a intentar o "
                "reduce la cantidad de insumos candidatos.")
        texto = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            data = json.loads(texto)
        except Exception:
            return Propuesta()   # JSON truncado: propuesta vacía, no una mentira
        return propuesta_desde_json(data)

    def _pedir_al_sdk(self, system: str, schema: dict, contenido: str, effort: str):
        """La llamada pelada al SDK. Aparte para que el `try` de arriba envuelva SOLO
        la red y no el parseo, y para que los tests la sustituyan sin simular el
        cliente de anthropic — el mismo patrón que `revision.Revisor`."""
        return self._client.messages.create(
            model=self.model,
            max_tokens=16000,        # techo, no gasto: cubre el pensamiento y el JSON
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": contenido}],
        )
