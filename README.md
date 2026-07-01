# Armador de APUs — Obra Civil

Programa para **armar Análisis de Precios Unitarios (APUs)** a partir de una lista
de licitación, reutilizando el histórico de la empresa, y entregar un **cuadro
resumen** que compara el **precio contractual** contra el **precio de costo**.

> **Regla de oro:** la IA **nunca** ve precios, costos ni totales. Solo decide la
> *estructura* de los APUs (qué insumos y con qué rendimiento). Todo el cálculo de
> dinero vive en un motor determinístico aparte.

---

## Qué hace

1. **Ingesta** el Excel histórico a una base local (`data/apu.db`, SQLite):
   - catálogo de **insumos** con precio y fuente (público vs. costo interno),
   - catálogo de **APUs** con turno (DIURNO/NOCTURNO),
   - **composición** de cada APU (insumos + rendimientos).
2. Recibe una **lista de licitación** (Excel/CSV: ítem, descripción, unidad,
   cantidad, precio contractual, turno).
3. Para cada actividad:
   - **matching** determinístico contra el histórico (filtrado por turno);
   - los casos **dudosos o nuevos** los resuelve la **IA acotada** (propone el APU
     base, con justificación y confianza) para que tú **confirmes**;
   - el **motor de precios** costea la composición llamando a los precios vigentes
     de los insumos.
4. Entrega el **cuadro resumen** (Excel): por ítem y total, contractual vs. costo,
   margen y margen %, más hojas de **desglose** y **alertas**.

---

## Instalación

Requiere Python 3.10+ (en Windows trae `tkinter` incluido).

```bash
pip install -r requirements.txt
```

`anthropic` es **opcional**: sin `ANTHROPIC_API_KEY` el programa usa un fallback
determinístico y funciona igual (solo que la decisión de los dudosos es por
similaridad de nombre en vez de criterio de IA).

Para habilitar la IA:

```bash
set ANTHROPIC_API_KEY=tu-api-key      # Windows (cmd)
$env:ANTHROPIC_API_KEY="tu-api-key"   # Windows (PowerShell)
```

---

## Uso rápido

### Interfaz gráfica (recomendada)

```bash
python run_gui.py
```

1. **Cargar histórico** (botón 1) — ingesta el Excel de la carpeta.
2. **Generar ejemplo** o **Cargar lista…** (botón 2) — tu Excel/CSV de licitación.
3. **Armar APUs** (botón 3).
4. Doble clic en una fila marcada *Revisar*/*Manual* para **elegir el APU base**.
5. **Exportar cuadro…** a Excel.

### Línea de comandos

```bash
python run_cli.py demo          # semilla + ejemplo + cuadro resumen, todo de una
python run_cli.py seed          # semillar las bases desde el Excel histórico
python run_cli.py seed --force  # re-semillar (borra datos mantenidos)
python run_cli.py sample -n 20  # genera una licitación de ejemplo
python run_cli.py build ejemplos/licitacion_ejemplo.xlsx
python run_cli.py status        # estado de la base e IA

# Base de datos
python run_cli.py db price 6140                 # precio vigente + historial
python run_cli.py db update-price 6140 120000 --fuente "COMPRAS 2026"
```

> **Precios vivos:** el precio de cada insumo vive en su propia tabla (`insumo_precios`),
> separado de su identidad. Al actualizar un precio, los APUs que usan ese insumo toman
> el nuevo valor automáticamente al costear — sin reconstruir nada. Queda historial.

Las salidas quedan en `salidas/` y los ejemplos en `ejemplos/`.

---

## Formato de la lista de licitación

Un Excel o CSV con encabezados (el lector reconoce variantes de nombre):

| ITEM | DESCRIPCION | UNIDAD | CANTIDAD | PRECIO CONTRACTUAL | TURNO |
|------|-------------|--------|----------|--------------------|-------|
| 1 | EXCAVACION MANUAL PARA REDES | M3 | 120 | 64.878 | DIURNO |

- `TURNO` es opcional; si falta se usa el turno por defecto (Diurno, configurable).
- El lector tolera nombres de columna distintos (escalabilidad entre proyectos).

---

## La frontera de privacidad (cómo se garantiza)

- `apu_tool/privacy.py` construye **todos** los payloads que van a la IA y los pasa
  por `assert_no_money(...)`, que recorre la estructura y **lanza una excepción** si
  encuentra cualquier campo monetario. Preferimos *fallar* a *filtrar*.
- Las vistas que recibe la IA son los tipos `DePriced*` de `apu_tool/models.py`, que
  **por construcción** no tienen campos de precio.
- El motor de precios (`apu_tool/pricing.py`) y el reporte son los únicos que tocan
  dinero, y nunca se le pasan a la IA.

---

## Arquitectura

```
Excel histórico ──ingest──► SQLite (insumos, apus, componentes)
                                  │
lista licitación ──► matching ──► IA acotada (sin dinero) ──► confirma usuario
                                  │
                                  └─► motor de precios ──► cuadro resumen (Excel)
```

| Módulo | Responsabilidad |
|--------|-----------------|
| `config.py`    | rutas, umbrales, modelo de IA |
| `models.py`    | tipos del dominio; vistas `DePriced*` sin dinero |
| `db.py`        | acceso SQLite (aísla el almacenamiento) |
| `ingest.py`    | Excel histórico → base |
| `licitacion.py`| lectura de la lista de entrada + ejemplo |
| `matching.py`  | matcher determinístico (fuzzy, sin dependencias) |
| `privacy.py`   | frontera de precios para la IA |
| `ai_assist.py` | IA acotada + fallback determinístico |
| `pricing.py`   | motor de costos (único que ve dinero) |
| `assemble.py`  | orquestador por ítem |
| `report.py`    | cuadro resumen en Excel |
| `pipeline.py`  | orquestación de alto nivel (CLI + GUI) |
| `gui.py` / `cli.py` | interfaces |

---

## Escalabilidad y siguiente paso (nube)

- **Distintos proyectos / formatos:** el lector de licitación mapea columnas por
  palabras clave; la ingesta es defensiva ante layouts distintos.
- **Migración a la nube:** todo el acceso a datos está aislado en `db.py`. Cambiar
  SQLite por Postgres/servidor es reemplazar esa clase, sin tocar el resto.
- **Precios siempre vigentes:** el costo de un APU se calcula llamando al precio
  actual del insumo; el histórico embebido queda como respaldo.

---

## Pruebas

```bash
python -m pytest tests/ -q
```

Cubren la frontera de privacidad, el matcher, la ingesta, el motor de precios y el
orquestador.

---

## Desarrollo local (con login)

Desde los Planes 2a/2b la app exige login por Supabase. Para correrla en local:

1. `web/.env` con `VITE_SUPABASE_URL` y `VITE_SUPABASE_ANON_KEY` (ver `web/.env.example`).
   **Sin esto la SPA no monta** (supabase-js revienta al importar).
2. `.env` del backend con `SUPABASE_PROJECT_REF` (o `SUPABASE_URL`) y `APU_ADMIN_EMAILS=<tu-correo>`
   (ver `.env.example`). Sin `DATABASE_URL` usa SQLite local.
3. `python run_cli.py seed` — siembra el catálogo y crea las bases locales.
4. En dos terminales: `python run_web.py` (backend :8000) y, en `web/`, `npm run dev` (Vite :5173,
   proxya `/api` al backend). Abre http://localhost:5173.
5. Crea tu usuario en el panel de Supabase Auth (con un correo de `APU_ADMIN_EMAILS`) y entra: al
   primer login se te bootstrapea como Admin.

## Despliegue (Render + Docker)

- **Imagen:** `Dockerfile` multi-stage (Node compila `web/dist` → Python sirve todo con gunicorn).
  Las `VITE_SUPABASE_URL`/`VITE_SUPABASE_ANON_KEY` se pasan como **build-args** (se bakean en el bundle).
- **Render:** servicio web tipo Docker (ver `render.yaml`); `healthCheckPath: /api/health`; secretos
  (`DATABASE_URL`, `SUPABASE_SERVICE_ROLE_KEY`, `SUPABASE_PROJECT_REF`, `APU_ADMIN_EMAILS`,
  `ANTHROPIC_API_KEY`) por el dashboard; HTTPS automático.
- **Migración del catálogo (una vez, ops):** con `DATABASE_URL` de Supabase, correr
  `python run_cli.py migrate-pg` y verificar conteos (insumos/precios/APUs/componentes) SQLite vs
  Postgres. El esquema Postgres (`db/pg/*.sql` + auditoría) ya está aplicado.
- **Post-deploy:** en Supabase añadir `https://<app-url>/definir-clave` al allowlist de redirect URLs;
  crear el primer usuario Admin en Supabase Auth con un correo de `APU_ADMIN_EMAILS`.
