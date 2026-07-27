# Arquitectura objetivo — Armador de APUs

> Documento vivo. Es el **norte** del proyecto: a dónde va el sistema y en qué orden se
> construye. La arquitectura *actual* (módulos de hoy) está en [CLAUDE.md](../CLAUDE.md);
> este documento describe el **objetivo** y la hoja de ruta para llegar.
>
> Esquema visual: ver `docs/superpowers/arquitectura-esquema.html` (lámina A-01).

## Qué es

Herramienta para armar APUs (Análisis de Precios Unitarios) de obra civil y entregar un
**cuadro resumen** que compara **precio contractual** vs **costo interno**, reutilizando la
biblioteca histórica de APUs y el catálogo de precios de la empresa.

## Quién lo usa y cómo (madurez)

- **Usuarios:** el **equipo de la empresa** (analistas / presupuestadores). Arman sus
  licitaciones contra una **data central común**.
- **Entrada:** **app web** (navegador) como destino; **CLI** para operación y automatización.
- **Flujo de uso:** presupuesto por capítulos → cruce con la biblioteca de APUs (por código)
  → la IA decide la **estructura** del APU (nunca ve dinero) → costeo con el precio interno
  vigente → **cuadro contractual vs costo**, por capítulo.

## Las cuatro capas

Regla de oro: **el dominio no sabe dónde viven los datos ni quién lo llama.** Eso es lo que
abarata cada migración (local→nube, CLI→web).

| Nivel | Capa | Responsabilidad | Estado |
|------:|------|-----------------|--------|
| 01 | **Plataforma de datos** | Dos dominios canónicos y separados: **Precios** (catálogo + libro de precios) y **APUs** (biblioteca histórica). Fuente de verdad. SQLite hoy → Postgres/nube después. Acceso por repositorios + fachada `Almacen`. | existe hoy (SQLite + Postgres) |
| 02 | **Dominio / motor** | Lógica pura y reutilizable, sin UI ni red: lectura de entrada, matching, ensamblado, IA acotada, costeo, reporte, orquestación. Es una **librería con API clara**. | existe hoy |
| 03 | **Servicio / API** | Expone las operaciones del dominio por HTTP (FastAPI): mantener precios, mantener APUs, armar licitación, generar cuadro, chequeo de integridad. Auth ligera de equipo. | existe hoy (FastAPI, 44 endpoints) |
| 04 | **Interfaz** | App web sobre la API (destino); CLI/GUI para operación. | existe hoy (CLI, GUI y web) |

### Transversales (invariantes)
- **Invariante #1:** la IA **nunca** ve dinero; solo estructura (insumo, unidad, rendimiento).
  Ley del dominio, garantizada en `apu_tool/dominio/privacy.py`.
- **Precios confidenciales:** equipo de confianza por ahora (sin roles), pero el diseño no lo
  impide después.
- **Aislamiento de almacenamiento:** los repositorios son la costura que permite local→nube
  sin reescribir el dominio.

## Estructura de carpetas (objetivo)

Las carpetas **son** las capas: `datos/` no importa **lógica** de `dominio/` (matching,
pricing…), el `dominio/` no conoce la API. El **núcleo compartido** (`nucleo/`) son tipos de
datos puros (dataclasses) que todas las capas pueden importar — incluida `datos`, que devuelve
esos modelos. La estructura obliga las fronteras, no solo las sugiere. (Los nombres de archivo
se conservan; la convención de español aplica a los identificadores del dominio, no a los módulos.)

```
intento_plan/
├── apu_tool/
│   ├── config.py                  # transversal: rutas, umbrales, modelo IA
│   ├── nucleo/                    ── KERNEL COMPARTIDO
│   │   ├── models.py              #   dataclasses puras (Insumo, Apu, DePriced*)
│   │   ├── redondeo.py            #   redondeo a la unidad en multiplicaciones monetarias
│   │   └── texto.py               #   normalización de texto compartida
│   │
│   ├── datos/                     ── NIVEL 01 · plataforma de datos
│   │   ├── repositorio.py         #   Protocols de almacenamiento
│   │   ├── precios_db.py   apus_db.py   carpetas_db.py   corridas_db.py
│   │   ├── auditoria_db.py   perfiles_db.py
│   │   ├── almacen.py             #   fachada Almacen (agrupa SQLite/Postgres)
│   │   ├── seed.py   correcciones.py
│   │   ├── migracion_pg.py        #   migración SQLite → Postgres
│   │   └── pg/                    #   backend Postgres (espejo 1:1 de los *_db.py)
│   │
│   ├── dominio/                   ── NIVEL 02 · motor (lógica pura)
│   │   ├── licitacion.py   presupuesto.py   matching.py   cruce.py   compose.py
│   │   ├── privacy.py   ai_assist.py   assemble.py
│   │   ├── pricing.py   alertas.py   report.py   report_categorizado.py
│   │   ├── integridad.py          #   chequeo de integridad APU↔insumo
│   │   └── pipeline.py            #   orquestación (usa datos + dominio)
│   │
│   ├── servicio/                  ── NIVEL 03 · API (FastAPI) — 44 endpoints
│   │   ├── app.py   rutas.py   dependencias.py   esquemas.py
│   │   ├── auth.py   limites.py   seguridad_headers.py
│   │   └── corridas.py   insumos.py   autoria.py   subapus.py   apus.py
│   │       carpetas.py   usuarios.py   auditoria.py   supabase_admin.py   plantillas.py
│   │
│   └── interfaz/                  ── NIVEL 04 · interfaces
│       ├── cli.py   gui.py
│
├── db/                            # DDL canónico (SQL): precios, apus, corridas, seguridad
├── data/                          # bases mantenidas: precios.db, apus.db, corridas.db, seguridad.db
├── salidas/                       # cuadros generados
├── ejemplos/                      # licitaciones de ejemplo
├── tests/
├── web/                           # frontend React ya construido (Vite + TS + Supabase)
├── constructor-apus/              # vault de Obsidian auto-mantenida (ver su propio spec)
├── docs/                          # ARQUITECTURA.md + superpowers/{specs,plans}
├── run_cli.py   run_gui.py   run_web.py   requirements.txt
```

## Hoja de ruta

Los pasos 1 a 5 ya están construidos; el proyecto pasó de roadmap a mantenimiento y
features incrementales (ver `docs/superpowers/plans/` y `docs/superpowers/specs/` para
el historial de features desde entonces).

1. ✅ **Datos canónicos y separados** — reorganización completa a la estructura por capas.
2. ✅ **Dominio como librería con API clara.**
3. ✅ **Postgres** — `datos/pg/` implementa los repositorios contra Supabase; `datos/almacen.py`
   elige el backend. Migración con `datos/migracion_pg.py`.
4. ✅ **Capa de servicio / API (FastAPI)** — `servicio/`, 44 endpoints, auth Supabase + RBAC,
   rate limiting, headers de seguridad.
5. ✅ **App web** — `web/` (React + TypeScript + Vite), consume la API, servida por
   `servicio/app.py` desde `web/dist`.
6. **Endurecer multiusuario** — auth/RBAC y auditoría ya en producción; optimización de
   round-trips a Postgres ya hecha (ver `perf-corrida-optimizacion` en el historial de
   specs). Concurrencia y roles finos sobre precios se siguen evaluando caso a caso, sin
   un ítem de trabajo abierto puntual hoy.

*(La normalización de insumos —skill `apu-civil:apu-normalizar`— se usó para limpiar la
data canónica durante los pasos 1–3.)*
