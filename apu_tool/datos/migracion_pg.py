"""Migración de catálogo SQLite → Postgres (Supabase). Corridas NO se migran.

Lee las SQLite locales directo y escribe en Postgres preservando ids y el
linkage insumo_precios.insumo_id. Idempotente sobre esquema limpio.
"""
from __future__ import annotations

import sqlite3
from pathlib import Path

from apu_tool.datos.pg.conexion import Conexion


def _sqlite(path: Path) -> sqlite3.Connection:
    conn = sqlite3.connect(str(path))
    conn.row_factory = sqlite3.Row
    return conn


def _resync_identity(conn, tabla: str, col: str = "id") -> None:
    conn.execute(
        f"SELECT setval(pg_get_serial_sequence('{tabla}', '{col}'), "
        f"COALESCE((SELECT MAX({col}) FROM {tabla}), 1))")


def migrar_catalogo(sqlite_precios: Path, sqlite_apus: Path, cx: Conexion) -> dict:
    sp = _sqlite(sqlite_precios)
    sa = _sqlite(sqlite_apus)
    n = {"insumos": 0, "precios": 0, "apus": 0, "componentes": 0}
    try:
        with cx.connection() as conn:
            # insumos (id explícito para preservar linkage)
            for r in sp.execute("SELECT id, codigo, nombre, nombre_norm, unidad, grupo "
                                "FROM insumos").fetchall():
                conn.execute(
                    "INSERT INTO precios.insumos (id, codigo, nombre, nombre_norm, unidad, grupo) "
                    "OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (r["id"], r["codigo"], r["nombre"], r["nombre_norm"], r["unidad"], r["grupo"]))
                n["insumos"] += 1
            # historial de precios (con creado_por='migración')
            for r in sp.execute("SELECT id, insumo_id, precio, fuente, clasificacion, fecha, "
                                "vigente FROM insumo_precios").fetchall():
                conn.execute(
                    "INSERT INTO precios.insumo_precios "
                    "(id, insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
                    "OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s,%s,'migración') "
                    "ON CONFLICT DO NOTHING",
                    (r["id"], r["insumo_id"], r["precio"], r["fuente"],
                     r["clasificacion"], r["fecha"], r["vigente"]))
                n["precios"] += 1
            _resync_identity(conn, "precios.insumos")
            _resync_identity(conn, "precios.insumo_precios")
            # meta de precios
            for r in sp.execute("SELECT clave, valor FROM meta").fetchall():
                conn.execute("INSERT INTO precios.meta (clave, valor) VALUES (%s,%s) "
                             "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                             (r["clave"], r["valor"]))
            # apus
            for r in sa.execute("SELECT codigo, shift, nombre, unidad, grupo FROM apus").fetchall():
                conn.execute("INSERT INTO apus.apus (codigo, shift, nombre, unidad, grupo) "
                             "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                             (r["codigo"], r["shift"], r["nombre"], r["unidad"], r["grupo"]))
                n["apus"] += 1
            # componentes
            for r in sa.execute("SELECT apu_codigo, shift, seq, insumo_codigo, insumo_nombre, "
                                "unidad, rendimiento, precio_unitario_hist "
                                "FROM apu_componentes").fetchall():
                conn.execute(
                    "INSERT INTO apus.apu_componentes (apu_codigo, shift, seq, insumo_codigo, "
                    "insumo_nombre, unidad, rendimiento, precio_unitario_hist) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (r["apu_codigo"], r["shift"], r["seq"], r["insumo_codigo"],
                     r["insumo_nombre"], r["unidad"], r["rendimiento"], r["precio_unitario_hist"]))
                n["componentes"] += 1
            # meta de apus
            for r in sa.execute("SELECT clave, valor FROM meta").fetchall():
                conn.execute("INSERT INTO apus.meta (clave, valor) VALUES (%s,%s) "
                             "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                             (r["clave"], r["valor"]))
    finally:
        sp.close()
        sa.close()
    return n


def verificar(sqlite_precios: Path, sqlite_apus: Path, cx: Conexion) -> dict:
    sp = _sqlite(sqlite_precios)
    sa = _sqlite(sqlite_apus)
    try:
        origen = {
            "insumos": sp.execute("SELECT COUNT(*) FROM insumos").fetchone()[0],
            "insumo_precios": sp.execute("SELECT COUNT(*) FROM insumo_precios").fetchone()[0],
            "apus": sa.execute("SELECT COUNT(*) FROM apus").fetchone()[0],
            "apu_componentes": sa.execute("SELECT COUNT(*) FROM apu_componentes").fetchone()[0],
        }
    finally:
        sp.close()
        sa.close()
    with cx.connection() as conn:
        destino = {
            "insumos": conn.execute("SELECT COUNT(*) AS n FROM precios.insumos").fetchone()["n"],
            "insumo_precios": conn.execute(
                "SELECT COUNT(*) AS n FROM precios.insumo_precios").fetchone()["n"],
            "apus": conn.execute("SELECT COUNT(*) AS n FROM apus.apus").fetchone()["n"],
            "apu_componentes": conn.execute(
                "SELECT COUNT(*) AS n FROM apus.apu_componentes").fetchone()["n"],
        }
    return {"ok": origen == destino, "detalle": {"origen": origen, "destino": destino}}
