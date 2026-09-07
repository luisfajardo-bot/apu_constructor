# Igualar el costo unitario al precio contractual

Fecha: 2026-09-07 · Rama: `feat/igualar-costo-contractual` (desde `master`)

## Problema

Hay actividades de **proyectos especiales** que son globales: valen lo que dice el
contrato y punto. Armarles el APU se puede, pero no paga el trabajo — son de un solo
uso, no se repiten entre licitaciones, y su composición real no le sirve a nadie
después.

Hoy no hay forma de decir eso. El costo de una fila de corrida **no se guarda**: se
recalcula en cada apertura desde la composición del APU asignado (`_costear_row`,
`servicio/corridas.py:281`). Una fila sin APU cuesta $0, y el candado de
`congelar`/`generar_cuadro` la bloquea. O sea: o armás el APU, o no sacás el cuadro.

## Qué se construye

Un botón **`Igualar costo al contractual`** en la barra de selección que ya existe
al pie de la tabla de corrida (`web/src/components/corrida/TablaItems.tsx:521`, junto
a "Confirmar el APU actual" y "Borrar"). Con N filas marcadas, copia el precio
contractual de cada una como su costo unitario. Margen 0, a propósito.

El costo copiado es **provisional y reversible**: cuando más adelante exista el APU de
verdad y se asigne a esa fila, el costo a mano desaparece solo y la fila vuelve a
costear desde la composición.

## Decisiones

| Decisión | Por qué |
|---|---|
| **Copia de una vez**, no un vínculo vivo | Si mañana cambia el contractual, el costo se queda donde estaba y aparece un margen ≠ 0 — visible, para que decidas. Un costo que persigue al contractual escondería el cambio. |
| Se borra en `actualizar_eleccion`, no con un botón | Es el **único** punto de paso por el que cambia el APU de una fila, y ya borra ahí `revision_json`. Armás el APU, lo asignás, y el costo a mano se limpia solo. Un botón "quitar" sería otra cosa que acordarse de apretar. |
| El costo a mano **abre el candado** de `seqs_sin_apu` | Es el caso de uso entero: no querés armar el APU. El candado existe para que no salga un cuadro con filas en $0 sin que nadie se entere; una fila con costo declarado y marcado no es ninguna de las dos cosas. Cambia un invariante que `CLAUDE.md` decía no esquivar, y por eso se actualiza el documento. |
| El botón **rechaza** las filas con contractual ≤ 0 | Igualar a 0 es exactamente el $0 que la regla de negocio prohíbe. |
| Siempre aparece en la hoja ALERTAS del cuadro | Regla de la casa: nada silencioso. Un costo que puso una persona tiene que ser distinguible de uno que calculó el motor. |
| La fila queda en `status = confirmed` | La resolviste a propósito; seguir contándola en "en revisión" sería mentir en los totales. |
| Solo el botón — sin costo editable a mano | YAGNI. Cubre los proyectos especiales. Si después hacen falta valores arbitrarios, el campo ya está y se le agrega la edición. |
| Corrida congelada → 409 | Misma respuesta que ya dan confirmar y agregar líneas. La barra ni siquiera se muestra (`seleccionable` ya mira `readOnly`). |

## Arquitectura

### `datos/` — la columna

`corrida_item.costo_manual` (`REAL` en SQLite, `numeric` en Postgres, `NULL` = costeo
normal), agregada con `ADD COLUMN IF NOT EXISTS` al boot en los dos backends, igual
que `modo` y `snapshot_json`. `CorridaItemRow.costo_manual: Optional[float] = None`.

Método nuevo en el contrato de `datos/repositorio.py` y en los dos backends:

```python
def set_costo_manual(self, corrida_id: int, costos: dict[int, float]) -> None
```

`costos` es `{seq: costo}` — ya trae los seqs, no hace falta pasarlos aparte. Escribe
`costo_manual` y `status='confirmed'` en un solo lote. Es una sola acción del usuario
("esta fila la resuelvo así"), así que es una sola escritura.

`actualizar_eleccion` (`corridas_db.py:148` y `pg/corridas_pg.py:93`) suma
`costo_manual=NULL` al `revision_json=NULL` que ya escribe. Es el borrado automático.

### `servicio/corridas.py` — el costeo

`_costear_row` sale temprano cuando `row.costo_manual is not None`: devuelve un
`AssembledApu` con `costo_unitario = costo_manual` y `componentes = []`, sin consultar
precios ni catálogo. Como `costo_total` y `contractual_total` pasan por el mismo
`mul_redondeado` sobre los mismos números, el margen de la fila da **0 exacto**.

`seqs_sin_apu` (`corridas.py:54`) ignora las filas con `costo_manual`. Un solo cambio;
lo heredan `congelar` y `generar_cuadro`, que son sus dos únicos llamadores.

`_vista_item` agrega `"costo_manual": ens.componentes == [] and ens.costo_unitario > 0`
— derivado del ensamble, así los dos call sites quedan sin tocar. La firma es
inequívoca: sin componentes el motor no puede dar un costo positivo.

Función de servicio nueva:

```python
def igualar_costo_al_contractual(alm, corrida_id: int, seqs: list[int], actor=None) -> dict
```

Corrida congelada → `CorridaCongelada` (409). Filas con `precio_contractual <= 0` → se
saltean y se informan en la respuesta. Devuelve la vista completa de la corrida, con la
misma forma que `confirmar_items`, para que el frontend solo reemplace estado.

### `dominio/alertas.py` — que se vea

`alertas_costeo` reconoce la firma `componentes == [] and costo_unitario > 0` y agrega
el motivo `"costo puesto a mano (igualado al contractual)"`. Va **antes** de la regla
del $0, como ya hace `sin_precio_lista`, para dar el motivo accionable.

Funciona igual con la corrida congelada sin tocar el snapshot: `congelar` guarda
`composicion: []` y `costo_unitario`, y `_assembled_desde_snapshot` reconstruye la misma
firma.

### `dominio/privacy.py` — la frontera

`costo_manual` entra en `_FORBIDDEN_KEYS`. Hoy no filtra —los payloads de `revision.py`
se arman con listas de campos explícitas, nunca volcando la fila— pero es un campo
monetario nuevo y `CLAUDE.md` lo pide.

### `servicio/rutas.py` — el endpoint

`POST /api/corridas/{id}/igualar-costo`, cuerpo `{"seqs": [7, 8]}`, rol **`editor`**.

Es a propósito **más estricto que sus vecinos**: `confirmar-lote`, `congelar` y
`generar-cuadro` piden hoy `requiere_rol("consulta")` (`rutas.py:332`, `:442`, `:480`),
que es justo el hallazgo Alto "el rol consulta escribe/borra" de la auditoría del
2026-08-28, todavía sin arreglar. No toco esos endpoints —cambiarles el rol le sacaría
el acceso a gente que hoy trabaja— pero no le abro un endpoint nuevo que **declara
dinero** a un rol de solo lectura.

Se audita como `corrida.igualar_costo` (entidad `corrida`, `antes` con el costo previo
por fila, `despues` con el nuevo). Es la misma categoría que `precio.editar`, que ya se
audita: una persona fijando plata a mano.

### `web/` — el botón

Un `Button` más en la barra pegajosa y un badge `[a mano]` en la celda de costo cuando
`costo_manual` es true. La barra ya se esconde sola en corridas de solo lectura.

## Fuera de alcance (a propósito)

- **La IA seguirá objetando esas filas** por no tener APU (`revision.py`: sin APU nunca
  es "ok"). Excluirlas del barrido es una línea, pero es otra decisión: por ahora el
  veredicto "esta fila no tiene APU" no es falso.
- **No hay botón "quitar el costo a mano"**: asignar un APU ya lo limpia.
- **CLI/GUI no cambian.** Las corridas son estado de la web (`corridas.db` no se migra
  a Postgres), y `pipeline.py` no pasa por el candado.

## Pruebas

| Prueba | Qué protege |
|---|---|
| Costo = contractual y `margen_total == 0` en la fila | El redondeo no deja un peso de resto. |
| Asignar un APU borra el `costo_manual` | La reversibilidad, en el punto de paso real. |
| `seqs_sin_apu` deja pasar la fila y `generar_cuadro` emite | El candado nuevo. |
| La fila sale en la hoja ALERTAS con el motivo | Que no sea silencioso — activa **y** congelada. |
| Contractual ≤ 0 → la fila se saltea y se informa | La regla "nada en $0". |
| Congelada → 409 | Solo lectura. |
| Contrato del repositorio contra **los dos** backends | La última vez `CorridasPg` se quedó afuera del test de contrato y por eso se escapó un bug. |

## Documentación

`CLAUDE.md`, sección **No hacer**: el candado deja de ser "ninguna fila sin APU" y pasa
a ser "ninguna fila sin APU **y sin costo declarado**". Se anota por qué.
