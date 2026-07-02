# Diseño — Plan B: 8 Important + Minors de la auditoría

**Fecha:** 2026-07-02
**Rama:** `fix/auditoria-important` (desde `master`; Plan A + fix executemany ya fusionados)
**Estado:** aprobado en brainstorming; pendiente plan de implementación.
**Origen:** `docs/auditoria-codigo-2026-07-01.md`; memoria de hallazgos.

## 1. Contexto y principio

Los 3 Critical y el bug `executemany` del backend Postgres ya están arreglados y fusionados. Quedan
los **8 Important** + **Minors** de la auditoría. Un solo plan, TDD por bug (reproducir primero), fixes
duales verificados en CI (`postgres:17`), invariante #1 intacta.

**Restricciones:** NO tocar `apu_tool/dominio/privacy.py`, `apu_tool/dominio/ai_assist.py`, vistas
`DePriced*`. CERO regresiones (255 backend + 19 vitest) + AÑADIR tests. Español. Ejecución con
subagentes. Disciplina de commit estricta. Frontend con vitest + `npm run build`. Postgres se valida en CI.

## 2. Backend — correctitud

### I1 — TOCTOU del último admin → UPDATE condicional atómico
`apu_tool/servicio/usuarios.py::_proteger_ultimo_admin` lee el conteo fuera de la transacción del
`UPDATE`, así que dos degradaciones/desactivaciones concurrentes dejan 0 admins. **Fix:** un **UPDATE
condicional atómico** (una sola sentencia, sin race, idéntico en ambos backends):
```sql
UPDATE perfiles SET rol=? WHERE user_id=? AND NOT
  (rol='admin' AND estado='activo' AND
   (SELECT COUNT(*) FROM perfiles WHERE rol='admin' AND estado='activo') <= 1)
```
(análogo para `set_estado` a 'inactivo'). Nuevos métodos de repo `set_rol_protegido(user_id, rol, conn) ->
bool` y `set_estado_protegido(user_id, estado, conn) -> bool` (dual: perfiles_db/perfiles_pg) que
devuelven si el UPDATE aplicó (rowcount>0). `usuarios.cambiar_rol`/`cambiar_estado` usan estos métodos
dentro de `alm.transaccion("seguridad")` (+ auditoría, que ya está) y, si no aplicó y el usuario existe,
lanzan el mismo `ValueError` del guardrail. Se retira el `_proteger_ultimo_admin` de solo-lectura (o se
deja solo para degradaciones que no son a admin donde no hay riesgo — mejor: unificar en el UPDATE
guardado). **Test:** los tests de guardrail actuales siguen verdes (último admin no se degrada; con 2
admins sí); nuevo test de nivel repo: `set_rol_protegido` devuelve False y no cambia nada cuando sería el
último admin. La ausencia de race es por construcción (una sola sentencia).

### I2 — bootstrap admin sin auditar
`apu_tool/servicio/auth.py::resolver_perfil` (rama bootstrap) hace `alm.perfiles.upsert(nuevo)` sin
transacción ni auditoría. **Fix:** envolver en `alm.transaccion("seguridad")` +
`registrar_auditoria(alm, conn, None, "usuario.bootstrap_admin", "usuario", user_id, antes=None,
despues={email, rol:"admin", estado:"activo"})`. `actor=None` → `rol="sistema"`. Import de
`servicio/auditoria` en `auth.py` (sin ciclo — verificado). **Test:** bootstrap crea el admin y deja una
fila `usuario.bootstrap_admin` en auditoría (SQLite).

### I6 — migrate-pg no idempotente
`apu_tool/datos/migracion_pg.py::migrar_catalogo` usa `INSERT` plano; re-correr choca `UNIQUE`/PK.
**Fix:** `INSERT ... ON CONFLICT DO NOTHING` en insumos, insumo_precios, apus, apu_componentes
(conservando `OVERRIDING SYSTEM VALUE` y `_resync_identity`; meta ya hace upsert). **Test (CI Postgres):**
correr `migrar_catalogo` dos veces → sin excepción, conteos estables e iguales a origen.

## 3. Backend — endurecimiento

### I7 — bypass del límite de subida (sin Content-Length)
`apu_tool/servicio/limites.py::LimiteSubida` solo mira `Content-Length`; un POST `chunked`/sin CL lo
salta y el cuerpo se bufferiza entero. **Fix:** en el middleware, para métodos con cuerpo (POST/PUT/PATCH)
sobre rutas `/api`, si **falta** `Content-Length` → **411 Length Required** (obliga a declarar tamaño; con
CL sigue el tope 413). **Test:** unit del `dispatch` con un request stub sin `content-length` y método POST
→ 411 (TestClient siempre pone CL, por eso se prueba el middleware directamente); y el caso con CL grande
sigue dando 413.

## 4. Frontend

### I3 — "Descargar cuadro" da 401
`web/src/pages/Corrida.tsx` usa `window.open(descargarCuadroUrl(id))` — navegación sin header Bearer.
**Fix:** `web/src/api/corridas.ts` gana `descargarCuadro(id)` que hace `fetch` con `authHeader()` (Bearer),
recibe el `Blob`, crea `URL.createObjectURL`, dispara un `<a download>` programático y revoca la URL;
`Corrida.tsx` la usa en vez de `window.open`. **Test vitest:** mock de fetch/`authHeader` → se llama con
`Authorization: Bearer` y se dispara la descarga (mock de `createObjectURL`/click).

### I4 — el visor de auditoría oculta filas de un lote
`web/src/pages/Auditoria.tsx` asume que las filas de un `lote_id` son contiguas; con `ORDER BY ts DESC`
multiusuario se intercalan → filas colapsadas desaparecen / expandidas quedan huérfanas. **Fix:** agrupar
por `lote_id` en un `Map` (preservando el orden de aparición del primer miembro) **antes** de renderizar,
y render por grupo. **Test vitest:** filas de un lote **no contiguas** (intercaladas con otros eventos) →
todas presentes y agrupadas bajo su cabecera.

### M3 — flag `noAutorizado` pisado por signOut
`web/src/lib/auth.tsx`: al rechazar (403 de `/api/yo`) se hace `signOut()`, que re-dispara
`onAuthStateChange` y re-pone `noAutorizado=false` → muestra `/login` en vez de "cuenta no autorizada".
**Fix:** no re-poner `noAutorizado=false` cuando el evento es la propia salida tras un 403 (guardar/loguear
el estado o no resetear si ya está en true). **Test vitest:** un 403 deja `noAutorizado=true` estable.

## 5. Docs / limpieza

### M1 — /docs y /openapi públicos
`create_app` expone `/docs`, `/redoc`, `/openapi.json` sin auth. **Fix:** desactivarlos en prod —
`FastAPI(docs_url=None, redoc_url=None, openapi_url=None)` cuando estén deshabilitados. Nueva
`config.docs_enabled() -> bool` basada en una **env explícita** `APU_DOCS_ENABLED` (default **true**, para
no afectar dev/tests/CI); `render.yaml` añade `APU_DOCS_ENABLED=false` para prod. (Se elige env explícita,
no acoplar a `db_backend`, para que la suite —que corre SQLite— no cambie de comportamiento.) **Test:** con
`APU_DOCS_ENABLED=false` (monkeypatch) `create_app` no expone `/openapi.json` (404); con default sí (los
tests actuales que usan `/openapi.json`, p.ej. `test_endurecimiento_headers`, siguen verdes).

### M4 — código muerto
Borrar `apu_tool/dominio/models.py` (copia obsoleta sin usar; verificado que nadie importa
`apu_tool.dominio.models`). **`_ALLOWED_NUMERIC_KEYS` en `privacy.py` NO se toca** (archivo de invariante
#1; la regla es no tocarlo). **Test:** la suite sigue verde tras borrar el módulo (no rompe imports).

### I8 + M2 + M5 + M6 + M7 — documentación (una tarea)
- **I8:** comentario en `Dockerfile` (junto a `--forwarded-allow-ips="*"`) + nota en `README` — se confía el
  XFF porque el único ingreso es el edge de Render; si se despliega con acceso directo, restringir.
- **M2:** nota (README/comentario en `limites.py`) — el rate-limit es in-memory por worker; con N workers el
  límite efectivo es ×N (mitigación de abuso, no cuota exacta).
- **M5:** nota — `db/pg/precios.sql` tiene `ON DELETE CASCADE` en `insumo_precios` que `db/precios.sql`
  (SQLite) no; hoy inocuo (nadie borra insumos); reconciliar si se añade borrado.
- **M6:** comentario en `auditoria_db.py` — el `INSERT INTO auditoria` sin calificar depende de que ninguna
  tabla de dominio se llame `auditoria`.
- **M7:** comentario en `usuarios.invitar` — si el upsert local falla tras crear el usuario en Supabase,
  queda un usuario Auth sin perfil (idempotente al re-invitar).

## 6. I5 — LIKE vs ILIKE (decisión: opción b)
Búsquedas divergen entre SQLite (`LIKE`, case-insensitive solo ASCII) y Postgres (`ILIKE`, Unicode) con
acentos. **Fix (opción b, aprobada):**
- **Insumos:** cambiar `list_insumos(q)`, `search_insumos`, `search_insumos_por_palabras` a buscar sobre la
  columna existente `nombre_norm` con el término normalizado por `apu_tool/nucleo/texto.normalizar` →
  idéntico y accent/case-insensitive en ambos backends. (El filtro por `codigo` se mantiene igual; los
  códigos no tienen problema de acentos.)
- **APUs:** se **documenta** la divergencia (no se añade `nombre_norm` a apus en este plan; queda como
  mejora futura). Nota en el código/README.
**Test (contrato dual):** buscar "hormigon"/"HORMIGÓN" sobre un insumo "HORMIGÓN" devuelve el mismo
resultado (lo encuentra) en SQLite y Postgres.

## 7. No romper + criterios de éxito

**No romper:** métodos nuevos/renombrados son aditivos; el comportamiento observable single-thread de
usuarios/búsqueda/descarga se preserva (o mejora). 255 backend + 19 vitest verdes + nuevos tests. Invariante
#1 intacta. El CI (Postgres) debe quedar verde (I1/I6/I5-insumos se validan ahí).

**Éxito:**
- I1: imposible dejar 0 admins ni con requests concurrentes (UPDATE atómico); guardrail conservado.
- I2: el bootstrap admin deja rastro en auditoría.
- I3: "Descargar cuadro" funciona con auth real (Bearer); I4: el visor agrupa lotes correctamente aunque
  las filas estén intercaladas; M3: mensaje de "no autorizado" correcto.
- I5: búsqueda de insumos idéntica y accent-insensitive en ambos backends.
- I6: `migrate-pg` re-ejecutable sin error.
- I7: subida sin Content-Length → 411; M1: docs ocultos en prod; M4: sin el módulo muerto.
- I8/M2/M5/M6/M7 documentados. Suite + CI verdes; invariante #1 intacta.

**Diferido:** `apus.nombre_norm` para paridad de búsqueda de APUs (I5-APUs); reconciliar el FK CASCADE
(M5); storage compartido para el rate-limit (M2).
