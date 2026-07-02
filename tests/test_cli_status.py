import argparse

from apu_tool.datos.almacen import Almacen
from apu_tool.interfaz import cli


def test_cmd_status_no_crashea(tmp_path, monkeypatch, capsys):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    monkeypatch.setattr(cli, "get_almacen", lambda: alm)
    assert cli.cmd_status(argparse.Namespace()) == 0
    salida = capsys.readouterr().out
    assert "Insumos:" in salida   # el reporte se imprimió sin AttributeError
