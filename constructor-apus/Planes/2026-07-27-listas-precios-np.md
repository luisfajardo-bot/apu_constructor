> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-07-27-listas-precios-np.md`

# Listas de precios para APUs de NP — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que una corrida pueda costearse contra una **lista de precios** distinta de la del catálogo principal, para armar APUs de actividades No Previstas (NP) con la tarifa de cada obra.

**Architecture:** El precio deja de ser "uno por insumo" y pasa a ser "uno por insumo **y lista**": tabla nueva `lista_precios` + columna `lista_id` en `insumo_precios`. Todo parámetro `lista_id` nuevo es opcional con default `None`, y `None ≡ Principal ≡ comportamiento actual`. Una corrida guarda su lista al crearse y el `PricingEngine` queda atado a ella.

**Tech Stack:** Python 3.12+, SQLite + Postgres (psycopg v3), FastAPI, pytest, React 18 + TypeScript + Vite + Vitest, shadcn/ui.

## Global Constraints

- **Invariante #1:** ningún payload hacia la IA cambia. No se toca `apu_tool/dominio/privacy.py` ni `_FORBIDDEN_KEYS`. `lista_id` no es un campo monetario.
- **Invariante de esta feature:** `lista_id = None` ≡ `config.LISTA_PRINCIPAL_ID` ≡ comportamiento de hoy, en **todos** los caminos.
- **`LISTA_PRINCIPAL_ID = 1`**, siempre. Es el `DEFAULT` de la columna y el ancla del invariante.
- **Nada en $0:** un precio válido es `> 0`. El mensaje de rechazo es la constante existente `apu_tool/servicio/insumos.py::MSG_PRECIO_POSITIVO`. No se duplica el texto.
- **La suite actual NO se modifica.** Que siga verde con las firmas nuevas *es* la evidencia de no-regresión. Si un test existente falla, el bug está en el código nuevo, no en el test.
- **Persistencia solo en `apu_tool/datos/`.** Nada de SQL crudo fuera de esa capa.
- **Dual-backend:** todo método nuevo o modificado en `precios_db.py` tiene su gemelo idéntico en `pg/precios_pg.py`. El oráculo es `tests/test_repositorios_contrato.py`, que corre la misma batería contra ambos.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- Los parámetros nuevos van **al final** de las firmas: hay llamadas posicionales en el código actual.
- Frontend: verificar con `npm run build` (`tsc -b`), **nunca** `tsc --noEmit`.

## Refinamiento sobre el spec (descubierto al planear)

El spec dice "el dataclass `Insumo` no cambia". Se añade **un** campo aditivo con default:
`sin_precio: bool = False`. Motivo: sin él, `precio == 0` es indistinguible de "no hay
fila de precio en esta lista", y la UI pintaría `—` sobre un `$0` genuino —ocultando
justo lo que la regla "nada en $0" quiere hacer visible—. Con el `LEFT JOIN`,
`p.precio IS NULL` ⟺ no hay fila (la columna es `NOT NULL`), así que la señal es exacta.
Es aditivo, con default, y ningún constructor existente se rompe.

## Estructura de archivos

| Archivo | Responsabilidad | Tarea |
|---|---|---|
| `apu_tool/config.py` | `LISTA_PRINCIPAL_ID` | 1 |
| `apu_tool/nucleo/models.py` | `ListaPrecios`, `Insumo.sin_precio`, `CorridaMeta.lista_precios_id` | 1, 2, 5 |
| `db/precios.sql` | tabla `lista_precios`, columna `lista_id` | 1 |
| `apu_tool/datos/precios_db.py` | migración, CRUD de listas, `lista_id` en todo | 1, 2 |
| `db/pg/precios.sql`, `apu_tool/datos/pg/precios_pg.py` | espejo Postgres | 3 |
| `apu_tool/datos/repositorio.py` | contratos `Protocol` | 3, 5 |
| `apu_tool/dominio/pricing.py` | motor atado a una lista, sin respaldo histórico fuera de Principal | 4 |
| `apu_tool/dominio/alertas.py` | motivo "sin precio en la lista" | 4 |
| `db/corridas.sql`, `db/pg/corridas.sql`, `corridas_db.py`, `pg/corridas_pg.py` | `corrida.lista_precios_id` | 5 |
| `apu_tool/dominio/assemble.py` | `Assembler(lista_id=…)` | 6 |
| `apu_tool/servicio/corridas.py` | propagación de la lista en los 5 motores | 6 |
| `apu_tool/dominio/report.py`, `report_categorizado.py` | fila `Lista de precios` en la hoja INFO (cada uno tiene la suya) | 7 |
| `apu_tool/servicio/listas.py` **(nuevo)** | servicio de listas (crear/listar/renombrar) | 8 |
| `apu_tool/servicio/esquemas.py`, `rutas.py` | DTOs y endpoints | 8, 9, 10 |
| `apu_tool/servicio/insumos.py`, `autoria.py` | edición e import con lista | 9 |
| `apu_tool/servicio/apus.py` | costo de la biblioteca con lista | 10 |
| `web/src/lib/tipos.ts`, `web/src/api/listas.ts` **(nuevo)**, `api/insumos.ts`, `api/corridas.ts` | contrato del cliente | 11 |
| `web/src/pages/Insumos.tsx`, `components/insumos/BarraFiltros.tsx`, `TablaInsumos.tsx` | selector de lista, `—`, filtro sin precio | 12 |
| `web/src/pages/CorridasInicio.tsx`, `Corrida.tsx`, `MisCorridas.tsx` | elegir y mostrar la lista | 13 |
| `CLAUDE.md`, `docs/ARQUITECTURA.md` | documentación | 14 |

---

### Task 1: Tabla `lista_precios` y su CRUD (SQLite)

**Files:**
- Modify: `apu_tool/config.py`
- Modify: `apu_tool/nucleo/models.py`
- Modify: `db/precios.sql`
- Modify: `apu_tool/datos/precios_db.py`
- Test: `tests/test_listas_precios.py` (crear)

**Interfaces:**
- Consumes: nada (primera tarea).
- Produces:
  - `config.LISTA_PRINCIPAL_ID: int = 1`
  - `models.ListaPrecios(id: Optional[int], nombre: str, creada_en: str, creado_por: Optional[str] = None)` — `@dataclass(frozen=True)`
  - `PreciosDB.listar_listas() -> list[ListaPrecios]`
  - `PreciosDB.get_lista(lista_id: int) -> Optional[ListaPrecios]`
  - `PreciosDB.crear_lista(nombre: str, creado_por: Optional[str] = None, conn=None) -> int`
  - `PreciosDB.renombrar_lista(lista_id: int, nombre: str, conn=None) -> None`

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_listas_precios.py`:

```python
"""Listas de precios: tabla, semilla de Principal y CRUD."""
import pytest

from apu_tool import config
from apu_tool.datos.precios_db import PreciosDB


@pytest.fixture()
def precios(tmp_path):
    p = PreciosDB(tmp_path / "precios.db")
    p.init_schema()
    return p


def test_principal_existe_con_id_1(precios):
    listas = precios.listar_listas()
    assert [(l.id, l.nombre) for l in listas] == [(config.LISTA_PRINCIPAL_ID, "Principal")]


def test_init_schema_es_idempotente(precios):
    precios.init_schema()
    precios.init_schema()
    assert len(precios.listar_listas()) == 1


def test_crear_lista_devuelve_id_y_aparece_en_listar(precios):
    lid = precios.crear_lista("NP Calle 13", creado_por="u1")
    assert lid != config.LISTA_PRINCIPAL_ID
    lista = precios.get_lista(lid)
    assert lista.nombre == "NP Calle 13" and lista.creado_por == "u1"
    assert lista.creada_en                      # fecha ISO no vacía
    assert {l.nombre for l in precios.listar_listas()} == {"Principal", "NP Calle 13"}


def test_crear_lista_rechaza_nombre_vacio(precios):
    with pytest.raises(ValueError):
        precios.crear_lista("   ")


def test_crear_lista_rechaza_duplicado_sin_importar_mayusculas(precios):
    precios.crear_lista("NP Calle 13")
    with pytest.raises(ValueError):
        precios.crear_lista("np calle 13")


def test_renombrar_lista(precios):
    lid = precios.crear_lista("NP Calle 13")
    precios.renombrar_lista(lid, "NP Calle 13 - Acta 2")
    assert precios.get_lista(lid).nombre == "NP Calle 13 - Acta 2"


def test_renombrar_principal_esta_prohibido(precios):
    with pytest.raises(ValueError):
        precios.renombrar_lista(config.LISTA_PRINCIPAL_ID, "Otra cosa")


def test_renombrar_lista_inexistente_lanza(precios):
    with pytest.raises(ValueError):
        precios.renombrar_lista(999, "X")


def test_get_lista_inexistente_devuelve_none(precios):
    assert precios.get_lista(999) is None


def test_reset_deja_principal_de_nuevo(precios):
    precios.crear_lista("NP Calle 13")
    precios.reset()
    assert [l.nombre for l in precios.listar_listas()] == ["Principal"]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_listas_precios.py -q`
Expected: FAIL — `AttributeError: 'PreciosDB' object has no attribute 'listar_listas'`

- [ ] **Step 3: Añadir la constante en `apu_tool/config.py`**

Justo debajo del bloque de `PUBLIC_PRICE_SOURCES` / `classify_price_source` (después de la línea 55):

```python
# ---------------------------------------------------------------------------
# Listas de precios. Una lista = una tarifa (la del catálogo, o la de una obra
# de No Previstos). La lista 1 es SIEMPRE 'Principal': es el DEFAULT de la
# columna insumo_precios.lista_id y el ancla del invariante
#   lista_id = None  ==  Principal  ==  comportamiento histórico.
# ---------------------------------------------------------------------------
LISTA_PRINCIPAL_ID = 1
```

- [ ] **Step 4: Añadir el modelo en `apu_tool/nucleo/models.py`**

Después del dataclass `Carpeta` (línea 83):

```python
@dataclass(frozen=True)
class ListaPrecios:
    """Una tarifa. 'Principal' (id 1) es la del catálogo; las demás son de obra (NP)."""
    id: Optional[int]
    nombre: str
    creada_en: str                # ISO 8601 (YYYY-MM-DD)
    creado_por: Optional[str] = None
```

- [ ] **Step 5: Actualizar `db/precios.sql`**

`lista_precios` debe crearse **antes** de `insumo_precios` (la FK la referencia). Insertar el bloque justo después del `CREATE INDEX ... idx_insumo_cod` (línea 17):

```sql
-- Una lista = una tarifa. La id 1 es SIEMPRE 'Principal' (la siembra init_schema).
CREATE TABLE IF NOT EXISTS lista_precios (
    id         INTEGER PRIMARY KEY,
    nombre     TEXT NOT NULL UNIQUE,
    creada_en  TEXT NOT NULL,      -- ISO (YYYY-MM-DD)
    creado_por TEXT                -- user_id (NULL = sistema/migración)
);
```

Y en `CREATE TABLE insumo_precios`, añadir la columna después de `creado_por`:

```sql
    creado_por    TEXT,          -- user_id de quien fijó el precio (NULL = histórico/seed)
    lista_id      INTEGER NOT NULL DEFAULT 1 REFERENCES lista_precios(id),
    -- NOTA (drift vs. base migrada): SQLite no permite ADD COLUMN con NOT NULL DEFAULT
    -- *y* REFERENCES a la vez, así que una base preexistente recibe la columna SIN la
    -- FK (ver PreciosDB.init_schema). Misma clase de drift ya anotada en db/pg/precios.sql.
    FOREIGN KEY (insumo_id) REFERENCES insumos(id)
```

Y añadir el índice al final del archivo:

```sql
CREATE INDEX IF NOT EXISTS idx_precio_ins_lista ON insumo_precios(insumo_id, lista_id, vigente);
```

- [ ] **Step 6: Migración y semilla en `PreciosDB.init_schema` / `reset`**

En `apu_tool/datos/precios_db.py`, reemplazar `init_schema` y `reset` (líneas 45-60):

```python
    def init_schema(self) -> None:
        with self.connect() as conn:
            conn.executescript(_load_schema())
            cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumo_precios)").fetchall()}
            if "creado_por" not in cols:
                conn.execute("ALTER TABLE insumo_precios ADD COLUMN creado_por TEXT")
            if "lista_id" not in cols:
                # Sin REFERENCES: SQLite no lo admite junto con NOT NULL DEFAULT (drift
                # declarado en db/precios.sql). El DEFAULT deja todo lo existente en
                # Principal, así que no hay backfill que escribir.
                conn.execute(
                    "ALTER TABLE insumo_precios ADD COLUMN lista_id INTEGER NOT NULL DEFAULT 1")
                conn.execute("CREATE INDEX IF NOT EXISTS idx_precio_ins_lista "
                             "ON insumo_precios(insumo_id, lista_id, vigente)")
            insumos_cols = {r["name"] for r in conn.execute("PRAGMA table_info(insumos)").fetchall()}
            if "oculto" not in insumos_cols:
                conn.execute("ALTER TABLE insumos ADD COLUMN oculto INTEGER NOT NULL DEFAULT 0")
            self._asegurar_principal(conn)

    def reset(self) -> None:
        """Reconstruye el esquema desde cero (descarta y recrea desde db/precios.sql)."""
        with self.connect() as conn:
            for t in ("insumo_precios", "insumos", "lista_precios", "meta"):
                conn.execute(f"DROP TABLE IF EXISTS {t}")
            conn.executescript(_load_schema())
            self._asegurar_principal(conn)

    def _asegurar_principal(self, conn) -> None:
        """Siembra la lista Principal (id 1) si falta. Idempotente."""
        r = conn.execute("SELECT id FROM lista_precios WHERE id=?",
                         (config.LISTA_PRINCIPAL_ID,)).fetchone()
        if r is None:
            conn.execute(
                "INSERT INTO lista_precios (id, nombre, creada_en, creado_por) "
                "VALUES (?, 'Principal', ?, NULL)",
                (config.LISTA_PRINCIPAL_ID, date.today().isoformat()))
```

- [ ] **Step 7: CRUD de listas en `PreciosDB`**

Añadir al final de la sección de escritura (después de `todos_no_ocultos`, línea 184), e importar `ListaPrecios` en la línea 17 (`from apu_tool.nucleo.models import Insumo, ListaPrecios`):

```python
    # ---- listas de precios ----
    @staticmethod
    def _limpiar_nombre_lista(nombre: str) -> str:
        limpio = (nombre or "").strip()[:80].strip()
        if not limpio:
            raise ValueError("El nombre de la lista no puede estar vacío.")
        return limpio

    @staticmethod
    def _fila_a_lista(r) -> ListaPrecios:
        return ListaPrecios(id=r["id"], nombre=r["nombre"], creada_en=r["creada_en"],
                            creado_por=r["creado_por"])

    def listar_listas(self) -> list[ListaPrecios]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM lista_precios "
                "ORDER BY id").fetchall()
        return [self._fila_a_lista(r) for r in rows]

    def get_lista(self, lista_id: int) -> Optional[ListaPrecios]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM lista_precios WHERE id=?",
                (int(lista_id),)).fetchone()
        return self._fila_a_lista(r) if r else None

    def crear_lista(self, nombre: str, creado_por: Optional[str] = None, conn=None) -> int:
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            return self._crear_lista(conn, limpio, creado_por)
        with self.connect() as c:
            return self._crear_lista(c, limpio, creado_por)

    def _crear_lista(self, conn, nombre: str, creado_por: Optional[str]) -> int:
        if conn.execute("SELECT 1 FROM lista_precios WHERE UPPER(nombre)=UPPER(?)",
                        (nombre,)).fetchone():
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        cur = conn.execute(
            "INSERT INTO lista_precios (nombre, creada_en, creado_por) VALUES (?,?,?)",
            (nombre, date.today().isoformat(), creado_por))
        return int(cur.lastrowid)

    def renombrar_lista(self, lista_id: int, nombre: str, conn=None) -> None:
        if int(lista_id) == config.LISTA_PRINCIPAL_ID:
            raise ValueError("La lista Principal no se puede renombrar.")
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            self._renombrar_lista(conn, int(lista_id), limpio)
            return
        with self.connect() as c:
            self._renombrar_lista(c, int(lista_id), limpio)

    def _renombrar_lista(self, conn, lista_id: int, nombre: str) -> None:
        if conn.execute("SELECT 1 FROM lista_precios WHERE id=?", (lista_id,)).fetchone() is None:
            raise ValueError(f"No existe la lista de precios id={lista_id}.")
        if conn.execute("SELECT 1 FROM lista_precios WHERE UPPER(nombre)=UPPER(?) AND id<>?",
                        (nombre, lista_id)).fetchone():
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        conn.execute("UPDATE lista_precios SET nombre=? WHERE id=?", (nombre, lista_id))
```

- [ ] **Step 8: Correr el test nuevo y la suite completa**

Run: `python -m pytest tests/test_listas_precios.py -q`
Expected: PASS (10 passed)

Run: `python -m pytest tests/ -q`
Expected: PASS — la suite existente no se tocó y debe seguir verde. Si algo falla aquí, el bug está en la migración, no en el test.

- [ ] **Step 9: Commit**

```bash
git add apu_tool/config.py apu_tool/nucleo/models.py db/precios.sql apu_tool/datos/precios_db.py tests/test_listas_precios.py
git commit -m "feat(precios): tabla lista_precios con semilla Principal y CRUD (SQLite)"
```

---

### Task 2: `lista_id` en las lecturas y escrituras de precios (SQLite)

**Files:**
- Modify: `apu_tool/nucleo/models.py` (campo `Insumo.sin_precio`)
- Modify: `apu_tool/datos/precios_db.py`
- Test: `tests/test_precios_por_lista.py` (crear)

**Interfaces:**
- Consumes: `config.LISTA_PRINCIPAL_ID`, `PreciosDB.crear_lista` (Task 1).
- Produces (todas con `lista_id: Optional[int] = None` **al final**, `None` ⇒ Principal):
  - `get_candidatos(codigo, lista_id=None) -> list[Insumo]`
  - `get_candidatos_bulk(codigos, lista_id=None) -> dict[str, list[Insumo]]`
  - `get_insumo_por_id(insumo_id, lista_id=None) -> Optional[Insumo]`
  - `set_precio_por_id(insumo_id, precio, fuente="", fecha=None, conn=None, creado_por=None, lista_id=None) -> None`
  - `crear_insumo(insumo, conn=None, creado_por=None, lista_id=None) -> int`
  - `price_history(codigo, nombre=None, lista_id=None) -> list[dict]`
  - `fuentes(lista_id=None) -> list[str]`
  - `list_insumos(q=None, grupo=None, fuente=None, clasificacion=None, limit=100, offset=0, lista_id=None, sin_precio=False) -> tuple[list[Insumo], int]`
  - `Insumo.sin_precio: bool = False` — `True` ⇔ no hay fila de precio vigente en la lista leída.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_precios_por_lista.py`:

```python
"""Precios por lista: dos tarifas vivas a la vez sobre el mismo catálogo."""
import pytest

from apu_tool import config
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.nucleo.models import Insumo


@pytest.fixture()
def precios(tmp_path):
    p = PreciosDB(tmp_path / "precios.db")
    p.init_schema()
    p.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"),
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"),
    ])
    return p


@pytest.fixture()
def np(precios):
    return precios.crear_lista("NP Calle 13")


def test_seed_queda_en_principal(precios):
    assert precios.get_candidatos("6140")[0].precio == 3500.0
    assert precios.get_candidatos("6140", lista_id=config.LISTA_PRINCIPAL_ID)[0].precio == 3500.0


def test_precio_en_np_no_toca_principal(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    assert precios.get_candidatos("6140", lista_id=np)[0].precio == 4200.0
    assert precios.get_candidatos("6140")[0].precio == 3500.0          # Principal intacto


def test_vigente_es_por_lista(precios, np):
    iid = precios.get_candidatos("9")[0].id
    precios.set_precio_por_id(iid, 1100.0, "ACTA NP", lista_id=np)
    precios.set_precio_por_id(iid, 950.0, "COMPRAS 2026")               # Principal
    assert precios.get_insumo_por_id(iid, lista_id=np).precio == 1100.0
    assert precios.get_insumo_por_id(iid).precio == 950.0


def test_insumo_sin_precio_en_la_lista(precios, np):
    ins = precios.get_candidatos("6140", lista_id=np)[0]
    assert ins.precio == 0.0 and ins.sin_precio is True
    assert precios.get_candidatos("6140")[0].sin_precio is False


def test_bulk_respeta_la_lista(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    bulk = precios.get_candidatos_bulk(["6140", "9"], lista_id=np)
    assert bulk["6140"][0].precio == 4200.0
    assert bulk["9"][0].sin_precio is True


def test_price_history_filtra_por_lista(precios, np):
    iid = precios.get_candidatos("9")[0].id
    precios.set_precio_por_id(iid, 1100.0, "ACTA NP", lista_id=np)
    assert len(precios.price_history("9")) == 1                          # solo el del seed
    assert len(precios.price_history("9", lista_id=np)) == 1
    assert precios.price_history("9", lista_id=np)[0]["precio"] == 1100.0


def test_crear_insumo_en_np_no_existe_en_principal(precios, np):
    iid = precios.crear_insumo(
        Insumo("NP-INS-1", "GEOTEXTIL NT 2500", "M2", "MATERIAL", 8000.0, "ACTA NP"),
        lista_id=np)
    assert precios.get_insumo_por_id(iid, lista_id=np).precio == 8000.0
    assert precios.get_insumo_por_id(iid).sin_precio is True             # sin precio en Principal


def test_list_insumos_devuelve_todo_el_catalogo_con_precio_nulo(precios, np):
    items, total = precios.list_insumos(lista_id=np, limit=50, offset=0)
    assert total == 2                                                     # catálogo completo
    assert all(i.sin_precio for i in items)


def test_list_insumos_filtro_sin_precio(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    items, total = precios.list_insumos(lista_id=np, sin_precio=True, limit=50, offset=0)
    assert total == 1 and items[0].codigo == "9"


def test_sin_precio_es_excluyente_con_fuente_y_clasificacion(precios, np):
    with pytest.raises(ValueError):
        precios.list_insumos(lista_id=np, sin_precio=True, fuente="ACTA NP")
    with pytest.raises(ValueError):
        precios.list_insumos(lista_id=np, sin_precio=True, clasificacion="interno")


def test_fuentes_por_lista(precios, np):
    iid = precios.get_candidatos("6140")[0].id
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    assert precios.fuentes(lista_id=np) == ["ACTA NP"]
    assert "ACTA NP" not in precios.fuentes()
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_precios_por_lista.py -q`
Expected: FAIL — `TypeError: get_candidatos() got an unexpected keyword argument 'lista_id'`

- [ ] **Step 3: Añadir `sin_precio` al modelo `Insumo`**

En `apu_tool/nucleo/models.py`, dataclass `Insumo` (línea 24), añadir el campo tras `id`:

```python
@dataclass(frozen=True)
class Insumo:
    codigo: str
    nombre: str
    unidad: str
    grupo: str
    precio: float
    fuente_precio: str
    id: Optional[int] = None    # id interno del catálogo (None si aún no persistido)
    # True = NO hay fila de precio vigente en la lista con la que se leyó este insumo.
    # Distingue "sin tarifa en esta lista" de un $0 genuino, que la regla de negocio
    # prohíbe y que las alertas de costeo deben seguir mostrando.
    sin_precio: bool = False
```

- [ ] **Step 4: Propagar `lista_id` en `precios_db.py`**

Reemplazar cada método por su versión con lista. `_insertar_precio_vigente` (línea 127):

```python
    def _insertar_precio_vigente(self, conn: sqlite3.Connection, insumo_id: int, precio: float,
                                fuente: str, fecha: str, creado_por: Optional[str] = None,
                                lista_id: Optional[int] = None) -> None:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=? AND lista_id=?",
                     (int(insumo_id), lid))
        conn.execute(
            "INSERT INTO insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por, lista_id) "
            "VALUES (?,?,?,?,?,1,?,?)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha, creado_por, lid))
```

`crear_insumo` / `_crear_insumo` (líneas 85-115):

```python
    def crear_insumo(self, insumo: Insumo, conn: Optional[sqlite3.Connection] = None,
                     creado_por: Optional[str] = None, lista_id: Optional[int] = None) -> int:
        if not str(insumo.codigo or "").strip() or not str(insumo.nombre or "").strip():
            raise ValueError("El insumo necesita código y nombre.")
        if conn is not None:
            return self._crear_insumo(conn, insumo, creado_por, lista_id)
        with self.connect() as c:
            return self._crear_insumo(c, insumo, creado_por, lista_id)

    def _crear_insumo(self, conn, insumo: Insumo, creado_por: Optional[str],
                      lista_id: Optional[int] = None) -> int:
        nombre_norm = normalizar(insumo.nombre)
        hoy = date.today().isoformat()
        existe = conn.execute(
            "SELECT 1 FROM insumos WHERE codigo=? AND nombre_norm=?",
            (str(insumo.codigo), nombre_norm)).fetchone()
        if existe:
            raise ValueError(
                f"Ya existe un insumo con código {insumo.codigo} y ese nombre.")
        cur = conn.execute(
            "INSERT INTO insumos (codigo, nombre, nombre_norm, unidad, grupo) "
            "VALUES (?,?,?,?,?)",
            (str(insumo.codigo), insumo.nombre, nombre_norm, insumo.unidad, insumo.grupo))
        iid = int(cur.lastrowid)
        self._insertar_precio_vigente(conn, iid, insumo.precio, insumo.fuente_precio, hoy,
                                      creado_por, lista_id)
        return iid
```

`set_precio_por_id` / `_set_precio_por_id` (líneas 148-162):

```python
    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None, conn: Optional[sqlite3.Connection] = None,
                          creado_por: Optional[str] = None,
                          lista_id: Optional[int] = None) -> None:
        fecha = fecha or date.today().isoformat()
        if conn is not None:
            self._set_precio_por_id(conn, insumo_id, precio, fuente, fecha, creado_por, lista_id)
            return
        with self.connect() as c:
            self._set_precio_por_id(c, insumo_id, precio, fuente, fecha, creado_por, lista_id)

    def _set_precio_por_id(self, conn, insumo_id, precio, fuente, fecha, creado_por,
                           lista_id=None) -> None:
        r = conn.execute("SELECT id FROM insumos WHERE id=?", (int(insumo_id),)).fetchone()
        if r is None:
            raise ValueError(f"No existe el insumo id={insumo_id}.")
        self._insertar_precio_vigente(conn, int(insumo_id), precio, fuente, fecha,
                                      creado_por, lista_id)
```

`_fila_a_insumo` y los tres lectores por identidad (líneas 187-227):

```python
    def _fila_a_insumo(self, r) -> Insumo:
        # precio es NOT NULL en la tabla: un NULL aquí solo puede venir del LEFT JOIN,
        # o sea "no hay precio vigente en esta lista" (≠ un $0 genuino).
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"],
                      sin_precio=r["precio"] is None)

    _SELECT_INSUMO = (
        "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
        "FROM insumos i LEFT JOIN insumo_precios p "
        "  ON p.insumo_id = i.id AND p.vigente = 1 AND p.lista_id = ? ")

    def get_candidatos(self, codigo: str, lista_id: Optional[int] = None) -> list[Insumo]:
        """Todos los insumos con ese código, con su precio vigente EN `lista_id`."""
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        with self.connect() as conn:
            rows = conn.execute(
                self._SELECT_INSUMO + "WHERE i.codigo = ? ORDER BY i.id",
                (lid, str(codigo))).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_candidatos_bulk(self, codigos, lista_id: Optional[int] = None) -> dict:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        codes = [c for c in dict.fromkeys(str(x) for x in codigos if x)]
        out: dict[str, list[Insumo]] = {c: [] for c in codes}
        if not codes:
            return out
        with self.connect() as conn:
            for i in range(0, len(codes), 800):          # límite de placeholders de SQLite
                chunk = codes[i:i + 800]
                ph = ",".join("?" * len(chunk))
                rows = conn.execute(
                    self._SELECT_INSUMO + f"WHERE i.codigo IN ({ph}) ORDER BY i.codigo, i.id",
                    [lid] + chunk).fetchall()
                for r in rows:
                    out[r["codigo"]].append(self._fila_a_insumo(r))
        return out

    def get_insumo_por_id(self, insumo_id: int,
                          lista_id: Optional[int] = None) -> Optional[Insumo]:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        with self.connect() as conn:
            r = conn.execute(self._SELECT_INSUMO + "WHERE i.id = ?",
                             (lid, int(insumo_id))).fetchone()
        return self._fila_a_insumo(r) if r else None
```

`price_history` (línea 229):

```python
    def price_history(self, codigo: str, nombre: Optional[str] = None,
                      lista_id: Optional[int] = None) -> list[dict]:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        with self.connect() as conn:
            q = ("SELECT p.precio, p.fuente, p.clasificacion, p.fecha, p.vigente "
                 "FROM insumo_precios p JOIN insumos i ON i.id = p.insumo_id "
                 "WHERE i.codigo = ? AND p.lista_id = ?")
            params: list = [str(codigo), lid]
            if nombre is not None:
                q += " AND i.nombre_norm = ?"
                params.append(normalizar(nombre))
            q += " ORDER BY p.id"
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]
```

`list_insumos` (línea 242) — ojo con el orden de los parámetros: el de la lista va en el `JOIN`, así que es el **primero**:

```python
    def list_insumos(self, q=None, grupo=None, fuente=None,
                     clasificacion: Optional[str] = None,
                     limit: int = 100, offset: int = 0,
                     lista_id: Optional[int] = None,
                     sin_precio: bool = False) -> tuple[list[Insumo], int]:
        """Catálogo COMPLETO con el precio vigente en `lista_id`. Los insumos sin
        tarifa en esa lista vienen igual, con precio 0 y `sin_precio=True`: la lista
        decide QUÉ PRECIO se lee, no QUÉ INSUMOS existen."""
        if sin_precio and (fuente or clasificacion):
            raise ValueError(
                "El filtro «sin precio en esta lista» no se puede combinar con "
                "fuente ni clasificación: son atributos de un precio que no existe.")
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        base = ("FROM insumos i LEFT JOIN insumo_precios p "
                "ON p.insumo_id = i.id AND p.vigente = 1 AND p.lista_id = ?")
        where, params = ["i.oculto = 0"], [lid]
        if sin_precio:
            where.append("p.id IS NULL")
        if q:
            where.append("(i.nombre_norm LIKE ? OR UPPER(i.codigo) LIKE ?)")
            like = f"%{normalizar(q)}%"
            params += [like, f"%{normalizar(q)}%"]
        if grupo:
            where.append("i.grupo = ?")
            params.append(grupo)
        if fuente:
            where.append("p.fuente = ?")
            params.append(fuente)
        if clasificacion == "publico":
            placeholders = ",".join("?" * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"UPPER(p.fuente) IN ({placeholders})")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        elif clasificacion == "interno":
            placeholders = ",".join("?" * len(config.PUBLIC_PRICE_SOURCES))
            where.append(f"(p.fuente IS NULL OR UPPER(p.fuente) NOT IN ({placeholders}))")
            params += [s.upper() for s in config.PUBLIC_PRICE_SOURCES]
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) {base}{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                f"{base}{wsql} ORDER BY i.codigo, i.id LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)
```

`fuentes` (línea 282):

```python
    def fuentes(self, lista_id: Optional[int] = None) -> list[str]:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT p.fuente FROM insumo_precios p "
                "JOIN insumos i ON i.id = p.insumo_id AND i.oculto = 0 "
                "WHERE p.vigente = 1 AND p.lista_id = ? "
                "  AND p.fuente IS NOT NULL AND p.fuente <> '' "
                "ORDER BY p.fuente", (lid,)).fetchall()
        return [r["fuente"] for r in rows]
```

`search_insumos` y `search_insumos_por_palabras` llaman a `get_insumo_por_id(r["id"])` sin lista: se quedan **igual** (búsqueda por texto en Principal). No se tocan.

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_precios_por_lista.py -q`
Expected: PASS (11 passed)

Run: `python -m pytest tests/ -q`
Expected: PASS — toda la suite existente sigue verde sin haberla modificado.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/nucleo/models.py apu_tool/datos/precios_db.py tests/test_precios_por_lista.py
git commit -m "feat(precios): precio vigente por lista en el backend SQLite"
```

---

### Task 3: Espejo Postgres y contrato del `Protocol`

**Files:**
- Modify: `db/pg/precios.sql`
- Modify: `apu_tool/datos/pg/precios_pg.py`
- Modify: `apu_tool/datos/repositorio.py`
- Test: `tests/test_repositorios_contrato.py` (añadir casos), `tests/test_paridad_backends.py` (crear)

**Interfaces:**
- Consumes: todas las firmas producidas en las Tasks 1 y 2.
- Produces: `PreciosPg` con **exactamente** las mismas firmas públicas que `PreciosDB`; `RepositorioPrecios` actualizado.

- [ ] **Step 1: Escribir el test de paridad que falla**

Crear `tests/test_paridad_backends.py`:

```python
"""Los dos backends de precios son espejo 1:1. Sin Postgres real: se comparan firmas.

Es el guardia barato contra el drift: si alguien añade un parámetro en SQLite y se
olvida de Postgres, esto falla en CI aunque no haya TEST_DATABASE_URL.
"""
import inspect

from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.pg.precios_pg import PreciosPg
from apu_tool.datos.repositorio import RepositorioPrecios


def _publicos(cls) -> dict:
    return {n: m for n, m in inspect.getmembers(cls, inspect.isfunction)
            if not n.startswith("_")}


def test_mismos_metodos_publicos():
    assert set(_publicos(PreciosDB)) == set(_publicos(PreciosPg))


def test_mismos_nombres_de_parametros():
    sq, pg = _publicos(PreciosDB), _publicos(PreciosPg)
    for nombre in sorted(sq):
        p_sq = list(inspect.signature(sq[nombre]).parameters)
        p_pg = list(inspect.signature(pg[nombre]).parameters)
        assert p_sq == p_pg, f"{nombre}: SQLite {p_sq} != Postgres {p_pg}"


def test_protocol_cubre_los_metodos_de_listas():
    for metodo in ("listar_listas", "get_lista", "crear_lista", "renombrar_lista"):
        assert hasattr(RepositorioPrecios, metodo), metodo


def test_ambos_backends_satisfacen_el_protocol():
    # runtime_checkable comprueba presencia de métodos (no firmas); la firma la cubre
    # test_mismos_nombres_de_parametros.
    assert isinstance(PreciosDB.__new__(PreciosDB), RepositorioPrecios)
    assert isinstance(PreciosPg.__new__(PreciosPg), RepositorioPrecios)
```

Añadir al final de `tests/test_repositorios_contrato.py` (la batería que corre contra **ambos** backends cuando hay `TEST_DATABASE_URL`):

```python
def test_lista_principal_sembrada(repos):
    from apu_tool import config
    precios, _ = repos
    listas = precios.listar_listas()
    assert [(l.id, l.nombre) for l in listas] == [(config.LISTA_PRINCIPAL_ID, "Principal")]


def test_crear_y_renombrar_lista(repos):
    precios, _ = repos
    lid = precios.crear_lista("NP Calle 13", creado_por="u1")
    assert precios.get_lista(lid).nombre == "NP Calle 13"
    precios.renombrar_lista(lid, "NP Calle 13 - Acta 2")
    assert precios.get_lista(lid).nombre == "NP Calle 13 - Acta 2"
    with pytest.raises(ValueError):
        precios.crear_lista("np calle 13 - acta 2")     # duplicado, case-insensitive


def test_renombrar_principal_prohibido(repos):
    from apu_tool import config
    precios, _ = repos
    with pytest.raises(ValueError):
        precios.renombrar_lista(config.LISTA_PRINCIPAL_ID, "Otra")


def test_precio_por_lista_no_contamina_principal(repos):
    precios, _ = repos
    iid = precios.crear_insumo(
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"))
    np = precios.crear_lista("NP Calle 13")
    precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    assert precios.get_insumo_por_id(iid, lista_id=np).precio == 4200.0
    assert precios.get_insumo_por_id(iid).precio == 3500.0
    assert precios.get_candidatos_bulk(["6140"], lista_id=np)["6140"][0].precio == 4200.0


def test_sin_precio_en_la_lista(repos):
    precios, _ = repos
    precios.crear_insumo(
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"))
    np = precios.crear_lista("NP Calle 13")
    assert precios.get_candidatos("9", lista_id=np)[0].sin_precio is True
    items, total = precios.list_insumos(lista_id=np, sin_precio=True, limit=50, offset=0)
    assert total == 1 and items[0].codigo == "9"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_paridad_backends.py tests/test_repositorios_contrato.py -q`
Expected: FAIL — `test_mismos_nombres_de_parametros` reporta `get_candidatos: SQLite ['self','codigo','lista_id'] != Postgres ['self','codigo']`

- [ ] **Step 3: Actualizar `db/pg/precios.sql`**

Insertar **antes** del `CREATE TABLE precios.insumo_precios` (para que la FK resuelva):

```sql
CREATE TABLE IF NOT EXISTS precios.lista_precios (
    -- BY DEFAULT (no ALWAYS): la semilla de abajo inserta el id 1 explícitamente.
    id         BIGINT GENERATED BY DEFAULT AS IDENTITY PRIMARY KEY,
    nombre     TEXT NOT NULL UNIQUE,
    creada_en  TEXT NOT NULL,
    creado_por TEXT
);

INSERT INTO precios.lista_precios (id, nombre, creada_en)
SELECT 1, 'Principal', to_char(now(), 'YYYY-MM-DD')
WHERE NOT EXISTS (SELECT 1 FROM precios.lista_precios WHERE id = 1);

SELECT setval(pg_get_serial_sequence('precios.lista_precios', 'id'),
              GREATEST((SELECT COALESCE(MAX(id), 1) FROM precios.lista_precios), 1));
```

Y después del `CREATE TABLE precios.insumo_precios`, junto al `ALTER TABLE ... oculto` existente:

```sql
ALTER TABLE precios.insumo_precios
    ADD COLUMN IF NOT EXISTS lista_id BIGINT NOT NULL DEFAULT 1
    REFERENCES precios.lista_precios(id);

CREATE INDEX IF NOT EXISTS idx_precio_ins_lista
    ON precios.insumo_precios(insumo_id, lista_id, vigente);
```

Añadir la columna también al `CREATE TABLE` canónico de `precios.insumo_precios`
(`lista_id BIGINT NOT NULL DEFAULT 1 REFERENCES precios.lista_precios(id)`), para que una
base nueva no dependa del `ALTER`.

- [ ] **Step 4: Portar `precios_pg.py`**

Aplicar las mismas transformaciones de la Task 2, con dialecto `%s` y tablas calificadas.
Importar `ListaPrecios` (línea 14) y añadir, junto a `todos_no_ocultos`:

```python
    # ---- listas de precios ----
    @staticmethod
    def _limpiar_nombre_lista(nombre: str) -> str:
        limpio = (nombre or "").strip()[:80].strip()
        if not limpio:
            raise ValueError("El nombre de la lista no puede estar vacío.")
        return limpio

    @staticmethod
    def _fila_a_lista(r) -> ListaPrecios:
        return ListaPrecios(id=r["id"], nombre=r["nombre"], creada_en=r["creada_en"],
                            creado_por=r["creado_por"])

    def listar_listas(self) -> list[ListaPrecios]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM precios.lista_precios "
                "ORDER BY id").fetchall()
        return [self._fila_a_lista(r) for r in rows]

    def get_lista(self, lista_id: int) -> Optional[ListaPrecios]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT id, nombre, creada_en, creado_por FROM precios.lista_precios "
                "WHERE id=%s", (int(lista_id),)).fetchone()
        return self._fila_a_lista(r) if r else None

    def crear_lista(self, nombre: str, creado_por: Optional[str] = None, conn=None) -> int:
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            return self._crear_lista(conn, limpio, creado_por)
        with self.cx.connection() as c:
            return self._crear_lista(c, limpio, creado_por)

    def _crear_lista(self, conn, nombre: str, creado_por: Optional[str]) -> int:
        if conn.execute("SELECT 1 FROM precios.lista_precios WHERE UPPER(nombre)=UPPER(%s)",
                        (nombre,)).fetchone():
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        cur = conn.execute(
            "INSERT INTO precios.lista_precios (nombre, creada_en, creado_por) "
            "VALUES (%s,%s,%s) RETURNING id",
            (nombre, date.today().isoformat(), creado_por))
        return int(cur.fetchone()["id"])

    def renombrar_lista(self, lista_id: int, nombre: str, conn=None) -> None:
        if int(lista_id) == config.LISTA_PRINCIPAL_ID:
            raise ValueError("La lista Principal no se puede renombrar.")
        limpio = self._limpiar_nombre_lista(nombre)
        if conn is not None:
            self._renombrar_lista(conn, int(lista_id), limpio)
            return
        with self.cx.connection() as c:
            self._renombrar_lista(c, int(lista_id), limpio)

    def _renombrar_lista(self, conn, lista_id: int, nombre: str) -> None:
        if conn.execute("SELECT 1 FROM precios.lista_precios WHERE id=%s",
                        (lista_id,)).fetchone() is None:
            raise ValueError(f"No existe la lista de precios id={lista_id}.")
        if conn.execute(
                "SELECT 1 FROM precios.lista_precios WHERE UPPER(nombre)=UPPER(%s) AND id<>%s",
                (nombre, lista_id)).fetchone():
            raise ValueError(f"Ya existe una lista de precios llamada «{nombre}».")
        conn.execute("UPDATE precios.lista_precios SET nombre=%s WHERE id=%s",
                     (nombre, lista_id))
```

Y las versiones con lista de los métodos existentes:

```python
    _SELECT_INSUMO = (
        "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
        "FROM precios.insumos i LEFT JOIN precios.insumo_precios p "
        "  ON p.insumo_id = i.id AND p.vigente = 1 AND p.lista_id = %s ")

    def _fila_a_insumo(self, r) -> Insumo:
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"],
                      sin_precio=r["precio"] is None)

    def _insertar_precio_vigente(self, conn, insumo_id: int, precio: float,
                                 fuente: str, fecha: str, creado_por: Optional[str] = None,
                                 lista_id: Optional[int] = None) -> None:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        conn.execute(
            "UPDATE precios.insumo_precios SET vigente=0 WHERE insumo_id=%s AND lista_id=%s",
            (int(insumo_id), lid))
        conn.execute(
            "INSERT INTO precios.insumo_precios "
            "(insumo_id, precio, fuente, clasificacion, fecha, vigente, creado_por, lista_id) "
            "VALUES (%s,%s,%s,%s,%s,1,%s,%s)",
            (int(insumo_id), float(precio), fuente,
             config.classify_price_source(fuente), fecha, creado_por, lid))

    def get_candidatos(self, codigo: str, lista_id: Optional[int] = None) -> list[Insumo]:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        with self.cx.connection() as conn:
            rows = conn.execute(
                self._SELECT_INSUMO + "WHERE i.codigo = %s ORDER BY i.id",
                (lid, str(codigo))).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_candidatos_bulk(self, codigos, lista_id: Optional[int] = None) -> dict:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        codes = [c for c in dict.fromkeys(str(x) for x in codigos if x)]
        out: dict[str, list[Insumo]] = {c: [] for c in codes}
        if not codes:
            return out
        with self.cx.connection() as conn:
            rows = conn.execute(
                self._SELECT_INSUMO + "WHERE i.codigo = ANY(%s) ORDER BY i.codigo, i.id",
                (lid, codes)).fetchall()
        for r in rows:
            out[r["codigo"]].append(self._fila_a_insumo(r))
        return out

    def get_insumo_por_id(self, insumo_id: int,
                          lista_id: Optional[int] = None) -> Optional[Insumo]:
        lid = int(lista_id or config.LISTA_PRINCIPAL_ID)
        with self.cx.connection() as conn:
            r = conn.execute(self._SELECT_INSUMO + "WHERE i.id = %s",
                             (lid, int(insumo_id))).fetchone()
        return self._fila_a_insumo(r) if r else None
```

`crear_insumo`, `_crear_insumo`, `set_precio_por_id`, `_set_precio_por_id`, `price_history`,
`list_insumos` y `fuentes`: **mismas firmas y misma lógica** que en la Task 2, cambiando
`?` por `%s`, `i.oculto = 0` por `i.oculto = FALSE`, y `COUNT(*)` por `COUNT(*) AS n`
con `.fetchone()["n"]`. En `list_insumos`, el parámetro de la lista va **primero** en
`params` (está en el `JOIN`), igual que en SQLite.

- [ ] **Step 5: Actualizar el `Protocol` en `apu_tool/datos/repositorio.py`**

Importar `ListaPrecios` (línea 11) y reemplazar las firmas afectadas dentro de
`RepositorioPrecios`:

```python
    def crear_insumo(self, insumo: Insumo, conn=None, creado_por: Optional[str] = None,
                     lista_id: Optional[int] = None) -> int: ...
    def get_candidatos(self, codigo: str, lista_id: Optional[int] = None) -> list[Insumo]: ...
    def get_candidatos_bulk(self, codigos: Iterable[str],
                            lista_id: Optional[int] = None) -> dict[str, list[Insumo]]:
        """Como get_candidatos pero para muchos códigos en UNA consulta (optimización).
        Devuelve {codigo: [candidatos...]} con la misma semántica que llamarlo 1x1."""
        ...
    def get_insumo_por_id(self, insumo_id: int,
                          lista_id: Optional[int] = None) -> Optional[Insumo]: ...
    def set_precio_por_id(self, insumo_id: int, precio: float, fuente: str = "",
                          fecha: Optional[str] = None, conn=None,
                          creado_por: Optional[str] = None,
                          lista_id: Optional[int] = None) -> None: ...
    def price_history(self, codigo: str, nombre: Optional[str] = None,
                      lista_id: Optional[int] = None) -> list[dict]: ...
    def list_insumos(self, q=None, grupo=None, fuente=None,
                     clasificacion: Optional[str] = None,
                     limit: int = 100, offset: int = 0,
                     lista_id: Optional[int] = None,
                     sin_precio: bool = False) -> tuple[list[Insumo], int]:
        """Catálogo COMPLETO con el precio vigente en `lista_id` (None = Principal).
        Los insumos sin tarifa en esa lista vienen con precio 0 y `sin_precio=True`.
        `sin_precio=True` es excluyente con `fuente` y `clasificacion` (ValueError)."""
        ...
    def fuentes(self, lista_id: Optional[int] = None) -> list[str]: ...
```

Y añadir el bloque de listas justo antes de `descripcion()`:

```python
    # --- listas de precios (tarifas). La id config.LISTA_PRINCIPAL_ID es 'Principal' ---
    def listar_listas(self) -> list[ListaPrecios]: ...
    def get_lista(self, lista_id: int) -> Optional[ListaPrecios]: ...
    def crear_lista(self, nombre: str, creado_por: Optional[str] = None,
                    conn=None) -> int:
        """Crea una lista. ValueError si el nombre está vacío o ya existe (sin
        distinguir mayúsculas)."""
        ...
    def renombrar_lista(self, lista_id: int, nombre: str, conn=None) -> None:
        """ValueError si la lista no existe, si el nombre choca, o si es la Principal
        (intocable: es el ancla del invariante lista_id=None == Principal)."""
        ...
```

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_paridad_backends.py tests/test_repositorios_contrato.py -q`
Expected: PASS

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add db/pg/precios.sql apu_tool/datos/pg/precios_pg.py apu_tool/datos/repositorio.py tests/test_paridad_backends.py tests/test_repositorios_contrato.py
git commit -m "feat(precios): espejo Postgres de las listas de precios + contrato del Protocol"
```

---

### Task 4: Motor de precios atado a una lista y alertas

**Files:**
- Modify: `apu_tool/dominio/pricing.py`
- Modify: `apu_tool/dominio/alertas.py`
- Modify: `apu_tool/nucleo/models.py` (comentario de `calidad_cruce`)
- Test: `tests/test_pricing_lista.py` (crear)

**Interfaces:**
- Consumes: `get_candidatos(codigo, lista_id)`, `get_candidatos_bulk(codigos, lista_id)`, `config.LISTA_PRINCIPAL_ID`.
- Produces:
  - `PricingEngine(almacen, lista_id: Optional[int] = None)` con atributo público `lista_id`.
  - Valor nuevo de `CostedComponent.calidad_cruce`: `"sin_precio_lista"`, con `fuente_precio == "sin precio en lista"` y `precio_unitario == 0.0`.
  - `alertas_costeo` devuelve `"<código> <nombre>: sin precio en la lista"` para ese caso.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_pricing_lista.py`:

```python
"""Costeo contra una lista de precios distinta de Principal.

Decisión de negocio: en una lista NP NO se cae al precio histórico embebido — eso
sería cobrar con la tarifa contractual sin que nadie se entere. Falta el precio ->
$0 con alerta explícita.
"""
import pytest

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.alertas import alertas_costeo
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.nucleo.models import (
    Apu, ApuComponent, AssembledApu, Insumo, LicitacionItem, MatchStatus,
)


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"),
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"),
    ])
    a.apus.insert_apus([Apu("NP-3002", "DEMOLICION MURO", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0),
        ApuComponent("NP-3002", "DIURNO", "9", "CEMENTO GRIS", "KG", 1.0, 800.0),
    ])
    return a


@pytest.fixture()
def np(alm):
    lid = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=lid)
    return lid


def _ensamblado(costed, total) -> AssembledApu:
    item = LicitacionItem("1", "DEMOLICION", "M3", 1.0, 0.0, "DIURNO")
    return AssembledApu(item=item, apu_codigo="NP-3002", apu_nombre="DEMOLICION MURO",
                        unidad="M3", shift="DIURNO", componentes=costed,
                        costo_unitario=total, status=MatchStatus.AUTO, confianza=1.0)


def test_costea_con_el_precio_de_la_lista(alm, np):
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    acero = [c for c in costed if c.insumo_codigo == "6140"][0]
    assert acero.precio_unitario == 4200.0 and acero.fuente_precio == "ACTA NP"
    assert acero.calidad_cruce == "exacto"


def test_sin_precio_en_la_lista_no_cae_al_historico(alm, np):
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    cem = [c for c in costed if c.insumo_codigo == "9"][0]
    assert cem.precio_unitario == 0.0                 # NO 800 (histórico) ni 900 (Principal)
    assert cem.fuente_precio == "sin precio en lista"
    assert cem.calidad_cruce == "sin_precio_lista"
    assert cem.costo == 0


def test_en_principal_si_cae_al_historico(alm):
    # Mismo APU, pero con un insumo huérfano: en Principal el respaldo histórico sigue vivo.
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "0000", "INSUMO INEXISTENTE", "UN", 1.0, 700.0)])
    costed, _ = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    h = [c for c in costed if c.insumo_codigo == "0000"][0]
    assert h.precio_unitario == 700.0 and h.fuente_precio == "histórico"
    assert h.calidad_cruce == "huerfano"


def test_huerfano_en_lista_np_tampoco_usa_historico(alm, np):
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "0000", "INSUMO INEXISTENTE", "UN", 1.0, 700.0)])
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    h = [c for c in costed if c.insumo_codigo == "0000"][0]
    assert h.precio_unitario == 0.0 and h.calidad_cruce == "sin_precio_lista"


def test_none_y_principal_dan_exactamente_lo_mismo(alm):
    a, _ = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    b, _ = PricingEngine(alm, lista_id=config.LISTA_PRINCIPAL_ID).cost_apu("NP-3002", "DIURNO")
    assert [(c.precio_unitario, c.fuente_precio, c.costo, c.calidad_cruce) for c in a] == \
           [(c.precio_unitario, c.fuente_precio, c.costo, c.calidad_cruce) for c in b]


def test_subapu_vacio_en_lista_np_no_usa_historico(alm, np):
    alm.apus.insert_apus([Apu("SUB", "SUB VACIO", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "SUB", "SUB VACIO", "M3", 1.0, 5000.0,
                     tipo="apu", ref_shift="DIURNO")])
    costed, _ = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    sub = [c for c in costed if c.insumo_codigo == "SUB"][0]
    assert sub.precio_unitario == 0.0 and sub.fuente_precio == "sin precio en lista"
    assert sub.calidad_cruce == "apu_vacio"           # el problema real es estructural


def test_dos_motores_con_listas_distintas_no_se_contaminan(alm, np):
    principal = PricingEngine(alm)
    lista_np = PricingEngine(alm, lista_id=np)
    _, t_np = lista_np.cost_apu("NP-3002", "DIURNO")
    _, t_pr = principal.cost_apu("NP-3002", "DIURNO")
    assert t_np == 8400                               # 2 * 4200 + 0
    assert t_pr == 7900                               # 2 * 3500 + 1 * 900


def test_precargar_respeta_la_lista(alm, np):
    eng = PricingEngine(alm, lista_id=np)
    eng.precargar([("NP-3002", "DIURNO")])
    costed, _ = eng.cost_apu("NP-3002", "DIURNO")
    assert [c for c in costed if c.insumo_codigo == "6140"][0].precio_unitario == 4200.0


def test_alerta_dice_sin_precio_en_la_lista(alm, np):
    costed, total = PricingEngine(alm, lista_id=np).cost_apu("NP-3002", "DIURNO")
    motivos = alertas_costeo(_ensamblado(costed, total))
    assert any("sin precio en la lista" in m for m in motivos)
    assert not any("en $0" in m for m in motivos)     # mensaje específico, no el genérico


def test_alerta_en_cero_genuino_sigue_diciendo_en_0(alm):
    iid = alm.precios.get_candidatos("9")[0].id
    alm.precios.set_precio_por_id(iid, 0.0, "PRECIO IDU")   # $0 genuino en Principal
    costed, total = PricingEngine(alm).cost_apu("NP-3002", "DIURNO")
    motivos = alertas_costeo(_ensamblado(costed, total))
    assert any("en $0" in m for m in motivos)
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_pricing_lista.py -q`
Expected: FAIL — `TypeError: PricingEngine.__init__() got an unexpected keyword argument 'lista_id'`

- [ ] **Step 3: Modificar `apu_tool/dominio/pricing.py`**

Cambiar el import (línea 14-17) para añadir `config`, y reemplazar `__init__`, `_candidatos`, `_precargar_lote`, `cost_component` y `_fallback_historico`:

```python
from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import cruce
from apu_tool.nucleo.models import ApuComponent, CostedComponent
from apu_tool.nucleo.redondeo import mul_redondeado

# Marca de un componente que no tiene tarifa en la lista contra la que se costea.
FUENTE_SIN_PRECIO = "sin precio en lista"
CALIDAD_SIN_PRECIO = "sin_precio_lista"


class PricingEngine:
    def __init__(self, almacen: Almacen, lista_id: int | None = None):
        self.alm = almacen
        # La instancia queda ATADA a una lista de precios (None = Principal). Por eso
        # los tres cachés de abajo NO llevan la lista en la clave: dos listas distintas
        # son dos instancias distintas y no pueden contaminarse entre sí.
        self.lista_id = lista_id
        self._cache: dict[str, list] = {}          # codigo -> list[Insumo] candidatos
        self._comp_cache: dict[tuple, list] = {}   # (codigo, shift) -> list[ApuComponent]
        # Memo (codigo, shift) -> costo_unitario, POR INSTANCIA (no global).
        # Supone grafo de sub-APUs ACÍCLICO (los datos reales no tienen ciclos):
        # con un ciclo, el valor cacheado depende del camino de la primera pasada
        # (el borde que cerró el ciclo cayó a histórico). Aceptable porque un ciclo
        # es un error de datos; la guarda de ciclos garantiza terminación igual.
        self._apu_cost_cache: dict[tuple, float] = {}

    def _respalda_con_historico(self) -> bool:
        """Solo la lista Principal usa el precio histórico embebido como respaldo.

        En una lista de obra (NP) ese histórico es una tarifa CONTRACTUAL: usarlo
        sería costear el no previsto con el precio equivocado en silencio. Preferimos
        el $0 con alerta explícita (regla de negocio: nada en $0 pasa desapercibido)."""
        return self.lista_id in (None, config.LISTA_PRINCIPAL_ID)

    def _candidatos(self, codigo: str) -> list:
        if not codigo:
            return []
        if codigo not in self._cache:
            self._cache[codigo] = self.alm.precios.get_candidatos(
                codigo, lista_id=self.lista_id)
        return self._cache[codigo]
```

En `_precargar_lote` (línea 79), cambiar la última línea:

```python
        for cod, cands in self.alm.precios.get_candidatos_bulk(
                codigos_ins, lista_id=self.lista_id).items():
            self._cache.setdefault(cod, cands)
```

`cost_component` (línea 82):

```python
    def cost_component(self, comp: ApuComponent, _visitando: tuple = ()) -> CostedComponent:
        if (comp.tipo or "insumo") == "apu":
            return self._cost_subapu(comp, _visitando)
        r = cruce.resolver(self._candidatos(comp.insumo_codigo), comp.insumo_nombre)
        calidad = r.calidad.value
        if r.insumo is not None and r.insumo.precio > 0:        # EXACTO o APROXIMADO
            precio, fuente = r.insumo.precio, r.insumo.fuente_precio
        elif self._respalda_con_historico():                    # AMBIGUO/HUERFANO en Principal
            precio, fuente = comp.precio_unitario_hist, "histórico"
        else:                                                   # lista NP: señal, no un número
            precio, fuente, calidad = 0.0, FUENTE_SIN_PRECIO, CALIDAD_SIN_PRECIO
        costo = mul_redondeado(comp.rendimiento, precio)
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=precio, fuente_precio=fuente, costo=costo,
            calidad_cruce=calidad, tipo="insumo", ref_shift="")
```

`_fallback_historico` (línea 97):

```python
    def _fallback_historico(self, comp: ApuComponent, sub_shift: str, calidad: str) -> CostedComponent:
        """Respaldo de un sub-APU que no se puede costear por su árbol (ciclo o sin
        composición). En Principal usa `comp.precio_unitario_hist`; en una lista NP ese
        histórico es tarifa contractual, así que queda en 0 y lo delata la alerta.
        La `calidad` estructural (ciclo / apu_vacio) se CONSERVA: el problema real no es
        que falte el precio, es que el árbol está mal."""
        if self._respalda_con_historico():
            precio, fuente = comp.precio_unitario_hist, "histórico"
        else:
            precio, fuente = 0.0, FUENTE_SIN_PRECIO
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad, rendimiento=comp.rendimiento,
            precio_unitario=precio, fuente_precio=fuente,
            costo=mul_redondeado(comp.rendimiento, precio), calidad_cruce=calidad,
            tipo="apu", ref_shift=sub_shift)
```

- [ ] **Step 4: Modificar `apu_tool/dominio/alertas.py`**

Reemplazar `alertas_costeo` (línea 21):

```python
def alertas_costeo(a: AssembledApu) -> list[str]:
    """Motivos de revisión de costo del ítem. Lista vacía = sin alerta."""
    motivos: list[str] = []
    for c in a.componentes:
        etiqueta = f"{c.insumo_codigo} {c.insumo_nombre}".strip()
        # Va ANTES de la regla del $0 para dar el motivo accionable en vez del genérico.
        # Solo puede aparecer costeando contra una lista distinta de Principal, así que
        # el camino histórico queda idéntico.
        if c.calidad_cruce == "sin_precio_lista":
            motivos.append(f"{etiqueta}: sin precio en la lista")
        elif c.costo <= 0 or c.precio_unitario <= 0:        # regla dura: $0 siempre
            motivos.append(f"{etiqueta}: en $0")
        elif c.calidad_cruce in _MOTIVO_CRUCE:
            motivos.append(f"{etiqueta}: {_MOTIVO_CRUCE[c.calidad_cruce]}")
    if not motivos and a.costo_unitario <= 0:               # ítem sin composición / sin costo
        motivos.append("APU en $0 (sin composición o sin costo)")
    return motivos
```

- [ ] **Step 5: Actualizar el comentario de `calidad_cruce`**

En `apu_tool/nucleo/models.py`, dataclass `CostedComponent` (línea 176):

```python
    calidad_cruce: str = "exacto" # exacto | aproximado | ambiguo | huerfano | apu | apu_vacio | ciclo | sin_precio_lista
```

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_pricing_lista.py -q`
Expected: PASS (11 passed)

Run: `python -m pytest tests/ -q`
Expected: PASS — en particular `test_pricing_cruce.py`, `test_pricing_subapu*.py`, `test_alertas_costeo.py` y `test_report_alertas_costeo.py` deben seguir verdes sin tocarlos.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/pricing.py apu_tool/dominio/alertas.py apu_tool/nucleo/models.py tests/test_pricing_lista.py
git commit -m "feat(pricing): motor atado a una lista; sin respaldo histórico fuera de Principal"
```

---

### Task 5: `corrida.lista_precios_id` en ambos backends

**Files:**
- Modify: `apu_tool/nucleo/models.py` (`CorridaMeta`)
- Modify: `db/corridas.sql`, `db/pg/corridas.sql`
- Modify: `apu_tool/datos/corridas_db.py`, `apu_tool/datos/pg/corridas_pg.py`
- Test: `tests/test_corridas_lista.py` (crear)

**Interfaces:**
- Consumes: nada de las tareas previas (columna independiente).
- Produces: `CorridaMeta.lista_precios_id: Optional[int] = None` — persistido en `crear_corrida` y leído en `get_corrida` / `listar_corridas`. **No hay `set_lista`**: la lista es inmutable tras crear la corrida.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_corridas_lista.py`:

```python
"""La corrida recuerda contra qué lista de precios se costea. Fijada al crear, inmutable."""
import pytest

from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.nucleo.models import CorridaMeta


@pytest.fixture()
def corridas(tmp_path):
    c = CorridasDB(tmp_path / "corridas.db")
    c.init_schema()
    return c


def _meta(lista_precios_id=None) -> CorridaMeta:
    return CorridaMeta(id=None, creada_en="2026-07-27T10:00:00", archivo="lic.xlsx",
                       turno_def="DIURNO", use_ai=False, estado="en_revision",
                       nombre="Acta NP 1", lista_precios_id=lista_precios_id)


def test_corrida_guarda_y_devuelve_la_lista(corridas):
    cid = corridas.crear_corrida(_meta(lista_precios_id=7))
    assert corridas.get_corrida(cid).lista_precios_id == 7


def test_corrida_sin_lista_queda_en_none(corridas):
    cid = corridas.crear_corrida(_meta())
    assert corridas.get_corrida(cid).lista_precios_id is None


def test_listar_corridas_incluye_la_lista(corridas):
    corridas.crear_corrida(_meta(lista_precios_id=7))
    assert [m.lista_precios_id for m in corridas.listar_corridas()] == [7]


def test_init_schema_idempotente_conserva_la_lista(corridas):
    cid = corridas.crear_corrida(_meta(lista_precios_id=7))
    corridas.init_schema()
    assert corridas.get_corrida(cid).lista_precios_id == 7
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_corridas_lista.py -q`
Expected: FAIL — `TypeError: CorridaMeta.__init__() got an unexpected keyword argument 'lista_precios_id'`

- [ ] **Step 3: Añadir el campo a `CorridaMeta`**

En `apu_tool/nucleo/models.py`, dataclass `CorridaMeta` (línea 220), tras `nombre`:

```python
    nombre: str = ""              # alias editable; vacío => se deriva de `archivo`
    # Tarifa contra la que se costea la corrida. None = Principal (el catálogo).
    # Se fija AL CREAR y no cambia: una corrida nunca debe mudar de tarifa por accidente.
    lista_precios_id: Optional[int] = None
```

- [ ] **Step 4: Esquemas**

En `db/corridas.sql`, dentro de `CREATE TABLE corrida`, tras `nombre TEXT`:

```sql
  nombre        TEXT,
  -- Tarifa de la corrida. NULL = Principal. Sin FK: lista_precios vive en precios.db,
  -- otro archivo SQLite (mismo trato que corrida_item.apu_codigo). La integridad se
  -- cuida no borrando listas (la API no expone DELETE).
  lista_precios_id INTEGER
```

En `db/pg/corridas.sql`, la línea equivalente dentro de `CREATE TABLE corridas.corrida`
más el `ALTER` idempotente junto a los que ya existen:

```sql
ALTER TABLE corridas.corrida ADD COLUMN IF NOT EXISTS lista_precios_id BIGINT;
```

- [ ] **Step 5: `corridas_db.py`**

Migración en `init_schema` (tras el bloque de `nombre`, línea 58):

```python
            if "lista_precios_id" not in cols:
                conn.execute("ALTER TABLE corrida ADD COLUMN lista_precios_id INTEGER")
```

`_insert_corrida` (línea 98):

```python
    def _insert_corrida(self, conn: sqlite3.Connection, meta: CorridaMeta) -> int:
        cur = conn.execute(
            "INSERT INTO corrida (creada_en, archivo, turno_def, use_ai, estado, "
            "cuadro_path, duracion_ms, modo, carpeta_id, nombre, lista_precios_id) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (meta.creada_en, meta.archivo, meta.turno_def,
             None if meta.use_ai is None else int(meta.use_ai),
             meta.estado, meta.cuadro_path, meta.duracion_ms, meta.modo,
             meta.carpeta_id, meta.nombre, meta.lista_precios_id))
        return int(cur.lastrowid)
```

`_row_to_meta` (línea 199), añadiendo el campo con la misma defensa `in r.keys()` que usan
`carpeta_id` y `nombre`:

```python
            nombre=((r["nombre"] if "nombre" in r.keys() else None) or r["archivo"]),
            lista_precios_id=(r["lista_precios_id"] if "lista_precios_id" in r.keys() else None))
```

- [ ] **Step 6: `pg/corridas_pg.py`**

Aplicar los mismos tres cambios (INSERT con la columna, lectura en el `_row_to_meta`
equivalente) con dialecto `%s`. Buscar el `INSERT INTO corridas.corrida` y el conversor
de fila, y espejar exactamente lo de SQLite. En Postgres las filas son `dict`, así que la
lectura defensiva es `r.get("lista_precios_id")`.

- [ ] **Step 7: Correr los tests**

Run: `python -m pytest tests/test_corridas_lista.py tests/test_corridas_db.py tests/test_nombre_corridas.py -q`
Expected: PASS

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/nucleo/models.py db/corridas.sql db/pg/corridas.sql apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_lista.py
git commit -m "feat(corridas): columna lista_precios_id (inmutable, dual-backend)"
```

---

### Task 6: Propagar la lista por el servicio de corridas

**Files:**
- Modify: `apu_tool/dominio/assemble.py`
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_servicio_corridas_lista.py` (crear)

**Interfaces:**
- Consumes: `PricingEngine(alm, lista_id=…)` (Task 4), `CorridaMeta.lista_precios_id` (Task 5), `alm.precios.get_lista` (Task 1).
- Produces:
  - `Assembler(almacen, advisor=None, lista_id: Optional[int] = None)`
  - `construir_corrida_stream(alm, archivo, items, turno_def, use_ai, carpeta_id=None, nombre=None, lista_precios_id=None)` — mismo parámetro añadido al final en `construir_corrida`.
  - `_costear_row(alm, row, pricing=None, lista_id=None)`
  - `vista_corrida` y cada fila de `listar_corridas` devuelven `lista_precios_id: Optional[int]` y `lista_nombre: str` (`"Principal"` cuando es `None`).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicio_corridas_lista.py`:

```python
"""La corrida se costea contra su lista, de punta a punta."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.corridas.init_schema()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    a.apus.insert_apus([Apu("NP-3002", "DEMOLICION MURO", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0)])
    return a


@pytest.fixture()
def np(alm):
    lid = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=lid)
    return lid


def _items():
    return [LicitacionItem("1", "DEMOLICION MURO", "M3", 1.0, 20000.0, "DIURNO")]


def test_corrida_np_costea_con_su_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    v = svc.vista_corrida(alm, cid)
    assert v["lista_precios_id"] == np and v["lista_nombre"] == "NP Calle 13"
    assert v["items"][0]["costo_unitario"] == 8400        # 2 * 4200


def test_corrida_sin_lista_usa_principal(alm, np):
    cid = svc.construir_corrida(alm, "lic.xlsx", _items(), "DIURNO", False, carpeta_id=None)
    v = svc.vista_corrida(alm, cid)
    assert v["lista_precios_id"] is None and v["lista_nombre"] == "Principal"
    assert v["items"][0]["costo_unitario"] == 7000        # 2 * 3500


def test_listar_corridas_trae_el_nombre_de_la_lista(alm, np):
    svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                          carpeta_id=None, lista_precios_id=np)
    fila = svc.listar_corridas(alm)[0]
    assert fila["lista_nombre"] == "NP Calle 13" and fila["costo"] == 8400


def test_detalle_item_usa_la_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    d = svc.detalle_item(alm, cid, 0)
    assert d["composicion"][0]["precio_unitario"] == 4200.0
    assert d["composicion"][0]["fuente_precio"] == "ACTA NP"


def test_congelada_no_se_mueve_al_cambiar_la_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    svc.congelar(alm, cid)
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 9999.0, "ACTA NP v2", lista_id=np)
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 8400


def test_confirmar_item_costea_con_la_lista(alm, np):
    cid = svc.construir_corrida(alm, "acta.xlsx", _items(), "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    v = svc.confirmar_item(alm, cid, 0, "NP-3002", "DIURNO")
    assert v["items"][0]["costo_unitario"] == 8400
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_servicio_corridas_lista.py -q`
Expected: FAIL — `TypeError: construir_corrida() got an unexpected keyword argument 'lista_precios_id'`

- [ ] **Step 3: `Assembler` recibe la lista**

En `apu_tool/dominio/assemble.py`, línea 36:

```python
class Assembler:
    def __init__(self, almacen: Almacen, advisor: Optional[ApuAdvisor] = None,
                 lista_id: Optional[int] = None):
        self.alm = almacen
        # Costear con la tarifa de la corrida: armar y confirmar deben dar el mismo
        # número que la vista. None = Principal.
        self.lista_id = lista_id
        self.pricing = PricingEngine(almacen, lista_id=lista_id)
```

- [ ] **Step 4: Propagar en `apu_tool/servicio/corridas.py`**

Helper nuevo, justo debajo de `_estructura` (línea 41):

```python
def _nombre_lista(alm: Almacen, lista_id: Optional[int]) -> str:
    """Etiqueta legible de la tarifa de una corrida. None = Principal.
    Se resuelve en vivo (no se denormaliza): renombrar una lista debe reflejarse."""
    if lista_id is None:
        return "Principal"
    lista = alm.precios.get_lista(lista_id)
    return lista.nombre if lista else f"lista {lista_id}"
```

`construir_corrida_stream` (línea 52) — añadir el parámetro al final, pasarlo al
`Assembler` y guardarlo en el `CorridaMeta`:

```python
def construir_corrida_stream(alm: Almacen, archivo: str, items: list[LicitacionItem],
                             turno_def: str, use_ai: Optional[bool],
                             carpeta_id: Optional[int] = None,
                             nombre: Optional[str] = None,
                             lista_precios_id: Optional[int] = None):
```

y dentro:

```python
    advisor = ApuAdvisor(enabled=use_ai)
    assembler = Assembler(alm, advisor=advisor, lista_id=lista_precios_id)
    nombre_efectivo = (nombre or "").strip()[:120].strip() or nombre_desde_archivo(archivo)
    corrida_id = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en=datetime.now().isoformat(timespec="seconds"),
        archivo=archivo, turno_def=turno_def, use_ai=use_ai,
        estado="armando", cuadro_path=None, carpeta_id=carpeta_id,
        nombre=nombre_efectivo, lista_precios_id=lista_precios_id))
```

`construir_corrida` (línea 109) — mismo parámetro, reenviado:

```python
def construir_corrida(alm: Almacen, archivo: str, items: list[LicitacionItem],
                      turno_def: str, use_ai: Optional[bool],
                      carpeta_id: Optional[int] = None,
                      nombre: Optional[str] = None,
                      lista_precios_id: Optional[int] = None) -> int:
    """Envoltorio no-stream: drena el generador e ignora el progreso; devuelve el id."""
    corrida_id = -1
    for evento, payload in construir_corrida_stream(alm, archivo, items, turno_def,
                                                    use_ai, carpeta_id, nombre,
                                                    lista_precios_id):
        if evento == "done":
            corrida_id = payload["id"]
    return corrida_id
```

`_costear_row` (línea 122) — solo cambia la creación del motor propio:

```python
def _costear_row(alm: Almacen, row: CorridaItemRow,
                 pricing: Optional[PricingEngine] = None,
                 lista_id: Optional[int] = None) -> AssembledApu:
```

y su primera línea:

```python
    pricing = pricing or PricingEngine(alm, lista_id=lista_id)
```

Añadir al docstring de `_costear_row`, tras el párrafo de `pricing`:

```
    `lista_id`: tarifa a usar cuando se crea el motor aquí (None = Principal). Si llega
    un `pricing` compartido, la lista viaja DENTRO de él y este parámetro se ignora.
```

`_ensamblar_corrida` (línea 185) — pasar la lista de la corrida al camino sin snapshot:

```python
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(meta.id)
        return [_assembled_desde_snapshot(r, snaps[r.seq]) if r.seq in snaps
                else _costear_row(alm, r, pricing, meta.lista_precios_id) for r in rows]
    return [_costear_row(alm, r, pricing, meta.lista_precios_id) for r in rows]
```

`vista_corrida` (línea 207) — motor con lista y dos claves nuevas en la respuesta:

```python
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id)   # COMPARTIDO por la corrida
    pricing.precargar((r.apu_codigo, r.shift) for r in rows if r.apu_codigo)  # lote
    ensambles = _ensamblar_corrida(alm, meta, rows, pricing)
    items = [_vista_item(ens, r.seq, r.status) for ens, r in zip(ensambles, rows)]
    return {
        "id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
        "estado": meta.estado, "modo": meta.modo,
        "carpeta_id": meta.carpeta_id,
        "lista_precios_id": meta.lista_precios_id,
        "lista_nombre": _nombre_lista(alm, meta.lista_precios_id),
        "duracion_ms": meta.duracion_ms, "items": items,
        "totales": _totales(ensambles, rows),
    }
```

`detalle_item` (línea 225) — el motor implícito necesita la lista:

```python
    if meta.modo == "congelada":
        snaps = alm.corridas.get_snapshots(corrida_id)
        ens = (_assembled_desde_snapshot(row, snaps[seq]) if seq in snaps
               else _costear_row(alm, row, None, meta.lista_precios_id))
    else:
        ens = _costear_row(alm, row, None, meta.lista_precios_id)
```

`congelar` (línea 252):

```python
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id)   # COMPARTIDO al congelar
    _rows = alm.corridas.get_items(corrida_id)
    pricing.precargar((r.apu_codigo, r.shift) for r in _rows if r.apu_codigo)
    for r in _rows:
        ens = _costear_row(alm, r, pricing)
```

`confirmar_item` (línea 297) — el `Assembler` recostea el ítem elegido:

```python
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id)
```

`listar_corridas` (línea 317) — dos claves nuevas en la fila y el motor con lista:

```python
        fila = {"id": meta.id, "nombre": meta.nombre, "archivo": meta.archivo,
                "creada_en": meta.creada_en,
                "estado": meta.estado, "modo": meta.modo, "duracion_ms": meta.duracion_ms,
                "carpeta_id": meta.carpeta_id,
                "lista_precios_id": meta.lista_precios_id,
                "lista_nombre": _nombre_lista(alm, meta.lista_precios_id),
                "n_items": len(rows), "n_revision": n_rev,
                "contractual": None, "costo": None, "margen": None, "margen_pct": None}
        try:                                           # fail-safe: si una corrida no
            pricing = PricingEngine(alm, lista_id=meta.lista_precios_id)   # costea, queda en None
```

`generar_cuadro` (línea 354):

```python
    pricing = PricingEngine(alm, lista_id=meta.lista_precios_id)   # COMPARTIDO al generar
```

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_servicio_corridas_lista.py -q`
Expected: PASS (6 passed)

Run: `python -m pytest tests/ -q`
Expected: PASS — `test_servicio_corridas.py`, `test_api_corridas.py` y `test_corrida_alertas_costeo.py` siguen verdes sin tocarlos.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/assemble.py apu_tool/servicio/corridas.py tests/test_servicio_corridas_lista.py
git commit -m "feat(corridas): costear la corrida contra su lista de precios"
```

---

### Task 7: El cuadro declara su tarifa

**Files:**
- Modify: `apu_tool/dominio/report.py`, `apu_tool/dominio/report_categorizado.py`
- Modify: `apu_tool/servicio/corridas.py` (`generar_cuadro`)
- Test: `tests/test_report_lista.py` (crear)

**Interfaces:**
- Consumes: `_nombre_lista` (Task 6).
- Produces:
  - `write_report(apus, path, lista_nombre: str = "Principal") -> Path`
  - `write_report_categorizado(apus, path, lista_nombre: str = "Principal") -> Path`
  - Ambos añaden la fila `["Lista de precios", <nombre>]` en su hoja `INFO`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_report_lista.py`:

```python
"""El cuadro dice con qué tarifa se emitió: sin eso, un cuadro NP y uno contractual
son indistinguibles en el archivo."""
import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.report import write_report
from apu_tool.nucleo.models import (
    Apu, ApuComponent, AssembledApu, CostedComponent, Insumo, LicitacionItem, MatchStatus,
)
from apu_tool.servicio import corridas as svc


def _assembled() -> AssembledApu:
    item = LicitacionItem("1", "DEMOLICION", "M3", 1.0, 20000.0, "DIURNO")
    comp = CostedComponent("6140", "ACERO", "KG", 2.0, 4200.0, "ACTA NP", 8400)
    return AssembledApu(item=item, apu_codigo="NP-3002", apu_nombre="DEMOLICION",
                        unidad="M3", shift="DIURNO", componentes=[comp],
                        costo_unitario=8400, status=MatchStatus.AUTO, confianza=1.0)


def _info(path) -> dict:
    wb = openpyxl.load_workbook(path)
    filas = {r[0]: r[1] for r in wb["INFO"].iter_rows(values_only=True) if r and r[0]}
    wb.close()
    return filas


def test_info_dice_principal_por_defecto(tmp_path):
    out = write_report([_assembled()], tmp_path / "cuadro.xlsx")
    assert _info(out)["Lista de precios"] == "Principal"


def test_info_dice_la_lista_pasada(tmp_path):
    out = write_report([_assembled()], tmp_path / "cuadro.xlsx",
                       lista_nombre="NP Calle 13")
    assert _info(out)["Lista de precios"] == "NP Calle 13"


def test_generar_cuadro_estampa_la_lista_de_la_corrida(tmp_path, monkeypatch):
    from apu_tool import config
    monkeypatch.setattr(config, "OUTPUT_DIR", tmp_path / "salidas")
    alm = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    alm.reset()
    alm.corridas.init_schema()
    alm.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    alm.apus.insert_apus([Apu("NP-3002", "DEMOLICION", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0)])
    np = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    items = [LicitacionItem("1", "DEMOLICION", "M3", 1.0, 20000.0, "DIURNO")]
    cid = svc.construir_corrida(alm, "acta.xlsx", items, "DIURNO", False,
                                carpeta_id=None, lista_precios_id=np)
    out = svc.generar_cuadro(alm, cid)
    assert _info(out)["Lista de precios"] == "NP Calle 13"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_report_lista.py -q`
Expected: FAIL — `KeyError: 'Lista de precios'`

- [ ] **Step 3: Modificar `write_report`**

En `apu_tool/dominio/report.py`, línea 167:

```python
def write_report(apus: list[AssembledApu], path: Path | str,
                 lista_nombre: str = "Principal") -> Path:
    path = Path(path)
    path.parent.mkdir(parents=True, exist_ok=True)
    wb = openpyxl.Workbook()
    _build_resumen(wb.active, apus)
    wb.active.title = "RESUMEN"
    _build_desglose(wb.create_sheet("DESGLOSE"), apus)
    _build_alertas(wb.create_sheet("ALERTAS"), apus)
    # Metadatos.
    meta = wb.create_sheet("INFO")
    meta.append(["Generado", date.today().isoformat()])
    meta.append(["Ítems", len(apus)])
    # Qué tarifa costeó este cuadro. Sin esta fila, un cuadro de No Previstos y uno
    # contractual son indistinguibles en el archivo.
    meta.append(["Lista de precios", lista_nombre])
    meta.append(["Nota", "Los precios de costo NO fueron vistos por la IA. "
                         "La IA solo decidió la estructura de los APUs."])
    wb.save(path)
    return path
```

- [ ] **Step 4: El mismo trato en `report_categorizado.py`**

Tiene su **propia** hoja `INFO` (no reusa la de `report.py`), así que necesita la fila
igual: sin ella, el cuadro por capítulos de un NP sería indistinguible de uno
contractual. En `apu_tool/dominio/report_categorizado.py`, línea 172:

```python
def write_report_categorizado(apus: list[AssembledApu], path: Path | str,
                              lista_nombre: str = "Principal") -> Path:
```

y en el bloque de la hoja `INFO` (línea 184), tras la fila `Capítulos`:

```python
    info.append(["Capítulos", len(grupos)])
    # Qué tarifa costeó este cuadro (ver write_report: misma razón).
    info.append(["Lista de precios", lista_nombre])
```

Buscar sus llamadores con `grep -rn "write_report_categorizado" --include=*.py` y pasarles
`lista_nombre=_nombre_lista(alm, meta.lista_precios_id)` donde haya una corrida a mano.
Donde no la haya (CLI/pipeline), no pasar nada: el default es `"Principal"`.

Añadir el caso al test:

```python
def test_categorizado_tambien_declara_la_lista(tmp_path):
    from apu_tool.dominio.report_categorizado import write_report_categorizado
    out = write_report_categorizado([_assembled()], tmp_path / "cat.xlsx",
                                    lista_nombre="NP Calle 13")
    assert _info(out)["Lista de precios"] == "NP Calle 13"
```

- [ ] **Step 5: Pasar el nombre desde `generar_cuadro`**

En `apu_tool/servicio/corridas.py`, línea 373:

```python
    write_report(assembled, out, lista_nombre=_nombre_lista(alm, meta.lista_precios_id))
```

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_report_lista.py tests/test_report_categorizado.py -q`
Expected: PASS (4 passed en el primero + los existentes verdes)

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/report.py apu_tool/dominio/report_categorizado.py apu_tool/servicio/corridas.py tests/test_report_lista.py
git commit -m "feat(report): la hoja INFO declara la lista de precios del cuadro"
```

---

### Task 8: Servicio y endpoints de listas de precios

**Files:**
- Create: `apu_tool/servicio/listas.py`
- Modify: `apu_tool/servicio/esquemas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_listas.py` (crear)

**Interfaces:**
- Consumes: `alm.precios.listar_listas / get_lista / crear_lista / renombrar_lista` (Task 1), `registrar_auditoria` (existente).
- Produces:
  - `listas.listar(alm) -> list[dict]` con claves `id`, `nombre`, `creada_en`.
  - `listas.crear(alm, nombre, actor=None) -> dict`
  - `listas.renombrar(alm, lista_id, nombre, actor=None) -> dict`
  - Endpoints `GET /api/listas-precios`, `POST /api/listas-precios`, `PATCH /api/listas-precios/{lista_id}`.
  - DTO `ListaPreciosIn(nombre: str)`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_api_listas.py`, con el mismo patrón de `tests/test_api_insumos.py`
(el helper `cliente(app, rol=…)` de `tests/conftest.py`; **no** hay fixtures de cliente
por rol, se construye uno por test):

```python
# tests/test_api_listas.py
"""API de listas de precios: leer cualquiera, crear/renombrar solo editor, Principal intocable."""
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="editor"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return cliente(create_app(almacen=alm), rol=rol), alm


def test_listar_devuelve_principal(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    r = cli.get("/api/listas-precios")
    assert r.status_code == 200
    assert [(l["id"], l["nombre"]) for l in r.json()] == [(1, "Principal")]


def test_crear_lista_como_editor(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.post("/api/listas-precios", json={"nombre": "NP Calle 13"})
    assert r.status_code == 200
    assert r.json()["nombre"] == "NP Calle 13" and r.json()["id"] != 1


def test_crear_lista_duplicada_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    cli.post("/api/listas-precios", json={"nombre": "NP Calle 13"})
    assert cli.post("/api/listas-precios",
                    json={"nombre": "np calle 13"}).status_code == 400


def test_crear_lista_vacia_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    assert cli.post("/api/listas-precios", json={"nombre": "  "}).status_code == 400


def test_crear_lista_como_consulta_da_403(tmp_path):
    cli, _ = _cli(tmp_path, rol="consulta")
    assert cli.post("/api/listas-precios",
                    json={"nombre": "NP Calle 13"}).status_code == 403


def test_renombrar_lista(tmp_path):
    cli, _ = _cli(tmp_path)
    lid = cli.post("/api/listas-precios", json={"nombre": "NP A"}).json()["id"]
    r = cli.patch(f"/api/listas-precios/{lid}", json={"nombre": "NP A - Acta 2"})
    assert r.status_code == 200 and r.json()["nombre"] == "NP A - Acta 2"


def test_renombrar_principal_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    assert cli.patch("/api/listas-precios/1", json={"nombre": "Otra"}).status_code == 400


def test_renombrar_inexistente_da_400(tmp_path):
    cli, _ = _cli(tmp_path)
    assert cli.patch("/api/listas-precios/999", json={"nombre": "X"}).status_code == 400


def test_no_existe_delete(tmp_path):
    # Borrar una lista dejaría corridas huérfanas de su tarifa (no hay FK entre bases).
    cli, _ = _cli(tmp_path)
    assert cli.delete("/api/listas-precios/1").status_code == 405


def test_auditoria_registra_la_creacion(tmp_path):
    cli, _ = _cli(tmp_path, rol="admin")
    cli.post("/api/listas-precios", json={"nombre": "NP Calle 13"})
    acciones = [e["accion"] for e in cli.get("/api/auditoria").json()["items"]]
    assert "lista.crear" in acciones
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_api_listas.py -q`
Expected: FAIL — 404 en todas (los endpoints no existen)

- [ ] **Step 3: Crear `apu_tool/servicio/listas.py`**

```python
"""
Lógica de servicio para las listas de precios (tarifas).

Una lista = una tarifa: la del catálogo ('Principal', id 1) o la de una obra de No
Previstos. NO ve dinero por sí misma (solo nombres e ids) y nunca toca la IA.

NO hay borrado: una corrida guarda su `lista_precios_id` sin FK (vive en otra base),
así que borrar una lista dejaría corridas huérfanas de su tarifa. Un nombre mal escrito
se corrige renombrando.
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.servicio.auditoria import registrar_auditoria


def _out(lista) -> dict:
    return {"id": lista.id, "nombre": lista.nombre, "creada_en": lista.creada_en}


def listar(alm: Almacen) -> list[dict]:
    return [_out(l) for l in alm.precios.listar_listas()]


def crear(alm: Almacen, nombre: str, actor=None) -> dict:
    """Crea una lista. ValueError (-> 400) si el nombre está vacío o ya existe."""
    with alm.transaccion("precios") as conn:
        lid = alm.precios.crear_lista(
            nombre, creado_por=(actor.user_id if actor else None), conn=conn)
        registrar_auditoria(
            alm, conn, actor, "lista.crear", "lista", lid, antes=None,
            despues={"id": lid, "nombre": (nombre or "").strip()})
    return _out(alm.precios.get_lista(lid))


def renombrar(alm: Almacen, lista_id: int, nombre: str, actor=None) -> dict:
    """Renombra una lista. ValueError (-> 400) si no existe, si el nombre choca,
    o si es la Principal (ancla del invariante lista_id=None == Principal)."""
    previa = alm.precios.get_lista(lista_id)
    if previa is None:
        raise ValueError(f"No existe la lista de precios id={lista_id}.")
    with alm.transaccion("precios") as conn:
        alm.precios.renombrar_lista(lista_id, nombre, conn=conn)
        registrar_auditoria(
            alm, conn, actor, "lista.renombrar", "lista", lista_id,
            antes={"nombre": previa.nombre},
            despues={"nombre": (nombre or "").strip()})
    return _out(alm.precios.get_lista(lista_id))
```

- [ ] **Step 4: DTO en `apu_tool/servicio/esquemas.py`**

Tras `CambiosIn` (línea 27):

```python
class ListaPreciosIn(BaseModel):
    nombre: str
```

- [ ] **Step 5: Endpoints en `apu_tool/servicio/rutas.py`**

Importar el servicio y el DTO junto a los que ya se importan, y añadir el bloque
**antes** de `@router.get("/insumos")` (línea 315):

```python
# ---- listas de precios (tarifas) ----
@router.get("/listas-precios")
def listar_listas_precios(alm: Almacen = Depends(get_almacen),
                          _: object = Depends(requiere_rol("consulta"))):
    return listas_svc.listar(alm)


@router.post("/listas-precios")
def crear_lista_precios(body: ListaPreciosIn, alm: Almacen = Depends(get_almacen),
                        actor=Depends(requiere_rol("editor"))):
    try:
        return listas_svc.crear(alm, body.nombre, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.patch("/listas-precios/{lista_id}")
def renombrar_lista_precios(lista_id: int, body: ListaPreciosIn,
                            alm: Almacen = Depends(get_almacen),
                            actor=Depends(requiere_rol("editor"))):
    try:
        return listas_svc.renombrar(alm, lista_id, body.nombre, actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Import: `from apu_tool.servicio import listas as listas_svc` y añadir `ListaPreciosIn`
a la línea de import de `apu_tool.servicio.esquemas`.

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_api_listas.py -q`
Expected: PASS (9 passed)

Run: `python -m pytest tests/ -q`
Expected: PASS — ojo con `tests/test_auditoria_contrato.py`: si valida la taxonomía de
acciones contra una lista cerrada, hay que añadir `lista.crear` y `lista.renombrar` ahí.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/listas.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_listas.py
git commit -m "feat(api): endpoints de listas de precios (listar/crear/renombrar)"
```

---

### Task 9: Editar e importar precios en una lista

**Files:**
- Modify: `apu_tool/servicio/insumos.py`, `apu_tool/servicio/autoria.py`
- Modify: `apu_tool/servicio/esquemas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_servicio_insumos_lista.py` (crear)

**Interfaces:**
- Consumes: `set_precio_por_id(..., lista_id=…)`, `crear_insumo(..., lista_id=…)`, `list_insumos(..., lista_id=…, sin_precio=…)`, `get_insumo_por_id(..., lista_id=…)`, `price_history(..., lista_id=…)`, `fuentes(lista_id=…)` (Tasks 2-3).
- Produces:
  - `insumos_svc.listar(alm, q=None, grupo=None, fuente=None, clasificacion=None, limit=100, offset=0, lista_id=None, sin_precio=False) -> dict`
  - `insumos_svc.detalle(alm, insumo_id, lista_id=None) -> Optional[dict]`
  - `insumos_svc.aplicar_cambios(alm, cambios, actor=None, lista_id=None) -> dict`
  - `autoria.crear_insumo(alm, datos, actor=None, lista_id=None) -> dict`
  - `autoria.preview_importar_insumos(alm, contenido, nombre_archivo, lista_id=None) -> dict`
  - `autoria.aplicar_importar_insumos(alm, contenido, nombre_archivo, actor=None, lista_id=None) -> dict`
  - Cada dict de insumo gana la clave `sin_precio: bool`.
  - Query param `lista` y `sin_precio` en `GET /insumos`; `lista` en `/insumos/fuentes` y `/insumos/{id}`; campo `lista_id` en `CambiosIn`, `InsumoNuevoIn` y en los `Form` de import.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicio_insumos_lista.py`:

```python
"""Editar e importar precios apuntando a una lista concreta."""
import io

import openpyxl
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.servicio import autoria
from apu_tool.servicio import insumos as insumos_svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.corridas.init_schema()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU"),
        Insumo("9", "CEMENTO GRIS", "KG", "MATERIAL", 900.0, "COSTO INTERNO"),
    ])
    return a


@pytest.fixture()
def np(alm):
    return alm.precios.crear_lista("NP Calle 13")


def _xlsx(filas: list[list]) -> bytes:
    wb = openpyxl.Workbook()
    for f in filas:
        wb.active.append(f)
    buf = io.BytesIO()
    wb.save(buf)
    return buf.getvalue()


def test_listar_marca_sin_precio(alm, np):
    res = insumos_svc.listar(alm, lista_id=np)
    assert res["total"] == 2
    assert all(i["sin_precio"] for i in res["items"])
    assert all(not i["sin_precio"] for i in insumos_svc.listar(alm)["items"])


def test_listar_filtro_sin_precio(alm, np):
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    res = insumos_svc.listar(alm, lista_id=np, sin_precio=True)
    assert [i["codigo"] for i in res["items"]] == ["9"]


def test_aplicar_cambios_escribe_en_la_lista(alm, np):
    iid = alm.precios.get_candidatos("6140")[0].id
    res = insumos_svc.aplicar_cambios(
        alm, [{"insumo_id": iid, "precio": 4200.0, "fuente": "ACTA NP"}], lista_id=np)
    assert res["aplicados"] == 1
    assert alm.precios.get_insumo_por_id(iid, lista_id=np).precio == 4200.0
    assert alm.precios.get_insumo_por_id(iid).precio == 3500.0        # Principal intacto


def test_detalle_trae_historial_de_la_lista(alm, np):
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=np)
    d = insumos_svc.detalle(alm, iid, lista_id=np)
    assert d["insumo"]["precio"] == 4200.0
    assert [h["precio"] for h in d["historial"]] == [4200.0]


def test_crear_insumo_en_la_lista_np(alm, np):
    out = autoria.crear_insumo(alm, {"codigo": "NP-INS-1", "nombre": "GEOTEXTIL NT 2500",
                                     "unidad": "M2", "grupo": "MATERIAL",
                                     "precio": 8000.0, "fuente": "ACTA NP"}, lista_id=np)
    assert out["precio"] == 8000.0
    assert alm.precios.get_insumo_por_id(out["id"]).sin_precio is True


def test_import_preview_compara_contra_la_lista(alm, np):
    contenido = _xlsx([["codigo", "nombre", "precio", "fuente"],
                       ["6140", "ACERO 60000 PSI", 4200, "ACTA NP"]])
    prev = autoria.preview_importar_insumos(alm, contenido, "np.xlsx", lista_id=np)
    assert prev["actualizar"][0]["precio_actual"] == 0.0      # sin tarifa aún en NP
    assert prev["actualizar"][0]["precio_nuevo"] == 4200.0


def test_import_aplica_en_la_lista_y_crea_los_nuevos(alm, np):
    contenido = _xlsx([["codigo", "nombre", "precio", "fuente"],
                       ["6140", "ACERO 60000 PSI", 4200, "ACTA NP"],
                       ["NP-INS-1", "GEOTEXTIL NT 2500", 8000, "ACTA NP"]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "np.xlsx", lista_id=np)
    assert res["creados"] == 1 and res["actualizados"] == 1 and res["errores"] == []
    assert alm.precios.get_candidatos("6140", lista_id=np)[0].precio == 4200.0
    assert alm.precios.get_candidatos("6140")[0].precio == 3500.0
    assert alm.precios.get_candidatos("NP-INS-1")[0].sin_precio is True


def test_import_rechaza_precio_no_positivo_en_la_lista(alm, np):
    contenido = _xlsx([["codigo", "nombre", "precio", "fuente"],
                       ["NP-INS-2", "MATERIAL DEL CLIENTE", 0, "ACTA NP"]])
    res = autoria.aplicar_importar_insumos(alm, contenido, "np.xlsx", lista_id=np)
    assert res["creados"] == 0 and len(res["errores"]) == 1
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_servicio_insumos_lista.py -q`
Expected: FAIL — `TypeError: listar() got an unexpected keyword argument 'lista_id'`

- [ ] **Step 3: `apu_tool/servicio/insumos.py`**

Reemplazar `_insumo_out`, `listar`, `detalle` y `aplicar_cambios`:

```python
def _insumo_out(ins) -> dict:
    return {"id": ins.id, "codigo": ins.codigo, "nombre": ins.nombre,
            "unidad": ins.unidad, "grupo": ins.grupo, "precio": ins.precio,
            "fuente": ins.fuente_precio,
            "clasificacion": config.classify_price_source(ins.fuente_precio),
            # True = no hay tarifa en la lista consultada (≠ un $0 genuino, que la
            # regla de negocio prohíbe y la UI debe seguir mostrando como $0).
            "sin_precio": ins.sin_precio}


def listar(alm: Almacen, q: Optional[str] = None, grupo: Optional[str] = None,
           fuente: Optional[str] = None, clasificacion: Optional[str] = None,
           limit: int = 100, offset: int = 0,
           lista_id: Optional[int] = None, sin_precio: bool = False) -> dict:
    items, total = alm.precios.list_insumos(q, grupo, fuente, clasificacion, limit, offset,
                                            lista_id, sin_precio)
    return {"items": [_insumo_out(i) for i in items], "total": total,
            "limit": limit, "offset": offset}


def detalle(alm: Almacen, insumo_id: int, lista_id: Optional[int] = None) -> Optional[dict]:
    ins = alm.precios.get_insumo_por_id(insumo_id, lista_id=lista_id)
    if ins is None:
        return None
    return {"insumo": _insumo_out(ins),
            "historial": alm.precios.price_history(ins.codigo, nombre=ins.nombre,
                                                   lista_id=lista_id)}


def aplicar_cambios(alm: Almacen, cambios: list[dict], actor=None,
                    lista_id: Optional[int] = None) -> dict:
    aplicados, errores = 0, []
    lote = nuevo_lote()
    for c in cambios:
        try:
            precio = float(c["precio"])
            if precio <= 0:
                raise ValueError(MSG_PRECIO_POSITIVO)
            iid = int(c["insumo_id"])
            fuente = str(c.get("fuente", "") or "")
            antes_ins = alm.precios.get_insumo_por_id(iid, lista_id=lista_id)
            with alm.transaccion("precios") as conn:
                alm.precios.set_precio_por_id(iid, precio, fuente, conn=conn,
                                              creado_por=(actor.user_id if actor else None),
                                              lista_id=lista_id)
                registrar_auditoria(
                    alm, conn, actor, "precio.editar", "insumo", iid,
                    antes=({"precio": antes_ins.precio, "fuente": antes_ins.fuente_precio}
                           if antes_ins else None),
                    despues={"precio": precio, "fuente": fuente},
                    # lista_id en el contexto: sin esto el log no dice QUÉ tarifa se tocó.
                    contexto={"origen": "edicion", "lote_id": lote, "lista_id": lista_id})
            aplicados += 1
        except Exception as e:
            errores.append({"insumo_id": c.get("insumo_id"), "error": str(e)})
    return {"aplicados": aplicados, "errores": errores}
```

- [ ] **Step 4: `apu_tool/servicio/autoria.py`**

`crear_insumo` (línea 33) — añadir `lista_id` al final y propagarlo:

```python
def crear_insumo(alm: Almacen, datos: dict, actor=None, lista_id=None) -> dict:
```

y dentro del `with`:

```python
    with alm.transaccion("precios") as conn:
        iid = alm.precios.crear_insumo(ins, conn=conn,
                                       creado_por=(actor.user_id if actor else None),
                                       lista_id=lista_id)
        registrar_auditoria(
            alm, conn, actor, "insumo.crear", "insumo", iid, antes=None,
            despues={"codigo": ins.codigo, "nombre": ins.nombre, "unidad": ins.unidad,
                     "grupo": ins.grupo, "precio": ins.precio, "fuente": ins.fuente_precio},
            contexto={"origen": "individual", "lista_id": lista_id})
    return _insumo_out(alm.precios.get_insumo_por_id(iid, lista_id=lista_id))
```

`_match_identidad` (línea 169) — la identidad es global, pero el precio que se compara
debe ser el de la lista destino:

```python
def _match_identidad(alm: Almacen, codigo: str, nombre: str, lista_id=None):
    """Insumo con (codigo, nombre) exactos (nombre normalizado), o None.
    La identidad es global; el precio devuelto es el de `lista_id` (None = Principal),
    porque es contra ESE precio que el preview reporta el cambio."""
    nn = normalizar(nombre)
    for c in alm.precios.get_candidatos(codigo, lista_id=lista_id):
        if normalizar(c.nombre) == nn:
            return c
    return None
```

`preview_importar_insumos` (línea 231):

```python
def preview_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             lista_id=None) -> dict:
    """Upsert por fila CONTRA `lista_id` (None = Principal). Con nombre: identidad
    código+nombre (crea o actualiza). Sin nombre: actualiza precio por código (único),
    o marca ambigua/no encontrada."""
    crear, actualizar, ambigua, no_encontrada, invalida = [], [], [], [], []
    for f in _filas_insumos(contenido, nombre_archivo):
        cod, nom = f["codigo"], f["nombre"]
        if not cod:
            invalida.append(f)
        elif nom:
            match = _match_identidad(alm, cod, nom, lista_id)
            (actualizar.append(_cambio_upsert(match, f)) if match else crear.append(f))
        else:
            cands = alm.precios.get_candidatos(cod, lista_id=lista_id)
            if len(cands) == 1:
                actualizar.append(_cambio_upsert(cands[0], f))
            elif len(cands) > 1:
                ambigua.append({"codigo": cod,
                                "candidatos": [{"id": c.id, "nombre": c.nombre} for c in cands]})
            else:
                no_encontrada.append({"codigo": cod})
    return {"crear": crear, "actualizar": actualizar, "ambigua": ambigua,
            "no_encontrada": no_encontrada, "invalida": invalida}
```

`aplicar_importar_insumos` (línea 255) — firma con `lista_id` al final, preview con lista,
y las tres llamadas de escritura con lista:

```python
def aplicar_importar_insumos(alm: Almacen, contenido: bytes, nombre_archivo: str,
                             actor=None, lista_id=None) -> dict:
    prev = preview_importar_insumos(alm, contenido, nombre_archivo, lista_id)
```

En el bucle de `crear`:

```python
            with alm.transaccion("precios") as conn:
                iid = alm.precios.crear_insumo(ins, conn=conn,
                                               creado_por=(actor.user_id if actor else None),
                                               lista_id=lista_id)
                registrar_auditoria(
                    alm, conn, actor, "insumo.crear", "insumo", iid, antes=None,
                    despues={"codigo": ins.codigo, "nombre": ins.nombre, "unidad": ins.unidad,
                             "grupo": ins.grupo, "precio": ins.precio, "fuente": ins.fuente_precio},
                    contexto={"origen": "import", "lote_id": lote, "archivo": nombre_archivo,
                              "lista_id": lista_id})
```

En el bucle de `actualizar`:

```python
            with alm.transaccion("precios") as conn:
                alm.precios.set_precio_por_id(c["insumo_id"], c["precio_nuevo"], c["fuente_nueva"],
                                              conn=conn,
                                              creado_por=(actor.user_id if actor else None),
                                              lista_id=lista_id)
                registrar_auditoria(
                    alm, conn, actor, "precio.editar", "insumo", c["insumo_id"],
                    antes={"precio": c["precio_actual"], "fuente": c["fuente_actual"]},
                    despues={"precio": c["precio_nuevo"], "fuente": c["fuente_nueva"]},
                    contexto={"origen": "import", "lote_id": lote, "archivo": nombre_archivo,
                              "lista_id": lista_id})
```

- [ ] **Step 5: DTOs y endpoints**

En `esquemas.py`, añadir `lista_id` a los dos DTOs de escritura:

```python
class CambiosIn(BaseModel):
    cambios: list[CambioIn]
    lista_id: Optional[int] = None      # None = Principal


class InsumoNuevoIn(BaseModel):
    codigo: str
    nombre: str
    unidad: str = ""
    grupo: str = ""
    precio: float = 0.0
    fuente: str = ""
    lista_id: Optional[int] = None      # None = Principal
```

En `rutas.py`, reemplazar los cinco endpoints de insumos afectados:

```python
@router.get("/insumos")
def listar_insumos(q: Optional[str] = None, grupo: Optional[str] = None,
                   fuente: Optional[str] = None, clasificacion: Optional[str] = None,
                   limit: int = 100, offset: int = 0,
                   lista: Optional[int] = None, sin_precio: bool = False,
                   alm: Almacen = Depends(get_almacen),
                   _: object = Depends(requiere_rol("consulta"))):
    try:
        return insumos_svc.listar(alm, q, grupo, fuente, clasificacion, limit, offset,
                                  lista, sin_precio)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/insumos/fuentes")
def insumos_fuentes(lista: Optional[int] = None, alm: Almacen = Depends(get_almacen),
                    _: object = Depends(requiere_rol("consulta"))):
    return alm.precios.fuentes(lista_id=lista)


@router.get("/insumos/{insumo_id}")
def insumo_detalle(insumo_id: int, lista: Optional[int] = None,
                   alm: Almacen = Depends(get_almacen),
                   _: object = Depends(requiere_rol("consulta"))):
    d = insumos_svc.detalle(alm, insumo_id, lista_id=lista)
    if d is None:
        raise HTTPException(status_code=404, detail="Insumo no encontrado.")
    return d


@router.post("/insumos/cambios")
def insumos_cambios(body: CambiosIn, alm: Almacen = Depends(get_almacen),
                    actor=Depends(requiere_rol("editor"))):
    return insumos_svc.aplicar_cambios(alm, [c.model_dump() for c in body.cambios],
                                       actor=actor, lista_id=body.lista_id)


@router.post("/insumos/crear")
def crear_insumo(body: InsumoNuevoIn, alm: Almacen = Depends(get_almacen),
                 actor=Depends(requiere_rol("editor"))):
    datos = body.model_dump()
    lista_id = datos.pop("lista_id", None)
    try:
        return autoria.crear_insumo(alm, datos, actor=actor, lista_id=lista_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Y los dos de import, que reciben la lista como campo de formulario (van con `UploadFile`):

```python
@router.post("/insumos/importar/preview")
async def insumos_importar_preview(archivo: UploadFile = File(...),
                                   lista_id: Optional[int] = Form(None),
                                   alm: Almacen = Depends(get_almacen),
                                   _: object = Depends(requiere_rol("editor"))):
    contenido = await archivo.read()
    try:
        return autoria.preview_importar_insumos(alm, contenido,
                                                archivo.filename or "insumos.xlsx", lista_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (zipfile.BadZipFile, InvalidFileException):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel válido o está corrupto.")


@router.post("/insumos/importar")
async def insumos_importar(archivo: UploadFile = File(...),
                           lista_id: Optional[int] = Form(None),
                           alm: Almacen = Depends(get_almacen),
                           actor=Depends(requiere_rol("editor"))):
    contenido = await archivo.read()
    try:
        return autoria.aplicar_importar_insumos(alm, contenido,
                                                archivo.filename or "insumos.xlsx",
                                                actor=actor, lista_id=lista_id)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (zipfile.BadZipFile, InvalidFileException):
        raise HTTPException(status_code=400, detail="El archivo no es un Excel válido o está corrupto.")
```

- [ ] **Step 6: Endpoints de corrida con lista**

En `rutas.py`, `POST /corridas` y `POST /corridas/stream`: añadir el campo y reenviarlo.

```python
                        nombre: Optional[str] = Form(None),
                        lista_id: Optional[int] = Form(None),
                        archivo: UploadFile = File(...),
```

Validar antes de armar (en ambos endpoints, junto a la validación de carpeta):

```python
    if lista_id is not None and alm.precios.get_lista(lista_id) is None:
        raise HTTPException(status_code=400, detail="La lista de precios indicada no existe.")
```

Y en la llamada al servicio:

```python
    cid = svc.construir_corrida(alm, archivo.filename or "licitacion", items, turno, use_ai,
                                carpeta_id=carpeta_id, nombre=nombre,
                                lista_precios_id=lista_id)
```

```python
    gen = svc.construir_corrida_stream(alm, archivo.filename or "licitacion", items, turno,
                                       use_ai, carpeta_id=carpeta_id, nombre=nombre,
                                       lista_precios_id=lista_id)
```

Los endpoints `/sample` y `/sample/stream` **no** cambian: el ejemplo siempre es Principal.

- [ ] **Step 7: Correr los tests**

Run: `python -m pytest tests/test_servicio_insumos_lista.py -q`
Expected: PASS (8 passed)

Run: `python -m pytest tests/ -q`
Expected: PASS — vigilar `test_api_insumos.py`, `test_servicio_insumos.py`, `test_servicio_autoria.py`, `test_api_autoria.py`, `test_auditoria_servicios_precios.py` y `test_guard_precio_positivo.py`.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/insumos.py apu_tool/servicio/autoria.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_servicio_insumos_lista.py
git commit -m "feat(insumos): editar, crear e importar precios apuntando a una lista"
```

---

### Task 10: Costo de la biblioteca de APUs por lista

**Files:**
- Modify: `apu_tool/servicio/apus.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_servicio_apus_lista.py` (crear)

**Interfaces:**
- Consumes: `PricingEngine(alm, lista_id=…)` (Task 4).
- Produces: `apus_svc.listar(alm, q=None, grupo=None, turno=None, limit=100, offset=0, lista_id=None)` y `apus_svc.detalle(alm, codigo, turno, lista_id=None)`; query param `lista` en `GET /apus` y `GET /apus/{codigo}/{turno}`.

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_servicio_apus_lista.py`:

```python
"""El costo mostrado en la biblioteca de APUs depende de la lista consultada."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio import apus as apus_svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.corridas.init_schema()
    a.precios.insert_insumos([
        Insumo("6140", "ACERO 60000 PSI", "KG", "MATERIAL", 3500.0, "PRECIO IDU")])
    a.apus.insert_apus([Apu("NP-3002", "DEMOLICION", "M3", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("NP-3002", "DIURNO", "6140", "ACERO 60000 PSI", "KG", 2.0, 3000.0)])
    return a


@pytest.fixture()
def np(alm):
    lid = alm.precios.crear_lista("NP Calle 13")
    iid = alm.precios.get_candidatos("6140")[0].id
    alm.precios.set_precio_por_id(iid, 4200.0, "ACTA NP", lista_id=lid)
    return lid


def test_listar_costea_con_la_lista(alm, np):
    assert apus_svc.listar(alm)["items"][0]["costo_unitario"] == 7000
    assert apus_svc.listar(alm, lista_id=np)["items"][0]["costo_unitario"] == 8400


def test_detalle_costea_con_la_lista(alm, np):
    d = apus_svc.detalle(alm, "NP-3002", "DIURNO", lista_id=np)
    assert d["costo_unitario"] == 8400
    assert d["composicion"][0]["fuente_precio"] == "ACTA NP"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_servicio_apus_lista.py -q`
Expected: FAIL — `TypeError: listar() got an unexpected keyword argument 'lista_id'`

- [ ] **Step 3: Modificar `apu_tool/servicio/apus.py`**

```python
def listar(alm: Almacen, q: Optional[str] = None, grupo: Optional[str] = None,
           turno: Optional[str] = None, limit: int = 100, offset: int = 0,
           lista_id: Optional[int] = None) -> dict:
    items, total = alm.apus.list_apus(q, grupo, turno, limit, offset)
    counts = alm.apus.component_counts()
    # Costo unitario por APU de la página (para verlo sin desplegar). Un solo
    # PricingEngine reutiliza el caché de candidatos entre APUs, y queda atado a
    # `lista_id` (None = Principal). Ve dinero como el cuadro, pero NUNCA lo pasa
    # a la IA (Invariante #1).
    eng = PricingEngine(alm, lista_id=lista_id)
    out = []
    for a in items:
        _comp, costo = eng.cost_apu(a.codigo, a.shift)
        out.append({"codigo": a.codigo, "turno": a.shift, "nombre": a.nombre,
                    "unidad": a.unidad, "grupo": a.grupo,
                    "n_componentes": counts.get((a.codigo, a.shift), 0),
                    "costo_unitario": costo})
    return {"items": out, "total": total, "limit": limit, "offset": offset}


def detalle(alm: Almacen, codigo: str, turno: str,
            lista_id: Optional[int] = None) -> Optional[dict]:
    apu = alm.apus.get_apu(codigo, turno)
    if apu is None:
        return None
    costed, total = PricingEngine(alm, lista_id=lista_id).cost_apu(codigo, turno)
```

(el resto del cuerpo de `detalle` no cambia)

- [ ] **Step 4: Endpoints**

En `rutas.py`:

```python
@router.get("/apus")
def listar_apus(q: Optional[str] = None, grupo: Optional[str] = None,
                turno: Optional[str] = None, limit: int = 100, offset: int = 0,
                lista: Optional[int] = None,
                alm: Almacen = Depends(get_almacen),
                _: object = Depends(requiere_rol("consulta"))):
    return apus_svc.listar(alm, q, grupo, turno, limit, offset, lista)


@router.get("/apus/{codigo}/{turno}")
def detalle_apu(codigo: str, turno: str, lista: Optional[int] = None,
                alm: Almacen = Depends(get_almacen),
                _: object = Depends(requiere_rol("consulta"))):
    d = apus_svc.detalle(alm, codigo, turno, lista_id=lista)
    if d is None:
        raise HTTPException(status_code=404, detail="APU no encontrado.")
    return d
```

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_servicio_apus_lista.py -q`
Expected: PASS (2 passed)

Run: `python -m pytest tests/ -q`
Expected: PASS — el backend queda completo aquí.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/apus.py apu_tool/servicio/rutas.py tests/test_servicio_apus_lista.py
git commit -m "feat(apus): costo de la biblioteca contra una lista de precios"
```

---

### Task 11: Contrato del cliente (tipos y API)

**Files:**
- Create: `web/src/api/listas.ts`
- Modify: `web/src/lib/tipos.ts`, `web/src/api/insumos.ts`
- Test: `web/src/api/listas.test.ts` (crear)

**Interfaces:**
- Consumes: los endpoints de las Tasks 8-10.
- Produces:
  - `tipos.ListaPrecios { id: number; nombre: string; creada_en: string }`
  - `tipos.Insumo` gana `sin_precio: boolean`
  - `tipos.CorridaDetalle` y `tipos.CorridaResumen` ganan `lista_precios_id: number | null` y `lista_nombre: string`
  - `api/listas.ts`: `listarListas()`, `crearLista(nombre)`, `renombrarLista(id, nombre)`
  - `ListarInsumosParams` gana `lista?: number` y `sin_precio?: boolean`
  - `LISTA_PRINCIPAL_ID = 1` exportado desde `web/src/lib/tipos.ts`

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/api/listas.test.ts`, siguiendo el patrón de mock de `fetch` de
`web/src/api/carpetas.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { listarListas, crearLista, renombrarLista } from "@/api/listas";

function mockFetch(body: unknown) {
  const spy = vi.fn().mockResolvedValue({
    ok: true, status: 200, json: async () => body,
    headers: new Headers({ "content-type": "application/json" }),
  });
  vi.stubGlobal("fetch", spy);
  return spy;
}

beforeEach(() => vi.unstubAllGlobals());

describe("api de listas de precios", () => {
  it("listar pega a /api/listas-precios", async () => {
    const spy = mockFetch([{ id: 1, nombre: "Principal", creada_en: "2026-07-27" }]);
    const listas = await listarListas();
    expect(spy.mock.calls[0][0]).toContain("/listas-precios");
    expect(listas[0].nombre).toBe("Principal");
  });

  it("crear manda el nombre por POST", async () => {
    const spy = mockFetch({ id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" });
    const lista = await crearLista("NP Calle 13");
    expect(spy.mock.calls[0][1].method).toBe("POST");
    expect(JSON.parse(spy.mock.calls[0][1].body as string)).toEqual({ nombre: "NP Calle 13" });
    expect(lista.id).toBe(2);
  });

  it("renombrar usa PATCH sobre el id", async () => {
    const spy = mockFetch({ id: 2, nombre: "NP A2", creada_en: "2026-07-27" });
    await renombrarLista(2, "NP A2");
    expect(spy.mock.calls[0][0]).toContain("/listas-precios/2");
    expect(spy.mock.calls[0][1].method).toBe("PATCH");
  });
});
```

Añadir a `web/src/api/insumos.ts` un test en el archivo de tests que ya cubra
`buildQuery` (o crear `web/src/api/insumos.test.ts` si no existe):

```ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { listarInsumos } from "@/api/insumos";

beforeEach(() => vi.unstubAllGlobals());

describe("listarInsumos con lista", () => {
  it("propaga lista y sin_precio como query params", async () => {
    const spy = vi.fn().mockResolvedValue({
      ok: true, status: 200, json: async () => ({ items: [], total: 0, limit: 100, offset: 0 }),
      headers: new Headers({ "content-type": "application/json" }),
    });
    vi.stubGlobal("fetch", spy);
    await listarInsumos({ lista: 7, sin_precio: true });
    const url = String(spy.mock.calls[0][0]);
    expect(url).toContain("lista=7");
    expect(url).toContain("sin_precio=true");
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/api/listas.test.ts src/api/insumos.test.ts`
Expected: FAIL — `Failed to resolve import "@/api/listas"`

- [ ] **Step 3: Tipos en `web/src/lib/tipos.ts`**

```ts
// La lista 1 es SIEMPRE 'Principal' (el catálogo). Gemelo de config.LISTA_PRINCIPAL_ID.
export const LISTA_PRINCIPAL_ID = 1;

export interface ListaPrecios {
  id: number;
  nombre: string;
  creada_en: string;
}
```

En `interface Insumo`, añadir el campo:

```ts
export interface Insumo {
  id: number;
  codigo: string;
  nombre: string;
  unidad: string;
  grupo: string;
  precio: number;
  fuente: string;
  clasificacion: string;
  // true = no hay tarifa en la lista consultada. Distinto de un $0 genuino, que
  // la regla de negocio prohíbe y hay que seguir mostrando como $0.
  sin_precio: boolean;
}
```

En `CorridaDetalle` y `CorridaResumen`, añadir a ambas:

```ts
  lista_precios_id: number | null;
  lista_nombre: string;
```

- [ ] **Step 4: Crear `web/src/api/listas.ts`**

```ts
import { apiGet, apiPost, apiPatch } from "@/api/client";
import type { ListaPrecios } from "@/lib/tipos";

export function listarListas(): Promise<ListaPrecios[]> {
  return apiGet<ListaPrecios[]>("/listas-precios");
}

export function crearLista(nombre: string): Promise<ListaPrecios> {
  return apiPost<ListaPrecios>("/listas-precios", { nombre });
}

export function renombrarLista(id: number, nombre: string): Promise<ListaPrecios> {
  return apiPatch<ListaPrecios>(`/listas-precios/${id}`, { nombre });
}
```

Si `apiPatch` no existe en `web/src/api/client.ts`, añadirlo con la misma forma que
`apiPost` pero con `method: "PATCH"` (lo usa `carpetas.ts` para renombrar; reusar esa
implementación en vez de duplicarla).

- [ ] **Step 5: Parámetros en `web/src/api/insumos.ts`**

```ts
export interface ListarInsumosParams {
  q?: string;
  grupo?: string;
  fuente?: string;
  clasificacion?: string;
  limit?: number;
  offset?: number;
  lista?: number;
  sin_precio?: boolean;
}

function buildQuery(params: ListarInsumosParams): string {
  const qs = new URLSearchParams();
  if (params.q !== undefined) qs.set("q", params.q);
  if (params.grupo !== undefined) qs.set("grupo", params.grupo);
  if (params.fuente !== undefined) qs.set("fuente", params.fuente);
  if (params.clasificacion !== undefined) qs.set("clasificacion", params.clasificacion);
  if (params.limit !== undefined) qs.set("limit", String(params.limit));
  if (params.offset !== undefined) qs.set("offset", String(params.offset));
  if (params.lista !== undefined) qs.set("lista", String(params.lista));
  if (params.sin_precio) qs.set("sin_precio", "true");
  const str = qs.toString();
  return str ? `?${str}` : "";
}
```

Y las tres funciones que ahora dependen de la lista:

```ts
export function getFuentes(lista?: number): Promise<string[]> {
  return apiGet<string[]>(`/insumos/fuentes${lista !== undefined ? `?lista=${lista}` : ""}`);
}

export function getInsumo(id: number, lista?: number): Promise<InsumoDetalle> {
  return apiGet<InsumoDetalle>(`/insumos/${id}${lista !== undefined ? `?lista=${lista}` : ""}`);
}

export function aplicarCambios(cambios: CambioInput[], lista_id?: number): Promise<CambiosAplicados> {
  return apiPost<CambiosAplicados>("/insumos/cambios", { cambios, lista_id: lista_id ?? null });
}
```

- [ ] **Step 6: Correr los tests y el build**

Run: `cd web && npx vitest run src/api/listas.test.ts src/api/insumos.test.ts`
Expected: PASS

Run: `cd web && npm run build`
Expected: build OK. Si `tsc -b` marca errores en los componentes por el campo `sin_precio`
obligatorio, es esperado: los arregla la Task 12. En ese caso, dejar `sin_precio` como
obligatorio (es la fuente de verdad del backend) y continuar.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/listas.ts web/src/api/insumos.ts web/src/api/client.ts web/src/api/listas.test.ts web/src/api/insumos.test.ts
git commit -m "feat(web): contrato de cliente para listas de precios"
```

---

### Task 12: Página de Insumos con selector de lista

**Files:**
- Modify: `web/src/pages/Insumos.tsx`, `web/src/components/insumos/BarraFiltros.tsx`, `web/src/components/insumos/TablaInsumos.tsx`, `web/src/components/insumos/DialogoImportarInsumos.tsx`, `web/src/components/autoria/DialogoAgregarInsumo.tsx`
- Test: `web/src/pages/Insumos.test.tsx` (crear)

**Interfaces:**
- Consumes: `listarListas`, `listarInsumos({lista, sin_precio})`, `aplicarCambios(cambios, lista_id)`, `LISTA_PRINCIPAL_ID` (Task 11).
- Produces: `FiltrosState` gana `lista: number` (default `LISTA_PRINCIPAL_ID`) y `sinPrecio: boolean`.

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/pages/Insumos.test.tsx`, siguiendo el patrón de mocks de módulo de
`web/src/pages/MisCorridas.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import Insumos from "@/pages/Insumos";

const listarInsumos = vi.fn();
vi.mock("@/api/insumos", () => ({
  listarInsumos: (...a: unknown[]) => listarInsumos(...a),
  getFuentes: () => Promise.resolve([]),
  getGrupos: () => Promise.resolve([]),
  getInsumo: () => Promise.resolve(null),
  aplicarCambios: () => Promise.resolve({ aplicados: 0, errores: [] }),
}));
vi.mock("@/api/listas", () => ({
  listarListas: () => Promise.resolve([
    { id: 1, nombre: "Principal", creada_en: "2026-07-27" },
    { id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" },
  ]),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));

beforeEach(() => {
  listarInsumos.mockReset();
  listarInsumos.mockResolvedValue({
    items: [{ id: 1, codigo: "9", nombre: "CEMENTO GRIS", unidad: "KG", grupo: "MAT",
              precio: 0, fuente: "", clasificacion: "interno", sin_precio: true }],
    total: 1, limit: 100, offset: 0,
  });
});

describe("Insumos con listas de precios", () => {
  it("carga con la lista Principal por defecto", async () => {
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    expect(listarInsumos.mock.calls[0][0].lista).toBe(1);
  });

  it("muestra — cuando el insumo no tiene precio en la lista", async () => {
    render(<Insumos />);
    expect(await screen.findByText("—")).toBeInTheDocument();
  });

  it("avisa cuando la lista activa no es Principal", async () => {
    render(<Insumos />);
    await waitFor(() => expect(listarInsumos).toHaveBeenCalled());
    // El aviso solo aparece con una lista distinta de Principal; con Principal, no.
    expect(screen.queryByText(/editando la lista/i)).toBeNull();
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/pages/Insumos.test.tsx`
Expected: FAIL — `expect(listarInsumos.mock.calls[0][0].lista).toBe(1)` recibe `undefined`

- [ ] **Step 3: `BarraFiltros.tsx` — estado, selector y chip**

Ampliar `FiltrosState` y los props:

```tsx
export interface FiltrosState {
  q: string;
  grupo: string;
  fuente: string;
  clasificacion: string;
  lista: number;
  sinPrecio: boolean;
  offset: number;
}

interface BarraFiltrosProps {
  filtros: FiltrosState;
  listas: ListaPrecios[];
  total: number;
  limit: number;
  onChange: (f: Partial<FiltrosState>) => void;
}
```

`getFuentes` debe seguir la lista activa (las fuentes son de la lista, no globales):

```tsx
  useEffect(() => {
    getGrupos().then(setGrupos).catch(() => {});
  }, []);

  useEffect(() => {
    getFuentes(filtros.lista).then(setFuentes).catch(() => {});
  }, [filtros.lista]);
```

Selector de lista, **primero** en la barra (es el que manda sobre todo lo demás). Al
cambiar de lista se limpian `fuente`, `clasificacion` y `sinPrecio`, porque son
atributos de precios de la lista anterior:

```tsx
      <Select
        value={String(filtros.lista)}
        onValueChange={(v) =>
          onChange({ lista: Number(v), fuente: "", clasificacion: "", sinPrecio: false, offset: 0 })
        }
      >
        <SelectTrigger size="sm" className="w-44 text-xs">
          <SelectValue placeholder="Lista de precios" />
        </SelectTrigger>
        <SelectContent>
          {listas.map((l) => (
            <SelectItem key={l.id} value={String(l.id)}>
              {l.nombre}
            </SelectItem>
          ))}
        </SelectContent>
      </Select>
```

Botón de alternancia para "sin precio". Se deshabilita si hay fuente o clasificación
activas, porque el backend responde 400 con esa combinación:

```tsx
      <Button
        size="xs"
        variant={filtros.sinPrecio ? "default" : "outline"}
        disabled={Boolean(filtros.fuente || filtros.clasificacion)}
        title="Insumos sin tarifa en la lista seleccionada"
        onClick={() => onChange({ sinPrecio: !filtros.sinPrecio, offset: 0 })}
      >
        Sin precio
      </Button>
```

Y los selectores de fuente y clasificación se deshabilitan mientras `sinPrecio` esté
activo — añadir `disabled={filtros.sinPrecio}` al `SelectTrigger` de ambos.

Importar `ListaPrecios` de `@/lib/tipos`.

- [ ] **Step 4: `Insumos.tsx` — cargar listas, propagar y avisar**

```tsx
import { useEffect, useState, useCallback } from "react";
import { listarInsumos, type ListarInsumosParams } from "@/api/insumos";
import { listarListas } from "@/api/listas";
import { LISTA_PRINCIPAL_ID, type Insumo, type ListaPrecios } from "@/lib/tipos";
```

Estado inicial y carga:

```tsx
  const [filtros, setFiltros] = useState<FiltrosState>({
    q: "",
    grupo: "",
    fuente: "",
    clasificacion: "",
    lista: LISTA_PRINCIPAL_ID,
    sinPrecio: false,
    offset: 0,
  });
  const [listas, setListas] = useState<ListaPrecios[]>([]);

  const cargar = useCallback(async (f: FiltrosState) => {
    setCargando(true);
    setError(null);
    try {
      const params: ListarInsumosParams = {
        limit: LIMIT,
        offset: f.offset,
        lista: f.lista,
      };
      if (f.q) params.q = f.q;
      if (f.grupo) params.grupo = f.grupo;
      if (f.fuente) params.fuente = f.fuente;
      if (f.clasificacion) params.clasificacion = f.clasificacion;
      if (f.sinPrecio) params.sin_precio = true;

      const res = await listarInsumos(params);
      setInsumos(res.items);
      setTotal(res.total);
    } catch (e: unknown) {
      const msg = e instanceof Error ? e.message : "Error desconocido";
      setError(msg);
    } finally {
      setCargando(false);
    }
  }, []);

  useEffect(() => {
    listarListas().then(setListas).catch(() => {});
  }, []);
```

Eliminar el `useEffect` que llamaba a `getFuentes` y el estado `fuentes` de esta página
(ahora vive en `BarraFiltros`, que la recarga por lista); `TablaInsumos` recibe las
fuentes desde ahí — si `TablaInsumos` las necesita para su editor, subir el estado
`fuentes` a `Insumos.tsx` y recargarlo con `getFuentes(filtros.lista)` en un `useEffect`
que dependa de `filtros.lista`.

Aviso persistente cuando la lista activa no es Principal, justo debajo de la cabecera:

```tsx
      {filtros.lista !== LISTA_PRINCIPAL_ID && (
        <div className="px-4 py-1.5 text-xs border-b bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
          Editando la lista <span className="font-semibold">
            {listas.find((l) => l.id === filtros.lista)?.nombre ?? filtros.lista}
          </span>. Los precios que cambies aquí NO afectan la lista Principal.
        </div>
      )}
```

Pasar la lista a la barra y a los diálogos:

```tsx
      <BarraFiltros
        filtros={filtros}
        listas={listas}
        total={total}
        limit={LIMIT}
        onChange={cambiarFiltros}
      />
```

```tsx
          <DialogoImportarInsumos
            open={importarOpen}
            onOpenChange={setImportarOpen}
            listaId={filtros.lista}
            listaNombre={listas.find((l) => l.id === filtros.lista)?.nombre ?? "Principal"}
            onAplicado={recargar}
          />

          <DialogoAgregarInsumo
            open={agregarOpen}
            onOpenChange={setAgregarOpen}
            listaId={filtros.lista}
            onCreado={recargar}
          />
```

Y `TablaInsumos` recibe `listaId={filtros.lista}`.

- [ ] **Step 5: `TablaInsumos.tsx` — `—` y escritura en la lista**

Añadir `listaId: number` a los props. En la celda de precio (línea ~182), mostrar `—`
solo cuando el backend dice que no hay tarifa:

```tsx
                        {ins.sin_precio && dirty[ins.id]?.precio === undefined
                          ? <span className="text-muted-foreground">—</span>
                          : fmtMoneda(precioEdit as number)}
```

El guardado pasa la lista: buscar la llamada a `aplicarCambios(...)` y cambiarla por
`aplicarCambios(cambios, listaId)`. La carga del detalle también:
`getInsumo(id, listaId)`. En el panel de detalle, el precio vigente usa la misma regla:

```tsx
                <span className="font-medium">
                  {detalle.insumo.sin_precio ? "—" : fmtMoneda(detalle.insumo.precio)}
                </span>
```

- [ ] **Step 6: Diálogos de importar y agregar**

`DialogoImportarInsumos.tsx`: añadir props `listaId: number` y `listaNombre: string`,
adjuntar la lista al `FormData` en ambas llamadas y decir a qué lista se importa.

```tsx
      const form = new FormData();
      form.append("archivo", archivo);
      form.append("lista_id", String(listaId));
```

(en las dos: preview y aplicar). Y en la cabecera del diálogo:

```tsx
      <p className="text-xs text-muted-foreground">
        Se importará sobre la lista <span className="font-semibold">{listaNombre}</span>.
      </p>
```

`DialogoAgregarInsumo.tsx`: añadir el prop `listaId: number` e incluirlo en el cuerpo que
manda a `/insumos/crear` (`lista_id: listaId`).

- [ ] **Step 7: Correr tests y build**

Run: `cd web && npx vitest run`
Expected: PASS — toda la suite de Vitest, incluidos los tests existentes.

Run: `cd web && npm run build`
Expected: build OK (`tsc -b` sin errores).

- [ ] **Step 8: Commit**

```bash
git add web/src/pages/Insumos.tsx web/src/pages/Insumos.test.tsx web/src/components/insumos/ web/src/components/autoria/DialogoAgregarInsumo.tsx
git commit -m "feat(web): selector de lista en Insumos, aviso fuera de Principal y filtro sin precio"
```

---

### Task 13: Elegir y mostrar la lista en las corridas

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx`, `web/src/pages/Corrida.tsx`, `web/src/pages/MisCorridas.tsx`
- Test: `web/src/pages/CorridasInicio.test.tsx` (crear)

**Interfaces:**
- Consumes: `listarListas`, `LISTA_PRINCIPAL_ID`, `CorridaDetalle.lista_nombre`, `CorridaResumen.lista_nombre` (Task 11).
- Produces: el `FormData` de creación incluye `lista_id` cuando la lista elegida no es Principal.

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/pages/CorridasInicio.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import CorridasInicio from "@/pages/CorridasInicio";

vi.mock("@/api/listas", () => ({
  listarListas: () => Promise.resolve([
    { id: 1, nombre: "Principal", creada_en: "2026-07-27" },
    { id: 2, nombre: "NP Calle 13", creada_en: "2026-07-27" },
  ]),
}));
vi.mock("@/api/carpetas", () => ({ listarCarpetas: () => Promise.resolve([]) }));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));

describe("CorridasInicio", () => {
  it("ofrece las listas de precios disponibles", async () => {
    render(<CorridasInicio />);
    await waitFor(() => expect(screen.getByLabelText(/lista de precios/i)).toBeInTheDocument());
    expect(screen.getByRole("option", { name: "NP Calle 13" })).toBeInTheDocument();
    expect(screen.getByRole("option", { name: "Principal" })).toBeInTheDocument();
  });
});
```

Si el componente necesita un router o providers para montarse, envolverlo igual que en
`web/src/pages/MisCorridas.test.tsx`.

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/pages/CorridasInicio.test.tsx`
Expected: FAIL — `Unable to find a label with the text of: /lista de precios/i`

- [ ] **Step 3: Selector en `CorridasInicio.tsx`**

Esta página usa objetos `styles` en línea (no clases de Tailwind): seguir ese estilo.
Estado y carga:

```tsx
  const [listaId, setListaId] = useState<number>(LISTA_PRINCIPAL_ID);
  const [listas, setListas] = useState<ListaPrecios[]>([]);

  useEffect(() => {
    listarListas().then(setListas).catch(() => {});
  }, []);
```

Campo visible junto al nombre y la carpeta (no escondido: la lista es **inmutable**
después de crear la corrida, así que este es el único momento de acertar):

```tsx
            <label style={styles.label} htmlFor="lista">
              Lista de precios
            </label>
            <select
              id="lista"
              style={styles.input}
              value={listaId}
              onChange={(e) => setListaId(Number(e.target.value))}
            >
              {listas.map((l) => (
                <option key={l.id} value={l.id}>{l.nombre}</option>
              ))}
            </select>
            {listaId !== LISTA_PRINCIPAL_ID && (
              <p style={styles.aviso}>
                Esta corrida se costeará con la lista seleccionada y no se puede cambiar después.
              </p>
            )}
```

Añadir a `styles` una entrada `aviso` con el mismo lenguaje visual que el resto del
archivo (texto pequeño, color de énfasis).

Y en el envío (línea ~101):

```tsx
    const form = new FormData();
    form.append("archivo", archivo);
    form.append("use_ai", String(usarIA));
    form.append("carpeta_id", String(carpetaDestino));
    form.append("nombre", nombre.trim());
    if (listaId !== LISTA_PRINCIPAL_ID) form.append("lista_id", String(listaId));
```

Importar `listarListas` de `@/api/listas` y `LISTA_PRINCIPAL_ID`, `ListaPrecios` de
`@/lib/tipos`.

- [ ] **Step 4: Mostrarla en `Corrida.tsx`**

En el encabezado, junto al nombre y al indicador de modo (activa/congelada), añadir la
tarifa. Solo se destaca cuando no es Principal:

```tsx
        {corrida.lista_precios_id !== null && (
          <span className="px-1.5 py-0.5 rounded text-xs font-medium bg-amber-100 text-amber-900 dark:bg-amber-950 dark:text-amber-200">
            {corrida.lista_nombre}
          </span>
        )}
```

- [ ] **Step 5: Columna en `MisCorridas.tsx`**

Añadir una columna `Lista` a la tabla de corridas, entre el nombre y el estado, para no
confundir un cuadro NP con uno contractual:

```tsx
              <td className="px-2 py-1 text-xs">
                {c.lista_precios_id === null
                  ? <span className="text-muted-foreground">Principal</span>
                  : <span className="font-medium">{c.lista_nombre}</span>}
              </td>
```

y su `<th>` correspondiente (`Lista`) en la cabecera de la tabla.

- [ ] **Step 6: Correr tests y build**

Run: `cd web && npx vitest run`
Expected: PASS

Run: `cd web && npm run build`
Expected: build OK

- [ ] **Step 7: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx web/src/pages/CorridasInicio.test.tsx web/src/pages/Corrida.tsx web/src/pages/MisCorridas.tsx
git commit -m "feat(web): elegir la lista al crear la corrida y mostrarla en la corrida y el listado"
```

---

### Task 14: Documentación y verificación final

**Files:**
- Modify: `CLAUDE.md`, `docs/ARQUITECTURA.md`
- Create: `docs/listas-precios-np.md`

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: documentación; ningún cambio de código.

- [ ] **Step 1: Actualizar `CLAUDE.md`**

En la tabla de `apu_tool/servicio/`, añadir la fila (orden alfabético cerca de `insumos.py`):

```markdown
| `listas.py`            | listas de precios (tarifas): Principal + una por obra de NP |
```

En la sección **Datos**, tras el párrafo de las bases locales:

```markdown
- **Listas de precios (tarifas).** El precio de un insumo es *por lista*: la lista
  `Principal` (id 1) es la del catálogo, y cada obra de No Previstos (NP) puede tener la
  suya. Una corrida elige su lista **al crearse** y no la cambia. Costeando contra una
  lista que no es Principal, un insumo sin tarifa **no** cae al precio histórico
  embebido: queda en $0 con alerta explícita, porque usar el histórico sería cobrar el
  no previsto con la tarifa contractual sin que nadie se entere.
```

En **No hacer**:

```markdown
- No hagas que una lista que no sea Principal caiga al precio histórico ni al de
  Principal: el respaldo silencioso es justo lo que esta feature evita.
- No borres listas de precios: una corrida guarda su `lista_precios_id` sin FK.
```

- [ ] **Step 2: Actualizar `docs/ARQUITECTURA.md`**

Añadir `apu_tool/servicio/listas.py` al inventario de módulos y mencionar la tabla
`lista_precios` y la columna `insumo_precios.lista_id` donde se describa el esquema de
`precios.db`, más `corrida.lista_precios_id` en el de `corridas.db`.

- [ ] **Step 3: Crear `docs/listas-precios-np.md`**

Guía corta de operación, con estas secciones:

```markdown
# Listas de precios y APUs de No Previstos (NP)

## Qué resuelve
Cobrar actividades que no estaban presupuestadas, con la tarifa acordada para esa obra.

## Cómo se usa
1. **Crear la lista.** Insumos → selector de lista → crear (rol editor). Nómbrala con la
   obra: `NP Calle 13`.
2. **Cargarla.** Con el selector en esa lista: *Importar* un Excel (columnas `codigo`,
   `nombre`, `unidad`, `grupo`, `precio`, `fuente`) o editar precios a mano en la tabla.
   El import crea los insumos que no existan en el catálogo.
3. **Completarla.** El botón *Sin precio* filtra los insumos que aún no tienen tarifa en
   la lista. Mientras queden, los APUs que los usen costearán en $0 con alerta.
4. **Armar la corrida.** Nueva corrida → *Lista de precios* → la lista NP. **No se puede
   cambiar después.** Los APUs de NP son APUs normales con código `NP-xxxx`, en la misma
   biblioteca.
5. **Emitir.** El cuadro trae la fila `Lista de precios` en la hoja `INFO`.

## Reglas
- La lista `Principal` (id 1) no se renombra ni se borra.
- Ninguna lista se borra (dejaría corridas huérfanas de su tarifa).
- Un insumo sin tarifa en la lista **no** hereda el precio de Principal ni el histórico:
  queda en $0 con la alerta *«sin precio en la lista»*.
- Congelar una corrida fija sus números: editar la lista después no los mueve.

## Despliegue
La migración es aditiva (`ADD COLUMN` con `DEFAULT 1`) y no necesita backfill. Validarla
contra el Postgres real antes de desplegar, como se hizo con nombre/alias de corridas.
```

- [ ] **Step 4: Verificación final completa**

Run: `python -m pytest tests/ -q`
Expected: PASS, toda la suite.

Run: `cd web && npm run build && npx vitest run`
Expected: build OK y todos los tests de Vitest en verde.

Run: `python run_cli.py status`
Expected: corre sin error (el camino CLI sigue en Principal).

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md docs/ARQUITECTURA.md docs/listas-precios-np.md
git commit -m "docs: listas de precios y flujo de APUs para No Previstos"
```

---

## Antes de desplegar

1. **Validar la migración contra el Postgres real** (no solo contra SQLite). Es aditiva y
   con `DEFAULT`, sin backfill, pero el `ADD COLUMN ... REFERENCES` toma un lock breve
   sobre `precios.insumo_precios`, que en producción tiene ~8157 insumos y su historial.
2. **Verificar que la lista Principal quedó sembrada** con id 1 en producción y que
   `SELECT count(*) FROM precios.insumo_precios WHERE lista_id <> 1` devuelve 0.
3. **Smoke test en el navegador:** crear una lista, importar 2-3 precios, armar una
   corrida contra ella, comprobar la alerta "sin precio en la lista" y descargar el
   cuadro para ver la fila `Lista de precios` en la hoja `INFO`.
