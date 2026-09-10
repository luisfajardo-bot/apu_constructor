> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-09-10-agente-composicion.md`

# Agente de composición asistida de APUs — plan de implementación (fase 0 + fase 1)

> **Para trabajadores agénticos:** SUB-SKILL OBLIGATORIA: usa
> `superpowers:subagent-driven-development` (recomendada) o
> `superpowers:executing-plans` para implementar este plan tarea por tarea. Los pasos
> usan casillas (`- [ ]`) para seguimiento.

**Objetivo:** convertir la composición generativa de un solo tiro (dos campos, sin
validar, sin persistir, con la confianza que se pone el modelo a sí mismo) en un
expediente auditable: contrato explicable por componente, validador determinístico,
confianza calculada por la plataforma, persistencia append-only en los dos backends y
una mesa de revisión editable con URL propia.

**Arquitectura:** el agente es hermano de `dominio/revision.py`, no un framework. Una
llamada a la IA por generación; todo lo demás es Python determinístico. La IA no ve
dinero (`privacy.safe_json`), no guarda nada (el alta pasa por `servicio/autoria.py`) y
no toca el matcher, el armado ni el motor de precios.

**Stack:** Python 3.14 + FastAPI + SQLite/Postgres · React + TypeScript + Vitest ·
pytest · SDK `anthropic` (opcional).

**Diseño de referencia:** `docs/superpowers/specs/2026-09-10-agente-composicion-design.md`

**Estado previo (medido en `master` `deec22e`, 2026-09-10):**
`python -m pytest tests/ -q` → **1036 pasadas, 15 saltadas, 0 fallos**. No hay nada roto
de antes.

**Rama:** `feat/agente-composicion` desde `master`. **Sin push hasta aprobación
explícita** — `master` autodespliega.

---

## Estructura de archivos

| Archivo | Responsabilidad |
|---|---|
| `apu_tool/dominio/composicion.py` | **nuevo.** Contrato puro: vocabularios cerrados, dataclasses, parseo tolerante del JSON del modelo |
| `apu_tool/dominio/composicion_agente.py` | **nuevo.** Orquestador: `recuperar()`, `evaluar()`, `componer()` |
| `apu_tool/dominio/validacion_composicion.py` | **nuevo.** Validador determinístico + confianza calculada. Sin IA, sin dinero, sin motor de precios |
| `apu_tool/dominio/compose.py` | + `RendimientoObservado` y `rendimientos_observados()` |
| `apu_tool/dominio/privacy.py` | + `payload_composicion()` y sus helpers |
| `apu_tool/dominio/ai_assist.py` | + `ApuAdvisor.componer()`, esquema v2, `PROMPT_VERSION` |
| `apu_tool/dominio/assemble.py` | − `generar_composicion` (se muda al orquestador) |
| `apu_tool/nucleo/models.py` | + `ComposicionRow` |
| `apu_tool/datos/composiciones_db.py` | **nuevo.** Backend SQLite de la tabla `composicion` (vive en `corridas.db`) |
| `apu_tool/datos/pg/composiciones_pg.py` | **nuevo.** Backend Postgres, espejo 1:1 |
| `apu_tool/datos/{repositorio,almacen,apus_db}.py`, `datos/pg/apus_pg.py` | Protocol, wiring, `rendimientos_por_insumo` |
| `db/corridas.sql`, `db/pg/corridas.sql` | tabla `composicion` |
| `apu_tool/servicio/composicion.py` | **nuevo.** Lógica de servicio, hermano de `corridas.py` |
| `apu_tool/servicio/{rutas,esquemas}.py` | 5 endpoints + DTOs |
| `apu_tool/config.py` | + `COMPOSICION_LIMITE_RENDIMIENTO`, `COMPOSICION_MIN_ANTECEDENTES` |
| `web/src/api/composicion.ts`, `web/src/pages/Composicion.tsx` | cliente + mesa de revisión |
| `web/src/components/corrida/TablaItems.tsx` | puerta de entrada nueva (fase 0) |
| `web/src/components/corrida/DialogoComposicion.tsx` | **borrado** |

**Nota de orden:** respecto al §14 del diseño, las tareas 5 y 6 van intercambiadas
(privacidad antes que la fachada de IA). La dependencia real es esa:
`payload_composicion` no necesita el advisor, pero el advisor sí necesita el payload.

---

## Tarea 0: preparar la rama

**Archivos:** ninguno.

- [ ] **Paso 1: crear la rama desde master limpio**

```bash
git checkout master
git status --short          # debe salir vacío salvo los untracked previos
git checkout -b feat/agente-composicion
```

- [ ] **Paso 2: dejar constancia del estado previo**

```bash
python -m pytest tests/ -q 2>&1 | tail -3
```

Esperado: `1036 passed, 15 skipped, 1 warning`. Si sale distinto, **para y avisa**: el
plan asume esta línea base.

---

## Tarea 1: contrato y tipos

Los vocabularios cerrados y las dataclasses del contrato, más el parseo del JSON que
devuelve el modelo. Todo puro: sin base, sin red, sin IA.

**La regla central de esta tarea:** el parseo **nunca descarta un componente en
silencio**. Un campo ilegible se degrada de forma **conservadora** (hacia menos
confianza, nunca hacia más) y el validador lo dice después. Esto arregla el hueco de hoy,
donde `assemble.py:150` tira componentes sin avisar.

**Archivos:**
- Crear: `apu_tool/dominio/composicion.py`
- Test: `tests/test_composicion_contrato.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""Contrato de la composición: vocabularios cerrados y parseo tolerante.

El parseo NUNCA descarta un componente: degrada conservadoramente y deja que el
validador (dominio/validacion_composicion.py) lo diga. Descartar en silencio es el
hueco que esta feature viene a tapar.
"""
import math

from apu_tool.dominio.composicion import (
    FUNCIONES,
    NIVELES_EVIDENCIA,
    ORIGENES,
    Calculo,
    propuesta_desde_json,
)


def _crudo(**extra) -> dict:
    """Un JSON del modelo bien formado, con los campos que se quieran pisar."""
    comp = {"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
            "rendimiento": 0.5, "origen": "copiado_de_antecedente",
            "referencias": [{"apu_codigo": "3010", "turno": "DIURNO"}],
            "hipotesis": {}, "calculo": None, "justificacion": "porque sí",
            "nivel_evidencia": "alto"}
    comp.update(extra)
    return {"componentes": [comp], "supuestos": [], "incertidumbre_declarada": 0.2,
            "justificacion": "global"}


def test_parsea_una_propuesta_bien_formada():
    p = propuesta_desde_json(_crudo())
    assert len(p.componentes) == 1
    c = p.componentes[0]
    assert (c.codigo, c.tipo, c.funcion) == ("4279", "insumo", "mano_de_obra")
    assert c.rendimiento == 0.5
    assert c.referencias[0].apu_codigo == "3010"
    assert p.incertidumbre_declarada == 0.2


def test_funcion_ilegible_no_descarta_el_componente():
    p = propuesta_desde_json(_crudo(funcion="excavacion_y_cargue"))
    assert len(p.componentes) == 1        # NO se tira
    assert p.componentes[0].funcion == ""  # queda vacía; el validador la marca


def test_origen_ilegible_degrada_a_sin_evidencia():
    """Conservador: no reclamar evidencia que no se entendió."""
    p = propuesta_desde_json(_crudo(origen="me_lo_invente"))
    assert p.componentes[0].origen == "sin_evidencia"


def test_nivel_de_evidencia_ilegible_degrada_a_bajo():
    p = propuesta_desde_json(_crudo(nivel_evidencia="altisimo"))
    assert p.componentes[0].nivel_evidencia == "bajo"


def test_rendimiento_no_numerico_queda_nan_y_no_se_descarta():
    p = propuesta_desde_json(_crudo(rendimiento="mucho"))
    assert len(p.componentes) == 1
    assert math.isnan(p.componentes[0].rendimiento)


def test_tipo_ilegible_degrada_a_insumo():
    p = propuesta_desde_json(_crudo(tipo="cosa"))
    assert p.componentes[0].tipo == "insumo"


def test_componente_sin_codigo_no_se_descarta_queda_vacio():
    p = propuesta_desde_json(_crudo(codigo=""))
    assert len(p.componentes) == 1
    assert p.componentes[0].codigo == ""


def test_json_basura_da_propuesta_vacia_no_revienta():
    for basura in ({}, {"componentes": None}, {"componentes": "no"},
                   {"componentes": [42, "x", None]}):
        p = propuesta_desde_json(basura)
        assert p.componentes == ()


def test_calculo_evalua_la_division():
    assert Calculo("division", 8, 96, 0.09).evaluar() == 8 / 96


def test_calculo_con_denominador_cero_es_imposible():
    assert Calculo("division", 8, 0, 1.0).evaluar() is None


def test_calculo_con_valores_no_finitos_es_imposible():
    assert Calculo("division", float("inf"), 96, 1.0).evaluar() is None
    assert Calculo("multiplicacion", float("nan"), 2, 1.0).evaluar() is None


def test_calculo_multiplicacion_y_directo():
    assert Calculo("multiplicacion", 3, 4, 0).evaluar() == 12
    assert Calculo("directo", 0.7, 0, 0).evaluar() == 0.7


def test_vocabularios_son_los_del_diseno():
    assert FUNCIONES == ("mano_de_obra", "equipo", "herramienta", "material",
                         "transporte", "subcontrato", "sub_apu")
    assert ORIGENES == ("copiado_de_antecedente", "ajustado_de_antecedente",
                        "calculado_desde_produccion", "supuesto_tecnico",
                        "sin_evidencia")
    assert NIVELES_EVIDENCIA == ("alto", "medio", "bajo")
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_composicion_contrato.py -q`
Esperado: FALLA con `ModuleNotFoundError: No module named 'apu_tool.dominio.composicion'`

- [ ] **Paso 3: escribir la implementación mínima**

Crea `apu_tool/dominio/composicion.py`:

```python
"""Contrato de la composición asistida y su orquestador.

Hermano de `dominio/revision.py`: la IA propone la ESTRUCTURA de un APU para una
actividad que el matcher determinístico no supo resolver, y lo que sale de acá es una
propuesta que alguien tiene que aprobar. No hay dinero en ningún campo de este módulo,
a propósito: la propuesta persistida se puede reinyectar en un payload futuro sin
volver a filtrarla (ver `dominio/privacy.py`).

REGLA DEL PARSEO: un componente NUNCA se descarta en silencio. Un campo que no se
entiende se degrada de forma CONSERVADORA — hacia menos confianza, nunca hacia más — y
el validador lo dice después. Descartar callado es lo que hacía `assemble.py`
(`if not cands: continue`): la IA proponía ocho insumos, el usuario veía cinco y nadie
explicaba los tres que faltaban.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Any, Optional

# --------------------------------------------------------------- vocabularios
# Cerrados y revalidados en Python aunque el esquema JSON ya los restrinja, por la
# misma razón que `revision.py` revalida `DICTAMENES`: un valor que no entendemos no
# puede colarse como si lo hubiéramos entendido.

# Rol del componente DENTRO del APU, no nombre de actividad. Es lo que permite que el
# validador escriba reglas ("no hay ni mano de obra ni equipo"); un texto libre no se
# puede validar y sería un campo decorativo. El qué-hace-en-esta-actividad va en
# `justificacion`.
FUNCIONES = ("mano_de_obra", "equipo", "herramienta", "material", "transporte",
             "subcontrato", "sub_apu")

ORIGENES = ("copiado_de_antecedente", "ajustado_de_antecedente",
            "calculado_desde_produccion", "supuesto_tecnico", "sin_evidencia")

NIVELES_EVIDENCIA = ("alto", "medio", "bajo")
OPERACIONES = ("division", "multiplicacion", "directo")
TIPOS = ("insumo", "apu")

# Estados PERSISTIDOS. `analizando` y `recuperando_antecedentes` no están porque son
# etapas dentro de una generación (eventos SSE), no filas; `pendiente` es la ausencia
# de fila; `validada` es un campo de la validación, no un estado.
ESTADOS = ("generando", "propuesta", "editada", "aprobada", "rechazada", "error")


# ------------------------------------------------------------------- tipos
@dataclass(frozen=True)
class Referencia:
    """Un antecedente concreto: el APU de la biblioteca del que sale el componente."""
    apu_codigo: str
    turno: str

    def to_dict(self) -> dict[str, Any]:
        return {"apu_codigo": self.apu_codigo, "turno": self.turno}


@dataclass(frozen=True)
class Calculo:
    """La fórmula que el modelo dice haber usado. Python la RECALCULA siempre:
    el número del modelo no se usa cuando hay un cálculo que lo contradice."""
    operacion: str
    numerador: float
    denominador: float
    resultado: float

    def evaluar(self) -> Optional[float]:
        """El resultado según Python, o None si la operación es imposible."""
        a, b = self.numerador, self.denominador
        if not math.isfinite(a) or not math.isfinite(b):
            return None
        if self.operacion == "division":
            return None if b == 0 else a / b
        if self.operacion == "multiplicacion":
            return a * b
        if self.operacion == "directo":
            return a
        return None

    def to_dict(self) -> dict[str, Any]:
        return {"operacion": self.operacion, "numerador": self.numerador,
                "denominador": self.denominador, "resultado": self.resultado}


@dataclass(frozen=True)
class ComponentePropuesto:
    codigo: str
    tipo: str                     # insumo | apu
    funcion: str                  # de FUNCIONES; "" = ilegible (el validador lo marca)
    rendimiento: float            # cantidad por unidad de actividad; NaN = ilegible
    origen: str                   # de ORIGENES
    referencias: tuple[Referencia, ...] = ()
    hipotesis: dict[str, Any] = field(default_factory=dict)
    calculo: Optional[Calculo] = None
    justificacion: str = ""
    nivel_evidencia: str = "bajo"
    ref_shift: str = ""           # turno del sub-APU cuando tipo == "apu"

    def to_dict(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "tipo": self.tipo, "funcion": self.funcion,
                "rendimiento": self.rendimiento, "origen": self.origen,
                "referencias": [r.to_dict() for r in self.referencias],
                "hipotesis": self.hipotesis,
                "calculo": self.calculo.to_dict() if self.calculo else None,
                "justificacion": self.justificacion,
                "nivel_evidencia": self.nivel_evidencia,
                "ref_shift": self.ref_shift}


@dataclass(frozen=True)
class Supuesto:
    campo: str
    supuesto: str
    impacto: str

    def to_dict(self) -> dict[str, Any]:
        return {"campo": self.campo, "supuesto": self.supuesto,
                "impacto": self.impacto}


@dataclass(frozen=True)
class Propuesta:
    componentes: tuple[ComponentePropuesto, ...] = ()
    supuestos: tuple[Supuesto, ...] = ()
    # Lo que el modelo dice de sí mismo. Se GUARDA y se MUESTRA, pero NO entra en el
    # cálculo de la confianza: esa la hace la plataforma con señales observables.
    incertidumbre_declarada: float = 0.0
    justificacion: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"componentes": [c.to_dict() for c in self.componentes],
                "supuestos": [s.to_dict() for s in self.supuestos],
                "incertidumbre_declarada": self.incertidumbre_declarada,
                "justificacion": self.justificacion}


# ------------------------------------------------------------------ parseo
def _texto(v: Any) -> str:
    return "" if v is None else str(v).strip()


def _numero(v: Any) -> float:
    """Un float, o NaN si no se puede. NaN no se descarta: el validador lo rechaza
    con un mensaje que el usuario puede leer."""
    try:
        return float(v)
    except (TypeError, ValueError):
        return float("nan")


def _del_vocabulario(v: Any, vocabulario: tuple[str, ...], por_defecto: str) -> str:
    val = _texto(v).lower()
    return val if val in vocabulario else por_defecto


def _referencias_desde(v: Any) -> tuple[Referencia, ...]:
    out = []
    for r in (v if isinstance(v, list) else []):
        if not isinstance(r, dict):
            continue
        cod = _texto(r.get("apu_codigo"))
        if cod:
            out.append(Referencia(cod, _texto(r.get("turno")).upper()))
    return tuple(out)


def _calculo_desde(v: Any) -> Optional[Calculo]:
    if not isinstance(v, dict):
        return None
    op = _del_vocabulario(v.get("operacion"), OPERACIONES, "")
    if not op:
        return None
    return Calculo(op, _numero(v.get("numerador")), _numero(v.get("denominador")),
                   _numero(v.get("resultado")))


def _componente_desde(v: Any) -> Optional[ComponentePropuesto]:
    if not isinstance(v, dict):
        return None          # no es un componente degradable: no hay nada que leer
    return ComponentePropuesto(
        codigo=_texto(v.get("codigo")),
        tipo=_del_vocabulario(v.get("tipo"), TIPOS, "insumo"),
        # "" y no un valor del vocabulario: inventarle un rol sería una mentira que el
        # validador daría por buena. Vacío es legible y se marca.
        funcion=_del_vocabulario(v.get("funcion"), FUNCIONES, ""),
        rendimiento=_numero(v.get("rendimiento")),
        # Conservador: si no se entiende de dónde sale, no se le reconoce evidencia.
        origen=_del_vocabulario(v.get("origen"), ORIGENES, "sin_evidencia"),
        referencias=_referencias_desde(v.get("referencias")),
        hipotesis=v.get("hipotesis") if isinstance(v.get("hipotesis"), dict) else {},
        calculo=_calculo_desde(v.get("calculo")),
        justificacion=_texto(v.get("justificacion")),
        nivel_evidencia=_del_vocabulario(v.get("nivel_evidencia"),
                                         NIVELES_EVIDENCIA, "bajo"),
        ref_shift=_texto(v.get("ref_shift")).upper(),
    )


def _supuestos_desde(v: Any) -> tuple[Supuesto, ...]:
    out = []
    for s in (v if isinstance(v, list) else []):
        if isinstance(s, dict):
            out.append(Supuesto(_texto(s.get("campo")), _texto(s.get("supuesto")),
                                _texto(s.get("impacto"))))
    return tuple(out)


def propuesta_desde_json(data: Any) -> Propuesta:
    """Lee el JSON del modelo sin confiar en él y sin descartar nada en silencio.

    Un JSON que no es un objeto, o sin `componentes`, da una propuesta VACÍA — que el
    validador rechaza con `PROPUESTA_VACIA`. Nadie sale marcado como válido por
    accidente, que es la misma regla que aplica `revision.py` con los dictámenes.
    """
    if not isinstance(data, dict):
        return Propuesta()
    crudos = data.get("componentes")
    comps = [c for c in (_componente_desde(x)
                         for x in (crudos if isinstance(crudos, list) else []))
             if c is not None]
    inc = _numero(data.get("incertidumbre_declarada"))
    if not math.isfinite(inc):
        inc = 0.0
    return Propuesta(
        componentes=tuple(comps),
        supuestos=_supuestos_desde(data.get("supuestos")),
        incertidumbre_declarada=min(max(inc, 0.0), 1.0),
        justificacion=_texto(data.get("justificacion")),
    )
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

Ejecuta: `python -m pytest tests/test_composicion_contrato.py -q`
Esperado: `13 passed`

- [ ] **Paso 5: commit**

```bash
git add apu_tool/dominio/composicion.py tests/test_composicion_contrato.py
git commit -m "feat(composicion): contrato con vocabularios cerrados y parseo que no descarta"
```

---

## Tarea 2: rendimientos observados en la biblioteca

Para cada insumo candidato, en cuántos APUs de la biblioteca aparece y con qué rango de
rendimiento. Es la evidencia determinística que le da al modelo la base para declarar
"copiado" o "ajustado", y al validador la base para decir "atípico".

El SQL va en la capa `datos`, como manda la convención del repo. Nada de recorrer 1500
APUs en memoria.

**Archivos:**
- Modificar: `apu_tool/datos/apus_db.py`, `apu_tool/datos/pg/apus_pg.py`,
  `apu_tool/datos/repositorio.py`, `apu_tool/dominio/compose.py`, `apu_tool/config.py`
- Test: `tests/test_rendimientos_observados.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""Rendimientos observados: la evidencia determinística de la biblioteca.

Sin esto el validador no tiene contra qué comparar y la confianza no tiene señal.
"""
import pytest

from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.compose import rendimientos_observados
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
    ])
    a.apus.insert_apus([
        Apu("A1", "UNO", "M3", "DIURNO"), Apu("A2", "DOS", "M3", "DIURNO"),
        Apu("A3", "TRES", "M3", "DIURNO"),
    ])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.40, 0),
        ApuComponent("A2", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 0),
        ApuComponent("A3", "DIURNO", "4279", "CUADRILLA", "HR", 1.10, 0),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 0),
    ])
    return a


def test_devuelve_n_minimo_mediana_y_maximo(alm):
    obs = rendimientos_observados(alm, ["4279"])
    r = obs["4279"]
    assert r.n == 3
    assert r.minimo == 0.40
    assert r.mediana == 0.62
    assert r.maximo == 1.10
    assert r.unidad == "HR"


def test_un_insumo_sin_uso_no_aparece(alm):
    assert "9999" not in rendimientos_observados(alm, ["9999"])


def test_ignora_rendimientos_no_positivos(alm):
    """Un 0 en la biblioteca es un dato roto, no un antecedente."""
    alm.apus.insert_apus([Apu("A4", "CUATRO", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A4", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 0.0, 0)])
    assert rendimientos_observados(alm, ["6092"])["6092"].n == 1


def test_mediana_con_n_par(alm):
    alm.apus.insert_apus([Apu("A5", "CINCO", "M3", "DIURNO")])
    alm.apus.insert_components([
        ApuComponent("A5", "DIURNO", "4279", "CUADRILLA", "HR", 0.80, 0)])
    # 0.40, 0.62, 0.80, 1.10 -> (0.62+0.80)/2
    assert rendimientos_observados(alm, ["4279"])["4279"].mediana == pytest.approx(0.71)


def test_sin_codigos_no_consulta_nada(alm):
    assert rendimientos_observados(alm, []) == {}


def test_umbral_minimo_de_antecedentes_existe():
    assert config.COMPOSICION_MIN_ANTECEDENTES == 3
    assert config.COMPOSICION_LIMITE_RENDIMIENTO > 0


def test_a_la_ia_no_le_llega_dinero_en_esto(alm):
    """El tipo no tiene campos monetarios y el guardián lo confirma."""
    from apu_tool.dominio import privacy
    obs = rendimientos_observados(alm, ["4279"])
    privacy.assert_no_money([r.to_dict() for r in obs.values()])
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_rendimientos_observados.py -q`
Esperado: FALLA con `ImportError: cannot import name 'rendimientos_observados'`

- [ ] **Paso 3a: agregar los umbrales a `config.py`**

En `apu_tool/config.py`, justo después del bloque `CRUCE_UMBRAL` / `CRUCE_MARGEN`:

```python
# Umbrales de la composición asistida (dominio/validacion_composicion.py).
# Techo absurdo por componente: atrapa un rendimiento con la coma corrida (0,5 -> 500)
# sin bloquear un consumo grande legítimo (arena en m3 por m3 de mampostería).
COMPOSICION_LIMITE_RENDIMIENTO = 10_000.0
# Antecedentes mínimos para llamar "atípico" a un rendimiento. Con n=1 o n=2 el "rango"
# no significa nada y la advertencia sería ruido: por debajo se informa que no hay con
# qué comparar, que es un dato distinto y útil.
COMPOSICION_MIN_ANTECEDENTES = 3
```

- [ ] **Paso 3b: agregar el método al repo SQLite**

En `apu_tool/datos/apus_db.py`, junto a `get_components_bulk`:

```python
    def rendimientos_por_insumo(self, codigos) -> dict[str, list[tuple[str, float]]]:
        """Para cada código de insumo, los (unidad, rendimiento) con que aparece en la
        biblioteca. Es la materia prima de `dominio/compose.rendimientos_observados`.

        Una sola consulta: recorrer los APUs en memoria para esto sería leer la
        biblioteca entera por cada composición.
        """
        codes = [c for c in dict.fromkeys(str(x) for x in codigos if x)]
        out: dict[str, list[tuple[str, float]]] = {}
        if not codes:
            return out
        with self.connect() as conn:
            for i in range(0, len(codes), 800):     # límite de placeholders de SQLite
                chunk = codes[i:i + 800]
                ph = ",".join("?" * len(chunk))
                rows = conn.execute(
                    f"SELECT insumo_codigo, unidad, rendimiento FROM apu_componentes "
                    f"WHERE insumo_codigo IN ({ph}) AND tipo = 'insumo'", chunk
                ).fetchall()
                for r in rows:
                    out.setdefault(r["insumo_codigo"], []).append(
                        (r["unidad"] or "", float(r["rendimiento"] or 0.0)))
        return out
```

- [ ] **Paso 3c: agregar el espejo Postgres**

En `apu_tool/datos/pg/apus_pg.py`, junto a `get_components_bulk`:

```python
    def rendimientos_por_insumo(self, codigos) -> dict[str, list[tuple[str, float]]]:
        """Espejo Postgres de ApusDB.rendimientos_por_insumo. Sin trocear: psycopg
        manda la lista como un solo parámetro (= ANY), no como N placeholders."""
        codes = [c for c in dict.fromkeys(str(x) for x in codigos if x)]
        out: dict[str, list[tuple[str, float]]] = {}
        if not codes:
            return out
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT insumo_codigo, unidad, rendimiento FROM apus.apu_componentes "
                "WHERE insumo_codigo = ANY(%s) AND tipo = 'insumo'", (codes,)
            ).fetchall()
        for r in rows:
            out.setdefault(r["insumo_codigo"], []).append(
                (r["unidad"] or "", float(r["rendimiento"] or 0.0)))
        return out
```

- [ ] **Paso 3d: declararlo en el Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioApus`, junto a
`get_components_bulk`:

```python
    def rendimientos_por_insumo(self, codigos: Iterable[str]
                                ) -> dict[str, list[tuple[str, float]]]:
        """(unidad, rendimiento) con que cada insumo aparece en la biblioteca."""
        ...
```

- [ ] **Paso 3e: agregar el tipo y la función a `compose.py`**

Al final de `apu_tool/dominio/compose.py`:

```python
@dataclass(frozen=True)
class RendimientoObservado:
    """Cómo se usa un insumo en la biblioteca. SIN dinero: son cantidades físicas."""
    insumo_codigo: str
    unidad: str
    n: int
    minimo: float
    mediana: float
    maximo: float

    def to_dict(self) -> dict:
        return {"insumo_codigo": self.insumo_codigo, "unidad": self.unidad,
                "n": self.n, "minimo": round(self.minimo, 6),
                "mediana": round(self.mediana, 6), "maximo": round(self.maximo, 6)}


def _mediana(xs: list[float]) -> float:
    ord_ = sorted(xs)
    m = len(ord_) // 2
    return ord_[m] if len(ord_) % 2 else (ord_[m - 1] + ord_[m]) / 2


def rendimientos_observados(almacen: Almacen, codigos) -> dict[str, RendimientoObservado]:
    """Estadística no monetaria de cada insumo en la biblioteca.

    Le da al modelo con qué declarar "copiado" o "ajustado", y al validador con qué
    llamar atípico a un rendimiento. Un insumo que no se usa en ningún APU no aparece:
    la ausencia es el dato (`SIN_ANTECEDENTES`), no un rango de ceros.
    """
    crudo = almacen.apus.rendimientos_por_insumo(codigos)
    out: dict[str, RendimientoObservado] = {}
    for cod, pares in crudo.items():
        # Un rendimiento <= 0 en la biblioteca es un dato roto, no un antecedente.
        vals = [r for _u, r in pares if r > 0]
        if not vals:
            continue
        unidades = [u for u, r in pares if r > 0 and u]
        out[cod] = RendimientoObservado(
            insumo_codigo=cod, unidad=(unidades[0] if unidades else ""),
            n=len(vals), minimo=min(vals), mediana=_mediana(vals), maximo=max(vals))
    return out
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_rendimientos_observados.py -q
python -m pytest tests/test_repositorios_contrato.py tests/test_compose.py -q
```

Esperado: `7 passed` en la primera; las otras dos siguen verdes.

- [ ] **Paso 5: commit**

```bash
git add apu_tool/config.py apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py \
        apu_tool/datos/repositorio.py apu_tool/dominio/compose.py \
        tests/test_rendimientos_observados.py
git commit -m "feat(composicion): rendimientos observados de la biblioteca, en una consulta"
```

---

## Tarea 3: el validador determinístico

El corazón de la feature. Sin IA, sin dinero, sin motor de precios. Recalcula la
aritmética del modelo y aplica las reglas, separando **lo estructural** (bloquea) de
**lo contextual** (advierte, porque ahí un ingeniero puede tener razón contra la regla).

**Archivos:**
- Crear: `apu_tool/dominio/validacion_composicion.py`
- Test: `tests/test_validacion_composicion.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""El validador determinístico: qué bloquea, qué advierte y qué recalcula.

Regla del reparto: bloquea lo ESTRUCTURAL (el código no existe, la cantidad no es un
número, el sub-APU cicla) y advierte lo CONTEXTUAL (rendimiento raro, falta
herramienta, el método no cuadra). Convertir criterio de ingeniería discutible en
bloqueo absoluto es lo que el diseño prohíbe.
"""
import pytest

from apu_tool import config
from apu_tool.dominio.composicion import (
    Calculo, ComponentePropuesto, Propuesta, Referencia, Supuesto,
)
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.validacion_composicion import ContextoValidacion, validar


def comp(**kw) -> ComponentePropuesto:
    base = dict(codigo="4279", tipo="insumo", funcion="mano_de_obra",
                rendimiento=0.62, origen="copiado_de_antecedente",
                referencias=(Referencia("A1", "DIURNO"),), hipotesis={},
                calculo=None, justificacion="j", nivel_evidencia="alto",
                ref_shift="")
    base.update(kw)
    return ComponentePropuesto(**base)


def ctx(**kw) -> ContextoValidacion:
    base = dict(
        descripcion="EXCAVACION MANUAL EN MATERIAL COMUN", unidad_actividad="M3",
        shift="DIURNO",
        codigos_permitidos=frozenset({"4279", "6092", "322"}),
        unidades_catalogo={"4279": "HR", "6092": "GLB", "322": "M3"},
        apus_existentes=frozenset({("A1", "DIURNO"), ("SUB", "DIURNO")}),
        componentes_de_apu={("SUB", "DIURNO"): ()},
        observados={"4279": RendimientoObservado("4279", "HR", 14, 0.40, 0.62, 1.10)},
        apu_codigo_propio="", supuestos_confirmados=False)
    base.update(kw)
    return ContextoValidacion(**base)


def codigos(hallazgos) -> set[str]:
    return {h.codigo for h in hallazgos}


# --- casos limpios ---------------------------------------------------------
def test_una_propuesta_sana_es_valida():
    p = Propuesta(componentes=(comp(), comp(codigo="6092", funcion="herramienta",
                                            rendimiento=1.0)))
    _, v = validar(p, ctx())
    assert v.valido is True
    assert v.errores == ()
    assert v.totales > 0 and v.superadas <= v.totales


# --- bloqueantes -----------------------------------------------------------
def test_propuesta_vacia_es_error():
    _, v = validar(Propuesta(), ctx())
    assert v.valido is False
    assert "PROPUESTA_VACIA" in codigos(v.errores)


def test_codigo_fuera_de_la_lista_blanca_es_error():
    _, v = validar(Propuesta(componentes=(comp(codigo="9999"),)), ctx())
    assert "CODIGO_NO_AUTORIZADO" in codigos(v.errores)
    assert v.valido is False


def test_codigo_autorizado_pero_ausente_del_catalogo_es_error():
    c = ctx(codigos_permitidos=frozenset({"4279", "7777"}))
    _, v = validar(Propuesta(componentes=(comp(codigo="7777"),)), c)
    assert "CODIGO_INEXISTENTE" in codigos(v.errores)


@pytest.mark.parametrize("valor", [0.0, -1.0, float("nan"), float("inf")])
def test_cantidades_no_positivas_o_no_finitas_son_error(valor):
    _, v = validar(Propuesta(componentes=(comp(rendimiento=valor),)), ctx())
    assert "CANTIDAD_INVALIDA" in codigos(v.errores)


def test_cantidad_por_encima_del_techo_es_error():
    absurdo = config.COMPOSICION_LIMITE_RENDIMIENTO + 1
    _, v = validar(Propuesta(componentes=(comp(rendimiento=absurdo),)), ctx())
    assert "CANTIDAD_INVALIDA" in codigos(v.errores)


def test_componente_duplicado_es_error():
    _, v = validar(Propuesta(componentes=(comp(), comp())), ctx())
    assert "COMPONENTE_DUPLICADO" in codigos(v.errores)


def test_mismo_codigo_como_insumo_y_como_subapu_no_es_duplicado():
    """La clave es (codigo, tipo, ref_shift): son dos cosas distintas."""
    p = Propuesta(componentes=(
        comp(codigo="SUB", tipo="apu", funcion="sub_apu", ref_shift="DIURNO"),
        comp(codigo="SUB", tipo="insumo")))
    c = ctx(codigos_permitidos=frozenset({"SUB"}), unidades_catalogo={"SUB": "UN"})
    _, v = validar(p, c)
    assert "COMPONENTE_DUPLICADO" not in codigos(v.errores)


def test_subapu_inexistente_es_error():
    p = Propuesta(componentes=(comp(codigo="NOEXISTE", tipo="apu", funcion="sub_apu",
                                    ref_shift="DIURNO"),))
    _, v = validar(p, ctx(codigos_permitidos=frozenset({"NOEXISTE"})))
    assert "SUBAPU_INEXISTENTE" in codigos(v.errores)


def test_subapu_en_otro_turno_del_que_existe_es_error():
    p = Propuesta(componentes=(comp(codigo="SUB", tipo="apu", funcion="sub_apu",
                                    ref_shift="NOCTURNO"),))
    _, v = validar(p, ctx(codigos_permitidos=frozenset({"SUB"})))
    assert "SUBAPU_INEXISTENTE" in codigos(v.errores)


def test_subapu_que_contiene_al_apu_que_se_esta_creando_es_ciclo():
    """Solo detectable al aprobar, cuando el código propio ya se eligió."""
    p = Propuesta(componentes=(comp(codigo="SUB", tipo="apu", funcion="sub_apu",
                                    ref_shift="DIURNO"),))
    c = ctx(codigos_permitidos=frozenset({"SUB"}),
            componentes_de_apu={("SUB", "DIURNO"): (("YO", "apu", "DIURNO"),)},
            apu_codigo_propio="YO")
    _, v = validar(p, c)
    assert "SUBAPU_CICLO" in codigos(v.errores)


def test_calculo_con_denominador_cero_es_error():
    p = Propuesta(componentes=(comp(calculo=Calculo("division", 8, 0, 1.0)),))
    _, v = validar(p, ctx())
    assert "CALCULO_IMPOSIBLE" in codigos(v.errores)


# --- recálculo -------------------------------------------------------------
def test_python_manda_sobre_la_aritmetica_del_modelo():
    """El modelo dice 8/96 = 0,09. Python escribe 0,0833... y lo advierte."""
    p = Propuesta(componentes=(comp(rendimiento=0.09,
                                    calculo=Calculo("division", 8, 96, 0.09)),))
    corregida, v = validar(p, ctx())
    assert corregida.componentes[0].rendimiento == pytest.approx(8 / 96)
    assert "CALCULO_CORREGIDO" in codigos(v.advertencias)
    assert v.valido is True          # se corrige, no se rechaza


def test_un_redondeo_razonable_no_se_marca_como_corregido():
    p = Propuesta(componentes=(comp(rendimiento=0.083333,
                                    calculo=Calculo("division", 8, 96, 0.083333)),))
    _, v = validar(p, ctx())
    assert "CALCULO_CORREGIDO" not in codigos(v.advertencias)


def test_sin_calculo_el_rendimiento_del_modelo_se_respeta():
    corregida, _ = validar(Propuesta(componentes=(comp(rendimiento=0.62),)), ctx())
    assert corregida.componentes[0].rendimiento == 0.62


# --- advertencias ----------------------------------------------------------
def test_rendimiento_fuera_del_rango_observado_advierte():
    _, v = validar(Propuesta(componentes=(comp(rendimiento=5.0),)), ctx())
    assert "RENDIMIENTO_ATIPICO" in codigos(v.advertencias)
    assert v.valido is True          # advierte, no bloquea


def test_con_pocos_antecedentes_no_se_llama_atipico_a_nada():
    pocos = {"4279": RendimientoObservado("4279", "HR", 2, 0.40, 0.50, 0.60)}
    _, v = validar(Propuesta(componentes=(comp(rendimiento=5.0),)),
                   ctx(observados=pocos))
    assert "RENDIMIENTO_ATIPICO" not in codigos(v.advertencias)
    assert "SIN_ANTECEDENTES" in codigos(v.advertencias)


def test_origen_sin_evidencia_advierte():
    _, v = validar(Propuesta(componentes=(comp(origen="sin_evidencia",
                                               referencias=()),)), ctx())
    assert "SIN_EVIDENCIA" in codigos(v.advertencias)


def test_origen_que_exige_antecedente_sin_referencias_advierte():
    _, v = validar(Propuesta(componentes=(comp(origen="copiado_de_antecedente",
                                               referencias=()),)), ctx())
    assert "SIN_EVIDENCIA" in codigos(v.advertencias)


def test_referencia_a_un_apu_que_no_existe_se_limpia_y_advierte():
    p = Propuesta(componentes=(comp(referencias=(Referencia("FANTASMA", "DIURNO"),
                                                 Referencia("A1", "DIURNO"))),))
    corregida, v = validar(p, ctx())
    assert [r.apu_codigo for r in corregida.componentes[0].referencias] == ["A1"]
    assert "REFERENCIA_INEXISTENTE" in codigos(v.advertencias)


def test_funcion_ilegible_advierte():
    _, v = validar(Propuesta(componentes=(comp(funcion=""),)), ctx())
    assert "FUNCION_ILEGIBLE" in codigos(v.advertencias)


def test_sin_mano_de_obra_ni_equipo_advierte():
    p = Propuesta(componentes=(comp(codigo="322", funcion="material",
                                    rendimiento=1.0),))
    _, v = validar(p, ctx())
    assert "FALTA_MANO_DE_OBRA" in codigos(v.advertencias)


def test_mano_de_obra_sin_herramienta_ni_equipo_advierte():
    _, v = validar(Propuesta(componentes=(comp(),)), ctx())
    assert "FALTA_HERRAMIENTA" in codigos(v.advertencias)


def test_actividad_manual_con_equipo_pesado_advierte():
    p = Propuesta(componentes=(comp(), comp(codigo="6092", funcion="equipo",
                                            rendimiento=1.0)))
    _, v = validar(p, ctx(descripcion="EXCAVACION MANUAL EN MATERIAL COMUN"))
    assert "METODO_INCOHERENTE" in codigos(v.advertencias)


def test_actividad_mecanica_sin_equipo_advierte():
    p = Propuesta(componentes=(comp(), comp(codigo="6092", funcion="herramienta",
                                            rendimiento=1.0)))
    _, v = validar(p, ctx(descripcion="EXCAVACION MECANICA CON RETROEXCAVADORA"))
    assert "METODO_INCOHERENTE" in codigos(v.advertencias)


def test_supuesto_sin_confirmar_advierte():
    p = Propuesta(componentes=(comp(),),
                  supuestos=(Supuesto("profundidad_m", "< 1,5 m", "cambia el equipo"),))
    _, v = validar(p, ctx(supuestos_confirmados=False))
    assert "SUPUESTO_SIN_CONFIRMAR" in codigos(v.advertencias)


def test_supuesto_confirmado_no_advierte():
    p = Propuesta(componentes=(comp(),),
                  supuestos=(Supuesto("profundidad_m", "< 1,5 m", "cambia el equipo"),))
    _, v = validar(p, ctx(supuestos_confirmados=True))
    assert "SUPUESTO_SIN_CONFIRMAR" not in codigos(v.advertencias)


# --- forma del resultado ---------------------------------------------------
def test_las_metricas_cuentan_reglas_no_componentes():
    _, v = validar(Propuesta(componentes=(comp(),)), ctx())
    d = v.to_dict()
    assert set(d) == {"valido", "errores", "advertencias", "metricas"}
    assert (d["metricas"]["superadas"] + len(d["errores"]) + len(d["advertencias"])
            == d["metricas"]["totales"])


def test_cada_hallazgo_apunta_a_su_componente():
    _, v = validar(Propuesta(componentes=(comp(codigo="9999"),)), ctx())
    err = next(h for h in v.errores if h.codigo == "CODIGO_NO_AUTORIZADO")
    assert err.componente == "9999"
    assert err.mensaje


def test_la_validacion_no_lleva_dinero():
    from apu_tool.dominio import privacy
    _, v = validar(Propuesta(componentes=(comp(),)), ctx())
    privacy.assert_no_money(v.to_dict())
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_validacion_composicion.py -q`
Esperado: FALLA con `ModuleNotFoundError: No module named 'apu_tool.dominio.validacion_composicion'`

- [ ] **Paso 3: escribir la implementación**

Crea `apu_tool/dominio/validacion_composicion.py`:

```python
"""Validación determinística de una propuesta de composición.

Sin IA, sin dinero, sin motor de precios. Recibe la propuesta que devolvió el modelo y
un contexto que salió todo de la base, y devuelve la propuesta CORREGIDA más la lista
de hallazgos.

El reparto entre error y advertencia sigue una regla, no el gusto:

  - Bloquea lo ESTRUCTURAL: el código no está autorizado, no existe, la cantidad no es
    un número usable, el sub-APU no existe o cierra un ciclo, la fórmula es imposible.
    Con cualquiera de estas la propuesta no describe algo que el sistema pueda costear.
  - Advierte lo CONTEXTUAL: el rendimiento es raro, falta herramienta, el método no
    cuadra con la descripción. Acá un ingeniero puede tener razón contra la regla, y
    convertir criterio discutible en bloqueo absoluto es lo que el diseño prohíbe.

`validar` CORRIGE dos cosas y lo dice: la aritmética (Python manda sobre el número del
modelo cuando hay un `calculo` que lo contradice) y las referencias muertas (se
limpian). Tirar una propuesta buena por una división mal hecha que sabemos arreglar
sería el peor de los dos comportamientos.
"""
from __future__ import annotations

import math
from dataclasses import dataclass, replace
from typing import Any

from apu_tool import config
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.composicion import ComponentePropuesto, Propuesta

# Orígenes que AFIRMAN venir de un antecedente: sin referencia viva, la afirmación no
# se sostiene y se advierte.
_ORIGENES_CON_ANTECEDENTE = ("copiado_de_antecedente", "ajustado_de_antecedente")

# Tolerancia relativa del recálculo. El modelo redondea a 6 decimales; 8/96 devuelto
# como 0,083333 no es un error, 0,09 sí. 1e-4 separa las dos cosas con holgura.
_TOLERANCIA_RELATIVA = 1e-4

# ponytail: detección de método por palabra clave sobre la descripción cruda. Es tosca
# —por eso es ADVERTENCIA y no error— y se reemplaza en la fase 3, cuando la ficha
# técnica traiga el método en un campo propio en vez de adivinarlo del texto.
_PALABRAS_MANUAL = ("MANUAL", "A MANO")
_PALABRAS_MECANICO = ("MECANIC", "MECÁNIC", "RETRO", "EXCAVADORA", "MOTONIVELADORA",
                      "VIBROCOMPACTADOR")


@dataclass(frozen=True)
class Hallazgo:
    codigo: str                 # vocabulario estable, para que la interfaz lo mapee
    mensaje: str                # en español, para leer
    componente: str = ""        # código del componente; "" = hallazgo global

    def to_dict(self) -> dict[str, Any]:
        return {"codigo": self.codigo, "mensaje": self.mensaje,
                "componente": self.componente}


@dataclass(frozen=True)
class Validacion:
    valido: bool
    errores: tuple[Hallazgo, ...]
    advertencias: tuple[Hallazgo, ...]
    superadas: int
    totales: int

    def to_dict(self) -> dict[str, Any]:
        return {"valido": self.valido,
                "errores": [h.to_dict() for h in self.errores],
                "advertencias": [h.to_dict() for h in self.advertencias],
                "metricas": {"superadas": self.superadas, "totales": self.totales}}


@dataclass(frozen=True)
class ContextoValidacion:
    """Todo lo que hace falta para validar, y todo salió de la base.

    `componentes_de_apu` mapea (codigo, turno) -> tuplas (codigo, tipo, ref_shift) de
    sus componentes. Es lo único que necesita el recorrido de ciclos, y viene
    precargado para no consultar la base dentro del validador, que es puro a propósito.
    """
    descripcion: str
    unidad_actividad: str
    shift: str
    codigos_permitidos: frozenset[str]
    unidades_catalogo: dict[str, str]
    apus_existentes: frozenset[tuple[str, str]]
    componentes_de_apu: dict[tuple[str, str], tuple[tuple[str, str, str], ...]]
    observados: dict[str, RendimientoObservado]
    # Código del APU que se está creando. Vacío durante la generación (todavía no se
    # eligió) y con valor al aprobar: recién ahí un ciclo es detectable.
    apu_codigo_propio: str = ""
    supuestos_confirmados: bool = False


# --------------------------------------------------------------- recálculo
def _recalcular(c: ComponentePropuesto) -> tuple[ComponentePropuesto, list[Hallazgo]]:
    """Python manda sobre la aritmética."""
    if c.calculo is None:
        return c, []
    resultado = c.calculo.evaluar()
    if resultado is None:
        return c, [Hallazgo(
            "CALCULO_IMPOSIBLE",
            f"La fórmula declarada ({c.calculo.operacion}) no se puede evaluar: "
            f"numerador {c.calculo.numerador}, denominador {c.calculo.denominador}.",
            c.codigo)]
    dicho = c.rendimiento
    if math.isfinite(dicho) and abs(dicho - resultado) <= max(
            1e-9, _TOLERANCIA_RELATIVA * abs(resultado)):
        return c, []
    return replace(c, rendimiento=resultado), [Hallazgo(
        "CALCULO_CORREGIDO",
        f"El modelo declaró {dicho:g} pero su propia fórmula da {resultado:g}. "
        f"Se usa {resultado:g}.", c.codigo)]


def _limpiar_referencias(c: ComponentePropuesto, ctx: ContextoValidacion
                         ) -> tuple[ComponentePropuesto, list[Hallazgo]]:
    """Una referencia a un APU que ya no existe no respalda nada: se quita."""
    vivas, muertas = [], []
    for r in c.referencias:
        turno = (r.turno or ctx.shift).upper()
        (vivas if (r.apu_codigo, turno) in ctx.apus_existentes else muertas).append(r)
    if not muertas:
        return c, []
    nombres = ", ".join(r.apu_codigo for r in muertas)
    return replace(c, referencias=tuple(vivas)), [Hallazgo(
        "REFERENCIA_INEXISTENTE",
        f"El APU de referencia {nombres} ya no está en la biblioteca; se descarta "
        f"como respaldo.", c.codigo)]


# ----------------------------------------------------------------- ciclos
def _cierra_ciclo(codigo: str, turno: str, propio: str,
                  arbol: dict[tuple[str, str], tuple[tuple[str, str, str], ...]]
                  ) -> bool:
    """El árbol de este sub-APU, ¿vuelve al APU que estamos creando?"""
    if not propio:
        return False        # sin código propio no hay ciclo posible todavía
    pendientes = [(codigo, turno)]
    vistos: set[tuple[str, str]] = set()
    while pendientes:
        clave = pendientes.pop()
        if clave in vistos:
            continue
        vistos.add(clave)
        if clave[0] == propio:
            return True
        for hijo, tipo, ref in arbol.get(clave, ()):
            if tipo == "apu":
                pendientes.append((hijo, (ref or clave[1]).upper()))
    return False


# ------------------------------------------------------- reglas por componente
def _validar_componente(c: ComponentePropuesto, ctx: ContextoValidacion
                        ) -> tuple[list[Hallazgo], list[Hallazgo], int]:
    """(errores, advertencias, reglas_evaluadas) de UN componente."""
    err: list[Hallazgo] = []
    adv: list[Hallazgo] = []
    reglas = 0

    reglas += 1
    if c.codigo not in ctx.codigos_permitidos:
        err.append(Hallazgo("CODIGO_NO_AUTORIZADO",
                            f"El código {c.codigo or '(vacío)'} no estaba entre los "
                            f"candidatos que se le dieron a la IA.", c.codigo))
    elif c.tipo == "apu":
        reglas += 1
        turno = (c.ref_shift or ctx.shift).upper()
        if (c.codigo, turno) not in ctx.apus_existentes:
            err.append(Hallazgo("SUBAPU_INEXISTENTE",
                                f"El sub-APU {c.codigo} no existe en turno {turno}.",
                                c.codigo))
        else:
            reglas += 1
            if _cierra_ciclo(c.codigo, turno, ctx.apu_codigo_propio,
                             ctx.componentes_de_apu):
                err.append(Hallazgo("SUBAPU_CICLO",
                                    f"El sub-APU {c.codigo} contiene al APU que se "
                                    f"está creando: sería un ciclo.", c.codigo))
    else:
        reglas += 1
        if c.codigo not in ctx.unidades_catalogo:
            err.append(Hallazgo("CODIGO_INEXISTENTE",
                                f"El insumo {c.codigo} no está en el catálogo.",
                                c.codigo))

    reglas += 1
    r = c.rendimiento
    if not math.isfinite(r) or r <= 0 or r > config.COMPOSICION_LIMITE_RENDIMIENTO:
        err.append(Hallazgo("CANTIDAD_INVALIDA",
                            f"El rendimiento de {c.codigo} ({r}) tiene que ser un "
                            f"número mayor que 0 y menor que "
                            f"{config.COMPOSICION_LIMITE_RENDIMIENTO:g}.", c.codigo))

    reglas += 1
    if not c.funcion:
        adv.append(Hallazgo("FUNCION_ILEGIBLE",
                            f"No se entendió qué función cumple {c.codigo} en la "
                            f"actividad; revisala antes de aprobar.", c.codigo))

    reglas += 1
    if c.origen == "sin_evidencia" or (
            c.origen in _ORIGENES_CON_ANTECEDENTE and not c.referencias):
        adv.append(Hallazgo("SIN_EVIDENCIA",
                            f"{c.codigo} no tiene un antecedente que lo respalde.",
                            c.codigo))

    reglas += 1
    obs = ctx.observados.get(c.codigo)
    if obs is None or obs.n < config.COMPOSICION_MIN_ANTECEDENTES:
        adv.append(Hallazgo("SIN_ANTECEDENTES",
                            f"{c.codigo} aparece en {0 if obs is None else obs.n} APUs "
                            f"de la biblioteca: no hay rango contra el cual comparar "
                            f"su rendimiento.", c.codigo))
    elif math.isfinite(r) and not (obs.minimo <= r <= obs.maximo):
        ref = obs.minimo if r < obs.minimo else obs.maximo
        pct = abs(r - ref) / ref * 100 if ref else 0.0
        lado = "por debajo" if r < obs.minimo else "por encima"
        adv.append(Hallazgo("RENDIMIENTO_ATIPICO",
                            f"{r:g} {obs.unidad} queda {pct:.0f} % {lado} del rango "
                            f"observado ({obs.minimo:g}-{obs.maximo:g} {obs.unidad}, "
                            f"n={obs.n}).", c.codigo))

    return err, adv, reglas


# ------------------------------------------------------- reglas del conjunto
def _validar_conjunto(p: Propuesta, ctx: ContextoValidacion
                      ) -> tuple[list[Hallazgo], list[Hallazgo], int]:
    err: list[Hallazgo] = []
    adv: list[Hallazgo] = []
    reglas = 0
    comps = p.componentes
    funciones = {c.funcion for c in comps}

    reglas += 1
    claves = [(c.codigo, c.tipo, c.ref_shift) for c in comps]
    for k in sorted({k for k in claves if claves.count(k) > 1}):
        err.append(Hallazgo("COMPONENTE_DUPLICADO",
                            f"{k[0]} aparece más de una vez en la composición.", k[0]))

    reglas += 1
    if not ({"mano_de_obra", "equipo"} & funciones):
        adv.append(Hallazgo("FALTA_MANO_DE_OBRA",
                            "La composición no tiene ni mano de obra ni equipo: "
                            "revisá si la actividad es solo de suministro."))

    reglas += 1
    if "mano_de_obra" in funciones and not ({"herramienta", "equipo"} & funciones):
        adv.append(Hallazgo("FALTA_HERRAMIENTA",
                            "Hay cuadrilla pero ni herramienta ni equipo."))

    reglas += 1
    desc = (ctx.descripcion or "").upper()
    if any(x in desc for x in _PALABRAS_MANUAL) and "equipo" in funciones:
        adv.append(Hallazgo("METODO_INCOHERENTE",
                            "La actividad dice MANUAL y la composición trae equipo."))
    elif any(x in desc for x in _PALABRAS_MECANICO) and "equipo" not in funciones:
        adv.append(Hallazgo("METODO_INCOHERENTE",
                            "La actividad dice mecánica y la composición no trae "
                            "equipo."))

    reglas += 1
    if p.supuestos and not ctx.supuestos_confirmados:
        adv.append(Hallazgo("SUPUESTO_SIN_CONFIRMAR",
                            f"Hay {len(p.supuestos)} supuesto(s) que nadie confirmó."))

    return err, adv, reglas


# --------------------------------------------------------------------- api
def validar(p: Propuesta, ctx: ContextoValidacion) -> tuple[Propuesta, Validacion]:
    """Devuelve la propuesta CORREGIDA y su validación.

    Corrige dos cosas y lo dice: la aritmética y las referencias muertas. Todo lo
    demás se reporta, no se toca — arreglarlo es del humano en la mesa de revisión.
    """
    if not p.componentes:
        return p, Validacion(
            valido=False,
            errores=(Hallazgo("PROPUESTA_VACIA",
                              "La IA no propuso ningún componente."),),
            advertencias=(), superadas=0, totales=1)

    corregidos: list[ComponentePropuesto] = []
    errores: list[Hallazgo] = []
    advertencias: list[Hallazgo] = []
    reglas = 0

    for c in p.componentes:
        c, h1 = _recalcular(c)
        c, h2 = _limpiar_referencias(c, ctx)
        reglas += 2
        for h in h1 + h2:
            (errores if h.codigo == "CALCULO_IMPOSIBLE" else advertencias).append(h)
        e, a, n = _validar_componente(c, ctx)
        errores += e
        advertencias += a
        reglas += n
        corregidos.append(c)

    nueva = replace(p, componentes=tuple(corregidos))
    e, a, n = _validar_conjunto(nueva, ctx)
    errores += e
    advertencias += a
    reglas += n

    return nueva, Validacion(
        valido=not errores, errores=tuple(errores), advertencias=tuple(advertencias),
        superadas=reglas - len(errores) - len(advertencias), totales=reglas)
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

Ejecuta: `python -m pytest tests/test_validacion_composicion.py -q`
Esperado: `31 passed`

- [ ] **Paso 5: commit**

```bash
git add apu_tool/dominio/validacion_composicion.py tests/test_validacion_composicion.py
git commit -m "feat(composicion): validador deterministico; Python manda sobre la aritmetica"
```

---

## Tarea 4: la confianza calculada por la plataforma

Cuatro niveles explicables, no un porcentaje. Lo que el modelo dice de sí mismo se
guarda y se muestra, pero **no entra en la fórmula**: ese es el criterio 27.

**Archivos:**
- Modificar: `apu_tool/dominio/validacion_composicion.py`
- Test: `tests/test_confianza_composicion.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""La confianza la calcula la plataforma, no el modelo.

Cuatro niveles explicables (alta/media/baja/insuficiente) a partir de señales
observables, con el desglose guardado para que el usuario vea por qué.
"""
from apu_tool.dominio.composicion import (
    ComponentePropuesto, Propuesta, Referencia, Supuesto,
)
from apu_tool.dominio.compose import RendimientoObservado
from apu_tool.dominio.validacion_composicion import (
    NIVELES_CONFIANZA, ContextoValidacion, calcular_confianza, validar,
)


def comp(**kw) -> ComponentePropuesto:
    base = dict(codigo="4279", tipo="insumo", funcion="mano_de_obra",
                rendimiento=0.62, origen="copiado_de_antecedente",
                referencias=(Referencia("A1", "DIURNO"),), hipotesis={},
                calculo=None, justificacion="j", nivel_evidencia="alto",
                ref_shift="")
    base.update(kw)
    return ComponentePropuesto(**base)


def ctx(**kw) -> ContextoValidacion:
    base = dict(
        descripcion="EXCAVACION EN MATERIAL COMUN", unidad_actividad="M3",
        shift="DIURNO",
        codigos_permitidos=frozenset({"4279", "6092", "322"}),
        unidades_catalogo={"4279": "HR", "6092": "GLB", "322": "M3"},
        apus_existentes=frozenset({("A1", "DIURNO")}),
        componentes_de_apu={},
        observados={
            "4279": RendimientoObservado("4279", "HR", 14, 0.55, 0.62, 0.70),
            "6092": RendimientoObservado("6092", "GLB", 20, 1.0, 1.0, 1.0),
        },
        unidades_de_apu={("A1", "DIURNO"): "M3"},
        apu_codigo_propio="", supuestos_confirmados=False)
    base.update(kw)
    return ContextoValidacion(**base)


def _nivel(p: Propuesta, c: ContextoValidacion) -> str:
    corregida, v = validar(p, c)
    return calcular_confianza(corregida, v, c).nivel


SANA = Propuesta(componentes=(comp(),
                              comp(codigo="6092", funcion="herramienta",
                                   rendimiento=1.0)))


def test_el_vocabulario_es_el_del_diseno():
    assert NIVELES_CONFIANZA == ("alta", "media", "baja", "insuficiente")


def test_una_propuesta_bien_respaldada_da_alta():
    assert _nivel(SANA, ctx()) == "alta"


def test_con_un_error_bloqueante_siempre_es_insuficiente():
    """Sin excepción: si no se puede aprobar, no hay confianza que reportar."""
    rota = Propuesta(componentes=(comp(codigo="9999"),))
    assert _nivel(rota, ctx()) == "insuficiente"


def test_sin_evidencia_en_todos_los_componentes_baja_el_nivel():
    floja = Propuesta(componentes=(
        comp(origen="sin_evidencia", referencias=()),
        comp(codigo="6092", funcion="herramienta", rendimiento=1.0,
             origen="sin_evidencia", referencias=())))
    assert _nivel(floja, ctx()) in ("baja", "media")
    assert _nivel(floja, ctx()) != "alta"


def test_la_incertidumbre_del_modelo_no_mueve_el_nivel():
    """Criterio 27: dos propuestas idénticas con incertidumbre 0,0 y 1,0 dan lo mismo."""
    segura = Propuesta(componentes=SANA.componentes, incertidumbre_declarada=0.0)
    insegura = Propuesta(componentes=SANA.componentes, incertidumbre_declarada=1.0)
    assert _nivel(segura, ctx()) == _nivel(insegura, ctx())


def test_los_supuestos_sin_confirmar_restan():
    con = Propuesta(componentes=SANA.componentes,
                    supuestos=(Supuesto("prof", "<1,5 m", "cambia el equipo"),))
    corregida, v = validar(con, ctx())
    conf = calcular_confianza(corregida, v, ctx())
    assert any(m.senal == "supuestos_sin_confirmar" and m.aporte < 0
               for m in conf.motivos)


def test_un_rendimiento_atipico_resta():
    rara = Propuesta(componentes=(comp(rendimiento=5.0),
                                  comp(codigo="6092", funcion="herramienta",
                                       rendimiento=1.0)))
    corregida, v = validar(rara, ctx())
    conf = calcular_confianza(corregida, v, ctx())
    assert any(m.senal == "rendimientos_atipicos" and m.aporte < 0
               for m in conf.motivos)


def test_el_desglose_explica_el_nivel():
    corregida, v = validar(SANA, ctx())
    conf = calcular_confianza(corregida, v, ctx())
    assert conf.motivos                       # nunca vacío
    assert sum(m.aporte for m in conf.motivos) == conf.puntos
    for m in conf.motivos:
        assert m.senal and m.detalle          # todo motivo se puede leer


def test_la_senal_de_unidad_ve_la_unidad_del_antecedente():
    igual = calcular_confianza(*validar(SANA, ctx()), ctx())
    distinta = calcular_confianza(
        *validar(SANA, ctx(unidades_de_apu={("A1", "DIURNO"): "ML"})),
        ctx(unidades_de_apu={("A1", "DIURNO"): "ML"}))
    aporte = lambda c: next(m.aporte for m in c.motivos
                            if m.senal == "unidad_de_antecedentes")
    assert aporte(igual) > aporte(distinta)


def test_la_confianza_no_lleva_dinero():
    from apu_tool.dominio import privacy
    conf = calcular_confianza(*validar(SANA, ctx()), ctx())
    privacy.assert_no_money(conf.to_dict())


def test_el_nivel_siempre_es_del_vocabulario():
    for p in (Propuesta(), SANA, Propuesta(componentes=(comp(codigo="9999"),))):
        corregida, v = validar(p, ctx())
        assert calcular_confianza(corregida, v, ctx()).nivel in NIVELES_CONFIANZA
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_confianza_composicion.py -q`
Esperado: FALLA con `ImportError: cannot import name 'NIVELES_CONFIANZA'`

- [ ] **Paso 3a: agregar el campo `unidades_de_apu` al contexto**

En `apu_tool/dominio/validacion_composicion.py`, dentro de `ContextoValidacion`, después
de `observados` y **antes** de `apu_codigo_propio` no: va al final, con valor por
defecto, para no romper a quien ya construye el contexto sin él:

```python
    # Unidad de cada APU de la biblioteca, (codigo, turno) -> unidad. La usa la señal
    # `unidad_de_antecedentes` de la confianza: un antecedente que mide en ML no
    # respalda una actividad que se paga por M3, por parecido que sea el nombre.
    unidades_de_apu: dict[tuple[str, str], str] = field(default_factory=dict)
```

Y agrega `field` al import de `dataclasses`:

```python
from dataclasses import dataclass, field, replace
```

- [ ] **Paso 3b: agregar la confianza al mismo módulo**

Al final de `apu_tool/dominio/validacion_composicion.py`:

```python
# ------------------------------------------------------------------ confianza
# Cuatro niveles y no un porcentaje: no hay masa de datos para sostener una escala
# continua, y pintar "73 %" es la falsa precisión que esta feature vino a quitar. Lo
# que sí hay es un desglose: el usuario puede ver de dónde salió el nivel.
NIVELES_CONFIANZA = ("alta", "media", "baja", "insuficiente")

_UMBRAL_ALTA = 4
_UMBRAL_MEDIA = 2

# Un rango observado tan ancho como (max-min)/mediana <= 0,5 es un consenso; por encima
# de 2,0 la biblioteca no se pone de acuerdo y el antecedente respalda menos.
_DISPERSION_ESTRECHA = 0.5
_DISPERSION_ANCHA = 2.0


@dataclass(frozen=True)
class Motivo:
    senal: str
    # `detalle` y no `valor`: "valor" está en `_FORBIDDEN_KEYS` (por valor_unitario y
    # valor_total) y `assert_no_money` mira NOMBRES de clave, no contenido. Con la
    # clave "valor" el guardián reventaba sobre un desglose que no lleva un peso.
    detalle: str        # legible: "4 de 5 con antecedente vivo"
    aporte: int

    def to_dict(self) -> dict[str, Any]:
        return {"senal": self.senal, "detalle": self.detalle, "aporte": self.aporte}


@dataclass(frozen=True)
class Confianza:
    nivel: str
    puntos: int
    motivos: tuple[Motivo, ...]

    def to_dict(self) -> dict[str, Any]:
        return {"nivel": self.nivel, "puntos": self.puntos,
                "motivos": [m.to_dict() for m in self.motivos]}


def _dispersion(obs: RendimientoObservado) -> float:
    return (obs.maximo - obs.minimo) / obs.mediana if obs.mediana else 0.0


def calcular_confianza(p: Propuesta, v: Validacion,
                       ctx: ContextoValidacion) -> Confianza:
    """El nivel de confianza, calculado FUERA del modelo.

    `p.incertidumbre_declarada` no se lee acá a propósito: es lo que el modelo dice de
    sí mismo, se guarda y se muestra aparte, y no puede mover un indicador que existe
    justamente para no depender de él. Hay un test que lo fija.

    Con cualquier error bloqueante el nivel es `insuficiente` sin mirar nada más: una
    propuesta que no se puede aprobar no tiene confianza que reportar.
    """
    if v.errores:
        return Confianza("insuficiente", 0, (Motivo(
            "errores_bloqueantes", f"{len(v.errores)} error(es) que impiden aprobar",
            0),))

    comps = p.componentes
    n = len(comps)
    motivos: list[Motivo] = []

    # Respaldado = el validador NO le puso SIN_EVIDENCIA. Se lee de los hallazgos en
    # vez de recalcular la regla acá: cuando esto parcheaba la constante por su cuenta
    # (`_ORIGENES_CON_ANTECEDENTE + ("calculado_desde_produccion",)`), el validador y
    # la confianza decían cosas distintas del mismo componente.
    sin_respaldo = {h.componente for h in v.advertencias if h.codigo == "SIN_EVIDENCIA"}
    respaldados = sum(1 for c in comps if c.codigo not in sin_respaldo)
    frac = respaldados / n if n else 0.0
    aporte = 2 if frac >= 0.8 else (1 if frac >= 0.5 else 0)
    motivos.append(Motivo("respaldo_de_componentes",
                          f"{respaldados} de {n} con antecedente vivo", aporte))

    refs = {(r.apu_codigo, (r.turno or ctx.shift).upper())
            for c in comps for r in c.referencias}
    unidad = (ctx.unidad_actividad or "").strip().upper()
    iguales = sum(1 for k in refs
                  if (ctx.unidades_de_apu.get(k, "") or "").strip().upper() == unidad)
    motivos.append(Motivo("unidad_de_antecedentes",
                          f"{iguales} de {len(refs)} comparten {unidad or '(sin unidad)'}",
                          1 if iguales else 0))

    con_masa = sum(1 for c in comps
                   if (o := ctx.observados.get(c.codigo)) is not None
                   and o.n >= config.COMPOSICION_MIN_ANTECEDENTES)
    motivos.append(Motivo("antecedentes_comparables",
                          f"{con_masa} de {n} con al menos "
                          f"{config.COMPOSICION_MIN_ANTECEDENTES} usos en la biblioteca",
                          1 if con_masa >= max(1, n // 2) else 0))

    usados = [o for c in comps if (o := ctx.observados.get(c.codigo)) is not None]
    if usados:
        media = sum(_dispersion(o) for o in usados) / len(usados)
        disp = (1 if media <= _DISPERSION_ESTRECHA
                else (-1 if media > _DISPERSION_ANCHA else 0))
        motivos.append(Motivo("dispersion_de_rendimientos",
                              f"amplitud media {media:.2f} veces la mediana", disp))

    atipicos = sum(1 for h in v.advertencias if h.codigo == "RENDIMIENTO_ATIPICO")
    if atipicos:
        motivos.append(Motivo("rendimientos_atipicos", str(atipicos), -atipicos))

    sin_ev = sum(1 for h in v.advertencias if h.codigo == "SIN_EVIDENCIA")
    if sin_ev:
        motivos.append(Motivo("componentes_sin_evidencia", str(sin_ev), -sin_ev))

    supuestos = len(p.supuestos) if not ctx.supuestos_confirmados else 0
    if supuestos:
        motivos.append(Motivo("supuestos_sin_confirmar", str(supuestos), -supuestos))

    motivos.append(Motivo("validaciones",
                          f"{v.superadas} de {v.totales} superadas",
                          1 if not v.advertencias else 0))

    puntos = sum(m.aporte for m in motivos)
    nivel = ("alta" if puntos >= _UMBRAL_ALTA
             else "media" if puntos >= _UMBRAL_MEDIA else "baja")
    return Confianza(nivel, puntos, tuple(motivos))
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_confianza_composicion.py tests/test_validacion_composicion.py -q
```

Esperado: `42 passed` (11 de confianza + 31 de validación).

- [ ] **Paso 5: commit**

```bash
git add apu_tool/dominio/validacion_composicion.py tests/test_confianza_composicion.py
git commit -m "feat(composicion): confianza calculada por la plataforma, con su desglose"
```

---

## Tarea 5: la frontera de privacidad del agente

El payload hacia la IA y la batería que intenta filtrar dinero por cada rendija nueva.
Va **antes** que la fachada de IA porque el advisor lo necesita, no al revés.

**Archivos:**
- Modificar: `apu_tool/dominio/privacy.py`, `apu_tool/dominio/compose.py`
- Test: `tests/test_composicion_privacidad.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""Invariante #1 en la superficie nueva: la IA nunca ve dinero.

Se prueba por forma (qué claves lleva el payload) y por guardián (que `assert_no_money`
reviente si algo monetario se cuela). Las dos cosas: la forma atrapa un campo agregado
sin pensar, el guardián atrapa uno con nombre monetario.
"""
import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.compose import CandidateInsumo, RendimientoObservado
from apu_tool.nucleo.models import (
    DePricedApu, DePricedComponent, LicitacionItem,
)

ITEM = LicitacionItem(item="1.3", descripcion="EXCAVACION MANUAL", unidad="M3",
                      cantidad=120.0, precio_contractual=180000.0, shift="DIURNO")
INSUMOS = [CandidateInsumo("4279", "CUADRILLA", "HR", "MO")]
EJEMPLOS = [DePricedApu("A1", "UNO", "M3", "DIURNO", "EXCAVACIONES",
                        (DePricedComponent("4279", "CUADRILLA", "HR", 0.62),))]
OBS = {"4279": RendimientoObservado("4279", "HR", 14, 0.40, 0.62, 1.10)}


def test_el_payload_pasa_el_guardian():
    privacy.assert_no_money(privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS))


def test_el_payload_lleva_exactamente_estas_claves():
    """Test de forma: un campo agregado sin pensar rompe acá antes que en producción."""
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert set(p) == {"actividad", "insumos_disponibles", "apus_referencia",
                      "rendimientos_observados"}
    assert set(p["actividad"]) == {"item", "descripcion", "unidad", "cantidad",
                                   "shift"}
    assert set(p["insumos_disponibles"][0]) == {"insumo_codigo", "insumo_nombre",
                                                "unidad", "grupo"}
    assert set(p["rendimientos_observados"][0]) == {"insumo_codigo", "unidad", "n",
                                                    "minimo", "mediana", "maximo",
                                                    "descartados_otra_unidad"}


def test_el_precio_contractual_de_la_actividad_no_viaja():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert "precio_contractual" not in p["actividad"]
    assert 180000.0 not in p["actividad"].values()


def test_los_apus_de_referencia_no_llevan_precio_historico():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    comp = p["apus_referencia"][0]["componentes"][0]
    assert "precio_unitario_hist" not in comp
    assert "precio" not in comp


def test_un_precio_colado_en_el_payload_revienta():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    p["insumos_disponibles"][0]["precio"] = 40000
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money(p)


@pytest.mark.parametrize("clave", ["precio", "costo", "costo_unitario", "valor_total",
                                   "margen", "total", "amount", "fuente_precio",
                                   "costo_manual", "plan_json"])
def test_cada_nombre_monetario_revienta_donde_sea(clave):
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS)
    p["apus_referencia"][0]["componentes"][0][clave] = 1
    with pytest.raises(privacy.PrivacyViolation):
        privacy.assert_no_money(p)


def test_safe_json_es_el_unico_camino_de_salida():
    texto = privacy.safe_json(privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, OBS))
    assert "180000" not in texto
    assert "EXCAVACION MANUAL" in texto


def test_el_payload_sin_antecedentes_sigue_siendo_valido():
    p = privacy.payload_composicion(ITEM, INSUMOS, EJEMPLOS, {})
    assert p["rendimientos_observados"] == []
    privacy.assert_no_money(p)


def test_candidate_insumo_lleva_grupo_y_nada_mas():
    from dataclasses import fields
    assert {f.name for f in fields(CandidateInsumo)} == {"codigo", "nombre", "unidad",
                                                         "grupo"}
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_composicion_privacidad.py -q`
Esperado: FALLA con `AttributeError: module 'apu_tool.dominio.privacy' has no attribute 'payload_composicion'`

- [ ] **Paso 3a: agregar `grupo` a `CandidateInsumo`**

En `apu_tool/dominio/compose.py`, reemplaza la dataclass y su serializador:

```python
@dataclass(frozen=True)
class CandidateInsumo:
    """Insumo candidato SIN dinero (código, nombre, unidad, grupo).

    `grupo` es clasificación técnica (MO/EQ/MAT), no monetaria, y lo llena el
    orquestador con la misma consulta al catálogo con la que arma
    `unidades_catalogo` para el validador: una lectura, dos usos. Por defecto vacío
    para que el retriever siga construyendo candidatos sin consultar nada.
    """
    codigo: str
    nombre: str
    unidad: str
    grupo: str = ""


def candidate_insumo_to_dict(c: CandidateInsumo) -> dict:
    return {"insumo_codigo": c.codigo, "insumo_nombre": c.nombre,
            "unidad": c.unidad, "grupo": c.grupo}
```

- [ ] **Paso 3b: agregar el payload a `privacy.py`**

Al final de `apu_tool/dominio/privacy.py`, **antes** de la clase `PrivacyViolation`:

```python
def rendimiento_observado_to_dict(o) -> dict[str, Any]:
    """Estadística de uso de un insumo en la biblioteca. Cantidades físicas, no dinero.

    Se copia clave por clave y no se delega en `o.to_dict()`: este es el borde hacia
    la IA, y un campo agregado al tipo del dominio no debe viajar solo por existir.
    """
    return {"insumo_codigo": o.insumo_codigo, "unidad": o.unidad, "n": o.n,
            "minimo": round(o.minimo, 6), "mediana": round(o.mediana, 6),
            "maximo": round(o.maximo, 6),
            # El modelo tiene que saber que el rango dejó filas afuera: si no, un
            # "n=35" sobre un insumo que también se usa en otra unidad le parece
            # evidencia más firme de la que es.
            "descartados_otra_unidad": o.descartados_otra_unidad}


def payload_composicion(item, insumos, ejemplos, observados) -> dict[str, Any]:
    """El payload de la composición asistida (dominio/composicion.py).

    Se arma clave por clave a propósito, nunca volcando objetos en bloque: es lo que
    hace que el test de FORMA sirva de algo. Los APUs de referencia entran como
    `DePricedApu`, un tipo que estructuralmente no puede llevar dinero — la frontera
    está en el tipo, no en acordarse de filtrar campos.

    `observados` es un dict {codigo: RendimientoObservado}; se ordena por código para
    que dos llamadas con los mismos datos produzcan el mismo texto (el prompt es
    cacheable y los tests, comparables).
    """
    from apu_tool.dominio.compose import candidate_insumo_to_dict
    return {
        "actividad": licitacion_item_to_dict(item),
        "insumos_disponibles": [candidate_insumo_to_dict(i) for i in insumos],
        "apus_referencia": [depriced_apu_to_dict(a) for a in ejemplos],
        "rendimientos_observados": [rendimiento_observado_to_dict(observados[k])
                                    for k in sorted(observados)],
    }
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_composicion_privacidad.py tests/test_privacy.py tests/test_compose.py -q
```

Esperado: `9 passed` en la primera; `test_privacy.py` y `test_compose.py` siguen verdes.

- [ ] **Paso 5: commit**

```bash
git add apu_tool/dominio/privacy.py apu_tool/dominio/compose.py \
        tests/test_composicion_privacidad.py
git commit -m "feat(privacidad): payload de la composicion, por forma y por guardian"
```

---

## Tarea 6: la fachada de IA

`ApuAdvisor.componer` con el esquema v2. Se **agrega** junto a `compose_apu`; el viejo
muere en la tarea 9, con `generar_composicion`, para que ninguna tarea intermedia deje
el árbol rojo.

**Archivos:**
- Modificar: `apu_tool/dominio/ai_assist.py`
- Test: `tests/test_composicion_advisor.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""La fachada de IA de la composición: una llamada, contrato v2, degradado explícito.

No se llama a la API real: se sustituye `_pedir_al_sdk`, la ÚNICA puerta al SDK, con el
mismo truco que usan los tests de `revision.py`.
"""
import json
from types import SimpleNamespace

import pytest

from apu_tool.dominio import privacy
from apu_tool.dominio.ai_assist import (
    PROMPT_VERSION, ApuAdvisor, IANoDisponible,
)
from apu_tool.dominio.compose import CandidateInsumo, RendimientoObservado
from apu_tool.nucleo.models import DePricedApu, DePricedComponent, LicitacionItem

ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL", "M3", 120.0, 180000.0, "DIURNO")
INSUMOS = [CandidateInsumo("4279", "CUADRILLA", "HR", "MO")]
EJEMPLOS = [DePricedApu("A1", "UNO", "M3", "DIURNO", "EXCAVACIONES",
                        (DePricedComponent("4279", "CUADRILLA", "HR", 0.62),))]
OBS = {"4279": RendimientoObservado("4279", "HR", 14, 0.40, 0.62, 1.10)}

BUENA = {"componentes": [{"codigo": "4279", "tipo": "insumo",
                          "funcion": "mano_de_obra", "rendimiento": 0.62,
                          "origen": "copiado_de_antecedente",
                          "referencias": [{"apu_codigo": "A1", "turno": "DIURNO"}],
                          "hipotesis": {}, "calculo": None, "justificacion": "j",
                          "nivel_evidencia": "alto"}],
         "supuestos": [], "incertidumbre_declarada": 0.3, "justificacion": "g"}


class AdvisorFalso(ApuAdvisor):
    """Sustituye la única puerta al SDK. `texto` es lo que 'devuelve' el modelo."""

    def __init__(self, texto: str):
        self.enabled = True
        self._client = object()
        self.model = "falso"
        self.texto = texto
        self.contenido_enviado = None

    def _pedir_al_sdk(self, system, schema, contenido, effort):
        self.contenido_enviado = contenido
        return SimpleNamespace(
            content=[SimpleNamespace(type="text", text=self.texto)])


def test_devuelve_una_propuesta_parseada():
    a = AdvisorFalso(json.dumps(BUENA))
    p = a.componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert len(p.componentes) == 1
    assert p.componentes[0].codigo == "4279"
    assert p.incertidumbre_declarada == 0.3


def test_no_le_manda_el_precio_contractual_al_modelo():
    a = AdvisorFalso(json.dumps(BUENA))
    a.componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert "180000" not in a.contenido_enviado


def test_revienta_antes_de_tocar_la_red_si_hay_dinero():
    """La PrivacyViolation NO se traga: sale del try, como en revision.Revisor._pedir."""
    a = AdvisorFalso(json.dumps(BUENA))
    sucio = [CandidateInsumo("4279", "CUADRILLA", "HR", "MO")]

    def payload_sucio(*_a, **_k):
        return {"actividad": {"precio_contractual": 1}}

    original = privacy.payload_composicion
    privacy.payload_composicion = payload_sucio
    try:
        with pytest.raises(privacy.PrivacyViolation):
            a.componer(ITEM, sucio, EJEMPLOS, OBS)
    finally:
        privacy.payload_composicion = original
    assert a.contenido_enviado is None      # nunca llegó al SDK


@pytest.mark.parametrize("texto", ["", "no soy json", "{", "[1,2]", '"ok"', "42",
                                   "{}", '{"componentes": []}'])
def test_una_respuesta_ilegible_o_vacia_da_propuesta_vacia_no_revienta(texto):
    p = AdvisorFalso(texto).componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert p.componentes == ()


def test_sin_credencial_levanta_ia_no_disponible():
    a = ApuAdvisor(enabled=False)
    with pytest.raises(IANoDisponible):
        a.componer(ITEM, INSUMOS, EJEMPLOS, OBS)


def test_sin_insumos_candidatos_levanta_valueerror():
    """No hay lista blanca: pedirle algo al modelo sería invitarlo a inventar."""
    with pytest.raises(ValueError):
        AdvisorFalso(json.dumps(BUENA)).componer(ITEM, [], EJEMPLOS, OBS)


def test_la_version_del_prompt_esta_declarada():
    assert PROMPT_VERSION.startswith("composicion/")


def test_un_401_del_sdk_se_convierte_en_ia_no_disponible():
    class Rota(AdvisorFalso):
        def _pedir_al_sdk(self, *a, **k):
            raise type("E", (Exception,), {"status_code": 401})()

    with pytest.raises(IANoDisponible):
        Rota("").componer(ITEM, INSUMOS, EJEMPLOS, OBS)


def test_un_429_del_sdk_no_se_confunde_con_falta_de_credencial():
    class Lenta(AdvisorFalso):
        def _pedir_al_sdk(self, *a, **k):
            raise type("E", (Exception,), {"status_code": 429})()

    with pytest.raises(RuntimeError) as exc:
        Lenta("").componer(ITEM, INSUMOS, EJEMPLOS, OBS)
    assert not isinstance(exc.value, IANoDisponible)
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_composicion_advisor.py -q`
Esperado: FALLA con `ImportError: cannot import name 'PROMPT_VERSION'`

- [ ] **Paso 3: agregar el esquema v2, el prompt y `componer`**

En `apu_tool/dominio/ai_assist.py`, después de `_COMPOSE_SCHEMA`:

```python
# Versión del prompt de composición. Se guarda con cada propuesta: sin esto, cuando el
# modelo empiece a proponer distinto no hay forma de saber si cambió el modelo o el
# prompt. Se sube A MANO al tocar `_SISTEMA_COMPOSICION` o `_ESQUEMA_COMPOSICION`.
PROMPT_VERSION = "composicion/v2"

_SISTEMA_COMPOSICION = """\
Eres un ingeniero de costos de obra civil. Te dan una ACTIVIDAD de licitación que no
tiene un APU adecuado en la biblioteca histórica, una lista cerrada de INSUMOS
DISPONIBLES (código, nombre, unidad, grupo), APUs DE REFERENCIA técnicamente cercanos
con su composición, y RENDIMIENTOS OBSERVADOS: con qué cantidades aparece cada insumo
en la biblioteca.

Tu tarea: proponer la composición del APU y EXPLICAR cada componente.

Reglas estrictas:
- Usa ÚNICAMENTE códigos de la lista de insumos disponibles. Un código que no esté ahí
  se rechaza entero: no inventes ninguno.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Los rendimientos son cantidades FÍSICAS por unidad de la actividad.
- Cuando derives un rendimiento de una hipótesis de producción, escribe la fórmula en
  `calculo`. Un programa la recalcula y manda su resultado sobre el tuyo, así que no te
  esfuerces en la aritmética: esfuérzate en la hipótesis.
- `funcion` es el ROL del insumo dentro del APU, del vocabulario cerrado. No es el
  nombre de la actividad; eso va en `justificacion`.
- `origen` dice de dónde sale el rendimiento. Sé honesto: si no tienes antecedente,
  `sin_evidencia` es la respuesta correcta y no te penaliza.
- `referencias` solo puede citar APUs que estén en los de referencia que te dimos.
- Si algún dato que falta cambiaría materialmente la composición, decláralo en
  `supuestos` en vez de inventarlo en silencio.
- Incluye típicamente mano de obra o equipo, herramienta y materiales según la
  actividad. Entre 2 y 12 componentes.

Responde EXCLUSIVAMENTE con un JSON válido con el esquema pedido.
"""

_ESQUEMA_COMPOSICION = {
    "type": "object",
    "properties": {
        "componentes": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "codigo": {"type": "string"},
                    "tipo": {"type": "string", "enum": ["insumo", "apu"]},
                    "funcion": {"type": "string", "enum": list(FUNCIONES)},
                    "rendimiento": {"type": "number"},
                    "origen": {"type": "string", "enum": list(ORIGENES)},
                    "referencias": {
                        "type": "array",
                        "items": {
                            "type": "object",
                            "properties": {"apu_codigo": {"type": "string"},
                                           "turno": {"type": "string"}},
                            "required": ["apu_codigo", "turno"],
                            "additionalProperties": False,
                        },
                    },
                    "hipotesis": {"type": "object", "additionalProperties": True},
                    "calculo": {
                        "type": ["object", "null"],
                        "properties": {
                            "operacion": {"type": "string",
                                          "enum": list(OPERACIONES)},
                            "numerador": {"type": "number"},
                            "denominador": {"type": "number"},
                            "resultado": {"type": "number"},
                        },
                        "required": ["operacion", "numerador", "denominador",
                                     "resultado"],
                        "additionalProperties": False,
                    },
                    "justificacion": {"type": "string"},
                    "nivel_evidencia": {"type": "string",
                                        "enum": list(NIVELES_EVIDENCIA)},
                },
                "required": ["codigo", "tipo", "funcion", "rendimiento", "origen",
                             "referencias", "hipotesis", "calculo", "justificacion",
                             "nivel_evidencia"],
                "additionalProperties": False,
            },
        },
        "supuestos": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {"campo": {"type": "string"},
                               "supuesto": {"type": "string"},
                               "impacto": {"type": "string"}},
                "required": ["campo", "supuesto", "impacto"],
                "additionalProperties": False,
            },
        },
        "incertidumbre_declarada": {"type": "number", "minimum": 0, "maximum": 1},
        "justificacion": {"type": "string"},
    },
    "required": ["componentes", "supuestos", "incertidumbre_declarada",
                 "justificacion"],
    "additionalProperties": False,
}
```

Y arriba, con los imports:

```python
from apu_tool.dominio.composicion import (
    FUNCIONES, NIVELES_EVIDENCIA, OPERACIONES, ORIGENES, Propuesta,
    propuesta_desde_json,
)
```

Dentro de `ApuAdvisor`, después de `compose_apu`:

```python
    def componer(self, item, insumos, ejemplos, observados) -> Propuesta:
        """Una llamada al modelo con el contrato v2. Devuelve la propuesta PARSEADA.

        No valida nada: eso es de `dominio/validacion_composicion.py`, que además
        recalcula la aritmética. Acá solo se habla con el modelo y se lee lo que dijo.

        Una respuesta ilegible da una propuesta VACÍA, que el validador rechaza con
        `PROPUESTA_VACIA`. Nadie sale por válido por accidente — misma regla que
        `revision.Revisor.profundizar`, que degrada a "dudoso".
        """
        if not self.enabled or self._client is None:
            raise IANoDisponible(
                "Componer un APU con IA necesita ANTHROPIC_API_KEY en el servidor.")
        if not insumos:
            # Sin lista blanca no hay nada entre lo que elegir: pedírselo igual sería
            # invitarlo a inventar códigos, que es lo único que el contrato prohíbe.
            raise ValueError("No hay insumos candidatos para esta actividad.")
        payload = privacy.payload_composicion(item, insumos, ejemplos, observados)
        # FUERA del try: el invariante #1 nunca se traga. Adentro, una PrivacyViolation
        # saldría por el `except` de abajo y el usuario leería "la IA no pudo componer"
        # mientras nadie se entera de que saltó el guardián. Mismo criterio que
        # `compose_apu` y que `revision.barrer_lote`.
        contenido = privacy.safe_json(payload)
        try:
            resp = self._pedir_al_sdk(_SISTEMA_COMPOSICION, _ESQUEMA_COMPOSICION,
                                      contenido, "medium")
        except Exception as exc:
            if credencial_invalida(exc):
                raise IANoDisponible(MSG_CREDENCIAL) from exc
            raise
        texto = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            data = json.loads(texto)
        except Exception:
            return Propuesta()   # JSON truncado: propuesta vacía, no una mentira
        return propuesta_desde_json(data)

    def _pedir_al_sdk(self, system: str, schema: dict, contenido: str, effort: str):
        """La llamada pelada al SDK. Aparte para que el `try` de arriba envuelva SOLO
        la red y no el parseo, y para que los tests la sustituyan sin simular el
        cliente de anthropic — el mismo patrón que `revision.Revisor`."""
        return self._client.messages.create(
            model=self.model,
            max_tokens=16000,        # techo, no gasto: cubre el pensamiento y el JSON
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": contenido}],
        )
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_composicion_advisor.py tests/test_compose.py -q
```

Esperado: `17 passed` en la primera; `test_compose.py` sigue verde.

- [ ] **Paso 5: commit**

```bash
git add apu_tool/dominio/ai_assist.py tests/test_composicion_advisor.py
git commit -m "feat(composicion): fachada de IA con el contrato v2 y version de prompt"
```

---

## Tarea 7: persistencia SQLite

Una tabla, append-only por versión, dentro de `corridas.db`. Repo propio, igual que
`carpetas_db.py`: la separación es por dominio, no por archivo de base.

**La versión es explícita, no calculada dentro del INSERT.** Si el repo hiciera
`MAX(version)+1`, dos clics seguidos obtendrían 4 y 5 y los dos entrarían: el índice
único no protegería nada. Con la versión que manda el llamador (`version_base + 1`), el
segundo choca contra `ux_composicion_version` y el servicio devuelve 409.

**Archivos:**
- Crear: `apu_tool/datos/composiciones_db.py`
- Modificar: `apu_tool/nucleo/models.py`, `db/corridas.sql`,
  `apu_tool/datos/repositorio.py`, `apu_tool/datos/almacen.py`
- Test: `tests/test_composiciones_db.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""Persistencia de la composición: append-only por versión, en los dos backends.

Este archivo prueba SQLite. La paridad con Postgres la fija
`tests/test_composiciones_paridad.py` (tarea 8) con los mismos casos.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.datos.repositorio import VersionYaExiste
from apu_tool.nucleo.models import ComposicionRow


def fila(**kw) -> ComposicionRow:
    base = dict(
        id=None, corrida_id=1, seq=7, version=1, estado="propuesta",
        actividad={"item": "1.3", "descripcion": "EXCAVACION", "unidad": "M3",
                   "cantidad": 120.0, "shift": "DIURNO"},
        ficha=None,
        propuesta={"componentes": [{"codigo": "4279", "rendimiento": 0.62}],
                   "supuestos": [], "incertidumbre_declarada": 0.3,
                   "justificacion": "g"},
        validacion={"valido": True, "errores": [], "advertencias": [],
                    "metricas": {"superadas": 9, "totales": 9}},
        confianza="alta",
        confianza_motivos=[{"senal": "respaldo_de_componentes", "detalle": "1 de 1",
                            "aporte": 2}],
        antecedentes={"codigos_permitidos": ["4279"], "apus_referencia": ["A1"]},
        modelo="claude-sonnet-5", prompt_version="composicion/v2",
        apu_codigo=None, apu_turno=None, autor="luis@test.co",
        creada_en="2026-09-10T10:00:00", motivo=None)
    base.update(kw)
    return ComposicionRow(**base)


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.init_schema()
    return a


def test_guarda_y_recupera_la_vigente(alm):
    alm.composiciones.agregar(fila())
    v = alm.composiciones.vigente(1, 7)
    assert v is not None
    assert v.version == 1
    assert v.estado == "propuesta"
    assert v.propuesta["componentes"][0]["codigo"] == "4279"
    assert v.confianza == "alta"
    assert v.modelo == "claude-sonnet-5"
    assert v.prompt_version == "composicion/v2"


def test_la_vigente_es_la_de_mayor_version(alm):
    alm.composiciones.agregar(fila(version=1, estado="propuesta"))
    alm.composiciones.agregar(fila(version=2, estado="editada"))
    assert alm.composiciones.vigente(1, 7).estado == "editada"


def test_el_historial_viene_en_orden(alm):
    for n, est in enumerate(("propuesta", "editada", "aprobada"), start=1):
        alm.composiciones.agregar(fila(version=n, estado=est))
    assert [f.estado for f in alm.composiciones.historial(1, 7)] == [
        "propuesta", "editada", "aprobada"]


def test_repetir_una_version_choca(alm):
    """La protección del doble clic es el índice único, no un if."""
    alm.composiciones.agregar(fila(version=1))
    with pytest.raises(VersionYaExiste):
        alm.composiciones.agregar(fila(version=1, estado="aprobada"))


def test_sin_composicion_la_vigente_es_none(alm):
    assert alm.composiciones.vigente(1, 99) is None
    assert alm.composiciones.historial(1, 99) == []


def test_cada_fila_es_de_su_corrida_y_su_seq(alm):
    alm.composiciones.agregar(fila(corrida_id=1, seq=7))
    alm.composiciones.agregar(fila(corrida_id=1, seq=8))
    alm.composiciones.agregar(fila(corrida_id=2, seq=7))
    assert alm.composiciones.vigente(1, 8).seq == 8
    assert alm.composiciones.vigente(2, 7).corrida_id == 2


def test_los_campos_opcionales_aceptan_none(alm):
    alm.composiciones.agregar(fila(ficha=None, propuesta=None, validacion=None,
                                   confianza=None, confianza_motivos=None,
                                   antecedentes=None, estado="error",
                                   motivo="la IA no contestó"))
    v = alm.composiciones.vigente(1, 7)
    assert v.estado == "error" and v.motivo == "la IA no contestó"
    assert v.propuesta is None and v.confianza_motivos is None


def test_la_aprobada_guarda_el_apu_creado(alm):
    alm.composiciones.agregar(fila(estado="aprobada", apu_codigo="9001",
                                   apu_turno="DIURNO"))
    v = alm.composiciones.vigente(1, 7)
    assert (v.apu_codigo, v.apu_turno) == ("9001", "DIURNO")


def test_la_fila_persistida_no_lleva_dinero(alm):
    """Toda la fila es reinyectable en un payload: por eso `actividad` guarda la
    vista des-monetizada y no el LicitacionItem crudo."""
    from apu_tool.dominio import privacy
    alm.composiciones.agregar(fila())
    privacy.assert_no_money(alm.composiciones.vigente(1, 7).to_dict())


def test_no_hay_columna_para_el_razonamiento_del_modelo(alm):
    """No se guarda cadena de pensamiento: criterio 36."""
    from dataclasses import fields
    nombres = {f.name for f in fields(ComposicionRow)}
    assert not (nombres & {"thinking", "razonamiento", "pensamiento", "reasoning"})
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_composiciones_db.py -q`
Esperado: FALLA con `ImportError: cannot import name 'ComposicionRow'`

- [ ] **Paso 3a: agregar el tipo a `nucleo/models.py`**

Al final de `apu_tool/nucleo/models.py`:

```python
@dataclass(frozen=True)
class ComposicionRow:
    """Una VERSIÓN del expediente de composición de una fila de corrida.

    Append-only: cada acción que cambia la propuesta (generar, regenerar, editar,
    aprobar, rechazar) escribe una fila nueva y la vigente es la de mayor `version`.
    El historial de correcciones sale gratis, y es lo que la fase 4 va a leer como
    evidencia.

    NO lleva dinero, y es deliberado: `actividad` guarda la vista des-monetizada
    (`privacy.licitacion_item_to_dict`), no el `LicitacionItem` crudo, que traería
    `precio_contractual`. Así la fila entera se puede reinyectar en un payload hacia la
    IA sin volver a filtrarla. Es la lección de `plan_json`, aplicada antes de tropezar.

    Tampoco hay campo para razonamiento del modelo: solo justificaciones cortas, datos
    estructurados, referencias y decisiones observables.
    """
    id: Optional[int]
    corrida_id: int
    seq: int
    version: int
    estado: str                       # de dominio.composicion.ESTADOS
    actividad: dict
    ficha: Optional[dict]             # fase 2; None en fase 1
    propuesta: Optional[dict]
    validacion: Optional[dict]
    confianza: Optional[str]          # alta | media | baja | insuficiente
    confianza_motivos: Optional[list]
    antecedentes: Optional[dict]
    modelo: Optional[str]
    prompt_version: Optional[str]
    apu_codigo: Optional[str]         # el APU creado, solo si estado == 'aprobada'
    apu_turno: Optional[str]
    autor: Optional[str]
    creada_en: str
    motivo: Optional[str]             # el error, o la razón del rechazo

    def to_dict(self) -> dict:
        return {
            "corrida_id": self.corrida_id, "seq": self.seq, "version": self.version,
            "estado": self.estado, "actividad": self.actividad, "ficha": self.ficha,
            "propuesta": self.propuesta, "validacion": self.validacion,
            "confianza": self.confianza, "confianza_motivos": self.confianza_motivos,
            "antecedentes": self.antecedentes, "modelo": self.modelo,
            "prompt_version": self.prompt_version, "apu_codigo": self.apu_codigo,
            "apu_turno": self.apu_turno, "autor": self.autor,
            "creada_en": self.creada_en, "motivo": self.motivo,
        }
```

- [ ] **Paso 3b: agregar la tabla a `db/corridas.sql`**

Al final de `db/corridas.sql`:

```sql
-- Expediente de composición asistida: una fila POR VERSIÓN (append-only). La vigente
-- es la de mayor `version`; el historial de correcciones es la tabla entera.
-- SIN dinero a propósito: `actividad_json` guarda la vista des-monetizada del ítem
-- (sin precio_contractual), así la fila completa se puede reinyectar en un payload
-- hacia la IA. No hay columna para razonamiento del modelo.
CREATE TABLE IF NOT EXISTS composicion (
  id              INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id      INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE,
  seq             INTEGER NOT NULL,
  version         INTEGER NOT NULL,
  estado          TEXT NOT NULL,
  actividad_json  TEXT NOT NULL,
  ficha_json      TEXT,
  propuesta_json  TEXT,
  validacion_json TEXT,
  confianza       TEXT,
  confianza_json  TEXT,
  antecedentes_json TEXT,
  modelo          TEXT,
  prompt_version  TEXT,
  apu_codigo      TEXT,
  apu_turno       TEXT,
  autor           TEXT,
  creada_en       TEXT NOT NULL,
  motivo          TEXT
);
-- La protección del doble clic, y por eso es un índice y no un `if`: las dos
-- peticiones de un doble clic llegan con milisegundos de diferencia y las dos leerían
-- la misma versión vigente. Mismo criterio que ux_corrida_armando_archivo.
CREATE UNIQUE INDEX IF NOT EXISTS ux_composicion_version
  ON composicion(corrida_id, seq, version);
CREATE INDEX IF NOT EXISTS ix_composicion ON composicion(corrida_id, seq);
```

- [ ] **Paso 3c: crear el repo SQLite**

Crea `apu_tool/datos/composiciones_db.py`:

```python
"""Acceso a la tabla `composicion` (vive en corridas.db). Implementa
RepositorioComposiciones.

Append-only: `agregar` escribe una versión y nunca actualiza. La `version` la manda el
llamador (`version_base + 1`), NO se calcula acá con un MAX+1: si se calculara adentro,
dos clics seguidos sacarían 4 y 5 y los dos entrarían, y el índice único no protegería
nada. Con la versión explícita, el segundo choca y el servicio devuelve 409.

Como CarpetasDB, comparte el archivo corridas.db y no tiene init_schema propio: la
tabla se crea con el resto del esquema (`db/corridas.sql`, cargado por CorridasDB).
"""
from __future__ import annotations

import json
import sqlite3
from contextlib import contextmanager
from pathlib import Path
from typing import Any, Iterator, Optional

from apu_tool import config
from apu_tool.datos.repositorio import VersionYaExiste
from apu_tool.nucleo.models import ComposicionRow

_COLS = ("corrida_id", "seq", "version", "estado", "actividad_json", "ficha_json",
         "propuesta_json", "validacion_json", "confianza", "confianza_json",
         "antecedentes_json", "modelo", "prompt_version", "apu_codigo", "apu_turno",
         "autor", "creada_en", "motivo")


def _j(v: Any) -> Optional[str]:
    return None if v is None else json.dumps(v, ensure_ascii=False)


def _dj(v: Any) -> Any:
    return None if v in (None, "") else json.loads(v)


def _params(f: ComposicionRow) -> tuple:
    return (int(f.corrida_id), int(f.seq), int(f.version), f.estado,
            _j(f.actividad), _j(f.ficha), _j(f.propuesta), _j(f.validacion),
            f.confianza, _j(f.confianza_motivos), _j(f.antecedentes), f.modelo,
            f.prompt_version, f.apu_codigo, f.apu_turno, f.autor, f.creada_en,
            f.motivo)


def _fila(r) -> ComposicionRow:
    return ComposicionRow(
        id=r["id"], corrida_id=r["corrida_id"], seq=r["seq"], version=r["version"],
        estado=r["estado"], actividad=_dj(r["actividad_json"]) or {},
        ficha=_dj(r["ficha_json"]), propuesta=_dj(r["propuesta_json"]),
        validacion=_dj(r["validacion_json"]), confianza=r["confianza"],
        confianza_motivos=_dj(r["confianza_json"]),
        antecedentes=_dj(r["antecedentes_json"]), modelo=r["modelo"],
        prompt_version=r["prompt_version"], apu_codigo=r["apu_codigo"],
        apu_turno=r["apu_turno"], autor=r["autor"], creada_en=r["creada_en"],
        motivo=r["motivo"])


class ComposicionesDB:
    """Backend SQLite del expediente de composición."""

    def __init__(self, path: Path | str = config.CORRIDAS_DB_PATH):
        self.path = Path(path)
        self.path.parent.mkdir(parents=True, exist_ok=True)

    @contextmanager
    def connect(self) -> Iterator[sqlite3.Connection]:
        conn = sqlite3.connect(self.path)
        conn.row_factory = sqlite3.Row
        conn.execute("PRAGMA foreign_keys = ON")
        try:
            yield conn
            conn.commit()
        finally:
            conn.close()

    def agregar(self, fila: ComposicionRow, conn=None) -> None:
        sql = (f"INSERT INTO composicion ({', '.join(_COLS)}) "
               f"VALUES ({', '.join('?' * len(_COLS))})")
        try:
            if conn is not None:
                conn.execute(sql, _params(fila))
                return
            with self.connect() as c:
                c.execute(sql, _params(fila))
        except sqlite3.IntegrityError as exc:
            raise VersionYaExiste(fila.corrida_id, fila.seq, fila.version) from exc

    def vigente(self, corrida_id: int, seq: int) -> Optional[ComposicionRow]:
        with self.connect() as conn:
            r = conn.execute(
                "SELECT * FROM composicion WHERE corrida_id=? AND seq=? "
                "ORDER BY version DESC LIMIT 1",
                (int(corrida_id), int(seq))).fetchone()
        return _fila(r) if r else None

    def historial(self, corrida_id: int, seq: int) -> list[ComposicionRow]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT * FROM composicion WHERE corrida_id=? AND seq=? "
                "ORDER BY version", (int(corrida_id), int(seq))).fetchall()
        return [_fila(r) for r in rows]
```

- [ ] **Paso 3d: agregar la excepción y el Protocol**

En `apu_tool/datos/repositorio.py`, después de `ArmadoDuplicado`:

```python
class VersionYaExiste(Exception):
    """Se intentó escribir una versión de composición que ya está.

    La levanta el índice único `ux_composicion_version`, no una comprobación previa:
    las dos peticiones de un doble clic leerían la misma versión vigente y las dos
    creerían estar escribiendo la siguiente. El servicio la traduce a un 409.
    """

    def __init__(self, corrida_id: int, seq: int, version: int):
        super().__init__(f"La composición {corrida_id}/{seq} ya tiene la versión "
                         f"{version}: alguien más la cambió mientras trabajabas.")
        self.corrida_id, self.seq, self.version = corrida_id, seq, version
```

Y al final del archivo, el Protocol (agrega `ComposicionRow` al import de arriba):

```python
@runtime_checkable
class RepositorioComposiciones(Protocol):
    def agregar(self, fila: ComposicionRow, conn=None) -> None:
        """Escribe una versión NUEVA. Levanta VersionYaExiste si esa versión ya está."""
        ...

    def vigente(self, corrida_id: int, seq: int) -> Optional[ComposicionRow]:
        """La versión de mayor número, o None si nunca se compuso esta fila."""
        ...

    def historial(self, corrida_id: int, seq: int) -> list[ComposicionRow]:
        """Todas las versiones, de la más vieja a la más nueva."""
        ...
```

- [ ] **Paso 3e: enchufarlo en el `Almacen`**

En `apu_tool/datos/almacen.py`, en la rama SQLite (junto a `self.carpetas = CarpetasDB(corridas_path)`):

```python
            self.composiciones = ComposicionesDB(corridas_path)
```

Y el import arriba, con los demás:

```python
from apu_tool.datos.composiciones_db import ComposicionesDB
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_composiciones_db.py tests/test_corridas_db.py \
                 tests/test_repositorios_contrato.py -q
```

Esperado: `10 passed` en la primera; las otras dos siguen verdes.

- [ ] **Paso 5: commit**

```bash
git add apu_tool/nucleo/models.py apu_tool/datos/composiciones_db.py \
        apu_tool/datos/repositorio.py apu_tool/datos/almacen.py db/corridas.sql \
        tests/test_composiciones_db.py
git commit -m "feat(datos): expediente de composicion append-only por version (SQLite)"
```

---

## Tarea 8: persistencia Postgres y paridad

Espejo 1:1 del repo SQLite. La paridad se prueba con **los mismos casos** corriendo
contra los dos backends, no con una lista aparte que se desincroniza.

**Archivos:**
- Crear: `apu_tool/datos/pg/composiciones_pg.py`
- Modificar: `db/pg/corridas.sql`, `apu_tool/datos/almacen.py`
- Test: `tests/test_composiciones_paridad.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""Paridad SQLite ↔ Postgres del expediente de composición (criterio 33).

Reusa los casos de test_composiciones_db.py contra los dos backends: una lista aparte
se desincroniza el día que alguien agrega un caso en un solo lado.

Los de Postgres se saltan sin TEST_DATABASE_URL. OJO: hacen DROP SCHEMA — nunca
apuntarlos a producción (ver docs y el guard autouse de conftest.py).
"""
import os

import pytest

from apu_tool.datos.repositorio import VersionYaExiste
from tests.test_composiciones_db import fila

pg = pytest.importorskip("psycopg", reason="psycopg no instalado")
URL = os.environ.get("TEST_DATABASE_URL")
pytestmark = pytest.mark.skipif(not URL, reason="sin TEST_DATABASE_URL")


@pytest.fixture()
def repo_pg():
    from apu_tool.datos.pg.composiciones_pg import ComposicionesPg
    from apu_tool.datos.pg.conexion import Conexion
    from apu_tool.datos.pg.corridas_pg import CorridasPg
    cx = Conexion(URL)
    CorridasPg(cx).reset()
    with cx.connection() as c:
        c.execute("INSERT INTO corridas.corrida "
                  "(creada_en, archivo, turno_def, estado) "
                  "VALUES ('2026-09-10','x.xlsx','DIURNO','en_revision')")
    yield ComposicionesPg(cx)
    cx.cerrar()


def _id_de_corrida(repo) -> int:
    with repo.cx.connection() as c:
        return int(c.execute("SELECT id FROM corridas.corrida "
                             "ORDER BY id DESC LIMIT 1").fetchone()["id"])


def test_pg_guarda_y_recupera_la_vigente(repo_pg):
    cid = _id_de_corrida(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid))
    v = repo_pg.vigente(cid, 7)
    assert v.version == 1 and v.estado == "propuesta"
    assert v.propuesta["componentes"][0]["codigo"] == "4279"
    assert v.confianza_motivos[0]["aporte"] == 2


def test_pg_la_vigente_es_la_de_mayor_version(repo_pg):
    cid = _id_de_corrida(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid, version=1, estado="propuesta"))
    repo_pg.agregar(fila(corrida_id=cid, version=2, estado="editada"))
    assert repo_pg.vigente(cid, 7).estado == "editada"


def test_pg_el_historial_viene_en_orden(repo_pg):
    cid = _id_de_corrida(repo_pg)
    for n, est in enumerate(("propuesta", "editada", "aprobada"), start=1):
        repo_pg.agregar(fila(corrida_id=cid, version=n, estado=est))
    assert [f.estado for f in repo_pg.historial(cid, 7)] == [
        "propuesta", "editada", "aprobada"]


def test_pg_repetir_una_version_choca_igual_que_sqlite(repo_pg):
    cid = _id_de_corrida(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid, version=1))
    with pytest.raises(VersionYaExiste):
        repo_pg.agregar(fila(corrida_id=cid, version=1, estado="aprobada"))


def test_pg_sin_composicion_la_vigente_es_none(repo_pg):
    cid = _id_de_corrida(repo_pg)
    assert repo_pg.vigente(cid, 99) is None
    assert repo_pg.historial(cid, 99) == []


def test_pg_los_campos_opcionales_aceptan_none(repo_pg):
    cid = _id_de_corrida(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid, ficha=None, propuesta=None, validacion=None,
                         confianza=None, confianza_motivos=None, antecedentes=None,
                         estado="error", motivo="la IA no contestó"))
    v = repo_pg.vigente(cid, 7)
    assert v.estado == "error" and v.propuesta is None


def test_pg_borra_en_cascada_con_la_corrida(repo_pg):
    cid = _id_de_corrida(repo_pg)
    repo_pg.agregar(fila(corrida_id=cid))
    with repo_pg.cx.connection() as c:
        c.execute("DELETE FROM corridas.corrida WHERE id=%s", (cid,))
    assert repo_pg.vigente(cid, 7) is None
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

```bash
python -m pytest tests/test_composiciones_paridad.py -q
```

Esperado sin `TEST_DATABASE_URL`: `7 skipped`. Con la base desechable levantada
(receta en `docs/`): FALLA con `ModuleNotFoundError: apu_tool.datos.pg.composiciones_pg`.

- [ ] **Paso 3a: agregar la tabla a `db/pg/corridas.sql`**

Al final de `db/pg/corridas.sql`, **antes** del bloque de bootstrap de carpetas:

```sql
-- Expediente de composición asistida. Equivalente a la tabla `composicion` de
-- db/corridas.sql: una fila POR VERSIÓN (append-only); la vigente es la de mayor
-- `version`. SIN dinero: actividad_json guarda la vista des-monetizada del ítem.
CREATE TABLE IF NOT EXISTS corridas.composicion (
    id              BIGINT GENERATED ALWAYS AS IDENTITY PRIMARY KEY,
    corrida_id      BIGINT NOT NULL REFERENCES corridas.corrida(id) ON DELETE CASCADE,
    seq             INTEGER NOT NULL,
    version         INTEGER NOT NULL,
    estado          TEXT NOT NULL,
    actividad_json  TEXT NOT NULL,
    ficha_json      TEXT,
    propuesta_json  TEXT,
    validacion_json TEXT,
    confianza       TEXT,
    confianza_json  TEXT,
    antecedentes_json TEXT,
    modelo          TEXT,
    prompt_version  TEXT,
    apu_codigo      TEXT,
    apu_turno       TEXT,
    autor           TEXT,
    creada_en       TEXT NOT NULL,
    motivo          TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS ux_composicion_version
    ON corridas.composicion(corrida_id, seq, version);
CREATE INDEX IF NOT EXISTS ix_composicion ON corridas.composicion(corrida_id, seq);
```

- [ ] **Paso 3b: crear el repo Postgres**

Crea `apu_tool/datos/pg/composiciones_pg.py`:

```python
"""Backend Postgres del expediente de composición. Port de composiciones_db.py."""
from __future__ import annotations

from typing import Optional

from apu_tool.datos.composiciones_db import _COLS, _dj, _params
from apu_tool.datos.pg.conexion import Conexion
from apu_tool.datos.repositorio import VersionYaExiste
from apu_tool.nucleo.models import ComposicionRow


def _fila(r) -> ComposicionRow:
    return ComposicionRow(
        id=r["id"], corrida_id=r["corrida_id"], seq=r["seq"], version=r["version"],
        estado=r["estado"], actividad=_dj(r["actividad_json"]) or {},
        ficha=_dj(r["ficha_json"]), propuesta=_dj(r["propuesta_json"]),
        validacion=_dj(r["validacion_json"]), confianza=r["confianza"],
        confianza_motivos=_dj(r["confianza_json"]),
        antecedentes=_dj(r["antecedentes_json"]), modelo=r["modelo"],
        prompt_version=r["prompt_version"], apu_codigo=r["apu_codigo"],
        apu_turno=r["apu_turno"], autor=r["autor"], creada_en=r["creada_en"],
        motivo=r["motivo"])


class ComposicionesPg:
    def __init__(self, cx: Conexion):
        self.cx = cx

    def agregar(self, fila: ComposicionRow, conn=None) -> None:
        sql = (f"INSERT INTO corridas.composicion ({', '.join(_COLS)}) "
               f"VALUES ({', '.join(['%s'] * len(_COLS))})")
        try:
            if conn is not None:
                conn.execute(sql, _params(fila))
                return
            with self.cx.connection() as c:
                c.execute(sql, _params(fila))
        except Exception as exc:
            # Se mira el SQLSTATE y no la clase: 23505 es unique_violation. Traducirla
            # acá deja al servicio hablando un solo idioma con los dos backends.
            if getattr(exc, "sqlstate", None) == "23505":
                raise VersionYaExiste(fila.corrida_id, fila.seq, fila.version) from exc
            raise

    def vigente(self, corrida_id: int, seq: int) -> Optional[ComposicionRow]:
        with self.cx.connection() as conn:
            r = conn.execute(
                "SELECT * FROM corridas.composicion WHERE corrida_id=%s AND seq=%s "
                "ORDER BY version DESC LIMIT 1",
                (int(corrida_id), int(seq))).fetchone()
        return _fila(r) if r else None

    def historial(self, corrida_id: int, seq: int) -> list[ComposicionRow]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT * FROM corridas.composicion WHERE corrida_id=%s AND seq=%s "
                "ORDER BY version", (int(corrida_id), int(seq))).fetchall()
        return [_fila(r) for r in rows]
```

- [ ] **Paso 3c: enchufarlo en el `Almacen`**

En `apu_tool/datos/almacen.py`, en la rama Postgres, junto a
`self.carpetas = CarpetasPg(self._cx)`:

```python
            from apu_tool.datos.pg.composiciones_pg import ComposicionesPg
            self.composiciones = ComposicionesPg(self._cx)
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_composiciones_paridad.py tests/test_paridad_backends.py \
                 tests/test_pg_esquema.py -q
```

Esperado sin `TEST_DATABASE_URL`: los de Postgres se saltan y el resto pasa. Con la
base desechable: `7 passed` en el primero.

- [ ] **Paso 5: commit**

```bash
git add apu_tool/datos/pg/composiciones_pg.py apu_tool/datos/almacen.py \
        db/pg/corridas.sql tests/test_composiciones_paridad.py
git commit -m "feat(datos): expediente de composicion en Postgres, con paridad probada"
```

---

## Tarea 9: el orquestador

Cose las piezas y emite los eventos del SSE. Acá muere también la composición vieja
(`ApuAdvisor.compose_apu` y `Assembler.generar_composicion`), con sus tests migrados: se
van juntas para que ninguna tarea deje el árbol rojo.

Se parte en tres funciones porque tienen tres llamadores distintos:

- `recuperar()` — arma el contexto (una lectura del catálogo sirve para el `grupo` de
  los candidatos **y** para `unidades_catalogo` del validador).
- `evaluar()` — recalcula, valida y calcula la confianza. **La usa el `PUT`**, cuando
  el humano guarda una edición y no hay que volver a pagarle a la IA.
- `componer()` — el generador con los eventos; usa las dos anteriores.

**Archivos:**
- Crear: `apu_tool/dominio/composicion_agente.py`
- Modificar: `apu_tool/dominio/ai_assist.py`, `apu_tool/dominio/assemble.py`,
  `tests/test_compose.py`, `tests/test_assemble_generado.py`
- Test: `tests/test_composicion_motor.py`

> **Cambio respecto al borrador del plan** (revisión de calidad de la tarea 1): el
> orquestador va en un **archivo hermano**, no al final de `composicion.py`. Razón: el
> orquestador arrastra `Almacen` y la fachada del SDK, y todo el que importe el
> contrato — el validador, `esquemas.py`, el servicio — se los comería. Es el mismo
> reparto que ya tiene el repo entre `revision.py` y `ai_assist.py`. Como efecto
> secundario desaparecen los imports dentro de funciones que el borrador usaba para
> esquivar ese acoplamiento: acá van todos arriba, normales.
>
> En el código de abajo, donde dice "al final de `composicion.py`", va en
> `composicion_agente.py`, con estos imports a nivel de módulo:
>
> ```python
> from dataclasses import dataclass, replace
> from typing import Any
>
> from apu_tool.dominio import privacy
> from apu_tool.dominio.ai_assist import PROMPT_VERSION, IANoDisponible
> from apu_tool.dominio.compose import InsumoRetriever, rendimientos_observados
> from apu_tool.dominio.composicion import Propuesta, propuesta_desde_json
> from apu_tool.dominio.validacion_composicion import (
>     ContextoValidacion, calcular_confianza, validar,
> )
> ```
>
> Y el test importa `componer`, `evaluar` y `recuperar` de
> `apu_tool.dominio.composicion_agente` (los tipos siguen viniendo de
> `apu_tool.dominio.composicion`).

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""El orquestador: eventos, estados y el pegado de las piezas.

El advisor se sustituye; no se llama a la API real.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.dominio.ai_assist import ApuAdvisor, IANoDisponible
from apu_tool.dominio.composicion import (
    Calculo, ComponentePropuesto, Propuesta, Referencia,
)
from apu_tool.dominio.composicion_agente import componer, evaluar, recuperar
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem

ITEM = LicitacionItem("1.3", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3", 120.0,
                      180000.0, "DIURNO")


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                tmp_path / "corridas.db")
    a.reset()
    a.precios.insert_insumos([
        Insumo("4279", "CUADRILLA OFICIAL MAS AYUDANTES", "HR", "MO", 40000,
               "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
    ])
    a.apus.insert_apus([Apu("A1", "EXCAVACION MANUAL COMUN", "M3", "DIURNO", "EXCAVACIONES")])
    a.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 40000),
        ApuComponent("A1", "DIURNO", "6092", "HERRAMIENTA MENOR", "GLB", 1.0, 2000),
    ])
    return a


class AdvisorFalso(ApuAdvisor):
    def __init__(self, propuesta: Propuesta):
        self.enabled = True
        self._client = object()
        self.model = "falso"
        self.propuesta = propuesta
        self.llamadas = 0

    def componer(self, item, insumos, ejemplos, observados):
        self.llamadas += 1
        self.insumos_vistos = insumos
        return self.propuesta


def comp(**kw) -> ComponentePropuesto:
    base = dict(codigo="4279", tipo="insumo", funcion="mano_de_obra",
                rendimiento=0.62, origen="copiado_de_antecedente",
                referencias=(Referencia("A1", "DIURNO"),), hipotesis={},
                calculo=None, justificacion="j", nivel_evidencia="alto",
                ref_shift="")
    base.update(kw)
    return ComponentePropuesto(**base)


SANA = Propuesta(componentes=(comp(),
                              comp(codigo="6092", funcion="herramienta",
                                   rendimiento=1.0)))


def eventos(alm, advisor, item=ITEM) -> list[tuple[str, dict]]:
    return list(componer(alm, item, advisor))


# --- recuperar -------------------------------------------------------------
def test_recuperar_llena_el_grupo_de_los_candidatos(alm):
    ctx = recuperar(alm, ITEM)
    grupos = {i.codigo: i.grupo for i in ctx.insumos}
    assert grupos.get("4279") == "MO"


def test_recuperar_arma_la_lista_blanca_y_las_unidades(alm):
    ctx = recuperar(alm, ITEM)
    assert "4279" in ctx.validacion.codigos_permitidos
    assert ctx.validacion.unidades_catalogo["4279"] == "HR"
    assert ("A1", "DIURNO") in ctx.validacion.apus_existentes
    assert ctx.validacion.unidades_de_apu[("A1", "DIURNO")] == "M3"


def test_recuperar_trae_los_rendimientos_observados(alm):
    assert "4279" in recuperar(alm, ITEM).validacion.observados


# --- evaluar (el camino del PUT) -------------------------------------------
def test_evaluar_no_llama_a_la_ia(alm):
    """Guardar una edición humana no vuelve a pagar una generación."""
    ctx = recuperar(alm, ITEM)
    propuesta, validacion, confianza = evaluar(SANA, ctx.validacion)
    assert validacion.valido is True
    assert confianza.nivel in ("alta", "media", "baja")
    assert len(propuesta.componentes) == 2


def test_evaluar_recalcula_la_aritmetica(alm):
    ctx = recuperar(alm, ITEM)
    mala = Propuesta(componentes=(comp(rendimiento=0.09,
                                       calculo=Calculo("division", 8, 96, 0.09)),))
    propuesta, validacion, _ = evaluar(mala, ctx.validacion)
    assert propuesta.componentes[0].rendimiento == pytest.approx(8 / 96)
    assert any(h.codigo == "CALCULO_CORREGIDO" for h in validacion.advertencias)


# --- componer --------------------------------------------------------------
def test_los_eventos_salen_en_orden(alm):
    evs = eventos(alm, AdvisorFalso(SANA))
    assert [e for e, _ in evs] == ["recuperando", "generando", "validando", "lista"]


def test_el_evento_recuperando_dice_cuanto_encontro(alm):
    _, payload = eventos(alm, AdvisorFalso(SANA))[0]
    assert set(payload) == {"n_insumos", "n_apus"}
    assert payload["n_insumos"] > 0


def test_el_evento_lista_trae_todo_lo_que_hay_que_guardar(alm):
    _, payload = eventos(alm, AdvisorFalso(SANA))[-1]
    assert set(payload) == {"propuesta", "validacion", "confianza",
                            "confianza_motivos", "antecedentes", "modelo",
                            "prompt_version"}
    assert payload["prompt_version"].startswith("composicion/")
    assert payload["modelo"] == "falso"


def test_los_antecedentes_guardan_la_lista_blanca(alm):
    _, payload = eventos(alm, AdvisorFalso(SANA))[-1]
    assert "4279" in payload["antecedentes"]["codigos_permitidos"]
    assert {"codigo": "A1", "turno": "DIURNO"} in \
        payload["antecedentes"]["apus_referencia"]


def test_una_propuesta_vacia_sale_invalida_nunca_lista_en_verde(alm):
    _, payload = eventos(alm, AdvisorFalso(Propuesta()))[-1]
    assert payload["validacion"]["valido"] is False
    assert payload["confianza"] == "insuficiente"


def test_un_codigo_inventado_no_pasa(alm):
    inventada = Propuesta(componentes=(comp(codigo="NO-EXISTE"),))
    _, payload = eventos(alm, AdvisorFalso(inventada))[-1]
    codigos = {e["codigo"] for e in payload["validacion"]["errores"]}
    assert "CODIGO_NO_AUTORIZADO" in codigos


def test_la_ia_solo_ve_los_codigos_autorizados(alm):
    a = AdvisorFalso(SANA)
    eventos(alm, a)
    _, payload = eventos(alm, a)[-1]
    assert {i.codigo for i in a.insumos_vistos} <= \
        set(payload["antecedentes"]["codigos_permitidos"])


def test_sin_credencial_el_evento_es_error(alm):
    class Sin(AdvisorFalso):
        def componer(self, *a, **k):
            raise IANoDisponible("falta ANTHROPIC_API_KEY")

    evs = eventos(alm, Sin(SANA))
    assert evs[-1][0] == "error"
    assert "ANTHROPIC_API_KEY" in evs[-1][1]["detail"]


def test_una_actividad_sin_candidatos_da_error_legible(alm):
    vacia = LicitacionItem("9.9", "ZZZZZZ QQQQQQ", "UN", 1.0, 0.0, "DIURNO")
    alm.precios.reset()
    alm.apus.reset()
    evs = eventos(alm, AdvisorFalso(SANA), item=vacia)
    assert evs[-1][0] == "error"


def test_la_privacidad_no_se_traga_nunca(alm):
    """Una PrivacyViolation sube; NO se convierte en un evento `error` genérico."""
    from apu_tool.dominio import privacy

    class Fuga(AdvisorFalso):
        def componer(self, *a, **k):
            raise privacy.PrivacyViolation("se coló un precio")

    with pytest.raises(privacy.PrivacyViolation):
        eventos(alm, Fuga(SANA))


def test_el_payload_del_evento_lista_no_lleva_dinero(alm):
    from apu_tool.dominio import privacy
    _, payload = eventos(alm, AdvisorFalso(SANA))[-1]
    privacy.assert_no_money(payload)
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_composicion_motor.py -q`
Esperado: FALLA con `ImportError: cannot import name 'componer'`

- [ ] **Paso 3a: agregar el orquestador a `composicion.py`**

Al final de `apu_tool/dominio/composicion.py`:

```python
# ------------------------------------------------------------- orquestador
@dataclass(frozen=True)
class ContextoComposicion:
    """Todo lo recuperado para una composición: lo que va al modelo y lo que valida."""
    insumos: tuple                        # CandidateInsumo, con `grupo` lleno
    ejemplos: tuple                       # DePricedApu de referencia
    validacion: Any                       # ContextoValidacion


def recuperar(almacen, item, *, apu_codigo_propio: str = "",
              supuestos_confirmados: bool = False) -> ContextoComposicion:
    """Arma el contexto de una composición con UNA lectura del catálogo.

    Esa lectura sirve para dos cosas que si no se harían por separado: el `grupo` de
    cada candidato (que viaja al modelo) y `unidades_catalogo` (que usa el validador
    para saber si un código existe). Una consulta, dos usos.
    """
    from dataclasses import replace as _replace

    from apu_tool.dominio.compose import InsumoRetriever, rendimientos_observados
    from apu_tool.dominio.validacion_composicion import ContextoValidacion

    insumos, ejemplos = InsumoRetriever(almacen).retrieve(item.descripcion, item.shift)
    codigos = [i.codigo for i in insumos]

    # Una sola consulta al catálogo: grupo (para el modelo) + unidad (para validar).
    catalogo = almacen.precios.get_candidatos_bulk(codigos)
    grupos, unidades = {}, {}
    for cod, cands in catalogo.items():
        if cands:
            grupos[cod] = cands[0].grupo or ""
            unidades[cod] = cands[0].unidad or ""
    insumos = tuple(_replace(i, grupo=grupos.get(i.codigo, "")) for i in insumos)

    apus = almacen.apus.all_apus()
    componentes = {}
    for (cod, turno), comps in almacen.apus.get_components_bulk(
            [(a.codigo, a.shift) for a in apus]).items():
        componentes[(cod, turno)] = tuple(
            (c.insumo_codigo, c.tipo, c.ref_shift) for c in comps)

    ctx = ContextoValidacion(
        descripcion=item.descripcion, unidad_actividad=item.unidad, shift=item.shift,
        codigos_permitidos=frozenset(codigos),
        unidades_catalogo=unidades,
        apus_existentes=frozenset((a.codigo, a.shift) for a in apus),
        componentes_de_apu=componentes,
        observados=rendimientos_observados(almacen, codigos),
        unidades_de_apu={(a.codigo, a.shift): a.unidad or "" for a in apus},
        apu_codigo_propio=apu_codigo_propio,
        supuestos_confirmados=supuestos_confirmados)
    return ContextoComposicion(tuple(insumos), tuple(ejemplos), ctx)


def evaluar(propuesta: Propuesta, ctx_validacion):
    """Recalcula, valida y calcula la confianza. SIN IA.

    Es el camino del `PUT`: guardar una edición humana no vuelve a pagar una
    generación. También lo usa `componer` después de la llamada al modelo, así que la
    propuesta de la IA y la editada a mano pasan por exactamente el mismo filtro.
    """
    from apu_tool.dominio.validacion_composicion import calcular_confianza, validar

    corregida, validacion = validar(propuesta, ctx_validacion)
    return corregida, validacion, calcular_confianza(corregida, validacion,
                                                     ctx_validacion)


def componer(almacen, item, advisor, *, apu_codigo_propio: str = "",
             supuestos_confirmados: bool = False):
    """Genera una propuesta y emite los eventos del SSE.

      ('recuperando', {'n_insumos', 'n_apus'})
      ('generando',   {})
      ('validando',   {})
      ('lista',       {propuesta, validacion, confianza, confianza_motivos,
                       antecedentes, modelo, prompt_version})
      ('error',       {'detail'})

    Emite eventos y no devuelve un objeto, por lo mismo que `revision.revisar`: el
    llamador persiste y reporta en vivo, y una conexión muda demasiado rato la corta el
    proxy. El evento `lista` trae exactamente lo que hay que guardar.

    Una `PrivacyViolation` NO se convierte en un evento `error`: sube. El invariante #1
    no se maquilla como "no se pudo componer" — mismo criterio que `revision.barrer_lote`.
    """
    from apu_tool.dominio import privacy
    from apu_tool.dominio.ai_assist import PROMPT_VERSION, IANoDisponible

    try:
        ctx = recuperar(almacen, item, apu_codigo_propio=apu_codigo_propio,
                        supuestos_confirmados=supuestos_confirmados)
        yield ("recuperando", {"n_insumos": len(ctx.insumos),
                               "n_apus": len(ctx.ejemplos)})
        yield ("generando", {})
        cruda = advisor.componer(item, list(ctx.insumos), list(ctx.ejemplos),
                                 ctx.validacion.observados)
        yield ("validando", {})
    except privacy.PrivacyViolation:
        raise                       # el invariante #1 nunca se traga
    except (IANoDisponible, ValueError) as exc:
        yield ("error", {"detail": str(exc)})
        return

    propuesta, validacion, confianza = evaluar(cruda, ctx.validacion)
    yield ("lista", {
        "propuesta": propuesta.to_dict(),
        "validacion": validacion.to_dict(),
        "confianza": confianza.nivel,
        "confianza_motivos": [m.to_dict() for m in confianza.motivos],
        "antecedentes": {
            "codigos_permitidos": sorted(ctx.validacion.codigos_permitidos),
            "apus_referencia": [{"codigo": a.codigo, "turno": a.shift}
                                for a in ctx.ejemplos],
        },
        "modelo": advisor.model,
        "prompt_version": PROMPT_VERSION,
    })
```

Y arriba, en el import de `typing`, agrega `Any` si no está:

```python
from typing import Any, Optional
```

- [ ] **Paso 3b: borrar la composición vieja**

En `apu_tool/dominio/ai_assist.py`, borra:
- la dataclass `ComposedComponent`
- la dataclass `ComposeResult`
- la constante `_COMPOSE_SYSTEM`
- la constante `_COMPOSE_SCHEMA`
- el método `ApuAdvisor.compose_apu` completo

En `apu_tool/dominio/assemble.py`, borra el método `Assembler.generar_composicion`
completo y el bloque de imports que queda sin uso:

```python
from apu_tool.dominio.ai_assist import ApuAdvisor, ComposeResult
from apu_tool.dominio.compose import InsumoRetriever
```

pasa a:

```python
from apu_tool.dominio.ai_assist import ApuAdvisor
```

Borra también la `@property retriever` y el atributo `self._retriever`: nadie los usa
ya. Deja el `advisor` en el constructor **solo si algún llamador lo pasa**; si no queda
ninguno, bórralo también y actualiza el docstring de la clase.

- [ ] **Paso 3c: migrar los tests de la composición vieja**

En `tests/test_compose.py`: borra `FakeAdvisor`, `test_retriever_returns_candidates`
déjalo (sigue probando el retriever) y borra todo test que llame a
`generar_composicion` o a `compose_apu`. La cobertura equivalente vive ahora en
`tests/test_composicion_motor.py` y `tests/test_composicion_advisor.py`.

Borra `tests/test_assemble_generado.py` entero: probaba `generar_composicion`.

Verifica que `tests/test_assemble.py::test_armado_nunca_llama_a_la_ia` **sigue estando
y sigue verde** — es la garantía de que el armado no cambió.

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_composicion_motor.py -q
python -m pytest tests/ -q 2>&1 | tail -3
```

Esperado: `18 passed` en el primero. En la suite completa, el total baja respecto a las
1036 de base por los tests borrados y sube por los nuevos; **no puede haber ni un
fallo**. Si `test_servicio_corridas.py` o `test_api_corridas.py` fallan, es porque
`componer_item` todavía llama a `generar_composicion`: eso se arregla en la tarea 10, así
que **si ese es el único rojo, anótalo y sigue** — pero no commitees rojo: mueve el
borrado de `componer_item` a esta tarea si hace falta para dejar verde.

- [ ] **Paso 5: commit**

```bash
git add apu_tool/dominio/composicion.py apu_tool/dominio/ai_assist.py \
        apu_tool/dominio/assemble.py tests/test_composicion_motor.py \
        tests/test_compose.py
git rm tests/test_assemble_generado.py
git commit -m "feat(composicion): orquestador con eventos; muere la composicion de dos campos"
```

---

## Tarea 10: servicio y endpoints

Cinco endpoints. La aprobación es un endpoint y no una cadena en el navegador: llama a
`autoria.crear_apu` con los componentes de la versión vigente, sella la versión
`aprobada` y asigna el APU a la fila.

**Sobre la lista blanca en el `PUT`:** existe para que el **modelo** no invente
códigos. Un humano que agrega un componente desde el buscador del catálogo no está
inventando, así que al guardar una edición la lista se **amplía** con los códigos que
mandó el humano y que existen en el catálogo. El guardián que queda es
`CODIGO_INEXISTENTE`, que es el correcto para una adición humana.

**Archivos:**
- Crear: `apu_tool/servicio/composicion.py`
- Modificar: `apu_tool/servicio/rutas.py`, `apu_tool/servicio/esquemas.py`,
  `apu_tool/servicio/corridas.py` (borrar `componer_item`)
- Test: `tests/test_api_composicion.py`

- [ ] **Paso 1: escribir la prueba que falla**

```python
"""Los cinco endpoints de la composición: roles, códigos de error e idempotencia."""
import json

import pytest

from apu_tool.dominio.composicion import Propuesta
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from tests.conftest import cliente


@pytest.fixture()
def app_alm(tmp_path, monkeypatch):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.servicio.app import crear_app
    alm = Almacen(tmp_path / "precios.db", tmp_path / "apus.db",
                  tmp_path / "corridas.db")
    alm.reset()
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU"),
        Insumo("6092", "HERRAMIENTA MENOR", "GLB", "EQ", 2000, "PRECIO IDU"),
    ])
    alm.apus.insert_apus([Apu("A1", "EXCAVACION MANUAL", "M3", "DIURNO", "EXCAVACIONES")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "4279", "CUADRILLA", "HR", 0.62, 40000)])
    app = crear_app()
    app.state.almacen = alm
    return app, alm


@pytest.fixture()
def corrida(app_alm):
    """Una corrida con una fila SIN APU en seq 1."""
    from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta
    _, alm = app_alm
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-10T10:00:00", archivo="x.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision"))
    item = LicitacionItem("1.3", "EXCAVACION MANUAL EN MATERIAL COMUN", "M3", 120.0,
                          180000.0, "DIURNO")
    alm.corridas.guardar_items(cid, [CorridaItemRow(
        seq=1, item=item, status="new", apu_codigo=None,
        apu_nombre="(sin base — armar manual)", unidad="M3", shift="DIURNO",
        origen="manual", confianza=0.0, explicacion="", componentes=[],
        candidatos=[])])
    return cid


PROPUESTA = {"componentes": [
    {"codigo": "4279", "tipo": "insumo", "funcion": "mano_de_obra",
     "rendimiento": 0.62, "origen": "copiado_de_antecedente",
     "referencias": [{"apu_codigo": "A1", "turno": "DIURNO"}], "hipotesis": {},
     "calculo": None, "justificacion": "j", "nivel_evidencia": "alto",
     "ref_shift": ""}],
    "supuestos": [], "incertidumbre_declarada": 0.3, "justificacion": "g"}


def _sembrar(alm, cid, *, version=1, estado="propuesta", valido=True, propuesta=None):
    from apu_tool.nucleo.models import ComposicionRow
    alm.composiciones.agregar(ComposicionRow(
        id=None, corrida_id=cid, seq=1, version=version, estado=estado,
        actividad={"item": "1.3", "descripcion": "EXCAVACION MANUAL",
                   "unidad": "M3", "cantidad": 120.0, "shift": "DIURNO"},
        ficha=None, propuesta=propuesta or PROPUESTA,
        validacion={"valido": valido, "errores": [] if valido else [
            {"codigo": "PROPUESTA_VACIA", "mensaje": "x", "componente": ""}],
            "advertencias": [], "metricas": {"superadas": 9, "totales": 9}},
        confianza="alta" if valido else "insuficiente", confianza_motivos=[],
        antecedentes={"codigos_permitidos": ["4279", "6092"],
                      "apus_referencia": [{"codigo": "A1", "turno": "DIURNO"}]},
        modelo="falso", prompt_version="composicion/v2", apu_codigo=None,
        apu_turno=None, autor="t@test.co", creada_en="2026-09-10T10:00:00",
        motivo=None))


# --- GET -------------------------------------------------------------------
def test_get_sin_composicion_devuelve_vacio(app_alm, corrida):
    app, _ = app_alm
    r = cliente(app, "consulta").get(f"/api/corridas/{corrida}/composicion/1")
    assert r.status_code == 200
    assert r.json() == {"vigente": None, "historial": []}


def test_get_devuelve_la_vigente_y_el_historial(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    _sembrar(alm, corrida, version=2, estado="editada")
    d = cliente(app, "consulta").get(
        f"/api/corridas/{corrida}/composicion/1").json()
    assert d["vigente"]["version"] == 2
    assert len(d["historial"]) == 2


def test_get_de_una_fila_inexistente_es_404(app_alm, corrida):
    app, _ = app_alm
    r = cliente(app, "consulta").get(f"/api/corridas/{corrida}/composicion/99")
    assert r.status_code == 404


def test_la_respuesta_del_get_no_lleva_dinero(app_alm, corrida):
    from apu_tool.dominio import privacy
    app, alm = app_alm
    _sembrar(alm, corrida)
    privacy.assert_no_money(
        cliente(app, "consulta").get(f"/api/corridas/{corrida}/composicion/1").json())


# --- PUT (edición humana) --------------------------------------------------
def test_put_guarda_una_version_nueva_y_revalida(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    cuerpo = {"version_base": 1, "componentes": PROPUESTA["componentes"]}
    r = cliente(app, "editor").put(f"/api/corridas/{corrida}/composicion/1",
                                   json=cuerpo)
    assert r.status_code == 200
    assert r.json()["vigente"]["version"] == 2
    assert r.json()["vigente"]["estado"] == "editada"


def test_put_con_una_version_vieja_es_409(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    _sembrar(alm, corrida, version=2, estado="editada")
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": PROPUESTA["componentes"]})
    assert r.status_code == 409


def test_put_acepta_un_insumo_que_agrego_el_humano(app_alm, corrida):
    """La lista blanca frena al MODELO, no a una persona que elige del catálogo."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    nuevo = dict(PROPUESTA["componentes"][0], codigo="6092",
                 funcion="herramienta", rendimiento=1.0, origen="supuesto_tecnico",
                 referencias=[])
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1,
              "componentes": PROPUESTA["componentes"] + [nuevo]})
    assert r.status_code == 200
    errores = r.json()["vigente"]["validacion"]["errores"]
    assert not [e for e in errores if e["codigo"] == "CODIGO_NO_AUTORIZADO"]


def test_put_rechaza_un_codigo_que_no_esta_en_el_catalogo(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    falso = dict(PROPUESTA["componentes"][0], codigo="INVENTADO")
    r = cliente(app, "editor").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": [falso]})
    assert r.status_code == 200      # se guarda, pero inválida
    codigos = {e["codigo"] for e in r.json()["vigente"]["validacion"]["errores"]}
    assert "CODIGO_INEXISTENTE" in codigos or "CODIGO_NO_AUTORIZADO" in codigos
    assert r.json()["vigente"]["validacion"]["valido"] is False


def test_put_necesita_rol_editor(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "consulta").put(
        f"/api/corridas/{corrida}/composicion/1",
        json={"version_base": 1, "componentes": PROPUESTA["componentes"]})
    assert r.status_code == 403


# --- aprobar ---------------------------------------------------------------
CUERPO_APROBAR = {"version_base": 1, "codigo": "9001", "turno": "DIURNO",
                  "nombre": "EXCAVACION MANUAL MATERIAL COMUN",
                  "grupo": "EXCAVACIONES"}


def test_aprobar_crea_el_apu_por_autoria_y_lo_asigna_a_la_fila(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar", json=CUERPO_APROBAR)
    assert r.status_code == 200
    assert alm.apus.get_apu("9001", "DIURNO") is not None
    assert alm.corridas.get_item(corrida, 1).apu_codigo == "9001"
    assert alm.composiciones.vigente(corrida, 1).estado == "aprobada"
    assert alm.composiciones.vigente(corrida, 1).apu_codigo == "9001"


def test_aprobar_dos_veces_no_crea_dos_apus(app_alm, corrida):
    """Criterio 32: el doble clic lo frena el índice único, no un if."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    c = cliente(app, "editor")
    r1 = c.post(f"/api/corridas/{corrida}/composicion/1/aprobar",
                json=CUERPO_APROBAR)
    r2 = c.post(f"/api/corridas/{corrida}/composicion/1/aprobar",
                json=CUERPO_APROBAR)
    assert r1.status_code == 200
    assert r2.status_code == 409
    apus, _ = alm.apus.list_apus(q="9001")
    assert len(apus) == 1


def test_aprobar_con_errores_bloqueantes_es_422(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1, valido=False)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar", json=CUERPO_APROBAR)
    assert r.status_code == 422


def test_aprobar_con_un_codigo_duplicado_sube_el_error_de_autoria(app_alm, corrida):
    """No se reimplementan las reglas de unicidad: son de autoria.py."""
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar",
        json=dict(CUERPO_APROBAR, codigo="A1", nombre="EXCAVACION MANUAL"))
    assert r.status_code == 422
    assert "A1" in r.json()["detail"] or "existe" in r.json()["detail"].lower()


def test_aprobar_necesita_rol_editor(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "consulta").post(
        f"/api/corridas/{corrida}/composicion/1/aprobar", json=CUERPO_APROBAR)
    assert r.status_code == 403


# --- rechazar --------------------------------------------------------------
def test_rechazar_escribe_una_version_y_no_toca_nada_mas(app_alm, corrida):
    app, alm = app_alm
    _sembrar(alm, corrida, version=1)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/rechazar",
        json={"version_base": 1, "motivo": "no aplica"})
    assert r.status_code == 200
    assert alm.composiciones.vigente(corrida, 1).estado == "rechazada"
    assert alm.corridas.get_item(corrida, 1).apu_codigo is None
    assert alm.apus.counts()["apus"] == 1        # no se creó nada


# --- generar (SSE) ---------------------------------------------------------
def test_generar_sin_credencial_es_503(app_alm, corrida, monkeypatch):
    app, _ = app_alm
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/stream")
    assert r.status_code == 503


def test_generar_en_una_corrida_congelada_es_409(app_alm, corrida, monkeypatch):
    app, alm = app_alm
    monkeypatch.setenv("ANTHROPIC_API_KEY", "x")
    alm.corridas.set_modo(corrida, "congelada")
    r = cliente(app, "editor").post(
        f"/api/corridas/{corrida}/composicion/1/stream")
    assert r.status_code == 409


def test_el_endpoint_viejo_de_componer_ya_no_existe(app_alm, corrida):
    app, _ = app_alm
    r = cliente(app, "editor").post(f"/api/corridas/{corrida}/componer/1")
    assert r.status_code == 404
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `python -m pytest tests/test_api_composicion.py -q`
Esperado: FALLA con 404 en todos los endpoints nuevos.

- [ ] **Paso 3a: los DTOs**

En `apu_tool/servicio/esquemas.py`, al final:

```python
class ComponenteComposicionIn(BaseModel):
    """Un componente tal como lo deja el humano en la mesa de revisión."""
    codigo: str
    tipo: str = "insumo"
    funcion: str = ""
    rendimiento: float
    origen: str = "supuesto_tecnico"
    referencias: list[dict] = []
    hipotesis: dict = {}
    calculo: Optional[dict] = None
    justificacion: str = ""
    nivel_evidencia: str = "bajo"
    ref_shift: str = ""


class ComposicionEditarIn(BaseModel):
    # La versión sobre la que trabajó el usuario. Si ya hay una mayor, 409: alguien
    # más la cambió mientras tanto.
    version_base: int
    componentes: list[ComponenteComposicionIn]
    supuestos_confirmados: bool = False


class ComposicionAprobarIn(BaseModel):
    """La identidad del APU la pone el humano; los componentes salen de la versión
    vigente, no del cuerpo: aprobar no es una oportunidad de editar."""
    version_base: int
    codigo: str
    turno: str
    nombre: str
    grupo: str = ""
    unidad: str = ""


class ComposicionRechazarIn(BaseModel):
    version_base: int
    motivo: str = ""
```

- [ ] **Paso 3b: la lógica de servicio**

Crea `apu_tool/servicio/composicion.py`:

```python
"""Servicio de la composición asistida. Hermano de `servicio/corridas.py`.

No importa `pricing`: el agente no ve dinero ni de rebote. La creación del APU pasa
por `servicio/autoria.py` — sus reglas de unicidad, gemelo día/noche y auditoría no se
duplican acá.
"""
from __future__ import annotations

import datetime as _dt
from typing import Optional

from apu_tool.datos.almacen import Almacen
from apu_tool.datos.repositorio import VersionYaExiste
from apu_tool.dominio.ai_assist import PROMPT_VERSION, ApuAdvisor, IANoDisponible
from apu_tool.dominio import privacy
from apu_tool.dominio.composicion import Propuesta, propuesta_desde_json
from apu_tool.dominio.composicion_agente import componer, evaluar, recuperar
from apu_tool.nucleo.models import ComposicionRow
from apu_tool.servicio import autoria
from apu_tool.servicio.corridas import CorridaCongelada, confirmar_item

__all__ = ["CorridaCongelada", "IANoDisponible", "VersionYaExiste",
           "ComposicionInvalida", "vista", "generar_stream", "guardar_edicion",
           "aprobar", "rechazar"]


class ComposicionInvalida(Exception):
    """Se intentó aprobar una composición con errores bloqueantes."""


def _ahora() -> str:
    return _dt.datetime.now().isoformat(timespec="seconds")


def _fila_base(alm: Almacen, corrida_id: int, seq: int, item) -> dict:
    """Los campos que toda versión comparte. `actividad` va DES-MONETIZADA."""
    return {"corrida_id": corrida_id, "seq": seq,
            "actividad": privacy.licitacion_item_to_dict(item), "ficha": None,
            "creada_en": _ahora()}


def vista(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    """La versión vigente y el historial. None si la fila no existe."""
    if alm.corridas.get_item(corrida_id, seq) is None:
        return None
    v = alm.composiciones.vigente(corrida_id, seq)
    return {"vigente": v.to_dict() if v else None,
            "historial": [f.to_dict() for f in
                          alm.composiciones.historial(corrida_id, seq)]}


def _exigir_activa(alm: Almacen, corrida_id: int):
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    return meta


def generar_stream(alm: Almacen, corrida_id: int, seq: int, actor=None):
    """Genera una propuesta y la persiste. Devuelve el generador de eventos SSE.

    Valida ANTES de devolver el generador (corrida congelada, fila inexistente, falta
    de credencial): si no, el error saldría con el stream ya abierto y el cliente
    vería un 200 que muere solo. Mismo criterio que `revisar_corrida_stream`.
    """
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    advisor = ApuAdvisor()
    if not advisor.enabled:
        raise IANoDisponible(
            "Componer un APU con IA necesita ANTHROPIC_API_KEY en el servidor.")
    vigente = alm.composiciones.vigente(corrida_id, seq)
    proxima = (vigente.version + 1) if vigente else 1
    return _eventos(alm, corrida_id, seq, row, advisor, proxima, actor)


def _eventos(alm, corrida_id, seq, row, advisor, version, actor):
    for evento, payload in componer(alm, row.item, advisor):
        if evento == "lista":
            fila = ComposicionRow(
                id=None, version=version, estado="propuesta",
                propuesta=payload["propuesta"], validacion=payload["validacion"],
                confianza=payload["confianza"],
                confianza_motivos=payload["confianza_motivos"],
                antecedentes=payload["antecedentes"], modelo=payload["modelo"],
                prompt_version=payload["prompt_version"], apu_codigo=None,
                apu_turno=None, autor=(actor.email if actor else None), motivo=None,
                **_fila_base(alm, corrida_id, seq, row.item))
            alm.composiciones.agregar(fila)
            yield ("lista", {**payload, "version": version})
            continue
        if evento == "error":
            alm.composiciones.agregar(ComposicionRow(
                id=None, version=version, estado="error", propuesta=None,
                validacion=None, confianza=None, confianza_motivos=None,
                antecedentes=None, modelo=advisor.model,
                prompt_version=PROMPT_VERSION, apu_codigo=None, apu_turno=None,
                autor=(actor.email if actor else None), motivo=payload["detail"],
                **_fila_base(alm, corrida_id, seq, row.item)))
        yield (evento, payload)


def _revalidar(alm, corrida_id, seq, row, componentes, supuestos_confirmados,
               vigente):
    """Recalcula y valida una propuesta EDITADA A MANO, sin llamar a la IA.

    La lista blanca de la generación frena al MODELO; una persona que agrega un
    componente desde el buscador del catálogo no está inventando nada, así que la
    lista se AMPLÍA con lo que mandó. El guardián que queda es `CODIGO_INEXISTENTE`,
    que es el correcto para una adición humana.
    """
    from dataclasses import replace

    previos = set((vigente.antecedentes or {}).get("codigos_permitidos", []))
    ctx = recuperar(alm, row.item, supuestos_confirmados=supuestos_confirmados)
    permitidos = previos | {c["codigo"] for c in componentes} | \
        ctx.validacion.codigos_permitidos
    ctxv = replace(ctx.validacion, codigos_permitidos=frozenset(permitidos),
                   supuestos_confirmados=supuestos_confirmados)
    base = dict(vigente.propuesta or {})
    base["componentes"] = componentes
    return evaluar(propuesta_desde_json(base), ctxv), ctx


def guardar_edicion(alm: Almacen, corrida_id: int, seq: int, datos: dict,
                    actor=None) -> Optional[dict]:
    """Escribe una versión `editada`. Levanta VersionYaExiste si alguien se adelantó."""
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    vigente = alm.composiciones.vigente(corrida_id, seq)
    if row is None or vigente is None:
        return None
    version = int(datos["version_base"]) + 1
    (propuesta, validacion, confianza), ctx = _revalidar(
        alm, corrida_id, seq, row, datos["componentes"],
        bool(datos.get("supuestos_confirmados")), vigente)
    alm.composiciones.agregar(ComposicionRow(
        id=None, version=version, estado="editada", propuesta=propuesta.to_dict(),
        validacion=validacion.to_dict(), confianza=confianza.nivel,
        confianza_motivos=[m.to_dict() for m in confianza.motivos],
        antecedentes={"codigos_permitidos": sorted(ctx.validacion.codigos_permitidos),
                      "apus_referencia": (vigente.antecedentes or {}).get(
                          "apus_referencia", [])},
        modelo=vigente.modelo, prompt_version=vigente.prompt_version,
        apu_codigo=None, apu_turno=None,
        autor=(actor.email if actor else None), motivo=None,
        **_fila_base(alm, corrida_id, seq, row.item)))
    return vista(alm, corrida_id, seq)


def aprobar(alm: Almacen, corrida_id: int, seq: int, datos: dict,
            actor=None) -> Optional[dict]:
    """Crea el APU por autoría, sella la versión `aprobada` y lo asigna a la fila.

    Los componentes salen de la versión VIGENTE, no del cuerpo: aprobar no es una
    oportunidad de editar (para eso está el PUT, que revalida). Del cuerpo viene solo
    la identidad, que es lo que el humano elige.

    Costura conocida: `crear_apu` escribe en apus.db y el sellado en corridas.db —
    dos archivos SQLite, sin transacción común. Si lo segundo falla, el APU existe y
    la fila no lo tiene; se avisa, nunca en silencio.
    """
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    vigente = alm.composiciones.vigente(corrida_id, seq)
    if row is None or vigente is None:
        return None
    if vigente.estado == "aprobada":
        raise VersionYaExiste(corrida_id, seq, vigente.version)
    if not (vigente.validacion or {}).get("valido"):
        raise ComposicionInvalida(
            "La composición tiene errores que impiden aprobarla. Corregilos en la "
            "mesa de revisión y volvé a guardar.")

    version = int(datos["version_base"]) + 1
    comps = (vigente.propuesta or {}).get("componentes", [])
    apu = autoria.crear_apu(alm, {
        "codigo": datos["codigo"], "turno": datos["turno"],
        "nombre": datos["nombre"], "grupo": datos.get("grupo", ""),
        "unidad": datos.get("unidad") or row.item.unidad,
        "componentes": [{"insumo_codigo": c["codigo"],
                         "rendimiento": c["rendimiento"],
                         "tipo": c.get("tipo", "insumo"),
                         "ref_shift": c.get("ref_shift", "")} for c in comps],
    }, actor=actor)
    alm.composiciones.agregar(ComposicionRow(
        id=None, version=version, estado="aprobada", propuesta=vigente.propuesta,
        validacion=vigente.validacion, confianza=vigente.confianza,
        confianza_motivos=vigente.confianza_motivos,
        antecedentes=vigente.antecedentes, modelo=vigente.modelo,
        prompt_version=vigente.prompt_version, apu_codigo=apu["codigo"],
        apu_turno=apu["turno"], autor=(actor.email if actor else None), motivo=None,
        **_fila_base(alm, corrida_id, seq, row.item)))
    confirmar_item(alm, corrida_id, seq, apu["codigo"], apu["turno"])
    return vista(alm, corrida_id, seq)


def rechazar(alm: Almacen, corrida_id: int, seq: int, datos: dict,
             actor=None) -> Optional[dict]:
    """Sella una versión `rechazada`. No toca corrida, biblioteca ni catálogo."""
    if _exigir_activa(alm, corrida_id) is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    vigente = alm.composiciones.vigente(corrida_id, seq)
    if row is None or vigente is None:
        return None
    alm.composiciones.agregar(ComposicionRow(
        id=None, version=int(datos["version_base"]) + 1, estado="rechazada",
        propuesta=vigente.propuesta, validacion=vigente.validacion,
        confianza=vigente.confianza, confianza_motivos=vigente.confianza_motivos,
        antecedentes=vigente.antecedentes, modelo=vigente.modelo,
        prompt_version=vigente.prompt_version, apu_codigo=None, apu_turno=None,
        autor=(actor.email if actor else None),
        motivo=str(datos.get("motivo") or ""),
        **_fila_base(alm, corrida_id, seq, row.item)))
    return vista(alm, corrida_id, seq)
```

- [ ] **Paso 3c: las rutas**

En `apu_tool/servicio/rutas.py`, **borra** el endpoint
`@router.post("/corridas/{cid}/componer/{seq}")` completo y agrega:

```python
@router.get("/corridas/{cid}/composicion/{seq}")
def get_composicion(cid: int, seq: int, alm: Almacen = Depends(get_almacen),
                    _: object = Depends(requiere_rol("consulta"))):
    d = comp_svc.vista(alm, cid, seq)
    if d is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return d


@router.post("/corridas/{cid}/composicion/{seq}/stream")
def generar_composicion(cid: int, seq: int, alm: Almacen = Depends(get_almacen),
                        actor=Depends(requiere_rol("editor"))):
    """Compone un APU con IA para una fila sin APU. Propone; no crea nada."""
    try:
        gen = comp_svc.generar_stream(alm, cid, seq, actor=actor)
    except comp_svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; activala para componer.")
    except comp_svc.IANoDisponible as e:
        raise HTTPException(status_code=503, detail=str(e))
    if gen is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return StreamingResponse(_event_stream(gen), media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache"})


@router.put("/corridas/{cid}/composicion/{seq}")
def editar_composicion(cid: int, seq: int, body: ComposicionEditarIn,
                       alm: Almacen = Depends(get_almacen),
                       actor=Depends(requiere_rol("editor"))):
    try:
        d = comp_svc.guardar_edicion(alm, cid, seq, body.model_dump(), actor=actor)
    except comp_svc.CorridaCongelada:
        raise HTTPException(status_code=409, detail="La corrida está congelada.")
    except comp_svc.VersionYaExiste as e:
        raise HTTPException(status_code=409, detail=str(e))
    if d is None:
        raise HTTPException(status_code=404, detail="Composición no encontrada.")
    return d


@router.post("/corridas/{cid}/composicion/{seq}/aprobar")
def aprobar_composicion(cid: int, seq: int, body: ComposicionAprobarIn,
                        alm: Almacen = Depends(get_almacen),
                        actor=Depends(requiere_rol("editor"))):
    """Crea el APU por el alta de siempre y lo asigna a la fila."""
    try:
        d = comp_svc.aprobar(alm, cid, seq, body.model_dump(), actor=actor)
    except comp_svc.CorridaCongelada:
        raise HTTPException(status_code=409, detail="La corrida está congelada.")
    except comp_svc.VersionYaExiste as e:
        raise HTTPException(status_code=409, detail=str(e))
    except comp_svc.ComposicionInvalida as e:
        raise HTTPException(status_code=422, detail=str(e))
    except ValueError as e:            # las reglas de autoria.py, tal cual
        raise HTTPException(status_code=422, detail=str(e))
    if d is None:
        raise HTTPException(status_code=404, detail="Composición no encontrada.")
    return d


@router.post("/corridas/{cid}/composicion/{seq}/rechazar")
def rechazar_composicion(cid: int, seq: int, body: ComposicionRechazarIn,
                         alm: Almacen = Depends(get_almacen),
                         actor=Depends(requiere_rol("editor"))):
    try:
        d = comp_svc.rechazar(alm, cid, seq, body.model_dump(), actor=actor)
    except comp_svc.CorridaCongelada:
        raise HTTPException(status_code=409, detail="La corrida está congelada.")
    except comp_svc.VersionYaExiste as e:
        raise HTTPException(status_code=409, detail=str(e))
    if d is None:
        raise HTTPException(status_code=404, detail="Composición no encontrada.")
    return d
```

Imports a agregar arriba de `rutas.py`:

```python
from apu_tool.servicio import composicion as comp_svc
from apu_tool.servicio.esquemas import (
    ComposicionAprobarIn, ComposicionEditarIn, ComposicionRechazarIn,
)
```

**Ojo con `requiere_rol`:** hoy se usa como `_: object = Depends(requiere_rol("editor"))`
y se descarta. Acá se necesita el actor para la auditoría y el campo `autor`. Verificá
que `requiere_rol` devuelva el `Perfil`; si no, usá el mismo patrón que ya usan los
endpoints de autoría para obtener el actor y ajustá estas firmas en consecuencia.

- [ ] **Paso 3d: borrar `componer_item` del servicio de corridas**

En `apu_tool/servicio/corridas.py`, borra la función `componer_item` completa y el
import de `ApuAdvisor` si queda sin uso.

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
python -m pytest tests/test_api_composicion.py -q
python -m pytest tests/ -q 2>&1 | tail -3
```

Esperado: `20 passed` en el primero, y **cero fallos** en la suite completa.

- [ ] **Paso 5: commit**

```bash
git add apu_tool/servicio/composicion.py apu_tool/servicio/rutas.py \
        apu_tool/servicio/esquemas.py apu_tool/servicio/corridas.py \
        tests/test_api_composicion.py
git commit -m "feat(servicio): cinco endpoints de composicion; aprobar pasa por autoria"
```

---

## Tarea 11: cliente y tipos del frontend

Reusa `consumirSse` de `api/corridas.ts` (el mismo que usa la revisión): no se escribe
un lector de streams nuevo.

**Archivos:**
- Crear: `web/src/api/composicion.ts`, `web/src/api/composicion.test.ts`
- Modificar: `web/src/lib/tipos.ts`, `web/src/api/corridas.ts` (exportar `consumirSse`)

- [ ] **Paso 1: escribir la prueba que falla**

Crea `web/src/api/composicion.test.ts`:

```ts
import { beforeEach, expect, test, vi } from "vitest";

const apiGet = vi.fn();
const apiPut = vi.fn();
const apiPost = vi.fn();
const consumirSse = vi.fn();

vi.mock("./client", () => ({
  apiGet: (...a: unknown[]) => apiGet(...a),
  apiPut: (...a: unknown[]) => apiPut(...a),
  apiPost: (...a: unknown[]) => apiPost(...a),
}));
vi.mock("./corridas", () => ({
  consumirSse: (...a: unknown[]) => consumirSse(...a),
}));

beforeEach(() => {
  apiGet.mockReset().mockResolvedValue({ vigente: null, historial: [] });
  apiPut.mockReset().mockResolvedValue({ vigente: null, historial: [] });
  apiPost.mockReset().mockResolvedValue({ vigente: null, historial: [] });
  consumirSse.mockReset().mockResolvedValue(undefined);
});

test("getComposicion pega al GET de la fila", async () => {
  const { getComposicion } = await import("./composicion");
  await getComposicion(7, 3);
  expect(apiGet).toHaveBeenCalledWith("/corridas/7/composicion/3");
});

test("guardarComposicion manda version_base y componentes", async () => {
  const { guardarComposicion } = await import("./composicion");
  await guardarComposicion(7, 3, 2, [{ codigo: "4279", rendimiento: 0.5 }] as never, true);
  expect(apiPut).toHaveBeenCalledWith("/corridas/7/composicion/3", {
    version_base: 2,
    componentes: [{ codigo: "4279", rendimiento: 0.5 }],
    supuestos_confirmados: true,
  });
});

test("aprobarComposicion manda la identidad del APU", async () => {
  const { aprobarComposicion } = await import("./composicion");
  await aprobarComposicion(7, 3, {
    version_base: 2, codigo: "9001", turno: "DIURNO", nombre: "X", grupo: "G",
    unidad: "M3",
  });
  expect(apiPost).toHaveBeenCalledWith("/corridas/7/composicion/3/aprobar", {
    version_base: 2, codigo: "9001", turno: "DIURNO", nombre: "X", grupo: "G",
    unidad: "M3",
  });
});

test("rechazarComposicion manda el motivo", async () => {
  const { rechazarComposicion } = await import("./composicion");
  await rechazarComposicion(7, 3, 2, "no aplica");
  expect(apiPost).toHaveBeenCalledWith("/corridas/7/composicion/3/rechazar", {
    version_base: 2, motivo: "no aplica",
  });
});

test("generarComposicionStream usa el SSE con POST", async () => {
  const { generarComposicionStream } = await import("./composicion");
  await generarComposicionStream(7, 3, () => {});
  expect(consumirSse).toHaveBeenCalled();
  const [path, init] = consumirSse.mock.calls[0];
  expect(path).toBe("/corridas/7/composicion/3/stream");
  expect((init as { method: string }).method).toBe("POST");
});

test("los eventos del stream llegan tipados al callback", async () => {
  // OJO: `consumirSse` entrega `{ event, data }` (en inglés), no `{ evento, datos }`.
  // Es el contrato que ya usa `revisarCorridaStream`; no se renombra por capricho.
  consumirSse.mockImplementation(
    async (_p: string, _i: unknown, onEvent: (e: { event: string; data: unknown }) => void) => {
      onEvent({ event: "recuperando", data: { n_insumos: 40, n_apus: 3 } });
      onEvent({ event: "lista", data: { version: 1 } });
    },
  );
  const { generarComposicionStream } = await import("./composicion");
  const vistos: string[] = [];
  await generarComposicionStream(7, 3, (e) => vistos.push(e.event));
  expect(vistos).toEqual(["recuperando", "lista"]);
});
```

- [ ] **Paso 2: correr la prueba para verificar que falla**

Ejecuta: `cd web && npx vitest run src/api/composicion.test.ts`
Esperado: FALLA con `Failed to resolve import "./composicion"`

- [ ] **Paso 3a: exportar `consumirSse`**

En `web/src/api/corridas.ts`, cambia `async function consumirSse(` por
`export async function consumirSse(`. Es la misma plomería de fetch + auth + lectura
del stream que ya usa la revisión; escribir otra sería duplicarla.

- [ ] **Paso 3b: los tipos**

En `web/src/lib/tipos.ts`, **reemplaza** `ComposicionPropuesta` y
`ComponenteComposicion` (el contrato viejo de dos campos ya no existe) por:

```ts
/** Un componente propuesto, con todo lo que lo explica. Espejo del contrato de
 *  `apu_tool/dominio/composicion.py`. Ningún campo es monetario, a propósito. */
export interface ComponentePropuesto {
  codigo: string;
  tipo: "insumo" | "apu";
  funcion: string;              // "" = la IA no dijo un rol legible
  rendimiento: number;
  origen: string;
  referencias: { apu_codigo: string; turno: string }[];
  hipotesis: Record<string, unknown>;
  calculo: {
    operacion: string; numerador: number; denominador: number; resultado: number;
  } | null;
  justificacion: string;
  nivel_evidencia: "alto" | "medio" | "bajo";
  ref_shift: string;
}

export interface Hallazgo {
  codigo: string;
  mensaje: string;
  componente: string;           // "" = hallazgo del conjunto, no de un componente
}

export interface ValidacionComposicion {
  valido: boolean;
  errores: Hallazgo[];
  advertencias: Hallazgo[];
  metricas: { superadas: number; totales: number };
}

/** El nivel lo calcula la plataforma. `incertidumbre_declarada` (lo que el modelo
 *  dice de sí mismo) va aparte y NO influye: se muestra rotulada como dato suyo. */
export type NivelConfianza = "alta" | "media" | "baja" | "insuficiente";

export interface MotivoConfianza {
  senal: string;
  /** `detalle` y no `valor`: "valor" está en la denylist de privacidad del backend
   *  (por valor_unitario / valor_total) y el guardián mira nombres de clave. */
  detalle: string;
  aporte: number;
}

export interface ComposicionVersion {
  corrida_id: number;
  seq: number;
  version: number;
  estado: "generando" | "propuesta" | "editada" | "aprobada" | "rechazada" | "error";
  actividad: {
    item: string; descripcion: string; unidad: string; cantidad: number; shift: string;
  };
  ficha: null;                  // fase 2
  propuesta: {
    componentes: ComponentePropuesto[];
    supuestos: { campo: string; supuesto: string; impacto: string }[];
    incertidumbre_declarada: number;
    justificacion: string;
  } | null;
  validacion: ValidacionComposicion | null;
  confianza: NivelConfianza | null;
  confianza_motivos: MotivoConfianza[] | null;
  antecedentes: {
    codigos_permitidos: string[];
    apus_referencia: { codigo: string; turno: string }[];
  } | null;
  modelo: string | null;
  prompt_version: string | null;
  apu_codigo: string | null;
  apu_turno: string | null;
  autor: string | null;
  creada_en: string;
  motivo: string | null;
}

export interface VistaComposicion {
  vigente: ComposicionVersion | null;
  historial: ComposicionVersion[];
}
```

- [ ] **Paso 3c: el cliente**

Crea `web/src/api/composicion.ts`:

```ts
import { apiGet, apiPost, apiPut } from "./client";
import { consumirSse } from "./corridas";
import type { ComponentePropuesto, VistaComposicion } from "@/lib/tipos";

/** La versión vigente y el historial. Es lo que hace que recargar la página funcione:
 *  la propuesta vive en la base, no en el estado del navegador. */
export function getComposicion(id: number, seq: number): Promise<VistaComposicion> {
  return apiGet<VistaComposicion>(`/corridas/${id}/composicion/${seq}`);
}

/** Guarda la edición humana. `versionBase` es la versión sobre la que se trabajó: si
 *  alguien se adelantó, el servidor devuelve 409 en vez de pisarla. */
export function guardarComposicion(
  id: number,
  seq: number,
  versionBase: number,
  componentes: ComponentePropuesto[],
  supuestosConfirmados: boolean,
): Promise<VistaComposicion> {
  return apiPut<VistaComposicion>(`/corridas/${id}/composicion/${seq}`, {
    version_base: versionBase,
    componentes,
    supuestos_confirmados: supuestosConfirmados,
  });
}

export interface IdentidadApu {
  version_base: number;
  codigo: string;
  turno: string;
  nombre: string;
  grupo: string;
  unidad: string;
}

/** Crea el APU por el alta de siempre y lo asigna a la fila. La IA nunca escribe en
 *  la biblioteca: este endpoint lo dispara una persona. */
export function aprobarComposicion(
  id: number, seq: number, identidad: IdentidadApu,
): Promise<VistaComposicion> {
  return apiPost<VistaComposicion>(
    `/corridas/${id}/composicion/${seq}/aprobar`, identidad);
}

export function rechazarComposicion(
  id: number, seq: number, versionBase: number, motivo: string,
): Promise<VistaComposicion> {
  return apiPost<VistaComposicion>(`/corridas/${id}/composicion/${seq}/rechazar`, {
    version_base: versionBase,
    motivo,
  });
}

/** La forma que entrega `consumirSse`: `event` y `data`, en inglés. Es el contrato que
 *  ya consume `revisarCorridaStream` — renombrarlo acá obligaría a tocar el lector de
 *  streams, que funciona y es compartido. */
export interface EventoComposicion {
  event: string;
  data: unknown;
}

/** Genera la propuesta por SSE. Si la conexión se corta, la propuesta igual quedó
 *  guardada: recargar la página la levanta. */
export function generarComposicionStream(
  id: number,
  seq: number,
  onEvent: (e: EventoComposicion) => void,
): Promise<void> {
  return consumirSse(
    `/corridas/${id}/composicion/${seq}/stream`, { method: "POST" }, onEvent);
}
```

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
cd web && npx vitest run src/api/composicion.test.ts
```

Esperado: `6 passed`

- [ ] **Paso 5: commit**

```bash
git add web/src/api/composicion.ts web/src/api/composicion.test.ts \
        web/src/api/corridas.ts web/src/lib/tipos.ts
git commit -m "feat(web): cliente y tipos de la composicion, sobre el SSE que ya existe"
```

---

## Tarea 12: la mesa de revisión y la puerta de entrada

La página con URL propia y el disparador nuevo. Acá muere `DialogoComposicion.tsx`.

**La fase 0 va en este commit y no antes**, a propósito: cambiar el disparador sobre un
modal que vamos a borrar es trabajo tirado.

**Archivos:**
- Crear: `web/src/pages/Composicion.tsx`, `web/src/pages/Composicion.test.tsx`
- Modificar: `web/src/App.tsx` (la ruta),
  `web/src/components/corrida/TablaItems.tsx` (el disparador)
- Borrar: `web/src/components/corrida/DialogoComposicion.tsx`,
  `web/src/components/corrida/DialogoComposicion.test.tsx`

- [ ] **Paso 1: escribir la prueba que falla**

Crea `web/src/pages/Composicion.test.tsx`:

```tsx
import { render, screen, waitFor } from "@testing-library/react";
import userEvent from "@testing-library/user-event";
import { beforeEach, expect, test, vi } from "vitest";
import { MemoryRouter, Route, Routes } from "react-router-dom";

const getComposicion = vi.fn();
const guardarComposicion = vi.fn();
const aprobarComposicion = vi.fn();
const rechazarComposicion = vi.fn();
const generarComposicionStream = vi.fn();

vi.mock("@/api/composicion", () => ({
  getComposicion: (...a: unknown[]) => getComposicion(...a),
  guardarComposicion: (...a: unknown[]) => guardarComposicion(...a),
  aprobarComposicion: (...a: unknown[]) => aprobarComposicion(...a),
  rechazarComposicion: (...a: unknown[]) => rechazarComposicion(...a),
  generarComposicionStream: (...a: unknown[]) => generarComposicionStream(...a),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "editor" } }) }));

const COMPONENTE = {
  codigo: "4279", tipo: "insumo", funcion: "mano_de_obra", rendimiento: 0.62,
  origen: "copiado_de_antecedente",
  referencias: [{ apu_codigo: "A1", turno: "DIURNO" }], hipotesis: {},
  calculo: null, justificacion: "Cuadrilla de antecedentes", nivel_evidencia: "alto",
  ref_shift: "",
};

function vista(over: Record<string, unknown> = {}) {
  const vigente = {
    corrida_id: 7, seq: 3, version: 1, estado: "propuesta",
    actividad: { item: "1.3", descripcion: "EXCAVACION MANUAL", unidad: "M3",
                 cantidad: 120, shift: "DIURNO" },
    ficha: null,
    propuesta: { componentes: [COMPONENTE], supuestos: [],
                 incertidumbre_declarada: 0.35, justificacion: "g" },
    validacion: { valido: true, errores: [], advertencias: [],
                  metricas: { superadas: 11, totales: 11 } },
    confianza: "media",
    confianza_motivos: [{ senal: "respaldo_de_componentes", detalle: "1 de 1",
                          aporte: 2 }],
    antecedentes: { codigos_permitidos: ["4279"],
                    apus_referencia: [{ codigo: "A1", turno: "DIURNO" }] },
    modelo: "claude-sonnet-5", prompt_version: "composicion/v2", apu_codigo: null,
    apu_turno: null, autor: "t@test.co", creada_en: "2026-09-10T10:00:00",
    motivo: null, ...over,
  };
  return { vigente, historial: [vigente] };
}

function montar() {
  return render(
    <MemoryRouter initialEntries={["/corridas/7/componer/3"]}>
      <Routes>
        <Route path="/corridas/:id/componer/:seq" element={<Pagina />} />
      </Routes>
    </MemoryRouter>,
  );
}

let Pagina: React.ComponentType;

beforeEach(async () => {
  getComposicion.mockReset().mockResolvedValue(vista());
  guardarComposicion.mockReset().mockResolvedValue(vista({ version: 2 }));
  aprobarComposicion.mockReset().mockResolvedValue(vista({ estado: "aprobada" }));
  rechazarComposicion.mockReset().mockResolvedValue(vista({ estado: "rechazada" }));
  generarComposicionStream.mockReset().mockResolvedValue(undefined);
  Pagina = (await import("./Composicion")).default;
});

test("al abrir levanta la composicion guardada", async () => {
  montar();
  await waitFor(() => expect(getComposicion).toHaveBeenCalledWith(7, 3));
  expect(await screen.findByText(/EXCAVACION MANUAL/)).toBeTruthy();
});

test("pinta los componentes con su origen y justificacion", async () => {
  montar();
  expect(await screen.findByText("4279")).toBeTruthy();
  expect(screen.getByText(/copiado_de_antecedente/)).toBeTruthy();
});

test("muestra el nivel de confianza calculado y su desglose", async () => {
  montar();
  expect(await screen.findByText(/MEDIA/i)).toBeTruthy();
  await userEvent.click(screen.getByRole("button", { name: /por qué/i }));
  expect(screen.getByText(/respaldo_de_componentes/)).toBeTruthy();
});

test("la incertidumbre del modelo se muestra rotulada como suya", async () => {
  montar();
  expect(await screen.findByText(/el modelo declara/i)).toBeTruthy();
});

test("editar un rendimiento y guardar manda la version base", async () => {
  montar();
  const campo = await screen.findByLabelText(/rendimiento de 4279/i);
  await userEvent.clear(campo);
  await userEvent.type(campo, "0.8");
  await userEvent.click(screen.getByRole("button", { name: /guardar cambios/i }));
  await waitFor(() => expect(guardarComposicion).toHaveBeenCalled());
  const [, , versionBase, comps] = guardarComposicion.mock.calls[0];
  expect(versionBase).toBe(1);
  expect((comps as { rendimiento: number }[])[0].rendimiento).toBe(0.8);
});

test("borrar un componente lo saca de lo que se guarda", async () => {
  montar();
  await userEvent.click(await screen.findByRole("button",
    { name: /quitar 4279/i }));
  await userEvent.click(screen.getByRole("button", { name: /guardar cambios/i }));
  await waitFor(() => expect(guardarComposicion).toHaveBeenCalled());
  expect(guardarComposicion.mock.calls[0][3]).toEqual([]);
});

test("con errores bloqueantes no se puede aprobar", async () => {
  getComposicion.mockResolvedValue(vista({
    validacion: { valido: false,
      errores: [{ codigo: "CODIGO_INEXISTENTE", mensaje: "no existe",
                  componente: "4279" }],
      advertencias: [], metricas: { superadas: 10, totales: 11 } },
    confianza: "insuficiente",
  }));
  montar();
  const boton = await screen.findByRole("button", { name: /aprobar/i });
  expect((boton as HTMLButtonElement).disabled).toBe(true);
  expect(screen.getByText(/no existe/)).toBeTruthy();
});

test("con solo advertencias si se puede aprobar", async () => {
  getComposicion.mockResolvedValue(vista({
    validacion: { valido: true, errores: [],
      advertencias: [{ codigo: "RENDIMIENTO_ATIPICO", mensaje: "42 % fuera",
                       componente: "4279" }],
      metricas: { superadas: 10, totales: 11 } },
  }));
  montar();
  const boton = await screen.findByRole("button", { name: /aprobar/i });
  expect((boton as HTMLButtonElement).disabled).toBe(false);
  expect(screen.getByText(/42 % fuera/)).toBeTruthy();
});

test("sin composicion ofrece generar y no la pide sola", async () => {
  getComposicion.mockResolvedValue({ vigente: null, historial: [] });
  montar();
  expect(await screen.findByRole("button", { name: /generar propuesta/i })).toBeTruthy();
  expect(generarComposicionStream).not.toHaveBeenCalled();
});

test("generar muestra el avance por etapas", async () => {
  getComposicion.mockResolvedValue({ vigente: null, historial: [] });
  generarComposicionStream.mockImplementation(
    async (_i: number, _s: number, onEvent: (e: { event: string; data: unknown }) => void) => {
      onEvent({ event: "recuperando", data: { n_insumos: 40, n_apus: 3 } });
      onEvent({ event: "generando", data: {} });
    },
  );
  montar();
  await userEvent.click(await screen.findByRole("button",
    { name: /generar propuesta/i }));
  await waitFor(() => expect(screen.getByText(/antecedentes/i)).toBeTruthy());
});

test("rechazar no crea nada y vuelve", async () => {
  montar();
  await userEvent.click(await screen.findByRole("button", { name: /rechazar/i }));
  await waitFor(() => expect(rechazarComposicion).toHaveBeenCalled());
  expect(aprobarComposicion).not.toHaveBeenCalled();
});

test("un lector de solo consulta no ve las acciones que escriben", async () => {
  vi.doMock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "consulta" } }) }));
  vi.resetModules();
  const Solo = (await import("./Composicion")).default;
  render(
    <MemoryRouter initialEntries={["/corridas/7/componer/3"]}>
      <Routes><Route path="/corridas/:id/componer/:seq" element={<Solo />} /></Routes>
    </MemoryRouter>,
  );
  await screen.findByText(/EXCAVACION MANUAL/);
  expect(screen.queryByRole("button", { name: /aprobar/i })).toBeNull();
});
```

Y en `web/src/components/corrida/TablaItems.test.tsx`, en el bloque de Componer (junto
a `test("con dictamen sin_apu y rol editor aparece Componer")`, que es el caso hermano
y hoy pasa), agrega la puerta de entrada nueva. Los cuatro tests que ya están siguen
valiendo tal cual: `sin_apu` con editor sigue ofreciendo, sin editor no, y congelada no.

```tsx
// ─── Fase 0: componer sale de cualquier fila sin APU ─────────────────────────
// Antes el botón exigía haber corrido la revisión con IA sobre TODA la corrida para
// que apareciera en una sola fila. Ahora una fila que el determinístico no resolvió
// lo ofrece por sí sola.

const boton = () => screen.queryByRole("button", { name: /^Componer$/ });

test("una fila sin APU ofrece componer sin haber corrido la revisión", () => {
  render(
    <TablaItems corridaId={1}
      items={[{ ...ITEM, apu_codigo: null, revision: null, costo_manual: null }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar />,
  );
  expect(boton()).toBeTruthy();
});

test("una fila con APU asignado y sin veredicto no ofrece componer", () => {
  // El determinístico resolvió: la IA no rehace lo que ya está bien (invariante 2).
  render(
    <TablaItems corridaId={1}
      items={[{ ...ITEM, apu_codigo: "3010", revision: null, costo_manual: null }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar />,
  );
  expect(boton()).toBeNull();
});

test("una fila con costo puesto a mano no ofrece componer", () => {
  // Proyectos especiales: la línea ya declaró su costo, no necesita APU.
  render(
    <TablaItems corridaId={1}
      items={[{ ...ITEM, apu_codigo: null, revision: null, costo_manual: 250000 }]}
      onConfirmado={() => {}} onComponer={() => {}} puedeEditar />,
  );
  expect(boton()).toBeNull();
});

test("componer avisa al padre con el seq, no navega solo", () => {
  // TablaItems se monta SIN Router en estos tests: la navegación es del padre.
  const onComponer = vi.fn();
  render(
    <TablaItems corridaId={1}
      items={[{ ...ITEM, seq: 4, apu_codigo: null, revision: null,
                costo_manual: null }]}
      onConfirmado={() => {}} onComponer={onComponer} puedeEditar />,
  );
  boton()!.click();
  expect(onComponer).toHaveBeenCalledWith(4);
});
```

Los cuatro tests de Componer que ya existen necesitan la prop nueva: agregales
`onComponer={() => {}}`.

- [ ] **Paso 2: correr las pruebas para verificar que fallan**

```bash
cd web && npx vitest run src/pages/Composicion.test.tsx
```

Esperado: FALLA con `Failed to resolve import "./Composicion"`

- [ ] **Paso 3a: la página**

Crea `web/src/pages/Composicion.tsx`. Densa, table-first, sin cards (la convención de
este repo). La estructura:

```tsx
import { useCallback, useEffect, useMemo, useState } from "react";
import { useNavigate, useParams } from "react-router-dom";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { useAuth } from "@/lib/auth";
import { puede } from "@/components/rutas";
import {
  aprobarComposicion, generarComposicionStream, getComposicion,
  guardarComposicion, rechazarComposicion,
} from "@/api/composicion";
import type {
  ComponentePropuesto, NivelConfianza, VistaComposicion,
} from "@/lib/tipos";

const ETIQUETA_ETAPA: Record<string, string> = {
  recuperando: "Buscando antecedentes en la biblioteca…",
  generando: "La IA está armando la propuesta…",
  validando: "Recalculando y validando…",
};

const COLOR_CONFIANZA: Record<NivelConfianza, string> = {
  alta: "text-ok", media: "text-revisar", baja: "text-revisar",
  insuficiente: "text-destructive",
};

/** Mesa de revisión de una composición asistida.
 *
 *  La propuesta vive en la BASE, no en este componente: recargar la página la levanta
 *  igual, y una conexión que se corta a mitad de la generación no la pierde. Lo único
 *  que es estado local son las ediciones sin guardar.
 *
 *  La IA no ve precios y esta pantalla tampoco los muestra: acá se decide la
 *  ESTRUCTURA del APU. El costo aparece cuando el motor determinístico lo calcula,
 *  después de crear el APU. */
export default function Composicion() {
  const { id, seq } = useParams();
  const corridaId = Number(id);
  const fila = Number(seq);
  const navegar = useNavigate();
  const { perfil } = useAuth();
  const puedeEditar = puede(perfil?.rol, "editor");

  const [vista, setVista] = useState<VistaComposicion | null>(null);
  const [borrador, setBorrador] = useState<ComponentePropuesto[] | null>(null);
  const [etapa, setEtapa] = useState<string | null>(null);
  const [ocupado, setOcupado] = useState(false);
  const [verMotivos, setVerMotivos] = useState(false);

  const cargar = useCallback(async () => {
    const v = await getComposicion(corridaId, fila);
    setVista(v);
    setBorrador(v.vigente?.propuesta?.componentes ?? null);
  }, [corridaId, fila]);

  useEffect(() => { void cargar(); }, [cargar]);

  const vigente = vista?.vigente ?? null;
  const validacion = vigente?.validacion ?? null;
  const componentes = borrador ?? [];
  const sucio = useMemo(
    () => JSON.stringify(componentes) !==
      JSON.stringify(vigente?.propuesta?.componentes ?? []),
    [componentes, vigente],
  );

  async function conError(fn: () => Promise<VistaComposicion>) {
    setOcupado(true);
    try {
      const v = await fn();
      setVista(v);
      setBorrador(v.vigente?.propuesta?.componentes ?? null);
      return v;
    } catch (e) {
      // El mensaje es el del backend (409 versión vieja, 422 reglas de autoría,
      // 503 sin credencial): dice qué hacer, y un texto propio lo taparía.
      toast.error(e instanceof Error ? e.message : "No se pudo completar la acción.");
      return null;
    } finally {
      setOcupado(false);
    }
  }

  async function generar() {
    setOcupado(true);
    setEtapa("recuperando");
    try {
      await generarComposicionStream(corridaId, fila, (ev) => {
        if (ev.event === "error") {
          toast.error((ev.data as { detail: string }).detail);
          setEtapa(null);
          return;
        }
        setEtapa(ev.event === "lista" ? null : ev.event);
      });
      await cargar();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "Se cortó la generación.");
      await cargar();   // pudo haberse guardado igual
    } finally {
      setEtapa(null);
      setOcupado(false);
    }
  }

  // …render: cabecera con la actividad y "Volver a la corrida"; panel de confianza
  // con el desglose desplegable y la incertidumbre del modelo rotulada aparte;
  // bloques de errores y advertencias; la tabla editable de componentes; los
  // supuestos; los APUs de referencia; y la barra de acciones.
}
```

**Requisitos del render que fijan los tests** (implementalos tal cual, el resto del
maquetado es libre dentro de la convención densa del repo):

| Elemento | Requisito |
|---|---|
| Actividad | se muestra `vigente.actividad.descripcion`, más unidad, cantidad y turno |
| Confianza | el nivel en mayúsculas; un botón "por qué" que despliega `confianza_motivos` con `senal`, `detalle` y `aporte` |
| Incertidumbre | texto que empieza con "El modelo declara …", separado del nivel |
| Errores | uno por `validacion.errores`, con su `mensaje` visible |
| Advertencias | uno por `validacion.advertencias`, con su `mensaje` visible |
| Hallazgo sin `componente` | `componente: ""` significa que es del **conjunto**, no de una fila: se pinta en el bloque de arriba y no resalta ninguna fila. Pasa con `FALTA_MANO_DE_OBRA`, `FALTA_HERRAMIENTA`, `METODO_INCOHERENTE`, `SUPUESTO_SIN_CONFIRMAR` y con `COMPONENTE_DUPLICADO` cuando hay **más de un** código repetido (con uno solo sí trae el código). Los códigos van nombrados dentro del `mensaje` |
| Rendimiento | `<input>` numérico con `aria-label={\`Rendimiento de ${c.codigo}\`}` |
| Quitar | `<button>` con `aria-label={\`Quitar ${c.codigo}\`}` |
| Métricas | el cociente "N de M validaciones superadas" se muestra **solo** cuando `validacion.valido` es verdadero. Con errores se lee "N errores" y nada más: un 89 % al lado de un cartel de bloqueo tranquiliza sobre algo que no se puede aprobar |
| Guardar cambios | llama `guardarComposicion(corridaId, fila, vigente.version, componentes, supuestosConfirmados)`; deshabilitado si no hay cambios |
| Regenerar | llama `generar()` |
| Rechazar | llama `rechazarComposicion(corridaId, fila, vigente.version, motivo)` |
| Aprobar y crear APU | `disabled` cuando `!validacion?.valido`; abre el diálogo de identidad |
| Sin composición | botón "Generar propuesta"; **no** se genera sola al montar (cada corrida es plata) |
| Etapas | mientras `etapa !== null`, el texto de `ETIQUETA_ETAPA[etapa]` |
| Rol | con rol `consulta` no se renderiza ninguna acción que escriba |

El diálogo de identidad es un modal chico con `codigo`, `turno` (select DIURNO/NOCTURNO),
`nombre` (precargado con la descripción de la actividad), `grupo` (el desplegable de
grupos que ya existe) y `unidad` (precargada con la de la actividad). Al aceptar llama
`aprobarComposicion` y, si va bien, `navegar(\`/corridas/${corridaId}\`)`.

**No se reusa `DialogoAgregarApu` completo** a propósito: obligaría a editar los
componentes dos veces, en la mesa y otra vez en el alta.

- [ ] **Paso 3b: la ruta**

En `web/src/App.tsx`, junto a la ruta de la corrida:

```tsx
<Route path="/corridas/:id/componer/:seq" element={<Composicion />} />
```

con su import. Si las rutas están dentro de un `<RequiereRol minimo="consulta">`,
poné esta en el mismo bloque: leer la mesa es de `consulta`, escribir es de `editor` y
eso ya lo controla la página.

- [ ] **Paso 3c: la puerta de entrada (fase 0)**

En `web/src/components/corrida/TablaItems.tsx`:

1. Borra el `import DialogoComposicion`, el estado `componer`, el bloque
   `{componer && <DialogoComposicion … />}` y la función `apuCompuesto`.
2. Reemplaza la condición de hoy:

```tsx
const ofreceComponer = puedeAplicar && v.dictamen === "sin_apu";
```

por una regla que no dependa de haber corrido la revisión:

```tsx
/** ¿Esta línea puede componerse con IA?
 *
 *  Sin APU (el determinístico no encontró nada), o con el veredicto `sin_apu` de la
 *  revisión sobre una fila que sí tiene APU. NO cuando hay `costo_manual`: esa línea
 *  ya declaró su costo (proyectos especiales) y no necesita APU.
 *
 *  Antes esto exigía haber corrido la revisión con IA sobre TODA la corrida para que
 *  apareciera el botón en una sola fila. */
function ofreceComponer(it: ItemCuadro, puedeEditar: boolean): boolean {
  if (!puedeEditar) return false;
  if (it.costo_manual != null && it.costo_manual > 0) return false;
  return !it.apu_codigo || it.revision?.dictamen === "sin_apu";
}
```

3. El botón sigue siendo un botón con `onComponer`, **no un `<Link>`**. Los tests de
   `TablaItems.test.tsx` montan el componente **sin Router**, así que un `<Link>` (o un
   `useNavigate` adentro) rompería los 40 tests que ya existen con
   `useHref() may be used only in the context of a <Router>`. La navegación la hace el
   padre, que sí está dentro del Router:

```tsx
// TablaItems.tsx — el botón, en la columna de acciones de la fila (ya no en la celda
// del veredicto: dejó de depender de que haya veredicto).
{ofreceComponer(it, puedeEditar && !readOnly) && (
  <Button size="sm" variant="outline" onClick={() => onComponer(it.seq)}>
    Componer
  </Button>
)}
```

```tsx
// Corrida.tsx — el padre navega.
const navegar = useNavigate();
// …
<TablaItems
  corridaId={id}
  items={items}
  onConfirmado={recargar}
  puedeEditar={puedeEditar}
  readOnly={congelada}
  onComponer={(seq) => navegar(`/corridas/${id}/componer/${seq}`)}
/>
```

La prop `onComponer` ya existe en `TablaItems` (hoy hace `setComponer(it)`): cambia su
firma a `(seq: number) => void` y su implementación en el padre. Un cambio de tipo, no
una prop nueva.

4. Borra `web/src/components/corrida/DialogoComposicion.tsx` y su test.

- [ ] **Paso 4: correr las pruebas y verificar que pasan**

```bash
cd web && npx vitest run
cd web && npm run build
```

Esperado: toda la suite de vitest verde y el build sin errores. **`npm run build`
(que corre `tsc -b`), no `tsc --noEmit`**: la lección de `nombre-corridas` fue que
`--noEmit` deja pasar errores que el build sí encuentra.

- [ ] **Paso 5: commit**

```bash
git add web/src/pages/Composicion.tsx web/src/pages/Composicion.test.tsx \
        web/src/App.tsx web/src/components/corrida/TablaItems.tsx \
        web/src/components/corrida/TablaItems.test.tsx
git rm web/src/components/corrida/DialogoComposicion.tsx \
       web/src/components/corrida/DialogoComposicion.test.tsx
git commit -m "feat(web): mesa de revision con URL propia; componer sale de cualquier fila sin APU"
```

---

## Tarea 13: documentación

**Archivos:** `CLAUDE.md`, `README.md`, `docs/ARQUITECTURA.md`, mapa de módulos.

- [ ] **Paso 1: `CLAUDE.md`**

En la tabla de `apu_tool/dominio/`, agrega dos filas y corrige la de `compose.py`:

```markdown
| `compose.py`             | candidatos de insumos + rendimientos observados de la biblioteca |
| `composicion.py`         | contrato del agente de composición (tipos y parseo, sin dependencias) |
| `composicion_agente.py`  | orquestador de la composición (propone; nunca aplica) |
| `validacion_composicion.py` | validador determinístico + confianza calculada (sin IA, sin dinero) |
```

En la tabla de `apu_tool/datos/`:

```markdown
| `composiciones_db.py` | SQLite del expediente de composición (append-only por versión) |
```

En la tabla de `apu_tool/servicio/`:

```markdown
| `composicion.py`       | servicio de la composición asistida (genera, edita, aprueba por autoría) |
```

En el diagrama de flujo, después de la línea de la revisión:

```
fila sin APU ──► composición con IA (sin dinero) ──► validación determinística
                                        └─► confianza calculada ──► aprueba usuario ──► autoria.crear_apu
```

En **Datos**, una entrada nueva (el estilo de las que ya están: qué, por qué, y la
trampa):

```markdown
- **Expediente de composición.** Cuando el matcher no encuentra nada, el usuario puede
  pedirle a la IA una composición para esa fila. Lo que vuelve es un **expediente**, no
  dos columnas: cada componente declara su función, de dónde sale el rendimiento
  (`origen`), qué APU lo respalda, la hipótesis productiva y la fórmula. Python
  **recalcula** esa fórmula y su resultado manda sobre el número del modelo
  (`CALCULO_CORREGIDO`); `dominio/validacion_composicion.py` aplica el resto de las
  reglas, y la **confianza la calcula la plataforma**, no el modelo — lo que el modelo
  dice de sí mismo se guarda como `incertidumbre_declarada` y **no entra en la fórmula**.
  Todo se persiste en `composicion`, **append-only por versión** (`ux_composicion_version`
  es la protección del doble clic, no un `if`): generar, regenerar, editar, aprobar y
  rechazar escriben una fila nueva, y la vigente es la de mayor `version`. El historial
  es el registro de correcciones. `actividad_json` guarda la vista **des-monetizada** del
  ítem, no el `LicitacionItem`: así la fila entera se puede reinyectar en un payload
  hacia la IA sin volver a filtrarla (la lección de `plan_json`). Una composición **no se
  borra** cuando la fila cambia de APU — al revés que `revision_json` —: un veredicto es
  caché barata, un expediente tiene trabajo humano adentro. Aprobar pasa por
  `servicio/autoria.py`; la IA nunca escribe en la biblioteca. Endpoints:
  `GET/PUT /api/corridas/{id}/composicion/{seq}`, `POST …/stream|aprobar|rechazar`.
```

En **No hacer**:

```markdown
- No dejes que la IA proponga un código que no esté en la lista blanca de esa
  generación (`antecedentes.codigos_permitidos`): `CODIGO_NO_AUTORIZADO` existe para
  eso. La lista **sí** se amplía cuando una PERSONA agrega un componente desde el
  buscador del catálogo — frena al modelo, no al usuario — y ahí el guardián que
  queda es `CODIGO_INEXISTENTE`.
- No uses la `incertidumbre_declarada` del modelo como confianza. La confianza la
  calcula `validacion_composicion.calcular_confianza` con señales observables y guarda
  su desglose. Hay un test que falla si el número del modelo mueve el nivel.
- No conviertas una regla de ingeniería discutible en error bloqueante. Bloquean el
  código inexistente, la cantidad que no es un número y el sub-APU que cicla; el
  rendimiento raro, la herramienta que falta y el método que no cuadra **advierten**.
```

- [ ] **Paso 2: `README.md` y `docs/ARQUITECTURA.md`**

Actualizá donde se describa la composición con IA: hoy dicen que es una llamada que
devuelve insumos y rendimiento. Reemplazá por el expediente (contrato explicable,
validación determinística, confianza calculada, persistencia versionada) y mencioná la
ruta `/corridas/{id}/componer/{seq}`.

- [ ] **Paso 3: el mapa de módulos**

```bash
python scripts/actualizar_vault.py    # o el que use el hook pre-commit
python -m pytest tests/test_mapa_arquitectura.py tests/test_actualizar_vault.py -q
```

Esperado: verde. Ese test compara la documentación de arquitectura contra los imports
reales; si falla, la tabla de `CLAUDE.md` tiene un módulo mal escrito.

- [ ] **Paso 4: commit**

```bash
git add CLAUDE.md README.md docs/ARQUITECTURA.md constructor-apus/
git commit -m "docs: el agente de composicion en CLAUDE.md, README y arquitectura"
```

---

## Tarea 14: verificación

- [ ] **Paso 1: la suite completa**

```bash
python -m pytest tests/ -q 2>&1 | tail -5
```

Esperado: **cero fallos**. La base era 1036 pasadas / 15 saltadas; el total cambia (se
borraron los tests de la composición vieja y entraron ~120 nuevos), lo que no puede
cambiar es que no haya rojo.

- [ ] **Paso 2: el frontend, con el build de verdad**

```bash
cd web && npx vitest run && npm run build
```

`npm run build` corre `tsc -b`. **No sirve `tsc --noEmit`**: en la rama de nombre de
corridas dejó pasar un error que el build sí encontró, ya en producción.

- [ ] **Paso 3: la migración contra un Postgres real**

Levantá la base desechable (receta registrada: binarios portables EDB, puerto 55433) y:

```bash
TEST_DATABASE_URL=postgresql://...:55433/apu python -m pytest tests/ -q 2>&1 | tail -5
```

Esperado: los tests de Postgres corren en vez de saltarse, y todos pasan. **Nunca
apuntes esto a producción**: hacen `DROP SCHEMA`.

- [ ] **Paso 4: smoke test en el navegador, con actividades reales**

Este paso **no es opcional** y es el que puede tumbar el diseño: el riesgo número uno es
que el contrato rico le cargue la atención al modelo y produzca **peores** rendimientos
que el de dos campos. Los tests unitarios no pueden verlo.

Levantá el servidor local (`scripts/servidor_local.py`) con `ANTHROPIC_API_KEY` puesta y,
sobre una corrida real, componé al menos **cinco actividades** de familias distintas
(una excavación, un concreto, una tubería, un transporte, una señalización). Por cada
una anotá en `smoke-test-composicion-2026-09-XX.md`:

- ¿los insumos elegidos son los correctos para la actividad?
- ¿los rendimientos son plausibles para un ingeniero de costos?
- ¿el `origen` declarado es honesto (dice `sin_evidencia` cuando no tiene antecedente)?
- ¿las advertencias apuntan a cosas reales o son ruido?
- ¿el nivel de confianza coincide con tu juicio?
- ¿cuánto tardó y cuántos tokens costó?

Comprobá además, en el navegador:

- recargar la página en medio de una generación y que la propuesta aparezca igual;
- editar un rendimiento, guardar, y que las advertencias se recalculen;
- doble clic en "Aprobar" y que se cree **un** APU, no dos;
- que una corrida sin filas pendientes no ofrezca componer en ninguna línea;
- que con `ANTHROPIC_API_KEY` sin poner, la app siga funcionando y el botón dé un 503
  con mensaje accionable.

- [ ] **Paso 5: pedir la revisión y el permiso de push**

```bash
git log --oneline master..HEAD
```

Presentá el resumen, el resultado del smoke test y **pedí aprobación explícita antes de
hacer push**: `master` autodespliega a producción.

---

## Cobertura de los criterios de aceptación

| Criterios | Tarea que los fija |
|---|---|
| 1, 2, 3, 4 — el determinístico no cambia | 9 (regresión), 12 (la corrida sin pendientes), 14 |
| 5, 8 — la actividad pendiente arranca y cancelar no toca nada | 10, 12 |
| 9, 10, 11, 12 — privacidad | 5, 7, 10 |
| 15, 16 — códigos y referencias rastreables | 3, 9 |
| 17, 18, 19, 20, 21 — generación | 1, 6, 9 |
| 22, 23, 24, 25, 26, 27 — validación y confianza | 3, 4 |
| 28, 29, 30, 31, 32 — aprobación | 10 |
| 33, 34, 35, 36 — persistencia | 7, 8, 12 |

**Fuera de esta fase:** 6 y 7 (preguntas críticas) → fase 2; 13 y 14 (recuperación
guiada por la ficha) → fase 3. **32 de 36.**
