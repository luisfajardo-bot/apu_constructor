# IA revisora post-armado — Plan de implementación

> **Para agentes ejecutores:** SUB-SKILL REQUERIDA: usa `superpowers:subagent-driven-development` (recomendado) o `superpowers:executing-plans` para ejecutar este plan tarea por tarea. Los pasos usan checkbox (`- [ ]`).

**Objetivo:** Sacar la IA del armado de corridas (que queda 100% determinístico) y meterla después como una pasada de revisión que audita la corrida completa y **propone** cambios de APU; y convertir las filas sin APU en un candado duro antes de congelar o descargar el cuadro.

**Arquitectura:** El armado pierde su rama de IA. Un módulo nuevo `apu_tool/dominio/revision.py` (sin HTTP, sin dinero) hace dos pasos: un **barrido** por lotes de 25 filas que ve el índice de la corrida completa y marca sospechosas, y una **profundización** por fila marcada con las composiciones `DePriced` de sus candidatos. El veredicto se guarda en una columna nueva `corrida_item.revision_json` y viaja en la vista de la corrida. Aplicar una sugerencia reusa `confirmar_items`, la primitiva de lote que ya existe.

**Stack:** Python 3.14 + FastAPI + SQLite/Postgres (doble backend) + React/TypeScript con Vitest. SDK `anthropic` (opcional). Pruebas con `pytest`.

**Spec:** `docs/superpowers/specs/2026-08-31-ia-revisora-post-armado-design.md`

**Rama:** `feat/ia-revisora-post-armado`, apilada sobre `feat/distancias-transporte-proyecto`. Esa rama espera PR: **no le hagas ni un commit ni un push**.

---

## Reglas del repositorio (léelas antes de empezar)

1. **Invariante #1 — la IA nunca ve dinero.** Todo payload hacia la IA se serializa con `apu_tool/dominio/privacy.py::safe_json`, que lanza `PrivacyViolation` si encuentra una clave monetaria. Nunca construyas un payload a mano con `json.dumps`.
2. **Español** en nombres de dominio, comentarios y mensajes de usuario.
3. **Persistencia solo en `apu_tool/datos/`.** Nada de SQL crudo fuera de ahí.
4. **Doble backend.** Todo cambio de esquema va en `db/corridas.sql` (SQLite) **y** en `db/pg/corridas.sql` (Postgres), y todo método nuevo del repositorio va en `corridas_db.py`, `pg/corridas_pg.py` y en el `Protocol` de `datos/repositorio.py`.
5. **Nada en $0 en silencio.** Un costo en $0 siempre lleva alerta.
6. **Correr `python -m pytest tests/ -q` antes de dar algo por terminado.**

---

## Estructura de archivos

**Se crean:**

| Archivo | Responsabilidad |
|---|---|
| `apu_tool/dominio/revision.py` | Motor de revisión: tipos, payloads sin dinero, barrido, profundización, orquestador. Sin HTTP. |
| `tests/test_revision_privacidad.py` | Que los dos payloads no lleven dinero. |
| `tests/test_revision_motor.py` | Barrido, profundización, degradación de sugerencias inválidas. |
| `tests/test_revision_persistencia.py` | `revision_json` en el repositorio y su invalidación. |
| `tests/test_api_revision.py` | Endpoint SSE, aplicar en lote, componer a pedido. |
| `tests/test_candado_sin_apu.py` | Candado en congelar y en cuadro. |
| `web/src/components/corrida/DialogoComposicion.tsx` | Muestra la composición propuesta y abre el alta de APU precargada. |
| `web/src/components/corrida/DialogoComposicion.test.tsx` | Prueba del diálogo. |

**Se modifican:**

| Archivo | Cambio |
|---|---|
| `apu_tool/dominio/assemble.py` | `assemble_item` pierde la rama de IA; `_try_generate` → `generar_composicion` (público). |
| `apu_tool/nucleo/models.py` | `CorridaItemRow` gana el campo `revision`. |
| `db/corridas.sql`, `db/pg/corridas.sql` | Columna `revision_json`. |
| `apu_tool/datos/corridas_db.py`, `apu_tool/datos/pg/corridas_pg.py` | Leer/escribir `revision_json`; borrarlo en `actualizar_eleccion`. |
| `apu_tool/datos/repositorio.py` | `set_revision` / `get_revisiones` en el `Protocol`. |
| `apu_tool/servicio/corridas.py` | `seqs_sin_apu`, candado, `revisar_corrida_stream`, `componer_item`, `confirmar_items(asignaciones=...)`, `revision` en `_vista_item`, `ia_disponible` en `vista_corrida`. |
| `apu_tool/servicio/rutas.py` | 3 endpoints nuevos + 409 del candado. |
| `apu_tool/servicio/esquemas.py` | `AsignacionIn`, campo `asignaciones` en `ConfirmarLoteIn`. |
| `web/src/lib/tipos.ts` | `VeredictoIA`, `revision` en `ItemCuadro`, `ia_disponible` en `CorridaDetalle`. |
| `web/src/api/corridas.ts` | `revisarCorridaStream`, `aplicarSugerencias`, `componerItem`. |
| `web/src/lib/corridaTabla.ts` | Columna/filtro `veredicto`. |
| `web/src/components/corrida/TablaItems.tsx` | Columna Veredicto + botón Aplicar + botón Componer. |
| `web/src/pages/Corrida.tsx` | Botón Revisar con IA, contador de filas sin APU, botones bloqueados. |
| `web/src/pages/CorridasInicio.tsx` | Quitar el interruptor "Usar IA". |
| `tests/test_assemble.py`, `tests/test_assemble_generado.py` | Ajustar al armado sin IA y al rename. |

---

## FASE 1 — El armado deja de usar IA

### Task 1: `assemble_item` sin rama de IA

**Files:**
- Modify: `apu_tool/dominio/assemble.py`
- Test: `tests/test_assemble.py`, `tests/test_assemble_generado.py`

Contexto: hoy `assemble_item` llama a `self.advisor.choose_apu(...)` para los ítems dudosos o nuevos, y si la IA no elige nada llama a `self._try_generate(item)`, que **inventa** un APU. Se quitan las dos llamadas. El parámetro `advisor` del constructor **se queda**, porque `generar_composicion` (el ex `_try_generate`) lo sigue usando cuando alguien lo pide explícitamente — así ningún llamador actual se rompe.

- [ ] **Step 1: Escribe el test que falla**

Agrega al final de `tests/test_assemble.py`:

```python
class _AdvisorEspia:
    """Revienta si el armado lo toca. El armado tiene que ser determinístico."""
    def choose_apu(self, *a, **k):
        raise AssertionError("assemble_item no debe llamar a la IA")

    def compose_apu(self, *a, **k):
        raise AssertionError("assemble_item no debe componer con IA")


def test_armado_nunca_llama_a_la_ia(tmp_path):
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem

    a = Almacen(tmp_path / "p.db", tmp_path / "a.db")
    a.reset()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000)])
    asm = Assembler(a, advisor=_AdvisorEspia())

    # Dudoso (entre MATCH_REVIEW y MATCH_ACCEPT): toma el mejor candidato, sin IA.
    dudoso = LicitacionItem(item="1", descripcion="EXCAVACION MANUAL EN TIERRA",
                            unidad="M3", cantidad=1, precio_contractual=0, shift="DIURNO")
    r1 = asm.assemble_item(dudoso)
    assert r1.apu_codigo == "100"

    # Sin coincidencia: queda SIN APU y con status new, nunca generado.
    nuevo = LicitacionItem(item="2", descripcion="BARRERA ANTIRRUIDO MODULAR",
                           unidad="M2", cantidad=1, precio_contractual=0, shift="DIURNO")
    r2 = asm.assemble_item(nuevo)
    assert r2.apu_codigo is None
    assert r2.status.value == "new"
    assert r2.origen == "manual"
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_assemble.py::test_armado_nunca_llama_a_la_ia -q`
Expected: FAIL con `AssertionError: assemble_item no debe llamar a la IA`

- [ ] **Step 3: Quita la rama de IA**

En `apu_tool/dominio/assemble.py`, reemplaza el bloque que hoy va desde `# Dudoso o nuevo: la IA elige...` hasta el `return self._build(item, decision.apu_codigo, ...)` (el final de `assemble_item`) por:

```python
        # Dudoso o nuevo: SIN IA. El mejor candidato por encima del piso de revisión
        # se asigna marcado REVIEW; por debajo del piso la fila queda sin APU, en $0
        # y con alerta. La IA ya no decide acá: audita después (dominio/revision.py).
        # Un 25% de parecido de nombre producía un APU con pinta de autoritativo —
        # caso real de 2026-08-04: una "Localización y replanteo" costeada como
        # PEDESTAL DE CONCRETO, 2010 veces el costo correcto.
        mejor = result.candidatos[0] if result.candidatos else None
        if mejor is not None and mejor.score >= config.MATCH_REVIEW:
            return self._build(item, mejor.apu_codigo, item.shift, MatchStatus.REVIEW,
                               mejor.score,
                               f"Mejor similaridad de nombre ({mejor.score:.0%}). "
                               f"Sin confirmar.")
        peor = f"{mejor.score:.0%}" if mejor is not None else "sin candidatos"
        return AssembledApu(
            item=item, apu_codigo=None, apu_nombre="(sin base — armar manual)",
            unidad=item.unidad, shift=item.shift, componentes=[],
            costo_unitario=0.0, status=MatchStatus.NEW,
            confianza=mejor.score if mejor is not None else 0.0, origen="manual",
            explicacion=(f"Mejor coincidencia {peor}, por debajo del mínimo de "
                         f"{config.MATCH_REVIEW:.0%} para asignar un APU. "
                         f"Elige uno de los candidatos o ármalo a mano."),
        )
```

Agrega `from apu_tool import config` al bloque de imports del archivo (hoy no está).

Renombra `_try_generate` a `generar_composicion` y cambia su docstring por:

```python
    def generar_composicion(self, item: LicitacionItem) -> Optional[AssembledApu]:
        """Compone un APU desde cero con la IA para una actividad nueva.

        NO la llama el armado: es a pedido explícito del usuario (endpoint
        `/corridas/{id}/componer/{seq}`), y lo que devuelve es una PROPUESTA que
        alguien tiene que confirmar. Devuelve None si no hay IA o si no se pudo
        componer. Es la única razón por la que el `Assembler` sigue recibiendo un
        `advisor`.
        """
```

Actualiza el docstring del módulo (arriba del todo) reemplazando los puntos 1–3 por:

```
Para cada ítem de la lista de licitación:
  1. si el ítem trae código del presupuesto y ese APU existe -> AUTO, directo.
  2. matching determinístico contra el histórico (filtrado por turno):
       >= MATCH_ACCEPT -> AUTO
       >= MATCH_REVIEW -> el mejor candidato, marcado REVIEW
       por debajo      -> SIN APU, $0 con alerta (nunca se inventa nada)
  3. el motor determinístico costea la composición y arma el AssembledApu.

La IA NO participa del armado. Audita después, sobre la corrida ya armada
(ver dominio/revision.py) y siempre proponiendo, nunca aplicando.
```

- [ ] **Step 4: Corre el test y verifica que pasa**

Run: `python -m pytest tests/test_assemble.py::test_armado_nunca_llama_a_la_ia -q`
Expected: PASS

- [ ] **Step 5: Arregla el test del rename**

En `tests/test_assemble_generado.py`, cambia `res = asm._try_generate(item)` por `res = asm.generar_composicion(item)`, y borra el método `choose_apu` de la clase `_Advisor` (ya nadie lo llama desde el armado):

```python
class _Advisor:
    """Advisor falso: compone con un código conocido. `generar_composicion` es lo
    único que usa al advisor ahora."""
    def compose_apu(self, item, insumos, ejemplos):
        class C:
            componentes = [type("X", (), {"insumo_codigo": "4279", "rendimiento": 2.0})()]
            justificacion = "ok"; confianza = 0.9
        return C()
```

- [ ] **Step 6: Corre toda la suite de armado**

Run: `python -m pytest tests/test_assemble.py tests/test_assemble_generado.py tests/test_assemble_codigo.py tests/test_pipeline.py -q`
Expected: PASS. Si algún test asumía que la IA elegía durante el armado, es un test que describe el comportamiento viejo: cámbialo para que espere el determinístico, no revivas la rama.

- [ ] **Step 7: Corre la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/dominio/assemble.py tests/test_assemble.py tests/test_assemble_generado.py
git commit -m "feat(armado): el armado ya no llama a la IA, nunca inventa un APU"
```

---

### Task 2: Quitar el interruptor "Usar IA" de crear corrida

**Files:**
- Modify: `web/src/pages/CorridasInicio.tsx`

Contexto: el interruptor manda `use_ai` al backend, que ya no tiene efecto en el armado. La columna `corrida.use_ai` se queda en la base como histórico; solo desaparece de la pantalla. El backend sigue aceptando el `Form(None)` — no se toca `rutas.py`.

- [ ] **Step 1: Borra el estado y el checkbox**

En `web/src/pages/CorridasInicio.tsx`:

1. Borra la línea `const [usarIA, setUsarIA] = useState(true);`
2. Borra la línea `form.append("use_ai", String(usarIA));`
3. Borra el bloque JSX del `<input id="usar-ia" ...>` junto con su `<label htmlFor="usar-ia">Usar IA</label>` y el contenedor que los envuelve si queda vacío.

- [ ] **Step 2: Compila el frontend**

Run: `cd web && npm run build`
Expected: build OK, sin errores de `tsc -b`. (Usa `npm run build`, no `tsc --noEmit`: en este repo el `--noEmit` deja pasar errores que `tsc -b` sí atrapa.)

- [ ] **Step 3: Corre los tests del frontend**

Run: `cd web && npm test`
Expected: PASS. Si un test de `CorridasInicio` buscaba la casilla "Usar IA", bórrale esa aserción.

- [ ] **Step 4: Commit**

```bash
git add web/src/pages/CorridasInicio.tsx web/src/pages/CorridasInicio.test.tsx
git commit -m "feat(web): crear corrida ya no ofrece 'Usar IA' (el armado es deterministico)"
```

---

## FASE 2 — Candado de filas sin APU

### Task 3: Candado en congelar y en generar_cuadro

**Files:**
- Modify: `apu_tool/servicio/corridas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_candado_sin_apu.py`

Contexto: `generar_cuadro` llama a `congelar` **solo** si la corrida no está ya congelada con foto. Por eso hacen falta dos chequeos, no uno: una corrida congelada antes de esta feature puede traer filas sin APU y su cuadro se descargaría igual.

- [ ] **Step 1: Escribe el test que falla**

Crea `tests/test_candado_sin_apu.py`:

```python
"""Una fila sin APU bloquea congelar y descargar el cuadro.

Regla de negocio: una corrida con filas sin APU no describe un presupuesto — le
faltan líneas. Mejor trabar la puerta que emitir un cuadro incompleto que alguien
va a mandar creyendo que está entero.
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.servicio import corridas as svc


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000)])
    return a


def _corrida_con_fila_sin_apu(alm) -> int:
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-08-31T10:00:00", archivo="x.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision", cuadro_path=None,
        nombre="x"))
    item_ok = LicitacionItem(item="1", descripcion="EXCAVACION MANUAL", unidad="M3",
                             cantidad=1, precio_contractual=100, shift="DIURNO")
    item_malo = LicitacionItem(item="2", descripcion="ACTIVIDAD RARA", unidad="M2",
                               cantidad=1, precio_contractual=100, shift="DIURNO")
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0, item=item_ok, status="auto", apu_codigo="100", apu_nombre="EXCAVACION MANUAL",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[], candidatos=[]))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=1, item=item_malo, status="new", apu_codigo=None, apu_nombre="(sin base)",
        unidad="M2", shift="DIURNO", origen="manual", confianza=0.0, explicacion="",
        componentes=[], candidatos=[]))
    return cid


def test_congelar_falla_con_filas_sin_apu(alm):
    cid = _corrida_con_fila_sin_apu(alm)
    with pytest.raises(svc.FilasSinApu) as exc:
        svc.congelar(alm, cid)
    assert exc.value.seqs == [1]


def test_cuadro_falla_con_filas_sin_apu(alm):
    cid = _corrida_con_fila_sin_apu(alm)
    with pytest.raises(svc.FilasSinApu):
        svc.generar_cuadro(alm, cid)


def test_cuadro_congelado_legacy_tambien_falla(alm):
    """Congelada ANTES del candado: `generar_cuadro` se salta `congelar`, así que
    necesita su propio chequeo o el cuadro incompleto sale igual."""
    cid = _corrida_con_fila_sin_apu(alm)
    alm.corridas.set_modo(cid, "congelada")
    alm.corridas.set_snapshot(cid, 0, {"composicion": [], "costo_unitario": 0.0})
    with pytest.raises(svc.FilasSinApu):
        svc.generar_cuadro(alm, cid)


def test_con_todas_asignadas_pasa(alm):
    cid = _corrida_con_fila_sin_apu(alm)
    svc.confirmar_items(alm, cid, [1], "100", "DIURNO")
    assert svc.congelar(alm, cid) is not None
    assert svc.generar_cuadro(alm, cid) is not None
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_candado_sin_apu.py -q`
Expected: FAIL con `AttributeError: module ... has no attribute 'FilasSinApu'`

- [ ] **Step 3: Implementa el candado**

En `apu_tool/servicio/corridas.py`, junto a las otras excepciones del módulo (donde está `CorridaCongelada`), agrega:

```python
class FilasSinApu(RuntimeError):
    """La corrida tiene líneas sin APU asignado: no se congela ni se emite cuadro.

    Un cuadro con líneas sin APU se ve completo y no lo está: las filas van en $0 y
    quien lo recibe no tiene forma de saber que le faltan actividades. Se traba la
    puerta y se dice exactamente qué seq faltan.
    """
    def __init__(self, corrida_id: int, seqs: list[int]):
        self.corrida_id = corrida_id
        self.seqs = seqs
        super().__init__(
            f"{len(seqs)} línea(s) sin APU asignado (ítems {', '.join(str(s) for s in seqs)}). "
            f"Asígnalas antes de congelar o descargar el cuadro.")


def seqs_sin_apu(rows) -> list[int]:
    """Los seq de las filas que no tienen APU. Lista vacía = se puede cerrar."""
    return [r.seq for r in rows if not r.apu_codigo]
```

En `congelar`, justo después de `if meta is None: return None`, agrega:

```python
    _rows_guard = alm.corridas.get_items(corrida_id)
    faltan = seqs_sin_apu(_rows_guard)
    if faltan:
        raise FilasSinApu(corrida_id, faltan)
```

y reemplaza el `_rows = alm.corridas.get_items(corrida_id)` que viene más abajo por `_rows = _rows_guard` (una consulta, no dos).

En `generar_cuadro`, justo después de `if meta is None: return None`, agrega el mismo guard:

```python
    # Chequeo propio, no basta con el de `congelar`: si la corrida ya está congelada
    # con foto, la llamada a `congelar` de abajo se saltea, y una corrida congelada
    # ANTES de este candado sí puede traer filas sin APU.
    faltan = seqs_sin_apu(alm.corridas.get_items(corrida_id))
    if faltan:
        raise FilasSinApu(corrida_id, faltan)
```

- [ ] **Step 4: Corre el test y verifica que pasa**

Run: `python -m pytest tests/test_candado_sin_apu.py -q`
Expected: PASS

- [ ] **Step 5: Traduce el candado a 409 en los endpoints**

En `apu_tool/servicio/rutas.py`, cambia el endpoint `congelar`:

```python
@router.post("/corridas/{cid}/congelar")
def congelar(cid: int, alm: Almacen = Depends(get_almacen),
             _: object = Depends(requiere_rol("consulta"))):
    try:
        v = svc.congelar(alm, cid)
    except svc.FilasSinApu as e:
        raise HTTPException(status_code=409,
                            detail={"detail": str(e), "seqs": e.seqs})
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

y el endpoint `cuadro`:

```python
@router.get("/corridas/{cid}/cuadro")
def cuadro(cid: int, alm: Almacen = Depends(get_almacen),
          _: object = Depends(requiere_rol("consulta"))):
    try:
        out = svc.generar_cuadro(alm, cid)
    except svc.FilasSinApu as e:
        raise HTTPException(
            status_code=409,
            detail={"detail": f"{e} Si está congelada, actívala, asígnalas y "
                              f"vuelve a congelar.",
                    "seqs": e.seqs})
    if out is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return FileResponse(str(out), filename=out.name, media_type=_XLSX)
```

- [ ] **Step 6: Agrega el test del 409**

Al final de `tests/test_candado_sin_apu.py`:

Los tests de API de este repo **no usan fixtures**: usan un helper `_cliente(tmp_path)`
que devuelve `(cli, alm)` (ver `tests/test_api_corridas.py:14`). Sigue ese patrón:

```python
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cliente_api(tmp_path):
    a = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db")
    a.init_schema()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000)])
    return cliente(create_app(almacen=a), rol="admin"), a


def test_endpoints_devuelven_409_con_los_seqs(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_con_fila_sin_apu(alm)
    r = cli.post(f"/api/corridas/{cid}/congelar")
    assert r.status_code == 409
    assert r.json()["detail"]["seqs"] == [1]
    r = cli.get(f"/api/corridas/{cid}/cuadro")
    assert r.status_code == 409
```

- [ ] **Step 7: Corre la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/corridas.py apu_tool/servicio/rutas.py tests/test_candado_sin_apu.py
git commit -m "feat(corridas): una fila sin APU bloquea congelar y descargar el cuadro"
```

---

### Task 4: El candado se ve antes de la puerta (UI)

**Files:**
- Modify: `web/src/pages/Corrida.tsx`

- [ ] **Step 1: Calcula el conteo y bloquea los botones**

En `web/src/pages/Corrida.tsx`, después de `const margenNegativo = totales.margen < 0;` agrega:

```tsx
  // Filas sin APU: se cuentan sobre TODOS los ítems, no sobre los filtrados —
  // el candado no depende de lo que estés mirando.
  const sinApu = (data.items ?? []).filter((f) => !f.apu_codigo);
  const bloqueado = sinApu.length > 0;
```

Cambia el botón de congelar y el de descargar (en la barra de acciones) por:

```tsx
            <Button size="sm" variant="outline"
              disabled={bloqueado && data.modo !== "congelada"}
              title={bloqueado && data.modo !== "congelada"
                ? `${sinApu.length} línea(s) sin APU: asígnalas antes de congelar.`
                : undefined}
              onClick={() => cambiarModo(data.modo === "congelada" ? "activar" : "congelar")}>
              {data.modo === "congelada" ? "Activar" : "Congelar"}
            </Button>
```

```tsx
            <Button size="sm" variant="outline"
              disabled={bloqueado}
              title={bloqueado
                ? `${sinApu.length} línea(s) sin APU: asígnalas antes de descargar.`
                : undefined}
              onClick={() => descargarCuadro(corridaId).catch((e) =>
                toast.error(e instanceof Error ? e.message : "No se pudo descargar el cuadro."))}>
              Descargar cuadro
            </Button>
```

Nota: "Activar" nunca se bloquea — es justamente la salida de una corrida congelada con filas sin APU.

- [ ] **Step 2: Agrega el contador que filtra**

En el bloque de contadores (`{/* Counters sub-line */}`), después del `{totales.n_revision > 0 && ...}`, agrega:

```tsx
        {!live && sinApu.length > 0 && (
          <button
            type="button"
            className="text-red-700 font-semibold underline"
            onClick={() => control.setFiltro("apu", "__sin__")}
            title="Ver solo las líneas sin APU"
          >
            {sinApu.length} sin APU
          </button>
        )}
```

- [ ] **Step 3: Soporta el filtro "sin APU" en la tabla**

En `web/src/lib/corridaTabla.ts`, dentro de `filtrar`, en la rama del filtro de texto de `apu`, agrega el caso especial antes de la comparación normal:

```ts
    if (f.apu === "__sin__") {
      if (it.apu_codigo) return false;
    } else if (f.apu && !contiene(`${it.apu_codigo} ${it.apu_nombre}`, f.apu)) {
      return false;
    }
```

Ajusta el código existente para que este `if/else` reemplace la comprobación previa de `apu` (busca dónde se evalúa hoy la clave `apu` dentro de `filtrar`). Verifica también que `useCorridaTabla` exponga `setFiltro`; si el hook expone otro nombre (p. ej. `setFiltros`), usa ese en el Step 2 en vez de inventar uno.

- [ ] **Step 4: Escribe la prueba**

En `web/src/pages/Corrida.test.tsx`, agrega:

Este archivo ya tiene un helper `fila(...)`, una constante `CORRIDA` y un
`vi.mock("@/api/corridas", ...)` en el tope. **El mock reemplaza el módulo entero**:
agrégale las funciones nuevas o el import de `Corrida.tsx` fallará.

```tsx
vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(async () => CORRIDA),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
  revisarCorridaStream: vi.fn(async () => ({ ok: 2 })),
  aplicarSugerencias: vi.fn(async () => CORRIDA),
}));
```

Y el test:

```tsx
test("bloquea congelar y descargar cuando hay líneas sin APU", async () => {
  const { getCorrida } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce({
    ...CORRIDA,
    items: [
      fila({ seq: 0, descripcion: "Excavación" }),
      fila({ seq: 1, descripcion: "Actividad rara", apu_codigo: "", apu_nombre: "" }),
    ],
  } as never);

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Actividad rara");

  expect(screen.getByRole("button", { name: /descargar cuadro/i })).toBeDisabled();
  expect(screen.getByRole("button", { name: /^congelar$/i })).toBeDisabled();
  expect(screen.getByText(/1 sin APU/)).toBeInTheDocument();
});
```

Si `fila(...)` todavía no incluye `revision`, agrégaselo como `revision: null` en su
objeto base — la vista siempre manda el campo.

- [ ] **Step 5: Corre build y tests del frontend**

Run: `cd web && npm run build && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Corrida.tsx web/src/pages/Corrida.test.tsx web/src/lib/corridaTabla.ts
git commit -m "feat(web): el candado de lineas sin APU se ve y bloquea antes de la puerta"
```

---

## FASE 3 — Persistencia del veredicto

### Task 5: Columna `revision_json` en los dos backends

**Files:**
- Modify: `db/corridas.sql`, `db/pg/corridas.sql`, `apu_tool/datos/corridas_db.py`, `apu_tool/datos/pg/corridas_pg.py`, `apu_tool/datos/repositorio.py`, `apu_tool/nucleo/models.py`
- Test: `tests/test_revision_persistencia.py`

- [ ] **Step 1: Escribe el test que falla**

Crea `tests/test_revision_persistencia.py`:

```python
"""`revision_json`: el veredicto de la IA por fila, y su invalidación.

Un veredicto sobre un APU que la fila ya no tiene es peor que ninguno: se borra en
el mismo punto donde se cambia el APU (`actualizar_eleccion`).
"""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import CorridaItemRow, CorridaMeta, LicitacionItem


@pytest.fixture()
def alm(tmp_path):
    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    return a


def _corrida(alm) -> int:
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-08-31T10:00:00", archivo="x.xlsx",
        turno_def="DIURNO", use_ai=None, estado="en_revision", cuadro_path=None,
        nombre="x"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0, item=LicitacionItem(item="1", descripcion="A", unidad="M3", cantidad=1,
                                   precio_contractual=0, shift="DIURNO"),
        status="auto", apu_codigo="100", apu_nombre="A", unidad="M3", shift="DIURNO",
        origen="historico", confianza=1.0, explicacion="", componentes=[], candidatos=[]))
    return cid


def test_fila_nueva_no_tiene_veredicto(alm):
    cid = _corrida(alm)
    assert alm.corridas.get_revisiones(cid) == {}
    assert alm.corridas.get_items(cid)[0].revision is None


def test_guarda_y_lee_el_veredicto(alm):
    cid = _corrida(alm)
    v = {"seq": 0, "dictamen": "cambiar", "apu_sugerido": "200",
         "turno_sugerido": "DIURNO", "confianza": 0.8,
         "justificacion": "la unidad no coincide", "nivel": "profundo"}
    alm.corridas.set_revision(cid, 0, v)
    assert alm.corridas.get_revisiones(cid) == {0: v}
    assert alm.corridas.get_items(cid)[0].revision == v


def test_cambiar_el_apu_borra_el_veredicto(alm):
    cid = _corrida(alm)
    alm.corridas.set_revision(cid, 0, {"seq": 0, "dictamen": "ok", "apu_sugerido": None,
                                       "turno_sugerido": None, "confianza": 1.0,
                                       "justificacion": "", "nivel": "barrido"})
    alm.corridas.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="200", apu_nombre="B", unidad="M3",
        shift="DIURNO", origen="historico", confianza=1.0, explicacion="", componentes=[])
    assert alm.corridas.get_revisiones(cid) == {}
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_revision_persistencia.py -q`
Expected: FAIL con `AttributeError: 'CorridasDB' object has no attribute 'get_revisiones'`

- [ ] **Step 3: Esquema SQLite**

En `db/corridas.sql`, dentro de `CREATE TABLE IF NOT EXISTS corrida_item (...)`, después de la línea `snapshot_json    TEXT`, agrega:

```sql
  ,revision_json    TEXT
```

- [ ] **Step 4: Migración idempotente SQLite**

En `apu_tool/datos/corridas_db.py::init_schema`, junto al bloque que ya migra `snapshot_json`:

```python
            if "revision_json" not in icols:
                conn.execute("ALTER TABLE corrida_item ADD COLUMN revision_json TEXT")
```

- [ ] **Step 5: Esquema Postgres**

En `db/pg/corridas.sql`, dentro de `CREATE TABLE IF NOT EXISTS corridas.corrida_item (...)`, después de `snapshot_json    TEXT`, agrega `,` y la columna:

```sql
    snapshot_json    TEXT,
    revision_json    TEXT
```

Y en el bloque de migración idempotente al final del archivo, junto al `ADD COLUMN IF NOT EXISTS snapshot_json`:

```sql
ALTER TABLE corridas.corrida_item ADD COLUMN IF NOT EXISTS revision_json TEXT;
```

- [ ] **Step 6: Campo en el modelo**

En `apu_tool/nucleo/models.py`, en `CorridaItemRow`, agrega al final de los campos:

```python
    revision: Optional[dict] = None    # veredicto de la IA; None = nunca revisada
```

Va al final y con default para no romper los llamadores posicionales que ya existen.

- [ ] **Step 7: Métodos en SQLite**

En `apu_tool/datos/corridas_db.py`, junto a `set_snapshot` / `get_snapshots`:

```python
    def set_revision(self, corrida_id: int, seq: int, payload: Optional[dict]) -> None:
        """Guarda (o borra, con payload=None) el veredicto de la IA de una fila."""
        with self.connect() as conn:
            conn.execute(
                "UPDATE corrida_item SET revision_json=? WHERE corrida_id=? AND seq=?",
                (None if payload is None else json.dumps(payload, ensure_ascii=False),
                 int(corrida_id), int(seq)))

    def get_revisiones(self, corrida_id: int) -> dict[int, dict]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT seq, revision_json FROM corrida_item "
                "WHERE corrida_id=? AND revision_json IS NOT NULL",
                (int(corrida_id),)).fetchall()
        return {r["seq"]: json.loads(r["revision_json"]) for r in rows}
```

En `_row_to_item`, agrega el campo:

```python
            candidatos=json.loads(r["candidatos_json"] or "[]"),
            revision=(json.loads(r["revision_json"])
                      if ("revision_json" in r.keys() and r["revision_json"]) else None))
```

En `actualizar_eleccion`, agrega `revision_json=NULL` al UPDATE:

```python
            conn.execute(
                "UPDATE corrida_item SET status=?, apu_codigo=?, apu_nombre=?, unidad=?, "
                "shift=?, origen=?, confianza=?, explicacion=?, componentes_json=?, "
                # El APU cambió: el veredicto de la IA hablaba del anterior. Se borra
                # acá, el único punto por el que pasa un cambio de APU.
                "revision_json=NULL "
                "WHERE corrida_id=? AND seq=?",
```

- [ ] **Step 8: Métodos en Postgres**

En `apu_tool/datos/pg/corridas_pg.py`, espejo exacto:

```python
    def set_revision(self, corrida_id: int, seq: int, payload: Optional[dict]) -> None:
        with self.cx.connection() as conn:
            conn.execute(
                "UPDATE corridas.corrida_item SET revision_json=%s "
                "WHERE corrida_id=%s AND seq=%s",
                (None if payload is None else json.dumps(payload, ensure_ascii=False),
                 int(corrida_id), int(seq)))

    def get_revisiones(self, corrida_id: int) -> dict[int, dict]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT seq, revision_json FROM corridas.corrida_item "
                "WHERE corrida_id=%s AND revision_json IS NOT NULL",
                (int(corrida_id),)).fetchall()
        return {r["seq"]: json.loads(r["revision_json"]) for r in rows}
```

Agrega `revision_json=NULL` al UPDATE de su `actualizar_eleccion` igual que en SQLite, y el campo `revision` a su hidratación de filas (busca el método que construye `CorridaItemRow` en ese archivo y agrégalo con la misma guarda de clave ausente).

- [ ] **Step 9: Protocol**

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioCorridas`, junto a `set_snapshot` / `get_snapshots`:

```python
    def set_revision(self, corrida_id: int, seq: int, payload: Optional[dict]) -> None:
        """Veredicto de la IA de una fila. payload=None lo borra."""
        ...
    def get_revisiones(self, corrida_id: int) -> dict[int, dict]:
        """seq -> veredicto, solo de las filas revisadas."""
        ...
```

- [ ] **Step 10: Corre el test**

Run: `python -m pytest tests/test_revision_persistencia.py -q`
Expected: PASS

- [ ] **Step 11: Corre el contrato dual-backend y la suite**

Run: `python -m pytest tests/ -q`
Expected: PASS

El test de contrato compartido de corridas (busca en `tests/` el que corre el mismo cuerpo contra `CorridasDB` y `CorridasPg`) debe cubrir los métodos nuevos: agrégalos ahí siguiendo su patrón, para que Postgres no quede sin probar. Si no hay Postgres levantado en local, esos tests se saltan solos; la receta para levantarlo está en la memoria del proyecto (binarios portables EDB, puerto 55433). **Nunca los apuntes a producción: hacen `DROP SCHEMA`.**

- [ ] **Step 12: Commit**

```bash
git add db/corridas.sql db/pg/corridas.sql apu_tool/datos/ apu_tool/nucleo/models.py tests/test_revision_persistencia.py
git commit -m "feat(datos): columna revision_json por fila de corrida, con invalidacion al cambiar el APU"
```

---

## FASE 4 — El motor de revisión

### Task 6: Tipos, payloads y frontera de privacidad

**Files:**
- Create: `apu_tool/dominio/revision.py`, `tests/test_revision_privacidad.py`

- [ ] **Step 1: Escribe el test que falla**

Crea `tests/test_revision_privacidad.py`:

```python
"""La revisión también respeta el invariante #1: la IA nunca ve dinero."""
import pytest

from apu_tool.dominio import privacy, revision
from apu_tool.nucleo.models import (
    CorridaItemRow, DePricedApu, DePricedComponent, LicitacionItem,
)


def _fila(seq=0):
    return CorridaItemRow(
        seq=seq,
        item=LicitacionItem(item="1", descripcion="EXCAVACION MANUAL", unidad="M3",
                            cantidad=12.5, precio_contractual=999999, shift="DIURNO"),
        status="auto", apu_codigo="100", apu_nombre="EXCAVACION MANUAL", unidad="M3",
        shift="DIURNO", origen="historico", confianza=0.9, explicacion="",
        componentes=[], candidatos=[{"apu_codigo": "200", "apu_nombre": "EXCAVACION MECANICA",
                                     "score": 0.71, "motivo": ""}])


def test_payload_de_barrido_no_lleva_dinero():
    p = revision.payload_barrido(_fila())
    privacy.assert_no_money(p)            # no lanza
    assert "precio_contractual" not in privacy.safe_json(p)


def test_payload_de_barrido_no_lleva_el_score_del_matcher():
    """Si le damos la nota del fuzzy, la copia en vez de pensar."""
    texto = privacy.safe_json(revision.payload_barrido(_fila()))
    assert "score" not in texto
    assert "0.71" not in texto


def test_payload_profundo_no_lleva_dinero():
    dp = DePricedApu(codigo="100", nombre="EXCAVACION MANUAL", unidad="M3",
                     shift="DIURNO", grupo="MOV",
                     componentes=[DePricedComponent(
                         insumo_codigo="4279", insumo_nombre="CUADRILLA", unidad="HR",
                         rendimiento=1.0, tipo="insumo")])
    p = revision.payload_profundo(_fila(), asignado=dp, candidatos=[dp])
    privacy.assert_no_money(p)
    assert "precio" not in privacy.safe_json(p).lower()


def test_un_precio_colado_revienta():
    p = revision.payload_barrido(_fila())
    p["actividad"]["costo_unitario"] = 12345
    with pytest.raises(privacy.PrivacyViolation):
        privacy.safe_json(p)
```

Antes de escribirlo, abre `apu_tool/nucleo/models.py` y confirma los nombres exactos de los campos de `DePricedApu` y `DePricedComponent`; usa esos, no los de este ejemplo si difieren.

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_revision_privacidad.py -q`
Expected: FAIL con `ImportError: cannot import name 'revision'`

- [ ] **Step 3: Crea el módulo con los tipos y los payloads**

Crea `apu_tool/dominio/revision.py`:

```python
"""
Revisión con IA de una corrida YA armada.

La IA no arma: audita. Recibe la corrida completa (sin dinero) y dice, por fila, si
el APU asignado le parece bien, dudoso, cambiable por otro candidato, o si para esa
actividad no hay nada en la biblioteca. **Propone; nunca aplica.** Quien aplica es
el usuario, con `confirmar_items`.

Dos pasos, por costo y por foco:
  1. BARRIDO   — lotes de filas, sin composiciones. Cada lote lleva además el índice
                 de la corrida entera, así la IA ve el presupuesto como un todo y
                 puede detectar incoherencias entre líneas. Devuelve ok | revisar.
  2. PROFUNDIZACIÓN — solo las marcadas `revisar`. Una llamada por fila, ahora con la
                 composición completa (insumos, rendimientos, unidades) del APU
                 asignado y de cada candidato.

Invariante #1: todo lo que sale de acá pasa por `privacy.safe_json`. En particular
NO va el `precio_contractual` del ítem (lo omite `licitacion_item_to_dict`) ni el
`score` del matcher: darle la nota del fuzzy hace que la copie en vez de pensar.

Sin `ANTHROPIC_API_KEY` no hay fallback determinístico, a propósito: un revisor
determinístico sería el matcher auditándose a sí mismo.
"""
from __future__ import annotations

import json
from dataclasses import dataclass, asdict
from typing import Any, Callable, Iterator, Optional

from apu_tool import config
from apu_tool.dominio import privacy
from apu_tool.nucleo.models import CorridaItemRow, DePricedApu

# Filas por llamada del barrido. Bajarlo mejora el foco de la IA y sube el costo;
# subirlo hace lo contrario. Es la palanca si al barrido se le escapan objeciones.
TAM_LOTE = 25

DICTAMENES = ("ok", "dudoso", "cambiar", "sin_apu")


@dataclass(frozen=True)
class Veredicto:
    seq: int
    dictamen: str                    # ok | dudoso | cambiar | sin_apu
    apu_sugerido: Optional[str]
    turno_sugerido: Optional[str]
    confianza: float
    justificacion: str
    nivel: str                       # barrido | profundo

    def to_dict(self) -> dict:
        return asdict(self)


# ------------------------------------------------------------------ payloads
def payload_barrido(fila: CorridaItemRow) -> dict[str, Any]:
    """Una fila para el barrido: sin composiciones y SIN el score del matcher."""
    return {
        "seq": fila.seq,
        "actividad": privacy.licitacion_item_to_dict(fila.item),
        "apu_asignado": (None if not fila.apu_codigo else {
            "codigo": fila.apu_codigo,
            "nombre": fila.apu_nombre,
            "unidad": fila.unidad,
            "shift": fila.shift,
        }),
        "candidatos": [{"codigo": c.get("apu_codigo"), "nombre": c.get("apu_nombre")}
                       for c in (fila.candidatos or [])],
    }


def indice_corrida(filas: list[CorridaItemRow]) -> list[dict[str, Any]]:
    """El presupuesto entero en una línea por ítem: contexto para ver incoherencias
    entre filas (dos actividades gemelas con APUs distintos)."""
    return [{"seq": f.seq, "descripcion": f.item.descripcion,
             "unidad": f.unidad, "apu": f.apu_codigo or None} for f in filas]


def payload_profundo(fila: CorridaItemRow, asignado: Optional[DePricedApu],
                     candidatos: list[DePricedApu]) -> dict[str, Any]:
    """Una fila con TODA la estructura: composiciones del asignado y de cada candidato."""
    return {
        "seq": fila.seq,
        "actividad": privacy.licitacion_item_to_dict(fila.item),
        "apu_asignado": (None if asignado is None
                         else privacy.depriced_apu_to_dict(asignado)),
        "candidatos": [privacy.depriced_apu_to_dict(a) for a in candidatos],
    }
```

- [ ] **Step 4: Corre el test y verifica que pasa**

Run: `python -m pytest tests/test_revision_privacidad.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/revision.py tests/test_revision_privacidad.py
git commit -m "feat(revision): tipos y payloads sin dinero para la revision con IA"
```

---

### Task 7: El barrido

**Files:**
- Modify: `apu_tool/dominio/revision.py`
- Test: `tests/test_revision_motor.py`

- [ ] **Step 1: Escribe el test que falla**

Crea `tests/test_revision_motor.py`:

```python
"""Barrido y profundización, con un revisor de doble (sin red)."""
import pytest

from apu_tool.dominio import revision
from apu_tool.nucleo.models import CorridaItemRow, LicitacionItem


def _fila(seq, desc, apu):
    return CorridaItemRow(
        seq=seq,
        item=LicitacionItem(item=str(seq + 1), descripcion=desc, unidad="M3",
                            cantidad=1, precio_contractual=0, shift="DIURNO"),
        status="auto", apu_codigo=apu, apu_nombre=f"APU {apu}", unidad="M3",
        shift="DIURNO", origen="historico", confianza=0.9, explicacion="",
        componentes=[], candidatos=[])


class RevisorDoble(revision.Revisor):
    """Sustituye la ÚNICA llamada al SDK. Sin red, sin mocks del cliente.

    `enabled=False` en el super para que NO intente construir `anthropic.Anthropic()`
    (en CI no hay API key y el constructor caería a enabled=False); después se
    fuerza `enabled` a True porque `_pedir` está sustituido y el cliente nunca se usa.
    """
    def __init__(self, respuestas):
        super().__init__(enabled=False)
        self.enabled = True
        self.respuestas = list(respuestas)
        self.pedidos = []

    def _pedir(self, system, schema, payload, effort):
        self.pedidos.append({"payload": payload, "effort": effort})
        return self.respuestas.pop(0)


def test_barrido_marca_solo_lo_que_la_ia_senala():
    filas = [_fila(0, "EXCAVACION MANUAL", "100"), _fila(1, "CONCRETO 3000 PSI", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"},
                                 {"seq": 1, "resultado": "revisar"}]}])
    marcadas = r.barrer(filas)
    assert marcadas == {1}


def test_barrido_parte_en_lotes_y_manda_el_indice_completo(monkeypatch):
    monkeypatch.setattr(revision, "TAM_LOTE", 2)
    filas = [_fila(i, f"ACTIVIDAD {i}", "100") for i in range(5)]
    r = RevisorDoble([{"filas": [{"seq": s, "resultado": "ok"}]} for s in (0, 2, 4)])
    r.barrer(filas)
    assert len(r.pedidos) == 3                       # 5 filas / lotes de 2
    for p in r.pedidos:
        assert len(p["payload"]["indice"]) == 5      # el presupuesto entero, siempre
    assert r.pedidos[0]["effort"] == "low"


def test_barrido_sin_respuesta_para_una_fila_no_la_da_por_buena():
    """Un lote que vuelve incompleto deja esas filas SIN veredicto, no en `ok`."""
    filas = [_fila(0, "A", "100"), _fila(1, "B", "200")]
    r = RevisorDoble([{"filas": [{"seq": 0, "resultado": "ok"}]}])
    assert r.barrer(filas) == set()
    assert r.sin_respuesta == {1}


def test_barrido_falla_si_la_ia_no_esta_disponible():
    r = revision.Revisor(enabled=False)
    with pytest.raises(revision.IANoDisponible):
        r.barrer([_fila(0, "A", "100")])
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_revision_motor.py -q`
Expected: FAIL con `AttributeError: module 'apu_tool.dominio.revision' has no attribute 'Revisor'`

- [ ] **Step 3: Implementa `Revisor` y `barrer`**

Agrega a `apu_tool/dominio/revision.py`:

```python
class IANoDisponible(RuntimeError):
    """No hay ANTHROPIC_API_KEY (o falta el SDK). La revisión no tiene fallback:
    un revisor determinístico sería el matcher auditándose a sí mismo."""


_SISTEMA_BARRIDO = """\
Eres un ingeniero de costos de obra civil auditando un presupuesto YA armado por un
programa determinístico. Para cada ACTIVIDAD te dan el APU que el programa le asignó
y los candidatos que descartó. Además recibes el ÍNDICE de todo el presupuesto.

Tu tarea: decir por cada fila si el APU asignado es razonable ("ok") o si merece un
análisis a fondo ("revisar").

Marca "revisar" cuando:
- la unidad del APU no cuadra con la de la actividad;
- el tipo de trabajo difiere (manual vs mecánico, suministro vs instalación);
- la actividad no tiene APU asignado;
- dos filas del índice describen la misma actividad pero tienen APUs distintos;
- un candidato descartado encaja claramente mejor que el asignado.

Reglas:
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- Responde por TODAS las filas del lote, usando su `seq` exacto.
- Ante la duda, marca "revisar": el paso siguiente mira a fondo y corrige.

Responde EXCLUSIVAMENTE con un JSON válido con este esquema:
{"filas": [{"seq": <int>, "resultado": "ok"|"revisar"}]}
"""

_ESQUEMA_BARRIDO = {
    "type": "object",
    "properties": {
        "filas": {
            "type": "array",
            "items": {
                "type": "object",
                "properties": {
                    "seq": {"type": "integer"},
                    "resultado": {"type": "string", "enum": ["ok", "revisar"]},
                },
                "required": ["seq", "resultado"],
                "additionalProperties": False,
            },
        },
    },
    "required": ["filas"],
    "additionalProperties": False,
}


class Revisor:
    """Fachada sobre la IA para la revisión. Sin fallback determinístico.

    `_pedir` es la ÚNICA puerta al SDK: los tests heredan de esta clase y la
    sustituyen, así no hace falta simular el cliente de anthropic.
    """

    def __init__(self, enabled: Optional[bool] = None, model: str = config.AI_MODEL):
        self.model = model
        self.enabled = config.ai_available() if enabled is None else enabled
        self._client = None
        # Filas de las que la IA no dijo nada (lote truncado o JSON inválido). No se
        # dan por buenas: quedan sin veredicto y se reportan.
        self.sin_respuesta: set[int] = set()
        if self.enabled:
            try:
                import anthropic
                self._client = anthropic.Anthropic()
            except Exception:
                self.enabled = False

    @property
    def disponible(self) -> bool:
        return bool(self.enabled)

    # ------------------------------------------------------------ puerta al SDK
    def _pedir(self, system: str, schema: dict, payload: dict, effort: str) -> dict:
        """Una llamada a la IA. Devuelve el JSON ya parseado, o {} si falló."""
        if self._client is None:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        contenido = privacy.safe_json(payload)   # garantía dura: sin dinero
        resp = self._client.messages.create(
            model=self.model,
            # Techo, no gasto: cubre el pensamiento adaptativo MÁS el JSON.
            max_tokens=16000,
            system=system,
            thinking={"type": "adaptive"},
            output_config={"effort": effort,
                           "format": {"type": "json_schema", "schema": schema}},
            messages=[{"role": "user", "content": contenido}],
        )
        texto = next((b.text for b in resp.content if b.type == "text"), "{}")
        try:
            return json.loads(texto)
        except Exception:
            return {}    # JSON truncado o inválido: nadie queda en "ok" por accidente

    # ------------------------------------------------------------------ barrido
    def barrer(self, filas: list[CorridaItemRow]) -> set[int]:
        """Devuelve los seq que merecen profundización. Deja en `self.sin_respuesta`
        los que la IA no contestó: esos NO se dan por buenos."""
        if not self.disponible:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        self.sin_respuesta = set()
        indice = indice_corrida(filas)
        marcadas: set[int] = set()
        for i in range(0, len(filas), TAM_LOTE):
            lote = filas[i:i + TAM_LOTE]
            payload = {"indice": indice,
                       "filas": [payload_barrido(f) for f in lote]}
            data = self._pedir(_SISTEMA_BARRIDO, _ESQUEMA_BARRIDO, payload, "low")
            vistos = set()
            for r in data.get("filas", []):
                try:
                    seq = int(r.get("seq"))
                except (TypeError, ValueError):
                    continue
                vistos.add(seq)
                if str(r.get("resultado")) == "revisar":
                    marcadas.add(seq)
            self.sin_respuesta |= {f.seq for f in lote if f.seq not in vistos}
        return marcadas
```

- [ ] **Step 4: Corre el test y verifica que pasa**

Run: `python -m pytest tests/test_revision_motor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/revision.py tests/test_revision_motor.py
git commit -m "feat(revision): barrido por lotes con el indice del presupuesto completo"
```

---

### Task 8: La profundización

**Files:**
- Modify: `apu_tool/dominio/revision.py`
- Test: `tests/test_revision_motor.py`

- [ ] **Step 1: Escribe el test que falla**

Agrega a `tests/test_revision_motor.py`:

```python
from apu_tool.nucleo.models import DePricedApu, DePricedComponent


def _dp(codigo, nombre, unidad="M3"):
    return DePricedApu(codigo=codigo, nombre=nombre, unidad=unidad, shift="DIURNO",
                       grupo="MOV",
                       componentes=[DePricedComponent(
                           insumo_codigo="4279", insumo_nombre="CUADRILLA", unidad="HR",
                           rendimiento=1.0, tipo="insumo")])


def test_profundizar_devuelve_cambiar_con_el_apu_sugerido():
    fila = _fila(3, "EXCAVACION MECANICA", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": "200",
                       "turno_sugerido": "DIURNO", "confianza": 0.85,
                       "justificacion": "la actividad es mecánica"}])
    v = r.profundizar(fila, asignado=_dp("100", "EXCAVACION MANUAL"),
                      candidatos=[_dp("200", "EXCAVACION MECANICA")])
    assert (v.dictamen, v.apu_sugerido, v.nivel) == ("cambiar", "200", "profundo")
    assert r.pedidos[0]["effort"] == "medium"


def test_sugerencia_que_no_esta_entre_los_candidatos_degrada_a_dudoso():
    """La IA no puede inventar un código: si sugiere uno que no le pasamos, se cae."""
    fila = _fila(3, "EXCAVACION MECANICA", "100")
    r = RevisorDoble([{"dictamen": "cambiar", "apu_sugerido": "9999",
                       "turno_sugerido": "DIURNO", "confianza": 0.9,
                       "justificacion": "x"}])
    v = r.profundizar(fila, asignado=_dp("100", "EXCAVACION MANUAL"),
                      candidatos=[_dp("200", "EXCAVACION MECANICA")])
    assert v.dictamen == "dudoso"
    assert v.apu_sugerido is None
    assert "9999" in v.justificacion


def test_dictamen_desconocido_degrada_a_dudoso():
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{"dictamen": "explota", "apu_sugerido": None,
                       "turno_sugerido": None, "confianza": 0.5, "justificacion": ""}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[])
    assert v.dictamen == "dudoso"


def test_respuesta_vacia_degrada_a_dudoso():
    fila = _fila(3, "A", "100")
    r = RevisorDoble([{}])
    v = r.profundizar(fila, asignado=_dp("100", "A"), candidatos=[])
    assert v.dictamen == "dudoso"
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_revision_motor.py -q`
Expected: FAIL con `AttributeError: 'RevisorDoble' object has no attribute 'profundizar'`

- [ ] **Step 3: Implementa `profundizar`**

Agrega a `apu_tool/dominio/revision.py`, antes de la clase `Revisor`:

```python
_SISTEMA_PROFUNDO = """\
Eres un ingeniero de costos de obra civil auditando UNA línea de un presupuesto ya
armado. Te dan la ACTIVIDAD, el APU que se le asignó con su composición completa
(insumos, unidades y rendimientos) y los APUs candidatos con la suya.

Tu tarea: decidir cuál de estos cuatro dictámenes corresponde.
- "ok": el APU asignado es el correcto para esta actividad.
- "dudoso": no puedes decidir con lo que tienes; alguien tiene que mirarlo.
- "cambiar": otro de los candidatos es claramente mejor. Devuelve su código en
  `apu_sugerido` — SOLO códigos que estén en la lista de candidatos.
- "sin_apu": ninguno sirve; para esta actividad no hay nada adecuado en la biblioteca.

Reglas:
- Decides por afinidad técnica: unidad, tipo de trabajo, e insumos y rendimientos de
  la composición.
- NUNCA recibirás precios ni costos, y no debes inventarlos ni pedirlos.
- NUNCA inventes un código de APU. Si el que quieres no está entre los candidatos,
  el dictamen es "sin_apu" o "dudoso".
- La justificación va en una frase corta, en español.

Responde EXCLUSIVAMENTE con un JSON válido con este esquema:
{"dictamen": "ok"|"dudoso"|"cambiar"|"sin_apu",
 "apu_sugerido": <string|null>, "turno_sugerido": <string|null>,
 "confianza": <number 0..1>, "justificacion": <string corto>}
"""

_ESQUEMA_PROFUNDO = {
    "type": "object",
    "properties": {
        "dictamen": {"type": "string", "enum": list(DICTAMENES)},
        "apu_sugerido": {"type": ["string", "null"]},
        "turno_sugerido": {"type": ["string", "null"]},
        "confianza": {"type": "number"},
        "justificacion": {"type": "string"},
    },
    "required": ["dictamen", "apu_sugerido", "turno_sugerido", "confianza",
                 "justificacion"],
    "additionalProperties": False,
}
```

Y como método de `Revisor`:

```python
    def profundizar(self, fila: CorridaItemRow, asignado: Optional[DePricedApu],
                    candidatos: list[DePricedApu]) -> Veredicto:
        """Dictamen final de UNA fila, con las composiciones completas a la vista."""
        if not self.disponible:
            raise IANoDisponible("La revisión con IA necesita ANTHROPIC_API_KEY.")
        data = self._pedir(_SISTEMA_PROFUNDO, _ESQUEMA_PROFUNDO,
                           payload_profundo(fila, asignado, candidatos), "medium")
        dictamen = str(data.get("dictamen") or "")
        sugerido = data.get("apu_sugerido")
        sugerido = str(sugerido).strip() if sugerido else None
        turno = data.get("turno_sugerido")
        turno = str(turno).strip() if turno else None
        just = str(data.get("justificacion") or "").strip()
        try:
            conf = float(data.get("confianza") or 0.0)
        except (TypeError, ValueError):
            conf = 0.0

        validos = {a.codigo for a in candidatos}
        if dictamen not in DICTAMENES:
            # JSON vacío, truncado o un dictamen que no existe: nadie sale en "ok"
            # por accidente. "dudoso" manda la decisión al humano, que es lo correcto.
            dictamen, sugerido, turno = "dudoso", None, None
            just = just or "La IA no devolvió un dictamen legible."
        elif dictamen == "cambiar" and (sugerido is None or sugerido not in validos):
            # La IA no puede inventar un código. Si el que pide no estaba entre los
            # candidatos que le dimos, no existe para esta decisión.
            just = (f"La IA sugirió el APU {sugerido}, que no estaba entre los "
                    f"candidatos. {just}").strip()
            dictamen, sugerido, turno = "dudoso", None, None

        return Veredicto(seq=fila.seq, dictamen=dictamen, apu_sugerido=sugerido,
                         turno_sugerido=turno, confianza=conf, justificacion=just,
                         nivel="profundo")
```

- [ ] **Step 4: Corre el test y verifica que pasa**

Run: `python -m pytest tests/test_revision_motor.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/revision.py tests/test_revision_motor.py
git commit -m "feat(revision): profundizacion por fila; una sugerencia inventada degrada a dudoso"
```

---

### Task 9: El orquestador `revisar`

**Files:**
- Modify: `apu_tool/dominio/revision.py`
- Test: `tests/test_revision_motor.py`

- [ ] **Step 1: Escribe el test que falla**

Agrega a `tests/test_revision_motor.py`:

```python
@pytest.fixture()
def alm_apus(tmp_path):
    """Almacén con los APUs 100 y 200, para que `revisar` pueda pedir sus DePriced."""
    from apu_tool.datos.almacen import Almacen
    from apu_tool.nucleo.models import Apu, ApuComponent, Insumo

    a = Almacen(tmp_path / "p.db", tmp_path / "a.db", tmp_path / "c.db")
    a.reset()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV"),
                        Apu("200", "CONCRETO 3000 PSI", "M3", "DIURNO", "EST")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000),
        ApuComponent("200", "DIURNO", "4279", "CUADRILLA", "HR", 2.0, 40000)])
    return a


def test_revisar_emite_eventos_y_solo_profundiza_lo_marcado(alm_apus):
    filas = [_fila(0, "EXCAVACION MANUAL", "100"), _fila(1, "CONCRETO", "200")]
    r = RevisorDoble([
        {"filas": [{"seq": 0, "resultado": "ok"}, {"seq": 1, "resultado": "revisar"}]},
        {"dictamen": "ok", "apu_sugerido": None, "turno_sugerido": None,
         "confianza": 0.9, "justificacion": "correcto"},
    ])
    eventos = list(revision.revisar(alm_apus, filas, r))
    tipos = [e for e, _ in eventos]
    assert tipos[0] == "started"
    assert "barrido" in tipos
    assert tipos[-1] == "done"
    # Dos veredictos (uno por fila) pero UNA sola profundización.
    veredictos = [p["veredicto"] for e, p in eventos if e == "veredicto"]
    assert len(veredictos) == 2
    assert {v["nivel"] for v in veredictos} == {"barrido", "profundo"}
    assert len(r.pedidos) == 2      # 1 barrido + 1 profundización
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_revision_motor.py -q`
Expected: FAIL con `AttributeError: module ... has no attribute 'revisar'`

- [ ] **Step 3: Implementa `revisar`**

Agrega al final de `apu_tool/dominio/revision.py`:

```python
def revisar(almacen, filas: list[CorridaItemRow], revisor: Revisor,
            ) -> Iterator[tuple[str, dict]]:
    """Revisa la corrida entera y emite eventos, para que el llamador (el endpoint
    SSE) persista y reporte en vivo:

      ('started',  {'total'})
      ('barrido',  {'revisar': n, 'sin_respuesta': [seq, ...]})
      ('veredicto',{'seq', 'veredicto': {...}})   — por fila, ya lista para guardar
      ('done',     {'total', 'ok', 'dudoso', 'cambiar', 'sin_apu', 'sin_veredicto'})

    Las filas que el barrido no contestó quedan SIN veredicto (no se inventa un `ok`)
    y salen contadas en `sin_veredicto`.
    """
    yield ("started", {"total": len(filas)})
    marcadas = revisor.barrer(filas)
    sin_respuesta = set(revisor.sin_respuesta)
    yield ("barrido", {"revisar": len(marcadas),
                       "sin_respuesta": sorted(sin_respuesta)})

    conteo = {d: 0 for d in DICTAMENES}
    for fila in filas:
        if fila.seq in sin_respuesta:
            continue
        if fila.seq not in marcadas:
            v = Veredicto(seq=fila.seq, dictamen="ok", apu_sugerido=None,
                          turno_sugerido=None, confianza=0.0,
                          justificacion="Sin objeciones en el barrido.",
                          nivel="barrido")
        else:
            asignado = (almacen.apus.get_depriced_apu(fila.apu_codigo, fila.shift)
                        if fila.apu_codigo else None)
            candidatos = []
            for c in (fila.candidatos or []):
                dp = almacen.apus.get_depriced_apu(c.get("apu_codigo"), fila.shift)
                if dp is not None:
                    candidatos.append(dp)
            v = revisor.profundizar(fila, asignado, candidatos)
        conteo[v.dictamen] = conteo.get(v.dictamen, 0) + 1
        yield ("veredicto", {"seq": fila.seq, "veredicto": v.to_dict()})

    yield ("done", {"total": len(filas), **conteo,
                    "sin_veredicto": len(sin_respuesta)})
```

- [ ] **Step 4: Corre el test y verifica que pasa**

Run: `python -m pytest tests/test_revision_motor.py -q`
Expected: PASS

- [ ] **Step 5: Corre la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/dominio/revision.py tests/test_revision_motor.py
git commit -m "feat(revision): orquestador que emite eventos y solo profundiza lo marcado"
```

---

## FASE 5 — API

### Task 10: Endpoint SSE de revisión

**Files:**
- Modify: `apu_tool/servicio/corridas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_revision.py`

- [ ] **Step 1: Escribe el test que falla**

Crea `tests/test_api_revision.py`. Los tests de API de este repo **no usan fixtures**:
usan un helper que devuelve `(cli, alm)` (ver `tests/test_api_corridas.py:14`).

```python
"""Endpoint de revisión: SSE, rol, corrida congelada, persistencia del veredicto."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import (
    Apu, ApuComponent, CorridaItemRow, CorridaMeta, Insumo, LicitacionItem,
)
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cliente_api(tmp_path):
    a = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                corridas_path=tmp_path / "c.db")
    a.init_schema()
    a.precios.insert_insumos([Insumo("4279", "CUADRILLA", "HR", "MO", 40000, "PRECIO IDU")])
    a.apus.insert_apus([Apu("100", "EXCAVACION MANUAL", "M3", "DIURNO", "MOV"),
                        Apu("200", "EXCAVACION MECANICA", "M3", "DIURNO", "MOV")])
    a.apus.insert_components([
        ApuComponent("100", "DIURNO", "4279", "CUADRILLA", "HR", 1.0, 40000),
        ApuComponent("200", "DIURNO", "4279", "CUADRILLA", "HR", 0.4, 40000)])
    return cliente(create_app(almacen=a), rol="admin"), a


def _corrida_armada(alm) -> int:
    """Dos filas, las dos con el APU 100 asignado."""
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-08-31T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for seq, desc in enumerate(("EXCAVACION MANUAL", "EXCAVACION A MAQUINA")):
        alm.corridas.agregar_item(cid, CorridaItemRow(
            seq=seq,
            item=LicitacionItem(item=str(seq + 1), descripcion=desc, unidad="M3",
                                cantidad=10, precio_contractual=1000, shift="DIURNO"),
            status="auto", apu_codigo="100", apu_nombre="EXCAVACION MANUAL",
            unidad="M3", shift="DIURNO", origen="historico", confianza=0.9,
            explicacion="", componentes=[],
            candidatos=[{"apu_codigo": "200", "apu_nombre": "EXCAVACION MECANICA",
                         "score": 0.7, "motivo": ""}]))
    return cid


def test_revision_stream_guarda_los_veredictos(tmp_path, monkeypatch):
    from apu_tool.dominio import revision
    from apu_tool.servicio import corridas as svc

    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)

    class Doble(revision.Revisor):
        def __init__(self, *a, **k):
            super().__init__(enabled=False)   # no toca el SDK
            self.enabled = True               # ...pero se comporta como disponible
        def _pedir(self, system, schema, payload, effort):
            if "indice" in payload:
                return {"filas": [{"seq": f["seq"], "resultado": "revisar"}
                                  for f in payload["filas"]]}
            return {"dictamen": "cambiar", "apu_sugerido": "200",
                    "turno_sugerido": "DIURNO", "confianza": 0.9,
                    "justificacion": "mejor encaje"}

    monkeypatch.setattr(svc, "Revisor", Doble)
    r = cli.post(f"/api/corridas/{cid}/revision/stream")
    assert r.status_code == 200
    assert "event: done" in r.text
    guardados = alm.corridas.get_revisiones(cid)
    assert guardados[0]["dictamen"] == "cambiar"
    assert guardados[0]["apu_sugerido"] == "200"


def test_revision_de_corrida_congelada_da_409(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/revision/stream")
    assert r.status_code == 409


def test_revision_sin_api_key_da_409(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    r = cli.post(f"/api/corridas/{cid}/revision/stream")
    assert r.status_code == 409
    assert "ANTHROPIC_API_KEY" in r.json()["detail"]


def test_la_vista_trae_el_veredicto_y_si_hay_ia(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    alm.corridas.set_revision(cid, 0, {"seq": 0, "dictamen": "dudoso",
                                           "apu_sugerido": None, "turno_sugerido": None,
                                           "confianza": 0.4, "justificacion": "x",
                                           "nivel": "profundo"})
    v = cli.get(f"/api/corridas/{cid}").json()
    assert v["items"][0]["revision"]["dictamen"] == "dudoso"
    assert "ia_disponible" in v
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_api_revision.py -q`
Expected: FAIL (404 en el endpoint que todavía no existe)

- [ ] **Step 3: Servicio de revisión**

En `apu_tool/servicio/corridas.py`, agrega al bloque de imports:

```python
from apu_tool.dominio.revision import IANoDisponible, Revisor, revisar
```

y la función de servicio:

```python
def revisar_corrida_stream(alm: Almacen, corrida_id: int):
    """Revisa una corrida ya armada y emite eventos SSE, persistiendo cada veredicto
    apenas sale. Si la IA falla a mitad, lo ya guardado se queda: re-correr solo
    vuelve a pedir lo que no tiene veredicto.

    Eventos: los de `dominio.revision.revisar`, más ('error', {'detail'}).
    Lanza CorridaCongelada (una foto no se revisa) e IANoDisponible.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    # ponytail: dos revisiones simultáneas sobre la misma corrida se pisan (gana la
    # última). Los veredictos son por fila e idempotentes, así que el daño es gastar
    # dos veces, no corromper. Si molesta, el arreglo es un lock por corrida.
    revisor = Revisor()
    if not revisor.disponible:
        raise IANoDisponible(
            "La revisión con IA necesita ANTHROPIC_API_KEY en el servidor.")
    filas = alm.corridas.get_items(corrida_id)
    try:
        for evento, payload in revisar(alm, filas, revisor):
            if evento == "veredicto":
                alm.corridas.set_revision(corrida_id, payload["seq"], payload["veredicto"])
            yield (evento, payload)
    except Exception as exc:
        # Lo ya persistido se queda. El detalle del error no expone internals.
        yield ("error", {"detail": f"La revisión se interrumpió: {type(exc).__name__}. "
                                   f"Los veredictos ya guardados se conservan."})
```

- [ ] **Step 4: El veredicto y la disponibilidad viajan en la vista**

En `apu_tool/servicio/corridas.py`, cambia la firma y el cuerpo de `_vista_item` para que acepte el veredicto:

```python
def _vista_item(ens: AssembledApu, seq: int, status: str,
                revision: Optional[dict] = None) -> dict:
    return {
        ...   # (todos los campos actuales, sin tocar)
        "alertas_costeo": alertas_costeo(ens),
        "revision": revision,
    }
```

En `vista_corrida`, pasa el veredicto de cada fila:

```python
    items = [_vista_item(ens, r.seq, r.status, r.revision)
             for ens, r in zip(ensambles, rows)]
```

y agrega al dict que devuelve, junto a `"duracion_ms"`:

```python
        # Si el servidor puede revisar con IA: el botón se apaga solo, sin pedirle
        # al frontend que adivine.
        "ia_disponible": config.ai_available(),
```

Nota: `GET /api/status` ya devuelve un booleano `ia` con lo mismo. Va acá igual porque
la página de corrida ya pide esta vista y no `/status`: un campo frente a una petición
más. No borres el de `/status` — lo usan otros tests.

`construir_corrida_stream` y `agregar_items` llaman a `_vista_item` con tres argumentos: como el cuarto tiene default `None`, no hay que tocarlos.

- [ ] **Step 5: El endpoint**

En `apu_tool/servicio/rutas.py`, junto a los otros endpoints de corrida:

```python
@router.post("/corridas/{cid}/revision/stream")
def revisar_corrida(cid: int, alm: Almacen = Depends(get_almacen),
                    _: object = Depends(requiere_rol("editor"))):
    """Audita la corrida con IA. Propone; no aplica nada."""
    if svc.vista_corrida(alm, cid) is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    try:
        gen = svc.revisar_corrida_stream(alm, cid)
        primero = next(gen)          # dispara las validaciones antes del stream
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para revisarla.")
    except svc.IANoDisponible as e:
        raise HTTPException(status_code=409, detail=str(e))

    def _con_el_primero():
        yield primero
        yield from gen

    return StreamingResponse(_event_stream(_con_el_primero()),
                             media_type="text/event-stream",
                             headers={"Cache-Control": "no-cache",
                                      "X-Accel-Buffering": "no"})
```

Copia el dict de `headers` exacto del endpoint `crear_corrida_stream` que ya existe en ese archivo, para no divergir. Agrega `IANoDisponible` a lo que `corridas.py` reexporta (el `import` del Step 3 ya lo deja accesible como `svc.IANoDisponible`).

- [ ] **Step 6: Corre el test**

Run: `python -m pytest tests/test_api_revision.py -q`
Expected: PASS

- [ ] **Step 7: Corre la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/corridas.py apu_tool/servicio/rutas.py tests/test_api_revision.py
git commit -m "feat(api): endpoint SSE de revision con IA; el veredicto viaja en la vista"
```

---

### Task 11: Aplicar N sugerencias distintas en una llamada

**Files:**
- Modify: `apu_tool/servicio/corridas.py`, `apu_tool/servicio/esquemas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_revision.py`

Contexto: `confirmar_items` ya valida que el APU exista antes de escribir, hace un solo recosteo y un solo `vista_corrida`. Se le agrega un parámetro opcional en vez de duplicar todo eso en un endpoint nuevo. **`tests/test_corridas_confirmar_lote.py` tiene que seguir verde sin tocarlo**: esa es la prueba de que el camino viejo no cambió.

- [ ] **Step 1: Escribe el test que falla**

Agrega a `tests/test_api_revision.py`:

```python
def test_aplicar_sugerencias_distintas_en_una_llamada(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)     # seq 0 y 1, ambos con APU "100"
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [],
        "asignaciones": [
            {"seq": 0, "apu_codigo": "200", "shift": "DIURNO"},
            {"seq": 1, "apu_codigo": "100", "shift": "DIURNO"},
        ],
    })
    assert r.status_code == 200
    items = {i["seq"]: i for i in r.json()["items"]}
    assert items[0]["apu_codigo"] == "200"
    assert items[1]["apu_codigo"] == "100"
    # Aplicar cambia el APU -> el veredicto de esas filas se borra solo.
    assert alm.corridas.get_revisiones(cid) == {}


def test_asignacion_con_apu_inexistente_falla_sin_aplicar_nada(tmp_path):
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote", json={
        "seqs": [],
        "asignaciones": [
            {"seq": 0, "apu_codigo": "200", "shift": "DIURNO"},
            {"seq": 1, "apu_codigo": "NO_EXISTE", "shift": "DIURNO"},
        ],
    })
    assert r.status_code == 400
    v = cli.get(f"/api/corridas/{cid}").json()
    assert v["items"][0]["apu_codigo"] == "100"    # nada se aplicó a medias
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_api_revision.py -q`
Expected: FAIL (422 o 200 con los APUs sin cambiar)

- [ ] **Step 3: Extiende `confirmar_items`**

En `apu_tool/servicio/corridas.py`, cambia la firma:

```python
def confirmar_items(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                    apu_codigo: Optional[str] = None,
                    shift: Optional[str] = None,
                    asignaciones: Optional[dict[int, tuple[str, Optional[str]]]] = None,
                    ) -> Optional[dict]:
```

Agrega al docstring, después del párrafo que explica `apu_codigo=None`:

```
    `asignaciones` (seq -> (código, turno)) aplica un APU DISTINTO por fila en un
    solo recosteo: es lo que usa "aplicar N sugerencias de la IA". Cuando se pasa,
    los seq salen de ahí y `seqs` se ignora. Gana sobre `apu_codigo` fila por fila.
```

Justo después de `seqs_pedidos = list(seqs)`, agrega:

```python
    if asignaciones:
        seqs_pedidos = list(asignaciones)
```

y dentro del bucle `for seq in seqs_pedidos:`, reemplaza las dos líneas que resuelven código y turno por:

```python
        propuesto = (asignaciones or {}).get(seq)
        codigo = (propuesto[0] if propuesto else (apu_codigo or row.apu_codigo))
        if not codigo:
            continue                      # nada que confirmar (evita el $0)
        turno = (propuesto[1] if propuesto and propuesto[1] else shift) or row.shift
```

- [ ] **Step 4: DTO**

En `apu_tool/servicio/esquemas.py`, encima de `ConfirmarLoteIn`:

```python
class AsignacionIn(BaseModel):
    """Una sugerencia aplicada: a esta fila, este APU."""
    seq: int
    apu_codigo: str
    shift: Optional[str] = None
```

y agrega el campo a `ConfirmarLoteIn`:

```python
class ConfirmarLoteIn(BaseModel):
    seqs: list[int]
    apu_codigo: Optional[str] = None
    shift: Optional[str] = None
    # Un APU distinto por fila (aplicar sugerencias de la IA). Cuando viene, manda
    # sobre `seqs` y `apu_codigo`.
    asignaciones: Optional[list[AsignacionIn]] = None
```

- [ ] **Step 5: Endpoint**

En `apu_tool/servicio/rutas.py`, dentro de `confirmar_lote`, cambia la llamada:

```python
        mapa = ({a.seq: (a.apu_codigo, a.shift) for a in body.asignaciones}
                if body.asignaciones else None)
        v = svc.confirmar_items(alm, cid, body.seqs, body.apu_codigo, body.shift,
                                asignaciones=mapa)
```

Importa `AsignacionIn` si el archivo importa los DTOs por nombre.

- [ ] **Step 6: Corre los tests**

Run: `python -m pytest tests/test_api_revision.py tests/test_corridas_confirmar_lote.py -q`
Expected: PASS, y `test_corridas_confirmar_lote.py` **sin haber sido modificado**.

- [ ] **Step 7: Corre la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 8: Commit**

```bash
git add apu_tool/servicio/ tests/test_api_revision.py
git commit -m "feat(api): confirmar-lote acepta un APU distinto por fila (aplicar sugerencias)"
```

---

### Task 12: Componer un APU a pedido

**Files:**
- Modify: `apu_tool/servicio/corridas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_api_revision.py`

Contexto: esto es lo único que queda de la composición generativa, y solo se dispara si el usuario pulsa un botón. **No persiste nada**: devuelve una propuesta.

- [ ] **Step 1: Escribe el test que falla**

Agrega a `tests/test_api_revision.py`:

```python
def test_componer_devuelve_propuesta_sin_persistir(tmp_path, monkeypatch):
    from apu_tool.servicio import corridas as svc

    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)

    class AdvisorDoble:
        def compose_apu(self, item, insumos, ejemplos):
            class C:
                componentes = [type("X", (), {"insumo_codigo": "4279",
                                              "rendimiento": 2.0})()]
                justificacion = "cuadrilla base"; confianza = 0.7
            return C()

    monkeypatch.setattr(svc, "ApuAdvisor", lambda *a, **k: AdvisorDoble())
    antes = alm.counts()["apus"]
    r = cli.post(f"/api/corridas/{cid}/componer/0")
    assert r.status_code == 200
    d = r.json()
    assert d["componentes"][0]["insumo_codigo"] == "4279"
    assert d["componentes"][0]["rendimiento"] == 2.0
    assert "justificacion" in d
    assert alm.counts()["apus"] == antes     # NO creó ningún APU


def test_componer_sin_ia_da_409(tmp_path, monkeypatch):
    monkeypatch.delenv("ANTHROPIC_API_KEY", raising=False)
    cli, alm = _cliente_api(tmp_path)
    cid = _corrida_armada(alm)
    r = cli.post(f"/api/corridas/{cid}/componer/0")
    assert r.status_code == 409
```

- [ ] **Step 2: Corre el test y verifica que falla**

Run: `python -m pytest tests/test_api_revision.py -q`
Expected: FAIL (404)

- [ ] **Step 3: Servicio**

En `apu_tool/servicio/corridas.py`:

```python
def componer_item(alm: Almacen, corrida_id: int, seq: int) -> Optional[dict]:
    """PROPONE una composición para una fila sin APU. No escribe nada.

    Es el único uso que queda de la composición generativa, y solo llega acá por un
    clic del usuario en una fila que la revisión dictaminó `sin_apu`. Lo que vuelve
    es una propuesta: crear el APU sigue siendo el alta de siempre, con sus
    validaciones de duplicados.

    None si la corrida o la fila no existen. Lanza IANoDisponible sin IA, y
    ValueError si la IA no pudo componer.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    row = alm.corridas.get_item(corrida_id, seq)
    if row is None:
        return None
    advisor = ApuAdvisor()
    if not advisor.enabled:
        raise IANoDisponible(
            "Componer con IA necesita ANTHROPIC_API_KEY en el servidor.")
    assembler = Assembler(alm, advisor=advisor, lista_id=meta.lista_precios_id,
                          contexto=_contexto(alm, meta))
    ens = assembler.generar_composicion(row.item)
    if ens is None:
        raise ValueError("La IA no pudo componer un APU para esta actividad.")
    return {
        "seq": seq,
        "nombre": row.item.descripcion,
        "unidad": row.item.unidad,
        "shift": row.shift,
        "justificacion": ens.explicacion,
        "confianza": ens.confianza,
        "componentes": [{"insumo_codigo": c.insumo_codigo,
                         "insumo_nombre": c.insumo_nombre,
                         "unidad": c.unidad,
                         "rendimiento": c.rendimiento} for c in ens.componentes],
    }
```

- [ ] **Step 4: Endpoint**

En `apu_tool/servicio/rutas.py`:

```python
@router.post("/corridas/{cid}/componer/{seq}")
def componer_item(cid: int, seq: int, alm: Almacen = Depends(get_almacen),
                  _: object = Depends(requiere_rol("editor"))):
    """Propone una composición para una fila sin APU. No crea nada en la biblioteca."""
    try:
        d = svc.componer_item(alm, cid, seq)
    except svc.IANoDisponible as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
    if d is None:
        raise HTTPException(status_code=404, detail="Ítem no encontrado.")
    return d
```

- [ ] **Step 5: Corre el test**

Run: `python -m pytest tests/test_api_revision.py -q`
Expected: PASS

- [ ] **Step 6: Corre la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/ tests/test_api_revision.py
git commit -m "feat(api): componer un APU con IA solo a pedido, y sin persistir nada"
```

---

## FASE 6 — Interfaz web

### Task 13: Tipos y cliente de API

**Files:**
- Modify: `web/src/lib/tipos.ts`, `web/src/api/corridas.ts`

- [ ] **Step 1: Tipos**

En `web/src/lib/tipos.ts`, agrega encima de `ItemCuadro`:

```ts
export type DictamenIA = "ok" | "dudoso" | "cambiar" | "sin_apu";

/** Lo que la IA opinó de una línea. La IA propone; aplicar es del usuario. */
export interface VeredictoIA {
  seq: number;
  dictamen: DictamenIA;
  apu_sugerido: string | null;
  turno_sugerido: string | null;
  confianza: number;
  justificacion: string;
  nivel: "barrido" | "profundo";
}

/** Una composición propuesta por la IA, sin crear nada todavía. */
export interface ComposicionPropuesta {
  seq: number;
  nombre: string;
  unidad: string;
  shift: string;
  justificacion: string;
  confianza: number;
  componentes: {
    insumo_codigo: string;
    insumo_nombre: string;
    unidad: string;
    rendimiento: number;
  }[];
}

/** Progreso del stream de revisión. */
export interface ProgresoRevision {
  total: number;
  revisadas: number;
}
```

Agrega a `ItemCuadro`:

```ts
  revision: VeredictoIA | null;
```

Agrega a `CorridaDetalle`:

```ts
  ia_disponible?: boolean;
```

(Opcional para no romper los objetos que la página construye a mano durante el armado en vivo.)

- [ ] **Step 2: Cliente**

En `web/src/api/corridas.ts`, agrega a los imports de tipos `ComposicionPropuesta`, `VeredictoIA`, y agrega:

```ts
/** Aplica varias sugerencias de la IA de una sola vez (un recosteo). */
export function aplicarSugerencias(
  id: number,
  asignaciones: { seq: number; apu_codigo: string; shift?: string | null }[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/confirmar-lote`, {
    seqs: [],
    asignaciones,
  });
}

export function componerItem(id: number, seq: number): Promise<ComposicionPropuesta> {
  return apiPost<ComposicionPropuesta>(`/corridas/${id}/componer/${seq}`, {});
}

/** Revisa la corrida con IA. Llama `onVeredicto` por fila, según van llegando. */
export async function revisarCorridaStream(
  id: number,
  onVeredicto: (v: VeredictoIA) => void,
  onBarrido?: (n: number) => void,
): Promise<Record<string, number>> {
  const r = await fetch(`/api/corridas/${id}/revision/stream`, {
    method: "POST",
    headers: { ...(await authHeader()) },
  });
  if (!r.ok || !r.body) {
    const err = await r.json().catch(() => ({}) as { detail?: string });
    throw new Error(err.detail || r.statusText);
  }
  const reader = r.body.getReader();
  const decoder = new TextDecoder();
  let buf = "";
  let resumen: Record<string, number> | null = null;
  for (;;) {
    const { value, done: fin } = await reader.read();
    if (fin) break;
    buf += decoder.decode(value, { stream: true });
    let idx: number;
    while ((idx = buf.indexOf("\n\n")) >= 0) {
      const ev = parseSse(buf.slice(0, idx));
      buf = buf.slice(idx + 2);
      if (!ev) continue;
      if (ev.event === "veredicto")
        onVeredicto((ev.data as { veredicto: VeredictoIA }).veredicto);
      else if (ev.event === "barrido")
        onBarrido?.((ev.data as { revisar: number }).revisar);
      else if (ev.event === "done") resumen = ev.data as Record<string, number>;
      else if (ev.event === "error")
        throw new Error((ev.data as { detail?: string }).detail || "Error al revisar");
    }
  }
  if (!resumen) throw new Error("La revisión no terminó correctamente.");
  return resumen;
}
```

`parseSse` y `authHeader` ya están importados/definidos en ese archivo. Reutilízalos; no dupliques el parser.

- [ ] **Step 3: Compila**

Run: `cd web && npm run build`
Expected: build OK. Si `tsc -b` se queja porque los mocks de tests no traen el campo `revision` en `ItemCuadro`, agrégalo como `revision: null` en esos fixtures de test — no lo hagas opcional en el tipo: la vista siempre lo manda.

- [ ] **Step 4: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts
git commit -m "feat(web): tipos y cliente para la revision con IA"
```

---

### Task 14: Columna Veredicto en la tabla

**Files:**
- Modify: `web/src/lib/corridaTabla.ts`, `web/src/components/corrida/TablaItems.tsx`
- Test: `web/src/components/corrida/TablaItems.test.tsx`

- [ ] **Step 1: Escribe la prueba que falla**

En `web/src/components/corrida/TablaItems.test.tsx`, agrega:

Este archivo mockea `@/api/corridas` entero: agrégale `aplicarSugerencias` o el
import de `TablaItems.tsx` fallará.

```tsx
  aplicarSugerencias: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
  })),
```

Y el test (`ITEM` es la constante que ya está en el archivo):

```tsx
test("muestra el dictamen de la IA y aplica el cambio sugerido", async () => {
  const { default: TablaItems } = await import("./TablaItems");
  const { aplicarSugerencias } = await import("@/api/corridas");
  const items = [
    { ...ITEM, seq: 0,
      revision: { seq: 0, dictamen: "ok", apu_sugerido: null, turno_sugerido: null,
                  confianza: 0, justificacion: "Sin objeciones en el barrido.",
                  nivel: "barrido" } },
    { ...ITEM, seq: 1, descripcion: "Excavación",
      revision: { seq: 1, dictamen: "cambiar", apu_sugerido: "222",
                  turno_sugerido: "DIURNO", confianza: 0.9,
                  justificacion: "la actividad es mecánica", nivel: "profundo" } },
  ];
  render(<TablaItems corridaId={1} items={items as never} onConfirmado={() => {}}
                     puedeEditar />);

  expect(screen.getByText("✔ ok")).toBeInTheDocument();
  expect(screen.getByText("↔ cambiar")).toBeInTheDocument();

  fireEvent.click(screen.getByRole("button", { name: /aplicar/i }));
  await waitFor(() =>
    expect(aplicarSugerencias).toHaveBeenCalledWith(1, [
      { seq: 1, apu_codigo: "222", shift: "DIURNO" },
    ]),
  );
});
```

Si `TablaItems` recibe `control` en los otros tests de este archivo, pásale lo mismo
que ellos; el ejemplo omite props que no cambian nada para esta prueba.

- [ ] **Step 2: Corre la prueba y verifica que falla**

Run: `cd web && npm test -- TablaItems`
Expected: FAIL

- [ ] **Step 3: Helper de presentación**

En `web/src/lib/corridaTabla.ts`, agrega y expórtalo:

```ts
import type { DictamenIA, ItemCuadro } from "@/lib/tipos";

/** Etiqueta corta del dictamen para la columna Veredicto. */
export const ETIQUETA_VEREDICTO: Record<DictamenIA, string> = {
  ok: "✔ ok",
  dudoso: "⚠ dudoso",
  cambiar: "↔ cambiar",
  sin_apu: "✖ sin APU",
};

/** Texto por el que se filtra y ordena la columna. "" = sin revisar. */
export function textoVeredicto(it: ItemCuadro): string {
  return it.revision ? it.revision.dictamen : "";
}
```

Agrega `"veredicto"` a `ClaveColumna`, a `FiltrosColumna` (como `string`), a `FILTROS_VACIOS` (como `""`) y a `CLAVES_TEXTO`. En el `switch` que resuelve el valor de una clave, agrega:

```ts
    case "veredicto": return textoVeredicto(it);
```

y en `filtrar`, el filtro de esa clave:

```ts
    if (f.veredicto && textoVeredicto(it) !== f.veredicto) return false;
```

Extiende `opcionesDe` para que acepte `"veredicto"` además de `"unidad"` y `"status"`, usando `textoVeredicto(it)` como valor.

- [ ] **Step 4: Columna en la tabla**

En `web/src/components/corrida/TablaItems.tsx`:

1. Agrega la cabecera `Veredicto` entre las columnas de APU y las monetarias, con su filtro (usa el mismo componente `CabeceraFiltros` y el mismo patrón que la columna `status`).
2. En cada fila, la celda:

```tsx
<td className="px-2 py-1 whitespace-nowrap">
  {it.revision ? (
    <span
      title={it.revision.justificacion || undefined}
      className={
        it.revision.dictamen === "ok" ? "text-green-700"
        : it.revision.dictamen === "cambiar" ? "text-blue-700 font-medium"
        : it.revision.dictamen === "sin_apu" ? "text-red-700 font-medium"
        : "text-amber-700"
      }
    >
      {ETIQUETA_VEREDICTO[it.revision.dictamen]}
    </span>
  ) : (
    <span className="text-muted-foreground">—</span>
  )}
  {it.revision?.dictamen === "cambiar" && it.revision.apu_sugerido && puedeEditar && !readOnly && (
    <button
      type="button"
      className="ml-2 underline text-xs"
      title={`Cambiar a ${it.revision.apu_sugerido}`}
      onClick={() => aplicarUna(it.seq, it.revision!.apu_sugerido!, it.revision!.turno_sugerido)}
    >
      Aplicar
    </button>
  )}
</td>
```

3. Define `aplicarUna` en el componente, junto a los otros manejadores:

```tsx
  async function aplicarUna(seq: number, apu: string, turno: string | null) {
    try {
      const c = await aplicarSugerencias(corridaId, [
        { seq, apu_codigo: apu, shift: turno },
      ]);
      onConfirmado(c);
      toast.success(`Línea ${seq + 1}: APU cambiado a ${apu}`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo aplicar la sugerencia.");
    }
  }
```

Importa `aplicarSugerencias` de `@/api/corridas` y `ETIQUETA_VEREDICTO` de `@/lib/corridaTabla`.

- [ ] **Step 5: Corre build y tests**

Run: `cd web && npm run build && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/corridaTabla.ts web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): columna Veredicto en la corrida, con aplicar por fila"
```

---

### Task 15: Botón "Revisar con IA" y aplicar en lote

**Files:**
- Modify: `web/src/pages/Corrida.tsx`
- Test: `web/src/pages/Corrida.test.tsx`

- [ ] **Step 1: Estado y acción**

En `web/src/pages/Corrida.tsx`, agrega el import `revisarCorridaStream, aplicarSugerencias` de `@/api/corridas` y, dentro del componente:

```tsx
  const [revisando, setRevisando] = useState<{ hechas: number; total: number } | null>(null);

  async function revisar() {
    if (!data) return;
    setRevisando({ hechas: 0, total: data.items.length });
    try {
      const resumen = await revisarCorridaStream(corridaId, () =>
        setRevisando((r) => (r ? { ...r, hechas: r.hechas + 1 } : r)),
      );
      setCorrida(await getCorrida(corridaId));
      toast.success(
        `Revisión lista: ${resumen.cambiar ?? 0} por cambiar, ` +
        `${resumen.dudoso ?? 0} dudosas, ${resumen.sin_apu ?? 0} sin APU.`,
      );
    } catch (e) {
      // Los veredictos ya guardados se conservan: se relee igual.
      setCorrida(await getCorrida(corridaId).catch(() => corrida!));
      toast.error(e instanceof Error ? e.message : "No se pudo revisar la corrida.");
    } finally {
      setRevisando(null);
    }
  }

  const sugerencias = (data?.items ?? []).filter(
    (f) => f.revision?.dictamen === "cambiar" && f.revision.apu_sugerido,
  );

  async function aplicarTodas() {
    try {
      const c = await aplicarSugerencias(
        corridaId,
        sugerencias.map((f) => ({
          seq: f.seq,
          apu_codigo: f.revision!.apu_sugerido!,
          shift: f.revision!.turno_sugerido,
        })),
      );
      setCorrida(c);
      toast.success(`${sugerencias.length} sugerencia(s) aplicada(s).`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudieron aplicar.");
    }
  }
```

- [ ] **Step 2: Botones en la barra**

En la barra de acciones (dentro del `{!live && (...)}`), antes de "Descargar cuadro":

```tsx
            {data.modo !== "congelada" && puede(perfil?.rol, "editor") && (
              <Button size="sm" variant="outline"
                disabled={!!revisando || data.ia_disponible === false || data.estado === "armando"}
                title={data.ia_disponible === false
                  ? "El servidor no tiene ANTHROPIC_API_KEY: la revisión con IA está apagada."
                  : `Auditar las ${data.items.length} líneas con IA. Propone; no aplica nada.`}
                onClick={revisar}>
                {revisando
                  ? `Revisando ${revisando.hechas}/${revisando.total}…`
                  : `Revisar con IA (${data.items.length})`}
              </Button>
            )}
            {sugerencias.length > 0 && data.modo !== "congelada" && puede(perfil?.rol, "editor") && (
              <Button size="sm" onClick={aplicarTodas}>
                Aplicar {sugerencias.length} sugerencia{sugerencias.length === 1 ? "" : "s"}
              </Button>
            )}
```

- [ ] **Step 3: Escribe la prueba**

En `web/src/pages/Corrida.test.tsx`:

```tsx
test("apaga el botón de revisar cuando el servidor no tiene IA", async () => {
  const { getCorrida } = await import("@/api/corridas");
  vi.mocked(getCorrida).mockResolvedValueOnce({
    ...CORRIDA, ia_disponible: false,
  } as never);

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  expect(screen.getByRole("button", { name: /revisar con ia/i })).toBeDisabled();
});

test("ofrece aplicar en lote cuando hay sugerencias de cambio", async () => {
  const { getCorrida } = await import("@/api/corridas");
  const cambiar = (seq: number) => ({
    seq, dictamen: "cambiar", apu_sugerido: "222", turno_sugerido: "DIURNO",
    confianza: 0.9, justificacion: "mejor encaje", nivel: "profundo",
  });
  vi.mocked(getCorrida).mockResolvedValueOnce({
    ...CORRIDA, ia_disponible: true,
    items: [
      fila({ seq: 0, descripcion: "Excavación", revision: cambiar(0) }),
      fila({ seq: 1, descripcion: "Concreto", revision: cambiar(1) }),
    ],
  } as never);

  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Excavación");

  expect(
    screen.getByRole("button", { name: /aplicar 2 sugerencias/i }),
  ).toBeInTheDocument();
});
```

- [ ] **Step 4: Corre build y tests**

Run: `cd web && npm run build && npm test`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add web/src/pages/Corrida.tsx web/src/pages/Corrida.test.tsx
git commit -m "feat(web): boton Revisar con IA y aplicar sugerencias en lote"
```

---

### Task 16: Componer a pedido desde una fila sin APU

**Files:**
- Create: `web/src/components/corrida/DialogoComposicion.tsx`, `web/src/components/corrida/DialogoComposicion.test.tsx`
- Modify: `web/src/components/corrida/TablaItems.tsx`

Contexto: el diálogo **no crea nada**. Muestra la propuesta y, si el usuario sigue, abre `DialogoAgregarApu` en modo `"crear"` con la propuesta como `inicial`. El alta de siempre, con sus validaciones de duplicados, es la que crea el APU.

- [ ] **Step 1: Escribe la prueba que falla**

Crea `web/src/components/corrida/DialogoComposicion.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { render, screen, waitFor } from "@testing-library/react";
import { DialogoComposicion } from "./DialogoComposicion";

vi.mock("@/api/corridas", () => ({
  componerItem: vi.fn().mockResolvedValue({
    seq: 3, nombre: "BARRERA ANTIRRUIDO", unidad: "M2", shift: "DIURNO",
    justificacion: "cuadrilla + panel", confianza: 0.7,
    componentes: [
      { insumo_codigo: "4279", insumo_nombre: "CUADRILLA", unidad: "HR", rendimiento: 2 },
    ],
  }),
}));

describe("DialogoComposicion", () => {
  it("muestra la propuesta y avisa que no se creó nada todavía", async () => {
    render(
      <DialogoComposicion open corridaId={1} seq={3}
        onOpenChange={() => {}} onCreado={() => {}} />,
    );
    await waitFor(() => expect(screen.getByText("CUADRILLA")).toBeInTheDocument());
    expect(screen.getByText(/propuesta/i)).toBeInTheDocument();
    expect(screen.getByRole("button", { name: /crear apu con esto/i })).toBeInTheDocument();
  });
});
```

- [ ] **Step 2: Corre la prueba y verifica que falla**

Run: `cd web && npm test -- DialogoComposicion`
Expected: FAIL — el módulo no existe.

- [ ] **Step 3: Implementa el diálogo**

Crea `web/src/components/corrida/DialogoComposicion.tsx`:

```tsx
import { useEffect, useState } from "react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { DialogoAgregarApu } from "@/components/autoria/DialogoAgregarApu";
import { componerItem } from "@/api/corridas";
import type { ApuDetalle, ComposicionPropuesta } from "@/lib/tipos";

/**
 * Muestra una composición PROPUESTA por la IA para una línea sin APU.
 * No crea nada: si el usuario sigue, se abre el alta de APU de siempre precargada,
 * y es esa la que valida duplicados y escribe en la biblioteca.
 */
export function DialogoComposicion({
  open, corridaId, seq, onOpenChange, onCreado,
}: {
  open: boolean;
  corridaId: number;
  seq: number;
  onOpenChange: (v: boolean) => void;
  onCreado: (codigo: string, turno: string) => void;
}) {
  const [prop, setProp] = useState<ComposicionPropuesta | null>(null);
  const [error, setError] = useState<string | null>(null);
  const [creando, setCreando] = useState(false);

  useEffect(() => {
    if (!open) return;
    let vivo = true;
    componerItem(corridaId, seq)
      .then((p) => { if (vivo) setProp(p); })
      .catch((e: unknown) => {
        if (vivo) setError(e instanceof Error ? e.message : "No se pudo componer.");
      });
    return () => { vivo = false; };
  }, [open, corridaId, seq]);

  if (!open) return null;

  if (creando && prop) {
    const inicial: ApuDetalle = {
      codigo: "", turno: prop.shift, nombre: prop.nombre, unidad: prop.unidad,
      grupo: "", costo_unitario: 0,
      composicion: prop.componentes.map((c) => ({
        insumo_codigo: c.insumo_codigo, insumo_nombre: c.insumo_nombre,
        unidad: c.unidad, rendimiento: c.rendimiento,
        precio_unitario: 0, fuente_precio: "", costo: 0, calidad_cruce: "",
        tipo: "insumo",
      })),
    };
    return (
      <DialogoAgregarApu
        open modo="crear" inicial={inicial}
        onOpenChange={(v) => { if (!v) { setCreando(false); onOpenChange(false); } }}
        onCreado={(codigo, turno) => { onCreado(codigo, turno); onOpenChange(false); }}
      />
    );
  }

  return (
    <div className="fixed inset-0 z-50 flex items-center justify-center bg-black/40"
         role="dialog" aria-modal="true">
      <div className="bg-background rounded-lg border p-4 w-[min(680px,92vw)] max-h-[80vh] overflow-auto">
        <h3 className="text-sm font-semibold">Composición propuesta por la IA</h3>
        <p className="text-xs text-muted-foreground mt-1">
          Es una <strong>propuesta</strong>: todavía no se creó ningún APU. Revisa los
          rendimientos antes de seguir — la IA no ve precios y puede equivocarse.
        </p>
        {error && <p className="text-xs text-destructive mt-2">{error}</p>}
        {!prop && !error && (
          <p className="text-xs text-muted-foreground mt-3">Componiendo…</p>
        )}
        {prop && (
          <>
            <p className="text-xs mt-3">{prop.justificacion}</p>
            <table className="w-full text-xs mt-3">
              <thead>
                <tr className="text-left text-muted-foreground">
                  <th className="py-1">Código</th><th>Insumo</th>
                  <th>Unidad</th><th className="text-right">Rendimiento</th>
                </tr>
              </thead>
              <tbody>
                {prop.componentes.map((c) => (
                  <tr key={c.insumo_codigo} className="border-t">
                    <td className="py-1 font-mono">{c.insumo_codigo}</td>
                    <td>{c.insumo_nombre}</td>
                    <td>{c.unidad}</td>
                    <td className="text-right font-mono tabular-nums">{c.rendimiento}</td>
                  </tr>
                ))}
              </tbody>
            </table>
          </>
        )}
        <div className="flex justify-end gap-2 mt-4">
          <Button size="sm" variant="outline" onClick={() => onOpenChange(false)}>
            Descartar
          </Button>
          <Button size="sm" disabled={!prop}
            onClick={() => {
              if (!prop) return;
              setCreando(true);
              toast.info("Revisa el APU antes de guardarlo.");
            }}>
            Crear APU con esto
          </Button>
        </div>
      </div>
    </div>
  );
}
```

Antes de escribirlo, abre `web/src/components/autoria/DialogoAgregarApu.tsx` y confirma los nombres exactos de sus props (`open`, `onOpenChange`, `onCreado`, `modo`, `inicial`) y la forma de `LineaComposicion`; ajusta si difieren.

- [ ] **Step 4: Botón en la fila sin APU**

En `web/src/components/corrida/TablaItems.tsx`, en la celda de Veredicto, después del botón "Aplicar":

```tsx
  {it.revision?.dictamen === "sin_apu" && puedeEditar && !readOnly && (
    <button type="button" className="ml-2 underline text-xs"
      onClick={() => setComponiendo(it.seq)}
      title="Pedirle a la IA una composición para esta actividad">
      Componer
    </button>
  )}
```

Agrega el estado `const [componiendo, setComponiendo] = useState<number | null>(null);` y, al final del JSX del componente:

```tsx
  {componiendo !== null && (
    <DialogoComposicion
      open corridaId={corridaId} seq={componiendo}
      onOpenChange={(v) => { if (!v) setComponiendo(null); }}
      onCreado={async (codigo, turno) => {
        const c = await aplicarSugerencias(corridaId, [
          { seq: componiendo, apu_codigo: codigo, shift: turno },
        ]);
        onConfirmado(c);
        setComponiendo(null);
      }}
    />
  )}
```

- [ ] **Step 5: Corre build y tests**

Run: `cd web && npm run build && npm test`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add web/src/components/corrida/DialogoComposicion.tsx web/src/components/corrida/DialogoComposicion.test.tsx web/src/components/corrida/TablaItems.tsx
git commit -m "feat(web): componer un APU con IA a pedido desde una fila sin APU"
```

---

## Cierre

### Task 17: Documentación y verificación final

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Actualiza `CLAUDE.md`**

En la tabla de `apu_tool/dominio/`, agrega la fila (después de `ai_assist.py`):

```
| `revision.py`            | revisión con IA de una corrida ya armada (propone, no aplica) |
```

En la sección "Arquitectura (flujo)", cambia el diagrama:

```
lista licitación ──► matching determinístico ──► confirma usuario
                                       └─► motor de precios ──► cuadro resumen (Excel)
corrida armada ──► revisión con IA (sin dinero) ──► propone ──► confirma usuario
```

En "No hacer", agrega:

```
- No metas la IA en el armado. Arma el programa; la IA audita después
  (`dominio/revision.py`) y siempre propone: aplicar es del usuario.
- No emitas un cuadro con filas sin APU: el candado de `congelar`/`generar_cuadro`
  está para eso, no lo esquives.
```

- [ ] **Step 2: Verificación completa**

Run: `python -m pytest tests/ -q`
Expected: PASS, sin fallos ni errores.

Run: `cd web && npm run build && npm test && npm run lint`
Expected: PASS.

No declares la feature terminada sin haber visto la salida verde de los dos comandos.

- [ ] **Step 3: Prueba en el navegador**

Levanta la app en local (la receta con `SUPABASE_URL` + `APU_ADMIN_EMAILS` está en la memoria del proyecto; sin esas variables todo `/api` rebota con 401) y comprueba a mano:

1. Crear una corrida: **no** aparece la casilla "Usar IA" y el armado es rápido.
2. Con una fila sin APU: el contador rojo aparece, filtra al pulsarlo, y Congelar y Descargar están deshabilitados.
3. Con `ANTHROPIC_API_KEY` puesta: "Revisar con IA" avanza, la columna Veredicto se llena, "Aplicar" cambia el APU de una fila y el veredicto de esa fila desaparece.
4. Sin `ANTHROPIC_API_KEY`: el botón está apagado y el tooltip lo explica.

En cambios de UI el navegador va **antes** del push: en este repo ya hubo un modal que se cerraba solo en el navegador con 145 tests verdes.

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: la IA revisa, no arma; y el candado de filas sin APU"
```

- [ ] **Step 5: No hagas push**

`master` autodespliega y el push necesita aprobación explícita del usuario para cada cambio. Al terminar, informa el estado y espera. Verifica también que `feat/distancias-transporte-proyecto` sigue exactamente donde estaba:

```bash
git rev-parse feat/distancias-transporte-proyecto origin/feat/distancias-transporte-proyecto
```

Los dos hashes deben coincidir y ser `7be02a9…`.
