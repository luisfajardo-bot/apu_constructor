> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-09-08-armado-reanudable.md`

# Armado reanudable — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sacar el armado de la petición HTTP y convertirlo en un trabajo del servidor que sobrevive a los reinicios de la instancia, retomando solo donde quedó.

**Architecture:** Un hilo en el proceso web consume una cola que vive en la base: una corrida en `estado='armando'` **es** un trabajo pendiente. Al crearla se guardan las líneas ya interpretadas del Excel en `corrida.plan_json`, que es la única fuente de qué falta armar. El worker reclama la corrida más vieja con un `UPDATE ... WHERE` atómico (que cierra la ventana de doble armado durante un deploy), arma desde `max(seq)+1`, y late para no perder la reclama.

**Tech Stack:** Python 3.14, FastAPI, `threading` (stdlib), SQLite + Postgres (psycopg/psycopg_pool), React + Vite + Vitest, pytest.

**Spec:** `docs/superpowers/specs/2026-09-07-armado-reanudable-design.md`

**Rama:** `feat/armado-reanudable` (dos commits de spec sobre `master`).

---

## Estructura de archivos

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `db/corridas.sql` | esquema SQLite: columnas nuevas + índice único | modificar |
| `db/pg/corridas.sql` | espejo Postgres, con su bloque de migración idempotente | modificar |
| `apu_tool/nucleo/models.py` | `CorridaMeta` suma los campos del armado | modificar |
| `apu_tool/datos/repositorio.py` | contrato: 8 métodos nuevos en `RepositorioCorridas` | modificar |
| `apu_tool/datos/corridas_db.py` | implementación SQLite | modificar |
| `apu_tool/datos/pg/corridas_pg.py` | implementación Postgres (espejo 1:1) | modificar |
| `apu_tool/dominio/privacy.py` | `plan_json` a `_FORBIDDEN_KEYS` | modificar |
| `apu_tool/config.py` | los 4 números del worker | modificar |
| `apu_tool/servicio/corridas.py` | `armar_pendientes`, guarda de borrado, vista con progreso | modificar |
| **`apu_tool/servicio/armador.py`** | **el worker: bucle, reclama, latido, reintentos** | **crear** |
| `apu_tool/servicio/app.py` | arranca y para el worker en el `lifespan` | modificar |
| `apu_tool/servicio/rutas.py` | encolar en vez de armar; borrar el SSE; `/reanudar` | modificar |
| `web/src/lib/armado.tsx` | queda sin razón de ser | **borrar** |
| `web/src/pages/Corrida.tsx` | progreso desde el poll, `armado_detenido`, poll a 5 s | modificar |
| `web/src/pages/CorridasInicio.tsx` | crear y navegar sin esperar | modificar |
| `web/src/api/corridas.ts` | `crearCorrida`, `crearSample`, `reanudarArmado`; fuera los `*Stream` | modificar |
| `web/src/lib/tipos.ts` | el bloque `armado` en `CorridaDetalle` | modificar |

**Por qué `armador.py` es un archivo nuevo y no más código en `corridas.py`:** `servicio/corridas.py` ya tiene ~870 líneas y mezcla vista, costeo, confirmación y candados. El worker es una responsabilidad distinta (ciclo de vida de un hilo) y necesita testearse sin montar la app. Separarlo también es lo que hace que mudar a un Background Worker de Render sea un cambio de una línea.

---

## Tarea 1: Columnas nuevas del armado

**Files:**
- Modify: `db/corridas.sql`
- Modify: `db/pg/corridas.sql`
- Modify: `apu_tool/nucleo/models.py:259-273`
- Modify: `apu_tool/datos/corridas_db.py:46-80` (`init_schema`), `:252-261` (`_row_to_meta`), `:268-272` (`listar_corridas`)
- Modify: `apu_tool/datos/pg/corridas_pg.py:185` (`_row_to_meta`)
- Test: `tests/test_corridas_contrato.py`

- [ ] **Step 1: Write the failing test**

En `tests/test_corridas_contrato.py`, agregar al final:

```python
def test_corrida_nace_con_los_campos_del_armado_en_cero(repo):
    """Los campos del armado tienen default seguro: una corrida vieja (o recién
    creada) no está reclamada por nadie y no acumuló intentos."""
    cid = repo.crear_corrida(_meta())
    m = repo.get_corrida(cid)
    assert m.intentos == 0
    assert m.ultimo_error is None
    assert m.armando_por is None
    assert m.armando_desde is None
```

Si `_meta()` no existe en ese archivo, usar el helper que ya use para crear corridas (revisar el principio del archivo y reusarlo; **no** definir uno nuevo).

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_contrato.py -k armado_en_cero -q`
Expected: FAIL con `AttributeError: 'CorridaMeta' object has no attribute 'intentos'`

- [ ] **Step 3: Agregar los campos a `CorridaMeta`**

En `apu_tool/nucleo/models.py`, dentro de `class CorridaMeta`, después de `lista_precios_id`:

```python
    # --- armado como trabajo del servidor (ver docs/superpowers/specs/2026-09-07-armado-reanudable-design.md) ---
    # `estado='armando'` ES la cola: nadie saca una corrida de ahí salvo el worker al
    # terminarla o `reencolar_armado`. Un set_estado sin guarda la borra de la cola.
    intentos: int = 0                      # +1 por cada reclama; al pasar el tope -> 'armado_detenido'
    ultimo_error: Optional[str] = None     # por qué se detuvo, en español, para la pantalla
    armando_por: Optional[str] = None      # id de la instancia que la reclamó
    armando_desde: Optional[str] = None    # ISO 8601 del último latido de esa reclama
```

**`plan_json` NO va acá, a propósito:** son ~400 KB por corrida grande y `CorridaMeta` viaja en `listar_corridas`. Se lee aparte con `get_plan` (Tarea 2).

- [ ] **Step 4: Migración SQLite**

En `db/corridas.sql`, dentro de `CREATE TABLE IF NOT EXISTS corrida (...)`, antes del cierre:

```sql
  -- Las líneas ya interpretadas del Excel, en orden. Única fuente de qué falta armar:
  -- el archivo subido no se guarda. Lleva precio_contractual (dinero) -> la clave
  -- `plan_json` está en privacy._FORBIDDEN_KEYS.
  plan_json     TEXT,
  intentos      INTEGER NOT NULL DEFAULT 0,
  ultimo_error  TEXT,
  armando_por   TEXT,
  armando_desde TEXT
```

En `apu_tool/datos/corridas_db.py`, dentro de `init_schema`, después del bloque de `lista_precios_id` (línea 60) y **antes** del `UPDATE corrida SET nombre = archivo`:

```python
            if "plan_json" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN plan_json TEXT")
            if "intentos" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN intentos INTEGER NOT NULL DEFAULT 0")
            if "ultimo_error" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN ultimo_error TEXT")
            if "armando_por" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN armando_por TEXT")
            if "armando_desde" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN armando_desde TEXT")
```

- [ ] **Step 5: Migración Postgres**

En `db/pg/corridas.sql`, dentro de `CREATE TABLE IF NOT EXISTS corridas.corrida (...)`, antes del cierre:

```sql
    plan_json     TEXT,
    intentos      INTEGER NOT NULL DEFAULT 0,
    ultimo_error  TEXT,
    armando_por   TEXT,
    armando_desde TEXT
```

Y en el bloque `-- Migración idempotente para bases existentes.`, después de la línea de `lista_precios_id`:

```sql
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS plan_json TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS intentos INTEGER NOT NULL DEFAULT 0;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS ultimo_error TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS armando_por TEXT;
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS armando_desde TEXT;
```

- [ ] **Step 6: Mapear los campos al leer, en los dos backends**

En `apu_tool/datos/corridas_db.py`, en `_row_to_meta`, agregar al final del constructor (usando el mismo patrón defensivo `in r.keys()` que ya usan `carpeta_id` y `nombre`, porque `reset()` recrea el esquema y hay tests con tablas viejas):

```python
            intentos=(r["intentos"] if "intentos" in r.keys() else 0) or 0,
            ultimo_error=(r["ultimo_error"] if "ultimo_error" in r.keys() else None),
            armando_por=(r["armando_por"] if "armando_por" in r.keys() else None),
            armando_desde=(r["armando_desde"] if "armando_desde" in r.keys() else None))
```

(la línea de `lista_precios_id` pierde su `)` final, que pasa a la última línea nueva).

En `apu_tool/datos/pg/corridas_pg.py`, en `_row_to_meta`, agregar los mismos cuatro campos leyendo del dict de la fila con el estilo que ya use ese método.

- [ ] **Step 7: `listar_corridas` deja de traer `plan_json`**

En `apu_tool/datos/corridas_db.py`, reemplazar el `SELECT *` de `listar_corridas`:

```python
    # Columnas explícitas y NO `SELECT *`: `plan_json` pesa ~400 KB en una corrida de
    # 1900 ítems y este listado trae TODAS las corridas. Con `*`, abrir "Mis corridas"
    # arrastraría decenas de MB que nadie mira.
    _COLS_META = ("id, creada_en, archivo, turno_def, use_ai, estado, cuadro_path, "
                  "duracion_ms, modo, carpeta_id, nombre, lista_precios_id, "
                  "intentos, ultimo_error, armando_por, armando_desde")

    def listar_corridas(self) -> list[CorridaMeta]:
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT {self._COLS_META} FROM corrida "
                "ORDER BY creada_en DESC, id DESC").fetchall()
        return [self._row_to_meta(r) for r in rows]
```

Hacer el equivalente en `apu_tool/datos/pg/corridas_pg.py` (mismo listado de columnas, con el prefijo `corridas.corrida`).

- [ ] **Step 8: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: PASS (todos)

- [ ] **Step 9: Suite completa, para confirmar que la migración no rompió nada**

Run: `python -m pytest tests/ -q`
Expected: PASS, sin fallos nuevos

- [ ] **Step 10: Commit**

```bash
git add db/corridas.sql db/pg/corridas.sql apu_tool/nucleo/models.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_contrato.py
git commit -m "feat(datos): columnas del armado como trabajo del servidor

plan_json guarda las lineas ya interpretadas (el Excel subido no se guarda y
sin eso no hay forma de saber que falta armar). intentos/ultimo_error cortan
el bucle de reintentos; armando_por/armando_desde son la reclama que cierra
la ventana de doble armado durante un deploy.

listar_corridas deja de usar SELECT *: plan_json pesa ~400 KB por corrida
grande y ese listado las trae todas."
```

---

## Tarea 2: Guardar y leer el plan, y saber dónde quedó

**Files:**
- Modify: `apu_tool/datos/repositorio.py:160-212` (`RepositorioCorridas`)
- Modify: `apu_tool/datos/corridas_db.py`
- Modify: `apu_tool/datos/pg/corridas_pg.py`
- Test: `tests/test_corridas_contrato.py`

- [ ] **Step 1: Write the failing test**

```python
def test_plan_se_guarda_y_se_lee_igual(repo):
    cid = repo.crear_corrida(_meta())
    assert repo.get_plan(cid) is None          # sin plan todavía
    repo.set_plan(cid, '[{"descripcion": "EXCAVACION"}]')
    assert repo.get_plan(cid) == '[{"descripcion": "EXCAVACION"}]'


def test_max_seq_dice_donde_reanudar(repo):
    """-1 con la corrida vacía, para que `max_seq + 1` dé 0 y arranque del principio."""
    cid = repo.crear_corrida(_meta())
    assert repo.max_seq(cid) == -1
    repo.agregar_item(cid, _fila(seq=0))
    repo.agregar_item(cid, _fila(seq=1))
    assert repo.max_seq(cid) == 1


def test_max_seq_ignora_los_huecos(repo):
    """Con la fila 1 borrada, reanudar por CONTEO daría 1 y duplicaría la fila 1.
    Por eso se usa el máximo y no la cantidad."""
    cid = repo.crear_corrida(_meta())
    for s in (0, 1, 2):
        repo.agregar_item(cid, _fila(seq=s))
    repo.borrar_items(cid, [1])
    assert repo.max_seq(cid) == 2
```

Usar el helper de filas que ya exista en el archivo para `_fila`; si no existe, definirlo una vez arriba con la forma mínima de `CorridaItemRow` que usen los otros tests del mismo archivo.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_contrato.py -k "plan_se_guarda or max_seq" -q`
Expected: FAIL con `AttributeError: ... has no attribute 'set_plan'`

- [ ] **Step 3: Declarar los métodos en el contrato**

En `apu_tool/datos/repositorio.py`, dentro de `class RepositorioCorridas(Protocol)`, después de `set_costo_manual`:

```python
    def set_plan(self, corrida_id: int, plan_json: str, conn=None) -> None:
        """Guarda las líneas ya interpretadas del Excel. Única fuente de qué falta
        armar: el archivo subido no se persiste."""
        ...

    def get_plan(self, corrida_id: int) -> Optional[str]:
        """El plan crudo, o None si la corrida no existe o no tiene."""
        ...

    def max_seq(self, corrida_id: int) -> int:
        """El `seq` más alto ya armado, o -1 si no hay ninguno. El worker reanuda en
        `max_seq + 1`. Se usa el MÁXIMO y no la cantidad: con una fila borrada en el
        medio, contar reanudaría sobre un seq que ya existe."""
        ...
```

- [ ] **Step 4: Implementar en SQLite**

En `apu_tool/datos/corridas_db.py`, junto a los otros `set_*`:

```python
    def set_plan(self, corrida_id: int, plan_json: str, conn=None) -> None:
        sql = "UPDATE corrida SET plan_json=? WHERE id=?"
        if conn is not None:
            conn.execute(sql, (plan_json, int(corrida_id)))
            return
        with self.connect() as c:
            c.execute(sql, (plan_json, int(corrida_id)))

    def get_plan(self, corrida_id: int) -> Optional[str]:
        with self.connect() as conn:
            r = conn.execute("SELECT plan_json FROM corrida WHERE id=?",
                             (int(corrida_id),)).fetchone()
        return r["plan_json"] if r else None

    def max_seq(self, corrida_id: int) -> int:
        with self.connect() as conn:
            r = conn.execute("SELECT MAX(seq) AS m FROM corrida_item WHERE corrida_id=?",
                             (int(corrida_id),)).fetchone()
        return -1 if (r is None or r["m"] is None) else int(r["m"])
```

- [ ] **Step 5: Implementar en Postgres**

En `apu_tool/datos/pg/corridas_pg.py`, el espejo exacto (`%s` en vez de `?`, tablas con prefijo `corridas.`, `self.cx.connection()`):

```python
    def set_plan(self, corrida_id: int, plan_json: str, conn=None) -> None:
        sql = "UPDATE corridas.corrida SET plan_json=%s WHERE id=%s"
        if conn is not None:
            conn.execute(sql, (plan_json, int(corrida_id)))
            return
        with self.cx.connection() as c:
            c.execute(sql, (plan_json, int(corrida_id)))

    def get_plan(self, corrida_id: int) -> Optional[str]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT plan_json FROM corridas.corrida WHERE id=%s",
                             (int(corrida_id),)).fetchone()
        return r["plan_json"] if r else None

    def max_seq(self, corrida_id: int) -> int:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT MAX(seq) AS m FROM corridas.corrida_item WHERE corrida_id=%s",
                (int(corrida_id),)).fetchone()
        return -1 if (r is None or r["m"] is None) else int(r["m"])
```

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: PASS

- [ ] **Step 7: Paridad de firmas entre backends**

Run: `python -m pytest tests/test_paridad_backends.py -q`
Expected: PASS. Si falla, es porque ese test compara las firmas del Protocol contra las dos implementaciones — agregar los métodos que reporte faltantes, no relajar el test.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_contrato.py
git commit -m "feat(datos): set_plan/get_plan/max_seq en los dos backends

max_seq devuelve -1 con la corrida vacia para que max_seq+1 arranque en 0, y
es el MAXIMO y no la cantidad: con una fila borrada en el medio, contar
reanudaria sobre un seq que ya existe."
```

---

## Tarea 3: La reclama atómica

**Files:**
- Modify: `apu_tool/datos/repositorio.py`
- Modify: `apu_tool/datos/corridas_db.py`
- Modify: `apu_tool/datos/pg/corridas_pg.py`
- Test: `tests/test_corridas_contrato.py`

- [ ] **Step 1: Write the failing test**

```python
def test_reclamar_toma_la_mas_vieja_y_solo_una_vez(repo):
    """La reclama es un UPDATE condicional: dos workers compitiendo, uno solo gana.
    Es lo que cierra la ventana del deploy, cuando la instancia nueva arranca
    mientras la vieja todavia esta armando."""
    vieja = repo.crear_corrida(_meta(creada_en="2026-01-01T00:00:00", estado="armando"))
    repo.crear_corrida(_meta(creada_en="2026-01-02T00:00:00", estado="armando"))

    ganada = repo.reclamar_armado("instancia-A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    assert ganada == vieja                      # la más vieja primero

    # Segunda pasada con la reclama todavía fresca: NO la puede volver a tomar.
    otra = repo.reclamar_armado("instancia-B", "2026-01-03T10:00:10", "2026-01-03T09:57:10")
    assert otra != vieja


def test_una_reclama_vencida_se_puede_retomar(repo):
    cid = repo.crear_corrida(_meta(estado="armando"))
    repo.reclamar_armado("instancia-A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    # El límite de vencimiento ya pasó la hora del latido de A: la instancia murió.
    assert repo.reclamar_armado("instancia-B", "2026-01-03T10:10:00",
                                "2026-01-03T10:07:00") == cid


def test_reclamar_sube_los_intentos(repo):
    cid = repo.crear_corrida(_meta(estado="armando"))
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    assert repo.get_corrida(cid).intentos == 1
    repo.reclamar_armado("B", "2026-01-03T10:10:00", "2026-01-03T10:07:00")
    assert repo.get_corrida(cid).intentos == 2


def test_reclamar_ignora_lo_que_no_esta_armando(repo):
    repo.crear_corrida(_meta(estado="en_revision"))
    repo.crear_corrida(_meta(estado="armado_detenido"))
    assert repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00") is None


def test_latir_corre_el_vencimiento(repo):
    cid = repo.crear_corrida(_meta(estado="armando"))
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    repo.latir_armado(cid, "2026-01-03T10:20:00")
    # Un límite que habría vencido la reclama original ya no alcanza.
    assert repo.reclamar_armado("B", "2026-01-03T10:21:00", "2026-01-03T10:18:00") is None


def test_finalizar_libera_la_reclama(repo):
    cid = repo.crear_corrida(_meta(estado="armando"))
    repo.reclamar_armado("A", "2026-01-03T10:00:00", "2026-01-03T09:57:00")
    repo.finalizar_armado(cid, "en_revision", duracion_ms=1234)
    m = repo.get_corrida(cid)
    assert (m.estado, m.armando_por, m.duracion_ms) == ("en_revision", None, 1234)


def test_detener_guarda_el_motivo(repo):
    cid = repo.crear_corrida(_meta(estado="armando"))
    repo.finalizar_armado(cid, "armado_detenido", error="El Excel no se pudo leer.")
    m = repo.get_corrida(cid)
    assert (m.estado, m.ultimo_error) == ("armado_detenido", "El Excel no se pudo leer.")


def test_reencolar_limpia_intentos_y_error(repo):
    cid = repo.crear_corrida(_meta(estado="armado_detenido"))
    repo.finalizar_armado(cid, "armado_detenido", error="se murió")
    repo.reencolar_armado(cid)
    m = repo.get_corrida(cid)
    assert (m.estado, m.intentos, m.ultimo_error) == ("armando", 0, None)


def test_posicion_en_cola_cuenta_las_mas_viejas(repo):
    a = repo.crear_corrida(_meta(creada_en="2026-01-01T00:00:00", estado="armando"))
    b = repo.crear_corrida(_meta(creada_en="2026-01-02T00:00:00", estado="armando"))
    assert repo.posicion_en_cola(a) == 0
    assert repo.posicion_en_cola(b) == 1
```

El helper `_meta()` tiene que aceptar `creada_en` y `estado`; si el que hay en el archivo no lo hace, extenderlo con esos dos parámetros con default.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_contrato.py -k "reclamar or latir or finalizar or detener or reencolar or posicion" -q`
Expected: FAIL con `AttributeError: ... has no attribute 'reclamar_armado'`

- [ ] **Step 3: Declarar en el contrato**

En `apu_tool/datos/repositorio.py`, después de `max_seq`:

```python
    def reclamar_armado(self, instancia: str, ahora: str,
                        limite_vencimiento: str) -> Optional[int]:
        """Toma la corrida en 'armando' más vieja que nadie esté armando, y devuelve
        su id (None si no hay ninguna). Sube `intentos`.

        ES UN SOLO UPDATE CONDICIONAL, no un "leo y después escribo": durante un
        deploy la instancia nueva arranca mientras la vieja todavía drena, y sin
        atomicidad las dos armarían la misma corrida sobre una tabla que hasta hace
        poco ni siquiera tenía UNIQUE(corrida_id, seq).

        `limite_vencimiento` es el ISO por debajo del cual una reclama se considera
        muerta (ahora - config.ARMADO_TTL_RECLAMA_S)."""
        ...

    def latir_armado(self, corrida_id: int, ahora: str) -> None:
        """Refresca `armando_desde` para que la reclama no venza mientras se trabaja."""
        ...

    def finalizar_armado(self, corrida_id: int, estado: str,
                         duracion_ms: Optional[int] = None,
                         error: Optional[str] = None) -> None:
        """Fija `estado`, libera la reclama y guarda la duración o el motivo.

        Con `estado='en_revision'` o `'armado_detenido'` saca la corrida de la cola
        (es el único camino de salida junto con `reencolar_armado`). El worker
        también la llama con `estado='armando'` tras un fallo que no es de un ítem:
        ahí la corrida SIGUE en la cola, solo se suelta la reclama para que se pueda
        reintentar de inmediato en vez de esperar el TTL. `intentos` no se toca, así
        que el tope sigue aplicando."""
        ...

    def reencolar_armado(self, corrida_id: int) -> None:
        """Vuelve a poner la corrida en la cola desde cero: 'armando', intentos en 0,
        sin error y sin reclama. Lo usa el endpoint de reanudar a mano."""
        ...

    def posicion_en_cola(self, corrida_id: int) -> int:
        """Cuántas corridas en 'armando' son más viejas que esta. 0 = es la próxima."""
        ...
```

- [ ] **Step 4: Implementar en SQLite**

```python
    def reclamar_armado(self, instancia: str, ahora: str,
                        limite_vencimiento: str) -> Optional[int]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT id FROM corrida "
                " WHERE estado='armando' "
                "   AND (armando_desde IS NULL OR armando_desde < ?) "
                " ORDER BY creada_en ASC, id ASC LIMIT 1",
                (limite_vencimiento,)).fetchone()
            if r is None:
                return None
            cid = int(r["id"])
            # El WHERE se repite entero: entre el SELECT y el UPDATE otro worker pudo
            # haberla reclamado. Si rowcount es 0, la perdimos y no devolvemos nada.
            cur = conn.execute(
                "UPDATE corrida "
                "   SET armando_por=?, armando_desde=?, intentos=intentos+1 "
                " WHERE id=? AND estado='armando' "
                "   AND (armando_desde IS NULL OR armando_desde < ?)",
                (instancia, ahora, cid, limite_vencimiento))
            return cid if cur.rowcount > 0 else None

    def latir_armado(self, corrida_id: int, ahora: str) -> None:
        with self.connect() as conn:
            conn.execute("UPDATE corrida SET armando_desde=? WHERE id=?",
                         (ahora, int(corrida_id)))

    def finalizar_armado(self, corrida_id: int, estado: str,
                         duracion_ms: Optional[int] = None,
                         error: Optional[str] = None) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida "
                "   SET estado=?, armando_por=NULL, armando_desde=NULL, "
                "       duracion_ms=COALESCE(?, duracion_ms), ultimo_error=? "
                " WHERE id=?",
                (estado, duracion_ms, error, int(corrida_id)))

    def reencolar_armado(self, corrida_id: int) -> None:
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida "
                "   SET estado='armando', intentos=0, ultimo_error=NULL, "
                "       armando_por=NULL, armando_desde=NULL "
                " WHERE id=?", (int(corrida_id),))

    def posicion_en_cola(self, corrida_id: int) -> int:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT COUNT(*) AS n FROM corrida "
                " WHERE estado='armando' AND (creada_en, id) < "
                "       (SELECT creada_en, id FROM corrida WHERE id=?)",
                (int(corrida_id),)).fetchone()
        return int(r["n"]) if r else 0
```

- [ ] **Step 5: Implementar en Postgres**

Espejo exacto con `%s`, prefijo `corridas.` y `self.cx.connection()`. Dos diferencias a respetar:

- El `rowcount` de psycopg se lee del cursor: `cur = conn.execute(...)` y después `cur.rowcount`.
- La comparación de tuplas `(creada_en, id) < (...)` funciona igual en Postgres; mantener la misma forma para que las dos implementaciones ordenen idéntico.

- [ ] **Step 6: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: PASS

- [ ] **Step 7: Correr el contrato contra Postgres real**

Run (con el Postgres desechable de la receta del proyecto):
`TEST_DATABASE_URL=postgresql://postgres:postgres@127.0.0.1:55433/postgres python -m pytest tests/test_corridas_contrato.py tests/test_paridad_backends.py -q`
Expected: PASS, 0 skipped en esos archivos.

**NUNCA apuntar `TEST_DATABASE_URL` a producción: estos tests hacen `DROP SCHEMA`.**

- [ ] **Step 8: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_contrato.py
git commit -m "feat(datos): reclama atomica del armado en los dos backends

reclamar_armado es un UPDATE condicional que repite el WHERE entero: durante
un deploy la instancia nueva arranca mientras la vieja drena, y sin esto las
dos armarian la misma corrida. finalizar_armado y reencolar_armado son los
dos unicos caminos de salida de 'armando'."
```

---

## Tarea 4: El índice único, y que no tumbe el arranque

**Files:**
- Modify: `db/corridas.sql`
- Modify: `db/pg/corridas.sql`
- Modify: `apu_tool/datos/corridas_db.py` (`init_schema`)
- Test: `tests/test_corridas_contrato.py`

- [ ] **Step 1: Write the failing test**

```python
def test_no_se_puede_duplicar_un_seq(repo):
    """Sin este indice una fila duplicada entra CALLADA y duplica la actividad en el
    cuadro. Con el indice, revienta: preferimos fallar a mentir."""
    import pytest
    cid = repo.crear_corrida(_meta())
    repo.agregar_item(cid, _fila(seq=0))
    with pytest.raises(Exception):
        repo.agregar_item(cid, _fila(seq=0))
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_corridas_contrato.py -k duplicar_un_seq -q`
Expected: FAIL con `DID NOT RAISE`

- [ ] **Step 3: Crear el índice, de forma no-fatal**

En `db/corridas.sql`, junto al `CREATE INDEX ix_corrida_item`:

```sql
-- El seq identifica la fila dentro de la corrida (es la clave del snapshot y de la
-- URL del item). Sin UNIQUE, una fila repetida entra callada.
CREATE UNIQUE INDEX IF NOT EXISTS ux_corrida_item_seq ON corrida_item(corrida_id, seq);
```

En `db/pg/corridas.sql`, junto a su `CREATE INDEX`:

```sql
CREATE UNIQUE INDEX IF NOT EXISTS ux_corrida_item_seq
    ON corridas.corrida_item(corrida_id, seq);
```

**El `.sql` de SQLite se ejecuta con `executescript` dentro de `init_schema`, así que un duplicado preexistente lo haría fallar y la app no arrancaría.** Envolverlo: en `apu_tool/datos/corridas_db.py::init_schema`, sacar esa línea del `.sql` **no** es necesario porque `CREATE UNIQUE INDEX` va después del `CREATE TABLE`; lo que hay que hacer es capturarlo. Agregar al final de `init_schema`, y **quitar** la línea del `.sql` de SQLite (dejarla solo en el de Postgres):

```python
            # Fuera del executescript y con try: si una base vieja trae duplicados de
            # armados muertos, el indice no se puede crear — y eso NO puede impedir
            # que la app arranque. Se grita en el log y se limpia a mano.
            try:
                conn.execute("CREATE UNIQUE INDEX IF NOT EXISTS ux_corrida_item_seq "
                             "ON corrida_item(corrida_id, seq)")
            except sqlite3.IntegrityError:
                logger.error(
                    "No se pudo crear ux_corrida_item_seq: hay (corrida_id, seq) "
                    "duplicados. El armado reanudable no esta protegido hasta "
                    "limpiarlos. Consulta: SELECT corrida_id, seq, COUNT(*) FROM "
                    "corrida_item GROUP BY 1,2 HAVING COUNT(*) > 1;")
```

Necesita `import logging` y `logger = logging.getLogger(__name__)` arriba del archivo si no están.

En Postgres, `ejecutar_migracion` corre el `.sql` entero; envolver igual el `CREATE UNIQUE INDEX` en `CorridasPg.init_schema` con `try/except psycopg.errors.UniqueViolation` y el mismo `logger.error`, y sacarlo del `.sql`.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add db/corridas.sql db/pg/corridas.sql apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_contrato.py
git commit -m "feat(datos): UNIQUE(corrida_id, seq), y no-fatal si ya hay duplicados

Sin el indice una fila repetida entra callada y duplica la actividad en el
cuadro. La creacion va fuera del script y con try: una base con duplicados
de armados muertos no puede impedir que la app arranque; se loggea con la
consulta para encontrarlos."
```

---

## Tarea 5: `plan_json` no puede llegar a la IA

**Files:**
- Modify: `apu_tool/dominio/privacy.py:21-26`
- Test: `tests/test_privacy.py`

- [ ] **Step 1: Write the failing test**

En `tests/test_privacy.py`:

```python
def test_plan_json_es_dinero_y_no_pasa():
    """plan_json lleva las lineas de licitacion, con su precio_contractual dentro.
    CLAUDE.md: todo campo monetario nuevo entra en _FORBIDDEN_KEYS."""
    import pytest
    from apu_tool.dominio import privacy
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money({"corrida": {"plan_json": "[]"}})
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_privacy.py -k plan_json -q`
Expected: FAIL con `DID NOT RAISE`

- [ ] **Step 3: Agregar la clave**

En `apu_tool/dominio/privacy.py`, en `_FORBIDDEN_KEYS`:

```python
    "fuente_precio", "costo_manual", "plan_json",
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_privacy.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/privacy.py tests/test_privacy.py
git commit -m "feat(privacidad): plan_json es dinero (lleva precio_contractual)"
```

---

## Tarea 6: Extraer el bucle de armado, con punto de arranque

**Files:**
- Modify: `apu_tool/servicio/corridas.py:108-166`
- Test: `tests/test_api_corridas.py`

Esta tarea **no cambia ningún comportamiento**: solo parte `construir_corrida_stream` en dos para que el worker pueda entrar por el medio.

- [ ] **Step 1: Write the failing test**

En `tests/test_api_corridas.py`:

```python
def test_armar_pendientes_arranca_donde_se_le_dice(tmp_path):
    """El worker reanuda por el medio: con desde_seq=2 no vuelve a armar 0 y 1."""
    from apu_tool.servicio import corridas as svc
    alm = _almacen(tmp_path)                      # helper existente del archivo
    items = [_item(f"ACTIVIDAD {i}") for i in range(4)]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(alm))
    eventos = list(svc.armar_pendientes(alm, cid, items, desde_seq=2))
    armados = [p["i"] for e, p in eventos if e == "progress"]
    assert armados == [3, 4]                       # 1-based: solo los seq 2 y 3
    assert [r.seq for r in alm.corridas.get_items(cid)] == [2, 3]
```

Reusar los helpers `_almacen`, `_item`, `_carpeta` que ya existan en `tests/test_api_corridas.py`; si tienen otro nombre, usar ese.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py -k armar_pendientes -q`
Expected: FAIL con `AttributeError: module ... has no attribute 'crear_corrida_encolada'`

- [ ] **Step 3: Partir la función**

En `apu_tool/servicio/corridas.py`, reemplazar `construir_corrida_stream` (líneas 108-151) por estas tres:

```python
def crear_corrida_encolada(alm: Almacen, archivo: str, items: list[LicitacionItem],
                           turno_def: str, use_ai: Optional[bool],
                           carpeta_id: Optional[int] = None,
                           nombre: Optional[str] = None,
                           lista_precios_id: Optional[int] = None) -> int:
    """Crea la corrida en 'armando' con su plan guardado y devuelve el id. NO arma:
    de eso se encarga el worker (`servicio/armador.py`), que la ve porque
    `estado='armando'` ES la cola.

    Guardar el plan es lo que hace posible reanudar: el Excel subido no se persiste,
    así que sin esto un reinicio deja la corrida a medias sin forma de continuar.
    """
    nombre_efectivo = (nombre or "").strip()[:120].strip() or nombre_desde_archivo(archivo)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="armando", cuadro_path=None, carpeta_id=carpeta_id,
        nombre=nombre_efectivo, lista_precios_id=lista_precios_id))
    alm.corridas.set_plan(corrida_id, json.dumps([asdict(i) for i in items],
                                                 ensure_ascii=False))
    return corrida_id


def plan_de(alm: Almacen, corrida_id: int) -> list[LicitacionItem]:
    """Las líneas guardadas al crear la corrida. Lista vacía si no hay plan."""
    crudo = alm.corridas.get_plan(corrida_id)
    if not crudo:
        return []
    return [LicitacionItem(**d) for d in json.loads(crudo)]


def armar_pendientes(alm: Almacen, corrida_id: int, items: list[LicitacionItem],
                     desde_seq: int = 0):
    """Arma los ítems de `items` desde el índice `desde_seq`, emitiendo:
      ('progress', {'i','total','descripcion','fila'}) — por ítem ya persistido.
      ('error', {'detail': ...})                       — la corrida se borró a mitad.

    Un ítem que revienta NO tumba la corrida: se persiste sin APU con el motivo en
    `explicacion` y se sigue. Cae solo en el candado de `seqs_sin_apu`, que impide
    emitir el cuadro; y si no vale la pena armarle el APU, se puede igualar el costo
    al contractual (que abre ese candado a propósito).
    """
    advisor = ApuAdvisor(enabled=False)   # el armado NUNCA llama a la IA (test lo fija)
    meta = alm.corridas.get_corrida(corrida_id)
    assembler = Assembler(alm, advisor=advisor,
                          lista_id=meta.lista_precios_id if meta else None)
    total = len(items)
    for seq in range(desde_seq, total):
        item = items[seq]
        i = seq + 1
        print(f"  [{i}/{total}] {item.descripcion[:60]}", flush=True)
        try:
            ens, fila = _armar_fila(assembler, item, seq)
        except Exception as exc:                  # noqa: BLE001 — un ítem venenoso
            logger.exception("Fallo al armar el ítem %s de la corrida %s", seq, corrida_id)
            ens, fila = _fila_sin_apu(item, seq, f"No se pudo armar: {exc}")
        try:
            alm.corridas.agregar_item(corrida_id, fila)
        except CorridaEliminada:
            yield ("error", {"detail": "Armado cancelado: la corrida fue eliminada."})
            return
        yield ("progress", {"i": i, "total": total,
                            "descripcion": item.descripcion,
                            "fila": _vista_item(ens, seq, ens.status.value)})
```

Y el helper de la fila envenenada, justo debajo de `_armar_fila`:

```python
def _fila_sin_apu(item: LicitacionItem, seq: int,
                  motivo: str) -> tuple[AssembledApu, CorridaItemRow]:
    """La fila que queda cuando armar un ítem revienta: sin APU, en $0, con el motivo
    a la vista. No se inventa nada — es exactamente lo que el armado ya produce para
    un ítem bajo el umbral."""
    ens = AssembledApu(
        item=item, apu_codigo=None, apu_nombre="(no se pudo armar)",
        unidad=item.unidad, shift=item.shift, componentes=[], costo_unitario=0.0,
        status=MatchStatus.NEW, confianza=0.0, origen="manual", explicacion=motivo)
    fila = CorridaItemRow(
        seq=seq, item=item, status=ens.status.value, apu_codigo=None, apu_nombre="",
        unidad=item.unidad, shift=item.shift, origen="manual", confianza=0.0,
        explicacion=motivo, componentes=[], candidatos=[])
    return ens, fila
```

Verificar los nombres de los campos de `CorridaItemRow` y `AssembledApu` contra `apu_tool/nucleo/models.py` antes de escribirlo, y ajustar si difieren.

`construir_corrida` (el envoltorio no-stream que usan CLI/GUI) pasa a:

```python
def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None,
                      nombre: Optional[str] = None,
                      lista_precios_id: Optional[int] = None) -> int:
    """Crea y arma en el acto, sin worker ni cola. Lo usan la CLI, la GUI y los tests:
    ahí no hay proceso de fondo que espere, y las listas son chicas."""
    corrida_id = crear_corrida_encolada(alm, archivo, items, turno_def, use_ai,
                                        carpeta_id, nombre, lista_precios_id)
    t0 = time.monotonic()
    for _evento, _payload in armar_pendientes(alm, corrida_id, items, desde_seq=0):
        pass
    alm.corridas.finalizar_armado(corrida_id, "en_revision",
                                  duracion_ms=round((time.monotonic() - t0) * 1000))
    return corrida_id
```

Agregar los imports que falten arriba del archivo: `from dataclasses import asdict`, `import json`, `import logging`, y `logger = logging.getLogger(__name__)` si no existen.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS

- [ ] **Step 5: Confirmar que el armado sigue sin llamar a la IA**

Run: `python -m pytest tests/test_assemble.py -q`
Expected: PASS, incluido `test_armado_nunca_llama_a_la_ia`

- [ ] **Step 6: Suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS. `construir_corrida_stream` ya no existe: si algún test lo importa, cambiarlo a `armar_pendientes`.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_api_corridas.py
git commit -m "refactor(corridas): partir el armado en crear-encolada + armar-pendientes

armar_pendientes recibe desde_seq, que es por donde entra el worker al
reanudar. Un item que revienta ya no tumba la corrida: queda sin APU con el
motivo y el armado sigue. construir_corrida (CLI/GUI) llama a las dos
seguidas y sigue armando sincrono."
```

---

## Tarea 7: Borrar líneas queda bloqueado mientras arma

**Files:**
- Modify: `apu_tool/servicio/corridas.py:266-285` (`borrar_items`)
- Test: `tests/test_api_corridas.py`

- [ ] **Step 1: Write the failing test**

```python
def test_borrar_lineas_mientras_arma_da_error(tmp_path):
    """Sin esta guarda: borras las ULTIMAS lineas, la instancia muere, y al reanudar
    max(seq)+1 retrocede y el worker re-arma justo lo que borraste."""
    import pytest
    from apu_tool.servicio import corridas as svc
    alm = _almacen(tmp_path)
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", [_item("A"), _item("B")],
                                     "DIURNO", None, carpeta_id=_carpeta(alm))
    list(svc.armar_pendientes(alm, cid, [_item("A"), _item("B")]))
    # sigue en 'armando': crear_corrida_encolada no la finaliza
    with pytest.raises(ValueError, match="se está armando"):
        svc.borrar_items(alm, cid, [1])
    assert len(alm.corridas.get_items(cid)) == 2      # no borró nada

    alm.corridas.finalizar_armado(cid, "en_revision")
    svc.borrar_items(alm, cid, [1])                    # ya terminada: sí deja
    assert len(alm.corridas.get_items(cid)) == 1
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py -k borrar_lineas_mientras_arma -q`
Expected: FAIL con `DID NOT RAISE ValueError`

- [ ] **Step 3: Agregar la guarda**

En `apu_tool/servicio/corridas.py`, en `borrar_items`, después del chequeo de `modo == "congelada"`:

```python
    if meta.estado == "armando":
        # El punto de reanudación del worker es `max(seq)+1`. Borrar las últimas
        # líneas lo hace RETROCEDER, y si la instancia muere ahí, al reanudar se
        # re-arma exactamente lo que se acaba de borrar. Misma guarda y mismo motivo
        # que `agregar_items`.
        raise ValueError("La corrida se está armando; esperá a que termine "
                         "para borrar líneas.")
```

Y actualizar el docstring de `borrar_items` agregando: `Lanza ValueError si la corrida todavía se está armando.`

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS

- [ ] **Step 5: Verificar que la ruta traduce el ValueError**

Leer `apu_tool/servicio/rutas.py` en el endpoint `POST /corridas/{cid}/items/borrar`: tiene que haber un `except ValueError` que devuelva 422 o 400. Si no lo hay, agregarlo con el mismo estilo que el endpoint de agregar líneas.

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py apu_tool/servicio/rutas.py tests/test_api_corridas.py
git commit -m "feat(corridas): no se borran lineas mientras la corrida se arma

max(seq)+1 es el punto de reanudacion y borrar el final lo hace retroceder:
si la instancia muere ahi, el worker re-arma lo borrado. Misma guarda que ya
tenia agregar_items, por la misma razon."
```

---

## Tarea 8: El worker

**Files:**
- Modify: `apu_tool/config.py`
- Create: `apu_tool/servicio/armador.py`
- Test: `tests/test_armador.py` (crear)

- [ ] **Step 1: Los cuatro números, en config**

En `apu_tool/config.py`, cerca de los otros umbrales:

```python
# --- armado como trabajo del servidor (servicio/armador.py) ---
# Una reclama sin latido por más de esto se considera muerta y otra instancia puede
# retomar la corrida. Es el tiempo de recuperación tras un reinicio de golpe: más
# corto arriesga doble armado durante el drenaje de un deploy, más largo hace esperar.
ARMADO_TTL_RECLAMA_S = 180
# Cada cuánto se refresca la reclama, EN TIEMPO. Contra el TTL de arriba da 3x de
# margen fijo. Se mide en segundos y no en ítems a propósito: un lease se mide en
# tiempo, y contar ítems ataba el margen a una velocidad que no controlamos (medida
# variando de 2,8 a 6,2 s/ítem, o sea entre 1,16x y 2,6x de margen). No la cambies
# sin mirar ARMADO_TTL_RECLAMA_S.
ARMADO_LATIDO_S = 60
# Respaldo del evento: es lo ÚNICO que hace arrancar un armado huérfano al bootear,
# cuando no hay ningún evento que despierte al worker.
ARMADO_POLL_S = 30
# Reclamas antes de rendirse. Cubre "algo la mata siempre en el mismo punto".
ARMADO_MAX_INTENTOS = 3
```

- [ ] **Step 2: Write the failing test**

Crear `tests/test_armador.py`:

```python
"""El worker del armado: un ciclo, sin hilo y sin dormir."""
from apu_tool import config
from apu_tool.servicio import armador, corridas as svc


def test_un_ciclo_arma_la_corrida_pendiente(tmp_path):
    alm = _almacen(tmp_path)
    items = [_item("A"), _item("B")]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(alm))
    assert armador.un_ciclo(alm, "instancia-test") is True
    m = alm.corridas.get_corrida(cid)
    assert m.estado == "en_revision"
    assert m.armando_por is None
    assert len(alm.corridas.get_items(cid)) == 2


def test_un_ciclo_sin_trabajo_devuelve_false(tmp_path):
    alm = _almacen(tmp_path)
    assert armador.un_ciclo(alm, "instancia-test") is False


def test_reanuda_desde_donde_quedo_y_no_duplica(tmp_path):
    """El caso entero: media corrida armada, la instancia murio, otra la retoma."""
    alm = _almacen(tmp_path)
    items = [_item("A%d" % i) for i in range(5)]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(alm))
    for _ in svc.armar_pendientes(alm, cid, items[:2], desde_seq=0):
        pass                                    # arma solo los seq 0 y 1
    assert armador.un_ciclo(alm, "instancia-B") is True
    seqs = sorted(r.seq for r in alm.corridas.get_items(cid))
    assert seqs == [0, 1, 2, 3, 4]              # completa y sin duplicados


def test_al_pasar_el_tope_de_intentos_se_detiene(tmp_path):
    """Algo la mata siempre en el mismo punto: deja de reintentarse para siempre."""
    alm = _almacen(tmp_path)
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", [_item("A")], "DIURNO", None,
                                     carpeta_id=_carpeta(alm))
    for _ in range(config.ARMADO_MAX_INTENTOS):
        alm.corridas.reclamar_armado("X", "2026-01-01T00:00:00", "2025-12-31T00:00:00")
    assert armador.un_ciclo(alm, "instancia-C") is True
    m = alm.corridas.get_corrida(cid)
    assert m.estado == "armado_detenido"
    assert "interrump" in (m.ultimo_error or "").lower()
```

Los helpers `_almacen`, `_item`, `_carpeta`: copiarlos de `tests/test_api_corridas.py` (mismo cuerpo). **No** inventar una forma nueva de construir el almacén.

- [ ] **Step 3: Run test to verify it fails**

Run: `python -m pytest tests/test_armador.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.servicio.armador'`

- [ ] **Step 4: Escribir el worker**

Crear `apu_tool/servicio/armador.py`:

```python
"""El worker del armado: un hilo que consume la cola que vive en la base.

`corrida.estado == 'armando'` ES la cola. No hay estructura en memoria que se pueda
perder en un reinicio: al arrancar, la instancia ve exactamente el mismo trabajo
pendiente que dejó la anterior.

Por qué un hilo acá y no un Background Worker de Render: un servicio aparte cuesta
plata y otro deploy, y sigue muriendo y reiniciándose — o sea, necesitarías reanudar
igual. El día que la web se ponga lenta durante un armado, mudarlo es cambiar quién
llama a `correr_para_siempre`: todo lo demás lee su trabajo de la base.
"""
from __future__ import annotations

import logging
import os
import threading
import time
import uuid
from datetime import datetime, timedelta

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio import corridas as svc

logger = logging.getLogger(__name__)

# Se levanta al crear una corrida para que el worker arranque YA en vez de esperar el
# poll. El poll sigue existiendo porque al bootear no hay ningún evento que levantar.
hay_trabajo = threading.Event()


def id_de_instancia() -> str:
    """Quién es esta instancia, para la reclama. En Render viene en el entorno; si no,
    un uuid por proceso alcanza (lo único que importa es que dos procesos difieran)."""
    return os.environ.get("RENDER_INSTANCE_ID") or "local-%s" % uuid.uuid4().hex[:8]


def _ahora() -> str:
    return datetime.now().isoformat(timespec="seconds")


def _limite_vencimiento() -> str:
    vencido = datetime.now() - timedelta(seconds=config.ARMADO_TTL_RECLAMA_S)
    return vencido.isoformat(timespec="seconds")


def un_ciclo(alm: Almacen, instancia: str) -> bool:
    """Reclama UNA corrida y la arma entera. Devuelve si había trabajo.

    Separado de `correr_para_siempre` para poder testear el ciclo sin hilo, sin
    dormir y sin app: los tests llaman a esto.
    """
    corrida_id = alm.corridas.reclamar_armado(instancia, _ahora(), _limite_vencimiento())
    if corrida_id is None:
        return False

    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:                       # la borraron entre el UPDATE y el SELECT
        return True
    if meta.intentos > config.ARMADO_MAX_INTENTOS:
        # Sale de la cola o se reintentaría para siempre. El usuario la puede
        # reencolar a mano desde la pantalla (POST /corridas/{id}/reanudar).
        alm.corridas.finalizar_armado(
            corrida_id, "armado_detenido",
            error=("El armado se interrumpió %d veces seguidas. Puede ser un "
                   "reinicio del servidor o un problema con el archivo. "
                   "Reintentá; si vuelve a pasar, avisá." % meta.intentos))
        return True

    try:
        items = svc.plan_de(alm, corrida_id)
        if not items:
            alm.corridas.finalizar_armado(
                corrida_id, "armado_detenido",
                error="La corrida no tiene guardadas las líneas a armar. "
                      "Volvé a subir el archivo en una corrida nueva.")
            return True
        desde = alm.corridas.max_seq(corrida_id) + 1
        t0 = time.monotonic()
        hechos = 0
        for evento, _payload in svc.armar_pendientes(alm, corrida_id, items, desde):
            if evento == "error":          # la corrida se borró a mitad
                return True
            hechos += 1
            if reloj() >= proximo_latido:
                alm.corridas.latir_armado(corrida_id, _ahora())
        alm.corridas.finalizar_armado(
            corrida_id, "en_revision",
            duracion_ms=round((time.monotonic() - t0) * 1000))
    except Exception as exc:               # noqa: BLE001
        # Un fallo que NO es de un ítem (esos ya los absorbe `armar_pendientes`):
        # se deja la corrida EN LA COLA con el motivo, para que se reintente.
        logger.exception("Fallo armando la corrida %s", corrida_id)
        alm.corridas.finalizar_armado(corrida_id, "armando", error=str(exc))
    return True


def correr_para_siempre(alm: Almacen, parar: threading.Event) -> None:
    """El bucle del hilo. Trabaja hasta vaciar la cola, después espera un evento (una
    corrida nueva) o el poll de respaldo."""
    instancia = id_de_instancia()
    logger.info("Worker de armado arrancado (instancia %s)", instancia)
    while not parar.is_set():
        try:
            while not parar.is_set() and un_ciclo(alm, instancia):
                pass
        except Exception:                  # noqa: BLE001 — el hilo NUNCA se muere
            logger.exception("Error en el bucle del worker de armado")
        hay_trabajo.wait(timeout=config.ARMADO_POLL_S)
        hay_trabajo.clear()


def arrancar(alm: Almacen):
    """Lanza el hilo en daemon y devuelve (hilo, evento-de-parada)."""
    parar = threading.Event()
    hilo = threading.Thread(target=correr_para_siempre, args=(alm, parar),
                            name="armador", daemon=True)
    hilo.start()
    return hilo, parar
```

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_armador.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/config.py apu_tool/servicio/armador.py tests/test_armador.py
git commit -m "feat(armado): worker que consume la cola que vive en la base"
```

---

## ⚠️ ORDEN CORREGIDO: la Tarea 10 va ANTES que la 9

**Descubierto y reproducido durante la revisión de la Tarea 8.** El plan original ponía
la 9 (arrancar el worker) antes que la 10 (que la API deje de armar en el request).
Ese orden **deja la app rota entre las dos tareas**.

Por qué: los cuatro endpoints que todavía arman dentro de la petición
(`rutas.py`, `construir_corrida` / `construir_corrida_stream`) crean la corrida con
`estado='armando'` y `armando_desde=NULL` — o sea que **entran a la cola en el instante
en que nacen y nunca la reclaman**. Apenas la Tarea 9 llame a `arrancar()`, el worker se
las lleva a mitad de la petición. Reproducido en proceso:

```
[1/6] ...                    <- la peticion HTTP armo el item 0
worker: un_ciclo -> True     <- el worker armo 1..5 y la cerro
EL STREAM REVIENTA: IntegrityError UNIQUE ... corrida_item.corrida_id, seq
estado final: en_revision
```

El `UNIQUE (corrida_id, seq)` de la Tarea 4 salva el dato —no salen actividades
duplicadas, que es justo para lo que está— pero el usuario se come un 500 a mitad del
stream y la corrida se cierra por debajo.

**Entonces: hacé la Tarea 10 primero.** Si por alguna razón tienen que ir en deploys
separados, el orden obligatorio es 10 y después 9; nunca al revés. La precondición
quedó escrita también en el docstring de `apu_tool/servicio/armador.py`, que es donde
la va a leer el próximo.

---

## Tarea 9: Arrancar el worker con la app

**Files:**
- Modify: `apu_tool/servicio/app.py:30-46`
- Test: `tests/test_armador.py`

- [ ] **Step 1: Write the failing test**

```python
def test_la_app_arranca_y_para_el_worker(tmp_path):
    from fastapi.testclient import TestClient
    from apu_tool.servicio.app import create_app
    alm = _almacen(tmp_path)
    app = create_app(almacen=alm)
    with TestClient(app):
        assert app.state.armador_hilo.is_alive()
    assert app.state.armador_parar.is_set()      # el lifespan lo apagó al salir
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_armador.py -k la_app_arranca -q`
Expected: FAIL con `AttributeError: 'State' object has no attribute 'armador_hilo'`

- [ ] **Step 3: Engancharlo al lifespan**

En `apu_tool/servicio/app.py`, reemplazar el cuerpo del `lifespan`:

```python
    @asynccontextmanager
    async def lifespan(app: FastAPI):
        from apu_tool.servicio import armador
        app.state.armador_hilo, app.state.armador_parar = armador.arrancar(app.state.almacen)
        yield
        # Se pide la parada y NO se hace join: el hilo puede estar a mitad de una
        # corrida de horas, y bloquear el apagado solo consigue que Render lo mate
        # igual, más tarde. Es daemon; lo que quedó a medias lo retoma la instancia
        # siguiente cuando venza la reclama — para eso existe la reclama.
        app.state.armador_parar.set()
        armador.hay_trabajo.set()          # lo despierta para que vea la parada
        app.state.almacen.cerrar()         # cierra el pool Postgres (no-op en SQLite)
```

`app.state.almacen` se asigna antes de que corra el lifespan, así que se puede usar.

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_armador.py -q`
Expected: PASS

- [ ] **Step 5: Toda la suite, para ver que ningún test de API se cuelga**

Run: `python -m pytest tests/ -q`
Expected: PASS. Los tests que usan `TestClient` ahora levantan el hilo; si alguno se pone lento, es porque dejó corridas en `armando` — dejarlas en un estado terminal en el test, no relajar el worker.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/app.py tests/test_armador.py
git commit -m "feat(servicio): el worker de armado arranca y para con la app"
```

---

## Tarea 10: La API deja de armar y pasa a encolar

**Files:**
- Modify: `apu_tool/servicio/rutas.py:163-232` y el endpoint `GET /corridas/{cid}`
- Modify: `apu_tool/servicio/corridas.py` (`vista_corrida`)
- Test: `tests/test_api_corridas.py`

- [ ] **Step 1: Write the failing test**

```python
def test_crear_corrida_devuelve_al_instante_y_encola(cliente):
    r = cliente.post("/api/corridas", files={"archivo": ("x.xlsx", _xlsx(), _MIME)},
                     data={"carpeta_id": 1, "turno": "DIURNO"})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["estado"] == "armando"
    assert cuerpo["total"] > 0
    assert "id" in cuerpo


def test_la_vista_trae_el_progreso_del_armado(cliente, alm):
    cid = _corrida_armando(alm, n_items=4, ya_armados=1)
    d = cliente.get("/api/corridas/%d" % cid).json()
    assert d["armado"] == {"hechos": 1, "total": 4, "posicion_en_cola": 0,
                           "intentos": 0, "ultimo_error": None}


def test_reanudar_devuelve_la_corrida_a_la_cola(cliente, alm):
    cid = _corrida_armando(alm, n_items=2, ya_armados=0)
    alm.corridas.finalizar_armado(cid, "armado_detenido", error="se murio")
    assert cliente.post("/api/corridas/%d/reanudar" % cid).status_code == 200
    m = alm.corridas.get_corrida(cid)
    assert (m.estado, m.intentos, m.ultimo_error) == ("armando", 0, None)


def test_el_endpoint_de_stream_ya_no_existe(cliente):
    r = cliente.post("/api/corridas/stream",
                     files={"archivo": ("x.xlsx", _xlsx(), _MIME)},
                     data={"carpeta_id": 1})
    assert r.status_code == 404
```

Usar las fixtures `cliente` / `alm` que ya tenga `tests/test_api_corridas.py`. `_corrida_armando` es un helper nuevo en ese archivo: crea con `crear_corrida_encolada` y arma `ya_armados` ítems con `armar_pendientes`.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_corridas.py -k "devuelve_al_instante or progreso_del_armado or reanudar_devuelve or stream_ya_no" -q`
Expected: FAIL (el POST arma sincrónico y devuelve `resumen`; no hay clave `armado`; `/reanudar` da 404 y `/stream` da 200)

- [ ] **Step 3: `vista_corrida` informa el progreso**

En `apu_tool/servicio/corridas.py`, dentro del dict que devuelve `vista_corrida`, antes de `"ia_disponible"`:

```python
        # Progreso del armado. `total` sale del plan y no de las filas: durante el
        # armado las filas son justamente las que faltan contar.
        "armado": _progreso_armado(alm, meta, len(rows)),
```

Y el helper, junto a `vista_corrida`:

```python
def _progreso_armado(alm: Almacen, meta: CorridaMeta, hechos: int):
    """None cuando la corrida ya terminó de armarse: la pantalla no muestra nada."""
    if meta.estado not in ("armando", "armado_detenido"):
        return None
    crudo = alm.corridas.get_plan(meta.id)
    total = len(json.loads(crudo)) if crudo else hechos
    return {"hechos": hechos, "total": total,
            "posicion_en_cola": alm.corridas.posicion_en_cola(meta.id),
            "intentos": meta.intentos, "ultimo_error": meta.ultimo_error}
```

- [ ] **Step 4: Reescribir los endpoints**

En `apu_tool/servicio/rutas.py`:

**a)** `POST /corridas` — reemplazar desde `items = ...`:

```python
    items = _items_del_upload(archivo.filename, await archivo.read(), turno)
    cid = svc.crear_corrida_encolada(alm, archivo.filename or "licitacion", items, turno,
                                     use_ai, carpeta_id=carpeta_id, nombre=nombre,
                                     lista_precios_id=lista_id)
    armador.hay_trabajo.set()       # que el worker arranque ya, sin esperar el poll
    return {"id": cid, "total": len(items), "estado": "armando"}
```

**b)** `POST /sample` — mismo tratamiento: `svc.crear_corrida_encolada(...)` + `armador.hay_trabajo.set()`, devolviendo `{"id": cid, "total": len(items), "estado": "armando"}`.

**c)** **Borrar entero** `POST /corridas/stream` (y `POST /sample/stream` si existe). **`_event_stream` se queda**: la usa `POST /corridas/{cid}/revision/stream`. Confirmarlo antes de borrar nada con:

```bash
grep -n "_event_stream" apu_tool/servicio/rutas.py
```

**d)** Endpoint nuevo, junto a los otros `POST /corridas/{cid}/...`:

```python
@router.post("/corridas/{cid}/reanudar")
def reanudar_armado(cid: int, alm: Almacen = Depends(get_almacen),
                    _: object = Depends(requiere_rol("editor"))):
    """Devuelve a la cola una corrida que se quedó en 'armado_detenido'."""
    meta = alm.corridas.get_corrida(cid)
    if meta is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    if meta.estado == "armando":
        raise HTTPException(status_code=409, detail="Esa corrida ya está en la cola.")
    alm.corridas.reencolar_armado(cid)
    armador.hay_trabajo.set()
    return svc.vista_corrida(alm, cid)
```

Agregar `from apu_tool.servicio import armador` a los imports de `rutas.py`.

- [ ] **Step 5: Run test to verify it passes**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS

- [ ] **Step 6: Suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/rutas.py apu_tool/servicio/corridas.py tests/test_api_corridas.py
git commit -m "feat(api): crear una corrida encola en vez de armar, y se borra el SSE"
```

---

## Tarea 11: La pantalla

**Files:**
- Delete: `web/src/lib/armado.tsx`, `web/src/lib/armado.test.tsx`
- Modify: `web/src/App.tsx`, `web/src/api/corridas.ts`, `web/src/lib/tipos.ts`
- Modify: `web/src/pages/Corrida.tsx`, `web/src/pages/CorridasInicio.tsx`
- Test: `web/src/pages/Corrida.test.tsx`

- [ ] **Step 1: Write the failing test**

En `web/src/pages/Corrida.test.tsx` (y **borrar** el `vi.mock("@/lib/armado", ...)` de su línea 5, porque el módulo deja de existir):

```tsx
test("muestra el progreso del armado desde la vista", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void })
    .mockResolvedValueOnce({
      ...CORRIDA, estado: "armando",
      armado: { hechos: 290, total: 1939, posicion_en_cola: 0,
                intentos: 1, ultimo_error: null },
    });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  expect(await screen.findByText(/290 de 1939/)).toBeTruthy();
});

test("una corrida detenida muestra el motivo y deja reintentar", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void })
    .mockResolvedValueOnce({
      ...CORRIDA, estado: "armado_detenido",
      armado: { hechos: 10, total: 100, posicion_en_cola: 0,
                intentos: 3, ultimo_error: "El armado se interrumpio 3 veces." },
    });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  expect(await screen.findByText(/se interrumpio 3 veces/)).toBeTruthy();
  expect(screen.getByRole("button", { name: /reintentar armado/i })).toBeTruthy();
});

test("con cola, dice que puesto tiene", async () => {
  const { getCorrida } = await import("@/api/corridas");
  (getCorrida as unknown as { mockResolvedValueOnce: (v: unknown) => void })
    .mockResolvedValueOnce({
      ...CORRIDA, estado: "armando",
      armado: { hechos: 0, total: 50, posicion_en_cola: 2,
                intentos: 0, ultimo_error: null },
    });
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  expect(await screen.findByText(/3ª en la cola/)).toBeTruthy();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run: `cd web && npx vitest run src/pages/Corrida.test.tsx`
Expected: FAIL (no encuentra los textos)

- [ ] **Step 3: Tipos y cliente**

En `web/src/lib/tipos.ts`:

```ts
export interface ProgresoArmado {
  hechos: number;
  total: number;
  posicion_en_cola: number;
  intentos: number;
  ultimo_error: string | null;
}
```

y en `CorridaDetalle`:

```ts
  /** Progreso del armado; null cuando ya terminó de armarse. */
  armado: ProgresoArmado | null;
```

En `web/src/api/corridas.ts`: **borrar** `crearCorridaStream` y `crearSampleStream`, y agregar (respetando la firma del helper de POST que ya use el archivo):

```ts
export async function crearCorrida(form: FormData): Promise<{ id: number; total: number }> {
  return apiPost("/corridas", form);
}

export async function crearSample(): Promise<{ id: number; total: number }> {
  return apiPost("/sample", undefined);
}

export async function reanudarArmado(id: number): Promise<CorridaDetalle> {
  return apiPost(`/corridas/${id}/reanudar`, undefined);
}
```

- [ ] **Step 4: Borrar el provider**

```bash
git rm web/src/lib/armado.tsx web/src/lib/armado.test.tsx
```

En `web/src/App.tsx`: quitar `import { ArmadoVivoProvider } from "@/lib/armado";` y desenvolver el árbol que ese provider envolvía.

- [ ] **Step 5: `Corrida.tsx`**

- Quitar `import { useArmadoVivo } from "@/lib/armado";`, la constante `live` (línea ~39) y el bloque `const data = live ? {...} : corrida` (líneas ~116-133): `data` pasa a ser siempre `corrida`.
- El poll (línea 102) sube a 5 s:

```tsx
          // 5 s y no 2: un armado de horas son ~5.400 peticiones por pestaña a 2 s,
          // compitiendo con el worker por el unico proceso.
          if (c.estado === "armando") timer = setTimeout(cargar, 5000);
```

- En la cabecera, junto al contador de "sin APU":

```tsx
{data.armado && data.estado === "armando" && (
  <span className="text-xs text-muted-foreground">
    {data.armado.posicion_en_cola > 0
      ? `En espera: ${data.armado.posicion_en_cola + 1}ª en la cola`
      : `Armando: ${data.armado.hechos} de ${data.armado.total}`}
  </span>
)}
{data.armado && data.estado === "armado_detenido" && (
  <span className="flex items-center gap-2 text-xs">
    <span className="text-destructive">{data.armado.ultimo_error}</span>
    {puedeEditar && (
      <Button size="sm" variant="outline" onClick={async () => {
        try { setCorrida(await reanudarArmado(corridaId)); }
        catch (e) { toast.error(e instanceof Error ? e.message : "No se pudo reanudar."); }
      }}>Reintentar armado</Button>
    )}
  </span>
)}
```

- [ ] **Step 6: `CorridasInicio.tsx`**

Reemplazar `armarArchivo` (línea 122) y `armarEjemplo` (línea 133):

```tsx
      const { id } = await crearCorrida(form);
      navigate(`/corridas/${id}`);
```

```tsx
      const { id } = await crearSample();
      navigate(`/corridas/${id}`);
```

y quitar `const { armarArchivo, armarEjemplo } = useArmadoVivo();` con su import.

- [ ] **Step 7: `MisCorridas.tsx` muestra el estado**

El spec lo pide y sin esto una corrida a medio armar se esconde en la lista: se ve
igual que una terminada. Donde ese archivo pinta el estado de cada corrida, agregar
las dos etiquetas nuevas con el mismo estilo que ya use para `en_revision` /
`finalizada`:

```tsx
{c.estado === "armando" && <span className="text-xs text-muted-foreground">armando…</span>}
{c.estado === "armado_detenido" && <span className="text-xs text-destructive">armado detenido</span>}
```

Si `MisCorridas.tsx` usa el componente `EstadoBadge` para esto, agregarle los dos
estados ahí en vez de escribir spans sueltos — es el punto de paso y ya lo tocó la
feature de igualar el costo.

- [ ] **Step 8: Run test to verify it passes**

Run: `cd web && npx vitest run`
Expected: PASS

- [ ] **Step 9: Build**

Run: `cd web && npm run build`
Expected: OK. **`tsc --noEmit` no alcanza** (`tsc -b` es el que agarra los tipos) — este repo ya se quemó con eso.

- [ ] **Step 10: Commit**

```bash
git add -A web/
git commit -m "feat(web): el progreso del armado sale del poll y muere el SSE"
```

---

## Tarea 12: El invariante de la cola, con test

**Files:**
- Test: `tests/test_armador.py`
- Modify: `CLAUDE.md`

- [ ] **Step 1: Write the test**

```python
def test_ninguna_operacion_de_fila_saca_la_corrida_de_la_cola(tmp_path):
    """`estado='armando'` ES la cola. Un set_estado sin guarda la borra de ahi para
    siempre: queda a medio armar, sin worker que la retome y sin error que mirar.
    Este test es el guardian de esa regla para el proximo que toque estado."""
    alm = _almacen(tmp_path)
    items = [_item("A"), _item("B")]
    cid = svc.crear_corrida_encolada(alm, "x.xlsx", items, "DIURNO", None,
                                     carpeta_id=_carpeta(alm))
    for _ in svc.armar_pendientes(alm, cid, items[:1], desde_seq=0):
        pass                                          # media corrida armada

    svc.igualar_costo_al_contractual(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "armando"
```

Leer la firma real de `igualar_costo_al_contractual` en `apu_tool/servicio/corridas.py` antes de escribirlo y ajustar los argumentos. Si la fila 0 quedó con `precio_contractual <= 0`, darle uno positivo en `_item("A")`.

- [ ] **Step 2: Run test**

Run: `python -m pytest tests/test_armador.py -k saca_la_corrida_de_la_cola -q`
Expected: **PASS** — hoy nadie rompe el invariante (los cinco `set_estado` de `corridas.py` están guardados por `estado == "finalizada"`, incluido el que agregó igualar-costo en `:665`). Si **falla**, encontraste un camino que sí saca corridas de la cola: arreglarlo agregando la guarda en ese punto, no cambiando el test.

- [ ] **Step 3: Documentar el invariante donde se lo va a leer**

En `CLAUDE.md`, sección **No hacer**:

```markdown
- No saques una corrida de `estado='armando'` con un `set_estado` pelado: ese estado
  **es la cola** del worker de armado (`servicio/armador.py`). Sacarla de ahí la deja a
  medio armar, sin nadie que la retome y sin error que mirar. Los únicos caminos de
  salida son `finalizar_armado` (el worker, al terminar o rendirse) y `reencolar_armado`
  (el botón de reintentar). Si escribís `estado`, guardá con `estado == "finalizada"`
  como ya hacen los cinco puntos que hoy lo tocan.
```

- [ ] **Step 4: Commit**

```bash
git add tests/test_armador.py CLAUDE.md
git commit -m "test(armado): el invariante de que 'armando' es la cola"
```

---

## Verificación final

- [ ] `python -m pytest tests/ -q` → sin fallos
- [ ] Suite contra el Postgres desechable → sin fallos y **sin skips** en `test_corridas_contrato.py` / `test_paridad_backends.py`. **Nunca apuntar `TEST_DATABASE_URL` a producción: estos tests hacen `DROP SCHEMA`.**
- [ ] `cd web && npm run build` → OK
- [ ] `cd web && npx vitest run` → PASS
- [ ] `cd web && npm run lint` → los 11 warnings preexistentes, ninguno nuevo

## Verificación en navegador (los tests no cubren nada de esto)

1. Subir una lista real y confirmar que **la página de la corrida abre al instante**, con "Armando: N de M" avanzando.
2. **Cerrar la pestaña, volver a entrar**: el armado sigue y el progreso avanzó.
3. **Reiniciar el servidor a mitad del armado** y esperar el TTL (3 min): tiene que retomar solo y terminar, sin filas duplicadas. Es el caso entero de esta feature.
4. Arrancar una segunda corrida con la primera armando: dice **"2ª en la cola"** y arranca sola al terminar la anterior.
5. Con una corrida armando, **el botón de borrar líneas da el error** y no borra.
6. **Igualar el costo al contractual** sobre filas ya armadas mientras el resto se arma: funciona y la corrida sigue en `armando`.

## Pasos manuales antes de desplegar

1. **Contar duplicados de `(corrida_id, seq)` en producción** antes de que el índice único intente crearse:

```sql
SELECT corrida_id, seq, COUNT(*) FROM corridas.corrida_item
 GROUP BY 1,2 HAVING COUNT(*) > 1;
```

Si devuelve filas, limpiarlas a mano. Si no se limpian, la app arranca igual (el índice es no-fatal) pero el armado reanudable queda sin su red.

2. **Corridas viejas en `estado='armando'`**: al desplegar, el worker las va a reclamar y **no tienen `plan_json`**, así que caen en `armado_detenido` con el mensaje de "no tiene guardadas las líneas". Es correcto (no hay forma de saber qué les faltaba), pero conviene saber cuántas son:

```sql
SELECT id, nombre, creada_en FROM corridas.corrida WHERE estado = 'armando';
```

3. **Subir el plan de Render a Starter.** Sin eso la instancia se sigue reiniciando ~7 veces al día por el spin-down; esta feature hace que el armado sobreviva a cada reinicio, no que dejen de ocurrir.
