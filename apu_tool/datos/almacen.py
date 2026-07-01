"""Fachada de persistencia. Agrupa los repositorios SQLite/Postgres (precios, apus, corridas, perfiles).

Backend por config: 'sqlite' (local/dev/tests, por defecto) o 'postgres'
(Supabase, cuando hay DATABASE_URL). Los repos Postgres comparten una Conexion.
"""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path

from apu_tool import config
from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.datos.precios_db import PreciosDB


class Almacen:
    def __init__(self, precios_path: Path | str = config.PRECIOS_DB_PATH,
                 apus_path: Path | str = config.APUS_DB_PATH,
                 corridas_path: Path | str = config.CORRIDAS_DB_PATH):
        self._cx = None
        if config.db_backend() == "postgres":
            from apu_tool.datos.pg.conexion import Conexion
            from apu_tool.datos.pg.precios_pg import PreciosPg
            from apu_tool.datos.pg.apus_pg import ApusPg
            from apu_tool.datos.pg.corridas_pg import CorridasPg
            from apu_tool.datos.pg.perfiles_pg import PerfilesPg
            from apu_tool.datos.pg.auditoria_pg import AuditoriaPg
            self._cx = Conexion(config.database_url())
            self.precios = PreciosPg(self._cx)
            self.apus = ApusPg(self._cx)
            self.corridas = CorridasPg(self._cx)
            self.perfiles = PerfilesPg(self._cx)
            self.auditoria = AuditoriaPg(self._cx)
            self._paths = None
            self._seg_path = None
        else:
            from apu_tool.datos.auditoria_db import AuditoriaDB
            from apu_tool.datos.perfiles_db import PerfilesDB
            self._seg_path = (Path(precios_path).parent / "seguridad.db"
                              if isinstance(precios_path, Path) else config.DATA_DIR / "seguridad.db")
            self.precios = PreciosDB(precios_path)
            self.apus = ApusDB(apus_path)
            self.corridas = CorridasDB(corridas_path)
            self.perfiles = PerfilesDB(self._seg_path)
            self.auditoria = AuditoriaDB(self._seg_path)
            self._paths = {"precios": Path(precios_path), "apus": Path(apus_path),
                           "corridas": Path(corridas_path), "seguridad": Path(self._seg_path)}

    def init_schema(self) -> None:
        self.precios.init_schema()
        self.apus.init_schema()
        self.corridas.init_schema()
        self.perfiles.init_schema()

    def reset(self) -> None:
        """Reseteo COMPLETO de todas las áreas (precios, apus, corridas, perfiles); uso explícito."""
        self.precios.reset()
        self.apus.reset()
        self.corridas.reset()
        self.perfiles.reset()

    def reset_catalogo(self) -> None:
        """Resetea solo el catálogo (precios + apus), preservando las corridas."""
        self.precios.reset()
        self.apus.reset()

    @contextmanager
    def transaccion(self, dominio: str):
        """Unidad de trabajo: cede UNA conexión que ve la tabla del `dominio`
        ('precios'|'apus'|'corridas'|'seguridad') y la tabla `auditoria`, para
        escribir mutación + auditoría atómicamente. Commit único al salir OK;
        rollback ante excepción.

        Postgres: conexión del pool (todos los schemas visibles).
        SQLite: conexión sobre el archivo del dominio; si no es 'seguridad', ATTACH
        de seguridad.db (`auditoria` resuelve sin calificar por ser la única base que
        la contiene). NO usar WAL: rompería el commit atómico multi-archivo.
        """
        if self._cx is not None:  # Postgres: el pool hace commit/rollback al salir
            with self._cx.transaccion() as conn:
                yield conn
            return
        conn = sqlite3.connect(self._paths[dominio])
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        if dominio != "seguridad":
            conn.execute("ATTACH DATABASE ? AS seg", (str(self._seg_path),))
        try:
            yield conn
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        finally:
            conn.close()  # SQLite hace DETACH de las bases adjuntas al cerrar

    def counts(self) -> dict[str, int]:
        return {**self.precios.counts(), **self.apus.counts(), **self.corridas.counts()}

    def cerrar(self) -> None:
        """Cierra el pool si es backend Postgres (no-op en SQLite)."""
        if self._cx is not None:
            self._cx.cerrar()
