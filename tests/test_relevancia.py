"""Orden por relevancia de una búsqueda.

El caso que originó esto: buscar "transporte" devolvía veinte APUs que la mencionan de
paso ANTES del que se llama "TRANSPORTE", porque el orden era por código.
"""
from apu_tool.nucleo import relevancia


class Fila:
    """Lo mínimo que `ordenar` necesita: un nombre y un código."""

    def __init__(self, codigo, nombre):
        self.codigo = codigo
        self.nombre = nombre

    def __repr__(self):
        return f"Fila({self.codigo!r}, {self.nombre!r})"


def _ordenar(q, *pares):
    filas = [Fila(c, n) for c, n in pares]
    return [f.nombre for f in relevancia.ordenar(
        filas, q, nombre_de=lambda f: f.nombre, codigo_de=lambda f: f.codigo)]


def test_los_niveles_mandan_sobre_el_codigo():
    """El de código menor NO gana si el otro empieza con lo buscado."""
    assert _ordenar(
        "transporte",
        ("1000", "SUMINISTRO, TRANSPORTE E INSTALACION DE TUBERIA PVC 12 PULGADAS"),
        ("2000", "AUTOTRANSPORTEDORA DE CONCRETO"),
        ("3000", "TRANSPORTE DE MATERIAL SOBRANTE A 20 KM"),
        ("4000", "TRANSPORTE"),
    ) == [
        "TRANSPORTE",                                     # nivel 0: exacto
        "TRANSPORTE DE MATERIAL SOBRANTE A 20 KM",        # nivel 1: empieza con
        "SUMINISTRO, TRANSPORTE E INSTALACION DE TUBERIA PVC 12 PULGADAS",  # nivel 2
        "AUTOTRANSPORTEDORA DE CONCRETO",                 # nivel 4: dentro de palabra
    ]


def test_dos_palabras_en_cualquier_orden_y_separadas():
    """Hoy esto devuelve CERO filas: `LIKE '%transporte material%'` es una frase."""
    assert _ordenar(
        "transporte material",
        ("1000", "EXCAVACION MANUAL"),
        ("2000", "TRANSPORTE DE MATERIAL SOBRANTE"),
        ("3000", "MATERIAL DE PRESTAMO Y SU TRANSPORTE"),
    ) == ["TRANSPORTE DE MATERIAL SOBRANTE", "MATERIAL DE PRESTAMO Y SU TRANSPORTE"]
    # "EXCAVACION MANUAL" no tiene ninguna de las dos palabras -> se descarta.


def test_la_frase_completa_gana_al_and_de_palabras():
    assert _ordenar(
        "transporte material",
        ("1000", "RETIRO Y MATERIAL CON TRANSPORTE INCLUIDO"),   # nivel 3: AND
        ("2000", "OBRA: TRANSPORTE MATERIAL A 5 KM"),            # nivel 2: la frase
    ) == ["OBRA: TRANSPORTE MATERIAL A 5 KM",
          "RETIRO Y MATERIAL CON TRANSPORTE INCLUIDO"]


def test_encuentra_sin_tildes_lo_que_esta_con_tildes():
    """El defecto de APUs: `excavacion` no encontraba "EXCAVACIÓN"."""
    assert _ordenar("excavacion", ("1000", "EXCAVACIÓN MECÁNICA")) == ["EXCAVACIÓN MECÁNICA"]


def test_busca_tambien_por_codigo():
    assert _ordenar("3017", ("9000", "MANO DE OBRA"), ("3017", "TRANSPORTE")) == [
        "TRANSPORTE", ]
    # Solo la fila cuyo código coincide; la otra no tiene "3017" en ningún lado.


def test_empate_de_nivel_desempata_por_parecido_y_despues_por_codigo():
    """Determinista: sin esto la paginación cambiaría de orden entre páginas."""
    assert _ordenar(
        "transporte",
        ("2000", "TRANSPORTE DE MATERIAL"),
        ("1000", "TRANSPORTE DE MATERIAL"),
    ) == ["TRANSPORTE DE MATERIAL", "TRANSPORTE DE MATERIAL"]
    filas = [Fila("2000", "TRANSPORTE DE MATERIAL"), Fila("1000", "TRANSPORTE DE MATERIAL")]
    ordenadas = relevancia.ordenar(filas, "transporte", nombre_de=lambda f: f.nombre,
                                   codigo_de=lambda f: f.codigo)
    assert [f.codigo for f in ordenadas] == ["1000", "2000"]


def test_q_vacia_no_reordena_ni_descarta():
    for q in (None, "", "   "):
        assert _ordenar(q, ("2000", "B"), ("1000", "A")) == ["B", "A"]


def test_arriba_del_techo_no_se_puntua_pero_los_niveles_siguen(monkeypatch):
    """El guard de CPU: sin score, el nivel y el código siguen ordenando."""
    monkeypatch.setattr(relevancia, "MAX_RANKEO", 1)
    assert _ordenar(
        "transporte",
        ("2000", "RETIRO Y TRANSPORTE"),
        ("1000", "TRANSPORTE DE MATERIAL"),
    ) == ["TRANSPORTE DE MATERIAL", "RETIRO Y TRANSPORTE"]


def test_similarity_sigue_disponible_desde_matching():
    """Movida a núcleo, pero `dominio/matching.py` la reexporta: compose.py y cruce.py
    la importan de ahí."""
    from apu_tool.dominio.matching import _tokens, normalize, similarity
    assert similarity("EXCAVACION MANUAL", "excavacion manual") == 1.0
    assert normalize("Excavación") == "EXCAVACION"
    assert "EXCAVACION" in _tokens("de la excavación")
