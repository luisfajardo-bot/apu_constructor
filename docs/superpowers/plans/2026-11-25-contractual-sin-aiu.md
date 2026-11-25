# El contractual es el SIN AIU (ruta IDU) — plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En las corridas nuevas de la ruta IDU, `precio_contractual` pasa a ser el valor unitario básico sin AIU. La columna «incluye AIU» solo se lee para verificar el archivo contra el Excel y se descarta. Las corridas viejas no se tocan.

**Architecture:** El cambio nace en el lector (`dominio/presupuesto.py`, `PARSER_VERSION = "idu-f1/2"`). El margen, los totales, `resumen_por_capitulo`, el umbral y el chat leen `precio_contractual`, así que lo siguen sin tocar el motor. Hay tres ajustes de presentación:
- La previa trae una sola base.
- El cuadro quita la columna aparte «sin AIU» cuando no aporta nada. Lo decide por datos con `report.hay_columna_sin_aiu`.
- El chat agrega «(con AIU)» a las cifras de las corridas `idu-f1/1`.

No hay migración ni campos nuevos en `LicitacionItem`.

**Tech Stack:** Python 3 / openpyxl / FastAPI, React + TypeScript + vitest.

**Spec:** `docs/superpowers/specs/2026-11-25-contractual-sin-aiu-design.md`. Es el diseño aprobado. Léelo antes de empezar y no lo reinterpretes.

**Reglas del repo que aplican (CLAUDE.md):**

- Invariante #1: nada con dinero hacia la IA. `origen_json` y `conciliacion` siguen en `_FORBIDDEN_KEYS`. **No** borres de esa lista las claves que quedan muertas (`contractual_con_aiu`, `subtotales_excel`): un nombre muerto que sigue prohibido no cuesta nada.
- `resumen_por_capitulo` es la ÚNICA función que suma por capítulo, y el frontend no suma dinero.
- Español de Colombia en mensajes, tuteando.
- Rama `feat/contractual-sin-aiu`, ya creada. **No cambies de rama. No hagas push** sin aprobación explícita.
- Corre `python -m pytest tests/ -q` **sin `DATABASE_URL`** antes de dar una tarea por terminada.
- Frontend: verifica con `npm run build` (incluye `tsc -b`), no con `tsc --noEmit`.

**Reglas de commit (todas las tareas):**

- Un commit por tarea. El mensaje termina con la línea `Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>`.
- Patrón EXACTO. El `pop` solo corre si ese mismo comando hizo el `push`:
  ```bash
  git stash push -q constructor-apus/.obsidian/appearance.json && { git add <archivos> && git commit -q -m "<asunto>" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
  ```
- Nunca `--no-verify`. Si un hook falla, arregla la causa.
- `git add` solo de los archivos de la tarea. Hay archivos sin seguimiento en el árbol (`ejemplos/*.xlsx`, `scripts/servidor_local.py`, `smoke-*.md`…) que **no** van.

---

## Mapa de archivos

| Archivo | Qué cambia |
|---|---|
| `apu_tool/dominio/presupuesto.py` (modificar) | `precio_contractual` = básico; el valor con AIU solo verifica; `conciliacion()` sin totales con AIU; `PARSER_VERSION = "idu-f1/2"` |
| `apu_tool/nucleo/models.py` (modificar) | solo comentarios: qué es `precio_contractual_sin_aiu` en una corrida nueva y en una vieja |
| `apu_tool/servicio/corridas.py` (modificar) | la previa deja de mandar `contractual_sin_aiu` (en una lectura nueva es igual al contractual) |
| `apu_tool/dominio/report.py` (modificar) | `hay_columna_sin_aiu`, `_sin_columna_aparte` y su uso en RESUMEN |
| `apu_tool/dominio/report_categorizado.py` (modificar) | la misma regla en RESUMEN POR CAPÍTULO y en DETALLE |
| `apu_tool/servicio/consulta.py` (modificar) | «(con AIU)» en contractual, diferencia y margen de corridas `idu-f1/1` |
| `apu_tool/dominio/ai_assist.py` (modificar) | `_SISTEMA_CONSULTA` y `PROMPT_VERSION_CONSULTA = "consulta/v2"` |
| `web/src/lib/tipos.ts` (modificar) | `CapituloPrevia`, `PreviaPresupuesto` y el comentario de `precio_contractual_sin_aiu` |
| `web/src/components/corrida/PreviaIdu.tsx` (modificar) | rótulo «Contractual (sin AIU)», una sola columna y «Verificación contra el Excel» |
| `tests/test_servicio_corridas_capitulos.py` (modificar) | regresión de la corrida vieja; valores nuevos |
| `tests/test_report_capitulos.py` (modificar) | regresión del cuadro viejo; cuadro nuevo sin columna aparte |
| `tests/test_presupuesto_idu.py` (modificar) | lector nuevo + verificación contra el Excel |
| `tests/test_presupuesto.py` (modificar) | `precio_contractual` = básico |
| `tests/test_presupuesto_idu_regresion.py` (modificar) | conciliación del archivo real sin totales con AIU |
| `tests/test_servicio_previsualizacion.py` (modificar) | previa y `origen_json` sin AIU |
| `tests/test_consulta_resolver.py` (modificar) | nota «(con AIU)» |
| `tests/test_consulta_chat_motor.py` (modificar) | `consulta/v2` |
| `web/src/components/corrida/PreviaIdu.test.tsx` (modificar) | previa sin cifras con AIU |
| `CLAUDE.md` (modificar) | documentación |

**No se tocan (y por qué):**
- `ResumenCapitulos.tsx` y `TablaItems.tsx`: no muestran la columna «sin AIU» en ninguna corrida, ni vieja ni nueva, así que no hay columna que esconder. Por eso `vista_corrida` **no** gana un flag: sería un campo que nadie lee.
- `test_resumen_capitulo.py` y `test_corridas_origen.py`: prueban datos viejos (con ≠ sin) y el almacenamiento crudo, y siguen valiendo tal cual.
- `CorridasInicio.idu.test.tsx`: su fixture trae `contractual_sin_aiu` de más. Los tests no pasan por `tsc -b` (`tsconfig.app.json` los excluye) y el campo sobrante no rompe nada.

---

### Task 1: Candado de regresión — una corrida IDU vieja se ve y se cuadra igual

Esta tarea **no implementa nada**. Fija el comportamiento de hoy para las corridas que se leyeron con `idu-f1/1`: contractual CON AIU en `precio_contractual` y el básico aparte. Las pruebas **pasan hoy** y tienen que seguir pasando hasta el final del plan. Por eso van primero.

**Files:**
- Test: `tests/test_servicio_corridas_capitulos.py` (al final)
- Test: `tests/test_report_capitulos.py` (al final)

- [ ] **Step 1: Escribe la regresión de la vista**

Agrega al final de `tests/test_servicio_corridas_capitulos.py`:

```python
# ------------------------------------------------ corrida vieja (lector idu-f1/1)
def _corrida_vieja(alm) -> int:
    """Así quedó toda corrida IDU creada antes del 2026-11-25: el contractual CON AIU
    en `precio_contractual` y el básico aparte. No se migra: tiene que verse igual."""
    items = [LicitacionItem(
        item="1.001", descripcion="REPLANTEO GENERAL", unidad="M2", cantidad=100.0,
        precio_contractual=1351.0, shift="DIURNO", categoria="1 · PRELIMINARES",
        codigo_sugerido="3007", capitulo_codigo="1", capitulo_nombre="PRELIMINARES",
        item_pago_original="1.001", fila_origen=10, precio_contractual_sin_aiu=1056.0)]
    origen = {"entidad": "IDU", "formato": "idu_formulario_1",
              "parser_version": "idu-f1/1",
              "conciliacion": {"contractual_con_aiu": 135100,
                               "contractual_sin_aiu": 105600,
                               "subtotales_excel": 135100, "diferencia": 0,
                               "subtotales_ok": True}}
    return svc.construir_corrida(alm, "vieja.xlsx", items, "DIURNO", False,
                                 origen=origen)


def test_una_corrida_vieja_se_ve_exactamente_igual(tmp_path):
    alm = _almacen(tmp_path)
    vista = svc.vista_corrida(alm, _corrida_vieja(alm))
    fila = vista["items"][0]
    assert (fila["precio_contractual"], fila["precio_contractual_sin_aiu"]) == (1351, 1056)
    assert (fila["contractual_total"], fila["contractual_total_sin_aiu"]) == (135100, 105600)
    assert vista["totales"]["contractual"] == 135100
    cap = vista["capitulos"][0]
    assert (cap["contractual"], cap["contractual_sin_aiu"]) == (135100, 105600)
    assert vista["origen"]["parser_version"] == "idu-f1/1"
    assert vista["origen"]["conciliacion"]["contractual_con_aiu"] == 135100
```

- [ ] **Step 2: Escribe la regresión del cuadro**

Agrega al final de `tests/test_report_capitulos.py`:

```python
# ------------------------------------------------ corrida vieja (lector idu-f1/1)
# `_item()` por defecto ES una fila vieja: 1351 con AIU en el contractual, 1056 aparte.
_RESUMEN_DE_SIEMPRE = ["Ítem", "Descripción", "Und", "Cantidad",
                       "P. Contractual", "P. Contractual sin AIU",
                       "Costo Unit.", "Margen Unit.", "Margen %",
                       "Total Contractual", "Total Contractual sin AIU",
                       "Total Costo", "Margen Total",
                       "Estado", "Confianza", "APU base"]


def test_corrida_vieja_el_resumen_sale_igual_que_siempre(tmp_path):
    out = tmp_path / "vieja.xlsx"
    write_report([_ens(_item("1", "PRELIMINARES"))], out)
    enc, filas = _tabla(out, "RESUMEN")
    assert enc == _RESUMEN_DE_SIEMPRE
    assert filas[0][4:6] == [1351, 1056]
    assert filas[0][9:13] == [13510, 10560, 9000, 4510]
    assert filas[-2][9:13] == [13510, 10560, 9000, 4510]      # TOTALES


def test_corrida_vieja_la_hoja_de_capitulos_y_el_detalle_salen_igual(tmp_path):
    apus = [_ens(_item("1", "PRELIMINARES"))]
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    write_report(apus, a)
    write_report_categorizado(apus, b)
    enc, filas = _tabla(a, HOJA)
    assert enc == ["Capítulo", "Nombre", "Actividades", "Con APU", "Sin APU",
                   "Contractual", "Contractual sin AIU", "Costo interno",
                   "Diferencia", "Margen %", "Cobertura", "Cobertura $", "Estado"]
    assert filas[-1][5:9] == [13510, 10560, 9000, 4510]       # GRAN TOTAL
    enc, filas = _tabla(b, "DETALLE")
    assert enc == ["Ítem", "Descripción", "Und", "Cantidad",
                   "P. Contractual", "P. Contractual sin AIU",
                   "Costo Unit.", "Margen Unit.", "Margen %",
                   "Total Contractual", "Total Contractual sin AIU",
                   "Total Costo", "Margen Total", "Estado"]
    subtotal = next(f for f in filas if str(f[1] or "").startswith("Subtotal"))
    assert subtotal[9:13] == [13510, 10560, 9000, 4510]
```

(`_tabla` lee las celdas `""` como `None`, y la fila en blanco que agrega `ws.append([])` sí aparece. Por eso TOTALES es `filas[-2]`).

- [ ] **Step 3: Confirma que pasan HOY**

Run: `python -m pytest tests/test_servicio_corridas_capitulos.py tests/test_report_capitulos.py -q`
Expected: PASS. Son candados: si alguno falla hoy, el fixture está mal. Arréglalo antes de seguir, y no toques código de producción.

- [ ] **Step 4: Commit**

```bash
git stash push -q constructor-apus/.obsidian/appearance.json && { git add tests/test_servicio_corridas_capitulos.py tests/test_report_capitulos.py && git commit -q -m "test: candado de regresion — una corrida IDU vieja se ve y se cuadra igual" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
```

---

### Task 2: El lector toma el básico; el valor con AIU solo verifica (`idu-f1/2`)

**Files:**
- Modify: `apu_tool/dominio/presupuesto.py`:
  - docstring del módulo (~l. 16-18);
  - `PARSER_VERSION` (~l. 312);
  - `_Recorrido.__init__` (~l. 404-416);
  - `_agregar_actividad` (~l. 499-521);
  - `errores` (~l. 535-538);
  - `conciliacion` (~l. 550-562);
  - docstring de `read_presupuesto` (~l. 632-634);
  - aviso `oferta_diligenciada` (~l. 719-723).
- Modify: `apu_tool/nucleo/models.py`, solo comentarios (~l. 276-278 y ~l. 396-403).
- Test: `tests/test_presupuesto_idu.py`, `tests/test_presupuesto.py`, `tests/test_presupuesto_idu_regresion.py`, `tests/test_servicio_corridas_capitulos.py`, `tests/test_servicio_previsualizacion.py`.

Las filas del fixture (`tests/fixtures_idu.py`), medidas:
- fila 10 = `1.001`: cantidad 100, básico 1056, con AIU 1351, VALOR TOTAL 135100;
- fila 14 = Subtotal del capítulo 1: 195420.
- Columnas 1-based: 10 = básico, 11 = «incluye AIU», 12 = VALOR TOTAL.
- Contractual sin AIU total: 8.844.098. Con AIU: 11.313.377.

- [ ] **Step 1: Escribe las pruebas nuevas del lector**

Agrega al final de `tests/test_presupuesto_idu.py`:

```python
# ------------------------------------- idu-f1/2: el contractual es el básico sin AIU
import dataclasses  # noqa: E402


def _alterar(tmp_path, fila, columna, valor):
    """El fixture con UNA celda cambiada. Columnas 1-based de Excel: 10 = básico sin
    AIU, 11 = «incluye AIU», 12 = VALOR TOTAL. Fila 10 = la 1.001; fila 14 = el
    Subtotal del capítulo 1."""
    p = escribir_formulario(tmp_path / "f1.xlsx")
    wb = openpyxl.load_workbook(p)
    wb["PROPUESTA ECONÓMICA"].cell(row=fila, column=columna).value = valor
    wb.save(p)
    return leer_formulario_idu(p)


def test_ningun_campo_del_item_trae_el_valor_con_aiu(tmp_path):
    lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
    con_aiu = {a[7] for a in ACTIVIDADES_CAP_1 + ACTIVIDADES_CAP_2}
    for it in lec.items:
        assert it.precio_contractual == it.precio_contractual_sin_aiu
        assert not con_aiu & set(dataclasses.asdict(it).values()), it.item


def test_sin_contractual_salta_con_el_basico_vacio(tmp_path):
    lec = _alterar(tmp_path, 10, 10, None)
    assert any(e.startswith("sin_contractual") and "1.001" in e for e in lec.errores)


def test_con_aiu_ilegible_sale_por_la_verificacion_de_fila(tmp_path):
    # El básico está: no es `sin_contractual`. Pero sin el valor con AIU la fila no
    # cuadra contra su VALOR TOTAL, y eso se avisa.
    lec = _alterar(tmp_path, 10, 11, None)
    assert not any(e.startswith("sin_contractual") for e in lec.errores)
    assert [a.fila for a in lec.advertencias
            if a.tipo == "total_fila_no_concilia"] == [10]
    assert lec.conciliacion["subtotales_ok"] is False


def test_un_valor_total_alterado_sigue_disparando_la_verificacion(tmp_path):
    lec = _alterar(tmp_path, 10, 12, 135101)
    assert [a.fila for a in lec.advertencias
            if a.tipo == "total_fila_no_concilia"] == [10]
    assert lec.errores == []


def test_un_subtotal_alterado_sigue_disparando_la_verificacion(tmp_path):
    lec = _alterar(tmp_path, 14, 12, 195421)        # el Excel dice 195.420
    assert any(a.tipo == "subtotal_no_concilia" for a in lec.advertencias)
    assert lec.conciliacion["subtotales_ok"] is False
    assert lec.conciliacion["diferencia"] == 1
```

`openpyxl`, `escribir_formulario`, `ACTIVIDADES_CAP_1`, `ACTIVIDADES_CAP_2` y `leer_formulario_idu` ya están importados más arriba en el archivo.

- [ ] **Step 2: Ajusta las pruebas que fijan el comportamiento viejo**

En `tests/test_presupuesto_idu.py`:

1. En `test_lee_hoja_encabezado_y_estructura` (~l. 354), cambia
   `assert lec.parser_version == "idu-f1/1"` por
   `assert lec.parser_version == "idu-f1/2"`.

2. Reemplaza entera `test_las_dos_columnas_de_precio` (~l. 395-400) por:
   ```python
   def test_el_contractual_es_el_basico_sin_aiu(tmp_path):
       lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
       replanteo = next(i for i in lec.items if i.item_pago_original == "1.001")
       assert replanteo.cantidad == 100
       assert replanteo.precio_contractual == 1056             # col J, SIN AIU
       assert replanteo.precio_contractual_sin_aiu == 1056     # el mismo valor
       assert replanteo.fila_origen > 0
   ```

3. Reemplaza entera `test_conciliacion_contra_los_subtotales_del_excel` (~l. 404-411) por:
   ```python
   def test_conciliacion_contra_los_subtotales_del_excel(tmp_path):
       # Verifica contra el Excel (con AIU), pero lo que devuelve —y va a
       # origen_json— es el contractual SIN AIU. Ningún total con AIU.
       lec = leer_formulario_idu(escribir_formulario(tmp_path / "f1.xlsx"))
       basico = sum(round(a[5] * a[6]) for a in ACTIVIDADES_CAP_1 + ACTIVIDADES_CAP_2)
       assert lec.conciliacion == {"contractual": basico, "subtotales_ok": True,
                                   "diferencia": 0}
       assert [a for a in lec.advertencias if a.tipo == "total_fila_no_concilia"] == []
   ```

4. En `test_avisa_si_la_oferta_viene_diligenciada` (~l. 456-458), reemplaza las tres últimas líneas por:
   ```python
       # Y NO cambia el contractual: se sigue leyendo el básico oficial (sin AIU).
       assert next(i for i in lec.items
                   if i.item_pago_original == "1.001").precio_contractual == 1056
   ```

En `tests/test_presupuesto.py`, en `test_read_presupuesto_items_y_herencia` (~l. 71-74), reemplaza:
```python
    # El contractual de la ruta IDU es el valor unitario CON AIU (col [10]), que es
    # el que concilia con el VALOR TOTAL del Excel. El basico sin AIU viaja aparte.
    assert exc.precio_contractual == 67153
    assert exc.precio_contractual_sin_aiu == 49473
```
por:
```python
    # Desde idu-f1/2 el contractual de la ruta IDU es el básico SIN AIU (col [9]);
    # la col [10] (con AIU) solo se usa para verificar contra el Excel.
    assert exc.precio_contractual == 49473
    assert exc.precio_contractual_sin_aiu == 49473
```

En `tests/test_presupuesto_idu_regresion.py`:
- Reemplaza las constantes (~l. 19-20):
  ```python
  # Lo que manda desde idu-f1/2. El total con AIU (158.456.072.140) se sigue verificando
  # contra los subtotales del Excel, pero ya no se devuelve.
  CONTRACTUAL_SIN_AIU = 123_871_215_068
  ```
- Reemplaza entera `test_conciliacion_exacta_contra_el_excel` (~l. 69-74):
  ```python
  def test_conciliacion_exacta_contra_el_excel(lectura):
      assert lectura.conciliacion == {"contractual": CONTRACTUAL_SIN_AIU,
                                      "subtotales_ok": True, "diferencia": 0}


  def test_el_contractual_es_el_basico(lectura):
      assert all(i.precio_contractual == i.precio_contractual_sin_aiu
                 for i in lectura.items)
  ```

En `tests/test_servicio_corridas_capitulos.py`:
- En `test_la_vista_trae_el_origen` (~l. 50), cambia `"idu-f1/1"` por `"idu-f1/2"`.
- Reemplaza entera `test_cada_item_trae_su_capitulo_y_las_dos_bases` (~l. 53-63) por:
  ```python
  def test_cada_item_trae_su_capitulo_y_el_contractual_sin_aiu(tmp_path):
      alm = _almacen(tmp_path)
      vista = svc.vista_corrida(alm, _corrida_idu(tmp_path, alm))
      fila = vista["items"][0]
      assert fila["capitulo_codigo"] == "1"
      assert fila["capitulo_nombre"] == "PRELIMINARES"
      assert fila["item_pago_original"] == "1.001"
      assert fila["precio_contractual"] == 1056
      assert fila["precio_contractual_sin_aiu"] == 1056
      assert fila["contractual_total"] == 100 * 1056
      assert fila["contractual_total_sin_aiu"] == 100 * 1056
  ```

En `tests/test_servicio_previsualizacion.py`:
- ~l. 33: `"idu-f1/1"` → `"idu-f1/2"`.
- ~l. 55: `prev["conciliacion"]["contractual_con_aiu"]` → `prev["conciliacion"]["contractual"]`.
- ~l. 116: `"idu-f1/1"` → `"idu-f1/2"`.
- ~l. 121: `assert origen["conciliacion"]["contractual_con_aiu"] > 0` → `assert origen["conciliacion"]["contractual"] > 0`.
- Agrega al final del archivo:
  ```python
  def test_el_origen_no_guarda_ningun_total_con_aiu(tmp_path):
      import pytest
      from apu_tool.dominio.privacy import PrivacyViolation, assert_no_money
      from tests.fixtures_idu import ACTIVIDADES_CAP_1, ACTIVIDADES_CAP_2
      p = escribir_formulario(tmp_path / "f1.xlsx")
      lectura = svc.leer_para_corrida(EntidadOrigen.IDU, p.read_bytes(), "f1.xlsx")
      origen = svc.origen_de(EntidadOrigen.IDU, lectura, "f1.xlsx", "yo@test.co")
      filas = ACTIVIDADES_CAP_1 + ACTIVIDADES_CAP_2
      basico = sum(round(a[5] * a[6]) for a in filas)
      con_aiu = sum(round(a[5] * a[7]) for a in filas)
      assert origen["conciliacion"] == {"contractual": basico, "subtotales_ok": True,
                                        "diferencia": 0}
      assert str(con_aiu) not in json.dumps(origen)
      # Sigue siendo dinero: el objeto entero no cruza hacia la IA.
      with pytest.raises(PrivacyViolation):
          assert_no_money({"corrida": origen})
  ```

- [ ] **Step 3: Confirma que fallan**

Run: `python -m pytest tests/test_presupuesto_idu.py tests/test_presupuesto.py tests/test_servicio_corridas_capitulos.py tests/test_servicio_previsualizacion.py -q`
Expected: FAIL en todas las que esperan `idu-f1/2`, `precio_contractual == 1056` / `49473` o la clave `contractual` de la conciliación. También fallan `test_ningun_campo_del_item_trae_el_valor_con_aiu`, `test_sin_contractual_salta_con_el_basico_vacio` (hoy el básico vacío no es error) y `test_el_origen_no_guarda_ningun_total_con_aiu`. Ya pasan hoy y siguen pasando:
- `test_un_valor_total_alterado_*`, `test_un_subtotal_alterado_*` y `test_con_aiu_ilegible_*` (la parte de fila). Son candados de que la verificación se conserva.
- Las de Task 1. Son el candado de la corrida vieja.

- [ ] **Step 4: Implementa en `apu_tool/dominio/presupuesto.py`**

4a. Docstring del módulo. Reemplaza:
```python
El precio contractual es el **valor unitario CON AIU**, que es el que concilia con el
`VALOR TOTAL` y con los `Subtotal` del propio Excel; el básico sin AIU viaja aparte en
`precio_contractual_sin_aiu`.
```
por:
```python
El precio contractual es el **valor unitario BÁSICO, sin AIU** (desde `idu-f1/2`): el
mismo valor va en `precio_contractual` y en `precio_contractual_sin_aiu`. La columna
«incluye AIU» se lee SOLO para verificar contra el `VALOR TOTAL` y los `Subtotal` del
Excel, que son con AIU, y se descarta: ningún campo la lleva.
```

4b. `PARSER_VERSION` (~l. 312). Reemplaza `PARSER_VERSION = "idu-f1/1"` por:
```python
# idu-f1/1: el contractual era el valor CON AIU. idu-f1/2 (2026-11-25): es el básico sin
# AIU. Va a `corrida.origen_json` y es lo único que distingue una corrida vieja de una
# nueva: no hay migración.
PARSER_VERSION = "idu-f1/2"
```

4c. `_Recorrido.__init__`. Reemplaza:
```python
        self.ignoradas = 0
        self._cap: Optional[Capitulo] = None
```
por:
```python
        self.ignoradas = 0
        # Suma de cantidad × «incluye AIU». SOLO para verificar contra los subtotales
        # del Excel (`conciliacion`); no sale de esta clase.
        self._total_con_aiu = 0
        self._cap: Optional[Capitulo] = None
```

4d. `_agregar_actividad`. Reemplaza:
```python
        con_aiu = _to_float(_val(fila, m.get("unitario_con_aiu")))
        sin_aiu = _to_float(_val(fila, m.get("unitario_sin_aiu")))
        total_excel = _a_entero(_val(fila, m.get("total_excel")))
        recalculado = mul_redondeado(con_aiu, float(cantidad))
        if total_excel and recalculado != total_excel:
```
por:
```python
        # El VALOR TOTAL del Excel es cantidad × «incluye AIU»: con esa columna se
        # verifica la fila, y después se descarta. Lo que entra al ítem es el básico.
        con_aiu = _to_float(_val(fila, m.get("unitario_con_aiu")))
        basico = _to_float(_val(fila, m.get("unitario_sin_aiu")))
        total_excel = _a_entero(_val(fila, m.get("total_excel")))
        recalculado = mul_redondeado(con_aiu, float(cantidad))
        self._total_con_aiu += recalculado
        if total_excel and recalculado != total_excel:
```
y, más abajo en el mismo `LicitacionItem(...)`, reemplaza:
```python
            precio_contractual=con_aiu,
            precio_contractual_sin_aiu=sin_aiu,
```
por:
```python
            precio_contractual=basico,
            # El mismo valor: el campo se mantiene para que las corridas viejas
            # (idu-f1/1, contractual CON AIU) se sigan leyendo igual.
            precio_contractual_sin_aiu=basico,
```

4e. `errores`. Reemplaza:
```python
            errs.append("sin_contractual: estas actividades no traen valor unitario con "
                        f"AIU legible: {', '.join(sin_precio[:10])}.")
```
por:
```python
            errs.append("sin_contractual: estas actividades no traen valor unitario "
                        f"básico (sin AIU) legible: {', '.join(sin_precio[:10])}.")
```
(`total_no_concilia` no cambia de código: `_contractual` suma `precio_contractual`, que ahora es el básico. Es lo que pide el spec.)

4f. `conciliacion`. Reemplaza el método entero:
```python
    def conciliacion(self) -> dict:
        con = self._contractual(self.items)
        sin = sum(mul_redondeado(i.precio_contractual_sin_aiu, i.cantidad)
                  for i in self.items)
        suma_sub = sum(self.subtotales)
        if self.subtotales and suma_sub != con:
            self.avisos.append(Advertencia(
                "subtotal_no_concilia", 0,
                f"Los subtotales del Excel suman {suma_sub:,} y las actividades {con:,}."))
        return {"contractual_con_aiu": con, "contractual_sin_aiu": sin,
                "subtotales_excel": suma_sub,
                "diferencia": (suma_sub - con) if self.subtotales else 0,
                "subtotales_ok": (not self.subtotales) or suma_sub == con}
```
por:
```python
    def conciliacion(self) -> dict:
        """La verificación contra el Excel, y lo único de ella que se guarda.

        Los `Subtotal` del Formulario 1 suman cantidad × «incluye AIU», así que se
        comparan contra esa suma (`_total_con_aiu`). Esa suma NO se devuelve: el dict
        va a `origen_json`, y ahí solo queda el contractual sin AIU, si cuadró y la
        diferencia en pesos si no.
        """
        suma_sub = sum(self.subtotales)
        con_aiu = self._total_con_aiu
        ok = (not self.subtotales) or suma_sub == con_aiu
        if not ok:
            self.avisos.append(Advertencia(
                "subtotal_no_concilia", 0,
                f"Los subtotales del Excel suman {suma_sub:,} y las actividades "
                f"{con_aiu:,} (con AIU, como el Excel)."))
        return {"contractual": self._contractual(self.items),
                "subtotales_ok": ok,
                "diferencia": (suma_sub - con_aiu) if self.subtotales else 0}
```
Deja el literal `Advertencia(` seguido de `"subtotal_no_concilia"` así: `test_el_vocabulario_de_advertencias_solo_promete_lo_que_emite` lo busca con una regex.

4g. Docstring de `read_presupuesto`. Reemplaza:
```python
    OJO: el `precio_contractual` que devuelve ahora es el valor unitario CON AIU (la
    columna que concilia con el VALOR TOTAL del Excel), no el básico sin AIU que usaba
    la versión anterior. El básico viaja aparte, en `precio_contractual_sin_aiu`.
```
por:
```python
    OJO: el `precio_contractual` que devuelve es el valor unitario BÁSICO, sin AIU
    (lector `idu-f1/2`), y `precio_contractual_sin_aiu` trae el mismo valor. El valor
    con AIU solo se usa para verificar el archivo contra el Excel y no se devuelve.
```

4h. Aviso de oferta. Reemplaza:
```python
            f"Esta versión NO las lee: el contractual sale del valor unitario oficial "
            f"con AIU."))
```
por:
```python
            f"Esta versión NO las lee: el contractual sale del valor unitario básico "
            f"oficial (sin AIU)."))
```

- [ ] **Step 5: Actualiza los comentarios de `apu_tool/nucleo/models.py`**

En `LicitacionItem` (~l. 276-278), reemplaza:
```python
    # Valor unitario SIN AIU. Es DINERO: va a privacy._FORBIDDEN_KEYS y NO viaja en
    # licitacion_item_to_dict. `precio_contractual` sigue siendo el que manda (con AIU).
    precio_contractual_sin_aiu: float = 0.0
```
por:
```python
    # Valor unitario básico SIN AIU. Es DINERO: va a privacy._FORBIDDEN_KEYS y NO viaja
    # en licitacion_item_to_dict. Desde el lector idu-f1/2 es el MISMO valor que
    # `precio_contractual`; en una corrida vieja (idu-f1/1) `precio_contractual` es el
    # CON AIU y este es el básico. 0 en una corrida plana.
    precio_contractual_sin_aiu: float = 0.0
```
En `AssembledApu.contractual_total_sin_aiu` (~l. 397-402), reemplaza el docstring por:
```python
        """El contractual del ítem sin AIU. Misma regla de redondeo que su gemelo.

        Igual a `contractual_total` en una corrida IDU nueva (lector idu-f1/2); distinto
        en una vieja (idu-f1/1), donde `precio_contractual` es el CON AIU. 0 en una
        corrida que no venga del IDU.
        """
```

- [ ] **Step 6: Confirma que pasan**

Run: `python -m pytest tests/test_presupuesto_idu.py tests/test_presupuesto.py tests/test_presupuesto_idu_regresion.py tests/test_servicio_corridas_capitulos.py tests/test_servicio_previsualizacion.py tests/test_report_capitulos.py tests/test_privacy.py tests/test_api_idu.py tests/test_entrada_entidad.py -q`
Expected: PASS. `test_presupuesto_idu_regresion.py` sale *skipped* si `APU_IDU_F1_XLSX` no está definida. Si tienes el archivo real, córrela con la variable puesta: tiene que dar 123.871.215.068 exacto.

- [ ] **Step 7: Commit**

```bash
git stash push -q constructor-apus/.obsidian/appearance.json && { git add apu_tool/dominio/presupuesto.py apu_tool/nucleo/models.py tests/test_presupuesto_idu.py tests/test_presupuesto.py tests/test_presupuesto_idu_regresion.py tests/test_servicio_corridas_capitulos.py tests/test_servicio_previsualizacion.py && git commit -q -m "feat(idu): el contractual es el basico sin AIU; el AIU solo verifica contra el Excel (idu-f1/2)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
```

---

### Task 3: La previa trae una sola base del contractual

Con el lector nuevo, `contractual_sin_aiu` de la previa es **siempre** igual a `contractual`: la previa lee el archivo en el momento, así que nunca es una corrida vieja. Se saca para no mandar dos veces el mismo número.

**Files:**
- Modify: `apu_tool/servicio/corridas.py`: `previsualizar` (~l. 160-163) y `_capitulos_de_lectura` (~l. 191-206).
- Test: `tests/test_servicio_previsualizacion.py`

- [ ] **Step 1: Ajusta las pruebas**

En `test_previsualizar_devuelve_capitulos_totales_y_conciliacion` (~l. 38), reemplaza
`assert prev["capitulos"][0]["contractual_sin_aiu"] > 0` por:
```python
    # Una sola base: en una lectura nueva el «sin AIU» sería el mismo número.
    assert "contractual_sin_aiu" not in prev["capitulos"][0]
```
En `test_el_total_de_la_previa_es_la_suma_de_sus_capitulos` (~l. 50-55), reemplaza el cuerpo después de `prev = ...` por:
```python
    assert prev["totales"] == {"contractual": sum(
        c["contractual"] for c in prev["capitulos"])}
    # Y con lo que el parser verificó contra el Excel.
    assert prev["totales"]["contractual"] == prev["conciliacion"]["contractual"]
```

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_servicio_previsualizacion.py -q`
Expected: FAIL en esas dos (todavía viaja `contractual_sin_aiu`).

- [ ] **Step 3: Implementa en `apu_tool/servicio/corridas.py`**

En `previsualizar`, reemplaza:
```python
        "totales": {
            "contractual": sum(c["contractual"] for c in capitulos),
            "contractual_sin_aiu": sum(c["contractual_sin_aiu"] for c in capitulos),
        },
```
por:
```python
        # Una sola base: desde idu-f1/2 el contractual YA es el sin AIU.
        "totales": {"contractual": sum(c["contractual"] for c in capitulos)},
```
En `_capitulos_de_lectura`, reemplaza:
```python
    for cap in lectura.capitulos:
        por_codigo[cap.codigo] = {**cap.to_dict(), "actividades": 0,
                                  "contractual": 0, "contractual_sin_aiu": 0}
    for it in lectura.items:
        fila = por_codigo.get(it.capitulo_codigo)
        if fila is None:
            fila = por_codigo.setdefault(it.capitulo_codigo, {
                "codigo": it.capitulo_codigo,
                "nombre": it.capitulo_nombre or "(sin capítulo)",
                "orden": len(por_codigo) + 1, "fila_origen": 0,
                "actividades": 0, "contractual": 0, "contractual_sin_aiu": 0})
        fila["actividades"] += 1
        fila["contractual"] += mul_redondeado(it.precio_contractual, it.cantidad)
        fila["contractual_sin_aiu"] += mul_redondeado(
            it.precio_contractual_sin_aiu, it.cantidad)
    return list(por_codigo.values())
```
por:
```python
    for cap in lectura.capitulos:
        por_codigo[cap.codigo] = {**cap.to_dict(), "actividades": 0, "contractual": 0}
    for it in lectura.items:
        fila = por_codigo.get(it.capitulo_codigo)
        if fila is None:
            fila = por_codigo.setdefault(it.capitulo_codigo, {
                "codigo": it.capitulo_codigo,
                "nombre": it.capitulo_nombre or "(sin capítulo)",
                "orden": len(por_codigo) + 1, "fila_origen": 0,
                "actividades": 0, "contractual": 0})
        fila["actividades"] += 1
        fila["contractual"] += mul_redondeado(it.precio_contractual, it.cantidad)
    return list(por_codigo.values())
```
`vista_corrida` y `_vista_item` **no** se tocan: siguen mandando `precio_contractual_sin_aiu` y `contractual_total_sin_aiu`, que es lo que hace falta para que una corrida vieja se vea igual (Task 1).

- [ ] **Step 4: Confirma que pasan**

Run: `python -m pytest tests/test_servicio_previsualizacion.py tests/test_servicio_corridas_capitulos.py tests/test_api_idu.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git stash push -q constructor-apus/.obsidian/appearance.json && { git add apu_tool/servicio/corridas.py tests/test_servicio_previsualizacion.py && git commit -q -m "feat(previa): la previsualizacion trae una sola base del contractual" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
```

---

### Task 4: El cuadro muestra la columna aparte «sin AIU» solo cuando difiere

La regla es **por datos**. La columna aparte sale si algún ítem trae `precio_contractual_sin_aiu != precio_contractual`, sin leer `origen_json`, que el cuadro no recibe. Eso cubre tres casos:
- **Corrida IDU vieja:** con ≠ sin. Sale como hoy.
- **Corrida plana:** básico en 0. Sale como hoy, con la columna en cero, igual que siempre.
- **Corrida IDU nueva:** con == sin. Una sola columna, rotulada «(sin AIU)».

Sin ítems, el cuadro de siempre.

La implementación escribe las hojas igual que hoy y, si la columna sobra, la borra con `ws.delete_cols`. Esa llamada corre valores **y** estilos, así que los formatos puestos por índice quedan en su celda. Los anchos se corren a mano. Es el diff más corto y no toca los índices de los bucles de formato.

**Files:**
- Modify: `apu_tool/dominio/report.py`: dos funciones nuevas antes de `_build_resumen` (~l. 59) y el final de `_build_resumen` (~l. 116-117).
- Modify: `apu_tool/dominio/report_categorizado.py`: import (~l. 22-24), final de `escribir_hoja_capitulos` (~l. 157-158) y final de `_build_detalle` (~l. 214-215).
- Test: `tests/test_report_capitulos.py`

- [ ] **Step 1: Escribe las pruebas que fallan**

Agrega al final de `tests/test_report_capitulos.py`:

```python
# --------------------------------------- idu-f1/2: una sola base del contractual
def _nuevo(cap_cod="1", cap_nom="PRELIMINARES", item="1.001"):
    """Ítem leído con el lector idu-f1/2: el contractual YA es el básico sin AIU."""
    return _item(cap_cod, cap_nom, con_aiu=1056.0, sin_aiu=1056.0, item=item)


def test_hay_columna_sin_aiu_se_decide_por_datos():
    from apu_tool.dominio.report import hay_columna_sin_aiu
    nueva = _ens(_nuevo())
    assert hay_columna_sin_aiu([nueva]) is False
    assert hay_columna_sin_aiu([_ens(_item("1", "PRELIMINARES"))]) is True   # vieja
    assert hay_columna_sin_aiu([_ens(_item(sin_aiu=0.0))]) is True           # plana
    # Una línea agregada a una corrida nueva trae básico 0: la columna vuelve.
    assert hay_columna_sin_aiu([nueva, _ens(_item(sin_aiu=0.0, item="9"))]) is True
    assert hay_columna_sin_aiu([]) is True                 # sin ítems: lo de siempre


def test_corrida_nueva_el_resumen_trae_una_sola_columna_de_contractual(tmp_path):
    out = tmp_path / "nueva.xlsx"
    write_report([_ens(_nuevo())], out)
    enc, filas = _tabla(out, "RESUMEN")
    assert enc == ["Ítem", "Descripción", "Und", "Cantidad",
                   "P. Contractual (sin AIU)", "Costo Unit.", "Margen Unit.",
                   "Margen %", "Total Contractual (sin AIU)", "Total Costo",
                   "Margen Total", "Estado", "Confianza", "APU base"]
    assert filas[0][4] == 1056
    assert filas[0][8:11] == [10560, 9000, 1560]
    assert filas[-2][8:11] == [10560, 9000, 1560]             # TOTALES
    assert abs(filas[-1][10] - 1560 / 10560) < 1e-9           # MARGEN % GLOBAL
    ws = openpyxl.load_workbook(out)["RESUMEN"]
    assert ws.cell(row=2, column=10).number_format == "#,##0"  # Total Costo
    assert ws.cell(row=2, column=8).number_format == "0.0%"    # Margen %


def test_corrida_nueva_capitulos_y_detalle_sin_columna_aparte(tmp_path):
    apus = [_ens(_nuevo()), _ens(_nuevo("2", "PAVIMENTOS", item="2.001"))]
    a, b = tmp_path / "a.xlsx", tmp_path / "b.xlsx"
    write_report(apus, a)
    write_report_categorizado(apus, b)
    enc, filas = _tabla(a, HOJA)
    assert enc == ["Capítulo", "Nombre", "Actividades", "Con APU", "Sin APU",
                   "Contractual (sin AIU)", "Costo interno", "Diferencia",
                   "Margen %", "Cobertura", "Cobertura $", "Estado"]
    assert filas[-1][5:8] == [21120, 18000, 3120]             # GRAN TOTAL
    assert _tabla(a, HOJA) == _tabla(b, HOJA)                 # la misma hoja en los dos
    enc, filas = _tabla(b, "DETALLE")
    assert enc == ["Ítem", "Descripción", "Und", "Cantidad",
                   "P. Contractual (sin AIU)", "Costo Unit.", "Margen Unit.",
                   "Margen %", "Total Contractual (sin AIU)", "Total Costo",
                   "Margen Total", "Estado"]
    subtotales = [f for f in filas if str(f[1] or "").startswith("Subtotal")]
    assert [f[8:11] for f in subtotales] == [[10560, 9000, 1560]] * 2
```

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_report_capitulos.py -q`
Expected: FAIL. La primera falla con `ImportError: cannot import name 'hay_columna_sin_aiu'` y las otras dos por los encabezados. Las de Task 1 siguen en PASS.

- [ ] **Step 3: Implementa en `apu_tool/dominio/report.py`**

Agrega justo antes de `def _build_resumen(`:
```python
def hay_columna_sin_aiu(apus: list[AssembledApu]) -> bool:
    """¿Va la columna aparte «sin AIU»? Se decide POR DATOS, sin leer `origen_json`.

    Sí cuando algún ítem trae un básico distinto del contractual: una corrida vieja
    de la ruta IDU (lector `idu-f1/1`, contractual CON AIU) o una plana (básico en 0,
    como siempre). No en una corrida IDU nueva (`idu-f1/2`): ahí el contractual YA es
    el básico y la columna repetiría la principal. Sin ítems, el cuadro de siempre.
    """
    return not apus or any(
        a.item.precio_contractual_sin_aiu != a.item.precio_contractual for a in apus)


def _sin_columna_aparte(ws, columnas: tuple[int, ...], anchos: list[int],
                        rotulos: tuple[str, ...]) -> None:
    """Corrida IDU nueva: quita las columnas «sin AIU» (1-based) ya escritas y le
    agrega «(sin AIU)» al rótulo del contractual que queda.

    `delete_cols` corre los valores Y los estilos de las celdas, así que los formatos
    y rellenos que se pusieron por índice siguen en su lugar. Los anchos no se corren
    solos: `anchos` (uno por columna, en orden) se edita en el lugar.
    """
    for col in sorted(columnas, reverse=True):
        ws.delete_cols(col)
        del anchos[col - 1]
    for celda in ws[1]:
        if celda.value in rotulos:
            celda.value = f"{celda.value} (sin AIU)"
```
Al final de `_build_resumen`, reemplaza:
```python
    _autosize(ws, {1: 8, 2: 50, 3: 6, 4: 12, 5: 16, 6: 20, 7: 14, 8: 14, 9: 10,
                   10: 18, 11: 20, 12: 16, 13: 16, 14: 12, 15: 10, 16: 10})
```
por:
```python
    anchos = [8, 50, 6, 12, 16, 20, 14, 14, 10, 18, 20, 16, 16, 12, 10, 10]
    if not hay_columna_sin_aiu(apus):
        _sin_columna_aparte(ws, (6, 11), anchos, ("P. Contractual", "Total Contractual"))
    _autosize(ws, dict(enumerate(anchos, start=1)))
```

- [ ] **Step 4: Implementa en `apu_tool/dominio/report_categorizado.py`**

Reemplaza el import:
```python
from apu_tool.dominio.report import (_MONEY, _PCT, _REND, _STATUS_LABEL, _TOTAL_FILL,
                                     _WARN_FILL, _ALERT_FILL, _autosize, _style_header,
                                     _build_desviaciones)
```
por:
```python
from apu_tool.dominio.report import (_MONEY, _PCT, _REND, _STATUS_LABEL, _TOTAL_FILL,
                                     _WARN_FILL, _ALERT_FILL, _autosize, _style_header,
                                     _build_desviaciones, _sin_columna_aparte,
                                     hay_columna_sin_aiu)
```
(No hay ciclo nuevo: este módulo ya importaba de `report.py`, y `report.py` lo importa a él solo **dentro** de `write_report`.)

Al final de `escribir_hoja_capitulos`, reemplaza:
```python
    _autosize(ws, {1: 10, 2: 42, 3: 12, 4: 10, 5: 10, 6: 18, 7: 20, 8: 16,
                   9: 16, 10: 10, 11: 11, 12: 12, 13: 12})
```
por:
```python
    anchos = [10, 42, 12, 10, 10, 18, 20, 16, 16, 10, 11, 12, 12]
    if not hay_columna_sin_aiu(apus):
        _sin_columna_aparte(ws, (7,), anchos, ("Contractual",))
    _autosize(ws, dict(enumerate(anchos, start=1)))
```
Al final de `_build_detalle`, reemplaza:
```python
    _autosize(ws, {1: 9, 2: 46, 3: 6, 4: 12, 5: 16, 6: 20, 7: 14, 8: 14, 9: 10,
                   10: 18, 11: 20, 12: 16, 13: 16, 14: 12})
```
por:
```python
    anchos = [9, 46, 6, 12, 16, 20, 14, 14, 10, 18, 20, 16, 16, 12]
    if not hay_columna_sin_aiu([a for filas in grupos.values() for a in filas]):
        _sin_columna_aparte(ws, (6, 11), anchos, ("P. Contractual", "Total Contractual"))
    _autosize(ws, dict(enumerate(anchos, start=1)))
```
`resumen_por_capitulo` **no** se toca: sigue devolviendo `contractual_sin_aiu`, que la hoja vieja necesita y la nueva borra.

- [ ] **Step 5: Confirma que pasan**

Run: `python -m pytest tests/test_report_capitulos.py tests/test_resumen_capitulo.py tests/test_report_alertas_costeo.py tests/test_report_categorizado_alertas.py tests/test_servicio_corridas_lista.py tests/test_transporte_corridas.py tests/test_privacy.py -q`
Expected: PASS. Las de `test_report_alertas_costeo.py` y `test_report_categorizado_alertas.py` usan ítems planos (básico 0), así que la columna sigue y sus índices fijos (`column=5`, `column=6`, `column=7`) no se corren.

- [ ] **Step 6: Commit**

```bash
git stash push -q constructor-apus/.obsidian/appearance.json && { git add apu_tool/dominio/report.py apu_tool/dominio/report_categorizado.py tests/test_report_capitulos.py && git commit -q -m "feat(cuadro): la columna aparte sin AIU solo cuando difiere del contractual" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
```

---

### Task 5: El chat marca «(con AIU)» en las corridas viejas; prompt `consulta/v2`

`vista_corrida(...)["origen"]` es `meta.origen`: el dict de `origen_json`, o `None`. Solo la ruta IDU lo escribe (`rutas.crear_corrida` pasa `origen=None` para las demás entidades). Por eso basta con mirar `parser_version`. Una corrida plana trae `None` y no lleva nota. La nota va en `contractual`, `diferencia` y `margen`, **no** en `costo`: el costo interno no lleva AIU en ninguna corrida.

**Files:**
- Modify: `apu_tool/servicio/consulta.py`: constantes (~l. 26-35), `_corrida` (~l. 132-151), `_capitulo` (~l. 153-172).
- Modify: `apu_tool/dominio/ai_assist.py`: `PROMPT_VERSION_CONSULTA` (~l. 351) y la regla del AIU en `_SISTEMA_CONSULTA` (~l. 395-397).
- Test: `tests/test_consulta_resolver.py`, `tests/test_consulta_chat_motor.py`

- [ ] **Step 1: Escribe las pruebas que fallan**

En `tests/test_consulta_resolver.py`, agrega `import json` justo antes de `import logging` (~l. 3). Al final del archivo, agrega:

```python
# ------------------------------------------- corridas viejas del IDU (idu-f1/1)
def _origen(alm, cid, version):
    alm.corridas.set_origen(cid, json.dumps({"entidad": "IDU",
                                             "parser_version": version}))


def test_corrida_vieja_del_idu_dice_con_aiu_menos_en_el_costo(base):
    alm, ids = base
    cid = ids["cali"]
    _origen(alm, cid, "idu-f1/1")
    t = vista_corrida(alm, cid)["totales"]
    assert resolver(alm, f"{{{{contractual:corrida:{cid}}}}}") == \
        pesos(t["contractual"]) + " (con AIU)"
    assert resolver(alm, f"{{{{diferencia:corrida:{cid}}}}}") == \
        pesos(t["margen"]) + " (con AIU)"
    assert resolver(alm, f"{{{{margen:corrida:{cid}}}}}") == \
        pct(t["margen_pct"]) + " (con AIU)"
    # El costo interno es costo directo en toda corrida: nunca lleva la nota.
    assert resolver(alm, f"{{{{costo:corrida:{cid}}}}}") == pesos(t["costo"])


def test_capitulo_de_una_corrida_vieja_dice_con_aiu(base):
    alm, ids = base
    cid = ids["calle13"]
    _origen(alm, cid, "idu-f1/1")
    cap = next(c for c in vista_corrida(alm, cid)["capitulos"] if c["codigo"] == "1")
    assert resolver(alm, f"{{{{contractual:capitulo:{cid}:1}}}}") == \
        pesos(cap["contractual"]) + " (con AIU)"
    assert resolver(alm, f"{{{{costo:capitulo:{cid}:1}}}}") == pesos(cap["costo"])


def test_corrida_nueva_del_idu_no_lleva_nota(base):
    alm, ids = base
    cid = ids["cali"]
    _origen(alm, cid, "idu-f1/2")
    t = vista_corrida(alm, cid)["totales"]
    assert resolver(alm, f"{{{{contractual:corrida:{cid}}}}}") == pesos(t["contractual"])
    assert "AIU" not in resolver(alm, f"{{{{margen:corrida:{cid}}}}}")
```

(En `tests/consulta_base.py`, la Cali es una sola fila costeada y el capítulo 1 de la Calle 13 está completo: ninguna de las dos lleva nota de «parcial», y eso lo prueban `test_totales_de_corrida_son_los_de_la_vista` y `test_capitulos`.)

En `tests/test_consulta_chat_motor.py` (~l. 33), cambia
`assert eventos[-1][1]["prompt_version"] == "consulta/v1"` por
`assert eventos[-1][1]["prompt_version"] == "consulta/v2"`.

- [ ] **Step 2: Confirma que fallan**

Run: `python -m pytest tests/test_consulta_resolver.py tests/test_consulta_chat_motor.py -q`
Expected: FAIL en las dos de «(con AIU)» y en la de `consulta/v2`. `test_corrida_nueva_del_idu_no_lleva_nota` pasa ya.

- [ ] **Step 3: Implementa en `apu_tool/servicio/consulta.py`**

Agrega justo después de `MAX_CORRIDAS_POR_RESPUESTA = 5`:
```python
# Corridas leídas con el lector viejo del IDU: su contractual LLEVA AIU (antes del
# 2026-11-25 el IDU se leía así). El costo interno es costo directo, así que esas
# cifras se marcan para que nadie las compare sin darse cuenta. Spec:
# docs/superpowers/specs/2026-11-25-contractual-sin-aiu-design.md
PARSER_CON_AIU = "idu-f1/1"
CON_AIU = " (con AIU)"
```
Agrega, después de `def _costeada(...)` y antes de `class _Resolutor`:
```python
def _nota_aiu(v: dict, campo: str) -> str:
    """« (con AIU)» en contractual, diferencia y margen de una corrida vieja del IDU.
    `v["origen"]` es `origen_json` ya parseado, o None (corrida plana)."""
    if campo == "costo":
        return ""
    return CON_AIU if (v.get("origen") or {}).get("parser_version") == PARSER_CON_AIU \
        else ""
```
En `_corrida`, reemplaza:
```python
        s = _fmt(campo, v["totales"][_CAMPOS_CORRIDA[campo]])
```
por:
```python
        s = _fmt(campo, v["totales"][_CAMPOS_CORRIDA[campo]]) + _nota_aiu(v, campo)
```
En `_capitulo`, reemplaza:
```python
        s = _fmt(campo, cap[_CAMPOS_CAPITULO[campo]])
```
por:
```python
        s = _fmt(campo, cap[_CAMPOS_CAPITULO[campo]]) + _nota_aiu(v, campo)
```

- [ ] **Step 4: Implementa en `apu_tool/dominio/ai_assist.py`**

Cambia `PROMPT_VERSION_CONSULTA = "consulta/v1"` por `PROMPT_VERSION_CONSULTA = "consulta/v2"` y deja el comentario de la línea como está.

En `_SISTEMA_CONSULTA`, reemplaza:
```
- Los precios y costos de insumos y APUs son de la lista Principal. El costo interno
  no lleva AIU; el contractual de una licitación del IDU sí lo lleva. Dilo cuando
  compares contractual con costo.
```
por:
```
- Los precios y costos de insumos y APUs son de la lista Principal. El costo interno
  es costo directo, sin AIU, y el contractual también, así que se comparan tal cual.
  Algunas corridas viejas del IDU tienen el contractual con AIU: en esas, el sistema
  le agrega «(con AIU)» a la cifra cuando reemplaza el marcador. Tú no lo escribes
  ni lo adivinas.
```
(El modelo nunca ve la nota, porque el historial vuelve con el `crudo`. La regla solo evita que siga diciendo «el contractual del IDU lleva AIU».)

- [ ] **Step 5: Confirma que pasan**

Run: `python -m pytest tests/test_consulta_resolver.py tests/test_consulta_chat_motor.py tests/test_consulta_advisor.py tests/test_consulta_chat_herramientas.py tests/test_api_consulta_chat.py tests/test_privacy_consulta.py tests/test_servicio_privacidad.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git stash push -q constructor-apus/.obsidian/appearance.json && { git add apu_tool/servicio/consulta.py apu_tool/dominio/ai_assist.py tests/test_consulta_resolver.py tests/test_consulta_chat_motor.py && git commit -q -m "feat(consulta): (con AIU) en las cifras de corridas idu-f1/1; prompt consulta/v2" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
```

---

### Task 6: La previa web muestra el contractual sin AIU y la verificación

**Files:**
- Modify: `web/src/lib/tipos.ts`: `precio_contractual_sin_aiu` de la fila (~l. 277), `CapituloPrevia` (~l. 830-838) y `PreviaPresupuesto` (~l. 851-857).
- Modify: `web/src/components/corrida/PreviaIdu.tsx`: líneas ~46-60 y la tabla (~l. 102-141).
- Test: `web/src/components/corrida/PreviaIdu.test.tsx`

- [ ] **Step 1: Ajusta el fixture y escribe la prueba que falla**

En `web/src/components/corrida/PreviaIdu.test.tsx`, reemplaza `BASE` (~l. 6-28) por el de una lectura nueva, con las cifras sin AIU del archivo de referencia:
```tsx
const BASE: PreviaPresupuesto = {
  entidad: "IDU",
  formato: "idu_formulario_1",
  archivo: "f1.xlsx",
  hoja: "PROPUESTA ECONÓMICA",
  fila_encabezado: 10,
  parser_version: "idu-f1/2",
  capitulos: [
    { codigo: "1", nombre: "PRELIMINARES", orden: 1, fila_origen: 13,
      actividades: 2, contractual: 107565459 },
    { codigo: "2", nombre: "PAVIMENTOS", orden: 2, fila_origen: 21,
      actividades: 42, contractual: 29037106963 },
  ],
  actividades: 1939,
  filas_ignoradas: 804,
  totales: { contractual: 123871215068 },
  conciliacion: { contractual: 123871215068, subtotales_ok: true, diferencia: 0 },
  errores: [],
  advertencias: [],
  filas_senaladas: [],
  puede_aprobar: true,
  requiere_confirmacion: true,
};
```
Reemplaza el test `"lista los capítulos con su contractual en formato colombiano"` por:
```tsx
  it("lista los capítulos con su contractual en formato colombiano", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText("PRELIMINARES")).toBeTruthy();
    expect(screen.getByText("$107.565.459")).toBeTruthy();
  });

  it("muestra el contractual sin AIU y la verificación, sin ninguna cifra con AIU", () => {
    render(<PreviaIdu {...props(BASE)} />);
    expect(screen.getByText("Contractual (sin AIU) $123.871.215.068")).toBeTruthy();
    expect(screen.getByText("Verificación contra el Excel: OK.")).toBeTruthy();
    expect(screen.getByRole("columnheader", { name: "Contractual (sin AIU)" }))
      .toBeTruthy();
    expect(screen.getAllByRole("columnheader")).toHaveLength(4);
    expect(screen.queryByText(/con AIU|c\/AIU|s\/AIU/)).toBeNull();
  });
```
El test `"avisa cuando la conciliación contra el Excel no cuadra"` no cambia: sigue buscando `/no cuadra/i`.

- [ ] **Step 2: Confirma que falla**

Run: `cd web && npx vitest run src/components/corrida/PreviaIdu.test.tsx`
Expected: FAIL en `"muestra el contractual sin AIU…"`: hoy dice «Contractual (con AIU)…» y la tabla tiene 5 columnas.

- [ ] **Step 3: Implementa `web/src/lib/tipos.ts`**

En la fila de la corrida (~l. 277), reemplaza:
```ts
  /** Valor unitario básico SIN AIU. `precio_contractual` es el que INCLUYE AIU. */
```
por:
```ts
  /** Valor unitario básico SIN AIU. En una corrida IDU nueva (lector idu-f1/2) es igual a
   *  `precio_contractual`; en una vieja (idu-f1/1), `precio_contractual` es el CON AIU. */
```
Reemplaza `CapituloPrevia`:
```ts
export interface CapituloPrevia {
  codigo: string;
  nombre: string;
  orden: number;
  fila_origen: number;
  actividades: number;
  contractual: number;
  contractual_sin_aiu: number;
}
```
por:
```ts
export interface CapituloPrevia {
  codigo: string;
  nombre: string;
  orden: number;
  fila_origen: number;
  actividades: number;
  /** Contractual SIN AIU: desde el lector idu-f1/2 es el único que hay. */
  contractual: number;
}
```
En `PreviaPresupuesto`, reemplaza:
```ts
  totales: { contractual: number; contractual_sin_aiu: number };
  conciliacion: {
    contractual_con_aiu?: number;
    contractual_sin_aiu?: number;
    subtotales_excel?: number;
    diferencia?: number;
    subtotales_ok?: boolean;
  };
```
por:
```ts
  totales: { contractual: number };
  /** Verificación contra el Excel. Ningún total con AIU: el contractual sin AIU, si
   *  los subtotales cuadraron y la diferencia en pesos si no. */
  conciliacion: {
    contractual?: number;
    diferencia?: number;
    subtotales_ok?: boolean;
  };
```

- [ ] **Step 4: Implementa `web/src/components/corrida/PreviaIdu.tsx`**

Reemplaza:
```tsx
      <p className="mt-1 text-xs">
        Contractual (con AIU) {cop(previa.totales.contractual)} · sin AIU{" "}
        {cop(previa.totales.contractual_sin_aiu)}
      </p>
```
por:
```tsx
      <p className="mt-1 text-xs">
        Contractual (sin AIU) {cop(previa.totales.contractual)}
      </p>
```
Reemplaza:
```tsx
        {conciliacionOk
          ? "Conciliación contra el Excel: cuadra."
          : `Conciliación contra el Excel: no cuadra (diferencia ${cop(
              previa.conciliacion.diferencia ?? 0,
            )}).`}
```
por:
```tsx
        {conciliacionOk
          ? "Verificación contra el Excel: OK."
          : `Verificación contra el Excel: no cuadra (diferencia ${cop(
              previa.conciliacion.diferencia ?? 0,
            )}).`}
```
En la tabla, reemplaza:
```tsx
                <th scope="col" className="p-1 text-right">Contractual (c/AIU)</th>
                <th scope="col" className="p-1 text-right">Contractual (s/AIU)</th>
```
por:
```tsx
                <th scope="col" className="p-1 text-right">Contractual (sin AIU)</th>
```
Reemplaza:
```tsx
                  <td className="p-1 text-right tabular-nums">{cop(c.contractual)}</td>
                  <td className="p-1 text-right tabular-nums">
                    {cop(c.contractual_sin_aiu)}
                  </td>
```
por:
```tsx
                  <td className="p-1 text-right tabular-nums">{cop(c.contractual)}</td>
```
Y en el `tfoot`, reemplaza:
```tsx
                <td className="p-1 text-right tabular-nums">
                  {cop(previa.totales.contractual)}
                </td>
                <td className="p-1 text-right tabular-nums">
                  {cop(previa.totales.contractual_sin_aiu)}
                </td>
```
por:
```tsx
                <td className="p-1 text-right tabular-nums">
                  {cop(previa.totales.contractual)}
                </td>
```
El total sigue viniendo del backend (`previa.totales.contractual`): el frontend no suma dinero.

- [ ] **Step 5: Confirma que pasan y que compila**

Run: `cd web && npx vitest run src/components/corrida src/pages/CorridasInicio.idu.test.tsx && npm run build`
Expected: PASS y build sin errores de tipos. Si `tsc -b` se queja de `contractual_sin_aiu` en algún otro archivo, búscalo con `grep -rn "contractual_sin_aiu" web/src --include=*.tsx --include=*.ts`. Hoy solo lo usaban `PreviaIdu.tsx` y `tipos.ts`.

- [ ] **Step 6: Commit**

```bash
git stash push -q constructor-apus/.obsidian/appearance.json && { git add web/src/lib/tipos.ts web/src/components/corrida/PreviaIdu.tsx web/src/components/corrida/PreviaIdu.test.tsx && git commit -q -m "feat(web): la previa muestra el contractual sin AIU y la verificacion contra el Excel" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
```

---

### Task 7: Documentación en `CLAUDE.md`

**Files:**
- Modify: `CLAUDE.md`: «Las dos bases del contractual» (~l. 435-441), «Chat de consulta (2026-11)» (~l. 288-327) y «No hacer».

- [ ] **Step 1: Reescribe «Las dos bases del contractual»**

Reemplaza el bullet entero, desde `- **Las dos bases del contractual.**` hasta `158.456.072.140 con AIU, 123.871.215.068 sin AIU.`, por:
```markdown
- **El contractual del IDU es el SIN AIU (2026-11-25, lector `idu-f1/2`).** En una
  corrida nueva de la ruta IDU, `precio_contractual` es el **valor unitario BÁSICO, sin
  AIU** (col J del Formulario 1), comparable con el costo interno, que es costo directo;
  `precio_contractual_sin_aiu` lleva el mismo valor y **no hay ningún campo con AIU**. La
  columna «incluye AIU» (col K) sigue siendo obligatoria y se lee fila por fila **solo**
  para verificar el archivo contra el `VALOR TOTAL` y los `Subtotal` del Excel (que son
  con AIU): `total_fila_no_concilia`, `subtotal_no_concilia`. Después se descarta. En
  `origen_json.conciliacion` quedan `contractual` (sin AIU), `subtotales_ok` y
  `diferencia`, ningún total con AIU. `sin_contractual` exige el básico > 0;
  `total_no_concilia` suma el básico. Las corridas **viejas** (`origen.parser_version ==
  "idu-f1/1"`) **no se migran**: su `precio_contractual` sigue siendo el CON AIU y el
  básico va aparte. El cuadro decide la columna aparte «sin AIU» **por datos**, sin leer
  `origen_json` (`report.hay_columna_sin_aiu`): sale si algún ítem trae
  `precio_contractual_sin_aiu != precio_contractual`, o sea una corrida IDU vieja o una
  plana (básico 0, como siempre). En una IDU nueva sale una sola columna, rotulada
  «(sin AIU)». La web no muestra esa columna en la corrida (nunca la mostró), y la
  previa dice «Contractual (sin AIU)» y «Verificación contra el Excel». Medido sobre el
  archivo de referencia (1939 actividades): 123.871.215.068 sin AIU (lo que manda) y
  158.456.072.140 con AIU (solo verificación). Riesgos residuales:
  - un proyecto puede tener una corrida vieja (con AIU) y una nueva (sin AIU), y no se
    suman entre corridas;
  - el plan de una corrida que se estaba armando durante el deploy ya se leyó con
    `idu-f1/1` y queda con AIU, como toda corrida vieja;
  - una línea agregada a mano o por Excel a una corrida IDU nueva trae básico 0 y hace
    reaparecer la columna aparte en el cuadro;
  - las advertencias de verificación de la previa citan cifras con AIU, porque son las
    del Excel.

  Spec: `docs/superpowers/specs/2026-11-25-contractual-sin-aiu-design.md`.
```

- [ ] **Step 2: Agrega la nota al chat de consulta**

En el bullet «Chat de consulta (2026-11)», justo después de la frase que termina en `Las corridas de un proyecto no se suman. Spec:` + `` `docs/superpowers/specs/2026-11-25-chat-consulta-design.md`. ``, agrega:
```markdown
  Prompt `consulta/v2`: el contractual se compara tal cual con el costo directo, y
  `resolver` agrega « (con AIU)» a `contractual`, `diferencia` y `margen` (nunca a
  `costo`) de una corrida o capítulo cuyo `origen.parser_version` es `idu-f1/1`
  (`servicio/consulta.py::_nota_aiu`). La IA no ve la nota: el historial vuelve con
  el `crudo`.
```

- [ ] **Step 3: Agrega la regla a «No hacer»**

Al final de la lista «No hacer», agrega:
```markdown
- No vuelvas a guardar el valor con AIU de la ruta IDU (ni en `LicitacionItem`, ni en
  `plan_json`, ni en `origen_json`): se lee solo para verificar contra el Excel y se
  descarta. Y no «le quites el AIU» a un valor dividiendo por un factor: el AIU varía
  por actividad (entre 1,2781 y 1,2797 en el archivo de referencia), y el básico ya
  viene escrito en el formulario. Tampoco borres de `_FORBIDDEN_KEYS` las claves que
  quedaron muertas (`contractual_con_aiu`, `subtotales_excel`).
```

- [ ] **Step 4: Revisa que no quede nada que diga que el contractual IDU lleva AIU**

Run: `grep -n "AIU" CLAUDE.md`
Expected: solo las menciones de arriba. Ninguna línea dice que el contractual de una corrida nueva lleva AIU.

- [ ] **Step 5: Commit**

```bash
git stash push -q constructor-apus/.obsidian/appearance.json && { git add CLAUDE.md && git commit -q -m "docs: CLAUDE.md — el contractual IDU es el sin AIU (idu-f1/2)" -m "Co-Authored-By: Claude Opus 5.5 <noreply@anthropic.com>"; git stash pop -q; }
```

---

### Task 8: Verificación final

**Files:** ninguno, salvo que algo falle.

- [ ] **Step 1: Suite de Python sin `DATABASE_URL`**

Run (Git Bash): `env -u DATABASE_URL python -m pytest tests/ -q`
Expected: todo en PASS (los de Postgres y el de regresión del archivo real salen *skipped*). Si algo falla, **no** lo arregles a ciegas: mira si fija el comportamiento con AIU. Si es así, cámbialo con el mismo criterio de las tareas 2-4 y haz un commit aparte con el patrón de siempre.

- [ ] **Step 2: Web**

Run: `cd web && npx vitest run && npm run build`
Expected: vitest en PASS y build sin errores.

- [ ] **Step 3: Busca restos del comportamiento viejo**

Run: `grep -rn "contractual_con_aiu\|subtotales_excel\|idu-f1/1" apu_tool web/src --include=*.py --include=*.ts --include=*.tsx`
Expected, y nada más:
- `apu_tool/dominio/privacy.py`: las claves muertas, a propósito;
- `apu_tool/dominio/presupuesto.py`: el comentario de `PARSER_VERSION`;
- `apu_tool/servicio/consulta.py`: `PARSER_CON_AIU`;
- `web/src/pages/CorridasInicio.idu.test.tsx`: el `parser_version` de su fixture. Es inofensivo, ver «No se tocan».

- [ ] **Step 4: Antes de mergear**

- Smoke en el navegador: previsualiza el Formulario 1 real. Tiene que decir «Contractual (sin AIU) $123.871.215.068» y «Verificación contra el Excel: OK.». Crea la corrida y descarga el cuadro: una sola columna de contractual, rotulada «(sin AIU)». Abre una corrida vieja: su cuadro sigue con las dos columnas.
- **Pide aprobación explícita** antes de mergear a `master` y de hacer push: `master` despliega solo.
