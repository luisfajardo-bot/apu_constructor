"""
Lógica de la capa de servicio para las corridas (armado web).

No habla HTTP ni con la IA directamente: orquesta el dominio (matcher, assembler,
pricing, report) y la persistencia de la corrida. Ve dinero (arma el cuadro para
el equipo), pero nunca abre un camino hacia la IA.
"""
from __future__ import annotations

from datetime import datetime
from pathlib import Path
from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.assemble import Assembler, ApuAdvisor
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.report import write_report
from apu_tool.nucleo.models import (
    ApuComponent, AssembledApu, CorridaItemRow, CorridaMeta, LicitacionItem,
    MatchStatus,
)


def _estructura(componentes) -> list[dict]:
    """Snapshot SIN dinero de una composición costeada."""
    return [{"insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
             "unidad": c.unidad, "rendimiento": c.rendimiento} for c in componentes]


def construir_corrida_stream(alm: Almacen, archivo: str, items: list[LicitacionItem],
                             turno_def: str, use_ai: Optional[bool]):
    """Arma la corrida emitiendo progreso. Genera ('progress', {...}) por ítem y
    ('done', {'id', 'resumen'}) al final. La lógica de armado por ítem es idéntica
    a la versión no-stream; solo se añaden el log de consola y los yields."""
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(alm, advisor=advisor)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="en_revision", cuadro_path=None))
    filas: list[CorridaItemRow] = []
    total = len(items)
    for seq, item in enumerate(items):
        i = seq + 1
        print(f"  [{i}/{total}] {item.descripcion[:60]}", flush=True)
        result = assembler.matcher.match(item)
        candidatos = [{"apu_codigo": c.apu_codigo, "apu_nombre": c.apu_nombre,
                       "score": c.score, "motivo": c.motivo}
                      for c in result.candidatos]
        ens = assembler.assemble_item(item)
        filas.append(CorridaItemRow(
            seq=seq, item=item, status=ens.status.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
            origen=ens.origen, confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes), candidatos=candidatos))
        yield ("progress", {"i": i, "total": total, "descripcion": item.descripcion})
    alm.corridas.guardar_items(corrida_id, filas)
    resumen = vista_corrida(alm, corrida_id)["totales"]
    yield ("done", {"id": corrida_id, "resumen": resumen})


def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool]) -> int:
    """Envoltorio no-stream: drena el generador e ignora el progreso; devuelve el id."""
    corrida_id = -1
    for evento, payload in construir_corrida_stream(alm, archivo, items, turno_def, use_ai):
        if evento == "done":
            corrida_id = payload["id"]
    return corrida_id


def _costear_row(alm: Almacen, row: CorridaItemRow) -> AssembledApu:
    """Recostea la estructura guardada con el precio vigente."""
    pricing = PricingEngine(alm)
    comps = [ApuComponent(
        apu_codigo=row.apu_codigo or "", shift=row.shift,
        insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
        unidad=c["unidad"], rendimiento=c["rendimiento"],
        precio_unitario_hist=0.0) for c in row.componentes]
    costed, total = pricing.cost_components(comps)
    return AssembledApu(
        item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
        unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=costed,
        costo_unitario=total, status=MatchStatus(row.status),
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
    }


def vista_corrida(alm: Almacen, corrida_id: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    items = [_vista_item(_costear_row(alm, r), r.seq, r.status) for r in rows]
    tot_c = sum(i["contractual_total"] for i in items)
    tot_k = sum(i["costo_total"] for i in items)
    n_rev = sum(1 for i in items if i["status"] in ("review", "new"))
    return {
        "id": meta.id, "archivo": meta.archivo, "estado": meta.estado, "items": items,
        "totales": {"contractual": tot_c, "costo": tot_k, "margen": tot_c - tot_k,
                    "margen_pct": ((tot_c - tot_k) / tot_c) if tot_c else 0.0,
                    "n_items": len(items), "n_revision": n_rev},
    }


def detalle_item(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
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


def confirmar_item(alm: Almacen, corrida_id: int, seq: int, apu_codigo: str,
                   shift: Optional[str] = None) -> Optional[dict]:
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


def generar_cuadro(alm: Almacen, corrida_id: int) -> Optional[Path]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    config.ensure_dirs()
    rows = alm.corridas.get_items(corrida_id)
    assembled = [_costear_row(alm, r) for r in rows]
    stamp = meta.creada_en.replace(":", "").replace("-", "").replace("T", "_")
    out = config.OUTPUT_DIR / f"cuadro_corrida_{corrida_id}_{stamp}.xlsx"
    write_report(assembled, out)
    alm.corridas.set_cuadro(corrida_id, str(out))
    alm.corridas.set_estado(corrida_id, "finalizada")
    return out
