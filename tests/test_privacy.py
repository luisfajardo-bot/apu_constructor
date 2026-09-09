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
