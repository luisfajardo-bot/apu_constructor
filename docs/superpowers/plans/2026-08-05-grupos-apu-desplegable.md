# Grupo del APU como desplegable — Plan de implementación

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** El campo *Grupo* del diálogo de crear/editar/duplicar APU pasa de `<input>` de texto libre a `<select>` con un vocabulario cerrado, y un Admin puede agregar grupos nuevos desde la página de APUs.

**Architecture:** Sin tabla nueva. El vocabulario es la unión de una lista base en `config.py` y los grupos que ya usa algún APU (`SELECT DISTINCT grupo FROM apus`), expuesta en `GET /api/apus/grupos`. La escritura de APUs **no** cambia: el vocabulario se cierra en la pantalla, no en la API.

**Tech Stack:** Python 3 + FastAPI + SQLite/Postgres (doble backend espejo) · React + TypeScript + vitest · pytest.

Spec: `docs/superpowers/specs/2026-08-05-grupos-apu-desplegable-design.md`
Rama: `feat/grupos-apu-desplegable` (ya creada; el spec está commiteado en `1eb5fe9`).

## Global Constraints

- **Invariante #1:** nada de dinero hacia la IA. Esta feature no toca ningún camino de IA; no agregar campos a payloads de `dominio/ai_assist.py`.
- **Toda la persistencia vive en `apu_tool/datos/`.** Nada de SQL crudo fuera de esa capa.
- **Doble backend espejo:** todo método nuevo en `datos/apus_db.py` (SQLite) va también en `datos/pg/apus_pg.py` (Postgres) y se declara en el `Protocol` de `datos/repositorio.py`. En Postgres la tabla es `apus.apus`; los placeholders son `%s`, no `?`.
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias nuevas.**
- Lista base exacta, en este orden (se ordena alfabéticamente al servir, pero la constante va así):
  `PAVIMENTOS`, `REDES DE ACUEDUCTO`, `REDES DE ALCANTARILLADO Y DRENAJE`, `REDES ELÉCTRICAS`, `REDES TELEFÓNICAS Y DATOS`, `CONCRETO Y ACERO PARA ESTRUCTURAS`, `EXCAVACIONES Y RELLENOS`, `ANDENES Y SARDINELES`, `SEÑALIZACIÓN`, `MOBILIARIO URBANO Y PAISAJISMO`.
- **No se toca ninguna escritura** (`servicio/autoria.py` queda igual) ni el importador de Excel. Ningún test existente de backend debe cambiar.
- Frontend: verificar con `npm run build` (`tsc -b`), **no** con `tsc --noEmit`.

## Estructura de archivos

| Archivo | Responsabilidad | Acción |
|---|---|---|
| `apu_tool/config.py` | `GRUPOS_APU_BASE` | modificar |
| `apu_tool/datos/repositorio.py` | declarar `grupos()` en `RepositorioApus` | modificar |
| `apu_tool/datos/apus_db.py` | `grupos()` SQLite | modificar |
| `apu_tool/datos/pg/apus_pg.py` | `grupos()` Postgres | modificar |
| `apu_tool/servicio/apus.py` | `grupos(alm)`: unión + dedup | modificar |
| `apu_tool/servicio/rutas.py` | `GET /api/apus/grupos` | modificar |
| `tests/test_apus_grupos.py` | vocabulario + autolimpieza | crear |
| `web/src/api/autoria.ts` | `getGruposApu()` | modificar |
| `web/src/components/autoria/DialogoAgregarApu.tsx` | `<select>` + `+ nuevo grupo` | modificar |
| `web/src/pages/Apus.tsx` | pasa `puedeCrearGrupo` en sus 3 montajes | modificar |
| `web/src/components/autoria/DialogoAgregarApu.test.tsx` | tests del select y del botón | modificar |
| `web/src/components/corrida/TablaItems.test.tsx`, `web/src/pages/Apus.duplicar.test.tsx` | sumar `getGruposApu` a la factory de `vi.mock` | modificar |

---

### Task 1: `grupos()` en la capa de datos (los dos backends)

**Files:**
- Modify: `apu_tool/datos/repositorio.py` (dentro de `class RepositorioApus(Protocol)`, que arranca en la línea 99; poner la firma junto a `search_apus`, línea 118)
- Modify: `apu_tool/datos/apus_db.py` (después de `list_apus`, que termina en la línea 210)
- Modify: `apu_tool/datos/pg/apus_pg.py` (después de `list_apus`, que termina en la línea 184)
- Test: `tests/test_apus_db.py` (agregar al final), `tests/test_repositorios_contrato.py` (agregar al final)

**Interfaces:**
- Produces: `RepositorioApus.grupos(self) -> list[str]` — los valores distintos y no vacíos de `apus.grupo`, ordenados por la base. Lo consume la Task 2.

- [ ] **Step 1: Escribir el test que falla (SQLite)**

En `tests/test_apus_db.py`, al final del archivo. Usa la fixture `apus` que ya existe (línea 8) — inserta `Apu("A1", "MURO", "M2", "DIURNO")`, o sea con `grupo` vacío por defecto, que es justo el caso que hay que filtrar:

```python
def test_grupos_distintos_sin_vacios(apus):
    apus.crear_apu(Apu("G1", "PISO", "M2", "DIURNO", "PAVIMENTOS"), [])
    apus.crear_apu(Apu("G2", "ANDEN", "M2", "DIURNO", "PAVIMENTOS"), [])
    apus.crear_apu(Apu("G3", "TUBO", "ML", "DIURNO", "REDES DE ACUEDUCTO"), [])
    # A1 (de la fixture) tiene grupo '' y no debe aparecer
    assert apus.grupos() == ["PAVIMENTOS", "REDES DE ACUEDUCTO"]
```

- [ ] **Step 2: Correr el test y verificar que falla**

Run: `python -m pytest tests/test_apus_db.py::test_grupos_distintos_sin_vacios -q`
Expected: FAIL con `AttributeError: 'ApusDB' object has no attribute 'grupos'`

- [ ] **Step 3: Implementar en SQLite**

En `apu_tool/datos/apus_db.py`, justo después del `return` de `list_apus` (línea 210). Es el espejo de `precios_db.py:418::grupos()`, sin la condición `oculto = 0` (la tabla `apus` no tiene esa columna):

```python
    def grupos(self) -> list[str]:
        """Grupos en uso por algún APU. Es la mitad viva del vocabulario de grupos
        (la otra es config.GRUPOS_APU_BASE): un grupo que deja de usarse desaparece,
        que es cómo se autolimpia un grupo mal escrito. Ver servicio/apus.py::grupos."""
        with self.connect() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM apus "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]
```

- [ ] **Step 4: Correr el test y verificar que pasa**

Run: `python -m pytest tests/test_apus_db.py::test_grupos_distintos_sin_vacios -q`
Expected: PASS

- [ ] **Step 5: Declararlo en el `Protocol`**

En `apu_tool/datos/repositorio.py`, dentro de `class RepositorioApus(Protocol)`, inmediatamente después de la línea 118 (`def search_apus(...)`):

```python
    def grupos(self) -> list[str]: ...
```

- [ ] **Step 6: Implementar en Postgres**

En `apu_tool/datos/pg/apus_pg.py`, justo después del `return` de `list_apus` (línea 184). Mismo comentario que en SQLite, tabla `apus.apus`:

```python
    def grupos(self) -> list[str]:
        """Grupos en uso por algún APU. Espejo de apus_db.py::grupos."""
        with self.cx.connection() as conn:
            rows = conn.execute(
                "SELECT DISTINCT grupo FROM apus.apus "
                "WHERE grupo IS NOT NULL AND grupo <> '' ORDER BY grupo").fetchall()
        return [r["grupo"] for r in rows]
```

- [ ] **Step 7: Test de contrato compartido por los dos backends**

En `tests/test_repositorios_contrato.py`, al final. La fixture `repos` (línea 39) está parametrizada sobre los dos backends y entrega la tupla `(precios, apus)`, así que este único test cubre SQLite y Postgres:

```python
def test_grupos_ignora_vacios_y_deduplica(repos):
    _, apus = repos
    apus.crear_apu(Apu("Z1", "PISO", "M2", "DIURNO", "PAVIMENTOS"), [])
    apus.crear_apu(Apu("Z2", "ANDEN", "M2", "DIURNO", "PAVIMENTOS"), [])
    apus.crear_apu(Apu("Z3", "SIN GRUPO", "M2", "DIURNO"), [])
    assert apus.grupos() == ["PAVIMENTOS"]
```

- [ ] **Step 8: Correr la suite de datos completa**

Run: `python -m pytest tests/test_apus_db.py tests/test_repositorios_contrato.py -q`
Expected: todo PASS. El `test_cumple_contrato` (línea 18 de `test_apus_db.py`) verifica el `Protocol` con `isinstance`, así que si la firma quedó mal, falla ahí.

Los tests de Postgres solo corren con un Postgres apuntado por env (receta en la memoria del proyecto: binarios portables EDB, puerto 55433). Si no está disponible, se saltan solos; queda cubierto en la Task 5.

- [ ] **Step 9: Commit**

```bash
git add apu_tool/datos/apus_db.py apu_tool/datos/pg/apus_pg.py apu_tool/datos/repositorio.py tests/test_apus_db.py tests/test_repositorios_contrato.py
git commit -m "feat(datos): grupos() lista los grupos de APU en uso, en los dos backends"
```

---

### Task 2: El vocabulario y su endpoint

**Files:**
- Modify: `apu_tool/config.py`
- Modify: `apu_tool/servicio/apus.py` (agregar `grupos` al final del módulo)
- Modify: `apu_tool/servicio/rutas.py` (después del endpoint `GET /apus`, que termina en la línea 483)
- Test: `tests/test_apus_grupos.py` (crear)

**Interfaces:**
- Consumes: `alm.apus.grupos() -> list[str]` (Task 1).
- Produces: `apu_tool.servicio.apus.grupos(alm: Almacen) -> list[str]` y `GET /api/apus/grupos` → `["ANDENES Y SARDINELES", …]` (array JSON plano de strings). Lo consume la Task 3.

- [ ] **Step 1: Escribir los tests que fallan**

Crear `tests/test_apus_grupos.py`. El helper `_alm` es el mismo patrón de `tests/test_auditoria_servicios_precios.py:7`; el cliente HTTP, el de `tests/test_api_autoria.py:13`:

```python
"""Vocabulario de grupos de APU: lista base de config ∪ grupos en uso."""
from apu_tool import config
from apu_tool.datos.almacen import Almacen
from apu_tool.nucleo.models import Apu
from apu_tool.servicio import apus as apus_svc
from apu_tool.servicio.app import create_app
from tests.conftest import cliente


def _alm(tmp_path):
    alm = Almacen(precios_path=tmp_path / "p.db", apus_path=tmp_path / "a.db",
                  corridas_path=tmp_path / "c.db")
    alm.init_schema()
    return alm


def test_incluye_la_lista_base_con_la_biblioteca_vacia(tmp_path):
    alm = _alm(tmp_path)
    assert apus_svc.grupos(alm) == sorted(config.GRUPOS_APU_BASE)


def test_suma_los_grupos_en_uso(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "OBRA ESPECIAL SL5")])
    out = apus_svc.grupos(alm)
    assert "OBRA ESPECIAL SL5" in out
    assert set(config.GRUPOS_APU_BASE) <= set(out)
    assert out == sorted(out)


def test_dedup_insensible_a_mayusculas_y_tildes_gana_config(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "señalizacion")])
    out = apus_svc.grupos(alm)
    assert out.count("SEÑALIZACIÓN") == 1
    assert "señalizacion" not in out          # gana la ortografía de config


def test_un_grupo_sin_apus_desaparece(tmp_path):
    """La autolimpieza es la propiedad por la que se eligió no tener tabla."""
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "TYPEO RARO")])
    assert "TYPEO RARO" in apus_svc.grupos(alm)
    alm.apus.borrar_apu("A1", "DIURNO")
    assert "TYPEO RARO" not in apus_svc.grupos(alm)


def test_endpoint_devuelve_el_vocabulario(tmp_path):
    alm = _alm(tmp_path)
    alm.apus.insert_apus([Apu("A1", "MURO", "M2", "DIURNO", "OBRA ESPECIAL SL5")])
    cli = cliente(create_app(almacen=alm), rol="consulta")
    r = cli.get("/api/apus/grupos")
    assert r.status_code == 200, r.text
    assert "OBRA ESPECIAL SL5" in r.json()
    assert "PAVIMENTOS" in r.json()
```

`borrar_apu(codigo, shift, conn=None) -> bool` ya existe en el `Protocol` (`datos/repositorio.py:109`) y borra componentes + cabecera, así que no hay que limpiar nada antes.

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `python -m pytest tests/test_apus_grupos.py -q`
Expected: FAIL — `AttributeError: module 'apu_tool.config' has no attribute 'GRUPOS_APU_BASE'`

- [ ] **Step 3: La lista base en `config.py`**

Agregar a `apu_tool/config.py`, cerca de las otras constantes de clasificación (junto a `PUBLIC_PRICE_SOURCES`):

```python
# Vocabulario base de grupos (capítulos de obra) para el desplegable de Grupo del APU.
# El vocabulario real que se sirve es esta lista UNIÓN los grupos que ya usa algún APU
# (ver servicio/apus.py::grupos): así un Admin crea un grupo nuevo simplemente usándolo,
# sin tabla ni migración, y un grupo mal escrito desaparece cuando ningún APU lo usa.
GRUPOS_APU_BASE: tuple[str, ...] = (
    "PAVIMENTOS",
    "REDES DE ACUEDUCTO",
    "REDES DE ALCANTARILLADO Y DRENAJE",
    "REDES ELÉCTRICAS",
    "REDES TELEFÓNICAS Y DATOS",
    "CONCRETO Y ACERO PARA ESTRUCTURAS",
    "EXCAVACIONES Y RELLENOS",
    "ANDENES Y SARDINELES",
    "SEÑALIZACIÓN",
    "MOBILIARIO URBANO Y PAISAJISMO",
)
```

- [ ] **Step 4: El vocabulario en `servicio/apus.py`**

Al final de `apu_tool/servicio/apus.py`. Hay que sumar dos imports arriba: `from apu_tool import config` y `from apu_tool.nucleo.texto import normalizar` (el módulo hoy solo importa `Almacen` y `PricingEngine`).

```python
def grupos(alm: Almacen) -> list[str]:
    """Vocabulario de grupos de APU: la lista base de config ∪ los grupos en uso.

    No hay tabla de grupos a propósito (ver el spec): así no hace falta migrar nada en
    Supabase, un Admin crea un grupo usándolo, y uno mal escrito se autolimpia cuando
    ningún APU lo usa. Dedup insensible a tildes/mayúsculas con `normalizar` (mismo
    criterio que servicio/listas.py); gana la ortografía de config.

    ponytail: el vocabulario se cierra en la pantalla, no acá — `crear_apu`/`editar_apu`
    siguen aceptando cualquier texto. Si algún día hay un segundo cliente de la API, el
    upgrade es exigir en esas dos escrituras que el grupo esté en este vocabulario salvo
    para rol == "admin".
    """
    vistos = {normalizar(g): g for g in alm.apus.grupos()}
    vistos.update({normalizar(g): g for g in config.GRUPOS_APU_BASE})
    return sorted(vistos.values())
```

- [ ] **Step 5: El endpoint**

En `apu_tool/servicio/rutas.py`, inmediatamente después del endpoint `GET /apus` (termina en la línea 483). No colisiona con `/apus/{codigo}/{turno}`, que son dos segmentos:

```python
@router.get("/apus/grupos")
def apus_grupos(alm: Almacen = Depends(get_almacen),
                _: object = Depends(requiere_rol("consulta"))):
    return apus_svc.grupos(alm)
```

`apus_svc` ya está importado (línea 21).

- [ ] **Step 6: Correr los tests y verificar que pasan**

Run: `python -m pytest tests/test_apus_grupos.py -q`
Expected: 5 passed

- [ ] **Step 7: Suite completa de backend, para probar que nada se rompió**

Run: `python -m pytest tests/ -q`
Expected: todo verde. No se tocó ninguna escritura, así que ningún test existente debería moverse. Si alguno falla, **no lo ajustes**: pará y reportá, porque significa que el cambio tocó algo que el plan no previó.

- [ ] **Step 8: Commit**

```bash
git add apu_tool/config.py apu_tool/servicio/apus.py apu_tool/servicio/rutas.py tests/test_apus_grupos.py
git commit -m "feat(api): GET /apus/grupos sirve el vocabulario de grupos de APU"
```

---

### Task 3: El `<select>` en el diálogo de APU

**Files:**
- Modify: `web/src/api/autoria.ts`
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx:330-337` (el `<label>` de Grupo)
- Modify: `web/src/components/corrida/TablaItems.test.tsx`, `web/src/pages/Apus.duplicar.test.tsx` (factories de `vi.mock`)
- Test: `web/src/components/autoria/DialogoAgregarApu.test.tsx`

**Interfaces:**
- Consumes: `GET /api/apus/grupos` (Task 2).
- Produces: `getGruposApu(): Promise<string[]>` en `@/api/autoria`; estado `grupos: string[]` en el diálogo. Lo consume la Task 4.

- [ ] **Step 1: El cliente de API**

En `web/src/api/autoria.ts`, después de `listarApus` (línea 43):

```ts
export function getGruposApu(): Promise<string[]> {
  return apiGet<string[]>("/apus/grupos");
}
```

- [ ] **Step 2: Sumar `getGruposApu` a las factories de mock que ya existen**

Las factories de `vi.mock("@/api/autoria", () => ({...}))` listan función por función, así que un miembro ausente revienta al llamarse. Agregar esta línea a la factory de `web/src/components/corrida/TablaItems.test.tsx` y de `web/src/pages/Apus.duplicar.test.tsx` (ambos abren el diálogo):

```ts
  getGruposApu: vi.fn(async () => ["PAVIMENTOS", "REDES DE ACUEDUCTO"]),
```

- [ ] **Step 3: Escribir el test que falla**

En `web/src/components/autoria/DialogoAgregarApu.test.tsx`. Primero agregar `getGruposApu` a la factory de `vi.mock` del propio archivo (línea 6-14), con la misma línea del Step 2. Después, al final del archivo:

```tsx
test("Grupo es un select con el vocabulario del backend", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(<DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}} />);
  const sel = await screen.findByLabelText("Grupo");
  expect(sel.tagName).toBe("SELECT");
  await waitFor(() =>
    expect(screen.getByRole("option", { name: "PAVIMENTOS" })).toBeTruthy());
  expect(screen.queryByRole("option", { name: "REDES DE ACUEDUCTO" })).toBeTruthy();
});

test("editar un APU con un grupo fuera del vocabulario lo conserva como opción", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}}
      modo="editar" inicial={{ ...inicialDemo, grupo: "NA" }} />,
  );
  const sel = (await screen.findByLabelText("Grupo")) as HTMLSelectElement;
  await waitFor(() => expect(sel.value).toBe("NA"));
  expect(screen.getByRole("option", { name: "NA" })).toBeTruthy();
});
```

`inicialDemo` ya existe en el archivo (línea 19).

- [ ] **Step 4: Correr los tests y verificar que fallan**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: FAIL — el elemento de Grupo es un `INPUT`, no un `SELECT`.

- [ ] **Step 5: Cargar el vocabulario en el diálogo**

En `web/src/components/autoria/DialogoAgregarApu.tsx`:

a) Sumar `getGruposApu` al import de la línea 18:
```ts
import { crearApu, editarApu, listarApus, getGruposApu } from "@/api/autoria";
```

b) Estado, junto a `const [ocupados, setOcupados] = useState<string[]>([]);` (línea 120):
```ts
  const [grupos, setGrupos] = useState<string[]>([]);
```

c) Efecto de carga, después del efecto de `ocupados` (que termina en la línea 178). Mismo patrón de cancelación que ese efecto:
```ts
  // Vocabulario de grupos. Si falla, el select queda con el grupo actual como única
  // opción: se puede guardar sin cambiarlo, pero no inventar uno nuevo.
  useEffect(() => {
    if (!open) return;
    let cancelado = false;
    (async () => {
      try {
        const gs = await getGruposApu();
        if (!cancelado) setGrupos(gs);
      } catch {
        /* sin vocabulario: queda el grupo actual */
      }
    })();
    return () => {
      cancelado = true;
    };
  }, [open]);
```

d) Limpiar en `handleOpenChange` (línea 184-193), junto a `setOcupados([])`:
```ts
      setGrupos([]);
```

- [ ] **Step 6: Cambiar el input por el select**

Reemplazar el `<label>` de Grupo (líneas 330-337) por:

```tsx
          <label className="flex flex-col gap-1 text-xs">
            <span className="text-muted-foreground">Grupo</span>
            <select
              aria-label="Grupo"
              className={inputCls}
              value={cab.grupo}
              onChange={(e) => setCabecera("grupo", e.target.value)}
            >
              {/* Placeholder deshabilitado: `cabeceraValida` ya exige grupo no vacío,
                  así que el guardado sigue bloqueado hasta que se elija uno. */}
              <option value="" disabled>
                Elegí un grupo…
              </option>
              {opcionesGrupo.map((g) => (
                <option key={g} value={g}>
                  {g}
                </option>
              ))}
            </select>
          </label>
```

Y el derivado, junto a `cabeceraValida` (línea 211):

```ts
  // El grupo actual va SIEMPRE entre las opciones aunque no esté en el vocabulario:
  // si no, abrir un APU viejo con grupo 'NA' le cambiaría el grupo sin querer.
  const opcionesGrupo =
    cab.grupo && !grupos.includes(cab.grupo) ? [cab.grupo, ...grupos] : grupos;
```

`inputCls` (línea 68) sirve igual para el `<select>`.

- [ ] **Step 7: Correr los tests y verificar que pasan**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: PASS

- [ ] **Step 8: Suite de frontend + build**

Run: `cd web && npx vitest run` y después `cd web && npm run build`
Expected: todo verde. `npm run build` corre `tsc -b`, que es el que agarra los errores de tipos reales (`tsc --noEmit` ya dejó pasar uno).

- [ ] **Step 9: Commit**

```bash
git add web/src/api/autoria.ts web/src/components/autoria/DialogoAgregarApu.tsx web/src/components/autoria/DialogoAgregarApu.test.tsx web/src/components/corrida/TablaItems.test.tsx web/src/pages/Apus.duplicar.test.tsx
git commit -m "feat(web): el Grupo del APU se elige de un desplegable"
```

---

### Task 4: "+ nuevo grupo" para Admin

**Files:**
- Modify: `web/src/components/autoria/DialogoAgregarApu.tsx` (props + botón)
- Modify: `web/src/pages/Apus.tsx:41` y sus 3 montajes del diálogo (líneas 294, 304, 312)
- Test: `web/src/components/autoria/DialogoAgregarApu.test.tsx`

**Interfaces:**
- Consumes: el estado `grupos` y el derivado `opcionesGrupo` (Task 3).
- Produces: prop `puedeCrearGrupo?: boolean` (default `false`) en `DialogoAgregarApuProps`.

- [ ] **Step 1: Escribir los tests que fallan**

Al final de `web/src/components/autoria/DialogoAgregarApu.test.tsx`:

```tsx
test("'+ nuevo grupo' no se muestra sin permiso de Admin", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  render(<DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}} />);
  await screen.findByLabelText("Grupo");
  expect(screen.queryByText("+ nuevo grupo")).toBeNull();
});

test("un Admin crea un grupo y queda elegido", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  const spy = vi.spyOn(window, "prompt").mockReturnValue("  OBRA NUEVA SL7  ");
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}} puedeCrearGrupo />,
  );
  const sel = (await screen.findByLabelText("Grupo")) as HTMLSelectElement;
  fireEvent.click(screen.getByText("+ nuevo grupo"));
  await waitFor(() => expect(sel.value).toBe("OBRA NUEVA SL7"));   // recortado
  expect(screen.getByRole("option", { name: "OBRA NUEVA SL7" })).toBeTruthy();
  spy.mockRestore();
});

test("cancelar el prompt no cambia el grupo", async () => {
  const { DialogoAgregarApu } = await import("./DialogoAgregarApu");
  const spy = vi.spyOn(window, "prompt").mockReturnValue(null);
  render(
    <DialogoAgregarApu open onOpenChange={() => {}} onCreado={() => {}} puedeCrearGrupo />,
  );
  const sel = (await screen.findByLabelText("Grupo")) as HTMLSelectElement;
  fireEvent.click(screen.getByText("+ nuevo grupo"));
  expect(sel.value).toBe("");
  spy.mockRestore();
});
```

- [ ] **Step 2: Correr los tests y verificar que fallan**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: FAIL en los dos últimos — no existe el botón "+ nuevo grupo".

- [ ] **Step 3: La prop**

En `DialogoAgregarApuProps` (línea 30-38):

```ts
  /** Rol Admin: habilita crear un grupo nuevo. El rol NO se lee con useAuth() acá
   *  porque `useAuth` lanza fuera de <AuthProvider> (lib/auth.tsx:68) y este diálogo
   *  se monta sin provider en los tests. */
  puedeCrearGrupo?: boolean;
```

Y en la desestructuración (línea 105-111), con default:

```ts
  puedeCrearGrupo = false,
```

- [ ] **Step 4: El botón**

Dentro del `<label>` de Grupo de la Task 3, después del `</select>`:

```tsx
            {puedeCrearGrupo && (
              <button
                type="button"
                className="self-start text-[11px] text-muted-foreground underline underline-offset-2 hover:text-foreground"
                onClick={nuevoGrupo}
              >
                + nuevo grupo
              </button>
            )}
```

Y el handler, junto a `setCabecera` (línea 180). `window.prompt` es el patrón de la casa (listas, carpetas, renombrar corridas) y evita el modal anidado que ya se revirtió una vez:

```ts
  // Un grupo nuevo no se persiste solo: queda elegido y se guarda con el APU. Si el
  // usuario cancela el diálogo, no se creó nada, que es lo correcto.
  function nuevoGrupo() {
    const nombre = window.prompt("Nombre del grupo nuevo (capítulo de obra)");
    const limpio = (nombre ?? "").trim();
    if (!limpio) return;
    setGrupos((prev) => (prev.includes(limpio) ? prev : [...prev, limpio].sort()));
    setCabecera("grupo", limpio);
  }
```

- [ ] **Step 5: Correr los tests y verificar que pasan**

Run: `cd web && npx vitest run src/components/autoria/DialogoAgregarApu.test.tsx`
Expected: PASS

- [ ] **Step 6: Pasar la prop desde la página de APUs**

En `web/src/pages/Apus.tsx`, la línea 41 ya calcula `const puedeBorrar = puede(perfil?.rol, "admin");`. Agregar debajo:

```ts
  const esAdmin = puede(perfil?.rol, "admin");
```

y sumar `puedeCrearGrupo={esAdmin}` a los **tres** montajes de `<DialogoAgregarApu>` (líneas 294, 304 y 312).

`TablaItems.tsx` no se toca: el flujo de duplicar desde una corrida no es el momento de crear vocabulario, y un grupo creado desde la página de APUs queda disponible en todas partes igual.

- [ ] **Step 7: Suite de frontend + build**

Run: `cd web && npx vitest run` y después `cd web && npm run build`
Expected: todo verde.

- [ ] **Step 8: Commit**

```bash
git add web/src/components/autoria/DialogoAgregarApu.tsx web/src/components/autoria/DialogoAgregarApu.test.tsx web/src/pages/Apus.tsx
git commit -m "feat(web): un Admin puede crear un grupo de APU desde el desplegable"
```

---

### Task 5: Verificación end-to-end en el navegador

Ningún push antes de esto: en cambios de UI el navegador va antes que el push (lección del `DialogoTexto`, que pasó 145 tests y se cerraba solo en el navegador).

- [ ] **Step 1: Suite completa, los dos lados**

Run: `python -m pytest tests/ -q` y `cd web && npx vitest run && npm run build`
Expected: todo verde. Anotar el número de tests de cada lado.

- [ ] **Step 2: Correr también los tests de Postgres**

`grupos()` se implementó en los dos backends y solo SQLite quedó cubierto por defecto. Levantar el Postgres desechable de la receta del proyecto (binarios portables EDB, puerto 55433) y correr la suite con él apuntado. **Nunca** apuntar esos tests a producción: hacen `DROP SCHEMA`.

Si no se puede levantar, decirlo explícitamente en el reporte en vez de darlo por cubierto.

- [ ] **Step 3: Levantar la web en local**

Sin `SUPABASE_URL` + `APU_ADMIN_EMAILS` el login rebota con 401 en todo `/api` (receta en la memoria del proyecto).

- [ ] **Step 4: Probar los cuatro casos a mano**

1. **APUs → agregar APU**: el desplegable de Grupo trae los 10 capítulos más los grupos que ya usan los APUs de la base.
2. **Editar un APU con grupo vacío**: el select arranca en "Elegí un grupo…", *Guardar* está bloqueado hasta elegir uno.
3. **Editar un APU con grupo raro** (en la base local hay `NA` y `Pruebas`): ese valor aparece como opción y queda seleccionado, sin cambiarse solo.
4. **Como Admin**: "+ nuevo grupo" pide el nombre, lo deja elegido, y al guardar el APU el grupo aparece en el desplegable la próxima vez que se abre. Como editor, el botón no está.

- [ ] **Step 5: Reportar y pedir el push**

Master autodespliega, así que el push necesita aprobación explícita. Reportar: número de tests de cada suite, si los tests de Postgres corrieron o no, y el resultado de los 4 casos del navegador.

---

## Notas de la autorevisión

- **`servicio/autoria.py` no aparece en ninguna tarea, a propósito**: el spec decidió no validar el vocabulario en el backend. Si una tarea toca ese archivo, se salió del alcance.
- **El importador de Excel (`aplicar_importar_apus`) tampoco se toca**: escribe por `alm.apus.crear_apu` directo. Los grupos que entren por Excel aparecen solos en el desplegable, y eso es lo buscado.
- **Nombres que tienen que coincidir entre tareas**: `grupos()` (datos, Task 1) · `apus_svc.grupos(alm)` (servicio, Task 2) · `getGruposApu()` (API cliente, Task 3) · el estado `grupos` y el derivado `opcionesGrupo` (Task 3, usados por `nuevoGrupo` en Task 4) · la prop `puedeCrearGrupo` (Task 4).
- **`GRUPOS_APU_BASE` es una `tuple`**, no una lista: es una constante de `config.py` y no debe mutarse.
