"""Backend Postgres de precios. Implementa RepositorioPrecios.

Port 1:1 de apu_tool/datos/precios_db.py a Postgres (psycopg v3). Misma lógica
de negocio; cambian dialecto SQL (%s, ON CONFLICT, RETURNING) y tablas
calificadas por schema. NO toca dinero de cara a la IA (fuera de su alcance).
"""
from __future__ import annotations

from datetime import date
from typing import Iterable, Optional

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
from apu_tool.nucleo.models import Insumo
from apu_tool.nucleo.texto import normalizar

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "precios.sql"


class PreciosPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        with self.cx.connection() as conn:
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    # ---- escritura ----
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int:
        hoy = date.today().isoformat()
        n = 0
        with self.cx.connection() as conn:
            for i in insumos:
                nombre_norm = normalizar(i.nombre)
                cur = conn.execute(
                    "INSERT INTO precios.insumos "
                    "(codigo, nombre, nombre_norm, unidad, grupo) VALUES (%s,%s,%s,%s,%s) "
                    # ON CONFLICT sobre la única restricción unique de la tabla (además de PK identity)
                    "ON CONFLICT (codigo, nombre_norm) DO NOTHING RETURNING id",
                    (i.codigo, i.nombre, nombre_norm, i.unidad, i.grupo))
                row = cur.fetchone()
                if row is None:
                    continue  # identidad ya existía; no duplicar precio
                iid = row["id"]
                conn.execute(
                    "INSERT INTO precios.insumo_precios "
                    "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                    "VALUES (%s,%s,%s,%s,%s,1)",
                    (iid, i.precio, i.fuente_precio,
                     config.classify_price_source(i.fuente_precio), hoy))
                n += 1
        return n

    def crear_insumo(self, insumo: Insumo) -> int:
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        nombre_norm = normalizar(insumo.nombre)
        hoy = date.today().isoformat()
        with self.cx.connection() as conn:
            existe = conn.execute(
                "SELECT 1 FROM precios.insumos WHERE codigo=%s AND nombre_norm=%s",
                (str(insumo.codigo), nombre_norm)).fetchone()
            if existe:
                raise ValueError(
                    f"Ya existe un insumo con código {insumo.codigo} y ese nombre.")
            cur = conn.execute(
                "INSERT INTO precios.insumos (codigo, nombre, nombre_norm, unidad, grupo) "
                "VALUES (%s,%s,%s,%s,%s) RETURNING id",
                (str(insumo.codigo), insumo.nombre, nombre_norm, insumo.unidad, insumo.grupo))
            iid = int(cur.fetchone()["id"])
            self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy)
            return iid

    def _ids_de(self, conn, codigo: str, nombre: Optional[str]) -> list[int]:
        if nombre is None:
            rows = conn.execute("SELECT id FROM precios.insumos WHERE codigo=%s",
                                (str(codigo),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE codigo=%s AND nombre_norm=%s",
                (str(codigo), normalizar(nombre))).fetchall()
        return [r["id"] for r in rows]

    def _insertar_precio_vigente(self, conn, insumo_id: int, precio: float,
                                 fuente: str, fecha: str) -> None:
        conn.execute("UPDATE precios.insumo_precios SET vigente=0 WHERE insumo_id=%s",
                     (int(insumo_id),))
        conn.execute(
            "INSERT INTO precios.insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
            "VALUES (%s,%s,%s,%s,%s,1)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha))

    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None, nombre: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.cx.connection() as conn:
            ids = self._ids_de(conn, codigo, nombre)
            if len(ids) != 1:
                raise ValueError(
                    f"Código {codigo} resuelve a {len(ids)} insumos; "
                    f"especifica el nombre exacto para desambiguar.")
            self._insertar_precio_vigente(conn, ids[0], precio, fuente, fecha)

    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.cx.connection() as conn:
            r = conn.execute("SELECT id FROM precios.insumos WHERE id=%s",
                             (int(insumo_id),)).fetchone()
            if r is None:
                raise ValueError(f"No existe el insumo id={insumo_id}.")
            self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha)

    def set_meta(self, clave: str, valor: str) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "INSERT INTO precios.meta (clave, valor) VALUES (%s,%s) "
                "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                (clave, str(valor)))

    # ---- lectura ----
    def _fila_a_insumo(self, r) -> Insumo:
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"])

    def get_candidatos(self, codigo: str) -> list[Insumo]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.codigo = %s ORDER BY i.id", (str(codigo),)).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_insumo_por_id(self, insumo_id: int) -> Optional[Insumo]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.id = %s", (int(insumo_id),)).fetchone()
        return self._fila_a_insumo(r) if r else None

    def price_history(self, codigo: str, nombre: Optional[str] = None) -> list[dict]:
        with self.cx.connection() as conn:
            q = ("SELECT p.precio, p.fuente, p.clasificacion, p.fecha, p.vigente "
                 "FROM precios.insumo_precios p JOIN precios.insumos i ON i.id = p.insumo_id "
                 "WHERE i.codigo = %s")
            params: list = [str(codigo)]
            if nombre is not None:
                q += " AND i.nombre_norm = %s"
                params.append(normalizar(nombre))
            q += " ORDER BY p.id"
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def list_insumos(self, q=None, grupo=None, fuente=None,
                     clasificacion: Optional[str] = None,
                     limit: int = 100, offset: int = 0) -> tuple[list[Insumo], int]:
        base = ("FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
                "ON p.insumo_id = i.id AND p.vigente = 1")
        where, params = [], []
        if q:
            where.append("(i.nombre ILIKE %s OR i.codigo ILIKE %s)")
            like = f"%{q.strip()}%"
            params += [like, like]
        if grupo:
            where.append("i.grupo = %s")
            params.append(grupo)
        if fuente:
            where.append("p.fuente = %s")
            params.append(fuente)
        if clasificacion == "publico":
            placeholders = ",".join(["%s"] * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"UPPER(p.fuente) IN ({placeholders})")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        elif clasificacion == "interno":
            placeholders = ",".join(["%s"] * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"(p.fuente IS NULL OR UPPER(p.fuente) NOT IN ({placeholders}))")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.cx.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n {base}{wsql}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                f"{base}{wsql} ORDER BY i.codigo, i.id LIMIT %s OFFSET %s",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)

    def grupos(self) -> list[str]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM precios.insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]

    def fuentes(self) -> list[str]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT fuente FROM precios.insumo_precios "
                "WHERE vigente = 1 AND fuente IS NOT NULL AND fuente <> '' "
                "ORDER BY fuente").fetchall()
        return [r["fuente"] for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{texto.strip()}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE nombre ILIKE %s OR codigo ILIKE %s LIMIT %s",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        palabras = [p for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre ILIKE %s"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.cx.connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM precios.insumos WHERE {clauses} LIMIT %s", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM precios.{t}").fetchone()["n"]
                    for t in ("insumos", "insumo_precios")}

    def get_meta(self) -> dict[str, str]:
        with self.cx.connection() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM precios.meta").fetchall()}
