> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-18-agregar-lineas-corrida.md`

# Agregar líneas a una corrida activa — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Sumar actividades que faltaron a una corrida ya armada —una a mano o un Excel con solo las faltantes— y poder borrar líneas cuando se metió lo que no era.

**Architecture:** Las líneas nuevas pasan por el mismo camino que el armado inicial: se extrae el trabajo por ítem de `construir_corrida_stream` a un `_armar_fila` y lo reusan las dos vías. `seq` sigue desde el máximo existente y **nunca se renumera** (es la clave del `snapshot_json` y de la URL del ítem). Cuatro endpoints nuevos en el router que ya existe, un método nuevo de persistencia (`borrar_items`) en los dos backends, y un diálogo en la página de la corrida.

**Tech Stack:** Python 3 · FastAPI · SQLite + Postgres (psycopg3) · openpyxl · pytest · React + TypeScript · vitest + @testing-library/react

## Global Constraints

- **NO COMMITEAR.** El usuario revisa el árbol de trabajo antes de cualquier commit. Ningún paso de este plan corre `git commit`, `git add`, `git push` ni `git checkout`. Cada tarea termina corriendo sus pruebas y dejando los archivos modificados.
- **Rama:** `feat/agregar-lineas-corrida`, creada desde `master`. **No usar nada de `feat/login-google`**: no se toca `apu_tool/servicio/auth.py`, `apu_tool/datos/perfiles_db.py`, `apu_tool/datos/pg/perfiles_pg.py`, `RepositorioPerfiles`, `web/src/pages/Login.tsx` ni sus tests.
- **Invariante #1:** ningún dato monetario llega a la IA. Este plan no construye payloads para la IA; `ApuAdvisor` se usa tal cual, por dentro de `Assembler`.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Nada en $0 en silencio:** una línea nueva sin tarifa en una lista que no es Principal queda en $0 **con alerta**, nunca cae al precio histórico.
- **Doble backend:** todo método nuevo de persistencia va en `RepositorioCorridas` (Protocol), `datos/corridas_db.py` (SQLite) y `datos/pg/corridas_pg.py` (Postgres). `tests/test_repositorios_contrato.py` falla si falta uno.
- **Tope:** 100 líneas por operación (`corridas.MAX_LINEAS_AGREGADAS`).
- Suite completa antes de dar algo por terminado: `python -m pytest tests/ -q` y, para el frontend, `cd web && npm run test -- --run` + `npm run build`.

## Mapa de archivos

| Archivo | Responsabilidad | Tarea |
|---|---|---|
| `apu_tool/servicio/corridas.py` | `_armar_fila`, `agregar_items`, `preview_agregar`, `borrar_items` | 1, 2, 3 |
| `apu_tool/datos/repositorio.py` | `RepositorioCorridas.borrar_items` (contrato) | 3 |
| `apu_tool/datos/corridas_db.py` | `borrar_items` SQLite | 3 |
| `apu_tool/datos/pg/corridas_pg.py` | `borrar_items` Postgres | 3 |
| `apu_tool/servicio/esquemas.py` | `LineaNuevaIn`, `AgregarLineasIn`, `BorrarLineasIn` | 4 |
| `apu_tool/servicio/rutas.py` | `_items_del_upload`, `_turno_valido`, 4 endpoints | 4 |
| `web/src/lib/tipos.ts` | `LineaPreview`, `PreviewLineas` | 5 |
| `web/src/api/corridas.ts` | `previewLineas`, `importarLineas`, `agregarLineas`, `borrarLineas` | 5, 6 |
| `web/src/components/corrida/DialogoAgregarLineas.tsx` | diálogo con las dos vías | 5 |
| `web/src/pages/Corrida.tsx` | botón `Agregar líneas` | 5 |
| `web/src/components/corrida/TablaItems.tsx` | `Borrar` en la barra de líneas marcadas | 6 |
| `tests/test_corridas_agregar_lineas.py` | servicio (nuevo archivo) | 1, 2, 3 |
| `tests/test_api_corridas.py` | los 4 endpoints | 4 |
| `web/src/components/corrida/DialogoAgregarLineas.test.tsx` | diálogo (nuevo archivo) | 5 |
| `web/src/components/corrida/TablaItems.test.tsx` | borrado en lote | 6 |

---

### Task 1: `_armar_fila` + `agregar_items`

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (bloque del `for` en `construir_corrida_stream`, líneas 88-111)
- Test: `tests/test_corridas_agregar_lineas.py` (nuevo)

**Interfaces:**
- Consumes: `Assembler`, `ApuAdvisor`, `_estructura`, `_vista_item`, `vista_corrida`, `CorridaCongelada` (ya existen en `apu_tool/servicio/corridas.py`).
- Produces:
  - `_armar_fila(assembler: Assembler, item: LicitacionItem, seq: int) -> tuple[AssembledApu, CorridaItemRow]`
  - `agregar_items(alm: Almacen, corrida_id: int, items: list[LicitacionItem]) -> Optional[dict]` — devuelve `vista_corrida`; `None` si la corrida no existe; `CorridaCongelada` si está congelada; `ValueError` si `items` está vacío o pasa `MAX_LINEAS_AGREGADAS`.
  - `MAX_LINEAS_AGREGADAS: int = 100`

- [ ] **Step 1: Escribir las pruebas que fallan**

Crear `tests/test_corridas_agregar_lineas.py`:

```python
# tests/test_corridas_agregar_lineas.py
"""Agregar líneas a una corrida ya armada (y borrarlas)."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas


def _almacen_seed(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "100", "Concreto 3000 PSI", "M3", 1.05, 350000.0)])
    return alm


def _lic(num, desc, cantidad=10.0, precio=400000.0, shift="DIURNO", unidad="M3"):
    return LicitacionItem(item=num, descripcion=desc, unidad=unidad, cantidad=cantidad,
                          precio_contractual=precio, shift=shift)


def _corrida_de_una(alm, **kw):
    return corridas.construir_corrida(alm, "lic.xlsx", [_lic("1", "Concreto clase D")],
                                      "DIURNO", use_ai=False, **kw)


def test_agregar_items_continua_el_seq_y_pasa_por_el_matcher(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    vista = corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D", cantidad=2.0)])
    assert [f["seq"] for f in vista["items"]] == [0, 1]
    nueva = vista["items"][1]
    assert nueva["apu_codigo"] == "A1"                       # la armó el matcher
    assert nueva["costo_unitario"] == 1.05 * 350000.0        # y la costeó
    assert vista["totales"]["n_items"] == 2


def test_agregar_items_numera_el_item_vacio(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    vista = corridas.agregar_items(alm, cid, [_lic("", "Concreto clase D")])
    assert vista["items"][1]["item"] == "2"                  # seq 1 -> ítem "2"


def test_agregar_items_bloqueado_si_congelada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D")])
    assert len(alm.corridas.get_items(cid)) == 1             # no escribió nada


def test_agregar_items_reabre_la_corrida_finalizada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    corridas.generar_cuadro(alm, cid)                        # finalizada + congelada
    corridas.activar(alm, cid)
    corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D")])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_agregar_items_corrida_inexistente_es_none(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.agregar_items(alm, 999, [_lic("1", "Concreto clase D")]) is None


def test_agregar_items_rechaza_vacio_y_pasado_de_tope(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    with pytest.raises(ValueError):
        corridas.agregar_items(alm, cid, [])
    muchas = [_lic(str(k), "Concreto clase D")
              for k in range(corridas.MAX_LINEAS_AGREGADAS + 1)]
    with pytest.raises(ValueError):
        corridas.agregar_items(alm, cid, muchas)
    assert len(alm.corridas.get_items(cid)) == 1


def test_agregar_items_costea_con_la_lista_de_la_corrida(tmp_path):
    # La línea nueva NO puede costearse con otra tarifa que el resto de la corrida.
    # En una lista de NP sin tarifa para el insumo, queda en $0 con alerta: jamás
    # cae al precio histórico (sería cobrar el no previsto con la tarifa contractual).
    alm = _almacen_seed(tmp_path)
    lid = alm.precios.crear_lista("NP Calle 13")
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_lic("1", "Concreto clase D")],
                                     "DIURNO", use_ai=False, lista_precios_id=lid)
    vista = corridas.agregar_items(alm, cid, [_lic("2", "Concreto clase D")])
    assert vista["lista_precios_id"] == lid
    assert vista["items"][1]["costo_unitario"] == 0.0
    assert vista["items"][1]["alertas_costeo"]                # no queda en $0 callado
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_corridas_agregar_lineas.py -q`
Expected: FAIL con `AttributeError: module 'apu_tool.servicio.corridas' has no attribute 'agregar_items'` (y `MAX_LINEAS_AGREGADAS`).

- [ ] **Step 3: Extraer `_armar_fila`**

En `apu_tool/servicio/corridas.py`, agregar la función justo **antes** de `construir_corrida_stream`:

```python
def _armar_fila(assembler: Assembler, item: LicitacionItem,
                seq: int) -> tuple[AssembledApu, CorridaItemRow]:
    """Arma UNA línea y devuelve (ensamble costeado, fila lista para persistir).

    Un solo `match()` por ítem: sus candidatos son los que se le muestran al usuario y
    se reusan en `assemble_item()` para elegir el APU final (mismo resultado
    determinístico, sin recalcular el matcher).

    Es el camino ÚNICO del armado: lo usan el armado inicial (`construir_corrida_stream`)
    y las líneas que se agregan después (`agregar_items`), para que no puedan divergir.
    """
    result = assembler.matcher.match(item)
    candidatos = [{"apu_codigo": c.apu_codigo, "apu_nombre": c.apu_nombre,
                   "score": c.score, "motivo": c.motivo}
                  for c in result.candidatos]
    ens = assembler.assemble_item(item, result)
    fila = CorridaItemRow(
        seq=seq, item=item, status=ens.status.value, apu_codigo=ens.apu_codigo,
        apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
        origen=ens.origen, confianza=ens.confianza, explicacion=ens.explicacion,
        componentes=_estructura(ens.componentes), candidatos=candidatos)
    return ens, fila
```

- [ ] **Step 4: Usar `_armar_fila` en el armado inicial**

En `construir_corrida_stream`, reemplazar el cuerpo del `for` (hoy líneas 88-111) por:

```python
    for seq, item in enumerate(items):
        i = seq + 1
        print(f"  [{i}/{total}] {item.descripcion[:60]}", flush=True)
        ens, fila = _armar_fila(assembler, item, seq)
        try:
            alm.corridas.agregar_item(corrida_id, fila)
        except CorridaEliminada:
            yield ("error", {"detail": "Armado cancelado: la corrida fue eliminada."})
            return
        yield ("progress", {"i": i, "total": total,
                            "descripcion": item.descripcion,
                            "fila": _vista_item(ens, seq, ens.status.value)})
```

- [ ] **Step 5: Verificar que el armado inicial no cambió**

Run: `python -m pytest tests/test_servicio_corridas.py tests/test_api_corridas.py -q`
Expected: PASS (todos). Si algo falla acá, la extracción cambió comportamiento: revisar antes de seguir.

- [ ] **Step 6: Escribir `agregar_items`**

Agregar `from dataclasses import replace` a los imports de `apu_tool/servicio/corridas.py`, y la constante + función después de `construir_corrida` (antes de `_costear_row`):

```python
# Tope por operación al agregar líneas. Es una sola petición HTTP sin progreso, así
# que la espera tiene que ser humana; con IA activada cada línea cuesta segundos.
MAX_LINEAS_AGREGADAS = 100


def agregar_items(alm: Almacen, corrida_id: int,
                  items: list[LicitacionItem]) -> Optional[dict]:
    """Suma líneas a una corrida ya armada. Devuelve la vista; None si no existe.

    Las líneas nuevas pasan por el MISMO camino que el armado inicial (`_armar_fila`),
    con la `use_ai` y la lista de precios que la corrida guardó al crearse: una
    actividad que faltó no puede costearse con otra tarifa que el resto de la corrida.

    Lanza CorridaCongelada si está congelada (una foto inmutable no crece) y ValueError
    si no llegó ninguna línea o si pasan de MAX_LINEAS_AGREGADAS.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    if not items:
        raise ValueError("No hay líneas para agregar.")
    if len(items) > MAX_LINEAS_AGREGADAS:
        raise ValueError(f"Máximo {MAX_LINEAS_AGREGADAS} líneas por vez; "
                         f"llegaron {len(items)}. Partí el archivo.")
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=meta.use_ai),
                          lista_id=meta.lista_precios_id)
    # El seq sigue desde el máximo y los huecos que dejó un borrado NO se reusan: el
    # seq es la clave del snapshot y de la URL del ítem.
    # ponytail: se lee fuera de transacción, y corrida_item no tiene UNIQUE
    # (corrida_id, seq) sino un índice; dos usuarios agregando en el mismo instante
    # podrían pedir el mismo seq. Si llega a pasar, el arreglo es el índice UNIQUE.
    siguiente = max((r.seq for r in alm.corridas.get_items(corrida_id)), default=-1) + 1
    for k, item in enumerate(items):
        seq = siguiente + k
        if not (item.item or "").strip():
            # Línea a mano sin nº de ítem: se numera sola (el lector de Excel ya
            # numera por fila, así que esto solo aplica a la vía manual).
            item = replace(item, item=str(seq + 1))
        _ens, fila = _armar_fila(assembler, item, seq)
        alm.corridas.agregar_item(corrida_id, fila)
    if meta.estado == "finalizada":
        # El cuadro emitido ya no describe la corrida: vuelve a revisión.
        alm.corridas.set_estado(corrida_id, "en_revision")
    return vista_corrida(alm, corrida_id)
```

- [ ] **Step 7: Correr las pruebas nuevas**

Run: `python -m pytest tests/test_corridas_agregar_lineas.py -q`
Expected: PASS (7 pruebas).

- [ ] **Step 8: Suite completa de Python**

Run: `python -m pytest tests/ -q`
Expected: PASS. **No commitear** — dejar los cambios en el árbol.

---

### Task 2: `preview_agregar`

**Files:**
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_corridas_agregar_lineas.py`

**Interfaces:**
- Consumes: `agregar_items`, `MAX_LINEAS_AGREGADAS` (Task 1); `apu_tool.nucleo.texto.normalizar`.
- Produces: `preview_agregar(alm: Almacen, corrida_id: int, items: list[LicitacionItem]) -> Optional[dict]` con la forma
  `{"total": int, "nuevas": [linea], "duplicadas": [linea + {"seq_existente": int}], "modo": str, "tope": int}`
  donde `linea` es `{"item", "descripcion", "unidad", "cantidad", "precio_contractual", "shift"}`.

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar al final de `tests/test_corridas_agregar_lineas.py`:

```python
def test_preview_marca_duplicadas_por_descripcion_y_no_escribe(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)                                # seq 0 = "Concreto clase D"
    prev = corridas.preview_agregar(alm, cid, [
        _lic("9", "  concreto   CLASE d "),                   # misma actividad, otro formato
        _lic("10", "Sardinel A-10"),
    ])
    assert prev["total"] == 2
    assert [f["descripcion"] for f in prev["nuevas"]] == ["Sardinel A-10"]
    assert prev["duplicadas"][0]["seq_existente"] == 0
    assert prev["modo"] == "activa" and prev["tope"] == corridas.MAX_LINEAS_AGREGADAS
    assert len(alm.corridas.get_items(cid)) == 1              # el preview no escribe


def test_agregar_items_agrega_la_duplicada_igual(tmp_path):
    # El preview AVISA; aplicar hace lo que dice el archivo. Saltear en silencio
    # esconde el duplicado y nadie se enteraría.
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_una(alm)
    vista = corridas.agregar_items(alm, cid, [_lic("9", "Concreto clase D")])
    assert vista["totales"]["n_items"] == 2


def test_preview_corrida_inexistente_es_none(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.preview_agregar(alm, 999, [_lic("1", "x")]) is None
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_corridas_agregar_lineas.py -q -k preview`
Expected: FAIL con `AttributeError: ... has no attribute 'preview_agregar'`.

- [ ] **Step 3: Implementar**

En `apu_tool/servicio/corridas.py`, agregar el import `from apu_tool.nucleo.texto import normalizar` y la función justo antes de `agregar_items`:

```python
def preview_agregar(alm: Almacen, corrida_id: int,
                    items: list[LicitacionItem]) -> Optional[dict]:
    """Qué pasaría al agregar estas líneas, SIN escribir nada ni tocar el matcher.

    `duplicadas` son las que ya están en la corrida por descripción normalizada, con el
    seq de la línea existente. Es un AVISO: `agregar_items` las agrega igual, porque
    saltearlas en silencio esconde el duplicado. None si la corrida no existe.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    existentes: dict[str, int] = {}
    for r in alm.corridas.get_items(corrida_id):
        existentes.setdefault(normalizar(r.item.descripcion), r.seq)   # gana el primer seq
    nuevas: list[dict] = []
    duplicadas: list[dict] = []
    for it in items:
        fila = {"item": it.item, "descripcion": it.descripcion, "unidad": it.unidad,
                "cantidad": it.cantidad, "precio_contractual": it.precio_contractual,
                "shift": it.shift}
        seq_existente = existentes.get(normalizar(it.descripcion))
        if seq_existente is None:
            nuevas.append(fila)
        else:
            duplicadas.append({**fila, "seq_existente": seq_existente})
    return {"total": len(items), "nuevas": nuevas, "duplicadas": duplicadas,
            "modo": meta.modo, "tope": MAX_LINEAS_AGREGADAS}
```

- [ ] **Step 4: Correr las pruebas**

Run: `python -m pytest tests/test_corridas_agregar_lineas.py -q`
Expected: PASS (10 pruebas).

- [ ] **Step 5: Suite completa de Python**

Run: `python -m pytest tests/ -q`
Expected: PASS. **No commitear.**

---

### Task 3: `borrar_items` (persistencia + servicio)

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (`RepositorioCorridas`, después de `agregar_item`)
- Modify: `apu_tool/datos/corridas_db.py` (sección `# ---- escritura ----`)
- Modify: `apu_tool/datos/pg/corridas_pg.py` (junto a `agregar_item`)
- Modify: `apu_tool/servicio/corridas.py`
- Test: `tests/test_corridas_agregar_lineas.py`

**Interfaces:**
- Consumes: `agregar_items` (Task 1); `registrar_auditoria` y `alm.transaccion("corridas")` (ya existen, ver `eliminar_corrida` en `apu_tool/servicio/corridas.py:436`).
- Produces:
  - `RepositorioCorridas.borrar_items(corrida_id: int, seqs: Iterable[int], conn=None) -> int`
  - `corridas.borrar_items(alm: Almacen, corrida_id: int, seqs: Iterable[int], actor=None) -> Optional[dict]`

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar al final de `tests/test_corridas_agregar_lineas.py`:

```python
def _corrida_de_dos(alm):
    """Dos líneas con APUs distintos: A1 (1.05) en seq 0, A2 (2.0) en seq 1."""
    alm.apus.insert_apus([Apu("A2", "Concreto clase E", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([
        ApuComponent("A2", "DIURNO", "100", "Concreto 3000 PSI", "M3", 2.0, 350000.0)])
    return corridas.construir_corrida(
        alm, "lic.xlsx", [_lic("1", "Concreto clase D"), _lic("2", "Concreto clase E")],
        "DIURNO", use_ai=False)


def test_borrar_items_deja_hueco_sin_renumerar(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    vista = corridas.borrar_items(alm, cid, [0])
    assert [f["seq"] for f in vista["items"]] == [1]          # el que queda NO pasó a 0
    assert vista["totales"]["n_items"] == 1


def test_borrar_y_despues_agregar_no_reusa_el_hueco(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.borrar_items(alm, cid, [0])
    vista = corridas.agregar_items(alm, cid, [_lic("3", "Concreto clase D")])
    assert [f["seq"] for f in vista["items"]] == [1, 2]       # 0 quedó libre y libre se queda


def test_borrar_no_le_cambia_el_snapshot_al_sobreviviente(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.congelar(alm, cid)                              # snapshots: seq 0 y seq 1
    corridas.activar(alm, cid)
    corridas.borrar_items(alm, cid, [0])
    alm.corridas.set_modo(cid, "congelada")                  # sin recongelar: snapshots viejos
    vista = corridas.vista_corrida(alm, cid)
    assert [f["seq"] for f in vista["items"]] == [1]
    assert vista["items"][0]["costo_unitario"] == 2.0 * 350000.0   # el snapshot de SU seq


def test_borrar_items_bloqueado_si_congelada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.borrar_items(alm, cid, [0])
    assert len(alm.corridas.get_items(cid)) == 2


def test_borrar_items_seq_ajeno_se_saltea(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    vista = corridas.borrar_items(alm, cid, [77])
    assert [f["seq"] for f in vista["items"]] == [0, 1]       # no borró nada, no explotó


def test_borrar_items_corrida_inexistente_es_none(tmp_path):
    alm = _almacen_seed(tmp_path)
    assert corridas.borrar_items(alm, 999, [0]) is None


def test_borrar_items_reabre_la_corrida_finalizada(tmp_path):
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.generar_cuadro(alm, cid)                        # finalizada + congelada
    corridas.activar(alm, cid)
    corridas.borrar_items(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"


def test_borrar_items_queda_auditado(tmp_path):
    from apu_tool.nucleo.models import Perfil
    alm = _almacen_seed(tmp_path)
    cid = _corrida_de_dos(alm)
    corridas.borrar_items(alm, cid, [0], actor=Perfil("u-1", "jefe@obra.co", "admin", "activo"))
    eventos, total = alm.auditoria.listar(accion="corrida.borrar_items")
    assert total == 1
    assert eventos[0]["antes"]["lineas"][0]["seq"] == 0
    assert eventos[0]["antes"]["lineas"][0]["descripcion"] == "Concreto clase D"
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_corridas_agregar_lineas.py -q -k borrar`
Expected: FAIL con `AttributeError: ... has no attribute 'borrar_items'`.

- [ ] **Step 3: Agregar el método al contrato**

En `apu_tool/datos/repositorio.py`, dentro de `class RepositorioCorridas`, justo después de `agregar_item`:

```python
    def borrar_items(self, corrida_id: int, seqs: Iterable[int], conn=None) -> int:
        """Borra los ítems indicados y devuelve cuántos borró. Los seq que no existen
        se ignoran. NO renumera lo que queda: el seq es identidad (URL del ítem y clave
        del snapshot), así que renumerar casaría snapshots con la línea equivocada."""
        ...
```

- [ ] **Step 4: Implementar en SQLite**

En `apu_tool/datos/corridas_db.py`, después de `agregar_item`:

```python
    def borrar_items(self, corrida_id: int, seqs, conn=None) -> int:
        lista = [int(s) for s in seqs]
        if not lista:
            return 0
        marcas = ",".join("?" * len(lista))
        sql = f"DELETE FROM corrida_item WHERE corrida_id=? AND seq IN ({marcas})"
        params = (int(corrida_id), *lista)
        if conn is not None:
            return conn.execute(sql, params).rowcount
        with self.connect() as c:
            return c.execute(sql, params).rowcount
```

- [ ] **Step 5: Implementar en Postgres**

En `apu_tool/datos/pg/corridas_pg.py`, después de `agregar_item`:

```python
    def borrar_items(self, corrida_id: int, seqs, conn=None) -> int:
        lista = [int(s) for s in seqs]
        if not lista:
            return 0
        sql = "DELETE FROM corridas.corrida_item WHERE corrida_id=%s AND seq = ANY(%s)"
        params = (int(corrida_id), lista)
        if conn is not None:
            return conn.execute(sql, params).rowcount
        with self.cx.connection() as c:
            return c.execute(sql, params).rowcount
```

- [ ] **Step 6: Verificar el contrato de los dos backends**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_corridas_db.py -q`
Expected: PASS. Si falla por `isinstance`, falta el método en uno de los dos backends.

- [ ] **Step 7: Implementar el servicio**

En `apu_tool/servicio/corridas.py`, después de `agregar_items`:

```python
def borrar_items(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                 actor=None) -> Optional[dict]:
    """Borra líneas de una corrida: la válvula del "me equivoqué al agregar".

    No renumera. Los seq que quedan siguen siendo los mismos (los snapshots y las URLs
    de ítem no cambian de dueño) y un seq borrado no se reusa: `agregar_items` sigue
    desde el máximo. Los seq ajenos a la corrida se saltean. Lanza CorridaCongelada si
    está congelada; devuelve None si la corrida no existe.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    pedidos = {int(s) for s in seqs}
    victimas = [r for r in alm.corridas.get_items(corrida_id) if r.seq in pedidos]
    if victimas:
        with alm.transaccion("corridas") as conn:
            alm.corridas.borrar_items(corrida_id, [r.seq for r in victimas], conn=conn)
            registrar_auditoria(
                alm, conn, actor, "corrida.borrar_items", "corrida", corrida_id,
                antes={"lineas": [{"seq": r.seq, "descripcion": r.item.descripcion}
                                  for r in victimas]},
                despues=None)
        if meta.estado == "finalizada":
            alm.corridas.set_estado(corrida_id, "en_revision")
    return vista_corrida(alm, corrida_id)
```

- [ ] **Step 8: Correr las pruebas nuevas**

Run: `python -m pytest tests/test_corridas_agregar_lineas.py -q`
Expected: PASS (18 pruebas).

- [ ] **Step 9: Suite completa de Python**

Run: `python -m pytest tests/ -q`
Expected: PASS. **No commitear.**

---

### Task 4: Endpoints HTTP

**Files:**
- Modify: `apu_tool/servicio/esquemas.py`
- Modify: `apu_tool/servicio/rutas.py` (`crear_corrida` líneas 140-170, `crear_corrida_stream` líneas 204-235, y los endpoints nuevos después de `confirmar_lote`)
- Test: `tests/test_api_corridas.py`

**Interfaces:**
- Consumes: `svc.agregar_items`, `svc.preview_agregar`, `svc.borrar_items`, `svc.CorridaCongelada`, `svc.MAX_LINEAS_AGREGADAS` (Tasks 1-3).
- Produces:
  - `_items_del_upload(nombre: str, contenido: bytes, turno: str) -> list[LicitacionItem]`
  - `_turno_valido(raw: Optional[str], default: str) -> str`
  - `POST /api/corridas/{cid}/items/preview` (multipart `archivo`) → preview
  - `POST /api/corridas/{cid}/items/importar` (multipart `archivo`) → vista de corrida
  - `POST /api/corridas/{cid}/items` (JSON `{lineas:[...]}`) → vista de corrida
  - `POST /api/corridas/{cid}/items/borrar` (JSON `{seqs:[...]}`) → vista de corrida

**Nota de diseño:** el borrado va por `POST .../items/borrar` y no por `DELETE .../items` porque `apiDelete` en `web/src/api/client.ts:56` no manda cuerpo, y el repo ya usa POST para las acciones en lote (`items/confirmar-lote`).

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregar al final de `tests/test_api_corridas.py`:

```python
def _corrida_api(cli, tmp_path):
    """Crea una corrida de 1 ítem por la API y devuelve su id."""
    obra = cli.post("/api/carpetas", json={"nombre": "Obra"}).json()
    lic = _xlsx_lic(tmp_path)
    with open(lic, "rb") as f:
        r = cli.post("/api/corridas",
                     data={"turno": "DIURNO", "use_ai": "false",
                           "carpeta_id": str(obra["id"])},
                     files={"archivo": ("lic.xlsx", f, _XLSX_MIME)})
    assert r.status_code == 200, r.text
    return r.json()["id"]


_XLSX_MIME = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet"


def _xlsx_faltantes(tmp_path):
    """Excel con las líneas que faltaron: una nueva y una que ya está en la corrida."""
    p = tmp_path / "faltantes.xlsx"
    write_sample_licitacion(p, [
        LicitacionItem(item="9", descripcion="Sardinel A-10", unidad="ML",
                       cantidad=5.0, precio_contractual=40000.0, shift="DIURNO"),
        LicitacionItem(item="10", descripcion="Concreto clase D", unidad="M3",
                       cantidad=1.0, precio_contractual=400000.0, shift="NOCTURNO"),
    ])
    return p


def test_api_agregar_linea_a_mano(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D", "unidad": "M3", "cantidad": 3.0,
         "precio_contractual": 400000.0}]})
    assert r.status_code == 200, r.text
    items = r.json()["items"]
    assert [f["seq"] for f in items] == [0, 1]
    assert items[1]["apu_codigo"] == "A1" and items[1]["cantidad"] == 3.0


def test_api_agregar_linea_sin_descripcion_es_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [{"descripcion": "  "}]})
    assert r.status_code == 400


def test_api_agregar_linea_turno_invalido_es_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D", "shift": "TARDE"}]})
    assert r.status_code == 400
    assert "Turno" in r.json()["detail"]


def test_api_preview_y_importar_lineas(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    xls = _xlsx_faltantes(tmp_path)

    with open(xls, "rb") as f:
        prev = cli.post(f"/api/corridas/{cid}/items/preview",
                        files={"archivo": ("faltantes.xlsx", f, _XLSX_MIME)})
    assert prev.status_code == 200, prev.text
    cuerpo = prev.json()
    assert cuerpo["total"] == 2
    assert [n["descripcion"] for n in cuerpo["nuevas"]] == ["Sardinel A-10"]
    assert cuerpo["duplicadas"][0]["seq_existente"] == 0
    assert len(cli.get(f"/api/corridas/{cid}").json()["items"]) == 1   # el preview no escribió

    with open(xls, "rb") as f:
        r = cli.post(f"/api/corridas/{cid}/items/importar",
                     files={"archivo": ("faltantes.xlsx", f, _XLSX_MIME)})
    assert r.status_code == 200, r.text
    assert [f["seq"] for f in r.json()["items"]] == [0, 1, 2]


def test_api_importar_archivo_corrupto_es_400(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    r = cli.post(f"/api/corridas/{cid}/items/importar",
                 files={"archivo": ("malo.xlsx", b"no soy un excel", _XLSX_MIME)})
    assert r.status_code == 400


def test_api_agregar_en_corrida_congelada_es_409(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    assert cli.post(f"/api/corridas/{cid}/congelar").status_code == 200
    r = cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D"}]})
    assert r.status_code == 409
    b = cli.post(f"/api/corridas/{cid}/items/borrar", json={"seqs": [0]})
    assert b.status_code == 409


def test_api_borrar_lineas(tmp_path):
    cli, _ = _cliente(tmp_path)
    cid = _corrida_api(cli, tmp_path)
    cli.post(f"/api/corridas/{cid}/items", json={"lineas": [
        {"descripcion": "Concreto clase D"}]})
    r = cli.post(f"/api/corridas/{cid}/items/borrar", json={"seqs": [0]})
    assert r.status_code == 200, r.text
    assert [f["seq"] for f in r.json()["items"]] == [1]        # sin renumerar


def test_api_corrida_inexistente_es_404(tmp_path):
    cli, _ = _cliente(tmp_path)
    assert cli.post("/api/corridas/999/items",
                    json={"lineas": [{"descripcion": "x"}]}).status_code == 404
    assert cli.post("/api/corridas/999/items/borrar",
                    json={"seqs": [0]}).status_code == 404
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_api_corridas.py -q -k "agregar or preview or importar or borrar or inexistente"`
Expected: FAIL con 404/405 (los endpoints no existen).

- [ ] **Step 3: Agregar los DTOs**

En `apu_tool/servicio/esquemas.py`, después de `ConfirmarLoteIn`:

```python
class LineaNuevaIn(BaseModel):
    """Una actividad que faltó en la corrida, cargada a mano."""
    descripcion: str
    unidad: str = ""
    cantidad: float = 1.0
    precio_contractual: float = 0.0
    shift: Optional[str] = None    # None/vacío = el turno por defecto de la corrida
    item: str = ""                 # nº de ítem del pliego; vacío = se numera solo


class AgregarLineasIn(BaseModel):
    lineas: list[LineaNuevaIn]


class BorrarLineasIn(BaseModel):
    seqs: list[int]
```

- [ ] **Step 4: Extraer `_items_del_upload` y usarlo en los endpoints que ya existen**

En `apu_tool/servicio/rutas.py`, agregar `AgregarLineasIn, BorrarLineasIn` al import de `esquemas` y `LicitacionItem` al import de `apu_tool.nucleo.models` (verificar cómo están escritos esos imports arriba del archivo y respetarlos). Después, agregar el helper justo antes de `crear_corrida`:

```python
def _items_del_upload(nombre: str, contenido: bytes, turno: str) -> list[LicitacionItem]:
    """Bytes de una lista subida -> ítems de licitación. Traduce a 400 los fallos de
    lectura (columna faltante, ítem sin turno, archivo que no es Excel)."""
    suf = Path(nombre or "lic.xlsx").suffix or ".xlsx"
    with tempfile.NamedTemporaryFile(delete=False, suffix=suf) as tmp:
        tmp.write(contenido)
        tmp_path = tmp.name
    try:
        items = read_licitacion(tmp_path, default_shift=turno, require_turno=True)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except (zipfile.BadZipFile, InvalidFileException):
        raise HTTPException(status_code=400,
                            detail="El archivo no es un Excel válido o está corrupto.")
    finally:
        os.unlink(tmp_path)
    if not items:
        raise HTTPException(status_code=400, detail="La lista no tiene ítems legibles.")
    return items
```

En `crear_corrida`, reemplazar el bloque que va desde `suf = Path(...)` hasta el `if not items: raise ...` (líneas 153-166) por:

```python
    items = _items_del_upload(archivo.filename, await archivo.read(), turno)
```

En `crear_corrida_stream`, reemplazar el bloque equivalente (líneas 217-230) por la misma línea.

- [ ] **Step 5: Verificar que el armado por API no cambió**

Run: `python -m pytest tests/test_api_corridas.py tests/test_endurecimiento_excel.py tests/test_licitacion_turno.py -q -k "not agregar and not preview and not importar and not borrar"`
Expected: PASS. Los tests nuevos siguen fallando (todavía no hay endpoints).

- [ ] **Step 6: Agregar los endpoints**

En `apu_tool/servicio/rutas.py`, después de `confirmar_lote` (línea 307). No hay choque de rutas: `/corridas/{cid}/items/{seq}` es GET y estas son POST con segmentos fijos.

```python
def _turno_valido(raw: Optional[str], default: str) -> str:
    """DIURNO/NOCTURNO explícito; vacío cae al turno por defecto de la corrida.
    El turno es parte de la clave del APU: un valor raro no se adivina, se rechaza."""
    if raw is None or not str(raw).strip():
        return default
    turno = str(raw).strip().upper()
    if turno not in (config.SHIFT_DIURNO, config.SHIFT_NOCTURNO):
        raise HTTPException(
            status_code=400,
            detail=f"Turno inválido: {raw}. Debe ser {config.SHIFT_DIURNO} "
                   f"o {config.SHIFT_NOCTURNO}.")
    return turno


def _agregar_o_error(alm: Almacen, cid: int, items) -> dict:
    """Traduce las excepciones de svc.agregar_items al contrato HTTP."""
    try:
        v = svc.agregar_items(alm, cid, items)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para modificar.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v


def _meta_o_404(alm: Almacen, cid: int):
    meta = alm.corridas.get_corrida(cid)
    if meta is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return meta


@router.post("/corridas/{cid}/items/preview")
async def preview_lineas(cid: int, archivo: UploadFile = File(...),
                         alm: Almacen = Depends(get_almacen),
                         _: object = Depends(requiere_rol("consulta"))):
    """Qué se agregaría con este Excel y qué ya está en la corrida. No escribe nada."""
    meta = _meta_o_404(alm, cid)
    items = _items_del_upload(archivo.filename, await archivo.read(), meta.turno_def)
    return svc.preview_agregar(alm, cid, items)


@router.post("/corridas/{cid}/items/importar")
async def importar_lineas(cid: int, archivo: UploadFile = File(...),
                          alm: Almacen = Depends(get_almacen),
                          _: object = Depends(requiere_rol("consulta"))):
    """Agrega a la corrida las líneas del Excel (solo las que faltaron)."""
    meta = _meta_o_404(alm, cid)
    items = _items_del_upload(archivo.filename, await archivo.read(), meta.turno_def)
    return _agregar_o_error(alm, cid, items)


@router.post("/corridas/{cid}/items")
def agregar_lineas(cid: int, body: AgregarLineasIn,
                   alm: Almacen = Depends(get_almacen),
                   _: object = Depends(requiere_rol("consulta"))):
    """Agrega líneas cargadas a mano."""
    meta = _meta_o_404(alm, cid)
    items = []
    for linea in body.lineas:
        desc = (linea.descripcion or "").strip()
        if not desc:
            raise HTTPException(status_code=400, detail="La descripción es obligatoria.")
        items.append(LicitacionItem(
            item=(linea.item or "").strip(), descripcion=desc,
            unidad=(linea.unidad or "").strip(), cantidad=linea.cantidad or 1.0,
            precio_contractual=linea.precio_contractual or 0.0,
            shift=_turno_valido(linea.shift, meta.turno_def)))
    return _agregar_o_error(alm, cid, items)


@router.post("/corridas/{cid}/items/borrar")
def borrar_lineas(cid: int, body: BorrarLineasIn,
                  alm: Almacen = Depends(get_almacen),
                  actor=Depends(requiere_rol("consulta"))):
    """Borra las líneas indicadas. Los seq ajenos a la corrida se saltean."""
    try:
        v = svc.borrar_items(alm, cid, body.seqs, actor=actor)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para modificar.")
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

- [ ] **Step 7: Correr las pruebas de API**

Run: `python -m pytest tests/test_api_corridas.py -q`
Expected: PASS (todas, viejas y nuevas).

- [ ] **Step 8: Suite completa de Python**

Run: `python -m pytest tests/ -q`
Expected: PASS. Ojo con `tests/test_mapa_arquitectura.py`: si falla, es que el mapa de módulos se regenera desde los imports reales — seguir su mensaje. **No commitear.**

---

### Task 5: Diálogo `Agregar líneas` + botón en la corrida

**Files:**
- Modify: `web/src/lib/tipos.ts`
- Modify: `web/src/api/corridas.ts`
- Create: `web/src/components/corrida/DialogoAgregarLineas.tsx`
- Create: `web/src/components/corrida/DialogoAgregarLineas.test.tsx`
- Modify: `web/src/pages/Corrida.tsx`

**Interfaces:**
- Consumes: los endpoints de Task 4; `descargarPlantillaLicitacion` (ya existe en `web/src/api/corridas.ts:102`); `Dialog/DialogContent/DialogFooter/DialogHeader/DialogTitle` de `@/components/ui/dialog`; `Button` de `@/components/ui/button`.
- Produces:
  - `previewLineas(id: number, form: FormData): Promise<PreviewLineas>`
  - `importarLineas(id: number, form: FormData): Promise<CorridaDetalle>`
  - `agregarLineas(id: number, lineas: LineaNueva[]): Promise<CorridaDetalle>`
  - `<DialogoAgregarLineas open corridaId onOpenChange onAgregado />` donde `onAgregado: (c: CorridaDetalle) => void`

- [ ] **Step 1: Escribir la prueba que falla**

Crear `web/src/components/corrida/DialogoAgregarLineas.test.tsx`:

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { describe, expect, it, vi, beforeEach } from "vitest";
import { DialogoAgregarLineas } from "./DialogoAgregarLineas";

const previewLineas = vi.fn();
const importarLineas = vi.fn();
const agregarLineas = vi.fn();
vi.mock("@/api/corridas", () => ({
  previewLineas: (...a: unknown[]) => previewLineas(...a),
  importarLineas: (...a: unknown[]) => importarLineas(...a),
  agregarLineas: (...a: unknown[]) => agregarLineas(...a),
  descargarPlantillaLicitacion: vi.fn(),
}));
vi.mock("sonner", () => ({ toast: { success: vi.fn(), error: vi.fn() } }));

const CORRIDA = {
  id: 7, nombre: "Calle 13", archivo: "lic.xlsx", estado: "en_revision", modo: "activa",
  items: [], duracion_ms: null, carpeta_id: null, lista_precios_id: null,
  lista_nombre: "Principal",
  totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
};

function archivoDemo(): File {
  return new File(["contenido"], "faltantes.xlsx", {
    type: "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
  });
}

beforeEach(() => {
  previewLineas.mockReset();
  importarLineas.mockReset();
  agregarLineas.mockReset();
  previewLineas.mockResolvedValue({
    total: 2, tope: 100, modo: "activa",
    nuevas: [{ item: "9", descripcion: "SARDINEL A-10", unidad: "ML", cantidad: 5,
               precio_contractual: 40000, shift: "DIURNO" }],
    duplicadas: [{ item: "10", descripcion: "CONCRETO CLASE D", unidad: "M3", cantidad: 1,
                   precio_contractual: 400000, shift: "DIURNO", seq_existente: 0 }],
  });
  importarLineas.mockResolvedValue(CORRIDA);
  agregarLineas.mockResolvedValue(CORRIDA);
});

describe("DialogoAgregarLineas", () => {
  it("agrega una línea a mano con el turno elegido", async () => {
    const onAgregado = vi.fn();
    render(<DialogoAgregarLineas open corridaId={7} onOpenChange={() => {}}
                                 onAgregado={onAgregado} />);
    fireEvent.change(screen.getByLabelText("Descripción de la actividad"),
                     { target: { value: "Sardinel A-10" } });
    fireEvent.change(screen.getByLabelText("Unidad"), { target: { value: "ML" } });
    fireEvent.change(screen.getByLabelText("Cantidad"), { target: { value: "5" } });
    fireEvent.change(screen.getByLabelText("Precio contractual"), { target: { value: "40000" } });
    fireEvent.change(screen.getByLabelText("Turno"), { target: { value: "NOCTURNO" } });
    fireEvent.click(screen.getByText("Agregar la línea"));

    await waitFor(() => expect(agregarLineas).toHaveBeenCalledWith(7, [{
      descripcion: "Sardinel A-10", unidad: "ML", cantidad: 5,
      precio_contractual: 40000, shift: "NOCTURNO",
    }]));
    expect(onAgregado).toHaveBeenCalledWith(CORRIDA);
  });

  it("no deja agregar una línea sin descripción", async () => {
    render(<DialogoAgregarLineas open corridaId={7} onOpenChange={() => {}}
                                 onAgregado={() => {}} />);
    expect((screen.getByText("Agregar la línea") as HTMLButtonElement).disabled).toBe(true);
    expect(agregarLineas).not.toHaveBeenCalled();
  });

  it("el Excel muestra la previa con las duplicadas antes de aplicar", async () => {
    render(<DialogoAgregarLineas open corridaId={7} onOpenChange={() => {}}
                                 onAgregado={() => {}} />);
    fireEvent.click(screen.getByText("Desde Excel"));
    const input = document.querySelector('input[type="file"]') as HTMLInputElement;
    fireEvent.change(input, { target: { files: [archivoDemo()] } });

    await waitFor(() => expect(previewLineas).toHaveBeenCalled());
    expect(await screen.findByText("SARDINEL A-10")).toBeTruthy();
    expect(screen.getByText(/ya está en la corrida/i)).toBeTruthy();
    expect(screen.getByText(/línea 0/i)).toBeTruthy();
    expect(importarLineas).not.toHaveBeenCalled();          // la previa no aplica

    fireEvent.click(screen.getByText("Agregar 2 líneas"));
    await waitFor(() => expect(importarLineas).toHaveBeenCalled());
    expect((importarLineas.mock.calls[0][1] as FormData).get("archivo")).toBeTruthy();
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npm run test -- --run DialogoAgregarLineas`
Expected: FAIL — no existe `./DialogoAgregarLineas`.

- [ ] **Step 3: Agregar los tipos**

En `web/src/lib/tipos.ts`, después de `ItemCuadro`:

```ts
/** Una línea tal como la leyó el Excel, antes de armarse. */
export interface LineaPreview {
  item: string;
  descripcion: string;
  unidad: string;
  cantidad: number;
  precio_contractual: number;
  shift: string;
  /** Presente solo en `duplicadas`: el seq de la línea que ya está en la corrida. */
  seq_existente?: number;
}

export interface PreviewLineas {
  total: number;
  nuevas: LineaPreview[];
  duplicadas: LineaPreview[];
  modo: string;
  tope: number;
}

/** Línea cargada a mano. `shift` vacío = el turno por defecto de la corrida. */
export interface LineaNueva {
  descripcion: string;
  unidad?: string;
  cantidad?: number;
  precio_contractual?: number;
  shift?: string;
  item?: string;
}
```

- [ ] **Step 4: Agregar las funciones de API**

En `web/src/api/corridas.ts`: sumar `PreviewLineas` y `LineaNueva` al import de tipos, y agregar después de `confirmarLote`:

```ts
/** Qué se agregaría con este Excel (y qué ya está en la corrida). No escribe. */
export function previewLineas(id: number, form: FormData): Promise<PreviewLineas> {
  return apiPost<PreviewLineas>(`/corridas/${id}/items/preview`, form);
}

/** Agrega a la corrida las líneas del Excel. Devuelve la corrida recosteada. */
export function importarLineas(id: number, form: FormData): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/importar`, form);
}

/** Agrega líneas cargadas a mano. Devuelve la corrida recosteada. */
export function agregarLineas(id: number, lineas: LineaNueva[]): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items`, { lineas });
}
```

- [ ] **Step 5: Escribir el diálogo**

Crear `web/src/components/corrida/DialogoAgregarLineas.tsx`:

```tsx
import { useRef, useState } from "react";
import { toast } from "sonner";
import { Download } from "lucide-react";
import { Button } from "@/components/ui/button";
import {
  Dialog, DialogContent, DialogFooter, DialogHeader, DialogTitle,
} from "@/components/ui/dialog";
import {
  agregarLineas, importarLineas, previewLineas, descargarPlantillaLicitacion,
} from "@/api/corridas";
import { cop } from "@/lib/moneda";
import type { CorridaDetalle, LineaPreview, PreviewLineas } from "@/lib/tipos";

interface Props {
  open: boolean;
  corridaId: number;
  onOpenChange: (open: boolean) => void;
  onAgregado: (corrida: CorridaDetalle) => void;
}

type Via = "manual" | "excel";
type FaseExcel = "idle" | "cargando" | "preview" | "aplicando";

const CAMPO = "h-7 rounded border border-input bg-background px-2 text-xs";

export function DialogoAgregarLineas({ open, corridaId, onOpenChange, onAgregado }: Props) {
  const [via, setVia] = useState<Via>("manual");

  // --- línea a mano ---
  const [descripcion, setDescripcion] = useState("");
  const [unidad, setUnidad] = useState("");
  const [cantidad, setCantidad] = useState("1");
  const [precio, setPrecio] = useState("0");
  const [turno, setTurno] = useState("");
  const [guardando, setGuardando] = useState(false);

  // --- excel ---
  const fileRef = useRef<HTMLInputElement>(null);
  const archivoRef = useRef<File | null>(null);
  const [fase, setFase] = useState<FaseExcel>("idle");
  const [prev, setPrev] = useState<PreviewLineas | null>(null);
  const [errorMsg, setErrorMsg] = useState<string | null>(null);

  function resetear() {
    setVia("manual");
    setDescripcion(""); setUnidad(""); setCantidad("1"); setPrecio("0"); setTurno("");
    setGuardando(false);
    setFase("idle"); setPrev(null); setErrorMsg(null);
    archivoRef.current = null;
    if (fileRef.current) fileRef.current.value = "";
  }

  function cerrar(v: boolean) {
    if (!v) resetear();
    onOpenChange(v);
  }

  async function guardarManual() {
    const desc = descripcion.trim();
    if (!desc) return;
    setGuardando(true);
    try {
      const corrida = await agregarLineas(corridaId, [{
        descripcion: desc,
        unidad: unidad.trim(),
        cantidad: Number(cantidad) || 1,
        precio_contractual: Number(precio) || 0,
        ...(turno ? { shift: turno } : {}),
      }]);
      toast.success("Línea agregada");
      onAgregado(corrida);
      cerrar(false);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo agregar la línea.");
      setGuardando(false);
    }
  }

  async function elegirArchivo(e: React.ChangeEvent<HTMLInputElement>) {
    const archivo = e.target.files?.[0];
    if (!archivo) return;
    archivoRef.current = archivo;
    setErrorMsg(null);
    setPrev(null);
    setFase("cargando");
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      setPrev(await previewLineas(corridaId, form));
      setFase("preview");
    } catch (err) {
      setErrorMsg(err instanceof Error ? err.message : "Error al leer el archivo");
      setFase("idle");
    }
  }

  async function aplicarExcel() {
    const archivo = archivoRef.current;
    if (!archivo || !prev) return;
    setFase("aplicando");
    try {
      const form = new FormData();
      form.append("archivo", archivo);
      const corrida = await importarLineas(corridaId, form);
      toast.success(`${prev.total} ${prev.total === 1 ? "línea agregada" : "líneas agregadas"}`);
      onAgregado(corrida);
      cerrar(false);
    } catch (err) {
      toast.error(err instanceof Error ? err.message : "No se pudo agregar las líneas.");
      setFase("preview");
    }
  }

  async function bajarPlantilla() {
    try {
      await descargarPlantillaLicitacion();
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo descargar la plantilla.");
    }
  }

  const pasadoDeTope = prev !== null && prev.total > prev.tope;

  return (
    <Dialog open={open} onOpenChange={cerrar}>
      <DialogContent className="max-w-2xl">
        <DialogHeader>
          <DialogTitle className="text-sm">Agregar líneas a la corrida</DialogTitle>
        </DialogHeader>

        <div className="flex gap-1">
          <Button size="xs" variant={via === "manual" ? "default" : "outline"}
                  onClick={() => setVia("manual")}>Una línea</Button>
          <Button size="xs" variant={via === "excel" ? "default" : "outline"}
                  onClick={() => setVia("excel")}>Desde Excel</Button>
        </div>

        {via === "manual" ? (
          <div className="flex flex-col gap-2">
            <label className="flex flex-col gap-0.5 text-xs">
              Descripción de la actividad
              <input aria-label="Descripción de la actividad" className={CAMPO}
                     value={descripcion} onChange={(e) => setDescripcion(e.target.value)} />
            </label>
            <div className="grid grid-cols-4 gap-2">
              <label className="flex flex-col gap-0.5 text-xs">
                Unidad
                <input aria-label="Unidad" className={CAMPO} value={unidad}
                       onChange={(e) => setUnidad(e.target.value)} />
              </label>
              <label className="flex flex-col gap-0.5 text-xs">
                Cantidad
                <input aria-label="Cantidad" className={CAMPO} type="number" value={cantidad}
                       onChange={(e) => setCantidad(e.target.value)} />
              </label>
              <label className="flex flex-col gap-0.5 text-xs">
                Precio contractual
                <input aria-label="Precio contractual" className={CAMPO} type="number"
                       value={precio} onChange={(e) => setPrecio(e.target.value)} />
              </label>
              <label className="flex flex-col gap-0.5 text-xs">
                Turno
                <select aria-label="Turno" className={CAMPO} value={turno}
                        onChange={(e) => setTurno(e.target.value)}>
                  <option value="">El de la corrida</option>
                  <option value="DIURNO">DIURNO</option>
                  <option value="NOCTURNO">NOCTURNO</option>
                </select>
              </label>
            </div>
            <p className="text-xs text-muted-foreground">
              La línea se arma con el mismo matcher que la corrida: queda por revisar y
              se le confirma o cambia el APU desde la tabla.
            </p>
          </div>
        ) : (
          <div className="flex flex-col gap-3">
            <p className="text-xs text-muted-foreground">
              Subí un Excel con <span className="font-semibold">solo las actividades que
              faltaron</span>, con las mismas columnas de la lista de licitación. El turno
              (DIURNO/NOCTURNO) es obligatorio por línea.
            </p>
            <div className="flex flex-wrap items-center gap-3">
              <input
                ref={fileRef}
                type="file"
                accept=".xlsx,.xls,.csv"
                onChange={elegirArchivo}
                disabled={fase === "cargando" || fase === "aplicando"}
                className="text-xs file:mr-2 file:rounded file:border file:border-border file:bg-muted file:px-2 file:py-0.5 file:text-xs file:font-medium file:cursor-pointer cursor-pointer disabled:opacity-50"
              />
              {fase === "cargando" && (
                <span className="text-xs text-muted-foreground animate-pulse">leyendo…</span>
              )}
              <Button size="sm" variant="outline" type="button" onClick={bajarPlantilla}
                      className="ml-auto">
                <Download className="mr-1 h-3.5 w-3.5" />
                Descargar plantilla
              </Button>
            </div>

            {errorMsg && <p className="text-xs text-destructive">{errorMsg}</p>}

            {prev && (
              <div className="flex flex-col gap-3">
                <TablaPrev titulo={`Se agregan (${prev.nuevas.length})`} filas={prev.nuevas} />
                {prev.duplicadas.length > 0 && (
                  <div className="flex flex-col gap-1">
                    <p className="text-xs font-semibold text-amber-700">
                      {prev.duplicadas.length === 1
                        ? "1 actividad ya está en la corrida"
                        : `${prev.duplicadas.length} actividades ya están en la corrida`}
                    </p>
                    <p className="text-xs text-muted-foreground">
                      Se agregan igual, como líneas nuevas. Si no las querés, sacalas del
                      Excel y volvé a subirlo.
                    </p>
                    <TablaPrev titulo="" filas={prev.duplicadas} conExistente />
                  </div>
                )}
                {pasadoDeTope && (
                  <p className="text-xs text-destructive">
                    El archivo trae {prev.total} líneas y el máximo por vez es {prev.tope}.
                    Partilo en varios archivos.
                  </p>
                )}
              </div>
            )}
          </div>
        )}

        <DialogFooter>
          <Button size="sm" variant="outline" onClick={() => cerrar(false)}
                  disabled={guardando || fase === "aplicando"}>
            Cancelar
          </Button>
          {via === "manual" ? (
            <Button size="sm" onClick={guardarManual}
                    disabled={guardando || descripcion.trim() === ""}>
              {guardando ? "Agregando…" : "Agregar la línea"}
            </Button>
          ) : (
            <Button size="sm" onClick={aplicarExcel}
                    disabled={fase !== "preview" || prev === null || prev.total === 0 || pasadoDeTope}>
              {fase === "aplicando"
                ? "Agregando…"
                : `Agregar ${prev?.total ?? 0} ${prev?.total === 1 ? "línea" : "líneas"}`}
            </Button>
          )}
        </DialogFooter>
      </DialogContent>
    </Dialog>
  );
}

function TablaPrev({ titulo, filas, conExistente = false }: {
  titulo: string; filas: LineaPreview[]; conExistente?: boolean;
}) {
  return (
    <div className="flex flex-col gap-1">
      {titulo && <p className="text-xs font-semibold">{titulo}</p>}
      {filas.length === 0 ? (
        <p className="text-xs text-muted-foreground">Ninguna.</p>
      ) : (
        <div className="max-h-52 overflow-auto rounded border">
          <table className="w-full text-xs">
            <thead className="bg-muted/50">
              <tr>
                <th className="px-2 py-1 text-left font-medium">Ítem</th>
                <th className="px-2 py-1 text-left font-medium">Descripción</th>
                <th className="px-2 py-1 text-left font-medium">Und</th>
                <th className="px-2 py-1 text-right font-medium">Cantidad</th>
                <th className="px-2 py-1 text-right font-medium">Contractual</th>
                <th className="px-2 py-1 text-left font-medium">Turno</th>
                {conExistente && <th className="px-2 py-1 text-left font-medium">Ya está</th>}
              </tr>
            </thead>
            <tbody>
              {filas.map((f, i) => (
                <tr key={`${f.item}-${i}`} className="border-t">
                  <td className="px-2 py-1 font-mono">{f.item}</td>
                  <td className="px-2 py-1">{f.descripcion}</td>
                  <td className="px-2 py-1">{f.unidad}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{f.cantidad}</td>
                  <td className="px-2 py-1 text-right tabular-nums">{cop(f.precio_contractual)}</td>
                  <td className="px-2 py-1">{f.shift}</td>
                  {conExistente && (
                    <td className="px-2 py-1 text-muted-foreground">línea {f.seq_existente}</td>
                  )}
                </tr>
              ))}
            </tbody>
          </table>
        </div>
      )}
    </div>
  );
}
```

- [ ] **Step 6: Correr la prueba del diálogo**

Run: `cd web && npm run test -- --run DialogoAgregarLineas`
Expected: PASS (3 pruebas). Si el texto de un `getByText` no coincide exactamente con lo renderizado, ajustar la **prueba** al texto real del componente, no al revés.

- [ ] **Step 7: Enganchar el botón en la página de la corrida**

En `web/src/pages/Corrida.tsx`:

1. Agregar los imports:

```tsx
import { DialogoAgregarLineas } from "@/components/corrida/DialogoAgregarLineas";
```

2. Agregar el estado, junto a los otros `useState`:

```tsx
  const [agregando, setAgregando] = useState(false);
```

3. Dentro del bloque `{!live && (...)}` de la cabecera, antes del botón `Descargar cuadro`:

```tsx
            {data.modo !== "congelada" && (
              <Button size="sm" variant="outline" onClick={() => setAgregando(true)}>
                Agregar líneas
              </Button>
            )}
```

4. Antes del cierre del `<div>` raíz del `return` (después de `<TablaItems ... />`):

```tsx
      {agregando && (
        <DialogoAgregarLineas
          open
          corridaId={corridaId}
          onOpenChange={(v) => { if (!v) setAgregando(false); }}
          onAgregado={(c) => { setCorrida(c); setAgregando(false); }}
        />
      )}
```

- [ ] **Step 8: Verificar el frontend completo**

Run: `cd web && npm run test -- --run`
Expected: PASS (toda la suite).

Run: `cd web && npm run build`
Expected: build OK. `npm run build` corre `tsc -b`, que es lo que atrapa los errores de tipos reales (`tsc --noEmit` no alcanza).

**No commitear.**

---

### Task 6: Borrar líneas marcadas

**Files:**
- Modify: `web/src/api/corridas.ts`
- Modify: `web/src/components/corrida/TablaItems.tsx` (barra de líneas marcadas, líneas 423-441)
- Test: `web/src/components/corrida/TablaItems.test.tsx`

**Interfaces:**
- Consumes: `POST /corridas/{cid}/items/borrar` (Task 4); `accionLote`, `seleccionadas`, `limpiarSeleccion`, `enLote`, `onConfirmado` (ya existen en `TablaItems.tsx`).
- Produces: `borrarLineas(id: number, seqs: number[]): Promise<CorridaDetalle>`

- [ ] **Step 1: Escribir la prueba que falla**

En `web/src/components/corrida/TablaItems.test.tsx`, agregar `borrarLineas` al mock de `@/api/corridas` (dentro del `vi.mock` de arriba del archivo, junto a `confirmarLote`):

```tsx
  borrarLineas: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
  })),
```

Y agregar al final del archivo:

```tsx
test("borra las líneas marcadas después de confirmar", async () => {
  const { borrarLineas } = await import("@/api/corridas");
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(true);
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 3"));
  fireEvent.click(await screen.findByText("Borrar"));

  expect(confirmSpy).toHaveBeenCalledWith(expect.stringContaining("2 líneas"));
  await waitFor(() => expect(borrarLineas).toHaveBeenCalledWith(1, [0, 2]));
  confirmSpy.mockRestore();
});

test("cancelar la confirmación no borra nada", async () => {
  const { borrarLineas } = await import("@/api/corridas");
  vi.mocked(borrarLineas).mockClear();
  const confirmSpy = vi.spyOn(window, "confirm").mockReturnValue(false);
  render(<TablaConControl items={itemsCuatro()} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(await screen.findByText("Borrar"));

  expect(borrarLineas).not.toHaveBeenCalled();
  confirmSpy.mockRestore();
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npm run test -- --run TablaItems`
Expected: FAIL — no existe el botón "Borrar" (`Unable to find an element with the text: Borrar`).

- [ ] **Step 3: Agregar la función de API**

En `web/src/api/corridas.ts`, después de `agregarLineas`:

```ts
/** Borra las líneas indicadas. No renumera: los seq que quedan no cambian. */
export function borrarLineas(id: number, seqs: number[]): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/borrar`, { seqs });
}
```

- [ ] **Step 4: Agregar el borrado a la tabla**

En `web/src/components/corrida/TablaItems.tsx`:

1. Sumar `borrarLineas` al import de `@/api/corridas` (línea 19):

```tsx
import { getItem, confirmar, confirmarLote, borrarLineas } from "@/api/corridas";
```

2. Agregar la función después de `accionLote` (línea 195):

```tsx
  /** Borrar es destructivo y no se deshace: se pregunta antes (igual que borrar
   *  una corrida en Mis corridas). */
  async function borrarSeleccionadas() {
    const n = seleccionadas.length;
    if (n === 0) return;
    const mensaje = n === 1
      ? "¿Borrar 1 línea de la corrida? No se puede deshacer."
      : `¿Borrar ${n} líneas de la corrida? No se puede deshacer.`;
    if (!window.confirm(mensaje)) return;
    setEnLote(true);
    try {
      const actualizada = await borrarLineas(corridaId, seleccionadas);
      onConfirmado(actualizada);
      limpiarSeleccion();
      toast.success(n === 1 ? "1 línea borrada" : `${n} líneas borradas`);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo borrar las líneas.");
    } finally {
      setEnLote(false);
    }
  }
```

3. En la barra de líneas marcadas, entre el botón `Confirmar el APU actual` y el `Limpiar` (líneas 434-439):

```tsx
          <Button size="xs" variant="destructive" disabled={enLote}
                  onClick={borrarSeleccionadas}>
            Borrar
          </Button>
```

- [ ] **Step 5: Correr las pruebas de la tabla**

Run: `cd web && npm run test -- --run TablaItems`
Expected: PASS (todas, viejas y nuevas).

- [ ] **Step 6: Verificación final completa**

Run: `python -m pytest tests/ -q`
Expected: PASS.

Run: `cd web && npm run test -- --run`
Expected: PASS.

Run: `cd web && npm run build`
Expected: build OK.

Run: `git status --short`
Expected: solo archivos modificados/nuevos de este plan, **sin ningún commit**. Los archivos del PR de Google (`apu_tool/servicio/auth.py`, `apu_tool/datos/perfiles_db.py`, `web/src/pages/Login.tsx`) NO deben aparecer en la lista.

**No commitear.** Reportar al usuario qué archivos cambiaron y que falta el smoke test en el navegador (levantar la web en local: la receta de `SUPABASE_URL` + `APU_ADMIN_EMAILS`).

---

## Autorrevisión del plan

**Cobertura del spec:**
- Agregar una línea a mano → Task 4 (endpoint) + Task 5 (diálogo) ✓
- Agregar por Excel con vista previa → Tasks 2, 4, 5 ✓
- Borrar líneas → Tasks 3, 6 ✓
- Solo corrida activa / 409 si congelada → Tasks 1, 3, 4 ✓
- `seq` sin renumerar, huecos no reusados → Tasks 1, 3 (pruebas explícitas) ✓
- Duplicadas se avisan y se agregan igual → Task 2 ✓
- `finalizada` → `en_revision` → Tasks 1, 3 ✓
- Tope de 100 → Tasks 1, 5 (aviso en la previa) ✓
- Auditoría del borrado → Task 3 ✓
- Rol `consulta` → Task 4 ✓
- Doble backend → Task 3 ✓
- `use_ai` y lista de precios de la corrida → Task 1 (prueba de lista NP en $0 con alerta) ✓
- Plantilla de licitación reusada → Task 5 (`descargarPlantillaLicitacion`) ✓

**Consistencia de nombres entre tareas:** `_armar_fila`, `agregar_items`, `preview_agregar`, `borrar_items`, `MAX_LINEAS_AGREGADAS`, `_items_del_upload`, `_turno_valido`, `_agregar_o_error`, `_meta_o_404`, `previewLineas`, `importarLineas`, `agregarLineas`, `borrarLineas`, `PreviewLineas`, `LineaPreview`, `LineaNueva`, `DialogoAgregarLineas`, `onAgregado` — usados igual en todas las tareas. La ruta de borrado es `POST /corridas/{cid}/items/borrar` en Tasks 4 y 6.

**Sin placeholders:** cada paso trae el código o el comando exacto.
