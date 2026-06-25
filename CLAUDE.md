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
- Lo que la IA recibe son los tipos `DePriced*` de `models.py`, sin campos de precio.
- Solo `pricing.py` y `report.py` tocan dinero, y jamás se pasan a la IA.

Si agregas una llamada a la IA, construye el payload con helpers de `privacy.py` y
serialízalo con `privacy.safe_json(...)`. Si agregas un campo monetario nuevo,
añádelo a `_FORBIDDEN_KEYS` en `privacy.py`.

## Comandos

```bash
pip install -r requirements.txt

python run_cli.py demo      # semilla + ejemplo + cuadro resumen (todo)
python run_cli.py seed      # semillar las bases desde el Excel histórico
python run_cli.py seed --force  # re-semillar (borra datos mantenidos)
python run_cli.py build <licitacion.xlsx>
python run_cli.py status
python run_cli.py db price <codigo>     # precio vigente + historial de un insumo
python run_cli.py db update-price <codigo> <precio> [--fuente ...]
python run_gui.py           # interfaz tkinter

python -m pytest tests/ -q  # pruebas
```

La IA se activa solo si existe `ANTHROPIC_API_KEY`; sin ella se usa un fallback
determinístico y todo corre igual. Modelo por defecto: `claude-haiku-4-5-20251001`
(`apu_tool/config.py::AI_MODEL`).

## Arquitectura (flujo)

```
Excel histórico ──seed──► SQLite (data/precios.db + data/apus.db)
lista licitación ──► matching ──► IA acotada (sin dinero) ──► confirma usuario
                                       └─► motor de precios ──► cuadro resumen (Excel)
```

| Módulo | Responsabilidad |
|--------|-----------------|
| `config.py`     | rutas, umbrales de matching, modelo de IA, clasificación de precios |
| `models.py`     | tipos del dominio; vistas `DePriced*` SIN dinero |
| `db.py`         | acceso SQLite; **toda** la persistencia pasa por aquí |
| `ingest.py`     | Excel histórico → base |
| `licitacion.py` | lectura de la lista de entrada + generador de ejemplo |
| `matching.py`   | matcher determinístico (fuzzy, sin dependencias externas) |
| `privacy.py`    | frontera de precios para la IA (invariante #1) |
| `ai_assist.py`  | IA acotada (Anthropic SDK) + fallback determinístico |
| `pricing.py`    | motor de costos (ÚNICO que ve dinero) |
| `assemble.py`   | orquestador por ítem |
| `report.py`     | cuadro resumen en Excel |
| `pipeline.py`   | orquestación de alto nivel (la usan CLI y GUI) |
| `gui.py`/`cli.py` | interfaces |

## Convenciones

- **Persistencia aislada en `db.py`.** No metas SQL crudo en otros módulos. Esto
  permite migrar a Postgres/nube reemplazando una sola capa (plan: local primero,
  nube después).
- **Español** en nombres de dominio, comentarios y mensajes de usuario.
- **Sin dependencias pesadas:** el matcher usa stdlib (`difflib`); `openpyxl` para
  Excel; `anthropic` es opcional.
- **Determinismo del costo:** el costo de un APU se calcula llamando al precio
  vigente del insumo (`pricing.py`); el precio histórico embebido es solo respaldo.
- **Turno** DIURNO/NOCTURNO es parte de la clave de un APU y de su composición.

## Datos

- **Excel fuente:** `OBRA-Calle 13-LOTE SL5-...xlsx` (no se modifica; solo se lee).
  Pestañas clave: `APUS` (composición + turno), `listado_insumos_idu` (precios),
  `insumos_apus_especificos`, `listado_apus_idu_especiales`.
- **Bases locales:** `data/precios.db` (catálogo de precios e insumos) y
  `data/apus.db` (biblioteca de APUs y composiciones) — ambas SQLite, generadas con
  `seed`. El precio del insumo vive separado de su identidad: actualizarlo
  (`db update-price`) no toca los APUs, que toman el precio vigente al costear.
  El contrato de almacenamiento está en `repository.py` (Protocol) para que un
  backend de nube sea un reemplazo limpio.
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
