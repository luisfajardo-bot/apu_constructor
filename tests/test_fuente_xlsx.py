"""La fuente Excel se da SIEMPRE de forma explícita: no se adivina por carpeta."""
from pathlib import Path

from apu_tool import config


def test_sin_variable_no_adivina(monkeypatch):
    # Sin APU_SOURCE_XLSX no devuelve nada, AUNQUE haya .xlsx en la raíz del proyecto.
    monkeypatch.delenv("APU_SOURCE_XLSX", raising=False)
    assert config.detect_source_xlsx() is None


def test_usa_la_variable(monkeypatch, tmp_path):
    f = tmp_path / "licitacion.xlsx"
    f.write_text("x", encoding="utf-8")
    monkeypatch.setenv("APU_SOURCE_XLSX", str(f))
    assert config.detect_source_xlsx() == f


def test_variable_a_ruta_inexistente_devuelve_none(monkeypatch, tmp_path):
    monkeypatch.setenv("APU_SOURCE_XLSX", str(tmp_path / "no_existe.xlsx"))
    assert config.detect_source_xlsx() is None
