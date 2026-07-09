"""Pool de conexiones Postgres (Supabase) para el backend de nube.

Una instancia de Conexion envuelve un ConnectionPool de psycopg. Los repos
Postgres (PreciosPg, ApusPg, CorridasPg) comparten UNA Conexion (un pool).

Notas Supabase: se usa el pooler en modo transacción (Supavisor), por lo que
se desactivan los prepared statements server-side (prepare_threshold=None).
"""
from __future__ import annotations

import re
import time
from contextlib import contextmanager
from typing import Callable, Iterator

import psycopg
from psycopg.rows import dict_row
from psycopg_pool import ConnectionPool

# Errores transitorios de una migración: espera de lock (lock_timeout, 55P03),
# cancelación por statement_timeout (57014) o deadlock. Se reintentan.
_ERRORES_MIGRACION = (
    psycopg.errors.LockNotAvailable,
    psycopg.errors.QueryCanceled,
    psycopg.errors.DeadlockDetected,
)


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

    def ejecutar_migracion(self, sql: str, **kwargs) -> None:
        """Aplica un script DDL idempotente de forma resiliente en el arranque.

        Ver aplicar_migracion(): acota lock_timeout y reintenta ante esperas de
        lock, para no colgarse hasta statement_timeout durante un deploy con
        solape (instancia vieja aún sirviendo) o una carrera entre workers."""
        aplicar_migracion(self._pool.connection, sql, **kwargs)

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


def aplicar_migracion(abrir_conexion: Callable, sql: str, *, intentos: int = 6,
                      espera_s: float = 4.0, lock_timeout_ms: int = 4000,
                      dormir: Callable[[float], None] = time.sleep) -> None:
    """Aplica un script DDL idempotente acotando el lock y reintentando.

    Problema: en un deploy con solape (la instancia vieja sigue sirviendo
    tráfico) o con varios workers arrancando a la vez, un ``ALTER TABLE`` sobre
    una tabla caliente puede quedar esperando ``ACCESS EXCLUSIVE`` hasta el
    ``statement_timeout`` (~2 min) y morir; peor aún, si el worker se reinicia a
    mitad, deja un lock huérfano que bloquea a los siguientes.

    Solución: ``SET LOCAL lock_timeout`` hace que una sentencia bloqueada falle
    rápido (55P03) y la transacción se revierte (sin lock huérfano); reintentamos
    hasta que el lock quede libre (la instancia vieja drena / el otro worker
    termina). Cada intento usa una conexión fresca. Idempotente: los reintentos
    son seguros porque el script usa ``IF NOT EXISTS`` / ``WHERE NOT EXISTS``.

    ``abrir_conexion`` es un callable que devuelve un context manager de conexión
    (p.ej. ``pool.connection``); inyectable para pruebas sin un Postgres real.
    """
    ultimo: Exception | None = None
    for intento in range(max(1, intentos)):
        try:
            with abrir_conexion() as conn:
                conn.execute(f"SET LOCAL lock_timeout = '{int(lock_timeout_ms)}ms'")
                ejecutar_script(conn, sql)
            return
        except _ERRORES_MIGRACION as e:
            ultimo = e
            if intento < intentos - 1:
                dormir(espera_s)
    assert ultimo is not None
    raise ultimo
