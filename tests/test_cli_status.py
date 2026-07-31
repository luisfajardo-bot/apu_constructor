import argparse

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.interfaz import cli


def test_cmd_status_no_crashea(tmp_path, monkeypatch, capsys):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    monkeypatch.setattr(cli, "get_almacen", lambda: alm)
    assert cli.cmd_status(argparse.Namespace()) == 0
    salida = capsys.readouterr().out
    assert "Insumos:" in salida   # el reporte se imprimió sin AttributeError


def test_cmd_status_cuenta_los_visibles_no_el_total(tmp_path, monkeypatch, capsys):
    """El CLI cuenta lo mismo que `/api/status` y que la tabla de Insumos de la web.

    Antes imprimía `counts()["insumos"]` (todas las filas, ocultos incluidos): con ~990
    códigos ocultos, la web decía 7167 y el CLI 8157 — dos números para lo mismo.
    """
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    ids = [alm.precios.crear_insumo(Insumo(c, n, "UN", "MAT", 100.0, "PRECIO IDU"))
           for c, n in (("1", "UNO"), ("2", "DOS"), ("3", "TRES"))]
    alm.precios.set_oculto(ids[0], True)
    monkeypatch.setattr(cli, "get_almacen", lambda: alm)

    assert cli.cmd_status(argparse.Namespace()) == 0

    linea = next(l for l in capsys.readouterr().out.splitlines()
                 if l.strip().startswith("Insumos:"))
    assert linea.split()[-1] == "2", f"esperaba 2 visibles, imprimió: {linea!r}"
