> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-09-30-notas-fase-2-menciones.md`

# Notas — Fase 2: menciones y campanita — Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** En una nota se puede mencionar a otro usuario con `@`, y ese usuario ve una campanita en la barra superior con sus menciones sin leer; al abrir una mención va al panel de esa nota y queda leída.

**Architecture:** Tabla `nota_mencion` junto a `nota` (seguridad.db / schema seguridad), manejada por el mismo repo de notas (`alm.notas`) en los dos backends. El servicio `servicio/notas.py` valida las menciones contra perfiles activos y las sincroniza al crear/editar. El conteo sin leer viaja en la respuesta de `GET /api/presencia`, que la barra ya pide cada 45 s: **no se agrega ningún sondeo**. La web suma una caja de texto con autocompletado de `@` (`CajaConMenciones`), resalta los nombres mencionados y agrega `Campanita` a la barra.

**Tech Stack:** Python 3 + FastAPI + sqlite3 / psycopg; React + TypeScript + Vite + Vitest + Testing Library; lucide-react.

**Spec:** `docs/superpowers/specs/2026-09-30-notas-insumos-apus-design.md` (sección «Fase 2: menciones»). Fase 1 ya está en producción (merge 1f5aa45).

## Global Constraints

- Español en nombres de dominio, comentarios y mensajes de usuario; español colombiano, de **tú**, sin voseo.
- Invariante #1: las notas y menciones **nunca** van a la IA (`nota`/`notas`/`ultima_nota` ya están en `_FORBIDDEN_KEYS`).
- Persistencia solo en `apu_tool/datos/`; SQLite y Postgres se comportan igual; `nota_mencion` vive en `seguridad.db` / schema `seguridad`.
- Las menciones las manda el **cliente** como `menciones: [user_id]`; el servidor las valida contra perfiles **activos**, descarta las que no, descarta al propio autor y deduplica. **No** las deduce parseando el texto.
- Editar resincroniza: mencionado nuevo → aviso nuevo (`leida_en` NULL); quitado → se borra su fila; los que siguen conservan su estado de lectura. Una nota borrada deja de contar y de listarse en las menciones.
- El conteo sin leer viaja en `GET /api/presencia` como `menciones_sin_leer` (entero, o `null` si la lectura falla — la presencia nunca se cae por eso). **Ningún sondeo nuevo**; ningún poll de fondo con `apiGet`.
- `GET /api/usuarios/mencionables` = rol **editor** (solo quien escribe menciona); devuelve solo `user_id`, `nombre`, `email` de perfiles activos, sin el que pregunta.
- `GET /api/menciones`, `POST /api/menciones/{nota_id}/leida`, `POST /api/menciones/leidas` = rol **consulta** (a cualquiera lo pueden mencionar).
- Cada nota que sale de la API trae `menciones: [{user_id, nombre}]` (nombre = `perfil.nombre` o, si está vacío, el email), calculado en lote (una consulta para todas las notas de la respuesta, nunca una por nota).
- JSX: texto de usuario en atributos va como expresión (`title={"..." + "..."}`), nunca partido en dos líneas.
- Tests: `python -m pytest tests/ -q -p no:warnings`, y en `web/` `npx vitest run` + `npm run build`, verdes antes de cada commit que toque su lado. Postgres local desechable disponible en `postgresql://postgres@127.0.0.1:55433/apu_notas_test` (lo arranca el controlador); **nunca** otra URL.

---

## File Structure

| Archivo | Responsabilidad |
|---|---|
| `db/seguridad.sql`, `db/pg/seguridad.sql` | DDL de `nota_mencion` |
| `supabase/migrations/0008_menciones_rls.sql` | RLS sin policies (paso manual en prod) |
| `apu_tool/datos/repositorio.py` | métodos nuevos en `RepositorioNotas` |
| `apu_tool/datos/notas_db.py`, `apu_tool/datos/pg/notas_pg.py` | menciones en los dos backends |
| `apu_tool/datos/perfiles_db.py` | el reset completo también dropea `nota_mencion` |
| `apu_tool/servicio/notas.py` | validar/sincronizar menciones, `menciones` en la salida, bandeja |
| `apu_tool/servicio/esquemas.py` | `menciones` en los DTOs |
| `apu_tool/servicio/rutas.py` | endpoints de menciones, mencionables y presencia |
| `web/src/lib/tipos.ts` | tipos `MencionNota`, `Mencionable`, `Mencion`; `menciones_sin_leer` |
| `web/src/lib/menciones.ts` | funciones puras: detectar `@`, insertar, vigentes, partir para resaltar |
| `web/src/api/notas.ts` | cliente de menciones y mencionables |
| `web/src/components/notas/CajaConMenciones.tsx` | textarea con autocompletado de `@` |
| `web/src/components/notas/TextoConMenciones.tsx` | pinta el texto con los `@Nombre` resaltados |
| `web/src/components/notas/DialogoNotas.tsx` | usa la caja y el resaltado |
| `web/src/components/notas/Campanita.tsx` | campanita + lista de menciones |
| `web/src/components/Layout.tsx` | monta la campanita con el conteo de presencia |
| `CLAUDE.md` | documentar |

---

### Task 1: Tabla `nota_mencion` + repo (los dos backends)

**Files:**
- Modify: `db/seguridad.sql`, `db/pg/seguridad.sql` (al final)
- Create: `supabase/migrations/0008_menciones_rls.sql`
- Modify: `apu_tool/datos/repositorio.py` (`RepositorioNotas`)
- Modify: `apu_tool/datos/notas_db.py`, `apu_tool/datos/pg/notas_pg.py`
- Modify: `apu_tool/datos/perfiles_db.py` (tupla del reset)
- Test: `tests/test_notas_contrato.py` (agregar casos; ya está parametrizado por backend)

**Interfaces:**
- Consumes: `Nota`, `NotasDB`, `NotasPg`, helpers `_crear`, `_escribir` y fixture `repo` que ya existen en `tests/test_notas_contrato.py`.
- Produces (métodos nuevos, mismos en los dos repos):
  - `set_menciones(conn, nota_id: int, user_ids: list[str], creada_en: str) -> list[str]` — deja exactamente esas filas para la nota; devuelve los user_id **nuevos** (en el orden recibido).
  - `menciones_de_notas(nota_ids: list[int]) -> dict[int, list[str]]` — una consulta; notas sin menciones no aparecen.
  - `contar_sin_leer(user_id: str) -> int` — menciones sin leer de notas no borradas.
  - `listar_menciones(user_id: str, limit: int = 50) -> list[tuple[Nota, Optional[str]]]` — (nota, leida_en), notas no borradas, la mención más reciente primero.
  - `marcar_leida(conn, user_id: str, nota_id: int, leida_en: str) -> None`
  - `marcar_todas_leidas(conn, user_id: str, leida_en: str) -> None`

- [ ] **Step 1: Write the failing test**

Agregar al final de `tests/test_notas_contrato.py`:

```python
# ---- Fase 2: menciones ----

def _mencionar(r, tx, nid, uids, ts="2026-09-30T10:00:00+00:00"):
    return _escribir(tx, lambda c: r.set_menciones(c, nid, uids, ts))


def test_set_menciones_sincroniza_y_devuelve_los_nuevos(repo):
    r, tx = repo
    nid = _crear(r, tx)
    assert _mencionar(r, tx, nid, ["ana", "beto"]) == ["ana", "beto"]
    assert sorted(r.menciones_de_notas([nid])[nid]) == ["ana", "beto"]
    # editar: se va beto, llega caro; ana sigue y NO es "nueva"
    assert _mencionar(r, tx, nid, ["ana", "caro"]) == ["caro"]
    assert sorted(r.menciones_de_notas([nid])[nid]) == ["ana", "caro"]
    assert _mencionar(r, tx, nid, []) == []
    assert r.menciones_de_notas([nid]) == {}
    assert r.menciones_de_notas([]) == {}


def test_contar_listar_y_marcar_leidas(repo):
    r, tx = repo
    a = _crear(r, tx, texto="primera", ts="2026-09-30T10:00:00+00:00")
    b = _crear(r, tx, texto="segunda", ts="2026-09-30T11:00:00+00:00")
    _mencionar(r, tx, a, ["ana"], ts="2026-09-30T10:00:00+00:00")
    _mencionar(r, tx, b, ["ana", "beto"], ts="2026-09-30T11:00:00+00:00")
    assert r.contar_sin_leer("ana") == 2 and r.contar_sin_leer("beto") == 1
    lista = r.listar_menciones("ana")
    assert [(n.texto, leida) for n, leida in lista] == [("segunda", None), ("primera", None)]

    _escribir(tx, lambda c: r.marcar_leida(c, "ana", a, "2026-09-30T12:00:00+00:00"))
    assert r.contar_sin_leer("ana") == 1
    assert dict((n.id, l) for n, l in r.listar_menciones("ana"))[a] == "2026-09-30T12:00:00+00:00"
    # marcar otra vez no pisa la fecha de lectura
    _escribir(tx, lambda c: r.marcar_leida(c, "ana", a, "2026-09-30T13:00:00+00:00"))
    assert dict((n.id, l) for n, l in r.listar_menciones("ana"))[a] == "2026-09-30T12:00:00+00:00"

    _escribir(tx, lambda c: r.marcar_todas_leidas(c, "ana", "2026-09-30T14:00:00+00:00"))
    assert r.contar_sin_leer("ana") == 0 and r.contar_sin_leer("beto") == 1


def test_una_nota_borrada_no_cuenta_ni_se_lista(repo):
    r, tx = repo
    nid = _crear(r, tx)
    _mencionar(r, tx, nid, ["ana"])
    _escribir(tx, lambda c: r.borrar(c, nid))
    assert r.contar_sin_leer("ana") == 0
    assert r.listar_menciones("ana") == []


def test_listar_menciones_respeta_el_limite(repo):
    r, tx = repo
    for i in range(3):
        nid = _crear(r, tx, texto=f"n{i}", ts=f"2026-09-30T1{i}:00:00+00:00")
        _mencionar(r, tx, nid, ["ana"], ts=f"2026-09-30T1{i}:00:00+00:00")
    assert [n.texto for n, _ in r.listar_menciones("ana", limit=2)] == ["n2", "n1"]


def test_ddl_crea_nota_mencion_en_los_dos_backends():
    for ruta in (("db", "seguridad.sql"), ("db", "pg", "seguridad.sql")):
        sql = config.PROJECT_ROOT.joinpath(*ruta).read_text(encoding="utf-8")
        assert "nota_mencion" in sql and "UNIQUE (nota_id, user_id)" in sql
```

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_notas_contrato.py -q`
Expected: FAIL con `AttributeError: 'NotasDB' object has no attribute 'set_menciones'` (y el test de DDL en `assert "nota_mencion" in sql`).

- [ ] **Step 3: Write minimal implementation**

Al final de `db/seguridad.sql`:

```sql

-- Menciones de la Fase 2: a quién avisa una nota. `leida_en` NULL = sin leer.
-- Enlace blando a perfiles (user_id de Supabase Auth), sin FK, como autor_id de nota.
CREATE TABLE IF NOT EXISTS nota_mencion (
    nota_id   INTEGER NOT NULL,
    user_id   TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    leida_en  TEXT,
    UNIQUE (nota_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_mencion_user ON nota_mencion(user_id, leida_en);
```

Al final de `db/pg/seguridad.sql`:

```sql

-- Espejo de db/seguridad.sql::nota_mencion.
CREATE TABLE IF NOT EXISTS seguridad.nota_mencion (
    nota_id   BIGINT NOT NULL,
    user_id   TEXT NOT NULL,
    creada_en TEXT NOT NULL,
    leida_en  TEXT,
    UNIQUE (nota_id, user_id)
);
CREATE INDEX IF NOT EXISTS idx_mencion_user ON seguridad.nota_mencion(user_id, leida_en);
```

Crear `supabase/migrations/0008_menciones_rls.sql`:

```sql
-- Defensa en profundidad: RLS SIN policies en seguridad.nota_mencion, igual que
-- 0007_notas_rls.sql. La tabla la crea el boot (db/pg/seguridad.sql).
-- PASO MANUAL en producción: aplicarlo en el SQL editor de Supabase tras el deploy.
ALTER TABLE seguridad.nota_mencion ENABLE ROW LEVEL SECURITY;
```

En `apu_tool/datos/repositorio.py`, dentro de `RepositorioNotas`, al final:

```python
    # ---- Fase 2: menciones (tabla nota_mencion) ----
    def set_menciones(self, conn, nota_id: int, user_ids: list[str],
                      creada_en: str) -> list[str]:
        """Deja exactamente esas menciones para la nota (sobre la conexión de la UdT).
        Devuelve los user_id NUEVOS; los que ya estaban conservan su estado de lectura."""
        ...

    def menciones_de_notas(self, nota_ids: list[int]) -> dict[int, list[str]]:
        """nota_id → user_ids mencionados. UNA consulta; sin menciones = ausente."""
        ...

    def contar_sin_leer(self, user_id: str) -> int:
        """Menciones sin leer de `user_id` en notas no borradas."""
        ...

    def listar_menciones(self, user_id: str,
                         limit: int = 50) -> list[tuple[Nota, Optional[str]]]:
        """(nota, leida_en) de notas no borradas, la mención más reciente primero."""
        ...

    def marcar_leida(self, conn, user_id: str, nota_id: int, leida_en: str) -> None:
        """Solo si estaba sin leer (no pisa la fecha de una lectura anterior)."""
        ...

    def marcar_todas_leidas(self, conn, user_id: str, leida_en: str) -> None: ...
```

En `apu_tool/datos/notas_db.py`, al final de la clase `NotasDB`:

```python
    # ---- Fase 2: menciones ----
    def set_menciones(self, conn, nota_id: int, user_ids: list[str],
                      creada_en: str) -> list[str]:
        actuales = {r["user_id"] for r in conn.execute(
            "SELECT user_id FROM nota_mencion WHERE nota_id=?", (int(nota_id),))}
        deseados = list(dict.fromkeys(user_ids))            # dedup conservando el orden
        for u in actuales - set(deseados):
            conn.execute("DELETE FROM nota_mencion WHERE nota_id=? AND user_id=?",
                         (int(nota_id), u))
        nuevos = [u for u in deseados if u not in actuales]
        for u in nuevos:
            conn.execute("INSERT INTO nota_mencion (nota_id, user_id, creada_en) "
                         "VALUES (?,?,?)", (int(nota_id), u, creada_en))
        return nuevos

    def menciones_de_notas(self, nota_ids: list[int]) -> dict[int, list[str]]:
        if not nota_ids:
            return {}
        marcas = ",".join("?" * len(nota_ids))
        with self.connect() as conn:
            rows = conn.execute(
                f"SELECT nota_id, user_id FROM nota_mencion WHERE nota_id IN ({marcas}) "
                f"ORDER BY nota_id, user_id", [int(i) for i in nota_ids]).fetchall()
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(int(r["nota_id"]), []).append(r["user_id"])
        return out

    def contar_sin_leer(self, user_id: str) -> int:
        with self.connect() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) FROM nota_mencion m JOIN nota n ON n.id = m.nota_id "
                "WHERE m.user_id=? AND m.leida_en IS NULL AND n.borrada=0",
                (user_id,)).fetchone()[0])

    def listar_menciones(self, user_id: str,
                         limit: int = 50) -> list[tuple[Nota, Optional[str]]]:
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT n.*, m.leida_en AS mencion_leida_en FROM nota_mencion m "
                "JOIN nota n ON n.id = m.nota_id WHERE m.user_id=? AND n.borrada=0 "
                "ORDER BY m.creada_en DESC, n.id DESC LIMIT ?",
                (user_id, int(limit))).fetchall()
        return [(_fila(r), r["mencion_leida_en"]) for r in rows]

    def marcar_leida(self, conn, user_id: str, nota_id: int, leida_en: str) -> None:
        conn.execute("UPDATE nota_mencion SET leida_en=? WHERE user_id=? AND nota_id=? "
                     "AND leida_en IS NULL", (leida_en, user_id, int(nota_id)))

    def marcar_todas_leidas(self, conn, user_id: str, leida_en: str) -> None:
        conn.execute("UPDATE nota_mencion SET leida_en=? WHERE user_id=? "
                     "AND leida_en IS NULL", (leida_en, user_id))
```

En `apu_tool/datos/pg/notas_pg.py`, al final de la clase `NotasPg`:

```python
    # ---- Fase 2: menciones (espejo de notas_db.py) ----
    def set_menciones(self, conn, nota_id: int, user_ids: list[str],
                      creada_en: str) -> list[str]:
        actuales = {r["user_id"] for r in conn.execute(
            "SELECT user_id FROM seguridad.nota_mencion WHERE nota_id=%s",
            (int(nota_id),)).fetchall()}
        deseados = list(dict.fromkeys(user_ids))
        for u in actuales - set(deseados):
            conn.execute("DELETE FROM seguridad.nota_mencion WHERE nota_id=%s AND user_id=%s",
                         (int(nota_id), u))
        nuevos = [u for u in deseados if u not in actuales]
        for u in nuevos:
            conn.execute("INSERT INTO seguridad.nota_mencion (nota_id, user_id, creada_en) "
                         "VALUES (%s,%s,%s)", (int(nota_id), u, creada_en))
        return nuevos

    def menciones_de_notas(self, nota_ids: list[int]) -> dict[int, list[str]]:
        if not nota_ids:
            return {}
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT nota_id, user_id FROM seguridad.nota_mencion "
                "WHERE nota_id = ANY(%s) ORDER BY nota_id, user_id",
                ([int(i) for i in nota_ids],)).fetchall()
        out: dict[int, list[str]] = {}
        for r in rows:
            out.setdefault(int(r["nota_id"]), []).append(r["user_id"])
        return out

    def contar_sin_leer(self, user_id: str) -> int:
        with self.cx.connection() as conn:
            return int(conn.execute(
                "SELECT COUNT(*) AS n FROM seguridad.nota_mencion m "
                "JOIN seguridad.nota n ON n.id = m.nota_id "
                "WHERE m.user_id=%s AND m.leida_en IS NULL AND n.borrada=0",
                (user_id,)).fetchone()["n"])

    def listar_menciones(self, user_id: str,
                         limit: int = 50) -> list[tuple[Nota, Optional[str]]]:
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT n.*, m.leida_en AS mencion_leida_en FROM seguridad.nota_mencion m "
                "JOIN seguridad.nota n ON n.id = m.nota_id "
                "WHERE m.user_id=%s AND n.borrada=0 "
                "ORDER BY m.creada_en DESC, n.id DESC LIMIT %s",
                (user_id, int(limit))).fetchall()
        return [(_fila(r), r["mencion_leida_en"]) for r in rows]

    def marcar_leida(self, conn, user_id: str, nota_id: int, leida_en: str) -> None:
        conn.execute("UPDATE seguridad.nota_mencion SET leida_en=%s WHERE user_id=%s "
                     "AND nota_id=%s AND leida_en IS NULL", (leida_en, user_id, int(nota_id)))

    def marcar_todas_leidas(self, conn, user_id: str, leida_en: str) -> None:
        conn.execute("UPDATE seguridad.nota_mencion SET leida_en=%s WHERE user_id=%s "
                     "AND leida_en IS NULL", (leida_en, user_id))
```

(`Optional` ya está importado en los dos archivos; verificar.)

En `apu_tool/datos/perfiles_db.py::reset`, la tupla pasa a:

```python
            for t in ("auditoria", "nota_mencion", "nota", "perfiles"):
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_notas_contrato.py -q` → todo pasa (SQLite).
Run: `TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55433/apu_notas_test python -m pytest tests/test_notas_contrato.py tests/test_auditoria_contrato.py -q` → las variantes `[postgres]` pasan.
Run: `python -m pytest tests/ -q -p no:warnings` → verde.

- [ ] **Step 5: Commit**

```bash
git add db/seguridad.sql db/pg/seguridad.sql supabase/migrations/0008_menciones_rls.sql apu_tool/datos/repositorio.py apu_tool/datos/notas_db.py apu_tool/datos/pg/notas_pg.py apu_tool/datos/perfiles_db.py tests/test_notas_contrato.py
git commit -m "feat(notas): tabla nota_mencion y su repo en los dos backends"
```

---

### Task 2: Servicio y API de menciones + conteo en presencia

**Files:**
- Modify: `apu_tool/servicio/notas.py`
- Modify: `apu_tool/servicio/esquemas.py` (`NotaNuevaIn`, `NotaEditarIn`)
- Modify: `apu_tool/servicio/rutas.py` (endpoints de notas, `/presencia`, nuevos endpoints)
- Modify: `tests/test_api_presencia.py` (la respuesta suma una clave)
- Test: `tests/test_api_menciones.py`

**Interfaces:**
- Consumes: métodos de la Task 1; `alm.perfiles.listar() -> list[Perfil]` (con `user_id`, `email`, `nombre`, `estado`); lo existente de `servicio/notas.py` (`_out`, `crear`, `editar`, `listar`, `todas`, `_vigente`, `_ahora`, `_resolver_dueno`, `_texto_valido`, `_dueno`).
- Produces:
  - Nota JSON suma `menciones: [{user_id, nombre}]`.
  - `POST /api/notas` y `PATCH /api/notas/{id}` aceptan `menciones: [user_id]` (en PATCH, omitirlo = no tocar las menciones).
  - `GET /api/usuarios/mencionables` (editor) → `[{user_id, nombre, email}]`.
  - `GET /api/menciones` (consulta) → `[{nota_id, etiqueta, autor_email, creada_en, texto, leida, dueno}]` (texto recortado a 160).
  - `POST /api/menciones/{nota_id}/leida` (consulta) → `{"leida": nota_id}`.
  - `POST /api/menciones/leidas` (consulta) → `{"leidas": true}`.
  - `GET /api/presencia` → `{"en_linea": [...], "menciones_sin_leer": int | null}`.

- [ ] **Step 1: Write the failing test**

`tests/test_api_menciones.py`:

```python
# tests/test_api_menciones.py
from fastapi.testclient import TestClient

from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Insumo, Perfil
from apu_tool.servicio import presencia
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual

INS = {"entidad": "insumo", "codigo": "4520", "nombre": "DUCTO PVC"}
ANA = Perfil(user_id="u-ana", email="ana@obra.co", rol="editor", estado="activo", nombre="Ana")
BETO = Perfil(user_id="u-beto", email="beto@obra.co", rol="consulta", estado="activo", nombre="")
CARO = Perfil(user_id="u-caro", email="caro@obra.co", rol="editor", estado="inactivo", nombre="Caro")


def _app(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    alm.precios.insert_insumos([Insumo("4520", "DUCTO PVC", "ML", "D", 1.0, "COSTO INTERNO")])
    for p in (ANA, BETO, CARO):
        alm.perfiles.upsert(p)
    return create_app(almacen=alm), alm


def _como(app, p):
    app.dependency_overrides[usuario_actual] = lambda: p
    return TestClient(app)


def setup_function():
    presencia._vistos.clear()


def test_crear_con_menciones_valida_y_avisa(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    # se descartan: ella misma, un inactivo, uno que no existe y el duplicado
    r = ana.post("/api/notas", json={**INS, "texto": "@beto revisa",
                                     "menciones": ["u-beto", "u-ana", "u-caro", "u-x", "u-beto"]})
    assert r.status_code == 200, r.text
    assert r.json()["menciones"] == [{"user_id": "u-beto", "nombre": "beto@obra.co"}]
    beto = _como(app, BETO)
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 1
    bandeja = beto.get("/api/menciones").json()
    assert len(bandeja) == 1 and bandeja[0]["leida"] is False
    assert bandeja[0]["autor_email"] == "ana@obra.co" and bandeja[0]["texto"] == "@beto revisa"
    assert bandeja[0]["dueno"]["codigo"] == "4520"


def test_listar_notas_trae_las_menciones(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    ana.post("/api/notas", json={**INS, "texto": "sin menciones"})
    ana.post("/api/notas", json={**INS, "texto": "@beto", "menciones": ["u-beto"]})
    lista = ana.get("/api/notas", params=INS).json()
    assert [n["menciones"] for n in lista] == [[], [{"user_id": "u-beto", "nombre": "beto@obra.co"}]]


def test_editar_resincroniza_y_omitirlas_no_las_toca(tmp_path):
    app, alm = _app(tmp_path)
    ana = _como(app, ANA)
    nid = ana.post("/api/notas", json={**INS, "texto": "@beto", "menciones": ["u-beto"]}).json()["id"]
    beto = _como(app, BETO)
    beto.post(f"/api/menciones/{nid}/leida")
    ana = _como(app, ANA)
    # PATCH sin `menciones`: solo cambia el texto; beto sigue mencionado y leído
    r = ana.patch(f"/api/notas/{nid}", json={"texto": "@beto corregido"})
    assert r.json()["menciones"] == [{"user_id": "u-beto", "nombre": "beto@obra.co"}]
    assert alm.notas.contar_sin_leer("u-beto") == 0
    # PATCH con lista vacía: se van todas
    assert ana.patch(f"/api/notas/{nid}", json={"texto": "nadie", "menciones": []}).json()["menciones"] == []
    assert _como(app, BETO).get("/api/menciones").json() == []


def test_marcar_leida_y_todas(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    a = ana.post("/api/notas", json={**INS, "texto": "1", "menciones": ["u-beto"]}).json()["id"]
    ana.post("/api/notas", json={**INS, "texto": "2", "menciones": ["u-beto"]})
    beto = _como(app, BETO)
    assert beto.post(f"/api/menciones/{a}/leida").json() == {"leida": a}
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 1
    assert beto.post("/api/menciones/leidas").json() == {"leidas": True}
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 0
    assert all(m["leida"] for m in beto.get("/api/menciones").json())


def test_borrar_la_nota_saca_la_mencion(tmp_path):
    app, _ = _app(tmp_path)
    ana = _como(app, ANA)
    nid = ana.post("/api/notas", json={**INS, "texto": "x", "menciones": ["u-beto"]}).json()["id"]
    ana.delete(f"/api/notas/{nid}")
    beto = _como(app, BETO)
    assert beto.get("/api/presencia").json()["menciones_sin_leer"] == 0
    assert beto.get("/api/menciones").json() == []


def test_mencionables_solo_editor_y_sin_uno_mismo(tmp_path):
    app, _ = _app(tmp_path)
    assert _como(app, BETO).get("/api/usuarios/mencionables").status_code == 403
    r = _como(app, ANA).get("/api/usuarios/mencionables").json()
    assert r == [{"user_id": "u-beto", "nombre": "", "email": "beto@obra.co"}]   # sin Ana ni Caro (inactiva)


def test_presencia_no_se_cae_si_falla_el_conteo(tmp_path, monkeypatch):
    app, alm = _app(tmp_path)
    def boom(_uid):
        raise RuntimeError("base caída")
    monkeypatch.setattr(alm.notas, "contar_sin_leer", boom)
    r = _como(app, BETO).get("/api/presencia")
    assert r.status_code == 200 and r.json()["menciones_sin_leer"] is None
    assert r.json()["en_linea"][0]["email"] == "beto@obra.co"


def test_auditoria_de_crear_guarda_las_menciones(tmp_path):
    app, alm = _app(tmp_path)
    _como(app, ANA).post("/api/notas", json={**INS, "texto": "x", "menciones": ["u-beto"]})
    items, _ = alm.auditoria.listar(entidad_tipo="nota")
    assert items[0]["despues"]["menciones"] == ["u-beto"]
```

En `tests/test_api_presencia.py`, las aserciones de igualdad exacta sobre la respuesta (p. ej. línea 35 `assert r.json() == {"en_linea": [...]}`) pasan a mirar solo `en_linea`: `assert r.json()["en_linea"] == [...]`. Hacer ese cambio mínimo en cada aserción de ese estilo del archivo.

- [ ] **Step 2: Run test to verify it fails**

Run: `python -m pytest tests/test_api_menciones.py -q`
Expected: FAIL (`KeyError: 'menciones'`, 404 en `/api/menciones`, etc.)

- [ ] **Step 3: Write minimal implementation**

`apu_tool/servicio/esquemas.py`:

```python
class NotaNuevaIn(BaseModel):
    entidad: str                 # insumo | apu
    codigo: str
    nombre: str = ""             # insumo: parte de la identidad
    turno: str = ""              # apu: parte de la identidad
    texto: str
    menciones: list[str] = []    # user_id de los mencionados (los valida el servidor)


class NotaEditarIn(BaseModel):
    texto: str
    menciones: Optional[list[str]] = None   # None = no tocar las menciones
```

(verificar que `Optional` esté importado en `esquemas.py`.)

`apu_tool/servicio/notas.py` — agregar/cambiar:

```python
def _perfiles(alm: Almacen) -> dict[str, Perfil]:
    """user_id → Perfil. La tabla de perfiles es chica (decenas): una lectura por request."""
    return {p.user_id: p for p in alm.perfiles.listar()}


def _nombre(p: Optional[Perfil], uid: str) -> str:
    return (p.nombre or p.email) if p else uid


def _menciones_validas(perfiles: dict[str, Perfil], actor: Perfil,
                       pedidas: list[str]) -> list[str]:
    """Solo perfiles activos, sin el propio autor, sin duplicados, en el orden pedido.
    El cliente dice a quién quiere mencionar; el servidor decide a quién se puede."""
    out: list[str] = []
    for uid in pedidas or []:
        p = perfiles.get(uid)
        if p and p.estado == "activo" and uid != actor.user_id and uid not in out:
            out.append(uid)
    return out


def _salidas(alm: Almacen, notas: list[Nota], actor: Perfil) -> list[dict]:
    """Notas → JSON con sus menciones, en lote (una consulta para todas)."""
    menc = alm.notas.menciones_de_notas([n.id for n in notas])
    perfiles = _perfiles(alm) if menc else {}
    return [_out(n, actor, [{"user_id": u, "nombre": _nombre(perfiles.get(u), u)}
                            for u in menc.get(n.id, [])]) for n in notas]
```

y cambiar `_out` para recibir las menciones:

```python
def _out(n: Nota, actor: Perfil, menciones: list[dict]) -> dict:
    mia = actor.user_id == n.autor_id
    escribe = actor.rol in ("editor", "admin")
    return {"id": n.id, "entidad": n.entidad, "etiqueta": n.etiqueta, "texto": n.texto,
            "autor_email": n.autor_email, "creada_en": n.creada_en,
            "editada_en": n.editada_en, "es_mia": mia,
            "puede_editar": mia and escribe,
            "puede_borrar": escribe and _puede_borrar(n, actor),
            "dueno": _dueno(n), "menciones": menciones}
```

`listar` y `todas` usan `_salidas`:

```python
    return _salidas(alm, alm.notas.listar(entidad, clave), actor)
```

```python
    return {"items": _salidas(alm, items, actor), "total": total,
            "limit": limit, "offset": offset}
```

`crear` y `editar`:

```python
def crear(alm: Almacen, actor: Perfil, entidad: str, codigo: str, nombre: str,
          turno: str, texto: str, menciones: Optional[list[str]] = None) -> dict:
    t = _texto_valido(texto)
    clave, etiqueta = _resolver_dueno(alm, entidad, codigo, nombre, turno)
    uids = _menciones_validas(_perfiles(alm), actor, menciones or [])
    ahora = _ahora()
    with alm.transaccion("seguridad") as conn:
        nid = alm.notas.crear(conn, entidad, clave, etiqueta, t, actor.user_id,
                              actor.email, ahora)
        alm.notas.set_menciones(conn, nid, uids, ahora)
        registrar_auditoria(alm, conn, actor, "nota.crear", "nota", nid, antes=None,
                            despues={"entidad": entidad, "clave": clave, "texto": t,
                                     "menciones": uids})
    return _salidas(alm, [alm.notas.get(nid)], actor)[0]


def editar(alm: Almacen, actor: Perfil, nota_id: int, texto: str,
           menciones: Optional[list[str]] = None) -> dict:
    """`menciones=None` deja las menciones como están; una lista (aun vacía) las
    resincroniza: los nuevos reciben aviso, los quitados pierden el suyo."""
    n = _vigente(alm, nota_id)
    if actor.user_id != n.autor_id:
        raise SinPermiso("Solo quien escribió la nota puede editarla.")
    t = _texto_valido(texto)
    uids = (None if menciones is None
            else _menciones_validas(_perfiles(alm), actor, menciones))
    ahora = _ahora()
    with alm.transaccion("seguridad") as conn:
        alm.notas.editar(conn, n.id, t, ahora)
        if uids is not None:
            alm.notas.set_menciones(conn, n.id, uids, ahora)
        despues = {"texto": t} if uids is None else {"texto": t, "menciones": uids}
        registrar_auditoria(alm, conn, actor, "nota.editar", "nota", n.id,
                            antes={"texto": n.texto}, despues=despues)
    return _salidas(alm, [alm.notas.get(n.id)], actor)[0]
```

Bandeja y mencionables (al final del archivo):

```python
def mencionables(alm: Almacen, actor: Perfil) -> list[dict]:
    """A quién se puede mencionar: perfiles activos menos quien pregunta. Solo nombre,
    email e id (la barra de presencia ya les muestra eso mismo a todos)."""
    out = [{"user_id": p.user_id, "nombre": p.nombre or "", "email": p.email}
           for p in alm.perfiles.listar()
           if p.estado == "activo" and p.user_id != actor.user_id]
    return sorted(out, key=lambda u: (u["nombre"] or u["email"]).lower())


def bandeja(alm: Almacen, actor: Perfil, limit: int = 50) -> list[dict]:
    return [{"nota_id": n.id, "etiqueta": n.etiqueta, "autor_email": n.autor_email,
             "creada_en": n.creada_en, "texto": n.texto[:160], "leida": leida is not None,
             "dueno": _dueno(n)}
            for n, leida in alm.notas.listar_menciones(actor.user_id, limit)]


def marcar_leida(alm: Almacen, actor: Perfil, nota_id: int) -> None:
    with alm.transaccion("seguridad") as conn:
        alm.notas.marcar_leida(conn, actor.user_id, nota_id, _ahora())


def marcar_todas_leidas(alm: Almacen, actor: Perfil) -> None:
    with alm.transaccion("seguridad") as conn:
        alm.notas.marcar_todas_leidas(conn, actor.user_id, _ahora())


def sin_leer(alm: Almacen, actor: Perfil) -> Optional[int]:
    """Para la presencia: si la base falla, None; la presencia no se cae por esto."""
    try:
        return alm.notas.contar_sin_leer(actor.user_id)
    except Exception:
        return None
```

`apu_tool/servicio/rutas.py`:

- `/presencia` pasa a recibir el almacén (el docstring se actualiza: ya toca la base, UNA cuenta liviana por latido):

```python
@router.get("/presencia")
def presencia(usuario=Depends(requiere_rol("consulta")),
              alm: Almacen = Depends(get_almacen)):
    """Quién está usando la app ahora, y cuántas menciones sin leer tiene el que
    pregunta. Pedirla te marca presente: el latido es el poll del frontend (cada 45 s),
    no hay endpoint de latido aparte.

    El conteo de menciones viaja aquí A PROPÓSITO: la barra ya late cada 45 s, y un
    sondeo aparte para la campanita costaría las mismas consultas y el doble de
    peticiones. Es un COUNT por latido; si falla, sale null y la presencia sigue."""
    presencia_svc.marcar(usuario)
    return {"en_linea": presencia_svc.en_linea(),
            "menciones_sin_leer": notas_svc.sin_leer(alm, usuario)}
```

- `notas_crear` y `notas_editar` pasan las menciones:

```python
    return _http_notas(lambda: notas_svc.crear(alm, actor, body.entidad, body.codigo,
                                               body.nombre, body.turno, body.texto,
                                               body.menciones))
```

```python
    return _http_notas(lambda: notas_svc.editar(alm, actor, nota_id, body.texto,
                                                body.menciones))
```

- endpoints nuevos, en la sección de notas (declarar `/usuarios/mencionables` **antes** de cualquier ruta `/usuarios/{...}` con parámetro si existe — revisar el orden en el archivo):

```python
@router.get("/usuarios/mencionables")
def usuarios_mencionables(alm: Almacen = Depends(get_almacen),
                          actor=Depends(requiere_rol("editor"))):
    return notas_svc.mencionables(alm, actor)


@router.get("/menciones")
def menciones_listar(alm: Almacen = Depends(get_almacen),
                     actor=Depends(requiere_rol("consulta"))):
    return notas_svc.bandeja(alm, actor)


@router.post("/menciones/leidas")
def menciones_todas_leidas(alm: Almacen = Depends(get_almacen),
                           actor=Depends(requiere_rol("consulta"))):
    notas_svc.marcar_todas_leidas(alm, actor)
    return {"leidas": True}


@router.post("/menciones/{nota_id}/leida")
def menciones_leida(nota_id: int, alm: Almacen = Depends(get_almacen),
                    actor=Depends(requiere_rol("consulta"))):
    notas_svc.marcar_leida(alm, actor, nota_id)
    return {"leida": nota_id}
```

- [ ] **Step 4: Run test to verify it passes**

Run: `python -m pytest tests/test_api_menciones.py tests/test_api_notas.py tests/test_api_notas_listados.py tests/test_api_presencia.py tests/test_presencia.py -q` → todo pasa.
Run: `python -m pytest tests/ -q -p no:warnings` → verde.

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/notas.py apu_tool/servicio/esquemas.py apu_tool/servicio/rutas.py tests/test_api_menciones.py tests/test_api_presencia.py
git commit -m "feat(notas): menciones validadas en el servidor, bandeja y conteo en la presencia"
```

---

### Task 3: Web — autocompletado de `@` en el panel de notas

**Files:**
- Modify: `web/src/lib/tipos.ts`
- Modify: `web/src/api/notas.ts`
- Create: `web/src/lib/menciones.ts` + `web/src/lib/menciones.test.ts`
- Create: `web/src/components/notas/CajaConMenciones.tsx`
- Create: `web/src/components/notas/TextoConMenciones.tsx`
- Modify: `web/src/components/notas/DialogoNotas.tsx`
- Modify: `web/src/components/notas/DialogoNotas.test.tsx`
- Modify (mocks): `web/src/components/insumos/TablaInsumos.notas.test.tsx`, `web/src/pages/Apus.notas.test.tsx`, `web/src/pages/Notas.test.tsx` — agregar `listarMencionables: vi.fn(async () => [])` al `vi.mock("@/api/notas", ...)` de cada uno (el panel lo pide al abrir si el usuario escribe).

**Interfaces:**
- Consumes: endpoints de la Task 2.
- Produces:
  - tipos: `MencionNota = { user_id: string; nombre: string }`; `Nota.menciones: MencionNota[]`; `Mencionable = { user_id: string; nombre: string; email: string }`; `Mencion = { nota_id: number; etiqueta: string; autor_email: string; creada_en: string; texto: string; leida: boolean; dueno: DuenoNota }`; `PresenciaResponse.menciones_sin_leer?: number | null`.
  - api: `crearNota(d, texto, menciones: string[] = [])`, `editarNota(id, texto, menciones?: string[])`, `listarMencionables(): Promise<Mencionable[]>`, `listarMenciones(): Promise<Mencion[]>`, `marcarMencionLeida(notaId: number)`, `marcarMencionesLeidas()`.
  - `lib/menciones.ts`: `etiquetaDe(u: {nombre: string; email: string}): string`, `consultaMencion(texto: string, cursor: number): { inicio: number; q: string } | null`, `insertarMencion(texto: string, inicio: number, cursor: number, etiqueta: string): { texto: string; cursor: number }`, `mencionesVigentes(texto: string, elegidos: MencionNota[]): string[]`, `partesConMenciones(texto: string, nombres: string[]): { texto: string; mencion: boolean }[]`.
  - `<CajaConMenciones ariaLabel valor onValor elegidos onElegidos mencionables rows? placeholder? maxLength? />`
  - `<TextoConMenciones texto nombres />`

- [ ] **Step 1: Write the failing tests**

`web/src/lib/menciones.test.ts`:

```ts
import { describe, expect, it } from "vitest";
import {
  consultaMencion, etiquetaDe, insertarMencion, mencionesVigentes, partesConMenciones,
} from "./menciones";

describe("menciones", () => {
  it("etiquetaDe usa el nombre y, si no hay, el email", () => {
    expect(etiquetaDe({ nombre: "Ana Ruiz", email: "a@o.co" })).toBe("Ana Ruiz");
    expect(etiquetaDe({ nombre: "", email: "a@o.co" })).toBe("a@o.co");
  });

  it("consultaMencion detecta la @ justo antes del cursor", () => {
    expect(consultaMencion("hola @an", 8)).toEqual({ inicio: 5, q: "an" });
    expect(consultaMencion("@", 1)).toEqual({ inicio: 0, q: "" });
    expect(consultaMencion("correo a@b", 10)).toBeNull();       // @ pegada a una palabra
    expect(consultaMencion("@ana listo", 10)).toBeNull();       // ya hay espacio después
    expect(consultaMencion("sin arroba", 10)).toBeNull();
  });

  it("insertarMencion reemplaza la consulta por @Etiqueta y un espacio", () => {
    expect(insertarMencion("hola @an", 5, 8, "Ana Ruiz")).toEqual({ texto: "hola @Ana Ruiz ", cursor: 15 });
    expect(insertarMencion("@b y más", 0, 2, "Beto")).toEqual({ texto: "@Beto  y más", cursor: 6 });
  });

  it("mencionesVigentes solo deja a los que siguen escritos en el texto", () => {
    const elegidos = [{ user_id: "u1", nombre: "Ana Ruiz" }, { user_id: "u2", nombre: "Beto" }];
    expect(mencionesVigentes("ojo @Ana Ruiz", elegidos)).toEqual(["u1"]);
    expect(mencionesVigentes("@Beto y @Ana Ruiz", elegidos)).toEqual(["u1", "u2"]);
    expect(mencionesVigentes("nadie", elegidos)).toEqual([]);
  });

  it("partesConMenciones separa los @Nombre para resaltarlos", () => {
    expect(partesConMenciones("hola @Ana Ruiz, mira", ["Ana Ruiz"])).toEqual([
      { texto: "hola ", mencion: false },
      { texto: "@Ana Ruiz", mencion: true },
      { texto: ", mira", mencion: false },
    ]);
    expect(partesConMenciones("sin nada", ["Ana"])).toEqual([{ texto: "sin nada", mencion: false }]);
    // el nombre más largo gana: "@Ana Ruiz" no se parte en "@Ana" + " Ruiz"
    expect(partesConMenciones("@Ana Ruiz", ["Ana", "Ana Ruiz"])).toEqual([{ texto: "@Ana Ruiz", mencion: true }]);
  });
});
```

Agregar a `web/src/components/notas/DialogoNotas.test.tsx`:
- en el `vi.mock("@/api/notas", ...)`, agregar `listarMencionables: (...a: unknown[]) => listarMencionables(...a),` con `const listarMencionables = vi.fn();` arriba, y en `beforeEach`: `listarMencionables.mockReset(); listarMencionables.mockResolvedValue([{ user_id: "u-beto", nombre: "Beto", email: "beto@obra.co" }]);`
- el objeto `nota()` suma `menciones: []`.
- tests nuevos:

```tsx
  it("escribir @ ofrece usuarios y manda la mención al crear", async () => {
    crearNota.mockResolvedValue(nota({ id: 2, texto: "@Beto mira", menciones: [{ user_id: "u-beto", nombre: "Beto" }] }));
    montar();
    await screen.findByText("cotización X");
    const caja = screen.getByLabelText("Nueva nota") as HTMLTextAreaElement;
    fireEvent.change(caja, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    fireEvent.click(await screen.findByRole("button", { name: "Mencionar a Beto" }));
    expect(caja.value).toBe("@Beto ");
    fireEvent.change(caja, { target: { value: "@Beto mira", selectionStart: 10, selectionEnd: 10 } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar nota" }));
    await waitFor(() => expect(crearNota).toHaveBeenCalledWith(DUENO, "@Beto mira", ["u-beto"]));
  });

  it("si borras el @Nombre del texto, no se manda la mención", async () => {
    crearNota.mockResolvedValue(nota({ id: 2, texto: "nada" }));
    montar();
    await screen.findByText("cotización X");
    const caja = screen.getByLabelText("Nueva nota") as HTMLTextAreaElement;
    fireEvent.change(caja, { target: { value: "@Be", selectionStart: 3, selectionEnd: 3 } });
    fireEvent.click(await screen.findByRole("button", { name: "Mencionar a Beto" }));
    fireEvent.change(caja, { target: { value: "nada", selectionStart: 4, selectionEnd: 4 } });
    fireEvent.click(screen.getByRole("button", { name: "Agregar nota" }));
    await waitFor(() => expect(crearNota).toHaveBeenCalledWith(DUENO, "nada", []));
  });

  it("resalta los nombres mencionados en la nota", async () => {
    listarNotas.mockResolvedValue([nota({ texto: "@Beto revisa", menciones: [{ user_id: "u-beto", nombre: "Beto" }] })]);
    montar();
    const resaltado = await screen.findByText("@Beto");
    expect(resaltado.getAttribute("data-mencion")).toBe("si");
  });

  it("editar conserva y manda las menciones vigentes", async () => {
    listarNotas.mockResolvedValue([nota({ texto: "@Beto revisa", menciones: [{ user_id: "u-beto", nombre: "Beto" }] })]);
    editarNota.mockResolvedValue(nota({ texto: "@Beto revisa ya", menciones: [{ user_id: "u-beto", nombre: "Beto" }] }));
    montar();
    fireEvent.click(await screen.findByRole("button", { name: "Editar" }));
    fireEvent.change(screen.getByLabelText("Editar nota"),
                     { target: { value: "@Beto revisa ya", selectionStart: 15, selectionEnd: 15 } });
    fireEvent.click(screen.getByRole("button", { name: "Guardar" }));
    await waitFor(() => expect(editarNota).toHaveBeenCalledWith(1, "@Beto revisa ya", ["u-beto"]));
  });
```

- el test existente de «agrega una nota» cambia su expectativa a `toHaveBeenCalledWith(DUENO, "nueva", [])`, y el de «edita la propia» a `toHaveBeenCalledWith(1, "corregida", [])`.
- el test de consulta: `listarMencionables` **no** debe llamarse (`expect(listarMencionables).not.toHaveBeenCalled()`).

- [ ] **Step 2: Run tests to verify they fail**

Run (en `web/`): `npx vitest run src/lib/menciones.test.ts src/components/notas`
Expected: FAIL (`Failed to resolve import "./menciones"` y los nuevos del diálogo).

- [ ] **Step 3: Write minimal implementation**

`web/src/lib/tipos.ts`: agregar

```ts
export interface MencionNota {
  user_id: string;
  nombre: string;
}

export interface Mencionable {
  user_id: string;
  nombre: string;
  email: string;
}

export interface Mencion {
  nota_id: number;
  etiqueta: string;
  autor_email: string;
  creada_en: string;
  texto: string;
  leida: boolean;
  dueno: DuenoNota;
}
```

en `interface Nota` agregar `menciones: MencionNota[];` y en `interface PresenciaResponse` agregar `menciones_sin_leer?: number | null;`.

`web/src/api/notas.ts`: cambiar `crearNota`/`editarNota` y agregar

```ts
export const crearNota = (d: DuenoNota, texto: string, menciones: string[] = []) =>
  apiPost<Nota>("/notas", { ...d, texto, menciones });

export const editarNota = (id: number, texto: string, menciones?: string[]) =>
  apiPatch<Nota>(`/notas/${id}`, menciones === undefined ? { texto } : { texto, menciones });

export const listarMencionables = () => apiGet<Mencionable[]>("/usuarios/mencionables");

export const listarMenciones = () => apiGet<Mencion[]>("/menciones");

export const marcarMencionLeida = (notaId: number) =>
  apiPost<{ leida: number }>(`/menciones/${notaId}/leida`);

export const marcarMencionesLeidas = () => apiPost<{ leidas: boolean }>("/menciones/leidas");
```

(sumar `Mencion`, `Mencionable` al `import type` de `@/lib/tipos`.)

`web/src/lib/menciones.ts`:

```ts
import type { MencionNota } from "@/lib/tipos";

/** Cómo se escribe a alguien después de la @: su nombre, o su email si no tiene. */
export function etiquetaDe(u: { nombre: string; email: string }): string {
  return u.nombre || u.email;
}

/** Si el cursor está justo después de "@algo" (la @ al inicio o tras un espacio, y sin
 *  espacios entre la @ y el cursor), devuelve dónde empieza y qué se lleva escrito. */
export function consultaMencion(texto: string, cursor: number): { inicio: number; q: string } | null {
  const antes = texto.slice(0, cursor);
  const i = antes.lastIndexOf("@");
  if (i < 0) return null;
  if (i > 0 && !/\s/.test(antes[i - 1])) return null;
  const q = antes.slice(i + 1);
  if (/\s/.test(q)) return null;
  return { inicio: i, q };
}

/** Reemplaza "@consulta" por "@Etiqueta " y deja el cursor después del espacio. */
export function insertarMencion(texto: string, inicio: number, cursor: number,
                                etiqueta: string): { texto: string; cursor: number } {
  const puesto = `@${etiqueta} `;
  return { texto: texto.slice(0, inicio) + puesto + texto.slice(cursor), cursor: inicio + puesto.length };
}

/** Los elegidos cuyo "@Nombre" sigue escrito: borrar el nombre del texto quita la mención. */
export function mencionesVigentes(texto: string, elegidos: MencionNota[]): string[] {
  const out: string[] = [];
  for (const e of elegidos) {
    if (texto.includes(`@${e.nombre}`) && !out.includes(e.user_id)) out.push(e.user_id);
  }
  return out.sort();
}

/** Parte el texto para resaltar los "@Nombre". Prueba primero los nombres más largos,
 *  para que "@Ana Ruiz" no se corte en "@Ana". */
export function partesConMenciones(texto: string, nombres: string[]): { texto: string; mencion: boolean }[] {
  const marcas = [...new Set(nombres.filter(Boolean))].sort((a, b) => b.length - a.length).map((n) => `@${n}`);
  const partes: { texto: string; mencion: boolean }[] = [];
  let resto = "";
  let i = 0;
  while (i < texto.length) {
    const m = marcas.find((x) => texto.startsWith(x, i));
    if (m) {
      if (resto) partes.push({ texto: resto, mencion: false });
      partes.push({ texto: m, mencion: true });
      resto = "";
      i += m.length;
    } else {
      resto += texto[i];
      i += 1;
    }
  }
  if (resto) partes.push({ texto: resto, mencion: false });
  return partes;
}
```

(Ojo: `mencionesVigentes` devuelve ordenado para que el payload sea estable; los tests esperan `["u1", "u2"]`.)

`web/src/components/notas/TextoConMenciones.tsx`:

```tsx
import { partesConMenciones } from "@/lib/menciones";

/** El texto de una nota con los @Nombre mencionados resaltados. */
export function TextoConMenciones({ texto, nombres }: { texto: string; nombres: string[] }) {
  return (
    <p className="mt-1 whitespace-pre-wrap">
      {partesConMenciones(texto, nombres).map((p, i) =>
        p.mencion ? (
          <span key={i} data-mencion="si" className="font-medium text-primary">{p.texto}</span>
        ) : (
          <span key={i}>{p.texto}</span>
        ),
      )}
    </p>
  );
}
```

`web/src/components/notas/CajaConMenciones.tsx`:

```tsx
import { useState } from "react";
import type { Mencionable, MencionNota } from "@/lib/tipos";
import { consultaMencion, etiquetaDe, insertarMencion } from "@/lib/menciones";

interface Props {
  ariaLabel: string;
  valor: string;
  onValor: (v: string) => void;
  elegidos: MencionNota[];
  onElegidos: (e: MencionNota[]) => void;
  mencionables: Mencionable[];
  rows?: number;
  placeholder?: string;
  maxLength?: number;
}

const areaCls =
  "w-full rounded border border-border bg-transparent px-2 py-1 text-xs outline-none " +
  "focus-visible:border-ring focus-visible:ring-2 focus-visible:ring-ring/40";
const MAX_SUGERENCIAS = 6;

/** Textarea con autocompletado de @: al escribir "@be" ofrece los usuarios cuyo nombre o
 *  email contiene "be"; escoger uno escribe "@Nombre " y lo suma a los elegidos. Qué
 *  menciones valen al guardar lo decide `mencionesVigentes` (lo que siga escrito). */
export function CajaConMenciones({ ariaLabel, valor, onValor, elegidos, onElegidos,
                                   mencionables, rows = 3, placeholder, maxLength = 4000 }: Props) {
  const [consulta, setConsulta] = useState<{ inicio: number; cursor: number; q: string } | null>(null);

  const q = (consulta?.q ?? "").toLocaleLowerCase("es");
  const sugerencias = consulta
    ? mencionables
        .filter((u) => etiquetaDe(u).toLocaleLowerCase("es").includes(q) ||
                       u.email.toLocaleLowerCase("es").includes(q))
        .slice(0, MAX_SUGERENCIAS)
    : [];

  function cambiar(e: React.ChangeEvent<HTMLTextAreaElement>) {
    const v = e.target.value;
    const cursor = e.target.selectionStart ?? v.length;
    onValor(v);
    const c = consultaMencion(v, cursor);
    setConsulta(c ? { ...c, cursor } : null);
  }

  function escoger(u: Mencionable) {
    if (!consulta) return;
    const etiqueta = etiquetaDe(u);
    onValor(insertarMencion(valor, consulta.inicio, consulta.cursor, etiqueta).texto);
    if (!elegidos.some((x) => x.user_id === u.user_id)) {
      onElegidos([...elegidos, { user_id: u.user_id, nombre: etiqueta }]);
    }
    setConsulta(null);
  }

  return (
    <div className="relative">
      <textarea aria-label={ariaLabel} rows={rows} className={areaCls} value={valor}
                maxLength={maxLength} placeholder={placeholder} onChange={cambiar}
                onKeyDown={(e) => { if (e.key === "Escape" && consulta) { e.stopPropagation(); setConsulta(null); } }} />
      {sugerencias.length > 0 && (
        <div className="absolute left-0 z-50 mt-1 w-64 rounded border border-border bg-background shadow">
          {sugerencias.map((u) => (
            <button key={u.user_id} type="button" aria-label={`Mencionar a ${etiquetaDe(u)}`}
                    className="block w-full px-2 py-1 text-left text-xs hover:bg-muted"
                    onMouseDown={(e) => e.preventDefault()} onClick={() => escoger(u)}>
              <span className="font-medium">{etiquetaDe(u)}</span>
              {u.nombre && <span className="ml-1 text-muted-foreground">{u.email}</span>}
            </button>
          ))}
        </div>
      )}
    </div>
  );
}
```

`web/src/components/notas/DialogoNotas.tsx` (sobre la versión actual, que ya tiene la clave estable `claveDueno`, `duenoRef`/`claveVigente` y la guarda post-await — **conservarlas**):
- importar `CajaConMenciones`, `TextoConMenciones`, `listarMencionables`, `mencionesVigentes` y los tipos `Mencionable`, `MencionNota`.
- estado nuevo: `const [mencionables, setMencionables] = useState<Mencionable[]>([]);`, `const [elegidosNueva, setElegidosNueva] = useState<MencionNota[]>([]);`; `editando` pasa a `{ id: number; texto: string; elegidos: MencionNota[] } | null`.
- en el efecto de carga (el que depende de `claveDueno`), además de listar notas: resetear `setElegidosNueva([])` y, **solo si `escribe`**, `listarMencionables().then((u) => { if (!cancelado) setMencionables(u); }).catch(() => {})` (sin toast: sin la lista igual se puede escribir). `escribe` va en las dependencias del efecto.
- `agregar`: `crearNota(dueno, nueva, mencionesVigentes(nueva, elegidosNueva))`; al tener éxito (y si la clave no cambió) también `setElegidosNueva([])`.
- botón «Editar»: `setEditando({ id: n.id, texto: n.texto, elegidos: n.menciones })`.
- `guardarEdicion`: `editarNota(editando.id, editando.texto, mencionesVigentes(editando.texto, editando.elegidos))`.
- el textarea de edición se reemplaza por
  `<CajaConMenciones ariaLabel="Editar nota" valor={editando.texto} onValor={(v) => setEditando({ ...editando, texto: v })} elegidos={editando.elegidos} onElegidos={(e) => setEditando({ ...editando, elegidos: e })} mencionables={mencionables} />`
- el de nueva nota por
  `<CajaConMenciones ariaLabel="Nueva nota" valor={nueva} onValor={setNueva} elegidos={elegidosNueva} onElegidos={setElegidosNueva} mencionables={mencionables} placeholder="Ej.: Precio extraído de la cotización de… (usa @ para avisarle a alguien)" />`
- el `<p className="mt-1 whitespace-pre-wrap">{n.texto}</p>` se reemplaza por `<TextoConMenciones texto={n.texto} nombres={n.menciones.map((m) => m.nombre)} />`.
- quitar la constante `areaCls` si queda sin uso.

- [ ] **Step 4: Run tests to verify they pass**

Run (en `web/`): `npx vitest run src/lib/menciones.test.ts src/components/notas` → todo pasa.
Run: `npx vitest run` (toda la suite; con los mocks de `listarMencionables` agregados en los 3 archivos listados) y `npm run build` → verdes.

- [ ] **Step 5: Commit**

```bash
git add web/src/lib/tipos.ts web/src/api/notas.ts web/src/lib/menciones.ts web/src/lib/menciones.test.ts web/src/components/notas web/src/components/insumos/TablaInsumos.notas.test.tsx web/src/pages/Apus.notas.test.tsx web/src/pages/Notas.test.tsx
git commit -m "feat(web): mencionar con @ en las notas"
```

---

### Task 4: Web — campanita en la barra superior

**Files:**
- Create: `web/src/components/notas/Campanita.tsx`
- Create: `web/src/components/notas/Campanita.test.tsx`
- Modify: `web/src/components/Layout.tsx`
- Modify: `web/src/components/Layout.test.tsx` (el mock de presencia suma `menciones_sin_leer`; mock de `@/api/notas`)

**Interfaces:**
- Consumes: `listarMenciones`, `marcarMencionLeida`, `marcarMencionesLeidas` (Task 3), `DialogoNotas`, `Mencion`, `PresenciaResponse.menciones_sin_leer`.
- Produces: `<Campanita sinLeer={number | null} onSinLeer={(n: number) => void} />`.

- [ ] **Step 1: Write the failing test**

`web/src/components/notas/Campanita.test.tsx`:

```tsx
import { describe, expect, it, vi, beforeEach } from "vitest";
import { render, screen, fireEvent, waitFor } from "@testing-library/react";
import { Campanita } from "./Campanita";

const listarMenciones = vi.fn();
const marcarMencionLeida = vi.fn();
const marcarMencionesLeidas = vi.fn();
const listarNotas = vi.fn(async () => []);
vi.mock("@/api/notas", () => ({
  listarMenciones: (...a: unknown[]) => listarMenciones(...a),
  marcarMencionLeida: (...a: unknown[]) => marcarMencionLeida(...a),
  marcarMencionesLeidas: (...a: unknown[]) => marcarMencionesLeidas(...a),
  listarNotas: (...a: unknown[]) => listarNotas(...(a as [])),
  listarMencionables: vi.fn(async () => []),
  crearNota: vi.fn(), editarNota: vi.fn(), borrarNota: vi.fn(),
}));
vi.mock("@/lib/auth", () => ({ useAuth: () => ({ perfil: { rol: "consulta" } }) }));

const DUENO = { entidad: "insumo" as const, codigo: "4520", nombre: "DUCTO", turno: "" };
const mencion = (over = {}) => ({
  nota_id: 7, etiqueta: "4520 · DUCTO", autor_email: "ana@obra.co",
  creada_en: "2026-09-30T10:00:00+00:00", texto: "@Beto revisa", leida: false, dueno: DUENO, ...over,
});

beforeEach(() => {
  [listarMenciones, marcarMencionLeida, marcarMencionesLeidas].forEach((f) => f.mockReset());
  listarMenciones.mockResolvedValue([mencion(), mencion({ nota_id: 8, leida: true, texto: "vieja" })]);
  marcarMencionLeida.mockResolvedValue({ leida: 7 });
  marcarMencionesLeidas.mockResolvedValue({ leidas: true });
});

describe("Campanita", () => {
  it("muestra el número sin leer solo si hay", () => {
    const { rerender } = render(<Campanita sinLeer={0} onSinLeer={() => {}} />);
    expect(screen.getByRole("button", { name: "Menciones" }).textContent).toBe("");
    rerender(<Campanita sinLeer={3} onSinLeer={() => {}} />);
    expect(screen.getByRole("button", { name: "Menciones (3 sin leer)" }).textContent).toContain("3");
  });

  it("abrir lista las menciones; clic en una la marca leída y abre la nota", async () => {
    const onSinLeer = vi.fn();
    render(<Campanita sinLeer={1} onSinLeer={onSinLeer} />);
    fireEvent.click(screen.getByRole("button", { name: /Menciones/ }));
    fireEvent.click(await screen.findByText("@Beto revisa"));
    await waitFor(() => expect(marcarMencionLeida).toHaveBeenCalledWith(7));
    expect(onSinLeer).toHaveBeenCalledWith(0);
    expect(await screen.findByText("Notas · 4520 · DUCTO")).toBeTruthy();
    expect(listarNotas).toHaveBeenCalledWith(DUENO);
  });

  it("marcar todas como leídas", async () => {
    const onSinLeer = vi.fn();
    render(<Campanita sinLeer={1} onSinLeer={onSinLeer} />);
    fireEvent.click(screen.getByRole("button", { name: /Menciones/ }));
    fireEvent.click(await screen.findByRole("button", { name: "Marcar todas como leídas" }));
    await waitFor(() => expect(marcarMencionesLeidas).toHaveBeenCalled());
    expect(onSinLeer).toHaveBeenCalledWith(0);
  });

  it("sin menciones lo dice", async () => {
    listarMenciones.mockResolvedValue([]);
    render(<Campanita sinLeer={0} onSinLeer={() => {}} />);
    fireEvent.click(screen.getByRole("button", { name: "Menciones" }));
    expect(await screen.findByText("Nadie te ha mencionado todavía.")).toBeTruthy();
  });
});
```

En `web/src/components/Layout.test.tsx`: el mock de `getPresencia` suma `menciones_sin_leer: 2`; agregar `vi.mock("@/api/notas", () => ({ listarMenciones: vi.fn(async () => []), marcarMencionLeida: vi.fn(), marcarMencionesLeidas: vi.fn(), listarNotas: vi.fn(async () => []), listarMencionables: vi.fn(async () => []), crearNota: vi.fn(), editarNota: vi.fn(), borrarNota: vi.fn() }));` y un test:

```tsx
test("la campanita muestra las menciones sin leer que trae la presencia", async () => {
  rol = "consulta";
  render(<MemoryRouter><Layout /></MemoryRouter>);
  expect(await screen.findByRole("button", { name: "Menciones (2 sin leer)" })).not.toBeNull();
});
```

- [ ] **Step 2: Run test to verify it fails**

Run (en `web/`): `npx vitest run src/components/notas/Campanita.test.tsx src/components/Layout.test.tsx`
Expected: FAIL (`Failed to resolve import "./Campanita"`).

- [ ] **Step 3: Write minimal implementation**

`web/src/components/notas/Campanita.tsx`:

```tsx
import { useState } from "react";
import { Bell } from "lucide-react";
import { toast } from "sonner";
import { Button } from "@/components/ui/button";
import { Dialog, DialogContent, DialogHeader, DialogTitle } from "@/components/ui/dialog";
import { listarMenciones, marcarMencionLeida, marcarMencionesLeidas } from "@/api/notas";
import type { DuenoNota, Mencion } from "@/lib/tipos";
import { DialogoNotas } from "./DialogoNotas";

interface Props {
  sinLeer: number | null;          // viene de la presencia (cada 45 s); null = no se sabe
  onSinLeer: (n: number) => void;  // corrige el número al leer, sin esperar el próximo latido
}

const fecha = (iso: string) => new Date(iso).toLocaleString("es-CO");

/** Campanita de menciones. El número lo trae la presencia; la lista se pide al abrir
 *  (una acción del usuario, no un sondeo). */
export function Campanita({ sinLeer, onSinLeer }: Props) {
  const [abierta, setAbierta] = useState(false);
  const [menciones, setMenciones] = useState<Mencion[] | null>(null);
  const [nota, setNota] = useState<{ dueno: DuenoNota; etiqueta: string } | null>(null);
  const n = sinLeer ?? 0;

  function abrir() {
    setAbierta(true);
    setMenciones(null);
    listarMenciones()
      .then(setMenciones)
      .catch((e) => {
        toast.error(e instanceof Error ? e.message : "No se pudieron cargar las menciones");
        setMenciones([]);
      });
  }

  const restantes = (lista: Mencion[]) => lista.filter((m) => !m.leida).length;

  async function ir(m: Mencion) {
    setAbierta(false);
    setNota({ dueno: m.dueno, etiqueta: m.etiqueta });
    if (m.leida) return;
    try {
      await marcarMencionLeida(m.nota_id);
      const lista = (menciones ?? []).map((x) => (x.nota_id === m.nota_id ? { ...x, leida: true } : x));
      setMenciones(lista);
      onSinLeer(restantes(lista));
    } catch {
      /* si no se pudo marcar, sigue sin leer: el próximo latido lo muestra igual */
    }
  }

  async function todas() {
    try {
      await marcarMencionesLeidas();
      setMenciones((prev) => (prev ?? []).map((x) => ({ ...x, leida: true })));
      onSinLeer(0);
    } catch (e) {
      toast.error(e instanceof Error ? e.message : "No se pudieron marcar las menciones");
    }
  }

  return (
    <>
      <button type="button" onClick={abrir}
              aria-label={n > 0 ? `Menciones (${n} sin leer)` : "Menciones"}
              className="relative inline-flex h-7 w-7 items-center justify-center rounded hover:bg-muted">
        <Bell className="h-4 w-4" aria-hidden />
        {n > 0 && (
          <span className="absolute -right-0.5 -top-0.5 min-w-4 rounded-full bg-primary px-1 text-[9px] font-semibold leading-4 text-primary-foreground">
            {n}
          </span>
        )}
      </button>

      <Dialog open={abierta} onOpenChange={setAbierta}>
        <DialogContent className="max-w-lg">
          <DialogHeader>
            <DialogTitle className="text-sm">Menciones</DialogTitle>
          </DialogHeader>
          <div className="max-h-[60vh] space-y-1 overflow-y-auto">
            {menciones === null && <p className="text-xs text-muted-foreground">Cargando…</p>}
            {menciones?.length === 0 && (
              <p className="text-xs text-muted-foreground">Nadie te ha mencionado todavía.</p>
            )}
            {menciones?.map((m) => (
              <button key={m.nota_id} type="button" onClick={() => ir(m)}
                      className={"block w-full rounded px-2 py-1.5 text-left text-xs hover:bg-muted " +
                                 (m.leida ? "text-muted-foreground" : "font-medium")}>
                <span className="block">
                  {m.autor_email} · {m.etiqueta} · {fecha(m.creada_en)}
                </span>
                <span className="block truncate">{m.texto}</span>
              </button>
            ))}
          </div>
          {menciones && restantes(menciones) > 0 && (
            <div className="flex justify-end">
              <Button size="xs" variant="outline" onClick={todas}>Marcar todas como leídas</Button>
            </div>
          )}
        </DialogContent>
      </Dialog>

      <DialogoNotas dueno={nota?.dueno ?? null} etiqueta={nota?.etiqueta ?? ""}
                    onClose={() => setNota(null)} onCambio={() => {}} />
    </>
  );
}
```

`web/src/components/Layout.tsx`:
- `import { Campanita } from "@/components/notas/Campanita";`
- estado: `const [sinLeer, setSinLeer] = useState<number | null>(null);`
- en el `.then` del poll de presencia: `if (vivo) { setEnLinea(r.en_linea); setSinLeer(r.menciones_sin_leer ?? null); }`
- en la barra, justo antes del `<span ...>` con el correo y el rol:

```tsx
              <Campanita sinLeer={sinLeer} onSinLeer={setSinLeer} />
```

- [ ] **Step 4: Run tests to verify they pass**

Run (en `web/`): `npx vitest run src/components/notas src/components/Layout.test.tsx` → pasa.
Run: `npx vitest run` y `npm run build` → verdes.

- [ ] **Step 5: Commit**

```bash
git add web/src/components/notas/Campanita.tsx web/src/components/notas/Campanita.test.tsx web/src/components/Layout.tsx web/src/components/Layout.test.tsx
git commit -m "feat(web): campanita de menciones en la barra"
```

---

### Task 5: Documentación + verificación completa

**Files:**
- Modify: `CLAUDE.md`

- [ ] **Step 1: Documentar**

En `CLAUDE.md`, en la viñeta **«Notas de insumos y APUs.»** de la sección *Datos*, agregar al final (antes de la mención de las fases):

```markdown
  **Menciones (Fase 2):** tabla `nota_mencion` (mismo schema, mismo repo `alm.notas`).
  El cliente manda `menciones: [user_id]`; el servidor las valida contra perfiles
  activos, saca al propio autor y deduplica — **no** las deduce del texto. Editar
  resincroniza (`menciones` omitido en el PATCH = no tocar). El conteo sin leer viaja en
  `GET /api/presencia` (`menciones_sin_leer`, `null` si falla): la barra ya late cada 45 s,
  así que la campanita **no** agrega sondeo. `GET /api/usuarios/mencionables` es de
  editor y solo expone id, nombre y email. RLS manual en prod:
  `supabase/migrations/0008_menciones_rls.sql`.
```

y en la sección **No hacer**, a la viñeta de notas, agregar:

```markdown
  Tampoco saques el conteo de menciones de la presencia a un sondeo propio: sería el
  mismo COUNT con el doble de peticiones.
```

- [ ] **Step 2: Suites completas**

Run: `python -m pytest tests/ -q -p no:warnings` → verde.
Run: `TEST_DATABASE_URL=postgresql://postgres@127.0.0.1:55433/apu_notas_test python -m pytest tests/test_notas_contrato.py -q` → verde.
Run (en `web/`): `npx vitest run` y `npm run build` → verdes.

- [ ] **Step 3: Commit**

```bash
git add CLAUDE.md
git commit -m "docs: menciones de notas en CLAUDE.md"
```

- [ ] **Step 4: Prueba en navegador (la hace el controlador)**

Misma receta de la Fase 1 (app real sobre copia de `data/`, sesión simulada, dos servidores con perfiles distintos). **Los dos perfiles tienen que existir activos en la copia de `seguridad.db`** para que sean mencionables (sembrarlos con `alm.perfiles.upsert` en el script del servidor). Chequeos:
1. Editor A escribe `@` en una nota y ve a B en la lista; lo escoge; el texto queda `@B `; guarda; el nombre sale resaltado.
2. En la pestaña de B, al siguiente latido (o recargando), la campanita muestra 1.
3. B abre la campanita, hace clic en la mención: se abre el panel de esa nota y la campanita baja a 0.
4. A edita la nota quitando `@B`: la mención desaparece de la bandeja de B.
5. Capturas de la barra con la campanita, la lista y el autocompletado.

- [ ] **Step 5: Pendiente manual en producción**

Aplicar `supabase/migrations/0008_menciones_rls.sql` en el SQL editor de Supabase tras el deploy (junto con `0007` y `0005`, si siguen pendientes).
