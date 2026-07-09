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
