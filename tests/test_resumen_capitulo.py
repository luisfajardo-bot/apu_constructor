"""Resumen por capítulo: una sola función suma dinero, y la usan API, web y Excel."""
from apu_tool.dominio.report_categorizado import resumen_por_capitulo
from apu_tool.nucleo.models import (
    AssembledApu, CostedComponent, LicitacionItem, MatchStatus,
)


def _item(cap_cod, cap_nom, cant, con_aiu, sin_aiu, item="1.001"):
    return LicitacionItem(
        item=item, descripcion=f"ACT {item}", unidad="M2", cantidad=cant,
        precio_contractual=con_aiu, precio_contractual_sin_aiu=sin_aiu,
        shift="DIURNO", categoria=f"{cap_cod} · {cap_nom}",
        capitulo_codigo=cap_cod, capitulo_nombre=cap_nom, item_pago_original=item)


def _ens(item, costo_unitario, apu_codigo="A1", costo_manual=False):
    comps = []
    if costo_unitario > 0 and not costo_manual:
        comps = [CostedComponent(
            insumo_codigo="I1", insumo_nombre="CEMENTO", unidad="KG", rendimiento=1.0,
            precio_unitario=costo_unitario, fuente_precio="COSTO INTERNO",
            costo=costo_unitario)]
    return AssembledApu(
        item=item, apu_codigo=apu_codigo, apu_nombre="APU", unidad=item.unidad,
        shift="DIURNO", componentes=comps, costo_unitario=costo_unitario,
        status=MatchStatus.AUTO, confianza=1.0)


def test_agrupa_por_capitulo_en_orden_de_aparicion():
    apus = [_ens(_item("2", "PAVIMENTOS", 10, 100, 80), 60),
            _ens(_item("1", "PRELIMINARES", 5, 200, 160), 120),
            _ens(_item("2", "PAVIMENTOS", 3, 100, 80), 60)]
    res = resumen_por_capitulo(apus)
    assert [r["codigo"] for r in res] == ["2", "1"]
    assert [r["nombre"] for r in res] == ["PAVIMENTOS", "PRELIMINARES"]
    assert [r["orden"] for r in res] == [1, 2]
    assert [r["actividades"] for r in res] == [2, 1]


def test_suma_las_dos_bases_del_contractual_y_el_costo():
    apus = [_ens(_item("1", "PRELIMINARES", 10, 1351, 1056), 900),
            _ens(_item("1", "PRELIMINARES", 4, 1508, 1179), 1000)]
    r = resumen_por_capitulo(apus)[0]
    assert r["contractual"] == 10 * 1351 + 4 * 1508            # con AIU
    assert r["contractual_sin_aiu"] == 10 * 1056 + 4 * 1179    # sin AIU
    assert r["costo"] == 10 * 900 + 4 * 1000
    assert r["diferencia"] == r["contractual"] - r["costo"]
    assert abs(r["margen_pct"] - r["diferencia"] / r["contractual"]) < 1e-9


def test_sin_apu_cuenta_y_marca_el_capitulo_incompleto():
    completa = _ens(_item("1", "PRELIMINARES", 10, 100, 80), 60)
    huerfana = _ens(_item("1", "PRELIMINARES", 5, 100, 80, item="1.002"), 0.0,
                    apu_codigo=None)
    r = resumen_por_capitulo([completa, huerfana])[0]
    assert r["actividades"] == 2
    assert r["con_apu"] == 1
    assert r["sin_apu"] == 1
    assert r["completo"] is False


def test_capitulo_entero_costeado_queda_completo():
    apus = [_ens(_item("1", "PRELIMINARES", 10, 100, 80), 60),
            _ens(_item("1", "PRELIMINARES", 5, 100, 80, item="1.002"), 40)]
    r = resumen_por_capitulo(apus)[0]
    assert r["sin_apu"] == 0
    assert r["completo"] is True
    assert r["cobertura"] == 1.0
    assert r["cobertura_valor"] == 1.0


def test_cobertura_por_conteo_y_por_valor_no_son_lo_mismo():
    # Justificación de la métrica ponderada: 3 de 4 actividades costeadas (75 % por
    # conteo) pero la que falta vale el 90 % del capítulo.
    chicas = [_ens(_item("2", "PAVIMENTOS", 1, 100, 80, item=f"2.00{i}"), 60)
              for i in range(1, 4)]
    grande = _ens(_item("2", "PAVIMENTOS", 1, 2700, 2100, item="2.004"), 0.0,
                  apu_codigo=None)
    r = resumen_por_capitulo(chicas + [grande])[0]
    assert r["cobertura"] == 0.75
    assert r["cobertura_valor"] == 300 / 3000
    assert r["completo"] is False


def test_costo_puesto_a_mano_cuenta_como_costeado():
    # Misma regla que seqs_sin_apu: sin APU pero con costo declarado positivo SÍ cuenta.
    a_mano = _ens(_item("1", "PRELIMINARES", 10, 100, 80), 100.0, apu_codigo=None,
                  costo_manual=True)
    r = resumen_por_capitulo([a_mano])[0]
    assert r["sin_apu"] == 0
    assert r["costo"] == 1000


def test_items_sin_capitulo_caen_en_un_grupo_con_nombre():
    plano = LicitacionItem(item="1", descripcion="X", unidad="M2", cantidad=1.0,
                           precio_contractual=100.0, shift="DIURNO")
    r = resumen_por_capitulo([_ens(plano, 60)])[0]
    assert r["codigo"] == ""
    assert r["nombre"] == "(sin capítulo)"


def test_lista_vacia_no_revienta():
    assert resumen_por_capitulo([]) == []


def test_contractual_en_cero_no_divide_por_cero():
    gratis = _ens(_item("1", "PRELIMINARES", 10, 0, 0), 0.0, apu_codigo=None)
    r = resumen_por_capitulo([gratis])[0]
    assert r["margen_pct"] == 0.0
    assert r["cobertura_valor"] == 0.0


def test_un_apu_en_cero_deja_el_capitulo_incompleto():
    # Tiene APU asignado, así que no cuenta como sin_apu, pero su costo es 0: la regla
    # "nada en $0" lo marca por alertas_costeo y el capítulo no puede decirse completo.
    en_cero = _ens(_item("1", "PRELIMINARES", 10, 100, 80), 0.0, apu_codigo="A1")
    r = resumen_por_capitulo([en_cero])[0]
    assert r["sin_apu"] == 0
    assert r["completo"] is False
