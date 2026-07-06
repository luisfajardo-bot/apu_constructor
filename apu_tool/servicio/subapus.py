"""Migración: marca como sub-APU los componentes cuyo código es un APU existente.

Auto-marcado con auditoría; idempotente. Regla de turno del sub-APU: hereda el del
APU padre si existe en ese turno; si no, DIURNO; si no, el único turno disponible.
NO ve la IA (solo estructura). Persistencia via los repos (sin SQL crudo aquí).
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auditoria import registrar_auditoria


def _ref_shift(sub_cod: str, parent_shift: str, shifts_por_codigo: dict) -> str:
    disponibles = shifts_por_codigo.get(sub_cod, set())
    if parent_shift in disponibles:
        return parent_shift
    if config.SHIFT_DIURNO in disponibles:
        return config.SHIFT_DIURNO
    return next(iter(disponibles)) if disponibles else parent_shift


def marcar_subapus(alm: Almacen, actor: Optional[Perfil] = None) -> dict:
    alm.apus.init_schema()   # idempotente: asegura columnas tipo/ref_shift
    candidatos = alm.apus.componentes_subapu_candidatos()
    if not candidatos:
        return {"apus_afectados": 0, "componentes_marcados": 0}

    shifts_por_codigo: dict[str, set] = {}
    for cod, _nom, sh in alm.apus.apu_index():
        shifts_por_codigo.setdefault(cod, set()).add(sh)

    por_padre: dict[tuple, list] = {}
    for c in candidatos:
        c["ref_shift"] = _ref_shift(c["insumo_codigo"], c["shift"], shifts_por_codigo)
        por_padre.setdefault((c["apu_codigo"], c["shift"]), []).append(c)

    marcados = 0
    with alm.transaccion("apus") as conn:
        for (padre_cod, padre_shift), comps in por_padre.items():
            for c in comps:
                alm.apus.set_componente_subapu(
                    c["apu_codigo"], c["shift"], c["seq"], c["ref_shift"], conn=conn)
                marcados += 1
            registrar_auditoria(
                alm, conn, actor, "apu.componente.marcar_subapu", "apu", padre_cod,
                despues={"shift": padre_shift, "componentes": [
                    {"seq": c["seq"], "ref_codigo": c["insumo_codigo"],
                     "ref_shift": c["ref_shift"]} for c in comps]})
    return {"apus_afectados": len(por_padre), "componentes_marcados": marcados}
