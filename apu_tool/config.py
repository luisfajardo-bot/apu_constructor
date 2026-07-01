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
CORRIDAS_DB_PATH = DATA_DIR / "corridas.db"

# ---------------------------------------------------------------------------
# Modelo de IA. Por defecto Claude Haiku 4.5 (más barato; se puede subir con
# APU_AI_MODEL). La IA es OPCIONAL: si no hay API key el armador usa el matcher
# determinístico y nunca falla por ello.
# ---------------------------------------------------------------------------
AI_MODEL = os.environ.get("APU_AI_MODEL", "claude-haiku-4-5-20251001")
AI_ENABLED_ENV = "ANTHROPIC_API_KEY"  # si está presente, se habilita la IA

# Umbrales del matcher determinístico (similaridad 0..1).
MATCH_ACCEPT = 0.88   # >= se acepta automáticamente
MATCH_REVIEW = 0.55   # entre REVIEW y ACCEPT -> candidato dudoso (revisar)
#                     # < REVIEW -> sin match (armado por analogía / manual)

# Umbrales del cruce código+nombre (resolver de insumos, dominio/cruce.py).
CRUCE_UMBRAL = 0.60   # similitud mínima de nombre para aceptar un cruce aproximado
CRUCE_MARGEN = 0.10   # ventaja mínima del mejor candidato sobre el segundo

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


# ---------------------------------------------------------------------------
# Selección de backend de persistencia. Por defecto SQLite (local/dev/tests).
# En producción se usa Postgres (Supabase) si hay DATABASE_URL o se fuerza con
# APU_DB_BACKEND=postgres.
# ---------------------------------------------------------------------------
def database_url() -> str | None:
    return os.environ.get("DATABASE_URL") or None


def db_backend() -> str:
    """'postgres' | 'sqlite'. Postgres si se fuerza por env o hay DATABASE_URL."""
    if os.environ.get("APU_DB_BACKEND", "").strip().lower() == "postgres":
        return "postgres"
    return "postgres" if database_url() else "sqlite"


# ---------------------------------------------------------------------------
# Auth (Supabase). Todo por variables de entorno; sin secretos en el repo.
# ---------------------------------------------------------------------------
def supabase_project_ref() -> str | None:
    return os.environ.get("SUPABASE_PROJECT_REF") or None


def supabase_url() -> str | None:
    url = os.environ.get("SUPABASE_URL")
    if url:
        return url.rstrip("/")
    ref = supabase_project_ref()
    return f"https://{ref}.supabase.co" if ref else None


def supabase_issuer() -> str | None:
    base = supabase_url()
    return f"{base}/auth/v1" if base else None


def supabase_jwks_url() -> str | None:
    base = supabase_url()
    return f"{base}/auth/v1/.well-known/jwks.json" if base else None


def supabase_service_role_key() -> str | None:
    return os.environ.get("SUPABASE_SERVICE_ROLE_KEY") or None


def admin_emails() -> set[str]:
    raw = os.environ.get("APU_ADMIN_EMAILS", "")
    return {e.strip().lower() for e in raw.split(",") if e.strip()}
