# apu_tool/dominio/integridad.py
"""
Chequeo de integridad del vínculo APU -> insumo (que cruza las dos bases).

Sustituye la FK que ya no existe entre archivos. Reutiliza el resolver de `cruce`:
reporta componentes cuyo código no está en precios (HUERFANO), los que casan por
nombre de forma aproximada (APROXIMADO) y los que no resuelven a un solo insumo
(AMBIGUO) — la clase del problema del 4613 y de los códigos repetidos del IDU.
"""
from __future__ import annotations

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import cruce


def revisar(almacen: Almacen) -> dict:
    """Devuelve {'huerfanos', 'aproximados', 'ambiguos', 'detalles': [...]}."""
    huerfanos = aproximados = ambiguos = 0
    detalles: dict[tuple, dict] = {}
    for cod, nom in almacen.apus.componentes_para_integridad():
        res = cruce.resolver(almacen.precios.get_candidatos(cod), nom)
        if res.calidad == cruce.CalidadCruce.HUERFANO:
            huerfanos += 1
        elif res.calidad == cruce.CalidadCruce.AMBIGUO:
            ambiguos += 1
            _acumular(detalles, cod, nom, "ambiguo")
        elif res.calidad == cruce.CalidadCruce.APROXIMADO:
            aproximados += 1
            _acumular(detalles, cod, nom, "aproximado",
                      cat_nom=res.insumo.nombre if res.insumo else "")
    return {"huerfanos": huerfanos, "aproximados": aproximados,
            "ambiguos": ambiguos, "detalles": list(detalles.values())}


def _acumular(detalles, cod, nom, calidad, cat_nom=""):
    key = (cod, nom, calidad)
    d = detalles.setdefault(key, {"codigo": cod, "apu_nom": nom,
                                  "calidad": calidad, "cat_nom": cat_nom, "n": 0})
    d["n"] += 1
