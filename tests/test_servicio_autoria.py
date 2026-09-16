"""Servicio de autoría de base: crear insumos/APUs (individual + Excel)."""
import io
import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio import autoria


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU"),
        Insumo("200", "ARENA", "M3", "MAT", 50000, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("A1", "MURO EXISTENTE", "M2", "DIURNO", "ESTR")])
    return alm


# ---------------------------------------------------------------- individual
def test_crear_insumo_ok(tmp_path):
    alm = _alm(tmp_path)
    out = autoria.crear_insumo(alm, {"codigo": "300", "nombre": "GRAVA", "unidad": "M3",
                                     "grupo": "MAT", "precio": 80000, "fuente": "PRECIO IDU"})
    assert out["codigo"] == "300" and out["precio"] == 80000
    assert any(i.codigo == "300" for i in alm.precios.get_candidatos("300"))


def test_crear_insumo_duplicado_y_validacion(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, {"codigo": "100", "nombre": "CEMENTO GRIS", "precio": 1})
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, {"codigo": "", "nombre": "X", "precio": 1})
    with pytest.raises(ValueError):
        autoria.crear_insumo(alm, {"codigo": "9", "nombre": "X", "precio": -5})


def test_crear_apu_con_composicion(tmp_path):
    alm = _alm(tmp_path)
    out = autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0},
                        {"insumo_codigo": "200", "rendimiento": 0.5}]})
    assert out["codigo"] == "B2" and out["n_componentes"] == 2
    comps = alm.apus.get_components("B2", "DIURNO")
    # nombre/unidad se resolvieron desde la base
    assert comps[0].insumo_nombre == "CEMENTO GRIS" and comps[0].unidad == "KG"


def test_crear_apu_validaciones(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):  # turno inválido
        autoria.crear_apu(alm, {"codigo": "Z", "turno": "TARDE", "nombre": "X"})
    with pytest.raises(ValueError):  # rendimiento <= 0
        autoria.crear_apu(alm, {"codigo": "Z", "turno": "DIURNO", "nombre": "X",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 0}]})
    with pytest.raises(ValueError):  # duplicado (A1, DIURNO)
        autoria.crear_apu(alm, {"codigo": "A1", "turno": "DIURNO", "nombre": "MURO"})


# ---------------------------------------------------------------- import insumos
def _xlsx_upsert() -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio", "fuente"])
    ws.append(["300", "GRAVA COMUN", "M3", "MAT", 80000, "PRECIO IDU"])   # con nombre, no existe -> crear
    ws.append(["100", "CEMENTO GRIS", "KG", "MAT", 1200, "PRECIO IDU"])   # con nombre, existe -> actualizar
    ws.append(["", "SIN CODIGO", "UN", "", 10, ""])                       # sin codigo -> invalida
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _xlsx_solo_precio(filas) -> bytes:
    """Archivo estilo lista de precios: codigo, precio (sin nombre)."""
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "precio", "fuente"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def _xlsx_upsert_filas(filas) -> bytes:
    """Excel con las columnas del importador y las filas que se le pasen."""
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["codigo", "nombre", "unidad", "grupo", "precio"])
    for f in filas:
        ws.append(f)
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_upsert_preview_con_nombre(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx", "PRECIO IDU")
    assert [c["codigo"] for c in prev["crear"]] == ["300"]
    assert [c["codigo"] for c in prev["actualizar"]] == ["100"]
    assert prev["actualizar"][0]["precio_actual"] == 1000 and prev["actualizar"][0]["precio_nuevo"] == 1200
    assert len(prev["invalida"]) == 1


def test_preview_dice_como_clasifico_la_fuente(tmp_path):
    """El candado es fail-open: una fuente pública mal escrita clasifica interna y no
    protege nada. El diálogo pinta esta clave para que se vea antes de aplicar."""
    alm = _alm(tmp_path)
    contenido = _xlsx_solo_precio([["100", 1200, ""]])
    assert autoria.preview_importar_insumos(
        alm, contenido, "f.xlsx", "PRECIO IDU")["clasificacion_import"] == "publico"
    assert autoria.preview_importar_insumos(
        alm, contenido, "f.xlsx", "PRECIO IDU 2026")["clasificacion_import"] == "interno"


def test_upsert_aplicar_crea_y_actualiza(tmp_path):
    alm = _alm(tmp_path)
    res = autoria.aplicar_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx", "PRECIO IDU")
    assert res["creados"] == 1 and res["actualizados"] == 1
    assert any(i.codigo == "300" for i in alm.precios.get_candidatos("300"))
    assert alm.precios.get_candidatos("100")[0].precio == 1200   # precio actualizado


def test_upsert_sin_nombre_codigo_unico_actualiza(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["100", 1500, "COMPRAS"]]),
                                            "precios.xlsx", "COMPRAS")
    assert len(prev["actualizar"]) == 1 and prev["actualizar"][0]["precio_nuevo"] == 1500
    assert prev["crear"] == [] and prev["no_encontrada"] == []


def test_upsert_sin_nombre_codigo_repetido_ambiguo(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("100", "CEMENTO BLANCO", "KG", "MAT", 2000, "PRECIO IDU")])
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["100", 1500, "X"]]),
                                            "precios.xlsx", "PRECIO IDU")
    assert len(prev["ambigua"]) == 1 and prev["ambigua"][0]["codigo"] == "100"
    assert len(prev["ambigua"][0]["candidatos"]) == 2


def test_upsert_sin_nombre_codigo_inexistente_no_encontrada(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["999", 1500, "X"]]),
                                            "precios.xlsx", "PRECIO IDU")
    assert [n["codigo"] for n in prev["no_encontrada"]] == ["999"]


def test_upsert_precio_vacio_en_actualizacion_no_cambia(tmp_path):
    alm = _alm(tmp_path)
    prev = autoria.preview_importar_insumos(alm, _xlsx_solo_precio([["100", "", "IGNORADA"]]),
                                            "precios.xlsx", "NUEVA FUENTE")
    c = prev["actualizar"][0]
    assert c["precio_nuevo"] == 1000            # precio actual, no 0
    assert c["fuente_nueva"] == "NUEVA FUENTE"  # la declarada, no la columna del archivo


def test_fuente_declarada_gana_sobre_la_columna_del_archivo(tmp_path):
    """La fuente la declara la importación, no el archivo. Antes, un archivo sin
    columna `fuente` dejaba el precio nuevo con la etiqueta vieja: un precio del IDU
    rotulado COSTO INTERNO."""
    alm = _alm(tmp_path)
    # El archivo dice "FUENTE DEL ARCHIVO"; la importación declara "COTIZACION 2026".
    contenido = _xlsx_solo_precio([["100", 1500, "FUENTE DEL ARCHIVO"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "precios.xlsx",
                                            "COTIZACION 2026")
    assert prev["actualizar"][0]["fuente_nueva"] == "COTIZACION 2026"

    # también al crear
    prev2 = autoria.preview_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx",
                                             "COTIZACION 2026")
    assert prev2["crear"][0]["fuente"] == "COTIZACION 2026"


def test_fuente_declarada_vacia_se_rechaza(tmp_path):
    """Sin declaración no hay importación: un default silencioso es exactamente
    cómo nació el bug de la etiqueta."""
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="fuente"):
        autoria.preview_importar_insumos(alm, _xlsx_upsert(), "insumos.xlsx", "   ")


def _alm_con_interno(tmp_path):
    """Base con un insumo de costo interno (el que hay que proteger) y uno con fuente
    vacía pero precio real (el otro caso que `_protegida` protege: ver el test
    `test_fuente_vacia_con_precio_real_tambien_se_protege`)."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("500", "MANO DE OBRA OFICIAL", "HR", "MO", 25000, "COSTO INTERNO"),
        Insumo("600", "TRANSPORTE INTERNO", "VJE", "TRA", 15000, "")])
    return alm


def test_import_publico_no_pisa_un_precio_interno(tmp_path):
    """El caso del usuario: subir la lista del visor IDU no puede pisar los costos
    internos de la empresa."""
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["100", 1200, ""], ["500", 9, ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "idu.xlsx", "PRECIO IDU")

    assert [c["codigo"] for c in prev["actualizar"]] == ["100"]   # el público sí
    assert len(prev["protegida"]) == 1
    p = prev["protegida"][0]
    assert p["codigo"] == "500" and p["fuente_actual"] == "COSTO INTERNO"
    assert p["precio_actual"] == 25000 and p["precio_archivo"] == 9


def test_import_interno_si_pisa_un_precio_interno(tmp_path):
    """La regla es asimétrica: una tanda interna es curada y deliberada."""
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["500", 27000, ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "compras.xlsx",
                                            "COMPRAS ALMACEN 2026")
    assert prev["protegida"] == []
    assert prev["actualizar"][0]["precio_nuevo"] == 27000


def test_insumo_sin_tarifa_en_la_lista_no_se_protege(tmp_path):
    """El falso positivo: sin tarifa en la lista consultada, `fuente_precio` es "" por
    el LEFT JOIN, no porque el precio sea interno. Sin el `not ins.sin_precio`, una
    importación pública contra una lista de NP quedaría bloqueada entera."""
    alm = _alm(tmp_path)
    np = alm.precios.crear_lista("NP Calle 13")
    contenido = _xlsx_solo_precio([["100", 1200, ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "np.xlsx", "PRECIO IDU",
                                            lista_id=np)
    assert prev["protegida"] == []
    assert prev["actualizar"][0]["precio_nuevo"] == 1200


def test_import_publico_protege_aunque_el_archivo_no_traiga_precio(tmp_path):
    """Una fila sin precio le cambiaría SOLO la etiqueta al insumo interno: es el bug
    de rotulado al revés, y también se protege."""
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["500", "", ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "idu.xlsx", "PRECIO IDU")
    assert len(prev["protegida"]) == 1
    assert prev["protegida"][0]["precio_archivo"] is None
    assert prev["actualizar"] == [] and prev["invalida"] == []


def test_fuente_vacia_con_precio_real_tambien_se_protege(tmp_path):
    """Fija que una fuente "" con precio real cuenta como interna igual que COSTO
    INTERNO (no sabemos qué es ese precio) — NO fija sola el término
    `not ins.sin_precio` de `_protegida`: acá `ins.sin_precio` ya es False, así que
    ese término da True esté o no. Lo que sí rompería este caso es reclasificar ""
    como público, o que el LEFT JOIN de alguno de los dos backends devuelva
    `sin_precio=True` para un insumo con precio real. La frontera completa la cubren
    entre esta prueba y su hermana `test_insumo_sin_tarifa_en_la_lista_no_se_protege`,
    que cubre el otro lado (fuente "" que de verdad no tiene tarifa, y no se
    protege)."""
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["600", 500, ""]])
    prev = autoria.preview_importar_insumos(alm, contenido, "idu.xlsx", "PRECIO IDU")
    assert [p["codigo"] for p in prev["protegida"]] == ["600"]
    assert prev["protegida"][0]["fuente_actual"] == ""


def test_aplicar_no_escribe_las_protegidas_y_las_cuenta(tmp_path):
    alm = _alm_con_interno(tmp_path)
    contenido = _xlsx_solo_precio([["100", 1200, ""], ["500", 9, ""]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "idu.xlsx", "PRECIO IDU")

    assert res == {"creados": 0, "actualizados": 1, "protegidos": 1, "errores": []}
    interno = alm.precios.get_candidatos("500")[0]
    assert interno.precio == 25000 and interno.fuente_precio == "COSTO INTERNO"
    assert alm.precios.get_candidatos("100")[0].precio == 1200


def test_las_protegidas_no_dejan_auditoria(tmp_path):
    """No cambió nada: no hay evento que registrar."""
    alm = _alm_con_interno(tmp_path)
    autoria.aplicar_importar_insumos(alm, _xlsx_solo_precio([["500", 9, ""]]),
                                     "idu.xlsx", "PRECIO IDU")
    _items, total = alm.auditoria.listar(accion="precio.editar")
    assert total == 0


def test_conflicto_de_codigo_trae_el_mejor_candidato(tmp_path):
    """Con 652 códigos repetidos en el catálogo real, "el código ya existe" no dice
    cuál insumo es. El conflicto tiene que nombrar contra cuál se ofrece actualizar."""
    alm = _alm(tmp_path)
    # dos insumos con el MISMO código y nombres muy distintos
    alm.precios.insert_insumos([
        Insumo("700", "CHEVRON 90 CM X 40 CM REFLECTIVO", "UN", "SEN", 330498, "PRECIO IDU"),
        Insumo("700", "PISO EN LOSETA PREFABRICADA A-50", "M2", "PAV", 135101, "PRECIO IDU")])
    # OJO con el nombre del archivo: `normalizar` convierte "A-50" en "A 50", así que un
    # nombre que solo cambie el guion haría MATCH de identidad y nunca llegaría a
    # conflicto. La diferencia tiene que ser una letra de verdad (LOSETA -> LOZETA).
    contenido = _xlsx_upsert_filas([["700", "PISO EN LOZETA PREFABRICADA A-50", "M2", "PAV", 140000]])
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")

    assert len(prev["conflicto"]) == 1
    c = prev["conflicto"][0]
    assert c["campo"] == "codigo"
    assert c["nombre_actual"] == "PISO EN LOSETA PREFABRICADA A-50"   # el parecido, no el CHEVRON
    assert c["precio_actual"] == 135101
    assert c["parecido"] > 0.7      # medido: 74.8% contra el PISO, 10.0% contra el CHEVRON


def test_numeros_no_coinciden_cuando_cambia_un_numero(tmp_path):
    """El parecido NO separa "es el mismo" de "es otro": con nombres largos, cambiar un
    dígito puntúa ~89%, igual que una letra distinta. Lo que separa son los números."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("800", "TUBERIA PVC SANITARIA DE 6 PULGADAS INCLUYE ACCESORIOS Y MANO DE OBRA",
               "ML", "MAT", 50000, "PRECIO IDU")])
    contenido = _xlsx_upsert_filas([
        ["800", "TUBERIA PVC SANITARIA DE 8 PULGADAS INCLUYE ACCESORIOS Y MANO DE OBRA",
         "ML", "MAT", 60000]])
    c = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")["conflicto"][0]
    assert c["parecido"] > 0.80          # el parecido solo lo dejaría pasar
    assert c["numeros_coinciden"] is False       # los números lo delatan


def test_numeros_coinciden_con_una_letra_distinta(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("900", "CONCRETO 3000 PSI HECHO EN OBRA PARA REDES", "M3", "MAT",
               526100, "PRECIO IDU")])
    contenido = _xlsx_upsert_filas([
        ["900", "CONCRETO 3000 PSI HECHO EN OVRA PARA REDES", "M3", "MAT", 530000]])
    c = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")["conflicto"][0]
    assert c["numeros_coinciden"] is True


# Los diez casos con los que se eligió la regla. El parecido SOLO no los separa: "una
# letra distinta" da 89.0% y "MR-42 vs MR-40" da 88.7%. Lo que los separa son los números.
@pytest.mark.parametrize("esperado,a,b", [
    (True,  "CONCRETO 3000 PSI HECHO EN OBRA PARA REDES", "CONCRETO 3000 PSI HECHO EN OVRA PARA REDES"),
    (True,  "SUBBASE GRANULAR CLASE C PARA VIA", "SUBBASE GRANULAR CLASE C"),
    (True,  "PINTURA ACRILICA BASE AGUA PARA DEMARCACION DE VIAS", "PINTURA ACRILICA BASE AGUA"),
    (True,  "SUMINISTRO E INSTALACION DE TUBERIA PVC SANITARIA 6 PULGADAS", "SUM E INST TUBERIA PVC SANITARIA 6 PULG"),
    (False, "CONCRETO 3000 PSI HECHO EN OBRA PARA REDES", "CONCRETO 2500 PSI HECHO EN OBRA PARA REDES"),
    (False, "SUMINISTRO Y COLOCACION DE CONCRETO HIDRAULICO MR-42 PARA LOSA", "SUMINISTRO Y COLOCACION DE CONCRETO HIDRAULICO MR-40 PARA LOSA"),
    (False, "TUBERIA PVC SANITARIA DE 6 PULGADAS INCLUYE ACCESORIOS", "TUBERIA PVC SANITARIA DE 8 PULGADAS INCLUYE ACCESORIOS"),
    (False, "ACERO DE REFUERZO FY=420 MPA PARA ESTRUCTURAS", "ACERO DE REFUERZO FY=240 MPA PARA ESTRUCTURAS"),
    # el orden de los números importa: son dos materiales
    (False, "BREAKER INDUSTRIAL ABB 3 X 40 AMP", "BREAKER INDUSTRIAL ABB 40 X 3 AMP"),
    # sin números de ningún lado coinciden trivialmente: por eso `numeros_coinciden` es
    # una SEÑAL y no un veredicto — acá no separa nada
    (True,  "LADRILLO TOLETE COMUN", "LADRILLO TOLETE PRENSADO"),
])
def test_regla_de_los_numeros(esperado, a, b):
    assert autoria._mismos_numeros(a, b) is esperado


def test_conflictos_salen_ordenados_por_parecido(tmp_path):
    """El orden es lo que reemplaza al premarcado: los typos obvios quedan arriba."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("600", "ARENA DE PENA LAVADA", "M3", "MAT", 50000, "PRECIO IDU"),
        Insumo("601", "CEMENTO BLANCO TIPO III", "KG", "MAT", 2000, "PRECIO IDU")])
    contenido = _xlsx_upsert_filas([
        ["600", "NADA QUE VER CON ARENA", "M3", "MAT", 1],           # parecido bajísimo
        ["601", "CEMENTO BLANCO TIPO III EXTRA", "KG", "MAT", 2]])   # casi igual
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")
    parecidos = [c["parecido"] for c in prev["conflicto"]]
    assert parecidos == sorted(parecidos, reverse=True)
    assert prev["conflicto"][0]["codigo"] == "601"


def test_conflicto_contra_una_fila_del_mismo_archivo_no_trae_candidato(tmp_path):
    """El choque es contra una fila anterior del MISMO archivo: ese insumo todavía no
    existe en la base, así que no hay contra qué actualizar y no lleva casilla."""
    alm = _alm(tmp_path)
    contenido = _xlsx_upsert_filas([
        ["7777", "GRAVA COMUN DE RIO", "M3", "MAT", 8000],
        ["7777", "OTRA COSA DISTINTA", "M3", "MAT", 9000]])
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")
    assert len(prev["crear"]) == 1 and len(prev["conflicto"]) == 1
    assert "insumo_id" not in prev["conflicto"][0]


def test_conflicto_sin_tarifa_en_la_lista_no_miente_con_un_cero(tmp_path):
    """Contra una lista de NP, `precio_actual` es 0.0 por el LEFT JOIN, no porque el
    precio sea 0. `sin_precio_actual` es lo que deja que el diálogo diga la verdad."""
    alm = _alm(tmp_path)
    np = alm.precios.crear_lista("NP Calle 13")
    contenido = _xlsx_upsert_filas([["100", "CEMENTO GRIZ", "KG", "MAT", 1200]])
    c = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                         lista_id=np)["conflicto"][0]
    assert c["precio_actual"] == 0.0 and c["sin_precio_actual"] is True


def test_conflicto_de_nombre_no_trae_candidato(tmp_path):
    """El nombre ya existe bajo OTRO código: forzar ahí reasignaría el precio a un
    insumo con código distinto, y está fuera de alcance. Sin casilla."""
    alm = _alm(tmp_path)
    contenido = _xlsx_upsert_filas([["999", "CEMENTO GRIS", "KG", "MAT", 1200]])
    c = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")["conflicto"][0]
    assert c["campo"] == "nombre"
    assert "insumo_id" not in c


# ------------------------------------------------------- forzar_ids (Task 2)
def test_forzar_un_conflicto_actualiza_el_insumo_elegido(tmp_path):
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("900", "CONCRETO 3000 PSI HECHO EN OBRA", "M3", "MAT", 526100, "PRECIO IDU")])
    iid = alm.precios.get_candidatos("900")[0].id
    contenido = _xlsx_upsert_filas([["900", "CONCRETO 3000 PSI HECHO EN OVRA", "M3", "MAT", 530000]])

    # sin forzar: queda en conflicto y no se escribe
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU")
    assert res["creados"] == 0 and res["actualizados"] == 0
    assert alm.precios.get_candidatos("900")[0].precio == 526100

    # forzando: se actualiza el que se eligió
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                           forzar_ids={iid})
    assert res["actualizados"] == 1
    assert alm.precios.get_candidatos("900")[0].precio == 530000
    assert alm.precios.get_candidatos("900")[0].nombre == "CONCRETO 3000 PSI HECHO EN OBRA"


def test_forzar_no_es_un_permiso_el_candado_sigue(tmp_path):
    """Forzar resuelve una pregunta de IDENTIDAD, no de PERMISO. Una fila forzada sobre
    un insumo con precio interno, con importación pública, sigue protegida."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("901", "MANO DE OBRA OFICIAL DE PRIMERA", "HR", "MO", 25000, "COSTO INTERNO")])
    iid = alm.precios.get_candidatos("901")[0].id
    contenido = _xlsx_upsert_filas([["901", "MANO DE OBRA OFICIAL DE PRIMER", "HR", "MO", 9]])

    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                            forzar_ids={iid})
    assert prev["conflicto"] == []                  # ya no es conflicto: se forzó
    assert prev["actualizar"] == []                 # pero tampoco se actualiza
    assert [p["codigo"] for p in prev["protegida"]] == ["901"]

    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                           forzar_ids={iid})
    assert res["protegidos"] == 1 and res["actualizados"] == 0
    assert alm.precios.get_candidatos("901")[0].precio == 25000


def test_forzar_un_id_que_no_resuelve_no_escribe(tmp_path):
    """El catálogo puede cambiar entre el preview y el aplicar: un id que ya no
    corresponde deja la fila en conflicto, sin error."""
    alm = _alm(tmp_path)
    alm.precios.insert_insumos([
        Insumo("902", "ARENA DE PENA LAVADA", "M3", "MAT", 50000, "PRECIO IDU")])
    contenido = _xlsx_upsert_filas([["902", "ARENA DE PENA LAVADA GRUESA", "M3", "MAT", 60000]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                           forzar_ids={999999})
    assert res["actualizados"] == 0 and res["errores"] == []
    assert alm.precios.get_candidatos("902")[0].precio == 50000


def test_forzar_un_conflicto_de_nombre_no_hace_nada(tmp_path):
    """Solo se fuerzan conflictos de código (ver spec, fuera de alcance)."""
    alm = _alm(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id      # CEMENTO GRIS, código 100
    contenido = _xlsx_upsert_filas([["999", "CEMENTO GRIS", "KG", "MAT", 1200]])
    prev = autoria.preview_importar_insumos(alm, contenido, "f.xlsx", "PRECIO IDU",
                                            forzar_ids={iid})
    assert len(prev["conflicto"]) == 1 and prev["actualizar"] == []


# ---------------------------------------------------------------- import APUs
def _xlsx_apus() -> bytes:
    wb = openpyxl.Workbook(); ws = wb.active
    # formato hoja APUS: actividad(0) cod_idu(1) unidad(2) insumo(3) cod(4) und(5)
    #                    rendimiento(6) inv(7) precio(8) costo(9) turno(10)
    ws.title = "APUS"
    ws.append(["ACTIVIDAD","COD IDU","UN","INSUMO","COD","UND","RENDIMIENTO","INV","PRECIO","COSTO","TURNO"])
    ws.append(["MURO NUEVO ESPECIAL","7777","M2","","","","","","","","DIURNO"])  # cabecera APU
    ws.append(["","","","CEMENTO","100","KG",2.5,"",900,"",""])                   # componente
    ws.append(["","","","ARENA","200","M3",0.5,"",50,"",""])                      # componente
    ws.append(["MURO EXISTENTE","A1","M2","","","","","","","","DIURNO"])         # ya existe
    ws.append(["","","","CEMENTO","100","KG",1.0,"",900,"",""])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_import_apus_preview_y_aplicar(tmp_path):
    alm = _alm(tmp_path)
    data = _xlsx_apus()
    prev = autoria.preview_importar_apus(alm, data)
    codigos_crear = {c["codigo"] for c in prev["crear"]}
    assert "7777" in codigos_crear
    assert any(c["codigo"] == "A1" for c in prev["ya_existe"])
    nuevo = next(c for c in prev["crear"] if c["codigo"] == "7777")
    assert nuevo["n_componentes"] == 2 and nuevo["turno"] == "DIURNO"
    res = autoria.aplicar_importar_apus(alm, data)
    assert res["creados"] == 1
    assert alm.apus.get_apu("7777", "DIURNO").nombre == "MURO NUEVO ESPECIAL"
    assert len(alm.apus.get_components("7777", "DIURNO")) == 2


def _xlsx_apus_nocturno() -> bytes:
    """Plantilla con nocturnos de código PELADO (la N va solo en la columna turno),
    como en la lista de licitación real que rompió en prod."""
    wb = openpyxl.Workbook(); ws = wb.active
    ws.title = "APUS"
    ws.append(["ACTIVIDAD","COD IDU","UN","INSUMO","COD","UND","RENDIMIENTO","INV","PRECIO","COSTO","TURNO"])
    ws.append(["EXCAVACION NOCTURNA","8888","M3","","","","","","","","NOCTURNO"])   # pelado -> debe quedar "8888 N"
    ws.append(["","","","CEMENTO","100","KG",1.5,"",900,"",""])
    ws.append(["DEMOLICION DIURNA","9999","M2","","","","","","","","DIURNO"])       # diurno -> intacto
    ws.append(["","","","ARENA","200","M3",1.0,"",50,"",""])
    ws.append(["YA CON N","7000 N","M3","","","","","","","","NOCTURNO"])            # ya trae N -> idempotente
    ws.append(["","","","CEMENTO","100","KG",1.0,"",900,"",""])
    buf = io.BytesIO(); wb.save(buf); return buf.getvalue()


def test_import_apus_nocturno_agrega_sufijo_n(tmp_path):
    alm = _alm(tmp_path)
    data = _xlsx_apus_nocturno()
    prev = autoria.preview_importar_apus(alm, data)
    codigos = {(c["codigo"], c["turno"]) for c in prev["crear"]}
    assert ("8888 N", "NOCTURNO") in codigos       # nocturno pelado -> con sufijo
    assert ("8888", "NOCTURNO") not in codigos     # no se crea el pelado
    assert ("9999", "DIURNO") in codigos           # diurno intacto
    assert ("7000 N", "NOCTURNO") in codigos       # ya tenía N -> sin doble sufijo
    assert ("7000 N N", "NOCTURNO") not in codigos

    res = autoria.aplicar_importar_apus(alm, data)
    assert res["creados"] == 3
    assert alm.apus.get_apu("8888 N", "NOCTURNO") is not None
    assert alm.apus.get_apu("8888", "NOCTURNO") is None
    assert len(alm.apus.get_components("8888 N", "NOCTURNO")) == 1   # el componente cuelga del código con N
    assert alm.apus.get_apu("7000 N", "NOCTURNO") is not None
    assert alm.apus.get_apu("9999", "DIURNO") is not None


def test_import_apus_sin_hoja_apus(tmp_path):
    alm = _alm(tmp_path)
    wb = openpyxl.Workbook(); wb.active.append(["x"]); buf = io.BytesIO(); wb.save(buf)
    with pytest.raises(ValueError):
        autoria.preview_importar_apus(alm, buf.getvalue())


def test_editar_apu_reemplaza_y_devuelve_resumen(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    out = autoria.editar_apu(alm, "B2", "DIURNO", {"nombre": "PISO PULIDO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "200", "rendimiento": 0.5}]})
    assert out["nombre"] == "PISO PULIDO" and out["n_componentes"] == 1
    comps = alm.apus.get_components("B2", "DIURNO")
    assert [c.insumo_codigo for c in comps] == ["200"]


def test_editar_apu_inexistente_devuelve_none(tmp_path):
    alm = _alm(tmp_path)
    assert autoria.editar_apu(alm, "NOPE", "DIURNO", {"nombre": "X",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}]}) is None


def test_editar_apu_rendimiento_invalido_lanza(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    with pytest.raises(ValueError):
        autoria.editar_apu(alm, "B2", "DIURNO", {"nombre": "PISO",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 0}]})


def test_borrar_apu_ok_devuelve_resultado(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    out = autoria.borrar_apu(alm, "B2", "DIURNO")
    assert out == {"borrado": True, "n_corridas": 0}
    assert alm.apus.get_apu("B2", "DIURNO") is None


def test_borrar_apu_inexistente_devuelve_none(tmp_path):
    alm = _alm(tmp_path)
    assert autoria.borrar_apu(alm, "NOPE", "DIURNO") is None


# --------------------------------------------------- FIX 1: preservar tipo/ref_shift
def test_editar_apu_preserva_marca_subapu_si_no_viene_tipo(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    alm.apus.set_componente_subapu("B2", "DIURNO", 0, "DIURNO")
    comps = alm.apus.get_components("B2", "DIURNO")
    assert comps[0].tipo == "apu" and comps[0].ref_shift == "DIURNO"

    autoria.editar_apu(alm, "B2", "DIURNO", {"nombre": "PISO PULIDO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})  # sin 'tipo'
    comps = alm.apus.get_components("B2", "DIURNO")
    assert comps[0].tipo == "apu" and comps[0].ref_shift == "DIURNO"    # preservado


def test_editar_apu_tipo_explicito_gana_sobre_marca_previa(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    alm.apus.set_componente_subapu("B2", "DIURNO", 0, "DIURNO")

    autoria.editar_apu(alm, "B2", "DIURNO", {"nombre": "PISO PULIDO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0, "tipo": "insumo"}]})
    comps = alm.apus.get_components("B2", "DIURNO")
    assert comps[0].tipo == "insumo" and comps[0].ref_shift == ""      # explícito gana


# ------------------------------------------- piso de $1 y herencia del histórico
def test_crear_apu_pone_piso_de_uno_en_el_historico(tmp_path):
    """Regla de negocio 'nada en $0': un componente sin histórico que heredar se
    guarda en 1.0, no en 0.0."""
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    comps = alm.apus.get_components("B2", "DIURNO")
    assert comps[0].precio_unitario_hist == autoria.PISO_HIST == 1.0


def test_mapas_de_componentes_devuelve_marcas_y_historico():
    comps = [
        ApuComponent("A1", "DIURNO", "100", "CEMENTO GRIS", "KG", 2.0, 900.0),
        ApuComponent("A1", "DIURNO", "200", "ARENA", "M3", 0.5, 48000.0,
                     tipo="apu", ref_shift="NOCTURNO"),
    ]
    previos, hist = autoria._mapas_de_componentes(comps)
    assert previos == {"100": ("insumo", ""), "200": ("apu", "NOCTURNO")}
    assert hist == {"100": 900.0, "200": 48000.0}


def test_mapas_de_componentes_codigo_repetido_gana_el_de_tipo_apu():
    """Misma regla de desempate que ya aplicaba editar_apu para las marcas."""
    comps = [
        ApuComponent("A1", "DIURNO", "100", "X", "KG", 1.0, 500.0),
        ApuComponent("A1", "DIURNO", "100", "X", "KG", 1.0, 700.0,
                     tipo="apu", ref_shift="DIURNO"),
    ]
    previos, hist = autoria._mapas_de_componentes(comps)
    assert previos["100"] == ("apu", "DIURNO")
    assert hist["100"] == 700.0


def test_componentes_de_hereda_el_historico_del_mapa(tmp_path):
    alm = _alm(tmp_path)
    comps = autoria._componentes_de(
        alm, [{"insumo_codigo": "100", "rendimiento": 2.0},
              {"insumo_codigo": "200", "rendimiento": 1.0}],
        "DIURNO", hist={"100": 900.0})
    assert comps[0].precio_unitario_hist == 900.0     # heredado
    assert comps[1].precio_unitario_hist == 1.0       # sin nada que heredar -> piso


def test_componentes_de_sube_al_piso_un_historico_en_cero(tmp_path):
    alm = _alm(tmp_path)
    comps = autoria._componentes_de(
        alm, [{"insumo_codigo": "100", "rendimiento": 2.0}],
        "DIURNO", hist={"100": 0.0})
    assert comps[0].precio_unitario_hist == 1.0


def test_editar_apu_conserva_el_historico_de_los_componentes(tmp_path):
    """Antes, editar un APU ponía precio_unitario_hist=0.0 en TODOS sus componentes
    y tiraba a $0 las líneas cuyo insumo es huérfano/sin tarifa en catálogo."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("C3", "BASE GRANULAR", "M3", "DIURNO", "PAV")])
    alm.apus.insert_components([
        ApuComponent("C3", "DIURNO", "100", "CEMENTO GRIS", "KG", 2.0, 900.0),
        ApuComponent("C3", "DIURNO", "999", "INSUMO HUERFANO", "UN", 1.0, 75000.0),
    ])

    autoria.editar_apu(alm, "C3", "DIURNO", {"nombre": "BASE GRANULAR B",
        "unidad": "M3", "grupo": "PAV",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 3.0},
                        {"insumo_codigo": "999", "rendimiento": 1.0,
                         "insumo_nombre": "INSUMO HUERFANO", "unidad": "UN"}]})

    comps = {c.insumo_codigo: c for c in alm.apus.get_components("C3", "DIURNO")}
    assert comps["100"].precio_unitario_hist == 900.0      # heredado, no borrado
    assert comps["999"].precio_unitario_hist == 75000.0    # el huérfano conserva su respaldo
    assert comps["100"].rendimiento == 3.0                 # la edición sí se aplicó


# ------------------------------------------------------------------- duplicado
def _apu_origen(alm):
    """APU de origen con un insumo normal y uno huérfano (con histórico real)."""
    alm.apus.insert_apus([Apu("3454", "MEZCLA MD12", "M3", "DIURNO", "PAV")])
    alm.apus.insert_components([
        ApuComponent("3454", "DIURNO", "100", "CEMENTO GRIS", "KG", 2.0, 900.0),
        ApuComponent("3454", "DIURNO", "999", "MEZCLA MD12", "M3", 1.0, 480000.0),
    ])


def test_duplicar_hereda_historico_y_deja_el_insumo_nuevo_en_el_piso(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    out = autoria.crear_apu(alm, {
        "codigo": "3454-2", "turno": "DIURNO", "nombre": "MEZCLA MD13",
        "unidad": "M3", "grupo": "PAV",
        "componentes": [
            {"insumo_codigo": "100", "rendimiento": 2.0},
            {"insumo_codigo": "888", "rendimiento": 1.0,
             "insumo_nombre": "MEZCLA MD13", "unidad": "M3"}],
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})
    assert out["codigo"] == "3454-2" and out["n_componentes"] == 2
    comps = {c.insumo_codigo: c for c in alm.apus.get_components("3454-2", "DIURNO")}
    assert comps["100"].precio_unitario_hist == 900.0    # heredado del origen
    assert comps["888"].precio_unitario_hist == 1.0      # insumo nuevo -> piso
    # el origen queda intacto
    assert len(alm.apus.get_components("3454", "DIURNO")) == 2


def test_duplicar_conserva_las_marcas_de_subapu_del_origen(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    alm.apus.set_componente_subapu("3454", "DIURNO", 0, "NOCTURNO")
    autoria.crear_apu(alm, {
        "codigo": "3454-2", "turno": "DIURNO", "nombre": "MEZCLA MD13",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}],   # sin 'tipo'
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})
    comps = alm.apus.get_components("3454-2", "DIURNO")
    assert comps[0].tipo == "apu" and comps[0].ref_shift == "NOCTURNO"


def test_duplicar_origen_inexistente_lanza(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="origen ya no existe"):
        autoria.crear_apu(alm, {"codigo": "X", "turno": "DIURNO", "nombre": "X",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
            "duplicado_de": {"codigo": "NOPE", "turno": "DIURNO"}})


def test_duplicar_con_la_misma_identidad_lanza(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    with pytest.raises(ValueError, match="distinto al del APU de origen"):
        autoria.crear_apu(alm, {"codigo": "3454", "turno": "DIURNO", "nombre": "OTRO",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
            "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})


def test_duplicar_con_el_mismo_nombre_lanza(tmp_path):
    """Comparación normalizada: espacios, mayúsculas y puntuación no cuentan como cambio."""
    alm = _alm(tmp_path)
    _apu_origen(alm)
    for nombre in ("MEZCLA MD12", "  mezcla   md12 ", "MEZCLA MD12."):
        with pytest.raises(ValueError, match="nombre debe ser distinto"):
            autoria.crear_apu(alm, {"codigo": "3454-2", "turno": "DIURNO",
                "nombre": nombre,
                "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
                "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})


def test_duplicar_destino_existente_lanza(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    alm.apus.insert_apus([Apu("3454-2", "YA ESTABA", "M3", "DIURNO", "PAV")])
    with pytest.raises(ValueError):
        autoria.crear_apu(alm, {"codigo": "3454-2", "turno": "DIURNO", "nombre": "MD13",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
            "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})


def test_duplicar_deja_rastro_en_auditoria(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    autoria.crear_apu(alm, {"codigo": "3454-2", "turno": "DIURNO", "nombre": "MEZCLA MD13",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}],
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})
    eventos, _ = alm.auditoria.listar(limit=50, offset=0)
    creacion = [e for e in eventos if e["accion"] == "apu.crear"][0]
    assert creacion["contexto"]["origen"] == "duplicado"
    assert creacion["contexto"]["de"] == "3454"
    assert creacion["contexto"]["de_turno"] == "DIURNO"


def test_crear_apu_sin_duplicado_de_sigue_marcando_origen_individual(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    eventos, _ = alm.auditoria.listar(limit=50, offset=0)
    creacion = [e for e in eventos if e["accion"] == "apu.crear"][0]
    assert creacion["contexto"]["origen"] == "individual"
