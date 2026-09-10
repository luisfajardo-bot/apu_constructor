"""Contrato de la composición asistida.

Hermano de `dominio/revision.py`: la IA propone la ESTRUCTURA de un APU para una
actividad que el matcher determinístico no supo resolver, y lo que sale de acá es una
propuesta que alguien tiene que aprobar. No hay dinero en ningún campo de este módulo,
a propósito: aun así, la propuesta persistida se filtra igual al salir de nuevo hacia
la IA (`dominio/privacy.py`) — `hipotesis` es un dict abierto cuyas claves las pone el
modelo (o, en estado `editada`, una persona), y nada impide que alguien meta ahí un
`"costo"`.

REGLA DEL PARSEO: un componente LEGIBLE nunca se descarta en silencio. Un campo que no
se entiende se degrada de forma CONSERVADORA — hacia menos confianza, nunca hacia más —
y el validador lo dice después. Descartar callado es lo que hacía `assemble.py`
(`if not cands: continue`): la IA proponía ocho insumos, el usuario veía cinco y nadie
explicaba los tres que faltaban.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

# --------------------------------------------------------------- vocabularios
# Cerrados y revalidados en Python aunque el esquema JSON ya los restrinja, por la
# misma razón que `revision.py` revalida `DICTAMENES`: un valor que no entendemos no
# puede colarse como si lo hubiéramos entendido.

# Rol del componente DENTRO del APU, no nombre de actividad. Es lo que permite que el
# validador escriba reglas ("no hay ni mano de obra ni equipo"); un texto libre no se
# puede validar y sería un campo decorativo. El qué-hace-en-esta-actividad va en
# `justificacion`.
FUNCIONES = ("mano_de_obra", "equipo", "herramienta", "material", "transporte",
             "subcontrato", "sub_apu")

ORIGENES = ("copiado_de_antecedente", "ajustado_de_antecedente",
            "calculado_desde_produccion", "supuesto_tecnico", "sin_evidencia")

NIVELES_EVIDENCIA = ("alto", "medio", "bajo")
OPERACIONES = ("division", "multiplicacion", "directo")
TIPOS = ("insumo", "apu")

# Estados PERSISTIDOS. `analizando` y `recuperando_antecedentes` no están porque son
# etapas dentro de una generación (eventos SSE), no filas; `pendiente` es la ausencia
# de fila; `validada` es un campo de la validación, no un estado.
ESTADOS = ("generando", "propuesta", "editada", "aprobada", "rechazada", "error")


# ------------------------------------------------------------------- tipos
def _serializable(x: float) -> Optional[float]:
    """NaN e infinito no son JSON: viajan como null. Round-trip gratis, porque
    `_numero(None)` vuelve a dar NaN al leer."""
    return x if math.isfinite(x) else None


@dataclass(frozen=True)
class Referencia:
    """Un antecedente concreto: el APU de la biblioteca del que sale el componente."""
    apu_codigo: str
    turno: str

    def to_dict(self) -> dict[str, Any]:
        return {"apu_codigo": self.apu_codigo, "turno": self.turno}


@dataclass(frozen=True)
class Calculo:
    """La fórmula que el modelo dice haber usado. Python la RECALCULA siempre:
    el número del modelo no se usa cuando hay un cálculo que lo contradice."""
    operacion: str
    numerador: float
    denominador: float
    resultado: float

    def evaluar(self) -> Optional[float]:
        """El resultado según Python, o None si la operación es imposible."""
        a, b = self.numerador, self.denominador
        if not math.isfinite(a):
            return None
        if self.operacion == "directo":
            return a                       # `directo` no usa el denominador
        if not math.isfinite(b):
            return None
        if self.operacion == "division":
            r = None if b == 0 else a / b
        elif self.operacion == "multiplicacion":
            r = a * b
        else:
            return None
        # Dos operandos finitos pueden dar un resultado que no lo es
        # (1e308 / 1e-308). Un rendimiento infinito no es un rendimiento.
        return r if r is not None and math.isfinite(r) else None

    def to_dict(self) -> dict[str, Any]:
        return {"operacion": self.operacion, "numerador": _serializable(self.numerador),
                "denominador": _serializable(self.denominador),
                "resultado": _serializable(self.resultado)}


@dataclass(frozen=True)
class ComponentePropuesto:
    codigo: str
    tipo: str                     # insumo | apu
    funcion: str                  # de FUNCIONES; "" = ilegible (el validador lo marca)
    rendimiento: float            # cantidad por unidad de actividad; NaN = ilegible
    origen: str                   # de ORIGENES
    referencias: tuple[Referencia, ...] = ()
    hipotesis: dict[str, Any] = field(default_factory=dict)
    calculo: Optional[Calculo] = None
    justificacion: str = ""
    nivel_evidencia: str = "bajo"
    ref_shift: str = ""           # turno del sub-APU cuando tipo == "apu"

    def to_dict(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "tipo": self.tipo, "funcion": self.funcion,
                "rendimiento": _serializable(self.rendimiento), "origen": self.origen,
                "referencias": [r.to_dict() for r in self.referencias],
                "hipotesis": self.hipotesis,
                "calculo": self.calculo.to_dict() if self.calculo else None,
                "justificacion": self.justificacion,
                "nivel_evidencia": self.nivel_evidencia,
                "ref_shift": self.ref_shift}


@dataclass(frozen=True)
class Supuesto:
    campo: str
    supuesto: str
    impacto: str

    def to_dict(self) -> dict[str, Any]:
        return {"campo": self.campo, "supuesto": self.supuesto,
                "impacto": self.impacto}


@dataclass(frozen=True)
class Propuesta:
    componentes: tuple[ComponentePropuesto, ...] = ()
    supuestos: tuple[Supuesto, ...] = ()
    # Lo que el modelo dice de sí mismo. Se GUARDA y se MUESTRA, pero NO entra en el
    # cálculo de la confianza: esa la hace la plataforma con señales observables.
    incertidumbre_declarada: float = 0.0
    justificacion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"componentes": [c.to_dict() for c in self.componentes],
                "supuestos": [s.to_dict() for s in self.supuestos],
                "incertidumbre_declarada": self.incertidumbre_declarada,
                "justificacion": self.justificacion}


# ------------------------------------------------------------------ parseo
# Tope de longitud para los textos que vienen del modelo. Un código de insumo real
# tiene menos de 20 caracteres y una justificación corta cabe de sobra; lo que esto
# ataja es una respuesta degenerada que rompería la tabla de la interfaz o inflaría
# la fila persistida. Se acota en el PARSEO y no río abajo porque acá es donde está
# el borde de confianza: todo lo que sigue ya trabaja con datos acotados.
#
# Medido contra las bases reales del repo: el código más largo del catálogo tiene 7
# caracteres ("10016 N") y el `shift` más largo 8 ("NOCTURNO"), así que 40 sobra.
# OJO con _MAX_TEXTO si algún día se parsea un NOMBRE de insumo o de APU: los reales
# llegan a 830 caracteres (`insumos.nombre`) y este tope los cortaría. Hoy no pasa
# ninguno por acá — el modelo manda códigos y el nombre lo pone el catálogo.
_MAX_TEXTO = 500
_MAX_CODIGO = 40


def _texto(v: Any, tope: int = _MAX_TEXTO) -> str:
    return "" if v is None else str(v).strip()[:tope]


def _numero(v: Any) -> float:
    """Un float, o NaN si no se puede. NaN no se descarta: el validador lo rechaza
    con un mensaje que el usuario puede leer."""
    try:
        return float(v)
    except (TypeError, ValueError, OverflowError):
        return float("nan")


def _del_vocabulario(v: Any, vocabulario: tuple[str, ...], por_defecto: str) -> str:
    val = _texto(v).lower()
    return val if val in vocabulario else por_defecto


def _referencias_desde(v: Any) -> tuple[Referencia, ...]:
    out = []
    for r in (v if isinstance(v, list) else []):
        if not isinstance(r, dict):
            continue
        cod = _texto(r.get("apu_codigo"), _MAX_CODIGO)
        if cod:
            out.append(Referencia(cod, _texto(r.get("turno"), _MAX_CODIGO).upper()))
    return tuple(out)


def _calculo_desde(v: Any) -> Optional[Calculo]:
    if not isinstance(v, dict):
        return None
    op = _del_vocabulario(v.get("operacion"), OPERACIONES, "")
    if not op:
        return None
    return Calculo(op, _numero(v.get("numerador")), _numero(v.get("denominador")),
                   _numero(v.get("resultado")))


def _componente_desde(v: Any) -> Optional[ComponentePropuesto]:
    if not isinstance(v, dict):
        return None          # no es un componente degradable: no hay nada que leer
    return ComponentePropuesto(
        codigo=_texto(v.get("codigo"), _MAX_CODIGO),
        tipo=_del_vocabulario(v.get("tipo"), TIPOS, "insumo"),
        # "" y no un valor del vocabulario: inventarle un rol sería una mentira que el
        # validador daría por buena. Vacío es legible y se marca.
        funcion=_del_vocabulario(v.get("funcion"), FUNCIONES, ""),
        rendimiento=_numero(v.get("rendimiento")),
        # Conservador: si no se entiende de dónde sale, no se le reconoce evidencia.
        origen=_del_vocabulario(v.get("origen"), ORIGENES, "sin_evidencia"),
        referencias=_referencias_desde(v.get("referencias")),
        hipotesis=dict(v["hipotesis"]) if isinstance(v.get("hipotesis"), dict) else {},
        calculo=_calculo_desde(v.get("calculo")),
        justificacion=_texto(v.get("justificacion")),
        nivel_evidencia=_del_vocabulario(v.get("nivel_evidencia"),
                                         NIVELES_EVIDENCIA, "bajo"),
        ref_shift=_texto(v.get("ref_shift"), _MAX_CODIGO).upper(),
    )


def _supuestos_desde(v: Any) -> tuple[Supuesto, ...]:
    out = []
    for s in (v if isinstance(v, list) else []):
        if isinstance(s, dict):
            out.append(Supuesto(_texto(s.get("campo")), _texto(s.get("supuesto")),
                                _texto(s.get("impacto"))))
    return tuple(out)


def propuesta_desde_json(data: Any) -> Propuesta:
    """Lee el JSON del modelo sin confiar en él y sin descartar nada en silencio.

    Un JSON que no es un objeto, o sin `componentes`, da una propuesta VACÍA — que el
    validador rechaza con `PROPUESTA_VACIA`. Nadie sale marcado como válido por
    accidente, que es la misma regla que aplica `revision.py` con los dictámenes.
    """
    if not isinstance(data, dict):
        return Propuesta()
    crudos = data.get("componentes")
    comps = [c for c in (_componente_desde(x)
                         for x in (crudos if isinstance(crudos, list) else []))
             if c is not None]
    inc = _numero(data.get("incertidumbre_declarada"))
    if not math.isfinite(inc):
        inc = 0.0
    return Propuesta(
        componentes=tuple(comps),
        supuestos=_supuestos_desde(data.get("supuestos")),
        incertidumbre_declarada=min(max(inc, 0.0), 1.0),
        justificacion=_texto(data.get("justificacion")),
    )
