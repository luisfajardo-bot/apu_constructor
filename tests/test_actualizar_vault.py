from pathlib import Path

from scripts.actualizar_vault import (
    fecha_desde_nombre,
    titulo_desde_markdown,
)


def test_titulo_desde_markdown_usa_primer_encabezado(tmp_path):
    archivo = tmp_path / "algo.md"
    archivo.write_text("> nota\n\n# Mi Título\n\ncontenido\n", encoding="utf-8")
    assert titulo_desde_markdown(archivo) == "Mi Título"


def test_titulo_desde_markdown_fallback_sin_encabezado(tmp_path):
    archivo = tmp_path / "sin-encabezado.md"
    archivo.write_text("solo texto, sin encabezado\n", encoding="utf-8")
    assert titulo_desde_markdown(archivo) == "Sin encabezado"


def test_fecha_desde_nombre_con_prefijo():
    assert fecha_desde_nombre(Path("2026-07-24-algo-design.md")) == "2026-07-24"


def test_fecha_desde_nombre_sin_prefijo():
    assert fecha_desde_nombre(Path("README.md")) is None
