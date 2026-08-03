"""La barra de estado de la GUI cuenta los insumos visibles, no el total con ocultos.

Es el gemelo de `tests/test_cli_status.py` para la otra interfaz local. El repo no tenía
tests de Tkinter porque necesitan display: en CI (Linux, sin pantalla, y probablemente sin
el paquete `python3-tk`) este módulo se **saltea**, y corre en la máquina del desarrollador,
que es justo donde alguien abre la GUI.

El guard de la raíz de Tk atrapa cualquier excepción a propósito: preferimos que este
módulo se saltee antes que dejar CI en rojo por un problema de entorno gráfico, que no es
lo que estos tests vinieron a proteger.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo

tk = pytest.importorskip("tkinter", reason="tkinter no está instalado")


@pytest.fixture()
def raiz():
    """Ventana oculta (`withdraw`) y sin `mainloop`: se construye, se lee y se destruye."""
    try:
        root = tk.Tk()
    except Exception as e:                       # sin display, sin Xvfb, sin theme...
        pytest.skip(f"no se pudo crear la ventana de Tk: {e}")
    root.withdraw()
    try:
        yield root
    finally:
        root.destroy()


def _alm_con_un_oculto(tmp_path) -> Almacen:
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    ids = [alm.precios.crear_insumo(Insumo(c, n, "UN", "MAT", 100.0, "PRECIO IDU"))
           for c, n in (("1", "UNO"), ("2", "DOS"), ("3", "TRES"))]
    alm.precios.set_oculto(ids[0], True)
    return alm


def test_barra_de_estado_cuenta_los_visibles(tmp_path, monkeypatch, raiz):
    """3 insumos, 1 oculto -> la barra dice 2.

    Antes decía `counts()["insumos"]` (el total): con ~990 códigos ocultos, la web mostraba
    7167 y esta barra 8157.
    """
    from apu_tool.interfaz import gui

    alm = _alm_con_un_oculto(tmp_path)
    monkeypatch.setattr(gui, "get_almacen", lambda: alm)

    app = gui.ApuApp(raiz)                       # su __init__ ya llama a _refresh_status()
    texto = app.status_lbl.cget("text")

    assert "Insumos: 2" in texto, f"la barra dice: {texto!r}"
    assert "Insumos: 3" not in texto
