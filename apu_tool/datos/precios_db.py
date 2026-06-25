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
from apu_tool.nucleo.texto import normalizar

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
        hoy = date.today().isoformat()
        n = 0
        with self.connect() as conn:
            for i in insumos:
                nombre_norm = normalizar(i.nombre)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO insumos "
                    "(codigo, nombre, nombre_norm, unidad, grupo) VALUES (?,?,?,?,?)",
                    (i.codigo, i.nombre, nombre_norm, i.unidad, i.grupo))
                if not cur.rowcount:
                    continue  # identidad (codigo, nombre_norm) ya existía; no duplicar precio
                iid = cur.lastrowid
                conn.execute(
                    "INSERT INTO insumo_precios "
                    "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                    "VALUES (?,?,?,?,?,1)",
                    (iid, i.precio, i.fuente_precio,
                     config.classify_price_source(i.fuente_precio), hoy))
                n += 1
        return n

    def _ids_de(self, conn, codigo: str, nombre: Optional[str]) -> list[int]:
        if nombre is None:
            rows = conn.execute("SELECT id FROM insumos WHERE codigo=?",
                                (str(codigo),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE codigo=? AND nombre_norm=?",
                (str(codigo), normalizar(nombre))).fetchall()
        return [r["id"] for r in rows]

    def _insertar_precio_vigente(self, conn, insumo_id: int, precio: float,
                                fuente: str, fecha: str) -> None:
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=?", (int(insumo_id),))
        conn.execute(
            "INSERT INTO insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
            "VALUES (?,?,?,?,?,1)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha))

    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None, nombre: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.connect() as conn:
            ids = self._ids_de(conn, codigo, nombre)
            if len(ids) != 1:
                raise ValueError(
                    f"Código {codigo} resuelve a {len(ids)} insumos; "
                    f"especifica el nombre exacto para desambiguar.")
            self._insertar_precio_vigente(conn, ids[0], precio, fuente, fecha)

    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.connect() as conn:
            r = conn.execute("SELECT id FROM insumos WHERE id=?", (int(insumo_id),)).fetchone()
            if r is None:
                raise ValueError(f"No existe el insumo id={insumo_id}.")
            self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha)

    def set_meta(self, clave: str, valor: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)",
                         (clave, str(valor)))

    # ---- lectura ----
    def _fila_a_insumo(self, r) -> Insumo:
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"])

    def get_candidatos(self, codigo: str) -> list[Insumo]:
        """Todos los insumos con ese código (cada uno con su precio vigente e id)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM insumos i LEFT JOIN insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.codigo = ? ORDER BY i.id", (str(codigo),)).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_insumo_por_id(self, insumo_id: int) -> Optional[Insumo]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM insumos i LEFT JOIN insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.id = ?", (int(insumo_id),)).fetchone()
        return self._fila_a_insumo(r) if r else None

    def price_history(self, codigo: str, nombre: Optional[str] = None) -> list[dict]:
        with self.connect() as conn:
            q = ("SELECT p.precio, p.fuente, p.clasificacion, p.fecha, p.vigente "
                 "FROM insumo_precios p JOIN insumos i ON i.id = p.insumo_id "
                 "WHERE i.codigo = ?")
            params: list = [str(codigo)]
            if nombre is not None:
                q += " AND i.nombre_norm = ?"
                params.append(normalizar(nombre))
            q += " ORDER BY p.id"
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{texto.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE nombre LIKE ? OR codigo LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        """Insumos cuyo nombre contiene alguna de las `palabras` (ya tokenizadas por el dominio)."""
        palabras = [p for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre LIKE ?"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM insumos WHERE {clauses} LIMIT ?", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("insumos", "insumo_precios")}

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}
