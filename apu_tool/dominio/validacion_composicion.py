"""Validación determinística de una propuesta de composición.

Sin IA, sin dinero, sin motor de precios. Recibe la propuesta que devolvió el modelo y
un contexto que salió todo de la base, y devuelve la propuesta CORREGIDA más la lista
de hallazgos.

El reparto entre error y advertencia sigue una regla, no el gusto:

  - Bloquea lo ESTRUCTURAL: el código no está autorizado, no existe, la cantidad no es
    un número usable, el sub-APU no existe o cierra un ciclo, la fórmula es imposible.
    Con cualquiera de estas la propuesta no describe algo que el sistema pueda costear.
  - Advierte lo CONTEXTUAL: el rendimiento es raro, falta herramienta, el método no
    cuadra con la descripción. Acá un ingeniero puede tener razón contra la regla, y
    convertir criterio discutible en bloqueo absoluto es lo que el diseño prohíbe.

`validar` CORRIGE dos cosas y lo dice: la aritmética (Python manda sobre el número del
modelo cuando hay un `calculo` que lo contradice) y las referencias muertas (se
limpian). Tirar una propuesta buena por una división mal hecha que sabemos arreglar
sería el peor de los dos comportamientos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field, replace
from typing import Any

from apu_tool import config
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.composicion import ComponentePropuesto, Propuesta

# Orígenes que AFIRMAN venir de un antecedente: sin referencia viva, la afirmación no
# se sostiene y se advierte.
_ORIGENES_CON_ANTECEDENTE = ("copiado_de_antecedente", "ajustado_de_antecedente")

# Tolerancia relativa del recálculo. El modelo redondea a 6 decimales; 8/96 devuelto
# como 0,083333 no es un error, 0,09 sí. 1e-4 separa las dos cosas con holgura.
_TOLERANCIA_RELATIVA = 1e-4

# ponytail: detección de método por palabra clave sobre la descripción cruda. Es tosca
# —por eso es ADVERTENCIA y no error— y se reemplaza en la fase 3, cuando la ficha
# técnica traiga el método en un campo propio en vez de adivinarlo del texto.
_PALABRAS_MANUAL = ("MANUAL", "A MANO")
_PALABRAS_MECANICO = ("MECANIC", "MECÁNIC", "RETRO", "EXCAVADORA", "MOTONIVELADORA",
                      "VIBROCOMPACTADOR")


@dataclass(frozen=True)
class Hallazgo:
    codigo: str                 # vocabulario estable, para que la interfaz lo mapee
    mensaje: str                # en español, para leer
    componente: str = ""        # código del componente; "" = hallazgo global

    def to_dict(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "mensaje": self.mensaje,
                "componente": self.componente}


@dataclass(frozen=True)
class Validacion:
    valido: bool
    errores: tuple[Hallazgo, ...]
    advertencias: tuple[Hallazgo, ...]
    superadas: int
    totales: int

    def to_dict(self) -> dict[str, Any]:
        # OJO al renombrar: `total` (singular) está en `_FORBIDDEN_KEYS` de
        # `dominio/privacy.py`. Este dict viaja hacia la interfaz y se persiste, y el
        # día que se reinyecte como contexto hacia la IA, un `total` haría saltar el
        # guardián sobre una validación que no tiene un peso adentro. `totales` pasa
        # por el plural, no por diseño.
        return {"valido": self.valido,
                "errores": [h.to_dict() for h in self.errores],
                "advertencias": [h.to_dict() for h in self.advertencias],
                "metricas": {"superadas": self.superadas, "totales": self.totales}}


@dataclass(frozen=True)
class ContextoValidacion:
    """Todo lo que hace falta para validar, y todo salió de la base.

    `componentes_de_apu` mapea (codigo, turno) -> tuplas (codigo, tipo, ref_shift) de
    sus componentes. Es lo único que necesita el recorrido de ciclos, y viene
    precargado para no consultar la base dentro del validador, que es puro a propósito.
    """
    descripcion: str
    unidad_actividad: str
    shift: str
    codigos_permitidos: frozenset[str]
    unidades_catalogo: dict[str, str]
    apus_existentes: frozenset[tuple[str, str]]
    componentes_de_apu: dict[tuple[str, str], tuple[tuple[str, str, str], ...]]
    observados: dict[str, RendimientoObservado]
    # Código del APU que se está creando. Vacío durante la generación (todavía no se
    # eligió) y con valor al aprobar: recién ahí un ciclo es detectable.
    apu_codigo_propio: str = ""
    supuestos_confirmados: bool = False
    # Unidad de cada APU de la biblioteca, (codigo, turno) -> unidad. La usa la señal
    # `unidad_de_antecedentes` de la confianza (tarea 4): un antecedente que mide en
    # ML no respalda una actividad que se paga por M3, por parecido que sea el nombre.
    unidades_de_apu: dict[tuple[str, str], str] = field(default_factory=dict)


# --------------------------------------------------------------- recálculo
def _recalcular(c: ComponentePropuesto) -> tuple[ComponentePropuesto, list[Hallazgo]]:
    """Python manda sobre la aritmética."""
    if c.calculo is None:
        return c, []
    resultado = c.calculo.evaluar()
    if resultado is None:
        return c, [Hallazgo(
            "CALCULO_IMPOSIBLE",
            f"La fórmula declarada ({c.calculo.operacion}) no se puede evaluar: "
            f"numerador {c.calculo.numerador}, denominador {c.calculo.denominador}.",
            c.codigo)]
    dicho = c.rendimiento
    if math.isfinite(dicho) and abs(dicho - resultado) <= max(
            1e-9, _TOLERANCIA_RELATIVA * abs(resultado)):
        return c, []
    return replace(c, rendimiento=resultado), [Hallazgo(
        "CALCULO_CORREGIDO",
        f"El modelo declaró {dicho:g} pero su propia fórmula da {resultado:g}. "
        f"Se usa {resultado:g}.", c.codigo)]


def _limpiar_referencias(c: ComponentePropuesto, ctx: ContextoValidacion
                         ) -> tuple[ComponentePropuesto, list[Hallazgo]]:
    """Una referencia a un APU que ya no existe no respalda nada: se quita."""
    vivas, muertas = [], []
    for r in c.referencias:
        turno = (r.turno or ctx.shift).upper()
        (vivas if (r.apu_codigo, turno) in ctx.apus_existentes else muertas).append(r)
    if not muertas:
        return c, []
    nombres = ", ".join(r.apu_codigo for r in muertas)
    return replace(c, referencias=tuple(vivas)), [Hallazgo(
        "REFERENCIA_INEXISTENTE",
        f"El APU de referencia {nombres} ya no está en la biblioteca; se descarta "
        f"como respaldo.", c.codigo)]


# ----------------------------------------------------------------- ciclos
def _cierra_ciclo(codigo: str, turno: str, propio: str,
                  arbol: dict[tuple[str, str], tuple[tuple[str, str, str], ...]]
                  ) -> bool:
    """El árbol de este sub-APU, ¿vuelve al APU que estamos creando?"""
    if not propio:
        return False        # sin código propio no hay ciclo posible todavía
    pendientes = [(codigo, turno)]
    vistos: set[tuple[str, str]] = set()
    while pendientes:
        clave = pendientes.pop()
        if clave in vistos:
            continue
        vistos.add(clave)
        if clave[0] == propio:
            return True
        for hijo, tipo, ref in arbol.get(clave, ()):
            if tipo == "apu":
                pendientes.append((hijo, (ref or clave[1]).upper()))
    return False


# ------------------------------------------------------- reglas por componente
def _validar_componente(c: ComponentePropuesto, ctx: ContextoValidacion
                        ) -> tuple[list[Hallazgo], list[Hallazgo], int]:
    """(errores, advertencias, reglas_evaluadas) de UN componente."""
    err: list[Hallazgo] = []
    adv: list[Hallazgo] = []
    reglas = 0

    reglas += 1
    if c.codigo not in ctx.codigos_permitidos:
        err.append(Hallazgo("CODIGO_NO_AUTORIZADO",
                            f"El código {c.codigo or '(vacío)'} no estaba entre los "
                            f"candidatos que se le dieron a la IA.", c.codigo))
    elif c.tipo == "apu":
        reglas += 1
        turno = (c.ref_shift or ctx.shift).upper()
        if (c.codigo, turno) not in ctx.apus_existentes:
            err.append(Hallazgo("SUBAPU_INEXISTENTE",
                                f"El sub-APU {c.codigo} no existe en turno {turno}.",
                                c.codigo))
        else:
            reglas += 1
            if _cierra_ciclo(c.codigo, turno, ctx.apu_codigo_propio,
                             ctx.componentes_de_apu):
                err.append(Hallazgo("SUBAPU_CICLO",
                                    f"El sub-APU {c.codigo} contiene al APU que se "
                                    f"está creando: sería un ciclo.", c.codigo))
    else:
        reglas += 1
        if c.codigo not in ctx.unidades_catalogo:
            err.append(Hallazgo("CODIGO_INEXISTENTE",
                                f"El insumo {c.codigo} no está en el catálogo.",
                                c.codigo))

    reglas += 1
    r = c.rendimiento
    if not math.isfinite(r) or r <= 0 or r > config.COMPOSICION_LIMITE_RENDIMIENTO:
        err.append(Hallazgo("CANTIDAD_INVALIDA",
                            f"El rendimiento de {c.codigo} ({r}) tiene que ser un "
                            f"número mayor que 0 y menor que "
                            f"{config.COMPOSICION_LIMITE_RENDIMIENTO:g}.", c.codigo))

    reglas += 1
    if not c.funcion:
        adv.append(Hallazgo("FUNCION_ILEGIBLE",
                            f"No se entendió qué función cumple {c.codigo} en la "
                            f"actividad; revisala antes de aprobar.", c.codigo))

    reglas += 1
    if c.origen == "sin_evidencia" or (
            c.origen in _ORIGENES_CON_ANTECEDENTE and not c.referencias):
        adv.append(Hallazgo("SIN_EVIDENCIA",
                            f"{c.codigo} no tiene un antecedente que lo respalde.",
                            c.codigo))

    reglas += 1
    obs = ctx.observados.get(c.codigo)
    if obs is None or obs.n < config.COMPOSICION_MIN_ANTECEDENTES:
        adv.append(Hallazgo("SIN_ANTECEDENTES",
                            f"{c.codigo} aparece en {0 if obs is None else obs.n} APUs "
                            f"de la biblioteca: no hay rango contra el cual comparar "
                            f"su rendimiento.", c.codigo))
    elif math.isfinite(r) and not (obs.minimo <= r <= obs.maximo):
        ref = obs.minimo if r < obs.minimo else obs.maximo
        pct = abs(r - ref) / ref * 100 if ref else 0.0
        lado = "por debajo" if r < obs.minimo else "por encima"
        adv.append(Hallazgo("RENDIMIENTO_ATIPICO",
                            f"{r:g} {obs.unidad} queda {pct:.0f} % {lado} del rango "
                            f"observado ({obs.minimo:g}-{obs.maximo:g} {obs.unidad}, "
                            f"n={obs.n}).", c.codigo))

    return err, adv, reglas


# ------------------------------------------------------- reglas del conjunto
def _validar_conjunto(p: Propuesta, ctx: ContextoValidacion
                      ) -> tuple[list[Hallazgo], list[Hallazgo], int]:
    err: list[Hallazgo] = []
    adv: list[Hallazgo] = []
    reglas = 0
    comps = p.componentes
    funciones = {c.funcion for c in comps}

    reglas += 1
    claves = [(c.codigo, c.tipo, c.ref_shift) for c in comps]
    repetidas = sorted({k[0] for k in claves if claves.count(k) > 1})
    if repetidas:
        # UN hallazgo con todos los códigos, no uno por par: es una sola regla, y si
        # emitiera N la métrica `superadas` restaría N por una regla evaluada.
        err.append(Hallazgo(
            "COMPONENTE_DUPLICADO",
            f"{', '.join(repetidas)} aparece más de una vez en la composición.",
            repetidas[0] if len(repetidas) == 1 else ""))

    reglas += 1
    if not ({"mano_de_obra", "equipo"} & funciones):
        adv.append(Hallazgo("FALTA_MANO_DE_OBRA",
                            "La composición no tiene ni mano de obra ni equipo: "
                            "revisá si la actividad es solo de suministro."))

    reglas += 1
    if "mano_de_obra" in funciones and not ({"herramienta", "equipo"} & funciones):
        adv.append(Hallazgo("FALTA_HERRAMIENTA",
                            "Hay cuadrilla pero ni herramienta ni equipo."))

    reglas += 1
    desc = (ctx.descripcion or "").upper()
    if any(x in desc for x in _PALABRAS_MANUAL) and "equipo" in funciones:
        adv.append(Hallazgo("METODO_INCOHERENTE",
                            "La actividad dice MANUAL y la composición trae equipo."))
    elif any(x in desc for x in _PALABRAS_MECANICO) and "equipo" not in funciones:
        adv.append(Hallazgo("METODO_INCOHERENTE",
                            "La actividad dice mecánica y la composición no trae "
                            "equipo."))

    reglas += 1
    if p.supuestos and not ctx.supuestos_confirmados:
        adv.append(Hallazgo("SUPUESTO_SIN_CONFIRMAR",
                            f"Hay {len(p.supuestos)} supuesto(s) que nadie confirmó."))

    return err, adv, reglas


# --------------------------------------------------------------------- api
def validar(p: Propuesta, ctx: ContextoValidacion) -> tuple[Propuesta, Validacion]:
    """Devuelve la propuesta CORREGIDA y su validación.

    Corrige dos cosas y lo dice: la aritmética y las referencias muertas. Todo lo
    demás se reporta, no se toca — arreglarlo es del humano en la mesa de revisión.
    """
    if not p.componentes:
        return p, Validacion(
            valido=False,
            errores=(Hallazgo("PROPUESTA_VACIA",
                              "La IA no propuso ningún componente."),),
            advertencias=(), superadas=0, totales=1)

    corregidos: list[ComponentePropuesto] = []
    errores: list[Hallazgo] = []
    advertencias: list[Hallazgo] = []
    reglas = 0

    for c in p.componentes:
        c, h1 = _recalcular(c)
        c, h2 = _limpiar_referencias(c, ctx)
        reglas += 2
        for h in h1 + h2:
            (errores if h.codigo == "CALCULO_IMPOSIBLE" else advertencias).append(h)
        e, a, n = _validar_componente(c, ctx)
        errores += e
        advertencias += a
        reglas += n
        corregidos.append(c)

    nueva = replace(p, componentes=tuple(corregidos))
    e, a, n = _validar_conjunto(nueva, ctx)
    errores += e
    advertencias += a
    reglas += n

    return nueva, Validacion(
        valido=not errores, errores=tuple(errores), advertencias=tuple(advertencias),
        superadas=reglas - len(errores) - len(advertencias), totales=reglas)
