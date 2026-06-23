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
| 01 | **Plataforma de datos** | Dos dominios canónicos y separados: **Precios** (catálogo + libro de precios) y **APUs** (biblioteca histórica). Fuente de verdad. SQLite hoy → Postgres/nube después. Acceso por repositorios + fachada `Almacen`. | base |
| 02 | **Dominio / motor** | Lógica pura y reutilizable, sin UI ni red: lectura de entrada, matching, ensamblado, IA acotada, costeo, reporte, orquestación. Es una **librería con API clara**. | existe hoy |
| 03 | **Servicio / API** | Expone las operaciones del dominio por HTTP (FastAPI): mantener precios, mantener APUs, armar licitación, generar cuadro, chequeo de integridad. Auth ligera de equipo. | futuro |
| 04 | **Interfaz** | App web sobre la API (destino); CLI/GUI para operación. | CLI/GUI hoy, web futuro |

### Transversales (invariantes)
- **Invariante #1:** la IA **nunca** ve dinero; solo estructura (insumo, unidad, rendimiento).
  Ley del dominio, garantizada en `privacy.py`.
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
│   │   └── models.py              #   dataclasses puras (Insumo, Apu, DePriced*); lo importan todas las capas
│   │
│   ├── datos/                     ── NIVEL 01 · plataforma de datos
│   │   ├── repositorio.py         #   Protocols: RepositorioPrecios, RepositorioApus
│   │   ├── precios_db.py          #   PreciosDB  → data/precios.db
│   │   ├── apus_db.py             #   ApusDB     → data/apus.db
│   │   ├── almacen.py             #   fachada Almacen(.precios, .apus)
│   │   ├── seed.py                #   importación semilla desde Excel (guardada)
│   │   ├── correcciones.py        #   mapeo de códigos (4613 → 3017)
│   │   └── integridad.py          #   chequeo de huérfanos / descalces
│   │
│   ├── dominio/                   ── NIVEL 02 · motor (lógica pura)
│   │   ├── models.py   licitacion.py   presupuesto.py   matching.py
│   │   ├── privacy.py  ai_assist.py    compose.py       assemble.py
│   │   ├── pricing.py  report.py       report_categorizado.py
│   │   └── pipeline.py             #   orquestación (usa datos + dominio)
│   │
│   ├── servicio/                  ── NIVEL 03 · API (FastAPI)        [se llena en paso 4]
│   └── interfaz/                  ── NIVEL 04 · interfaces
│       ├── cli.py   gui.py
│
├── db/                            # DDL canónico (SQL): precios.sql, apus.sql
├── data/                          # bases mantenidas (fuente de verdad): precios.db, apus.db
├── salidas/                       # cuadros generados
├── ejemplos/                      # licitaciones de ejemplo
├── tests/
├── web/                           # frontend de la app web           [se llena en paso 5]
├── docs/                          # ARQUITECTURA.md + superpowers/{specs,plans}
├── run_cli.py   run_gui.py   requirements.txt
```

## Hoja de ruta

1. **Datos canónicos y separados** — `precios.db` + `apus.db` como fuente de verdad, seed
   guardado, limpieza del código 4613, chequeo de integridad. **Incluye la reorganización
   completa del proyecto a la estructura por capas de arriba.** ← *paso actual*
2. **Consolidar el dominio como librería con API clara** — fronteras limpias para que una API
   pueda llamar al motor sin pasar por CLI/GUI.
3. **Migrar almacenamiento a Postgres** — implementar los repositorios contra Postgres; el
   dominio no cambia. Nube.
4. **Capa de servicio / API (FastAPI)** — exponer operaciones, auth de equipo, concurrencia.
5. **App web** sobre la API.
6. **Endurecer multiusuario** — concurrencia, auditoría y, si hace falta, roles sobre precios.

*(La normalización de insumos —skill `apu-civil:apu-normalizar`— se intercala en el paso 1–2
para limpiar la data canónica.)*
