"""
Lógica de la capa de servicio para las corridas (armado web).

No habla HTTP ni con la IA directamente: orquesta el dominio (matcher, assembler,
pricing, report) y la persistencia de la corrida. Ve dinero (arma el cuadro para
el equipo), pero nunca abre un camino hacia la IA.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import time
from dataclasses import asdict, replace
from datetime import datetime
from pathlib import Path
from typing import Iterable, Optional
from weakref import WeakKeyDictionary

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.datos.repositorio import ArmadoDuplicado, CorridaEliminada
from apu_tool.dominio import entrada
from apu_tool.dominio.alertas import alertas_costeo
from apu_tool.dominio.assemble import Assembler, ApuAdvisor
from apu_tool.dominio.matching import Matcher
from apu_tool.dominio.presupuesto import LecturaPresupuesto
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.report import write_report
from apu_tool.dominio import transporte
from apu_tool.dominio.report_categorizado import resumen_por_capitulo
from apu_tool.dominio.revision import IANoDisponible, Revisor, revisar
from apu_tool.nucleo.models import (
    AjusteProyecto, ApuComponent, AssembledApu, CostedComponent, CorridaItemRow,
    CorridaMeta, EntidadOrigen, LicitacionItem, MatchStatus, ParametrosProyecto,
)
from apu_tool.nucleo.redondeo import mul_redondeado
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria

logger = logging.getLogger(__name__)


class CorridaCongelada(Exception):
    """Se intentó modificar (confirmar/reasignar) una corrida en modo congelada."""
    def __init__(self, corrida_id: int):
        super().__init__(f"La corrida {corrida_id} está congelada (solo lectura).")
        self.corrida_id = corrida_id


class ArmadoIncompleto(RuntimeError):
    """La corrida todavía tiene líneas del plan SIN ARMAR: no se congela ni se emite
    cuadro.

    Es el hermano silencioso de `FilasSinApu`, y peor. Ahí las filas existen y están
    en $0, así que el candado las ve y la hoja ALERTAS las nombra. Acá las líneas que
    el worker no alcanzó a armar **no existen como filas**: `seqs_sin_apu` no puede
    verlas, y un cuadro de una corrida detenida en 290 de 1939 sale con 290 líneas
    pareciendo entero. Quien lo recibe no tiene forma de saber que le faltan 1.649
    actividades de la licitación.
    """
    def __init__(self, corrida_id: int, hechos: int, total: int):
        self.corrida_id = corrida_id
        self.hechos = hechos
        self.total = total
        super().__init__(
            f"La corrida todavía se está armando: {hechos} de {total} líneas. "
            f"Esperá a que termine (o reanudala si quedó detenida) antes de "
            f"congelar o descargar el cuadro.")


class FilasSinApu(RuntimeError):
    """La corrida tiene líneas sin APU asignado: no se congela ni se emite cuadro.

    Un cuadro con líneas sin APU se ve completo y no lo está: las filas van en $0 y
    quien lo recibe no tiene forma de saber que le faltan actividades. Se traba la
    puerta y se dice exactamente qué seq faltan.
    """
    def __init__(self, corrida_id: int, seqs: list[int]):
        self.corrida_id = corrida_id
        self.seqs = seqs
        super().__init__(
            f"{len(seqs)} línea(s) sin APU asignado. "
            f"Asígnalas antes de congelar o descargar el cuadro.")


def seqs_sin_apu(rows) -> list[int]:
    """Los seq de las filas que no tienen APU NI un costo declarado POSITIVO.
    Lista vacía = se puede cerrar.

    El candado existe para que no salga un cuadro con filas en $0 sin que nadie se
    entere. Una fila con costo puesto a mano no es ninguna de las dos cosas: el monto
    lo declaró una persona y la hoja ALERTAS la nombra (ver `alertas_costeo`).

    Pide `> 0` y NO `is not None` a propósito: el candado se defiende solo. Con
    `is not None`, un `costo_manual` de 0.0 (o NaN) abriría la puerta mientras el badge
    y la alerta —que piden `costo_unitario > 0`— lo ignoran, y saldría al cuadro una
    fila en $0 sin APU, sin badge y sin alerta. La validación del servicio
    (`igualar_costo_al_contractual`) ya rechaza el contractual ≤ 0, pero el
    candado no puede depender de que su único llamador se porte bien. `not (x or 0) > 0`
    también cierra el NaN: `not (nan > 0)` es True."""
    return [r.seq for r in rows
            if not r.apu_codigo and not (r.costo_manual or 0) > 0]


def _estructura(componentes) -> list[dict]:
    """Snapshot SIN dinero de una composición costeada (incluye tipo/ref_shift del componente)."""
    return [{"insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
             "unidad": c.unidad, "rendimiento": c.rendimiento,
             "tipo": getattr(c, "tipo", "insumo"), "ref_shift": getattr(c, "ref_shift", "")}
            for c in componentes]


# Cuántas filas con problema viajan en la previsualización. La previa valida la
# ESTRUCTURA (14 capítulos, 1939 actividades, conciliación); no reemplaza a la tabla de
# la corrida. Mandar 1939 filas para que el usuario mire 3 es medio mega por nada.
MAX_FILAS_SENALADAS = 50


def leer_para_corrida(entidad: EntidadOrigen, contenido: bytes, nombre_archivo: str,
                      default_shift: str = config.SHIFT_DIURNO) -> LecturaPresupuesto:
    """Bytes subidos -> LecturaPresupuesto, con el lector de esa entidad.

    El archivo se escribe a un temporal porque openpyxl necesita una ruta; se borra
    siempre. El archivo subido NO se persiste (igual que en el camino de hoy): lo que
    sobrevive es `plan_json`, que es de donde se reanuda el armado.
    """
    sufijo = Path(nombre_archivo or "presupuesto.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=sufijo) as tmp:
        tmp.write(contenido)
        ruta = tmp.name
    try:
        return entrada.leer(entidad, ruta, default_shift=default_shift)
    finally:
        os.unlink(ruta)


def previsualizar(entidad: EntidadOrigen, contenido: bytes,
                  nombre_archivo: str) -> dict:
    """Qué se detectó en el archivo, SIN escribir una sola fila.

    Es el paso que el usuario aprueba. No hay borrador ni estado temporal en la base: el
    navegador se queda con el archivo y lo reenvía al aprobar, y el parser es
    determinístico, así que la segunda lectura da lo mismo. Cancelar no deja nada que
    limpiar porque nunca hubo nada.
    """
    lectura = leer_para_corrida(entidad, contenido, nombre_archivo)
    capitulos = _capitulos_de_lectura(lectura)
    return {
        "entidad": entidad.value,
        "formato": entrada.formato_de(entidad),
        "archivo": nombre_archivo,
        "hoja": lectura.hoja,
        "fila_encabezado": lectura.fila_encabezado,
        "parser_version": lectura.parser_version,
        "capitulos": capitulos,
        "actividades": len(lectura.items),
        "filas_ignoradas": lectura.filas_ignoradas,
        "totales": {
            "contractual": sum(c["contractual"] for c in capitulos),
            "contractual_sin_aiu": sum(c["contractual_sin_aiu"] for c in capitulos),
        },
        "conciliacion": lectura.conciliacion,
        "errores": list(lectura.errores),
        "advertencias": [a.to_dict() for a in lectura.advertencias],
        "filas_senaladas": [a.to_dict() for a in lectura.advertencias
                            if a.fila][:MAX_FILAS_SENALADAS],
        # Lo decide el SERVIDOR; el botón del navegador solo obedece. `POST /corridas`
        # lo vuelve a evaluar al crear, porque el cliente puede mentir.
        "puede_aprobar": not lectura.errores and bool(lectura.items),
        "requiere_confirmacion": entrada.requiere_confirmacion(entidad),
    }


def _capitulos_de_lectura(lectura: LecturaPresupuesto) -> list[dict]:
    """Capítulos con sus totales contractuales, para la previsualización.

    Acá todavía NO hay costo (nada está armado), así que no se puede usar
    `resumen_por_capitulo`, que trabaja sobre `AssembledApu`. Lo que sí se comparte es la
    regla de redondeo: `mul_redondeado`, la misma que usará el armado, para que el total
    que el usuario aprueba sea exactamente el que después ve en la corrida.
    """
    if not lectura.capitulos:
        # Sin capítulos declarados no hay estructura que revisar: una lista plana no
        # gana una tabla de un solo grupo "(sin capítulo)", que sería puro ruido. El
        # grupo huérfano SÍ aparece cuando hay capítulos y alguna actividad quedó antes
        # del primero — ahí es una anomalía que el usuario tiene que ver.
        return []
    por_codigo: dict[str, dict] = {}
    for cap in lectura.capitulos:
        por_codigo[cap.codigo] = {**cap.to_dict(), "actividades": 0,
                                  "contractual": 0, "contractual_sin_aiu": 0}
    for it in lectura.items:
        fila = por_codigo.get(it.capitulo_codigo)
        if fila is None:
            fila = por_codigo.setdefault(it.capitulo_codigo, {
                "codigo": it.capitulo_codigo,
                "nombre": it.capitulo_nombre or "(sin capítulo)",
                "orden": len(por_codigo) + 1, "fila_origen": 0,
                "actividades": 0, "contractual": 0, "contractual_sin_aiu": 0})
        fila["actividades"] += 1
        fila["contractual"] += mul_redondeado(it.precio_contractual, it.cantidad)
        fila["contractual_sin_aiu"] += mul_redondeado(
            it.precio_contractual_sin_aiu, it.cantidad)
    return list(por_codigo.values())


def origen_de(entidad: EntidadOrigen, lectura: LecturaPresupuesto,
              nombre_archivo: str, confirmada_por: Optional[str]) -> dict:
    """El registro de importación que se guarda en `corrida.origen_json`.

    Una sola columna y no ocho, como `plan_json`: la migración es una línea por backend.
    Lleva la conciliación adentro, o sea DINERO, y por eso `origen_json` está en
    `privacy._FORBIDDEN_KEYS` — este objeto nunca cruza hacia la IA.
    """
    return {
        "entidad": entidad.value,
        "formato": entrada.formato_de(entidad),
        "archivo": nombre_archivo,
        "hoja": lectura.hoja,
        "fila_encabezado": lectura.fila_encabezado,
        "parser_version": lectura.parser_version,
        "importada_en": datetime.now().isoformat(timespec="seconds"),
        "confirmada_por": confirmada_por or "",
        "estructura_confirmada": True,
        "capitulos": len(lectura.capitulos),
        "actividades": len(lectura.items),
        "filas_ignoradas": lectura.filas_ignoradas,
        "advertencias": _contar_advertencias(lectura),
        "conciliacion": dict(lectura.conciliacion),
    }


def _contar_advertencias(lectura: LecturaPresupuesto) -> dict:
    """{tipo: cuántas}. El detalle de cada una NO se persiste: la previa ya lo mostró y
    el usuario ya lo confirmó; lo que importa después es el rastro de que las hubo.
    Además `Advertencia.detalle` lleva montos en texto libre (ver su docstring)."""
    conteo: dict[str, int] = {}
    for a in lectura.advertencias:
        conteo[a.tipo] = conteo.get(a.tipo, 0) + 1
    return conteo


def nombre_desde_archivo(filename: str) -> str:
    """Nombre por defecto de una corrida: el archivo subido SIN su última extensión.

    `Licitacion Calle 13.xlsx` -> `Licitacion Calle 13`. Es puro (sin I/O)."""
    base = (filename or "").strip()
    return Path(base).stem.strip() if base else ""


def _nombre_lista(alm: Almacen, lista_id: Optional[int]) -> str:
    """Etiqueta legible de la tarifa de una corrida. None = Principal.
    Se resuelve en vivo (no se denormaliza): renombrar una lista debe reflejarse."""
    if lista_id is None:
        return "Principal"
    lista = alm.precios.get_lista(lista_id)
    return lista.nombre if lista else f"lista {lista_id}"


def _contexto(alm: Almacen, meta: CorridaMeta, cache: Optional[dict] = None):
    """Desviaciones del proyecto de esta corrida (distancias, peaje, ajustes).

    Se resuelven EN VIVO desde la carpeta raíz: cambiar las distancias del proyecto
    recostea sus corridas activas sin tocar nada más. Una corrida congelada nunca
    llega acá (se sirve del snapshot).

    `cache`: memo por carpeta para un barrido de varias corridas (`listar_corridas`).
    Sin él, listar N corridas resuelve el contexto N veces (hasta 4 consultas cada
    una), que es el mismo N+1 de round-trips contra Postgres que la precarga en lote
    ya había eliminado."""
    if cache is None:
        return transporte.cargar_contexto(alm, meta.carpeta_id)
    if meta.carpeta_id not in cache:
        cache[meta.carpeta_id] = transporte.cargar_contexto(alm, meta.carpeta_id)
    return cache[meta.carpeta_id]


def _contexto_al_congelar(snaps: dict) -> Optional[transporte.ContextoProyecto]:
    """El contexto (parámetros + ajustes) con el que se congeló la corrida, leído
    del snapshot de cualquier ítem — `congelar` lo guarda redundante en CADA uno
    (no hay tabla a nivel de corrida; reusar `snapshot_json` es cero cambios de
    esquema). None si no hay snapshots o son de antes de este campo: el llamador
    cae a `_contexto` en vivo (retrocompatible)."""
    for snap in snaps.values():
        if "parametros" in snap:
            params = ParametrosProyecto(**snap["parametros"])
            ajustes = tuple(AjusteProyecto(**a) for a in snap.get("ajustes", ()))
            return transporte.ContextoProyecto(params=params, clasificacion={}, ajustes=ajustes)
    return None


def _armar_fila(assembler: Assembler, item: LicitacionItem,
                seq: int) -> tuple[AssembledApu, CorridaItemRow]:
    """Arma UNA línea y devuelve (ensamble costeado, fila lista para persistir).

    Un solo `match()` por ítem: sus candidatos son los que se le muestran al usuario y
    se reusan en `assemble_item()` para elegir el APU final (mismo resultado
    determinístico, sin recalcular el matcher).

    Es el camino ÚNICO del armado: lo usan el armado inicial (`armar_pendientes`)
    y las líneas que se agregan después (`agregar_items`), para que no puedan divergir.
    El `assembler` recibido trae SIEMPRE el contexto del proyecto (ver `_contexto`):
    de eso depende que `sin_distancia`/`en_subapus` de abajo salgan bien.
    """
    result = assembler.matcher.match(item)
    candidatos = [{"apu_codigo": c.apu_codigo, "apu_nombre": c.apu_nombre,
                   "score": c.score, "motivo": c.motivo}
                  for c in result.candidatos]
    ens = assembler.assemble_item(item, result)
    # AssembledApu es mutable: el Assembler no conoce el proyecto (no queremos
    # meterle esa noción a assemble.py), así que los pendientes se completan acá
    # con el motor compartido de la corrida, ANTES de armar la fila/vista.
    ens.sin_distancia = assembler.pricing.sin_distancia(ens.apu_codigo or "", ens.shift)
    ens.en_subapus = assembler.pricing.sin_distancia_en_subapus(
        ens.apu_codigo or "", ens.shift)
    fila = CorridaItemRow(
        seq=seq, item=item, status=ens.status.value, apu_codigo=ens.apu_codigo,
        apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
        origen=ens.origen, confianza=ens.confianza, explicacion=ens.explicacion,
        componentes=_estructura(ens.componentes), candidatos=candidatos)
    return ens, fila


def _fila_sin_apu(item: LicitacionItem, seq: int,
                  motivo: str) -> tuple[AssembledApu, CorridaItemRow]:
    """La fila que queda cuando armar un ítem revienta: sin APU, en $0 y con el motivo
    a la vista.

    No inventa una forma nueva: es la misma que `assemble_item` deja para un ítem bajo
    el umbral (sin APU, sin componentes, status `new`, origen manual), con otro nombre
    para que se distinga de "no había nada parecido en la biblioteca"."""
    ens = AssembledApu(
        item=item, apu_codigo=None, apu_nombre="(no se pudo armar)",
        unidad=item.unidad, shift=item.shift, componentes=[], costo_unitario=0.0,
        status=MatchStatus.NEW, confianza=0.0, origen="manual", explicacion=motivo)
    fila = CorridaItemRow(
        seq=seq, item=item, status=ens.status.value, apu_codigo=None,
        apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
        origen=ens.origen, confianza=ens.confianza, explicacion=motivo,
        componentes=[], candidatos=[])
    return ens, fila


def crear_corrida_encolada(alm: Almacen, archivo: str, items: list[LicitacionItem],
                           turno_def: str, use_ai: Optional[bool],
                           carpeta_id: Optional[int] = None,
                           nombre: Optional[str] = None,
                           lista_precios_id: Optional[int] = None,
                           origen: Optional[dict] = None) -> int:
    """Crea la corrida en 'armando' con su plan guardado y devuelve el id. NO arma:
    de eso se encarga quien llame a `armar_pendientes` — el camino sincrónico de la
    CLI/GUI, o el worker, que la ve porque `estado='armando'` ES la cola.

    Guardar el plan es lo que hace posible reanudar: el Excel subido no se persiste,
    así que sin esto un reinicio deja la corrida a medias sin forma de continuar.
    """
    nombre_efectivo = (nombre or "").strip()[:120].strip() or nombre_desde_archivo(archivo)
    try:
        corrida_id = alm.corridas.crear_corrida(CorridaMeta(
            id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
            archivo=archivo, turno_def=turno_def, use_ai=use_ai,
            estado="armando", cuadro_path=None, carpeta_id=carpeta_id,
            nombre=nombre_efectivo, lista_precios_id=lista_precios_id))
    except ArmadoDuplicado as e:
        # La violación pasa en el INSERT, así que no queda una corrida a medio crear
        # (el `set_plan` de abajo ni se intenta). Solo falta decir CUÁL es la que ya
        # existe, para poder llevar al usuario ahí en vez de dejarlo reintentando.
        raise ArmadoDuplicado(archivo, armado_en_curso(alm, carpeta_id, archivo)) from e
    alm.corridas.set_plan(corrida_id, json.dumps([asdict(i) for i in items],
                                                 ensure_ascii=False))
    if origen is not None:
        # Igual que el plan: una escritura aparte en vez de ensuciar el INSERT de
        # los dos backends. Va DESPUÉS del plan a propósito — si esto falla, la
        # corrida queda armable; al revés quedaría sellada y sin qué armar.
        alm.corridas.set_origen(corrida_id,
                                json.dumps(origen, ensure_ascii=False))
    return corrida_id


def armado_en_curso(alm: Almacen, carpeta_id: Optional[int],
                    archivo: str) -> Optional[int]:
    """El id del armado a medias que ocupa ese (carpeta, archivo), o None.

    Se busca DESPUÉS de la violación, no antes: preguntar antes es la carrera que este
    índice existe para cerrar. Recorre `listar_corridas` en vez de agregar una consulta
    nueva a los dos backends — corre una vez por doble clic, no por petición.

    None solo si la corrida que acaba de bloquear el INSERT desapareció en el medio
    (la borraron entre las dos escrituras): rarísimo, y el mensaje se adapta."""
    for meta in alm.corridas.listar_corridas():
        if (meta.estado in ARMANDO_O_A_MEDIAS and meta.carpeta_id == carpeta_id
                and meta.archivo == archivo):
            return meta.id
    return None


def plan_de(alm: Almacen, corrida_id: int) -> list[LicitacionItem]:
    """Las líneas guardadas al crear la corrida. Lista vacía si no hay plan.

    Ojo con el esquema: un campo NUEVO de `LicitacionItem` con default se resuelve
    callado, así que una corrida encolada antes del deploy reanuda con el default en
    vez de lo que decía el Excel. Un campo renombrado o borrado, en cambio, levanta
    `TypeError` — ruidoso, que es lo correcto para el caso peligroso. Si algún día hay
    que cambiar la forma de `LicitacionItem`, hay que mirar las corridas en cola.

    Y el caso que NO es simétrico, medido al agregar los campos de la ruta IDU: un plan
    escrito por la versión NUEVA y leído por la VIEJA también levanta `TypeError`, por
    las claves que su constructor no conoce. Pasa solo en la ventana de un deploy —
    mientras la instancia vieja drena puede reclamar una corrida que creó la nueva— y
    se recupera solo: el worker cuenta el fallo, la corrida cae en `armado_detenido`
    con el motivo, y el botón de reintentar la arma bien contra la instancia nueva. No
    corrompe nada. Se documenta acá para que nadie pierda media hora entendiendo un
    `TypeError` que se arregla con un clic.
    """
    crudo = alm.corridas.get_plan(corrida_id)
    if not crudo:
        return []
    return [LicitacionItem(**d) for d in json.loads(crudo)]


def armar_pendientes(alm: Almacen, corrida_id: int, items: list[LicitacionItem],
                     desde_seq: int = 0):
    """Arma los ítems de `items` desde el índice `desde_seq`, emitiendo:
      ('progress', {'i','total','descripcion','fila'}) — por ítem YA persistido, con la
                                                fila costeada; `i` es 1-based y `total`
                                                es el plan entero.
      ('error', {'detail': ...})               — la corrida se borró a mitad
                                                (cancelación limpia, sin FK crudo).

    `desde_seq` es por donde entra el worker al reanudar: el seq de una fila ES su
    índice en el plan, así que arrancar en el índice N es seguir donde quedó. Cada APU
    se guarda al armarlo (no todo al final), así la tabla se llena en vivo y lo ya
    armado sobrevive a un reinicio.

    Un ítem que revienta NO tumba la corrida: se persiste sin APU con el motivo en
    `explicacion` y el armado sigue. Un ítem venenoso cuesta una fila, no 1900. Esa
    fila cae sola en el candado de `seqs_sin_apu` (que impide emitir el cuadro), y si
    no vale la pena armarle el APU se le puede igualar el costo al contractual, que
    abre ese candado a propósito.

    Salvo que los fallos vengan SEGUIDOS: a los `config.MAX_FALLOS_SEGUIDOS_ARMADO`
    se corta y la excepción SUBE, sin escribir esa última fila. Ahí lo que se cayó no
    es un ítem, es el entorno, y seguir escribiría el plan entero como "no se pudo
    armar" — filas permanentes, porque cuentan para `max_seq` y al reanudar el worker
    arranca después de ellas. Levantando, la corrida queda en la cola con el motivo y
    se reintenta cuando la base vuelva. Un éxito reinicia el contador (ver config).
    """
    # `enabled=False` y no `use_ai`: el armado NUNCA llama a la IA (audita después, ver
    # dominio/revision.py; hay un test que lo fija). El Assembler ya no usa el advisor
    # para nada — la composición se mudó a `dominio/composicion_agente.py` — pero
    # pasarle uno apagado deja la puerta cerrada de este lado igual.
    meta = alm.corridas.get_corrida(corrida_id)
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id if meta else None,
                          # Las mismas desviaciones del proyecto que usará la vista: si
                          # el armado en vivo costeara con la biblioteca cruda, los
                          # números saltarían al terminar.
                          contexto=_contexto(alm, meta) if meta else None)
    total = len(items)
    fallos_seguidos = 0
    for seq in range(desde_seq, total):
        item = items[seq]
        i = seq + 1
        # El ritmo real por ítem se mide con esto en los logs de Render (2,8 s/ítem):
        # sacarlo nos deja ciegos justo cuando queramos atacar la velocidad.
        print(f"  [{i}/{total}] {item.descripcion[:60]}", flush=True)
        try:
            ens, fila = _armar_fila(assembler, item, seq)
        except Exception as exc:   # noqa: BLE001 — un ítem venenoso no mata la corrida
            logger.exception("Fallo al armar el ítem %s de la corrida %s", seq, corrida_id)
            fallos_seguidos += 1
            if fallos_seguidos >= config.MAX_FALLOS_SEGUIDOS_ARMADO:
                # `from exc`: el motivo real viaja en la cadena y el worker lo guarda.
                raise RuntimeError(
                    f"{fallos_seguidos} ítems seguidos fallaron al armar "
                    f"(el último, el {i} de {total}): se detuvo el armado para no "
                    f"quemar el plan. Último error: {exc}") from exc
            ens, fila = _fila_sin_apu(item, seq, f"No se pudo armar: {exc}")
        else:
            fallos_seguidos = 0        # un ítem sano corta la racha: era el ítem, no el entorno
        try:
            alm.corridas.agregar_item(corrida_id, fila)
        except CorridaEliminada:
            yield ("error", {"detail": "Armado cancelado: la corrida fue eliminada."})
            return
        yield ("progress", {"i": i, "total": total,
                            "descripcion": item.descripcion,
                            "fila": _vista_item(ens, seq, ens.status.value)})


def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None,
                      nombre: Optional[str] = None,
                      lista_precios_id: Optional[int] = None,
                      origen: Optional[dict] = None) -> int:
    """Crea y arma en el acto, sin worker ni cola. Lo usan la CLI, la GUI y los tests:
    ahí no hay proceso de fondo que espere, y las listas son chicas."""
    corrida_id = crear_corrida_encolada(alm, archivo, items, turno_def, use_ai,
                                        carpeta_id, nombre, lista_precios_id,
                                        origen)
    t0 = time.monotonic()
    for evento, _payload in armar_pendientes(alm, corrida_id, items, desde_seq=0):
        if evento == "error":
            return corrida_id       # borraron la corrida a mitad: no hay nada que cerrar
    alm.corridas.finalizar_armado(corrida_id, "en_revision",
                                  duracion_ms=round((time.monotonic() - t0) * 1000))
    return corrida_id


# Tope por operación al agregar líneas. Es una sola petición HTTP sin progreso, así
# que la espera tiene que ser humana; con IA activada cada línea cuesta segundos.
MAX_LINEAS_AGREGADAS = 100


def preview_agregar(alm: Almacen, corrida_id: int,
                    items: list[LicitacionItem]) -> Optional[dict]:
    """Qué pasaría al agregar estas líneas, SIN escribir nada ni tocar el matcher.

    `duplicadas` son las que ya están en la corrida por descripción normalizada, con el
    seq de la línea existente. Es un AVISO: `agregar_items` las agrega igual, porque
    saltearlas en silencio esconde el duplicado. None si la corrida no existe.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    existentes: dict[str, int] = {}
    for r in alm.corridas.get_items(corrida_id):
        existentes.setdefault(normalizar(r.item.descripcion), r.seq)   # gana el primer seq
    nuevas: list[dict] = []
    duplicadas: list[dict] = []
    for it in items:
        fila = {"item": it.item, "descripcion": it.descripcion, "unidad": it.unidad,
                "cantidad": it.cantidad, "precio_contractual": it.precio_contractual,
                "shift": it.shift}
        seq_existente = existentes.get(normalizar(it.descripcion))
        if seq_existente is None:
            nuevas.append(fila)
        else:
            duplicadas.append({**fila, "seq_existente": seq_existente})
    return {"total": len(items), "nuevas": nuevas, "duplicadas": duplicadas,
            "modo": meta.modo, "tope": MAX_LINEAS_AGREGADAS}


# Estados en los que el plan está a medias y el espacio de `seq` sigue siendo del
# armador. `armado_detenido` cuenta: la corrida se rindió con ítems del plan sin armar
# y `reencolar_armado` la puede devolver a la cola en cualquier momento.
_MSG_PLAN_A_MEDIAS = (
    "La corrida todavía tiene líneas por armar; esperá a que termine "
    "(o reanudala si quedó detenida) antes de {accion} líneas.")

ARMANDO_O_A_MEDIAS = ("armando", "armado_detenido")


def _plan_a_medias(meta) -> bool:
    return meta.estado in ARMANDO_O_A_MEDIAS


def agregar_items(alm: Almacen, corrida_id: int,
                  items: list[LicitacionItem]) -> Optional[dict]:
    """Suma líneas a una corrida ya armada. Devuelve la vista; None si no existe.

    Las líneas nuevas pasan por el MISMO camino que el armado inicial (`_armar_fila`),
    con la `use_ai` y la lista de precios que la corrida guardó al crearse: una
    actividad que faltó no puede costearse con otra tarifa que el resto de la corrida.

    Lanza CorridaCongelada si está congelada (una foto inmutable no crece) y ValueError
    si no llegó ninguna línea o si pasan de MAX_LINEAS_AGREGADAS.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    if _plan_a_medias(meta):
        # El armador va tomando los seq del plan a medida que avanza; agregar acá
        # pediría uno que el armado todavía no llegó a usar. Con `ux_corrida_item_seq`
        # eso ya no entra callado —revienta—, pero reventar a mitad de un armado de
        # tres horas tampoco es el comportamiento que queremos: se espera y listo.
        #
        # `armado_detenido` cuenta igual, y ahí el daño es PEOR y silencioso: la línea
        # nueva ocupa el `seq` que le tocaba a un ítem del plan, el worker reanuda en
        # `max_seq + 1` y ese ítem NUNCA se arma. La corrida sale a `en_revision`
        # entera a la vista y `seqs_sin_apu` no ve nada, porque esa fila no existe.
        raise ValueError(_MSG_PLAN_A_MEDIAS.format(accion="agregar"))
    if not items:
        raise ValueError("No hay líneas para agregar.")
    if len(items) > MAX_LINEAS_AGREGADAS:
        raise ValueError(f"Máximo {MAX_LINEAS_AGREGADAS} líneas por vez; "
                         f"llegaron {len(items)}. Partí el archivo.")
    # Advisor apagado, igual que `armar_pendientes`: las dos entran por `_armar_fila`,
    # que es el camino ÚNICO del armado, y la IA no participa de ninguna de las dos.
    # Tener dos políticas para un camino único es cómo se cuela una diferencia.
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id,
                          # Mismas desviaciones del proyecto que el resto de la
                          # corrida: si no, el respaldo que persiste esta línea
                          # (`row.componentes`, ver `_costear_row`) queda con el
                          # rendimiento de la biblioteca cruda. Hoy no se nota
                          # (el costeo vivo se re-deriva fresco de la biblioteca
                          # mientras el APU siga ahí) pero SÍ en cuanto el APU se
                          # borre de la biblioteca: ese respaldo es lo único que
                          # queda, y costearía de menos en silencio.
                          contexto=_contexto(alm, meta))
    # El seq sigue desde el máximo y los huecos que dejó un borrado NO se reusan: el
    # seq es la clave del snapshot y de la URL del ítem.
    # Se lee fuera de transacción: dos usuarios agregando en el mismo instante podrían
    # pedir el mismo seq. Desde `ux_corrida_item_seq` eso ya NO entra callado — el
    # segundo INSERT revienta y el usuario reintenta —, así que la carrera dejó de
    # poder duplicar una actividad en el cuadro, que era el daño real.
    siguiente = max((r.seq for r in alm.corridas.get_items(corrida_id)), default=-1) + 1
    for k, item in enumerate(items):
        seq = siguiente + k
        if not (item.item or "").strip():
            # Línea a mano sin nº de ítem: se numera sola (el lector de Excel ya
            # numera por fila, así que esto solo aplica a la vía manual).
            item = replace(item, item=str(seq + 1))
        _ens, fila = _armar_fila(assembler, item, seq)
        alm.corridas.agregar_item(corrida_id, fila)
    if meta.estado == "finalizada":
        # El cuadro emitido ya no describe la corrida: vuelve a revisión.
        alm.corridas.set_estado(corrida_id, "en_revision")
    return vista_corrida(alm, corrida_id)


def borrar_items(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                 actor=None) -> Optional[dict]:
    """Borra líneas de una corrida: la válvula del "me equivoqué al agregar".

    No renumera. Los seq que quedan siguen siendo los mismos (los snapshots y las URLs
    de ítem no cambian de dueño) y un seq borrado no se reusa: `agregar_items` sigue
    desde el máximo. Los seq ajenos a la corrida se saltean. Lanza CorridaCongelada si
    está congelada, y ValueError si todavía se está armando (ver la guarda).
    Devuelve None si la corrida no existe.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    if _plan_a_medias(meta):
        # El worker reanuda en `max_seq + 1`. Borrar las ÚLTIMAS líneas hace que ese
        # máximo RETROCEDA, y si la instancia muere justo ahí, al reanudar se re-arma
        # exactamente lo que se acaba de borrar. Misma guarda y mismo motivo que
        # `agregar_items`: mientras el plan esté a medias, el espacio de `seq` es del
        # armador.
        raise ValueError(_MSG_PLAN_A_MEDIAS.format(accion="borrar"))
    pedidos = {int(s) for s in seqs}
    victimas = [r for r in alm.corridas.get_items(corrida_id) if r.seq in pedidos]
    if victimas:
        with alm.transaccion("corridas") as conn:
            alm.corridas.borrar_items(corrida_id, [r.seq for r in victimas], conn=conn)
            registrar_auditoria(
                alm, conn, actor, "corrida.borrar_items", "corrida", corrida_id,
                antes={"lineas": [{"seq": r.seq, "descripcion": r.item.descripcion}
                                  for r in victimas]},
                despues=None)
        if meta.estado == "finalizada":
            alm.corridas.set_estado(corrida_id, "en_revision")
    return vista_corrida(alm, corrida_id)


def _costear_row(alm: Almacen, row: CorridaItemRow,
                 pricing: Optional[PricingEngine] = None,
                 lista_id: Optional[int] = None,
                 contexto=None) -> AssembledApu:
    """Costeo ACTIVA: re-lee la composición del APU asignado desde la biblioteca y
    costea con precios vigentes. Si no hay apu_codigo o el APU fue borrado, usa la
    composición guardada del ítem (respaldo).

    `pricing`: motor opcional COMPARTIDO entre filas (optimización). Sus cachés de
    precios y de costo de sub-APUs se reusan entre ítems, evitando re-consultar el
    mismo insumo/sub-APU una vez por fila. Si es None se crea uno por fila (como
    antes). El caché por (código, precio vigente) da el mismo costo dentro del
    request, así que compartirlo no cambia resultados.

    `lista_id`/`contexto`: tarifa y desviaciones del proyecto a usar cuando se crea
    el motor aquí (None = Principal / biblioteca tal cual). Si llega un `pricing`
    compartido, ambos viajan DENTRO de él y estos parámetros se ignoran."""
    if row.costo_manual is not None:
        # Costo declarado por una persona (proyectos especiales: la actividad vale lo
        # que dice el contrato y armarle el APU no paga). No se consulta el catálogo:
        # no hay composición que costear. La firma "sin componentes + costo > 0" es la
        # que `alertas_costeo` reconoce para marcar la fila, activa y congelada.
        return AssembledApu(
            item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
            unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=[],
            costo_unitario=row.costo_manual, status=MatchStatus(row.status),
            confianza=row.confianza, explicacion=row.explicacion, origen=row.origen)
    pricing = pricing or PricingEngine(alm, lista_id=lista_id, contexto=contexto)
    clave_apu = (row.apu_codigo or "", row.shift)
    seed = (clave_apu,)
    costed = None
    if row.apu_codigo:
        lib = pricing.components(row.apu_codigo, row.shift)   # usa caché precargado si existe
        if lib or pricing.vaciado_por_el_proyecto(row.apu_codigo, row.shift):
            # `lib` vacío por dos motivos MUY distintos: (a) el APU fue borrado de
            # la biblioteca (o nunca tuvo composición ahí) -> cae al respaldo de
            # abajo; (b) la biblioteca SÍ tenía algo y el proyecto lo vació (p.ej.
            # el único componente era el peaje y el proyecto no tiene peaje) -> se
            # costea la lista vacía tal cual (da 0) y NO se cae al respaldo: ese
            # respaldo recobraría justo lo que el proyecto excluyó, al precio del
            # catálogo y sin alerta. `alertas.py` avisa el $0 en cualquier caso.
            costed, total = pricing.cost_components(lib, seed, clave_apu)
    if costed is None:
        comps = [ApuComponent(
            apu_codigo=row.apu_codigo or "", shift=row.shift,
            insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
            unidad=c["unidad"], rendimiento=c["rendimiento"],
            precio_unitario_hist=0.0,
            tipo=c.get("tipo", "insumo"), ref_shift=c.get("ref_shift", ""))
            for c in row.componentes]
        costed, total = pricing.cost_components(comps, seed, clave_apu)
    return AssembledApu(
        item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
        unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=costed,
        costo_unitario=total, status=MatchStatus(row.status),
        confianza=row.confianza, explicacion=row.explicacion, origen=row.origen,
        sin_distancia=pricing.sin_distancia(row.apu_codigo or "", row.shift),
        en_subapus=pricing.sin_distancia_en_subapus(row.apu_codigo or "", row.shift),
        peaje_sin_categoria=pricing.peaje_sin_categoria(row.apu_codigo or "", row.shift))


def _assembled_desde_snapshot(row: CorridaItemRow, snap: dict) -> AssembledApu:
    """Reconstruye un AssembledApu desde un snapshot congelado (composición + costos
    fijos). Los pendientes de distancia quedaron guardados en el snapshot (ver
    `congelar`): uno viejo, de antes de este campo, simplemente no trae ninguno."""
    comps = [CostedComponent(
        insumo_codigo=c["insumo_codigo"], insumo_nombre=c["insumo_nombre"],
        unidad=c["unidad"], rendimiento=c["rendimiento"],
        precio_unitario=c["precio_unitario"], fuente_precio=c["fuente_precio"],
        costo=c["costo"], calidad_cruce=c.get("calidad_cruce", "exacto"))
        for c in snap.get("composicion", [])]
    return AssembledApu(
        item=row.item, apu_codigo=row.apu_codigo, apu_nombre=row.apu_nombre,
        unidad=row.unidad or row.item.unidad, shift=row.shift, componentes=comps,
        costo_unitario=snap["costo_unitario"], status=MatchStatus(row.status),
        confianza=row.confianza, explicacion=row.explicacion, origen=row.origen,
        sin_distancia=tuple(snap.get("sin_distancia", ())),
        en_subapus=tuple(tuple(par) for par in snap.get("en_subapus", ())))


def _vista_item(ens: AssembledApu, seq: int, status: str,
                revision: Optional[dict] = None) -> dict:
    # Un veredicto sobre OTRO APU no dice nada del actual: no se manda. Es la red
    # contra la carrera de `revisar_corrida_stream`, que lee las filas al abrir el
    # request y corre por minutos — la tabla no se bloquea mientras tanto, así que el
    # usuario puede reasignar la fila 7 (lo que borra su veredicto) y el `set_revision`
    # de la revisión, ya en vuelo, lo escribe después: quedaría un `✔ ok` pegado a un
    # APU que la IA nunca vio. Se filtra al hidratar y no en el stream para no pagar
    # una lectura por fila (el N+1 contra Postgres que este repo ya arregló). Es
    # auto-sanador: el veredicto zombi no se muestra nunca más y no hay que limpiar
    # nada en la base. Un veredicto viejo, guardado antes de que existiera el campo,
    # no trae la clave: eso es "no sé qué evalué", y se muestra.
    if revision is not None and "apu_evaluado" in revision:
        if (revision["apu_evaluado"] or None) != (ens.apu_codigo or None):
            revision = None
        else:
            # El campo es del backend: al frontend le basta con no recibir el
            # veredicto descartado, así que no viaja (menos superficie de contrato).
            revision = {k: v for k, v in revision.items() if k != "apu_evaluado"}
    return {
        # Veredicto de la IA (o None si esa fila no se revisó). Default None para que
        # los llamadores del armado no tengan que pasarlo: ahí todavía no hay revisión.
        "revision": revision,
        "seq": seq, "item": ens.item.item, "descripcion": ens.item.descripcion,
        "unidad": ens.unidad, "cantidad": ens.item.cantidad,
        "apu_codigo": ens.apu_codigo, "apu_nombre": ens.apu_nombre,
        "status": status, "confianza": round(ens.confianza, 4),
        "precio_contractual": ens.item.precio_contractual,
        # --- ruta IDU: capítulo y la segunda base del contractual ----------------
        # Vacíos en una corrida plana; el frontend esconde la columna cuando lo están.
        "capitulo_codigo": ens.item.capitulo_codigo,
        "capitulo_nombre": ens.item.capitulo_nombre,
        "item_pago_original": ens.item.item_pago_original,
        "precio_contractual_sin_aiu": ens.item.precio_contractual_sin_aiu,
        "contractual_total_sin_aiu": ens.contractual_total_sin_aiu,
        "costo_unitario": ens.costo_unitario, "margen_unitario": ens.margen_unitario,
        "costo_manual": ens.costo_a_mano,
        "margen_pct": ens.margen_pct, "contractual_total": ens.contractual_total,
        "costo_total": ens.costo_total, "margen_total": ens.margen_total,
        "alertas_costeo": alertas_costeo(ens),
    }


def _ensamblar_corrida(alm: Almacen, meta, rows, pricing: PricingEngine,
                       snaps: Optional[dict] = None) -> list[AssembledApu]:
    """Ensambla los ítems de una corrida respetando el modo: congelada -> snapshot por
    ítem (con caída a costeo en vivo si falta el snapshot); activa -> costeo en vivo.
    Camino ÚNICO compartido por vista_corrida y listar_corridas. Cada AssembledApu ya
    trae sus pendientes de distancia (sin_distancia/en_subapus, ver `_costear_row` y
    `_assembled_desde_snapshot`), así que el llamador no necesita tocar el motor ni
    los snapshots de nuevo.

    `snaps`: si el llamador ya los leyó (p.ej. para resolver el contexto congelado,
    ver `vista_corrida`), se reusan en vez de volver a consultarlos."""
    if meta.modo == "congelada":
        if snaps is None:
            snaps = alm.corridas.get_snapshots(meta.id)
        return [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                else _costear_row(alm, r, pricing, meta.lista_precios_id) for r in rows]
    return [_costear_row(alm, r, pricing, meta.lista_precios_id) for r in rows]


def _totales(ensambles: list[AssembledApu], rows) -> dict:
    """Totales de una corrida (fórmula única). margen_pct es AGREGADO."""
    tot_c = sum(e.contractual_total for e in ensambles)
    tot_k = sum(e.costo_total for e in ensambles)
    n_rev = sum(1 for r in rows if r.status in ("review", "new"))
    return {"contractual": tot_c, "costo": tot_k, "margen": tot_c - tot_k,
            "margen_pct": ((tot_c - tot_k) / tot_c) if tot_c else 0.0,
            "n_items": len(rows), "n_revision": n_rev,
            "n_alertas_costeo": sum(1 for e in ensambles if alertas_costeo(e))}


# Cuántas líneas tenía el plan de cada corrida, contadas UNA vez por proceso:
# {repo de corridas: {(id, creada_en): total}}.
#
# `vista_corrida` se llama en cada poll de la pantalla (cada 5 s) y el plan de una
# licitación de 1900 ítems pesa ~400 KB: traerlo entero para contar sus elementos es el
# mismo trabajo con la misma respuesta, porque el plan se escribe al crear la corrida y
# NO vuelve a cambiar (agregar o borrar líneas está prohibido mientras el plan esté a
# medias, ver `_plan_a_medias`).
#
# Va colgado del repo de corridas y no en un dict por id: los tests (y una máquina con
# varias bases) tienen muchos `Almacen` distintos, y SQLite REUSA el id de la última
# corrida borrada. `creada_en` está en la clave por lo mismo, dentro de una base. Y
# `WeakKeyDictionary` se limpia sola cuando el Almacen muere, así que esto no crece.
_TOTAL_PLAN: "WeakKeyDictionary[object, dict[tuple[int, str], int]]" = WeakKeyDictionary()


def _total_del_plan(alm: Almacen, meta: CorridaMeta, hechos: int) -> int:
    """Cuántas líneas hay que armar. Sale del PLAN y no de las filas: durante el
    armado, las filas son justo las que faltan contar."""
    memo = _TOTAL_PLAN.setdefault(alm.corridas, {})
    clave = (meta.id, meta.creada_en)
    if clave not in memo:
        crudo = alm.corridas.get_plan(meta.id)
        if not crudo:
            # Sin plan no hay total que saber (corrida anterior a esta feature, o
            # muerta entre `crear_corrida` y `set_plan`). No se memoriza: `hechos` es
            # de hoy, no del plan.
            return hechos
        memo[clave] = len(json.loads(crudo))
    return memo[clave]


def _progreso_armado(alm: Almacen, meta: CorridaMeta, hechos: int) -> Optional[dict]:
    """Cómo va el armado, o None cuando la corrida ya terminó de armarse: ahí la
    pantalla no muestra nada (un progreso al 100 % que no se apaga es peor que nada).

    `posicion_en_cola` y `ultimo_error` son lo que explica una corrida que no avanza:
    está esperando su turno, o se rindió y hay que reanudarla a mano."""
    if meta.estado not in ARMANDO_O_A_MEDIAS:
        return None
    return {"hechos": hechos, "total": _total_del_plan(alm, meta, hechos),
            "posicion_en_cola": alm.corridas.posicion_en_cola(meta.id),
            "intentos": meta.intentos, "ultimo_error": meta.ultimo_error}


def vista_corrida(alm: Almacen, corrida_id: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    # Congelada: costear y mostrar con los parámetros CON LOS QUE SE CONGELÓ, no
    # los de hoy — si no, el encabezado ("transporte") contradice al cuadro y a la
    # propia composición ya fija del snapshot. Retrocompatible: una foto vieja sin
    # esa clave cae a `_contexto` en vivo (comportamiento de siempre).
    snaps = alm.corridas.get_snapshots(corrida_id) if meta.modo == "congelada" else {}
    ctx = _contexto_al_congelar(snaps) or _contexto(alm, meta)
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                            contexto=ctx)   # COMPARTIDO por la corrida
    pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)  # lote
    ensambles = _ensamblar_corrida(alm, meta, rows, pricing, snaps)
    items = [_vista_item(ens, r.seq, r.status, r.revision)
             for ens, r in zip(ensambles, rows)]
    return {
        "id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
        "estado": meta.estado, "modo": meta.modo,
        "carpeta_id": meta.carpeta_id,
        # Con qué distancias se está costeando: el encabezado de la corrida lo muestra.
        "transporte": (None if ctx.params.vacio else {
            "km_botadero": ctx.params.km_botadero,
            "km_mezclas": ctx.params.km_mezclas,
            "km_granulares": ctx.params.km_granulares,
            "peaje_botadero_aplica": ctx.params.peaje_botadero_aplica,
            "peaje_botadero_valor": ctx.params.peaje_botadero_valor,
            "peaje_mezclas_aplica": ctx.params.peaje_mezclas_aplica,
            "peaje_mezclas_valor": ctx.params.peaje_mezclas_valor,
            "peaje_granulares_aplica": ctx.params.peaje_granulares_aplica,
            "peaje_granulares_valor": ctx.params.peaje_granulares_valor,
            "ajustes": len(ctx.ajustes)}),
        "lista_precios_id": meta.lista_precios_id,
        "lista_nombre": _nombre_lista(alm, meta.lista_precios_id),
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": _totales(ensambles, rows),
        # Resumen por capítulo, calculado por la ÚNICA función que lo hace
        # (dominio/report_categorizado.resumen_por_capitulo). El frontend solo pinta:
        # no suma dinero. `[]` cuando la corrida no tiene capítulos.
        "capitulos": (resumen_por_capitulo(ensambles)
                      if any(e.item.capitulo_codigo for e in ensambles) else []),
        # De dónde salió el presupuesto. None en corridas anteriores a la ruta IDU:
        # la pantalla lo muestra como "sin clasificación por capítulo".
        "origen": meta.origen,
        # Cómo va el armado que corre en el servidor (None si ya terminó). La pantalla
        # ya pide esta vista, así que el progreso no necesita endpoint propio.
        "armado": _progreso_armado(alm, meta, len(rows)),
        # Para que el botón "Revisar con IA" se apague solo donde no hay clave. Va
        # acá y no solo en /api/status (que ya trae el mismo booleano como `ia`)
        # porque la página de corrida pide esta vista y no /status.
        "ia_disponible": config.ai_available(),
    }


def detalle_item(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(corrida_id)
        ens = (_assembled_desde_snapshot(row, snaps[seq]) if seq in snaps
               else _costear_row(alm, row, None, meta.lista_precios_id, _contexto(alm, meta)))
    else:
        ens = _costear_row(alm, row, None, meta.lista_precios_id, _contexto(alm, meta))
    return {
        "seq": row.seq, "descripcion": row.item.descripcion,
        "apu_codigo": row.apu_codigo, "apu_nombre": row.apu_nombre,
        # turno del APU asignado: lo necesita "duplicar este APU y usarlo aquí"
        # para leer el APU de origen de la biblioteca (la identidad es código+turno).
        "apu_turno": row.shift,
        # El código que pedía el presupuesto (ruta IDU) y la unidad del ítem: los usa
        # "Armar APU" para precargar el alta desde la fila. Si ese APU existiera en la
        # biblioteca el armado ya lo habría asignado, así que cuando la fila no lo tiene,
        # este es el código que el APU nuevo debería llevar. "" en una corrida plana.
        #
        # La unidad es la del ÍTEM, no `row.unidad`: esa es la del APU asignado (la pone
        # `_build` en assemble.py), y un APU nuevo se arma para la ACTIVIDAD. Si la fila
        # trae un APU en M2 y la licitación pide M3, el que manda es M3.
        "codigo_sugerido": row.item.codigo_sugerido,
        "unidad": row.item.unidad,
        "status": row.status, "explicacion": row.explicacion,
        "candidatos": row.candidatos,
        "composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce}
            for c in ens.componentes],
        "costo_unitario": ens.costo_unitario,
        "costo_manual": ens.costo_a_mano,
    }


def _exigir_armado_completo(alm: Almacen, meta, filas: int) -> None:
    """Traba congelar/emitir mientras el plan no esté armado entero.

    NO alcanza con `seqs_sin_apu`: ese candado mira las filas que EXISTEN, y las que
    el worker todavía no armó no existen. Sin esto, una corrida a medio armar emite
    un cuadro que se ve completo.
    """
    if not _plan_a_medias(meta):
        return
    crudo = alm.corridas.get_plan(meta.id)
    total = len(json.loads(crudo)) if crudo else filas
    raise ArmadoIncompleto(meta.id, filas, total)


def congelar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Fija una foto inmutable: costea la vista ACTIVA ahora y guarda el snapshot de
    cada ítem; luego marca modo='congelada'. Idempotente (recongelar = foto nueva)."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    _rows = alm.corridas.get_items(corrida_id)
    _exigir_armado_completo(alm, meta, len(_rows))
    faltan = seqs_sin_apu(_rows)
    if faltan:
        raise FilasSinApu(corrida_id, faltan)
    ctx = _contexto(alm, meta)
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                            contexto=ctx)   # COMPARTIDO al congelar
    pricing.precargar((r.apu_codigo, r.shift) for r in _rows if r.apu_codigo)
    # Con qué parámetros/ajustes se congela: van CON cada foto (redundante entre
    # ítems, pero son de la CORRIDA, no del ítem, y no hay tabla a nivel de corrida)
    # para que un cuadro/vista regenerados después no mezclen esta foto con las
    # distancias de HOY (ver `_contexto_al_congelar`).
    ctx_congelado = {"parametros": asdict(ctx.params),
                     "ajustes": [asdict(a) for a in ctx.ajustes]}
    for r in _rows:
        ens = _costear_row(alm, r, pricing)
        payload = {"composicion": [{
            "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
            "unidad": c.unidad, "rendimiento": c.rendimiento,
            "precio_unitario": c.precio_unitario, "fuente_precio": c.fuente_precio,
            "costo": c.costo, "calidad_cruce": c.calidad_cruce} for c in ens.componentes],
            "costo_unitario": ens.costo_unitario,
            # Se guardan CON la foto: sin esto, `generar_cuadro` (que congela antes de
            # armar el cuadro) perdería la alerta justo en el entregable — el snapshot
            # solo tenía composición+costo, y la re-lectura desde ahí no traía de
            # vuelta los pendientes calculados arriba.
            "sin_distancia": ens.sin_distancia, "en_subapus": ens.en_subapus,
            **ctx_congelado}
        alm.corridas.set_snapshot(corrida_id, r.seq, payload)
    alm.corridas.set_modo(corrida_id, "congelada")
    return vista_corrida(alm, corrida_id)


def activar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Vuelve la corrida a seguir la biblioteca. El snapshot queda pero se ignora."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    alm.corridas.set_modo(corrida_id, "activa")
    return vista_corrida(alm, corrida_id)


def renombrar_corrida(alm: Almacen, corrida_id: int, nombre: str) -> Optional[dict]:
    """Cambia el alias de una corrida. Devuelve la vista; None si no existe.
    Lanza ValueError si el nombre queda vacío. Permitido aun si está congelada
    (el nombre es etiqueta, no forma parte del snapshot)."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    limpio = (nombre or "").strip()[:120].strip()
    if not limpio:
        raise ValueError("El nombre no puede estar vacío.")
    alm.corridas.set_nombre(corrida_id, limpio)
    return vista_corrida(alm, corrida_id)


def confirmar_items(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                    apu_codigo: Optional[str] = None,
                    shift: Optional[str] = None,
                    asignaciones: Optional[dict[int, tuple[str, Optional[str]]]] = None,
                    ) -> Optional[dict]:
    """Confirma varios ítems de una corrida en UN solo recosteo.

    `apu_codigo=None` confirma el APU que cada ítem ya tiene (sin reasignar);
    con `apu_codigo` se le asigna ese APU (codigo+turno) a todos los seqs.

    `asignaciones` (seq -> (código, turno)) aplica un APU DISTINTO por fila en un
    solo recosteo: es lo que usa "aplicar N sugerencias de la IA". Cuando se pasa,
    los seq salen de ahí y `seqs` se ignora. Gana sobre `apu_codigo` fila por fila.

    Devuelve la vista de la corrida, o None si la corrida no existe, o si
    ninguno de los seqs pedidos existe en ella (pedir una lista vacía no
    cuenta: ahí no se pidió ningún seq inexistente, se pidió nada).

    Es la primitiva: `confirmar_item` es el caso de un solo seq. Un solo
    Assembler para todo el lote (su PricingEngine cachea, y el camino de
    confirmar no toca matcher/retriever, que son perezosos), y un solo
    vista_corrida al final en vez de uno por ítem.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id, contexto=_contexto(alm, meta))
    seqs_pedidos = list(seqs)   # Iterable: consumirlo dos veces no es seguro
    if asignaciones:
        seqs_pedidos = list(asignaciones)
    # Dos pasadas. La primera resuelve (fila, código, turno) y valida que el APU
    # exista, SIN escribir: con un código que no existe, reassemble_with_choice
    # produce una composición vacía y el ítem queda costeado en $0 (regla de
    # negocio: nada en $0 en silencio). Validando antes, un código inválido falla
    # sin dejar el lote a medio aplicar.
    # El turno se resuelve POR FILA (`shift or row.shift`): confirmar sin turno es
    # un camino real y usado — el botón "Elegir" de los candidatos y "Confirmar APU
    # actual" llaman sin él —, así que no se puede exigir.
    trabajo: list[tuple[int, CorridaItemRow, str, str]] = []
    validados: set[tuple[str, str]] = set()
    encontrados = 0
    # Una sola consulta para toda la corrida (get_items, no get_item por seq): con
    # Postgres lo caro es la latencia del viaje, no el tamaño del payload, y este
    # dict evita pagar un round trip por fila marcada (era el N+1 que esta feature
    # existe para evitar).
    filas_por_seq = {r.seq: r for r in alm.corridas.get_items(corrida_id)}
    for seq in seqs_pedidos:
        row = filas_por_seq.get(seq)
        if row is None:
            continue                      # seq ajeno a la corrida: se saltea
        encontrados += 1
        propuesto = (asignaciones or {}).get(seq)
        codigo = (propuesto[0] if propuesto else (apu_codigo or row.apu_codigo))
        if not codigo:
            continue                      # nada que confirmar (evita el $0)
        turno = (propuesto[1] if propuesto and propuesto[1] else shift) or row.shift
        if (codigo, turno) not in validados:
            # Turno EXACTO a propósito, más estricto que el fallback de `_build`
            # (assemble.py), que si el código existe con OTRO turno cae a ese turno
            # en silencio. Ese autocorregido silencioso es justo la clase de sorpresa
            # que "nada en $0" quiere evitar: costear con el turno equivocado sin que
            # nadie se entere. Acá se prefiere fallar y que el usuario mande el turno
            # correcto.
            if alm.apus.get_apu(codigo, turno) is None:
                raise ValueError(f"Fila {seq}: no existe el APU {codigo} ({turno}).")
            validados.add((codigo, turno))   # una consulta por par distinto, no por fila
        trabajo.append((seq, row, codigo, turno))
    # Ningún seq de los pedidos existe: no hay nada que informar y el llamador
    # pidió algo que no está. Devolver None deja que el endpoint conteste 404,
    # que es lo que confirmar_item hizo siempre para un seq inexistente. Con la
    # lista vacía no aplica: pedir nada no es pedir algo que no existe.
    if seqs_pedidos and encontrados == 0:
        return None
    for seq, row, codigo, turno in trabajo:
        ens = assembler.reassemble_with_choice(row.item, codigo, turno)
        alm.corridas.actualizar_eleccion(
            corrida_id, seq, status=MatchStatus.CONFIRMED.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift, origen=ens.origen,
            confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes))
    return vista_corrida(alm, corrida_id)


def confirmar_item(alm: Almacen, corrida_id: int, seq: int, apu_codigo: str,
                   shift: Optional[str] = None) -> Optional[dict]:
    """Un solo ítem. Wrapper sobre `confirmar_items` para que confirmar-uno y
    confirmar-muchos no se puedan separar con el tiempo. `confirmar_items`
    devuelve None cuando ese seq no existe en la corrida (además de cuando la
    corrida no existe), así que el 404 del endpoint sale gratis del lote."""
    return confirmar_items(alm, corrida_id, [seq], apu_codigo, shift or None)


def _propuestas_rebusqueda(alm: Almacen, meta, rows, solo_seqs=None):
    """Re-corre el matcher del armado sobre las filas NO confirmadas y devuelve
    `(propuestas, candidatos_frescos, escaneadas)`.

    `propuestas` es [(fila, ensamble propuesto ya costeado)]: solo las filas cuyo APU
    cambiaría. `candidatos_frescos` es {seq: [candidato…]} de TODAS las escaneadas (lo
    usa `aplicar_rebusqueda` para refrescar la lista que se ve al desplegar una fila).

    Es el camino ÚNICO: `rebuscar` lo muestra y `aplicar_rebusqueda` lo recalcula y
    escribe, así que la previa y lo que se aplica no se pueden separar con el tiempo.

    Dos fases a propósito. La primera solo matchea (0.2 ms por fila con
    `escaneo_completo=False`); la segunda costea, que es lo caro, y corre solo sobre
    las pocas filas que cambiarían. Costear las 1939 sería el armado otra vez.

    `solo_seqs`: si se pasa, recorta lo que se COSTEA (Fase 2) a esos seq. La Fase 1
    corre igual sobre toda la corrida —los candidatos frescos son de todas las filas
    escaneadas, y hay un test que lo exige—; lo que se recorta es solo el costeo, que
    es la parte cara. `aplicar_rebusqueda` lo usa para no pagar el costeo de las
    candidatas que el usuario no marcó; `rebuscar` no lo pasa, porque la previa tiene
    que mostrar todo.
    """
    indice = alm.apus.apu_index()
    matcher = Matcher(indice)
    codigos = {c for c, _n, _s in indice}
    # Pares (código, turno) que existen HOY en la biblioteca. Sirve para el tamiz de
    # Fase 1 (Arreglo 1) y para acertarle al turno del precargado (Arreglo 2).
    pares = {(c, s) for c, _n, s in indice}
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id)

    # Fase 1: matchear y pre-filtrar por (código, turno). El turno definitivo lo
    # decide `_build` (puede caer a otro si el APU no existe en el del ítem), así que
    # esta comparación es solo un tamiz: el filtro de verdad va después de costear.
    pendientes = []
    candidatos: dict[int, list[dict]] = {}
    escaneadas = 0
    for r in rows:
        if r.status == MatchStatus.CONFIRMED.value:
            continue          # lo resolvió una persona; el re-match no lo pisa
        escaneadas += 1
        result = matcher.match(r.item, escaneo_completo=False)
        candidatos[r.seq] = [{"apu_codigo": c.apu_codigo, "apu_nombre": c.apu_nombre,
                              "score": c.score, "motivo": c.motivo}
                             for c in result.candidatos]
        # Misma regla que `assemble_item`: el código del presupuesto manda sobre el
        # matcher. Una sola regla, no dos que se puedan separar.
        if r.item.codigo_sugerido and r.item.codigo_sugerido in codigos:
            propuesto = r.item.codigo_sugerido
        elif result.status == MatchStatus.AUTO and result.elegido:
            propuesto = result.elegido.apu_codigo
        elif result.status == MatchStatus.REVIEW and result.candidatos:
            propuesto = result.candidatos[0].apu_codigo
        else:
            continue          # nada asignable: la fila se queda como está
        # "Es lo mismo" solo si el par que la fila tiene hoy TODAVÍA existe en la
        # biblioteca. Si alguien borró justo esa variante de turno, el par ya no está
        # en `pares` y "es lo mismo" es mentira: `_build` va a caer al turno gemelo, así
        # que la fila tiene que llegar a la Fase 2, que decide con el resultado real
        # ya costeado (Arreglo 1).
        if ((propuesto, r.item.shift) == (r.apu_codigo, r.shift)
                and (r.apu_codigo, r.shift) in pares):
            continue
        pendientes.append((r, result, propuesto))

    if solo_seqs is not None:
        marcados = set(solo_seqs)
        pendientes = [t for t in pendientes if t[0].seq in marcados]

    def _turno_probable(cod: str, pedido: str) -> str:
        """El turno con el que `_build` va a costear: el pedido si existe, si no el
        gemelo. Solo para acertarle al precargado — si erra, el costeo igual sale
        bien (`precargar` es fail-safe), solo se paga una consulta de más."""
        if (cod, pedido) in pares:
            return pedido
        return next((s for c, _n, s in indice if c == cod), pedido)

    # Fase 2: costear solo las candidatas, con el motor compartido y precarga en lote
    # (el patrón que bajó 540 round-trips a 2 al abrir una corrida).
    # ponytail: `_build` llama `alm.apus.get_apu(...)` UNA VEZ POR FILA y eso no lo
    # cubre ningún precargado, así que aplicar cientos de filas de una paga cientos de
    # round-trips. La salida, si algún día molesta, es batchear `get_apu` en el
    # `Assembler`, no acá.
    assembler.pricing.precargar((cod, _turno_probable(cod, r.item.shift))
                                for r, _res, cod in pendientes)
    propuestas = []
    for r, result, _cod in pendientes:
        ens = assembler.assemble_item(r.item, result)
        if (ens.apu_codigo, ens.shift) == (r.apu_codigo, r.shift):
            continue          # el turno cayó al mismo lugar: no cambia nada
        if not ens.apu_codigo:
            continue          # `assemble_item` no encontró nada: no se propone vacío
        propuestas.append((r, ens))
    return propuestas, candidatos, escaneadas


# Estados de un expediente de composición que significan "hay trabajo humano vivo
# acá". `aprobada` ya se convirtió en APU y `rechazada` se descartó a propósito;
# `error` es una generación que reventó, no un borrador. Salen de
# `dominio/composicion.py::ESTADOS`.
COMPOSICION_EN_CURSO = ("generando", "propuesta", "editada")


def _vista_propuesta(row: CorridaItemRow, ens: AssembledApu,
                     con_composicion: set[int]) -> dict:
    """Una línea de la vista previa. El costo y el margen los calcula el backend:
    el frontend no suma plata."""
    return {
        "seq": row.seq, "item": row.item.item, "descripcion": row.item.descripcion,
        "unidad": ens.unidad, "cantidad": row.item.cantidad,
        "apu_actual": ({"codigo": row.apu_codigo, "nombre": row.apu_nombre}
                       if row.apu_codigo else None),
        "apu_propuesto": {"codigo": ens.apu_codigo, "nombre": ens.apu_nombre,
                          "turno": ens.shift},
        "score": round(ens.confianza, 4), "status": ens.status.value,
        "explicacion": ens.explicacion,
        "precio_contractual": row.item.precio_contractual,
        "costo_unitario": ens.costo_unitario,
        "margen_unitario": ens.margen_unitario, "margen_pct": ens.margen_pct,
        # La previa marca sola las filas que están en $0... salvo que tengan una
        # composición a medias: ahí hay trabajo humano que aplicar dejaría huérfano
        # (la fila pasa a tener APU y el botón "Componer" desaparece de la tabla).
        # La decisión la toma el backend, el frontend solo obedece el booleano.
        "marcar_por_defecto": row.apu_codigo is None and row.seq not in con_composicion,
        "composicion_pendiente": row.seq in con_composicion,
    }


def _exigir_rebuscable(alm: Almacen, corrida_id: int):
    """Los candados compartidos por `rebuscar` y `aplicar_rebusqueda`. Devuelve la
    meta, o None si la corrida no existe."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    if _plan_a_medias(meta):
        # Mientras el armador no termine, el espacio de seq es suyo y las filas que
        # faltan no existen: re-buscar ahora mira media corrida.
        raise ValueError(_MSG_PLAN_A_MEDIAS.format(accion="volver a buscar APU de"))
    return meta


def rebuscar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Qué cambiaría si se volviera a matchear la corrida contra la biblioteca de hoy.

    NO escribe nada: propone. Devuelve None si la corrida no existe.
    """
    meta = _exigir_rebuscable(alm, corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    propuestas, _candidatos, escaneadas = _propuestas_rebusqueda(alm, meta, rows)
    con_composicion = {seq for seq, estado
                       in alm.composiciones.estados_vigentes(corrida_id).items()
                       if estado in COMPOSICION_EN_CURSO}
    return {
        "corrida_id": corrida_id,
        "escaneadas": escaneadas,
        "propuestas": [_vista_propuesta(r, e, con_composicion) for r, e in propuestas],
    }


def aplicar_rebusqueda(alm: Almacen, corrida_id: int,
                       seqs: Iterable[int]) -> Optional[dict]:
    """Aplica la re-búsqueda a los `seqs` marcados. Devuelve la vista de la corrida
    con `rebusqueda: {aplicadas, salteadas}`, o None si la corrida no existe.

    RECALCULA la propuesta acá adentro en vez de creerle al cliente: entre que se
    mostró la previa y se apretó Aplicar pueden haber pasado minutos y otro usuario
    puede haber reasignado la fila. Los seq cuya propuesta ya no está vigente se
    saltean y se informan. Es el mismo candado que `apu_evaluado` en la revisión.

    Escribe con `actualizar_eleccion` y NO con `confirmar_items`: ese camino pasa por
    `reassemble_with_choice`, que pisa `confianza` con 1.0 y `explicacion` con
    "Confirmado por el usuario". La fila tiene que quedar con el parecido y el motivo
    que dio el matcher, para que una asignación dudosa siga contando en «por revisar».
    """
    meta = _exigir_rebuscable(alm, corrida_id)
    if meta is None:
        return None
    seqs = list(seqs)   # Iterable: se usa acá abajo Y en `_propuestas_rebusqueda`
    rows = alm.corridas.get_items(corrida_id)
    propuestas, candidatos, _escaneadas = _propuestas_rebusqueda(
        alm, meta, rows, solo_seqs=seqs)
    vigentes = {r.seq: (r, e) for r, e in propuestas}
    aplicadas, salteadas = [], []
    for seq in dict.fromkeys(seqs):          # sin repetidos, en el orden que llegaron
        par = vigentes.get(seq)
        if par is None:
            salteadas.append(seq)
            continue
        _row, ens = par
        alm.corridas.actualizar_eleccion(
            corrida_id, seq, status=ens.status.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
            origen=ens.origen, confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes))
        aplicadas.append(seq)
    # Candidatos frescos: solo donde la lista cambió de verdad y no quedó vacía. Una
    # lista vacía es "no encontré nada", no "olvidá lo que sabías".
    previos = {r.seq: r.candidatos for r in rows}
    cambiados = {seq: c for seq, c in candidatos.items()
                 if c and c != previos.get(seq)}
    if cambiados:
        alm.corridas.set_candidatos(corrida_id, cambiados)
    vista = vista_corrida(alm, corrida_id)
    vista["rebusqueda"] = {"aplicadas": aplicadas, "salteadas": salteadas}
    return vista


def _exigir_editable(alm: Almacen, corrida_id: int, accion: str):
    """Los candados compartidos por igualar/quitar costo a mano: existe, no está
    congelada y el plan no está a medias. Mismo candado que `_exigir_rebuscable`
    (las filas que faltan armar no existen; decidir sobre ellas es mirar media
    corrida). Devuelve la meta, o None si la corrida no existe."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    if _plan_a_medias(meta):
        raise ValueError(_MSG_PLAN_A_MEDIAS.format(accion=accion))
    return meta


def igualar_costo_al_contractual(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                                 actor=None,
                                 umbral_contractual: Optional[float] = None
                                 ) -> Optional[dict]:
    """Copia el precio contractual de cada fila marcada como su costo unitario.

    Para proyectos especiales: actividades globales que valen lo que dice el contrato
    y a las que armarles el APU no paga. El margen de esas filas queda en 0 a
    propósito.

    Es una COPIA de una vez, no un vínculo vivo: si mañana cambia el contractual, el
    costo se queda donde estaba y aparece un margen ≠ 0 — visible, para que el usuario
    decida. Un costo que persiguiera al contractual escondería el cambio.

    Se deshace solo: `actualizar_eleccion` borra el `costo_manual` cuando la fila
    cambia de APU, así que armar el APU de verdad y asignarlo devuelve la fila al
    costeo normal sin ningún botón que acordarse de apretar.

    Devuelve la vista de la corrida con dos claves extra —`igualadas` y `rechazadas`
    (seqs con contractual ≤ 0, que no se tocan por la regla "nada en $0")— o None si
    la corrida no existe. Lanza CorridaCongelada si está congelada.

    `umbral_contractual` no cambia lo que se escribe: solo queda en la auditoría
    cuando el gesto vino del techo por línea (`igualar_por_umbral`).
    """
    meta = _exigir_editable(alm, corrida_id, "igualar el costo de")
    if meta is None:
        return None
    pedidos = {int(s) for s in seqs}
    filas = [r for r in alm.corridas.get_items(corrida_id) if r.seq in pedidos]
    costos: dict[int, float] = {}
    rechazadas: list[int] = []
    for r in filas:
        # `not (x > 0)` y NO `x <= 0`: con NaN, `nan <= 0` es False y el NaN se
        # colaría al costo, envenenando todos los totales de ahí para abajo.
        if not (r.item.precio_contractual > 0):
            rechazadas.append(r.seq)   # igualar a 0 es el $0 que la regla prohíbe
        else:
            costos[r.seq] = float(r.item.precio_contractual)
    if costos:
        with alm.transaccion("corridas") as conn:
            alm.corridas.set_costo_manual(corrida_id, costos, conn=conn)
            # Se audita como `precio.editar`, que ya se audita: una persona fijando
            # plata a mano. `antes` guarda el costo a mano previo (None la primera vez).
            registrar_auditoria(
                alm, conn, actor, "corrida.igualar_costo", "corrida", corrida_id,
                antes={"lineas": [{"seq": r.seq, "costo_manual": r.costo_manual}
                                  for r in filas if r.seq in costos]},
                despues={"lineas": [{"seq": s, "costo_manual": c}
                                    for s, c in sorted(costos.items())]},
                contexto={"rechazadas": sorted(rechazadas),
                          # Solo cuando el gesto vino de un techo: el registro tiene
                          # que decir con qué regla se aplicó.
                          **({} if umbral_contractual is None
                             else {"umbral_contractual": float(umbral_contractual)})})
        if meta.estado == "finalizada":
            alm.corridas.set_estado(corrida_id, "en_revision")   # el cuadro ya no dice la verdad
    vista = vista_corrida(alm, corrida_id)
    if vista is not None:
        vista["igualadas"] = sorted(costos)
        vista["rechazadas"] = sorted(rechazadas)
    return vista


def _candidata_umbral(item: dict) -> bool:
    """Una fila que el umbral puede igualar: está en $0 y el contrato sí la paga.

    Una fila SIN APU siempre cuesta $0, así que entra sola; una CON APU pero sin
    precios también, que es el otro caso que deja el cuadro trabado. `not (x > 0)` y
    no `x == 0` por el NaN, igual que en el resto del módulo.

    `item` es un ítem de `vista_corrida`, no una fila cruda: ahí `costo_manual` ya es
    el booleano derivado del ensamble y `costo_unitario` ya está costeado.
    """
    return (not item["costo_manual"]
            and not (item["costo_unitario"] > 0)
            and item["precio_contractual"] > 0)


def igualar_por_umbral(alm: Almacen, corrida_id: int, umbral: float,
                       seqs: Iterable[int], actor=None) -> Optional[dict]:
    """Iguala al contractual las filas en $0 cuyo TOTAL contractual no pase el umbral.

    Para priorizar: en una licitación de 1939 actividades un puñado se lleva casi
    todo el presupuesto y la cola larga pesa centavos. Armarle el APU a cada una de
    esas cuesta semanas y no mueve la evaluación.

    El cliente manda los `seq` que marcó en la previa, pero la candidatura se
    RECALCULA acá: si entre la previa y el aplicar alguien le asignó un APU a una
    fila, se saltea. Es el mismo candado que `apu_evaluado` en la revisión y que
    `aplicar_rebusqueda` — el cliente dice cuáles quiere, no qué se escribe. Sin
    esto, una pestaña vieja pisaría un APU recién asignado con una copia del
    contractual, y encima dejaría la fila `confirmed`, o sea fuera del alcance de
    volver a buscar APU. Con diez filas eso se ve; con mil quinientas no.

    Cuesta dos costeos: uno para decidir la candidatura y otro para la vista que
    vuelve. Es una acción deliberada, no un render.

    Devuelve la vista con `igualadas`, `rechazadas` y `salteadas`, o None si la
    corrida no existe. Lanza CorridaCongelada si está congelada y ValueError si el
    umbral no es un monto positivo.

    Ojo con `rechazadas`: por ESTE camino viene siempre vacía. La trae el camino de
    escritura compartido (para el contractual ≤ 0), pero `_candidata_umbral` ya
    descartó esas filas hacia `salteadas` antes de llegar ahí. Quien consuma la
    respuesta tiene que mirar `salteadas`, no `rechazadas`.
    """
    meta = _exigir_editable(alm, corrida_id, "igualar el costo de")
    if meta is None:
        return None
    # `not (x > 0)` y NO `x <= 0`: con NaN, `nan <= 0` es False y el techo dejaría
    # pasar cualquier fila.
    if not (float(umbral) > 0):
        raise ValueError("El umbral tiene que ser un monto mayor que $0.")
    vista = vista_corrida(alm, corrida_id)
    if vista is None:
        return None
    pedidos = {int(s) for s in seqs}
    elegidas: list[int] = []
    salteadas: list[int] = []
    for it in vista["items"]:
        if it["seq"] not in pedidos:
            continue          # no se pidió: no se iguala y tampoco se reporta
        if _candidata_umbral(it) and it["contractual_total"] <= umbral:
            elegidas.append(it["seq"])
        else:
            salteadas.append(it["seq"])
    v = igualar_costo_al_contractual(alm, corrida_id, elegidas, actor,
                                     umbral_contractual=float(umbral))
    if v is not None:
        v["salteadas"] = sorted(salteadas)
    return v


def quitar_costo_manual(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                        actor=None) -> Optional[dict]:
    """Borra el costo puesto a mano de las filas marcadas y las devuelve al costeo.

    Es el reverso de `igualar_costo_al_contractual`, y existe porque el umbral puede
    tocar cientos de filas de un clic: sin vuelta atrás, un techo mal puesto se
    arregla fila por fila armando APUs que justamente no querías armar.

    Pedir el borrado de una fila que no tiene costo a mano no es un error: es un
    no-op y no se audita. Devuelve la vista de la corrida con `quitadas`, o None si
    la corrida no existe. Lanza CorridaCongelada si está congelada.
    """
    meta = _exigir_editable(alm, corrida_id, "quitar el costo puesto a mano de")
    if meta is None:
        return None
    pedidos = {int(s) for s in seqs}
    filas = [r for r in alm.corridas.get_items(corrida_id)
             if r.seq in pedidos and r.costo_manual is not None]
    if filas:
        with alm.transaccion("corridas") as conn:
            alm.corridas.limpiar_costo_manual(
                corrida_id, [r.seq for r in filas], conn=conn)
            registrar_auditoria(
                alm, conn, actor, "corrida.quitar_costo_manual", "corrida", corrida_id,
                antes={"lineas": [{"seq": r.seq, "costo_manual": r.costo_manual}
                                  for r in filas]},
                despues={"lineas": [{"seq": r.seq, "costo_manual": None}
                                    for r in filas]})
        if meta.estado == "finalizada":
            alm.corridas.set_estado(corrida_id, "en_revision")   # el cuadro ya no dice la verdad
    vista = vista_corrida(alm, corrida_id)
    if vista is not None:
        vista["quitadas"] = sorted(r.seq for r in filas)
    return vista


def revisar_corrida_stream(alm: Almacen, corrida_id: int):
    """Revisa una corrida ya armada. Devuelve None si la corrida no existe; el
    generador de eventos SSE si sí.

    Función normal (no generador) a propósito: validar acá y devolver el generador
    deja el 404 explícito en el endpoint, en vez de depender de que un `return` antes
    del primer `yield` se convierta en `StopIteration`.

    Si la revisión se interrumpe, los veredictos ya persistidos se quedan; pero
    re-correr revisa TODO de nuevo (el barrido necesita el índice de la corrida
    entera) y sobrescribe los veredictos previos: cuesta el precio completo.

    Lanza CorridaCongelada (una foto no se revisa) e IANoDisponible.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    # ponytail: dos revisiones simultáneas sobre la misma corrida se pisan (gana la
    # última). Los veredictos son por fila e idempotentes, así que el daño es gastar
    # dos veces, no corromper. Si molesta, el arreglo es un lock por corrida.
    revisor = Revisor()   # POR REQUEST: compartirlo mezclaría estado entre peticiones
    if not revisor.disponible:
        raise IANoDisponible(
            "La revisión con IA necesita ANTHROPIC_API_KEY en el servidor.")
    return _eventos_revision(alm, corrida_id, alm.corridas.get_items(corrida_id), revisor)


def _eventos_revision(alm: Almacen, corrida_id: int, filas, revisor):
    """Generador puro: corre el motor y persiste cada veredicto apenas sale.

    Eventos: los de `dominio.revision.revisar` (incluido el `barriendo` de cada lote
    del barrido, que va tal cual al stream para que no se quede mudo), más
    ('error', {'detail'}) si falta la IA. Cualquier OTRO fallo sube al `_event_stream`
    del endpoint, que lo loggea — en particular la PrivacyViolation, que
    `revision.barrer_lote` re-lanza a propósito y acá tampoco se traga (invariante #1).
    """
    try:
        for evento, payload in revisar(alm, filas, revisor):
            if evento == "veredicto":
                alm.corridas.set_revision(corrida_id, payload["seq"],
                                          payload["veredicto"])
            yield (evento, payload)
    except IANoDisponible as exc:
        # `Revisor.disponible` solo mira la env var: si el SDK no importa, la falta de
        # IA aparece acá, con el stream ya abierto. Mensaje accionable en vez del
        # "Error interno." genérico.
        yield ("error", {"detail": str(exc)})


def listar_corridas(alm: Almacen) -> list[dict]:
    out: list[dict] = []
    # Nombres de lista resueltos UNA vez para todas las corridas (no una consulta por
    # fila dentro del bucle): este listado ya sufrió round-trips N+1 contra Postgres
    # (precios/composición) y se arregló precargando en lote; el nombre de la lista
    # sigue la misma regla para no reintroducir el mismo patrón.
    nombres_lista = {l.id: l.nombre for l in alm.precios.listar_listas()}
    ctx_cache: dict = {}   # memo por carpeta: N corridas del mismo proyecto, un solo contexto
    for meta in alm.corridas.listar_corridas():
        rows = alm.corridas.get_items(meta.id)
        n_rev = sum(1 for it in rows if it.status in ("review", "new"))
        lista_nombre = ("Principal" if meta.lista_precios_id is None
                        else nombres_lista.get(meta.lista_precios_id, f"lista {meta.lista_precios_id}"))
        fila = {"id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
                "creada_en": meta.creada_en,
                "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                "carpeta_id": meta.carpeta_id,
                "lista_precios_id": meta.lista_precios_id,
                "lista_nombre": lista_nombre,
                "n_items": len(rows), "n_revision": n_rev,
                "contractual": None, "costo": None, "margen": None, "margen_pct": None}
        try:                                           # fail-safe: si una corrida no
            pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                                    contexto=_contexto(alm, meta, ctx_cache))   # costea, su fila queda con None
            pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)
            tot = _totales(_ensamblar_corrida(alm, meta, rows, pricing), rows)
            fila.update(contractual=tot["contractual"], costo=tot["costo"],
                        margen=tot["margen"], margen_pct=tot["margen_pct"])
        except Exception:
            pass
        out.append(fila)
    return out


def eliminar_corrida(alm: Almacen, corrida_id: int, actor=None) -> bool:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return False
    with alm.transaccion("corridas") as conn:
        ok = alm.corridas.eliminar_corrida(corrida_id, conn=conn)
        if ok:
            registrar_auditoria(
                alm, conn, actor, "corrida.eliminar", "corrida", corrida_id,
                antes={"archivo": meta.archivo, "creada_en": meta.creada_en, "estado": meta.estado},
                despues=None)
    return ok


def generar_cuadro(alm: Almacen, corrida_id: int) -> Optional[Path]:
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)   # una sola lectura: guard + cuadro
    _exigir_armado_completo(alm, meta, len(rows))
    # Chequeo propio, no basta con el de `congelar`: si la corrida ya está congelada
    # con foto, la llamada a `congelar` de abajo se saltea, y una corrida congelada
    # ANTES de este candado sí puede traer filas sin APU.
    faltan = seqs_sin_apu(rows)
    if faltan:
        raise FilasSinApu(corrida_id, faltan)
    config.ensure_dirs()
    snaps = alm.corridas.get_snapshots(corrida_id)
    # Si ya está congelada y tiene snapshots, respeta la foto emitida (no recongela);
    # si está activa (o congelada sin snapshots), congela el estado actual.
    if not (meta.modo == "congelada" and snaps):
        congelar(alm, corrida_id)
        snaps = alm.corridas.get_snapshots(corrida_id)
    # A esta altura la corrida está congelada CON foto (recién generada arriba, o
    # ya existía): el cuadro tiene que costear con esos parámetros, no con los de
    # hoy — si no, RESUMEN queda con los números de la foto y DESVIACIONES DEL
    # PROYECTO con las distancias de hoy, contradiciéndose en el mismo Excel.
    ctx = _contexto_al_congelar(snaps) or _contexto(alm, meta)
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id,
                            contexto=ctx)   # COMPARTIDO al generar el cuadro
    pricing.precargar((r.apu_codigo, r.shift) for r in rows
                      if r.apu_codigo and r.seq not in snaps)
    assembled = [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                 else _costear_row(alm, r, pricing) for r in rows]
    stamp = meta.creada_en.replace(":", "").replace("-", "").replace("T", "_")
    out = config.OUTPUT_DIR / f"cuadro_corrida_{corrida_id}_{stamp}.xlsx"
    write_report(assembled, out, lista_nombre=_nombre_lista(alm, meta.lista_precios_id),
                 parametros=ctx.params, ajustes=ctx.ajustes)
    alm.corridas.set_cuadro(corrida_id, str(out))
    alm.corridas.set_estado(corrida_id, "finalizada")
    return out
