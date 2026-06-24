# Diseño — Frontend web + API (v1: armar el cuadro)

> Fecha: 2026-06-24
> Estado: aprobado para implementación
> Hoja de ruta: ejecuta los pasos 4 (API/FastAPI) y 5 (app web) de `docs/ARQUITECTURA.md`,
> acotados a un primer corte vertical.

## Objetivo

Construir un primer corte vertical de la app web del Armador de APUs: un analista
**sube una licitación plana**, el sistema **arma el cuadro**, el analista **revisa y
confirma** los ítems dudosos/nuevos en pantalla, y **descarga el cuadro resumen** en Excel.

La API (FastAPI) expone el dominio existente; el frontend (React) la consume. **El dominio
no cambia** (salvo, quizá, exponer un método público fino de re-costeo, a confirmar en el
plan). Se respetan todas las convenciones del proyecto.

## Decisiones de alcance (v1)

| Decisión | Elección |
|----------|----------|
| Alcance | Corte vertical: armar el cuadro (subir → revisar → confirmar → cuadro) |
| Entrada | Licitación plana (`run_pipeline` → cuadro resumen). NO presupuesto por capítulos |
| Profundidad de revisión | Confirmar o **elegir otro APU entre los candidatos** del matcher, con recosteo en vivo. NO se edita la composición |
| Búsqueda libre de APUs | **Fuera del v1** (fast-follow: `GET /api/apus?q=...`) |
| Estado de la corrida | Persistida ligera (tabla nueva vía repositorio). Sobrevive recarga/reinicio. Sin gestión completa de proyectos |
| Despliegue | Local, sin login, SQLite, un solo proceso |
| Frontend | Vite + React + `shadcn/ui`, compilado a estáticos que **FastAPI sirve** en prod (Enfoque A) |

Fuera de v1 (fast-follow conocidos): mantenimiento de precios, biblioteca de APUs,
chequeo de integridad en UI, auth de equipo, Postgres/nube, progreso por SSE,
edición de composición, búsqueda libre de APUs, rechazar/manual en el panel.

## Arquitectura y estructura de archivos

Regla de oro respetada: **el dominio no sabe quién lo llama.** La API llama al dominio; el
frontend llama a la API. Sin lógica nueva en capas equivocadas; sin SQL crudo fuera de `datos/`.

```
apu_tool/
├── servicio/                  ── NIVEL 03 · API (FastAPI)  [se llena ahora]
│   ├── app.py                 #   crea la app, monta rutas, sirve estáticos del web en prod
│   ├── rutas.py               #   endpoints (delgados: validan y llaman al dominio)
│   ├── esquemas.py            #   DTOs Pydantic (request/response) — contrato HTTP explícito
│   └── dependencias.py        #   cableado de Almacen / Assembler (singleton por proceso)
│
├── datos/
│   ├── corridas_db.py         #   RepositorioCorridas → data/corridas.db   [nuevo]
│   ├── repositorio.py         #   + Protocol RepositorioCorridas           [se amplía]
│   └── almacen.py             #   Almacen gana .corridas                    [se amplía]
│
db/
└── corridas.sql               #   DDL canónico de la corrida                [nuevo]

web/                           ── NIVEL 04 · frontend (Vite + React)         [nuevo]
├── index.html  vite.config.ts  package.json  tsconfig.json
├── src/
│   ├── api/         #   cliente tipado contra /api (fetch)
│   ├── pages/       #   Inicio (nueva corrida) · Corrida (cuadro)
│   ├── components/  #   tabla de ítems · panel de revisión · chips de estado
│   └── lib/         #   tipos compartidos, formato de moneda
└── (build → dist/, que FastAPI sirve en prod)

run_web.py                     #   lanza FastAPI (uvicorn) y abre el navegador  [nuevo]
```

**Por qué una BD aparte (`corridas.db`):** `precios.db` y `apus.db` son la *fuente de
verdad* del negocio. Una "corrida" es **estado de aplicación** (un trabajo de armado en
progreso), no dato canónico. Su propio store la mantiene fuera de las bases de verdad y
respeta la convención de aislar persistencia tras un repositorio.

**Lo que la API NO hace:** no habla con la IA. Las llamadas a la IA siguen dentro del
dominio (`assemble.py` → `ai_assist.py`), detrás de `privacy.py`.

**Cómo se sirve (Enfoque A):**
- Desarrollo: `vite dev` (:5173) hace proxy de `/api` a FastAPI (:8000).
- Uso local / prod: `python run_web.py` levanta FastAPI (:8000), que sirve `/api/*` →
  dominio y `/*` → estáticos de `web/dist`, y abre el navegador. Un solo proceso. Node solo
  se necesita para compilar, no en runtime.

## Contrato de la API

Endpoints REST bajo `/api`. Delgados: validan, llaman al dominio, mapean a DTOs. El dinero
(contractual, costo, margen) **sí** va en las respuestas — es el cuadro para el equipo; la
frontera de la IA es interna y no se toca.

| Método + ruta | Hace | Dominio que usa |
|---|---|---|
| `GET /api/status` | Estado de las bases (conteos, IA on/off) para el encabezado | `alm.counts()`, `config.ai_available()` |
| `POST /api/sample` | Genera una licitación de ejemplo y la deja lista para subir | `generate_sample` |
| `POST /api/corridas` | **Crea la corrida.** Multipart: archivo `.xlsx/.csv` + `turno` + `use_ai`. Lee, matchea y arma todos los ítems (aquí corre la IA para REVIEW/NEW), persiste y devuelve `{id, resumen}` | `read_licitacion` + `Assembler.assemble_all` → `RepositorioCorridas` |
| `GET /api/corridas/{id}` | Cuadro completo: ítems con status, APU elegido y números recosteados + totales | re-costeo determinístico + repo |
| `GET /api/corridas/{id}/items/{seq}` | Detalle de un ítem: candidatos con score + composición costeada del APU elegido | repo + `pricing` |
| `POST /api/corridas/{id}/items/{seq}/confirmar` | `{apu_codigo, shift?}` → rehace el ítem con ese APU, persiste (status `confirmed`), devuelve ítem recosteado + totales actualizados | `Assembler.reassemble_with_choice` |
| `GET /api/corridas/{id}/cuadro` | Genera el Excel y lo devuelve como descarga | `write_report` |

**Notas:**
- `POST /api/corridas` es la llamada pesada (lee + matchea + IA por ítem). En v1 va
  **síncrona** con spinner. Mejora futura: progreso por SSE (el dominio ya acepta un
  `progress` callback).
- "Elegir otro APU" en v1 = elegir **entre los candidatos** del matcher (sin dinero).
  Búsqueda libre queda fuera del v1.
- **Sin datos sembrados:** `POST /api/corridas` llama `ensure_seeded()` primero, como la CLI.

## Modelo de datos — la corrida persistida

Se persisten **decisiones y estructura**, no dinero. El costo se recalcula siempre con el
precio vigente.

`db/corridas.sql`:

```sql
CREATE TABLE corrida (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  creada_en     TEXT NOT NULL,           -- ISO 8601
  archivo       TEXT NOT NULL,           -- nombre de la licitación subida
  turno_def     TEXT NOT NULL,           -- DIURNO / NOCTURNO
  use_ai        INTEGER,                 -- 0/1/NULL (auto)
  estado        TEXT NOT NULL,           -- 'en_revision' | 'finalizada'
  cuadro_path   TEXT                     -- ruta del Excel ya generado (o NULL)
);

CREATE TABLE corrida_item (
  id            INTEGER PRIMARY KEY AUTOINCREMENT,
  corrida_id    INTEGER NOT NULL REFERENCES corrida(id) ON DELETE CASCADE,
  seq           INTEGER NOT NULL,
  item_json     TEXT NOT NULL,    -- LicitacionItem de entrada (incl. precio_contractual)
  status        TEXT NOT NULL,    -- auto | review | new | confirmed | rejected
  apu_codigo    TEXT,             -- APU elegido (NULL si manual)
  apu_nombre    TEXT,
  unidad        TEXT, shift TEXT, origen TEXT,
  confianza     REAL, explicacion TEXT,
  componentes_json TEXT,  -- estructura SIN dinero: [{insumo_codigo,nombre,unidad,rendimiento}]
  candidatos_json  TEXT   -- SIN dinero: [{apu_codigo,apu_nombre,score,motivo}]
);
CREATE INDEX ix_corrida_item ON corrida_item(corrida_id, seq);
```

`RepositorioCorridas` (Protocol en `repositorio.py`, impl en `corridas_db.py`):
`crear_corrida(meta) → id` · `guardar_items(id, items)` · `get_corrida(id)` ·
`get_items(id)` · `get_item(id, seq)` · `actualizar_item(id, seq, **campos)` ·
`set_cuadro(id, path)` · `set_estado(id, estado)`.

Devuelve dataclasses puras nuevas en `nucleo/models.py` (`CorridaMeta`, `CorridaItemRow`),
coherente con "la capa de datos devuelve modelos del núcleo".

**Re-costeo:** se guarda la **estructura** (insumo + rendimiento). Para el cuadro/detalle,
el servicio arma `ApuComponent` desde esa estructura y llama
`PricingEngine.cost_components(...)` (ya existe; lo usa `assemble.py`), que devuelve
componentes costeados + total con el precio vigente. Congelar la estructura y flotar solo
los precios cumple el principio "el costo se calcula llamando al precio vigente". Confirmar
otro APU re-snapshotea la estructura (vía `reassemble_with_choice`) y vuelve a costear.

**Candidatos:** se obtienen del `Matcher` (determinístico, sin IA, sin dinero); el APU
elegido + status + explicación vienen del `Assembler`. Sin tocar la API del dominio.

## Frontend — pantallas y flujo

Tres vistas, React + `shadcn/ui`. Cliente `/api` tipado en `web/src/api`.

**1. Inicio / Nueva corrida**
- Encabezado con estado de las bases (`GET /api/status`): nº de APUs/insumos y chip
  **IA: habilitada / fallback**.
- Zona de carga: arrastrar/soltar `.xlsx`/`.csv`, selector de **turno por defecto**
  (DIURNO/NOCTURNO) y toggle **usar IA**.
- Botón secundario **"Usar ejemplo"** (`POST /api/sample`) para probar sin datos reales.
- Al subir → `POST /api/corridas` (spinner) → navega a la corrida.

**2. Corrida (el cuadro)** — `GET /api/corridas/{id}`
- **Totales arriba:** contractual, costo, margen y margen %.
- **Tabla de ítems:** descripción · unidad · cantidad · APU elegido · **chip de status**
  (AUTO verde / REVIEW ámbar / NEW gris / CONFIRMED azul) · contractual · costo · margen ·
  margen %.
- Filtro rápido **"Solo los que requieren revisión"** (REVIEW + NEW) y contador "N por revisar".
- Una fila REVIEW/NEW abre el panel de revisión. Botón **"Descargar cuadro"** (`GET .../cuadro`).

**3. Panel de revisión de un ítem** (drawer lateral) — `GET .../items/{seq}`
- Arriba: descripción del ítem + el APU propuesto y su **explicación**.
- **Candidatos:** lista con nombre + **score**; el elegido marcado. Seleccionar otro →
  `POST .../confirmar` → recostea en vivo y actualiza totales.
- **Composición costeada** del APU seleccionado: insumo · unidad · rendimiento · precio
  vigente · costo · aviso de **calidad del cruce** (exacto/aproximado/ambiguo/huérfano, que
  `CostedComponent` ya trae).
- Acción **Confirmar** (status → CONFIRMED). Rechazar/manual queda como gancho para después.

**Formato:** moneda en COP sin decimales (como la CLI: `$1,234,567`), helper en `web/src/lib`.

## Errores, privacidad y pruebas

**Manejo de errores (API → UI):**
- Excel/CSV ilegible o sin columnas esperadas → `400` con mensaje claro; la UI lo muestra en
  la zona de carga.
- Corrida o ítem inexistente → `404`.
- APU elegido inexistente / turno sin ese APU → `422` con detalle (el dominio cae a otro
  turno cuando puede; si no, se reporta).
- Base vacía → no es error: `POST /api/corridas` llama `ensure_seeded()` primero.
- IA caída o sin `ANTHROPIC_API_KEY` → no es error: fallback determinístico (como hoy). La UI
  refleja "IA: fallback" en el encabezado.
- Errores no previstos → `500` con id de error en el log; nunca se filtra stack al cliente.

**Privacidad (Invariante #1):**
- La API no importa ni llama `ai_assist`; toda interacción con la IA queda en el dominio,
  detrás de `privacy.py`. No se crea ningún camino nuevo hacia la IA.
- Los DTOs de respuesta sí llevan dinero (es el cuadro para el equipo) — permitido; el
  invariante gobierna lo que ve la IA, no lo que ve el equipo.
- **Test de regresión:** verificar que el paquete `servicio` no referencia `ai_assist` y que
  el estado persistido de la corrida no guarda campos monetarios (espíritu de
  `assert_no_money` sobre `componentes_json` / `candidatos_json`).

**Pruebas:**
- **Backend (pytest + FastAPI `TestClient`):** crear corrida desde el ejemplo → `GET` cuadro
  → confirmar un ítem → re-`GET` (totales cambian) → descargar Excel. Más pruebas del
  `RepositorioCorridas` (roundtrip, cascade delete) al estilo de `tests/test_*_db.py`.
- **Frontend:** ligero en v1 — Vitest + React Testing Library solo para la lógica del panel
  de revisión (selección de candidato → llamada → recosteo). Sin sobre-invertir.
- Se corre `pytest` antes de dar nada por terminado.

**Convenciones respetadas:** español en el dominio; persistencia solo en `datos/`; sin
dependencias pesadas en el backend (FastAPI + uvicorn + python-multipart); el dominio no se
modifica salvo, quizá, exponer un método público fino de re-costeo (a confirmar en el plan).

## Dependencias nuevas

- **Backend:** `fastapi`, `uvicorn`, `python-multipart` (subida de archivos). Se agregan a
  `requirements.txt`.
- **Frontend (solo build):** Node + Vite + React + TypeScript + `shadcn/ui` (Tailwind).
  Aislado en `web/`; no afecta el runtime de Python.

## Criterios de aceptación (v1)

1. `python run_web.py` levanta un solo proceso y abre el navegador en la app.
2. Subir el ejemplo (o un `.xlsx/.csv` propio) crea una corrida y muestra el cuadro con totales.
3. Los ítems se marcan con su status; el filtro "por revisar" funciona.
4. En el panel, elegir/confirmar un candidato recostea el ítem y actualiza los totales en vivo.
5. La corrida sobrevive recargar la página (estado persistido).
6. "Descargar cuadro" entrega el Excel correcto.
7. `pytest` pasa, incluido el test de regresión de privacidad del servicio.
8. La IA nunca recibe dinero (invariante intacto); con IA apagada todo corre igual.
