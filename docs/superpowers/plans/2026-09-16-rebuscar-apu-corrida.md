# Volver a buscar APU en una corrida activa — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Un botón en la corrida activa que vuelve a correr el matcher del armado sobre las filas no confirmadas, muestra en una vista previa qué cambiaría (con costo y margen), y aplica solo lo que el usuario marque.

**Architecture:** Dos funciones de servicio sobre un helper compartido. `_propuestas_rebusqueda()` re-corre el matcher por la vía rápida del índice invertido (0,2 ms por fila en vez de 42) sobre las filas que no están `confirmed`, y costea solo las que cambiarían de APU. `rebuscar()` devuelve eso sin escribir nada; `aplicar_rebusqueda()` lo **recalcula del lado del servidor** y escribe solo los `seq` pedidos cuya propuesta siga vigente. La vía rápida es exacta para asignar: `similarity = 0.4·secuencia + 0.6·jaccard`, así que un APU sin tokens en común tope en 0,40 y el mínimo para asignar es 0,55.

**Tech Stack:** Python 3 + FastAPI + SQLite/Postgres (dos backends espejo) · React + TypeScript + Vite + Tailwind · pytest + vitest.

**Spec:** `docs/superpowers/specs/2026-09-16-rebuscar-apu-corrida-design.md`

**Rama:** `feat/rebuscar-apu-corrida` (ya creada, con el spec commiteado). No se pushea a master sin OK explícito.

---

## Estructura de archivos

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `apu_tool/dominio/matching.py` | `candidates()`/`match()` aceptan `escaneo_completo` | Modificar |
| `apu_tool/datos/repositorio.py` | contrato `set_candidatos` (Protocol) | Modificar |
| `apu_tool/datos/corridas_db.py` | `set_candidatos` SQLite | Modificar |
| `apu_tool/datos/pg/corridas_pg.py` | `set_candidatos` Postgres | Modificar |
| `apu_tool/servicio/corridas.py` | `_propuestas_rebusqueda`, `rebuscar`, `aplicar_rebusqueda` | Modificar |
| `apu_tool/servicio/esquemas.py` | `RebuscarAplicarIn` | Modificar |
| `apu_tool/servicio/rutas.py` | los dos endpoints | Modificar |
| `web/src/lib/tipos.ts` | `PropuestaRebusqueda`, `RebusquedaPrevia` | Modificar |
| `web/src/api/corridas.ts` | `rebuscarApus`, `aplicarRebusqueda` | Modificar |
| `web/src/components/corrida/DialogoRebuscar.tsx` | la vista previa | Crear |
| `web/src/pages/Corrida.tsx` | el botón y el cableado | Modificar |
| `CLAUDE.md` | la sección de datos que documenta la feature | Modificar |

---

## Task 1: el matcher puede saltarse el escaneo completo

**Files:**
- Modify: `apu_tool/dominio/matching.py:78-101`
- Test: `tests/test_matching_optimizacion.py`

- [ ] **Step 1: Escribir el test que falla**

Al final de `tests/test_matching_optimizacion.py`:

```python
def test_via_rapida_no_cambia_ninguna_asignacion():
    """GATE de `servicio/corridas.py::rebuscar`: saltarse el `_full_scan` de respaldo
    no puede cambiar el estado ni el APU elegido de NINGUNA consulta.

    Es exacto por construcción, no por suerte: `similarity` es
    0.4*secuencia + 0.6*jaccard, así que un APU sin ningún token en común tiene
    jaccard 0 y su score no pasa de 0.4 — debajo del 0.55 de MATCH_REVIEW. Todo lo
    que se puede asignar comparte tokens, y eso ya lo encuentra el índice invertido.
    Lo único que la vía rápida no trae es la cola de candidatos de relleno.
    """
    matcher = Matcher([(c, n, s) for (c, n, s) in _APUS])
    diffs = []
    for descripcion, shift in _queries():
        item = LicitacionItem(item="1", descripcion=descripcion, unidad="UN",
                              cantidad=1.0, precio_contractual=1.0, shift=shift)
        completo = matcher.match(item)
        rapido = matcher.match(item, escaneo_completo=False)
        esperado = (completo.status,
                    completo.elegido.apu_codigo if completo.elegido else None)
        got = (rapido.status, rapido.elegido.apu_codigo if rapido.elegido else None)
        if got != esperado:
            diffs.append((descripcion, shift, esperado, got))
        # Donde hay algo asignable, el mejor candidato también tiene que ser el mismo:
        # es la base con la que `assemble_item` arma una fila `review`.
        if completo.candidatos and completo.candidatos[0].score >= config.MATCH_REVIEW:
            mejor_rapido = rapido.candidatos[0].apu_codigo if rapido.candidatos else None
            if mejor_rapido != completo.candidatos[0].apu_codigo:
                diffs.append((descripcion, shift,
                              completo.candidatos[0].apu_codigo, mejor_rapido))
    assert not diffs, f"La vía rápida divergió en {len(diffs)}: {diffs[:5]}"
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_matching_optimizacion.py::test_via_rapida_no_cambia_ninguna_asignacion -q`
Expected: FAIL con `TypeError: match() got an unexpected keyword argument 'escaneo_completo'`

- [ ] **Step 3: Implementar**

En `apu_tool/dominio/matching.py`, cambiar la firma de `candidates` (línea ~78):

```python
    def candidates(self, descripcion: str, shift: str, top_n: int = 5,
                   escaneo_completo: bool = True) -> list[MatchCandidate]:
```

y reemplazar el bloque final del método (el que hoy dice "Garantía exacta…") por:

```python
        # Garantía exacta: si el mejor con tokens en común alcanza REVISAR, ese es el
        # mejor global (un APU sin tokens comunes tiene jaccard 0 -> score ≤ 0.4 < 0.55).
        if best >= config.MATCH_REVIEW:
            return self._top(scored, top_n)
        if not escaneo_completo:
            # Vía rápida a secas: la usa el re-match de una corrida
            # (`servicio/corridas.py::rebuscar`), que recorre miles de filas de una.
            # Las ASIGNACIONES salen idénticas por la misma garantía de arriba; lo que
            # no aparece es la cola de candidatos de relleno (score < 0.4), que no se
            # puede asignar ni con permiso. 0.2 ms por fila en vez de 42.
            #
            # ponytail: techo conocido — `similarity` devuelve 1.0 por atajo cuando los
            # textos normalizados son idénticos, SIN mirar tokens. Una descripción cuyo
            # set de tokens quede vacío (`_tokens` filtra) y que además coincida exacto
            # con el nombre de un APU no la vería esta vía. No hay ningún caso así en la
            # biblioteca de hoy; si aparece, se llama con `escaneo_completo=True`.
            return self._top(scored, top_n)
        # Débil/novedoso: el mejor global podría ser un APU sin tokens comunes (alta
        # similitud de caracteres) -> escaneo completo exacto para no perderlo.
        return self._full_scan(descripcion, pool, top_n)
```

y la firma de `match` (línea ~103), pasando la bandera:

```python
    def match(self, item: LicitacionItem, escaneo_completo: bool = True) -> MatchResult:
        cands = self.candidates(item.descripcion, item.shift,
                                escaneo_completo=escaneo_completo)
```

- [ ] **Step 4: Correr los tests del matcher**

Run: `python -m pytest tests/test_matching.py tests/test_matching_optimizacion.py tests/test_assemble.py tests/test_assemble_codigo.py -q`
Expected: PASS, todo verde. El armado sigue llamando con el default, así que no cambia nada.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/dominio/matching.py tests/test_matching_optimizacion.py
git commit -m "feat(matching): via rapida opcional sin escaneo completo

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 2: `set_candidatos` por lote en los dos backends

**Files:**
- Modify: `apu_tool/datos/repositorio.py:229` (después de `actualizar_eleccion`)
- Modify: `apu_tool/datos/corridas_db.py:266` (después de `actualizar_eleccion`)
- Modify: `apu_tool/datos/pg/corridas_pg.py` (después de su `actualizar_eleccion`)
- Test: `tests/test_corridas_contrato.py`

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `tests/test_corridas_contrato.py`:

```python
def test_set_candidatos_refresca_por_lote(repo):
    """Varias filas en UNA llamada, y las no pedidas intactas."""
    cid = _corrida_con(repo, _item(0, 1000.0), _item(1, 2000.0), _item(2, 3000.0))
    frescos = [{"apu_codigo": "A9", "apu_nombre": "APU NUEVO", "score": 0.7,
                "motivo": ""}]
    repo.set_candidatos(cid, {0: frescos, 2: frescos})
    filas = {r.seq: r for r in repo.get_items(cid)}
    assert filas[0].candidatos == frescos
    assert filas[2].candidatos == frescos
    assert filas[1].candidatos == []          # no se pidió: intacta


def test_set_candidatos_no_toca_el_apu_ni_el_veredicto_ni_el_costo_a_mano(repo):
    """Refrescar candidatos NO es cambiar de APU: por eso no pasa por
    `actualizar_eleccion`, que borra el veredicto y el costo puesto a mano."""
    cid = _corrida_con(repo, _item(0, 1000.0))
    repo.actualizar_eleccion(cid, 0, status="confirmed", apu_codigo="A1",
                             apu_nombre="APU UNO", unidad="M3", shift="DIURNO",
                             origen="historico", confianza=1.0, explicacion="ok",
                             componentes=[])
    # El orden importa: `set_costo_manual` BORRA el veredicto (poner el costo a mano
    # es un confirm), así que el veredicto se pone después, o este test probaría que
    # `set_candidatos` no borró algo que ya no estaba.
    repo.set_costo_manual(cid, {0: 5000.0})
    repo.set_revision(cid, 0, {"veredicto": "ok", "apu_evaluado": "A1"})
    repo.set_candidatos(cid, {0: [{"apu_codigo": "A2", "apu_nombre": "OTRO",
                                   "score": 0.6, "motivo": ""}]})
    fila = repo.get_items(cid)[0]
    assert fila.candidatos[0]["apu_codigo"] == "A2"
    assert fila.apu_codigo == "A1"
    assert fila.status == "confirmed"
    assert fila.revision is not None
    assert fila.costo_manual == 5000.0


def test_set_candidatos_vacio_no_escribe(repo):
    """Igual que `set_costo_manual`: un lote vacío es una no-operación, no un error."""
    cid = _corrida_con(repo, _item(0, 1000.0))
    repo.set_candidatos(cid, {})
    assert repo.get_items(cid)[0].candidatos == []
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_corridas_contrato.py -q -k candidatos`
Expected: FAIL con `AttributeError: 'CorridasDB' object has no attribute 'set_candidatos'`

- [ ] **Step 3: Implementar el Protocol**

En `apu_tool/datos/repositorio.py`, justo después del `...` de `actualizar_eleccion`:

```python
    def set_candidatos(self, corrida_id: int,
                       candidatos: dict[int, list[dict]]) -> None:
        """Refresca la lista de candidatos de varias filas, {seq: candidatos}.

        NO toca el APU elegido, ni el veredicto, ni el costo puesto a mano: refrescar
        candidatos no es cambiar de APU, y por eso no pasa por `actualizar_eleccion`,
        que borra los dos.

        Es por lote (no fila por fila) por la misma razón que `set_costo_manual`: crear
        un APU puede cambiar la lista de cientos de filas, y contra Postgres eso serían
        cientos de round-trips. Un dict vacío no escribe nada."""
        ...
```

- [ ] **Step 4: Implementar SQLite**

En `apu_tool/datos/corridas_db.py`, después de `actualizar_eleccion`:

```python
    def set_candidatos(self, corrida_id: int,
                       candidatos: dict[int, list[dict]]) -> None:
        """Ver el contrato en repositorio.py."""
        if not candidatos:
            return
        filas = [(json.dumps(c, ensure_ascii=False), int(corrida_id), int(s))
                 for s, c in candidatos.items()]
        with self.connect() as conn:
            conn.executemany(
                "UPDATE corrida_item SET candidatos_json=? "
                "WHERE corrida_id=? AND seq=?", filas)
```

- [ ] **Step 5: Implementar Postgres**

En `apu_tool/datos/pg/corridas_pg.py`, después de su `actualizar_eleccion`:

```python
    def set_candidatos(self, corrida_id: int,
                       candidatos: dict[int, list[dict]]) -> None:
        """Ver el contrato en repositorio.py."""
        if not candidatos:
            return
        filas = [(json.dumps(c, ensure_ascii=False), int(corrida_id), int(s))
                 for s, c in candidatos.items()]
        with self.cx.connection() as c, c.cursor() as cur:
            cur.executemany(
                "UPDATE corridas.corrida_item SET candidatos_json=%s "
                "WHERE corrida_id=%s AND seq=%s", filas)
```

- [ ] **Step 6: Correr los tests**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: PASS. (Con `TEST_DATABASE_URL` puesto corre también contra Postgres; sin esa variable solo SQLite, y está bien.)

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_contrato.py
git commit -m "feat(datos): set_candidatos por lote en los dos backends

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 3: `rebuscar()` — la propuesta, sin escribir nada

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (después de `confirmar_item`, ~línea 1007)
- Test: `tests/test_servicio_rebuscar.py` (crear)

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_servicio_rebuscar.py`:

```python
# tests/test_servicio_rebuscar.py
"""Volver a buscar APU: el re-match de una corrida activa contra la biblioteca de hoy."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas


def _almacen(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([
        Insumo("100", "Concreto 3000 PSI", "M3", "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent("A1", "DIURNO", "100", "Concreto 3000 PSI", "M3", 1.0, 350000.0)])
    return alm


def _agregar_apu(alm, codigo, nombre, rendimiento=2.0, shift="DIURNO"):
    alm.apus.insert_apus([Apu(codigo, nombre, "M3", shift, "ESTRUCTURAS")])
    alm.apus.insert_components([
        ApuComponent(codigo, shift, "100", "Concreto 3000 PSI", "M3",
                     rendimiento, 350000.0)])


def _item(desc, n="1"):
    return LicitacionItem(item=n, descripcion=desc, unidad="M3", cantidad=10.0,
                          precio_contractual=900000.0, shift="DIURNO")


def test_rebuscar_encuentra_un_apu_creado_despues_del_armado(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    assert corridas.vista_corrida(alm, cid)["items"][0]["apu_codigo"] is None

    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")

    previa = corridas.rebuscar(alm, cid)
    assert previa["escaneadas"] == 1
    assert len(previa["propuestas"]) == 1
    p = previa["propuestas"][0]
    assert p["seq"] == 0
    assert p["apu_actual"] is None
    assert p["apu_propuesto"]["codigo"] == "A9"
    assert p["sin_apu"] is True                      # el frontend la marca por defecto
    assert p["status"] == "auto"
    assert p["costo_unitario"] == 2.0 * 350000.0     # ya viene costeada
    assert p["margen_unitario"] == 900000.0 - 700000.0


def test_rebuscar_no_escribe_nada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    # Los candidatos de ANTES, no una lista vacía: el armado nunca deja la lista
    # vacía — `_full_scan` guarda todo lo que puntúe > 0, y `SequenceMatcher` da > 0
    # para casi cualquier par de textos. La fila nace con un candidato basura de 0,09.
    # Lo que se prueba acá es que la previa no los TOCA: refrescarlos es del aplicar.
    antes = alm.corridas.get_items(cid)[0].candidatos
    corridas.rebuscar(alm, cid)
    fila = alm.corridas.get_items(cid)[0]
    assert fila.apu_codigo is None                   # la previa propone, no aplica
    assert fila.candidatos == antes
    assert "A9" not in [c["apu_codigo"] for c in fila.candidatos]


def test_rebuscar_no_toca_las_confirmadas(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.confirmar_item(alm, cid, 0, apu_codigo="A1")
    _agregar_apu(alm, "A9", "Concreto clase D")      # gemelo con el mismo nombre
    previa = corridas.rebuscar(alm, cid)
    assert previa["escaneadas"] == 0
    assert previa["propuestas"] == []


def test_rebuscar_no_propone_lo_que_la_fila_ya_tiene(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    previa = corridas.rebuscar(alm, cid)             # sin crear nada nuevo
    assert previa["escaneadas"] == 1
    assert previa["propuestas"] == []


def test_rebuscar_bloqueado_si_congelada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.rebuscar(alm, cid)


def test_rebuscar_bloqueado_si_el_plan_esta_a_medias(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    alm.corridas.set_estado(cid, "armado_detenido")
    with pytest.raises(ValueError, match="por armar"):
        corridas.rebuscar(alm, cid)


def test_rebuscar_corrida_inexistente(tmp_path):
    assert corridas.rebuscar(_almacen(tmp_path), 999) is None
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_servicio_rebuscar.py -q`
Expected: FAIL con `AttributeError: module 'apu_tool.servicio.corridas' has no attribute 'rebuscar'`

- [ ] **Step 3: Implementar**

En `apu_tool/servicio/corridas.py`, después de `confirmar_item` (~línea 1007). El
módulo ya importa `Assembler`, `ApuAdvisor`, `MatchStatus`, `PricingEngine` y
`_estructura`; agregar arriba el import del matcher:

```python
from apu_tool.dominio.matching import Matcher
```

y las funciones:

```python
def _propuestas_rebusqueda(alm: Almacen, meta, rows):
    """Re-corre el matcher del armado sobre las filas NO confirmadas y devuelve
    `(propuestas, candidatos_frescos, escaneadas)`.

    `propuestas` es [(fila, ensamble propuesto ya costeado)]: solo las filas cuyo APU
    cambiaría. `candidatos_frescos` es {seq: [candidato…]} de TODAS las escaneadas (lo
    usa `aplicar_rebusqueda` para refrescar la lista que se ve al desplegar una fila).

    Es el camino ÚNICO: `rebuscar` lo muestra y `aplicar_rebusqueda` lo recalcula y
    escribe, así que la previa y lo que se aplica no se pueden separar con el tiempo.

    Dos fases a propósito. La primera solo matchea (0.2 ms por fila con
    `escaneo_completo=False`); la segunda costea, que es lo caro, y corre solo sobre
    las pocas filas que cambiarían. Costear las 1939 sería el armado otra vez.
    """
    indice = alm.apus.apu_index()
    matcher = Matcher(indice)
    codigos = {c for c, _n, _s in indice}
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id)

    # Fase 1: matchear y pre-filtrar por (código, turno). El turno definitivo lo
    # decide `_build` (puede caer a otro si el APU no existe en el del ítem), así que
    # esta comparación es solo un tamiz: el filtro de verdad va después de costear.
    pendientes = []
    candidatos: dict[int, list[dict]] = {}
    escaneadas = 0
    for r in rows:
        if r.status == MatchStatus.CONFIRMED.value:
            continue          # lo resolvió una persona; el re-match no lo pisa
        escaneadas += 1
        result = matcher.match(r.item, escaneo_completo=False)
        candidatos[r.seq] = [{"apu_codigo": c.apu_codigo, "apu_nombre": c.apu_nombre,
                              "score": c.score, "motivo": c.motivo}
                             for c in result.candidatos]
        # Misma regla que `assemble_item`: el código del presupuesto manda sobre el
        # matcher. Una sola regla, no dos que se puedan separar.
        if r.item.codigo_sugerido and r.item.codigo_sugerido in codigos:
            propuesto = r.item.codigo_sugerido
        elif result.status == MatchStatus.AUTO and result.elegido:
            propuesto = result.elegido.apu_codigo
        elif result.status == MatchStatus.REVIEW and result.candidatos:
            propuesto = result.candidatos[0].apu_codigo
        else:
            continue          # nada asignable: la fila se queda como está
        if (propuesto, r.item.shift) == (r.apu_codigo, r.shift):
            continue
        pendientes.append((r, result, propuesto))

    # Fase 2: costear solo las candidatas, con el motor compartido y precarga en lote
    # (el patrón que bajó 540 round-trips a 2 al abrir una corrida).
    assembler.pricing.precargar((cod, r.item.shift) for r, _res, cod in pendientes)
    propuestas = []
    for r, result, _cod in pendientes:
        ens = assembler.assemble_item(r.item, result)
        if (ens.apu_codigo, ens.shift) == (r.apu_codigo, r.shift):
            continue          # el turno cayó al mismo lugar: no cambia nada
        if not ens.apu_codigo:
            continue          # `assemble_item` no encontró nada: no se propone vacío
        propuestas.append((r, ens))
    return propuestas, candidatos, escaneadas


def _vista_propuesta(row: CorridaItemRow, ens: AssembledApu) -> dict:
    """Una línea de la vista previa. El costo y el margen los calcula el backend:
    el frontend no suma plata."""
    return {
        "seq": row.seq, "item": row.item.item, "descripcion": row.item.descripcion,
        "unidad": ens.unidad, "cantidad": row.item.cantidad,
        "apu_actual": ({"codigo": row.apu_codigo, "nombre": row.apu_nombre}
                       if row.apu_codigo else None),
        "apu_propuesto": {"codigo": ens.apu_codigo, "nombre": ens.apu_nombre,
                          "turno": ens.shift},
        "score": round(ens.confianza, 4), "status": ens.status.value,
        "explicacion": ens.explicacion,
        "precio_contractual": row.item.precio_contractual,
        "costo_unitario": ens.costo_unitario,
        "margen_unitario": ens.margen_unitario, "margen_pct": ens.margen_pct,
        # Se marcan solas en la previa: están en $0 y traban el cuadro, así que
        # cualquier APU es mejor que nada. Lo decide el backend, no el frontend.
        "sin_apu": row.apu_codigo is None,
    }


def _exigir_rebuscable(alm: Almacen, corrida_id: int):
    """Los candados compartidos por `rebuscar` y `aplicar_rebusqueda`. Devuelve la
    meta, o None si la corrida no existe."""
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    if _plan_a_medias(meta):
        # Mientras el armador no termine, el espacio de seq es suyo y las filas que
        # faltan no existen: re-buscar ahora mira media corrida.
        raise ValueError(_MSG_PLAN_A_MEDIAS.format(accion="volver a buscar APU de"))
    return meta


def rebuscar(alm: Almacen, corrida_id: int) -> Optional[dict]:
    """Qué cambiaría si se volviera a matchear la corrida contra la biblioteca de hoy.

    NO escribe nada: propone. Devuelve None si la corrida no existe.
    """
    meta = _exigir_rebuscable(alm, corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    propuestas, _candidatos, escaneadas = _propuestas_rebusqueda(alm, meta, rows)
    return {
        "corrida_id": corrida_id,
        "escaneadas": escaneadas,
        "propuestas": [_vista_propuesta(r, e) for r, e in propuestas],
    }
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_servicio_rebuscar.py -q`
Expected: PASS, 7 tests.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_rebuscar.py
git commit -m "feat(corridas): rebuscar propone el re-match contra la biblioteca de hoy

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 4: `aplicar_rebusqueda()` — escribir solo lo marcado

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (después de `rebuscar`)
- Test: `tests/test_servicio_rebuscar.py`

- [ ] **Step 1: Escribir los tests que fallan**

Agregar a `tests/test_servicio_rebuscar.py`:

```python
def test_aplicar_asigna_solo_los_seq_marcados(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx",
        [_item("Pantalla acustica modular en aluminio", "1"),
         _item("Barrera vegetal perimetral en guadua", "2")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    _agregar_apu(alm, "A8", "Barrera vegetal perimetral en guadua", rendimiento=3.0)

    vista = corridas.aplicar_rebusqueda(alm, cid, [0])
    filas = {f["seq"]: f for f in vista["items"]}
    assert filas[0]["apu_codigo"] == "A9"
    assert filas[0]["costo_unitario"] == 2.0 * 350000.0   # recosteada
    assert filas[1]["apu_codigo"] is None                 # no se marcó: intacta
    assert vista["rebusqueda"]["aplicadas"] == [0]
    assert vista["rebusqueda"]["salteadas"] == []


def test_aplicar_conserva_el_nivel_de_parecido_no_confirma(tmp_path):
    """Aprobar la asignación no es auditar la fila: un match dudoso entra `review`
    y sigue contando en «por revisar»."""
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    corridas.aplicar_rebusqueda(alm, cid, [0])
    fila = alm.corridas.get_items(cid)[0]
    assert fila.status == "auto"            # 100% de parecido, no "confirmed"
    assert fila.confianza == 1.0
    assert "Coincidencia directa" in fila.explicacion


def test_aplicar_saltea_lo_que_cambio_desde_la_previa(tmp_path):
    """La previa de hace cinco minutos no manda sobre la fila de ahora: el servidor
    recalcula y solo aplica lo que sigue vigente."""
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    corridas.rebuscar(alm, cid)                     # el usuario ve la propuesta…
    corridas.confirmar_item(alm, cid, 0, apu_codigo="A1")   # …y otro confirma la fila
    vista = corridas.aplicar_rebusqueda(alm, cid, [0])
    assert vista["items"][0]["apu_codigo"] == "A1"          # no la pisó
    assert vista["rebusqueda"]["aplicadas"] == []
    assert vista["rebusqueda"]["salteadas"] == [0]


def test_aplicar_refresca_los_candidatos_de_las_escaneadas(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(
        alm, "lic.xlsx", [_item("Pantalla acustica modular en aluminio")],
        "DIURNO", use_ai=False)
    # Ojo: el armado NO deja la lista vacía (`_full_scan` guarda todo lo que puntúe
    # > 0), así que la fila nace con un candidato basura. Lo que se prueba es que
    # después del aplicar la lista es la de hoy, con el APU nuevo adentro.
    assert "A9" not in [c["apu_codigo"]
                        for c in alm.corridas.get_items(cid)[0].candidatos]
    _agregar_apu(alm, "A9", "Pantalla acustica modular en aluminio")
    corridas.aplicar_rebusqueda(alm, cid, [])       # sin marcar nada
    fila = alm.corridas.get_items(cid)[0]
    assert fila.apu_codigo is None                  # no se asignó nada
    assert [c["apu_codigo"] for c in fila.candidatos] == ["A9"]


def test_aplicar_no_pisa_los_candidatos_con_una_lista_vacia(tmp_path):
    """Una lista fresca vacía es «no encontré nada», no «olvidá lo que sabías»."""
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    alm.corridas.set_candidatos(cid, {0: [{"apu_codigo": "A1", "apu_nombre": "x",
                                           "score": 0.9, "motivo": ""}]})
    alm.apus.borrar_apu("A1", "DIURNO")
    corridas.aplicar_rebusqueda(alm, cid, [])
    assert alm.corridas.get_items(cid)[0].candidatos[0]["apu_codigo"] == "A1"


def test_aplicar_bloqueado_si_congelada(tmp_path):
    alm = _almacen(tmp_path)
    cid = corridas.construir_corrida(alm, "lic.xlsx", [_item("Concreto clase D")],
                                     "DIURNO", use_ai=False)
    corridas.congelar(alm, cid)
    with pytest.raises(corridas.CorridaCongelada):
        corridas.aplicar_rebusqueda(alm, cid, [0])


def test_aplicar_corrida_inexistente(tmp_path):
    assert corridas.aplicar_rebusqueda(_almacen(tmp_path), 999, [0]) is None
```

**Nota para quien implemente:** `test_aplicar_no_pisa_los_candidatos_con_una_lista_vacia`
usa `alm.apus.borrar_apu("A1", "DIURNO")`. Verificá el nombre real del método con
`grep -n "def borrar_apu" apu_tool/datos/apus_db.py`; si no existe, dejá la biblioteca
vacía creando el almacén sin APUs y armando la corrida antes de insertarlos.

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_servicio_rebuscar.py -q -k aplicar`
Expected: FAIL con `AttributeError: … has no attribute 'aplicar_rebusqueda'`

- [ ] **Step 3: Implementar**

En `apu_tool/servicio/corridas.py`, después de `rebuscar`:

```python
def aplicar_rebusqueda(alm: Almacen, corrida_id: int,
                       seqs: Iterable[int]) -> Optional[dict]:
    """Aplica la re-búsqueda a los `seqs` marcados. Devuelve la vista de la corrida
    con `rebusqueda: {aplicadas, salteadas}`, o None si la corrida no existe.

    RECALCULA la propuesta acá adentro en vez de creerle al cliente: entre que se
    mostró la previa y se apretó Aplicar pueden haber pasado minutos y otro usuario
    puede haber reasignado la fila. Los seq cuya propuesta ya no está vigente se
    saltean y se informan. Es el mismo candado que `apu_evaluado` en la revisión.

    Escribe con `actualizar_eleccion` y NO con `confirmar_items`: ese camino pasa por
    `reassemble_with_choice`, que pisa `confianza` con 1.0 y `explicacion` con
    "Confirmado por el usuario". La fila tiene que quedar con el parecido y el motivo
    que dio el matcher, para que una asignación dudosa siga contando en «por revisar».
    """
    meta = _exigir_rebuscable(alm, corrida_id)
    if meta is None:
        return None
    rows = alm.corridas.get_items(corrida_id)
    propuestas, candidatos, _escaneadas = _propuestas_rebusqueda(alm, meta, rows)
    vigentes = {r.seq: (r, e) for r, e in propuestas}
    aplicadas, salteadas = [], []
    for seq in dict.fromkeys(seqs):          # sin repetidos, en el orden que llegaron
        par = vigentes.get(seq)
        if par is None:
            salteadas.append(seq)
            continue
        _row, ens = par
        alm.corridas.actualizar_eleccion(
            corrida_id, seq, status=ens.status.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift,
            origen=ens.origen, confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes))
        aplicadas.append(seq)
    # Candidatos frescos: solo donde la lista cambió de verdad y no quedó vacía. Una
    # lista vacía es "no encontré nada", no "olvidá lo que sabías".
    previos = {r.seq: r.candidatos for r in rows}
    cambiados = {seq: c for seq, c in candidatos.items()
                 if c and c != previos.get(seq)}
    if cambiados:
        alm.corridas.set_candidatos(corrida_id, cambiados)
    vista = vista_corrida(alm, corrida_id)
    vista["rebusqueda"] = {"aplicadas": aplicadas, "salteadas": salteadas}
    return vista
```

- [ ] **Step 4: Correr los tests**

Run: `python -m pytest tests/test_servicio_rebuscar.py -q`
Expected: PASS, 14 tests.

- [ ] **Step 5: Correr la suite de corridas entera (no romper nada)**

Run: `python -m pytest tests/test_servicio_corridas.py tests/test_corridas_contrato.py tests/test_armador.py -q`
Expected: PASS.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_servicio_rebuscar.py
git commit -m "feat(corridas): aplicar_rebusqueda escribe solo lo marcado y lo vigente

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 5: los dos endpoints

**Files:**
- Modify: `apu_tool/servicio/esquemas.py:56` (después de `IgualarCostoIn`)
- Modify: `apu_tool/servicio/rutas.py:439` (después de `confirmar_lote`)
- Test: `tests/test_api_rebuscar.py` (crear)

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_api_rebuscar.py` (mismo estilo que `tests/test_api_corridas.py`:
helpers, no fixtures de pytest):

```python
# tests/test_api_rebuscar.py
"""Contrato HTTP de volver a buscar APU."""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _cliente(tmp_path):
    """Almacén con un APU (A1) y una corrida de una línea que NO matchea con nada."""
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "Concreto 3000 PSI", "M3",
                                       "CONCRETOS", 350000.0, "COSTO INTERNO")])
    alm.apus.insert_apus([Apu("A1", "Concreto clase D", "M3", "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A1", "DIURNO", "100",
                               "Concreto 3000 PSI", "M3", 1.0, 350000.0)])
    item = LicitacionItem(item="1", descripcion="Pantalla acustica modular en aluminio",
                          unidad="M2", cantidad=10.0, precio_contractual=900000.0,
                          shift="DIURNO")
    cid = svc.construir_corrida(alm, "lic.xlsx", [item], "DIURNO", use_ai=False)
    return cliente(create_app(almacen=alm), rol="admin"), alm, cid


def _apu_nuevo(alm):
    """El APU que aparece DESPUÉS del armado: es lo que la corrida no puede ver."""
    alm.apus.insert_apus([Apu("A9", "Pantalla acustica modular en aluminio", "M2",
                              "DIURNO", "ESTR")])
    alm.apus.insert_components([ApuComponent("A9", "DIURNO", "100",
                               "Concreto 3000 PSI", "M2", 2.0, 350000.0)])


def test_rebuscar_devuelve_la_previa_sin_escribir(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    _apu_nuevo(alm)
    r = cli.post(f"/api/corridas/{cid}/rebuscar")
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["escaneadas"] == 1
    assert cuerpo["propuestas"][0]["apu_propuesto"]["codigo"] == "A9"
    assert cuerpo["propuestas"][0]["sin_apu"] is True
    assert alm.corridas.get_items(cid)[0].apu_codigo is None      # no escribió


def test_aplicar_devuelve_la_corrida_recosteada(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    _apu_nuevo(alm)
    r = cli.post(f"/api/corridas/{cid}/rebuscar/aplicar", json={"seqs": [0]})
    assert r.status_code == 200
    cuerpo = r.json()
    assert cuerpo["items"][0]["apu_codigo"] == "A9"
    assert cuerpo["items"][0]["costo_unitario"] == 2.0 * 350000.0
    assert cuerpo["rebusqueda"]["aplicadas"] == [0]
    assert cuerpo["rebusqueda"]["salteadas"] == []


def test_rebuscar_congelada_da_409(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/rebuscar")
    assert r.status_code == 409
    assert "congelada" in r.json()["detail"]


def test_rebuscar_corrida_inexistente_da_404(tmp_path):
    cli, _alm, _cid = _cliente(tmp_path)
    assert cli.post("/api/corridas/999/rebuscar").status_code == 404


def test_rebuscar_plan_a_medias_da_400(tmp_path):
    cli, alm, cid = _cliente(tmp_path)
    alm.corridas.set_estado(cid, "armado_detenido")
    r = cli.post(f"/api/corridas/{cid}/rebuscar")
    assert r.status_code == 400
    assert "por armar" in r.json()["detail"]
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `python -m pytest tests/test_api_rebuscar.py -q`
Expected: FAIL con 404 en todas (la ruta no existe).

- [ ] **Step 3: Implementar el DTO**

En `apu_tool/servicio/esquemas.py`, después de `IgualarCostoIn`:

```python
class RebuscarAplicarIn(BaseModel):
    """Los seq que el usuario marcó en la vista previa de volver a buscar APU."""
    seqs: list[int]
```

- [ ] **Step 4: Implementar las rutas**

En `apu_tool/servicio/rutas.py`, después de `confirmar_lote` (importando
`RebuscarAplicarIn` donde se importan los demás esquemas):

```python
@router.post("/corridas/{cid}/rebuscar")
def rebuscar(cid: int, alm: Almacen = Depends(get_almacen),
             _: object = Depends(requiere_rol("consulta"))):
    """Qué cambiaría si se volviera a matchear la corrida contra la biblioteca de hoy.
    NO escribe: propone. Rol `consulta`, el mismo que `confirmar-lote`, porque es la
    misma operación (asignar un APU que ya existe); no declara dinero de la nada como
    `igualar-costo`."""
    try:
        v = svc.rebuscar(alm, cid)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para volver "
                                   "a buscar APU.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v


@router.post("/corridas/{cid}/rebuscar/aplicar")
def rebuscar_aplicar(cid: int, body: RebuscarAplicarIn,
                     alm: Almacen = Depends(get_almacen),
                     _: object = Depends(requiere_rol("consulta"))):
    try:
        v = svc.aplicar_rebusqueda(alm, cid, body.seqs)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para volver "
                                   "a buscar APU.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

- [ ] **Step 5: Correr los tests**

Run: `python -m pytest tests/test_api_rebuscar.py -q`
Expected: PASS, 5 tests.

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_rebuscar.py
git commit -m "feat(api): endpoints de volver a buscar APU

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 6: cliente HTTP y tipos del frontend

**Files:**
- Modify: `web/src/lib/tipos.ts`
- Modify: `web/src/api/corridas.ts`
- Test: `web/src/api/corridas.rebuscar.test.ts` (crear)

- [ ] **Step 1: Escribir el test que falla**

Copiá el estilo de mock de `web/src/api/corridas.estados.test.ts`. Crear
`web/src/api/corridas.rebuscar.test.ts`:

```ts
import { describe, expect, it, vi, beforeEach } from "vitest";
import { rebuscarApus, aplicarRebusqueda } from "./corridas";

// Mockeá `./client` igual que lo hace corridas.estados.test.ts.
vi.mock("./client", () => ({
  apiPost: vi.fn(async (ruta: string, cuerpo?: unknown) => ({ ruta, cuerpo })),
  apiGet: vi.fn(),
}));

import { apiPost } from "./client";

beforeEach(() => vi.clearAllMocks());

describe("volver a buscar APU", () => {
  it("pide la previa sin cuerpo", async () => {
    await rebuscarApus(7);
    expect(apiPost).toHaveBeenCalledWith("/corridas/7/rebuscar", {});
  });

  it("aplica solo los seq marcados", async () => {
    await aplicarRebusqueda(7, [0, 3]);
    expect(apiPost).toHaveBeenCalledWith("/corridas/7/rebuscar/aplicar",
                                         { seqs: [0, 3] });
  });
});
```

- [ ] **Step 2: Correr y verificar que falla**

Run: `cd web && npx vitest run src/api/corridas.rebuscar.test.ts`
Expected: FAIL — `rebuscarApus` no existe.

- [ ] **Step 3: Implementar los tipos**

En `web/src/lib/tipos.ts` (junto a los demás tipos de corrida):

```ts
/** Una línea de la vista previa de "volver a buscar APU". El costo y el margen
 *  vienen calculados del backend: el frontend no suma plata. */
export interface PropuestaRebusqueda {
  seq: number;
  item: string;
  descripcion: string;
  unidad: string;
  cantidad: number;
  apu_actual: { codigo: string; nombre: string } | null;
  apu_propuesto: { codigo: string; nombre: string; turno: string };
  score: number;
  status: string;
  explicacion: string;
  precio_contractual: number;
  costo_unitario: number;
  margen_unitario: number;
  margen_pct: number;
  /** Hoy está en $0: se marca sola en la previa. Lo decide el backend. */
  sin_apu: boolean;
}

export interface RebusquedaPrevia {
  corrida_id: number;
  escaneadas: number;
  propuestas: PropuestaRebusqueda[];
}
```

Y en la interfaz `CorridaDetalle`, agregar el campo opcional que devuelve el aplicar:

```ts
  /** Solo en la respuesta de aplicar una re-búsqueda. */
  rebusqueda?: { aplicadas: number[]; salteadas: number[] };
```

- [ ] **Step 4: Implementar las funciones**

En `web/src/api/corridas.ts`, después de `aplicarSugerencias` (agregando
`RebusquedaPrevia` a los imports de tipos):

```ts
/** Qué cambiaría si se volviera a matchear la corrida contra la biblioteca de hoy.
 *  NO escribe: propone. */
export function rebuscarApus(id: number): Promise<RebusquedaPrevia> {
  return apiPost<RebusquedaPrevia>(`/corridas/${id}/rebuscar`, {});
}

/** Aplica la re-búsqueda a las líneas marcadas, en un solo recosteo. El servidor
 *  recalcula la propuesta: las que ya no estén vigentes vuelven en `salteadas`. */
export function aplicarRebusqueda(
  id: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/rebuscar/aplicar`, { seqs });
}
```

- [ ] **Step 5: Correr el test**

Run: `cd web && npx vitest run src/api/corridas.rebuscar.test.ts`
Expected: PASS, 2 tests.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts web/src/api/corridas.rebuscar.test.ts
git commit -m "feat(web): cliente de volver a buscar APU

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 7: el diálogo de la vista previa

**Files:**
- Create: `web/src/components/corrida/DialogoRebuscar.tsx`
- Test: `web/src/components/corrida/DialogoRebuscar.test.tsx` (crear)

Antes de escribir: mirá `web/src/components/corrida/DialogoAgregarLineas.tsx` para el
armazón de `Dialog` y `web/src/components/insumos/DialogoImportarInsumos.tsx:312-345`
para el `alternar` con shift+clic y el `marcarTodas`. Formatea plata con
`web/src/lib/moneda.ts`.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `web/src/components/corrida/DialogoRebuscar.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DialogoRebuscar from "./DialogoRebuscar";
import type { PropuestaRebusqueda } from "@/lib/tipos";

function propuesta(over: Partial<PropuestaRebusqueda> = {}): PropuestaRebusqueda {
  return {
    seq: 0, item: "1", descripcion: "PANTALLA ACUSTICA", unidad: "M2", cantidad: 10,
    apu_actual: null,
    apu_propuesto: { codigo: "A9", nombre: "PANTALLA ACUSTICA", turno: "DIURNO" },
    score: 0.98, status: "auto", explicacion: "Coincidencia directa (98%).",
    precio_contractual: 900000, costo_unitario: 700000,
    margen_unitario: 200000, margen_pct: 22.2, sin_apu: true, ...over,
  };
}

const previa = (ps: PropuestaRebusqueda[]) => ({
  corrida_id: 1, escaneadas: ps.length + 5, propuestas: ps,
});

describe("DialogoRebuscar", () => {
  it("marca por defecto solo las filas que hoy están sin APU", () => {
    render(<DialogoRebuscar abierto previa={previa([
      propuesta(),
      propuesta({ seq: 1, sin_apu: false,
                  apu_actual: { codigo: "A1", nombre: "OTRO APU" } }),
    ])} aplicando={false} onAplicar={vi.fn()} onCerrar={vi.fn()} />);
    expect((screen.getByLabelText("Marcar línea 1") as HTMLInputElement).checked)
      .toBe(true);
    expect((screen.getByLabelText("Marcar línea 2") as HTMLInputElement).checked)
      .toBe(false);
  });

  it("aplica solo los seq marcados", () => {
    const onAplicar = vi.fn();
    render(<DialogoRebuscar abierto previa={previa([
      propuesta(),
      propuesta({ seq: 1, sin_apu: false,
                  apu_actual: { codigo: "A1", nombre: "OTRO APU" } }),
    ])} aplicando={false} onAplicar={onAplicar} onCerrar={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Marcar línea 2"));
    fireEvent.click(screen.getByRole("button", { name: /Aplicar 2/ }));
    expect(onAplicar).toHaveBeenCalledWith([0, 1]);
  });

  it("marcar todas alcanza a las que ya tienen APU", () => {
    const onAplicar = vi.fn();
    render(<DialogoRebuscar abierto previa={previa([
      propuesta({ seq: 0, sin_apu: false,
                  apu_actual: { codigo: "A1", nombre: "OTRO" } }),
      propuesta({ seq: 1, sin_apu: false,
                  apu_actual: { codigo: "A2", nombre: "OTRO" } }),
    ])} aplicando={false} onAplicar={onAplicar} onCerrar={vi.fn()} />);
    fireEvent.click(screen.getByLabelText("Marcar todas las líneas"));
    fireEvent.click(screen.getByRole("button", { name: /Aplicar 2/ }));
    expect(onAplicar).toHaveBeenCalledWith([0, 1]);
  });

  it("sin propuestas lo dice y no ofrece aplicar", () => {
    render(<DialogoRebuscar abierto previa={previa([])} aplicando={false}
                            onAplicar={vi.fn()} onCerrar={vi.fn()} />);
    expect(screen.getByText(/Ninguna actividad encontró un APU mejor/)).toBeTruthy();
    expect(screen.queryByRole("button", { name: /Aplicar/ })).toBeNull();
  });

  it("muestra el antes y el después de la fila que ya tiene APU", () => {
    render(<DialogoRebuscar abierto previa={previa([
      propuesta({ sin_apu: false, apu_actual: { codigo: "A1", nombre: "VIEJO" } }),
    ])} aplicando={false} onAplicar={vi.fn()} onCerrar={vi.fn()} />);
    expect(screen.getByText(/A1/)).toBeTruthy();
    expect(screen.getByText(/A9/)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd web && npx vitest run src/components/corrida/DialogoRebuscar.test.tsx`
Expected: FAIL — el módulo no existe.

- [ ] **Step 3: Implementar el componente**

Crear `web/src/components/corrida/DialogoRebuscar.tsx`:

```tsx
import { useEffect, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cop } from "@/lib/moneda";
import type { PropuestaRebusqueda, RebusquedaPrevia } from "@/lib/tipos";

interface Props {
  abierto: boolean;
  previa: RebusquedaPrevia;
  aplicando: boolean;
  onAplicar: (seqs: number[]) => void;
  onCerrar: () => void;
}

/** Vista previa de "volver a buscar APU": qué líneas cambiarían de APU contra la
 *  biblioteca de hoy, con el costo y el margen que quedarían. Propone; aplicar es
 *  del usuario, y solo lo que marque. */
export default function DialogoRebuscar({
  abierto, previa, aplicando, onAplicar, onCerrar,
}: Props) {
  const ps = previa.propuestas;
  // Vienen marcadas las que hoy están sin APU: están en $0 y traban el cuadro, así que
  // cualquier APU es mejor que nada. Quién es cuál lo dice el backend (`sin_apu`), no
  // una regla repetida acá.
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set());
  useEffect(() => {
    setMarcadas(new Set(ps.filter((p) => p.sin_apu).map((p) => p.seq)));
  }, [previa]);                                   // eslint-disable-line react-hooks/exhaustive-deps

  // Ancla del último clic SIN Shift, por `seq` (único en la corrida), igual que el
  // diálogo de conflictos del import.
  const anclaRef = useRef<number | null>(null);

  function alternar(idx: number, seq: number, conShift: boolean) {
    const desde = anclaRef.current === null
      ? -1
      : ps.findIndex((p) => p.seq === anclaRef.current);
    if (conShift && desde >= 0) {
      const [a, b] = desde <= idx ? [desde, idx] : [idx, desde];
      const rango = ps.slice(a, b + 1).map((p) => p.seq);
      setMarcadas((prev) => new Set([...prev, ...rango]));
      return;                                     // el ancla del rango no se mueve
    }
    anclaRef.current = seq;
    setMarcadas((prev) => {
      const s = new Set(prev);
      if (s.has(seq)) s.delete(seq); else s.add(seq);
      return s;
    });
  }

  function marcarTodas(marcar: boolean) {
    anclaRef.current = null;
    setMarcadas(marcar ? new Set(ps.map((p) => p.seq)) : new Set());
  }

  const th = "px-2 py-1 text-left font-semibold text-muted-foreground";
  const td = "px-2 py-1 align-top";

  return (
    <Dialog open={abierto} onOpenChange={(v) => { if (!v) onCerrar(); }}>
      <DialogContent className="max-w-5xl">
        <DialogHeader>
          <DialogTitle>Volver a buscar APU</DialogTitle>
        </DialogHeader>
        <p className="text-xs text-muted-foreground -mt-2">
          {ps.length} de {previa.escaneadas}{" "}
          {previa.escaneadas === 1 ? "línea revisada" : "líneas revisadas"} cambiarían
          de APU. Las confirmadas no se tocan.
        </p>

        {ps.length === 0 ? (
          <p className="py-6 text-center text-sm text-muted-foreground">
            Ninguna actividad encontró un APU mejor que el que ya tiene.
          </p>
        ) : (
          <div className="max-h-[60vh] overflow-auto rounded border border-border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className={th}>
                    <input type="checkbox" className="cursor-pointer"
                      aria-label="Marcar todas las líneas"
                      checked={marcadas.size === ps.length && ps.length > 0}
                      onChange={(e) => marcarTodas(e.target.checked)} />
                  </th>
                  <th className={th}>#</th>
                  <th className={th}>Actividad</th>
                  <th className={th}>APU actual</th>
                  <th className={th}>APU propuesto</th>
                  <th className={th}>Parecido</th>
                  <th className={`${th} text-right`}>Costo unit.</th>
                  <th className={`${th} text-right`}>Margen unit.</th>
                </tr>
              </thead>
              <tbody>
                {ps.map((p: PropuestaRebusqueda, i) => (
                  <tr key={p.seq} className="border-t border-border hover:bg-muted/40">
                    <td className={td}>
                      {/* `onChange` vacío a propósito: el que sabe del Shift es el
                          `onClick`, y React exige onChange en un input controlado. */}
                      <input type="checkbox" className="cursor-pointer"
                        aria-label={`Marcar línea ${i + 1}`}
                        checked={marcadas.has(p.seq)}
                        onChange={() => {}}
                        onMouseDown={(e) => { if (e.shiftKey) e.preventDefault(); }}
                        onClick={(e) => alternar(i, p.seq, e.shiftKey)} />
                    </td>
                    <td className={`${td} tabular-nums`}>{p.item}</td>
                    <td className={`${td} max-w-[22rem]`}>{p.descripcion}</td>
                    <td className={td}>
                      {p.apu_actual
                        ? <span>{p.apu_actual.codigo} — {p.apu_actual.nombre}</span>
                        : <span className="text-amber-700 font-semibold">— sin APU</span>}
                    </td>
                    <td className={td}>
                      {p.apu_propuesto.codigo} — {p.apu_propuesto.nombre}
                    </td>
                    <td className={`${td} tabular-nums`}>
                      {(p.score * 100).toFixed(0)}%
                      {p.status === "review" && (
                        <span className="ml-1 rounded-full bg-amber-100 px-1.5
                                         text-[10px] font-semibold text-amber-800">
                          revisar
                        </span>
                      )}
                    </td>
                    <td className={`${td} text-right tabular-nums`}>
                      {cop(p.costo_unitario)}
                    </td>
                    <td className={`${td} text-right tabular-nums ${
                      p.margen_unitario < 0 ? "text-red-600" : ""}`}>
                      {cop(p.margen_unitario)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          <Button size="sm" variant="outline" onClick={onCerrar}>Cerrar</Button>
          {ps.length > 0 && (
            <Button size="sm" disabled={marcadas.size === 0 || aplicando}
              onClick={() => onAplicar([...marcadas].sort((a, b) => a - b))}>
              {aplicando
                ? "Aplicando…"
                : `Aplicar ${marcadas.size} ${marcadas.size === 1 ? "cambio" : "cambios"}`}
            </Button>
          )}
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

(`cop` y los exports de `@/components/ui/dialog` están verificados contra el repo.)

- [ ] **Step 4: Correr los tests**

Run: `cd web && npx vitest run src/components/corrida/DialogoRebuscar.test.tsx`
Expected: PASS, 5 tests.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/corrida/DialogoRebuscar.tsx web/src/components/corrida/DialogoRebuscar.test.tsx
git commit -m "feat(web): dialogo de vista previa de volver a buscar APU

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 8: el botón en la corrida

**Files:**
- Modify: `web/src/pages/Corrida.tsx` (la barra de botones, ~línea 313)
- Test: `web/src/pages/Corrida.rebuscar.test.tsx` (crear)

- [ ] **Step 1: Escribir los tests que fallan**

Crear `web/src/pages/Corrida.rebuscar.test.tsx` (mismos mocks que `Corrida.test.tsx`):

```tsx
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { beforeEach, expect, test, vi } from "vitest";

vi.mock("react-router-dom", () => ({
  useParams: () => ({ id: "1" }),
  useNavigate: () => vi.fn(),
}));
vi.mock("sonner", () => ({
  toast: { success: vi.fn(), warning: vi.fn(), error: vi.fn() },
}));
let rol: "consulta" | "editor" | "admin" = "editor";
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol } }) }));

function fila(p: Record<string, unknown>) {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "M3", cantidad: 1,
    apu_codigo: null, apu_nombre: "(sin base — armar manual)", status: "new",
    confianza: 0, precio_contractual: 900000, costo_unitario: 0, margen_unitario: 0,
    margen_pct: 0, contractual_total: 0, costo_total: 0, margen_total: 0, ...p,
  };
}

let modo = "activa";
const CORRIDA = () => ({
  id: 1, archivo: "obra.xlsx", estado: "en_revision", modo, duracion_ms: 1000,
  ia_disponible: true, armado: null,
  items: [fila({ seq: 0, descripcion: "Pantalla acustica" })],
  totales: { contractual: 900000, costo: 0, margen: 900000, margen_pct: 1,
             n_items: 1, n_revision: 0 },
});

const PREVIA = {
  corrida_id: 1, escaneadas: 1,
  propuestas: [{
    seq: 0, item: "1", descripcion: "Pantalla acustica", unidad: "M2", cantidad: 10,
    apu_actual: null,
    apu_propuesto: { codigo: "A9", nombre: "PANTALLA ACUSTICA", turno: "DIURNO" },
    score: 0.98, status: "auto", explicacion: "Coincidencia directa (98%).",
    precio_contractual: 900000, costo_unitario: 700000, margen_unitario: 200000,
    margen_pct: 22.2, sin_apu: true,
  }],
};

const APLICADA = () => ({
  ...CORRIDA(),
  items: [fila({ seq: 0, descripcion: "Pantalla acustica", apu_codigo: "A9",
                 apu_nombre: "PANTALLA ACUSTICA", status: "auto",
                 costo_unitario: 700000 })],
  rebusqueda: { aplicadas: [0], salteadas: [] },
});

const rebuscarApus = vi.fn(async () => PREVIA);
const aplicarRebusqueda = vi.fn(async () => APLICADA());

vi.mock("@/api/corridas", () => ({
  getCorrida: vi.fn(async () => CORRIDA()),
  descargarCuadro: vi.fn(),
  congelarCorrida: vi.fn(),
  activarCorrida: vi.fn(),
  revisarCorridaStream: vi.fn(),
  aplicarSugerencias: vi.fn(),
  reanudarArmado: vi.fn(),
  rebuscarApus: (...a: unknown[]) => rebuscarApus(...(a as [])),
  aplicarRebusqueda: (...a: unknown[]) => aplicarRebusqueda(...(a as [])),
}));
vi.mock("@/api/autoria", () => ({
  listarApus: vi.fn(async () => ({ items: [], total: 0, limit: 15, offset: 0 })),
}));

beforeEach(() => { rol = "editor"; modo = "activa"; vi.clearAllMocks(); });

test("el botón pide la previa y abre el diálogo con las propuestas", async () => {
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");

  fireEvent.click(screen.getByRole("button", { name: /Volver a buscar APU/ }));

  await waitFor(() => expect(rebuscarApus).toHaveBeenCalledWith(1));
  expect(await screen.findByText(/A9/)).toBeTruthy();
  // La fila viene sin APU: se marca sola.
  expect((screen.getByLabelText("Marcar línea 1") as HTMLInputElement).checked)
    .toBe(true);
});

test("aplicar manda los seq marcados y pinta la corrida que devuelve el servidor",
  async () => {
    const { default: Corrida } = await import("./Corrida");
    render(<Corrida />);
    await screen.findByText("Pantalla acustica");
    fireEvent.click(screen.getByRole("button", { name: /Volver a buscar APU/ }));
    await screen.findByText(/A9/);

    fireEvent.click(screen.getByRole("button", { name: /Aplicar 1 cambio/ }));

    await waitFor(() => expect(aplicarRebusqueda).toHaveBeenCalledWith(1, [0]));
    // La tabla se actualiza con la respuesta, sin volver a pedir la corrida.
    expect(await screen.findByText("A9")).toBeTruthy();
  });

test("en una corrida congelada el botón no está", async () => {
  modo = "congelada";
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  expect(screen.queryByRole("button", { name: /Volver a buscar APU/ })).toBeNull();
});

test("sin rol editor el botón no está", async () => {
  rol = "consulta";
  const { default: Corrida } = await import("./Corrida");
  render(<Corrida />);
  await screen.findByText("Pantalla acustica");
  expect(screen.queryByRole("button", { name: /Volver a buscar APU/ })).toBeNull();
});
```

- [ ] **Step 2: Correr y verificar que fallan**

Run: `cd web && npx vitest run src/pages/Corrida.rebuscar.test.tsx`
Expected: FAIL — no existe el botón.

- [ ] **Step 3: Implementar**

En `web/src/pages/Corrida.tsx`:

```tsx
const [previaRebusqueda, setPreviaRebusqueda] = useState<RebusquedaPrevia | null>(null);
const [rebuscando, setRebuscando] = useState(false);
const [aplicandoRebusqueda, setAplicandoRebusqueda] = useState(false);

async function volverABuscar() {
  setRebuscando(true);
  try {
    setPreviaRebusqueda(await rebuscarApus(data.id));
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "No se pudo volver a buscar.");
  } finally {
    setRebuscando(false);
  }
}

async function aplicarRebusquedaMarcada(seqs: number[]) {
  setAplicandoRebusqueda(true);
  try {
    const actualizada = await aplicarRebusqueda(data.id, seqs);
    setCorrida(actualizada);                  // el estado de la página; `data` es su alias
    setPreviaRebusqueda(null);
    const n = actualizada.rebusqueda?.aplicadas.length ?? 0;
    toast.success(n === 1 ? "1 línea reasignada" : `${n} líneas reasignadas`);
    const salteadas = actualizada.rebusqueda?.salteadas ?? [];
    if (salteadas.length > 0) {
      toast.warning(
        `${salteadas.length} línea(s) cambiaron mientras mirabas la propuesta y se `
        + "saltearon. Volvé a buscar para verlas de nuevo.",
      );
    }
  } catch (e) {
    toast.error(e instanceof Error ? e.message : "No se pudo aplicar.");
  } finally {
    setAplicandoRebusqueda(false);
  }
}
```

El botón, junto al de "Revisar … con IA" (misma guarda `puedeEditar`, más
`!esActivar` para que no salga en una congelada, y fuera mientras se arma):

```tsx
{puedeEditar && !esActivar && data.estado !== "armando" && (
  <Button size="sm" variant="outline" disabled={rebuscando}
    title="Vuelve a buscar APU para las líneas que no confirmaste, contra la
           biblioteca de hoy. Te muestra qué cambiaría antes de aplicar."
    onClick={volverABuscar}>
    {rebuscando ? "Buscando…" : "Volver a buscar APU"}
  </Button>
)}
```

Y el diálogo, junto a los demás del final del componente:

```tsx
{previaRebusqueda && (
  <DialogoRebuscar
    abierto
    previa={previaRebusqueda}
    aplicando={aplicandoRebusqueda}
    onAplicar={aplicarRebusquedaMarcada}
    onCerrar={() => setPreviaRebusqueda(null)}
  />
)}
```

**Ojo:** `esActivar` en esta página es `true` cuando la corrida está **congelada** (el
botón dice "Activar"). Verificá el valor antes de usarlo leyendo
`web/src/pages/Corrida.tsx:296-307`.

- [ ] **Step 4: Correr los tests del frontend**

Run: `cd web && npx vitest run src/pages/Corrida.rebuscar.test.tsx src/pages/Corrida.test.tsx`
Expected: PASS.

- [ ] **Step 5: Verificar que el build de verdad compila**

Run: `cd web && npm run build`
Expected: build OK. (`tsc -b`, no `tsc --noEmit`: es la lección de la rama de
nombre/alias de corridas.)

- [ ] **Step 6: Commit**

```bash
git add web/src/pages/Corrida.tsx web/src/pages/Corrida.rebuscar.test.tsx
git commit -m "feat(web): boton de volver a buscar APU en la corrida

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

---

## Task 9: documentar y verificar todo junto

**Files:**
- Modify: `CLAUDE.md` (sección **Datos**, después de "Costo puesto a mano")

- [ ] **Step 1: Documentar la feature en CLAUDE.md**

Agregar a la sección **Datos**:

```markdown
- **Volver a buscar APU.** El match corre una vez, al armar; los APUs creados después
  son invisibles para la corrida (costear sí sigue la biblioteca, matchear no). El botón
  **Volver a buscar APU** (`POST /api/corridas/{id}/rebuscar`, rol `consulta`) re-corre
  el matcher del armado sobre las filas que NO están `confirmed`, muestra qué cambiaría
  con costo y margen, y `.../rebuscar/aplicar` escribe solo los `seq` marcados. Usa
  `Matcher.candidates(..., escaneo_completo=False)`: la vía rápida del índice invertido
  es **exacta para asignar** —`similarity` es `0.4·secuencia + 0.6·jaccard`, así que un
  APU sin tokens en común tope en 0,40 y el mínimo para asignar es 0,55—, y baja el costo
  de 42 ms a 0,2 ms por fila, que es lo que hace que el botón sea síncrono sobre 1939
  líneas. Aplicar **recalcula la propuesta en el servidor** y saltea lo que cambió desde
  la previa (mismo candado que `apu_evaluado` en la revisión: el cliente no dicta qué APU
  se escribe). La fila queda con el status del matcher (`auto`/`review`), **no**
  `confirmed`: aprobar la asignación no es auditar la fila, y por eso escribe con
  `actualizar_eleccion` y no con `confirmar_items`, que pisaría la confianza con 1.0.
```

Y a la sección **No hacer**:

```markdown
- No hagas que volver a buscar APU toque una fila `confirmed`, ni le agregues un
  "forzar". Una persona resolvió esa fila; el re-match no la pisa. Las de `costo_manual`
  caen ahí solas (`set_costo_manual` las deja `confirmed`), y eso es el candado, no una
  casualidad: si algún día el costo a mano dejara de confirmar la fila, un re-match se
  lo llevaría puesto.
- No refresques candidatos fila por fila. `set_candidatos` es por lote a propósito: crear
  un APU puede cambiar la lista de cientos de filas, y contra Supabase eso es el N+1 que
  este repo ya pagó una vez.
```

- [ ] **Step 2: Correr la suite entera de Python**

Run: `python -m pytest tests/ -q`
Expected: todo verde. Si algo falla, arreglalo antes de seguir — no se reporta "listo"
con la suite roja.

- [ ] **Step 3: Correr la suite entera del frontend**

Run: `cd web && npx vitest run`
Expected: todo verde.

- [ ] **Step 4: Build del frontend**

Run: `cd web && npm run build`
Expected: OK.

- [ ] **Step 5: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: volver a buscar APU en una corrida activa

Co-Authored-By: Claude Opus 5 (1M context) <noreply@anthropic.com>"
```

- [ ] **Step 6: Smoke en el navegador (NO se salta)**

Levantá la app local (receta en la memoria "Levantar la web en local": hacen falta
`SUPABASE_URL` y `APU_ADMIN_EMAILS`, si no todo `/api` rebota con 401) y comprobá a mano:

1. Abrí una corrida activa con al menos una línea sin APU.
2. Creá un APU desde la pestaña APUs con un nombre casi igual a esa actividad.
3. Volvé a la corrida → **Volver a buscar APU** → la línea aparece marcada, con el costo.
4. Aplicar → la fila queda con el APU, costeada, y el badge dice `auto` o `revisar`
   (no `confirmado`).
5. Congelá la corrida → el botón desaparece.

En cambios de UI el navegador va ANTES del push: es la lección de la rama del
`DialogoTexto`, que llegó a producción con 145 tests verdes y un modal que se cerraba
solo.

---

## Fuera de alcance (a propósito)

- Que corra solo al crear un APU. El usuario aprieta.
- Otras corridas, o las congeladas.
- Filas `confirmed`.
- Persistir la previa entre recargas: volver a apretar cuesta menos de un segundo.
