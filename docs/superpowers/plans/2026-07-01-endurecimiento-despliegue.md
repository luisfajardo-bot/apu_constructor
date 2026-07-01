# Endurecimiento + Despliegue — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Endurecer la API (rate limiting, límites de subida, errores sin fugas, cabeceras + CSP) y empaquetarla para desplegar en Render (Docker) con CI en GitHub Actions.

**Architecture:** Un contenedor stateless multi-stage (Node compila `web/dist` → Python sirve FastAPI `/api` + SPA, mismo origen). El endurecimiento se añade como middlewares y manejadores en `apu_tool/servicio/` (sin tocar el dominio). Postgres/Auth viven en Supabase; el gate psycopg corre en CI contra un Postgres efímero.

**Tech Stack:** FastAPI, slowapi (rate limit), gunicorn + uvicorn workers, Docker multi-stage, Render, GitHub Actions, Vite.

## Global Constraints

- **Invariante #1:** NO tocar `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py`, ni las vistas `DePriced*`. El endurecimiento vive en `apu_tool/servicio/` + infra.
- **Cero regresiones:** 236 tests backend + 19 vitest verdes. El rate-limit queda **desactivado por defecto en el entorno de test** (fixture autouse en `conftest.py` pone `APU_RATELIMIT_ENABLED=false`); el test de `429` lo activa localmente.
- **Same-origin, sin CORS.** Contenedor **stateless** (cuadros Excel efímeros).
- **Español** en comentarios y mensajes de usuario.
- **DISCIPLINA DE COMMIT:** `git add` SOLO los archivos de cada tarea por ruta explícita. NUNCA `-A`/`.`/`-u`. Cruft ignorado: `node_modules/` raíz, `web/node_modules`, `.env`; y `ejemplos/licitacion_ejemplo.xlsx` está modificado **FUERA DE ALCANCE** — nunca incluirlo.
- **Comandos de prueba:** backend `python -m pytest tests/ -q` (desde la raíz). Frontend, dentro de `web/`: `npm test` y `npm run build`.
- **Ops (NO son tareas de código con test, van documentados en README):** correr `migrate-pg` contra "BASE APUS", crear el primer Admin, y añadir la redirect URL al allowlist de Supabase. El gate psycopg corre en CI (Postgres efímero), no local.

---

### Task 1: Config helpers + dependencias (slowapi, gunicorn)

**Files:**
- Modify: `apu_tool/config.py` (añadir 3 helpers al final)
- Modify: `requirements.txt` (añadir `slowapi`, `gunicorn`)
- Test: `tests/test_config_endurecimiento.py`

**Interfaces:**
- Produces: `config.max_upload_mb() -> int` (default 15), `config.ratelimit_enabled() -> bool` (default True), `config.web_concurrency() -> int` (default 2).

- [ ] **Step 1: Write the failing test**

Crea `tests/test_config_endurecimiento.py`:

```python
from apu_tool import config


def test_max_upload_mb_default(monkeypatch):
    monkeypatch.delenv("APU_MAX_UPLOAD_MB", raising=False)
    assert config.max_upload_mb() == 15


def test_max_upload_mb_env(monkeypatch):
    monkeypatch.setenv("APU_MAX_UPLOAD_MB", "25")
    assert config.max_upload_mb() == 25
    monkeypatch.setenv("APU_MAX_UPLOAD_MB", "basura")
    assert config.max_upload_mb() == 15   # fallback ante valor inválido


def test_ratelimit_enabled(monkeypatch):
    monkeypatch.delenv("APU_RATELIMIT_ENABLED", raising=False)
    assert config.ratelimit_enabled() is True
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "false")
    assert config.ratelimit_enabled() is False
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "0")
    assert config.ratelimit_enabled() is False


def test_web_concurrency(monkeypatch):
    monkeypatch.delenv("WEB_CONCURRENCY", raising=False)
    assert config.web_concurrency() == 2
    monkeypatch.setenv("WEB_CONCURRENCY", "4")
    assert config.web_concurrency() == 4
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_config_endurecimiento.py -q`
Expected: FAIL (`AttributeError: module 'apu_tool.config' has no attribute 'max_upload_mb'`).

- [ ] **Step 3: Añadir los helpers a `config.py`**

Al final de `apu_tool/config.py`:

```python
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
```

- [ ] **Step 4: Añadir dependencias a `requirements.txt`**

Añade al final de `requirements.txt`:

```
slowapi>=0.1.9         # rate limiting (endurecimiento)
gunicorn>=23.0         # servidor de producción (gestiona workers uvicorn en el contenedor)
```

Instala: `pip install -r requirements.txt`

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_config_endurecimiento.py -q`
Expected: PASS (4 passed).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/config.py requirements.txt tests/test_config_endurecimiento.py
git commit -m "feat(endurecimiento): config helpers (upload/ratelimit/workers) + deps slowapi/gunicorn"
```

---

### Task 2: Middleware de cabeceras de seguridad + CSP

**Files:**
- Create: `apu_tool/servicio/seguridad_headers.py`
- Modify: `apu_tool/servicio/app.py` (registrar el middleware)
- Test: `tests/test_endurecimiento_headers.py`

**Interfaces:**
- Consumes: `config.supabase_url()`.
- Produces: `CabecerasSeguridad` (clase `BaseHTTPMiddleware`). Toda respuesta gana HSTS, `X-Content-Type-Options`, `X-Frame-Options`, `Referrer-Policy`, `Content-Security-Policy`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_endurecimiento_headers.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_cabeceras_presentes(tmp_path):
    # /openapi.json no requiere auth → sirve para inspeccionar cabeceras.
    r = TestClient(_app(tmp_path)).get("/openapi.json")
    assert r.status_code == 200
    assert r.headers["X-Content-Type-Options"] == "nosniff"
    assert r.headers["X-Frame-Options"] == "DENY"
    assert "Strict-Transport-Security" in r.headers
    assert r.headers["Referrer-Policy"] == "no-referrer"
    assert "default-src 'self'" in r.headers["Content-Security-Policy"]


def test_csp_incluye_host_supabase(tmp_path, monkeypatch):
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abcxyz")
    csp = TestClient(_app(tmp_path)).get("/openapi.json").headers["Content-Security-Policy"]
    assert "connect-src 'self' https://abcxyz.supabase.co wss://abcxyz.supabase.co" in csp
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_endurecimiento_headers.py -q`
Expected: FAIL (`KeyError: 'X-Content-Type-Options'`).

- [ ] **Step 3: Crear el middleware**

Crea `apu_tool/servicio/seguridad_headers.py`:

```python
"""Middleware de cabeceras de seguridad (HSTS, nosniff, X-Frame-Options, Referrer-Policy, CSP).

La CSP se restringe al mismo origen; `connect-src` añade el host de Supabase (supabase-js hace
fetch + realtime/websocket). Solo son cabeceras HTTP: no afecta la invariante #1."""
from __future__ import annotations

from urllib.parse import urlparse

from starlette.middleware.base import BaseHTTPMiddleware

from apu_tool import config


def construir_csp() -> str:
    conn = ["'self'"]
    base = config.supabase_url()
    if base:
        host = urlparse(base).netloc
        if host:
            conn.append(f"https://{host}")
            conn.append(f"wss://{host}")
    return "; ".join([
        "default-src 'self'",
        "base-uri 'self'",
        "frame-ancestors 'none'",
        "img-src 'self' data:",
        "style-src 'self' 'unsafe-inline'",   # estilos inline de la SPA/Tailwind
        "script-src 'self'",
        f"connect-src {' '.join(conn)}",
    ])


class CabecerasSeguridad(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._csp = construir_csp()   # se calcula una vez al arrancar (lee config/env)

    async def dispatch(self, request, call_next):
        resp = await call_next(request)
        resp.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        resp.headers.setdefault("X-Content-Type-Options", "nosniff")
        resp.headers.setdefault("X-Frame-Options", "DENY")
        resp.headers.setdefault("Referrer-Policy", "no-referrer")
        resp.headers.setdefault("Content-Security-Policy", self._csp)
        return resp
```

- [ ] **Step 4: Registrar el middleware en `create_app`**

En `apu_tool/servicio/app.py`, añade el import y registra el middleware **antes** del bloque `if WEB_DIST.exists()`:

```python
from apu_tool.servicio.seguridad_headers import CabecerasSeguridad
```

Dentro de `create_app`, tras `app.include_router(rutas.router, prefix="/api")`:

```python
    app.add_middleware(CabecerasSeguridad)   # cabeceras en TODA respuesta (incl. errores y estáticos)
```

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_endurecimiento_headers.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/seguridad_headers.py apu_tool/servicio/app.py tests/test_endurecimiento_headers.py
git commit -m "feat(endurecimiento): middleware de cabeceras de seguridad + CSP same-origin"
```

---

### Task 3: Health público + manejador global de errores + SSE genérico

**Files:**
- Modify: `apu_tool/servicio/app.py` (manejadores de excepción + logger)
- Modify: `apu_tool/servicio/rutas.py` (endpoint `/health` público + `_event_stream` genérico + logger)
- Test: `tests/test_endurecimiento_errores.py`

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `GET /api/health` (público, `{"status": "ok"}`); `Exception` → `500 {"detail": "Error interno."}` (traza solo al log `apu_tool`); `ValueError` → `400 {"detail": "Solicitud inválida."}`; el `event: error` del SSE es genérico.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_endurecimiento_errores.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_health_publico_sin_token(tmp_path):
    r = TestClient(_app(tmp_path)).get("/api/health")
    assert r.status_code == 200 and r.json() == {"status": "ok"}


def test_error_interno_es_generico_sin_traza(tmp_path):
    app = _app(tmp_path)

    @app.get("/api/_boom")
    def _boom():
        raise RuntimeError("detalle-secreto-interno")

    cli = TestClient(app, raise_server_exceptions=False)
    r = cli.get("/api/_boom")
    assert r.status_code == 500
    assert r.json() == {"detail": "Error interno."}
    assert "secreto" not in r.text   # no se filtra el detalle interno
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_endurecimiento_errores.py -q`
Expected: FAIL (`/api/health` → 404; y `/api/_boom` → la excepción se propaga / 500 con traza).

- [ ] **Step 3: Añadir el endpoint `/health` y el logger a `rutas.py`**

En `apu_tool/servicio/rutas.py`, añade el import del logger al inicio (junto a los otros imports):

```python
import logging

logger = logging.getLogger("apu_tool")
```

Añade el endpoint de salud (p.ej. tras `yo`, es público — sin `requiere_rol`):

```python
@router.get("/health")
def health():
    """Sonda de salud pública (sin auth) para el health-check del PaaS."""
    return {"status": "ok"}
```

Reemplaza `_event_stream` (líneas ~110-116) para no filtrar detalles:

```python
def _event_stream(gen):
    """Serializa los eventos del generador como SSE; cualquier fallo a mitad -> event: error genérico."""
    try:
        for evento, payload in gen:
            yield f"event: {evento}\ndata: {json.dumps(payload, ensure_ascii=False)}\n\n"
    except Exception:  # nunca dejar el stream a medias sin avisar; detalle solo al log
        logger.exception("Error durante el streaming de la corrida")
        yield f"event: error\ndata: {json.dumps({'detail': 'Error interno.'}, ensure_ascii=False)}\n\n"
```

- [ ] **Step 4: Añadir los manejadores globales en `app.py`**

En `apu_tool/servicio/app.py`, añade imports:

```python
import logging

from fastapi import Request
from fastapi.responses import JSONResponse

logger = logging.getLogger("apu_tool")
```

Dentro de `create_app`, tras `app.add_middleware(CabecerasSeguridad)`:

```python
    @app.exception_handler(ValueError)
    async def _manejar_valor(request: Request, exc: ValueError):
        return JSONResponse(status_code=400, content={"detail": "Solicitud inválida."})

    @app.exception_handler(Exception)
    async def _manejar_error(request: Request, exc: Exception):
        # Traza completa SOLO al log server-side; al cliente, mensaje genérico.
        logger.exception("Error no controlado en %s %s", request.method, request.url.path)
        return JSONResponse(status_code=500, content={"detail": "Error interno."})
```

(Los `HTTPException` conservan su manejador propio de FastAPI — status/detalle intencionales — porque el despacho de Starlette elige el manejador por tipo más específico.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_endurecimiento_errores.py -q`
Expected: PASS (2 passed).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/app.py apu_tool/servicio/rutas.py tests/test_endurecimiento_errores.py
git commit -m "feat(endurecimiento): /api/health público + manejador global de errores + SSE genérico"
```

---

### Task 4: Excel corrupto → 400 (no 500)

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (capturar errores de openpyxl en endpoints de archivo)
- Test: `tests/test_endurecimiento_excel.py`

**Interfaces:**
- Consumes: endpoints de importación/corrida de `rutas.py`.
- Produces: los endpoints que reciben Excel devuelven `400` (no `500`) ante un archivo corrupto/no-Excel.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_endurecimiento_excel.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_excel_corrupto_da_400_no_500(tmp_path):
    cli = cliente(_app(tmp_path), rol="editor")
    basura = b"esto no es un xlsx"
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("lista.xlsx", basura,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 400, r.text


def test_apus_importar_excel_corrupto_da_400(tmp_path):
    cli = cliente(_app(tmp_path), rol="editor")
    r = cli.post("/api/apus/importar/preview",
                 files={"archivo": ("apus.xlsx", b"xx", "application/octet-stream")})
    assert r.status_code == 400, r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_endurecimiento_excel.py -q`
Expected: FAIL (500 por `BadZipFile`/`InvalidFileException` no capturado).

- [ ] **Step 3: Capturar los errores de archivo en `rutas.py`**

En `apu_tool/servicio/rutas.py`, añade los imports al inicio:

```python
import zipfile

from openpyxl.utils.exceptions import InvalidFileException
```

En cada endpoint que lee un Excel subido, **añade** la captura de `zipfile.BadZipFile` e `InvalidFileException` junto al `except ValueError` existente, devolviendo `400` con mensaje genérico. Endpoints a ajustar (todos ya tienen `try: ... except ValueError as e: raise HTTPException(400, str(e))`): `insumos_importar_preview`, `insumos_importar_crear`, `insumos_importar_crear_preview`, `apus_importar`, `apus_importar_preview`. Patrón (aplicar a cada uno):

```python
    try:
        return insumos_svc.preview_import(alm, contenido, archivo.filename or "lista.xlsx")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (zipfile.BadZipFile, InvalidFileException):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel válido o está corrupto.")
```

Para `crear_corrida` y `crear_corrida_stream` (que llaman `read_licitacion`), el `try/except ValueError` que rodea `read_licitacion` gana la misma cláusula extra:

```python
    try:
        items = read_licitacion(tmp_path, default_shift=turno, require_turno=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (zipfile.BadZipFile, InvalidFileException):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel válido o está corrupto.")
    finally:
        os.unlink(tmp_path)
```

(No se toca `apu_tool/dominio/licitacion.py` ni los servicios — la captura vive en la capa de rutas.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_endurecimiento_excel.py -q`
Expected: PASS (2 passed).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_endurecimiento_excel.py
git commit -m "feat(endurecimiento): Excel corrupto/no-Excel -> 400 (antes 500)"
```

---

### Task 5: Límite de subida → 413

**Files:**
- Create: `apu_tool/servicio/limites.py` (middleware de tamaño; el rate limit se añade en Task 6)
- Modify: `apu_tool/servicio/app.py` (registrar el middleware)
- Test: `tests/test_endurecimiento_subida.py`

**Interfaces:**
- Consumes: `config.max_upload_mb()`.
- Produces: `LimiteSubida` (`BaseHTTPMiddleware`, param `max_bytes`). Request con `Content-Length` > límite → `413` antes de leer el cuerpo.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_endurecimiento_subida.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_subida_sobre_limite_da_413(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_MAX_UPLOAD_MB", "1")   # límite 1 MB para el test
    cli = TestClient(_app(tmp_path))
    grande = b"x" * (2 * 1024 * 1024)              # 2 MB > 1 MB
    r = cli.post("/api/insumos/importar/preview",
                 files={"archivo": ("grande.xlsx", grande,
                                    "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")})
    assert r.status_code == 413, r.text
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_endurecimiento_subida.py -q`
Expected: FAIL (sin middleware, el body de 2 MB pasa; no hay 413).

- [ ] **Step 3: Crear `limites.py` con el middleware de subida**

Crea `apu_tool/servicio/limites.py`:

```python
"""Endurecimiento de tráfico: límite de tamaño de subida (aquí) y rate limiting (Task 6).

El límite de subida rechaza por `Content-Length` ANTES de leer el cuerpo → no se carga a memoria
un archivo enorme. Solo mira cabeceras/tamaño: no afecta la invariante #1."""
from __future__ import annotations

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse


class LimiteSubida(BaseHTTPMiddleware):
    def __init__(self, app, max_bytes: int):
        super().__init__(app)
        self.max_bytes = max_bytes

    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl is not None:
            try:
                if int(cl) > self.max_bytes:
                    return JSONResponse(status_code=413,
                                        content={"detail": "Archivo demasiado grande."})
            except ValueError:
                pass  # Content-Length no numérico: dejar seguir (lo valida el endpoint)
        return await call_next(request)
```

- [ ] **Step 4: Registrar el middleware en `create_app`**

En `apu_tool/servicio/app.py`, import:

```python
from apu_tool.servicio.limites import LimiteSubida
```

Dentro de `create_app`, junto al registro de middlewares (tras `CabecerasSeguridad`):

```python
    app.add_middleware(LimiteSubida, max_bytes=config.max_upload_mb() * 1024 * 1024)
```

(`config` ya está importado en `app.py`.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_endurecimiento_subida.py -q`
Expected: PASS (1 passed).

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/limites.py apu_tool/servicio/app.py tests/test_endurecimiento_subida.py
git commit -m "feat(endurecimiento): límite de subida por Content-Length -> 413"
```

---

### Task 6: Rate limiting (slowapi) → 429

**Files:**
- Modify: `apu_tool/servicio/limites.py` (Limiter de slowapi)
- Modify: `apu_tool/servicio/app.py` (state + handler + middleware; set `enabled` por config)
- Modify: `apu_tool/servicio/rutas.py` (límite estricto en endpoints sensibles; `request: Request`)
- Modify: `tests/conftest.py` (fixture autouse que desactiva el rate-limit en tests)
- Test: `tests/test_endurecimiento_ratelimit.py`

**Interfaces:**
- Consumes: `config.ratelimit_enabled()`.
- Produces: `limites.limiter` (`Limiter`, `default_limits=["200/minute"]`); en `create_app` se hace `app.state.limiter = limites.limiter`, `limites.limiter.enabled = config.ratelimit_enabled()`, se registra el handler de `RateLimitExceeded` y `SlowAPIMiddleware`. Exceso → `429`. Endpoint `usuarios_invitar` decorado con `@limites.limiter.limit("3/minute")` requiere `request: Request`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_endurecimiento_ratelimit.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from apu_tool.servicio import rutas
from apu_tool.servicio.supabase_admin import AdminSupabaseFake
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    app = create_app(almacen=alm)
    fake = AdminSupabaseFake(id_por_email={"a@obra.co": "u-a", "b@obra.co": "u-b",
                                           "c@obra.co": "u-c", "d@obra.co": "u-d"})
    app.dependency_overrides[rutas.get_admin_supabase] = lambda: fake
    return app


def test_invitar_supera_limite_da_429(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_RATELIMIT_ENABLED", "true")   # activarlo para ESTE test
    cli = cliente(_app(tmp_path), rol="admin")
    correos = ["a@obra.co", "b@obra.co", "c@obra.co", "d@obra.co"]
    codigos = [cli.post("/api/usuarios/invitar",
                        json={"email": e, "rol": "consulta", "nombre": ""}).status_code
               for e in correos]
    assert codigos[:3] == [200, 200, 200]     # los 3 primeros pasan (límite 3/minute)
    assert codigos[3] == 429                  # el 4º es rechazado
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_endurecimiento_ratelimit.py -q`
Expected: FAIL (sin rate limit, el 4º devuelve 200).

- [ ] **Step 3: Añadir el Limiter a `limites.py`**

Al inicio de `apu_tool/servicio/limites.py` (tras el docstring, antes de `LimiteSubida`):

```python
from slowapi import Limiter
from slowapi.util import get_remote_address

# Limiter global keyeado por IP remota. `enabled` se fija en create_app desde config
# (default true; los tests lo apagan). default_limits aplica a TODA ruta vía SlowAPIMiddleware.
limiter = Limiter(key_func=get_remote_address, default_limits=["200/minute"])
```

- [ ] **Step 4: Cablear slowapi en `create_app`**

En `apu_tool/servicio/app.py`, imports:

```python
from slowapi import _rate_limit_exceeded_handler
from slowapi.errors import RateLimitExceeded
from slowapi.middleware import SlowAPIMiddleware

from apu_tool.servicio import limites
```

Dentro de `create_app`, tras registrar `LimiteSubida` (y antes del bloque `if WEB_DIST.exists()`):

```python
    limites.limiter.enabled = config.ratelimit_enabled()
    app.state.limiter = limites.limiter
    app.add_exception_handler(RateLimitExceeded, _rate_limit_exceeded_handler)
    app.add_middleware(SlowAPIMiddleware)
```

- [ ] **Step 5: Límite estricto en el endpoint de invitación**

En `apu_tool/servicio/rutas.py`, importa `Request` y el limiter:

```python
from fastapi import Request
from apu_tool.servicio import limites
```

Decora `usuarios_invitar` y añádele `request: Request` como primer parámetro (slowapi lo requiere para extraer la IP):

```python
@router.post("/usuarios/invitar")
@limites.limiter.limit("3/minute")
def usuarios_invitar(request: Request, body: UsuarioInvitarIn, alm: Almacen = Depends(get_almacen),
                     admin=Depends(get_admin_supabase),
                     actor=Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.invitar(alm, admin, body.email, body.rol, body.nombre, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except httpx.HTTPStatusError:
        raise HTTPException(status_code=400,
                            detail="No se pudo invitar (¿el email ya existe?).")
```

(El límite global de 200/min ya cubre el resto de endpoints vía el middleware. Este estricto protege la invitación, que es la acción más sensible.)

- [ ] **Step 6: Desactivar el rate-limit por defecto en los tests**

En `tests/conftest.py`, añade una fixture autouse que apaga el rate-limit salvo que un test lo active:

```python
import os
import pytest


@pytest.fixture(autouse=True)
def _sin_ratelimit(monkeypatch):
    """El rate-limit se apaga por defecto en tests para no volverlos flaky.
    El test de 429 lo reactiva con su propio monkeypatch.setenv."""
    if "APU_RATELIMIT_ENABLED" not in os.environ:
        monkeypatch.setenv("APU_RATELIMIT_ENABLED", "false")
```

(Añade los imports `os`/`pytest` si no están.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_endurecimiento_ratelimit.py -q`
Expected: PASS (1 passed). Luego corre la suite completa para confirmar que el rate-limit no afecta a nadie: `python -m pytest tests/ -q` (sin regresiones).

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/limites.py apu_tool/servicio/app.py apu_tool/servicio/rutas.py tests/conftest.py tests/test_endurecimiento_ratelimit.py
git commit -m "feat(endurecimiento): rate limiting slowapi (global + estricto en invitar) -> 429"
```

---

### Task 7: Dockerfile multi-stage + entrypoint gunicorn

**Files:**
- Create: `Dockerfile`
- Create: `.dockerignore`
- Test: `docker build` (si Docker está disponible) + revisión estructural

**Interfaces:**
- Consumes: `web/` (build Vite), `apu_tool/`, `db/`, `requirements.txt`, `config.web_concurrency()`.
- Produces: imagen que sirve FastAPI `/api` + SPA con gunicorn en `0.0.0.0:$PORT`.

- [ ] **Step 1: Crear `.dockerignore`**

Crea `.dockerignore`:

```
.git
.github
.superpowers
**/__pycache__
*.pyc
.pytest_cache
tests
data
salidas
ejemplos/*.xlsx
.env
.env.*
!.env.example
node_modules
web/node_modules
web/dist
docs
*.md
```

- [ ] **Step 2: Crear el `Dockerfile` multi-stage**

Crea `Dockerfile`:

```dockerfile
# --- Etapa 1: compilar el frontend (Vite) ---
FROM node:22-slim AS frontend
WORKDIR /web
COPY web/package.json web/package-lock.json ./
RUN npm ci
COPY web/ ./
# Las VITE_* son públicas (se bakean en el bundle). Se pasan como build-args.
ARG VITE_SUPABASE_URL
ARG VITE_SUPABASE_ANON_KEY
ENV VITE_SUPABASE_URL=$VITE_SUPABASE_URL
ENV VITE_SUPABASE_ANON_KEY=$VITE_SUPABASE_ANON_KEY
RUN npm run build   # produce /web/dist

# --- Etapa 2: backend Python que sirve API + SPA ---
FROM python:3.12-slim AS backend
WORKDIR /app
ENV PYTHONUNBUFFERED=1 PIP_NO_CACHE_DIR=1
COPY requirements.txt ./
RUN pip install -r requirements.txt
COPY apu_tool/ ./apu_tool/
COPY db/ ./db/
COPY run_cli.py run_web.py ./
COPY --from=frontend /web/dist ./web/dist
# Render inyecta $PORT; gunicorn con workers uvicorn, confiando en el proxy para la IP real.
ENV PORT=8000 WEB_CONCURRENCY=2
CMD gunicorn apu_tool.servicio.app:app \
    -k uvicorn.workers.UvicornWorker \
    --workers ${WEB_CONCURRENCY} \
    --bind 0.0.0.0:${PORT} \
    --forwarded-allow-ips="*" \
    --timeout 120
```

- [ ] **Step 3: Verificar (build si hay Docker)**

Si hay Docker disponible localmente:
Run: `docker build -t apu-endurecimiento --build-arg VITE_SUPABASE_URL=https://x.supabase.co --build-arg VITE_SUPABASE_ANON_KEY=demo .`
Expected: build OK hasta la etapa backend (la app arranca; sin envs reales la validación de token fallará en requests, pero eso no rompe el build ni el arranque).

Si NO hay Docker: revisión estructural — el `Dockerfile` copia `web/dist` de la etapa frontend, instala `requirements.txt`, y el `CMD` usa `gunicorn ... apu_tool.servicio.app:app`. Reporta que Docker no está disponible y que la validación real ocurrirá en el deploy de Render / CI.

- [ ] **Step 4: Commit**

```bash
git add Dockerfile .dockerignore
git commit -m "feat(despliegue): Dockerfile multi-stage (Vite build -> Python/gunicorn) + .dockerignore"
```

---

### Task 8: `.env.example` (backend) + sección de despliegue/quickstart en README

**Files:**
- Create: `.env.example`
- Modify: `README.md` (añadir sección "Despliegue y desarrollo local")
- Test: revisión de contenido (sin test automatizado)

**Interfaces:**
- Produces: documentación de TODAS las envs + el quickstart local que resuelve "no corre local".

- [ ] **Step 1: Crear `.env.example` (backend)**

Crea `.env.example`:

```bash
# Backend — variables de entorno (copiar a .env local; NUNCA commitear .env)
# --- Base de datos (producción: Supabase; local dev usa SQLite si se omite) ---
DATABASE_URL=                     # postgresql://...pooler.supabase.com:6543/postgres?... (modo transacción). Vacío => SQLite local.
# --- Supabase Auth (necesario para validar el JWT, incluso en local) ---
SUPABASE_PROJECT_REF=             # p.ej. hfjljzhgignngzooiwvl  (deriva URL/JWKS/issuer)
SUPABASE_SERVICE_ROLE_KEY=        # clave service_role (solo backend; NUNCA en el front)
APU_ADMIN_EMAILS=                 # correos que arrancan como admin, separados por coma
# --- IA (opcional; sin clave usa el fallback determinístico) ---
ANTHROPIC_API_KEY=
# --- Endurecimiento (opcionales, con defaults) ---
APU_MAX_UPLOAD_MB=15
APU_RATELIMIT_ENABLED=true
WEB_CONCURRENCY=2
```

- [ ] **Step 2: Añadir la sección al `README.md`**

Añade al final de `README.md`:

```markdown
## Desarrollo local (con login)

Desde los Planes 2a/2b la app exige login por Supabase. Para correrla en local:

1. `web/.env` con `VITE_SUPABASE_URL` y `VITE_SUPABASE_ANON_KEY` (ver `web/.env.example`).
   **Sin esto la SPA no monta** (supabase-js revienta al importar).
2. `.env` del backend con `SUPABASE_PROJECT_REF` (o `SUPABASE_URL`) y `APU_ADMIN_EMAILS=<tu-correo>`
   (ver `.env.example`). Sin `DATABASE_URL` usa SQLite local.
3. `python run_cli.py seed` — siembra el catálogo y crea las bases locales.
4. En dos terminales: `python run_web.py` (backend :8000) y, en `web/`, `npm run dev` (Vite :5173,
   proxya `/api` al backend). Abre http://localhost:5173.
5. Crea tu usuario en el panel de Supabase Auth (con un correo de `APU_ADMIN_EMAILS`) y entra: al
   primer login se te bootstrapea como Admin.

## Despliegue (Render + Docker)

- **Imagen:** `Dockerfile` multi-stage (Node compila `web/dist` → Python sirve todo con gunicorn).
  Las `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` se pasan como **build-args** (se bakean en el bundle).
- **Render:** servicio web tipo Docker (ver `render.yaml`); `healthCheckPath: /api/health`; secretos
  (`DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PROJECT_REF`, `APU_ADMIN_EMAILS`,
  `ANTHROPIC_API_KEY`) por el dashboard; HTTPS automático.
- **Migración del catálogo (una vez, ops):** con `DATABASE_URL` de Supabase, correr
  `python run_cli.py migrate-pg` y verificar conteos (insumos/precios/APUs/componentes) SQLite vs
  Postgres. El esquema Postgres (`db/pg/*.sql` + auditoría) ya está aplicado.
- **Post-deploy:** en Supabase añadir `https://<app-url>/definir-clave` al allowlist de redirect URLs;
  crear el primer usuario Admin en Supabase Auth con un correo de `APU_ADMIN_EMAILS`.
```

- [ ] **Step 3: Verificar**

Revisión de contenido: `.env.example` lista todas las envs usadas por `config.py` (grep de `os.environ` en `apu_tool/config.py` para confirmar cobertura). No hay test automatizado.

- [ ] **Step 4: Commit**

```bash
git add .env.example README.md
git commit -m "docs(despliegue): .env.example backend + quickstart local + guía de deploy"
```

---

### Task 9: `render.yaml`

**Files:**
- Create: `render.yaml`
- Test: validez YAML + revisión estructural

**Interfaces:**
- Produces: definición IaC del servicio web en Render (Docker, health-check, env vars).

- [ ] **Step 1: Crear `render.yaml`**

Crea `render.yaml`:

```yaml
services:
  - type: web
    name: armador-apus
    runtime: docker
    plan: starter            # evita el spin-down del free tier
    healthCheckPath: /api/health
    autoDeploy: true
    branch: master
    dockerfilePath: ./Dockerfile
    envVars:
      # VITE_* se bakean en el build (públicas); se pasan como build-args del Docker.
      - key: VITE_SUPABASE_URL
        sync: false
      - key: VITE_SUPABASE_ANON_KEY
        sync: false
      # Secretos de runtime (se llenan en el dashboard).
      - key: DATABASE_URL
        sync: false
      - key: SUPABASE_PROJECT_REF
        sync: false
      - key: SUPABASE_SERVICE_ROLE_KEY
        sync: false
      - key: APU_ADMIN_EMAILS
        sync: false
      - key: ANTHROPIC_API_KEY
        sync: false
      - key: APU_MAX_UPLOAD_MB
        value: "15"
      - key: APU_RATELIMIT_ENABLED
        value: "true"
      - key: WEB_CONCURRENCY
        value: "2"
```

- [ ] **Step 2: Verificar validez YAML**

Si hay PyYAML: `python -c "import yaml; yaml.safe_load(open('render.yaml')); print('ok')"` → `ok`.
Si no, revisión estructural: `type: web`, `runtime: docker`, `healthCheckPath: /api/health`, y todas las envs con `sync: false` (secretas) o `value` (no secretas). Render valida el resto al conectar el repo.

- [ ] **Step 3: Commit**

```bash
git add render.yaml
git commit -m "feat(despliegue): render.yaml (servicio web Docker + health-check + envs)"
```

---

### Task 10: CI (GitHub Actions) — backend + Postgres efímero + frontend

**Files:**
- Create: `.github/workflows/ci.yml`
- Test: validez YAML + revisión estructural (se ejecuta de verdad al hacer push)

**Interfaces:**
- Produces: workflow que en push/PR a `master` corre pytest (con y sin Postgres) + vitest + build + lint.

- [ ] **Step 1: Crear `.github/workflows/ci.yml`**

Crea `.github/workflows/ci.yml`:

```yaml
name: CI
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]

jobs:
  backend:
    runs-on: ubuntu-latest
    services:
      postgres:
        image: postgres:17
        env:
          POSTGRES_PASSWORD: postgres
          POSTGRES_DB: postgres
        ports:
          - 5432:5432
        options: >-
          --health-cmd "pg_isready -U postgres"
          --health-interval 10s --health-timeout 5s --health-retries 5
    env:
      # Ejercita los contratos Postgres (repos *Pg) contra un Postgres real efímero.
      TEST_DATABASE_URL: postgresql://postgres:postgres@localhost:5432/postgres
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-python@v5
        with:
          python-version: "3.12"
      - run: pip install -r requirements.txt
      - run: python -m pytest tests/ -q

  frontend:
    runs-on: ubuntu-latest
    defaults:
      run:
        working-directory: web
    steps:
      - uses: actions/checkout@v4
      - uses: actions/setup-node@v4
        with:
          node-version: "22"
          cache: npm
          cache-dependency-path: web/package-lock.json
      - run: npm ci
      - run: npx vitest run
      - run: npm run build
      - run: npx oxlint
```

- [ ] **Step 2: Verificar validez YAML**

Si hay PyYAML: `python -c "import yaml; yaml.safe_load(open('.github/workflows/ci.yml')); print('ok')"` → `ok`.
Revisión estructural: dos jobs (`backend` con service `postgres:17` + `TEST_DATABASE_URL`; `frontend` con `working-directory: web`). Nota de ops: en GitHub, activar branch protection para que el merge a `master` requiera estos checks.

- [ ] **Step 3: Commit**

```bash
git add .github/workflows/ci.yml
git commit -m "ci: GitHub Actions — pytest (+Postgres efímero) + vitest + build + lint"
```

---

## Notas de cierre (para el revisor final)

- **Suite:** `python -m pytest tests/ -q` (236 previos + nuevos de endurecimiento, todos verdes) y, en `web/`, `npm test` + `npm run build`.
- **Invariante #1:** verificar que NO se tocaron `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py` ni las vistas `DePriced*` (el endurecimiento es solo `servicio/` + infra).
- **Orden de middlewares en `create_app`** (por adición; el último es el más externo): `CabecerasSeguridad`, `LimiteSubida`, `SlowAPIMiddleware`. El catch-all SPA `@app.get("/{full_path:path}")` DEBE seguir siendo la última RUTA registrada.
- **Validación manual de la CSP (crítica, no automatizable aquí):** tras un build real, servir la app (`run_web.py` con `web/dist`, o el contenedor) y confirmar en la consola del navegador que NO hay violaciones de CSP y que login + navegación + llamadas a Supabase funcionan. Si Vite inyecta scripts inline, ajustar `script-src` con hash/nonce.
- **Ops pendientes (no código):** `migrate-pg` contra "BASE APUS" + verificación de conteos; crear el primer Admin; redirect allowlist en Supabase; activar branch protection en GitHub.
```
