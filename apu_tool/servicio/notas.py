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


def _out(n: Nota, actor: Perfil, menciones: list[dict]) -> dict:
    mia = actor.user_id == n.autor_id
    escribe = actor.rol in ("editor", "admin")
    if n.borrada:
        # Marcador de una raíz borrada que todavía tiene respuestas: sostiene el hilo
        # sin mostrar lo que se borró.
        return {"id": n.id, "entidad": n.entidad, "etiqueta": n.etiqueta, "texto": "",
                "autor_email": n.autor_email, "creada_en": n.creada_en,
                "editada_en": n.editada_en, "es_mia": mia, "puede_editar": False,
                "puede_borrar": False, "dueno": _dueno(n), "menciones": [],
                "responde_a": n.responde_a, "borrada": True}
    return {"id": n.id, "entidad": n.entidad, "etiqueta": n.etiqueta, "texto": n.texto,
            "autor_email": n.autor_email, "creada_en": n.creada_en,
            "editada_en": n.editada_en, "es_mia": mia,
            "puede_editar": mia and escribe,
            "puede_borrar": escribe and _puede_borrar(n, actor),
            "dueno": _dueno(n), "menciones": menciones,
            "responde_a": n.responde_a, "borrada": False}


def _perfiles(alm: Almacen) -> dict[str, Perfil]:
    """user_id → Perfil. La tabla de perfiles es chica (decenas): una lectura por request."""
    return {p.user_id: p for p in alm.perfiles.listar()}


def _nombre(p: Optional[Perfil], uid: str) -> str:
    return (p.nombre or p.email) if p else uid


def _menciones_validas(perfiles: dict[str, Perfil], actor: Perfil,
                       pedidas: list[str]) -> list[str]:
    """Solo perfiles activos, sin el propio autor, sin duplicados, en el orden pedido.
    El cliente dice a quién quiere mencionar; el servidor decide a quién se puede."""
    out: list[str] = []
    for uid in pedidas or []:
        p = perfiles.get(uid)
        if p and p.estado == "activo" and uid != actor.user_id and uid not in out:
            out.append(uid)
    return out


def _salidas(alm: Almacen, notas: list[Nota], actor: Perfil) -> list[dict]:
    """Notas → JSON con sus menciones, en lote (una consulta para todas)."""
    menc = alm.notas.menciones_de_notas([n.id for n in notas])
    perfiles = _perfiles(alm) if menc else {}
    return [_out(n, actor, [{"user_id": u, "nombre": _nombre(perfiles.get(u), u)}
                            for u in menc.get(n.id, [])]) for n in notas]


def _vigente(alm: Almacen, nota_id: int) -> Nota:
    n = alm.notas.get(nota_id)
    if n is None or n.borrada:
        raise NotaNoEncontrada()
    return n


def _hilo(notas: list[Nota]) -> list[Nota]:
    """Las vivas, más las raíces borradas que todavía tienen respuestas vivas (como
    marcador). Una respuesta borrada no se muestra. Orden por id (cronológico)."""
    con_respuesta = {n.responde_a for n in notas if n.responde_a is not None and not n.borrada}
    return [n for n in notas
            if not n.borrada or (n.responde_a is None and n.id in con_respuesta)]


def listar(alm: Almacen, actor: Perfil, entidad: str, codigo: str, nombre: str = "",
           turno: str = "") -> list[dict]:
    if entidad not in ENTIDADES:
        raise ValueError("La nota debe ser de un insumo o de un APU.")
    clave = (clave_insumo(codigo, nombre) if entidad == "insumo"
             else clave_apu(codigo, turno))
    return _salidas(alm, _hilo(alm.notas.listar(entidad, clave, incluir_borradas=True)), actor)


def _raiz_para_responder(alm: Almacen, responde_a: int, entidad: str, clave: str) -> int:
    """Valida el padre y aplana a un nivel: responder a una respuesta cuelga de su raíz."""
    padre = alm.notas.get(responde_a)
    if padre is None or padre.borrada:
        raise ValueError("La nota a la que respondes ya no existe.")
    if padre.entidad != entidad or padre.clave != clave:
        raise ValueError("Solo puedes responder notas del mismo insumo o APU.")
    return padre.responde_a or padre.id


def crear(alm: Almacen, actor: Perfil, entidad: str, codigo: str, nombre: str,
          turno: str, texto: str, menciones: Optional[list[str]] = None,
          responde_a: Optional[int] = None) -> dict:
    t = _texto_valido(texto)
    clave, etiqueta = _resolver_dueno(alm, entidad, codigo, nombre, turno)
    raiz = (None if responde_a is None
            else _raiz_para_responder(alm, responde_a, entidad, clave))
    perfiles = _perfiles(alm)
    uids = _menciones_validas(perfiles, actor, menciones or [])
    ahora = _ahora()
    with alm.transaccion("seguridad") as conn:
        nid = alm.notas.crear(conn, entidad, clave, etiqueta, t, actor.user_id,
                              actor.email, ahora, responde_a=raiz)
        alm.notas.set_menciones(conn, nid, uids, ahora)
        despues = {"entidad": entidad, "clave": clave, "texto": t}
        if raiz is not None:
            despues["responde_a"] = raiz
        if uids:   # la auditoría es historia permanente: correos, no user_ids
            despues["menciones"] = [perfiles[u].email for u in uids]
        registrar_auditoria(alm, conn, actor, "nota.crear", "nota", nid, antes=None,
                            despues=despues)
    return _salidas(alm, [alm.notas.get(nid)], actor)[0]


def editar(alm: Almacen, actor: Perfil, nota_id: int, texto: str,
           menciones: Optional[list[str]] = None) -> dict:
    """`menciones=None` deja las menciones como están; una lista (aun vacía) las
    resincroniza: los nuevos reciben aviso, los quitados pierden el suyo."""
    n = _vigente(alm, nota_id)
    if actor.user_id != n.autor_id:
        raise SinPermiso("Solo quien escribió la nota puede editarla.")
    t = _texto_valido(texto)
    perfiles = _perfiles(alm)
    uids = (None if menciones is None else _menciones_validas(perfiles, actor, menciones))
    ahora = _ahora()
    with alm.transaccion("seguridad") as conn:
        # El UPDATE de `nota` va ANTES de set_menciones: su bloqueo de fila serializa dos
        # ediciones concurrentes de la misma nota, por eso set_menciones no necesita ON CONFLICT.
        alm.notas.editar(conn, n.id, t, ahora)
        if uids is not None:
            alm.notas.set_menciones(conn, n.id, uids, ahora)
        despues = {"texto": t}
        if uids:
            despues["menciones"] = [perfiles[u].email for u in uids]
        registrar_auditoria(alm, conn, actor, "nota.editar", "nota", n.id,
                            antes={"texto": n.texto}, despues=despues)
    return _salidas(alm, [alm.notas.get(n.id)], actor)[0]


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
    return {"items": _salidas(alm, items, actor), "total": total,
            "limit": limit, "offset": offset}


def resumen(alm: Almacen, entidad: str, claves: list[str]) -> dict[str, str]:
    """clave → texto de la última nota, para pintar el ícono de TODA una página de un
    listado en UNA consulta (nunca una por fila: el N+1 que ya se pagó con Supabase)."""
    return alm.notas.resumen_por_claves(entidad, claves)


def mencionables(alm: Almacen, actor: Perfil) -> list[dict]:
    """A quién se puede mencionar: perfiles activos menos quien pregunta. Solo nombre,
    email e id (la barra de presencia ya les muestra eso mismo a todos)."""
    out = [{"user_id": p.user_id, "nombre": p.nombre or "", "email": p.email}
           for p in alm.perfiles.listar()
           if p.estado == "activo" and p.user_id != actor.user_id]
    return sorted(out, key=lambda u: (u["nombre"] or u["email"]).lower())


def bandeja(alm: Almacen, actor: Perfil, limit: int = 50) -> list[dict]:
    return [{"nota_id": n.id, "etiqueta": n.etiqueta, "autor_email": n.autor_email,
             "creada_en": n.creada_en, "texto": n.texto[:160], "leida": leida is not None,
             "dueno": _dueno(n)}
            for n, leida in alm.notas.listar_menciones(actor.user_id, limit)]


def marcar_leida(alm: Almacen, actor: Perfil, nota_id: int) -> None:
    with alm.transaccion("seguridad") as conn:
        alm.notas.marcar_leida(conn, actor.user_id, nota_id, _ahora())


def marcar_todas_leidas(alm: Almacen, actor: Perfil) -> None:
    with alm.transaccion("seguridad") as conn:
        alm.notas.marcar_todas_leidas(conn, actor.user_id, _ahora())


def sin_leer(alm: Almacen, actor: Perfil) -> Optional[int]:
    """Para la presencia: si la base falla, None; la presencia no se cae por esto."""
    try:
        return alm.notas.contar_sin_leer(actor.user_id)
    except Exception:
        return None
