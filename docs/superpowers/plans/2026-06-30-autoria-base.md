# Plan — Autoría de la base (agregar insumos y APUs)

> Spec: docs/superpowers/specs/2026-06-30-autoria-base-design.md
> Rama: feat/autoria-base · Base: master (417fd7d, tag pre-obras-especiales)
> Ejecución: TDD inline (como etapa 2), commit por tarea, suite verde tras cada una.
> Mandato: aditivo; no tocar matching/costeo/corridas/seed; Invariante #1; UI densa.

## Tarea 1 — Capa de datos: creación + listado de APUs
**Archivos:** `apu_tool/datos/precios_db.py`, `apu_tool/datos/apus_db.py`,
`apu_tool/datos/repositorio.py`; tests `tests/test_precios_db.py`, `tests/test_apus_db.py`.
- `PreciosDB.crear_insumo(insumo: Insumo) -> int`: si `(codigo, nombre_norm)` existe →
  `ValueError`; si no, INSERT insumo + precio vigente; devuelve id.
- `ApusDB.crear_apu(apu: Apu, componentes: list[ApuComponent]) -> None`: si `(codigo,
  shift)` existe → `ValueError`; si no, INSERT apu (sin REPLACE) + componentes (seq correlativo).
- `ApusDB.list_apus(q=None, grupo=None, shift=None, limit=100, offset=0) -> (list[Apu], int)`.
- Protocol: agregar las firmas en `RepositorioPrecios` / `RepositorioApus`.
- Tests: crear (ok + duplicado→ValueError + mismo código otro nombre ok); list_apus (filtros/paginación).

## Tarea 2 — Servicio `apu_tool/servicio/autoria.py` (nuevo)
**Archivos:** crear `apu_tool/servicio/autoria.py`; test `tests/test_servicio_autoria.py`.
- `crear_insumo(alm, datos) -> dict` / `crear_apu(alm, datos) -> dict` con validación
  (campos requeridos, precio≥0, turno válido, rendimiento>0).
- `preview_importar_insumos(alm, contenido, nombre)` → {crear, ya_existe, invalida};
  `aplicar_importar_insumos(alm, filas)`.
- `preview_importar_apus(alm, contenido, nombre)` (reusa `seed._read_apus`, marca
  `(codigo,turno)` existentes; sin `correcciones`); `aplicar_importar_apus(...)`.
- Invariante #1: el archivo NO contiene "ai_assist".

## Tarea 3 — API + esquemas
**Archivos:** `apu_tool/servicio/esquemas.py`, `apu_tool/servicio/rutas.py`; test `tests/test_api_autoria.py`.
- Esquemas: `InsumoNuevoIn`, `ComponenteIn`, `ApuNuevoIn`.
- Endpoints: `POST /insumos/crear`, `POST /insumos/importar-crear/preview`+`/importar-crear`,
  `GET /apus`, `GET /apus/{codigo}/{shift}`, `POST /apus/crear`,
  `POST /apus/importar/preview`+`/importar`. 400 en ValueError.
- Tests TestClient: cada endpoint, duplicado→400, Excel malo→400.

## Tarea 4 — Frontend
**Archivos:** `web/src/lib/tipos.ts`, `web/src/api/*`, `web/src/pages/Insumos.tsx`,
nueva `web/src/pages/Apus.tsx`, `web/src/App.tsx`, `web/src/components/Layout.tsx` (nav).
- Insumos: "Agregar insumo" (form) + "Importar para crear" (preview crear/ya_existe/invalida).
- Página APUs: tabla (código/turno/nombre/unidad/grupo/nº comp) + buscar + "Agregar APU"
  (form con sub-tabla de composición: buscar insumo + rendimiento) + "Importar APUs".
- Nav + ruta `/apus`. Vitest ligero (validación form) + `npm run build` 0 TS.

## Estado
- [ ] Tarea 1
- [ ] Tarea 2
- [ ] Tarea 3
- [ ] Tarea 4
