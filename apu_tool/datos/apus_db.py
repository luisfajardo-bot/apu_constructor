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
            cols = {r["name"] for r in
                    conn.execute("PRAGMA table_info(apu_componentes)").fetchall()}
            if "tipo" not in cols:
                conn.execute("ALTER TABLE apu_componentes "
                             "ADD COLUMN tipo TEXT NOT NULL DEFAULT 'insumo'")
            if "ref_shift" not in cols:
                conn.execute("ALTER TABLE apu_componentes ADD COLUMN ref_shift TEXT")

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
                             c.precio_unitario_hist, c.tipo, c.ref_shift))
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)
        return len(rows)

    def crear_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        """Crea un APU NUEVO con su composición, atómico. Identidad (código, turno):
        si ya existe → ValueError."""
        if not str(apu.codigo or "").strip() or not str(apu.nombre or "").strip():
            raise ValueError("El APU necesita código y nombre.")
        if conn is not None:
            return self._crear_apu(conn, apu, componentes)
        with self.connect() as c:
            return self._crear_apu(c, apu, componentes)

    def _crear_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus WHERE codigo=? AND shift=?",
                              (str(apu.codigo), apu.shift)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "INSERT INTO apus (codigo, shift, nombre, unidad, grupo) VALUES (?,?,?,?,?)",
            (str(apu.codigo), apu.shift, apu.nombre, apu.unidad, apu.grupo))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist, c.tipo, c.ref_shift)
                for seq, c in enumerate(componentes)]
        if rows:
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    def editar_apu(self, apu: Apu, componentes: list[ApuComponent], conn=None) -> None:
        """Edita cabecera + reemplaza composición de un APU existente. ValueError si no existe."""
        if conn is not None:
            return self._editar_apu(conn, apu, componentes)
        with self.connect() as c:
            return self._editar_apu(c, apu, componentes)

    def _editar_apu(self, conn, apu: Apu, componentes: list[ApuComponent]) -> None:
        existe = conn.execute("SELECT 1 FROM apus WHERE codigo=? AND shift=?",
                              (str(apu.codigo), apu.shift)).fetchone()
        if not existe:
            raise ValueError(
                f"No existe un APU con código {apu.codigo} en turno {apu.shift}.")
        conn.execute(
            "UPDATE apus SET nombre=?, unidad=?, grupo=? WHERE codigo=? AND shift=?",
            (apu.nombre, apu.unidad, apu.grupo, str(apu.codigo), apu.shift))
        conn.execute("DELETE FROM apu_componentes WHERE apu_codigo=? AND shift=?",
                     (str(apu.codigo), apu.shift))
        rows = [(str(apu.codigo), apu.shift, seq, c.insumo_codigo, c.insumo_nombre,
                 c.unidad, c.rendimiento, c.precio_unitario_hist, c.tipo, c.ref_shift)
                for seq, c in enumerate(componentes)]
        if rows:
            conn.executemany(
                "INSERT INTO apu_componentes "
                "(apu_codigo, shift, seq, insumo_codigo, insumo_nombre, unidad, "
                " rendimiento, precio_unitario_hist, tipo, ref_shift) "
                "VALUES (?,?,?,?,?,?,?,?,?,?)", rows)

    def borrar_apu(self, codigo: str, shift: str, conn=None) -> bool:
        """Borra componentes + cabecera de un APU. False si no existía."""
        if conn is not None:
            return self._borrar_apu(conn, codigo, shift)
        with self.connect() as c:
            return self._borrar_apu(c, codigo, shift)

    def _borrar_apu(self, conn, codigo: str, shift: str) -> bool:
        existe = conn.execute("SELECT 1 FROM apus WHERE codigo=? AND shift=?",
                              (str(codigo), shift)).fetchone()
        if not existe:
            return False
        conn.execute("DELETE FROM apu_componentes WHERE apu_codigo=? AND shift=?",
                     (str(codigo), shift))
        conn.execute("DELETE FROM apus WHERE codigo=? AND shift=?", (str(codigo), shift))
        return True

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

    def list_apus(self, q: Optional[str] = None, grupo: Optional[str] = None,
                  shift: Optional[str] = None, limit: int = 100,
                  offset: int = 0) -> tuple[list[Apu], int]:
        # NOTA: la búsqueda por nombre aquí usa LIKE (SQLite); en apus_pg.py usa ILIKE (Postgres).
        # Esto puede divergir en acentos. El insumo_search usa nombre_norm para unificar; APU
        # seguirá LIKE/ILIKE hasta añadir apus.nombre_norm (mejora futura).
        where, params = [], []
        if q:
            where.append("(nombre LIKE ? OR codigo LIKE ?)")
            like = f"%{q.strip()}%"
            params += [like, like]
        if grupo:
            where.append("grupo = ?")
            params.append(grupo)
        if shift:
            where.append("shift = ?")
            params.append(shift)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM apus{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT codigo, nombre, unidad, shift, grupo FROM apus{wsql} "
                f"ORDER BY codigo, shift LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return ([Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"])
                 for r in rows], int(total))

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
            precio_unitario_hist=r["precio_unitario_hist"] or 0.0,
            tipo=(r["tipo"] or "insumo"), ref_shift=(r["ref_shift"] or "")) for r in rows]

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
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT insumo_codigo, insumo_nombre FROM apu_componentes "
                "WHERE insumo_codigo IS NOT NULL AND insumo_codigo <> ''").fetchall()
        return [(r["insumo_codigo"], r["insumo_nombre"]) for r in rows]

    def component_counts(self) -> dict[tuple[str, str], int]:
        """nº de componentes por APU, en una sola consulta (para la lista de APUs)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, COUNT(*) n FROM apu_componentes "
                "GROUP BY apu_codigo, shift").fetchall()
        return {(r["apu_codigo"], r["shift"]): r["n"] for r in rows}

    def componentes_subapu_candidatos(self) -> list[dict]:
        """Componentes tipo='insumo' cuyo código es un APU (candidatos a sub-APU)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, seq, insumo_codigo, insumo_nombre FROM apu_componentes "
                "WHERE tipo = 'insumo' AND insumo_codigo IN (SELECT codigo FROM apus)"
            ).fetchall()
        return [{"apu_codigo": r["apu_codigo"], "shift": r["shift"], "seq": r["seq"],
                 "insumo_codigo": r["insumo_codigo"], "insumo_nombre": r["insumo_nombre"]} for r in rows]

    def set_componente_subapu(self, apu_codigo: str, shift: str, seq: int,
                              ref_shift: str, conn=None) -> None:
        sql = ("UPDATE apu_componentes SET tipo='apu', ref_shift=? "
               "WHERE apu_codigo=? AND shift=? AND seq=?")
        args = (ref_shift, str(apu_codigo), shift, int(seq))
        if conn is not None:
            conn.execute(sql, args)
            return
        with self.connect() as c:
            c.execute(sql, args)

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("apus", "apu_componentes")}

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}

    def descripcion(self) -> str:
        return f"SQLite: {self.path}"
