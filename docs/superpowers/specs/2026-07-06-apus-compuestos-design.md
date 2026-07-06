# Diseño — APUs compuestos (un APU usa otros APUs como insumos)

> Fecha: 2026-07-06
> Estado: aprobado por el usuario (pendiente de plan de implementación)
> Rama de trabajo: `feat/apus-compuestos` (parte del tip de `master`). Trabajo LOCAL; nada a prod sin OK explícito.
> Alcance de este spec: **Fase 1 — núcleo backend**. UI, etiqueta en el Excel y limpieza del catálogo son fases posteriores.

## Problema

Algunos APUs usan **otros APUs** como insumo (APUs compuestos / anidados). Hoy la biblioteca
guarda cada componente como un enlace blando a un código de insumo, y el motor de precios
(`pricing.cost_component`) resuelve ese código contra el catálogo de insumos (`cruce.resolver`).
Como los APUs fueron **aplanados** dentro del catálogo de insumos (hojas `insumos_apus_especificos`,
`listado_apus_idu_especiales` del seed), un APU compuesto termina costeando contra una **copia con
precio congelado** del sub-APU. Si el sub-APU cambia, hay que actualizar también su copia en insumos:
duplicación y desincronización.

### Evidencia (producción, Supabase `hfjljzhgignngzooiwvl`, 2026-07-06)

- 1.181 APUs (códigos distintos); 7.505 códigos de insumo.
- **1.078/1.181 (91%) de los códigos de APU existen también como código de insumo** (las copias aplanadas).
- **267** componentes (de 5.205) apuntan a un código que es un APU → son los sub-APUs de uso actual.
  **Los 267 son ambiguos** (su código existe como insumo *y* como APU).
- De esos 267: **215** existen en el turno del padre; **52** requieren fallback de turno.
- **75** códigos de sub-APU distintos; **8** de ellos son a su vez compuestos → **hay anidamiento (nivel ≥2)**.
- **0** ciclos directos (A↔B) hoy.

**Por qué se descarta inferir por búsqueda:** con 1.078 códigos que son a la vez insumo y APU,
adivinar por código costearía mal muchos materiales legítimos; y "insumos primero" nunca alcanzaría
el APU vivo (siempre encontraría antes la copia congelada). Se elige **marca explícita**.

## Objetivo (Fase 1)

Un componente de APU puede ser un **insumo** o un **sub-APU**. Cuando es sub-APU, su costo se calcula
**en vivo** desde la composición del sub-APU (una sola fuente de verdad): si el sub-APU cambia, todo
APU que lo use —y toda corrida activa— reflejan el cambio sin duplicar nada.

## Restricciones

- Persistencia aislada en la capa de datos (`db.py`/repos); SQL crudo solo ahí. Dual-backend (SQLite + Postgres).
- **Invariante #1 intacta:** la IA nunca ve dinero. El costeo recursivo vive solo en `pricing.py`.
- Cambios de esquema **aditivos e idempotentes** (`ADD COLUMN IF NOT EXISTS` / `PRAGMA table_info`), como `modo`/`snapshot_json`.
- Español en dominio/mensajes. Sin dependencias nuevas.
- Preservar comportamiento actual: un componente sin marcar es `tipo='insumo'` y se costea igual que hoy.

## Diseño

### 1. Modelo y esquema

`ApuComponent` (en `apu_tool/nucleo/models.py`) gana dos campos con default (compatibles hacia atrás):

```python
tipo: str = "insumo"     # "insumo" | "apu"
ref_shift: str = ""      # turno del sub-APU cuando tipo == "apu"
```

Cuando `tipo == "apu"`: `insumo_codigo` = código del sub-APU, `insumo_nombre` = nombre del sub-APU
(display/respaldo), `ref_shift` = su turno, `rendimiento` = cantidad del sub-APU, `precio_unitario_hist`
= costo histórico embebido (respaldo si el sub-APU no resuelve o hay ciclo).

Esquema `apu_componentes` (SQLite `db/apus.sql` y Postgres `db/pg/apus.sql`):

```sql
tipo       TEXT NOT NULL DEFAULT 'insumo',
ref_shift  TEXT
```

Migración de esquema: SQLite en `init_schema` vía `PRAGMA table_info` + `ALTER TABLE ADD COLUMN`;
Postgres vía `ALTER TABLE apus.apu_componentes ADD COLUMN IF NOT EXISTS ...` en el script de arranque.
Los repos (`apus_db.py`, `apus_pg.py`) leen/escriben `tipo` y `ref_shift` en `insert_components`,
`get_components`, `crear_apu` y `editar_apu` (y en cualquier `_row_to_component`).

### 2. Motor de precios — costeo recursivo (`pricing.py`)

`cost_component` decide por `tipo`:

- `tipo == "insumo"` (o vacío): comportamiento actual (cruce contra catálogo; si no, `precio_unitario_hist`).
- `tipo == "apu"`: costea el sub-APU en vivo:
  - `sub_shift = comp.ref_shift or comp.shift` (hereda el turno del padre si falta).
  - `sub_unit = _costo_unitario_apu(comp.insumo_codigo, sub_shift, visitando)` (suma recursiva de la composición del sub-APU).
  - `costo = comp.rendimiento * sub_unit`; `fuente_precio = "APU"`; `calidad_cruce = "apu"`.

Reglas de recursión:

- **Guarda de ciclos:** un conjunto `visitando` de `(codigo, shift)` en la pila. Si el sub-APU ya está en
  la pila → **ciclo**: no se recursa; `costo = comp.rendimiento * comp.precio_unitario_hist`,
  `calidad_cruce = "ciclo"` (respaldo histórico, nunca cuelga).
- **Memoización por pasada:** cache `(codigo, shift) -> costo_unitario` dentro del `PricingEngine` para no
  recomputar un sub-APU repetido.
- **Sub-APU inexistente** (código sin composición en ese turno): respaldo `precio_unitario_hist`,
  `calidad_cruce = "huerfano"`.

`CostedComponent.calidad_cruce` admite ahora también `"apu"` y `"ciclo"` además de
`exacto|aproximado|ambiguo|huerfano`. Sigue siendo el único módulo que toca dinero.

### 3. Migración de datos — marcar los sub-APUs existentes (auto-marcado + auditoría)

Función de servicio idempotente `marcar_subapus(alm, actor=None) -> dict` (en `apu_tool/servicio/`),
expuesta como comando de CLI (`python run_cli.py marcar-subapus`) para correrla de forma controlada
contra el backend activo (incluida prod vía `DATABASE_URL`). NO corre automáticamente al bootear.

Regla: por cada componente con `tipo='insumo'` cuyo `insumo_codigo` sea un código de APU existente,
lo marca `tipo='apu'` y fija `ref_shift`:
1. el turno del APU padre si `(insumo_codigo, turno_padre)` existe en `apus` (215 casos);
2. si no, `DIURNO` si `(insumo_codigo, 'DIURNO')` existe;
3. si no, el único turno en que ese código exista.

Escribe auditoría por APU padre afectado: `accion="apu.componente.marcar_subapu"`, `entidad_tipo="apu"`,
`entidad_id=<codigo padre>`, `contexto={shift, componentes:[{seq, ref_codigo, ref_shift}]}`.
Es **idempotente**: solo toca filas `tipo='insumo'` que casan con un código de APU; re-ejecutarla no marca nada nuevo
y no vuelve a auditar (no hay filas por cambiar). Devuelve `{apus_afectados, componentes_marcados}`.

### 4. Frontera con la IA

`DePricedComponent` gana `tipo: str = "insumo"` (solo estructura; sin dinero) para que la IA sepa que
una línea es un sub-APU. `get_depriced_apu` copia el `tipo` del componente. `privacy.assert_no_money`
no cambia y sigue pasando (no se agregó ningún campo monetario). `ref_shift` es estructura, no dinero.

### 5. Corridas (activa/congelada)

- **Activa:** `_costear_row` re-lee `alm.apus.get_components(apu, shift)` (que ahora traen `tipo`/`ref_shift`)
  y costea con recursión → los compuestos se recostean solos. Sin cambios de flujo.
- **Congelada:** conserva su `snapshot_json` (composición ya costeada); intacto.
- **Respaldo (APU borrado):** `_estructura(componentes)` incluye ahora `tipo` y `ref_shift`, y el respaldo de
  `_costear_row` (que arma `ApuComponent` desde `row.componentes`) los propaga, para que ese camino también
  costee sub-APUs correctamente. (Sin dinero: `_estructura` sigue sin campos monetarios.)

## Pruebas (pytest)

- **Precios (recursión):** APU A con un componente `tipo='apu'`→B (insumos) → costo de A = rend × costo(B).
  Anidamiento A→B→C (dos niveles). Ciclo A→B→A → A cae a `precio_unitario_hist`, `calidad_cruce='ciclo'`,
  sin recursión infinita. Sub-APU referenciado dos veces → costeo consistente (memoización).
- **Repos (round-trip):** `insert_components`/`get_components` y `crear_apu`/`editar_apu` conservan `tipo` y
  `ref_shift` en SQLite (y, si hay `TEST_DATABASE_URL`, en Postgres).
- **Migración:** con componentes cuyo código casa con un APU, `marcar_subapus` marca `tipo='apu'` con el
  `ref_shift` correcto (turno padre / DIURNO / único), escribe auditoría, y es **idempotente** (2ª corrida =
  0 cambios). Un componente cuyo código NO es APU queda `tipo='insumo'`.
- **Privacidad:** `get_depriced_apu` de un APU compuesto pasa `assert_no_money` y expone `tipo`.
- **Verificación:** `python -m pytest tests/ -q` verde.

## Criterios de aceptación

1. Un APU con un componente `tipo='apu'` se costea desde la composición **vigente** del sub-APU; actualizar el
   sub-APU cambia el costo del padre (y de las corridas activas) sin tocar el catálogo de insumos.
2. La recursión soporta anidamiento (≥2 niveles), memoiza, y una referencia cíclica cae a respaldo histórico
   con `calidad_cruce='ciclo'` (nunca cuelga).
3. `marcar-subapus` marca los 267 componentes con el turno correcto, deja auditoría y es idempotente.
4. Un componente sin marcar (`tipo='insumo'`) se costea exactamente como hoy (sin regresión).
5. Invariante #1 intacta (la IA solo ve estructura, incluido `tipo`; nunca el costo del sub-APU).
6. Cambios de esquema aditivos e idempotentes en ambos backends; `pytest` verde.

## Fuera de alcance (fases posteriores)

- UI del editor de APUs para elegir insumo vs sub-APU (BuscadorInsumo / BuscadorApu) y mostrar líneas de
  sub-APU distinguidas en la corrida (badge "APU", drill-in a su composición).
- Etiqueta de sub-APU en el Excel del cuadro (`report.py`).
- Limpieza del catálogo de insumos (quitar las ~1.078 copias aplanadas de APUs).
