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
from apu_tool.nucleo import relevancia
from apu_tool.nucleo.models import Insumo, ListaPrecios
from apu_tool.nucleo.texto import normalizar

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "precios.sql"


def _resolver_lista_id(lista_id: Optional[int]) -> int:
    """`None` ≡ Principal (comportamiento de hoy). Cualquier otro valor, incluido
    `0`, se usa tal cual: `0` no es un id alcanzable hoy, pero tratarlo como
    "ausente" (p.ej. con `lista_id or LISTA_PRINCIPAL_ID`) costearía en silencio
    contra Principal en vez de fallar con la tarifa equivocada."""
    return int(lista_id) if lista_id is not None else config.LISTA_PRINCIPAL_ID


class PreciosPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        self.cx.ejecutar_migracion(SCHEMA_PATH.read_text(encoding="utf-8"))

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

    def crear_insumo(self, insumo: Insumo, conn=None, creado_por: Optional[str] = None,
                     lista_id: Optional[int] = None) -> int:
        """Crea un insumo NUEVO + su precio vigente; devuelve el id.

        Identidad (código, nombre_norm): si ya existe → ValueError (no se pisa, a
        diferencia de actualizar precio). Mismo código con otro nombre sí se permite
        (identidad distinta). A diferencia de insert_insumos (lote, ON CONFLICT DO
        NOTHING), este es para altas individuales con detección de duplicado."""
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        if conn is not None:
            return self._crear_insumo(conn, insumo, creado_por, lista_id)
        with self.cx.connection() as c:
            return self._crear_insumo(c, insumo, creado_por, lista_id)

    def _crear_insumo(self, conn, insumo: Insumo, creado_por: Optional[str],
                      lista_id: Optional[int] = None) -> int:
        nombre_norm = normalizar(insumo.nombre)
        hoy = date.today().isoformat()
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
        self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy,
                                      creado_por, lista_id)
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
                                 fuente: str, fecha: str, creado_por: Optional[str] = None,
                                 lista_id: Optional[int] = None) -> None:
        lid = _resolver_lista_id(lista_id)
        conn.execute(
            "UPDATE precios.insumo_precios SET vigente=0 WHERE insumo_id=%s AND lista_id=%s",
            (int(insumo_id), lid))
        conn.execute(
            "INSERT INTO precios.insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por, lista_id) "
            "VALUES (%s,%s,%s,%s,%s,1,%s,%s)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha, creado_por, lid))

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
                          fecha: Optional[str] = None, conn=None,
                          creado_por: Optional[str] = None,
                          lista_id: Optional[int] = None) -> None:
        fecha = fecha or date.today().isoformat()
        if conn is not None:
            self._set_precio_por_id(conn, insumo_id, precio, fuente, fecha, creado_por, lista_id)
            return
        with self.cx.connection() as c:
            self._set_precio_por_id(c, insumo_id, precio, fuente, fecha, creado_por, lista_id)

    def _set_precio_por_id(self, conn, insumo_id, precio, fuente, fecha, creado_por,
                           lista_id=None) -> None:
        r = conn.execute("SELECT id FROM precios.insumos WHERE id=%s",
                         (int(insumo_id),)).fetchone()
        if r is None:
            raise ValueError(f"No existe el insumo id={insumo_id}.")
        self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha,
                                      creado_por, lista_id)

    def set_meta(self, clave: str, valor: str) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "INSERT INTO precios.meta (clave, valor) VALUES (%s,%s) "
                "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                (clave, str(valor)))

    def set_oculto(self, insumo_id: int, oculto: bool, conn=None) -> None:
        sql = "UPDATE precios.insumos SET oculto=%s WHERE id=%s"
        args = (bool(oculto), int(insumo_id))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.cx.connection() as c:
            c.execute(sql, args)

    def todos_no_ocultos(self) -> list[tuple[int, str, str]]:
        """(id, codigo, nombre) de todos los insumos con oculto=false."""
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id, codigo, nombre FROM precios.insumos WHERE oculto = FALSE").fetchall()
        return [(r["id"], r["codigo"], r["nombre"]) for r in rows]

    def identidades_en_conflicto(self, codigo: str,
                                 nombre_norm: str) -> list[tuple[str, str, bool]]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT codigo, nombre, oculto FROM precios.insumos "
                "WHERE codigo = %s OR nombre_norm = %s ORDER BY id",
                (str(codigo), nombre_norm)).fetchall()
        return [(r["codigo"], r["nombre"], bool(r["oculto"])) for r in rows]

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
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM precios.lista_precios "
                "ORDER BY id").fetchall()
        return [self._fila_a_lista(r) for r in rows]

    def get_lista(self, lista_id: int) -> Optional[ListaPrecios]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM precios.lista_precios "
                "WHERE id=%s", (int(lista_id),)).fetchone()
        return self._fila_a_lista(r) if r else None

    def crear_lista(self, nombre: str, creado_por: Optional[str] = None, conn=None) -> int:
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            return self._crear_lista(conn, limpio, creado_por)
        with self.cx.connection() as c:
            return self._crear_lista(c, limpio, creado_por)

    def _crear_lista(self, conn, nombre: str, creado_por: Optional[str]) -> int:
        # Comparación en Python con normalizar() (quita tildes + MAYÚSCULAS), no con
        # UPPER() de SQL: igual que en SQLite, para que ambos backends se comporten
        # IGUAL con nombres de obra que llevan ñ/tildes ("NP Peñón" vs "NP PEÑÓN").
        nombre_norm = normalizar(nombre)
        existentes = conn.execute("SELECT nombre FROM precios.lista_precios").fetchall()
        if any(normalizar(r["nombre"]) == nombre_norm for r in existentes):
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        cur = conn.execute(
            "INSERT INTO precios.lista_precios (nombre, creada_en, creado_por) "
            "VALUES (%s,%s,%s) RETURNING id",
            (nombre, date.today().isoformat(), creado_por))
        return int(cur.fetchone()["id"])

    def renombrar_lista(self, lista_id: int, nombre: str, conn=None) -> None:
        if int(lista_id) == config.LISTA_PRINCIPAL_ID:
            raise ValueError("La lista Principal no se puede renombrar.")
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            self._renombrar_lista(conn, int(lista_id), limpio)
            return
        with self.cx.connection() as c:
            self._renombrar_lista(c, int(lista_id), limpio)

    def _renombrar_lista(self, conn, lista_id: int, nombre: str) -> None:
        if conn.execute("SELECT 1 FROM precios.lista_precios WHERE id=%s",
                        (lista_id,)).fetchone() is None:
            raise ValueError(f"No existe la lista de precios id={lista_id}.")
        # Mismo criterio que _crear_lista: comparar en Python con normalizar(), no con
        # UPPER() de SQL (no pliega ñ/tildes).
        nombre_norm = normalizar(nombre)
        existentes = conn.execute(
            "SELECT nombre FROM precios.lista_precios WHERE id<>%s", (lista_id,)).fetchall()
        if any(normalizar(r["nombre"]) == nombre_norm for r in existentes):
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        conn.execute("UPDATE precios.lista_precios SET nombre=%s WHERE id=%s",
                     (nombre, lista_id))

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
        "FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
        "  ON p.insumo_id = i.id AND p.vigente = 1 AND p.lista_id = %s ")

    def get_candidatos(self, codigo: str, lista_id: Optional[int] = None) -> list[Insumo]:
        """Todos los insumos con ese código, con su precio vigente EN `lista_id`."""
        lid = _resolver_lista_id(lista_id)
        with self.cx.connection() as conn:
            rows = conn.execute(
                self._SELECT_INSUMO + "WHERE i.codigo = %s ORDER BY i.id",
                (lid, str(codigo))).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_candidatos_bulk(self, codigos, lista_id: Optional[int] = None) -> dict:
        lid = _resolver_lista_id(lista_id)
        codes = [c for c in dict.fromkeys(str(x) for x in codigos if x)]
        out: dict[str, list[Insumo]] = {c: [] for c in codes}
        if not codes:
            return out
        with self.cx.connection() as conn:
            rows = conn.execute(
                self._SELECT_INSUMO + "WHERE i.codigo = ANY(%s) ORDER BY i.codigo, i.id",
                (lid, codes)).fetchall()
        for r in rows:
            out[r["codigo"]].append(self._fila_a_insumo(r))
        return out

    def get_insumo_por_id(self, insumo_id: int,
                          lista_id: Optional[int] = None) -> Optional[Insumo]:
        lid = _resolver_lista_id(lista_id)
        with self.cx.connection() as conn:
            r = conn.execute(self._SELECT_INSUMO + "WHERE i.id = %s",
                             (lid, int(insumo_id))).fetchone()
        return self._fila_a_insumo(r) if r else None

    def price_history(self, codigo: str, nombre: Optional[str] = None,
                      lista_id: Optional[int] = None) -> list[dict]:
        lid = _resolver_lista_id(lista_id)
        with self.cx.connection() as conn:
            q = ("SELECT p.precio, p.fuente, p.clasificacion, p.fecha, p.vigente "
                 "FROM precios.insumo_precios p JOIN precios.insumos i ON i.id = p.insumo_id "
                 "WHERE i.codigo = %s AND p.lista_id = %s")
            params: list = [str(codigo), lid]
            if nombre is not None:
                q += " AND i.nombre_norm = %s"
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
        base = ("FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
                "ON p.insumo_id = i.id AND p.vigente = 1 AND p.lista_id = %s")
        where, params = ["i.oculto = FALSE"], [lid]
        if sin_precio:
            where.append("p.id IS NULL")
        if q:
            # Una palabra = un LIKE, todas en AND (igual que precios_db.py).
            for palabra in relevancia.palabras(q):
                where.append("(i.nombre_norm LIKE %s OR UPPER(i.codigo) LIKE %s)")
                params += [f"%{palabra}%", f"%{palabra}%"]
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
            # p.id IS NOT NULL exige que EXISTA una fila de precio vigente en esta
            # lista: sin eso, un insumo sin tarifa (p.fuente IS NULL por el LEFT JOIN)
            # colaría como "interno" sin serlo. En Principal es inocuo (todo insumo
            # tiene su fila de precio desde que se crea), pero en una lista NP la
            # ausencia de fila es el caso dominante, no la excepción.
            placeholders = ",".join(["%s"] * len(config.PUBLIC_PRICE_SOURCES))
            where.append(
                f"(p.id IS NOT NULL AND "
                f"(p.fuente IS NULL OR UPPER(p.fuente) NOT IN ({placeholders})))")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        campos = "i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente"
        with self.cx.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n {base}{wsql}", params).fetchone()["n"]
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
                f"SELECT {campos} {base}{wsql} ORDER BY i.codigo, i.id LIMIT %s OFFSET %s",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)

    def grupos(self) -> list[str]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM precios.insumos "
                "WHERE grupo IS NOT NULL AND grupo <> '' AND oculto = FALSE ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]

    def fuentes(self, lista_id: Optional[int] = None) -> list[str]:
        lid = _resolver_lista_id(lista_id)
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT p.fuente FROM precios.insumo_precios p "
                "JOIN precios.insumos i ON i.id = p.insumo_id AND i.oculto = FALSE "
                "WHERE p.vigente = 1 AND p.lista_id = %s "
                "  AND p.fuente IS NOT NULL AND p.fuente <> '' "
                "ORDER BY p.fuente", (lid,)).fetchall()
        return [r["fuente"] for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE (nombre_norm LIKE %s OR UPPER(codigo) LIKE %s) "
                "AND oculto = FALSE LIMIT %s", (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        palabras = [normalizar(p) for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre_norm LIKE %s"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.cx.connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM precios.insumos WHERE ({clauses}) AND oculto = FALSE LIMIT %s", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def counts(self) -> dict[str, int]:
        """Espejo de PreciosDB.counts(): ver allí por qué van las dos claves."""
        with self.cx.connection() as conn:
            c = {t: conn.execute(f"SELECT COUNT(*) AS n FROM precios.{t}").fetchone()["n"]
                 for t in ("insumos", "insumo_precios")}
            c["insumos_visibles"] = conn.execute(
                "SELECT COUNT(*) AS n FROM precios.insumos WHERE oculto = FALSE"
            ).fetchone()["n"]
            return c

    def get_meta(self) -> dict[str, str]:
        with self.cx.connection() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM precios.meta").fetchall()}

    def descripcion(self) -> str:
        return "Postgres (schema precios)"
