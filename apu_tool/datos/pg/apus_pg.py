"""Backend Postgres de APUs. Implementa RepositorioApus. Port 1:1 de apus_db.py."""
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
        with self.cx.connection() as conn:
            conn.executemany(
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
                             c.precio_unitario_hist))
            conn.executemany(
                "INSERT INTO apus.apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)
        return len(rows)

    def crear_apu(self, apu: Apu, componentes: list[ApuComponent]) -> None:
        if not str(apu.codigo or "").strip() or not str(apu.nombre or "").strip():
            raise ValueError("El APU necesita código y nombre.")
        with self.cx.connection() as conn:
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
                     c.unidad, c.rendimiento, c.precio_unitario_hist)
                    for seq, c in enumerate(componentes)]
            if rows:
                conn.executemany(
                    "INSERT INTO apus.apu_componentes "
                    "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                    " rendimiento, precio_unitario_hist) VALUES (%s,%s,%s,%s,%s,%s,%s,%s)", rows)

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

    def get_components(self, apu_codigo: str, shift: str) -> list[ApuComponent]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM apus.apu_componentes WHERE apu_codigo=%s AND shift=%s ORDER BY seq",
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

    def component_counts(self) -> dict[tuple[str, str], int]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, COUNT(*) AS n FROM apus.apu_componentes "
                "GROUP BY apu_codigo, shift").fetchall()
        return {(r["apu_codigo"], r["shift"]): r["n"] for r in rows}

    def counts(self) -> dict[str, int]:
        with self.cx.connection() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) AS n FROM apus.{t}").fetchone()["n"]
                    for t in ("apus", "apu_componentes")}

    def get_meta(self) -> dict[str, str]:
        with self.cx.connection() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM apus.meta").fetchall()}
