"""
Configuración central y rutas del proyecto.

Todo lo generado (base de datos, salidas, ejemplos) se queda dentro de la carpeta
del proyecto. La ruta al Excel se da SIEMPRE de forma explícita: con `--xlsx <ruta>`
en los comandos, o con la variable de entorno APU_SOURCE_XLSX. No se adivina.
"""
from __future__ import annotations

import os
from pathlib import Path

# Raíz del proyecto = carpeta que contiene este paquete.
PROJECT_ROOT = Path(__file__).resolve().parent.parent

# Carpetas de trabajo (se crean si no existen).
DATA_DIR = PROJECT_ROOT / "data"
OUTPUT_DIR = PROJECT_ROOT / "salidas"
SAMPLE_DIR = PROJECT_ROOT / "ejemplos"

# Bases canónicas separadas (fuente de verdad).
PRECIOS_DB_PATH = DATA_DIR / "precios.db"
APUS_DB_PATH = DATA_DIR / "apus.db"

# ---------------------------------------------------------------------------
# Modelo de IA. Por defecto Claude Opus 4.8. La IA es OPCIONAL: si no hay API key
# el armador usa el matcher determinístico y nunca falla por ello.
# ---------------------------------------------------------------------------
AI_MODEL = os.environ.get("APU_AI_MODEL", "claude-opus-4-8")
AI_ENABLED_ENV = "ANTHROPIC_API_KEY"  # si está presente, se habilita la IA

# Umbrales del matcher determinístico (similaridad 0..1).
MATCH_ACCEPT = 0.88   # >= se acepta automáticamente
MATCH_REVIEW = 0.55   # entre REVIEW y ACCEPT -> candidato dudoso (revisar)
#                     # < REVIEW -> sin match (armado por analogía / manual)

# Etiquetas de turno.
SHIFT_DIURNO = "DIURNO"
SHIFT_NOCTURNO = "NOCTURNO"

# Fuentes de precio que se consideran CONFIDENCIALES (costo interno / margen).
# Cualquier fuente que NO sea pública se trata como interna.
PUBLIC_PRICE_SOURCES = {"PRECIO IDU"}


def classify_price_source(fuente: str) -> str:
    """Clasifica una fuente de precio como 'publico' o 'interno' (confidencial)."""
    f = (fuente or "").strip().upper()
    return "publico" if f in {s.upper() for s in PUBLIC_PRICE_SOURCES} else "interno"


def detect_source_xlsx() -> Path | None:
    """Devuelve la ruta al Excel definida en la variable APU_SOURCE_XLSX, o None.

    NO adivina: la ruta debe darse siempre de forma explícita — con `--xlsx <ruta>`
    en los comandos, o con esta variable de entorno. Antes tomaba "el primer .xlsx
    de la carpeta" (orden alfabético), lo que escogía archivos al azar; eso se eliminó.
    """
    override = os.environ.get("APU_SOURCE_XLSX")
    if not override:
        return None
    p = Path(override)
    return p if p.exists() else None


def ensure_dirs() -> None:
    for d in (DATA_DIR, OUTPUT_DIR, SAMPLE_DIR):
        d.mkdir(parents=True, exist_ok=True)


def ai_available() -> bool:
    """True si hay credenciales para usar la IA."""
    return bool(os.environ.get(AI_ENABLED_ENV))
