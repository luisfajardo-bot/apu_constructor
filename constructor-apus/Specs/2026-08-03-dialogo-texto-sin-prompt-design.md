> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-08-03-dialogo-texto-sin-prompt-design.md`

# Diseño — un modal propio en lugar de `window.prompt()`

> Fecha: 2026-08-03
> Estado: aprobado en brainstorming
> Rama de trabajo: `feat/dialogo-texto-sin-prompt`

## El problema

Hallazgo 3 del smoke test de producción (2026-08-03): crear y renombrar una lista de
precios abre un `window.prompt()` nativo. No se puede estilizar, no es accesible, bloquea
el hilo principal de la página (le impidió automatizar el paso 2 a quien ejecutó el smoke
test) y es inconsistente con el resto de la app, que ya usa modales propios
(`components/ui/dialog.tsx`, usado por `DialogoAgregarApu`, `DialogoAgregarInsumo`,
`DialogoImportarInsumos`).

Al medir el alcance real aparecieron **11 diálogos nativos**, no 2:

```
prompt (8):  Insumos.tsx:111 crear lista · :130 renombrar lista
             CorridasInicio.tsx:64 crear carpeta/subcarpeta
             MisCorridas.tsx:116 crear carpeta · :128 renombrar carpeta · :151 renombrar corrida
             MisCorridas.tsx:170 mover corrida  ← "Escribe el número:"
             MisCorridas.tsx:194 mover carpeta  ← "Escribe el número:"
confirm (3): Insumos.tsx:99 cambio de lista con precios sin guardar ← guard de dinero
             MisCorridas.tsx:105 eliminar corrida · :140 eliminar carpeta
```

## Decisiones tomadas (brainstorming)

- **Alcance: los 6 `prompt` que piden un nombre.** Un componente reutilizable usado en los
  seis. Resultado coherente en toda la app.
- **Fuera de alcance, a propósito:**
  - Los **3 `window.confirm`**. Uno es el guard de los precios sin guardar al cambiar de
    lista (dinero) y está cubierto por `Insumos.dirty.test.tsx`, el test que además flaquea:
    no se toca en esta rama.
  - Los **2 `prompt` de "escribe el número"** (mover corrida / mover carpeta). No son un
    prompt de texto sino elegir de una lista: necesitan otro diseño (un `select`), y meterlos
    acá mezclaría dos problemas.
- **Con el nombre vacío, el botón queda HABILITADO y aparece un mensaje**, no deshabilitado.
  Rompe el patrón de los otros diálogos del repo (`DialogoAgregarApu` usa
  `disabled={!valido || guardando}`), y es deliberado: es la misma decisión que se tomó al
  arreglar el hallazgo 1 (`6fd5472`), donde un botón bloqueado sin explicación dejaba al
  usuario sin salida. Queda comentado en el código para que no parezca un descuido.

## Invariante #1 (recordatorio)

No toca la IA ni el dinero: es la capa de presentación de un cuadro de texto. No hay
payloads hacia el modelo, ni campos monetarios, ni cambios en `privacy.py` o `pricing.py`.
El único diálogo relacionado con dinero —el `confirm` de precios sin guardar— queda fuera
de alcance justamente por eso.

## Diseño

### Componente nuevo: `web/src/components/DialogoTexto.tsx`

```ts
type Props = {
  open: boolean;
  onOpenChange: (v: boolean) => void;
  titulo: string;              // "Nueva lista de precios"
  etiqueta?: string;           // "Nombre" por defecto
  valorInicial?: string;       // para renombrar
  ayuda?: string;              // texto opcional bajo el input
  textoConfirmar?: string;     // "Crear" / "Guardar"; "Guardar" por defecto
  onConfirmar: (valor: string) => void | Promise<void>;
};
```

Comportamiento:
- Foco en el input al abrir.
- **Enter** confirma (el input vive en un `<form onSubmit>`), **Esc** cancela (lo da Radix).
- Botón de confirmar **siempre habilitado**. Con el valor vacío (tras `trim()`), muestra
  *"Escribí un nombre"* bajo el input y no llama a `onConfirmar`.
- Al confirmar sin error, el diálogo cierra. **Si `onConfirmar` lanza, el diálogo QUEDA
  ABIERTO** con lo escrito, para poder corregir. Es una mejora sobre el `prompt`, que
  cerraba y perdía el texto: hoy, un nombre de lista duplicado (400 del backend) obliga a
  reescribirlo desde cero.
- El llamador sigue mostrando sus propios `toast.error`: el componente no inventa mensajes
  de dominio.

### Los 6 usos

| Archivo | Handler | Título | Confirmar |
|---|---|---|---|
| `Insumos.tsx` | `crearListaNueva` | Nueva lista de precios | Crear |
| `Insumos.tsx` | `renombrarListaActual` | Renombrar lista de precios | Guardar |
| `CorridasInicio.tsx` | `handleCrearCarpeta` | Nueva carpeta / Nueva subcarpeta | Crear |
| `MisCorridas.tsx` | `handleNuevaCarpeta` | Nueva carpeta | Crear |
| `MisCorridas.tsx` | `handleRenombrar` | Renombrar carpeta | Guardar |
| `MisCorridas.tsx` | `handleRenombrarCorrida` | Renombrar corrida | Guardar |

La conversión es de **imperativo a declarativo**: hoy es
`const nombre = window.prompt(...); if (!nombre?.trim()) return; await api(...)`, y pasa a
ser estado (qué diálogo está abierto y sobre qué entidad) + el modal renderizado + el
`onConfirmar` que hace la llamada. Se preserva **toda** la lógica actual de cada handler,
incluida la que no es obvia:

- `CorridasInicio.handleCrearCarpeta`: el título depende de si hay una carpeta de nivel 1
  seleccionada (carpeta vs subcarpeta), y tras crear **auto-selecciona** la nueva.
- `MisCorridas.handleRenombrar` y `handleRenombrarCorrida`: si el nombre nuevo es igual al
  actual, **no llaman a la API** (`nuevo.trim() === carpeta.nombre → return`).
- `MisCorridas.handleRenombrarCorrida`: muestra `toast.success` con el nombre nuevo.
- Los `e.stopPropagation()` de los handlers de fila se conservan (la fila es clickeable).

`MisCorridas` tiene 3 usos, así que necesita un estado que diga cuál está abierto y sobre
qué entidad; un solo `useState` con una unión discriminada, no tres banderas.

## Pruebas

- **Nuevo** `web/src/components/DialogoTexto.test.tsx`: foco al abrir, Enter confirma,
  vacío → mensaje y `onConfirmar` no se llama, `valorInicial` precargado al renombrar, y
  que si `onConfirmar` lanza el diálogo sigue abierto.
- **A ajustar**: `Insumos.listas.test.tsx` y `MisCorridas.test.tsx` stubbean `window.prompt`
  y pasan a interactuar con el modal (escribir en el input, clic en confirmar).
- **Intacto**: `Insumos.dirty.test.tsx` — solo stubbea `window.confirm`, que sigue nativo.
- Al terminar: los 4 pasos de `.github/workflows/ci.yml`, y 3 corridas de la suite del
  frontend (por el flake tolerado de `Insumos.dirty`).

## Qué NO cambia

- Backend: nada. Ni un endpoint, ni un esquema.
- Los 3 `window.confirm` y los 2 `prompt` de "mover".
- Ninguna llamada a la API cambia de forma: mismos endpoints, mismos payloads.
