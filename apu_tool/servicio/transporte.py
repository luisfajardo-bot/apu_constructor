"""
Servicio de distancias de acarreo por proyecto y de clasificación de la biblioteca.

Ve dinero solo en el valor del peaje (es para el equipo); nunca abre un camino
hacia la IA. Roles: leer = consulta+, escribir = editor+ (los aplica rutas.py).
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import transporte as regla
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.nucleo.models import ClaseTransporte, ParametrosProyecto
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria

MSG_PEAJE = ("El valor del peaje debe ser mayor que 0 cuando el proyecto tiene "
             "peaje. Un $0 está prohibido: si no hay peaje, marca «no hay».")


def _params_out(p: Optional[ParametrosProyecto], carpeta_id: int) -> dict:
    p = p or ParametrosProyecto(carpeta_id=carpeta_id)
    return {"carpeta_id": carpeta_id, "km_botadero": p.km_botadero,
            "km_mezclas": p.km_mezclas, "km_granulares": p.km_granulares,
            "peaje_aplica": p.peaje_aplica, "peaje_valor": p.peaje_valor,
            "actualizado_en": p.actualizado_en, "actualizado_por": p.actualizado_por}


def _raiz_o_error(alm: Almacen, carpeta_id: int) -> int:
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        raise ValueError("La carpeta no existe.")
    if c.parent_id is not None:
        raise ValueError("Las distancias son del proyecto: se definen en la carpeta "
                         "de nivel 1, no en una subcarpeta.")
    return c.id


def ver(alm: Almacen, carpeta_id: int) -> dict:
    """Parámetros del proyecto + tabla de impacto + cuántos componentes faltan clasificar."""
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        raise ValueError("La carpeta no existe.")
    params = alm.carpetas.get_parametros(raiz)
    impacto = _impacto(alm, raiz)
    return {"parametros": _params_out(params, raiz),
            "impacto": impacto,
            "sin_clasificar": sum(1 for f in impacto if f["sin_clasificar"])}


def guardar(alm: Almacen, carpeta_id: int, datos: dict, actor=None) -> dict:
    """Guarda los parámetros del proyecto. ValueError (-> 400) si algo no cuadra."""
    raiz = _raiz_o_error(alm, carpeta_id)
    kms = {}
    for campo in ("km_botadero", "km_mezclas", "km_granulares"):
        v = datos.get(campo)
        # Un 0 NO es una distancia válida: reescalaría el acarreo a rendimiento 0 y
        # dejaría el ítem en $0. Regla de negocio: nada en $0. Para "no aplica" se
        # deja el campo en null, que es lo que la regla trata como sin definir.
        if v is not None and float(v) <= 0:
            raise ValueError(f"{campo} debe ser mayor que 0; deja el campo vacío "
                             f"si esa distancia no aplica al proyecto.")
        kms[campo] = None if v is None else float(v)
    aplica = datos.get("peaje_aplica")
    valor = datos.get("peaje_valor")
    if aplica is True and not (valor and float(valor) > 0):
        raise ValueError(MSG_PEAJE)
    previos = alm.carpetas.get_parametros(raiz)
    nuevos = ParametrosProyecto(
        carpeta_id=raiz, peaje_aplica=None if aplica is None else bool(aplica),
        peaje_valor=None if valor is None else float(valor), **kms)
    with alm.transaccion("corridas") as conn:
        alm.carpetas.set_parametros(
            nuevos, conn=conn,
            actualizado_por=(getattr(actor, "email", None) if actor else None))
        registrar_auditoria(
            alm, conn, actor, "proyecto.transporte", "carpeta", raiz,
            antes=_params_out(previos, raiz) if previos else None,
            despues=_params_out(nuevos, raiz))
    return ver(alm, raiz)


def _claves_del_proyecto(alm: Almacen, raiz: int) -> list[tuple[str, str]]:
    """(apu, turno) asignados en las corridas del proyecto (raíz + subcarpetas)."""
    hijas = {c.id for c in alm.carpetas.listar() if c.parent_id == raiz}
    propias = hijas | {raiz}
    claves = set()
    for meta in alm.corridas.listar_corridas():
        if meta.carpeta_id in propias:
            for row in alm.corridas.get_items(meta.id):
                if row.apu_codigo:
                    claves.add((row.apu_codigo, row.shift))
    return sorted(claves)


def _impacto(alm: Almacen, raiz: int) -> list[dict]:
    """Previsualización en seco: qué rendimiento tendría cada componente de acarreo.

    Recorre los APUs asignados en el proyecto MÁS el cierre de sus sub-APUs — es
    justo lo que hace `PricingEngine.precargar`, así que se reusa el motor en vez
    de duplicar la BFS. No escribe nada."""
    ctx = regla.cargar_contexto(alm, raiz)
    claves = _claves_del_proyecto(alm, raiz)
    if not claves:
        return []
    motor = PricingEngine(alm, contexto=ctx)
    motor.precargar(claves)
    claves_cargadas = motor.claves_cargadas()                    # incluye sub-APUs
    # UNA sola consulta en lote (en vez de un get_components por clave dentro del
    # bucle): el repo ya la expone y PricingEngine._precargar_lote la usa igual.
    crudos_por_clave = alm.apus.get_components_bulk(claves_cargadas)
    filas = []
    for apu_codigo, shift in claves_cargadas:
        crudos = crudos_por_clave.get((apu_codigo, shift), [])
        if not crudos:            # nada en la biblioteca: no hay nada que mostrar
            continue
        efectivos = {(c.insumo_codigo, normalizar(c.insumo_nombre)): c
                     for c in motor.components(apu_codigo, shift)}
        pend = set(motor.sin_distancia(apu_codigo, shift))
        for c in crudos:
            if normalizar(c.unidad) != normalizar(config.UNIDAD_TRANSPORTE) \
                    and not regla.es_peaje(c):
                continue
            ef = efectivos.get((c.insumo_codigo, normalizar(c.insumo_nombre)))
            cls = ctx.clasificacion.get((apu_codigo, shift, c.insumo_codigo))
            quitado = ef is None
            filas.append({
                "apu_codigo": apu_codigo, "shift": shift,
                "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
                "unidad": c.unidad, "rendimiento_actual": c.rendimiento,
                "categoria": cls.categoria if cls else None,
                "volumen": cls.volumen if cls else None,
                "rendimiento_nuevo": ef.rendimiento if ef is not None else None,
                "quitado": quitado,
                # Un quitado (p.ej. el peaje excluido porque el proyecto no lo
                # tiene) también es una desviación del proyecto: "biblioteca"
                # sugeriría que no cambió nada, y sí cambió.
                "origen": ("distancia" if quitado or (ef is not None
                           and ef.rendimiento != c.rendimiento) else "biblioteca"),
                "sin_clasificar": c.insumo_codigo in pend,
            })
    return filas


# ---- clasificación de la biblioteca (una vez, no por proyecto) ----
def _sugerir(apu_nombre: str, insumo_nombre: str) -> Optional[str]:
    apu_n, ins_n = normalizar(apu_nombre), normalizar(insumo_nombre)
    for ambito, fragmentos, categoria in config.TRANSPORTE_SUGERENCIAS:
        texto = apu_n if ambito == "apu_nombre" else ins_n
        if any(normalizar(f) in texto for f in fragmentos):
            return categoria
    return None


def listar_componentes(alm: Almacen) -> dict:
    """Las filas de acarreo de la biblioteca, con su clasificación o la sugerida."""
    guardadas = {(c.apu_codigo, c.shift, c.insumo_codigo): c
                 for c in alm.apus.get_clasificacion_transporte()}
    items = []
    for cand in alm.apus.componentes_transporte_candidatos():
        clave = (cand["apu_codigo"], cand["shift"], cand["insumo_codigo"])
        cls = guardadas.get(clave)
        if cls is not None and normalizar(cls.insumo_nombre) != normalizar(
                cand["insumo_nombre"]):
            cls = None                     # misma clave, otro insumo: no vale
        km_base = (cls.km_base if cls and cls.km_base else config.KM_BASE_DEFECTO)
        rend = float(cand["rendimiento"] or 0.0)
        volumen = cls.volumen if cls else (rend / km_base if km_base else 0.0)
        items.append({
            "apu_codigo": cand["apu_codigo"], "shift": cand["shift"],
            "apu_nombre": cand["apu_nombre"] or "",
            "insumo_codigo": cand["insumo_codigo"],
            "insumo_nombre": cand["insumo_nombre"], "unidad": cand["unidad"],
            "rendimiento": rend,
            "categoria": cls.categoria if cls else None,
            "categoria_sugerida": _sugerir(cand["apu_nombre"] or "",
                                           cand["insumo_nombre"]),
            "volumen": volumen, "km_base": km_base,
            # km que la fila representa hoy con el volumen mostrado: delata las
            # filas cuya distancia no cuadra con la que declara su nombre.
            "km_implicito": round(rend / volumen, 2) if volumen else None,
        })
    return {"items": items, "total": len(items),
            "categorias": list(config.TRANSPORTE_CATEGORIAS),
            "km_base_defecto": config.KM_BASE_DEFECTO}


def clasificar(alm: Almacen, filas: list[dict], actor=None) -> dict:
    """Guarda categoría + volumen de N componentes. Es la acción en bloque."""
    validas: list[ClaseTransporte] = []
    for f in filas:
        categoria = str(f.get("categoria") or "")
        if categoria not in config.TRANSPORTE_CATEGORIAS:
            raise ValueError(f"Categoría inválida: «{categoria}». "
                             f"Válidas: {', '.join(config.TRANSPORTE_CATEGORIAS)}.")
        volumen = float(f.get("volumen") or 0.0)
        if volumen <= 0:
            raise ValueError("El volumen debe ser mayor que 0.")
        validas.append(ClaseTransporte(
            apu_codigo=str(f["apu_codigo"]), shift=str(f["shift"]),
            insumo_codigo=str(f["insumo_codigo"]),
            insumo_nombre=str(f.get("insumo_nombre") or ""),
            categoria=categoria, volumen=volumen,
            km_base=(float(f["km_base"]) if f.get("km_base") else None)))
    email = getattr(actor, "email", None) if actor else None
    with alm.transaccion("apus") as conn:
        alm.apus.set_clasificacion_transporte(validas, conn=conn, actualizado_por=email)
        registrar_auditoria(
            alm, conn, actor, "transporte.clasificar", "apu",
            f"{len(validas)} componentes", antes=None,
            despues={"filas": [{"apu": c.apu_codigo, "shift": c.shift,
                                "insumo": c.insumo_codigo, "categoria": c.categoria,
                                "volumen": c.volumen} for c in validas]})
    return {"aplicados": len(validas)}
