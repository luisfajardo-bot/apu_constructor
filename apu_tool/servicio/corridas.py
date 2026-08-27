"""
Lógica de la capa de servicio para las corridas (armado web).

No habla HTTP ni con la IA directamente: orquesta el dominio (matcher, assembler,
pricing, report) y la persistencia de la corrida. Ve dinero (arma el cuadro para
el equipo), pero nunca abre un camino hacia la IA.
"""
from __future__ import annotations

import time
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.datos.repositorio import CorridaEliminada
from apu_tool.dominio.alertas import alertas_costeo
from apu_tool.dominio.assemble import Assembler, ApuAdvisor
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.report import write_report
from apu_tool.dominio import transporte
from apu_tool.nucleo.models import (
    ApuComponent, AssembledApu, CostedComponent, CorridaItemRow, CorridaMeta,
    LicitacionItem, MatchStatus,
)
from apu_tool.servicio.auditoria import registrar_auditoria


class CorridaCongelada(Exception):
    """Se intentó modificar (confirmar/reasignar) una corrida en modo congelada."""
    def __init__(self, corrida_id: int):
        super().__init__(f"La corrida {corrida_id} está congelada (solo lectura).")
        self.corrida_id = corrida_id


def _estructura(componentes) -> list[dict]:
    """Snapshot SIN dinero de una composición costeada (incluye tipo/ref_shift del componente)."""
    return [{"insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
             "unidad": c.unidad, "rendimiento": c.rendimiento,
             "tipo": getattr(c, "tipo", "insumo"), "ref_shift": getattr(c, "ref_shift", "")}
            for c in componentes]


def nombre_desde_archivo(filename: str) -> str:
    """Nombre por defecto de una corrida: el archivo subido SIN su última extensión.

    `Licitacion Calle 13.xlsx` -> `Licitacion Calle 13`. Es puro (sin I/O)."""
    base = (filename or "").strip()
    return Path(base).stem.strip() if base else ""


def _nombre_lista(alm: Almacen, lista_id: Optional[int]) -> str:
    """Etiqueta legible de la tarifa de una corrida. None = Principal.
    Se resuelve en vivo (no se denormaliza): renombrar una lista debe reflejarse."""
    if lista_id is None:
        return "Principal"
    lista = alm.precios.get_lista(lista_id)
    return lista.nombre if lista else f"lista {lista_id}"


def _contexto(alm: Almacen, meta: CorridaMeta, cache: Optional[dict] = None):
    """Desviaciones del proyecto de esta corrida (distancias, peaje, ajustes).

    Se resuelven EN VIVO desde la carpeta raíz: cambiar las distancias del proyecto
    recostea sus corridas activas sin tocar nada más. Una corrida congelada nunca
    llega acá (se sirve del snapshot).

    `cache`: memo por carpeta para un barrido de varias corridas (`listar_corridas`).
    Sin él, listar N corridas resuelve el contexto N veces (hasta 4 consultas cada
    una), que es el mismo N+1 de round-trips contra Postgres que la precarga en lote
    ya había eliminado."""
    if cache is None:
        return transporte.cargar_contexto(alm, meta.carpeta_id)
    if meta.carpeta_id not in cache:
        cache[meta.carpeta_id] = transporte.cargar_contexto(alm, meta.carpeta_id)
    return cache[meta.carpeta_id]


def construir_corrida_stream(alm: Almacen, archivo: str, items: list[LicitacionItem],
                             turno_def: str, use_ai: Optional[bool],
                             carpeta_id: Optional[int] = None,
                             nombre: Optional[str] = None,
                             lista_precios_id: Optional[int] = None):
    """Arma la corrida de forma INCREMENTAL, emitiendo eventos:
      ('started', {'id', 'total'})           — al crear la corrida (estado 'armando').
      ('progress', {'i','total','descripcion','fila'}) — por ítem, con la fila ya
                                                costeada; el ítem ya quedó persistido.
      ('done', {'id','resumen','duracion_ms'}) — al terminar (estado 'en_revision').
      ('error', {'detail': ...})             — si la corrida se borra/resetea a mitad
                                                (cancelación limpia, sin FK crudo).

    Cada APU se guarda al armarlo (no todo al final), así la tabla se llena en vivo y
    lo ya armado sobrevive si se abandona. La corrida nace 'armando'; si desaparece
    durante el armado, `agregar_item` lanza CorridaEliminada y se cancela."""
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(alm, advisor=advisor, lista_id=lista_precios_id,
                          # Las mismas desviaciones del proyecto que usará la vista:
                          # si el armado en vivo costeara con la biblioteca cruda, los
                          # números saltarían al terminar.
                          contexto=transporte.cargar_contexto(alm, carpeta_id))
    nombre_efectivo = (nombre or "").strip()[:120].strip() or nombre_desde_archivo(archivo)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="armando", cuadro_path=None, carpeta_id=carpeta_id,
        nombre=nombre_efectivo, lista_precios_id=lista_precios_id))
    total = len(items)
    yield ("started", {"id": corrida_id, "total": total})
    t0 = time.monotonic()
    for seq, item in enumerate(items):
        i = seq + 1
        print(f"  [{i}/{total}] {item.descripcion[:60]}", flush=True)
        # Un solo match por ítem: matcher.match() genera los candidatos para
        # mostrar al usuario y se reusa en assemble_item() para elegir el APU final
        # (mismo resultado determinístico, sin recalcular el matcher).
        result = assembler.matcher.match(item)
        candidatos = [{"apu_codigo": c.apu_codigo, "apu_nombre": c.apu_nombre,
                       "score": c.score, "motivo": c.motivo}
                      for c in result.candidatos]
        ens = assembler.assemble_item(item, result)
        fila = CorridaItemRow(
            seq=seq, item=item, status=ens.status.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
            origen=ens.origen, confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes), candidatos=candidatos)
        try:
            alm.corridas.agregar_item(corrida_id, fila)
        except CorridaEliminada:
            yield ("error", {"detail": "Armado cancelado: la corrida fue eliminada."})
            return
        yield ("progress", {"i": i, "total": total,
                            "descripcion": item.descripcion,
                            "fila": _vista_item(
                                ens, seq, ens.status.value,
                                assembler.pricing.sin_distancia(ens.apu_codigo or "", ens.shift))})
    duracion_ms = round((time.monotonic() - t0) * 1000)
    alm.corridas.set_estado(corrida_id, "en_revision")
    alm.corridas.set_duracion(corrida_id, duracion_ms)
    resumen = vista_corrida(alm, corrida_id)["totales"]
    yield ("done", {"id": corrida_id, "resumen": resumen, "duracion_ms": duracion_ms})


def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None,
                      nombre: Optional[str] = None,
                      lista_precios_id: Optional[int] = None) -> int:
    """Envoltorio no-stream: drena el generador e ignora el progreso; devuelve el id."""
    corrida_id = -1
    for evento, payload in construir_corrida_stream(alm, archivo, items, turno_def,
                                                    use_ai, carpeta_id, nombre,
                                                    lista_precios_id):
        if evento == "done":
            corrida_id = payload["id"]
    return corrida_id


def _costear_row(alm: Almacen, row: CorridaItemRow,
                 pricing: Optional[PricingEngine] = None,
                 lista_id: Optional[int] = None,
                 contexto=None) -> AssembledApu:
    """Costeo ACTIVA: re-lee la composición del APU asignado desde la biblioteca y
    costea con precios vigentes. Si no hay apu_codigo o el APU fue borrado, usa la
    composición guardada del ítem (respaldo).

    `pricing`: motor opcional COMPARTIDO entre filas (optimización). Sus cachés de
    precios y de costo de sub-APUs se reusan entre ítems, evitando re-consultar el
    mismo insumo/sub-APU una vez por fila. Si es None se crea uno por fila (como
    antes). El caché por (código, precio vigente) da el mismo costo dentro del
    request, así que compartirlo no cambia resultados.

    `lista_id`/`contexto`: tarifa y desviaciones del proyecto a usar cuando se crea
    el motor aquí (None = Principal / biblioteca tal cual). Si llega un `pricing`
    compartido, ambos viajan DENTRO de él y estos parámetros se ignoran."""
    pricing = pricing or PricingEngine(alm, lista_id=lista_id, contexto=contexto)
    seed = ((row.apu_codigo or "", row.shift),)
    costed = None
    if row.apu_codigo:
        lib = pricing.components(row.apu_codigo, row.shift)   # usa caché precargado si existe
        if lib:
            costed, total = pricing.cost_components(lib, seed)
    if costed is None:
        comps = [ApuComponent(
            apu_codigo=row.apu_codigo or "", shift=row.shift,
            insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
            unidad=c["unidad"], rendimiento=c["rendimiento"],
            precio_unitario_hist=0.0,
            tipo=c.get("tipo", "insumo"), ref_shift=c.get("ref_shift", ""))
            for c in row.componentes]
        costed, total = pricing.cost_components(comps, seed)
    return AssembledApu(
        item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
        unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=costed,
        costo_unitario=total, status=MatchStatus(row.status),
        confianza=row.confianza, explicacion=row.explicacion, origen=row.origen)


def _assembled_desde_snapshot(row: CorridaItemRow, snap: dict) -> AssembledApu:
    """Reconstruye un AssembledApu desde un snapshot congelado (composición + costos fijos)."""
    comps = [CostedComponent(
        insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
        unidad=c["unidad"], rendimiento=c["rendimiento"],
        precio_unitario=c["precio_unitario"], fuente_precio=c["fuente_precio"],
        costo=c["costo"], calidad_cruce=c.get("calidad_cruce", "exacto"))
        for c in snap.get("composicion", [])]
    return AssembledApu(
        item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
        unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=comps,
        costo_unitario=snap["costo_unitario"], status=MatchStatus(row.status),
        confianza=row.confianza, explicacion=row.explicacion, origen=row.origen)


def _vista_item(ens: AssembledApu, seq: int, status: str,
                sin_distancia: tuple[str, ...] = ()) -> dict:
    return {
        "seq": seq, "item": ens.item.item, "descripcion": ens.item.descripcion,
        "unidad": ens.unidad, "cantidad": ens.item.cantidad,
        "apu_codigo": ens.apu_codigo, "apu_nombre": ens.apu_nombre,
        "status": status, "confianza": round(ens.confianza, 4),
        "precio_contractual": ens.item.precio_contractual,
        "costo_unitario": ens.costo_unitario, "margen_unitario": ens.margen_unitario,
        "margen_pct": ens.margen_pct, "contractual_total": ens.contractual_total,
        "costo_total": ens.costo_total, "margen_total": ens.margen_total,
        "alertas_costeo": alertas_costeo(ens, sin_distancia),
    }


def _ensamblar_corrida(alm: Almacen, meta, rows, pricing: PricingEngine) -> list[AssembledApu]:
    """Ensambla los ítems de una corrida respetando el modo: congelada -> snapshot por
    ítem (con caída a costeo en vivo si falta el snapshot); activa -> costeo en vivo.
    Camino ÚNICO compartido por vista_corrida y listar_corridas."""
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(meta.id)
        return [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                else _costear_row(alm, r, pricing, meta.lista_precios_id) for r in rows]
    return [_costear_row(alm, r, pricing, meta.lista_precios_id) for r in rows]


def _totales(ensambles: list[AssembledApu], rows) -> dict:
    """Totales de una corrida (fórmula única). margen_pct es AGREGADO."""
    tot_c = sum(e.contractual_total for e in ensambles)
    tot_k = sum(e.costo_total for e in ensambles)
    n_rev = sum(1 for r in rows if r.status in ("review", "new"))
    return {"contractual": tot_c, "costo": tot_k, "margen": tot_c - tot_k,
            "margen_pct": ((tot_c - tot_k) / tot_c) if tot_c else 0.0,
            "n_items": len(rows), "n_revision": n_rev,
            "n_alertas_costeo": sum(1 for e in ensambles if alertas_costeo(e))}


def vista_corrida(alm: Almacen, corrida_id: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                            contexto=_contexto(alm, meta))   # COMPARTIDO por la corrida
    pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)  # lote
    ensambles = _ensamblar_corrida(alm, meta, rows, pricing)
    # Una foto congelada ya se emitió: no tiene pendientes que avisar (evita ruido
    # sobre un costo que no se va a recalcular). Solo los ítems costeados EN VIVO
    # (activa, o congelada sin snapshot -> cae a _costear_row) llevan sin_distancia.
    snaps = alm.corridas.get_snapshots(meta.id) if meta.modo == "congelada" else {}
    items = [_vista_item(ens, r.seq, r.status,
                         () if r.seq in snaps
                         else pricing.sin_distancia(r.apu_codigo or "", r.shift))
             for ens, r in zip(ensambles, rows)]
    return {
        "id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
        "estado": meta.estado, "modo": meta.modo,
        "carpeta_id": meta.carpeta_id,
        "lista_precios_id": meta.lista_precios_id,
        "lista_nombre": _nombre_lista(alm, meta.lista_precios_id),
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": _totales(ensambles, rows),
    }


def detalle_item(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(corrida_id)
        ens = (_assembled_desde_snapshot(row, snaps[seq]) if seq in snaps
               else _costear_row(alm, row, None, meta.lista_precios_id, _contexto(alm, meta)))
    else:
        ens = _costear_row(alm, row, None, meta.lista_precios_id, _contexto(alm, meta))
    return {
        "seq": row.seq, "descripcion": row.item.descripcion,
        "apu_codigo": row.apu_codigo, "apu_nombre": row.apu_nombre,
        # turno del APU asignado: lo necesita "duplicar este APU y usarlo aquí"
        # para leer el APU de origen de la biblioteca (la identidad es código+turno).
        "apu_turno": row.shift,
        "status": row.status, "explicacion": row.explicacion,
        "candidatos": row.candidatos,
        "composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce}
            for c in ens.componentes],
        "costo_unitario": ens.costo_unitario,
    }


def congelar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Fija una foto inmutable: costea la vista ACTIVA ahora y guarda el snapshot de
    cada ítem; luego marca modo='congelada'. Idempotente (recongelar = foto nueva)."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                            contexto=_contexto(alm, meta))   # COMPARTIDO al congelar
    _rows = alm.corridas.get_items(corrida_id)
    pricing.precargar((r.apu_codigo, r.shift) for r in _rows if r.apu_codigo)
    for r in _rows:
        ens = _costear_row(alm, r, pricing)
        payload = {"composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce} for c in ens.componentes],
            "costo_unitario": ens.costo_unitario}
        alm.corridas.set_snapshot(corrida_id, r.seq, payload)
    alm.corridas.set_modo(corrida_id, "congelada")
    return vista_corrida(alm, corrida_id)


def activar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Vuelve la corrida a seguir la biblioteca. El snapshot queda pero se ignora."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    alm.corridas.set_modo(corrida_id, "activa")
    return vista_corrida(alm, corrida_id)


def renombrar_corrida(alm: Almacen, corrida_id: int, nombre: str) -> Optional[dict]:
    """Cambia el alias de una corrida. Devuelve la vista; None si no existe.
    Lanza ValueError si el nombre queda vacío. Permitido aun si está congelada
    (el nombre es etiqueta, no forma parte del snapshot)."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    limpio = (nombre or "").strip()[:120].strip()
    if not limpio:
        raise ValueError("El nombre no puede estar vacío.")
    alm.corridas.set_nombre(corrida_id, limpio)
    return vista_corrida(alm, corrida_id)


def confirmar_items(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                    apu_codigo: Optional[str] = None,
                    shift: Optional[str] = None) -> Optional[dict]:
    """Confirma varios ítems de una corrida en UN solo recosteo.

    `apu_codigo=None` confirma el APU que cada ítem ya tiene (sin reasignar);
    con `apu_codigo` se le asigna ese APU (codigo+turno) a todos los seqs.
    Devuelve la vista de la corrida, o None si la corrida no existe, o si
    ninguno de los seqs pedidos existe en ella (pedir una lista vacía no
    cuenta: ahí no se pidió ningún seq inexistente, se pidió nada).

    Es la primitiva: `confirmar_item` es el caso de un solo seq. Un solo
    Assembler para todo el lote (su PricingEngine cachea, y el camino de
    confirmar no toca matcher/retriever, que son perezosos), y un solo
    vista_corrida al final en vez de uno por ítem.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id, contexto=_contexto(alm, meta))
    seqs_pedidos = list(seqs)   # Iterable: consumirlo dos veces no es seguro
    # Dos pasadas. La primera resuelve (fila, código, turno) y valida que el APU
    # exista, SIN escribir: con un código que no existe, reassemble_with_choice
    # produce una composición vacía y el ítem queda costeado en $0 (regla de
    # negocio: nada en $0 en silencio). Validando antes, un código inválido falla
    # sin dejar el lote a medio aplicar.
    # El turno se resuelve POR FILA (`shift or row.shift`): confirmar sin turno es
    # un camino real y usado — el botón "Elegir" de los candidatos y "Confirmar APU
    # actual" llaman sin él —, así que no se puede exigir.
    trabajo: list[tuple[int, CorridaItemRow, str, str]] = []
    validados: set[tuple[str, str]] = set()
    encontrados = 0
    # Una sola consulta para toda la corrida (get_items, no get_item por seq): con
    # Postgres lo caro es la latencia del viaje, no el tamaño del payload, y este
    # dict evita pagar un round trip por fila marcada (era el N+1 que esta feature
    # existe para evitar).
    filas_por_seq = {r.seq: r for r in alm.corridas.get_items(corrida_id)}
    for seq in seqs_pedidos:
        row = filas_por_seq.get(seq)
        if row is None:
            continue                      # seq ajeno a la corrida: se saltea
        encontrados += 1
        codigo = apu_codigo or row.apu_codigo
        if not codigo:
            continue                      # nada que confirmar (evita el $0)
        turno = shift or row.shift
        if (codigo, turno) not in validados:
            # Turno EXACTO a propósito, más estricto que el fallback de `_build`
            # (assemble.py), que si el código existe con OTRO turno cae a ese turno
            # en silencio. Ese autocorregido silencioso es justo la clase de sorpresa
            # que "nada en $0" quiere evitar: costear con el turno equivocado sin que
            # nadie se entere. Acá se prefiere fallar y que el usuario mande el turno
            # correcto.
            if alm.apus.get_apu(codigo, turno) is None:
                raise ValueError(f"Fila {seq}: no existe el APU {codigo} ({turno}).")
            validados.add((codigo, turno))   # una consulta por par distinto, no por fila
        trabajo.append((seq, row, codigo, turno))
    # Ningún seq de los pedidos existe: no hay nada que informar y el llamador
    # pidió algo que no está. Devolver None deja que el endpoint conteste 404,
    # que es lo que confirmar_item hizo siempre para un seq inexistente. Con la
    # lista vacía no aplica: pedir nada no es pedir algo que no existe.
    if seqs_pedidos and encontrados == 0:
        return None
    for seq, row, codigo, turno in trabajo:
        ens = assembler.reassemble_with_choice(row.item, codigo, turno)
        alm.corridas.actualizar_eleccion(
            corrida_id, seq, status=MatchStatus.CONFIRMED.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift, origen=ens.origen,
            confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes))
    return vista_corrida(alm, corrida_id)


def confirmar_item(alm: Almacen, corrida_id: int, seq: int, apu_codigo: str,
                   shift: Optional[str] = None) -> Optional[dict]:
    """Un solo ítem. Wrapper sobre `confirmar_items` para que confirmar-uno y
    confirmar-muchos no se puedan separar con el tiempo. `confirmar_items`
    devuelve None cuando ese seq no existe en la corrida (además de cuando la
    corrida no existe), así que el 404 del endpoint sale gratis del lote."""
    return confirmar_items(alm, corrida_id, [seq], apu_codigo, shift or None)


def listar_corridas(alm: Almacen) -> list[dict]:
    out: list[dict] = []
    # Nombres de lista resueltos UNA vez para todas las corridas (no una consulta por
    # fila dentro del bucle): este listado ya sufrió round-trips N+1 contra Postgres
    # (precios/composición) y se arregló precargando en lote; el nombre de la lista
    # sigue la misma regla para no reintroducir el mismo patrón.
    nombres_lista = {l.id: l.nombre for l in alm.precios.listar_listas()}
    ctx_cache: dict = {}   # memo por carpeta: N corridas del mismo proyecto, un solo contexto
    for meta in alm.corridas.listar_corridas():
        rows = alm.corridas.get_items(meta.id)
        n_rev = sum(1 for it in rows if it.status in ("review", "new"))
        lista_nombre = ("Principal" if meta.lista_precios_id is None
                        else nombres_lista.get(meta.lista_precios_id, f"lista {meta.lista_precios_id}"))
        fila = {"id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
                "creada_en": meta.creada_en,
                "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                "carpeta_id": meta.carpeta_id,
                "lista_precios_id": meta.lista_precios_id,
                "lista_nombre": lista_nombre,
                "n_items": len(rows), "n_revision": n_rev,
                "contractual": None, "costo": None, "margen": None, "margen_pct": None}
        try:                                           # fail-safe: si una corrida no
            pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                                    contexto=_contexto(alm, meta, ctx_cache))   # costea, su fila queda con None
            pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)
            tot = _totales(_ensamblar_corrida(alm, meta, rows, pricing), rows)
            fila.update(contractual=tot["contractual"], costo=tot["costo"],
                        margen=tot["margen"], margen_pct=tot["margen_pct"])
        except Exception:
            pass
        out.append(fila)
    return out


def eliminar_corrida(alm: Almacen, corrida_id: int, actor=None) -> bool:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return False
    with alm.transaccion("corridas") as conn:
        ok = alm.corridas.eliminar_corrida(corrida_id, conn=conn)
        if ok:
            registrar_auditoria(
                alm, conn, actor, "corrida.eliminar", "corrida", corrida_id,
                antes={"archivo": meta.archivo, "creada_en": meta.creada_en, "estado": meta.estado},
                despues=None)
    return ok


def generar_cuadro(alm: Almacen, corrida_id: int) -> Optional[Path]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    config.ensure_dirs()
    snaps = alm.corridas.get_snapshots(corrida_id)
    # Si ya está congelada y tiene snapshots, respeta la foto emitida (no recongela);
    # si está activa (o congelada sin snapshots), congela el estado actual.
    if not (meta.modo == "congelada" and snaps):
        congelar(alm, corrida_id)
        snaps = alm.corridas.get_snapshots(corrida_id)
    rows = alm.corridas.get_items(corrida_id)
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                            contexto=_contexto(alm, meta))   # COMPARTIDO al generar el cuadro
    pricing.precargar((r.apu_codigo, r.shift) for r in rows
                      if r.apu_codigo and r.seq not in snaps)
    assembled = [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                 else _costear_row(alm, r, pricing) for r in rows]
    stamp = meta.creada_en.replace(":", "").replace("-", "").replace("T", "_")
    out = config.OUTPUT_DIR / f"cuadro_corrida_{corrida_id}_{stamp}.xlsx"
    write_report(assembled, out, lista_nombre=_nombre_lista(alm, meta.lista_precios_id))
    alm.corridas.set_cuadro(corrida_id, str(out))
    alm.corridas.set_estado(corrida_id, "finalizada")
    return out
