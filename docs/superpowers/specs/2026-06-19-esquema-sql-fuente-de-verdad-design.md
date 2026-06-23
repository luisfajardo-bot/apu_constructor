# Esquema SQL como fuente de verdad

**Fecha:** 2026-06-19
**Estado:** aprobado para planificar

## Objetivo

Sacar el DDL del esquema (hoy embebido como string `SCHEMA` en
[`apu_tool/db.py`](../../../apu_tool/db.py)) a un archivo `.sql` versionado que sea el
**origen canónico** del modelo de datos. Esto deja la definición de la base en limpio
y prepara el terreno para una futura migración a Postgres/nube (plan "local primero,
nube después").

De paso, se sanea la **integridad referencial**: hoy la base activa
`PRAGMA foreign_keys = ON` pero no declara ninguna FK, y `apu_componentes` no tiene
clave primaria.

## Decisiones acordadas

1. **Un solo archivo canónico:** `db/schema.sql` (carpeta `db/` en la raíz del proyecto).
2. **SQL portable:** se escribe para correr hoy en SQLite, estructurado para que la
   migración a Postgres sea mecánica. Las diferencias de dialecto se anotan en
   comentarios dentro del `.sql`.
3. **Saneamiento = integridad + comentarios:** mismas tablas y columnas (sin rediseño
   del modelo), pero con FOREIGN KEYs reales, PK en `apu_componentes` y comentarios que
   hacen explícita la intención.
4. **`apu_componentes.insumo_codigo` queda como enlace blando (opción A):** sin FK dura,
   porque el Excel histórico puede citar códigos de insumo huérfanos y el componente ya
   guarda `insumo_nombre`/`unidad` desnormalizados. Preferimos no romper la ingesta.

## Alcance

### Archivos afectados
- **Nuevo:** `db/schema.sql` — DDL canónico, portable, comentado.
- **Modificado:** `apu_tool/db.py` — deja de tener el string `SCHEMA`; lee el `.sql`.
- **Sin cambios de firma:** [`apu_tool/repository.py`](../../../apu_tool/repository.py)
  (`init_schema`/`reset` mantienen su contrato).

### Esquema (`db/schema.sql`)

Mismas tablas y columnas que hoy, con estos cambios de integridad:

| Tabla | Cambio |
|-------|--------|
| `insumos` | sin cambios (PK `codigo`) |
| `insumo_precios` | `id INTEGER PRIMARY KEY` (se quita `AUTOINCREMENT`, más portable; comentario con el equivalente Postgres `GENERATED ALWAYS AS IDENTITY`). **FK** `codigo → insumos(codigo)`. |
| `apus` | sin cambios (PK `codigo, shift`) |
| `apu_componentes` | **PK nueva** `(apu_codigo, shift, seq)`. **FK** `(apu_codigo, shift) → apus(codigo, shift)`. `insumo_codigo` SIN FK (enlace blando, opción A). |
| `meta` | sin cambios |

Índices actuales se conservan, ahora comentados:
- `idx_comp_apu` sobre `apu_componentes(apu_codigo, shift)`
- `idx_apus_nombre` sobre `apus(nombre)`
- `idx_precio_cod` sobre `insumo_precios(codigo, vigente)`

### Carga del esquema en `db.py`
- Se elimina la constante `SCHEMA`.
- Se añade una función/constante que lee `db/schema.sql` desde la raíz del proyecto
  (vía `config.PROJECT_ROOT / "db" / "schema.sql"`, manteniendo el acceso a rutas
  centralizado).
- `init_schema()` ejecuta el contenido del `.sql`.
- `reset()` ejecuta el `.sql` y luego borra filas en **orden hijos→padres**
  (`apu_componentes → insumo_precios → apus → insumos → meta`) para respetar las FKs.

## Lo que NO cambia
- El modelo de dominio ([`models.py`](../../../apu_tool/models.py)) y sus vistas `DePriced*`.
- La invariante #1 (la IA nunca ve dinero): este trabajo no toca la frontera de privacidad.
- El contrato de [`repository.py`](../../../apu_tool/repository.py).
- La lógica de ingesta, matching, pricing, reporte ni la GUI/CLI.

## Riesgos y mitigación
- **Orden de borrado en `reset()`:** con FKs activas, borrar padres antes que hijos
  falla. Mitigación: reordenar los `DELETE` a hijos→padres (incluido en el alcance).
- **`PRAGMA foreign_keys = ON` por conexión:** SQLite requiere activarlo en cada
  conexión; ya se hace en `Database.connect()`. Verificar que sigue presente.
- **Ruta del `.sql` al empaquetar:** se lee desde `PROJECT_ROOT`; si en el futuro se
  empaqueta como wheel habría que usar `importlib.resources`. Fuera de alcance hoy
  (la app corre desde el repo), pero se deja anotado.

## Verificación
- Correr `python -m pytest tests/ -q` — los 20 tests deben seguir pasando.
- `python run_cli.py db rebuild` debe reconstruir la base desde el Excel sin error.
- `python run_cli.py status` debe reportar los mismos conteos que antes.

## Nota de versionado
El proyecto no es un repositorio git (verificado en esta sesión), así que no hay paso
de commit. El `.sql` queda versionado por su mera existencia en el árbol del proyecto.
