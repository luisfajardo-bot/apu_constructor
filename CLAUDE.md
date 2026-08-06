# CLAUDE.md

Guía para trabajar en este repositorio. Léela antes de modificar código.

## Qué es

**Armador de APUs** (Análisis de Precios Unitarios) de obra civil. Toma una lista de
licitación, reutiliza el histórico de la empresa para armar los APUs, y entrega un
**cuadro resumen** que compara **precio contractual** vs **precio de costo**.

## Invariante #1 — la IA nunca ve dinero (NO LA ROMPAS)

La IA solo decide la **estructura** de los APUs (qué insumos, qué rendimiento).
**Nunca** debe recibir precios, costos ni totales.

- Todo payload que salga hacia la IA pasa por `apu_tool/privacy.py::assert_no_money`,
  que recorre la estructura y **lanza `PrivacyViolation`** si encuentra un campo
  monetario. Preferimos *fallar* a *filtrar*.
- Lo que la IA recibe son los tipos `DePriced*` de `apu_tool/nucleo/models.py`, sin campos de precio.
- Solo `apu_tool/dominio/pricing.py` y `apu_tool/dominio/report.py` tocan dinero, y jamás se pasan a la IA.

Si agregas una llamada a la IA, construye el payload con helpers de `apu_tool/dominio/privacy.py` y
serialízalo con `privacy.safe_json(...)`. Si agregas un campo monetario nuevo,
añádelo a `_FORBIDDEN_KEYS` en `apu_tool/dominio/privacy.py`.

## Comandos

```bash
pip install -r requirements.txt

python run_cli.py demo      # semilla + ejemplo + cuadro resumen (todo)
python run_cli.py seed      # semillar las bases desde el Excel histórico
python run_cli.py seed --force  # re-semillar (borra datos mantenidos Y listas NP, sin Excel del que recuperarlas)
python run_cli.py build <licitacion.xlsx>
python run_cli.py status
python run_cli.py db price <codigo>     # precio vigente + historial de un insumo
python run_cli.py db update-price <codigo> <precio> [--fuente ...]
python run_gui.py           # interfaz tkinter

python -m pytest tests/ -q  # pruebas
```

La IA se activa solo si existe `ANTHROPIC_API_KEY`; sin ella se usa un fallback
determinístico y todo corre igual. Modelo por defecto: `claude-sonnet-5`
(`apu_tool/config.py::AI_MODEL`, se cambia con la env `APU_AI_MODEL`). Si lo
cambias, el modelo debe soportar pensamiento adaptativo, `effort` y salida
estructurada: es lo que pide `dominio/ai_assist.py`.

## Arquitectura (flujo)

```
Excel histórico ──seed──► SQLite/Postgres (precios, apus, corridas, perfiles, auditoría)
lista licitación ──► matching ──► IA acotada (sin dinero) ──► confirma usuario
                                       └─► motor de precios ──► cuadro resumen (Excel)

Interfaces sobre el mismo pipeline (dominio/pipeline.py):
  interfaz/{cli,gui}.py (local) · servicio/ (FastAPI, 50 endpoints) + web/ (React) para multiusuario
```

`apu_tool/config.py` es transversal, fuera de cualquier paquete: rutas, umbrales de
matching, modelo de IA, clasificación de precios.

### `apu_tool/nucleo/` — tipos y utilidades puras (sin dependencias de otras capas)

| Módulo | Responsabilidad |
|--------|-----------------|
| `models.py`   | tipos del dominio; vistas `DePriced*` SIN dinero |
| `redondeo.py` | redondeo a la unidad (peso) en multiplicaciones monetarias |
| `relevancia.py` | orden por relevancia de una búsqueda + scorer `similarity` |
| `texto.py`    | normalización de texto compartida |

### `apu_tool/datos/` — persistencia (**toda** la persistencia pasa por aquí)

| Módulo | Responsabilidad |
|--------|-----------------|
| `repositorio.py`  | contratos de almacenamiento (`Protocol`), por dominio |
| `precios_db.py`   | SQLite de `precios.db` (catálogo + precios) |
| `apus_db.py`      | SQLite de `apus.db` (biblioteca de APUs) |
| `carpetas_db.py`  | SQLite de carpetas de corridas |
| `corridas_db.py`  | SQLite de `corridas.db` (estado de corridas en curso) |
| `auditoria_db.py` | SQLite de auditoría (`seguridad.db`) |
| `perfiles_db.py`  | SQLite de perfiles (identidad + rol) |
| `almacen.py`      | fachada que agrupa los repos SQLite/Postgres |
| `seed.py`         | ingesta Excel histórico → bases |
| `correcciones.py` | correcciones de código aplicadas al semillar |
| `migracion_pg.py` | migración SQLite → Postgres (Supabase); corridas NO se migran |
| `pg/`             | backend Postgres (espejo 1:1 de los `*_db.py`, para la nube) |

### `apu_tool/dominio/` — motor de negocio (`pricing.py` es el **único** que ve dinero)

| Módulo | Responsabilidad |
|--------|-----------------|
| `licitacion.py`          | lectura de la lista de entrada + generador de ejemplo |
| `presupuesto.py`         | lectura del presupuesto oficial por capítulos |
| `matching.py`            | matcher determinístico (fuzzy, sin dependencias externas) |
| `cruce.py`               | cruce insumo-de-APU ↔ insumo-de-catálogo por código+nombre |
| `compose.py`             | candidatos de insumos para composición generativa |
| `privacy.py`             | frontera de precios para la IA (invariante #1) |
| `ai_assist.py`           | IA acotada (Anthropic SDK) + fallback determinístico |
| `assemble.py`            | orquestador por ítem |
| `pricing.py`             | motor de costos (**ÚNICO** que ve dinero) |
| `alertas.py`             | alertas de costeo (por qué un ítem necesita revisión) |
| `report.py`              | cuadro resumen en Excel |
| `report_categorizado.py` | cuadro resumen agrupado por capítulos de presupuesto |
| `integridad.py`          | chequeo de integridad del vínculo APU↔insumo |
| `pipeline.py`            | orquestación de alto nivel (la usan CLI, GUI y el servicio web) |

### `apu_tool/servicio/` — API web (FastAPI)

| Módulo | Responsabilidad |
|--------|-----------------|
| `app.py`               | arma la app FastAPI: monta `/api`, sirve `web/dist`, middlewares de seguridad |
| `rutas.py`             | el único `APIRouter`; todos los endpoints HTTP (delega a los módulos de abajo) |
| `dependencias.py`      | inyección de dependencias (el `Almacen` vive en `app.state`) |
| `esquemas.py`          | DTOs del contrato HTTP |
| `auth.py`              | autenticación (Supabase Auth) + autorización por rol |
| `limites.py`           | límite de tamaño de subida + rate limiting |
| `seguridad_headers.py` | middleware de headers de seguridad (HSTS, CSP, etc.) |
| `corridas.py`          | lógica de servicio de corridas (armado en vivo) |
| `insumos.py`           | lógica de servicio para editar insumos |
| `listas.py`            | listas de precios (tarifas): Principal + una por obra de NP |
| `autoria.py`           | alta de insumos/APUs nuevos |
| `subapus.py`           | migración: marca componentes que son sub-APU |
| `apus.py`              | lectura de la biblioteca de APUs |
| `carpetas.py`          | reglas de carpetas de corridas |
| `usuarios.py`          | gestión de usuarios (solo Admin) |
| `auditoria.py`         | servicio de auditoría (registro + lectura paginada) |
| `supabase_admin.py`    | cliente de la Admin API de Supabase Auth |
| `plantillas.py`        | plantillas `.xlsx` para importadores |
| `presencia.py`         | quién está usando la app ahora (dict en memoria, sin DB) |

### `apu_tool/interfaz/` — puntos de entrada

| Módulo | Responsabilidad |
|--------|-----------------|
| `cli.py` | línea de comandos |
| `gui.py` | interfaz gráfica (Tkinter) |

## Convenciones

- **Persistencia aislada en `apu_tool/datos/`.** No metas SQL crudo en otros módulos. Esto
  permite migrar a Postgres/nube reemplazando una sola capa (plan: local primero,
  nube después).
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias pesadas:** el matcher usa stdlib (`difflib`); `openpyxl` para
  Excel; `anthropic` es opcional.
- **Determinismo del costo:** el costo de un APU se calcula llamando al precio
  vigente del insumo (`apu_tool/dominio/pricing.py`); el precio histórico embebido es solo respaldo.
- **Turno** DIURNO/NOCTURNO es parte de la clave de un APU y de su composición.

## Datos

- **Excel fuente:** `OBRA-Calle 13-LOTE SL5-...xlsx` (no se modifica; solo se lee).
  Pestañas clave: `APUS` (composición + turno), `listado_insumos_idu` (precios),
  `insumos_apus_especificos`, `listado_apus_idu_especiales`.
- **Bases locales:** `data/precios.db` (catálogo de precios e insumos) y
  `data/apus.db` (biblioteca de APUs y composiciones) — ambas SQLite, generadas con
  `seed`. El precio del insumo vive separado de su identidad: actualizarlo
  (`db update-price`) no toca los APUs, que toman el precio vigente al costear.
  El contrato de almacenamiento está en `datos/repositorio.py` (Protocol) para que un
  backend de nube sea un reemplazo limpio.
- **Listas de precios (tarifas).** El precio de un insumo es *por lista*: la lista
  `Principal` (id 1, `config.LISTA_PRINCIPAL_ID`, intocable — no se renombra ni se
  borra) es la del catálogo, y cada obra de No Previstos (NP) puede tener la suya
  (tabla `lista_precios`, columna `insumo_precios.lista_id NOT NULL DEFAULT 1`). Una
  corrida elige su lista **al crearse** (`corrida.lista_precios_id`, sin FK) y no la
  cambia — no existe ningún `set_lista`. Costeando contra una lista que no es
  Principal, un insumo sin tarifa **no** cae al precio histórico embebido: queda en
  $0 con alerta explícita (`calidad_cruce = sin_precio_lista`), porque usar el
  histórico sería cobrar el no previsto con la tarifa contractual sin que nadie se
  entere. Si el insumo existe pero le falta precio en el catálogo (Principal), se
  costea con el histórico pero con alerta (`sin_precio_catalogo`) — antes era un
  underbid silencioso. API: `GET/POST /api/listas-precios`, `PATCH
  /api/listas-precios/{id}` (sin DELETE, a propósito).
- **Salidas:** `salidas/` (cuadros) y `ejemplos/` (licitaciones de ejemplo).
- Fuentes de precio: `PRECIO IDU` se trata como **público**; el resto
  (`COSTO INTERNO`, `COMPRAS…`, etc.) como **interno/confidencial**
  (`config.PUBLIC_PRICE_SOURCES`).

## Pruebas

`tests/` cubre la frontera de privacidad, el matcher, la ingesta, el motor de
precios y el orquestador. Corre `pytest` antes de dar algo por terminado.

## No hacer

- No le pases dinero a la IA (invariante #1).
- No edites el Excel fuente ni borres `data/`, `salidas/`, `ejemplos/`.
- No dupliques lógica de orquestación: reúsala desde `pipeline.py`.
- No hagas que una lista que no sea Principal caiga al precio histórico ni al de
  Principal: el respaldo silencioso es justo lo que esta feature evita.
- No borres listas de precios: una corrida guarda su `lista_precios_id` sin FK, y
  `seed --force` ya las destruye sin poder recuperarlas del Excel (ver Comandos).
