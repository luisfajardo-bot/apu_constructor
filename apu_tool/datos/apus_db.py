"""
Acceso a apus.db (SQLite): biblioteca histórica de APUs (composición + rendimiento + turno).

Implementa RepositorioApus. NO toca dinero (precio_unitario_hist es un respaldo embebido,
no se expone a la IA). get_depriced_apu devuelve la vista SIN dinero para la IA.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterable, Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import (
    Apu, ApuComponent, DePricedApu, DePricedComponent,
)

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "apus.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


class ApusDB:
    """Backend SQLite de APUs. Implementa RepositorioApus."""

    def __init__(self, path: Path | str = config.APUS_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())

    def reset(self) -> None:
        """Reconstruye el esquema desde cero (descarta y recrea desde db/apus.sql)."""
        with self.connect() as conn:
            for t in ("apu_componentes", "apus", "meta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())

    # ---- escritura ----
    def insert_apus(self, apus: Iterable[Apu]) -> int:
        rows = [(a.codigo, a.shift, a.nombre, a.unidad, a.grupo) for a in apus]
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO apus (codigo, shift, nombre, unidad, grupo) "
                "VALUES (?,?,?,?,?)", rows)
        return len(rows)

    def insert_components(self, comps: Iterable[ApuComponent]) -> int:
        comps = list(comps)
        with self.connect() as conn:
            seq_by_key: dict[tuple[str, str], int] = {}
            rows = []
            for c in comps:
                key = (c.apu_codigo, c.shift)
                if key not in seq_by_key:
                    r = conn.execute(
                        "SELECT COALESCE(MAX(seq) + 1, 0) FROM apu_componentes "
                        "WHERE apu_codigo=? AND shift=?", key).fetchone()
                    seq_by_key[key] = r[0]
                seq = seq_by_key[key]
                seq_by_key[key] = seq + 1
                rows.append((c.apu_codigo, c.shift, seq, c.insumo_codigo,
                             c.insumo_nombre, c.unidad, c.rendimiento,
                             c.precio_unitario_hist))
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist) VALUES (?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def set_meta(self, clave: str, valor: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)",
                         (clave, str(valor)))

    # ---- lectura ----
    def all_apus(self) -> list[Apu]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM apus").fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def apu_index(self) -> list[tuple[str, str, str]]:
        with self.connect() as conn:
            rows = conn.execute("SELECT codigo, nombre, shift FROM apus").fetchall()
        return [(r["codigo"], r["nombre"], r["shift"]) for r in rows]

    def search_apus(self, texto: str, limit: int = 20) -> list[Apu]:
        like = f"%{texto.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM apus WHERE nombre LIKE ? OR codigo LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def get_apu(self, codigo: str, shift: str) -> Optional[Apu]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM apus WHERE codigo=? AND shift=?",
                             (str(codigo), shift)).fetchone()
        return Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) if r else None

    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM apu_componentes WHERE apu_codigo=? AND shift=? ORDER BY seq",
                (str(apu_codigo), shift)).fetchall()
        return [ApuComponent(
            apu_codigo=r["apu_codigo"], shift=r["shift"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"], unidad=r["unidad"],
            rendimiento=r["rendimiento"] or 0.0,
            precio_unitario_hist=r["precio_unitario_hist"] or 0.0) for r in rows]

    def get_depriced_apu(self, codigo: str, shift: str) -> Optional[DePricedApu]:
        apu = self.get_apu(codigo, shift)
        if apu is None:
            return None
        comps = self.get_components(codigo, shift)
        return DePricedApu(
            codigo=apu.codigo, nombre=apu.nombre, unidad=apu.unidad,
            shift=apu.shift, grupo=apu.grupo,
            componentes=tuple(
                DePricedComponent(c.insumo_codigo, c.insumo_nombre, c.unidad, c.rendimiento)
                for c in comps))

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("apus", "apu_componentes")}

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}
