"""Migración: marca como sub-APU los componentes cuyo código es un APU existente.

Auto-marcado con auditoría; idempotente. Regla de turno del sub-APU: hereda el del
APU padre si existe en ese turno; si no, DIURNO; si no, el único turno disponible.
NO ve la IA (solo estructura). Persistencia via los repos (sin SQL crudo aquí).

Además provee la detección de sub-APUs en un lote de import: `mapa_codigos_apu`
(codigo -> turnos, biblioteca ∪ lote), `detectar_subapus_lote` (vínculos padre→sub)
y `marcar_comps_subapu` (aplica esos vínculos sobre los componentes a insertar).
"""
from __future__ import annotations

from dataclasses import replace
from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import ApuComponent, Perfil
from apu_tool.servicio.auditoria import registrar_auditoria


def _ref_shift(sub_cod: str, parent_shift: str, shifts_por_codigo: dict) -> str:
    disponibles = shifts_por_codigo.get(sub_cod, set())
    if parent_shift in disponibles:
        return parent_shift
    if config.SHIFT_DIURNO in disponibles:
        return config.SHIFT_DIURNO
    return next(iter(disponibles)) if disponibles else parent_shift


def mapa_codigos_apu(alm: Almacen, apus_extra=()) -> dict:
    """codigo -> {turnos}, uniendo la biblioteca con los APUs `apus_extra` del lote."""
    m: dict[str, set] = {}
    for cod, _nom, sh in alm.apus.apu_index():
        m.setdefault(cod, set()).add(sh)
    for a in apus_extra:
        m.setdefault(a.codigo, set()).add(a.shift)
    return m


def detectar_subapus_lote(alm: Almacen, apus_lote, comps_por, solo=None) -> list[dict]:
    """Vínculos sub-APU de los componentes de `solo` (o de todos los del lote).
    El mapa de códigos-APU cubre biblioteca ∪ apus_lote completo."""
    scan = solo if solo is not None else apus_lote
    lib_codes = {cod for cod, _nom, _sh in alm.apus.apu_index()}
    mapa = mapa_codigos_apu(alm, apus_lote)
    vinculos: list[dict] = []
    for a in scan:
        for c in comps_por.get((a.codigo, a.shift), []):
            if c.insumo_codigo and c.insumo_codigo in mapa:
                vinculos.append({
                    "apu_codigo": a.codigo, "apu_turno": a.shift,
                    "sub_codigo": c.insumo_codigo,
                    "sub_turno": _ref_shift(c.insumo_codigo, a.shift, mapa),
                    "sub_nombre": c.insumo_nombre,
                    "origen": "biblioteca" if c.insumo_codigo in lib_codes else "lote"})
    return vinculos


def marcar_comps_subapu(comps, apu_shift: str, mapa: dict):
    """Devuelve (comps con sub-APUs marcados tipo='apu'+ref_shift, nº marcados)."""
    out, n = [], 0
    for c in comps:
        if c.insumo_codigo and c.insumo_codigo in mapa:
            out.append(replace(c, tipo="apu",
                               ref_shift=_ref_shift(c.insumo_codigo, apu_shift, mapa)))
            n += 1
        else:
            out.append(c)
    return out, n


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
