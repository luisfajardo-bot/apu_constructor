# Fix Auditoría — 8 Important + Minors — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arreglar los 8 Important + Minors seleccionados de la auditoría (TOCTOU último-admin, bootstrap sin auditar, LIKE/ILIKE, migrate-pg no idempotente, bypass de subida, descarga 401, visor de auditoría, flag noAutorizado, docs públicos, código muerto) y documentar el resto.

**Architecture:** Fixes puntuales por adición; los que tienen parte Postgres se validan en CI (`postgres:17`). Invariante #1 intacta (no se toca `dominio/privacy.py`/`ai_assist.py`/`DePriced*`).

**Tech Stack:** Python/FastAPI, psycopg v3, SQLite, slowapi, React/Vite/vitest.

## Global Constraints

- **Invariante #1:** NO tocar `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py`, ni `DePriced*`.
- **Cero regresiones:** 255 tests backend + 19 vitest verdes; cada tarea AÑADE tests que reproducen el bug (TDD, RED primero).
- **Postgres se valida en CI** (`postgres:17` + `TEST_DATABASE_URL`); local corre SQLite y salta Postgres (patrón `tests/test_repositorios_contrato.py`, fixture `repos`; `tests/test_perfiles_contrato.py`, fixture `repo`).
- **Español**; **frontend** con `npm test` (vitest) + `npm run build` (dentro de `web/`).
- **DISCIPLINA DE COMMIT:** `git add` SOLO los archivos de cada tarea por ruta explícita. NUNCA `-A`/`.`/`-u`. El borrado de `apu_tool/dominio/models.py` es `git rm` explícito. `ejemplos/licitacion_ejemplo.xlsx` está modificado FUERA DE ALCANCE — nunca incluirlo.
- **Comando de prueba backend:** `python -m pytest tests/ -q`.
- **`normalizar()`** (`apu_tool/nucleo/texto.py`) devuelve MAYÚSCULAS sin tildes; `insumos.nombre_norm` se guarda así.

---

### Task 1: I1 — TOCTOU último-admin → UPDATE condicional atómico

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (firmas en `RepositorioPerfiles`)
- Modify: `apu_tool/datos/perfiles_db.py` (`set_rol_protegido`, `set_estado_protegido`)
- Modify: `apu_tool/datos/pg/perfiles_pg.py` (idem)
- Modify: `apu_tool/servicio/usuarios.py` (`cambiar_rol`/`cambiar_estado` usan el UPDATE atómico; quitar `_proteger_ultimo_admin`)
- Test: `tests/test_perfiles_contrato.py` (añadir), `tests/test_servicio_usuarios.py` (ya cubre el guardrail; sigue verde)

**Interfaces:**
- Produces: `RepositorioPerfiles.set_rol_protegido(user_id, rol, conn=None) -> bool` y `set_estado_protegido(user_id, estado, conn=None) -> bool` — hacen el UPDATE solo si NO deja el sistema sin admin activo; devuelven si aplicó (rowcount>0).

- [ ] **Step 1: Write the failing test**

En `tests/test_perfiles_contrato.py`, añade (usa la fixture `repo`):

```python
def test_set_rol_protegido_bloquea_ultimo_admin(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    aplicado = repo.set_rol_protegido("u1", "editor")
    assert aplicado is False
    assert repo.get("u1").rol == "admin"        # no cambió


def test_set_rol_protegido_permite_si_hay_otro_admin(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    repo.upsert(Perfil("u2", "b@obra.co", "admin", "activo"))
    assert repo.set_rol_protegido("u1", "editor") is True
    assert repo.get("u1").rol == "editor"


def test_set_estado_protegido_bloquea_ultimo_admin(repo):
    repo.upsert(Perfil("u1", "a@obra.co", "admin", "activo"))
    assert repo.set_estado_protegido("u1", "inactivo") is False
    assert repo.get("u1").estado == "activo"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_perfiles_contrato.py -q`
Expected: FAIL (`AttributeError: 'PerfilesDB' object has no attribute 'set_rol_protegido'`).

- [ ] **Step 3: Añadir las firmas al Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioPerfiles`:

```python
    def set_rol_protegido(self, user_id: str, rol: str, conn=None) -> bool:
        """UPDATE atómico del rol que NO deja el sistema sin admin activo.
        Devuelve True si aplicó, False si lo bloqueó el guard (o el usuario no existe)."""
        ...

    def set_estado_protegido(self, user_id: str, estado: str, conn=None) -> bool:
        """UPDATE atómico del estado con el mismo guard de último-admin. Devuelve si aplicó."""
        ...
```

- [ ] **Step 4: Implementar en SQLite (`perfiles_db.py`)**

En `apu_tool/datos/perfiles_db.py` (clase `PerfilesDB`):

```python
    _GUARD = ("NOT (rol='admin' AND estado='activo' AND "
              "(SELECT COUNT(*) FROM perfiles WHERE rol='admin' AND estado='activo') <= 1)")

    def set_rol_protegido(self, user_id: str, rol: str, conn=None) -> bool:
        sql = f"UPDATE perfiles SET rol=? WHERE user_id=? AND {self._GUARD}"
        if conn is not None:
            return conn.execute(sql, (rol, user_id)).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, (rol, user_id)).rowcount > 0

    def set_estado_protegido(self, user_id: str, estado: str, conn=None) -> bool:
        sql = f"UPDATE perfiles SET estado=? WHERE user_id=? AND {self._GUARD}"
        if conn is not None:
            return conn.execute(sql, (estado, user_id)).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, (estado, user_id)).rowcount > 0
```

- [ ] **Step 5: Implementar en Postgres (`pg/perfiles_pg.py`)**

En `apu_tool/datos/pg/perfiles_pg.py` (clase `PerfilesPg`):

```python
    _GUARD = ("NOT (rol='admin' AND estado='activo' AND "
              "(SELECT COUNT(*) FROM seguridad.perfiles WHERE rol='admin' AND estado='activo') <= 1)")

    def set_rol_protegido(self, user_id: str, rol: str, conn=None) -> bool:
        sql = f"UPDATE seguridad.perfiles SET rol=%s WHERE user_id=%s AND {self._GUARD}"
        if conn is not None:
            return conn.execute(sql, (rol, user_id)).rowcount > 0
        with self.cx.connection() as c:
            return c.execute(sql, (rol, user_id)).rowcount > 0

    def set_estado_protegido(self, user_id: str, estado: str, conn=None) -> bool:
        sql = f"UPDATE seguridad.perfiles SET estado=%s WHERE user_id=%s AND {self._GUARD}"
        if conn is not None:
            return conn.execute(sql, (estado, user_id)).rowcount > 0
        with self.cx.connection() as c:
            return c.execute(sql, (estado, user_id)).rowcount > 0
```

- [ ] **Step 6: Usar el UPDATE atómico en el servicio (`usuarios.py`)**

En `apu_tool/servicio/usuarios.py`: **elimina** `_proteger_ultimo_admin` (líneas 45-49) y reemplaza `cambiar_rol` y `cambiar_estado`:

```python
def cambiar_rol(alm: Almacen, actor: Perfil, user_id: str, rol: str) -> dict:
    if rol not in _ROLES:
        raise ValueError(f"Rol inválido: {rol}.")
    objetivo = _existe(alm, user_id)
    with alm.transaccion("seguridad") as conn:
        if rol == "admin":
            alm.perfiles.set_rol(user_id, rol, conn=conn)   # promover: sin guard
        elif not alm.perfiles.set_rol_protegido(user_id, rol, conn=conn):
            raise ValueError("No se puede degradar/desactivar al último Admin activo.")
        registrar_auditoria(alm, conn, actor, "usuario.cambiar_rol", "usuario", user_id,
                            antes={"rol": objetivo.rol}, despues={"rol": rol})
    return {"user_id": user_id, "rol": rol}


def cambiar_estado(alm: Almacen, actor: Perfil, user_id: str, estado: str) -> dict:
    if estado not in _ESTADOS:
        raise ValueError(f"Estado inválido: {estado}.")
    objetivo = _existe(alm, user_id)
    with alm.transaccion("seguridad") as conn:
        if estado == "inactivo":
            if not alm.perfiles.set_estado_protegido(user_id, "inactivo", conn=conn):
                raise ValueError("No se puede degradar/desactivar al último Admin activo.")
        else:
            alm.perfiles.set_estado(user_id, estado, conn=conn)
        registrar_auditoria(alm, conn, actor, "usuario.cambiar_estado", "usuario", user_id,
                            antes={"estado": objetivo.estado}, despues={"estado": estado})
    return {"user_id": user_id, "estado": estado}
```

(El `raise` dentro del `with alm.transaccion(...)` revierte la tx — nada cambió ni se auditó. `contar_admins_activos` se conserva en los repos.)

- [ ] **Step 7: Run tests to verify they pass**

Run: `python -m pytest tests/test_perfiles_contrato.py tests/test_servicio_usuarios.py -q`
Expected: PASS (nuevos + guardrail existente verdes). Full: `python -m pytest tests/ -q`.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/perfiles_db.py apu_tool/datos/pg/perfiles_pg.py apu_tool/servicio/usuarios.py tests/test_perfiles_contrato.py
git commit -m "fix(usuarios): guard de último-admin atómico (UPDATE condicional), sin TOCTOU (I1)"
```

---

### Task 2: I2 — bootstrap admin auditado

**Files:**
- Modify: `apu_tool/servicio/auth.py` (`resolver_perfil` bootstrap)
- Test: `tests/test_auth_rbac.py` (añadir) o `tests/test_servicio_auditoria.py`

**Interfaces:**
- Consumes: `registrar_auditoria`, `alm.transaccion`.

- [ ] **Step 1: Write the failing test**

En `tests/test_auth_rbac.py` (o crea `tests/test_auth_bootstrap_audit.py`), añade:

```python
def test_bootstrap_admin_deja_auditoria(tmp_path, monkeypatch):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.servicio import auth
    monkeypatch.setenv("APU_ADMIN_EMAILS", "jefe@obra.co")
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    p = auth.resolver_perfil(alm, "u-jefe", "jefe@obra.co")
    assert p.rol == "admin"
    items, total = alm.auditoria.listar(accion="usuario.bootstrap_admin")
    assert total == 1 and items[0]["entidad_id"] == "u-jefe" and items[0]["rol"] == "sistema"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_auth_rbac.py::test_bootstrap_admin_deja_auditoria -q`
Expected: FAIL (`total == 0` — el bootstrap no audita).

- [ ] **Step 3: Auditar el bootstrap en `resolver_perfil`**

En `apu_tool/servicio/auth.py`, añade el import (junto a los otros de servicio, al final del bloque de imports de la línea ~66):

```python
from apu_tool.servicio.auditoria import registrar_auditoria
```

Reemplaza la rama de bootstrap dentro de `resolver_perfil` (líneas 81-85):

```python
    if (email or "").strip().lower() in config.admin_emails():
        nuevo = Perfil(user_id=user_id, email=email, rol="admin", estado="activo",
                       nombre="", creado_en=_dt.date.today().isoformat())
        with alm.transaccion("seguridad") as conn:
            alm.perfiles.upsert(nuevo, conn=conn)
            registrar_auditoria(alm, conn, None, "usuario.bootstrap_admin", "usuario", user_id,
                                antes=None,
                                despues={"email": email, "rol": "admin", "estado": "activo"})
        return nuevo
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_auth_rbac.py tests/test_auth_jwt.py tests/test_api_autorizacion.py -q`
Expected: PASS. Full: `python -m pytest tests/ -q`.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/auth.py tests/test_auth_rbac.py
git commit -m "fix(auth): auditar el bootstrap de admin (usuario.bootstrap_admin) en transacción (I2)"
```

---

### Task 3: I5 — búsqueda de insumos por `nombre_norm` (paridad SQLite/Postgres)

**Files:**
- Modify: `apu_tool/datos/precios_db.py` (`list_insumos`, `search_insumos`, `search_insumos_por_palabras`)
- Modify: `apu_tool/datos/pg/precios_pg.py` (idem)
- Test: `tests/test_repositorios_contrato.py` (añadir)

**Interfaces:** sin cambios de firma; cambia el SQL interno para buscar sobre `nombre_norm` con el término normalizado.

- [ ] **Step 1: Write the failing test**

En `tests/test_repositorios_contrato.py`, añade:

```python
def test_busqueda_insensible_a_acentos_y_caso(repos):
    precios, _ = repos
    precios.insert_insumos([Insumo("100", "HORMIGÓN 3000 PSI", "M3", "MAT", 1.0, "PRECIO IDU")])
    for termino in ("hormigon", "HORMIGÓN", "Hormigon"):
        items, n = precios.list_insumos(q=termino, limit=50, offset=0)
        assert n == 1 and items[0].codigo == "100", termino
    assert [i.codigo for i in precios.search_insumos("hormigon")] == ["100"]
    assert [i.codigo for i in precios.search_insumos_por_palabras(["hormigon"])] == ["100"]
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_repositorios_contrato.py::test_busqueda_insensible_a_acentos_y_caso -q`
Expected: FAIL en SQLite (`LIKE '%hormigon%'` no matchea "HORMIGÓN").

- [ ] **Step 3: SQLite — buscar sobre `nombre_norm` (`precios_db.py`)**

Import: asegura `from apu_tool.nucleo.texto import normalizar` está presente (ya lo está). En `list_insumos`, la cláusula `q`:

```python
        if q:
            where.append("(i.nombre_norm LIKE ? OR UPPER(i.codigo) LIKE ?)")
            like = f"%{normalizar(q)}%"
            params += [like, f"%{normalizar(q)}%"]
```

En `search_insumos`:

```python
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE nombre_norm LIKE ? OR UPPER(codigo) LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

En `search_insumos_por_palabras`:

```python
    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        palabras = [normalizar(p) for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre_norm LIKE ?"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM insumos WHERE {clauses} LIMIT ?", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

- [ ] **Step 4: Postgres — mismos cambios (`pg/precios_pg.py`)**

Import `from apu_tool.nucleo.texto import normalizar` (ya lo usa). En `list_insumos`, la cláusula `q`:

```python
        if q:
            where.append("(i.nombre_norm LIKE %s OR UPPER(i.codigo) LIKE %s)")
            like = f"%{normalizar(q)}%"
            params += [like, like]
```

En `search_insumos`:

```python
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{normalizar(texto)}%"
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id FROM precios.insumos WHERE nombre_norm LIKE %s OR UPPER(codigo) LIKE %s "
                "LIMIT %s", (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

En `search_insumos_por_palabras`:

```python
    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        palabras = [normalizar(p) for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre_norm LIKE %s"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.cx.connection() as conn:
            rows = conn.execute(
                f"SELECT id FROM precios.insumos WHERE {clauses} LIMIT %s", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]
```

(Nota: como `nombre_norm` y `normalizar(q)` están ambos en MAYÚSCULAS sin tildes, `LIKE` da resultados idénticos en SQLite y Postgres — ya no hace falta `ILIKE`. `UPPER(codigo)` es ASCII en ambos. La búsqueda de **APUs** por `nombre` NO se cambia en este plan — se documenta en la Task 11.)

- [ ] **Step 5: Run tests to verify they pass**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_precios_db.py tests/test_matching.py tests/test_matching_optimizacion.py -q`
Expected: PASS (nuevos + los que ejercitan búsqueda/matching verdes). Full: `python -m pytest tests/ -q`.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py tests/test_repositorios_contrato.py
git commit -m "fix(precios): búsqueda de insumos por nombre_norm (paridad SQLite/Postgres, acentos) (I5)"
```

---

### Task 4: I6 — migrate-pg idempotente (`ON CONFLICT DO NOTHING`)

**Files:**
- Modify: `apu_tool/datos/migracion_pg.py` (los 4 INSERT de datos)
- Test: `tests/test_migracion_pg.py` (añadir; corre solo con `TEST_DATABASE_URL` → CI)

**Interfaces:** sin cambios de firma.

- [ ] **Step 1: Write the failing test**

En `tests/test_migracion_pg.py`, añade (gated por `TEST_DATABASE_URL`; en local hace skip). Sigue el patrón del archivo para obtener `cx`/paths SQLite sembrados; el núcleo:

```python
import os
import pytest

@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"), reason="requiere Postgres de prueba")
def test_migrar_catalogo_es_idempotente(tmp_path):
    from apu_tool.datos.pg.conexion import Conexion, ejecutar_script
    from apu_tool.datos import migracion_pg
    from apu_tool import config
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
    # Semilla SQLite mínima
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 10.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "OC"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 1.0, 10.0)])
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    try:
        with cx.connection() as conn:
            conn.execute("DROP SCHEMA IF EXISTS precios CASCADE")
            conn.execute("DROP SCHEMA IF EXISTS apus CASCADE")
        with cx.connection() as conn:
            for f in ("precios.sql", "apus.sql"):
                ejecutar_script(conn, (config.PROJECT_ROOT / "db" / "pg" / f).read_text("utf-8"))
        migracion_pg.migrar_catalogo(tmp_path / "p.db", tmp_path / "a.db", cx)
        migracion_pg.migrar_catalogo(tmp_path / "p.db", tmp_path / "a.db", cx)  # 2ª vez: no debe romper
        ver = migracion_pg.verificar(tmp_path / "p.db", tmp_path / "a.db", cx)
        assert ver["ok"], ver["detalle"]
    finally:
        cx.cerrar()
```

- [ ] **Step 2: Run test to verify it fails**

Run (en CI con `TEST_DATABASE_URL`): `python -m pytest tests/test_migracion_pg.py::test_migrar_catalogo_es_idempotente -q`
Expected: FAIL con `UniqueViolation` en la 2ª migración (local: SKIP).

- [ ] **Step 3: Añadir `ON CONFLICT DO NOTHING` a los 4 INSERT**

En `apu_tool/datos/migracion_pg.py::migrar_catalogo`, añade `ON CONFLICT DO NOTHING` a cada INSERT de datos:

- insumos:
```python
                conn.execute(
                    "INSERT INTO precios.insumos (id, codigo, nombre, nombre_norm, unidad, grupo) "
                    "OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (r["id"], r["codigo"], r["nombre"], r["nombre_norm"], r["unidad"], r["grupo"]))
```
- insumo_precios:
```python
                conn.execute(
                    "INSERT INTO precios.insumo_precios "
                    "(id, insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por) "
                    "OVERRIDING SYSTEM VALUE VALUES (%s,%s,%s,%s,%s,%s,%s,'migración') "
                    "ON CONFLICT DO NOTHING",
                    (r["id"], r["insumo_id"], r["precio"], r["fuente"],
                     r["clasificacion"], r["fecha"], r["vigente"]))
```
- apus:
```python
                conn.execute("INSERT INTO apus.apus (codigo, shift, nombre, unidad, grupo) "
                             "VALUES (%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                             (r["codigo"], r["shift"], r["nombre"], r["unidad"], r["grupo"]))
```
- apu_componentes:
```python
                conn.execute(
                    "INSERT INTO apus.apu_componentes (apu_codigo, shift, seq, insumo_codigo, "
                    "insumo_nombre, unidad, rendimiento, precio_unitario_hist) "
                    "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) ON CONFLICT DO NOTHING",
                    (r["apu_codigo"], r["shift"], r["seq"], r["insumo_codigo"],
                     r["insumo_nombre"], r["unidad"], r["rendimiento"], r["precio_unitario_hist"]))
```
(La docstring del módulo ya dice "Idempotente"; ahora es cierto. `_resync_identity` y los upserts de `meta` no cambian.)

- [ ] **Step 4: Run tests**

Run: `python -m pytest tests/test_migracion_pg.py -q` (local: skips; CI: corre contra Postgres). Full local: `python -m pytest tests/ -q` (sin regresiones).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/migracion_pg.py tests/test_migracion_pg.py
git commit -m "fix(migracion): migrate-pg idempotente con ON CONFLICT DO NOTHING (I6)"
```

---

### Task 5: I7 — subida sin Content-Length → 411

**Files:**
- Modify: `apu_tool/servicio/limites.py` (`LimiteSubida.dispatch`)
- Test: `tests/test_endurecimiento_subida.py` (añadir unit del middleware)

**Interfaces:** sin cambios de firma.

- [ ] **Step 1: Write the failing test**

En `tests/test_endurecimiento_subida.py`, añade (unit del dispatch, sin TestClient — que siempre pone Content-Length):

```python
import asyncio
from apu_tool.servicio.limites import LimiteSubida


class _Req:
    def __init__(self, headers, method="POST", path="/api/insumos/importar/preview"):
        self.headers = headers
        self.method = method
        self.url = type("U", (), {"path": path})()


def _dispatch(headers, method="POST", path="/api/insumos/importar/preview"):
    mw = LimiteSubida(app=None, max_bytes=15 * 1024 * 1024)
    async def call_next(_req):
        return "PASO"
    return asyncio.run(mw.dispatch(_Req(headers, method, path), call_next))


def test_post_sin_content_length_da_411():
    r = _dispatch({})   # POST a /api sin Content-Length
    assert getattr(r, "status_code", None) == 411


def test_get_sin_content_length_pasa():
    assert _dispatch({}, method="GET", path="/api/corridas") == "PASO"


def test_post_con_content_length_pasa():
    assert _dispatch({"content-length": "100"}) == "PASO"
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_endurecimiento_subida.py -q`
Expected: FAIL — sin CL hoy el middleware deja pasar (devuelve "PASO", no 411).

- [ ] **Step 3: Rechazar POST/PUT/PATCH a /api sin Content-Length**

En `apu_tool/servicio/limites.py`, reemplaza `LimiteSubida.dispatch`:

```python
    _METODOS_CON_CUERPO = ("POST", "PUT", "PATCH")

    async def dispatch(self, request, call_next):
        cl = request.headers.get("content-length")
        if cl is None:
            # Sin Content-Length en un método con cuerpo hacia /api: exigirlo (evita
            # cuerpos chunked/sin tope que se bufferizarían enteros → OOM).
            if request.method in self._METODOS_CON_CUERPO and request.url.path.startswith("/api"):
                return JSONResponse(status_code=411,
                                    content={"detail": "Falta la cabecera Content-Length."})
        else:
            try:
                if int(cl) > self.max_bytes:
                    return JSONResponse(status_code=413,
                                        content={"detail": "Archivo demasiado grande."})
            except ValueError:
                pass  # Content-Length no numérico: dejar seguir (lo valida el endpoint)
        return await call_next(request)
```

(`_METODOS_CON_CUERPO` como atributo de clase; el 413 existente se preserva.)

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_endurecimiento_subida.py tests/test_endurecimiento_headers.py tests/test_api_corridas.py tests/test_api_insumos.py -q`
Expected: PASS (los endpoints reales por TestClient siempre llevan CL → no afectados). Full: `python -m pytest tests/ -q`.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/limites.py tests/test_endurecimiento_subida.py
git commit -m "fix(endurecimiento): exigir Content-Length en subidas /api -> 411 (I7)"
```

---

### Task 6: M1 — /docs y /openapi desactivables en prod

**Files:**
- Modify: `apu_tool/config.py` (`docs_enabled`)
- Modify: `apu_tool/servicio/app.py` (`FastAPI(...)` condicional)
- Modify: `render.yaml` (`APU_DOCS_ENABLED=false`)
- Test: `tests/test_docs_toggle.py` (nuevo)

**Interfaces:**
- Produces: `config.docs_enabled() -> bool` (default True; False si `APU_DOCS_ENABLED` ∈ {false,0,no}).

- [ ] **Step 1: Write the failing test**

Crea `tests/test_docs_toggle.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from fastapi.testclient import TestClient


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return create_app(almacen=alm)


def test_docs_habilitados_por_defecto(tmp_path):
    assert TestClient(_app(tmp_path)).get("/openapi.json").status_code == 200


def test_docs_desactivados_en_prod(tmp_path, monkeypatch):
    monkeypatch.setenv("APU_DOCS_ENABLED", "false")
    assert TestClient(_app(tmp_path)).get("/openapi.json").status_code == 404
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_docs_toggle.py -q`
Expected: FAIL (`test_docs_desactivados_en_prod`: 200 en vez de 404).

- [ ] **Step 3: `config.docs_enabled()`**

En `apu_tool/config.py`, junto a los helpers de endurecimiento:

```python
def docs_enabled() -> bool:
    """Exponer /docs, /redoc y /openapi.json (default sí; desactivar en prod)."""
    return os.environ.get("APU_DOCS_ENABLED", "true").strip().lower() not in ("false", "0", "no")
```

- [ ] **Step 4: `create_app` condicional**

En `apu_tool/servicio/app.py`, reemplaza la construcción del app (línea 40):

```python
    _docs = config.docs_enabled()
    app = FastAPI(title="Armador de APUs", lifespan=lifespan,
                  docs_url="/docs" if _docs else None,
                  redoc_url="/redoc" if _docs else None,
                  openapi_url="/openapi.json" if _docs else None)
```

- [ ] **Step 5: `render.yaml`**

En `render.yaml`, dentro de `envVars`, añade:

```yaml
      - key: APU_DOCS_ENABLED
        value: "false"
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_docs_toggle.py tests/test_endurecimiento_headers.py -q`
Expected: PASS (headers usa `/openapi.json`, que sigue habilitado por defecto). Full: `python -m pytest tests/ -q`.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/config.py apu_tool/servicio/app.py render.yaml tests/test_docs_toggle.py
git commit -m "fix(endurecimiento): /docs y /openapi desactivables en prod (APU_DOCS_ENABLED) (M1)"
```

---

### Task 7: I3 — "Descargar cuadro" con Bearer (fetch → Blob)

**Files:**
- Modify: `web/src/api/corridas.ts` (`descargarCuadro`)
- Modify: `web/src/pages/Corrida.tsx` (usar `descargarCuadro`)
- Test: `web/src/api/corridas.descarga.test.ts` (nuevo)

**Interfaces:**
- Produces: `descargarCuadro(id: number): Promise<void>` — hace `fetch` con Bearer, recibe el Blob y dispara la descarga.

- [ ] **Step 1: Write the failing test**

Crea `web/src/api/corridas.descarga.test.ts`:

```ts
import { expect, test, vi, beforeEach } from "vitest";

vi.mock("@/api/client", () => ({
  authHeader: vi.fn(async () => ({ Authorization: "Bearer T" })),
  apiGet: vi.fn(), apiPost: vi.fn(), apiDelete: vi.fn(),
}));

beforeEach(() => { vi.restoreAllMocks(); });

test("descargarCuadro usa Bearer y dispara la descarga", async () => {
  const fetchMock = vi.fn(async () => ({
    status: 200, ok: true, blob: async () => new Blob(["x"]),
  })) as unknown as typeof fetch;
  vi.stubGlobal("fetch", fetchMock);
  vi.stubGlobal("URL", { createObjectURL: () => "blob:x", revokeObjectURL: () => {} });
  const click = vi.fn();
  vi.spyOn(document, "createElement").mockReturnValue({ click, remove: () => {}, href: "", download: "" } as unknown as HTMLAnchorElement);
  vi.spyOn(document.body, "appendChild").mockImplementation((n) => n as never);

  const { descargarCuadro } = await import("./corridas");
  await descargarCuadro(7);

  const [, init] = (fetchMock as unknown as ReturnType<typeof vi.fn>).mock.calls[0];
  expect((init.headers as Record<string, string>).Authorization).toBe("Bearer T");
  expect(click).toHaveBeenCalled();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (en `web/`): `npm test -- --run corridas.descarga`
Expected: FAIL (no existe `descargarCuadro`).

- [ ] **Step 3: Implementar `descargarCuadro`**

En `web/src/api/corridas.ts`, **reemplaza** `descargarCuadroUrl` por `descargarCuadro`:

```ts
/** Descarga el cuadro xlsx con el token Bearer (una navegación normal no lleva el header). */
export async function descargarCuadro(id: number): Promise<void> {
  const r = await fetch(`/api/corridas/${id}/cuadro`, { headers: { ...(await authHeader()) } });
  if (r.status === 401) {
    const { supabase } = await import("@/lib/supabase");
    await supabase.auth.signOut();
    throw new Error("Sesión expirada.");
  }
  if (!r.ok) {
    const err = await r.json().catch(() => ({}) as { detail?: string });
    throw new Error(err.detail || r.statusText);
  }
  const blob = await r.blob();
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = `cuadro_corrida_${id}.xlsx`;
  document.body.appendChild(a);
  a.click();
  a.remove();
  URL.revokeObjectURL(url);
}
```

- [ ] **Step 4: Usar `descargarCuadro` en `Corrida.tsx`**

En `web/src/pages/Corrida.tsx`: cambia el import `descargarCuadroUrl` → `descargarCuadro` (viene de `@/api/corridas`), asegura que `toast` de `sonner` esté importado, y reemplaza el botón (líneas 115-123):

```tsx
        {!live && (
          <Button
            size="sm"
            variant="outline"
            onClick={() =>
              descargarCuadro(corridaId).catch((e) =>
                toast.error(e instanceof Error ? e.message : "No se pudo descargar el cuadro."))
            }
          >
            Descargar cuadro
          </Button>
        )}
```

(Si `toast` no estaba importado en `Corrida.tsx`, añade `import { toast } from "sonner";`.)

- [ ] **Step 5: Run tests + build**

Run (en `web/`): `npm test -- --run` y `npm run build`
Expected: vitest verde (nuevo + 19 existentes) + build OK.

- [ ] **Step 6: Commit**

```bash
git add web/src/api/corridas.ts web/src/pages/Corrida.tsx web/src/api/corridas.descarga.test.ts
git commit -m "fix(web): descargar cuadro con Bearer (fetch+Blob) en vez de window.open -> 401 (I3)"
```

---

### Task 8: I4 — visor de auditoría agrupa por `lote_id` (Map)

**Files:**
- Modify: `web/src/pages/Auditoria.tsx` (agrupación)
- Test: `web/src/pages/Auditoria.test.tsx` (añadir caso de filas no contiguas)

**Interfaces:** sin cambios de API.

- [ ] **Step 1: Write the failing test**

Lee `web/src/pages/Auditoria.test.tsx` y añade un test con filas de un mismo `lote_id` **no contiguas** (intercaladas con otro evento), mockeando `@/api/auditoria`:

```ts
test("agrupa filas de un lote aunque estén intercaladas", async () => {
  const mod = await import("@/api/auditoria");
  vi.spyOn(mod, "listarAuditoria").mockResolvedValue({
    items: [
      { id: 3, ts: "2026-07-01T10:02:00Z", user_id: "u", user_email: "a@o.co", rol: "editor",
        accion: "insumo.crear", entidad_tipo: "insumo", entidad_id: "1",
        antes: null, despues: null, contexto: { origen: "import", lote_id: "L1" } },
      { id: 2, ts: "2026-07-01T10:01:00Z", user_id: "u2", user_email: "b@o.co", rol: "editor",
        accion: "precio.editar", entidad_tipo: "insumo", entidad_id: "9",
        antes: null, despues: null, contexto: { origen: "edicion", lote_id: "L2" } },
      { id: 1, ts: "2026-07-01T10:00:00Z", user_id: "u", user_email: "a@o.co", rol: "editor",
        accion: "insumo.crear", entidad_tipo: "insumo", entidad_id: "2",
        antes: null, despues: null, contexto: { origen: "import", lote_id: "L1" } },
    ],
    total: 3, limit: 200, offset: 0,
  });
  const { default: Auditoria } = await import("./Auditoria");
  render(<Auditoria />);
  // El lote L1 (2 filas no contiguas) aparece como UN grupo con su cabecera.
  await waitFor(() => expect(screen.getByText(/2 eventos/)).toBeTruthy());
  expect(screen.getByText("b@o.co")).toBeTruthy();   // el evento intercalado sigue visible
});
```

(Ajusta los campos al tipo `EventoAuditoria` real y el texto de la cabecera al que use el componente.)

- [ ] **Step 2: Run test to verify it fails**

Run (en `web/`): `npm test -- --run Auditoria`
Expected: FAIL — con la agrupación por orden de array, las filas no contiguas del lote se ocultan/orfanan.

- [ ] **Step 3: Agrupar por `lote_id` en un `Map`**

En `web/src/pages/Auditoria.tsx`, reemplaza la lógica de agrupación dependiente del orden del array (el `Set` `cabecerasEmitidas`/`cabecerasVistas` y el `filas.map` con `return null`) por una agrupación explícita: construir, con `useMemo`, una lista de "bloques" — cada bloque es o bien una fila suelta (sin `lote_id` o lote de tamaño 1) o un grupo `{loteId, filas[]}` (lote con ≥2 filas), preservando el orden de primera aparición:

```tsx
  type Bloque =
    | { tipo: "fila"; ev: EventoAuditoria }
    | { tipo: "lote"; loteId: string; filas: EventoAuditoria[] };

  const bloques = useMemo<Bloque[]>(() => {
    const porLote = new Map<string, EventoAuditoria[]>();
    for (const e of eventos) {
      const l = (e.contexto?.lote_id as string) || null;
      if (l) (porLote.get(l) ?? porLote.set(l, []).get(l)!).push(e);
    }
    const out: Bloque[] = [];
    const emitidos = new Set<string>();
    for (const e of eventos) {
      const l = (e.contexto?.lote_id as string) || null;
      const grupo = l ? porLote.get(l)! : null;
      if (grupo && grupo.length > 1) {
        if (!emitidos.has(l!)) { emitidos.add(l!); out.push({ tipo: "lote", loteId: l!, filas: grupo }); }
      } else {
        out.push({ tipo: "fila", ev: e });
      }
    }
    return out;
  }, [eventos]);
```

Luego el render itera `bloques`: un `{tipo:"fila"}` renderiza la fila; un `{tipo:"lote"}` renderiza la cabecera colapsable (usando `lotesAbiertos[loteId]`) y, si está abierto, `bloque.filas.map(...)`. Todas las filas del lote quedan juntas bajo su cabecera, sin depender del orden del array. Mantén el estilo denso/table-first actual y los estados/filtros existentes.

- [ ] **Step 4: Run tests + build**

Run (en `web/`): `npm test -- --run` y `npm run build`
Expected: vitest verde (nuevo + existentes) + build OK.

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Auditoria.tsx web/src/pages/Auditoria.test.tsx
git commit -m "fix(web): agrupar auditoría por lote_id en Map (filas no contiguas) (I4)"
```

---

### Task 9: M3 — flag `noAutorizado` no se pisa tras el signOut del 403

**Files:**
- Modify: `web/src/lib/auth.tsx`
- Test: `web/src/lib/auth.test.tsx` (añadir)

**Interfaces:** sin cambios de API.

- [ ] **Step 1: Write the failing test**

Lee `web/src/lib/auth.test.tsx` y añade un caso: sesión válida en Supabase pero `getYo` lanza (403) → tras el `signOut` que re-dispara el listener con sesión null, `noAutorizado` queda **true** (no se pisa). Mockea supabase `onAuthStateChange` para invocar el callback con una sesión y luego con null (simulando el signOut), y `getYo` que rechaza. Asegúrate de aserir que el estado final expone `noAutorizado === true` (via un componente de prueba que lo lea con `useAuth`, como en el patrón existente del archivo).

- [ ] **Step 2: Run test to verify it fails**

Run (en `web/`): `npm test -- --run auth`
Expected: FAIL — hoy el segundo evento (null) hace `setNoAutorizado(false)` y lo pisa.

- [ ] **Step 3: No re-poner `noAutorizado=false` tras el rechazo**

En `web/src/lib/auth.tsx`, usa un `useRef` para recordar el rechazo y no pisarlo. Añade `useRef` al import de `react` y reescribe el efecto:

```tsx
  const rechazado = useRef(false);

  useEffect(() => {
    const { data } = supabase.auth.onAuthStateChange(async (_evento, nuevaSesion) => {
      setSesion(nuevaSesion);
      if (nuevaSesion) {
        rechazado.current = false;
        setNoAutorizado(false);
        try {
          setPerfil(await getYo());
        } catch {
          // Autenticado en Supabase pero sin perfil / inactivo -> 403
          setPerfil(null);
          rechazado.current = true;
          setNoAutorizado(true);
          await supabase.auth.signOut();  // re-dispara este listener con sesión null
        }
      } else {
        setPerfil(null);
        setNoAutorizado(rechazado.current);  // preserva el "no autorizado" si venimos de un 403
      }
      setCargando(false);
    });
    return () => data.subscription.unsubscribe();
  }, []);
```

(Import: `import { createContext, useContext, useEffect, useRef, useState, type ReactNode } from "react";`.)

- [ ] **Step 4: Run tests + build**

Run (en `web/`): `npm test -- --run` y `npm run build`
Expected: vitest verde + build OK.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/auth.tsx web/src/lib/auth.test.tsx
git commit -m "fix(web): preservar noAutorizado tras el signOut del 403 (M3)"
```

---

### Task 10: M4 — borrar código muerto (`dominio/models.py`)

**Files:**
- Delete: `apu_tool/dominio/models.py` (duplicado obsoleto sin usar)
- Test: la suite completa (no debe romperse ningún import)

**Interfaces:** ninguno.

- [ ] **Step 1: Verificar que nadie lo importa**

Run: `python -c "import subprocess,sys; sys.exit(0)"` y una búsqueda: `grep -rn "dominio.models\|dominio import models\|from apu_tool.dominio.models" apu_tool tests` (o `Grep`). Expected: **cero** referencias (el módulo vivo es `apu_tool/nucleo/models.py`). Si hubiera alguna referencia, DETENERSE y reportar (no borrar).

- [ ] **Step 2: Borrar el módulo**

```bash
git rm apu_tool/dominio/models.py
```

- [ ] **Step 3: Run the full suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (255 passed/4 skipped) — ningún import roto. (`apu_tool/dominio/privacy.py` NO se toca: `_ALLOWED_NUMERIC_KEYS` se deja.)

- [ ] **Step 4: Commit**

```bash
git add apu_tool/dominio/models.py
git commit -m "chore: borrar apu_tool/dominio/models.py (duplicado obsoleto sin usar) (M4)"
```

(El `git rm` deja el borrado staged; `git add <ruta>` lo confirma.)

---

### Task 11: I8 + M2 + M5 + M6 + M7 — documentación

**Files:**
- Modify: `Dockerfile` (comentario junto a `--forwarded-allow-ips`)
- Modify: `README.md` (nota de topología/proxy + limiter per-worker)
- Modify: `apu_tool/servicio/limites.py` (comentario M2 — ya presente; verificar/ampliar)
- Modify: `apu_tool/datos/auditoria_db.py` (comentario M6)
- Modify: `apu_tool/servicio/usuarios.py` (comentario M7 en `invitar`)
- Modify: `db/pg/precios.sql` (comentario M5 sobre el CASCADE que SQLite no tiene)
- Test: ninguno (solo documentación/comentarios)

- [ ] **Step 1: I8 — Dockerfile + README (XFF / topología Render)**

En `Dockerfile`, junto a `--forwarded-allow-ips="*"`, añade un comentario:

```dockerfile
    # --forwarded-allow-ips="*": confiamos el X-Forwarded-For porque el ÚNICO ingreso
    # es el edge/proxy de Render. Si algún día el contenedor queda accesible directo
    # (VM/Docker -p sin proxy), restringir a los CIDR del proxy — con "*" el XFF es
    # spoofeable y se podría evadir el rate-limit.
```

En `README.md` (sección de despliegue), añade una nota equivalente sobre la dependencia de topología, **y** una nota M2: el rate-limit es in-memory por worker → con `WEB_CONCURRENCY=N` el límite efectivo es ×N (mitigación de abuso, no cuota exacta; para cuota global usar storage compartido).

- [ ] **Step 2: M6 — comentario en `auditoria_db.py`**

En `apu_tool/datos/auditoria_db.py`, junto al `INSERT INTO auditoria` (método `registrar`), añade:

```python
        # `auditoria` sin calificar: resuelve a seguridad.db (única base con esa tabla),
        # incluso cuando la UdT ATTACHea seguridad a otra base. Depende de que NINGUNA
        # tabla de dominio se llame `auditoria`.
```

- [ ] **Step 3: M7 — comentario en `usuarios.invitar`**

En `apu_tool/servicio/usuarios.py::invitar`, junto a `user_id = admin.invitar(email)`, añade:

```python
    # Efecto externo NO transaccional: si el upsert local + auditoría fallan después,
    # queda un usuario en Supabase Auth sin perfil local (idempotente al re-invitar).
```

- [ ] **Step 4: M5 — comentario en `db/pg/precios.sql`**

En `db/pg/precios.sql`, junto al FK `insumo_precios.insumo_id ... ON DELETE CASCADE`, añade un comentario:

```sql
    -- NOTA (drift vs SQLite): db/precios.sql no tiene ON DELETE CASCADE. Hoy inocuo
    -- (nadie borra insumos); reconciliar ambos esquemas si se añade borrado de insumos.
```

- [ ] **Step 5: M2 — verificar el comentario en `limites.py`**

`apu_tool/servicio/limites.py` ya tiene la nota del limiter per-worker (líneas 15-16). Verifícala; amplíala solo si hace falta. (Sin cambio de código.)

- [ ] **Step 6: Run the full suite (sin regresiones)**

Run: `python -m pytest tests/ -q`
Expected: PASS (solo comentarios/docs; nada de lógica cambió).

- [ ] **Step 7: Commit**

```bash
git add Dockerfile README.md apu_tool/datos/auditoria_db.py apu_tool/servicio/usuarios.py db/pg/precios.sql apu_tool/servicio/limites.py
git commit -m "docs(auditoría): documentar XFF/Render (I8), limiter per-worker (M2), FK drift (M5), footgun auditoria (M6), ventana invitar (M7)"
```

---

## Notas de cierre (para el revisor final)

- **Suite:** `python -m pytest tests/ -q` (255 previos + nuevos verdes) y, en `web/`, `npm test -- --run` + `npm run build`.
- **Invariante #1:** verificar que NO se tocaron `apu_tool/dominio/privacy.py`, `ai_assist.py`, ni `DePriced*` (M4 solo borra `dominio/models.py`; `privacy.py` intacto).
- **Postgres real:** I1, I5-insumos, I6 se validan en CI (`postgres:17`). El guard de I1 y la búsqueda de I5 son un solo SQL idéntico en ambos backends.
- **I5-APUs diferido:** la búsqueda de APUs por nombre sigue LIKE/ILIKE (documentado); paridad total requeriría `apus.nombre_norm` (mejora futura).
- **I7:** exige Content-Length en POST/PUT/PATCH a `/api`; los clientes normales (y TestClient) siempre lo envían.
