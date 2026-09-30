# Notas — Fase 3: respuestas — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Responder una nota en un hilo de un nivel: la nota raíz con sus respuestas debajo, un botón «Responder», y una raíz borrada que tiene respuestas se muestra «(nota borrada)» sin tumbar el hilo.

**Architecture:** Una respuesta es una fila más de `nota` con `responde_a = <id de la raíz>` (la columna existe desde la Fase 1, siempre NULL hasta ahora), mismo `entidad` y `clave` que su raíz. Sin tabla nueva ni migración. El servidor valida el padre y aplana a un nivel (responder a una respuesta cuelga de su raíz). El listado devuelve una lista plana con `responde_a` y `borrada`; la web agrupa.

**Tech Stack:** Python 3 + FastAPI + sqlite3 / psycopg; React + TypeScript + Vite + Vitest.

**Spec:** `docs/superpowers/specs/2026-09-30-notas-insumos-apus-design.md` (sección «Fase 3: respuestas»). Fases 1 y 2 en producción (merge 77b0103).

## Global Constraints

- Español en nombres de dominio, comentarios y mensajes de usuario; colombiano, de **tú**, sin voseo.
- Invariante #1: las notas nunca van a la IA (sin cambios: `nota`/`notas`/`ultima_nota` ya en `_FORBIDDEN_KEYS`).
- Persistencia solo en `apu_tool/datos/`; SQLite y Postgres iguales. **Sin DDL nuevo**: `responde_a` ya existe en los dos schemas.
- Una respuesta tiene la **misma** `entidad` y `clave` que su raíz; si el cliente manda un `responde_a` de otro dueño → 400. Padre inexistente o borrado → 400 («La nota a la que respondes ya no existe.»).
- **Un solo nivel:** si `responde_a` apunta a una respuesta, se guarda la raíz de esa respuesta.
- Permisos iguales a una nota normal: responder = rol editor; editar = solo el autor; borrar = autor o Admin. Las respuestas aceptan menciones con las mismas reglas.
- Una raíz borrada **con** respuestas vivas se lista como marcador: `borrada: true`, `texto: ""`, `menciones: []`, `puede_editar/puede_borrar: false`. Sin respuestas vivas, no se lista. Una respuesta borrada no se lista.
- `tiene_notas`/`ultima_nota` cuentan raíces y respuestas no borradas (ya es así: `resumen_por_claves` filtra `borrada=0`; no se toca).
- Responder **no** avisa solo al autor de la raíz: para avisar se menciona con `@`.
- JSX: texto de usuario en atributos va como expresión, nunca partido en dos líneas.
- Tests: `python -m pytest tests/ -q -p no:warnings`, y en `web/` `npx vitest run` + `npm run build`, verdes antes de cada commit. Postgres local desechable: `postgresql://postgres@127.0.0.1:55433/apu_notas_test` (nunca otra URL).

---

### Task 1: Backend — respuestas en repo, servicio y API

**Files:**
- Modify: `apu_tool/datos/repositorio.py`, `apu_tool/datos/notas_db.py`, `apu_tool/datos/pg/notas_pg.py` (`crear` con `responde_a`, `listar` con `incluir_borradas`)
- Modify: `apu_tool/servicio/notas.py`, `apu_tool/servicio/esquemas.py`, `apu_tool/servicio/rutas.py`
- Test: `tests/test_notas_contrato.py`, `tests/test_api_respuestas.py`

**Interfaces:**
- Produces (repo, los dos backends):
  - `crear(conn, entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en, responde_a: Optional[int] = None) -> int`
  - `listar(entidad, clave, incluir_borradas: bool = False) -> list[Nota]` (orden id asc)
- Produces (API): `POST /api/notas` acepta `responde_a: int | null`; cada nota JSON suma `responde_a: int | null` y `borrada: bool`.

- [ ] **Step 1: Write the failing tests**

En `tests/test_notas_contrato.py` (corre en los dos backends):

```python
# ---- Fase 3: respuestas ----

def test_crear_respuesta_y_listar_con_borradas(repo):
    r, tx = repo
    raiz = _crear(r, tx, texto="raíz")
    resp = _escribir(tx, lambda c: r.crear(c, "insumo", "4520|DUCTO PVC", "4520 · DUCTO PVC",
                                           "respuesta", "u2", "u2@obra.co",
                                           "2026-09-30T11:00:00+00:00", responde_a=raiz))
    assert r.get(resp).responde_a == raiz and r.get(raiz).responde_a is None
    _escribir(tx, lambda c: r.borrar(c, raiz))
    assert [n.id for n in r.listar("insumo", "4520|DUCTO PVC")] == [resp]
    todas = r.listar("insumo", "4520|DUCTO PVC", incluir_borradas=True)
    assert [(n.id, n.borrada) for n in todas] == [(raiz, True), (resp, False)]
```

`tests/test_api_respuestas.py`:

```python
# tests/test_api_respuestas.py
from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, Perfil
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual

INS = {"entidad": "insumo", "codigo": "4520", "nombre": "DUCTO PVC"}
OTRO = {"entidad": "insumo", "codigo": "4521", "nombre": "CODO PVC"}
ANA = Perfil(user_id="u-ana", email="ana@obra.co", rol="editor", estado="activo", nombre="Ana")
BETO = Perfil(user_id="u-beto", email="beto@obra.co", rol="editor", estado="activo", nombre="Beto")
ADMIN = Perfil(user_id="u-adm", email="adm@obra.co", rol="admin", estado="activo", nombre="Adm")


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("4520", "DUCTO PVC", "ML", "D", 1.0, "COSTO INTERNO"),
                                Insumo("4521", "CODO PVC", "UN", "D", 1.0, "COSTO INTERNO")])
    for p in (ANA, BETO, ADMIN):
        alm.perfiles.upsert(p)
    return create_app(almacen=alm), alm


def _como(app, p):
    app.dependency_overrides[usuario_actual] = lambda: p
    return TestClient(app)


def test_responder_y_listar_el_hilo(tmp_path):
    app, _ = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()
    assert raiz["responde_a"] is None and raiz["borrada"] is False
    r = _como(app, BETO).post("/api/notas", json={**INS, "texto": "de acuerdo", "responde_a": raiz["id"]})
    assert r.status_code == 200, r.text
    assert r.json()["responde_a"] == raiz["id"]
    lista = _como(app, ANA).get("/api/notas", params=INS).json()
    assert [(n["texto"], n["responde_a"]) for n in lista] == [("raíz", None), ("de acuerdo", raiz["id"])]


def test_responder_a_una_respuesta_cuelga_de_la_raiz(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    raiz = ana.post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    r1 = ana.post("/api/notas", json={**INS, "texto": "r1", "responde_a": raiz}).json()["id"]
    r2 = ana.post("/api/notas", json={**INS, "texto": "r2", "responde_a": r1}).json()
    assert r2["responde_a"] == raiz


def test_padre_de_otro_dueno_o_inexistente_es_400(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    raiz = ana.post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    assert ana.post("/api/notas", json={**OTRO, "texto": "x", "responde_a": raiz}).status_code == 400
    assert ana.post("/api/notas", json={**INS, "texto": "x", "responde_a": 99999}).status_code == 400
    ana.delete(f"/api/notas/{raiz}")
    r = ana.post("/api/notas", json={**INS, "texto": "x", "responde_a": raiz})
    assert r.status_code == 400 and "ya no existe" in r.json()["detail"]


def test_raiz_borrada_con_respuestas_queda_como_marcador(tmp_path):
    app, _ = _app(tmp_path)
    ana, beto = _como(app, ANA), _como(app, BETO)
    raiz = ana.post("/api/notas", json={**INS, "texto": "secreto", "menciones": ["u-beto"]}).json()["id"]
    resp = beto.post("/api/notas", json={**INS, "texto": "respuesta", "responde_a": raiz}).json()["id"]
    _como(app, ANA).delete(f"/api/notas/{raiz}")
    lista = _como(app, ADMIN).get("/api/notas", params=INS).json()
    marcador = lista[0]
    assert marcador["id"] == raiz and marcador["borrada"] is True
    assert marcador["texto"] == "" and marcador["menciones"] == []
    assert marcador["puede_editar"] is False and marcador["puede_borrar"] is False
    assert lista[1]["id"] == resp
    # sin respuestas vivas, la raíz borrada desaparece
    _como(app, BETO).delete(f"/api/notas/{resp}")
    assert _como(app, ANA).get("/api/notas", params=INS).json() == []


def test_respuesta_con_mencion_y_auditoria(tmp_path):
    app, alm = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    _como(app, BETO).post("/api/notas", json={**INS, "texto": "@Ana mira", "responde_a": raiz,
                                              "menciones": ["u-ana"]})
    assert alm.notas.contar_sin_leer("u-ana") == 1
    items, _ = alm.auditoria.listar(entidad_tipo="nota")
    assert items[0]["despues"]["responde_a"] == raiz


def test_responder_no_avisa_solo_al_autor_de_la_raiz(tmp_path):
    app, alm = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    _como(app, BETO).post("/api/notas", json={**INS, "texto": "ok", "responde_a": raiz})
    assert alm.notas.contar_sin_leer("u-ana") == 0


def test_consulta_no_responde(tmp_path):
    app, _ = _app(tmp_path)
    raiz = _como(app, ANA).post("/api/notas", json={**INS, "texto": "raíz"}).json()["id"]
    lector = Perfil(user_id="u-l", email="l@obra.co", rol="consulta", estado="activo", nombre="L")
    r = _como(app, lector).post("/api/notas", json={**INS, "texto": "x", "responde_a": raiz})
    assert r.status_code == 403
```

- [ ] **Step 2: Run tests to verify they fail**

Run: `python -m pytest tests/test_notas_contrato.py tests/test_api_respuestas.py -q`
Expected: FAIL (`crear() got an unexpected keyword argument 'responde_a'`, `KeyError: 'responde_a'`, etc.)

- [ ] **Step 3: Write minimal implementation**

Repo — `apu_tool/datos/notas_db.py`:

```python
    def crear(self, conn, entidad: str, clave: str, etiqueta: str, texto: str,
              autor_id: str, autor_email: str, creada_en: str,
              responde_a: Optional[int] = None) -> int:
        cur = conn.execute(
            "INSERT INTO nota (entidad, clave, etiqueta, texto, autor_id, autor_email, "
            "creada_en, responde_a) VALUES (?,?,?,?,?,?,?,?)",
            (entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en, responde_a))
        return int(cur.lastrowid)
```

```python
    def listar(self, entidad: str, clave: str, incluir_borradas: bool = False) -> list[Nota]:
        filtro = "" if incluir_borradas else " AND borrada=0"
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT * FROM nota WHERE entidad=? AND clave=?{filtro} ORDER BY id",
                (entidad, clave)).fetchall()
        return [_fila(r) for r in rows]
```

`apu_tool/datos/pg/notas_pg.py`, espejo:

```python
    def crear(self, conn, entidad: str, clave: str, etiqueta: str, texto: str,
              autor_id: str, autor_email: str, creada_en: str,
              responde_a: Optional[int] = None) -> int:
        r = conn.execute(
            "INSERT INTO seguridad.nota "
            "(entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en, responde_a) "
            "VALUES (%s,%s,%s,%s,%s,%s,%s,%s) RETURNING id",
            (entidad, clave, etiqueta, texto, autor_id, autor_email, creada_en,
             responde_a)).fetchone()
        return int(r["id"])
```

```python
    def listar(self, entidad: str, clave: str, incluir_borradas: bool = False) -> list[Nota]:
        filtro = "" if incluir_borradas else " AND borrada=0"
        with self.cx.connection() as conn:
            rows = conn.execute(
                f"SELECT * FROM seguridad.nota WHERE entidad=%s AND clave=%s{filtro} "
                f"ORDER BY id", (entidad, clave)).fetchall()
        return [_fila(r) for r in rows]
```

`apu_tool/datos/repositorio.py`: actualizar las dos firmas en `RepositorioNotas` y documentar: `listar` sin borradas por defecto; `incluir_borradas=True` las trae todas (para armar el hilo).

`apu_tool/servicio/esquemas.py`, en `NotaNuevaIn`: `responde_a: Optional[int] = None   # id de la nota a la que responde (una raíz o una respuesta)`.

`apu_tool/servicio/notas.py`:

- `_out` suma `responde_a` y `borrada`, y convierte la raíz borrada en marcador:

```python
def _out(n: Nota, actor: Perfil, menciones: list[dict]) -> dict:
    mia = actor.user_id == n.autor_id
    escribe = actor.rol in ("editor", "admin")
    if n.borrada:
        # Marcador de una raíz borrada que todavía tiene respuestas: sostiene el hilo
        # sin mostrar lo que se borró.
        return {"id": n.id, "entidad": n.entidad, "etiqueta": n.etiqueta, "texto": "",
                "autor_email": n.autor_email, "creada_en": n.creada_en,
                "editada_en": n.editada_en, "es_mia": mia, "puede_editar": False,
                "puede_borrar": False, "dueno": _dueno(n), "menciones": [],
                "responde_a": n.responde_a, "borrada": True}
    return {"id": n.id, "entidad": n.entidad, "etiqueta": n.etiqueta, "texto": n.texto,
            "autor_email": n.autor_email, "creada_en": n.creada_en,
            "editada_en": n.editada_en, "es_mia": mia,
            "puede_editar": mia and escribe,
            "puede_borrar": escribe and _puede_borrar(n, actor),
            "dueno": _dueno(n), "menciones": menciones,
            "responde_a": n.responde_a, "borrada": False}
```

- `listar` arma el hilo:

```python
def _hilo(notas: list[Nota]) -> list[Nota]:
    """Las vivas, más las raíces borradas que todavía tienen respuestas vivas (como
    marcador). Una respuesta borrada no se muestra. Orden por id (cronológico)."""
    con_respuesta = {n.responde_a for n in notas if n.responde_a is not None and not n.borrada}
    return [n for n in notas
            if not n.borrada or (n.responde_a is None and n.id in con_respuesta)]


def listar(alm: Almacen, actor: Perfil, entidad: str, codigo: str, nombre: str = "",
           turno: str = "") -> list[dict]:
    if entidad not in ENTIDADES:
        raise ValueError("La nota debe ser de un insumo o de un APU.")
    clave = (clave_insumo(codigo, nombre) if entidad == "insumo"
             else clave_apu(codigo, turno))
    return _salidas(alm, _hilo(alm.notas.listar(entidad, clave, incluir_borradas=True)), actor)
```

(`_salidas` pide menciones de todas las notas del hilo; las del marcador se descartan en `_out`.)

- `crear` recibe `responde_a`:

```python
def _raiz_para_responder(alm: Almacen, responde_a: int, entidad: str, clave: str) -> int:
    """Valida el padre y aplana a un nivel: responder a una respuesta cuelga de su raíz."""
    padre = alm.notas.get(responde_a)
    if padre is None or padre.borrada:
        raise ValueError("La nota a la que respondes ya no existe.")
    if padre.entidad != entidad or padre.clave != clave:
        raise ValueError("Solo puedes responder notas del mismo insumo o APU.")
    return padre.responde_a or padre.id


def crear(alm: Almacen, actor: Perfil, entidad: str, codigo: str, nombre: str,
          turno: str, texto: str, menciones: Optional[list[str]] = None,
          responde_a: Optional[int] = None) -> dict:
    t = _texto_valido(texto)
    clave, etiqueta = _resolver_dueno(alm, entidad, codigo, nombre, turno)
    raiz = (None if responde_a is None
            else _raiz_para_responder(alm, responde_a, entidad, clave))
    perfiles = _perfiles(alm)
    uids = _menciones_validas(perfiles, actor, menciones or [])
    ahora = _ahora()
    with alm.transaccion("seguridad") as conn:
        nid = alm.notas.crear(conn, entidad, clave, etiqueta, t, actor.user_id,
                              actor.email, ahora, responde_a=raiz)
        alm.notas.set_menciones(conn, nid, uids, ahora)
        despues = {"entidad": entidad, "clave": clave, "texto": t}
        if raiz is not None:
            despues["responde_a"] = raiz
        if uids:   # la auditoría es historia permanente: correos, no user_ids
            despues["menciones"] = [perfiles[u].email for u in uids]
        registrar_auditoria(alm, conn, actor, "nota.crear", "nota", nid, antes=None,
                            despues=despues)
    return _salidas(alm, [alm.notas.get(nid)], actor)[0]
```

`apu_tool/servicio/rutas.py`, `notas_crear` pasa `body.responde_a`:

```python
    return _http_notas(lambda: notas_svc.crear(alm, actor, body.entidad, body.codigo,
                                               body.nombre, body.turno, body.texto,
                                               body.menciones, body.responde_a))
```

- [ ] **Step 4: Run tests to verify they pass**

Run: `python -m pytest tests/test_notas_contrato.py tests/test_api_respuestas.py tests/test_api_notas.py tests/test_api_menciones.py -q` → pasa.
Run: `TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55433/apu_notas_test python -m pytest tests/test_notas_contrato.py -q` → las `[postgres]` pasan.
Run: `python -m pytest tests/ -q -p no:warnings` → verde (si un test viejo compara un dict de nota exacto, ajustarlo para `responde_a`/`borrada` y decirlo).

- [ ] **Step 5: Commit**

```bash
git add apu_tool/datos/repositorio.py apu_tool/datos/notas_db.py apu_tool/datos/pg/notas_pg.py apu_tool/servicio/notas.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_notas_contrato.py tests/test_api_respuestas.py
git commit -m "feat(notas): responder una nota (hilo de un nivel)"
```

---

### Task 2: Web — hilos en el panel de notas

**Files:**
- Modify: `web/src/lib/tipos.ts` (`Nota.responde_a`, `Nota.borrada`)
- Modify: `web/src/api/notas.ts` (`crearNota` con `respondeA`)
- Create: `web/src/lib/hilos.ts` + `web/src/lib/hilos.test.ts`
- Modify: `web/src/components/notas/DialogoNotas.tsx` + `DialogoNotas.test.tsx`
- Modify: `web/src/pages/Notas.tsx` (marca «↳» en las respuestas)

**Interfaces:**
- Consumes: API de la Task 1.
- Produces:
  - `Nota.responde_a: number | null; Nota.borrada: boolean`
  - `crearNota(d: DuenoNota, texto: string, menciones: string[] = [], respondeA?: number)` → body `{...d, texto, menciones, responde_a?}`
  - `agruparHilos(notas: Nota[]): { raiz: Nota; respuestas: Nota[] }[]` — raíces en orden; respuestas bajo su raíz en orden; una respuesta cuya raíz no vino se trata como raíz (no se pierde).

- [ ] **Step 1: Write the failing tests**

`web/src/lib/hilos.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import { agruparHilos } from "./hilos";
import type { Nota } from "./tipos";

const n = (id: number, responde_a: number | null = null) => ({ id, responde_a } as unknown as Nota);

describe("agruparHilos", () => {
  it("pone cada respuesta bajo su raíz, en orden", () => {
    const h = agruparHilos([n(1), n(2), n(3, 1), n(4, 2), n(5, 1)]);
    expect(h.map((x) => [x.raiz.id, x.respuestas.map((r) => r.id)])).toEqual([[1, [3, 5]], [2, [4]]]);
  });
  it("una respuesta huérfana se muestra como raíz", () => {
    expect(agruparHilos([n(7, 99)]).map((x) => x.raiz.id)).toEqual([7]);
  });
});
```

En `web/src/components/notas/DialogoNotas.test.tsx`: el helper `nota()` suma `responde_a: null, borrada: false`; tests nuevos:

```tsx
  it("muestra las respuestas bajo su nota y permite responder", async () => {
    listarNotas.mockResolvedValue([
      nota({ id: 1, texto: "raíz" }),
      nota({ id: 2, texto: "una respuesta", responde_a: 1, es_mia: false, puede_editar: false, puede_borrar: false }),
    ]);
    crearNota.mockResolvedValue(nota({ id: 3, texto: "otra respuesta", responde_a: 1 }));
    const onCambio = montar();
    const respuesta = await screen.findByText("una respuesta");
    expect(respuesta.closest("[data-respuesta='si']")).not.toBeNull();
    fireEvent.click(screen.getByRole("button", { name: "Responder" }));
    fireEvent.change(screen.getByLabelText("Responder nota"),
                     { target: { value: "otra respuesta", selectionStart: 14, selectionEnd: 14 } });
    fireEvent.click(screen.getByRole("button", { name: "Enviar respuesta" }));
    await waitFor(() => expect(crearNota).toHaveBeenCalledWith(DUENO, "otra respuesta", [], 1));
    expect(await screen.findByText("otra respuesta")).toBeTruthy();
    expect(onCambio).toHaveBeenCalled();
  });

  it("una respuesta no tiene botón Responder (un solo nivel)", async () => {
    listarNotas.mockResolvedValue([nota({ id: 1, texto: "raíz" }), nota({ id: 2, texto: "r", responde_a: 1 })]);
    montar();
    await screen.findByText("r");
    expect(screen.getAllByRole("button", { name: "Responder" })).toHaveLength(1);
  });

  it("una raíz borrada con respuestas se ve como (nota borrada)", async () => {
    listarNotas.mockResolvedValue([
      nota({ id: 1, texto: "", borrada: true, puede_editar: false, puede_borrar: false }),
      nota({ id: 2, texto: "sigue aquí", responde_a: 1 }),
    ]);
    montar();
    expect(await screen.findByText("(nota borrada)")).toBeTruthy();
    expect(screen.getByText("sigue aquí")).toBeTruthy();
    expect(screen.queryByRole("button", { name: "Responder" })).toBeNull();
  });

  it("borrar recarga el hilo desde el servidor", async () => {
    vi.spyOn(window, "confirm").mockReturnValue(true);
    borrarNota.mockResolvedValue(undefined);
    listarNotas
      .mockResolvedValueOnce([nota({ id: 1, texto: "raíz" }), nota({ id: 2, texto: "r", responde_a: 1 })])
      .mockResolvedValueOnce([nota({ id: 1, texto: "", borrada: true, puede_editar: false, puede_borrar: false }),
                              nota({ id: 2, texto: "r", responde_a: 1 })]);
    montar();
    await screen.findByText("raíz");
    fireEvent.click(screen.getAllByRole("button", { name: "Borrar" })[0]);
    expect(await screen.findByText("(nota borrada)")).toBeTruthy();
    expect(listarNotas).toHaveBeenCalledTimes(2);
  });
```

- el test de consulta existente: además, `Responder` no aparece (`queryByRole("button", { name: "Responder" })` es null).
- el test viejo de «borra con confirmación» pasa a esperar la recarga: `listarNotas` se llama una segunda vez (con `mockResolvedValueOnce([nota()])` y luego `[]`); ajustar lo mínimo.

- [ ] **Step 2: Run tests to verify they fail**

Run (en `web/`): `npx vitest run src/lib/hilos.test.ts src/components/notas`
Expected: FAIL.

- [ ] **Step 3: Write minimal implementation**

`web/src/lib/tipos.ts`, en `interface Nota`: `responde_a: number | null;` y `borrada: boolean;`.

`web/src/api/notas.ts`:

```ts
export const crearNota = (d: DuenoNota, texto: string, menciones: string[] = [], respondeA?: number) =>
  apiPost<Nota>("/notas", respondeA === undefined
    ? { ...d, texto, menciones }
    : { ...d, texto, menciones, responde_a: respondeA });
```

`web/src/lib/hilos.ts`:

```ts
import type { Nota } from "@/lib/tipos";

/** Agrupa la lista plana del servidor en hilos de un nivel: cada raíz con sus
 *  respuestas debajo, en el orden en que llegaron. Una respuesta cuya raíz no vino
 *  (no debería pasar) se muestra como raíz para no perderla. */
export function agruparHilos(notas: Nota[]): { raiz: Nota; respuestas: Nota[] }[] {
  const ids = new Set(notas.map((n) => n.id));
  const hilos: { raiz: Nota; respuestas: Nota[] }[] = [];
  const porRaiz = new Map<number, Nota[]>();
  for (const n of notas) {
    if (n.responde_a !== null && ids.has(n.responde_a)) {
      porRaiz.set(n.responde_a, [...(porRaiz.get(n.responde_a) ?? []), n]);
    }
  }
  for (const n of notas) {
    if (n.responde_a === null || !ids.has(n.responde_a)) {
      hilos.push({ raiz: n, respuestas: porRaiz.get(n.id) ?? [] });
    }
  }
  return hilos;
}
```

`web/src/components/notas/DialogoNotas.tsx` (sobre la versión actual — **conservar** `claveDueno` + cancelación, la guarda `claveVigente`/`duenoRef`, las actualizaciones funcionales de `editando`, `onEscapeKeyDown` y `abrirHacia`):
- estado nuevo: `const [respondiendo, setRespondiendo] = useState<{ raizId: number; texto: string; elegidos: MencionNota[] } | null>(null);` (se resetea en el efecto de carga, como `editando`).
- extraer el pintado de una nota a una función interna `renderNota(n: Nota, esRespuesta: boolean)` con lo que ya pinta cada nota (encabezado autor/fecha/(editada), Editar/Borrar, caja de edición o `TextoConMenciones`). Si `n.borrada`: solo `<p className="mt-1 italic text-muted-foreground">(nota borrada)</p>`, sin botones.
- la lista se pinta con `agruparHilos(notas)`: por cada hilo, `renderNota(raiz, false)`; debajo, las respuestas en `<div data-respuesta="si" className="ml-4 border-l border-border pl-3">`; y, si `escribe` y la raíz no está borrada, un botón `Responder` (`size="xs" variant="ghost"`) que abre `CajaConMenciones` con `ariaLabel="Responder nota"`, `abrirHacia="abajo"`, y botones «Cancelar» / «Enviar respuesta».
- `responder()`: igual que `agregar` pero `crearNota(dueno, r.texto, mencionesVigentes(r.texto, r.elegidos), r.raizId)`; al tener éxito (con la guarda de clave) agrega la nota a la lista y cierra `respondiendo`; `onCambio()`.
- `borrar(id)`: tras el éxito, **recargar** la lista (`listarNotas(duenoRef.current)` con la guarda de clave) en vez de filtrar localmente — una raíz con respuestas no desaparece, pasa a marcador, y eso lo decide el servidor. `onCambio()` como antes.

`web/src/pages/Notas.tsx`: en la celda del texto, si `n.responde_a !== null`, anteponer `<span className="text-muted-foreground">↳ </span>`; `title` del texto sin cambios.

- [ ] **Step 4: Run tests to verify they pass**

Run (en `web/`): `npx vitest run src/lib src/components/notas src/pages/Notas.test.tsx` → pasa.
Run: `npx vitest run` y `npm run build` → verdes. (Mocks de `nota` en otros tests pueden necesitar `responde_a`/`borrada`: si un test falla solo por eso, agregarlos y decirlo.)

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/notas.ts web/src/lib/hilos.ts web/src/lib/hilos.test.ts web/src/components/notas web/src/pages/Notas.tsx
git commit -m "feat(web): responder notas en hilos de un nivel"
```

---

### Task 3: Documentación + verificación

- [ ] **Step 1:** En `CLAUDE.md`, viñeta «Notas de insumos y APUs.», reemplazar «La Fase 3 (respuestas) sigue en el spec …» por:

```markdown
  **Respuestas (Fase 3):** una respuesta es otra fila de `nota` con `responde_a` = la
  raíz (misma `entidad`/`clave`); responder a una respuesta cuelga de su raíz (un solo
  nivel). Una raíz borrada con respuestas vivas se lista como marcador (`borrada: true`,
  sin texto); sin respuestas, desaparece. Responder no avisa solo: se menciona con `@`.
```

- [ ] **Step 2:** Suites: `python -m pytest tests/ -q -p no:warnings`; Postgres local (`tests/test_notas_contrato.py`); en `web/` `npx vitest run` y `npm run build`.
- [ ] **Step 3:** Commit `docs: respuestas de notas en CLAUDE.md`.
- [ ] **Step 4 (controlador):** navegador con dos usuarios: A escribe una nota; B responde (y menciona a A → campanita de A); la respuesta sale indentada bajo la nota; A borra su nota raíz → queda «(nota borrada)» con la respuesta de B debajo; B borra su respuesta → el hilo desaparece y el ícono de la fila vuelve a vacío.
