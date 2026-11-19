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


MSG_SIN_SALDO = ("La cuenta de Anthropic del servidor no tiene saldo. Compra "
                 "créditos en console.anthropic.com (Plans & Billing) y vuelve a "
                 "intentar.")

# Un 400 por saldo agotado NO es un fallo pasajero que convenga reintentar: es
# configuración del servidor, igual que una credencial vencida, y hay que decirlo con
# el mismo detalle. Sin esto la API mandaba "Your credit balance is too low" —
# perfectamente accionable— y el usuario leía "Error interno", buscando en la
# aplicación un problema que estaba en la consola de Anthropic.
#
# Se mira el TEXTO porque la API no da un código propio para este caso: el estado es
# 400 y el tipo `invalid_request_error`, los mismos que un esquema mal armado (que sí
# es un bug nuestro). Es frágil a que Anthropic cambie la redacción, y por eso el
# degradado es seguro: si deja de coincidir, se vuelve al comportamiento de antes
# —mensaje genérico y traceback completo en el log—, no a un error peor.
_SENALES_SIN_SALDO = ("credit balance", "purchase credits", "plans & billing")


def sin_saldo(exc: BaseException) -> bool:
    """¿Este 400 es por saldo agotado, y no por un payload mal armado?"""
    if getattr(exc, "status_code", None) != 400:
        return False
    texto = str(getattr(exc, "message", "") or exc).lower()
    return any(s in texto for s in _SENALES_SIN_SALDO)


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
- `hipotesis` es el razonamiento productivo detrás del rendimiento, como lista de
  pares clave-valor (el valor siempre como texto): por ejemplo [{"clave": "horas_jornada", "valor": "8"},
  {"clave": "produccion_por_jornada", "valor": "96"},
  {"clave": "unidad_produccion", "valor": "m3/dia"}]. No se valida, se le muestra a un
  ingeniero de costos para que pueda discutir el criterio y no solo el número. Si el
  rendimiento viene copiado de un antecedente y no de una hipótesis propia, manda [].
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
                    # Pares y no un dict abierto: la salida estructurada exige objetos
                    # CERRADOS (un dict de claves libres da 400). `_hipotesis_desde`
                    # lo convierte en dict al leerlo; lo guardado y la UI no cambian.
                    "hipotesis": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"clave": {"type": "string"},
                                           "valor": {"type": "string"}},
                            "required": ["clave", "valor"],
                            "additionalProperties": False,
                        },
                    },
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
        # Sin minimum/maximum: la salida estructurada no los soporta (400). El
        # rango 0..1 lo promete el prompt y lo impone el parseo (composicion.py).
        "incertidumbre_declarada": {"type": "number"},
        "justificacion": {"type": "string"},
    },
    "required": ["componentes", "supuestos", "incertidumbre_declarada",
                 "justificacion"],
    "additionalProperties": False,
}


# --------------------------------------------------------------------- chat
# El chat de la mesa de composición (`dominio/composicion_chat.py`). Misma puerta al
# SDK que `componer`, misma traducción de errores; distinto contrato: una vuelta de
# un bucle de tool use, que termina en `{texto, cambios}`.
PROMPT_VERSION_CHAT = "chat/v2"   # se sube A MANO al tocar el prompt o los esquemas

_SISTEMA_CHAT = """\
Eres un ingeniero de costos de obra civil que ayuda a una persona a completar la
composición de un APU (análisis de precios unitarios) en una mesa de revisión. Con
cada mensaje recibes la ACTIVIDAD y la COMPOSICIÓN ACTUAL de la mesa (lo que la
persona ve en pantalla) y su instrucción.

Herramientas:
- `buscar_insumos(texto)`: busca en el catálogo por palabras del nombre. Devuelve
  código, nombre, unidad, grupo y con qué rendimientos aparece el insumo en la
  biblioteca.
- `buscar_apus(texto)`: busca APUs de la biblioteca parecidos, con su composición.
Busca con palabras cortas del nombre ("oficial", "soldador", "retroexcavadora"), no
con frases. `buscar_insumos` exige TODAS las palabras: una de más (un adjetivo como
"sanitaria" o "corrugada") deja afuera lo que buscas. Empieza con dos o tres palabras
esenciales y el diámetro como 12"; si trae pocos resultados (`encontrados` bajo), quita
palabras antes de concluir que no existe. Tienes un máximo de 4 búsquedas por mensaje:
no las gastes en `buscar_apus` si ya tienes un antecedente.

Reglas estrictas:
- Solo PROPONES cambios; la persona decide si los aplica. No digas que ya los
  aplicaste.
- Usa ÚNICAMENTE códigos que viste en un resultado de búsqueda o que ya están en la
  composición actual. No inventes códigos.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Los rendimientos son cantidades FÍSICAS por unidad de la actividad.
- `op`: "agregar" un insumo que no está; "modificar" uno que ya está (manda el
  componente completo con el cambio); "quitar" uno que está (`componente` en null).
- En `componente`, `origen` dice de dónde sale el rendimiento. Sé honesto:
  "copiado_de_antecedente" o "ajustado_de_antecedente" solo si sale de un APU que
  viste en `buscar_apus` (cítalo en `referencias`); "calculado_desde_produccion" si
  hiciste una cuenta (escríbela en `calculo`); "supuesto_tecnico" si es criterio;
  "sin_evidencia" si no tienes en qué apoyarte.
- `hipotesis` va como lista de pares clave-valor (el valor como texto), o [].
- Si la persona pregunta algo y no pide cambios, responde en `texto` y deja
  `cambios` vacío.
- `texto` es lo que lee la persona: corto, en español de Colombia y tuteando.

Responde EXCLUSIVAMENTE con un JSON válido con el esquema pedido.
"""

# El componente es EL MISMO de `componer`, acotado igual (tipo solo `insumo`, sin
# `sub_apu`): lo parsea el mismo `propuesta_desde_json`. Nullable porque `quitar` no
# lleva componente.
_COMPONENTE_ESQUEMA = _ESQUEMA_COMPOSICION["properties"]["componentes"]["items"]
OPS_CHAT = ("agregar", "modificar", "quitar")

_ESQUEMA_CHAT = {
    "type": "object",
    "properties": {
        "texto": {"type": "string"},
        "cambios": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "op": {"type": "string", "enum": list(OPS_CHAT)},
                    "codigo": {"type": "string"},
                    "componente": {**_COMPONENTE_ESQUEMA,
                                   "type": ["object", "null"]},
                },
                "required": ["op", "codigo", "componente"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["texto", "cambios"],
    "additionalProperties": False,
}


def _herramienta(nombre: str, descripcion: str, campo: str) -> dict:
    return {"name": nombre, "description": descripcion, "strict": True,
            "input_schema": {"type": "object",
                             "properties": {"texto": {"type": "string",
                                                      "description": campo}},
                             "required": ["texto"], "additionalProperties": False}}


HERRAMIENTAS_CHAT = [
    _herramienta("buscar_insumos",
                 "Busca insumos del catálogo por palabras de su nombre. Devuelve hasta "
                 "15 con código, nombre, unidad, grupo y los rendimientos con que "
                 "aparecen en la biblioteca. No devuelve precios.",
                 "Palabras cortas del nombre del insumo, p. ej. 'oficial soldador'."),
    _herramienta("buscar_apus",
                 "Busca APUs de la biblioteca parecidos a un texto. Devuelve hasta 5 "
                 "con su composición (insumos, unidades y rendimientos). No devuelve "
                 "precios.",
                 "Descripción corta de la actividad, p. ej. 'excavación manual'."),
]
MAX_TOKENS_CHAT = 16000


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
            if sin_saldo(exc):
                raise IANoDisponible(MSG_SIN_SALDO) from exc
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

    def turno_chat(self, mensajes: list, *, con_herramientas: bool):
        """UNA vuelta del bucle del chat. Devuelve la respuesta cruda del SDK.

        El bucle (ejecutar herramientas, cortar en el tope) vive en
        `dominio/composicion_chat.py`; acá solo se habla con el modelo y se traducen
        los errores de configuración, igual que en `componer`.

        `con_herramientas=False` apaga las herramientas con `tool_choice: none` SIN
        sacarlas de `tools`: el historial ya trae bloques `tool_use` que las nombran.
        No se usa `tool_choice` forzado: los modelos nuevos lo rechazan con 400.
        """
        if not self.enabled or self._client is None:
            if getattr(self, "_sdk_ausente", False):
                raise IANoDisponible(
                    "Conversar con el agente necesita el SDK de anthropic instalado "
                    "en el servidor.")
            raise IANoDisponible(
                "Conversar con el agente necesita ANTHROPIC_API_KEY en el servidor.")
        # FUERA del try, como en `componer`: el invariante #1 nunca se traga. Los
        # bloques del SDK (no-dict) no se recorren; lo que armamos nosotros, sí.
        privacy.assert_no_money(mensajes)
        try:
            return self._pedir_chat_al_sdk(mensajes, con_herramientas)
        except Exception as exc:
            if credencial_invalida(exc):
                raise IANoDisponible(MSG_CREDENCIAL) from exc
            if sin_saldo(exc):
                raise IANoDisponible(MSG_SIN_SALDO) from exc
            raise

    def _pedir_chat_al_sdk(self, mensajes: list, con_herramientas: bool):
        """La llamada pelada. Aparte para que los tests la sustituyan sin simular el
        cliente, igual que `_pedir_al_sdk`."""
        return self._client.messages.create(
            model=self.model,
            max_tokens=MAX_TOKENS_CHAT,
            system=_SISTEMA_CHAT,
            thinking={"type": "adaptive"},
            # `low`: una instrucción puntual no necesita el razonamiento de una
            # composición entera, y el pensamiento es la parte que domina el costo.
            output_config={"effort": "low",
                           "format": {"type": "json_schema", "schema": _ESQUEMA_CHAT}},
            tools=HERRAMIENTAS_CHAT,
            tool_choice={"type": "auto"} if con_herramientas else {"type": "none"},
            messages=mensajes,
            # Caché automática del prefijo: cada vuelta del bucle reenvía todo lo
            # anterior (sistema, herramientas, contexto, resultados), y esa parte se
            # cobra a 0,1x. En el smoke real el 94 % de los tokens era entrada.
            cache_control={"type": "ephemeral"},
        )
