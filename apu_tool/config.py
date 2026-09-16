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
# Modelo de IA. Por defecto Claude Sonnet 5 (se puede cambiar con APU_AI_MODEL).
# Soporta pensamiento adaptativo, `effort` y salida estructurada, que es lo que
# usa ai_assist.py. La IA es OPCIONAL: si no hay API key el armador usa el
# matcher determinístico y nunca falla por ello.
# ---------------------------------------------------------------------------
AI_MODEL = os.environ.get("APU_AI_MODEL", "claude-sonnet-5")
AI_ENABLED_ENV = "ANTHROPIC_API_KEY"  # si está presente, se habilita la IA

# Umbrales del matcher determinístico (similaridad 0..1).
MATCH_ACCEPT = 0.88   # >= se acepta automáticamente
MATCH_REVIEW = 0.55   # entre REVIEW y ACCEPT -> candidato dudoso (revisar)
#                     # < REVIEW -> sin match (armado por analogía / manual)

# Corte del armado por fallos SEGUIDOS (servicio/corridas.py::armar_pendientes).
# Un ítem que revienta deja una fila sin APU y el armado sigue: un ítem venenoso
# cuesta una fila, no las 1900 de la lista. Pero si lo que se cayó es el ENTORNO
# (la base, la red), ese mismo comportamiento quema el plan entero: escribe 1900
# filas "no se pudo armar" y las deja permanentes, porque cuentan para `max_seq` y
# el worker reanuda DESPUÉS de ellas — nunca las reintenta.
# No hay forma local de distinguir un ítem malo de un entorno caído; la RACHA es el
# único discriminador barato: un fallo aislado es un ítem, N seguidos es el entorno.
# 5 porque un fallo NO es "matcheó mal" (eso es un status, no una excepción): que
# cinco ítems seguidos levanten una excepción no pasa en una lista real, donde los
# ítems raros están salpicados (y por eso un éxito reinicia el contador). Al cortar
# se pierden 4 filas, no 1900, y la corrida queda reintentable.
MAX_FALLOS_SEGUIDOS_ARMADO = 5

# --- armado como trabajo del servidor (servicio/armador.py) ---
# Una reclama sin latido por más de esto se considera muerta y otra instancia puede
# retomar la corrida. Es el tiempo de recuperación tras un reinicio de golpe: más
# corto arriesga doble armado durante el drenaje de un deploy, más largo hace esperar.
ARMADO_TTL_RECLAMA_S = 180
# Cada cuánto se refresca la reclama MIENTRAS se arma. Se mide en TIEMPO y no en ítems
# porque lo que vence es un lease, que también es tiempo: contar ítems es un proxy de
# una velocidad que no controlamos (medida entre 2,8 y 6,2 s/ítem, más del doble de
# variación), y con el proxy el margen contra el TTL depende de qué tan gordos vengan
# los sub-APUs. Así el margen es fijo: 3x el intervalo antes de que la reclama venza.
# Cambiar esto sin mirar ARMADO_TTL_RECLAMA_S es quedarse sin ese margen.
ARMADO_LATIDO_S = 60
# Respaldo del evento: es lo ÚNICO que hace arrancar un armado huérfano al bootear,
# cuando no hay ningún evento que despierte al worker.
ARMADO_POLL_S = 30
# Reclamas antes de rendirse. Cubre "algo la mata siempre en el mismo punto".
ARMADO_MAX_INTENTOS = 3

# Umbrales del cruce código+nombre (resolver de insumos, dominio/cruce.py).
CRUCE_UMBRAL = 0.60   # similitud mínima de nombre para aceptar un cruce aproximado
CRUCE_MARGEN = 0.10   # ventaja mínima del mejor candidato sobre el segundo

# Parecido mínimo para PRE-MARCAR un conflicto de código en el import de insumos.
# Solo pre-marca: el usuario decide, y lo que se aplica es lo que él manda.
# Medido sobre nombres del estilo del catálogo: con 0.80 y el guard de los números,
# ninguno de los seis casos de "cambió un dígito" se pre-marca.
UMBRAL_PREMARCA_CONFLICTO = 0.80

# Umbrales de la composición asistida (dominio/validacion_composicion.py).
# Techo absurdo por componente: atrapa un rendimiento con la coma corrida (0,5 -> 500)
# sin bloquear un consumo grande legítimo (arena en m3 por m3 de mampostería).
COMPOSICION_LIMITE_RENDIMIENTO = 10_000.0
# Antecedentes mínimos para llamar "atípico" a un rendimiento. Con n=1 o n=2 el "rango"
# no significa nada y la advertencia sería ruido: por debajo se informa que no hay con
# qué comparar, que es un dato distinto y útil.
COMPOSICION_MIN_ANTECEDENTES = 3

# Etiquetas de turno.
SHIFT_DIURNO = "DIURNO"
SHIFT_NOCTURNO = "NOCTURNO"

# Fuentes de precio que se consideran CONFIDENCIALES (costo interno / margen).
# Cualquier fuente que NO sea pública se trata como interna.
PUBLIC_PRICE_SOURCES = {"PRECIO IDU"}

# Vocabulario base de grupos (capítulos de obra) para el desplegable de Grupo del APU.
# El vocabulario real que se sirve es esta lista UNIÓN los grupos que ya usa algún APU
# (ver servicio/apus.py::grupos): así un Admin crea un grupo nuevo simplemente usándolo,
# sin tabla ni migración, y un grupo mal escrito desaparece cuando ningún APU lo usa.
GRUPOS_APU_BASE: tuple[str, ...] = (
    "PAVIMENTOS",
    "REDES DE ACUEDUCTO",
    "REDES DE ALCANTARILLADO Y DRENAJE",
    "REDES ELÉCTRICAS",
    "REDES TELEFÓNICAS Y DATOS",
    "CONCRETO Y ACERO PARA ESTRUCTURAS",
    "DEMOLICIONES",
    "EXCAVACIONES",
    "RELLENOS Y CAPAS GRANULARES",
    "ANDENES Y SARDINELES",
    "SEÑALIZACIÓN",
    "MOBILIARIO URBANO Y PAISAJISMO",
)


def classify_price_source(fuente: str) -> str:
    """Clasifica una fuente de precio como 'publico' o 'interno' (confidencial)."""
    f = (fuente or "").strip().upper()
    return "publico" if f in {s.upper() for s in PUBLIC_PRICE_SOURCES} else "interno"


# ---------------------------------------------------------------------------
# Listas de precios. Una lista = una tarifa (la del catálogo, o la de una obra
# de No Previstos). La lista 1 es SIEMPRE 'Principal': es el DEFAULT de la
# columna insumo_precios.lista_id y el ancla del invariante
#   lista_id = None  ==  Principal  ==  comportamiento histórico.
# ---------------------------------------------------------------------------
LISTA_PRINCIPAL_ID = 1


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


def public_url() -> str | None:
    """URL pública del frontend, para redirecciones de auth (invitación/recuperación).
    Ej.: https://armador-apus.onrender.com. Sin ella, Supabase usa su Site URL."""
    u = os.environ.get("APU_PUBLIC_URL", "").strip().rstrip("/")
    return u or None


# ---------------------------------------------------------------------------
# Endurecimiento (Plan 4). Todo por variables de entorno con defaults seguros.
# ---------------------------------------------------------------------------
def max_upload_mb() -> int:
    """Tamaño máximo de subida en MB (rechazo temprano por Content-Length)."""
    try:
        return int(os.environ.get("APU_MAX_UPLOAD_MB", "15"))
    except ValueError:
        return 15


def ratelimit_enabled() -> bool:
    """Rate limiting activo (default sí). Se apaga en tests para no volverlos flaky."""
    return os.environ.get("APU_RATELIMIT_ENABLED", "true").strip().lower() not in ("false", "0", "no")


def web_concurrency() -> int:
    """Número de workers de gunicorn en el contenedor."""
    try:
        return int(os.environ.get("WEB_CONCURRENCY", "2"))
    except ValueError:
        return 2


def docs_enabled() -> bool:
    """Exponer /docs, /redoc y /openapi.json (default sí; desactivar en prod)."""
    return os.environ.get("APU_DOCS_ENABLED", "true").strip().lower() not in ("false", "0", "no")
