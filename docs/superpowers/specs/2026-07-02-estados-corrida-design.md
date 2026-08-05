# Diseño — Estados de corrida (activa / congelada)

> Fecha: 2026-07-02
> Estado: propuesto (pendiente de revisión del usuario)
> Antecede: `2026-07-02-alta-de-apus-design.md` (biblioteca de APUs, ya en `feat/alta-de-apus`).
> Rama de trabajo: `feat/estados-corrida` (parte del tip de `feat/alta-de-apus`; todo local, sin push).

## Objetivo

Hoy una corrida es un híbrido: la **composición** de cada ítem queda congelada (foto al
armar), pero los **precios** se recalculan siempre en vivo. No hay forma de que una corrida
siga los cambios de la biblioteca de APUs, ni de "cerrarla" como una cotización fija.

Este proyecto agrega un **modo** por corrida:

- **Activa** (por defecto): la corrida **sigue la biblioteca**. Al verla, cada ítem re-lee la
  composición actual de su APU asignado y se costea con precios vigentes. Es el borrador de trabajo.
- **Congelada**: la corrida es una **foto inmutable** (composición **y** precios fijos del
  momento en que se congeló). No cambia aunque después se editen APUs o suban precios. Es la
  cotización emitida.

El modo es **reversible** (Congelar / Activar).

## Decisiones de alcance

| Decisión | Elección |
|----------|----------|
| Qué congela | **Todo**: composición + precios (foto completa e inmutable). |
| Qué sigue la activa | Re-lee la **composición del APU asignado** a cada ítem + **precios vigentes**. |
| Match | **No** se re-hace el matching: se respeta qué APU quedó asignado/confirmado en cada ítem. |
| Estado inicial | Nace **activa**. |
| Reversibilidad | **Reversible**: Congelar / Activar cuando se quiera. |
| Generar cuadro | **Auto-congela** (el cuadro es lo que se envía → queda fijo). Reversible. |
| Congelada | **Solo lectura**: confirmar/editar ítems queda deshabilitado hasta activar. |
| Relación con el ciclo actual | `modo` es **ortogonal** a `estado` (`armando`/`en_revisión`/`finalizada`), que no cambia. |

**Fuera de alcance:** re-matching automático en modo activa; versionar/guardar múltiples fotos
por corrida (solo la última congelación); congelar/activar ítems individuales (el modo es de
toda la corrida); auth; nube.

## Arquitectura y estructura de archivos

El dominio (matcher, assembler, pricing, report) **no cambia**. La lógica de modo vive en el
servicio de corridas y en la capa de datos de corridas. **No toca la IA**: el snapshot con dinero
es un entregable interno (como el cuadro), nunca se pasa a la IA.

```
db/corridas.sql                    + corrida.modo, + corrida_item.snapshot_json
apu_tool/datos/corridas_db.py      migración idempotente en init_schema; set_modo;
                                     set_snapshot / get_snapshots; modo en get_corrida/listar
apu_tool/datos/repositorio.py      + set_modo, set_snapshot, get_snapshots en RepositorioCorridas
apu_tool/nucleo/models.py          CorridaMeta + campo `modo`
apu_tool/servicio/corridas.py      costeo según modo; congelar/activar; modo en vista/listar;
                                     generar_cuadro auto-congela; confirmar bloqueado si congelada
apu_tool/servicio/rutas.py         + POST /api/corridas/{id}/congelar y /activar;
                                     confirmar → 409 si la corrida está congelada
web/src/api/corridas.ts            + congelarCorrida, activarCorrida; `modo` en tipos
web/src/lib/tipos.ts               + `modo` en la vista y en la lista de corridas
web/src/pages/Corrida.tsx          badge Activa/Congelada + botones Congelar/Activar;
                                     acciones de revisión deshabilitadas si congelada
web/src/pages/MisCorridas.tsx      muestra el modo en la lista
```

## Comportamiento de costeo (el corazón)

En `apu_tool/servicio/corridas.py`, la función que hoy costea un ítem (`_costear_row`) se
reemplaza por una que decide según el `modo` de la corrida:

- **Activa** — por cada ítem:
  - Si tiene `apu_codigo`: se **re-lee** la composición actual del APU con
    `alm.apus.get_components(apu_codigo, shift)` y se costea con `PricingEngine` (precios vigentes).
    Así, cambiar un rendimiento o agregar/quitar un insumo del APU se refleja al abrir la corrida.
  - Si no tiene `apu_codigo` (status "nuevo"): se usa su composición guardada (`componentes_json`),
    como hoy (no hay APU de biblioteca que seguir).
  - Si el `apu_codigo` ya **no existe** en la biblioteca (fue borrado): se cae a `componentes_json`
    como respaldo; no revienta.
- **Congelada** — por cada ítem se usa el **snapshot congelado** (`snapshot_json`): composición +
  precios + costos **tal cual**, sin recalcular. Si un ítem no tuviera snapshot (caso improbable),
  se cae al comportamiento activa para ese ítem.

Los totales de la corrida (`vista_corrida`) se suman a partir de las filas costeadas según el modo.

## Congelar / Activar / Generar cuadro

- **`congelar(alm, corrida_id)`**: calcula la vista **activa** en ese instante (composición live +
  precios vigentes) y, por cada ítem, guarda su foto costeada en `snapshot_json`
  (`[{insumo_codigo, insumo_nombre, unidad, rendimiento, precio_unitario, fuente_precio, costo,
  calidad_cruce}]` + `costo_unitario`). Luego `set_modo('congelada')`. Idempotente (recongela = nueva foto).
- **`activar(alm, corrida_id)`**: `set_modo('activa')`. El snapshot queda guardado pero se ignora;
  la próxima congelación lo sobrescribe.
- **`generar_cuadro`** (ya existe): arma el Excel **y** llama a `congelar` (guarda snapshots +
  `modo='congelada'`). El cuadro se escribe desde la vista congelada resultante → coherente con lo enviado.
- **`confirmar_item`**: si la corrida está **congelada**, se rechaza (la corrida es solo lectura;
  hay que activarla primero). Si está activa, funciona como hoy.

## Datos / migración

- `corrida`: `+ modo TEXT NOT NULL DEFAULT 'activa'`.
- `corrida_item`: `+ snapshot_json TEXT` (nullable; foto costeada al congelar).
- **Migración idempotente** en `CorridasDB.init_schema()`: además de `CREATE TABLE IF NOT EXISTS`,
  revisa `PRAGMA table_info(...)` y hace `ALTER TABLE ... ADD COLUMN` si la columna falta. Así las
  bases existentes ganan las columnas **sin resetear** ni perder corridas.
- Corridas existentes quedan `modo='activa'` (empezarán a seguir la biblioteca; son de prueba, aceptable).
- **Privacidad (Invariante #1):** `snapshot_json` contiene dinero → es un dato interno del equipo
  (como el cuadro), **nunca** se pasa a la IA. `componentes_json` sigue money-free. El test que
  verifica que `apu_tool/servicio/` no referencia `ai_assist` sigue aplicando.

## API / UI

| Método + ruta | Hace |
|---|---|
| `POST /api/corridas/{id}/congelar` | congela; devuelve la vista de la corrida (modo=congelada) |
| `POST /api/corridas/{id}/activar` | activa; devuelve la vista (modo=activa) |
| `POST /api/corridas/{id}/items/{seq}/confirmar` | como hoy, pero `409` si la corrida está congelada |

`vista_corrida` y `listar_corridas` añaden `modo` a su respuesta.

**UI:**
- `Corrida.tsx`: **badge** "Activa" / "Congelada" junto a los totales; botones **Congelar** /
  **Activar** (según el modo). Si está congelada, las acciones de revisión/confirmación se
  muestran **deshabilitadas** con el aviso "Activa la corrida para modificar".
- `MisCorridas.tsx`: columna/etiqueta con el modo de cada corrida.

## Errores / casos límite

- APU asignado borrado (modo activa) → respaldo a `componentes_json`; sin error.
- Confirmar/editar con corrida congelada → `409` con mensaje claro.
- Congelar corrida sin ítems → no-op válido. Activar una ya activa (o congelar una ya congelada) → idempotente.
- `snapshot_json` ausente en un ítem de una corrida marcada congelada → ese ítem se costea como activa (degradación segura).

## Pruebas (pytest + TestClient)

- **Datos:** migración idempotente (correr `init_schema` dos veces y sobre una base "vieja" sin las
  columnas no falla y agrega las columnas); `modo` default `'activa'`; `set_snapshot`/`get_snapshots`.
- **Servicio:**
  - Activa re-lee composición: armar corrida → cambiar rendimiento de un APU en la biblioteca →
    `vista_corrida` refleja el nuevo costo.
  - Congelar fija todo: congelar → cambiar rendimiento del APU y/o precio del insumo →
    `vista_corrida` **no** cambia; activar → **sí** cambia.
  - `generar_cuadro` deja la corrida en `congelada` y con snapshots.
  - `confirmar_item` sobre corrida congelada → error (bloqueado).
- **API:** `POST congelar`/`activar` cambian el modo; `modo` presente en vista/lista; confirmar en
  congelada → 409.
- **Frontend:** vitest ligero para el render del badge/botones según modo (si aplica); smoke manual.
- `python -m pytest tests/ -q` verde, incluido el test de privacidad; la IA nunca ve dinero.

## Criterios de aceptación

1. Una corrida nueva nace **activa**; cambiar un rendimiento (o agregar/quitar un insumo) en un APU
   se refleja en la corrida activa al abrirla.
2. **Congelar** deja la corrida inmutable: cambios posteriores en APUs o precios no la alteran.
3. **Activar** la vuelve a hacer seguir la biblioteca.
4. **Generar el cuadro** congela la corrida automáticamente (reversible).
5. Estando **congelada**, no se puede confirmar/editar ítems (solo lectura) hasta activarla.
6. La migración no pierde corridas existentes; `pytest` pasa completo; la IA nunca recibe dinero.
