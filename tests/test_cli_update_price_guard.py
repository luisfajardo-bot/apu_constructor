from types import SimpleNamespace
from apu_tool.interfaz import cli


def test_update_price_rechaza_cero(capsys, monkeypatch):
    # No debe intentar escribir: retorna código de error y no llama set_precio.
    llamado = {"set": False}

    class _Precios:
        def get_candidatos(self, codigo):
            return [SimpleNamespace(id=1, nombre="Cemento")]
        def set_precio(self, *a, **k):
            llamado["set"] = True

    class _Alm:
        precios = _Precios()

    monkeypatch.setattr(cli, "get_almacen", lambda: _Alm())
    rc = cli.cmd_db_update_price(SimpleNamespace(codigo="7", precio=0.0, nombre=None, fuente=None))
    assert rc == 1
    assert llamado["set"] is False
    assert "mayor que 0" in capsys.readouterr().out
