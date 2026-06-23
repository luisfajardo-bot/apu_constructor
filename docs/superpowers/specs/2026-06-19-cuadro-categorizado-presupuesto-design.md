# Cuadro resumen categorizado desde el presupuesto

**Fecha:** 2026-06-19
**Estado:** aprobado para planificar

## Objetivo

Generar un cuadro resumen **agrupado por capítulos del presupuesto** (p. ej. "obra
civil", "redes húmedas", "redes eléctricas externas") que **sume y compare**, por
capítulo y en total, el **precio contractual** contra el **costo interno** calculado
con los APUs de la empresa. Además, permitir **ver cada APU completo** (estilo de la
pestaña APUS del Excel original).

La fuente es el presupuesto oficial estructurado por capítulos que vive en el Excel
histórico; hoy el armador solo lee una lista plana de licitación sin capítulos.

## Decisiones acordadas

1. **Fuente:** la hoja **`FOR 1-PPTO OFICIAL`** del Excel histórico
   (`config.detect_source_xlsx()`).
2. **Precio contractual:** la columna de **valor unitario BÁSICO (sin AIU)** — col `[9]`
   (0-indexada). Comparación "manzana con manzana" contra el costo interno directo
   (ambos sin AIU). El AIU (35.737%) queda fuera del análisis.
3. **Ver APUs:** una hoja con cada APU como **bloque apilado estilo Excel original**:
   título de la actividad y debajo sus insumos (rendimiento, precio unit., costo) y el
   costo unitario del APU.
4. **Enfoque A — flujo nuevo en paralelo:** lector + reporte + comando nuevos, reusando
   matching/costeo/ensamblaje. El flujo de licitación plana NO se toca.
5. **Agrupación por capítulo** (nivel alto), no por subgrupo.
6. **Todos** los capítulos del presupuesto se procesan.

## Estructura de la hoja `FOR 1-PPTO OFICIAL` (columnas 0-indexadas)

| Col | Contenido |
|-----|-----------|
| `[2]` | N° = **código IDU** del ítem (3009, 4489…) |
| `[3]` | ítem de pago (7.101…) — en filas de capítulo, el número de capítulo (7) |
| `[6]` | descripción del ítem; **también** los encabezados (`REDES ELÉCTRICAS EXTERNAS`, `TURNO DIURNO`, `REDES ENERGÍA`…) |
| `[7]` | unidad |
| `[8]` | **cantidad** |
| `[9]` | valor unitario **básico (sin AIU)** ← precio contractual |
| `[10]` | valor unitario + AIU 35.737% (no se usa) |
| `[11]` | valor total (= cantidad × `[10]`; no se usa) |

Aritmética verificada: fila 13 → 6445 × 67153 = 432.801.085.

Reglas de parseo (recorrido de arriba abajo con estado `(capítulo, turno, subgrupo)`):
- Fila con `[6]` con texto y **sin** código en `[2]` → **encabezado**:
  - si `[3]` trae un número entero → fija el **capítulo** (`"7 · REDES ELÉCTRICAS EXTERNAS"`);
  - si `[6]` contiene `TURNO DIURNO`/`TURNO NOCTURNO` → fija el **turno**;
  - en otro caso → fija el **subgrupo** (informativo).
- Fila con código en `[2]` y cantidad en `[8]` → **ítem**: hereda capítulo/turno vigentes.
- Filas de títulos/sub-encabezados sin datos útiles (p. ej. `GENERAL`/`PARTICULAR`) se ignoran.

## Alcance

### Archivos
- **Nuevo:** `apu_tool/presupuesto.py` — lector del presupuesto.
- **Nuevo:** `apu_tool/report_categorizado.py` — reporte agrupado por capítulo.
- **Modificado:** `apu_tool/models.py` — extender `LicitacionItem` con dos campos
  **opcionales** (default `""`): `categoria` y `codigo_sugerido`. No rompe el flujo actual.
- **Modificado:** `apu_tool/assemble.py` — armado por **código directo** cuando hay
  `codigo_sugerido`; respaldo al match difuso/IA si el código no existe.
- **Modificado:** `apu_tool/pipeline.py` — función `build_desde_presupuesto(path, hoja)`.
- **Modificado:** `apu_tool/cli.py` — comando `build-ppto [hoja]`.
- **Nuevo (tests):** `tests/test_presupuesto.py`, `tests/test_report_categorizado.py`.

### Modelo de datos
`LicitacionItem` gana:
- `categoria: str = ""` — capítulo del presupuesto.
- `codigo_sugerido: str = ""` — código IDU dado por el presupuesto (para armado directo).

Campos opcionales con default vacío ⇒ la ruta de licitación plana sigue igual.

### Lector — `presupuesto.py`
`read_presupuesto(path, hoja="FOR 1-PPTO OFICIAL", default_shift=config.SHIFT_DIURNO) -> list[LicitacionItem]`
Aplica las reglas de parseo de arriba. Cada ítem: `item`=ítem de pago `[3]`,
`descripcion`=`[6]`, `unidad`=`[7]`, `cantidad`=`[8]`, `precio_contractual`=`[9]`,
`shift`=turno vigente, `categoria`=capítulo vigente, `codigo_sugerido`=código IDU `[2]`.

### Armado por código directo
En el ensamblado: si `item.codigo_sugerido` está presente, buscar el APU por
`(codigo_sugerido, shift)`:
- existe → costear y marcar `AUTO` (código autoritativo), `origen="historico"`;
- no existe → caer al match difuso/IA actual, marcado `REVIEW`/`NEW`.
La `categoria` viaja en `item`, así que `AssembledApu.item.categoria` da la agrupación.

### Reporte — `report_categorizado.py`
`write_report_categorizado(apus, path) -> Path`. Hojas:
- **RESUMEN POR CAPÍTULO:** una fila por capítulo (Total Contractual, Total Costo,
  Margen Total, Margen %); fila de subtotal por capítulo y **gran total** al final.
- **DETALLE:** ítems agrupados bajo su capítulo (con subtotal por capítulo), columnas
  por ítem: cantidad, P. contractual, costo unit., margen unit., totales, estado.
- **APUS:** cada APU como bloque apilado estilo Excel original (título + insumos +
  costo unitario del APU).
- **ALERTAS:** ítems `REVIEW`/`NEW`.
- **INFO:** metadatos + nota de privacidad ("la IA no vio dinero").

### Orquestación / interfaz
- `pipeline.build_desde_presupuesto(path=None, hoja="FOR 1-PPTO OFICIAL")`: detecta el
  Excel fuente si no se da `path`, lee el presupuesto, arma/costea cada ítem, escribe el
  cuadro categorizado en `salidas/` con nombre con timestamp. Reúsa la lógica existente.
- `cli.py`: `build-ppto [hoja]` invoca esa función.

## Invariantes / lo que NO cambia
- **Invariante #1 (la IA nunca ve dinero):** intacta. El precio contractual viene del
  presupuesto y el costo del motor interno; ninguno se pasa a la IA. Los payloads a la IA
  siguen pasando por `privacy.py`.
- El flujo de licitación plana (`read_licitacion`, `report.py`), la base de datos y el
  esquema SQL no se tocan.
- El contrato de `repository.py` no cambia.

## Riesgos y mitigación
- **Formato irregular del presupuesto:** la hoja tiene filas de título, sub-encabezados
  (`GENERAL`/`PARTICULAR`), posibles filas de subtotal y celdas combinadas. El lector
  debe ser defensivo: solo emite ítem si hay código en `[2]` Y cantidad en `[8]`; ignora
  el resto. Se valida con verificación real sobre el Excel.
- **Código sin APU en la base:** se marca `REVIEW`/`NEW` y aparece en ALERTAS; no rompe
  el flujo.
- **Capítulo sin número en `[3]`:** si algún capítulo no trae número, se usa el texto de
  `[6]` como nombre de capítulo igualmente.
- **Turno:** un mismo código puede aparecer bajo `TURNO DIURNO` y `TURNO NOCTURNO`; el
  turno vigente del encabezado decide qué APU `(codigo, shift)` se costea.

## Verificación
- `python -m pytest tests/ -q` — todo verde, incluidos los nuevos.
- `python run_cli.py build-ppto` — genera el cuadro categorizado sin error.
- Revisar a mano: los capítulos detectados, que los subtotales por capítulo sumen el gran
  total, y que ítems con código existente NO caigan en "Revisar".

## Nota de versionado
El proyecto no es repositorio git, así que no hay paso de commit; el spec queda versionado
por existir en el árbol del proyecto.
