# Diseño — Detección de sub-APUs en el import de APUs

> Fecha: 2026-07-06
> Estado: aprobado por el usuario (pendiente de plan de implementación)
> Rama de trabajo: `feat/subapus-import`, **apilada sobre `feat/apus-compuestos`** (Fase 1, aún sin mergear).
> Trabajo LOCAL. Nada a prod sin OK explícito.

## Objetivo

Al importar APUs desde Excel (hoja `APUS`), que la **vista previa** detecte y **muestre** qué
componentes son sub-APUs, y que al **aplicar** el import se marquen automáticamente (`tipo='apu'`),
sin tener que correr `marcar-subapus` aparte. La detección incluye sub-APUs que vienen **en el mismo
lote** de import, no solo los que ya están en la biblioteca.

## Dependencia

Se apoya en la **Fase 1** (APUs compuestos): usa `ApuComponent.tipo`/`ref_shift`, el costeo recursivo
y la lógica de marcado (`subapus.py`). Por eso la rama va apilada sobre `feat/apus-compuestos`.

## Alcance

- **Flujo de import de APUs** (Excel hoja `APUS`): `preview_importar_apus` y `aplicar_importar_apus`
  (`apu_tool/servicio/autoria.py`), el endpoint de preview, los tipos del API y el diálogo
  `web/src/components/autoria/DialogoImportarApus.tsx`.
- El comando CLI `marcar-subapus` **se mantiene** para backfill de lo ya importado/histórico.
- **Fuera de alcance (YAGNI):** corregir a mano un falso positivo dentro del import (eso lo cubrirá el
  editor de la Fase 2); detección de huérfanos; el buscador de sub-APU en el editor manual.

## Detección (biblioteca ∪ lote)

Un componente de un APU del lote es **sub-APU** si su `insumo_codigo` coincide con el `codigo` de un
APU que:
- ya existe en la biblioteca, **o**
- viene en el **mismo lote** de import.

`ref_shift` del sub-APU (misma regla que `marcar_subapus`, pero sobre biblioteca ∪ lote):
1. el turno del APU padre si el sub-APU existe en ese turno;
2. si no, `DIURNO`;
3. si no, el único turno en que exista ese código.

Cada vínculo detectado lleva su **origen**: `"lote"` (el sub-APU viene en el import) o `"biblioteca"`
(ya existía).

**Nota de ambigüedad:** como el código solo no distingue insumo de APU (1.078 códigos son ambos),
la detección por código puede marcar un material cuyo código coincida con el de un APU. Por eso la
vista previa **lista los vínculos** para que el usuario los revise antes de confirmar. La corrección
fina (marcar a mano) es de la Fase 2.

## Diseño

### Lógica compartida (`apu_tool/servicio/subapus.py`)

Un helper reutilizable por preview y apply, para no duplicar la detección:
- `mapa_codigos_apu(alm, apus_extra=()) -> dict[str, set[str]]`: `codigo -> {turnos}` uniendo la
  biblioteca (`alm.apus.apu_index()`) con los APUs `apus_extra` del lote.
- Reutiliza `_ref_shift(sub_cod, parent_shift, mapa)` (ya existe).
- `detectar_subapus_lote(alm, apus_lote, comps_por) -> list[Vinculo]`: recorre los componentes del
  lote y devuelve los vínculos (`apu_codigo`, `apu_turno`, `sub_codigo`, `sub_turno=ref_shift`,
  `sub_nombre`, `origen`).

### Backend — preview (`preview_importar_apus`)

Además de `crear` / `ya_existe`, la respuesta gana:
- por cada APU en `crear`: `n_subapus` (cuántos de sus componentes son sub-APUs);
- a nivel raíz: `subapus`: lista de vínculos detectados (para la sección de la UI), cada uno
  `{apu_codigo, apu_turno, sub_codigo, sub_turno, sub_nombre, origen}`.

### Backend — apply (`aplicar_importar_apus`)

Antes de insertar cada APU, marca sus componentes sub-APU: para cada componente cuyo código esté en
`mapa_codigos_apu(alm, apus_lote)`, se reemplaza por `dataclasses.replace(c, tipo="apu",
ref_shift=<regla>)`. Luego `crear_apu` inserta la composición ya marcada. La auditoría existente de
`apu.crear` refleja `n_componentes`; se añade `n_subapus` al `despues`/contexto para dejar rastro.
Devuelve `creados`, `errores` y `subapus_marcados` (total).

### Frontend (`DialogoImportarApus.tsx` + tipos del API)

- El tipo del preview (`ImportApusPreview`) gana `subapus: VinculoSubApu[]` y cada fila de `crear`
  gana `n_subapus?: number`.
- La vista previa muestra una sección nueva **"Sub-APUs detectados (N)"** que lista los vínculos:
  `APU X → usa Y (turno) [en el lote | en biblioteca]`, con un aviso arriba del total. Estética densa,
  como las tablas existentes del diálogo.
- El botón "Crear" aplica igual que hoy (el marcado ocurre en el backend).

## Pruebas (pytest + vitest)

- **Backend (`tests/test_servicio_autoria.py` o nuevo `tests/test_subapus_import.py`):**
  - preview detecta un sub-APU que **ya está en biblioteca** y uno que **viene en el lote**; el que no
    es APU queda como insumo (no aparece en `subapus`).
  - `ref_shift` correcto (turno del padre / DIURNO / único), incluyendo un sub-APU que solo existe en
    el lote.
  - apply marca `tipo='apu'`/`ref_shift` en los componentes detectados y los deja costeando recursivo;
    no-regresión del import normal (APU solo con insumos → todo `insumo`).
- **Frontend (`DialogoImportarApus.test.tsx`, si existe patrón; si no, un test de render):** con un
  preview que trae `subapus`, la sección "Sub-APUs detectados" los lista.
- **Verificación:** `python -m pytest tests/ -q`; desde `web/`: `npx tsc --noEmit`, `npx vitest run`,
  `npm run build`.

## Criterios de aceptación

1. La vista previa del import lista los sub-APUs detectados (con origen lote/biblioteca) **antes** de
   confirmar.
2. Al confirmar, esos componentes quedan marcados `tipo='apu'` con el turno correcto y cotizan su
   sub-APU en vivo — **sin** correr `marcar-subapus` aparte.
3. Un import de APUs solo con insumos se comporta igual que hoy (sin regresión).
4. `marcar-subapus` (CLI) sigue disponible para backfill.
5. Invariante #1 intacta; `pytest`, `tsc`, `vitest`, `build` verdes.
