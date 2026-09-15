# Importar insumos sin pisar los precios internos

**Fecha:** 2026-09-15
**Estado:** aprobado

## Problema

Subir un Excel de insumos en lote (el caso real: la lista completa del visor del IDU,
miles de filas) **sobreescribe el precio de todos los códigos que ya existen sin mirar
qué fuente tenían**. Un costo interno curado durante meses lo pisa una importación
masiva de precios públicos, en silencio y en una sola pasada.

El punto de paso es `apu_tool/servicio/autoria.py::_cambio_upsert`:

```python
precio_nuevo = f["precio"] if f["tiene_precio"] else ins.precio
fuente_nueva = f["fuente"] or ins.fuente_precio
```

No hay ninguna comprobación de `ins.fuente_precio`: si el archivo trae precio, gana.

**El segundo bug, en el `or` de la línea de abajo.** Con un archivo sin columna
`fuente` (o con la columna vacía), el precio se reemplaza por el del archivo pero la
etiqueta se queda con la vieja: queda un precio del IDU rotulado `COSTO INTERNO`, y
`config.classify_price_source` lo sigue tratando como confidencial. No se pierde el
dato — se rotula mal, y nada lo avisa.

**El hueco en la interfaz.** `preview_importar_insumos` ya devuelve `fuente_actual` en
cada cambio, y `web/src/components/insumos/DialogoImportarInsumos.tsx` nunca la pinta:
ves que el precio cambia, no que estás reemplazando un costo interno por uno público.

### Lo que ya protege (y por qué no alcanza)

- `insumo_precios` es append-only: el precio viejo queda en el historial con su fuente.
  Recuperable — a mano, fila por fila, sabiendo que pasó.
- Auditoría por fila con `origen:"import"` y `lote_id` por importación.
- Hay preview antes de aplicar. Pero el preview de una importación del visor IDU trae
  miles de filas: los ~107 insumos internos no se distinguen del resto a ojo.

### Proporciones reales (base local, 2026-08-10)

| Fuente vigente | Insumos |
|---|---|
| `PRECIO IDU` | 8050 |
| `COSTO INTERNO` | 93 |
| `REFERENCIA NUEVOS PROYECTOS` | 4 |
| *(fuente vacía)* | 4 |
| `COMPRAS ALMACEN 2026` | 3 |
| `REFERECIA NUEVOS PROYECTOS` *(typo)* | 1 |
| `PROYECTO WF1-WF2` | 1 |
| `COMPRAS 2025 + AUMENTO 5.1%` | 1 |

Una importación declarada `PRECIO IDU` debe poder pisar los 8050 y **no debe tocar los
107 restantes**.

## Alcance

- `apu_tool/servicio/autoria.py` — import de insumos: la declaración de fuente y el candado.
- `apu_tool/servicio/rutas.py` — los dos endpoints de import de insumos.
- `apu_tool/servicio/plantillas.py` — la plantilla pierde la columna `fuente`.
- `web/src/components/insumos/DialogoImportarInsumos.tsx` + `web/src/api/insumos.ts` +
  `web/src/lib/tipos.ts` — el desplegable, el balde nuevo y la columna que faltaba.
- `tests/` — cuatro pruebas nuevas; los ~15 llamados existentes ganan el argumento nuevo.

**Fuera de alcance, decidido:**

- **El importador de APUs.** `aplicar_importar_apus` ya hace
  `if alm.apus.get_apu(a.codigo, a.shift): continue` — un APU que ya existe no se pisa
  nunca. Seguro por construcción; no se toca.
- **La edición manual de precios** (`servicio/insumos.py::aplicar_cambios`). Ahí el
  usuario ve y escribe fila por fila lo que cambia: no es una pisada a ciegas.
- **Forzar.** No hay casilla de escape para pisar un interno desde el import en lote.
  Si hay que cambiar un interno, se edita por insumo, que ya se puede.

## Diseño

### 1. La importación declara su fuente

El importador recibe **`fuente_import`**: la fuente que el usuario escoge en el diálogo.
Se aplica a **todas** las filas del archivo — al crear y al actualizar — y la columna
`fuente` del archivo se ignora.

Con eso muere el `fuente_nueva = f["fuente"] or ins.fuente_precio`: ya no existe el
camino que deja un precio nuevo con la etiqueta vieja. Lo que ves en el diálogo es lo
que queda rotulado en la base.

La plantilla (`plantillas.py::plantilla_insumos`) pierde la columna `fuente`, para que
no prometa un campo que ya no se lee. El parser (`_filas_insumos`) **sigue tolerándola**:
`col("fuente", "source")` devuelve `None` si no está, y la fila queda con `fuente: ""`
que de todos modos se descarta. Un archivo viejo sube igual.

`fuente_import` es **obligatoria** en el endpoint HTTP y en la función de servicio. No
lleva default: un default silencioso es exactamente cómo nació el bug de la etiqueta.
Los ~15 llamados en `tests/` ganan una palabra cada uno.

El desplegable se llena con `GET /api/insumos/fuentes`, que ya existe
(`rutas.py:733` → `alm.precios.fuentes(lista_id=...)`), y permite escribir una fuente
nueva. Mismo patrón que el Grupo del APU: vocabulario que sale de los datos, sin tabla.

### 2. El candado

```python
def _protegida(ins, fuente_import: str) -> bool:
    """Una importación pública no pisa un precio interno."""
    return (config.classify_price_source(fuente_import) == "publico"
            and not ins.sin_precio
            and config.classify_price_source(ins.fuente_precio) == "interno")
```

La regla en una frase: **lo público no pisa lo interno**. Es asimétrica a propósito. Una
tanda pública es masiva y automática (miles de filas del visor); una tanda interna es
curada y deliberada, y sí puede pisar lo que sea — incluido "ascender" un insumo que hoy
tiene precio IDU a costo interno propio, que es algo que hoy se puede hacer y se sigue
pudiendo.

Tres detalles que no son decorativos:

- **Vive en `_upsert_o_invalida`.** Es el embudo por donde pasan los dos caminos de
  match (con nombre → identidad código+nombre; sin nombre → código único). Un solo
  punto, no un `if` en cada rama.
- **`not ins.sin_precio` evita el falso positivo.** Un insumo sin tarifa en la lista
  consultada llega con `fuente_precio=""` por el LEFT JOIN (ver el docstring de
  `Insumo.sin_precio` en `nucleo/models.py`), no porque sea interno. Sin ese término,
  una importación pública contra una lista de NP recién creada quedaría **bloqueada
  entera**: todos sus insumos se verían como internos.
- **Fuente vacía con precio real cuenta como interna** (`classify_price_source("")` →
  `interno`). Son 4 insumos. Conservador a propósito: no sabemos qué es ese precio, y la
  fila queda visible en el balde en vez de pisarse callada.

`config.PUBLIC_PRICE_SOURCES` (hoy `{"PRECIO IDU"}`) sigue siendo el único lugar donde
se define qué es público. Si mañana entra otra entidad, se agrega ahí y el candado la
respeta sin tocar nada más.

### 3. El preview

Balde nuevo **`protegida`**, hermano de `conflicto` e `invalida`:

```python
{"codigo", "nombre", "fuente_actual", "precio_actual", "precio_archivo"}
```

`precio_archivo` es `null` cuando el archivo no trae precio para esa fila — y esa fila
**también se protege**: con la fuente declarada mandando, una fila sin precio le
cambiaría solo la *etiqueta* al insumo interno, que es el bug de rotulado al revés.

En el diálogo, sección propia: **"Protegidas — no se tocan"**, con esas cinco columnas.
El usuario ve exactamente qué quedó quieto y con qué precio venía en el archivo.

Dentro de `_upsert_o_invalida` el candado va **primero**, antes del chequeo de
`MOTIVO_SIN_PRECIO_EN_LISTA`. Los dos casos son excluyentes (`_protegida` exige
`not ins.sin_precio` y el otro exige `ins.sin_precio`), pero el orden queda fijado para
que no dependa de esa coincidencia.

Y la tabla **Actualizar precio** gana la columna **Fuente actual**, que el backend ya
manda y el diálogo nunca pintó. En una importación pública esa columna será siempre la
misma (el candado garantiza que solo quedan públicos); en una interna es la que deja ver
qué estás reemplazando.

### 4. Aplicar

`aplicar_importar_insumos` ya recalcula el preview internamente a partir del archivo
(`prev = preview_importar_insumos(...)`) y recorre los baldes `crear` y `actualizar`. Con
`fuente_import` pasando a ambos, las filas protegidas **nunca llegan a `actualizar`**: no
hay una segunda regla que se pueda desincronizar de la que viste en pantalla.

El resultado gana `protegidos: N` y el toast lo dice:
`"12 creado(s), 340 actualizado(s), 107 protegido(s)"`.

Las filas protegidas **no** generan auditoría: no cambió nada. Quedan en el preview, que
es donde se miran.

### 5. Reglas que no cambian

- **La regla "nada en $0"** sigue igual: `precio_nuevo <= 0` es error, antes y después
  del candado.
- **El no-op** (precio y fuente iguales) sigue saltándose, con su excepción de
  `sin_precio_actual`.
- **La regla aplica igual contra Principal y contra listas de NP.** Una sola regla, sin
  excepción por lista: un costo interno de una obra de NP merece la misma protección.
- **Crear no se toca.** Un insumo que no existe no pisa nada; se crea con la fuente
  declarada.

## Pruebas

Cuatro nuevas en `tests/test_servicio_autoria.py`:

1. **El caso del usuario.** Insumo con `COSTO INTERNO` + import declarado `PRECIO IDU`
   → la fila cae en `protegida`; después de `aplicar`, el precio **en base** no cambió y
   `protegidos == 1`.
2. **La asimetría.** El mismo insumo + import declarado `COMPRAS ALMACEN 2026` → cae en
   `actualizar` y sí se escribe.
3. **El falso positivo.** Insumo sin tarifa en una lista de NP + import `PRECIO IDU` →
   **no** se protege (sigue el camino de hoy: `actualizar` o `invalida` según traiga
   precio el archivo).
4. **La etiqueta.** Archivo con columna `fuente` distinta a la declarada → gana la
   declarada, en `crear` y en `actualizar`.

Más los ~15 llamados existentes actualizados con el argumento nuevo, y el round-trip de
`tests/test_plantillas.py` ajustado a la plantilla sin columna `fuente`.

En el frontend, `DialogoImportarInsumos.test.tsx` gana: el botón Aplicar está
deshabilitado hasta escoger fuente, y el balde `protegida` se pinta.

## Riesgos

- **Cambio de contrato HTTP.** Los dos endpoints de import pasan a exigir un campo nuevo.
  El único cliente es el diálogo de esta misma app; se despliegan juntos.
- **La plantilla cambia.** Quien tenga una plantilla vieja guardada la sube igual (el
  parser tolera la columna sobrante), solo que la columna `fuente` deja de tener efecto.
  Es el punto: antes tampoco tenía el efecto que parecía tener.
