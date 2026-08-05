> Espejo automático — no editar aquí. Fuente: `docs/superpowers/specs/2026-08-04-duplicar-apu-design.md`

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

Para que la copia no salga costando menos que el original, el diseño arregla en el camino
la pérdida del precio histórico de respaldo al escribir APUs desde la web — incluida la que
sufre hoy `editar_apu`— y le pone piso de 1 (nada en $0).

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
| Nada en $0 | Ningún componente escrito desde la web queda con `precio_unitario_hist` en 0: **piso de 1**. |
| `editar_apu` | Se **arregla** en esta feature: hereda el histórico del propio APU en vez de borrarlo. |
| `pricing.py` | **No se toca.** Los APUs del histórico costean exactamente igual que hoy. |
| Backend | Sin ruta nueva: `POST /api/apus` gana un campo opcional `duplicado_de`. |
| Capa de datos | **No se toca** (`repositorio.py`, esquemas SQL y ambos backends quedan igual). Sin migración. |
| Rol | `editor`, igual que "Editar APU". |

**Fuera de alcance:** duplicar en lote (varias variantes de una vez); duplicar desde el
cuadro Excel; cambiar la identidad de un APU ya creado (eso sigue siendo borrar + crear);
aplicar el piso de 1 al **costear** (sería un cambio de conducta para los APUs que ya
tienen histórico 0 en la base) y migrar esos valores ya guardados.

## Por qué el `precio_unitario_hist` importa

Cada componente guarda el precio histórico embebido como **respaldo**. `pricing.py`
(`_cost_insumo`, líneas 117-133) lo usa cuando el insumo es huérfano o ambiguo en el
catálogo, o cuando existe pero no tiene tarifa en Principal (`sin_precio_catalogo`).

`autoria.py::_componentes_de` —la que arma componentes desde el diálogo web— pone
**`precio_unitario_hist=0.0` siempre**. Si la copia viajara de vuelta por el diálogo sin
más, esas líneas quedarían en **$0** en la copia mientras el original sí costea el
histórico: la copia costaría menos que el original sin que eso sea decisión de nadie,
contra la regla de negocio "nada en $0".

De ahí las dos reglas de esta feature:

1. **Heredar.** La copia toma el histórico de los componentes que siguen siendo los
   mismos. Lo mismo vale para `editar_apu`, que hoy lo borra: pasa a heredar el del propio
   APU (ver abajo).
2. **Piso de 1.** Lo que se escriba desde la web nunca queda en 0: si no hay histórico que
   heredar, se guarda `1.0`. Es el mismo idioma que ya usa el proyecto para el material del
   cliente ("nada en $0", y `mul_redondeado` sube a 1 lo que redondearía a 0).

### El piso no apaga ninguna alerta (verificado)

`alertas.py:34` es un `elif`: la regla dura del `$0` va **antes** de los motivos de cruce.
Hoy, un componente ambiguo con histórico 0 reporta el genérico *"en $0"* y **tapa** el
motivo real. Con el piso, cae al `elif` siguiente y reporta *"cruce ambiguo"*, *"sin
insumo en catálogo"* o *"sin precio en el catálogo"* — más accionable, que es justo lo que
persigue el comentario de `alertas.py:29`.

Todas las ramas de `pricing.py` que leen el histórico llevan un `calidad_cruce` que está
en `_MOTIVO_CRUCE` (`ambiguo`, `huerfano`, `apu_vacio`, `ciclo`,
`CALIDAD_SIN_PRECIO_CATALOGO`), así que ninguna se queda muda. El `$0` deliberado de las
listas NP (`CALIDAD_SIN_PRECIO_LISTA`) tiene su propia rama antes de la regla dura y no
depende del histórico: **no se toca**.

El piso va en el camino de **escritura**, no en el de costeo. `pricing.py` queda intacto,
así que los APUs que ya tienen histórico 0 en la base siguen costeando igual que hoy: cero
riesgo de que el cuadro cambie por debajo.

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

`_componentes_de(...)` gana un parámetro **opcional** `hist: dict[str, float] | None` y
aplica el piso:

```python
PISO_HIST = 1.0   # regla de negocio: nada en $0

heredado = (hist or {}).get(cod, 0.0)
precio_unitario_hist = max(PISO_HIST, heredado)
```

Un histórico real, en pesos, está muy por encima de 1, así que el piso solo muerde donde no
había nada que heredar (o donde el propio origen ya traía 0, que también sube a 1). Con
esto, **ninguna** escritura desde la web —alta individual, duplicado o edición— puede
guardar un componente con histórico 0.

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

Cuando `duplicado_de` es `None`, `crear_apu` se comporta como hoy salvo por el piso de 1
en el histórico de los componentes.

### `editar_apu` — arreglo del histórico

`editar_apu` ya lee los componentes existentes para armar el mapa `previos` (conserva las
marcas de sub-APU). Con el mismo recorrido arma **también** el mapa `hist` del propio APU y
lo pasa a `_componentes_de`. Efecto: editar el rendimiento de un insumo desde la web deja
de destruir el respaldo histórico de los demás componentes.

Es el mismo helper que usa `crear_apu` con `duplicado_de`, así que la extracción del par de
mapas (`previos`, `hist`) desde una lista de componentes se hace **una vez** y la comparten
las dos rutas. La regla de desempate cuando un código se repite es la que ya aplica
`editar_apu` hoy: gana la primera aparición, salvo que otra sea de `tipo == "apu"`.

Es un arreglo de conducta, no una feature: un APU editado que antes bajaba de costo (o
caía a $0) en sus componentes huérfanos ahora conserva el costo del original. Va con test
de regresión propio.

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
| El insumo nuevo (el que sustituiste) no tiene precio en catálogo | Su histórico queda en el piso de 1, y la línea alerta por el motivo de cruce ("sin insumo en catálogo" / "cruce ambiguo" / "sin precio en el catálogo") en vez de por "en $0" |
| El origen ya traía un componente con histórico 0 | Sube al piso de 1 en la copia (nada en $0) |
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
- `crear_apu` **sin** `duplicado_de` sigue comportándose igual, salvo el piso (regresión).
- **Piso de 1:** un componente sin histórico que heredar queda guardado en `1.0`, nunca en
  `0.0` — en alta individual, en duplicado y en edición.
- **`editar_apu`:** editar un APU conserva el `precio_unitario_hist` de los componentes que
  siguen siendo los mismos (test de regresión del arreglo), y sigue conservando las marcas
  de sub-APU (test que ya existe, debe seguir verde).
- **Alertas:** un componente ambiguo/huérfano con histórico en el piso sigue alertando, con
  el motivo de cruce en vez del genérico "en $0" (`alertas_costeo`). Y un componente con
  `CALIDAD_SIN_PRECIO_LISTA` sigue reportando "sin precio en la lista", intacto.
- **`pricing.py` sin cambios:** los tests del motor de precios y del cuadro deben pasar sin
  tocarlos. Si alguno necesita cambio, es señal de que el piso se filtró al costeo.
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
8. **Nada en $0:** ningún componente guardado desde la web queda con histórico en 0; el
   mínimo es 1.
9. **Editar deja de romper el respaldo:** editar el rendimiento de un insumo de un APU no
   cambia el costo de los demás componentes.
10. Los APUs del histórico costean **igual que antes** (los tests de `pricing.py` y del
    cuadro pasan sin modificarlos).
11. `pytest` completo verde y `npm run build` sin errores.

## Lo que queda pendiente a propósito

En la base ya hay componentes con `precio_unitario_hist = 0` guardados desde antes (los que
se crearon o editaron por la web hasta ahora). Esta feature **no los toca**: el piso aplica
de aquí en adelante, y `pricing.py` sigue costeándolos como hoy. Subirlos requeriría o
parchear el costeo —cambiaría el cuadro de APUs existentes— o migrar datos en producción con
backup. Se decide aparte, con la cuenta de cuántas filas son sobre la mesa.
