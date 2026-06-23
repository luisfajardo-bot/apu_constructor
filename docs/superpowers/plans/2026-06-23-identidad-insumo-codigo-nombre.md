# Identidad de insumo por (código + nombre) — Plan de Implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que un insumo se identifique por (código + nombre) y que el costeo cruce por ambos, con coincidencia difusa que avisa la calidad del cruce, para que los códigos repetidos del IDU (hoja `INSUMOS_IDU-INT`) dejen de cruzar precios equivocados.

**Architecture:** `insumos` pasa a tener un `id` interno con `UNIQUE(codigo, nombre_norm)`; el libro `insumo_precios` cuelga del `id`. Un resolver de dominio (`cruce.py`) elige el insumo correcto entre los candidatos de un código, comparando nombres con `matching.similarity`; el motor de costos lo usa y propaga una `calidad_cruce` (exacto/aproximado/ambiguo/huérfano). La normalización de texto se centraliza en `nucleo/texto.py`.

**Tech Stack:** Python 3, SQLite (stdlib `sqlite3`), `openpyxl`, `pytest`. Sin dependencias nuevas.

## Global Constraints

- **Invariante #1 — la IA nunca ve dinero.** Todo este trabajo vive en `dominio/pricing.py`, `dominio/cruce.py` y `datos/`. Nada de esto entra en payloads de IA. No tocar `dominio/privacy.py` ni `ai_assist.py`.
- **Persistencia aislada en la capa `datos/`.** Nada de SQL crudo fuera de `precios_db.py`/`apus_db.py`.
- **Capas:** `datos` no importa de `dominio`; ambas importan de `nucleo`. Por eso la normalización va en `nucleo/texto.py` y el chequeo de integridad (que usa el resolver de `dominio`) **se mueve** a `dominio/`.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin git:** este proyecto NO es un repo git. Los pasos rotulados **"Checkpoint"** significan: correr `python -m pytest tests/ -q` y confirmar verde antes de pasar a la siguiente tarea. Si más adelante se inicializa git, conviértelos en commits.
- **Comando de pruebas:** `python -m pytest tests/ -q` (toda la suite) o `python -m pytest tests/test_X.py -v` (un archivo).
- **Migración:** el esquema cambia; tras implementar hay que re-semillar con `python run_cli.py seed --force`. No hay migración de datos (la base es derivada del Excel).

---

### Task 1: Normalización de texto centralizada — `nucleo/texto.py`

Hoy la normalización está duplicada en `matching.normalize` (dominio) y `integridad._norm` (datos). Se crea una única definición en la capa núcleo y `matching` delega en ella.

**Files:**
- Create: `apu_tool/nucleo/texto.py`
- Modify: `apu_tool/dominio/matching.py:14-42` (delegar `normalize`, quitar `_strip_accents` y los imports que queden sin uso)
- Test: `tests/test_texto.py`

**Interfaces:**
- Produces: `apu_tool.nucleo.texto.normalizar(texto: str) -> str` (sin tildes, MAYÚSCULAS, sin puntuación, espacios colapsados).

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_texto.py
from apu_tool.nucleo.texto import normalizar


def test_normaliza_tildes_mayusculas_y_espacios():
    assert normalizar("  Camión  de   Volteo  ") == "CAMION DE VOLTEO"

def test_normaliza_puntuacion_a_espacio():
    assert normalizar('CODO 90° D=8" RDE-21.') == "CODO 90 D 8 RDE 21"

def test_normaliza_none_y_vacio():
    assert normalizar(None) == ""
    assert normalizar("") == ""
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_texto.py -v`
Expected: FAIL — `ModuleNotFoundError: No module named 'apu_tool.nucleo.texto'`

- [ ] **Step 3: Implementar `nucleo/texto.py`**

```python
# apu_tool/nucleo/texto.py
"""
Normalización de texto compartida (capa núcleo, sin dependencias).

Una sola definición de "normalizar un nombre": sin tildes, MAYÚSCULAS, sin
puntuación, espacios colapsados. La usan el seed (para `nombre_norm`), la capa de
datos, el resolver de cruce y el chequeo de integridad. Antes estaba duplicada en
`matching.normalize` y en `integridad._norm`.
"""
from __future__ import annotations

import re
import unicodedata


def _sin_tildes(texto: str) -> str:
    return "".join(
        c for c in unicodedata.normalize("NFD", texto)
        if unicodedata.category(c) != "Mn"
    )


def normalizar(texto: str) -> str:
    t = _sin_tildes((texto or "").upper())
    t = re.sub(r"[^A-Z0-9 ]+", " ", t)
    t = re.sub(r"\s+", " ", t).strip()
    return t
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python -m pytest tests/test_texto.py -v`
Expected: PASS (3 passed)

- [ ] **Step 5: Hacer que `matching.normalize` delegue**

En `apu_tool/dominio/matching.py`, reemplazar las líneas 14-42 (los imports `re`/`unicodedata`, `_strip_accents` y `normalize`) por:

```python
from functools import lru_cache

from apu_tool import config
from apu_tool.nucleo.models import LicitacionItem, MatchCandidate, MatchResult, MatchStatus
from apu_tool.nucleo.texto import normalizar as _normalizar

_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "y", "o", "en", "para", "por", "con",
    "incluye", "incluido", "no", "un", "una", "a", "e", "su", "al", "segun",
    "tipo", "obra", "ml", "m2", "m3", "und", "un",
}


@lru_cache(maxsize=20000)
def normalize(text: str) -> str:
    return _normalizar(text)
```

(Se eliminan `import re`, `import unicodedata` y `_strip_accents`: ya no se usan en este módulo. `_tokens` y `similarity` siguen igual, llamando a `normalize`.)

- [ ] **Step 6: Checkpoint — correr toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (incluido `tests/test_matching.py`, cuyo comportamiento de `normalize` es idéntico).

---

### Task 2: Capa de datos con identidad (código + nombre) — esquema + `precios_db.py`

Cambia el esquema (id interno + `UNIQUE(codigo, nombre_norm)`, precios por `insumo_id`) y la capa de datos. Se mantiene un `get_insumo(codigo)` **transitorio** (devuelve el primer candidato) para que `pricing`/`assemble`/`cli`/`integridad` sigan funcionando hasta migrarlos; se retira en la Tarea 10.

**Files:**
- Modify: `db/precios.sql` (esquema completo)
- Modify: `apu_tool/nucleo/models.py:22-36` (campo `id` en `Insumo`)
- Modify: `apu_tool/datos/precios_db.py` (insert/lecturas/escritura por id)
- Modify: `apu_tool/datos/repositorio.py:15-28` (Protocol)
- Test: `tests/test_precios_db.py` (reescribir), `tests/test_db_repository.py` (ajustar `set_precio`/`price_history`)

**Interfaces:**
- Consumes: `apu_tool.nucleo.texto.normalizar` (Tarea 1).
- Produces:
  - `Insumo(..., id: Optional[int] = None)` — campo nuevo al final, no rompe construcción posicional.
  - `PreciosDB.get_candidatos(codigo: str) -> list[Insumo]` — todos los insumos con ese código (cada uno con su precio vigente y su `id`).
  - `PreciosDB.get_insumo_por_id(insumo_id: int) -> Optional[Insumo]`.
  - `PreciosDB.set_precio(codigo, precio, fuente="", fecha=None, nombre=None)` — `nombre` desambigua códigos repetidos; lanza `ValueError` si el código resuelve a ≠1 insumo.
  - `PreciosDB.price_history(codigo, nombre=None) -> list[dict]`.
  - `PreciosDB.get_insumo(codigo) -> Optional[Insumo]` — **transitorio**, devuelve el primer candidato.

- [ ] **Step 1: Escribir el esquema nuevo en `db/precios.sql`**

```sql
-- Esquema canónico de precios.db — catálogo de insumos y libro de precios.
-- SQL portable (SQLite hoy; Postgres luego). Cargado por apu_tool/datos/precios_db.py.
--
-- El código NO es único: el IDU repite códigos para insumos distintos. La identidad
-- es (codigo, nombre_norm); el precio cuelga del id interno del insumo.

CREATE TABLE IF NOT EXISTS insumos (
    id          INTEGER PRIMARY KEY,   -- rowid de SQLite; sin AUTOINCREMENT (porta a Postgres)
    codigo      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    nombre_norm TEXT NOT NULL,         -- normalizado (apu_tool/nucleo/texto.py)
    unidad      TEXT,
    grupo       TEXT,
    UNIQUE (codigo, nombre_norm)
);
CREATE INDEX IF NOT EXISTS idx_insumo_cod ON insumos(codigo);

CREATE TABLE IF NOT EXISTS insumo_precios (
    -- SQLite autollena un INTEGER PRIMARY KEY (rowid); sin AUTOINCREMENT para portar limpio.
    -- Postgres: id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY
    id            INTEGER PRIMARY KEY,
    insumo_id     INTEGER NOT NULL,
    precio        REAL NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,          -- 'publico' | 'interno'
    fecha         TEXT,          -- ISO (YYYY-MM-DD)
    vigente       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (insumo_id) REFERENCES insumos(id)
);

CREATE TABLE IF NOT EXISTS meta (
    clave TEXT PRIMARY KEY,
    valor TEXT
);

CREATE INDEX IF NOT EXISTS idx_precio_ins ON insumo_precios(insumo_id, vigente);
```

- [ ] **Step 2: Añadir `id` a `Insumo` en `nucleo/models.py`**

En `apu_tool/nucleo/models.py`, reemplazar el bloque de `class Insumo` (líneas 22-36) por:

```python
@dataclass(frozen=True)
class Insumo:
    codigo: str
    nombre: str
    unidad: str
    grupo: str
    precio: float
    fuente_precio: str          # "PRECIO IDU", "COSTO INTERNO", etc.
    id: Optional[int] = None    # id interno del catálogo (None si aún no persistido)

    @property
    def es_confidencial(self) -> bool:
        from apu_tool.config import PUBLIC_PRICE_SOURCES
        return (self.fuente_precio or "").strip().upper() not in {
            s.upper() for s in PUBLIC_PRICE_SOURCES
        }
```

(`Optional` ya está importado en `models.py`.)

- [ ] **Step 3: Reescribir las pruebas de `tests/test_precios_db.py`**

```python
import sqlite3
import pytest
from apu_tool.datos.precios_db import PreciosDB
from apu_tool.datos.repositorio import RepositorioPrecios
from apu_tool.nucleo.models import Insumo


@pytest.fixture()
def precios(tmp_path):
    d = PreciosDB(tmp_path / "precios.db")
    d.reset()
    d.insert_insumos([
        Insumo("100", "CEMENTO GRIS", "KG", "MAT", 1000, "PRECIO IDU"),
        Insumo("200", "ACERO FIGURADO", "KG", "MAT", 5000, "COSTO INTERNO"),
        # mismo código 100, insumo distinto -> debe convivir
        Insumo("100", "BASE GRANULAR", "M3", "MAT", 190300, "PRECIO IDU"),
    ])
    return d


def test_cumple_contrato(precios):
    assert isinstance(precios, RepositorioPrecios)

def test_codigo_repetido_convive(precios):
    cands = precios.get_candidatos("100")
    assert len(cands) == 2
    nombres = {c.nombre for c in cands}
    assert nombres == {"CEMENTO GRIS", "BASE GRANULAR"}

def test_candidato_trae_id_y_precio(precios):
    cem = [c for c in precios.get_candidatos("100") if c.nombre == "CEMENTO GRIS"][0]
    assert cem.id is not None and cem.precio == 1000
    assert precios.get_insumo_por_id(cem.id).nombre == "CEMENTO GRIS"

def test_clasificacion(precios):
    base = [c for c in precios.get_candidatos("100") if c.nombre == "BASE GRANULAR"][0]
    assert base.es_confidencial is False
    assert precios.get_candidatos("200")[0].es_confidencial is True

def test_set_precio_desambigua_por_nombre(precios):
    precios.set_precio("100", 1500, fuente="COMPRAS 2026", nombre="CEMENTO GRIS")
    cem = [c for c in precios.get_candidatos("100") if c.nombre == "CEMENTO GRIS"][0]
    base = [c for c in precios.get_candidatos("100") if c.nombre == "BASE GRANULAR"][0]
    assert cem.precio == 1500 and base.precio == 190300  # solo cambió el cemento
    hist = precios.price_history("100", nombre="CEMENTO GRIS")
    assert sum(h["vigente"] for h in hist) == 1 and len(hist) == 2

def test_set_precio_codigo_ambiguo_sin_nombre_falla(precios):
    with pytest.raises(ValueError):
        precios.set_precio("100", 1500)   # 100 es ambiguo, falta --nombre

def test_fk_precio_requiere_insumo(precios):
    with pytest.raises(sqlite3.IntegrityError):
        with precios.connect() as c:
            c.execute("INSERT INTO insumo_precios (insumo_id, precio, vigente) "
                      "VALUES (999999, 1, 1)")

def test_busqueda(precios):
    assert any(i.codigo == "100" for i in precios.search_insumos("CEMENTO"))
    assert any(i.codigo == "200" for i in precios.search_insumos_por_palabras(["ACERO"]))

def test_counts(precios):
    c = precios.counts()
    assert c["insumos"] == 3 and c["insumo_precios"] == 3
```

- [ ] **Step 4: Correr y verificar que falla**

Run: `python -m pytest tests/test_precios_db.py -v`
Expected: FAIL (métodos `get_candidatos`/`get_insumo_por_id` no existen; esquema viejo).

- [ ] **Step 5: Reescribir `apu_tool/datos/precios_db.py`**

Reemplazar el cuerpo de la clase (de `# ---- escritura ----` en adelante, líneas 55-143) por:

```python
    # ---- escritura ----
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int:
        hoy = date.today().isoformat()
        n = 0
        with self.connect() as conn:
            for i in insumos:
                nombre_norm = normalizar(i.nombre)
                cur = conn.execute(
                    "INSERT OR IGNORE INTO insumos "
                    "(codigo, nombre, nombre_norm, unidad, grupo) VALUES (?,?,?,?,?)",
                    (i.codigo, i.nombre, nombre_norm, i.unidad, i.grupo))
                if not cur.rowcount:
                    continue  # identidad (codigo, nombre_norm) ya existía; no duplicar precio
                iid = cur.lastrowid
                conn.execute(
                    "INSERT INTO insumo_precios "
                    "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                    "VALUES (?,?,?,?,?,1)",
                    (iid, i.precio, i.fuente_precio,
                     config.classify_price_source(i.fuente_precio), hoy))
                n += 1
        return n

    def _ids_de(self, conn, codigo: str, nombre: Optional[str]) -> list[int]:
        if nombre is None:
            rows = conn.execute("SELECT id FROM insumos WHERE codigo=?",
                                (str(codigo),)).fetchall()
        else:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE codigo=? AND nombre_norm=?",
                (str(codigo), normalizar(nombre))).fetchall()
        return [r["id"] for r in rows]

    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None, nombre: Optional[str] = None) -> None:
        fecha = fecha or date.today().isoformat()
        with self.connect() as conn:
            ids = self._ids_de(conn, codigo, nombre)
            if len(ids) != 1:
                raise ValueError(
                    f"Código {codigo} resuelve a {len(ids)} insumos; "
                    f"especifica el nombre exacto para desambiguar.")
            iid = ids[0]
            conn.execute("UPDATE insumo_precios SET vigente=0 WHERE insumo_id=?", (iid,))
            conn.execute(
                "INSERT INTO insumo_precios "
                "(insumo_id, precio, fuente, clasificacion, fecha, vigente) "
                "VALUES (?,?,?,?,?,1)",
                (iid, float(precio), fuente,
                 config.classify_price_source(fuente), fecha))

    def set_meta(self, clave: str, valor: str) -> None:
        with self.connect() as conn:
            conn.execute("INSERT OR REPLACE INTO meta (clave, valor) VALUES (?,?)",
                         (clave, str(valor)))

    # ---- lectura ----
    def _fila_a_insumo(self, r) -> Insumo:
        return Insumo(codigo=r["codigo"], nombre=r["nombre"], unidad=r["unidad"] or "",
                      grupo=r["grupo"] or "", precio=r["precio"] or 0.0,
                      fuente_precio=r["fuente"] or "", id=r["id"])

    def get_candidatos(self, codigo: str) -> list[Insumo]:
        """Todos los insumos con ese código (cada uno con su precio vigente e id)."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM insumos i LEFT JOIN insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.codigo = ? ORDER BY i.id", (str(codigo),)).fetchall()
        return [self._fila_a_insumo(r) for r in rows]

    def get_insumo_por_id(self, insumo_id: int) -> Optional[Insumo]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente "
                "FROM insumos i LEFT JOIN insumo_precios p "
                "  ON p.insumo_id = i.id AND p.vigente = 1 "
                "WHERE i.id = ?", (int(insumo_id),)).fetchone()
        return self._fila_a_insumo(r) if r else None

    def get_insumo(self, codigo: str) -> Optional[Insumo]:
        """TRANSITORIO (se retira en la Tarea 10): primer candidato del código."""
        cands = self.get_candidatos(codigo)
        return cands[0] if cands else None

    def price_history(self, codigo: str, nombre: Optional[str] = None) -> list[dict]:
        with self.connect() as conn:
            q = ("SELECT p.precio, p.fuente, p.clasificacion, p.fecha, p.vigente "
                 "FROM insumo_precios p JOIN insumos i ON i.id = p.insumo_id "
                 "WHERE i.codigo = ?")
            params: list = [str(codigo)]
            if nombre is not None:
                q += " AND i.nombre_norm = ?"
                params.append(normalizar(nombre))
            q += " ORDER BY p.id"
            rows = conn.execute(q, params).fetchall()
        return [dict(r) for r in rows]

    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]:
        like = f"%{texto.strip()}%"
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT id FROM insumos WHERE nombre LIKE ? OR codigo LIKE ? LIMIT ?",
                (like, like, limit)).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def search_insumos_por_palabras(self, palabras: list[str], limit: int = 60) -> list[Insumo]:
        """Insumos cuyo nombre contiene alguna de las `palabras` (ya tokenizadas por el dominio)."""
        palabras = [p for p in palabras if p]
        if not palabras:
            return []
        clauses = " OR ".join(["nombre LIKE ?"] * len(palabras))
        params = [f"%{p}%" for p in palabras] + [limit]
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT id FROM insumos WHERE {clauses} LIMIT ?", params).fetchall()
        return [self.get_insumo_por_id(r["id"]) for r in rows]

    def counts(self) -> dict[str, int]:
        with self.connect() as conn:
            return {t: conn.execute(f"SELECT COUNT(*) FROM {t}").fetchone()[0]
                    for t in ("insumos", "insumo_precios")}

    def get_meta(self) -> dict[str, str]:
        with self.connect() as conn:
            return {r["clave"]: r["valor"]
                    for r in conn.execute("SELECT clave, valor FROM meta").fetchall()}
```

Y añadir el import al inicio del archivo (junto a los otros), tras `from apu_tool.nucleo.models import Insumo`:

```python
from apu_tool.nucleo.texto import normalizar
```

- [ ] **Step 6: Correr y verificar que pasa**

Run: `python -m pytest tests/test_precios_db.py -v`
Expected: PASS.

- [ ] **Step 7: Actualizar el Protocol en `repositorio.py`**

En `apu_tool/datos/repositorio.py`, reemplazar las líneas 18-25 (firmas de `RepositorioPrecios`) por:

```python
    def insert_insumos(self, insumos: Iterable[Insumo]) -> int: ...
    def get_candidatos(self, codigo: str) -> list[Insumo]: ...
    def get_insumo_por_id(self, insumo_id: int) -> Optional[Insumo]: ...
    def get_insumo(self, codigo: str) -> Optional[Insumo]: ...   # transitorio (Tarea 10)
    def set_precio(self, codigo: str, precio: float, fuente: str = "",
                   fecha: Optional[str] = None, nombre: Optional[str] = None) -> None: ...
    def price_history(self, codigo: str, nombre: Optional[str] = None) -> list[dict]: ...
    def search_insumos(self, texto: str, limit: int = 20) -> list[Insumo]: ...
    def search_insumos_por_palabras(self, palabras: list[str],
                                    limit: int = 60) -> list[Insumo]: ...
```

- [ ] **Step 8: Ajustar `tests/test_db_repository.py`**

En `tests/test_db_repository.py`, la prueba `test_set_precio_changes_current_and_keeps_history` usa códigos únicos, así que `set_precio("100", ...)` resuelve a 1 insumo y sigue funcionando. No requiere cambios. Verificar:

Run: `python -m pytest tests/test_db_repository.py -v`
Expected: PASS (sus códigos 100/200 son únicos; `get_insumo` transitorio y `set_precio` resuelven bien).

- [ ] **Step 9: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. (`test_esquemas_separados` sigue verde: las tablas `insumos`/`insumo_precios`/`meta` existen.)

---

### Task 3: Resolver del cruce — `dominio/cruce.py` + umbrales en `config.py`

**Files:**
- Modify: `apu_tool/config.py` (umbrales)
- Create: `apu_tool/dominio/cruce.py`
- Test: `tests/test_cruce.py`

**Interfaces:**
- Consumes: `Insumo` (con `nombre`), `matching.similarity`, `nucleo.texto.normalizar`, `config.CRUCE_UMBRAL`, `config.CRUCE_MARGEN`.
- Produces:
  - `CalidadCruce` (Enum str): `EXACTO`, `APROXIMADO`, `AMBIGUO`, `HUERFANO`.
  - `ResultadoCruce(insumo: Optional[Insumo], calidad: CalidadCruce, score: float)`.
  - `resolver(candidatos: list[Insumo], nombre_apu: str) -> ResultadoCruce`.

- [ ] **Step 1: Añadir umbrales a `config.py`**

Tras la línea 35 de `apu_tool/config.py` (después de los umbrales del matcher), añadir:

```python
# Umbrales del cruce código+nombre (resolver de insumos, dominio/cruce.py).
CRUCE_UMBRAL = 0.60   # similitud mínima de nombre para aceptar un cruce aproximado
CRUCE_MARGEN = 0.10   # ventaja mínima del mejor candidato sobre el segundo
```

- [ ] **Step 2: Escribir el test que falla**

```python
# tests/test_cruce.py
from apu_tool.dominio.cruce import resolver, CalidadCruce
from apu_tool.nucleo.models import Insumo


def _ins(cod, nom): return Insumo(cod, nom, "UN", "G", 100, "PRECIO IDU", id=1)


def test_huerfano_sin_candidatos():
    r = resolver([], "CEMENTO GRIS")
    assert r.calidad == CalidadCruce.HUERFANO and r.insumo is None

def test_exacto_por_nombre_normalizado():
    cands = [_ins("100", "BASE GRANULAR"), _ins("100", "CEMENTO GRIS")]
    r = resolver(cands, "  cemento   gris ")
    assert r.calidad == CalidadCruce.EXACTO and r.insumo.nombre == "CEMENTO GRIS"

def test_aproximado_cuando_uno_destaca():
    cands = [_ins("100", "DUCTO TELEFONICO LIVIANO PVC TIPO EB D=3"),
             _ins("100", "BASE GRANULAR CLASE C")]
    r = resolver(cands, "DUCTO TELEFONICO PVC EB 3")
    assert r.calidad == CalidadCruce.APROXIMADO and "DUCTO" in r.insumo.nombre

def test_ambiguo_cuando_ningun_nombre_se_parece():
    cands = [_ins("100", "BASE GRANULAR CLASE C"),
             _ins("100", "SOBRECARPETA RODADURA ASFALTICA")]
    r = resolver(cands, "TORNILLO HEXAGONAL 1 PULGADA")
    assert r.calidad == CalidadCruce.AMBIGUO and r.insumo is None

def test_un_solo_candidato_nombre_lejano_es_ambiguo():
    # caso "código sospechoso" estilo 4613: el único insumo del código no se parece
    cands = [_ins("4613", "UNION PVC D=10")]
    r = resolver(cands, "TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS")
    assert r.calidad == CalidadCruce.AMBIGUO and r.insumo is None
```

- [ ] **Step 3: Correr y verificar que falla**

Run: `python -m pytest tests/test_cruce.py -v`
Expected: FAIL — `No module named 'apu_tool.dominio.cruce'`.

- [ ] **Step 4: Implementar `dominio/cruce.py`**

```python
# apu_tool/dominio/cruce.py
"""
Resolución del cruce insumo-de-APU -> insumo-de-catálogo, por código + nombre.

Un código puede no ser único en el catálogo (el IDU repite códigos para insumos
distintos). Este resolver recibe los candidatos de un código y el nombre que el APU
cita, y decide cuál es —o avisa que no se puede resolver con confianza—.

Sin dinero: solo compara nombres. Lo usan el motor de costos y el chequeo de integridad.
"""
from __future__ import annotations

from dataclasses import dataclass
from enum import Enum
from typing import Optional

from apu_tool import config
from apu_tool.dominio.matching import similarity
from apu_tool.nucleo.models import Insumo
from apu_tool.nucleo.texto import normalizar


class CalidadCruce(str, Enum):
    EXACTO = "exacto"          # código coincide y nombre normalizado idéntico
    APROXIMADO = "aproximado"  # código coincide y un nombre destaca por similitud
    AMBIGUO = "ambiguo"        # código coincide pero el nombre no resuelve a uno solo
    HUERFANO = "huerfano"      # ningún insumo tiene ese código


@dataclass(frozen=True)
class ResultadoCruce:
    insumo: Optional[Insumo]   # None si AMBIGUO o HUERFANO
    calidad: CalidadCruce
    score: float               # similitud del mejor candidato (0..1)


def resolver(candidatos: list[Insumo], nombre_apu: str) -> ResultadoCruce:
    if not candidatos:
        return ResultadoCruce(None, CalidadCruce.HUERFANO, 0.0)

    objetivo = normalizar(nombre_apu)
    # 1) Coincidencia exacta de nombre normalizado (única por UNIQUE(codigo, nombre_norm)).
    for c in candidatos:
        if normalizar(c.nombre) == objetivo:
            return ResultadoCruce(c, CalidadCruce.EXACTO, 1.0)

    # 2) Mejor coincidencia difusa, con margen sobre el segundo.
    puntuados = sorted(
        ((similarity(nombre_apu, c.nombre), c) for c in candidatos),
        key=lambda t: t[0], reverse=True,
    )
    mejor_score, mejor = puntuados[0]
    segundo_score = puntuados[1][0] if len(puntuados) > 1 else 0.0
    if mejor_score >= config.CRUCE_UMBRAL and (mejor_score - segundo_score) >= config.CRUCE_MARGEN:
        return ResultadoCruce(mejor, CalidadCruce.APROXIMADO, mejor_score)
    return ResultadoCruce(None, CalidadCruce.AMBIGUO, mejor_score)
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `python -m pytest tests/test_cruce.py -v`
Expected: PASS (5 passed).

- [ ] **Step 6: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

---

### Task 4: Motor de costos por código + nombre — `pricing.py` + `CostedComponent.calidad_cruce`

**Files:**
- Modify: `apu_tool/nucleo/models.py` (`CostedComponent` gana `calidad_cruce`)
- Modify: `apu_tool/dominio/pricing.py` (resolver por código+nombre, propagar calidad)
- Test: `tests/test_pricing_cruce.py`

**Interfaces:**
- Consumes: `cruce.resolver`, `PreciosDB.get_candidatos` (Tareas 2-3).
- Produces: `CostedComponent(..., calidad_cruce: str = "exacto")`; `PricingEngine.cost_component` lo setea.

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_pricing_cruce.py
import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.dominio.pricing import PricingEngine


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    # código 4513 repetido: ducto (barato) vs base granular (caro)
    a.precios.insert_insumos([
        Insumo("4513", "DUCTO TELEFONICO LIVIANO PVC TIPO EB D=3", "ML", "MAT", 16925, "PRECIO IDU"),
        Insumo("4513", "BASE GRANULAR CLASE C", "M3", "MAT", 190300, "PRECIO IDU"),
    ])
    a.apus.insert_apus([Apu("A1", "RED", "ML", "DIURNO")])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4513", "DUCTO TELEFONICO LIVIANO PVC TIPO EB D=3", "ML", 1.0, 9999),
    ])
    return a


def test_elige_precio_por_nombre_no_por_codigo(alm):
    eng = PricingEngine(alm)
    costed, total = eng.cost_apu("A1", "DIURNO")
    assert total == pytest.approx(16925)        # ducto, NO base granular
    assert costed[0].calidad_cruce == "exacto"

def test_codigo_ambiguo_cae_al_historico_y_avisa(alm):
    # un componente cuyo nombre no casa con ninguno de los dos -> ambiguo -> histórico
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4513", "TORNILLO HEXAGONAL 1 PULGADA", "UN", 2.0, 500),
    ])
    eng = PricingEngine(alm)
    costed, _ = eng.cost_apu("A1", "DIURNO")
    amb = [c for c in costed if c.insumo_nombre.startswith("TORNILLO")][0]
    assert amb.precio_unitario == 500 and amb.fuente_precio == "histórico"
    assert amb.calidad_cruce == "ambiguo"

def test_huerfano_avisa(alm):
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "0000", "INSUMO INEXISTENTE", "UN", 1.0, 700),
    ])
    eng = PricingEngine(alm)
    costed, _ = eng.cost_apu("A1", "DIURNO")
    h = [c for c in costed if c.insumo_codigo == "0000"][0]
    assert h.precio_unitario == 700 and h.calidad_cruce == "huerfano"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_pricing_cruce.py -v`
Expected: FAIL (`CostedComponent` no acepta `calidad_cruce`; el costeo aún cruza por código).

- [ ] **Step 3: Añadir `calidad_cruce` a `CostedComponent`**

En `apu_tool/nucleo/models.py`, en la `@dataclass class CostedComponent` (líneas 124-133), añadir el campo al final:

```python
@dataclass
class CostedComponent:
    insumo_codigo: str
    insumo_nombre: str
    unidad: str
    rendimiento: float
    precio_unitario: float        # precio usado (catálogo actual o histórico)
    fuente_precio: str
    costo: float                  # rendimiento * precio_unitario
    calidad_cruce: str = "exacto" # exacto | aproximado | ambiguo | huerfano (aviso del cruce)
```

- [ ] **Step 4: Reescribir `pricing.py`**

Reemplazar `apu_tool/dominio/pricing.py` (líneas 12-52, imports + `_insumo_price` + `cost_component`) por:

```python
from __future__ import annotations

from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import cruce
from apu_tool.nucleo.models import ApuComponent, CostedComponent


class PricingEngine:
    def __init__(self, almacen: Almacen):
        self.alm = almacen
        self._cache: dict[str, list] = {}   # codigo -> list[Insumo] candidatos

    def _candidatos(self, codigo: str) -> list:
        if not codigo:
            return []
        if codigo not in self._cache:
            self._cache[codigo] = self.alm.precios.get_candidatos(codigo)
        return self._cache[codigo]

    def cost_component(self, comp: ApuComponent) -> CostedComponent:
        r = cruce.resolver(self._candidatos(comp.insumo_codigo), comp.insumo_nombre)
        if r.insumo is not None and r.insumo.precio > 0:        # EXACTO o APROXIMADO
            precio, fuente = r.insumo.precio, r.insumo.fuente_precio
        else:                                                   # AMBIGUO o HUERFANO
            precio, fuente = comp.precio_unitario_hist, "histórico"
        costo = comp.rendimiento * precio
        return CostedComponent(
            insumo_codigo=comp.insumo_codigo,
            insumo_nombre=comp.insumo_nombre,
            unidad=comp.unidad,
            rendimiento=comp.rendimiento,
            precio_unitario=precio,
            fuente_precio=fuente,
            costo=costo,
            calidad_cruce=r.calidad.value,
        )
```

(Los métodos `cost_components` y `cost_apu`, líneas 54-61, quedan sin cambios.)

- [ ] **Step 5: Correr y verificar que pasa**

Run: `python -m pytest tests/test_pricing_cruce.py -v`
Expected: PASS (3 passed).

- [ ] **Step 6: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS. (`test_pricing_ingest` sigue verde: sus códigos son únicos y los nombres del APU coinciden exacto con el catálogo, así que el precio del catálogo se sigue usando.)

---

### Task 5: Composición generativa por candidatos — `assemble.py`

`_try_generate` usa hoy `get_insumo(cc.insumo_codigo)`. La IA solo devuelve código (sin nombre), así que se toma el (único o primer) candidato del código; el costeo luego re-resuelve por nombre y casará EXACTO.

**Files:**
- Modify: `apu_tool/dominio/assemble.py:110-118`
- Test: `tests/test_assemble_generado.py`

**Interfaces:**
- Consumes: `PreciosDB.get_candidatos`.

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_assemble_generado.py
import pytest
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, LicitacionItem
from apu_tool.dominio.assemble import Assembler
from apu_tool.dominio.ai_assist import ComposeResult


class _Advisor:
    """Advisor falso: no elige histórico, y compone con un código conocido."""
    def choose_apu(self, item, candidatos, depriced):
        class D:  # decisión vacía -> fuerza la rama generativa
            apu_codigo = None; confianza = 0.0; justificacion = ""; fuente = "test"
        return D()
    def compose_apu(self, item, insumos, ejemplos):
        class C:
            componentes = [type("X", (), {"insumo_codigo": "4279", "rendimiento": 2.0})()]
            justificacion = "ok"; confianza = 0.9
        return C()


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    return a


def test_generado_usa_candidato_del_codigo(alm):
    asm = Assembler(alm, advisor=_Advisor())
    item = LicitacionItem(item="1", descripcion="ACTIVIDAD NUEVA", unidad="M2",
                          cantidad=1, precio_contractual=0, shift="DIURNO")
    res = asm._try_generate(item)
    assert res is not None
    assert res.componentes[0].insumo_nombre == "CUADRILLA"
    assert res.componentes[0].precio_unitario == 40000
```

- [ ] **Step 2: Correr y verificar que pasa o falla**

Run: `python -m pytest tests/test_assemble_generado.py -v`
Expected: PASS ya hoy (el `get_insumo` transitorio devuelve el candidato único). El objetivo de esta tarea es dejar el código explícito en candidatos antes de retirar el shim.

- [ ] **Step 3: Migrar `_try_generate` a `get_candidatos`**

En `apu_tool/dominio/assemble.py`, reemplazar las líneas 110-118 por:

```python
        comps: list[ApuComponent] = []
        for cc in result.componentes:
            cands = self.alm.precios.get_candidatos(cc.insumo_codigo)
            if not cands:
                continue
            ins = cands[0]   # la IA solo da código; el costeo re-resuelve por nombre
            comps.append(ApuComponent(
                apu_codigo="", shift=item.shift, insumo_codigo=ins.codigo,
                insumo_nombre=ins.nombre, unidad=ins.unidad,
                rendimiento=cc.rendimiento, precio_unitario_hist=0.0))
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_assemble_generado.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

---

### Task 6: Chequeo de integridad sobre el resolver — mover a `dominio/integridad.py`

`integridad` usa el resolver (dominio), así que se mueve de `datos/` a `dominio/` (respeta la regla datos↛dominio). Reporta huérfanos / aproximados / ambiguos.

**Files:**
- Create: `apu_tool/dominio/integridad.py` (reescrito sobre el resolver)
- Delete: `apu_tool/datos/integridad.py`
- Modify: `apu_tool/interfaz/cli.py:79` (import), `tests/test_integridad.py:2` (import)
- Test: `tests/test_integridad.py` (ampliar)

**Interfaces:**
- Consumes: `cruce.resolver`, `CalidadCruce`, `Almacen`.
- Produces: `dominio.integridad.revisar(almacen) -> {"huerfanos": int, "aproximados": int, "ambiguos": int, "detalles": list[dict]}`.

- [ ] **Step 1: Ampliar el test (y corregir el import)**

Reescribir `tests/test_integridad.py`:

```python
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import integridad
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo


def _alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    return a


def test_detecta_huerfano(tmp_path):
    a = _alm(tmp_path)
    a.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "999", "X", "UN", 1.0, 0)])
    rep = integridad.revisar(a)
    assert rep["huerfanos"] == 1

def test_detecta_ambiguo(tmp_path):
    a = _alm(tmp_path)
    a.precios.insert_insumos([
        Insumo("4513", "DUCTO TELEFONICO PVC D=3", "ML", "MAT", 16925, "PRECIO IDU"),
        Insumo("4513", "BASE GRANULAR CLASE C", "M3", "MAT", 190300, "PRECIO IDU"),
    ])
    a.apus.insert_apus([Apu("A1", "RED", "ML", "DIURNO")])
    a.apus.insert_components([ApuComponent("A1", "DIURNO", "4513", "TORNILLO X", "UN", 1.0, 0)])
    rep = integridad.revisar(a)
    assert rep["ambiguos"] == 1
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_integridad.py -v`
Expected: FAIL — `ImportError: cannot import name 'integridad' from 'apu_tool.dominio'`.

- [ ] **Step 3: Crear `apu_tool/dominio/integridad.py`**

```python
# apu_tool/dominio/integridad.py
"""
Chequeo de integridad del vínculo APU -> insumo (que cruza las dos bases).

Sustituye la FK que ya no existe entre archivos. Reutiliza el resolver de `cruce`:
reporta componentes cuyo código no está en precios (HUERFANO), los que casan por
nombre de forma aproximada (APROXIMADO) y los que no resuelven a un solo insumo
(AMBIGUO) — la clase del problema del 4613 y de los códigos repetidos del IDU.
"""
from __future__ import annotations

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import cruce


def revisar(almacen: Almacen) -> dict:
    """Devuelve {'huerfanos', 'aproximados', 'ambiguos', 'detalles': [...]}."""
    huerfanos = aproximados = ambiguos = 0
    detalles: dict[tuple, dict] = {}
    with almacen.apus.connect() as ca:
        comps = ca.execute(
            "SELECT insumo_codigo AS cod, insumo_nombre AS nom "
            "FROM apu_componentes WHERE insumo_codigo IS NOT NULL AND insumo_codigo <> ''"
        ).fetchall()
    for r in comps:
        res = cruce.resolver(almacen.precios.get_candidatos(r["cod"]), r["nom"])
        if res.calidad == cruce.CalidadCruce.HUERFANO:
            huerfanos += 1
        elif res.calidad == cruce.CalidadCruce.AMBIGUO:
            ambiguos += 1
            _acumular(detalles, r["cod"], r["nom"], "ambiguo")
        elif res.calidad == cruce.CalidadCruce.APROXIMADO:
            aproximados += 1
            _acumular(detalles, r["cod"], r["nom"], "aproximado",
                      cat_nom=res.insumo.nombre if res.insumo else "")
    return {"huerfanos": huerfanos, "aproximados": aproximados,
            "ambiguos": ambiguos, "detalles": list(detalles.values())}


def _acumular(detalles, cod, nom, calidad, cat_nom=""):
    key = (cod, nom, calidad)
    d = detalles.setdefault(key, {"codigo": cod, "apu_nom": nom,
                                  "calidad": calidad, "cat_nom": cat_nom, "n": 0})
    d["n"] += 1
```

- [ ] **Step 4: Borrar el módulo viejo y arreglar el import del CLI**

Borrar `apu_tool/datos/integridad.py`.

En `apu_tool/interfaz/cli.py:79`, cambiar:

```python
    from apu_tool.datos import integridad
```
por:
```python
    from apu_tool.dominio import integridad
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `python -m pytest tests/test_integridad.py -v`
Expected: PASS (2 passed).

- [ ] **Step 6: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

---

### Task 7: Seed — `INSUMOS_IDU-INT` autoritativa + dedup por (código, nombre)

**Files:**
- Modify: `apu_tool/datos/seed.py:92-103` (orden de hojas), `:204-209` (dedup)
- Test: `tests/test_seed_identidad.py`

**Interfaces:**
- Consumes: `nucleo.texto.normalizar`, `PreciosDB.insert_insumos`/`get_candidatos`.

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_seed_identidad.py
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo
from apu_tool.datos import seed


def test_dedup_por_codigo_y_nombre(tmp_path):
    """insert_insumos conserva dos insumos del mismo código si difieren en nombre,
    y colapsa los que son idénticos en (código, nombre)."""
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4513", "DUCTO PVC D=3", "ML", "MAT", 16925, "PRECIO IDU"),
        Insumo("4513", "BASE GRANULAR", "M3", "MAT", 190300, "PRECIO IDU"),
        Insumo("4513", "ducto   pvc  d=3", "ML", "MAT", 99999, "OTRA"),  # idéntico normalizado -> se ignora
    ])
    cands = a.precios.get_candidatos("4513")
    assert len(cands) == 2
    ducto = [c for c in cands if c.nombre == "DUCTO PVC D=3"][0]
    assert ducto.precio == 16925   # ganó la primera ocurrencia, no la de 99999
```

- [ ] **Step 2: Correr y verificar que pasa**

Run: `python -m pytest tests/test_seed_identidad.py -v`
Expected: PASS ya (la lógica de dedup vive en `insert_insumos`, hecha en la Tarea 2). Esta prueba blinda el comportamiento; los siguientes pasos ajustan el orden de hojas del seed.

- [ ] **Step 3: Reordenar las hojas e independizar el dedup en `seed.py`**

En `apu_tool/datos/seed.py`, reemplazar el bloque `INSUMO_SHEETS` (líneas 92-103) por:

```python
# Orden importante: la primera ocurrencia de una identidad (código, nombre) gana.
# 'INSUMOS_IDU-INT' va PRIMERO: es la base autoritativa con todos los insumos.
INSUMO_SHEETS = [
    InsumoSheet("INSUMOS_IDU-INT", col_codigo=2, col_nombre=3, col_unidad=4,
                col_precio=5, col_fuente=6, col_grupo=1),
    InsumoSheet("listado_insumos_idu", col_codigo=2, col_nombre=3, col_unidad=4,
                col_precio=5, col_fuente=6, col_grupo=1),
    InsumoSheet("insumos_apus_especificos", col_codigo=2, col_nombre=3, col_unidad=4,
                col_precio=5, col_fuente=6),
    InsumoSheet("listado_apus_idu_especiales", col_codigo=2, col_nombre=3, col_unidad=4,
                col_precio=5, col_fuente=6),
]
```

En la función `seed`, reemplazar el dedup por código (líneas 204-209) por dedup por identidad (código, nombre normalizado):

```python
        insumos: dict[tuple[str, str], Insumo] = {}
        for sheet in INSUMO_SHEETS:
            for ins in _read_insumos(wb, sheet):
                insumos.setdefault((ins.codigo, normalizar(ins.nombre)), ins)
        alm.precios.insert_insumos(insumos.values())
```

Y añadir el import al inicio de `seed.py` (junto a los otros `from apu_tool...`):

```python
from apu_tool.nucleo.texto import normalizar
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_seed_identidad.py tests/test_seed_correcciones.py tests/test_fuente_xlsx.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

---

### Task 8: CLI — listar candidatos y desambiguar precios

**Files:**
- Modify: `apu_tool/interfaz/cli.py` (`cmd_db_price`, `cmd_db_update_price`, `cmd_db_check`, parser de `update-price`)

**Interfaces:**
- Consumes: `PreciosDB.get_candidatos`, `set_precio(..., nombre=)`, `price_history(codigo, nombre=)`, `dominio.integridad.revisar` (claves nuevas).

- [ ] **Step 1: Reescribir `cmd_db_price`**

En `apu_tool/interfaz/cli.py`, reemplazar `cmd_db_price` (líneas 88-104) por:

```python
def cmd_db_price(args) -> int:
    alm = get_almacen()
    cands = alm.precios.get_candidatos(args.codigo)
    if not cands:
        print(f"No existe el insumo {args.codigo}.")
        return 1
    if len(cands) > 1:
        print(f"⚠ El código {args.codigo} tiene {len(cands)} insumos distintos:")
    for ins in cands:
        print(f"  id={ins.id}  {ins.codigo}  {ins.nombre}")
        print(f"     Unidad: {ins.unidad}   Grupo: {ins.grupo}")
        print(f"     Precio vigente: ${ins.precio:,.0f}   Fuente: {ins.fuente_precio} "
              f"({'confidencial' if ins.es_confidencial else 'público'})")
        hist = alm.precios.price_history(ins.codigo, nombre=ins.nombre)
        if len(hist) > 1:
            print("     Historial:")
            for h in hist:
                flag = " (vigente)" if h["vigente"] else ""
                print(f"       {h['fecha']}  ${h['precio']:,.0f}  {h['fuente']}{flag}")
    return 0
```

- [ ] **Step 2: Reescribir `cmd_db_update_price`**

Reemplazar `cmd_db_update_price` (líneas 107-116) por:

```python
def cmd_db_update_price(args) -> int:
    alm = get_almacen()
    cands = alm.precios.get_candidatos(args.codigo)
    if not cands:
        print(f"No existe el insumo {args.codigo}.")
        return 1
    if len(cands) > 1 and not args.nombre:
        print(f"⚠ El código {args.codigo} es ambiguo ({len(cands)} insumos). "
              f"Repite con --nombre \"<nombre exacto>\":")
        for ins in cands:
            print(f"  - {ins.nombre}")
        return 1
    try:
        alm.precios.set_precio(args.codigo, args.precio,
                               fuente=args.fuente or "ACTUALIZACION MANUAL",
                               nombre=args.nombre)
    except ValueError as e:
        print(str(e))
        return 1
    print(f"Precio actualizado para {args.codigo}"
          + (f" / {args.nombre}" if args.nombre else "") + f" -> ${args.precio:,.0f}")
    print("Los APUs que usan este insumo tomarán el nuevo precio automáticamente.")
    return 0
```

- [ ] **Step 3: Reescribir `cmd_db_check`**

Reemplazar `cmd_db_check` (líneas 78-85) por:

```python
def cmd_db_check(args) -> int:
    from apu_tool.dominio import integridad
    rep = integridad.revisar(get_almacen())
    print(f"Huérfanos (código sin insumo): {rep['huerfanos']}")
    print(f"Aproximados (cruce difuso):     {rep['aproximados']}")
    print(f"Ambiguos (código no resuelve):  {rep['ambiguos']}")
    for d in sorted(rep["detalles"], key=lambda x: -x["n"])[:25]:
        print(f"  [{d['calidad']:<10}] {d['codigo']:>7}  x{d['n']:<3}  "
              f"{d['apu_nom'][:30]}" + (f" -> {d['cat_nom'][:30]}" if d['cat_nom'] else ""))
    return 0
```

- [ ] **Step 4: Añadir el argumento `--nombre` al parser de `update-price`**

Buscar en `build_parser` la definición del subcomando `update-price` (alrededor de las líneas 205-215, `dbsub.add_parser("update-price", ...)`). Tras sus `add_argument` existentes (`codigo`, `precio`, `--fuente`), añadir:

```python
    pup.add_argument("--nombre", help="Nombre exacto del insumo (desambigua códigos repetidos).")
```

(usar el nombre de variable que ya tenga ese parser en el archivo; si es otro, ajustarlo).

- [ ] **Step 5: Smoke manual (no hay suite de CLI)**

```bash
python run_cli.py seed --force
python run_cli.py db check
python run_cli.py db price 4513
```
Expected: `db price 4513` lista 2 insumos (ducto y base granular) con sus `id`; `db check` imprime conteos de huérfanos/aproximados/ambiguos sin error.

- [ ] **Step 6: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS (el CLI no tiene pruebas unitarias; la suite valida que no se rompió nada importado por el CLI).

---

### Task 9: Aviso en el cuadro resumen — columna "Cruce"

Se añade `calidad_cruce` como **última** columna del desglose de insumos en ambos reportes (no desplaza columnas existentes ni sus formatos numéricos).

**Files:**
- Modify: `apu_tool/dominio/report.py:117-137` (`_build_desglose`)
- Modify: `apu_tool/dominio/report_categorizado.py:118` y `:131-135`
- Test: `tests/test_report_categorizado.py` (verificar la columna nueva)

**Interfaces:**
- Consumes: `CostedComponent.calidad_cruce`.

- [ ] **Step 1: Añadir la columna en `report.py::_build_desglose`**

En `apu_tool/dominio/report.py`, dentro de `_build_desglose`:

Cambiar `headers` (líneas 118-119) a:
```python
    headers = ["Ítem", "APU", "Actividad", "Insumo Cód", "Insumo",
               "Und", "Rendimiento", "Precio Unit.", "Fuente precio", "Costo", "Cruce"]
```
Cambiar la fila "sin composición" (líneas 125-126) a:
```python
            ws.append([a.item.item, a.apu_codigo or "", a.apu_nombre,
                       "", "(sin composición — armar manual)", "", "", "", "", "", ""])
```
Cambiar la fila de componente (líneas 129-131) a:
```python
            ws.append([a.item.item, a.apu_codigo or "", a.apu_nombre,
                       c.insumo_codigo, c.insumo_nombre, c.unidad,
                       c.rendimiento, c.precio_unitario, c.fuente_precio, c.costo,
                       c.calidad_cruce])
```
Cambiar el `_autosize` (líneas 136-137) a:
```python
    _autosize(ws, {1: 8, 2: 8, 3: 40, 4: 10, 5: 40, 6: 8, 7: 14, 8: 14,
                   9: 18, 10: 14, 11: 12})
```

- [ ] **Step 2: Añadir la columna en `report_categorizado.py`**

En `apu_tool/dominio/report_categorizado.py`:

Cambiar `sub` (línea 118) a:
```python
    sub = ["Insumo Cód", "Insumo", "Und", "Rendimiento", "Precio Unit.",
           "Fuente precio", "Costo", "Cruce"]
```
Cambiar la fila "sin composición" (línea 132) a:
```python
            ws.append(["", "(sin composición — armar manual)", "", "", "", "", "", ""])
```
Cambiar la fila de componente (líneas 134-135) a:
```python
            ws.append([c.insumo_codigo, c.insumo_nombre, c.unidad, c.rendimiento,
                       c.precio_unitario, c.fuente_precio, c.costo, c.calidad_cruce])
```
Cambiar la fila "COSTO UNITARIO APU" (línea 141) a (un `""` extra para alinear):
```python
        ws.append(["", "COSTO UNITARIO APU", "", "", "", "", a.costo_unitario, ""])
```
Cambiar el `_autosize` (línea 147) a:
```python
    _autosize(ws, {1: 12, 2: 46, 3: 8, 4: 14, 5: 14, 6: 18, 7: 14, 8: 12})
```

- [ ] **Step 3: Verificar/ampliar `tests/test_report_categorizado.py`**

Correr primero para ver si la prueba existente sigue verde con la columna extra:

Run: `python -m pytest tests/test_report_categorizado.py -v`
Expected: PASS (la columna nueva va al final; las aserciones existentes no se desplazan). Si la prueba cuenta columnas o longitudes de fila, ajustarla para incluir la columna "Cruce" (8 columnas en el desglose categorizado).

- [ ] **Step 4: Checkpoint — toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS.

---

### Task 10: Retirar el `get_insumo` transitorio

Quitar el shim y migrar los últimos consumidores (solo tests) a `get_candidatos`.

**Files:**
- Modify: `apu_tool/datos/precios_db.py` (quitar `get_insumo`), `apu_tool/datos/repositorio.py` (quitar del Protocol)
- Modify: `tests/test_db_repository.py`, `tests/test_pricing_ingest.py`, `tests/test_repositorios_contrato.py`

- [ ] **Step 1: Confirmar que no quedan usos en código de producción**

Run: `python -m pytest tests/ -q` y luego buscar usos:
Buscar `get_insumo(` (sin `_por_id`) en `apu_tool/`. Expected: solo aparecía en `precios_db.py` (definición). Ningún módulo de `apu_tool/` lo llama ya (pricing→`get_candidatos`, assemble→`get_candidatos`, cli→`get_candidatos`, integridad→`get_candidatos`).

- [ ] **Step 2: Migrar los tests que aún usan `get_insumo`**

En `tests/test_pricing_ingest.py`, reemplazar `test_insumo_confidencial_flag` (líneas 48-50) por:
```python
def test_insumo_confidencial_flag(alm):
    assert alm.precios.get_candidatos("9999")[0].es_confidencial is True
    assert alm.precios.get_candidatos("4279")[0].es_confidencial is False
```

En `tests/test_db_repository.py`, reemplazar las llamadas `get_insumo("...")` por `get_candidatos("...")[0]`:
- Línea 26-27: `alm.precios.get_candidatos("100")[0].es_confidencial` / `get_candidatos("200")[0]...`
- Línea 32-33: `ins = alm.precios.get_candidatos("100")[0]`

En `tests/test_repositorios_contrato.py`, cambiar la aserción (línea 5):
```python
    assert hasattr(RepositorioPrecios, "get_candidatos")
```

- [ ] **Step 3: Quitar el shim de `precios_db.py` y del Protocol**

En `apu_tool/datos/precios_db.py`, borrar el método `get_insumo` (el bloque transitorio con su docstring "TRANSITORIO").

En `apu_tool/datos/repositorio.py`, borrar la línea:
```python
    def get_insumo(self, codigo: str) -> Optional[Insumo]: ...   # transitorio (Tarea 10)
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_db_repository.py tests/test_pricing_ingest.py tests/test_repositorios_contrato.py -v`
Expected: PASS.

- [ ] **Step 5: Checkpoint final — toda la suite + re-seed**

Run: `python -m pytest tests/ -q`
Expected: PASS (toda la suite).

Luego, validación de extremo a extremo con datos reales:
```bash
python run_cli.py seed --force
python run_cli.py db check
python run_cli.py db price 4513
```
Expected: el seed reconstruye ambas bases; `db check` muestra conteos; `db price 4513` lista los 2 insumos distintos del código. Confirma que los códigos repetidos del IDU ya conviven y que el cruce usa código + nombre.

---

## Self-Review

**1. Cobertura del spec:**
- §1 Modelo de datos → Tarea 2 (esquema + `Insumo.id`). ✓
- §2 Normalización centralizada → Tarea 1. ✓
- §3 Resolver del cruce → Tarea 3. ✓
- §4 Motor de costos + `calidad_cruce` → Tarea 4. ✓
- §5 Capa de datos + Protocol → Tarea 2 (+ retiro de `get_insumo` en Tarea 10). ✓
- §6 Seed (autoritativa + dedup) → Tarea 7. ✓
- §7 Aviso: integridad → Tarea 6; reporte → Tarea 9; CLI → Tarea 8. ✓
- §8 No cambia: privacidad (no se toca); `correcciones.py` se queda (no se toca). ✓
- §9 Pruebas → cubiertas en cada tarea + Tarea 10. ✓

**2. Placeholders:** ninguno; todos los pasos llevan código o comando concreto.

**3. Consistencia de tipos/nombres:** `get_candidatos`, `get_insumo_por_id`, `resolver`, `CalidadCruce`, `ResultadoCruce`, `calidad_cruce`, `normalizar`, `set_precio(..., nombre=)`, `price_history(codigo, nombre=)` usados igual en todas las tareas. `Insumo.id` (Optional) consistente entre Tarea 2 y consumidores.

**Nota de refinamiento vs spec:** el spec decía "`set_precio`/`price_history` operan por `insumo_id`". El plan los mantiene con clave `codigo` + `nombre` opcional (resolviendo internamente al `id`), porque es la forma en que el usuario y el CLI piensan (código + nombre) y evita romper pruebas; internamente el almacenamiento ya es por `insumo_id` (FK), que es el objetivo del esquema. Para el camino por id está `get_insumo_por_id`.
