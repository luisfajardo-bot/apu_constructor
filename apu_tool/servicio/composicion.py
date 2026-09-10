"""
Lógica de servicio del expediente de composición asistida.

Hermano de `servicio/corridas.py`: no habla HTTP y no habla con el SDK; orquesta el
dominio (`dominio/composicion_agente.py`), la persistencia (`alm.composiciones`) y,
al aprobar, las dos capas que ya existen y NO se reimplementan — `servicio/autoria.py`
(unicidad, gemelo día/noche, auditoría del alta) y `servicio/corridas.py`
(`confirmar_item`, el único camino por el que una fila cambia de APU).

No importa `pricing` ni ningún módulo que vea dinero: la actividad se persiste
des-monetizada (`privacy.licitacion_item_to_dict`) para que la fila entera se pueda
reinyectar hacia la IA sin volver a filtrarla.
"""
from __future__ import annotations

import logging
from dataclasses import replace
from datetime import datetime
from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.datos.repositorio import CorridaEliminada, VersionYaExiste
from apu_tool.dominio import composicion_agente, privacy
# Re-exportadas por el orquestador de dominio a propósito: ningún módulo de
# `servicio/` importa la fachada del SDK: lo fija `tests/test_servicio_privacidad`
# buscando el nombre de ese módulo como TEXTO en cada archivo de `servicio/`, así
# que tampoco se lo nombra en un comentario. Mismo camino que `corridas.py`, que
# toma `IANoDisponible` de `dominio/revision`.
from apu_tool.dominio.composicion_agente import (
    PROMPT_VERSION, ApuAdvisor, IANoDisponible,
)
from apu_tool.dominio.composicion import propuesta_desde_json
from apu_tool.nucleo.models import ComposicionRow, CorridaItemRow
from apu_tool.servicio import autoria
from apu_tool.servicio.auditoria import registrar_auditoria
from apu_tool.servicio.corridas import CorridaCongelada, confirmar_item

logger = logging.getLogger(__name__)


class ComposicionInvalida(Exception):
    """Se intentó aprobar una propuesta con errores bloqueantes.

    No es un 400 (el cuerpo está bien formado) ni un 409 (no hay conflicto de
    estado): es una entidad que el dominio rechaza. El endpoint contesta 422.
    """

    def __init__(self, mensaje: str, errores=()):
        super().__init__(mensaje)
        self.errores = list(errores)


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _email(actor) -> Optional[str]:
    return getattr(actor, "email", None)


def _es_de_esta_linea(v: ComposicionRow, row: CorridaItemRow) -> bool:
    """¿El expediente `v` habla de la actividad que hoy está en esa fila?

    El `seq` SE REUSA. La FK del expediente apunta a `corrida`, no a `corrida_item`,
    así que sobrevive al borrado de su línea; y `agregar_items` numera con
    `max(seq) + 1`, así que borrar la última línea y agregar otra le da el mismo
    número. Sin este filtro, `vigente(cid, seq)` devolvería el expediente de OTRA
    actividad — y si esa versión quedó `aprobada`, aprobar contestaría 409 nombrando
    un APU ajeno y la línea de hoy no se podría componer nunca más.

    Es exactamente la protección que el repo ya usa para el veredicto de la revisión
    (`revision_json` con `apu_evaluado`, ver `corridas._vista_item`): la fila guarda
    con qué se la evaluó y no se devuelve si ya no coincide. Nada se borra y el
    append-only queda intacto — el expediente es CACHÉ, no verdad.

    Se compara solo la `descripcion` y no el dict entero a propósito: la descripción
    es lo que identifica la actividad y lo único de lo que habla la propuesta.
    Cambiarle la cantidad (o corregirle la unidad) no la convierte en otra cosa, y
    comparar el dict completo tiraría expedientes buenos por un decimal.
    """
    return (v.actividad or {}).get("descripcion") == row.item.descripcion


def _exigir_activa(alm: Almacen, corrida_id: int):
    """La meta de la corrida, o None si no existe. Lanza CorridaCongelada.

    Una corrida congelada es una foto inmutable: ni se compone, ni se edita, ni se
    aprueba contra ella. Es el mismo candado de `confirmar_items` — y cubre el caso
    de que alguien congele ENTRE la generación y la aprobación, porque cada endpoint
    que escribe vuelve a pasar por acá.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    return meta


def _exigir_version(v: ComposicionRow, version_base: int) -> None:
    """La versión sobre la que trabajó el usuario tiene que ser la vigente.

    El índice único `ux_composicion_version` es el guardián de la concurrencia real
    (dos peticiones a milisegundos leen la misma vigente y las dos creen escribir la
    siguiente). Este chequeo previo cubre lo que el índice no puede: un
    `version_base` MAYOR que la vigente escribiría un número libre y abriría un hueco
    en el historial, y en `aprobar` el índice llegaría tarde — para cuando choca, el
    APU ya está creado. Se levanta la MISMA excepción que el índice para que el
    endpoint tenga una sola traducción a 409.
    """
    if int(version_base) != v.version:
        raise VersionYaExiste(v.corrida_id, v.seq, int(version_base) + 1)


def _sello(corrida_id: int, row: CorridaItemRow, base: Optional[ComposicionRow], *,
           version: int, estado: str, autor: Optional[str], **cambios
           ) -> ComposicionRow:
    """Una versión nueva del expediente, heredando de `base` lo que no cambia.

    `actividad` se guarda SIEMPRE des-monetizada: `licitacion_item_to_dict` y nunca
    el `LicitacionItem` crudo, que trae `precio_contractual`. Ningún módulo de
    `datos/` lo impide, así que el punto de paso es este.
    """
    datos = dict(
        id=None, corrida_id=corrida_id, seq=row.seq, version=version, estado=estado,
        actividad=privacy.licitacion_item_to_dict(row.item),
        ficha=base.ficha if base else None,
        propuesta=base.propuesta if base else None,
        validacion=base.validacion if base else None,
        confianza=base.confianza if base else None,
        confianza_motivos=base.confianza_motivos if base else None,
        antecedentes=base.antecedentes if base else None,
        modelo=base.modelo if base else None,
        prompt_version=base.prompt_version if base else None,
        apu_codigo=None, apu_turno=None, autor=autor, creada_en=_ahora(),
        motivo=None)
    datos.update(cambios)
    return ComposicionRow(**datos)


# ------------------------------------------------------------------- lectura
def vista(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    """El expediente de una fila, o None si la fila no existe (endpoint -> 404).

    La VIGENTE se descarta si no es de esta línea (ver `_es_de_esta_linea`); el
    HISTORIAL se devuelve completo, porque es el registro de correcciones y no miente
    sobre nada: cada versión dice de qué actividad hablaba.

    `catalogo` enriquece la RESPUESTA (ver `_catalogo_de`), y como los cuatro
    endpoints que devuelven el expediente salen por acá, los nombres no se pierden
    después de guardar una edición ni de aprobar.
    """
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    # Mismo camino que `_exigir_activa`, pero sin lanzar: acá la lectura vale
    # también con la corrida congelada, así que no hay 409 que levantar.
    meta = alm.corridas.get_corrida(corrida_id)
    # Una sola consulta: la vigente es la última del historial (viene ordenado por
    # `version`), así que pedir las dos cosas serían dos round-trips por lo mismo.
    hist = alm.composiciones.historial(corrida_id, seq)
    vig = hist[-1] if hist else None
    if vig is not None and not _es_de_esta_linea(vig, row):
        vig = None
    return {"vigente": vig.to_dict() if vig else None,
            "historial": [h.to_dict() for h in hist],
            "catalogo": _catalogo_de(alm, vig),
            # El modo de la corrida viaja con el expediente para que la mesa pueda
            # apagarse ANTES del primer clic, en vez de dejar los botones habilitados y
            # contestar 409 cuando el usuario ya editó. Sale de la metadata que esta
            # función ya carga: cero consultas nuevas. Es una foto del momento de cargar
            # —si la congelan con la mesa abierta, el 409 sigue siendo la red— y eso es
            # deliberado: cubrir ese caso pedía un poll, que este repo no hace.
            "corrida_modo": meta.modo,
            # Igual criterio que `seqs_sin_apu` (nucleo/models.py no aplica acá: esa
            # firma —"sin componentes y costo > 0"— pide haber costeado, y esta
            # función no importa `pricing` a propósito). `row.costo_manual` ya está
            # cargado, así que no hace falta: mismo `> 0` y no `is not None`, para que
            # un costo puesto a mano en 0 (o NaN) no dispare el aviso de más abajo.
            # La mesa lo necesita para avisar ANTES de aprobar que un APU real borra
            # este costo declarado (`actualizar_eleccion` lo hace solo).
            "costo_a_mano": (row.costo_manual or 0) > 0}


def _catalogo_de(alm: Almacen, v: Optional[ComposicionRow]) -> dict[str, dict]:
    """Nombre, unidad y grupo de cada código de la propuesta vigente.

    Va en la RESPUESTA y no en la fila persistida a propósito: la propuesta guarda
    lo que dijo el modelo, que es solo el código; el nombre lo pone el catálogo y
    tiene que leerse fresco, o quedaría viejo el día que alguien renombre un insumo.
    Sin esto la mesa muestra "4279 · 0,62 · mano_de_obra", que no se puede revisar.

    Se copian los TRES campos clave por clave: `get_candidatos_bulk` devuelve
    `Insumo`, que lleva `precio`, y volcar el objeto entero sacaría dinero por la API
    de la composición. Es la misma regla que `privacy.rendimiento_observado_to_dict`
    —copiar campo por campo en el borde— y por eso un campo nuevo en `Insumo` no
    viaja solo por existir.

    Un código que el catálogo no tiene simplemente NO aparece en el mapa: la mesa
    muestra el código pelado, que es lo correcto — el validador ya emitió
    `CODIGO_INEXISTENTE` y eso es justo lo que el usuario tiene que ver.

    Una consulta en lote, no una por componente.
    """
    comps = ((v.propuesta or {}).get("componentes") or []) if v else []
    codigos = [str(c.get("codigo", "")) for c in comps if c.get("codigo")]
    if not codigos:
        return {}
    out: dict[str, dict] = {}
    for cod, cands in alm.precios.get_candidatos_bulk(codigos).items():
        if cands:
            out[cod] = {"nombre": cands[0].nombre, "unidad": cands[0].unidad,
                        "grupo": cands[0].grupo}
    return out


def _expediente(alm: Almacen, corrida_id: int, seq: int):
    """(fila, historial, vigente-de-esta-línea) para los caminos que escriben.
    Cualquiera de los tres en None significa 404 para el endpoint."""
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None, [], None
    hist = alm.composiciones.historial(corrida_id, seq)
    ultima = hist[-1] if hist else None
    vig = ultima if (ultima is not None and _es_de_esta_linea(ultima, row)) else None
    return row, hist, vig


# ----------------------------------------------------------------- generación
def generar_stream(alm: Almacen, corrida_id: int, seq: int, actor=None):
    """Devuelve el generador de eventos SSE, o None si la corrida o la fila no existen.

    Función normal (no generador) a propósito, igual que `revisar_corrida_stream`:
    todo lo que puede fallar antes de empezar —congelada, fila inexistente, sin
    credencial— se valida ACÁ, con el stream todavía cerrado. Si no, el error saldría
    con la respuesta ya abierta y el cliente vería un 200 que muere solo.

    Lanza CorridaCongelada (409) e IANoDisponible (503).
    """
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    if not config.ai_available():
        # Mismo criterio que `revisar_corrida_stream`: acá se mira solo la credencial
        # (que es lo que el operador puede arreglar) y el caso "el SDK no está
        # instalado" sale como evento `error` desde el advisor, ya con el stream
        # abierto.
        raise IANoDisponible(
            "Componer un APU con IA necesita ANTHROPIC_API_KEY en el servidor.")
    # La versión siguiente sale del historial CRUDO, no de la vigente filtrada: el
    # índice único es por (corrida_id, seq, version) y no le importa de qué actividad
    # hablaba la versión anterior. Un expediente de otra actividad queda abajo, la
    # generación nueva pasa a ser la vigente y la línea se destraba sola.
    hist = alm.composiciones.historial(corrida_id, seq)
    siguiente = (hist[-1].version + 1) if hist else 1
    return _eventos(alm, corrida_id, row, ApuAdvisor(), siguiente, _email(actor))


def _eventos(alm: Almacen, corrida_id: int, row: CorridaItemRow, advisor,
             version: int, autor: Optional[str]):
    """Generador puro: corre el agente y persiste el resultado apenas sale.

    Persiste DOS de los cinco eventos: `lista` como versión `propuesta` y `error`
    como versión `error`. Un fallo también es parte del expediente — si no, el
    usuario reintenta sin que quede rastro de que ya falló una vez.

    Cualquier otro fallo sube al `_event_stream` del endpoint, que lo loggea; en
    particular la `PrivacyViolation`, que `composicion_agente.componer` re-lanza a
    propósito y acá tampoco se traga (invariante #1).
    """
    for evento, payload in composicion_agente.componer(alm, row.item, advisor):
        if evento == "lista":
            fila = _sello(
                corrida_id, row, None, version=version, estado="propuesta",
                autor=autor, propuesta=payload["propuesta"],
                validacion=payload["validacion"], confianza=payload["confianza"],
                confianza_motivos=payload["confianza_motivos"],
                antecedentes=payload["antecedentes"], modelo=payload["modelo"],
                prompt_version=payload["prompt_version"])
            try:
                alm.composiciones.agregar(fila)
            except (VersionYaExiste, CorridaEliminada) as exc:
                # La propuesta existe pero no se pudo guardar: el cliente tiene que
                # enterarse, no recibir un `lista` que después no está en el GET.
                yield ("error", {"detail": str(exc)})
                return
            payload = dict(payload, version=version)   # el PUT necesita `version_base`
        elif evento == "error":
            try:
                alm.composiciones.agregar(_sello(
                    corrida_id, row, None, version=version, estado="error",
                    autor=autor, prompt_version=PROMPT_VERSION,
                    motivo=payload.get("detail", "")))
            except (VersionYaExiste, CorridaEliminada):
                logger.warning("No se pudo registrar el error de composición %s/%s",
                               corrida_id, row.seq)   # el evento igual va al cliente
        yield (evento, payload)


# ------------------------------------------------------------ edición humana
def guardar_edicion(alm: Almacen, corrida_id: int, seq: int, datos: dict,
                    actor=None) -> Optional[dict]:
    """Guarda la propuesta que dejó una persona y la REVALIDA sin IA.

    Devuelve None si la corrida, la fila o el expediente de esta línea no existen.
    Lanza CorridaCongelada (409) y VersionYaExiste (409).

    La lista blanca sale de `_lista_blanca` (la persistida, más lo que agregó la
    persona) y NO del `recuperar` fresco, cuyo `codigos_permitidos` se descarta. El
    resto del contexto sí es de hoy: unidades del catálogo, APUs existentes,
    rendimientos observados.
    """
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row, _, vig = _expediente(alm, corrida_id, seq)
    if row is None or vig is None:
        return None
    _exigir_version(vig, datos["version_base"])

    comps = [dict(c) for c in datos.get("componentes", []) or []]
    previa = vig.propuesta or {}
    # Se reusa el parser del contrato (`propuesta_desde_json`) en vez de construir los
    # dataclasses a mano: la edición humana pasa por el MISMO acotado de textos y la
    # misma degradación conservadora de campos ilegibles que la respuesta del modelo.
    cruda = propuesta_desde_json({
        "componentes": comps,
        "supuestos": previa.get("supuestos", []),
        "incertidumbre_declarada": previa.get("incertidumbre_declarada", 0.0),
        "justificacion": previa.get("justificacion", ""),
    })
    ctx = composicion_agente.recuperar(
        alm, row.item,
        supuestos_confirmados=bool(datos.get("supuestos_confirmados")))
    blanca = _lista_blanca(vig, comps)
    propuesta, validacion, confianza = composicion_agente.evaluar(
        cruda, _con_lista_blanca(alm, ctx.validacion, blanca))

    fila = _sello(
        corrida_id, row, vig, version=vig.version + 1, estado="editada",
        autor=_email(actor), propuesta=propuesta.to_dict(),
        validacion=validacion.to_dict(), confianza=confianza.nivel,
        confianza_motivos=[m.to_dict() for m in confianza.motivos],
        # Las dos mitades de `antecedentes` con la MISMA política: la lista blanca
        # ampliada (no una re-derivada de un retrieve nuevo) y los APUs de referencia
        # de la generación. Es lo que la próxima edición va a leer como base.
        antecedentes={"codigos_permitidos": sorted(blanca),
                      "apus_referencia": (vig.antecedentes or {}).get(
                          "apus_referencia", [])})
    alm.composiciones.agregar(fila)
    return vista(alm, corrida_id, seq)


def _lista_blanca(vigente: ComposicionRow, componentes: list[dict]) -> frozenset[str]:
    """La lista blanca de esta composición: la de la generación, más lo que agregó
    una persona.

    Solo CRECE, nunca se re-deriva de un `recuperar` fresco. Un retrieve nuevo puede
    dar una lista más chica que la de la generación (un insumo nuevo desplaza a otro
    fuera de los 40, alguien oculta uno), y entonces un componente que el modelo
    propuso legítimamente pasaría a CODIGO_NO_AUTORIZADO al guardar un cambio de
    rendimiento que no tiene nada que ver — y desde la mesa no hay forma de
    arreglarlo.

    La lista existe para que el MODELO no invente códigos. Una persona que elige del
    buscador del catálogo no está inventando: para ella el guardián es
    CODIGO_INEXISTENTE, que sí mira el catálogo de verdad.
    """
    previos = set((vigente.antecedentes or {}).get("codigos_permitidos", []))
    return frozenset(previos | {str(c.get("codigo", "")) for c in componentes})


def _con_lista_blanca(alm: Almacen, ctx, blanca: frozenset[str]):
    """El contexto de hoy, con la lista blanca de la composición puesta encima.

    `unidades_catalogo` se completa con una consulta REAL por los códigos que la
    lista blanca trae y el retrieve no: es lo que mira `CODIGO_INEXISTENTE`, y
    dejarlo como vino haría saltar ese error sobre insumos que existen — el guardián
    que le queda a la edición humana daría falsos positivos justo cuando la persona
    tiene razón. Los que el catálogo no confirma NO se agregan: ahí el error es
    correcto.
    """
    faltan = sorted(c for c in blanca if c and c not in ctx.unidades_catalogo)
    unidades = dict(ctx.unidades_catalogo)
    if faltan:
        for cod, cands in alm.precios.get_candidatos_bulk(faltan).items():
            if cands:
                unidades[cod] = cands[0].unidad or ""
    return replace(ctx, codigos_permitidos=blanca, unidades_catalogo=unidades)


# ------------------------------------------------------------------- decisión
def _componentes_para_autoria(propuesta: Optional[dict], turno: str) -> list[dict]:
    """La propuesta en el formato que espera `autoria._componentes_de`.

    Nombre y unidad NO se mandan: los resuelve autoría desde el catálogo, que es la
    fuente. `ref_shift` se completa con el turno del APU cuando falta, igual que hace
    el validador (`c.ref_shift or ctx.shift`): un sub-APU sin turno explícito es el
    del mismo turno.
    """
    out = []
    for c in (propuesta or {}).get("componentes", []) or []:
        tipo = c.get("tipo") or "insumo"
        out.append({"insumo_codigo": c.get("codigo", ""),
                    "rendimiento": c.get("rendimiento"),
                    "tipo": tipo,
                    "ref_shift": (c.get("ref_shift") or turno) if tipo == "apu" else ""})
    return out


def aprobar(alm: Almacen, corrida_id: int, seq: int, datos: dict,
            actor=None) -> Optional[dict]:
    """Crea el APU de la propuesta vigente y se lo asigna a la fila.

    Devuelve None si la corrida, la fila o el expediente de esta línea no existen
    (endpoint -> 404). Lanza CorridaCongelada y VersionYaExiste (409),
    ComposicionInvalida (422: rechazada, o con errores bloqueantes) y el ValueError
    de `autoria.crear_apu` (422).

    Los componentes salen de la VERSIÓN VIGENTE, nunca del cuerpo: aprobar no es una
    oportunidad de editar. Lo único que pone el humano acá es la identidad del APU
    (código, turno, nombre, grupo), y esas reglas —unicidad, gemelo día/noche,
    auditoría del alta— son de `autoria.crear_apu` y NO se reimplementan.

    COSTURA DE DOS BASES, conocida y sin arreglo barato: `crear_apu` escribe en
    `apus.db` y el sello de la aprobación en `corridas.db`. No hay transacción común,
    así que si el sello falla el APU ya existe y el expediente no lo sabe. Se ordena
    de lo irreversible a lo recuperable —crear, sellar, asignar— y el fallo se loggea
    con el código creado y sube como 500: no sale en silencio. Si falla el último
    paso, la fila se arregla sola reasignando el APU desde el buscador, que ya existe.

    Antes de crear nada se REVALIDA contra el estado de hoy y con el código que el
    humano acaba de elegir (ver el comentario largo más abajo): la validación
    guardada es caché de otro momento y se calculó sin código propio.
    """
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row, _, vig = _expediente(alm, corrida_id, seq)
    if row is None or vig is None:
        return None
    _exigir_version(vig, datos["version_base"])
    if vig.estado == "rechazada":
        # `rechazada` tiene que significar algo: si de ahí se salta directo a
        # `aprobada`, el estado es una etiqueta decorativa. La vía para arrepentirse
        # existe y es gratis — editar y guardar produce una versión `editada` sobre
        # la que sí se aprueba, y ese paso queda en el historial. Así un cambio de
        # opinión se ve, en vez de que una aprobación pise un rechazo sin rastro.
        # El guardián NO está en `guardar_edicion`: editar una rechazada es
        # justamente el camino de reapertura.
        raise ComposicionInvalida(
            "Esta composición está rechazada. Si querés retomarla, editala y "
            "guardá: eso abre una versión nueva que sí se puede aprobar.")
    if not (vig.validacion or {}).get("valido"):
        # Lo que quedó registrado como inválido no se aprueba, aunque hoy validara:
        # el camino para eso es corregirlo en la mesa (PUT), que deja su propia
        # versión con su propia validación.
        raise ComposicionInvalida(
            "La propuesta guardada tiene errores bloqueantes: corregila en la mesa "
            "o rechazala, no se puede aprobar así.",
            (vig.validacion or {}).get("errores") or [])

    turno = str(datos.get("turno") or row.shift or "").strip().upper()
    codigo = str(datos.get("codigo", "") or "").strip()
    comps = (vig.propuesta or {}).get("componentes", []) or []
    # Revalidar y NO confiar en `vigente.validacion`, por dos razones que se suman:
    #
    # 1) La validación guardada se calculó SIN código propio (durante la generación
    #    todavía no existe), y `_cierra_ciclo` corta de entrada sin él. Si no
    #    revalidamos acá, nadie pasa nunca `apu_codigo_propio` y la detección de
    #    ciclos de sub-APU es decoración: parece implementada y no corre. Hoy no
    #    puede haber ciclos (el esquema acota `tipo` a "insumo"), pero en la fase 3
    #    nadie iba a sospechar del guardián.
    # 2) Entre generar y aprobar pasan minutos: un insumo oculto, un APU de
    #    referencia borrado. La caché no es verdad — la misma decisión que ya tomó
    #    este repo con `revision_json` y `apu_evaluado`.
    #
    # `supuestos_confirmados=True`: al aprobar, el humano está confirmando lo que ve.
    ctx = composicion_agente.recuperar(alm, row.item, apu_codigo_propio=codigo,
                                       supuestos_confirmados=True)
    _, validacion, _ = composicion_agente.evaluar(
        propuesta_desde_json(vig.propuesta),
        _con_lista_blanca(alm, ctx.validacion, _lista_blanca(vig, comps)))
    if not validacion.valido:
        raise ComposicionInvalida(
            "La composición ya no es válida: "
            + "; ".join(h.mensaje for h in validacion.errores),
            [h.to_dict() for h in validacion.errores])

    apu = autoria.crear_apu(alm, {
        "codigo": codigo,
        "turno": turno,
        "nombre": datos.get("nombre", ""),
        # La unidad de la actividad es la del APU salvo que el humano diga otra: el
        # rendimiento propuesto está expresado POR esa unidad.
        "unidad": datos.get("unidad") or row.item.unidad,
        "grupo": datos.get("grupo", ""),
        "componentes": _componentes_para_autoria(vig.propuesta, turno),
    }, actor=actor)

    try:
        # Sello y auditoría en UNA transacción de `corridas` (la conexión ve
        # `composicion` y, por el ATTACH, `auditoria`): mismo patrón que
        # `corridas.igualar_costo_al_contractual`.
        #
        # Se audita ADEMÁS de lo que ya audita `autoria.crear_apu`, y la redundancia
        # es deliberada: ese evento dice "se creó el APU 9001" (biblioteca), este
        # dice "se aprobó una propuesta de IA para tal línea, versión N, con tal
        # confianza" (el agente). Auditar el agente es lo que no se puede reconstruir
        # desde el otro.
        with alm.transaccion("corridas") as conn:
            alm.composiciones.agregar(_sello(
                corrida_id, row, vig, version=vig.version + 1, estado="aprobada",
                autor=_email(actor), apu_codigo=apu["codigo"],
                apu_turno=apu["turno"]), conn=conn)
            registrar_auditoria(
                alm, conn, actor, "composicion.aprobar", "corrida", corrida_id,
                antes=None, despues={"apu_codigo": apu["codigo"],
                                     "apu_turno": apu["turno"],
                                     "n_componentes": apu["n_componentes"]},
                contexto={"seq": seq, "version": vig.version + 1,
                          "confianza": vig.confianza,
                          "modelo": vig.modelo,
                          "prompt_version": vig.prompt_version})
    except Exception:
        logger.exception(
            "El APU %s (%s) se creó pero la aprobación de la composición %s/%s no se "
            "pudo sellar: el APU existe y hay que asignarlo a mano.",
            apu["codigo"], apu["turno"], corrida_id, seq)
        raise
    out = vista(alm, corrida_id, seq) or {}
    out["apu"] = apu
    # `confirmar_item` es el ÚNICO camino por el que una fila cambia de APU (recostea,
    # borra el veredicto viejo y el costo puesto a mano). Devuelve la vista de la
    # corrida, que el cliente necesita igual: se pasa y se ahorra un round-trip.
    out["corrida"] = confirmar_item(alm, corrida_id, seq, apu["codigo"], turno)
    return out


def rechazar(alm: Almacen, corrida_id: int, seq: int, datos: dict,
             actor=None) -> Optional[dict]:
    """Sella una versión `rechazada` con el motivo. No toca corrida, biblioteca ni
    catálogo: es una anotación en el expediente, y la fila sigue sin APU.

    Devuelve None si la corrida, la fila o el expediente de esta línea no existen.
    Lanza CorridaCongelada y VersionYaExiste (409).
    """
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row, _, vig = _expediente(alm, corrida_id, seq)
    if row is None or vig is None:
        return None
    _exigir_version(vig, datos["version_base"])
    motivo = str(datos.get("motivo", "") or "")[:500]
    with alm.transaccion("corridas") as conn:
        alm.composiciones.agregar(_sello(
            corrida_id, row, vig, version=vig.version + 1, estado="rechazada",
            autor=_email(actor), motivo=motivo), conn=conn)
        registrar_auditoria(
            alm, conn, actor, "composicion.rechazar", "corrida", corrida_id,
            antes=None, despues=None,
            contexto={"seq": seq, "version": vig.version + 1, "motivo": motivo,
                      "confianza": vig.confianza, "modelo": vig.modelo,
                      "prompt_version": vig.prompt_version})
    return vista(alm, corrida_id, seq)
