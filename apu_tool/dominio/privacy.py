"""
Frontera de privacidad de precios.

Regla del negocio: la IA NUNCA debe ver valores monetarios (precios de insumos,
costos internos, totales). Solo puede ver actividades, insumos, unidades y
rendimientos para decidir la ESTRUCTURA de los APUs.

Este módulo construye los payloads que se envían a la IA y verifica, de forma
programática, que no traigan ninguna clave monetaria. Si algo se filtra,
`assert_no_money` levanta una excepción: preferimos fallar a filtrar. El chequeo
es por nombre de clave, NO por valor — ver la limitación en su docstring.
"""
from __future__ import annotations

import json
import math
import re
from typing import Any, Optional

from apu_tool.nucleo.models import DePricedApu, DePricedComponent, LicitacionItem

# Nombres de campo que jamás deben aparecer en un payload destinado a la IA.
_FORBIDDEN_KEYS = {
    "precio", "precio_unitario", "precio_contractual", "precio_unitario_hist",
    "costo", "costo_unitario", "costo_total", "valor", "valor_unitario",
    "valor_total", "margen", "price", "cost", "amount", "total",
    "fuente_precio", "costo_manual", "plan_json",
    # El techo en pesos con el que se igualan las líneas chicas al contractual. No se
    # persiste (vive en el request y en la auditoría), pero es un monto con nombre
    # propio. Se llama así y no `umbral` a secas para no chocar con los umbrales de
    # matching, que NO son dinero: un falso positivo ahí volaría un payload legítimo.
    "umbral_contractual",
    # Los valores del peaje de un proyecto son dinero, uno por categoría de acarreo.
    # `valor` ya está en la lista, pero el chequeo es por nombre EXACTO de clave.
    # Las casillas (`peaje_*_aplica`) NO entran: son booleanos, estructura.
    # `peaje_valor` se queda aunque el campo único ya no exista: la lista es de
    # nombres prohibidos y que un nombre muerto siga prohibido no cuesta nada.
    "peaje_valor",
    "peaje_botadero_valor", "peaje_mezclas_valor", "peaje_granulares_valor",
    # --- ruta IDU (Formulario 1) ------------------------------------------------
    # Las dos bases del contractual y sus multiplicaciones.
    "precio_contractual_sin_aiu", "contractual_total_sin_aiu",
    "contractual_con_aiu", "contractual_sin_aiu",
    "unitario_sin_aiu", "unitario_con_aiu",
    # Lo que el Excel del IDU trae y el parser concilia.
    "total_excel", "subtotales_excel", "conciliacion",
    # Las claves del dict de `report_categorizado.resumen_por_capitulo`. Hoy NINGÚN
    # camino las lleva hacia la IA (sus tres consumidores son la API HTTP y las dos
    # hojas de Excel), pero son dinero con nombre genérico: el día que alguien quiera
    # darle a la IA "contexto del capítulo" pasando ese dict, se filtrarían en silencio.
    # El resto de sus claves ya estaba cubierto por `costo`, `margen` y las de arriba.
    "contractual", "diferencia", "margen_pct", "cobertura_valor",
    # `origen_json` va por la MISMA razón que `plan_json`: lleva la conciliación
    # —o sea dinero— adentro, así que el objeto entero no puede cruzar la frontera.
    "origen_json",
    # Notas humanas de insumos/APUs: texto libre que puede llevar montos
    # («cotización a $45.000»). assert_no_money mira claves, no valores: prohibir la
    # clave es la única forma de que un payload con notas FALLE en vez de filtrarse.
    "nota", "notas", "ultima_nota",
}


def depriced_component_to_dict(c: DePricedComponent) -> dict[str, Any]:
    return {
        "insumo_codigo": c.insumo_codigo,
        "insumo_nombre": c.insumo_nombre,
        "unidad": c.unidad,
        "rendimiento": round(c.rendimiento, 6),
        "tipo": c.tipo,
    }


def depriced_apu_to_dict(apu: DePricedApu) -> dict[str, Any]:
    return {
        "codigo": apu.codigo,
        "nombre": apu.nombre,
        "unidad": apu.unidad,
        "shift": apu.shift,
        "grupo": apu.grupo,
        "componentes": [depriced_component_to_dict(c) for c in apu.componentes],
    }


def licitacion_item_to_dict(item: LicitacionItem) -> dict[str, Any]:
    """Versión SIN dinero de un ítem de licitación.

    Se arma clave por clave a propósito: un campo nuevo del dataclass NO se cuela solo
    por existir. Por eso no están `precio_contractual` ni `precio_contractual_sin_aiu`.

    El capítulo sí viaja: es texto y es estructura — saber que una actividad pertenece a
    RED DE ACUEDUCTO ayuda a componerla, y no dice nada de lo que cuesta.
    """
    return {
        "item": item.item,
        "descripcion": item.descripcion,
        "unidad": item.unidad,
        "cantidad": round(item.cantidad, 6),
        "shift": item.shift,
        "capitulo_codigo": item.capitulo_codigo,
        "capitulo_nombre": item.capitulo_nombre,
    }


def assert_no_money(payload: Any) -> None:
    """Valida recursivamente que `payload` no contenga campos monetarios.

    Levanta PrivacyViolation si encuentra una clave de `_FORBIDDEN_KEYS`.

    LIMITACIÓN REAL, léela antes de agregar un payload nuevo: el chequeo es por
    **nombre de clave**, no por valor. Un monto embebido en un string de texto
    libre — `{"comentario": "el m3 sale a $180.000"}` — pasa el guardián sin que salte
    nada, porque `comentario` no está en la denylist y nadie mira el contenido.

    De ahí la regla operativa: **nunca metas en un payload hacia la IA texto
    generado por el motor de costos** (mensajes de `alertas.py`, explicaciones de
    `pricing.py`, cualquier cadena armada donde se ve dinero). Manda campos
    estructurados con nombre propio, que sí son los que este chequeo cubre.
    """
    def walk(node: Any, path: str) -> None:
        if isinstance(node, dict):
            for k, v in node.items():
                key = str(k).strip().lower()
                if key in _FORBIDDEN_KEYS:
                    raise PrivacyViolation(
                        f"Campo monetario '{path}.{k}' destinado a la IA. "
                        f"La IA no puede ver precios."
                    )
                walk(v, f"{path}.{k}")
        elif isinstance(node, (list, tuple)):
            for i, v in enumerate(node):
                walk(v, f"{path}[{i}]")

    walk(payload, "payload")


def safe_json(payload: Any) -> str:
    """Serializa a JSON tras verificar que no hay dinero. Úsalo para todo lo que
    salga hacia la IA."""
    assert_no_money(payload)
    return json.dumps(payload, ensure_ascii=False, indent=2)


# --------------------------------------------------- texto libre (chat del agente)
# `assert_no_money` mira NOMBRES de clave. El chat de la mesa de composición es el
# primer payload hacia la IA armado con texto libre escrito por personas, así que los
# VALORES necesitan su propio detector. Preferimos fallar a filtrar: un falso positivo
# cuesta reescribir el mensaje; un falso negativo le muestra un precio a la IA.
#
# Lo que NO está, a propósito:
#   - "vale": en Colombia es "de acuerdo" ("vale, agrega 2 ayudantes"); "vale 3
#     millones" igual cae por "millones".
#   - "peso" en singular: es también peso físico ("peso específico 2,4 t/m3").
# Falsos positivos ACEPTADOS: "pon el valor en 0,5", "el rendimiento sale en 0,5". El
# motivo le dice a la persona cómo decirlo para que no salte.
_SENAL_MONEDA = re.compile(
    # Sin \b: "COP1200" y "1200COP" tienen la moneda pegada al número (los dígitos son
    # \w). El lookaround solo exige que no haya una LETRA al lado, así "copiar" pasa.
    r"\$|€|(?<![^\W\d_])(cop|usd|eur|euros?|pesos|d[oó]lares?|lucas)(?![^\W\d_])",
    re.IGNORECASE)
# Un número con separador de miles con punto ("45.000", "1.250.000") es dinero en este
# dominio: los rendimientos llevan coma decimal ("0,125"). La premisa de que las
# especificaciones van sin separador NO siempre se cumple: el catálogo real trae
# "PESO 60.000 KG". Ese falso positivo se acepta (preferimos fallar a filtrar) y el
# motivo le explica a la persona cómo escribirlo ("3000 psi"). Empieza en 1-9 para que
# "0.125" (decimal con punto) pase.
_MILES = re.compile(r"\b[1-9]\d{0,2}(?:\.\d{3})+\b")
# Miles con coma: solo con dos o más grupos ("1,250,000"). Con uno ("45,000") es
# ambiguo con el decimal ("0,125"), y ahí gana el decimal.
_MILES_COMA = re.compile(r"\b[1-9]\d{0,2}(?:,\d{3}){2,}\b")
# Los verbos de plata se listan conjugados y no como `cost\w*`: eso rompería "costal" y
# "costado". "costo" ya lo cubre `costos?`; que se repita en `cost(?:o…)` no estorba.
_RAIZ_DINERO = re.compile(
    r"(precios?|costos?|costar|cuesta|cuestan|cost(?:ó|o|aba|aban|ará|arán|aría|arían)|"
    r"val[ií]a|gast\w+|valor(es)?|tarifas?|cotiz\w*|"
    r"presupuest\w*|mill[oó]n|millones|mil|k|plata|cobra\w*|pag\w+|compr(?!es)\w+|"
    r"factur\w+|sale|sali[oó]|salen)", re.IGNORECASE)
# Palabras y números por separado: "precio:45000" y "45k" quedan como dos tokens. Con
# `split()` la palabra quedaba pegada al número y la raíz no casaba.
_TOKEN = re.compile(r"[^\W\d_]+|\d[\d.,]*")
_VENTANA_DINERO = 3        # tokens a cada lado de la raíz donde se busca un número


def _motivo_dinero(fragmento: str) -> str:
    frag = fragmento.strip()[:60]
    return (f"El mensaje parece traer un monto («{frag}»). La IA no puede ver "
            "precios: quítalo y vuelve a enviarlo. Si es una cantidad física, "
            "nómbrala así: «rendimiento 0,5», «8 horas». "
            "Para especificaciones, sin punto de miles: «3000 psi».")


def _alrededor(t: str, m: re.Match) -> str:
    return t[max(0, m.start() - 20):m.end() + 20]


def texto_con_dinero(texto: str) -> Optional[str]:
    """El motivo para bloquear `texto` si parece traer dinero, o None si no.

    Bloquea si hay un símbolo o una moneda (`$`, `€`, COP, USD, pesos…), un número con
    separador de miles con punto ("45.000"), o una palabra de dinero (precio, costo,
    valor, tarifa, cotiz-, pag-, sale, mil, k…) con un número a menos de
    `_VENTANA_DINERO` tokens. Deja pasar las cantidades físicas ("8 horas",
    "0,125 HH/m3"): sin palabra de dinero cerca, un número es un rendimiento.
    """
    t = texto or ""
    for patron in (_SENAL_MONEDA, _MILES, _MILES_COMA):
        m = patron.search(t)
        if m:
            return _motivo_dinero(_alrededor(t, m))
    tokens = _TOKEN.findall(t)
    for i, tok in enumerate(tokens):
        if not _RAIZ_DINERO.fullmatch(tok):
            continue
        vecinos = tokens[max(0, i - _VENTANA_DINERO): i + _VENTANA_DINERO + 1]
        if any(ch.isdigit() for v in vecinos for ch in v):
            return _motivo_dinero(" ".join(vecinos))
    return None


def rendimiento_observado_to_dict(o) -> dict[str, Any]:
    """Estadística de uso de un insumo en la biblioteca. Cantidades físicas, no dinero.

    Se copia clave por clave y no se delega en `o.to_dict()`: este es el borde hacia
    la IA, y un campo agregado al tipo del dominio no debe viajar solo por existir.
    """
    return {"insumo_codigo": o.insumo_codigo, "unidad": o.unidad, "n": o.n,
            "minimo": round(o.minimo, 6), "mediana": round(o.mediana, 6),
            "maximo": round(o.maximo, 6),
            # El modelo tiene que saber que el rango dejó filas afuera: si no, un
            # "n=35" sobre un insumo que también se usa en otra unidad le parece
            # evidencia más firme de la que es.
            "descartados_otra_unidad": o.descartados_otra_unidad}


def payload_composicion(item, insumos, ejemplos, observados) -> dict[str, Any]:
    """El payload de la composición asistida (dominio/composicion_agente.py).

    Se arma clave por clave a propósito, nunca volcando objetos en bloque: es lo que
    hace que el test de FORMA sirva de algo. Los APUs de referencia entran como
    `DePricedApu`, un tipo que estructuralmente no puede llevar dinero — la frontera
    está en el tipo, no en acordarse de filtrar campos.

    `observados` es un dict {codigo: RendimientoObservado}; se ordena por código para
    que dos llamadas con los mismos datos produzcan el mismo texto (el prompt es
    cacheable y los tests, comparables).
    """
    from apu_tool.dominio.compose import candidate_insumo_to_dict
    return {
        "actividad": licitacion_item_to_dict(item),
        "insumos_disponibles": [candidate_insumo_to_dict(i) for i in insumos],
        "apus_referencia": [depriced_apu_to_dict(a) for a in ejemplos],
        "rendimientos_observados": [rendimiento_observado_to_dict(observados[k])
                                    for k in sorted(observados)],
    }


def _rendimiento_o_none(v: Any) -> Optional[float]:
    try:
        x = float(v)
    except (TypeError, ValueError, OverflowError):
        return None
    return round(x, 6) if math.isfinite(x) else None


def componente_mesa_to_dict(c: dict, catalogo: dict) -> dict[str, Any]:
    """Un componente de la mesa tal como lo ve el agente del chat.

    Los componentes los manda el CLIENTE (la tabla tal como está en pantalla), así que
    se copian clave por clave y SOLO los campos estructurados. `justificacion` e
    `hipotesis` NO viajan: son texto libre que una persona pudo editar, y un monto
    adentro pasaría por `assert_no_money` sin que nada salte. Nombre y unidad salen del
    catálogo (`catalogo`, ya filtrado a nombre/unidad/grupo), no del cliente.
    `funcion` y `origen` solo viajan si son del vocabulario cerrado del contrato, y un
    `codigo` que dispare el detector de dinero viaja vacío.
    """
    # Import local, como hace `composicion._hipotesis_desde` en la otra dirección: el
    # contrato no depende de nada a nivel de módulo y así no hay ciclo posible.
    from apu_tool.dominio.composicion import FUNCIONES, ORIGENES
    cod = str(c.get("codigo", "") or "")[:40]
    if texto_con_dinero(cod):
        cod = ""
    info = catalogo.get(cod) or {}
    funcion = str(c.get("funcion", "") or "")
    origen = str(c.get("origen", "") or "")
    return {"codigo": cod, "nombre": info.get("nombre", ""),
            "unidad": info.get("unidad", ""),
            "funcion": funcion if funcion in FUNCIONES else "",
            "rendimiento": _rendimiento_o_none(c.get("rendimiento")),
            "origen": origen if origen in ORIGENES else ""}


def payload_chat(item, componentes: list, catalogo: dict) -> dict[str, Any]:
    """El contexto que acompaña cada mensaje del chat de composición: la actividad
    (sin `precio_contractual`) y la composición que la persona ve en pantalla."""
    return {"actividad": licitacion_item_to_dict(item),
            "composicion_actual": [componente_mesa_to_dict(c, catalogo)
                                   for c in componentes if isinstance(c, dict)]}


def insumo_encontrado_to_dict(ins, observado=None) -> dict[str, Any]:
    """Un resultado de `buscar_insumos`. `ins` es un `Insumo`, que LLEVA `precio` y
    `fuente_precio`: por eso se copia campo por campo y nunca se vuelca."""
    return {"insumo_codigo": ins.codigo, "insumo_nombre": ins.nombre,
            "unidad": ins.unidad, "grupo": ins.grupo,
            "rendimientos_observados": (rendimiento_observado_to_dict(observado)
                                        if observado is not None else None)}


# --------------------------------------------------------------- chat de consulta
# Un número pegado a "mil"/"millones". El lookahead exige que no siga una letra:
# así "3 milímetros" y "4 kg" pasan.
_CIFRA_MILES_PALABRA = re.compile(
    r"\d[\d.,]*\s*(?:mil(?:es)?|mill[oó]n(?:es)?)(?![^\W\d_])", re.IGNORECASE)


def cifra_monetaria(texto: str) -> Optional[str]:
    """El fragmento con un monto si `texto` trae uno escrito, o None.

    Más ANGOSTA que `texto_con_dinero` a propósito: solo señales fuertes (símbolo o
    moneda, separador de miles, número pegado a mil/millones). Se usa sobre el texto
    del AGENTE de consulta, que nombra proyectos con números al lado de palabras de
    dinero («el costo de la Calle 13: {{…}}»); ahí la ventana de `texto_con_dinero`
    omitiría casi toda respuesta. Un precio inventado se escribe con símbolo o con
    miles, y eso es lo que esto ataja. Los mensajes del USUARIO siguen pasando por
    `texto_con_dinero` completo.
    """
    t = texto or ""
    for patron in (_SENAL_MONEDA, _MILES, _MILES_COMA, _CIFRA_MILES_PALABRA):
        m = patron.search(t)
        if m:
            return _alrededor(t, m)
    return None


def insumo_consulta_to_dict(ins) -> dict[str, Any]:
    """Un resultado de `buscar_insumos` del chat de consulta. `ins` LLEVA precio: se
    copia campo por campo. El `ref` va por id porque 652 códigos son de dos insumos."""
    return {"ref": f"insumo:{ins.id}", "insumo_codigo": ins.codigo,
            "insumo_nombre": ins.nombre, "unidad": ins.unidad, "grupo": ins.grupo}


def apu_consulta_to_dict(codigo: str, nombre: str, turno: str) -> dict[str, Any]:
    return {"ref": f"apu:{codigo}|{turno}", "codigo": codigo, "nombre": nombre,
            "turno": turno}


def corrida_consulta_to_dict(meta, carpeta: Optional[str]) -> dict[str, Any]:
    """`meta` es un `CorridaMeta`; NO se vuelca (trae `plan_json`/`origen` con dinero)."""
    nombre = meta.nombre or str(meta.archivo).rsplit(".", 1)[0]
    # nombre y carpeta son texto libre de una persona: pueden traer un monto.
    if cifra_monetaria(nombre):
        nombre = f"corrida {meta.id}"
    if carpeta and cifra_monetaria(carpeta):
        carpeta = None
    return {"ref": f"corrida:{meta.id}", "nombre": nombre, "carpeta": carpeta,
            "estado": meta.estado, "modo": meta.modo}


def capitulo_consulta_to_dict(corrida_id: int, codigo: str, nombre: str,
                              actividades: int) -> dict[str, Any]:
    if cifra_monetaria(nombre):
        nombre = f"capítulo {codigo}"
    return {"ref": f"capitulo:{corrida_id}:{codigo}", "codigo": codigo,
            "nombre": nombre, "actividades": actividades}


def proyecto_consulta_to_dict(nombre: str, corridas: list,
                              encontradas: int) -> dict[str, Any]:
    if cifra_monetaria(nombre):
        nombre = "proyecto (nombre omitido)"
    return {"proyecto": nombre, "corridas": corridas, "corridas_encontradas": encontradas}


class PrivacyViolation(RuntimeError):
    """Se intentó enviar un valor monetario a la IA."""
