# Auditoría de seguridad — Armador de APUs

**Fecha:** 2026-08-28
**Alcance:** código, cuentas, accesos, bases de datos, despliegue
**Rama:** `feat/distancias-transporte-proyecto`
**Método:** 5 auditorías paralelas (auth/RBAC, capa de datos, secretos/despliegue, superficie HTTP, diff de rama) + verificación directa de cada hallazgo crítico y alto leyendo el código fuente.

---

## Veredicto

La base del código es **sólida en lo que suele fallar**: cero inyección SQL en 357 llamadas a `execute`, verificación de JWT correcta, sin CORS permisivo, sin path traversal, sin XSS, y el historial de git limpio en 696 commits. La ingeniería defensiva está bien pensada.

El riesgo real está en otra parte: **una credencial de producción sin rotar en disco**, y **una capa de autorización mal calibrada** que le da al rol de solo-lectura poder de escritura y borrado sobre el corazón del negocio.

| Severidad | Cantidad |
|---|---|
| Crítico | 1 |
| Alto | 5 |
| Medio | 6 |
| Bajo | 9 |

---

## CRÍTICO

### C-1 · Contraseñas de superusuario de producción, en claro, sin rotar

`.env.bak` y `secretos-prod.dsn.txt` contienen contraseñas **reales y distintas entre sí** del usuario `postgres` de la Supabase de producción. Ese usuario **bypassea RLS por completo**: es root sobre catálogo, APUs, corridas, perfiles y auditoría.

Tres agravantes:

1. **`.env.bak` lleva un nombre que VS Code, direnv y compañía cargan solos.** Ése es exactamente el mecanismo del incidente anterior, cuando un pytest suelto escribió contra la Supabase real. El archivo dice "DESACTIVADA por seguridad 2026-07-02" — pero el valor sigue ahí, intacto.
2. **La clave nunca se rotó** tras ese incidente. La variable de entorno sí se sacó (verificado: `DATABASE_URL`, `TEST_DATABASE_URL` y `SUPABASE_SERVICE_ROLE_KEY` no están seteadas en ningún scope de Windows). Falta la otra mitad.
3. Hay **dos contraseñas distintas**, así que al menos una es histórica y no hay forma de saber cuál sigue viva sin probarla.

**Lo bueno:** ninguno de los dos archivos estuvo jamás en git. Verificado con `ls-files`, `--diff-filter=A` y pickaxe sobre las contraseñas mismas en todo el historial. La exposición es local, no pública.

**Remediación:** rotar el password en Supabase (Settings → Database → Reset database password); borrar `.env.bak`; sacar `secretos-prod.dsn.txt` del árbol del repo (gestor de contraseñas o Credential Manager, y que el script de migración lo pida por stdin).

---

## ALTO

### A-1 · El rol `consulta` puede crear, alterar y borrar corridas

14 endpoints que escriben, congelan, descongelan y borran corridas exigen solo `requiere_rol("consulta")` — el rol cuyo nombre significa literalmente solo-lectura. Verificado mapeando cada decorador contra su dependencia:

```
DELETE /corridas/{cid}                       → consulta   ✗
POST   /corridas/{cid}/items/borrar          → consulta   ✗
POST   /corridas/{cid}/activar               → consulta   ✗  rompe el snapshot inmutable
POST   /corridas/{cid}/items/{seq}/confirmar → consulta   ✗  cambia el costo
POST   /corridas/{cid}/renombrar             → editor     ✓
POST   /corridas/{cid}/mover                 → editor     ✓
```

Que **renombrar** exija `editor` pero **borrar** no, delata que es un descuido acumulado, no una decisión.

Un usuario recién invitado con el rol más bajo puede listar todos los ids con `GET /corridas`, borrar la corrida de cualquiera, descongelar un cuadro ya emitido al cliente, o vaciar una licitación entera. **El precio de costo de una licitación se puede alterar o destruir desde la cuenta con menos privilegios.**

**Remediación:** subir a `editor` los 10 verbos de escritura y borrado. Es una palabra por línea.

### A-2 · `GET /corridas/{cid}/cuadro` es un GET que muta estado

Verificado en `corridas.py:684-713`: llama `congelar()` (escribe snapshots de **todos** los ítems), `set_cuadro()` y `set_estado(cid, "finalizada")`. Accesible con rol `consulta`.

Un bucle `for cid in 1..N: GET /api/corridas/$cid/cuadro` finaliza en masa las corridas de todo el equipo, y cada llamada recostea la corrida completa. No es explotable por CSRF (el token va en `Authorization`, no en cookie), pero sí por prefetch o reintento del propio navegador.

**Remediación:** convertirlo en `POST` (o separar generación de descarga) y exigir `editor`.

### A-3 · El bootstrap de admin no exige identidad verificada

`auth.py:215`:

```python
if (email or "").strip().lower() in config.admin_emails():
    nuevo = Perfil(user_id=user_id, email=email, rol="admin", estado="activo", ...)
```

La adopción de perfil por email (`_adoptar_por_email`) **sí** exige `identidad_verificada(claims)` — proveedor externo confiable en `app_metadata` más `amr:oauth`. El bootstrap a admin **no exige nada**: basta un JWT firmado por Supabase cuyo claim `email` coincida con la lista.

La anon key está bakeada en el bundle y es pública por diseño. Si el signup público quedara habilitado con confirmación de correo apagada, alguien podría registrarse con la dirección de `APU_ADMIN_EMAILS` y el primer request a `/api/yo` lo insertaría como admin activo.

**Es condicional a la config del dashboard**, no explotable con los defaults de Supabase. Pero el código no tiene defensa propia: depende de un ajuste que no está versionado ni verificado al arrancar.

**Remediación:** exigir `identidad_verificada` también en el bootstrap (una línea) y vaciar `APU_ADMIN_EMAILS` en Render ahora que el admin ya existe. Confirmar en el dashboard que el signup público está deshabilitado.

### A-4 · El RLS de toda tabla nueva es un paso manual que nada verifica

Verificado: **`db/pg/*.sql` no contiene ni un solo `ROW LEVEL SECURITY`**. El boot (`Almacen.init_schema()`) aplica solo esos archivos, que crean las tablas desnudas. Los `ENABLE ROW LEVEL SECURITY` viven aparte en `supabase/migrations/` y se corren a mano en el SQL editor.

Resultado: **el repo no sabe si el RLS está puesto en producción**, y sus propios documentos se contradicen sobre `0005`. Ahora `0006` (las 3 tablas de esta rama) hereda el mismo problema. El único test verifica orden de creación, no cobertura — una tabla nueva sin migración RLS pasa CI en silencio.

5 de 15 tablas dependen de que un humano se acuerde: `lista_precios`, `carpeta`, `componente_transporte`, `proyecto_parametros`, `proyecto_ajuste`.

**Atenuante:** el backend conecta como `postgres` (bypassea RLS), así que el RBAC sigue funcionando; y ningún schema es `public`, así que PostgREST no los expone salvo que alguien los agregue a "Exposed schemas". El RLS es la red de seguridad si la anon key se usa directamente — defensa en profundidad, pero hoy depende de un toggle del dashboard.

**Remediación:** mover cada `ALTER TABLE ... ENABLE ROW LEVEL SECURITY` a `db/pg/*.sql`, justo tras su `CREATE TABLE`. Habilitar RLS sobre una tabla que ya lo tiene es un no-op, así que es idempotente y el paso manual desaparece. Unas 15 líneas.

### A-5 · El rate limit es evadible con un header

El `Dockerfile` usa `--forwarded-allow-ips="*"`, lo que pone al `ProxyHeadersMiddleware` de uvicorn en modo `always_trust`: toma el elemento **más a la izquierda** de `X-Forwarded-For`. Ese elemento lo pone el cliente — el proxy de Render *añade* al final, no reemplaza.

```
curl -H "X-Forwarded-For: 1.2.3.$RANDOM" ...   → cubeta de rate-limit nueva en cada request
```

Anula el `200/minute` global y el `3/minute` de `POST /usuarios/invitar`. El comentario del Dockerfile anticipa el riesgo pero lo descarta razonando que "el único ingreso es el edge de Render" — eso protege contra alcanzar el contenedor directamente, no contra un cliente que atraviesa el proxy prependiendo su propio XFF.

**Remediación:** para una API 100% autenticada, keyear por identidad en vez de IP; o fijar `--forwarded-allow-ips` a los CIDR de Render.

---

## MEDIO

| # | Hallazgo | Ubicación |
|---|---|---|
| M-1 | **Zip-bomb en las subidas .xlsx.** `read_only=True` hace streaming, pero `[list(r) for r in ...]` lo anula: todo queda en memoria. Sin tope de filas ni de tamaño descomprimido. Un .xlsx válido de 15 MB puede llevar ~5 GB de XML (deflate comprime 343:1 en filas repetidas). Con Render free (512 MB, 1 worker), **una petición tumba la instancia**. Afecta 6 endpoints. | `licitacion.py:77`, `autoria.py:417` |
| M-2 | **`TEST_DATABASE_URL` sin guard.** El guard autouse de `conftest.py` cubre `DATABASE_URL` y es efectivo, pero deja fuera `TEST_DATABASE_URL` — y esos tests hacen `DROP SCHEMA … CASCADE`. Un copy-paste del DSN de producción ahí **destruye la base**. Peor que el incidente original: destructivo, no aditivo. | `tests/conftest.py` |
| M-3 | **El contenedor corre como root.** Sin directiva `USER` en el Dockerfile. Una RCE da root en el contenedor. | `Dockerfile` |
| M-4 | **DoS no autenticado por refresco del JWKS.** `get_signing_key_from_jwt` corre *antes* de autenticar; un `kid` desconocido dispara un GET síncrono con `timeout=30`. Decenas de requests con `kid` aleatorio clavan el threadpool. Fix: `PyJWKClient(url, timeout=3)`. | `auth.py:48-57` |
| M-5 | **Default inseguro en `docs_enabled()`.** Devuelve `True` por defecto. Solo `render.yaml` apaga `/docs` en producción; si alguien borra esa variable, se publica el mapa completo de los 63 endpoints. | `config.py:218-220` |
| M-6 | **Lotes sin cota.** `ConfirmarLoteIn.seqs`, `BorrarLineasIn.seqs`, `CambiosIn.cambios` y `ClasificarIn.filas` son listas sin `max_length`, y `aplicar_cambios` abre una transacción por elemento. `AgregarLineasIn` sí está acotado a 100 — la cota se pensó pero no se generalizó. | `esquemas.py` |

---

## BAJO

- `limit`/`offset` sin cota en `GET /auditoria` (`rutas.py:99`), mientras el hermano en `:499` sí usa `Query(ge=1, le=500)`.
- Tokens en `localStorage`: sin sinks de XSS hoy, pero convierte un XSS futuro en persistencia de sesión.
- CSP con `style-src 'unsafe-inline'`; faltan `form-action` y `Permissions-Policy`.
- Los 500 salen sin cabeceras de seguridad (límite de Starlette, ya documentado en `app.py`).
- El 401 filtra el texto interno de la excepción de PyJWT.
- El catch-all de la SPA responde 200 a `/api/*` inexistente en vez de 404.
- `sub` no está en los claims requeridos del JWT.
- `search_apus` mete comodines LIKE sin escapar — **código muerto**, solo lo llama un test. Bórralo.
- Faltan constraints `CHECK` de enum en 6 columnas (`perfiles` sí los tiene; `componente_transporte.categoria` es el que más importa).
- Workflow de CI sin bloque `permissions` (no usa secretos ni `pull_request_target`, así que no hay exposición).
- `.dockerignore` no excluye el DSN ni los `.xlsx` de la raíz.
- Sin escaneo de secretos en CI.

---

## Un defecto en la invariante #1

`assert_no_money` valida **solo nombres de clave** contra una denylist fija, aunque su propio docstring promete verificar "que no contengan ningún número que pueda ser dinero". Y `_ALLOWED_NUMERIC_KEYS` (`privacy.py:32`) es **código muerto**: no se usa en ninguna parte del proyecto.

Consecuencia: un campo monetario con un nombre nuevo (`tarifa`, `importe`, `subtotal`, `vr_unitario`) llegaría a la IA sin que nada lo detecte. El commit `feat(privacidad): peaje_valor nunca llega a la IA` es la prueba: hubo que agregar `peaje_valor` a mano porque `valor` no lo cubría. Cada campo monetario nuevo es una carrera contra el olvido.

No es explotable por un atacante — es una debilidad estructural de la barrera que protege el dato más sensible del negocio.

---

## Lo que está bien y no conviene tocar

- **Cero inyección SQL.** Revisados los 16 archivos de persistencia; los f-strings interpolan únicamente nombres de tabla de tuplas literales y placeholders `?` generados por `len()`. La causa raíz es estructural: **no hay una sola sentencia SQL fuera de `apu_tool/datos/`**. La convención del proyecto es lo que está protegiendo.
- **Verificación de JWT correcta:** `algorithms=["ES256","RS256"]` (sin `none`, sin confusión HS256), `aud`+`iss`+`exp` requeridos, JWKS construido server-side desde env — nunca desde el `jku` del token.
- **La lógica de identidad Google está bien pensada.** Usa solo claims que el usuario no puede escribir, y **nunca** `user_metadata` — que es exactamente el error que uno espera encontrar ahí. `amr` estrecha la señal en vez de sustituirla, y `_adoptar_por_email` falla cerrada ante carreras.
- **Guard de último admin sin TOCTOU:** la condición va dentro del propio `UPDATE`, no en un `if` previo.
- **Sin CORS** (same-origin puro), sin `dangerouslySetInnerHTML` ni `eval` en todo `web/src/`, sin stack traces al cliente, límite de subida evaluado *antes* de leer el cuerpo.
- **Path traversal verificado y descartado:** `Path(nombre).suffix` opera sobre el último componente, así que el sufijo no puede contener separador en ninguna plataforma.
- **Git impecable:** ningún secreto en 696 commits.
- **El diff de esta rama está limpio.** Los 9 endpoints nuevos declaran el mismo rol que sus equivalentes preexistentes, las 10 consultas nuevas están parametrizadas y `0006` cubre las 3 tablas nuevas en deny-all.

---

## Un dato de arquitectura que cambia la lectura

**El modelo de datos no es multi-tenant.** `CorridaMeta` no tiene dueño; `creado_por` en `Carpeta` y `ListaPrecios` solo se escribe y se muestra — **nunca aparece en un `WHERE`**. Cualquier `corrida_id`, `carpeta_id` o `lista_id` es accesible por cualquier usuario autenticado, y `GET /corridas` los enumera todos.

Eso no es un bug: es un workspace único de empresa, y es defendible mientras todos los invitados sean del mismo equipo. Pero significa que **el rol es la única barrera que existe** — y por eso A-1 pesa el doble de lo que parece.

---

## Orden de remediación

1. **Rotar el password de la base** y borrar `.env.bak` (C-1). Es lo único con exposición viva.
2. **`consulta` → `editor`** en los 10 endpoints de escritura de corridas y en `/cuadro` (A-1, A-2). Diff de una palabra por línea, el mayor retorno del informe.
3. **Guard de `TEST_DATABASE_URL`** en `conftest.py` (M-2). Tres líneas contra un `DROP SCHEMA` sobre producción.
4. **Mover los `ENABLE ROW LEVEL SECURITY` a `db/pg/*.sql`** (A-4). Elimina el paso manual para siempre, incluido el de esta rama.
5. **`identidad_verificada` en el bootstrap admin** y vaciar `APU_ADMIN_EMAILS` (A-3).
6. Guard de zip-bomb, `USER app`, `PyJWKClient(timeout=3)`, cotas de lote (M-1, M-3, M-4, M-6).

**Dos avisos sobre el paso 1:** rotar el password de la base **no** rota la llave de firma JWT, así que no dispara el bucle de login que ya ocurrió una vez. Pero sí hay que actualizar `DATABASE_URL` en Render, y el servicio se reinicia al hacerlo.

---

*Nada de esto fue implementado — el informe es solo diagnóstico. Los hallazgos críticos y altos se verificaron leyendo el código fuente directamente, no solo el diff.*
