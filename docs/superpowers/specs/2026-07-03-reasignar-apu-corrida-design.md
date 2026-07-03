# Diseño — Reasignar el APU de un ítem de corrida (buscador en la biblioteca)

> Fecha: 2026-07-03
> Estado: propuesto (pendiente de revisión del usuario)
> Antecede: la corrida ya permite confirmar/elegir el APU de un ítem entre los
> **candidatos del matcher**; este spec agrega poder cambiarlo a **cualquier** APU de
> la biblioteca, en **cualquier** ítem, con un **buscador autocompletar**.
> Rama de trabajo: `feat/reasignar-apu-corrida` (parte del tip de `master`).

## Objetivo

Cuando el programa asocia un APU equivocado a una actividad de la corrida, hoy solo se
puede corregir si el ítem quedó "por revisar" (`review`/`new`) y **solo eligiendo entre los
candidatos que propuso el matcher**. No hay forma de: (a) corregir un ítem que el programa dio
por bueno (`matched`), ni (b) escribir directamente un código de APU (p. ej. `33333`) que el
usuario sabe que corresponde pero que el matcher no ofreció.

Este proyecto agrega, en el detalle de cada ítem de la corrida, un **buscador de APU**
(autocompletar contra toda la biblioteca, por código o nombre — como el buscador de insumos)
para **reasignar el APU** de **cualquier** ítem. Al elegir uno, el ítem se recostea con la
composición vigente de ese APU.

## Alcance y hallazgo clave

**Es un proyecto solo-frontend.** El backend ya soporta todo lo necesario y está probado:

- `POST /api/corridas/{cid}/items/{seq}/confirmar` (body `ConfirmarIn {apu_codigo, shift?}`,
  rol `consulta`) reasigna el ítem a **cualquier** `apu_codigo`+`shift` vía
  `Assembler.reassemble_with_choice`, que lee la composición actual de ese APU de la biblioteca
  y la guarda como la nueva foto del ítem. **No gatea por estado del ítem.**
- El cliente web ya expone `confirmar(id, seq, apu_codigo, shift?)` en `web/src/api/corridas.ts`.
- La búsqueda de APUs ya existe: `GET /api/apus?q=` → `web/src/api/autoria.ts::listarApus({q})`,
  que devuelve `ApuResumen { codigo, turno, nombre, unidad, grupo, n_componentes }`.

El hueco es **de UI**: `web/src/components/corrida/TablaItems.tsx` hoy muestra la tabla de
candidatos y el botón de confirmar **solo** cuando el ítem es `review`/`new`, y solo ofrece los
candidatos precalculados por el matcher.

## Decisiones de alcance

| Decisión | Elección |
|----------|----------|
| Dónde se reasigna | En el **panel expandido** de cada ítem (donde ya se ven candidatos y composición). Enfoque A. |
| En qué ítems | En **TODOS** (incluidos `matched` confiados y `new`). |
| Cómo se elige | **Buscador autocompletar** contra la biblioteca (código o nombre) + los **candidatos del matcher** como quick-pick cuando existan. |
| Turno al reasignar | El buscador devuelve entradas concretas `(código, turno)`; el ítem **adopta ese `(código, turno)`**. Los candidatos del matcher confirman con el **turno del ítem** (como hoy). |
| Rol | El del endpoint actual (`consulta`); **no se toca el backend**. |
| Auditoría | **Sin auditoría** (igual que el `confirmar` actual, que no audita). |
| Recosteo | Automático: `confirmar` devuelve la `CorridaDetalle` recosteada; la vista se refresca (comportamiento actual). |

**Fuera de alcance:** cambios de backend (endpoint, rol, auditoría de reasignación); re-hacer
el matching automático; editar la **composición** de un ítem/APU desde la corrida (eso es del
Spec de estados de corrida); interacción con "congelar" una corrida (Spec de estados de corrida).

## Arquitectura y estructura de archivos

Solo frontend. El único archivo compartido que se edita es `TablaItems.tsx`; el resto es un
componente nuevo aislado. No se toca el backend ni los archivos del trabajo reciente de
plantillas de licitación (`corridas.ts` solo se **lee**, no se modifica).

```
web/src/components/corrida/BuscadorApu.tsx   [nuevo] combobox autocompletar de APU (patrón de BuscadorInsumo)
web/src/components/corrida/TablaItems.tsx    reasignar en TODOS los ítems; integrar BuscadorApu; candidatos como quick-pick;
                                             handleConfirmar acepta shift opcional
```

**Invariante #1 (la IA nunca ve dinero):** intacta. Nada de esto toca la IA; es UI sobre
endpoints existentes que ya viven del lado del equipo.

## Componente `BuscadorApu` (`web/src/components/corrida/BuscadorApu.tsx`)

Clonado del `BuscadorInsumo` que ya existe en `web/src/components/autoria/DialogoAgregarApu.tsx`,
adaptado a APUs:

- **Estado interno:** `q` (texto), `resultados: ApuResumen[]`, `abierto`, `buscando`; cierre al
  clic-afuera (listener `mousedown` con `ref`).
- **Búsqueda debounced (~250 ms):** si `q.trim()` no está vacío, llama
  `listarApus({ q: q.trim(), limit: 15 })` y muestra `res.items`; si vacío, limpia resultados.
- **Render de cada resultado:** `código · turno · nombre` (mono para código; turno como etiqueta).
- **Props:** `onElegir(apu: ApuResumen) => void` y `placeholder?: string`. Al hacer clic en un
  resultado: `onElegir(apu)`, limpia `q`, cierra el dropdown.
- **Sin resultados** (con `q` no vacío y no buscando): muestra "Sin resultados".

Consume `listarApus` de `@/api/autoria` y el tipo `ApuResumen` de `@/lib/tipos` (ya existentes).

## Cambios en `TablaItems.tsx`

Dentro de `DetalleExpandido` (el panel que se abre al expandir una fila):

1. **`handleConfirmar` acepta un `shift` opcional:** firma `handleConfirmar(seq, apuCodigo, shift?)`
   → `confirmar(corridaId, seq, apuCodigo, shift)`. El resto del manejo (estado `confirmando`,
   `errorConfirm[seq]`, colapsar la fila y `onConfirmado(corridaActualizada)`) queda igual.
2. **Bloque "Cambiar APU" para TODOS los ítems:** una sección nueva (no condicionada a
   `esRevisable`) con el `BuscadorApu`. Al elegir un APU:
   `handleConfirmar(seq, apu.codigo, apu.turno)` → el ítem adopta ese `(código, turno)`.
   Deshabilitado mientras `confirmando !== null`.
3. **Candidatos del matcher como quick-pick:** la tabla de candidatos se muestra cuando
   `detalle.candidatos.length > 0` (ya no restringida a `esRevisable`). Cada botón "Elegir"
   sigue llamando `handleConfirmar(seq, c.apu_codigo)` (sin `shift` → turno del ítem), como hoy.
4. **"Confirmar APU actual":** se conserva **solo** para `review`/`new` (confirmar sin cambiar),
   sin cambios.
5. **Recosteo/refresco:** sin lógica nueva — `confirmar` devuelve la `CorridaDetalle` recosteada,
   `onConfirmado` refresca la vista de la corrida y la fila se colapsa mostrando el APU nuevo y
   los totales actualizados.

Estética: densa, table-first, sin cards; reutiliza los estilos/inputs existentes del archivo y
del `BuscadorInsumo`.

## Errores y casos límite

- **Búsqueda sin resultados:** dropdown muestra "Sin resultados" (patrón del `BuscadorInsumo`).
- **Reasignar al mismo APU:** permitido (idempotente); confirma y recostea igual.
- **Turno distinto al del ítem:** intencional — el usuario elige la entrada `(código, turno)` y el
  ítem adopta ese turno. No puede elegir un `(código, turno)` inexistente (el buscador solo
  devuelve entradas reales de la biblioteca).
- **Error de red/4xx al confirmar:** ya cubierto — `handleConfirmar` captura el error y lo muestra
  en `errorConfirm[seq]`; la fila no se colapsa; se puede reintentar.
- **Ítem "nuevo" (sin APU):** ahora también reasignable vía el buscador.
- **Corrida finalizada:** se conserva el comportamiento actual (el endpoint confirma sin importar
  estado). La interacción con "congelar" es del Spec de estados de corrida (fuera de alcance).

## Pruebas

**Frontend (Vitest, sin red — mocks de módulos, como los tests existentes):**
- **`BuscadorApu`**: al teclear llama `listarApus` con el `q` (debounced) y renderiza los
  resultados como `código·turno·nombre`; clic en un resultado dispara `onElegir` con el
  `ApuResumen` correcto. Mock de `@/api/autoria` (y de `@/lib/supabase` si el import lo requiere,
  igual que el resto de tests del repo).
- **`TablaItems`**: en un ítem **matched** (no revisable), el bloque "Cambiar APU" está presente;
  elegir un APU llama `confirmar(corridaId, seq, codigo, turno)` con el turno elegido (mock de
  `@/api/corridas`). Se preserva el flujo actual de candidatos/confirmar.

**Verificación:** desde `web/` → `npx tsc --noEmit` (limpio), `npx vitest run` (verde, sin
regresiones), `npm run build` (OK). **Backend sin cambios** → su suite (`python -m pytest tests/ -q`)
no se toca y sigue verde. Smoke manual opcional: reasignar un APU en un ítem `matched` y ver el
recosteo.

## Criterios de aceptación

1. Al expandir **cualquier** ítem (incluido uno `matched` con confianza) aparece "Cambiar APU"
   con un buscador; teclear código o nombre lista APUs de la biblioteca.
2. Elegir un APU reasigna el ítem a ese `(código, turno)`, lo recostea y refleja el cambio (APU
   nuevo + totales) sin recargar la página.
3. Los candidatos del matcher siguen disponibles como quick-pick cuando existan.
4. Un error al confirmar se muestra y permite reintentar; la búsqueda sin resultados avisa.
5. `tsc` / `vitest` / `build` verdes; backend intacto; Invariante #1 intacta.
