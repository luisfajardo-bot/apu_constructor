# Diseño — Columna "Ítem" (código de licitación) en la tabla de la corrida

> Fecha: 2026-07-05
> Estado: propuesto (pendiente de revisión del usuario)
> Rama de trabajo: `feat/columna-item-corrida` (parte del tip de `master`).

## Objetivo

Al revisar una corrida, poder ver **con qué código entró cada actividad en la licitación** y
**qué APU le asignó el programa**, lado a lado, para comparar de un vistazo (entró como `X`, se
le asignó `Y`) y detectar asignaciones dudosas.

## Hallazgo / alcance

Los dos datos **ya viajan** en cada fila de la corrida — no hay que tocar el backend:
- **Código de licitación** = `LicitacionItem.item` (la columna "ítem/número/código" de la lista de
  entrada; en `models.py`: *"número/código de ítem en la licitación"*). Ya expuesto como
  `ItemCuadro.item` en la respuesta de `vista_corrida` (`_vista_item` → `"item": ens.item.item`).
- **APU asignado** = `apu_codigo`, ya visible en la columna "APU".

El hueco es solo de **UI**: la tabla de la corrida (`web/src/components/corrida/TablaItems.tsx`)
hoy arranca en "Descripción" y no muestra el código de licitación.

**Es un proyecto solo-frontend.** No se toca `corridas.py`, el Excel del cuadro (`report.py`), ni
ningún archivo de backend.

## Diseño

Único archivo: `web/src/components/corrida/TablaItems.tsx`.

- Agregar una columna **"Ítem"** que renderiza `it.item` en `font-mono` (como los demás códigos),
  ubicada **inmediatamente antes** de la columna **"APU"**. Orden resultante:
  chevron · Descripción · Und · Cantidad · **Ítem** · APU · Estado · Contractual · Costo · Margen · %.
- Actualizar `TOTAL_COLS` (10 → 11) para que la fila expandida (que usa `colSpan={TOTAL_COLS}`) siga
  ocupando el ancho completo.
- Reutiliza los estilos existentes (`text-xs`, `font-mono`); estética densa, sin cambios de layout.

**Fuera de alcance:** mostrarlo en el detalle expandido del ítem; incluirlo en el Excel del cuadro
(`report.py`). Ambos son agregados triviales para un follow-up si se piden.

## Pruebas

- **Vitest** (`web/src/components/corrida/TablaItems.test.tsx`): con un ítem cuyo `item` es un
  código conocido (p. ej. `"1.1"`), afirmar que ese código se renderiza en la tabla (además del
  `apu_codigo`), demostrando que ambos códigos son visibles.
- **Verificación:** desde `web/` → `npx tsc --noEmit`, `npx vitest run`, `npm run build`. Backend
  intacto (su suite no se toca).

## Criterios de aceptación

1. Al abrir una corrida, cada fila muestra el **código de licitación** (`Ítem`) junto a la columna
   **APU**; se compara de un vistazo con qué entró y qué se le asignó.
2. La fila expandida sigue ocupando el ancho completo (colspan actualizado).
3. `tsc` / `vitest` / `build` verdes; backend sin cambios; Invariante #1 intacta (nada toca la IA).
