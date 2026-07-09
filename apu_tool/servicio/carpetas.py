"""Servicio de carpetas: reglas de negocio (profundidad máx. 2, unicidad de
hermanas, borrado bloqueado si no vacía) + auditoría. No ve dinero ni la IA.

Roles (los aplica la API en rutas.py): crear = consulta+; renombrar/mover/borrar
y mover corridas = editor+.
"""
from __future__ import annotations

import sqlite3
from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Carpeta
from apu_tool.servicio.auditoria import registrar_auditoria


class CarpetaInvalida(Exception):
    """Nombre vacío, duplicado entre hermanas, padre inexistente o profundidad > 2."""


class CarpetaNoVacia(Exception):
    """Se intentó borrar una carpeta con subcarpetas o corridas dentro."""
    def __init__(self, carpeta_id: int):
        super().__init__(f"La carpeta {carpeta_id} no está vacía.")
        self.carpeta_id = carpeta_id


def _dto(c: Carpeta) -> dict:
    return {"id": c.id, "nombre": c.nombre, "parent_id": c.parent_id,
            "creada_en": c.creada_en}


def _es_duplicado(e: Exception) -> bool:
    """True si la excepción de integridad es por el índice de hermanas."""
    return isinstance(e, sqlite3.IntegrityError) or "ux_carpeta_hermanas" in str(e) \
        or "unique" in str(e).lower()


def crear_carpeta(alm: Almacen, nombre: str, parent_id: Optional[int],
                  actor=None) -> dict:
    nombre = (nombre or "").strip()
    if not nombre:
        raise CarpetaInvalida("El nombre de la carpeta no puede estar vacío.")
    if parent_id is not None:
        padre = alm.carpetas.get(parent_id)
        if padre is None:
            raise CarpetaInvalida("La carpeta padre no existe.")
        if padre.parent_id is not None:
            raise CarpetaInvalida("No se permiten más de 2 niveles de carpetas.")
    try:
        with alm.transaccion("corridas") as conn:
            new_id = alm.carpetas.crear(nombre, parent_id, creado_por=_email(actor), conn=conn)
            registrar_auditoria(alm, conn, actor, "carpeta.crear", "carpeta", new_id,
                                antes=None, despues={"nombre": nombre, "parent_id": parent_id})
    except Exception as e:
        if _es_duplicado(e):
            raise CarpetaInvalida("Ya existe una carpeta con ese nombre en el mismo nivel.") from e
        raise
    return _dto(alm.carpetas.get(new_id))


def listar_arbol(alm: Almacen) -> list[dict]:
    """Árbol de 2 niveles con conteo de corridas por carpeta."""
    todas = alm.carpetas.listar()
    por_padre: dict[Optional[int], list[Carpeta]] = {}
    for c in todas:
        por_padre.setdefault(c.parent_id, []).append(c)

    def nodo(c: Carpeta) -> dict:
        hijas = [nodo(h) for h in por_padre.get(c.id, [])]
        return {"id": c.id, "nombre": c.nombre, "parent_id": c.parent_id,
                "n_corridas": alm.carpetas.contar_corridas(c.id), "hijas": hijas}

    return [nodo(c) for c in por_padre.get(None, [])]


def _email(actor) -> Optional[str]:
    return getattr(actor, "email", None) if actor is not None else None


def renombrar_carpeta(alm: Almacen, carpeta_id: int, nombre: str, actor=None) -> dict:
    nombre = (nombre or "").strip()
    if not nombre:
        raise CarpetaInvalida("El nombre de la carpeta no puede estar vacío.")
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        raise CarpetaInvalida("La carpeta no existe.")
    try:
        with alm.transaccion("corridas") as conn:
            alm.carpetas.renombrar(carpeta_id, nombre, conn=conn)
            registrar_auditoria(alm, conn, actor, "carpeta.renombrar", "carpeta", carpeta_id,
                                antes={"nombre": c.nombre}, despues={"nombre": nombre})
    except Exception as e:
        if _es_duplicado(e):
            raise CarpetaInvalida("Ya existe una carpeta con ese nombre en el mismo nivel.") from e
        raise
    return _dto(alm.carpetas.get(carpeta_id))


def mover_carpeta(alm: Almacen, carpeta_id: int, nuevo_parent_id: Optional[int],
                  actor=None) -> dict:
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        raise CarpetaInvalida("La carpeta no existe.")
    if nuevo_parent_id is not None:
        if nuevo_parent_id == carpeta_id:
            raise CarpetaInvalida("Una carpeta no puede ser su propio padre.")
        padre = alm.carpetas.get(nuevo_parent_id)
        if padre is None:
            raise CarpetaInvalida("La carpeta padre no existe.")
        if padre.parent_id is not None:
            raise CarpetaInvalida("No se permiten más de 2 niveles de carpetas.")
        if alm.carpetas.contar_hijas(carpeta_id) > 0:
            raise CarpetaInvalida("Una carpeta con subcarpetas no puede volverse subcarpeta.")
    try:
        with alm.transaccion("corridas") as conn:
            alm.carpetas.mover(carpeta_id, nuevo_parent_id, conn=conn)
            registrar_auditoria(alm, conn, actor, "carpeta.mover", "carpeta", carpeta_id,
                                antes={"parent_id": c.parent_id},
                                despues={"parent_id": nuevo_parent_id})
    except Exception as e:
        if _es_duplicado(e):
            raise CarpetaInvalida("Ya existe una carpeta con ese nombre en el destino.") from e
        raise
    return _dto(alm.carpetas.get(carpeta_id))


def eliminar_carpeta(alm: Almacen, carpeta_id: int, actor=None) -> bool:
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        return False
    if alm.carpetas.contar_hijas(carpeta_id) > 0 or alm.carpetas.contar_corridas(carpeta_id) > 0:
        raise CarpetaNoVacia(carpeta_id)
    with alm.transaccion("corridas") as conn:
        ok = alm.carpetas.eliminar(carpeta_id, conn=conn)
        if ok:
            registrar_auditoria(alm, conn, actor, "carpeta.eliminar", "carpeta", carpeta_id,
                                antes={"nombre": c.nombre, "parent_id": c.parent_id},
                                despues=None)
    return ok


def carpeta_sin_clasificar_id(alm: Almacen) -> int:
    """Id de la carpeta raíz 'Sin clasificar' (la crea init_schema; fallback defensivo)."""
    for c in alm.carpetas.listar():
        if c.parent_id is None and c.nombre == "Sin clasificar":
            return c.id
    return alm.carpetas.crear("Sin clasificar", parent_id=None)


def mover_corrida(alm: Almacen, corrida_id: int, carpeta_id: int, actor=None) -> bool:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return False
    if alm.carpetas.get(carpeta_id) is None:
        raise CarpetaInvalida("La carpeta destino no existe.")
    with alm.transaccion("corridas") as conn:
        # set_carpeta abre su propia conexión; para mantener la mutación + auditoría
        # en la misma transacción, hazlo con SQL directo sobre `conn`:
        conn.execute("UPDATE corrida SET carpeta_id=? WHERE id=?", (int(carpeta_id), int(corrida_id)))
        registrar_auditoria(alm, conn, actor, "corrida.mover", "corrida", corrida_id,
                            antes={"carpeta_id": meta.carpeta_id},
                            despues={"carpeta_id": carpeta_id})
    return True
