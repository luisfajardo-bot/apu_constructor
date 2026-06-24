# Diseño — Frontend web (Proyecto 1: shell + corrida + edición de insumos)

> Fecha: 2026-06-24
> Estado: aprobado para implementación
> Antecede: `2026-06-24-frontend-api-web-design.md` (backend v1, ya fusionado en master).
> Hoja de ruta: ejecuta el paso 5 (app web) de `docs/ARQUITECTURA.md`, primer corte.

## Objetivo

Construir el frontend web del Armador de APUs (Vite + React + shadcn/ui, servido por
FastAPI) con dos capacidades en este Proyecto 1:
1. **Flujo de corrida** sobre el backend v1 ya existente: subir licitación → ver el cuadro →
   revisar/confirmar ítems dudosos → descargar el Excel.
2. **Edición de insumos** (precio + fuente), **individual y en batch**, con tres mecanismos:
   grid editable, importación Excel/CSV y transformación masiva por filtro. Requiere
   endpoints y métodos de datos nuevos.

La edición de **composición de APUs** queda explícitamente para el **Proyecto 2**.

La UI es **práctica y densa, orientada a tabla, sin cards** (instrucción del usuario).

## Decisiones de alcance

| Decisión | Elección |
|----------|----------|
| Secuencia | Incremental. Proyecto 1 = shell + corrida + edición de insumos. Proyecto 2 = composición de APUs |
| Qué se edita | Insumos: precio + fuente (individual y batch). APUs NO en este proyecto |
| Mecanismos de batch | Los tres: grid editable, importar Excel/CSV, transformación masiva por filtro |
| Identidad al editar | Por **id** de insumo (los códigos se repiten), no por código |
| Stack | Vite + React + TS + shadcn/ui, compilado a `web/dist` y servido por FastAPI |
| Parseo de Excel | En el **servidor** (reusa `openpyxl`); sin librería xlsx en JS |
| Estética | Densa, table-first, sin cards; dinero monoespaciado alineado a la derecha |
| Despliegue | Local, sin login (igual que el backend v1) |

Fuera de alcance (Proyecto 2+): edición de composición/metadata de APUs; auth; Postgres/nube;
progreso por SSE; resolución interactiva de códigos ambiguos en la importación (en v1 se
listan y no se aplican).

## Arquitectura y estructura de archivos

El dominio NO se toca. El módulo de insumos es edición pura de catálogo/precios y **no roza la
IA**. Toda persistencia nueva vive en `apu_tool/datos/`.

```
web/                                   [nuevo — Vite + React + TS + shadcn/Tailwind]
├── index.html  vite.config.ts  package.json  tsconfig.json  components.json
├── src/
│   ├── main.tsx  App.tsx              # router + Layout
│   ├── api/    client.ts · corridas.ts · insumos.ts   # cliente fetch tipado a /api
│   ├── pages/  CorridasInicio.tsx · Corrida.tsx · Insumos.tsx
│   ├── components/  Layout.tsx · corrida/* · insumos/*
│   └── lib/    moneda.ts · tipos.ts · useDirtyRows.ts
└── (build → web/dist, servido por FastAPI cuando existe)

apu_tool/datos/precios_db.py    # + set_precio_por_id, list_insumos, grupos, fuentes
apu_tool/datos/repositorio.py   # + esos métodos en RepositorioPrecios (Protocol)
apu_tool/servicio/insumos.py    # [nuevo] lógica de servicio de insumos
apu_tool/servicio/rutas.py      # + endpoints /api/insumos*
apu_tool/servicio/esquemas.py   # + DTOs de insumos
```

`vite.config.ts` hace proxy de `/api` a FastAPI (:8000) en desarrollo. En producción, `npm run
build` genera `web/dist`, que FastAPI ya sirve (cableado en `app.py`); `run_web.py` abre `/`
cuando existe `dist` y `/docs` mientras no.

## Espina dorsal de la edición

Una sola primitiva de aplicación, alimentada por tres formas de producir cambios:

```
                       ┌─ Grid editable (editar filas) ──┐
Filtro/búsqueda ──────►├─ Transformar por filtro ────────┤──► lista de cambios
                       └─ Importar Excel/CSV ────────────┘    [{insumo_id, precio, fuente}]
                                                                     │
                                          POST /api/insumos/cambios (aplica todo, reporta
                                          ok/error por ítem, guarda historial por insumo)
```

## Backend nuevo (datos + servicio + API)

### Capa de datos — `PreciosDB`
- `set_precio_por_id(insumo_id, precio, fuente)` — versión por id de `set_precio`: marca el
  precio vigente anterior `vigente=0` e inserta uno nuevo `vigente=1` con su `clasificacion`
  (público/interno). **Guarda historial**, igual que hoy. `set_precio` se refactoriza para
  resolver el id y delegar aquí (DRY).
- `list_insumos(q=None, grupo=None, fuente=None, limit=100, offset=0) -> tuple[list[Insumo], int]`
  — lista filtrable con precio/fuente vigentes; devuelve los insumos de la página y el total.
- `grupos() -> list[str]`, `fuentes() -> list[str]` — valores distintos para los filtros.

Estos métodos se agregan también al `Protocol RepositorioPrecios` en `repositorio.py`.

### Servicio — `apu_tool/servicio/insumos.py`
- `listar(alm, q, grupo, fuente, limit, offset) -> dict` → `{items: [InsumoOut], total}`.
  `InsumoOut` incluye `clasificacion` (derivada de la fuente con `config.classify_price_source`).
- `detalle(alm, insumo_id) -> Optional[dict]` → insumo vigente + `historial` (de `price_history`).
- `aplicar_cambios(alm, cambios: list[dict]) -> dict` → para cada `{insumo_id, precio, fuente}`
  llama `set_precio_por_id`; acumula `{aplicados: int, errores: [{insumo_id, error}]}`. Un id
  inexistente o un precio inválido (`< 0` / no numérico) es un error **por ítem**, no tumba el lote.
- `preview_import(alm, contenido_archivo, nombre) -> dict` → parsea Excel/CSV con `openpyxl`
  (encabezados tolerantes: código, precio, fuente). Resuelve cada código vía `get_candidatos`:
  exactamente 1 → `cambio` `{insumo_id, codigo, nombre, precio_actual, precio_nuevo, fuente_nueva}`;
  >1 → `ambiguo` (con candidatos); 0 → `no_encontrado`. Devuelve
  `{cambios: [...], ambiguos: [...], no_encontrados: [...]}`. **No aplica.**
- `preview_transformar(alm, filtro: dict, operacion: dict) -> dict` → resuelve el conjunto
  filtrado (vía `list_insumos` sin límite efectivo) y calcula el cambio por insumo según la
  operación: `{tipo: "fuente", valor: "X"}` (cambia fuente), `{tipo: "precio_factor", valor: 1.1}`,
  `{tipo: "precio_pct", valor: 10}`, `{tipo: "precio_set", valor: 1000}`. Devuelve la lista de
  cambios + `afectados: int`. **No aplica.**

El servicio de insumos NO importa ni llama `ai_assist` (no hay IA en este módulo).

### Endpoints — `apu_tool/servicio/rutas.py`
| Método + ruta | Hace |
|---|---|
| `GET /api/insumos?q=&grupo=&fuente=&limit=&offset=` | lista filtrable + paginada `{items, total}` |
| `GET /api/insumos/grupos` | grupos distintos (para el filtro) |
| `GET /api/insumos/fuentes` | fuentes distintas (para el filtro) |
| `GET /api/insumos/{id}` | detalle + historial de precios; 404 si no existe |
| `POST /api/insumos/cambios` | body `{cambios:[{insumo_id,precio,fuente}]}` → aplica; `{aplicados, errores}` |
| `POST /api/insumos/importar/preview` | multipart archivo → `{cambios, ambiguos, no_encontrados}` (no aplica) |
| `POST /api/insumos/transformar/preview` | body `{filtro, operacion}` → `{cambios, afectados}` (no aplica) |

### DTOs — `apu_tool/servicio/esquemas.py`
`InsumoOut {id, codigo, nombre, unidad, grupo, precio, fuente, clasificacion}`,
`CambioIn {insumo_id:int, precio:float, fuente:str}`, `CambiosIn {cambios:[CambioIn]}`,
`TransformarIn {filtro:dict, operacion:dict}`. Las respuestas de listar/preview se devuelven
como dict (consistente con el backend v1).

## Frontend — shell + flujo de corrida

**App shell (`Layout.tsx`):** barra superior delgada con el nombre del producto + chip de
estado (`GET /api/status`: nº insumos/APUs, IA habilitada/fallback). Navegación lateral
compacta con dos secciones: **Corridas** e **Insumos**. Contenido a ancho completo, denso, sin
cards.

**Flujo de corrida** (consume los endpoints del backend v1, sin backend nuevo):
- **CorridasInicio** — subir `.xlsx/.csv` (selector de turno, toggle IA) + botón "Usar ejemplo"
  → `POST /api/corridas` o `POST /api/sample` → navega a `/corridas/{id}`.
- **Corrida** — barra de totales arriba (contractual, costo, margen, margen %); tabla densa de
  ítems (descripción · und · cantidad · APU · estado · contractual · costo · margen · %); filtro
  "solo revisión" con contador; botón "Descargar cuadro" (`GET .../cuadro`). Estado como
  badge/texto de color pequeño (no card). Dinero monoespaciado, alineado a la derecha, formato
  COP `$1,234,567`.
- **Panel de revisión** (drawer) — para ítems REVIEW/NEW: descripción + APU propuesto +
  explicación; candidatos con score; composición costeada (insumo · und · rend · precio · costo
  · calidad de cruce); confirmar o elegir candidato → `POST .../confirmar` → recosteo en vivo y
  totales actualizados.

## Frontend — módulo de insumos (el grid)

Una sola página **Insumos**, orientada a tabla, que cubre individual + los tres mecanismos de batch:

- **Barra de filtros:** búsqueda de texto (`q`), dropdown de grupo, dropdown de fuente, filtro
  público/interno. Paginación (limit/offset; por defecto ~100). Con 8157 insumos siempre se
  filtra/pagina; nunca se cargan todos.
- **Tabla editable:** código · nombre · unidad · grupo · **precio (editable)** · **fuente
  (editable: combobox de fuentes existentes + texto libre)** · clasificación (derivada). Editar
  una celda marca la **fila sucia** (resaltada) vía `useDirtyRows`. Barra de acción fija:
  *"N cambios sin guardar — [Guardar] [Descartar]"* → `POST /api/insumos/cambios` → muestra
  resultado por ítem (ok/error) y refresca. Una fila = individual; varias = batch, misma pantalla.
- **Botón "Transformar"** → diálogo: conjunto = filtro actual; operación = (fuente → X) o
  (precio: ×factor / +% / = valor) → `POST /api/insumos/transformar/preview` muestra cuántos
  afecta + lista → "Aplicar" → `POST /api/insumos/cambios`.
- **Botón "Importar"** → diálogo: subir Excel/CSV → `POST /api/insumos/importar/preview` muestra
  **reconocidos / ambiguos / no encontrados** → "Aplicar los N reconocidos" →
  `POST /api/insumos/cambios`. Los ambiguos/no encontrados se listan, nunca se aplican a ciegas.
- **Detalle de fila** → `GET /api/insumos/{id}`: historial de precios en un drawer/popover denso.

**Estética:** práctico y denso, table-first, sin cards; dinero monoespaciado alineado a la
derecha; acciones en barras y diálogos, no en tarjetas.

## Errores, privacidad y pruebas

**Privacidad (Invariante #1):** el módulo de insumos no abre ningún camino hacia la IA — la IA
sigue viendo solo estructura `DePriced` dentro del dominio. Los endpoints de insumos devuelven
dinero (dato interno del equipo), permitido. El test que verifica que `apu_tool/servicio/` no
contiene la cadena `"ai_assist"` aplica también a los archivos nuevos.

**Errores:**
- Edición por **id** → sin ambigüedad de código al guardar.
- `POST /api/insumos/cambios`: id inexistente o precio inválido (`< 0` / no numérico) → error
  **por ítem** en el resultado, no un 500 para todo el lote; los demás se aplican.
- Importar: códigos ambiguos (>1) o no encontrados → en el preview, nunca se aplican a ciegas.
- Excel/CSV ilegible o sin columnas código/precio → `400` con mensaje.
- Transformar: preview obligatorio (muestra afectados) antes de aplicar.

**Pruebas:**
- **Backend (pytest + TestClient):** `set_precio_por_id` (crea historial, voltea `vigente`);
  `list_insumos` con filtros + paginación; `aplicar_cambios` (mezcla ok + errores);
  `preview_import` (reconocido/ambiguo/no encontrado); `preview_transformar` (cada operación);
  endpoints nuevos vía TestClient.
- **Frontend:** ligero — Vitest + React Testing Library para `useDirtyRows` (marcar/guardar/
  descartar), la lógica de guardado del grid y el render del preview de importación. Smoke
  manual para lo visual.
- `python -m pytest tests/ -q` debe seguir verde (incluye el backend v1).

**Build/serve:** `npm run build` en `web/` genera `web/dist`; FastAPI lo sirve; `run_web.py`
abre `/` cuando existe `dist`.

## Dependencias nuevas

- **Backend:** ninguna (reusa `openpyxl` para el parseo de importación).
- **Frontend (solo build):** Node + Vite + React + TypeScript + Tailwind + `shadcn/ui`; Vitest +
  React Testing Library para pruebas. Aislado en `web/`; no afecta el runtime de Python.

## Criterios de aceptación (Proyecto 1)

1. `npm run build` genera `web/dist`; `python run_web.py` abre la app en `/` (un solo proceso).
2. Navegación entre **Corridas** e **Insumos** desde el shell; el chip de estado muestra conteos e IA.
3. Flujo de corrida completo desde la UI: subir/ejemplo → cuadro con totales → revisar/confirmar
   un ítem (recosteo en vivo) → descargar el Excel.
4. Insumos: filtrar/paginar; editar precio y/o fuente en una o varias filas y "Guardar" aplica el
   batch con reporte por ítem; el historial del insumo refleja el cambio.
5. Transformar por filtro: preview muestra afectados; aplicar persiste.
6. Importar Excel/CSV: preview separa reconocidos/ambiguos/no encontrados; aplicar solo los
   reconocidos.
7. `pytest` pasa, incluido el backend v1; el test de privacidad cubre los archivos nuevos.
8. La IA nunca recibe dinero (invariante intacto); el módulo de insumos no toca la IA.
