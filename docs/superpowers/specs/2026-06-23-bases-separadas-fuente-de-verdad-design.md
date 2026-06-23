# Dos bases separadas, fuente de verdad (precios.db + apus.db)

**Fecha:** 2026-06-23
**Estado:** aprobado para planificar
**Contexto:** Es el **paso 1** de la hoja de ruta en [docs/ARQUITECTURA.md](../../ARQUITECTURA.md).
Además de las dos bases, este paso **reorganiza todo el proyecto a la estructura por capas**
objetivo (`datos/ · dominio/ · servicio/ · interfaz/`).

## Objetivo

Dejar de tratar al Excel como la fuente de verdad. Hoy `data/apu.db` es una proyección
desechable del Excel (`db rebuild` la regenera y borra cualquier corrección — por eso el
arreglo del código 4613 no persistía). Queremos **dos bases SQLite canónicas y mantenidas
directamente**, separadas por dominio, listas para migrar a un servidor/nube después:

- **`precios.db`** — catálogo de insumos y su libro de precios.
- **`apus.db`** — biblioteca histórica de APUs (composición + rendimiento + turno).

El Excel pasa a ser una **semilla de importación de una sola vez**; a partir de ahí las
correcciones (4613→3017), actualizaciones de precio y altas de APU viven en las bases y
**persisten**.

## Decisiones acordadas (brainstorming 2026-06-23)

1. **Fuente de verdad = las bases.** El Excel se importa una vez como semilla; después no manda.
2. **SQLite canónico ahora, nube después.** Acceso aislado para migrar a Postgres por base
   sin reescribir el resto. Cero infraestructura que montar hoy.
3. **Dos archivos `.db` independientes** (`precios.db`, `apus.db`), cada uno mantenible y
   reemplazable solo. El vínculo APU→insumo (`apu_componentes.insumo_codigo`) deja de ser
   FK de base (cruza archivos) y se **valida en la aplicación**.
4. **Enfoque A — dos repositorios + fachada.** `RepositorioPrecios` sobre `precios.db` y
   `RepositorioApus` sobre `apus.db`, cada uno con su contrato; una fachada delgada
   (`Almacen`) que el resto de la app usa. Mañana cada repo puede apuntar a un Postgres
   distinto sin tocar el resto. Es la evolución natural de `repository.py`.

## Arquitectura

```
Excel histórico ──seed (una vez, guardado)──► precios.db  +  apus.db
                                                  │             │
                            RepositorioPrecios ───┘             └─── RepositorioApus
                                          │                              │
                                          └────────── Almacen ───────────┘
                                                         │
                         pricing / assemble / matching / pipeline / report / cli / gui
```

### Las dos bases

**`precios.db`** (esquema en `db/precios.sql`)
- `insumos` (identidad: codigo, nombre, unidad, grupo).
- `insumo_precios` (libro de precios; vigente + historial). **FK** `codigo → insumos`
  (dentro de la misma base, se conserva).
- `meta` (procedencia: de qué Excel, cuándo se semilló, conteos).

**`apus.db`** (esquema en `db/apus.sql`)
- `apus` (codigo, shift, nombre, unidad, grupo; PK `(codigo, shift)`).
- `apu_componentes` (composición; PK `(apu_codigo, shift, seq)`; **FK** `(apu_codigo, shift)
  → apus`). `insumo_codigo` **sin FK** — ya era un "enlace blando", lo que encaja
  perfectamente con la separación en dos archivos. Conserva `precio_unitario_hist` como
  respaldo de costeo cuando un insumo no esté en `precios.db`.
- `meta` (procedencia).

### Capa de acceso (enfoque A) — todo bajo `apu_tool/datos/`
- `datos/repositorio.py` — dos `Protocol`: `RepositorioPrecios` y `RepositorioApus`
  (reemplaza a `repository.py`).
- `db.py` se divide en `datos/precios_db.py` (`PreciosDB`) y `datos/apus_db.py` (`ApusDB`),
  cada uno con su archivo y su esquema. Cada clase mantiene el patrón actual (conexión,
  `init_schema`, `reset`, contar, etc.) aislado en su base.
- `datos/almacen.py` expone `Almacen` con `.precios: RepositorioPrecios` y
  `.apus: RepositorioApus`.
  El resto de la app recibe un `Almacen` y usa el repo correcto:
  - `PricingEngine` pide composición a `almacen.apus.get_components(...)` y precio vigente a
    `almacen.precios.get_insumo(...)`.
  - `Assembler`/`Matcher`/`InsumoRetriever` usan `almacen.apus` (índice, APUs, vistas
    DePriced) y `almacen.precios` (búsqueda de insumos).

### Reparto de métodos (resumen)
- **RepositorioPrecios:** `init_schema`, `reset`, `insert_insumos`, `get_insumo`,
  `set_precio`, `price_history`, `search_insumos`, `search_insumos_by_tokens`, `counts`,
  `set_meta`/`get_meta`.
- **RepositorioApus:** `init_schema`, `reset`, `insert_apus`, `insert_components`,
  `all_apus`, `apu_index`, `get_apu`, `search_apus`, `get_components`, `get_depriced_apu`,
  `counts`, `set_meta`/`get_meta`.
  (`get_depriced_apu` vive en Apus: es la vista SIN dinero, no necesita precios.)

## Semillado (fuente de verdad)

- Comando nuevo **`seed`** (reemplaza al `db rebuild` destructivo): importa el Excel y
  crea/llena `precios.db` y `apus.db`. Es **guardado**: si ya hay datos mantenidos en las
  bases, se **niega** a sobrescribir salvo `--force` (evita borrar correcciones por accidente).
- El `seed` aplica una **lista de correcciones de código** documentada y reproducible,
  arrancando con **`4613 → 3017`** (las 18 componentes diurnas donde el APU nombra
  "transporte y disposición final" pero el catálogo tiene 4613 = "UNIÓN PVC D=10").
  Justificación: el escaneo confirmó que **ningún** APU usa 4613 como unión PVC, así que el
  remapeo total de 4613→3017 en `apu_componentes` es seguro para estos datos.
- Tras importar, corre el **chequeo de integridad** y reporta:
  - códigos de componente que no existen en `precios.db` (huérfanos), y
  - descalces de nombre (nombre embebido en el APU ≠ nombre del código en el catálogo),
    reusando la lógica del escaneo ya hecho.
  Expuesto también como comando `db check` para correrlo cuando se quiera.

## Lo que NO cambia / invariantes
- **Invariante #1:** la IA nunca ve dinero. La frontera de `privacy.py` no se toca; el costo
  lo sigue calculando solo `pricing.py`.
- El pipeline de armado, el reporte categorizado, el matching y la CLI/GUI siguen
  funcionando; solo cambia **de dónde leen** (Almacen en vez de un único Database).
- `precio_unitario_hist` embebido se conserva como respaldo.
- El comando `build-ppto` y el flujo plano siguen igual de cara al usuario.

## Alcance
**Dentro:**
- **Reorganización completa a la estructura por capas** (objetivo de ARQUITECTURA.md):
  mover los módulos existentes a `apu_tool/dominio/` (`models, licitacion, presupuesto,
  matching, privacy, ai_assist, compose, assemble, pricing, report, report_categorizado,
  pipeline`) y `apu_tool/interfaz/` (`cli, gui`); crear `apu_tool/datos/` y
  `apu_tool/servicio/` (vacío). Actualizar todos los imports y los lanzadores
  `run_cli.py`/`run_gui.py`.
- `db/precios.sql`, `db/apus.sql` (esquemas canónicos portables a Postgres, con comentarios
  de dialecto como ya se hizo).
- `datos/precios_db.py`, `datos/apus_db.py`, `datos/almacen.py`, `datos/repositorio.py`
  (dos contratos), `datos/seed.py`, `datos/correcciones.py`, `datos/integridad.py`.
- Adaptar el dominio (`pricing`, `assemble`, `compose`, `matching`, `pipeline`) y la interfaz
  (`cli`, `gui`) para usar `Almacen` en vez del `Database` único.
- `seed` guardado (importación una vez) + lista de correcciones (4613→3017) + `db check`.
- Migrar/retirar el `data/apu.db` único y los comandos `db rebuild`/`ingest` actuales.
- Tests: esquemas, los dos repos, la fachada, el seed con corrección, el chequeo de
  integridad; **adaptar imports y fixtures** de los 44 tests existentes a la nueva estructura.

**Fuera (YAGNI por ahora):**
- Postgres/nube real (solo dejamos el acceso aislado para hacerlo después).
- GUI nueva de edición de datos.
- Normalización masiva de TODOS los insumos (solo corregimos los descalces detectados; la
  normalización completa es su propia skill, `apu-civil:apu-normalizar`, más adelante).

## Riesgos y mitigación
- **Churn muy amplio (doble):** este paso mueve TODOS los módulos a carpetas por capa Y
  cambia `Database` por `Almacen`. Mitigación: hacerlo por tareas separadas — primero la
  reorganización de carpetas (solo mover + arreglar imports, sin cambiar lógica; suite verde
  como red de seguridad), y solo después partir la base. La fachada expone los dos repos con
  métodos de igual firma a los actuales, así el segundo cambio es mayormente mecánico. Los 44
  tests deben quedar verdes tras adaptar imports y fixtures.
- **Pérdida de la FK cruzada APU→insumo:** se compensa con el chequeo de integridad en la
  app (huérfanos + descalces), que además es más informativo que una FK.
- **Seed destructivo por accidente:** mitigado por el guard (`--force` requerido si hay datos).
- **Remapeo 4613→3017 demasiado amplio:** mitigado porque el escaneo probó que 4613 no se usa
  legítimamente como unión PVC en ningún APU; aun así el `db check` posterior delata cualquier
  efecto inesperado.

## Verificación
- `python -m pytest tests/ -q` — todo verde (44 existentes adaptados + nuevos).
- `python run_cli.py seed` crea `precios.db` y `apus.db`; correr `seed` de nuevo sin `--force`
  se niega; con `--force` re-semilla.
- `python run_cli.py db check` reporta 0 huérfanos y los descalces restantes (idealmente 0 de
  alto impacto; 9164/4513 son menores y conocidos).
- `python run_cli.py build-ppto` produce el cuadro y el ítem 13.601 ya da margen positivo
  (~+12%), confirmando que la corrección del 4613 persiste y se aplica.
- `python run_cli.py status` reporta conteos de ambas bases.

## Nota de versionado
El proyecto no es repositorio git; el spec queda versionado por existir en el árbol.
