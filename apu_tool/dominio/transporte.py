"""
Desviaciones de un proyecto respecto de la biblioteca de APUs.

Dos capas sobre la composición que devuelve la biblioteca:
  1. REGLA de transporte: el rendimiento de un componente de acarreo clasificado
     pasa a ser `volumen × km_de_su_categoría` (el volumen sale de la
     clasificación de la biblioteca; los km, de los parámetros del proyecto).
  2. AJUSTES del proyecto: excepciones explícitas (rendimiento / agregar /
     quitar / reemplazar) que GANAN sobre la regla.

La composición de la biblioteca NUNCA se muta: se devuelve una lista nueva.

Este módulo no ve dinero. El precio del peaje lo aplica `dominio/pricing.py`,
el único módulo que ve dinero. `cargar_contexto` es lo único que lee la base
(mismo criterio que `PricingEngine`, que también recibe el `Almacen`).

IDENTIDAD: un componente se reconoce por código + nombre normalizado, nunca por
código solo — en el catálogo 6 de los 9 códigos de transporte tienen homónimo
(`7462` es también NIPLE 16", `6878` también CONCRETO 3000 PSI). Misma lección
que el fix de detección de sub-APUs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Optional, Sequence

from apu_tool import config
from apu_tool.nucleo.models import (
    AjusteProyecto, ApuComponent, ClaseTransporte, ParametrosProyecto,
)
from apu_tool.nucleo.texto import normalizar

# Los ajustes se aplican en este orden para que 'agregar' pueda reponer algo que
# 'quitar' sacó y para que 'rendimiento' actúe sobre el insumo ya reemplazado.
ORDEN_ACCIONES = ("quitar", "reemplazar", "rendimiento", "agregar")

Clasificacion = dict[tuple[str, str, str], ClaseTransporte]


@dataclass(frozen=True)
class ContextoProyecto:
    """Todo lo que el motor necesita para costear con las desviaciones del proyecto."""
    params: ParametrosProyecto
    clasificacion: Clasificacion
    ajustes: tuple[AjusteProyecto, ...] = ()

    @property
    def vacio(self) -> bool:
        return self.params.vacio and not self.ajustes


def _codigo_base(codigo: str) -> str:
    """`"INT3 N"` -> `"INT3"`. Los nocturnos comparten identidad de insumo."""
    cod = (codigo or "").strip()
    return cod[:-2].strip() if cod.upper().endswith(" N") else cod


def _mismo(comp: ApuComponent, codigo: str, nombre: str) -> bool:
    """Identidad de un componente: código base (sin la marca nocturna) + nombre
    normalizado. Los DOS lados se normalizan: un ajuste guardado con el código
    literal de una composición nocturna ("3017 N") tiene que encontrar su
    componente igual. Mismo criterio que `autoria._es_gemelo_nocturno`."""
    return (_codigo_base(comp.insumo_codigo) == _codigo_base(codigo)
            and normalizar(comp.insumo_nombre) == normalizar(nombre))


def es_peaje(comp: ApuComponent) -> bool:
    return _mismo(comp, *config.PEAJE)


def es_derechos(comp: ApuComponent) -> bool:
    return _mismo(comp, *config.DERECHOS_BOTADERO)


def _clase_de(comp: ApuComponent, apu_codigo: str, shift: str,
              clasificacion: Clasificacion) -> Optional[ClaseTransporte]:
    cls = clasificacion.get((apu_codigo, shift, comp.insumo_codigo))
    if cls is None:
        return None
    # El nombre manda: la clasificación es de UN insumo, no de un código.
    if normalizar(cls.insumo_nombre) != normalizar(comp.insumo_nombre):
        return None
    return cls


def _escalable(comp: ApuComponent) -> bool:
    """Un componente que escala con la distancia: insumo (no sub-APU), en M3-KM,
    que no es el peaje ni los derechos de botadero."""
    return ((comp.tipo or "insumo") != "apu"
            and normalizar(comp.unidad) == normalizar(config.UNIDAD_TRANSPORTE)
            and not es_peaje(comp) and not es_derechos(comp))


def _km_util(params: ParametrosProyecto, categoria: str) -> Optional[float]:
    """El km de una categoría solo sirve si es > 0. Un 0 (o un negativo) es un dato
    inválido, no una distancia: reescalar con él dejaría el acarreo en $0 y la regla
    de negocio prohíbe un $0 silencioso, así que se trata como 'sin definir' y lo
    delata `pendientes`."""
    km = params.km(categoria)
    return km if km is not None and km > 0 else None


def pendientes(componentes: Sequence[ApuComponent], apu_codigo: str, shift: str,
               params: Optional[ParametrosProyecto],
               clasificacion: Optional[Clasificacion]) -> tuple[str, ...]:
    """Códigos de componentes de acarreo que el proyecto NO pudo reescalar porque
    les falta clasificación. Son los que alertan: preferimos avisar a costear con
    una distancia equivocada en silencio."""
    if params is None or params.vacio:
        return ()
    clasificacion = clasificacion or {}
    faltan = []
    for c in componentes:
        if not _escalable(c):
            continue
        cls = _clase_de(c, apu_codigo, shift, clasificacion)
        if cls is None or _km_util(params, cls.categoria) is None:
            faltan.append(c.insumo_codigo)
    return tuple(faltan)


def aplicar(componentes: Iterable[ApuComponent], apu_codigo: str, shift: str,
            params: Optional[ParametrosProyecto] = None,
            clasificacion: Optional[Clasificacion] = None,
            ajustes: Sequence[AjusteProyecto] = ()) -> list[ApuComponent]:
    """Composición EFECTIVA del proyecto. Sin parámetros ni ajustes devuelve la
    misma composición (garantía de no regresión)."""
    comps = list(componentes)
    if params is not None and not params.vacio:
        comps = _aplicar_regla(comps, apu_codigo, shift, params, clasificacion or {})
    if ajustes:
        comps = _aplicar_ajustes(comps, apu_codigo, shift, ajustes)
    return comps


def _aplicar_regla(comps: list[ApuComponent], apu_codigo: str, shift: str,
                   params: ParametrosProyecto,
                   clasificacion: Clasificacion) -> list[ApuComponent]:
    salida: list[ApuComponent] = []
    for c in comps:
        if (c.tipo or "insumo") == "apu":
            salida.append(c)               # el sub-APU se reescala en su propia pasada
            continue
        if es_peaje(c):
            if params.peaje_aplica is False:
                continue                   # se QUITA: un peaje en $0 está prohibido
            salida.append(c)               # el valor lo pone pricing.py
            continue
        if es_derechos(c) or not _escalable(c):
            salida.append(c)               # volumen, no distancia
            continue
        cls = _clase_de(c, apu_codigo, shift, clasificacion)
        km = _km_util(params, cls.categoria) if cls is not None else None
        if cls is None or km is None:
            salida.append(c)               # sin clasificar o sin km: intacto (ver pendientes)
            continue
        salida.append(replace(c, rendimiento=round(cls.volumen * float(km), 6)))
    return salida


def _aplicar_ajustes(comps: list[ApuComponent], apu_codigo: str, shift: str,
                     ajustes: Sequence[AjusteProyecto]) -> list[ApuComponent]:
    mios = [a for a in ajustes if a.apu_codigo == apu_codigo and a.shift == shift]
    if not mios:
        return comps
    salida = list(comps)
    for accion in ORDEN_ACCIONES:
        for a in (x for x in mios if x.accion == accion):
            salida = _un_ajuste(salida, a, apu_codigo, shift)
    return salida


def _un_ajuste(comps: list[ApuComponent], a: AjusteProyecto,
               apu_codigo: str, shift: str) -> list[ApuComponent]:
    if a.accion in ("rendimiento", "agregar") and not (a.rendimiento and a.rendimiento > 0):
        # Fila corrupta (la API exige rendimiento > 0 al crearla): se ignora este
        # ajuste en vez de tumbar el costeo de toda la corrida con un TypeError.
        return comps
    if a.accion == "quitar":
        return [c for c in comps if not _mismo(c, a.insumo_codigo, a.insumo_nombre)]
    if a.accion == "reemplazar":
        # `precio_unitario_hist=0.0` a propósito: el histórico embebido es del insumo
        # VIEJO. Conservarlo costearía el insumo nuevo con el precio del viejo en
        # silencio; con 0 cae a "sin precio" y la alerta lo delata. La unidad nueva
        # gana si el ajuste la trae: dejar la vieja podría hacer que una pasada
        # futura de la regla trate el insumo nuevo como acarreo (M3-KM) por error.
        return [replace(c, insumo_codigo=a.insumo_nuevo_codigo,
                        insumo_nombre=a.insumo_nuevo_nombre,
                        unidad=(a.unidad or c.unidad),
                        precio_unitario_hist=0.0)
                if _mismo(c, a.insumo_codigo, a.insumo_nombre) else c
                for c in comps]
    if a.accion == "rendimiento":
        return [replace(c, rendimiento=float(a.rendimiento))
                if _mismo(c, a.insumo_codigo, a.insumo_nombre) else c
                for c in comps]
    if a.accion == "agregar":
        # Idempotente: si ya está, solo se ajusta el rendimiento (no se duplica).
        if any(_mismo(c, a.insumo_codigo, a.insumo_nombre) for c in comps):
            return [replace(c, rendimiento=float(a.rendimiento))
                    if _mismo(c, a.insumo_codigo, a.insumo_nombre) else c
                    for c in comps]
        return comps + [ApuComponent(
            apu_codigo=apu_codigo, shift=shift, insumo_codigo=a.insumo_codigo,
            insumo_nombre=a.insumo_nombre, unidad=a.unidad,
            rendimiento=float(a.rendimiento), precio_unitario_hist=0.0,
            tipo=a.tipo or "insumo", ref_shift=a.ref_shift or "")]
    return comps
