"""La IA nunca debe ver dinero: estas pruebas blindan esa frontera."""
import pytest

from apu_tool.dominio import privacy
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


def test_peaje_valor_no_puede_ir_a_la_ia():
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money({"proyecto": {"km_botadero": 34, "peaje_valor": 12400}})
    # las distancias y los rendimientos SÍ pueden (son cantidades, no dinero)
    privacy.assert_no_money({"proyecto": {"km_botadero": 34, "km_mezclas": 28},
                             "componentes": [{"rendimiento": 33.6}]})
