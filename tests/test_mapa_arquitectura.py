from pathlib import Path

from scripts.mapa_arquitectura import (
    dependencias_entre_paquetes,
    diagrama_mermaid,
    escanear_apu_tool,
    generar_mapa_arquitectura,
    imports_internos,
    paquete_de_modulo,
    responsabilidad_de_modulo,
    seccion_paquete,
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


def test_escanear_apu_tool(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "dominio").mkdir(parents=True)
    (raiz / "nucleo" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "dominio" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "nucleo" / "models.py").write_text('"""Tipos puros."""\n', encoding="utf-8")
    (raiz / "dominio" / "pricing.py").write_text(
        '"""Motor de costos."""\nfrom apu_tool.nucleo.models import Insumo\n',
        encoding="utf-8",
    )
    (raiz / "config.py").write_text('"""Config transversal."""\n', encoding="utf-8")

    registros = escanear_apu_tool(raiz)

    por_modulo = {r["modulo"]: r for r in registros}
    assert set(por_modulo) == {
        "apu_tool.nucleo.models",
        "apu_tool.dominio.pricing",
        "apu_tool.config",
    }
    assert por_modulo["apu_tool.dominio.pricing"]["paquete"] == "dominio"
    assert por_modulo["apu_tool.dominio.pricing"]["archivo"] == "pricing.py"
    assert por_modulo["apu_tool.dominio.pricing"]["imports"] == ["apu_tool.nucleo.models"]
    assert por_modulo["apu_tool.dominio.pricing"]["responsabilidad"] == "Motor de costos."
    assert por_modulo["apu_tool.config"]["paquete"] == "raíz"
    assert por_modulo["apu_tool.config"]["archivo"] == "config.py"


def test_escanear_apu_tool_agrupa_pg_bajo_datos(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "datos" / "pg").mkdir(parents=True)
    (raiz / "datos" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "datos" / "pg" / "__init__.py").write_text("", encoding="utf-8")
    (raiz / "datos" / "pg" / "precios_pg.py").write_text(
        '"""Backend Postgres de precios."""\n', encoding="utf-8"
    )

    (registro,) = escanear_apu_tool(raiz)

    assert registro["modulo"] == "apu_tool.datos.pg.precios_pg"
    assert registro["paquete"] == "datos"
    assert registro["archivo"] == "pg/precios_pg.py"


def test_escanear_apu_tool_excluye_init(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "nucleo" / "__init__.py").write_text("", encoding="utf-8")

    assert escanear_apu_tool(raiz) == []


def test_dependencias_entre_paquetes_deduplica_y_excluye_autoreferencias():
    registros = [
        {"paquete": "dominio", "imports": ["apu_tool.nucleo.models"]},
        {"paquete": "dominio", "imports": ["apu_tool.nucleo.models", "apu_tool.dominio.otro"]},
        {"paquete": "servicio", "imports": ["apu_tool.dominio.pricing"]},
    ]

    aristas = dependencias_entre_paquetes(registros)

    assert aristas == [("dominio", "nucleo"), ("servicio", "dominio")]


def test_diagrama_mermaid_formato():
    diagrama = diagrama_mermaid([("dominio", "nucleo"), ("servicio", "dominio")])

    assert diagrama == (
        "```mermaid\n"
        "flowchart TD\n"
        "    dominio --> nucleo\n"
        "    servicio --> dominio\n"
        "```\n"
    )


def test_diagrama_mermaid_vacio():
    assert diagrama_mermaid([]) == "```mermaid\nflowchart TD\n```\n"


def test_seccion_paquete_tabla_ordenada_por_archivo():
    registros = [
        {"paquete": "dominio", "archivo": "pricing.py", "responsabilidad": "Motor de costos"},
        {"paquete": "dominio", "archivo": "alertas.py", "responsabilidad": "Alertas de costeo"},
        {"paquete": "nucleo", "archivo": "models.py", "responsabilidad": "Tipos puros"},
    ]

    tabla = seccion_paquete("dominio", registros)

    assert tabla == (
        "| Archivo | Responsabilidad |\n"
        "| --- | --- |\n"
        "| `alertas.py` | Alertas de costeo |\n"
        "| `pricing.py` | Motor de costos |\n"
    )


def test_seccion_paquete_vacia():
    assert seccion_paquete("interfaz", []) == "_(vacío)_\n"


def test_generar_mapa_arquitectura_integracion(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "dominio").mkdir(parents=True)
    (raiz / "nucleo" / "models.py").write_text('"""Tipos puros."""\n', encoding="utf-8")
    (raiz / "dominio" / "pricing.py").write_text(
        '"""Motor de costos."""\nfrom apu_tool.nucleo.models import Insumo\n',
        encoding="utf-8",
    )

    mapa = generar_mapa_arquitectura(raiz)

    assert "# Mapa de módulos — apu_tool/" in mapa
    assert "No editar" in mapa
    assert "dominio --> nucleo" in mapa
    assert "`models.py`" in mapa
    assert "`pricing.py`" in mapa
    assert "Motor de costos" in mapa


def test_generar_mapa_arquitectura_es_idempotente(tmp_path):
    raiz = tmp_path / "apu_tool"
    (raiz / "nucleo").mkdir(parents=True)
    (raiz / "nucleo" / "models.py").write_text('"""Tipos puros."""\n', encoding="utf-8")

    assert generar_mapa_arquitectura(raiz) == generar_mapa_arquitectura(raiz)
