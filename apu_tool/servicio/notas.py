"""Notas humanas de insumos y APUs: dueño, permisos y auditoría.

Texto libre que puede llevar montos: NUNCA se pasa a la IA (Invariante #1; las claves
`nota`/`notas`/`ultima_nota` están en privacy._FORBIDDEN_KEYS). El dueño se identifica
por su identidad estable, no por un id: insumo = código + nombre normalizado (los códigos
se repiten), APU = código + turno (diurno y nocturno tienen notas propias).
"""
from __future__ import annotations

import datetime as dt
from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Nota, Perfil
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria

MAX_TEXTO = 4000
ENTIDADES = ("insumo", "apu")


class NotaNoEncontrada(Exception):
    pass


class SinPermiso(Exception):
    pass


def clave_insumo(codigo: str, nombre: str) -> str:
    return f"{(codigo or '').strip()}|{normalizar(nombre or '')}"


def clave_apu(codigo: str, turno: str) -> str:
    return f"{(codigo or '').strip()}|{(turno or '').strip().upper()}"


def _ahora() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def _texto_valido(texto: str) -> str:
    t = (texto or "").strip()
    if not t:
        raise ValueError("La nota no puede estar vacía.")
    if len(t) > MAX_TEXTO:
        raise ValueError(f"La nota no puede pasar de {MAX_TEXTO} caracteres.")
    return t


def _resolver_dueno(alm: Almacen, entidad: str, codigo: str, nombre: str,
                    turno: str) -> tuple[str, str]:
    """(clave, etiqueta) del dueño si existe HOY; ValueError si no. Una nota sobre algo
    inexistente es una nota perdida desde el día uno."""
    codigo = (codigo or "").strip()
    if entidad == "insumo":
        objetivo = normalizar(nombre or "")
        for ins in alm.precios.get_candidatos(codigo):
            if normalizar(ins.nombre) == objetivo:
                return clave_insumo(codigo, ins.nombre), f"{ins.codigo} · {ins.nombre}"
        raise ValueError(f"No existe el insumo {codigo} «{nombre}».")
    if entidad == "apu":
        t = (turno or "").strip().upper()
        apu = alm.apus.get_apu(codigo, t)
        if apu is None:
            raise ValueError(f"No existe el APU {codigo} en turno {t}.")
        return clave_apu(codigo, t), f"{apu.codigo} · {apu.shift} · {apu.nombre}"
    raise ValueError("La nota debe ser de un insumo o de un APU.")


def _dueno(n: Nota) -> dict:
    """Identidad del dueño leída de la clave, para reabrir su panel desde la pestaña
    Notas. El nombre del insumo sale tal cual de la etiqueta (lo que va después de ' · ');
    solo si la etiqueta no lo trae se usa la parte normalizada de la clave."""
    codigo, _, resto = n.clave.partition("|")
    if n.entidad == "insumo":
        nombre = n.etiqueta.split(" · ", 1)[1] if " · " in n.etiqueta else resto
        return {"entidad": "insumo", "codigo": codigo, "nombre": nombre, "turno": ""}
    return {"entidad": "apu", "codigo": codigo, "nombre": "", "turno": resto}


def _puede_borrar(n: Nota, actor: Perfil) -> bool:
    return actor.user_id == n.autor_id or actor.rol == "admin"


def _out(n: Nota, actor: Perfil) -> dict:
    mia = actor.user_id == n.autor_id
    escribe = actor.rol in ("editor", "admin")
    return {"id": n.id, "entidad": n.entidad, "etiqueta": n.etiqueta, "texto": n.texto,
            "autor_email": n.autor_email, "creada_en": n.creada_en,
            "editada_en": n.editada_en, "es_mia": mia,
            "puede_editar": mia and escribe,
            "puede_borrar": escribe and _puede_borrar(n, actor),
            "dueno": _dueno(n)}


def _vigente(alm: Almacen, nota_id: int) -> Nota:
    n = alm.notas.get(nota_id)
    if n is None or n.borrada:
        raise NotaNoEncontrada()
    return n


def listar(alm: Almacen, actor: Perfil, entidad: str, codigo: str, nombre: str = "",
           turno: str = "") -> list[dict]:
    if entidad not in ENTIDADES:
        raise ValueError("La nota debe ser de un insumo o de un APU.")
    clave = (clave_insumo(codigo, nombre) if entidad == "insumo"
             else clave_apu(codigo, turno))
    return [_out(n, actor) for n in alm.notas.listar(entidad, clave)]


def crear(alm: Almacen, actor: Perfil, entidad: str, codigo: str, nombre: str,
          turno: str, texto: str) -> dict:
    t = _texto_valido(texto)
    clave, etiqueta = _resolver_dueno(alm, entidad, codigo, nombre, turno)
    with alm.transaccion("seguridad") as conn:
        nid = alm.notas.crear(conn, entidad, clave, etiqueta, t, actor.user_id,
                              actor.email, _ahora())
        registrar_auditoria(alm, conn, actor, "nota.crear", "nota", nid, antes=None,
                            despues={"entidad": entidad, "clave": clave, "texto": t})
    return _out(alm.notas.get(nid), actor)


def editar(alm: Almacen, actor: Perfil, nota_id: int, texto: str) -> dict:
    n = _vigente(alm, nota_id)
    if actor.user_id != n.autor_id:
        raise SinPermiso("Solo quien escribió la nota puede editarla.")
    t = _texto_valido(texto)
    with alm.transaccion("seguridad") as conn:
        alm.notas.editar(conn, n.id, t, _ahora())
        registrar_auditoria(alm, conn, actor, "nota.editar", "nota", n.id,
                            antes={"texto": n.texto}, despues={"texto": t})
    return _out(alm.notas.get(n.id), actor)


def borrar(alm: Almacen, actor: Perfil, nota_id: int) -> None:
    n = _vigente(alm, nota_id)
    if not _puede_borrar(n, actor):
        raise SinPermiso("Solo quien escribió la nota o un Admin puede borrarla.")
    with alm.transaccion("seguridad") as conn:
        alm.notas.borrar(conn, n.id)
        registrar_auditoria(alm, conn, actor, "nota.borrar", "nota", n.id,
                            antes={"texto": n.texto}, despues=None)


def todas(alm: Almacen, actor: Perfil, entidad: Optional[str] = None,
          autor: Optional[str] = None, q: Optional[str] = None,
          limit: int = 100, offset: int = 0) -> dict:
    items, total = alm.notas.buscar(entidad=entidad or None, autor_id=autor or None,
                                    q=(q or "").strip() or None, limit=limit, offset=offset)
    return {"items": [_out(n, actor) for n in items], "total": total,
            "limit": limit, "offset": offset}


def resumen(alm: Almacen, entidad: str, claves: list[str]) -> dict[str, str]:
    """clave → texto de la última nota, para pintar el ícono de TODA una página de un
    listado en UNA consulta (nunca una por fila: el N+1 que ya se pagó con Supabase)."""
    return alm.notas.resumen_por_claves(entidad, claves)
