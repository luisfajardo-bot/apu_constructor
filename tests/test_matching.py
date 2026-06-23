from apu_tool import config
from apu_tool.dominio.matching import Matcher, normalize, similarity
from apu_tool.nucleo.models import LicitacionItem, MatchStatus


def test_normalize_strips_accents_and_punct():
    assert normalize("Demolición, pavimento  ASFÁLTICO!") == "DEMOLICION PAVIMENTO ASFALTICO"


def test_similarity_identical_is_one():
    assert similarity("EXCAVACION MANUAL", "excavacion manual") == 1.0


def test_similarity_partial_between_zero_and_one():
    s = similarity("EXCAVACION MANUAL PARA REDES", "EXCAVACION MECANICA PARA REDES")
    assert 0.3 < s < 1.0


INDEX = [
    ("3009", "EXCAVACION MANUAL PARA REDES", "DIURNO"),
    ("3010", "DEMOLICION PAVIMENTO ASFALTICO", "DIURNO"),
    ("9001", "EXCAVACION MANUAL PARA REDES", "NOCTURNO"),
]


def test_match_auto_on_exact():
    m = Matcher(INDEX)
    item = LicitacionItem("1", "EXCAVACION MANUAL PARA REDES", "M3", 10, 0, "DIURNO")
    r = m.match(item)
    assert r.status == MatchStatus.AUTO
    assert r.elegido.apu_codigo == "3009"


def test_match_respects_shift():
    m = Matcher(INDEX)
    item = LicitacionItem("1", "EXCAVACION MANUAL PARA REDES", "M3", 10, 0, "NOCTURNO")
    r = m.match(item)
    assert r.elegido.apu_codigo == "9001"


def test_match_new_when_no_similarity():
    m = Matcher(INDEX)
    item = LicitacionItem("1", "INSTALACION DE PANELES SOLARES FOTOVOLTAICOS", "UN",
                          1, 0, "DIURNO")
    r = m.match(item)
    assert r.status in (MatchStatus.NEW, MatchStatus.REVIEW)
