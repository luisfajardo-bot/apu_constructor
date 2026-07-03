# Diseño — Importador unificado de insumos (upsert)

**Fecha:** 2026-07-03
**Estado:** aprobado (diseño)

## Problema

Hoy hay **dos** importadores de insumos, confusos por nombre y separados:

- **Importar para crear** (`/insumos/importar-crear`): identifica por **código+nombre**,
  crea insumos nuevos; si ya existe, lo **omite** (no toca el precio).
- **Importar (precios)** (`/insumos/importar/preview` + `/insumos/cambios`): identifica
  por **código**, actualiza precio de existentes; no crea; ambiguo si el código se repite.

El usuario quiere **un solo importador** que haga lo correcto según la fila (upsert).

## Objetivo

Un único importador de insumos que, por archivo, **cree** los que no existen y
**actualice el precio** de los que sí, decidiendo por fila. Reemplaza a los dos
actuales (un botón, un diálogo, un par de endpoints, una plantilla).

## Comportamiento — regla por fila

Columnas del archivo (Excel/CSV): `codigo, nombre, unidad, grupo, precio, fuente`.
Encabezados flexibles (igual que hoy: `codigo/cod/code`, `nombre/descripcion/name`, etc.).
Solo `codigo` es obligatorio; `nombre` decide el modo de la fila.

| Fila | Acción | Bucket |
|---|---|---|
| Con nombre, y (código+nombre) ya existe | Actualiza precio(+fuente) del que coincide | **actualizar** |
| Con nombre, no existe esa identidad | Crea el insumo con todos los campos | **crear** |
| Sin nombre, código con **un** candidato | Actualiza precio por código | **actualizar** |
| Sin nombre, código con **varios** candidatos | Se omite (no sabe cuál) | **ambigua** |
| Sin nombre, código **sin** candidatos | Se omite (no puede crear sin nombre) | **no_encontrada** |
| Sin código | Se omite | **invalida** |

### Reglas finas
- **Identidad** = `codigo` + `normalizar(nombre)` (la del sistema; ver
  `apu_tool.nucleo.texto.normalizar`). Con nombre nunca hay ambigüedad.
- **Actualizar** solo toca **precio + fuente** del insumo existente; jamás cambia
  su nombre/unidad/grupo (la identidad no se pisa).
- **Precio vacío en una fila de actualización → NO cambia el precio** (regla de
  seguridad; evita poner 0 por accidente). Para poder distinguir "vacío" de "0",
  el parser conserva si la celda de precio venía informada.
- **Fuente vacía en actualización → conserva la fuente actual** (como hoy).
- **Crear**: usa todos los campos; precio vacío → 0 (como hoy).
- Preview-and-confirm: el preview muestra los buckets con conteos + tabla
  (código · nombre · precio actual → nuevo · acción). Al aplicar, solo se procesan
  `crear` y `actualizar`; el resto se omite.

## Alcance del reemplazo (no suma un tercero)

- **Frontend:**
  - Nuevo diálogo `web/src/components/insumos/DialogoImportarInsumos.tsx` (unificado).
  - Un solo botón **“Importar”** en `web/src/pages/Insumos.tsx` (se quitan los dos
    actuales: “Importar para crear” y “Importar”).
  - Se **eliminan** `DialogoImportar.tsx` (precios) y `DialogoImportarCrearInsumos.tsx`.
  - API en `web/src/api/insumos.ts`: `previewImportarInsumos(form)`,
    `aplicarImportarInsumos(form)`, `descargarPlantillaInsumos()`. Se retiran las
    funciones de los flujos viejos que queden sin uso (`importarPreview`,
    `previewImportarInsumos`/`aplicarImportarInsumos` del flujo crear en `autoria.ts`,
    `descargarPlantillaPrecios`).
- **Backend:**
  - Servicio unificado en `apu_tool/servicio/autoria.py`:
    `preview_importar_insumos(alm, contenido, nombre) -> {crear, actualizar, ambigua, no_encontrada, invalida}`
    y `aplicar_importar_insumos(alm, contenido, nombre, actor) -> {creados, actualizados, errores}`.
    (Reemplazan a las versiones crear-solo actuales, mismos nombres.)
  - Endpoints unificados: `POST /insumos/importar/preview` y `POST /insumos/importar`
    (rol `editor`). Se **eliminan** los de crear-solo (`/insumos/importar-crear*`) y el
    de precios viejo pasa a ser el unificado.
  - Se **elimina** `insumos.preview_import` (precios-solo) al quedar sin uso.
  - `aplicar_cambios` (edición individual/batch en la tabla) **se conserva** — lo usa
    `TablaInsumos`, no es parte de este flujo.
- **Plantilla:** una sola `plantilla_insumos.xlsx` (columnas completas, nombre opcional)
  vía `GET /insumos/importar/plantilla`. Se elimina `plantilla_precios` y su endpoint
  `/insumos/importar-crear/plantilla` se consolida en `/insumos/importar/plantilla`.
  La plantilla incluye una nota/fila de ejemplo mostrando que sin nombre solo actualiza.
- **APUs:** su importador **no se toca**.

## Componentes y límites

- `autoria.py` gana la lógica de clasificación (`_clasificar_fila`) y el upsert.
  Reutiliza helpers existentes: `_filas_insumos` (parser; se extiende para conservar
  "precio informado"), `normalizar`, `alm.precios.get_candidatos/crear_insumo/
  set_precio_por_id/get_insumo_por_id`, `registrar_auditoria`.
- El diálogo unificado sigue el patrón de los actuales (fase idle/cargando/preview/
  aplicando, re-envía el archivo al aplicar).

## Flujo de datos

```
archivo → POST /insumos/importar/preview → clasifica filas → {crear, actualizar, ambigua,
   no_encontrada, invalida} → usuario revisa → POST /insumos/importar (re-envía archivo)
   → crea nuevos + actualiza precios (con auditoría) → {creados, actualizados, errores}
```

## Manejo de errores

- Archivo no-Excel/corrupto → 400 (como hoy: `BadZipFile`/`InvalidFileException`).
- Fila sin código/ambigua/no encontrada → se omite (no es error; sale en su bucket).
- Al aplicar, un fallo por fila (ej. `ValueError` de validación) → se acumula en
  `errores`, no aborta el resto.
- Rol insuficiente → 403.

## Pruebas (candado de seguridad)

- **Unitarias de clasificación** (`tests/test_servicio_autoria.py` o test nuevo): una por
  bucket — con nombre existente→actualizar; con nombre nuevo→crear; sin nombre código
  único→actualizar; sin nombre repetido→ambigua; sin nombre inexistente→no_encontrada;
  sin código→invalida; **precio vacío en actualización→no cambia precio**.
- **Aplicar**: crea los nuevos y actualiza precios de los existentes en una pasada;
  verifica conteos `{creados, actualizados}` y que el precio quedó actualizado + historial.
- **Ruta**: `POST /insumos/importar/preview` y `/insumos/importar` → 200 y buckets/conteos;
  403 sin `editor`; archivo malo → 400.
- **Plantilla**: round-trip — la plantilla unificada se re-alimenta al parser y clasifica
  bien (una fila crear + una fila actualizar). Endpoint 200 + content-type + attachment.
- **Frontend**: build + tests verdes; el diálogo unificado compila y descarga la plantilla.
- **Regresión**: suite completa backend + frontend verde antes y después.

## Seguridad / invariantes

- **Invariante #1** intacta: toca precios (catálogo) pero **no** el camino de la IA.
- **Auditoría**: crear y actualizar registran en auditoría (como hoy).
- **Sin cambios de esquema/DB/migración.**
- Reemplazo quirúrgico: no toca `aplicar_cambios` (edición en tabla), corridas, ni APUs.
- TDD, rama aislada, suite verde; sin push hasta confirmación (despliega a producción).
