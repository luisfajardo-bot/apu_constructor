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

# Filas por llamada del barrido. Bajarlo mejora el foco de la IA y SUBE el costo: el
# índice de la corrida entera viaja en CADA lote, así que el gasto en índice crece como
# O(n²/TAM_LOTE) — subirlo reduce copias del índice a cambio de foco. Es la palanca si
# al barrido se le escapan objeciones; si el costo llegara a doler, la palanca
# siguiente no es este número sino `cache_control: {"type": "ephemeral"}` sobre el
# bloque del índice, que es idéntico en todos los lotes.
TAM_LOTE = 25

# Vocabulario del VEREDICTO final (paso 2). El del barrido es otro (`ok | revisar`)
# y no se mezclan: "revisar" tría, nunca dictamina.
DICTAMENES = ("ok", "dudoso", "cambiar", "sin_apu")

# Vocabulario del TRIAJE (paso 1). Se valida en `barrer_lote` aunque el esquema JSON ya lo
# restrinja, igual que `profundizar` revalida `dictamen`: un `resultado` que no
# entendemos NO puede contar como "contestada y sin objeciones".
RESULTADOS_BARRIDO = ("ok", "revisar")

# Turnos válidos para `turno_sugerido`. El turno es parte de la clave del APU: un
# código válido con un turno inventado describe un APU que no existe.
TURNOS = (config.SHIFT_DIURNO, config.SHIFT_NOCTURNO)


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
                    "resultado": {"type": "string", "enum": list(RESULTADOS_BARRIDO)},
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
- `turno_sugerido` es la jornada del APU que propones y es parte de su identidad:
  SOLO valen "DIURNO" y "NOCTURNO". Cópialo del campo `shift` del candidato que
  elegiste. Si el dictamen no es "cambiar", o no lo sabes, devuelve null.
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
        "confianza": {"type": "number", "minimum": 0, "maximum": 1},
        "justificacion": {"type": "string"},
    },
    "required": ["dictamen", "apu_sugerido", "turno_sugerido", "confianza",
                 "justificacion"],
    "additionalProperties": False,
}


class Revisor:
    """Fachada sobre la IA para la revisión. Sin fallback determinístico.

    `_pedir` es la ÚNICA puerta al SDK: los tests heredan de esta clase y la
    sustituyen, así no hace falta simular el cliente de anthropic. El cliente se
    construye ahí, la primera vez que hace falta: preguntar `disponible` no tiene por
    qué armar un cliente HTTP.
    """

    def __init__(self, enabled: Optional[bool] = None, model: str = config.AI_MODEL):
        self.model = model
        self.enabled = config.ai_available() if enabled is None else enabled
        self._client = None

    @property
    def disponible(self) -> bool:
        return bool(self.enabled)

    # ------------------------------------------------------------ puerta al SDK
    def _pedir(self, system: str, schema: dict, payload: dict, effort: str) -> dict:
        """Una llamada a la IA. Devuelve el JSON ya parseado, o {} si falló."""
        if self._client is None:
            if not self.enabled:
                raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception as exc:
                self.enabled = False
                raise IANoDisponible(
                    "La revisión con IA necesita el SDK de anthropic.") from exc
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
            data = json.loads(texto)
        except Exception:
            return {}    # JSON truncado o inválido: nadie queda en "ok" por accidente
        # `json.loads` valida sintaxis, no forma: `[{...}]`, `"ok"` o `42` parsean bien
        # y reventarían el `.get` del llamador. Que caigan por el mismo camino.
        return data if isinstance(data, dict) else {}

    # ------------------------------------------------------------------ barrido
    def barrer_lote(self, lote: list[CorridaItemRow],
                    indice: list[dict[str, Any]]) -> tuple[set[int], set[int]]:
        """Triaje de UN lote: UNA sola llamada a la IA. Devuelve `(marcadas,
        sin_respuesta)` de ese lote — los seq que merecen profundización y los que la
        IA no contestó (lote truncado, JSON inválido, vocabulario ilegible o error
        del SDK). Esos NO se dan por buenos.

        El `indice` es el de la corrida ENTERA y viaja en CADA lote: es la razón de
        ser del barrido, que la IA vea el presupuesto como un todo y pueda detectar
        incoherencias entre líneas.

        `sin_respuesta` va en el valor de retorno y no como estado del objeto a
        propósito: el orquestador natural ("si no está en marcadas, es ok")
        convertiría justo las filas sin contestar en veredictos `ok`, que es lo único
        que este módulo existe para evitar. Devolverlas obliga a mirarlas.

        Partir la corrida en lotes NO se hace acá sino en `revisar`: un método = una
        llamada a la IA, así el orquestador puede reportar progreso entre lote y lote
        y el stream no se queda mudo (un proxy corta la conexión inactiva).
        """
        payload = {"indice": indice, "filas": [payload_barrido(f) for f in lote]}
        try:
            data = self._pedir(_SISTEMA_BARRIDO, _ESQUEMA_BARRIDO, payload, "low")
        except (privacy.PrivacyViolation, IANoDisponible):
            # El invariante #1 NUNCA se traga: sin este `raise`, el `except` de
            # abajo convertiría una fuga de dinero en un lote vacío y silencioso.
            # Sin IA tampoco hay revisión que reportar: se avisa, no se maquilla
            # (la levanta `_pedir`; el guard explícito está en `revisar`, que además
            # cubre la corrida vacía, donde no hay ni una llamada que la levante).
            raise
        except Exception:
            # Un 429 o un timeout que sobreviva a los reintentos del SDK no puede
            # tirar los lotes ya pagados: este cae entero en `sin_respuesta`.
            data = {}
        marcadas: set[int] = set()
        vistos: set[int] = set()
        crudas = data.get("filas")
        for r in (crudas if isinstance(crudas, list) else []):
            if not isinstance(r, dict):
                continue
            try:
                seq = int(r.get("seq"))
            except (TypeError, ValueError):
                continue
            res = str(r.get("resultado") or "").strip().lower()
            if res not in RESULTADOS_BARRIDO:
                # Vocabulario ilegible (falta, `null`, "okey", basura): la fila NO
                # queda contestada. Darla por buena es bendecir un APU en silencio,
                # y el prompt dice lo contrario: ante la duda, revisar.
                continue
            vistos.add(seq)
            if res == "revisar":
                marcadas.add(seq)
        return marcadas, {f.seq for f in lote if f.seq not in vistos}

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
        turno = str(turno).strip().upper() if turno else None
        # El turno es parte de la clave del APU: uno inventado describe un APU que no
        # existe. `None` es correcto — el consumidor cae al turno de la fila.
        turno = turno if turno in TURNOS else None
        just = str(data.get("justificacion") or "").strip()
        try:
            conf = float(data.get("confianza") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0
        conf = min(max(conf, 0.0), 1.0)   # el prompt promete 0..1; acá se cumple

        validos = {a.codigo for a in candidatos}
        if dictamen not in DICTAMENES:
            # JSON vacío, truncado o un dictamen que no existe: nadie sale en "ok"
            # por accidente. "dudoso" manda la decisión al humano, que es lo correcto.
            dictamen, sugerido, turno = "dudoso", None, None
            just = just or "La IA no devolvió un dictamen legible."
        elif dictamen == "cambiar" and sugerido is None:
            # Pidió cambiar pero no dijo por cuál: no hay propuesta que aplicar.
            just = ("La IA pidió cambiar el APU pero no indicó por cuál. "
                    f"{just}").strip()
            dictamen, sugerido, turno = "dudoso", None, None
        elif dictamen == "cambiar" and sugerido not in validos:
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
      ('barriendo',{'lote': i, 'lotes': n})       — uno por lote del barrido
      ('barrido',  {'revisar': n, 'sin_respuesta': [seq, ...]})
      ('veredicto',{'seq', 'veredicto': {...}})   — por fila, ya lista para guardar
      ('done',     {'total', 'ok', 'dudoso', 'cambiar', 'sin_apu', 'sin_veredicto'})

    Las filas que el barrido no contestó quedan SIN veredicto (no se inventa un `ok`)
    y salen contadas en `sin_veredicto`.

    El `almacen` viene por parámetro y no vive dentro del `Revisor`: esta función es
    la única parte que necesita leer la biblioteca, y dejar al `Revisor` como pura
    fachada de la IA permite sustituirlo en los tests sin montar una base.
    """
    if not revisor.disponible:
        # Acá y no en `barrer_lote`: una corrida vacía no hace ni una llamada, y sin
        # este guard el llamador creería que la revisión corrió bien sin haber corrido.
        raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
    yield ("started", {"total": len(filas)})

    # El barrido reporta lote por lote y no de una: con 300 líneas son 12 llamadas con
    # pensamiento adaptativo, varios minutos. Un stream mudo tanto rato lo corta el
    # proxy (Render) y la interfaz no tiene cómo saber si avanza.
    indice = indice_corrida(filas)
    lotes = (len(filas) + TAM_LOTE - 1) // TAM_LOTE
    marcadas: set[int] = set()
    sin_respuesta: set[int] = set()
    for n, i in enumerate(range(0, len(filas), TAM_LOTE), start=1):
        del_lote, sin_del_lote = revisor.barrer_lote(filas[i:i + TAM_LOTE], indice)
        marcadas |= del_lote
        sin_respuesta |= sin_del_lote
        yield ("barriendo", {"lote": n, "lotes": lotes})
    # La IA puede devolver un `seq` que no le dimos: si no es de esta corrida no hay
    # fila que profundizar, y el bucle de abajo la buscaría en vano.
    marcadas &= {f.seq for f in filas}
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
            # Un candidato que ya no está en la biblioteca se omite: no hay
            # composición que mostrarle a la IA, y no puede ser el sugerido.
            candidatos = []
            for c in (fila.candidatos or []):
                dp = almacen.apus.get_depriced_apu(c.get("apu_codigo"), fila.shift)
                if dp is not None:
                    candidatos.append(dp)
            if not fila.apu_codigo and not candidatos:
                # Sin APU y sin un solo candidato vivo, profundizar es pagarle a la IA
                # para que mire una lista vacía y conteste lo obvio.
                v = Veredicto(seq=fila.seq, dictamen="sin_apu", apu_sugerido=None,
                              turno_sugerido=None, confianza=1.0,
                              justificacion=("La actividad no tiene APU asignado y "
                                             "ningún candidato existe en la "
                                             "biblioteca."),
                              nivel="barrido")
            else:
                asignado = (almacen.apus.get_depriced_apu(fila.apu_codigo, fila.shift)
                            if fila.apu_codigo else None)
                v = revisor.profundizar(fila, asignado, candidatos)
        conteo[v.dictamen] = conteo.get(v.dictamen, 0) + 1
        yield ("veredicto", {"seq": fila.seq, "veredicto": v.to_dict()})

    yield ("done", {"total": len(filas), **conteo,
                    "sin_veredicto": len(sin_respuesta)})
