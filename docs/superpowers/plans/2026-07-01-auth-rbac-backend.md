# Plan 2a — Auth + RBAC (backend) Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Proteger la API con autenticación (Supabase Auth, JWT asimétrico/JWKS) y autorización por roles (Admin/Editor/Consulta), con gestión de usuarios solo-Admin y RLS, sin romper los 173 tests ni la invariante #1.

**Architecture:** FastAPI verifica el JWT localmente contra el JWKS de Supabase (PyJWT). Los roles viven en una tabla `perfiles` (schema `seguridad`) con repositorio DUAL (SQLite para dev/tests, Postgres para prod), igual que el patrón del Plan 1. Dependencias FastAPI `usuario_actual` + `requiere_rol(minimo)` protegen cada endpoint. La gestión de usuarios usa la Admin API de Supabase por HTTPS, tras una interfaz con *fake* para tests. Todo se prueba sin BD viva.

**Tech Stack:** Python 3.10+, FastAPI, PyJWT[crypto], psycopg v3 (existente), httpx (existente), pytest, SQLite (dev/tests) + Postgres/Supabase (prod).

## Global Constraints

- **Invariante #1 (NO romper):** la IA nunca ve dinero. NO tocar `apu_tool/dominio/privacy.py`, `ai_assist.py` ni las vistas `DePriced*`.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias pesadas:** se acepta `PyJWT[crypto]` (estándar, liviana). No otras.
- **Persistencia aislada en `apu_tool/datos/`** (repos); auth en `apu_tool/servicio/`.
- **Los 173 tests actuales deben seguir verdes.** Los `test_api_*` (usan `TestClient`) requieren el override de `usuario_actual`; los `test_servicio_*` llaman servicios directo y NO se afectan.
- **SQL parametrizado siempre** (`%s`/`?`); cero concatenación de input. DDL multi-sentencia en Postgres se aplica con `ejecutar_script` (psycopg3 rechaza multi-comando en `execute()`).
- **Sin bypass de auth en runtime** (no `APU_AUTH_DISABLED`).
- **Jerarquía de roles:** `consulta < editor < admin`. `requiere_rol(minimo)` pasa si el rol del usuario es ≥ mínimo (un Admin pasa endpoints de Editor y Consulta).
- **Backend por defecto SQLite** (sin `DATABASE_URL`); tests Postgres se omiten sin `TEST_DATABASE_URL`.
- TDD, commits frecuentes. Rama: `feat/auth-rbac`.

---

### Task 1: Dependencia PyJWT + config de auth

**Files:**
- Modify: `requirements.txt`
- Modify: `apu_tool/config.py` (añadir al final)
- Test: `tests/test_auth_config.py`

**Interfaces:**
- Produces:
  - `config.supabase_project_ref() -> str | None` (env `SUPABASE_PROJECT_REF`)
  - `config.supabase_url() -> str | None` — `https://<ref>.supabase.co` o env `SUPABASE_URL`
  - `config.supabase_issuer() -> str | None` — `<supabase_url>/auth/v1`
  - `config.supabase_jwks_url() -> str | None` — `<supabase_url>/auth/v1/.well-known/jwks.json`
  - `config.supabase_service_role_key() -> str | None` (env `SUPABASE_SERVICE_ROLE_KEY`)
  - `config.admin_emails() -> set[str]` — parse de `APU_ADMIN_EMAILS` (coma-separado, minúsculas, sin espacios)

- [ ] **Step 1: Añadir dependencia**

En `requirements.txt`, añadir al final:
```
PyJWT[crypto]>=2.9   # verificación de JWT (Supabase Auth, JWKS asimétrico)
```
Run: `pip install -r requirements.txt`
Expected: instala PyJWT y cryptography sin error.

- [ ] **Step 2: Escribir el test (falla)**

Create `tests/test_auth_config.py`:
```python
from apu_tool import config


def test_admin_emails_parsea_lista(monkeypatch):
    monkeypatch.setenv("APU_ADMIN_EMAILS", " Jefe@Obra.CO ,  admin2@obra.co ")
    assert config.admin_emails() == {"jefe@obra.co", "admin2@obra.co"}


def test_admin_emails_vacio(monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    assert config.admin_emails() == set()


def test_urls_derivadas_del_ref(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.setenv("SUPABASE_PROJECT_REF", "abc123")
    assert config.supabase_url() == "https://abc123.supabase.co"
    assert config.supabase_issuer() == "https://abc123.supabase.co/auth/v1"
    assert config.supabase_jwks_url() == "https://abc123.supabase.co/auth/v1/.well-known/jwks.json"


def test_sin_config_devuelve_none(monkeypatch):
    monkeypatch.delenv("SUPABASE_URL", raising=False)
    monkeypatch.delenv("SUPABASE_PROJECT_REF", raising=False)
    assert config.supabase_url() is None
    assert config.supabase_jwks_url() is None
```

- [ ] **Step 3: Verificar que falla**

Run: `python -m pytest tests/test_auth_config.py -v`
Expected: FAIL (funciones no existen).

- [ ] **Step 4: Implementar en `config.py`**

Añadir al final de `apu_tool/config.py`:
```python
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
```

- [ ] **Step 5: Verificar que pasa + no-regresión**

Run: `python -m pytest tests/test_auth_config.py -v`
Expected: PASS (4 tests).
Run: `python -m pytest tests/ -q`
Expected: 177 passed (173 + 4), sin skips nuevos.

- [ ] **Step 6: Commit**
```bash
git add requirements.txt apu_tool/config.py tests/test_auth_config.py
git commit -m "feat(auth): dependencia PyJWT y config de Supabase/roles"
```

---

### Task 2: Verificación del JWT (JWKS asimétrico)

**Files:**
- Create: `apu_tool/servicio/auth.py`
- Test: `tests/test_auth_jwt.py`

**Interfaces:**
- Consumes: `config.supabase_issuer()`, `config.supabase_jwks_url()`.
- Produces:
  - `class ErrorAuth(Exception)` — auth inválida (→ 401 en la capa de rutas).
  - `verificar_token(token: str, public_key, *, issuer: str, audience: str = "authenticated") -> dict` — decodifica/verifica con una llave pública dada (firma, `exp`, `aud`, `iss`); lanza `ErrorAuth` si algo falla. Es la unidad testeable sin red.
  - `obtener_claims(token: str) -> dict` — producción: obtiene la llave del JWKS (cacheado) y llama a `verificar_token`.

- [ ] **Step 1: Escribir el test (falla)**

Create `tests/test_auth_jwt.py`:
```python
import datetime as dt

import jwt
import pytest
from cryptography.hazmat.primitives.asymmetric import rsa

from apu_tool.servicio.auth import ErrorAuth, verificar_token

ISS = "https://proj.supabase.co/auth/v1"


@pytest.fixture(scope="module")
def par_llaves():
    priv = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    return priv, priv.public_key()


def _token(priv, **over):
    ahora = dt.datetime(2026, 7, 1, 12, 0, 0, tzinfo=dt.timezone.utc)
    payload = {
        "sub": "user-123", "email": "x@obra.co", "aud": "authenticated",
        "iss": ISS, "iat": ahora, "exp": ahora + dt.timedelta(hours=1)}
    payload.update(over)
    return jwt.encode(payload, priv, algorithm="RS256")


def test_token_valido_devuelve_claims(par_llaves):
    priv, pub = par_llaves
    claims = verificar_token(_token(priv), pub, issuer=ISS)
    assert claims["sub"] == "user-123" and claims["email"] == "x@obra.co"


def test_token_expirado_falla(par_llaves):
    priv, pub = par_llaves
    viejo = dt.datetime(2020, 1, 1, tzinfo=dt.timezone.utc)
    t = _token(priv, iat=viejo, exp=viejo + dt.timedelta(hours=1))
    with pytest.raises(ErrorAuth):
        verificar_token(t, pub, issuer=ISS)


def test_aud_incorrecto_falla(par_llaves):
    priv, pub = par_llaves
    with pytest.raises(ErrorAuth):
        verificar_token(_token(priv, aud="otra"), pub, issuer=ISS)


def test_iss_incorrecto_falla(par_llaves):
    priv, pub = par_llaves
    with pytest.raises(ErrorAuth):
        verificar_token(_token(priv, iss="https://malo/auth/v1"), pub, issuer=ISS)


def test_firma_de_otra_llave_falla(par_llaves):
    priv, pub = par_llaves
    otra = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    with pytest.raises(ErrorAuth):
        verificar_token(_token(otra), pub, issuer=ISS)
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_auth_jwt.py -v`
Expected: FAIL (`apu_tool.servicio.auth` no existe).

- [ ] **Step 3: Implementar `auth.py` (parte JWT)**

Create `apu_tool/servicio/auth.py`:
```python
"""Autenticación (Supabase Auth) y autorización (RBAC) para la API.

Verifica el JWT localmente contra el JWKS asimétrico de Supabase (PyJWT). La
autorización por roles vive en la tabla `perfiles` (ver resolver_perfil).
NO toca dinero: fuera de la frontera de la IA.
"""
from __future__ import annotations

import jwt
from jwt import PyJWKClient

from apu_tool import config

_ALGOS = ["ES256", "RS256"]


class ErrorAuth(Exception):
    """Autenticación inválida (token ausente/expirado/firma mala). → 401."""


def verificar_token(token: str, public_key, *, issuer: str,
                    audience: str = "authenticated") -> dict:
    """Verifica firma + exp + aud + iss con una llave pública dada.

    Unidad testeable sin red (los tests inyectan la llave). Lanza ErrorAuth.
    """
    try:
        return jwt.decode(
            token, public_key, algorithms=_ALGOS, audience=audience, issuer=issuer,
            options={"require": ["exp", "aud", "iss"]})
    except jwt.InvalidTokenError as e:
        raise ErrorAuth(str(e)) from e


_jwks_client: PyJWKClient | None = None


def _cliente_jwks() -> PyJWKClient:
    global _jwks_client
    if _jwks_client is None:
        url = config.supabase_jwks_url()
        if not url:
            raise ErrorAuth("Auth no configurada (falta SUPABASE_PROJECT_REF/URL).")
        _jwks_client = PyJWKClient(url)  # cachea llaves; refresca por kid desconocido
    return _jwks_client


def obtener_claims(token: str) -> dict:
    """Producción: resuelve la llave del JWKS de Supabase y verifica el token."""
    issuer = config.supabase_issuer()
    if not issuer:
        raise ErrorAuth("Auth no configurada.")
    try:
        signing_key = _cliente_jwks().get_signing_key_from_jwt(token)
    except Exception as e:  # PyJWKClientError, red, kid inválido → auth inválida
        raise ErrorAuth(f"No se pudo resolver la llave de firma: {e}") from e
    return verificar_token(token, signing_key.key, issuer=issuer)
```

- [ ] **Step 4: Verificar que pasa + no-regresión**

Run: `python -m pytest tests/test_auth_jwt.py -v`
Expected: PASS (5 tests).
Run: `python -m pytest tests/ -q`
Expected: 182 passed.

- [ ] **Step 5: Commit**
```bash
git add apu_tool/servicio/auth.py tests/test_auth_jwt.py
git commit -m "feat(auth): verificación de JWT asimétrico contra JWKS de Supabase"
```

---

### Task 3: Tabla `perfiles` + repositorio dual + Almacen

**Files:**
- Create: `db/pg/seguridad.sql`
- Create: `db/seguridad.sql` (SQLite)
- Modify: `apu_tool/nucleo/models.py` (añadir `Perfil`)
- Modify: `apu_tool/datos/repositorio.py` (añadir `RepositorioPerfiles`)
- Create: `apu_tool/datos/perfiles_db.py` (SQLite)
- Create: `apu_tool/datos/pg/perfiles_pg.py` (Postgres)
- Modify: `apu_tool/datos/almacen.py` (añadir `.perfiles`)
- Modify: `supabase/migrations/0001_esquema_inicial.sql`? NO — nueva migración en Task 8.
- Test: `tests/test_perfiles_contrato.py`

**Interfaces:**
- Produces:
  - `nucleo.models.Perfil(user_id: str, email: str, rol: str, estado: str, nombre: str = "", creado_en: str = "")` (dataclass).
  - `RepositorioPerfiles` (Protocol): `init_schema()`, `reset()`, `get(user_id) -> Perfil | None`, `upsert(perfil: Perfil) -> None`, `listar() -> list[Perfil]`, `set_rol(user_id, rol) -> None`, `set_estado(user_id, estado) -> None`, `contar_admins_activos() -> int`.
  - `PerfilesDB(path)` (SQLite) y `PerfilesPg(cx)` implementan el Protocol.
  - `Almacen.perfiles` disponible en ambos backends; `Almacen.init_schema()` lo inicializa.

- [ ] **Step 1: Escribir el contrato (falla)**

Create `tests/test_perfiles_contrato.py`:
```python
import os
import pytest

from apu_tool.nucleo.models import Perfil


def _sqlite(tmp_path):
    from apu_tool.datos.perfiles_db import PerfilesDB
    r = PerfilesDB(tmp_path / "seg.db"); r.init_schema(); return r, None


def _postgres(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.perfiles_pg import PerfilesPg
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    r = PerfilesPg(cx); r.reset(); return r, cx


_BACKENDS = ["sqlite"] + (["postgres"] if os.environ.get("TEST_DATABASE_URL") else [])


@pytest.fixture(params=_BACKENDS)
def repo(request, tmp_path):
    r, cx = _sqlite(tmp_path) if request.param == "sqlite" else _postgres(tmp_path)
    yield r
    if cx is not None:
        cx.cerrar()


def test_upsert_y_get(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "editor", "activo", "Ana"))
    p = repo.get("u1")
    assert p.email == "a@obra.co" and p.rol == "editor" and p.estado == "activo"
    assert repo.get("noexiste") is None


def test_upsert_actualiza(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    repo.upsert(Perfil("u1", "a@obra.co", "editor", "activo"))
    assert repo.get("u1").rol == "editor"
    assert len(repo.listar()) == 1


def test_set_rol_y_estado(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    repo.set_rol("u1", "admin")
    repo.set_estado("u1", "inactivo")
    p = repo.get("u1")
    assert p.rol == "admin" and p.estado == "inactivo"


def test_contar_admins_activos(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    repo.upsert(Perfil("u2", "b@obra.co", "admin", "inactivo"))
    repo.upsert(Perfil("u3", "c@obra.co", "editor", "activo"))
    assert repo.contar_admins_activos() == 1
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_perfiles_contrato.py -v`
Expected: FAIL (módulos/tipos no existen); el param postgres se omite sin `TEST_DATABASE_URL`.

- [ ] **Step 3: `Perfil` en models.py**

Añadir a `apu_tool/nucleo/models.py` (tras la sección de catálogos, junto a los otros dataclass frozen):
```python
@dataclass(frozen=True)
class Perfil:
    """Identidad + rol de un usuario (tabla seguridad.perfiles)."""
    user_id: str                  # UUID de Supabase Auth
    email: str
    rol: str                      # admin | editor | consulta
    estado: str                   # activo | inactivo
    nombre: str = ""
    creado_en: str = ""
```

- [ ] **Step 4: Esquemas SQL**

Create `db/seguridad.sql` (SQLite):
```sql
CREATE TABLE IF NOT EXISTS perfiles (
    user_id   TEXT PRIMARY KEY,
    email     TEXT NOT NULL,
    rol       TEXT NOT NULL CHECK (rol IN ('admin','editor','consulta')),
    estado    TEXT NOT NULL CHECK (estado IN ('activo','inactivo')),
    nombre    TEXT,
    creado_en TEXT
);
```

Create `db/pg/seguridad.sql` (Postgres):
```sql
CREATE SCHEMA IF NOT EXISTS seguridad;
CREATE TABLE IF NOT EXISTS seguridad.perfiles (
    user_id   TEXT PRIMARY KEY,
    email     TEXT NOT NULL,
    rol       TEXT NOT NULL CHECK (rol IN ('admin','editor','consulta')),
    estado    TEXT NOT NULL CHECK (estado IN ('activo','inactivo')),
    nombre    TEXT,
    creado_en TEXT
);
```

- [ ] **Step 5: `PerfilesDB` (SQLite)**

Create `apu_tool/datos/perfiles_db.py`:
```python
"""Acceso SQLite a la tabla perfiles (identidad + rol). Implementa RepositorioPerfiles."""
from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Iterator, Optional

from apu_tool import config
from apu_tool.nucleo.models import Perfil

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "seguridad.sql"


class PerfilesDB:
    def __init__(self, path: Path | str = config.DATA_DIR / "seguridad.db"):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.connect() as conn:
            conn.execute("DROP TABLE IF EXISTS perfiles")
            conn.executescript(SCHEMA_PATH.read_text(encoding="utf-8"))

    def _fila(self, r) -> Perfil:
        return Perfil(user_id=r["user_id"], email=r["email"], rol=r["rol"],
                      estado=r["estado"], nombre=r["nombre"] or "",
                      creado_en=r["creado_en"] or "")

    def get(self, user_id: str) -> Optional[Perfil]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM perfiles WHERE user_id=?", (user_id,)).fetchone()
        return self._fila(r) if r else None

    def upsert(self, p: Perfil) -> None:
        with self.connect() as conn:
            conn.execute(
                "INSERT INTO perfiles (user_id,email,rol,estado,nombre,creado_en) "
                "VALUES (?,?,?,?,?,?) "
                "ON CONFLICT(user_id) DO UPDATE SET email=excluded.email, rol=excluded.rol, "
                "estado=excluded.estado, nombre=excluded.nombre",
                (p.user_id, p.email, p.rol, p.estado, p.nombre, p.creado_en))

    def listar(self) -> list[Perfil]:
        with self.connect() as conn:
            rows = conn.execute("SELECT * FROM perfiles ORDER BY email").fetchall()
        return [self._fila(r) for r in rows]

    def set_rol(self, user_id: str, rol: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE perfiles SET rol=? WHERE user_id=?", (rol, user_id))

    def set_estado(self, user_id: str, estado: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE perfiles SET estado=? WHERE user_id=?", (estado, user_id))

    def contar_admins_activos(self) -> int:
        with self.connect() as conn:
            return conn.execute(
                "SELECT COUNT(*) FROM perfiles WHERE rol='admin' AND estado='activo'"
            ).fetchone()[0]
```

- [ ] **Step 6: `PerfilesPg` (Postgres)**

Create `apu_tool/datos/pg/perfiles_pg.py`:
```python
"""Acceso Postgres a seguridad.perfiles. Implementa RepositorioPerfiles. Port de perfiles_db."""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
from apu_tool.nucleo.models import Perfil

SCHEMA_PATH = config.PROJECT_ROOT / "db" / "pg" / "seguridad.sql"


class PerfilesPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def init_schema(self) -> None:
        with self.cx.connection() as conn:
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    def reset(self) -> None:
        with self.cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS seguridad CASCADE")
            ejecutar_script(conn, SCHEMA_PATH.read_text(encoding="utf-8"))

    def _fila(self, r) -> Perfil:
        return Perfil(user_id=r["user_id"], email=r["email"], rol=r["rol"],
                      estado=r["estado"], nombre=r["nombre"] or "",
                      creado_en=r["creado_en"] or "")

    def get(self, user_id: str) -> Optional[Perfil]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM seguridad.perfiles WHERE user_id=%s",
                             (user_id,)).fetchone()
        return self._fila(r) if r else None

    def upsert(self, p: Perfil) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "INSERT INTO seguridad.perfiles (user_id,email,rol,estado,nombre,creado_en) "
                "VALUES (%s,%s,%s,%s,%s,%s) "
                "ON CONFLICT (user_id) DO UPDATE SET email=EXCLUDED.email, rol=EXCLUDED.rol, "
                "estado=EXCLUDED.estado, nombre=EXCLUDED.nombre",
                (p.user_id, p.email, p.rol, p.estado, p.nombre, p.creado_en))

    def listar(self) -> list[Perfil]:
        with self.cx.connection() as conn:
            rows = conn.execute("SELECT * FROM seguridad.perfiles ORDER BY email").fetchall()
        return [self._fila(r) for r in rows]

    def set_rol(self, user_id: str, rol: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE seguridad.perfiles SET rol=%s WHERE user_id=%s", (rol, user_id))

    def set_estado(self, user_id: str, estado: str) -> None:
        with self.cx.connection() as conn:
            conn.execute("UPDATE seguridad.perfiles SET estado=%s WHERE user_id=%s",
                         (estado, user_id))

    def contar_admins_activos(self) -> int:
        with self.cx.connection() as conn:
            return conn.execute(
                "SELECT COUNT(*) AS n FROM seguridad.perfiles "
                "WHERE rol='admin' AND estado='activo'").fetchone()["n"]
```

- [ ] **Step 7: `RepositorioPerfiles` en repositorio.py**

Añadir a `apu_tool/datos/repositorio.py` (tras los otros Protocols; añadir `Perfil` al import de models):
```python
@runtime_checkable
class RepositorioPerfiles(Protocol):
    def init_schema(self) -> None: ...
    def reset(self) -> None: ...
    def get(self, user_id: str) -> Optional[Perfil]: ...
    def upsert(self, perfil: Perfil) -> None: ...
    def listar(self) -> list[Perfil]: ...
    def set_rol(self, user_id: str, rol: str) -> None: ...
    def set_estado(self, user_id: str, estado: str) -> None: ...
    def contar_admins_activos(self) -> int: ...
```
(Actualizar la línea `from apu_tool.nucleo.models import (...)` para incluir `Perfil`.)

- [ ] **Step 8: Wire en `Almacen`**

En `apu_tool/datos/almacen.py`, dentro de `__init__`, añadir la creación de `self.perfiles` en AMBAS ramas, y en `init_schema` inicializarlo. En la rama `postgres` (bloque `if config.db_backend() == "postgres"`):
```python
            from apu_tool.datos.pg.perfiles_pg import PerfilesPg
            self.perfiles = PerfilesPg(self._cx)
```
En la rama `else` (SQLite), tras crear los otros repos:
```python
            from apu_tool.datos.perfiles_db import PerfilesDB
            self.perfiles = PerfilesDB(precios_path.parent / "seguridad.db"
                                       if isinstance(precios_path, Path) else config.DATA_DIR / "seguridad.db")
```
Nota: para mantener los tests aislados por `tmp_path`, `PerfilesDB` se ubica junto a las otras DBs de esa corrida. Simplifica: deriva la carpeta de `precios_path`. Añadir `from pathlib import Path` ya está importado.
En `init_schema(self)` añadir al final: `self.perfiles.init_schema()`.

- [ ] **Step 9: Verificar contrato + no-regresión**

Run: `python -m pytest tests/test_perfiles_contrato.py -v`
Expected: PASS en sqlite (4 tests); postgres omitido.
Run: `python -m pytest tests/ -q`
Expected: 186 passed (182 + 4). Los tests existentes que crean `Almacen(...).init_schema()` ahora también crean perfiles — deben seguir verdes.

- [ ] **Step 10: Commit**
```bash
git add db/seguridad.sql db/pg/seguridad.sql apu_tool/nucleo/models.py apu_tool/datos/repositorio.py apu_tool/datos/perfiles_db.py apu_tool/datos/pg/perfiles_pg.py apu_tool/datos/almacen.py tests/test_perfiles_contrato.py
git commit -m "feat(datos): tabla perfiles + repositorio dual (RBAC)"
```

---

### Task 4: resolver_perfil + usuario_actual + requiere_rol

**Files:**
- Modify: `apu_tool/servicio/auth.py`
- Modify: `apu_tool/servicio/dependencias.py` (reutilizar `get_almacen`)
- Test: `tests/test_auth_rbac.py`

**Interfaces:**
- Consumes: `obtener_claims` (Task 2), `Almacen.perfiles` (Task 3), `config.admin_emails()` (Task 1), `get_almacen` (existente).
- Produces:
  - `resolver_perfil(alm, user_id, email) -> Perfil` — bootstrap admin / invitado / deniega. Lanza `ErrorAuth` si no autorizado o inactivo.
  - `RANGO = {"consulta":1,"editor":2,"admin":3}`.
  - `usuario_actual(request, alm=Depends(get_almacen)) -> Perfil` — dependencia FastAPI (401/403).
  - `requiere_rol(minimo: str)` — fábrica de dependencia (403 si rol < mínimo).

- [ ] **Step 1: Escribir el test (falla)**

Create `tests/test_auth_rbac.py`:
```python
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auth import ErrorAuth, resolver_perfil, RANGO


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_bootstrap_admin_por_env(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_ADMIN_EMAILS", "jefe@obra.co")
    alm = _alm(tmp_path)
    p = resolver_perfil(alm, "u1", "Jefe@Obra.CO")   # case-insensitive
    assert p.rol == "admin" and p.estado == "activo"
    assert alm.perfiles.get("u1").rol == "admin"      # persistió


def test_invitado_existente_se_devuelve(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u2", "e@obra.co", "editor", "activo"))
    assert resolver_perfil(alm, "u2", "e@obra.co").rol == "editor"


def test_inactivo_deniega(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u3", "x@obra.co", "consulta", "inactivo"))
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "u3", "x@obra.co")


def test_desconocido_no_admin_deniega(tmp_path, monkeypatch):
    monkeypatch.delenv("APU_ADMIN_EMAILS", raising=False)
    alm = _alm(tmp_path)
    with pytest.raises(ErrorAuth):
        resolver_perfil(alm, "u4", "ajeno@obra.co")


def test_jerarquia_rangos():
    assert RANGO["admin"] > RANGO["editor"] > RANGO["consulta"]
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_auth_rbac.py -v`
Expected: FAIL (`resolver_perfil`/`RANGO` no existen).

- [ ] **Step 3: Implementar en `auth.py`**

Añadir a `apu_tool/servicio/auth.py`:
```python
import datetime as _dt

from fastapi import Depends, Request, HTTPException

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.dependencias import get_almacen

RANGO = {"consulta": 1, "editor": 2, "admin": 3}


def resolver_perfil(alm: Almacen, user_id: str, email: str) -> Perfil:
    """Devuelve el Perfil activo del usuario; bootstrap admin por APU_ADMIN_EMAILS.

    Lanza ErrorAuth si el usuario está inactivo o no está autorizado (no invitado).
    """
    p = alm.perfiles.get(user_id)
    if p is not None:
        if p.estado != "activo":
            raise ErrorAuth("Usuario inactivo.")
        return p
    if (email or "").strip().lower() in config.admin_emails():
        nuevo = Perfil(user_id=user_id, email=email, rol="admin", estado="activo",
                       nombre="", creado_en=_dt.date.today().isoformat())
        alm.perfiles.upsert(nuevo)
        return nuevo
    raise ErrorAuth("Usuario no autorizado (no invitado).")


def _extraer_bearer(request: Request) -> str:
    h = request.headers.get("authorization") or request.headers.get("Authorization") or ""
    if not h.lower().startswith("bearer "):
        raise ErrorAuth("Falta el token Bearer.")
    return h[7:].strip()


def usuario_actual(request: Request, alm: Almacen = Depends(get_almacen)) -> Perfil:
    """Dependencia FastAPI: verifica el JWT y resuelve el perfil. 401/403."""
    try:
        token = _extraer_bearer(request)
        claims = obtener_claims(token)
    except ErrorAuth as e:
        raise HTTPException(status_code=401, detail=str(e))
    user_id = claims.get("sub", "")
    email = claims.get("email", "")
    try:
        return resolver_perfil(alm, user_id, email)
    except ErrorAuth as e:
        raise HTTPException(status_code=403, detail=str(e))


def requiere_rol(minimo: str):
    """Fábrica de dependencia: exige rol >= minimo (jerarquía). 403 si no."""
    min_rango = RANGO[minimo]

    def _dep(usuario: Perfil = Depends(usuario_actual)) -> Perfil:
        if RANGO.get(usuario.rol, 0) < min_rango:
            raise HTTPException(status_code=403, detail="Permiso insuficiente.")
        return usuario
    return _dep
```

- [ ] **Step 4: Verificar que pasa + no-regresión**

Run: `python -m pytest tests/test_auth_rbac.py -v`
Expected: PASS (5 tests).
Run: `python -m pytest tests/ -q`
Expected: 191 passed.

- [ ] **Step 5: Commit**
```bash
git add apu_tool/servicio/auth.py tests/test_auth_rbac.py
git commit -m "feat(auth): resolver_perfil (bootstrap) + usuario_actual + requiere_rol"
```

---

### Task 5: Cliente Admin de Supabase + servicio de usuarios

**Files:**
- Create: `apu_tool/servicio/supabase_admin.py`
- Create: `apu_tool/servicio/usuarios.py`
- Test: `tests/test_servicio_usuarios.py`

**Interfaces:**
- Consumes: `Almacen.perfiles`, `Perfil`, `config.supabase_url()`, `config.supabase_service_role_key()`.
- Produces:
  - `class AdminSupabase(Protocol)`: `invitar(email: str) -> str` (devuelve el `user_id` creado).
  - `AdminSupabaseHTTP` (impl real, httpx) y `AdminSupabaseFake` (tests).
  - `usuarios.listar(alm) -> list[dict]`
  - `usuarios.invitar(alm, admin, email, rol, nombre) -> dict` — crea/invita en Supabase + upsert perfil. `ValueError` si rol inválido o email vacío.
  - `usuarios.cambiar_rol(alm, actor: Perfil, user_id, rol) -> dict` — con guardrail del último admin.
  - `usuarios.cambiar_estado(alm, actor: Perfil, user_id, estado) -> dict` — con guardrail del último admin.

- [ ] **Step 1: Escribir el test (falla)**

Create `tests/test_servicio_usuarios.py`:
```python
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import usuarios as svc
from apu_tool.servicio.supabase_admin import AdminSupabaseFake


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def _actor_admin():
    return Perfil("admin-0", "root@obra.co", "admin", "activo")


def test_invitar_crea_perfil(tmp_path):
    alm = _alm(tmp_path)
    admin = AdminSupabaseFake(id_por_email={"nuevo@obra.co": "u-nuevo"})
    out = svc.invitar(alm, admin, "nuevo@obra.co", "editor", "Nuevo")
    assert out["user_id"] == "u-nuevo"
    p = alm.perfiles.get("u-nuevo")
    assert p.rol == "editor" and p.estado == "activo" and p.email == "nuevo@obra.co"


def test_invitar_rol_invalido(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError):
        svc.invitar(alm, AdminSupabaseFake(), "x@obra.co", "superuser", "X")


def test_cambiar_rol(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    svc.cambiar_rol(alm, _actor_admin(), "u1", "editor")
    assert alm.perfiles.get("u1").rol == "editor"


def test_guardrail_no_degradar_ultimo_admin(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))  # único admin
    with pytest.raises(ValueError):
        svc.cambiar_rol(alm, _actor_admin(), "u1", "editor")
    with pytest.raises(ValueError):
        svc.cambiar_estado(alm, _actor_admin(), "u1", "inactivo")
    assert alm.perfiles.get("u1").rol == "admin" and alm.perfiles.get("u1").estado == "activo"


def test_guardrail_permite_si_hay_otro_admin(tmp_path):
    alm = _alm(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    alm.perfiles.upsert(Perfil("u2", "b@obra.co", "admin", "activo"))
    svc.cambiar_estado(alm, _actor_admin(), "u1", "inactivo")   # queda u2 admin activo
    assert alm.perfiles.get("u1").estado == "inactivo"
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_servicio_usuarios.py -v`
Expected: FAIL (módulos no existen).

- [ ] **Step 3: `supabase_admin.py`**

Create `apu_tool/servicio/supabase_admin.py`:
```python
"""Cliente de la Admin API de Supabase Auth, tras una interfaz (fake en tests).

Solo se usa server-side con la service_role key. Llama por HTTPS (443), así que
funciona aunque los puertos de BD estén bloqueados.
"""
from __future__ import annotations

from typing import Protocol, runtime_checkable

import httpx

from apu_tool import config


@runtime_checkable
class AdminSupabase(Protocol):
    def invitar(self, email: str) -> str:
        """Invita/crea el usuario en Supabase Auth; devuelve su user_id (UUID)."""
        ...


class AdminSupabaseHTTP:
    """Implementación real contra la Admin API de Supabase."""

    def invitar(self, email: str) -> str:
        base = config.supabase_url()
        key = config.supabase_service_role_key()
        if not base or not key:
            raise RuntimeError("Falta SUPABASE_URL/SERVICE_ROLE_KEY para invitar.")
        headers = {"Authorization": f"Bearer {key}", "apikey": key,
                   "Content-Type": "application/json"}
        r = httpx.post(f"{base}/auth/v1/invite", headers=headers,
                       json={"email": email}, timeout=20.0)
        r.raise_for_status()
        return r.json()["id"]


class AdminSupabaseFake:
    """Fake para tests: no llama a la red; asigna ids deterministas."""

    def __init__(self, id_por_email: dict | None = None):
        self._ids = id_por_email or {}
        self.invitados: list[str] = []

    def invitar(self, email: str) -> str:
        self.invitados.append(email)
        return self._ids.get(email, f"fake-{email}")
```

- [ ] **Step 4: `usuarios.py`**

Create `apu_tool/servicio/usuarios.py`:
```python
"""Lógica de gestión de usuarios (solo-Admin). Mutaciones sensibles: ganchos para
auditoría del Plan 3. No toca dinero."""
from __future__ import annotations

import datetime as dt

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.supabase_admin import AdminSupabase

_ROLES = {"admin", "editor", "consulta"}
_ESTADOS = {"activo", "inactivo"}


def listar(alm: Almacen) -> list[dict]:
    return [{"user_id": p.user_id, "email": p.email, "rol": p.rol,
             "estado": p.estado, "nombre": p.nombre} for p in alm.perfiles.listar()]


def invitar(alm: Almacen, admin: AdminSupabase, email: str, rol: str,
            nombre: str = "") -> dict:
    email = (email or "").strip().lower()
    if not email:
        raise ValueError("El email es obligatorio.")
    if rol not in _ROLES:
        raise ValueError(f"Rol inválido: {rol}.")
    user_id = admin.invitar(email)
    alm.perfiles.upsert(Perfil(user_id=user_id, email=email, rol=rol, estado="activo",
                               nombre=nombre, creado_en=dt.date.today().isoformat()))
    return {"user_id": user_id, "email": email, "rol": rol, "estado": "activo"}


def _existe(alm: Almacen, user_id: str) -> Perfil:
    p = alm.perfiles.get(user_id)
    if p is None:
        raise ValueError("Usuario no encontrado.")
    return p


def _proteger_ultimo_admin(alm: Almacen, objetivo: Perfil) -> None:
    """Impide dejar el sistema sin ningún admin activo."""
    if objetivo.rol == "admin" and objetivo.estado == "activo" \
            and alm.perfiles.contar_admins_activos() <= 1:
        raise ValueError("No se puede degradar/desactivar al último Admin activo.")


def cambiar_rol(alm: Almacen, actor: Perfil, user_id: str, rol: str) -> dict:
    if rol not in _ROLES:
        raise ValueError(f"Rol inválido: {rol}.")
    objetivo = _existe(alm, user_id)
    if rol != "admin":
        _proteger_ultimo_admin(alm, objetivo)
    alm.perfiles.set_rol(user_id, rol)
    return {"user_id": user_id, "rol": rol}


def cambiar_estado(alm: Almacen, actor: Perfil, user_id: str, estado: str) -> dict:
    if estado not in _ESTADOS:
        raise ValueError(f"Estado inválido: {estado}.")
    objetivo = _existe(alm, user_id)
    if estado == "inactivo":
        _proteger_ultimo_admin(alm, objetivo)
    alm.perfiles.set_estado(user_id, estado)
    return {"user_id": user_id, "estado": estado}
```

- [ ] **Step 5: Verificar que pasa + no-regresión**

Run: `python -m pytest tests/test_servicio_usuarios.py -v`
Expected: PASS (5 tests).
Run: `python -m pytest tests/ -q`
Expected: 196 passed.

- [ ] **Step 6: Commit**
```bash
git add apu_tool/servicio/supabase_admin.py apu_tool/servicio/usuarios.py tests/test_servicio_usuarios.py
git commit -m "feat(auth): cliente Admin de Supabase (fake) + servicio de usuarios con guardrail"
```

---

### Task 6: conftest de auth + endpoints /api/usuarios (solo Admin)

**Files:**
- Create: `tests/conftest.py`
- Modify: `apu_tool/servicio/esquemas.py` (schemas Pydantic de usuarios)
- Modify: `apu_tool/servicio/rutas.py` (endpoints `/usuarios`, + dependencia del cliente Admin)
- Test: `tests/test_api_usuarios.py`

**Interfaces:**
- Consumes: `requiere_rol` (Task 4), `usuarios` (Task 5), `AdminSupabaseHTTP`/`AdminSupabaseFake` (Task 5), `usuario_actual` (Task 4).
- Produces:
  - `tests/conftest.py`: `perfil_de_prueba(rol="admin")` y `cliente(app, rol="admin")` que aplica `app.dependency_overrides[usuario_actual]`.
  - Rutas: `GET /api/usuarios`, `POST /api/usuarios/invitar`, `PATCH /api/usuarios/{user_id}/rol`, `PATCH /api/usuarios/{user_id}/estado`, todas con `Depends(requiere_rol("admin"))`.
  - Dependencia `get_admin_supabase()` (override en tests con el fake).

- [ ] **Step 1: `tests/conftest.py`**

Create `tests/conftest.py`:
```python
"""Fixtures compartidos de tests. Override de auth para los tests de API."""
from fastapi.testclient import TestClient

from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.auth import usuario_actual


def perfil_de_prueba(rol: str = "admin") -> Perfil:
    return Perfil(user_id=f"test-{rol}", email=f"{rol}@test.co", rol=rol, estado="activo")


def cliente(app, rol: str = "admin") -> TestClient:
    """TestClient con usuario_actual sobreescrito por un perfil de prueba."""
    app.dependency_overrides[usuario_actual] = lambda: perfil_de_prueba(rol)
    return TestClient(app)
```

- [ ] **Step 2: Escribir el test de la API de usuarios (falla)**

Create `tests/test_api_usuarios.py`:
```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio.app import create_app
from apu_tool.servicio import rutas
from apu_tool.servicio.supabase_admin import AdminSupabaseFake
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    app = create_app(almacen=alm)
    fake = AdminSupabaseFake(id_por_email={"nuevo@obra.co": "u-nuevo"})
    app.dependency_overrides[rutas.get_admin_supabase] = lambda: fake
    return app, alm


def test_invitar_y_listar_como_admin(tmp_path):
    app, alm = _app(tmp_path)
    cli = cliente(app, rol="admin")
    r = cli.post("/api/usuarios/invitar",
                 json={"email": "nuevo@obra.co", "rol": "editor", "nombre": "Nuevo"})
    assert r.status_code == 200, r.text
    assert r.json()["user_id"] == "u-nuevo"
    lst = cli.get("/api/usuarios")
    assert lst.status_code == 200 and any(u["email"] == "nuevo@obra.co" for u in lst.json())


def test_usuarios_prohibido_para_editor(tmp_path):
    app, _ = _app(tmp_path)
    cli = cliente(app, rol="editor")
    assert cli.get("/api/usuarios").status_code == 403
    assert cli.post("/api/usuarios/invitar",
                    json={"email": "x@obra.co", "rol": "editor"}).status_code == 403


def test_cambiar_rol_y_estado(tmp_path):
    app, alm = _app(tmp_path)
    alm.perfiles.upsert(Perfil("u1", "a@obra.co", "consulta", "activo"))
    cli = cliente(app, rol="admin")
    assert cli.patch("/api/usuarios/u1/rol", json={"rol": "editor"}).status_code == 200
    assert alm.perfiles.get("u1").rol == "editor"
    assert cli.patch("/api/usuarios/u1/estado", json={"estado": "inactivo"}).status_code == 200
    assert alm.perfiles.get("u1").estado == "inactivo"
```

- [ ] **Step 3: Verificar que falla**

Run: `python -m pytest tests/test_api_usuarios.py -v`
Expected: FAIL (rutas/`get_admin_supabase` no existen).

- [ ] **Step 4: Schemas Pydantic**

Añadir a `apu_tool/servicio/esquemas.py`:
```python
class UsuarioInvitarIn(BaseModel):
    email: str
    rol: str
    nombre: str = ""


class RolIn(BaseModel):
    rol: str


class EstadoIn(BaseModel):
    estado: str
```
(Si `BaseModel` no está importado en el archivo, añadir `from pydantic import BaseModel`.)

- [ ] **Step 5: Rutas de usuarios**

En `apu_tool/servicio/rutas.py`:

Añadir imports:
```python
from apu_tool.servicio.auth import requiere_rol
from apu_tool.servicio import usuarios as usuarios_svc
from apu_tool.servicio.supabase_admin import AdminSupabase, AdminSupabaseHTTP
from apu_tool.servicio.esquemas import UsuarioInvitarIn, RolIn, EstadoIn
```

Añadir la dependencia del cliente Admin (cerca de la cabecera del router):
```python
def get_admin_supabase() -> AdminSupabase:
    return AdminSupabaseHTTP()
```

Añadir los endpoints (protegidos con `requiere_rol("admin")`):
```python
@router.get("/usuarios")
def usuarios_listar(alm: Almacen = Depends(get_almacen),
                    _: object = Depends(requiere_rol("admin"))):
    return usuarios_svc.listar(alm)


@router.post("/usuarios/invitar")
def usuarios_invitar(body: UsuarioInvitarIn, alm: Almacen = Depends(get_almacen),
                     admin=Depends(get_admin_supabase),
                     _: object = Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.invitar(alm, admin, body.email, body.rol, body.nombre)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/usuarios/{user_id}/rol")
def usuarios_cambiar_rol(user_id: str, body: RolIn,
                         alm: Almacen = Depends(get_almacen),
                         actor=Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.cambiar_rol(alm, actor, user_id, body.rol)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/usuarios/{user_id}/estado")
def usuarios_cambiar_estado(user_id: str, body: EstadoIn,
                            alm: Almacen = Depends(get_almacen),
                            actor=Depends(requiere_rol("admin"))):
    try:
        return usuarios_svc.cambiar_estado(alm, actor, user_id, body.estado)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```
Nota: `requiere_rol("admin")` devuelve el `Perfil` del actor; en las rutas que lo necesitan (`actor=Depends(...)`) se usa como identidad del que ejecuta la acción.

- [ ] **Step 6: Verificar que pasa + no-regresión**

Run: `python -m pytest tests/test_api_usuarios.py -v`
Expected: PASS (3 tests).
Run: `python -m pytest tests/ -q`
Expected: 199 passed (196 + 3).

- [ ] **Step 7: Commit**
```bash
git add tests/conftest.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_usuarios.py
git commit -m "feat(api): endpoints /api/usuarios (solo Admin) + conftest de override de auth"
```

---

### Task 7: Proteger TODOS los endpoints existentes + actualizar tests de API

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (añadir `Depends(requiere_rol(...))` por endpoint)
- Modify: `tests/test_api_corridas.py`, `tests/test_api_insumos.py`, `tests/test_api_autoria.py` (usar el override)
- Test: reutiliza los existentes + un test de 401/403.

**Interfaces:**
- Consumes: `requiere_rol` (Task 4), `cliente` de conftest (Task 6).

**Matriz (rol mínimo por endpoint):**
- **Consulta**: `GET /status`, `GET /corridas`, `POST /corridas`, `POST /sample`, `POST /corridas/stream`, `POST /sample/stream`, `GET /corridas/{cid}`, `GET /corridas/{cid}/items/{seq}`, `POST /corridas/{cid}/items/{seq}/confirmar`, `GET /corridas/{cid}/cuadro`, `DELETE /corridas/{cid}`, `GET /insumos`, `GET /insumos/grupos`, `GET /insumos/fuentes`, `GET /insumos/{id}`, `GET /apus`, `GET /apus/{codigo}/{turno}`.
- **Editor**: `POST /insumos/cambios`, `POST /insumos/importar/preview`, `POST /insumos/transformar/preview`, `POST /insumos/crear`, `POST /insumos/importar-crear/preview`, `POST /insumos/importar-crear`, `POST /apus/crear`, `POST /apus/importar/preview`, `POST /apus/importar`.
- **Admin**: `/usuarios/*` (ya en Task 6).

- [ ] **Step 1: Escribir el test de autorización (falla)**

Create `tests/test_api_autorizacion.py`:
```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_consulta_puede_ver_pero_no_editar(tmp_path):
    app = _app(tmp_path)
    cli = cliente(app, rol="consulta")
    assert cli.get("/api/insumos").status_code == 200            # ver: OK
    r = cli.post("/api/insumos/crear",
                 json={"codigo": "9", "nombre": "X", "unidad": "U", "grupo": "G",
                       "precio": 1.0, "fuente_precio": "COSTO INTERNO"})
    assert r.status_code == 403                                   # editar: prohibido


def test_editor_puede_editar_catalogo(tmp_path):
    app = _app(tmp_path)
    cli = cliente(app, rol="editor")
    r = cli.post("/api/insumos/crear",
                 json={"codigo": "9", "nombre": "X", "unidad": "U", "grupo": "G",
                       "precio": 1.0, "fuente_precio": "COSTO INTERNO"})
    assert r.status_code == 200, r.text


def test_sin_override_no_autenticado_da_401(tmp_path):
    # sin dependency_overrides: no hay token → 401
    from fastapi.testclient import TestClient
    app = _app(tmp_path)
    cli = TestClient(app)
    assert cli.get("/api/insumos").status_code == 401
```

- [ ] **Step 2: Verificar que falla**

Run: `python -m pytest tests/test_api_autorizacion.py -v`
Expected: FAIL (los endpoints aún no exigen rol → `crear` daría 200 para consulta; sin override daría 200 en vez de 401).

- [ ] **Step 3: Aplicar `requiere_rol` a cada endpoint de `rutas.py`**

A cada endpoint existente, añadir un parámetro de dependencia según la matriz. Para los de solo-lectura y de corridas (Consulta):
```python
_: object = Depends(requiere_rol("consulta"))
```
Para los de mutación de catálogo (Editor):
```python
_: object = Depends(requiere_rol("editor"))
```
Ejemplo concreto (endpoint de Consulta) — `GET /insumos`:
```python
@router.get("/insumos")
def listar_insumos(q: Optional[str] = None, grupo: Optional[str] = None,
                   fuente: Optional[str] = None, clasificacion: Optional[str] = None,
                   limit: int = 100, offset: int = 0,
                   alm: Almacen = Depends(get_almacen),
                   _: object = Depends(requiere_rol("consulta"))):
    return insumos_svc.listar(alm, q, grupo, fuente, clasificacion, limit, offset)
```
Ejemplo concreto (endpoint de Editor) — `POST /insumos/crear`:
```python
@router.post("/insumos/crear")
def crear_insumo(body: InsumoNuevoIn, alm: Almacen = Depends(get_almacen),
                 _: object = Depends(requiere_rol("editor"))):
    try:
        return autoria.crear_insumo(alm, body.model_dump())
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```
Aplicar el mismo patrón a TODOS los endpoints de la matriz de arriba. Los endpoints con `UploadFile`/`Form` (p. ej. `crear_corrida`) añaden el `_: object = Depends(requiere_rol("consulta"))` como último parámetro. NO tocar el orden de los parámetros de `File`/`Form` existentes; añadir la dependencia al final.

- [ ] **Step 4: Actualizar los tests de API existentes para usar el override**

En `tests/test_api_corridas.py`, `tests/test_api_insumos.py` y `tests/test_api_autoria.py`: donde se construye `TestClient(create_app(almacen=alm))`, reemplazar por el helper con override. Concretamente, en `test_api_corridas.py` el helper `_cliente`:
```python
from tests.conftest import cliente   # añadir import

def _cliente(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return cliente(create_app(almacen=alm), rol="admin"), alm   # override admin
```
Hacer el cambio equivalente (envolver `create_app(...)` con `cliente(..., rol="admin")` importado de `tests.conftest`) en `test_api_insumos.py` y `test_api_autoria.py` en su(s) helper(s) que construyen el `TestClient`. Los tests que llaman servicios directo (`test_servicio_*`) NO se tocan.

- [ ] **Step 5: Verificar todo verde**

Run: `python -m pytest tests/test_api_autorizacion.py -v`
Expected: PASS (3 tests).
Run: `python -m pytest tests/ -q`
Expected: 202 passed (199 + 3), 0 fallos. Si algún `test_api_*` falla con 401/403, revisar que su helper use `cliente(..., rol="admin")`.

- [ ] **Step 6: Commit**
```bash
git add apu_tool/servicio/rutas.py tests/test_api_corridas.py tests/test_api_insumos.py tests/test_api_autoria.py tests/test_api_autorizacion.py
git commit -m "feat(api): RBAC en todos los endpoints (requiere_rol) + tests de API con override"
```

---

### Task 8: Migración RLS (defensa en profundidad)

**Files:**
- Create: `supabase/migrations/0002_rls.sql`

**Interfaces:** ninguna de código; artefacto SQL que se aplica vía MCP/CLI de Supabase.

- [ ] **Step 1: Escribir la migración**

Create `supabase/migrations/0002_rls.sql`:
```sql
-- Defensa en profundidad: habilitar RLS SIN policies en todas las tablas.
-- Bloquea anon/authenticated; la service_role (FastAPI) hace bypass de RLS.
ALTER TABLE precios.insumos            ENABLE ROW LEVEL SECURITY;
ALTER TABLE precios.insumo_precios     ENABLE ROW LEVEL SECURITY;
ALTER TABLE precios.meta               ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.apus                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.apu_componentes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.meta                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.corrida           ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.corrida_item      ENABLE ROW LEVEL SECURITY;
ALTER TABLE seguridad.perfiles         ENABLE ROW LEVEL SECURITY;
```

- [ ] **Step 2: Aplicar y verificar contra Supabase (vía MCP)**

Esto lo ejecuta el controlador (no un test local): aplicar el SQL con el MCP de Supabase (`execute_sql`/`apply_migration`) contra el proyecto `BASE APUS`, luego verificar:
```sql
SELECT relnamespace::regnamespace AS schema, relname, relrowsecurity
FROM pg_class
WHERE relname IN ('insumos','insumo_precios','meta','apus','apu_componentes',
                  'corrida','corrida_item','perfiles') AND relkind='r'
ORDER BY 1,2;
```
Expected: `relrowsecurity = true` en las 9 tablas. Confirmar además que una consulta con la service_role (p. ej. `execute_sql` normal) sigue funcionando (bypass de RLS).

- [ ] **Step 3: Commit**
```bash
git add supabase/migrations/0002_rls.sql
git commit -m "feat(seguridad): migración RLS sin policies (defensa en profundidad)"
```

---

## Self-Review

**Cobertura del spec:**
- JWT asimétrico/JWKS (spec §2) → Task 2. ✅
- `usuario_actual`/`requiere_rol`/`Usuario`(=`Perfil`) (spec §2/§3) → Task 4. ✅ (Nota: se consolidó `Usuario`→`Perfil`, un solo tipo; simplificación justificada.)
- `perfiles` schema `seguridad` + repo dual + Almacen (spec §3) → Task 3. ✅
- `resolver_perfil` con bootstrap APU_ADMIN_EMAILS (spec §3) → Task 4. ✅
- Matriz RBAC aplicada a rutas (spec §3) → Task 7. ✅ (Nota: `requiere_rol(minimo)` con jerarquía en vez de `*roles`; el admin cubre todo.)
- Gestión de usuarios solo-Admin + Admin API tras interfaz fake + guardrail último admin (spec §4) → Tasks 5,6. ✅
- RLS sin policies (spec §5) → Task 8. ✅
- Pruebas sin BD viva + override de tests API (spec §6) → Tasks 2,4,5,6,7 (conftest). ✅
- Invariante #1 intacta / no romper 173 (spec §7) → ningún task toca dominio/privacy; Task 7 mantiene verde con override. ✅

**Placeholder scan:** sin TODO/TBD; todo paso con código lo trae completo. Únicas indirecciones: Task 7 Step 3/4 aplican el mismo patrón mecánico (`Depends(requiere_rol(...))`) a la lista enumerada de endpoints y el `cliente(...)` a 3 archivos de test nombrados — patrón mostrado con ejemplos concretos.

**Consistencia de tipos:** `Perfil` (models) usado en repo, auth, usuarios, rutas y tests con la misma firma. `requiere_rol(minimo)`/`usuario_actual`/`resolver_perfil` con firmas consistentes. `AdminSupabase.invitar(email)->user_id` consistente entre HTTP/Fake/servicio/tests. `get_admin_supabase`/`usuario_actual` como puntos de `dependency_overrides`.

**Riesgo abierto conocido:** `esquemas.py` y `rutas.py` no se releyeron línea por línea al escribir el plan; el implementador debe (a) confirmar si `BaseModel` ya está importado en `esquemas.py`, (b) añadir la dependencia RBAC como ÚLTIMO parámetro en endpoints con `File`/`Form` sin alterar el orden de los existentes. La suite (Task 7 Step 5) es la red que lo caza.
