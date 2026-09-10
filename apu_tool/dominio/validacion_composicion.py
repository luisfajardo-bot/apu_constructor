"""Validación determinística de una propuesta de composición.

Sin IA, sin dinero, sin motor de precios. Recibe la propuesta que devolvió el modelo y
un contexto que salió todo de la base, y devuelve la propuesta CORREGIDA más la lista
de hallazgos.

El reparto entre error y advertencia sigue una regla, no el gusto:

  - Bloquea lo ESTRUCTURAL: el código no está autorizado, no existe, la cantidad no es
    un número usable, el sub-APU no existe o cierra un ciclo, la fórmula es imposible,
    el tipo contradice la función. Con cualquiera de estas la propuesta no describe
    algo que el sistema pueda costear.
  - Advierte lo CONTEXTUAL: el rendimiento es raro, falta herramienta, el método no
    cuadra con la descripción. Acá un ingeniero puede tener razón contra la regla, y
    convertir criterio discutible en bloqueo absoluto es lo que el diseño prohíbe.

`validar` CORRIGE dos cosas y lo dice: la aritmética (Python manda sobre el número del
modelo cuando hay un `calculo` que lo contradice) y las referencias muertas (se
limpian). Tirar una propuesta buena por una división mal hecha que sabemos arreglar
sería el peor de los dos comportamientos.

CONVENCIÓN DE LA MÉTRICA: una regla evaluada = a lo sumo un hallazgo, y una regla que
no aplica no se cuenta. `superadas` se muestra en la interfaz ("20 de 21"), así que una
regla que emita N hallazgos restaría N por una sola evaluación y el número mentiría.
"""
from __future__ import annotations

import math
from collections import Counter
from dataclasses import dataclass, field, replace
from typing import Any

from apu_tool import config
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.composicion import (_MAX_CODIGO, ComponentePropuesto,
                                          Propuesta)
from apu_tool.nucleo.texto import normalizar

# Orígenes que AFIRMAN un respaldo. Cada uno lo afirma de una forma distinta y por eso
# se chequean distinto: los dos primeros con una referencia viva, el tercero con la
# cuenta a la vista, el cuarto con un supuesto declarado para que alguien lo confirme.
# `sin_evidencia` no afirma nada — es honesto y por eso también advierte, pero sin
# contradicción. La tarea 4 (confianza) lee esta misma constante: si se parchea allá
# en vez de acá, el validador y la confianza dicen cosas distintas del mismo componente.
_ORIGENES_CON_REFERENCIA = ("copiado_de_antecedente", "ajustado_de_antecedente")

# Funciones que APORTAN ejecución. Un APU hecho de sub-APUs tiene la mano de obra
# adentro de ellos, y un subcontrato la tiene adentro de su precio: exigirle cuadrilla
# propia sería una advertencia que suena siempre sobre composiciones correctas.
_FUNCIONES_EJECUCION = frozenset({"mano_de_obra", "equipo", "sub_apu", "subcontrato"})

# Tolerancia relativa del recálculo. El modelo redondea a 6 decimales; 8/96 devuelto
# como 0,083333 no es un error, 0,09 sí. 1e-4 separa las dos cosas con holgura.
_TOLERANCIA_RELATIVA = 1e-4

# ponytail: detección de método por palabra clave sobre la descripción normalizada. Es
# tosca —por eso es ADVERTENCIA y no error— y se reemplaza en la fase 3, cuando la
# ficha técnica traiga el método en un campo propio en vez de adivinarlo del texto.
# Van sin tilde porque `normalizar` las quita: "MECÁNICA" entra como "MECANICA".
_PALABRAS_MANUAL = ("MANUAL", "A MANO")
_PALABRAS_MECANICO = ("MECANIC", "RETRO", "EXCAVADORA", "MOTONIVELADORA",
                      "VIBROCOMPACTADOR")


def _corto(codigo: str) -> str:
    """El código lo escribe el modelo: uno de 10 KB rompe la interfaz que lo muestra.

    Mismo tope que el parseo, importado y no copiado: la confianza (tarea 4) cruza
    `Hallazgo.componente` con `ComponentePropuesto.codigo`, y si los dos topes se
    separan, un componente sin evidencia pasaría a contar como respaldado sin que
    nada lo diga.
    """
    return codigo if len(codigo) <= _MAX_CODIGO else codigo[:_MAX_CODIGO] + "…"


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
    # Turno del APU que se está creando. Un APU es (codigo, turno): el mismo código en
    # DIURNO y en NOCTURNO son dos APUs, y solo uno de los dos puede ciclar. Vacío
    # (todavía no se eligió) hace que el ciclo se compare solo por código, que es lo
    # conservador: puede señalar un ciclo que no lo es, y eso se explica; al revés se
    # colaría uno real.
    turno_propio: str = ""
    supuestos_confirmados: bool = False
    # Unidad de cada APU de la biblioteca, (codigo, turno) -> unidad. La usa la señal
    # `unidad_de_antecedentes` de la confianza (tarea 4): un antecedente que mide en
    # ML no respalda una actividad que se paga por M3, por parecido que sea el nombre.
    unidades_de_apu: dict[tuple[str, str], str] = field(default_factory=dict)


# --------------------------------------------------------------- recálculo
def _recalcular(c: ComponentePropuesto
                ) -> tuple[ComponentePropuesto, list[Hallazgo], list[Hallazgo]]:
    """Python manda sobre la aritmética. Devuelve (componente, errores, advertencias):
    quién bloquea y quién no lo decide esta función, que es la que sabe, y no el
    llamador comparando códigos de hallazgo contra strings."""
    if c.calculo is None:
        return c, [], []
    resultado = c.calculo.evaluar()
    if resultado is None:
        return c, [Hallazgo(
            "CALCULO_IMPOSIBLE",
            f"La fórmula declarada ({c.calculo.operacion}) no se puede evaluar: "
            f"numerador {c.calculo.numerador}, denominador {c.calculo.denominador}.",
            _corto(c.codigo))], []
    dicho = c.rendimiento
    # Piso absoluto 5e-7: el modelo redondea a 6 decimales, así que ese es su error
    # máximo honesto. Con el piso en 1e-9, todo resultado por debajo de ~0,005 se
    # marcaba como corregido por un redondeo correcto.
    if math.isfinite(dicho) and abs(dicho - resultado) <= max(
            5e-7, _TOLERANCIA_RELATIVA * abs(resultado)):
        return c, [], []
    # Se corrige el rendimiento Y el resultado que la fórmula declara: la interfaz
    # muestra la cuenta, y no puede decir "8 / 96 = 0,09" arriba de un 0,083333.
    return replace(c, rendimiento=resultado,
                   calculo=replace(c.calculo, resultado=resultado)), [], [Hallazgo(
        "CALCULO_CORREGIDO",
        f"El modelo declaró {dicho:g} pero su propia fórmula da {resultado:g}. "
        f"Se usa {resultado:g}.", _corto(c.codigo))]


def _limpiar_referencias(c: ComponentePropuesto, ctx: ContextoValidacion
                         ) -> tuple[ComponentePropuesto, list[Hallazgo]]:
    """Una referencia a un APU que ya no existe no respalda nada: se quita."""
    vivas, muertas = [], []
    for r in c.referencias:
        turno = (r.turno or ctx.shift).upper()
        (vivas if (r.apu_codigo, turno) in ctx.apus_existentes else muertas).append(r)
    if not muertas:
        return c, []
    nombres = ", ".join(_corto(r.apu_codigo) for r in muertas)
    return replace(c, referencias=tuple(vivas)), [Hallazgo(
        "REFERENCIA_INEXISTENTE",
        f"El APU de referencia {nombres} ya no está en la biblioteca; se descarta "
        f"como respaldo.", _corto(c.codigo))]


# ----------------------------------------------------------------- ciclos
def _cierra_ciclo(codigo: str, turno: str, propio: str, turno_propio: str,
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
        # Sin turno propio se compara solo el código (ver `ContextoValidacion`).
        if clave[0] == propio and (not turno_propio
                                   or clave[1] == turno_propio.upper()):
            return True
        for hijo, tipo, ref in arbol.get(clave, ()):
            if tipo == "apu":
                pendientes.append((hijo, (ref or clave[1]).upper()))
    return False


# ------------------------------------------------------- reglas por componente
def _validar_componente(c: ComponentePropuesto, ctx: ContextoValidacion,
                        hay_supuestos: bool
                        ) -> tuple[list[Hallazgo], list[Hallazgo], int]:
    """(errores, advertencias, reglas_evaluadas) de UN componente."""
    err: list[Hallazgo] = []
    adv: list[Hallazgo] = []
    reglas = 0
    cod = _corto(c.codigo)

    reglas += 1
    if c.codigo not in ctx.codigos_permitidos:
        err.append(Hallazgo("CODIGO_NO_AUTORIZADO",
                            f"El código {cod or '(vacío)'} no estaba entre los "
                            f"candidatos que se le dieron a la IA.", cod))
    elif c.tipo == "apu":
        reglas += 1
        turno = (c.ref_shift or ctx.shift).upper()
        if (c.codigo, turno) not in ctx.apus_existentes:
            err.append(Hallazgo("SUBAPU_INEXISTENTE",
                                f"El sub-APU {cod} no existe en turno {turno}.", cod))
        else:
            reglas += 1
            if _cierra_ciclo(c.codigo, turno, ctx.apu_codigo_propio,
                             ctx.turno_propio, ctx.componentes_de_apu):
                err.append(Hallazgo("SUBAPU_CICLO",
                                    f"El sub-APU {cod} contiene al APU que se está "
                                    f"creando: sería un ciclo.", cod))
    else:
        reglas += 1
        if c.codigo not in ctx.unidades_catalogo:
            err.append(Hallazgo("CODIGO_INEXISTENTE",
                                f"El insumo {cod} no está en el catálogo.", cod))

    reglas += 1
    if c.funcion == "sub_apu" and c.tipo != "apu":
        # Solo esta dirección es peligrosa: `tipo` es lo que persiste
        # `autoria._componentes_de` y lo que decide cómo se costea, mientras que
        # `funcion` no llega a la base (`apu_componentes` no tiene esa columna). Un
        # sub-APU guardado como insumo se costea como insumo, y si su código es uno de
        # los "eco de un APU" sin tarifa cae al piso de $1 — el underbid silencioso que
        # este repo ya persiguió dos veces.
        # La dirección inversa (tipo="apu" con otra funcion) no cambia ningún costo, y
        # bloquearla dejaba sin salida al caso más común: `funcion=""`, que es lo que
        # el parser produce ante un valor ilegible, y que la mesa no deja editar.
        err.append(Hallazgo(
            "TIPO_INCOHERENTE",
            f"{cod} dice cumplir función de sub-APU pero está declarado como "
            f"insumo: así se costearía como insumo.", cod))
    elif c.tipo == "apu" and c.funcion and c.funcion != "sub_apu":
        adv.append(Hallazgo(
            "FUNCION_INESPERADA",
            f"{cod} es un sub-APU pero su función dice {c.funcion}.", cod))

    reglas += 1
    r = c.rendimiento
    if not math.isfinite(r) or r <= 0:
        err.append(Hallazgo("CANTIDAD_INVALIDA",
                            f"El rendimiento de {cod} ({r:g}) tiene que ser un "
                            f"número mayor que 0.", cod))
    elif r > config.COMPOSICION_LIMITE_RENDIMIENTO:
        # Advertencia y no error: un APU en GLB o KM lleva la cantidad de la obra
        # adentro (15.000 M2 de señalización en un PMT global) y pasa el techo de
        # forma legítima. Bloquearlo dejaba la propuesta sin ningún estado en el que
        # se pudiera aprobar, ni corrigiéndola a mano. La coma corrida (0,5 -> 500),
        # que es el error que motivó el techo, la atrapa RENDIMIENTO_ATIPICO.
        adv.append(Hallazgo("CANTIDAD_SOSPECHOSA",
                            f"El rendimiento de {cod} ({r:g}) supera "
                            f"{config.COMPOSICION_LIMITE_RENDIMIENTO:g}: verificá que "
                            f"la unidad de la actividad sea global.", cod))

    reglas += 1
    if not c.funcion:
        adv.append(Hallazgo("FUNCION_ILEGIBLE",
                            f"No se entendió qué función cumple {cod} en la "
                            f"actividad; revisala antes de aprobar.", cod))

    reglas += 1
    if c.origen == "sin_evidencia":
        motivo = "no declara de dónde sale su rendimiento"
    elif c.origen in _ORIGENES_CON_REFERENCIA and not c.referencias:
        motivo = f"dice venir de un antecedente ({c.origen}) pero no cita ninguno"
    elif c.origen == "calculado_desde_produccion" and c.calculo is None:
        motivo = "dice estar calculado pero no muestra la cuenta"
    elif c.origen == "supuesto_tecnico" and not hay_supuestos:
        motivo = "se apoya en un supuesto técnico que nadie declaró"
    else:
        motivo = ""
    if motivo:
        adv.append(Hallazgo("SIN_EVIDENCIA", f"{cod} {motivo}.", cod))

    # Los rendimientos observados salen de `apu_componentes` filtrando por
    # `tipo='insumo'`: un sub-APU nunca los tiene, y no porque no se use. Aplicarle la
    # regla sería una advertencia que suena siempre y que además miente el conteo.
    if c.tipo != "apu":
        reglas += 1
        obs = ctx.observados.get(c.codigo)
        unidad_cat = ctx.unidades_catalogo.get(c.codigo)
        # Normalizadas de los dos lados: "HR" contra " hr " no es una divergencia, y
        # tomarla por tal se llevaría puesto el RENDIMIENTO_ATIPICO del componente.
        u_obs = (obs.unidad or "").strip().upper() if obs is not None else ""
        u_cat = (unidad_cat or "").strip().upper()
        if obs is None or obs.n < config.COMPOSICION_MIN_ANTECEDENTES:
            adv.append(Hallazgo("SIN_ANTECEDENTES",
                                f"{cod} aparece en {0 if obs is None else obs.n} APUs "
                                f"de la biblioteca: no hay rango contra el cual "
                                f"comparar su rendimiento.", cod))
        elif u_obs and unidad_cat is not None and u_obs != u_cat:
            # `obs.unidad` es la MAYORITARIA de la biblioteca. El caso 4288 N (HR vs
            # JR, ~100x) muestra que si difiere de la del catálogo el rango no compara.
            adv.append(Hallazgo("SIN_ANTECEDENTES",
                                f"{cod} se usa en la biblioteca en {obs.unidad} pero "
                                f"el catálogo lo mide en {unidad_cat}: el rango no "
                                f"compara.", cod))
        elif math.isfinite(r) and not (obs.minimo <= r <= obs.maximo):
            ref = obs.minimo if r < obs.minimo else obs.maximo
            pct = abs(r - ref) / ref * 100 if ref else 0.0
            lado = "por debajo" if r < obs.minimo else "por encima"
            adv.append(Hallazgo("RENDIMIENTO_ATIPICO",
                                f"{r:g} {obs.unidad} queda {pct:.0f} % {lado} del "
                                f"rango observado ({obs.minimo:g}-{obs.maximo:g} "
                                f"{obs.unidad}, n={obs.n}).", cod))

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
    conteo = Counter((c.codigo, c.tipo, c.ref_shift) for c in comps)
    repetidas = sorted({k[0] for k, n in conteo.items() if n > 1})
    if repetidas:
        # UN hallazgo con todos los códigos, no uno por par: es una sola regla, y si
        # emitiera N la métrica `superadas` restaría N por una regla evaluada.
        err.append(Hallazgo(
            "COMPONENTE_DUPLICADO",
            f"{', '.join(_corto(k) for k in repetidas)} aparece más de una vez en la "
            f"composición.",
            _corto(repetidas[0]) if len(repetidas) == 1 else ""))

    reglas += 1
    if not (_FUNCIONES_EJECUCION & funciones):
        adv.append(Hallazgo("FALTA_MANO_DE_OBRA",
                            "La composición no tiene ni mano de obra ni equipo: "
                            "revisá si la actividad es solo de suministro."))

    reglas += 1
    if "mano_de_obra" in funciones and not ({"herramienta", "equipo"} & funciones):
        adv.append(Hallazgo("FALTA_HERRAMIENTA",
                            "Hay cuadrilla pero ni herramienta ni equipo."))

    reglas += 1
    desc = normalizar(ctx.descripcion or "")
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
    hay_supuestos = bool(p.supuestos)

    for c in p.componentes:
        tenia_calculo = c.calculo is not None
        tenia_referencias = bool(c.referencias)
        c, e1, a1 = _recalcular(c)
        c, a2 = _limpiar_referencias(c, ctx)
        # Solo cuentan como regla evaluada si había algo que evaluar.
        reglas += tenia_calculo + tenia_referencias
        errores += e1
        advertencias += a1 + a2
        e, a, n = _validar_componente(c, ctx, hay_supuestos)
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
