# Igualar por umbral de total contractual

Fecha: 2026-09-21 · Rama: `feat/umbral-igualar-contractual` (desde `master`)

## Problema

Una licitación real trae entre 1000 y 2000 actividades, y armarle el APU a cada una
cuesta semanas. Pero el dinero no está repartido parejo: un puñado de actividades se
lleva casi todo el presupuesto y la cola larga pesa centavos. Hoy no hay forma de
decirle al sistema "estas no me importan todavía".

El botón **Igualar costo al contractual** ya resuelve una fila (o las que marques a
mano), pero marcar 300 filas a mano no es un flujo, es un castigo. Y el candado de
`seqs_sin_apu` no deja emitir el cuadro mientras quede una sola fila en $0, así que
hasta la actividad de $80.000 bloquea la evaluación de la de $12.000.000.000.

Lo que falta es poder decir: **"todo lo que valga menos de $500.000.000 se iguala al
contractual; el resto lo armo yo"** — y verlo antes de apretar.

## Qué se construye

Un diálogo **`Igualar bajo umbral…`** en la barra de acciones de la corrida. Escribes
un monto, el diálogo te dice cuántas líneas caen debajo y cuánta plata representan
contra el contrato entero, y aplicas. Por dentro escribe el mismo `costo_manual` de
siempre: **no hay estado nuevo**.

Y su reverso, que hoy no existe: un botón **`Quitar costo a mano`** que devuelve las
filas marcadas al costeo normal. Con un gesto que puede tocar 1500 filas de una, no
tener vuelta atrás deja de ser aceptable.

## La regla

**Candidata** = fila con `costo_unitario == 0`, sin costo a mano, y con
`precio_contractual > 0`.

- Una fila **sin APU** siempre cuesta $0, así que entra sola: no hace falta una regla
  aparte para ella.
- Una fila **con APU pero en $0** (le faltan precios a sus insumos) también entra. Es
  otro problema —se arregla cargando el precio, que es mucho más barato que armar un
  APU— así que el diálogo muestra el desglose para que sepas cuántas son, pero no las
  esconde: están en $0 y traban el cuadro igual.
- `precio_contractual > 0` se escribe `not (x > 0)` y **no** `x <= 0`: con NaN,
  `nan <= 0` es False y el NaN se colaría al costo envenenando todos los totales.
  Es el mismo cuidado que ya tiene `igualar_costo_al_contractual`.

**Se iguala** toda candidata cuyo `contractual_total` (unitario **con AIU** × cantidad,
que es el que concilia con el Formulario 1) sea **≤ el umbral**.

## Decisiones

| Decisión | Por qué |
|---|---|
| Techo **por línea**, no acumulado tipo Pareto | Es lo que pidió el usuario y es lo que se puede explicar en una frase. Un "cubrir el 80%" se puede agregar después sobre la misma maquinaria; al revés no. |
| Regla única **"está en $0"**, con el desglose a la vista | Cubre los dos casos que importan (sin APU / con APU sin precios) sin un interruptor más. El desglose informa; no decide. |
| La previa la calcula el **frontend** | Los ítems ya están en memoria con `contractual_total`, `costo_unitario`, `costo_manual` y `apu_codigo`: la previa es aritmética sobre un arreglo que ya viajó. Un endpoint de previa sería una segunda fuente de verdad para la misma suma. Es un apoyo a la decisión, no un número que se persiste ni se emite: la escritura la manda el backend con sus propios números. (`Corrida.tsx:42` ya suma `contractual_total` para el encabezado; esto es lo mismo.) |
| El servidor **recalcula la candidatura** al aplicar | Mismo candado que `apu_evaluado` en la revisión y que `rebuscar/aplicar`: el cliente dice *cuáles quiere*, no *qué se escribe*. Sin esto, una pestaña vieja pisa con una copia del contractual el APU que alguien acabó de asignar, y encima deja la fila `confirmed` — o sea, fuera del alcance de "Volver a buscar APU". Con 10 filas eso se ve; con 1500 no. |
| Se reusa `igualar_costo_al_contractual` para escribir | Ya hace el lote, la auditoría, el rechazo del contractual ≤ 0 y el `set_estado("en_revision")`. Un camino de escritura, no dos. |
| El campo se llama `umbral_contractual`, no `umbral` | Entra a `_FORBIDDEN_KEYS` (es dinero, y `CLAUDE.md` lo pide). `umbral` a secas chocaría con los umbrales de matching, que no son dinero: un falso positivo ahí volaría un payload legítimo hacia la IA. |
| El botón no aparece con el plan a medias | Con la corrida en `armando`/`armado_detenido` las filas que faltan **no existen**, así que "5,3% del contrato" sería el 5,3% de 290 líneas de 1939. Misma condición que `Volver a buscar APU`. |
| Al deshacer, el status vuelve a `new` sin APU y a `review` con APU | No guardamos el status previo, y no hace falta: una fila sin APU **era** `new` (así la deja `assemble.py`). Con APU, `review` es la verdad honesta ("mírala"), en vez de adivinar un `auto` que quizás nunca tuvo. |
| Deshacer es **por selección**, no "deshacer la última tanda" | La barra de selección ya existe y sirve igual para 1 fila que para 1500. Una pila de tandas se muere al cerrar la pestaña. |
| Dos costeos por request al aplicar | Uno para decidir la candidatura, otro para la vista que vuelve. Es una acción deliberada, no un render. Si algún día pesa, el primero se reusa. |

## Arquitectura

### `datos/` — el borrado

Método nuevo en el contrato de `datos/repositorio.py` y en los dos backends:

```python
def limpiar_costo_manual(self, corrida_id: int, seqs: list[int], conn=None) -> None
```

Una sentencia, igual en SQLite y en Postgres:

```sql
UPDATE corrida_item
   SET costo_manual=NULL,
       status = CASE WHEN COALESCE(apu_codigo,'')='' THEN 'new' ELSE 'review' END
 WHERE corrida_id=? AND seq=?
```

`executemany` sobre los seqs, con el mismo `conn=None` opcional que
`set_costo_manual`, para que la escritura entre en la transacción que también registra
la auditoría. No toca `revision_json`: `set_costo_manual` ya lo había borrado y no hay
nada que restaurar.

### `servicio/corridas.py` — las dos funciones

```python
def igualar_por_umbral(alm, corrida_id: int, umbral: float,
                       seqs: Iterable[int], actor=None) -> Optional[dict]
```

Corrida inexistente → `None`. Congelada → `CorridaCongelada` (409). `umbral <= 0` o NaN
→ `ValueError` (400): un umbral de $0 no iguala nada, y uno negativo es un dedo
resbalado.

Costea la corrida con `vista_corrida` y se queda con los `seq` que **hoy** cumplan las
tres condiciones —candidata, `contractual_total <= umbral`, y estar en los `seqs` que
mandó el cliente—. La candidatura se lee de los ítems de esa misma vista
(`not it["costo_manual"]` y `not (it["costo_unitario"] > 0)` y
`it["precio_contractual"] > 0`), que es exactamente la definición de arriba y la misma
que usa el frontend: una sola regla, escrita en los dos lados sobre los mismos campos.
Los pedidos que ya no cumplen vuelven en `salteadas`. Delega la
escritura en `igualar_costo_al_contractual(..., umbral_contractual=umbral)` y le agrega
`salteadas` a la vista que esa devuelve (que ya trae `igualadas` y `rechazadas`).

```python
def quitar_costo_manual(alm, corrida_id: int, seqs: Iterable[int],
                        actor=None) -> Optional[dict]
```

Mismas guardas. Filtra las filas que de verdad tienen `costo_manual` (pedir el borrado
de una que no lo tiene no es un error, es un no-op), borra en lote dentro de la
transacción que audita `corrida.quitar_costo_manual` (`antes` con el costo que había,
`despues` con `null`), y si la corrida estaba `finalizada` la pasa a `en_revision` —el
cuadro ya no dice la verdad—, igual que hace su gemelo. Devuelve la vista con
`quitadas`.

`igualar_costo_al_contractual` gana **un parámetro opcional**,
`umbral_contractual: Optional[float] = None`, que solo viaja al `contexto` de la
auditoría. El registro tiene que decir con qué regla se aplicó: 312 filas igualadas de
a una y 312 igualadas por un umbral de $500M son hechos distintos.

### `dominio/privacy.py` — la frontera

`"umbral_contractual"` entra a `_FORBIDDEN_KEYS`. Hoy no viaja a ningún payload de IA
—ni siquiera se persiste, vive en el request y en la auditoría— pero es un monto con
nombre propio y la regla de la casa es esa.

### `servicio/esquemas.py` + `servicio/rutas.py` — los endpoints

```python
class IgualarUmbralIn(BaseModel):
    umbral_contractual: float
    seqs: list[int]

class QuitarCostoManualIn(BaseModel):
    seqs: list[int]
```

- `POST /api/corridas/{cid}/igualar-umbral` → rol **`editor`**
- `POST /api/corridas/{cid}/quitar-costo-manual` → rol **`editor`**

Los dos declaran dinero, así que van con el mismo rol que `igualar-costo` y por la
misma razón: más estricto que sus vecinos a propósito. `CorridaCongelada` → 409,
`ValueError` → 400, corrida inexistente → 404.

### `web/src/lib/umbralCosto.ts` — el cálculo, puro

```ts
export interface PreviaUmbral {
  candidatas: ItemCuadro[];     // en $0, con contractual > 0
  igualadas: ItemCuadro[];      // candidatas bajo el umbral, por contractual_total desc
  restantes: ItemCuadro[];      // candidatas por encima del umbral
  sumaIgualadas: number;
  sumaRestantes: number;
  contractualCorrida: number;   // suma de TODAS las filas, para los porcentajes
  sinApu: number;               // desglose de `igualadas`
  conApu: number;
  sinContractual: number;       // en $0 pero con contractual ≤ 0: no se pueden igualar
}

export function previaUmbral(items: ItemCuadro[], umbral: number): PreviaUmbral
```

Función pura sobre los ítems que la página ya tiene. Umbral 0, negativo o NaN →
`igualadas` vacío (y el botón deshabilitado). Vive en `lib/` y no adentro del diálogo
para poder probarla sin renderizar nada, igual que `corridaTabla.ts`.

### `web/src/components/corrida/DialogoUmbralCosto.tsx`

Calcado de `DialogoRebuscar` (175 líneas), que es el patrón de la casa para "previa +
aplicar solo lo marcado":

- Campo de umbral en pesos, con el monto formateado al lado (`cop(umbral)`) para no
  contar ceros a ojo: son nueve dígitos.
- El resumen en vivo, con las sumas y los porcentajes contra el contrato entero:

  ```
  Candidatas (en $0):        359 líneas · $9.100.000.000
    ├ se igualan (≤ $500M):  312 líneas · $8.400.000.000    5,3% del contrato
    └ quedan por armar:       47 líneas · $150.000.000.000  94,7% del contrato
  Se igualan: 294 sin APU · 18 con APU pero sin precios
  ```

- La lista de las afectadas, de mayor a menor, con casilla; todas marcadas. Clic con
  Shift selecciona rangos, con el ancla por `seq` (no por índice), igual que
  `DialogoRebuscar` y el diálogo de conflictos del import.
- Cambiar el umbral **rehace** las marcas: la lista es otra, y conservar destildes de
  una lista anterior sería adivinar.
- Si hay `sinContractual > 0`, una línea lo dice: esas están en $0 y no se pueden
  igualar porque el contrato tampoco las paga.

### `web/src/pages/Corrida.tsx` y `TablaItems.tsx`

- Botón `Igualar bajo umbral…` junto a `Volver a buscar APU`, con su misma condición
  (`puedeEditar && !esActivar && !planAMedias`). El `title` va como expresión
  (`title={"…" + "…"}`), no como atributo partido en dos líneas — esa ya se pagó dos
  veces.
- Al aplicar: pinta con lo que devuelve el servidor (ya recosteado), sin volver a pedir
  la corrida. Toast con las igualadas y, si hubo, un `warning` con las salteadas
  explicando por qué (cambiaron desde que abriste el diálogo).
- `Quitar costo a mano` en la barra de selección de `TablaItems.tsx`, al lado de
  `Igualar costo al contractual`, habilitado solo si alguna fila marcada tiene
  `costo_manual`.
- `web/src/api/corridas.ts`: `igualarPorUmbral(id, umbral, seqs)` y
  `quitarCostoManual(id, seqs)`.

### `CLAUDE.md`

La sección **Costo puesto a mano** suma el umbral y el deshacer, y **No hacer** suma la
regla del recálculo en el servidor (el cliente no dicta qué filas se escriben).

## Lo que NO se construye

- **Modo acumulado / Pareto.** El techo por línea es lo pedido. La maquinaria queda
  lista si después hace falta.
- **Un endpoint de previa.** Los números ya están en el cliente.
- **Umbral por capítulo.** El diálogo trabaja sobre la corrida entera, sin importar los
  filtros de la tabla: es una decisión de presupuesto, no de vista. Si algún día se
  quiere por capítulo, el lugar es este mismo diálogo con un selector.
- **Guardar el umbral en la corrida.** No es un parámetro del proyecto: es un gesto que
  se aplicó una vez y quedó en la auditoría.
- **Un estado nuevo.** Explícitamente descartado por el usuario. Se escribe el
  `costo_manual` que ya existe, con su `confirmed` y su alerta.

## Pruebas

**Backend**

- `tests/test_costo_manual.py`: el umbral iguala las que están bajo el techo y deja las
  de arriba · una fila que dejó de ser candidata (le asignaron APU entre la previa y el
  aplicar) se saltea y vuelve en `salteadas` · `precio_contractual <= 0` no se iguala ·
  umbral 0 o negativo → `ValueError` · congelada → `CorridaCongelada` · la auditoría
  registra el umbral · `quitar_costo_manual` deja la fila en $0, con status `new` sin
  APU y `review` con APU, y vuelve a trabar `seqs_sin_apu`.
- `tests/test_corridas_contrato.py`: `limpiar_costo_manual` en la batería que corre
  contra **los dos backends** (SQLite siempre, Postgres con `TEST_DATABASE_URL`). Esta
  es la que se escapó en "agregar líneas": el contrato no cubría `CorridasPg`.
- `tests/test_api_corridas.py`: los dos endpoints, con sus roles y sus códigos.

**Frontend**

- `web/src/lib/umbralCosto.test.ts`: candidatas, sumas, porcentajes, desglose
  sin APU / con APU, y los bordes (umbral 0, sin candidatas, contractual ≤ 0,
  corrida con contractual total 0 — que no puede dividir por cero).
- `DialogoUmbralCosto.test.tsx`: el resumen refleja el umbral escrito, destildar saca
  la fila del aplicar, cambiar el umbral rehace las marcas.

**Cierre:** `python -m pytest tests/ -q`, `npm test` y `npm run build` (que es
`tsc -b`, no `tsc --noEmit`: esa lección ya costó un hotfix). Smoke en el navegador
antes de pedir el push.
