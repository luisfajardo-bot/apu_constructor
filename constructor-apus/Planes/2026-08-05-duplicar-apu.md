> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-05-duplicar-apu.md`

# Duplicar un APU a partir de otro — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poder duplicar un APU existente (p.ej. el de una mezcla MD12), cambiarle un insumo (MD13) y guardarlo como APU nuevo, desde la biblioteca y desde un ítem de corrida — sin que la copia cueste menos que el original.

**Architecture:** Se reusa el endpoint de alta `POST /api/apus/crear` con un campo opcional `duplicado_de`, y el diálogo `DialogoAgregarApu` con un `modo="duplicar"` (precarga como editar, pero código y turno editables). El servicio hereda del APU de origen el `precio_unitario_hist` y las marcas de sub-APU de cada componente que no cambió, y aplica un piso de `1.0` para que nada quede en $0. `pricing.py` y la capa de datos no se tocan.

**Tech Stack:** Python 3 + FastAPI + Pydantic + pytest (backend) · React 19 + TypeScript + Vite + Vitest + Testing Library (frontend) · SQLite/Postgres vía `apu_tool/datos/`.

**Spec:** `docs/superpowers/specs/2026-08-04-duplicar-apu-design.md`

## Global Constraints

- **Rama:** trabajar en `feat/duplicar-apu` (ya creada). **No** hacer push a `master` sin OK explícito del usuario: `master` auto-despliega.
- **Invariante #1:** la IA nunca ve dinero. Nada de este plan construye payloads hacia la IA ni importa `ai_assist`. El test que verifica que `apu_tool/servicio/` no menciona `ai_assist` debe seguir verde.
- **`apu_tool/dominio/pricing.py` NO se modifica.** Los tests del motor de precios y del cuadro deben pasar **sin tocarlos**. Si alguno necesita cambio, el piso se filtró al costeo → es un bug del cambio, no del test.
- **La capa de datos NO se modifica:** ni `apu_tool/datos/*`, ni `repositorio.py`, ni los `.sql`. No hay migración.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Piso de negocio:** `PISO_HIST = 1.0`. Ningún componente escrito desde la web puede quedar con `precio_unitario_hist` en `0.0`.
- **Ruta real:** el alta es `POST /api/apus/crear` (no `POST /api/apus`), y `rutas.py` mapea todo `ValueError` a **400** (no hay 409 en ese endpoint).
- **Verificación backend:** `python -m pytest tests/ -q` (desde la raíz del repo).
- **Verificación frontend:** `cd web && npm test` y `cd web && npm run build`. **`npm run build` corre `tsc -b`, que es el que detecta los errores de tipos reales — `tsc --noEmit` no alcanza.**
- **Commits frecuentes**, uno por tarea, en español, con el trailer:
  `Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>`

---

## Mapa de archivos

**Backend**

| Archivo | Responsabilidad / cambio |
|---|---|
| `apu_tool/servicio/autoria.py` | `PISO_HIST`, helper `_mapas_de_componentes`, `_componentes_de(hist=)`, `_origen_duplicado`, `crear_apu` con duplicado, `editar_apu` hereda histórico |
| `apu_tool/servicio/esquemas.py` | `DuplicadoDeIn` + `ApuNuevoIn.duplicado_de` |
| `apu_tool/servicio/corridas.py` | `detalle_item` devuelve `apu_turno` |
| `tests/test_servicio_autoria.py` | piso, herencia, validaciones del duplicado, auditoría, regresión de `editar_apu` |
| `tests/test_api_autoria.py` | endpoint con `duplicado_de` (éxito + los 400) |
| `tests/test_servicio_corridas.py` | `detalle_item` trae `apu_turno` |
| `tests/test_corrida_alertas_costeo.py` | el piso no apaga la alerta: el motivo pasa a ser el del cruce |

**Frontend**

| Archivo | Responsabilidad / cambio |
|---|---|
| `web/src/lib/duplicarApu.ts` | **[nuevo]** helpers puros: `codigoSugerido`, `nombreEsDistinto`, `normalizarNombre` |
| `web/src/lib/duplicarApu.test.ts` | **[nuevo]** tests de los helpers |
| `web/src/lib/tipos.ts` | `ApuNuevo.duplicado_de?`, `DetalleItem.apu_turno` |
| `web/src/components/autoria/DialogoAgregarApu.tsx` | `modo="duplicar"` + validaciones + payload |
| `web/src/components/autoria/DialogoAgregarApu.test.tsx` | tests del modo duplicar |
| `web/src/pages/Apus.tsx` | botón "Duplicar" en la fila expandida |
| `web/src/components/corrida/TablaItems.tsx` | prop `puedeEditar` + botón "Duplicar este APU y usarlo aquí" |
| `web/src/components/corrida/TablaItems.test.tsx` | tests del botón y del flujo crear→reasignar |
| `web/src/pages/Corrida.tsx` | calcula `puedeEditar` y lo pasa a `TablaItems` |

---

## Task 1: Piso de $1 y herencia del histórico en `_componentes_de`

**Files:**
- Modify: `apu_tool/servicio/autoria.py:58-93` (`_componentes_de`)
- Test: `tests/test_servicio_autoria.py`

**Interfaces:**
- Consumes: nada (primera tarea).
- Produces:
  - `PISO_HIST: float = 1.0` (módulo `apu_tool.servicio.autoria`)
  - `_mapas_de_componentes(comps: list[ApuComponent]) -> tuple[dict[str, tuple[str, str]], dict[str, float]]` — devuelve `(previos, hist)`
  - `_componentes_de(alm, comp_dicts, shift, previos=None, hist=None) -> list[ApuComponent]`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_servicio_autoria.py`:

```python
# ------------------------------------------- piso de $1 y herencia del histórico
def test_crear_apu_pone_piso_de_uno_en_el_historico(tmp_path):
    """Regla de negocio 'nada en $0': un componente sin histórico que heredar se
    guarda en 1.0, no en 0.0."""
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "unidad": "M2", "grupo": "ACAB",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    comps = alm.apus.get_components("B2", "DIURNO")
    assert comps[0].precio_unitario_hist == autoria.PISO_HIST == 1.0


def test_mapas_de_componentes_devuelve_marcas_y_historico():
    comps = [
        ApuComponent("A1", "DIURNO", "100", "CEMENTO GRIS", "KG", 2.0, 900.0),
        ApuComponent("A1", "DIURNO", "200", "ARENA", "M3", 0.5, 48000.0,
                     tipo="apu", ref_shift="NOCTURNO"),
    ]
    previos, hist = autoria._mapas_de_componentes(comps)
    assert previos == {"100": ("insumo", ""), "200": ("apu", "NOCTURNO")}
    assert hist == {"100": 900.0, "200": 48000.0}


def test_mapas_de_componentes_codigo_repetido_gana_el_de_tipo_apu():
    """Misma regla de desempate que ya aplicaba editar_apu para las marcas."""
    comps = [
        ApuComponent("A1", "DIURNO", "100", "X", "KG", 1.0, 500.0),
        ApuComponent("A1", "DIURNO", "100", "X", "KG", 1.0, 700.0,
                     tipo="apu", ref_shift="DIURNO"),
    ]
    previos, hist = autoria._mapas_de_componentes(comps)
    assert previos["100"] == ("apu", "DIURNO")
    assert hist["100"] == 700.0


def test_componentes_de_hereda_el_historico_del_mapa(tmp_path):
    alm = _alm(tmp_path)
    comps = autoria._componentes_de(
        alm, [{"insumo_codigo": "100", "rendimiento": 2.0},
              {"insumo_codigo": "200", "rendimiento": 1.0}],
        "DIURNO", hist={"100": 900.0})
    assert comps[0].precio_unitario_hist == 900.0     # heredado
    assert comps[1].precio_unitario_hist == 1.0       # sin nada que heredar -> piso


def test_componentes_de_sube_al_piso_un_historico_en_cero(tmp_path):
    alm = _alm(tmp_path)
    comps = autoria._componentes_de(
        alm, [{"insumo_codigo": "100", "rendimiento": 2.0}],
        "DIURNO", hist={"100": 0.0})
    assert comps[0].precio_unitario_hist == 1.0
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_servicio_autoria.py -q -k "piso or mapas_de_componentes or componentes_de_hereda or componentes_de_sube"`

Expected: FAIL — `AttributeError: module 'apu_tool.servicio.autoria' has no attribute 'PISO_HIST'` / `'_mapas_de_componentes'`, y `TypeError: _componentes_de() got an unexpected keyword argument 'hist'`.

- [ ] **Step 3: Implementar el piso y el helper**

En `apu_tool/servicio/autoria.py`, **agregar** la constante justo debajo del bloque de imports (después de la línea `from apu_tool.servicio.subapus import (...)`):

```python
# Regla de negocio "nada en $0": el precio histórico de respaldo que se escribe
# desde la web nunca queda en 0. Ver docs/superpowers/specs/2026-08-04-duplicar-apu-design.md
PISO_HIST = 1.0
```

**Reemplazar** el bloque `_componentes_de` completo (`apu_tool/servicio/autoria.py:58-93`) por:

```python
def _mapas_de_componentes(
    comps: list[ApuComponent],
) -> tuple[dict[str, tuple[str, str]], dict[str, float]]:
    """Marcas y precio histórico de una composición existente, por código de insumo.

    - `previos`: (tipo, ref_shift), para preservar la marca de sub-APU cuando el
      componente entrante no trae `tipo` explícito (invariante de FIX 1).
    - `hist`: `precio_unitario_hist`, para que duplicar o editar un APU no destruya
      el respaldo histórico de los componentes que siguen siendo los mismos.

    Si un código se repite, gana la primera aparición salvo que otra sea de
    `tipo == "apu"` (la regla que ya aplicaba `editar_apu` para las marcas)."""
    previos: dict[str, tuple[str, str]] = {}
    hist: dict[str, float] = {}
    for c in comps:
        if c.insumo_codigo not in previos or c.tipo == "apu":
            previos[c.insumo_codigo] = (c.tipo, c.ref_shift)
            hist[c.insumo_codigo] = c.precio_unitario_hist
    return previos, hist


def _componentes_de(alm: Almacen, comp_dicts: list[dict], shift: str,
                    previos: dict | None = None,
                    hist: dict | None = None) -> list[ApuComponent]:
    """Arma los ApuComponent a partir de los dicts del contrato HTTP.

    `previos` (opcional): marcas existentes por código -> (tipo, ref_shift), para
    preservarlas al editar cuando el componente entrante no trae `tipo` explícito
    (invariante de FIX 1: editar un APU no debe borrar las marcas de sub-APU).

    `hist` (opcional): precio histórico de respaldo por código, del APU de origen
    (duplicado) o del propio APU (edición). Lo que no está ahí no tiene histórico
    que heredar y queda en `PISO_HIST`: nunca en 0 (regla "nada en $0")."""
    previos = previos or {}
    hist = hist or {}
    comps: list[ApuComponent] = []
    for c in comp_dicts:
        cod = str(c.get("insumo_codigo", "") or "").strip()
        rend = _to_float(c.get("rendimiento"))
        if not cod:
            raise ValueError("Cada componente necesita un código de insumo.")
        if rend <= 0:
            raise ValueError(f"El rendimiento del insumo {cod} debe ser mayor que 0.")
        # Resuelve nombre/unidad desde la base si el insumo existe (respaldo embebido);
        # si no existe, se guarda lo que venga (enlace blando -> cruce huérfano al costear).
        cands = alm.precios.get_candidatos(cod)
        if cands:
            nombre, unidad = cands[0].nombre, cands[0].unidad
        else:
            nombre = str(c.get("insumo_nombre", "") or "")
            unidad = str(c.get("unidad", "") or "")
        tipo_in = c.get("tipo")
        if tipo_in:
            tipo, ref_shift = str(tipo_in), str(c.get("ref_shift", "") or "")
        elif cod in previos:
            tipo, ref_shift = previos[cod]
        else:
            tipo, ref_shift = "insumo", ""
        comps.append(ApuComponent(
            apu_codigo="", shift=shift, insumo_codigo=cod, insumo_nombre=nombre,
            unidad=unidad, rendimiento=rend,
            precio_unitario_hist=max(PISO_HIST, hist.get(cod, 0.0)),
            tipo=tipo, ref_shift=ref_shift))
    return comps
```

- [ ] **Step 4: Correr los tests nuevos**

Run: `python -m pytest tests/test_servicio_autoria.py -q -k "piso or mapas_de_componentes or componentes_de_hereda or componentes_de_sube"`

Expected: PASS (5 passed).

- [ ] **Step 5: Correr la suite completa (el piso no debe romper nada)**

Run: `python -m pytest tests/ -q`

Expected: todo verde. Si falla un test de `pricing.py` o del cuadro, **no lo modifiques**: significa que el piso se filtró al costeo o que un test asumía `hist == 0.0` en un APU creado por la web — revisá el caso y reportalo.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_servicio_autoria.py
git commit -m "$(cat <<'EOF'
feat(autoria): piso de $1 y herencia del histórico en _componentes_de

Ningún componente escrito desde la web queda con precio_unitario_hist en 0
(regla "nada en $0"), y _componentes_de puede heredar el histórico de una
composición existente. _mapas_de_componentes extrae marcas + histórico con la
misma regla de desempate que ya usaba editar_apu.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 2: `editar_apu` deja de borrar el histórico

**Files:**
- Modify: `apu_tool/servicio/autoria.py:118-147` (`editar_apu`)
- Test: `tests/test_servicio_autoria.py`

**Interfaces:**
- Consumes: `_mapas_de_componentes(comps)` y `_componentes_de(..., previos=, hist=)` de la Task 1.
- Produces: nada nuevo en la API pública; `editar_apu` conserva su firma
  `editar_apu(alm, codigo, shift, datos, actor=None) -> dict | None`.

- [ ] **Step 1: Escribir el test de regresión que falla**

Agregar al final de `tests/test_servicio_autoria.py`:

```python
def test_editar_apu_conserva_el_historico_de_los_componentes(tmp_path):
    """Antes, editar un APU ponía precio_unitario_hist=0.0 en TODOS sus componentes
    y tiraba a $0 las líneas cuyo insumo es huérfano/sin tarifa en catálogo."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("C3", "BASE GRANULAR", "M3", "DIURNO", "PAV")])
    alm.apus.insert_components([
        ApuComponent("C3", "DIURNO", "100", "CEMENTO GRIS", "KG", 2.0, 900.0),
        ApuComponent("C3", "DIURNO", "999", "INSUMO HUERFANO", "UN", 1.0, 75000.0),
    ])

    autoria.editar_apu(alm, "C3", "DIURNO", {"nombre": "BASE GRANULAR B",
        "unidad": "M3", "grupo": "PAV",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 3.0},
                        {"insumo_codigo": "999", "rendimiento": 1.0,
                         "insumo_nombre": "INSUMO HUERFANO", "unidad": "UN"}]})

    comps = {c.insumo_codigo: c for c in alm.apus.get_components("C3", "DIURNO")}
    assert comps["100"].precio_unitario_hist == 900.0      # heredado, no borrado
    assert comps["999"].precio_unitario_hist == 75000.0    # el huérfano conserva su respaldo
    assert comps["100"].rendimiento == 3.0                 # la edición sí se aplicó
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_servicio_autoria.py -q -k "conserva_el_historico"`

Expected: FAIL — `assert 1.0 == 900.0` (hoy `editar_apu` no pasa `hist`, así que cae al piso).

- [ ] **Step 3: Usar el helper en `editar_apu`**

En `apu_tool/servicio/autoria.py`, dentro de `editar_apu`, **reemplazar**:

```python
    existentes = alm.apus.get_components(codigo, shift)
    previos: dict[str, tuple[str, str]] = {}
    for e in existentes:
        if e.insumo_codigo not in previos or e.tipo == "apu":
            previos[e.insumo_codigo] = (e.tipo, e.ref_shift)
    comps = _componentes_de(alm, datos.get("componentes", []) or [], shift, previos=previos)
```

por:

```python
    existentes = alm.apus.get_components(codigo, shift)
    # Hereda marcas de sub-APU Y precio histórico de respaldo: editar el rendimiento
    # de un insumo no debe tirar a $0 las líneas cuyo insumo es huérfano o no tiene
    # tarifa en el catálogo.
    previos, hist = _mapas_de_componentes(existentes)
    comps = _componentes_de(alm, datos.get("componentes", []) or [], shift,
                            previos=previos, hist=hist)
```

- [ ] **Step 4: Correr el test nuevo y los de marcas de sub-APU**

Run: `python -m pytest tests/test_servicio_autoria.py -q -k "editar_apu"`

Expected: PASS — incluidos `test_editar_apu_preserva_marca_subapu_si_no_viene_tipo` y `test_editar_apu_tipo_explicito_gana_sobre_marca_previa`, que ya existían y deben seguir verdes.

- [ ] **Step 5: Correr la suite completa**

Run: `python -m pytest tests/ -q`

Expected: todo verde.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/autoria.py tests/test_servicio_autoria.py
git commit -m "$(cat <<'EOF'
fix(autoria): editar un APU ya no borra el precio histórico de respaldo

editar_apu reusa _mapas_de_componentes y hereda el histórico del propio APU.
Antes ponía precio_unitario_hist=0.0 en todos los componentes, así que editar
el rendimiento de un insumo podía tirar a $0 las líneas cuyo insumo es huérfano
o no tiene tarifa en el catálogo.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 3: El piso no apaga la alerta de costeo

**Files:**
- Test: `tests/test_corrida_alertas_costeo.py`

**Interfaces:**
- Consumes: `PISO_HIST` (Task 1). No modifica código de producción — es la prueba de que el piso cambia el *motivo* de la alerta, no su existencia.
- Produces: nada.

**Contexto para el implementador:** `apu_tool/dominio/alertas.py:32-37` es una cadena `if/elif`:
`sin_precio_lista` → **regla dura del $0** (`costo <= 0 or precio_unitario <= 0`) → motivos de cruce (`_MOTIVO_CRUCE`: `ambiguo`, `huerfano`, `apu_vacio`, `ciclo`, `sin_precio_catalogo`). Con histórico en 0 el componente huérfano reportaba el genérico *"en $0"* y tapaba el motivo real; con el piso reporta *"sin insumo en catálogo"*. Este test fija esa conducta para que nadie la revierta por accidente.

- [ ] **Step 1: Leer el archivo de tests existente**

Run: `python -m pytest tests/test_corrida_alertas_costeo.py -q`

Expected: PASS. Leé el archivo completo para reusar sus fixtures/helpers (cómo arma el `Almacen`, los insumos y la corrida) antes de escribir el test nuevo. Seguí el estilo que ya está ahí en vez de inventar uno.

- [ ] **Step 2: Escribir el test**

Agregar al final de `tests/test_corrida_alertas_costeo.py` (adaptando los helpers a los que existan en el archivo):

```python
def test_componente_huerfano_creado_por_web_alerta_por_cruce_no_por_cero(tmp_path):
    """Con el piso de $1, un componente huérfano deja de reportar el genérico
    'en $0' y reporta el motivo accionable del cruce. Sigue alertando."""
    from apu_tool.dominio.alertas import alertas_costeo
    from apu_tool.servicio import autoria

    alm = _alm(tmp_path)                      # helper del archivo
    # "999" no existe en el catálogo -> cruce huérfano al costear
    autoria.crear_apu(alm, {"codigo": "H1", "turno": "DIURNO", "nombre": "HUERFANO",
        "unidad": "UN", "grupo": "G",
        "componentes": [{"insumo_codigo": "999", "rendimiento": 1.0,
                         "insumo_nombre": "NO EXISTE", "unidad": "UN"}]})
    comps = alm.apus.get_components("H1", "DIURNO")
    assert comps[0].precio_unitario_hist == 1.0            # el piso quedó guardado

    ens = _ensamblar(alm, "H1", "DIURNO")                 # helper del archivo
    motivos = alertas_costeo(ens)
    assert motivos, "el componente huérfano debe seguir alertando"
    assert any("sin insumo en catálogo" in m for m in motivos)
    assert not any("en $0" in m for m in motivos)
```

Si el archivo no tiene un helper de ensamblado reutilizable, armá el `AssembledApu`
costeando con `PricingEngine` igual que lo hacen los tests vecinos — **sin** tocar
`pricing.py`.

- [ ] **Step 3: Correr el test**

Run: `python -m pytest tests/test_corrida_alertas_costeo.py -q`

Expected: PASS. Si falla porque el motivo real no es `"sin insumo en catálogo"` sino `"cruce ambiguo"`, ajustá la aserción al motivo que corresponda al escenario del helper — lo que **no** se acepta es que el motivo sea `"en $0"` ni que la lista de motivos quede vacía.

- [ ] **Step 4: Commit**

```bash
git add tests/test_corrida_alertas_costeo.py
git commit -m "$(cat <<'EOF'
test(alertas): el piso de $1 cambia el motivo de la alerta, no la apaga

Un componente huérfano creado desde la web reporta "sin insumo en catálogo"
en vez del genérico "en $0", que tapaba el motivo real. Fija la conducta para
que el piso no se lea nunca como "ya no alerta".

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 4: `crear_apu` con `duplicado_de`

**Files:**
- Modify: `apu_tool/servicio/autoria.py` (nuevo `_origen_duplicado`; `crear_apu` en `:96-115`)
- Modify: `apu_tool/servicio/esquemas.py:52-60` (`ApuNuevoIn`)
- Test: `tests/test_servicio_autoria.py`, `tests/test_api_autoria.py`

**Interfaces:**
- Consumes: `_mapas_de_componentes`, `_componentes_de(..., hist=)`, `PISO_HIST` (Task 1).
- Produces:
  - `DuplicadoDeIn(BaseModel)` con campos `codigo: str`, `turno: str`
  - `ApuNuevoIn.duplicado_de: Optional[DuplicadoDeIn] = None`
  - `_origen_duplicado(alm, dup, codigo, turno, nombre) -> tuple[dict | None, dict | None, tuple[str, str] | None]`
  - `crear_apu(alm, datos, actor=None) -> dict` — misma firma; `datos["duplicado_de"]` opcional

- [ ] **Step 1: Escribir los tests de servicio que fallan**

Agregar al final de `tests/test_servicio_autoria.py`:

```python
# ------------------------------------------------------------------- duplicado
def _apu_origen(alm):
    """APU de origen con un insumo normal y uno huérfano (con histórico real)."""
    alm.apus.insert_apus([Apu("3454", "MEZCLA MD12", "M3", "DIURNO", "PAV")])
    alm.apus.insert_components([
        ApuComponent("3454", "DIURNO", "100", "CEMENTO GRIS", "KG", 2.0, 900.0),
        ApuComponent("3454", "DIURNO", "999", "MEZCLA MD12", "M3", 1.0, 480000.0),
    ])


def test_duplicar_hereda_historico_y_deja_el_insumo_nuevo_en_el_piso(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    out = autoria.crear_apu(alm, {
        "codigo": "3454-2", "turno": "DIURNO", "nombre": "MEZCLA MD13",
        "unidad": "M3", "grupo": "PAV",
        "componentes": [
            {"insumo_codigo": "100", "rendimiento": 2.0},
            {"insumo_codigo": "888", "rendimiento": 1.0,
             "insumo_nombre": "MEZCLA MD13", "unidad": "M3"}],
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})
    assert out["codigo"] == "3454-2" and out["n_componentes"] == 2
    comps = {c.insumo_codigo: c for c in alm.apus.get_components("3454-2", "DIURNO")}
    assert comps["100"].precio_unitario_hist == 900.0    # heredado del origen
    assert comps["888"].precio_unitario_hist == 1.0      # insumo nuevo -> piso
    # el origen queda intacto
    assert len(alm.apus.get_components("3454", "DIURNO")) == 2


def test_duplicar_conserva_las_marcas_de_subapu_del_origen(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    alm.apus.set_componente_subapu("3454", "DIURNO", 0, "NOCTURNO")
    autoria.crear_apu(alm, {
        "codigo": "3454-2", "turno": "DIURNO", "nombre": "MEZCLA MD13",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}],   # sin 'tipo'
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})
    comps = alm.apus.get_components("3454-2", "DIURNO")
    assert comps[0].tipo == "apu" and comps[0].ref_shift == "NOCTURNO"


def test_duplicar_origen_inexistente_lanza(tmp_path):
    alm = _alm(tmp_path)
    with pytest.raises(ValueError, match="origen ya no existe"):
        autoria.crear_apu(alm, {"codigo": "X", "turno": "DIURNO", "nombre": "X",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
            "duplicado_de": {"codigo": "NOPE", "turno": "DIURNO"}})


def test_duplicar_con_la_misma_identidad_lanza(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    with pytest.raises(ValueError, match="distinto al del APU de origen"):
        autoria.crear_apu(alm, {"codigo": "3454", "turno": "DIURNO", "nombre": "OTRO",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
            "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})


def test_duplicar_con_el_mismo_nombre_lanza(tmp_path):
    """Comparación normalizada: espacios, mayúsculas y puntuación no cuentan como cambio."""
    alm = _alm(tmp_path)
    _apu_origen(alm)
    for nombre in ("MEZCLA MD12", "  mezcla   md12 ", "MEZCLA MD12."):
        with pytest.raises(ValueError, match="nombre debe ser distinto"):
            autoria.crear_apu(alm, {"codigo": "3454-2", "turno": "DIURNO",
                "nombre": nombre,
                "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
                "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})


def test_duplicar_destino_existente_lanza(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    alm.apus.insert_apus([Apu("3454-2", "YA ESTABA", "M3", "DIURNO", "PAV")])
    with pytest.raises(ValueError):
        autoria.crear_apu(alm, {"codigo": "3454-2", "turno": "DIURNO", "nombre": "MD13",
            "componentes": [{"insumo_codigo": "100", "rendimiento": 1.0}],
            "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})


def test_duplicar_deja_rastro_en_auditoria(tmp_path):
    alm = _alm(tmp_path)
    _apu_origen(alm)
    autoria.crear_apu(alm, {"codigo": "3454-2", "turno": "DIURNO", "nombre": "MEZCLA MD13",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}],
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})
    eventos, _ = alm.auditoria.listar(limit=50, offset=0)
    creacion = [e for e in eventos if e.accion == "apu.crear"][0]
    assert creacion.contexto["origen"] == "duplicado"
    assert creacion.contexto["de"] == "3454"
    assert creacion.contexto["de_turno"] == "DIURNO"


def test_crear_apu_sin_duplicado_de_sigue_marcando_origen_individual(tmp_path):
    alm = _alm(tmp_path)
    autoria.crear_apu(alm, {"codigo": "B2", "turno": "DIURNO", "nombre": "PISO",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}]})
    eventos, _ = alm.auditoria.listar(limit=50, offset=0)
    creacion = [e for e in eventos if e.accion == "apu.crear"][0]
    assert creacion.contexto["origen"] == "individual"
```

**Nota para el implementador:** la firma exacta de `alm.auditoria.listar(...)` y la forma
de `contexto` en el objeto devuelto pueden diferir — mirá cómo lo consultan los tests de
`tests/test_auditoria_servicios_corridas_usuarios.py` y ajustá **solo** esas dos
aserciones de auditoría a la API real. El resto de los tests no cambia.

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `python -m pytest tests/test_servicio_autoria.py -q -k "duplicar or sin_duplicado_de"`

Expected: FAIL — el duplicado se ignora: `comps["100"].precio_unitario_hist == 1.0` en vez de `900.0`, y las validaciones no lanzan.

- [ ] **Step 3: Implementar `_origen_duplicado` y usarlo en `crear_apu`**

En `apu_tool/servicio/autoria.py`, **agregar** antes de `crear_apu`:

```python
def _origen_duplicado(alm: Almacen, dup: dict | None, codigo: str, turno: str,
                      nombre: str) -> tuple[dict | None, dict | None, tuple[str, str] | None]:
    """Valida un alta que es copia de otro APU y devuelve `(previos, hist, origen)`.

    Sin `dup` devuelve `(None, None, None)` y `crear_apu` se comporta como un alta
    normal. La copia debe tener identidad propia y nombre propio: si no, el usuario
    creería que duplicó cuando en realidad no distinguió nada."""
    if not dup:
        return None, None, None
    cod_o = str(dup.get("codigo", "") or "").strip()
    turno_o = str(dup.get("turno", "") or "").strip().upper()
    origen = alm.apus.get_apu(cod_o, turno_o)
    if origen is None:
        raise ValueError("El APU de origen ya no existe.")
    if (codigo, turno) == (cod_o, turno_o):
        raise ValueError(
            "La copia necesita un código o un turno distinto al del APU de origen.")
    if normalizar(nombre) == normalizar(origen.nombre):
        raise ValueError("El nombre debe ser distinto al del APU de origen.")
    previos, hist = _mapas_de_componentes(alm.apus.get_components(cod_o, turno_o))
    return previos, hist, (cod_o, turno_o)
```

**Reemplazar** el cuerpo de `crear_apu` (desde `comps = _componentes_de(...)` hasta el
`return`) por:

```python
    previos, hist, origen = _origen_duplicado(
        alm, datos.get("duplicado_de"), codigo, turno, nombre)
    comps = _componentes_de(alm, datos.get("componentes", []) or [], turno,
                            previos=previos, hist=hist)
    apu = Apu(codigo=codigo, nombre=nombre, unidad=str(datos.get("unidad", "") or ""),
              shift=turno, grupo=str(datos.get("grupo", "") or ""))
    contexto = ({"origen": "duplicado", "de": origen[0], "de_turno": origen[1]}
                if origen else {"origen": "individual"})
    with alm.transaccion("apus") as conn:
        alm.apus.crear_apu(apu, comps, conn=conn)
        registrar_auditoria(
            alm, conn, actor, "apu.crear", "apu", codigo, antes=None,
            despues={"codigo": codigo, "turno": turno, "nombre": nombre,
                     "unidad": apu.unidad, "grupo": apu.grupo, "n_componentes": len(comps)},
            contexto=contexto)
    return {"codigo": codigo, "turno": turno, "nombre": nombre,
            "unidad": apu.unidad, "grupo": apu.grupo, "n_componentes": len(comps)}
```

- [ ] **Step 4: Correr los tests de servicio**

Run: `python -m pytest tests/test_servicio_autoria.py -q`

Expected: PASS (todos, incluidos los previos).

- [ ] **Step 5: Agregar el campo al DTO**

En `apu_tool/servicio/esquemas.py`, **agregar** antes de `class ApuNuevoIn`:

```python
class DuplicadoDeIn(BaseModel):
    """APU del que sale una copia. Presente solo cuando el alta es un duplicado."""
    codigo: str
    turno: str
```

y **agregar** el campo al final de `ApuNuevoIn`:

```python
class ApuNuevoIn(BaseModel):
    codigo: str
    turno: str
    nombre: str
    unidad: str = ""
    grupo: str = ""
    componentes: list[ComponenteIn] = []
    duplicado_de: Optional[DuplicadoDeIn] = None   # None = alta normal
```

- [ ] **Step 6: Escribir el test del endpoint**

Agregar al final de `tests/test_api_autoria.py`:

```python
def test_crear_apu_duplicado_endpoint(tmp_path):
    cli, alm = _cli(tmp_path)
    alm.apus.insert_apus([Apu("3454", "MEZCLA MD12", "M3", "DIURNO", "PAV")])
    alm.apus.insert_components([
        ApuComponent("3454", "DIURNO", "100", "CEMENTO GRIS", "KG", 2.0, 900.0)])

    r = cli.post("/api/apus/crear", json={
        "codigo": "3454-2", "turno": "DIURNO", "nombre": "MEZCLA MD13",
        "unidad": "M3", "grupo": "PAV",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}],
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}})
    assert r.status_code == 200, r.text
    assert r.json()["codigo"] == "3454-2"
    comps = alm.apus.get_components("3454-2", "DIURNO")
    assert comps[0].precio_unitario_hist == 900.0        # heredado

    # nombre igual al del origen -> 400
    assert cli.post("/api/apus/crear", json={
        "codigo": "3454-3", "turno": "DIURNO", "nombre": "MEZCLA MD12",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}],
        "duplicado_de": {"codigo": "3454", "turno": "DIURNO"}}).status_code == 400

    # origen inexistente -> 400
    assert cli.post("/api/apus/crear", json={
        "codigo": "3454-4", "turno": "DIURNO", "nombre": "OTRA",
        "componentes": [{"insumo_codigo": "100", "rendimiento": 2.0}],
        "duplicado_de": {"codigo": "NOPE", "turno": "DIURNO"}}).status_code == 400
```

Verificá los imports al principio de `tests/test_api_autoria.py`: si `Apu` o
`ApuComponent` no están importados, agregalos con
`from apu_tool.nucleo.models import Apu, ApuComponent`. Y confirmá qué devuelve el
helper `_cli(tmp_path)` del archivo (si no devuelve el `Almacen`, usá el mismo camino
que usan los tests vecinos para llegar a la base).

- [ ] **Step 7: Correr los tests del endpoint y la suite completa**

Run: `python -m pytest tests/test_api_autoria.py -q && python -m pytest tests/ -q`

Expected: todo verde.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/autoria.py apu_tool/servicio/esquemas.py tests/test_servicio_autoria.py tests/test_api_autoria.py
git commit -m "$(cat <<'EOF'
feat(autoria): POST /api/apus/crear acepta duplicado_de

Un alta puede declararse copia de otro APU: hereda el precio histórico de
respaldo y las marcas de sub-APU de los componentes que no cambiaron, exige
identidad y nombre propios (nombre comparado normalizado), y deja rastro en
auditoría con origen=duplicado.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 5: `apu_turno` en el detalle de ítem de corrida

**Files:**
- Modify: `apu_tool/servicio/corridas.py:256-268` (`detalle_item`)
- Test: `tests/test_servicio_corridas.py`

**Interfaces:**
- Consumes: nada.
- Produces: `GET /api/corridas/{id}/items/{seq}` devuelve la clave `apu_turno: str`
  (valor de `row.shift`). La consume la Task 9 para leer el APU de origen.

- [ ] **Step 1: Escribir el test que falla**

En `tests/test_servicio_corridas.py`, dentro de `test_detalle_confirmar_y_cuadro`,
**agregar** justo después de `assert det["apu_codigo"] == "A1"`:

```python
    assert det["apu_turno"] == "DIURNO"      # lo necesita "duplicar y usar aquí"
```

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `python -m pytest tests/test_servicio_corridas.py -q -k "detalle_confirmar_y_cuadro"`

Expected: FAIL con `KeyError: 'apu_turno'`.

- [ ] **Step 3: Agregar la clave**

En `apu_tool/servicio/corridas.py`, dentro del `return` de `detalle_item`, **reemplazar**:

```python
        "apu_codigo": row.apu_codigo, "apu_nombre": row.apu_nombre,
```

por:

```python
        "apu_codigo": row.apu_codigo, "apu_nombre": row.apu_nombre,
        # turno del APU asignado: lo necesita "duplicar este APU y usarlo aquí"
        # para leer el APU de origen de la biblioteca (la identidad es código+turno).
        "apu_turno": row.shift,
```

- [ ] **Step 4: Correr los tests de corridas y la suite**

Run: `python -m pytest tests/test_servicio_corridas.py tests/test_api_corridas.py -q && python -m pytest tests/ -q`

Expected: todo verde.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_corridas.py
git commit -m "$(cat <<'EOF'
feat(corridas): el detalle de un ítem devuelve apu_turno

La identidad de un APU es código+turno; el detalle solo traía el código, así
que el frontend no podía leer el APU de origen de la biblioteca.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 6: Helpers puros de duplicación (frontend)

**Files:**
- Create: `web/src/lib/duplicarApu.ts`
- Create: `web/src/lib/duplicarApu.test.ts`

**Interfaces:**
- Consumes: nada.
- Produces:
  - `baseDe(codigo: string): string` — código sin marca nocturna ni sufijo de copia
  - `normalizarNombre(s: string): string`
  - `nombreEsDistinto(nombreOrigen: string, nombreNuevo: string): boolean`
  - `codigoSugerido(codigoOrigen: string, turno: string, ocupados: string[]): string`

- [ ] **Step 1: Escribir los tests que fallan**

Crear `web/src/lib/duplicarApu.test.ts`:

```ts
import { expect, test } from "vitest";
import { baseDe, codigoSugerido, nombreEsDistinto, normalizarNombre } from "./duplicarApu";

test("baseDe quita la marca nocturna y el sufijo de copia", () => {
  expect(baseDe("3454")).toBe("3454");
  expect(baseDe("3454 N")).toBe("3454");
  expect(baseDe("3454-2")).toBe("3454");
  expect(baseDe("3454-2 N")).toBe("3454");
});

test("codigoSugerido agrega el sufijo -2 sobre la base", () => {
  expect(codigoSugerido("3454", "DIURNO", [])).toBe("3454-2");
});

test("codigoSugerido salta los códigos ocupados", () => {
  expect(codigoSugerido("3454", "DIURNO", ["3454-2", "3454-3"])).toBe("3454-4");
});

test("codigoSugerido no anida cuando el origen ya es una copia", () => {
  expect(codigoSugerido("3454-2", "DIURNO", ["3454-2"])).toBe("3454-3");
});

test("codigoSugerido pone la ' N' al final en nocturno", () => {
  expect(codigoSugerido("3454 N", "NOCTURNO", [])).toBe("3454-2 N");
  expect(codigoSugerido("3454", "NOCTURNO", [])).toBe("3454-2 N");
  expect(codigoSugerido("3454 N", "DIURNO", [])).toBe("3454-2");
  expect(codigoSugerido("3454 N", "NOCTURNO", ["3454-2 N"])).toBe("3454-3 N");
});

test("normalizarNombre replica el criterio del backend", () => {
  expect(normalizarNombre("  Mezcla   MD12. ")).toBe("MEZCLA MD12");
  expect(normalizarNombre("MEZCLÁ MD12")).toBe("MEZCLA MD12");
});

test("nombreEsDistinto ignora espacios, mayúsculas, tildes y puntuación", () => {
  expect(nombreEsDistinto("MEZCLA MD12", "  mezcla   md12 ")).toBe(false);
  expect(nombreEsDistinto("MEZCLA MD12", "MEZCLA MD12.")).toBe(false);
  expect(nombreEsDistinto("MEZCLA MD12", "MEZCLA MD13")).toBe(true);
  expect(nombreEsDistinto("MEZCLA MD12", "   ")).toBe(false);
});
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `cd web && npm test -- duplicarApu`

Expected: FAIL — no se puede resolver `./duplicarApu`.

- [ ] **Step 3: Implementar los helpers**

Crear `web/src/lib/duplicarApu.ts`:

```ts
// Helpers puros para duplicar un APU. Aislados para testearlos sin montar la UI,
// igual que costoApu.ts / validacionApu.ts.

/** Convención de la empresa: el APU nocturno lleva el código con sufijo " N". */
const MARCA_NOCTURNA = " N";
const RE_MARCA_NOCTURNA = /\s+N$/i;
const RE_SUFIJO_COPIA = /-\d+$/;

/**
 * Base de un código: sin la marca nocturna y sin el sufijo de copia.
 * "3454 N" -> "3454" · "3454-2" -> "3454" · "3454-2 N" -> "3454"
 * Se exporta porque también es el `q` con el que se consultan los códigos ocupados.
 */
export function baseDe(codigo: string): string {
  return codigo
    .trim()
    .replace(RE_MARCA_NOCTURNA, "")
    .trim()
    .replace(RE_SUFIJO_COPIA, "")
    .trim();
}

/**
 * Código sugerido para la copia: el primer `-<n>` libre sobre la base, con la
 * marca nocturna al final si el turno es NOCTURNO. `ocupados` son códigos
 * completos (tal como están en la biblioteca).
 */
export function codigoSugerido(
  codigoOrigen: string,
  turno: string,
  ocupados: string[],
): string {
  const base = baseDe(codigoOrigen);
  const nocturno = turno.trim().toUpperCase() === "NOCTURNO";
  const tomados = new Set(ocupados.map((c) => c.trim().toUpperCase()));
  const arma = (n: number) => `${base}-${n}${nocturno ? MARCA_NOCTURNA : ""}`;
  let n = 2;
  while (tomados.has(arma(n).toUpperCase()) && n < 999) n++;
  return arma(n);
}

/**
 * Mismo criterio que `apu_tool/nucleo/texto.py::normalizar`: sin tildes,
 * MAYÚSCULAS, sin puntuación, espacios colapsados. Espejar el backend evita que
 * el diálogo habilite un guardado que el servidor va a rechazar con 400.
 */
export function normalizarNombre(s: string): string {
  return (s || "")
    .toUpperCase()
    .normalize("NFD")
    .replace(/[\u0300-\u036f]/g, "")            // sin tildes
    .replace(/[^A-Z0-9 ]+/g, " ")
    .replace(/\s+/g, " ")
    .trim();
}

/** La copia necesita nombre propio: vacío o igual al del origen no cuenta. */
export function nombreEsDistinto(nombreOrigen: string, nombreNuevo: string): boolean {
  const nuevo = normalizarNombre(nombreNuevo);
  return nuevo !== "" && nuevo !== normalizarNombre(nombreOrigen);
}
```

- [ ] **Step 4: Correr los tests**

Run: `cd web && npm test -- duplicarApu`

Expected: PASS (6 tests).

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/duplicarApu.ts web/src/lib/duplicarApu.test.ts
git commit -m "$(cat <<'EOF'
feat(web): helpers puros para duplicar un APU

codigoSugerido arma el primer "-<n>" libre sobre la base del código y respeta
la convención " N" del turno nocturno; nombreEsDistinto espeja el normalizar
del backend para no habilitar un guardado que el servidor rechazaría.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 7: `DialogoAgregarApu` en modo duplicar

**Files:**
- Modify: `web/src/lib/tipos.ts:233-240` (`ApuNuevo`), `:72-82` (`DetalleItem`)
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx`
- Test: `web/src/components/autoria/DialogoAgregarApu.test.tsx`

**Interfaces:**
- Consumes: `codigoSugerido`, `nombreEsDistinto` (Task 6); `duplicado_de` del backend (Task 4); `apu_turno` (Task 5).
- Produces:
  - `ApuNuevo.duplicado_de?: { codigo: string; turno: string }`
  - `DetalleItem.apu_turno: string`
  - `DialogoAgregarApu` acepta `modo?: "crear" | "editar" | "duplicar"`
  - **Cambio de contrato:** `onCreado` pasa de `() => void` a
    `(codigo: string, turno: string) => void`. Los llamadores que no necesitan los
    argumentos pueden seguir pasando `() => recargar()`.

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `web/src/components/autoria/DialogoAgregarApu.test.tsx`:

```tsx
const origenDemo = {
  codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3", grupo: "PAV",
  costo_unitario: 480000,
  composicion: [{
    insumo_codigo: "999", insumo_nombre: "MEZCLA MD12", unidad: "M3",
    rendimiento: 1, precio_unitario: 480000, fuente_precio: "PRECIO IDU",
    costo: 480000, calidad_cruce: "exacto",
  }],
};

test("modo duplicar precarga el código sugerido y deja código y turno editables", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  const codigo = await screen.findByDisplayValue("3454-2");
  expect((codigo as HTMLInputElement).disabled).toBe(false);
  const turno = screen.getByDisplayValue("DIURNO");
  expect((turno as HTMLSelectElement).disabled).toBe(false);
  // la composición del origen viene copiada
  expect(screen.getByText("MEZCLA MD12")).toBeTruthy();
});

test("modo duplicar bloquea el guardado mientras el nombre sea el del origen", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  const boton = await screen.findByRole("button", { name: /Crear APU/i });
  expect((boton as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/nombre debe ser distinto/i)).toBeTruthy();

  fireEvent.change(screen.getByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  await waitFor(() =>
    expect((screen.getByRole("button", { name: /Crear APU/i }) as HTMLButtonElement)
      .disabled).toBe(false));
});

test("modo duplicar manda duplicado_de en el payload y avisa el código creado", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  const { crearApu } = await import("@/api/autoria");
  const onCreado = vi.fn();
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={onCreado}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  fireEvent.change(await screen.findByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Crear APU/i }));

  await waitFor(() => expect(crearApu).toHaveBeenCalled());
  const payload = (crearApu as unknown as { mock: { calls: unknown[][] } }).mock.calls[0][0] as {
    codigo: string; nombre: string; duplicado_de?: { codigo: string; turno: string };
  };
  expect(payload.codigo).toBe("3454-2");
  expect(payload.nombre).toBe("MEZCLA MD13");
  expect(payload.duplicado_de).toEqual({ codigo: "3454", turno: "DIURNO" });
  await waitFor(() => expect(onCreado).toHaveBeenCalledWith("3454-2", "DIURNO"));
});

test("modo duplicar recalcula el código al cambiar el turno si no lo tocaste", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  await screen.findByDisplayValue("3454-2");
  fireEvent.change(screen.getByDisplayValue("DIURNO"), { target: { value: "NOCTURNO" } });
  await waitFor(() => expect(screen.getByDisplayValue("3454-2 N")).toBeTruthy());
});

test("modo duplicar NO recalcula el código si ya lo escribiste a mano", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu
      open onOpenChange={() => {}} onCreado={() => {}}
      modo="duplicar" inicial={origenDemo as never}
    />,
  );
  fireEvent.change(await screen.findByDisplayValue("3454-2"), {
    target: { value: "9999" },
  });
  fireEvent.change(screen.getByDisplayValue("DIURNO"), { target: { value: "NOCTURNO" } });
  await waitFor(() => expect(screen.getByDisplayValue("9999")).toBeTruthy());
});
```

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `cd web && npm test -- DialogoAgregarApu`

Expected: FAIL — `modo="duplicar"` no está en el tipo y el diálogo no precarga nada (los tests previos del archivo deben seguir pasando).

- [ ] **Step 3: Extender los tipos**

En `web/src/lib/tipos.ts`, **reemplazar** `ApuNuevo`:

```ts
export interface ApuNuevo {
  codigo: string;
  turno: string;
  nombre: string;
  unidad: string;
  grupo: string;
  componentes: ComponenteNuevo[];
  // Presente solo cuando el alta es una copia de otro APU: el backend hereda de
  // ahí el precio histórico de respaldo y las marcas de sub-APU.
  duplicado_de?: { codigo: string; turno: string };
}
```

y **agregar** `apu_turno` a `DetalleItem`:

```ts
export interface DetalleItem {
  seq: number;
  descripcion: string;
  apu_codigo: string;
  apu_turno: string;
  apu_nombre: string;
  status: string;
  explicacion: string;
  candidatos: Candidato[];
  composicion: LineaComposicion[];
  costo_unitario: number;
}
```

- [ ] **Step 4: Implementar el modo duplicar en el diálogo**

En `web/src/components/autoria/DialogoAgregarApu.tsx`:

**4a.** Agregar el import:

```ts
import { baseDe, codigoSugerido, nombreEsDistinto } from "@/lib/duplicarApu";
```

y agregar `listarApus` al import existente de `@/api/autoria`:

```ts
import { crearApu, editarApu, listarApus } from "@/api/autoria";
```

**4b.** Cambiar la interfaz de props:

```ts
interface DialogoAgregarApuProps {
  open: boolean;
  onOpenChange: (open: boolean) => void;
  /** `codigo`/`turno` del APU creado o editado (los llamadores pueden ignorarlos). */
  onCreado: (codigo: string, turno: string) => void;
  modo?: "crear" | "editar" | "duplicar";
  /** APU base: el que se edita, o el que se duplica. */
  inicial?: ApuDetalle | null;
}
```

**4c.** Agregar estado, debajo de `const [guardando, setGuardando] = useState(false);`:

```ts
  // Duplicar: el código arranca sugerido; si el usuario lo escribe a mano, deja de
  // recalcularse (no pisamos lo que ya escribió).
  const [codigoTocado, setCodigoTocado] = useState(false);
  const [ocupados, setOcupados] = useState<string[]>([]);
```

**4d.** Reemplazar el `useEffect` de precarga (`:113-141`) por:

```ts
  useEffect(() => {
    if (!open || !inicial) return;
    if (modo !== "editar" && modo !== "duplicar") return;
    const duplicando = modo === "duplicar";
    setCab({
      // Duplicar: código sugerido derivado (se refina cuando llega `ocupados`).
      codigo: duplicando ? codigoSugerido(inicial.codigo, inicial.turno, []) : inicial.codigo,
      turno: inicial.turno,
      nombre: inicial.nombre,
      unidad: inicial.unidad,
      grupo: inicial.grupo,
    });
    setFilas(
      inicial.composicion.length === 0
        ? [nuevaFila()]
        : inicial.composicion.map((c) => {
            const { tipo, ref_shift } = tipoRefDeLinea(c);
            return {
              uid: uidSeq++,
              tipo,
              ref_shift,
              insumo_codigo: c.insumo_codigo,
              insumo_nombre: c.insumo_nombre,
              unidad: c.unidad,
              rendimiento: String(c.rendimiento),
              precio: c.precio_unitario,
            };
          }),
    );
  }, [open, modo, inicial]);

  // Duplicar: una sola consulta para saber qué códigos derivados están tomados.
  // Si falla, se queda con el "-2" sugerido: el backend rechaza el choque con 400.
  useEffect(() => {
    if (!open || modo !== "duplicar" || !inicial) return;
    let cancelado = false;
    (async () => {
      try {
        // `q` va con la BASE del código: buscar "3454 N" no matchearía "3454-2 N".
        const res = await listarApus({ q: baseDe(inicial.codigo), limit: 100 });
        if (cancelado) return;
        const codigos = res.items.map((a) => a.codigo);
        setOcupados(codigos);
        setCab((prev) =>
          codigoTocado
            ? prev
            : { ...prev, codigo: codigoSugerido(inicial.codigo, prev.turno, codigos) },
        );
      } catch {
        /* sin lista de ocupados: se conserva el sugerido */
      }
    })();
    return () => {
      cancelado = true;
    };
    // `codigoTocado` a propósito fuera de deps: solo importa su valor al resolver.
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [open, modo, inicial]);
```

**4e.** En `handleOpenChange`, agregar el reset del estado nuevo:

```ts
  function handleOpenChange(v: boolean) {
    if (!v) {
      setCab(CABECERA_VACIA);
      setFilas([nuevaFila()]);
      setGuardando(false);
      setCodigoTocado(false);
      setOcupados([]);
    }
    onOpenChange(v);
  }
```

**4f.** Agregar las validaciones, junto a `const valido = ...`:

```ts
  const duplicando = modo === "duplicar" && inicial !== null && inicial !== undefined;
  // La copia necesita nombre propio e identidad propia; si no, no distinguió nada.
  const nombreOk = !duplicando || nombreEsDistinto(inicial!.nombre, cab.nombre);
  const identidadOk =
    !duplicando ||
    cab.codigo.trim() !== inicial!.codigo ||
    cab.turno !== inicial!.turno;

  const valido =
    cabeceraValida && compValidos.length > 0 && !hayRendInvalido && nombreOk && identidadOk;
```

**4g.** En `guardar()`, mandar `duplicado_de` y avisar el código creado. Reemplazar el
bloque `if (modo === "editar") { ... } else { ... }` por:

```ts
      if (modo === "editar") {
        await editarApu(cab.codigo, cab.turno, payload);
        toast.success(`APU ${cab.codigo} (${cab.turno}) actualizado`);
      } else {
        await crearApu({
          codigo: cab.codigo.trim(),
          turno: cab.turno,
          ...payload,
          ...(duplicando
            ? { duplicado_de: { codigo: inicial!.codigo, turno: inicial!.turno } }
            : {}),
        });
        toast.success(`APU ${cab.codigo.trim()} (${cab.turno}) creado`);
      }
      handleOpenChange(false);
      onCreado(cab.codigo.trim(), cab.turno);
```

**4h.** Título del diálogo — reemplazar el contenido de `DialogTitle`:

```tsx
          <DialogTitle className="text-sm">
            {modo === "editar"
              ? "Editar APU"
              : duplicando
                ? `Duplicar APU ${inicial!.codigo} (${inicial!.turno})`
                : "Agregar APU"}
          </DialogTitle>
```

**4i.** Inputs de cabecera: el código y el turno se habilitan al duplicar, y el turno
recalcula el código sugerido. Reemplazar los dos primeros `<label>` del grid:

```tsx
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Código</span>
            <input
              className={inputCls}
              value={cab.codigo}
              onChange={(e) => {
                setCodigoTocado(true);
                setCabecera("codigo", e.target.value);
              }}
              autoFocus
              disabled={modo === "editar"}
            />
          </label>
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Turno</span>
            <select
              className={inputCls}
              value={cab.turno}
              onChange={(e) => {
                const turno = e.target.value;
                setCab((prev) => ({
                  ...prev,
                  turno,
                  // Respeta la convención " N" del nocturno mientras no hayas
                  // escrito el código a mano.
                  codigo:
                    duplicando && !codigoTocado
                      ? codigoSugerido(inicial!.codigo, turno, ocupados)
                      : prev.codigo,
                }));
              }}
              disabled={modo === "editar"}
            >
              <option value="DIURNO">DIURNO</option>
              <option value="NOCTURNO">NOCTURNO</option>
            </select>
          </label>
```

**4j.** Avisos de validación — agregar debajo del bloque `{hayRendInvalido && (...)}`:

```tsx
          {duplicando && !nombreOk && (
            <p className="text-xs text-destructive mt-1">
              El nombre debe ser distinto al del APU de origen.
            </p>
          )}
          {duplicando && !identidadOk && (
            <p className="text-xs text-destructive mt-1">
              La copia necesita un código o un turno distinto al del APU de origen.
            </p>
          )}
```

- [ ] **Step 5: Correr los tests del diálogo**

Run: `cd web && npm test -- DialogoAgregarApu`

Expected: PASS — los 5 nuevos y todos los que ya existían.

- [ ] **Step 6: Verificar los tipos de todo el frontend**

Run: `cd web && npm run build`

Expected: **build OK, sin excepciones.** No dejes un commit con el build rojo.

Dos cosas verificadas de antemano, para que no te desvíes: `onCreado={recargar}` en
`Apus.tsx` sigue compilando (TypeScript acepta pasar una función de menos parámetros),
y los mocks de `vi.mock` son objetos sin tipar, así que el `apu_turno` nuevo y
obligatorio de `DetalleItem` no rompe los fixtures existentes. Si igual aparece un
error de tipos por un objeto literal tipado como `DetalleItem`, agregale
`apu_turno: "DIURNO"` en este mismo commit.

- [ ] **Step 7: Commit**

```bash
git add web/src/lib/tipos.ts web/src/components/autoria/DialogoAgregarApu.tsx web/src/components/autoria/DialogoAgregarApu.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): DialogoAgregarApu en modo duplicar

Precarga cabecera y composición del APU de origen con el código sugerido
derivado, deja código y turno editables, bloquea el guardado si el nombre sigue
siendo el del origen y manda duplicado_de en el payload. onCreado ahora recibe
(codigo, turno).

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 8: Botón "Duplicar" en la página APUs

**Files:**
- Modify: `web/src/pages/Apus.tsx`
- Test: `web/src/pages/Apus.duplicar.test.tsx` **[nuevo]**

**Interfaces:**
- Consumes: `DialogoAgregarApu` con `modo="duplicar"` (Task 7).
- Produces: nada para tareas posteriores.

- [ ] **Step 1: Escribir el test que falla**

Crear `web/src/pages/Apus.duplicar.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { expect, test, vi } from "vitest";

const detalle = {
  codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3", grupo: "PAV",
  costo_unitario: 480000,
  composicion: [{
    insumo_codigo: "999", insumo_nombre: "MEZCLA MD12", unidad: "M3",
    rendimiento: 1, precio_unitario: 480000, fuente_precio: "PRECIO IDU",
    costo: 480000, calidad_cruce: "exacto",
  }],
};

vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({
    items: [{ codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3",
              grupo: "PAV", n_componentes: 1, costo_unitario: 480000 }],
    total: 1, limit: 100, offset: 0,
  })),
  getApuDetalle: vi.fn(async () => detalle),
  crearApu: vi.fn(async () => ({})),
  editarApu: vi.fn(async () => ({})),
  borrarApu: vi.fn(async () => {}),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
vi.mock("@/lib/auth", () => ({
  useAuth: () => ({ perfil: { rol: "admin" } }),
}));

test("la fila expandida ofrece Duplicar y abre el diálogo precargado", async () => {
  const Apus = (await import("./Apus")).default;
  render(<Apus />);
  fireEvent.click(await screen.findByText("MEZCLA MD12"));      // expande la fila
  fireEvent.click(await screen.findByRole("button", { name: /^Duplicar$/ }));
  await waitFor(() =>
    expect(screen.getByText(/Duplicar APU 3454 \(DIURNO\)/)).toBeTruthy());
  expect(screen.getByDisplayValue("3454-2")).toBeTruthy();
});
```

**Nota:** si `Apus.tsx` no se puede renderizar suelto (por rutas o contextos), mirá
cómo lo hacen `web/src/pages/Auditoria.test.tsx` o `CorridasInicio.test.tsx` y copiá
ese andamiaje (mocks de `@/lib/auth`, wrapper de router, etc.).

- [ ] **Step 2: Correr el test para verificar que falla**

Run: `cd web && npm test -- Apus.duplicar`

Expected: FAIL — no existe el botón "Duplicar".

- [ ] **Step 3: Agregar el estado y el diálogo**

En `web/src/pages/Apus.tsx`:

**3a.** Agregar el estado junto a los demás:

```ts
  const [duplicarDetalle, setDuplicarDetalle] = useState<ApuDetalle | null>(null);
```

**3b.** Pasar el handler al detalle. Reemplazar el uso de `<DetalleApu ... />`:

```tsx
                          <DetalleApu
                            detalle={estado}
                            puedeEditar={puedeEditar}
                            onEditar={() => setEditarDetalle(estado)}
                            onDuplicar={() => setDuplicarDetalle(estado)}
                            puedeBorrar={puedeBorrar}
                            onBorrar={() => setBorrarDetalle(estado)}
                          />
```

**3c.** Montar el diálogo, dentro del bloque `{puedeEditar && (<> ... </>)}`, después
del de editar:

```tsx
          <DialogoAgregarApu
            key={duplicarDetalle ? `dup-${duplicarDetalle.codigo}@@${duplicarDetalle.turno}` : "nuevo-dup"}
            open={duplicarDetalle !== null}
            onOpenChange={(v) => { if (!v) setDuplicarDetalle(null); }}
            onCreado={recargar}
            modo="duplicar"
            inicial={duplicarDetalle}
          />
```

**3d.** En `DetalleApu`, agregar la prop y el botón. Reemplazar la firma y el bloque
de acciones:

```tsx
function DetalleApu({
  detalle,
  puedeEditar,
  onEditar,
  onDuplicar,
  puedeBorrar,
  onBorrar,
}: {
  detalle: ApuDetalle;
  puedeEditar: boolean;
  onEditar: () => void;
  onDuplicar: () => void;
  puedeBorrar: boolean;
  onBorrar: () => void;
}) {
```

y dentro del `div` de acciones, entre "Editar" y "Borrar":

```tsx
            {puedeEditar && (
              <Button size="xs" variant="outline" onClick={onDuplicar}>
                Duplicar
              </Button>
            )}
```

- [ ] **Step 4: Correr el test y el build**

Run: `cd web && npm test -- Apus.duplicar && npm run build`

Expected: PASS y build OK (`onCreado={recargar}` sigue siendo válido: los argumentos
extra se ignoran).

- [ ] **Step 5: Correr toda la suite del frontend**

Run: `cd web && npm test`

Expected: todo verde.

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Apus.tsx web/src/pages/Apus.duplicar.test.tsx
git commit -m "$(cat <<'EOF'
feat(web): botón Duplicar en la biblioteca de APUs

La fila expandida ofrece Duplicar junto a Editar (rol editor) y abre el diálogo
precargado con el APU de origen y el código sugerido.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 9: "Duplicar este APU y usarlo aquí" desde la corrida

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Modify: `web/src/pages/Corrida.tsx:201-207`
- Test: `web/src/components/corrida/TablaItems.test.tsx`

**Interfaces:**
- Consumes: `DetalleItem.apu_turno` (Tasks 5 y 7), `DialogoAgregarApu` modo duplicar
  (Task 7), `getApuDetalle` de `@/api/autoria`, `confirmar` de `@/api/corridas`.
- Produces: `TablaItems` acepta la prop nueva `puedeEditar?: boolean` (default `false`).

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `web/src/components/corrida/TablaItems.test.tsx` (reusando los mocks y
fixtures que ya tiene el archivo; agregá los mocks que falten):

```tsx
test("con rol editor, el ítem ofrece duplicar el APU y usarlo aquí", async () => {
  const TablaItems = (await import("./TablaItems")).default;
  render(
    <TablaItems
      corridaId={1}
      items={[itemDemo]}
      onConfirmado={() => {}}
      puedeEditar
    />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  expect(await screen.findByRole("button", { name: /Duplicar este APU/i })).toBeTruthy();
});

test("sin rol editor no ofrece duplicar", async () => {
  const TablaItems = (await import("./TablaItems")).default;
  render(<TablaItems corridaId={1} items={[itemDemo]} onConfirmado={() => {}} />);
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  await screen.findByText(/Cambiar APU/i);
  expect(screen.queryByRole("button", { name: /Duplicar este APU/i })).toBeNull();
});

test("en corrida congelada no ofrece duplicar", async () => {
  const TablaItems = (await import("./TablaItems")).default;
  render(
    <TablaItems
      corridaId={1}
      items={[itemDemo]}
      onConfirmado={() => {}}
      puedeEditar
      readOnly
    />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  expect(screen.queryByRole("button", { name: /Duplicar este APU/i })).toBeNull();
});

test("al crear la copia, el ítem queda reasignado al APU nuevo", async () => {
  const TablaItems = (await import("./TablaItems")).default;
  const { confirmar } = await import("@/api/corridas");
  render(
    <TablaItems
      corridaId={1}
      items={[itemDemo]}
      onConfirmado={() => {}}
      puedeEditar
    />,
  );
  fireEvent.click(screen.getByLabelText("Expandir fila"));
  fireEvent.click(await screen.findByRole("button", { name: /Duplicar este APU/i }));
  // el diálogo abre precargado desde la biblioteca
  fireEvent.change(await screen.findByDisplayValue("MEZCLA MD12"), {
    target: { value: "MEZCLA MD13" },
  });
  fireEvent.click(screen.getByRole("button", { name: /Crear APU/i }));
  await waitFor(() =>
    expect(confirmar).toHaveBeenCalledWith(1, itemDemo.seq, "3454-2", "DIURNO"));
});
```

El archivo necesita estos mocks (agregalos a los que ya tenga, sin duplicar claves):

```tsx
vi.mock("@/api/autoria", () => ({
  getApuDetalle: vi.fn(async () => ({
    codigo: "3454", turno: "DIURNO", nombre: "MEZCLA MD12", unidad: "M3", grupo: "PAV",
    costo_unitario: 480000,
    composicion: [{
      insumo_codigo: "999", insumo_nombre: "MEZCLA MD12", unidad: "M3",
      rendimiento: 1, precio_unitario: 480000, fuente_precio: "PRECIO IDU",
      costo: 480000, calidad_cruce: "exacto",
    }],
  })),
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 100, offset: 0 })),
  crearApu: vi.fn(async () => ({})),
  editarApu: vi.fn(async () => ({})),
}));
vi.mock("@/api/insumos", () => ({
  listarInsumos: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));
```

El `itemDemo`/`detalleDemo` del archivo debe traer `apu_codigo: "3454"` y
`apu_turno: "DIURNO"` en el detalle que devuelve el mock de `getItem`.

- [ ] **Step 2: Correr los tests para verificar que fallan**

Run: `cd web && npm test -- TablaItems`

Expected: FAIL — la prop `puedeEditar` no existe y no hay botón de duplicar.

- [ ] **Step 3: Implementar en `TablaItems.tsx`**

**3a.** Imports nuevos:

```ts
import { toast } from "sonner";
import { getApuDetalle } from "@/api/autoria";
import { DialogoAgregarApu } from "@/components/autoria/DialogoAgregarApu";
import type { ItemCuadro, DetalleItem, CorridaDetalle, ApuDetalle } from "@/lib/tipos";
```

(el `import type` reemplaza el existente, agregando `ApuDetalle`).

**3b.** Props:

```ts
interface TablaItemsProps {
  corridaId: number;
  items: ItemCuadro[];
  onConfirmado: (corridaActualizada: CorridaDetalle) => void;
  readOnly?: boolean;
  control?: ControlCorridaTabla;
  /** Rol editor: habilita crear un APU nuevo (duplicar) desde la corrida. */
  puedeEditar?: boolean;
}

export default function TablaItems({
  corridaId,
  items,
  onConfirmado,
  readOnly = false,
  control,
  puedeEditar = false,
}: TablaItemsProps) {
```

**3c.** Estado y handlers, junto a los demás `useState`:

```ts
  // Duplicar el APU de un ítem: se lee el APU real de la biblioteca (la composición
  // del ítem es la costeada y no trae las marcas de sub-APU).
  const [duplicar, setDuplicar] = useState<{ seq: number; origen: ApuDetalle } | null>(null);

  async function abrirDuplicar(seq: number, codigo: string, turno: string) {
    try {
      const origen = await getApuDetalle(codigo, turno);
      setDuplicar({ seq, origen });
    } catch {
      toast.error("No se pudo leer el APU de origen.");
    }
  }

  async function duplicado(seq: number, codigo: string, turno: string) {
    setDuplicar(null);
    // El APU YA está creado. Si la reasignación falla, hay que decirlo: dejar el
    // toast de éxito o el silencio sugeriría que no pasó nada.
    const ok = await handleConfirmar(seq, codigo, turno);
    if (ok) {
      toast.success(`APU ${codigo} creado y asignado al ítem.`);
    } else {
      toast.error(
        `APU ${codigo} creado; no se pudo asignar al ítem — asignalo con Cambiar APU.`,
      );
    }
  }
```

**3d.** Pasar las props al detalle expandido:

```tsx
                        <DetalleExpandido
                          detalle={estado}
                          seq={it.seq}
                          confirmando={confirmando}
                          errorConfirm={errorConfirm[it.seq]}
                          onConfirmar={handleConfirmar}
                          readOnly={readOnly}
                          puedeDuplicar={puedeEditar && !readOnly}
                          onDuplicar={abrirDuplicar}
                        />
```

**3e.** Montar el diálogo al final del JSX de `TablaItems`, justo antes del `</div>`
que cierra el contenedor raíz:

```tsx
      {duplicar && (
        <DialogoAgregarApu
          key={`dup-${duplicar.origen.codigo}@@${duplicar.origen.turno}@@${duplicar.seq}`}
          open
          onOpenChange={(v) => { if (!v) setDuplicar(null); }}
          onCreado={(codigo, turno) => duplicado(duplicar.seq, codigo, turno)}
          modo="duplicar"
          inicial={duplicar.origen}
        />
      )}
```

**3f.** `DetalleExpandidoProps` y la firma:

```ts
interface DetalleExpandidoProps {
  detalle: DetalleItem;
  seq: number;
  confirmando: string | null;
  errorConfirm: string | undefined;
  onConfirmar: (seq: number, apuCodigo: string, shift?: string) => void;
  readOnly: boolean;
  puedeDuplicar: boolean;
  onDuplicar: (seq: number, codigo: string, turno: string) => void;
}

function DetalleExpandido({
  detalle,
  seq,
  confirmando,
  errorConfirm,
  onConfirmar,
  readOnly,
  puedeDuplicar,
  onDuplicar,
}: DetalleExpandidoProps) {
```

**3g.** El botón, dentro de la sección "Cambiar APU" (después del `<BuscadorApu ... />`):

```tsx
          <BuscadorApu
            disabled={confirmando !== null || readOnly}
            onElegir={(apu) => onConfirmar(seq, apu.codigo, apu.turno)}
          />
          {puedeDuplicar && detalle.apu_codigo && (
            <div className="mt-2">
              <Button
                size="xs"
                variant="outline"
                disabled={confirmando !== null}
                onClick={() => onDuplicar(seq, detalle.apu_codigo, detalle.apu_turno)}
              >
                Duplicar este APU y usarlo aquí
              </Button>
            </div>
          )}
```

**3h.** `handleConfirmar` (`web/src/components/corrida/TablaItems.tsx:75-91`) hoy se
traga el error en `errorConfirm[seq]`, así que `duplicado` no puede saber si funcionó.
Hacer que **devuelva si funcionó**. Es un cambio no rompedor: los llamadores actuales
(`onConfirmar={handleConfirmar}`, cuyo tipo declara `=> void`) ignoran el valor.
Reemplazar la función por:

```ts
  /** Devuelve true si el ítem quedó reasignado. Los llamadores que no lo necesiten
   *  pueden ignorar el valor (el tipo de `onConfirmar` declara `void`). */
  async function handleConfirmar(
    seq: number,
    apuCodigo: string,
    shift?: string,
  ): Promise<boolean> {
    setConfirmando(apuCodigo + "@" + seq);
    setErrorConfirm((prev) => ({ ...prev, [seq]: "" }));
    try {
      const corridaActualizada = await confirmar(corridaId, seq, apuCodigo, shift);
      // Colapsar la fila y refrescar el detalle para mostrar nuevo estado
      setExpandido((prev) => ({ ...prev, [seq]: undefined }));
      onConfirmado(corridaActualizada);
      return true;
    } catch (err) {
      setErrorConfirm((prev) => ({
        ...prev,
        [seq]: err instanceof Error ? err.message : "Error al confirmar",
      }));
      return false;
    } finally {
      setConfirmando(null);
    }
  }
```

El cuerpo es idéntico al actual salvo los dos `return`: la conducta de "Cambiar APU" y
"Confirmar APU actual" no cambia (siguen llenando `errorConfirm`).

- [ ] **Step 4: Pasar `puedeEditar` desde `Corrida.tsx`**

En `web/src/pages/Corrida.tsx`, agregar los imports:

```ts
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
```

dentro del componente, junto a los otros hooks:

```ts
  const { perfil } = useAuth();
```

y en el uso de `<TablaItems ... />` agregar la prop:

```tsx
      <TablaItems
        corridaId={corridaId}
        items={filas}
        onConfirmado={(c) => setCorrida(c)}
        readOnly={data.modo === "congelada"}
        control={live ? undefined : control}
        puedeEditar={puede(perfil?.rol, "editor")}
      />
```

- [ ] **Step 5: Correr los tests del frontend y el build**

Run: `cd web && npm test && npm run build`

Expected: todo verde y build OK.

- [ ] **Step 6: Correr la suite del backend una vez más**

Run: `python -m pytest tests/ -q`

Expected: todo verde.

- [ ] **Step 7: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx web/src/pages/Corrida.tsx
git commit -m "$(cat <<'EOF'
feat(web): duplicar el APU de un ítem de corrida y usarlo ahí

El detalle del ítem ofrece "Duplicar este APU y usarlo aquí" (rol editor,
corrida activa): lee el APU real de la biblioteca, abre el diálogo de duplicado
y al crear reasigna el ítem al APU nuevo. Si la creación funciona pero la
asignación falla, el toast lo dice en vez de sugerir que no pasó nada.

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>
EOF
)"
```

---

## Task 10: Verificación final y smoke en el navegador

**Files:** ninguno (solo verificación).

**Interfaces:**
- Consumes: todo lo anterior.
- Produces: la evidencia para decidir el merge.

- [ ] **Step 1: Suite completa del backend**

Run: `python -m pytest tests/ -q`

Expected: todo verde. Pegá el conteo final (`N passed`) en el reporte.

- [ ] **Step 2: Suite completa del frontend + build**

Run: `cd web && npm test && npm run build`

Expected: todo verde y build OK. Pegá los conteos.

- [ ] **Step 3: Confirmar que `pricing.py` y la capa de datos no se tocaron**

Run: `git diff --stat master...HEAD -- apu_tool/dominio/pricing.py apu_tool/datos/ db/`

Expected: **salida vacía**. Si aparece algo, es una violación de las Global Constraints
— hay que revisarlo antes de seguir.

- [ ] **Step 4: Smoke manual en el navegador**

Levantar la app y verificar a mano (en este orden):

1. Página **APUs** → expandir un APU con varios insumos → **Duplicar**.
2. El código llega sugerido (`<codigo>-2`) y el botón está **bloqueado** con el aviso
   del nombre.
3. Cambiar el nombre → el botón se habilita. Cambiar **un** insumo con el "cambiar" de
   la fila → Crear APU.
4. Buscar el APU nuevo en la lista y comparar su **costo unitario** con el del original:
   deben diferir **solo** por el insumo sustituido.
5. Cambiar el turno a NOCTURNO en un duplicado nuevo → el código sugerido pasa a
   terminar en ` N`.
6. Abrir una corrida **activa** → expandir un ítem con APU → **Duplicar este APU y
   usarlo aquí** → crear → el ítem queda con el APU nuevo y el costo recalculado.
7. Congelar la corrida → el botón de duplicar **desaparece**.
8. Página **Auditoría** → la creación aparece con `origen: duplicado` y el `de`.

**Regla del proyecto:** en cambios de UI, el navegador va **antes** del push. No
declarar la feature terminada con solo los tests verdes.

- [ ] **Step 5: Reportar y pedir el OK para el merge**

Resumir: qué se implementó, los conteos de tests, el resultado del smoke y lo que
quedó fuera (piso al costear y migración de los históricos ya guardados en 0).
**No hacer push a `master` sin OK explícito del usuario** — `master` auto-despliega.

---

## Notas para el implementador

- **`master` auto-despliega a producción.** Todo el trabajo vive en `feat/duplicar-apu`.
- **No inventes migraciones.** Este plan no cambia el esquema: `precio_unitario_hist`,
  `tipo` y `ref_shift` ya existen en `apu_componentes`.
- **Doble backend:** como no se toca `apu_tool/datos/`, no hay que espejar nada en
  `apu_tool/datos/pg/`. Si te encontrás editando algo ahí, pará y revisá el diseño.
- **Los tests de Postgres** (`tests/test_*_pg.py` y afines) hacen `DROP SCHEMA`: nunca
  apuntarlos a producción. Si no tenés Postgres local, corré el resto de la suite y
  reportá que esos quedaron sin correr — CI los cubre.
- **Si un test existente falla y la tentación es editarlo:** no. Primero entendé por qué
  falla. Un test rojo por el piso de $1 en `pricing.py` significa que el piso se filtró
  al costeo, que es exactamente lo que el diseño prohíbe.
