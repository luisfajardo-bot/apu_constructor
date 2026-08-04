# Diseño — Duplicar un APU a partir de otro (variantes: MD12 → MD13)

> Fecha: 2026-08-04
> Estado: propuesto (pendiente de revisión del usuario)
> Antecede: `2026-07-02-alta-de-apus-design.md` (alta/edición/borrado de APUs desde la web),
> del que reusa endpoint, diálogo y validaciones.
> Rama de trabajo: `feat/duplicar-apu` (en el mismo directorio, sin worktree).

## Objetivo

Armar un APU nuevo que es *casi* otro que ya existe. Caso real: el APU de una mezcla
**MD12** sirve tal cual para la **MD13** cambiando un solo insumo. Hoy eso obliga a
recrear la composición completa a mano desde "Agregar APU", o a editar el original y
perderlo.

La función es **duplicar**: abrir el diálogo de alta precargado con todo el APU de
origen, cambiar lo que haga falta (típicamente un insumo) y guardar como APU nuevo con
su propia identidad.

## Decisiones de alcance

| Decisión | Elección |
|----------|----------|
| Identidad de la copia | `(código, turno)` nuevo. El código se **sugiere derivado** (`3454` → `3454-2`) y es editable. |
| Obligación de cambiar | El botón de guardar está bloqueado hasta que el **nombre** sea distinto al del origen. Código y turno tampoco pueden ser los del origen. |
| Turno | Hereda el del origen y es **editable** (sirve para armar el gemelo nocturno). |
| Precarga | Cabecera + composición **completa**, incluidas las filas de sub-APU con su marca. |
| Cambiar un insumo | Con el botón "cambiar" que ya tiene cada fila del editor de composición. Nada nuevo. |
| Entradas | Página **APUs** (fila expandida) **y** detalle de ítem de **corrida** (duplicar + reasignar en un paso). |
| De a uno | Una copia por vez. Sin lote. |
| Precio histórico de respaldo | La copia **hereda** `precio_unitario_hist` de los componentes que no cambiaron. |
| Backend | Sin ruta nueva: `POST /api/apus` gana un campo opcional `duplicado_de`. |
| Capa de datos | **No se toca** (`repositorio.py`, esquemas SQL y ambos backends quedan igual). Sin migración. |
| Rol | `editor`, igual que "Editar APU". |

**Fuera de alcance:** duplicar en lote (varias variantes de una vez); duplicar desde el
cuadro Excel; cambiar la identidad de un APU ya creado (eso sigue siendo borrar + crear);
y arreglar la pérdida de `precio_unitario_hist` en `editar_apu` (ver *Deuda conocida*).

## Por qué el `precio_unitario_hist` importa

Cada componente guarda el precio histórico embebido como **respaldo**. `pricing.py`
(`_cost_insumo`, líneas 117-133) lo usa cuando el insumo es huérfano o ambiguo en el
catálogo, o cuando existe pero no tiene tarifa en Principal (`sin_precio_catalogo`).

`autoria.py::_componentes_de` —la que arma componentes desde el diálogo web— pone
**`precio_unitario_hist=0.0` siempre**. Si la copia viajara de vuelta por el diálogo sin
más, esas líneas quedarían en **$0 con alerta** en la copia mientras el original sí
costea el histórico: la copia costaría menos que el original sin que eso sea decisión de
nadie, contra la regla de negocio "nada en $0".

Por eso la copia **hereda** el histórico de los componentes que siguen siendo los mismos.
El insumo que sustituiste entra como cualquier alta manual (hist 0.0), que es lo correcto:
de ese componente no hay histórico que heredar.

## Backend

### `apu_tool/servicio/esquemas.py`

```python
class DuplicadoDeIn(BaseModel):
    codigo: str
    turno: str


class ApuNuevoIn(BaseModel):
    ...                                          # sin cambios
    duplicado_de: Optional[DuplicadoDeIn] = None # None = alta normal
```

Nadie más cambia: `ComponenteIn` ya lleva `tipo`/`ref_shift`, y `ApuEditIn` no se toca.

### `apu_tool/servicio/autoria.py`

`_componentes_de(...)` gana un parámetro **opcional** `hist: dict[str, float] | None`:
por cada componente, si su `insumo_codigo` está en `hist`, usa ese valor como
`precio_unitario_hist`; si no, `0.0` (comportamiento actual). Las llamadas existentes
(`crear_apu` sin duplicado, `editar_apu`) no cambian de conducta.

`crear_apu(alm, datos, actor)` — cuando `datos["duplicado_de"]` viene:

1. Lee el origen: `alm.apus.get_apu(cod_o, turno_o)`.
   No existe → `ValueError("El APU de origen ya no existe.")` → **400**.
2. `(codigo, turno) == (cod_o, turno_o)` → `ValueError` → **400**
   ("La copia necesita un código o un turno distinto al del APU de origen.").
3. `normalizar(nombre) == normalizar(origen.nombre)` → `ValueError` → **400**
   ("El nombre debe ser distinto al del APU de origen."). Usa
   `nucleo.texto.normalizar`, el mismo criterio que el resto del proyecto.
4. Lee `alm.apus.get_components(cod_o, turno_o)` y arma dos mapas por código de insumo:
   - `previos: {codigo: (tipo, ref_shift)}` — **ya existe** esta mecánica en
     `editar_apu`; se extrae a un helper para no duplicarla. Conserva las marcas de
     sub-APU cuando el componente entrante no trae `tipo` explícito.
   - `hist: {codigo: precio_unitario_hist}`.
   Si el origen repite un código, gana la primera aparición, salvo que otra sea de
   `tipo == "apu"` (misma regla que `editar_apu` ya aplica para `previos`).
5. Llama a `_componentes_de(..., previos=previos, hist=hist)` y sigue el camino normal:
   `alm.apus.crear_apu(...)`, que ya lanza `ValueError` si `(codigo, turno)` existe →
   **409** por el manejo de errores que ya tiene la ruta.
6. Auditoría: misma acción `apu.crear`, con
   `contexto={"origen": "duplicado", "de": cod_o, "de_turno": turno_o}`. No se inventa
   una acción nueva, así la pantalla de auditoría no necesita aprender nada, y el
   contexto deja la trazabilidad de dónde salió la copia.

Cuando `duplicado_de` es `None`, `crear_apu` se comporta **exactamente** como hoy.

### `apu_tool/servicio/corridas.py`

`detalle_item(...)` agrega **`"apu_turno": row.shift`** al dict que devuelve. El dato ya
existe en la fila de la corrida; hoy simplemente no viaja al frontend, y la entrada B lo
necesita para leer el APU de origen de la biblioteca.

### API

Sin rutas nuevas.

| Método + ruta | Cambio |
|---|---|
| `POST /api/apus` | acepta `duplicado_de: {codigo, turno}` opcional; `400` en las tres validaciones nuevas, `409` si `(código,turno)` ya existe (ya estaba) |
| `GET /api/corridas/{id}/items/{seq}` | la respuesta agrega `apu_turno` |

## Frontend

### `web/src/lib/duplicarApu.ts` [nuevo]

Helpers puros, testeables sin montar UI (patrón de `costoApu.ts` / `validacionApu.ts`):

- `codigoSugerido(codigoOrigen: string, turno: string, ocupados: string[]): string`
  - Descompone el código en `base` + sufijo de copia + marca de turno, en este orden:
    quita la ` N` final si la tiene, y luego un sufijo `-<dígitos>` si lo tiene. Lo que
    queda es la **base** (`3454 N` → base `3454`; `3454-2` → base `3454`).
  - Sufijo consecutivo sobre la base: `3454` → `3454-2`; si `3454-2` está en `ocupados`,
    `-3`, y así. Que el origen ya sea una copia (`3454-2`) no anida (`3454-2-2`): la base
    es la misma, así que sale `3454-3`.
  - Nocturno (`turno == "NOCTURNO"`): la ` N` se vuelve a poner **al final**, después del
    sufijo → `3454-2 N`. Es la convención de la empresa que documenta
    `autoria.py::_codigo_con_turno`.
  - `ocupados` se compara contra el código completo (con su ` N` si aplica), no contra la
    base.
- `nombreEsDistinto(nombreOrigen: string, nombreNuevo: string): boolean` — compara
  normalizado (trim, espacios colapsados, sin distinguir mayúsculas) para que un espacio
  de más no cuente como cambio. Espejo de la validación del backend.

`ocupados` se obtiene con **una** llamada `listarApus({ q: base, limit: 100 })` al abrir
el diálogo (`base` = la del párrafo anterior; `q` ya busca por código y nombre, así que
trae de sobra) y se queda con los `codigo` de los `items`. Si falla, se sugiere `-2` a
secas: el `409` del backend cubre el choque, así que el fallo de la consulta no bloquea
nada.

### `web/src/components/autoria/DialogoAgregarApu.tsx`

- `modo?: "crear" | "editar" | "duplicar"`.
- En `duplicar`: precarga desde `inicial` **igual que editar** (incluida
  `tipoRefDeLinea`, que ya conserva las filas de sub-APU), pero con **código y turno
  habilitados**, el código precargado por `codigoSugerido` y el nombre precargado con el
  del origen.
- Si cambias el turno y **todavía no editaste el código a mano**, el código sugerido se
  recalcula para respetar la ` N`. Si ya lo editaste, no se toca.
- Validación extra en `duplicar` (bloquea el botón, con el motivo visible):
  `nombreEsDistinto(origen.nombre, cab.nombre)` y `(cab.codigo, cab.turno)` ≠ los del
  origen. Se suma a las que ya existen (cabecera completa, rendimientos > 0).
- Al guardar: `crearApu({ ...payload, duplicado_de: { codigo, turno } })`.
- `onCreado` pasa de `() => void` a `(codigo: string, turno: string) => void`. Los
  llamadores actuales (crear/editar) ignoran los argumentos.
- Título del diálogo: "Duplicar APU 3454 (DIURNO)".

### `web/src/pages/Apus.tsx`

Estado `duplicarDetalle: ApuDetalle | null` y botón **"Duplicar"** en `DetalleApu`, junto
a Editar (rol `editor`). Monta el mismo diálogo con `modo="duplicar"`. Al crear: recarga
la lista.

### `web/src/components/corrida/TablaItems.tsx`

En el detalle expandido, junto a la sección "Cambiar APU", botón **"Duplicar este APU y
usarlo aquí"**. Visible solo si `detalle.apu_codigo` no está vacío, `!readOnly` (corrida
activa) y el rol alcanza `editor`.

El rol necesita cablearse: la ruta `corridas/:id` no está gateada por rol en `App.tsx` y
`TablaItems` no conoce el perfil hoy. Se agrega una prop **`puedeEditar`** a `TablaItems`,
calculada en `Corrida.tsx` con `useAuth()` + `puede(perfil?.rol, "editor")` — el mismo
criterio con el que `Apus.tsx` gatea "Agregar APU". Solo la usa el botón nuevo: **"Cambiar
APU" y "Confirmar" siguen exactamente como están** (hoy dependen solo de `readOnly`, y el
backend es el que gatea de verdad); esta feature no cambia su comportamiento.

Flujo: `getApuDetalle(detalle.apu_codigo, detalle.apu_turno)` → diálogo en modo
`duplicar` → al crear, `onConfirmar(seq, codigoNuevo, turnoNuevo)`, que es el mismo
camino de reasignación que ya usa `BuscadorApu`.

Si la creación funciona pero la reasignación falla, el APU **ya quedó creado**: el toast
lo dice explícitamente ("APU 3454-2 creado; no se pudo asignar al ítem — asignalo con
Cambiar APU") en vez de sugerir que no pasó nada.

### `web/src/api/autoria.ts` y `web/src/lib/tipos.ts`

- `crearApu` acepta `duplicado_de?: { codigo: string; turno: string }`.
- `DetalleItem` gana `apu_turno: string`.

## Privacidad (Invariante #1)

Intacto. Duplicar un APU es edición de biblioteca: no construye ningún payload hacia la
IA ni pasa por `dominio/ai_assist.py`. El test que verifica que `apu_tool/servicio/` no
importa `ai_assist` cubre también estos cambios.

## Errores y casos borde

| Caso | Comportamiento |
|---|---|
| El APU de origen fue borrado entre abrir el diálogo y guardar | `400` con mensaje claro; nada se crea |
| `(código, turno)` de la copia ya existe | `409` (ya lo daba `crear_apu`); el diálogo lo muestra en un toast y no cierra |
| Nombre igual al del origen (o solo distinto en espacios/mayúsculas) | Botón bloqueado en el frontend; `400` si alguien llama la API directo |
| Código igual y turno igual al del origen | Igual que arriba |
| La consulta de códigos ocupados falla | Se sugiere `-2`; el `409` cubre el choque |
| El origen tiene sub-APUs en su composición | Se copian como sub-APU (marca `tipo="apu"` + `ref_shift` preservados) |
| Un componente del origen apunta a un insumo huérfano/ambiguo | La copia hereda su `precio_unitario_hist`, así que cuesta igual que el original |
| Corrida congelada | El botón de la entrada B no aparece (consistente con el resto del solo-lectura) |
| Ítem de corrida sin APU asignado | El botón de la entrada B no aparece |

## Pruebas

**pytest**
- `crear_apu` con `duplicado_de`: hereda `precio_unitario_hist` de los componentes que
  coinciden por código y deja `0.0` en el insumo sustituido.
- Conserva las marcas de sub-APU del origen cuando el componente entrante no trae `tipo`.
- Los tres `400`: origen inexistente, misma identidad, nombre igual (incluida la variante
  que solo cambia mayúsculas/espacios).
- `409` cuando el `(código, turno)` destino ya existe.
- Auditoría: la entrada `apu.crear` lleva `contexto.origen == "duplicado"` y el `de`.
- `crear_apu` **sin** `duplicado_de` sigue comportándose igual (regresión).
- Endpoint `POST /api/apus` con `duplicado_de` vía `TestClient`.
- `detalle_item` devuelve `apu_turno`.
- La suite completa (`python -m pytest tests/ -q`) verde, incluidos los tests de Postgres.

**vitest**
- `duplicarApu.ts`: sufijo consecutivo, incremento sobre una copia, colisiones, ` N`
  nocturna, y `nombreEsDistinto` con espacios/mayúsculas.
- `DialogoAgregarApu` en modo duplicar: código y turno habilitados, código sugerido,
  botón bloqueado mientras el nombre sea el del origen, recálculo del código al cambiar
  el turno solo si no lo editaste, y `duplicado_de` en el payload.
- Entrada B: crea y reasigna; el caso "creó pero no pudo asignar" muestra el toast
  correcto; el botón no aparece con `readOnly`, sin APU asignado, ni con rol por debajo de
  `editor`.
- Regresión: con `puedeEditar={false}`, "Cambiar APU" y "Confirmar APU actual" siguen
  visibles y funcionando como hoy (la prop nueva solo gatea el botón de duplicar).
- `npm run build` (tsc -b) debe pasar — no basta `tsc --noEmit`.

## Criterios de aceptación

1. Desde la página APUs, duplicar el APU de la MD12, cambiar un insumo por el de la MD13,
   darle código y nombre propios, y guardarlo: aparece en la lista y queda disponible para
   corridas, sin tocar el original.
2. El botón de guardar no se habilita mientras el nombre siga siendo el del origen, y el
   aviso dice por qué.
3. El código llega sugerido (`3454-2`) y editable; para un origen nocturno respeta la ` N`.
4. La copia **cuesta lo mismo** que el original salvo por el insumo sustituido — incluidas
   las líneas cuyo insumo es huérfano o no tiene tarifa en catálogo.
5. Los sub-APUs del origen siguen siendo sub-APUs en la copia.
6. Desde un ítem de corrida activa, "Duplicar este APU y usarlo aquí" crea la copia y deja
   el ítem reasignado en un paso; en una corrida congelada el botón no aparece.
7. La auditoría muestra que ese APU nació como duplicado, y de cuál.
8. `pytest` completo verde y `npm run build` sin errores.

## Deuda conocida (no se arregla aquí)

`editar_apu` también pasa por `_componentes_de` y por lo tanto pone
`precio_unitario_hist=0.0` en **todos** los componentes al guardar: editar el rendimiento
de un insumo desde la web puede tirar a $0 (con alerta) las líneas cuyo insumo es huérfano
o sin tarifa en catálogo. Es preexistente y ajeno a esta feature. Este diseño deja el
helper (`hist=`) que haría el arreglo trivial —pasar el mapa del propio APU—, pero **no lo
aplica**: cambiar la conducta de `editar_apu` merece su propia decisión.
