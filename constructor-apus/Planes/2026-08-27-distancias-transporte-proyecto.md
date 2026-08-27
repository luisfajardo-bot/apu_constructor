> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-27-distancias-transporte-proyecto.md`

# Distancias de transporte y ajustes por proyecto — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Que cada proyecto (carpeta de nivel 1) tenga sus propias distancias de acarreo, su peaje y sus ajustes puntuales de composición, sin duplicar ni tocar la biblioteca de APUs.

**Architecture:** Dos capas de desviación sobre la composición de la biblioteca, aplicadas en el único punto de paso del costeo (`PricingEngine.components()`): capa 1 = regla paramétrica de transporte (`rend = volumen × km_de_su_categoría`), capa 2 = ajustes explícitos del proyecto (rendimiento / agregar / quitar / reemplazar). Sin parámetros ni ajustes, el costeo es idéntico al de hoy.

**Tech Stack:** Python 3.12, FastAPI, SQLite + Postgres (Supabase), openpyxl, pytest; React 19 + TypeScript + Vite + Vitest en `web/`.

**Spec:** `docs/superpowers/specs/2026-08-26-distancias-transporte-proyecto-design.md`

---

## Estructura de archivos

**Nuevos:**

| archivo | responsabilidad |
|---|---|
| `apu_tool/dominio/transporte.py` | la regla y los ajustes: funciones puras sobre `list[ApuComponent]` + `cargar_contexto` (único punto que lee la base) |
| `apu_tool/servicio/transporte.py` | parámetros del proyecto, tabla de impacto y clasificación de la biblioteca |
| `apu_tool/servicio/ajustes.py` | CRUD de ajustes del proyecto |
| `supabase/migrations/0006_transporte_proyecto_rls.sql` | RLS de las 3 tablas nuevas |
| `web/src/api/transporte.ts` | cliente HTTP de los 7 endpoints |
| `web/src/pages/DistanciasProyecto.tsx` | pantalla A: distancias + peaje + tabla de impacto |
| `web/src/pages/ClasificacionTransporte.tsx` | pantalla B: las 64 filas M3-KM de la biblioteca |

**Modificados:**

| archivo | cambio |
|---|---|
| `apu_tool/config.py` | vocabulario de categorías, peaje, derechos, `KM_BASE_DEFECTO`, sugerencias |
| `apu_tool/nucleo/models.py` | `ClaseTransporte`, `ParametrosProyecto`, `AjusteProyecto`, `CALIDAD_SIN_DISTANCIA` |
| `apu_tool/dominio/pricing.py` | `contexto=` + `components()` efectivo + precio del peaje |
| `apu_tool/dominio/alertas.py` | motivo «distancia del proyecto no aplicada» |
| `apu_tool/dominio/privacy.py` | `peaje_valor` en `_FORBIDDEN_KEYS` |
| `apu_tool/dominio/report.py` | hoja `DESVIACIONES DEL PROYECTO` |
| `apu_tool/servicio/corridas.py` | construir el contexto y pasarlo a todos los costeos |
| `apu_tool/servicio/rutas.py`, `esquemas.py` | 7 endpoints + DTOs |
| `apu_tool/datos/apus_db.py`, `pg/apus_pg.py`, `db/apus.sql`, `db/pg/apus.sql` | `componente_transporte` |
| `apu_tool/datos/carpetas_db.py`, `pg/carpetas_pg.py`, `db/corridas.sql`, `db/pg/corridas.sql` | `proyecto_parametros`, `proyecto_ajuste` |
| `apu_tool/datos/repositorio.py` | métodos nuevos en los Protocols |
| `web/src/lib/tipos.ts`, `web/src/App.tsx`, `web/src/pages/MisCorridas.tsx`, `web/src/components/corrida/TablaItems.tsx` | tipos, rutas, botón del proyecto, composición editable |
| `CLAUDE.md` | comandos, datos, «No hacer» |

**Orden de despliegue:** las fases 1–3 son seguras de fusionar solas (sin parámetros el costeo no cambia). La fase 4 abre la API y la 5 la UI.

---

## FASE 1 — Dominio puro (sin base de datos)

### Task 1: Vocabulario y modelos

**Files:**
- Modify: `apu_tool/config.py` (al final, después de `LISTA_PRINCIPAL_ID`)
- Modify: `apu_tool/nucleo/models.py`
- Test: `tests/test_transporte_regla.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_transporte_regla.py
"""Regla de transporte por proyecto: pura, sin base de datos."""
from apu_tool import config
from apu_tool.nucleo.models import ClaseTransporte, ParametrosProyecto


def test_parametros_vacios():
    assert ParametrosProyecto().vacio is True
    assert ParametrosProyecto(km_botadero=30).vacio is False
    assert ParametrosProyecto(peaje_aplica=False).vacio is False


def test_km_por_categoria():
    p = ParametrosProyecto(km_botadero=34, km_mezclas=28, km_granulares=32)
    assert p.km("botadero") == 34
    assert p.km("mezclas") == 28
    assert p.km("granulares") == 32
    assert p.km("inexistente") is None


def test_vocabulario_de_config():
    assert config.TRANSPORTE_CATEGORIAS == ("botadero", "mezclas", "granulares")
    assert config.PEAJE == ("INT3", "PEAJE")
    assert config.DERECHOS_BOTADERO == ("7231", "DERECHOS DE BOTADERO")
    assert config.KM_BASE_DEFECTO == 25.0


def test_clase_transporte_es_inmutable():
    c = ClaseTransporte(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS",
                        categoria="mezclas", volumen=1.05, km_base=25.0)
    assert c.volumen == 1.05
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_transporte_regla.py -q`
Expected: FAIL con `ImportError: cannot import name 'ClaseTransporte'`

- [ ] **Step 3: Agregar el vocabulario a `config.py`**

```python
# --- Transporte por proyecto (distancias de acarreo) -------------------------
# Categorías de acarreo que un proyecto parametriza. Vocabulario cerrado, sin
# tabla (mismo criterio que PUBLIC_PRICE_SOURCES y los grupos de APU).
TRANSPORTE_CATEGORIAS = ("botadero", "mezclas", "granulares")

# Identidad (código, nombre) de los insumos con trato especial. Se compara por
# código + nombre normalizado: 6 de los 9 códigos de transporte tienen homónimo
# en el catálogo (7462 es también NIPLE 16", 6878 también CONCRETO 3000 PSI).
PEAJE = ("INT3", "PEAJE")
DERECHOS_BOTADERO = ("7231", "DERECHOS DE BOTADERO")   # es volumen: NO escala con km

# Supuesto inicial de la pantalla de clasificación: la distancia con la que se
# armó la biblioteca. El usuario lo corrige fila por fila.
KM_BASE_DEFECTO = 25.0

# Solo para SUGERIR la categoría al clasificar; el usuario confirma.
# (ámbito, fragmentos de nombre normalizado, categoría)
TRANSPORTE_SUGERENCIAS = (
    ("apu_nombre", ("ESCOMBROS", "BOTADERO"), "botadero"),
    ("insumo_nombre", ("BASES ASFALTICAS", "ASFALTIC"), "mezclas"),
    ("insumo_nombre", ("PETREOS", "GRANULARES"), "granulares"),
)

UNIDAD_TRANSPORTE = "M3-KM"     # unidad de los componentes que escalan con la distancia
```

- [ ] **Step 4: Agregar los modelos a `nucleo/models.py`**

Después de `class ListaPrecios` (antes de `class EventoAuditoria`):

```python
@dataclass(frozen=True)
class ClaseTransporte:
    """Clasificación de un componente de transporte de la biblioteca.

    `volumen` = m³ esponjados que mueve el APU por unidad suya; el rendimiento
    efectivo es `volumen × km_del_proyecto`. `km_base` es la distancia que se
    asumió al clasificar (solo trazabilidad: `volumen = rendimiento / km_base`).
    La identidad es código + nombre porque los códigos se repiten en el catálogo.
    """
    apu_codigo: str
    shift: str
    insumo_codigo: str
    insumo_nombre: str
    categoria: str                # botadero | mezclas | granulares
    volumen: float
    km_base: Optional[float] = None
    actualizado_en: str = ""
    actualizado_por: Optional[str] = None


@dataclass(frozen=True)
class ParametrosProyecto:
    """Distancias y peaje de un proyecto (carpeta de nivel 1).

    Todo `None` = no definido: la regla no toca nada y el costeo es el de hoy.
    `peaje_valor` es dinero (por eso está en `privacy._FORBIDDEN_KEYS`).
    """
    carpeta_id: Optional[int] = None
    km_botadero: Optional[float] = None
    km_mezclas: Optional[float] = None
    km_granulares: Optional[float] = None
    peaje_aplica: Optional[bool] = None
    peaje_valor: Optional[float] = None
    actualizado_en: str = ""
    actualizado_por: Optional[str] = None

    def km(self, categoria: str) -> Optional[float]:
        return {"botadero": self.km_botadero,
                "mezclas": self.km_mezclas,
                "granulares": self.km_granulares}.get(categoria)

    @property
    def vacio(self) -> bool:
        """Sin nada definido la regla es un no-op (garantía de no regresión)."""
        return all(v is None for v in (self.km_botadero, self.km_mezclas,
                                       self.km_granulares, self.peaje_aplica))


@dataclass(frozen=True)
class AjusteProyecto:
    """Excepción puntual de composición para un proyecto. NO ve dinero."""
    apu_codigo: str
    shift: str
    accion: str                   # rendimiento | agregar | quitar | reemplazar
    insumo_codigo: str
    insumo_nombre: str = ""
    unidad: str = ""
    rendimiento: Optional[float] = None
    insumo_nuevo_codigo: str = ""
    insumo_nuevo_nombre: str = ""
    tipo: str = "insumo"          # insumo | apu (sub-APU)
    ref_shift: str = ""
    nota: str = ""
    id: Optional[int] = None
    carpeta_id: Optional[int] = None
    creado_en: str = ""
    creado_por: Optional[str] = None
```

Y junto a las constantes de vocabulario de `calidad_cruce` (después de
`CALIDAD_SIN_PRECIO_CATALOGO`):

```python
CALIDAD_SIN_DISTANCIA = "sin_distancia_proyecto"   # componente M3-KM sin clasificar
```

- [ ] **Step 5: Correr el test y verificar que pasa**

Run: `python -m pytest tests/test_transporte_regla.py -q`
Expected: PASS (4 tests)

- [ ] **Step 6: Commit**

```bash
git add apu_tool/config.py apu_tool/nucleo/models.py tests/test_transporte_regla.py
git commit -m "feat(transporte): vocabulario y modelos de distancias por proyecto"
```

---

### Task 2: La regla de transporte

**Files:**
- Create: `apu_tool/dominio/transporte.py`
- Test: `tests/test_transporte_regla.py` (agregar)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar al final de `tests/test_transporte_regla.py`:

```python
from apu_tool.dominio import transporte
from apu_tool.nucleo.models import ApuComponent


def _comp(cod, nombre, unidad="M3-KM", rend=26.25, tipo="insumo", hist=1000.0):
    return ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo=cod,
                        insumo_nombre=nombre, unidad=unidad, rendimiento=rend,
                        precio_unitario_hist=hist, tipo=tipo)


def _clase(cod, nombre, categoria, volumen):
    return {("4200", "DIURNO", cod): ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo=cod, insumo_nombre=nombre,
        categoria=categoria, volumen=volumen, km_base=25.0)}


def test_sin_parametros_no_toca_nada():
    comps = [_comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    assert transporte.aplicar(comps, "4200", "DIURNO") == comps
    assert transporte.aplicar(comps, "4200", "DIURNO",
                              ParametrosProyecto(), {}, ()) == comps


def test_reescala_mezclas():
    comps = [_comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    cls = _clase("6878", "TRANSPORTE DE BASES ASFALTICAS", "mezclas", 1.05)
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_mezclas=28), cls, ())
    assert out[0].rendimiento == 29.4
    assert out[0].insumo_codigo == "6878"          # solo cambia el rendimiento


def test_km_de_otra_categoria_no_afecta():
    comps = [_comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    cls = _clase("6878", "TRANSPORTE DE BASES ASFALTICAS", "mezclas", 1.05)
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_granulares=32), cls, ())
    assert out[0].rendimiento == 26.25


def test_componente_sin_clasificar_queda_intacto_y_es_pendiente():
    comps = [_comp("7462", "TRANSPORTE DE PETREOS")]
    p = ParametrosProyecto(km_granulares=32)
    assert transporte.aplicar(comps, "4200", "DIURNO", p, {}, ())[0].rendimiento == 26.25
    assert transporte.pendientes(comps, "4200", "DIURNO", p, {}) == ("7462",)


def test_nombre_distinto_no_se_reescala():
    """El mismo código con OTRO nombre es OTRO insumo (7462 es también NIPLE 16")."""
    comps = [_comp("7462", 'NIPLE 16" ACERO CARBON', unidad="UN", rend=1.0)]
    cls = _clase("7462", "TRANSPORTE DE PETREOS", "granulares", 1.05)
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_granulares=32), cls, ())
    assert out[0].rendimiento == 1.0


def test_derechos_de_botadero_nunca_escalan():
    comps = [_comp("7231", "DERECHOS DE BOTADERO", unidad="M3", rend=1.3)]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_botadero=34), {}, ())
    assert out[0].rendimiento == 1.3
    assert transporte.pendientes(comps, "4200", "DIURNO",
                                 ParametrosProyecto(km_botadero=34), {}) == ()


def test_peaje_se_quita_si_no_aplica():
    comps = [_comp("INT3", "PEAJE", unidad="GLB", rend=1.0),
             _comp("6878", "TRANSPORTE DE BASES ASFALTICAS")]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(peaje_aplica=False), {}, ())
    assert [c.insumo_codigo for c in out] == ["6878"]


def test_peaje_se_conserva_si_aplica():
    comps = [_comp("INT3", "PEAJE", unidad="GLB", rend=1.0)]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(peaje_aplica=True, peaje_valor=12400),
                             {}, ())
    assert len(out) == 1 and out[0].rendimiento == 1.0   # el valor lo aplica pricing.py


def test_subapu_no_se_toca_aqui():
    comps = [_comp("3017", "TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS",
                   unidad="M3", rend=1.3, tipo="apu")]
    out = transporte.aplicar(comps, "4200", "DIURNO",
                             ParametrosProyecto(km_botadero=34), {}, ())
    assert out[0].rendimiento == 1.3 and out[0].tipo == "apu"


def test_es_peaje_y_es_derechos():
    assert transporte.es_peaje(_comp("INT3", "PEAJE", unidad="GLB")) is True
    assert transporte.es_peaje(_comp("INT3", "OTRA COSA", unidad="GLB")) is False
    assert transporte.es_derechos(_comp("7231", "DERECHOS DE BOTADERO")) is True
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_transporte_regla.py -q`
Expected: FAIL con `ModuleNotFoundError: No module named 'apu_tool.dominio.transporte'`

- [ ] **Step 3: Escribir `apu_tool/dominio/transporte.py`**

```python
"""
Desviaciones de un proyecto respecto de la biblioteca de APUs.

Dos capas sobre la composición que devuelve la biblioteca:
  1. REGLA de transporte: el rendimiento de un componente de acarreo clasificado
     pasa a ser `volumen × km_de_su_categoría` (el volumen sale de la
     clasificación de la biblioteca; los km, de los parámetros del proyecto).
  2. AJUSTES del proyecto: excepciones explícitas (rendimiento / agregar /
     quitar / reemplazar) que GANAN sobre la regla.

La composición de la biblioteca NUNCA se muta: se devuelve una lista nueva.

Este módulo no ve dinero. El precio del peaje lo aplica `dominio/pricing.py`,
el único módulo que ve dinero. `cargar_contexto` es lo único que lee la base
(mismo criterio que `PricingEngine`, que también recibe el `Almacen`).

IDENTIDAD: un componente se reconoce por código + nombre normalizado, nunca por
código solo — en el catálogo 6 de los 9 códigos de transporte tienen homónimo
(`7462` es también NIPLE 16", `6878` también CONCRETO 3000 PSI). Misma lección
que el fix de detección de sub-APUs.
"""
from __future__ import annotations

from dataclasses import dataclass, replace
from typing import Iterable, Optional, Sequence

from apu_tool import config
from apu_tool.nucleo.models import (
    AjusteProyecto, ApuComponent, ClaseTransporte, ParametrosProyecto,
)
from apu_tool.nucleo.texto import normalizar

# Los ajustes se aplican en este orden para que 'agregar' pueda reponer algo que
# 'quitar' sacó y para que 'rendimiento' actúe sobre el insumo ya reemplazado.
ORDEN_ACCIONES = ("quitar", "reemplazar", "rendimiento", "agregar")

Clasificacion = dict[tuple[str, str, str], ClaseTransporte]


@dataclass(frozen=True)
class ContextoProyecto:
    """Todo lo que el motor necesita para costear con las desviaciones del proyecto."""
    params: ParametrosProyecto
    clasificacion: Clasificacion
    ajustes: tuple[AjusteProyecto, ...] = ()

    @property
    def vacio(self) -> bool:
        return self.params.vacio and not self.ajustes


def _codigo_base(codigo: str) -> str:
    """`"INT3 N"` -> `"INT3"`. Los nocturnos comparten identidad de insumo."""
    cod = (codigo or "").strip()
    return cod[:-2].strip() if cod.upper().endswith(" N") else cod


def _mismo(comp: ApuComponent, codigo: str, nombre: str) -> bool:
    return (_codigo_base(comp.insumo_codigo) == codigo
            and normalizar(comp.insumo_nombre) == normalizar(nombre))


def es_peaje(comp: ApuComponent) -> bool:
    return _mismo(comp, *config.PEAJE)


def es_derechos(comp: ApuComponent) -> bool:
    return _mismo(comp, *config.DERECHOS_BOTADERO)


def _clase_de(comp: ApuComponent, apu_codigo: str, shift: str,
              clasificacion: Clasificacion) -> Optional[ClaseTransporte]:
    cls = clasificacion.get((apu_codigo, shift, comp.insumo_codigo))
    if cls is None:
        return None
    # El nombre manda: la clasificación es de UN insumo, no de un código.
    if normalizar(cls.insumo_nombre) != normalizar(comp.insumo_nombre):
        return None
    return cls


def _escalable(comp: ApuComponent) -> bool:
    """Un componente que escala con la distancia: insumo (no sub-APU), en M3-KM,
    que no es el peaje ni los derechos de botadero."""
    return ((comp.tipo or "insumo") != "apu"
            and normalizar(comp.unidad) == normalizar(config.UNIDAD_TRANSPORTE)
            and not es_peaje(comp) and not es_derechos(comp))


def pendientes(componentes: Sequence[ApuComponent], apu_codigo: str, shift: str,
               params: Optional[ParametrosProyecto],
               clasificacion: Optional[Clasificacion]) -> tuple[str, ...]:
    """Códigos de componentes de acarreo que el proyecto NO pudo reescalar porque
    les falta clasificación. Son los que alertan: preferimos avisar a costear con
    una distancia equivocada en silencio."""
    if params is None or params.vacio:
        return ()
    clasificacion = clasificacion or {}
    faltan = []
    for c in componentes:
        if not _escalable(c):
            continue
        if _clase_de(c, apu_codigo, shift, clasificacion) is None:
            faltan.append(c.insumo_codigo)
    return tuple(faltan)


def aplicar(componentes: Iterable[ApuComponent], apu_codigo: str, shift: str,
            params: Optional[ParametrosProyecto] = None,
            clasificacion: Optional[Clasificacion] = None,
            ajustes: Sequence[AjusteProyecto] = ()) -> list[ApuComponent]:
    """Composición EFECTIVA del proyecto. Sin parámetros ni ajustes devuelve la
    misma composición (garantía de no regresión)."""
    comps = list(componentes)
    if params is not None and not params.vacio:
        comps = _aplicar_regla(comps, apu_codigo, shift, params, clasificacion or {})
    if ajustes:
        comps = _aplicar_ajustes(comps, apu_codigo, shift, ajustes)
    return comps


def _aplicar_regla(comps: list[ApuComponent], apu_codigo: str, shift: str,
                   params: ParametrosProyecto,
                   clasificacion: Clasificacion) -> list[ApuComponent]:
    salida: list[ApuComponent] = []
    for c in comps:
        if (c.tipo or "insumo") == "apu":
            salida.append(c)               # el sub-APU se reescala en su propia pasada
            continue
        if es_peaje(c):
            if params.peaje_aplica is False:
                continue                   # se QUITA: un peaje en $0 está prohibido
            salida.append(c)               # el valor lo pone pricing.py
            continue
        if es_derechos(c) or not _escalable(c):
            salida.append(c)               # volumen, no distancia
            continue
        cls = _clase_de(c, apu_codigo, shift, clasificacion)
        km = params.km(cls.categoria) if cls is not None else None
        if cls is None or km is None:
            salida.append(c)               # sin clasificar o sin km: intacto (ver pendientes)
            continue
        salida.append(replace(c, rendimiento=round(cls.volumen * float(km), 6)))
    return salida


def _aplicar_ajustes(comps: list[ApuComponent], apu_codigo: str, shift: str,
                     ajustes: Sequence[AjusteProyecto]) -> list[ApuComponent]:
    mios = [a for a in ajustes if a.apu_codigo == apu_codigo and a.shift == shift]
    if not mios:
        return comps
    salida = list(comps)
    for accion in ORDEN_ACCIONES:
        for a in (x for x in mios if x.accion == accion):
            salida = _un_ajuste(salida, a, apu_codigo, shift)
    return salida


def _un_ajuste(comps: list[ApuComponent], a: AjusteProyecto,
               apu_codigo: str, shift: str) -> list[ApuComponent]:
    if a.accion == "quitar":
        return [c for c in comps if not _mismo(c, a.insumo_codigo, a.insumo_nombre)]
    if a.accion == "reemplazar":
        # `precio_unitario_hist=0.0` a propósito: el histórico embebido es del insumo
        # VIEJO. Conservarlo costearía el insumo nuevo con el precio del viejo en
        # silencio; con 0 cae a "sin precio" y la alerta lo delata.
        return [replace(c, insumo_codigo=a.insumo_nuevo_codigo,
                        insumo_nombre=a.insumo_nuevo_nombre,
                        precio_unitario_hist=0.0)
                if _mismo(c, a.insumo_codigo, a.insumo_nombre) else c
                for c in comps]
    if a.accion == "rendimiento":
        return [replace(c, rendimiento=float(a.rendimiento))
                if _mismo(c, a.insumo_codigo, a.insumo_nombre) else c
                for c in comps]
    if a.accion == "agregar":
        # Idempotente: si ya está, solo se ajusta el rendimiento (no se duplica).
        if any(_mismo(c, a.insumo_codigo, a.insumo_nombre) for c in comps):
            return [replace(c, rendimiento=float(a.rendimiento))
                    if _mismo(c, a.insumo_codigo, a.insumo_nombre) else c
                    for c in comps]
        return comps + [ApuComponent(
            apu_codigo=apu_codigo, shift=shift, insumo_codigo=a.insumo_codigo,
            insumo_nombre=a.insumo_nombre, unidad=a.unidad,
            rendimiento=float(a.rendimiento), precio_unitario_hist=0.0,
            tipo=a.tipo or "insumo", ref_shift=a.ref_shift or "")]
    return comps
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_transporte_regla.py -q`
Expected: PASS (14 tests)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/transporte.py tests/test_transporte_regla.py
git commit -m "feat(transporte): regla de distancias por categoria (modulo puro)"
```

---

### Task 3: Los ajustes puntuales

**Files:**
- Test: `tests/test_transporte_ajustes.py`
- Modify: `apu_tool/dominio/transporte.py` (solo si algún test falla)

- [ ] **Step 1: Escribir los tests que fallan**

```python
# tests/test_transporte_ajustes.py
"""Ajustes puntuales del proyecto: las 4 acciones y su precedencia sobre la regla."""
from apu_tool.dominio import transporte
from apu_tool.nucleo.models import (
    AjusteProyecto, ApuComponent, ClaseTransporte, ParametrosProyecto)


def _comp(cod, nombre, unidad="M3", rend=1.0, hist=500.0):
    return ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo=cod,
                        insumo_nombre=nombre, unidad=unidad, rendimiento=rend,
                        precio_unitario_hist=hist)


BASE = [_comp("6722", "SUBBASE GRANULAR B-400"), _comp("7231", "DERECHOS DE BOTADERO")]


def _aj(accion, **kw):
    return AjusteProyecto(apu_codigo="4390", shift="DIURNO", accion=accion, **kw)


def test_quitar():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("quitar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400")])
    assert [c.insumo_codigo for c in out] == ["7231"]


def test_rendimiento():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("rendimiento", insumo_codigo="6722",
            insumo_nombre="SUBBASE GRANULAR B-400", rendimiento=1.25)])
    assert out[0].rendimiento == 1.25 and out[1].rendimiento == 1.0


def test_agregar():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("agregar", insumo_codigo="9001", insumo_nombre="GEOTEXTIL NT 2000",
            unidad="M2", rendimiento=1.1)])
    assert len(out) == 3
    nuevo = out[-1]
    assert (nuevo.insumo_codigo, nuevo.rendimiento, nuevo.unidad) == ("9001", 1.1, "M2")
    assert nuevo.precio_unitario_hist == 0.0     # sin histórico ajeno


def test_agregar_es_idempotente():
    aj = _aj("agregar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400",
             unidad="M3", rendimiento=2.0)
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[aj])
    assert len(out) == 2 and out[0].rendimiento == 2.0


def test_reemplazar_borra_el_historico_del_viejo():
    out = transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[
        _aj("reemplazar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400",
            insumo_nuevo_codigo="7004", insumo_nuevo_nombre="BASE GRANULAR B-600")])
    assert out[0].insumo_codigo == "7004"
    assert out[0].insumo_nombre == "BASE GRANULAR B-600"
    assert out[0].precio_unitario_hist == 0.0


def test_ajuste_de_otro_apu_no_aplica():
    aj = AjusteProyecto(apu_codigo="9999", shift="DIURNO", accion="quitar",
                        insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400")
    assert transporte.aplicar(BASE, "4390", "DIURNO", ajustes=[aj]) == BASE


def test_el_ajuste_gana_sobre_la_regla():
    comps = [ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
                          insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                          rendimiento=26.25, precio_unitario_hist=900.0)]
    cls = {("4390", "DIURNO", "7462"): ClaseTransporte(
        apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
        insumo_nombre="TRANSPORTE DE PETREOS", categoria="granulares",
        volumen=1.05, km_base=25.0)}
    out = transporte.aplicar(
        comps, "4390", "DIURNO", ParametrosProyecto(km_granulares=32), cls,
        [_aj("rendimiento", insumo_codigo="7462",
             insumo_nombre="TRANSPORTE DE PETREOS", rendimiento=40.0)])
    assert out[0].rendimiento == 40.0     # la regla habría puesto 33.6


def test_quitar_lo_que_la_regla_conservo():
    comps = [_comp("INT3", "PEAJE", unidad="GLB")]
    out = transporte.aplicar(
        comps, "4390", "DIURNO", ParametrosProyecto(peaje_aplica=True, peaje_valor=100),
        {}, [_aj("quitar", insumo_codigo="INT3", insumo_nombre="PEAJE")])
    assert out == []


def test_no_muta_la_lista_de_entrada():
    entrada = list(BASE)
    transporte.aplicar(entrada, "4390", "DIURNO", ajustes=[
        _aj("quitar", insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400")])
    assert entrada == BASE
```

- [ ] **Step 2: Correr los tests**

Run: `python -m pytest tests/test_transporte_ajustes.py -q`
Expected: PASS (10 tests) — el módulo de la Task 2 ya los cubre. Si alguno falla,
corregir `_un_ajuste` en `apu_tool/dominio/transporte.py` hasta que pase, sin
cambiar los tests.

- [ ] **Step 3: Commit**

```bash
git add tests/test_transporte_ajustes.py
git commit -m "test(transporte): las 4 acciones de ajuste y su precedencia"
```

---

## FASE 2 — Persistencia

### Task 4: `componente_transporte` en SQLite

**Files:**
- Modify: `db/apus.sql`
- Modify: `apu_tool/datos/apus_db.py`
- Modify: `apu_tool/datos/repositorio.py` (`RepositorioApus`)
- Test: `tests/test_transporte_db.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_transporte_db.py
"""Persistencia de la clasificación de transporte de la biblioteca."""
from apu_tool.datos.apus_db import ApusDB
from apu_tool.nucleo.models import Apu, ApuComponent, ClaseTransporte


def _db(tmp_path):
    db = ApusDB(tmp_path / "apus.db")
    db.init_schema()
    db.insert_apus([Apu(codigo="4200", nombre="MEZCLA MD20", unidad="M3",
                        shift="DIURNO", grupo="PAVIMENTOS")])
    db.insert_components([
        ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                     insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=900.0),
        ApuComponent(apu_codigo="4200", shift="DIURNO", insumo_codigo="7172",
                     insumo_nombre="MEZCLA ASFALTICA MD20", unidad="M3",
                     rendimiento=1.0, precio_unitario_hist=500000.0),
    ])
    return db


def test_clasificacion_vacia_al_inicio(tmp_path):
    assert _db(tmp_path).get_clasificacion_transporte() == []


def test_upsert_y_lectura(tmp_path):
    db = _db(tmp_path)
    fila = ClaseTransporte(apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
                           insumo_nombre="TRANSPORTE DE BASES ASFALTICAS",
                           categoria="mezclas", volumen=1.05, km_base=25.0)
    assert db.set_clasificacion_transporte([fila], actualizado_por="yo@test.co") == 1
    leidas = db.get_clasificacion_transporte()
    assert len(leidas) == 1
    assert (leidas[0].categoria, leidas[0].volumen, leidas[0].km_base) == ("mezclas", 1.05, 25.0)
    # Reescribir la misma clave actualiza, no duplica.
    db.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", categoria="mezclas",
        volumen=1.30, km_base=20.0)])
    leidas = db.get_clasificacion_transporte()
    assert len(leidas) == 1 and leidas[0].volumen == 1.30


def test_candidatos_solo_las_filas_m3_km(tmp_path):
    db = _db(tmp_path)
    cands = db.componentes_transporte_candidatos()
    assert [c["insumo_codigo"] for c in cands] == ["6878"]
    c = cands[0]
    assert c["apu_codigo"] == "4200" and c["apu_nombre"] == "MEZCLA MD20"
    assert c["rendimiento"] == 26.25 and c["unidad"] == "M3-KM"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_transporte_db.py -q`
Expected: FAIL con `AttributeError: 'ApusDB' object has no attribute 'get_clasificacion_transporte'`

- [ ] **Step 3: Agregar la tabla a `db/apus.sql`**

Al final del archivo:

```sql
-- Clasificación de los componentes de acarreo: qué categoría son y cuántos m3
-- esponjados mueven por unidad de APU. El rendimiento efectivo de un proyecto es
-- volumen * km_del_proyecto. Tabla APARTE de apu_componentes a propósito: esa la
-- reescriben seed/autoría/importadores con seq nuevo en cada semillado.
CREATE TABLE IF NOT EXISTS componente_transporte (
    apu_codigo      TEXT NOT NULL,
    shift           TEXT NOT NULL,
    insumo_codigo   TEXT NOT NULL,
    insumo_nombre   TEXT NOT NULL,   -- identidad real: codigo + nombre
    categoria       TEXT NOT NULL,   -- botadero | mezclas | granulares
    volumen         REAL NOT NULL,
    km_base         REAL,
    actualizado_en  TEXT NOT NULL,
    actualizado_por TEXT,
    PRIMARY KEY (apu_codigo, shift, insumo_codigo)
);
```

- [ ] **Step 4: Agregar los métodos a `apu_tool/datos/apus_db.py`**

Importar `ClaseTransporte` en el import de `nucleo.models` y agregar, después de
`get_components_bulk`:

```python
    # ---- clasificación de transporte (distancias por proyecto) ----
    def get_clasificacion_transporte(self) -> list[ClaseTransporte]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, insumo_codigo, insumo_nombre, categoria, "
                "       volumen, km_base, actualizado_en, actualizado_por "
                "FROM componente_transporte").fetchall()
        return [ClaseTransporte(
            apu_codigo=r["apu_codigo"], shift=r["shift"],
            insumo_codigo=r["insumo_codigo"], insumo_nombre=r["insumo_nombre"],
            categoria=r["categoria"], volumen=r["volumen"], km_base=r["km_base"],
            actualizado_en=r["actualizado_en"] or "",
            actualizado_por=r["actualizado_por"]) for r in rows]

    def set_clasificacion_transporte(self, filas: Iterable[ClaseTransporte],
                                     conn=None, actualizado_por: Optional[str] = None) -> int:
        import datetime as _dt
        ahora = _dt.datetime.now().isoformat(timespec="seconds")
        rows = [(f.apu_codigo, f.shift, f.insumo_codigo, f.insumo_nombre,
                 f.categoria, float(f.volumen), f.km_base, ahora, actualizado_por)
                for f in filas]
        sql = ("INSERT OR REPLACE INTO componente_transporte "
               "(apu_codigo, shift, insumo_codigo, insumo_nombre, categoria, "
               " volumen, km_base, actualizado_en, actualizado_por) "
               "VALUES (?,?,?,?,?,?,?,?,?)")
        if conn is not None:
            conn.executemany(sql, rows)
            return len(rows)
        with self.connect() as c:
            c.executemany(sql, rows)
        return len(rows)

    def componentes_transporte_candidatos(self) -> list[dict]:
        """Filas de la biblioteca que escalan con la distancia (unidad M3-KM), con
        su APU dueño. Es la entrada de la pantalla de clasificación."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT c.apu_codigo, c.shift, a.nombre AS apu_nombre, "
                "       c.insumo_codigo, c.insumo_nombre, c.unidad, c.rendimiento "
                "FROM apu_componentes c "
                "LEFT JOIN apus a ON a.codigo = c.apu_codigo AND a.shift = c.shift "
                "WHERE UPPER(c.unidad) = ? AND COALESCE(c.tipo,'insumo') <> 'apu' "
                "ORDER BY c.apu_codigo, c.shift, c.insumo_codigo",
                (config.UNIDAD_TRANSPORTE,)).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Agregar al Protocol `RepositorioApus` en `apu_tool/datos/repositorio.py`**

Después de `get_components_bulk`, e importando `ClaseTransporte`:

```python
    def get_clasificacion_transporte(self) -> list[ClaseTransporte]:
        """Clasificación de los componentes de acarreo (categoría + volumen)."""
        ...
    def set_clasificacion_transporte(self, filas: Iterable[ClaseTransporte],
                                     conn=None,
                                     actualizado_por: Optional[str] = None) -> int: ...
    def componentes_transporte_candidatos(self) -> list[dict]:
        """Filas M3-KM de la biblioteca con su APU dueño, para clasificar."""
        ...
```

- [ ] **Step 6: Correr y verificar que pasa**

Run: `python -m pytest tests/test_transporte_db.py tests/test_db_repository.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add db/apus.sql apu_tool/datos/apus_db.py apu_tool/datos/repositorio.py tests/test_transporte_db.py
git commit -m "feat(datos): tabla componente_transporte en SQLite"
```

---

### Task 5: `proyecto_parametros` y `proyecto_ajuste` en SQLite

**Files:**
- Modify: `db/corridas.sql`
- Modify: `apu_tool/datos/carpetas_db.py`
- Modify: `apu_tool/datos/repositorio.py` (`RepositorioCarpetas`)
- Test: `tests/test_transporte_db.py` (agregar)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_transporte_db.py`:

```python
from apu_tool.datos.carpetas_db import CarpetasDB
from apu_tool.datos.corridas_db import CorridasDB
from apu_tool.nucleo.models import AjusteProyecto, ParametrosProyecto


def _carpetas(tmp_path):
    CorridasDB(tmp_path / "c.db").init_schema()      # crea el esquema compartido
    return CarpetasDB(tmp_path / "c.db")


def test_parametros_inexistentes_son_none(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Calle 13")
    assert car.get_parametros(cid) is None


def test_set_y_get_parametros(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Metro")
    car.set_parametros(ParametrosProyecto(
        carpeta_id=cid, km_botadero=34, km_mezclas=28, km_granulares=32,
        peaje_aplica=True, peaje_valor=12400), actualizado_por="yo@test.co")
    p = car.get_parametros(cid)
    assert (p.km_botadero, p.km_mezclas, p.km_granulares) == (34, 28, 32)
    assert p.peaje_aplica is True and p.peaje_valor == 12400
    assert p.actualizado_en and p.actualizado_por == "yo@test.co"
    # Reescribir actualiza, no duplica.
    car.set_parametros(ParametrosProyecto(carpeta_id=cid, km_botadero=21,
                                         peaje_aplica=False))
    p = car.get_parametros(cid)
    assert p.km_botadero == 21 and p.peaje_aplica is False and p.km_mezclas is None


def test_crud_de_ajustes(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Metro")
    assert car.listar_ajustes(cid) == []
    aid = car.crear_ajuste(AjusteProyecto(
        carpeta_id=cid, apu_codigo="4390", shift="DIURNO", accion="agregar",
        insumo_codigo="9001", insumo_nombre="GEOTEXTIL NT 2000", unidad="M2",
        rendimiento=1.1, nota="lo exige la especificación"), creado_por="yo@test.co")
    ajustes = car.listar_ajustes(cid)
    assert len(ajustes) == 1 and ajustes[0].id == aid
    assert ajustes[0].accion == "agregar" and ajustes[0].rendimiento == 1.1
    assert car.borrar_ajuste(cid, aid) is True
    assert car.listar_ajustes(cid) == []
    assert car.borrar_ajuste(cid, aid) is False


def test_borrar_la_carpeta_borra_sus_parametros_y_ajustes(tmp_path):
    car = _carpetas(tmp_path)
    cid = car.crear("Temporal")
    car.set_parametros(ParametrosProyecto(carpeta_id=cid, km_botadero=30))
    car.crear_ajuste(AjusteProyecto(carpeta_id=cid, apu_codigo="1", shift="DIURNO",
                                    accion="quitar", insumo_codigo="9",
                                    insumo_nombre="X"))
    assert car.eliminar(cid) is True
    assert car.get_parametros(cid) is None and car.listar_ajustes(cid) == []
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_transporte_db.py -q -k parametros`
Expected: FAIL con `AttributeError: 'CarpetasDB' object has no attribute 'get_parametros'`

- [ ] **Step 3: Agregar las tablas a `db/corridas.sql`**

Después de la tabla `carpeta` y su índice:

```sql
-- Distancias de acarreo y peaje del proyecto. Una fila por carpeta de nivel 1.
-- Sin fila = comportamiento de siempre (la regla no toca nada).
CREATE TABLE IF NOT EXISTS proyecto_parametros (
  carpeta_id      INTEGER PRIMARY KEY REFERENCES carpeta(id) ON DELETE CASCADE,
  km_botadero     REAL,
  km_mezclas      REAL,
  km_granulares   REAL,
  peaje_aplica    INTEGER,    -- NULL = sin definir, 0 = no hay peaje, 1 = sí
  peaje_valor     REAL,
  actualizado_en  TEXT NOT NULL,
  actualizado_por TEXT
);

-- Excepciones de composición del proyecto. Ganan sobre la regla de transporte.
-- Solo estructura: no guarda dinero.
CREATE TABLE IF NOT EXISTS proyecto_ajuste (
  id                  INTEGER PRIMARY KEY AUTOINCREMENT,
  carpeta_id          INTEGER NOT NULL REFERENCES carpeta(id) ON DELETE CASCADE,
  apu_codigo          TEXT NOT NULL,
  shift               TEXT NOT NULL,
  accion              TEXT NOT NULL,   -- rendimiento | agregar | quitar | reemplazar
  insumo_codigo       TEXT NOT NULL,
  insumo_nombre       TEXT NOT NULL DEFAULT '',
  unidad              TEXT NOT NULL DEFAULT '',
  rendimiento         REAL,
  insumo_nuevo_codigo TEXT,
  insumo_nuevo_nombre TEXT,
  tipo                TEXT NOT NULL DEFAULT 'insumo',
  ref_shift           TEXT NOT NULL DEFAULT '',
  nota                TEXT NOT NULL DEFAULT '',
  creado_en           TEXT NOT NULL,
  creado_por          TEXT,
  UNIQUE (carpeta_id, apu_codigo, shift, accion, insumo_codigo)
);
CREATE INDEX IF NOT EXISTS ix_proyecto_ajuste ON proyecto_ajuste(carpeta_id);
```

- [ ] **Step 4: Agregar los métodos a `apu_tool/datos/carpetas_db.py`**

Importar `AjusteProyecto, ParametrosProyecto` de `nucleo.models` y agregar al final
de la clase:

```python
    # ---- parámetros de transporte del proyecto ----
    def get_parametros(self, carpeta_id: int) -> Optional[ParametrosProyecto]:
        with self.connect() as conn:
            r = conn.execute("SELECT * FROM proyecto_parametros WHERE carpeta_id=?",
                             (int(carpeta_id),)).fetchone()
        if r is None:
            return None
        return ParametrosProyecto(
            carpeta_id=r["carpeta_id"], km_botadero=r["km_botadero"],
            km_mezclas=r["km_mezclas"], km_granulares=r["km_granulares"],
            peaje_aplica=None if r["peaje_aplica"] is None else bool(r["peaje_aplica"]),
            peaje_valor=r["peaje_valor"], actualizado_en=r["actualizado_en"] or "",
            actualizado_por=r["actualizado_por"])

    def set_parametros(self, params: ParametrosProyecto, conn=None,
                       actualizado_por: Optional[str] = None) -> None:
        import datetime as _dt
        ahora = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT OR REPLACE INTO proyecto_parametros "
               "(carpeta_id, km_botadero, km_mezclas, km_granulares, peaje_aplica, "
               " peaje_valor, actualizado_en, actualizado_por) VALUES (?,?,?,?,?,?,?,?)")
        p = (int(params.carpeta_id), params.km_botadero, params.km_mezclas,
             params.km_granulares,
             None if params.peaje_aplica is None else int(params.peaje_aplica),
             params.peaje_valor, ahora, actualizado_por or params.actualizado_por)
        if conn is not None:
            conn.execute(sql, p)
            return
        with self.connect() as c:
            c.execute(sql, p)

    # ---- ajustes puntuales del proyecto ----
    def _fila_ajuste(self, r) -> AjusteProyecto:
        return AjusteProyecto(
            id=r["id"], carpeta_id=r["carpeta_id"], apu_codigo=r["apu_codigo"],
            shift=r["shift"], accion=r["accion"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"] or "", unidad=r["unidad"] or "",
            rendimiento=r["rendimiento"],
            insumo_nuevo_codigo=r["insumo_nuevo_codigo"] or "",
            insumo_nuevo_nombre=r["insumo_nuevo_nombre"] or "",
            tipo=r["tipo"] or "insumo", ref_shift=r["ref_shift"] or "",
            nota=r["nota"] or "", creado_en=r["creado_en"] or "",
            creado_por=r["creado_por"])

    def listar_ajustes(self, carpeta_id: int) -> list[AjusteProyecto]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM proyecto_ajuste WHERE carpeta_id=? "
                "ORDER BY apu_codigo, shift, accion, insumo_codigo",
                (int(carpeta_id),)).fetchall()
        return [self._fila_ajuste(r) for r in rows]

    def crear_ajuste(self, ajuste: AjusteProyecto, conn=None,
                     creado_por: Optional[str] = None) -> int:
        import datetime as _dt
        creado_en = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT OR REPLACE INTO proyecto_ajuste "
               "(carpeta_id, apu_codigo, shift, accion, insumo_codigo, insumo_nombre, "
               " unidad, rendimiento, insumo_nuevo_codigo, insumo_nuevo_nombre, tipo, "
               " ref_shift, nota, creado_en, creado_por) "
               "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)")
        p = (int(ajuste.carpeta_id), ajuste.apu_codigo, ajuste.shift, ajuste.accion,
             ajuste.insumo_codigo, ajuste.insumo_nombre, ajuste.unidad,
             ajuste.rendimiento, ajuste.insumo_nuevo_codigo,
             ajuste.insumo_nuevo_nombre, ajuste.tipo or "insumo", ajuste.ref_shift,
             ajuste.nota, creado_en, creado_por or ajuste.creado_por)
        if conn is not None:
            return int(conn.execute(sql, p).lastrowid)
        with self.connect() as c:
            return int(c.execute(sql, p).lastrowid)

    def borrar_ajuste(self, carpeta_id: int, ajuste_id: int, conn=None) -> bool:
        sql = "DELETE FROM proyecto_ajuste WHERE carpeta_id=? AND id=?"
        p = (int(carpeta_id), int(ajuste_id))
        if conn is not None:
            return conn.execute(sql, p).rowcount > 0
        with self.connect() as c:
            return c.execute(sql, p).rowcount > 0
```

- [ ] **Step 5: Agregar los 5 métodos al Protocol `RepositorioCarpetas`**

```python
    def get_parametros(self, carpeta_id: int) -> Optional[ParametrosProyecto]:
        """Distancias/peaje del proyecto. None = sin definir (costeo de siempre)."""
        ...
    def set_parametros(self, params: ParametrosProyecto, conn=None,
                       actualizado_por: Optional[str] = None) -> None: ...
    def listar_ajustes(self, carpeta_id: int) -> list[AjusteProyecto]: ...
    def crear_ajuste(self, ajuste: AjusteProyecto, conn=None,
                     creado_por: Optional[str] = None) -> int: ...
    def borrar_ajuste(self, carpeta_id: int, ajuste_id: int, conn=None) -> bool: ...
```

- [ ] **Step 6: Correr y verificar que pasa**

Run: `python -m pytest tests/test_transporte_db.py tests/test_carpetas_db.py -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add db/corridas.sql apu_tool/datos/carpetas_db.py apu_tool/datos/repositorio.py tests/test_transporte_db.py
git commit -m "feat(datos): parametros y ajustes por proyecto en SQLite"
```

---

### Task 6: Espejo Postgres

**Files:**
- Modify: `db/pg/apus.sql`, `db/pg/corridas.sql`
- Modify: `apu_tool/datos/pg/apus_pg.py`, `apu_tool/datos/pg/carpetas_pg.py`
- Create: `supabase/migrations/0006_transporte_proyecto_rls.sql`
- Test: `tests/test_paridad_backends.py` (extender), `tests/test_transporte_pg.py`

- [ ] **Step 1: Escribir el test de paridad de firmas**

Crear `tests/test_transporte_pg.py`:

```python
"""Los dos backends son espejo 1:1 en los métodos nuevos de transporte.

Sin Postgres real se comparan firmas (guardia barato contra el drift). Con
TEST_DATABASE_URL corre además el contrato real.
"""
import inspect
import os

import pytest

from apu_tool.datos.apus_db import ApusDB
from apu_tool.datos.carpetas_db import CarpetasDB
from apu_tool.datos.pg.apus_pg import ApusPg
from apu_tool.datos.pg.carpetas_pg import CarpetasPg
from apu_tool.nucleo.models import AjusteProyecto, ClaseTransporte, ParametrosProyecto

_APUS = ["get_clasificacion_transporte", "set_clasificacion_transporte",
         "componentes_transporte_candidatos"]
_CARPETAS = ["get_parametros", "set_parametros", "listar_ajustes", "crear_ajuste",
             "borrar_ajuste"]


@pytest.mark.parametrize("nombre", _APUS)
def test_apus_mismo_metodo_en_ambos_backends(nombre):
    a, b = getattr(ApusDB, nombre), getattr(ApusPg, nombre)
    assert inspect.signature(a) == inspect.signature(b), nombre


@pytest.mark.parametrize("nombre", _CARPETAS)
def test_carpetas_mismo_metodo_en_ambos_backends(nombre):
    a, b = getattr(CarpetasDB, nombre), getattr(CarpetasPg, nombre)
    assert inspect.signature(a) == inspect.signature(b), nombre


@pytest.mark.skipif(not os.environ.get("TEST_DATABASE_URL"),
                    reason="requiere TEST_DATABASE_URL (Postgres desechable)")
def test_contrato_real_postgres():
    from apu_tool.datos.pg.conexion import Conexion
    cx = Conexion(os.environ["TEST_DATABASE_URL"])
    apus, carpetas = ApusPg(cx), CarpetasPg(cx)
    apus.reset()
    from apu_tool.datos.pg.corridas_pg import CorridasPg
    CorridasPg(cx).reset()
    cid = carpetas.crear("Metro")
    assert carpetas.get_parametros(cid) is None
    carpetas.set_parametros(ParametrosProyecto(carpeta_id=cid, km_botadero=34,
                                              peaje_aplica=True, peaje_valor=12400))
    p = carpetas.get_parametros(cid)
    assert p.km_botadero == 34 and p.peaje_aplica is True
    aid = carpetas.crear_ajuste(AjusteProyecto(
        carpeta_id=cid, apu_codigo="4390", shift="DIURNO", accion="quitar",
        insumo_codigo="6722", insumo_nombre="SUBBASE GRANULAR B-400"))
    assert len(carpetas.listar_ajustes(cid)) == 1
    assert carpetas.borrar_ajuste(cid, aid) is True
    apus.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4200", shift="DIURNO", insumo_codigo="6878",
        insumo_nombre="TRANSPORTE DE BASES ASFALTICAS", categoria="mezclas",
        volumen=1.05, km_base=25.0)])
    assert len(apus.get_clasificacion_transporte()) == 1
    cx.cerrar()
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_transporte_pg.py -q`
Expected: FAIL con `AttributeError: type object 'ApusPg' has no attribute 'get_clasificacion_transporte'`

- [ ] **Step 3: Agregar el DDL de Postgres**

Al final de `db/pg/apus.sql`:

```sql
CREATE TABLE IF NOT EXISTS apus.componente_transporte (
    apu_codigo      TEXT NOT NULL,
    shift           TEXT NOT NULL,
    insumo_codigo   TEXT NOT NULL,
    insumo_nombre   TEXT NOT NULL,
    categoria       TEXT NOT NULL,
    volumen         DOUBLE PRECISION NOT NULL,
    km_base         DOUBLE PRECISION,
    actualizado_en  TEXT NOT NULL,
    actualizado_por TEXT,
    PRIMARY KEY (apu_codigo, shift, insumo_codigo)
);
```

En `db/pg/corridas.sql`, después de `corridas.carpeta`:

```sql
CREATE TABLE IF NOT EXISTS corridas.proyecto_parametros (
    carpeta_id      BIGINT PRIMARY KEY REFERENCES corridas.carpeta(id) ON DELETE CASCADE,
    km_botadero     DOUBLE PRECISION,
    km_mezclas      DOUBLE PRECISION,
    km_granulares   DOUBLE PRECISION,
    peaje_aplica    SMALLINT,
    peaje_valor     DOUBLE PRECISION,
    actualizado_en  TEXT NOT NULL,
    actualizado_por TEXT
);

CREATE TABLE IF NOT EXISTS corridas.proyecto_ajuste (
    id                  BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    carpeta_id          BIGINT NOT NULL REFERENCES corridas.carpeta(id) ON DELETE CASCADE,
    apu_codigo          TEXT NOT NULL,
    shift               TEXT NOT NULL,
    accion              TEXT NOT NULL,
    insumo_codigo       TEXT NOT NULL,
    insumo_nombre       TEXT NOT NULL DEFAULT '',
    unidad              TEXT NOT NULL DEFAULT '',
    rendimiento         DOUBLE PRECISION,
    insumo_nuevo_codigo TEXT,
    insumo_nuevo_nombre TEXT,
    tipo                TEXT NOT NULL DEFAULT 'insumo',
    ref_shift           TEXT NOT NULL DEFAULT '',
    nota                TEXT NOT NULL DEFAULT '',
    creado_en           TEXT NOT NULL,
    creado_por          TEXT,
    UNIQUE (carpeta_id, apu_codigo, shift, accion, insumo_codigo)
);
CREATE INDEX IF NOT EXISTS ix_proyecto_ajuste ON corridas.proyecto_ajuste(carpeta_id);
```

- [ ] **Step 4: Portar los métodos a `ApusPg`**

Mismos cuerpos que en SQLite, con `%s`, tablas `apus.`-calificadas y
`ON CONFLICT ... DO UPDATE` en vez de `INSERT OR REPLACE`:

```python
    # ---- clasificación de transporte ----
    def get_clasificacion_transporte(self) -> list[ClaseTransporte]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT apu_codigo, shift, insumo_codigo, insumo_nombre, categoria, "
                "       volumen, km_base, actualizado_en, actualizado_por "
                "FROM apus.componente_transporte").fetchall()
        return [ClaseTransporte(
            apu_codigo=r["apu_codigo"], shift=r["shift"],
            insumo_codigo=r["insumo_codigo"], insumo_nombre=r["insumo_nombre"],
            categoria=r["categoria"], volumen=r["volumen"], km_base=r["km_base"],
            actualizado_en=r["actualizado_en"] or "",
            actualizado_por=r["actualizado_por"]) for r in rows]

    def set_clasificacion_transporte(self, filas, conn=None,
                                     actualizado_por: Optional[str] = None) -> int:
        import datetime as _dt
        ahora = _dt.datetime.now().isoformat(timespec="seconds")
        rows = [(f.apu_codigo, f.shift, f.insumo_codigo, f.insumo_nombre,
                 f.categoria, float(f.volumen), f.km_base, ahora, actualizado_por)
                for f in filas]
        sql = ("INSERT INTO apus.componente_transporte "
               "(apu_codigo, shift, insumo_codigo, insumo_nombre, categoria, "
               " volumen, km_base, actualizado_en, actualizado_por) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT (apu_codigo, shift, insumo_codigo) DO UPDATE SET "
               "insumo_nombre=EXCLUDED.insumo_nombre, categoria=EXCLUDED.categoria, "
               "volumen=EXCLUDED.volumen, km_base=EXCLUDED.km_base, "
               "actualizado_en=EXCLUDED.actualizado_en, "
               "actualizado_por=EXCLUDED.actualizado_por")
        if conn is not None:
            with conn.cursor() as cur:
                cur.executemany(sql, rows)
            return len(rows)
        with self.cx.connection() as c, c.cursor() as cur:
            cur.executemany(sql, rows)
        return len(rows)

    def componentes_transporte_candidatos(self) -> list[dict]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT c.apu_codigo, c.shift, a.nombre AS apu_nombre, "
                "       c.insumo_codigo, c.insumo_nombre, c.unidad, c.rendimiento "
                "FROM apus.apu_componentes c "
                "LEFT JOIN apus.apus a ON a.codigo = c.apu_codigo AND a.shift = c.shift "
                "WHERE UPPER(c.unidad) = %s AND COALESCE(c.tipo,'insumo') <> 'apu' "
                "ORDER BY c.apu_codigo, c.shift, c.insumo_codigo",
                (config.UNIDAD_TRANSPORTE,)).fetchall()
        return [dict(r) for r in rows]
```

- [ ] **Step 5: Portar los 5 métodos a `CarpetasPg`**

```python
    # ---- parámetros de transporte del proyecto ----
    def get_parametros(self, carpeta_id: int) -> Optional[ParametrosProyecto]:
        with self.cx.connection() as conn:
            r = conn.execute("SELECT * FROM corridas.proyecto_parametros "
                             "WHERE carpeta_id=%s", (int(carpeta_id),)).fetchone()
        if r is None:
            return None
        return ParametrosProyecto(
            carpeta_id=r["carpeta_id"], km_botadero=r["km_botadero"],
            km_mezclas=r["km_mezclas"], km_granulares=r["km_granulares"],
            peaje_aplica=None if r["peaje_aplica"] is None else bool(r["peaje_aplica"]),
            peaje_valor=r["peaje_valor"], actualizado_en=r["actualizado_en"] or "",
            actualizado_por=r["actualizado_por"])

    def set_parametros(self, params: ParametrosProyecto, conn=None,
                       actualizado_por: Optional[str] = None) -> None:
        ahora = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO corridas.proyecto_parametros "
               "(carpeta_id, km_botadero, km_mezclas, km_granulares, peaje_aplica, "
               " peaje_valor, actualizado_en, actualizado_por) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT (carpeta_id) DO UPDATE SET "
               "km_botadero=EXCLUDED.km_botadero, km_mezclas=EXCLUDED.km_mezclas, "
               "km_granulares=EXCLUDED.km_granulares, "
               "peaje_aplica=EXCLUDED.peaje_aplica, peaje_valor=EXCLUDED.peaje_valor, "
               "actualizado_en=EXCLUDED.actualizado_en, "
               "actualizado_por=EXCLUDED.actualizado_por")
        p = (int(params.carpeta_id), params.km_botadero, params.km_mezclas,
             params.km_granulares,
             None if params.peaje_aplica is None else int(params.peaje_aplica),
             params.peaje_valor, ahora, actualizado_por or params.actualizado_por)
        if conn is not None:
            conn.execute(sql, p)
            return
        with self.cx.connection() as c:
            c.execute(sql, p)

    # ---- ajustes puntuales del proyecto ----
    def _fila_ajuste(self, r) -> AjusteProyecto:
        return AjusteProyecto(
            id=r["id"], carpeta_id=r["carpeta_id"], apu_codigo=r["apu_codigo"],
            shift=r["shift"], accion=r["accion"], insumo_codigo=r["insumo_codigo"],
            insumo_nombre=r["insumo_nombre"] or "", unidad=r["unidad"] or "",
            rendimiento=r["rendimiento"],
            insumo_nuevo_codigo=r["insumo_nuevo_codigo"] or "",
            insumo_nuevo_nombre=r["insumo_nuevo_nombre"] or "",
            tipo=r["tipo"] or "insumo", ref_shift=r["ref_shift"] or "",
            nota=r["nota"] or "", creado_en=r["creado_en"] or "",
            creado_por=r["creado_por"])

    def listar_ajustes(self, carpeta_id: int) -> list[AjusteProyecto]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.proyecto_ajuste WHERE carpeta_id=%s "
                "ORDER BY apu_codigo, shift, accion, insumo_codigo",
                (int(carpeta_id),)).fetchall()
        return [self._fila_ajuste(r) for r in rows]

    def crear_ajuste(self, ajuste: AjusteProyecto, conn=None,
                     creado_por: Optional[str] = None) -> int:
        creado_en = _dt.datetime.now().isoformat(timespec="seconds")
        sql = ("INSERT INTO corridas.proyecto_ajuste "
               "(carpeta_id, apu_codigo, shift, accion, insumo_codigo, insumo_nombre, "
               " unidad, rendimiento, insumo_nuevo_codigo, insumo_nuevo_nombre, tipo, "
               " ref_shift, nota, creado_en, creado_por) "
               "VALUES (%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s,%s) "
               "ON CONFLICT (carpeta_id, apu_codigo, shift, accion, insumo_codigo) "
               "DO UPDATE SET insumo_nombre=EXCLUDED.insumo_nombre, "
               "unidad=EXCLUDED.unidad, rendimiento=EXCLUDED.rendimiento, "
               "insumo_nuevo_codigo=EXCLUDED.insumo_nuevo_codigo, "
               "insumo_nuevo_nombre=EXCLUDED.insumo_nuevo_nombre, "
               "tipo=EXCLUDED.tipo, ref_shift=EXCLUDED.ref_shift, nota=EXCLUDED.nota "
               "RETURNING id")
        p = (int(ajuste.carpeta_id), ajuste.apu_codigo, ajuste.shift, ajuste.accion,
             ajuste.insumo_codigo, ajuste.insumo_nombre, ajuste.unidad,
             ajuste.rendimiento, ajuste.insumo_nuevo_codigo,
             ajuste.insumo_nuevo_nombre, ajuste.tipo or "insumo", ajuste.ref_shift,
             ajuste.nota, creado_en, creado_por or ajuste.creado_por)
        if conn is not None:
            return int(conn.execute(sql, p).fetchone()["id"])
        with self.cx.connection() as c:
            return int(c.execute(sql, p).fetchone()["id"])

    def borrar_ajuste(self, carpeta_id: int, ajuste_id: int, conn=None) -> bool:
        sql = "DELETE FROM corridas.proyecto_ajuste WHERE carpeta_id=%s AND id=%s"
        p = (int(carpeta_id), int(ajuste_id))
        if conn is not None:
            return conn.execute(sql, p).rowcount > 0
        with self.cx.connection() as c:
            return c.execute(sql, p).rowcount > 0
```

`carpetas_pg.py` ya importa `datetime as _dt`; agregar
`AjusteProyecto, ParametrosProyecto` al import de `nucleo.models` y `Optional` al
de `typing`.

- [ ] **Step 6: Escribir la migración RLS**

`supabase/migrations/0006_transporte_proyecto_rls.sql`:

```sql
-- Defensa en profundidad: RLS SIN policies en las tablas nuevas de transporte por
-- proyecto, igual que el resto (0003_rls.sql). Bloquea anon/authenticated; la
-- service_role (FastAPI) hace bypass y aplica el RBAC en la API.
-- Las tablas las crea el boot (db/pg/apus.sql, db/pg/corridas.sql), no una
-- migración numerada: por eso hace falta este archivo aparte, igual que
-- 0004_carpetas_rls.sql y 0005_lista_precios_rls.sql.
ALTER TABLE apus.componente_transporte ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.proyecto_parametros ENABLE ROW LEVEL SECURITY;
ALTER TABLE corridas.proyecto_ajuste ENABLE ROW LEVEL SECURITY;
```

- [ ] **Step 7: Correr y verificar que pasa**

Run: `python -m pytest tests/test_transporte_pg.py tests/test_paridad_backends.py tests/test_pg_esquema.py -q`
Expected: PASS (el contrato real se saltea sin `TEST_DATABASE_URL`)

- [ ] **Step 8: Commit**

```bash
git add db/pg apu_tool/datos/pg supabase/migrations/0006_transporte_proyecto_rls.sql tests/test_transporte_pg.py
git commit -m "feat(datos): espejo Postgres de transporte por proyecto + RLS"
```

---

## FASE 3 — Motor de precios y costeo

### Task 7: `PricingEngine` con contexto de proyecto

**Files:**
- Modify: `apu_tool/dominio/pricing.py`
- Test: `tests/test_transporte_pricing.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
# tests/test_transporte_pricing.py
"""El motor costea con las desviaciones del proyecto. Sin contexto, nada cambia."""
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.dominio.transporte import ContextoProyecto
from apu_tool.nucleo.models import (
    AjusteProyecto, Apu, ApuComponent, ClaseTransporte, Insumo, ParametrosProyecto)


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo(codigo="7462", nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
               grupo="TRANSPORTES", precio=1000.0, fuente_precio="COSTO INTERNO"),
        Insumo(codigo="7231", nombre="DERECHOS DE BOTADERO", unidad="M3",
               grupo="TRANSPORTES", precio=5000.0, fuente_precio="COSTO INTERNO"),
        Insumo(codigo="INT3", nombre="PEAJE", unidad="GLB", grupo="",
               precio=8000.0, fuente_precio="COSTO INTERNO"),
    ])
    alm.apus.insert_apus([
        Apu(codigo="4390", nombre="RELLENO", unidad="M3", shift="DIURNO", grupo="VIAS"),
        Apu(codigo="3017", nombre="TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS",
            unidad="M3", shift="DIURNO", grupo="TRANSPORTES"),
    ])
    alm.apus.insert_components([
        # el APU 4390 usa el sub-APU 3017 y transporte propio
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="3017",
                     insumo_nombre="TRANSPORTE Y DISPOSICION FINAL DE ESCOMBROS",
                     unidad="M3", rendimiento=1.0, precio_unitario_hist=20000.0,
                     tipo="apu", ref_shift="DIURNO"),
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=1000.0),
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="INT3",
                     insumo_nombre="PEAJE", unidad="GLB", rendimiento=1.0,
                     precio_unitario_hist=8000.0),
        # composición del sub-APU de botadero
        ApuComponent(apu_codigo="3017", shift="DIURNO", insumo_codigo="7231",
                     insumo_nombre="DERECHOS DE BOTADERO", unidad="M3",
                     rendimiento=1.3, precio_unitario_hist=5000.0),
        ApuComponent(apu_codigo="3017", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                     rendimiento=20.0, precio_unitario_hist=1000.0),
    ])
    return alm


def _clas():
    def c(apu, cod, cat, vol):
        return ((apu, "DIURNO", cod), ClaseTransporte(
            apu_codigo=apu, shift="DIURNO", insumo_codigo=cod,
            insumo_nombre="TRANSPORTE DE PETREOS", categoria=cat, volumen=vol,
            km_base=25.0))
    return dict([c("4390", "7462", "granulares", 1.05),
                 c("3017", "7462", "botadero", 1.0)])


def test_sin_contexto_el_costeo_es_el_de_siempre(tmp_path):
    alm = _alm(tmp_path)
    base = PricingEngine(alm).cost_apu("4390", "DIURNO")
    conctx_vacio = PricingEngine(alm, contexto=ContextoProyecto(
        params=ParametrosProyecto(), clasificacion={})).cost_apu("4390", "DIURNO")
    assert [(c.insumo_codigo, c.rendimiento, c.costo) for c in base[0]] == \
           [(c.insumo_codigo, c.rendimiento, c.costo) for c in conctx_vacio[0]]
    assert base[1] == conctx_vacio[1]


def test_reescala_granulares_del_apu(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_granulares=32),
                           clasificacion=_clas())
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    tte = [c for c in comps if c.insumo_codigo == "7462"][0]
    assert tte.rendimiento == 33.6           # 1.05 * 32
    assert tte.costo == 33600


def test_reescala_el_subapu_de_botadero(tmp_path):
    """La distancia del botadero vive dentro del sub-APU: reescalarlo alcanza a
    todos los APUs que lo usan, sin código extra."""
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_botadero=34),
                           clasificacion=_clas())
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    sub = [c for c in comps if c.insumo_codigo == "3017"][0]
    # sub-APU = derechos (1.3 * 5000) + transporte (1.0 * 34 * 1000)
    assert sub.precio_unitario == 6500 + 34000


def test_peaje_no_aplica_lo_saca_de_la_composicion(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(peaje_aplica=False),
                           clasificacion={})
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    assert all(c.insumo_codigo != "INT3" for c in comps)
    assert all(c.costo > 0 for c in comps)   # y nada quedó en $0


def test_peaje_usa_el_valor_del_proyecto(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(
        params=ParametrosProyecto(peaje_aplica=True, peaje_valor=12400),
        clasificacion={})
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    peaje = [c for c in comps if c.insumo_codigo == "INT3"][0]
    assert peaje.precio_unitario == 12400
    assert peaje.fuente_precio == "peaje del proyecto"
    assert peaje.costo == 12400


def test_pendientes_por_apu(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_granulares=32),
                           clasificacion={})
    motor = PricingEngine(alm, contexto=ctx)
    motor.cost_apu("4390", "DIURNO")
    assert motor.sin_distancia("4390", "DIURNO") == ("7462",)
    assert motor.sin_distancia("9999", "DIURNO") == ()


def test_ajuste_agrega_insumo_al_apu_del_proyecto(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(
        params=ParametrosProyecto(), clasificacion={},
        ajustes=(AjusteProyecto(apu_codigo="4390", shift="DIURNO", accion="quitar",
                                insumo_codigo="INT3", insumo_nombre="PEAJE"),))
    comps, _ = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    assert all(c.insumo_codigo != "INT3" for c in comps)


def test_precargar_no_cambia_el_resultado(tmp_path):
    alm = _alm(tmp_path)
    ctx = ContextoProyecto(params=ParametrosProyecto(km_granulares=32, km_botadero=34),
                           clasificacion=_clas())
    sin_precarga = PricingEngine(alm, contexto=ctx).cost_apu("4390", "DIURNO")
    motor = PricingEngine(alm, contexto=ctx)
    motor.precargar([("4390", "DIURNO")])
    con_precarga = motor.cost_apu("4390", "DIURNO")
    assert sin_precarga[1] == con_precarga[1]
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_transporte_pricing.py -q`
Expected: FAIL con `TypeError: PricingEngine.__init__() got an unexpected keyword argument 'contexto'`

- [ ] **Step 3: Modificar `apu_tool/dominio/pricing.py`**

Import y `__init__`:

```python
from apu_tool.dominio import cruce, transporte
```

```python
    def __init__(self, almacen: Almacen, lista_id: int | None = None,
                 contexto: "transporte.ContextoProyecto | None" = None):
        self.alm = almacen
        ...
        self._apu_cost_cache: dict[tuple, float] = {}
        # Desviaciones del proyecto (distancias, peaje, ajustes). None = biblioteca
        # tal cual: el costeo es idéntico al de antes de esta feature.
        self._ctx = None if (contexto is None or contexto.vacio) else contexto
        # (apu, shift) -> códigos de acarreo que no se pudieron reescalar; los lee
        # alertas.py para avisar en vez de costear con la distancia equivocada.
        self._sin_distancia: dict[tuple[str, str], tuple[str, ...]] = {}
```

Nuevo método público y `components()` reescrito:

```python
    def sin_distancia(self, apu_codigo: str, shift: str) -> tuple[str, ...]:
        """Componentes de acarreo de ese APU que el proyecto no pudo reescalar."""
        return self._sin_distancia.get((apu_codigo, shift), ())

    def claves_cargadas(self) -> list[tuple[str, str]]:
        """(código, turno) de todo lo que hay en el caché de composiciones, incluido
        el cierre de sub-APUs que trajo `precargar`. Lo usa la tabla de impacto para
        recorrer el árbol sin duplicar la BFS."""
        return sorted(self._comp_cache.keys())

    def _efectivos(self, codigo: str, shift: str, crudos: list) -> list:
        """Composición EFECTIVA del proyecto (regla de transporte + ajustes).

        Se aplica ANTES de cachear, así el costeo, el memo de sub-APUs y la
        precarga en lote ven todos la misma composición: un solo camino."""
        if self._ctx is None:
            return crudos
        pend = transporte.pendientes(crudos, codigo, shift, self._ctx.params,
                                     self._ctx.clasificacion)
        if pend:
            self._sin_distancia[(codigo, shift)] = pend
        return transporte.aplicar(crudos, codigo, shift, self._ctx.params,
                                  self._ctx.clasificacion, self._ctx.ajustes)

    def components(self, codigo: str, shift: str) -> list:
        """Composición EFECTIVA de un APU, cacheada por (codigo, shift). Si
        `precargar` la trajo en lote, no toca la base."""
        clave = (codigo, shift)
        if clave not in self._comp_cache:
            self._comp_cache[clave] = self._efectivos(
                codigo, shift, self.alm.apus.get_components(codigo, shift))
        return self._comp_cache[clave]
```

En `_precargar_lote`, aplicar lo mismo para que la BFS recorra la composición
efectiva (un ajuste puede agregar un sub-APU):

```python
            for clave in pendientes:
                comps = self._efectivos(clave[0], clave[1], cargados.get(clave, []))
                self._comp_cache[clave] = comps
                for comp in comps:
```

En `cost_component`, justo después de la rama de sub-APU:

```python
        if self._ctx is not None and transporte.es_peaje(comp):
            valor = self._ctx.params.peaje_valor
            if valor:                      # 0/None => sigue el camino normal del catálogo
                return CostedComponent(
                    insumo_codigo=comp.insumo_codigo, insumo_nombre=comp.insumo_nombre,
                    unidad=comp.unidad, rendimiento=comp.rendimiento,
                    precio_unitario=float(valor), fuente_precio="peaje del proyecto",
                    costo=mul_redondeado(comp.rendimiento, float(valor)),
                    calidad_cruce="exacto", tipo="insumo", ref_shift="")
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/test_transporte_pricing.py tests/test_pricing.py tests/test_subapus.py -q`
Expected: PASS (si no existen esos dos últimos archivos, correr
`python -m pytest tests/ -q -k "pricing or subapu"`)

- [ ] **Step 5: Correr TODA la suite (la garantía de no regresión)**

Run: `python -m pytest tests/ -q`
Expected: PASS, mismo número de tests que antes + los nuevos

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/pricing.py tests/test_transporte_pricing.py
git commit -m "feat(pricing): costear con las desviaciones del proyecto"
```

---

### Task 8: Cargar el contexto y cablearlo en las corridas

**Files:**
- Modify: `apu_tool/dominio/transporte.py` (agregar `cargar_contexto`)
- Modify: `apu_tool/dominio/assemble.py:36-42`
- Modify: `apu_tool/servicio/corridas.py` (líneas 149, 228, 280, 425, 462 y el `Assembler` de `confirmar_items`)
- Test: `tests/test_transporte_corridas.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
# tests/test_transporte_corridas.py
"""Las corridas costean con los parámetros de SU proyecto (carpeta raíz)."""
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import transporte
from apu_tool.nucleo.models import (
    Apu, ApuComponent, ClaseTransporte, Insumo, LicitacionItem, ParametrosProyecto)
from apu_tool.servicio import corridas as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo(codigo="7462", nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
               grupo="TRANSPORTES", precio=1000.0, fuente_precio="COSTO INTERNO")])
    alm.apus.insert_apus([Apu(codigo="4390", nombre="RELLENO", unidad="M3",
                              shift="DIURNO", grupo="VIAS")])
    alm.apus.insert_components([
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=1000.0)])
    alm.apus.set_clasificacion_transporte([ClaseTransporte(
        apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
        insumo_nombre="TRANSPORTE DE PETREOS", categoria="granulares",
        volumen=1.05, km_base=25.0)])
    return alm


def _corrida(alm, carpeta_id):
    items = [LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=10,
                            precio_contractual=100000.0, shift="DIURNO")]
    cid = svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False,
                                carpeta_id=carpeta_id)
    svc.confirmar_item(alm, cid, 1, "4390", "DIURNO")
    return cid


def test_cada_proyecto_costea_con_su_distancia(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    calle13 = alm.carpetas.crear("Calle 13")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=calle13, km_granulares=25))
    c_metro, c_c13 = _corrida(alm, metro), _corrida(alm, calle13)
    v_metro = svc.vista_corrida(alm, c_metro)["items"][0]
    v_c13 = svc.vista_corrida(alm, c_c13)["items"][0]
    assert v_metro["costo_unitario"] == 33600      # 1.05 * 32 * 1000
    assert v_c13["costo_unitario"] == 26250       # 1.05 * 25 * 1000
    # y la biblioteca no cambió
    comps = alm.apus.get_components("4390", "DIURNO")
    assert comps[0].rendimiento == 26.25


def test_subcarpeta_hereda_del_proyecto(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    lote = alm.carpetas.crear("Lote 2", parent_id=metro)
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, lote)
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 33600


def test_congelada_conserva_su_foto(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, metro)
    svc.congelar(alm, cid)
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=50))
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 33600


def test_sin_parametros_costea_como_siempre(tmp_path):
    alm = _alm(tmp_path)
    cid = _corrida(alm, alm.carpetas.crear("Sin distancias"))
    assert svc.vista_corrida(alm, cid)["items"][0]["costo_unitario"] == 26250


def test_cargar_contexto_sube_a_la_raiz(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    lote = alm.carpetas.crear("Lote 2", parent_id=metro)
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_botadero=34))
    ctx = transporte.cargar_contexto(alm, lote)
    assert ctx.params.km_botadero == 34
    assert transporte.cargar_contexto(alm, None).vacio is True


def test_detalle_item_y_cuadro_usan_el_contexto(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, metro)
    det = svc.detalle_item(alm, cid, 1)
    assert det["composicion"][0]["rendimiento"] == 33.6
    assert svc.generar_cuadro(alm, cid) is not None
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_transporte_corridas.py -q`
Expected: FAIL — `AttributeError: module 'apu_tool.dominio.transporte' has no attribute 'cargar_contexto'`

- [ ] **Step 3: Agregar `cargar_contexto` a `apu_tool/dominio/transporte.py`**

Al final del módulo:

```python
def cargar_contexto(almacen, carpeta_id: Optional[int]) -> ContextoProyecto:
    """Contexto del proyecto al que pertenece una carpeta (sube a la raíz).

    Es lo único de este módulo que lee la base — mismo criterio que
    `PricingEngine`, que también recibe el `Almacen`. Tres consultas como máximo:
    la carpeta raíz, sus parámetros/ajustes y la clasificación de la biblioteca
    (una tabla de decenas de filas, se lee completa).
    """
    vacio = ContextoProyecto(params=ParametrosProyecto(), clasificacion={})
    if carpeta_id is None:
        return vacio
    raiz = raiz_de(almacen, carpeta_id)
    if raiz is None:
        return vacio
    params = almacen.carpetas.get_parametros(raiz) or ParametrosProyecto(carpeta_id=raiz)
    ajustes = tuple(almacen.carpetas.listar_ajustes(raiz))
    if params.vacio and not ajustes:
        return vacio                       # nada definido: ni se lee la clasificación
    clasificacion = {(c.apu_codigo, c.shift, c.insumo_codigo): c
                     for c in almacen.apus.get_clasificacion_transporte()}
    return ContextoProyecto(params=params, clasificacion=clasificacion, ajustes=ajustes)


def raiz_de(almacen, carpeta_id: Optional[int]) -> Optional[int]:
    """Carpeta de nivel 1 (= el proyecto) a la que pertenece `carpeta_id`.
    La jerarquía es de 2 niveles (lo garantiza servicio/carpetas.py), así que
    esto son 2 consultas como máximo; el tope de 5 vueltas es una red por si
    algún día alguien crea un ciclo a mano en la base."""
    actual = carpeta_id
    for _ in range(5):
        if actual is None:
            return None
        c = almacen.carpetas.get(actual)
        if c is None:
            return None
        if c.parent_id is None:
            return c.id
        actual = c.parent_id
    return actual
```

- [ ] **Step 4: Pasar el contexto por el `Assembler`**

En `apu_tool/dominio/assemble.py:36-42`:

```python
    def __init__(self, almacen: Almacen, advisor: Optional[ApuAdvisor] = None,
                 lista_id: Optional[int] = None, contexto=None):
        self.alm = almacen
        # Costear con la tarifa de la corrida: armar y confirmar deben dar el mismo
        # número que la vista. None = Principal.
        self.lista_id = lista_id
        # Desviaciones del proyecto: armar/confirmar tienen que dar el mismo número
        # que la vista, así que el contexto viaja también por acá.
        self.pricing = PricingEngine(almacen, lista_id=lista_id, contexto=contexto)
```

- [ ] **Step 5: Cablear `apu_tool/servicio/corridas.py`**

Agregar el import y el helper (después de `_nombre_lista`):

```python
from apu_tool.dominio import transporte
```

```python
def _contexto(alm: Almacen, meta: CorridaMeta):
    """Desviaciones del proyecto de esta corrida (distancias, peaje, ajustes).

    Se resuelven EN VIVO desde la carpeta raíz: cambiar las distancias del
    proyecto recostea sus corridas activas sin tocar nada más. Una corrida
    congelada nunca llega acá (se sirve del snapshot)."""
    return transporte.cargar_contexto(alm, meta.carpeta_id)
```

Y en los 5 constructores + el `Assembler`, agregar `contexto=`:

| línea | antes | después |
|---|---|---|
| 149 (`_costear_row`) | `PricingEngine(alm, lista_id=lista_id)` | `PricingEngine(alm, lista_id=lista_id, contexto=contexto)` |
| 228 (`vista_corrida`) | `PricingEngine(alm, lista_id=meta.lista_precios_id)` | `PricingEngine(alm, lista_id=meta.lista_precios_id, contexto=_contexto(alm, meta))` |
| 280 (`congelar`) | idem | idem |
| 425 (`listar_corridas`) | idem | idem |
| 462 (`generar_cuadro`) | idem | idem |
| `confirmar_items` | `Assembler(alm, advisor=…, lista_id=meta.lista_precios_id)` | `Assembler(alm, advisor=…, lista_id=meta.lista_precios_id, contexto=_contexto(alm, meta))` |

Y la firma de `_costear_row` (línea ~137) gana el parámetro:

```python
def _costear_row(alm: Almacen, row: CorridaItemRow,
                 pricing: Optional[PricingEngine] = None,
                 lista_id: Optional[int] = None,
                 contexto=None) -> AssembledApu:
```

En `detalle_item` (línea ~372) y en el resto de las llamadas a `_costear_row` sin
motor compartido, pasar `contexto=_contexto(alm, meta)`:

```python
        ens = _costear_row(alm, row, None, meta.lista_precios_id, _contexto(alm, meta))
```

`apu_tool/dominio/pipeline.py:138` y `apu_tool/servicio/apus.py:27,43` se dejan
como están a propósito: el pipeline del CLI no tiene carpeta y la vista de la
biblioteca debe mostrar el APU de la biblioteca, no el de un proyecto.

- [ ] **Step 6: Correr y verificar que pasa**

Run: `python -m pytest tests/test_transporte_corridas.py -q`
Expected: PASS (6 tests)

- [ ] **Step 7: Correr toda la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/dominio/transporte.py apu_tool/dominio/assemble.py apu_tool/servicio/corridas.py tests/test_transporte_corridas.py
git commit -m "feat(corridas): costear cada corrida con los parametros de su proyecto"
```

---

### Task 9: Alerta «distancia del proyecto no aplicada»

**Files:**
- Modify: `apu_tool/dominio/alertas.py`
- Modify: `apu_tool/servicio/corridas.py` (`_vista_item` y sus 2 llamadores)
- Test: `tests/test_alertas_costeo.py` (agregar)

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_alertas_costeo.py`:

```python
def test_alerta_de_distancia_no_aplicada():
    from apu_tool.dominio.alertas import alertas_costeo
    from apu_tool.nucleo.models import (
        AssembledApu, CostedComponent, LicitacionItem, MatchStatus)
    item = LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                          precio_contractual=1000.0, shift="DIURNO")
    comp = CostedComponent(insumo_codigo="7462", insumo_nombre="TRANSPORTE DE PETREOS",
                           unidad="M3-KM", rendimiento=26.25, precio_unitario=1000.0,
                           fuente_precio="COSTO INTERNO", costo=26250)
    ens = AssembledApu(item=item, apu_codigo="4390", apu_nombre="RELLENO", unidad="M3",
                       shift="DIURNO", componentes=[comp], costo_unitario=26250,
                       status=MatchStatus.CONFIRMED, confianza=1.0)
    assert alertas_costeo(ens) == []                     # sin proyecto: sin alerta
    motivos = alertas_costeo(ens, sin_distancia=("7462",))
    assert motivos == ["7462 TRANSPORTE DE PETREOS: distancia del proyecto no aplicada"]
```

Y en `tests/test_transporte_corridas.py`:

```python
def test_la_corrida_alerta_el_componente_sin_clasificar(tmp_path):
    alm = _alm(tmp_path)
    # Se borra la clasificación para simular un APU nuevo sin clasificar.
    with alm.apus.connect() as conn:
        conn.execute("DELETE FROM componente_transporte")
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32))
    cid = _corrida(alm, metro)
    alertas = svc.vista_corrida(alm, cid)["items"][0]["alertas_costeo"]
    assert any("distancia del proyecto no aplicada" in a for a in alertas)
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_alertas_costeo.py -q -k distancia`
Expected: FAIL con `TypeError: alertas_costeo() got an unexpected keyword argument 'sin_distancia'`

- [ ] **Step 3: Modificar `apu_tool/dominio/alertas.py`**

```python
def alertas_costeo(a: AssembledApu, sin_distancia: tuple[str, ...] = ()) -> list[str]:
    """Motivos de revisión de costo del ítem. Lista vacía = sin alerta.

    `sin_distancia`: códigos de componentes de acarreo que el proyecto NO pudo
    reescalar por falta de clasificación (los reporta `PricingEngine.sin_distancia`).
    Se avisa en vez de costear con la distancia equivocada en silencio."""
    motivos: list[str] = []
    pendientes = set(sin_distancia)
    for c in a.componentes:
        etiqueta = f"{c.insumo_codigo} {c.insumo_nombre}".strip()
        if c.calidad_cruce == CALIDAD_SIN_PRECIO_LISTA:
            motivos.append(f"{etiqueta}: sin precio en la lista")
        elif c.costo <= 0 or c.precio_unitario <= 0:        # regla dura: $0 siempre
            motivos.append(f"{etiqueta}: en $0")
        elif c.insumo_codigo in pendientes:
            motivos.append(f"{etiqueta}: distancia del proyecto no aplicada")
        elif c.calidad_cruce in _MOTIVO_CRUCE:
            motivos.append(f"{etiqueta}: {_MOTIVO_CRUCE[c.calidad_cruce]}")
    if not motivos and a.costo_unitario <= 0:
        motivos.append("APU en $0 (sin composición o sin costo)")
    return motivos
```

El orden importa: el $0 sigue primero (es la regla dura) y la distancia va antes
que el motivo genérico de cruce, que es menos accionable.

- [ ] **Step 4: Pasar los pendientes desde `servicio/corridas.py`**

`_vista_item` gana el parámetro:

```python
def _vista_item(ens: AssembledApu, seq: int, status: str,
                sin_distancia: tuple[str, ...] = ()) -> dict:
    return {
        ...
        "alertas_costeo": alertas_costeo(ens, sin_distancia),
    }
```

En `vista_corrida` y `listar_corridas`, donde se arma la lista de ítems, pasar
`pricing.sin_distancia(r.apu_codigo or "", r.shift)` de la fila correspondiente.
Ejemplo del patrón en `vista_corrida`:

```python
    items = [_vista_item(ens, r.seq, r.status,
                         pricing.sin_distancia(r.apu_codigo or "", r.shift))
             for r, ens in zip(rows, assembled)]
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `python -m pytest tests/test_alertas_costeo.py tests/test_transporte_corridas.py tests/test_corrida_alertas_costeo.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/alertas.py apu_tool/servicio/corridas.py tests/test_alertas_costeo.py tests/test_transporte_corridas.py
git commit -m "feat(alertas): avisar cuando falta clasificar la distancia de un acarreo"
```

---

### Task 10: Frontera de privacidad

**Files:**
- Modify: `apu_tool/dominio/privacy.py:21-26`
- Test: `tests/test_privacy.py` (agregar; si el archivo tiene otro nombre, usar el que
  ya prueba `assert_no_money`: `python -m pytest tests/ -q -k privacy --collect-only`)

- [ ] **Step 1: Escribir el test que falla**

```python
def test_peaje_valor_no_puede_ir_a_la_ia():
    import pytest
    from apu_tool.dominio.privacy import PrivacyViolation, assert_no_money
    with pytest.raises(PrivacyViolation):
        assert_no_money({"proyecto": {"km_botadero": 34, "peaje_valor": 12400}})
    # las distancias y los rendimientos SÍ pueden (son cantidades, no dinero)
    assert_no_money({"proyecto": {"km_botadero": 34, "km_mezclas": 28},
                     "componentes": [{"rendimiento": 33.6}]})
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/ -q -k peaje_valor`
Expected: FAIL con `DID NOT RAISE PrivacyViolation`

- [ ] **Step 3: Agregar la clave prohibida**

```python
_FORBIDDEN_KEYS = {
    "precio", "precio_unitario", "precio_contractual", "precio_unitario_hist",
    "costo", "costo_unitario", "costo_total", "valor", "valor_unitario",
    "valor_total", "margen", "price", "cost", "amount", "total",
    "fuente_precio",
    # El valor del peaje de un proyecto es dinero. `valor` ya está en la lista,
    # pero el chequeo es por nombre EXACTO de clave.
    "peaje_valor",
}
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `python -m pytest tests/ -q -k "privacy or peaje_valor"`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/privacy.py tests/test_privacy.py
git commit -m "feat(privacidad): peaje_valor nunca llega a la IA"
```

---

## FASE 4 — API

### Task 11: Servicio y endpoints de parámetros, impacto y clasificación

**Files:**
- Create: `apu_tool/servicio/transporte.py`
- Modify: `apu_tool/servicio/esquemas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_transporte.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
# tests/test_api_transporte.py
"""API de distancias del proyecto y clasificación de la biblioteca."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="admin"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo(codigo="7462", nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
               grupo="TRANSPORTES", precio=1000.0, fuente_precio="COSTO INTERNO")])
    alm.apus.insert_apus([Apu(codigo="4390", nombre="RELLENO", unidad="M3",
                              shift="DIURNO", grupo="VIAS")])
    alm.apus.insert_components([
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="7462",
                     insumo_nombre="TRANSPORTE DE PETREOS", unidad="M3-KM",
                     rendimiento=26.25, precio_unitario_hist=1000.0)])
    return cliente(create_app(almacen=alm), rol=rol), alm


def test_get_parametros_vacios(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.get(f"/api/carpetas/{cid}/transporte")
    assert r.status_code == 200
    body = r.json()
    assert body["parametros"]["km_botadero"] is None
    assert body["impacto"] == [] and body["sin_clasificar"] == 0


def test_put_y_get_parametros(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.put(f"/api/carpetas/{cid}/transporte", json={
        "km_botadero": 34, "km_mezclas": 28, "km_granulares": 32,
        "peaje_aplica": True, "peaje_valor": 12400})
    assert r.status_code == 200, r.text
    p = cli.get(f"/api/carpetas/{cid}/transporte").json()["parametros"]
    assert p["km_granulares"] == 32 and p["peaje_valor"] == 12400


def test_peaje_sin_valor_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.put(f"/api/carpetas/{cid}/transporte",
                json={"peaje_aplica": True, "peaje_valor": 0})
    assert r.status_code == 400 and "$0" in r.text


def test_km_negativo_o_cero_es_400(tmp_path):
    """Un km en 0 dejaría el acarreo en rendimiento 0 y el ítem en $0."""
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": -1}).status_code == 400
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": 0}).status_code == 400
    # vacío sí se acepta: es "esta distancia no aplica".
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": None}).status_code == 200


def test_subcarpeta_no_puede_tener_parametros(tmp_path):
    cli, alm = _cli(tmp_path)
    raiz = alm.carpetas.crear("Metro")
    sub = alm.carpetas.crear("Lote 2", parent_id=raiz)
    r = cli.put(f"/api/carpetas/{sub}/transporte", json={"km_botadero": 34})
    assert r.status_code == 400 and "nivel" in r.text.lower()


def test_consulta_no_puede_escribir(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    cid = alm.carpetas.crear("Metro")
    assert cli.get(f"/api/carpetas/{cid}/transporte").status_code == 200
    assert cli.put(f"/api/carpetas/{cid}/transporte",
                   json={"km_botadero": 34}).status_code == 403


def test_candidatos_y_clasificacion(tmp_path):
    cli, _ = _cli(tmp_path)
    filas = cli.get("/api/transporte/componentes").json()["items"]
    assert len(filas) == 1
    f = filas[0]
    assert f["insumo_codigo"] == "7462" and f["categoria_sugerida"] == "granulares"
    assert f["km_base"] == 25.0 and round(f["volumen"], 4) == 1.05
    assert f["categoria"] is None                       # sin clasificar todavía
    r = cli.put("/api/transporte/componentes", json={"filas": [{
        "apu_codigo": "4390", "shift": "DIURNO", "insumo_codigo": "7462",
        "insumo_nombre": "TRANSPORTE DE PETREOS", "categoria": "granulares",
        "volumen": 1.05, "km_base": 25.0}]})
    assert r.status_code == 200 and r.json()["aplicados"] == 1
    f = cli.get("/api/transporte/componentes").json()["items"][0]
    assert f["categoria"] == "granulares"


def test_categoria_invalida_es_400(tmp_path):
    cli, _ = _cli(tmp_path)
    r = cli.put("/api/transporte/componentes", json={"filas": [{
        "apu_codigo": "4390", "shift": "DIURNO", "insumo_codigo": "7462",
        "insumo_nombre": "TRANSPORTE DE PETREOS", "categoria": "cemento",
        "volumen": 1.05}]})
    assert r.status_code == 400


def test_impacto_muestra_el_rendimiento_nuevo(tmp_path):
    from apu_tool.nucleo.models import LicitacionItem
    from apu_tool.servicio import corridas as svc
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    corrida = svc.construir_corrida(
        alm, "lic.xlsx",
        [LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                        precio_contractual=100.0, shift="DIURNO")],
        "DIURNO", False, carpeta_id=cid)
    svc.confirmar_item(alm, corrida, 1, "4390", "DIURNO")
    cli.put("/api/transporte/componentes", json={"filas": [{
        "apu_codigo": "4390", "shift": "DIURNO", "insumo_codigo": "7462",
        "insumo_nombre": "TRANSPORTE DE PETREOS", "categoria": "granulares",
        "volumen": 1.05, "km_base": 25.0}]})
    cli.put(f"/api/carpetas/{cid}/transporte", json={"km_granulares": 32})
    imp = cli.get(f"/api/carpetas/{cid}/transporte").json()["impacto"]
    fila = [f for f in imp if f["insumo_codigo"] == "7462"][0]
    assert fila["rendimiento_actual"] == 26.25
    assert fila["rendimiento_nuevo"] == 33.6
    assert fila["origen"] == "distancia"
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_api_transporte.py -q`
Expected: FAIL con 404 en todas las rutas

- [ ] **Step 3: Escribir `apu_tool/servicio/transporte.py`**

```python
"""
Servicio de distancias de acarreo por proyecto y de clasificación de la biblioteca.

Ve dinero solo en el valor del peaje (es para el equipo); nunca abre un camino
hacia la IA. Roles: leer = consulta+, escribir = editor+ (los aplica rutas.py).
"""
from __future__ import annotations

from typing import Optional

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import transporte as regla
from apu_tool.dominio.pricing import PricingEngine
from apu_tool.nucleo.models import ClaseTransporte, ParametrosProyecto
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria

MSG_PEAJE = ("El valor del peaje debe ser mayor que 0 cuando el proyecto tiene "
             "peaje. Un $0 está prohibido: si no hay peaje, marca «no hay».")


def _params_out(p: Optional[ParametrosProyecto], carpeta_id: int) -> dict:
    p = p or ParametrosProyecto(carpeta_id=carpeta_id)
    return {"carpeta_id": carpeta_id, "km_botadero": p.km_botadero,
            "km_mezclas": p.km_mezclas, "km_granulares": p.km_granulares,
            "peaje_aplica": p.peaje_aplica, "peaje_valor": p.peaje_valor,
            "actualizado_en": p.actualizado_en, "actualizado_por": p.actualizado_por}


def _raiz_o_error(alm: Almacen, carpeta_id: int) -> int:
    c = alm.carpetas.get(carpeta_id)
    if c is None:
        raise ValueError("La carpeta no existe.")
    if c.parent_id is not None:
        raise ValueError("Las distancias son del proyecto: se definen en la carpeta "
                         "de nivel 1, no en una subcarpeta.")
    return c.id


def ver(alm: Almacen, carpeta_id: int) -> dict:
    """Parámetros del proyecto + tabla de impacto + cuántos componentes faltan clasificar."""
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        raise ValueError("La carpeta no existe.")
    params = alm.carpetas.get_parametros(raiz)
    impacto = _impacto(alm, raiz)
    return {"parametros": _params_out(params, raiz),
            "impacto": impacto,
            "sin_clasificar": sum(1 for f in impacto if f["sin_clasificar"])}


def guardar(alm: Almacen, carpeta_id: int, datos: dict, actor=None) -> dict:
    """Guarda los parámetros del proyecto. ValueError (-> 400) si algo no cuadra."""
    raiz = _raiz_o_error(alm, carpeta_id)
    kms = {}
    for campo in ("km_botadero", "km_mezclas", "km_granulares"):
        v = datos.get(campo)
        # Un 0 NO es una distancia válida: reescalaría el acarreo a rendimiento 0 y
        # dejaría el ítem en $0. Regla de negocio: nada en $0. Para "no aplica" se
        # deja el campo en null, que es lo que la regla trata como sin definir.
        if v is not None and float(v) <= 0:
            raise ValueError(f"{campo} debe ser mayor que 0; deja el campo vacío "
                             f"si esa distancia no aplica al proyecto.")
        kms[campo] = None if v is None else float(v)
    aplica = datos.get("peaje_aplica")
    valor = datos.get("peaje_valor")
    if aplica is True and not (valor and float(valor) > 0):
        raise ValueError(MSG_PEAJE)
    previos = alm.carpetas.get_parametros(raiz)
    nuevos = ParametrosProyecto(
        carpeta_id=raiz, peaje_aplica=None if aplica is None else bool(aplica),
        peaje_valor=None if valor is None else float(valor), **kms)
    with alm.transaccion("corridas") as conn:
        alm.carpetas.set_parametros(
            nuevos, conn=conn,
            actualizado_por=(getattr(actor, "email", None) if actor else None))
        registrar_auditoria(
            alm, conn, actor, "proyecto.transporte", "carpeta", raiz,
            antes=_params_out(previos, raiz) if previos else None,
            despues=_params_out(nuevos, raiz))
    return ver(alm, raiz)


def _claves_del_proyecto(alm: Almacen, raiz: int) -> list[tuple[str, str]]:
    """(apu, turno) asignados en las corridas del proyecto (raíz + subcarpetas)."""
    hijas = {c.id for c in alm.carpetas.listar() if c.parent_id == raiz}
    propias = hijas | {raiz}
    claves = set()
    for meta in alm.corridas.listar_corridas():
        if meta.carpeta_id in propias:
            for row in alm.corridas.get_items(meta.id):
                if row.apu_codigo:
                    claves.add((row.apu_codigo, row.shift))
    return sorted(claves)


def _impacto(alm: Almacen, raiz: int) -> list[dict]:
    """Previsualización en seco: qué rendimiento tendría cada componente de acarreo.

    Recorre los APUs asignados en el proyecto MÁS el cierre de sus sub-APUs — es
    justo lo que hace `PricingEngine.precargar`, así que se reusa el motor en vez
    de duplicar la BFS. No escribe nada."""
    ctx = regla.cargar_contexto(alm, raiz)
    claves = _claves_del_proyecto(alm, raiz)
    if not claves:
        return []
    motor = PricingEngine(alm, contexto=ctx)
    motor.precargar(claves)
    filas = []
    for apu_codigo, shift in motor.claves_cargadas():            # incluye sub-APUs
        crudos = alm.apus.get_components(apu_codigo, shift)
        efectivos = {(c.insumo_codigo, normalizar(c.insumo_nombre)): c
                     for c in motor.components(apu_codigo, shift)}
        pend = set(motor.sin_distancia(apu_codigo, shift))
        for c in crudos:
            if normalizar(c.unidad) != normalizar(config.UNIDAD_TRANSPORTE) \
                    and not regla.es_peaje(c):
                continue
            ef = efectivos.get((c.insumo_codigo, normalizar(c.insumo_nombre)))
            cls = ctx.clasificacion.get((apu_codigo, shift, c.insumo_codigo))
            filas.append({
                "apu_codigo": apu_codigo, "shift": shift,
                "insumo_codigo": c.insumo_codigo, "insumo_nombre": c.insumo_nombre,
                "unidad": c.unidad, "rendimiento_actual": c.rendimiento,
                "categoria": cls.categoria if cls else None,
                "volumen": cls.volumen if cls else None,
                "rendimiento_nuevo": ef.rendimiento if ef is not None else None,
                "quitado": ef is None,
                "origen": ("distancia" if ef is not None
                           and ef.rendimiento != c.rendimiento else "biblioteca"),
                "sin_clasificar": c.insumo_codigo in pend,
            })
    return filas


# ---- clasificación de la biblioteca (una vez, no por proyecto) ----
def _sugerir(apu_nombre: str, insumo_nombre: str) -> Optional[str]:
    apu_n, ins_n = normalizar(apu_nombre), normalizar(insumo_nombre)
    for ambito, fragmentos, categoria in config.TRANSPORTE_SUGERENCIAS:
        texto = apu_n if ambito == "apu_nombre" else ins_n
        if any(normalizar(f) in texto for f in fragmentos):
            return categoria
    return None


def listar_componentes(alm: Almacen) -> dict:
    """Las filas de acarreo de la biblioteca, con su clasificación o la sugerida."""
    guardadas = {(c.apu_codigo, c.shift, c.insumo_codigo): c
                 for c in alm.apus.get_clasificacion_transporte()}
    items = []
    for cand in alm.apus.componentes_transporte_candidatos():
        clave = (cand["apu_codigo"], cand["shift"], cand["insumo_codigo"])
        cls = guardadas.get(clave)
        if cls is not None and normalizar(cls.insumo_nombre) != normalizar(
                cand["insumo_nombre"]):
            cls = None                     # misma clave, otro insumo: no vale
        km_base = (cls.km_base if cls and cls.km_base else config.KM_BASE_DEFECTO)
        rend = float(cand["rendimiento"] or 0.0)
        volumen = cls.volumen if cls else (rend / km_base if km_base else 0.0)
        items.append({
            "apu_codigo": cand["apu_codigo"], "shift": cand["shift"],
            "apu_nombre": cand["apu_nombre"] or "",
            "insumo_codigo": cand["insumo_codigo"],
            "insumo_nombre": cand["insumo_nombre"], "unidad": cand["unidad"],
            "rendimiento": rend,
            "categoria": cls.categoria if cls else None,
            "categoria_sugerida": _sugerir(cand["apu_nombre"] or "",
                                           cand["insumo_nombre"]),
            "volumen": volumen, "km_base": km_base,
            # km que la fila representa hoy con el volumen mostrado: delata las
            # filas cuya distancia no cuadra con la que declara su nombre.
            "km_implicito": round(rend / volumen, 2) if volumen else None,
        })
    return {"items": items, "total": len(items),
            "categorias": list(config.TRANSPORTE_CATEGORIAS),
            "km_base_defecto": config.KM_BASE_DEFECTO}


def clasificar(alm: Almacen, filas: list[dict], actor=None) -> dict:
    """Guarda categoría + volumen de N componentes. Es la acción en bloque."""
    validas: list[ClaseTransporte] = []
    for f in filas:
        categoria = str(f.get("categoria") or "")
        if categoria not in config.TRANSPORTE_CATEGORIAS:
            raise ValueError(f"Categoría inválida: «{categoria}». "
                             f"Válidas: {', '.join(config.TRANSPORTE_CATEGORIAS)}.")
        volumen = float(f.get("volumen") or 0.0)
        if volumen <= 0:
            raise ValueError("El volumen debe ser mayor que 0.")
        validas.append(ClaseTransporte(
            apu_codigo=str(f["apu_codigo"]), shift=str(f["shift"]),
            insumo_codigo=str(f["insumo_codigo"]),
            insumo_nombre=str(f.get("insumo_nombre") or ""),
            categoria=categoria, volumen=volumen,
            km_base=(float(f["km_base"]) if f.get("km_base") else None)))
    email = getattr(actor, "email", None) if actor else None
    with alm.transaccion("apus") as conn:
        alm.apus.set_clasificacion_transporte(validas, conn=conn, actualizado_por=email)
        registrar_auditoria(
            alm, conn, actor, "transporte.clasificar", "apu",
            f"{len(validas)} componentes", antes=None,
            despues=[{"apu": c.apu_codigo, "shift": c.shift,
                      "insumo": c.insumo_codigo, "categoria": c.categoria,
                      "volumen": c.volumen} for c in validas])
    return {"aplicados": len(validas)}
```

- [ ] **Step 4: Agregar los DTOs a `apu_tool/servicio/esquemas.py`**

```python
class TransporteParamsIn(BaseModel):
    km_botadero: Optional[float] = None
    km_mezclas: Optional[float] = None
    km_granulares: Optional[float] = None
    peaje_aplica: Optional[bool] = None
    peaje_valor: Optional[float] = None


class ClaseTransporteIn(BaseModel):
    apu_codigo: str
    shift: str
    insumo_codigo: str
    insumo_nombre: str = ""
    categoria: str
    volumen: float
    km_base: Optional[float] = None


class ClasificarIn(BaseModel):
    filas: list[ClaseTransporteIn]
```

- [ ] **Step 5: Agregar los endpoints a `apu_tool/servicio/rutas.py`**

Junto a los de carpetas (después de la sección `# ---- carpetas ----`):

```python
# ---- transporte por proyecto ----
@router.get("/carpetas/{carpeta_id}/transporte")
def ver_transporte(carpeta_id: int, alm: Almacen = Depends(get_almacen),
                   _: object = Depends(requiere_rol("consulta"))):
    try:
        return transporte_svc.ver(alm, carpeta_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.put("/carpetas/{carpeta_id}/transporte")
def guardar_transporte(carpeta_id: int, body: TransporteParamsIn,
                       alm: Almacen = Depends(get_almacen),
                       actor=Depends(requiere_rol("editor"))):
    try:
        return transporte_svc.guardar(alm, carpeta_id, body.model_dump(), actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/transporte/componentes")
def listar_componentes_transporte(alm: Almacen = Depends(get_almacen),
                                  _: object = Depends(requiere_rol("consulta"))):
    return transporte_svc.listar_componentes(alm)


@router.put("/transporte/componentes")
def clasificar_transporte(body: ClasificarIn, alm: Almacen = Depends(get_almacen),
                          actor=Depends(requiere_rol("editor"))):
    try:
        return transporte_svc.clasificar(
            alm, [f.model_dump() for f in body.filas], actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
```

Y los imports: `from apu_tool.servicio import transporte as transporte_svc` y
`ClasificarIn, TransporteParamsIn` en el import de `esquemas`.

- [ ] **Step 6: Correr y verificar que pasa**

Run: `python -m pytest tests/test_api_transporte.py -q`
Expected: PASS (9 tests)

- [ ] **Step 7: Correr toda la suite + los tests de autorización**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/transporte.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_transporte.py
git commit -m "feat(api): distancias del proyecto, impacto y clasificacion de transporte"
```

---

### Task 12: Servicio y endpoints de ajustes del proyecto

**Files:**
- Create: `apu_tool/servicio/ajustes.py`
- Modify: `apu_tool/servicio/esquemas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_ajustes.py`

- [ ] **Step 1: Escribir los tests que fallan**

```python
# tests/test_api_ajustes.py
"""API de ajustes puntuales del proyecto."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cli(tmp_path, rol="admin"):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo(codigo="9001", nombre="GEOTEXTIL NT 2000", unidad="M2", grupo="GEO",
               precio=9000.0, fuente_precio="COSTO INTERNO"),
        Insumo(codigo="6722", nombre="SUBBASE GRANULAR B-400", unidad="M3",
               grupo="AGREGADOS", precio=80000.0, fuente_precio="COSTO INTERNO")])
    alm.apus.insert_apus([Apu(codigo="4390", nombre="RELLENO", unidad="M3",
                              shift="DIURNO", grupo="VIAS")])
    alm.apus.insert_components([
        ApuComponent(apu_codigo="4390", shift="DIURNO", insumo_codigo="6722",
                     insumo_nombre="SUBBASE GRANULAR B-400", unidad="M3",
                     rendimiento=1.0, precio_unitario_hist=80000.0)])
    return cliente(create_app(almacen=alm), rol=rol), alm


def _cuerpo(**kw):
    base = {"apu_codigo": "4390", "shift": "DIURNO", "accion": "agregar",
            "insumo_codigo": "9001", "insumo_nombre": "GEOTEXTIL NT 2000",
            "unidad": "M2", "rendimiento": 1.1, "nota": "lo exige la especificación"}
    base.update(kw)
    return base


def test_crear_listar_borrar(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo())
    assert r.status_code == 200, r.text
    aid = r.json()["id"]
    lista = cli.get(f"/api/carpetas/{cid}/ajustes").json()
    assert len(lista) == 1 and lista[0]["insumo_codigo"] == "9001"
    assert cli.delete(f"/api/carpetas/{cid}/ajustes/{aid}").status_code == 200
    assert cli.get(f"/api/carpetas/{cid}/ajustes").json() == []


def test_accion_invalida_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(accion="inventada"))
    assert r.status_code == 400


def test_rendimiento_no_positivo_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(rendimiento=0))
    assert r.status_code == 400


def test_insumo_inexistente_es_400(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes",
                 json=_cuerpo(insumo_codigo="0000", insumo_nombre="NO EXISTE"))
    assert r.status_code == 400 and "catálogo" in r.text


def test_quitar_no_exige_rendimiento(tmp_path):
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    r = cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo(
        accion="quitar", insumo_codigo="6722",
        insumo_nombre="SUBBASE GRANULAR B-400", rendimiento=None))
    assert r.status_code == 200


def test_consulta_no_puede_escribir(tmp_path):
    cli, alm = _cli(tmp_path, rol="consulta")
    cid = alm.carpetas.crear("Metro")
    assert cli.get(f"/api/carpetas/{cid}/ajustes").status_code == 200
    assert cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo()).status_code == 403


def test_el_ajuste_cambia_el_costo_de_la_corrida(tmp_path):
    from apu_tool.nucleo.models import LicitacionItem
    from apu_tool.servicio import corridas as svc
    cli, alm = _cli(tmp_path)
    cid = alm.carpetas.crear("Metro")
    corrida = svc.construir_corrida(
        alm, "lic.xlsx",
        [LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=1,
                        precio_contractual=200000.0, shift="DIURNO")],
        "DIURNO", False, carpeta_id=cid)
    svc.confirmar_item(alm, corrida, 1, "4390", "DIURNO")
    antes = svc.vista_corrida(alm, corrida)["items"][0]["costo_unitario"]
    cli.post(f"/api/carpetas/{cid}/ajustes", json=_cuerpo())
    despues = svc.vista_corrida(alm, corrida)["items"][0]["costo_unitario"]
    assert despues == antes + 9900          # 1.1 * 9000
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_api_ajustes.py -q`
Expected: FAIL con 404

- [ ] **Step 3: Escribir `apu_tool/servicio/ajustes.py`**

```python
"""
Ajustes puntuales de composición por proyecto: las excepciones que decide el
ingeniero (agregar/quitar/reemplazar un insumo, cambiar un rendimiento).

NO ve dinero: solo estructura. El precio por obra es la lista NP y el peaje es un
parámetro del proyecto. Roles: leer = consulta+, escribir = editor+.
"""
from __future__ import annotations

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio import transporte as regla
from apu_tool.nucleo.models import AjusteProyecto
from apu_tool.nucleo.texto import normalizar
from apu_tool.servicio.auditoria import registrar_auditoria

ACCIONES = ("rendimiento", "agregar", "quitar", "reemplazar")
_EXIGEN_RENDIMIENTO = ("rendimiento", "agregar")


def _out(a: AjusteProyecto) -> dict:
    return {"id": a.id, "apu_codigo": a.apu_codigo, "shift": a.shift,
            "accion": a.accion, "insumo_codigo": a.insumo_codigo,
            "insumo_nombre": a.insumo_nombre, "unidad": a.unidad,
            "rendimiento": a.rendimiento,
            "insumo_nuevo_codigo": a.insumo_nuevo_codigo,
            "insumo_nuevo_nombre": a.insumo_nuevo_nombre,
            "tipo": a.tipo, "ref_shift": a.ref_shift, "nota": a.nota,
            "creado_en": a.creado_en, "creado_por": a.creado_por}


def _insumo_de_catalogo(alm: Almacen, codigo: str, nombre: str):
    """El insumo del catálogo con ESE código y ESE nombre, o None. La identidad es
    código + nombre: los códigos se repiten en el catálogo con significados
    distintos (`7462` es TRANSPORTE DE PETREOS y también NIPLE 16")."""
    objetivo = normalizar(nombre)
    for i in alm.precios.get_candidatos(codigo):
        if normalizar(i.nombre) == objetivo:
            return i
    return None


def listar(alm: Almacen, carpeta_id: int) -> list[dict]:
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        raise ValueError("La carpeta no existe.")
    return [_out(a) for a in alm.carpetas.listar_ajustes(raiz)]


def crear(alm: Almacen, carpeta_id: int, datos: dict, actor=None) -> dict:
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        raise ValueError("La carpeta no existe.")
    accion = str(datos.get("accion") or "")
    if accion not in ACCIONES:
        raise ValueError(f"Acción inválida: «{accion}». Válidas: {', '.join(ACCIONES)}.")
    rend = datos.get("rendimiento")
    if accion in _EXIGEN_RENDIMIENTO and not (rend and float(rend) > 0):
        raise ValueError("El rendimiento debe ser mayor que 0.")
    codigo = str(datos.get("insumo_codigo") or "")
    nombre = str(datos.get("insumo_nombre") or "")
    unidad = str(datos.get("unidad") or "")
    if accion == "agregar":
        ins = _insumo_de_catalogo(alm, codigo, nombre)
        if ins is None:
            raise ValueError(f"El insumo {codigo} «{nombre}» no está en el catálogo.")
        unidad = unidad or ins.unidad
    if accion == "reemplazar":
        nuevo_cod = str(datos.get("insumo_nuevo_codigo") or "")
        nuevo_nom = str(datos.get("insumo_nuevo_nombre") or "")
        nuevo = _insumo_de_catalogo(alm, nuevo_cod, nuevo_nom)
        if nuevo is None:
            raise ValueError(f"El insumo {nuevo_cod} «{nuevo_nom}» no está en el catálogo.")
        # La unidad viaja SIEMPRE la del insumo nuevo: `transporte._un_ajuste` la usa
        # para no dejar el componente reemplazado con la unidad del viejo (si esa
        # unidad fuera M3-KM, la regla lo trataría como acarreo sin serlo).
        unidad = nuevo.unidad
    ajuste = AjusteProyecto(
        carpeta_id=raiz, apu_codigo=str(datos["apu_codigo"]),
        shift=str(datos["shift"]), accion=accion, insumo_codigo=codigo,
        insumo_nombre=nombre, unidad=unidad,
        rendimiento=None if rend is None else float(rend),
        insumo_nuevo_codigo=str(datos.get("insumo_nuevo_codigo") or ""),
        insumo_nuevo_nombre=str(datos.get("insumo_nuevo_nombre") or ""),
        tipo=str(datos.get("tipo") or "insumo"),
        ref_shift=str(datos.get("ref_shift") or ""),
        nota=str(datos.get("nota") or ""))
    email = getattr(actor, "email", None) if actor else None
    with alm.transaccion("corridas") as conn:
        aid = alm.carpetas.crear_ajuste(ajuste, conn=conn, creado_por=email)
        registrar_auditoria(alm, conn, actor, "proyecto.ajuste.crear", "carpeta", raiz,
                            antes=None, despues=_out(ajuste) | {"id": aid})
    return _out(ajuste) | {"id": aid}


def borrar(alm: Almacen, carpeta_id: int, ajuste_id: int, actor=None) -> bool:
    raiz = regla.raiz_de(alm, carpeta_id)
    if raiz is None:
        return False
    previos = {a.id: a for a in alm.carpetas.listar_ajustes(raiz)}
    with alm.transaccion("corridas") as conn:
        ok = alm.carpetas.borrar_ajuste(raiz, ajuste_id, conn=conn)
        if ok:
            registrar_auditoria(
                alm, conn, actor, "proyecto.ajuste.borrar", "carpeta", raiz,
                antes=_out(previos[ajuste_id]) if ajuste_id in previos else None,
                despues=None)
    return ok
```

- [ ] **Step 4: DTO en `esquemas.py` y endpoints en `rutas.py`**

```python
class AjusteProyectoIn(BaseModel):
    apu_codigo: str
    shift: str
    accion: str                          # rendimiento | agregar | quitar | reemplazar
    insumo_codigo: str
    insumo_nombre: str = ""
    unidad: str = ""
    rendimiento: Optional[float] = None
    insumo_nuevo_codigo: str = ""
    insumo_nuevo_nombre: str = ""
    tipo: str = "insumo"
    ref_shift: str = ""
    nota: str = ""
```

```python
@router.get("/carpetas/{carpeta_id}/ajustes")
def listar_ajustes(carpeta_id: int, alm: Almacen = Depends(get_almacen),
                   _: object = Depends(requiere_rol("consulta"))):
    try:
        return ajustes_svc.listar(alm, carpeta_id)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/carpetas/{carpeta_id}/ajustes")
def crear_ajuste(carpeta_id: int, body: AjusteProyectoIn,
                 alm: Almacen = Depends(get_almacen),
                 actor=Depends(requiere_rol("editor"))):
    try:
        return ajustes_svc.crear(alm, carpeta_id, body.model_dump(), actor=actor)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.delete("/carpetas/{carpeta_id}/ajustes/{ajuste_id}")
def borrar_ajuste(carpeta_id: int, ajuste_id: int,
                  alm: Almacen = Depends(get_almacen),
                  actor=Depends(requiere_rol("editor"))):
    if not ajustes_svc.borrar(alm, carpeta_id, ajuste_id, actor=actor):
        raise HTTPException(status_code=404, detail="Ajuste no encontrado.")
    return {"ok": True}
```

Import: `from apu_tool.servicio import ajustes as ajustes_svc` y `AjusteProyectoIn`.

- [ ] **Step 5: Correr y verificar que pasa**

Run: `python -m pytest tests/test_api_ajustes.py tests/test_api_autorizacion.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/ajustes.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_ajustes.py
git commit -m "feat(api): ajustes puntuales de composicion por proyecto"
```

---

### Task 13: Hoja «DESVIACIONES DEL PROYECTO» en el cuadro

**Files:**
- Modify: `apu_tool/dominio/report.py:167-186`
- Modify: `apu_tool/servicio/corridas.py` (`generar_cuadro`, línea ~470)
- Test: `tests/test_report_desviaciones.py`

- [ ] **Step 1: Escribir el test que falla**

```python
# tests/test_report_desviaciones.py
"""El cuadro documenta con qué distancias y ajustes se costeó."""
import openpyxl

from apu_tool.dominio.report import write_report
from apu_tool.nucleo.models import (
    AjusteProyecto, AssembledApu, CostedComponent, LicitacionItem, MatchStatus,
    ParametrosProyecto)


def _ens():
    item = LicitacionItem(item="1", descripcion="RELLENO", unidad="M3", cantidad=2,
                          precio_contractual=100000.0, shift="DIURNO")
    comp = CostedComponent(insumo_codigo="7462", insumo_nombre="TRANSPORTE DE PETREOS",
                           unidad="M3-KM", rendimiento=33.6, precio_unitario=1000.0,
                           fuente_precio="COSTO INTERNO", costo=33600)
    return AssembledApu(item=item, apu_codigo="4390", apu_nombre="RELLENO",
                        unidad="M3", shift="DIURNO", componentes=[comp],
                        costo_unitario=33600, status=MatchStatus.CONFIRMED,
                        confianza=1.0)


def test_sin_desviaciones_no_hay_hoja(tmp_path):
    out = write_report([_ens()], tmp_path / "cuadro.xlsx")
    wb = openpyxl.load_workbook(out)
    assert "DESVIACIONES DEL PROYECTO" not in wb.sheetnames


def test_con_desviaciones_la_hoja_las_lista(tmp_path):
    out = write_report(
        [_ens()], tmp_path / "cuadro.xlsx",
        parametros=ParametrosProyecto(km_botadero=34, km_mezclas=28, km_granulares=32,
                                      peaje_aplica=True, peaje_valor=12400),
        ajustes=[AjusteProyecto(apu_codigo="4390", shift="DIURNO", accion="agregar",
                                insumo_codigo="9001",
                                insumo_nombre="GEOTEXTIL NT 2000", unidad="M2",
                                rendimiento=1.1, nota="especificación del cliente")])
    wb = openpyxl.load_workbook(out)
    ws = wb["DESVIACIONES DEL PROYECTO"]
    texto = "\n".join(str(c.value) for row in ws.iter_rows() for c in row
                      if c.value is not None)
    assert "34" in texto and "Botadero" in texto
    assert "12400" in texto or "12.400" in texto
    assert "GEOTEXTIL NT 2000" in texto and "especificación del cliente" in texto
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `python -m pytest tests/test_report_desviaciones.py -q`
Expected: FAIL con `TypeError: write_report() got an unexpected keyword argument 'parametros'`

- [ ] **Step 3: Modificar `apu_tool/dominio/report.py`**

Agregar el builder antes de `write_report`:

```python
def _build_desviaciones(ws, parametros, ajustes) -> None:
    """Con qué distancias, peaje y ajustes se costeó este cuadro. Sin esta hoja,
    dos cuadros del mismo APU con distancias distintas son indistinguibles."""
    ws.append(["PARÁMETRO", "VALOR"])
    _style_header(ws, 1, 2)
    if parametros is not None:
        ws.append(["Botadero (km)", parametros.km_botadero])
        ws.append(["Mezclas asfálticas (km)", parametros.km_mezclas])
        ws.append(["Granulares y pétreos (km)", parametros.km_granulares])
        peaje = ("sí" if parametros.peaje_aplica else
                 "no" if parametros.peaje_aplica is False else "sin definir")
        ws.append(["¿Hay peaje?", peaje])
        ws.append(["Valor del peaje", parametros.peaje_valor])
        ws.cell(row=ws.max_row, column=2).number_format = _MONEY
    if ajustes:
        ws.append([])
        fila = ws.max_row + 1
        ws.append(["APU", "TURNO", "ACCIÓN", "INSUMO", "NOMBRE", "REND.", "NOTA"])
        _style_header(ws, fila, 7)
        for a in ajustes:
            ws.append([a.apu_codigo, a.shift, a.accion, a.insumo_codigo,
                       a.insumo_nombre or a.insumo_nuevo_nombre, a.rendimiento, a.nota])
            ws.cell(row=ws.max_row, column=6).number_format = _REND
    _autosize(ws, {1: 26, 2: 18, 3: 14, 4: 12, 5: 40, 6: 10, 7: 40})
```

Y `write_report`:

```python
def write_report(apus: list[AssembledApu], path: Path | str,
                 lista_nombre: str = "Principal",
                 parametros=None, ajustes=()) -> Path:
    ...
    _build_alertas(wb.create_sheet("ALERTAS"), apus)
    # Solo si el proyecto realmente se desvía de la biblioteca.
    if (parametros is not None and not parametros.vacio) or ajustes:
        _build_desviaciones(wb.create_sheet("DESVIACIONES DEL PROYECTO"),
                            parametros, list(ajustes))
    # Metadatos.
    ...
```

`report_categorizado.py` recibe el mismo par de parámetros y llama al mismo
`_build_desviaciones` (importándolo de `report.py`).

- [ ] **Step 4: Pasar los datos desde `generar_cuadro`**

En `apu_tool/servicio/corridas.py`, dentro de `generar_cuadro`:

```python
    ctx = _contexto(alm, meta)
    write_report(assembled, out, lista_nombre=_nombre_lista(alm, meta.lista_precios_id),
                 parametros=ctx.params, ajustes=ctx.ajustes)
```

- [ ] **Step 5: Exponer las distancias en el encabezado de la corrida**

Sin esto, quien abre una corrida no sabe con qué distancias está viendo los costos
(y es la mitigación del riesgo de mover una corrida de carpeta).

Test primero, en `tests/test_transporte_corridas.py`:

```python
def test_la_vista_de_la_corrida_dice_con_que_distancias_costeo(tmp_path):
    alm = _alm(tmp_path)
    metro = alm.carpetas.crear("Metro")
    alm.carpetas.set_parametros(ParametrosProyecto(carpeta_id=metro, km_granulares=32,
                                                  peaje_aplica=True, peaje_valor=12400))
    cid = _corrida(alm, metro)
    meta = svc.vista_corrida(alm, cid)["meta"]
    assert meta["carpeta_id"] == metro
    assert meta["transporte"]["km_granulares"] == 32
    assert meta["transporte"]["peaje_valor"] == 12400
    # una corrida sin proyecto no trae distancias
    otra = _corrida(alm, alm.carpetas.crear("Sin distancias"))
    assert svc.vista_corrida(alm, otra)["meta"]["transporte"] is None
```

En `apu_tool/servicio/corridas.py`, donde `vista_corrida` arma el dict `meta`,
agregar las dos claves (`carpeta_id` puede ya estar; si está, dejarla):

```python
    ctx = _contexto(alm, meta)
    ...
    "carpeta_id": meta.carpeta_id,
    # Con qué distancias se está costeando: el encabezado de la corrida lo muestra.
    "transporte": (None if ctx.params.vacio else {
        "km_botadero": ctx.params.km_botadero,
        "km_mezclas": ctx.params.km_mezclas,
        "km_granulares": ctx.params.km_granulares,
        "peaje_aplica": ctx.params.peaje_aplica,
        "peaje_valor": ctx.params.peaje_valor,
        "ajustes": len(ctx.ajustes)}),
```

En `web/src/lib/tipos.ts`, agregar a la interfaz del `meta` de `CorridaDetalle`:
`carpeta_id: number | null;` y `transporte: (ParametrosTransporte & { ajustes: number }) | null;`.

En `web/src/pages/Corrida.tsx`, junto al badge de estado:

```tsx
{corrida.meta.transporte && (
  <span className="text-xs text-muted-foreground">
    botadero {corrida.meta.transporte.km_botadero ?? "—"} km · mezclas{" "}
    {corrida.meta.transporte.km_mezclas ?? "—"} · granulares{" "}
    {corrida.meta.transporte.km_granulares ?? "—"}
    {corrida.meta.transporte.peaje_aplica
      ? ` · peaje $${corrida.meta.transporte.peaje_valor}` : " · sin peaje"}
    {corrida.meta.transporte.ajustes > 0
      ? ` · ${corrida.meta.transporte.ajustes} ajustes` : ""}
  </span>
)}
```

- [ ] **Step 6: Correr y verificar que pasa**

Run: `python -m pytest tests/test_report_desviaciones.py tests/test_transporte_corridas.py -q`
Expected: PASS (para los tests del cuadro que ya existían: `python -m pytest tests/ -q -k report`)

Run: `cd web && npm run build`
Expected: build OK

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/report.py apu_tool/dominio/report_categorizado.py apu_tool/servicio/corridas.py web/src/lib/tipos.ts web/src/pages/Corrida.tsx tests/test_report_desviaciones.py tests/test_transporte_corridas.py
git commit -m "feat(cuadro): hoja DESVIACIONES y encabezado con las distancias vigentes"
```

---

## FASE 5 — Web

### Task 14: Cliente HTTP y tipos

**Files:**
- Create: `web/src/api/transporte.ts`
- Modify: `web/src/lib/tipos.ts`
- Test: `web/src/api/transporte.test.ts`

- [ ] **Step 1: Escribir el test que falla**

```ts
// web/src/api/transporte.test.ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import * as client from "@/api/client";
import { verTransporte, guardarTransporte, listarComponentes, clasificar,
         listarAjustes, crearAjuste, borrarAjuste } from "@/api/transporte";

describe("api/transporte", () => {
  beforeEach(() => vi.restoreAllMocks());

  it("usa las rutas del contrato", async () => {
    const get = vi.spyOn(client, "apiGet").mockResolvedValue({} as never);
    const put = vi.spyOn(client, "apiPut").mockResolvedValue({} as never);
    const post = vi.spyOn(client, "apiPost").mockResolvedValue({} as never);
    const del = vi.spyOn(client, "apiDelete").mockResolvedValue(undefined as never);
    await verTransporte(7);
    expect(get).toHaveBeenCalledWith("/carpetas/7/transporte");
    await guardarTransporte(7, { km_botadero: 34 });
    expect(put).toHaveBeenCalledWith("/carpetas/7/transporte", { km_botadero: 34 });
    await listarComponentes();
    expect(get).toHaveBeenCalledWith("/transporte/componentes");
    await clasificar([{ apu_codigo: "4390", shift: "DIURNO", insumo_codigo: "7462",
                       insumo_nombre: "TTE", categoria: "granulares", volumen: 1.05,
                       km_base: 25 }]);
    expect(put).toHaveBeenCalledWith("/transporte/componentes", { filas: expect.any(Array) });
    await listarAjustes(7);
    expect(get).toHaveBeenCalledWith("/carpetas/7/ajustes");
    await crearAjuste(7, { apu_codigo: "4390", shift: "DIURNO", accion: "quitar",
                           insumo_codigo: "1", insumo_nombre: "X" });
    expect(post).toHaveBeenCalledWith("/carpetas/7/ajustes", expect.any(Object));
    await borrarAjuste(7, 3);
    expect(del).toHaveBeenCalledWith("/carpetas/7/ajustes/3");
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/api/transporte.test.ts`
Expected: FAIL — `Cannot find module '@/api/transporte'`

- [ ] **Step 3: Agregar los tipos a `web/src/lib/tipos.ts`**

```ts
export type CategoriaTransporte = "botadero" | "mezclas" | "granulares";

export interface ParametrosTransporte {
  carpeta_id?: number;
  km_botadero: number | null;
  km_mezclas: number | null;
  km_granulares: number | null;
  peaje_aplica: boolean | null;
  peaje_valor: number | null;
  actualizado_en?: string;
  actualizado_por?: string | null;
}

export interface FilaImpacto {
  apu_codigo: string;
  shift: string;
  insumo_codigo: string;
  insumo_nombre: string;
  unidad: string;
  rendimiento_actual: number;
  categoria: CategoriaTransporte | null;
  volumen: number | null;
  rendimiento_nuevo: number | null;
  quitado: boolean;
  origen: "biblioteca" | "distancia";
  sin_clasificar: boolean;
}

export interface VistaTransporte {
  parametros: ParametrosTransporte;
  impacto: FilaImpacto[];
  sin_clasificar: number;
}

export interface FilaClasificacion {
  apu_codigo: string;
  shift: string;
  apu_nombre: string;
  insumo_codigo: string;
  insumo_nombre: string;
  unidad: string;
  rendimiento: number;
  categoria: CategoriaTransporte | null;
  categoria_sugerida: CategoriaTransporte | null;
  volumen: number;
  km_base: number;
  km_implicito: number | null;
}

export interface ListaClasificacion {
  items: FilaClasificacion[];
  total: number;
  categorias: CategoriaTransporte[];
  km_base_defecto: number;
}

export interface ClaseTransporteIn {
  apu_codigo: string;
  shift: string;
  insumo_codigo: string;
  insumo_nombre: string;
  categoria: CategoriaTransporte;
  volumen: number;
  km_base?: number | null;
}

export type AccionAjuste = "rendimiento" | "agregar" | "quitar" | "reemplazar";

export interface AjusteProyecto {
  id?: number;
  apu_codigo: string;
  shift: string;
  accion: AccionAjuste;
  insumo_codigo: string;
  insumo_nombre: string;
  unidad?: string;
  rendimiento?: number | null;
  insumo_nuevo_codigo?: string;
  insumo_nuevo_nombre?: string;
  tipo?: string;
  ref_shift?: string;
  nota?: string;
  creado_en?: string;
  creado_por?: string | null;
}
```

- [ ] **Step 4: Escribir `web/src/api/transporte.ts`**

```ts
import { apiGet, apiPost, apiPut, apiDelete } from "@/api/client";
import type {
  AjusteProyecto, ClaseTransporteIn, ListaClasificacion, ParametrosTransporte,
  VistaTransporte,
} from "@/lib/tipos";

export function verTransporte(carpetaId: number): Promise<VistaTransporte> {
  return apiGet<VistaTransporte>(`/carpetas/${carpetaId}/transporte`);
}

export function guardarTransporte(
  carpetaId: number, params: Partial<ParametrosTransporte>,
): Promise<VistaTransporte> {
  return apiPut<VistaTransporte>(`/carpetas/${carpetaId}/transporte`, params);
}

export function listarComponentes(): Promise<ListaClasificacion> {
  return apiGet<ListaClasificacion>("/transporte/componentes");
}

export function clasificar(filas: ClaseTransporteIn[]): Promise<{ aplicados: number }> {
  return apiPut<{ aplicados: number }>("/transporte/componentes", { filas });
}

export function listarAjustes(carpetaId: number): Promise<AjusteProyecto[]> {
  return apiGet<AjusteProyecto[]>(`/carpetas/${carpetaId}/ajustes`);
}

export function crearAjuste(
  carpetaId: number, ajuste: AjusteProyecto,
): Promise<AjusteProyecto> {
  return apiPost<AjusteProyecto>(`/carpetas/${carpetaId}/ajustes`, ajuste);
}

export function borrarAjuste(carpetaId: number, ajusteId: number): Promise<void> {
  return apiDelete(`/carpetas/${carpetaId}/ajustes/${ajusteId}`);
}
```

Si `apiPut` no existe en `web/src/api/client.ts`, agregarlo copiando `apiPatch`
y cambiando el verbo a `"PUT"`.

- [ ] **Step 5: Correr y verificar que pasa**

Run: `cd web && npx vitest run src/api/transporte.test.ts && npm run build`
Expected: PASS + build OK (`tsc -b`, no `--noEmit`)

- [ ] **Step 6: Commit**

```bash
git add web/src/api/transporte.ts web/src/api/transporte.test.ts web/src/lib/tipos.ts web/src/api/client.ts
git commit -m "feat(web): cliente HTTP de transporte por proyecto"
```

---

### Task 15: Pantalla «Distancias del proyecto»

**Files:**
- Create: `web/src/pages/DistanciasProyecto.tsx`
- Modify: `web/src/App.tsx` (ruta `/proyecto/:carpetaId/distancias`)
- Modify: `web/src/pages/MisCorridas.tsx` (botón en las carpetas de nivel 1)
- Test: `web/src/pages/DistanciasProyecto.test.tsx`

- [ ] **Step 1: Escribir el test que falla**

```tsx
// web/src/pages/DistanciasProyecto.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter, Route, Routes } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as api from "@/api/transporte";
import DistanciasProyecto from "@/pages/DistanciasProyecto";

const VISTA = {
  parametros: { km_botadero: 34, km_mezclas: null, km_granulares: 32,
                peaje_aplica: true, peaje_valor: 12400 },
  impacto: [{ apu_codigo: "4390", shift: "DIURNO", insumo_codigo: "7462",
              insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
              rendimiento_actual: 26.25, categoria: "granulares", volumen: 1.05,
              rendimiento_nuevo: 33.6, quitado: false, origen: "distancia",
              sin_clasificar: false },
             { apu_codigo: "4200", shift: "DIURNO", insumo_codigo: "6878",
               insumo_nombre: "TRANSPORTE DE BASES ASFALTICAS", unidad: "M3-KM",
               rendimiento_actual: 26.25, categoria: null, volumen: null,
               rendimiento_nuevo: 26.25, quitado: false, origen: "biblioteca",
               sin_clasificar: true }],
  sin_clasificar: 1,
};

function montar() {
  return render(
    <MemoryRouter initialEntries={["/proyecto/7/distancias"]}>
      <Routes>
        <Route path="/proyecto/:carpetaId/distancias" element={<DistanciasProyecto />} />
      </Routes>
    </MemoryRouter>);
}

describe("DistanciasProyecto", () => {
  it("muestra los parámetros y el impacto", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    montar();
    expect(await screen.findByDisplayValue("34")).toBeInTheDocument();
    expect(screen.getByText("TRANSPORTE DE PETREOS")).toBeInTheDocument();
    expect(screen.getByText("33,6")).toBeInTheDocument();
    expect(screen.getByText(/1 componente sin clasificar/i)).toBeInTheDocument();
  });

  it("guarda los parámetros", async () => {
    vi.spyOn(api, "verTransporte").mockResolvedValue(VISTA as never);
    const guardar = vi.spyOn(api, "guardarTransporte").mockResolvedValue(VISTA as never);
    montar();
    const botadero = await screen.findByLabelText(/botadero/i);
    await userEvent.clear(botadero);
    await userEvent.type(botadero, "40");
    await userEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenCalledWith(
      7, expect.objectContaining({ km_botadero: 40 })));
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/pages/DistanciasProyecto.test.tsx`
Expected: FAIL — `Cannot find module '@/pages/DistanciasProyecto'`

- [ ] **Step 3: Escribir `web/src/pages/DistanciasProyecto.tsx`**

Página densa, table-first, sin cards (patrón de `pages/Insumos.tsx` y
`components/insumos/BarraFiltros.tsx`):

```tsx
import { useEffect, useState } from "react";
import { Link, useParams } from "react-router-dom";
import { toast } from "sonner";
import { verTransporte, guardarTransporte } from "@/api/transporte";
import type { ParametrosTransporte, VistaTransporte } from "@/lib/tipos";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NUM = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 3 });

function num(v: string): number | null {
  const t = v.trim();
  if (!t) return null;
  const n = Number(t.replace(",", "."));
  return Number.isFinite(n) ? n : null;
}

export default function DistanciasProyecto() {
  const carpetaId = Number(useParams().carpetaId);
  const [vista, setVista] = useState<VistaTransporte | null>(null);
  const [form, setForm] = useState<Record<string, string>>({});
  const [peaje, setPeaje] = useState(false);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    verTransporte(carpetaId)
      .then((v) => {
        setVista(v);
        setForm({
          km_botadero: v.parametros.km_botadero?.toString() ?? "",
          km_mezclas: v.parametros.km_mezclas?.toString() ?? "",
          km_granulares: v.parametros.km_granulares?.toString() ?? "",
          peaje_valor: v.parametros.peaje_valor?.toString() ?? "",
        });
        setPeaje(v.parametros.peaje_aplica === true);
      })
      .catch((e) => toast.error(String(e)));
  }, [carpetaId]);

  async function guardar() {
    setGuardando(true);
    try {
      const payload: Partial<ParametrosTransporte> = {
        km_botadero: num(form.km_botadero ?? ""),
        km_mezclas: num(form.km_mezclas ?? ""),
        km_granulares: num(form.km_granulares ?? ""),
        peaje_aplica: peaje,
        peaje_valor: peaje ? num(form.peaje_valor ?? "") : null,
      };
      setVista(await guardarTransporte(carpetaId, payload));
      toast.success("Distancias del proyecto guardadas. Las corridas activas se recostean.");
    } catch (e) {
      toast.error(String(e));
    } finally {
      setGuardando(false);
    }
  }

  if (!vista) return <div className="p-4 text-sm text-muted-foreground">Cargando…</div>;

  return (
    <div className="p-4 space-y-4">
      <div className="flex flex-wrap items-end gap-4">
        <Campo id="km_botadero" etiqueta="Botadero (km)" form={form} setForm={setForm} />
        <Campo id="km_mezclas" etiqueta="Mezclas (km)" form={form} setForm={setForm} />
        <Campo id="km_granulares" etiqueta="Granulares (km)" form={form} setForm={setForm} />
        <label className="flex items-center gap-2 text-sm">
          <input type="checkbox" checked={peaje} onChange={(e) => setPeaje(e.target.checked)} />
          Peaje
        </label>
        {peaje && (
          <Campo id="peaje_valor" etiqueta="Valor del peaje" form={form} setForm={setForm} />
        )}
        <Button onClick={guardar} disabled={guardando}>
          {guardando ? "Guardando…" : "Guardar"}
        </Button>
      </div>

      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-1 pr-3">APU</th>
              <th className="py-1 pr-3">Insumo</th>
              <th className="py-1 pr-3">Un.</th>
              <th className="py-1 pr-3 text-right">Rend. hoy</th>
              <th className="py-1 pr-3">Categoría</th>
              <th className="py-1 pr-3 text-right">Vol.</th>
              <th className="py-1 pr-3 text-right">Rend. nuevo</th>
            </tr>
          </thead>
          <tbody>
            {vista.impacto.map((f) => (
              <tr key={`${f.apu_codigo}|${f.shift}|${f.insumo_codigo}`} className="border-b">
                <td className="py-1 pr-3 font-mono">{f.apu_codigo}</td>
                <td className="py-1 pr-3">
                  <span className="font-mono text-muted-foreground">{f.insumo_codigo}</span>{" "}
                  {f.insumo_nombre}
                </td>
                <td className="py-1 pr-3">{f.unidad}</td>
                <td className="py-1 pr-3 text-right">{NUM.format(f.rendimiento_actual)}</td>
                <td className="py-1 pr-3">{f.categoria ?? "—"}</td>
                <td className="py-1 pr-3 text-right">
                  {f.volumen === null ? "—" : NUM.format(f.volumen)}
                </td>
                <td className="py-1 pr-3 text-right">
                  {f.quitado ? "quitado"
                    : f.sin_clasificar ? "⚠ sin clasificar"
                    : NUM.format(f.rendimiento_nuevo ?? f.rendimiento_actual)}
                </td>
              </tr>
            ))}
          </tbody>
        </table>
      </div>

      <div className="text-sm text-muted-foreground">
        {vista.impacto.length} componentes de acarreo ·{" "}
        {vista.sin_clasificar} componente{vista.sin_clasificar === 1 ? "" : "s"} sin
        clasificar{" "}
        <Link className="underline" to="/transporte/clasificacion">Clasificar</Link>
      </div>
    </div>
  );
}

function Campo({ id, etiqueta, form, setForm }: {
  id: string; etiqueta: string;
  form: Record<string, string>;
  setForm: (f: (p: Record<string, string>) => Record<string, string>) => void;
}) {
  return (
    <label className="flex flex-col gap-1 text-sm">
      <span className="text-muted-foreground">{etiqueta}</span>
      <Input id={id} aria-label={etiqueta} className="w-28" inputMode="decimal"
             value={form[id] ?? ""}
             onChange={(e) => setForm((p) => ({ ...p, [id]: e.target.value }))} />
    </label>
  );
}
```

- [ ] **Step 4: Registrar la ruta y el botón**

En `web/src/App.tsx`, junto a las demás rutas:

```tsx
<Route path="/proyecto/:carpetaId/distancias" element={<DistanciasProyecto />} />
<Route path="/transporte/clasificacion" element={<ClasificacionTransporte />} />
```

En `web/src/pages/MisCorridas.tsx`, en la fila de una carpeta **de nivel 1**
(`carpeta.parent_id === null`), junto a los botones de renombrar/mover/eliminar:

```tsx
<Link to={`/proyecto/${carpeta.id}/distancias`} className="underline text-xs"
      onClick={(e) => e.stopPropagation()}>
  Distancias
</Link>
```

- [ ] **Step 5: Correr y verificar que pasa**

Run: `cd web && npx vitest run src/pages/DistanciasProyecto.test.tsx && npm run build`
Expected: PASS + build OK

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/DistanciasProyecto.tsx web/src/pages/DistanciasProyecto.test.tsx web/src/App.tsx web/src/pages/MisCorridas.tsx
git commit -m "feat(web): pantalla de distancias del proyecto"
```

---

### Task 16: Pantalla «Clasificación de transporte»

**Files:**
- Create: `web/src/pages/ClasificacionTransporte.tsx`
- Test: `web/src/pages/ClasificacionTransporte.test.tsx`

- [ ] **Step 1: Escribir el test que falla**

```tsx
// web/src/pages/ClasificacionTransporte.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { MemoryRouter } from "react-router-dom";
import { describe, expect, it, vi } from "vitest";
import * as api from "@/api/transporte";
import ClasificacionTransporte from "@/pages/ClasificacionTransporte";

const LISTA = {
  items: [
    { apu_codigo: "4390", shift: "DIURNO", apu_nombre: "RELLENO",
      insumo_codigo: "7462", insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
      rendimiento: 26.25, categoria: null, categoria_sugerida: "granulares",
      volumen: 1.05, km_base: 25, km_implicito: 25 },
    { apu_codigo: "4919", shift: "DIURNO", apu_nombre: "SUMIDERO",
      insumo_codigo: "7462", insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
      rendimiento: 0.28, categoria: null, categoria_sugerida: "granulares",
      volumen: 0.0112, km_base: 25, km_implicito: 25 },
  ],
  total: 2, categorias: ["botadero", "mezclas", "granulares"], km_base_defecto: 25,
};

describe("ClasificacionTransporte", () => {
  it("lista las filas con su categoría sugerida y su volumen", async () => {
    vi.spyOn(api, "listarComponentes").mockResolvedValue(LISTA as never);
    render(<MemoryRouter><ClasificacionTransporte /></MemoryRouter>);
    expect(await screen.findByText("SUMIDERO")).toBeInTheDocument();
    expect(screen.getAllByDisplayValue("granulares").length).toBe(2);
    expect(screen.getByText("0,0112")).toBeInTheDocument();
  });

  it("guarda la clasificación en bloque", async () => {
    vi.spyOn(api, "listarComponentes").mockResolvedValue(LISTA as never);
    const guardar = vi.spyOn(api, "clasificar")
      .mockResolvedValue({ aplicados: 2 } as never);
    render(<MemoryRouter><ClasificacionTransporte /></MemoryRouter>);
    await screen.findByText("SUMIDERO");
    await userEvent.click(screen.getByRole("button", { name: /guardar/i }));
    await waitFor(() => expect(guardar).toHaveBeenCalledWith(
      expect.arrayContaining([expect.objectContaining({
        apu_codigo: "4390", categoria: "granulares", volumen: 1.05 })])));
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/pages/ClasificacionTransporte.test.tsx`
Expected: FAIL — módulo inexistente

- [ ] **Step 3: Escribir `web/src/pages/ClasificacionTransporte.tsx`**

Tabla editable: `km base` por fila (default el del backend), `volumen` derivado
(`rendimiento / km_base`, recalculado al escribir), `categoría` en un `<select>`
precargado con la sugerida, y un aviso en las filas con volumen atípico
(`< 0.5` o `> 2`, los valores plausibles de esponjamiento por m³).

```tsx
import { useEffect, useMemo, useState } from "react";
import { toast } from "sonner";
import { listarComponentes, clasificar } from "@/api/transporte";
import type { CategoriaTransporte, FilaClasificacion } from "@/lib/tipos";
import { Button } from "@/components/ui/button";
import { Input } from "@/components/ui/input";

const NUM = new Intl.NumberFormat("es-CO", { maximumFractionDigits: 4 });
const clave = (f: FilaClasificacion) => `${f.apu_codigo}|${f.shift}|${f.insumo_codigo}`;

export default function ClasificacionTransporte() {
  const [filas, setFilas] = useState<FilaClasificacion[]>([]);
  const [categorias, setCategorias] = useState<CategoriaTransporte[]>([]);
  const [guardando, setGuardando] = useState(false);

  useEffect(() => {
    listarComponentes()
      .then((l) => {
        setCategorias(l.categorias);
        setFilas(l.items.map((f) => ({
          ...f, categoria: f.categoria ?? f.categoria_sugerida })));
      })
      .catch((e) => toast.error(String(e)));
  }, []);

  const atipicas = useMemo(
    () => filas.filter((f) => f.volumen < 0.5 || f.volumen > 2).length, [filas]);

  function editar(k: string, cambio: Partial<FilaClasificacion>) {
    setFilas((prev) => prev.map((f) => {
      if (clave(f) !== k) return f;
      const fusion = { ...f, ...cambio };
      // El volumen se deriva del km base: es la perilla de calibración.
      if (cambio.km_base !== undefined && fusion.km_base > 0) {
        fusion.volumen = fusion.rendimiento / fusion.km_base;
      }
      fusion.km_implicito = fusion.volumen > 0
        ? Number((fusion.rendimiento / fusion.volumen).toFixed(2)) : null;
      return fusion;
    }));
  }

  async function guardar() {
    const listas = filas.filter((f) => f.categoria && f.volumen > 0);
    if (!listas.length) { toast.error("No hay filas con categoría y volumen."); return; }
    setGuardando(true);
    try {
      const r = await clasificar(listas.map((f) => ({
        apu_codigo: f.apu_codigo, shift: f.shift, insumo_codigo: f.insumo_codigo,
        insumo_nombre: f.insumo_nombre, categoria: f.categoria as CategoriaTransporte,
        volumen: f.volumen, km_base: f.km_base })));
      toast.success(`${r.aplicados} componentes clasificados.`);
    } catch (e) {
      toast.error(String(e));
    } finally {
      setGuardando(false);
    }
  }

  return (
    <div className="p-4 space-y-3">
      <div className="flex items-center gap-3 text-sm">
        <span className="text-muted-foreground">
          {filas.length} componentes de acarreo · {atipicas} con volumen atípico
        </span>
        <Button onClick={guardar} disabled={guardando}>
          {guardando ? "Guardando…" : "Guardar clasificación"}
        </Button>
      </div>
      <div className="overflow-x-auto">
        <table className="w-full text-sm border-collapse">
          <thead>
            <tr className="border-b text-left text-muted-foreground">
              <th className="py-1 pr-3">APU</th>
              <th className="py-1 pr-3">Insumo</th>
              <th className="py-1 pr-3 text-right">Rend.</th>
              <th className="py-1 pr-3">Categoría</th>
              <th className="py-1 pr-3 text-right">km base</th>
              <th className="py-1 pr-3 text-right">Volumen</th>
              <th className="py-1 pr-3 text-right">km implícito</th>
            </tr>
          </thead>
          <tbody>
            {filas.map((f) => {
              const k = clave(f);
              const raro = f.volumen < 0.5 || f.volumen > 2;
              return (
                <tr key={k} className="border-b">
                  <td className="py-1 pr-3">
                    <span className="font-mono">{f.apu_codigo}</span>{" "}
                    <span className="text-muted-foreground">{f.apu_nombre}</span>
                  </td>
                  <td className="py-1 pr-3">
                    <span className="font-mono text-muted-foreground">{f.insumo_codigo}</span>{" "}
                    {f.insumo_nombre}
                  </td>
                  <td className="py-1 pr-3 text-right">{NUM.format(f.rendimiento)}</td>
                  <td className="py-1 pr-3">
                    <select className="border rounded px-1 py-0.5 bg-background"
                            aria-label={`Categoría de ${k}`}
                            value={f.categoria ?? ""}
                            onChange={(e) => editar(k, {
                              categoria: (e.target.value || null) as CategoriaTransporte })}>
                      <option value="">—</option>
                      {categorias.map((c) => <option key={c} value={c}>{c}</option>)}
                    </select>
                  </td>
                  <td className="py-1 pr-3 text-right">
                    <Input className="w-20 text-right" inputMode="decimal"
                           aria-label={`km base de ${k}`}
                           value={String(f.km_base)}
                           onChange={(e) => editar(k, {
                             km_base: Number(e.target.value.replace(",", ".")) || 0 })} />
                  </td>
                  <td className={`py-1 pr-3 text-right ${raro ? "text-amber-600" : ""}`}>
                    {NUM.format(f.volumen)}{raro ? " ⚠" : ""}
                  </td>
                  <td className="py-1 pr-3 text-right">
                    {f.km_implicito === null ? "—" : NUM.format(f.km_implicito)}
                  </td>
                </tr>
              );
            })}
          </tbody>
        </table>
      </div>
    </div>
  );
}
```

- [ ] **Step 4: Correr y verificar que pasa**

Run: `cd web && npx vitest run src/pages/ClasificacionTransporte.test.tsx && npm run build`
Expected: PASS + build OK

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/ClasificacionTransporte.tsx web/src/pages/ClasificacionTransporte.test.tsx
git commit -m "feat(web): pantalla de clasificacion de transporte"
```

---

### Task 17: Composición del ítem editable con alcance proyecto

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx` (bloque de composición, ~línea 584)
- Test: `web/src/components/corrida/TablaItems.composicion.test.tsx`

- [ ] **Step 1: Escribir el test que falla**

```tsx
// web/src/components/corrida/TablaItems.composicion.test.tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { describe, expect, it, vi } from "vitest";
import * as apiTte from "@/api/transporte";
import { FilaComposicion } from "@/components/corrida/TablaItems";

const LINEA = {
  insumo_codigo: "7462", insumo_nombre: "TRANSPORTE DE PETREOS", unidad: "M3-KM",
  rendimiento: 33.6, precio_unitario: 1000, fuente_precio: "COSTO INTERNO",
  costo: 33600, calidad_cruce: "exacto",
};

describe("FilaComposicion", () => {
  it("permite ajustar el rendimiento para el proyecto", async () => {
    const crear = vi.spyOn(apiTte, "crearAjuste").mockResolvedValue({} as never);
    const onCambio = vi.fn();
    render(<table><tbody>
      <FilaComposicion linea={LINEA} apuCodigo="4390" turno="DIURNO"
                       carpetaId={7} editable onCambio={onCambio} />
    </tbody></table>);
    await userEvent.click(screen.getByRole("button", { name: /ajustar/i }));
    const campo = screen.getByLabelText(/rendimiento del proyecto/i);
    await userEvent.clear(campo);
    await userEvent.type(campo, "40");
    await userEvent.click(screen.getByRole("button", { name: /aplicar/i }));
    await waitFor(() => expect(crear).toHaveBeenCalledWith(7, expect.objectContaining({
      apu_codigo: "4390", shift: "DIURNO", accion: "rendimiento",
      insumo_codigo: "7462", rendimiento: 40 })));
    expect(onCambio).toHaveBeenCalled();
  });

  it("sin carpeta o sin permiso no muestra el botón", () => {
    render(<table><tbody>
      <FilaComposicion linea={LINEA} apuCodigo="4390" turno="DIURNO"
                       carpetaId={7} editable={false} onCambio={() => {}} />
    </tbody></table>);
    expect(screen.queryByRole("button", { name: /ajustar/i })).toBeNull();
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.composicion.test.tsx`
Expected: FAIL — `FilaComposicion` no está exportado

- [ ] **Step 3: Extraer y hacer editable la fila de composición**

En `web/src/components/corrida/TablaItems.tsx`, reemplazar el bloque de la tabla de
composición (dentro de `DetalleFila`, ~línea 584) por filas `<FilaComposicion>` y
exportar el componente nuevo:

```tsx
export function FilaComposicion({ linea, apuCodigo, turno, carpetaId, editable, onCambio }: {
  linea: LineaComposicion;
  apuCodigo: string | null;
  turno: string;
  carpetaId: number | null;
  editable: boolean;
  onCambio: () => void;
}) {
  const [abierto, setAbierto] = useState(false);
  const [valor, setValor] = useState(String(linea.rendimiento));
  const [enviando, setEnviando] = useState(false);
  const puede = editable && carpetaId !== null && apuCodigo !== null;

  async function aplicar() {
    const rend = Number(valor.replace(",", "."));
    if (!Number.isFinite(rend) || rend <= 0) { toast.error("Rendimiento inválido."); return; }
    setEnviando(true);
    try {
      await crearAjuste(carpetaId as number, {
        apu_codigo: apuCodigo as string, shift: turno, accion: "rendimiento",
        insumo_codigo: linea.insumo_codigo, insumo_nombre: linea.insumo_nombre,
        unidad: linea.unidad, rendimiento: rend,
        nota: "ajuste del proyecto desde la corrida" });
      toast.success("Ajuste aplicado a este proyecto (la biblioteca no cambió).");
      setAbierto(false);
      onCambio();
    } catch (e) {
      toast.error(String(e));
    } finally {
      setEnviando(false);
    }
  }

  return (
    <tr className="border-b">
      <td className="py-1 pr-3 font-mono text-muted-foreground">{linea.insumo_codigo}</td>
      <td className="py-1 pr-3">{linea.insumo_nombre}</td>
      <td className="py-1 pr-3">{linea.unidad}</td>
      <td className="py-1 pr-3 text-right">
        {abierto ? (
          <span className="inline-flex items-center gap-1">
            <Input className="w-20 text-right" inputMode="decimal"
                   aria-label="Rendimiento del proyecto"
                   value={valor} onChange={(e) => setValor(e.target.value)} />
            <Button size="sm" onClick={aplicar} disabled={enviando}>Aplicar</Button>
          </span>
        ) : linea.rendimiento}
      </td>
      <td className="py-1 pr-3 text-right">{linea.precio_unitario}</td>
      <td className="py-1 pr-3 text-right">{linea.costo}</td>
      <td className="py-1 pr-3">
        {puede && !abierto && (
          <Button variant="outline" size="sm" onClick={() => setAbierto(true)}>
            Ajustar
          </Button>
        )}
      </td>
    </tr>
  );
}
```

`DetalleFila` pasa `carpetaId` (viene de `CorridaDetalle`, agregar el campo si no
está en el DTO: `vista_corrida` ya devuelve `meta`, exponer `carpeta_id` ahí) y
`editable={!congelada && puedeEditar}`, y `onCambio` recarga el detalle del ítem
(la misma función que ya usa `confirmar`).

El botón dice **Ajustar** y el toast aclara que el cambio es del proyecto: editar la
biblioteca sigue siendo la acción aparte de la pantalla de APUs.

- [ ] **Step 4: Correr y verificar que pasa**

Run: `cd web && npx vitest run src/components/corrida && npm run build`
Expected: PASS + build OK

- [ ] **Step 5: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.composicion.test.tsx apu_tool/servicio/corridas.py
git commit -m "feat(web): ajustar la composicion de un item con alcance proyecto"
```

---

### Task 18: Documentación y verificación final

**Files:**
- Modify: `CLAUDE.md`
- Test: toda la suite

- [ ] **Step 1: Actualizar `CLAUDE.md`**

En la tabla de `apu_tool/dominio/`:

```
| `transporte.py`          | distancias de acarreo por proyecto + ajustes de composición |
```

En la tabla de `apu_tool/servicio/`:

```
| `transporte.py`        | distancias del proyecto, impacto y clasificación de acarreos |
| `ajustes.py`           | ajustes puntuales de composición por proyecto |
```

En **Datos**, un párrafo nuevo:

```
- **Distancias por proyecto.** Una carpeta de nivel 1 ES un proyecto y puede fijar
  sus distancias de acarreo (`botadero`, `mezclas`, `granulares`), si hay peaje y
  cuánto vale (`proyecto_parametros`), más ajustes puntuales de composición
  (`proyecto_ajuste`). El rendimiento efectivo de un componente de acarreo es
  `volumen × km_del_proyecto`, con el volumen clasificado una vez por componente en
  `componente_transporte` (las filas M3-KM de la biblioteca). Se aplica en
  `PricingEngine.components()`, el único punto de paso; la biblioteca NO se toca y
  cada proyecto costea el mismo APU distinto. Sin parámetros ni ajustes, el costeo
  es idéntico al de siempre. Un componente M3-KM sin clasificar NO se reescala y
  sale con alerta.
```

En **No hacer**:

```
- No metas la distancia de un proyecto dentro de la biblioteca (ni editando el APU
  ni duplicándolo): para eso están `proyecto_parametros` y `proyecto_ajuste`. La
  distancia es del sitio, no del APU.
- No confíes en el código de un insumo de transporte para clasificarlo: 6 de los 9
  códigos tienen homónimo en el catálogo. Siempre código + nombre.
- Ojo: `seed --force` borra `componente_transporte` (igual que las listas NP) y hay
  que reclasificar las filas M3-KM. Los dos backends se comportan igual a propósito:
  el espejo Postgres hace `DROP SCHEMA apus CASCADE`.
```

- [ ] **Step 2: Correr la suite completa de Python**

Run: `python -m pytest tests/ -q`
Expected: PASS, sin fallos ni errores

- [ ] **Step 3: Correr la suite completa del frontend**

Run: `cd web && npx vitest run && npm run build`
Expected: PASS + build OK

- [ ] **Step 4: Verificación manual en el navegador** (obligatoria: es un cambio de UI)

```bash
# Terminal 1
python run_web.py
# Terminal 2 (si el front corre aparte)
cd web && npm run dev
```

Recorrido mínimo:
1. Crear la carpeta «Metro» (nivel 1) y entrar a **Distancias**.
2. Clasificar (pantalla B) las filas M3-KM con el default de 25 km.
3. Poner botadero 34 / mezclas 28 / granulares 32, peaje sí $12.400 y **Guardar**.
4. Abrir una corrida del proyecto: los rendimientos de acarreo cambiaron y los
   totales también; el ítem con un acarreo sin clasificar muestra la alerta.
5. Crear otra carpeta «Calle 13» con granulares 25 y verificar que el **mismo** APU
   cuesta distinto en cada proyecto.
6. Ajustar un rendimiento desde la composición de un ítem y confirmar que la
   biblioteca (pantalla de APUs) NO cambió.
7. Generar el cuadro y abrir la hoja **DESVIACIONES DEL PROYECTO**.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: distancias de transporte y ajustes por proyecto en CLAUDE.md"
```

- [ ] **Step 6: Antes de fusionar**

1. Aplicar `supabase/migrations/0006_transporte_proyecto_rls.sql` en el Supabase real.
2. Correr la suite con `TEST_DATABASE_URL` apuntando a un Postgres **desechable**
   (nunca a producción: esos tests hacen `DROP SCHEMA`).
3. Pedir aprobación explícita antes de empujar a `master` (auto-despliega).

