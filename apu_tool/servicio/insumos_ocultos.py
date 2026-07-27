"""Migración: oculta (no borra) del catálogo de insumos los códigos que son un eco
aplanado de un APU y ya no tienen ningún componente usándolos como insumo real.

Auto-marcado con auditoría; idempotente. NO ve la IA. El costeo (pricing.py) sigue
encontrando cualquier insumo por código exista o no esté oculto — `oculto` solo
filtra las lecturas orientadas a humanos/IA (list_insumos, search_insumos*).
"""
from __future__ import annotations

from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria


def ocultar_apus_duplicados(alm: Almacen, actor: Optional[Perfil] = None) -> dict:
    alm.precios.init_schema()   # idempotente: asegura la columna oculto

    codigos_apu: set[str] = set()
    nombres_por_codigo_apu: dict[str, set] = {}
    for cod, nom, _sh in alm.apus.apu_index():
        codigos_apu.add(cod)
        nombres_por_codigo_apu.setdefault(cod, set()).add(normalizar(nom))

    usos_restantes = {
        (cod, normalizar(nom)) for cod, nom in alm.apus.pares_insumo_en_uso()
    }

    a_ocultar = [
        (iid, cod, nom) for iid, cod, nom in alm.precios.todos_no_ocultos()
        if cod in codigos_apu
        and normalizar(nom) in nombres_por_codigo_apu.get(cod, set())
        and (cod, normalizar(nom)) not in usos_restantes
    ]

    if not a_ocultar:
        return {"insumos_ocultados": 0}

    with alm.transaccion("precios") as conn:
        for iid, cod, nom in a_ocultar:
            alm.precios.set_oculto(iid, True, conn=conn)
            registrar_auditoria(
                alm, conn, actor, "insumo.ocultar_duplicado_apu", "insumo", iid,
                antes={"oculto": False},
                despues={"oculto": True, "codigo": cod, "nombre": nom})
    return {"insumos_ocultados": len(a_ocultar)}
