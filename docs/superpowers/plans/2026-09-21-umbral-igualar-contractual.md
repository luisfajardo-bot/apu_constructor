# Umbral para igualar el costo al contractual — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Poner un techo en pesos sobre el total contractual de una línea y, con un gesto, igualar al contractual todas las actividades en $0 que caigan debajo — más el reverso que hoy no existe, quitar el costo puesto a mano.

**Architecture:** La previa la calcula el frontend sobre los ítems que ya tiene en memoria (función pura en `web/src/lib/umbralCosto.ts`); el aplicar lo manda un endpoint nuevo que **recalcula la candidatura en el servidor** y delega la escritura en `igualar_costo_al_contractual`, que ya existe. No hay estado ni columna nueva: se escribe el `costo_manual` de siempre. El deshacer es un método nuevo del repositorio (`limpiar_costo_manual`) en los dos backends.

**Tech Stack:** Python 3 + FastAPI + SQLite/Postgres (psycopg) en el backend; React 19 + TypeScript + Vite + Tailwind + shadcn/ui en el frontend. Pruebas con pytest y vitest (+ @testing-library/react).

**Spec:** `docs/superpowers/specs/2026-09-21-umbral-igualar-contractual-design.md`

**Rama:** `feat/umbral-igualar-contractual` (ya creada, con la spec commiteada en `af27be7`).

---

## Estructura de archivos

| Archivo | Responsabilidad | Tarea |
|---|---|---|
| `apu_tool/datos/repositorio.py` | Contrato: `limpiar_costo_manual` | 1 |
| `apu_tool/datos/corridas_db.py` | Implementación SQLite | 1 |
| `apu_tool/datos/pg/corridas_pg.py` | Implementación Postgres | 1 |
| `tests/test_corridas_contrato.py` | La misma batería contra los dos backends | 1 |
| `apu_tool/servicio/corridas.py` | `quitar_costo_manual`, `igualar_por_umbral`, `_candidata_umbral` | 2, 3 |
| `tests/test_costo_manual.py` | Pruebas de servicio de las dos funciones | 2, 3 |
| `tests/test_auditoria_servicios_corridas_usuarios.py` | El umbral queda en la auditoría | 3 |
| `apu_tool/dominio/privacy.py` | `umbral_contractual` en `_FORBIDDEN_KEYS` | 4 |
| `apu_tool/servicio/esquemas.py` | DTOs de los dos endpoints | 4 |
| `apu_tool/servicio/rutas.py` | Los dos endpoints | 4 |
| `tests/test_api_corridas.py` | Códigos y roles de los endpoints | 4 |
| `web/src/lib/umbralCosto.ts` | El cálculo de la previa, puro | 5 |
| `web/src/lib/umbralCosto.test.ts` | Sus pruebas | 5 |
| `web/src/components/corrida/DialogoUmbralCosto.tsx` | El diálogo | 6 |
| `web/src/components/corrida/DialogoUmbralCosto.test.tsx` | Sus pruebas | 6 |
| `web/src/api/corridas.ts` + `web/src/lib/tipos.ts` | Las dos llamadas y sus tipos | 7 |
| `web/src/pages/Corrida.tsx` | Botón, estado y cableado del diálogo | 7 |
| `web/src/components/corrida/TablaItems.tsx` | Botón `Quitar costo a mano` | 8 |
| `CLAUDE.md` | Documentar el umbral y el deshacer | 9 |

---

### Task 1: `limpiar_costo_manual` en el contrato y en los dos backends

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (después de `set_costo_manual`, ~línea 269)
- Modify: `apu_tool/datos/corridas_db.py` (después de `set_costo_manual`, ~línea 365)
- Modify: `apu_tool/datos/pg/corridas_pg.py` (después de `set_costo_manual`, ~línea 264)
- Test: `tests/test_corridas_contrato.py` (al final del archivo)

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregá al final de `tests/test_corridas_contrato.py`. Esta batería corre contra SQLite siempre y contra Postgres cuando hay `TEST_DATABASE_URL`: es el archivo donde una implementación de `CorridasPg` que se olvida de un detalle explota.

```python
def test_limpiar_costo_manual_devuelve_la_fila_al_costeo(repo):
    """El reverso de set_costo_manual. Sin APU, la fila vuelve a `new`: es
    exactamente lo que era antes (así la deja `assemble.py` cuando no hay match)."""
    cid = _corrida_con(repo, _item(0, 1500.0), _item(1, 900.0))
    repo.set_costo_manual(cid, {0: 1500.0, 1: 900.0})
    repo.limpiar_costo_manual(cid, [0])
    filas = {r.seq: r for r in repo.get_items(cid)}
    assert filas[0].costo_manual is None
    assert filas[0].status == "new"
    assert filas[1].costo_manual == 900.0      # la que no se pidió no se toca
    assert filas[1].status == "confirmed"


def test_limpiar_costo_manual_con_apu_deja_la_fila_en_review(repo):
    """Con APU no se puede volver a `new` (la fila SÍ tiene match). No guardamos el
    status previo, y `review` —«mírala»— es la verdad honesta en vez de adivinar."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.actualizar_eleccion(
        cid, 0, status="auto", apu_codigo="100", apu_nombre="EXCAVACION",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0,
        explicacion="", componentes=[])
    repo.set_costo_manual(cid, {0: 1500.0})
    repo.limpiar_costo_manual(cid, [0])
    fila = repo.get_items(cid)[0]
    assert fila.costo_manual is None
    assert fila.status == "review"


def test_limpiar_costo_manual_vacio_no_escribe(repo):
    """Sin esto el test no podría fallar: hay que dejar algo que borrar."""
    cid = _corrida_con(repo, _item(0, 1500.0))
    repo.set_costo_manual(cid, {0: 1500.0})
    repo.limpiar_costo_manual(cid, [])
    fila = repo.get_items(cid)[0]
    assert fila.costo_manual == 1500.0
    assert fila.status == "confirmed"
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `python -m pytest tests/test_corridas_contrato.py -k limpiar_costo_manual -q`
Expected: 3 FAIL con `AttributeError: 'CorridasDB' object has no attribute 'limpiar_costo_manual'`

- [ ] **Step 3: Agregar el método al contrato**

En `apu_tool/datos/repositorio.py`, justo después del bloque de `set_costo_manual` (el que termina con `...` antes de `def set_plan`):

```python
    def limpiar_costo_manual(self, corrida_id: int, seqs: list[int], conn=None) -> None:
        """Borra el costo puesto a mano y devuelve la fila al costeo normal.

        Es el reverso de `set_costo_manual`, y va por lote por la misma razón: el
        umbral puede tocar cientos de filas de una. Una lista vacía no escribe nada.

        El status vuelve a `new` si la fila no tiene APU (que es exactamente lo que
        era: así la deja `assemble.py` cuando no hay match) y a `review` si lo tiene.
        No guardamos el status previo y no hace falta adivinarlo: `review` —«mírala»—
        es la verdad honesta para una fila que sí tiene match.

        NO toca `revision_json`: `set_costo_manual` ya lo había borrado y no hay
        veredicto que restaurar."""
        ...
```

- [ ] **Step 4: Implementar en SQLite**

En `apu_tool/datos/corridas_db.py`, después de `set_costo_manual`:

```python
    def limpiar_costo_manual(self, corrida_id: int, seqs: list[int], conn=None) -> None:
        """Borra el costo a mano de varias filas (contrato en repositorio.py)."""
        if not seqs:
            return
        filas = [(int(corrida_id), int(s)) for s in seqs]
        sql = ("UPDATE corrida_item SET costo_manual=NULL, "
               "status=CASE WHEN COALESCE(apu_codigo,'')='' THEN 'new' ELSE 'review' END "
               "WHERE corrida_id=? AND seq=?")
        if conn is not None:
            conn.executemany(sql, filas)
            return
        with self.connect() as c:
            c.executemany(sql, filas)
```

- [ ] **Step 5: Implementar en Postgres**

En `apu_tool/datos/pg/corridas_pg.py`, después de `set_costo_manual`:

```python
    def limpiar_costo_manual(self, corrida_id: int, seqs: list[int], conn=None) -> None:
        """Borra el costo a mano de varias filas (contrato en repositorio.py)."""
        if not seqs:
            return
        filas = [(int(corrida_id), int(s)) for s in seqs]
        sql = ("UPDATE corridas.corrida_item SET costo_manual=NULL, "
               "status=CASE WHEN COALESCE(apu_codigo,'')='' THEN 'new' ELSE 'review' END "
               "WHERE corrida_id=%s AND seq=%s")
        if conn is not None:
            with conn.cursor() as cur:
                cur.executemany(sql, filas)
            return
        with self.cx.connection() as c, c.cursor() as cur:
            cur.executemany(sql, filas)
```

- [ ] **Step 6: Correr las pruebas para verificar que pasan**

Run: `python -m pytest tests/test_corridas_contrato.py -q`
Expected: PASS (todas; con `TEST_DATABASE_URL` puesta, el doble de casos)

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/corridas_db.py apu_tool/datos/pg/corridas_pg.py tests/test_corridas_contrato.py
git commit -m "feat(corridas): limpiar_costo_manual, el reverso del costo a mano"
```

---

### Task 2: `quitar_costo_manual` en el servicio

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (después de `igualar_costo_al_contractual`, ~línea 1396)
- Test: `tests/test_costo_manual.py` (al final del archivo)

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregá al final de `tests/test_costo_manual.py`:

```python
def test_quitar_costo_manual_devuelve_la_fila_al_costeo(alm):
    """Con APU, la fila vuelve a costear desde su composición ($40.000 del APU 100)."""
    cid = _corrida(alm, contractual=92106000.0, apu="100")
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    v = svc.quitar_costo_manual(alm, cid, [0])
    assert v["quitadas"] == [0]
    fila = v["items"][0]
    assert fila["costo_manual"] is False
    assert fila["costo_unitario"] == 40000.0
    assert fila["status"] == "review"


def test_quitar_costo_manual_sin_apu_vuelve_a_trabar_el_cuadro(alm):
    """El candado tiene que volver a cerrarse: la fila está otra vez en $0 sin APU."""
    cid = _corrida(alm, contractual=1000.0)
    svc.igualar_costo_al_contractual(alm, cid, [0])
    assert svc.seqs_sin_apu(alm.corridas.get_items(cid)) == []
    svc.quitar_costo_manual(alm, cid, [0])
    filas = alm.corridas.get_items(cid)
    assert filas[0].status == "new"
    assert svc.seqs_sin_apu(filas) == [0]


def test_quitar_costo_manual_sin_costo_a_mano_es_no_op(alm):
    """Pedir el borrado de una fila que no lo tiene no es un error."""
    cid = _corrida(alm, contractual=1000.0, apu="100")
    v = svc.quitar_costo_manual(alm, cid, [0])
    assert v["quitadas"] == []
    assert v["items"][0]["costo_unitario"] == 40000.0


def test_quitar_costo_manual_congelada_no_se_toca(alm):
    cid = _corrida(alm, contractual=1000.0)
    alm.corridas.set_costo_manual(cid, {0: 1000.0})
    alm.corridas.set_modo(cid, "congelada")
    with pytest.raises(svc.CorridaCongelada):
        svc.quitar_costo_manual(alm, cid, [0])


def test_quitar_costo_manual_corrida_inexistente_devuelve_none(alm):
    assert svc.quitar_costo_manual(alm, 9999, [0]) is None


def test_quitar_costo_manual_finalizada_vuelve_a_revision(alm):
    """El cuadro emitido ya no dice la verdad."""
    cid = _corrida(alm, contractual=1000.0, estado="finalizada")
    alm.corridas.set_costo_manual(cid, {0: 1000.0})
    svc.quitar_costo_manual(alm, cid, [0])
    assert alm.corridas.get_corrida(cid).estado == "en_revision"
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `python -m pytest tests/test_costo_manual.py -k quitar -q`
Expected: 6 FAIL con `AttributeError: module 'apu_tool.servicio.corridas' has no attribute 'quitar_costo_manual'`

- [ ] **Step 3: Implementar**

En `apu_tool/servicio/corridas.py`, justo después de `igualar_costo_al_contractual` (antes de `def revisar_corrida_stream`):

```python
def quitar_costo_manual(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                        actor=None) -> Optional[dict]:
    """Borra el costo puesto a mano de las filas marcadas y las devuelve al costeo.

    Es el reverso de `igualar_costo_al_contractual`, y existe porque el umbral puede
    tocar cientos de filas de un clic: sin vuelta atrás, un techo mal puesto se
    arregla fila por fila armando APUs que justamente no querías armar.

    Pedir el borrado de una fila que no tiene costo a mano no es un error: es un
    no-op y no se audita. Devuelve la vista de la corrida con `quitadas`, o None si
    la corrida no existe. Lanza CorridaCongelada si está congelada.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    pedidos = {int(s) for s in seqs}
    filas = [r for r in alm.corridas.get_items(corrida_id)
             if r.seq in pedidos and r.costo_manual is not None]
    if filas:
        with alm.transaccion("corridas") as conn:
            alm.corridas.limpiar_costo_manual(
                corrida_id, [r.seq for r in filas], conn=conn)
            registrar_auditoria(
                alm, conn, actor, "corrida.quitar_costo_manual", "corrida", corrida_id,
                antes={"lineas": [{"seq": r.seq, "costo_manual": r.costo_manual}
                                  for r in filas]},
                despues={"lineas": [{"seq": r.seq, "costo_manual": None}
                                    for r in filas]})
        if meta.estado == "finalizada":
            alm.corridas.set_estado(corrida_id, "en_revision")   # el cuadro ya no dice la verdad
    vista = vista_corrida(alm, corrida_id)
    if vista is not None:
        vista["quitadas"] = sorted(r.seq for r in filas)
    return vista
```

- [ ] **Step 4: Correr las pruebas para verificar que pasan**

Run: `python -m pytest tests/test_costo_manual.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_costo_manual.py
git commit -m "feat(corridas): quitar el costo puesto a mano de un lote de lineas"
```

---

### Task 3: `igualar_por_umbral` en el servicio

**Files:**
- Modify: `apu_tool/servicio/corridas.py` (la firma de `igualar_costo_al_contractual`, ~línea 1343, y funciones nuevas después de ella)
- Test: `tests/test_costo_manual.py`
- Test: `tests/test_auditoria_servicios_corridas_usuarios.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregá al final de `tests/test_costo_manual.py`. Primero el helper (la corrida de este bloque tiene varias filas, a diferencia de `_corrida`):

```python
def _corrida_varias(alm, precios, *, cantidad: float = 1.0) -> int:
    """Una corrida con una fila por precio, todas SIN APU (o sea, todas en $0)."""
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="2026-09-21T10:00:00", archivo="x.xlsx", turno_def="DIURNO",
        use_ai=None, estado="en_revision", cuadro_path=None, nombre="x"))
    for seq, precio in enumerate(precios):
        alm.corridas.agregar_item(cid, CorridaItemRow(
            seq=seq,
            item=LicitacionItem(item=str(seq), descripcion=f"ACTIVIDAD {seq}",
                                unidad="GLB", cantidad=cantidad,
                                precio_contractual=precio, shift="DIURNO"),
            status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
            origen="historico", confianza=0.0, explicacion="", componentes=[],
            candidatos=[]))
    return cid


def test_umbral_iguala_lo_de_abajo_y_deja_lo_de_arriba(alm):
    """El techo es inclusivo: «iguales o menores al límite», como lo pidió el usuario."""
    cid = _corrida_varias(alm, [100_000_000.0, 500_000_000.0, 900_000_000.0])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0, 1, 2])
    assert v["igualadas"] == [0, 1]
    assert v["salteadas"] == [2]
    assert [f["costo_unitario"] for f in v["items"]] == [
        100_000_000.0, 500_000_000.0, 0.0]


def test_umbral_mide_el_total_y_no_el_unitario(alm):
    """Unitario chico por cantidad grande es una actividad cara: no se iguala."""
    cid = _corrida_varias(alm, [1_000_000.0], cantidad=1000.0)   # total = $1.000M
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["igualadas"] == []
    assert v["salteadas"] == [0]


def test_umbral_saltea_la_fila_que_dejo_de_estar_en_cero(alm):
    """La carrera de la pestaña vieja: entre la previa y el aplicar le asignaron un
    APU. Sin el recálculo en el servidor, el costo real se pisaría con el contractual
    y encima la fila quedaría `confirmed`, fuera del alcance de volver a buscar."""
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.actualizar_eleccion(
        cid, 0, status="confirmed", apu_codigo="100", apu_nombre="EXCAVACION MANUAL",
        unidad="M3", shift="DIURNO", origen="historico", confianza=1.0, explicacion="",
        componentes=[{"insumo_codigo": "4279", "insumo_nombre": "CUADRILLA",
                      "unidad": "HR", "rendimiento": 1.0}])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["igualadas"] == []
    assert v["salteadas"] == [0]
    assert v["items"][0]["costo_unitario"] == 40000.0      # el del APU, intacto


def test_umbral_no_toca_la_que_ya_tiene_costo_a_mano(alm):
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.set_costo_manual(cid, {0: 777.0})
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["salteadas"] == [0]
    assert v["items"][0]["costo_unitario"] == 777.0


def test_umbral_saltea_la_fila_sin_precio_contractual(alm):
    """Está en $0 pero el contrato tampoco la paga: igualarla sería el $0 que la
    regla de negocio prohíbe, así que ni se propone."""
    cid = _corrida_varias(alm, [0.0])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])
    assert v["salteadas"] == [0]
    assert v["igualadas"] == []


def test_umbral_solo_mira_lo_que_el_cliente_marco(alm):
    """Destildar una fila en la previa la deja afuera, y ni siquiera se saltea:
    nunca se pidió."""
    cid = _corrida_varias(alm, [100.0, 200.0])
    v = svc.igualar_por_umbral(alm, cid, 500_000_000.0, [1])
    assert v["igualadas"] == [1]
    assert v["salteadas"] == []
    assert v["items"][0]["costo_unitario"] == 0.0


def test_umbral_no_positivo_es_error(alm):
    """Un umbral de $0 no iguala nada y uno negativo es un dedo resbalado. El NaN va
    con `not (x > 0)`: `nan <= 0` es False y dejaría pasar cualquier fila."""
    cid = _corrida_varias(alm, [1000.0])
    for malo in (0.0, -5.0, float("nan")):
        with pytest.raises(ValueError):
            svc.igualar_por_umbral(alm, cid, malo, [0])


def test_umbral_congelada_no_se_toca(alm):
    cid = _corrida_varias(alm, [1000.0])
    alm.corridas.set_modo(cid, "congelada")
    with pytest.raises(svc.CorridaCongelada):
        svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0])


def test_umbral_corrida_inexistente_devuelve_none(alm):
    assert svc.igualar_por_umbral(alm, 9999, 500_000_000.0, [0]) is None
```

Y en `tests/test_auditoria_servicios_corridas_usuarios.py`, al final:

```python
def test_igualar_por_umbral_deja_el_umbral_en_la_auditoria(tmp_path):
    """312 filas igualadas de a una y 312 igualadas por un techo de $500M son hechos
    distintos: el registro tiene que decir con qué regla se aplicó."""
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA", unidad="GLB",
                            cantidad=1.0, precio_contractual=1000.0, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[]))
    corridas_svc.igualar_por_umbral(alm, cid, 500_000_000.0, [0], actor=_admin())
    items, total = alm.auditoria.listar(accion="corrida.igualar_costo")
    assert total == 1
    assert items[0]["contexto"]["umbral_contractual"] == 500_000_000.0


def test_igualar_de_a_una_no_inventa_umbral_en_la_auditoria(tmp_path):
    """El botón de siempre no pone techo: la clave no aparece."""
    alm = _alm(tmp_path)
    cid = alm.corridas.crear_corrida(CorridaMeta(
        id=None, creada_en="x", archivo="lic.xlsx", turno_def="DIURNO",
        use_ai=False, estado="en_revision"))
    alm.corridas.agregar_item(cid, CorridaItemRow(
        seq=0,
        item=LicitacionItem(item="1", descripcion="PRUEBA DE CARGA", unidad="GLB",
                            cantidad=1.0, precio_contractual=1000.0, shift="DIURNO"),
        status="new", apu_codigo=None, apu_nombre="", unidad="GLB", shift="DIURNO",
        origen="historico", confianza=0.0, explicacion="", componentes=[], candidatos=[]))
    corridas_svc.igualar_costo_al_contractual(alm, cid, [0], actor=_admin())
    items, _ = alm.auditoria.listar(accion="corrida.igualar_costo")
    assert "umbral_contractual" not in items[0]["contexto"]
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `python -m pytest tests/test_costo_manual.py -k umbral tests/test_auditoria_servicios_corridas_usuarios.py -k umbral -q`
Expected: FAIL con `AttributeError: module 'apu_tool.servicio.corridas' has no attribute 'igualar_por_umbral'`

- [ ] **Step 3: Agregar el parámetro de auditoría a `igualar_costo_al_contractual`**

En `apu_tool/servicio/corridas.py`, cambiá la firma (~línea 1343):

```python
def igualar_costo_al_contractual(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                                 actor=None,
                                 umbral_contractual: Optional[float] = None
                                 ) -> Optional[dict]:
```

y el `contexto` de la llamada a `registrar_auditoria` que ya está adentro:

```python
                contexto={"rechazadas": sorted(rechazadas),
                          # Solo cuando el gesto vino de un techo: el registro tiene
                          # que decir con qué regla se aplicó.
                          **({} if umbral_contractual is None
                             else {"umbral_contractual": float(umbral_contractual)})})
```

Agregá al final del docstring de esa función:

```
    `umbral_contractual` no cambia lo que se escribe: solo queda en la auditoría
    cuando el gesto vino del techo por línea (`igualar_por_umbral`).
```

- [ ] **Step 4: Implementar `igualar_por_umbral` y su predicado**

En el mismo archivo, después de `igualar_costo_al_contractual`:

```python
def _candidata_umbral(item: dict) -> bool:
    """Una fila que el umbral puede igualar: está en $0 y el contrato sí la paga.

    Una fila SIN APU siempre cuesta $0, así que entra sola; una CON APU pero sin
    precios también, que es el otro caso que deja el cuadro trabado. `not (x > 0)` y
    no `x == 0` por el NaN, igual que en el resto del módulo.

    `item` es un ítem de `vista_corrida`, no una fila cruda: ahí `costo_manual` ya es
    el booleano derivado del ensamble y `costo_unitario` ya está costeado.
    """
    return (not item["costo_manual"]
            and not (item["costo_unitario"] > 0)
            and item["precio_contractual"] > 0)


def igualar_por_umbral(alm: Almacen, corrida_id: int, umbral: float,
                       seqs: Iterable[int], actor=None) -> Optional[dict]:
    """Iguala al contractual las filas en $0 cuyo TOTAL contractual no pase el umbral.

    Para priorizar: en una licitación de 1939 actividades un puñado se lleva casi
    todo el presupuesto y la cola larga pesa centavos. Armarle el APU a cada una de
    esas cuesta semanas y no mueve la evaluación.

    El cliente manda los `seq` que marcó en la previa, pero la candidatura se
    RECALCULA acá: si entre la previa y el aplicar alguien le asignó un APU a una
    fila, se saltea. Es el mismo candado que `apu_evaluado` en la revisión y que
    `aplicar_rebusqueda` — el cliente dice cuáles quiere, no qué se escribe. Sin
    esto, una pestaña vieja pisaría un APU recién asignado con una copia del
    contractual, y encima dejaría la fila `confirmed`, o sea fuera del alcance de
    volver a buscar APU. Con diez filas eso se ve; con mil quinientas no.

    Cuesta dos costeos: uno para decidir la candidatura y otro para la vista que
    vuelve. Es una acción deliberada, no un render.

    Devuelve la vista con `igualadas`, `rechazadas` y `salteadas`, o None si la
    corrida no existe. Lanza CorridaCongelada si está congelada y ValueError si el
    umbral no es un monto positivo.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    # `not (x > 0)` y NO `x <= 0`: con NaN, `nan <= 0` es False y el techo dejaría
    # pasar cualquier fila.
    if not (float(umbral) > 0):
        raise ValueError("El umbral tiene que ser un monto mayor que $0.")
    vista = vista_corrida(alm, corrida_id)
    if vista is None:
        return None
    pedidos = {int(s) for s in seqs}
    elegidas: list[int] = []
    salteadas: list[int] = []
    for it in vista["items"]:
        if it["seq"] not in pedidos:
            continue          # no se pidió: no se iguala y tampoco se reporta
        if _candidata_umbral(it) and it["contractual_total"] <= umbral:
            elegidas.append(it["seq"])
        else:
            salteadas.append(it["seq"])
    v = igualar_costo_al_contractual(alm, corrida_id, elegidas, actor,
                                     umbral_contractual=float(umbral))
    if v is not None:
        v["salteadas"] = sorted(salteadas)
    return v
```

- [ ] **Step 5: Correr las pruebas para verificar que pasan**

Run: `python -m pytest tests/test_costo_manual.py tests/test_auditoria_servicios_corridas_usuarios.py -q`
Expected: PASS

- [ ] **Step 6: Commit**

```bash
git add apu_tool/servicio/corridas.py tests/test_costo_manual.py tests/test_auditoria_servicios_corridas_usuarios.py
git commit -m "feat(corridas): igualar al contractual por techo de total contractual"
```

---

### Task 4: Los dos endpoints y la frontera de privacidad

**Files:**
- Modify: `apu_tool/dominio/privacy.py` (`_FORBIDDEN_KEYS`, ~línea 25)
- Modify: `apu_tool/servicio/esquemas.py` (después de `IgualarCostoIn`, ~línea 56)
- Modify: `apu_tool/servicio/rutas.py` (imports ~línea 48; endpoints después de `igualar_costo`, ~línea 497)
- Test: `tests/test_api_corridas.py`

- [ ] **Step 1: Escribir las pruebas que fallan**

Agregá a `tests/test_api_corridas.py`, después de `test_igualar_costo_rol_editor_permitido`. Reusan `_corrida_especial`, `_cliente` y `_cli_rol`, que ya están en el archivo:

```python
def test_igualar_umbral_endpoint(tmp_path):
    """Feliz: la fila cae bajo el techo y queda con el contractual como costo."""
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)          # una línea sin APU, contractual $92.106.000
    r = cli.post(f"/api/corridas/{cid}/igualar-umbral",
                 json={"umbral_contractual": 500_000_000.0, "seqs": [0]})
    assert r.status_code == 200, r.text
    body = r.json()
    assert body["igualadas"] == [0] and body["salteadas"] == []
    assert body["items"][0]["costo_manual"] is True


def test_igualar_umbral_saltea_lo_que_pasa_el_techo(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-umbral",
                 json={"umbral_contractual": 1000.0, "seqs": [0]})
    assert r.status_code == 200, r.text
    assert r.json()["salteadas"] == [0]
    assert r.json()["items"][0]["costo_manual"] is False


def test_igualar_umbral_400_si_el_techo_no_es_positivo(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-umbral",
                 json={"umbral_contractual": 0.0, "seqs": [0]})
    assert r.status_code == 400


def test_igualar_umbral_409_si_congelada(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/igualar-umbral",
                 json={"umbral_contractual": 500_000_000.0, "seqs": [0]})
    assert r.status_code == 409


def test_igualar_umbral_404_si_no_existe(tmp_path):
    cli, _ = _cliente(tmp_path)
    r = cli.post("/api/corridas/9999/igualar-umbral",
                 json={"umbral_contractual": 500_000_000.0, "seqs": [0]})
    assert r.status_code == 404


def test_igualar_umbral_rol_consulta_prohibido(tmp_path):
    """Declara dinero, y de a cientos de filas: no se le abre al rol de solo lectura."""
    cli, alm = _cli_rol(tmp_path, "consulta")
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/igualar-umbral",
                 json={"umbral_contractual": 500_000_000.0, "seqs": [0]})
    assert r.status_code == 403


def test_quitar_costo_manual_endpoint(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    r = cli.post(f"/api/corridas/{cid}/quitar-costo-manual", json={"seqs": [0]})
    assert r.status_code == 200, r.text
    assert r.json()["quitadas"] == [0]
    assert r.json()["items"][0]["costo_manual"] is False


def test_quitar_costo_manual_409_si_congelada(tmp_path):
    cli, alm = _cliente(tmp_path)
    cid = _corrida_especial(alm)
    alm.corridas.set_costo_manual(cid, {0: 92106000.0})
    alm.corridas.set_modo(cid, "congelada")
    r = cli.post(f"/api/corridas/{cid}/quitar-costo-manual", json={"seqs": [0]})
    assert r.status_code == 409


def test_quitar_costo_manual_404_si_no_existe(tmp_path):
    cli, _ = _cliente(tmp_path)
    r = cli.post("/api/corridas/9999/quitar-costo-manual", json={"seqs": [0]})
    assert r.status_code == 404


def test_quitar_costo_manual_rol_consulta_prohibido(tmp_path):
    cli, alm = _cli_rol(tmp_path, "consulta")
    cid = _corrida_especial(alm)
    r = cli.post(f"/api/corridas/{cid}/quitar-costo-manual", json={"seqs": [0]})
    assert r.status_code == 403
```

Y al final de `tests/test_privacy.py` (ese archivo ya importa `PrivacyViolation` y
`assert_no_money` directo, no hace falta tocar los imports):

```python
def test_umbral_contractual_es_dinero_para_la_frontera():
    """No viaja a ningún payload de IA hoy —vive en el request y en la auditoría—
    pero es un monto con nombre propio, y la regla de la casa es que entre."""
    with pytest.raises(PrivacyViolation):
        assert_no_money({"umbral_contractual": 500_000_000.0})
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `python -m pytest tests/test_api_corridas.py -k "umbral or quitar_costo" -q`
Expected: FAIL con 404 (la ruta no existe todavía)

- [ ] **Step 3: Agregar la clave prohibida**

En `apu_tool/dominio/privacy.py`, dentro de `_FORBIDDEN_KEYS`, junto a `"costo_manual"`:

```python
    "fuente_precio", "costo_manual", "plan_json",
    # El techo en pesos con el que se igualan las líneas chicas al contractual. No se
    # persiste (vive en el request y en la auditoría), pero es un monto con nombre
    # propio. Se llama así y no `umbral` a secas para no chocar con los umbrales de
    # matching, que NO son dinero: un falso positivo ahí volaría un payload legítimo.
    "umbral_contractual",
```

- [ ] **Step 4: Agregar los DTOs**

En `apu_tool/servicio/esquemas.py`, después de `IgualarCostoIn`:

```python
class IgualarUmbralIn(BaseModel):
    """El techo por línea y los seq que el usuario marcó en la previa.

    El servidor recalcula la candidatura con estos dos datos: el cliente dice cuáles
    quiere, no qué se escribe."""
    umbral_contractual: float
    seqs: list[int]


class QuitarCostoManualIn(BaseModel):
    seqs: list[int]
```

- [ ] **Step 5: Agregar los endpoints**

En `apu_tool/servicio/rutas.py`, sumá los dos nombres al import de `esquemas` (~línea 48):

```python
    ComposicionRechazarIn, ConfirmarIn, ConfirmarLoteIn, EstadoIn, IgualarCostoIn,
    IgualarUmbralIn, InsumoNuevoIn, ListaPreciosIn, QuitarCostoManualIn,
    RebuscarAplicarIn, RolIn, StatusOut,
```

(mantené el orden alfabético y el resto de la lista tal como está).

Y después de la función `igualar_costo`:

```python
@router.post("/corridas/{cid}/igualar-umbral")
def igualar_umbral(cid: int, body: IgualarUmbralIn,
                   alm: Almacen = Depends(get_almacen),
                   actor=Depends(requiere_rol("editor"))):
    # Rol `editor` por lo mismo que `igualar-costo`: declara dinero. Este además lo
    # declara de a cientos de filas de un clic.
    try:
        v = svc.igualar_por_umbral(alm, cid, body.umbral_contractual, body.seqs, actor)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para modificar.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v


@router.post("/corridas/{cid}/quitar-costo-manual")
def quitar_costo_manual(cid: int, body: QuitarCostoManualIn,
                        alm: Almacen = Depends(get_almacen),
                        actor=Depends(requiere_rol("editor"))):
    # Mismo rol que poner el costo a mano: quitarlo también mueve plata.
    try:
        v = svc.quitar_costo_manual(alm, cid, body.seqs, actor)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para modificar.")
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

- [ ] **Step 6: Correr las pruebas para verificar que pasan**

Run: `python -m pytest tests/ -q`
Expected: PASS (toda la suite, para confirmar que la clave nueva de `_FORBIDDEN_KEYS` no rompe ningún payload existente)

- [ ] **Step 7: Commit**

```bash
git add apu_tool/dominio/privacy.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_corridas.py tests/test_privacy.py
git commit -m "feat(api): endpoints de igualar por umbral y quitar el costo a mano"
```

---

### Task 5: El cálculo de la previa (`umbralCosto.ts`)

**Files:**
- Create: `web/src/lib/umbralCosto.ts`
- Test: `web/src/lib/umbralCosto.test.ts`

- [ ] **Step 1: Escribir las pruebas que fallan**

Creá `web/src/lib/umbralCosto.test.ts`:

```ts
import { expect, test } from "vitest";
import { esCandidata, porcentaje, previaUmbral } from "./umbralCosto";
import type { ItemCuadro } from "./tipos";

function item(p: Partial<ItemCuadro>): ItemCuadro {
  return {
    seq: 0, item: "1", descripcion: "X", unidad: "GLB", cantidad: 1,
    apu_codigo: "", apu_nombre: "", status: "new", confianza: 0,
    precio_contractual: 1000, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 1000, costo_total: 0, margen_total: 0,
    costo_manual: false, revision: null, ...p,
  } as ItemCuadro;
}

test("candidata: sin APU está en $0 y el contrato la paga", () => {
  expect(esCandidata(item({}))).toBe(true);
});

test("candidata: con APU pero en $0 también entra", () => {
  expect(esCandidata(item({ apu_codigo: "A1", costo_unitario: 0 }))).toBe(true);
});

test("no es candidata: ya tiene costo, o costo a mano, o el contrato no la paga", () => {
  expect(esCandidata(item({ costo_unitario: 500 }))).toBe(false);
  expect(esCandidata(item({ costo_manual: true, costo_unitario: 1000 }))).toBe(false);
  expect(esCandidata(item({ precio_contractual: 0 }))).toBe(false);
});

test("el techo es inclusivo y parte por el total, no por el unitario", () => {
  const items = [
    item({ seq: 0, contractual_total: 100 }),
    item({ seq: 1, contractual_total: 500 }),
    item({ seq: 2, contractual_total: 501 }),
  ];
  const p = previaUmbral(items, 500);
  expect(p.igualadas.map((i) => i.seq)).toEqual([1, 0]);   // de mayor a menor
  expect(p.restantes.map((i) => i.seq)).toEqual([2]);
  expect(p.sumaIgualadas).toBe(600);
  expect(p.sumaRestantes).toBe(501);
});

test("el contractual de la corrida suma TODAS las filas, no solo las candidatas", () => {
  const items = [
    item({ seq: 0, contractual_total: 100 }),
    item({ seq: 1, contractual_total: 9000, costo_unitario: 50 }),  // ya costeada
  ];
  const p = previaUmbral(items, 500);
  expect(p.candidatas).toHaveLength(1);
  expect(p.contractualCorrida).toBe(9100);
});

test("desglose de las que se igualan: con APU y sin APU", () => {
  const items = [
    item({ seq: 0, contractual_total: 100 }),
    item({ seq: 1, contractual_total: 100, apu_codigo: "A1" }),
  ];
  const p = previaUmbral(items, 500);
  expect(p.sinApu).toBe(1);
  expect(p.conApu).toBe(1);
});

test("las que están en $0 pero sin contractual se cuentan aparte", () => {
  const p = previaUmbral([item({ precio_contractual: 0, contractual_total: 0 })], 500);
  expect(p.candidatas).toHaveLength(0);
  expect(p.sinContractual).toBe(1);
});

test("umbral 0, negativo o NaN no iguala nada", () => {
  const items = [item({ contractual_total: 100 })];
  for (const malo of [0, -5, NaN]) {
    expect(previaUmbral(items, malo).igualadas).toHaveLength(0);
  }
});

test("porcentaje no divide por cero", () => {
  expect(porcentaje(50, 200)).toBe(25);
  expect(porcentaje(50, 0)).toBe(0);
});
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `cd web && npm test -- src/lib/umbralCosto.test.ts`
Expected: FAIL — `Failed to resolve import "./umbralCosto"`

- [ ] **Step 3: Implementar**

Creá `web/src/lib/umbralCosto.ts`:

```ts
import type { ItemCuadro } from "./tipos";

/** Una fila que el umbral puede igualar: está en $0 y el contrato sí la paga.
 *
 *  Misma regla que `_candidata_umbral` en `servicio/corridas.py`, sobre los mismos
 *  campos. Una fila SIN APU siempre cuesta $0, así que entra sola; una CON APU pero
 *  sin precios también, que es el otro caso que deja el cuadro trabado.
 *  `!(x > 0)` y no `x === 0` por el NaN. */
export function esCandidata(it: ItemCuadro): boolean {
  return !it.costo_manual && !(it.costo_unitario > 0) && it.precio_contractual > 0;
}

export interface PreviaUmbral {
  /** En $0 y pagables: el universo sobre el que actúa el techo. */
  candidatas: ItemCuadro[];
  /** Candidatas bajo el techo, por `contractual_total` de mayor a menor. */
  igualadas: ItemCuadro[];
  /** Candidatas por encima del techo: las que hay que armar de verdad. */
  restantes: ItemCuadro[];
  sumaIgualadas: number;
  sumaRestantes: number;
  /** Suma de TODAS las filas de la corrida, para los porcentajes. */
  contractualCorrida: number;
  sinApu: number;
  conApu: number;
  /** En $0 pero con contractual ≤ 0: no se pueden igualar (regla «nada en $0»). */
  sinContractual: number;
}

const suma = (xs: ItemCuadro[]) => xs.reduce((s, it) => s + it.contractual_total, 0);

/** Qué pasaría con este umbral.
 *
 *  Cálculo puro sobre los ítems que la página ya tiene: es apoyo a la decisión, no un
 *  número que se persiste ni se emite. La escritura la manda el backend, que
 *  recalcula la candidatura con sus propios números. */
export function previaUmbral(items: ItemCuadro[], umbral: number): PreviaUmbral {
  const candidatas = items.filter(esCandidata);
  // Umbral 0, negativo o NaN: no se iguala nada (y el botón queda deshabilitado).
  const hayTecho = umbral > 0;
  const igualadas = candidatas
    .filter((it) => hayTecho && it.contractual_total <= umbral)
    .sort((a, b) => b.contractual_total - a.contractual_total);
  const marcadas = new Set(igualadas.map((it) => it.seq));
  const restantes = candidatas.filter((it) => !marcadas.has(it.seq));
  return {
    candidatas,
    igualadas,
    restantes,
    sumaIgualadas: suma(igualadas),
    sumaRestantes: suma(restantes),
    contractualCorrida: suma(items),
    sinApu: igualadas.filter((it) => !it.apu_codigo).length,
    conApu: igualadas.filter((it) => !!it.apu_codigo).length,
    sinContractual: items.filter(
      (it) => !it.costo_manual && !(it.costo_unitario > 0) && !(it.precio_contractual > 0),
    ).length,
  };
}

/** Porcentaje del contrato, a prueba de una corrida que suma $0. */
export function porcentaje(parte: number, total: number): number {
  return total > 0 ? (parte / total) * 100 : 0;
}
```

- [ ] **Step 4: Correr las pruebas para verificar que pasan**

Run: `cd web && npm test -- src/lib/umbralCosto.test.ts`
Expected: PASS (9 tests)

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/umbralCosto.ts web/src/lib/umbralCosto.test.ts
git commit -m "feat(web): calculo de la previa del umbral, puro y probado"
```

---

### Task 6: El diálogo (`DialogoUmbralCosto.tsx`)

**Files:**
- Create: `web/src/components/corrida/DialogoUmbralCosto.tsx`
- Test: `web/src/components/corrida/DialogoUmbralCosto.test.tsx`

- [ ] **Step 1: Escribir las pruebas que fallan**

Creá `web/src/components/corrida/DialogoUmbralCosto.test.tsx`:

```tsx
import { describe, expect, it, vi } from "vitest";
import { fireEvent, render, screen } from "@testing-library/react";
import DialogoUmbralCosto from "./DialogoUmbralCosto";
import type { ItemCuadro } from "@/lib/tipos";

function item(p: Partial<ItemCuadro>): ItemCuadro {
  return {
    seq: 0, item: "1", descripcion: "ACTIVIDAD", unidad: "GLB", cantidad: 1,
    apu_codigo: "", apu_nombre: "", status: "new", confianza: 0,
    precio_contractual: 1000, costo_unitario: 0, margen_unitario: 0, margen_pct: 0,
    contractual_total: 1000, costo_total: 0, margen_total: 0,
    costo_manual: false, revision: null, ...p,
  } as ItemCuadro;
}

const ITEMS = [
  item({ seq: 0, item: "1", contractual_total: 100 }),
  item({ seq: 1, item: "2", contractual_total: 900 }),
  item({ seq: 2, item: "3", contractual_total: 5000 }),
];

function abrir(onAplicar = vi.fn()) {
  render(<DialogoUmbralCosto abierto items={ITEMS} aplicando={false}
                             onAplicar={onAplicar} onCerrar={vi.fn()} />);
  return onAplicar;
}

function escribirUmbral(valor: string) {
  fireEvent.change(screen.getByLabelText("Umbral de total contractual"),
                   { target: { value: valor } });
}

describe("DialogoUmbralCosto", () => {
  it("sin umbral no propone nada y el botón está deshabilitado", () => {
    abrir();
    // Sin jest-dom en este proyecto: se mira la propiedad, no un matcher.
    const btn = screen.getByRole("button", { name: /Igualar/ }) as HTMLButtonElement;
    expect(btn.disabled).toBe(true);
  });

  it("el techo es inclusivo: con 900 entran las de 100 y 900, no la de 5000", () => {
    abrir();
    escribirUmbral("900");
    expect(screen.getByLabelText("Marcar línea 1")).toBeTruthy();
    expect(screen.getByLabelText("Marcar línea 2")).toBeTruthy();
    expect(screen.queryByLabelText("Marcar línea 3")).toBeNull();
  });

  it("aplica el umbral y solo los seq marcados", () => {
    const onAplicar = abrir();
    escribirUmbral("900");
    // La lista va de mayor a menor: la línea 1 es el seq 1 ($900).
    fireEvent.click(screen.getByLabelText("Marcar línea 1"));
    fireEvent.click(screen.getByRole("button", { name: /Igualar/ }));
    expect(onAplicar).toHaveBeenCalledWith(900, [0]);
  });

  it("cambiar el umbral rehace las marcas", () => {
    const onAplicar = abrir();
    escribirUmbral("900");
    fireEvent.click(screen.getByLabelText("Marcar línea 1"));   // destilda el seq 1
    escribirUmbral("5000");
    fireEvent.click(screen.getByRole("button", { name: /Igualar/ }));
    expect(onAplicar).toHaveBeenCalledWith(5000, [0, 1, 2]);
  });

  it("avisa de las que están en $0 pero el contrato no paga", () => {
    render(<DialogoUmbralCosto abierto aplicando={false} onAplicar={vi.fn()}
                               onCerrar={vi.fn()}
                               items={[item({ precio_contractual: 0, contractual_total: 0 })]} />);
    expect(screen.getByText(/sin precio contractual/i)).toBeTruthy();
  });
});
```

- [ ] **Step 2: Correr las pruebas para verificar que fallan**

Run: `cd web && npm test -- src/components/corrida/DialogoUmbralCosto.test.tsx`
Expected: FAIL — `Failed to resolve import "./DialogoUmbralCosto"`

- [ ] **Step 3: Implementar el diálogo**

Creá `web/src/components/corrida/DialogoUmbralCosto.tsx`:

```tsx
import { useMemo, useRef, useState } from "react";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { Button } from "@/components/ui/button";
import { cop } from "@/lib/moneda";
import { porcentaje, previaUmbral } from "@/lib/umbralCosto";
import type { ItemCuadro } from "@/lib/tipos";

interface Props {
  abierto: boolean;
  /** Todos los ítems de la corrida: el techo es una decisión de presupuesto, no de
   *  vista, así que NO se filtra por lo que la tabla esté mostrando. */
  items: ItemCuadro[];
  aplicando: boolean;
  onAplicar: (umbral: number, seqs: number[]) => void;
  onCerrar: () => void;
}

/** Pone un techo en pesos sobre el total contractual de una línea: todas las
 *  actividades en $0 que caigan debajo se igualan al contractual de un gesto.
 *
 *  Para priorizar: un puñado de actividades se lleva casi todo el presupuesto y
 *  armarle el APU a la cola larga cuesta semanas sin mover la evaluación. */
export default function DialogoUmbralCosto({
  abierto, items, aplicando, onAplicar, onCerrar,
}: Props) {
  const [texto, setTexto] = useState("");
  const umbral = Number(texto);
  const p = useMemo(() => previaUmbral(items, umbral), [items, umbral]);

  // Las marcas se DERIVAN del umbral y se rehacen cuando cambia: la lista es otra, y
  // conservar destildes de una lista anterior sería adivinar. `destildadas` guarda
  // solo lo que el usuario sacó a mano de la lista de hoy.
  const [destildadas, setDestildadas] = useState<Set<number>>(new Set());
  const [ultimoTecho, setUltimoTecho] = useState("");
  if (ultimoTecho !== texto) {                 // patrón de estado derivado, sin efecto
    setUltimoTecho(texto);
    setDestildadas(new Set());
  }
  const marcados = p.igualadas
    .filter((it) => !destildadas.has(it.seq))
    .map((it) => it.seq);

  // Ancla del último clic SIN Shift, por `seq` (único en la corrida), igual que
  // DialogoRebuscar.
  const anclaRef = useRef<number | null>(null);

  function alternar(idx: number, seq: number, conShift: boolean) {
    const desde = anclaRef.current === null
      ? -1
      : p.igualadas.findIndex((it) => it.seq === anclaRef.current);
    if (conShift && desde >= 0) {
      const [a, b] = desde <= idx ? [desde, idx] : [idx, desde];
      const rango = p.igualadas.slice(a, b + 1).map((it) => it.seq);
      setDestildadas((prev) => {
        const s = new Set(prev);
        for (const seqRango of rango) s.delete(seqRango);   // el rango MARCA
        return s;
      });
      return;                                  // el ancla del rango no se mueve
    }
    anclaRef.current = seq;
    setDestildadas((prev) => {
      const s = new Set(prev);
      if (s.has(seq)) s.delete(seq); else s.add(seq);
      return s;
    });
  }

  const pctIgualadas = porcentaje(p.sumaIgualadas, p.contractualCorrida);
  const pctRestantes = porcentaje(p.sumaRestantes, p.contractualCorrida);
  const th = "px-2 py-1 text-left font-semibold text-muted-foreground";
  const td = "px-2 py-1 align-top";

  return (
    <Dialog open={abierto} onOpenChange={(v) => { if (!v) onCerrar(); }}>
      <DialogContent className="max-w-4xl">
        <DialogHeader>
          <DialogTitle>Igualar bajo umbral</DialogTitle>
        </DialogHeader>

        <p className="text-xs text-muted-foreground -mt-2">
          Las actividades en $0 cuyo total contractual no pase el umbral se igualan al
          precio contractual, para poder evaluar sin armarles el APU. Se puede
          deshacer con «Quitar costo a mano».
        </p>

        <div className="flex flex-wrap items-center gap-2">
          <label className="text-xs font-medium" htmlFor="umbral-contractual">
            Umbral de total contractual
          </label>
          <input
            id="umbral-contractual"
            aria-label="Umbral de total contractual"
            className="h-8 w-48 rounded border border-border bg-transparent px-2
                       text-sm tabular-nums outline-none focus-visible:border-ring"
            type="number" min="0" step="1000000" value={texto}
            placeholder="500000000"
            onChange={(e) => setTexto(e.target.value)}
          />
          {/* El monto escrito, en letras de gente: son nueve dígitos. */}
          <span className="text-sm font-semibold tabular-nums">
            {umbral > 0 ? cop(umbral) : "—"}
          </span>
        </div>

        <div className="rounded border border-border bg-muted/40 p-2 text-xs">
          <div className="flex justify-between">
            <span>Actividades en $0</span>
            <span className="tabular-nums">
              {p.candidatas.length} · {cop(p.sumaIgualadas + p.sumaRestantes)}
            </span>
          </div>
          <div className="flex justify-between text-emerald-700 dark:text-emerald-400">
            <span>Se igualan al contractual</span>
            <span className="tabular-nums">
              {p.igualadas.length} · {cop(p.sumaIgualadas)} · {pctIgualadas.toFixed(1)}%
              {" "}del contrato
            </span>
          </div>
          <div className="flex justify-between">
            <span>Quedan por armar</span>
            <span className="tabular-nums">
              {p.restantes.length} · {cop(p.sumaRestantes)} · {pctRestantes.toFixed(1)}%
              {" "}del contrato
            </span>
          </div>
          {p.igualadas.length > 0 && (
            <div className="pt-1 text-muted-foreground">
              Se igualan: {p.sinApu} sin APU · {p.conApu} con APU pero sin precios.
            </div>
          )}
          {p.sinContractual > 0 && (
            <div className="pt-1 text-amber-700 dark:text-amber-400">
              {p.sinContractual} en $0 sin precio contractual: no se pueden igualar
              (nada queda en $0).
            </div>
          )}
        </div>

        {p.igualadas.length > 0 && (
          <div className="max-h-[45vh] overflow-auto rounded border border-border">
            <table className="w-full text-xs">
              <thead className="sticky top-0 bg-muted">
                <tr>
                  <th className={th}> </th>
                  <th className={th}>#</th>
                  <th className={th}>Actividad</th>
                  <th className={th}>APU</th>
                  <th className={`${th} text-right`}>Total contractual</th>
                </tr>
              </thead>
              <tbody>
                {p.igualadas.map((it, i) => (
                  <tr key={it.seq} className="border-t border-border hover:bg-muted/40">
                    <td className={td}>
                      {/* `onChange` vacío a propósito: el que sabe del Shift es el
                          `onClick`, y React exige onChange en un input controlado. */}
                      <input type="checkbox" className="cursor-pointer"
                        aria-label={`Marcar línea ${i + 1}`}
                        checked={!destildadas.has(it.seq)}
                        onChange={() => {}}
                        onMouseDown={(e) => { if (e.shiftKey) e.preventDefault(); }}
                        onClick={(e) => alternar(i, it.seq, e.shiftKey)} />
                    </td>
                    <td className={`${td} tabular-nums`}>{it.item}</td>
                    <td className={`${td} max-w-[24rem]`}>{it.descripcion}</td>
                    <td className={td}>
                      {it.apu_codigo
                        ? <span>{it.apu_codigo} — {it.apu_nombre}</span>
                        : <span className="text-amber-700 font-semibold">— sin APU</span>}
                    </td>
                    <td className={`${td} text-right tabular-nums`}>
                      {cop(it.contractual_total)}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          </div>
        )}

        <div className="flex justify-end gap-2 pt-2">
          {/* Deshabilitado mientras aplica: cerrar no cancela el POST en vuelo. */}
          <Button size="sm" variant="outline" disabled={aplicando}
            onClick={onCerrar}>Cerrar</Button>
          <Button size="sm" disabled={marcados.length === 0 || aplicando}
            onClick={() => onAplicar(umbral, [...marcados].sort((a, b) => a - b))}>
            {aplicando
              ? "Aplicando…"
              : `Igualar ${marcados.length} ${
                  marcados.length === 1 ? "línea" : "líneas"}`}
          </Button>
        </div>
      </DialogContent>
    </Dialog>
  );
}
```

- [ ] **Step 4: Correr las pruebas para verificar que pasan**

Run: `cd web && npm test -- src/components/corrida/DialogoUmbralCosto.test.tsx`
Expected: PASS (5 tests)

- [ ] **Step 5: Commit**

```bash
git add web/src/components/corrida/DialogoUmbralCosto.tsx web/src/components/corrida/DialogoUmbralCosto.test.tsx
git commit -m "feat(web): dialogo del umbral con previa de impacto"
```

---

### Task 7: Cablear el diálogo en la página de la corrida

**Files:**
- Modify: `web/src/lib/tipos.ts` (`CorridaDetalle`, ~línea 431)
- Modify: `web/src/api/corridas.ts` (después de `igualarCostoAlContractual`, ~línea 116)
- Modify: `web/src/pages/Corrida.tsx` (imports; estado ~línea 89; función nueva; botón ~línea 418; montaje ~línea 577)

- [ ] **Step 1: Agregar los campos de respuesta al tipo**

En `web/src/lib/tipos.ts`, dentro de `CorridaDetalle`, junto a `rebusqueda`:

```ts
  /** Solo en la respuesta de aplicar una re-búsqueda. */
  rebusqueda?: { aplicadas: number[]; salteadas: number[] };
  /** Solo al igualar por umbral: los seq pedidos que ya no eran candidatos (les
   *  asignaron un APU, o cambiaron, entre la previa y el aplicar). */
  salteadas?: number[];
  /** Solo en la respuesta de `quitarCostoManual`. */
  quitadas?: number[];
```

- [ ] **Step 2: Agregar las dos llamadas a la API**

En `web/src/api/corridas.ts`, después de `igualarCostoAlContractual`:

```ts
/** Iguala al contractual las líneas en $0 cuyo TOTAL contractual no pase el umbral.
 *  `seqs` son las que el usuario dejó marcadas en la previa; el servidor recalcula
 *  la candidatura y devuelve en `salteadas` las que ya no correspondían. */
export function igualarPorUmbral(
  id: number,
  umbral: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/igualar-umbral`, {
    umbral_contractual: umbral,
    seqs,
  });
}

/** Borra el costo puesto a mano de las líneas marcadas: vuelven al costeo normal.
 *  Es el reverso de `igualarCostoAlContractual` y de `igualarPorUmbral`. */
export function quitarCostoManual(
  id: number,
  seqs: number[],
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/quitar-costo-manual`, { seqs });
}
```

- [ ] **Step 3: Cablear la página**

En `web/src/pages/Corrida.tsx`:

1. Import del diálogo, junto al de `DialogoRebuscar` (~línea 8):

```tsx
import DialogoUmbralCosto from "@/components/corrida/DialogoUmbralCosto";
```

2. Import de la API, en la lista que ya trae `rebuscarApus, aplicarRebusqueda` (~línea 12): agregá `igualarPorUmbral`.

3. Estado, junto a los de la re-búsqueda (~línea 89):

```tsx
  const [umbralAbierto, setUmbralAbierto] = useState(false);
  const [aplicandoUmbral, setAplicandoUmbral] = useState(false);
```

4. La función, junto a `aplicarRebusquedaMarcada`:

```tsx
  /** Aplica el umbral sobre las líneas marcadas en el diálogo; pinta con lo que
   *  devuelve el servidor (ya recosteado), sin volver a pedir la corrida. */
  async function aplicarUmbral(umbral: number, seqs: number[]) {
    if (aplicandoUmbral) return;      // cinturón contra el doble clic
    setAplicandoUmbral(true);
    try {
      const actualizada = await igualarPorUmbral(corridaId, umbral, seqs);
      if (montado.current) {
        setCorrida(actualizada);
        setUmbralAbierto(false);
      }
      const n = actualizada.igualadas?.length ?? 0;
      toast.success(n === 1
        ? "1 línea igualada al contractual"
        : `${n} líneas igualadas al contractual`);
      const salteadas = actualizada.salteadas ?? [];
      if (salteadas.length > 0) {
        // Nada silencioso: si no se tocó una fila, se dice por qué.
        toast.warning(
          `${salteadas.length} sin tocar: cambiaron desde que abriste el diálogo `
          + "(ya tienen APU o costo).");
      }
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudo igualar por umbral.");
    } finally {
      if (montado.current) setAplicandoUmbral(false);
    }
  }
```

5. El botón, justo después del de `Volver a buscar APU` (~línea 427), con la misma
   condición: con el plan a medias las filas que faltan no existen y el porcentaje
   mentiría.

```tsx
          {puedeEditar && !esActivar && !planAMedias && (
            <Button size="sm" variant="outline"
              title={"Iguala al contractual las actividades en $0 cuyo total "
                + "contractual no pase el umbral que pongas. Para priorizar: lo "
                + "chico se iguala, lo grande lo armas vos."}
              onClick={() => setUmbralAbierto(true)}>
              Igualar bajo umbral…
            </Button>
          )}
```

6. El montaje, después del bloque de `DialogoRebuscar` (~línea 585):

```tsx
      {umbralAbierto && (
        <DialogoUmbralCosto
          abierto
          items={data.items}
          aplicando={aplicandoUmbral}
          onAplicar={aplicarUmbral}
          onCerrar={() => setUmbralAbierto(false)}
        />
      )}
```

- [ ] **Step 4: Agregar el export nuevo a los mocks de `@/api/corridas`**

Los tests mockean ese módulo con **factory**, así que un import que la factory no
tenga revienta al cargar el módulo (`No "igualarPorUmbral" export is defined on the
mock`). Agregá esta entrada al objeto de `vi.mock("@/api/corridas", () => ({ … }))`
en los tres archivos que montan `Corrida.tsx`:

- `web/src/pages/Corrida.test.tsx`
- `web/src/pages/Corrida.armado.test.tsx`
- `web/src/pages/Corrida.rebuscar.test.tsx`

```ts
  igualarPorUmbral: vi.fn(async () => CORRIDA),
```

(en el archivo que no tenga una constante `CORRIDA`, usá el mismo objeto de respuesta
que ya usan sus vecinos `aplicarSugerencias` / `aplicarRebusqueda`).

- [ ] **Step 5: Verificar que compila y que la suite web sigue verde**

Run: `cd web && npm run build && npm test`
Expected: build OK (`tsc -b` sin errores) y todos los tests en PASS. Si vitest se
queja de un export faltante en otro archivo, agregale la misma entrada a esa factory.

- [ ] **Step 6: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/corridas.ts web/src/pages/Corrida.tsx web/src/pages/Corrida.test.tsx web/src/pages/Corrida.armado.test.tsx web/src/pages/Corrida.rebuscar.test.tsx
git commit -m "feat(web): boton Igualar bajo umbral en la barra de la corrida"
```

---

### Task 8: `Quitar costo a mano` en la barra de selección

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx` (import ~línea 22; función junto a `igualarAlContractual` ~línea 291; botón en la barra ~línea 643)
- Test: `web/src/components/corrida/TablaItems.test.tsx`

- [ ] **Step 1: Escribir la prueba que falla**

Primero sumá la entrada al `vi.mock("@/api/corridas", () => ({ … }))` del principio de
`web/src/components/corrida/TablaItems.test.tsx`, junto a `igualarCostoAlContractual`
(la factory reemplaza el módulo entero: sin esto el import revienta):

```ts
  quitarCostoManual: vi.fn(async () => ({
    id: 1, archivo: "x", estado: "en_revision", modo: "activa", items: [], duracion_ms: null,
    totales: { contractual: 0, costo: 0, margen: 0, margen_pct: 0, n_items: 0, n_revision: 0 },
    quitadas: [0],
  })),
```

Y agregá los casos al final del archivo, con los helpers que ya viven ahí
(`TablaConControl`, `itemsCuatro`, y las casillas con `aria-label` "Marcar ítem N"):

```tsx
// ─── Quitar el costo puesto a mano ──────────────────────────────────────────

test("sin filas con costo a mano no aparece el botón de quitar", async () => {
  render(<TablaConControl items={itemsCuatro()} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  // La barra sí aparece; el botón de quitar no, porque no hay nada que deshacer.
  expect(await screen.findByText(/Igualar costo al contractual/i)).toBeTruthy();
  expect(screen.queryByText(/Quitar costo a mano/i)).toBeNull();
});

test("quitar manda solo los seqs marcados que tienen costo a mano", async () => {
  const { quitarCostoManual } = await import("@/api/corridas");
  const items = itemsCuatro();
  items[0] = { ...items[0], costo_manual: true };    // seq 0
  items[1] = { ...items[1], costo_manual: true };    // seq 1, NO se marca
  render(<TablaConControl items={items} puedeEditar />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));   // seq 0, con costo a mano
  fireEvent.click(screen.getByLabelText("Marcar ítem 3"));   // seq 2, sin costo a mano
  fireEvent.click(await screen.findByText(/Quitar costo a mano/i));
  await waitFor(() => expect(quitarCostoManual).toHaveBeenCalledWith(1, [0]));
});

test("sin permiso de editor no hay botón de quitar", async () => {
  const items = itemsCuatro();
  items[0] = { ...items[0], costo_manual: true };
  render(<TablaConControl items={items} puedeEditar={false} />);
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  expect(await screen.findByText(/Confirmar el APU actual/i)).toBeTruthy();
  expect(screen.queryByText(/Quitar costo a mano/i)).toBeNull();
});
```

- [ ] **Step 2: Correr la prueba para verificar que falla**

Run: `cd web && npm test -- src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — no existe ningún botón `Quitar costo a mano`

- [ ] **Step 3: Implementar**

En `web/src/components/corrida/TablaItems.tsx`:

1. Sumá `quitarCostoManual` al import de `@/api/corridas` (~línea 22).

2. Junto a `igualarAlContractual`:

```tsx
  /** Deshace el costo puesto a mano: las filas vuelven a costear desde su APU (o a
   *  quedar en $0 sin APU, que es la verdad y vuelve a trabar el cuadro). */
  async function quitarCostoAMano() {
    if (conCostoAMano.length === 0) return;
    setEnLote(true);
    try {
      const actualizada = await quitarCostoManual(corridaId, conCostoAMano);
      onConfirmado(actualizada);
      limpiarSeleccion();
      const n = actualizada.quitadas?.length ?? conCostoAMano.length;
      toast.success(`${n} ${n === 1 ? "línea devuelta" : "líneas devueltas"} al costeo normal`);
    } catch (e) {
      // La selección NO se limpia: el usuario puede reintentar sin volver a marcar.
      toast.error(e instanceof Error ? e.message : "No se pudo quitar el costo a mano.");
    } finally {
      setEnLote(false);
    }
  }
```

3. La lista derivada, junto a `seleccionadas` (~línea 115):

```tsx
  // Solo las marcadas que de verdad tienen costo a mano: el botón no se ofrece
  // cuando no hay nada que deshacer.
  const conCostoAMano = visible
    .filter((it) => marcadas.has(it.seq) && it.costo_manual)
    .map((it) => it.seq);
```

4. El botón, en la barra de selección, después del de `Igualar costo al contractual`:

```tsx
          {puedeEditar && conCostoAMano.length > 0 && (
            <Button size="xs" variant="outline" disabled={enLote}
                    onClick={quitarCostoAMano}
                    title={"Borra el costo que se puso a mano: las líneas vuelven a "
                      + "costear desde su APU. Las que no tengan APU vuelven a $0."}>
              {enLote ? "Aplicando…" : `Quitar costo a mano (${conCostoAMano.length})`}
            </Button>
          )}
```

- [ ] **Step 4: Agregar `quitarCostoManual` a las otras factories que montan la tabla**

Misma razón que en la tarea anterior: la factory reemplaza el módulo entero. Los
archivos que montan `TablaItems` (directo o dentro de `Corrida.tsx`) son:

- `web/src/components/corrida/TablaItems.composicion.test.tsx`
- `web/src/pages/Corrida.test.tsx`
- `web/src/pages/Corrida.armado.test.tsx`
- `web/src/pages/Corrida.rebuscar.test.tsx`

```ts
  quitarCostoManual: vi.fn(async () => CORRIDA),
```

(usá el objeto de respuesta que ya usan sus vecinos en cada archivo).

- [ ] **Step 5: Correr la suite web entera para verificar que pasa**

Run: `cd web && npm test`
Expected: PASS. Si vitest se queja de un export faltante en otro archivo, agregale la
misma entrada a esa factory.

- [ ] **Step 6: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx web/src/components/corrida/TablaItems.composicion.test.tsx web/src/pages/Corrida.test.tsx web/src/pages/Corrida.armado.test.tsx web/src/pages/Corrida.rebuscar.test.tsx
git commit -m "feat(web): boton para quitar el costo puesto a mano"
```

---

### Task 9: Documentar en `CLAUDE.md` y cerrar

**Files:**
- Modify: `CLAUDE.md` (sección **Costo puesto a mano** en "Datos"; sección **No hacer**)

- [ ] **Step 1: Ampliar la sección «Costo puesto a mano»**

Agregá al final de ese párrafo, antes de la línea del endpoint:

```
  Además del botón por selección, un **umbral** lo hace en lote: `POST
  /api/corridas/{id}/igualar-umbral` (rol `editor`) iguala las filas **en $0**
  —sin APU, o con APU pero sin precios— cuyo `contractual_total` no pase el techo
  que el usuario ponga. Sirve para priorizar: en 1939 actividades, un puñado se
  lleva casi todo el presupuesto. La **previa la calcula el frontend**
  (`web/src/lib/umbralCosto.ts`) sobre los ítems que ya tiene, pero el aplicar
  **recalcula la candidatura en el servidor** y devuelve en `salteadas` lo que
  cambió desde la previa: el cliente dice cuáles quiere, no qué se escribe. El
  reverso es `POST /api/corridas/{id}/quitar-costo-manual` (rol `editor`), que
  borra el `costo_manual` y devuelve la fila a `new` si no tiene APU o a `review`
  si lo tiene — no se guarda el status previo, y `review` es la verdad honesta en
  vez de adivinar un `auto`.
```

Y actualizá los endpoints del final de ese párrafo para que nombren los tres.

- [ ] **Step 2: Agregar las reglas a «No hacer»**

```
- No dejes que el cliente dicte qué filas iguala el umbral. `igualar_por_umbral`
  **recalcula** la candidatura (`_candidata_umbral` + el techo) sobre una vista
  fresca y saltea lo que cambió: es el mismo candado que `apu_evaluado` y que
  `rebuscar/aplicar`. Sin él, una pestaña vieja pisa un APU recién asignado con una
  copia del contractual y encima deja la fila `confirmed`, o sea fuera del alcance de
  volver a buscar APU. Con diez filas eso se ve; con mil quinientas no.
- No hagas que el umbral mire los filtros de la tabla. El techo es una decisión de
  presupuesto, no de vista: el diálogo trabaja sobre la corrida entera a propósito.
- No llames `umbral` a secas al campo del techo. Es dinero y va en `_FORBIDDEN_KEYS`
  como `umbral_contractual`; `umbral` chocaría con los umbrales de matching, que no
  son dinero, y un falso positivo ahí volaría un payload legítimo hacia la IA.
```

- [ ] **Step 3: Correr la suite completa**

Run: `python -m pytest tests/ -q`
Expected: PASS, sin regresiones

Run: `cd web && npm test && npm run build`
Expected: PASS y build OK

- [ ] **Step 4: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: el umbral de igualacion y el reverso del costo a mano"
```

- [ ] **Step 5: Smoke en el navegador**

Levantá la app en local (`python scripts/servidor_local.py` o la receta de
`web-local-auth-receta`, que necesita `SUPABASE_URL` y `APU_ADMIN_EMAILS` o el login
rebota con 401) y comprobá a mano, sobre una corrida con líneas sin APU:

1. `Igualar bajo umbral…` aparece en la barra y no aparece con la corrida congelada
   ni mientras se está armando.
2. Escribir el techo actualiza los conteos, las sumas y los porcentajes en vivo.
3. Aplicar deja las filas con el badge de costo a mano, margen 0 y status `confirmed`.
4. Marcar esas filas y `Quitar costo a mano` las devuelve a $0 (o al costo de su APU).
5. Emitir el cuadro: las filas igualadas salen en la hoja ALERTAS con «costo puesto a
   mano».

**No hagas push a master sin el OK explícito del usuario:** master auto-despliega.

---

## Notas para quien ejecute

- **El español del dominio y de los mensajes de usuario es obligatorio** (convención
  del repo). Los comentarios también van en español.
- **La frontera de privacidad no se toca**: nada de este trabajo manda payloads a la
  IA. Si en algún momento agregás un campo monetario, va a `_FORBIDDEN_KEYS`.
- **No inventes un estado de corrida nuevo.** El usuario lo descartó explícitamente:
  se escribe el `costo_manual` que ya existe.
- **Las pruebas de Postgres** solo corren con `TEST_DATABASE_URL` apuntando a una base
  desechable. NUNCA a producción: esos tests hacen `DROP SCHEMA`.
