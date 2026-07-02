# Fix Auditoría — 3 Critical — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Arreglar los 3 fallos Critical de la auditoría (`status`/`db check` crashean en Postgres; `supabase/migrations/` no crea `seguridad.perfiles` antes del RLS) extendiendo el `Protocol` con métodos backend-agnósticos y reconciliando las migraciones.

**Architecture:** Las 3 roturas son asunciones de SQLite que se colaron por encima de la frontera del `Protocol`. Se añaden métodos backend-agnósticos a `apu_tool/datos/repositorio.py` implementados en ambos backends, y se reorganiza `supabase/migrations/` para que sea consistente. Sin `isinstance`/`hasattr`.

**Tech Stack:** Python, FastAPI, psycopg v3, SQLite, pytest, SQL (Postgres/Supabase migrations).

## Global Constraints

- **Invariante #1:** NO tocar `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py`, ni las vistas `DePriced*`.
- **Cero regresiones:** 249 tests backend + 19 vitest verdes; AÑADIR tests que reproduzcan cada bug (TDD).
- **Postgres se valida en CI** (contenedor `postgres:17` + `TEST_DATABASE_URL`); local hace `skip` — el patrón está en `tests/test_repositorios_contrato.py` (fixture `repos` parametrizada sqlite/postgres).
- **Español** en comentarios y mensajes. El **frontend NO se toca** en este plan.
- **DISCIPLINA DE COMMIT:** `git add` SOLO los archivos de cada tarea por ruta explícita. NUNCA `-A`/`.`/`-u`. El `git mv`/`git rm` de migraciones es explícito. Cruft ignorado (`node_modules`, `.env`); `ejemplos/licitacion_ejemplo.xlsx` modificado está **FUERA DE ALCANCE** — nunca incluirlo.
- **Comando de prueba:** `python -m pytest tests/ -q` (desde la raíz).
- **Alcance:** solo C1/C2/C3. Los Important+Minor van en el Plan B.

---

### Task 1: C1 — `descripcion()` backend-agnóstico para `status`

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (firmas en `RepositorioPrecios` y `RepositorioApus`)
- Modify: `apu_tool/datos/precios_db.py` (`PreciosDB.descripcion`)
- Modify: `apu_tool/datos/apus_db.py` (`ApusDB.descripcion`)
- Modify: `apu_tool/datos/pg/precios_pg.py` (`PreciosPg.descripcion`)
- Modify: `apu_tool/datos/pg/apus_pg.py` (`ApusPg.descripcion`)
- Modify: `apu_tool/interfaz/cli.py` (`cmd_status`, líneas 65-66)
- Test: `tests/test_repositorios_contrato.py` (añadir), `tests/test_cli_status.py` (nuevo)

**Interfaces:**
- Produces: `RepositorioPrecios.descripcion() -> str`, `RepositorioApus.descripcion() -> str`. SQLite: `f"SQLite: {self.path}"`. Postgres: `"Postgres (schema precios)"` / `"Postgres (schema apus)"`.

- [ ] **Step 1: Write the failing tests**

En `tests/test_repositorios_contrato.py`, añade al final (usa la fixture `repos` existente):

```python
def test_descripcion_no_vacia(repos):
    precios, apus = repos
    dp, da = precios.descripcion(), apus.descripcion()
    assert isinstance(dp, str) and dp.strip()
    assert isinstance(da, str) and da.strip()
```

Crea `tests/test_cli_status.py`:

```python
import argparse

from apu_tool.datos.almacen import Almacen
from apu_tool.interfaz import cli


def test_cmd_status_no_crashea(tmp_path, monkeypatch, capsys):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    monkeypatch.setattr(cli, "get_almacen", lambda: alm)
    assert cli.cmd_status(argparse.Namespace()) == 0
    salida = capsys.readouterr().out
    assert "Insumos:" in salida   # el reporte se imprimió sin AttributeError
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_repositorios_contrato.py::test_descripcion_no_vacia tests/test_cli_status.py -q`
Expected: FAIL — `AttributeError: 'PreciosDB' object has no attribute 'descripcion'` (contrato) y, tras implementar el método pero antes de tocar cli, el smoke seguiría fallando si `cmd_status` usa `.path`. (Con `descripcion` aún inexistente, ambos fallan.)

- [ ] **Step 3: Añadir las firmas al Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioPrecios` (junto a las otras firmas):

```python
    def descripcion(self) -> str:
        """Identidad legible del backend (para `status`), agnóstica de SQLite/Postgres."""
        ...
```

Y lo mismo dentro de `RepositorioApus`:

```python
    def descripcion(self) -> str:
        """Identidad legible del backend (para `status`), agnóstica de SQLite/Postgres."""
        ...
```

- [ ] **Step 4: Implementar en los 4 repos**

En `apu_tool/datos/precios_db.py` (clase `PreciosDB`, junto a otros métodos):

```python
    def descripcion(self) -> str:
        return f"SQLite: {self.path}"
```

En `apu_tool/datos/apus_db.py` (clase `ApusDB`):

```python
    def descripcion(self) -> str:
        return f"SQLite: {self.path}"
```

En `apu_tool/datos/pg/precios_pg.py` (clase `PreciosPg`):

```python
    def descripcion(self) -> str:
        return "Postgres (schema precios)"
```

En `apu_tool/datos/pg/apus_pg.py` (clase `ApusPg`):

```python
    def descripcion(self) -> str:
        return "Postgres (schema apus)"
```

- [ ] **Step 5: Usar `descripcion()` en `cmd_status`**

En `apu_tool/interfaz/cli.py`, reemplaza las líneas 65-66:

```python
    print(f"Base de precios: {alm.precios.path}")
    print(f"Base de APUs:    {alm.apus.path}")
```

por:

```python
    print(f"Base de precios: {alm.precios.descripcion()}")
    print(f"Base de APUs:    {alm.apus.descripcion()}")
```

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_cli_status.py -q`
Expected: PASS. Luego la suite completa: `python -m pytest tests/ -q` (sin regresiones).

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/precios_db.py apu_tool/datos/apus_db.py apu_tool/datos/pg/precios_pg.py apu_tool/datos/pg/apus_pg.py apu_tool/interfaz/cli.py tests/test_repositorios_contrato.py tests/test_cli_status.py
git commit -m "fix(cli): status backend-agnóstico via descripcion() en el Protocol (C1)"
```

---

### Task 2: C2 — integridad por el Protocol (`componentes_para_integridad()`)

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (firma en `RepositorioApus`)
- Modify: `apu_tool/datos/apus_db.py` (`ApusDB.componentes_para_integridad`)
- Modify: `apu_tool/datos/pg/apus_pg.py` (`ApusPg.componentes_para_integridad`)
- Modify: `apu_tool/dominio/integridad.py` (`revisar`, líneas 20-24 + el bucle)
- Test: `tests/test_repositorios_contrato.py` (añadir), `tests/test_integridad.py` (añadir)

**Interfaces:**
- Consumes: nada nuevo.
- Produces: `RepositorioApus.componentes_para_integridad() -> list[tuple[str, str]]` — `(insumo_codigo, insumo_nombre)` de cada componente con `insumo_codigo` no vacío.

- [ ] **Step 1: Write the failing tests**

En `tests/test_repositorios_contrato.py`, añade (usa la fixture `repos`):

```python
def test_componentes_para_integridad(repos):
    _, apus = repos
    from apu_tool.nucleo.models import Apu, ApuComponent
    apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MOV"), [
        ApuComponent("A1", "DIURNO", "1", "6140", "ACERO", "KG", 0.5, 10.0),
        ApuComponent("A1", "DIURNO", "2", "9", "CEMENTO", "KG", 1.2, 20.0)])
    comps = apus.componentes_para_integridad()
    assert ("6140", "ACERO") in comps and ("9", "CEMENTO") in comps
    assert all(isinstance(c, tuple) and len(c) == 2 for c in comps)
```

En `tests/test_integridad.py`, añade (crea el archivo si no existe; si existe, añade la función):

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.dominio import integridad


def test_revisar_corre_sin_crash(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("6140", "ACERO", "KG", "MAT", 3500.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "EXCAVACION", "M3", "DIURNO", "MOV"), [
        ApuComponent("A1", "DIURNO", "1", "6140", "ACERO", "KG", 0.5, 10.0)])
    rep = integridad.revisar(alm)
    assert set(rep) >= {"huerfanos", "aproximados", "ambiguos", "detalles"}
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_repositorios_contrato.py::test_componentes_para_integridad tests/test_integridad.py::test_revisar_corre_sin_crash -q`
Expected: FAIL — `AttributeError: 'ApusDB' object has no attribute 'componentes_para_integridad'`.

- [ ] **Step 3: Añadir la firma al Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioApus`:

```python
    def componentes_para_integridad(self) -> list[tuple[str, str]]:
        """(insumo_codigo, insumo_nombre) de cada componente con código no vacío.
        Para el chequeo de integridad APU→insumo, sin SQL crudo en el dominio."""
        ...
```

- [ ] **Step 4: Implementar en ambos backends**

En `apu_tool/datos/apus_db.py` (clase `ApusDB`):

```python
    def componentes_para_integridad(self) -> list[tuple[str, str]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT insumo_codigo, insumo_nombre FROM apu_componentes "
                "WHERE insumo_codigo IS NOT NULL AND insumo_codigo <> ''").fetchall()
        return [(r["insumo_codigo"], r["insumo_nombre"]) for r in rows]
```

En `apu_tool/datos/pg/apus_pg.py` (clase `ApusPg`):

```python
    def componentes_para_integridad(self) -> list[tuple[str, str]]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT insumo_codigo, insumo_nombre FROM apus.apu_componentes "
                "WHERE insumo_codigo IS NOT NULL AND insumo_codigo <> ''").fetchall()
        return [(r["insumo_codigo"], r["insumo_nombre"]) for r in rows]
```

- [ ] **Step 5: Usar el método en `integridad.revisar`**

En `apu_tool/dominio/integridad.py`, reemplaza el bloque de las líneas 20-24 (el `with almacen.apus.connect() ...` y su SQL) y el bucle. El cuerpo de `revisar` queda:

```python
def revisar(almacen: Almacen) -> dict:
    """Devuelve {'huerfanos', 'aproximados', 'ambiguos', 'detalles': [...]}."""
    huerfanos = aproximados = ambiguos = 0
    detalles: dict[tuple, dict] = {}
    for cod, nom in almacen.apus.componentes_para_integridad():
        res = cruce.resolver(almacen.precios.get_candidatos(cod), nom)
        if res.calidad == cruce.CalidadCruce.HUERFANO:
            huerfanos += 1
        elif res.calidad == cruce.CalidadCruce.AMBIGUO:
            ambiguos += 1
            _acumular(detalles, cod, nom, "ambiguo")
        elif res.calidad == cruce.CalidadCruce.APROXIMADO:
            aproximados += 1
            _acumular(detalles, cod, nom, "aproximado",
                      cat_nom=res.insumo.nombre if res.insumo else "")
    return {"huerfanos": huerfanos, "aproximados": aproximados,
            "ambiguos": ambiguos, "detalles": list(detalles.values())}
```

(No cambies `_acumular`.)

- [ ] **Step 6: Run tests to verify they pass**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_integridad.py -q`
Expected: PASS. Luego la suite completa: `python -m pytest tests/ -q` (sin regresiones).

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py apu_tool/dominio/integridad.py tests/test_repositorios_contrato.py tests/test_integridad.py
git commit -m "fix(integridad): db check por el Protocol (componentes_para_integridad), sin SQL crudo (C2)"
```

---

### Task 3: C3 — reconciliar migraciones Supabase + `migrate-pg` + README

**Files:**
- Create: `supabase/migrations/0002_seguridad.sql`
- Rename+Modify: `supabase/migrations/0002_rls.sql` → `supabase/migrations/0003_rls.sql` (añade RLS de auditoria)
- Delete: `supabase/migrations/0003_auditoria.sql` (su tabla se movió a `0002_seguridad.sql`)
- Modify: `apu_tool/interfaz/cli.py` (constante `ESQUEMAS_PG` + `cmd_migrate_pg`)
- Modify: `README.md` (sección de despliegue)
- Test: `tests/test_migraciones_supabase.py` (nuevo)

**Interfaces:**
- Produces: `apu_tool.interfaz.cli.ESQUEMAS_PG: tuple[str, ...]` = `("precios.sql", "apus.sql", "corridas.sql", "seguridad.sql")`.

- [ ] **Step 1: Write the failing test**

Crea `tests/test_migraciones_supabase.py`:

```python
import re
from pathlib import Path

from apu_tool import config
from apu_tool.interfaz.cli import ESQUEMAS_PG

MIGR = config.PROJECT_ROOT / "supabase" / "migrations"


def test_migrate_pg_aplica_seguridad():
    assert "seguridad.sql" in ESQUEMAS_PG


def test_migraciones_crean_perfiles_antes_del_rls():
    archivos = sorted(p.name for p in MIGR.glob("*.sql"))
    assert "0002_seguridad.sql" in archivos
    assert "0003_auditoria.sql" not in archivos          # su tabla se movió a 0002_seguridad
    crea = next(n for n in archivos
                if re.search(r"create table[^;]*perfiles",
                             (MIGR / n).read_text("utf-8"), re.I | re.S))
    rls = next(n for n in archivos
               if re.search(r"alter table\s+seguridad\.perfiles[^;]*row level security",
                            (MIGR / n).read_text("utf-8"), re.I | re.S))
    assert crea <= rls   # perfiles se crea en un archivo anterior (o igual) al que le aplica RLS
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_migraciones_supabase.py -q`
Expected: FAIL — `ImportError: cannot import name 'ESQUEMAS_PG'` (aún no existe) y, tras crearla, `0002_seguridad.sql` no existe / `0003_auditoria.sql` sí → el segundo test falla.

- [ ] **Step 3: Crear `supabase/migrations/0002_seguridad.sql`**

Contenido (idéntico a `db/pg/seguridad.sql`, crea perfiles+auditoria ANTES del RLS):

```sql
-- Schema de seguridad: perfiles (RBAC) + auditoría. DEBE crearse antes del RLS (0003_rls.sql).
CREATE SCHEMA IF NOT EXISTS seguridad;
CREATE TABLE IF NOT EXISTS seguridad.perfiles (
    user_id   TEXT PRIMARY KEY,
    email     TEXT NOT NULL,
    rol       TEXT NOT NULL CHECK (rol IN ('admin','editor','consulta')),
    estado    TEXT NOT NULL CHECK (estado IN ('activo','inactivo')),
    nombre    TEXT,
    creado_en TEXT
);

CREATE TABLE IF NOT EXISTS seguridad.auditoria (
    id           BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    ts           TEXT NOT NULL,
    user_id      TEXT,
    user_email   TEXT,
    rol          TEXT NOT NULL,
    accion       TEXT NOT NULL,
    entidad_tipo TEXT NOT NULL,
    entidad_id   TEXT,
    antes        JSONB,
    despues      JSONB,
    contexto     JSONB
);
CREATE INDEX IF NOT EXISTS idx_auditoria_ts ON seguridad.auditoria(ts);
CREATE INDEX IF NOT EXISTS idx_auditoria_entidad ON seguridad.auditoria(entidad_tipo, entidad_id);
CREATE INDEX IF NOT EXISTS idx_auditoria_user ON seguridad.auditoria(user_id);
```

- [ ] **Step 4: Renombrar la migración RLS y extenderla**

```bash
git mv supabase/migrations/0002_rls.sql supabase/migrations/0003_rls.sql
```

Reemplaza el contenido de `supabase/migrations/0003_rls.sql` para incluir `seguridad.auditoria` (11 tablas):

```sql
-- Defensa en profundidad: habilitar RLS SIN policies en todas las tablas.
-- Bloquea anon/authenticated; la service_role (FastAPI) hace bypass de RLS.
-- Requiere que seguridad.perfiles y seguridad.auditoria existan (0002_seguridad.sql).
ALTER TABLE precios.insumos            ENABLE ROW LEVEL SECURITY;
ALTER TABLE precios.insumo_precios     ENABLE ROW LEVEL SECURITY;
ALTER TABLE precios.meta               ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.apus                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.apu_componentes       ENABLE ROW LEVEL SECURITY;
ALTER TABLE apus.meta                  ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.corrida           ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.corrida_item      ENABLE ROW LEVEL SECURITY;
ALTER TABLE seguridad.perfiles         ENABLE ROW LEVEL SECURITY;
ALTER TABLE seguridad.auditoria        ENABLE ROW LEVEL SECURITY;
```

- [ ] **Step 5: Eliminar la migración de auditoría (movida a 0002_seguridad)**

```bash
git rm supabase/migrations/0003_auditoria.sql
```

- [ ] **Step 6: Añadir `ESQUEMAS_PG` y usarla en `cmd_migrate_pg`**

En `apu_tool/interfaz/cli.py`, añade una constante de módulo (cerca del inicio, tras los imports):

```python
# Esquemas Postgres aplicados por `migrate-pg`, en orden de dependencia.
ESQUEMAS_PG = ("precios.sql", "apus.sql", "corridas.sql", "seguridad.sql")
```

En `cmd_migrate_pg`, reemplaza la línea 191:

```python
            for f in ("precios.sql", "apus.sql", "corridas.sql"):
```

por:

```python
            for f in ESQUEMAS_PG:
```

- [ ] **Step 7: Corregir el README**

En `README.md`, en la sección "Despliegue (Render + Docker)", reemplaza la línea que afirma que el esquema ya está aplicado:

```markdown
- **Migración del catálogo (una vez, ops):** con `DATABASE_URL` de Supabase, correr
  `python run_cli.py migrate-pg` y verificar conteos (insumos/precios/APUs/componentes) SQLite vs
  Postgres. El esquema Postgres (`db/pg/*.sql` + auditoría) ya está aplicado.
```

por:

```markdown
- **Migración del catálogo (una vez, ops):** con `DATABASE_URL` de Supabase, correr
  `python run_cli.py migrate-pg` y verificar conteos (insumos/precios/APUs/componentes) SQLite vs
  Postgres. `migrate-pg` aplica los esquemas `db/pg/*.sql` (precios/apus/corridas/seguridad) antes de
  migrar; el arranque de la app también los autoprovisiona vía `init_schema`. La carpeta
  `supabase/migrations/` (fuente para `supabase db push`) es consistente: `0002_seguridad.sql` crea
  `seguridad.perfiles`/`auditoria` antes de que `0003_rls.sql` les aplique RLS.
```

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_migraciones_supabase.py -q`
Expected: PASS (2 passed). Luego la suite completa: `python -m pytest tests/ -q` (sin regresiones).

- [ ] **Step 9: Commit**

```bash
git add supabase/migrations/0002_seguridad.sql supabase/migrations/0003_rls.sql supabase/migrations/0003_auditoria.sql apu_tool/interfaz/cli.py README.md tests/test_migraciones_supabase.py
git commit -m "fix(migraciones): perfiles antes del RLS + migrate-pg aplica seguridad.sql + README veraz (C3)"
```

(El `git rm` de `0003_auditoria.sql` ya lo dejó staged como borrado; incluirlo por ruta explícita en el `git add` registra la eliminación.)

---

## Notas de cierre (para el revisor final)

- **Suite:** `python -m pytest tests/ -q` (249 previos + los nuevos, todos verdes). El frontend no se toca.
- **Invariante #1:** verificar que NO se tocaron `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py` ni las vistas `DePriced*`.
- **Validación Postgres real:** ocurre en CI (el job `postgres:17` corre los contratos duales de C1/C2 y `migrate-pg` completo con `seguridad.sql`). Local solo cubre SQLite.
- **Sin `isinstance`/`hasattr`:** confirmar que los fixes de C1/C2 son métodos del Protocol implementados en ambos backends, no ramas por tipo.
- **C3 vs I6:** este plan solo hace que `migrate-pg` **aplique** `seguridad.sql`; la idempotencia de los INSERT de datos de `migrate-pg` (I6) es del Plan B — no se toca aquí.
- **Reorg de migraciones:** el historial Supabase está vacío y el DDL es idempotente (`IF NOT EXISTS`, `ENABLE RLS` re-aplicable), así que re-aplicar el set reorganizado contra "BASE APUS" es seguro.
