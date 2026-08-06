> Espejo automático — no editar aquí. Fuente: `docs/superpowers/plans/2026-08-06-presencia-y-busqueda-relevante.md`

# Presencia en línea + búsqueda por relevancia — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Mostrar quién está usando la app ahora mismo, y ordenar los resultados de las barras de búsqueda por relevancia en vez de por código.

**Architecture:** Dos features sin un solo archivo en común. Presencia = un `dict` en memoria del proceso web, marcado por el propio poll del frontend, sin DB. Relevancia = un helper puro nuevo (`apu_tool/nucleo/relevancia.py`) que filtra y ordena filas por nivel de coincidencia y desempata con el scorer `similarity` que ya existía en `dominio/matching.py` (se mueve a núcleo y se reexporta). En APUs (~1200 filas) el filtro por texto se hace entero en Python; en Insumos (7167 visibles con JOIN a precios) el `WHERE` se queda en SQL y solo el orden va en Python.

**Tech Stack:** Python 3 / FastAPI / SQLite + Postgres (psycopg) / pytest · React + TypeScript / Vite / vitest / Tailwind

**Spec:** `docs/superpowers/specs/2026-08-06-presencia-y-busqueda-relevante-design.md`

## Global Constraints

- **Invariante #1: la IA nunca ve dinero.** Ninguna tarea de este plan agrega una llamada a la IA. `nucleo/relevancia.py` no toca precios. `servicio/presencia.py` no toca el `Almacen`.
- **Español** en nombres de dominio, comentarios, docstrings y mensajes de usuario.
- **Sin dependencias nuevas.** Solo stdlib (`difflib`, `functools`, `time`) y lo ya instalado.
- **Toda la persistencia vive en `apu_tool/datos/`.** No hay SQL crudo fuera de ahí.
- **Doble backend obligatorio:** todo cambio en `datos/*_db.py` (SQLite) tiene su espejo 1:1 en `datos/pg/*_pg.py` (Postgres). Un cambio en uno solo es un bug de producción.
- **Cero cambios de esquema y cero migraciones** en todo el plan.
- **Sin `q` nada cambia:** mismo SQL, mismo orden por código, mismo `total`, mismo costo.
- **Redondeo / dinero:** ninguna tarea toca `pricing.py` ni multiplicaciones monetarias.
- **Rama:** `feat/presencia-y-busqueda-relevante` (ya creada). **No se pushea a master sin OK explícito** del dueño del repo.
- **Estilo de la barra superior:** densa, sin cards, `text-[13px]`, etiquetas en `uppercase tracking-[0.1em]`. Se reusa el componente `Lectura` que ya está en `Layout.tsx`.
- Comentar los techos deliberados con un comentario `ponytail:` que nombre el techo y el upgrade.

---

# FASE 1 — Presencia

### Task 1: Módulo de presencia (`servicio/presencia.py`)

**Files:**
- Create: `apu_tool/servicio/presencia.py`
- Test: `tests/test_presencia.py`

**Interfaces:**
- Consumes: `apu_tool.nucleo.models.Perfil` (campos `user_id`, `email`, `nombre`).
- Produces:
  - `VENTANA_S: float = 90.0`
  - `marcar(perfil, *, ahora: float | None = None) -> None`
  - `en_linea(*, ahora: float | None = None) -> list[dict]` → `[{"user_id": str, "email": str, "nombre": str}, ...]` ordenado por `nombre or email`
  - `_vistos: dict[str, tuple[float, str, str]]` (privado; los tests lo limpian con `_vistos.clear()`)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_presencia.py`:

```python
"""Presencia: quién está usando la app ahora mismo.

El reloj se inyecta (`ahora=`) en vez de dormir: un test que espera 91 segundos
reales no lo corre nadie.
"""
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import presencia


def _perfil(uid="u1", email="ana@obra.co", nombre="Ana"):
    return Perfil(user_id=uid, email=email, rol="editor", estado="activo", nombre=nombre)


def setup_function():
    presencia._vistos.clear()


def test_marcar_deja_al_usuario_en_linea():
    presencia.marcar(_perfil(), ahora=1000.0)
    assert presencia.en_linea(ahora=1000.0) == [
        {"user_id": "u1", "email": "ana@obra.co", "nombre": "Ana"}]


def test_pasada_la_ventana_ya_no_esta_en_linea():
    presencia.marcar(_perfil(), ahora=1000.0)
    assert presencia.en_linea(ahora=1000.0 + presencia.VENTANA_S + 1) == []


def test_un_latido_dentro_de_la_ventana_lo_mantiene():
    """El frontend late cada 45 s con ventana de 90 s: dos latidos de margen, así
    una petición perdida no apaga el punto."""
    presencia.marcar(_perfil(), ahora=1000.0)
    presencia.marcar(_perfil(), ahora=1045.0)
    assert len(presencia.en_linea(ahora=1091.0)) == 1


def test_varios_usuarios_ordenados_por_nombre():
    presencia.marcar(_perfil("u1", "zoe@obra.co", "Zoe"), ahora=1000.0)
    presencia.marcar(_perfil("u2", "ana@obra.co", "Ana"), ahora=1000.0)
    assert [p["nombre"] for p in presencia.en_linea(ahora=1000.0)] == ["Ana", "Zoe"]


def test_sin_nombre_ordena_y_muestra_por_correo():
    """Un usuario invitado que todavía no puso su nombre no puede quedar invisible."""
    presencia.marcar(_perfil("u1", "beto@obra.co", ""), ahora=1000.0)
    en_linea = presencia.en_linea(ahora=1000.0)
    assert en_linea == [{"user_id": "u1", "email": "beto@obra.co", "nombre": ""}]


def test_el_mismo_usuario_no_se_duplica():
    presencia.marcar(_perfil(), ahora=1000.0)
    presencia.marcar(_perfil(), ahora=1010.0)
    assert len(presencia.en_linea(ahora=1010.0)) == 1
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_presencia.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apu_tool.servicio.presencia'`

- [ ] **Step 3: Implementación mínima**

Crear `apu_tool/servicio/presencia.py`:

```python
"""Quién está usando la app ahora mismo.

Un `dict` en el proceso web, no una tabla: el dato caduca en 90 segundos, así que no
tiene sentido pagarle a Supabase un write por usuario por minuto ni una migración para
guardarlo. `marcar` lo llama el propio endpoint `GET /api/presencia`, que el frontend
pide cada 45 s: el latido es el poll.

NO toca la DB ni dinero (no recibe el Almacen; Invariante #1 fuera de discusión).

ponytail: dict en el proceso — si algún día hay 2 instances, cada uno ve su mitad de la
gente. El upgrade es una tabla `presencia` (user_id, visto_en) con upsert por latido.
"""
from __future__ import annotations

import time

from apu_tool.nucleo.models import Perfil

VENTANA_S = 90.0
"""Cuánto vale un latido. El frontend late cada 45 s: dos latidos de margen."""

# user_id -> (visto_en, email, nombre)
_vistos: dict[str, tuple[float, str, str]] = {}


def marcar(perfil: Perfil, *, ahora: float | None = None) -> None:
    """Registra que este usuario está activo. Idempotente por usuario."""
    _vistos[perfil.user_id] = (
        time.time() if ahora is None else ahora,
        perfil.email or "",
        perfil.nombre or "",
    )


def en_linea(*, ahora: float | None = None) -> list[dict]:
    """Los vistos dentro de la ventana, ordenados por nombre (o correo si no tiene)."""
    t = time.time() if ahora is None else ahora
    corte = t - VENTANA_S
    vivos = [
        {"user_id": uid, "email": email, "nombre": nombre}
        for uid, (visto, email, nombre) in _vistos.items()
        if visto > corte
    ]
    return sorted(vivos, key=lambda p: (p["nombre"] or p["email"]).lower())
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python -m pytest tests/test_presencia.py -q`
Expected: PASS (6 tests)

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/presencia.py tests/test_presencia.py
git commit -m "feat(api): modulo de presencia (quien esta usando la app ahora)"
```

---

### Task 2: Endpoint `GET /api/presencia`

**Files:**
- Modify: `apu_tool/servicio/rutas.py` (justo después del endpoint `/yo`, línea ~71)
- Test: `tests/test_api_presencia.py`

**Interfaces:**
- Consumes: `presencia.marcar`, `presencia.en_linea` (Task 1); `requiere_rol` de `apu_tool.servicio.auth`.
- Produces: `GET /api/presencia` → `{"en_linea": [{"user_id","email","nombre"}, ...]}`. Rol mínimo `consulta` (lo ven todos los usuarios, decisión de la spec).

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_api_presencia.py` (mismo patrón que `tests/test_api_yo.py`):

```python
"""El endpoint de presencia. Marca al que pregunta: el latido ES el poll.

Ojo con el patrón de estos tests: overridean la dependencia `usuario_actual`, así que
cualquier cosa metida DENTRO de esa dependencia no se ejecuta acá. Por eso `marcar`
vive en el endpoint y no en auth.py.
"""
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Perfil
from apu_tool.servicio import presencia
from apu_tool.servicio.app import create_app
from apu_tool.servicio.auth import usuario_actual
from fastapi.testclient import TestClient


def _app(tmp_path, perfil):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    app = create_app(almacen=alm)
    app.dependency_overrides[usuario_actual] = lambda: perfil
    return app


def setup_function():
    presencia._vistos.clear()


def test_pedir_la_lista_te_deja_en_la_lista(tmp_path):
    """Sin endpoint de latido: preguntar quién está en línea te marca presente."""
    ana = Perfil(user_id="u1", email="ana@obra.co", rol="consulta", estado="activo",
                 nombre="Ana")
    cli = TestClient(_app(tmp_path, ana))
    r = cli.get("/api/presencia")
    assert r.status_code == 200
    assert r.json() == {"en_linea": [
        {"user_id": "u1", "email": "ana@obra.co", "nombre": "Ana"}]}


def test_dos_usuarios_se_ven_entre_si(tmp_path):
    ana = Perfil(user_id="u1", email="ana@obra.co", rol="consulta", estado="activo",
                 nombre="Ana")
    beto = Perfil(user_id="u2", email="beto@obra.co", rol="editor", estado="activo",
                  nombre="Beto")
    TestClient(_app(tmp_path, ana)).get("/api/presencia")
    r = TestClient(_app(tmp_path, beto)).get("/api/presencia")
    assert [p["nombre"] for p in r.json()["en_linea"]] == ["Ana", "Beto"]


def test_sin_token_da_401(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    cli = TestClient(create_app(almacen=alm))
    assert cli.get("/api/presencia").status_code == 401
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_api_presencia.py -q`
Expected: FAIL — los dos primeros con `assert 404 == 200`

- [ ] **Step 3: Implementación mínima**

En `apu_tool/servicio/rutas.py`, agregar el import junto a los otros `from apu_tool.servicio import ...` (orden alfabético, después de `plantillas as plantillas_svc`):

```python
from apu_tool.servicio import presencia as presencia_svc
```

Y el endpoint inmediatamente después de `/yo`:

```python
@router.get("/presencia")
def presencia(usuario=Depends(requiere_rol("consulta"))):
    """Quién está usando la app ahora. Pedirla te marca presente: el latido es el
    poll del frontend (cada 45 s), no hay endpoint de latido aparte.

    No recibe el Almacen a propósito: esto no toca la DB."""
    presencia_svc.marcar(usuario)
    return {"en_linea": presencia_svc.en_linea()}
```

> Nota para quien implementa: el parámetro se llama `usuario` (no `_`) porque se usa. El
> alias `presencia_svc` evita que la función `presencia` tape al módulo.

- [ ] **Step 4: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_api_presencia.py tests/test_api_yo.py tests/test_api_autorizacion.py -q`
Expected: PASS

- [ ] **Step 5: Commit**

```bash
git add apu_tool/servicio/rutas.py tests/test_api_presencia.py
git commit -m "feat(api): GET /api/presencia (lista de conectados, rol consulta)"
```

---

### Task 3: Chip "En línea" en la barra superior

**Files:**
- Create: `web/src/api/presencia.ts`
- Modify: `web/src/lib/tipos.ts` (agregar el tipo)
- Modify: `web/src/components/Layout.tsx`
- Modify: `web/src/components/Layout.test.tsx` (agregar el mock del módulo nuevo — sin esto los 4 tests existentes se rompen)

**Interfaces:**
- Consumes: `GET /api/presencia` (Task 2); `apiGet` de `@/api/client`; el componente `Lectura` que ya vive en `Layout.tsx`.
- Produces: `getPresencia(): Promise<PresenciaResponse>`; tipos `UsuarioEnLinea { user_id: string; email: string; nombre: string }` y `PresenciaResponse { en_linea: UsuarioEnLinea[] }`.

- [ ] **Step 1: Escribir el test que falla**

En `web/src/components/Layout.test.tsx`, agregar el mock del módulo nuevo junto a los otros `vi.mock` (arriba, antes de los tests):

```tsx
vi.mock("@/api/presencia", () => ({
  getPresencia: vi.fn(async () => ({
    en_linea: [
      { user_id: "u1", email: "a@obra.co", nombre: "Ana" },
      { user_id: "u2", email: "beto@obra.co", nombre: "Beto" },
    ],
  })),
}));
```

Y al final del archivo, el test nuevo:

```tsx
test("la barra muestra cuánta gente está en línea, y quién", async () => {
  rol = "editor";
  render(<MemoryRouter><Layout /></MemoryRouter>);

  // El conteo es un nodo propio, como las otras lecturas.
  const conteo = await screen.findByText("2");
  expect(conteo).not.toBeNull();

  // Los nombres van en el title: la barra es densa, no caben dos columnas de gente.
  // El propio usuario (a@obra.co, el del mock de useAuth) queda marcado.
  const titulo = conteo.closest("[title]")?.getAttribute("title") ?? "";
  expect(titulo).toContain("Ana (vos)");
  expect(titulo).toContain("Beto");
});
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `cd web && npx vitest run src/components/Layout.test.tsx`
Expected: FAIL — el test nuevo no encuentra el texto "2"; los otros 4 siguen pasando (el `vi.mock` de un módulo que todavía no se importa es inofensivo).

- [ ] **Step 3: Implementación mínima**

Crear `web/src/api/presencia.ts`:

```ts
import { apiGet } from "./client";
import type { PresenciaResponse } from "@/lib/tipos";

/** Quién está usando la app ahora. Pedirla también te marca presente (el latido es
 *  este mismo poll, ver apu_tool/servicio/presencia.py). */
export function getPresencia(): Promise<PresenciaResponse> {
  return apiGet<PresenciaResponse>("/presencia");
}
```

En `web/src/lib/tipos.ts`, agregar:

```ts
export interface UsuarioEnLinea {
  user_id: string;
  email: string;
  nombre: string;
}

export interface PresenciaResponse {
  en_linea: UsuarioEnLinea[];
}
```

En `web/src/components/Layout.tsx`:

1. Imports — agregar a los existentes:

```tsx
import { getPresencia } from "@/api/presencia";
import type { StatusResponse, UsuarioEnLinea } from "@/lib/tipos";
```

(el `import type { StatusResponse }` que ya está se extiende, no se duplica)

2. Estado y poll, después del `useEffect` de `getStatus`:

```tsx
  const [enLinea, setEnLinea] = useState<UsuarioEnLinea[] | null>(null);

  // Presencia: un poll de 45 s contra una ventana de 90 s en el servidor (dos latidos
  // de margen, así una petición perdida no apaga el punto). El poll ES el latido.
  useEffect(() => {
    let vivo = true;
    const pedir = () => {
      // Una pestaña de fondo no está "usando" la app: deja de latir y a los 90 s
      // desaparece de la lista de los demás.
      if (document.hidden) return;
      getPresencia()
        .then((r) => {
          if (vivo) setEnLinea(r.en_linea);
        })
        .catch(() => {
          /* sin backend — silencioso, se conserva la última lista */
        });
    };
    pedir();
    const t = setInterval(pedir, 45_000);
    return () => {
      vivo = false;
      clearInterval(t);
    };
  }, []);
```

3. El título, junto al `const num = ...`:

```tsx
  // Los nombres en el title: la barra es densa y no caben dos columnas de gente.
  const quienes = (enLinea ?? [])
    .map((u) => `${u.nombre || u.email}${u.email === perfil?.email ? " (vos)" : ""}`)
    .join("\n");
```

4. La lectura, dentro del `<div className="flex items-stretch @max-[980px]:hidden">`, **antes** de la de Insumos (la gente primero, los conteos después):

```tsx
                <Lectura etiqueta="En línea">
                  <span className="flex items-center gap-1.5" title={quienes}>
                    <span
                      aria-hidden
                      className="size-[5px] shrink-0 rounded-full bg-margen-pos"
                    />
                    {enLinea ? enLinea.length : "—"}
                  </span>
                </Lectura>
```

- [ ] **Step 4: Correr los tests y el build**

Run: `cd web && npx vitest run src/components/Layout.test.tsx && npm run build`
Expected: PASS los 5 tests de Layout, y el build limpio.

> `npm run build` corre `tsc -b`, que es el que de verdad falla ante un tipo mal puesto.
> `tsc --noEmit` no alcanza (lección del branch de nombre/alias de corridas).

- [ ] **Step 5: Commit**

```bash
git add web/src/api/presencia.ts web/src/lib/tipos.ts web/src/components/Layout.tsx web/src/components/Layout.test.tsx
git commit -m "feat(web): chip En linea en la barra (poll 45s, nombres en el title)"
```

---

# FASE 2 — Búsqueda por relevancia

### Task 4: Helper `nucleo/relevancia.py`

**Files:**
- Create: `apu_tool/nucleo/relevancia.py`
- Modify: `apu_tool/dominio/matching.py:22-54` (se van `_STOPWORDS`, `normalize`, `_tokens`, `similarity`; queda un reexport)
- Test: `tests/test_relevancia.py`

**Interfaces:**
- Consumes: `apu_tool.nucleo.texto.normalizar`.
- Produces:
  - `MAX_RANKEO: int = 2000`
  - `palabras(q: str) -> list[str]`
  - `nivel(nombre: str, codigo: str, q_norm: str, palabras_q: list[str]) -> int | None`
  - `ordenar(filas: list, q: str | None, *, nombre_de, codigo_de) -> list`
  - `similarity(a: str, b: str) -> float`, `normalize(text: str) -> str`, `_tokens(text) -> frozenset[str]` (movidas desde `dominio/matching.py`, reexportadas desde ahí)

- [ ] **Step 1: Escribir el test que falla**

Crear `tests/test_relevancia.py`:

```python
"""Orden por relevancia de una búsqueda.

El caso que originó esto: buscar "transporte" devolvía veinte APUs que la mencionan de
paso ANTES del que se llama "TRANSPORTE", porque el orden era por código.
"""
from apu_tool.nucleo import relevancia


class Fila:
    """Lo mínimo que `ordenar` necesita: un nombre y un código."""

    def __init__(self, codigo, nombre):
        self.codigo = codigo
        self.nombre = nombre

    def __repr__(self):
        return f"Fila({self.codigo!r}, {self.nombre!r})"


def _ordenar(q, *pares):
    filas = [Fila(c, n) for c, n in pares]
    return [f.nombre for f in relevancia.ordenar(
        filas, q, nombre_de=lambda f: f.nombre, codigo_de=lambda f: f.codigo)]


def test_los_niveles_mandan_sobre_el_codigo():
    """El de código menor NO gana si el otro empieza con lo buscado."""
    assert _ordenar(
        "transporte",
        ("1000", "SUMINISTRO, TRANSPORTE E INSTALACION DE TUBERIA PVC 12 PULGADAS"),
        ("2000", "AUTOTRANSPORTEDORA DE CONCRETO"),
        ("3000", "TRANSPORTE DE MATERIAL SOBRANTE A 20 KM"),
        ("4000", "TRANSPORTE"),
    ) == [
        "TRANSPORTE",                                     # nivel 0: exacto
        "TRANSPORTE DE MATERIAL SOBRANTE A 20 KM",        # nivel 1: empieza con
        "SUMINISTRO, TRANSPORTE E INSTALACION DE TUBERIA PVC 12 PULGADAS",  # nivel 2
        "AUTOTRANSPORTEDORA DE CONCRETO",                 # nivel 4: dentro de palabra
    ]


def test_dos_palabras_en_cualquier_orden_y_separadas():
    """Hoy esto devuelve CERO filas: `LIKE '%transporte material%'` es una frase."""
    assert _ordenar(
        "transporte material",
        ("1000", "EXCAVACION MANUAL"),
        ("2000", "TRANSPORTE DE MATERIAL SOBRANTE"),
        ("3000", "MATERIAL DE PRESTAMO Y SU TRANSPORTE"),
    ) == ["TRANSPORTE DE MATERIAL SOBRANTE", "MATERIAL DE PRESTAMO Y SU TRANSPORTE"]
    # "EXCAVACION MANUAL" no tiene ninguna de las dos palabras -> se descarta.


def test_la_frase_completa_gana_al_and_de_palabras():
    assert _ordenar(
        "transporte material",
        ("1000", "RETIRO Y MATERIAL CON TRANSPORTE INCLUIDO"),   # nivel 3: AND
        ("2000", "OBRA: TRANSPORTE MATERIAL A 5 KM"),            # nivel 2: la frase
    ) == ["OBRA: TRANSPORTE MATERIAL A 5 KM",
          "RETIRO Y MATERIAL CON TRANSPORTE INCLUIDO"]


def test_encuentra_sin_tildes_lo_que_esta_con_tildes():
    """El defecto de APUs: `excavacion` no encontraba "EXCAVACIÓN"."""
    assert _ordenar("excavacion", ("1000", "EXCAVACIÓN MECÁNICA")) == ["EXCAVACIÓN MECÁNICA"]


def test_busca_tambien_por_codigo():
    assert _ordenar("3017", ("9000", "MANO DE OBRA"), ("3017", "TRANSPORTE")) == [
        "TRANSPORTE", ]
    # Solo la fila cuyo código coincide; la otra no tiene "3017" en ningún lado.


def test_empate_de_nivel_desempata_por_parecido_y_despues_por_codigo():
    """Determinista: sin esto la paginación cambiaría de orden entre páginas."""
    assert _ordenar(
        "transporte",
        ("2000", "TRANSPORTE DE MATERIAL"),
        ("1000", "TRANSPORTE DE MATERIAL"),
    ) == ["TRANSPORTE DE MATERIAL", "TRANSPORTE DE MATERIAL"]
    filas = [Fila("2000", "TRANSPORTE DE MATERIAL"), Fila("1000", "TRANSPORTE DE MATERIAL")]
    ordenadas = relevancia.ordenar(filas, "transporte", nombre_de=lambda f: f.nombre,
                                   codigo_de=lambda f: f.codigo)
    assert [f.codigo for f in ordenadas] == ["1000", "2000"]


def test_q_vacia_no_reordena_ni_descarta():
    for q in (None, "", "   "):
        assert _ordenar(q, ("2000", "B"), ("1000", "A")) == ["B", "A"]


def test_arriba_del_techo_no_se_puntua_pero_los_niveles_siguen(monkeypatch):
    """El guard de CPU: sin score, el nivel y el código siguen ordenando."""
    monkeypatch.setattr(relevancia, "MAX_RANKEO", 1)
    assert _ordenar(
        "transporte",
        ("2000", "RETIRO Y TRANSPORTE"),
        ("1000", "TRANSPORTE DE MATERIAL"),
    ) == ["TRANSPORTE DE MATERIAL", "RETIRO Y TRANSPORTE"]


def test_similarity_sigue_disponible_desde_matching():
    """Movida a núcleo, pero `dominio/matching.py` la reexporta: compose.py y cruce.py
    la importan de ahí."""
    from apu_tool.dominio.matching import _tokens, normalize, similarity
    assert similarity("EXCAVACION MANUAL", "excavacion manual") == 1.0
    assert normalize("Excavación") == "EXCAVACION"
    assert "EXCAVACION" in _tokens("de la excavación")
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_relevancia.py -q`
Expected: FAIL — `ModuleNotFoundError: No module named 'apu_tool.nucleo.relevancia'`

- [ ] **Step 3: Crear el módulo**

Crear `apu_tool/nucleo/relevancia.py`:

```python
"""
Orden por relevancia de una búsqueda por texto (capa núcleo, sin dependencias).

Buscar "transporte" devolvía todo lo que contuviera el string ordenado por código: el
APU llamado "TRANSPORTE" salía después de veinte que lo mencionan de paso. Acá vive el
criterio: el NIVEL (dónde aparece lo buscado) manda, y `similarity` (parecido del
nombre completo) desempata dentro del nivel.

También vive acá `similarity` (antes en `dominio/matching.py`): es una utilidad pura de
texto, la misma razón por la que `normalizar` vive en `nucleo/texto.py`. `matching.py`
la reexporta, así que sus importadores no cambian.
"""
from __future__ import annotations

from difflib import SequenceMatcher
from functools import lru_cache

from apu_tool.nucleo.texto import normalizar

MAX_RANKEO = 2000
"""Arriba de esto no se calcula el parecido: `similarity` es caro y una consulta de 1-2
letras trae miles de candidatos donde el parecido es ruido igual. Los niveles se aplican
siempre (son comparaciones de strings, gratis).

ponytail: techo de CPU, no de correctitud — arriba de acá manda el nivel y el código.
El upgrade es un índice de texto (FTS5 en SQLite / pg_trgm en Postgres)."""

_STOPWORDS = {
    "de", "la", "el", "los", "las", "del", "y", "o", "en", "para", "por", "con",
    "incluye", "incluido", "no", "un", "una", "a", "e", "su", "al", "segun",
    "tipo", "obra", "ml", "m2", "m3", "und", "un",
}


@lru_cache(maxsize=20000)
def normalize(text: str) -> str:
    return normalizar(text)


def _tokens(text: str) -> frozenset[str]:
    return frozenset(
        t for t in normalize(text).split() if t and t.lower() not in _STOPWORDS
    )


def similarity(a: str, b: str) -> float:
    """Similaridad 0..1 combinando secuencia y tokens."""
    na, nb = normalize(a), normalize(b)
    if not na or not nb:
        return 0.0
    if na == nb:
        return 1.0
    seq = SequenceMatcher(None, na, nb).ratio()
    ta, tb = _tokens(a), _tokens(b)
    if ta and tb:
        jaccard = len(ta & tb) / len(ta | tb)
    else:
        jaccard = 0.0
    # Peso mayor a tokens: el orden de palabras varía mucho en obra civil.
    return 0.4 * seq + 0.6 * jaccard


def palabras(q: str | None) -> list[str]:
    """Las palabras de la consulta, normalizadas. Vacío si no hay consulta."""
    return [p for p in normalize(q or "").split() if p]


def nivel(nombre: str, codigo: str, q_norm: str, palabras_q: list[str]) -> int | None:
    """Dónde aparece lo buscado. Menor = más relevante. None = no coincide.

    Los niveles 0-2 miran la consulta como FRASE; del 3 en adelante manda el AND por
    palabras (todas tienen que aparecer, en cualquier orden). El truco de rodear con
    espacios (`f" {n} "`) da el borde de palabra gratis, sin regex.
    """
    n = normalize(nombre)
    c = normalize(codigo)
    if n == q_norm or c == q_norm:
        return 0
    if n.startswith(q_norm) or c.startswith(q_norm):
        return 1
    if f" {q_norm} " in f" {n} ":
        return 2
    if any(p not in n and p not in c for p in palabras_q):
        return None
    if all(f" {p} " in f" {n} " for p in palabras_q):
        return 3
    return 4


def ordenar(filas: list, q: str | None, *, nombre_de, codigo_de) -> list:
    """Descarta las filas que no coinciden con `q` y ordena las que quedan por
    (nivel, parecido desc, código). Con `q` vacía devuelve las filas tal cual.

    `nombre_de`/`codigo_de` sacan los dos textos de cada fila, así esto sirve igual
    para un Apu y para un Insumo sin conocer ninguno de los dos.
    """
    ps = palabras(q)
    if not ps:
        return list(filas)
    q_norm = " ".join(ps)
    con_score = len(filas) <= MAX_RANKEO
    clasificadas = []
    for fila in filas:
        nombre, codigo = nombre_de(fila), codigo_de(fila)
        niv = nivel(nombre, codigo, q_norm, ps)
        if niv is None:
            continue
        score = similarity(q_norm, nombre) if con_score else 0.0
        clasificadas.append((niv, -score, normalize(codigo), fila))
    # key=x[:3] y no la tupla entera: si empatan los tres criterios, comparar las filas
    # entre sí sería un TypeError (Apu/Insumo no son ordenables).
    clasificadas.sort(key=lambda x: x[:3])
    return [x[3] for x in clasificadas]
```

- [ ] **Step 4: Dejar `matching.py` reexportando**

En `apu_tool/dominio/matching.py`, borrar las líneas 15-16 (`from difflib import SequenceMatcher`, `from functools import lru_cache`), el bloque `_STOPWORDS` (22-26), `normalize` (29-31), `_tokens` (34-37) y `similarity` (40-54), y reemplazar el import de `nucleo.texto` por:

```python
# `similarity`, `normalize` y `_tokens` viven en núcleo (utilidades puras de texto, la
# misma razón que `normalizar`). Se reexportan acá porque compose.py, cruce.py y los
# tests de matching las importan de este módulo desde antes de la mudanza.
from apu_tool.nucleo.relevancia import _tokens, normalize, similarity  # noqa: F401
```

Y actualizar el docstring del módulo (líneas 9-11) para que apunte a dónde vive el
algoritmo:

```
Algoritmo: normalización + combinación de similaridad de secuencia (difflib) y de
tokens (Jaccard). Vive en `nucleo/relevancia.py` (lo comparte la búsqueda por
relevancia de la web) y se reexporta acá.
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_relevancia.py tests/test_matching.py tests/test_matching_optimizacion.py tests/test_compose.py tests/test_cruce.py -q`
Expected: PASS todos. Los de matching/compose/cruce son el guard de que la mudanza no cambió el scorer.

- [ ] **Step 6: Documentar el módulo nuevo**

Un módulo nuevo en `nucleo/` tiene que aparecer en las dos tablas que lo listan, o el
próximo que lea la arquitectura no sabe que existe:

1. `CLAUDE.md`, sección «`apu_tool/nucleo/` — tipos y utilidades puras», agregar la fila
   (después de `redondeo.py`, antes de `texto.py`):

```markdown
| `relevancia.py` | orden por relevancia de una búsqueda + scorer `similarity` |
```

2. `docs/ARQUITECTURA.md:61-64` — es un árbol, no una tabla. Queda:

```
│   ├── nucleo/                    ── KERNEL COMPARTIDO
│   │   ├── models.py              #   dataclasses puras (Insumo, Apu, DePriced*)
│   │   ├── redondeo.py            #   redondeo a la unidad en multiplicaciones monetarias
│   │   ├── relevancia.py          #   orden por relevancia de una búsqueda + similarity
│   │   └── texto.py               #   normalización de texto compartida
```

`constructor-apus/` (el vault de Obsidian) NO se edita a mano: lo regenera
`scripts/actualizar_vault.py` desde los archivos versionados.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/nucleo/relevancia.py apu_tool/dominio/matching.py tests/test_relevancia.py CLAUDE.md docs/ARQUITECTURA.md
git commit -m "feat(nucleo): relevancia.py (niveles + parecido) y similarity movida a nucleo"
```

---

### Task 5: `list_apus` filtra y ordena por relevancia (2 backends)

**Files:**
- Modify: `apu_tool/datos/apus_db.py:185-210` (`list_apus`)
- Modify: `apu_tool/datos/pg/apus_pg.py:158-190` (`list_apus`)
- Test: `tests/test_repositorios_contrato.py` (agregar al final)

> Los tests van en `test_repositorios_contrato.py` y no en `test_apus_db.py`: ese
> archivo corre **la misma batería contra los dos backends** (SQLite siempre, Postgres
> si hay `TEST_DATABASE_URL`) vía la fixture `repos`. Un solo test cubre SQLite y
> Postgres, que es justo donde este cambio puede divergir.

**Interfaces:**
- Consumes: `relevancia.ordenar` (Task 4).
- Produces: `list_apus(q, grupo, shift, limit, offset) -> tuple[list[Apu], int]` — misma firma y mismo tipo de retorno que hoy. Cambia solo el orden y, con `q`, el conjunto (ahora encuentra más: AND por palabras y sin tildes).

- [ ] **Step 1: Escribir el test que falla (los dos backends de una)**

Agregar al final de `tests/test_repositorios_contrato.py` (`Apu` ya está importado
arriba del archivo; la fixture `repos` devuelve `(precios, apus)`):

```python
def test_list_apus_ordena_por_relevancia(repos):
    """Buscar "transporte" tiene que traer primero el que empieza con la palabra,
    no el de código menor (que es lo que hacía el ORDER BY codigo)."""
    _, apus = repos
    apus.insert_apus([
        Apu("1000", "SUMINISTRO Y TRANSPORTE DE TUBERIA", "ML", "DIURNO", "REDES"),
        Apu("2000", "TRANSPORTE DE MATERIAL SOBRANTE", "M3", "DIURNO", "MOV"),
        Apu("3000", "EXCAVACIÓN MECÁNICA", "M3", "DIURNO", "MOV"),
    ])
    items, total = apus.list_apus(q="transporte")
    assert [a.codigo for a in items] == ["2000", "1000"]
    assert total == 2


def test_list_apus_encuentra_sin_tildes(repos):
    """Antes fallaba: el LIKE iba contra `nombre` crudo, y encima con LIKE en SQLite
    vs ILIKE en Postgres. Este test corre en los dos backends a propósito."""
    _, apus = repos
    apus.insert_apus([Apu("1000", "EXCAVACIÓN MECÁNICA", "M3", "DIURNO", "MOV")])
    items, total = apus.list_apus(q="excavacion mecanica")
    assert [a.codigo for a in items] == ["1000"]
    assert total == 1


def test_list_apus_dos_palabras_separadas(repos):
    """Antes devolvía cero filas: el LIKE buscaba la frase literal."""
    _, apus = repos
    apus.insert_apus([
        Apu("1000", "TRANSPORTE DE MATERIAL SOBRANTE", "M3", "DIURNO", "MOV")])
    items, _ = apus.list_apus(q="transporte material")
    assert [a.codigo for a in items] == ["1000"]


def test_list_apus_respeta_grupo_turno_y_paginacion_con_q(repos):
    _, apus = repos
    apus.insert_apus([
        Apu("1000", "TRANSPORTE A", "M3", "DIURNO", "MOV"),
        Apu("2000", "TRANSPORTE B", "M3", "NOCTURNO", "MOV"),
        Apu("3000", "TRANSPORTE C", "M3", "DIURNO", "REDES"),
    ])
    items, total = apus.list_apus(q="transporte", shift="DIURNO")
    assert {a.codigo for a in items} == {"1000", "3000"} and total == 2
    items, total = apus.list_apus(q="transporte", grupo="MOV")
    assert {a.codigo for a in items} == {"1000", "2000"} and total == 2
    pag1, total = apus.list_apus(q="transporte", limit=2, offset=0)
    pag2, _ = apus.list_apus(q="transporte", limit=2, offset=2)
    assert total == 3 and len(pag1) == 2 and len(pag2) == 1
    assert not ({a.codigo for a in pag1} & {a.codigo for a in pag2})


def test_list_apus_sin_q_no_cambia(repos):
    """El camino sin búsqueda queda intacto: orden por código y total real."""
    _, apus = repos
    apus.insert_apus([
        Apu("2000", "B", "M3", "DIURNO", "MOV"),
        Apu("1000", "A", "M3", "DIURNO", "MOV"),
    ])
    items, total = apus.list_apus()
    assert [a.codigo for a in items] == ["1000", "2000"] and total == 2
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_repositorios_contrato.py -q`
Expected: FAIL — `test_list_apus_ordena_por_relevancia` da `["1000", "2000"]` (orden por código) y los de tildes/dos-palabras dan listas vacías. Sin `TEST_DATABASE_URL` solo corre la variante `sqlite`; eso está bien para este paso.

- [ ] **Step 3: Implementar en SQLite**

Reemplazar `list_apus` en `apu_tool/datos/apus_db.py` (líneas 185-210) por:

```python
    def list_apus(self, q: Optional[str] = None, grupo: Optional[str] = None,
                  shift: Optional[str] = None, limit: int = 100,
                  offset: int = 0) -> tuple[list[Apu], int]:
        where, params = [], []
        if grupo:
            where.append("grupo = ?")
            params.append(grupo)
        if shift:
            where.append("shift = ?")
            params.append(shift)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        if (q or "").strip():
            # El filtro por texto y el orden van en Python (nucleo/relevancia.py): así
            # "excavacion" encuentra "EXCAVACIÓN" y el criterio es UNO para SQLite y
            # Postgres, en vez del LIKE-vs-ILIKE que divergía en acentos. La tabla tiene
            # ~1200 filas y el repo ya la lee entera en cada corrida (apu_index).
            with self.connect() as conn:
                rows = conn.execute(
                    f"SELECT codigo, nombre, unidad, shift, grupo FROM apus{wsql}",
                    params).fetchall()
            todos = [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"])
                     for r in rows]
            ordenados = relevancia.ordenar(todos, q, nombre_de=lambda a: a.nombre,
                                           codigo_de=lambda a: a.codigo)
            return ordenados[int(offset):int(offset) + int(limit)], len(ordenados)
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) FROM apus{wsql}", params).fetchone()[0]
            rows = conn.execute(
                f"SELECT codigo, nombre, unidad, shift, grupo FROM apus{wsql} "
                f"ORDER BY codigo, shift LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return ([Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"])
                 for r in rows], int(total))
```

Agregar el import arriba del archivo, junto al de `nucleo.models`:

```python
from apu_tool.nucleo import relevancia
```

- [ ] **Step 4: Correr los tests de SQLite**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_apus_db.py tests/test_apus_grupos.py tests/test_db_repository.py -q`
Expected: PASS

- [ ] **Step 5: Espejar en Postgres**

En `apu_tool/datos/pg/apus_pg.py`, reemplazar `list_apus` con la misma estructura, cambiando `?`→`%s`, `apus`→`apus.apus`, y el acceso a la fila por clave (el `row_factory` de PG devuelve dicts):

```python
    def list_apus(self, q: Optional[str] = None, grupo: Optional[str] = None,
                  shift: Optional[str] = None, limit: int = 100,
                  offset: int = 0) -> tuple[list[Apu], int]:
        where, params = [], []
        if grupo:
            where.append("grupo = %s")
            params.append(grupo)
        if shift:
            where.append("shift = %s")
            params.append(shift)
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        if (q or "").strip():
            # Igual que en apus_db.py: filtro y orden en Python (nucleo/relevancia.py),
            # un solo criterio para los dos backends. ~1200 filas.
            with self.cx.connection() as conn:
                rows = conn.execute(
                    f"SELECT codigo, nombre, unidad, shift, grupo FROM apus.apus{wsql}",
                    params).fetchall()
            todos = [Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"])
                     for r in rows]
            ordenados = relevancia.ordenar(todos, q, nombre_de=lambda a: a.nombre,
                                           codigo_de=lambda a: a.codigo)
            return ordenados[int(offset):int(offset) + int(limit)], len(ordenados)
        with self.cx.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n FROM apus.apus{wsql}",
                                 params).fetchone()["n"]
            rows = conn.execute(
                f"SELECT codigo, nombre, unidad, shift, grupo FROM apus.apus{wsql} "
                f"ORDER BY codigo, shift LIMIT %s OFFSET %s",
                params + [int(limit), int(offset)]).fetchall()
        return ([Apu(r["codigo"], r["nombre"], r["unidad"], r["shift"], r["grupo"])
                 for r in rows], int(total))
```

Con el import correspondiente arriba: `from apu_tool.nucleo import relevancia`

> **Antes de escribir**: abrir `apus_pg.list_apus` y copiar la forma exacta de leer la
> fila y de contar que ya usa el archivo (`.fetchone()["n"]` vs `[0]`). El espejo tiene
> que respetar las convenciones del archivo, no las de este plan.

- [ ] **Step 6: Correr la misma batería contra Postgres**

Con `TEST_DATABASE_URL` apuntando al Postgres desechable local, la fixture `repos`
agrega la variante `postgres` y los cinco tests del Step 1 corren de nuevo contra el
otro backend:

Run: `python -m pytest tests/test_repositorios_contrato.py -q`
Expected: PASS — el doble de tests que sin la variable (verificarlo en el conteo que
imprime pytest; si el número no subió, `TEST_DATABASE_URL` no está puesta y Postgres
NO se probó).

Si no hay Postgres local levantado, seguir el recetario del Postgres desechable
(binarios portables EDB, puerto 55433) que está en `docs/`.
**Nunca apuntar estos tests a producción: hacen `DROP SCHEMA`.**

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py tests/test_repositorios_contrato.py
git commit -m "feat(datos): list_apus filtra y ordena por relevancia (AND por palabras + acentos)"
```

---

### Task 6: `list_insumos` ordena por relevancia (2 backends)

**Files:**
- Modify: `apu_tool/datos/precios_db.py:366-416` (`list_insumos`)
- Modify: `apu_tool/datos/pg/precios_pg.py:310-360` (`list_insumos`)
- Test: `tests/test_repositorios_contrato.py` (agregar al final; misma razón que Task 5: cubre los dos backends)

**Interfaces:**
- Consumes: `relevancia.ordenar`, `relevancia.palabras`, `relevancia.MAX_RANKEO` (Task 4).
- Produces: `list_insumos(q, grupo, fuente, clasificacion, limit, offset, lista_id, sin_precio) -> tuple[list[Insumo], int]` — misma firma que hoy.

- [ ] **Step 1: Escribir el test que falla (los dos backends de una)**

Agregar al final de `tests/test_repositorios_contrato.py`. `Insumo` ya está importado
arriba; su firma es `Insumo(codigo, nombre, unidad, grupo, precio, fuente)`:

```python
def test_list_insumos_ordena_por_relevancia(repos):
    """Mismo criterio que APUs: el que empieza con la palabra va primero, aunque su
    código sea mayor."""
    precios, _ = repos
    precios.insert_insumos([
        Insumo("1000", "TUBERIA PVC PARA ACUEDUCTO", "ML", "MATERIAL", 1000.0, "PRECIO IDU"),
        Insumo("2000", "ACUEDUCTO DOMICILIARIO COMPLETO", "UN", "MATERIAL", 2000.0, "PRECIO IDU"),
    ])
    items, total = precios.list_insumos(q="acueducto")
    assert [i.codigo for i in items] == ["2000", "1000"]
    assert total == 2


def test_list_insumos_dos_palabras_separadas(repos):
    """Antes devolvía cero filas: el LIKE buscaba la frase literal."""
    precios, _ = repos
    precios.insert_insumos([
        Insumo("1000", "TUBERIA PVC PARA ACUEDUCTO", "ML", "MATERIAL", 1000.0, "PRECIO IDU")])
    items, total = precios.list_insumos(q="tuberia acueducto")
    assert [i.codigo for i in items] == ["1000"] and total == 1


def test_list_insumos_total_coincide_con_lo_devuelto(repos):
    """El contador no puede decir 3 sobre una lista de 2."""
    precios, _ = repos
    precios.insert_insumos([
        Insumo("1000", "ACUEDUCTO A", "UN", "MATERIAL", 100.0, "PRECIO IDU"),
        Insumo("2000", "ACUEDUCTO B", "UN", "MATERIAL", 100.0, "PRECIO IDU"),
        Insumo("3000", "CEMENTO GRIS", "KG", "MATERIAL", 100.0, "PRECIO IDU"),
    ])
    items, total = precios.list_insumos(q="acueducto", limit=100)
    assert total == len(items) == 2


def test_list_insumos_relevancia_convive_con_los_filtros(repos):
    """`q` no puede desactivar `grupo` ni `fuente` (ni al revés)."""
    precios, _ = repos
    precios.insert_insumos([
        Insumo("1000", "ACUEDUCTO A", "UN", "MATERIAL", 100.0, "PRECIO IDU"),
        Insumo("2000", "ACUEDUCTO B", "UN", "EQUIPO", 100.0, "COSTO INTERNO"),
    ])
    items, total = precios.list_insumos(q="acueducto", grupo="EQUIPO")
    assert [i.codigo for i in items] == ["2000"] and total == 1
    items, total = precios.list_insumos(q="acueducto", fuente="PRECIO IDU")
    assert [i.codigo for i in items] == ["1000"] and total == 1


def test_list_insumos_sin_q_no_cambia(repos):
    precios, _ = repos
    precios.insert_insumos([
        Insumo("2000", "B", "UN", "MATERIAL", 100.0, "PRECIO IDU"),
        Insumo("1000", "A", "UN", "MATERIAL", 100.0, "PRECIO IDU"),
    ])
    items, total = precios.list_insumos()
    assert [i.codigo for i in items] == ["1000", "2000"] and total == 2
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_repositorios_contrato.py -q`
Expected: FAIL — el de relevancia da `["1000","2000"]`, el de dos palabras da `[]`.

- [ ] **Step 3: Implementar en SQLite**

En `apu_tool/datos/precios_db.py::list_insumos`, cambiar el bloque del `if q:` (líneas 384-387) por un `LIKE` por palabra en `AND`:

```python
        if q:
            # Una palabra = un LIKE, todas en AND: antes `q` era una frase literal y
            # "transporte material" no encontraba "TRANSPORTE DE MATERIAL".
            for palabra in relevancia.palabras(q):
                where.append("(i.nombre_norm LIKE ? OR UPPER(i.codigo) LIKE ?)")
                params += [f"%{palabra}%", f"%{palabra}%"]
```

Y el bloque final de ejecución (líneas 409-416) por:

```python
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        campos = "i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente"
        with self.connect() as conn:
            total = conn.execute(f"SELECT COUNT(*) {base}{wsql}", params).fetchone()[0]
            if q and int(total) <= relevancia.MAX_RANKEO:
                # Rankear exige tener los candidatos en la mano. Arriba del techo se
                # cae al orden por código (ver relevancia.MAX_RANKEO).
                rows = conn.execute(
                    f"SELECT {campos} {base}{wsql} ORDER BY i.codigo, i.id",
                    params).fetchall()
                ordenados = relevancia.ordenar(
                    [self._fila_a_insumo(r) for r in rows], q,
                    nombre_de=lambda i: i.nombre, codigo_de=lambda i: i.codigo)
                # total = len(ordenados), no el COUNT: el WHERE de SQL es un poco más
                # laxo que el filtro de Python (UPPER(codigo) vs normalizar(codigo)) y
                # con dos fuentes de verdad el contador diría 41 sobre una lista de 40.
                return ordenados[int(offset):int(offset) + int(limit)], len(ordenados)
            rows = conn.execute(
                f"SELECT {campos} {base}{wsql} ORDER BY i.codigo, i.id LIMIT ? OFFSET ?",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)
```

Import arriba del archivo: `from apu_tool.nucleo import relevancia`

- [ ] **Step 4: Correr los tests de insumos en SQLite**

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_insumos_db.py tests/test_precios_db.py tests/test_precios_por_lista.py tests/test_api_insumos.py tests/test_api_listas.py tests/test_api_lista_invalida.py tests/test_listas_precios.py -q`
Expected: PASS. Los de listas son el guard de que los filtros `lista_id` / `sin_precio` / `clasificacion` siguen conviviendo con `q`.

- [ ] **Step 5: Espejar en Postgres**

En `apu_tool/datos/pg/precios_pg.py::list_insumos`, el mismo cambio con `%s`, `precios.insumos`, y `.fetchone()["n"]` para el COUNT:

```python
        if q:
            # Una palabra = un LIKE, todas en AND (igual que precios_db.py).
            for palabra in relevancia.palabras(q):
                where.append("(i.nombre_norm LIKE %s OR UPPER(i.codigo) LIKE %s)")
                params += [f"%{palabra}%", f"%{palabra}%"]
```

```python
        wsql = (" WHERE " + " AND ".join(where)) if where else ""
        campos = "i.id, i.codigo, i.nombre, i.unidad, i.grupo, p.precio, p.fuente"
        with self.cx.connection() as conn:
            total = conn.execute(f"SELECT COUNT(*) AS n {base}{wsql}", params).fetchone()["n"]
            if q and int(total) <= relevancia.MAX_RANKEO:
                rows = conn.execute(
                    f"SELECT {campos} {base}{wsql} ORDER BY i.codigo, i.id",
                    params).fetchall()
                ordenados = relevancia.ordenar(
                    [self._fila_a_insumo(r) for r in rows], q,
                    nombre_de=lambda i: i.nombre, codigo_de=lambda i: i.codigo)
                return ordenados[int(offset):int(offset) + int(limit)], len(ordenados)
            rows = conn.execute(
                f"SELECT {campos} {base}{wsql} ORDER BY i.codigo, i.id LIMIT %s OFFSET %s",
                params + [int(limit), int(offset)]).fetchall()
        return [self._fila_a_insumo(r) for r in rows], int(total)
```

Import: `from apu_tool.nucleo import relevancia`

- [ ] **Step 6: Correr la misma batería contra Postgres**

Con `TEST_DATABASE_URL` puesta:

Run: `python -m pytest tests/test_repositorios_contrato.py tests/test_precios_pg_smoke.py -q`
Expected: PASS, con el conteo de tests más alto que sin la variable.

- [ ] **Step 7: Commit**

```bash
git add apu_tool/datos/precios_db.py apu_tool/datos/pg/precios_pg.py tests/test_repositorios_contrato.py
git commit -m "feat(datos): list_insumos ordena por relevancia y busca por palabras (AND)"
```

---

### Task 7: Verificación completa

**Files:** ninguno (solo verificación; si algo falla, se arregla acá)

- [ ] **Step 1: Suite completa de Python**

Run: `python -m pytest tests/ -q`
Expected: PASS, cero fallos y cero errores. El conteo sube ~28 sobre los 647 de hoy
(6 de presencia + 3 del endpoint + 9 de relevancia + 10 de la batería de contrato), y
sube más si `TEST_DATABASE_URL` está puesta, porque la batería de contrato corre dos
veces. Si el conteo NO subió, algún archivo de test no se está recogiendo.

> Si algún test verde en local falla en CI, revisar el patrón conocido: `data/` y
> `web/.env.local` no versionados tapan fallos que sí explotan en CI.

- [ ] **Step 2: Frontend completo**

Run: `cd web && npx vitest run && npm run build`
Expected: PASS todos los tests y build limpio (`tsc -b`).

- [ ] **Step 3: Smoke test en el navegador (obligatorio antes de pedir el push)**

Levantar la web local (necesita `SUPABASE_URL` + `APU_ADMIN_EMAILS`, si no todo `/api`
rebota con 401) y verificar a mano:

1. La barra superior muestra "En línea 1" con tu nombre en el tooltip, marcado `(vos)`.
2. En la página de APUs, buscar `transporte`: el primero es el que empieza con la
   palabra, no el de código menor.
3. Buscar `transporte material` (dos palabras): trae resultados donde antes traía cero.
4. Buscar una palabra con tilde sin la tilde (`excavacion`): la encuentra.
5. Lo mismo en la página de Insumos y en el buscador de APU de una corrida.
6. Borrar la búsqueda: la tabla vuelve al orden por código y el contador total coincide.
7. Abrir la app en dos navegadores con dos usuarios: cada uno ve 2 en línea. Cerrar uno
   y esperar ~90 s: el otro pasa a 1.

- [ ] **Step 4: Reportar y pedir el OK para el push**

Reportar al dueño del repo: qué se hizo, salida real de las suites, y el resultado del
smoke test punto por punto. **No pushear a master sin OK explícito** (master
auto-despliega a producción).

---

## Notas para quien implementa

- **Cero migraciones en este plan.** Si te encuentras escribiendo un `ALTER TABLE`,
  algo se entendió mal: la spec descartó a propósito la columna `apus.nombre_norm`.
- **`grep` antes de editar.** Antes de tocar `list_apus` / `list_insumos`, buscar sus
  llamadores (`grep -rn "list_apus\|list_insumos" apu_tool/ tests/`): la firma no
  cambia, pero conviene saber quién depende del orden.
- **No toques** `search_apus`, `search_insumos` ni `search_insumos_por_palabras`.
  Los dos primeros no los llama ningún cliente web; el tercero alimenta los candidatos
  de composición de la IA y es otra frontera (Invariante #1).
- El `Almacen` no entra en `presencia.py`. Si aparece, se colaron la DB y el dinero en
  un módulo que no los necesita.
