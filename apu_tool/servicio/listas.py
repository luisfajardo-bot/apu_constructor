"""
Lógica de servicio para las listas de precios (tarifas).

Una lista = una tarifa: la del catálogo ('Principal', id 1) o la de una obra de No
Previstos. NO ve dinero por sí misma (solo nombres e ids) y nunca toca la IA.

NO hay borrado: una corrida guarda su `lista_precios_id` sin FK (vive en otra base),
así que borrar una lista dejaría corridas huérfanas de su tarifa. Un nombre mal escrito
se corrige renombrando.
"""
from __future__ import annotations

from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.auditoria import registrar_auditoria


def _out(lista) -> dict:
    return {"id": lista.id, "nombre": lista.nombre, "creada_en": lista.creada_en}


def _es_duplicado(e: Exception) -> bool:
    """True si la excepción es la UNIQUE de nombre disparándose en la propia base.

    La detección de duplicados de la capa de datos es un SELECT + comparación en
    Python (con `nucleo/texto.py::normalizar`, insensible a tildes/mayúsculas), no
    una constraint SQL — es TOCTOU: con varios workers de gunicorn, dos POST/PATCH
    simultáneos con el mismo nombre pueden pasar ambos ese chequeo, y solo el
    segundo INSERT/UPDATE choca contra la `UNIQUE(nombre)` de la tabla, que es la
    última red pero es byte-exacta (no pliega tildes/mayúsculas). Mismo criterio
    que `apu_tool.servicio.carpetas._es_duplicado`: SQLite dice "UNIQUE constraint
    failed…"; Postgres (psycopg) "duplicate key value violates unique constraint…".
    """
    return "unique" in str(e).lower()


def listar(alm: Almacen) -> list[dict]:
    return [_out(l) for l in alm.precios.listar_listas()]


def crear(alm: Almacen, nombre: str, actor=None) -> dict:
    """Crea una lista. ValueError (-> 400) si el nombre está vacío, ya existe, o
    choca por la carrera TOCTOU descrita en `_es_duplicado`."""
    try:
        with alm.transaccion("precios") as conn:
            lid = alm.precios.crear_lista(
                nombre, creado_por=(actor.user_id if actor else None), conn=conn)
            registrar_auditoria(
                alm, conn, actor, "lista.crear", "lista", lid, antes=None,
                despues={"id": lid, "nombre": (nombre or "").strip()})
    except Exception as e:
        if _es_duplicado(e):
            raise ValueError(
                f"Ya existe una lista de precios llamada «{(nombre or '').strip()}».") from e
        raise
    return _out(alm.precios.get_lista(lid))


def renombrar(alm: Almacen, lista_id: int, nombre: str, actor=None) -> dict:
    """Renombra una lista. ValueError (-> 400) si no existe, si el nombre choca
    (incluida la carrera TOCTOU de `_es_duplicado`), o si es la Principal (ancla
    del invariante lista_id=None == Principal)."""
    previa = alm.precios.get_lista(lista_id)
    if previa is None:
        raise ValueError(f"No existe la lista de precios id={lista_id}.")
    try:
        with alm.transaccion("precios") as conn:
            alm.precios.renombrar_lista(lista_id, nombre, conn=conn)
            registrar_auditoria(
                alm, conn, actor, "lista.renombrar", "lista", lista_id,
                antes={"nombre": previa.nombre},
                despues={"nombre": (nombre or "").strip()})
    except Exception as e:
        if _es_duplicado(e):
            raise ValueError(
                f"Ya existe una lista de precios llamada «{(nombre or '').strip()}».") from e
        raise
    return _out(alm.precios.get_lista(lista_id))
