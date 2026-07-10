# Auditoría de código — Armador de APUs (2026-07-08)

Auditoría adversarial de **solo lectura** sobre `master` (`ba8f752`), después de las features
nuevas desde la auditoría anterior (sub-APUs, estados de corrida activa/congelada, filtros/orden,
totales en la lista, reasignar APU, editar/borrar APUs, import unificado). Seis auditores
independientes, una dimensión cada uno: **seguridad web/RBAC**, **frontera de privacidad de la IA**,
**capa de datos/SQL/paridad de backends**, **costeo/lógica de dominio**, **config/despliegue**,
**frontend**. Severidad = **impacto real de negocio o de datos**, no estilo. Los hallazgos de mayor
severidad se verificaron leyendo el código fuente directamente.

## Veredicto

- **Sin fugas de dinero a la IA** (Invariante #1 se sostiene), **sin inyección SQL**, **sin XSS**,
  **sin secretos commiteados** (ni service-role, ni `.db`, ni `.env`; el front solo recibe la anon key),
  **JWT sólido** (algoritmos asimétricos fijos, `exp/aud/iss` obligatorios, JWKS), RBAC desde la BD
  (nunca desde `user_metadata`), congelada **enforced en backend**. Las 7 correcciones previas siguen
  aplicadas salvo el XFF (ver abajo).
- **El riesgo dominante NO es de seguridad, es de negocio: el cuadro entregable puede subvaluar el
  costo en silencio** (costeo en $0) → sobrestima el margen → **riesgo de licitar por debajo del costo**.
  Y la edición de precios en lote puede **corromper la base de precios** sin avisar.

---

## Estado de las correcciones previas (regresiones)

| Prev | Estado hoy |
|------|-----------|
| C1/C2 (CLI status/check en Postgres) | No re-verificado en detalle (fuera del foco web/prod). |
| C3 (perfiles antes de RLS) | **CORREGIDO** — `0002_seguridad.sql` crea `perfiles`+`auditoria`, `0003_rls.sql` va después. |
| I1 (TOCTOU último admin) | **PARCIAL** — caso secuencial/mismo-registro cerrado (UPDATE condicional atómico + rowcount); queda una carrera concurrente en Postgres (ver IM-3). |
| I2 (bootstrap sin auditar) | **CORREGIDO** — `auth.py:85-90` en `transaccion("seguridad")` + `registrar_auditoria`. |
| I3 (descarga 401 por window.open) | **CORREGIDO** — `client.ts:66-85`/`corridas.ts:61-81` usan fetch+Bearer+Blob. |
| I4 (visor auditoría filas no contiguas) | **CORREGIDO** — `Auditoria.tsx:62-80` agrupa por `lote_id` en un `Map`. |
| I5 (LIKE vs ILIKE) | **CORREGIDO en precios** (usa `nombre_norm`); **sigue en búsqueda de APUs** (ver MENOR). |
| I6 (migrate-pg no idempotente) | **CORREGIDO** — `ON CONFLICT DO NOTHING` + resync de identidad; `reset` en una tx. |
| I7 (OOM por chunked) | **CORREGIDO** — `limites.py:29-34` exige `Content-Length` (411) en POST/PUT/PATCH a `/api`. |
| I8 (spoofing XFF) | **NO CORREGIDO en código** — solo se documentó; sigue `--forwarded-allow-ips="*"` (ver IM-4). |
| M1 (/docs público) | **CORREGIDO en prod** vía `render.yaml` (`APU_DOCS_ENABLED=false`); default del código sigue `true` (MENOR). |
| M2 (limiter ×workers) | **MITIGADO** vía `WEB_CONCURRENCY=1` en `render.yaml` (Dockerfile aún default 2). |

---

## CRÍTICO — el cuadro entregable o la base de precios se corrompen en silencio

### CR-1 — Costeo silencioso en $0 por cruce ambiguo/huérfano o precio vigente faltante
`apu_tool/dominio/pricing.py:85-88` (y el respaldo de corrida `apu_tool/servicio/corridas.py:124-132`,
línea 129 con `precio_unitario_hist=0.0`).
`cost_component` solo usa el precio del catálogo si `r.insumo is not None and r.insumo.precio > 0`;
si no, cae a `comp.precio_unitario_hist` **sin piso ni aviso**, y el camino de respaldo de la corrida
fuerza `precio_unitario_hist=0.0`. Un insumo con cruce **AMBIGUO/HUÉRFANO** (o sin precio vigente)
cuesta exactamente **$0**.
**Escenario:** ítem "generado" o APU ausente en la biblioteca al `shift` del ítem → cae al respaldo →
un insumo (p. ej. código IDU `4513` "DUCTO…" vs "BASE GRANULAR CLASE C", nombre que no matchea) →
`insumo=None` → `precio=0` → `costo = rendimiento·0 = 0`. Una línea que debía costar ~66.605 COP se
reporta en **$0**, deflactando `costo_unitario`, inflando `margen_total`/`margen %` en el RESUMEN
entregado. `calidad_cruce="ambiguo"/"huerfano"` solo aparece en la hoja DESGLOSE; **el RESUMEN (lo que
se entrega) no muestra ninguna bandera**. Es el issue conocido de TRANSPORTE ($0, código 3017);
estructuralmente sigue abierto.

### CR-2 — Un sub-APU con composición vacía/inexistente cuesta $0 sin respaldo histórico
`apu_tool/dominio/pricing.py:96-122` (`_cost_subapu` → `_costo_unitario_apu`).
Para un componente `tipo="apu"`, el costo = suma de `components(codigo, sub_shift)`. Si esa composición
está **vacía** (sub-APU borrado, o `ref_shift` apunta a un turno sin filas), la suma es `0.0`, se
**memoiza** y se devuelve. A diferencia del insumo y del borde de ciclo, **no hay caída a
`precio_unitario_hist`** ni chequeo de composición vacía.
**Escenario:** APU padre `A` (NOCTURNO) con sub-APU `B` (`ref_shift="NOCTURNO"`, `rendimiento=3`,
`precio_unitario_hist=999`); `B` solo existe en DIURNO. `components("B","NOCTURNO")` → `[]` → costo
unitario del sub-APU = `0` → componente `costo = 3·0 = 0`, con `fuente_precio="APU"` y
`calidad_cruce="apu"` (aspecto normal). El respaldo 999 se ignora. El costo del padre se subvalúa por
el valor completo del sub-APU, en silencio. **Ningún test cubre el sub-APU vacío/faltante.**

### CR-3 — La edición de insumos en lote corrompe el campo no editado al paginar/filtrar
`web/src/lib/useDirtyRows.ts:42-52` + `web/src/components/insumos/TablaInsumos.tsx:23-25` +
`web/src/pages/Insumos.tsx:112` + backend `apu_tool/servicio/insumos.py:46-50`.
`cambios()` reconstruye cada cambio pendiente con `filas.find(f => f.id === id)` y cae a
`fila?.precio ?? 0` / `fila?.fuente ?? ""` para el campo que **no** se editó. `TablaInsumos` **persiste
montado** entre páginas/filtros (Insumos re-fetchea `insumos` en la misma instancia; no hay `key` que
cambie, ni se limpia `dirty`), y la barra "N cambios sin guardar" sigue visible. Cuando la fila editada
sale de la página actual, `fila` es `undefined` y dispara el fallback.
**Escenario:** editar solo el **precio** en la página 1 → "Sig.›" → **Guardar** → se envía el precio
correcto pero `fuente: ""`. El backend (`aplicar_cambios`) **acepta** `precio=0` (solo rechaza
negativos) y `fuente=""`, y escribe una fila de historial vigente. Resultado:
- `fuente=""` → la clasificación cae a **interno/confidencial** (cadena vacía no está en
  `PUBLIC_PRICE_SOURCES`): un precio público se vuelve confidencial (o al revés) sin avisar.
- Caso simétrico (editar solo la fuente, paginar, guardar) → se envía `precio: 0` → **precio vigente
  $0** para el insumo → alimenta el motor de costos → CR-1. 
Es el flujo natural de "edito precios en varias páginas y guardo todo al final". Pérdida de dato
silenciosa que además envenena la base que sostiene todo el costeo.

---

## IMPORTANTE

### IM-1 — Ítems/sub-APUs nocturnos costeados a tarifa DIURNA en silencio (sin recargo nocturno)
`apu_tool/dominio/assemble.py:161-168`; `apu_tool/servicio/subapus.py` (`_ref_shift`); fallback del
matcher `matching.py:108-112`. Cuando falta el `(codigo, shift)` exacto, `_build` toma **cualquier**
APU con el mismo código en otro turno y hace `shift = alt.shift`, luego costea a ese turno; y
`_ref_shift` resuelve una referencia de sub-APU a DIURNO si el turno del padre no existe. El turno es
parte de la identidad del APU. **Escenario:** ítem NOCTURNO que matchea un APU que solo existe en
DIURNO → se costea a DIURNO, sin el recargo nocturno (típico +25–35% en obra civil): una actividad de
130.000 COP/nocturna se reporta a 100.000 COP, ~30% subvaluada, sin aviso. Es la clase del "remapeo de
mano de obra nocturna (48 comps)" pendiente en la memoria del proyecto: el código degrada a diurno en
vez de señalar.

### IM-2 — Una corrida "congelada" re-costea EN VIVO si le falta el snapshot de un ítem
`apu_tool/servicio/corridas.py:172-176` (`_ensamblar_corrida`, usado por `vista_corrida` y
`listar_corridas`). En modo congelada usa el snapshot solo `if r.seq in snaps`; si no, llama
`_costear_row(...)` (precio vigente actual). Un total "congelado" no está garantizado inmutable.
**Escenario:** corrida `modo="congelada"` con `snapshot_json IS NULL` en algún `seq` (freeze parcial o
fila reparada fuera del loop de `congelar`) → un `db update-price` posterior se cuela en el total de esa
corrida "inmutable"; el cuadro mostrado y la lista discrepan del Excel emitido. `generar_cuadro:326-328`
sí guarda contra esto (re-congela); los caminos de lectura no. Debería fallar ruidoso o negarse, no
costear en vivo.

### IM-3 — Carrera del "último admin" en Postgres (READ COMMITTED) → posible lockout total
`apu_tool/datos/pg/perfiles_pg.py:71-86` (guard `_GUARD`, `set_rol_protegido`, `set_estado_protegido`).
*(Detectado de forma independiente por el auditor de datos y el de seguridad — señal fuerte.)*
El guard es un `UPDATE ... WHERE NOT(rol='admin' AND estado='activo' AND (SELECT COUNT(*)…)<=1)`. Bajo
READ COMMITTED, dos transacciones concurrentes que degraden/desactiven **dos admins distintos** ven
ambas `count=2` (ninguna ve el commit de la otra) → ambas pasan → **cero admins activos** → sistema
bloqueado (todo `/usuarios/*` exige admin; recuperación solo por BD/ops). SQLite serializa escritores y
no sufre esto (divergencia de semántica de transacción). Probabilidad baja, consecuencia alta.
**Fix:** `SELECT … FOR UPDATE` del conjunto admin dentro de la tx, o `SERIALIZABLE`.

### IM-4 — Spoofing de X-Forwarded-For evade el rate-limit (prior I8, NO corregido en código)
`Dockerfile:34` (`--forwarded-allow-ips="*"`) + `apu_tool/servicio/limites.py:17` (`get_remote_address`).
Con `"*"`, uvicorn (`proxy_headers.py`) confía el XFF de cualquier peer y toma la entrada **más a la
izquierda** (controlable por el cliente). **Escenario:** `X-Forwarded-For: <ip-rotativa>` por request →
cada request estrena bucket de slowapi → se evaden el `200/minute` global y el `3/minute` de invitación
→ amplificación de DoS contra un único worker free-tier + envenenamiento de la IP en auditoría. HOY
mitigado solo porque el edge de Render es el único ingreso (asunción de topología no garantizada en
código). La "corrección" previa fue un comentario. **Fix:** fijar el CIDR del proxy de Render.

### IM-5 — Las migraciones de Supabase están desalineadas del esquema vivo
`supabase/migrations/0001_esquema_inicial.sql`: crea `apus.apu_componentes` **sin** `tipo`/`ref_shift`,
`corridas.corrida` **sin** `modo`, y `corridas.corrida_item` **sin** `snapshot_json`. Ninguna migración
posterior las añade. Esas columnas solo existen porque `db/pg/*.sql` traen `ADD COLUMN IF NOT EXISTS`
que corre `init_schema()` en cada arranque. Producción se auto-cura al bootear, **pero quien provisione
una base nueva por el camino canónico `supabase/migrations/` (o lo lea como fuente de verdad) obtiene un
esquema sin 4 columnas** hasta el primer arranque con un rol con permisos DDL. DR/reproducibilidad rota.
**Fix:** reconciliar las migraciones numeradas con `db/pg/*.sql`.

### IM-6 — Cualquier fallo de `getYo()` cierra la sesión de un usuario válido
`web/src/lib/auth.tsx:30-43`. El `catch` alrededor de `getYo()` marca `noAutorizado=true` y hace
`signOut()` incondicionalmente; `getYo` lanza igual en 403 que en 500 o error de red, y corre en cada
evento de `onAuthStateChange` (incluido el `TOKEN_REFRESHED` de fondo). **Escenario:** un blip 5xx o de
red durante el refresh horario de token expulsa a un usuario válido con "Tu cuenta no está autorizada".
Falla cerrado (seguro) pero es hostil y engañoso. **Fix:** tratar como no-autorizado solo el 403 real;
conservar la sesión en red/5xx.

### IM-7 — Endurecimiento de despliegue: contenedor como root + dependencias Python sin fijar
- **Root:** `Dockerfile` (etapa backend) nunca hace `USER`; gunicorn/uvicorn corre como UID 0 → un bug
  de ejecución (p. ej. vía la ruta de subida openpyxl o una dependencia) da root en el contenedor.
- **Deps flotantes:** `requirements.txt` usa `>=` en todo y el build hace `pip install` fresco en cada
  deploy con `autoDeploy: true` → builds no reproducibles; un release nuevo (o comprometido) upstream
  entra a producción sin revisión. (El front sí usa `npm ci` contra lockfile.) **Fix:** `USER` no-root
  + fijar versiones (`==`) o constraints con hashes.

---

## MENOR

**Privacidad (backstop, no fuga activa):**
- `apu_tool/dominio/privacy.py:21-26` — `_FORBIDDEN_KEYS` no cubre `margen_unitario`, `margen_total`,
  `margen_pct`, `contractual_total` (existen y se usan en `_vista_item`); el match es exacto, no por
  subcadena, así que `"margen"` no las cubre. Ningún builder actual las manda a la IA (backstop, no
  fuga), pero contradice la regla de CLAUDE.md de registrar todo campo monetario nuevo.
- `privacy.py:69-82` — `walk` solo recorre dict/list/tuple; dataclasses/`__dict__`/namedtuples no se
  inspeccionan (hoy "falla cerrado" por accidente al reventar `json.dumps`).
- `privacy.py:29` — `_ALLOWED_NUMERIC_KEYS` definido y nunca usado (código muerto; delata que se
  pensó una allowlist que nunca se implementó — la raíz de que el backstop sea permisivo).

**Costeo/reporte:**
- `report.py:92-110` / `report_categorizado.py:43-57` — filas y total redondean por separado (formato
  `#,##0`) → el cuadro puede mostrar un descuadre de 1 peso. Redondear a peso entero al calcular.
- `nucleo/models.py:200-202` / `corridas.py:185` — `margen_pct = margen/contractual if contractual
  else 0.0`: con `contractual=0` muestra 0.0% aunque `margen_unitario = -costo` sea pérdida total.
- `pricing.py:24-29,115-122` — el supuesto acíclico se asume, no se aplica; bajo un ciclo real la memo
  depende del camino de la primera pasada. `integridad.revisar` no reporta ciclos (`calidad_cruce="ciclo"`).

**Capa de datos (paridad/latentes):**
- `apus_db.py:185-218` vs `pg/apus_pg.py:159-193` — búsqueda de APUs usa `LIKE` (SQLite) vs `ILIKE`
  (PG) sobre columnas sin normalizar → resultados distintos con acentos. Adoptar `nombre_norm` como insumos.
- `apus_db.py:63-69` (`INSERT OR REPLACE`) vs `pg/apus_pg.py:32-40` (`ON CONFLICT DO UPDATE`) — divergen
  al re-insertar un `(codigo,shift)` con componentes (latente; seed siempre resetea primero).
- `precios_db.py:124-132` / `precios_pg.py:94-103` — sin índice único parcial `(insumo_id) WHERE
  vigente=1`: dos ediciones concurrentes del mismo insumo pueden dejar dos filas vigentes → duplicados
  en los `LEFT JOIN`. Afecta a ambos backends.
- `servicio/insumos.py:51`, `autoria.py:121-157`, `usuarios.py:41-44` — el `antes` de auditoría se lee
  fuera de la tx (TOCTOU de fidelidad del log, no de datos).

**Seguridad (bajo impacto / auth-gated):**
- Zip-bomb vía xlsx: `rutas.py` → `openpyxl.load_workbook` — el tope de 15 MB es sobre el comprimido;
  un `sharedStrings.xml` crafteado infla a GBs → OOM. Requiere rol `editor` (trust-bounded).
- Paginación sin tope: `rutas.py` `/auditoria`, `/insumos`, `/apus` pasan `limit` sin clamp → un
  autenticado pide `limit=100000000`. Acotar (p. ej. 500).
- `auth.py:82-90` — el bootstrap admin confía en el claim `email`; la seguridad depende de que Supabase
  esté en invite-only / email confirmado. Verificar config y/o exigir `email_verified`.
- `config.py:163-165` — `docs_enabled()` default `true`; prod seguro por `render.yaml`, pero un deploy
  que olvide/escriba mal la var reexpone `/docs`. Default a `false`.
- `Dockerfile:25` deja `WEB_CONCURRENCY=2` (render.yaml lo baja a 1) → limiter ×2 fuera de Render.
- 500 que escapa por `ServerErrorMiddleware` sale sin cabeceras de seguridad (límite de Starlette,
  documentado; cuerpo genérico sin fuga).

**Frontend (UX/robustez):**
- `client.ts:25-45` — `.json()` sobre respuestas potencialmente vacías (204) → toast de error en una
  acción que sí funcionó (`cambiarRol`/`cambiarEstado`/`congelar`/`activar`).
- `moneda.ts:1-3` — `Math.round(n ?? 0)` no protege `NaN` → imprime `$NaN`.
- `TablaInsumos.tsx:166-169` — no se puede blanquear el precio (`parseFloat("")=NaN` se descarta; queda
  el valor viejo mientras el campo se ve vacío).
- `corridaTabla.ts:120-123` — `hayFiltrosActivos` compara `JSON.stringify` (frágil al orden de claves).
- `corridas.ts:61-81` — `descargarCuadro` duplica `descargarArchivo` (`client.ts:66-85`) (drift, no bug).

**Config/repo:**
- `.claude/settings.json` commiteado — filtra usuario/paths locales (Windows). No es secreto.
- `ejemplos/licitacion_ejemplo.xlsx` commiteado con descripciones reales de la licitación IDU y una
  columna `PRECIO CONTRACTUAL` poblada (los contractuales IDU son públicos; no viola Invariante #1).
  Considerar datos sintéticos.

---

## Por diseño (no bug, pero conviene tenerlo presente)

- **Corrida compartida sin dueño:** `DELETE/confirmar/congelar/activar` de corrida exigen solo rol
  `consulta` y `CorridaMeta` no tiene dueño; cualquier autenticado ve y puede borrar/modificar las
  corridas de cualquiera (modelo de equipo intencional, pero una cuenta base comprometida puede borrar
  todo el set de corridas).
- **`assert_no_money` es blocklist por nombre de clave**, no escáner de valores: dinero en texto libre
  o bajo una clave inocua no se detectaría. Se sostiene porque los builders nunca meten dinero.

---

## Recomendación de orden de arreglo

1. **CR-1, CR-2, IM-1** — el cuadro entregable subvalúa el costo en silencio → riesgo de underbid.
   El fix transversal más valioso: hacer que un insumo/sub-APU/turno **sin resolver** sea una condición
   **visible en el RESUMEN** (nunca un $0 mudo) y/o bloquee la emisión del cuadro.
2. **CR-3** — corrupción silenciosa de la base de precios; limpiar `dirty` al cambiar de página/filtro
   o snapshotear precio+fuente originales al editar; el backend debería exigir ambos campos, no aceptar
   `precio=0`/`fuente=""` por omisión.
3. **IM-2, IM-3, IM-5** — integridad: congelada realmente inmutable, carrera de último admin, migraciones
   como fuente de verdad.
4. **IM-4, IM-6** — evasión de rate-limit y expulsión de usuarios válidos.
5. **IM-7** y MENORES según convenga.
