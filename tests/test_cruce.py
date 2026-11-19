from apu_tool.dominio.cruce import resolver, CalidadCruce
from apu_tool.nucleo.models import Insumo


def _ins(cod, nom): return Insumo(cod, nom, "UN", "G", 100, "PRECIO IDU", id=1)


def test_huerfano_sin_candidatos():
    r = resolver([], "CEMENTO GRIS")
    assert r.calidad == CalidadCruce.HUERFANO and r.insumo is None and r.score == 0.0

def test_exacto_por_nombre_normalizado():
    cands = [_ins("100", "BASE GRANULAR"), _ins("100", "CEMENTO GRIS")]
    r = resolver(cands, "  cemento   gris ")
    assert r.calidad == CalidadCruce.EXACTO and r.insumo.nombre == "CEMENTO GRIS"
    assert r.score == 1.0

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


# ---- elección por nombre (códigos compartidos) ----
from apu_tool.dominio import cruce


def _i(cod, nom, unidad="UN", grupo="G", oculto=False):
    return Insumo(cod, nom, unidad, grupo, 100, "PRECIO IDU", id=1, oculto=oculto)


REDUCCION = _i("7406", "REDUCCION HD E.L. D=12 x 10", grupo="ACCESORIOS")
SENAL = _i("7406", "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE", grupo="SEÑALIZACION",
           oculto=True)


def test_elegir_exacto_aproximado_y_ambiguo():
    nombres = [REDUCCION.nombre, SENAL.nombre]
    assert cruce.elegir(nombres, " señal vertical sr 90x30 incluye poste ")[0] == 1
    i, calidad, _ = cruce.elegir(nombres, "SEÑAL VERTICAL SR 90X30")
    assert (i, calidad) == (1, cruce.CalidadCruce.APROXIMADO)
    assert cruce.elegir(nombres, "")[0] is None
    assert cruce.elegir(nombres, "TORNILLO HEXAGONAL")[0] is None
    assert cruce.elegir([], "X") == (None, cruce.CalidadCruce.HUERFANO, 0.0)


def test_elegir_fila_con_un_solo_candidato_no_mira_el_nombre():
    """Igual que el alta de siempre: un código de un solo insumo es ese insumo."""
    assert cruce.elegir_fila([REDUCCION], "CUALQUIER COSA") is REDUCCION
    assert cruce.elegir_fila([], "X") is None
    assert cruce.elegir_fila([REDUCCION, SENAL], "SEÑAL VERTICAL SR 90X30 INCLUYE POSTE") is SENAL
    assert cruce.elegir_fila([REDUCCION, SENAL], "") is None


def test_ficha_sin_dinero_y_con_opciones_si_el_codigo_es_compartido():
    f = cruce.ficha([REDUCCION, SENAL], "")
    assert f == {"nombre": "", "unidad": "", "grupo": "", "opciones": [
        {"nombre": REDUCCION.nombre, "unidad": "UN", "oculto": False},
        {"nombre": SENAL.nombre, "unidad": "UN", "oculto": True}]}
    assert cruce.ficha([REDUCCION, SENAL], REDUCCION.nombre)["nombre"] == REDUCCION.nombre
    assert cruce.ficha([REDUCCION], "") == {
        "nombre": REDUCCION.nombre, "unidad": "UN", "grupo": "ACCESORIOS"}
    assert "precio" not in str(cruce.ficha([REDUCCION, SENAL], ""))


def test_compartidos_solo_los_codigos_con_dos_o_mas_filas():
    cat = {"7406": [REDUCCION, SENAL], "100": [_i("100", "CEMENTO", "KG")], "9": []}
    assert cruce.compartidos(cat) == {
        "7406": ((REDUCCION.nombre, "UN"), (SENAL.nombre, "UN"))}
