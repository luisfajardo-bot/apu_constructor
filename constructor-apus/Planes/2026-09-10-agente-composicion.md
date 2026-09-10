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
| `apu_tool/dominio/composicion.py` | **nuevo.** Vocabularios cerrados, dataclasses del contrato, parseo tolerante del JSON del modelo, orquestador `componer()` |
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
                            f"{r:g} queda {pct:.0f} % {lado} del rango observado "
                            f"({obs.minimo:g}-{obs.maximo:g}, n={obs.n}).", c.codigo))

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
        assert m.senal and m.valor            # todo motivo se puede leer


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
    valor: str          # legible: "4 de 5 con antecedente vivo"
    aporte: int

    def to_dict(self) -> dict[str, Any]:
        return {"senal": self.senal, "valor": self.valor, "aporte": self.aporte}


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

    respaldados = sum(1 for c in comps
                      if c.origen in _ORIGENES_CON_ANTECEDENTE + (
                          "calculado_desde_produccion",) and c.referencias)
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
