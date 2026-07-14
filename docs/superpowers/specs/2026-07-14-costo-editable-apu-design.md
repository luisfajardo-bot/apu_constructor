# Costo editable en el armador de APUs — diseño

**Fecha:** 2026-07-14
**Estado:** aprobado el diseño; pendiente plan de implementación

## Objetivo

En la tabla de composición del diálogo de APUs, permitir ajustar el **costo** de un
componente y que el **rendimiento** se actualice solo, y viceversa. Hoy el diálogo
solo deja editar el rendimiento; el usuario quiere trabajar también "por costo"
cuando conoce el costo objetivo de una partida.

## Relación de dominio

Cada componente liga tres cantidades con una sola fórmula:

```
costo = rendimiento × precio
```

- **precio** — precio vigente del insumo (catálogo), o el costo unitario del sub-APU.
  Vive **separado** del APU. En esta ventana es **ancla de solo lectura**.
- **rendimiento** — lo único que el APU persiste (su estructura).
- **costo** — derivado; **no se guarda**. Se calcula al costear (`pricing.py:89`,
  `costo = comp.rendimiento * precio`).

## Modelo de edición (Opción A — decidido)

El precio es un dato dado y el rendimiento es lo único persistible. Por eso:

- **Editar rendimiento** → el costo mostrado se recalcula (`costo = rend × precio`).
- **Editar costo a X** → se despeja `rendimiento = X ÷ precio` y **se guarda el
  rendimiento**. El valor "X" nunca se persiste.

Consecuencia explícita y aceptada: fijar el costo **no congela el costo**, congela el
rendimiento *al precio de hoy*. Si mañana cambia el precio vigente del insumo, el
costo de ese componente cambia. Esto es consistente con el invariante del sistema:
"actualizar el precio no toca los APUs, que toman el precio vigente al costear".

Descartada la Opción B (guardar un override de costo clavado): rompería ese
invariante y exigiría cambios de esquema y del motor de costeo.

## Alcance

**Incluye:**
- `web/src/components/autoria/DialogoAgregarApu.tsx`, en modos **crear** y **editar**.
- La tabla de composición pasa de columnas *Insumo · Und · Rendimiento* a
  *Insumo · Und · **Rendimiento** · **Precio** (solo lectura) · **Costo***, con
  Rendimiento y Costo como campos editables enlazados.
- Costo unitario **total** del APU al pie del diálogo, recalculándose en vivo.

**No cambia:**
- El backend (ni lectura ni escritura). El payload de guardado sigue enviando solo
  `rendimiento` por componente (`ComponenteNuevo`).
- La vista desplegable de solo lectura `DetalleApu` en `Apus.tsx` (ya muestra
  Precio y Costo).
- Nada relacionado con la IA. Esto es dinero de cara al usuario (como el cuadro y
  como `DetalleApu`), **no** un payload hacia la IA → invariante #1 intacto.
- El precio del insumo no se edita aquí; eso sigue en la página de Insumos
  (efecto global + auditoría).

## Fuente del "precio" (ancla) por caso — sin tocar backend

| Caso | Fuente del precio |
|------|-------------------|
| Fila existente (modo editar) | `LineaComposicion.precio_unitario` del detalle ya cargado |
| Insumo nuevo (buscador) | `Insumo.precio` de `listarInsumos` (`BuscadorInsumo.onElegir`) |
| Sub-APU nuevo (buscador) | `ApuResumen.costo_unitario` de `listarApus` (`BuscadorApu.onElegir`) |

`FilaComp` gana un campo `precio: number` (0 si desconocido), poblado en esos tres
puntos. El resto del estado de la fila no cambia.

Nota de exactitud: para filas existentes, `precio_unitario` es el precio que el motor
de costeo resolvió (incluye la lógica de cruce), así que es el valor fiel. Para filas
nuevas se usa el precio del buscador (precio vigente del catálogo); puede diferir
levemente de la resolución por cruce cuando el nombre es ambiguo, pero el costo se
re-deriva de todos modos la próxima vez que se abre el APU. Aceptable para v1.

## Casos borde

- **Precio ≤ 0** (insumo sin precio, material del cliente, huérfano, sub-APU vacío):
  no se puede despejar el rendimiento (`X ÷ 0`). La casilla **Costo** queda
  deshabilitada con una nota ("sin precio — ajusta el rendimiento"); el rendimiento
  sigue editable como hoy. Coincide con la regla "nada en $0".
- **Precisión:** el rendimiento despejado puede tener muchos decimales. Se guarda con
  precisión completa (número tal cual) y se muestra el **costo recalculado** para que
  el usuario vea el valor real resultante, que puede diferir por redondeo de centavos.
  La celda de rendimiento se muestra con `maximumFractionDigits` razonable (p. ej. 6),
  pero el valor almacenado no se trunca artificialmente.
- **Sub-APUs:** funcionan igual que un insumo; el ancla es `costo_unitario` del sub-APU.

## Validación y guardado

- Se conserva la validación existente: un componente es válido con insumo elegido y
  `rendimiento > 0` (`validacionApu.ts::rendimientoValido`). El costo es un campo de
  conveniencia que escribe el rendimiento; no añade una regla de bloqueo nueva.
- El botón Guardar sigue habilitado con la misma condición (`compValidos.length > 0`
  y sin rendimientos inválidos).
- Payload sin cambios: `componenteDeFila` sigue produciendo `{ insumo_codigo,
  rendimiento, ... }`.

## Diseño de componentes (aislamiento)

Lógica pura, aislada y testeable sin montar la UI (junto a `validacionApu.ts`):

- `costoDeFila(rendimiento: string, precio: number): number`
  — devuelve `Number(rendimiento) * precio` (0 si rendimiento no es número válido).
- `rendimientoDesdeCosto(costo: string, precio: number): number | null`
  — devuelve `Number(costo) / precio`, o `null` si `precio <= 0` o costo inválido
  (señal de "no se puede despejar").
- `costoTotalApu(filas): number` — suma de `costoDeFila` sobre las filas válidas,
  para el total en vivo del pie.

La UI (`DialogoAgregarApu`) consume estos helpers; `setFila` sigue siendo el único
punto que muta una fila. Editar costo llama a `rendimientoDesdeCosto` y hace
`setFila(uid, { rendimiento })`.

## Pruebas

- **Unitarias (helpers):** `costoDeFila`, `rendimientoDesdeCosto`, `costoTotalApu`
  con casos: precio > 0 normal, precio = 0 (retorna null / costo 0), rendimiento o
  costo no numérico, redondeo de centavos, sub-APU.
- **UI (`DialogoAgregarApu`):** editar rendimiento actualiza el costo mostrado;
  editar costo actualiza el rendimiento; con precio 0 la casilla de costo está
  deshabilitada y el rendimiento sigue editable; el total del pie refleja los cambios;
  guardar envía el rendimiento despejado.

## Fuera de alcance (YAGNI)

- Congelar el costo (Opción B).
- Editar el precio del insumo desde esta ventana.
- Cambiar la vista de solo lectura o el backend.
