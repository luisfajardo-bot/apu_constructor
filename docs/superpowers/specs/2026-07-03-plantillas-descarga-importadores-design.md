# Diseño — Descarga de plantillas de importación (APUs, Insumos, Precios)

**Fecha:** 2026-07-03
**Estado:** aprobado (diseño)

## Problema

Los usuarios importan datos (APUs, insumos nuevos, actualización de precios) desde
Excel/CSV, pero **no hay una plantilla oficial**: cada quien arma el archivo a mano
o se pasa plantillas por fuera (inseguro, se desactualizan, no siempre disponibles).
El formato de la hoja `APUS` en particular es posicional y difícil de adivinar.

## Objetivo

Un botón **"Descargar plantilla"** junto a cada control de importación, que entregue
un `.xlsx` con el formato exacto que espera el parser correspondiente. Siempre
disponible, imposible de desincronizar del parser.

## Alcance

Tres importadores existentes (todos rol `editor`):

| Importador | Endpoint import | Formato |
|---|---|---|
| **APUs** | `POST /apus/importar` | Excel con hoja `APUS` (encabezado de APU + filas de componentes) |
| **Insumos nuevos** | `POST /insumos/importar-crear` | Tabla `codigo, nombre, unidad, grupo, precio, fuente` |
| **Actualizar precios** | `POST /insumos/importar/preview` | Tabla `codigo, precio, fuente` |

## No-objetivos (fuera de alcance)

- No se modifica ningún parser ni endpoint de import existente.
- No se toca la IA (Invariante #1: esto es catálogo, no abre camino a la IA).
- Sin cambios de esquema, DB ni migración.
- No se importan las plantillas automáticamente; el usuario las llena y sube por el
  flujo normal (preview-and-confirm).

## Enfoque

**Generar la plantilla al vuelo en el backend con openpyxl** (no archivos estáticos).

- *Por qué:* la plantilla usa las **mismas constantes/columnas que el parser**, así
  que no puede quedar desalineada; no metemos binarios al repo; "siempre disponible"
  sin mover archivos.
- *Alternativa descartada:* `.xlsx` pre-hechos en `web/public/` — simples, pero
  divergen del parser en silencio y reintroducen el "andar moviendo archivos".

## Componentes

### Backend

**Módulo nuevo `apu_tool/servicio/plantillas.py`** — 3 funciones puras `() -> bytes`
que construyen un workbook en memoria (`BytesIO`):

- `plantilla_apus()`:
  - Hoja renombrada a **`APUS`**.
  - Fila 1 = encabezados en las **posiciones exactas de `seed.APUS_COLS`**
    (se importa la constante; no se hardcodean índices → cero drift):
    `ACTIVIDAD | COD IDU | UN | INSUMO | COD | UND | RENDIMIENTO | INV | PRECIO UNITARIO | COSTO TOTAL | DIURNO/NOCTURNO`.
  - 1 APU de ejemplo: fila de encabezado con **COD IDU numérico** `999001`
    (necesario para que `_looks_like_code` lo detecte como APU) y ACTIVIDAD
    `"EJEMPLO — reemplazar"`, turno `DIURNO` en la col. de turno; + 2 filas de
    componentes de ejemplo (INSUMO, COD, UND, RENDIMIENTO).
- `plantilla_insumos_crear()`:
  - Encabezados `codigo, nombre, unidad, grupo, precio, fuente`.
  - 1 fila de ejemplo con `codigo="EJEMPLO-1"`, `nombre="EJEMPLO — reemplazar"`.
- `plantilla_precios()`:
  - Encabezados `codigo, precio, fuente`.
  - 1 fila de ejemplo con `codigo="EJEMPLO-1"`, `precio=1000`, `fuente="COTIZACIÓN"`.

Las filas de ejemplo van marcadas visiblemente; como el import es preview-and-confirm,
el usuario las ve antes de aplicar y las reemplaza/borra.

**3 endpoints GET en `rutas.py`** (nombres consistentes con los de importar), rol
`editor`, devuelven el `.xlsx` con `Content-Disposition: attachment`:

- `GET /apus/importar/plantilla`
- `GET /insumos/importar-crear/plantilla`
- `GET /insumos/importar/plantilla`

Se reutiliza la constante `_XLSX` (media type) ya definida en `rutas.py` y
`fastapi.responses.Response(content=..., media_type=_XLSX, headers={...})`.

### Frontend

**3 funciones de descarga** (en `web/src/api/autoria.ts` y `web/src/api/insumos.ts`)
que **clonan `descargarCuadro`** de `api/corridas.ts`: `fetch` con `authHeader()` →
`blob()` → `<a download>` con `URL.createObjectURL`.

- `descargarPlantillaApus()`, `descargarPlantillaInsumos()` (autoria.ts)
- `descargarPlantillaPrecios()` (insumos.ts)
- Nombres de archivo: `plantilla_apus.xlsx`, `plantilla_insumos.xlsx`, `plantilla_precios.xlsx`.

**Botón "Descargar plantilla"** (variant `outline`, `size="sm"`, con icono de descarga)
**junto al input de archivo** dentro de cada uno de los 3 diálogos:

- `web/src/components/autoria/DialogoImportarApus.tsx`
- `web/src/components/autoria/DialogoImportarCrearInsumos.tsx`
- `web/src/components/insumos/DialogoImportar.tsx`

Denso, sin cards (preferencia de UI). En caso de error de descarga → `toast.error`.

## Flujo de datos

```
click "Descargar plantilla" → GET autenticado → backend arma xlsx en memoria (openpyxl)
   → Response(bytes, xlsx, attachment) → blob → <a download> → archivo en Descargas
```

Sin estado, sin DB, sin IA.

## Manejo de errores

- Backend: la generación es determinística y no puede fallar salvo por auth (403 sin
  rol `editor`, 401 sin sesión). Sin ramas de error propias.
- Frontend: si el `fetch` falla → `toast.error(...)`, igual que `descargarCuadro`.

## Pruebas (candado de seguridad)

**`tests/test_plantillas.py`** — por cada plantilla:

1. Devuelve `bytes` no vacíos y abre como workbook válido con openpyxl.
2. **Round-trip (clave):** se re-alimenta la plantilla a su propio parser y se
   verifica que la(s) fila(s) de ejemplo se parsean:
   - `plantilla_apus()` → `autoria.preview_importar_apus(...)` devuelve ≥1 APU en
     `crear` (o `ya_existe`), con 2 componentes.
   - `plantilla_insumos_crear()` → `autoria.preview_importar_insumos(...)` devuelve el
     ejemplo en `crear` (código y nombre no vacíos).
   - `plantilla_precios()` → `insumos._parse_tabla(...)` devuelve una fila con
     `codigo="EJEMPLO-1"` y `precio=1000.0`.

   Esto **garantiza por construcción** que plantilla y parser nunca divergen: si
   alguien cambia un parser sin actualizar la plantilla, el test truena.

**Tests de ruta** (extienden `tests/test_api_*.py`): cada `GET .../plantilla` →
200, `content-type` xlsx, header `Content-Disposition: attachment`, cuerpo no vacío;
y 403 sin rol `editor`.

**Frontend:** test de descarga clonado de `web/src/api/corridas.descarga.test.ts`
(mock de `fetch` + `URL.createObjectURL` + `<a>.click`).

## Seguridad / invariantes preservadas

- **Adición pura:** ningún parser ni endpoint de import existente se modifica.
- **Invariante #1** (la IA nunca ve dinero) intacta: las plantillas son catálogo,
  no tocan el camino de la IA.
- Sin cambios de esquema/DB/migración; nada que revertir si se descarta.
- Auth `editor` consistente con los endpoints de importación.
