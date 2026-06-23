"""
Chequeo de integridad del vínculo APU→insumo (que cruza las dos bases).

Sustituye la FK que ya no existe entre archivos: reporta componentes cuyo código no
existe en precios (huérfanos) y descalces de nombre (el nombre embebido en el APU no
coincide con el del código en el catálogo) — la clase del problema del 4613.
"""
from __future__ import annotations

import unicodedata
from difflib import SequenceMatcher

from apu_tool.datos.almacen import Almacen


def _norm(s: str) -> str:
    s = "".join(c for c in unicodedata.normalize("NFD", str(s or ""))
                if unicodedata.category(c) != "Mn")
    return " ".join(s.upper().split())


def _coincide(a: str, b: str) -> bool:
    na, nb = _norm(a), _norm(b)
    if not na or not nb:
        return True
    if na == nb or na.startswith(nb) or nb.startswith(na):
        return True
    return SequenceMatcher(None, na, nb).ratio() >= 0.60


def revisar(almacen: Almacen) -> dict:
    """Devuelve {'huerfanos': int, 'descalces': [{codigo, apu_nom, cat_nom, n}]}."""
    huerfanos = 0
    descalces: dict[tuple, dict] = {}
    with almacen.apus.connect() as ca:
        comps = ca.execute(
            "SELECT insumo_codigo AS cod, insumo_nombre AS nom "
            "FROM apu_componentes WHERE insumo_codigo IS NOT NULL AND insumo_codigo <> ''"
        ).fetchall()
    for r in comps:
        ins = almacen.precios.get_insumo(r["cod"])
        if ins is None:
            huerfanos += 1
            continue
        if not _coincide(r["nom"], ins.nombre):
            key = (r["cod"], _norm(r["nom"]))
            d = descalces.setdefault(key, {"codigo": r["cod"], "apu_nom": r["nom"],
                                           "cat_nom": ins.nombre, "n": 0})
            d["n"] += 1
    return {"huerfanos": huerfanos, "descalces": list(descalces.values())}
