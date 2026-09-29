# Fuente de precio: solo dos opciones

**Fecha:** 2026-09-29 · **Rama:** `feat/fuente-dos-opciones`

## Qué

La fuente de un precio deja de ser texto libre: solo `PRECIO IDU` o `COSTO INTERNO`
(`config.FUENTES_PRECIO`). Lo que ya está guardado con otras etiquetas **no se migra**;
la regla aplica a lo que se escriba de ahora en adelante.

## Web

- **Tabla de Insumos:** la fuente es un selector. Digitar un precio pone la fuente de esa
  fila en `COSTO INTERNO`; se puede cambiar a `PRECIO IDU`. Una etiqueta vieja se muestra
  tal cual mientras la fila no se toque.
- **Agregar insumo:** selector, `COSTO INTERNO` preseleccionado.
- **Importar insumos:** selector **sin** preselección (una importación suele ser el
  listado del IDU; un default interno rotularía mal miles de filas).
- **Filtro de fuentes:** sin cambio (lista lo que existe, viejas incluidas).

## Backend (la regla no depende del cliente)

`config.normalizar_fuente_precio(fuente, default)` acepta las dos (sin distinguir
mayúsculas/espacios) y devuelve la canónica; vacía → `default`; cualquier otra → `ValueError`.

- `servicio/insumos.py::aplicar_cambios`: vacía → `COSTO INTERNO`; inválida → error de esa fila.
- `servicio/autoria.py::crear_insumo`: vacía → `COSTO INTERNO`; inválida → 400.
- `servicio/autoria.py::preview_importar_insumos` (y aplicar): vacía → 400 (como hoy); inválida → 400.
- CLI `db update-price --fuente`: default `COSTO INTERNO` (antes `ACTUALIZACION MANUAL`), inválida → mensaje y código 1.

`classify_price_source` no cambia. El seed desde el Excel no pasa por aquí y no cambia.

## Pruebas

Backend: fuente inválida rechazada en los tres caminos + default. Frontend: digitar precio →
`COSTO INTERNO`, y se puede volver a `PRECIO IDU`. Ajustar tests que usan etiquetas libres.
