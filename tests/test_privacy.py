"""La IA nunca debe ver dinero: estas pruebas blindan esa frontera."""
import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.privacy import (
    PrivacyViolation, assert_no_money, licitacion_item_to_dict,
)
from apu_tool.nucleo.models import (
    DePricedApu,
    DePricedComponent,
    LicitacionItem,
)


def test_depriced_apu_dict_has_no_money():
    apu = DePricedApu(
        codigo="3010", nombre="DEMOLICION", unidad="M3", shift="DIURNO", grupo="X",
        componentes=(DePricedComponent("4279", "CUADRILLA", "HR", 0.5),),
    )
    d = privacy.depriced_apu_to_dict(apu)
    privacy.assert_no_money(d)  # no debe lanzar
    assert "precio" not in privacy.safe_json(apu := d).lower()


def test_licitacion_item_dict_omits_price():
    item = LicitacionItem("1", "EXCAVACION", "M3", 10, 99999, "DIURNO")
    d = privacy.licitacion_item_to_dict(item)
    assert "precio_contractual" not in d
    assert "99999" not in privacy.safe_json(d)


def test_assert_no_money_detects_violation():
    bad = {"actividad": "x", "precio": 1000}
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money(bad)


def test_assert_no_money_detects_nested_violation():
    bad = {"a": {"b": [{"costo_total": 5}]}}
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money(bad)


def test_rendimiento_is_allowed():
    ok = {"componentes": [{"rendimiento": 1.5, "cantidad": 10}]}
    privacy.assert_no_money(ok)  # cantidades no son dinero


def test_costo_manual_es_campo_prohibido():
    """assert_no_money mira NOMBRES de clave: el campo nuevo tiene que estar en la
    denylist aunque hoy ningún payload de la IA lo arme."""
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money({"seq": 1, "costo_manual": 92106000.0})


def test_plan_json_es_dinero_y_no_pasa():
    """`corrida.plan_json` guarda las líneas de licitación ya interpretadas, y cada
    una lleva su `precio_contractual` adentro: es dinero, aunque la clave no lo
    parezca. CLAUDE.md lo pide literal — todo campo monetario nuevo entra acá.

    Hoy ningún payload hacia la IA lo incluye (la revisión arma el suyo campo por
    campo), pero el guardián mira NOMBRES DE CLAVE: si no está en la lista, el día que
    alguien vuelque la fila entera no salta nada."""
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money({"corrida": {"plan_json": "[]"}})


# ------------------------------------------------- ruta IDU (Formulario 1)
@pytest.mark.parametrize("clave", [
    "precio_contractual_sin_aiu", "contractual_total_sin_aiu", "origen_json",
    "conciliacion", "total_excel", "subtotales_excel", "unitario_sin_aiu",
    "unitario_con_aiu", "contractual_con_aiu", "contractual_sin_aiu",
])
def test_los_campos_monetarios_de_la_ruta_idu_disparan_la_violacion(clave):
    with pytest.raises(PrivacyViolation):
        assert_no_money({"actividad": {clave: 1351}})


def test_el_capitulo_si_puede_llegar_a_la_ia():
    # Texto, no dinero: saber que la actividad es de RED DE ACUEDUCTO es estructura.
    item = LicitacionItem(
        item="11.005", descripcion="TUBERÍA PVC", unidad="ML", cantidad=120.0,
        precio_contractual=95463.0, shift="DIURNO",
        precio_contractual_sin_aiu=74627.0,
        capitulo_codigo="11", capitulo_nombre="RED DE ACUEDUCTO",
        item_pago_original="11.005", fila_origen=1420, codigo_sugerido="3903")
    d = licitacion_item_to_dict(item)
    assert d["capitulo_codigo"] == "11"
    assert d["capitulo_nombre"] == "RED DE ACUEDUCTO"
    assert_no_money(d)      # no levanta


def test_ningun_precio_del_item_cruza_la_frontera():
    item = LicitacionItem(
        item="11.005", descripcion="TUBERÍA PVC", unidad="ML", cantidad=120.0,
        precio_contractual=95463.0, shift="DIURNO",
        precio_contractual_sin_aiu=74627.0)
    d = licitacion_item_to_dict(item)
    assert "precio_contractual" not in d
    assert "precio_contractual_sin_aiu" not in d
    # Y tampoco por valor: ninguno de los dos montos aparece en el payload.
    assert 95463.0 not in d.values()
    assert 74627.0 not in d.values()


def test_el_origen_de_la_corrida_nunca_viaja_entero():
    # origen_json lleva la conciliación (dinero) adentro: misma razón que plan_json.
    with pytest.raises(PrivacyViolation):
        assert_no_money({"corrida": {"origen_json": {"entidad": "IDU"}}})


def test_las_claves_del_resumen_por_capitulo_estan_cubiertas():
    """Todo lo que `resumen_por_capitulo` devuelve y sea dinero dispara la violación.

    Hoy ese dict no llega a la IA por ningún camino —lo consumen la API HTTP y las dos
    hojas de Excel—, pero sus claves son genéricas (`contractual`, `diferencia`) y el
    día que alguien quiera darle "contexto del capítulo" al modelo se filtrarían sin
    que nada salte. Este test recorre las claves REALES de la función, así que una
    clave monetaria nueva que se agregue allá rompe acá.
    """
    from apu_tool.dominio.report_categorizado import resumen_por_capitulo
    from apu_tool.nucleo.models import AssembledApu, MatchStatus

    item = LicitacionItem(item="2.001", descripcion="X", unidad="M3", cantidad=1.0,
                          precio_contractual=100.0, shift="DIURNO",
                          capitulo_codigo="2", capitulo_nombre="PAVIMENTOS")
    fila = resumen_por_capitulo([AssembledApu(
        item=item, apu_codigo="A1", apu_nombre="A", unidad="M3", shift="DIURNO",
        componentes=[], costo_unitario=0.0, status=MatchStatus.NEW, confianza=0.0)])[0]

    # Las que son dinero tienen que estar cubiertas por nombre.
    MONETARIAS = {"contractual", "contractual_sin_aiu", "costo", "diferencia",
                  "margen_pct", "cobertura_valor"}
    assert MONETARIAS <= set(fila), "cambió la forma de resumen_por_capitulo"
    for clave in MONETARIAS:
        with pytest.raises(PrivacyViolation):
            assert_no_money({"capitulo": {clave: 1}})


def test_una_advertencia_con_monto_en_el_texto_NO_la_atrapa_el_guardian():
    """Tripwire del hueco conocido, documentado en vez de escondido.

    `assert_no_money` mira nombres de clave, no valores: una `Advertencia` cuyo
    `detalle` dice «El Excel dice 67.153…» pasa limpia. Por eso la regla operativa es
    que una advertencia NUNCA entra a un payload hacia la IA (ver su docstring y
    CLAUDE.md). Si algún día alguien hace que el guardián mire contenido, este test
    falla y hay que venir a decidir a conciencia — que es justo lo que queremos.
    """
    from apu_tool.dominio.presupuesto import Advertencia
    aviso = Advertencia("total_fila_no_concilia", 16,
                        "El Excel dice 100.290.134 y el recálculo da 100.290.135.")
    assert_no_money({"advertencia": aviso.to_dict()})   # NO levanta: ese es el hueco
    assert "100.290.134" in aviso.to_dict()["detalle"]


def test_los_modulos_de_ia_no_importan_el_parser_ni_el_reporte():
    """Guarda mecánica: el parser y el resumen por capítulo manejan dinero y texto con
    montos adentro. Los tres módulos que hablan con la IA no pueden ni importarlos.

    Espejo de `test_servicio_no_importa_ai_assist`. Hoy ninguno lo hace; esto lo fija.
    """
    from pathlib import Path
    raiz = Path(__file__).resolve().parent.parent / "apu_tool" / "dominio"
    for nombre in ("ai_assist.py", "revision.py", "composicion_agente.py"):
        fuente = (raiz / nombre).read_text(encoding="utf-8")
        for prohibido in ("presupuesto", "report_categorizado", "report"):
            assert f"import {prohibido}" not in fuente, f"{nombre} importa {prohibido}"
            assert f"from apu_tool.dominio.{prohibido}" not in fuente, nombre
