# tests/test_fuente_dos_opciones.py
"""La fuente de un precio que se escribe es PRECIO IDU o COSTO INTERNO, nada más.
Lo ya guardado con otras etiquetas no se toca (ver el spec 2026-09-29)."""
import io
from types import SimpleNamespace

import openpyxl
import pytest

from apu_tool import config
from apu_tool.interfaz import cli as cli_mod
from tests.test_api_insumos import _XLSX, _cli


def test_normalizar_fuente_precio():
    assert config.normalizar_fuente_precio(" precio idu ", "X") == "PRECIO IDU"
    assert config.normalizar_fuente_precio("Costo Interno", "X") == "COSTO INTERNO"
    assert config.normalizar_fuente_precio("", "COSTO INTERNO") == "COSTO INTERNO"
    with pytest.raises(ValueError):
        config.normalizar_fuente_precio("PRECIO IDU 2026", "COSTO INTERNO")
    with pytest.raises(ValueError):
        config.normalizar_fuente_precio("", None)


def test_cambios_fuente_invalida_no_escribe(tmp_path):
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("100")[0].id
    r = cli.post("/api/insumos/cambios", json={"cambios": [
        {"insumo_id": iid, "precio": 1.0, "fuente": "COMPRAS"}]})
    assert r.json()["aplicados"] == 0 and len(r.json()["errores"]) == 1
    assert alm.precios.get_insumo_por_id(iid).precio == 350000.0


def test_cambios_sin_fuente_queda_costo_interno(tmp_path):
    cli, alm = _cli(tmp_path)
    iid = alm.precios.get_candidatos("200")[0].id
    r = cli.post("/api/insumos/cambios", json={"cambios": [{"insumo_id": iid, "precio": 5.0}]})
    assert r.json()["aplicados"] == 1
    assert alm.precios.get_insumo_por_id(iid).fuente_precio == "COSTO INTERNO"


def test_crear_insumo_fuente(tmp_path):
    cli, _ = _cli(tmp_path)
    base = {"codigo": "900", "nombre": "Nuevo", "unidad": "UN", "precio": 10}
    assert cli.post("/api/insumos/crear", json={**base, "fuente": "COMPRAS"}).status_code == 400
    r = cli.post("/api/insumos/crear", json=base)
    assert r.status_code == 200, r.text
    assert r.json()["fuente"] == "COSTO INTERNO"


def test_importar_fuente_invalida_es_400(tmp_path):
    cli, _ = _cli(tmp_path)
    wb = openpyxl.Workbook(); ws = wb.active
    ws.append(["CODIGO", "PRECIO"]); ws.append(["100", 390000])
    buf = io.BytesIO(); wb.save(buf)
    r = cli.post("/api/insumos/importar/preview", data={"fuente_import": "PRECIO IDU 2026"},
                 files={"archivo": ("l.xlsx", buf.getvalue(), _XLSX)})
    assert r.status_code == 400


def test_cli_update_price_fuente(capsys, monkeypatch):
    escrito = {}

    class _Precios:
        def get_candidatos(self, codigo):
            return [SimpleNamespace(id=1, codigo="7", nombre="Cemento", precio=5.0,
                                    fuente_precio=escrito.get("fuente", ""))]
        def set_precio(self, codigo, precio, fuente, nombre=None):
            escrito["fuente"] = fuente

    monkeypatch.setattr(cli_mod, "get_almacen", lambda: SimpleNamespace(precios=_Precios()))
    args = dict(codigo="7", precio=5.0, nombre=None)
    assert cli_mod.cmd_db_update_price(SimpleNamespace(**args, fuente="COMPRAS")) == 1
    assert "fuente" not in escrito
    assert cli_mod.cmd_db_update_price(SimpleNamespace(**args, fuente=None)) == 0
    assert escrito["fuente"] == "COSTO INTERNO"
