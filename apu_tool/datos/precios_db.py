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
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumo_precios)").fetchall()}
            if "creado_por" not in cols:
                conn.execute("ALTER TABLE insumo_precios ADD COLUMN creado_por TEXT")

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

    def crear_insumo(self, insumo: Insumo, conn: Optional[sqlite3.Connection] = None,
                     creado_por: Optional[str] = None) -> int:
        """Crea un insumo NUEVO + su precio vigente; devuelve el id.

        Identidad (código, nombre_norm): si ya existe → ValueError (no se pisa, a
        diferencia de actualizar precio). Mismo código con otro nombre sí se permite
        (identidad distinta). A diferencia de insert_insumos (lote, INSERT OR IGNORE),
        este es para altas individuales con detección de duplicado."""
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        if conn is not None:
            return self._crear_insumo(conn, insumo, creado_por)
        with self.connect() as c:
            return self._crear_insumo(c, insumo, creado_por)

    def _crear_insumo(self, conn, insumo: Insumo, creado_por: Optional[str]) -> int:
        nombre_norm = normalizar(insumo.nombre)
        hoy = date.today().isoformat()
        existe = conn.execute(
            "SELECT 1 FROM insumos WHERE codigo=? AND nombre_norm=?",
            (str(insumo.codigo), nombre_norm)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un insumo con código {insumo.codigo} y ese nombre.")
        cur = conn.execute(
            "INSERT INTO insumos (codigo, nombre, nombre_norm, unidad, grupo) "
            "VALUES (?,?,?,?,?)",
            (str(insumo.codigo), insumo.nombre, nombre_norm, insumo.unidad, insumo.grupo))
        iid = int(cur.lastrowid)
        self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy, creado_por)
        return iid

    def _ids_de(self, conn, codigo: str, nombre: Optional[str]) -> list[int]:
        if nombre is None:
            rows = conn.execute("SELECT id FROM insumos WHERE codigo=?",
                                (str(codigo),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE codigo=? AND nombre_norm=?",
                (str(codigo), normalizar(nombre))).fetchall()
        return [r["id"] for r in rows]

    def _insertar_precio_vigente(self, conn: sqlite3.Connection, insumo_id: int, precio: float,
                                fuente: str, fecha: str, creado_por: Optional[str] = None) -> None:
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=?", (int(insumo_id),))
        conn.execute(
            "INSERT INTO insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
            "VALUES (?,?,?,?,?,1,?)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha, creado_por))

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
                          fecha: Optional[str] = None, conn: Optional[sqlite3.Connection] = None,
                          creado_por: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        if conn is not None:
            self._set_precio_por_id(conn, insumo_id, precio, fuente, fecha, creado_por)
            return
        with self.connect() as c:
            self._set_precio_por_id(c, insumo_id, precio, fuente, fecha, creado_por)

    def _set_precio_por_id(self, conn, insumo_id, precio, fuente, fecha, creado_por) -> None:
        r = conn.execute("SELECT id FROM insumos WHERE id=?", (int(insumo_id),)).fetchone()
        if r is None:
            raise ValueError(f"No existe el insumo id={insumo_id}.")
        self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha, creado_por)

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

    def get_candidatos_bulk(self, codigos) -> dict:
        codes = [c for c in dict.fromkeys(str(x) for x in codigos if x)]
        out: dict[str, list[Insumo]] = {c: [] for c in codes}
        if not codes:
            return out
        with self.connect() as conn:
            for i in range(0, len(codes), 800):          # límite de placeholders de SQLite
                chunk = codes[i:i + 800]
                ph = ",".join("?" * len(chunk))
                rows = conn.execute(
                    "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                    "FROM insumos i LEFT JOIN insumo_precios p "
                    "  ON p.insumo_id = i.id AND p.vigente = 1 "
                    f"WHERE i.codigo IN ({ph}) ORDER BY i.codigo, i.id", chunk).fetchall()
                for r in rows:
                    out[r["codigo"]].append(self._fila_a_insumo(r))
        return out

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

    def list_insumos(self, q=None, grupo=None, fuente=None,
                     clasificacion: Optional[str] = None,
                     limit: int = 100, offset: int = 0) -> tuple[list[Insumo], int]:
        base = ("FROM insumos i LEFT JOIN insumo_precios p "
                "ON p.insumo_id = i.id AND p.vigente = 1")
        where, params = [], []
        if q:
            where.append("(i.nombre_norm LIKE ? OR UPPER(i.codigo) LIKE ?)")
            like = f"%{normalizar(q)}%"
            params += [like, f"%{normalizar(q)}%"]
        if grupo:
            where.append("i.grupo = ?")
            params.append(grupo)
        if fuente:
            where.append("p.fuente = ?")
            params.append(fuente)
        if clasificacion == "publico":
            placeholders = ",".join("?" * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"UPPER(p.fuente) IN ({placeholders})")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        elif clasificacion == "interno":
            placeholders = ",".join("?" * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"(p.fuente IS NULL OR UPPER(p.fuente) NOT IN ({placeholders}))")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) {base}{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                f"{base}{wsql} ORDER BY i.codigo, i.id LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)

    def grupos(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]

    def fuentes(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fuente FROM insumo_precios "
                "WHERE vigente = 1 AND fuente IS NOT NULL AND fuente <> '' "
                "ORDER BY fuente").fetchall()
        return [r["fuente"] for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE nombre_norm LIKE ? OR UPPER(codigo) LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        """Insumos cuyo nombre_norm contiene alguna de las `palabras` (ya tokenizadas por el dominio)."""
        palabras = [normalizar(p) for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre_norm LIKE ?"] * len(palabras))
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

    def descripcion(self) -> str:
        return f"SQLite: {self.path}"
