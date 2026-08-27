"""
Ajustes puntuales de composición por proyecto: las excepciones que decide el
ingeniero (agregar/quitar/reemplazar un insumo, cambiar un rendimiento).

NO ve dinero: solo estructura. El precio por obra es la lista NP y el peaje es un
parámetro del proyecto. Roles: leer = consulta+, escribir = editor+.
"""
from __future__ import annotations

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import transporte as regla
from apu_tool.nucleo.models import AjusteProyecto
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria

ACCIONES = ("rendimiento", "agregar", "quitar", "reemplazar")
_EXIGEN_RENDIMIENTO = ("rendimiento", "agregar")


def _out(a: AjusteProyecto) -> dict:
    return {"id": a.id, "apu_codigo": a.apu_codigo, "shift": a.shift,
            "accion": a.accion, "insumo_codigo": a.insumo_codigo,
            "insumo_nombre": a.insumo_nombre, "unidad": a.unidad,
            "rendimiento": a.rendimiento,
            "insumo_nuevo_codigo": a.insumo_nuevo_codigo,
            "insumo_nuevo_nombre": a.insumo_nuevo_nombre,
            "tipo": a.tipo, "ref_shift": a.ref_shift, "nota": a.nota,
            "creado_en": a.creado_en, "creado_por": a.creado_por}


def _insumo_de_catalogo(alm: Almacen, codigo: str, nombre: str):
    """El insumo del catálogo con ESE código y ESE nombre, o None. La identidad es
    código + nombre: los códigos se repiten en el catálogo con significados
    distintos (`7462` es TRANSPORTE DE PETREOS y también NIPLE 16")."""
    objetivo = normalizar(nombre)
    for i in alm.precios.get_candidatos(codigo):
        if normalizar(i.nombre) == objetivo:
            return i
    return None


def listar(alm: Almacen, carpeta_id: int) -> list[dict]:
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        raise ValueError("La carpeta no existe.")
    return [_out(a) for a in alm.carpetas.listar_ajustes(raiz)]


def crear(alm: Almacen, carpeta_id: int, datos: dict, actor=None) -> dict:
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        raise ValueError("La carpeta no existe.")
    accion = str(datos.get("accion") or "")
    if accion not in ACCIONES:
        raise ValueError(f"Acción inválida: «{accion}». Válidas: {', '.join(ACCIONES)}.")
    rend = datos.get("rendimiento")
    if accion in _EXIGEN_RENDIMIENTO and not (rend and float(rend) > 0):
        raise ValueError("El rendimiento debe ser mayor que 0.")
    codigo = str(datos.get("insumo_codigo") or "")
    nombre = str(datos.get("insumo_nombre") or "")
    unidad = str(datos.get("unidad") or "")
    if accion == "agregar":
        ins = _insumo_de_catalogo(alm, codigo, nombre)
        if ins is None:
            raise ValueError(f"El insumo {codigo} «{nombre}» no está en el catálogo.")
        unidad = unidad or ins.unidad
    nuevo_cod = str(datos.get("insumo_nuevo_codigo") or "")
    nuevo_nom = str(datos.get("insumo_nuevo_nombre") or "")
    if accion == "reemplazar":
        if not nuevo_cod or not nuevo_nom:
            raise ValueError("«reemplazar» exige insumo_nuevo_codigo e insumo_nuevo_nombre.")
        nuevo = _insumo_de_catalogo(alm, nuevo_cod, nuevo_nom)
        if nuevo is None:
            raise ValueError(f"El insumo {nuevo_cod} «{nuevo_nom}» no está en el catálogo.")
        # La unidad viaja SIEMPRE la del insumo nuevo: `transporte._un_ajuste` la usa
        # para no dejar el componente reemplazado con la unidad del viejo (si esa
        # unidad fuera M3-KM, la regla lo trataría como acarreo sin serlo).
        unidad = nuevo.unidad
    ajuste = AjusteProyecto(
        carpeta_id=raiz, apu_codigo=str(datos["apu_codigo"]),
        shift=str(datos["shift"]), accion=accion, insumo_codigo=codigo,
        insumo_nombre=nombre, unidad=unidad,
        rendimiento=None if rend is None else float(rend),
        insumo_nuevo_codigo=nuevo_cod, insumo_nuevo_nombre=nuevo_nom,
        tipo=str(datos.get("tipo") or "insumo"),
        ref_shift=str(datos.get("ref_shift") or ""),
        nota=str(datos.get("nota") or ""))
    email = getattr(actor, "email", None) if actor else None
    with alm.transaccion("corridas") as conn:
        aid = alm.carpetas.crear_ajuste(ajuste, conn=conn, creado_por=email)
        registrar_auditoria(alm, conn, actor, "proyecto.ajuste.crear", "carpeta", raiz,
                            antes=None, despues=_out(ajuste) | {"id": aid})
    return _out(ajuste) | {"id": aid}


def borrar(alm: Almacen, carpeta_id: int, ajuste_id: int, actor=None) -> bool:
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        return False
    previos = {a.id: a for a in alm.carpetas.listar_ajustes(raiz)}
    with alm.transaccion("corridas") as conn:
        ok = alm.carpetas.borrar_ajuste(raiz, ajuste_id, conn=conn)
        if ok:
            registrar_auditoria(
                alm, conn, actor, "proyecto.ajuste.borrar", "carpeta", raiz,
                antes=_out(previos[ajuste_id]) if ajuste_id in previos else None,
                despues=None)
    return ok
