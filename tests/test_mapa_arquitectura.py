from pathlib import Path

from scripts.mapa_arquitectura import (
    imports_internos,
    paquete_de_modulo,
    responsabilidad_de_modulo,
)


def test_responsabilidad_de_modulo_usa_primera_linea_del_docstring(tmp_path):
    archivo = tmp_path / "x.py"
    archivo.write_text(
        '"""Primera línea.\n\nMás texto que no importa.\n"""\ndef f(): pass\n',
        encoding="utf-8",
    )
    assert responsabilidad_de_modulo(archivo) == "Primera línea."


def test_responsabilidad_de_modulo_fallback_sin_docstring(tmp_path):
    archivo = tmp_path / "mi_modulo.py"
    archivo.write_text("def f(): pass\n", encoding="utf-8")
    assert responsabilidad_de_modulo(archivo) == "Mi modulo"


def test_imports_internos_detecta_apu_tool_absoluto(tmp_path):
    archivo = tmp_path / "x.py"
    archivo.write_text(
        "import re\n"
        "from pathlib import Path\n"
        "from apu_tool.dominio.pricing import PricingEngine\n"
        "from apu_tool.nucleo.models import Insumo\n",
        encoding="utf-8",
    )
    assert imports_internos(archivo) == [
        "apu_tool.dominio.pricing",
        "apu_tool.nucleo.models",
    ]


def test_imports_internos_ignora_relativos(tmp_path):
    archivo = tmp_path / "x.py"
    archivo.write_text(
        "from . import hermano\nfrom ..nucleo import models\n", encoding="utf-8"
    )
    assert imports_internos(archivo) == []


def test_paquete_de_modulo():
    assert paquete_de_modulo("apu_tool.dominio.pricing") == "dominio"
    assert paquete_de_modulo("apu_tool.datos.pg.precios_pg") == "datos"
    assert paquete_de_modulo("apu_tool.config") == "raíz"
