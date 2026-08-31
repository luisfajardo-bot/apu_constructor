"""
Revisión con IA de una corrida YA armada.

La IA no arma: audita. Recibe la corrida completa (sin dinero) y dice, por fila, si
el APU asignado le parece bien, dudoso, cambiable por otro candidato, o si para esa
actividad no hay nada en la biblioteca. **Propone; nunca aplica.** Quien aplica es
el usuario, con `confirmar_items`.

Dos pasos, por costo y por foco. Cada paso tiene su PROPIO vocabulario, a propósito:
  1. BARRIDO   — lotes de filas, sin composiciones. Cada lote lleva además el índice
                 de la corrida entera, así la IA ve el presupuesto como un todo y
                 puede detectar incoherencias entre líneas. Devuelve `ok | revisar`:
                 es un TRIAJE, no un veredicto — solo decide a quién vale la pena
                 mirarle la composición. Por eso `revisar` NO está en `DICTAMENES`.
  2. PROFUNDIZACIÓN — solo las marcadas `revisar`. Una llamada por fila, ahora con la
                 composición completa (insumos, rendimientos, unidades) del APU
                 asignado y de cada candidato. Devuelve el VEREDICTO final, ese sí
                 del vocabulario `DICTAMENES` (ok | dudoso | cambiar | sin_apu).

Invariante #1: todo lo que sale de acá pasa por `privacy.safe_json`. En particular
NO va el `precio_contractual` del ítem (lo omite `licitacion_item_to_dict`) ni el
`score` del matcher: darle la nota del fuzzy hace que la copie en vez de pensar.

Sin `ANTHROPIC_API_KEY` no hay fallback determinístico, a propósito: un revisor
determinístico sería el matcher auditándose a sí mismo.
"""
from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from typing import Any, Iterator, Optional

from apu_tool import config
from apu_tool.dominio import privacy
from apu_tool.nucleo.models import CorridaItemRow, DePricedApu

# Filas por llamada del barrido. Bajarlo mejora el foco de la IA y sube el costo;
# subirlo hace lo contrario. Es la palanca si al barrido se le escapan objeciones.
TAM_LOTE = 25

# Vocabulario del VEREDICTO final (paso 2). El del barrido es otro (`ok | revisar`)
# y no se mezclan: "revisar" tría, nunca dictamina.
DICTAMENES = ("ok", "dudoso", "cambiar", "sin_apu")


@dataclass(frozen=True)
class Veredicto:
    seq: int
    dictamen: str                    # ok | dudoso | cambiar | sin_apu
    apu_sugerido: Optional[str]
    turno_sugerido: Optional[str]
    confianza: float
    justificacion: str
    nivel: str                       # barrido | profundo

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ payloads
def payload_barrido(fila: CorridaItemRow) -> dict[str, Any]:
    """Una fila para el barrido: sin composiciones y SIN el score del matcher."""
    return {
        "seq": fila.seq,
        "actividad": privacy.licitacion_item_to_dict(fila.item),
        "apu_asignado": (None if not fila.apu_codigo else {
            "codigo": fila.apu_codigo,
            "nombre": fila.apu_nombre,
            "unidad": fila.unidad,
            "shift": fila.shift,
        }),
        # Los candidatos de la fila vienen del matcher y traen `score`/`motivo`:
        # se copian clave por clave, nunca en bloque.
        "candidatos": [{"codigo": c.get("apu_codigo"), "nombre": c.get("apu_nombre")}
                       for c in (fila.candidatos or [])],
    }


def indice_corrida(filas: list[CorridaItemRow]) -> list[dict[str, Any]]:
    """El presupuesto entero en una línea por ítem: contexto para ver incoherencias
    entre filas (dos actividades gemelas con APUs distintos)."""
    return [{"seq": f.seq, "descripcion": f.item.descripcion,
             "unidad": f.unidad, "apu": f.apu_codigo or None} for f in filas]


def payload_profundo(fila: CorridaItemRow, asignado: Optional[DePricedApu],
                     candidatos: list[DePricedApu]) -> dict[str, Any]:
    """Una fila con TODA la estructura: composiciones del asignado y de cada candidato.

    Los APUs entran como `DePricedApu` porque es un tipo que ESTRUCTURALMENTE no
    puede llevar dinero: la frontera está en el tipo, no en acordarse de filtrar
    campos. (`CorridaItemRow.componentes` tampoco trae precios; la que sí los lleva
    es la vista de la API en `servicio/corridas.py`, que no entra acá.)
    """
    return {
        "seq": fila.seq,
        "actividad": privacy.licitacion_item_to_dict(fila.item),
        "apu_asignado": (None if asignado is None
                         else privacy.depriced_apu_to_dict(asignado)),
        "candidatos": [privacy.depriced_apu_to_dict(a) for a in candidatos],
    }


# ------------------------------------------------------------------- revisor
class IANoDisponible(RuntimeError):
    """No hay ANTHROPIC_API_KEY (o falta el SDK). La revisión no tiene fallback:
    un revisor determinístico sería el matcher auditándose a sí mismo."""


_SISTEMA_BARRIDO = """\
Eres un ingeniero de costos de obra civil auditando un presupuesto YA armado por un
programa determinístico. Para cada ACTIVIDAD te dan el APU que el programa le asignó
y los candidatos que descartó. Además recibes el ÍNDICE de todo el presupuesto.

Tu tarea: decir por cada fila si el APU asignado es razonable ("ok") o si merece un
análisis a fondo ("revisar").

Marca "revisar" cuando:
- la unidad del APU no cuadra con la de la actividad;
- el tipo de trabajo difiere (manual vs mecánico, suministro vs instalación);
- la actividad no tiene APU asignado;
- dos filas del índice describen la misma actividad pero tienen APUs distintos;
- un candidato descartado encaja claramente mejor que el asignado.

Reglas:
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Responde por TODAS las filas del lote, usando su `seq` exacto.
- Ante la duda, marca "revisar": el paso siguiente mira a fondo y corrige.

Responde EXCLUSIVAMENTE con un JSON válido con este esquema:
{"filas": [{"seq": <int>, "resultado": "ok"|"revisar"}]}
"""

_ESQUEMA_BARRIDO = {
    "type": "object",
    "properties": {
        "filas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seq": {"type": "integer"},
                    "resultado": {"type": "string", "enum": ["ok", "revisar"]},
                },
                "required": ["seq", "resultado"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["filas"],
    "additionalProperties": False,
}


_SISTEMA_PROFUNDO = """Eres un ingeniero de costos de obra civil auditando UNA línea de un presupuesto ya
armado. Te dan la ACTIVIDAD, el APU que se le asignó con su composición completa
(insumos, unidades y rendimientos) y los APUs candidatos con la suya.

Tu tarea: decidir cuál de estos cuatro dictámenes corresponde.
- "ok": el APU asignado es el correcto para esta actividad.
- "dudoso": no puedes decidir con lo que tienes; alguien tiene que mirarlo.
- "cambiar": otro de los candidatos es claramente mejor. Devuelve su código en
  `apu_sugerido` — SOLO códigos que estén en la lista de candidatos.
- "sin_apu": ninguno sirve; para esta actividad no hay nada adecuado en la biblioteca.

Reglas:
- Decides por afinidad técnica: unidad, tipo de trabajo, e insumos y rendimientos de
  la composición.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- NUNCA inventes un código de APU. Si el que quieres no está entre los candidatos,
  el dictamen es "sin_apu" o "dudoso".
- La composición que ves es la de la BIBLIOTECA. Un proyecto puede ajustar distancias
  de acarreo al costear, así que los rendimientos de transporte pueden diferir; juzga
  la afinidad técnica de la actividad, no la exactitud numérica del rendimiento.
- La justificación va en una frase corta, en español.

Responde EXCLUSIVAMENTE con un JSON válido con este esquema:
{"dictamen": "ok"|"dudoso"|"cambiar"|"sin_apu",
 "apu_sugerido": <string|null>, "turno_sugerido": <string|null>,
 "confianza": <number 0..1>, "justificacion": <string corto>}
"""

_ESQUEMA_PROFUNDO = {
    "type": "object",
    "properties": {
        "dictamen": {"type": "string", "enum": list(DICTAMENES)},
        "apu_sugerido": {"type": ["string", "null"]},
        "turno_sugerido": {"type": ["string", "null"]},
        "confianza": {"type": "number"},
        "justificacion": {"type": "string"},
    },
    "required": ["dictamen", "apu_sugerido", "turno_sugerido", "confianza",
                 "justificacion"],
    "additionalProperties": False,
}


class Revisor:
    """Fachada sobre la IA para la revisión. Sin fallback determinístico.

    `_pedir` es la ÚNICA puerta al SDK: los tests heredan de esta clase y la
    sustituyen, así no hace falta simular el cliente de anthropic.
    """

    def __init__(self, enabled: Optional[bool] = None, model: str = config.AI_MODEL):
        self.model = model
        self.enabled = config.ai_available() if enabled is None else enabled
        self._client = None
        # Filas de las que la IA no dijo nada (lote truncado o JSON inválido). No se
        # dan por buenas: quedan sin veredicto y se reportan.
        self.sin_respuesta: set[int] = set()
        if self.enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception:
                self.enabled = False

    @property
    def disponible(self) -> bool:
        return bool(self.enabled)

    # ------------------------------------------------------------ puerta al SDK
    def _pedir(self, system: str, schema: dict, payload: dict, effort: str) -> dict:
        """Una llamada a la IA. Devuelve el JSON ya parseado, o {} si falló."""
        if self._client is None:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        contenido = privacy.safe_json(payload)   # garantía dura: sin dinero
        resp = self._client.messages.create(
            model=self.model,
            # Techo, no gasto: cubre el pensamiento adaptativo MÁS el JSON.
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": contenido}],
        )
        texto = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            return json.loads(texto)
        except Exception:
            return {}    # JSON truncado o inválido: nadie queda en "ok" por accidente

    # ------------------------------------------------------------------ barrido
    def barrer(self, filas: list[CorridaItemRow]) -> set[int]:
        """Devuelve los seq que merecen profundización. Deja en `self.sin_respuesta`
        los que la IA no contestó: esos NO se dan por buenos."""
        if not self.disponible:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        self.sin_respuesta = set()
        indice = indice_corrida(filas)
        marcadas: set[int] = set()
        for i in range(0, len(filas), TAM_LOTE):
            lote = filas[i:i + TAM_LOTE]
            payload = {"indice": indice,
                       "filas": [payload_barrido(f) for f in lote]}
            data = self._pedir(_SISTEMA_BARRIDO, _ESQUEMA_BARRIDO, payload, "low")
            vistos = set()
            for r in (data or {}).get("filas", []):
                try:
                    seq = int(r.get("seq"))
                except (TypeError, ValueError):
                    continue
                vistos.add(seq)
                if str(r.get("resultado")) == "revisar":
                    marcadas.add(seq)
            self.sin_respuesta |= {f.seq for f in lote if f.seq not in vistos}
        # La IA puede devolver un `seq` que no le dimos: si no es de esta corrida no
        # hay fila que profundizar, y el orquestador la buscaría en vano.
        return marcadas & {f.seq for f in filas}

    # ---------------------------------------------------------- profundización
    def profundizar(self, fila: CorridaItemRow, asignado: Optional[DePricedApu],
                    candidatos: list[DePricedApu]) -> Veredicto:
        """Dictamen final de UNA fila, con las composiciones completas a la vista."""
        if not self.disponible:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        data = self._pedir(_SISTEMA_PROFUNDO, _ESQUEMA_PROFUNDO,
                           payload_profundo(fila, asignado, candidatos), "medium")
        dictamen = str(data.get("dictamen") or "")
        sugerido = data.get("apu_sugerido")
        sugerido = str(sugerido).strip() if sugerido else None
        turno = data.get("turno_sugerido")
        turno = str(turno).strip() if turno else None
        just = str(data.get("justificacion") or "").strip()
        try:
            conf = float(data.get("confianza") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0

        validos = {a.codigo for a in candidatos}
        if dictamen not in DICTAMENES:
            # JSON vacío, truncado o un dictamen que no existe: nadie sale en "ok"
            # por accidente. "dudoso" manda la decisión al humano, que es lo correcto.
            dictamen, sugerido, turno = "dudoso", None, None
            just = just or "La IA no devolvió un dictamen legible."
        elif dictamen == "cambiar" and (sugerido is None or sugerido not in validos):
            # La IA no puede inventar un código. Si el que pide no estaba entre los
            # candidatos que le dimos, no existe para esta decisión.
            just = (f"La IA sugirió el APU {sugerido}, que no estaba entre los "
                    f"candidatos. {just}").strip()
            dictamen, sugerido, turno = "dudoso", None, None
        if dictamen != "cambiar":
            # Un `apu_sugerido` solo significa algo con "cambiar": con cualquier otro
            # dictamen no se aplica nada, y un código inventado que sobreviva viaja
            # igual a la base y a la interfaz como si fuera una propuesta real.
            sugerido, turno = None, None

        return Veredicto(seq=fila.seq, dictamen=dictamen, apu_sugerido=sugerido,
                         turno_sugerido=turno, confianza=conf, justificacion=just,
                         nivel="profundo")


# -------------------------------------------------------------- orquestador
def revisar(almacen, filas: list[CorridaItemRow], revisor: Revisor,
            ) -> Iterator[tuple[str, dict]]:
    """Revisa la corrida entera y emite eventos, para que el llamador (el endpoint
    SSE) persista y reporte en vivo:

      ('started',  {'total'})
      ('barrido',  {'revisar': n, 'sin_respuesta': [seq, ...]})
      ('veredicto',{'seq', 'veredicto': {...}})   — por fila, ya lista para guardar
      ('done',     {'total', 'ok', 'dudoso', 'cambiar', 'sin_apu', 'sin_veredicto'})

    Las filas que el barrido no contestó quedan SIN veredicto (no se inventa un `ok`)
    y salen contadas en `sin_veredicto`.

    El `almacen` viene por parámetro y no vive dentro del `Revisor`: esta función es
    la única parte que necesita leer la biblioteca, y dejar al `Revisor` como pura
    fachada de la IA permite sustituirlo en los tests sin montar una base.
    """
    yield ("started", {"total": len(filas)})
    marcadas = revisor.barrer(filas)
    sin_respuesta = set(revisor.sin_respuesta)
    yield ("barrido", {"revisar": len(marcadas),
                       "sin_respuesta": sorted(sin_respuesta)})

    conteo = {d: 0 for d in DICTAMENES}
    for fila in filas:
        if fila.seq in sin_respuesta:
            continue
        if fila.seq not in marcadas:
            v = Veredicto(seq=fila.seq, dictamen="ok", apu_sugerido=None,
                          turno_sugerido=None, confianza=0.0,
                          justificacion="Sin objeciones en el barrido.",
                          nivel="barrido")
        else:
            asignado = (almacen.apus.get_depriced_apu(fila.apu_codigo, fila.shift)
                        if fila.apu_codigo else None)
            # Un candidato que ya no está en la biblioteca se omite: no hay
            # composición que mostrarle a la IA, y no puede ser el sugerido.
            candidatos = []
            for c in (fila.candidatos or []):
                dp = almacen.apus.get_depriced_apu(c.get("apu_codigo"), fila.shift)
                if dp is not None:
                    candidatos.append(dp)
            v = revisor.profundizar(fila, asignado, candidatos)
        conteo[v.dictamen] = conteo.get(v.dictamen, 0) + 1
        yield ("veredicto", {"seq": fila.seq, "veredicto": v.to_dict()})

    yield ("done", {"total": len(filas), **conteo,
                    "sin_veredicto": len(sin_respuesta)})
