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
from apu_tool.nucleo import relevancia
from apu_tool.nucleo.models import Insumo, ListaPrecios
from apu_tool.nucleo.texto import normalizar

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "precios.sql"


def _load_schema() -> str:
    return SCHEMA_PATH.read_text(encoding="utf-8")


def _resolver_lista_id(lista_id: Optional[int]) -> int:
    """`None` ≡ Principal (comportamiento de hoy). Cualquier otro valor, incluido
    `0`, se usa tal cual: `0` no es un id alcanzable hoy, pero tratarlo como
    "ausente" (p.ej. con `lista_id or LISTA_PRINCIPAL_ID`) costearía en silencio
    contra Principal en vez de fallar con la tarifa equivocada."""
    return int(lista_id) if lista_id is not None else config.LISTA_PRINCIPAL_ID


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
            # Migración PREVIA al executescript: en una base anterior a esta migración,
            # insumo_precios ya existe sin lista_id. db/precios.sql crea, sin condicionar,
            # el índice idx_precio_ins_lista sobre esa columna — y SQLite no puede indexar
            # una columna que todavía no existe. Por eso la columna se añade ANTES de
            # correr el script (a diferencia de creado_por/oculto, que no tienen ningún
            # índice del script colgando de ellas y sí pueden migrarse después).
            # PRAGMA table_info de una tabla que no existe aún devuelve 0 filas (no
            # lanza), así que en una base nueva "cols_previas" queda vacío y no se
            # intenta alterar una tabla inexistente: el CREATE TABLE del script la crea
            # con lista_id incluida desde el principio.
            cols_previas = {r["name"] for r in
                           conn.execute("PRAGMA table_info(insumo_precios)").fetchall()}
            if cols_previas and "lista_id" not in cols_previas:
                # Sin REFERENCES: SQLite no lo admite junto con NOT NULL DEFAULT (drift
                # declarado en db/precios.sql). El DEFAULT deja todo lo existente en
                # Principal, así que no hay backfill que escribir.
                conn.execute(
                    "ALTER TABLE insumo_precios ADD COLUMN lista_id INTEGER NOT NULL DEFAULT 1")
            conn.executescript(_load_schema())
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumo_precios)").fetchall()}
            if "creado_por" not in cols:
                conn.execute("ALTER TABLE insumo_precios ADD COLUMN creado_por TEXT")
            insumos_cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumos)").fetchall()}
            if "oculto" not in insumos_cols:
                conn.execute("ALTER TABLE insumos ADD COLUMN oculto INTEGER NOT NULL DEFAULT 0")
            self._asegurar_principal(conn)

    def reset(self) -> None:
        """Reconstruye el esquema desde cero (descarta y recrea desde db/precios.sql)."""
        with self.connect() as conn:
            for t in ("insumo_precios", "insumos", "lista_precios", "meta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())
            self._asegurar_principal(conn)

    def _asegurar_principal(self, conn) -> None:
        """Siembra la lista Principal (id 1) si falta. Idempotente."""
        r = conn.execute("SELECT id FROM lista_precios WHERE id=?",
                         (config.LISTA_PRINCIPAL_ID,)).fetchone()
        if r is None:
            conn.execute(
                "INSERT INTO lista_precios (id, nombre, creada_en, creado_por) "
                "VALUES (?, 'Principal', ?, NULL)",
                (config.LISTA_PRINCIPAL_ID, date.today().isoformat()))

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
                     creado_por: Optional[str] = None, lista_id: Optional[int] = None) -> int:
        """Crea un insumo NUEVO + su precio vigente; devuelve el id.

        Identidad (código, nombre_norm): si ya existe → ValueError (no se pisa, a
        diferencia de actualizar precio). Mismo código con otro nombre sí se permite
        (identidad distinta). A diferencia de insert_insumos (lote, INSERT OR IGNORE),
        este es para altas individuales con detección de duplicado."""
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        if conn is not None:
            return self._crear_insumo(conn, insumo, creado_por, lista_id)
        with self.connect() as c:
            return self._crear_insumo(c, insumo, creado_por, lista_id)

    def _crear_insumo(self, conn, insumo: Insumo, creado_por: Optional[str],
                      lista_id: Optional[int] = None) -> int:
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
        self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy,
                                      creado_por, lista_id)
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
                                fuente: str, fecha: str, creado_por: Optional[str] = None,
                                lista_id: Optional[int] = None) -> None:
        lid = _resolver_lista_id(lista_id)
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=? AND lista_id=?",
                     (int(insumo_id), lid))
        conn.execute(
            "INSERT INTO insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por, lista_id) "
            "VALUES (?,?,?,?,?,1,?,?)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha, creado_por, lid))

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
                          creado_por: Optional[str] = None,
                          lista_id: Optional[int] = None) -> None:
        fecha = fecha or date.today().isoformat()
        if conn is not None:
            self._set_precio_por_id(conn, insumo_id, precio, fuente, fecha, creado_por, lista_id)
            return
        with self.connect() as c:
            self._set_precio_por_id(c, insumo_id, precio, fuente, fecha, creado_por, lista_id)

    def _set_precio_por_id(self, conn, insumo_id, precio, fuente, fecha, creado_por,
                           lista_id=None) -> None:
        r = conn.execute("SELECT id FROM insumos WHERE id=?", (int(insumo_id),)).fetchone()
        if r is None:
            raise ValueError(f"No existe el insumo id={insumo_id}.")
        self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha,
                                      creado_por, lista_id)

    def set_meta(self, clave: str, valor: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)",
                         (clave, str(valor)))

    def set_oculto(self, insumo_id: int, oculto: bool,
                   conn: Optional[sqlite3.Connection] = None) -> None:
        sql = "UPDATE insumos SET oculto=? WHERE id=?"
        args = (1 if oculto else 0, int(insumo_id))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.connect() as c:
            c.execute(sql, args)

    def todos_no_ocultos(self) -> list[tuple[int, str, str]]:
        """(id, codigo, nombre) de todos los insumos con oculto=0."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, codigo, nombre FROM insumos WHERE oculto = 0").fetchall()
        return [(r["id"], r["codigo"], r["nombre"]) for r in rows]

    # ---- listas de precios ----
    @staticmethod
    def _limpiar_nombre_lista(nombre: str) -> str:
        limpio = (nombre or "").strip()[:80].strip()
        if not limpio:
            raise ValueError("El nombre de la lista no puede estar vacío.")
        return limpio

    @staticmethod
    def _fila_a_lista(r) -> ListaPrecios:
        return ListaPrecios(id=r["id"], nombre=r["nombre"], creada_en=r["creada_en"],
                            creado_por=r["creado_por"])

    def listar_listas(self) -> list[ListaPrecios]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM lista_precios "
                "ORDER BY id").fetchall()
        return [self._fila_a_lista(r) for r in rows]

    def get_lista(self, lista_id: int) -> Optional[ListaPrecios]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM lista_precios WHERE id=?",
                (int(lista_id),)).fetchone()
        return self._fila_a_lista(r) if r else None

    def crear_lista(self, nombre: str, creado_por: Optional[str] = None, conn=None) -> int:
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            return self._crear_lista(conn, limpio, creado_por)
        with self.connect() as c:
            return self._crear_lista(c, limpio, creado_por)

    def _crear_lista(self, conn, nombre: str, creado_por: Optional[str]) -> int:
        # Comparación en Python con normalizar() (quita tildes + MAYÚSCULAS), no con
        # UPPER() de SQL: UPPER() de SQLite es solo ASCII y no pliega ñ/tildes, así que
        # "NP Peñón" y "NP PEÑÓN" colarían como listas distintas. Son pocas listas
        # (unidades), así que traerlas todas y comparar en Python es barato, y la
        # lógica queda idéntica al backend Postgres (que hará lo mismo).
        nombre_norm = normalizar(nombre)
        existentes = conn.execute("SELECT nombre FROM lista_precios").fetchall()
        if any(normalizar(r["nombre"]) == nombre_norm for r in existentes):
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        cur = conn.execute(
            "INSERT INTO lista_precios (nombre, creada_en, creado_por) VALUES (?,?,?)",
            (nombre, date.today().isoformat(), creado_por))
        return int(cur.lastrowid)

    def renombrar_lista(self, lista_id: int, nombre: str, conn=None) -> None:
        if int(lista_id) == config.LISTA_PRINCIPAL_ID:
            raise ValueError("La lista Principal no se puede renombrar.")
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            self._renombrar_lista(conn, int(lista_id), limpio)
            return
        with self.connect() as c:
            self._renombrar_lista(c, int(lista_id), limpio)

    def _renombrar_lista(self, conn, lista_id: int, nombre: str) -> None:
        if conn.execute("SELECT 1 FROM lista_precios WHERE id=?", (lista_id,)).fetchone() is None:
            raise ValueError(f"No existe la lista de precios id={lista_id}.")
        # Mismo criterio que _crear_lista: comparar en Python con normalizar(), no con
        # UPPER() de SQL (no pliega ñ/tildes).
        nombre_norm = normalizar(nombre)
        existentes = conn.execute(
            "SELECT nombre FROM lista_precios WHERE id<>?", (lista_id,)).fetchall()
        if any(normalizar(r["nombre"]) == nombre_norm for r in existentes):
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        conn.execute("UPDATE lista_precios SET nombre=? WHERE id=?", (nombre, lista_id))

    # ---- lectura ----
    def _fila_a_insumo(self, r) -> Insumo:
        # precio es NOT NULL en la tabla: un NULL aquí solo puede venir del LEFT JOIN,
        # o sea "no hay precio vigente en esta lista" (≠ un $0 genuino).
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"],
                      sin_precio=r["precio"] is None)

    _SELECT_INSUMO = (
        "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
        "FROM insumos i LEFT JOIN insumo_precios p "
        "  ON p.insumo_id = i.id AND p.vigente = 1 AND p.lista_id = ? ")

    def get_candidatos(self, codigo: str, lista_id: Optional[int] = None) -> list[Insumo]:
        """Todos los insumos con ese código, con su precio vigente EN `lista_id`."""
        lid = _resolver_lista_id(lista_id)
        with self.connect() as conn:
            rows = conn.execute(
                self._SELECT_INSUMO + "WHERE i.codigo = ? ORDER BY i.id",
                (lid, str(codigo))).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_candidatos_bulk(self, codigos, lista_id: Optional[int] = None) -> dict:
        lid = _resolver_lista_id(lista_id)
        codes = [c for c in dict.fromkeys(str(x) for x in codigos if x)]
        out: dict[str, list[Insumo]] = {c: [] for c in codes}
        if not codes:
            return out
        with self.connect() as conn:
            for i in range(0, len(codes), 800):          # límite de placeholders de SQLite
                chunk = codes[i:i + 800]
                ph = ",".join("?" * len(chunk))
                rows = conn.execute(
                    self._SELECT_INSUMO + f"WHERE i.codigo IN ({ph}) ORDER BY i.codigo, i.id",
                    [lid] + chunk).fetchall()
                for r in rows:
                    out[r["codigo"]].append(self._fila_a_insumo(r))
        return out

    def get_insumo_por_id(self, insumo_id: int,
                          lista_id: Optional[int] = None) -> Optional[Insumo]:
        lid = _resolver_lista_id(lista_id)
        with self.connect() as conn:
            r = conn.execute(self._SELECT_INSUMO + "WHERE i.id = ?",
                             (lid, int(insumo_id))).fetchone()
        return self._fila_a_insumo(r) if r else None

    def price_history(self, codigo: str, nombre: Optional[str] = None,
                      lista_id: Optional[int] = None) -> list[dict]:
        lid = _resolver_lista_id(lista_id)
        with self.connect() as conn:
            q = ("SELECT p.precio, p.fuente, p.clasificacion, p.fecha, p.vigente "
                 "FROM insumo_precios p JOIN insumos i ON i.id = p.insumo_id "
                 "WHERE i.codigo = ? AND p.lista_id = ?")
            params: list = [str(codigo), lid]
            if nombre is not None:
                q += " AND i.nombre_norm = ?"
                params.append(normalizar(nombre))
            q += " ORDER BY p.id"
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def list_insumos(self, q=None, grupo=None, fuente=None,
                     clasificacion: Optional[str] = None,
                     limit: int = 100, offset: int = 0,
                     lista_id: Optional[int] = None,
                     sin_precio: bool = False) -> tuple[list[Insumo], int]:
        """Catálogo COMPLETO con el precio vigente en `lista_id`. Los insumos sin
        tarifa en esa lista vienen igual, con precio 0 y `sin_precio=True`: la lista
        decide QUÉ PRECIO se lee, no QUÉ INSUMOS existen."""
        if sin_precio and (fuente or clasificacion):
            raise ValueError(
                "El filtro «sin precio en esta lista» no se puede combinar con "
                "fuente ni clasificación: son atributos de un precio que no existe.")
        lid = _resolver_lista_id(lista_id)
        base = ("FROM insumos i LEFT JOIN insumo_precios p "
                "ON p.insumo_id = i.id AND p.vigente = 1 AND p.lista_id = ?")
        where, params = ["i.oculto = 0"], [lid]
        if sin_precio:
            where.append("p.id IS NULL")
        if q:
            # Una palabra = un LIKE, todas en AND: antes `q` era una frase literal y
            # "transporte material" no encontraba "TRANSPORTE DE MATERIAL".
            for palabra in relevancia.palabras(q):
                where.append("(i.nombre_norm LIKE ? OR UPPER(i.codigo) LIKE ?)")
                params += [f"%{palabra}%", f"%{palabra}%"]
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
            # p.id IS NOT NULL exige que EXISTA una fila de precio vigente en esta
            # lista: sin eso, un insumo sin tarifa (p.fuente IS NULL por el LEFT JOIN)
            # colaría como "interno" sin serlo. En Principal es inocuo (todo insumo
            # tiene su fila de precio desde que se crea), pero en una lista NP la
            # ausencia de fila es el caso dominante, no la excepción.
            placeholders = ",".join("?" * len(config.PUBLIC_PRICE_SOURCES))
            where.append(
                f"(p.id IS NOT NULL AND "
                f"(p.fuente IS NULL OR UPPER(p.fuente) NOT IN ({placeholders})))")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        campos = "i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente"
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) {base}{wsql}", params).fetchone()[0]
            if q and int(total) <= relevancia.MAX_RANKEO:
                # Rankear exige tener los candidatos en la mano. Arriba del techo se
                # cae al orden por código (ver relevancia.MAX_RANKEO).
                rows = conn.execute(
                    f"SELECT {campos} {base}{wsql} ORDER BY i.codigo, i.id",
                    params).fetchall()
                ordenados = relevancia.ordenar(
                    [self._fila_a_insumo(r) for r in rows], q,
                    nombre_de=lambda i: i.nombre, codigo_de=lambda i: i.codigo)
                # total = len(ordenados), no el COUNT: el WHERE de SQL es un poco más
                # laxo que el filtro de Python (UPPER(codigo) vs normalizar(codigo)) y
                # con dos fuentes de verdad el contador diría 41 sobre una lista de 40.
                return ordenados[int(offset):int(offset) + int(limit)], len(ordenados)
            rows = conn.execute(
                f"SELECT {campos} {base}{wsql} ORDER BY i.codigo, i.id LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)

    def grupos(self) -> list[str]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' AND oculto = 0 ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]

    def fuentes(self, lista_id: Optional[int] = None) -> list[str]:
        lid = _resolver_lista_id(lista_id)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT p.fuente FROM insumo_precios p "
                "JOIN insumos i ON i.id = p.insumo_id AND i.oculto = 0 "
                "WHERE p.vigente = 1 AND p.lista_id = ? "
                "  AND p.fuente IS NOT NULL AND p.fuente <> '' "
                "ORDER BY p.fuente", (lid,)).fetchall()
        return [r["fuente"] for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE (nombre_norm LIKE ? OR UPPER(codigo) LIKE ?) "
                "AND oculto = 0 LIMIT ?",
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
                f"SELECT id FROM insumos WHERE ({clauses}) AND oculto = 0 LIMIT ?", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def counts(self) -> dict[str, int]:
        """`insumos` = TODAS las filas; `insumos_visibles` = las que no están ocultas.

        Las dos claves existen a propósito: `insumos` es el guard de `seed()` y de
        `pipeline.ensure_seeded()` ("¿la base ya tiene catálogo?") y tiene que seguir
        contando los ocultos — si no, una base con todo oculto parecería vacía y se
        re-semillaría encima. `insumos_visibles` es lo que se le muestra al usuario,
        para que cuadre con `GET /api/insumos` (que filtra `oculto = 0`).
        """
        with self.connect() as conn:
            c = {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                 for t in ("insumos", "insumo_precios")}
            try:
                c["insumos_visibles"] = conn.execute(
                    "SELECT COUNT(*) FROM insumos WHERE oculto = 0").fetchone()[0]
            except sqlite3.OperationalError:
                # Base anterior a la columna `oculto` (la agrega init_schema, y
                # `seed()` llama a counts() ANTES de eso). Si dejáramos propagar,
                # seed se come el OperationalError, la ve vacía y la re-semilla
                # encima: nada estaba oculto en ese esquema, así que total == visible.
                c["insumos_visibles"] = c["insumos"]
            return c

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}

    def descripcion(self) -> str:
        return f"SQLite: {self.path}"
