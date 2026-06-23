"""
Acceso a precios.db (SQLite): catálogo de insumos y libro de precios.

Toda la lectura/escritura de precios pasa por aquí. Implementa RepositorioPrecios.
No importa nada de `dominio` salvo el modelo `Insumo`: la búsqueda por palabras recibe
los tokens ya hechos (la tokenización vive en el dominio), respetando la frontera de capas.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import date
from pathlib import Path
from typing import Iterable, Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import Insumo

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "precios.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


class PreciosDB:
    """Backend SQLite de precios. Implementa RepositorioPrecios."""

    def __init__(self, path: Path | str = config.PRECIOS_DB_PATH):
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
        """Reconstruye el esquema desde cero (descarta y recrea desde db/precios.sql)."""
        with self.connect() as conn:
            for t in ("insumo_precios", "insumos", "meta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())

    # ---- escritura ----
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int:
        identidad, precios, seen = [], [], set()
        hoy = date.today().isoformat()
        for i in insumos:
            if i.codigo in seen:
                continue
            seen.add(i.codigo)
            identidad.append((i.codigo, i.nombre, i.unidad, i.grupo))
            precios.append((i.codigo, i.precio, i.fuente_precio,
                            config.classify_price_source(i.fuente_precio), hoy, 1))
        with self.connect() as conn:
            conn.executemany(
                "INSERT OR REPLACE INTO insumos (codigo, nombre, unidad, grupo) "
                "VALUES (?,?,?,?)", identidad)
            conn.executemany(
                "INSERT INTO insumo_precios "
                "(codigo, precio, fuente, clasificacion, fecha, vigente) "
                "VALUES (?,?,?,?,?,?)", precios)
        return len(identidad)

    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.connect() as conn:
            conn.execute("UPDATE insumo_precios SET vigente=0 WHERE codigo=?", (str(codigo),))
            conn.execute(
                "INSERT INTO insumo_precios "
                "(codigo, precio, fuente, clasificacion, fecha, vigente) "
                "VALUES (?,?,?,?,?,1)",
                (str(codigo), float(precio), fuente,
                 config.classify_price_source(fuente), fecha))

    def set_meta(self, clave: str, valor: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)",
                         (clave, str(valor)))

    # ---- lectura ----
    def get_insumo(self, codigo: str) -> Optional[Insumo]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM insumos i LEFT JOIN insumo_precios p "
                "  ON p.codigo = i.codigo AND p.vigente = 1 "
                "WHERE i.codigo = ?", (str(codigo),)).fetchone()
        if not r:
            return None
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "")

    def price_history(self, codigo: str) -> list[dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT precio, fuente, clasificacion, fecha, vigente "
                "FROM insumo_precios WHERE codigo=? ORDER BY id", (str(codigo),)).fetchall()
        return [dict(r) for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{texto.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT codigo FROM insumos WHERE nombre LIKE ? OR codigo LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo(r["codigo"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        """Insumos cuyo nombre contiene alguna de las `palabras` (ya tokenizadas por el dominio)."""
        palabras = [p for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre LIKE ?"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT codigo FROM insumos WHERE {clauses} LIMIT ?", params).fetchall()
        return [self.get_insumo(r["codigo"]) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("insumos", "insumo_precios")}

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}
