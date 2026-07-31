"""El auto-seed trabaja sobre la base del request, no sobre una que se arma sola.

`ensure_seeded()` se construía su propio `Almacen()` con las rutas por defecto de
`config`, así que el guard (`alm.counts()["apus"] == 0`) preguntaba por una base y el
seed escribía en otra. Consecuencias reales: 4 tests de API en rojo en CI (bd5fece), un
pool de conexiones huérfano por disparo en producción, y la posibilidad de armar una
corrida contra una biblioteca vacía sin que nada avise.

Ver docs/superpowers/specs/2026-07-31-ensure-seeded-almacen-inyectado-design.md
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import pipeline


def _alm_vacio(tmp_path) -> Almacen:
    """Almacén temporal SIN insumos ni APUs: es la condición que dispara el auto-seed
    (`ensure_seeded` solo semilla si las dos cuentas están en cero)."""
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_ensure_seeded_semilla_sobre_el_almacen_recibido(tmp_path, monkeypatch):
    alm = _alm_vacio(tmp_path)
    recibidos = []

    def fake_seed(almacen, **kwargs):
        recibidos.append(almacen)
        return {"apus": 0, "insumos": 0}

    monkeypatch.setattr(pipeline, "seed", fake_seed)

    pipeline.ensure_seeded(alm)

    assert recibidos, "no se llamó a seed"
    assert recibidos[0] is alm, "seed recibió otro almacén, no el que se le pasó"


def test_ensure_seeded_sin_almacen_usa_el_global(tmp_path, monkeypatch):
    """El default sigue existiendo: es lo que usan CLI y GUI, y no debe cambiar."""
    global_alm = _alm_vacio(tmp_path)
    monkeypatch.setattr(pipeline, "get_almacen", lambda: global_alm)
    recibidos = []
    monkeypatch.setattr(pipeline, "seed",
                        lambda almacen, **kw: (recibidos.append(almacen),
                                               {"apus": 0, "insumos": 0})[1])

    pipeline.ensure_seeded()

    assert recibidos[0] is global_alm


def test_sin_excel_historico_levanta_biblioteca_vacia(tmp_path, monkeypatch):
    """Sin fuente de la que semillar, el error tiene que ser explícito y del dominio.

    Antes salía un `FileNotFoundError` crudo que la API devolvía como 500.
    """
    monkeypatch.delenv("APU_SOURCE_XLSX", raising=False)   # detect_source_xlsx() -> None
    alm = _alm_vacio(tmp_path)

    with pytest.raises(pipeline.BibliotecaVacia) as exc:
        pipeline.ensure_seeded(alm)

    assert "biblioteca de APUs está vacía" in str(exc.value)


def test_biblioteca_poblada_no_semilla(tmp_path, monkeypatch):
    """No-regresión: con APUs en la biblioteca, ni se intenta semillar."""
    from apu_tool.nucleo.models import Apu
    alm = _alm_vacio(tmp_path)
    alm.apus.insert_apus([Apu("A1", "EXCAVACION", "M3", "DIURNO", "MT")])

    def explota(*a, **kw):
        raise AssertionError("no debía llamar a seed")

    monkeypatch.setattr(pipeline, "seed", explota)

    assert pipeline.ensure_seeded(alm)["apus"] == 1
