"""
Backend Postgres de APUs. Implementa RepositorioApus. Port 1:1 de apus_db.py.

NO toca dinero (precio_unitario_hist es un respaldo embebido, no se expone a la IA).
get_depriced_apu devuelve la vista SIN dinero para la IA.
"""
from __future__ import annotations

from typing import Iterable, Optional

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
from apu_tool.nucleo.models import Apu, ApuComponent, DePricedApu, DePricedComponent

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "apus.sql"


class ApusPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        with self.cx.connection() as conn:
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS apus CASCADE")
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    # ---- escritura ----
    def insert_apus(self, apus: Iterable[Apu]) -> int:
        rows = [(a.codigo, a.shift, a.nombre, a.unidad, a.grupo) for a in apus]
        with self.cx.connection() as conn, conn.cursor() as cur:
            cur.executemany(
                "INSERT INTO apus.apus (codigo, shift, nombre, unidad, grupo) "
                "VALUES (%s,%s,%s,%s,%s) "
                "ON CONFLICT (codigo, shift) DO UPDATE SET "
                "nombre=EXCLUDED.nombre, unidad=EXCLUDED.unidad, grupo=EXCLUDED.grupo", rows)
        return len(rows)

    def insert_components(self, comps: Iterable[ApuComponent]) -> int:
        comps = list(comps)
        with self.cx.connection() as conn:
            seq_by_key: dict[tuple[str, str], int] = {}
            rows = []
            for c in comps:
                key = (c.apu_codigo, c.shift)
                if key not in seq_by_key:
                    r = conn.execute(
                        "SELECT COALESCE(MAX(seq) + 1, 0) AS s FROM apus.apu_componentes "
                        "WHERE apu_codigo=%s AND shift=%s", key).fetchone()
                    seq_by_key[key] = r["s"]
                seq = seq_by_key[key]
                seq_by_key[key] = seq + 1
                rows.append((c.apu_codigo, c.shift, seq, c.insumo_codigo,
                             c.insumo_nombre, c.unidad, c.rendimiento,
                             c.precio_unitario_hist, c.tipo, c.ref_shift))
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO apus.apu_componentes "
                    "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                    " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        return len(rows)

    def crear_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        if not str(apu.codigo or "").strip() or not str(apu.nombre or "").strip():
            raise ValueError("El APU necesita código y nombre.")
        if conn is not None:
            return self._crear_apu(conn, apu, componentes)
        with self.cx.connection() as c:
            return self._crear_apu(c, apu, componentes)

    def _crear_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus.apus WHERE codigo=%s AND shift=%s",
                              (str(apu.codigo), apu.shift)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "INSERT INTO apus.apus (codigo, shift, nombre, unidad, grupo) "
            "VALUES (%s,%s,%s,%s,%s)",
            (str(apu.codigo), apu.shift, apu.nombre, apu.unidad, apu.grupo))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist, c.tipo, c.ref_shift)
                for seq, c in enumerate(componentes)]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO apus.apu_componentes "
                    "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                    " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)

    def editar_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        """Edita cabecera + reemplaza composición de un APU existente. ValueError si no existe."""
        if conn is not None:
            return self._editar_apu(conn, apu, componentes)
        with self.cx.connection() as c:
            return self._editar_apu(c, apu, componentes)

    def _editar_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus.apus WHERE codigo=%s AND shift=%s",
                              (str(apu.codigo), apu.shift)).fetchone()
        if not existe:
            raise ValueError(
                f"No existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "UPDATE apus.apus SET nombre=%s, unidad=%s, grupo=%s WHERE codigo=%s AND shift=%s",
            (apu.nombre, apu.unidad, apu.grupo, str(apu.codigo), apu.shift))
        conn.execute("DELETE FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s",
                     (str(apu.codigo), apu.shift))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist, c.tipo, c.ref_shift)
                for seq, c in enumerate(componentes)]
        if rows:
            with conn.cursor() as cur:
                cur.executemany(
                    "INSERT INTO apus.apu_componentes "
                    "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                    " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s)", rows)

    def borrar_apu(self, codigo: str, shift: str, conn=None) -> bool:
        if conn is not None:
            return self._borrar_apu(conn, codigo, shift)
        with self.cx.connection() as c:
            return self._borrar_apu(c, codigo, shift)

    def _borrar_apu(self, conn, codigo: str, shift: str) -> bool:
        existe = conn.execute("SELECT 1 FROM apus.apus WHERE codigo=%s AND shift=%s",
                              (str(codigo), shift)).fetchone()
        if not existe:
            return False
        conn.execute("DELETE FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s",
                     (str(codigo), shift))
        conn.execute("DELETE FROM apus.apus WHERE codigo=%s AND shift=%s", (str(codigo), shift))
        return True

    def set_meta(self, clave: str, valor: str) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "INSERT INTO apus.meta (clave, valor) VALUES (%s,%s) "
                "ON CONFLICT (clave) DO UPDATE SET valor=EXCLUDED.valor",
                (clave, str(valor)))

    # ---- lectura ----
    def all_apus(self) -> list[Apu]:
        with self.cx.connection() as conn:
            rows = conn.execute("SELECT * FROM apus.apus").fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def apu_index(self) -> list[tuple[str, str, str]]:
        with self.cx.connection() as conn:
            rows = conn.execute("SELECT codigo, nombre, shift FROM apus.apus").fetchall()
        return [(r["codigo"], r["nombre"], r["shift"]) for r in rows]

    def list_apus(self, q: Optional[str] = None, grupo: Optional[str] = None,
                  shift: Optional[str] = None, limit: int = 100,
                  offset: int = 0) -> tuple[list[Apu], int]:
        # NOTA: la búsqueda por nombre aquí usa ILIKE (Postgres); en apus_db.py usa LIKE (SQLite).
        # Esto puede divergir en acentos. El insumo_search usa nombre_norm para unificar; APU
        # seguirá LIKE/ILIKE hasta añadir apus.nombre_norm (mejora futura).
        where, params = [], []
        if q:
            where.append("(nombre ILIKE %s OR codigo ILIKE %s)")
            like = f"%{q.strip()}%"
            params += [like, like]
        if grupo:
            where.append("grupo = %s")
            params.append(grupo)
        if shift:
            where.append("shift = %s")
            params.append(shift)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.cx.connection() as conn:
            total = conn.execute(
                f"SELECT COUNT(*) AS n FROM apus.apus{wsql}", params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT codigo, nombre, unidad, shift, grupo FROM apus.apus{wsql} "
                f"ORDER BY codigo, shift LIMIT %s OFFSET %s",
                params + [int(limit), int(offset)]).fetchall()
        return ([Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"])
                 for r in rows], int(total))

    def search_apus(self, texto: str, limit: int = 20) -> list[Apu]:
        like = f"%{texto.strip()}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM apus.apus WHERE nombre ILIKE %s OR codigo ILIKE %s LIMIT %s",
                (like, like, limit)).fetchall()
        return [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) for r in rows]

    def get_apu(self, codigo: str, shift: str) -> Optional[Apu]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM apus.apus WHERE codigo=%s AND shift=%s",
                             (str(codigo), shift)).fetchone()
        return Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"]) if r else None

    def _fila_a_componente(self, r) -> ApuComponent:
        return ApuComponent(
            apu_codigo=r["apu_codigo"], shift=r["shift"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"], unidad=r["unidad"],
            rendimiento=r["rendimiento"] or 0.0,
            precio_unitario_hist=r["precio_unitario_hist"] or 0.0,
            tipo=(r["tipo"] or "insumo"), ref_shift=(r["ref_shift"] or ""))

    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s ORDER BY seq",
                (str(apu_codigo), shift)).fetchall()
        return [self._fila_a_componente(r) for r in rows]

    def get_components_bulk(self, claves) -> dict:
        codes = list({str(c) for c, _s in claves if c})
        out: dict[tuple, list[ApuComponent]] = {}
        if not codes:
            return out
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM apus.apu_componentes WHERE apu_codigo = ANY(%s) "
                "ORDER BY apu_codigo, shift, seq", (codes,)).fetchall()
        for r in rows:
            out.setdefault((r["apu_codigo"], r["shift"]), []).append(self._fila_a_componente(r))
        return out

    def get_depriced_apu(self, codigo: str, shift: str) -> Optional[DePricedApu]:
        apu = self.get_apu(codigo, shift)
        if apu is None:
            return None
        comps = self.get_components(codigo, shift)
        return DePricedApu(
            codigo=apu.codigo, nombre=apu.nombre, unidad=apu.unidad,
            shift=apu.shift, grupo=apu.grupo,
            componentes=tuple(
                DePricedComponent(c.insumo_codigo, c.insumo_nombre, c.unidad,
                                  c.rendimiento, c.tipo)
                for c in comps))

    def componentes_para_integridad(self) -> list[tuple[str, str]]:
        """(insumo_codigo, insumo_nombre) de cada componente con código no vacío.
        Para el chequeo de integridad APU→insumo, sin SQL crudo en el dominio."""
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT insumo_codigo, insumo_nombre FROM apus.apu_componentes "
                "WHERE insumo_codigo IS NOT NULL AND insumo_codigo <> ''").fetchall()
        return [(r["insumo_codigo"], r["insumo_nombre"]) for r in rows]

    def component_counts(self) -> dict[tuple[str, str], int]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, COUNT(*) AS n FROM apus.apu_componentes "
                "GROUP BY apu_codigo, shift").fetchall()
        return {(r["apu_codigo"], r["shift"]): r["n"] for r in rows}

    def componentes_subapu_candidatos(self) -> list[dict]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, seq, insumo_codigo, insumo_nombre FROM apus.apu_componentes "
                "WHERE tipo = 'insumo' AND insumo_codigo IN (SELECT codigo FROM apus.apus)"
            ).fetchall()
        return [{"apu_codigo": r["apu_codigo"], "shift": r["shift"], "seq": r["seq"],
                 "insumo_codigo": r["insumo_codigo"], "insumo_nombre": r["insumo_nombre"]} for r in rows]

    def set_componente_subapu(self, apu_codigo: str, shift: str, seq: int,
                              ref_shift: str, conn=None) -> None:
        sql = ("UPDATE apus.apu_componentes SET tipo='apu', ref_shift=%s "
               "WHERE apu_codigo=%s AND shift=%s AND seq=%s")
        args = (ref_shift, str(apu_codigo), shift, int(seq))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.cx.connection() as c:
            c.execute(sql, args)

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM apus.{t}").fetchone()["n"]
                    for t in ("apus", "apu_componentes")}

    def get_meta(self) -> dict[str, str]:
        with self.cx.connection() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM apus.meta").fetchall()}

    def descripcion(self) -> str:
        return "Postgres (schema apus)"
