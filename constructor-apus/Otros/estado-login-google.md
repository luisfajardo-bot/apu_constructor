> Espejo automático — no editar aquí. Fuente: `docs/estado-login-google.md`

# Dónde quedó el login con Google

Fecha de este corte: 2026-08-12. Rama: **`feat/login-google`**, 11 commits sobre `bfd568b`.

**El código está completo y verde. La feature está bloqueada en permisos de las consolas
externas** (Google Cloud y el dashboard de Supabase), que no dependen de este repo.

Este documento existe porque el rastro de las revisiones vivía en `.superpowers/sdd/`, que
está en `.gitignore`: un `git clean` se lo llevaba. Lo que sigue es lo que hay que saber
para retomar sin releer nada más.

- Spec: `docs/superpowers/specs/2026-08-10-login-google-design.md`
- Plan: `docs/superpowers/plans/2026-08-10-login-google.md`
- Pasos manuales: `docs/runbook-login-google.md`

## Verificación en el último commit

`pytest 743 passed / 15 skipped` · `vitest 43 archivos / 187 tests` · `npm run build` OK.
El único warning es el preexistente de `slowapi`. Los 15 skips son los de Postgres (sin
`TEST_DATABASE_URL` en la máquina de desarrollo).

## Lo que falta, en orden

1. **Habilitar el provider de Google en Supabase** (Authentication → Sign In / Providers →
   desplegar Google → toggle + Client ID/Secret → **Save dentro de ese panel**). Al
   2026-08-12 **no está habilitado**; la pregunta directa lo confirma en 5 segundos:

   ```bash
   curl -s "https://<project-ref>.supabase.co/auth/v1/authorize?provider=google"
   ```

   Deshabilitado devuelve
   `{"code":400,"error_code":"validation_failed","msg":"Unsupported provider: provider is not enabled"}`.
   Habilitado devuelve un 302 hacia `accounts.google.com`.

2. **Crear el OAuth client en Google Cloud**, si no está: el único campo que tiene que ser
   exacto es el redirect URI `https://<project-ref>.supabase.co/auth/v1/callback`. Los
   *Authorized JavaScript origins* pueden quedar vacíos (este flujo no habla con Google
   desde el navegador).

3. **Los tres ajustes de Authentication** del runbook: *Confirm email* ON, confirmación de
   **cambio** de email ON, *Manual linking* OFF. De ellos depende que el correo sea un
   ancla de identidad confiable, que es sobre lo que se apoya la adopción.

4. **El paso que no se puede saltar: decodificar un access token real** y confirmar que
   trae `amr: [{"method": "oauth"}]` y/o `app_metadata.providers` con `"google"`. La guarda
   es **fail-closed**: si el token no trae ninguna de las dos señales, la adopción nunca
   corre y todo invitado que entre por Google queda en 403 sin pista, y **nada en el repo
   puede demostrar qué claims trae un token real**. El runbook trae la ruta exacta.

5. Recién entonces, merge a `master` (que auto-despliega) con aprobación explícita.

## Un hallazgo que puede cambiar la decisión

Con los **signups cerrados** —como este proyecto los declara
(`docs/superpowers/specs/2026-07-01-produccion-multiusuario-design.md:115-118`)— GoTrue
rechaza con *«Signups not allowed for this instance»* al invitado a quien le tocaría un
`user_id` nuevo, **antes** de llegar a este backend. O sea que con signups cerrados la
adopción por email sólo sirve para un caso residual: usuarios de Auth que **ya existen**
con un `user_id` distinto al guardado en `perfiles` — por ejemplo los que se borraron y
recrearon en la limpieza de duplicados de producción.

Vale la pena decidir eso antes de invertir tiempo en los pasos 1-3.

## Dos hallazgos de seguridad que valen más allá de esta feature

Los encontró la revisión adversarial y **ya están en producción hoy**, no los introduce
esta rama:

- **Desactivar un perfil NO revoca a nadie cuyo correo esté en `APU_ADMIN_EMAILS`.** El
  bootstrap dispara cuando no hay perfil *para ese `user_id`*, sin mirar por qué, así que
  le crea un perfil admin nuevo en el siguiente ingreso. Para revocar de verdad hay que
  sacar el correo de esa variable en Render **además** de desactivar el perfil. El
  corolario tranquilizador es el mismo hecho al revés: el dueño de la app no puede
  quedarse afuera por desactivar su perfil — salvo que quede **activo pero degradado**,
  caso en que la adopción gana y el bootstrap no corre.
- **El correo es un ancla más débil de lo que parece:** `updateUser({email})` lo cambia el
  propio usuario desde el navegador con la anon key. El bootstrap ya confiaba en ese claim
  antes de esta rama; lo que la rama hace es **ensanchar el radio**, de los 1-2 correos
  listados a toda la tabla `perfiles`. De ahí el ajuste 3 de arriba.

## El agujero que tuvo esta rama, para que no vuelva

La primera versión de la guarda leía `claims["user_metadata"]["email_verified"]`.
`user_metadata` es `auth.users.raw_user_meta_data`, y **lo escribe el propio usuario** con
`supabase.auth.updateUser({ data: {...} })` y la anon key pública: cualquiera podía
declararse verificado. Rompía un invariante ya auditado del repo (*«`user_metadata` nunca
usado para authz»*, `docs/auditoria-codigo-2026-07-01.md:125`).

Se arregló en `a1f9860` y se endureció en `206b129`: `identidad_verificada(claims)` exige
un proveedor confiable en `app_metadata` (sólo cambiable con la service_role) **y** estrecha
con `amr`, para que una cuenta con Google vinculado que entró por contraseña no cuente como
respaldada por Google. Hay un test con la matriz de 12 casos, incluido el del ataque.

**Si alguien vuelve a tocar `identidad_verificada`: no leas `user_metadata`.**

## Deuda menor que quedó anotada (nada bloquea el merge)

- La fila de auditoría `usuario.vincular_identidad` se escribe aunque el `UPDATE` mueva 0
  filas (alcanzable por carrera). Arreglo: releer **dentro** del `with`.
- `_METODOS_PROVEEDOR = {"oauth"}` acepta cualquier proveedor OAuth mientras el respaldo
  filtra por `google`: hoy da igual (sólo Google habilitado), pero habilitar otro proveedor
  en el dashboard amplía la puerta sin tocar código.
- `resolver_perfil` recibe el hecho en **dos** parámetros (`identidad_verificada: bool` +
  `senal_identidad: str|None`) que un caller podría pasar inconsistentes; colapsarlos en uno
  lo haría imposible.
- El parámetro `identidad_verificada` sombrea la función homónima del módulo: quien la llame
  dentro de `resolver_perfil` se lleva un `TypeError`.
- El error de OAuth que llega en el hash lo lee `Login.tsx`, pero el redirect va a
  `/corridas` y el `<Navigate to="/login">` de `RutaProtegida` descarta el hash: el arreglo
  sólo cubre el aterrizaje directo en `/login`. Upgrade: mover ese `useEffect` a `App`, que
  ya hospeda el `<Toaster/>`.
- No hay guard de paridad de firmas para los backends de **perfiles** (existe para precios,
  `tests/test_paridad_backends.py`). Hoy no hay drift y `test_perfiles_contrato.py` corre
  contra Postgres real en CI; el hueco es futuro.
- `web/vitest.config.ts` no setea `clearMocks`/`restoreMocks`, así que `Login.test.tsx`
  depende del orden (está documentado en el propio test).
- No hay test de `reasignar_user_id` contra un `nuevo` que ya exista como PK; se verificó a
  mano que revienta con `IntegrityError` sin corromper, y es inalcanzable desde el camino de
  la adopción.

## Incidente de proceso, por si se repite

Un agente revisor escribió sin querer en el **`data/seguridad.db` real** al verificar: pasó
la ruta como `str` y la condición `isinstance(precios_path, Path)` de
`apu_tool/datos/almacen.py:44-45` cayó al fallback, que usa la base por defecto. Se limpió a
mano. **Al ejecutar algo contra un `Almacen`, pasar `pathlib.Path` y un directorio
temporal.** Ese fallback silencioso es un pie de plomo que sigue ahí.
