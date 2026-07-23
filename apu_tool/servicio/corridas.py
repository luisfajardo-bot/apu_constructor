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
from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.datos.repositorio import CorridaEliminada
from apu_tool.dominio.alertas import alertas_costeo
from apu_tool.dominio.assemble import Assembler, ApuAdvisor
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.report import write_report
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


def construir_corrida_stream(alm: Almacen, archivo: str, items: list[LicitacionItem],
                             turno_def: str, use_ai: Optional[bool],
                             carpeta_id: Optional[int] = None):
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
    assembler = Assembler(alm, advisor=advisor)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="armando", cuadro_path=None, carpeta_id=carpeta_id))
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
                            "fila": _vista_item(ens, seq, ens.status.value)})
    duracion_ms = round((time.monotonic() - t0) * 1000)
    alm.corridas.set_estado(corrida_id, "en_revision")
    alm.corridas.set_duracion(corrida_id, duracion_ms)
    resumen = vista_corrida(alm, corrida_id)["totales"]
    yield ("done", {"id": corrida_id, "resumen": resumen, "duracion_ms": duracion_ms})


def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None) -> int:
    """Envoltorio no-stream: drena el generador e ignora el progreso; devuelve el id."""
    corrida_id = -1
    for evento, payload in construir_corrida_stream(alm, archivo, items, turno_def,
                                                    use_ai, carpeta_id):
        if evento == "done":
            corrida_id = payload["id"]
    return corrida_id


def _costear_row(alm: Almacen, row: CorridaItemRow,
                 pricing: Optional[PricingEngine] = None) -> AssembledApu:
    """Costeo ACTIVA: re-lee la composición del APU asignado desde la biblioteca y
    costea con precios vigentes. Si no hay apu_codigo o el APU fue borrado, usa la
    composición guardada del ítem (respaldo).

    `pricing`: motor opcional COMPARTIDO entre filas (optimización). Sus cachés de
    precios y de costo de sub-APUs se reusan entre ítems, evitando re-consultar el
    mismo insumo/sub-APU una vez por fila. Si es None se crea uno por fila (como
    antes). El caché por (código, precio vigente) da el mismo costo dentro del
    request, así que compartirlo no cambia resultados."""
    pricing = pricing or PricingEngine(alm)
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


def _vista_item(ens: AssembledApu, seq: int, status: str) -> dict:
    return {
        "seq": seq, "item": ens.item.item, "descripcion": ens.item.descripcion,
        "unidad": ens.unidad, "cantidad": ens.item.cantidad,
        "apu_codigo": ens.apu_codigo, "apu_nombre": ens.apu_nombre,
        "status": status, "confianza": round(ens.confianza, 4),
        "precio_contractual": ens.item.precio_contractual,
        "costo_unitario": ens.costo_unitario, "margen_unitario": ens.margen_unitario,
        "margen_pct": ens.margen_pct, "contractual_total": ens.contractual_total,
        "costo_total": ens.costo_total, "margen_total": ens.margen_total,
        "alertas_costeo": alertas_costeo(ens),
    }


def _ensamblar_corrida(alm: Almacen, meta, rows, pricing: PricingEngine) -> list[AssembledApu]:
    """Ensambla los ítems de una corrida respetando el modo: congelada -> snapshot por
    ítem (con caída a costeo en vivo si falta el snapshot); activa -> costeo en vivo.
    Camino ÚNICO compartido por vista_corrida y listar_corridas."""
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(meta.id)
        return [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                else _costear_row(alm, r, pricing) for r in rows]
    return [_costear_row(alm, r, pricing) for r in rows]


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
    pricing = PricingEngine(alm)                       # motor COMPARTIDO por toda la corrida
    pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)  # lote
    ensambles = _ensamblar_corrida(alm, meta, rows, pricing)
    items = [_vista_item(ens, r.seq, r.status) for ens, r in zip(ensambles, rows)]
    return {
        "id": meta.id, "archivo": meta.archivo, "estado": meta.estado, "modo": meta.modo,
        "carpeta_id": meta.carpeta_id,
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
        ens = _assembled_desde_snapshot(row, snaps[seq]) if seq in snaps else _costear_row(alm, row)
    else:
        ens = _costear_row(alm, row)
    return {
        "seq": row.seq, "descripcion": row.item.descripcion,
        "apu_codigo": row.apu_codigo, "apu_nombre": row.apu_nombre,
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
    pricing = PricingEngine(alm)                       # motor COMPARTIDO al congelar
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


def confirmar_item(alm: Almacen, corrida_id: int, seq: int, apu_codigo: str,
                   shift: Optional[str] = None) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False))
    ens = assembler.reassemble_with_choice(row.item, apu_codigo, shift or row.shift)
    alm.corridas.actualizar_eleccion(
        corrida_id, seq, status=MatchStatus.CONFIRMED.value, apu_codigo=ens.apu_codigo,
        apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift, origen=ens.origen,
        confianza=ens.confianza, explicacion=ens.explicacion,
        componentes=_estructura(ens.componentes))
    return vista_corrida(alm, corrida_id)


def listar_corridas(alm: Almacen) -> list[dict]:
    out: list[dict] = []
    for meta in alm.corridas.listar_corridas():
        rows = alm.corridas.get_items(meta.id)
        n_rev = sum(1 for it in rows if it.status in ("review", "new"))
        fila = {"id": meta.id, "archivo": meta.archivo, "creada_en": meta.creada_en,
                "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                "carpeta_id": meta.carpeta_id,
                "n_items": len(rows), "n_revision": n_rev,
                "contractual": None, "costo": None, "margen": None, "margen_pct": None}
        try:                                           # fail-safe: si una corrida no
            pricing = PricingEngine(alm)               # costea, su fila queda con None
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
    pricing = PricingEngine(alm)                       # motor COMPARTIDO al generar el cuadro
    pricing.precargar((r.apu_codigo, r.shift) for r in rows
                      if r.apu_codigo and r.seq not in snaps)
    assembled = [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                 else _costear_row(alm, r, pricing) for r in rows]
    stamp = meta.creada_en.replace(":", "").replace("-", "").replace("T", "_")
    out = config.OUTPUT_DIR / f"cuadro_corrida_{corrida_id}_{stamp}.xlsx"
    write_report(assembled, out)
    alm.corridas.set_cuadro(corrida_id, str(out))
    alm.corridas.set_estado(corrida_id, "finalizada")
    return out
