"""Gate de no-regresión para la optimización del matcher (etapa 2, sub-proyecto A).

La barra acordada: para TODO ítem, el matcher optimizado debe dar el mismo estado
(AUTO/REVISAR/NUEVO), el mismo `elegido` (AUTO) y el mismo `candidatos[0]` (la base
que usa el fallback determinista de assemble_item) que el matcher de hoy. La cola de
candidatos de baja puntuación puede variar.

La referencia es un escaneo completo del pool con la MISMA función `similarity`
(que no cambia), replicando la lógica actual de `candidates()`/`match()`. Así el
gate no depende del historial de git: compara el Matcher real contra esa referencia.
"""
from apu_tool import config
from apu_tool.dominio import matching
from apu_tool.dominio.matching import Matcher
from apu_tool.nucleo.models import LicitacionItem, MatchStatus


# --- catálogo de prueba: nombres realistas de obra civil, dos turnos -----------
_APUS = [
    ("3007", "REPLANTEO GENERAL", "DIURNO"),
    ("3009", "EXCAVACION MANUAL PARA REDES PROFUNDIDAD 0M A 2M", "DIURNO"),
    ("3010", "DEMOLICION PAVIMENTO ASFALTICO INCLUYE CARGUE", "DIURNO"),
    ("3011", "DEMOLICION MANUAL SARDINEL EXISTENTE INCLUYE CARGUE", "DIURNO"),
    ("3012", "DEMOLICION PISOS DE CONCRETO ESPESOR VARIABLE", "DIURNO"),
    ("3020", "CONCRETO CLASE D PARA ESTRUCTURAS", "DIURNO"),
    ("3021", "CONCRETO CLASE E PARA SARDINELES", "DIURNO"),
    ("3030", "SUBBASE GRANULAR SBG SUMINISTRO EXTENDIDO Y COMPACTACION", "DIURNO"),
    ("3031", "BASE GRANULAR BG SUMINISTRO EXTENDIDO Y COMPACTACION", "DIURNO"),
    ("3040", "MEZCLA ASFALTICA EN CALIENTE TIPO DENSO MD10", "DIURNO"),
    ("3050", "TUBERIA PVC SANITARIA D 2 PULGADAS INCLUYE INSTALACION", "DIURNO"),
    ("3051", "TUBERIA PVC ALCANTARILLADO D 12 PULGADAS", "DIURNO"),
    ("3060", "SUMINISTRO E INSTALACION DE SARDINEL PREFABRICADO A10", "DIURNO"),
    ("3061", "PISOS EN LOSETA PREFABRICADA TACTIL ALERTA", "DIURNO"),
    ("3070", "EXCAVACION MECANICA EN MATERIAL COMUN INCLUYE CARGUE", "DIURNO"),
    ("3071", "RELLENO PARA REDES EN ARENA DE PEÑA", "DIURNO"),
    ("3080", "DEMARCACION LINEA DE TRAFICO PINTURA TERMOPLASTICA", "DIURNO"),
    ("3081", "SEÑAL VERTICAL DE PEDESTAL INCLUYE CIMENTACION", "DIURNO"),
    ("3090", "TALA DE ARBOLES ENTRE 10M A 20M DE ALTURA", "DIURNO"),
    ("3091", "TRATAMIENTO INTEGRAL DE ARBOLES DE 1M A 5M", "DIURNO"),
    ("3100", "ENCHAPE DE PISO Y PARED EN CERAMICA 30X30", "DIURNO"),
    ("3110", "CAJA DE INSPECCION TRIPLE PARA CANALIZACION", "DIURNO"),
    ("4007", "REPLANTEO GENERAL", "NOCTURNO"),
    ("4040", "MEZCLA ASFALTICA EN CALIENTE TIPO DENSO MD10", "NOCTURNO"),
    ("4050", "TUBERIA PVC SANITARIA D 2 PULGADAS INCLUYE INSTALACION", "NOCTURNO"),
]


def _ref_scored(descripcion, shift, top_n=5):
    """Réplica de la lógica ACTUAL de Matcher.candidates: escaneo completo del pool
    del turno (con fallback a todos los turnos) usando `similarity`, score>0,
    orden desc estable, top_n. Devuelve [(codigo, score), ...]."""
    pool = [(c, n) for (c, n, s) in _APUS if s == shift]
    if not pool:
        pool = [(c, n) for (c, n, s) in _APUS]
    scored = []
    for codigo, nombre in pool:
        sc = round(matching.similarity(descripcion, nombre), 4)
        if sc > 0:
            scored.append((codigo, sc))
    scored.sort(key=lambda x: x[1], reverse=True)
    return scored[:top_n]


def _ref_decision(descripcion, shift):
    """(estado, candidatos0_codigo, elegido_codigo) según la lógica actual."""
    cands = _ref_scored(descripcion, shift)
    if not cands:
        return ("new", None, None)
    cod, score = cands[0]
    if score >= config.MATCH_ACCEPT:
        return ("auto", cod, cod)
    if score >= config.MATCH_REVIEW:
        return ("review", cod, None)
    return ("new", cod, None)


def _queries():
    """Consultas variadas derivadas del catálogo: exactas (AUTO), reformuladas
    (dudosas), y novedosas (sin match fuerte)."""
    qs = []
    for cod, nombre, shift in _APUS:
        qs.append((nombre, shift))                                  # exacta
        qs.append((f"Suministro e instalacion de {nombre.lower()}", shift))  # reformulada
        # reformulación que quita palabras del medio
        ws = nombre.split()
        if len(ws) > 3:
            qs.append((" ".join(ws[:2] + ws[-1:]), shift))
    # novedosas (deberían quedar sin match fuerte; ejercitan el respaldo)
    for nv in [
        "Barrera anti ruido modular en aluminio",
        "Sensor IoT de trafico vehicular inteligente",
        "Escultura urbana decorativa en acero inoxidable",
        "Mantenimiento de jardin vertical hidroponico",
        "xyz qwerty zzz",
    ]:
        qs.append((nv, "DIURNO"))
        qs.append((nv, "NOCTURNO"))
    return qs


def test_matcher_optimizado_decision_identica():
    """GATE: el Matcher real coincide con la referencia de escaneo completo en
    estado, elegido (AUTO) y candidatos[0] (base del fallback) para TODA consulta."""
    matcher = Matcher([(c, n, s) for (c, n, s) in _APUS])
    diffs = []
    for descripcion, shift in _queries():
        item = LicitacionItem(item="1", descripcion=descripcion, unidad="UN",
                              cantidad=1.0, precio_contractual=1.0, shift=shift)
        r = matcher.match(item)
        got = (r.status.value,
               r.candidatos[0].apu_codigo if r.candidatos else None,
               r.elegido.apu_codigo if r.elegido else None)
        esperado = _ref_decision(descripcion, shift)
        if got != esperado:
            diffs.append((descripcion, shift, esperado, got))
    assert not diffs, f"Decisiones divergentes ({len(diffs)}): {diffs[:5]}"


def test_matcher_incluye_caso_auto_review_y_new():
    """El conjunto de consultas debe ejercitar los tres estados (si no, el gate no
    estaría probando nada)."""
    matcher = Matcher([(c, n, s) for (c, n, s) in _APUS])
    estados = set()
    for descripcion, shift in _queries():
        item = LicitacionItem(item="1", descripcion=descripcion, unidad="UN",
                              cantidad=1.0, precio_contractual=1.0, shift=shift)
        estados.add(matcher.match(item).status)
    assert {MatchStatus.AUTO, MatchStatus.REVIEW, MatchStatus.NEW} <= estados
