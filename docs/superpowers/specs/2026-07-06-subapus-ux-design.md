# Diseño — UX de sub-APUs (editor, corrida, detalle)

> Fecha: 2026-07-06
> Estado: propuesto (decisiones tomadas con criterio mientras el usuario estaba ausente; pendiente de su revisión)
> Rama de trabajo: `feat/subapus-ux`, **apilada sobre `feat/subapus-import`** (que a su vez va sobre Fase 1).
> Trabajo LOCAL. Nada a prod sin OK explícito.

## Objetivo

Cerrar la UX de sub-APUs (el resto de la "Fase 2"): poder **crear/editar** vínculos sub-APU desde
el editor de APU, y **distinguirlos** visualmente donde se muestra una composición (corrida y detalle).

## Dependencia

Sobre `feat/subapus-import` (Fase 1 + detección en import): usa `ApuComponent.tipo`/`ref_shift`, el
costeo recursivo, `ComponenteIn` (que ya acepta `tipo`/`ref_shift`), y `editar_apu` que preserva marcas.

## Piezas y alcance

### Pieza 0 (backend, chica) — el detalle expone `tipo`/`ref_shift`
`apus_svc.detalle(alm, codigo, turno)` incluye por cada línea de `composicion` los campos `tipo` y
`ref_shift` (ya presentes en el componente costeado). El tipo del frontend `LineaComposicion` gana
`tipo: string` y `ref_shift: string`. Es lo que permite al editor pre-cargar filas sub-APU y
round-tripearlas.

### Pieza 1 (la principal) — editor: agregar/editar sub-APUs (`DialogoAgregarApu.tsx`)
- `FilaComp` gana `tipo: "insumo" | "apu"` y `ref_shift: string`.
- **Dos botones** en "Composición": **"+ Insumo"** (fila `tipo="insumo"` con `BuscadorInsumo`) y
  **"+ Sub-APU"** (fila `tipo="apu"` con `BuscadorApu`).
- Una fila `tipo="apu"` usa `BuscadorApu` (ya existe; devuelve `{codigo, turno, nombre, unidad, grupo}`):
  al elegir, fija `insumo_codigo=apu.codigo`, `insumo_nombre=apu.nombre`, `unidad=apu.unidad`,
  `ref_shift=apu.turno`, `tipo="apu"`. La fila muestra un chip **"APU"**.
- **Pre-carga al editar:** cada línea de `inicial.composicion` se mapea a una `FilaComp` con
  `tipo` (de `linea.tipo`, o `calidad_cruce === "apu"` como respaldo) y `ref_shift` (de `linea.ref_shift`).
- **Guardar:** `compValidos: ComponenteNuevo[]` incluye `tipo` y `ref_shift` en las filas sub-APU.
  `ComponenteNuevo` (tipo del frontend) gana `tipo?: string` y `ref_shift?: string`. El backend ya
  los acepta (`ComponenteIn`) y `_componentes_de` los usa.
- **Validación:** una fila sub-APU es válida con `insumo_codigo` (código del APU) + `rendimiento > 0`,
  igual que una de insumo (reusa `rendimientoValido`).

### Pieza 2 (chica) — corrida: distinguir la línea de sub-APU (`TablaItems.tsx`, `DetalleExpandido`)
En la tabla "Composición costeada", la columna "Cruce" ya recibe `calidad_cruce="apu"` para sub-APUs;
en vez del texto crudo, mostrar un **badge "APU"** (mismo estilo denso que el resto). El resto de la
línea (precio unitario = costo del sub-APU, costo) queda igual.
**Fuera de alcance (YAGNI):** drill-in para expandir la composición del sub-APU dentro de la corrida.

### Pieza 3 (chica) — detalle de APU en la biblioteca
Donde se muestre la composición de un APU de forma legible (si hay una vista de detalle además del
editor), marcar las líneas sub-APU con el mismo chip **"APU"**. Si el único lugar que muestra la
composición es el editor (pre-carga), la Pieza 1 ya lo cubre y esta pieza es un no-op; se confirma en
el plan al revisar `Apus.tsx`.

## Pruebas

- **Backend (pytest):** `apus_svc.detalle` devuelve `tipo`/`ref_shift` por línea (incluida una sub-APU).
- **Frontend (vitest):**
  - Editor: "+ Sub-APU" agrega una fila con `BuscadorApu`; al elegir un APU, la fila queda `tipo="apu"`
    con chip "APU"; guardar arma un `ComponenteNuevo` con `tipo="apu"` + `ref_shift`; pre-carga al
    editar reconstruye una fila sub-APU desde una `composicion` con `calidad_cruce="apu"`/`ref_shift`.
  - Corrida: una línea de composición con `calidad_cruce="apu"` muestra el badge "APU".
- **Verificación:** `python -m pytest tests/ -q`; desde `web/`: `npx tsc --noEmit`, `npx vitest run`,
  `npm run build`.

## Criterios de aceptación

1. Desde el editor de APU puedo agregar una fila **sub-APU** (buscador de APU) y guardarla; el
   componente queda `tipo='apu'` con `ref_shift`, y cotiza el sub-APU en vivo.
2. Al **editar** un APU que ya tiene sub-APUs, esas filas aparecen como sub-APU (chip "APU") y se
   conservan al guardar (no se aplanan a insumo).
3. En la corrida, las líneas de sub-APU se distinguen con un badge "APU".
4. Sin regresión: crear/editar un APU solo con insumos funciona igual; Invariante #1 intacta.
5. `pytest`, `tsc`, `vitest`, `build` verdes.

## Fuera de alcance (fases posteriores / YAGNI)
- Drill-in a la composición del sub-APU dentro de la corrida.
- Limpieza del catálogo de insumos (las ~1.078 copias aplanadas de APUs).
- Guard anti-ciclos en el editor (crear A→B→A): el motor ya lo maneja al costear (cae a histórico);
  un aviso proactivo en el editor es follow-up.
