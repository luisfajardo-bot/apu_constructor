> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-05-asignar-apu-en-lote.md`

# Asignar / confirmar APU en lote — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Marcar varias líneas de una corrida y asignarles el mismo APU —o confirmar el que ya tienen— de un tirón, en lugar de expandir fila por fila.

**Architecture:** La primitiva del backend pasa a ser la de lote (`confirmar_items`) y `confirmar_item` queda como wrapper de una línea: un `Assembler` compartido y **un** recosteo de la corrida al final, en vez de N. En el frontend, la tabla de la corrida gana una columna de checkbox con rango por Shift y una barra de acciones que aparece cuando hay líneas marcadas.

**Tech Stack:** Python 3 + FastAPI + SQLite/Postgres · React + TypeScript + vitest · pytest.

Spec: `docs/superpowers/specs/2026-08-05-asignar-apu-en-lote-design.md`
Rama: `feat/asignar-apu-en-lote` (ya creada; el spec está commiteado en `b0c9637`).

## Global Constraints

- **Invariante #1:** la IA nunca ve dinero. El camino de confirmar usa `ApuAdvisor(enabled=False)` y no debe cambiar; no agregar nada a payloads de `dominio/ai_assist.py`.
- **Regla de negocio "nada en $0":** ningún ítem puede quedar costeado en $0 en silencio. Es la razón de la validación del APU en la Task 1, no un extra.
- **Toda la persistencia vive en `apu_tool/datos/`.** Nada de SQL crudo fuera de esa capa.
- **No dupliques lógica de orquestación:** reusala desde `pipeline.py` / `servicio/corridas.py`. En particular, `confirmar_item` y el lote deben compartir un solo camino.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias nuevas.**
- El frontend se verifica con `npm run build` (que corre `tsc -b`), **no** con `tsc --noEmit`.
- Ningún test existente debe cambiar de comportamiento. Agregar tests nuevos sí. Si un test existente empieza a fallar, **pará y reportá** en vez de ajustarlo (ver la nota de la Task 1 sobre el hueco del $0).
- La corrida congelada es de solo lectura: el lote respeta `CorridaCongelada` igual que el confirmar de un ítem.

## Estructura de archivos

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `apu_tool/servicio/corridas.py` | `confirmar_items` (primitiva) + `confirmar_item` (wrapper) | modificar |
| `apu_tool/servicio/esquemas.py` | `ConfirmarLoteIn` | modificar |
| `apu_tool/servicio/rutas.py` | `POST /corridas/{cid}/items/confirmar-lote` | modificar |
| `tests/test_corridas_confirmar_lote.py` | lote: asignar, confirmar-actual, congelada, APU inexistente, seq inexistente | crear |
| `web/src/api/corridas.ts` | `confirmarLote(...)` | modificar |
| `web/src/components/corrida/TablaItems.tsx` | selección (checkbox + Shift) y barra de acciones | modificar |
| `web/src/components/corrida/CabeceraFiltros.tsx` | una celda vacía más, para alinear la columna | modificar |
| `web/src/components/corrida/TablaItems.test.tsx` | selección y acciones en lote | modificar |

---

### Task 1: La primitiva de lote en el backend

**Files:**
- Modify: `apu_tool/servicio/corridas.py:319-337` (`confirmar_item`)
- Modify: `apu_tool/servicio/esquemas.py:15-17` (junto a `ConfirmarIn`)
- Modify: `apu_tool/servicio/rutas.py:266-277` (junto al endpoint `confirmar`)
- Test: `tests/test_corridas_confirmar_lote.py` (crear)

**Interfaces:**
- Produces:
  - `svc.confirmar_items(alm, corrida_id, seqs, apu_codigo=None, shift=None) -> Optional[dict]` — confirma varios ítems en UN recosteo; devuelve la vista de la corrida (misma forma que `confirmar_item`), `None` si la corrida no existe. Lanza `CorridaCongelada` (→409) y `ValueError` (→400).
  - `POST /api/corridas/{cid}/items/confirmar-lote` con cuerpo `{seqs: int[], apu_codigo?: str, shift?: str}` → la vista de la corrida. Lo consume la Task 3.
- `confirmar_item` conserva su firma actual: es un wrapper, y los llamadores existentes no cambian.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_corridas_confirmar_lote.py`. El armado de la corrida es el patrón de `tests/test_nombre_corridas.py:54-67` (que construye una corrida real con `svc.construir_corrida`), extendido a 3 ítems y 2 APUs:

```python
"""Confirmar/asignar APU en lote: un recosteo para N ítems."""
import pytest

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu, ApuComponent, Insumo, LicitacionItem
from apu_tool.servicio import corridas as svc


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("100", "CEMENTO", "KG", "MAT", 1000.0, "PRECIO IDU")])
    alm.apus.crear_apu(Apu("A1", "MURO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A1", "DIURNO", "100", "CEMENTO", "KG", 2.0, 0.0)])
    alm.apus.crear_apu(Apu("A2", "MURO REFORZADO", "M2", "DIURNO", "ESTR"),
                       [ApuComponent("A2", "DIURNO", "100", "CEMENTO", "KG", 3.0, 0.0)])
    return alm, alm.carpetas.crear("Obra")


def _corrida(alm, sc, n=3):
    items = [LicitacionItem(item=str(i + 1), descripcion="muro", unidad="M2",
                            cantidad=1.0, precio_contractual=10000.0, shift="DIURNO")
             for i in range(n)]
    return svc.construir_corrida(alm, "lic.xlsx", items, "DIURNO", False, carpeta_id=sc)


def _estado(alm, cid):
    return {r.seq: (r.status, r.apu_codigo) for r in alm.corridas.get_items(cid)}


def test_asignar_un_apu_a_varios_seqs(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    v = svc.confirmar_items(alm, cid, [0, 1, 2], apu_codigo="A2", shift="DIURNO")
    assert v is not None
    assert _estado(alm, cid) == {0: ("confirmed", "A2"), 1: ("confirmed", "A2"),
                                 2: ("confirmed", "A2")}
    # una sola vista, coherente con lo persistido
    assert {it["apu_codigo"] for it in v["items"]} == {"A2"}
    assert v["totales"]["n_items"] == 3


def test_asignar_solo_toca_los_seqs_pedidos(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    antes = _estado(alm, cid)
    svc.confirmar_items(alm, cid, [1], apu_codigo="A2", shift="DIURNO")
    despues = _estado(alm, cid)
    assert despues[1] == ("confirmed", "A2")
    assert despues[0] == antes[0] and despues[2] == antes[2]


def test_sin_apu_codigo_confirma_el_que_ya_tiene(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    previos = {seq: cod for seq, (_, cod) in _estado(alm, cid).items()}
    svc.confirmar_items(alm, cid, [0, 1, 2])            # sin apu_codigo
    for seq, (status, cod) in _estado(alm, cid).items():
        assert status == "confirmed"
        assert cod == previos[seq]                       # no se reasignó nada


def test_apu_inexistente_no_toca_nada(tmp_path):
    """Sin esto el ítem queda con composición vacía y costeado en $0
    (regla de negocio: nada en $0 en silencio)."""
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    antes = _estado(alm, cid)
    with pytest.raises(ValueError):
        svc.confirmar_items(alm, cid, [0, 1, 2], apu_codigo="NOEXISTE", shift="DIURNO")
    assert _estado(alm, cid) == antes


def test_sin_shift_cae_al_turno_de_la_fila(tmp_path):
    """Confirmar sin turno es un camino real (el botón "Elegir" de los candidatos y
    "Confirmar APU actual" llaman sin él), así que NO puede ser un error."""
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    v = svc.confirmar_items(alm, cid, [0], apu_codigo="A2")      # sin shift
    assert v is not None
    assert _estado(alm, cid)[0] == ("confirmed", "A2")


def test_seq_inexistente_se_saltea(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    svc.confirmar_items(alm, cid, [0, 999], apu_codigo="A2", shift="DIURNO")
    est = _estado(alm, cid)
    assert est[0] == ("confirmed", "A2") and 999 not in est


def test_lista_vacia_no_hace_nada_y_devuelve_la_vista(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    antes = _estado(alm, cid)
    v = svc.confirmar_items(alm, cid, [])
    assert v is not None and _estado(alm, cid) == antes


def test_corrida_inexistente_devuelve_none(tmp_path):
    alm, _ = _alm(tmp_path)
    assert svc.confirmar_items(alm, 999, [0], apu_codigo="A1", shift="DIURNO") is None


def test_corrida_congelada_rechaza_el_lote(tmp_path):
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    svc.congelar(alm, cid)
    with pytest.raises(svc.CorridaCongelada):
        svc.confirmar_items(alm, cid, [0], apu_codigo="A2", shift="DIURNO")


def test_confirmar_item_sigue_funcionando_igual(tmp_path):
    """El wrapper de 1 seq no cambia de comportamiento."""
    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    v = svc.confirmar_item(alm, cid, 1, "A2", "DIURNO")
    assert v is not None
    assert _estado(alm, cid)[1] == ("confirmed", "A2")
```

Y el test del endpoint, en el mismo archivo. El cliente es el patrón de `tests/test_api_corridas.py:14-23`:

```python
def test_endpoint_confirmar_lote(tmp_path):
    from apu_tool.servicio.app import create_app
    from tests.conftest import cliente

    alm, sc = _alm(tmp_path)
    cid = _corrida(alm, sc)
    cli = cliente(create_app(almacen=alm), rol="admin")
    r = cli.post(f"/api/corridas/{cid}/items/confirmar-lote",
                 json={"seqs": [0, 2], "apu_codigo": "A2", "shift": "DIURNO"})
    assert r.status_code == 200, r.text
    est = _estado(alm, cid)
    assert est[0] == ("confirmed", "A2") and est[2] == ("confirmed", "A2")
    # APU inexistente -> 400, nada cambia
    assert cli.post(f"/api/corridas/{cid}/items/confirmar-lote",
                    json={"seqs": [1], "apu_codigo": "NOPE", "shift": "DIURNO"}
                    ).status_code == 400
    # corrida inexistente -> 404
    assert cli.post("/api/corridas/999/items/confirmar-lote",
                    json={"seqs": [0]}).status_code == 404
    # congelada -> 409
    svc.congelar(alm, cid)
    assert cli.post(f"/api/corridas/{cid}/items/confirmar-lote",
                    json={"seqs": [1], "apu_codigo": "A2", "shift": "DIURNO"}
                    ).status_code == 409
```

Nota: `MatchStatus.CONFIRMED.value` es el string que queda en `status`; los tests de arriba asumen `"confirmed"`. Si el valor real difiere, ajustá los tests al valor real (no al revés) y anotalo.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_corridas_confirmar_lote.py -q`
Expected: FAIL con `AttributeError: module 'apu_tool.servicio.corridas' has no attribute 'confirmar_items'`

- [ ] **Step 3: Escribir `confirmar_items` y convertir `confirmar_item` en wrapper**

Reemplazar `confirmar_item` (`apu_tool/servicio/corridas.py:319-337`) por:

```python
def confirmar_items(alm: Almacen, corrida_id: int, seqs: Iterable[int],
                    apu_codigo: Optional[str] = None,
                    shift: Optional[str] = None) -> Optional[dict]:
    """Confirma varios ítems de una corrida en UN solo recosteo.

    `apu_codigo=None` confirma el APU que cada ítem ya tiene (sin reasignar);
    con `apu_codigo` se le asigna ese APU (codigo+turno) a todos los seqs.
    Devuelve la vista de la corrida, o None si la corrida no existe.

    Es la primitiva: `confirmar_item` es el caso de un solo seq. Un solo
    Assembler para todo el lote (su PricingEngine cachea, y el camino de
    confirmar no toca matcher/retriever, que son perezosos), y un solo
    vista_corrida al final en vez de uno por ítem.
    """
    meta = alm.corridas.get_corrida(corrida_id)
    if meta is None:
        return None
    if meta.modo == "congelada":
        raise CorridaCongelada(corrida_id)
    assembler = Assembler(alm, advisor=ApuAdvisor(enabled=False),
                          lista_id=meta.lista_precios_id)
    # Dos pasadas. La primera resuelve (fila, código, turno) y valida que el APU
    # exista, SIN escribir: con un código que no existe, reassemble_with_choice
    # produce una composición vacía y el ítem queda costeado en $0 (regla de
    # negocio: nada en $0 en silencio). Validando antes, un código inválido falla
    # sin dejar el lote a medio aplicar.
    # El turno se resuelve POR FILA (`shift or row.shift`): confirmar sin turno es
    # un camino real y usado — el botón "Elegir" de los candidatos y "Confirmar APU
    # actual" llaman sin él —, así que no se puede exigir.
    trabajo: list[tuple[int, object, str, str]] = []
    validados: set[tuple[str, str]] = set()
    for seq in seqs:
        row = alm.corridas.get_item(corrida_id, seq)
        if row is None:
            continue                      # seq ajeno a la corrida: se saltea
        codigo = apu_codigo or row.apu_codigo
        if not codigo:
            continue                      # nada que confirmar (evita el $0)
        turno = shift or row.shift
        if (codigo, turno) not in validados:
            if alm.apus.get_apu(codigo, turno) is None:
                raise ValueError(f"No existe el APU {codigo} ({turno}).")
            validados.add((codigo, turno))   # una consulta por par distinto, no por fila
        trabajo.append((seq, row, codigo, turno))
    for seq, row, codigo, turno in trabajo:
        ens = assembler.reassemble_with_choice(row.item, codigo, turno)
        alm.corridas.actualizar_eleccion(
            corrida_id, seq, status=MatchStatus.CONFIRMED.value, apu_codigo=ens.apu_codigo,
            apu_nombre=ens.apu_nombre, unidad=ens.unidad, shift=ens.shift, origen=ens.origen,
            confianza=ens.confianza, explicacion=ens.explicacion,
            componentes=_estructura(ens.componentes))
    return vista_corrida(alm, corrida_id)


def confirmar_item(alm: Almacen, corrida_id: int, seq: int, apu_codigo: str,
                   shift: Optional[str] = None) -> Optional[dict]:
    """Un solo ítem. Wrapper sobre `confirmar_items` para que confirmar-uno y
    confirmar-muchos no se puedan separar con el tiempo."""
    return confirmar_items(alm, corrida_id, [seq], apu_codigo, shift or None)
```

Dos detalles:

- `Iterable` tiene que estar en el import de `typing` del módulo; verificá qué se importa ahí arriba y sumalo si falta.
- **Los llamadores sin turno ya están relevados**, no hace falta que los busques: `rutas.py:271` pasa `body.shift`, que es `Optional[str] = None`; en el frontend el botón "Elegir" de un candidato (`TablaItems.tsx:406`) y "Confirmar APU actual" (`:510`) llaman sin turno; y `tests/test_servicio_corridas.py:60` hace `confirmar_item(alm, cid, 0, apu_codigo="A2")` sin turno. Por eso el turno se resuelve por fila y **no** se exige. Ese test existente sigue pasando (el APU `A2` existe en el turno de la fila).

- [ ] **Step 4: Correr los tests de servicio y verificar que pasan**

Run: `python -m pytest tests/test_corridas_confirmar_lote.py -q -k "not endpoint"`
Expected: PASS

- [ ] **Step 5: El DTO y el endpoint**

En `apu_tool/servicio/esquemas.py`, junto a `ConfirmarIn` (línea 15):

```python
class ConfirmarLoteIn(BaseModel):
    seqs: list[int]
    apu_codigo: Optional[str] = None
    shift: Optional[str] = None
```

En `apu_tool/servicio/rutas.py`, junto al endpoint `confirmar` (línea 266), y sumando `ConfirmarLoteIn` al import de `esquemas`:

```python
@router.post("/corridas/{cid}/items/confirmar-lote")
def confirmar_lote(cid: int, body: ConfirmarLoteIn,
                   alm: Almacen = Depends(get_almacen),
                   _: object = Depends(requiere_rol("consulta"))):
    try:
        v = svc.confirmar_items(alm, cid, body.seqs, body.apu_codigo, body.shift)
    except svc.CorridaCongelada:
        raise HTTPException(status_code=409,
                            detail="La corrida está congelada; actívala para modificar.")
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    if v is None:
        raise HTTPException(status_code=404, detail="Corrida no encontrada.")
    return v
```

`requiere_rol("consulta")` es el mismo guard que usa el `confirmar` de un ítem — se mantiene por consistencia con el endpoint hermano.

La ruta no debería colisionar con `/corridas/{cid}/items/{seq}/confirmar` (3 segmentos después de `cid`, contra 2 acá) ni con `GET /corridas/{cid}/items/{seq}` (otro método). **Verificalo** con el test del endpoint del Step 1: si `confirmar-lote` se estuviera matcheando como `{seq}`, el POST daría 422 en vez de 200.

- [ ] **Step 6: Correr el archivo completo + la suite**

Run: `python -m pytest tests/test_corridas_confirmar_lote.py -q` y después `python -m pytest tests/ -q`
Expected: todo verde.

Ojo con un caso: si algún test existente confirmaba un APU inexistente y esperaba que pasara (aprovechando el hueco del $0 que esta tarea cierra), ahora va a fallar. **No lo ajustes en silencio:** reportá cuál es y qué comportamiento asumía.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/servicio/corridas.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_corridas_confirmar_lote.py
git commit -m "feat(api): confirmar/asignar APU en lote con un solo recosteo"
```

---

### Task 2: Selección de líneas en la tabla de la corrida

**Files:**
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Modify: `web/src/components/corrida/CabeceraFiltros.tsx:55` y `:71` (una celda vacía más en cada fila de cabecera)
- Test: `web/src/components/corrida/TablaItems.test.tsx`

**Interfaces:**
- Produces: en `TablaItems`, el estado `marcadas: Set<number>` (seqs) y el derivado `seleccionadas: number[]` (la intersección de `marcadas` con los seqs visibles, en el orden en que se ven). Los consume la Task 3.

- [ ] **Step 1: Escribir los tests que fallan**

En `web/src/components/corrida/TablaItems.test.tsx`. **Leé primero el archivo** para reusar su helper de items y su forma de renderizar (ya monta `TablaItems` con y sin `control`); estos tests necesitan al menos 4 ítems y un `control` real (usá `useCorridaTabla` a través de un componente envoltorio, o el mismo mecanismo que ya usen los tests de filtros si existe).

```tsx
test("el checkbox de una fila la marca y muestra el contador", async () => {
  // render con 4 ítems y control
  fireEvent.click(screen.getByLabelText("Marcar ítem 2"));
  expect(await screen.findByText(/1 línea marcada/i)).toBeTruthy();
});

test("Shift+click marca el rango visible", async () => {
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 4"), { shiftKey: true });
  expect(await screen.findByText(/4 líneas marcadas/i)).toBeTruthy();
});

test("marcar todo usa solo lo que dejó pasar el filtro", async () => {
  // filtrar por descripción para dejar 2 de 4 visibles, después marcar todo
  fireEvent.click(screen.getByLabelText(/Marcar todas las líneas/i));
  expect(await screen.findByText(/2 líneas marcadas/i)).toBeTruthy();
});

test("cambiar el filtro no arrastra al lote las filas que dejaron de verse", async () => {
  fireEvent.click(screen.getByLabelText(/Marcar todas las líneas/i));   // 4
  // filtrar para dejar 1 visible
  expect(await screen.findByText(/1 línea marcada/i)).toBeTruthy();
});

test("con readOnly no hay checkboxes", async () => {
  // render con readOnly
  expect(screen.queryByLabelText(/Marcar todas las líneas/i)).toBeNull();
});
```

Los `aria-label` de arriba (`Marcar ítem <item>`, `Marcar todas las líneas`) son el contrato con el DOM: usá exactamente esos en la implementación.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — no existe ningún checkbox de selección.

- [ ] **Step 3: El estado de selección**

En `TablaItems.tsx`, junto a los otros `useState` (alrededor de la línea 48):

```ts
  // Selección para las acciones en lote. Guarda seqs, no índices: la tabla se
  // reordena y se filtra, y un índice dejaría de apuntar a la misma fila.
  const [marcadas, setMarcadas] = useState<Set<number>>(new Set());
  // Índice (dentro de `visible`) del último click sin Shift, para el rango.
  // Va en un ref: lo lee el handler del click siguiente, no el render.
  const ultimoIdxRef = useRef<number | null>(null);
```

Y el derivado, después de `visible`:

```ts
  // Solo se actúa sobre lo que se está viendo: si el usuario marca filas y después
  // cambia el filtro, las que se fueron no se tocan (y el contador no las cuenta).
  const seleccionadas = visible.filter((it) => marcadas.has(it.seq)).map((it) => it.seq);
  const haySeleccion = seleccionadas.length > 0;
  // La selección solo existe con `control` (no en el armado en vivo, cuya tabla
  // viene del stream) y con la corrida activa.
  const seleccionable = control !== undefined && !readOnly;
```

Handlers:

```ts
  function alternar(idx: number, seq: number, conShift: boolean) {
    const desde = ultimoIdxRef.current;
    if (conShift && desde !== null) {
      const [a, b] = desde <= idx ? [desde, idx] : [idx, desde];
      const rango = visible.slice(a, b + 1).map((it) => it.seq);
      setMarcadas((prev) => new Set([...prev, ...rango]));
      return;                                  // el ancla del rango no se mueve
    }
    ultimoIdxRef.current = idx;
    setMarcadas((prev) => {
      const s = new Set(prev);
      if (s.has(seq)) s.delete(seq); else s.add(seq);
      return s;
    });
  }

  function marcarTodas(marcar: boolean) {
    ultimoIdxRef.current = null;
    setMarcadas((prev) => {
      const s = new Set(prev);
      for (const it of visible) { if (marcar) s.add(it.seq); else s.delete(it.seq); }
      return s;
    });
  }

  function limpiarSeleccion() {
    ultimoIdxRef.current = null;
    setMarcadas(new Set());
  }
```

- [ ] **Step 4: La columna de checkbox**

`TOTAL_COLS` (línea 150) deja de ser una constante, porque lo usa el `colSpan` de la fila expandida:

```ts
  // 1 chevron + 12 columnas de datos, más la de selección cuando está activa.
  const TOTAL_COLS = 13 + (seleccionable ? 1 : 0);
```

En el `<TableBody>`, como **primera** celda de cada fila de datos (antes de la del chevron), y solo si `seleccionable`. El `.map` necesita el índice: cambiá `visible.map((it) =>` por `visible.map((it, idx) =>`.

```tsx
                  {seleccionable && (
                    <TableCell className="w-8 px-1 py-1">
                      <input
                        type="checkbox"
                        className="cursor-pointer"
                        aria-label={`Marcar ítem ${it.item}`}
                        checked={marcadas.has(it.seq)}
                        onChange={() => {}}
                        onClick={(e) => alternar(idx, it.seq, e.shiftKey)}
                      />
                    </TableCell>
                  )}
```

El `onClick` (no `onChange`) es lo que da acceso a `e.shiftKey`; el `onChange` vacío evita la advertencia de React por un checkbox controlado sin handler de cambio.

La fila de "No hay ítems" y la fila expandida ya usan `colSpan={TOTAL_COLS}`, así que se ajustan solas.

- [ ] **Step 5: Alinear las cabeceras**

Dos cabeceras dibujan esta tabla y las dos necesitan la celda extra, o las columnas quedan corridas:

1. `CabeceraFiltros.tsx` — agregar `<TableHead className="w-8 px-1" />` **antes** del `<TableHead className="w-6 px-1" />` de cada una de sus **dos** `<TableRow>` (líneas 55 y 71). Como el componente hoy solo recibe `control`, sumale una prop `conSeleccion?: boolean` (default `false`) y renderizá la celda solo si es `true`; `TablaItems` le pasa `seleccionable`.
2. `TablaItems.tsx` — la cabecera de respaldo (la del `else`, líneas 186-202) es la del modo vivo, donde `seleccionable` es `false`. No hace falta tocarla, pero **verificá** que efectivamente nunca se muestre con selección activa.

- [ ] **Step 6: El contador y "marcar todas"**

En la barra de filtros de arriba (donde ya viven "Solo revisión" y "Limpiar filtros", líneas 154-179), agregar cuando `seleccionable`:

```tsx
        {seleccionable && (
          <label className="flex items-center gap-1.5 cursor-pointer select-none text-xs text-muted-foreground">
            <input
              type="checkbox"
              className="cursor-pointer"
              aria-label="Marcar todas las líneas visibles"
              checked={visible.length > 0 && seleccionadas.length === visible.length}
              onChange={(e) => marcarTodas(e.target.checked)}
            />
            Marcar todas
          </label>
        )}
        {haySeleccion && (
          <span className="text-xs font-medium text-foreground">
            {seleccionadas.length === 1
              ? "1 línea marcada"
              : `${seleccionadas.length} líneas marcadas`}
          </span>
        )}
```

El "marcar todo" va en esta barra y no en la cabecera de la tabla a propósito: la cabecera se quedaría con una celda vacía y `CabeceraFiltros` no necesita conocer la selección más allá de un booleano de layout. Esta barra ya es donde viven los toggles de toda la tabla.

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS

- [ ] **Step 8: Suite de frontend + build**

Run: `cd web && npx vitest run` y después `cd web && npm run build`
Expected: todo verde. Prestá atención a los tests de `Corrida.test.tsx`, que montan la tabla con `control`: la columna nueva les cambia el DOM.

- [ ] **Step 9: Commit**

```bash
git add web/src/components/corrida/TablaItems.tsx web/src/components/corrida/CabeceraFiltros.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): seleccionar varias lineas de la corrida (checkbox + rango con Shift)"
```

---

### Task 3: La barra de acciones en lote

**Files:**
- Modify: `web/src/api/corridas.ts` (junto a `confirmar`, línea 44)
- Modify: `web/src/components/corrida/TablaItems.tsx`
- Test: `web/src/components/corrida/TablaItems.test.tsx`

**Interfaces:**
- Consumes: `seleccionadas: number[]` y `limpiarSeleccion()` (Task 2); `POST /api/corridas/{cid}/items/confirmar-lote` (Task 1).
- Produces: `confirmarLote(id, seqs, apuCodigo?, turno?): Promise<CorridaDetalle>` en `@/api/corridas`.

- [ ] **Step 1: El cliente de API**

En `web/src/api/corridas.ts`, después de `confirmar` (que termina alrededor de la línea 54):

```ts
/** Confirma varias líneas de una vez. Sin `apu_codigo`, cada línea confirma el APU
 *  que ya tiene. Devuelve la corrida recosteada (misma forma que `confirmar`). */
export function confirmarLote(
  id: number,
  seqs: number[],
  apu_codigo?: string,
  shift?: string,
): Promise<CorridaDetalle> {
  return apiPost<CorridaDetalle>(`/corridas/${id}/items/confirmar-lote`, {
    seqs,
    ...(apu_codigo !== undefined ? { apu_codigo } : {}),
    ...(shift !== undefined ? { shift } : {}),
  });
}
```

- [ ] **Step 2: Escribir los tests que fallan**

En `TablaItems.test.tsx`. El archivo ya mockea `@/api/corridas`; **sumale `confirmarLote` a esa factory** (si no, revienta con "confirmarLote is not a function"):

```tsx
test("Asignar manda los seqs marcados con el APU elegido", async () => {
  // render con control y 4 ítems; marcar 2 filas
  fireEvent.click(screen.getByLabelText("Marcar ítem 1"));
  fireEvent.click(screen.getByLabelText("Marcar ítem 3"));
  const input = await screen.findByPlaceholderText(/Buscar APU/i);
  fireEvent.change(input, { target: { value: "900" } });
  fireEvent.click(await screen.findByText("SUB APU DEMO"));   // el del mock de listarApus
  await waitFor(() =>
    expect(vi.mocked(confirmarLote)).toHaveBeenCalledWith(1, [seq1, seq3], "9001", "DIURNO"));
});

test("Confirmar el APU actual manda solo las filas que tienen APU", async () => {
  // una de las 4 filas sin apu_codigo; marcar todas
  fireEvent.click(screen.getByLabelText(/Marcar todas las líneas/i));
  fireEvent.click(screen.getByRole("button", { name: /Confirmar el APU actual/i }));
  await waitFor(() =>
    expect(vi.mocked(confirmarLote)).toHaveBeenCalledWith(1, [/* solo los con APU */], undefined, undefined));
});

test("después de asignar se limpia la selección", async () => {
  // ...asignar...
  await waitFor(() => expect(screen.queryByText(/líneas marcadas/i)).toBeNull());
});

test("si el lote falla, la selección se conserva", async () => {
  vi.mocked(confirmarLote).mockRejectedValueOnce(new Error("boom"));
  // ...asignar...
  expect(await screen.findByText(/2 líneas marcadas/i)).toBeTruthy();
});
```

Ajustá los seqs esperados a los del helper de items del archivo. Restaurá los mocks que modifiques (`mockRejectedValueOnce` se autorestaura tras una llamada).

- [ ] **Step 3: Correr los tests y verificar que fallan**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: FAIL — no existe la barra de acciones.

- [ ] **Step 4: La acción en lote**

En `TablaItems.tsx`, junto a `handleConfirmar` (línea 95). Reusa el `BuscadorApu` y el `toast` que el archivo ya importa:

```ts
  const [enLote, setEnLote] = useState(false);

  /** `apu` undefined = confirmar el APU que cada línea ya tiene. */
  async function accionLote(apu?: { codigo: string; turno: string }) {
    // Sin APU explícito, las filas sin APU no tienen nada que confirmar: se filtran
    // acá para no mandarle al backend seqs que va a saltear igual.
    const objetivo = apu
      ? seleccionadas
      : visible.filter((it) => marcadas.has(it.seq) && it.apu_codigo).map((it) => it.seq);
    if (objetivo.length === 0) {
      toast.error("Ninguna de las líneas marcadas tiene APU para confirmar.");
      return;
    }
    setEnLote(true);
    try {
      const actualizada = await confirmarLote(corridaId, objetivo, apu?.codigo, apu?.turno);
      onConfirmado(actualizada);
      limpiarSeleccion();
      const n = objetivo.length;
      toast.success(apu
        ? `${apu.codigo} asignado a ${n} ${n === 1 ? "línea" : "líneas"}`
        : `${n} ${n === 1 ? "línea" : "líneas"} confirmadas`);
    } catch (e) {
      // La selección NO se limpia: el usuario puede reintentar sin volver a marcar.
      toast.error(e instanceof Error ? e.message : "No se pudo aplicar el cambio en lote.");
    } finally {
      setEnLote(false);
    }
  }
```

Sumá `confirmarLote` al import de `@/api/corridas` (línea 19).

- [ ] **Step 5: La barra**

Al final del `return` de `TablaItems`, después de `</Table>` y antes del bloque de `duplicar`:

```tsx
      {seleccionable && haySeleccion && (
        <div className="sticky bottom-0 z-10 flex flex-wrap items-center gap-2 border-t bg-background/95 px-2 py-2 backdrop-blur">
          <span className="text-xs font-medium">
            {seleccionadas.length} {seleccionadas.length === 1 ? "línea" : "líneas"}
          </span>
          <div className="min-w-[220px] flex-1">
            <BuscadorApu
              disabled={enLote}
              onElegir={(apu) => accionLote({ codigo: apu.codigo, turno: apu.turno })}
            />
          </div>
          <Button size="xs" variant="outline" disabled={enLote} onClick={() => accionLote()}>
            {enLote ? "Aplicando…" : "Confirmar el APU actual"}
          </Button>
          <Button size="xs" variant="ghost" disabled={enLote} onClick={limpiarSeleccion}>
            Limpiar
          </Button>
        </div>
      )}
```

El `BuscadorApu` dispara la asignación al elegir un APU, igual que en la fila expandida — no hay botón "Asignar" aparte, porque elegir en el buscador ya es la confirmación de la intención.

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `cd web && npx vitest run src/components/corrida/TablaItems.test.tsx`
Expected: PASS

- [ ] **Step 7: Suite de frontend + build**

Run: `cd web && npx vitest run` y después `cd web && npm run build`
Expected: todo verde.

- [ ] **Step 8: Commit**

```bash
git add web/src/api/corridas.ts web/src/components/corrida/TablaItems.tsx web/src/components/corrida/TablaItems.test.tsx
git commit -m "feat(web): barra de acciones para asignar o confirmar APU en lote"
```

---

### Task 4: Verificación end-to-end en el navegador

Ningún push antes de esto: en cambios de UI el navegador va antes que el push.

- [ ] **Step 1: Suites completas**

Run: `python -m pytest tests/ -q` y `cd web && npx vitest run && npm run build`
Expected: todo verde. Anotar el número de tests de cada lado.

- [ ] **Step 2: Levantar la web en local**

`web/dist` tiene que estar reconstruido con el código final (`npm run build`). El backend necesita `SUPABASE_URL` (se puede derivar de `VITE_SUPABASE_URL` de `web/.env.local`) y `APU_ADMIN_EMAILS` (está comentado en `.env`); sin eso todo `/api` rebota 401. Un solo proceso: `python run_web.py` sirve `web/dist` y la API en `http://127.0.0.1:8000`. No exportes `APU_DB_BACKEND`, así corre contra el SQLite de `data/` y no contra producción.

- [ ] **Step 3: Probar los casos a mano**

Sobre una corrida con varios ítems repetidos:

1. Marcar 3 líneas con checkbox → el contador dice "3 líneas marcadas" y aparece la barra.
2. Click en una fila, Shift+click 4 filas más abajo → quedan marcadas las 5 del rango.
3. "Marcar todas" con un filtro puesto → marca solo lo filtrado.
4. Con líneas marcadas, cambiar el filtro para que algunas dejen de verse → el contador baja y al asignar no se tocan las que no se ven.
5. Elegir un APU en el buscador de la barra → las líneas marcadas quedan con ese APU y confirmadas, con un solo toast, y los totales de arriba se actualizan.
6. "Confirmar el APU actual" sobre líneas en revisión → quedan confirmadas sin cambiar de APU.
7. Congelar la corrida → no hay checkboxes ni barra.
8. Una corrida armándose en vivo → no hay checkboxes (la tabla viene del stream).

- [ ] **Step 4: Reportar y pedir el push**

Master autodespliega, así que el push necesita aprobación explícita. Reportar el número de tests de cada suite y el resultado de los 8 casos.

---

## Notas de la autorevisión

- **El lote NO es atómico** y es a propósito: `actualizar_eleccion` abre su propia conexión en los dos backends y no acepta `conn=`. La operación es idempotente (reasignar el mismo APU da lo mismo), un fallo a mitad se ve en la tabla y se arregla repitiendo el lote. Si una tarea empieza a propagar `conn=` por `corridas_db.py` / `pg/corridas_pg.py` / `repositorio.py`, se salió del alcance.
- **`_costear_row` y el snapshot no se tocan.** El lote solo escribe elecciones; congelar sigue siendo otro camino.
- **Nombres que tienen que coincidir entre tareas:** `confirmar_items` (Task 1) · `confirmarLote` (Task 3) · `marcadas` / `seleccionadas` / `seleccionable` / `limpiarSeleccion` (Task 2, usados por Task 3) · los `aria-label` `Marcar ítem <item>` y `Marcar todas las líneas visibles` (Task 2, usados por los tests de la Task 3).
- **El turno NO se puede exigir.** Relevado antes de escribir el plan: `rutas.py:271` pasa `body.shift` opcional, el botón "Elegir" de candidatos (`TablaItems.tsx:406`) y "Confirmar APU actual" (`:510`) confirman sin turno, y `tests/test_servicio_corridas.py:60` también. De ahí la resolución por fila (`shift or row.shift`) y las dos pasadas.
- **La validación del APU cambia el comportamiento de `confirmar_item`,** y eso es intencional: hoy confirmar un código inexistente deja el ítem costeado en $0. Al vivir en la primitiva compartida, el arreglo cubre el camino de un ítem y el de lote con un solo guard. Es la única desviación de "no cambiar comportamiento existente" del plan, y está declarada.
