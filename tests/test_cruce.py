from apu_tool.dominio.cruce import resolver, CalidadCruce
from apu_tool.nucleo.models import Insumo


def _ins(cod, nom): return Insumo(cod, nom, "UN", "G", 100, "PRECIO IDU", id=1)


def test_huerfano_sin_candidatos():
    r = resolver([], "CEMENTO GRIS")
    assert r.calidad == CalidadCruce.HUERFANO and r.insumo is None

def test_exacto_por_nombre_normalizado():
    cands = [_ins("100", "BASE GRANULAR"), _ins("100", "CEMENTO GRIS")]
    r = resolver(cands, "  cemento   gris ")
    assert r.calidad == CalidadCruce.EXACTO and r.insumo.nombre == "CEMENTO GRIS"

def test_aproximado_cuando_uno_destaca():
    cands = [_ins("100", "DUCTO TELEFONICO LIVIANO PVC TIPO EB D=3"),
             _ins("100", "BASE GRANULAR CLASE C")]
    r = resolver(cands, "DUCTO TELEFONICO PVC EB 3")
    assert r.calidad == CalidadCruce.APROXIMADO and "DUCTO" in r.insumo.nombre

def test_ambiguo_cuando_ningun_nombre_se_parece():
    cands = [_ins("100", "BASE GRANULAR CLASE C"),
             _ins("100", "SOBRECARPETA RODADURA ASFALTICA")]
    r = resolver(cands, "TORNILLO HEXAGONAL 1 PULGADA")
    assert r.calidad == CalidadCruce.AMBIGUO and r.insumo is None

def test_un_solo_candidato_nombre_lejano_es_ambiguo():
    # caso "código sospechoso" estilo 4613: el único insumo del código no se parece
    cands = [_ins("4613", "UNION PVC D=10")]
    r = resolver(cands, "TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS")
    assert r.calidad == CalidadCruce.AMBIGUO and r.insumo is None
