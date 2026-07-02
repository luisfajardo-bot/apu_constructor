"""Pool de conexiones Postgres (Supabase) para el backend de nube.

Una instancia de Conexion envuelve un ConnectionPool de psycopg. Los repos
Postgres (PreciosPg, ApusPg, CorridasPg) comparten UNA Conexion (un pool).

Notas Supabase: se usa el pooler en modo transacción (Supavisor), por lo que
se desactivan los prepared statements server-side (prepare_threshold=None).
"""
from __future__ import annotations

import re
from contextlib import contextmanager
from typing import Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool


class Conexion:
    def __init__(self, dsn: str, min_size: int = 1, max_size: int = 10):
        self._pool = ConnectionPool(
            conninfo=dsn,
            min_size=min_size,
            max_size=max_size,
            open=True,
            kwargs={"row_factory": dict_row, "prepare_threshold": None},
        )

    @contextmanager
    def connection(self) -> Iterator[psycopg.Connection]:
        """Conexión por operación: commit al salir OK, rollback si excepción."""
        with self._pool.connection() as conn:
            yield conn  # psycopg_pool ya hace commit/rollback y devuelve al pool

    @contextmanager
    def transaccion(self) -> Iterator[psycopg.Connection]:
        """Unidad de trabajo (mismo comportamiento). Seam para auditoría (Plan 3)."""
        with self._pool.connection() as conn:
            yield conn

    def cerrar(self) -> None:
        self._pool.close()


def dividir_sentencias(sql: str) -> list[str]:
    """Parte un script DDL en sentencias individuales por ';'.

    ANTES de partir, elimina los comentarios de línea ('-- ...') para que un
    ';' dentro de un comentario NO corte una sentencia por la mitad (esto
    rompió el esquema Postgres una vez: un ';' en un comentario dejaba el
    CREATE TABLE sin cerrar). Asume que el DDL no contiene ';' ni '--' dentro
    de literales/identificadores (cierto para nuestros db/pg/*.sql).

    Función pura y sin efectos: testeable localmente sin un Postgres real.
    """
    sin_comentarios = re.sub(r"--[^\n]*", "", sql)
    return [s for s in (frag.strip() for frag in sin_comentarios.split(";")) if s]


def ejecutar_script(conn, sql: str) -> None:
    """Ejecuta un script DDL multi-sentencia en Postgres.

    psycopg3 usa el protocolo extendido en execute(), que rechaza múltiples
    sentencias en un solo comando ('cannot insert multiple commands into a
    prepared statement'). Partimos el script con dividir_sentencias() y
    ejecutamos cada sentencia en la misma transacción.
    """
    for sentencia in dividir_sentencias(sql):
        conn.execute(sentencia)
