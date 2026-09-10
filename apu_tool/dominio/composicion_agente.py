"""Orquestador de la composición asistida.

Hermano de `dominio/revision.py`, y con el mismo reparto: el contrato y el parseo
viven en `dominio/composicion.py`, que no depende de nada; acá se juntan el almacén,
el retriever, la fachada de la IA y el validador. Separado a propósito — si esto
viviera en el contrato, todo el que importe un tipo se comería el `Almacen` y el SDK.

Tres funciones porque hay tres llamadores:
  - `recuperar` arma el contexto (una lectura del catálogo, dos usos).
  - `evaluar` recalcula, valida y puntúa. SIN IA: es el camino del `PUT`, cuando el
    humano guarda una edición y no hay que volver a pagar una generación.
  - `componer` emite los eventos del SSE y usa las dos anteriores.
"""
from __future__ import annotations

from dataclasses import dataclass, replace

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import privacy
# `ApuAdvisor` y `IANoDisponible` se RE-EXPORTAN desde acá, igual que `revision.py`
# re-exporta `IANoDisponible`: `apu_tool/servicio/` no importa `ai_assist` (lo fija
# `tests/test_servicio_privacidad.py::test_servicio_no_importa_ai_assist`), así que la
# capa de servicio construye la fachada a través de su orquestador de dominio y no
# tocando la puerta al SDK. Ese test es lo que mantiene el borde en un solo lugar.
from apu_tool.dominio.ai_assist import PROMPT_VERSION, ApuAdvisor, IANoDisponible
from apu_tool.dominio.compose import InsumoRetriever, rendimientos_observados
from apu_tool.dominio.composicion import Propuesta
from apu_tool.dominio.validacion_composicion import (
    Confianza, ContextoValidacion, Validacion, calcular_confianza, validar,
)


@dataclass(frozen=True)
class ContextoComposicion:
    """Lo recuperado para una composición: lo que va al modelo y lo que valida."""
    insumos: tuple          # CandidateInsumo, con `grupo` lleno
    ejemplos: tuple         # DePricedApu de referencia
    validacion: ContextoValidacion


def recuperar(almacen: Almacen, item, *, apu_codigo_propio: str = "",
              supuestos_confirmados: bool = False) -> ContextoComposicion:
    """Arma el contexto de una composición con UNA lectura del catálogo.

    Esa lectura sirve para dos cosas que si no se harían por separado: el `grupo` de
    cada candidato (que viaja al modelo) y `unidades_catalogo` (que usa el validador
    para saber si un código existe). Una consulta, dos usos.
    """
    insumos, ejemplos = InsumoRetriever(almacen).retrieve(item.descripcion, item.shift)
    codigos = [i.codigo for i in insumos]

    catalogo = almacen.precios.get_candidatos_bulk(codigos)
    grupos, unidades = {}, {}
    for cod, cands in catalogo.items():
        if cands:
            grupos[cod] = cands[0].grupo or ""
            unidades[cod] = cands[0].unidad or ""
    insumos = tuple(replace(i, grupo=grupos.get(i.codigo, "")) for i in insumos)

    # `all_apus` es incondicional: se gana el pan siempre (`apus_existentes` limpia
    # las referencias muertas y `unidades_de_apu` alimenta la señal de unidad de la
    # confianza).
    apus = almacen.apus.all_apus()

    # `componentes_de_apu` alimenta UN solo lector: la detección de ciclos de sub-APU
    # (`_cierra_ciclo`), que devuelve False de entrada cuando no hay código propio —
    # o sea durante toda la generación. Solo al APROBAR existe un código con el que un
    # ciclo sea posible. Cargarlo siempre costaba 5.213 filas por composición: en
    # SQLite 30 ms de 102, pero en Postgres son dos round-trips contra Supabase desde
    # Render, y este repo ya pagó una feature entera por sacar round-trips
    # innecesarios de este mismo camino.
    #
    # La condición es el MISMO campo del que depende el lector, no una copia de su
    # regla: `_cierra_ciclo` corta con `if not propio` y acá se carga con
    # `if apu_codigo_propio`. Por eso no pueden desalinearse, y por eso el árbol vacío
    # no es un falso negativo: cuando está vacío, el lector ya había cortado antes de
    # mirarlo. Si algún día el ciclo se detecta con otra cosa que el código propio,
    # esta condición se mueve con él.
    componentes: dict = {}
    if apu_codigo_propio:
        for (cod, turno), comps in almacen.apus.get_components_bulk(
                [(a.codigo, a.shift) for a in apus]).items():
            componentes[(cod, turno)] = tuple(
                (c.insumo_codigo, c.tipo, c.ref_shift) for c in comps)

    ctx = ContextoValidacion(
        descripcion=item.descripcion, unidad_actividad=item.unidad, shift=item.shift,
        codigos_permitidos=frozenset(codigos),
        unidades_catalogo=unidades,
        apus_existentes=frozenset((a.codigo, a.shift) for a in apus),
        componentes_de_apu=componentes,
        observados=rendimientos_observados(almacen, codigos),
        unidades_de_apu={(a.codigo, a.shift): a.unidad or "" for a in apus},
        apu_codigo_propio=apu_codigo_propio,
        supuestos_confirmados=supuestos_confirmados)
    return ContextoComposicion(tuple(insumos), tuple(ejemplos), ctx)


def evaluar(propuesta: Propuesta, ctx_validacion: ContextoValidacion
            ) -> tuple[Propuesta, Validacion, Confianza]:
    """Recalcula, valida y calcula la confianza. SIN IA.

    Es el camino del `PUT`: guardar una edición humana no vuelve a pagar una
    generación. También lo usa `componer` después de la llamada al modelo, así que la
    propuesta de la IA y la editada a mano pasan por exactamente el mismo filtro.
    """
    corregida, validacion = validar(propuesta, ctx_validacion)
    return corregida, validacion, calcular_confianza(corregida, validacion,
                                                     ctx_validacion)


def componer(almacen: Almacen, item, advisor, *, apu_codigo_propio: str = "",
             supuestos_confirmados: bool = False):
    """Genera una propuesta y emite los eventos del SSE.

      ('recuperando', {'n_insumos', 'n_apus'})
      ('generando',   {})
      ('validando',   {})
      ('lista',       {propuesta, validacion, confianza, confianza_motivos,
                       antecedentes, modelo, prompt_version})
      ('error',       {'detail'})

    Emite eventos y no devuelve un objeto por lo mismo que `revision.revisar`: el
    llamador persiste y reporta en vivo, y una conexión muda demasiado rato la corta
    el proxy. El evento `lista` trae exactamente lo que hay que guardar.

    Una `PrivacyViolation` NO se convierte en un evento `error`: sube. El invariante
    #1 no se maquilla como "no se pudo componer" — mismo criterio que
    `revision.barrer_lote`.
    """
    try:
        ctx = recuperar(almacen, item, apu_codigo_propio=apu_codigo_propio,
                        supuestos_confirmados=supuestos_confirmados)
        yield ("recuperando", {"n_insumos": len(ctx.insumos),
                               "n_apus": len(ctx.ejemplos)})
        if not ctx.insumos:
            # El candado vive acá y no solo en `ApuAdvisor.componer` porque es una
            # regla del orquestador, no de la fachada: sin lista blanca no hay nada
            # entre lo que elegir, y pedírselo igual al modelo es invitarlo a
            # inventar códigos. Un advisor sustituido (o el de mañana) no tiene por
            # qué volver a acordarse.
            raise ValueError(
                "No hay insumos candidatos para esta actividad: revisá la "
                "descripción o agregá el insumo al catálogo.")
        yield ("generando", {})
        cruda = advisor.componer(item, list(ctx.insumos), list(ctx.ejemplos),
                                 ctx.validacion.observados)
        yield ("validando", {})
    except privacy.PrivacyViolation:
        raise                       # el invariante #1 nunca se traga
    except (IANoDisponible, ValueError) as exc:
        yield ("error", {"detail": str(exc)})
        return

    propuesta, validacion, confianza = evaluar(cruda, ctx.validacion)
    yield ("lista", {
        "propuesta": propuesta.to_dict(),
        "validacion": validacion.to_dict(),
        "confianza": confianza.nivel,
        "confianza_motivos": [m.to_dict() for m in confianza.motivos],
        "antecedentes": {
            "codigos_permitidos": sorted(ctx.validacion.codigos_permitidos),
            "apus_referencia": [{"codigo": a.codigo, "turno": a.shift}
                                for a in ctx.ejemplos],
        },
        "modelo": advisor.model,
        "prompt_version": PROMPT_VERSION,
    })
