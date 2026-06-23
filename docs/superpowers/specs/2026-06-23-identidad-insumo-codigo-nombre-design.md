# Identidad de insumo por (código + nombre) y cruce con doble verificación difusa

**Fecha:** 2026-06-23
**Estado:** Diseño aprobado, pendiente de plan de implementación.

## Problema

En `precios.db` el código de insumo es la clave única (`codigo TEXT PRIMARY KEY` en
`db/precios.sql`), y todo el cruce de precios se hace **solo por código**:

- `pricing.PricingEngine._insumo_price(codigo)` busca por código.
- `precios_db.get_insumo(codigo)` hace `WHERE codigo = ?`.
- `seed` deduplica los insumos del Excel **por código** (`insumos.setdefault(ins.codigo, ins)`).

Pero la hoja autoritativa de insumos del Excel, **`INSUMOS_IDU-INT`** (8.156 filas,
7.505 códigos únicos), tiene **651 códigos repetidos, todos con nombres distintos**.
El IDU mezcla en una sola hoja insumos-material y actividades/APUs, y sus códigos
numéricos chocan entre registros. Ejemplos reales:

| Código | Insumo A | Insumo B |
|--------|----------|----------|
| 4513 | DUCTO TELEFÓNICO PVC D=3" → $16.925 | BASE GRANULAR CLASE C → $190.300 |
| 4520 | DUCTO PVC TDP D=3" → $10.747 | SOBRECARPETA RODADURA ASFÁLTICA → $97.009 |
| 4598 | CODO PVC 90° D=8" → $1.323.832 | SELLO DE GRIETAS → $12.107 |

Consecuencias hoy:
1. El esquema **no puede almacenar** los dos insumos: el `PRIMARY KEY` los colapsa.
2. El seed **descarta** en silencio el segundo (gana el primero según el orden de hojas).
3. El costeo puede cruzar el código contra el insumo equivocado → **errores de ~10x**
   en el costo.

## Objetivo

Que la **identidad** de un insumo sea **(código + nombre)** y que el cruce de precios
exija que **ambos coincidan**. Cuando el nombre no coincide exacto, usar **coincidencia
difusa y avisar** (no fallar duro, pero marcar la calidad del cruce). Nunca asignar en
silencio un precio dudoso.

## Decisiones tomadas

- **Enfoque A — id interno + `UNIQUE(codigo, nombre_norm)`** (no clave natural compuesta).
- **Comportamiento del cruce:** difuso + avisar (no "fallar y marcar", no "histórico ciego").
- **Hoja autoritativa:** `INSUMOS_IDU-INT` (hoy va segunda; pasa a primera).
- **Umbral difuso inicial:** `0.60` (igual al que ya usa `integridad._coincide`).
- **Invariante #1 intacto:** la IA nunca ve dinero; todo este trabajo vive en
  `pricing`/`datos`, nunca en el payload de IA.

## Diseño

### 1. Modelo de datos — `db/precios.sql`

```sql
CREATE TABLE IF NOT EXISTS insumos (
    id          INTEGER PRIMARY KEY,   -- rowid de SQLite; sin AUTOINCREMENT (porta a Postgres)
    codigo      TEXT NOT NULL,
    nombre      TEXT NOT NULL,
    nombre_norm TEXT NOT NULL,         -- normalizado: sin tildes, mayúsculas, espacios colapsados
    unidad      TEXT,
    grupo       TEXT,
    UNIQUE (codigo, nombre_norm)
);
CREATE INDEX IF NOT EXISTS idx_insumo_cod ON insumos(codigo);

CREATE TABLE IF NOT EXISTS insumo_precios (
    id            INTEGER PRIMARY KEY,
    insumo_id     INTEGER NOT NULL,    -- antes: codigo TEXT
    precio        REAL NOT NULL,
    fuente        TEXT,
    clasificacion TEXT,                -- 'publico' | 'interno'
    fecha         TEXT,
    vigente       INTEGER NOT NULL DEFAULT 1,
    FOREIGN KEY (insumo_id) REFERENCES insumos(id)
);
CREATE INDEX IF NOT EXISTS idx_precio_ins ON insumo_precios(insumo_id, vigente);
```

- `nombre_norm` se **almacena** (no se calcula en SQL) para que el `UNIQUE` y la búsqueda
  de candidatos sean deterministas y portables a Postgres.
- Postgres luego: `id BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY`.

### 2. Normalización centralizada — `apu_tool/nucleo/texto.py` (nuevo)

Hoy la normalización de texto está duplicada en `matching.normalize` (dominio) y en
`integridad._norm` (datos). Se centraliza en un módulo puro, sin dependencias, en la capa
`nucleo` (que ya importan datos y dominio):

```python
def normalizar(texto: str) -> str:
    """Sin tildes, mayúsculas, sin puntuación, espacios colapsados."""
```

- `matching.normalize` pasa a delegar en `nucleo.texto.normalizar` (conserva su `lru_cache`).
- `integridad._norm` se reemplaza por `normalizar`.
- El seed usa `normalizar(nombre)` para llenar `insumos.nombre_norm`.
- El resolver y `precios_db` lo usan para comparar/buscar.

Esto mantiene una sola definición de normalización y respeta la frontera de capas
(`datos` no importa de `dominio`; ambas importan de `nucleo`).

### 3. El cruce — `apu_tool/dominio/cruce.py` (nuevo)

```python
class CalidadCruce(str, Enum):
    EXACTO = "exacto"          # código coincide y nombre normalizado idéntico
    APROXIMADO = "aproximado"  # código coincide y nombre casa difuso (sobre umbral, con margen)
    AMBIGUO = "ambiguo"        # código coincide pero el nombre no resuelve a un único insumo
    HUERFANO = "huerfano"      # ningún insumo tiene ese código

@dataclass(frozen=True)
class ResultadoCruce:
    insumo: Optional[Insumo]   # None si AMBIGUO o HUERFANO
    calidad: CalidadCruce
    score: float               # similitud del mejor candidato (0..1)

def resolver(candidatos: list[Insumo], nombre_apu: str) -> ResultadoCruce: ...
```

Reglas (usa `matching.similarity`, que combina secuencia + tokens):

1. `candidatos == []` → `HUERFANO`, `insumo=None`.
2. Si algún candidato tiene `nombre_norm == normalizar(nombre_apu)` → `EXACTO` con ese insumo.
3. Se puntúa cada candidato con `similarity(nombre_apu, c.nombre)`. Sea `mejor` el de mayor
   score y `segundo` el siguiente (o 0 si hay uno solo):
   - `mejor.score >= CRUCE_UMBRAL` **y** `mejor.score - segundo.score >= CRUCE_MARGEN`
     → `APROXIMADO` con `mejor`.
   - en otro caso → `AMBIGUO`, `insumo=None`.

Notas:
- Con **un solo candidato** cuyo nombre no llega al umbral → `AMBIGUO` (caso "código
  sospechoso", estilo 4613): no se confía, se avisa.
- Umbrales nuevos en `config.py`: `CRUCE_UMBRAL = 0.60`, `CRUCE_MARGEN = 0.10`.

### 4. Motor de costos — `apu_tool/dominio/pricing.py`

`cost_component` se reescribe como resolución por **código + nombre**. La clave es que
la **calidad del cruce se propaga siempre**, incluso cuando se cae al histórico:

```python
def cost_component(self, comp) -> CostedComponent:
    candidatos = self.alm.precios.get_candidatos(comp.insumo_codigo)   # cacheado por codigo
    r = cruce.resolver(candidatos, comp.insumo_nombre)
    if r.insumo and r.insumo.precio > 0:           # EXACTO o APROXIMADO
        precio, fuente = r.insumo.precio, r.insumo.fuente_precio
    else:                                          # AMBIGUO o HUERFANO
        precio, fuente = comp.precio_unitario_hist, "histórico"
    # ... costo = comp.rendimiento * precio
    return CostedComponent(..., calidad_cruce=r.calidad.value)
```

- `EXACTO` / `APROXIMADO` → precio del catálogo; `calidad_cruce` = exacto/aproximado.
- `AMBIGUO` / `HUERFANO` → **precio histórico embebido** (`comp.precio_unitario_hist`,
  respaldo que ya existe); `calidad_cruce` = ambiguo/huerfano (el "aviso" queda registrado).
- El caché de candidatos se clavea por `codigo` (la resolución por nombre es barata y se
  hace por componente).

Garantía de unicidad de `EXACTO`: como `UNIQUE(codigo, nombre_norm)` impide dos candidatos
con el mismo código y nombre normalizado, a lo sumo un candidato puede empatar exacto.

`CostedComponent` (en `apu_tool/nucleo/models.py` — la copia de `dominio/models.py` es
código muerto, nadie la importa) gana:

```python
calidad_cruce: str = "exacto"   # el "aviso"; por defecto exacto para no romper constructores
```

`cost_component` setea `calidad_cruce` con el resultado del resolver.

### 5. Capa de datos — `apu_tool/datos/precios_db.py` + `repositorio.py`

- `insert_insumos`: dedup por `(codigo, nombre_norm)` (no por código). Por cada identidad
  nueva: inserta en `insumos` (obtiene `id`) e inserta su precio vigente en
  `insumo_precios` con ese `insumo_id`.
- **Nuevos métodos:**
  - `get_candidatos(codigo) -> list[Insumo]` — todos los insumos con ese código, cada uno
    con su precio vigente.
  - `get_insumo_por_id(id) -> Optional[Insumo]`.
- `get_insumo(codigo)` **se retira** (era la fuente del bug). Se actualizan los llamadores:
  `pricing`, `assemble.py:112` (composición generativa), `cli.py` (`db price` / `update-price`),
  `integridad.py`.
- `set_precio` y `price_history` pasan a operar por `insumo_id`.
- El `Protocol RepositorioPrecios` se actualiza: fuera `get_insumo`; dentro `get_candidatos`,
  `get_insumo_por_id`; `set_precio`/`price_history` por `insumo_id`.

`assemble._try_generate` (línea 112): hoy hace `get_insumo(cc.insumo_codigo)` para una
composición que la IA generó (la IA devuelve solo código, sin nombre). Como ahí el código
puede ser ambiguo, se resuelve con los candidatos del código y, si hay varios, se toma el de
mejor afinidad con el nombre de la actividad; si no hay ninguno, se omite el componente
(comportamiento actual cuando `ins is None`).

### 6. Seed — `apu_tool/datos/seed.py`

- Reordenar `INSUMO_SHEETS`: **`INSUMOS_IDU-INT` primero (autoritativa)**, luego
  `listado_insumos_idu` y el resto como complemento.
- Dedup por `(codigo, nombre_norm)` en vez de por código (la primera ocurrencia gana su
  precio si un mismo `(codigo, nombre)` aparece en dos hojas).
- **Requiere re-semillar** (`seed --force`): la base se reconstruye desde el Excel; no hay
  migración de datos (la base es derivada, el Excel es la fuente de verdad).

### 7. Aviso al usuario — integridad, reporte y CLI

- `integridad.revisar` se reescribe sobre el resolver. Reporta conteos de `HUERFANO`,
  `APROXIMADO` y `AMBIGUO` por componente de APU. (El problema de "insumos perdidos"
  desaparece: ambos quedan almacenados.)
- `report` / `report_categorizado`: el cuadro resumen muestra `calidad_cruce` por componente,
  para distinguir precios exactos / aproximados / sin resolver.
- CLI:
  - `db price <codigo>` lista **todos** los candidatos del código (id, nombre, precio, fuente,
    vigente).
  - `db update-price` admite `--id` (o `--nombre`) para desambiguar cuando el código está
    repetido; si el código es único, funciona como hoy.

### 8. Qué NO cambia

- **Invariante #1:** la IA no ve dinero. Confirmado: todo vive en `pricing`/`datos`.
- **`correcciones.py` se queda.** Resuelve un problema **distinto**: el APU cita el código
  **equivocado** y el insumo correcto vive bajo *otro* código (4613→3017). El resolver solo
  mira dentro del código citado, así que no puede arreglar eso; el remapeo manual sí.

## Pruebas

- **Seed:** un código repetido en `INSUMOS_IDU-INT` queda como **dos** filas en `insumos`
  (no se pierde ninguno).
- **DB:** `get_candidatos(codigo)` devuelve los varios candidatos con su precio vigente;
  `get_insumo_por_id` funciona; `insert_insumos` dedup por `(codigo, nombre_norm)`.
- **Resolver:** casos `EXACTO`, `APROXIMADO`, `AMBIGUO` (dos candidatos igual de buenos) y
  `HUERFANO`; caso de un solo candidato con nombre lejano → `AMBIGUO`.
- **Costeo:** con código repetido, elige el precio del candidato cuyo nombre casa
  (ej. 4513 → precio del ducto, no de la base granular); cuando es `AMBIGUO`/`HUERFANO`,
  cae al histórico y marca `calidad_cruce`.
- **Integridad:** reporta huérfanos / aproximados / ambiguos.
- **CLI:** `db price` lista candidatos; `update-price --id/--nombre` desambigua.
- **Privacidad:** los tests existentes de la frontera de IA siguen pasando sin cambios.
- **Actualizar** los tests que asumían `get_insumo(codigo)` único
  (`test_precios_db`, `test_db_repository`, `test_pricing_ingest`, `test_repositorios_contrato`).

## Riesgos y notas de migración

- **Re-seed obligatorio:** el esquema cambia; hay que correr `seed --force`. Se pierden
  correcciones de precio mantenidas a mano en la base (las hechas con `update-price`); si
  hubiera alguna importante, exportarla antes.
- **Tasa de match exacto:** validar tras implementar que la mayoría de componentes de APU
  resuelven `EXACTO`/`APROXIMADO` y que los `AMBIGUO` son pocos (en este Excel, el descalce
  APU→catálogo era mínimo). Si aparecieran muchos `AMBIGUO`, ajustar `CRUCE_UMBRAL`/`CRUCE_MARGEN`.
- **Compatibilidad del Protocol:** al retirar `get_insumo`, cualquier consumidor externo del
  contrato debe migrar a `get_candidatos`/`get_insumo_por_id`.
